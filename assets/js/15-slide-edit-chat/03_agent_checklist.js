    // ── Designer agent checklist (DESIGNER_AGENT=1) ───────────────────────────
    // The planner returns a pending plan (visible task list) for confirmation;
    // the runner reports per-task status live through the job poll and on the
    // final reply. This module owns the checklist UI under the chat messages.

    let tenantDesignerPendingPlan = null;
    let tenantDesignerRunTasks = null;
    let tenantDesignerCancelling = false;

    function designerAgentText(key, fallback, params) {
      return (typeof WFT === 'function') ? WFT(key, fallback, params) : fallback;
    }

    function designerTaskStatusLabel(status) {
      const labels = {
        pending: designerAgentText('designer_agent.task_pending', 'بانتظار التنفيذ'),
        running: designerAgentText('designer_agent.task_running', 'جارٍ التنفيذ'),
        success: designerAgentText('designer_agent.task_success', 'تمت بنجاح'),
        failed: designerAgentText('designer_agent.task_failed', 'تعذّرت'),
        skipped: designerAgentText('designer_agent.task_skipped', 'تخطّيت'),
      };
      return labels[String(status || 'pending')] || status || '';
    }

    function designerChecklistBox() {
      return document.getElementById('tenantDesignerChecklist');
    }

    // Display order follows the deck, not the execution order: a plan that
    // restyles everything and then splits slides 51/59/70 reads top-to-bottom
    // the way the user sees the presentation. task.n stays the runner's own
    // sequence number so progress messages still match.
    function designerTasksInDeckOrder(tasks) {
      const order = new Map();
      (Array.isArray(tenantSlidesData) ? tenantSlidesData : []).forEach((slide, i) => {
        if (slide && slide.id) order.set(String(slide.id), i);
      });
      const position = task => {
        const ids = Array.isArray(task?.slides) ? task.slides : [];
        const hit = ids.map(id => order.get(String(id))).filter(i => i !== undefined);
        if (hit.length) return Math.min(...hit);
        const after = String(task?.after || '');
        if (after === 'start') return -0.5;
        if (after === 'end' || !after) return Number.MAX_SAFE_INTEGER;
        const at = order.get(after);
        return at === undefined ? Number.MAX_SAFE_INTEGER : at + 0.5;
      };
      return (tasks || []).map((task, i) => ({ task, key: position(task), i }))
        .sort((a, b) => (a.key - b.key) || (a.i - b.i))
        .map(entry => entry.task);
    }

    function designerTaskRowHtml(task) {
      const n = Number(task?.n || 0);
      const label = String(task?.label || task?.op || designerAgentText('designer_agent.task', 'مهمة'));
      const status = String(task?.status || 'pending');
      const titles = Array.isArray(task?.titles) ? task.titles.filter(Boolean) : [];
      const target = titles.length ? ' — ' + titles.slice(0, 3).map(t => escapeHtml(String(t).slice(0, 40))).join('، ') : '';
      const reason = status === 'failed' && task?.failureReason
        ? '<div class="tenant-designer-task-reason">' + escapeHtml(String(task.failureReason).slice(0, 140)) + '</div>'
        : '';
      // What actually changed on each slide — the finish payload carries these
      // so a completed task reads as «done + what it did», not just «done».
      const changes = Array.isArray(task?.changes) && task.changes.length
        ? '<div class="tenant-designer-task-changes">' + task.changes
            .map(item => escapeHtml(String(item).slice(0, 80))).join(' • ') + '</div>'
        : '';
      // Applied-with-caveat findings — the slide did apply; these name what the
      // result dropped so the client can undo or ask for a fix.
      const warnings = Array.isArray(task?.warnings) && task.warnings.length
        ? '<div class="tenant-designer-task-warnings">' + task.warnings
            .map(item => escapeHtml(String(item).slice(0, 140))).join(' • ') + '</div>'
        : '';
      return '<div class="tenant-designer-task is-' + escapeHtml(status) + '">' +
        '<div class="tenant-designer-task-head">' +
        '<span class="tenant-designer-task-n">' + n + '</span>' +
        '<span class="tenant-designer-task-label">' + escapeHtml(label) + target + '</span>' +
        '<span class="tenant-designer-task-status">' + designerTaskStatusLabel(status) + '</span>' +
        '</div>' + reason + changes + warnings + '</div>';
    }

    function renderDesignerChecklist(liveTasks = null) {
      const box = designerChecklistBox();
      if (!box) return;
      if (liveTasks && Array.isArray(liveTasks) && liveTasks.length) {
        tenantDesignerRunTasks = liveTasks;
      }
      const tasks = tenantDesignerPendingPlan?.tasks || tenantDesignerRunTasks;
      if (!Array.isArray(tasks) || !tasks.length) {
        box.hidden = true;
        box.innerHTML = '';
        return;
      }
      const pending = !!tenantDesignerPendingPlan;
      const running = !!tenantDesignerChatBusy;
      const failedCount = tasks.filter(t => ['failed', 'skipped'].includes(String(t?.status))).length;
      const rows = designerTasksInDeckOrder(tasks).map(designerTaskRowHtml).join('');
      let actions = '';
      if (pending) {
        actions = '<div class="tenant-designer-checklist-actions">' +
          '<button type="button" class="btn primary tenant-designer-confirm" onclick="confirmDesignerPlan()">' +
          designerAgentText('designer_agent.run_plan', 'تنفيذ الخطة') + '</button>' +
          '<button type="button" class="btn ghost tenant-designer-cancel" onclick="cancelDesignerPlan()">' +
          designerAgentText('designer_agent.cancel', 'إلغاء') + '</button>' +
          '</div>';
      } else if (running) {
        actions = '<div class="tenant-designer-checklist-actions">' +
          '<button type="button" class="btn ghost tenant-designer-cancel" onclick="cancelDesignerJob()"' +
          (tenantDesignerCancelling ? ' disabled' : '') + '>' +
          designerAgentText(tenantDesignerCancelling ? 'designer_agent.cancelling' : 'designer_agent.stop_run',
                            tenantDesignerCancelling ? 'جاري إيقاف التنفيذ...' : 'إيقاف التنفيذ') +
          '</button></div>';
      } else if (failedCount) {
        actions = '<div class="tenant-designer-checklist-actions">' +
          '<button type="button" class="btn ghost tenant-designer-retry" onclick="retryDesignerTasks()">' +
          designerAgentText('designer_agent.retry_failed', 'إعادة المهام المتعثرة ({n})', { n: failedCount }) + '</button>' +
          '</div>';
      }
      // The rows scroll inside their own track so a long plan never pushes the
      // confirm/cancel buttons below the fold — actions must stay reachable.
      box.innerHTML = '<div class="tenant-designer-checklist-card">' +
        '<div class="tenant-designer-checklist-title">' +
        (pending ? designerAgentText('designer_agent.pending_plan', 'خطة التنفيذ المقترحة')
                 : designerAgentText('designer_agent.run_tasks', 'مهام التنفيذ')) +
        '</div><div class="tenant-designer-checklist-rows">' + rows +
        '</div>' + actions + '</div>';
      box.hidden = false;
    }

    function clearDesignerChecklist() {
      tenantDesignerPendingPlan = null;
      tenantDesignerRunTasks = null;
      tenantDesignerCancelling = false;
      renderDesignerChecklist();
      if (typeof clearDesignerSlideActivity === 'function') clearDesignerSlideActivity();
    }

    // A fresh user message always starts a new turn: any stale checklist or
    // pending plan belongs to the previous turn and must not linger.
    function resetDesignerChecklistForNewTurn() {
      tenantDesignerPendingPlan = null;
      tenantDesignerRunTasks = null;
      tenantDesignerCancelling = false;
      renderDesignerChecklist();
      if (typeof clearDesignerSlideActivity === 'function') clearDesignerSlideActivity();
    }

    function applyDesignerPlanPending(reply) {
      if (!reply || !reply.pendingPlan || typeof reply.pendingPlan !== 'object') return;
      tenantDesignerPendingPlan = {
        id: String(reply.pendingPlan.id || ''),
        deckSignature: String(reply.pendingPlan.deckSignature || ''),
        style_brief: String(reply.pendingPlan.style_brief || ''),
        ops: Array.isArray(reply.pendingPlan.ops) ? reply.pendingPlan.ops : [],
        tasks: Array.isArray(reply.pendingPlan.tasks) ? reply.pendingPlan.tasks : []
      };
      tenantDesignerRunTasks = tenantDesignerPendingPlan.tasks;
      // plan_pending carries the id-annotated deck so the confirm echoes the
      // same ids back. Merge ids positionally — content is untouched.
      if (Array.isArray(reply.slidesData) && reply.slidesData.length === tenantSlidesData.length) {
        tenantSlidesData = tenantSlidesData.map((slide, i) => ({
          ...slide, id: slide.id || reply.slidesData[i]?.id
        }));
        tenantProjectData.tenantSlidesData = tenantSlidesData;
      }
      renderDesignerChecklist();
      // The plan footprint is knowable before it runs — mark its slides so the
      // deck previews what «تنفيذ الخطة» will touch.
      if (typeof updateDesignerSlideActivity === 'function') {
        updateDesignerSlideActivity(tenantDesignerPendingPlan.tasks);
      }
    }

    function applyDesignerRunTasks(reply) {
      if (!reply || !Array.isArray(reply.tasks) || !reply.tasks.length) return;
      tenantDesignerPendingPlan = null;
      tenantDesignerRunTasks = reply.tasks;
      renderDesignerChecklist();
    }

    function designerAgentBasePayload(message) {
      const targetScope = tenantChatSlideScope === 'all' ? 'all' : 'auto';
      const payload = {
        message,
        target: targetScope,
        scope: targetScope,
        indexes: [],
        history: tenantDesignerMessages.slice(-DESIGNER_CHAT_HISTORY_KEPT).map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content || '').slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })),
        memory: tenantDesignerChatMemory,
        focusIndexes: tenantChatFocusIndexes,
        slideIndex: tenantChatSlideIndex,
        presentationId: tenantPresentationId,
        projectData: buildDesignerChatProjectData(tenantProjectData),
        creativeImages: buildPresentationGenerationImages()
      };
      ensureSlideIds(tenantSlidesData);
      payload.slideHtml = tenantSlidesData[tenantChatSlideIndex]?.html || '';
      payload.slideTitle = tenantSlidesData[tenantChatSlideIndex]?.title || '';
      payload.slidesData = tenantSlidesData;
      payload.slidePlan = tenantSlidePlan;
      return payload;
    }

    async function sendDesignerAgentRequest(payload, busyText) {
      const workspaceKey = designerChatWorkspaceKey();
      setDesignerChatBusy(busyText || designerAgentText('designer_agent.busy_run', 'جاري تنفيذ مهام التصميم...'), workspaceKey);
      const indicator = document.getElementById('tenantChatTypingIndicator');
      restoreDesignerChatBusyIndicator();
      let data = null;
      try {
        data = await requestTenantDesignerChat(payload, indicator);
      } catch (error) {
        data = { success: false, status: 'waiting', error: error?.message || designerAgentText('designer_agent.run_failed', 'تعذر تنفيذ الطلب.') };
      } finally {
        clearDesignerChatBusy(workspaceKey);
      }
      const job = data?._designerJob || null;
      if (job && !tenantDesignerJobMatchesWorkspace(job)) return;
      if (job && !tenantDesignerJobCanApply(job)) {
        applyTenantDesignerChatResult({
          success: false, status: 'failed',
          error: designerAgentText('designer_agent.deck_changed', 'لم تُطبق النتيجة لأن العرض تغير أثناء تنفيذ المهمة.')
        }, payload.message || '');
        clearTenantDesignerJob(job);
        return;
      }
      applyTenantDesignerChatResult(data, payload.message || '');
      if (job && isTerminalDesignerChatJob(data)) clearTenantDesignerJob(job);
    }

    async function confirmDesignerPlan() {
      const plan = tenantDesignerPendingPlan;
      if (!plan) return;
      if (tenantDesignerChatBusy || currentTenantDesignerJob()) return;
      tenantDesignerPendingPlan = null;
      // Queued slides lock at confirm — the first poll would only repaint the
      // same marks a beat later.
      if (typeof applyDesignerSlideActivity === 'function') applyDesignerSlideActivity();
      const payload = designerAgentBasePayload(designerAgentText('designer_agent.confirm_message', 'نفّذ الخطة المعروضة'));
      payload.confirmPlan = {
        id: plan.id, deckSignature: plan.deckSignature,
        style_brief: plan.style_brief, ops: plan.ops
      };
      await sendDesignerAgentRequest(payload, designerAgentText('designer_agent.busy_confirm', 'جاري تنفيذ الخطة المؤكدة...'));
    }

    function cancelDesignerPlan() {
      if (!tenantDesignerPendingPlan) return;
      tenantDesignerPendingPlan = null;
      tenantDesignerRunTasks = null;
      tenantDesignerMessages.push({
        role: 'assistant',
        content: designerAgentText('designer_agent.plan_cancelled', 'أُلغيت الخطة — لم يتغير العرض.'),
        slides: tenantChatFocusIndexes.slice()
      });
      tenantProjectData.designerChat = designerChatPersistence();
      renderDesignerChecklist();
      if (typeof clearDesignerSlideActivity === 'function') clearDesignerSlideActivity();
      renderTenantDesignerChat();
      triggerAutoSaveDraft();
    }

    async function retryDesignerTasks() {
      const tasks = Array.isArray(tenantDesignerRunTasks) ? tenantDesignerRunTasks : [];
      const retry = tasks
        .filter(t => ['failed', 'skipped'].includes(String(t?.status)) && t?.op)
        .map(t => ({ ...t, status: 'pending', failureReason: undefined }));
      if (!retry.length) return;
      if (tenantDesignerChatBusy || currentTenantDesignerJob()) return;
      const payload = designerAgentBasePayload(designerAgentText('designer_agent.retry_message', 'أعد تنفيذ المهام المتعثرة'));
      payload.retryTasks = retry;
      await sendDesignerAgentRequest(payload, designerAgentText('designer_agent.busy_retry', 'جاري إعادة المهام المتعثرة...'));
    }

    async function cancelDesignerJob() {
      const job = currentTenantDesignerJob();
      if (!job || !job.jobId || tenantDesignerCancelling) return;
      // Flag the local record first — the poll loop releases the UI at once,
      // even if the server job has not been claimed yet (a pre-registration
      // click would otherwise 404 the cancel and then resubmit the request).
      job.cancelRequested = true;
      job.updatedAt = Date.now();
      persistTenantDesignerJob(job);
      tenantDesignerCancelling = true;
      updateDesignerChatBusy(tenantDesignerChatBusy?.progress || 5,
        designerAgentText('designer_agent.cancelling', 'جاري إيقاف التنفيذ...'));
      renderDesignerChecklist();
      const cancelPath = '/api/designer-chat/jobs/' + encodeURIComponent(String(job.jobId)) + '/cancel';
      try {
        await apiWithTimeout('POST', cancelPath, null, 15000,
          designerAgentText('designer_agent.stop_send_failed', 'تعذر إرسال طلب الإيقاف.'));
      } catch (error) {
        // The job file may land a beat after the local claim — one silent
        // retry covers the race; a real failure surfaces on the next attempt.
        setTimeout(() => {
          apiWithTimeout('POST', cancelPath, null, 15000,
            designerAgentText('designer_agent.stop_send_failed', 'تعذر إرسال طلب الإيقاف.'))
            .catch(() => {});
        }, 1500);
      }
    }
