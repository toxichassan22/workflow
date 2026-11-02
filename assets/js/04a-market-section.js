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

    function autoGrowMarketStudyField(field) {
      if (!field || !field.style || typeof field.scrollHeight !== 'number') return;
      if (field.offsetParent === null) return;
      field.style.height = 'auto';
      field.style.height = field.scrollHeight + 'px';
    }

    function autoGrowMarketStudyFields() {
      if (!document.querySelectorAll) return;
      document.querySelectorAll('#section-market-study textarea.market-auto-grow')
        .forEach(autoGrowMarketStudyField);
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
          <button type="button" class="market-study-tab" id="marketCompetitorsTab" data-market-study-tab="competitors" role="tab" aria-controls="marketCompetitorsPanel" aria-selected="false" data-section-lock-ignore="1">المنافسون</button>
          <button type="button" class="market-study-tab active" id="marketMarketTab" data-market-study-tab="market" role="tab" aria-controls="marketMarketPanel" aria-selected="true" data-section-lock-ignore="1">السوق</button>
        </div>
        <div class="market-study-tab-panel market-study-tab-panel-off" id="marketCompetitorsPanel" data-market-study-panel="competitors" role="tabpanel" aria-labelledby="marketCompetitorsTab" aria-hidden="true">
        <div class="market-block">
          <h4>نطاق الدراسة</h4>
          <div class="market-grid">
            <div><label>نطاق المنافسين</label>
              <select id="marketCompetitorScopeMode">
                <option value="district" selected>الحي</option>
                <option value="city">المدينة</option>
                <option value="distance">المسافة</option>
              </select>
            </div>
            <div id="marketCompetitorRadiusWrap" hidden>
              <label>مسافة البحث</label>
              <select id="marketCompetitorRadius">
                <option value="3">3 كم</option>
                <option value="5">5 كم</option>
                <option value="10" selected>10 كم</option>
                <option value="custom">مسافة مخصصة</option>
              </select>
            </div>
            <div id="marketCompetitorRadiusCustomWrap" hidden>
              <label>المسافة المخصصة (كم)</label>
              <input id="marketCompetitorRadiusCustomKm" type="number" min="0.1" max="100" step="0.1" inputmode="decimal">
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
          <div class="market-scope-districts" id="marketCompetitorDistrictsWrap">
            <label>أحياء النطاق</label>
            <div id="marketCompetitorDistrictChips" class="market-scope-chips"></div>
            <div class="market-scope-add">
              <input id="marketCompetitorDistrictInput" type="text" placeholder="اسم الحي" data-i18n-ph="market.summary_scope_district_name">
              <button type="button" class="btn ghost small" onclick="addMarketCompetitorDistrict()">إضافة حي</button>
            </div>
          </div>
        </div>
        <div class="market-block">
          <h4>اختيارات المقارنة</h4>
          <div id="marketComparisonTypes" class="market-comparison-types"></div>
          <div id="marketCompetitorUnitTypes" class="market-unit-types"></div>
          <div class="market-competitors-mode">
            <label for="marketCompetitorsMode">طريقة الإدخال</label>
            <select id="marketCompetitorsMode" onchange="applyMarketCompetitorsMode()">
              <option value="generate">توليد آلي</option>
              <option value="manual">إدخال يدوي</option>
            </select>
          </div>
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
          <div id="marketCompetitorTypeTabs" class="market-competitor-type-tabs" role="group" aria-label="نوع المشروع" hidden></div>
          <div class="table-wrap">
            <table id="marketCompetitorsTable">
              <thead><tr>
                <th>اسم المشروع</th><th>الشعار</th><th>نوع المنافس</th><th>التصنيف</th><th data-benchmarks-col>يُقاس على</th><th>المساحة م²</th><th>الحالة</th><th>المصدر</th>
                <th>نوع العملية</th><th>نوع السعر</th><th>القيمة (ر.س)</th><th></th>
              </tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div id="marketCompetitorPriceBenchmarks" hidden></div>
        </div>
        </div>
        <div class="market-study-tab-panel" id="marketMarketPanel" data-market-study-panel="market" role="tabpanel" aria-labelledby="marketMarketTab" aria-hidden="false">
          <section class="market-study-generate-card" id="marketStudyGenerateBlock">
            <div class="market-study-section-head"><div><span class="market-study-kicker" data-i18n="market.generation_scope">نطاق التوليد</span><h4 data-i18n="market.generation_scope">نطاق التوليد</h4></div></div>
            <div class="market-study-generate">
              <div class="market-study-scope">
                <div class="market-study-scope-head"><button type="button" class="btn ghost small" id="marketSummaryScopeAddCityBtn" data-i18n="market.summary_scope_add_city" onclick="addMarketSummaryScopeCity()">إضافة مدينة</button></div>
                <div id="marketSummaryScopeCities"></div>
              </div>
              <div class="market-study-generate-row">
                <div class="market-study-field"><label for="marketSummaryPeriod">فترة البيانات</label>
                  <select id="marketSummaryPeriod">
                    <option value="12m">آخر 12 شهرًا</option>
                    <option value="24m">آخر 24 شهرًا</option>
                    <option value="3y">آخر 3 سنوات</option>
                    <option value="5y">آخر 5 سنوات</option>
                    <option value="custom">فترة مخصصة</option>
                  </select>
                </div>
                <div id="marketSummaryCustomPeriodWrap" hidden>
                  <label>من تاريخ</label><input id="marketSummaryPeriodFrom" type="date">
                  <label style="margin-top:8px">إلى تاريخ</label><input id="marketSummaryPeriodTo" type="date">
                </div>
                <button type="button" class="btn primary" id="marketGenerateSummaryBtn" onclick="runMarketSummaryJob()">توليد ملخص السوق</button>
                <button type="button" class="btn ghost" id="marketResumeSummaryBtn" onclick="resumeMarketSummaryJob()" hidden>استكمال المهمة</button>
                <button type="button" class="btn ghost" id="marketSummaryTraceBtn" hidden>تنزيل سجل البحث</button>
              </div>
              <div id="marketSummaryFailure"></div>
              <div id="marketSummaryCompare" hidden></div>
            </div>
          </section>
          <div class="market-study-context" id="marketStudyContext">
            <div><span>المدينة</span><strong id="marketContextCity">—</strong></div>
            <div><span>الحي</span><strong id="marketContextDistrict">—</strong></div>
            <div><span>المصادر</span><strong id="marketContextSources">0</strong></div>
            <div><span data-i18n="market.context_updated">آخر تحديث</span><strong id="marketContextUpdated">—</strong></div>
          </div>
          <section class="market-study-decision" id="marketStudyDecisionBlock">
            <div class="market-study-section-head"><div><span class="market-study-kicker">القرار</span><h4>تصنيف القرار</h4></div></div>
            <div class="market-study-field"><label for="marketDecision">تصنيف القرار</label>
              <select id="marketDecision">
                <option value="">-- اختر القيمة --</option>
                <option>فرصة قوية</option>
                <option>فرصة واعدة بشروط</option>
                <option>فرصة متوسطة</option>
                <option>فرصة مرتفعة المخاطر</option>
                <option>البيانات غير كافية</option>
              </select>
            </div>
            <div class="market-study-field"><label for="marketDisclaimer">إخلاء المسؤولية</label>
              <textarea id="marketDisclaimer" rows="1" class="market-auto-grow"></textarea>
            </div>
          </section>
          <nav class="market-study-toc" id="marketStudyToc" aria-label="محاور دراسة السوق" data-i18n-aria="market.toc_label">
            ${MARKET_STUDY_SUMMARY_SECTIONS.map((item, index) => '<a href="#market-axis-' + item.key + '">' + String(index + 1).padStart(2, '0') + ' ' + escapeHtml(item.label) + '</a>').join('')}
            <a href="#marketStudySwotBlock">SWOT</a>
            <a href="#marketStudySummaryBlock">الملخص</a>
            <a href="#marketStudySourcesBlock">المصادر</a>
            <button type="button" class="market-study-toc-toggle" id="marketStudyTocToggle" data-section-lock-ignore="1" data-i18n="market.collapse_all">طي الكل</button>
          </nav>
          <section class="market-study-axes" id="marketStudyAxesBlock">
            <div class="market-study-section-head"><div><span class="market-study-kicker" data-i18n="market.axes_title">محاور التحليل</span><h4 data-i18n="market.axes_title">محاور التحليل</h4></div><span class="market-study-count" data-i18n="market.axes_count">${MARKET_STUDY_SUMMARY_SECTIONS.length} محاور</span></div>
            <div id="marketSummaryFields"></div>
          </section>
          <section class="market-study-swot" id="marketStudySwotBlock">
            <div class="market-study-section-head" id="marketStudySwotHead"><div><span class="market-study-kicker">SWOT</span><h4>تحليل SWOT</h4></div><button type="button" class="market-study-section-toggle" data-market-section-toggle="swot" data-section-lock-ignore="1" data-i18n="market.collapse" aria-expanded="true">طي</button></div>
            <div id="marketSwotFields" data-market-section-body="swot"></div>
          </section>
          <section class="market-study-summary" id="marketStudySummaryBlock">
            <div class="market-study-section-head"><div><span class="market-study-kicker">الملخص التنفيذي</span><h4>الملخص التنفيذي لسوق المشروع</h4></div><button type="button" class="market-study-section-toggle" data-market-section-toggle="summary" data-section-lock-ignore="1" data-i18n="market.collapse" aria-expanded="true">طي</button></div>
            <div class="market-study-summary-body" data-market-section-body="summary">
              <textarea id="marketStudyOneBlockSummary" rows="1" class="market-auto-grow market-study-one-block" aria-label="الملخص التنفيذي لسوق المشروع"></textarea>
            </div>
          </section>
          <section class="market-study-sources" id="marketStudySourcesBlock">
            <div class="market-study-section-head"><div><span class="market-study-kicker">المصادر</span><h4 data-i18n="market.sources_title">سجل المصادر</h4></div>
              <div class="market-study-sources-actions"><span id="marketSourcesCount" class="market-study-count"></span><button type="button" class="btn ghost small" id="marketAddSourceBtn" onclick="addMarketSourceRow()">إضافة مصدر</button></div>
            </div>
            <div id="marketSourcesTabs" class="market-source-tabs" role="tablist"></div>
            <div id="marketSourcesPanels" class="market-source-panels"></div>
          </section>
        </div>
        <input type="hidden" data-key="market_study_data" data-type="text" id="marketStudyData">
      `;
      div.appendChild(body);
      if (before) form.insertBefore(div, before);
      else form.appendChild(div);
      setupMarketStudyTabs(div);
      const summaryHost = document.getElementById('marketSummaryFields');
      if (summaryHost) {
        summaryHost.innerHTML = MARKET_STUDY_SUMMARY_SECTIONS.map((item, index) =>
          '<section class="market-axis-card" id="market-axis-' + item.key + '">' +
            '<header class="market-axis-head">' +
              '<span class="market-axis-num">' + String(index + 1).padStart(2, '0') + '</span>' +
              '<label class="market-axis-title" for="marketSummary_' + item.key + '">' + item.label + '</label>' +
              '<button type="button" class="market-axis-toggle" data-section-lock-ignore="1" data-i18n="market.collapse" aria-expanded="true">طي</button>' +
            '</header>' +
            '<div class="market-axis-body"><textarea id="marketSummary_' + item.key + '" rows="1" class="market-auto-grow" aria-label="' + item.label + '"></textarea></div>' +
          '</section>'
        ).join('');
        summaryHost.querySelectorAll('.market-axis-toggle').forEach(btn => {
          btn.addEventListener('click', () => {
            const card = btn.closest('.market-axis-card');
            const collapsed = card.classList.toggle('collapsed');
            btn.textContent = collapsed ? WFT('market.expand', 'فتح') : WFT('market.collapse', 'طي');
            btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            if (!collapsed) autoGrowMarketStudyFields();
          });
        });
      }
      const swotHost = document.getElementById('marketSwotFields');
      if (swotHost) {
        swotHost.innerHTML = MARKET_STUDY_SWOT_SECTIONS.map(item =>
          '<article class="market-swot-card" id="market-swot-' + item.key + '">' +
            '<label class="market-swot-title" for="marketSwot_' + item.key + '">' + item.label + '</label>' +
            '<textarea id="marketSwot_' + item.key + '" rows="1" class="market-auto-grow" aria-label="' + item.label + '"></textarea>' +
          '</article>'
        ).join('');
      }
      const toc = document.getElementById('marketStudyToc');
      if (toc) {
        toc.addEventListener('click', event => {
          const link = event.target.closest('a[href^="#market-axis-"], a[href="#marketStudySummaryBlock"], a[href="#marketStudySwotBlock"]');
          if (!link) return;
          const card = document.querySelector(link.getAttribute('href'));
          if (!card || !card.classList.contains('collapsed')) return;
          card.classList.remove('collapsed');
          const btn = card.querySelector('.market-axis-toggle, .market-study-section-toggle');
          if (btn) {
            btn.textContent = WFT('market.collapse', 'طي');
            btn.setAttribute('aria-expanded', 'true');
          }
          setTimeout(autoGrowMarketStudyFields, 0);
        });
      }
      document.querySelectorAll('.market-study-section-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
          const card = btn.closest('.market-study-summary, .market-study-swot');
          if (!card) return;
          const collapsed = card.classList.toggle('collapsed');
          btn.textContent = collapsed ? WFT('market.expand', 'فتح') : WFT('market.collapse', 'طي');
          btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
          if (!collapsed) setTimeout(autoGrowMarketStudyFields, 0);
        });
      });
      const tocToggle = document.getElementById('marketStudyTocToggle');
      if (tocToggle && summaryHost) {
        let allOpen = true;
        tocToggle.addEventListener('click', () => {
          allOpen = !allOpen;
          summaryHost.querySelectorAll('.market-axis-card').forEach(card => {
            card.classList.toggle('collapsed', !allOpen);
            const btn = card.querySelector('.market-axis-toggle');
            if (btn) {
              btn.textContent = allOpen ? WFT('market.collapse', 'طي') : WFT('market.expand', 'فتح');
              btn.setAttribute('aria-expanded', allOpen ? 'true' : 'false');
            }
          });
          tocToggle.textContent = allOpen ? WFT('market.collapse_all', 'طي الكل') : WFT('market.expand_all', 'فتح الكل');
          if (allOpen) autoGrowMarketStudyFields();
        });
      }
      if (typeof window !== 'undefined' && !window.__marketStudyAutoGrowBound) {
        window.__marketStudyAutoGrowBound = true;
        window.addEventListener('resize', () => setTimeout(autoGrowMarketStudyFields, 120));
      }
      const projectSidebar = document.getElementById('tenantProjectSidebar');
      if (projectSidebar && !projectSidebar.dataset.marketStudyAutoGrowBound) {
        projectSidebar.dataset.marketStudyAutoGrowBound = '1';
        projectSidebar.addEventListener('click', () => setTimeout(autoGrowMarketStudyFields, 150));
      }
      setTimeout(autoGrowMarketStudyFields, 250);
      ['marketCompetitorScopeMode', 'marketCompetitorRadius', 'marketDataPeriod'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', () => {
          updateMarketStudyFieldVisibility();
          persistMarketStudyFromDom();
        });
      });
      ['marketCompetitorRadiusCustomKm', 'marketDataPeriodFrom', 'marketDataPeriodTo',
       'marketSummaryPeriodFrom', 'marketSummaryPeriodTo', 'marketDecision', 'marketDisclaimer']
        .forEach(id => document.getElementById(id)?.addEventListener('input', persistMarketStudyFromDom));
      document.getElementById('marketSummaryPeriod')?.addEventListener('change', () => {
        updateMarketStudyFieldVisibility();
        persistMarketStudyFromDom();
      });
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
        const field = document.getElementById('marketSummary_' + item.key);
        if (!field) return;
        field.addEventListener('input', () => {
          persistMarketStudyFromDom();
          autoGrowMarketStudyField(field);
        });
      });
      MARKET_STUDY_SWOT_SECTIONS.forEach(item => {
        const field = document.getElementById('marketSwot_' + item.key);
        if (!field) return;
        field.addEventListener('input', () => {
          persistMarketStudyFromDom();
          autoGrowMarketStudyField(field);
        });
      });
      const oneBlockField = document.getElementById('marketStudyOneBlockSummary');
      if (oneBlockField) {
        oneBlockField.addEventListener('input', () => {
          persistMarketStudyFromDom();
          autoGrowMarketStudyField(oneBlockField);
        });
      }
      document.getElementById('marketDisclaimer')?.addEventListener('input', event => {
        autoGrowMarketStudyField(event.target);
      });
      document.getElementById('marketCompetitorUnitTypes')?.addEventListener('change', (
        persistMarketStudyFromDom));
      document.getElementById('marketCompetitorDistrictInput')?.addEventListener(
        'keydown', event => {
          if (event.key !== 'Enter') return;
          event.preventDefault();
          addMarketCompetitorDistrict();
        });
      document.getElementById('marketComparisonTypes')?.addEventListener('change', event => {
        if (event.target?.dataset?.comparisonField === 'type') {
          const row = event.target.closest('[data-comparison-row]');
          if (row) syncMarketComparisonRow(row);
          syncMarketComparisonTypeOptions();
        }
        persistMarketStudyFromDom();
      });
      const savedMode = (typeof getMarketStudyState === 'function'
        ? (getMarketStudyState() || {}).competitor_mode : '') || 'generate';
      const modeSelect = document.getElementById('marketCompetitorsMode');
      if (modeSelect) modeSelect.value = savedMode;
      if (typeof applyMarketCompetitorsMode === 'function') {
        applyMarketCompetitorsMode(false);
      }
      refreshDynamicI18n(div);
      if (typeof mountMarketSummaryChat === 'function') mountMarketSummaryChat(div);
      if (typeof restoreMarketSummaryResumeAction === 'function') {
        restoreMarketSummaryResumeAction();
      }
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
      if (activeKey === 'market') setTimeout(autoGrowMarketStudyFields, 0);
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

    function marketComparisonValues(value, allowed) {
      const values = Array.isArray(value) ? value : [value];
      return [...new Set(values.flatMap(item => String(item ?? '').split(/[,،;|\n]/))
        .map(item => item.trim()).filter(item => allowed.includes(item)))];
    }

    function normalizeMarketComparisonRows(items) {
      const rows = [];
      const byType = new Map();
      let hasEmptyRow = false;
      (Array.isArray(items) ? items : []).forEach(item => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) return;
        const type = ['hotel', 'residential', 'commercial'].includes(item.type) ? item.type : '';
        if (!type) {
          hasEmptyRow = true;
          return;
        }
        let row = byType.get(type);
        if (!row) {
          row = { type, operation: [] };
          byType.set(type, row);
          rows.push(row);
        }
        if (type !== 'hotel') {
          row.operation = [...new Set(row.operation.concat(marketComparisonValues(
            item.operation ?? item.operations ?? item.operationType, ['sale', 'rent'])))];
        }
      });
      if (hasEmptyRow) rows.push({ type: '', operation: [] });
      return rows;
    }

    function readMarketComparisonRows() {
      return Array.from(document.querySelectorAll('#marketComparisonTypes [data-comparison-row]'))
        .map(row => ({
          type: row.querySelector('[data-comparison-field="type"]')?.value || '',
          operation: Array.from(row.querySelectorAll('[data-comparison-field="operation"]'))
            .filter(option => option.checked).map(option => option.value)
        }));
    }

    function collectMarketComparisonTypes() {
      return readMarketComparisonRows().filter(row =>
        row.type === 'hotel'
          || (['residential', 'commercial'].includes(row.type)
              && row.operation.some(value => ['sale', 'rent'].includes(value)))
      );
    }

    function marketComparisonTypeRowHtml(item = {}, occupiedTypes = []) {
      const type = ['hotel', 'residential', 'commercial'].includes(item.type) ? item.type : '';
      const operations = marketComparisonValues(item.operation ?? item.operations, ['sale', 'rent']);
      const typeOptions = [
        '<option value="">--</option>',
        '<option value="hotel"' + (type === 'hotel' ? ' selected' : '') + '>فندقي</option>',
        '<option value="residential"' + (type === 'residential' ? ' selected' : '') + '>سكني</option>',
        '<option value="commercial"' + (type === 'commercial' ? ' selected' : '') + '>تجاري</option>'
      ].filter(option => {
        const optionType = option.match(/value="(hotel|residential|commercial)"/)?.[1] || '';
        return !optionType || optionType === type || !occupiedTypes.includes(optionType);
      }).join('');
      const operationOptions = [
        ['sale', 'بيعي / تمليكي'], ['rent', 'إيجاري']
      ].map(([value, label]) =>
        '<label><input type="checkbox" data-comparison-field="operation" value="' + value + '"' +
        (operations.includes(value) ? ' checked' : '') + '><span>' + label + '</span></label>'
      ).join('');
      return '<div class="market-comparison-type-row" data-comparison-row>' +
        '<div><label>نوع المقارنة</label><select data-comparison-field="type">' + typeOptions + '</select></div>' +
        '<div data-comparison-operation' + (type === 'residential' || type === 'commercial' ? '' : ' hidden') + '><label>نوع العملية</label><div class="market-comparison-multi-options">' + operationOptions + '</div></div>' +
        '<button type="button" class="btn ghost small" data-remove-comparison-type>حذف</button>' +
        '</div>';
    }

    function applyMarketCompetitorsMode(persist = true) {
      const mode = document.getElementById('marketCompetitorsMode')?.value || 'generate';
      const generateBtn = document.getElementById('marketGenerateCompetitorsBtn');
      const fillBtn = document.getElementById('marketFillCompetitorsBtn');
      // Two buttons per mode, one shared: generate builds rows, manual
      // completes the rows the client typed; «إضافة منافس» stays in both.
      // A class rule owns .btn's display, so the hidden attribute alone never
      // hides one — set the inline display explicitly.
      if (generateBtn) generateBtn.style.display = mode === 'manual' ? 'none' : '';
      if (fillBtn) fillBtn.style.display = mode === 'manual' ? '' : 'none';
      if (persist && typeof persistMarketStudyFromDom === 'function') {
        try {
          persistMarketStudyFromDom();
        } catch (error) {
          console.error('market competitors mode persist failed', error);
        }
      }
    }

    // The two competitor modes are explicit: generate builds rows from the
    // comparison selection, while a manual row states its own type so the
    // fill step knows which source to read (Booking for hotels).
    function marketRowsMissingType(rows) {
      return (Array.isArray(rows) ? rows : [])
        .filter(row => String((row || {}).name || '').trim()
          && !String((row || {}).type || '').trim());
    }

    function marketComparisonAddGuard(rows) {      // A blank row is a slot the client is filling, not a third type: counting
      // it disabled «إضافة نوع مقارنة» after two real types.
      const filled = rows.filter(row => row.type);
      return { filled: filled.length, hasBlank: rows.length > filled.length };
    }

    function refreshMarketComparisonAddButton() {
      const host = document.getElementById('marketComparisonTypes');
      const addButton = document.getElementById('marketAddComparisonTypeBtn');
      if (!host || !addButton) return;
      const rows = Array.from(host.querySelectorAll('[data-comparison-row]')).map(row =>
        ({ type: row.querySelector('[data-comparison-field="type"]')?.value || '' }));
      addButton.disabled = marketComparisonAddGuard(rows).filled >= 3;
    }

    function renderMarketComparisonTypes(items) {
      const host = document.getElementById('marketComparisonTypes');
      if (!host) return;
      const rows = normalizeMarketComparisonRows(items);
      const occupiedTypes = rows.map(row => row.type).filter(Boolean);
      host.innerHTML = rows.map(row => marketComparisonTypeRowHtml(row, occupiedTypes)).join('') ||
        '<div class="tenant-hint">لا توجد أنواع مقارنة محددة</div>';
      host.querySelectorAll('[data-comparison-row]').forEach(row => {
        row.querySelector('[data-remove-comparison-type]')?.addEventListener('click', () => {
          row.remove();
          persistMarketStudyFromDom();
          if (!host.querySelector('[data-comparison-row]')) renderMarketComparisonTypes([]);
          else syncMarketComparisonTypeOptions();
        });
      });
      refreshMarketComparisonAddButton();
      refreshDynamicI18n(host);
    }

    function syncMarketComparisonRow(row) {
      const type = row.querySelector('[data-comparison-field="type"]')?.value || '';
      const operation = row.querySelector('[data-comparison-operation]');
      const isOperation = type === 'residential' || type === 'commercial';
      if (operation) {
        operation.hidden = !isOperation;
        if (!isOperation) operation.querySelectorAll('[data-comparison-field="operation"]')
          .forEach(option => { option.checked = false; });
      }
    }

    function syncMarketComparisonTypeOptions() {
      const host = document.getElementById('marketComparisonTypes');
      if (!host) return;
      const rows = Array.from(host.querySelectorAll('[data-comparison-row]'));
      const selectedTypes = rows.map(row =>
        row.querySelector('[data-comparison-field="type"]')?.value || '').filter(Boolean);
      rows.forEach(row => {
        const ownType = row.querySelector('[data-comparison-field="type"]')?.value || '';
        row.querySelector('[data-comparison-field="type"]')?.querySelectorAll('option').forEach(option => {
          const occupiedElsewhere = selectedTypes.includes(option.value) && option.value !== ownType;
          option.hidden = occupiedElsewhere;
          option.disabled = occupiedElsewhere;
        });
      });
      refreshMarketComparisonAddButton();
    }

    function addMarketComparisonType() {
      const host = document.getElementById('marketComparisonTypes');
      const rows = normalizeMarketComparisonRows(readMarketComparisonRows());
      const guard = marketComparisonAddGuard(rows);
      if (guard.filled >= 3) return;
      if (guard.hasBlank) {
        // The blank row is the one to fill; adding another would just stack
        // empty slots and look like a dead button.
        const blank = Array.from(
          (host || document).querySelectorAll('[data-comparison-row]'))
          .find(row => !(row.querySelector('[data-comparison-field="type"]')?.value || ''));
        blank?.scrollIntoView({ block: 'nearest' });
        blank?.querySelector('[data-comparison-field="type"]')?.focus();
        return;
      }
      rows.push({ type: '', operation: '', stars: '' });
      renderMarketComparisonTypes(rows);
      try {
        persistMarketStudyFromDom();
      } catch (error) {
        console.error('market comparison persist failed', error);
      }
    }

    function marketCompetitorDistrictNames() {
      return Array.from(
        document.querySelectorAll('#marketCompetitorDistrictChips [data-scope-district]'))
        .map(element => element.dataset.scopeDistrict || '')
        .filter(Boolean);
    }

    function renderMarketCompetitorDistricts(names) {
      const host = document.getElementById('marketCompetitorDistrictChips');
      if (!host) return;
      const selected = [];
      (Array.isArray(names) ? names : []).forEach(item => {
        const name = String(item || '').trim();
        if (name && !selected.includes(name)) selected.push(name);
      });
      if (!selected.length) {
        const projectDistrict = (document.querySelector(
          '#tenantProjectForm [data-key="district"]')?.value
          || tenantProjectData.district || '').trim();
        if (projectDistrict) selected.push(projectDistrict);
      }
      host.innerHTML = selected.map(name =>
        '<span class="market-scope-chip" data-scope-district="' + escapeHtml(name) + '">' +
        escapeHtml(name) +
        '<button type="button" class="market-scope-chip-remove" onclick="removeMarketCompetitorDistrict(this)">حذف</button>' +
        '</span>'
      ).join('') || '<div class="tenant-hint">لا توجد أحياء في نطاق المنافسين</div>';
      refreshDynamicI18n(host);
    }

    function addMarketCompetitorDistrict() {
      const input = document.getElementById('marketCompetitorDistrictInput');
      const value = String(input?.value || '').trim();
      if (input) input.value = '';
      if (!value) return;
      const names = marketCompetitorDistrictNames();
      if (names.includes(value)) return;
      names.push(value);
      renderMarketCompetitorDistricts(names);
      if (typeof persistMarketStudyFromDom === 'function') persistMarketStudyFromDom();
    }

    function removeMarketCompetitorDistrict(button) {
      const name = button?.closest('[data-scope-district]')?.dataset.scopeDistrict || '';
      const names = marketCompetitorDistrictNames().filter(item => item !== name);
      renderMarketCompetitorDistricts(names);
      if (typeof persistMarketStudyFromDom === 'function') persistMarketStudyFromDom();
    }

    function marketUnitTypeGroups() {
      return typeof MARKET_UNIT_TYPE_GROUPS !== 'undefined'
        ? MARKET_UNIT_TYPE_GROUPS : [];
    }

    function collectMarketUnitTypeSelections() {
      return Array.from(document.querySelectorAll(
        '#marketCompetitorUnitTypes [data-unit-type]'))
        .filter(input => input.checked)
        .map(input => input.dataset.unitType || '')
        .filter(Boolean);
    }

    function renderMarketUnitTypes(selected) {
      const host = document.getElementById('marketCompetitorUnitTypes');
      if (!host) return;
      const picked = new Set((Array.isArray(selected) ? selected : [])
        .map(item => String(item || '').trim()).filter(Boolean));
      const groups = marketUnitTypeGroups();
      host.innerHTML = groups.length ? groups.map(group =>
        '<div class="market-unit-type-group">' +
        '<div class="market-unit-type-label">' + escapeHtml(group.label) + '</div>' +
        '<div class="market-comparison-multi-options">' +
        group.options.map(option =>
          '<label><input type="checkbox" data-unit-type="' + escapeHtml(option) + '"' +
          (picked.has(option) ? ' checked' : '') + '><span>' + escapeHtml(option) +
          '</span></label>').join('') +
        '</div></div>').join('')
        : '<div class="tenant-hint">لا توجد أنواع عقار محددة</div>';
      refreshDynamicI18n(host);
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
        ? 'غير متاح' : formatExactSystemNumber(Number(value), true);
      const sourceLabel = benchmark.source_label || 'صفقات مرجعية من ملفات البيانات';
      host.innerHTML = '<div class="market-transaction-benchmarks"><h4>' + escapeHtml(sourceLabel) + '</h4>' +
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
