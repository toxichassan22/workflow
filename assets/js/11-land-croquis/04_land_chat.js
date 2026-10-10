/* 11-land-croquis/04_land_chat.js — scoped Q&A chat pinned inside the
 * land/croquis section (temporary feature). A floating button opens a small
 * popup at the bottom corner; the server answers only from the recorded land
 * data and must state uncertainty instead of guessing. */

    const LAND_CHAT_HISTORY_KEPT = 10;
    let landChatBusy = false;
    const landChatMessages = [];

    function landChatHistory() {
      return landChatMessages;
    }

    function mountLandChat(sectionDiv) {
      if (!sectionDiv || document.getElementById('landChatFab')) return;
      const wrap = document.createElement('div');
      wrap.className = 'land-chat-wrap';
      wrap.innerHTML =
        '<button type="button" class="land-chat-fab" id="landChatFab" onclick="toggleLandChat()">شات الأرض والكروكي</button>' +
        '<div class="land-chat-panel" id="landChatPanel" hidden>' +
        '<div class="land-chat-header">' +
        '<div class="land-chat-title">شات الأرض والكروكي</div>' +
        '<button type="button" class="land-chat-close" onclick="toggleLandChat(false)">إغلاق</button>' +
        '</div>' +
        '<div class="land-chat-messages" id="landChatMessages"></div>' +
        '<div class="land-chat-input-row">' +
        '<textarea id="landChatInput" class="land-chat-input" rows="1" ' +
        'placeholder="اسأل عن بيانات الأرض والكروكي..." data-i18n-ph="land_chat.placeholder" data-section-lock-ignore="1"></textarea>' +
        '<button type="button" class="btn primary land-chat-send" id="landChatSend" onclick="sendLandChat()">إرسال</button>' +
        '</div></div>';
      sectionDiv.appendChild(wrap);
      const input = wrap.querySelector('#landChatInput');
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendLandChat();
        }
      });
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
        const input = document.getElementById('landChatInput');
        if (input) input.focus();
      }
    }

    function renderLandChatMessages() {
      const box = document.getElementById('landChatMessages');
      if (!box) return;
      box.innerHTML = '';
      const messages = landChatHistory();
      if (!messages.length) {
        const empty = document.createElement('div');
        empty.className = 'land-chat-empty';
        empty.textContent = 'شات مخصص لبيانات الأرض والكروكي — يغطي معاملات البناء والأدوار المسموحة والارتدادات والإحداثيات والتوزيعات.';
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
        try { tenantProjectData = { ...tenantProjectData, ...(await collectTenantFormData()) }; } catch (error) {}
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
