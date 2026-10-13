/* 12-files-media/02e_plans_conflict_chat.js — advisory chat pinned inside the
 * plans workflow view. A draggable floating ball opens a panel anchored to it;
 * the server only explains the posted check findings and suggests what to
 * edit — it never writes back into workflow state. The scope follows the
 * visible stage: verification findings on «التحقق», distribution findings on
 * «الحدود والتوزيع». */

    const PLANS_CHAT_POS_KEY = 'plansChatFabPos';
    const PLANS_CHAT_SIZE_KEY = 'plansChatPanelSize';
    const PLANS_CHAT_FAB_SIZE = 56;
    let plansChatBusy = false;

    function plansConflictChatScope() {
      const workflow = tenantVisualConceptState && tenantVisualConceptState.plansWorkflow;
      return (workflow && workflow.viewStage) === 'verify' ? 'verify' : 'distribution';
    }

    function plansConflictChatMessages(scope) {
      const workflow = visualConceptPlansWorkflowState();
      scope = scope === 'verify' ? 'verify' : 'distribution';
      return workflow.conflictChats[scope] || [];
    }

    function plansChatClampFabPosition(left, top) {
      const margin = 8;
      const maxLeft = Math.max(margin, window.innerWidth - PLANS_CHAT_FAB_SIZE - margin);
      const maxTop = Math.max(margin, window.innerHeight - PLANS_CHAT_FAB_SIZE - margin);
      return {
        left: Math.min(Math.max(left, margin), maxLeft),
        top: Math.min(Math.max(top, margin), maxTop)
      };
    }

    function plansChatDefaultFabPosition() {
      const host = document.body || document.documentElement;
      const rtl = getComputedStyle(host).direction === 'rtl';
      return plansChatClampFabPosition(
        rtl ? 18 : window.innerWidth - 18 - PLANS_CHAT_FAB_SIZE,
        window.innerHeight - 18 - PLANS_CHAT_FAB_SIZE);
    }

    function plansChatFabPosition() {
      try {
        const saved = JSON.parse(localStorage.getItem(PLANS_CHAT_POS_KEY) || 'null');
        if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
          return plansChatClampFabPosition(saved.left, saved.top);
        }
      } catch (error) {}
      return plansChatDefaultFabPosition();
    }

    function plansChatApplyFabPosition(pos, persist) {
      const fab = document.getElementById('plansChatFab');
      if (!fab) return;
      const clamped = plansChatClampFabPosition(pos.left, pos.top);
      // inset-inline-end must be cleared BEFORE left/top: in RTL it maps to the
      // physical left edge, and the last declaration wins the edge.
      fab.style.insetInlineEnd = 'auto';
      fab.style.right = 'auto';
      fab.style.bottom = 'auto';
      fab.style.left = clamped.left + 'px';
      fab.style.top = clamped.top + 'px';
      if (persist) {
        try { localStorage.setItem(PLANS_CHAT_POS_KEY, JSON.stringify(clamped)); } catch (error) {}
      }
      const panel = document.getElementById('plansChatPanel');
      if (panel && !panel.hidden) plansChatPositionPanel();
    }

    function plansChatPositionPanel() {
      const panel = document.getElementById('plansChatPanel');
      const fab = document.getElementById('plansChatFab');
      if (!panel || panel.hidden || !fab) return;
      const rect = fab.getBoundingClientRect();
      const width = panel.offsetWidth || Math.min(420, window.innerWidth - 24);
      const height = panel.offsetHeight || Math.min(560, window.innerHeight - 24);
      const gap = 10;
      let top = rect.top - gap - height;
      if (top < 12) top = rect.bottom + gap;
      top = Math.max(12, Math.min(top, window.innerHeight - height - 12));
      const left = Math.max(12, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 12));
      panel.style.insetInlineEnd = 'auto';
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
      panel.style.left = left + 'px';
      panel.style.top = top + 'px';
    }

    function plansChatBindFabDrag(fab) {
      let startX = 0;
      let startY = 0;
      let startLeft = 0;
      let startTop = 0;
      let dragging = false;
      let pointerId = null;
      let suppressClick = false;
      fab.addEventListener('pointerdown', (event) => {
        if (event.button !== undefined && event.button !== 0) return;
        pointerId = event.pointerId;
        startX = event.clientX;
        startY = event.clientY;
        const pos = plansChatFabPosition();
        startLeft = pos.left;
        startTop = pos.top;
        dragging = false;
        try { fab.setPointerCapture(pointerId); } catch (error) {}
        event.preventDefault();
      });
      fab.addEventListener('pointermove', (event) => {
        if (event.pointerId !== pointerId) return;
        const dx = event.clientX - startX;
        const dy = event.clientY - startY;
        if (!dragging && Math.hypot(dx, dy) < 6) return;
        if (!dragging) {
          dragging = true;
          fab.classList.add('dragging');
        }
        plansChatApplyFabPosition({ left: startLeft + dx, top: startTop + dy }, false);
      });
      const finish = (event) => {
        if (event.pointerId !== pointerId) return;
        pointerId = null;
        suppressClick = dragging;
        if (dragging) {
          fab.classList.remove('dragging');
          const pos = plansChatClampFabPosition(
            parseFloat(fab.style.left) || 0,
            parseFloat(fab.style.top) || 0);
          try { localStorage.setItem(PLANS_CHAT_POS_KEY, JSON.stringify(pos)); } catch (error) {}
        }
        dragging = false;
      };
      fab.addEventListener('pointerup', finish);
      fab.addEventListener('pointercancel', finish);
      fab.addEventListener('click', () => {
        if (suppressClick) {
          suppressClick = false;
          return;
        }
        togglePlansChat();
      });
    }

    function plansChatBindResize(panel) {
      const grip = panel.querySelector('#plansChatResize');
      if (!grip) return;
      let startX = 0;
      let startY = 0;
      let startW = 0;
      let startH = 0;
      let startLeft = 0;
      let pointerId = null;
      grip.addEventListener('pointerdown', (event) => {
        if (event.button !== undefined && event.button !== 0) return;
        pointerId = event.pointerId;
        startX = event.clientX;
        startY = event.clientY;
        const rect = panel.getBoundingClientRect();
        startW = rect.width;
        startH = rect.height;
        startLeft = rect.left;
        try { grip.setPointerCapture(pointerId); } catch (error) {}
        event.preventDefault();
        event.stopPropagation();
      });
      grip.addEventListener('pointermove', (event) => {
        if (event.pointerId !== pointerId) return;
        const rtl = getComputedStyle(panel).direction === 'rtl';
        const dx = event.clientX - startX;
        const dy = event.clientY - startY;
        let width = Math.max(300, Math.min(startW + (rtl ? -dx : dx), window.innerWidth - 24));
        const height = Math.max(260, Math.min(startH + dy, window.innerHeight - 24));
        if (rtl) {
          // The grip sits on the left edge — keep the right edge fixed.
          const left = Math.max(8, Math.min(startLeft + dx, window.innerWidth - width - 8));
          panel.style.left = left + 'px';
          width = Math.min(width, window.innerWidth - left - 8);
        } else {
          width = Math.min(width, window.innerWidth - startLeft - 8);
        }
        panel.style.width = width + 'px';
        panel.style.height = height + 'px';
      });
      const finish = (event) => {
        if (event.pointerId !== pointerId) return;
        pointerId = null;
        try {
          const rect = panel.getBoundingClientRect();
          localStorage.setItem(PLANS_CHAT_SIZE_KEY, JSON.stringify({ width: rect.width, height: rect.height }));
        } catch (error) {}
      };
      grip.addEventListener('pointerup', finish);
      grip.addEventListener('pointercancel', finish);
    }

    function mountPlansConflictChat(panelHost) {
      if (!panelHost || document.getElementById('plansChatFab')) return;
      const wrap = document.createElement('div');
      wrap.className = 'land-chat-wrap';
      wrap.innerHTML =
        '<button type="button" class="land-chat-fab" id="plansChatFab" aria-label="شات نتائج فحص المخططات">AI</button>' +
        '<div class="land-chat-panel" id="plansChatPanel" hidden>' +
        '<div class="land-chat-header">' +
        '<div><div class="land-chat-title" id="plansChatTitle"></div>' +
        '<div class="tenant-hint" id="plansChatScope" style="font-size:11px"></div></div>' +
        '<div class="land-chat-actions">' +
        '<button type="button" class="land-chat-action" id="plansChatMinimize" title="إخفاء" aria-label="إخفاء" onclick="togglePlansChat(false)">&gt;&lt;</button>' +
        '<button type="button" class="land-chat-action" id="plansChatEnd" title="إنهاء" aria-label="إنهاء" onclick="showPlansChatEndConfirm()">×</button>' +
        '</div></div>' +
        '<div class="land-chat-messages" id="plansChatMessages"></div>' +
        '<div class="land-chat-input-row">' +
        '<textarea id="plansChatInput" class="land-chat-input" rows="1" maxlength="2000" ' +
        'placeholder="سؤالك عن نتيجة الفحص..." data-i18n-ph="plans.conflict_chat_placeholder" data-section-lock-ignore="1"></textarea>' +
        '<button type="button" class="btn primary land-chat-send" id="plansChatSend" onclick="sendPlansConflictChat()">' +
        escapeHtml(WFT('plans.conflict_chat_send', 'إرسال')) + '</button>' +
        '</div>' +
        '<div class="land-chat-confirm" id="plansChatConfirm" hidden>' +
        '<div class="land-chat-confirm-card">' +
        '<div class="land-chat-confirm-title">هل تريد إنهاء هذه المحادثة؟</div>' +
        '<div class="land-chat-confirm-body">سيبدأ الشات محادثة جديدة عند فتحه مرة أخرى.</div>' +
        '<button type="button" class="land-chat-confirm-end" id="plansChatConfirmEnd" onclick="confirmEndPlansChat()">إنهاء المحادثة</button>' +
        '<button type="button" class="land-chat-confirm-return" id="plansChatConfirmReturn" onclick="hidePlansChatEndConfirm()">العودة إلى المحادثة</button>' +
        '</div></div>' +
        '<div class="land-chat-resize" id="plansChatResize" aria-hidden="true"></div></div>';
      panelHost.appendChild(wrap);
      const fab = wrap.querySelector('#plansChatFab');
      plansChatBindFabDrag(fab);
      plansChatApplyFabPosition(plansChatFabPosition(), false);
      const panel = wrap.querySelector('#plansChatPanel');
      plansChatBindResize(panel);
      try {
        const size = JSON.parse(localStorage.getItem(PLANS_CHAT_SIZE_KEY) || 'null');
        if (size && Number.isFinite(size.width) && Number.isFinite(size.height)) {
          panel.style.width = Math.min(size.width, window.innerWidth - 24) + 'px';
          panel.style.height = Math.min(size.height, window.innerHeight - 24) + 'px';
        }
      } catch (error) {}
      const input = wrap.querySelector('#plansChatInput');
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendPlansConflictChat();
        }
      });
      if (!mountPlansConflictChat.resizeBound) {
        mountPlansConflictChat.resizeBound = true;
        window.addEventListener('resize', () => {
          plansChatApplyFabPosition(plansChatFabPosition(), false);
          plansChatPositionPanel();
        });
      }
      syncPlansConflictChat();
    }

    function togglePlansChat(force) {
      const panel = document.getElementById('plansChatPanel');
      if (!panel) return;
      const open = typeof force === 'boolean' ? force : panel.hidden;
      panel.hidden = !open;
      const fab = document.getElementById('plansChatFab');
      if (fab) fab.classList.toggle('open', open);
      if (open) {
        hidePlansChatEndConfirm();
        syncPlansConflictChat();
        plansChatPositionPanel();
        const input = document.getElementById('plansChatInput');
        if (input) input.focus();
      }
    }

    function showPlansChatEndConfirm() {
      const confirm = document.getElementById('plansChatConfirm');
      if (confirm) confirm.hidden = false;
    }

    function hidePlansChatEndConfirm() {
      const confirm = document.getElementById('plansChatConfirm');
      if (confirm) confirm.hidden = true;
    }

    function confirmEndPlansChat() {
      const workflow = visualConceptPlansWorkflowState();
      workflow.conflictChats[plansConflictChatScope()] = [];
      markVisualConceptDirty();
      renderPlansConflictChatMessages();
      hidePlansChatEndConfirm();
      togglePlansChat(false);
    }

    // Re-syncs the visible scope label and the message thread after every
    // workflow render — the stage may have changed under the open panel.
    function syncPlansConflictChat() {
      const scope = plansConflictChatScope();
      const title = document.getElementById('plansChatTitle');
      if (title) title.textContent = WFT('plans.conflict_chat_title', 'مناقشة نتائج الفحص');
      const scopeTag = document.getElementById('plansChatScope');
      if (scopeTag) {
        scopeTag.textContent = scope === 'verify'
          ? WFT('plans.conflict_chat_scope_verify', 'فحص التعارضات')
          : WFT('plans.conflict_chat_scope_distribution', 'فحص التوزيع');
      }
      renderPlansConflictChatMessages();
    }

    function renderPlansConflictChatMessages() {
      const box = document.getElementById('plansChatMessages');
      if (!box) return;
      box.innerHTML = '';
      const scope = plansConflictChatScope();
      const messages = plansConflictChatMessages(scope);
      if (!messages.length) {
        const empty = document.createElement('div');
        empty.className = 'land-chat-empty';
        empty.textContent = scope === 'verify'
          ? WFT('plans.conflict_chat_empty',
              'شات مخصص لشرح نتائج الفحص — يوضح سبب التعارض ويقترح التعديل دون تغيير أي بيانات.')
          : WFT('plans.dist_chat_empty',
              'شات مخصص لشرح التوزيع المقترح ونتائج فحصه — يوضح سبب التعارض ويقترح التعديل دون تغيير أي بيانات.');
        box.appendChild(empty);
      }
      messages.forEach(msg => {
        const bubble = document.createElement('div');
        bubble.className = 'land-chat-msg ' + (msg.role === 'user' ? 'user' : 'assistant');
        bubble.textContent = msg.text;
        box.appendChild(bubble);
      });
      if (plansChatBusy) {
        const typing = document.createElement('div');
        typing.className = 'land-chat-msg assistant typing';
        typing.textContent = 'يكتب…';
        box.appendChild(typing);
      }
      box.scrollTop = box.scrollHeight;
    }

    async function sendPlansConflictChat() {
      const input = document.getElementById('plansChatInput');
      const question = String(input && input.value || '').trim();
      if (!question || plansChatBusy) return;
      const scope = plansConflictChatScope();
      const messages = plansConflictChatMessages(scope);
      messages.push({ role: 'user', text: question });
      if (input) input.value = '';
      plansChatBusy = true;
      renderPlansConflictChatMessages();
      let reply = WFT('plans.conflict_chat_failed', 'تعذر الحصول على إجابة الآن.');
      try {
        const payload = await collectVisualConceptPlansWorkflowPayload();
        payload.scope = scope;
        payload.question = question;
        // Everything before the just-pushed turn is prior context for the model.
        payload.history = messages.slice(0, -1).slice(-8).map(item => ({
          role: item.role, content: String(item.text || '').slice(0, 2000)
        }));
        const data = await api('POST', '/api/visual-concept/plans-conflict-chat', payload);
        if (data && data.reply) reply = data.reply;
        else if (data && data.error) reply = data.error;
      } catch (error) {}
      const live = plansConflictChatMessages(scope);
      live.push({ role: 'assistant', text: String(reply || '').slice(0, 4000) });
      plansChatBusy = false;
      markVisualConceptDirty();
      renderPlansConflictChatMessages();
    }
