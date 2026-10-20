/* 07-project-form/07_draft_live_sync.js — the open workspace follows the file.
 *
 * A merge (or a save) by somebody else changes the file under the people who
 * still have it open. The workspace polls a tiny state endpoint, so the file
 * follows without a manual refresh: with nothing unsaved on this side the new
 * file is taken, and with unsaved edits the next save merges them instead of
 * overwriting anything.
 */
    const DRAFT_LIVE_SYNC_INTERVAL_MS = 20000;

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
        // Our own write is still in flight — the revision it produces is not
        // known yet, so there is nothing to compare against.
        scheduleDraftLiveSync();
        return;
      }
      const since = Number(draftLiveSyncRevision) || 0;
      try {
        const data = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId) +
          '/state?since=' + since);
        if (data && data.success && Number(data.revision) > since) {
          // The change is known now, so reporting it twice would only repeat
          // the badge. The workspace's own revision stays behind on purpose: a
          // save with unsaved edits must still meet the server's newer
          // revision and merge instead of writing over it.
          draftLiveSyncRevision = Number(data.revision) || draftLiveSyncRevision;
          handleDraftLiveChange(data);
        }
      } catch (error) {
        // A poll that could not go through is not something to read about.
      }
      scheduleDraftLiveSync();
    }

    function handleDraftLiveChange(data) {
      const editing = typeof tenantDraftDirty !== 'undefined' && tenantDraftDirty;
      const inProject = typeof tenantProjectMode === 'undefined' || tenantProjectMode === 'draft';
      if (!editing && inProject) {
        // Nothing to lose on this side: take the file as it is now.
        if (typeof openProjectDraftById === 'function') openProjectDraftById(data.draftId);
        toast(WFT('draft_live.updated', 'تم تحديث المسودة'));
        return;
      }
      // There are unsaved edits here (or the workspace is in another mode):
      // the file is not reloaded under the person's hands. The next save
      // merges instead of overwriting.
      const badge = document.getElementById('draftSyncBadge');
      if (badge) {
        badge.style.background = '#fef3c7';
        badge.style.color = '#92400e';
        badge.innerHTML = WFT('draft_live.pending', 'المسودة اتغيّرت — احفظ تعديلاتك وهي تتدمج');
      }
      toast(WFT('draft_live.pending_toast',
        'شخص آخر عدّل المسودة — حفظك هيدمج تعديلاتك مع تعديلاته'));
    }

    document.addEventListener('visibilitychange', () => {
      if (!draftLiveSyncId) return;
      if (document.visibilityState === 'visible') {
        // The tab was in the background: ask right away instead of waiting.
        pollDraftLiveState();
      } else if (draftLiveSyncTimer) {
        clearTimeout(draftLiveSyncTimer);
        draftLiveSyncTimer = null;
      }
    });
