    const visualConceptPlanRequests = new Set();

    function visualConceptPlanTodoMarkup(todos, jobError = '') {
      const statusText = { pending: 'بانتظار', active: 'قيد التنفيذ', done: 'مكتمل', failed: 'تعذر' };
      const rows = Array.isArray(todos) ? todos : [];
      if (!rows.length) return '';
      return '<ol class="visual-plan-job-todos">' + rows.map(item => {
        const detail = String(item.error || (item.status === 'failed' ? jobError : '') || '').trim();
        return '<li class="is-' + escapeHtml(item.status) + '"><span>' + escapeHtml(item.label) +
          (detail ? '<small class="visual-plan-job-error">' + escapeHtml(detail) + '</small>' : '') + '</span>' +
          '<strong>' + escapeHtml(statusText[item.status] || statusText.pending) + '</strong></li>';
      }).join('') + '</ol>';
    }

    function updateVisualConceptPlanJobUi(job) {
      if (!job) return;
      const workflow = visualConceptPlansWorkflowState();
      let changed = false;
      const jobSucceeded = job.status === 'completed' &&
        (job.success === true || job.result?.success === true ||
        (Array.isArray(job.todos) && job.todos.length > 0 &&
        job.todos.every(item => item.status === 'done')));
      const jobError = !jobSucceeded && job.status === 'failed'
        ? String(job.result?.error || job.error || '').trim().slice(0, 1200) : '';
      if (workflow.jobError !== jobError) {
        workflow.jobError = jobError;
        changed = true;
      }
      if (jobSucceeded) {
        if (workflow.jobTodos.length) {
          workflow.jobTodos = [];
          changed = true;
        }
      } else if (Array.isArray(job.todos)) {
        const todos = jobError
          ? job.todos.map((item, index) => item.status === 'failed' &&
            !job.todos.slice(0, index).some(previous => previous.status === 'failed')
            ? { ...item, error: jobError } : item)
          : job.todos;
        if (JSON.stringify(workflow.jobTodos) !== JSON.stringify(todos)) {
          workflow.jobTodos = todos;
          changed = true;
        }
      }
      const checkpoint = job.checkpoint && typeof job.checkpoint === 'object' ? job.checkpoint : {};
      const revision = Number(checkpoint.svgRenderRevision) || 0;
      const signature = String(checkpoint.svgInputSignature || '');
      if (revision && signature &&
          (workflow.siteAssistant.renderRevision !== revision || workflow.siteAssistant.inputSignature !== signature)) {
        workflow.siteAssistant.checkpoints = {};
        workflow.siteAssistant.renderRevision = revision;
        workflow.siteAssistant.inputSignature = signature;
        changed = true;
      }
      const sections = job.checkpoint?.svgSections;
      if (sections && typeof sections === 'object') {
        workflow.siteAssistant.checkpoints = workflow.siteAssistant.checkpoints || {};
        Object.entries(sections).forEach(([name, code]) => {
          if (typeof code === 'string' && workflow.siteAssistant.checkpoints[name] !== code) {
            workflow.siteAssistant.checkpoints[name] = code;
            changed = true;
          }
        });
      }
      if (changed && typeof markVisualConceptDirty === 'function') markVisualConceptDirty();
      const markup = visualConceptPlanTodoMarkup(workflow.jobTodos, workflow.jobError);
      const panel = document.querySelector('[data-plans-workflow-todos]');
      if (panel) panel.innerHTML = markup;
      const siteStatus = document.querySelector('[data-site-chat-status]');
      if (siteStatus) {
        const active = workflow.jobTodos.find(item => item.status === 'active');
        siteStatus.textContent = jobSucceeded ? '' : 'المرحلة الحالية: ' +
          (active?.label || 'تجهيز المخطط وتحليل متطلباته');
      }
      const loader = document.getElementById('globalLoader');
      const card = loader?.querySelector('.global-loader-card');
      if (card) {
        let list = card.querySelector('.visual-plan-job-todos');
        if (!list && markup && document.createElement) {
          const host = document.createElement('div');
          host.innerHTML = markup;
          list = host.firstElementChild;
          if (list) card.appendChild(list);
        } else if (list) {
          list.outerHTML = markup || '';
        }
      }
      const active = workflow.jobTodos.find(item => item.status === 'active');
      if (active && job.status === 'running' && typeof updateLoaderProgress === 'function') {
        updateLoaderProgress(Number(job.progress || 20), active.label);
      }
    }

    function failVisualConceptPlanJobUi(error = '') {
      const workflow = visualConceptPlansWorkflowState();
      workflow.jobError = String(error || '').trim().slice(0, 1200);
      const todos = Array.isArray(workflow.jobTodos) ? workflow.jobTodos : [];
      let failedActive = false;
      const failedTodos = todos.map(item => {
        if (!failedActive && (item.status === 'active' || item.status === 'pending')) {
          failedActive = true;
          return { ...item, status: 'failed', error: workflow.jobError };
        }
        return item;
      });
      if (failedTodos.length) updateVisualConceptPlanJobUi({
        status: 'failed', error: workflow.jobError, todos: failedTodos
      });
    }

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
      if (!initial || !initial.jobId) {
        if (initial?.success === false) failVisualConceptPlanJobUi(initial.error || '');
        return initial;
      }
      const timeoutSeconds = Number(initial.timeoutSeconds);
      const jobWindowMs = Number.isFinite(timeoutSeconds) && timeoutSeconds > 0
        ? timeoutSeconds * 1000 : 600000;
      const deadline = Date.now() + jobWindowMs + 10000;
      const timeoutMessage = WFT('plans.job_timeout', 'انتهت مهلة معالجة المخطط الهندسي.');
      let job = initial;
      updateVisualConceptPlanJobUi(job);
      while (job && (job.status === 'queued' || job.status === 'running')) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) break;
        await new Promise(resolve => setTimeout(resolve, Math.min(1500, remaining)));
        const requestTimeout = Math.min(15000, deadline - Date.now());
        if (requestTimeout <= 0) break;
        job = await apiWithTimeout(
          'GET', '/api/visual-concept/plans-jobs/' + encodeURIComponent(initial.jobId),
          null, requestTimeout, WFT('plans.job_status_timeout', 'تعذر الاتصال بحالة معالجة المخطط.'));
        updateVisualConceptPlanJobUi(job);
        if (job?.error && !job?.result) {
          failVisualConceptPlanJobUi(job.error);
          return { success: false, error: job.error, error_code: job.error_code };
        }
      }
      if (job && job.result && typeof job.result === 'object') return job.result;
      if (job && job.error) return { success: false, error: job.error, error_code: job.error_code };
      failVisualConceptPlanJobUi(timeoutMessage);
      return { success: false, error: timeoutMessage, error_code: 'PLANS_JOB_EXPIRED' };
    }

    function visualConceptSiteAssistantProjectData(value) {
      const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
      const fields = [
        'project_name', 'project_idea', 'city', 'district', 'location_address',
        'approved_financial_area', 'croquis_land_area', 'land_area', 'total_area_sqm',
        'approved_coverage_ratio', 'coverage_ratio', 'approved_floor_area_ratio',
        'floor_area_ratio', 'approved_floor_count', 'table_floors',
        'approved_typical_floor_coverage', 'open_area', 'boundary_lengths',
        'survey_coordinates', 'regulation_coordinates', 'directions_table', 'directions',
        'setbacks', 'surrounding_streets', 'facades_count', 'facades_directions',
        'main_facade_direction', 'primary_facade_direction', 'main_frontage_direction',
        'north_direction', 'allowed_uses', 'regulatory_constraints',
        'land_and_building_summary', 'land_documents_analysis'
      ];
      const compactKeys = new Set([
        'rawtext', 'rawresponse', 'rawocrtext', 'ocrtext', 'pagetext',
        'extractiondiagnostics', 'documentprocessing', 'pageimages',
        'originalimage', 'imagedata', 'filedata', 'base64'
      ]);
      function compact(item, key = '', depth = 0) {
        const normalized = String(key).toLowerCase().replace(/[^a-z0-9]/g, '');
        if (compactKeys.has(normalized) || normalized.includes('base64') ||
            /(?:imagedata|filecontent|rawbytes)$/.test(normalized)) return undefined;
        if (Array.isArray(item)) {
          if (depth >= 8) return [];
          return item.slice(0, 80).map(child => compact(child, key, depth + 1))
            .filter(child => child !== undefined);
        }
        if (item && typeof item === 'object') {
          if (depth >= 8) return undefined;
          const clean = {};
          Object.entries(item).forEach(([childKey, child]) => {
            const result = compact(child, childKey, depth + 1);
            if (result !== undefined) clean[childKey] = result;
          });
          return clean;
        }
        return typeof item === 'string' && item.length > 12000 ? item.slice(0, 12000) : item;
      }
      const project = {};
      fields.forEach(key => {
        if (Object.prototype.hasOwnProperty.call(source, key)) {
          let value = source[key];
          if (key === 'land_documents_analysis' && typeof value === 'string') {
            try { value = JSON.parse(value); } catch (error) { /* Keep the recorded text. */ }
          }
          const clean = compact(value, key);
          if (clean !== undefined) project[key] = clean;
        }
      });
      let components = source.project_components_data;
      if (typeof components === 'string') {
        try { components = JSON.parse(components); } catch (error) { components = null; }
      }
      if (!Array.isArray(components)) {
        let financial = source.financial_study_model;
        if (typeof financial === 'string') {
          try { financial = JSON.parse(financial); } catch (error) { financial = null; }
        }
        financial = financial && typeof financial === 'object' ? financial : {};
        components = Array.isArray(financial.dynamicRows?.components) ? financial.dynamicRows.components
          : Array.isArray(financial.components) ? financial.components : [];
      }
      project.project_components_data = compact(components, 'project_components_data') || [];
      return project;
    }

    async function collectVisualConceptPlansWorkflowPayload(options = {}) {
      const payload = await collectVisualConceptPayload('plan_site');
      payload.plansWorkflow = normalizeVisualConceptPlansWorkflow(tenantVisualConceptState.plansWorkflow);
      // The plans endpoints read plansWorkflow and the project facts only, so the
      // visual_concept state mirror is dead weight here — and oversized bodies are
      // what the hosting edge corrupts, so the request drops it (clone: projectData
      // is tenantProjectData, which must keep its own copy).
      payload.projectData = { ...payload.projectData };
      delete payload.projectData.visual_concept;
      if (options.siteAssistantContext) {
        const workflow = payload.plansWorkflow;
        const assistant = { ...workflow.siteAssistant };
        if (options.assistantAction !== 'generate') assistant.checkpoints = {};
        payload.plansWorkflow = {
          verification: { approved: workflow.verification.approved },
          boundary: { points: workflow.boundary.points, approved: workflow.boundary.approved },
          distribution: { rows: workflow.distribution.rows, approved: workflow.distribution.approved },
          distributionNotes: workflow.distributionNotes,
          clientNotes: workflow.clientNotes,
          notesReview: workflow.notesReview,
          scene: workflow.scene,
          siteAssistant: assistant
        };
        return {
          slotId: payload.slotId,
          projectData: visualConceptSiteAssistantProjectData(payload.projectData),
          plansWorkflow: payload.plansWorkflow
        };
      }
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
        invalidateVisualConceptDistributionReview(workflow);
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

    // Approving a verification that still carries conflicts is allowed, but
    // only through the risk dialog — the same responsibility warning the
    // distribution stage shows. Its continue button lands on
    // applyVisualConceptPlansVerificationApproval directly.
    function approveVisualConceptPlansVerification() {
      const workflow = visualConceptPlansWorkflowState();
      const checks = Array.isArray(workflow.verification.checks) ? workflow.verification.checks : [];
      const issues = Array.isArray(workflow.verification.issues) ? workflow.verification.issues : [];
      if (!checks.length && !issues.length && !workflow.verification.canProceed) return;
      const realConflicts = checks.filter(item => {
        if (item.result !== 'متعارض') return false;
        const text = (item.detail || '') + ' ' + (item.item || '') + ' ' + (item.suggestion || '') + ' ' + (item.action || '');
        return typeof isAdvisoryOrCompliantNotice === 'function' ? !isAdvisoryOrCompliantNotice(text) : true;
      });
      const hasConflicts = realConflicts.length > 0 || (workflow.verification.canProceed === false && realConflicts.length > 0);
      if (hasConflicts) { showVisualConceptVerificationRisk(); return; }
      applyVisualConceptPlansVerificationApproval(workflow);
    }

    function applyVisualConceptPlansVerificationApproval(workflow) {
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

    let visualConceptDistCheckTimer = null;

    function scheduleVisualConceptDistributionCheck() {
      if (visualConceptDistCheckTimer) clearTimeout(visualConceptDistCheckTimer);
      visualConceptDistCheckTimer = setTimeout(() => {
        visualConceptDistCheckTimer = null;
        checkVisualConceptPlansDistribution('local', { silent: true });
      }, 700);
    }

    function addVisualConceptDistributionRow(building = '') {
      const workflow = visualConceptPlansWorkflowState();
      const targetBuilding = typeof building === 'string' ? building.trim() : '';
      const newRow = {
        id: 'row_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6),
        building: targetBuilding,
        floor_range: '', component: '',
        units_per_floor: '', floor_area_sqm: '', circulation: ''
      };
      const rows = workflow.distribution.rows || [];
      if (targetBuilding) {
        let lastIdx = -1;
        for (let i = rows.length - 1; i >= 0; i--) {
          if (String(rows[i].building || '').trim() === targetBuilding) {
            lastIdx = i;
            break;
          }
        }
        if (lastIdx >= 0) {
          rows.splice(lastIdx + 1, 0, newRow);
        } else {
          rows.push(newRow);
        }
      } else {
        rows.push(newRow);
      }
      workflow.distribution.rows = rows;
      invalidateVisualConceptDistributionReview(workflow);
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

    // A revision sends the current table plus the client's one-shot instruction;
    // the model edits those rows instead of redistributing from scratch. The
    // response lands in the same editable table and still needs a fresh check.
    async function reviseVisualConceptPlansDistribution() {
      if (!hasPermission('generate_images')) { toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات')); return; }
      const seedWorkflow = visualConceptPlansWorkflowState();
      const revision = String(seedWorkflow.distributionRevision || '').trim();
      if (!revision) { toast(WFT('plans.dist_revise_required', 'اكتب التعديل المطلوب أولاً')); return; }
      if (!(seedWorkflow.distribution.rows || []).length) return;
      if (!visualConceptPlanActionBusy('revise-distribution', true)) return;
      showLoader(WFT('plans.dist_revise_loading', 'جاري تعديل التوزيع'),
        WFT('plans.dist_revise_loading_detail', 'يتم تطبيق التعديل على الجدول...'), 30);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.revision = revision;
        payload.distribution = { rows: seedWorkflow.distribution.rows };
        const stamp = visualConceptPlanInputStamp();
        const response = await api('POST', '/api/visual-concept/plans-distribution', payload);
        hideLoader();
        if (stamp !== visualConceptPlanInputStamp()
            || String(visualConceptPlansWorkflowState().distributionRevision || '').trim() !== revision) {
          toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.'));
          return;
        }
        if (!response?.success) { toast(response?.error || WFT('plans.dist_revise_failed', 'تعذر تطبيق التعديل على التوزيع')); return; }
        const workflow = visualConceptPlansWorkflowState();
        workflow.distribution = normalizeVisualConceptPlansWorkflow({
          distribution: { ...response.distribution, checks: [], issues: [] }
        }).distribution;
        workflow.distributionRevision = '';
        workflow.planContext = response.planContext || workflow.planContext || null;
        invalidateVisualConceptPlanGeneration(workflow);
        markVisualConceptDirty();
        renderVisualConceptPage();
      } catch (error) {
        hideLoader();
        toast(error.message || WFT('plans.dist_revise_failed', 'تعذر تطبيق التعديل على التوزيع'));
      } finally {
        visualConceptPlanActionBusy('revise-distribution', false);
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
          workflow.distribution.reviewSignature = mode === 'ai' ? stamp : '';
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

    // Approving a table that still carries confirmed conflicts — or written
    // notes that never passed a check — is allowed, but only through the risk
    // dialog. Its continue button lands on confirmVisualConceptPlansDistributionApproval,
    // which signs the server-side notes acknowledgement first when needed.
    function approveVisualConceptPlansDistribution() {
      const workflow = visualConceptPlansWorkflowState();
      const rows = workflow.distribution.rows || [];
      if (!rows.length || !workflow.distribution.aiReviewed) return;
      const blockingList = visualConceptDistributionBlocking(workflow.distribution);
      const hasConflicts = Boolean(blockingList.length)
        || (workflow.distribution.canProceed === false && Boolean(blockingList.length));
      const notesPending = Boolean(workflow.clientNotes.trim()) && !visualConceptPlanNotesCleared(workflow);
      if (hasConflicts || notesPending) { showVisualConceptDistributionRisk(hasConflicts, notesPending); return; }
      applyVisualConceptPlansDistributionApproval(workflow);
    }

    async function confirmVisualConceptPlansDistributionApproval() {
      const workflow = visualConceptPlansWorkflowState();
      const needsAck = Boolean(workflow.clientNotes.trim()) && !visualConceptPlanNotesCleared(workflow);
      if (!needsAck) { applyVisualConceptPlansDistributionApproval(workflow); return; }
      if (!visualConceptPlanActionBusy('approve-distribution', true)) return;
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const stamp = visualConceptPlanInputStamp();
        const response = await api('POST', '/api/visual-concept/plans-notes-acknowledge', payload);
        if (stamp !== visualConceptPlanInputStamp()) { toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.')); return; }
        if (!response?.success || !response.notesAck) {
          toast(response?.error || WFT('plans.distribution_failed', 'تعذر اعتماد التوزيع'));
          return;
        }
        const current = visualConceptPlansWorkflowState();
        current.notesReview = { ...current.notesReview, acknowledged: true,
          ackSignature: String(response.notesAck.inputSignature || ''),
          ackToken: String(response.notesAck.token || '') };
        applyVisualConceptPlansDistributionApproval(current);
      } catch (error) {
        toast(error.message || WFT('plans.distribution_failed', 'تعذر اعتماد التوزيع'));
      } finally {
        visualConceptPlanActionBusy('approve-distribution', false);
      }
    }

    function applyVisualConceptPlansDistributionApproval(workflow) {
      workflow.distribution.approved = true;
      invalidateVisualConceptPlanGeneration(workflow, false);
      workflow.viewStage = 'generate';
      markVisualConceptDirty();
      renderVisualConceptPage();
    }

    // One risk dialog serves every stage's approve-through-conflicts path:
    // the caller hands it the stage's copy plus the approval it lands on, so
    // the client reads the same responsibility warning no matter what they
    // are overriding.
    let visualConceptPlansRiskContinue = null;

    function showVisualConceptPlansRisk(copy, onContinue) {
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
            closeVisualConceptPlansRisk();
            return;
          }
          if (event.target.closest('[data-plans-risk-continue]')) {
            const proceed = visualConceptPlansRiskContinue;
            closeVisualConceptPlansRisk();
            if (typeof proceed === 'function') proceed();
          }
        });
      }
      visualConceptPlansRiskContinue = onContinue;
      modal.querySelector('#plansDistributionRiskTitle').textContent = copy.title;
      modal.querySelector('#plansDistributionRiskBody').textContent = copy.body;
      modal.querySelector('#plansDistributionRiskOwn').textContent = copy.own;
      modal.querySelector('[data-plans-risk-continue]').textContent = copy.continueLabel;
      modal.querySelector('[data-plans-risk-cancel]').textContent = copy.cancelLabel;
      modal.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(modal);
    }

    function showVisualConceptDistributionRisk(hasConflicts, notesPending) {
      const review = visualConceptPlansWorkflowState().notesReview;
      let title = WFT('plans.dist_risk_title', 'تعارضات في التوزيع');
      let body = WFT('plans.dist_risk_body', 'فحص التعارضات سجّل بنودًا لم تُحل — نتيجة المخططات بهذه الحالة لن تكون دقيقة.');
      if (notesPending && hasConflicts) {
        body = WFT('plans.dist_notes_risk_body', 'فحص التعارضات وفحص الملاحظات سجّلا بنودًا لم تُحل — نتيجة المخططات بهذه الحالة لن تكون دقيقة.');
      } else if (notesPending) {
        title = WFT('plans.notes_risk_title', 'ملاحظات المخططات');
        body = review.verified
          ? WFT('plans.notes_risk_body', 'فحص الملاحظات سجّل تعارضات لم تُحل — نتيجة المخططات بهذه الحالة لن تكون دقيقة.')
          : WFT('plans.notes_risk_body_unchecked', 'ملاحظات المخططات لم تُفحص — نتيجة المخططات بهذه الحالة لن تكون دقيقة.');
      }
      showVisualConceptPlansRisk({
        title, body,
        own: WFT('plans.dist_risk_own', 'إذا أردت الاستمرار فهذا على مسؤوليتك الشخصية.'),
        continueLabel: WFT('plans.dist_risk_continue', 'استمرار'),
        cancelLabel: WFT('plans.dist_risk_cancel', 'إلغاء'),
      }, () => confirmVisualConceptPlansDistributionApproval());
    }

    // The verification stage reuses the distribution disclaimer verbatim —
    // the client signs off on the identical responsibility warning.
    function showVisualConceptVerificationRisk() {
      showVisualConceptPlansRisk({
        title: WFT('plans.verify_risk_title', 'تعارضات في التحقق'),
        body: WFT('plans.dist_risk_body', 'فحص التعارضات سجّل بنودًا لم تُحل — نتيجة المخططات بهذه الحالة لن تكون دقيقة.'),
        own: WFT('plans.dist_risk_own', 'إذا أردت الاستمرار فهذا على مسؤوليتك الشخصية.'),
        continueLabel: WFT('plans.dist_risk_continue', 'استمرار'),
        cancelLabel: WFT('plans.dist_risk_cancel', 'إلغاء'),
      }, () => applyVisualConceptPlansVerificationApproval(visualConceptPlansWorkflowState()));
    }

    function closeVisualConceptPlansRisk() {
      const modal = document.getElementById('plansDistributionRisk');
      if (!modal) return;
      modal.style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    async function checkVisualConceptPlanNotes(options) {
      const silent = Boolean(options && options.silent);
      if (!hasPermission('generate_images') || !visualConceptPlanActionBusy('check-notes', true)) return false;
      if (!silent) showLoader(WFT('plans.notes_loading', 'جاري فحص الملاحظات'), WFT('plans.notes_loading_detail', 'يتم فحص الملاحظات مقابل الكروكي والتوزيع والقيود...'), 35);
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        const stamp = visualConceptPlanInputStamp();
        const response = await visualConceptPlanJobApi('POST', '/api/visual-concept/plans-notes-check', payload);
        if (!silent) hideLoader();
        if (stamp !== visualConceptPlanInputStamp()) {
          if (!silent) toast(WFT('plans.stale_response', 'تغيرت البيانات أثناء المعالجة.'));
          return false;
        }
        if (!response?.success || !response.notesReview) {
          if (!silent) toast(response?.error || WFT('plans.notes_failed', 'تعذر فحص الملاحظات'));
          return false;
        }
        const workflow = visualConceptPlansWorkflowState();
        const previousReview = workflow.notesReview;
        workflow.notesReview = normalizeVisualConceptPlansWorkflow({ notesReview: response.notesReview }).notesReview;
        // A re-check of unchanged inputs mints the same signature — an
        // acknowledgement already signed for them still holds.
        if (previousReview.ackSignature && previousReview.ackSignature === workflow.notesReview.inputSignature) {
          workflow.notesReview.acknowledged = true;
          workflow.notesReview.ackSignature = previousReview.ackSignature;
          workflow.notesReview.ackToken = previousReview.ackToken;
        }
        if (response.primaryFrontage && typeof response.primaryFrontage === 'object') {
          workflow.planContext = { ...(workflow.planContext || {}), primary_frontage: response.primaryFrontage };
        }
        workflow.sourceStamp = stamp;
        markVisualConceptDirty();
        if (!silent) renderVisualConceptPage();
        return visualConceptPlanNotesValid(workflow);
      } catch (error) {
        if (!silent) {
          hideLoader();
          toast(error.message || WFT('plans.notes_failed', 'تعذر فحص الملاحظات'));
        }
        return false;
      } finally {
        visualConceptPlanActionBusy('check-notes', false);
      }
    }

    let visualConceptPlansPromptsPending = false;

    async function prepareVisualConceptPlansPrompts() {
      const initialWorkflow = visualConceptPlansWorkflowState();
      if (!initialWorkflow.verification.approved || !initialWorkflow.distribution.approved || !visualConceptPlanNotesCleared(initialWorkflow)) return;
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
        workflow.status = workflow.promptReady ? 'ready' : 'verified';
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
        // The last in-try render painted while the pending flag was still up —
        // repaint once it clears so the "قيد المعالجة" lock text never lingers.
        renderVisualConceptPage();
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
