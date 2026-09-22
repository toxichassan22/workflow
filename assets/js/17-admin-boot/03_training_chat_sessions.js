/* 17-admin-boot/03_training_chat_sessions.js — training & AI-rules chat session
   persistence: session storage keys, CRUD over saved sessions, history
   restore, and the session-list renderers. */


    // ── Training Data & Multi-Session Chat Persistence ──
    let trainingChatHistory = [];
    let activeTrainingSessionId = null;
    let activeAIRulesSessionId = null;

    function getSessionStorageKey(type) {
      const tenantId = (window.currentUser && window.currentUser.tenant_id) || (window.currentTenant && window.currentTenant.id) || 'default';
      return 'sag_sessions_' + type + '_' + tenantId;
    }

    function getAllChatSessions(type) {
      try {
        const raw = localStorage.getItem(getSessionStorageKey(type));
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed) && parsed.length > 0) return parsed;
        }
      } catch (e) {
        console.error('Failed to load chat sessions', e);
      }
      return [];
    }

    function saveAllChatSessions(type, sessions) {
      try {
        localStorage.setItem(getSessionStorageKey(type), JSON.stringify(sessions.slice(0, 30)));
      } catch (e) {
        console.error('Failed to save chat sessions', e);
      }
    }

    function createNewChatSession(type) {
      const sessions = getAllChatSessions(type);
      const newSession = {
        id: 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5),
        title: 'محادثة جديدة',
        createdAt: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
        messages: []
      };
      sessions.unshift(newSession);
      saveAllChatSessions(type, sessions);

      if (type === 'training') {
        activeTrainingSessionId = newSession.id;
        trainingChatHistory = [];
        renderTrainingChatSessions();
        renderTrainingChat();
      } else if (type === 'ai_rules') {
        activeAIRulesSessionId = newSession.id;
        aiRulesChatHistory = [];
        renderAIRulesChatSessions();
        renderAIRulesChat();
      }
    }

    function selectChatSession(type, sessionId) {
      const sessions = getAllChatSessions(type);
      const target = sessions.find(s => s.id === sessionId);
      if (!target) return;

      if (type === 'training') {
        activeTrainingSessionId = sessionId;
        trainingChatHistory = target.messages || [];
        renderTrainingChatSessions();
        renderTrainingChat();
      } else if (type === 'ai_rules') {
        activeAIRulesSessionId = sessionId;
        aiRulesChatHistory = target.messages || [];
        renderAIRulesChatSessions();
        renderAIRulesChat();
      }
    }

    function deleteChatSession(type, sessionId, e) {
      if (e) e.stopPropagation();
      let sessions = getAllChatSessions(type);
      sessions = sessions.filter(s => s.id !== sessionId);
      saveAllChatSessions(type, sessions);

      if (type === 'training') {
        if (activeTrainingSessionId === sessionId) {
          activeTrainingSessionId = sessions.length ? sessions[0].id : null;
          trainingChatHistory = sessions.length ? (sessions[0].messages || []) : [];
        }
        renderTrainingChatSessions();
        renderTrainingChat();
      } else if (type === 'ai_rules') {
        if (activeAIRulesSessionId === sessionId) {
          activeAIRulesSessionId = sessions.length ? sessions[0].id : null;
          aiRulesChatHistory = sessions.length ? (sessions[0].messages || []) : [];
        }
        renderAIRulesChatSessions();
        renderAIRulesChat();
      }
      toast('تم حذف المحادثة');
    }

    function clearAllChatSessions(type) {
      try {
        localStorage.removeItem(getSessionStorageKey(type));
      } catch (e) { }
      if (type === 'training') {
        activeTrainingSessionId = null;
        trainingChatHistory = [];
        renderTrainingChatSessions();
        renderTrainingChat();
      } else if (type === 'ai_rules') {
        activeAIRulesSessionId = null;
        aiRulesChatHistory = [];
        renderAIRulesChatSessions();
        renderAIRulesChat();
      }
      toast('تم مسح جميع المحادثات');
    }

    function saveCurrentSessionState(type, history) {
      let sessions = getAllChatSessions(type);
      const activeId = type === 'training' ? activeTrainingSessionId : activeAIRulesSessionId;

      let session = sessions.find(s => s.id === activeId);
      const cleanMessages = (history || []).filter(m => !m._typing);

      if (!session) {
        const firstUserMsg = cleanMessages.find(m => m.role === 'user');
        const autoTitle = firstUserMsg ? firstUserMsg.text.slice(0, 24).trim() : 'محادثة جديدة';
        session = {
          id: 'sess_' + Date.now(),
          title: autoTitle || 'محادثة جديدة',
          createdAt: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
          messages: cleanMessages
        };
        sessions.unshift(session);
        if (type === 'training') activeTrainingSessionId = session.id;
        else activeAIRulesSessionId = session.id;
      } else {
        session.messages = cleanMessages;
        if (session.title === 'محادثة جديدة') {
          const firstUserMsg = cleanMessages.find(m => m.role === 'user');
          if (firstUserMsg && firstUserMsg.text) {
            session.title = firstUserMsg.text.slice(0, 24).trim();
          }
        }
      }

      saveAllChatSessions(type, sessions);
      if (type === 'training') renderTrainingChatSessions();
      else renderAIRulesChatSessions();
    }

    function renderTrainingChatSessions() {
      const container = document.getElementById('trainingChatSessionsList');
      if (!container) return;
      const sessions = getAllChatSessions('training');
      if (!sessions.length) {
        container.innerHTML = '<p class="tenant-hint" style="text-align:center;padding:12px 0;font-size:11px;">لا توجد محادثات سابقة</p>';
        return;
      }
      container.innerHTML = sessions.map(s => {
        const isActive = s.id === activeTrainingSessionId;
        const bg = isActive ? '#e0f2fe' : '#ffffff';
        const border = isActive ? '#38bdf8' : '#e2e8f0';
        const textColor = isActive ? '#0369a1' : 'var(--txt)';
        const count = (s.messages || []).filter(m => m.role === 'user').length;
        return `
          <div onclick="selectChatSession('training', '${s.id}')" role="button" tabindex="0" style="background:${bg};border:1px solid ${border};border-radius:8px;padding:8px 10px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:6px;transition:all 0.15s ease;">
            <div style="overflow:hidden;flex:1;">
              <div style="font-size:12px;font-weight:${isActive ? '700' : '500'};color:${textColor};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(s.title)}">
                ${escapeHtml(s.title)}
              </div>
              <div style="font-size:10px;color:var(--muted);margin-top:2px;"><span>${count}</span> <span>رسالة</span> • ${s.createdAt || ''}</div>
            </div>
            <button onclick="deleteChatSession('training', '${s.id}', event)" title="حذف" style="background:none;border:none;cursor:pointer;font-size:13px;opacity:0.6;padding:2px;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.6"></button>
          </div>
        `;
      });
    }

    function renderAIRulesChatSessions() {
      const container = document.getElementById('aiRulesChatSessionsList');
      if (!container) return;
      const sessions = getAllChatSessions('ai_rules');
      if (!sessions.length) {
        container.innerHTML = '<p class="tenant-hint" style="text-align:center;padding:12px 0;font-size:11px;">لا توجد محادثات سابقة</p>';
        return;
      }
      container.innerHTML = sessions.map(s => {
        const isActive = s.id === activeAIRulesSessionId;
        const bg = isActive ? '#e0f2fe' : '#ffffff';
        const border = isActive ? '#38bdf8' : '#e2e8f0';
        const textColor = isActive ? '#0369a1' : 'var(--txt)';
        const count = (s.messages || []).filter(m => m.role === 'user').length;
        return `
          <div onclick="selectChatSession('ai_rules', '${s.id}')" role="button" tabindex="0" style="background:${bg};border:1px solid ${border};border-radius:8px;padding:8px 10px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:6px;transition:all 0.15s ease;">
            <div style="overflow:hidden;flex:1;">
              <div style="font-size:12px;font-weight:${isActive ? '700' : '500'};color:${textColor};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(s.title)}">
                ${escapeHtml(s.title)}
              </div>
              <div style="font-size:10px;color:var(--muted);margin-top:2px;"><span>${count}</span> <span>رسالة</span> • ${s.createdAt || ''}</div>
            </div>
            <button onclick="deleteChatSession('ai_rules', '${s.id}', event)" title="حذف" style="background:none;border:none;cursor:pointer;font-size:13px;opacity:0.6;padding:2px;" onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.6"></button>
          </div>
        `;
      }).join('');
    }

    async function openTenantTraining() {
      showTenantPage('tenantTrainingPage');
      const sessions = getAllChatSessions('training');
      if (sessions.length) {
        if (!activeTrainingSessionId || !sessions.some(s => s.id === activeTrainingSessionId)) {
          activeTrainingSessionId = sessions[0].id;
        }
        const active = sessions.find(s => s.id === activeTrainingSessionId);
        trainingChatHistory = active ? (active.messages || []) : [];
      } else {
        createNewChatSession('training');
      }
      renderTrainingChatSessions();
      renderTrainingChat();
      await loadTrainingList();
    }
