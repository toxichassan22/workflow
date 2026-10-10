/* 11-land-croquis/04_land_chat.js — scoped Q&A chat pinned inside the
 * land/croquis section (temporary feature). A draggable floating ball opens a
 * panel anchored to it; the server answers only from the recorded land data
 * and must state uncertainty instead of guessing. */

    const LAND_CHAT_HISTORY_KEPT = 10;
    const LAND_CHAT_POS_KEY = 'landChatFabPos';
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
      const rtl = getComputedStyle(document.documentElement).direction === 'rtl';
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
      fab.style.left = clamped.left + 'px';
      fab.style.top = clamped.top + 'px';
      fab.style.right = 'auto';
      fab.style.bottom = 'auto';
      fab.style.insetInlineEnd = 'auto';
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
      const width = Math.min(360, window.innerWidth - 24);
      const height = Math.min(480, window.innerHeight - 24);
      const gap = 10;
      let top = rect.top - gap - height;
      if (top < 12) top = rect.bottom + gap;
      top = Math.max(12, Math.min(top, window.innerHeight - height - 12));
      const left = Math.max(12, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 12));
      panel.style.left = left + 'px';
      panel.style.top = top + 'px';
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
      panel.style.insetInlineEnd = 'auto';
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
        '<button type="button" class="land-chat-action" id="landChatMinimize" onclick="toggleLandChat(false)">إخفاء</button>' +
        '<button type="button" class="land-chat-action" id="landChatEnd" onclick="showLandChatEndConfirm()">إنهاء</button>' +
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
        '</div></div></div>';
      sectionDiv.appendChild(wrap);
      const fab = wrap.querySelector('#landChatFab');
      landChatBindFabDrag(fab);
      landChatApplyFabPosition(landChatFabPosition(), false);
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
