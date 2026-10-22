/* 07-project-form/07_draft_live_sync.js — the open workspace follows the file.
 *
 * Real-time sync: an edit by somebody else updates the form in-place smoothly
 * without full-page reloads, without disrupting focus, and without kicking
 * the user away from their current section.
 */
    const DRAFT_LIVE_SYNC_INTERVAL_MS = 4000;

    let draftLiveSyncTimer = null;
    let draftLiveSyncId = '';
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
      draftLocalSavePending = false;
    }

    function startDraftLiveSync(draftId, revision) {
      stopDraftLiveSync();
      if (!draftId) return;
      draftLiveSyncId = draftId;
      // The baseline is set, not raised: a file opened with a lower revision
      // than the last one followed is followed from its own start.
      const value = Number(revision);
      if (Number.isFinite(value) && value >= 0) {
        tenantDraftRevision = value;
        draftLiveSyncRevision = value;
      }
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
      draftLiveSyncTimer = setTimeout(pollDraftLiveState, DRAFT_LIVE_SYNC_INTERVAL_MS);
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
        if (data && data.success && Number(data.revision) > since) {
          // The revision is consumed only after the change was applied (or
          // deliberately deferred). A failed fetch is retried by the next poll.
          const handled = await handleDraftLiveChange(data);
          if (handled) draftLiveSyncRevision = Number(data.revision) || draftLiveSyncRevision;
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
        if (Array.isArray(draftData.tenantSlidesData) && typeof tenantSlidesData !== 'undefined') {
          tenantSlidesData = draftData.tenantSlidesData;
        }
        if (typeof recoverTenantSlidePlan === 'function') {
          const plan = recoverTenantSlidePlan(draftData, tenantSlidesData);
          if (typeof tenantSlidePlan !== 'undefined') tenantSlidePlan = plan;
        }

        // Rebuild every section from the incoming payload, not just the plain
        // inputs: the market, financial, timeline, team and visual widgets read
        // their own state and used to keep showing the previous file.
        if (typeof hydrateTenantProjectForm === 'function') {
          hydrateTenantProjectForm(draftData);
        }

        if (sectionStatuses && typeof applySectionStatuses === 'function') {
          if (typeof tenantProjectSectionStatuses !== 'undefined') {
            tenantProjectSectionStatuses = { ...tenantProjectSectionStatuses, ...sectionStatuses };
          }
          applySectionStatuses(sectionStatuses);
        }

        if (typeof renderTenantSlides === 'function') {
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

    function handleDraftLiveChange(data) {
      if (!data || !data.draftId) return Promise.resolve(false);
      const inProject = typeof tenantProjectMode === 'undefined' || tenantProjectMode === 'draft';
      if (!inProject) return Promise.resolve(false);
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
