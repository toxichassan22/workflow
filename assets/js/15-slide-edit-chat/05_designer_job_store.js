/* Designer-chat job persistence, workspace keying and chat memory, split
   from 02_designer_chat.js to keep each part under the file-size limit. */

    /* ── Designer-chat job persistence: busy indicator, workspace-keyed
       job storage and restore/reset helpers. ── */


    // The indicator carries the step word only: the server publishes no measured
    // fraction for a chat turn, so there is no number to put in it.
    function updateDesignerChatBusy(message) {
      if (!tenantDesignerChatBusy) return;
      if (message) tenantDesignerChatBusy.message = String(message);
      const indicator = document.getElementById('tenantChatTypingIndicator');
      if (indicator) setInlineLoaderProgress(indicator, tenantDesignerChatBusy.message);
      updateDesignerChatStatus();
    }

    function clearDesignerChatBusy(workspaceKey = '') {
      if (workspaceKey && tenantDesignerChatBusy?.workspaceKey
        && tenantDesignerChatBusy.workspaceKey !== workspaceKey) return;
      tenantDesignerChatBusy = null;
      document.querySelectorAll('[data-designer-was-disabled]').forEach(button => {
        button.disabled = button.dataset.designerWasDisabled === 'true';
        delete button.dataset.designerWasDisabled;
      });
      const indicator = document.getElementById('tenantChatTypingIndicator');
      if (indicator) indicator.remove();
      if (typeof clearDesignerSlideActivity === 'function') clearDesignerSlideActivity();
      updateDesignerChatStatus();
    }

    function restoreDesignerChatBusyIndicator() {
      if (!tenantDesignerChatBusy) return;
      const messages = document.getElementById('tenantChatMessages');
      if (!messages) return;
      if (document.getElementById('tenantChatTypingIndicator')) return;
      const hint = messages.querySelector('.tenant-hint');
      if (hint) hint.remove();
      const indicator = document.createElement('div');
      indicator.id = 'tenantChatTypingIndicator';
      indicator.className = 'tenant-chat-message assistant typing';
      showInlineLoader(indicator, tenantDesignerChatBusy.message);
      setInlineLoaderProgress(indicator, tenantDesignerChatBusy.message);
      messages.appendChild(indicator);
      messages.scrollTop = messages.scrollHeight;
    }

    function designerChatWorkspaceKey(presentationId = tenantPresentationId, projectData = tenantProjectData) {
      const tenantId = tenantUser && (tenantUser.id || tenantUser.tenantId);
      const draftId = projectData && (projectData.draftId || projectData.draft_id);
      const workspaceId = presentationId
        ? 'presentation:' + String(presentationId)
        : (draftId ? 'draft:' + String(draftId) : '');
      return tenantId && workspaceId ? String(tenantId) + '|' + workspaceId : '';
    }

    function designerChatWorkspaceSignature() {
      let serialized = '';
      try {
        serialized = JSON.stringify({ slides: tenantSlidesData, creativeImages: tenantCreativeImages });
      } catch (error) {
        serialized = String(tenantSlidesData.length);
      }
      let hash = 2166136261;
      for (let index = 0; index < serialized.length; index++) {
        hash ^= serialized.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
      }
      return serialized.length + ':' + (hash >>> 0).toString(16);
    }

    function readTenantDesignerJobs() {
      try {
        const parsed = JSON.parse(localStorage.getItem(T_DESIGNER_JOBS_KEY) || '{}');
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      } catch (error) {
        return {};
      }
    }

    function persistTenantDesignerJob(metadata) {
      if (!metadata || !metadata.jobId || !metadata.workspaceKey) return;
      const jobs = readTenantDesignerJobs();
      const cutoff = Date.now() - 24 * 60 * 60 * 1000;
      Object.keys(jobs).forEach(key => {
        if (!jobs[key] || Number(jobs[key].startedAt || 0) < cutoff) delete jobs[key];
      });
      jobs[metadata.workspaceKey] = {
        jobId: String(metadata.jobId),
        workspaceKey: String(metadata.workspaceKey),
        presentationId: metadata.presentationId || null,
        draftId: metadata.draftId || null,
        message: String(metadata.message || '').slice(0, 2000),
        target: String(metadata.target || 'auto'),
        scope: String(metadata.scope || metadata.target || 'auto'),
        indexes: Array.isArray(metadata.indexes) ? metadata.indexes.slice(0, 30) : [],
        slideIndex: Number.isInteger(Number(metadata.slideIndex)) ? Number(metadata.slideIndex) : 0,
        hadAttachment: !!metadata.hadAttachment,
        workspaceSignature: String(metadata.workspaceSignature || ''),
        slideSignatures: (metadata.slideSignatures && typeof metadata.slideSignatures === 'object')
          ? { ...metadata.slideSignatures } : null,
        creativeSignatures: (metadata.creativeSignatures && typeof metadata.creativeSignatures === 'object')
          ? { ...metadata.creativeSignatures } : null,
        appliedSeq: Number(metadata.appliedSeq) || 0,
        startedAt: Number(metadata.startedAt || Date.now()),
        updatedAt: Number(metadata.updatedAt || Date.now()),
        status: String(metadata.status || 'queued'),
        cancelRequested: !!metadata.cancelRequested
      };
      try {
        localStorage.setItem(T_DESIGNER_JOBS_KEY, JSON.stringify(jobs));
      } catch (error) {
        console.warn('[DESIGNER JOB] Could not persist active job', error);
      }
    }

    function currentTenantDesignerJob() {
      const workspaceKey = designerChatWorkspaceKey();
      if (!workspaceKey) return null;
      const job = readTenantDesignerJobs()[workspaceKey];
      return job && job.workspaceKey === workspaceKey ? job : null;
    }

    function clearTenantDesignerJob(metadata) {
      if (!metadata || !metadata.workspaceKey) return;
      const jobs = readTenantDesignerJobs();
      const current = jobs[metadata.workspaceKey];
      if (current && (!metadata.jobId || String(current.jobId) === String(metadata.jobId))) {
        delete jobs[metadata.workspaceKey];
        try {
          localStorage.setItem(T_DESIGNER_JOBS_KEY, JSON.stringify(jobs));
        } catch (error) {
          console.warn('[DESIGNER JOB] Could not clear completed job', error);
        }
      }
    }

    function tenantDesignerJobMatchesWorkspace(metadata) {
      return !!metadata && metadata.workspaceKey === designerChatWorkspaceKey();
    }

    function tenantDesignerServerJobMatches(metadata, serverJob) {
      if (!metadata || !serverJob || typeof serverJob !== 'object') return true;
      const sameWhenPresent = (expected, actual) => !expected || !actual || String(expected) === String(actual);
      return sameWhenPresent(metadata.jobId, serverJob.jobId)
        && sameWhenPresent(metadata.presentationId, serverJob.presentationId)
        && sameWhenPresent(metadata.draftId, serverJob.draftId);
    }

    function tenantDesignerJobCanApply(metadata) {
      // A job keyed by slide id defers drift handling to the merge at apply
      // time — an edit on a slide the run never touched must not fail it.
      if (metadata?.slideSignatures) return true;
      return !metadata?.workspaceSignature
        || metadata.workspaceSignature === designerChatWorkspaceSignature();
    }

    function designerChatPersistence(presentationId = tenantPresentationId) {
      return {
        presentationId: presentationId || null,
        messages: tenantDesignerMessages.slice(-DESIGNER_CHAT_HISTORY_KEPT * 2).map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content || '').slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })),
        memory: tenantDesignerChatMemory || '',
        focusIndexes: tenantChatFocusIndexes || []
      };
    }

    function restoreDesignerChat(source, expectedPresentationId = null) {
      const stored = source && typeof source === 'object' ? (source.designerChat || {}) : {};
      const storedPresentationId = stored && stored.presentationId ? String(stored.presentationId) : '';
      const presentationMatches = !expectedPresentationId || !storedPresentationId
        || storedPresentationId === String(expectedPresentationId);
      tenantDesignerMessages = Array.isArray(stored.messages)
        && presentationMatches
        ? stored.messages.filter(item => item && typeof item.content === 'string').map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content).slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })).slice(-DESIGNER_CHAT_HISTORY_KEPT * 2)
        : [];
      tenantDesignerChatMemory = presentationMatches && typeof stored.memory === 'string'
        ? stored.memory.slice(0, 40000) : '';
      tenantChatFocusIndexes = presentationMatches && Array.isArray(stored.focusIndexes)
        ? stored.focusIndexes.map(Number).filter(value => Number.isInteger(value) && value >= 1).slice(0, 30)
        : [];
    }

    function resetDesignerChatForNewPresentation() {
      tenantDesignerMessages = [];
      tenantDesignerChatMemory = '';
      tenantChatFocusIndexes = [];
      tenantChatSlideScope = 'auto';
      tenantProjectData.designerChat = designerChatPersistence(null);
      renderTenantDesignerChat();
    }
    let tenantChatSlideIndex = 0;
    let tenantChatSlideScope = 'auto';
