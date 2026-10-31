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
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
    }

    /* ── Snapping ───────────────────────────────────────────────────────── */

    function clearSlideSnapGuides(slide) {
      if (!slide) return;
      slide.querySelectorAll('.slide-snap-guide').forEach(node => node.remove());
    }

    function slideSnapContext(stage, target) {
      const slide = stage ? stage.querySelector('.slide') : null;
      if (!slide) return null;
      const scale = Number(stage.style.getPropertyValue('--slide-scale')) || 1;
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
