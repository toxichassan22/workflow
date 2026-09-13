/* 14-slides-gen.js - index.html lines 23156-24650, shared global scope, classic scripts in order */

    /* Unified manual slide editing: one smart edit mode per slide with its own
       undo session (اعتماد / تراجع / تقدم / الغاء). Text editing and element
       dragging stay active together; a click decides by target (text edits,
       images and positioned blocks drag). */
    const slideEditSessions = {};
    const SLIDE_EDIT_HISTORY_LIMIT = 30;
    /* Mutual exclusion: only one element drag (move or resize) may run at a
       time per page. A second pointerdown while one is active is ignored, so
       two sessions can never write the same slide concurrently. */
    let slideElementDragActive = false;

    function slideEditFingerprint(slide) {
      const title = String((slide && slide.title) || '');
      const html = String((slide && slide.html) || '');
      const normalized = html
        .replace(/data-slide-counter=["'][^"']*["\'][^>]*>[\s\S]*?</g, 'data-slide-counter>')
        .replace(/\s+data-slide-counter=["'][^"']*["\']/g, ' data-slide-counter');
      let hash = 5381;
      for (let i = 0; i < normalized.length; i++) {
        hash = ((hash << 5) + hash + normalized.charCodeAt(i)) | 0;
      }
      return title + '|' + normalized.length + '|' + (hash >>> 0).toString(36);
    }

    // In-session deck history only. Reset AFTER workspace load/render; checkpoint
    // BEFORE/AFTER generation. Saving the same deck must not clear this history.
    const PRESENTATION_UNDO_LIMIT = 30;
    const PRESENTATION_UNDO_MAX_CHARS = 16 * 1024 * 1024;
    let presentationUndoHistory = [];
    let presentationUndoPosition = -1;
    let presentationUndoRestoring = false;
    let presentationUndoEpoch = 0;
    let presentationUndoPending = false;

    function capturePresentationUndo() {
      return {
        data: JSON.stringify({
          slides: tenantSlidesData || [], plan: tenantSlidePlan || null,
          generationCheckpoint: typeof tenantSlideGenerationCheckpoint === 'undefined' ? null : tenantSlideGenerationCheckpoint,
          provenance: typeof tenantPresentationProvenance === 'undefined' ? null : tenantPresentationProvenance
        }),
        active: activeSlideIndex, chat: tenantChatSlideIndex,
        focus: Array.isArray(tenantChatFocusIndexes) ? tenantChatFocusIndexes.slice() : []
      };
    }

    function presentationUndoBusy() {
      return !!((typeof isGeneratingTenantSlides !== 'undefined' && isGeneratingTenantSlides)
        || (typeof isRegeneratingTenantSlide !== 'undefined' && isRegeneratingTenantSlide)
        || (typeof tenantSlidePlanRequest !== 'undefined' && tenantSlidePlanRequest)
        || (typeof tenantPresentationSavePromise !== 'undefined' && tenantPresentationSavePromise)
        || (typeof tenantDesignerChatBusy !== 'undefined' && tenantDesignerChatBusy)
        || slideElementDragActive);
    }

    function presentationUndoAvailable() {
      return !!document.getElementById('tenantSlidesPage')?.classList.contains('active')
        && hasPermission('create_presentation') && !presentationUndoBusy()
        && !Object.keys(slideEditSessions).length;
    }

    function updatePresentationUndoButtons() {
      const available = presentationUndoAvailable();
      const undo = document.getElementById('presentationUndoButton');
      const redo = document.getElementById('presentationRedoButton');
      if (undo) undo.disabled = !available || presentationUndoPosition <= 0;
      if (redo) redo.disabled = !available || presentationUndoPosition >= presentationUndoHistory.length - 1;
    }

    function resetPresentationUndo() {
      presentationUndoEpoch += 1;
      presentationUndoPending = false;
      presentationUndoHistory = [capturePresentationUndo()];
      presentationUndoPosition = 0;
      updatePresentationUndoButtons();
    }

    function clearPresentationUndoProvenance() {
      if (typeof tenantPresentationProvenance !== 'undefined') tenantPresentationProvenance = null;
      presentationUndoHistory.forEach(snapshot => {
        const state = JSON.parse(snapshot.data);
        state.provenance = null;
        snapshot.data = JSON.stringify(state);
      });
      updatePresentationUndoButtons();
    }

    function checkpointPresentationUndo() {
      if (presentationUndoRestoring) return false;
      const snapshot = capturePresentationUndo();
      const current = presentationUndoHistory[presentationUndoPosition];
      if (current && current.data === snapshot.data) {
        Object.assign(current, snapshot);
        updatePresentationUndoButtons();
        return false;
      }
      presentationUndoHistory.splice(presentationUndoPosition + 1);
      presentationUndoHistory.push(snapshot);
      let size = presentationUndoHistory.reduce((total, entry) => total + entry.data.length, 0);
      // Retain an oversize current state, never multiple oversize copies.
      while (presentationUndoHistory.length > 1 && (presentationUndoHistory.length > PRESENTATION_UNDO_LIMIT
        || size > PRESENTATION_UNDO_MAX_CHARS)) size -= presentationUndoHistory.shift().data.length;
      presentationUndoPosition = presentationUndoHistory.length - 1;
      updatePresentationUndoButtons();
      return true;
    }

    function beginPresentationUndoChange() {
      if (presentationUndoRestoring) return;
      checkpointPresentationUndo();
      // Edit handlers write HTML after pushSlideEditHistory; defer the final
      // snapshot until their synchronous action finishes, without renumbering.
      if (presentationUndoPending) return;
      presentationUndoPending = true;
      const epoch = presentationUndoEpoch;
      queueMicrotask(() => {
        if (epoch !== presentationUndoEpoch) return;
        presentationUndoPending = false;
        checkpointPresentationUndo();
      });
    }

    function restorePresentationUndo(position) {
      const snapshot = presentationUndoHistory[position];
      if (!snapshot) return false;
      const state = JSON.parse(snapshot.data);
      presentationUndoRestoring = true;
      presentationUndoEpoch += 1;
      presentationUndoPending = false;
      try {
        tenantSlidesData = state.slides;
        tenantSlidePlan = state.plan;
        tenantSlideGenerationCheckpoint = state.generationCheckpoint;
        if (typeof tenantPresentationProvenance !== 'undefined') tenantPresentationProvenance = state.provenance;
        [slideEditSessions, slideInlineEditStates, slideElementEditStates].forEach(sessions => {
          Object.keys(sessions).forEach(key => delete sessions[key]);
        });
        const last = Math.max(0, tenantSlidesData.length - 1);
        const bounded = value => Math.max(0, Math.min(last, Number.isInteger(value) ? value : 0));
        activeSlideIndex = bounded(snapshot.active);
        tenantChatSlideIndex = bounded(snapshot.chat);
        tenantChatFocusIndexes = [...new Set(snapshot.focus.filter(index => Number.isInteger(index)
          && index >= 1 && index <= tenantSlidesData.length))];
        renumberTenantSlides();
        renderTenantSlides();
        // Rendering rebuilds a minimal plan: preserve full generation/media metadata.
        tenantSlidePlan = state.plan;
        tenantProjectData = { ...tenantProjectData, tenantSlidesData, tenantSlidePlan,
          slide_generation_checkpoint: tenantSlideGenerationCheckpoint };
        selectTenantSlide(activeSlideIndex, true);
        tenantChatSlideIndex = bounded(snapshot.chat);
        presentationUndoPosition = position;
        presentationUndoHistory[position] = capturePresentationUndo();
        setDraftDirty(true);
      } finally {
        presentationUndoRestoring = false;
        updatePresentationUndoButtons();
      }
      return true;
    }

    function undoPresentationChange() {
      if (!presentationUndoAvailable()) return false;
      checkpointPresentationUndo();
      return presentationUndoPosition > 0 && restorePresentationUndo(presentationUndoPosition - 1);
    }

    function redoPresentationChange() {
      if (!presentationUndoAvailable()) return false;
      checkpointPresentationUndo();
      return presentationUndoPosition < presentationUndoHistory.length - 1
        && restorePresentationUndo(presentationUndoPosition + 1);
    }

    function handlePresentationUndoKey(event) {
      const key = String(event.key || '').toLowerCase();
      if (event.defaultPrevented || event.isComposing || event.altKey || !(event.ctrlKey || event.metaKey)
        || !['z', 'y'].includes(key) || (key === 'y' && event.shiftKey)) return;
      if (!document.getElementById('tenantSlidesPage')?.classList.contains('active')
        || !hasPermission('create_presentation') || presentationUndoBusy()) return;
      const nativeEditor = el => el && (el.isContentEditable
        || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)
        || el.closest?.('[contenteditable]:not([contenteditable="false"]),[role="textbox"]'));
      if (nativeEditor(event.target) || nativeEditor(document.activeElement)) return;
      const redo = key === 'y' || event.shiftKey;
      const card = event.target?.closest?.('.ge-slide-card');
      const index = card ? Number(String(card.id).replace('slide-card-', '')) : activeSlideIndex;
      const session = getSlideEditSession(index);
      if (session) {
        event.preventDefault();
        if (redo) redoSlideEdit(index); else undoSlideEdit(index);
      } else if (!Object.keys(slideEditSessions).length) {
        const changed = redo ? redoPresentationChange() : undoPresentationChange();
        if (changed) event.preventDefault();
      }
    }

    document.addEventListener('keydown', handlePresentationUndoKey);
    // End presentation undo helpers.

    function getSlideEditSession(index) {
      const session = slideEditSessions[index];
      if (!session) return null;
      const slide = tenantSlidesData[index];
      if (!slide || slideEditFingerprint(slide) !== session.fp) {
        delete slideEditSessions[index];
        return null;
      }
      return session;
    }

    function touchSlideEditSession(index) {
      const session = slideEditSessions[index];
      const slide = tenantSlidesData[index];
      if (!session || !slide) return;
      session.fp = slideEditFingerprint(slide);
    }

    function pushSlideEditHistory(index) {
      beginPresentationUndoChange();
      const session = getSlideEditSession(index);
      if (!session || !tenantSlidesData[index]) return false;
      session.undo.push(tenantSlidesData[index].html);
      if (session.undo.length > SLIDE_EDIT_HISTORY_LIMIT) session.undo.shift();
      session.redo = [];
      refreshSlideEditToolbar(index);
      return true;
    }

    function syncSlideEditSessionsAfterRender() {
      try {
        Object.keys(slideEditSessions).forEach(k => {
          const idx = Number(k);
          const sess = slideEditSessions[k];
          const sld = tenantSlidesData[idx];
          if (!sess || !sld) { delete slideEditSessions[k]; return; }
          sess.fp = slideEditFingerprint(sld);
        });
      } catch (err) {}
    }

    function startSlideEditSession(index) {
      if (!hasPermission('create_presentation')) return;
      const slide = tenantSlidesData[index];
      if (!slide || !slide.html) return;
      slideEditSessions[index] = {
        originalHtml: slide.html, undo: [], redo: [], sel: null,
        fp: slideEditFingerprint(slide)
      };
      slideInlineEditStates[index] = true;
      slideElementEditStates[index] = true;
      updatePresentationUndoButtons();
      refreshSingleSlideCard(index);
      toast('وضع التحرير مفعّل لهذه الشريحة');
    }

    function commitSlideEditSession(index) {
      if (!slideEditSessions[index]) return;
      const ae = document.activeElement;
      if (ae && ae.blur && ae.closest && ae.closest('.tenant-slide-stage')) ae.blur();
      endSlideEditSession(index, true);
    }

    function endSlideEditSession(index, keep) {
      beginPresentationUndoChange();
      const session = slideEditSessions[index];
      if (keep !== true && session && tenantSlidesData[index]) {
        tenantSlidesData[index].html = session.originalHtml;
        tenantProjectData.tenantSlidesData = tenantSlidesData;
      } else if (keep === true && tenantSlidesData[index]) {
        tenantSlidesData[index]._designer_keep_html = true;
        tenantSlidesData[index].is_custom = true;
      }
      delete slideEditSessions[index];
      slideInlineEditStates[index] = false;
      slideElementEditStates[index] = false;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      if (keep === true && presentationUndoPosition >= 0) {
        // Approval changes edit metadata, not deck content; merge it into the
        // latest edit so one deck undo still restores the previous content.
        presentationUndoHistory[presentationUndoPosition] = capturePresentationUndo();
      }
      updatePresentationUndoButtons();
      toast(keep === true ? 'تم اعتماد تعديلات الشريحة' : 'تم إلغاء تعديلات الشريحة');
    }

    function undoSlideEdit(index) {
      const session = getSlideEditSession(index);
      if (!session || !session.undo.length) { toast('لا توجد خطوات للتراجع'); return; }
      beginPresentationUndoChange();
      const slide = tenantSlidesData[index];
      session.redo.push(slide.html);
      slide.html = session.undo.pop();
      session.sel = null;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
    }

    function redoSlideEdit(index) {
      const session = getSlideEditSession(index);
      if (!session || !session.redo.length) { toast('لا توجد خطوات للتقدم'); return; }
      beginPresentationUndoChange();
      const slide = tenantSlidesData[index];
      session.undo.push(slide.html);
      slide.html = session.redo.pop();
      session.sel = null;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
    }

    function slideStageForIndex(index) {
      const card = document.getElementById('slide-card-' + index);
      return card ? card.querySelector('.tenant-slide-stage') : null;
    }

    /* Deck watermark inheritance: the overlay div is deck chrome. A freshly
       generated slide (chat insert, single or section regeneration) carries no
       watermark, so the deck copy is cloned into it — the same spec the server
       keeps with _carry_slide_watermark. */
    function watermarkMarkupFromHtml(html) {
      const source = String(html || '');
      let match = source.match(/<div\b[^>]*\bdata-slide-watermark=["']true["'][^>]*>[\s\S]*?<\/div\s*>/i);
      if (!match) match = source.match(/<div\b[^>]*\bclass=["'][^"']*\bslide-watermark\b[^"']*["'][^>]*>[\s\S]*?<\/div\s*>/i);
      return match ? match[0] : '';
    }

    function isWatermarkVisible(html) {
      const markup = watermarkMarkupFromHtml(html);
      if (!markup) return false;
      const tagEnd = markup.indexOf('>');
      const tag = tagEnd === -1 ? markup : markup.slice(0, tagEnd + 1);
      const attr = tag.match(/data-watermark-visible\s*=\s*["']([^"']*)["']/i);
      // Overlays saved before the visibility flag carry no attribute and
      // count as visible, so opening an older presentation never flips them.
      if (attr) {
        if (String(attr[1]).trim().toLowerCase() === 'false') return false;
      }
      if (/display\s*:\s*none/i.test(tag)) return false;
      return true;
    }

    function setWatermarkMarkupVisible(markup, visible) {
      let out = String(markup || '');
      if (!out) return out;
      const end = out.indexOf('>');
      if (end === -1) return out;
      let tag = out.slice(0, end + 1);
      const rest = out.slice(end + 1);
      if (/data-watermark-visible\s*=/i.test(tag)) {
        tag = tag.replace(/data-watermark-visible\s*=\s*["'][^"']*["']/i,
          'data-watermark-visible="' + (visible ? 'true' : 'false') + '"');
      } else {
        tag = tag.slice(0, -1) + ' data-watermark-visible="' + (visible ? 'true' : 'false') + '">';
      }
      if (visible) {
        tag = tag.replace(/display\s*:\s*none\s*;?/gi, 'display:flex;');
      } else if (/display\s*:\s*flex/i.test(tag)) {
        tag = tag.replace(/display\s*:\s*flex/i, 'display:none');
      } else if (/display\s*:/i.test(tag)) {
        tag = tag.replace(/display\s*:\s*[^;]+/i, 'display:none');
      } else {
        const styleMatch = tag.match(/style\s*=\s*(["'])(.*?)\1/i);
        if (styleMatch) {
          tag = tag.slice(0, styleMatch.index) + 'style=' + styleMatch[1] + 'display:none;'
            + styleMatch[2] + styleMatch[1] + tag.slice(styleMatch.index + styleMatch[0].length);
        } else {
          tag = tag.slice(0, -1) + ' style="display:none;">';
        }
      }
      return tag + rest;
    }

    function watermarkSrcKey(url) {
      return String(url || '').split('?')[0].split('#')[0].trim();
    }

    function refreshWatermarkSrc(html, newUrl) {
      const markup = watermarkMarkupFromHtml(html);
      if (!markup || !newUrl) return html;
      const srcMatch = markup.match(/<img\b[^>]*\bsrc\s*=\s*["']([^"']*)["']/i);
      const current = srcMatch ? srcMatch[1] : '';
      if (watermarkSrcKey(current) === watermarkSrcKey(newUrl)) return html;
      const refreshed = markup.replace(/(<img\b[^>]*\bsrc\s*=\s*["'])[^"']*(["'])/i,
        '$1' + newUrl.replace(/\$/g, '$$$$') + '$2');
      return String(html).replace(markup, refreshed);
    }

    function setHtmlWatermarkVisible(html, visible) {
      const markup = watermarkMarkupFromHtml(html);
      if (!markup) return html;
      return String(html).replace(markup, setWatermarkMarkupVisible(markup, visible));
    }

    function stripWatermarkMarkup(html) {
      let out = String(html || '');
      out = out.replace(/<div\b[^>]*\bdata-slide-watermark=["']true["'][^>]*>[\s\S]*?<\/div\s*>/gi, '');
      out = out.replace(/<div\b[^>]*\bclass=["'][^"']*\bslide-watermark\b[^"']*["'][^>]*>[\s\S]*?<\/div\s*>/gi, '');
      return out;
    }

    function normalizeWatermarkLayer(markup) {
      let out = String(markup || '');
      if (!out) return out;
      // Watermarks stored before the on-top fix carry z-index:0 and sit behind
      // opaque cards. Cloning them verbatim would keep them buried.
      out = out.replace(/z-index\s*:\s*0(?![\d.])/gi, 'z-index:50');
      return out;
    }

    function copyWatermarkMarkup(sourceHtml, targetHtml) {
      if (!targetHtml) return targetHtml;
      const markup = normalizeWatermarkLayer(watermarkMarkupFromHtml(sourceHtml));
      if (!markup) return targetHtml;
      if (watermarkMarkupFromHtml(targetHtml)) return targetHtml;
      const cleaned = stripWatermarkMarkup(targetHtml);
      const closing = cleaned.match(/<\/div\s*>\s*$/i);
      if (!closing || closing.index === undefined) return cleaned + markup;
      return cleaned.slice(0, closing.index) + markup + cleaned.slice(closing.index);
    }

    function tenantWatermarkMarkup() {
      const watermarkUrl = String((tenantBranding && tenantBranding.watermark_path) || '').trim();
      if (!watermarkUrl) return '';
      const safeUrl = escapeHtml(watermarkUrl);
      return '<div class="slide-watermark" data-slide-watermark="true" data-watermark-visible="true" aria-hidden="true" '
        + 'style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
        + 'pointer-events:none;z-index:50;opacity:0.045;overflow:hidden;">'
        + '<img src="' + safeUrl + '" alt="" style="width:480px;max-width:50%;max-height:50%;'
        + 'object-fit:contain;filter:grayscale(100%) brightness(0) invert(53.3%);"></div>';
    }

    function setSlideWatermarkVisibility(index, visible) {
      const session = getSlideEditSession(index);
      const slide = tenantSlidesData[index];
      if (!session || !slide || !slide.html) return false;
      const markup = watermarkMarkupFromHtml(slide.html);
      const shown = isWatermarkVisible(slide.html);
      const currentUrl = String((tenantBranding && tenantBranding.watermark_path) || '').trim();
      if (visible && !currentUrl && !markup) {
        toast('لم تُرفع علامة مائية للشركة');
        refreshSlideEditToolbar(index);
        return false;
      }
      // Showing re-points the layer at the current company file, so a
      // replaced upload appears in place of the old mark without losing the
      // saved position/size/opacity.
      if (visible && markup && currentUrl) {
        const refreshed = refreshWatermarkSrc(slide.html, currentUrl);
        if (refreshed !== slide.html) {
          if (!pushSlideEditHistory(index)) return false;
          slide.html = setHtmlWatermarkVisible(refreshed, true);
          slide._designer_keep_html = true;
          slide.is_custom = true;
          session.sel = null;
          tenantProjectData.tenantSlidesData = tenantSlidesData;
          touchSlideEditSession(index);
          triggerAutoSaveDraft();
          refreshSingleSlideCard(index);
          toast('تم إظهار العلامة المائية');
          return true;
        }
      }
      if (shown === !!visible) return true;
      if (!pushSlideEditHistory(index)) return false;
      if (visible) {
        slide.html = markup
          ? setHtmlWatermarkVisible(slide.html, true)
          : copyWatermarkMarkup(tenantWatermarkMarkup(), stripWatermarkMarkup(slide.html));
      } else {
        // Hiding keeps the saved position/size/opacity so showing it again
        // restores exactly what the user had.
        slide.html = markup ? setHtmlWatermarkVisible(slide.html, false) : slide.html;
      }
      slide._designer_keep_html = true;
      slide.is_custom = true;
      session.sel = null;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      toast(visible ? 'تم إظهار العلامة المائية' : 'تم إخفاء العلامة المائية');
      return true;
    }

    function deckWatermarkMarkup() {
      for (const slide of (tenantSlidesData || [])) {
        const markup = watermarkMarkupFromHtml(slide && slide.html);
        if (markup && isWatermarkVisible(slide && slide.html)) return normalizeWatermarkLayer(markup);
      }
      return '';
    }

    function applyDeckWatermarkToHtml(html) {
      const markup = deckWatermarkMarkup();
      if (!markup || !html) return html;
      return copyWatermarkMarkup(markup, html);
    }

    /* Single-card refresh for manual edit flows (تعديل/اعتماد/الغاء/تراجع/تقدم/حذف
       عنصر/إضافة نص/إضافة صورة). renderTenantSlides() rebuilds every card, which
       makes all slides flash and resets the scroll position. Rebuilding only the
       touched card keeps every other card (and the viewport) exactly where it was. */
    function refreshSingleSlideCard(index) {
      const wrap = document.getElementById('tenantSlidesMain');
      const oldCard = document.getElementById('slide-card-' + index);
      const slide = tenantSlidesData[index];
      if (!wrap || !oldCard || !slide || !slide.html) { renderTenantSlides(); return; }
      const savedScrollTop = wrap.scrollTop;
      const container = document.createElement('div');
      container.className = 'ge-slide-card' + (index === activeSlideIndex ? ' active-slide' : '');
      container.id = 'slide-card-' + index;
      container.style.cssText = 'margin-bottom:24px; position:relative;';
      container.onclick = () => selectTenantSlide(index);
      if (hasPermission('create_presentation')) {
        const editControls = document.createElement('div');
        editControls.className = 'ge-slide-edit-controls';
        const editSession = getSlideEditSession(index);
        slideInlineEditStates[index] = !!editSession;
        slideElementEditStates[index] = !!editSession;
        editControls.innerHTML = slideEditToolbarHTML(index);
        wireSlideEditControls(editControls, index);
        container.appendChild(editControls);
      }
      const stage = document.createElement('div');
      stage.className = 'tenant-slide-stage';
      stage.style.setProperty('--stage-w', '960px');
      stage.style.setProperty('--stage-h', '540px');
      stage.style.setProperty('--slide-scale', '0.75');
      stage.innerHTML = processSlideHtmlClient(slide.html, slide.type)
        || '<div class="slide" style="padding:40px;font-size:24px;background:#fff">' + escapeHtml(slide.title || '') + '</div>';
      if (!stage.querySelector('.slide')) {
        stage.innerHTML = '<div class="slide" style="padding:40px;font-size:24px;background:#fff">' + escapeHtml(slide.title || '') + '</div>';
      }
      container.appendChild(stage);
      oldCard.replaceWith(container);
      autoFitSlideContent(stage);
      enableSlideInlineEditing(stage, index);
      enableSlideElementDragging(stage, index);
      restoreSlideEditSelection(stage, index);
      try {
        wrap.style.scrollBehavior = 'auto';
        wrap.scrollTop = savedScrollTop;
        wrap.style.scrollBehavior = '';
      } catch (err) {
        try { wrap.scrollTop = savedScrollTop; } catch (err2) {}
      }
    }

    function slideEditToolbarHTML(index) {
      const session = getSlideEditSession(index);
      if (!session) {
        return '<button type="button" data-slide-edit-act="edit"'
          + ' aria-label="' + trDynamicI18n('تعديل الشريحة: تعديل النص وتحريك العناصر') + '">' + trDynamicI18n('تعديل') + '</button>';
      }
      const canUndo = session.undo.length > 0;
      const canRedo = session.redo.length > 0;
      const hasSel = !!session.sel;
      const dis = hasSel ? '' : ' disabled';
      const watermarkChecked = isWatermarkVisible(tenantSlidesData[index] && tenantSlidesData[index].html) ? ' checked' : '';
      return '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('الجلسة') + '</span>'
        + '<div class="slide-edit-group-items">'
        + '<button type="button" class="active" data-slide-edit-act="commit">' + trDynamicI18n('اعتماد') + '</button>'
        + '<button type="button" data-slide-edit-act="cancel">' + trDynamicI18n('الغاء') + '</button>'
        + '</div></div>'
        + '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('السجل') + '</span>'
        + '<div class="slide-edit-group-items">'
        + '<button type="button" data-slide-edit-act="undo"' + (canUndo ? '' : ' disabled') + '>' + trDynamicI18n('تراجع') + '</button>'
        + '<button type="button" data-slide-edit-act="redo"' + (canRedo ? '' : ' disabled') + '>' + trDynamicI18n('تقدم') + '</button>'
        + '</div></div>'
        + '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('إضافة') + '</span>'
        + '<div class="slide-edit-group-items">'
        + '<button type="button" data-slide-edit-act="addtext">' + trDynamicI18n('إضافة نص') + '</button>'
        + '<button type="button" data-slide-edit-act="addimage">' + trDynamicI18n('إضافة صورة') + '</button>'
        + '</div></div>'
        + '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('العلامة المائية') + '</span>'
        + '<div class="slide-edit-group-items"><label class="slide-edit-watermark">'
        + '<input type="checkbox" data-slide-edit-watermark="toggle"' + watermarkChecked + '>' + trDynamicI18n('إظهار العلامة المائية')
        + '</label></div></div>'
        + '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('تنسيق النص') + '</span>'
        + '<div class="slide-edit-group-items">'
        + '<button type="button" data-slide-edit-act="fontup"' + dis + '>' + trDynamicI18n('تكبير') + '</button>'
        + '<button type="button" data-slide-edit-act="fontdown"' + dis + '>' + trDynamicI18n('تصغير') + '</button>'
         + '<button type="button" data-slide-edit-act="bold"' + dis + '>' + trDynamicI18n('عريض') + '</button>'
         + '<button type="button" data-slide-edit-act="del"' + dis + '>' + trDynamicI18n('حذف العنصر') + '</button>'
        + '</div></div>'
        + '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('الطبقة') + '</span>'
        + '<div class="slide-edit-group-items">'
        + '<button type="button" data-slide-edit-act="front"' + dis + '>' + trDynamicI18n('أمام') + '</button>'
        + '<button type="button" data-slide-edit-act="back"' + dis + '>' + trDynamicI18n('خلف') + '</button>'
        + '</div></div>'
        + '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('الشفافية') + '</span>'
        + '<div class="slide-edit-group-items">'
        + '<input type="range" min="5" max="100" step="5" value="100" data-slide-edit-opacity="range"'
        + dis + ' style="width:110px" aria-label="' + trDynamicI18n('الشفافية') + '">'
        + '<span data-slide-edit-opacity-readout style="font-size:12px;min-width:38px;text-align:center">100%</span>'
        + '</div></div>'
       + '<div class="slide-edit-group"><span class="slide-edit-group-title">' + trDynamicI18n('الألوان') + '</span>'
        + '<div class="slide-edit-group-items">'
        + '<label class="slide-edit-color">' + trDynamicI18n('لون النص') + '<input type="color" data-slide-edit-color="color" value="#1e293b"'
        + dis + '><input type="text" data-slide-edit-hex="color" value="#1e293b" maxlength="7" spellcheck="false" placeholder="#000000"'
        + dis + '></label>'
        + '<button type="button" class="slide-edit-eyedropper" data-slide-edit-eyedropper="color"' + dis + '>' + trDynamicI18n('قطارة النص') + '</button>'
        + '<label class="slide-edit-color">' + trDynamicI18n('لون الخلفية') + '<input type="color" data-slide-edit-color="background" value="#ffffff"'
        + dis + '><input type="text" data-slide-edit-hex="background" value="#ffffff" maxlength="7" spellcheck="false" placeholder="#ffffff"'
        + dis + '></label>'
        + '<button type="button" class="slide-edit-eyedropper" data-slide-edit-eyedropper="background"' + dis + '>' + trDynamicI18n('قطارة الخلفية') + '</button>'
        + '</div></div>';
    }

    function normalizeHexColor(value) {
      let text = String(value || '').trim();
      if (!text) return '';
      if (text.charAt(0) !== '#') text = '#' + text;
      const short = text.match(/^#([0-9a-fA-F]{3})$/);
      if (short) {
        return '#' + short[1].split('').map(ch => (ch + ch).toLowerCase()).join('');
      }
      const full = text.match(/^#([0-9a-fA-F]{6})$/);
      if (full) return '#' + full[1].toLowerCase();
      return '';
    }

    async function pickSlideElementColorWithEyedropper(index, kind) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('حدد عنصرا أولا'); return; }
      try {
        if (!window.EyeDropper) { toast('القطارة غير مدعومة في هذا المتصفح'); return; }
        const dropper = new window.EyeDropper();
        const result = await dropper.open();
        const hex = normalizeHexColor(result && result.sRGBHex);
        if (!hex) return;
        previewSlideElementColor(index, kind, hex);
        const card = document.getElementById('slide-card-' + index);
        const colorInput = card ? card.querySelector('[data-slide-edit-color="' + kind + '"]') : null;
        if (colorInput) colorInput.value = hex;
        const hexInput = card ? card.querySelector('[data-slide-edit-hex="' + kind + '"]') : null;
        if (hexInput) hexInput.value = hex;
        commitSlideElementColor(index, kind, hex);
      } catch (err) {
        if (err && err.name !== 'AbortError') toast('تعذر التقاط اللون');
      }
    }

    function wireSlideEditControls(editControls, index) {
      editControls.querySelectorAll('[data-slide-edit-act]').forEach(btn => {
        btn.addEventListener('click', event => {
          event.stopPropagation();
          const act = btn.getAttribute('data-slide-edit-act');
          if (act === 'edit') startSlideEditSession(index);
          else if (act === 'commit') commitSlideEditSession(index);
          else if (act === 'cancel') endSlideEditSession(index, false);
          else if (act === 'undo') undoSlideEdit(index);
          else if (act === 'redo') redoSlideEdit(index);
          else if (act === 'addtext') addSlideTextBox(index);
          else if (act === 'addimage') openSlideImagePicker(index);
          else if (act === 'fontup') adjustSlideElementFontSize(index, 2);
          else if (act === 'fontdown') adjustSlideElementFontSize(index, -2);
          else if (act === 'bold') toggleSlideElementBold(index);
          else if (act === 'del') deleteSelectedSlideElement(index);
          else if (act === 'front') adjustSlideElementLayer(index, 1);
          else if (act === 'back') adjustSlideElementLayer(index, -1);
        });
      });
      editControls.querySelectorAll('[data-slide-edit-watermark="toggle"]').forEach(inp => {
        inp.addEventListener('click', event => event.stopPropagation());
        inp.addEventListener('pointerdown', event => event.stopPropagation());
        inp.addEventListener('change', event => {
          event.stopPropagation();
          setSlideWatermarkVisibility(index, inp.checked);
        });
      });
      editControls.querySelectorAll('[data-slide-edit-eyedropper]').forEach(btn => {
        btn.addEventListener('click', event => {
          event.stopPropagation();
          pickSlideElementColorWithEyedropper(index, btn.getAttribute('data-slide-edit-eyedropper') || 'color');
        });
      });
      editControls.querySelectorAll('[data-slide-edit-opacity="range"]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('input', e => {
          e.stopPropagation();
          previewSlideElementOpacity(index, Number(inp.value));
        });
        inp.addEventListener('change', e => {
          e.stopPropagation();
          commitSlideElementOpacity(index, Number(inp.value));
        });
      });
      editControls.querySelectorAll('[data-slide-edit-color]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('input', e => {
          e.stopPropagation();
          const kind = inp.getAttribute('data-slide-edit-color');
          const card = inp.closest('.ge-slide-card');
          const hexInput = card ? card.querySelector('[data-slide-edit-hex="' + kind + '"]') : null;
          if (hexInput) hexInput.value = inp.value;
          previewSlideElementColor(index, kind, inp.value);
        });
        inp.addEventListener('change', e => {
          e.stopPropagation();
          commitSlideElementColor(index, inp.getAttribute('data-slide-edit-color'));
        });
      });
      editControls.querySelectorAll('[data-slide-edit-hex]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('keydown', e => e.stopPropagation());
        const applyHex = commit => {
          const kind = inp.getAttribute('data-slide-edit-hex');
          const hex = normalizeHexColor(inp.value);
          if (!hex) {
            inp.style.borderColor = '#dc2626';
            if (commit) toast('كود اللون غير صالح (مثال #1e293b)');
            return;
          }
          inp.style.borderColor = '';
          inp.value = hex;
          const card = inp.closest('.ge-slide-card');
          const colorInput = card ? card.querySelector('[data-slide-edit-color="' + kind + '"]') : null;
          if (colorInput) colorInput.value = hex;
          previewSlideElementColor(index, kind, hex);
          if (commit) commitSlideElementColor(index, kind, hex);
        };
        inp.addEventListener('input', () => applyHex(false));
        inp.addEventListener('change', () => applyHex(true));
      });
    }
    // Edit toolbars live inside skipped slide cards, so the DOM pass never
    // reaches them: rebuild their labels whenever the UI language changes.
    document.addEventListener('wf:lang', () => {
      try {
        document.querySelectorAll('.ge-slide-edit-controls').forEach(ctl => {
          const card = ctl.closest('[id^="slide-card-"]');
          const idx = card ? Number(String(card.id).replace('slide-card-', '')) : NaN;
          if (!Number.isInteger(idx)) return;
          ctl.innerHTML = slideEditToolbarHTML(idx);
          wireSlideEditControls(ctl, idx);
        });
      } catch (e) { /* ignore */ }
    });

    function refreshSlideEditToolbar(index) {
      const card = document.getElementById('slide-card-' + index);
      const controls = card ? card.querySelector('.ge-slide-edit-controls') : null;
      if (!controls) return;
      controls.innerHTML = slideEditToolbarHTML(index);
      wireSlideEditControls(controls, index);
    }

    function cssColorToHex(value) {
      const text = String(value || '').trim().toLowerCase();
      const hex = text.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
      if (hex) {
        let digits = hex[1];
        if (digits.length === 3) digits = digits.split('').map(ch => ch + ch).join('');
        return '#' + digits.toLowerCase();
      }
      const rgb = text.match(/^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([\d.]+))?\s*\)$/);
      if (rgb) {
        if (rgb[4] !== undefined && Number(rgb[4]) === 0) return '';
        const toHex = n => Math.max(0, Math.min(255, Number(n))).toString(16).padStart(2, '0');
        return '#' + toHex(rgb[1]) + toHex(rgb[2]) + toHex(rgb[3]);
      }
      return '';
    }

    function syncSlideElementToolbar(index) {
      const card = document.getElementById('slide-card-' + index);
      if (!card) return;
      const session = getSlideEditSession(index);
      const hasSel = !!(session && session.sel);
      let textColor = '#1e293b';
      let bgColor = '#ffffff';
      if (hasSel) {
        const stage = card.querySelector('.tenant-slide-stage');
        const slide = stage ? stage.querySelector('.slide') : null;
        const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
        if (target) {
          const cs = window.getComputedStyle(target);
          textColor = cssColorToHex(cs.color) || textColor;
          bgColor = cssColorToHex(cs.backgroundColor) || bgColor;
        }
      }
      card.querySelectorAll('[data-slide-edit-act="del"]').forEach(btn => { btn.disabled = !hasSel; });
      card.querySelectorAll('[data-slide-edit-act="fontup"], [data-slide-edit-act="fontdown"], [data-slide-edit-act="bold"]').forEach(btn => { btn.disabled = !hasSel; });
      card.querySelectorAll('[data-slide-edit-act="front"], [data-slide-edit-act="back"]').forEach(btn => { btn.disabled = !hasSel; });
      card.querySelectorAll('[data-slide-edit-eyedropper]').forEach(btn => { btn.disabled = !hasSel; });
      card.querySelectorAll('[data-slide-edit-color]').forEach(inp => {
        inp.disabled = !hasSel;
        if (hasSel) inp.value = inp.getAttribute('data-slide-edit-color') === 'color' ? textColor : bgColor;
      });
      card.querySelectorAll('[data-slide-edit-hex]').forEach(inp => {
        inp.disabled = !hasSel;
        if (hasSel) inp.value = inp.getAttribute('data-slide-edit-hex') === 'color' ? textColor : bgColor;
      });
      let opacityPct = 100;
      if (hasSel) {
        const stage = card.querySelector('.tenant-slide-stage');
        const slide = stage ? stage.querySelector('.slide') : null;
        let target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
        // Watermark opacity lives on the overlay layer, not the logo img.
        target = watermarkOverlayOf(target) || target;
        if (target) opacityPct = slideElementOpacityPct(target);
      }
      card.querySelectorAll('[data-slide-edit-opacity="range"]').forEach(inp => {
        inp.disabled = !hasSel;
        if (hasSel) inp.value = String(opacityPct);
      });
      card.querySelectorAll('[data-slide-edit-opacity-readout]').forEach(el => {
        el.textContent = opacityPct + '%';
      });
    }

    let slideImageFileInput = null;
    function openSlideImagePicker(index) {
      if (!getSlideEditSession(index)) return;
      if (!slideImageFileInput) {
        slideImageFileInput = document.createElement('input');
        slideImageFileInput.type = 'file';
        slideImageFileInput.accept = 'image/*';
        slideImageFileInput.style.display = 'none';
        slideImageFileInput.addEventListener('change', () => {
          const file = slideImageFileInput.files && slideImageFileInput.files[0];
          const targetIndex = Number(slideImageFileInput.dataset.index || 0);
          slideImageFileInput.value = '';
          if (file) addSlideImageFromDevice(targetIndex, file);
        });
        document.body.appendChild(slideImageFileInput);
      }
      slideImageFileInput.dataset.index = String(index);
      slideImageFileInput.click();
    }

    function toggleSlideElementEditing(index) {
      slideElementEditStates[index] = !slideElementEditStates[index];
      renderTenantSlides();
      toast(slideElementEditStates[index] ? 'تم تفعيل تحريك عناصر الشريحة' : 'تم إيقاف تحريك العناصر');
    }

    function stopEditEvent(e) { e.stopPropagation(); }
    function onInlineEditKey(e) {
      e.stopPropagation();
      if (e.key === 'Escape') { e.target.blur(); }
    }
    function onInlineEditPaste(e) {
      e.preventDefault();
      e.stopPropagation();
      const text = (e.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, text);
    }

    function clearSlideElementSelection(stage) {
      if (!stage) return;
      stage.querySelectorAll('.slide-element-selected').forEach(el => el.classList.remove('slide-element-selected'));
      stage.querySelectorAll('.slide-resize-handle, .slide-move-handle, .slide-element-delete-btn').forEach(el => el.remove());
    }

    function selectSlideElement(stage, index, target, path) {
      const session = getSlideEditSession(index);
      if (!session || !stage || !target) return;
      if (!path || !path.length) return;
      const slide = stage.querySelector('.slide');
      if (slide && target === slide) return;
      clearSlideElementSelection(stage);
      session.sel = {
        path: (path || []).slice(),
        placement: target.getAttribute
          ? (target.getAttribute('data-company-logo-placement')
            || target.getAttribute('data-team-logo-placement') || '') : ''
      };
      target.classList.add('slide-element-selected');
      positionSlideEditHandles(stage, target);
      syncSlideElementToolbar(index);
    }

    function restoreSlideEditSelection(stage, index) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel || !stage) return;
      if (!session.sel.path || !session.sel.path.length) {
        session.sel = null;
        refreshSlideEditToolbar(index);
        return;
      }
      const slide = stage.querySelector('.slide');
      let target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (target && session.sel.placement) {
        const attr = (target.hasAttribute && target.hasAttribute('data-company-logo-placement'))
          ? 'data-company-logo-placement' : 'data-team-logo-placement';
        const safePlacement = String(session.sel.placement).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
        const found = slide.querySelector('[' + attr + '="' + safePlacement + '"]');
        if (found) target = found;
      }
      if (!target || !slide.contains(target) || target === slide) {
        session.sel = null;
        refreshSlideEditToolbar(index);
        return;
      }
      target.classList.add('slide-element-selected');
      positionSlideEditHandles(stage, target);
      syncSlideElementToolbar(index);
    }

    function slideElementIsImageBox(target) {
      if (!target) return false;
      if (target.tagName === 'IMG') return true;
      if (target.hasAttribute && (target.hasAttribute('data-slide-imagebox'))) return true;
      try {
        if (target.children && target.children.length === 1 && target.children[0].tagName === 'IMG') return true;
      } catch (err) {}
      return false;
    }

    function positionSlideEditHandles(stage, target) {
      if (!stage || !target) return;
      stage.querySelectorAll('.slide-resize-handle, .slide-move-handle').forEach(el => el.remove());
      const slide = stage.querySelector('.slide');
      if (!slide || !slide.contains(target)) return;
      if (window.getComputedStyle(slide).position === 'static') slide.style.position = 'relative';
      const scale = Number(stage.style.getPropertyValue('--slide-scale')) || 1;
      const slideRect = slide.getBoundingClientRect();
      const rect = target.getBoundingClientRect();
      const x = (rect.left - slideRect.left) / scale;
      const y = (rect.top - slideRect.top) / scale;
      const w = rect.width / scale;
      const h = rect.height / scale;
      const card = stage.closest('.ge-slide-card');
      const index = card ? Number(String(card.id || '').replace('slide-card-', '')) : NaN;
      if (!Number.isInteger(index)) return;

      const moveHandle = document.createElement('div');
      moveHandle.className = 'slide-move-handle';
      moveHandle.textContent = 'تحريك';
      moveHandle.style.left = Math.max(0, Math.min(x, 1280 - 60)) + 'px';
      moveHandle.style.top = Math.max(0, y - 26) + 'px';
      slide.appendChild(moveHandle);
      moveHandle.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        if (slideElementDragActive) return;
        event.preventDefault();
        event.stopPropagation();
        const path = slideElementPath(slide, target);
        if (!path) return;
        slideElementDragActive = true;
        const startX = event.clientX;
        const startY = event.clientY;
        const baseX = Number(target.dataset.manualTranslateX) || 0;
        const baseY = Number(target.dataset.manualTranslateY) || 0;
        let moved = false;
        const onMove = moveEvent => {
          const dx = (moveEvent.clientX - startX) / scale;
          const dy = (moveEvent.clientY - startY) / scale;
          if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
          target.style.transform = 'translate(' + Math.round(baseX + dx) + 'px, ' + Math.round(baseY + dy) + 'px)';
        };
        const onUp = upEvent => {
          window.removeEventListener('pointermove', onMove, true);
          window.removeEventListener('pointerup', onUp, true);
          window.removeEventListener('pointercancel', onUp, true);
          slideElementDragActive = false;
          const dx = (upEvent.clientX - startX) / scale;
          const dy = (upEvent.clientY - startY) / scale;
          if (moved) commitSlideElementMove(stage, index, target, path, dx, dy);
          selectSlideElement(stage, index, target, path);
        };
        window.addEventListener('pointermove', onMove, true);
        window.addEventListener('pointerup', onUp, true);
        window.addEventListener('pointercancel', onUp, true);
      });

      const HANDLE_DEFS = [
        { dir: 'nw', cursor: 'nwse' }, { dir: 'ne', cursor: 'nesw' },
        { dir: 'sw', cursor: 'nesw' }, { dir: 'se', cursor: 'nwse' },
        { dir: 'n', cursor: 'ns' }, { dir: 's', cursor: 'ns' },
        { dir: 'w', cursor: 'ew' }, { dir: 'e', cursor: 'ew' }
      ];
      const HS = 16;
      const half = HS / 2;
      const positions = {
        nw: [x - half, y - half], ne: [x + w - half, y - half],
        sw: [x - half, y + h - half], se: [x + w - half, y + h - half],
        n: [x + w / 2 - half, y - half], s: [x + w / 2 - half, y + h - half],
        w: [x - half, y + h / 2 - half], e: [x + w - half, y + h / 2 - half]
      };
      HANDLE_DEFS.forEach(def => {
        const handle = document.createElement('div');
        handle.className = 'slide-resize-handle rh-' + def.dir;
        handle.dataset.resizeDir = def.dir;
        handle.title = 'سحب للتحجيم';
        const pos = positions[def.dir];
        handle.style.left = Math.max(-half, Math.min(pos[0], 1280 - half)) + 'px';
        handle.style.top = Math.max(-half, Math.min(pos[1], 720 - half)) + 'px';
        slide.appendChild(handle);
        handle.addEventListener('pointerdown', event => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.stopPropagation();
          startSlideElementResize(stage, index, slide, target, def.dir, scale, event);
        });
      });
    }

    /* Free resize in any direction: the edge opposite the drag stays visually
       fixed by compensating with translate. This works for absolute and flow
       elements, LTR and RTL, without rewriting the element positioning. */
    function startSlideElementResize(stage, index, slide, target, dir, scale, event) {
      if (slideElementDragActive) return;
      const path = slideElementPath(slide, target);
      if (!path) return;
      const touchW = dir.indexOf('e') !== -1 || dir.indexOf('w') !== -1;
      const touchH = dir.indexOf('n') !== -1 || dir.indexOf('s') !== -1;
      if (!touchW && !touchH) return;
      slideElementDragActive = true;
      // A hand-resized watermark logo owns its size: drop the 50% display caps
      // before measuring, or the drag would start from the clamped box and the
      // commit would shrink the stored width.
      if (target.tagName === 'IMG' && watermarkOverlayOf(target)) {
        target.style.maxWidth = 'none';
        target.style.maxHeight = 'none';
      }
      const measure = () => {
        const sRect = slide.getBoundingClientRect();
        const r = target.getBoundingClientRect();
        return {
          left: (r.left - sRect.left) / scale,
          top: (r.top - sRect.top) / scale,
          width: r.width / scale,
          height: r.height / scale
        };
      };
      const base = measure();
      const startX = event.clientX;
      const startY = event.clientY;
      const computed = window.getComputedStyle(target);
      const isImage = slideElementIsImageBox(target);
      const explicitHeight = !!(computed.height && computed.height !== 'auto');
      let baseTx = Number(target.dataset.manualTranslateX) || 0;
      let baseTy = Number(target.dataset.manualTranslateY) || 0;
      let foreignPrefix = '';
      const inlineTransform = String(target.style.transform || '').trim();
      if (inlineTransform && !/^translate\(\s*-?\d+(?:\.\d+)?px\s*,\s*-?\d+(?:\.\d+)?px\s*\)$/.test(inlineTransform)) {
        foreignPrefix = inlineTransform;
        baseTx = 0;
        baseTy = 0;
      }
      let displayPromoted = false;
      if (computed.display === 'inline') {
        target.style.display = 'inline-block';
        displayPromoted = true;
      }
      const writeTransform = (tx, ty) => {
        target.style.transform = (foreignPrefix ? foreignPrefix + ' ' : '')
          + 'translate(' + Math.round(tx) + 'px, ' + Math.round(ty) + 'px)';
      };
      let compX = 0;
      let compY = 0;
      let moved = false;
      writeTransform(baseTx, baseTy);
      const onMove = moveEvent => {
        const dw = (moveEvent.clientX - startX) / scale;
        const dh = (moveEvent.clientY - startY) / scale;
        if (Math.abs(dw) + Math.abs(dh) > 2) moved = true;
        let newW = base.width;
        let newH = base.height;
        if (dir.indexOf('e') !== -1) newW = base.width + dw;
        if (dir.indexOf('w') !== -1) newW = base.width - dw;
        if (dir.indexOf('s') !== -1) newH = base.height + dh;
        if (dir.indexOf('n') !== -1) newH = base.height - dh;
        newW = Math.max(24, Math.min(1280, Math.round(newW)));
        newH = Math.max(24, Math.min(720, Math.round(newH)));
        if (touchW) target.style.width = newW + 'px';
        if (touchH) {
          if (isImage) target.style.height = newH + 'px';
          else {
            target.style.minHeight = newH + 'px';
            if (explicitHeight) target.style.height = newH + 'px';
          }
        }
        const m = measure();
        if (dir.indexOf('e') !== -1) compX += (base.left - m.left);
        else if (dir.indexOf('w') !== -1) compX += ((base.left + base.width) - (m.left + m.width));
        if (dir.indexOf('s') !== -1) compY += (base.top - m.top);
        else if (dir.indexOf('n') !== -1) compY += ((base.top + base.height) - (m.top + m.height));
        writeTransform(baseTx + compX, baseTy + compY);
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove, true);
        window.removeEventListener('pointerup', onUp, true);
        window.removeEventListener('pointercancel', onUp, true);
        slideElementDragActive = false;
        if (!moved) return;
        const finalTx = Math.round(baseTx + compX);
        const finalTy = Math.round(baseTy + compY);
        writeTransform(finalTx, finalTy);
        const finalW = touchW ? (parseFloat(target.style.width) || base.width) : null;
        let finalH = null;
        if (touchH) {
          if (isImage) finalH = parseFloat(target.style.height) || base.height;
          else finalH = parseFloat(target.style.minHeight) || parseFloat(target.style.height) || base.height;
        }
        commitSlideElementResize(stage, index, target, path, {
          width: finalW, height: finalH, tx: finalTx, ty: finalTy,
          isImage: isImage, explicitHeight: explicitHeight,
          displayPromoted: displayPromoted, foreignPrefix: foreignPrefix
        });
        selectSlideElement(stage, index, target, path);
      };
      window.addEventListener('pointermove', onMove, true);
      window.addEventListener('pointerup', onUp, true);
      window.addEventListener('pointercancel', onUp, true);
    }

    function commitSlideElementResize(stage, index, target, path, size) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html || !target) return;
      if (!getSlideEditSession(index)) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const rawTarget = rawRoot && findSlideRawTarget(rawRoot, target, path);
      if (!rawRoot || !rawTarget) { renderTenantSlides(); return; }
      const widthPx = size && typeof size === 'object' ? size.width : size;
      const heightPx = size && typeof size === 'object' ? size.height : null;
      const isImage = !!(size && typeof size === 'object' && size.isImage);
      const explicitHeight = !!(size && typeof size === 'object' && size.explicitHeight);
      pushSlideEditHistory(index);
      if (widthPx !== null && widthPx !== undefined) {
        const widthValue = Math.max(24, Math.min(1280, Math.round(widthPx))) + 'px';
        target.style.width = widthValue;
        rawTarget.style.width = widthValue;
      }
      if (heightPx !== null && heightPx !== undefined) {
        const heightValue = Math.max(24, Math.min(720, Math.round(heightPx))) + 'px';
        if (isImage) {
          target.style.height = heightValue;
          rawTarget.style.height = heightValue;
        } else {
          target.style.minHeight = heightValue;
          rawTarget.style.minHeight = heightValue;
          if (explicitHeight) {
            target.style.height = heightValue;
            rawTarget.style.height = heightValue;
          }
        }
      }
      if (size && typeof size === 'object' && (size.tx !== undefined || size.ty !== undefined)) {
        const liveTransform = String(target.style.transform || '');
        rawTarget.style.transform = liveTransform;
        const m = liveTransform.match(/translate\(\s*(-?\d+)px\s*,\s*(-?\d+)px\s*\)\s*$/);
        const dx = m ? m[1] : String(Math.round(size.tx || 0));
        const dy = m ? m[2] : String(Math.round(size.ty || 0));
        target.dataset.manualTranslateX = dx;
        target.dataset.manualTranslateY = dy;
        if (rawTarget.dataset) {
          rawTarget.dataset.manualTranslateX = dx;
          rawTarget.dataset.manualTranslateY = dy;
        }
      }
      if (size && typeof size === 'object' && size.displayPromoted) {
        rawTarget.style.display = 'inline-block';
      }
      // Persist the caps dropped at drag start, or the next reload would clamp
      // the hand-picked watermark size back to 50% of the slide.
      if (target.tagName === 'IMG' && watermarkOverlayOf(target)) {
        target.style.maxWidth = 'none';
        target.style.maxHeight = 'none';
      }
      if (rawTarget.tagName === 'IMG' && watermarkOverlayOf(rawTarget)) {
        rawTarget.style.maxWidth = 'none';
        rawTarget.style.maxHeight = 'none';
      }
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      toast('تم تغيير حجم العنصر');
    }

    function applySlideElementColorValue(root, kind, value) {
      if (!root) return;
      if (kind === 'color') {
        root.style.color = value;
        try {
          root.querySelectorAll('*').forEach(el => {
            el.style.color = value;
            const tag = String(el.tagName || '').toLowerCase();
            if (tag === 'svg' || tag === 'path' || tag === 'rect' || tag === 'circle' || tag === 'ellipse' || tag === 'polygon' || tag === 'polyline' || tag === 'line' || tag === 'text' || tag === 'tspan') {
              try { el.style.fill = value; } catch (err) {}
            }
          });
          const rootTag = String(root.tagName || '').toLowerCase();
          if (rootTag === 'svg' || rootTag === 'path' || rootTag === 'rect' || rootTag === 'circle' || rootTag === 'ellipse' || rootTag === 'polygon') {
            try { root.style.fill = value; } catch (err) {}
          }
        } catch (err) {}
      } else {
        root.style.backgroundColor = value;
        try {
          const rootTag = String(root.tagName || '').toLowerCase();
          if (rootTag === 'svg' || rootTag === 'path' || rootTag === 'rect' || rootTag === 'circle' || rootTag === 'ellipse' || rootTag === 'polygon') {
            try { root.style.fill = value; } catch (err) {}
          }
        } catch (err) {}
      }
    }

    function previewSlideElementColor(index, kind, value) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) return;
      const hex = normalizeHexColor(value) || value;
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      applySlideElementColorValue(target, kind, hex);
    }

    function commitSlideElementColor(index, kind, explicitValue) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) return;
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      const card = document.getElementById('slide-card-' + index);
      const input = card ? card.querySelector('[data-slide-edit-color="' + kind + '"]') : null;
      const value = normalizeHexColor(explicitValue || (input && input.value)) || (input && input.value);
      if (!target || !value) return;
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const rawTarget = rawRoot && findSlideRawTarget(rawRoot, target, session.sel.path);
      if (!rawRoot || !rawTarget) { renderTenantSlides(); return; }
      pushSlideEditHistory(index);
      applySlideElementColorValue(target, kind, value);
      applySlideElementColorValue(rawTarget, kind, value);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      syncSlideElementToolbar(index);
      toast('تم تغيير لون العنصر');
    }

    function slideElementOpacityPct(el) {
      try {
        const value = parseFloat(window.getComputedStyle(el).opacity);
        if (isFinite(value)) return Math.max(5, Math.min(100, Math.round(value * 100)));
      } catch (err) {}
      return 100;
    }

    function previewSlideElementOpacity(index, pct) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) return;
      const clamped = Math.max(5, Math.min(100, Math.round(Number(pct) || 100)));
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      (watermarkOverlayOf(target) || target).style.opacity = String(clamped / 100);
      const card = document.getElementById('slide-card-' + index);
      const readout = card ? card.querySelector('[data-slide-edit-opacity-readout]') : null;
      if (readout) readout.textContent = clamped + '%';
    }

    function commitSlideElementOpacity(index, pct) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('حدد عنصرا أولا'); return; }
      const clamped = Math.max(5, Math.min(100, Math.round(Number(pct) || 100)));
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const rawTarget = rawRoot && findSlideRawTarget(rawRoot, target, session.sel.path);
      if (!rawRoot || !rawTarget) { renderTenantSlides(); return; }
      pushSlideEditHistory(index);
      (watermarkOverlayOf(target) || target).style.opacity = String(clamped / 100);
      (watermarkOverlayOf(rawTarget) || rawTarget).style.opacity = String(clamped / 100);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      syncSlideElementToolbar(index);
      toast('تم ضبط شفافية العنصر ' + clamped + '%');
    }

    function slideElementFontSizePx(el) {
      try {
        const cs = window.getComputedStyle(el);
        const size = parseFloat(cs.fontSize);
        if (size && isFinite(size)) return size;
      } catch (err) {}
      return 16;
    }

    function applySlideElementFontSize(root, newSize, ratio) {
      if (!root) return;
      root.style.fontSize = Math.round(newSize) + 'px';
      try {
        root.querySelectorAll('*').forEach(el => {
          const inline = el.style && el.style.fontSize;
          if (inline) {
            const current = parseFloat(inline);
            if (current && isFinite(current)) {
              el.style.fontSize = Math.max(8, Math.min(120, Math.round(current * ratio))) + 'px';
            } else {
              el.style.fontSize = Math.round(newSize) + 'px';
            }
          }
        });
      } catch (err) {}
    }

    function adjustSlideElementFontSize(index, delta) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('حدد عنصرا أولا'); return; }
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      const current = slideElementFontSizePx(target);
      const next = Math.max(8, Math.min(120, Math.round(current + delta)));
      if (next === Math.round(current)) return;
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const rawTarget = rawRoot && findSlideRawTarget(rawRoot, target, session.sel.path);
      if (!rawRoot || !rawTarget) { renderTenantSlides(); return; }
      pushSlideEditHistory(index);
      const ratio = next / (current || next);
      applySlideElementFontSize(target, next, ratio);
      applySlideElementFontSize(rawTarget, next, ratio);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      const selPath = session.sel.path;
      selectSlideElement(stage, index, target, selPath);
      toast('حجم النص ' + next + 'px');
    }

    function applySlideElementBold(root, makeBold) {
      if (!root) return;
      root.style.fontWeight = makeBold ? '700' : '400';
      try {
        root.querySelectorAll('*').forEach(el => { el.style.fontWeight = makeBold ? '700' : '400'; });
      } catch (err) {}
    }

    function toggleSlideElementBold(index) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('حدد عنصرا أولا'); return; }
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      let weight = 400;
      try { weight = parseInt(window.getComputedStyle(target).fontWeight, 10) || 400; } catch (err) {}
      if (String(window.getComputedStyle(target).fontWeight).toLowerCase() === 'bold') weight = 700;
      const makeBold = weight < 600;
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const rawTarget = rawRoot && findSlideRawTarget(rawRoot, target, session.sel.path);
      if (!rawRoot || !rawTarget) { renderTenantSlides(); return; }
      pushSlideEditHistory(index);
      applySlideElementBold(target, makeBold);
      applySlideElementBold(rawTarget, makeBold);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      selectSlideElement(stage, index, target, session.sel.path);
      toast(makeBold ? 'تم جعل النص عريضا' : 'تم جعل النص عاديا');
    }

    function deleteSelectedSlideElement(index) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('لا يوجد عنصر محدد'); return; }
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!stage || !target) { session.sel = null; refreshSlideEditToolbar(index); return; }
      commitSlideElementDelete(stage, index, target, session.sel.path);
    }

    /* Manual layer order: move the selected element (including the watermark
       overlay) forward or backward without touching anything else. */
    function adjustSlideElementLayer(index, direction) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('حدد عنصرا أولا'); return; }
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      // Layer order belongs to the watermark overlay itself: re-stacking the
      // logo img alone would do nothing visible inside its own layer.
      const layerTarget = watermarkOverlayOf(target) || target;
      let current = 0;
      try {
        const inline = parseInt(layerTarget.style.zIndex, 10);
        if (isFinite(inline)) current = inline;
        else {
          const computed = parseInt(window.getComputedStyle(layerTarget).zIndex, 10);
          if (isFinite(computed)) current = computed;
        }
      } catch (err) {}
      const next = Math.max(0, Math.min(200, current + (direction > 0 ? 10 : -10)));
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const rawTarget = rawRoot && findSlideRawTarget(rawRoot, target, session.sel.path);
      if (!rawRoot || !rawTarget) { renderTenantSlides(); return; }
      pushSlideEditHistory(index);
      const rawLayerTarget = watermarkOverlayOf(rawTarget) || rawTarget;
      if (!layerTarget.style.position || layerTarget.style.position === 'static') layerTarget.style.position = 'relative';
      layerTarget.style.zIndex = String(next);
      if (!rawLayerTarget.style.position || rawLayerTarget.style.position === 'static') rawLayerTarget.style.position = 'relative';
      rawLayerTarget.style.zIndex = String(next);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      selectSlideElement(stage, index, target, session.sel.path);
      toast(direction > 0 ? 'تم تقديم العنصر للأمام' : 'تم إرجاع العنصر للخلف');
    }

    function addSlideTextBox(index) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      if (!getSlideEditSession(index)) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      if (window.getComputedStyle && rawRoot.style && !rawRoot.style.position) rawRoot.style.position = 'relative';
      pushSlideEditHistory(index);
      const existingCount = rawRoot.querySelectorAll('[data-slide-textbox]').length;
      const cascade = (existingCount % 6) * 28;
      const top = 260 + cascade;
      const right = 400 + cascade;
      const box = rawDoc.createElement('div');
      box.setAttribute('data-slide-textbox', '1');
      box.setAttribute('style', 'position:absolute;top:' + top + 'px;right:' + right + 'px;width:400px;min-height:60px;'
        + 'padding:12px 16px;box-sizing:border-box;background:#ffffff;border:1px solid #e2e8f0;'
        + 'box-shadow:0 2px 12px rgba(15,40,70,.08);'
        + 'border-radius:10px;color:#1e293b;font-size:18px;font-weight:600;text-align:center;z-index:5;');
      box.textContent = 'نص جديد';
      rawRoot.appendChild(box);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      toast('تمت إضافة مربع نص جديد');
      setTimeout(() => {
        try {
          if (!getSlideEditSession(index)) return;
          const stage = slideStageForIndex(index);
          const slide = stage ? stage.querySelector('.slide') : null;
          if (!stage || !slide) return;
          const boxes = slide.querySelectorAll('[data-slide-textbox]');
          const newBox = boxes[boxes.length - 1];
          if (!newBox) return;
          const path = slideElementPath(slide, newBox);
          if (!path) return;
          selectSlideElement(stage, index, newBox, path);
          const editable = newBox.hasAttribute('contenteditable') ? newBox
            : (newBox.querySelector('[contenteditable]') || newBox);
          if (editable && editable.focus) {
            editable.focus({ preventScroll: true });
            try {
              const range = document.createRange();
              range.selectNodeContents(editable);
              const sel = window.getSelection();
              if (sel) { sel.removeAllRanges(); sel.addRange(range); }
            } catch (err) {}
          }
        } catch (err) {}
      }, 350);
    }