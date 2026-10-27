/* 20-live-collab/01_live_collab.js — Google-Docs-style editing between the
   people who have the same project file open.
 *
 * The browser runs a Yjs document for the project's text fields. Local text
 * edits become small CRDT updates; the server assigns them one order in the
 * live-session tables and every other client applies them on its next poll.
 * Presence travels with the same poll, so a caret and a name show where the
 * other person is typing.
 *
 * This is not an autosave: the project draft row is written only by the
 * explicit save button. The session state is stored separately and survives
 * a closed tab, so live work is never lost just because nobody saved yet.
 *
 * Transport is short polling because the hosting account cannot keep a
 * socket open. Polling runs only while the project page is visible, at a
 * slower cadence when the tab is idle.
 */

const LIVE_COLLAB_ACTIVE_POLL_MS = 800;
const LIVE_COLLAB_IDLE_POLL_MS = 4000;
const LIVE_COLLAB_IDLE_AFTER_MS = 120000;
const LIVE_COLLAB_FLUSH_MS = 350;
const LIVE_COLLAB_HEARTBEAT_MS = 3000;
const LIVE_COLLAB_SNAPSHOT_MS = 90000;
const LIVE_COLLAB_SNAPSHOT_UPDATES = 120;
const LIVE_COLLAB_PRESENCE_TTL_MS = 20000;
// The server drops a presence row after 20 seconds. An open tab therefore has
// to repeat "still here" while the person reads or thinks instead of typing,
// or they vanish from the others' screen mid-session.
const LIVE_COLLAB_PRESENCE_HEARTBEAT_MS = 10000;

let liveCollabSession = null;
let liveCollabClientIdValue = '';

function liveCollabEnabled() {
  return typeof Y !== 'undefined' && Y && typeof Y.Doc === 'function';
}

