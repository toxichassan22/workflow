/* 11-land-croquis/04_land_chat.js — scoped Q&A chat pinned inside the
 * land/croquis section (temporary feature). A draggable floating ball opens a
 * panel anchored to it; the server answers only from the recorded land data
 * and must state uncertainty instead of guessing. */

    const LAND_CHAT_HISTORY_KEPT = 10;
    const LAND_CHAT_POS_KEY = 'landChatFabPos';
    const LAND_CHAT_SIZE_KEY = 'landChatPanelSize';
    const LAND_CHAT_FAB_SIZE = 56;
    let landChatBusy = false;
    const landChatMessages = [];

    function landChatHistory() {
      return landChatMessages;
    }

    function landChatClampFabPosition(left, top) {
      const margin = 8;
      const maxLeft = Math.max(margin, window.innerWidth - LAND_CHAT_FAB_SIZE - margin);
      const maxTop = Math.max(margin, window.innerHeight - LAND_CHAT_FAB_SIZE - margin);
      return {
        left: Math.min(Math.max(left, margin), maxLeft),
        top: Math.min(Math.max(top, margin), maxTop)
      };
    }

    function landChatDefaultFabPosition() {
      const host = document.body || document.documentElement;
      const rtl = getComputedStyle(host).direction === 'rtl';
      return landChatClampFabPosition(
        rtl ? 18 : window.innerWidth - 18 - LAND_CHAT_FAB_SIZE,
        window.innerHeight - 18 - LAND_CHAT_FAB_SIZE);
    }

    function landChatFabPosition() {
      try {
        const saved = JSON.parse(localStorage.getItem(LAND_CHAT_POS_KEY) || 'null');
        if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
          return landChatClampFabPosition(saved.left, saved.top);
        }
      } catch (error) {}
      return landChatDefaultFabPosition();
    }

    function landChatApplyFabPosition(pos, persist) {
      const fab = document.getElementById('landChatFab');
      if (!fab) return;
      const clamped = landChatClampFabPosition(pos.left, pos.top);
      // inset-inline-end must be cleared BEFORE left/top: in RTL it maps to the
      // physical left edge, and the last declaration wins the edge — so setting
      // it after style.left silently discards the position.
      fab.style.insetInlineEnd = 'auto';
      fab.style.right = 'auto';
      fab.style.bottom = 'auto';
      fab.style.left = clamped.left + 'px';
      fab.style.top = clamped.top + 'px';
      if (persist) {
        try { localStorage.setItem(LAND_CHAT_POS_KEY, JSON.stringify(clamped)); } catch (error) {}
      }
      const panel = document.getElementById('landChatPanel');
      if (panel && !panel.hidden) landChatPositionPanel();
    }

    function landChatPositionPanel() {
      const panel = document.getElementById('landChatPanel');
      const fab = document.getElementById('landChatFab');
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

    function landChatBindFabDrag(fab) {
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
        const pos = landChatFabPosition();
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
        landChatApplyFabPosition({ left: startLeft + dx, top: startTop + dy }, false);
      });
      const finish = (event) => {
        if (event.pointerId !== pointerId) return;
        pointerId = null;
        suppressClick = dragging;
        if (dragging) {
          fab.classList.remove('dragging');
          const pos = landChatClampFabPosition(
            parseFloat(fab.style.left) || 0,
            parseFloat(fab.style.top) || 0);
          try { localStorage.setItem(LAND_CHAT_POS_KEY, JSON.stringify(pos)); } catch (error) {}
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
        toggleLandChat();
      });
    }

    function landChatBindResize(panel) {
      const grip = panel.querySelector('#landChatResize');
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
          localStorage.setItem(LAND_CHAT_SIZE_KEY, JSON.stringify({ width: rect.width, height: rect.height }));
        } catch (error) {}
      };
      grip.addEventListener('pointerup', finish);
      grip.addEventListener('pointercancel', finish);
    }

    function mountLandChat(sectionDiv) {
      if (!sectionDiv || document.getElementById('landChatFab')) return;
      const wrap = document.createElement('div');
      wrap.className = 'land-chat-wrap';
      wrap.innerHTML =
        '<button type="button" class="land-chat-fab" id="landChatFab" aria-label="شات الأرض والكروكي">AI</button>' +
        '<div class="land-chat-panel" id="landChatPanel" hidden>' +
        '<div class="land-chat-header">' +
        '<div class="land-chat-title">شات الأرض والكروكي</div>' +
        '<div class="land-chat-actions">' +
        '<button type="button" class="land-chat-action" id="landChatMinimize" title="إخفاء" aria-label="إخفاء" onclick="toggleLandChat(false)">&gt;&lt;</button>' +
        '<button type="button" class="land-chat-action" id="landChatEnd" title="إنهاء" aria-label="إنهاء" onclick="showLandChatEndConfirm()">×</button>' +
        '</div></div>' +
        '<div class="land-chat-messages" id="landChatMessages"></div>' +
        '<div class="land-chat-input-row">' +
        '<textarea id="landChatInput" class="land-chat-input" rows="1" ' +
        'placeholder="اسأل عن بيانات الأرض والكروكي..." data-i18n-ph="land_chat.placeholder" data-section-lock-ignore="1"></textarea>' +
        '<button type="button" class="btn primary land-chat-send" id="landChatSend" onclick="sendLandChat()">إرسال</button>' +
        '</div>' +
        '<div class="land-chat-confirm" id="landChatConfirm" hidden>' +
        '<div class="land-chat-confirm-card">' +
        '<div class="land-chat-confirm-title">هل تريد إنهاء هذه المحادثة؟</div>' +
        '<div class="land-chat-confirm-body">سيبدأ الشات محادثة جديدة عند فتحه مرة أخرى.</div>' +
        '<button type="button" class="land-chat-confirm-end" id="landChatConfirmEnd" onclick="confirmEndLandChat()">إنهاء المحادثة</button>' +
        '<button type="button" class="land-chat-confirm-return" id="landChatConfirmReturn" onclick="hideLandChatEndConfirm()">العودة إلى المحادثة</button>' +
        '</div></div>' +
        '<div class="land-chat-resize" id="landChatResize" aria-hidden="true"></div></div>';
      sectionDiv.appendChild(wrap);
      const fab = wrap.querySelector('#landChatFab');
      landChatBindFabDrag(fab);
      landChatApplyFabPosition(landChatFabPosition(), false);
      const panel = wrap.querySelector('#landChatPanel');
      landChatBindResize(panel);
      try {
        const size = JSON.parse(localStorage.getItem(LAND_CHAT_SIZE_KEY) || 'null');
        if (size && Number.isFinite(size.width) && Number.isFinite(size.height)) {
          panel.style.width = Math.min(size.width, window.innerWidth - 24) + 'px';
          panel.style.height = Math.min(size.height, window.innerHeight - 24) + 'px';
        }
      } catch (error) {}
      const input = wrap.querySelector('#landChatInput');
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendLandChat();
        }
      });
      if (!mountLandChat.resizeBound) {
        mountLandChat.resizeBound = true;
        window.addEventListener('resize', () => {
          landChatApplyFabPosition(landChatFabPosition(), false);
          landChatPositionPanel();
        });
      }
      renderLandChatMessages();
    }

    function toggleLandChat(force) {
      const panel = document.getElementById('landChatPanel');
      if (!panel) return;
      const open = typeof force === 'boolean' ? force : panel.hidden;
      panel.hidden = !open;
      const fab = document.getElementById('landChatFab');
      if (fab) fab.classList.toggle('open', open);
      if (open) {
        hideLandChatEndConfirm();
        landChatPositionPanel();
        const input = document.getElementById('landChatInput');
        if (input) input.focus();
      }
    }

    function showLandChatEndConfirm() {
      const confirm = document.getElementById('landChatConfirm');
      if (confirm) confirm.hidden = false;
    }

    function hideLandChatEndConfirm() {
      const confirm = document.getElementById('landChatConfirm');
      if (confirm) confirm.hidden = true;
    }

    function confirmEndLandChat() {
      landChatMessages.length = 0;
      renderLandChatMessages();
      hideLandChatEndConfirm();
      toggleLandChat(false);
    }

    function renderLandChatMessages() {
      const box = document.getElementById('landChatMessages');
      if (!box) return;
      box.innerHTML = '';
      const messages = landChatHistory();
      if (!messages.length) {
        const empty = document.createElement('div');
        empty.className = 'land-chat-empty';
        empty.textContent = 'شات مخصص لبيانات الأرض والكروكي — يغطي معاملات البناء والأدوار المسموحة والارتدادات والإحداثيات والتوزيعات والاشتراطات الموثقة.';
        box.appendChild(empty);
      }
      messages.forEach(msg => {
        const bubble = document.createElement('div');
        bubble.className = 'land-chat-msg ' + (msg.role === 'user' ? 'user' : 'assistant');
        bubble.textContent = msg.content;
        box.appendChild(bubble);
      });
      if (landChatBusy) {
        const typing = document.createElement('div');
        typing.className = 'land-chat-msg assistant typing';
        typing.textContent = 'يكتب…';
        box.appendChild(typing);
      }
      box.scrollTop = box.scrollHeight;
    }

    async function sendLandChat() {
      const input = document.getElementById('landChatInput');
      const message = String(input && input.value || '').trim();
      if (!message || landChatBusy) return;
      const messages = landChatHistory();
      messages.push({ role: 'user', content: message });
      if (input) input.value = '';
      landChatBusy = true;
      renderLandChatMessages();
      if (typeof collectTenantFormData === 'function' && document.getElementById('tenantProjectForm')) {
        // The hidden input keeps a slimmed analysis (parcels + conflicts only);
        // keep the richer in-memory object so the chat sees every extracted
        // requirement, not just what survived storage.
        const priorAnalysis = tenantProjectData.land_documents_analysis;
        try { tenantProjectData = { ...tenantProjectData, ...(await collectTenantFormData()) }; } catch (error) {}
        if (priorAnalysis && typeof priorAnalysis === 'object') {
          tenantProjectData.land_documents_analysis = priorAnalysis;
        }
      }
      let reply = 'تعذر الحصول على إجابة الآن.';
      try {
        const data = await api('POST', '/api/land-chat', {
          message,
          history: messages.slice(0, -1).slice(-LAND_CHAT_HISTORY_KEPT).map(item => ({
            role: item.role, content: String(item.content || '').slice(0, 2000)
          })),
          projectData: tenantProjectData || {}
        });
        if (data && data.reply) reply = data.reply;
        else if (data && data.error) reply = data.error;
      } catch (error) {}
      messages.push({ role: 'assistant', content: reply });
      landChatBusy = false;
      renderLandChatMessages();
    }
