/* 04a-market-section.js - market study section UI and tabs. */

    function refreshDynamicI18n(scope) {
      try {
        if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en' && scope) {
          window.WFI18n.autoTranslate(scope);
        }
      } catch (e) { /* ignore */ }
    }

    // Fragment translator for chrome/data composites (option labels, card metas):
    // exact-match auto-translate cannot split them, so chrome fragments are
    // resolved at build time from the shared map. Data stays untouched.
    function trDynamicI18n(text) {
      return wfTr(text);
    }

    function addMarketStudySection(form, before) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-market-study';
      div.dataset.section = 'section-market-study';
      div.appendChild(createProjectSectionHeader('section-market-study', 'دراسة السوق'));
      const body = document.createElement('div');
      body.className = 'market-study-body';
      body.innerHTML = `
        <div class="market-study-tabs" id="marketStudyTabs" role="tablist" aria-label="دراسة السوق">
          <button type="button" class="market-study-tab active" id="marketCompetitorsTab" data-market-study-tab="competitors" role="tab" aria-controls="marketCompetitorsPanel" aria-selected="true" data-section-lock-ignore>المنافسون</button>
          <button type="button" class="market-study-tab" id="marketMarketTab" data-market-study-tab="market" role="tab" aria-controls="marketMarketPanel" aria-selected="false" data-section-lock-ignore>السوق</button>
        </div>
        <div class="market-study-tab-panel" id="marketCompetitorsPanel" data-market-study-panel="competitors" role="tabpanel" aria-labelledby="marketCompetitorsTab">
        <div class="market-block">
          <h4>نطاق الدراسة</h4>
          <div class="market-grid">
            <div><label>نطاق المنافسين</label>
              <select id="marketCompetitorScopeMode">
                <option value="district" selected>الحي</option>
                <option value="city">المدينة</option>
              </select>
            </div>
            <div><label>فترة البيانات</label>
              <select id="marketDataPeriod">
                <option value="12m">آخر 12 شهرًا</option>
                <option value="24m">آخر 24 شهرًا</option>
                <option value="3y">آخر 3 سنوات</option>
                <option value="5y">آخر 5 سنوات</option>
                <option value="custom">فترة مخصصة</option>
              </select>
            </div>
            <div id="marketCustomPeriodWrap" hidden>
              <label>من تاريخ</label><input id="marketDataPeriodFrom" type="date">
              <label style="margin-top:8px">إلى تاريخ</label><input id="marketDataPeriodTo" type="date">
            </div>
          </div>
          <div class="market-grid" style="margin-top:12px">
            <div><label>المدينة</label><input id="marketCityMirror" readonly></div>
            <div><label>الحي</label><input id="marketDistrictMirror" readonly></div>
          </div>
        </div>
        <div class="market-block">
          <h4>اختيارات المقارنة</h4>
          <div id="marketComparisonTypes" class="market-comparison-types"></div>
          <div class="market-actions" style="margin-top:8px">
            <button type="button" class="btn ghost" id="marketAddComparisonTypeBtn" onclick="addMarketComparisonType()">إضافة نوع مقارنة</button>
          </div>
        </div>
        <div class="market-block">
          <h4>المنافسون</h4>
          <div class="market-actions">
            <button type="button" class="btn ghost" onclick="addMarketCompetitorRow()">إضافة منافس</button>
            <button type="button" class="btn ghost" id="marketFillCompetitorsBtn" onclick="runMarketCompetitorsJob('fill')">إكمال بيانات المنافسين بالاسم</button>
            <button type="button" class="btn primary" id="marketGenerateCompetitorsBtn" onclick="runMarketCompetitorsJob('generate')">توليد المنافسين</button>
          </div>
          <div id="marketCompetitorsNote"></div>
          <div class="table-wrap">
            <table id="marketCompetitorsTable">
              <thead><tr>
                <th>اسم المشروع</th><th>الشعار</th><th>النوع</th><th>النجوم</th><th>التصنيف</th><th data-benchmarks-col>يُقاس على</th><th>المساحة م²</th><th>الحالة</th><th>المصدر</th>
                <th>نوع العملية</th><th>نوع السعر</th><th>القيمة (ر.س)</th><th></th>
              </tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div id="marketCompetitorPriceBenchmarks" hidden></div>
        </div>
        </div>
        <div class="market-study-tab-panel market-study-tab-panel-off" id="marketMarketPanel" data-market-study-panel="market" role="tabpanel" aria-labelledby="marketMarketTab" aria-hidden="true">
        <div class="market-block">
          <h4>الملخص التنفيذي لسوق المشروع</h4>
          <div style="margin-top:12px">
            <div><label data-i18n="market.summary_scope">نطاق الملخص</label>
              <select id="marketSummaryScopeMode">
                <option value="distance" data-i18n="market.summary_scope_distance">بالمسافة</option>
                <option value="city" data-i18n="market.summary_scope_city">بالمدينة</option>
                <option value="district" data-i18n="market.summary_scope_district">بالحي</option>
              </select>
            </div>
            <div id="marketSummaryScopeDistanceWrap" style="margin-top:8px">
              <div><label data-i18n="market.summary_scope_distance_value">مسافة النطاق</label>
                <select id="marketSummaryScopeDistance">
                  <option value="3">3 كم</option>
                  <option value="5">5 كم</option>
                  <option value="10" selected>10 كم</option>
                  <option value="city">كامل المدينة</option>
                  <option value="custom">نطاق مخصص</option>
                </select>
              </div>
              <div id="marketSummaryScopeCustomWrap" hidden><label>النطاق المخصص (كم)</label><input id="marketSummaryScopeCustomKm" type="number" min="1" step="0.1"></div>
            </div>
            <div id="marketSummaryScopePlacesWrap" style="margin-top:8px" hidden>
              <div><label id="marketSummaryScopePlacesLabel" data-i18n="market.summary_scope_cities">المدن</label></div>
              <div class="table-wrap"><table><tbody id="marketSummaryScopePlaces"></tbody></table></div>
              <div class="market-actions" style="margin-top:8px"><button type="button" class="btn ghost" id="marketSummaryScopeAddBtn" data-i18n="market.summary_scope_add_city" onclick="addMarketSummaryScopePlace()">إضافة مدينة</button></div>
            </div>
          </div>
          <div class="market-actions" style="margin-top:12px">
            <button type="button" class="btn primary" id="marketGenerateSummaryBtn" onclick="runMarketSummaryJob()">توليد ملخص السوق</button>
          </div>
          <div id="marketSummaryFailure"></div>
          <div id="marketSummaryCompare" hidden></div>
          <div id="marketSummaryFields"></div>
          <h4 style="margin-top:18px">تحليل SWOT</h4>
          <div id="marketSwotFields"></div>
          <div style="margin-top:12px"><label>تصنيف القرار</label>
            <select id="marketDecision">
              <option value="">-- اختر القيمة --</option>
              <option>فرصة قوية</option>
              <option>فرصة واعدة بشروط</option>
              <option>فرصة متوسطة</option>
              <option>فرصة مرتفعة المخاطر</option>
              <option>البيانات غير كافية</option>
            </select>
          </div>
          <div style="margin-top:12px"><label>إخلاء المسؤولية</label>
            <textarea id="marketDisclaimer" rows="2"></textarea>
          </div>
        </div>
        <div class="market-block">
          <h4>ملخص دراسة سوق العمل</h4>
          <textarea id="marketStudyOneBlockSummary" rows="18" readonly></textarea>
        </div>
        <div class="market-block">
          <h4>المصادر</h4>
          <div class="market-actions">
            <button type="button" class="btn ghost" onclick="addMarketSourceRow()">إضافة مصدر</button>
          </div>
          <div id="marketSourcesTabs" class="market-source-tabs" role="tablist"></div>
          <div id="marketSourcesPanels" class="market-source-panels"></div>
        </div>
        </div>
        <input type="hidden" data-key="market_study_data" data-type="text" id="marketStudyData">
      `;
      div.appendChild(body);
      if (before) form.insertBefore(div, before);
      else form.appendChild(div);
      setupMarketStudyTabs(div);
      const summaryHost = document.getElementById('marketSummaryFields');
      if (summaryHost) {
        summaryHost.innerHTML = MARKET_STUDY_SUMMARY_SECTIONS.map(item =>
          '<div style="margin-top:12px"><label>' + item.label + '</label>' +
          '<textarea id="marketSummary_' + item.key + '" rows="4"></textarea></div>'
        ).join('');
      }
      const swotHost = document.getElementById('marketSwotFields');
      if (swotHost) {
        swotHost.innerHTML = MARKET_STUDY_SWOT_SECTIONS.map(item =>
          '<div style="margin-top:12px"><label>' + item.label + '</label>' +
          '<textarea id="marketSwot_' + item.key + '" rows="4"></textarea></div>'
        ).join('');
      }
      ['marketCompetitorScopeMode', 'marketDataPeriod', 'marketSummaryScopeMode', 'marketSummaryScopeDistance'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', () => {
          updateMarketStudyFieldVisibility();
          persistMarketStudyFromDom();
        });
      });
      ['marketSummaryScopeCustomKm', 'marketDataPeriodFrom', 'marketDataPeriodTo', 'marketDecision', 'marketDisclaimer']
        .forEach(id => document.getElementById(id)?.addEventListener('input', persistMarketStudyFromDom));
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
        document.getElementById('marketSummary_' + item.key)?.addEventListener('input', persistMarketStudyFromDom);
      });
      MARKET_STUDY_SWOT_SECTIONS.forEach(item => {
        document.getElementById('marketSwot_' + item.key)?.addEventListener('input', persistMarketStudyFromDom);
      });
      document.getElementById('marketComparisonTypes')?.addEventListener('change', event => {
        if (event.target?.dataset?.comparisonField === 'type') {
          const row = event.target.closest('[data-comparison-row]');
          if (row) syncMarketComparisonRow(row);
        }
        persistMarketStudyFromDom();
      });
      refreshDynamicI18n(div);
      if (typeof mountMarketSummaryChat === 'function') mountMarketSummaryChat(div);
    }

    function activateMarketStudyTab(root, tabKey) {
      if (!root) return;
      const activeKey = tabKey === 'market' ? 'market' : 'competitors';
      root.querySelectorAll('#marketStudyTabs .market-study-tab').forEach(button => {
        const active = button.dataset.marketStudyTab === activeKey;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
      });
      root.querySelectorAll('.market-study-tab-panel').forEach(panel => {
        const active = panel.dataset.marketStudyPanel === activeKey;
        panel.classList.toggle('market-study-tab-panel-off', !active);
        panel.setAttribute('aria-hidden', active ? 'false' : 'true');
      });
    }

    function setupMarketStudyTabs(root) {
      const bar = root.querySelector('#marketStudyTabs');
      if (!bar) return;
      const tabs = [...bar.querySelectorAll('.market-study-tab')];
      tabs.forEach(button => {
        button.addEventListener('click', () =>
          activateMarketStudyTab(root, button.dataset.marketStudyTab));
      });
      const active = tabs.find(button => button.classList.contains('active'));
      activateMarketStudyTab(root, active?.dataset.marketStudyTab || 'competitors');
    }

    function readMarketComparisonRows() {
      return Array.from(document.querySelectorAll('#marketComparisonTypes [data-comparison-row]'))
        .map(row => ({
          type: row.querySelector('[data-comparison-field="type"]')?.value || '',
          operation: row.querySelector('[data-comparison-field="operation"]')?.value || '',
          stars: row.querySelector('[data-comparison-field="stars"]')?.value || ''
        }));
    }

    function collectMarketComparisonTypes() {
      return readMarketComparisonRows().filter(row =>
        row.type === 'hotel' ? /^[1-5]$/.test(row.stars)
          : ['residential', 'commercial'].includes(row.type)
            && ['sale', 'rent'].includes(row.operation)
      );
    }

    function marketComparisonTypeRowHtml(item = {}) {
      const type = ['hotel', 'residential', 'commercial'].includes(item.type) ? item.type : '';
      const operation = ['sale', 'rent'].includes(item.operation) ? item.operation : '';
      const stars = /^[1-5]$/.test(String(item.stars || '')) ? String(item.stars) : '';
      const typeOptions = [
        '<option value="">--</option>',
        '<option value="hotel"' + (type === 'hotel' ? ' selected' : '') + '>فندقي</option>',
        '<option value="residential"' + (type === 'residential' ? ' selected' : '') + '>سكني</option>',
        '<option value="commercial"' + (type === 'commercial' ? ' selected' : '') + '>تجاري</option>'
      ].join('');
      const operationOptions = [
        '<option value="">--</option>',
        '<option value="sale"' + (operation === 'sale' ? ' selected' : '') + '>بيعي</option>',
        '<option value="rent"' + (operation === 'rent' ? ' selected' : '') + '>تأجيري</option>'
      ].join('');
      const starOptions = ['<option value="">--</option>']
        .concat([1, 2, 3, 4, 5].map(value =>
          '<option value="' + value + '"' + (stars === String(value) ? ' selected' : '') + '>' + value + ' نجوم</option>'
        )).join('');
      return '<div class="market-comparison-type-row" data-comparison-row>' +
        '<div><label>نوع المقارنة</label><select data-comparison-field="type">' + typeOptions + '</select></div>' +
        '<div data-comparison-operation' + (type === 'residential' || type === 'commercial' ? '' : ' hidden') + '><label>نوع العملية</label><select data-comparison-field="operation">' + operationOptions + '</select></div>' +
        '<div data-comparison-stars' + (type === 'hotel' ? '' : ' hidden') + '><label>تصنيف الفندق</label><select data-comparison-field="stars">' + starOptions + '</select></div>' +
        '<button type="button" class="btn ghost small" data-remove-comparison-type>حذف</button>' +
        '</div>';
    }

    function renderMarketComparisonTypes(items) {
      const host = document.getElementById('marketComparisonTypes');
      if (!host) return;
      const rows = Array.isArray(items) ? items : [];
      host.innerHTML = rows.map(marketComparisonTypeRowHtml).join('') ||
        '<div class="tenant-hint">لا توجد أنواع مقارنة محددة</div>';
      host.querySelectorAll('[data-comparison-row]').forEach(row => {
        row.querySelector('[data-remove-comparison-type]')?.addEventListener('click', () => {
          row.remove();
          persistMarketStudyFromDom();
          if (!host.querySelector('[data-comparison-row]')) renderMarketComparisonTypes([]);
        });
      });
      refreshDynamicI18n(host);
    }

    function syncMarketComparisonRow(row) {
      const type = row.querySelector('[data-comparison-field="type"]')?.value || '';
      const operation = row.querySelector('[data-comparison-operation]');
      const stars = row.querySelector('[data-comparison-stars]');
      if (operation) operation.hidden = type !== 'residential' && type !== 'commercial';
      if (stars) stars.hidden = type !== 'hotel';
    }

    function addMarketComparisonType() {
      const rows = readMarketComparisonRows();
      rows.push({ type: '', operation: '', stars: '' });
      renderMarketComparisonTypes(rows);
      persistMarketStudyFromDom();
    }

    function renderMarketTransactionBenchmarks(data) {
      const host = document.getElementById('marketCompetitorPriceBenchmarks');
      if (!host) return;
      const benchmark = data && typeof data === 'object' ? data : null;
      const groups = Array.isArray(benchmark?.groups) ? benchmark.groups : [];
      host.hidden = !groups.length;
      if (!groups.length) {
        host.innerHTML = '';
        return;
      }
      const format = value => value === null || value === undefined || value === ''
        ? 'غير متاح' : new Intl.NumberFormat('ar-SA', { maximumFractionDigits: 0 }).format(Number(value));
      host.innerHTML = '<div class="market-transaction-benchmarks"><h4>صفقات مرجعية مجهولة الهوية</h4>' +
        '<div class="tenant-hint">' + escapeHtml(benchmark.note || '') + '</div>' +
        '<div class="table-wrap"><table><thead><tr><th>الحي</th><th>نوع الوحدة</th><th>عدد الصفقات</th><th>وسيط سعر المتر</th><th>وسيط قيمة الصفقة</th><th>الفترة</th></tr></thead><tbody>' +
        groups.map(item => '<tr><td>' + escapeHtml(item.district || '') + '</td><td>' + escapeHtml(item.unit_type || '') + '</td>' +
          '<td>' + format(item.deal_count) + '</td><td>' + format(item.median_price_sqm_sar) + ' ر.س</td>' +
          '<td>' + format(item.median_deal_value_sar) + ' ر.س</td><td>' +
          escapeHtml([item.period_from, item.period_to].filter(Boolean).join(' إلى ')) + '</td></tr>').join('') +
        '</tbody></table></div><div class="tenant-hint">' + escapeHtml(benchmark.source || '') +
        (benchmark.source_url ? ' — <a href="' + escapeHtml(benchmark.source_url) + '" target="_blank" rel="noopener noreferrer">المصدر</a>' : '') +
        '</div></div>';
      refreshDynamicI18n(host);
    }
