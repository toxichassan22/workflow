/* Slide workspace — header, real thumbnails, selection, manual slide actions
   and present mode. Loaded after 15-slide-edit-chat so these definitions are
   the ones the deck page runs. */

    let tenantSlidesView = 'edit';
    let tenantSlidesSidebarCollapsed = false;
    let tenantSlideSelectionIds = [];
    let tenantSlideSelectionAnchorId = '';
    let tenantThumbRenamingId = '';
    let tenantThumbObserver = null;
    let tenantPresentationStatus = '';
    let tenantPresentActive = false;
    let tenantPresentIndex = 0;
    let tenantPresentHideTimer = null;

    function wsText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function slideRuntimeId(slide) {
      return String((slide && slide.id) || '');
    }

    function slideIndexById(id) {
      const wanted = String(id || '');
      if (!wanted) return -1;
      return tenantSlidesData.findIndex(slide => slideRuntimeId(slide) === wanted);
    }

    function markSlidesDeckChanged() {
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      if (typeof triggerAutoSaveDraft === 'function') triggerAutoSaveDraft();
      if (typeof renderSlidesHeader === 'function') renderSlidesHeader();
    }

    /* ── Header ─────────────────────────────────────────────────────────── */

    function presentationStatusLabel(status) {
      const value = String(status || '').toLowerCase();
      if (value === 'approved') return wsText('ws.status_approved', 'معتمد');
      if (value === 'pending_approval' || value === 'pending') return wsText('ws.status_pending', 'بانتظار التعميد');
      if (value === 'draft' || value === 'edited' || value === '') return wsText('ws.status_draft', 'مسودة');
      return wsText('ws.status_draft', 'مسودة');
    }

    function renderSlidesHeader() {
      const page = document.getElementById('tenantSlidesPage');
      if (!page) return;
      const titleInput = document.getElementById('slidesHeaderTitle');
      if (titleInput && document.activeElement !== titleInput) {
        titleInput.value = String(tenantPresentationTitle || '');
      }
      const total = Array.isArray(tenantSlidesData) ? tenantSlidesData.length : 0;
      const count = document.getElementById('slidesHeaderCount');
      if (count) count.textContent = String(total);
      const countLabel = document.getElementById('slidesHeaderCountLabel');
      if (countLabel) {
        countLabel.textContent = total === 1
          ? wsText('ws.slides_one', 'شريحة')
          : (total === 2 ? wsText('ws.slides_two', 'شريحتان') : wsText('ws.slides_many', 'شرائح'));
      }
      const hiddenInfo = document.getElementById('slidesEditorInfo');
      if (hiddenInfo) {
        hiddenInfo.textContent = (tenantPresentationTitle || '') + ' | ' + (tenantSlidesData.length || 0);
      }
      const dirty = (typeof tenantDraftDirty !== 'undefined') && tenantDraftDirty;
      const saveState = document.getElementById('slidesHeaderSaveState');
      if (saveState) {
        saveState.textContent = dirty
          ? wsText('ws.save_dirty', 'تعديلات غير محفوظة')
          : wsText('ws.saved_state', 'محفوظ');
        saveState.classList.toggle('is-dirty', !!dirty);
      }
      const badge = document.getElementById('slidesHeaderStatusBadge');
      if (badge) {
        const status = dirty ? 'draft' : tenantPresentationStatus;
        const label = presentationStatusLabel(status);
        badge.textContent = label;
        badge.hidden = !tenantPresentationId && !dirty;
        badge.classList.toggle('is-approved', String(status || '').toLowerCase() === 'approved');
      }
      document.querySelectorAll('[data-slides-view]').forEach(button => {
        button.classList.toggle('active', button.getAttribute('data-slides-view') === tenantSlidesView);
      });
    }

    function saveSlidesHeaderTitle() {
      const input = document.getElementById('slidesHeaderTitle');
      if (!input) return;
      const title = String(input.value || '').trim();
      if (!title) {
        input.value = String(tenantPresentationTitle || '');
        return;
      }
      if (title === tenantPresentationTitle) return;
      tenantPresentationTitle = title;
      if (tenantPresentationId && hasPermission('create_presentation')) {
        void saveTenantPresentation(title);
      } else {
        setDraftDirty(true);
      }
      renderSlidesHeader();
    }

    function setSlidesWorkspaceView(view) {
      if (view === 'present') {
        openTenantPresentation();
        return;
      }
      tenantSlidesView = view === 'sorter' ? 'sorter' : 'edit';
      const page = document.getElementById('tenantSlidesPage');
      if (!page) return;
      page.classList.toggle('slides-view-sorter', tenantSlidesView === 'sorter');
      page.classList.toggle('slides-view-edit', tenantSlidesView !== 'sorter');
      const sorter = document.getElementById('tenantSlidesSorter');
      if (sorter) sorter.hidden = tenantSlidesView !== 'sorter';
      renderSlidesHeader();
      if (tenantSlidesView === 'sorter') {
        renderTenantSlidesSorter();
      } else {
        renderTenantSlidesSidebar();
      }
    }

    function resetSlidesWorkspaceView() {
      tenantSlidesView = 'edit';
      const page = document.getElementById('tenantSlidesPage');
      if (page) {
        page.classList.add('slides-view-edit');
        page.classList.remove('slides-view-sorter');
      }
      const sorter = document.getElementById('tenantSlidesSorter');
      if (sorter) sorter.hidden = true;
    }

    /* ── Card width follows the slide stage ─────────────────────────────── */

    let tenantSlideStageWidthObserver = null;

    function ensureTenantStageWidthObserver() {
      if (tenantSlideStageWidthObserver || typeof ResizeObserver === 'undefined') return;
      tenantSlideStageWidthObserver = new ResizeObserver(entries => {
        entries.forEach(entry => {
          const stage = entry.target;
          if (!stage.isConnected) {
            tenantSlideStageWidthObserver.unobserve(stage);
            return;
          }
          const card = stage.closest('.ge-slide-card');
          if (!card) return;
          const width = Math.round(stage.getBoundingClientRect().width);
          if (width > 0) card.style.width = width + 'px';
        });
      });
    }

    function observeTenantSlideStage(stage, card) {
      if (!stage || !card) return;
      ensureTenantStageWidthObserver();
      if (tenantSlideStageWidthObserver) {
        tenantSlideStageWidthObserver.observe(stage);
      } else {
        card.style.width = Math.round(stage.offsetWidth || 0) + 'px';
      }
    }

    /* ── Sidebar ────────────────────────────────────────────────────────── */

    function slideThumbnailHtml(slide) {
      if (!slide || !slide.html) return '';
      try {
        return processSlideHtmlClient(slide.html, slide.type);
      } catch (error) {
        return '';
      }
    }

    function fillSlideThumbnailCanvas(canvas, slide) {
      if (!canvas) return;
      if (canvas.dataset.filled === '1') return;
      const html = slideThumbnailHtml(slide);
      canvas.innerHTML = html || '<div class="ge-thumb-placeholder">' + escapeHtml(slide && slide.title ? slide.title : '') + '</div>';
      canvas.dataset.filled = '1';
    }

    function ensureThumbObserver() {
      if (tenantThumbObserver || typeof IntersectionObserver === 'undefined') return;
      tenantThumbObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) return;
          const canvas = entry.target;
          const index = Number(canvas.dataset.thumbIndex);
          const slide = tenantSlidesData[index];
          if (slide) fillSlideThumbnailCanvas(canvas, slide);
          tenantThumbObserver.unobserve(canvas);
        });
      }, { root: null, rootMargin: '160px' });
    }

    // Icon buttons keep their Arabic label in title/aria-label, so the compact
    // row stays self-explanatory without printing a word per action.
    function thumbIconButton(icon, labelKey, labelFallback, action, disabled) {
      const label = wsText(labelKey, labelFallback);
      return '<button type="button" class="ge-thumb-icon" data-ws-icon="' + icon + '"'
        + ' title="' + escapeHtml(label) + '" aria-label="' + escapeHtml(label) + '"'
        + (disabled ? ' disabled' : '')
        + ' onclick="event.stopPropagation(); ' + action + '"></button>';
    }

    function slideThumbActionsHtml(index, slide) {
      const hasPermissionCreate = hasPermission('create_presentation');
      const selected = tenantSlideSelectionIds.includes(slideRuntimeId(slide));
      const up = index > 0
        ? thumbIconButton('arrow-up', 'ws.move_up', 'أعلى', 'moveTenantSlide(' + index + ', ' + (index - 1) + ')')
        : '';
      const down = index < tenantSlidesData.length - 1
        ? thumbIconButton('arrow-down', 'ws.move_down', 'أسفل', 'moveTenantSlide(' + index + ', ' + (index + 1) + ')')
        : '';
      const remove = hasPermissionCreate && tenantSlidesData.length > 1
        ? thumbIconButton('trash', 'ws.delete', 'حذف', 'deleteSlide(' + index + ')')
        : '';
      const more = hasPermissionCreate
        ? thumbIconButton('more', 'ws.more', 'المزيد', 'toggleTenantThumbMenu(' + index + ')')
        : '';
      const notes = hasPermissionCreate
        ? thumbIconButton('notes', 'ws.notes', 'ملاحظات', 'openTenantSlideNotesEditor(' + index + ')')
        : '';
      const regenerate = hasPermissionCreate
        ? '<button type="button" title="' + escapeHtml(wsText('ws.regenerate_title', 'إعادة توليد هذه الشريحة فقط')) + '"'
          + ((typeof isGeneratingTenantSlides !== 'undefined' && (isGeneratingTenantSlides || isRegeneratingTenantSlide)) ? ' disabled' : '')
          + ' onclick="event.stopPropagation(); regenerateTenantSlide(' + index + ')">' + escapeHtml(wsText('ws.regenerate', 'إعادة توليد')) + '</button>'
        : '';
      const background = hasPermissionCreate && typeof tenantSlideHasBackground === 'function' && tenantSlideHasBackground(slide)
        ? '<button type="button" onclick="event.stopPropagation(); removeTenantSlideBackground(' + index + ')">' + escapeHtml(wsText('gen.slide_no_background', 'بدون خلفية')) + '</button>'
        : '';
      const rename = hasPermissionCreate
        ? '<button type="button" onclick="event.stopPropagation(); startRenameTenantSlide(' + index + ')">' + escapeHtml(wsText('ws.rename', 'إعادة تسمية')) + '</button>'
        : '';
      const group = hasPermissionCreate
        ? '<button type="button" title="' + escapeHtml(wsText('ws.group_title', 'تجميع الشريحة في قسم')) + '"'
          + ' onclick="event.stopPropagation(); openTenantSlideGroupEditor(' + index + ')">' + escapeHtml(wsText('ws.group', 'قسم')) + '</button>'
        : '';
      const duplicate = hasPermissionCreate
        ? '<button type="button" onclick="event.stopPropagation(); duplicateSlideAt(' + index + ')">' + escapeHtml(wsText('ws.duplicate', 'تكرار')) + '</button>'
        : '';
      const hide = hasPermissionCreate
        ? '<button type="button" onclick="event.stopPropagation(); toggleSlideHidden(' + index + ')">'
          + escapeHtml(slide.hidden ? wsText('ws.show_slide', 'إظهار') : wsText('ws.hide_slide', 'إخفاء')) + '</button>'
        : '';
      const select = selected
        ? '<button type="button" onclick="event.stopPropagation(); removeSlideFromSelection(\'' + escapeHtml(slideRuntimeId(slide)) + '\')">' + escapeHtml(wsText('ws.deselect', 'إلغاء التحديد')) + '</button>'
        : '';
      return up + down + notes + remove + more
        + '<span class="ge-thumb-extra">' + regenerate + background + rename + group
        + duplicate + hide + select + '</span>';
    }

    // A rebuilt rail re-uses the thumbnails it already painted, so adding or
    // deleting a slide never flashes the rail: the canvas HTML is kept with
    // the slide HTML it was painted from and dropped when that changes.
    const tenantSidebarThumbCache = new Map();
    let tenantSidebarRendered = false;

    // Held inside the rail so the scoped thumb styles still apply; fixed
    // coordinates keep it where the thumb was on screen.
    function sidebarSpawnGhost(host, node, rect) {
      if (!host || !node || !rect) return null;
      const ghost = node.cloneNode(true);
      ghost.classList.add('ge-thumb-ghost');
      ghost.style.position = 'fixed';
      ghost.style.left = rect.left + 'px';
      ghost.style.top = rect.top + 'px';
      ghost.style.width = rect.width + 'px';
      ghost.style.height = rect.height + 'px';
      ghost.style.pointerEvents = 'none';
      ghost.style.zIndex = '9997';
      host.appendChild(ghost);
      try {
        ghost.animate(
          [{ opacity: 1, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(.94)' }],
          { duration: 180, easing: 'ease-out' }
        );
      } catch (error) { /* ignore */ }
      setTimeout(() => { if (ghost.parentNode) ghost.remove(); }, 200);
      return ghost;
    }

    function animateTenantSidebarRebuild(sidebar, previous, removed) {
      if (!tenantSidebarRendered) return;
      let reduceMotion = false;
      try {
        reduceMotion = typeof sorterPrefersReducedMotion === 'function' && sorterPrefersReducedMotion();
      } catch (error) { /* ignore */ }
      if (reduceMotion) return;
      const thumbs = Array.from(sidebar.querySelectorAll('.ge-thumb[data-slide-id]'));
      thumbs.forEach(thumb => {
        const id = String(thumb.dataset.slideId || '');
        const first = previous.get(id);
        if (!first) {
          try {
            thumb.animate(
              [{ opacity: 0, transform: 'scale(.94)' }, { opacity: 1, transform: 'scale(1)' }],
              { duration: 220, easing: 'cubic-bezier(.2, .8, .2, 1)' }
            );
          } catch (error) { /* ignore */ }
          return;
        }
        const now = thumb.getBoundingClientRect();
        const dx = Math.round((first.left - now.left) * 10) / 10;
        const dy = Math.round((first.top - now.top) * 10) / 10;
        if (!dx && !dy) return;
        try {
          thumb.animate(
            [{ transform: 'translate(' + dx + 'px, ' + dy + 'px)' }, { transform: 'translate(0, 0)' }],
            { duration: 200, easing: 'cubic-bezier(.2, .8, .2, 1)' }
          );
        } catch (error) { /* ignore */ }
      });
      removed.forEach(entry => sidebarSpawnGhost(sidebar, entry.node, entry.rect));
    }

    function renderTenantSlidesSidebar(force) {
      const sidebar = document.getElementById('tenantSlidesSidebar');
      if (!sidebar) return;
      if (typeof isGeneratingTenantSlides !== 'undefined' && isGeneratingTenantSlides && !force) return;
      if (tenantThumbObserver) {
        tenantThumbObserver.disconnect();
        tenantThumbObserver = null;
      }
      const desiredIds = new Set(tenantSlidesData.map(slide => slideRuntimeId(slide)).filter(Boolean));
      const previousRects = new Map();
      const removedThumbs = [];
      Array.from(sidebar.querySelectorAll('.ge-thumb[data-slide-id]')).forEach(thumb => {
        const id = String(thumb.dataset.slideId || '');
        if (!id) return;
        const rect = thumb.getBoundingClientRect();
        previousRects.set(id, { left: rect.left, top: rect.top, width: rect.width, height: rect.height });
        const canvas = thumb.querySelector('.ge-thumb-canvas');
        const slide = tenantSlidesData[slideIndexById(id)];
        if (canvas && canvas.dataset.filled === '1' && canvas.innerHTML) {
          tenantSidebarThumbCache.set(id, { source: slide ? String(slide.html || '') : '', html: canvas.innerHTML });
        }
        if (!desiredIds.has(id)) removedThumbs.push({ node: thumb, rect: rect });
      });
      sidebar.innerHTML = '';
      sidebar.classList.toggle('is-collapsed', !!tenantSlidesSidebarCollapsed);
      ensureThumbObserver();

      const head = document.createElement('div');
      head.className = 'ge-sidebar-head';
      const collapseLabel = tenantSlidesSidebarCollapsed
        ? wsText('ws.expand_sidebar', 'فتح القائمة')
        : wsText('ws.collapse_sidebar', 'طي القائمة');
      head.innerHTML = '<button type="button" class="ge-sidebar-head-btn is-icon" data-ws-icon="chevron"'
        + ' title="' + escapeHtml(collapseLabel) + '" aria-label="' + escapeHtml(collapseLabel) + '"'
        + ' onclick="toggleTenantSidebar()"></button>'
        + '<button type="button" class="ge-sidebar-head-btn" onclick="openSlideInsertMenu(this, ' + tenantSlidesData.length + ')">'
        + escapeHtml(wsText('ws.add_slide', 'إضافة شريحة'))
        + '</button>';
      sidebar.appendChild(head);

      if (tenantSlideSelectionIds.length > 1) {
        const bar = document.createElement('div');
        bar.className = 'ge-sidebar-selection';
        bar.innerHTML = '<span class="ge-sidebar-selection-count">'
          + escapeHtml(wsText('ws.selected_count', 'المحدد: {n}', { n: tenantSlideSelectionIds.length }))
          + '</span>'
          + '<button type="button" onclick="deleteSelectedSlides()">' + escapeHtml(wsText('ws.delete_selected', 'حذف المحدد')) + '</button>'
          + '<button type="button" onclick="duplicateSelectedSlides()">' + escapeHtml(wsText('ws.duplicate_selected', 'تكرار المحدد')) + '</button>'
          + '<button type="button" class="is-quiet" onclick="clearSlideSelection()">' + escapeHtml(wsText('ws.clear_selection', 'إلغاء التحديد')) + '</button>';
        sidebar.appendChild(bar);
      }

      let previousGroup = null;
      tenantSlidesData.forEach((slide, index) => {
        const groupName = String(slide.group || '').trim();
        if (groupName && groupName !== previousGroup) {
          const groupHead = document.createElement('div');
          groupHead.className = 'ge-thumb-group';
          groupHead.textContent = groupName;
          sidebar.appendChild(groupHead);
        }
        previousGroup = groupName;

        const id = slideRuntimeId(slide);
        const selected = tenantSlideSelectionIds.includes(id);

        const wrap = document.createElement('div');
        wrap.className = 'ge-thumb-wrap';

        const thumb = document.createElement('div');
        thumb.className = 'ge-thumb'
          + (index === activeSlideIndex ? ' active' : '')
          + (selected ? ' selected' : '')
          + (slide.hidden ? ' is-hidden' : '')
          + (tenantThumbRenamingId && tenantThumbRenamingId === id ? ' is-renaming' : '');
        thumb.dataset.slideId = id;
        thumb.onclick = event => handleThumbClick(event, index);

        const frame = document.createElement('div');
        frame.className = 'ge-thumb-frame';
        const canvas = document.createElement('div');
        canvas.className = 'ge-thumb-canvas';
        canvas.dataset.thumbIndex = String(index);
        const cachedThumb = tenantSidebarThumbCache.get(id);
        if (cachedThumb && cachedThumb.source === String(slide.html || '')) {
          canvas.innerHTML = cachedThumb.html;
          canvas.dataset.filled = '1';
        } else if (index === activeSlideIndex) {
          fillSlideThumbnailCanvas(canvas, slide);
        }
        frame.appendChild(canvas);
        thumb.appendChild(frame);

        const meta = document.createElement('div');
        meta.className = 'ge-thumb-meta';
        const notesChip = String(slide.notes || '').trim()
          ? '<button type="button" class="ge-thumb-notes" title="' + escapeHtml(String(slide.notes || '')) + '"'
            + ' onclick="event.stopPropagation(); openTenantSlideNotesEditor(' + index + ')">'
            + escapeHtml(wsText('ws.notes_chip', 'ملاحظات')) + '</button>'
          : '';
        const hiddenChip = slide.hidden
          ? '<span class="ge-thumb-hidden">' + escapeHtml(wsText('ws.hidden_chip', 'مخفية')) + '</span>'
          : '';
        if (tenantThumbRenamingId && tenantThumbRenamingId === id) {
          meta.innerHTML = '<span class="ge-thumb-num">' + (index + 1) + '</span>'
            + '<input type="text" class="ge-thumb-rename-input" value="' + escapeHtml(slide.title || '') + '">' + notesChip;
        } else {
          meta.innerHTML = '<span class="ge-thumb-num">' + (index + 1) + '</span>'
            + '<span class="ge-thumb-title" title="' + escapeHtml(slide.title || '') + '">'
            + escapeHtml(slide.title || wsText('ws.no_title', 'شريحة بدون عنوان')) + '</span>'
            + notesChip + hiddenChip;
        }
        thumb.appendChild(meta);

        const actions = document.createElement('div');
        actions.className = 'ge-thumb-actions';
        actions.innerHTML = slideThumbActionsHtml(index, slide);
        thumb.appendChild(actions);

        wrap.appendChild(thumb);
        sidebar.appendChild(wrap);

        const add = document.createElement('button');
        add.type = 'button';
        add.className = 'ge-thumb-add';
        add.textContent = wsText('ws.add_after', 'إضافة شريحة');
        add.onclick = event => {
          event.stopPropagation();
          openSlideInsertMenu(add, index + 1);
        };
        sidebar.appendChild(add);

        if (tenantThumbObserver && canvas.dataset.filled !== '1') tenantThumbObserver.observe(canvas);
      });

      animateTenantSidebarRebuild(sidebar, previousRects, removedThumbs);
      tenantSidebarRendered = true;
      tenantSidebarThumbCache.forEach((entry, id) => {
        if (!desiredIds.has(id)) tenantSidebarThumbCache.delete(id);
      });

      if (tenantThumbRenamingId) {
        const input = sidebar.querySelector('.ge-thumb-rename-input');
        const target = input ? input.closest('.ge-thumb') : null;
        const renameIndex = target ? slideIndexById(target.dataset.slideId) : -1;
        if (input && renameIndex !== -1) {
          input.focus();
          input.select();
          const commit = () => commitTenantSlideRename(renameIndex, input.value);
          input.onchange = commit;
          input.onblur = commit;
          input.onkeydown = event => {
            event.stopPropagation();
            if (event.key === 'Enter') { event.preventDefault(); commit(); }
            if (event.key === 'Escape') { event.preventDefault(); tenantThumbRenamingId = ''; renderTenantSlidesSidebar(); }
          };
        }
      }
      hydrateWorkspaceIcons(sidebar);
      if (typeof renderSlidesHeader === 'function') renderSlidesHeader();
      if (typeof reapplyDesignerSlideActivity === 'function') reapplyDesignerSlideActivity();
    }

    function toggleTenantSidebar() {
      tenantSlidesSidebarCollapsed = !tenantSlidesSidebarCollapsed;
      try { localStorage.setItem('wf.slidesSidebarCollapsed', tenantSlidesSidebarCollapsed ? '1' : '0'); } catch (error) {}
      renderTenantSlidesSidebar();
    }

    function toggleTenantThumbMenu(index) {
      const thumb = document.querySelector('#tenantSlidesSidebar .ge-thumb[data-slide-id="'
        + String(slideRuntimeId(tenantSlidesData[index])) + '"]');
      if (!thumb) return;
      const open = thumb.classList.contains('menu-open');
      document.querySelectorAll('#tenantSlidesSidebar .ge-thumb.menu-open').forEach(el => el.classList.remove('menu-open'));
      if (!open) thumb.classList.add('menu-open');
    }

    function refreshSlideThumbnail(index) {
      const slide = tenantSlidesData[index];
      if (!slide) return;
      const thumb = document.querySelector('#tenantSlidesSidebar .ge-thumb[data-slide-id="'
        + String(slideRuntimeId(slide)) + '"]');
      const canvas = thumb ? thumb.querySelector('.ge-thumb-canvas') : null;
      if (!canvas) return;
      canvas.dataset.filled = '';
      fillSlideThumbnailCanvas(canvas, slide);
    }

    /* ── Selection ──────────────────────────────────────────────────────── */

    function handleThumbClick(event, index) {
      const slide = tenantSlidesData[index];
      if (!slide) return;
      const id = slideRuntimeId(slide);
      if (event && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        toggleSlideSelection(id, false);
        return;
      }
      if (event && event.shiftKey && tenantSlideSelectionAnchorId) {
        event.preventDefault();
        const from = slideIndexById(tenantSlideSelectionAnchorId);
        if (from !== -1) {
          const [start, end] = from < index ? [from, index] : [index, from];
          tenantSlideSelectionIds = tenantSlidesData.slice(start, end + 1).map(slideRuntimeId).filter(Boolean);
          renderTenantSlidesSidebar();
          return;
        }
      }
      clearSlideSelection(true);
      if (index === activeSlideIndex) return;
      selectTenantSlide(index);
    }

    function toggleSlideSelection(id, rerender = true) {
      const wanted = String(id || '');
      if (!wanted) return;
      if (tenantSlideSelectionIds.includes(wanted)) {
        tenantSlideSelectionIds = tenantSlideSelectionIds.filter(item => item !== wanted);
      } else {
        tenantSlideSelectionIds = tenantSlideSelectionIds.concat(wanted);
        tenantSlideSelectionAnchorId = wanted;
      }
      if (rerender) renderTenantSlidesSidebar();
    }

    function removeSlideFromSelection(id) {
      tenantSlideSelectionIds = tenantSlideSelectionIds.filter(item => item !== String(id || ''));
      renderTenantSlidesSidebar();
    }

    function clearSlideSelection(silent) {
      tenantSlideSelectionIds = [];
      tenantSlideSelectionAnchorId = '';
      if (!silent) renderTenantSlidesSidebar();
    }

    function selectedSlideIndexes() {
      return tenantSlidesData
        .map((slide, index) => ({ id: slideRuntimeId(slide), index }))
        .filter(item => tenantSlideSelectionIds.includes(item.id))
        .map(item => item.index);
    }

    /* ── Manual slide actions ───────────────────────────────────────────── */

    function blankSlideTemplate(title) {
      return {
        id: wfNewSlideId(),
        title: title || wsText('ws.new_slide', 'شريحة جديدة'),
        type: 'content',
        section_key: '',
        is_custom: true,
        html: '<div class="slide" dir="rtl" style="width:1280px;height:720px;background:#ffffff;'
          + 'padding:64px;box-sizing:border-box;direction:rtl;font-family:\'The Sans Arabic\',Tahoma,Arial,sans-serif;">'
          + '<div style="position:absolute;left:0;right:0;bottom:36px;height:4px;background:#07182C;opacity:.8;"></div>'
          + '</div>'
      };
    }

    function insertBlankSlideAt(index) {
      if (!hasPermission('create_presentation')) return;
      if (typeof insertStructuredSlideAt === 'function') {
        insertStructuredSlideAt(index, 'blank');
        return;
      }
      const at = Math.max(0, Math.min(Number(index) || 0, tenantSlidesData.length));
      beginPresentationUndoChange();
      tenantSlidesData.splice(at, 0, blankSlideTemplate());
      renumberTenantSlides();
      renderTenantSlides();
      selectTenantSlide(at);
      markSlidesDeckChanged();
      if (typeof checkpointPresentationUndo === 'function') checkpointPresentationUndo();
      toast(WFT('ws.slide_added', 'أُضيفت شريحة جديدة'));
    }

    function duplicateSlideAt(index) {
      if (!hasPermission('create_presentation')) return;
      const source = tenantSlidesData[index];
      if (!source) return;
      beginPresentationUndoChange();
      const copy = JSON.parse(JSON.stringify(source));
      copy.id = wfNewSlideId();
      copy.title = wsText('ws.duplicate_title', 'نسخة من {title}', { title: source.title || wsText('ws.no_title', 'شريحة بدون عنوان') });
      copy.is_custom = true;
      copy.duplicated_from = source.id || '';
      tenantSlidesData.splice(index + 1, 0, copy);
      renumberTenantSlides();
      renderTenantSlides();
      selectTenantSlide(index + 1);
      markSlidesDeckChanged();
      if (typeof checkpointPresentationUndo === 'function') checkpointPresentationUndo();
      toast(WFT('ws.slide_duplicated', 'تم تكرار الشريحة'));
    }

    function duplicateSelectedSlides() {
      if (!hasPermission('create_presentation')) return;
      const indexes = selectedSlideIndexes();
      if (!indexes.length) return;
      beginPresentationUndoChange();
      const copies = indexes.map(index => {
        const source = tenantSlidesData[index];
        const copy = JSON.parse(JSON.stringify(source));
        copy.id = wfNewSlideId();
        copy.title = wsText('ws.duplicate_title', 'نسخة من {title}', { title: source.title || wsText('ws.no_title', 'شريحة بدون عنوان') });
        copy.is_custom = true;
        copy.duplicated_from = source.id || '';
        return copy;
      });
      const at = Math.max(...indexes) + 1;
      tenantSlidesData.splice(at, 0, ...copies);
      clearSlideSelection(true);
      renumberTenantSlides();
      renderTenantSlides();
      selectTenantSlide(at);
      markSlidesDeckChanged();
      toast(WFT('ws.slides_duplicated', 'تم تكرار الشرائح المحددة'));
    }

    function deleteSelectedSlides() {
      if (!hasPermission('create_presentation')) return;
      const indexes = selectedSlideIndexes();
      if (!indexes.length) return;
      if (tenantSlidesData.length - indexes.length < 1) {
        toast(WFT('ws.keep_one_slide', 'لا يمكن حذف آخر شريحة'));
        return;
      }
      if (!confirm(wsText('ws.delete_selected_confirm', 'حذف {n} شرائح محددة؟', { n: indexes.length }))) return;
      beginPresentationUndoChange();
      const anchor = activeSlideIndex;
      const removedBefore = indexes.filter(index => index < anchor).length;
      const removedSelf = indexes.includes(anchor);
      tenantSlidesData = tenantSlidesData.filter((slide, index) => !indexes.includes(index));
      let next = anchor - removedBefore;
      if (removedSelf) next = Math.min(next, tenantSlidesData.length - 1);
      next = Math.max(0, Math.min(next, tenantSlidesData.length - 1));
      activeSlideIndex = next;
      tenantChatSlideIndex = Math.min(tenantChatSlideIndex, tenantSlidesData.length - 1);
      clearSlideSelection(true);
      renumberTenantSlides();
      renderTenantSlides();
      selectTenantSlide(next, true);
      markSlidesDeckChanged();
      toast(WFT('ws.slides_deleted', 'تم حذف الشرائح المحددة'));
    }

    function startRenameTenantSlide(index) {
      const slide = tenantSlidesData[index];
      if (!slide) return;
      tenantThumbRenamingId = slideRuntimeId(slide);
      if (!tenantSlidesSidebarCollapsed) renderTenantSlidesSidebar();
    }

    function commitTenantSlideRename(index, value) {
      const slide = tenantSlidesData[index];
      tenantThumbRenamingId = '';
      if (!slide) return;
      const title = String(value || '').trim();
      if (!title || title === slide.title) {
        renderTenantSlidesSidebar();
        return;
      }
      beginPresentationUndoChange();
      slide.title = title;
      markSlideHtmlEdited(slide);
      markSlidesDeckChanged();
      renderTenantSlidesSidebar();
    }

    /* Notes and section are written in an inline card with debounced autosave,
       never a browser prompt. The note belongs to the slide, so it saves with
       the deck and shows up in the present view and the shared link. */

    let tenantSlideEditorSlideId = '';
    let tenantSlideEditorField = '';
    let tenantSlideEditorOriginal = '';
    let tenantSlideEditorChanged = false;
    let tenantSlideEditorTimer = null;

    function setTenantSlideEditorState(text) {
      const state = document.getElementById('tenantSlideEditorState');
      if (state) state.textContent = text || '';
    }

    function ensureTenantSlideEditor() {
      let pop = document.getElementById('tenantSlideEditor');
      if (pop) return pop;
      pop = document.createElement('div');
      pop.id = 'tenantSlideEditor';
      pop.className = 'slide-editor-popover';
      pop.hidden = true;
      pop.innerHTML = '<div class="slide-editor-popover-head">'
        + '<span class="slide-editor-popover-title" id="tenantSlideEditorTitle"></span>'
        + '<button type="button" class="slide-editor-popover-close" data-ws-icon="close"'
        + ' aria-label="إغلاق" title="إغلاق" onclick="closeTenantSlideEditor()"></button>'
        + '</div>'
        + '<textarea id="tenantSlideEditorInput" rows="4"></textarea>'
        + '<div class="slide-editor-popover-foot">'
        + '<button type="button" class="slide-editor-popover-clear" id="tenantSlideEditorClear"'
        + ' onclick="clearTenantSlideEditor()"></button>'
        + '<span class="slide-editor-popover-state" id="tenantSlideEditorState"></span>'
        + '</div>';
      document.body.appendChild(pop);
      hydrateWorkspaceIcons(pop);
      const input = pop.querySelector('#tenantSlideEditorInput');
      input.addEventListener('input', () => {
        setTenantSlideEditorState(wsText('ws.editor_pending', 'تعديل غير محفوظ'));
        if (tenantSlideEditorTimer) clearTimeout(tenantSlideEditorTimer);
        tenantSlideEditorTimer = setTimeout(commitTenantSlideEditor, 450);
      });
      input.addEventListener('blur', commitTenantSlideEditor);
      input.addEventListener('keydown', event => {
        event.stopPropagation();
        if (event.key === 'Escape') {
          event.preventDefault();
          closeTenantSlideEditor();
          return;
        }
        if (event.key === 'Enter' && tenantSlideEditorField === 'group') {
          event.preventDefault();
          closeTenantSlideEditor();
        }
      });
      return pop;
    }

    function openTenantSlideEditor(index, field) {
      const slide = tenantSlidesData[index];
      if (!slide || !hasPermission('create_presentation')) return;
      const pop = ensureTenantSlideEditor();
      tenantSlideEditorSlideId = slideRuntimeId(slide);
      tenantSlideEditorField = field;
      tenantSlideEditorOriginal = String(slide[field] || '').trim();
      tenantSlideEditorChanged = false;
      const isGroup = field === 'group';
      const heading = isGroup
        ? wsText('ws.group_prompt', 'اسم القسم')
        : wsText('ws.notes_prompt', 'ملاحظات الشريحة');
      pop.querySelector('#tenantSlideEditorTitle').textContent = slide.title
        ? slide.title + ' — ' + heading
        : heading;
      const input = pop.querySelector('#tenantSlideEditorInput');
      input.rows = isGroup ? 1 : 4;
      input.placeholder = isGroup
        ? wsText('ws.group_placeholder', 'اسم القسم')
        : wsText('ws.notes_placeholder', 'اكتب ملاحظات هذه الشريحة');
      input.value = String(slide[field] || '');
      const clear = pop.querySelector('#tenantSlideEditorClear');
      clear.textContent = isGroup
        ? wsText('ws.group_clear', 'إزالة القسم')
        : wsText('ws.notes_clear', 'مسح الملاحظات');
      setTenantSlideEditorState('');
      pop.hidden = false;
      input.focus();
      try { input.setSelectionRange(input.value.length, input.value.length); } catch (error) {}
    }

    function tenantSlideEditorTarget() {
      if (!tenantSlideEditorField) return null;
      const index = slideIndexById(tenantSlideEditorSlideId);
      return index === -1 ? null : tenantSlidesData[index];
    }

    function commitTenantSlideEditor() {
      if (tenantSlideEditorTimer) {
        clearTimeout(tenantSlideEditorTimer);
        tenantSlideEditorTimer = null;
      }
      const input = document.getElementById('tenantSlideEditorInput');
      const slide = tenantSlideEditorTarget();
      if (!input || !slide) return;
      const value = String(input.value || '').trim();
      if (value === tenantSlideEditorOriginal) {
        setTenantSlideEditorState(wsText('ws.editor_saved', 'محفوظ'));
        return;
      }
      if (!tenantSlideEditorChanged) {
        beginPresentationUndoChange();
        tenantSlideEditorChanged = true;
      }
      slide[tenantSlideEditorField] = value;
      tenantSlideEditorOriginal = value;
      markSlidesDeckChanged();
      renderTenantSlidesSidebar();
      setTenantSlideEditorState(wsText('ws.editor_saved', 'محفوظ'));
    }

    function clearTenantSlideEditor() {
      const input = document.getElementById('tenantSlideEditorInput');
      if (!input) return;
      input.value = '';
      commitTenantSlideEditor();
      if (tenantSlideEditorField !== 'group') input.focus();
    }

    function closeTenantSlideEditor() {
      commitTenantSlideEditor();
      tenantSlideEditorField = '';
      tenantSlideEditorSlideId = '';
      tenantSlideEditorChanged = false;
      const pop = document.getElementById('tenantSlideEditor');
      if (pop) pop.hidden = true;
    }

    function openTenantSlideNotesEditor(index) {
      openTenantSlideEditor(index, 'notes');
    }

    function openTenantSlideGroupEditor(index) {
      openTenantSlideEditor(index, 'group');
    }

    function editTenantSlideNotes(index) {
      openTenantSlideNotesEditor(index);
    }

    function editTenantSlideGroup(index) {
      openTenantSlideGroupEditor(index);
    }

    /* ── Present mode ───────────────────────────────────────────────────── */

    function presentSlideMarkup(slide) {
      const html = slideThumbnailHtml(slide);
      if (html) return html;
      return '<div class="slide" style="width:1280px;height:720px;background:#fff;padding:80px;'
        + 'display:flex;align-items:center;justify-content:center;font-size:44px;color:#334155;">'
        + escapeHtml(slide && slide.title ? slide.title : '') + '</div>';
    }

    function renderTenantPresentSlide() {
      const overlay = document.getElementById('tenantPresentOverlay');
      const stage = document.getElementById('tenantPresentStage');
      const counter = document.getElementById('tenantPresentCounter');
      if (!overlay || !stage) return;
      const slide = tenantSlidesData[tenantPresentIndex];
      if (!slide) return;
      stage.innerHTML = presentSlideMarkup(slide);
      if (counter) counter.textContent = (tenantPresentIndex + 1) + ' / ' + tenantSlidesData.length;
      renderTenantPresentNotes(slide);
      fitTenantPresentStage();
      if (typeof reapplyDesignerSlideActivity === 'function') { /* presentation view stays read-only */ }
    }

    function renderTenantPresentNotes(slide) {
      const panel = document.getElementById('tenantPresentNotes');
      const body = document.getElementById('tenantPresentNotesBody');
      const button = document.getElementById('presentNotesButton');
      const notes = String((slide && slide.notes) || '').trim();
      if (button) button.hidden = !notes;
      if (body) {
        body.textContent = notes
          ? notes
          : wsText('ws.present_notes_empty', 'لا توجد ملاحظات لهذه الشريحة');
      }
      if (!notes) {
        if (panel) panel.hidden = true;
        if (button) button.classList.remove('is-active');
      }
    }

    function toggleTenantPresentNotes() {
      const panel = document.getElementById('tenantPresentNotes');
      const button = document.getElementById('presentNotesButton');
      if (!panel) return;
      panel.hidden = !panel.hidden;
      if (button) button.classList.toggle('is-active', !panel.hidden);
      showTenantPresentControls();
    }

    function fitTenantPresentStage() {
      const overlay = document.getElementById('tenantPresentOverlay');
      const stage = document.getElementById('tenantPresentStage');
      if (!overlay || !stage) return;
      const scale = Math.min(window.innerWidth / 1280, window.innerHeight / 720) * 0.94;
      stage.style.transform = 'scale(' + scale.toFixed(4) + ')';
    }

    function showTenantPresentControls() {
      const overlay = document.getElementById('tenantPresentOverlay');
      if (!overlay) return;
      overlay.classList.remove('controls-hidden');
      if (tenantPresentHideTimer) clearTimeout(tenantPresentHideTimer);
      tenantPresentHideTimer = setTimeout(() => {
        overlay.classList.add('controls-hidden');
      }, 2600);
    }

    function visibleSlideIndexes() {
      return tenantSlidesData
        .map((slide, index) => ({ slide, index }))
        .filter(entry => entry.slide && !entry.slide.hidden)
        .map(entry => entry.index);
    }

    function nearestVisibleSlideIndex(from, direction) {
      const visible = visibleSlideIndexes();
      if (!visible.length) return -1;
      const start = Math.max(0, Math.min(Number(from) || 0, tenantSlidesData.length - 1));
      if (visible.includes(start)) return start;
      if (direction < 0) {
        for (let index = start - 1; index >= 0; index -= 1) if (visible.includes(index)) return index;
        return visible[0];
      }
      for (let index = start + 1; index < tenantSlidesData.length; index += 1) {
        if (visible.includes(index)) return index;
      }
      return visible[visible.length - 1];
    }

    function openTenantPresentation(startIndex) {
      if (!tenantSlidesData.length) return;
      const requested = Number.isInteger(startIndex)
        ? Math.max(0, Math.min(startIndex, tenantSlidesData.length - 1))
        : Math.max(0, Math.min(activeSlideIndex, tenantSlidesData.length - 1));
      const firstVisible = nearestVisibleSlideIndex(requested, 1);
      if (firstVisible === -1) {
        toast(WFT('ws.present_all_hidden', 'كل شرائح العرض مخفية'));
        return;
      }
      tenantPresentActive = true;
      tenantPresentIndex = firstVisible;
      const overlay = document.getElementById('tenantPresentOverlay');
      if (overlay) overlay.classList.add('is-open');
      document.documentElement.style.overflow = 'hidden';
      const openingNotes = String((tenantSlidesData[firstVisible] || {}).notes || '').trim();
      const notesPanel = document.getElementById('tenantPresentNotes');
      const notesButton = document.getElementById('presentNotesButton');
      if (notesPanel) notesPanel.hidden = !openingNotes;
      if (notesButton) notesButton.classList.toggle('is-active', !!openingNotes);
      renderTenantPresentSlide();
      showTenantPresentControls();
      const shell = document.getElementById('tenantSlidesPage');
      if (shell && shell.requestFullscreen) {
        shell.requestFullscreen().catch(() => {});
      }
    }

    function closeTenantPresentation() {
      tenantPresentActive = false;
      const overlay = document.getElementById('tenantPresentOverlay');
      if (overlay) overlay.classList.remove('is-open', 'controls-hidden');
      const notesPanel = document.getElementById('tenantPresentNotes');
      const notesButton = document.getElementById('presentNotesButton');
      if (notesPanel) notesPanel.hidden = true;
      if (notesButton) notesButton.classList.remove('is-active');
      document.documentElement.style.overflow = '';
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }
      if (tenantPresentHideTimer) {
        clearTimeout(tenantPresentHideTimer);
        tenantPresentHideTimer = null;
      }
      const prev = document.getElementById('presentSlidesPrevButton');
      if (prev) prev.focus({ preventScroll: true });
    }

    function stepTenantPresentation(delta) {
      if (!tenantPresentActive) return;
      let next = tenantPresentIndex + Number(delta || 0);
      while (next >= 0 && next < tenantSlidesData.length && tenantSlidesData[next] && tenantSlidesData[next].hidden) {
        next += Number(delta || 0) >= 0 ? 1 : -1;
      }
      if (next < 0 || next >= tenantSlidesData.length) return;
      tenantPresentIndex = next;
      renderTenantPresentSlide();
      showTenantPresentControls();
    }

    function handleTenantPresentationKey(event) {
      if (!tenantPresentActive) return;
      const target = event.target;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || ''))) return;
      if (event.key === 'Escape') { event.preventDefault(); closeTenantPresentation(); return; }
      if (['ArrowLeft', 'PageDown', ' ', 'Spacebar', 'ArrowDown'].includes(event.key)) {
        event.preventDefault();
        stepTenantPresentation(1);
        return;
      }
      if (['ArrowRight', 'PageUp', 'ArrowUp'].includes(event.key)) {
        event.preventDefault();
        stepTenantPresentation(-1);
        return;
      }
      if (event.key === 'Home') { event.preventDefault(); tenantPresentIndex = 0; renderTenantPresentSlide(); }
      if (event.key === 'End') { event.preventDefault(); tenantPresentIndex = tenantSlidesData.length - 1; renderTenantPresentSlide(); }
    }

    /* ── Chat panel: collapse, resize, conversation lifecycle ───────────── */

    function applyTenantChatPanelState() {
      const panel = document.getElementById('tenantSlidesChat');
      if (!panel) return;
      let collapsed = false;
      let width = 340;
      try {
        collapsed = localStorage.getItem('wf.slidesChatCollapsed') === '1';
        width = Number(localStorage.getItem('wf.slidesChatWidth')) || 340;
      } catch (error) {}
      panel.classList.toggle('is-collapsed', !!collapsed);
      panel.style.setProperty('--chat-width', Math.max(260, Math.min(560, width)) + 'px');
    }

    function toggleTenantChatPanel() {
      const panel = document.getElementById('tenantSlidesChat');
      if (!panel) return;
      const collapsed = !panel.classList.contains('is-collapsed');
      panel.classList.toggle('is-collapsed', collapsed);
      try { localStorage.setItem('wf.slidesChatCollapsed', collapsed ? '1' : '0'); } catch (error) {}
    }

    function bindTenantChatResize() {
      const handle = document.getElementById('tenantChatResize');
      const panel = document.getElementById('tenantSlidesChat');
      if (!handle || !panel || handle.dataset.bound === '1') return;
      handle.dataset.bound = '1';
      handle.addEventListener('pointerdown', event => {
        if (panel.classList.contains('is-collapsed')) return;
        event.preventDefault();
        const startX = event.clientX;
        const startWidth = panel.getBoundingClientRect().width;
        handle.setPointerCapture(event.pointerId);
        const move = moveEvent => {
          const width = Math.max(260, Math.min(560, startWidth + (moveEvent.clientX - startX)));
          panel.style.setProperty('--chat-width', width + 'px');
        };
        const up = () => {
          handle.removeEventListener('pointermove', move);
          handle.removeEventListener('pointerup', up);
          handle.removeEventListener('pointercancel', up);
          try {
            localStorage.setItem('wf.slidesChatWidth', String(Math.round(panel.getBoundingClientRect().width)));
          } catch (error) {}
        };
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', up);
        handle.addEventListener('pointercancel', up);
      });
    }

    function resetTenantDesignerConversationState() {
      tenantDesignerMessages = [];
      tenantDesignerChatMemory = '';
      tenantChatFocusIndexes = [];
      tenantChatSlideScope = 'auto';
      tenantProjectData.designerChat = designerChatPersistence();
      if (typeof clearDesignerChecklist === 'function') clearDesignerChecklist();
      renderTenantDesignerChat();
      triggerAutoSaveDraft();
    }

    function startNewTenantDesignerConversation() {
      if (tenantDesignerChatBusy || (typeof currentTenantDesignerJob === 'function' && currentTenantDesignerJob())) {
        toast(WFT('ws.chat_busy', 'لا يمكن بدء محادثة جديدة أثناء تنفيذ مهمة'));
        return;
      }
      resetTenantDesignerConversationState();
      toast(WFT('ws.conversation_started', 'بدأت محادثة جديدة'));
    }

    function deleteTenantDesignerConversation() {
      if (tenantDesignerChatBusy || (typeof currentTenantDesignerJob === 'function' && currentTenantDesignerJob())) {
        toast(WFT('ws.chat_busy', 'لا يمكن بدء محادثة جديدة أثناء تنفيذ مهمة'));
        return;
      }
      if (!confirm(WFT('ws.delete_conversation_confirm', 'حذف المحادثة الحالية؟'))) return;
      resetTenantDesignerConversationState();
      toast(WFT('ws.conversation_deleted', 'حُذفت المحادثة'));
    }

    function stopTenantDesignerChat() {
      if (typeof cancelDesignerJob === 'function') {
        void cancelDesignerJob();
        return;
      }
      if (typeof stopTenantGeneration === 'function') stopTenantGeneration();
    }

    function renderTenantComposerState() {
      const busy = !!(typeof tenantDesignerChatBusy !== 'undefined' && tenantDesignerChatBusy);
      const send = document.querySelector('#tenantSlidesChat .tenant-chat-send');
      const stop = document.getElementById('tenantChatStopButton');
      const attach = document.querySelector('#tenantSlidesChat .tenant-chat-attach');
      if (send) send.hidden = busy;
      if (stop) stop.hidden = !busy;
      if (attach) attach.disabled = busy;
    }

    /* ── Boot wiring ────────────────────────────────────────────────────── */

    document.addEventListener('keydown', handleTenantPresentationKey);
    window.addEventListener('mousemove', event => {
      if (!tenantPresentActive) return;
      const overlay = document.getElementById('tenantPresentOverlay');
      if (overlay && event.target && overlay.contains(event.target)) showTenantPresentControls();
    }, { passive: true });
    window.addEventListener('resize', () => {
      if (tenantPresentActive) fitTenantPresentStage();
    });
    document.addEventListener('fullscreenchange', () => {
      if (tenantPresentActive) fitTenantPresentStage();
    });

    (function initSlidesWorkspace() {
      try {
        localStorage.getItem('wf.slidesSidebarCollapsed');
      } catch (error) {}
      try {
        tenantSlidesSidebarCollapsed = localStorage.getItem('wf.slidesSidebarCollapsed') === '1';
      } catch (error) {}
      applyTenantChatPanelState();
      bindTenantChatResize();
      hydrateWorkspaceIcons(document);
      renderSlidesHeader();
    })();
