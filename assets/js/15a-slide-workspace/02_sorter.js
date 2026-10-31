/* Sorter view: the whole deck as a grid, drag to reorder, insert between
   slides. The deck itself stays the single source of truth — this view only
   calls the same move/insert functions the sidebar uses. */

    let tenantSorterDragId = '';
    let tenantSorterObserver = null;

    function sorterText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function sorterCardSlideId(card) {
      return card ? String(card.dataset.slideId || '') : '';
    }

    function renderTenantSlidesSorter() {
      const box = document.getElementById('tenantSlidesSorter');
      if (!box) return;
      box.hidden = tenantSlidesView !== 'sorter';
      if (box.hidden) return;
      if (tenantSorterObserver) {
        tenantSorterObserver.disconnect();
        tenantSorterObserver = null;
      }
      box.innerHTML = '';

      if (typeof IntersectionObserver !== 'undefined') {
        tenantSorterObserver = new IntersectionObserver(entries => {
          entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const canvas = entry.target;
            const index = Number(canvas.dataset.thumbIndex);
            const slide = tenantSlidesData[index];
            if (slide && typeof fillSlideThumbnailCanvas === 'function') fillSlideThumbnailCanvas(canvas, slide);
            tenantSorterObserver.unobserve(canvas);
          });
        }, { root: box, rootMargin: '240px' });
      }

      const grid = document.createElement('div');
      grid.className = 'ge-sorter-grid';

      tenantSlidesData.forEach((slide, index) => {
        const cell = document.createElement('div');
        cell.className = 'ge-sorter-cell';

        const card = document.createElement('div');
        card.className = 'ge-sorter-card' + (index === activeSlideIndex ? ' active' : '')
          + (slide.hidden ? ' is-hidden' : '');
        card.dataset.slideId = String(slide.id || '');
        card.dataset.sorterIndex = String(index);
        card.draggable = hasPermission('create_presentation');
        card.onclick = () => {
          selectTenantSlide(index);
          document.querySelectorAll('#tenantSlidesSorter .ge-sorter-card').forEach(el => {
            el.classList.toggle('active', Number(el.dataset.sorterIndex) === index);
          });
        };
        card.ondblclick = () => {
          setSlidesWorkspaceView('edit');
          selectTenantSlide(index);
        };
        card.ondragstart = event => {
          tenantSorterDragId = String(slide.id || '');
          cell.classList.add('is-dragging');
          if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', tenantSorterDragId);
          }
        };
        card.ondragend = () => {
          tenantSorterDragId = '';
          cell.classList.remove('is-dragging');
          document.querySelectorAll('#tenantSlidesSorter .ge-sorter-cell').forEach(el => el.classList.remove('drop-target'));
        };
        cell.ondragover = event => {
          if (!tenantSorterDragId) return;
          event.preventDefault();
          if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
          cell.classList.add('drop-target');
        };
        cell.ondragleave = () => cell.classList.remove('drop-target');
        cell.ondrop = event => {
          event.preventDefault();
          cell.classList.remove('drop-target');
          const fromId = tenantSorterDragId || (event.dataTransfer ? event.dataTransfer.getData('text/plain') : '');
          tenantSorterDragId = '';
          const from = slideIndexById(fromId);
          if (from === -1 || from === index) return;
          moveTenantSlide(from, index);
          renderTenantSlidesSorter();
        };

        const frame = document.createElement('div');
        frame.className = 'ge-thumb-frame';
        const canvas = document.createElement('div');
        canvas.className = 'ge-thumb-canvas';
        canvas.dataset.thumbIndex = String(index);
        frame.appendChild(canvas);
        card.appendChild(frame);

        const label = document.createElement('div');
        label.className = 'ge-sorter-label';
        label.innerHTML = '<span class="ge-thumb-num">' + (index + 1) + '</span>'
          + '<span class="ge-thumb-title">' + escapeHtml(slide.title || sorterText('ws.no_title', 'شريحة بدون عنوان')) + '</span>';
        card.appendChild(label);

        const insert = document.createElement('button');
        insert.type = 'button';
        insert.className = 'ge-sorter-insert';
        insert.textContent = '+';
        insert.title = sorterText('ws.add_after', 'إضافة شريحة');
        insert.setAttribute('aria-label', sorterText('ws.add_after', 'إضافة شريحة'));
        insert.onclick = event => {
          event.stopPropagation();
          if (typeof openSlideInsertMenu === 'function') openSlideInsertMenu(insert, index + 1);
        };

        cell.appendChild(card);
        cell.appendChild(insert);
        grid.appendChild(cell);

        if (tenantSorterObserver) tenantSorterObserver.observe(canvas);
        else if (typeof fillSlideThumbnailCanvas === 'function') fillSlideThumbnailCanvas(canvas, slide);
      });

      const addCell = document.createElement('div');
      addCell.className = 'ge-sorter-cell ge-sorter-add-cell';
      addCell.innerHTML = '<button type="button" onclick="openSlideInsertMenu(this, ' + tenantSlidesData.length
        + ')">' + escapeHtml(sorterText('ws.add_slide', 'إضافة شريحة')) + '</button>';
      grid.appendChild(addCell);

      box.appendChild(grid);
    }

    document.addEventListener('wf:lang', () => {
      try {
        if (tenantSlidesView === 'sorter') renderTenantSlidesSorter();
      } catch (error) { /* ignore */ }
    });
