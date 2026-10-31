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
        const kind = inp.getAttribute('data-slide-edit-color');
        if (hasSel) inp.value = kind === 'color' ? textColor : (kind === 'highlight' ? '#fff59d' : bgColor);
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
      // The toolbar shows the tools of the selected kind. The tab switches
      // only when the selection kind changes, so a tab the user opened stays
      // open while they tweak the same element.
      if (typeof inspectorTargetKind === 'function') {
        const stage = card.querySelector('.tenant-slide-stage');
        const slide = stage ? stage.querySelector('.slide') : null;
        const target = hasSel && slide ? elementAtSlidePath(slide, session.sel.path) : null;
        const kind = target ? inspectorTargetKind(target) : '';
        const lastKind = card.dataset.editKind || '';
        card.dataset.editKind = kind;
        if (kind !== lastKind) {
          slideEditToolbarTab = kind || 'add';
          refreshSlideEditToolbar(index);
          if (typeof renderSlideInspector === 'function') renderSlideInspector(index);
          return;
        }
      }
      if (typeof renderSlideInspector === 'function') renderSlideInspector(index);
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
      stage.querySelectorAll('.slide-element-selected, .slide-element-multiselected')
        .forEach(el => el.classList.remove('slide-element-selected', 'slide-element-multiselected'));
      stage.querySelectorAll('.slide-resize-handle, .slide-move-handle, .slide-element-delete-btn, .slide-rotation-handle')
        .forEach(el => el.remove());
      const slide = stage.querySelector('.slide');
      if (slide) slide.querySelectorAll('.slide-snap-guide').forEach(el => el.remove());
    }

    /* Selection opens the inspector above the stage; keep the canvas still so
       the next click still lands on the element the user aimed at. */
    function holdSlideStagePosition(stage, anchorTop) {
      const wrap = document.getElementById('tenantSlidesMain');
      if (!wrap || !stage || stage.isConnected === false) return;
      const settle = () => {
        if (!stage.isConnected) return;
        const shift = stage.getBoundingClientRect().top - anchorTop;
        if (Math.abs(shift) <= 0.5) return;
        const behavior = wrap.style.scrollBehavior;
        wrap.style.scrollBehavior = 'auto';
        wrap.scrollTop += shift;
        wrap.style.scrollBehavior = behavior;
      };
      settle();
      requestAnimationFrame(settle);
      setTimeout(settle, 80);
    }

    function selectSlideElement(stage, index, target, path) {
      const session = getSlideEditSession(index);
      if (!session || !stage || !target) return;
      if (!path || !path.length) return;
      const slide = stage.querySelector('.slide');
      if (slide && target === slide) return;
      const anchorTop = stage.getBoundingClientRect().top;
      clearSlideElementSelection(stage);
      session.sel = {
        path: (path || []).slice(),
        placement: target.getAttribute
          ? (target.getAttribute('data-company-logo-placement')
            || target.getAttribute('data-team-logo-placement') || '') : ''
      };
      session.multi = [session.sel];
      target.classList.add('slide-element-selected');
      positionSlideEditHandles(stage, target);
      syncSlideElementToolbar(index);
      holdSlideStagePosition(stage, anchorTop);
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
      const scale = slideRenderedScale(stage);
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
        handle.style.left = Math.max(0, Math.min(pos[0], 1280 - HS)) + 'px';
        handle.style.top = Math.max(0, Math.min(pos[1], 720 - HS)) + 'px';
        slide.appendChild(handle);
        handle.addEventListener('pointerdown', event => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.stopPropagation();
          startSlideElementResize(stage, index, slide, target, def.dir, scale, event);
        });
      });
      if (typeof attachSlideRotationHandle === 'function') {
        attachSlideRotationHandle(stage, index, slide, target, x, y, w);
      }
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
      const slideW = slide.offsetWidth || 1280;
      const slideH = slide.offsetHeight || 720;
      const maxW = !touchW ? slideW : Math.max(24, Math.min(slideW,
        dir.indexOf('e') !== -1 ? slideW - base.left : base.left + base.width));
      const maxH = !touchH ? slideH : Math.max(24, Math.min(slideH,
        dir.indexOf('s') !== -1 ? slideH - base.top : base.top + base.height));
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
        newW = Math.max(24, Math.min(maxW, Math.round(newW)));
        newH = Math.max(24, Math.min(maxH, Math.round(newH)));
        const aspectLock = isImage && slideEditSessions[index] && slideEditSessions[index].aspectLock;
        if (aspectLock && base.width > 0 && base.height > 0) {
          if (touchW && !touchH) newH = Math.round(newW * (base.height / base.width));
          else if (touchH && !touchW) newW = Math.round(newH * (base.width / base.height));
          else newH = Math.round(newW * (base.height / base.width));
          newW = Math.max(24, Math.min(maxW, newW));
          newH = Math.max(24, Math.min(maxH, newH));
          target.style.width = newW + 'px';
          target.style.height = newH + 'px';
        } else {
          if (touchW) target.style.width = newW + 'px';
          if (touchH) {
            if (isImage) target.style.height = newH + 'px';
            else {
              target.style.minHeight = newH + 'px';
              if (explicitHeight) target.style.height = newH + 'px';
            }
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
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      toast('تم تغيير حجم العنصر');
    }

    function applySlideElementColorValue(root, kind, value) {
      if (!root) return;
      if (kind === 'border') {
        root.style.borderColor = value;
        if (!parseFloat(root.style.borderWidth)) root.style.borderWidth = '1px';
        root.style.borderStyle = 'solid';
        return;
      }
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
      // A live text selection previews nothing for a whole element: the commit
      // colours only the selected words.
      if ((kind === 'color' || kind === 'highlight')
        && typeof slideTextSelectionInside === 'function' && slideTextSelectionInside(index, target)) return;
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
      if ((kind === 'color' || kind === 'highlight')
        && typeof applySlideInlineColorToSelection === 'function'
        && applySlideInlineColorToSelection(index, kind, value)) {
        syncSlideElementToolbar(index);
        return;
      }
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
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      syncSlideElementToolbar(index);
      toast('تم تغيير لون العنصر');
    }

    /* A designer can put the opacity on a wrapper (a logo layer, a card), so
       the selected element's own computed opacity reads 100 while the visible
       result is 50. The control shows the effective value (element × every
       ancestor) and compensates when it writes, so typing 80 really shows 80. */
    function slideElementOpacityProduct(el, includeSelf) {
      let node = el;
      let product = 1;
      if (!includeSelf && node) node = node.parentElement;
      while (node && node.nodeType === 1) {
        if (node.classList && node.classList.contains('slide')) break;
        const value = parseFloat(window.getComputedStyle(node).opacity);
        if (isFinite(value)) product *= value;
        node = node.parentElement;
      }
      return Math.max(0, Math.min(1, product));
    }

    function slideElementOpacityPct(el) {
      if (!el) return 100;
      return Math.max(0, Math.min(100, Math.round(slideElementOpacityProduct(el, true) * 100)));
    }

    /* A child can never be more visible than a faded ancestor. When the
       requested value is brighter than the wrapper that holds it, the wrapper's
       inline opacity is lifted first — otherwise the field snapped back to the
       ancestor's value and the element could never be brightened again. */
    function liftSlideOpacityAncestors(target, desired) {
      let product = slideElementOpacityProduct(target, false);
      let node = target.parentElement;
      while (product + 0.001 < desired && node && node.nodeType === 1) {
        if (node.classList && node.classList.contains('slide')) break;
        const value = parseFloat(window.getComputedStyle(node).opacity);
        if (isFinite(value) && value < 1) {
          const above = slideElementOpacityProduct(node, false) || 1;
          const needed = Math.min(1, desired / (above || 1));
          if (needed > value) {
            node.style.opacity = String(Math.round(needed * 1000) / 1000);
            product = slideElementOpacityProduct(target, false);
          }
        }
        node = node.parentElement;
      }
      return product;
    }

    function applySlideElementEffectiveOpacity(target, pct) {
      const desired = Math.max(1, Math.min(100, Math.round(Number(pct) || 100))) / 100;
      const parent = liftSlideOpacityAncestors(target, desired);
      const own = parent > 0 ? Math.min(1, desired / parent) : 1;
      target.style.opacity = String(Math.round(own * 1000) / 1000);
      return Math.max(0, Math.min(100, Math.round(Math.min(desired, parent || desired) * 100)));
    }

    /* A lifted wrapper lives on the live node; mirror the whole ancestor chain
       into the stored copy so the change survives the next render and save. */
    function mirrorSlideAncestorOpacity(slide, rawRoot, liveLayer) {
      let node = liveLayer && liveLayer.parentElement;
      while (node && node !== slide && node.nodeType === 1) {
        const path = slideElementPath(slide, node);
        const rawNode = path && path.length ? elementAtSlidePath(rawRoot, path) : null;
        if (rawNode && rawNode.style) rawNode.style.opacity = node.style.opacity;
        node = node.parentElement;
      }
    }

    function previewSlideElementOpacity(index, pct) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) return;
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      const actual = applySlideElementEffectiveOpacity(watermarkOverlayOf(target) || target, pct);
      const card = document.getElementById('slide-card-' + index);
      const readout = card ? card.querySelector('[data-slide-edit-opacity-readout]') : null;
      if (readout) readout.textContent = actual + '%';
    }

    function commitSlideElementOpacity(index, pct) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('حدد عنصرا أولا'); return; }
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
      const liveLayer = watermarkOverlayOf(target) || target;
      const rawLayer = watermarkOverlayOf(rawTarget) || rawTarget;
      const actual = applySlideElementEffectiveOpacity(liveLayer, pct);
      rawLayer.style.opacity = liveLayer.style.opacity;
      mirrorSlideAncestorOpacity(slide, rawRoot, liveLayer);
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      syncSlideElementToolbar(index);
      toast(WFT('slide.opacity_set', 'تم ضبط شفافية العنصر {n}%', { n: actual }));
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
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      const selPath = session.sel.path;
      selectSlideElement(stage, index, target, selPath);
      toast(WFT('slide.font_size_set', 'حجم النص {n}px', { n: next }));
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
      markSlideHtmlEdited(slideData);
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
       overlay) forward or backward. DOM order decides paint order between
       same-level siblings — a z-index bump alone can never cross a parent
       stacking context, and a z-index clamped at zero can never go behind
       auto-stacked siblings — so the element is physically reordered first
       and z-index only pressurizes the case with no sibling left to pass. */
    function isSlideEditorChrome(el) {
      return !!(el && el.classList && (
        el.classList.contains('slide-resize-handle')
        || el.classList.contains('slide-move-handle')
        || el.classList.contains('slide-element-delete-btn')));
    }

    function siblingContent(el, step) {
      let node = step > 0 ? el.nextElementSibling : el.previousElementSibling;
      while (node && isSlideEditorChrome(node)) {
        node = step > 0 ? node.nextElementSibling : node.previousElementSibling;
      }
      return node;
    }

    function restackElement(el, direction) {
      /* direction>0 paints above one more sibling (later in DOM), direction<0
         below one (earlier). Returns the sibling that was passed, or null. */
      const parent = el.parentElement;
      if (!parent) return null;
      if (direction > 0) {
        const over = siblingContent(el, 1);
        if (!over) return null;
        parent.insertBefore(el, over.nextElementSibling);
        return over;
      }
      const under = siblingContent(el, -1);
      if (!under) return null;
      parent.insertBefore(el, under);
      return under;
    }

    function outrankZ(el, sibling, direction) {
      /* DOM order alone cannot pass a sibling carrying an explicit z-index
         (z:50 beats last-in-DOM z:auto), so the moved element also takes one
         step beyond the sibling's stack level. */
      let base = NaN;
      const inline = parseInt(sibling.style && sibling.style.zIndex, 10);
      if (isFinite(inline)) base = inline;
      else {
        try {
          const computed = parseInt(window.getComputedStyle(sibling).zIndex, 10);
          if (isFinite(computed)) base = computed;
        } catch (err) {}
      }
      if (!isFinite(base)) base = 0;
      const next = Math.max(-50, Math.min(200, base + (direction > 0 ? 1 : -1)));
      if (!el.style.position || el.style.position === 'static') el.style.position = 'relative';
      el.style.zIndex = String(next);
    }

    function effectiveZ(el) {
      const inline = parseInt(el.style && el.style.zIndex, 10);
      if (isFinite(inline)) return inline;
      try {
        const computed = parseInt(window.getComputedStyle(el).zIndex, 10);
        if (isFinite(computed)) return computed;
      } catch (err) {}
      return 0;
    }

    function pressurizeZ(el, direction) {
      /* Fallback when no sibling is left to pass: jump one step beyond the
         sibling stack extreme — a fixed +10 could never clear a z:50 sibling,
         and a negative z is the only way "back" drops below auto-stacked
         siblings. */
      const parent = el.parentElement;
      if (!parent) return false;
      let hasSibling = false;
      let extreme = direction > 0 ? -Infinity : Infinity;
      for (const sib of parent.children) {
        if (sib === el || isSlideEditorChrome(sib)) continue;
        hasSibling = true;
        const z = effectiveZ(sib);
        extreme = direction > 0 ? Math.max(extreme, z) : Math.min(extreme, z);
      }
      if (!hasSibling) return false;
      if (!isFinite(extreme)) extreme = 0;
      const current = effectiveZ(el);
      let next = Math.max(-50, Math.min(200, extreme + (direction > 0 ? 1 : -1)));
      if (direction > 0 && next <= current) next = Math.min(200, current + 10);
      if (direction < 0 && next >= current) next = Math.max(-50, current - 10);
      if (next === current) return false;
      if (!el.style.position || el.style.position === 'static') el.style.position = 'relative';
      el.style.zIndex = String(next);
      return true;
    }

    function adjustSlideElementLayer(index, direction) {
      const session = getSlideEditSession(index);
      if (!session || !session.sel) { toast('حدد عنصرا أولا'); return; }
      const stage = slideStageForIndex(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      const target = slide ? elementAtSlidePath(slide, session.sel.path) : null;
      if (!target) return;
      // Layer order belongs to the watermark overlay itself: re-stacking the
      // logo img alone would do nothing visible inside its own layer. Chrome
      // works the same way: a text node selected inside the header/footer
      // restacks the whole bar.
      const layerTarget = watermarkOverlayOf(target) || slideChromeOf(slide, target) || target;
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const rawTarget = rawRoot && findSlideRawTarget(rawRoot, target, session.sel.path);
      if (!rawRoot || !rawTarget) { renderTenantSlides(); return; }
      pushSlideEditHistory(index);
      const rawLayerTarget = watermarkOverlayOf(rawTarget) || slideChromeOf(rawRoot, rawTarget) || rawTarget;
      const passed = restackElement(layerTarget, direction);
      const rawPassed = restackElement(rawLayerTarget, direction);
      let pressured = false;
      if (passed) outrankZ(layerTarget, passed, direction);
      else pressured = pressurizeZ(layerTarget, direction);
      if (rawPassed) outrankZ(rawLayerTarget, rawPassed, direction);
      else pressurizeZ(rawLayerTarget, direction);
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      // Reordering changed the DOM indexes the selection path was built on.
      const freshPath = slideElementPath(slide, target) || session.sel.path;
      selectSlideElement(stage, index, target, freshPath);
      if (!passed && !pressured) {
        toast(direction > 0 ? 'العنصر بالفعل في المقدمة' : 'العنصر بالفعل في الخلف');
        return;
      }
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
      box.setAttribute('style', 'position:absolute;top:' + top + 'px;right:' + right + 'px;width:560px;min-height:56px;'
        + 'padding:8px 12px;box-sizing:border-box;background:transparent;'
        + 'color:#1e293b;font-size:20px;font-weight:600;line-height:1.6;text-align:right;z-index:5;');
      box.textContent = 'نص جديد';
      rawRoot.appendChild(box);
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
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