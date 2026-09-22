    async function loadAllSectionVersions() {
      if (!tenantProjectData || !tenantProjectData.draftId) return;
      if (sectionVersionsLoading) return;
      sectionVersionsLoading = true;
      try {
        const result = await api('GET', '/api/project-draft/section-versions?draftId=' + encodeURIComponent(tenantProjectData.draftId));
        if (!result || !result.success) return;
        const grouped = {};
        (result.versions || []).forEach(version => {
          const key = version.section_key;
          if (!grouped[key]) grouped[key] = [];
          grouped[key].push(version);
        });
        Object.keys(grouped).forEach(key => { sectionVersionCache[key] = grouped[key]; });
        document.querySelectorAll('#tenantProjectForm .tenant-form-section[data-section]').forEach(section => {
          const key = section.dataset.section;
          if (!key || section.dataset.underConstruction === '1') return;
          if (!sectionVersionCache[key]) sectionVersionCache[key] = [];
          renderSectionVersionBlock(key);
        });
      } finally {
        sectionVersionsLoading = false;
      }
    }

    function refreshAllSectionVersionLines() {
      if (!tenantProjectData || !tenantProjectData.draftId) return;
      document.querySelectorAll('#tenantProjectForm .tenant-form-section[data-section]').forEach(section => {
        const key = section.dataset.section;
        if (!key || section.dataset.underConstruction === '1') return;
        attachSectionVersionBlock(key);
      });
      void loadAllSectionVersions();
    }

    function toggleSectionVersions(sectionKey) {
      openSectionVersionsPage(sectionKey);
    }

    async function sendSectionVersion(sectionKey) {
      const btn = document.getElementById('section-send-' + sectionKey);
      if (btn) btn.disabled = true;
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        // The snapshot freezes the stored draft, and autosave only marks the
        // form dirty — flush pending edits first or the send validates stale
        // data and fails on required fields that are filled on screen.
        if (tenantDraftDirty || !tenantProjectData.draftId) {
          const saved = await saveProjectAsDraft(true);
          if (!saved) {
            hideLoader();
            toast(WFT('sectionver.send_save_failed', 'تعذر حفظ المسودة قبل الإرسال'));
            return;
          }
        }
        const result = await api('POST', '/api/project-draft/section-version', { draftId: tenantProjectData.draftId, sectionKey: sectionKey });
        hideLoader();
        if (!result || !result.success) {
          if (result && result.error_code === 'SECTION_VERSION_INCOMPLETE') {
            const missing = Array.isArray(result.missing) ? result.missing.join('، ') : '';
            toast(WFT('sectionver.incomplete', 'حقول إلزامية ناقصة') + (missing ? ': ' + missing : ''));
          } else {
            toast((result && result.error) || WFT('sectionver.send_failed', 'تعذر إرسال القسم للاعتماد'));
          }
          return;
        }
        toast(WFT('sectionver.send_done', 'تم إرسال القسم للاعتماد'));
        openSectionVersionsPage(sectionKey);
        await loadAllSectionVersions();
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function decideSectionVersion(versionId, sectionKey, decision) {
      let note = null;
      if (decision === 'returned' || decision === 'rejected') {
        note = prompt(WFT('sectionver.note_prompt', 'سبب الإعادة'));
        if (!note || !String(note).trim()) { toast(WFT('sectionver.note_required', 'سبب الإعادة مطلوب')); return; }
      }
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        const result = await api('POST', '/api/project-draft/section-version/decision', { versionId: versionId, decision: decision, note: note });
        hideLoader();
        if (!result || !result.success) { toast((result && result.error) || WFT('sectionver.decide_failed', 'تعذر تسجيل القرار')); return; }
        applySectionStatuses({ [sectionKey]: decision === 'approved' ? 'approved' : 'draft' });
        toast(WFT('sectionver.decide_done', 'تم تسجيل القرار'));
        await loadAllSectionVersions();
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    async function cancelSectionVersion(versionId, sectionKey) {
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        const result = await api('POST', '/api/project-draft/section-version/cancel', { versionId: versionId });
        hideLoader();
        if (!result || !result.success) { toast((result && result.error) || WFT('sectionver.cancel_failed', 'تعذر إلغاء طلب الاعتماد')); return; }
        toast(WFT('sectionver.cancel_done', 'تم إلغاء طلب الاعتماد'));
        await loadAllSectionVersions();
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    async function restoreSectionVersion(versionId, sectionKey) {
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        const result = await api('POST', '/api/project-draft/section-version/restore', { versionId: versionId });
        hideLoader();
        if (!result || !result.success) { toast((result && result.error) || WFT('sectionver.restore_failed', 'تعذر الاستعادة')); return; }
        if (result.revision !== undefined) tenantDraftRevision = Number(result.revision) || tenantDraftRevision;
        toast(WFT('sectionver.restore_done', 'تمت الاستعادة كإصدار جديد'));
        openSectionVersionsPage(sectionKey);
        await loadAllSectionVersions();
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    // ── Section version comparison (t13): what changed between two snapshots ──
    // The approver opens the differences of a sent version against its
    // predecessor (or an explicit one) before deciding. One cached diff per
    // section stays visible until it is closed or another version is compared.
    const sectionVersionDiffCache = {};

    // Blob values (objects/arrays) never render as raw JSON in the preview —
    // they are laid out as labelled key/value rows, and a uniform array of flat
    // objects becomes a real table. Telemetry keys (diagnostics, confidence
    // maps, per-document processing) are processing metadata, not land data, so
    // they stay out of the view.
    const DIFF_BLOB_SKIP_KEYS = new Set(['extraction_diagnostics', 'document_processing', 'confidence']);

    const DIFF_BLOB_KEY_LABELS = {
      parcel_id: 'القطعة', plot_number: 'رقم القطعة', plan_number: 'رقم المخطط',
      subdivision_number: 'البلك', deed_number: 'رقم الصك', deed_date: 'تاريخ الصك',
      area_sqm: 'المساحة (م²)', zoning_code: 'كود التنظيم', allowed_uses: 'الاستخدامات',
      allowed_uses_restrictions: 'قيود الاستخدامات', building_ratio: 'نسبة البناء',
      building_ratio_coverage: 'نسب البناء والتغطية', building_ratio_setbacks: 'نسب البناء والارتدادات',
      coverage_ratio: 'نسبة التغطية', floor_area_ratio: 'معامل مسطح البناء (FAR)',
      max_floors_height: 'الأدوار والارتفاع', table_floors: 'الأدوار بموجب الجدول',
      setbacks: 'الارتدادات', facades_count: 'عدد الواجهات', facades_directions: 'اتجاهات الواجهات',
      north_direction: 'اتجاه الشمال', summary: 'الملخص',
      north: 'شمال', south: 'جنوب', east: 'شرق', west: 'غرب',
      point: 'النقطة', eastings: 'شرقيات', northings: 'شماليات',
      boundary_length_m: 'طول الحد (م)', street_name: 'اسم الشارع', street_width_m: 'عرض الشارع (م)',
      uses: 'الحد/الاستخدام', setback: 'الارتداد', lat: 'خط العرض', lng: 'خط الطول',
      directions: 'الاتجاهات', coordinates: 'الإحداثية', survey_coordinates: 'إحداثيات المساحة',
      regulation_coordinates: 'إحداثيات التنظيم', coordinate_tables: 'جداول الإحداثيات',
      coordinates_table_name: 'جدول الإحداثيات', coordinates_table_source_page: 'صفحة جدول الإحداثيات',
      regulation_text: 'النص التنظيمي', table_name: 'الجدول', rows: 'الصفوف',
      parcels: 'القطع', conflicts: 'التعارضات', sources: 'المصادر', source: 'المصدر',
      source_priority: 'أولوية المصادر', land_use_status: 'حالة الاستخدام',
      parking_requirements: 'اشتراطات المواقف', entrances_exits_requirements: 'اشتراطات المداخل والمخارج',
      regulatory_constraints: 'القيود التنظيمية',
      name: 'الاسم', category: 'النوع', type: 'النوع', value: 'القيمة', field: 'الحقل',
      label: 'الوصف', description: 'الوصف', role: 'الدور', company: 'الشركة',
      status: 'الحالة', date: 'التاريخ', amount: 'المبلغ', price: 'السعر',
      total: 'الإجمالي', count: 'العدد', percent: 'النسبة', notes: 'ملاحظات',
      distance_km: 'المسافة (كم)', duration_minutes: 'المدة (دقيقة)',
      duration_min: 'المدة (دقيقة)', show_on_map: 'يظهر على الخريطة',
      audience: 'الفئة المستهدفة', components: 'المكونات', segments: 'الفئات',
      access: 'خريطة الوصول', catchment: 'خريطة التغطية', landmarks: 'خريطة المعالم',
      overview: 'الخريطة العامة', enabled: 'مفعّل', visible: 'ظاهر',
      residential: 'سكني', commercial: 'تجاري', offices: 'مكاتب', retail: 'تجزئة',
      hotel: 'فندقي', mixed: 'مختلط', area: 'المساحة', floors: 'الأدوار',
      revenue: 'الإيراد', cost: 'التكلفة', year: 'السنة', month: 'الشهر',
      start: 'البداية', end: 'النهاية', phase: 'المرحلة', milestone: 'المرحلة',
      task: 'المهمة', owner: 'المسؤول', duration: 'المدة', progress: 'التقدم',
    };

    function diffBlobKeyLabel(key) {
      return DIFF_BLOB_KEY_LABELS[key] || key;
    }

    // Some fields store structured data as serialized JSON text; a string that
    // parses to an object/array renders structured like a real blob — printing
    // it raw would also garble the braces under RTL bidi.
    function diffParseJsonString(value) {
      if (typeof value !== 'string') return null;
      const trimmed = value.trim();
      if (trimmed.length < 2) return null;
      const first = trimmed[0];
      const last = trimmed[trimmed.length - 1];
      if ((first !== '{' || last !== '}') && (first !== '[' || last !== ']')) return null;
      try {
        const parsed = JSON.parse(trimmed);
        return (parsed && typeof parsed === 'object') ? parsed : null;
      } catch (e) {
        return null;
      }
    }

    function diffScalarText(value) {
      if (typeof value === 'boolean') return value ? 'نعم' : 'لا';
      return String(value);
    }

    function sectionVersionValueIsEmpty(value) {
      if (value === null || value === undefined || value === '') return true;
      if (Array.isArray(value)) return !value.length;
      if (typeof value === 'object') return !Object.keys(value).length;
      return false;
    }

    function diffValueNode(value) {
      const box = document.createElement('div');
      box.className = 'section-version-diff-struct';
      if (Array.isArray(value)) {
        const items = value.filter(item => !sectionVersionValueIsEmpty(item));
        if (!items.length) { box.textContent = '—'; return box; }
        const allScalar = items.every(item => typeof item !== 'object' || item === null);
        const flatObjects = !allScalar && items.every(item =>
          item && typeof item === 'object' && !Array.isArray(item) &&
          Object.keys(item).every(key => item[key] === null || typeof item[key] !== 'object'));
        if (allScalar) {
          items.forEach(item => {
            const line = document.createElement('div');
            line.className = 'section-version-diff-line';
            line.textContent = diffScalarText(item);
            box.appendChild(line);
          });
          return box;
        }
        if (flatObjects) {
          const cols = [];
          items.forEach(item => Object.keys(item).forEach(key => {
            if (!DIFF_BLOB_SKIP_KEYS.has(key) && !cols.includes(key)) cols.push(key);
          }));
          if (cols.length && cols.length <= 6) {
            const table = document.createElement('table');
            table.className = 'section-version-diff-table';
            const headRow = document.createElement('tr');
            cols.forEach(key => {
              const th = document.createElement('th');
              th.textContent = diffBlobKeyLabel(key);
              headRow.appendChild(th);
            });
            table.appendChild(headRow);
            items.forEach(item => {
              const tr = document.createElement('tr');
              cols.forEach(key => {
                const td = document.createElement('td');
                const cell = item[key];
                td.textContent = cell === null || cell === undefined || cell === '' ? '—' : diffScalarText(cell);
                tr.appendChild(td);
              });
              table.appendChild(tr);
            });
            box.appendChild(table);
            return box;
          }
        }
        items.forEach(item => {
          const sub = document.createElement('div');
          sub.className = 'section-version-diff-sub';
          const parsed = diffParseJsonString(item);
          if (item && typeof item === 'object') sub.appendChild(diffValueNode(item));
          else if (parsed) sub.appendChild(diffValueNode(parsed));
          else { sub.classList.add('section-version-diff-line'); sub.textContent = diffScalarText(item); }
          box.appendChild(sub);
        });
        return box;
      }
      Object.keys(value).forEach(key => {
        if (DIFF_BLOB_SKIP_KEYS.has(key)) return;
        const item = value[key];
        if (sectionVersionValueIsEmpty(item)) return;
        const kv = document.createElement('div');
        kv.className = 'section-version-diff-kv';
        const k = document.createElement('span');
        k.className = 'section-version-diff-key';
        k.textContent = diffBlobKeyLabel(key);
        kv.appendChild(k);
        const parsed = diffParseJsonString(item);
        if (item && typeof item === 'object') {
          const nested = document.createElement('div');
          nested.className = 'section-version-diff-nested';
          nested.appendChild(diffValueNode(item));
          kv.appendChild(nested);
        } else if (parsed) {
          const nested = document.createElement('div');
          nested.className = 'section-version-diff-nested';
          nested.appendChild(diffValueNode(parsed));
          kv.appendChild(nested);
        } else {
          const val = document.createElement('span');
          val.className = 'section-version-diff-val';
          val.textContent = diffScalarText(item);
          kv.appendChild(val);
        }
        box.appendChild(kv);
      });
      if (!box.children.length) box.textContent = '—';
      return box;
    }

    // A modified text field gets an inline diff: only the lines that actually
    // changed are tinted, and inside a changed pair of lines the differing
    // words are marked, so the approver sees exactly what moved.
    function diffPlainTextValue(value) {
      if (value === null || value === undefined) return null;
      if (typeof value === 'object') return null;
      if (diffParseJsonString(value)) return null;
      return String(value);
    }

    function diffLines(oldText, newText) {
      const a = String(oldText).split('\n');
      const b = String(newText).split('\n');
      if (a.length > 400 || b.length > 400) return null;
      const m = a.length;
      const n = b.length;
      const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
      for (let i = m - 1; i >= 0; i--) {
        for (let j = n - 1; j >= 0; j--) {
          dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
      const ops = [];
      let i = 0;
      let j = 0;
      while (i < m && j < n) {
        if (a[i] === b[j]) { ops.push({ type: 'same', oldLine: a[i], newLine: b[j] }); i++; j++; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ type: 'del', oldLine: a[i] }); i++; }
        else { ops.push({ type: 'add', newLine: b[j] }); j++; }
      }
      while (i < m) ops.push({ type: 'del', oldLine: a[i++] });
      while (j < n) ops.push({ type: 'add', newLine: b[j++] });
      return ops;
    }

    function diffWordMarks(line, paired) {
      // Token-level LCS that keeps whitespace: only the differing tokens mark.
      const mine = String(line).split(/(\s+)/);
      const other = String(paired).split(/(\s+)/);
      const m = mine.length;
      const n = other.length;
      if (m > 300 || n > 300) return null;
      const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
      for (let i = m - 1; i >= 0; i--) {
        for (let j = n - 1; j >= 0; j--) {
          dp[i][j] = mine[i] === other[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
      const marks = new Array(m).fill(false);
      let i = 0;
      let j = 0;
      while (i < m && j < n) {
        if (mine[i] === other[j]) { i++; j++; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) { marks[i] = true; i++; }
        else { j++; }
      }
      while (i < m) marks[i++] = true;
      const frags = [];
      for (let k = 0; k < m; k++) {
        const changed = marks[k] && mine[k].trim() !== '';
        const last = frags[frags.length - 1];
        if (last && last.changed === changed) last.text += mine[k];
        else frags.push({ text: mine[k], changed: changed });
      }
      return frags;
    }

    function renderDiffLines(ops, side) {
      const box = document.createElement('div');
      box.className = 'section-version-diff-text';
      let i = 0;
      while (i < ops.length) {
        if (ops[i].type === 'same') {
          const line = document.createElement('div');
          line.className = 'section-version-diff-tline';
          line.textContent = (side === 'old' ? ops[i].oldLine : ops[i].newLine) || ' ';
          box.appendChild(line);
          i++;
          continue;
        }
        const block = [];
        while (i < ops.length && ops[i].type !== 'same') { block.push(ops[i]); i++; }
        const dels = block.filter(op => op.type === 'del');
        const adds = block.filter(op => op.type === 'add');
        const source = side === 'old' ? dels : adds;
        const other = side === 'old' ? adds : dels;
        const pairs = Math.min(dels.length, adds.length);
        source.forEach((entry, idx) => {
          const lineText = side === 'old' ? entry.oldLine : entry.newLine;
          const pairedEntry = idx < pairs ? other[idx] : null;
          const pairedText = pairedEntry ? (side === 'old' ? pairedEntry.newLine : pairedEntry.oldLine) : null;
          const div = document.createElement('div');
          div.className = 'section-version-diff-tline ' + (side === 'old' ? 'diff-del' : 'diff-ins');
          const marks = pairedText === null ? null : diffWordMarks(lineText, pairedText);
          if (!marks) {
            div.textContent = lineText || ' ';
          } else {
            let wrote = false;
            marks.forEach(frag => {
              if (!frag.text) return;
              wrote = true;
              if (!frag.changed) { div.appendChild(document.createTextNode(frag.text)); return; }
              const mark = document.createElement('span');
              mark.className = 'diff-word';
              mark.textContent = frag.text;
              div.appendChild(mark);
            });
            if (!wrote) div.textContent = ' ';
          }
          box.appendChild(div);
        });
      }
      return box;
    }

    function fillScalarDiffCells(oldCell, newCell, oldValue, newValue) {
      const oldText = diffPlainTextValue(oldValue);
      const newText = diffPlainTextValue(newValue);
      if (oldText === null || newText === null || oldText === newText) return;
      const ops = diffLines(oldText, newText);
      if (!ops) return;
      const oldBox = oldCell.querySelector('.section-version-diff-value');
      const newBox = newCell.querySelector('.section-version-diff-value');
      if (!oldBox || !newBox) return;
      oldBox.innerHTML = '';
      newBox.innerHTML = '';
      oldBox.appendChild(renderDiffLines(ops, 'old'));
      newBox.appendChild(renderDiffLines(ops, 'new'));
    }

    // One side of the comparison: a captioned box so the previous value always
    // sits next to the new value, even when one of them is empty (added fields
    // have no previous value, removed fields have no new one).
    function sectionVersionDiffCell(side, value, isAttachment) {
      const cell = document.createElement('div');
      cell.className = 'section-version-diff-cell section-version-diff-' + side;
      const cap = document.createElement('span');
      cap.className = 'section-version-diff-cap';
      cap.textContent = side === 'old'
        ? WFT('sectionver.diff_col_old', 'القيمة السابقة')
        : side === 'same'
          ? WFT('sectionver.diff_col_value', 'القيمة')
          : WFT('sectionver.diff_col_new', 'القيمة الجديدة');
      cell.appendChild(cap);
      const val = document.createElement('div');
      val.className = 'section-version-diff-value';
      if (sectionVersionValueIsEmpty(value)) {
        val.textContent = '—';
        val.classList.add('is-empty');
      } else if (isAttachment) {
        const names = diffAttachmentNames(value);
        if (names.length) val.textContent = names.join('\n');
        else val.appendChild(diffValueNode(value));
      } else {
        const parsed = diffParseJsonString(value);
        if (parsed) val.appendChild(diffValueNode(parsed));
        else if (typeof value === 'object') val.appendChild(diffValueNode(value));
        else val.textContent = diffScalarText(value);
      }
      cell.appendChild(val);
      return cell;
    }

    // Attachment snapshots store file objects/ids; names read better than JSON.
    function diffAttachmentNames(value) {
      const names = [];
      const walk = item => {
        if (!item) return;
        if (Array.isArray(item)) { item.forEach(walk); return; }
        if (typeof item === 'object') {
          const name = item.originalName || item.original_name || item.name || item.filename;
          if (typeof name === 'string' && name.trim()) names.push(name);
          else Object.keys(item).forEach(key => walk(item[key]));
          return;
        }
        if (typeof item === 'string' && item.trim()) names.push(item);
      };
      walk(value);
      return names;
    }

    // The preview mirrors the section's own field order: controls carry
    // data-key, so their DOM position orders the diff rows. Snapshot-only keys
    // (stored blobs, attachments) keep their diff order at the end.
    function sectionFieldOrderMap(sectionKey) {
      const order = {};
      const section = getProjectSectionElement(sectionKey);
      if (section) {
        section.querySelectorAll('[data-key]').forEach((el, idx) => {
          const key = el.dataset ? el.dataset.key : '';
          if (key && order[key] === undefined) order[key] = idx;
        });
      }
      return order;
    }

    function sectionVersionDiffStatusText(status) {
      if (status === 'added') return WFT('sectionver.diff_added', 'مضاف');
      if (status === 'removed') return WFT('sectionver.diff_removed', 'محذوف');
      if (status === 'modified') return WFT('sectionver.diff_modified', 'معدل');
      return WFT('sectionver.diff_unchanged', 'بدون تغيير');
    }

    function renderSectionDiffPanel(sectionKey) {
      const body = document.getElementById('sectionVersionsPageBody');
      const history = document.getElementById('section-version-history-' + sectionKey);
      if (!body || !history) return;
      let panel = body.querySelector(':scope > .section-version-diff');
      if (!panel) {
        panel = document.createElement('div');
        panel.className = 'section-version-diff';
        body.appendChild(panel);
      }
      const diff = sectionVersionDiffCache[sectionKey];
      if (!diff) { panel.hidden = true; panel.innerHTML = ''; history.hidden = false; return; }
      // The preview takes over the versions page: the list stays mounted but
      // hidden until the approver goes back.
      panel.hidden = false;
      history.hidden = true;
      panel.innerHTML = '';
      const head = document.createElement('div');
      head.className = 'section-version-diff-head';
      const title = document.createElement('strong');
      title.textContent = diff.base_version_number
        ? WFT('sectionver.preview_title_between', 'معاينة الإصدار {n} — مقارنة مع الإصدار {b}', { n: diff.version_number, b: diff.base_version_number })
        : WFT('sectionver.preview_title_first', 'معاينة الإصدار {n}', { n: diff.version_number });
      head.appendChild(title);
      const closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'section-approve-btn';
      closeBtn.dataset.sectionLockIgnore = '1';
      closeBtn.textContent = WFT('common.back', 'رجوع');
      closeBtn.addEventListener('click', () => {
        delete sectionVersionDiffCache[sectionKey];
        renderSectionVersionBlock(sectionKey);
      });
      head.appendChild(closeBtn);
      panel.appendChild(head);
      const summary = diff.summary || {};
      const counts = document.createElement('p');
      counts.className = 'tenant-hint';
      counts.textContent = WFT('sectionver.diff_counts', 'تعديلات {m} — إضافات {a} — حذف {r}',
        { m: summary.modified || 0, a: summary.added || 0, r: summary.removed || 0 });
      panel.appendChild(counts);
      const attachments = Array.isArray(diff.attachments) ? diff.attachments : [];
      const order = sectionFieldOrderMap(sectionKey);
      // Only what changed: unchanged fields add noise and are already counted
      // in the summary line above.
      const items = (Array.isArray(diff.fields) ? diff.fields : [])
        .concat(attachments.map(att => Object.assign({ _diffAttachment: true }, att)))
        .filter(item => item && item.key && item.status !== 'unchanged')
        .map((item, idx) => ({ item: item, idx: idx }))
        .sort((a, b) => {
          const oa = order[a.item.key];
          const ob = order[b.item.key];
          const ia = oa === undefined ? Number.MAX_SAFE_INTEGER : oa;
          const ib = ob === undefined ? Number.MAX_SAFE_INTEGER : ob;
          return ia === ib ? a.idx - b.idx : ia - ib;
        })
        .map(x => x.item);
      if (!items.length) {
        const empty = document.createElement('p');
        empty.className = 'tenant-hint';
        empty.textContent = WFT('sectionver.diff_none', 'لا توجد تغييرات بين الإصدارين');
        panel.appendChild(empty);
        return;
      }
      const grid = document.createElement('div');
      grid.className = 'section-version-diff-grid';
      items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'tenant-field section-version-diff-row diff-' + item.status;
        const rowHead = document.createElement('div');
        rowHead.className = 'section-version-diff-row-head';
        const label = document.createElement('label');
        label.className = 'section-version-diff-label';
        label.textContent = (item._diffAttachment ? WFT('sectionver.diff_attachment', 'مرفق') + ': ' : '') + (item.label || item.key);
        rowHead.appendChild(label);
        const status = document.createElement('span');
        status.className = 'section-version-diff-status';
        status.textContent = sectionVersionDiffStatusText(item.status);
        rowHead.appendChild(status);
        row.appendChild(rowHead);
        const cols = document.createElement('div');
        cols.className = 'section-version-diff-cols';
        if (item.status === 'unchanged') {
          // Identical on both sides — one box states the value without
          // duplicating long content such as polygon or table data.
          cols.classList.add('single');
          cols.appendChild(sectionVersionDiffCell('same', item.new_value, item._diffAttachment));
        } else {
          const oldCell = sectionVersionDiffCell('old', item.old_value, item._diffAttachment);
          const newCell = sectionVersionDiffCell('new', item.new_value, item._diffAttachment);
          if (!item._diffAttachment && item.status === 'modified') {
            fillScalarDiffCells(oldCell, newCell, item.old_value, item.new_value);
          }
          cols.appendChild(oldCell);
          cols.appendChild(newCell);
        }
        row.appendChild(cols);
        grid.appendChild(row);
      });
      panel.appendChild(grid);
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
        try { window.WFI18n.autoTranslate(panel); } catch (e) {}
      }
    }

    async function toggleSectionVersionDiff(versionId, sectionKey) {
      const cached = sectionVersionDiffCache[sectionKey];
      if (cached && cached.version_id === versionId) {
        delete sectionVersionDiffCache[sectionKey];
        renderSectionDiffPanel(sectionKey);
        return;
      }
      showLoader(WFT('sectionver.diff_loading', 'جلب المقارنة'), '', 10);
      try {
        const result = await api('GET', '/api/project-draft/section-versions/' + encodeURIComponent(versionId) + '/diff');
        hideLoader();
        if (!result || !result.success) {
          toast((result && result.error) || WFT('sectionver.diff_failed', 'تعذر جلب المقارنة'));
          return;
        }
        sectionVersionDiffCache[sectionKey] = result.diff;
        sectionVersionsOpen[sectionKey] = true;
        renderSectionVersionBlock(sectionKey);
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    // ── Location data tables (roads / landmarks / catchment) ──────────────
    // These fields stay plain text in project data (each row serialized as
    // "name — X كم — Y دقائق") so maps/AI keep working, but the UI edits them
    // as proper tables with add/delete rows.
    const LOCATION_TABLE_FIELDS = {
      main_roads: { nameLabel: 'الطريق الرئيسي', nameHint: 'مثال: طريق الملك فهد', nameOnly: true, road: true, mapType: 'access' },
      nearby_landmarks: { nameLabel: 'المَعلم القريب', nameHint: 'مثال: مجمع الراشد', categoryLabel: 'النوع', mapSelectable: true, mapType: 'landmarks' },
      city_landmarks: { nameLabel: 'مَعلم المدينة', nameHint: 'مثال: الواجهة البحرية', categoryLabel: 'النوع', mapSelectable: true, mapType: 'catchment' },
    };

    function parseLocationFieldText(key, value) {
      if (Array.isArray(value)) {
        return value.map(item => ({
          name: (item && (item.name || item.area || item.title)) || '',
          category: item && (item.category || item.type || ''),
          distance_km: item && (item.distance_km ?? item.distance ?? ''),
          duration_minutes: item && (item.duration_minutes ?? item.duration_min ?? item.minutes ?? ''),
          lat: item && (item.lat ?? item.latitude ?? ''),
          lng: item && (item.lng ?? item.longitude ?? ''),
          show_on_map: !!(item && (item.show_on_map || item.selected)),
          row_source: item && (item.row_source || item.rowSource || 'manual'),
        })).filter(r => r.name);
      }
      const rows = [];
      String(value == null ? '' : value).split('\n').forEach(rawLine => {
        const line = rawLine.trim().replace(/^[-•*]\s*/, '');
        if (!line) return;
        const dur = line.match(/(\d+(?:\.\d+)?)\s*(?:دقيقة|دقائق|min|mins|minutes)/i);
        const dist = line.match(/(\d+(?:\.\d+)?)\s*(?:كم|كـم|km|kms|kilometers?)/i);
        let name = line;
        if (dur) name = name.replace(dur[0], '');
        if (dist) name = name.replace(dist[0], '');
        name = name.replace(/^[\s:：\-—–,،]+|[\s:：\-—–,،]+$/g, '').trim();
        let category = '';
        if (key === 'nearby_landmarks' || key === 'city_landmarks') {
          const categoryMatch = name.match(/\s+-\s+(ترفيهي|تعليمي|صحي|تجاري|ديني(?: ومركزي)?|ثقافي\/سياحي|حكومي\/خدمي|اجتماعي\/خدمي|النقل(?: العام)?|المشاعر|المحاور)\s*$/);
          if (categoryMatch) {
            category = categoryMatch[1];
            name = name.slice(0, categoryMatch.index).trim();
          } else {
            const pieces = name.split(/\s+[—-]\s+/).map(part => part.trim()).filter(Boolean);
            if (pieces.length > 1) {
              category = pieces.pop();
              name = pieces.join(' — ');
            }
          }
        }
        if (!name) name = line;
        rows.push({ name: name, category: category, distance_km: dist ? dist[1] : '', duration_minutes: dur ? dur[1] : '' });
      });
      return rows;
    }

    function normalizeAccessRoadNames(value) {
      const values = Array.isArray(value) ? value : String(value || '').split(/[\n,،;|]+/);
      const seen = new Set();
      const result = [];
      values.forEach(raw => {
        const name = String(raw || '').trim();
        if (!name) return;
        const prefix = name.match(/^(طريق|شارع|جادة|ممر)\s+/)?.[1] || '';
        name.split(/\s+و(?=\s|ال|شارع|طريق|جادة|ممر)\s*/).map(part => part.trim()).filter(Boolean).forEach(part => {
          if (prefix && !/^(طريق|شارع|جادة|ممر)\s+/.test(part)) part = prefix + ' ' + part;
          const key = part.replace(/^(طريق|شارع|جادة|ممر)\s+/, '').replace(/[\sـ]+/g, ' ').trim().toLowerCase();
          if (!key || seen.has(key)) return;
          seen.add(key);
          result.push(part);
        });
      });
      return result;
    }

    function formatLocationDataFetchedAt(value) {
      const date = new Date(value || '');
      if (!Number.isFinite(date.getTime())) return '';
      return new Intl.DateTimeFormat('ar-SA-u-ca-gregory', {
        timeZone: 'Asia/Riyadh', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
      }).format(date) + ' بتوقيت السعودية';
    }

    function setLocationDataFetchedAt(value = new Date().toISOString()) {
      tenantProjectData.location_data_fetched_at = value;
      const input = document.getElementById('locationDataFetchedAt');
      if (input) input.value = value;
      const display = document.getElementById('locationDataFetchedAtDisplay');
      if (display) display.textContent = value ? 'آخر تحديث للبيانات: ' + formatLocationDataFetchedAt(value) : '';
    }

    function serializeLocationTable(key) {
      const table = document.querySelector('#tenantProjectForm table.location-table[data-location-table="' + key + '"]');
      const hidden = document.querySelector('#tenantProjectForm [data-key="' + key + '"].location-table-value');
      if (!table || !hidden) return;
      const lines = [];
      const structuredRows = [];
      table.querySelectorAll('tbody tr').forEach(tr => {
        const name = (tr.querySelector('.lt-name-input').value || '').trim();
        if (!name) return;
        const category = (tr.querySelector('.lt-category-input')?.value || '').trim();
        const dist = (tr.querySelector('.lt-dist-input')?.value || '').trim();
        const dur = (tr.querySelector('.lt-dur-input')?.value || '').trim();
        const parts = [name];
        if (category) parts.push(category);
        if (dist) parts.push(dist + ' كم');
        if (dur) parts.push(dur + ' دقائق');
        lines.push(parts.join(' — '));
        structuredRows.push({
          name, category, distance_km: dist, duration_minutes: dur,
          lat: tr.dataset.lat || '', lng: tr.dataset.lng || '',
          show_on_map: !!tr.querySelector('.lt-map-select')?.checked,
          row_source: tr.dataset.rowSource || 'manual'
        });
      });
      hidden.value = (key === 'main_roads' ? normalizeAccessRoadNames(lines) : lines).join('\n');
      if (key === 'main_roads') {
        tenantProjectData.main_roads = hidden.value;
        tenantProjectData.main_roads_data = structuredRows;
      } else if (key === 'nearby_landmarks') {
        tenantNearbyLandmarks = structuredRows;
        tenantProjectData.nearby_landmarks_data = structuredRows;
      } else if (key === 'city_landmarks') {
        tenantProjectData.city_landmarks_data = structuredRows;
      }
    }