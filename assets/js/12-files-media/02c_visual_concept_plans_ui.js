    function visualConceptPlans() {
      if (!Array.isArray(tenantVisualConceptState?.plans2d)) {
        if (tenantVisualConceptState) tenantVisualConceptState.plans2d = [];
        else return [];
      }
      return tenantVisualConceptState.plans2d;
    }

    function visualConceptPlanMode(plan) {
      const slot = tenantVisualConceptState?.slots?.[plan?.id];
      const mode = slot ? slot.mode : plan?.mode;
      return mode === 'upload' ? 'upload' : 'generate';
    }

    function setVisualConceptPlansTab(tab) {
      const active = tab === 'upload' ? 'upload' : 'generate';
      document.querySelectorAll('[data-visual-plans-tab]').forEach(button => {
        button.classList.toggle('active', button.getAttribute('data-visual-plans-tab') === active);
      });
      document.querySelectorAll('[data-visual-plans-panel]').forEach(panel => {
        panel.hidden = panel.getAttribute('data-visual-plans-panel') !== active;
      });
    }

    function visualConceptDistributionTotalsRowsHtml(distribution) {
      const totals = Array.isArray(distribution.totals) ? distribution.totals : [];
      if (!totals.length) return '';
      const fmt = value => (value === null || value === undefined || value === '') ? '—'
        : (typeof value === 'number' ? String(Math.round(value * 100) / 100) : String(value));
      const rowsHtml = totals.map(item => {
        const deltas = [];
        if (typeof item.delta_units === 'number' && item.delta_units) deltas.push(WFT('vc.delta_units', 'وحدات {n}', { n: (item.delta_units > 0 ? '+' : '') + item.delta_units }));
        if (typeof item.delta_area === 'number' && item.delta_area) deltas.push('م² ' + (item.delta_area > 0 ? '+' : '') + item.delta_area);
        const hasRequired = typeof item.required_units === 'number' || typeof item.required_area === 'number';
        const deltaText = deltas.length ? deltas.join('، ') : (hasRequired ? 'مطابق للدراسة' : '—');
        const impact = deltas.length ? '<div class="plans-conflict-location">يؤثر في الدراسة المالية</div>' : '';
        return '<tr class="plans-distribution-total"><td colspan="3">' + escapeHtml(item.component || '') + '</td>' +
          '<td>' + escapeHtml(fmt(item.units)) + ' / ' + escapeHtml(fmt(item.required_units)) + '</td>' +
          '<td>' + escapeHtml(fmt(item.area)) + ' / ' + escapeHtml(fmt(item.required_area)) + '</td>' +
          '<td colspan="2">' + escapeHtml(deltaText) + impact + '</td></tr>';
      }).join('');
      return '<tr class="plans-distribution-total-head"><td colspan="3">إجمالي المكونات</td>' +
        '<td>الوحدات توزيع/دراسة</td><td>المساحة توزيع/دراسة</td><td colspan="2">الفرق</td></tr>' + rowsHtml;
    }

    function visualConceptDistributionEditorHtml(distribution) {
      const rows = Array.isArray(distribution.rows) ? distribution.rows : [];
      const head = '<thead><tr><th>المبنى</th><th>الدور أو نطاق الأدوار</th><th>الاستخدام / المكون</th>' +
        '<th>عدد الوحدات لكل دور</th><th>مساحة الدور الإجمالية</th><th>الحركة والخدمات ضمن المساحة</th><th></th></tr></thead>';
      const body = rows.length ? rows.map(row =>
        '<tr>' +
        '<td><input data-dist-field="building" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.building) + '"></td>' +
        '<td><input data-dist-field="floor_range" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_range) + '" placeholder="1-4"></td>' +
        '<td><input data-dist-field="component" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.component) + '"></td>' +
        '<td><input data-dist-field="units_per_floor" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.units_per_floor ?? '') + '"></td>' +
        '<td><input data-dist-field="floor_area_sqm" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_area_sqm ?? '') + '"></td>' +
        '<td><input data-dist-field="circulation" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.circulation) + '"></td>' +
        '<td><button type="button" class="btn ghost small" data-dist-remove="' + escapeHtml(row.id) + '">حذف</button></td>' +
        '</tr>').join('')
        : '<tr><td colspan="7" class="plans-workflow-empty">لم يُقترح توزيع بعد.</td></tr>';
      return '<div class="plans-workflow-table-wrap"><table class="plans-workflow-table plans-distribution-table">' +
        head + '<tbody>' + body + '</tbody>' +
        '<tfoot data-plans-distribution-totals>' + visualConceptDistributionTotalsRowsHtml(distribution) + '</tfoot>' +
        '</table></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="add-distribution-row">إضافة صف</button></div>';
    }

    function visualConceptPlanNotesValid(workflow = visualConceptPlansWorkflowState()) {
      return !workflow.clientNotes.trim() || Boolean(workflow.notesReview.verified && workflow.notesReview.canProceed
        && workflow.notesReview.token && workflow.notesReview.inputSignature);
    }

    function visualConceptPlanNotesAcked(workflow = visualConceptPlansWorkflowState()) {
      return Boolean(workflow.clientNotes.trim() && workflow.notesReview.acknowledged && workflow.notesReview.ackToken);
    }

    // Notes clear generation two ways: a clean check, or the client's signed
    // responsibility acknowledgement from the risk dialog. The server
    // re-verifies whichever token is present — presence here is display only.
    function visualConceptPlanNotesCleared(workflow = visualConceptPlansWorkflowState()) {
      return visualConceptPlanNotesValid(workflow) || visualConceptPlanNotesAcked(workflow);
    }

    function visualConceptPlanNotesResultsHtml(workflow = visualConceptPlansWorkflowState()) {
      if (!workflow.clientNotes.trim()) return '';
      const review = workflow.notesReview;
      if (!review.verified) {
        return '<p class="tenant-hint">' + escapeHtml(review.acknowledged
          ? WFT('plans.notes_acknowledged', 'الملاحظات معتمدة بإخلاء مسؤولية دون فحص.')
          : WFT('plans.notes_unchecked', 'الملاحظات غير مفحوصة.')) + '</p>';
      }
      const labels = { 'متعارض': WFT('plans.note_conflict', 'متعارض'),
        'يحتاج توضيح': WFT('plans.note_unclear', 'يحتاج توضيح') };
      // Only unresolved findings render — a «مطابق» verdict listed in the
      // warning box read as a conflict.
      const pending = review.checks.filter(check => check.result !== 'مطابق');
      if (!pending.length) {
        return '<p class="plans-workflow-success">' + escapeHtml(WFT('plans.notes_clear', 'لا توجد تعارضات في الملاحظات.')) + '</p>';
      }
      const rows = pending.map(check => '<li><strong>' + escapeHtml(labels[check.result] || check.result) +
        '</strong>: ' + escapeHtml(check.note || '') + (check.detail ? '<div>' + escapeHtml(check.detail) + '</div>' : '') + '</li>').join('');
      return '<div class="plans-workflow-notice"><ul class="plans-issue-list">' + rows + '</ul></div>' +
        (review.acknowledged
          ? '<p class="tenant-hint">' + escapeHtml(WFT('plans.notes_acknowledged_conflicts', 'الملاحظات معتمدة بإخلاء مسؤولية رغم التعارضات.')) + '</p>'
          : '');
    }

    function visualConceptDistributionResultsHtml(distribution) {
      const rows = Array.isArray(distribution.rows) ? distribution.rows : [];
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];
      // A «مطابق» verdict is not a finding — only conflicts and open items
      // render, so a clean row never shows inside the warning box.
      const findings = checks.filter(item => item.result !== 'مطابق').map(item => {
          const label = item.result === 'متعارض' && item.fixable === false
            ? 'متعارض — مصدره بيانات المشروع المعتمدة أو الاشتراطات'
            : (item.result || '');
          return (label ? label + ': ' : '') + (item.detail || item.item || '');
        })
        .concat(issues.flatMap(item =>
          (Array.isArray(item.points) && item.points.length ? item.points : [item.title || ''])))
        .filter(Boolean);
      const reviewed = Boolean(distribution.aiReviewed);
      const findingsHtml = findings.length
        ? '<div class="plans-workflow-notice"><ul class="plans-issue-list">' +
          findings.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul></div>'
        : (rows.length
          ? (reviewed
            ? '<p class="plans-workflow-success">لا توجد تعارضات في التوزيع.</p>'
            : '<p class="tenant-hint">لم يُفحص بعد.</p>')
          : '');
      // Findings and pending notes keep the button live — approving through
      // them routes via the responsibility warning dialog instead of a dead
      // disabled control.
      const canApprove = rows.length > 0 && reviewed;
      return findingsHtml +
        '<div class="visual-concept-actions">' +
        '<button type="button" class="btn ghost small" data-plans-workflow-action="check-distribution" ' + (rows.length ? '' : 'disabled') + '>فحص التعارضات</button>' +
        '<button type="button" class="btn primary small" data-plans-workflow-action="approve-distribution" ' + (canApprove ? '' : 'disabled') + '>اعتماد التوزيع</button>' +
        (distribution.approved ? '<span class="plans-workflow-success">التوزيع معتمد</span>' : '') +
        '</div>';
    }

    function visualConceptDistributionBlocking(distribution) {
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];
      return checks.filter(item => item.result === 'متعارض' || item.severity === 'high')
        .concat(issues.filter(item => item.severity === 'high'));
    }

    function renderVisualConceptPlansWorkflow() {
      const root = document.getElementById('visualConceptPlansWorkflow');
      if (!root) return;
      const workflow = visualConceptPlansWorkflowState();
      const verification = workflow.verification || {};
      const distribution = workflow.distribution || {};
      const verified = Boolean(verification.approved);
      const distApproved = Boolean(distribution.approved) && visualConceptPlanNotesCleared(workflow);
      const promptReady = Boolean(workflow.promptReady);
      const defaultStage = !verified ? 'verify' : (distApproved ? 'generate' : 'boundary');
      const requestedStage = ['verify', 'boundary', 'generate', 'other'].includes(workflow.viewStage) ? workflow.viewStage : defaultStage;
      const activeStage = (requestedStage === 'generate' || requestedStage === 'other') && !distApproved
        ? (verified ? 'boundary' : 'verify')
        : (requestedStage === 'boundary' && !verified ? 'verify' : requestedStage);
      const checks = Array.isArray(verification.checks) ? verification.checks : [];
      const conflicts = checks.filter(item => item.result === 'متعارض');
      // Conflicts keep the button live — approving through them routes via the
      // responsibility warning dialog, same as the distribution approval does.
      const canApprove = checks.length > 0 || verification.canProceed
        || (Array.isArray(verification.issues) && verification.issues.length > 0);
      const checkRows = conflicts.length ? conflicts.map(item =>
        '<tr><td>' + escapeHtml(item.item || '') +
        ((item.section || item.field) ? '<div class="plans-conflict-location">' + escapeHtml(item.section || '') + (item.field ? ' — ' + escapeHtml(item.field) : '') + '</div>' : '') +
        '</td><td>' + escapeHtml(item.project || '') + '</td><td>' + escapeHtml(item.regulatory || '') + '</td><td><span class="plans-check-result plans-check-' + escapeHtml(item.result || '') + '">' + escapeHtml(item.result || '') + '</span></td><td>' +
        (Array.isArray(item.issues) && item.issues.length ? '<ul class="plans-issue-list">' + item.issues.map(issue => '<li>' + escapeHtml(issue) + '</li>').join('') + '</ul>' : '') +
        (item.suggestion ? '<div class="plans-conflict-solution"><strong>' + escapeHtml(WFT('plans.proposed_solution', 'الحل المقترح:')) + '</strong> ' + escapeHtml(item.suggestion) + '</div>' : '') +
        escapeHtml(item.action || '') + '</td></tr>'
      ).join('') : '<tr><td colspan="5" class="plans-workflow-empty plans-workflow-success">' + escapeHtml(WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')) + '</td></tr>';
      const conflictPoints = conflicts.flatMap(item => Array.isArray(item.issues) ? item.issues : []).filter(Boolean);
      const issueList = conflictPoints.length
        ? '<ul class="plans-issue-list plans-issue-summary">' + conflictPoints.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul>'
        : '';
      const sitePlan = VISUAL_CONCEPT_PLAN_KINDS.find(item => item.kind === 'site');
      const otherPlans = VISUAL_CONCEPT_PLAN_KINDS.filter(item => item.kind !== 'site');
      const siteHasImage = Boolean(tenantVisualConceptState.slots[sitePlan.id]?.imageUrl);
      const otherHasImage = otherPlans.some(item => tenantVisualConceptState.slots[item.id]?.imageUrl);
      const sitePlanCard = promptReady || siteHasImage
        ? renderVisualConceptSlot({ id: sitePlan.id, label: sitePlan.label, group: 'plans' }, visualConceptSlotLocked(sitePlan.id))
        : '<p class="tenant-hint">مخطط الموقع العام غير جاهز للتوليد.</p>';
      const otherPlanCards = promptReady || otherHasImage
        ? '<div class="visual-concept-stack">' + otherPlans.map(definition =>
          renderVisualConceptSlot({ id: definition.id, label: definition.label, group: 'plans' }, visualConceptSlotLocked(definition.id))
        ).join('') + '</div>'
        : '<p class="tenant-hint">مخططا الاستخدامات والكتلة غير جاهزين للتوليد.</p>';
      root.innerHTML =
        '<div class="plans-workflow-card">' +
        '<ol class="plans-workflow-steps">' +
        '<li class="' + (activeStage === 'verify' ? 'is-active' : (verified ? 'is-complete' : '')) + '"><button type="button" data-plans-workflow-tab="verify">التحقق من التضارب</button></li>' +
        '<li class="' + (activeStage === 'boundary' ? 'is-active' : (distApproved ? 'is-complete' : '')) + '"><button type="button" data-plans-workflow-tab="boundary" ' + (!verified ? 'disabled' : '') + '>توزيع المكونات</button></li>' +
        '<li class="' + (activeStage === 'generate' ? 'is-active' : '') + '"><button type="button" data-plans-workflow-tab="generate" ' + (!distApproved ? 'disabled' : '') + '>' + escapeHtml(WFT('plans.stage_site', 'المخطط العام المبسط')) + '</button></li>' +
        '<li class="' + (activeStage === 'other' ? 'is-active' : '') + '"><button type="button" data-plans-workflow-tab="other" ' + (!distApproved ? 'disabled' : '') + '>' + escapeHtml(WFT('plans.stage_other', 'مخططا الاستخدامات والكتلة')) + '</button></li>' +
        '</ol>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="verify"' + (activeStage !== 'verify' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>التحقق من التضارب</h4><button type="button" class="btn primary small" data-plans-workflow-action="verify">تحقق</button></div>' +
        '<p class="' + (conflicts.length ? 'tenant-hint' : 'plans-workflow-success') + '" data-plans-verification-summary>' + escapeHtml(conflicts.length ? WFT('plans.conflicts_count', 'عدد التعارضات المباشرة: ') + conflicts.length : WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')) + '</p>' +
        (issueList ? '<div class="plans-workflow-notice">' + issueList + '</div>' : '') +
        '<div class="plans-workflow-table-wrap"><table class="plans-workflow-table plans-check-table"><thead><tr><th>البند</th><th>بيانات المشروع</th><th>البيانات الموثقة</th><th>النتيجة</th><th>المشاكل والإجراء</th></tr></thead><tbody>' + checkRows + '</tbody></table></div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn primary small" data-plans-workflow-action="approve-verification" ' + (!canApprove ? 'disabled' : '') + '>اعتماد نتيجة التحقق</button></div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="boundary"' + (activeStage !== 'boundary' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>توزيع المكونات على الأدوار</h4><button type="button" class="btn primary small" data-plans-workflow-action="propose-distribution">اقتراح التوزيع</button></div>' +
        '<div class="plans-workflow-panel-head"><h4>' + escapeHtml(WFT('plans.distribution_notes_title', 'ملاحظات التوزيع')) + '</h4><span class="tenant-hint">' + escapeHtml(WFT('plans.notes_optional', 'اختياري')) + '</span></div>' +
        '<textarea rows="3" maxlength="1000000" data-plans-distribution-notes>' + escapeHtml(workflow.distributionNotes) + '</textarea>' +
        '<div data-plans-distribution-editor>' + visualConceptDistributionEditorHtml(distribution) + '</div>' +
        '<div class="plans-distribution-revise">' +
        '<input type="text" maxlength="4000" data-plans-distribution-revision value="' + escapeHtml(workflow.distributionRevision || '') + '" placeholder="' + escapeHtml(WFT('plans.dist_revise_placeholder', 'انقل المكاتب من الدور الثالث إلى الخامس')) + '">' +
        '<button type="button" class="btn ghost small" data-plans-workflow-action="revise-distribution"' + ((Array.isArray(distribution.rows) && distribution.rows.length) ? '' : ' disabled') + '>' + escapeHtml(WFT('plans.dist_revise_button', 'تطبيق التعديل')) + '</button>' +
        '</div>' +
        '<div data-plans-distribution-results>' + visualConceptDistributionResultsHtml(distribution) + '</div>' +
        '<div class="plans-workflow-panel-head"><h4>' + escapeHtml(WFT('plans.notes_title', 'ملاحظات توليد المخططات')) + '</h4><span class="tenant-hint">' + escapeHtml(WFT('plans.notes_optional', 'اختياري')) + '</span></div>' +
        '<textarea id="visualConceptPlanClientNotes" data-plans-client-notes rows="4" maxlength="1000000">' + escapeHtml(workflow.clientNotes) + '</textarea>' +
        '<div data-plans-notes-results>' + visualConceptPlanNotesResultsHtml(workflow) + '</div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="check-notes" ' + (!workflow.clientNotes.trim() ? 'disabled' : '') + '>' + escapeHtml(WFT('plans.notes_check', 'فحص الملاحظات')) + '</button></div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="generate"' + (activeStage !== 'generate' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>' + escapeHtml(WFT('plans.stage_site_title', 'المخطط العام المبسط بصيغة SVG')) + '</h4>' + (promptReady ? '' : '<button type="button" class="btn primary small" data-plans-workflow-action="prepare-prompts">' + escapeHtml(WFT('plans.stage_site_prepare', 'تجهيز المخطط')) + '</button>') + '</div>' +
        '<p class="tenant-hint">' + escapeHtml(promptReady ? WFT('plans.stage_site_ready', 'مخطط الموقع جاهز للتوليد.') : (workflow.promptsError ? WFT('plans.stage_site_error', 'تعذر تجهيز المخطط: {error}', { error: workflow.promptsError }) : WFT('plans.stage_site_not_ready', 'مخطط الموقع غير جاهز للتوليد.'))) + '</p>' +
        '<div data-plans-workflow-prompts>' + sitePlanCard + '</div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="other"' + (activeStage !== 'other' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>' + escapeHtml(WFT('plans.stage_other_title', 'مخططا الاستخدامات والكتلة')) + '</h4>' + (promptReady ? '' : '<button type="button" class="btn primary small" data-plans-workflow-action="prepare-prompts">' + escapeHtml(WFT('plans.stage_other_prepare', 'تجهيز المخططات')) + '</button>') + '</div>' +
        '<p class="tenant-hint">' + escapeHtml(promptReady ? WFT('plans.stage_other_ready', 'مخططا الاستخدامات والكتلة جاهزان للتوليد.') : (workflow.promptsError ? WFT('plans.stage_other_error', 'تعذر تجهيز المخططات: {error}', { error: workflow.promptsError }) : WFT('plans.stage_other_not_ready', 'مخططا الاستخدامات والكتلة غير جاهزين للتوليد.'))) + '</p>' +
        '<div data-plans-workflow-prompts>' + otherPlanCards + '</div>' +
        '</section>' +
        '</div>';
      // Delegated binding, once: the distribution results container is re-rendered
      // in place after every re-check, so per-button listeners would die with it.
      if (!root.dataset.plansWorkflowBound) {
        root.dataset.plansWorkflowBound = 'true';
        root.addEventListener('click', event => {
          const tab = event.target.closest('[data-plans-workflow-tab]');
          if (tab && !tab.disabled) {
            const stage = tab.getAttribute('data-plans-workflow-tab');
            const state = visualConceptPlansWorkflowState();
            if (stage === 'boundary' && !state.verification.approved) return;
            if ((stage === 'generate' || stage === 'other')
                && !(state.distribution.approved && visualConceptPlanNotesCleared(state))) return;
            state.viewStage = stage;
            persistVisualConceptDraftState();
            renderVisualConceptPage();
            return;
          }
          const removeBtn = event.target.closest('[data-dist-remove]');
          if (removeBtn) {
            const state = visualConceptPlansWorkflowState();
            const id = removeBtn.getAttribute('data-dist-remove');
            state.distribution.rows = (state.distribution.rows || []).filter(item => item.id !== id);
            state.distribution.approved = false;
            state.distribution.aiReviewed = false;
            state.distribution.checks = [];
            state.distribution.issues = [];
            invalidateVisualConceptPlanGeneration(state);
            markVisualConceptDirty();
            renderVisualConceptPage();
            scheduleVisualConceptDistributionCheck();
            return;
          }
          const actionBtn = event.target.closest('[data-plans-workflow-action]');
          if (!actionBtn || actionBtn.disabled) return;
          const action = actionBtn.getAttribute('data-plans-workflow-action');
          const state = visualConceptPlansWorkflowState();
          if (action === 'verify') verifyVisualConceptPlans();
          else if (action === 'approve-verification') approveVisualConceptPlansVerification();
          else if (action === 'propose-distribution') proposeVisualConceptPlansDistribution();
          else if (action === 'revise-distribution') reviseVisualConceptPlansDistribution();
          else if (action === 'check-distribution') checkVisualConceptPlansDistribution('ai');
          else if (action === 'check-notes') checkVisualConceptPlanNotes();
          else if (action === 'add-distribution-row') addVisualConceptDistributionRow();
          else if (action === 'approve-distribution') approveVisualConceptPlansDistribution();
          else if (action === 'prepare-prompts') prepareVisualConceptPlansPrompts();
        });
        root.addEventListener('input', event => {
          const revisionInput = event.target.closest('[data-plans-distribution-revision]');
          if (revisionInput) {
            const state = visualConceptPlansWorkflowState();
            state.distributionRevision = String(revisionInput.value || '').slice(0, 4000);
            markVisualConceptDirty();
            return;
          }
          const distNotesInput = event.target.closest('[data-plans-distribution-notes]');
          if (distNotesInput) {
            const state = visualConceptPlansWorkflowState();
            state.distributionNotes = String(distNotesInput.value || '').slice(0, 1000000);
            markVisualConceptDirty();
            return;
          }
          const input = event.target.closest('[data-plans-client-notes]');
          if (!input) return;
          setVisualConceptPlanNotes(input.value);
          const state = visualConceptPlansWorkflowState();
          const notesHost = root.querySelector('[data-plans-notes-results]');
          if (notesHost) notesHost.innerHTML = visualConceptPlanNotesResultsHtml(state);
          const resultsHost = root.querySelector('[data-plans-distribution-results]');
          if (resultsHost) resultsHost.innerHTML = visualConceptDistributionResultsHtml(state.distribution);
          const check = root.querySelector('[data-plans-workflow-action="check-notes"]');
          if (check) check.disabled = !state.clientNotes.trim();
          const generate = root.querySelector('[data-plans-workflow-tab="generate"]');
          if (generate) generate.disabled = true;
        });
        root.addEventListener('change', event => {
          const input = event.target.closest('[data-dist-field]');
          if (!input) return;
          const state = visualConceptPlansWorkflowState();
          const id = input.getAttribute('data-dist-id');
          const field = input.getAttribute('data-dist-field');
          const row = (state.distribution.rows || []).find(item => item.id === id);
          if (!row) return;
          row[field] = input.value;
          state.distribution.approved = false;
          state.distribution.aiReviewed = false;
          state.distribution.checks = [];
          state.distribution.issues = [];
          invalidateVisualConceptPlanGeneration(state);
          markVisualConceptDirty();
          scheduleVisualConceptDistributionCheck();
        });
      }
    }

    function renderVisualConceptPlans() {
      renderVisualConceptPlansWorkflow();
      // The conflict chat lives as a floating panel on the generate panel so it
      // survives the workflow's innerHTML re-renders and auto-hides on the
      // upload tab with its host.
      if (typeof mountPlansConflictChat === 'function') {
        mountPlansConflictChat(document.getElementById('visualConceptPlansGeneratePanel'));
      }
      if (typeof syncPlansConflictChat === 'function') syncPlansConflictChat();
      const uploadHost = document.getElementById('visualConceptPlansUploadList');
      const count = document.getElementById('visualConceptPlansCount');
      const input = document.getElementById('visualConceptPlansUploadInput');
      const plans = visualConceptPlans().filter(plan => !isVisualConceptWorkflowPlan(plan.id));
      if (count) count.textContent = plans.length ? WFT('vc.plans_count', '{n} مخطط مرفوع', { n: plans.length }) : WFT('vc.plans_none', 'لا توجد مخططات مرفوعة.');
      if (input) input.disabled = plans.length >= VISUAL_CONCEPT_MAX_PLANS;
      if (!uploadHost) return;
      plans.forEach(plan => {
        if (!tenantVisualConceptState.slots[plan.id]) tenantVisualConceptState.slots[plan.id] = visualConceptPlanSeed(plan) || emptyVisualConceptSlot(plan.id);
      });
      uploadHost.innerHTML = plans.length
        ? '<div class="visual-concept-stack">' + plans.map(plan => renderVisualConceptSlot({ id: plan.id, label: plan.title || 'مخطط', group: 'plans' }, false)).join('') + '</div>'
        : '<p class="tenant-hint">لا توجد مخططات مرفوعة.</p>';
    }
