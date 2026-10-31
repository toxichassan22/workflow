/* Manual authoring: on-brand slide structures, text/image/shape/table
   insertion, table tools, slide background and visibility. The deck is HTML,
   so every authored element is an ordinary stored element that survives save,
   renumbering and export. */

    /* AUTHORING_PURE_BEGIN */
    function authoringEscape(value) {
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function authoringBrandColors() {
      const branding = (typeof tenantBranding !== 'undefined' && tenantBranding) || {};
      const pick = (value, fallback) => /^#[0-9a-fA-F]{6}$/.test(String(value || '').trim())
        ? String(value).trim() : fallback;
      return {
        primary: pick(branding.primary_color, '#07182C'),
        accent: pick(branding.accent_color || branding.secondary_color, '#17C8E3'),
        text: '#1e293b',
        muted: '#64748b',
        line: '#e2e8f0',
        surface: '#ffffff'
      };
    }

    function slideTableMarkup(rows, cols, colors) {
      const c = colors || authoringBrandColors();
      const rowCount = Math.max(1, Math.min(20, Number(rows) || 4));
      const colCount = Math.max(1, Math.min(10, Number(cols) || 3));
      const cell = (tag, header) => '<' + tag + ' style="padding:10px 12px;border:1px solid ' + c.line
        + ';font-size:15px;text-align:right;vertical-align:top;'
        + (header ? 'font-weight:700;background:' + c.primary + ';color:#ffffff;'
          : 'font-weight:400;background:' + c.surface + ';color:' + c.text + ';') + '">&nbsp;</' + tag + '>';
      let html = '<table style="width:100%;border-collapse:collapse;table-layout:fixed;">';
      html += '<thead><tr>' + Array.from({ length: colCount }, () => cell('th', true)).join('') + '</tr></thead><tbody>';
      for (let row = 1; row < rowCount; row += 1) {
        html += '<tr>' + Array.from({ length: colCount }, () => cell('td', false)).join('') + '</tr>';
      }
      return html + '</tbody></table>';
    }

    function structuredSlideHtml(structure, title, colors) {
      const c = colors || authoringBrandColors();
      const name = authoringEscape(title || '');
      const header = '<div data-slide-header="1" style="position:absolute;top:34px;right:56px;left:56px;'
        + 'display:flex;align-items:center;justify-content:space-between;z-index:3;">'
        + '<img src="##LOGO##" alt="" style="height:48px;max-width:220px;object-fit:contain;">'
        + '<div style="font-size:13px;font-weight:700;letter-spacing:0.5px;color:' + c.muted + ';">'
        + name + '</div></div>';
      const footer = '<div data-slide-footer="1" style="position:absolute;bottom:22px;right:56px;left:56px;'
        + 'display:flex;align-items:center;justify-content:space-between;font-size:12px;color:' + c.muted + ';">'
        + '<div style="width:64px;height:3px;background:' + c.accent + ';border-radius:2px;"></div>'
        + '<div data-slide-counter="1" dir="ltr">00 — 00</div></div>';
      const heading = '<div data-slide-textbox="1" style="position:absolute;top:150px;right:110px;left:110px;'
        + 'min-height:70px;box-sizing:border-box;color:' + c.primary + ';font-size:52px;font-weight:800;'
        + 'line-height:1.25;text-align:right;">' + (name || 'عنوان الشريحة') + '</div>'
        + '<div style="position:absolute;top:238px;right:110px;width:96px;height:4px;background:'
        + c.accent + ';border-radius:2px;"></div>';
      const body = (top, text) => '<div data-slide-textbox="1" style="position:absolute;top:' + top
        + 'px;right:110px;left:110px;min-height:200px;box-sizing:border-box;color:' + c.text
        + ';font-size:24px;font-weight:400;line-height:1.7;text-align:right;">' + text + '</div>';
      let content = '';
      if (structure === 'title') {
        content = heading;
      } else if (structure === 'title_text') {
        content = heading + body(300, 'اكتب النص هنا');
      } else if (structure === 'text_image') {
        content = heading
          + '<div data-slide-textbox="1" style="position:absolute;top:300px;right:110px;width:520px;'
          + 'min-height:240px;box-sizing:border-box;color:' + c.text + ';font-size:24px;font-weight:400;'
          + 'line-height:1.7;text-align:right;">اكتب النص هنا</div>';
      } else if (structure === 'table') {
        content = heading
          + '<div data-slide-table="1" style="position:absolute;top:280px;right:90px;width:1100px;'
          + 'box-sizing:border-box;z-index:5;background:' + c.surface + ';">'
          + slideTableMarkup(4, 3, c) + '</div>';
      }
      return '<div class="slide" dir="rtl" data-manual-slide="1" style="width:1280px;height:720px;'
        + 'position:relative;overflow:hidden;box-sizing:border-box;background:' + c.surface + ';'
        + 'color:' + c.text + ';direction:rtl;">' + header + content + footer + '</div>';
    }

    /* Replaces match text inside text nodes only: attributes, tags and the
       contents of style/script blocks stay untouched. The count is what the
       deck tools menu reports back. */
    function deckReplaceInSlideHtml(html, find, replace) {
      const needle = String(find || '');
      if (!needle) return { html: String(html || ''), count: 0 };
      const protectedBlocks = [];
      let out = String(html || '').replace(/<(style|script)\b[\s\S]*?<\/\1>/gi, match => {
        protectedBlocks.push(match);
        return '\u0000' + (protectedBlocks.length - 1) + '\u0000';
      });
      let count = 0;
      out = out.replace(/>([^<]*)</g, (match, text) => {
        if (!text || text.indexOf(needle) === -1) return match;
        const parts = text.split(needle);
        count += parts.length - 1;
        return '>' + parts.join(String(replace == null ? '' : replace)) + '<';
      });
      out = out.replace(/\u0000(\d+)\u0000/g, (match, index) => protectedBlocks[Number(index)] || match);
      return { html: out, count };
    }
    /* AUTHORING_PURE_END */

    function slideStructureLabel(structure) {
      if (structure === 'blank') return slideToolbarText('ws.new_slide_title', 'شريحة جديدة');
      const key = 'ws.structure_' + structure;
      const labels = {
        blank: 'شريحة جديدة', title: 'عنوان', title_text: 'عنوان ونص',
        text_image: 'نص وصورة', table: 'جدول'
      };
      return slideToolbarText(key, labels[structure] || labels.blank);
    }

    function structuredSlideObject(structure, title) {
      const name = String(title || '').trim() || slideStructureLabel(structure);
      return {
        id: wfNewSlideId(),
        title: name,
        type: 'content',
        section_key: '',
        is_custom: true,
        manual: true,
        structure: structure || 'blank',
        html: structuredSlideHtml(structure || 'blank', name)
      };
    }

    let slideInsertMenuEl = null;

    function closeSlideInsertMenu() {
      if (!slideInsertMenuEl) return;
      if (slideInsertMenuEl._onDoc) {
        document.removeEventListener('pointerdown', slideInsertMenuEl._onDoc, true);
      }
      if (slideInsertMenuEl._onKey) {
        document.removeEventListener('keydown', slideInsertMenuEl._onKey, true);
      }
      slideInsertMenuEl.remove();
      slideInsertMenuEl = null;
    }

    function openSlideInsertMenu(anchor, index) {
      if (!hasPermission('create_presentation') || !anchor) return;
      closeSlideInsertMenu();
      const choices = [
        ['blank', slideToolbarText('ws.structure_blank', 'فارغة')],
        ['title', slideToolbarText('ws.structure_title', 'عنوان')],
        ['title_text', slideToolbarText('ws.structure_title_text', 'عنوان ونص')],
        ['text_image', slideToolbarText('ws.structure_text_image', 'نص وصورة')],
        ['table', slideToolbarText('ws.structure_table', 'جدول')]
      ];
      const menu = document.createElement('div');
      menu.className = 'slide-insert-menu';
      menu.innerHTML = '<div class="slide-insert-menu-title">'
        + escapeHtml(slideToolbarText('ws.add_slide', 'إضافة شريحة')) + '</div>'
        + choices.map(choice => '<button type="button" class="slide-insert-menu-item" data-structure="'
          + choice[0] + '">' + escapeHtml(choice[1]) + '</button>').join('');
      document.body.appendChild(menu);
      menu.querySelectorAll('[data-structure]').forEach(button => {
        button.addEventListener('click', event => {
          event.stopPropagation();
          const structure = button.getAttribute('data-structure');
          closeSlideInsertMenu();
          insertStructuredSlideAt(index, structure);
        });
      });
      const rect = anchor.getBoundingClientRect();
      const width = menu.offsetWidth || 190;
      const height = menu.offsetHeight || 220;
      const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
      const top = rect.bottom + height + 8 <= window.innerHeight
        ? rect.bottom + 6
        : Math.max(8, rect.top - height - 6);
      menu.style.position = 'fixed';
      menu.style.left = left + 'px';
      menu.style.top = top + 'px';
      menu.style.zIndex = '9998';
      const onDoc = event => {
        if (slideInsertMenuEl && !slideInsertMenuEl.contains(event.target)) closeSlideInsertMenu();
      };
      const onKey = event => {
        if (event.key === 'Escape') {
          event.preventDefault();
          closeSlideInsertMenu();
        }
      };
      menu._onDoc = onDoc;
      menu._onKey = onKey;
      setTimeout(() => {
        document.addEventListener('pointerdown', onDoc, true);
        document.addEventListener('keydown', onKey, true);
      }, 0);
      slideInsertMenuEl = menu;
    }

    function selectSlideElementBySelector(index, selector, delay) {
      setTimeout(() => {
        try {
          const stage = slideStageForIndex(index);
          const slide = stage ? stage.querySelector('.slide') : null;
          if (!stage || !slide) return;
          const matches = slide.querySelectorAll(selector);
          const target = matches[matches.length - 1];
          if (!target) return;
          const path = slideElementPath(slide, target);
          if (!path) return;
          selectSlideElement(stage, index, target, path);
        } catch (error) { /* the slide may have been replaced */ }
      }, Number(delay) || 340);
    }

    function insertStructuredSlideAt(index, structure) {
      if (!hasPermission('create_presentation')) return;
      const at = Math.max(0, Math.min(Number(index) || 0, tenantSlidesData.length));
      beginPresentationUndoChange();
      tenantSlidesData.splice(at, 0, structuredSlideObject(structure));
      renumberTenantSlides();
      renderTenantSlides();
      selectTenantSlide(at);
      markSlidesDeckChanged();
      if (typeof startSlideEditSession === 'function') startSlideEditSession(at);
      if (structure === 'table') selectSlideElementBySelector(at, '[data-slide-table]');
      if (structure === 'title_text' || structure === 'title') {
        selectSlideElementBySelector(at, '[data-slide-textbox]', 380);
      }
      if (structure === 'text_image') {
        setTimeout(() => {
          const session = getSlideEditSession(at);
          if (!session) return;
          session.pendingImageBox = 'position:absolute;top:250px;left:80px;width:480px;height:340px;box-sizing:border-box;z-index:5;';
          openSlideImagePicker(at);
        }, 420);
      }
      if (typeof tenantSlidesView !== 'undefined' && tenantSlidesView === 'sorter'
        && typeof renderTenantSlidesSorter === 'function') {
        setTimeout(() => renderTenantSlidesSorter(), 0);
      }
      if (typeof checkpointPresentationUndo === 'function') checkpointPresentationUndo();
      toast(WFT('ws.slide_added', 'أُضيفت شريحة جديدة'));
    }

    function insertSlideShape(index, kind) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html || !getSlideEditSession(index)) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      if (!rawRoot.style.position) rawRoot.style.position = 'relative';
      const colors = authoringBrandColors();
      pushSlideEditHistory(index);
      const shape = rawDoc.createElement('div');
      shape.setAttribute('data-slide-shape', kind || 'rectangle');
      const base = 'position:absolute;z-index:5;right:430px;';
      if (kind === 'circle') {
        shape.setAttribute('style', base + 'top:280px;width:200px;height:200px;border-radius:50%;'
          + 'background:' + colors.accent + ';');
      } else if (kind === 'line') {
        shape.setAttribute('style', base + 'top:380px;width:420px;height:4px;border-radius:2px;'
          + 'background:' + colors.accent + ';');
      } else {
        shape.setAttribute('style', base + 'top:290px;width:320px;height:180px;border-radius:14px;'
          + 'background:' + colors.primary + ';');
      }
      rawRoot.appendChild(shape);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      selectSlideElementBySelector(index, '[data-slide-shape]');
      toast(WFT('slide.shape_added', 'تمت إضافة الشكل'));
    }

    function insertSlideTable(index, rows, cols) {
      const slideData = tenantSlidesData[index];
      if (!slideData || !slideData.html || !getSlideEditSession(index)) return;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return;
      if (!rawRoot.style.position) rawRoot.style.position = 'relative';
      pushSlideEditHistory(index);
      const wrapper = rawDoc.createElement('div');
      wrapper.setAttribute('data-slide-table', '1');
      wrapper.setAttribute('style', 'position:absolute;top:250px;right:90px;width:1100px;'
        + 'box-sizing:border-box;z-index:5;background:#ffffff;');
      wrapper.innerHTML = slideTableMarkup(rows, cols, authoringBrandColors());
      rawRoot.appendChild(wrapper);
      slideData.html = rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSingleSlideCard(index);
      selectSlideElementBySelector(index, '[data-slide-table]');
      toast(WFT('slide.table_added', 'تمت إضافة الجدول'));
    }

    function insertSlideTableFromPanel(index, controls) {
      const rowsInput = controls ? controls.querySelector('[data-slide-table-rows]') : null;
      const colsInput = controls ? controls.querySelector('[data-slide-table-cols]') : null;
      insertSlideTable(index, rowsInput ? Number(rowsInput.value) : 4, colsInput ? Number(colsInput.value) : 3);
    }

    /* ── Table tools ────────────────────────────────────────────────────── */

    function slideTableContext(index) {
      const stage = canvasStageFor(index);
      const session = canvasSession(index);
      const slideData = tenantSlidesData[index];
      if (!stage || !session || !slideData || !slideData.html) return null;
      const slide = stage.querySelector('.slide');
      const pairs = slideSelectedTargets(stage, session);
      const primary = pairs[0] ? pairs[0].target : null;
      if (!slide || !primary) return null;
      const liveWrapper = primary.closest && primary.closest('[data-slide-table]');
      if (!liveWrapper) return null;
      const liveTable = liveWrapper.tagName === 'TABLE' ? liveWrapper : liveWrapper.querySelector('table');
      if (!liveTable) return null;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      const path = slideElementPath(slide, liveWrapper);
      const rawWrapper = rawRoot && path ? findSlideRawTarget(rawRoot, liveWrapper, path) : null;
      const rawTable = rawWrapper
        ? (rawWrapper.tagName === 'TABLE' ? rawWrapper : rawWrapper.querySelector('table'))
        : null;
      if (!rawRoot || !rawWrapper || !rawTable) return null;
      return { stage, session, slide, slideData, rawDoc, rawRoot, liveWrapper, rawWrapper, liveTable, rawTable };
    }

    function slideTableActiveCell(context) {
      const rows = Array.from(context.liveTable.rows || []);
      if (!rows.length) return null;
      const stored = context.session.tableCell || { row: 0, col: 0 };
      const row = Math.max(0, Math.min(Number(stored.row) || 0, rows.length - 1));
      const cells = Array.from(rows[row].cells || []);
      if (!cells.length) return null;
      const col = Math.max(0, Math.min(Number(stored.col) || 0, cells.length - 1));
      return { row, col };
    }

    function slideTableCellAt(table, row, col) {
      const rows = table ? Array.from(table.rows || []) : [];
      const line = rows[row];
      return line ? line.cells[col] || null : null;
    }

    function mutateSlideTableSelection(index, mutator) {
      const context = slideTableContext(index);
      if (!context) return false;
      pushSlideEditHistory(index);
      mutator(context.liveTable, context.rawTable, context);
      context.slideData.html = context.rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSlideThumbnail(index);
      syncSlideElementToolbar(index);
      refreshSlideEditToolbar(index);
      return true;
    }

    function mutateSlideTableCell(index, mutator) {
      return mutateSlideTableSelection(index, (liveTable, rawTable, context) => {
        const active = slideTableActiveCell(context);
        if (!active) return;
        const liveCell = slideTableCellAt(liveTable, active.row, active.col);
        const rawCell = slideTableCellAt(rawTable, active.row, active.col);
        if (liveCell && rawCell) mutator(liveCell, rawCell, context);
      });
    }

    function cloneSlideTableCell(cell, tagName) {
      const doc = cell.ownerDocument;
      const clone = doc.createElement(tagName || cell.tagName.toLowerCase());
      const keep = ['padding', 'borderTop', 'borderRight', 'borderBottom', 'borderLeft',
        'borderStyle', 'borderWidth', 'borderColor', 'fontSize', 'fontWeight', 'backgroundColor',
        'color', 'textAlign', 'verticalAlign'];
      keep.forEach(prop => { if (cell.style[prop]) clone.style[prop] = cell.style[prop]; });
      clone.innerHTML = '&nbsp;';
      return clone;
    }

    function addSlideTableRow(liveTable, rawTable, context, direction) {
      const active = slideTableActiveCell(context);
      if (!active) return;
      const liveRows = Array.from(liveTable.rows);
      const rawRows = Array.from(rawTable.rows);
      const liveSource = liveRows[active.row];
      const rawSource = rawRows[active.row];
      if (!liveSource || !rawSource) return;
      const build = source => {
        const row = source.ownerDocument.createElement('tr');
        const sourceIsHeader = !!(source.cells[0] && source.cells[0].tagName === 'TH');
        Array.from(source.cells).forEach(cell => {
          row.appendChild(cloneSlideTableCell(cell, 'td'));
        });
        // Adding a row below the header must not clone the header's dark fill
        // into what is a normal body row.
        if (sourceIsHeader) {
          Array.from(row.cells).forEach(cell => {
            cell.style.backgroundColor = '#ffffff';
            cell.style.color = '#1e293b';
            cell.style.fontWeight = '400';
          });
        }
        return row;
      };
      const liveRow = build(liveSource);
      const rawRow = build(rawSource);
      if (direction < 0) {
        liveSource.parentNode.insertBefore(liveRow, liveSource);
        rawSource.parentNode.insertBefore(rawRow, rawSource);
      } else {
        liveSource.parentNode.insertBefore(liveRow, liveSource.nextSibling);
        rawSource.parentNode.insertBefore(rawRow, rawSource.nextSibling);
      }
      context.session.tableCell = { row: active.row + (direction < 0 ? 0 : 1), col: active.col };
      toast(WFT('slide.table_row_added', 'تمت إضافة صف'));
    }

    function removeSlideTableRow(liveTable, rawTable, context) {
      const active = slideTableActiveCell(context);
      if (!active) return;
      const liveRows = Array.from(liveTable.rows);
      const rawRows = Array.from(rawTable.rows);
      if (liveRows.length <= 1) { toast(WFT('slide.table_keep_row', 'لا يمكن حذف آخر صف')); return; }
      liveRows[active.row].remove();
      rawRows[active.row].remove();
      context.session.tableCell = { row: Math.max(0, active.row - 1), col: active.col };
      toast(WFT('slide.table_row_removed', 'تم حذف الصف'));
    }

    function addSlideTableColumn(liveTable, rawTable, context, direction) {
      const active = slideTableActiveCell(context);
      if (!active) return;
      const insertAt = Math.max(0, Math.min(active.col + (direction < 0 ? 0 : 1), liveTable.rows[0].cells.length));
      const addToTable = table => {
        Array.from(table.rows).forEach(row => {
          const source = row.cells[Math.min(active.col, row.cells.length - 1)];
          if (!source) return;
          const clone = cloneSlideTableCell(source, source.tagName.toLowerCase() === 'th' ? 'th' : 'td');
          row.insertBefore(clone, row.cells[insertAt] || null);
        });
      };
      addToTable(liveTable);
      addToTable(rawTable);
      context.session.tableCell = { row: active.row, col: insertAt };
      toast(WFT('slide.table_col_added', 'تمت إضافة عمود'));
    }

    function removeSlideTableColumn(liveTable, rawTable, context) {
      const active = slideTableActiveCell(context);
      if (!active) return;
      if (liveTable.rows[0] && liveTable.rows[0].cells.length <= 1) {
        toast(WFT('slide.table_keep_col', 'لا يمكن حذف آخر عمود'));
        return;
      }
      const removeIn = table => {
        Array.from(table.rows).forEach(row => {
          if (row.cells[active.col]) row.cells[active.col].remove();
        });
      };
      removeIn(liveTable);
      removeIn(rawTable);
      context.session.tableCell = { row: active.row, col: Math.max(0, active.col - 1) };
      toast(WFT('slide.table_col_removed', 'تم حذف العمود'));
    }

    function replaceSlideTableCellTag(cell, tagName) {
      const replacement = cell.ownerDocument.createElement(tagName);
      Array.from(cell.attributes).forEach(attr => replacement.setAttribute(attr.name, attr.value));
      replacement.innerHTML = cell.innerHTML;
      cell.replaceWith(replacement);
      return replacement;
    }

    function toggleSlideTableHeader(liveTable, rawTable) {
      const toggle = table => {
        const firstRow = table.rows[0];
        if (!firstRow) return;
        Array.from(firstRow.cells).forEach(cell => {
          const isHeader = cell.tagName.toLowerCase() === 'th';
          replaceSlideTableCellTag(cell, isHeader ? 'td' : 'th');
        });
      };
      toggle(liveTable);
      toggle(rawTable);
      toast(WFT('slide.table_header_toggled', 'تم تبديل صف الرأس'));
    }

    function setSlideTableCellStyle(liveCell, rawCell, styles) {
      [liveCell, rawCell].forEach(cell => {
        Object.entries(styles).forEach(([prop, value]) => { cell.style[prop] = value; });
      });
    }

    function setSlideTableBorderStyle(liveTable, rawTable, options) {
      const sampleLive = liveTable.rows[0] ? liveTable.rows[0].cells[0] : null;
      const color = options.color
        || (sampleLive && (sampleLive.style.borderTopColor || window.getComputedStyle(sampleLive).borderTopColor))
        || '#e2e8f0';
      const width = options.width !== undefined
        ? Math.max(0, Number(options.width) || 0)
        : (sampleLive ? (parseFloat(sampleLive.style.borderTopWidth) || 1) : 1);
      const apply = table => {
        Array.from(table.rows).forEach(row => {
          Array.from(row.cells).forEach(cell => {
            cell.style.borderStyle = width > 0 ? 'solid' : 'none';
            cell.style.borderWidth = width + 'px';
            cell.style.borderColor = color;
          });
        });
      };
      apply(liveTable);
      apply(rawTable);
      toast(WFT('slide.table_border_updated', 'تم تحديث حدود الجدول'));
    }

    function runSlideTableAction(index, action) {
      if (action === 'rowadd') return mutateSlideTableSelection(index, (live, raw, ctx) => addSlideTableRow(live, raw, ctx, 1));
      if (action === 'rowdel') return mutateSlideTableSelection(index, (live, raw, ctx) => removeSlideTableRow(live, raw, ctx));
      if (action === 'coladd') return mutateSlideTableSelection(index, (live, raw, ctx) => addSlideTableColumn(live, raw, ctx, 1));
      if (action === 'coldel') return mutateSlideTableSelection(index, (live, raw, ctx) => removeSlideTableColumn(live, raw, ctx));
      if (action === 'header') return mutateSlideTableSelection(index, (live, raw) => toggleSlideTableHeader(live, raw));
    }

    function setSlideInspectorTableCellColor(index, value) {
      return mutateSlideTableCell(index, (live, raw) => setSlideTableCellStyle(live, raw, { backgroundColor: value }));
    }

    function setSlideInspectorTableBorderColor(index, value) {
      return mutateSlideTableSelection(index, (live, raw) => setSlideTableBorderStyle(live, raw, { color: value }));
    }

    function bindSlideTableEditing(stage, index) {
      const card = stage && (stage.closest('.ge-slide-card') || stage);
      if (!card || card.dataset.tableEditingBound === '1') return;
      card.dataset.tableEditingBound = '1';
      let lastCellTap = null;
      card.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        const session = getSlideEditSession(index);
        if (!session) return;
        const now = Date.now();
        if (lastCellTap && now - lastCellTap.at <= 500
          && Math.abs(event.clientX - lastCellTap.x) <= 10
          && Math.abs(event.clientY - lastCellTap.y) <= 10
          && lastCellTap.cell.isConnected) {
          // Selecting the table inserts controls above it. A native double-click
          // would land on those controls instead of the cell, so the second tap
          // on the same spot opens the cell recorded by the first one.
          event.preventDefault();
          event.stopPropagation();
          const cell = lastCellTap.cell;
          lastCellTap = null;
          beginSlideTableCellEdit(stage, index, cell);
          return;
        }
        const cell = event.target.closest
          ? event.target.closest('[data-slide-table] td, [data-slide-table] th') : null;
        if (!cell) { lastCellTap = null; return; }
        const row = cell.parentElement ? cell.parentElement.rowIndex : 0;
        session.tableCell = { row, col: cell.cellIndex };
        lastCellTap = { cell, at: now, x: event.clientX, y: event.clientY };
      }, true);
      card.addEventListener('dblclick', event => {
        const session = getSlideEditSession(index);
        let cell = event.target.closest
          ? event.target.closest('[data-slide-table] td, [data-slide-table] th') : null;
        if (!cell && session && session.tableCell) {
          const box = event.target.closest ? event.target.closest('[data-slide-table]') : null;
          const table = box && (box.tagName === 'TABLE' ? box : box.querySelector('table'));
          cell = table ? slideTableCellAt(table, session.tableCell.row, session.tableCell.col) : null;
        }
        if (!cell || !session) return;
        event.preventDefault();
        event.stopPropagation();
        beginSlideTableCellEdit(stage, index, cell);
      }, true);
    }

    function beginSlideTableCellEdit(stage, index, cell) {
      if (!cell || cell.dataset.tableEditing === '1' || !getSlideEditSession(index)) return;
      cell.dataset.tableEditing = '1';
      cell.setAttribute('contenteditable', 'plaintext-only');
      cell.setAttribute('spellcheck', 'false');
      const finish = () => {
        cell.removeAttribute('contenteditable');
        cell.removeAttribute('spellcheck');
        delete cell.dataset.tableEditing;
        commitSlideInlineEdit(stage, index, cell);
      };
      cell.addEventListener('blur', finish, { once: true });
      cell.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); cell.blur(); }
      });
      cell.focus({ preventScroll: true });
      try {
        const range = document.createRange();
        range.selectNodeContents(cell);
        const selection = window.getSelection();
        if (selection) { selection.removeAllRanges(); selection.addRange(range); }
      } catch (error) { /* focus still edits the cell */ }
    }

    /* ── Slide background and visibility ────────────────────────────────── */

    function slideRootPair(index) {
      const stage = slideStageForIndex(index);
      const slideData = tenantSlidesData[index];
      if (!stage || !slideData || !slideData.html) return null;
      const slide = stage.querySelector('.slide');
      if (!slide) return null;
      const rawDoc = new DOMParser().parseFromString(slideData.html, 'text/html');
      const rawRoot = rawDoc.querySelector('.slide');
      if (!rawRoot) return null;
      return { stage, slide, slideData, rawDoc, rawRoot };
    }

    function setSlideRootStyles(index, styles, message) {
      const pair = slideRootPair(index);
      const session = getSlideEditSession(index);
      if (!pair || !session) return false;
      pushSlideEditHistory(index);
      Object.entries(styles).forEach(([property, value]) => {
        pair.slide.style[property] = value;
        pair.rawRoot.style[property] = value;
      });
      pair.slideData.html = pair.rawRoot.outerHTML;
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      touchSlideEditSession(index);
      triggerAutoSaveDraft();
      refreshSlideThumbnail(index);
      syncSlideElementToolbar(index);
      if (message) toast(message);
      return true;
    }

    function setSlideBackgroundColor(index, color) {
      const hex = typeof normalizeHexColor === 'function' ? normalizeHexColor(color) : String(color || '');
      if (!hex) return;
      setSlideRootStyles(index, { backgroundColor: hex }, WFT('slide.background_set', 'تم تحديث خلفية الشريحة'));
    }

    function clearSlideBackground(index) {
      setSlideRootStyles(index, {
        backgroundImage: '', backgroundSize: '', backgroundPosition: '', backgroundRepeat: ''
      }, WFT('slide.background_removed', 'أُزيلت خلفية الشريحة'));
    }

    function openSlideBackgroundPicker(index) {
      if (!getSlideEditSession(index)) return;
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.style.display = 'none';
      input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        input.value = '';
        if (!file) return;
        if (!String(file.type || '').startsWith('image/') || file.size > 4 * 1024 * 1024) {
          toast(WFT('slide.image_required', 'الملف المختار ليس صورة'));
          return;
        }
        showLoader(WFT('slide.image_uploading', 'رفع الصورة'), WFT('slide.image_uploading_hint', 'يتم حفظ الصورة في ملفات المشروع...'));
        let url = '';
        try {
          url = await uploadSlideImageFile(file);
        } catch (error) {
          hideLoader();
          toast(error && error.message ? error.message : WFT('slide.image_upload_failed', 'تعذر رفع الصورة'));
          return;
        }
        hideLoader();
        const safeUrl = String(url || '').replace(/"/g, '%22');
        setSlideRootStyles(index, {
          backgroundImage: 'url("' + safeUrl + '")',
          backgroundSize: 'cover',
          backgroundPosition: 'center center',
          backgroundRepeat: 'no-repeat'
        }, WFT('slide.background_set', 'تم تحديث خلفية الشريحة'));
        input.remove();
      });
      document.body.appendChild(input);
      input.click();
    }

    function toggleSlideHidden(index) {
      const slide = tenantSlidesData[index];
      if (!slide) return;
      beginPresentationUndoChange();
      slide.hidden = !slide.hidden;
      markSlidesDeckChanged();
      renderTenantSlidesSidebar();
      refreshSlideEditToolbar(index);
      if (typeof checkpointPresentationUndo === 'function') checkpointPresentationUndo();
      toast(slide.hidden
        ? WFT('slide.hidden', 'تم إخفاء الشريحة')
        : WFT('slide.shown', 'تم إظهار الشريحة'));
    }

    /* Manual slides are the client's own work: a full AI regeneration keeps
       them and puts each one back at its original position. */
    function preserveManualSlidesForRegeneration() {
      return (tenantSlidesData || []).map((slide, index) => ({ slide, index }))
        .filter(entry => entry.slide && entry.slide.manual);
    }

    function restoreManualSlidesAfterRegeneration(preserved, options) {
      const items = (preserved || []).filter(entry => entry && entry.slide && entry.slide.manual);
      if (!items.length) return 0;
      const atEnd = !!(options && options.atEnd);
      items.slice().sort((a, b) => a.index - b.index).forEach(entry => {
        // A failed run keeps them at the end: the generated prefix stays dense
        // at 0..n-1, so resuming the checkpoint can never overwrite them.
        const at = atEnd ? tenantSlidesData.length
          : Math.max(0, Math.min(entry.index, tenantSlidesData.length));
        tenantSlidesData.splice(at, 0, entry.slide);
      });
      renumberTenantSlides();
      renderTenantSlides();
      renderTenantSlidesSidebar(true);
      markSlidesDeckChanged();
      return items.length;
    }
