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
        : String(value);
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
        '<th>عدد الوحدات لكل دور</th><th>مساحة الدور الإجمالية</th><th>الحركة والخدمات ضمن المساحة</th><th>' +
        escapeHtml(WFT('plans.action_label', 'إجراء')) + '</th></tr></thead>';
      const groups = new Map();
      rows.forEach(row => {
        const building = String(row.building || '').trim() || WFT('plans.building_unnamed', 'مبنى غير محدد');
        if (!groups.has(building)) groups.set(building, []);
        groups.get(building).push(row);
      });
      const rowHtml = row =>
        '<tr>' +
        '<td><input data-dist-field="building" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.building) + '"></td>' +
        '<td><input data-dist-field="floor_range" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_range) + '" placeholder="1-4"></td>' +
        '<td><input data-dist-field="component" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.component) + '"></td>' +
        '<td><input data-dist-field="units_per_floor" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.units_per_floor ?? '') + '"></td>' +
        '<td><input data-dist-field="floor_area_sqm" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.floor_area_sqm ?? '') + '"></td>' +
        '<td><input data-dist-field="circulation" data-dist-id="' + escapeHtml(row.id) + '" value="' + escapeHtml(row.circulation) + '"></td>' +
        '<td><button type="button" class="btn ghost small" data-dist-remove="' + escapeHtml(row.id) + '">حذف</button></td>' +
        '</tr>';
      const body = rows.length ? Array.from(groups.entries()).map(([building, buildingRows]) => {
        const isUnnamed = building === WFT('plans.building_unnamed', 'مبنى غير محدد');
        const bNameAttr = isUnnamed ? '' : escapeHtml(building);
        return '<tr class="plans-distribution-building"><th colspan="7">' +
          '<div class="plans-distribution-building-header">' +
          '<span>' + escapeHtml(building) + '</span>' +
          '<div class="plans-distribution-building-meta">' +
          '<span class="plans-distribution-building-count">' +
          escapeHtml(WFT('plans.building_items_count', 'عدد البنود: {count}', { count: buildingRows.length })) + '</span>' +
          (!isUnnamed ? '<button type="button" class="btn ghost small plans-dist-add-item-btn" data-plans-workflow-action="add-distribution-row" data-dist-building="' + bNameAttr + '">' +
          escapeHtml(WFT('plans.add_building_item', 'إضافة بند')) + '</button>' : '') +
          '</div></div></th></tr>' +
          buildingRows.map(rowHtml).join('');
      }).join('')
        : '<tr><td colspan="7" class="plans-workflow-empty">لم يُقترح توزيع بعد.</td></tr>';
      return '<div class="plans-workflow-table-wrap plans-distribution-table-wrap"><table class="plans-workflow-table plans-distribution-table">' +
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
      let result = '';
      if (!review.verified) {
        result = '<p class="tenant-hint">' + escapeHtml(review.acknowledged
          ? WFT('plans.notes_acknowledged', 'الملاحظات معتمدة بإخلاء مسؤولية دون فحص.')
          : WFT('plans.notes_unchecked', 'الملاحظات غير مفحوصة.')) + '</p>';
      } else {
        const labels = { 'متعارض': WFT('plans.note_conflict', 'متعارض'),
          'يحتاج توضيح': WFT('plans.note_unclear', 'يحتاج توضيح') };
        // Only unresolved findings render — a «مطابق» verdict listed in the
        // warning box read as a conflict.
        const pending = review.checks.filter(check => check.result !== 'مطابق');
        if (!pending.length) {
          result = '<p class="plans-workflow-success">' + escapeHtml(WFT('plans.notes_clear', 'لا توجد تعارضات في الملاحظات.')) + '</p>';
        } else {
          const rows = pending.map(check => '<li><strong>' + escapeHtml(labels[check.result] || check.result) +
            '</strong>: ' + escapeHtml(check.note || '') + (check.detail ? '<div>' + escapeHtml(check.detail) + '</div>' : '') + '</li>').join('');
          result = '<div class="plans-workflow-notice"><ul class="plans-issue-list">' + rows + '</ul></div>' +
            (review.acknowledged
              ? '<p class="tenant-hint">' + escapeHtml(WFT('plans.notes_acknowledged_conflicts', 'الملاحظات معتمدة بإخلاء مسؤولية رغم التعارضات.')) + '</p>'
              : '');
        }
      }
      return '<div class="plans-workflow-result-block plans-notes-review-result"><h5>' +
        escapeHtml(WFT('plans.notes_result_heading', 'نتيجة فحص الملاحظات')) + '</h5>' + result + '</div>';
    }

    function visualConceptDistributionResultsHtml(distribution) {
      const rows = Array.isArray(distribution.rows) ? distribution.rows : [];
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];

      const realConflicts = [];
      const advisoryNotices = [];

      checks.filter(item => item.result !== 'مطابق').forEach(item => {
        const text = (item.detail || item.item || '');
        const isAdvisory = typeof isAdvisoryOrCompliantNotice === 'function' && isAdvisoryOrCompliantNotice(text + ' ' + (item.item || ''));
        const label = item.result === 'متعارض' && !isAdvisory
          ? (item.fixable === false ? 'متعارض — مصدره بيانات المشروع المعتمدة أو الاشتراطات' : 'متعارض')
          : (isAdvisory ? 'ملاحظة تنظيمية' : (item.result || 'ملاحظة'));
        const entry = (label ? label + ': ' : '') + text;
        if (item.result === 'متعارض' && !isAdvisory) {
          realConflicts.push(entry);
        } else {
          advisoryNotices.push(entry);
        }
      });

      issues.forEach(item => {
        const points = Array.isArray(item.points) && item.points.length ? item.points : [item.title || ''];
        points.filter(Boolean).forEach(point => {
          const full = (item.title ? item.title + ': ' : '') + point;
          const isAdvisory = typeof isAdvisoryOrCompliantNotice === 'function' && isAdvisoryOrCompliantNotice(full);
          if (item.severity === 'high' && !isAdvisory) {
            realConflicts.push(full);
          } else {
            advisoryNotices.push(full);
          }
        });
      });

      const reviewed = Boolean(distribution.aiReviewed);
      let resultsHtml = '';
      if (realConflicts.length) {
        resultsHtml += '<div class="plans-workflow-notice"><ul class="plans-issue-list">' +
          realConflicts.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul></div>';
      }
      if (advisoryNotices.length) {
        resultsHtml += '<div class="plans-workflow-info"><ul class="plans-issue-list">' +
          advisoryNotices.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul></div>';
      }
      if (!realConflicts.length && !advisoryNotices.length) {
        if (rows.length) {
          resultsHtml = reviewed
            ? '<p class="plans-workflow-success">لا توجد تعارضات في التوزيع.</p>'
            : '<p class="tenant-hint">لم يُفحص بعد.</p>';
        }
      }

      const canApprove = rows.length > 0 && reviewed;
      const resultHtml = resultsHtml || rows.length
        ? '<div class="plans-workflow-result-block plans-distribution-review-result"><h5>' +
          escapeHtml(WFT('plans.distribution_result_heading', 'نتيجة فحص التوزيع')) + '</h5>' + resultsHtml + '</div>'
        : '';
      return resultHtml +
        '<div class="visual-concept-actions">' +
        '<button type="button" class="btn primary small" data-plans-workflow-action="approve-distribution" ' + (canApprove ? '' : 'disabled') + '>اعتماد التوزيع</button>' +
        (distribution.approved ? '<span class="plans-workflow-success">التوزيع معتمد</span>' : '') +
        '</div>';
    }

    function visualConceptDistributionBlocking(distribution) {
      const checks = Array.isArray(distribution.checks) ? distribution.checks : [];
      const issues = Array.isArray(distribution.issues) ? distribution.issues : [];
      return checks.filter(item => {
        if (item.result !== 'متعارض' && item.severity !== 'high') return false;
        const text = (item.detail || '') + ' ' + (item.item || '');
        return typeof isAdvisoryOrCompliantNotice === 'function' ? !isAdvisoryOrCompliantNotice(text) : true;
      }).concat(issues.filter(item => {
        if (item.severity !== 'high') return false;
        const text = (item.title || '') + ' ' + (Array.isArray(item.points) ? item.points.join(' ') : '');
        return typeof isAdvisoryOrCompliantNotice === 'function' ? !isAdvisoryOrCompliantNotice(text) : true;
      }));
    }

    function renderVisualConceptSitePlanCard() {
      const slot = tenantVisualConceptState.slots.plan_site || emptyVisualConceptSlot('plan_site');
      const fallbackDataUri = slot.svgCode ? ('data:image/svg+xml;utf8,' + encodeURIComponent(slot.svgCode)) : '';
      const rawImage = slot.approvedImageUrl || slot.imageUrl || fallbackDataUri;
      const image = isSessionOnlyImageUrl(rawImage) ? '' : rawImage;
      const title = visualConceptSlotLabel('plan_site');
      const approved = slot.status === 'approved';
      const locked = visualConceptSlotLocked('plan_site');
      const status = approved ? 'معتمد' : slot.status === 'generating' ? 'قيد التوليد'
        : slot.status === 'review' ? 'مسودة - جاهزة للاعتماد' : 'مسودة';
      const chatMessages = slot.chat || [];
      const workflow = visualConceptPlansWorkflowState();
      const assistant = workflow.siteAssistant || {};
      const activeProgress = (workflow.jobTodos || []).find(item => item.status === 'active');
      const assistantProgressLabel = activeProgress?.label || 'تجهيز المخطط وتحليل متطلباته';
      const assistantProgressMarkup = '<div class="tenant-hint visual-plan-site-assistant-status" data-site-chat-status>المرحلة الحالية: ' +
        escapeHtml(assistantProgressLabel) + '</div>';
      const assistantBusy = typeof visualConceptSiteAssistantBusy !== 'undefined'
        && visualConceptSiteAssistantBusy;
      const conversationStarted = Boolean((assistant.turns || []).length || chatMessages.length);
      const hasConversation = Boolean(conversationStarted || (assistant.answers || []).length
        || assistant.summary || assistant.pendingQuestion || assistant.generateRequested
        || assistant.designSpec || Object.keys(assistant.checkpoints || {}).length);
      const resetBusy = typeof visualConceptPlansResetBusy === 'function'
        && visualConceptPlansResetBusy();
      const restart = hasConversation
        ? '<div class="visual-plan-site-controls"><button type="button" class="btn ghost small" data-visual-action="restart-site-plan" data-visual-slot="plan_site" ' +
          (assistantBusy || resetBusy || locked ? 'disabled' : '') + '>البدء من جديد</button></div>'
        : '';
      const canCompose = conversationStarted && !assistantBusy && !locked;
      const chat = chatMessages.map(item => {
        const isUser = item.role === 'user';
        const choices = !isUser && Array.isArray(item.choices) && item.choices.length
          ? '<div class="visual-plan-site-choices">' + item.choices.map(choice =>
            '<button type="button" class="btn ghost small" data-visual-action="chat-choice" data-visual-slot="plan_site" data-choice="' + escapeHtml(choice) + '"' + (assistantBusy ? ' disabled' : '') + '>' + escapeHtml(choice) + '</button>'
          ).join('') + '<button type="button" class="btn ghost small" data-visual-action="chat-choice" data-visual-slot="plan_site" data-choice-other="true"' + (assistantBusy ? ' disabled' : '') + '>أخرى</button></div>'
          : '';
        return '<article class="visual-plan-site-message ' + (isUser ? 'is-user' : 'is-assistant') + '">' +
          '<div class="visual-plan-site-message-text">' + escapeHtml(item.text || '') + '</div>' + choices + '</article>';
      }).join('') || (assistantBusy
        ? assistantProgressMarkup
        : '<div class="tenant-hint visual-plan-site-empty-chat"><p>لا توجد رسائل بعد.</p>' +
          (!conversationStarted ? '<button type="button" class="btn primary small" data-visual-action="start-site-chat" data-visual-slot="plan_site" ' +
            (locked ? 'disabled' : '') + '>بدء المحادثة</button>' : '') + '</div>');
      const assistantStatus = assistantBusy
        ? (chatMessages.length ? assistantProgressMarkup : '') : '';
      const preview = image
        ? '<div class="visual-plan-site-preview" data-visual-zoom="' + escapeHtml(image) + '" data-visual-title="' + escapeHtml(title) + '"><img src="' + escapeHtml(image) + '" alt="' + escapeHtml(title) + '"></div>'
        : '<div class="visual-plan-site-preview-empty">لا توجد معاينة بعد.</div>';
      const zoom = image
        ? '<button type="button" class="btn ghost small" data-visual-zoom="' + escapeHtml(image) + '" data-visual-title="' + escapeHtml(title) + '">عرض بالحجم الكامل</button>'
        : '';
      const approve = image || approved
        ? '<button type="button" class="btn primary small" data-visual-action="' + (approved ? 'unapprove' : 'approve') + '" data-visual-slot="plan_site" ' + (locked ? 'disabled' : '') + '>' + (approved ? 'إلغاء الاعتماد' : 'اعتماد') + '</button>'
        : '';
      const remove = image && !approved
        ? '<button type="button" class="btn danger small" data-visual-action="delete-image" data-visual-slot="plan_site">حذف الصورة</button>'
        : '';
      return '<article class="visual-concept-card visual-plan-site-card" data-visual-slot="plan_site">' +
        '<div class="visual-concept-head"><h3>' + escapeHtml(title) + '</h3><span class="visual-concept-status ' + escapeHtml(slot.status || 'pending') + '">' + escapeHtml(status) + '</span></div>' +
        '<div class="visual-plan-site-layout">' +
        '<section class="visual-plan-site-chat-panel" aria-label="محادثة المخطط">' +
        restart +
        '<div class="visual-plan-site-messages" role="log" aria-live="polite">' + chat + assistantStatus + '</div>' +
        '<div data-plans-workflow-todos>' + (typeof visualConceptPlanTodoMarkup === 'function' ? visualConceptPlanTodoMarkup(workflow.jobTodos, workflow.jobError) : '') + '</div>' +
        '<div class="visual-plan-site-composer"><textarea data-visual-chat="plan_site" rows="2" placeholder="رسالة جديدة" ' + (!canCompose ? 'disabled' : '') + '></textarea>' +
        '<button type="button" class="btn primary small" data-visual-action="chat" data-visual-slot="plan_site" ' + (!canCompose ? 'disabled' : '') + '>إرسال</button></div>' +
        '</section>' +
        '<aside class="visual-plan-site-preview-panel"><h4>معاينة المخطط</h4>' + preview +
        '<div class="visual-concept-actions">' + zoom + approve + remove + '</div></aside>' +
        '</div></article>';
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
      const conflicts = checks.filter(item => item.result === 'متعارض'
        && !(typeof isAdvisoryOrCompliantNotice === 'function' && isAdvisoryOrCompliantNotice((item.detail || '') + ' ' + (item.item || '') + ' ' + (item.suggestion || ''))));
      const checkFindings = checks.filter(item => item && item.result && item.result !== 'مطابق');
      const verificationIssues = Array.isArray(verification.issues) ? verification.issues : [];
      const hasVerificationResult = checks.length > 0 || verificationIssues.length > 0
        || Boolean(verification.summary) || verification.canProceed;
      // Conflicts keep the button live — approving through them routes via the
      // responsibility warning dialog, same as the distribution approval does.
      const canApprove = checks.length > 0 || verification.canProceed
        || (Array.isArray(verification.issues) && verification.issues.length > 0);
      const checkRows = checkFindings.map(item => {
        const isAdvisory = typeof isAdvisoryOrCompliantNotice === 'function'
          && isAdvisoryOrCompliantNotice((item.detail || '') + ' ' + (item.item || '') + ' ' + (item.suggestion || ''));
        const displayResult = (item.result === 'متعارض' && isAdvisory) ? 'ملاحظة تنظيمية' : (item.result || '');
        const badgeClass = isAdvisory ? 'plans-check-notice' : ('plans-check-' + escapeHtml(item.result || ''));
        return '<tr><td>' + escapeHtml(item.item || '') +
          ((item.section || item.field) ? '<div class="plans-conflict-location">' + escapeHtml(item.section || '') + (item.field ? ' — ' + escapeHtml(item.field) : '') + '</div>' : '') +
          '</td><td>' + escapeHtml(item.project || '') + '</td><td>' + escapeHtml(item.regulatory || '') + '</td><td><span class="plans-check-result ' + badgeClass + '">' + escapeHtml(displayResult) + '</span></td><td>' +
          (Array.isArray(item.issues) && item.issues.length ? '<ul class="plans-issue-list">' + item.issues.map(issue => '<li>' + escapeHtml(issue) + '</li>').join('') + '</ul>' : '') +
          (item.suggestion ? '<div class="plans-conflict-solution"><strong>' + escapeHtml(WFT('plans.proposed_solution', 'الحل المقترح:')) + '</strong> ' + escapeHtml(item.suggestion) + '</div>' : '') +
          escapeHtml(item.action || '') + '</td></tr>';
      }).join('');
      const issuePoints = verificationIssues.flatMap(item => {
        const points = Array.isArray(item.points) && item.points.length ? item.points : [item.title || ''];
        return points.filter(Boolean).map(point => (item.title ? item.title + ': ' : '') + point);
      });
      const issuesHtml = issuePoints.length
        ? '<div class="plans-workflow-review"><h5>' + escapeHtml(WFT('plans.verification_issues_title', 'ملاحظات التحقق')) +
          '</h5><ul class="plans-issue-list">' +
          issuePoints.map(point => '<li>' + escapeHtml(point) + '</li>').join('') + '</ul></div>'
        : '';
      const verificationMessage = conflicts.length
        ? WFT('plans.conflicts_count', 'عدد التعارضات المباشرة: ') + conflicts.length
        : (checkFindings.length || verificationIssues.length
          ? WFT('plans.verification_review_needed', 'لا توجد تعارضات مباشرة. توجد نتائج تحتاج مراجعة.')
          : (hasVerificationResult ? WFT('plans.no_conflicts', 'لا توجد تعارضات مباشرة.')
            : WFT('plans.verification_not_run', 'لم يتم فحص التعارضات بعد.')));
      const verificationMessageClass = conflicts.length || checkFindings.length || verificationIssues.length || !hasVerificationResult
        ? 'tenant-hint' : 'plans-workflow-success';
      const otherPlans = VISUAL_CONCEPT_PLAN_KINDS.filter(item => item.kind !== 'site');
      const otherHasImage = otherPlans.some(item => tenantVisualConceptState.slots[item.id]?.imageUrl);
      const sitePlanCard = renderVisualConceptSitePlanCard();
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
        '<p class="' + verificationMessageClass + '" data-plans-verification-summary>' + escapeHtml(verificationMessage) + '</p>' +
        issuesHtml +
        (checkFindings.length ? '<div class="plans-workflow-table-wrap"><table class="plans-workflow-table plans-check-table"><thead><tr><th>البند</th><th>بيانات المشروع</th><th>البيانات الموثقة</th><th>النتيجة</th><th>المشاكل والإجراء</th></tr></thead><tbody>' + checkRows + '</tbody></table></div>' : '') +
        '<div class="visual-concept-actions"><button type="button" class="btn primary small" data-plans-workflow-action="approve-verification" ' + (!canApprove ? 'disabled' : '') + '>اعتماد نتيجة التحقق</button></div>' +
        '</section>' +
        '<section class="plans-workflow-panel plans-workflow-distribution-panel" data-plans-workflow-stage="boundary"' + (activeStage !== 'boundary' ? ' hidden' : '') + '>' +
        '<div data-plans-distribution-chat>' + visualConceptDistributionChatHtml() + '</div>' +
        '<div data-plans-distribution-editor>' + visualConceptDistributionEditorHtml(distribution) + '</div>' +
        '<div data-plans-distribution-results>' + visualConceptDistributionResultsHtml(distribution) + '</div>' +
        '<div class="plans-workflow-panel-head"><h4>' + escapeHtml(WFT('plans.notes_title', 'ملاحظات توليد المخططات')) + '</h4><span class="tenant-hint">' + escapeHtml(WFT('plans.notes_optional', 'اختياري')) + '</span></div>' +
        '<textarea id="visualConceptPlanClientNotes" data-plans-client-notes rows="4" maxlength="1000000">' + escapeHtml(workflow.clientNotes) + '</textarea>' +
        '<div data-plans-notes-results>' + visualConceptPlanNotesResultsHtml(workflow) + '</div>' +
        '<div class="visual-concept-actions"><button type="button" class="btn ghost small" data-plans-workflow-action="check-notes" ' + (!workflow.clientNotes.trim() ? 'disabled' : '') + '>' + escapeHtml(WFT('plans.notes_check', 'فحص الملاحظات')) + '</button></div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="generate"' + (activeStage !== 'generate' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>' + escapeHtml(WFT('plans.stage_site_title', 'المخطط العام المبسط بصيغة SVG')) + '</h4></div>' +
        '<div data-plans-workflow-prompts>' + sitePlanCard + '</div>' +
        '</section>' +
        '<section class="plans-workflow-panel" data-plans-workflow-stage="other"' + (activeStage !== 'other' ? ' hidden' : '') + '>' +
        '<div class="plans-workflow-panel-head"><h4>' + escapeHtml(WFT('plans.stage_other_title', 'مخططا الاستخدامات والكتلة')) + '</h4>' + (promptReady ? '<button type="button" class="btn ghost small" data-plans-workflow-action="prepare-prompts">' + escapeHtml(WFT('plans.stage_other_refresh', 'إعادة تجهيز المخططات')) + '</button>' : '<button type="button" class="btn primary small" data-plans-workflow-action="prepare-prompts">' + escapeHtml(WFT('plans.stage_other_prepare', 'تجهيز المخططات')) + '</button>') + '</div>' +
        '<p class="tenant-hint">' + escapeHtml(promptReady ? WFT('plans.stage_other_ready', 'مخططا الاستخدامات والكتلة جاهزان للتوليد.') : (workflow.promptsError ? WFT('plans.stage_other_error', 'تعذر تجهيز المخططات: {error}', { error: workflow.promptsError }) : WFT('plans.stage_other_not_ready', 'مخططا الاستخدامات والكتلة غير جاهزين للتوليد.'))) + '</p>' +
        '<div data-plans-workflow-prompts>' + otherPlanCards + '</div>' +
        '</section>' +
        '</div>';
      const siteMessages = root.querySelector('.visual-plan-site-messages');
      if (siteMessages) siteMessages.scrollTop = siteMessages.scrollHeight;
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
            invalidateVisualConceptDistributionReview(state);
            invalidateVisualConceptPlanGeneration(state);
            markVisualConceptDirty();
            renderVisualConceptPage();
            scheduleVisualConceptDistributionCheck();
            return;
          }
          const actionBtn = event.target.closest('[data-plans-workflow-action]');
          const choiceBtn = event.target.closest('[data-plans-distribution-chat-choice]');
          if (choiceBtn && !choiceBtn.disabled) {
            submitVisualConceptDistributionChatChoice(
              choiceBtn.getAttribute('data-plans-distribution-chat-choice'));
            return;
          }
          if (!actionBtn || actionBtn.disabled) return;
          const action = actionBtn.getAttribute('data-plans-workflow-action');
          const state = visualConceptPlansWorkflowState();
          if (action === 'verify') verifyVisualConceptPlans();
          else if (action === 'approve-verification') approveVisualConceptPlansVerification();
          else if (action === 'distribution-chat-start') startVisualConceptDistributionChat();
          else if (action === 'distribution-chat-apply') applyVisualConceptDistributionChat();
          else if (action === 'distribution-chat-restart') restartVisualConceptDistributionChat();
          else if (action === 'distribution-chat-send') submitVisualConceptDistributionChat();
          else if (action === 'check-notes') checkVisualConceptPlanNotes();
          else if (action === 'add-distribution-row') {
            const building = actionBtn.getAttribute('data-dist-building') || '';
            addVisualConceptDistributionRow(building);
          }
          else if (action === 'approve-distribution') approveVisualConceptPlansDistribution();
          else if (action === 'prepare-prompts') prepareVisualConceptPlansPrompts();
        });
        root.addEventListener('input', event => {
          const distFieldInput = event.target.closest('[data-dist-field]');
          if (distFieldInput) {
            const state = visualConceptPlansWorkflowState();
            const id = distFieldInput.getAttribute('data-dist-id');
            const field = distFieldInput.getAttribute('data-dist-field');
            const row = (state.distribution.rows || []).find(item => item.id === id);
            if (row) {
              row[field] = distFieldInput.value;
              markVisualConceptDirty();
            }
            return;
          }
          const chatInput = event.target.closest('[data-plans-distribution-chat-input]');
          if (chatInput) return;
          const input = event.target.closest('[data-plans-client-notes]');
          if (!input) return;
          setVisualConceptPlanNotes(input.value);
          const state = visualConceptPlansWorkflowState();
          const notesHost = root.querySelector('[data-plans-notes-results]');
          if (notesHost) notesHost.innerHTML = visualConceptPlanNotesResultsHtml(state);
          const check = root.querySelector('[data-plans-workflow-action="check-notes"]');
          if (check) check.disabled = !state.clientNotes.trim();
        });
        root.addEventListener('keydown', event => {
          const chatInput = event.target.closest('[data-plans-distribution-chat-input]');
          if (!chatInput) return;
          if (event.key !== 'Enter' || event.shiftKey) return;
          event.preventDefault();
          submitVisualConceptDistributionChat();
        });
        root.addEventListener('change', event => {
          const input = event.target.closest('[data-dist-field]');
          if (!input) return;
          const state = visualConceptPlansWorkflowState();
          const id = input.getAttribute('data-dist-id');
          const field = input.getAttribute('data-dist-field');
          const row = (state.distribution.rows || []).find(item => item.id === id);
          if (!row) return;
          const prevBuilding = String(row.building || '').trim();
          row[field] = input.value;
          invalidateVisualConceptDistributionReview(state);
          invalidateVisualConceptPlanGeneration(state);
          markVisualConceptDirty();
          scheduleVisualConceptDistributionCheck();
          if (field === 'building' && prevBuilding !== String(input.value || '').trim()) {
            renderVisualConceptPage();
          }
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
