/* tests/workflow/test_live_collab.js — the CRDT half of live collaboration.
 *
 * The browser turns text edits into Yjs updates; the server never sees the
 * text itself. This harness loads the same vendored Yjs bundle the app ships,
 * applies two concurrent edits, and checks that both clients converge without
 * losing either character.
 *
 * Run from the repo root:  node tests/workflow/test_live_collab.js
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = process.cwd();
const vendor = fs.readFileSync(path.join(root, 'assets/vendor/yjs.min.js'), 'utf8');
const moduleSource = fs.readFileSync(
  path.join(root, 'assets/js/20-live-collab/01_live_collab.js'), 'utf8');

const hostEncoder = new TextEncoder();
const hostDecoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

// A page identity must never come from sessionStorage: a duplicated tab
// inherits that storage, so both tabs looked like one editor and neither could
// see the other. Touching it throws, and the client-id test fails loudly.
function throwingSessionStorage() {
  const refuse = () => {
    throw new Error('the live client id must not be kept in sessionStorage');
  };
  return { getItem: refuse, setItem: refuse, removeItem: refuse };
}

function stubDocument() {
  return {
    visibilityState: 'visible',
    activeElement: null,
    hasFocus: () => true,
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    createElement: () => ({ style: {}, appendChild() {}, classList: { add() {}, remove() {} } }),
    body: { appendChild() {} },
    addEventListener() {},
  };
}

const context = {
  console, setTimeout, clearTimeout, btoa, atob,
  window: {},
  sessionStorage: throwingSessionStorage(),
  document: stubDocument(),
  __hostEncode: value => Array.from(hostEncoder.encode(value)),
  __hostDecode: bytes => hostDecoder.decode(Uint8Array.from(bytes || [])),
  __hostRandom: length => Array.from(require('node:crypto').randomBytes(length)),
};
vm.createContext(context);
// The bundle runs in its own realm. Its instanceof checks compare against
// that realm's Uint8Array, so the text codec and the random source are
// created inside the realm and only call out to the host for the bytes.
vm.runInContext(`
  globalThis.TextEncoder = class {
    encode(value) {
      const bytes = __hostEncode(value);
      const out = new Uint8Array(bytes.length);
      for (let index = 0; index < bytes.length; index += 1) out[index] = bytes[index];
      return out;
    }
    encodeInto(value, destination) {
      const bytes = __hostEncode(value);
      const count = Math.min(bytes.length, destination.length);
      for (let index = 0; index < count; index += 1) destination[index] = bytes[index];
      return { read: value.length, written: count };
    }
  };
  globalThis.TextDecoder = class {
    decode(bytes) { return __hostDecode(Array.from(bytes || [])); }
  };
  globalThis.crypto = {
    subtle: {},
    getRandomValues(array) {
      const values = __hostRandom(array.length);
      for (let index = 0; index < array.length; index += 1) array[index] = values[index];
      return array;
    },
    randomUUID() {
      const bytes = __hostRandom(16);
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      const hex = bytes.map(byte => byte.toString(16).padStart(2, '0')).join('');
      return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-'
        + hex.slice(16, 20) + '-' + hex.slice(20);
    }
  };
`, context);
vm.runInContext(vendor, context);
assert.equal(typeof context.Y, 'object', 'the vendored Yjs bundle must expose the Y global');
vm.runInContext(moduleSource, context);

const Y = context.Y;

testRoundTripBytes();
testTextDiff();
testCaretTransform();
testFieldEligibility();
testConcurrentTypingConverges();
testClientIdIsPerPage();
testPresenceCoversEveryEditableField();
testPresenceFollowsTheFocusedField();
testPresenceHeartbeatWhileTheTabIsOpen();
testPresenceLineNamesTheField();
testPresenceIsWiredIntoTheLoops();
testGoogleDocsPresenceHighlight();
testSetLocalValueAndPreserveInputOnBind();
console.log('Live collaboration harness passed: bytes, diff, caret, field eligibility,'
  + ' concurrent typing, presence identity, field coverage, heartbeat, rail text, google docs highlight, local value preservation.');

function testRoundTripBytes() {
  const bytes = new Uint8Array([0, 1, 2, 250, 255]);
  const encoded = context.liveCollabBytesToBase64(bytes);
  const decoded = context.liveCollabBase64ToBytes(encoded);
  assert.deepEqual(Array.from(decoded), Array.from(bytes));
}

function testTextDiff() {
  const doc = new context.Y.Doc();
  const text = doc.getText('field');
  text.insert(0, 'hello');
  assert.equal(context.liveApplyTextDiff(text, 'hello world', 'local'), true);
  assert.equal(text.toString(), 'hello world');
  assert.equal(context.liveApplyTextDiff(text, 'hello', 'local'), true);
  assert.equal(text.toString(), 'hello');
  assert.equal(context.liveApplyTextDiff(text, 'hello', 'local'), false,
    'an unchanged value must not create an update');
  assert.equal(context.liveApplyTextDiff(text, 'أهلاً بالعالم', 'local'), true);
  assert.equal(text.toString(), 'أهلاً بالعالم');
}

function testCaretTransform() {
  assert.equal(context.liveTransformCaretByChange('hello world', 'hello', 8), 5);
  assert.equal(context.liveTransformCaretByChange('hello', 'hello world', 2), 2);
  assert.equal(context.liveTransformCaretByChange('abc', 'aXbc', 2), 3,
    'a caret after an insertion moves with the text');
  assert.equal(context.liveTransformCaretByChange('abc', 'ac', 2), 1,
    'a caret after a deletion moves back');
  assert.equal(context.liveTransformCaretByChange('abc', 'abc', 3), 3);
}

function testFieldEligibility() {
  assert.equal(context.liveCollabFieldEligible({ tagName: 'TEXTAREA', dataset: { key: 'a' } }), true);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'text', dataset: { key: 'a' } }), true);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'hidden', dataset: { key: 'a' } }), false);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'file', dataset: { key: 'a' } }), false);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'SELECT', dataset: { key: 'a' } }), false);
  assert.equal(context.liveCollabFieldEligible({ tagName: 'INPUT', type: 'text', dataset: {} }), false);
  assert.equal(context.liveCollabFieldLocked({ disabled: true }), true);
  assert.equal(context.liveCollabFieldLocked({ disabled: false, readOnly: true }), true);
  assert.equal(context.liveCollabFieldLocked({
    disabled: false,
    readOnly: false,
    closest: () => ({ classList: { contains: name => name === 'section-locked' } }),
  }), true);
  assert.equal(context.liveCollabFieldLocked({
    disabled: false,
    readOnly: false,
    closest: () => ({ classList: { contains: () => false } }),
  }), false);
}

function loadPageContext() {
  const page = {
    console, setTimeout, clearTimeout, btoa, atob, window: {},
    sessionStorage: throwingSessionStorage(),
    document: stubDocument(),
  };
  vm.createContext(page);
  vm.runInContext(moduleSource, page);
  return page;
}

function testClientIdIsPerPage() {
  const mine = context.liveCollabClientId();
  assert.equal(context.liveCollabClientId(), mine,
    'one page keeps one identity for as long as it is open');
  assert.match(mine, /^[A-Za-z0-9_-]{8,80}$/, 'the server only accepts this shape');
  const otherPage = loadPageContext();
  assert.notEqual(otherPage.liveCollabClientId(), mine,
    'a second tab of the same account is a different editor');
}

function testPresenceCoversEveryEditableField() {
  const field = (tagName, type, key) => ({ tagName, type, dataset: key ? { key } : {} });
  assert.equal(context.liveCollabPresenceEligible(field('INPUT', 'number', 'land_area')), true,
    'a financial figure belongs in "who is on this field"');
  assert.equal(context.liveCollabPresenceEligible(field('SELECT', undefined, 'project_type')), true);
  assert.equal(context.liveCollabPresenceEligible(field('TEXTAREA', undefined, 'project_idea')), true);
  assert.equal(context.liveCollabPresenceEligible(field('INPUT', 'text', 'project_name')), true);
  assert.equal(context.liveCollabPresenceEligible(field('INPUT', 'hidden', 'secret')), false);
  assert.equal(context.liveCollabPresenceEligible(field('INPUT', 'file', 'receipt')), false);
  assert.equal(context.liveCollabPresenceEligible(field('INPUT', 'number', '')), false);
  assert.equal(context.liveCollabPresenceEligible(null), false);
}

function testPresenceFollowsTheFocusedField() {
  const session = { bindings: new Map(), stopped: false };
  context.document.activeElement = {
    tagName: 'SELECT',
    dataset: { key: 'project_type' },
    closest: () => ({ dataset: { section: 'basic' } }),
  };
  const dropdown = context.liveCollabCurrentPresence(session);
  assert.equal(dropdown.fieldKey, 'project_type', 'a dropdown reports its own field');
  assert.equal(dropdown.sectionKey, 'basic');
  assert.equal(dropdown.caretStart, null, 'a dropdown has no caret to draw');

  const input = {
    tagName: 'INPUT', type: 'text', value: 'اسم', selectionStart: 2, selectionEnd: 4,
    dataset: { key: 'project_name' },
    closest: () => ({ dataset: { section: 'basic' } }),
  };
  session.bindings.set('project_name', { input });
  context.document.activeElement = input;
  const typing = context.liveCollabCurrentPresence(session);
  assert.equal(typing.fieldKey, 'project_name');
  assert.equal(typing.caretStart, 2);
  assert.equal(typing.caretEnd, 4);

  context.document.activeElement = null;
  const idle = context.liveCollabCurrentPresence(session);
  assert.equal(idle.fieldKey, '');
  assert.equal(idle.sectionKey, '');
}

function testPresenceHeartbeatWhileTheTabIsOpen() {
  const heartbeat = vm.runInContext('LIVE_COLLAB_PRESENCE_HEARTBEAT_MS', context);
  const ttl = vm.runInContext('LIVE_COLLAB_PRESENCE_TTL_MS', context);
  assert.ok(heartbeat < ttl, 'the heartbeat must fire before the presence expires');

  const session = { stopped: false, lastPresenceSentAt: 1000 };
  assert.equal(context.liveCollabPresenceHeartbeatDue(session, 5000), false,
    'a just-sent presence is not repeated');
  assert.equal(context.liveCollabPresenceHeartbeatDue(session, 11000), true,
    'an open, idle tab has to say it is still here');

  context.document.visibilityState = 'hidden';
  assert.equal(context.liveCollabPresenceHeartbeatDue(session, 11000), false,
    'a hidden tab stops reporting');
  context.document.visibilityState = 'visible';

  assert.equal(context.liveCollabPresenceHeartbeatDue({ stopped: true }, 11000), false);
  assert.equal(context.liveCollabPresenceHeartbeatDue(null, 11000), false);
}

function testPresenceLineNamesTheField() {
  const originalQuery = context.document.querySelector;
  context.document.querySelector = selector => (String(selector).indexOf('[data-key="project_name"]') >= 0
    ? { parentElement: { querySelector: () => ({ textContent: ' اسم المشروع ' }) } }
    : null);
  assert.equal(context.liveCollabPresenceLine({
    user_name: 'ليلى', field_key: 'project_name', section_key: 'basic',
  }), 'ليلى — اسم المشروع', 'the rail names the field, not just the section');
  assert.equal(context.liveCollabPresenceLine({ user_name: 'ليلى' }), 'ليلى',
    'someone with no focused field is still named');
  assert.equal(context.liveCollabPresenceLine({ user_name: '', field_key: 'project_name' }), '',
    'an unnamed row draws nothing');
  context.document.querySelector = originalQuery;
}

function testPresenceIsWiredIntoTheLoops() {
  assert.ok(moduleSource.includes('liveCollabPresenceHeartbeatDue(session, Date.now())'),
    'the poll has to repeat the presence on its own');
  assert.ok(/liveCollabFlush\(true\);\s*\n\s*liveCollabSchedulePoll/.test(moduleSource),
    'a freshly opened project announces its editor before the first keystroke');
}

function testGoogleDocsPresenceHighlight() {
  assert.equal(context.liveCollabHexToRgba('#17C8E3', 0.2), 'rgba(23, 200, 227, 0.2)');
  let railRemoved = false;
  context.document.getElementById = id => (id === 'liveCollabPresenceRail' ? { remove: () => { railRemoved = true; } } : null);
  context.liveCollabRenderRail([{ user_name: 'Hassan', field_key: 'site_analysis' }]);
  assert.ok(railRemoved, 'the bottom rail must be removed and never drawn');

  // Verify outline and badge are created in liveCollabRenderFieldCarets
  const created = [];
  const parent = {
    style: {},
    appendChild: child => created.push(child),
    getBoundingClientRect: () => ({ left: 10, top: 20, width: 200, height: 100 }),
  };
  const input = {
    tagName: 'TEXTAREA',
    value: 'محتوى التحليل',
    parentElement: parent,
    getBoundingClientRect: () => ({ left: 20, top: 40, width: 180, height: 80 }),
    style: { setProperty() {} },
    classList: { add() {} },
  };
  context.liveCollabRenderFieldCarets(input, [{ user_name: 'Hassan', caret_start: 3 }]);
  assert.equal(created.length, 1, 'an overlay layer must be appended to the field container');
  const layer = created[0];
  assert.equal(layer.className, 'live-caret-overlay');
}

function testConcurrentTypingConverges() {
  const left = new Y.Doc();
  const right = new Y.Doc();
  const leftUpdates = [];
  const rightUpdates = [];
  left.on('update', update => leftUpdates.push(update));
  right.on('update', update => rightUpdates.push(update));
  const leftText = left.getText('field');
  const rightText = right.getText('field');
  leftText.insert(0, 'abc');
  // Both people opened the same saved value, not two independent copies.
  Y.applyUpdate(right, Y.encodeStateAsUpdate(left));
  leftUpdates.length = 0;
  rightUpdates.length = 0;

  // Two people type in the same field before either has heard from the other.
  context.liveApplyTextDiff(leftText, 'aXbc', 'left');
  context.liveApplyTextDiff(rightText, 'abYc', 'right');

  const leftFirst = leftUpdates.slice();
  const rightFirst = rightUpdates.slice();
  leftFirst.forEach(update => Y.applyUpdate(right, update));
  rightFirst.forEach(update => Y.applyUpdate(left, update));

  assert.equal(leftText.toString(), rightText.toString(),
    'both clients must converge on the same text');
  assert.ok(leftText.toString().includes('X') && leftText.toString().includes('Y'),
    'neither concurrent insertion may be lost: ' + leftText.toString());

  leftUpdates.length = 0;
  rightUpdates.length = 0;
  // A deletion on one side and an insertion elsewhere on the other also merge.
  context.liveApplyTextDiff(leftText, leftText.toString().replace('X', ''), 'left');
  context.liveApplyTextDiff(rightText, rightText.toString() + 'Z', 'right');
  const leftTail = leftUpdates.slice();
  const rightTail = rightUpdates.slice();
  leftTail.forEach(update => Y.applyUpdate(right, update));
  rightTail.forEach(update => Y.applyUpdate(left, update));
  assert.equal(leftText.toString(), rightText.toString(),
    'a deletion and an insertion must still converge');
  assert.ok(leftText.toString().endsWith('Z'));
  assert.equal(leftText.toString().includes('X'), false);
}

function testSetLocalValueAndPreserveInputOnBind() {
  assert.equal(typeof context.liveCollabSetLocalValue, 'function',
    'liveCollabSetLocalValue must be exposed');

  const doc = new context.Y.Doc();
  const session = {
    doc,
    fields: doc.getMap('fields'),
    bindings: new Map(),
    pending: [],
    localFieldKey: '',
    localOrigin: { liveCollab: 'local' },
    remoteOrigin: { liveCollab: 'remote' },
    applyingRemote: false,
    stopped: false,
  };
  context.liveCollabSession = session;

  // 1. liveCollabSetLocalValue updates CRDT text
  context.liveCollabSetLocalValue('site_analysis', 'تحليل الموقع الأولي', session);
  let text = session.fields.get('site_analysis');
  assert.ok(text instanceof Y.Text, 'field must be created as Y.Text');
  assert.equal(text.toString(), 'تحليل الموقع الأولي');

  // 2. Setting another value via liveCollabSetLocalValue applies diff cleanly
  context.liveCollabSetLocalValue('site_analysis', 'تحليل الموقع المحدث', session);
  assert.equal(text.toString(), 'تحليل الموقع المحدث');

  // 3. Binding an input that has content while CRDT is empty must NOT wipe input
  const emptyKey = 'new_field';
  const dummyInput = {
    tagName: 'TEXTAREA',
    dataset: { key: emptyKey },
    value: 'محتوى محلي غير فارغ',
    disabled: false,
    readOnly: false,
    closest: () => null,
  };
  const originalGetElementById = context.document.getElementById;
  context.document.getElementById = id => (id === 'tenantProjectForm' ? {
    querySelectorAll: () => [dummyInput],
  } : null);

  context.liveCollabBindFields(session);
  assert.equal(dummyInput.value, 'محتوى محلي غير فارغ',
    'local input value must not be erased when CRDT text was empty');
  const emptyText = session.fields.get(emptyKey);
  assert.equal(emptyText.toString(), 'محتوى محلي غير فارغ',
    'CRDT must adopt local input value instead of wiping it');

  context.document.getElementById = originalGetElementById;
  context.liveCollabSession = null;
}
