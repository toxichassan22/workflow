/* 07-project-form/07_draft_live_sync.js — the open workspace follows the file.
 *
 * Real-time sync: an edit by somebody else updates the form in-place smoothly
 * without full-page reloads, without disrupting focus, and without kicking
 * the user away from their current section.
 */
    const DRAFT_LIVE_SYNC_INTERVAL_MS = 4000;
    const DRAFT_LIVE_SYNC_SOLO_MS = 20000;
    // A lone editor has nobody to follow: polling the draft every four seconds
    // only burns a request. The live presence poll detects the second person,
    // and the next schedule falls back to the fast interval.

    let draftLiveSyncTimer = null;
    let draftLiveSyncId = '';
    // Section approvals live in their own column and do not bump the payload
    // revision, so updatedAt is the signal that a badge changed.
    let draftLiveSyncUpdatedAt = '';
    // A save of our own is on the wire: the revision it will produce is not
    // known yet, so the poll waits instead of reading our own write as a
    // change by somebody else.
    let draftLocalSavePending = false;

    function stopDraftLiveSync() {
      if (draftLiveSyncTimer) {
        clearTimeout(draftLiveSyncTimer);
        draftLiveSyncTimer = null;
      }
      draftLiveSyncId = '';
      draftLiveSyncUpdatedAt = '';
      draftLocalSavePending = false;
      if (typeof stopLiveCollaboration === 'function') stopLiveCollaboration();
    }

    function startDraftLiveSync(draftId, revision) {
      if (draftLiveSyncTimer) {
        clearTimeout(draftLiveSyncTimer);
        draftLiveSyncTimer = null;
      }
      draftLocalSavePending = false;
      if (!draftId) {
        stopDraftLiveSync();
        return;
      }
      if (draftLiveSyncId && draftLiveSyncId !== draftId
          && typeof stopLiveCollaboration === 'function') {
        stopLiveCollaboration();
      }
      draftLiveSyncId = draftId;
      draftLiveSyncUpdatedAt = '';
      // The baseline is set, not raised: a file opened with a lower revision
      // than the last one followed is followed from its own start.
      const value = Number(revision);
      if (Number.isFinite(value) && value >= 0) {
        tenantDraftRevision = value;
        draftLiveSyncRevision = value;
      }
      if (typeof startLiveCollaboration === 'function') startLiveCollaboration(draftId);
      scheduleDraftLiveSync();
    }

    // A write of our own is on the wire: the poll waits for it instead of
    // reading the revision it is about to produce as somebody else's change.
    function beginDraftLocalSave() {
      draftLocalSavePending = true;
    }

    function endDraftLocalSave() {
      draftLocalSavePending = false;
    }

    function scheduleDraftLiveSync() {
      if (!draftLiveSyncId) return;
      if (draftLiveSyncTimer) clearTimeout(draftLiveSyncTimer);
      const alone = typeof liveCollabSession === 'undefined' || !liveCollabSession
        || !Array.isArray(liveCollabSession.presence)
        || liveCollabSession.presence.length === 0;
      draftLiveSyncTimer = setTimeout(
        pollDraftLiveState,
        alone ? DRAFT_LIVE_SYNC_SOLO_MS : DRAFT_LIVE_SYNC_INTERVAL_MS
      );
    }

    async function pollDraftLiveState() {
      const draftId = draftLiveSyncId;
      if (!draftId) return;
      if (draftLocalSavePending) {
        // Our own write is still in flight — wait for it.
        scheduleDraftLiveSync();
        return;
      }
      const since = Number(draftLiveSyncRevision) || 0;
      try {
        const data = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId) +
          '/state?since=' + since);
        if (data && data.success) {
          const nextRevision = Number(data.revision) || 0;
          const nextUpdatedAt = String(data.updatedAt || '');
          const revisionMoved = nextRevision > since;
          const statusMoved = Boolean(nextUpdatedAt)
            && nextUpdatedAt !== draftLiveSyncUpdatedAt;
          if (revisionMoved) {
            // The revision is consumed only after the change was applied (or
            // deliberately deferred). A failed fetch is retried by the next poll.
            const handled = await handleDraftLiveChange(data);
            if (handled) {
              if (nextRevision > 0) draftLiveSyncRevision = nextRevision;
              draftLiveSyncUpdatedAt = nextUpdatedAt;
            }
          } else if (statusMoved) {
            // Approving or unapproving a section does not touch the payload
            // revision; applying its badges here is what removes the refresh.
            handleDraftStatusChange(data);
            draftLiveSyncUpdatedAt = nextUpdatedAt;
          }
        }
      } catch (error) {
        // A poll that could not go through is not something to read about.
      }
      scheduleDraftLiveSync();
    }

    function showDraftPendingChangeBadge() {
      if (typeof document === 'undefined' || !document.getElementById) return;
      const badge = document.getElementById('draftSyncBadge');
      if (!badge) return;
      badge.style.background = '#fef3c7';
      badge.style.color = '#92400e';
      badge.innerHTML = WFT('draft_live.pending', 'المسودة اتغيّرت من مستخدم آخر');
    }

    // A field another person changed in a section this tab is not typing in.
    // With autosave the whole form must not be rebuilt on every revision: that
    // moved focus, the caret and every open widget. Text fields are already
    // handled by the CRDT session; the other controls are written in place.
    function applyRemoteDraftValues(draftData) {
      if (!draftData || typeof document === 'undefined' || !document.querySelectorAll) return false;
      const bound = (typeof liveCollabSession !== 'undefined' && liveCollabSession && liveCollabSession.bindings)
        ? liveCollabSession.bindings : null;
      const active = document.activeElement;
      let changed = false;
      document.querySelectorAll('#tenantProjectForm [data-key]').forEach(input => {
        const key = input.getAttribute('data-key');
        if (!key || (bound && bound.has(key))) return;
        if (input === active || (active && active.contains && active.contains(input))) return;
        if (typeof liveCollabFieldEligible === 'function' && liveCollabFieldEligible(input)) return;
        if (!Object.prototype.hasOwnProperty.call(draftData, key)) return;
        const value = draftData[key];
        if (value === null || typeof value === 'object') return;
        if (input.type === 'radio') return;
        if (typeof draftApplyingRemote !== 'undefined') draftApplyingRemote = true;
        try {
          if (input.type === 'checkbox') {
            const checked = value === true || value === 'true' || value === 1 || value === '1';
            if (input.checked === checked) return;
            input.checked = checked;
            input.dispatchEvent(new Event('change', { bubbles: true }));
            changed = true;
            return;
          }
          const nextValue = String(value);
          if (String(input.value) === nextValue) return;
          input.value = nextValue;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          changed = true;
        } finally {
          if (typeof draftApplyingRemote !== 'undefined') draftApplyingRemote = false;
        }
      });
      return changed;
    }

    async function applyLiveDraftSync(draftId, newRevision, options = {}) {
      if (!draftId) return false;
      const inProject = typeof tenantProjectMode === 'undefined' || tenantProjectMode === 'draft';
      if (!inProject) return false;
      if (typeof tenantProjectData !== 'undefined' && tenantProjectData && tenantProjectData.draftId && tenantProjectData.draftId !== draftId) {
        return false;
      }
      // Unsaved edits here must never be replaced by a remote snapshot: the
      // next save merges them instead of overwriting either side. Only the
      // save path itself may force the merged state in.
      const editing = typeof tenantDraftDirty !== 'undefined' && tenantDraftDirty;
      if (editing && !options.force) {
        showDraftPendingChangeBadge();
        return true;
      }

      const activeEl = (typeof document !== 'undefined') ? document.activeElement : null;
      const selectionStart = activeEl && typeof activeEl.selectionStart === 'number'
        ? activeEl.selectionStart : null;
      const selectionEnd = activeEl && typeof activeEl.selectionEnd === 'number'
        ? activeEl.selectionEnd : null;

      try {
        const resp = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId));
        if (!resp || !resp.success || !resp.draft) return false;
        const draft = resp.draft;
        const draftData = draft.draft_data || draft.draftData || {};
        const sectionStatuses = draft.section_statuses || {};

        if (typeof tenantProjectData !== 'undefined' && tenantProjectData) {
          tenantProjectData = { ...tenantProjectData, ...draftData, draftId };
        }
        if (draftData.tenantCreativeImages && typeof tenantCreativeImages !== 'undefined') {
          tenantCreativeImages = draftData.tenantCreativeImages;
          if (typeof tenantProjectData !== 'undefined' && tenantProjectData) {
            tenantProjectData.tenantCreativeImages = tenantCreativeImages;
          }
        }
        const slidesBefore = JSON.stringify(typeof tenantSlidesData !== 'undefined' ? tenantSlidesData : []);
        if (Array.isArray(draftData.tenantSlidesData) && typeof tenantSlidesData !== 'undefined') {
          tenantSlidesData = draftData.tenantSlidesData;
        }
        if (typeof recoverTenantSlidePlan === 'function') {
          const plan = recoverTenantSlidePlan(draftData, tenantSlidesData);
          if (typeof tenantSlidePlan !== 'undefined') tenantSlidePlan = plan;
        }

        // Rebuild every section from the incoming payload, not just the plain
        // inputs: the market, financial, timeline, team and visual widgets read
        // their own state and used to keep showing the previous file. With
        // autosave the file moves every couple of seconds, so a full rebuild
        // would steal the focus and the caret on every poll; text already flows
        // through the CRDT, and the remaining controls are written in place.
        const autosaveEnabled = typeof DRAFT_AUTOSAVE_ENABLED !== 'undefined'
          && DRAFT_AUTOSAVE_ENABLED;
        if (autosaveEnabled) {
          applyRemoteDraftValues(draftData);
        } else if (typeof hydrateTenantProjectForm === 'function') {
          hydrateTenantProjectForm(draftData);
        }

        if (sectionStatuses && typeof applySectionStatuses === 'function') {
          if (typeof tenantProjectSectionStatuses !== 'undefined') {
            tenantProjectSectionStatuses = { ...tenantProjectSectionStatuses, ...sectionStatuses };
          }
          applySectionStatuses(sectionStatuses);
        }

        // Text fields belong to the live session while it is open, so a
        // remote save's older text must not replace what people are typing.
        if (typeof liveApplySessionToForm === 'function') {
          liveApplySessionToForm({ markDirty: false });
        }

        if (typeof renderTenantSlides === 'function'
            && JSON.stringify(typeof tenantSlidesData !== 'undefined' ? tenantSlidesData : []) !== slidesBefore) {
          renderTenantSlides();
        }
        if (typeof getTenantNavigationState === 'function'
            && (getTenantNavigationState() || {}).pageId === 'tenantVisualConceptPage'
            && typeof renderVisualConceptPage === 'function') {
          renderVisualConceptPage();
        }

        if (activeEl && selectionStart !== null && typeof activeEl.setSelectionRange === 'function') {
          try { activeEl.setSelectionRange(selectionStart, selectionEnd); } catch (err) { /* detached input */ }
        }

        const incomingRev = Number(draft.revision) || Number(newRevision) || 0;
        if (incomingRev > 0 && typeof tenantDraftRevision !== 'undefined') {
          tenantDraftRevision = incomingRev;
          draftLiveSyncRevision = incomingRev;
        }
        // The applied remote state is the new baseline for "did the user clear
        // this field, or did it merely not load?".
        if (typeof tenantProjectData !== 'undefined' && tenantProjectData) {
          tenantDraftLoadedSnapshot = JSON.parse(JSON.stringify(tenantProjectData));
        }

        if (typeof document !== 'undefined' && document.getElementById) {
          const badge = document.getElementById('draftSyncBadge');
          if (badge) {
            badge.style.background = '#edf7f3';
            badge.style.color = '#126247';
            badge.innerHTML = 'محدّث تلقائيًا';
          }
        }
        return true;
      } catch (err) {
        console.warn('[DRAFT LIVE SYNC] In-place sync failed:', err);
        return false;
      }
    }

    function handleDraftStatusChange(data) {
      if (!data || !data.draftId) return false;
      const inProject = typeof tenantProjectMode === 'undefined' || tenantProjectMode === 'draft';
      if (!inProject) return false;
      const statuses = data.sectionStatuses;
      if (statuses && typeof statuses === 'object' && typeof applySectionStatuses === 'function') {
        if (typeof tenantProjectSectionStatuses !== 'undefined') {
          tenantProjectSectionStatuses = { ...tenantProjectSectionStatuses, ...statuses };
        }
        applySectionStatuses(statuses);
      }
      // A section that was approved while somebody typed is unlocked here; its
      // CRDT text must land in the input now, not on the next refresh.
      if (typeof liveCollabApplySessionToForm === 'function') {
        liveCollabApplySessionToForm({ markDirty: false });
      }
      if (typeof tenantDraftDirty !== 'undefined' && tenantDraftDirty) {
        showDraftPendingChangeBadge();
      }
      return true;
    }

    function handleDraftLiveChange(data) {
      if (!data || !data.draftId) return Promise.resolve(false);
      const inProject = typeof tenantProjectMode === 'undefined' || tenantProjectMode === 'draft';
      if (!inProject) return Promise.resolve(false);
      handleDraftStatusChange(data);
      return applyLiveDraftSync(data.draftId, data.revision);
    }

    if (typeof document !== 'undefined' && document.addEventListener) {
      document.addEventListener('visibilitychange', () => {
        if (!draftLiveSyncId) return;
        if (document.visibilityState === 'visible') {
          pollDraftLiveState();
        } else if (draftLiveSyncTimer) {
          clearTimeout(draftLiveSyncTimer);
          draftLiveSyncTimer = null;
        }
      });
    }
