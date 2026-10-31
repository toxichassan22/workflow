/* Text-level undo inside editable slide text, the shortcut contract for the
   canvas, and a bounded undo history that survives a refresh. */

    const slideTextUndoStacks = new WeakMap();

    function slideTextEditableFrom(target) {
      if (!target || !target.closest) return null;
      const page = document.getElementById('tenantSlidesPage');
      if (!page || !page.classList.contains('active')) return null;
      return target.closest('.tenant-slide-stage [contenteditable]');
    }

    function slideTextState(el) {
      let state = slideTextUndoStacks.get(el);
      if (!state) {
        state = { last: String(el.innerHTML || ''), past: [], future: [] };
        slideTextUndoStacks.set(el, state);
      }
      return state;
    }

    function rememberSlideTextState(el) {
      if (!el) return;
      const state = slideTextState(el);
      const current = String(el.innerHTML || '');
      if (current !== state.last) {
        state.past.push(state.last);
        if (state.past.length > 60) state.past.shift();
        state.last = current;
        state.future = [];
      }
    }

    function undoSlideText(el) {
      const state = slideTextState(el);
      if (!state.past.length) return false;
      state.future.push(state.last);
      state.last = state.past.pop();
      el.innerHTML = state.last;
      return true;
    }

    function redoSlideText(el) {
      const state = slideTextState(el);
      if (!state.future.length) return false;
      state.past.push(state.last);
      state.last = state.future.pop();
      el.innerHTML = state.last;
      return true;
    }

    document.addEventListener('focusin', event => {
      const el = slideTextEditableFrom(event.target);
      if (!el) return;
      slideTextState(el).last = String(el.innerHTML || '');
    }, true);

    document.addEventListener('input', event => {
      const el = slideTextEditableFrom(event.target);
      if (!el) return;
      rememberSlideTextState(el);
    }, true);

    document.addEventListener('keydown', event => {
      const el = slideTextEditableFrom(event.target);
      if (!el) return;
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.isComposing) return;
      const key = String(event.key || '').toLowerCase();
      if (key !== 'z' && key !== 'y') return;
      const redo = key === 'y' || event.shiftKey;
      if (redo ? redoSlideText(el) : undoSlideText(el)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }, true);

    /* ── Shortcut contract ──────────────────────────────────────────────── */

    function slidesPageIsActive() {
      const page = document.getElementById('tenantSlidesPage');
      return !!(page && page.classList.contains('active'));
    }

    function slidesShortcutBlocked(target) {
      if (!target) return false;
      if (target.isContentEditable) return true;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '')) return true;
      if (target.closest && target.closest('[contenteditable]:not([contenteditable="false"])')) return true;
      return false;
    }

    function handleSlidesWorkspaceShortcuts(event) {
      if (!slidesPageIsActive()) return;
      if (event.defaultPrevented || event.isComposing) return;
      const commandKey = event.ctrlKey || event.metaKey;
      const key = String(event.key || '').toLowerCase();
      if (commandKey && key === 's') {
        event.preventDefault();
        if (typeof savePresentationFromToolbar === 'function') void savePresentationFromToolbar();
        return;
      }
      if (slidesShortcutBlocked(event.target)) {
        if (event.key === 'Escape' && event.target && event.target.isContentEditable) {
          event.target.blur();
        }
        return;
      }
      const index = activeSlideIndex;
      const session = canvasSession(index);
      if (!session) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        session.sel = null;
        session.multi = [];
        const stage = canvasStageFor(index);
        const slide = stage ? stage.querySelector('.slide') : null;
        if (slide) clearSlideSnapGuides(slide);
        if (stage) clearSlideElementSelection(stage);
        syncSlideElementToolbar(index);
        closeSlideInspector();
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        if (!slideSelectedEntries(session).length) return;
        event.preventDefault();
        deleteSelectedSlideElements(index);
        return;
      }
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
        if (!slideSelectedEntries(session).length) return;
        event.preventDefault();
        const step = event.shiftKey ? 10 : 1;
        const dx = event.key === 'ArrowLeft' ? -step : (event.key === 'ArrowRight' ? step : 0);
        const dy = event.key === 'ArrowUp' ? -step : (event.key === 'ArrowDown' ? step : 0);
        moveSlideSelectionBy(index, dx, dy);
        return;
      }
      if (!commandKey) return;
      if (key === 'd') {
        event.preventDefault();
        duplicateSelectedSlideElements(index);
        return;
      }
      if (key === 'c') {
        event.preventDefault();
        copySelectedSlideElements(index);
        return;
      }
      if (key === 'v') {
        event.preventDefault();
        pasteSlideElements(index);
        return;
      }
      if (key === 'a') {
        event.preventDefault();
        selectAllSlideElements(index);
      }
    }

    document.addEventListener('keydown', handleSlidesWorkspaceShortcuts);

    /* ── Undo history survives a refresh, with a hard cap ──────────────── */

    const PRESENTATION_UNDO_PERSIST_LIMIT = 8;
    const PRESENTATION_UNDO_PERSIST_BYTES = 1500000;

    function presentationUndoStorageKey() {
      const id = tenantPresentationId
        || (tenantProjectData && (tenantProjectData.draftId || tenantProjectData.draft_id))
        || '';
      return id ? 'wf.undo.v1.' + String(id) : '';
    }

    function persistPresentationUndoHistory() {
      const key = presentationUndoStorageKey();
      if (!key || !Array.isArray(presentationUndoHistory)) return;
      try {
        const payload = {
          key,
          savedAt: Date.now(),
          position: presentationUndoPosition,
          history: presentationUndoHistory.slice(-PRESENTATION_UNDO_PERSIST_LIMIT)
        };
        const text = JSON.stringify(payload);
        if (text.length > PRESENTATION_UNDO_PERSIST_BYTES) {
          sessionStorage.removeItem(key);
          return;
        }
        sessionStorage.setItem(key, text);
      } catch (error) {
        // Quota is not a failure of the edit; the in-memory history stays.
      }
    }

    function restorePersistedUndoHistory() {
      const key = presentationUndoStorageKey();
      if (!key) return;
      try {
        const raw = sessionStorage.getItem(key);
        if (!raw) return;
        const payload = JSON.parse(raw);
        if (!payload || payload.key !== key || !Array.isArray(payload.history)
          || payload.history.length < 2) return;
        const history = payload.history
          .filter(entry => entry && typeof entry.data === 'string')
          .slice(-PRESENTATION_UNDO_PERSIST_LIMIT);
        if (history.length < 2) return;
        presentationUndoHistory = history;
        presentationUndoPosition = Math.max(0, Math.min(
          Number(payload.position) || 0, history.length - 1));
        updatePresentationUndoButtons();
      } catch (error) { /* ignore a corrupt snapshot */ }
    }

    function clearPersistedUndoHistory() {
      const key = presentationUndoStorageKey();
      if (!key) return;
      try { sessionStorage.removeItem(key); } catch (error) {}
    }

    (function initSlidesCanvasShortcuts() {
      if (typeof ensureSlidesCanvasChrome === 'function') ensureSlidesCanvasChrome();
      try {
        const saved = Number(localStorage.getItem('wf.slidesCanvasZoom'));
        if (saved && isFinite(saved)) tenantCanvasZoom = saved;
      } catch (error) {}
      if (typeof applyTenantCanvasZoom === 'function') applyTenantCanvasZoom(tenantCanvasZoom, true);
    })();
