/* 03-executive-classification.js - index.html lines 9748-10647, shared global scope, classic scripts in order */

    // ── فريق العمل inside a project file ──────────────────────────────────────
    // The company library is shared by every file. A file may drop a library entity, override the
    // role it plays here, or add an entity that belongs to this project alone. All three live in
    // draft_data so nothing leaks between projects.
    function getProjectTeamState() {
      const parsed = parseStoredLandTable(tenantProjectData.team_selection) || {};
      return {
        excluded: Array.isArray(parsed.excluded) ? parsed.excluded.map(String) : [],
        roles: (parsed.roles && typeof parsed.roles === 'object') ? parsed.roles : {},
        local: Array.isArray(parsed.local) ? parsed.local : [],
      };
    }

    function setProjectTeamState(state) {
      tenantProjectData.team_selection = state;
      const hidden = document.getElementById('projectTeamData');
      if (hidden) hidden.value = JSON.stringify(state);
      triggerAutoSaveDraft();
    }

    let editingProjectLocalTeamId = null;
    let projectLocalTeamDraft = null;

    const EXECUTIVE_CONTENT_BLOCKS = [
      { key: 'brief', label: 'نبذة المشروع' },
      { key: 'opportunity', label: 'الفرصة الاستثمارية' },
      { key: 'features', label: 'المميزات وفرص الاستثمار' },
      { key: 'risks', label: 'دراسة المخاطر' },
      { key: 'summary', label: 'الملخص التنفيذي' }
    ];

    function emptyExecutiveContentState() {
      return {
        brief: '',
        opportunity: '',
        features: '',
        risks: '',
        summary: ''
      };
    }

    function getExecutiveContentState() {
      const parsed = parseStoredLandTable(tenantProjectData.executive_content);
      const base = emptyExecutiveContentState();
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return base;
      const next = { ...base };
      EXECUTIVE_CONTENT_BLOCKS.forEach(item => {
        next[item.key] = typeof parsed[item.key] === 'string' ? parsed[item.key] : (base[item.key] || '');
      });
      return next;
    }

    function setExecutiveContentState(state) {
      const next = { ...emptyExecutiveContentState(), ...(state || {}) };
      delete next.swot;
      tenantProjectData.executive_content = next;
      const hidden = document.getElementById('executiveContentData');
      if (hidden) hidden.value = JSON.stringify(next);
      triggerAutoSaveDraft();
    }

    function collectExecutiveContentFromDom() {
      const state = emptyExecutiveContentState();
      EXECUTIVE_CONTENT_BLOCKS.forEach(item => {
        state[item.key] = document.getElementById('executiveText_' + item.key)?.value || '';
      });
      return state;
    }

    function persistExecutiveContentFromDom() {
      if (!document.getElementById('executiveContentData')) return;
      setExecutiveContentState(collectExecutiveContentFromDom());
    }

    function collectExecutiveFinancialIndicators() {
      const read = (id) => (document.getElementById(id)?.textContent || '').trim();
      const indicators = {
        projectCostBeforeFinance: read('resProjectCostBeforeFinance'),
        projectCost: read('resProjectCost'),
        totalInvestment: read('resTotalInvestmentCost'),
        saleRevenue: read('resSaleRevenue'),
        revenueY1: read('resRevenueY1'),
        noiY1: read('resNOIY1'),
        fullOccupancyNoi: read('resFullOccupancyNOI'),
        terminal: read('resTerminal'),
        financeCost: read('resFinanceCost'),
        roi: read('resROI'),
        projectIrr: read('resProjectIRR'),
        equityIrr: read('resIRR'),
        payback: read('resPayback'),
        equityPayback: read('resEquityPayback'),
        landEquity: read('resLandEquity'),
        cashEquity: read('resCashEquity'),
        equityRequired: read('resEquityRequired')
      };
      return Object.fromEntries(Object.entries(indicators).filter(([, value]) => value && value !== '0' && value !== '0%'));
    }

    function collectExecutiveTeamFacts() {
      const state = typeof getProjectTeamState === 'function'
        ? getProjectTeamState()
        : { excluded: [], roles: {}, local: [] };
      const excluded = new Set((state.excluded || []).map(String));
      const library = (Array.isArray(tenantTeamEntities) ? tenantTeamEntities : [])
        .filter(entity => entity && !excluded.has(String(entity.id)))
        .map(entity => ({
          name: entity.name || '',
          role: (state.roles && (state.roles[entity.id] || state.roles[String(entity.id)])) || entity.role || '',
          brief: entity.brief || '',
          experienceYears: entity.experienceYears || '',
          notableProjects: entity.notableProjects || ''
        }))
        .filter(item => item.name);
      const local = (state.local || [])
        .map(entity => ({
          name: entity.name || '',
          role: entity.role || '',
          brief: entity.brief || '',
          experienceYears: entity.experienceYears || '',
          notableProjects: entity.notableProjects || ''
        }))
        .filter(item => item.name);
      return library.concat(local);
    }

    function collectExecutiveTimelineFacts() {
      const rows = typeof collectTimelineRows === 'function' ? collectTimelineRows() : [];
      return rows.filter(row => (row.name || '').trim()).map(row => ({
        name: row.name || '',
        year: row.year || '',
        quarter: row.quarter || '',
        duration: row.duration || '',
        end: [row.endYear, row.endQuarter].filter(Boolean).join(' '),
        notes: row.notes || ''
      }));
    }

    function collectExecutiveContentFacts() {
      const field = (key) => {
        const input = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        if (input && String(input.value || '').trim()) return input.value;
        return tenantProjectData[key] || '';
      };
      const market = typeof getMarketStudyState === 'function' ? getMarketStudyState() : {};
      const executive = getExecutiveContentState();
      const components = (typeof getComponentRowsData === 'function' ? getComponentRowsData() : [])
        .map(row => ({
          name: row.name || '',
          useType: row.useType || '',
          units: row.units || '',
          builtArea: row.builtArea || '',
          revenueArea: row.revenueArea || ''
        }))
        .filter(row => row.name);
      const competitors = (Array.isArray(market.competitors) ? market.competitors : [])
        .filter(row => row && row.name)
        .slice(0, 8)
        .map(row => {
          const priceRange = [row.price_from, row.price_to].filter(Boolean).join(' إلى ');
          return {
            name: row.name || '',
            projectType: row.project_type || '',
            status: row.status || '',
            price: [row.price_type, priceRange || row.price_value].filter(Boolean).join(' '),
            operationType: row.operation_type || '',
            area: row.area_mode === 'range' || row.area_from || row.area_to
              ? [row.area_from, row.area_to].filter(Boolean).join(' إلى ')
              : (row.area_sqm || ''),
            source: row.source || ''
          };
        });
      return {
        projectName: tenantProjectData.project_name || field('project_name'),
        projectType: typeof selectedProjectTypeMains === 'function' ? selectedProjectTypeMains() : (tenantProjectData.project_type || ''),
        projectSubtype: typeof selectedProjectSubtypes === 'function' ? selectedProjectSubtypes() : (tenantProjectData.project_subtype || ''),
        activityClass: field('activity_class'),
        projectLevel: field('project_level'),
        projectStage: field('project_stage'),
        projectIdea: field('project_idea'),
        targetAudience: typeof groupedAudienceSelection === 'function' ? groupedAudienceSelection() : (tenantProjectData.target_audience || ''),
        city: field('city'),
        district: field('district'),
        locationAddress: field('location_address'),
        locationDetail: field('location_detail'),
        mainRoads: field('main_roads'),
        secondaryRoads: field('secondary_roads'),
        nearbyLandmarks: field('nearby_landmarks'),
        cityLandmarks: field('city_landmarks'),
        catchmentAreas: field('catchment_areas'),
        siteAnalysis: field('site_analysis'),
        plotNumber: field('plot_number_croquis') || field('plot_number'),
        planNumber: field('plan_number'),
        deedNumber: field('deed_number'),
        deedDate: field('deed_date'),
        croquisLandArea: field('croquis_land_area'),
        approvedFinancialArea: field('approved_financial_area'),
        boundaryLengths: field('boundary_lengths'),
        surroundingStreets: field('surrounding_streets'),
        facadesCount: field('facades_count'),
        facadesDirections: field('facades_directions'),
        buildingRatioCoverage: field('building_ratio_coverage'),
        setbacks: field('setbacks'),
        maxFloorsHeight: field('max_floors_height'),
        approvedFloorCount: field('approved_floor_count'),
        approvedCoverageRatio: field('approved_coverage_ratio'),
        allowedUses: field('allowed_uses'),
        landUseStatus: tenantProjectData.land_use_status || '',
        infrastructure: field('infrastructure'),
        buildingSystem: field('building_system'),
        regulatoryConstraints: field('regulatory_constraints'),
        landSummary: field('land_and_building_summary'),
        timelineStartYear: document.getElementById('tlStartYear')?.value || tenantProjectData.timeline_start_year || '',
        timelineYears: document.getElementById('tlYears')?.value || tenantProjectData.timeline_years || '',
        timelineStages: collectExecutiveTimelineFacts(),
        components,
        financialIndicators: collectExecutiveFinancialIndicators(),
        team: collectExecutiveTeamFacts(),
        marketSummary: market.summary || {},
        marketSwot: market.swot || {},
        marketDecision: market.decision || '',
        marketDisclaimer: market.disclaimer || '',
        marketOneBlockSummary: market.one_block_summary || '',
        competitors,
        generatedBlocks: {
          brief: executive.brief || '',
          opportunity: executive.opportunity || '',
          features: executive.features || '',
          risks: executive.risks || ''
        }
      };
    }

    function formatExecutiveFact(value) {
      if (Array.isArray(value)) return value.filter(Boolean).join('، ');
      if (value && typeof value === 'object') return Object.values(value).filter(Boolean).join('، ');
      return String(value || '').trim();
    }

    function renderExecutiveLinkedFacts() {
      const host = document.getElementById('executiveLinkedFacts');
      if (!host) return;
      const facts = collectExecutiveContentFacts();
      const rows = [
        ['اسم المشروع', facts.projectName],
        ['النوع', formatExecutiveFact(facts.projectType)],
        ['الأنواع الفرعية', formatExecutiveFact(facts.projectSubtype)],
        ['تصنيف النشاط', facts.activityClass],
        ['المستوى', facts.projectLevel],
        ['المرحلة', facts.projectStage],
        ['فكرة المشروع', facts.projectIdea],
        ['الفئة المستهدفة', formatExecutiveFact(facts.targetAudience)],
        ['المدينة', facts.city],
        ['الحي', facts.district],
        ['مساحة الأرض', facts.croquisLandArea],
        ['المساحة المعتمدة', facts.approvedFinancialArea],
        ['الاستخدامات المسموحة', facts.allowedUses],
        ['سنة البداية', facts.timelineStartYear],
        ['مدة المشروع', facts.timelineYears],
        ['قرار السوق', facts.marketDecision]
      ];
      host.innerHTML = rows.map(([label, value]) =>
        '<div class="executive-fact"><strong>' + escapeHtml(label) + '</strong>' +
        escapeHtml(value || 'غير متوفر من المدخلات المعتمدة') + '</div>'
      ).join('');
    }

    function applyExecutiveContentState(state) {
      const next = { ...emptyExecutiveContentState(), ...(state || {}) };
      delete next.swot;
      EXECUTIVE_CONTENT_BLOCKS.forEach(item => {
        const input = document.getElementById('executiveText_' + item.key);
        if (input) input.value = next[item.key] || '';
      });
      const hidden = document.getElementById('executiveContentData');
      if (hidden) hidden.value = JSON.stringify(next);
      tenantProjectData.executive_content = next;
    }

    function addVisualConceptSection(form, before) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-visual-concept'; // id="section-visual-concept"
      div.dataset.section = 'section-visual-concept';
      div.appendChild(createProjectSectionHeader('section-visual-concept', 'التصور البصري'));

      const body = document.createElement('div');
      body.className = 'visual-concept-body';
      body.style.gridColumn = '1 / -1';
      body.innerHTML = `
        <div id="visualConceptHome" class="visual-concept-home" data-visual-concept-view="home">
          <div class="visual-concept-home-grid">
            <button type="button" class="visual-concept-home-card" data-visual-concept-target="external">
              <span class="visual-concept-home-badge">القسم الأول</span>
              <h3>التصور الخارجي</h3>
              <img id="visualConceptHomeCoverPreview" class="visual-concept-home-preview" alt="معاينة الصورة الرئيسية" hidden>
              <span class="visual-concept-home-status" id="visualConceptHomeExternalStatus">جاهز للعمل</span>
            </button>
            <button type="button" class="visual-concept-home-card" data-visual-concept-target="internal">
              <span class="visual-concept-home-badge">القسم الثاني</span>
              <h3>التصور الداخلي</h3>
              <span class="visual-concept-home-status" id="visualConceptHomeInternalStatus">جاهز للعمل</span>
            </button>
            <button type="button" class="visual-concept-home-card" data-visual-concept-target="plans2d">
              <span class="visual-concept-home-badge">القسم الثالث</span>
              <h3>المخططات</h3>
              <span class="visual-concept-home-status" id="visualConceptHomePlansStatus">لا توجد مخططات</span>
            </button>
          </div>
        </div>
        <div id="visualConceptExternalView" class="visual-concept-section" data-visual-concept-view="external" hidden>
          <div class="visual-concept-view-head">
            <div>
              <h3>التصور الخارجي</h3>
            </div>
            <button type="button" class="btn ghost" onclick="showVisualConceptView('home')">العودة إلى أقسام التصور البصري</button>
          </div>
          <div id="visualConceptMissing" class="visual-concept-missing" hidden></div>
          <div class="visual-concept-card">
            <div class="visual-concept-head">
              <h3>الصورة المرجعية</h3>
            </div>
            <input id="visualConceptStyleReferenceInput" type="file" multiple accept="image/png,image/jpeg,image/jpg,image/webp">
            <div id="visualConceptStyleReferencePreview" class="visual-concept-preview" style="margin-top:12px">لم تُرفع صور مرجعية.</div>
            <div class="visual-concept-actions">
              <button type="button" class="btn ghost small" onclick="clearVisualConceptStyleReference()">حذف الصور المرجعية</button>
            </div>
          </div>
          <div id="visualConceptWorkspace" class="visual-concept-page"></div>
        </div>
        <div id="visualConceptInternalView" class="visual-concept-section" data-visual-concept-view="internal" hidden>
          <div class="visual-concept-view-head">
            <div>
              <h3>التصور الداخلي</h3>
            </div>
            <button type="button" class="btn ghost" onclick="showVisualConceptView('home')">العودة إلى أقسام التصور البصري</button>
          </div>
          <div class="visual-concept-card">
            <label>المكون</label>
            <select id="visualConceptInteriorComponentSelect"></select>
            <p class="tenant-hint" id="visualConceptInteriorHint"></p>
          </div>
          <div class="visual-concept-card" id="visualConceptInteriorReferenceCard" hidden>
            <div class="visual-concept-head">
              <h3>الصور المرجعية لهذا المكون</h3>
            </div>
            <input id="visualConceptInteriorReferenceInput" type="file" multiple accept="image/png,image/jpeg,image/jpg,image/webp">
            <div id="visualConceptInteriorReferencePreview" class="visual-concept-preview" style="margin-top:12px">لم تُرفع صور مرجعية لهذا المكون.</div>
            <div class="visual-concept-actions">
              <button type="button" class="btn ghost small" onclick="clearVisualConceptInteriorReferences()">حذف صور هذا المكون</button>
            </div>
          </div>
          <div id="visualConceptInternalWorkspace" class="visual-concept-page"></div>
        </div>
        <div id="visualConceptPlansView" class="visual-concept-section" data-visual-concept-view="plans2d" hidden>
          <div class="visual-concept-view-head">
            <div>
              <h3>المخططات</h3>
            </div>
            <button type="button" class="btn ghost" onclick="showVisualConceptView('home')">العودة إلى أقسام التصور البصري</button>
          </div>
          <div class="visual-concept-mode-selector visual-concept-plans-tabs">
            <button type="button" class="visual-concept-mode-btn active" data-visual-plans-tab="generate">توليد المخططات</button>
            <button type="button" class="visual-concept-mode-btn" data-visual-plans-tab="upload">رفع المخططات</button>
          </div>
          <div id="visualConceptPlansGeneratePanel" data-visual-plans-panel="generate">
            <div class="visual-concept-card plans-workflow-card" id="visualConceptPlansWizard">
              <div class="visual-concept-head">
                <div>
                  <h3 data-i18n="plans.workflow_title">سير عمل المخططات</h3>
                  <p class="tenant-hint" data-i18n="plans.workflow_status_label">حالة سير العمل</p>
                </div>
                <span class="visual-concept-status pending" id="visualConceptPlansWorkflowStatus"></span>
              </div>
              <ol class="plans-workflow-steps" id="visualConceptPlansWorkflowSteps">
                <li data-plans-step="verify"><span data-i18n="plans.step_verify">التحقق</span></li>
                <li data-plans-step="distribute"><span data-i18n="plans.step_distribute">التوزيع</span></li>
                <li data-plans-step="approve"><span data-i18n="plans.step_approve">الاعتماد</span></li>
                <li data-plans-step="generate"><span data-i18n="plans.step_generate">التوليد</span></li>
              </ol>

              <section class="plans-workflow-panel" data-plans-workflow-panel="verify">
                <div class="plans-workflow-panel-head">
                  <h4 data-i18n="plans.verify_title">التحقق من بيانات المشروع</h4>
                  <button type="button" class="btn primary small" id="visualConceptPlansVerifyBtn" data-i18n="plans.verify_button">تحقق</button>
                </div>
                <p class="tenant-hint" id="visualConceptPlansVerifySummary"></p>
                <div class="plans-workflow-notice" id="visualConceptPlansBlocking" hidden></div>
                <div class="plans-workflow-table-wrap">
                  <table class="plans-workflow-table plans-check-table">
                    <thead><tr>
                      <th data-i18n="plans.check_item">البند</th>
                      <th data-i18n="plans.check_project">بيانات المشروع</th>
                      <th data-i18n="plans.check_reference">المرجع</th>
                      <th data-i18n="plans.check_result">النتيجة</th>
                      <th data-i18n="plans.check_note">الملاحظة</th>
                    </tr></thead>
                    <tbody id="visualConceptPlansVerifyRows"></tbody>
                  </table>
                </div>
              </section>

              <section class="plans-workflow-panel" data-plans-workflow-panel="distribute">
                <div class="plans-workflow-panel-head">
                  <h4 data-i18n="plans.distribution_title">توزيع المكونات والأدوار</h4>
                  <div class="visual-concept-actions">
                    <button type="button" class="btn primary small" id="visualConceptPlansDistributeBtn" data-i18n="plans.distribute_button">اقتراح التوزيع</button>
                    <button type="button" class="btn ghost small" id="visualConceptPlansRecheckBtn" data-i18n="plans.recheck_button">مراجعة التوزيع</button>
                  </div>
                </div>
                <label data-i18n="plans.feedback_label">ملاحظات العميل</label>
                <textarea id="visualConceptPlansFeedback" rows="3" data-i18n-ph="plans.feedback_placeholder" placeholder="ملاحظات التوزيع"></textarea>
                <div class="plans-workflow-table-wrap">
                  <table class="plans-workflow-table plans-distribution-table">
                    <thead><tr>
                      <th data-i18n="plans.building">المبنى</th>
                      <th data-i18n="plans.floor_span">الدور أو النطاق</th>
                      <th data-i18n="plans.component">المكون</th>
                      <th data-i18n="plans.use">الاستخدام</th>
                      <th data-i18n="plans.units_per_floor">وحدات بالدور</th>
                      <th data-i18n="plans.total_units">إجمالي الوحدات</th>
                      <th data-i18n="plans.floor_area">مساحة الدور</th>
                      <th data-i18n="plans.group_area">مساحة المجموعة</th>
                      <th data-i18n="plans.services_share">الحركة والخدمات</th>
                      <th data-i18n="plans.notes">ملاحظات</th>
                    </tr></thead>
                    <tbody id="visualConceptPlansDistributionRows"></tbody>
                  </table>
                </div>
                <div class="plans-workflow-subhead" data-i18n="plans.reconciliation_title">المطابقة مع الدراسة المالية</div>
                <div class="plans-workflow-table-wrap">
                  <table class="plans-workflow-table plans-reconciliation-table">
                    <thead><tr>
                      <th data-i18n="plans.component">المكون</th>
                      <th data-i18n="plans.required_units">الوحدات المطلوبة</th>
                      <th data-i18n="plans.proposed_units">الوحدات المقترحة</th>
                      <th data-i18n="plans.required_area">المساحة المطلوبة</th>
                      <th data-i18n="plans.proposed_area">المساحة المقترحة</th>
                      <th data-i18n="plans.difference">الفرق</th>
                    </tr></thead>
                    <tbody id="visualConceptPlansReconciliationRows"></tbody>
                  </table>
                </div>
                <p class="tenant-hint" id="visualConceptPlansDistributionNotes"></p>
              </section>

              <section class="plans-workflow-panel" data-plans-workflow-panel="approve">
                <div class="plans-workflow-panel-head">
                  <h4 data-i18n="plans.approval_title">اعتماد التوزيع</h4>
                  <button type="button" class="btn primary small" id="visualConceptPlansApproveBtn" data-i18n="plans.approve_button">اعتماد التوزيع</button>
                </div>
                <p class="tenant-hint" id="visualConceptPlansApprovalStatus"></p>
              </section>

              <section class="plans-workflow-panel" data-plans-workflow-panel="generate">
                <div class="plans-workflow-panel-head">
                  <h4 data-i18n="plans.generate_title">توليد المخططات الثلاثة</h4>
                  <button type="button" class="btn primary small" id="visualConceptPlansGenerateAllBtn" data-i18n="plans.generate_all_button">توليد الكل</button>
                </div>
                <p class="tenant-hint" id="visualConceptPlansSpecStatus"></p>
                <div class="plans-disclaimer" id="visualConceptPlansDisclaimer" data-i18n="plans.disclaimer">تصور مبدئي لدراسة الفرصة الاستثمارية — غير مخصص للتنفيذ</div>
                <div id="visualConceptPlansWorkflowImages" class="plans-workflow-results"></div>
              </section>
            </div>
            <div class="visual-concept-card plans-legacy-extra" aria-hidden="true">
              <div class="visual-concept-head">
                <h3 data-i18n="plans.extra_title">مخططات إضافية</h3>
                <span class="visual-concept-status pending" id="visualConceptPlansCount"></span>
              </div>
              <div class="visual-concept-actions">
                <button type="button" class="btn primary small" id="visualConceptAddPlanBtn" data-i18n="plans.add_button">إضافة مخطط</button>
              </div>
            </div>
            <div id="visualConceptPlansGenerateList" class="visual-concept-page plans-legacy-extra" aria-hidden="true"></div>
          </div>
          <div id="visualConceptPlansUploadPanel" data-visual-plans-panel="upload" hidden>
            <div class="visual-concept-card">
              <div class="visual-concept-head">
                <h3>رفع مخططات العميل</h3>
              </div>
              <input id="visualConceptPlansUploadInput" type="file" multiple accept="image/png,image/jpeg,image/jpg,image/webp">
            </div>
            <div id="visualConceptPlansUploadList" class="visual-concept-page"></div>
          </div>
          <div class="visual-concept-actions">
            <button type="button" class="btn ghost" onclick="saveProjectAsDraft()">حفظ كمسودة</button>
          </div>
        </div>
        <input type="hidden" data-key="visual_concept" data-type="text" id="visualConceptData">
      `;
      div.appendChild(body);
      if (before) form.insertBefore(div, before);
      else form.appendChild(div);

      body.querySelectorAll('[data-visual-concept-target]').forEach(button => {
        button.addEventListener('click', () => showVisualConceptView(button.dataset.visualConceptTarget));
      });
      const refInput = body.querySelector('#visualConceptStyleReferenceInput');
      if (refInput) refInput.addEventListener('change', () => uploadVisualConceptStyleReference(refInput));
      const intInput = body.querySelector('#visualConceptInteriorReferenceInput');
      if (intInput) intInput.addEventListener('change', () => uploadVisualConceptInteriorReferences(intInput));
      const plansInput = body.querySelector('#visualConceptPlansUploadInput');
      if (plansInput) plansInput.addEventListener('change', () => uploadVisualConceptPlanImages(plansInput));
      const addPlanButton = body.querySelector('#visualConceptAddPlanBtn');
      if (addPlanButton) addPlanButton.addEventListener('click', () => addVisualConceptPlan());
      const planWorkflowActions = [
        ['#visualConceptPlansVerifyBtn', 'verifyVisualConceptPlans'],
        ['#visualConceptPlansDistributeBtn', 'distributeVisualConceptPlans'],
        ['#visualConceptPlansRecheckBtn', 'recheckVisualConceptPlans'],
        ['#visualConceptPlansApproveBtn', 'approveVisualConceptPlansDistribution'],
        ['#visualConceptPlansGenerateAllBtn', 'generateAllVisualConceptPlans']
      ];
      planWorkflowActions.forEach(([selector, functionName]) => {
        const button = body.querySelector(selector);
        if (button) button.addEventListener('click', () => {
          if (typeof window[functionName] === 'function') window[functionName]();
        });
      });
      body.querySelectorAll('[data-visual-plans-tab]').forEach(button => {
        button.addEventListener('click', () => setVisualConceptPlansTab(button.getAttribute('data-visual-plans-tab')));
      });
      const intSelect = body.querySelector('#visualConceptInteriorComponentSelect');
      if (intSelect) {
        intSelect.addEventListener('change', () => {
          tenantVisualConceptState.selectedInteriorComponentId = intSelect.value || '';
          markVisualConceptDirty();
          renderVisualConceptPage();
        });
      }
    }

    function addExecutiveContentSection(form, before) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-executive-content';
      div.dataset.section = 'section-executive-content';
      div.appendChild(createProjectSectionHeader('section-executive-content', 'المحتوى التنفيذي'));
      const body = document.createElement('div');
      body.className = 'executive-content-body';
      const generated = EXECUTIVE_CONTENT_BLOCKS.map(item => {
        const rows = item.key === 'summary' ? '22' : (item.key === 'risks' ? '12' : (item.key === 'brief' ? '7' : '5'));
        return '<div class="executive-block" data-executive-block="' + item.key + '">' +
          '<h4>' + item.label + '</h4>' +
          '<div class="executive-actions">' +
          '<button type="button" class="btn primary small" data-executive-generate="' + item.key + '">توليد</button>' +
          '</div>' +
          '<p class="tenant-hint executive-note" id="executiveNote_' + item.key + '"></p>' +
          '<textarea id="executiveText_' + item.key + '" rows="' + rows + '"></textarea>' +
          '</div>';
      }).join('');
      body.innerHTML =
        generated +
        '<input type="hidden" data-key="executive_content" data-type="text" id="executiveContentData">';
      div.appendChild(body);
      if (before) form.insertBefore(div, before);
      else form.appendChild(div);
      body.querySelectorAll('textarea').forEach(input => input.addEventListener('input', persistExecutiveContentFromDom));
      body.querySelectorAll('[data-executive-generate]').forEach(button => {
        button.addEventListener('click', () => generateExecutiveContentBlock(button.dataset.executiveGenerate));
      });
    }

    async function generateExecutiveContentBlock(key) {
      const spec = EXECUTIVE_CONTENT_BLOCKS.find(item => item.key === key);
      if (!spec) return;
      const note = document.getElementById('executiveNote_' + key);
      const button = document.querySelector('[data-executive-generate="' + key + '"]');
      if (typeof persistMarketStudyFromDom === 'function') persistMarketStudyFromDom();
      if (typeof persistFinancialStudyDraftState === 'function') persistFinancialStudyDraftState();
      persistExecutiveContentFromDom();
      const state = getExecutiveContentState();
      if (note) note.textContent = '';
      if (button) button.disabled = true;
      showLoader('توليد ' + spec.label, 'جاري صياغة النص من المدخلات المعتمدة...', 18);
      try {
        const res = await api('POST', '/api/executive-content/generate', {
          block: key,
          facts: collectExecutiveContentFacts(),
          currentText: state[key]
        });
        if (!res || !res.success) {
          const message = (res && res.error) || 'تعذر توليد النص. لم يُستبدل النص الحالي.';
          if (note) note.textContent = message;
          toast(message);
          return;
        }
        state[key] = res.text || '';
        const targetInput = document.getElementById('executiveText_' + key);
        if (targetInput) targetInput.value = state[key];
        applyExecutiveContentState(state);
        persistExecutiveContentFromDom();
        if (note) note.textContent = 'تم التوليد.';
        toast('تم توليد ' + spec.label);
        updateLoaderProgress(100, 'اكتمل ' + spec.label);
      } catch (error) {
        if (note) note.textContent = error.message || 'تعذر توليد النص';
        toast(error.message || 'تعذر توليد النص');
      } finally {
        hideLoader();
        if (button) button.disabled = false;
      }
    }

    function addTeamSection(form, before) {
      const div = document.createElement('div');
      div.className = 'tenant-form-section';
      div.id = 'section-team';
      div.dataset.section = 'section-team';
      div.appendChild(createProjectSectionHeader('section-team', 'فريق العمل'));
      // An active section is a two-column grid meant for form fields, so plain children land in
      // half-width cells and leave a dead column beside them. One full-width wrapper keeps the
      // internal layout here instead of leaking into the grid.
      const body = document.createElement('div');
      body.style.gridColumn = '1 / -1';
      body.innerHTML = `
        <div id="projectTeamLibrary"></div>
        <h4 id="projectTeamLocalTitle" style="margin:18px 0 8px;color:var(--p);font-size:14px">جهات خاصة بهذا المشروع</h4>
        <div id="projectTeamLocal"></div>
        <button type="button" class="btn ghost small" style="margin-top:10px" onclick="addLocalTeamEntity()">+ إضافة جهة لهذا المشروع</button>
        <input type="hidden" data-key="team_selection" data-type="text" id="projectTeamData">
      `;
      div.appendChild(body);
      if (before) form.insertBefore(div, before);
      else form.appendChild(div);
    }

    const MARKET_STUDY_SUMMARY_SECTIONS = [
      { key: 'market_definition', label: 'تعريف السوق' },
      { key: 'city_position', label: 'وضع المدينة' },
      { key: 'sector_performance', label: 'أداء القطاع' },
      { key: 'supply', label: 'العرض' },
      { key: 'demand', label: 'الطلب' },
      { key: 'competition', label: 'المنافسة' },
      { key: 'market_gap', label: 'الفجوة السوقية' },
      { key: 'recommendation', label: 'التوصية' },
      { key: 'risks', label: 'المخاطر' }
    ];
    // Older drafts included the decision inside the summary object.
    const MARKET_LEGACY_SUMMARY_SECTIONS = [
      ...MARKET_STUDY_SUMMARY_SECTIONS,
      { key: 'decision', label: 'القرار' }
    ];
    const MARKET_STUDY_SWOT_SECTIONS = [
      { key: 'strengths', label: 'نقاط القوة' },
      { key: 'weaknesses', label: 'نقاط الضعف' },
      { key: 'opportunities', label: 'الفرص' },
      { key: 'threats', label: 'التهديدات' }
    ];
    const MARKET_PROJECT_TYPES = ['سكني', 'تجاري', 'فندقي', 'صناعي ولوجستي'];
    const MARKET_MIXED_TYPE_OPTIONS = MARKET_PROJECT_TYPES.slice();
    const MARKET_SUBTYPES = {
      'سكني': [],
      'تجاري': ['مكاتب', 'تجزئة ومحلات', 'مطاعم ومقاهي', 'مركز تجاري'],
      'فندقي': ['فندق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية'],
      'صناعي ولوجستي': ['مصنع', 'مستودعات', 'مركز لوجستي', 'مجمع صناعي'],
      'متعدد الاستخدامات': ['سكني', 'مكاتب', 'تجزئة ومحلات', 'مطاعم ومقاهي', 'مركز تجاري', 'فندق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية', 'مصنع', 'مستودعات', 'مركز لوجستي', 'مجمع صناعي']
    };
    const MARKET_PROJECT_LEVELS = ['اقتصادي', 'متوسط', 'فوق المتوسط', 'متميز', 'فاخر', 'فائق الفخامة', 'أخرى'];
    const MARKET_SPECIALIZED_CLASS_KINDS = ['فندقي', 'مكاتب', 'صناعي ولوجستي'];
    const MARKET_ACTIVITY_CLASS_LABELS = {
      'فندقي': 'تصنيف النشاط الفندقي',
      'مكاتب': 'تصنيف المكاتب',
      'صناعي ولوجستي': 'تصنيف الصناعي واللوجستي',
      'سكني': 'مستوى المشروع السكني',
      'تجاري': 'مستوى المشروع التجاري',
      'تجزئة': 'مستوى المشروع التجاري',
      'متعدد الاستخدامات': 'مستوى المشروع'
    };
    const MARKET_AUDIENCE_LABELS = {
      'سكني': 'الفئة المستهدفة للسكني',
      'تجاري': 'الفئة المستهدفة للتجاري',
      'تجزئة': 'الفئة المستهدفة للتجزئة والمراكز التجارية',
      'مكاتب': 'الفئة المستهدفة للمكاتب',
      'فندقي': 'الفئة المستهدفة للفندقي',
      'صناعي ولوجستي': 'الفئة المستهدفة للصناعي واللوجستي'
    };
    const MARKET_SUBTYPE_LABELS = {
      'تجاري': 'النوع الفرعي التجاري',
      'فندقي': 'النوع الفرعي الفندقي',
      'صناعي ولوجستي': 'النوع الفرعي الصناعي واللوجستي'
    };
    const MARKET_ACTIVITY_CLASS = {
      'فندقي': ['غير مصنف', 'نجمة واحدة', 'نجمتان', '3 نجوم', '4 نجوم', '5 نجوم', '5 نجوم فاخر', 'منتجع', 'فندق بوتيك', 'شقق مخدومة اقتصادية', 'شقق مخدومة متوسطة', 'شقق مخدومة فاخرة', 'أخرى'],
      'مكاتب': ['فئة C', 'فئة B', 'فئة B+', 'فئة A', 'فئة A+ أو مكاتب مميزة', 'مكاتب مرنة ومشتركة', 'أخرى'],
      'صناعي ولوجستي': ['أساسي', 'قياسي', 'متقدم', 'عالي المواصفات', 'متخصص حسب النشاط', 'منشأة مؤتمتة أو ذكية', 'أخرى']
    };
    const MARKET_GENERAL_AUDIENCE = ['أفراد', 'عائلات', 'مستثمرون', 'شركات', 'جهات حكومية', 'سياح وزوار', 'مشغلون ومستأجرون'];
    const MARKET_AUDIENCE = {
      'سكني': ['أفراد', 'حديثو الزواج', 'العائلات الصغيرة', 'العائلات المتوسطة', 'العائلات الكبيرة', 'كبار السن', 'الطلاب', 'الموظفون', 'التنفيذيون ورجال الأعمال', 'أصحاب الدخل المحدود', 'أصحاب الدخل المتوسط', 'أصحاب الدخل فوق المتوسط', 'أصحاب الدخل المرتفع', 'أصحاب الثروات', 'السعوديون', 'المقيمون', 'الأجانب المؤهلون للتملك', 'زوار المدينة', 'الباحثون عن منزل ثان', 'الباحثون عن مساكن فندقية', 'موظفو الشركات القريبة'],
      'مكاتب': ['رواد الأعمال', 'الشركات الناشئة', 'المنشآت الصغيرة', 'المنشآت المتوسطة', 'الشركات الكبيرة', 'الشركات العالمية', 'المقرات الإقليمية', 'الجهات الحكومية', 'الجهات شبه الحكومية', 'الشركات المهنية والاستشارية', 'شركات التقنية', 'الشركات المالية', 'شركات العقار والإنشاءات', 'الشركات الطبية', 'مكاتب المحاماة والمحاسبة', 'مشغلو المكاتب المشتركة', 'المستقلون', 'المستثمرون العقاريون'],
      'تجزئة': ['متاجر محلية', 'علامات تجارية عالمية', 'مطاعم ومقاهي', 'متاجر فاخرة', 'سوبرماركت', 'صيدليات', 'خدمات يومية', 'مراكز ترفيه', 'عيادات', 'نواد رياضية', 'بنوك وخدمات مالية', 'مشغلو التجزئة'],
      'فندقي': ['سياح الترفيه', 'سياح الأعمال', 'رجال الأعمال والتنفيذيون', 'العائلات', 'الأزواج', 'الزوار الدوليون', 'الزوار المحليون', 'الزوار الخليجيون', 'الحجاج والمعتمرون', 'زوار الفعاليات والمواسم', 'زوار المؤتمرات والمعارض', 'المجموعات السياحية', 'أصحاب الدخل المتوسط', 'أصحاب الدخل المرتفع', 'فئة الفخامة', 'أصحاب الثروات', 'نزلاء الإقامة الطويلة', 'نزلاء الإقامة القصيرة', 'مسافرو الترانزيت', 'أطقم شركات الطيران', 'الرياضيون والفرق الرياضية', 'المرضى ومرافقوهم', 'موظفو الشركات', 'الجهات الحكومية', 'منظمو المؤتمرات والفعاليات', 'مشترو المساكن الفندقية'],
      'صناعي ولوجستي': ['المصانع الصغيرة والمتوسطة', 'الشركات الصناعية الكبرى', 'المستثمرون الصناعيون', 'المصنعون المحليون', 'المصنعون الدوليون', 'شركات الخدمات اللوجستية', 'مشغلو الطرف الثالث 3PL', 'شركات التجارة الإلكترونية', 'شركات التوزيع', 'شركات الاستيراد والتصدير', 'شركات الشحن', 'مشغلو الميل الأخير', 'شركات التخزين الجاف', 'شركات التخزين المبرد', 'الصناعات الغذائية', 'الصناعات الدوائية', 'الصناعات الطبية', 'الصناعات الخفيفة', 'الصناعات المتوسطة', 'الصناعات الثقيلة', 'الصناعات التقنية والإلكترونية', 'صناعة السيارات وقطع الغيار', 'مواد البناء', 'الشركات المرتبطة بالموانئ', 'الشركات المرتبطة بالمطارات', 'الجهات الحكومية', 'المستأجرون الصناعيون', 'مشترو المستودعات أو المصانع']
    };
    const MARKET_PRICE_TYPES = {
      'بيع': ['سعر الوحدة', 'سعر المتر المربع', 'متوسط سعر الوحدة', 'متوسط سعر المتر', 'يبدأ من', 'نطاق سعري', 'أخرى'],
      'إيجار': ['إيجار الوحدة الشهري', 'إيجار الوحدة السنوي', 'إيجار المتر الشهري', 'إيجار المتر السنوي', 'متوسط إيجار الوحدة', 'متوسط إيجار المتر', 'يبدأ من', 'نطاق سعري', 'أخرى'],
      'تشغيل فندقي': ['سعر الليلة', 'متوسط سعر الغرفة ADR', 'الإيراد لكل غرفة RevPAR', 'متوسط الإقامة الشهرية', 'يبدأ من', 'نطاق أسعار الغرف', 'أخرى'],
      'أخرى': ['قيمة واحدة', 'نطاق سعري', 'أخرى']
    };
    const MARKET_RANGE_PRICE_TYPES = ['نطاق سعري', 'نطاق أسعار الغرف'];
    const MARKET_COMPETITOR_CLASSIFICATIONS = ['مباشر', 'غير مباشر', 'مرجعي'];
    let marketSummaryPending = null;

    function marketAudienceKind(label) {
      const text = String(label || '').trim();
      if (['مكاتب', 'إداري'].includes(text)) return 'مكاتب';
      if (['تجزئة ومحلات', 'مطاعم ومقاهي', 'مركز تجاري', 'تجاري'].includes(text)) return 'تجزئة';
      if (['فندق', 'شقق مخدومة', 'منتجع', 'مساكن فندقية', 'فندقي'].includes(text)) return 'فندقي';
      if (['مصنع', 'مستودعات', 'مركز لوجستي', 'مجمع صناعي', 'صناعي ولوجستي', 'صناعي', 'لوجستي'].includes(text)) return 'صناعي ولوجستي';
      if (text === 'سكني') return 'سكني';
      return '';
    }

    function normalizeProjectTypeValues(raw) {
      const listed = parseSelectedMarketList(raw);
      const values = [];
      listed.forEach(value => {
        if (value === 'أخرى' || value === 'متعدد الاستخدامات') {
          selectedMixedComponents().forEach(item => values.push(item));
          return;
        }
        if (MARKET_PROJECT_TYPES.includes(value)) values.push(value);
      });
      return [...new Set(values)];
    }

    function normalizeProjectTypeValue(raw) {
      return normalizeProjectTypeValues(raw)[0] || '';
    }

    function persistProjectTypes(values) {
      const next = normalizeProjectTypeValues(values);
      const encoded = JSON.stringify(next);
      const input = document.querySelector('#tenantProjectForm [data-key="project_type"]');
      if (input) {
        input.type = 'hidden';
        input.style.display = 'none';
        input.value = encoded;
      }
      tenantProjectData.project_type = encoded;
      return next;
    }

    function applyProjectTypeSelect(input, raw) {
      const values = persistProjectTypes(raw || (input && input.value) || tenantProjectData.project_type);
      return values[0] || '';
    }

    function selectedProjectTypeMains() {
      const input = document.querySelector('#tenantProjectForm [data-key="project_type"]');
      const values = normalizeProjectTypeValues((input && input.value) || tenantProjectData.project_type);
      return values.length ? values : selectedMixedComponents();
    }

    function selectedProjectTypeMain() {
      const mains = selectedProjectTypeMains();
      if (mains.length > 1) return 'متعدد الاستخدامات';
      return mains[0] || '';
    }

    function selectedProjectSubtypesByMain() {
      const hidden = document.querySelector('#tenantProjectForm [data-key="project_subtype"]');
      const raw = hidden ? hidden.value : tenantProjectData.project_subtype;
      const parsed = parseStoredLandTable(raw);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const mapped = {};
        Object.entries(parsed).forEach(([typeName, values]) => {
          const list = [...new Set(parseSelectedMarketList(values))];
          if (typeName === 'متعدد الاستخدامات') {
            list.forEach(value => {
              const parent = parentMainForSubtype(value);
              if (!MARKET_MIXED_TYPE_OPTIONS.includes(parent) || parent === 'سكني') return;
              mapped[parent] = [...new Set((mapped[parent] || []).concat(value))];
            });
            return;
          }
          if (list.length) mapped[typeName] = list;
        });
        return mapped;
      }
      const listed = [...new Set(parseSelectedMarketList(raw))];
      const mains = selectedProjectTypeMains();
      return mains.length === 1 && listed.length ? { [mains[0]]: listed } : {};
    }

    function selectedProjectSubtypes() {
      return Object.values(selectedProjectSubtypesByMain()).flat();
    }

    function selectedProjectSubtype() {
      return selectedProjectSubtypes()[0] || '';
    }

    function selectedMixedComponents() {
      const hidden = document.querySelector('#tenantProjectForm [data-key="project_mixed_components"]');
      const listed = parseSelectedMarketList(hidden ? hidden.value : tenantProjectData.project_mixed_components)
        .filter(value => MARKET_MIXED_TYPE_OPTIONS.includes(value));
      if (listed.length) return [...new Set(listed)];
      const subtypeHidden = document.querySelector('#tenantProjectForm [data-key="project_subtype"]');
      const parsed = parseStoredLandTable(subtypeHidden ? subtypeHidden.value : tenantProjectData.project_subtype);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        const fromLegacy = parseSelectedMarketList(parsed['متعدد الاستخدامات']).map(parentMainForSubtype)
          .filter(value => MARKET_MIXED_TYPE_OPTIONS.includes(value));
        const fromKeys = Object.keys(parsed)
          .map(key => key === 'متعدد الاستخدامات' ? '' : key)
          .filter(value => MARKET_MIXED_TYPE_OPTIONS.includes(value));
        return [...new Set([...fromLegacy, ...fromKeys])];
      }
      return [];
    }

    function parentMainForSubtype(subtype) {
      if (MARKET_SUBTYPES['تجاري'].includes(subtype)) return 'تجاري';
      if (MARKET_SUBTYPES['فندقي'].includes(subtype)) return 'فندقي';
      if (MARKET_SUBTYPES['صناعي ولوجستي'].includes(subtype)) return 'صناعي ولوجستي';
      if (subtype === 'سكني') return 'سكني';
      return 'متعدد الاستخدامات';
    }

    function parseSelectedMarketList(value) {
      if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean);
      const text = String(value || '').trim();
      if (!text) return [];
      if (text.startsWith('[')) {
        try {
          const parsed = JSON.parse(text);
          if (Array.isArray(parsed)) return parsed.map(item => String(item || '').trim()).filter(Boolean);
        } catch (e) { /* keep splitting */ }
      }
      return text.split(/[,،\n;|]/).map(item => item.trim()).filter(Boolean);
    }

    function audienceKindForMain(main, subtype) {
      if (main === 'تجاري') return subtype === 'مكاتب' ? 'مكاتب' : 'تجزئة';
      return marketAudienceKind(subtype || main);
    }

    function audienceOptionsForMain(main, subtype) {
      if (main === 'تجاري') {
        const retail = MARKET_AUDIENCE['تجزئة'] || [];
        const offices = MARKET_AUDIENCE['مكاتب'] || [];
        if (subtype === 'مكاتب') return offices.slice();
        if (subtype && subtype !== 'مكاتب') return retail.slice();
        return [...offices, ...retail.filter(option => !offices.includes(option))];
      }
      const kind = audienceKindForMain(main, subtype);
      return (MARKET_AUDIENCE[kind] || MARKET_GENERAL_AUDIENCE).filter(option => option !== 'أخرى');
    }

    function projectAnalysisKinds() {
      const mains = selectedProjectTypeMains();
      const subtypeMap = selectedProjectSubtypesByMain();
      const kinds = [];
      const addKind = (label, parentMain) => {
        const kind = marketAudienceKind(label) || marketAudienceKind(parentMain);
        if (kind && !kinds.includes(kind)) kinds.push(kind);
      };
      mains.forEach(main => {
        const subtypes = subtypeMap[main] || [];
        if (main === 'سكني') {
          addKind(main, main);
        } else if (main === 'متعدد الاستخدامات') {
          subtypes.forEach(subtype => addKind(subtype, parentMainForSubtype(subtype)));
        } else if (['تجاري', 'فندقي', 'صناعي ولوجستي'].includes(main)) {
          subtypes.forEach(subtype => addKind(subtype, main));
        }
      });
      return kinds;
    }

    function emptyMarketStudyState() {
      const summary = {};
      const swot = {};
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => { summary[item.key] = ''; });
      MARKET_STUDY_SWOT_SECTIONS.forEach(item => { swot[item.key] = ''; });
      return {
        competitor_radius: '10',
        competitor_radius_custom_km: '',
        data_period: '12m',
        data_period_from: '',
        data_period_to: '',
        competitors: [],
        summary,
        swot,
        sources: [],
        one_block_summary: '',
        decision: '',
        disclaimer: ''
      };
    }

    function marketSummaryState(value) {
      const result = {};
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
        result[item.key] = '';
      });
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
          result[item.key] = String(value[item.key] || '').trim();
        });
      } else if (typeof value === 'string' && value.trim()) {
        // Keep a paragraph from the previous schema visible until it is regenerated.
        result.market_definition = value.trim();
      }
      return result;
    }

    function marketSummaryHasContent(value) {
      const state = marketSummaryState(value);
      return MARKET_STUDY_SUMMARY_SECTIONS.some(item => {
        const text = String(state[item.key] || '').trim();
        return text && text !== 'غير متوفر من مصدر موثوق';
      });
    }

    function marketSummaryAnalysisText(value) {
      const state = marketSummaryState(value);
      return MARKET_STUDY_SUMMARY_SECTIONS.map((item, index) => {
        const text = String(state[item.key] || '').trim();
        if (!text) return '';
        return (index + 1) + '. ' + item.label + ': ' + text;
      }).filter(Boolean).join('\n\n');
    }

    function marketSummaryIsParagraph(value) {
      const text = String(value || '').replace(/\\r?\\n/g, '\n').trim();
      if (!text || /(^|\n)\s*\d+[.)]\s+/.test(text)) return false;
      const headings = [
        'نطاق دراسة السوق', 'نطاق الدراسة', 'المنافسون', 'تحليل السوق',
        'تحليل SWOT', 'المصادر', 'مصادر دراسة السوق', 'القرار',
        'إخلاء المسؤولية', 'ملخص دراسة سوق العمل', 'الملخص التنفيذي لسوق المشروع'
      ];
      return !text.split('\n').some(line => headings.includes(line.trim().replace(/[：:]$/, '')));
    }

    function buildMarketStudyOneBlockSummary(state = {}) {
      const generated = String(state.one_block_summary || '')
        .replace(/\\r?\\n/g, '\n')
        .trim();
      if (marketSummaryIsParagraph(generated)) return generated;
      const parts = [];
      const text = value => String(value || '').trim();
      const summary = marketSummaryState(state.summary);
      MARKET_STUDY_SUMMARY_SECTIONS.forEach(item => {
        const value = text(summary[item.key]);
        if (value && value !== 'غير متوفر من مصدر موثوق') parts.push(value);
      });
      const competitors = Array.isArray(state.competitors) ? state.competitors : [];
      const names = competitors.map(row => text(row && row.name)).filter(Boolean);
      if (names.length) {
        parts.push('وتوضح المقارنة السوقية مع ' + names.join('، ') + ' طبيعة المنافسة والأسعار المرجعية المتاحة للمشروع.');
      }
      if (text(state.decision)) parts.push('وبناءً على هذه المعطيات، يصنّف القرار السوقي للمشروع باعتباره ' + text(state.decision) + '.');
      return parts.join(' ').replace(/\s+/g, ' ').trim();
    }

    function getMarketStudyState() {
      const parsed = parseStoredLandTable(tenantProjectData.market_study_data);
      const base = emptyMarketStudyState();
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return base;
      const competitors = (Array.isArray(parsed.competitors) ? parsed.competitors : []).map(item => {
        const row = { ...(item || {}) };
        const areaCache = row.area_cache || row.areaCache || {};
        row.area_sqm = cleanMarketNumber(row.area_sqm || '');
        row.area_from = cleanMarketNumber(row.area_from || row.areaFrom || '');
        row.area_to = cleanMarketNumber(row.area_to || row.areaTo || '');
        row.area_mode = row.area_mode === 'range' ? 'range'
          : row.area_mode === 'fixed' ? 'fixed'
            : row.area_from || row.area_to ? 'range' : 'fixed';
        row.area_cache = {
          area_sqm: cleanMarketNumber(areaCache.area_sqm || row.area_sqm),
          area_from: cleanMarketNumber(areaCache.area_from || row.area_from),
          area_to: cleanMarketNumber(areaCache.area_to || row.area_to)
        };
        return row;
      });
      const storedOneBlock = String(parsed.one_block_summary || '').replace(/\\r?\\n/g, '\n').trim();
      const migratedOneBlock = marketSummaryIsParagraph(storedOneBlock)
        ? storedOneBlock
        : (typeof parsed.summary === 'string' ? parsed.summary.trim() : '');
      return {
        ...base,
        ...parsed,
        competitors,
        sources: mergeMarketSourceRows(
          Array.isArray(parsed.sources) ? parsed.sources : [],
          buildMarketCompetitorSourceRows(competitors)
        ),
        summary: marketSummaryState(parsed.summary),
        one_block_summary: migratedOneBlock,
        swot: { ...base.swot, ...(parsed.swot || {}) }
      };
    }

    function setMarketStudyState(state) {
      const next = { ...emptyMarketStudyState(), ...(state || {}) };
      next.one_block_summary = buildMarketStudyOneBlockSummary(next);
      const oneBlock = document.getElementById('marketStudyOneBlockSummary');
      if (oneBlock) oneBlock.value = next.one_block_summary;
      tenantProjectData.market_study_data = next;
      const hidden = document.getElementById('marketStudyData');
      if (hidden) hidden.value = JSON.stringify(next);
      triggerAutoSaveDraft();
    }