/* Snapping guides, multi-element drag/commit and selection helpers used by the
   canvas drag handlers. */

    function slidePathKey(entry) {
      return Array.isArray(entry && entry.path) ? entry.path.join('.') : '';
    }

    function sameSlideEntry(a, b) {
      return slidePathKey(a) === slidePathKey(b);
    }

    function slideEntryForTarget(stage, target) {
      const slide = stage ? stage.querySelector('.slide') : null;
      const path = slide && target ? slideElementPath(slide, target) : null;
      if (!path) return null;
      return {
        path,
        placement: target.getAttribute
          ? (target.getAttribute('data-company-logo-placement')
            || target.getAttribute('data-team-logo-placement') || '')
          : ''
      };
    }

    function slideDragEntriesForTarget(stage, index, target, path) {
      const session = canvasSession(index);
      const slide = stage.querySelector('.slide');
      const entry = { path, placement: slideEntryForTarget(stage, target)?.placement || '' };
      if (!session) return [{ entry, target }];
      const current = slideSelectedEntries(session);
      const inSelection = current.some(item => sameSlideEntry(item, entry));
      if (!inSelection) {
        session.multi = [entry];
        session.sel = entry;
        clearSlideElementSelection(stage);
        target.classList.add('slide-element-selected');
        return [{ entry, target }];
      }
      return slideSelectedTargets(stage, session);
    }

    function restoreSlideGroupSelection(stage, index) {
      const session = canvasSession(index);
      if (!session) return;
      clearSlideElementSelection(stage);
      const pairs = slideSelectedTargets(stage, session);
      pairs.forEach(({ target }, i) => {
        target.classList.add(i === 0 ? 'slide-element-selected' : 'slide-element-multiselected');
      });
      if (pairs[0]) positionSlideEditHandles(stage, pairs[0].target);
      syncSlideElementToolbar(index);
      renderSlideInspector(index);
    }

    function addSlideElementToSelection(stage, index, target, path) {
      const session = canvasSession(index);
      const slide = stage ? stage.querySelector('.slide') : null;
      if (!session || !slide) return;
      const entry = { path, placement: slideEntryForTarget(stage, target)?.placement || '' };
      let entries = slideSelectedEntries(session).slice();
      const key = slidePathKey(entry);
      const existingIndex = entries.findIndex(item => slidePathKey(item) === key);
      if (existingIndex === -1) entries.push(entry);
      else entries.splice(existingIndex, 1);
      if (!entries.length) {
        entries = [entry];
      }
      session.multi = entries;
      session.sel = entries[0];
      clearSlideElementSelection(stage);
      const pairs = slideSelectedTargets(stage, session);
      pairs.forEach(({ target: item }, i) => {
        item.classList.add(i === 0 ? 'slide-element-selected' : 'slide-element-multiselected');
      });
      if (pairs[0]) positionSlideEditHandles(stage, pairs[0].target);
      syncSlideElementToolbar(index);
      renderSlideInspector(index);
    }

    function commitSlideDragEntries(stage, index, pairs, dx, dy) {
      if ((!dx && !dy) || !pairs.length) return;
      const session = canvasSession(index);
      const slideData = tenantSlidesData[index];
      if (!session || !slideData || !slideData.html) return;
      const slide = stage.querySelector('.slide');
      if (!slide) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      pushSlideEditHistory(index);
      pairs.forEach(({ entry, target }) => {
        const raw = findSlideRawTarget(rawRoot, target, entry.path);
        if (!raw) return;
        const nextX = (Number(target.dataset.manualTranslateX) || 0) + dx;
        const nextY = (Number(target.dataset.manualTranslateY) || 0) + dy;
        const transform = 'translate(' + Math.round(nextX) + 'px, ' + Math.round(nextY) + 'px)';
        target.dataset.manualTranslateX = String(Math.round(nextX));
        target.dataset.manualTranslateY = String(Math.round(nextY));
        target.style.transform = transform;
        raw.dataset.manualTranslateX = String(Math.round(nextX));
        raw.dataset.manualTranslateY = String(Math.round(nextY));
        raw.style.transform = transform;
      });
      slideData.html = rawRoot.outerHTML;
      markSlideHtmlEdited(slideData);
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
    }

    /* Drag on the empty canvas to select everything the rectangle touches —
       the same gesture PowerPoint and Canva use for a group of elements. */
    function startSlideMarqueeSelection(stage, index, event) {
      const slide = stage ? stage.querySelector('.slide') : null;
      const session = canvasSession(index);
      if (!slide || !session) return;
      const scale = slideRenderedScale(stage);
      const slideRect = slide.getBoundingClientRect();
      const startX = (event.clientX - slideRect.left) / scale;
      const startY = (event.clientY - slideRect.top) / scale;
      const additive = !!(event.shiftKey || event.ctrlKey || event.metaKey);
      const baseEntries = additive ? slideSelectedEntries(session).slice() : [];
      const box = document.createElement('div');
      box.className = 'slide-marquee';
      slide.appendChild(box);
      slideElementDragActive = true;
      let moved = false;
      const onMove = moveEvent => {
        const x = (moveEvent.clientX - slideRect.left) / scale;
        const y = (moveEvent.clientY - slideRect.top) / scale;
        const left = Math.min(startX, x);
        const top = Math.min(startY, y);
        const width = Math.abs(x - startX);
        const height = Math.abs(y - startY);
        if (width + height > 3) moved = true;
        box.style.left = Math.round(left) + 'px';
        box.style.top = Math.round(top) + 'px';
        box.style.width = Math.round(width) + 'px';
        box.style.height = Math.round(height) + 'px';
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove, true);
        window.removeEventListener('pointerup', onUp, true);
        window.removeEventListener('pointercancel', onUp, true);
        slideElementDragActive = false;
        const area = {
          left: parseFloat(box.style.left) || 0,
          top: parseFloat(box.style.top) || 0,
          width: parseFloat(box.style.width) || 0,
          height: parseFloat(box.style.height) || 0
        };
        box.remove();
        if (!moved) return;
        const entries = baseEntries.slice();
        Array.from(slide.children).forEach(child => {
          if (slidePathIgnores(child)) return;
          if (slideChromeOf(slide, child) === child) return;
          const childStyle = window.getComputedStyle(child);
          if (childStyle.display === 'none' || childStyle.visibility === 'hidden') return;
          const rect = child.getBoundingClientRect();
          if (rect.width < 2 || rect.height < 2) return;
          const item = {
            left: (rect.left - slideRect.left) / scale,
            top: (rect.top - slideRect.top) / scale,
            width: rect.width / scale,
            height: rect.height / scale
          };
          const intersects = item.left < area.left + area.width
            && item.left + item.width > area.left
            && item.top < area.top + area.height
            && item.top + item.height > area.top;
          if (!intersects) return;
          const entry = slideEntryForTarget(stage, child);
          if (!entry) return;
          if (!entries.some(existing => sameSlideEntry(existing, entry))) entries.push(entry);
        });
        if (!entries.length) {
          if (!additive) {
            session.sel = null;
            session.multi = [];
            clearSlideElementSelection(stage);
            syncSlideElementToolbar(index);
            renderSlideInspector(index);
          }
          return;
        }
        // The pointerup is followed by a click on the empty canvas; the click
        // handler clears the selection, so mark this gesture as consumed.
        session.marqueeAt = Date.now();
        session.multi = entries;
        session.sel = entries[0];
        clearSlideElementSelection(stage);
        const pairs = slideSelectedTargets(stage, session);
        pairs.forEach(({ target }, entryIndex) => {
          target.classList.add(entryIndex === 0 ? 'slide-element-selected' : 'slide-element-multiselected');
        });
        if (pairs[0]) positionSlideEditHandles(stage, pairs[0].target);
        syncSlideElementToolbar(index);
        renderSlideInspector(index);
      };
      window.addEventListener('pointermove', onMove, true);
      window.addEventListener('pointerup', onUp, true);
      window.addEventListener('pointercancel', onUp, true);
    }

    /* ── Snapping ───────────────────────────────────────────────────────── */

    function clearSlideSnapGuides(slide) {
      if (!slide) return;
      slide.querySelectorAll('.slide-snap-guide').forEach(node => node.remove());
    }

    function slideSnapContext(stage, target) {
      const slide = stage ? stage.querySelector('.slide') : null;
      if (!slide) return null;
      const scale = slideRenderedScale(stage);
      const slideRect = slide.getBoundingClientRect();
      const toSlide = rect => ({
        left: (rect.left - slideRect.left) / scale,
        top: (rect.top - slideRect.top) / scale,
        width: rect.width / scale,
        height: rect.height / scale
      });
      const targetRect = toSlide(target.getBoundingClientRect());
      const xLines = [0, 640, 1280];
      const yLines = [0, 360, 720];
      Array.from(slide.children).forEach(child => {
        if (child === target || slidePathIgnores(child)) return;
        if (target.contains(child) || child.contains(target)) return;
        const style = window.getComputedStyle(child);
        if (style.display === 'none' || style.visibility === 'hidden') return;
        const rect = toSlide(child.getBoundingClientRect());
        if (rect.width < 2 || rect.height < 2) return;
        [rect.left, rect.left + rect.width / 2, rect.left + rect.width].forEach(line => xLines.push(Math.round(line)));
        [rect.top, rect.top + rect.height / 2, rect.top + rect.height].forEach(line => yLines.push(Math.round(line)));
      });
      return { slide, targetRect, xLines, yLines };
    }

    function drawSlideSnapGuide(slide, axis, position) {
      if (!slide) return;
      const guide = document.createElement('div');
      guide.className = 'slide-snap-guide is-' + (axis === 'x' ? 'vertical' : 'horizontal');
      guide.setAttribute('data-slide-live-only', '1');
      if (axis === 'x') guide.style.left = Math.round(position) + 'px';
      else guide.style.top = Math.round(position) + 'px';
      slide.appendChild(guide);
    }

    function snapSlideMoveDelta(stage, target, dx, dy) {
      const context = slideSnapContext(stage, target);
      if (!context) return { dx, dy };
      const slide = context.slide;
      clearSlideSnapGuides(slide);
      const threshold = 7;
      const { targetRect } = context;
      const candidateX = [targetRect.left + dx, targetRect.left + dx + targetRect.width / 2,
        targetRect.left + dx + targetRect.width];
      const candidateY = [targetRect.top + dy, targetRect.top + dy + targetRect.height / 2,
        targetRect.top + dy + targetRect.height];
      let bestX = null;
      let bestY = null;
      candidateX.forEach((edge, edgeIndex) => {
        context.xLines.forEach(line => {
          const distance = Math.abs(edge - line);
          if (distance <= threshold && (!bestX || distance < bestX.distance)) {
            bestX = { distance, line, edgeIndex };
          }
        });
      });
      candidateY.forEach((edge, edgeIndex) => {
        context.yLines.forEach(line => {
          const distance = Math.abs(edge - line);
          if (distance <= threshold && (!bestY || distance < bestY.distance)) {
            bestY = { distance, line, edgeIndex };
          }
        });
      });
      let nextDx = dx;
      let nextDy = dy;
      if (bestX) {
        nextDx = dx + (bestX.line - candidateX[bestX.edgeIndex]);
        drawSlideSnapGuide(slide, 'x', bestX.line);
      }
      if (bestY) {
        nextDy = dy + (bestY.line - candidateY[bestY.edgeIndex]);
        drawSlideSnapGuide(slide, 'y', bestY.line);
      }
      return { dx: nextDx, dy: nextDy };
    }

    function slideSelectionShadowToggle(index) {
      toggleSlideSelectionShadow(index);
    }
