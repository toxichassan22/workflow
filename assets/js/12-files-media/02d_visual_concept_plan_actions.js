    const visualConceptPlanRequests = new Set();

    function visualConceptPlanActionBusy(action, busy) {
      if (busy) {
        if (visualConceptPlanRequests.has(action)) return false;
        visualConceptPlanRequests.add(action);
      } else visualConceptPlanRequests.delete(action);
      document.querySelectorAll('[data-plans-workflow-action="' + action + '"]').forEach(button => {
        button.disabled = busy;
      });
      return true;
    }

    // The plans endpoints may answer 202 {jobId} and finish inside a worker so
    // the request thread stays short. Poll the persisted job and hand back the
    // same shape a synchronous call would have returned — a failure job yields
    // its stored {success:false,error} result instead of hanging the caller.
    async function visualConceptPlanJobApi(method, path, body) {
      const initial = await api(method, path, body);
      if (!initial || !initial.jobId) return initial;
      const deadline = Date.now() + 240000;
      let job = initial;
      while (job && (job.status === 'queued' || job.status === 'running') && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 1500));
        job = await api('GET', '/api/visual-concept/plans-jobs/' + encodeURIComponent(initial.jobId));
      }
      if (job && job.result && typeof job.result === 'object') return job.result;
      if (job && job.error) return { success: false, error: job.error, error_code: job.error_code };
      return { success: false, error: WFT('plans.job_failed', 'تعذرت معالجة المخطط الهندسي.') };
    }

    async function collectVisualConceptPlansWorkflowPayload() {
      const payload = await collectVisualConceptPayload('plan_site');
      payload.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      // The plans endpoints read plansWorkflow and the project facts only, so the
      // visual_concept state mirror is dead weight here — and oversized bodies are
      // what the hosting edge corrupts, so the request drops it (clone: projectData
      // is tenantProjectData, which must keep its own copy).
      payload.projectData = { ...payload.projectData };
      delete payload.projectData.visual_concept;
      return payload;
    }

    async function verifyVisualConceptPlans() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      if (!visualConceptPlanActionBusy('verify', true)) return;
      showLoader(WFT('plans.verify_loading', 'جاري التحقق من التضارب'), WFT('plans.verify_loading_detail', 'يتم فحص بيانات المشروع والبيانات التنظيمية الموثقة...'), 18);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const stamp = visualConceptPlanInputStamp();
        const response = await api('POST', '/api/visual-concept/plans-verify', payload);
        hideLoader();
        if (stamp !== visualConceptPlanInputStamp()) { toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.')); return; }
        if (!response?.success) { toast(response?.error || WFT('plans.verify_failed', 'تعذر التحقق من التضارب')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.verification = normalizeVisualConceptPlansWorkflow({ verification: response.verification }).verification;
        // Fresh findings replace the set every earlier chat turn discussed —
        // keeping them would let the assistant answer about a stale conflict.
        workflow.conflictChats = { verify: [], distribution: [] };
        workflow.planContext = response.planContext || workflow.planContext || null;
        workflow.status = 'verified';
        workflow.viewStage = 'verify';
        workflow.boundary.approved = false;
        workflow.distribution.approved = false;
        workflow.distribution.aiReviewed = false;
        workflow.distribution.checks = [];
        workflow.distribution.issues = [];
        invalidateVisualConceptPlanGeneration(workflow);
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.verify_failed', 'تعذر التحقق من التضارب'));
      } finally {
        visualConceptPlanActionBusy('verify', false);
      }
    }

    function approveVisualConceptPlansVerification() {
      const workflow = visualConceptPlansWorkflowState();
      const checks = Array.isArray(workflow.verification.checks) ? workflow.verification.checks : [];
      const conflicts = checks.filter(item => item.result === 'متعارض');
      if (conflicts.length || workflow.verification.canProceed === false || (!checks.length && !workflow.verification.canProceed)) return;
      workflow.verification.approved = true;
      workflow.status = 'verified';
      workflow.viewStage = 'boundary';
      if (!workflow.boundary.points.length) {
        const seeded = visualConceptBoundaryPoints(tenantProjectData.survey_coordinates);
        workflow.boundary.points = seeded.length ? seeded : surveyBoundaryPointsFromDimensions(tenantProjectData);
      }
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    async function refreshVisualConceptPlansBoundary() {
      if (!visualConceptPlanActionBusy('refresh-boundary', true)) return;
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const seedWorkflow = visualConceptPlansWorkflowState();
        let sourcePoints = visualConceptBoundaryPoints(payload.projectData?.survey_coordinates);
        if (sourcePoints.length < 3) sourcePoints = surveyBoundaryPointsFromDimensions(payload.projectData || {});
        if (sourcePoints.length >= 3) seedWorkflow.boundary.points = sourcePoints;
        payload.points = seedWorkflow.boundary.points;
        payload.mode = 'manual';
        const stamp = visualConceptPlanInputStamp();
        showLoader(WFT('plans.boundary_loading', 'جاري تجهيز رسم حدود الأرض'), WFT('plans.boundary_loading_detail', 'يتم بناء الرسم من الإحداثيات المحفوظة...'), 35);
        const response = await api('POST', '/api/visual-concept/plans-boundary', payload);
        hideLoader();
        if (stamp !== visualConceptPlanInputStamp()) { toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.')); return; }
        if (!response?.success) { toast(response?.error || WFT('plans.boundary_failed', 'تعذر تجهيز رسم الحدود')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.boundary.points = visualConceptBoundaryPoints(response.points);
        workflow.boundary.referenceUrl = response.referenceUrl || '';
        workflow.boundary.approved = false;
        workflow.distribution.approved = false;
        invalidateVisualConceptPlanGeneration(workflow);
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.boundary_failed', 'تعذر تجهيز رسم الحدود'));
      } finally {
        visualConceptPlanActionBusy('refresh-boundary', false);
      }
    }

    function approveVisualConceptPlansBoundary() {
      const workflow = visualConceptPlansWorkflowState();
      if (workflow.boundary.points.length < 3 || !workflow.boundary.referenceUrl) return;
      workflow.boundary.approved = true;
      workflow.status = 'boundary';
      workflow.viewStage = workflow.distribution.approved ? 'generate' : 'boundary';
      invalidateVisualConceptPlanGeneration(workflow);
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    let visualConceptDistCheckTimer = null;

    function scheduleVisualConceptDistributionCheck() {
      if (visualConceptDistCheckTimer) clearTimeout(visualConceptDistCheckTimer);
      visualConceptDistCheckTimer = setTimeout(() => {
        visualConceptDistCheckTimer = null;
        checkVisualConceptPlansDistribution('local', { silent: true });
      }, 700);
    }

    function addVisualConceptDistributionRow() {
      const workflow = visualConceptPlansWorkflowState();
      workflow.distribution.rows.push({
        id: 'row_' + Date.now().toString(36),
        building: '', floor_range: '', component: '',
        units_per_floor: '', floor_area_sqm: '', circulation: ''
      });
      workflow.distribution.approved = false;
      workflow.distribution.aiReviewed = false;
      workflow.distribution.checks = [];
      workflow.distribution.issues = [];
      invalidateVisualConceptPlanGeneration(workflow);
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    async function proposeVisualConceptPlansDistribution() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      if (!visualConceptPlanActionBusy('propose-distribution', true)) return;
      showLoader(WFT('plans.distribution_loading', 'جاري اقتراح التوزيع'),
        WFT('plans.distribution_loading_detail', 'يتم توزيع المكونات على المباني والأدوار...'), 30);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const stamp = visualConceptPlanInputStamp();
        const response = await api('POST', '/api/visual-concept/plans-distribution', payload);
        hideLoader();
        if (stamp !== visualConceptPlanInputStamp()) { toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.')); return; }
        if (!response?.success) { toast(response?.error || WFT('plans.distribution_failed', 'تعذر اقتراح التوزيع')); return; }
        const workflow = visualConceptPlansWorkflowState();
        // Verdicts belong to sol's review only — the proposed table lands with
        // totals but no pre-baked deterministic conflict list.
        workflow.distribution = normalizeVisualConceptPlansWorkflow({
          distribution: { ...response.distribution, checks: [], issues: [] }
        }).distribution;
        workflow.planContext = response.planContext || workflow.planContext || null;
        invalidateVisualConceptPlanGeneration(workflow);
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.distribution_failed', 'تعذر اقتراح التوزيع'));
      } finally {
        visualConceptPlanActionBusy('propose-distribution', false);
      }
    }

    async function checkVisualConceptPlansDistribution(mode, options) {
      const silent = Boolean(options && options.silent);
      const seedWorkflow = visualConceptPlansWorkflowState();
      if (!seedWorkflow.verification.approved || !(seedWorkflow.distribution.rows || []).length) return;
      if (!silent) showLoader(WFT('plans.distribution_check_loading', 'جاري فحص التوزيع'),
        WFT('plans.distribution_check_loading_detail', 'يتم مراجعة المساحات والقيود...'), 35);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const stamp = visualConceptPlanInputStamp();
        payload.mode = mode || 'local';
        payload.distribution = { rows: seedWorkflow.distribution.rows };
        const response = await api('POST', '/api/visual-concept/plans-distribution-check', payload);
        if (!silent) hideLoader();
        if (stamp !== visualConceptPlanInputStamp()) return;
        if (!response?.success) {
          if (!silent) toast(response?.error || WFT('plans.distribution_check_failed', 'تعذر فحص التوزيع'));
          return;
        }
        const workflow = visualConceptPlansWorkflowState();
        workflow.distribution.totals = Array.isArray(response.totals) ? response.totals : [];
        if (!silent) {
          // Verdicts display only after sol adjudicates — the silent local pass
          // refreshes totals but never writes a conflict list on its own.
          workflow.distribution.checks = Array.isArray(response.checks) ? response.checks : [];
          if (Array.isArray(response.issues)) workflow.distribution.issues = response.issues;
          workflow.distribution.aiReviewed = mode === 'ai';
          workflow.distribution.canProceed = response.canProceed !== false;
          workflow.conflictChats.distribution = [];
        }
        markVisualConceptDirty();
        const totalsHost = document.querySelector('[data-plans-distribution-totals]');
        if (totalsHost) totalsHost.innerHTML = visualConceptDistributionTotalsRowsHtml(workflow.distribution);
        const host = document.querySelector('[data-plans-distribution-results]');
        if (host) host.innerHTML = visualConceptDistributionResultsHtml(workflow.distribution);
        else if (!silent) renderVisualConceptPage();
        return true;
      } catch (error) {
        if (silent) return;
        hideLoader();
        toast(error.message || WFT('plans.distribution_check_failed', 'تعذر فحص التوزيع'));
      }
    }

    // Approving a table that still carries confirmed conflicts is allowed, but
    // only through the risk dialog — its continue button lands on
    // applyVisualConceptPlansDistributionApproval directly.
    function approveVisualConceptPlansDistribution() {
      const workflow = visualConceptPlansWorkflowState();
      const rows = workflow.distribution.rows || [];
      if (!rows.length || !workflow.distribution.aiReviewed || !visualConceptPlanNotesValid(workflow)) return;
      const hasConflicts = Boolean(visualConceptDistributionBlocking(workflow.distribution).length)
        || workflow.distribution.canProceed === false;
      if (hasConflicts) { showVisualConceptDistributionRisk(); return; }
      applyVisualConceptPlansDistributionApproval(workflow);
    }

    function applyVisualConceptPlansDistributionApproval(workflow) {
      workflow.distribution.approved = true;
      invalidateVisualConceptPlanGeneration(workflow, false);
      workflow.viewStage = workflow.boundary.approved ? 'generate' : 'boundary';
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    function showVisualConceptDistributionRisk() {
      let modal = document.getElementById('plansDistributionRisk');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'plansDistributionRisk';
        modal.className = 'll-modal-overlay';
        modal.setAttribute('data-a11y-modal', '');
        modal.style.display = 'none';
        modal.innerHTML =
          '<div class="ll-modal-card" role="dialog" aria-modal="true" aria-labelledby="plansDistributionRiskTitle">' +
          '<div class="sag-modal-head"><h2 id="plansDistributionRiskTitle"></h2></div>' +
          '<p id="plansDistributionRiskBody" class="visual-concept-lock-hint"></p>' +
          '<p id="plansDistributionRiskOwn" class="plans-distribution-risk"></p>' +
          '<div class="sag-modal-actions" style="gap:8px;margin-top:16px">' +
          '<button type="button" class="btn danger" data-plans-risk-continue></button>' +
          '<button type="button" class="btn ghost" data-plans-risk-cancel></button>' +
          '</div></div>';
        document.body.appendChild(modal);
        modal.addEventListener('click', event => {
          if (event.target === modal || event.target.closest('[data-plans-risk-cancel]')) {
            closeVisualConceptDistributionRisk();
            return;
          }
          if (event.target.closest('[data-plans-risk-continue]')) {
            closeVisualConceptDistributionRisk();
            applyVisualConceptPlansDistributionApproval(visualConceptPlansWorkflowState());
          }
        });
      }
      modal.querySelector('#plansDistributionRiskTitle').textContent =
        WFT('plans.dist_risk_title', 'تعارضات في التوزيع');
      modal.querySelector('#plansDistributionRiskBody').textContent =
        WFT('plans.dist_risk_body', 'فحص التعارضات سجّل بنودًا لم تُحل — نتيجة المخططات بهذه الحالة لن تكون دقيقة.');
      modal.querySelector('#plansDistributionRiskOwn').textContent =
        WFT('plans.dist_risk_own', 'إذا أردت الاستمرار فهذا على مسؤوليتك الشخصية.');
      modal.querySelector('[data-plans-risk-continue]').textContent =
        WFT('plans.dist_risk_continue', 'استمرار');
      modal.querySelector('[data-plans-risk-cancel]').textContent =
        WFT('plans.dist_risk_cancel', 'إلغاء');
      modal.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(modal);
    }

    function closeVisualConceptDistributionRisk() {
      const modal = document.getElementById('plansDistributionRisk');
      if (!modal) return;
      modal.style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    async function checkVisualConceptPlanNotes() {
      if (!hasPermission('generate_images') || !visualConceptPlanActionBusy('check-notes', true)) return false;
      showLoader(WFT('plans.notes_loading', 'جاري فحص الملاحظات'), WFT('plans.notes_loading_detail', 'يتم فحص الملاحظات مقابل الكروكي والتوزيع والقيود...'), 35);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const stamp = visualConceptPlanInputStamp();
        const response = await visualConceptPlanJobApi('POST', '/api/visual-concept/plans-notes-check', payload);
        hideLoader();
        if (stamp !== visualConceptPlanInputStamp()) { toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.')); return false; }
        if (!response?.success || !response.notesReview) {
          toast(response?.error || WFT('plans.notes_failed', 'تعذر فحص الملاحظات'));
          return false;
        }
        const workflow = visualConceptPlansWorkflowState();
        workflow.notesReview = normalizeVisualConceptPlansWorkflow({ notesReview: response.notesReview }).notesReview;
        if (response.primaryFrontage && typeof response.primaryFrontage === 'object') {
          workflow.planContext = { ...(workflow.planContext || {}), primary_frontage: response.primaryFrontage };
        }
        workflow.sourceStamp = stamp;
        markVisualConceptDirty();
        renderVisualConceptPage();
        return visualConceptPlanNotesValid(workflow);
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.notes_failed', 'تعذر فحص الملاحظات'));
        return false;
      } finally {
        visualConceptPlanActionBusy('check-notes', false);
      }
    }

    let visualConceptPlansPromptsPending = false;

    async function prepareVisualConceptPlansPrompts() {
      const initialWorkflow = visualConceptPlansWorkflowState();
      if (!initialWorkflow.verification.approved || !initialWorkflow.boundary.approved || !initialWorkflow.distribution.approved || !visualConceptPlanNotesValid(initialWorkflow)) return;
      if (visualConceptPlansPromptsPending) return;
      visualConceptPlansPromptsPending = true;
      visualConceptPlanScenePending = true;
      visualConceptPlanActionBusy('prepare-prompts', true);
      initialWorkflow.promptsError = '';
      showLoader(WFT('plans.prompts_loading', 'جاري تجهيز توليد المخططات'), WFT('plans.prompts_loading_detail', 'يتم تجهيز المخططات من البيانات المعتمدة وحدود الأرض...'), 50);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const stamp = visualConceptPlanInputStamp();
        const response = await visualConceptPlanJobApi('POST', '/api/visual-concept/plans-prompts', payload);
        hideLoader();
        if (stamp !== visualConceptPlanInputStamp()) { toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.')); return; }
        const workflow = visualConceptPlansWorkflowState();
        if (!response?.success || !response.prompts || !response.scene) {
          workflow.promptsError = String(response?.error || WFT('plans.prompts_failed', 'تعذر تجهيز توليد المخططات'));
          markVisualConceptDirty();
          renderVisualConceptPage();
          toast(workflow.promptsError);
          return;
        }
        workflow.prompts = { ...workflow.prompts, ...response.prompts };
        workflow.scene = response.scene;
        workflow.sourceStamp = stamp;
        workflow.promptReady = VISUAL_CONCEPT_PLAN_KINDS.every(item => Boolean(workflow.prompts[item.kind])) && Boolean(response.scene.token);
        workflow.promptsError = workflow.promptReady ? '' : WFT('plans.prompts_incomplete', 'تجهيز المخططات الثلاثة غير مكتمل');
        workflow.status = workflow.promptReady ? 'ready' : 'boundary';
        VISUAL_CONCEPT_PLAN_KINDS.forEach(definition => {
          const slot = tenantVisualConceptState.slots[definition.id] || (tenantVisualConceptState.slots[definition.id] = emptyVisualConceptSlot(definition.id));
          slot.label = definition.label;
          slot.prompt = workflow.prompts[definition.kind] || slot.prompt;
          slot.caption = definition.label;
          slot.approvedImageUrl = '';
          slot.status = slot.imageUrl ? 'review' : 'pending';
        });
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        const workflow = visualConceptPlansWorkflowState();
        workflow.promptsError = String(error.message || WFT('plans.prompts_failed', 'تعذر تجهيز توليد المخططات'));
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast(workflow.promptsError);
      } finally {
        visualConceptPlansPromptsPending = false;
        visualConceptPlanScenePending = false;
        visualConceptPlanActionBusy('prepare-prompts', false);
      }
    }

    function addVisualConceptPlan() {
      if (visualConceptPlans().length >= VISUAL_CONCEPT_MAX_PLANS) {
        toast('تم الوصول إلى الحد الأقصى للمخططات');
        return;
      }
      tenantVisualConceptState = normalizeVisualConceptState(tenantVisualConceptState);
      const id = 'plan_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
      visualConceptPlans().push({ id, mode: 'ai', title: '', description: '', fileId: '', fileName: '', imageUrl: '' });
      tenantVisualConceptState.slots[id] = emptyVisualConceptSlot(id);
      markVisualConceptDirty();
      setVisualConceptPlansTab('generate');
      renderVisualConceptPage();
    }

    async function uploadVisualConceptPlanImages(input) {
      const files = Array.from(input?.files || []);
      if (!files.length) return;
      const plans = visualConceptPlans();
      const uploadedPlans = plans.filter(plan => !isVisualConceptWorkflowPlan(plan.id));
      const remaining = Math.max(0, VISUAL_CONCEPT_MAX_PLANS - uploadedPlans.length);
      if (!remaining) {
        toast('تم الوصول إلى الحد الأقصى للمخططات');
        input.value = '';
        return;
      }
      showLoader('جاري رفع المخططات', WFT('vc.plans_saving', 'يتم حفظ {n} مخطط...', { n: Math.min(files.length, remaining) }));
      input.disabled = true;
      try {
        input.dataset.projectFileType = 'visual_reference';
        const uploaded = await uploadTenantProjectFileInput(input, 'visual_plan_2d');
        const incoming = (Array.isArray(uploaded) ? uploaded : [uploaded]).map((file, index) => ({
          id: file?.id || file,
          name: file?.originalName || files[index]?.name || ''
        })).filter(file => file.id).slice(0, remaining);
        if (!incoming.length) throw new Error('تعذر رفع المخططات');
        for (const file of incoming) {
          if (plans.some(plan => plan.fileId === String(file.id))) continue;
          plans.push({
            id: 'plan_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
            mode: 'upload', title: '', description: '', fileId: String(file.id), fileName: file.name,
            imageUrl: await publishProjectFileImageUrl(file.id)
          });
        }
        markVisualConceptDirty();
        renderVisualConceptPage();
        toast(WFT('vc.plans_uploaded', 'تم رفع {n} مخطط.', { n: incoming.length }));
      } catch (error) {
        toast(error.message || 'تعذر رفع المخططات');
      } finally {
        hideLoader();
        if (input) {
          input.disabled = false;
          input.value = '';
          delete input.dataset.uploadSignatures;
        }
      }
    }

    function deleteVisualConceptPlan(planId) {
      if (isVisualConceptWorkflowPlan(planId)) return;
      const plans = visualConceptPlans();
      const index = plans.findIndex(item => item.id === planId);
      if (index < 0) return;
      plans.splice(index, 1);
      if (tenantVisualConceptState.slots) delete tenantVisualConceptState.slots[planId];
      markVisualConceptDirty();
      renderVisualConceptPage();
      toast('تم حذف المخطط');
    }
