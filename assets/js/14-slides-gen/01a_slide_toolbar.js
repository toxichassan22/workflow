/* Slide edit toolbar: the session rail and the tools of the selected element.
   Moved out of 01_undo.js so the undo history and the toolbar stay focused.
   The bar shows only what the selection needs: no selection -> slide tools and
   inserting, a text element -> text tools, a table -> table tools. */

    let slideEditToolbarTab = 'add';

    function slideToolbarText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function slideToolbarButton(label, act, disabled, extra) {
      return '<button type="button" data-slide-edit-act="' + act + '"'
        + (disabled ? ' disabled' : '') + (extra ? ' ' + extra : '') + '>' + label + '</button>';
    }

    function slideEditToolbarAvailableTabs(selectionKind) {
      if (!selectionKind) return ['add', 'slide'];
      if (selectionKind === 'text') return ['text', 'colors', 'common'];
      if (selectionKind === 'image') return ['image', 'common'];
      if (selectionKind === 'shape') return ['shape', 'colors', 'common'];
      if (selectionKind === 'table') return ['table', 'common'];
      return ['common'];
    }

    function slideEditToolbarTabForKind(selectionKind) {
      const available = slideEditToolbarAvailableTabs(selectionKind);
      if (available.includes(slideEditToolbarTab)) return slideEditToolbarTab;
      if (selectionKind) return selectionKind;
      return 'add';
    }

    function setSlideEditToolbarTab(index, tab) {
      slideEditToolbarTab = tab;
      refreshSlideEditToolbar(index);
    }

    function slideEditToolbarTabLabels() {
      return {
        add: ['tb.add', 'إضافة'],
        slide: ['tb.slide', 'الشريحة'],
        common: ['tb.common', 'مشترك'],
        text: ['tb.text', 'النص'],
        image: ['tb.image', 'الصورة'],
        shape: ['tb.shape', 'الشكل'],
        table: ['tb.table', 'جدول'],
        colors: ['tb.colors', 'الألوان']
      };
    }

    function slideEditToolbarPanels(index, dis) {
      const slide = tenantSlidesData[index] || {};
      const slideHidden = !!slide.hidden;
      const watermarkChecked = isWatermarkVisible(slide.html) ? ' checked' : '';
      return {
        add: '<div class="slide-edit-tab-panel" data-slide-edit-panel="add">'
          + slideToolbarButton(slideToolbarText('tb.add_text', 'إضافة نص'), 'addtext')
          + slideToolbarButton(slideToolbarText('tb.add_image', 'إضافة صورة'), 'addimage')
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('tb.rectangle', 'مستطيل'), 'addshape', false, 'data-slide-shape-kind="rectangle"')
          + slideToolbarButton(slideToolbarText('tb.circle', 'دائرة'), 'addshape', false, 'data-slide-shape-kind="circle"')
          + slideToolbarButton(slideToolbarText('tb.line', 'خط'), 'addshape', false, 'data-slide-shape-kind="line"')
          + '<span class="slide-edit-tab-sep"></span>'
          + '<label class="slide-edit-num-field">' + slideToolbarText('tb.rows', 'صفوف')
          + '<input type="number" min="1" max="20" value="4" data-slide-table-rows></label>'
          + '<label class="slide-edit-num-field">' + slideToolbarText('tb.cols', 'أعمدة')
          + '<input type="number" min="1" max="10" value="3" data-slide-table-cols></label>'
          + slideToolbarButton(slideToolbarText('tb.table_insert', 'إضافة جدول'), 'addtable')
          + '</div>',
        slide: '<div class="slide-edit-tab-panel" data-slide-edit-panel="slide">'
          + '<label class="slide-edit-color">' + slideToolbarText('tb.background_color', 'خلفية الشريحة')
          + '<input type="color" data-slide-edit-slide-bg value="#ffffff"></label>'
          + slideToolbarButton(slideToolbarText('tb.background_image', 'خلفية صورة'), 'slidebgimage')
          + slideToolbarButton(slideToolbarText('tb.clear_background', 'مسح الخلفية'), 'slidebgclear')
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText(slideHidden ? 'tb.show_slide' : 'tb.hide_slide',
            slideHidden ? 'إظهار الشريحة' : 'إخفاء الشريحة'), 'hideslide')
          + slideToolbarButton(slideToolbarText('tb.notes', 'ملاحظات'), 'slidenotes')
          + '<label class="slide-edit-watermark">'
          + '<input type="checkbox" data-slide-edit-watermark="toggle"' + watermarkChecked + '>'
          + slideToolbarText('ca.watermark_show', 'إظهار العلامة المائية')
          + '</label></div>',
        common: '<div class="slide-edit-tab-panel" data-slide-edit-panel="common">'
          + slideToolbarButton(slideToolbarText('ca.front', 'أمام'), 'front', dis)
          + slideToolbarButton(slideToolbarText('ca.back', 'خلف'), 'back', dis)
          + slideToolbarButton(slideToolbarText('ca.duplicate_element', 'تكرار'), 'dup', dis)
          + slideToolbarButton(slideToolbarText('ca.delete_element', 'حذف العنصر'), 'del', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + '<input type="range" min="5" max="100" step="5" value="100" data-slide-edit-opacity="range"'
          + dis + ' style="width:110px" aria-label="' + slideToolbarText('ca.opacity', 'الشفافية') + '">'
          + '<span data-slide-edit-opacity-readout class="slide-edit-tab-readout">100%</span>'
          + '</div>',
        text: '<div class="slide-edit-tab-panel" data-slide-edit-panel="text">'
          + slideToolbarButton(slideToolbarText('ca.font_smaller', 'تصغير'), 'fontdown', dis)
          + slideToolbarButton(slideToolbarText('ca.font_larger', 'تكبير'), 'fontup', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('ca.bold', 'عريض'), 'bold', dis)
          + slideToolbarButton(slideToolbarText('ca.italic', 'مائل'), 'italic', dis)
          + slideToolbarButton(slideToolbarText('ca.underline', 'تحته خط'), 'underline', dis)
          + slideToolbarButton(slideToolbarText('ca.strike', 'مشطوب'), 'strike', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('ca.align_right', 'يمين'), 'alignright', dis)
          + slideToolbarButton(slideToolbarText('ca.align_center', 'وسط'), 'aligncenter', dis)
          + slideToolbarButton(slideToolbarText('ca.align_left', 'يسار'), 'alignleft', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('ca.bullets', 'بوليته'), 'bullets', dis)
          + slideToolbarButton(slideToolbarText('ca.numbers', 'ترقيم'), 'numbers', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('ca.line_up', 'تباعد أوسع'), 'lineup', dis)
          + slideToolbarButton(slideToolbarText('ca.line_down', 'تباعد أضيق'), 'linedown', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('ca.clear_format', 'مسح التنسيق'), 'cleartext', dis)
          + slideToolbarButton(slideToolbarText('ca.fit_text', 'ضبط النص'), 'fittext', dis)
          + '</div>',
        colors: '<div class="slide-edit-tab-panel" data-slide-edit-panel="colors">'
          + '<label class="slide-edit-color">' + slideToolbarText('ca.text_color', 'لون النص')
          + '<input type="color" data-slide-edit-color="color" value="#1e293b"' + dis + '></label>'
          + '<span class="slide-edit-tab-sep"></span>'
          + '<label class="slide-edit-color">' + slideToolbarText('ca.highlight', 'تظليل')
          + '<input type="color" data-slide-edit-color="highlight" value="#fff59d"' + dis + '></label>'
          + '</div>',
        image: '<div class="slide-edit-tab-panel" data-slide-edit-panel="image">'
          + slideToolbarButton(slideToolbarText('ca.cover', 'ملء'), 'fitcover', dis)
          + slideToolbarButton(slideToolbarText('ca.contain', 'احتواء'), 'fitcontain', dis)
          + slideToolbarButton(slideToolbarText('ca.replace_image', 'استبدال'), 'replaceimg', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('ca.crop', 'قص'), 'crop', dis)
          + slideToolbarButton(slideToolbarText('ca.shadow', 'ظل'), 'shadow', dis)
          + '</div>',
        shape: '<div class="slide-edit-tab-panel" data-slide-edit-panel="shape">'
          + '<label class="slide-edit-color">' + slideToolbarText('ca.fill', 'التعبئة')
          + '<input type="color" data-slide-edit-color="background" value="#ffffff"' + dis + '></label>'
          + '<label class="slide-edit-color">' + slideToolbarText('ca.border_color', 'الحدود')
          + '<input type="color" data-slide-edit-color="border" value="#dbe3ea"' + dis + '></label>'
          + '<label class="slide-edit-num-field">' + slideToolbarText('ca.border_width', 'سماكة الحدود')
          + '<input type="number" min="0" max="20" value="0" data-slide-edit-border-width' + dis + '></label>'
          + '<label class="slide-edit-num-field">' + slideToolbarText('ca.radius', 'الزوايا')
          + '<input type="number" min="0" max="200" value="0" data-slide-edit-radius' + dis + '></label>'
          + slideToolbarButton(slideToolbarText('ca.shadow', 'ظل'), 'shadow', dis)
          + '</div>',
        table: '<div class="slide-edit-tab-panel" data-slide-edit-panel="table">'
          + slideToolbarButton(slideToolbarText('ca.add_row', 'صف جديد'), 'tablerowadd', dis)
          + slideToolbarButton(slideToolbarText('ca.del_row', 'حذف صف'), 'tablerowdel', dis)
          + slideToolbarButton(slideToolbarText('ca.add_col', 'عمود جديد'), 'tablecoladd', dis)
          + slideToolbarButton(slideToolbarText('ca.del_col', 'حذف عمود'), 'tablecoldel', dis)
          + slideToolbarButton(slideToolbarText('ca.header_row', 'صف رأس'), 'tableheader', dis)
          + '<span class="slide-edit-tab-sep"></span>'
          + '<label class="slide-edit-color">' + slideToolbarText('ca.cell_fill', 'لون الخلية')
          + '<input type="color" data-slide-table-cell-color value="#ffffff"' + dis + '></label>'
          + '<label class="slide-edit-color">' + slideToolbarText('ca.table_border', 'حدود الجدول')
          + '<input type="color" data-slide-table-border-color value="#dbe3ea"' + dis + '></label>'
          + '<label class="slide-edit-num-field">' + slideToolbarText('ca.border_width', 'سماكة الحدود')
          + '<input type="number" min="0" max="10" value="1" data-slide-table-border-width' + dis + '></label>'
          + '<span class="slide-edit-tab-sep"></span>'
          + slideToolbarButton(slideToolbarText('ca.align_right', 'يمين'), 'tablealignright', dis)
          + slideToolbarButton(slideToolbarText('ca.align_center', 'وسط'), 'tablealigncenter', dis)
          + slideToolbarButton(slideToolbarText('ca.align_left', 'يسار'), 'tablealignleft', dis)
          + '</div>'
      };
    }

    function slideEditToolbarHTML(index) {
      const session = getSlideEditSession(index);
      if (!session) {
        return '<button type="button" data-slide-edit-act="edit"'
          + ' aria-label="' + slideToolbarText('ca.start_editing', 'تعديل الشريحة: تعديل النص وتحريك العناصر') + '">'
          + slideToolbarText('ca.edit', 'تعديل') + '</button>';
      }
      const canUndo = session.undo.length > 0;
      const canRedo = session.redo.length > 0;
      const hasSel = !!session.sel;
      const dis = hasSel ? '' : ' disabled';
      const selectionKind = (typeof slideToolbarSelectionKind === 'function')
        ? slideToolbarSelectionKind(index) : '';
      const tabs = slideEditToolbarAvailableTabs(selectionKind);
      const activeTab = tabs.includes(slideEditToolbarTab)
        ? slideEditToolbarTab : slideEditToolbarTabForKind(selectionKind);
      slideEditToolbarTab = activeTab;
      // The session is the constant: approve/cancel and its history stay on
      // every tab, and the tab strip only swaps the tools below them.
      const sessionRail = '<div class="slide-edit-session-rail">'
        + '<div class="slide-edit-session-actions">'
        + '<button type="button" class="active" data-slide-edit-act="commit">' + slideToolbarText('ca.approve', 'اعتماد') + '</button>'
        + '<button type="button" data-slide-edit-act="cancel">' + slideToolbarText('ca.cancel', 'الغاء') + '</button>'
        + '</div>'
        + '<div class="slide-edit-session-actions">'
        + '<button type="button" data-slide-edit-act="undo"' + (canUndo ? '' : ' disabled') + '>' + slideToolbarText('ca.undo', 'تراجع') + '</button>'
        + '<button type="button" data-slide-edit-act="redo"' + (canRedo ? '' : ' disabled') + '>' + slideToolbarText('ca.redo', 'تقدم') + '</button>'
        + '</div></div>';
      const labels = slideEditToolbarTabLabels();
      const tabbar = '<div class="slide-edit-tabbar">' + tabs.map(tab => {
        const label = labels[tab] || [tab, tab];
        return '<button type="button" class="slide-edit-tab' + (tab === activeTab ? ' is-active' : '')
          + '" data-slide-edit-tab="' + tab + '">' + slideToolbarText(label[0], label[1]) + '</button>';
      }).join('') + '</div>';
      const panels = slideEditToolbarPanels(index, dis);
      return sessionRail + tabbar + (panels[activeTab] || panels.common);
    }

    function wireSlideEditControls(editControls, index) {
      editControls.querySelectorAll('[data-slide-edit-tab]').forEach(btn => {
        btn.addEventListener('click', event => {
          event.stopPropagation();
          setSlideEditToolbarTab(index, btn.getAttribute('data-slide-edit-tab'));
        });
      });
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
          else if (act === 'addshape' && typeof insertSlideShape === 'function') {
            insertSlideShape(index, btn.getAttribute('data-slide-shape-kind') || 'rectangle');
          } else if (act === 'addtable' && typeof insertSlideTableFromPanel === 'function') {
            insertSlideTableFromPanel(index, editControls);
          } else if (act === 'fontup') adjustSlideElementFontSize(index, 2);
          else if (act === 'fontdown') adjustSlideElementFontSize(index, -2);
          else if (act === 'bold') toggleSlideElementBold(index);
          else if (act === 'italic' && typeof toggleSlideSelectionTextStyle === 'function') toggleSlideSelectionTextStyle(index, 'italic');
          else if (act === 'underline' && typeof toggleSlideSelectionTextStyle === 'function') toggleSlideSelectionTextStyle(index, 'underline');
          else if (act === 'strike' && typeof toggleSlideSelectionTextStyle === 'function') toggleSlideSelectionTextStyle(index, 'strike');
          else if (act === 'bullets' && typeof toggleSlideSelectionList === 'function') toggleSlideSelectionList(index, 'bullet');
          else if (act === 'numbers' && typeof toggleSlideSelectionList === 'function') toggleSlideSelectionList(index, 'number');
          else if (act === 'lineup' && typeof adjustSlideSelectionLineHeight === 'function') adjustSlideSelectionLineHeight(index, 0.1);
          else if (act === 'linedown' && typeof adjustSlideSelectionLineHeight === 'function') adjustSlideSelectionLineHeight(index, -0.1);
          else if (act === 'cleartext' && typeof clearSlideSelectionFormatting === 'function') clearSlideSelectionFormatting(index);
          else if (act === 'fittext' && typeof fitSlideSelectionText === 'function') fitSlideSelectionText(index);
          else if (act === 'del') deleteSelectedSlideElement(index);
          else if (act === 'front') adjustSlideElementLayer(index, 1);
          else if (act === 'back') adjustSlideElementLayer(index, -1);
          else if (act === 'dup' && typeof duplicateSelectedSlideElements === 'function') duplicateSelectedSlideElements(index);
          else if (act === 'alignright' && typeof setSlideSelectionTextAlign === 'function') setSlideSelectionTextAlign(index, 'right');
          else if (act === 'aligncenter' && typeof setSlideSelectionTextAlign === 'function') setSlideSelectionTextAlign(index, 'center');
          else if (act === 'alignleft' && typeof setSlideSelectionTextAlign === 'function') setSlideSelectionTextAlign(index, 'left');
          else if (act === 'fitcover' && typeof setSlideSelectionImageFit === 'function') setSlideSelectionImageFit(index, 'cover');
          else if (act === 'fitcontain' && typeof setSlideSelectionImageFit === 'function') setSlideSelectionImageFit(index, 'contain');
          else if (act === 'replaceimg') openSlideImagePicker(index);
          else if (act === 'crop' && typeof toggleSlideImageCrop === 'function') toggleSlideImageCrop(index);
          else if (act === 'shadow' && typeof toggleSlideSelectionShadow === 'function') toggleSlideSelectionShadow(index);
          else if (act === 'hideslide' && typeof toggleSlideHidden === 'function') toggleSlideHidden(index);
          else if (act === 'slidenotes' && typeof openTenantSlideNotesEditor === 'function') openTenantSlideNotesEditor(index);
          else if (act === 'slidenotes' && typeof editTenantSlideNotes === 'function') editTenantSlideNotes(index);
          else if (act === 'slidebgimage' && typeof openSlideBackgroundPicker === 'function') openSlideBackgroundPicker(index);
          else if (act === 'slidebgclear' && typeof clearSlideBackground === 'function') clearSlideBackground(index);
          else if (act === 'tablerowadd' && typeof mutateSlideTableSelection === 'function') mutateSlideTableSelection(index, (live, raw, ctx) => addSlideTableRow(live, raw, ctx, 1));
          else if (act === 'tablerowdel' && typeof mutateSlideTableSelection === 'function') mutateSlideTableSelection(index, (live, raw, ctx) => removeSlideTableRow(live, raw, ctx));
          else if (act === 'tablecoladd' && typeof mutateSlideTableSelection === 'function') mutateSlideTableSelection(index, (live, raw, ctx) => addSlideTableColumn(live, raw, ctx, 1));
          else if (act === 'tablecoldel' && typeof mutateSlideTableSelection === 'function') mutateSlideTableSelection(index, (live, raw, ctx) => removeSlideTableColumn(live, raw, ctx));
          else if (act === 'tableheader' && typeof mutateSlideTableSelection === 'function') mutateSlideTableSelection(index, (live, raw) => toggleSlideTableHeader(live, raw));
          else if (act === 'tablealignright' && typeof mutateSlideTableCell === 'function') mutateSlideTableCell(index, (live, raw) => setSlideTableCellStyle(live, raw, { textAlign: 'right' }));
          else if (act === 'tablealigncenter' && typeof mutateSlideTableCell === 'function') mutateSlideTableCell(index, (live, raw) => setSlideTableCellStyle(live, raw, { textAlign: 'center' }));
          else if (act === 'tablealignleft' && typeof mutateSlideTableCell === 'function') mutateSlideTableCell(index, (live, raw) => setSlideTableCellStyle(live, raw, { textAlign: 'left' }));
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
          previewSlideElementColor(index, inp.getAttribute('data-slide-edit-color'), inp.value);
        });
        inp.addEventListener('change', e => {
          e.stopPropagation();
          commitSlideElementColor(index, inp.getAttribute('data-slide-edit-color'), inp.value);
        });
      });
      editControls.querySelectorAll('[data-slide-edit-slide-bg]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('change', e => {
          e.stopPropagation();
          if (typeof setSlideBackgroundColor === 'function') setSlideBackgroundColor(index, inp.value);
        });
      });
      editControls.querySelectorAll('[data-slide-edit-border-width]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('change', e => {
          e.stopPropagation();
          if (typeof setSlideSelectionBorderWidth === 'function') setSlideSelectionBorderWidth(index, Number(inp.value));
        });
      });
      editControls.querySelectorAll('[data-slide-edit-radius]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('change', e => {
          e.stopPropagation();
          if (typeof setSlideSelectionBorderRadius === 'function') setSlideSelectionBorderRadius(index, Number(inp.value));
        });
      });
      editControls.querySelectorAll('[data-slide-table-cell-color]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('change', e => {
          e.stopPropagation();
          if (typeof mutateSlideTableCell === 'function') mutateSlideTableCell(index, (live, raw) => setSlideTableCellStyle(live, raw, { backgroundColor: inp.value }));
        });
      });
      editControls.querySelectorAll('[data-slide-table-border-color]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('change', e => {
          e.stopPropagation();
          if (typeof mutateSlideTableSelection === 'function') mutateSlideTableSelection(index, (live, raw) => setSlideTableBorderStyle(live, raw, { color: inp.value }));
        });
      });
      editControls.querySelectorAll('[data-slide-table-border-width]').forEach(inp => {
        inp.addEventListener('click', e => e.stopPropagation());
        inp.addEventListener('pointerdown', e => e.stopPropagation());
        inp.addEventListener('change', e => {
          e.stopPropagation();
          if (typeof mutateSlideTableSelection === 'function') mutateSlideTableSelection(index, (live, raw) => setSlideTableBorderStyle(live, raw, { width: Number(inp.value) }));
        });
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
