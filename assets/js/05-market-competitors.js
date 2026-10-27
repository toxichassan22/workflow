/* 05-market-competitors.js - index.html lines 11653-12627, shared global scope, classic scripts in order */

    // Benchmark axes mirror market_study.project_competitor_axes — each
    // revenue-bearing component use needs COMPETITOR_MIN_DIRECT competitors
    // of its own, tagged in the row's benchmarks field.
    const MARKET_USE_AXIS_DEFS = {
      residential: { label: 'سكني', labelEn: 'Residential' },
      office: { label: 'مكاتب', labelEn: 'Offices' },
      retail: { label: 'تجزئة ومحلات', labelEn: 'Retail' },
      hospitality: { label: 'فندقي', labelEn: 'Hospitality' },
      industrial: { label: 'صناعي', labelEn: 'Industrial' },
      logistics: { label: 'لوجستي', labelEn: 'Logistics' },
      entertainment: { label: 'ترفيهي', labelEn: 'Entertainment' },
      commercial: { label: 'تجاري', labelEn: 'Commercial' },
      other: { label: 'أخرى', labelEn: 'Other' },
      general: { label: 'عام', labelEn: 'General' }
    };
    const MARKET_NON_COMPETING_USES = ['parking', 'services', 'openArea', 'basement'];
    const MARKET_SUBTYPE_AXIS_KEYS = {
      'سكني': 'residential', 'مكاتب': 'office',
      'تجزئة ومحلات': 'retail', 'مطاعم ومقاهي': 'retail', 'مركز تجاري': 'retail',
      'فندق': 'hospitality', 'شقق مخدومة': 'hospitality', 'منتجع': 'hospitality',
      'مساكن فندقية': 'hospitality',
      'مصنع': 'industrial', 'مجمع صناعي': 'industrial',
      'مستودعات': 'logistics', 'مركز لوجستي': 'logistics'
    };
    const MARKET_MAIN_AXIS_KEYS = {
      'سكني': 'residential', 'تجاري': 'commercial', 'فندقي': 'hospitality',
      'صناعي ولوجستي': 'industrial'
    };

    function marketBenchmarkAxes() {
      const selectedComparisons = typeof collectMarketComparisonTypes === 'function'
        ? collectMarketComparisonTypes() : [];
      if (selectedComparisons.length) {
        return selectedComparisons.map(item => {
          const hotel = item.type === 'hotel';
          const typeLabel = item.type === 'hotel' ? 'فندقي' : item.type === 'residential' ? 'سكني' : 'تجاري';
          const operationLabel = item.operation === 'sale' ? 'بيع' : item.operation === 'rent' ? 'إيجار' : '';
          const label = hotel ? typeLabel : typeLabel + ' - ' + operationLabel;
          const labelEn = hotel ? 'Hotel' : item.type + ' ' + (item.operation === 'sale' ? 'for sale' : 'for rent');
          return { key: hotel ? 'hotel' : item.type + ':' + item.operation, base: item.type,
            type: item.type, operation: item.operation,
            label, labelEn, names: [] };
        });
      }
      const axes = [];
      const add = (key, base, label, name) => {
        const def = MARKET_USE_AXIS_DEFS[base];
        if (!def) return;
        const existing = axes.find(axis => axis.key === key);
        if (existing) {
          if (name && !existing.names.includes(name)) existing.names.push(name);
          return;
        }
        axes.push({ key, label: label || def.label, labelEn: base === 'other' ? (label || def.labelEn) : def.labelEn, names: name ? [name] : [] });
      };
      const components = typeof getComponentRowsData === 'function' ? getComponentRowsData() : [];
      components.forEach(component => {
        if (String(component.investmentModel || '') === 'nonRevenue') return;
        const use = String(component.useType || '').trim();
        if (!use || MARKET_NON_COMPETING_USES.includes(use)) return;
        const name = String(component.name || '').trim();
        if (MARKET_USE_AXIS_DEFS[use]) add(use, use, '', name);
        else add('other:' + (name || 'أخرى'), 'other', name || 'أخرى', name);
      });
      if (!axes.length) {
        (typeof selectedProjectSubtypes === 'function' ? selectedProjectSubtypes() : []).forEach(subtype => {
          const key = MARKET_SUBTYPE_AXIS_KEYS[subtype];
          if (key) add(key, key, '', subtype);
        });
      }
      if (!axes.length) {
        (typeof selectedProjectTypeMains === 'function' ? selectedProjectTypeMains() : []).forEach(main => {
          const key = MARKET_MAIN_AXIS_KEYS[main];
          if (key) add(key, key, '', main);
        });
      }
      if (!axes.length) add('general', 'general', '', '');
      return axes;
    }

    function marketBenchmarkAxisLabel(axis) {
      return marketProjectIsEnglish() ? (axis.labelEn || axis.label) : axis.label;
    }

    function marketBenchmarkValues(row = {}) {
      const raw = row.benchmarks || row.benchmark_axes || row.measured_against || row['يُقاس على'] || [];
      const list = Array.isArray(raw) ? raw : String(raw).split(/[,،;|]/);
      return list.map(value => String(value || '').trim()).filter(Boolean);
    }

    function syncMarketBenchmarksColumn() {
      const show = marketBenchmarkAxes().length > 1;
      document.querySelectorAll('#marketCompetitorsTable [data-benchmarks-col], #marketCompetitorsTable [data-field="benchmarks_cell"]').forEach(el => {
        el.style.visibility = show ? 'visible' : 'hidden';
      });
    }

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
      const faviconHost = String(tr.dataset.logoFaviconHost || '').trim();
      const lowResNote = (hasLogo && !busy && tr.dataset.logoLowRes === '1')
        ? '<div style="color:var(--muted);font-size:11px;margin-top:4px">'
            + WFT('competitors.logo_low_res', 'أيقونة {host} (دقة منخفضة)', { host: escapeHtml(faviconHost || 'الموقع الرسمي') }) + '</div>'
        : '';
      const actions = hasLogo
        ? '<div class="market-logo-actions"><button type="button" class="btn ghost small" data-preview-competitor-logo>تكبير</button><button type="button" class="btn ghost small" data-remove-competitor-logo>حذف</button></div>'
        : '';
      cell.innerHTML = (path ? '<img src="' + escapeHtml(path) + '" alt="شعار المنافس" style="width:72px;height:54px;object-fit:contain;background:#fff;border:1px solid var(--line);border-radius:8px;margin-bottom:5px">' : '<div style="height:54px;display:flex;align-items:center;justify-content:center;color:var(--muted)">' + (busy ? busyLabel : 'لا يوجد') + '</div>') +
        progress + actions +
        '<input type="file" accept="image/png,image/jpeg,image/webp" data-competitor-logo style="width:100%;font-size:11px"' + (busy ? ' disabled' : '') + '>' +
        (warning ? '<div style="color:var(--muted);font-size:11px;margin-top:4px">' + escapeHtml(warning) + '</div>' : '') + lowResNote;
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

    function addMarketCompetitorRow(row = {}, deferTypeTabs = false) {
      const tb = document.querySelector('#marketCompetitorsTable tbody');
      if (!tb) return;
      if (MARKET_COMPETITOR_ACTIVE_TYPE_TAB !== 'all' && !row.project_type && !row.projectType) {
        row = { ...row, project_type: marketCompetitorTypeSelectValue(MARKET_COMPETITOR_ACTIVE_TYPE_TAB) };
      }
      const tr = document.createElement('tr');
      tr.dataset.competitorId = row.id || ('c_' + Date.now() + '_' + Math.random().toString(16).slice(2));
      tr.dataset.classification = row.classification || '';
      tr.dataset.rowSource = row.row_source || 'manual';
      tr.dataset.priceCurrency = row.price_currency || row.currency || 'SAR';
      tr.dataset.fieldSources = JSON.stringify(row.field_sources || row.fieldSources || {});
      tr.dataset.sourceUrlManual = row.source_url_manual || row.sourceUrlManual ? '1' : '';
      tr.dataset.logoFileId = row.logo_file_id || row.logoFileId || '';
      tr.dataset.logoPath = row.logo_path || row.logoPath || '';
      tr.dataset.logoUrl = row.logo_url || row.logoUrl || '';
      tr.dataset.logoSourceUrl = row.logo_source_url || row.logoSourceUrl || '';
      tr.dataset.conflictWarnings = JSON.stringify(row.conflict_warnings || row.conflictWarnings || []);
      tr.dataset.logoImportWarning = row.logo_import_warning || row.logoImportWarning || '';
      tr.dataset.logoLowRes = row.logo_low_res || row.logoLowRes ? '1' : '';
      tr.dataset.logoFaviconHost = row.logo_favicon_host || row.logoFaviconHost || '';
      tr.dataset.notes = row.notes || row.note || '';
      tr.dataset.district = row.district || row.neighborhood || '';
      tr.dataset.city = row.city || row.location_city || '';
      tr.dataset.distanceKm = row.distance_km || row.distanceKm || '';
      tr.dataset.lat = row.lat || '';
      tr.dataset.lng = row.lng || '';
      tr.dataset.dataDate = row.data_date || row.dataDate || '';
      tr.dataset.deadSourceUrls = JSON.stringify(row.dead_source_urls || row.deadSourceUrls || []);
      tr.dataset.outOfRadius = row.out_of_radius || row.outOfRadius ? '1' : '';
      tr.dataset.sourcesUnverified = row.sources_unverified || row.sourcesUnverified ? '1' : '';
      tr.dataset.noSearchEvidence = row.no_search_evidence || row.noSearchEvidence ? '1' : '';
      tr.dataset.verifyState = row.verify_state || row.verifyState || '';
      tr.dataset.verifyProviderError = row.verify_provider_error || row.verifyProviderError || '';
      tr.dataset.projectType = row.project_type || row.projectType || '';
      const areaCache = row.area_cache || row.areaCache || {};
      tr.dataset.areaFixed = cleanMarketNumber(row.area_sqm || row.areaSqm || areaCache.area_sqm || '');
      tr.dataset.areaFrom = cleanMarketNumber(row.area_from || row.areaFrom || areaCache.area_from || '');
      tr.dataset.areaTo = cleanMarketNumber(row.area_to || row.areaTo || areaCache.area_to || '');
      tr.dataset.priceCache = JSON.stringify(row.price_cache || row.priceCache || {});
      const operation = inferCompetitorOperation(row);
      const priceType = inferCompetitorPriceType(row);
      const priceTypes = marketPriceTypesForOperation(operation);
      tr.dataset.previousPriceType = priceType;
      const benchAxes = marketBenchmarkAxes();
      const benchSelected = marketBenchmarkValues(row);
      const benchmarksHtml = marketBenchmarkPickerHtml(benchAxes, benchSelected);
      let warnings = [];
      try { warnings = JSON.parse(tr.dataset.conflictWarnings || '[]') || []; } catch (error) { warnings = []; }
      const warningsHtml = warnings.map(item => {
        const label = marketSourceFieldLabel(item.field || '');
        const link = safeMarketUrl(item.source_url) ? ' <a href="' + escapeHtml(safeMarketUrl(item.source_url)) + '" target="_blank" rel="noopener noreferrer">المصدر الرسمي</a>' : '';
        if (item.field === 'distance_km') {
          return '<div style="color:#92400e;margin-top:4px">' + escapeHtml(WFT('market.conflict_vs', '{src}: {incoming} مقابل {existing}', {
            src: String(item.source || WFT('market.outside_scope', 'خارج نطاق المنافسين')),
            incoming: String(item.incoming || ''),
            existing: String(item.existing || '')
          })) + '</div>';
        }
        return '<div style="color:#92400e;margin-top:4px">' + escapeHtml(WFT('market.conflict_kept', 'تعارض في {label}: تم الإبقاء على القيمة الحالية.', { label: label })) + link + '</div>';
      }).join('') +
      (tr.dataset.sourcesUnverified
        ? '<div style="color:#92400e;margin-top:4px">روابط هذا الصف لم تُسترجع عبر البحث — معروضة للمراجعة وغير موثقة.</div>'
        : '') +
      (tr.dataset.noSearchEvidence
        ? '<div style="color:#b91c1c;margin-top:4px">لم يظهر اسم هذا المنافس في أي صفحة من نتائج البحث — الاسم غير موثق.</div>'
        : '') +
      marketCompetitorVerificationWarningHtml(tr);
      const typeValue = marketTranslateCompetitorValue(row.project_type);
      tr.innerHTML =
        '<td><textarea data-field="name" rows="2">' + escapeHtml(row.name || '') + '</textarea></td>' +
        '<td data-field="logo_cell"></td>' +
        '<td><select data-field="project_type">' + marketSelectHtml(marketProjectIsEnglish() ? MARKET_COMPETITOR_PROJECT_TYPES_EN : MARKET_PROJECT_TYPES, marketTranslateCompetitorValue(row.project_type)) + '</select></td>' +
        '<td><select data-field="classification">' + marketSelectHtml(marketProjectIsEnglish() ? MARKET_COMPETITOR_CLASSIFICATIONS_EN : MARKET_COMPETITOR_CLASSIFICATIONS, marketTranslateCompetitorValue(row.classification)) + '</select></td>' +
        '<td data-field="benchmarks_cell">' + benchmarksHtml + '</td>' +
        '<td data-field="area_cell"></td>' +
        '<td><select data-field="status">' + marketSelectHtml(marketProjectIsEnglish() ? MARKET_COMPETITOR_STATUSES_EN : MARKET_COMPETITOR_STATUSES, marketTranslateCompetitorValue(row.status)) + '</select></td>' +
        '<td><textarea data-field="source" rows="2" placeholder="المصدر">' + escapeHtml(row.source || '') + '</textarea>' +
        '<div data-source-url-editor class="market-source-url-editor"></div>' +
        '<div data-source-links class="market-source-links"></div><div data-conflict-warnings>' + warningsHtml + '</div></td>' +
        '<td><select data-field="operation_type">' + marketSelectHtml(marketProjectIsEnglish() ? MARKET_COMPETITOR_OPERATIONS_EN : MARKET_COMPETITOR_OPERATIONS, operation) + '</select></td>' +
        '<td><select data-field="price_type">' + marketSelectHtml(priceTypes, priceType) + '</select></td>' +
        '<td data-field="price_cell"></td>' +
        '<td><button type="button" class="btn ghost small" data-remove-competitor>حذف</button></td>';
      tb.appendChild(tr);
      tr.dataset.projectType = String(row.project_type || row.projectType || tr.querySelector('[data-field="project_type"]')?.value || '');
      renderCompetitorLogoCell(tr);
      renderCompetitorSourceUrlEditor(tr, row);
      renderCompetitorSourceLinks(tr);
      renderCompetitorAreaInputs(tr, row);
      renderCompetitorPriceInputs(tr, row);
      tr.querySelector('[data-field="project_type"]')?.addEventListener('change', event => {
        const value = String(event.target.value || '');
        tr.dataset.projectType = value;
        syncMarketCompetitorTypeTabs();
        persistMarketStudyFromDom();
      });
      tr.querySelector('[data-field="operation_type"]').addEventListener('change', () => {
        cacheCompetitorPriceInputs(tr, tr.dataset.previousPriceType);
        const nextOp = tr.querySelector('[data-field="operation_type"]').value;
        const options = marketPriceTypesForOperation(nextOp);
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
        syncMarketCompetitorTypeTabs();
        persistMarketStudyFromDom();
      });
      tr.querySelectorAll('input,select,textarea').forEach(input => input.addEventListener('input', persistMarketStudyFromDom));
      tr.querySelectorAll('[data-market-benchmark-option]').forEach(input => input.addEventListener('change', () => {
        refreshMarketBenchmarkPicker(tr);
        persistMarketStudyFromDom();
      }));
      syncMarketBenchmarksColumn();
      refreshDynamicI18n(tr);
      if (!deferTypeTabs) syncMarketCompetitorTypeTabs();
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
      const rowCurrency = marketTranslateCompetitorValue(String(tr.dataset.priceCurrency || 'SAR'));
      const currencyLabel = rowCurrency === 'SAR' ? 'ر.س' : rowCurrency;
      const priceFromPlaceholder = 'من (' + currencyLabel + ')';
      const priceToPlaceholder = 'إلى (' + currencyLabel + ')';
      const priceValuePlaceholder = 'القيمة (' + currencyLabel + ')';
      if (competitorPriceIsRange(priceType)) {
        cell.innerHTML = '<input data-field="price_from" data-currency="' + escapeHtml(rowCurrency) + '" value="' + escapeHtml(priceFrom) + '" placeholder="' + escapeHtml(priceFromPlaceholder) + '" inputmode="decimal">' +
          '<input data-field="price_to" data-currency="' + escapeHtml(rowCurrency) + '" value="' + escapeHtml(priceTo) + '" placeholder="' + escapeHtml(priceToPlaceholder) + '" style="margin-top:6px" inputmode="decimal">';
      } else {
        cell.innerHTML = '<input data-field="price_value" data-currency="' + escapeHtml(rowCurrency) + '" value="' + escapeHtml(priceValue) + '" placeholder="' + escapeHtml(priceValuePlaceholder) + '" inputmode="decimal">';
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
        benchmarks: marketSelectedBenchmarkValues(tr),
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
        source_url_manual: tr.dataset.sourceUrlManual === '1',
        field_sources,
        district: tr.dataset.district || '',
        city: tr.dataset.city || '',
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
      if (tr.dataset.noSearchEvidence) row.no_search_evidence = true;
      if (tr.dataset.verifyState) row.verify_state = tr.dataset.verifyState;
      if (tr.dataset.verifyProviderError) row.verify_provider_error = tr.dataset.verifyProviderError;
      if (tr.dataset.logoLowRes) row.logo_low_res = true;
      if (tr.dataset.logoFaviconHost) row.logo_favicon_host = tr.dataset.logoFaviconHost;
      return row;
    }

    function collectMarketCompetitorRows() {
      return Array.from(document.querySelectorAll('#marketCompetitorsTable tbody tr')).map(collectOneCompetitorRow);
    }

    function renderMarketCompetitors(rows) {
      const tb = document.querySelector('#marketCompetitorsTable tbody');
      if (!tb) return;
      tb.innerHTML = '';
      const visibleRows = Array.isArray(rows) && rows.length ? rows : [{}];
      visibleRows.forEach(row => addMarketCompetitorRow(row, true));
      syncMarketCompetitorTypeTabs();
    }

    function applyMarketStudyState(state) {
      const next = { ...emptyMarketStudyState(), ...(state || {}) };
      next.sources = mergeMarketSourceRows(
        Array.isArray(next.sources) ? next.sources : [], []);
      const scopeMode = document.getElementById('marketCompetitorScopeMode');
      const competitorRadius = document.getElementById('marketCompetitorRadius');
      const competitorRadiusCustom = document.getElementById('marketCompetitorRadiusCustomKm');
      const period = document.getElementById('marketDataPeriod');
      const from = document.getElementById('marketDataPeriodFrom');
      const to = document.getElementById('marketDataPeriodTo');
      if (scopeMode) {
        const mode = next.competitor_scope?.mode;
        scopeMode.value = ['city', 'distance'].includes(mode) ? mode : 'district';
      }
      if (competitorRadius) {
        competitorRadius.value = String(next.competitor_scope?.radius
          || next.competitor_scope?.radius_km || '10');
      }
      if (competitorRadiusCustom) {
        competitorRadiusCustom.value = String(next.competitor_scope?.radius_custom_km
          || next.competitor_scope?.radiusCustomKm || '');
      }
      if (typeof renderMarketCompetitorDistricts === 'function') {
        renderMarketCompetitorDistricts(next.competitor_scope?.districts
          || next.competitor_scope?.district_list || []);
      }
      if (typeof renderMarketUnitTypes === 'function') {
        renderMarketUnitTypes(next.competitor_scope?.unit_types
          || next.competitor_scope?.unitTypes || []);
      }
      if (typeof renderMarketComparisonTypes === 'function') {
        renderMarketComparisonTypes(Array.isArray(next.comparison_types) ? next.comparison_types : []);
      }
      if (period) period.value = next.data_period || '12m';
      if (from) from.value = next.data_period_from || '';
      if (to) to.value = next.data_period_to || '';
      const summaryPeriod = document.getElementById('marketSummaryPeriod');
      const summaryFrom = document.getElementById('marketSummaryPeriodFrom');
      const summaryTo = document.getElementById('marketSummaryPeriodTo');
      if (summaryPeriod) {
        summaryPeriod.value = next.summary_period || next.data_period || '12m';
      }
      if (summaryFrom) {
        summaryFrom.value = next.summary_period_from
          || (next.summary_period ? '' : (next.data_period_from || ''));
      }
      if (summaryTo) {
        summaryTo.value = next.summary_period_to
          || (next.summary_period ? '' : (next.data_period_to || ''));
      }
      const researchDepth = document.getElementById('marketSummaryResearchDepth');
      if (researchDepth) researchDepth.value = next.summary_research_depth || 'full';
      renderMarketCompetitors(next.competitors || []);
      if (typeof renderMarketTransactionBenchmarks === 'function') {
        renderMarketTransactionBenchmarks(next.transaction_benchmarks);
      }
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
      if (typeof renderMarketSummaryScope === 'function') renderMarketSummaryScope(next.summary_scope);
      updateMarketStudyFieldVisibility();
      next.one_block_summary = buildMarketStudyOneBlockSummary(next);
      const oneBlock = document.getElementById('marketStudyOneBlockSummary');
      if (oneBlock) oneBlock.value = next.one_block_summary;
      renderMarketSources(next.sources || []);
      const hidden = document.getElementById('marketStudyData');
      if (hidden) hidden.value = JSON.stringify(next);
      tenantProjectData.market_study_data = next;
      updateMarketStudyFieldVisibility();
      syncMarketLocationMirrors();
      if (typeof renderMarketSummaryChat === 'function') renderMarketSummaryChat();
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
        project_language: tenantProjectData.project_language || '',
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
        approvedFloorAreaRatio: tenantProjectData.approved_floor_area_ratio || '',
        setbacks: tenantProjectData.setbacks || '',
        mainRoads: tenantProjectData.main_roads || '',
        nearbyLandmarks,
        financial,
        components,
        competitorScope: state.competitor_scope,
        comparisonTypes: state.comparison_types,
        summaryScope: state.summary_scope,
        dataPeriod: state.data_period,
        dataPeriodFrom: state.data_period_from,
        dataPeriodTo: state.data_period_to,
        summaryPeriod: state.summary_period,
        summaryPeriodFrom: state.summary_period_from,
        summaryPeriodTo: state.summary_period_to,
        summaryResearchDepth: state.summary_research_depth,
        competitors: state.competitors,
        currentSummary: state.summary,
        currentSources: state.sources,
        currentSwot: state.swot,
        // The market study is the one AI surface that sees the whole project:
        // a live data-key snapshot over tenantProjectData (files skipped —
        // build_project_facts renders it into the bounded facts brief).
        projectData: collectMarketProjectData()
      };
    }