// One identity per open page. This used to be kept in sessionStorage, but a
// duplicated tab inherits that storage: both tabs then carried the same id,
// presence excludes the caller by that id, and two windows of one account
// could never see each other.
function liveCollabClientId() {
  if (liveCollabClientIdValue) return liveCollabClientIdValue;
  liveCollabClientIdValue = (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : ('client-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10));
  return liveCollabClientIdValue;
}

function liveCollabBytesToBase64(bytes) {
  let binary = '';
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function liveCollabBase64ToBytes(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

// One diff for a text control: keep the common prefix and suffix, replace the
// middle. It is the same transform for typing, paste, cut and undo.
function liveApplyTextDiff(text, value, origin) {
  if (!text || typeof text.toString !== 'function') return false;
  const current = text.toString();
  if (current === value) return false;
  let start = 0;
  const shortest = Math.min(current.length, value.length);
  while (start < shortest && current[start] === value[start]) start += 1;
  let endCurrent = current.length;
  let endValue = value.length;
  while (endCurrent > start && endValue > start
    && current[endCurrent - 1] === value[endValue - 1]) {
    endCurrent -= 1;
    endValue -= 1;
  }
  const apply = () => {
    if (endCurrent > start) text.delete(start, endCurrent - start);
    if (endValue > start) text.insert(start, value.slice(start, endValue));
  };
  if (text.doc && typeof text.doc.transact === 'function') {
    text.doc.transact(apply, origin);
  } else {
    apply();
  }
  return true;
}

// A caret inside a region that changed moves to the end of the new region;
// before it stays put and after it shifts by the length difference.
function liveTransformCaretByChange(oldValue, newValue, caret) {
  const index = Math.max(0, Math.min(Number(caret) || 0, oldValue.length));
  if (oldValue === newValue) return index;
  let start = 0;
  const shortest = Math.min(oldValue.length, newValue.length);
  while (start < shortest && oldValue[start] === newValue[start]) start += 1;
  let endOld = oldValue.length;
  let endNew = newValue.length;
  while (endOld > start && endNew > start
    && oldValue[endOld - 1] === newValue[endNew - 1]) {
    endOld -= 1;
    endNew -= 1;
  }
  if (index <= start) return index;
  if (index >= endOld) return Math.max(0, index + (endNew - endOld));
  return endNew;
}

function startLiveCollaboration(draftId) {
  if (!draftId || !liveCollabEnabled()) return;
  if (liveCollabSession && liveCollabSession.draftId === draftId && !liveCollabSession.stopped) {
    liveCollabBindFields();
    liveCollabSchedulePoll(0);
    return;
  }
  stopLiveCollaboration();
  const doc = new Y.Doc();
  const session = {
    draftId: String(draftId),
    doc,
    fields: doc.getMap('fields'),
    clientId: liveCollabClientId(),
    bindings: new Map(),
    pending: [],
    deferredRemote: null,
    composing: null,
    localFieldKey: '',
    localOrigin: { liveCollab: 'local' },
    remoteOrigin: { liveCollab: 'remote' },
    applyingRemote: false,
    lastSeq: 0,
    presence: [],
    presenceSignature: '',
    lastActivityAt: Date.now(),
    lastPresenceSentAt: 0,
    lastSnapshotAt: 0,
    localUpdateCount: 0,
    pollTimer: null,
    flushTimer: null,
    presenceTimer: null,
    pollInFlight: false,
    flushing: false,
    flushAgain: false,
    stopped: false,
    listeners: null,
  };
  liveCollabSession = session;
  doc.on('update', (update, origin) => {
    if (origin === session.remoteOrigin) return;
    session.pending.push({
      payload: liveCollabBytesToBase64(update),
      fieldKey: session.localFieldKey || '',
    });
    session.localUpdateCount += 1;
    liveCollabScheduleFlush();
  });
  session.listeners = liveCollabInstallListeners(session);
  liveCollabLoadInitialState(session);
}

function stopLiveCollaboration() {
  const session = liveCollabSession;
  if (!session) return;
  session.stopped = true;
  clearTimeout(session.pollTimer);
  clearTimeout(session.flushTimer);
  clearTimeout(session.presenceTimer);
  session.pollTimer = null;
  session.flushTimer = null;
  session.presenceTimer = null;
  if (session.listeners) {
    session.listeners.forEach(item => {
      try { item.target.removeEventListener(item.type, item.handler, item.options); } catch (e) {}
    });
  }
  document.querySelectorAll('.live-caret-overlay').forEach(node => node.remove());
  document.querySelectorAll('.live-field-collaborator').forEach(node => {
    node.classList.remove('live-field-collaborator');
    if (node.style && node.style.removeProperty) node.style.removeProperty('--collab-tint');
  });
  const rail = document.getElementById('liveCollabPresenceRail');
  if (rail) rail.remove();
  try {
    if (session.draftId && session.clientId && typeof api === 'function') {
      api('POST', '/api/project-draft/' + encodeURIComponent(session.draftId) + '/live/leave', {
        clientId: session.clientId
      }).catch(() => {});
    }
  } catch (e) {}
  try { session.doc.destroy(); } catch (e) {}
  liveCollabSession = null;
}

function liveCollabLivePath(session) {
  return '/api/project-draft/' + encodeURIComponent(session.draftId) + '/live';
}

async function liveCollabLoadInitialState(session) {
  try {
    const resp = await api('GET', liveCollabLivePath(session) + '?since=0&clientId='
      + encodeURIComponent(session.clientId));
    if (!resp || !resp.success) {
      liveCollabBindFields();
      liveCollabSchedulePoll(LIVE_COLLAB_ACTIVE_POLL_MS);
      return;
    }
    if (resp.hasSession) {
      if (resp.reset && resp.snapshot) {
        try {
          Y.applyUpdate(session.doc, liveCollabBase64ToBytes(resp.snapshot), session.remoteOrigin);
        } catch (e) { /* a corrupt snapshot is skipped, polling still works */ }
      }
      (resp.updates || []).forEach(update => {
        try {
          Y.applyUpdate(session.doc, liveCollabBase64ToBytes(update.payload), session.remoteOrigin);
        } catch (e) { /* one bad update must not stop the rest */ }
      });
      session.lastSeq = Number(resp.seq) || 0;
    }
    liveCollabBindFields();
    liveCollabApplySessionToForm({ markDirty: Boolean(resp.hasSession) });
    liveCollabRenderPresence(resp.presence || []);
  } catch (e) {
    liveCollabBindFields();
  }
  // Announce this tab at once: "who has the file open" must not wait for the
  // first keystroke.
  liveCollabFlush(true);
  liveCollabSchedulePoll(LIVE_COLLAB_ACTIVE_POLL_MS);
}

function liveCollabFieldEligible(input) {
  if (!input || !input.dataset || !input.dataset.key) return false;
  const tag = (input.tagName || '').toUpperCase();
  if (tag === 'TEXTAREA') return true;
  if (tag !== 'INPUT') return false;
  const type = (input.type || 'text').toLowerCase();
  return ['text', 'search', 'url', 'email', 'tel'].indexOf(type) >= 0;
}

function liveCollabFieldLocked(input) {
  if (!input) return true;
  if (input.disabled || input.readOnly) return true;
  const section = typeof input.closest === 'function' ? input.closest('.tenant-form-section') : null;
  return Boolean(section && section.classList && section.classList.contains('section-locked'));
}

function liveCollabBindFields() {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  const form = document.getElementById('tenantProjectForm');
  if (!form || !form.querySelectorAll) return;
  const seen = new Set();
  form.querySelectorAll('[data-key]').forEach(input => {
    if (!liveCollabFieldEligible(input) || liveCollabFieldLocked(input)) return;
    const key = input.dataset.key;
    if (!key) return;
    seen.add(key);
    const existing = session.bindings.get(key);
    if (existing && existing.input === input) return;
    if (existing && existing.observer) {
      try { existing.text.unobserve(existing.observer); } catch (e) {}
    }
    let text = session.fields.get(key);
    if (!(text instanceof Y.Text)) {
      text = new Y.Text();
      session.localFieldKey = key;
      try {
        if (input.value) text.insert(0, input.value);
        session.fields.set(key, text);
      } finally {
        session.localFieldKey = '';
      }
    }
    const observer = (event, transaction) => {
      if (transaction.origin === session.localOrigin) return;
      if (liveCollabFieldLocked(input)) return;
      const value = text.toString();
      if (session.composing === input) {
        session.deferredRemote = { input, text };
        return;
      }
      if (input.value === value) return;
      liveCollabApplyRemoteValue(input, value);
    };
    text.observe(observer);
    session.bindings.set(key, { input, text, observer });
    if (input.value !== text.toString()) {
      // A rebuilt form starts empty: put the live value back and let the
      // app's listeners react without feeding it back into the CRDT.
      liveCollabSetInputValue(input, text.toString(), true);
    }
  });
  // A field removed from the form keeps its Y.Text in the document, so a
  // section that comes back does not lose its text.
  session.bindings.forEach((binding, key) => {
    if (!seen.has(key)) {
      try { binding.text.unobserve(binding.observer); } catch (e) {}
      session.bindings.delete(key);
    }
  });
}

function liveCollabSetInputValue(input, value, dispatchInput) {
  if (!input || input.value === value) return;
  input.value = value;
  if (dispatchInput) {
    const session = liveCollabSession;
    if (session) session.applyingRemote = true;
    try {
      input.dispatchEvent(new Event('input', { bubbles: true }));
    } catch (e) {
      // A detached input cannot notify its listeners.
    } finally {
      if (session) session.applyingRemote = false;
    }
  }
}

function liveCollabApplyRemoteValue(input, value) {
  const oldValue = input.value;
  const active = document.activeElement === input;
  const caret = active && typeof input.selectionStart === 'number' ? input.selectionStart : null;
  const selectionEnd = active && typeof input.selectionEnd === 'number' ? input.selectionEnd : null;
  // The value is written by the setter so the app's own listeners (financial
  // mirrors, dirty flag) see the remote edit, while the CRDT input handler is
  // suppressed by applyingRemote.
  liveCollabSetInputValue(input, value, true);
  if (active && caret !== null) {
    const nextStart = liveTransformCaretByChange(oldValue, value, caret);
    let nextEnd = selectionEnd === null ? nextStart
      : liveTransformCaretByChange(oldValue, value, selectionEnd);
    nextEnd = Math.max(nextStart, Math.min(nextEnd, value.length));
    try { input.setSelectionRange(nextStart, nextEnd); } catch (e) {}
  }
  input.classList.add('live-field-updated');
  setTimeout(() => { try { input.classList.remove('live-field-updated'); } catch (e) {} }, 900);
  if (typeof setDraftDirty === 'function') setDraftDirty(true);
}

function liveCollabApplySessionToForm(options = {}) {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  let changed = false;
  session.bindings.forEach(binding => {
    const value = binding.text.toString();
    if (binding.input.value !== value) {
      liveCollabSetInputValue(binding.input, value, true);
      changed = true;
    }
  });
  if (changed && options.markDirty && typeof setDraftDirty === 'function') {
    setDraftDirty(true);
  }
}

function liveCollabInstallListeners(session) {
  const listeners = [];
  const add = (target, type, handler, options) => {
    target.addEventListener(type, handler, options);
    listeners.push({ target, type, handler, options });
  };
  add(document, 'input', event => {
    const input = event.target;
    const current = liveCollabSession;
    if (!current || current !== session || current.applyingRemote) return;
    if (!input || !input.dataset || !input.dataset.key) return;
    if (liveCollabFieldLocked(input)) return;
    const binding = current.bindings.get(input.dataset.key);
    if (!binding || binding.input !== input) return;
    if (current.composing === input) return;
    current.lastActivityAt = Date.now();
    current.localFieldKey = input.dataset.key;
    try {
      liveApplyTextDiff(binding.text, input.value, current.localOrigin);
    } finally {
      current.localFieldKey = '';
    }
    liveCollabPresenceSoon();
  }, true);
  add(document, 'compositionstart', event => {
    const current = liveCollabSession;
    if (!current || current !== session) return;
    if (event.target && event.target.dataset && current.bindings.has(event.target.dataset.key)) {
      current.composing = event.target;
    }
  }, true);
  add(document, 'compositionend', event => {
    const current = liveCollabSession;
    if (!current || current !== session) return;
    const input = event.target;
    if (current.composing !== input) return;
    current.composing = null;
    const binding = input && input.dataset ? current.bindings.get(input.dataset.key) : null;
    if (binding && binding.input === input) {
      current.localFieldKey = input.dataset.key;
      try {
        liveApplyTextDiff(binding.text, input.value, current.localOrigin);
      } finally {
        current.localFieldKey = '';
      }
      if (current.deferredRemote && current.deferredRemote.input === input) {
        const remoteValue = current.deferredRemote.text.toString();
        current.deferredRemote = null;
        if (input.value !== remoteValue) liveCollabApplyRemoteValue(input, remoteValue);
      }
    }
    liveCollabPresenceSoon();
  }, true);
  add(document, 'focusin', event => {
    const current = liveCollabSession;
    if (!current || current !== session) return;
    current.lastActivityAt = Date.now();
    liveCollabPresenceSoon();
  }, true);
  add(document, 'selectionchange', () => {
    const current = liveCollabSession;
    if (!current || current !== session) return;
    const active = document.activeElement;
    if (!active || !active.dataset || !current.bindings.has(active.dataset.key)) return;
    current.lastActivityAt = Date.now();
    liveCollabPresenceSoon();
  });
  add(document, 'scroll', () => {
    const current = liveCollabSession;
    if (!current || current !== session) return;
    current.presenceSignature = '';
    liveCollabRenderCarets();
  }, true);
  if (typeof window !== 'undefined') {
    add(window, 'resize', () => {
      const current = liveCollabSession;
      if (!current || current !== session) return;
      current.presenceSignature = '';
      liveCollabRenderCarets();
    });
    add(window, 'beforeunload', () => {
      const current = liveCollabSession;
      if (!current || current !== session || !current.draftId || !current.clientId) return;
      try {
        const url = '/api/project-draft/' + encodeURIComponent(current.draftId) + '/live/leave';
        const payload = JSON.stringify({ clientId: current.clientId });
        if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
          navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }));
        }
      } catch (e) {}
    });
  }
  add(document, 'visibilitychange', () => {
    const current = liveCollabSession;
    if (!current || current !== session) return;
    if (document.visibilityState === 'visible') {
      liveCollabSchedulePoll(0);
    } else {
      clearTimeout(current.pollTimer);
      current.pollTimer = null;
    }
  });
  return listeners;
}

