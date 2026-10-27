/* Competitor table controls: compact benchmark selection and project-type tabs. */

    const MARKET_COMPETITOR_TYPE_TAB_DEFS = [
      { key: 'residential', label: 'سكني', labelEn: 'Residential' },
      { key: 'commercial', label: 'تجاري', labelEn: 'Commercial' },
      { key: 'hotel', label: 'فندقي', labelEn: 'Hotel' },
      { key: 'industrial', label: 'صناعي ولوجستي', labelEn: 'Industrial and logistics' },
      { key: 'other', label: 'أخرى', labelEn: 'Other' }
    ];
    let MARKET_COMPETITOR_ACTIVE_TYPE_TAB = 'all';

    function marketCompetitorTypeKey(value) {
      const text = String(value || '').trim().toLowerCase();
      if (/فندقي|فندق|ضيافة|hospitality|hotel|resort/.test(text)) return 'hotel';
      if (/سكن|شقق|residential|apartment|housing/.test(text)) return 'residential';
      if (/تجار|مكتب|تجزئة|محل|مطعم|مقهى|commercial|retail|office/.test(text)) return 'commercial';
      if (/صناع|لوجست|مستودع|مصنع|industrial|logistic|warehouse|factory/.test(text)) return 'industrial';
      return 'other';
    }

    function marketCompetitorTypeSelectValue(typeKey) {
      const arabic = {
        residential: 'سكني', commercial: 'تجاري', hotel: 'فندقي',
        industrial: 'صناعي ولوجستي', other: 'أخرى'
      }[typeKey] || '';
      return marketProjectIsEnglish() ? (MARKET_AR_TO_EN_COMPETITOR[arabic] || arabic) : arabic;
    }

    function marketCompetitorTypeTabsModel(rows, comparisons) {
      const types = new Set();
      (Array.isArray(rows) ? rows : []).forEach(row => {
        const value = row && (row.project_type || row.projectType || row.type);
        if (String(value || '').trim()) types.add(marketCompetitorTypeKey(value));
      });
      (Array.isArray(comparisons) ? comparisons : []).forEach(item => {
        const value = item && (item.type || item.project_type);
        if (String(value || '').trim()) types.add(marketCompetitorTypeKey(value));
      });
      return MARKET_COMPETITOR_TYPE_TAB_DEFS.filter(item => types.has(item.key));
    }

    function marketCompetitorRowsForType(rows, typeKey) {
      const list = Array.isArray(rows) ? rows : [];
      if (!typeKey || typeKey === 'all') return list;
      return list.filter(row => marketCompetitorTypeKey(
        row && (row.project_type || row.projectType || row.type || row.dataset?.projectType)) === typeKey);
    }

    function syncMarketCompetitorTypeTabs() {
      const host = document.getElementById('marketCompetitorTypeTabs');
      const domRows = Array.from(document.querySelectorAll('#marketCompetitorsTable tbody tr'));
      if (!host) return;
      const rowData = domRows.map(row => ({ project_type: row.dataset.projectType || '' }));
      const comparisons = typeof collectMarketComparisonTypes === 'function'
        ? collectMarketComparisonTypes() : [];
      const types = marketCompetitorTypeTabsModel(rowData, comparisons);
      if (types.length < 2) {
        host.hidden = true;
        MARKET_COMPETITOR_ACTIVE_TYPE_TAB = 'all';
        domRows.forEach(row => { row.hidden = false; });
        return;
      }
      host.hidden = false;
      if (MARKET_COMPETITOR_ACTIVE_TYPE_TAB !== 'all' &&
          !types.some(item => item.key === MARKET_COMPETITOR_ACTIVE_TYPE_TAB)) {
        MARKET_COMPETITOR_ACTIVE_TYPE_TAB = 'all';
      }
      const buttons = [{ key: 'all', label: 'الكل', labelEn: 'All' }].concat(types);
      host.innerHTML = buttons.map(item => {
        const selected = item.key === MARKET_COMPETITOR_ACTIVE_TYPE_TAB;
        const label = marketProjectIsEnglish() ? item.labelEn : item.label;
        return '<button type="button" class="market-study-tab' + (selected ? ' active' : '') + '"' +
          ' aria-pressed="' + (selected ? 'true' : 'false') + '"' +
          ' data-market-competitor-type="' + escapeHtml(item.key) + '">' +
          escapeHtml(label) + '</button>';
      }).join('');
      host.querySelectorAll('[data-market-competitor-type]').forEach(button => {
        button.addEventListener('click', () => {
          MARKET_COMPETITOR_ACTIVE_TYPE_TAB = button.dataset.marketCompetitorType || 'all';
          syncMarketCompetitorTypeTabs();
        });
      });
      const visibleRows = new Set(marketCompetitorRowsForType(domRows, MARKET_COMPETITOR_ACTIVE_TYPE_TAB));
      domRows.forEach(row => { row.hidden = !visibleRows.has(row); });
    }

    function marketBenchmarkPickerHtml(axes, selectedValues) {
      const selected = Array.from(new Set((Array.isArray(selectedValues) ? selectedValues : [])
        .map(value => String(value || '').trim()).filter(Boolean)));
      const selectedSet = new Set(selected);
      const options = Array.from(new Set((Array.isArray(axes) ? axes : [])
        .map(marketBenchmarkAxisLabel).concat(selected)));
      const selectedText = selected.length ? selected.join('، ') :
        (marketProjectIsEnglish() ? 'Not selected' : 'غير محدد');
      const editText = marketProjectIsEnglish() ? 'Edit' : 'تعديل';
      return '<details class="market-benchmark-picker" data-field="benchmarks" aria-label="يُقاس على">' +
        '<summary><span class="market-benchmark-selected" data-market-benchmark-selected>' +
        escapeHtml(selectedText) + '</span><span class="market-benchmark-edit">' + editText + '</span></summary>' +
        '<div class="market-benchmark-options">' + options.map(value =>
          '<label><input type="checkbox" data-market-benchmark-option value="' + escapeHtml(value) + '"' +
          (selectedSet.has(value) ? ' checked' : '') + '><span>' + escapeHtml(value) + '</span></label>'
        ).join('') + '</div></details>';
    }

    function marketSelectedBenchmarkValues(row) {
      if (!row || typeof row.querySelectorAll !== 'function') return [];
      return Array.from(row.querySelectorAll('[data-market-benchmark-option]:checked'))
        .map(option => String(option.value || '').trim()).filter(Boolean);
    }

    function refreshMarketBenchmarkPicker(row) {
      const output = row?.querySelector('[data-market-benchmark-selected]');
      if (!output) return;
      const selected = marketSelectedBenchmarkValues(row);
      output.textContent = selected.length ? selected.join('، ')
        : (marketProjectIsEnglish() ? 'Not selected' : 'غير محدد');
    }

    function marketCompetitorVerificationErrorIsNoEvidence(providerError) {
      return String(providerError || '').trim() === 'browse_agent: no browsed evidence';
    }
