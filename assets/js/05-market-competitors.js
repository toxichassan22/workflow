/* 05-market-competitors.js - index.html lines 11653-12627, shared global scope, classic scripts in order */

    function renderCompetitorAreaInputs(tr, row = {}) {
      const cell = tr.querySelector('[data-field="area_cell"]');
      if (!cell) return;
      const from = cleanMarketNumber(row.area_from ?? row.areaFrom ?? tr.dataset.areaFrom ?? '');
      const to = cleanMarketNumber(row.area_to ?? row.areaTo ?? tr.dataset.areaTo ?? '');
      const fixed = cleanMarketNumber(row.area_sqm ?? row.areaSqm ?? tr.dataset.areaFixed ?? '');
      const mode = row.area_mode === 'range' ? 'range'
        : row.area_mode === 'fixed' ? 'fixed'
          : from !== '' || to !== '' ? 'range' : 'fixed';
      cell.innerHTML = '<select data-field="area_mode"><option value="fixed"' + (mode === 'fixed' ? ' selected' : '') + '>مساحة ثابتة</option><option value="range"' + (mode === 'range' ? ' selected' : '') + '>نطاق من — إلى</option></select>' +
        (mode === 'range'
          ? '<input data-field="area_from" value="' + escapeHtml(from) + '" placeholder="من (م²)" inputmode="decimal" style="margin-top:6px"><input data-field="area_to" value="' + escapeHtml(to) + '" placeholder="إلى (م²)" inputmode="decimal" style="margin-top:6px">'
          : '<input data-field="area_sqm" value="' + escapeHtml(fixed) + '" placeholder="المساحة (م²)" inputmode="decimal" style="margin-top:6px">');
      cell.querySelector('[data-field="area_mode"]').addEventListener('change', event => {
        cacheCompetitorAreaInputs(tr);
        const current = collectOneCompetitorRow(tr);
        current.area_mode = event.target.value;
        if (current.area_mode === 'range') {
          current.area_from = current.area_cache?.area_from || current.area_sqm;
          current.area_to = current.area_cache?.area_to || '';
        } else {
          current.area_sqm = current.area_cache?.area_sqm || current.area_from || current.area_to;
        }
        renderCompetitorAreaInputs(tr, current);
        persistMarketStudyFromDom();
      });
      cell.querySelectorAll('input').forEach(input => {
        formatMarketNumericInput(input);
        input.addEventListener('input', () => {
          cacheCompetitorAreaInputs(tr);
          persistMarketStudyFromDom();
        });
      });
      refreshDynamicI18n(cell);
    }

    function competitorLogoPath(row = {}) {
      return String(row.logo_path || row.logoPath || row.logo_url || row.logoUrl || '');
    }

    function closeCompetitorLogoPreview() {
      document.getElementById('competitorLogoPreviewModal')?.remove();
    }

    async function openCompetitorLogoPreview(tr) {
      if (!tr) return;
      let source = tr.dataset.logoPath || tr.dataset.logoUrl || '';
      if (/^\/api\/project-files\//i.test(source)) source = '';
      if (!source && tr.dataset.logoFileId) {
        try {
          source = await getProjectFileObjectUrl(tr.dataset.logoFileId);
        } catch (error) {
          toast(error.message || 'تعذر تحميل صورة الشعار');
          return;
        }
      }
      if (!source) {
        toast('لا توجد صورة شعار للمعاينة');
        return;
      }
      closeCompetitorLogoPreview();
      const modal = document.createElement('div');
      modal.id = 'competitorLogoPreviewModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:16px;max-width:1100px;width:100%;max-height:92vh;display:flex;flex-direction:column;gap:12px">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:12px"><h3 style="margin:0;font-size:1rem">معاينة شعار المنافس</h3>' +
        '<button type="button" class="btn ghost" data-close-competitor-logo-preview>إغلاق</button></div>' +
        '<div style="min-height:320px;max-height:78vh;overflow:auto;background:#f6f7f9;border-radius:12px;display:flex;align-items:center;justify-content:center;padding:12px">' +
        '<img src="' + escapeHtml(source) + '" alt="شعار المنافس" style="max-width:100%;max-height:76vh;width:auto;height:auto;object-fit:contain;display:block"></div></div>';
      modal.addEventListener('click', event => { if (event.target === modal) closeCompetitorLogoPreview(); });
      document.body.appendChild(modal);
      modal.querySelector('[data-close-competitor-logo-preview]')?.addEventListener('click', closeCompetitorLogoPreview);
      modal.querySelector('img')?.addEventListener('error', () => {
        const image = modal.querySelector('img');
        if (image) image.replaceWith(Object.assign(document.createElement('span'), {
          className: 'tenant-hint', textContent: 'تعذر عرض صورة الشعار'
        }));
      });
    }

    function startCompetitorLogoProgress(tr, initialLabel) {
      const progress = tr?.querySelector('[data-logo-progress]');
      const bar = progress?.querySelector('[data-logo-progress-bar]');
      const label = progress?.querySelector('[data-logo-progress-label]');
      if (!progress || !bar || !label) return;
      progress.hidden = false;
      let value = 8;
      let phase = 0;
      const phases = ['جاري التحقق من الموقع الرسمي', 'جاري البحث عن صورة الشعار', 'جاري حفظ الشعار'];
      bar.style.width = value + '%';
      bar.setAttribute('aria-valuenow', String(value));
      label.textContent = initialLabel || phases[phase];
      clearInterval(tr._competitorLogoProgressTimer);
      tr._competitorLogoProgressTimer = window.setInterval(() => {
        value = value < 65 ? value + 7 : value < 90 ? value + 2 : value;
        if (value >= 35) phase = 1;
        if (value >= 70) phase = 2;
        bar.style.width = value + '%';
        bar.setAttribute('aria-valuenow', String(value));
        label.textContent = phases[phase];
      }, 700);
    }

    function finishCompetitorLogoProgress(tr, success, successLabel = 'اكتمل استيراد الشعار', failureLabel = 'تعذر استيراد الشعار') {
      if (!tr) return;
      clearInterval(tr._competitorLogoProgressTimer);
      const progress = tr.querySelector('[data-logo-progress]');
      const bar = progress?.querySelector('[data-logo-progress-bar]');
      const label = progress?.querySelector('[data-logo-progress-label]');
      if (bar) {
        bar.style.width = '100%';
        bar.setAttribute('aria-valuenow', '100');
      }
      if (label) label.textContent = success ? successLabel : failureLabel;
      window.setTimeout(() => {
        tr.dataset.logoUploading = '';
        renderCompetitorLogoCell(tr);
      }, success ? 450 : 900);
    }

    async function removeCompetitorLogo(tr) {
      if (!tr || tr.dataset.logoUploading === 'true') return;
      if (!confirm('حذف شعار المنافس؟')) return;
      const fileId = tr.dataset.logoFileId || '';
      if (fileId) {
        try {
          const response = await api('DELETE', '/api/project-files/' + encodeURIComponent(fileId));
          if (!response?.success) throw new Error(response?.error || 'تعذر حذف ملف الشعار');
        } catch (error) {
          toast(error.message || 'تعذر حذف ملف الشعار');
          return;
        }
      }
      tr.dataset.logoFileId = '';
      tr.dataset.logoPath = '';
      tr.dataset.logoUrl = '';
      tr.dataset.logoImportWarning = '';
      renderCompetitorLogoCell(tr);
      persistMarketStudyFromDom();
    }

    async function uploadCompetitorLogo(input, tr) {
      const file = input.files?.[0];
      if (!file) return;
      const formData = new FormData();
      formData.append('file', file, file.name);
      formData.append('fileType', 'competitor_logo');
      if (tenantProjectData?.draftId) formData.append('draftId', tenantProjectData.draftId);
      formData.append('projectId', tr.dataset.competitorId);
      tr.dataset.logoUploading = 'true';
      renderCompetitorLogoCell(tr);
      startCompetitorLogoProgress(tr, 'جاري حفظ الشعار');
      let success = false;
      try {
        const response = await api('POST', '/api/project-files', formData, true);
        if (!response?.success || !response.file?.id) throw new Error(response?.error || 'تعذر حفظ شعار المنافس');
        const published = await publishProjectFileImageUrl(response.file.id, 'competitor-logo-' + tr.dataset.competitorId);
        tr.dataset.logoFileId = response.file.id;
        tr.dataset.logoPath = published || ('/api/project-files/' + response.file.id);
        tr.dataset.logoUrl = '';
        tr.dataset.logoSourceUrl = '';
        renderCompetitorLogoCell(tr);
        persistMarketStudyFromDom();
        success = true;
      } catch (error) {
        toast(error.message || 'تعذر حفظ شعار المنافس');
      } finally {
        finishCompetitorLogoProgress(tr, success, 'اكتمل حفظ الشعار', 'تعذر حفظ الشعار');
      }
    }

    function renderCompetitorLogoCell(tr) {
      const cell = tr.querySelector('[data-field="logo_cell"]');
      if (!cell) return;
      const path = tr.dataset.logoPath || tr.dataset.logoUrl || '';
      const hasLogo = Boolean(path || tr.dataset.logoFileId);
      const uploading = tr.dataset.logoUploading === 'true';
      const busy = uploading;
      const busyLabel = 'جاري حفظ الشعار';
      const progress = busy
        ? '<div data-logo-progress class="market-logo-progress"><div class="market-logo-progress-track"><div data-logo-progress-bar class="market-logo-progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="8"></div></div><span data-logo-progress-label class="market-logo-progress-label">' + busyLabel + '</span></div>'
        : '';
      const warning = (!hasLogo && !busy) ? String(tr.dataset.logoImportWarning || '').trim() : '';
      const actions = hasLogo
        ? '<div class="market-logo-actions"><button type="button" class="btn ghost small" data-preview-competitor-logo>تكبير</button><button type="button" class="btn ghost small" data-remove-competitor-logo>حذف</button></div>'
        : '';
      cell.innerHTML = (path ? '<img src="' + escapeHtml(path) + '" alt="شعار المنافس" style="width:72px;height:54px;object-fit:contain;background:#fff;border:1px solid var(--line);border-radius:8px;margin-bottom:5px">' : '<div style="height:54px;display:flex;align-items:center;justify-content:center;color:var(--muted)">' + (busy ? busyLabel : 'لا يوجد') + '</div>') +
        progress + actions +
        '<input type="file" accept="image/png,image/jpeg,image/webp" data-competitor-logo style="width:100%;font-size:11px"' + (busy ? ' disabled' : '') + '>' +
        (warning ? '<div style="color:var(--muted);font-size:11px;margin-top:4px">' + escapeHtml(warning) + '</div>' : '');
      cell.querySelector('[data-competitor-logo]')?.addEventListener('change', event => uploadCompetitorLogo(event.target, tr));
      cell.querySelector('[data-preview-competitor-logo]')?.addEventListener('click', () => openCompetitorLogoPreview(tr));
      cell.querySelector('[data-remove-competitor-logo]')?.addEventListener('click', () => removeCompetitorLogo(tr));
      refreshDynamicI18n(cell);
    }

    function competitorPriceCache(tr) {
      try { return JSON.parse(tr.dataset.priceCache || '{}') || {}; } catch (error) { return {}; }
    }

    function cacheCompetitorPriceInputs(tr, priceType) {
      const cache = competitorPriceCache(tr);
      const read = field => cleanMarketNumber(tr.querySelector('[data-field="' + field + '"]')?.value || '');
      const type = priceType || tr.dataset.previousPriceType || tr.querySelector('[data-field="price_type"]')?.value || '';
      if (type) cache[type] = { price_value: read('price_value'), price_from: read('price_from'), price_to: read('price_to') };
      tr.dataset.priceCache = JSON.stringify(cache);
      return cache;
    }

    function addMarketCompetitorRow(row = {}) {
      const tb = document.querySelector('#marketCompetitorsTable tbody');
      if (!tb) return;
      const tr = document.createElement('tr');
      tr.dataset.competitorId = row.id || ('c_' + Date.now() + '_' + Math.random().toString(16).slice(2));
      tr.dataset.classification = row.classification || '';
      tr.dataset.rowSource = row.row_source || 'manual';
      tr.dataset.priceCurrency = row.price_currency || row.currency || 'SAR';
      tr.dataset.fieldSources = JSON.stringify(row.field_sources || row.fieldSources || {});
      tr.dataset.logoFileId = row.logo_file_id || row.logoFileId || '';
      tr.dataset.logoPath = row.logo_path || row.logoPath || '';
      tr.dataset.logoUrl = row.logo_url || row.logoUrl || '';
      tr.dataset.logoSourceUrl = row.logo_source_url || row.logoSourceUrl || '';
      tr.dataset.conflictWarnings = JSON.stringify(row.conflict_warnings || row.conflictWarnings || []);
      tr.dataset.logoImportWarning = row.logo_import_warning || row.logoImportWarning || '';
      tr.dataset.notes = row.notes || row.note || '';
      tr.dataset.district = row.district || row.neighborhood || '';
      tr.dataset.distanceKm = row.distance_km || row.distanceKm || '';
      tr.dataset.lat = row.lat || '';
      tr.dataset.lng = row.lng || '';
      tr.dataset.dataDate = row.data_date || row.dataDate || '';
      tr.dataset.deadSourceUrls = JSON.stringify(row.dead_source_urls || row.deadSourceUrls || []);
      tr.dataset.outOfRadius = row.out_of_radius || row.outOfRadius ? '1' : '';
      tr.dataset.sourcesUnverified = row.sources_unverified || row.sourcesUnverified ? '1' : '';
      const areaCache = row.area_cache || row.areaCache || {};
      tr.dataset.areaFixed = cleanMarketNumber(row.area_sqm || row.areaSqm || areaCache.area_sqm || '');
      tr.dataset.areaFrom = cleanMarketNumber(row.area_from || row.areaFrom || areaCache.area_from || '');
      tr.dataset.areaTo = cleanMarketNumber(row.area_to || row.areaTo || areaCache.area_to || '');
      tr.dataset.priceCache = JSON.stringify(row.price_cache || row.priceCache || {});
      const operation = inferCompetitorOperation(row);
      const priceType = inferCompetitorPriceType(row);
      const priceTypes = MARKET_PRICE_TYPES[operation] || MARKET_PRICE_TYPES['أخرى'];
      tr.dataset.previousPriceType = priceType;
      let warnings = [];
      try { warnings = JSON.parse(tr.dataset.conflictWarnings || '[]') || []; } catch (error) { warnings = []; }
      const warningsHtml = warnings.map(item => {
        const label = marketSourceFieldLabel(item.field || '');
        const link = safeMarketUrl(item.source_url) ? ' <a href="' + escapeHtml(safeMarketUrl(item.source_url)) + '" target="_blank" rel="noopener noreferrer">المصدر الرسمي</a>' : '';
        if (item.field === 'distance_km') {
          return '<div style="color:#92400e;margin-top:4px">' + escapeHtml(String(item.source || 'خارج نطاق المنافسين')) +
            ': ' + escapeHtml(String(item.incoming || '')) + ' مقابل ' + escapeHtml(String(item.existing || '')) + '</div>';
        }
        return '<div style="color:#92400e;margin-top:4px">تعارض في ' + escapeHtml(label) + ': تم الإبقاء على القيمة الحالية.' + link + '</div>';
      }).join('') +
      (tr.dataset.sourcesUnverified
        ? '<div style="color:#92400e;margin-top:4px">مصادر هذا الصف لم تُسترجع عبر البحث — أُزيلت الروابط غير الموثقة.</div>'
        : '');
      tr.innerHTML =
        '<td><textarea data-field="name" rows="2">' + escapeHtml(row.name || '') + '</textarea></td>' +
        '<td data-field="logo_cell"></td>' +
        '<td><select data-field="project_type">' + marketSelectHtml(MARKET_PROJECT_TYPES, row.project_type || '') + '</select></td>' +
        '<td><select data-field="classification">' + marketSelectHtml(MARKET_COMPETITOR_CLASSIFICATIONS, row.classification || '') + '</select></td>' +
        '<td data-field="area_cell"></td>' +
        '<td><select data-field="status">' + marketSelectHtml(['قائم', 'تحت الإنشاء', 'على الخارطة'], row.status || '') + '</select></td>' +
        '<td><textarea data-field="source" rows="2" placeholder="المصدر">' + escapeHtml(row.source || '') + '</textarea>' +
        '<div data-source-url-editor class="market-source-url-editor"></div>' +
        '<div data-source-links class="market-source-links"></div><div data-conflict-warnings>' + warningsHtml + '</div></td>' +
        '<td><select data-field="operation_type">' + marketSelectHtml(['بيع', 'إيجار', 'تشغيل فندقي', 'أخرى'], operation) + '</select></td>' +
        '<td><select data-field="price_type">' + marketSelectHtml(priceTypes, priceType) + '</select></td>' +
        '<td data-field="price_cell"></td>' +
        '<td><button type="button" class="btn ghost small" data-remove-competitor>حذف</button></td>';
      tb.appendChild(tr);
      renderCompetitorLogoCell(tr);
      renderCompetitorSourceUrlEditor(tr, row);
      renderCompetitorSourceLinks(tr);
      renderCompetitorAreaInputs(tr, row);
      renderCompetitorPriceInputs(tr, row);
      tr.querySelector('[data-field="operation_type"]').addEventListener('change', () => {
        cacheCompetitorPriceInputs(tr, tr.dataset.previousPriceType);
        const nextOp = tr.querySelector('[data-field="operation_type"]').value;
        const options = MARKET_PRICE_TYPES[nextOp] || MARKET_PRICE_TYPES['أخرى'];
        const previousType = tr.dataset.previousPriceType || '';
        const nextType = options.includes(previousType) ? previousType : (options[0] || '');
        fillSelectOptions(tr.querySelector('[data-field="price_type"]'), options, nextType, '--');
        tr.dataset.previousPriceType = nextType;
        renderCompetitorPriceInputs(tr, { price_cache: competitorPriceCache(tr) });
        refreshDynamicI18n(tr);
        persistMarketStudyFromDom();
      });
      tr.querySelector('[data-field="price_type"]').addEventListener('change', event => {
        cacheCompetitorPriceInputs(tr, tr.dataset.previousPriceType);
        tr.dataset.previousPriceType = event.target.value;
        renderCompetitorPriceInputs(tr, { price_cache: competitorPriceCache(tr) });
        persistMarketStudyFromDom();
      });
      tr.querySelector('[data-remove-competitor]').addEventListener('click', () => {
        tr.remove();
        persistMarketStudyFromDom();
      });
      tr.querySelectorAll('input,select,textarea').forEach(input => input.addEventListener('input', persistMarketStudyFromDom));
      refreshDynamicI18n(tr);
    }

    function renderCompetitorPriceInputs(tr, row) {
      const cell = tr.querySelector('[data-field="price_cell"]');
      if (!cell) return;
      const priceType = tr.querySelector('[data-field="price_type"]')?.value || inferCompetitorPriceType(row);
      const cache = row?.price_cache || row?.priceCache || competitorPriceCache(tr);
      const cached = cache?.[priceType] || {};
      const priceFrom = competitorPriceField(row, 'price_from') || cached.price_from || '';
      const priceTo = competitorPriceField(row, 'price_to') || cached.price_to || '';
      const priceValue = competitorPriceField(row, 'price_value') || cached.price_value || '';
      if (competitorPriceIsRange(priceType)) {
        cell.innerHTML = '<input data-field="price_from" data-currency="SAR" value="' + escapeHtml(priceFrom) + '" placeholder="من (ر.س)" inputmode="decimal">' +
          '<input data-field="price_to" data-currency="SAR" value="' + escapeHtml(priceTo) + '" placeholder="إلى (ر.س)" style="margin-top:6px" inputmode="decimal">';
      } else {
        cell.innerHTML = '<input data-field="price_value" data-currency="SAR" value="' + escapeHtml(priceValue) + '" placeholder="القيمة (ر.س)" inputmode="decimal">';
      }
      cell.querySelectorAll('input').forEach(input => {
        formatMarketNumericInput(input);
        input.addEventListener('input', persistMarketStudyFromDom);
      });
      refreshDynamicI18n(cell);
    }

    function collectOneCompetitorRow(tr) {
      const read = (field) => tr.querySelector('[data-field="' + field + '"]')?.value || '';
      let field_sources = {};
      try {
        field_sources = JSON.parse(tr.dataset.fieldSources || '{}') || {};
      } catch (error) {
        field_sources = {};
      }
      const directSourceUrls = competitorSourceUrlValues(tr);
      const source_urls = marketSourceUrls({
        source_urls: directSourceUrls.length ? directSourceUrls : Array.from(tr.querySelectorAll('[data-source-links] a[href]'))
          .map(anchor => anchor.getAttribute('href') || '')
      });
      cacheCompetitorAreaInputs(tr);
      cacheCompetitorPriceInputs(tr, read('price_type'));
      let conflict_warnings = [];
      try { conflict_warnings = JSON.parse(tr.dataset.conflictWarnings || '[]') || []; } catch (error) { conflict_warnings = []; }
      const area_mode = read('area_mode') || 'fixed';
      const area_cache = {
        area_sqm: cleanMarketNumber(tr.dataset.areaFixed || ''),
        area_from: cleanMarketNumber(tr.dataset.areaFrom || ''),
        area_to: cleanMarketNumber(tr.dataset.areaTo || '')
      };
      let dead_source_urls = [];
      try { dead_source_urls = JSON.parse(tr.dataset.deadSourceUrls || '[]') || []; } catch (error) { dead_source_urls = []; }
      const row = {
        id: tr.dataset.competitorId,
        name: read('name'),
        project_type: read('project_type'),
        area_mode,
        area_sqm: area_mode === 'fixed' ? area_cache.area_sqm : '',
        area_from: area_mode === 'range' ? area_cache.area_from : '',
        area_to: area_mode === 'range' ? area_cache.area_to : '',
        area_cache,
        status: read('status'),
        classification: read('classification'),
        logo_file_id: tr.dataset.logoFileId || '',
        logo_path: tr.dataset.logoPath || '',
        logo_url: tr.dataset.logoUrl || '',
        logo_source_url: tr.dataset.logoSourceUrl || '',
        logo_import_warning: tr.dataset.logoImportWarning || '',
        conflict_warnings,
        operation_type: read('operation_type'),
        price_type: read('price_type'),
        price_currency: tr.dataset.priceCurrency || 'SAR',
        price_value: cleanMarketNumber(read('price_value')),
        price_from: cleanMarketNumber(read('price_from')),
        price_to: cleanMarketNumber(read('price_to')),
        price_cache: competitorPriceCache(tr),
        source: read('source'),
        source_url: source_urls[0] || '',
        source_urls,
        field_sources,
        district: tr.dataset.district || '',
        distance_km: cleanMarketNumber(tr.dataset.distanceKm || ''),
        lat: cleanMarketNumber(tr.dataset.lat || ''),
        lng: cleanMarketNumber(tr.dataset.lng || ''),
        data_date: tr.dataset.dataDate || '',
        notes: tr.dataset.notes || '',
        row_source: tr.dataset.rowSource || 'manual'
      };
      if (dead_source_urls.length) row.dead_source_urls = dead_source_urls;
      if (tr.dataset.outOfRadius) row.out_of_radius = true;
      if (tr.dataset.sourcesUnverified) row.sources_unverified = true;
      return row;
    }

    function collectMarketCompetitorRows() {
      return Array.from(document.querySelectorAll('#marketCompetitorsTable tbody tr')).map(collectOneCompetitorRow);
    }

    function syncMarketCompetitorSources() {
      const state = getMarketStudyState();
      state.competitors = collectMarketCompetitorRows();
      state.sources = mergeMarketSourceRows(
        collectMarketSourceRows(),
        buildMarketCompetitorSourceRows(state.competitors)
      );
      renderMarketSources(state.sources);
      setMarketStudyState(state);
    }

    function renderMarketCompetitors(rows) {
      const tb = document.querySelector('#marketCompetitorsTable tbody');
      if (!tb) return;
      tb.innerHTML = '';
      const visibleRows = Array.isArray(rows) && rows.length ? rows : [{}];
      visibleRows.forEach(row => addMarketCompetitorRow(row));
    }

    function marketSourcesTableHtml() {
      return '<div class="table-wrap"><table class="market-sources-table">' +
        '<thead><tr><th>المنافس</th><th>المصدر</th><th>الرابط</th><th>تاريخ البيانات</th>' +
        '<th>تاريخ الوصول</th><th>الموثوقية</th><th>ملاحظة</th><th></th></tr></thead><tbody></tbody></table></div>';
    }

    function selectMarketSourceTab(key) {
      const value = String(key || 'general');
      document.querySelectorAll('#marketSourcesTabs .market-source-tab').forEach(button => {
        const active = button.dataset.sourceTab === value;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('#marketSourcesPanels .market-source-panel').forEach(panel => {
        panel.hidden = panel.dataset.sourceTab !== value;
      });
    }

    function marketCompetitorDomRow(competitorId) {
      return Array.from(document.querySelectorAll('#marketCompetitorsTable tbody tr'))
        .find(row => row.dataset.competitorId === String(competitorId || ''));
    }

    function rewriteMarketCompetitorSourceUrl(competitor, previousUrl, nextUrl) {
      if (!competitor) return;
      const previous = String(previousUrl || '').trim().toLowerCase();
      const next = safeMarketUrl(nextUrl) ? String(nextUrl).trim() : '';
      const nextKey = next.toLowerCase();
      if (previous && previous !== nextKey) {
        let replacedInput = false;
        competitor.querySelectorAll('[data-source-url]').forEach(input => {
          if (String(input.value || '').trim().toLowerCase() !== previous) return;
          if (next && !replacedInput) {
            input.value = next;
            input.dataset.previousUrl = next;
            replacedInput = true;
          } else {
            input.closest('[data-source-url-row]')?.remove();
          }
        });
        const host = competitor.querySelector('[data-source-links]');
        let replaced = false;
        host?.querySelectorAll('a[href]').forEach(anchor => {
          const href = String(anchor.getAttribute('href') || '').trim();
          if (href.toLowerCase() !== previous) return;
          if (next && !replaced) {
            anchor.setAttribute('href', next);
            anchor.textContent = next;
            replaced = true;
          } else {
            anchor.remove();
          }
        });
        if (next && !replaced && host) {
          host.insertAdjacentHTML('beforeend', '<a href="' + escapeHtml(next) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(next) + '</a>');
        }
        let fieldSources = {};
        try { fieldSources = JSON.parse(competitor.dataset.fieldSources || '{}') || {}; } catch (error) { fieldSources = {}; }
        Object.keys(fieldSources).forEach(field => {
          const values = marketValueList(fieldSources[field])
            .map(item => String(item || '').trim().toLowerCase() === previous ? next : item)
            .filter(Boolean);
          if (values.length) fieldSources[field] = Array.from(new Set(values));
          else delete fieldSources[field];
        });
        competitor.dataset.fieldSources = JSON.stringify(fieldSources);
        const sourceInput = competitor.querySelector('[data-field="source"]');
        if (sourceInput && String(sourceInput.value || '').toLowerCase().includes(previous)) {
          sourceInput.value = String(sourceInput.value || '').replace(new RegExp(previousUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'ig'), next).trim();
        }
        if (String(competitor.dataset.logoSourceUrl || '').trim().toLowerCase() === previous) {
          competitor.dataset.logoSourceUrl = next;
        }
      }
    }

    function competitorSourceUrlValues(tr) {
      return Array.from(tr?.querySelectorAll('[data-source-url]') || [])
        .map(input => String(input.value || '').trim())
        .filter(value => /^https?:\/\//i.test(value) && safeMarketUrl(value));
    }

    function renderCompetitorSourceLinks(tr) {
      const host = tr?.querySelector('[data-source-links]');
      if (host) host.innerHTML = marketSourceLinksHtml({ source_urls: competitorSourceUrlValues(tr) });
    }

    function addCompetitorSourceUrlInput(tr, value = '') {
      const editor = tr?.querySelector('[data-source-url-editor]');
      if (!editor) return;
      const row = document.createElement('div');
      row.className = 'market-source-url-row';
      row.dataset.sourceUrlRow = '1';
      row.innerHTML = '<input data-source-url value="' + escapeHtml(value || '') + '" placeholder="https://..." inputmode="url">' +
        '<button type="button" class="btn ghost small" data-remove-source-url>حذف</button>';
      editor.insertBefore(row, editor.querySelector('[data-add-source-url]'));
      const input = row.querySelector('[data-source-url]');
      input.dataset.previousUrl = String(value || '').trim();
      input.addEventListener('input', () => {
        const previous = input.dataset.previousUrl || '';
        const next = String(input.value || '').trim();
        if (previous && previous.toLowerCase() !== next.toLowerCase()) {
          rewriteMarketCompetitorSourceUrl(tr, previous, next);
        }
        input.dataset.previousUrl = next;
        renderCompetitorSourceLinks(tr);
        persistMarketStudyFromDom();
      });
      row.querySelector('[data-remove-source-url]').addEventListener('click', () => {
        const current = String(input.value || '').trim();
        rewriteMarketCompetitorSourceUrl(tr, current, '');
        row.remove();
        renderCompetitorSourceLinks(tr);
        persistMarketStudyFromDom();
      });
      refreshDynamicI18n(row);
      return input;
    }

    function renderCompetitorSourceUrlEditor(tr, row = {}) {
      const editor = tr?.querySelector('[data-source-url-editor]');
      if (!editor) return;
      editor.innerHTML = '<div class="tenant-hint">الروابط المرجعية</div>' +
        '<button type="button" class="btn ghost small market-source-url-add" data-add-source-url>إضافة رابط مرجعي</button>';
      marketSourceUrls(row).forEach(url => addCompetitorSourceUrlInput(tr, url));
      editor.querySelector('[data-add-source-url]').addEventListener('click', () => {
        const input = addCompetitorSourceUrlInput(tr);
        input?.focus();
      });
      refreshDynamicI18n(editor);
    }

    function attachMarketSourceToCompetitor(sourceRow) {
      const competitor = marketCompetitorDomRow(sourceRow?.dataset?.competitorId);
      const url = String(sourceRow?.querySelector('[data-field="url"]')?.value || '').trim();
      const previousUrl = sourceRow?.dataset?.previousUrl || '';
      rewriteMarketCompetitorSourceUrl(competitor, previousUrl, url);
      sourceRow.dataset.previousUrl = safeMarketUrl(url) ? url : '';
    }

    function removeMarketSourcePermanently(sourceRow) {
      if (!sourceRow) return;
      const url = String(sourceRow.querySelector('[data-field="url"]')?.value || '').trim();
      const competitor = marketCompetitorDomRow(sourceRow.dataset.competitorId);
      rewriteMarketCompetitorSourceUrl(competitor, url, '');
      sourceRow.remove();
      persistMarketStudyFromDom();
    }

    function addMarketSourceRow(row = {}, targetBody) {
      const sourceRow = { ...(row || {}) };
      let tb = targetBody;
      if (!tb) {
        let panel = document.querySelector('#marketSourcesPanels .market-source-panel:not([hidden])')
          || document.querySelector('#marketSourcesPanels .market-source-panel');
        if (!panel) {
          renderMarketSources([]);
          panel = document.querySelector('#marketSourcesPanels .market-source-panel');
        }
        if (panel && !sourceRow.competitor_id && panel.dataset.competitorId) {
          sourceRow.competitor_id = panel.dataset.competitorId;
          sourceRow.competitor_name = panel.dataset.competitorName || '';
        }
        tb = panel?.querySelector('tbody');
      }
      if (!tb) return;
      const tr = document.createElement('tr');
      tr.dataset.sourceKind = sourceRow.source_kind || '';
      tr.dataset.competitorId = sourceRow.competitor_id || '';
      tr.dataset.previousUrl = sourceRow.url || '';
      tr.dataset.sourceFields = JSON.stringify(sourceRow.source_fields || {});
      const safeUrl = safeMarketUrl(sourceRow.url || '');
      sourceRow.reliability = sourceRow.reliability || marketOfficialSourceReliability(
        sourceRow.competitor_name, sourceRow.name, sourceRow.url);
      const link = safeUrl
        ? '<a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(sourceRow.url || '') + '</a>'
        : '';
      tr.innerHTML =
        '<td><input data-field="competitor_name" value="' + escapeHtml(sourceRow.competitor_name || '') + '" readonly></td>' +
        '<td><textarea data-field="name" rows="2">' + escapeHtml(sourceRow.name || '') + '</textarea></td>' +
        '<td><input data-field="url" value="' + escapeHtml(sourceRow.url || '') + '"><div data-source-link class="market-source-links">' + link + '</div></td>' +
        '<td><input data-field="data_date" value="' + escapeHtml(sourceRow.data_date || '') + '"></td>' +
        '<td><input data-field="accessed_at" value="' + escapeHtml(sourceRow.accessed_at || '') + '"></td>' +
        '<td><textarea data-field="reliability" rows="2">' + escapeHtml(sourceRow.reliability || '') + '</textarea></td>' +
        '<td><textarea data-field="note" rows="2">' + escapeHtml(sourceRow.note || '') + '</textarea></td>' +
        '<td><button type="button" class="btn ghost small" data-remove-source>حذف</button></td>';
      tb.appendChild(tr);
      tr.querySelector('[data-remove-source]').addEventListener('click', () => removeMarketSourcePermanently(tr));
      tr.querySelector('[data-field="url"]').addEventListener('input', () => {
        const value = tr.querySelector('[data-field="url"]')?.value || '';
        const current = safeMarketUrl(value);
        const host = tr.querySelector('[data-source-link]');
        if (host) host.innerHTML = current
          ? '<a href="' + escapeHtml(current) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(value) + '</a>'
          : '';
        attachMarketSourceToCompetitor(tr);
        const reliability = tr.querySelector('[data-field="reliability"]');
        if (reliability && !reliability.value) {
          reliability.value = marketOfficialSourceReliability(
            tr.querySelector('[data-field="competitor_name"]')?.value,
            tr.querySelector('[data-field="name"]')?.value,
            value);
        }
      });
      tr.querySelectorAll('input,textarea').forEach(input => input.addEventListener('input', persistMarketStudyFromDom));
      refreshDynamicI18n(tr);
    }

    function collectMarketSourceRows() {
      return Array.from(document.querySelectorAll('#marketSourcesPanels .market-sources-table tbody tr')).map(tr => {
        const read = (field) => tr.querySelector('[data-field="' + field + '"]')?.value || '';
        let source_fields = {};
        try {
          source_fields = JSON.parse(tr.dataset.sourceFields || '{}') || {};
        } catch (error) {
          source_fields = {};
        }
        return {
          competitor_id: tr.dataset.competitorId || '',
          competitor_name: read('competitor_name'),
          source_kind: tr.dataset.sourceKind || '',
          source_fields,
          name: read('name'),
          url: read('url'),
          data_date: read('data_date'),
          accessed_at: read('accessed_at'),
          reliability: read('reliability'),
          note: read('note')
        };
      }).filter(row => row.name || row.url);
    }

    function renderMarketSources(rows) {
      const tabs = document.getElementById('marketSourcesTabs');
      const panels = document.getElementById('marketSourcesPanels');
      if (!tabs || !panels) return;
      const currentKey = tabs.querySelector('.market-source-tab.active')?.dataset.sourceTab || '';
      const groups = new Map();
      (Array.isArray(rows) ? rows : []).forEach(row => {
        const key = row.competitor_id || row.competitor_name
          ? 'competitor|' + (row.competitor_id || row.competitor_name)
          : 'general';
        if (!groups.has(key)) {
          groups.set(key, {
            key,
            label: row.competitor_name || 'مصادر عامة',
            competitorId: row.competitor_id || '',
            competitorName: row.competitor_name || '',
            rows: []
          });
        }
        groups.get(key).rows.push(row);
      });
      if (!groups.size) groups.set('general', {
        key: 'general', label: 'مصادر عامة', competitorId: '', competitorName: '', rows: []
      });
      const selectedKey = groups.has(currentKey) ? currentKey : groups.keys().next().value;
      tabs.innerHTML = '';
      panels.innerHTML = '';
      groups.forEach(group => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'market-source-tab';
        button.dataset.sourceTab = group.key;
        button.setAttribute('role', 'tab');
        button.textContent = group.label;
        button.addEventListener('click', () => selectMarketSourceTab(group.key));
        tabs.appendChild(button);

        const panel = document.createElement('section');
        panel.className = 'market-source-panel';
        panel.dataset.sourceTab = group.key;
        panel.dataset.competitorId = group.competitorId;
        panel.dataset.competitorName = group.competitorName;
        panel.hidden = group.key !== selectedKey;
        panel.innerHTML = marketSourcesTableHtml();
        panels.appendChild(panel);
        const body = panel.querySelector('tbody');
        group.rows.forEach(row => addMarketSourceRow(row, body));
      });
      selectMarketSourceTab(selectedKey);
      refreshDynamicI18n(tabs);
      refreshDynamicI18n(panels);
    }

    function applyMarketStudyState(state) {
      const next = { ...emptyMarketStudyState(), ...(state || {}) };
      next.sources = mergeMarketSourceRows(
        Array.isArray(next.sources) ? next.sources : [],
        buildMarketCompetitorSourceRows(next.competitors)
      );
      const radius = document.getElementById('marketCompetitorRadius');
      const custom = document.getElementById('marketCompetitorRadiusCustom');
      const period = document.getElementById('marketDataPeriod');
      const from = document.getElementById('marketDataPeriodFrom');
      const to = document.getElementById('marketDataPeriodTo');
      if (radius) radius.value = (!next.competitor_radius || next.competitor_radius === 'auto') ? '10' : next.competitor_radius;
      if (custom) custom.value = next.competitor_radius_custom_km || '';
      if (period) period.value = next.data_period || '12m';
      if (from) from.value = next.data_period_from || '';
      if (to) to.value = next.data_period_to || '';
      renderMarketCompetitors(next.competitors || []);
      const summary = marketSummaryState(next.summary);
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
        const field = document.getElementById('marketSummary_' + item.key);
        if (field) field.value = summary[item.key] || '';
      });
      MARKET_STUDY_SWOT_SECTIONS.forEach(item => {
        const field = document.getElementById('marketSwot_' + item.key);
        if (field) field.value = (next.swot && next.swot[item.key]) || '';
      });
      const decision = document.getElementById('marketDecision');
      const disclaimer = document.getElementById('marketDisclaimer');
      if (decision) decision.value = next.decision || '';
      if (disclaimer) disclaimer.value = next.disclaimer || 'هذه دراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا.';
      next.one_block_summary = buildMarketStudyOneBlockSummary(next);
      const oneBlock = document.getElementById('marketStudyOneBlockSummary');
      if (oneBlock) oneBlock.value = next.one_block_summary;
      renderMarketSources(next.sources || []);
      const hidden = document.getElementById('marketStudyData');
      if (hidden) hidden.value = JSON.stringify(next);
      tenantProjectData.market_study_data = next;
      updateMarketStudyFieldVisibility();
      syncMarketLocationMirrors();
      refreshDynamicI18n(document.getElementById('section-market-study'));
    }

    function collectMarketStudyRequestPayload() {
      persistMarketStudyFromDom();
      const state = getMarketStudyState();
      const components = (typeof getComponentRowsData === 'function' ? getComponentRowsData() : []).map(row => ({
        name: row.name, useType: row.useType, units: row.units, unitArea: row.unitArea,
        builtArea: row.builtArea, revenueArea: row.revenueArea,
        investmentModel: row.investmentModel, leasable: row.leasable
      }));
      const financialModel = (typeof parseFinancialStudySnapshot === 'function'
        ? (parseFinancialStudySnapshot(document.getElementById('financialCalcData')?.value)
          || parseFinancialStudySnapshot(tenantProjectData.financial_calc_data)
          || parseFinancialStudySnapshot(tenantProjectData.financial_study_model))
        : null) || {};
      const liveFinancial = window.__financialProjection || {};
      const financial = {
        unitRevenueMode: financialModel.unitRevenueMode || liveFinancial?.modeFlags?.mode || '',
        projectCost: liveFinancial.projectCost ?? financialModel.projectCost ?? '',
        projectCostWithFinance: liveFinancial.projectCostWithFinance ?? financialModel.projectCostWithFinance ?? '',
        adjustedProjectCost: liveFinancial.adjustedProjectCost ?? financialModel.adjustedProjectCost ?? '',
        revenueY1: liveFinancial.revenueY1 ?? '',
        noiY1: liveFinancial.noiY1 ?? '',
        fullOccupancyRevenue: liveFinancial.fullOccupancyRevenue ?? '',
        saleRevenueTotal: liveFinancial.saleRevenueTotal ?? '',
        roi: liveFinancial.roi ?? financialModel.roi ?? '',
        projectIrr: liveFinancial.projectIrr ?? financialModel.projectIrr ?? '',
        equityIrr: liveFinancial.irr ?? financialModel.equityIrr ?? '',
        payback: liveFinancial.payback ?? financialModel.payback ?? '',
        equityPayback: liveFinancial.equityPayback ?? financialModel.equityPayback ?? '',
        totalEquityRequired: liveFinancial.totalEquityRequired ?? financialModel.totalEquityRequired ?? '',
        saleExitValue: liveFinancial.saleExitValue ?? '',
        operatingExitValue: liveFinancial.operatingExitValue ?? '',
        saleExitYear: liveFinancial.saleExitYear ?? financialModel.saleExitYear ?? '',
        operatingExitYear: liveFinancial.operatingExitYear ?? financialModel.operatingExitYear ?? '',
        developmentYears: liveFinancial.developmentYears ?? financialModel.developmentYears ?? '',
        salesStartYear: liveFinancial.salesStartYear ?? financialModel.salesStartYear ?? '',
        salesYears: liveFinancial.salesYears ?? financialModel.salesYears ?? '',
        operationYears: liveFinancial.operationYears ?? financialModel.operationYears ?? '',
        operationStartYear: liveFinancial.operationStartYear ?? '',
        totalYears: liveFinancial.totalYears ?? '',
        floorCount: financialModel.floorCount ?? '',
        coverageRate: financialModel.coverageRate ?? '',
        builtUpAreaAbove: financialModel.builtUpAreaAbove ?? '',
        basementArea: financialModel.basementArea ?? ''
      };
      const landmarkRows = Array.isArray(tenantProjectData.nearby_landmarks_data) ? tenantProjectData.nearby_landmarks_data : [];
      const nearbyLandmarks = landmarkRows.map(item => {
        const name = String(item?.name || item?.original_name || '').trim();
        const category = String(item?.category || item?.type || '').trim();
        return category ? name + ' (' + category + ')' : name;
      }).filter(Boolean).slice(0, 12);
      return {
        draftId: tenantProjectData.draftId || tenantProjectData.draft_id || '',
        projectName: tenantProjectData.project_name || '',
        projectType: selectedProjectTypeMains().join('، '),
        projectSubtype: selectedProjectSubtypes().join('، '),
        projectComponents: selectedProjectSubtypes().join('، ') || (components.map(item => item.name).filter(Boolean).join('، ')),
        projectLevel: document.querySelector('#tenantProjectForm [data-key="project_level"]')?.value || tenantProjectData.project_level || '',
        activityClass: document.querySelector('#tenantProjectForm [data-key="activity_class"]')?.value || tenantProjectData.activity_class || '',
        targetAudience: groupedAudienceSelection(),
        projectIdea: document.querySelector('#tenantProjectForm [data-key="project_idea"]')?.value || tenantProjectData.project_idea || '',
        city: document.querySelector('#tenantProjectForm [data-key="city"]')?.value || tenantProjectData.city || '',
        district: document.querySelector('#tenantProjectForm [data-key="district"]')?.value || tenantProjectData.district || '',
        locationAddress: tenantProjectData.location_address || '',
        locationLat: tenantProjectData.location_lat || '',
        locationLng: tenantProjectData.location_lng || '',
        landArea: tenantProjectData.approved_financial_area || tenantProjectData.croquis_land_area || '',
        allowedUses: tenantProjectData.allowed_uses || '',
        approvedFloorCount: tenantProjectData.approved_floor_count || financial.floorCount || '',
        approvedCoverageRatio: tenantProjectData.approved_coverage_ratio || financial.coverageRate || '',
        setbacks: tenantProjectData.setbacks || '',
        mainRoads: tenantProjectData.main_roads || '',
        nearbyLandmarks,
        financial,
        components,
        competitorRadius: state.competitor_radius,
        competitorRadiusCustomKm: state.competitor_radius_custom_km,
        dataPeriod: state.data_period,
        dataPeriodFrom: state.data_period_from,
        dataPeriodTo: state.data_period_to,
        competitors: state.competitors,
        currentSummary: state.summary,
        currentSources: state.sources,
        currentSwot: state.swot
      };
    }

    async function pollMarketStudyJob(jobId, onProgress) {
      const started = Date.now();
      let res = null;
      while (Date.now() - started < 12 * 60 * 1000) {
        await new Promise(resolve => setTimeout(resolve, 2500));
        res = await api('GET', '/api/market-study/jobs/' + encodeURIComponent(jobId));
        const status = String(res && res.status || '');
        if (typeof onProgress === 'function') onProgress(res);
        if (status === 'completed' || status === 'failed' || (res && res.failureReason)) break;
        if (!res || res.failureReason === 'job_not_found') break;
      }
      return res;
    }

    async function runMarketCompetitorsJob(mode) {
      const generateBtn = document.getElementById('marketGenerateCompetitorsBtn');
      const fillBtn = document.getElementById('marketFillCompetitorsBtn');
      const note = document.getElementById('marketCompetitorsNote');
      if (generateBtn) generateBtn.disabled = true;
      if (fillBtn) fillBtn.disabled = true;
      showLoader(
        mode === 'fill' ? 'إكمال بيانات المنافسين' : 'توليد المنافسين',
        'جاري البحث عن المنافسين من المصادر المعتمدة...',
        12
      );
      try {
        const payload = collectMarketStudyRequestPayload();
        payload.mode = mode;
        let res = await api('POST', '/api/market-study/competitors', payload);
        if (res && res.jobId && !Array.isArray(res.competitors)) {
          updateLoaderProgress(35, res.message || 'بدأت المهمة في الخلفية...');
          res = await pollMarketStudyJob(res.jobId, job => {
            updateLoaderProgress(job && job.status === 'running' ? 60 : 40, (job && job.message) || 'جاري البحث...');
          });
        }
        if (!res || !res.success) {
          if (note) note.textContent = (res && (res.error || res.providerError)) || 'تعذر تحديث المنافسين.';
          toast((res && res.error) || 'تعذر تحديث المنافسين.');
          return;
        }
        const state = getMarketStudyState();
        state.competitors = res.competitors || state.competitors;
        state.sources = mergeMarketSourceRows(
          state.sources,
          res.sources || buildMarketCompetitorSourceRows(state.competitors)
        );
        applyMarketStudyState(state);
        persistMarketStudyFromDom();
        const extra = res.expansionNote || res.notes || '';
        const conflictCount = Array.isArray(res.conflictWarnings) ? res.conflictWarnings.length : 0;
        if (note) {
          note.textContent = (mode === 'fill'
            ? ('أُكملت بيانات ' + (res.updated || 0) + ' منافس')
            : ('تم استبدال الجدول بـ ' + ((res.competitors || []).length) + ' منافس')) +
            (conflictCount ? ' — تم الإبقاء على ' + conflictCount + ' قيمة حالية متعارضة' : '') +
            (res.searchVerified === false ? ' — لم يعمل البحث في الويب؛ أُزيلت الروابط غير الموثقة من الصفوف' : '') +
            ((res.outOfRadiusCount || 0) ? ' — ' + res.outOfRadiusCount + ' منافس خارج النطاق المحدد' : '') +
            (extra ? ' — ' + extra : '');
        }
        toast(mode === 'fill' ? 'تم إكمال بيانات المنافسين دون حذف الصفوف' : 'تم استبدال جدول المنافسين بالنتيجة الجديدة');
        updateLoaderProgress(100, 'اكتمل تحديث المنافسين');
      } catch (error) {
        toast(error.message || 'تعذر تحديث المنافسين');
      } finally {
        hideLoader();
        if (generateBtn) generateBtn.disabled = false;
        if (fillBtn) fillBtn.disabled = false;
      }
    }

    function renderMarketSummaryCompare(current, incoming, currentSwot, incomingSwot) {
      const host = document.getElementById('marketSummaryCompare');
      if (!host) return;
      host.hidden = false;
      const currentOneBlock = arguments[4] || '';
      const incomingOneBlock = arguments[5] || '';
      const swotBlocks = values => MARKET_STUDY_SWOT_SECTIONS.map(item =>
        (item.label + '\n' + ((values && values[item.key]) || '')).trim()
      ).join('\n\n');
      const currentText = [
        marketSummaryAnalysisText(current),
        currentOneBlock ? ('ملخص دراسة سوق العمل\n' + currentOneBlock) : '',
        'تحليل SWOT',
        swotBlocks(currentSwot)
      ].filter(part => String(part || '').trim()).join('\n\n');
      const incomingText = [
        marketSummaryAnalysisText(incoming),
        incomingOneBlock ? ('ملخص دراسة سوق العمل\n' + incomingOneBlock) : '',
        'تحليل SWOT',
        swotBlocks(incomingSwot)
      ].filter(part => String(part || '').trim()).join('\n\n');
      host.innerHTML =
        '<div class="summary-compare">' +
        '<div><label>النسخة الحالية</label><textarea rows="12" readonly>' + currentText.replace(/</g, '&lt;') + '</textarea></div>' +
        '<div><label>النسخة الجديدة</label><textarea rows="12" readonly>' + incomingText.replace(/</g, '&lt;') + '</textarea></div>' +
        '</div>' +
        '<div class="market-actions">' +
        '<button type="button" class="btn primary" id="marketAcceptSummaryBtn">استبدال بالنسخة الجديدة</button>' +
        '<button type="button" class="btn ghost" id="marketKeepSummaryBtn">الإبقاء على الحالية</button>' +
        '</div>';
      document.getElementById('marketAcceptSummaryBtn')?.addEventListener('click', () => {
        if (!marketSummaryPending) return;
        const state = getMarketStudyState();
        state.summary = marketSummaryPending.summary;
        state.swot = marketSummaryPending.swot || state.swot;
        state.sources = mergeMarketSourceRows(
          marketSummaryPending.sources,
          buildMarketCompetitorSourceRows(state.competitors)
        );
        state.decision = marketSummaryPending.decision;
        state.disclaimer = marketSummaryPending.disclaimer;
        state.one_block_summary = marketSummaryPending.oneBlockSummary || '';
        applyMarketStudyState(state);
        persistMarketStudyFromDom();
        marketSummaryPending = null;
        host.hidden = true;
        host.innerHTML = '';
        toast('تم استبدال الملخص والمصادر بالنسخة الجديدة');
      });
      document.getElementById('marketKeepSummaryBtn')?.addEventListener('click', () => {
        marketSummaryPending = null;
        host.hidden = true;
        host.innerHTML = '';
        toast('تم الإبقاء على الملخص الحالي');
      });
    }

    async function runMarketSummaryJob() {
      const btn = document.getElementById('marketGenerateSummaryBtn');
      const fail = document.getElementById('marketSummaryFailure');
      if (btn) btn.disabled = true;
      if (fail) fail.textContent = '';
      showLoader('توليد ملخص السوق', 'جاري البحث في المصادر الرسمية وكتابة الملخص التنفيذي...', 12);
      try {
        const payload = collectMarketStudyRequestPayload();
        const currentState = getMarketStudyState();
        const currentSummary = marketSummaryState(currentState.summary);
        const currentSwot = { ...(currentState.swot || {}) };
        const currentOneBlock = String(currentState.one_block_summary || '').trim();
        let res = await api('POST', '/api/market-study/summary', payload);
        if (res && res.jobId && !res.summary) {
          updateLoaderProgress(35, res.message || 'بدأت المهمة في الخلفية...');
          res = await pollMarketStudyJob(res.jobId, job => {
            updateLoaderProgress(job && job.status === 'running' ? 65 : 45, (job && job.message) || 'جاري إعداد الملخص...');
          });
        }
        if (!res || !res.success || !res.summary) {
          const message = (res && (res.error || res.providerError)) || 'تعذر توليد الملخص. لم يُستبدل النص الحالي.';
          if (fail) fail.textContent = message;
          toast(message);
          return;
        }
        const hasCurrent = marketSummaryHasContent(currentSummary)
          || currentOneBlock
          || Object.values(currentSwot).some(value => String(value || '').trim());
        const unverifiedNote = res.searchVerified === false
          ? ' — مصادر الملخص غير موثقة: لم يعمل البحث في الويب أثناء التوليد'
          : '';
        marketSummaryPending = {
          summary: res.summary,
          swot: res.swot || {},
          sources: res.sources || [],
          decision: res.decision || '',
          disclaimer: res.disclaimer || '',
          oneBlockSummary: res.one_block_summary || res.oneBlockSummary || ''
        };
        if (hasCurrent) {
          renderMarketSummaryCompare(currentSummary, res.summary, currentSwot, res.swot || {}, currentOneBlock, marketSummaryPending.oneBlockSummary);
          toast('النسختان ظاهرتان. اختر الاستبدال أو الإبقاء.' + unverifiedNote);
        } else {
          const state = getMarketStudyState();
          state.summary = res.summary;
          state.swot = res.swot || {};
          state.sources = mergeMarketSourceRows(
            res.sources || [],
            buildMarketCompetitorSourceRows(state.competitors)
          );
          state.decision = res.decision || '';
          state.disclaimer = res.disclaimer || state.disclaimer;
          state.one_block_summary = res.one_block_summary || res.oneBlockSummary || '';
          applyMarketStudyState(state);
          persistMarketStudyFromDom();
          toast('تم توليد ملخص السوق وتحليل SWOT' + unverifiedNote);
        }
        updateLoaderProgress(100, 'اكتمل ملخص السوق');
      } catch (error) {
        if (fail) fail.textContent = error.message || 'تعذر توليد الملخص';
        toast(error.message || 'تعذر توليد الملخص');
      } finally {
        hideLoader();
        if (btn) btn.disabled = false;
      }
    }