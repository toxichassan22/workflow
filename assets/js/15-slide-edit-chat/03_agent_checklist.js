    // ── Designer agent checklist (DESIGNER_AGENT=1) ───────────────────────────
    // The planner returns a pending plan (visible task list) for confirmation;
    // the runner reports per-task status live through the job poll and on the
    // final reply. This module owns the checklist UI under the chat messages.

    let tenantDesignerPendingPlan = null;
    let tenantDesignerRunTasks = null;

    const DESIGNER_TASK_STATUS_LABELS = {
      pending: 'بانتظار التنفيذ',
      running: 'جارٍ التنفيذ',
      success: 'تمت بنجاح',
      failed: 'تعذّرت',
      skipped: 'تخطّيت',
    };

    function designerTaskStatusLabel(status) {
      return DESIGNER_TASK_STATUS_LABELS[String(status || 'pending')] || status || '';
    }

    function designerChecklistBox() {
      return document.getElementById('tenantDesignerChecklist');
    }

    function designerTaskRowHtml(task) {
      const n = Number(task?.n || 0);
      const label = String(task?.label || task?.op || 'مهمة');
      const status = String(task?.status || 'pending');
      const titles = Array.isArray(task?.titles) ? task.titles.filter(Boolean) : [];
      const target = titles.length ? ' — ' + titles.slice(0, 3).map(t => escapeHtml(String(t).slice(0, 40))).join('، ') : '';
      const reason = status === 'failed' && task?.failureReason
        ? '<div class="tenant-designer-task-reason">' + escapeHtml(String(task.failureReason).slice(0, 140)) + '</div>'
        : '';
      return '<div class="tenant-designer-task is-' + escapeHtml(status) + '">' +
        '<div class="tenant-designer-task-head">' +
        '<span class="tenant-designer-task-n">' + n + '</span>' +
        '<span class="tenant-designer-task-label">' + escapeHtml(label) + target + '</span>' +
        '<span class="tenant-designer-task-status">' + designerTaskStatusLabel(status) + '</span>' +
        '</div>' + reason + '</div>';
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
      const rows = tasks.map(designerTaskRowHtml).join('');
      let actions = '';
      if (pending) {
        actions = '<div class="tenant-designer-checklist-actions">' +
          '<button type="button" class="btn primary tenant-designer-confirm" onclick="confirmDesignerPlan()">تنفيذ الخطة</button>' +
          '<button type="button" class="btn ghost tenant-designer-cancel" onclick="cancelDesignerPlan()">إلغاء</button>' +
          '</div>';
      } else if (running) {
        actions = '<div class="tenant-designer-checklist-actions">' +
          '<button type="button" class="btn ghost tenant-designer-cancel" onclick="cancelDesignerJob()">إيقاف التنفيذ</button>' +
          '</div>';
      } else if (failedCount) {
        actions = '<div class="tenant-designer-checklist-actions">' +
          '<button type="button" class="btn ghost tenant-designer-retry" onclick="retryDesignerTasks()">إعادة المهام المتعثرة (' + failedCount + ')</button>' +
          '</div>';
      }
      box.innerHTML = '<div class="tenant-designer-checklist-card">' +
        '<div class="tenant-designer-checklist-title">' +
        (pending ? 'خطة التنفيذ المقترحة' : 'مهام التنفيذ') + '</div>' + rows + actions + '</div>';
      box.hidden = false;
    }

    function clearDesignerChecklist() {
      tenantDesignerPendingPlan = null;
      tenantDesignerRunTasks = null;
      renderDesignerChecklist();
    }

    // A fresh user message always starts a new turn: any stale checklist or
    // pending plan belongs to the previous turn and must not linger.
    function resetDesignerChecklistForNewTurn() {
      tenantDesignerPendingPlan = null;
      tenantDesignerRunTasks = null;
      renderDesignerChecklist();
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
      setDesignerChatBusy(busyText || 'جاري تنفيذ مهام التصميم...', workspaceKey);
      const indicator = document.getElementById('tenantChatTypingIndicator');
      restoreDesignerChatBusyIndicator();
      let data = null;
      try {
        data = await requestTenantDesignerChat(payload, indicator);
      } catch (error) {
        data = { success: false, status: 'waiting', error: error?.message || 'تعذر تنفيذ الطلب.' };
      } finally {
        clearDesignerChatBusy(workspaceKey);
      }
      const job = data?._designerJob || null;
      if (job && !tenantDesignerJobMatchesWorkspace(job)) return;
      if (job && !tenantDesignerJobCanApply(job)) {
        applyTenantDesignerChatResult({
          success: false, status: 'failed',
          error: 'لم تُطبق النتيجة لأن العرض تغير أثناء تنفيذ المهمة.'
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
      const payload = designerAgentBasePayload('نفّذ الخطة المعروضة');
      payload.confirmPlan = {
        id: plan.id, deckSignature: plan.deckSignature,
        style_brief: plan.style_brief, ops: plan.ops
      };
      await sendDesignerAgentRequest(payload, 'جاري تنفيذ الخطة المؤكدة...');
    }

    function cancelDesignerPlan() {
      if (!tenantDesignerPendingPlan) return;
      tenantDesignerPendingPlan = null;
      tenantDesignerRunTasks = null;
      tenantDesignerMessages.push({
        role: 'assistant',
        content: 'أُلغيت الخطة — لم يتغير العرض.',
        slides: tenantChatFocusIndexes.slice()
      });
      tenantProjectData.designerChat = designerChatPersistence();
      renderDesignerChecklist();
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
      const payload = designerAgentBasePayload('أعد تنفيذ المهام المتعثرة');
      payload.retryTasks = retry;
      await sendDesignerAgentRequest(payload, 'جاري إعادة المهام المتعثرة...');
    }

    async function cancelDesignerJob() {
      const job = currentTenantDesignerJob();
      if (!job || !job.jobId) return;
      try {
        await apiWithTimeout(
          'POST', '/api/designer-chat/jobs/' + encodeURIComponent(String(job.jobId)) + '/cancel',
          null, 15000, 'تعذر إرسال طلب الإيقاف.');
      } catch (error) {
        toast(error?.message || 'تعذر إيقاف المهمة');
      }
    }