function liveCollabPresenceSoon() {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  if (session.presenceTimer) return;
  session.presenceTimer = setTimeout(() => {
    session.presenceTimer = null;
    liveCollabFlush(true);
  }, 250);
}

function liveCollabScheduleFlush() {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  clearTimeout(session.flushTimer);
  session.flushTimer = setTimeout(() => {
    session.flushTimer = null;
    liveCollabFlush(false);
  }, LIVE_COLLAB_FLUSH_MS);
}

// A field the person is working in, whether or not it carries a CRDT text.
// Numbers, dropdowns and dates are not live-synced (their value is not a text
// being typed), but "who is on this field" still has to be visible.
function liveCollabPresenceEligible(input) {
  if (!input || !input.dataset || !input.dataset.key) return false;
  const tag = (input.tagName || '').toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = (input.type || 'text').toLowerCase();
  return ['hidden', 'file', 'button', 'submit', 'reset', 'image'].indexOf(type) < 0;
}

function liveCollabCurrentPresence(session) {
  const active = typeof document !== 'undefined' ? document.activeElement : null;
  let fieldKey = '';
  let sectionKey = '';
  let caretStart = null;
  let caretEnd = null;
  if (active && session.bindings.has(active.dataset && active.dataset.key)) {
    fieldKey = active.dataset.key;
    caretStart = typeof active.selectionStart === 'number' ? active.selectionStart : null;
    caretEnd = typeof active.selectionEnd === 'number' ? active.selectionEnd : caretStart;
  } else if (liveCollabPresenceEligible(active)) {
    // The field is read by the form but has no text session (a number or a
    // dropdown): report it so the others see which field this person is on.
    fieldKey = active.dataset.key;
  }
  if (fieldKey && active && typeof active.closest === 'function') {
    const section = active.closest('.tenant-form-section');
    if (section && section.dataset) sectionKey = section.dataset.section || '';
  }
  return { fieldKey, sectionKey, caretStart, caretEnd };
}

