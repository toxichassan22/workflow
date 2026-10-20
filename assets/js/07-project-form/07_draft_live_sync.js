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
          draftLiveSyncRevision = Number(data.revision) || draftLiveSyncRevision;
          await handleDraftLiveChange(data);
        }
      } catch (error) {
        // A poll that could not go through is not something to read about.
      }
      scheduleDraftLiveSync();
    }

    async function applyLiveDraftSync(draftId, newRevision) {
      if (!draftId) return;
      const inProject = typeof tenantProjectMode === 'undefined' || tenantProjectMode === 'draft';
      if (!inProject) return;
      if (typeof tenantProjectData !== 'undefined' && tenantProjectData && tenantProjectData.draftId && tenantProjectData.draftId !== draftId) {
        return;
      }

      try {
        const resp = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId));
        if (!resp || !resp.success || !resp.draft) return;
        const draft = resp.draft;
        const draftData = draft.draft_data || draft.draftData || {};
        const incomingRev = Number(draft.revision) || Number(newRevision) || tenantDraftRevision;

        if (incomingRev > tenantDraftRevision) {
          tenantDraftRevision = incomingRev;
          draftLiveSyncRevision = incomingRev;
        }

        const activeEl = (typeof document !== 'undefined') ? document.activeElement : null;
        const focusedKey = (activeEl && activeEl.dataset) ? activeEl.dataset.key : null;

        // In-place DOM update for inputs (preserving the element the user is currently typing in)
        if (typeof document !== 'undefined' && document.getElementById) {
          const form = document.getElementById('tenantProjectForm');
          if (form && form.querySelectorAll) {
            form.querySelectorAll('[data-key]').forEach(input => {
              const key = input.dataset.key;
              if (!key || !(key in draftData) || input.type === 'file') return;
              if (input === activeEl || (focusedKey && key === focusedKey)) return;

              const newVal = draftData[key];
              let strVal = '';
              if (newVal === null || newVal === undefined) {
                strVal = '';
              } else if (typeof newVal === 'object') {
                strVal = JSON.stringify(newVal);
              } else {
                strVal = String(newVal);
              }

              if (input.value !== strVal) {
                input.value = strVal;
                if (input.classList && input.classList.add) {
                  input.classList.add('field-live-updated');
                  setTimeout(() => {
                    try { input.classList.remove('field-live-updated'); } catch (e) {}
                  }, 1200);
                }
              }
            });
          }
        }

        // In-place update of backing data
        if (typeof tenantProjectData !== 'undefined' && tenantProjectData) {
          Object.keys(draftData).forEach(key => {
            if (focusedKey && key === focusedKey) return;
            tenantProjectData[key] = draftData[key];
          });
          tenantProjectData.draftId = draftId;
        }

        // In-place section statuses update
        const sectionStatuses = draft.section_statuses || {};
        if (sectionStatuses && typeof applySectionStatuses === 'function') {
          if (typeof tenantProjectSectionStatuses !== 'undefined') {
            tenantProjectSectionStatuses = { ...tenantProjectSectionStatuses, ...sectionStatuses };
          }
          applySectionStatuses(sectionStatuses);
        }

        // In-place slides update
        if (Array.isArray(draftData.tenantSlidesData) && typeof tenantSlidesData !== 'undefined') {
          tenantSlidesData = draftData.tenantSlidesData;
          if (typeof document !== 'undefined' && document.getElementById) {
            const slidesEditor = document.getElementById('tenantSlidesEditor');
            if (slidesEditor && !slidesEditor.hidden && typeof renderTenantSlides === 'function') {
              renderTenantSlides();
            }
          }
        }

        // Update badge subtly
        if (typeof document !== 'undefined' && document.getElementById) {
          const badge = document.getElementById('draftSyncBadge');
          if (badge) {
            badge.style.background = '#edf7f3';
            badge.style.color = '#126247';
            badge.innerHTML = 'محدّث تلقائيًا';
          }
        }
      } catch (err) {
        console.warn('[DRAFT LIVE SYNC] In-place sync failed:', err);
      }
    }

    function handleDraftLiveChange(data) {
      if (!data || !data.draftId) return Promise.resolve();
      const inProject = typeof tenantProjectMode === 'undefined' || tenantProjectMode === 'draft';
      if (!inProject) return Promise.resolve();
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
