/* 12-files-media/02f_plans_distribution_chat.js — the conversation that owns the
 * floor distribution. One thread proposes the table, explains it, edits it and
 * checks it; the table below stays editable by hand. The whole thread travels
 * with every request and the server folds the older turns into a memory digest,
 * so the answer builds on what was agreed instead of contradicting it.
 *
 * A turn is a queued job: the model thinks for minutes at maximum reasoning
 * effort, and the hosting proxy drops a request that stays open that long. The
 * browser polls the job, shows the elapsed time, can stop it, and reports the
 * reason the server gave when the turn fails — never a made-up one. */

    let visualConceptDistributionChatBusy = false;
    const VISUAL_CONCEPT_DISTRIBUTION_CHAT_POLL_MS = 2500;
    const VISUAL_CONCEPT_DISTRIBUTION_CHAT_MAX_SECONDS = 600;

    function visualConceptDistributionChatState() {
      const workflow = visualConceptPlansWorkflowState();
      return normalizePlansChatState(workflow.distributionChat);
    }

    function visualConceptDistributionChatElapsed(seconds) {
      const total = Math.max(0, Math.floor(Number(seconds) || 0));
      const minutes = Math.floor(total / 60);
      const rest = total % 60;
      return minutes + ':' + String(rest).padStart(2, '0');
    }

    // The reason the turn failed, in the words the server used. One message
    // for every failure used to hide the cause: the client said «تعذر تنفيذ
    // الطلب على التوزيع» for a timeout, a dead connection and an unreadable
    // answer alike, and the table simply never changed.
    function visualConceptDistributionChatErrorText(response) {
      const code = String((response && response.error_code) || '');
      if (code === 'PLANS_ANSWER_UNREADABLE') {
        return WFT('plans.distribution_chat_failed_unreadable',
          'ما جا رد مفهوم من النموذج — لم يتغير التوزيع.');
      }
      if (code === 'PLANS_ANSWER_EMPTY') {
        return WFT('plans.distribution_chat_failed_empty',
          'لم يرد النموذج بجواب — لم يتغير التوزيع.');
      }
      if (code === 'PLANS_PROVIDER_TIMEOUT' || code === 'PLANS_JOB_EXPIRED') {
        return WFT('plans.distribution_chat_failed_timeout',
          'انتهت مهلة تنفيذ الطلب على التوزيع.');
      }
      const reason = String((response && response.error) || '').trim();
      if (reason) return reason;
      return WFT('plans.distribution_chat_failed', 'تعذر تنفيذ الطلب على التوزيع.');
    }

    function visualConceptDistributionChatHtml() {
      const workflow = visualConceptPlansWorkflowState();
      const chat = visualConceptDistributionChatState();
      const turns = chat.turns || [];
      const rows = workflow.distribution.rows || [];
      const messages = turns.map(turn => (
        '<div class="plans-distribution-chat-msg ' + (turn.role === 'user' ? 'user' : 'assistant') + '">'
        + escapeHtml(turn.text) + '</div>'
      )).join('');
      const empty = turns.length ? '' : '<p class="plans-workflow-empty">'
        + escapeHtml(WFT('plans.distribution_chat_empty',
          'مساعد توزيع المكونات: يقترح التوزيع، ويجيب عن أسئلتك، ويعدّل الجدول بناءً على كلامك.'))
        + '</p>';
      // Two one-click actions: distribute the floors, or start the whole
      // distribution over instead of continuing on the current one.
      const actions = '<div class="visual-concept-actions plans-distribution-chat-actions">'
        + '<button type="button" class="btn primary small" data-plans-workflow-action="distribution-chat-start"'
        + (visualConceptDistributionChatBusy ? ' disabled' : '') + '>'
        + escapeHtml(WFT('plans.distribution_chat_distribute', 'توزيع الأدوار')) + '</button>'
        + '<button type="button" class="btn ghost small" data-plans-workflow-action="distribution-chat-restart"'
        + (visualConceptDistributionChatBusy || (!rows.length && !turns.length) ? ' disabled' : '') + '>'
        + escapeHtml(WFT('plans.distribution_chat_restart', 'ابدأ من جديد')) + '</button>'
        + '</div>';
      const typing = visualConceptDistributionChatBusy
        ? '<div class="plans-distribution-chat-msg assistant typing">'
          + escapeHtml(WFT('plans.distribution_chat_typing', 'يكتب…')) + '</div>' : '';
      return '<div class="plans-distribution-chat">'
        + '<div class="plans-workflow-panel-head"><h4>'
        + escapeHtml(WFT('plans.distribution_chat_title', 'مناقشة توزيع المكونات')) + '</h4></div>'
        + '<div class="plans-distribution-chat-messages" role="log" aria-live="polite">'
        + empty + messages + typing + '</div>'
        + actions
        + '<div class="plans-distribution-chat-composer">'
        + '<textarea rows="2" maxlength="4000" data-plans-distribution-chat-input data-i18n-ph="plans.distribution_chat_placeholder" placeholder="'
        + escapeHtml(WFT('plans.distribution_chat_placeholder', 'سؤالك أو طلبك عن التوزيع...')) + '"></textarea>'
        + '<button type="button" class="btn primary small" data-plans-workflow-action="distribution-chat-send">'
        + escapeHtml(WFT('plans.distribution_chat_send', 'إرسال')) + '</button>'
        + '</div></div>';
    }

    function visualConceptDistributionChatDraft() {
      const input = document.querySelector('[data-plans-distribution-chat-input]');
      return input ? String(input.value || '') : '';
    }

    // The turn runs off the request path: the answer comes from a job the
    // browser polls, so the hosting edge never sees a request that stays open
    // for minutes.
    async function visualConceptDistributionChatJob(payload) {
      const initial = await api('POST', '/api/visual-concept/plans-distribution-chat', payload);
      if (!initial || initial.success === false) {
        return initial || { success: false, error: '' };
      }
      const jobId = String(initial.jobId || '');
      if (!jobId) return initial;
      if (typeof registerTenantGenerationRun === 'function') registerTenantGenerationRun(jobId);
      const timeoutSeconds = Number(initial.timeoutSeconds);
      const windowSeconds = Number.isFinite(timeoutSeconds) && timeoutSeconds > 0
        ? timeoutSeconds : VISUAL_CONCEPT_DISTRIBUTION_CHAT_MAX_SECONDS;
      const deadline = Date.now() + (windowSeconds + 30) * 1000;
      let job = initial;
      try {
        while (job && (job.status === 'queued' || job.status === 'running')) {
          if (Date.now() >= deadline) break;
          await new Promise(resolve => setTimeout(resolve, VISUAL_CONCEPT_DISTRIBUTION_CHAT_POLL_MS));
          job = await api('GET', '/api/visual-concept/plans-jobs/' + encodeURIComponent(jobId), null);
          if (typeof updateVisualConceptPlanJobUi === 'function') updateVisualConceptPlanJobUi(job);
          if (job && job.error && !job.result) {
            return { success: false, error: job.error, error_code: job.error_code };
          }
        }
      } finally {
        if (typeof releaseTenantGenerationRun === 'function') releaseTenantGenerationRun(jobId);
      }
      if (job && job.result && typeof job.result === 'object') return job.result;
      if (job && job.error) return { success: false, error: job.error, error_code: job.error_code };
      return {
        success: false,
        error_code: 'PLANS_JOB_EXPIRED',
        error: WFT('plans.distribution_chat_failed_timeout', 'انتهت مهلة تنفيذ الطلب على التوزيع.'),
      };
    }

    async function sendVisualConceptDistributionChat(message, options = {}) {
      const text = String(message || '').trim();
      if (!text || visualConceptDistributionChatBusy) return;
      if (!hasPermission('generate_images')) {
        toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات'));
        return;
      }
      const reset = options.reset === true;
      const workflow = visualConceptPlansWorkflowState();
      const chat = visualConceptDistributionChatState();
      const turns = reset
        ? [{ role: 'user', text }]
        : chat.turns.slice().concat([{ role: 'user', text }]);
      visualConceptDistributionChatBusy = true;
      workflow.distributionChat = { ...chat, turns };
      markVisualConceptDirty();
      renderVisualConceptPage();
      const startedAt = Date.now();
      showLoader(WFT('plans.distribution_chat_loading', 'جاري تنفيذ الطلب على التوزيع'),
        WFT('plans.distribution_chat_loading_detail', 'يتم تحديث جدول التوزيع ومراجعته...'), 30,
        { stoppable: true });
      // The bar of a thinking model is not a percentage: the elapsed time is
      // the honest sign that the turn is alive.
      const elapsedTimer = setInterval(() => {
        const elapsed = visualConceptDistributionChatElapsed((Date.now() - startedAt) / 1000);
        if (typeof updateLoaderProgress === 'function') {
          updateLoaderProgress(30, WFT('plans.distribution_chat_elapsed', 'يعمل الآن… {time}', { time: elapsed }));
        }
      }, 1000);
      let response = null;
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.message = text;
        payload.reset = reset;
        payload.history = (reset ? [] : turns.slice(0, -1)).map(item => ({
          role: item.role, content: String(item.text || '').slice(0, 4000)
        }));
        payload.memory = reset ? '' : (chat.memory || '');
        payload.decisions = reset ? [] : (chat.decisions || []);
        payload.distribution = {
          rows: reset ? [] : (workflow.distribution.rows || []).slice()
        };
        response = await visualConceptDistributionChatJob(payload);
      } catch (error) {
        clearInterval(elapsedTimer);
        hideLoader();
        visualConceptDistributionChatBusy = false;
        toast(error?.message || WFT('plans.distribution_chat_failed', 'تعذر تنفيذ الطلب على التوزيع.'));
        renderVisualConceptPage();
        return;
      }
      clearInterval(elapsedTimer);
      hideLoader();
      visualConceptDistributionChatBusy = false;
      if (!response || response.success === false) {
        // The table stays exactly as the client left it: a failed turn never
        // writes a partial proposal.
        toast(visualConceptDistributionChatErrorText(response));
        renderVisualConceptPage();
        return;
      }
      const state = visualConceptPlansWorkflowState();
      const reply = String(response.reply || '').slice(0, 6000);
      const updated = turns.concat(reply ? [{ role: 'assistant', text: reply }] : []);
      state.distributionChat = {
        turns: updated,
        memory: String(response.memory || chat.memory || '').slice(0, PLANS_CHAT_MEMORY_MAX_CHARS),
        decisions: Array.isArray(response.decisions) ? response.decisions : (chat.decisions || [])
      };
      const rows = Array.isArray(response.rows) ? response.rows : null;
      const tableChanged = response.action === 'update' && !!(rows && rows.length);
      if (tableChanged) {
        const stamp = visualConceptPlanInputStamp();
        state.distribution = normalizeVisualConceptPlansWorkflow({
          distribution: {
            rows,
            totals: Array.isArray(response.totals) ? response.totals : [],
            checks: Array.isArray(response.checks) ? response.checks : [],
            issues: Array.isArray(response.issues) ? response.issues : []
          }
        }).distribution;
        state.distribution.aiReviewed = true;
        state.distribution.reviewSignature = stamp;
        state.distribution.canProceed = response.canProceed !== false;
        state.distribution.approved = false;
        invalidateVisualConceptPlanGeneration(state, false);
      }
      markVisualConceptDirty();
      renderVisualConceptPage();
      if (options.expectsTable && !tableChanged) {
        // The turn asked for a layout and the answer carried none: saying
        // nothing would look like a finished distribution that never happened.
        toast(WFT('plans.distribution_chat_table_unchanged',
          'وصل الرد بدون جدول توزيع — لم يتغير توزيع الأدوار.'));
      }
    }

    function startVisualConceptDistributionChat() {
      sendVisualConceptDistributionChat(
        WFT('plans.distribution_chat_start_prompt', 'اقترح توزيع المكونات على المباني والأدوار.'),
        { expectsTable: true });
    }

    // Start the distribution over: the current floors and the thread that
    // agreed on them are dropped, and the model proposes a clean layout from
    // the approved project data.
    async function restartVisualConceptDistributionChat() {
      if (visualConceptDistributionChatBusy) return;
      if (!hasPermission('generate_images')) {
        toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات'));
        return;
      }
      if (typeof confirm !== 'function' || !confirm(WFT('plans.distribution_chat_restart_confirm',
        'سيُمسح توزيع الأدوار الحالي وتبدأ المحادثة من جديد. هل تريد المتابعة؟'))) {
        return false;
      }
      const workflow = visualConceptPlansWorkflowState();
      workflow.distribution = {
        ...workflow.distribution,
        rows: [], totals: [], checks: [], issues: [],
        aiReviewed: false, approved: false, canProceed: false, reviewSignature: '',
      };
      workflow.distributionChat = { turns: [], memory: '', decisions: [] };
      markVisualConceptDirty();
      renderVisualConceptPage();
      await sendVisualConceptDistributionChat(
        WFT('plans.distribution_chat_start_prompt', 'اقترح توزيع المكونات على المباني والأدوار.'),
        { reset: true });
      return true;
    }

    function submitVisualConceptDistributionChat() {
      const text = visualConceptDistributionChatDraft().trim();
      if (!text) return;
      const input = document.querySelector('[data-plans-distribution-chat-input]');
      if (input) input.value = '';
      sendVisualConceptDistributionChat(text);
    }
