/* Sorter view: the whole deck as a grid. Cards are built once; dragging moves
   a dashed gap under the pointer and the neighbouring cards slide with a FLIP
   animation, so the landing spot is visible before the drop. The drop reorders
   the existing nodes — the grid is never rebuilt, so thumbnails stay painted. */

    let tenantSorterDragId = '';
    let tenantSorterDragCardHeight = 0;
    let tenantSorterPlaceholder = null;
    let tenantSorterLastSlot = null;
    let tenantSorterObserver = null;
    let tenantSorterDropHandled = false;
    let tenantSorterLastLeaveAt = 0;
    let tenantSorterSuppressRender = false;

    /* SORTER_PURE_BEGIN */
    // Where the pointer lands among the cards, as a boundary index into the
    // reading-ordered item list. Counting against card midpoints keeps the slot
    // stable when the landing gap reflows the grid under a resting pointer —
    // reading the hovered card instead made the gap walk on its own.
    function sorterDropBoundary(items, clientX, clientY, isRtl) {
      if (!items || !items.length) return 0;
      const rows = [];
      items.forEach(item => {
        const rect = item.rect;
        const row = rows.find(entry => Math.abs(entry.top - rect.top) < 10);
        if (row) row.items.push(item);
        else rows.push({ top: rect.top, items: [item] });
      });
      rows.sort((a, b) => a.top - b.top);
      let row = rows.find(entry => {
        const rect = entry.items[0].rect;
        return clientY >= rect.top && clientY <= rect.top + (rect.height || 0);
      }) || null;
      if (!row) {
        let bestDistance = Infinity;
        rows.forEach(entry => {
          const rect = entry.items[0].rect;
          const distance = Math.abs(rect.top + (rect.height || 0) / 2 - clientY);
          if (distance < bestDistance) {
            bestDistance = distance;
            row = entry;
          }
        });
      }
      let boundary = items.indexOf(row.items[0]);
      row.items.forEach(item => {
        const center = item.rect.left + item.rect.width / 2;
        if (isRtl ? center >= clientX : center <= clientX) boundary += 1;
      });
      return boundary;
    }

    // The + hangs on its card's inline-start edge. In RTL that edge faces the
    // previous card, so the gap it marks is BEFORE this card; in LTR the same
    // edge faces the next card, so the gap is after it. Inserting anywhere
    // else put the new slide one slot past the gap the client clicked.
    function sorterInsertIndex(index, isRtl) {
      const base = Number.isFinite(Number(index)) ? Math.max(0, Math.floor(Number(index))) : 0;
      return isRtl ? base : base + 1;
    }

    // Final array index of the dragged slide for a "before"/"after" drop on the
    // cell at targetIndex, or at the end. -1 means the slot is impossible.
    function sorterDropFinalIndex(from, targetIndex, mode, total) {
      if (mode === 'end') return total > 0 ? total - 1 : -1;
      if (from < 0 || from >= total) return -1;
      if (targetIndex < 0 || targetIndex >= total) return -1;
      if (mode === 'before') return from < targetIndex ? targetIndex - 1 : targetIndex;
      return from <= targetIndex ? targetIndex : targetIndex + 1;
    }
    /* SORTER_PURE_END */

    function sorterText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function sorterPrefersReducedMotion() {
      try {
        return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
          && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      } catch (error) { return false; }
    }

    function sorterIsRtl(grid) {
      try {
        if (document.dir) return document.dir === 'rtl';
      } catch (error) { /* ignore */ }
      try {
        if (typeof getComputedStyle === 'function') return getComputedStyle(grid).direction === 'rtl';
      } catch (error) { /* ignore */ }
      return true;
    }

    // Layout position without the running FLIP transform, so a slot decision
    // made mid-animation matches where the cards will settle.
    function sorterLayoutRect(element) {
      const rect = element.getBoundingClientRect();
      try {
        if (typeof getComputedStyle === 'function') {
          const transform = getComputedStyle(element).transform;
          if (transform && transform !== 'none' && typeof DOMMatrixReadOnly === 'function') {
            const matrix = new DOMMatrixReadOnly(transform);
            const zoom = typeof wfRootZoom === 'function' ? wfRootZoom() : 1;
            return {
              left: rect.left - matrix.m41 * zoom,
              top: rect.top - matrix.m42 * zoom,
              width: rect.width,
              height: rect.height
            };
          }
        }
      } catch (error) { /* ignore */ }
      return rect;
    }

    function sorterFlipCells(grid, mutate) {
      if (!grid) { mutate(); return; }
      const reduceMotion = sorterPrefersReducedMotion();
      const items = Array.from(grid.children).filter(el => el !== tenantSorterPlaceholder);
      const before = new Map();
      if (!reduceMotion) {
        items.forEach(el => {
          try {
            if (typeof el.getAnimations === 'function') {
              el.getAnimations().forEach(animation => animation.cancel());
            }
          } catch (error) { /* ignore */ }
          const rect = el.getBoundingClientRect();
          if (rect && (rect.width || rect.height)) before.set(el, { left: rect.left, top: rect.top });
        });
      }
      mutate();
      if (reduceMotion) return;
      items.forEach(el => {
        const first = before.get(el);
        if (!first || !el.isConnected || typeof el.animate !== 'function') return;
        const rect = el.getBoundingClientRect();
        if (!rect || !(rect.width || rect.height)) return;
        // Rects are painted, transforms are layout: convert before animating.
        const zoom = typeof wfRootZoom === 'function' ? wfRootZoom() : 1;
        const dx = Math.round((first.left - rect.left) / zoom * 10) / 10;
        const dy = Math.round((first.top - rect.top) / zoom * 10) / 10;
        if (!dx && !dy) return;
        try {
          el.animate(
            [{ transform: 'translate(' + dx + 'px, ' + dy + 'px)' }, { transform: 'translate(0, 0)' }],
            { duration: 180, easing: 'cubic-bezier(.2, .8, .2, 1)' }
          );
        } catch (error) { /* ignore */ }
      });
    }

    function sorterCreatePlaceholder() {
      const placeholder = document.createElement('div');
      placeholder.className = 'ge-sorter-placeholder';
      placeholder.setAttribute('aria-hidden', 'true');
      placeholder.style.height = (tenantSorterDragCardHeight || 150) + 'px';
      return placeholder;
    }

    function sorterPlacePlaceholder(grid, slot, node) {
      if (slot.mode === 'end' || !slot.cell) {
        const addCell = grid.querySelector('.ge-sorter-add-cell');
        if (addCell) grid.insertBefore(node, addCell);
        else grid.appendChild(node);
        return node;
      }
      if (slot.mode === 'after') {
        const next = slot.cell.nextSibling;
        if (next) grid.insertBefore(node, next);
        else grid.appendChild(node);
      } else {
        grid.insertBefore(node, slot.cell);
      }
      return node;
    }

    function sorterResolveDropSlot(grid, target, clientX, clientY) {
      if (target && typeof target.closest === 'function' && target.closest('.ge-sorter-add-cell')) {
        return { mode: 'end', cell: null, key: 'end' };
      }
      const cells = grid.querySelectorAll('.ge-sorter-cell:not(.ge-sorter-add-cell)');
      const items = [];
      cells.forEach(cell => {
        if (cell.classList.contains('is-dragging-source')) return;
        const rect = sorterLayoutRect(cell);
        if (!rect || (!rect.width && !rect.height)) return;
        items.push({ cell: cell, rect: rect });
      });
      if (!items.length) return { mode: 'end', cell: null, key: 'end' };
      const boundary = sorterDropBoundary(items, clientX, clientY, sorterIsRtl(grid));
      if (boundary >= items.length) return { mode: 'end', cell: null, key: 'end' };
      const cell = items[Math.max(boundary, 0)].cell;
      return {
        mode: 'before',
        cell: cell,
        key: 'before:' + String(cell.dataset.slideId || boundary)
      };
    }

    function sorterCellBySlideId(grid, id) {
      const wanted = String(id || '');
      if (!wanted || !grid) return null;
      const cells = grid.querySelectorAll('.ge-sorter-cell:not(.ge-sorter-add-cell)');
      for (let index = 0; index < cells.length; index += 1) {
        if (String(cells[index].dataset.slideId || '') === wanted) return cells[index];
      }
      return null;
    }

    // The editor list was display:none while the sorter was showing, so a
    // scroll issued in the same tick as the view switch is measured against a
    // hidden container and settles back on the cover. Apply the selection
    // immediately, then reveal the card once the editor has real layout.
    function sorterOpenSlideInEditor(index) {
      setSlidesWorkspaceView('edit');
      selectTenantSlide(index, true);
      const reveal = () => selectTenantSlide(index);
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(() => requestAnimationFrame(reveal));
      } else {
        reveal();
      }
    }

    function sorterHighlightActive(grid) {
      const cells = grid.querySelectorAll('.ge-sorter-cell:not(.ge-sorter-add-cell)');
      cells.forEach(cell => {
        const card = cell.querySelector('.ge-sorter-card');
        if (card) card.classList.toggle('active', Number(cell.dataset.sorterIndex) === activeSlideIndex);
      });
    }

    function sorterSyncCellIndexes(grid) {
      const cells = grid.querySelectorAll('.ge-sorter-cell:not(.ge-sorter-add-cell)');
      cells.forEach((cell, index) => {
        cell.dataset.sorterIndex = String(index);
        const number = cell.querySelector('.ge-thumb-num');
        if (number) number.textContent = String(index + 1);
        const canvas = cell.querySelector('.ge-thumb-canvas');
        // A lazily painted thumbnail reads this index; leaving it stale would
        // paint an untouched card with the slide that used to sit there.
        if (canvas && canvas.dataset.filled !== '1') canvas.dataset.thumbIndex = String(index);
      });
      sorterHighlightActive(grid);
    }

    function sorterUpdateDragPreview(grid, slot) {
      const from = slideIndexById(tenantSorterDragId);
      if (from === -1) return;
      const total = tenantSlidesData.length;
      const targetIndex = slot.mode === 'end' ? total : Number(slot.cell.dataset.sorterIndex);
      const finalIndex = sorterDropFinalIndex(from, targetIndex, slot.mode, total);
      const placeholder = tenantSorterPlaceholder;
      if (finalIndex === from) {
        // Landing where the card already is: the gap rests over its home slot.
        const sourceCell = sorterCellBySlideId(grid, tenantSorterDragId);
        if (!sourceCell) return;
        if (placeholder && placeholder.isConnected && placeholder.dataset.slotKey === 'home') return;
        sorterFlipCells(grid, () => {
          const node = (placeholder && placeholder.isConnected)
            ? placeholder
            : sorterCreatePlaceholder();
          tenantSorterPlaceholder = node;
          node.dataset.slotKey = 'home';
          grid.insertBefore(node, sourceCell);
        });
        return;
      }
      if (placeholder && placeholder.isConnected && placeholder.dataset.slotKey === slot.key) return;
      sorterFlipCells(grid, () => {
        const node = (placeholder && placeholder.isConnected)
          ? placeholder
          : sorterCreatePlaceholder();
        tenantSorterPlaceholder = node;
        node.dataset.slotKey = slot.key;
        sorterPlacePlaceholder(grid, slot, node);
      });
    }

    function sorterHandleGridDragOver(grid, event) {
      if (!tenantSorterDragId) return;
      if (slideIndexById(tenantSorterDragId) === -1) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      const slot = sorterResolveDropSlot(grid, event.target, event.clientX, event.clientY);
      tenantSorterLastSlot = slot;
      sorterUpdateDragPreview(grid, slot);
    }

    function sorterApplyDrop(grid, slot) {
      const from = slideIndexById(tenantSorterDragId);
      const sourceCell = sorterCellBySlideId(grid, tenantSorterDragId);
      const placeholder = tenantSorterPlaceholder;
      tenantSorterDragId = '';
      tenantSorterLastSlot = null;
      tenantSorterDragCardHeight = 0;
      tenantSorterPlaceholder = null;
      const restore = () => {
        if (sourceCell) sourceCell.classList.remove('is-dragging-source');
        if (placeholder && placeholder.isConnected) placeholder.remove();
      };
      if (from === -1 || !slot || !sourceCell) {
        sorterFlipCells(grid, restore);
        return;
      }
      const total = tenantSlidesData.length;
      const targetIndex = slot.mode === 'end' ? total : Number(slot.cell.dataset.sorterIndex);
      const finalIndex = sorterDropFinalIndex(from, targetIndex, slot.mode, total);
      if (finalIndex === from) {
        sorterFlipCells(grid, restore);
        return;
      }
      sorterFlipCells(grid, () => {
        let slotNode = placeholder;
        if (!slotNode || !slotNode.isConnected) {
          slotNode = sorterCreatePlaceholder();
          sorterPlacePlaceholder(grid, slot, slotNode);
        } else if (slotNode.dataset.slotKey !== slot.key) {
          slotNode.dataset.slotKey = slot.key;
          sorterPlacePlaceholder(grid, slot, slotNode);
        }
        // moveTenantSlide re-renders the sorter; it must not rebuild a grid the
        // drop is reordering in place, so the render is suppressed for the call.
        tenantSorterSuppressRender = true;
        try {
          moveTenantSlide(from, finalIndex);
        } finally {
          tenantSorterSuppressRender = false;
        }
        grid.insertBefore(sourceCell, slotNode);
        slotNode.remove();
        sourceCell.classList.remove('is-dragging-source');
        sorterSyncCellIndexes(grid);
      });
    }

    function sorterHandleGridDrop(grid, event) {
      if (!tenantSorterDragId) return;
      event.preventDefault();
      tenantSorterDropHandled = true;
      const slot = sorterResolveDropSlot(grid, event.target, event.clientX, event.clientY) || tenantSorterLastSlot;
      sorterApplyDrop(grid, slot);
    }

    function sorterRenderCellLabel(cell, slide, index) {
      const label = cell.querySelector('.ge-sorter-label');
      if (!label) return;
      const titleText = slide.title || sorterText('ws.no_title', 'شريحة بدون عنوان');
      const number = label.querySelector('.ge-thumb-num');
      if (number) number.textContent = String(index + 1);
      const title = label.querySelector('.ge-thumb-title');
      if (title) {
        title.textContent = titleText;
        title.setAttribute('title', titleText);
      }
      let remove = label.querySelector('.ge-sorter-delete');
      const canDelete = hasPermission('create_presentation') && tenantSlidesData.length > 1;
      if (canDelete && !remove) {
        remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'ge-sorter-delete';
        remove.onclick = event => {
          event.stopPropagation();
          const current = Number(cell.dataset.sorterIndex);
          if (!Number.isFinite(current)) return;
          if (typeof deleteSlide === 'function') deleteSlide(current);
        };
        remove.ondblclick = event => event.stopPropagation();
        label.appendChild(remove);
      } else if (!canDelete && remove) {
        remove.remove();
        remove = null;
      }
      if (remove) {
        const removeLabel = sorterText('ws.delete', 'حذف');
        remove.textContent = removeLabel;
        remove.title = removeLabel;
        remove.setAttribute('aria-label', removeLabel);
      }
    }

    function sorterBuildCell(grid, slide, index) {
      const cell = document.createElement('div');
      cell.className = 'ge-sorter-cell';
      cell.dataset.slideId = String(slide.id || '');
      cell.dataset.sorterIndex = String(index);

      const card = document.createElement('div');
      card.className = 'ge-sorter-card' + (index === activeSlideIndex ? ' active' : '')
        + (slide.hidden ? ' is-hidden' : '');
      card.dataset.slideId = String(slide.id || '');
      card.dataset.sorterIndex = String(index);
      card.draggable = hasPermission('create_presentation');
      card.onclick = () => {
        const current = Number(cell.dataset.sorterIndex);
        if (!Number.isFinite(current)) return;
        selectTenantSlide(current);
        sorterHighlightActive(grid);
      };
      card.ondblclick = () => {
        const current = Number(cell.dataset.sorterIndex);
        if (!Number.isFinite(current)) return;
        sorterOpenSlideInEditor(current);
      };
      card.ondragstart = event => {
        tenantSorterDragId = String(slide.id || '');
        tenantSorterDropHandled = false;
        tenantSorterLastLeaveAt = 0;
        const rect = card.getBoundingClientRect();
        tenantSorterDragCardHeight = Math.round(rect && rect.height ? rect.height : 0);
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', tenantSorterDragId);
          try { event.dataTransfer.setDragImage(card, 16, 16); } catch (error) { /* ignore */ }
        }
        // Nothing is mutated inside dragstart itself: Chromium drops the
        // native drop phase when the grid changes during that callback. The
        // gap takes the card's own slot on the next frame instead, so the
        // grid still never reflows a full cell when the drag begins.
        const showHomeGap = () => {
          cell.classList.add('is-dragging-source');
          if (tenantSorterPlaceholder || !tenantSorterDragId) return;
          const home = sorterCreatePlaceholder();
          home.dataset.slotKey = 'home';
          tenantSorterPlaceholder = home;
          grid.insertBefore(home, cell);
        };
        if (typeof requestAnimationFrame === 'function') requestAnimationFrame(showHomeGap);
        else showHomeGap();
      };
      card.ondragend = event => {
        const handled = tenantSorterDropHandled;
        // Chromium skips the native drop when the preview reflowed the grid
        // under a resting pointer. A real release is announced by a
        // dragleave right before dragend; an Escape cancel has none, so the
        // fallback below only commits when that signal is fresh.
        const released = (Date.now() - tenantSorterLastLeaveAt) <= 40;
        tenantSorterDropHandled = false;
        if (!handled && released && tenantSorterDragId) {
          let inside = false;
          try {
            const under = event && typeof document.elementFromPoint === 'function'
              ? document.elementFromPoint(event.clientX, event.clientY)
              : null;
            inside = !!(under && grid.contains(under));
          } catch (error) { /* ignore */ }
          if (inside) {
            const slot = sorterResolveDropSlot(grid, document.elementFromPoint(event.clientX, event.clientY), event.clientX, event.clientY)
              || tenantSorterLastSlot;
            sorterApplyDrop(grid, slot);
            return;
          }
        }
        tenantSorterDragId = '';
        tenantSorterLastSlot = null;
        tenantSorterDragCardHeight = 0;
        const placeholder = tenantSorterPlaceholder;
        tenantSorterPlaceholder = null;
        cell.classList.remove('is-dragging-source');
        sorterFlipCells(grid, () => {
          if (placeholder && placeholder.isConnected) placeholder.remove();
        });
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
      const number = document.createElement('span');
      number.className = 'ge-thumb-num';
      number.textContent = String(index + 1);
      label.appendChild(number);
      const title = document.createElement('span');
      title.className = 'ge-thumb-title';
      label.appendChild(title);
      card.appendChild(label);

      const insert = document.createElement('button');
      insert.type = 'button';
      insert.className = 'ge-sorter-insert';
      insert.textContent = '+';
      insert.title = sorterText('ws.add_after', 'إضافة شريحة');
      insert.setAttribute('aria-label', sorterText('ws.add_after', 'إضافة شريحة'));
      insert.onclick = event => {
        event.stopPropagation();
        const current = Number(cell.dataset.sorterIndex);
        if (!Number.isFinite(current)) return;
        const at = sorterInsertIndex(current, sorterIsRtl(grid));
        if (typeof openSlideInsertMenu === 'function') openSlideInsertMenu(insert, at);
      };

      cell.appendChild(card);
      cell.appendChild(insert);
      sorterRenderCellLabel(cell, slide, index);
      return cell;
    }

    function sorterSyncCellContent(cell, slide, index) {
      const id = String(slide.id || '');
      cell.dataset.slideId = id;
      cell.dataset.sorterIndex = String(index);
      const card = cell.querySelector('.ge-sorter-card');
      if (card) {
        card.dataset.slideId = id;
        card.dataset.sorterIndex = String(index);
        card.classList.toggle('active', index === activeSlideIndex);
        card.classList.toggle('is-hidden', !!slide.hidden);
        card.draggable = hasPermission('create_presentation');
      }
      sorterRenderCellLabel(cell, slide, index);
    }

    function sorterAnimateEnter(cell) {
      const card = cell.querySelector('.ge-sorter-card') || cell;
      try {
        card.animate(
          [{ opacity: 0, transform: 'scale(.94)' }, { opacity: 1, transform: 'scale(1)' }],
          { duration: 220, easing: 'cubic-bezier(.2, .8, .2, 1)' }
        );
      } catch (error) { /* ignore */ }
    }

    // The removed card is gone from the layout immediately; a cloned ghost
    // holds its old spot for one short fade so the delete reads as an action
    // instead of a flash.
    function sorterSpawnGhost(grid, cell, rect, gridRect) {
      const ghost = cell.cloneNode(true);
      ghost.classList.remove('ge-sorter-cell');
      ghost.classList.add('ge-sorter-ghost');
      ghost.dataset.slideId = '';
      ghost.style.position = 'absolute';
      // The grid is the containing block, so these are layout lengths while the
      // captured rects are painted ones.
      const zoom = typeof wfRootZoom === 'function' ? wfRootZoom() : 1;
      ghost.style.left = ((rect.left - gridRect.left) / zoom) + 'px';
      ghost.style.top = ((rect.top - gridRect.top) / zoom) + 'px';
      ghost.style.width = (rect.width / zoom) + 'px';
      ghost.style.height = (rect.height / zoom) + 'px';
      ghost.style.pointerEvents = 'none';
      ghost.style.zIndex = '6';
      grid.appendChild(ghost);
      try {
        ghost.animate(
          [{ opacity: 1, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(.92)' }],
          { duration: 180, easing: 'ease-out' }
        );
      } catch (error) { /* ignore */ }
      const drop = () => { if (ghost.parentNode) ghost.remove(); };
      if (typeof setTimeout === 'function') setTimeout(drop, 200);
      return ghost;
    }

    // Inserts and deletes move through the existing grid: the cards that stay
    // keep their nodes and painted thumbnails, the change animates, and the
    // cards that remain slide to their new slots (FLIP). Returns false when
    // the deck was replaced wholesale, where a clean rebuild is the honest
    // answer.
    function sorterReconcileGrid(grid) {
      const cells = Array.from(grid.querySelectorAll('.ge-sorter-cell:not(.ge-sorter-add-cell)'));
      const desired = tenantSlidesData.map(slide => String((slide && slide.id) || ''));
      if (!cells.length || !desired.length || desired.some(id => !id)) return false;
      const existing = new Map();
      cells.forEach(cell => {
        const id = String(cell.dataset.slideId || '');
        if (id) existing.set(id, cell);
      });
      if (!desired.some(id => existing.has(id))) return false;
      const reduceMotion = sorterPrefersReducedMotion();
      const gridRect = grid.getBoundingClientRect();
      const before = new Map();
      if (!reduceMotion) {
        cells.forEach(cell => {
          const id = String(cell.dataset.slideId || '');
          if (!id) return;
          const rect = sorterLayoutRect(cell);
          if (rect && (rect.width || rect.height)) before.set(id, rect);
        });
      }
      const keep = new Set(desired);
      cells.forEach(cell => {
        const id = String(cell.dataset.slideId || '');
        if (keep.has(id)) return;
        if (!reduceMotion && before.has(id)) sorterSpawnGhost(grid, cell, before.get(id), gridRect);
        if (cell.parentNode === grid) cell.remove();
      });

      const addCell = grid.querySelector('.ge-sorter-add-cell');
      const entering = [];
      desired.forEach((id, index) => {
        const slide = tenantSlidesData[index];
        let cell = existing.get(id) || null;
        if (cell) {
          sorterSyncCellContent(cell, slide, index);
        } else {
          cell = sorterBuildCell(grid, slide, index);
          entering.push(cell);
        }
        grid.insertBefore(cell, addCell || null);
      });
      sorterSyncCellIndexes(grid);

      entering.forEach(cell => {
        const canvas = cell.querySelector('.ge-thumb-canvas');
        const slide = tenantSlidesData[Number(cell.dataset.sorterIndex)];
        if (canvas && slide && typeof fillSlideThumbnailCanvas === 'function') {
          fillSlideThumbnailCanvas(canvas, slide);
        }
        if (!reduceMotion) sorterAnimateEnter(cell);
      });
      if (reduceMotion) return true;

      desired.forEach(id => {
        const cell = existing.get(id);
        const first = before.get(id);
        if (!cell || !first || !cell.isConnected) return;
        const rect = sorterLayoutRect(cell);
        // Rects are painted, transforms are layout: convert before animating.
        const zoom = typeof wfRootZoom === 'function' ? wfRootZoom() : 1;
        const dx = Math.round((first.left - rect.left) / zoom * 10) / 10;
        const dy = Math.round((first.top - rect.top) / zoom * 10) / 10;
        if (!dx && !dy) return;
        try {
          cell.animate(
            [{ transform: 'translate(' + dx + 'px, ' + dy + 'px)' }, { transform: 'translate(0, 0)' }],
            { duration: 200, easing: 'cubic-bezier(.2, .8, .2, 1)' }
          );
        } catch (error) { /* ignore */ }
      });
      return true;
    }

    let tenantSorterRendered = false;

    function renderTenantSlidesSorter() {
      if (tenantSorterSuppressRender) return;
      const box = document.getElementById('tenantSlidesSorter');
      if (!box) return;
      box.hidden = tenantSlidesView !== 'sorter';
      if (box.hidden) return;
      const liveGrid = box.querySelector('.ge-sorter-grid');
      if (tenantSorterRendered && liveGrid
        && liveGrid.querySelector('.ge-sorter-cell:not(.ge-sorter-add-cell)')
        && sorterReconcileGrid(liveGrid)) {
        return;
      }
      tenantSorterDragId = '';
      tenantSorterLastSlot = null;
      tenantSorterDragCardHeight = 0;
      tenantSorterPlaceholder = null;
      tenantSorterDropHandled = false;
      tenantSorterLastLeaveAt = 0;
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
      grid.ondragover = event => sorterHandleGridDragOver(grid, event);
      grid.ondragleave = () => { tenantSorterLastLeaveAt = Date.now(); };
      grid.ondrop = event => sorterHandleGridDrop(grid, event);

      tenantSlidesData.forEach((slide, index) => {
        const cell = sorterBuildCell(grid, slide, index);
        grid.appendChild(cell);
        const canvas = cell.querySelector('.ge-thumb-canvas');
        if (tenantSorterObserver && canvas) tenantSorterObserver.observe(canvas);
        else if (canvas && typeof fillSlideThumbnailCanvas === 'function') fillSlideThumbnailCanvas(canvas, slide);
      });

      const addCell = document.createElement('div');
      addCell.className = 'ge-sorter-cell ge-sorter-add-cell';
      const addButton = document.createElement('button');
      addButton.type = 'button';
      addButton.textContent = sorterText('ws.add_slide', 'إضافة شريحة');
      addButton.onclick = () => {
        if (typeof openSlideInsertMenu === 'function') openSlideInsertMenu(addButton, tenantSlidesData.length);
      };
      addCell.appendChild(addButton);
      grid.appendChild(addCell);

      box.appendChild(grid);
      tenantSorterRendered = true;
    }

    document.addEventListener('wf:lang', () => {
      try {
        if (tenantSlidesView === 'sorter') renderTenantSlidesSorter();
      } catch (error) { /* ignore */ }
    });
