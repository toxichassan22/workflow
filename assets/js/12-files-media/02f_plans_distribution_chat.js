/* 12-files-media/02f_plans_distribution_chat.js — the conversation that owns the
 * floor distribution. One thread proposes the table, explains it, edits it and
 * checks it; the table below stays editable by hand. The whole thread travels
 * with every request and the server folds the older turns into a memory digest,
 * so the answer builds on what was agreed instead of contradicting it. */

    let visualConceptDistributionChatBusy = false;

    function visualConceptDistributionChatState() {
      const workflow = visualConceptPlansWorkflowState();
      return normalizePlansChatState(workflow.distributionChat);
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
      const start = (!turns.length && !rows.length)
        ? '<div class="visual-concept-actions"><button type="button" class="btn primary small" '
          + 'data-plans-workflow-action="distribution-chat-start">'
          + escapeHtml(WFT('plans.distribution_chat_start', 'ابدأ باقتراح التوزيع')) + '</button></div>' : '';
      const typing = visualConceptDistributionChatBusy
        ? '<div class="plans-distribution-chat-msg assistant typing">'
          + escapeHtml(WFT('plans.distribution_chat_typing', 'يكتب…')) + '</div>' : '';
      return '<div class="plans-distribution-chat">'
        + '<div class="plans-workflow-panel-head"><h4>'
        + escapeHtml(WFT('plans.distribution_chat_title', 'مناقشة توزيع المكونات')) + '</h4></div>'
        + '<div class="plans-distribution-chat-messages" role="log" aria-live="polite">'
        + empty + messages + typing + '</div>'
        + start
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

    async function sendVisualConceptDistributionChat(message) {
      const text = String(message || '').trim();
      if (!text || visualConceptDistributionChatBusy) return;
      if (!hasPermission('generate_images')) {
        toast(WFT('plans.permission', 'لا تملك صلاحية توليد المخططات'));
        return;
      }
      const workflow = visualConceptPlansWorkflowState();
      const chat = visualConceptDistributionChatState();
      const turns = chat.turns.slice();
      turns.push({ role: 'user', text });
      visualConceptDistributionChatBusy = true;
      workflow.distributionChat = { ...chat, turns };
      markVisualConceptDirty();
      renderVisualConceptPage();
      showLoader(WFT('plans.distribution_chat_loading', 'جاري تنفيذ الطلب على التوزيع'),
        WFT('plans.distribution_chat_loading_detail', 'يتم تحديث جدول التوزيع ومراجعته...'), 30);
      let response = null;
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.message = text;
        payload.history = turns.slice(0, -1).map(item => ({
          role: item.role, content: String(item.text || '').slice(0, 4000)
        }));
        payload.memory = chat.memory || '';
        payload.decisions = chat.decisions || [];
        payload.distribution = { rows: (workflow.distribution.rows || []).slice() };
        response = await api('POST', '/api/visual-concept/plans-distribution-chat', payload);
      } catch (error) {
        hideLoader();
        visualConceptDistributionChatBusy = false;
        toast(error.message || WFT('plans.distribution_chat_failed', 'تعذر تنفيذ الطلب على التوزيع.'));
        renderVisualConceptPage();
        return;
      }
      hideLoader();
      visualConceptDistributionChatBusy = false;
      const state = visualConceptPlansWorkflowState();
      const reply = String(response?.reply || '').slice(0, 6000);
      const updated = turns.concat(reply ? [{ role: 'assistant', text: reply }] : []);
      state.distributionChat = {
        turns: updated,
        memory: String(response?.memory || chat.memory || '').slice(0, PLANS_CHAT_MEMORY_MAX_CHARS),
        decisions: Array.isArray(response?.decisions) ? response.decisions : (chat.decisions || [])
      };
      const rows = Array.isArray(response?.rows) ? response.rows : null;
      if (response?.action === 'update' && rows && rows.length) {
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
      if (!reply) toast(WFT('plans.distribution_chat_failed', 'تعذر تنفيذ الطلب على التوزيع.'));
    }

    function startVisualConceptDistributionChat() {
      sendVisualConceptDistributionChat(
        WFT('plans.distribution_chat_start_prompt', 'اقترح توزيع المكونات على المباني والأدوار.'));
    }

    function submitVisualConceptDistributionChat() {
      const text = visualConceptDistributionChatDraft().trim();
      if (!text) return;
      const input = document.querySelector('[data-plans-distribution-chat-input]');
      if (input) input.value = '';
      sendVisualConceptDistributionChat(text);
    }
