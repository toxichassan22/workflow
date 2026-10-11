    let financialParkingBusy = false;
    let financialParkingRequestTask = null;
    let financialParkingLastInvalidation = '';

    function financialParkingText(text) {
      const prefix = 'اشتراط المواقف أو أساس حسابه غير موثق للمكون: ';
      if (String(text).startsWith(prefix)) return financialParkingText(prefix.trim()) + ' ' + String(text).slice(prefix.length);
      return typeof wfTr === 'function' ? wfTr(text) : text;
    }

    function financialParkingObject(value) {
      if (value && typeof value === 'object' && !Array.isArray(value)) return value;
      try { const parsed = JSON.parse(value || '{}'); return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}; }
      catch (error) { return {}; }
    }

    function financialParkingPlan() {
      return financialParkingObject(financialParkingObject(tenantProjectData.financial_study_model).parkingPlan);
    }

    function financialParkingNumber(value) {
      if (typeof value === 'boolean' || value == null || String(value).trim() === '') return null;
      const cleaned = String(value).replace(/[٠-٩]/g, ch => String('٠١٢٣٤٥٦٧٨٩'.indexOf(ch)))
        .replace(/[۰-۹]/g, ch => ch.charCodeAt(0) - 0x06F0).replace(/[\s,٬،]/g, '').replace(/٫/g, '.');
      const number = Number(cleaned);
      return Number.isFinite(number) && number >= 0 ? number : null;
    }

    function financialComponentAreaPool(component) {
      if (component.useType === 'parking' && ['basement', 'surface', 'aboveGround'].includes(component.parkingLocation)) return component.parkingLocation;
      return component.useType === 'basement' ? 'basement' : component.useType === 'openArea' ? 'surface' : 'aboveGround';
    }

    function financialParkingSnapshot() {
      const model = financialParkingObject(tenantProjectData.financial_study_model);
      const inputs = financialParkingObject(model.inputs);
      const plan = financialParkingPlan();
      const readField = key => {
        const element = document.querySelector('#tenantProjectForm [data-key="' + key + '"]');
        return element ? element.value : tenantProjectData[key];
      };
      const readInput = key => {
        const element = document.getElementById(key);
        return element ? element.value : inputs[key];
      };
      const rows = document.getElementById('componentsTable') && typeof getComponentRowsData === 'function'
        ? getComponentRowsData() : (model.dynamicRows?.components || []);
      let basement = financialParkingNumber(readInput('basementArea')) || 0;
      if (rows.some(row => row.parkingPlanId) && [plan.basementAreaTarget, plan.previousBasementAreaTarget].includes(basement)) {
        basement = financialParkingNumber(plan.baseBasementArea) || 0;
      }
      const components = rows.filter(row => !row.parkingPlanId).map(row => {
        const component = {};
        ['id', 'name', 'useType', 'investmentModel', 'parkingLocation'].forEach(key => { component[key] = String(row[key] || '').trim(); });
        ['units', 'unitArea', 'builtArea', 'revenueArea'].forEach(key => { component[key] = financialParkingNumber(row[key]); });
        return component;
      }).sort((first, second) => first.id < second.id ? -1 : first.id > second.id ? 1 : 0);
      const analysis = financialParkingObject(tenantProjectData.land_documents_analysis);
      const texts = [];
      [analysis, ...(Array.isArray(analysis.parcels) ? analysis.parcels : [])].forEach(holder => {
        if (!holder || typeof holder !== 'object') return;
        ['parking_requirements', 'regulatory_constraints'].forEach(key => {
          const text = String(holder[key] || '').trim();
          if (text && !texts.includes(text)) texts.push(text);
        });
      });
      const land = readField('approved_financial_area');
      const coverage = readField('approved_coverage_ratio');
      const floors = readField('approved_floor_count');
      return {
        landArea: financialParkingNumber(land === undefined ? readInput('landArea') : land),
        croquisArea: financialParkingNumber(readField('croquis_land_area')),
        coverageRate: financialParkingNumber(coverage === undefined ? readInput('coverageRate') : coverage),
        floorCount: financialParkingNumber(floors === undefined ? readInput('floorCount') : floors),
        builtUpAreaAbove: financialParkingNumber(readInput('builtUpAreaAbove')),
        basementArea: basement,
        city: String(readField('city') || '').trim(),
        zoningCode: String(readField('zoning_code') || '').trim(),
        regulatoryConstraints: String(readField('regulatory_constraints') || '').trim(),
        parkingRequirements: String(readField('parking_requirements') || '').trim(),
        analysisParkingRequirements: texts.join('\n'),
        components
      };
    }

    function financialParkingStable(value) {
      if (Array.isArray(value)) return '[' + value.map(financialParkingStable).join(',') + ']';
      if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + financialParkingStable(value[key])).join(',') + '}';
      return JSON.stringify(value ?? null);
    }

    function financialParkingError() {
      const plan = financialParkingPlan();
      const rows = typeof getComponentRowsData === 'function' ? getComponentRowsData() : [];
      const actual = rows.filter(row => row.parkingPlanId);
      if (!plan.id) return actual.length ? 'اعتماد اقتراح المواقف مطلوب قبل اعتماد الدراسة المالية أو تصديرها.' : '';
      if (plan.approved !== true || !plan.canApply) return 'اعتماد اقتراح المواقف مطلوب قبل اعتماد الدراسة المالية أو تصديرها.';
      if (financialParkingStable(financialParkingSnapshot()) !== financialParkingStable(plan.sourceSnapshot)) return 'تغيّرت بيانات المشروع أو الاشتراطات التي بُني عليها اقتراح المواقف.';
      return actual.every(row => String(row.parkingPlanId) === String(plan.id))
        ? '' : 'مكونات المواقف الحالية لا تطابق الاقتراح المعتمد.';
    }

    function financialParkingMarkup() {
      return `<section id="financialParkingPanel" class="financial-parking" aria-labelledby="financialParkingTitle">
        <div class="financial-parking-header"><h4 id="financialParkingTitle">المواقف المقترحة</h4>
          <div class="financial-parking-actions">
            <button type="button" id="financialParkingSuggest" class="btn ghost" onclick="suggestFinancialParking()">اقتراح المواقف بالذكاء الاصطناعي</button>
            <button type="button" id="financialParkingApprove" class="btn primary" data-section-lock-ignore="1" onclick="approveFinancialParking()" hidden>اعتماد اقتراح المواقف</button>
            <button type="button" id="financialParkingDiscard" class="btn ghost" data-section-lock-ignore="1" onclick="discardFinancialParking()" hidden>حذف اقتراح المواقف</button>
          </div></div>
        <div id="financialParkingStatus" class="tenant-hint financial-parking-status" role="status" aria-live="polite"></div>
      </section>`;
    }

    function financialParkingInvalidateVisuals() {
      const concept = typeof tenantVisualConceptState !== 'undefined' && tenantVisualConceptState
        ? tenantVisualConceptState : financialParkingObject(tenantProjectData.visual_concept);
      if (!concept || !Object.keys(concept).length) return;
      const workflow = concept.plansWorkflow || concept.plans_workflow;
      if (workflow) {
        workflow.planContext = null;
        workflow.promptReady = false;
        workflow.prompts = { site: '', uses: '', massing: '' };
        if (workflow.distribution) Object.assign(workflow.distribution, { approved: false, aiReviewed: false });
      }
      Object.values(concept.slots || {}).forEach(slot => {
        Object.assign(slot, { approvedImageUrl: '', approved: false, status: 'pending', prompt: '' });
        if (slot.sketch) Object.assign(slot.sketch, { approvedImageUrl: '', approved: false, status: 'pending' });
      });
      tenantProjectData.visual_concept = concept;
      if (typeof persistVisualConceptDraftState === 'function') persistVisualConceptDraftState();
    }

    function renderFinancialParking() {
      const panel = document.getElementById('financialParkingPanel');
      if (!panel) return;
      const plan = financialParkingPlan();
      const snapshot = financialParkingSnapshot();
      const stale = !!plan.id && financialParkingStable(snapshot) !== financialParkingStable(plan.sourceSnapshot);
      const error = financialParkingError();
      const status = document.getElementById('financialParkingStatus');
      const presentationMode = typeof tenantProjectMode !== 'undefined' && tenantProjectMode === 'presentation';
      const sectionLocked = tenantProjectSectionStatuses['section-financial-calc'] === 'approved';
      const suggest = document.getElementById('financialParkingSuggest');
      if (suggest) suggest.disabled = financialParkingBusy || presentationMode || sectionLocked;
      const generated = (typeof getComponentRowsData === 'function' ? getComponentRowsData() : []).filter(row => row.parkingPlanId);
      const extras = [];
      if (plan.id) {
        if (plan.areaBasis) extras.push(plan.areaBasis);
        (plan.missing || []).forEach(item => extras.push(item));
        (plan.warnings || []).forEach(item => extras.push(item));
        if (plan.approved === true && !error && plan.requiredSpaces != null) {
          const recorded = generated.reduce((sum, row) => sum + (financialParkingNumber(row.units) || 0), 0);
          if (recorded < plan.requiredSpaces) extras.push('المواقف المسجلة في الجدول أقل من المطلوب بالاشتراط.');
        }
      }
      if (status) status.textContent = financialParkingText(financialParkingBusy ? 'جاري إعداد اقتراح المواقف...' : !plan.id ? 'لا يوجد اقتراح مواقف.'
        : stale ? 'تغيّرت بيانات المشروع أو الاشتراطات التي بُني عليها اقتراح المواقف.'
        : plan.approved && !error ? 'اقتراح المواقف معتمد.' : plan.canApply ? 'اقتراح المواقف بانتظار الاعتماد.' : 'اقتراح المواقف غير مكتمل.')
        + (extras.length ? ' ' + extras.map(financialParkingText).join(' ') : '');
      const approve = document.getElementById('financialParkingApprove');
      if (approve) {
        approve.hidden = !plan.id;
        approve.textContent = financialParkingText(plan.approved ? 'إلغاء اعتماد اقتراح المواقف' : 'اعتماد اقتراح المواقف');
        approve.disabled = financialParkingBusy || presentationMode || (!plan.approved && (!plan.canApply || stale));
      }
      const discard = document.getElementById('financialParkingDiscard');
      if (discard) {
        discard.hidden = !plan.id;
        discard.disabled = financialParkingBusy || presentationMode;
      }
      document.querySelectorAll('#componentsTable tbody tr').forEach(row => {
        const parking = row.querySelector('[data-field="useType"] select')?.value === 'parking';
        const location = row.querySelector('[data-field="parkingLocation"]');
        if (location) location.hidden = !parking;
      });
      if (plan.approved && error) {
        const signature = plan.id + financialParkingStable(snapshot);
        if (signature !== financialParkingLastInvalidation) {
          financialParkingLastInvalidation = signature;
          financialParkingInvalidateVisuals();
        }
        const updates = {};
        ['section-financial-calc', 'section-visual-concept'].forEach(key => { if (tenantProjectSectionStatuses[key] === 'approved') updates[key] = 'draft'; });
        if (Object.keys(updates).length && typeof applySectionStatuses === 'function') applySectionStatuses(updates);
      }
      if (typeof refreshDynamicI18n === 'function') refreshDynamicI18n(panel);
    }

    function hydrateFinancialParkingPlan(model) {
      const current = financialParkingObject(tenantProjectData.financial_study_model);
      const next = { ...current };
      if (model.parkingPlan) next.parkingPlan = model.parkingPlan;
      else delete next.parkingPlan;
      tenantProjectData.financial_study_model = next;
    }

    function financialParkingReceive(response, expectedSnapshot, draftId) {
      if (tenantProjectData.draftId !== draftId || response.draftId !== draftId) return false;
      if (response.revision) tenantDraftRevision = Number(response.revision);
      const fresh = financialParkingStable(financialParkingSnapshot()) === expectedSnapshot;
      const model = financialParkingObject(response.financialModel);
      hydrateFinancialParkingPlan(model);
      if (fresh) {
        window.__batchLoading = true;
        try {
          document.querySelectorAll('#componentsTable tbody tr').forEach(row => { if (row.dataset.parkingPlanId) row.remove(); });
          (model.dynamicRows?.components || []).filter(row => row.parkingPlanId).forEach(addComponent);
          const basement = document.getElementById('basementArea');
          if (basement && model.inputs?.basementArea != null) basement.value = String(model.inputs.basementArea);
        } finally { window.__batchLoading = false; }
      }
      if (response.visualConcept && typeof normalizeVisualConceptState === 'function') {
        tenantVisualConceptState = normalizeVisualConceptState(response.visualConcept);
        tenantProjectData.visual_concept = tenantVisualConceptState;
        if (typeof persistVisualConceptDraftState === 'function') persistVisualConceptDraftState();
      }
      if (response.sectionStatuses && typeof applySectionStatuses === 'function') applySectionStatuses(response.sectionStatuses);
      calculateAll();
      if (typeof persistFinancialStudyDraftState === 'function') persistFinancialStudyDraftState();
      triggerAutoSaveDraft();
      if (!fresh) toast(financialParkingText('تغيّرت البيانات الحالية أثناء إعداد اقتراح المواقف؛ لم تُستبدل مدخلاتك.'));
      return fresh;
    }

    function runFinancialParkingAction(action) {
      if (financialParkingRequestTask) return financialParkingRequestTask;
      financialParkingRequestTask = (async () => {
        if (typeof tenantProjectMode !== 'undefined' && tenantProjectMode === 'presentation') return false;
        financialParkingBusy = true;
        renderFinancialParking();
        try {
          const workspace = tenantProjectData;
          const initial = financialParkingStable(financialParkingSnapshot());
          if (!(await saveProjectAsDraft(true, false))) return false;
          if (tenantProjectData !== workspace || initial !== financialParkingStable(financialParkingSnapshot())) {
            toast(financialParkingText('تغيّرت البيانات الحالية أثناء إعداد اقتراح المواقف؛ لم تُستبدل مدخلاتك.'));
            return false;
          }
          const draftId = tenantProjectData.draftId;
          const snapshot = financialParkingStable(financialParkingSnapshot());
          const plan = financialParkingPlan();
          const body = { draftId, expectedRevision: tenantDraftRevision };
          if (action === 'approval') Object.assign(body, { planId: plan.id, approved: !plan.approved });
          if (action === 'discard') body.planId = plan.id;
          const response = await api('POST', '/api/financial-study/parking/' + action, body);
          if (!response?.success) {
            toast(financialParkingText(response?.error || 'تعذر إعداد اقتراح المواقف.'));
            return false;
          }
          return financialParkingReceive(response, snapshot, draftId);
        } catch (error) {
          toast(financialParkingText('تعذر إعداد اقتراح المواقف.'));
          return false;
        } finally {
          financialParkingBusy = false;
          renderFinancialParking();
        }
      })().finally(() => { financialParkingRequestTask = null; });
      return financialParkingRequestTask;
    }

    function suggestFinancialParking() { return runFinancialParkingAction('suggest'); }
    function approveFinancialParking() { return runFinancialParkingAction('approval'); }
    function discardFinancialParking() {
      if (!financialParkingPlan().id || !confirm(financialParkingText('حذف اقتراح المواقف ومكوناته المولدة؟'))) return Promise.resolve(false);
      return runFinancialParkingAction('discard');
    }

    document.addEventListener('wf:lang', () => renderFinancialParking());
    document.addEventListener('input', event => {
      if (event.target?.closest('#tenantProjectForm') && !window.__batchLoading && !financialParkingBusy) renderFinancialParking();
    });
