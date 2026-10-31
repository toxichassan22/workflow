/* Slide element drag/hover/delete chrome, split from 02_slides_progress.js
   to keep each part under the file-size limit. */

    /* A static "shape": a block with its own visible surface (background,
       image, border or shadow). These are the cards and panels behind texts
       in flow layouts. Outline is deliberately ignored: hover and selection
       outlines must never make an element look like a shape. */
    function slideNodeIsVisualShape(node, style) {
      if (!node || !style) return false;
      const bg = String(style.backgroundColor || '').trim().toLowerCase();
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return true;
      const bgImg = String(style.backgroundImage || '').trim().toLowerCase();
      if (bgImg && bgImg !== 'none') return true;
      const borderW = parseFloat(style.borderTopWidth) || 0;
      const borderStyle = String(style.borderTopStyle || '').trim().toLowerCase();
      if (borderW > 0 && borderStyle && borderStyle !== 'none') return true;
      const shadow = String(style.boxShadow || '').trim().toLowerCase();
      if (shadow && shadow !== 'none') return true;
      return false;
    }

    /* Watermark-aware target: geometry ops (frame/move/resize) use the logo img
       itself, while overlay-level ops (opacity/layer/delete) walk back up via
       watermarkOverlayOf(). */
    function watermarkOverlayOf(node) {
      if (!node || !node.closest) return null;
      return node.closest('[data-slide-watermark="true"], .slide-watermark');
    }

    /* Managed chrome (header/footer bars) is a direct child of the slide root.
       Element edits treat the bar as one element: a click on its logo, accent
       strip, inner wrappers or gaps selects the bar, and layer ops applied to
       a text selection inside it hoist to the bar. Nested <header>/<footer>
       (e.g. inside a card) are not chrome — their parent is not the slide. */
    function slideChromeOf(slideRoot, node) {
      const chrome = node && node.closest
        ? node.closest('[data-slide-header], [data-slide-footer], header, footer')
        : null;
      return (chrome && slideRoot && chrome.parentElement === slideRoot) ? chrome : null;
    }

    function slideDragTarget(slide, source) {
      if (!slide || !source || source === slide) return null;
      if (source.closest && source.closest('.slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return null;
      if (source.closest && source.closest('[contenteditable]')) return null;
      const chrome = slideChromeOf(slide, source);
      if (chrome) return chrome;
      if (source.closest && source.closest('[data-slide-table]')) {
        const tableBox = source.closest('[data-slide-table]');
        const table = tableBox && (tableBox.tagName === 'TABLE'
          ? tableBox : tableBox.querySelector('table'));
        if (tableBox && slide.contains(tableBox)
          && (!table || table.contains(source) || source === tableBox)) return tableBox;
      }
      if (source.closest && source.closest('[data-slide-textbox], [data-slide-imagebox]')) {
        const box = source.closest('[data-slide-textbox], [data-slide-imagebox]');
        if (box && slide.contains(box)) return box;
      }
      if (source.closest && source.closest('.presentation-chrome-logo')) return null;
      /* Watermark layer: selectable in edit mode so it can be dragged,
         restacked or deleted per slide. In normal view it stays
         click-through via pointer-events:none. */
      if (source.closest) {
        const watermark = source.closest('[data-slide-watermark="true"], .slide-watermark');
        if (watermark && slide.contains(watermark)) {
          // The overlay is a full-slide inset:0 layer; selecting it stretched
          // the edit frame over the whole slide. Handles must hug the logo img.
          const logo = watermark.querySelector('img');
          return (logo && watermark.contains(logo)) ? logo : watermark;
        }
      }
      let node = source.nodeType === 1 ? source : source.parentElement;
      while (node && node !== slide) {
        const style = window.getComputedStyle(node);
        if (node.matches('[data-company-logo-placement], [data-team-logo-placement], img:not(.presentation-chrome-logo)')
          || style.position === 'absolute') {
          if (node.tagName === 'IMG' && node.parentElement && node.parentElement !== slide
            && node.parentElement.hasAttribute
            && (node.parentElement.hasAttribute('data-slide-imagebox')
              || node.parentElement.hasAttribute('data-canonical-map'))) {
            return node.parentElement;
          }
          return node;
        }
        /* Flow-layout shapes: the deepest block with its own visible surface
           wins, so an inner card is picked over a full-slide wrapper. Managed
           chrome (header/footer/counters) is never a shape. The walk stops
           before the slide root, which can never be selected. */
        if (!node.closest('[data-slide-header], [data-slide-footer], header, footer')
          && node.matches('div, section, aside, figure, table, ul')
          && slideNodeIsVisualShape(node, style)) {
          return node;
        }
        node = node.parentElement;
      }
      return null;
    }

    function findSlideRawTarget(rawRoot, target, path) {
      if (!rawRoot) return null;
      const placement = target ? (target.getAttribute('data-company-logo-placement')
        || target.getAttribute('data-team-logo-placement')) : null;
      if (placement) {
        const attr = target.hasAttribute('data-company-logo-placement')
          ? 'data-company-logo-placement' : 'data-team-logo-placement';
        const safePlacement = String(placement).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
        const byPlacement = rawRoot.querySelector('[' + attr + '="' + safePlacement + '"]');
        if (byPlacement) return byPlacement;
      }
      return elementAtSlidePath(rawRoot, path);
    }

    function commitSlideElementMove(stage, index, target, path, dx, dy) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html || (!dx && !dy)) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const rawTarget = findSlideRawTarget(rawRoot, target, path);
      if (!rawTarget) return;

      pushSlideEditHistory(index);
      const nextX = (Number(target.dataset.manualTranslateX) || 0) + dx;
      const nextY = (Number(target.dataset.manualTranslateY) || 0) + dy;
      const transform = 'translate(' + Math.round(nextX) + 'px, ' + Math.round(nextY) + 'px)';
      target.dataset.manualTranslateX = String(Math.round(nextX));
      target.dataset.manualTranslateY = String(Math.round(nextY));
      target.style.transform = transform;
      rawTarget.dataset.manualTranslateX = String(Math.round(nextX));
      rawTarget.dataset.manualTranslateY = String(Math.round(nextY));
      rawTarget.style.transform = transform;
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      toast('تم تحريك العنصر وحفظ موضعه في الشريحة');
    }

    function commitSlideElementDelete(stage, index, target, path) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      const rawTarget = findSlideRawTarget(rawRoot, target, path);
      if (!rawTarget || !rawTarget.parentElement) return;
      // Deleting the logo must remove the whole watermark overlay,
      // not leave an empty full-slide layer behind.
      const deleteTarget = watermarkOverlayOf(rawTarget) || rawTarget;
      if (!deleteTarget.parentElement) return;
      const coverBackground = deleteTarget.getAttribute
        ? deleteTarget.getAttribute('data-cover-background') : '';
      const dividerBackground = deleteTarget.getAttribute
        ? deleteTarget.getAttribute('data-section-divider-background') : '';
      if (coverBackground === '1' || dividerBackground === '1') {
        // Removing a photo layer is a deliberate edit: the save/renumber path
        // must not plant it back on the next open.
        if (coverBackground === '1') slideData.coverBackgroundRemoved = true;
        if (dividerBackground === '1') slideData.sectionDividerBackgroundRemoved = true;
      }
      pushSlideEditHistory(index);
      deleteTarget.parentElement.removeChild(deleteTarget);
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      const session = slideEditSessions[index];
      if (session) session.sel = null;
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      toast('تم حذف العنصر من الشريحة');
    }

    function enableSlideElementDragging(stage, index) {
      const slide = stage.querySelector('.slide');
      if (!slide) return;
      const enabled = hasPermission('create_presentation') && !!slideElementEditStates[index];
      slide.classList.toggle('slide-element-editing', enabled);
      if (!enabled) return;
      let activeDeleteBtn = null;
      function removeDeleteBtn() {
        if (activeDeleteBtn) { activeDeleteBtn.remove(); activeDeleteBtn = null; }
      }
      stage.addEventListener('mouseover', function handleSlideHover(event) {
        if (!enabled) return;
        if (slideElementDragActive) return;
        removeDeleteBtn();
        const target = slideDragTarget(slide, event.target);
        if (!target) return;
        const path = slideElementPath(slide, target);
        if (!path) return;
        target.classList.add('slide-element-editable');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'slide-element-delete-btn';
        btn.textContent = 'حذف';
        btn.addEventListener('pointerdown', function(e) { e.stopPropagation(); e.preventDefault(); });
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          e.preventDefault();
          removeDeleteBtn();
          commitSlideElementDelete(stage, index, target, path);
        });
        // A selected watermark target is the logo img itself (a void element),
        // so the hover button docks on its overlay instead of throwing.
        const btnHost = (target.tagName === 'IMG' && target.parentElement) ? target.parentElement : target;
        btnHost.appendChild(btn);
        activeDeleteBtn = btn;
      });
      stage.addEventListener('mouseout', function handleSlideHoverOut(event) {
        if (!enabled) return;
        const related = event.relatedTarget;
        if (activeDeleteBtn && (!related || (!activeDeleteBtn.contains(related) && !activeDeleteBtn.parentElement?.contains(related)))) {
          const target = slideDragTarget(slide, event.target);
          if (target) target.classList.remove('slide-element-editable');
          removeDeleteBtn();
        }
      });
      stage.addEventListener('pointerdown', function handleSlidePointerDown(event) {
        if (event.button !== 0) return;
        if (slideElementDragActive) return;
        const target = slideDragTarget(slide, event.target);
        if (!target) {
          if (typeof startSlideMarqueeSelection === 'function' && getSlideEditSession(index)) {
            const bounds = slide.getBoundingClientRect();
            if (event.clientX >= bounds.left && event.clientX <= bounds.right
              && event.clientY >= bounds.top && event.clientY <= bounds.bottom) {
              event.preventDefault();
              event.stopPropagation();
              startSlideMarqueeSelection(stage, index, event);
            }
          }
          return;
        }
        const path = slideElementPath(slide, target);
        if (!path) return;
        // Crop mode turns the drag into moving the picture inside its frame,
        // never into moving or resizing the frame itself.
        const cropSession = canvasSession(index);
        if (cropSession && cropSession.cropMode && typeof startSlideImageCropDrag === 'function'
          && (target.tagName === 'IMG' || (target.querySelector && target.querySelector('img')))) {
          event.preventDefault();
          event.stopPropagation();
          startSlideImageCropDrag(stage, index, target, event);
          return;
        }
        // Ctrl/Cmd/Shift click builds a multi-element selection instead of
        // starting a drag — the PowerPoint selection gesture.
        if ((event.ctrlKey || event.metaKey || event.shiftKey) && typeof addSlideElementToSelection === 'function') {
          event.preventDefault();
          event.stopPropagation();
          addSlideElementToSelection(stage, index, target, path);
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        slideElementDragActive = true;
        const scale = slideRenderedScale(stage);
        const startX = event.clientX;
        const startY = event.clientY;
        const dragPairs = (typeof slideDragEntriesForTarget === 'function')
          ? slideDragEntriesForTarget(stage, index, target, path)
          : [{ entry: { path, placement: '' }, target }];
        const dragStarts = dragPairs.map(pair => ({
          target: pair.target,
          x: Number(pair.target.dataset.manualTranslateX) || 0,
          y: Number(pair.target.dataset.manualTranslateY) || 0
        }));
        let moved = false;
        target.classList.add('slide-element-editable');
        target.setPointerCapture?.(event.pointerId);

        const handlePointerMove = moveEvent => {
          let dx = (moveEvent.clientX - startX) / scale;
          let dy = (moveEvent.clientY - startY) / scale;
          if (typeof snapSlideMoveDelta === 'function') {
            const snapped = snapSlideMoveDelta(stage, target, dx, dy);
            if (snapped) { dx = snapped.dx; dy = snapped.dy; }
          }
          if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
          dragStarts.forEach(start => {
            start.target.style.transform = 'translate(' + Math.round(start.x + dx) + 'px, '
              + Math.round(start.y + dy) + 'px)';
          });
        };
        const finish = endEvent => {
          const dx = (endEvent.clientX - startX) / scale;
          const dy = (endEvent.clientY - startY) / scale;
          target.releasePointerCapture?.(event.pointerId);
          target.removeEventListener('pointermove', handlePointerMove);
          target.removeEventListener('pointerup', finish);
          target.removeEventListener('pointercancel', finish);
          target.classList.remove('slide-element-editable');
          slideElementDragActive = false;
          if (typeof clearSlideSnapGuides === 'function') clearSlideSnapGuides(slide);
          if (moved) {
            if (typeof commitSlideDragEntries === 'function') {
              commitSlideDragEntries(stage, index, dragPairs, dx, dy);
            } else {
              commitSlideElementMove(stage, index, target, path, dx, dy);
            }
          }
          if (dragPairs.length > 1 && typeof restoreSlideGroupSelection === 'function') {
            restoreSlideGroupSelection(stage, index);
          } else {
            selectSlideElement(stage, index, target, path);
          }
        };
        target.addEventListener('pointermove', handlePointerMove);
        target.addEventListener('pointerup', finish);
        target.addEventListener('pointercancel', finish);
      });
      stage.addEventListener('click', function handleSlideEditClick(event) {
        if (!getSlideEditSession(index)) return;
        if (event.target.closest('.slide-element-selected, .slide-resize-handle, .slide-move-handle, .slide-element-delete-btn')) return;
        if (event.target.closest && event.target.closest('[contenteditable]')) return;
        const session = slideEditSessions[index];
        if (session && session.marqueeAt) {
          delete session.marqueeAt;
          return;
        }
        if (session && session.sel) {
          const slideEl = stage.querySelector('.slide');
          const selected = slideEl ? elementAtSlidePath(slideEl, session.sel.path) : null;
          if (selected && (selected === event.target || selected.contains(event.target))) return;
        }
        if (slideDragTarget(slide, event.target)) return;
        clearSlideElementSelection(stage);
        if (session) session.sel = null;
        syncSlideElementToolbar(index);
      });
      stage.addEventListener('keydown', function handleSlideEditKey(event) {
        if (event.key !== 'Delete' && event.key !== 'Backspace') return;
        const ae = document.activeElement;
        if (ae && (ae.isContentEditable || /^(INPUT|TEXTAREA|BUTTON|SELECT)$/.test(ae.tagName))) return;
        if (!getSlideEditSession(index)) return;
        event.preventDefault();
        event.stopPropagation();
        deleteSelectedSlideElement(index);
      });
    }