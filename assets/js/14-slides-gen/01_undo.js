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