// The visible name of the field, so the rail says what the person is working
// on instead of only which section they are in.
function liveCollabFieldLabel(fieldKey) {
  const key = String(fieldKey || '');
  if (!key || typeof document === 'undefined' || !document.querySelector) return '';
  let input = null;
  try {
    input = document.querySelector('#tenantProjectForm [data-key="'
      + key.replace(/["\\]/g, '') + '"]');
  } catch (e) {
    input = null;
  }
  if (!input || !input.parentElement || !input.parentElement.querySelector) return '';
  const label = input.parentElement.querySelector('label');
  const text = label && label.textContent ? String(label.textContent).trim() : '';
  return text.split('\n')[0].trim().slice(0, 60);
}

function liveCollabPresenceLine(item) {
  const name = String((item && item.user_name) || '').trim();
  if (!name) return '';
  const field = liveCollabFieldLabel(item.field_key || '');
  const section = field ? '' : liveCollabSectionLabel(item.section_key || '');
  return [name, field || section].filter(Boolean).join(' — ');
}

// While the tab is on screen, repeat the presence so a name does not expire
// just because its owner is reading. A hidden tab stops saying anything, which
// is what "who has the file open right now" should mean.
function liveCollabPresenceHeartbeatDue(session, now) {
  if (!session || session.stopped) return false;
  if (typeof document === 'undefined') return false;
  if (document.visibilityState === 'hidden') return false;
  return (Number(now) - (session.lastPresenceSentAt || 0)) >= LIVE_COLLAB_PRESENCE_HEARTBEAT_MS;
}

async function liveCollabFlush(forcePresence) {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  const now = Date.now();
  const presence = liveCollabCurrentPresence(session);
  const heartbeatDue = forcePresence
    || (now - session.lastPresenceSentAt) >= LIVE_COLLAB_HEARTBEAT_MS;
  if (session.flushing) {
    session.flushAgain = true;
    return;
  }
  let snapshot = null;
  if (session.pending.length === 0
      && session.lastSeq > 0
      && !session.pollInFlight
      && (now - session.lastSnapshotAt) >= LIVE_COLLAB_SNAPSHOT_MS
      && session.localUpdateCount > 0) {
    try {
      snapshot = {
        payload: liveCollabBytesToBase64(Y.encodeStateAsUpdate(session.doc)),
        seq: session.lastSeq,
      };
      session.lastSnapshotAt = now;
      session.localUpdateCount = 0;
    } catch (e) {
      snapshot = null;
    }
  }
  const allUpdates = session.pending.splice(0);
  const updates = allUpdates.slice(0, 64);
  if (allUpdates.length > updates.length) {
    // The server accepts 64 updates per request. The rest goes in the next
    // flush instead of being refused as one oversized batch.
    session.pending = allUpdates.slice(64).concat(session.pending);
    session.flushAgain = true;
  }
  const presenceOnly = !updates.length && !snapshot;
  if (presenceOnly && forcePresence
      && (now - (session.lastPresenceAttemptAt || 0)) < 800) return;
  if (!updates.length && !snapshot && !heartbeatDue) return;
  if (forcePresence) session.lastPresenceAttemptAt = now;
  session.flushing = true;
  try {
    const body = {
      clientId: session.clientId,
      updates,
      presence,
      baseRevision: Number(tenantDraftRevision) || 0,
    };
    if (snapshot) {
      body.snapshot = snapshot.payload;
      body.snapshotSeq = snapshot.seq;
    }
    const resp = await api('POST', liveCollabLivePath(session), body);
    if (!resp || !resp.success) {
      if (resp && resp.error_code === 'LIVE_FIELD_FORBIDDEN') {
        // The section was approved while it was being typed in: the server
        // refused the last batch, and retrying it would never succeed.
        if (snapshot) session.lastSnapshotAt = 0;
        return;
      }
      if (resp && resp.error_code === 'DRAFT_LOCKED') {
        // The project moved to a lifecycle state that refuses edits. The
        // session has nothing legal to send until it is unlocked again.
        stopLiveCollaboration();
        return;
      }
      // A failed batch stays queued for the next flush instead of losing text.
      if (updates.length) session.pending = updates.concat(session.pending);
      if (snapshot) session.lastSnapshotAt = 0;
      return;
    }
    session.lastPresenceSentAt = now;
    if (resp.baseRevision && Number(resp.baseRevision) > 0) {
      session.serverBaseRevision = Number(resp.baseRevision);
    }
  } catch (e) {
    if (updates.length) session.pending = updates.concat(session.pending);
    if (snapshot) session.lastSnapshotAt = 0;
  } finally {
    session.flushing = false;
    if (session.flushAgain) {
      session.flushAgain = false;
      liveCollabScheduleFlush();
    }
  }
}

function liveCollabSchedulePoll(delay) {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  clearTimeout(session.pollTimer);
  session.pollTimer = setTimeout(liveCollabPoll, Math.max(0, delay));
}

async function liveCollabPoll() {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  liveCollabBindFields();
  if (document.visibilityState === 'hidden') {
    session.pollTimer = null;
    return;
  }
  if (session.pollInFlight) {
    liveCollabSchedulePoll(200);
    return;
  }
  session.pollInFlight = true;
  let hasMore = false;
  try {
    const resp = await api('GET', liveCollabLivePath(session) + '?since='
      + encodeURIComponent(session.lastSeq) + '&clientId='
      + encodeURIComponent(session.clientId));
    if (resp && resp.success) {
      if (resp.reset && resp.snapshot) {
        try {
          Y.applyUpdate(session.doc, liveCollabBase64ToBytes(resp.snapshot), session.remoteOrigin);
        } catch (e) { /* keep the local document, polling continues */ }
      }
      (resp.updates || []).forEach(update => {
        try {
          Y.applyUpdate(session.doc, liveCollabBase64ToBytes(update.payload), session.remoteOrigin);
        } catch (e) { /* one bad update must not stop the rest */ }
      });
      const nextSeq = Number(resp.seq) || 0;
      if (nextSeq > session.lastSeq) session.lastSeq = nextSeq;
      hasMore = Boolean(resp.hasMore);
      liveCollabRenderPresence(resp.presence || []);
    }
  } catch (e) {
    // A poll that could not go through is retried on the next tick.
  } finally {
    session.pollInFlight = false;
  }
  if (session.stopped) return;
  if (liveCollabPresenceHeartbeatDue(session, Date.now())) {
    liveCollabFlush(true);
  }
  if (hasMore) {
    liveCollabSchedulePoll(50);
    return;
  }
  const idle = Date.now() - session.lastActivityAt > LIVE_COLLAB_IDLE_AFTER_MS;
  liveCollabSchedulePoll(idle ? LIVE_COLLAB_IDLE_POLL_MS : LIVE_COLLAB_ACTIVE_POLL_MS);
}

function liveCollabUserColor(name) {
  const palette = ['#17C8E3', '#0A829B', '#B8860B', '#7C3AED', '#DC2626', '#0F766E'];
  const value = String(name || '');
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0;
  }
  return palette[Math.abs(hash) % palette.length];
}

function liveCollabSectionLabel(sectionKey) {
  if (!sectionKey) return '';
  let element = null;
  if (typeof getProjectSectionElement === 'function') {
    try { element = getProjectSectionElement(sectionKey); } catch (e) { element = null; }
  }
  if (!element) {
    element = document.querySelector('#tenantProjectForm .tenant-form-section[data-section="'
      + String(sectionKey).replace(/"/g, '') + '"]');
  }
  if (!element) return sectionKey;
  const label = element.querySelector('.project-section-title-label');
  return label && label.textContent ? label.textContent.trim() : sectionKey;
}

function liveCollabHexToRgba(hex, alpha) {
  const clean = String(hex || '').replace('#', '');
  if (clean.length === 6) {
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    return 'rgba(' + r + ', ' + g + ', ' + b + ', ' + alpha + ')';
  }
  return 'rgba(23, 200, 227, ' + alpha + ')';
}

function liveCollabRenderPresence(entries) {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  session.presence = Array.isArray(entries) ? entries : [];
  const signature = JSON.stringify(session.presence.map(item => [
    item.user_name || '', item.field_key || '', item.section_key || '',
    item.caret_start, item.caret_end, item.updated_at || '',
  ]));
  session.presenceSignature = signature;
  liveCollabRenderRail(session.presence);
  liveCollabRenderCarets();
}

function liveCollabRenderRail(entries) {
  // Presence is rendered directly as field highlights with name badges (like Google Docs).
  // The bottom rail is never rendered — remove it if present in the DOM.
  const rail = typeof document !== 'undefined' && document.getElementById
    ? document.getElementById('liveCollabPresenceRail') : null;
  if (rail && rail.remove) rail.remove();
}

function liveCollabFindFieldInput(session, key) {
  if (session && session.bindings && session.bindings.has(key)) {
    const b = session.bindings.get(key);
    if (b && b.input && b.input.isConnected) return b.input;
  }
  if (typeof document === 'undefined' || !document.querySelector) return null;
  const safeKey = String(key || '').replace(/["\\]/g, '');
  if (!safeKey) return null;
  try {
    return document.querySelector('#tenantProjectForm [data-key="' + safeKey + '"]')
        || document.querySelector('[data-key="' + safeKey + '"]');
  } catch (e) {
    return null;
  }
}

function liveCollabGetTargetElement(input) {
  if (!input) return null;
  const isHidden = input.type === 'hidden' || (input.style && input.style.display === 'none');
  const isVisible = input.offsetParent !== null || (input.getClientRects && input.getClientRects().length > 0);
  if (!isHidden && isVisible) return input;
  if (typeof input.closest === 'function') {
    const card = input.closest('.tenant-field');
    if (card && (card.offsetParent !== null || (card.getClientRects && card.getClientRects().length > 0))) {
      return card;
    }
  }
  return isVisible ? input : null;
}

function liveCollabIsSelfActive(targetEl, entry) {
  if (typeof document === 'undefined') return false;
  const activeEl = document.activeElement;
  if (!activeEl || !targetEl) return false;
  const isFocused = (activeEl === targetEl || (targetEl.contains && targetEl.contains(activeEl)));
  if (!isFocused) return false;
  const myName = (typeof tenantUser !== 'undefined' && tenantUser && (tenantUser._userName || tenantUser.companyName)) || '';
  if (myName && entry && entry.user_name) {
    return String(entry.user_name).trim().toLowerCase() === String(myName).trim().toLowerCase();
  }
  return false;
}

function liveCollabRenderCarets() {
  const session = liveCollabSession;
  if (!session || session.stopped) return;
  if (typeof document === 'undefined') return;

  if (document.querySelectorAll) {
    document.querySelectorAll('.live-caret-overlay').forEach(node => node.remove());
    document.querySelectorAll('.live-field-collaborator').forEach(node => {
      node.classList.remove('live-field-collaborator');
      if (node.style && node.style.removeProperty) node.style.removeProperty('--collab-tint');
    });
  }

  const byField = {};
  session.presence.forEach(item => {
    const key = String(item.field_key || '');
    if (!key) return;
    if (!byField[key]) byField[key] = [];
    byField[key].push(item);
  });

  Object.keys(byField).forEach(key => {
    const rawInput = liveCollabFindFieldInput(session, key);
    if (!rawInput || !rawInput.isConnected) return;
    const targetEl = liveCollabGetTargetElement(rawInput);
    if (!targetEl || !targetEl.isConnected) return;

    // Filter out presence from self if currently focused on this exact field
    const entries = byField[key].filter(entry => !liveCollabIsSelfActive(targetEl, entry));
    if (!entries.length) return;

    liveCollabRenderFieldCarets(targetEl, entries);
  });
}

function liveCollabRenderFieldCarets(targetEl, entries) {
  const parent = targetEl.parentElement;
  if (!parent) return;
  const computed = typeof getComputedStyle === 'function' ? getComputedStyle(parent) : null;
  if (computed && computed.position === 'static') parent.style.position = 'relative';

  const targetRect = typeof targetEl.getBoundingClientRect === 'function'
    ? targetEl.getBoundingClientRect()
    : { left: 0, top: 0, width: 0, height: 0 };
  const parentRect = typeof parent.getBoundingClientRect === 'function'
    ? parent.getBoundingClientRect()
    : { left: 0, top: 0, width: 0, height: 0 };
  const left = targetRect.left - parentRect.left;
  const top = targetRect.top - parentRect.top;

  const layer = document.createElement('div');
  layer.className = 'live-caret-overlay';
  layer.style.left = left + 'px';
  layer.style.top = top + 'px';
  layer.style.width = targetRect.width + 'px';
  layer.style.height = targetRect.height + 'px';

  const primaryEntry = entries[0];
  const primaryColor = liveCollabUserColor(primaryEntry.user_name);
  if (layer.style && layer.style.setProperty) {
    layer.style.setProperty('--collab-color', primaryColor);
    layer.style.setProperty('--collab-glow', liveCollabHexToRgba(primaryColor, 0.18));
    layer.style.setProperty('--collab-tint', liveCollabHexToRgba(primaryColor, 0.04));
  }

  // Google-Docs style outline around the field
  const outline = document.createElement('div');
  outline.className = 'live-collab-field-outline';
  const targetRadius = typeof getComputedStyle === 'function' ? getComputedStyle(targetEl).borderRadius : '12px';
  if (targetRadius) outline.style.borderRadius = targetRadius;
  outline.style.borderColor = primaryColor;
  outline.style.boxShadow = '0 0 0 3px ' + liveCollabHexToRgba(primaryColor, 0.18);
  layer.appendChild(outline);

  // Subtle background tint on the input being edited
  if (targetEl.classList && targetEl.classList.add) {
    targetEl.classList.add('live-field-collaborator');
    if (targetEl.style && targetEl.style.setProperty) {
      targetEl.style.setProperty('--collab-tint', liveCollabHexToRgba(primaryColor, 0.04));
    }
  }

  // Google-Docs style collaborator name tag badge
  const badgeContainer = document.createElement('div');
  badgeContainer.className = 'live-collab-badge-container';
  const seenNames = new Set();
  entries.forEach(entry => {
    const name = String(entry.user_name || '').trim();
    if (!name || seenNames.has(name)) return;
    seenNames.add(name);
    const badge = document.createElement('span');
    badge.className = 'live-collab-badge';
    const userColor = liveCollabUserColor(name);
    badge.style.backgroundColor = userColor;
    badge.textContent = name;
    badgeContainer.appendChild(badge);
  });
  if (badgeContainer.hasChildNodes && badgeContainer.hasChildNodes()) {
    layer.appendChild(badgeContainer);
  }

  // Caret indicator inside text input / textarea
  const tag = (targetEl.tagName || '').toUpperCase();
  const isTextEl = tag === 'TEXTAREA' || (tag === 'INPUT' && ['text', 'search', 'url', 'email', 'tel'].indexOf((targetEl.type || 'text').toLowerCase()) >= 0);
  if (isTextEl) {
    entries.forEach(entry => {
      if (entry.caret_start === null || entry.caret_start === undefined) return;
      const index = Math.max(0, Math.min(Number(entry.caret_start) || 0, (targetEl.value || '').length));
      const point = liveCollabCaretPoint(targetEl, index);
      const caretLeft = point.left - targetEl.scrollLeft;
      const caretTop = point.top - targetEl.scrollTop;
      if (caretLeft < -5 || caretLeft > (targetEl.clientWidth || 0) + 5
          || caretTop < -5 || caretTop > (targetEl.clientHeight || 0) + 5) return;
      const caret = document.createElement('span');
      caret.className = 'live-caret';
      const userColor = liveCollabUserColor(entry.user_name);
      caret.style.backgroundColor = userColor;
      caret.style.left = caretLeft + 'px';
      caret.style.top = caretTop + 'px';
      layer.appendChild(caret);
    });
  }

  parent.appendChild(layer);
}

function liveCollabCaretPoint(input, index) {
  const mirror = document.createElement('div');
  const style = typeof getComputedStyle === 'function' ? getComputedStyle(input) : {};
  const properties = [
    'fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing',
    'lineHeight', 'textTransform', 'textIndent', 'paddingLeft', 'paddingRight',
    'paddingTop', 'paddingBottom', 'borderLeftWidth', 'borderRightWidth',
    'borderTopWidth', 'borderBottomWidth', 'boxSizing', 'wordSpacing',
    'direction', 'textAlign',
  ];
  properties.forEach(property => { mirror.style[property] = style[property]; });
  mirror.style.position = 'absolute';
  mirror.style.visibility = 'hidden';
  mirror.style.left = '-9999px';
  mirror.style.top = '0';
  mirror.style.width = (input.clientWidth || 0) + 'px';
  mirror.style.height = 'auto';
  mirror.style.boxSizing = 'border-box';
  mirror.style.whiteSpace = input.tagName === 'TEXTAREA' ? 'pre-wrap' : 'pre';
  mirror.style.overflowWrap = 'break-word';
  mirror.style.overflow = 'hidden';
  mirror.textContent = (input.value || '').slice(0, index);
  const marker = document.createElement('span');
  marker.textContent = '\u200b';
  mirror.appendChild(marker);
  if (document.body && document.body.appendChild) document.body.appendChild(mirror);
  const left = marker.offsetLeft + (input.clientLeft || 0);
  const top = marker.offsetTop + (input.clientTop || 0);
  if (mirror.remove) mirror.remove();
  return { left, top };
}

if (typeof window !== 'undefined') {
  window.startLiveCollaboration = startLiveCollaboration;
  window.stopLiveCollaboration = stopLiveCollaboration;
  window.liveApplySessionToForm = liveCollabApplySessionToForm;
}
