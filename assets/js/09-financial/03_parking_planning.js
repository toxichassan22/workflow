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
      const keys = ['id', 'name', 'useType', 'units', 'unitArea', 'builtArea', 'revenueArea', 'investmentModel', 'parkingLocation', 'parkingPlanId', 'floorRange'];
      const normalized = items => items.map(item => Object.fromEntries(keys.map(key => [key, item[key] ?? null])))
        .sort((first, second) => String(first.id).localeCompare(String(second.id)));
      return financialParkingStable(normalized(actual)) === financialParkingStable(normalized(plan.components || []))
        ? '' : 'مكونات المواقف الحالية لا تطابق الاقتراح المعتمد.';
    }

    function financialParkingMarkup() {
      return `<section id="financialParkingPanel" class="financial-parking" aria-labelledby="financialParkingTitle">
        <div class="financial-parking-header"><h4 id="financialParkingTitle">المواقف المقترحة</h4>
          <button type="button" id="financialParkingSuggest" class="btn ghost" onclick="suggestFinancialParking()">اقتراح المواقف بالذكاء الاصطناعي</button></div>
        <div id="financialParkingStatus" class="tenant-hint financial-parking-status" role="status" aria-live="polite"></div>
        <div id="financialParkingDetails" hidden>
          <div class="grid four financial-parking-summary">
            <div><label for="parkingRequiredSpaces">إجمالي المواقف المطلوبة</label><input id="parkingRequiredSpaces" readonly></div>
            <div><label for="parkingExistingSpaces">المواقف المدخلة سابقًا</label><input id="parkingExistingSpaces" readonly></div>
            <div><label for="parkingAdditionalSpaces">المواقف الإضافية المقترحة</label><input id="parkingAdditionalSpaces" readonly></div>
            <div><label for="parkingProposedArea">مساحة المواقف المقترحة م²</label><input id="parkingProposedArea" readonly></div>
            <div><label for="parkingAreaPerSpace">مساحة الموقف شاملة الحركة م²</label><input id="parkingAreaPerSpace" readonly></div>
            <div><label for="parkingAdditionalBasementArea">مساحة البدروم الإضافية المقترحة م²</label><input id="parkingAdditionalBasementArea" readonly></div>
          </div>
          <div class="table-wrap"><table id="parkingRequirementsTable"><thead><tr><th>المكون</th><th>أساس احتساب المواقف</th><th>الكمية المعتمدة</th><th>عدد المواقف المطلوبة</th><th>الاشتراط الموثق</th></tr></thead><tbody></tbody></table></div>
          <div class="financial-parking-notes"><div id="financialParkingNotesWrap"><label for="financialParkingNotes">ملاحظات اقتراح المواقف</label><textarea id="financialParkingNotes" readonly rows="4"></textarea></div></div>
          <div class="financial-parking-actions"><button type="button" id="financialParkingApprove" class="btn primary" data-section-lock-ignore="1" onclick="approveFinancialParking()">اعتماد اقتراح المواقف</button><button type="button" id="financialParkingDiscard" class="btn ghost" data-section-lock-ignore="1" onclick="discardFinancialParking()">حذف اقتراح المواقف</button></div>
        </div>
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
      const details = document.getElementById('financialParkingDetails');
      if (details) details.hidden = !plan.id || plan.approved === true;
      if (status) status.textContent = financialParkingText(financialParkingBusy ? 'جاري إعداد اقتراح المواقف...' : !plan.id ? 'لا يوجد اقتراح مواقف.'
        : stale ? 'تغيّرت بيانات المشروع أو الاشتراطات التي بُني عليها اقتراح المواقف.'
        : plan.approved && !error ? 'اقتراح المواقف معتمد.' : plan.canApply ? 'اقتراح المواقف بانتظار الاعتماد.' : 'اقتراح المواقف غير مكتمل.');
      const setValue = (id, value) => { const input = document.getElementById(id); if (input) input.value = !plan.id ? '' : value == null ? '—' : money(value); };
      setValue('parkingRequiredSpaces', plan.requiredSpaces);
      setValue('parkingExistingSpaces', plan.existingSpaces);
      setValue('parkingAdditionalSpaces', plan.additionalSpaces);
      setValue('parkingProposedArea', plan.parkingArea);
      setValue('parkingAreaPerSpace', plan.areaPerSpace);
      setValue('parkingAdditionalBasementArea', plan.id ? Math.max(0, (plan.basementAreaTarget || 0) - (plan.baseBasementArea || 0)) : null);
      const body = document.querySelector('#parkingRequirementsTable tbody');
      if (body) body.innerHTML = (plan.requirements || []).map(row => {
        const basis = { units: 'عدد الوحدات', builtArea: 'المساحة المبنية م²', revenueArea: 'المساحة البيعية / التأجيرية م²', landArea: 'مساحة الأرض م²' }[row.basis] || 'غير موثق';
        return '<tr><td>' + escapeHtml(row.name || '') + '</td><td>' + escapeHtml(financialParkingText(basis)) + '</td><td>'
          + (row.quantity == null ? '—' : money(row.quantity)) + '</td><td>' + (row.spaces == null ? escapeHtml(financialParkingText('غير موثق')) : money(row.spaces))
          + '</td><td><span class="financial-parking-reference" title="' + escapeHtml(row.sourceQuote || '') + '">' + escapeHtml(financialParkingText(row.summary || row.sourceQuote || '')) + '</span></td></tr>';
      }).join('');
      const noteLines = [plan.areaBasis, ...(plan.missing || []), ...(plan.warnings || [])].filter(Boolean).map(financialParkingText);
      const notes = document.getElementById('financialParkingNotes');
      if (notes) notes.value = noteLines.join('\n');
      const notesWrap = document.getElementById('financialParkingNotesWrap');
      if (notesWrap) notesWrap.hidden = !noteLines.length;
      const approve = document.getElementById('financialParkingApprove');
      if (approve) {
        approve.textContent = financialParkingText(plan.approved ? 'إلغاء اعتماد اقتراح المواقف' : 'اعتماد اقتراح المواقف');
        approve.disabled = financialParkingBusy || presentationMode || (!plan.approved && (!plan.canApply || stale));
      }
      const discard = document.getElementById('financialParkingDiscard');
      if (discard) discard.disabled = financialParkingBusy || presentationMode;
      document.querySelectorAll('#componentsTable tbody tr').forEach(row => {
        const parking = row.querySelector('[data-field="useType"] select')?.value === 'parking';
        const location = row.querySelector('[data-field="parkingLocation"]');
        if (location) location.hidden = !parking;
        if (row.dataset.parkingPlanId) row.querySelectorAll('input,select,button').forEach(control => { control.disabled = true; });
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
