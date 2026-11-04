/* 17-admin-boot.js - index.html lines 27659-28724, shared global scope, classic scripts in order */

    function setTrainingChatExample(text) {
      const input = document.getElementById('trainingChatInput');
      if (input) {
        input.value = (input.value ? input.value + '\n' : '') + text;
        input.focus();
      }
    }

    async function sendTrainingChat() {
      const input = document.getElementById('trainingChatInput');
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      trainingChatHistory.push({ role: 'user', text });
      saveCurrentSessionState('training', trainingChatHistory);
      // Show typing indicator
      trainingChatHistory.push({ role: 'ai', text: ' جاري التفكير والتنفيذ...', _typing: true });
      renderTrainingChat();

      let data;
      try {
        data = await api('POST', '/api/training-chat', {
          message: text,
          history: trainingChatHistory.filter(m => !m._typing).slice(0, -1),
          workspace: buildAgentWorkspacePayload()
        });
      } catch (error) {
        data = { success: false, error: error.message || 'تعذر الاتصال بخادم التدريب.' };
      } finally {
        trainingChatHistory = trainingChatHistory.filter(m => !m._typing);
      }

      if (data && data.success) {
        const msg = { role: 'ai', text: data.reply || 'تم استلام رسالتك.' };
        if (data.actions && data.actions.length) {
          msg.actions = data.actions;
        }
        trainingChatHistory.push(msg);
        saveCurrentSessionState('training', trainingChatHistory);
        // If actions were executed, refresh the training list and show toast
        if (data.actions && data.actions.length) {
          const successCount = data.actions.filter(a => a.status === 'success').length;
          if (successCount) {
            toast(WFT('training.actions_done', 'تم تنفيذ {n} إجراء بنجاح', { n: successCount }));
            await applyAgentWorkspaceActions(data.actions);
            await loadTrainingList();
            await refreshSystemDataAfterAgentAction();
          }
        }
      } else {
        trainingChatHistory.push({ role: 'ai', text: (data && data.error) || 'فشل الرد.' });
        saveCurrentSessionState('training', trainingChatHistory);
      }
      renderTrainingChat();
    }

    async function refreshSystemDataAfterAgentAction() {
      try {
        await loadTenantBranding();
        if (typeof loadTenantFontCss === 'function') await loadTenantFontCss();
        const settingsPage = document.getElementById('tenantSettingsPage');
        if (settingsPage && settingsPage.style.display !== 'none') {
          await loadTenantFonts();
        }
        const fieldsData = await api('GET', '/api/fields');
        if (fieldsData.success && fieldsData.fields) {
          tenantFields = fieldsData.fields;
          const projectPage = document.getElementById('tenantProjectPage');
          if (projectPage && projectPage.style.display !== 'none') {
            renderTenantProjectForm(tenantFields);
          }
          const fieldsPage = document.getElementById('tenantFieldsPage');
          if (fieldsPage && fieldsPage.style.display !== 'none') {
            renderTenantFields();
          }
        }
      } catch (e) {
        console.warn('System refresh after agent action:', e);
      }
    }

    async function saveLastTrainingChatMessage() {
      const lastUser = trainingChatHistory.slice().reverse().find(m => m.role === 'user');
      if (!lastUser) { toast('لا توجد رسالة لحفظها'); return; }
      const title = lastUser.text.split('\n')[0].trim().slice(0, 80) || 'بيانات تدريب';
      const data = await api('POST', '/api/training', { title, content: lastUser.text, category: 'chat' });
      if (data.success) {
        toast('تم حفظ البيانات');
        await loadTrainingList();
      } else {
        toast(data.error || 'فشل الحفظ');
      }
    }

    async function loadTrainingList() {
      const list = document.getElementById('trainingList');
      if (list) showInlineLoader(list, 'جاري التحميل...');
      const data = await api('GET', '/api/training');
      const entries = (data.success && data.entries) ? data.entries : [];
      if (list) {
        list.innerHTML = entries.length
          ? entries.map(e => '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(e.title) + '</h3></div></div>').join('')
          : '<p class="tenant-hint">لا توجد بيانات تدريب بعد</p>';
      }
      renderTrainingEntriesInChat(entries);
    }

    async function toggleTrainingEntry(entryId, isActive) {
      const data = await api('PUT', '/api/training/' + entryId, { is_active: isActive });
      if (data.success) { toast(isActive ? 'تم التفعيل' : 'تم التعطيل'); await loadTrainingList(); }
    }

    async function deleteTrainingEntry(entryId) {
      if (!confirm('حذف هذه البيانات؟')) return;
      const data = await api('DELETE', '/api/training/' + entryId);
      if (data.success) { toast('تم الحذف'); await loadTrainingList(); }
    }

    function renderTrainingEntriesInChat(entries) {
      const container = document.getElementById('trainingEntriesInChat');
      if (!container) return;
      if (!entries || !entries.length) {
        container.innerHTML = '<p class="tenant-hint">لا توجد بيانات محفوظة لعرضها هنا</p>';
        return;
      }
      container.innerHTML = entries.map(e => {
        const img = e.imageUrl ? '<img src="' + e.imageUrl + '" style="width:72px;height:54px;object-fit:cover;border-radius:6px;border:1px solid var(--line);margin-left:8px">' : '';
        const contentPreview = '<div style="font-size:13px;color:var(--muted);max-height:64px;overflow:hidden;white-space:pre-wrap">' + escapeHtml(e.content) + '</div>';
        return '<div style="display:flex;align-items:flex-start;gap:8px;margin-bottom:8px;border:1px solid var(--line);padding:8px;border-radius:10px;background:#fff">' +
          (img ? img : '') +
          '<div style="flex:1">' +
          '<div style="display:flex;justify-content:space-between;align-items:center"><strong>' + escapeHtml(e.title) + '</strong>' +
          '<div style="display:flex;gap:6px">' +
          '<button class="btn small ' + (e.is_active ? 'danger' : 'green') + '" onclick="toggleTrainingEntry(\'' + e.id + '\',' + (!e.is_active) + ')">' + (e.is_active ? 'تعطيل' : 'تفعيل') + '</button>' +
          '<button class="btn small danger" onclick="deleteTrainingEntry(\'' + e.id + '\')">حذف</button>' +
          '</div></div>' +
          contentPreview +
          '</div>' +
          '</div>';
      }).join('');
    }

    async function uploadTrainingImageFromChat() {
      const fileInput = document.getElementById('trainingChatImageFile');
      const consent = document.getElementById('trainingChatImageConsent');
      const type = document.getElementById('trainingChatImageType');
      const title = document.getElementById('trainingChatImageTitle');
      const status = document.getElementById('trainingChatImageStatus');
      if (!fileInput || !fileInput.files || !fileInput.files[0]) { toast('اختر صورة أولاً'); return; }
      if (!consent || !consent.checked) { toast('الموافقة مطلوبة قبل رفع الصورة'); return; }
      status.textContent = 'جاري رفع الصورة...';
      const form = new FormData();
      form.append('image', fileInput.files[0]);
      form.append('title', (title && title.value) ? title.value : 'Training image');
      form.append('category', 'chat');
      form.append('imageType', type ? type.value : 'reference');
      form.append('description', 'Uploaded from training chat');
      form.append('companyDataConsent', '1');
      const resp = await api('POST', '/api/training/upload-image', form, true);
      if (resp && resp.success) {
        toast('تم رفع الصورة وحفظها كبيانات تدريب');
        fileInput.value = '';
        if (title) title.value = '';
        status.textContent = '';
        await loadTrainingList();
      } else {
        status.textContent = '';
        toast(resp && resp.error ? resp.error : 'فشل رفع الصورة');
      }
    }

    // ── AI Rules ──
    let aiRulesData = { designRules: [], contentRules: '', training: [], log: [] };

    async function openTenantAIRules() {
      showTenantPage('tenantAIRulesPage');
      await loadAIRules();
      showAIRuleTab('training');
    }

    async function loadAIRules() {
      const data = await api('GET', '/api/ai-rules');
      if (!data.success) { toast('تعذر تحميل قواعد AI'); return; }
      aiRulesData = {
        designRules: data.designRules || [],
        contentRules: data.contentRules || '',
        training: data.training || [],
        log: data.log || []
      };
      renderAITrainingList();
      renderAILogList();
    }

    let aiRulesChatHistory = [];

    function showAIRuleTab(tab) {
      document.querySelectorAll('.ai-rule-tab').forEach(el => el.style.display = 'none');
      document.getElementById('aiRules' + (tab.charAt(0).toUpperCase() + tab.slice(1))).style.display = 'block';
      ['training', 'log'].forEach(t => {
        const btn = document.getElementById('aiTab' + (t.charAt(0).toUpperCase() + t.slice(1)));
        if (btn) btn.classList.toggle('primary', t === tab);
      });
      if (tab === 'log') {
        renderAILogList();
      }
      if (tab === 'training') {
        const sessions = getAllChatSessions('ai_rules');
        if (sessions.length) {
          if (!activeAIRulesSessionId || !sessions.some(s => s.id === activeAIRulesSessionId)) {
            activeAIRulesSessionId = sessions[0].id;
          }
          const active = sessions.find(s => s.id === activeAIRulesSessionId);
          aiRulesChatHistory = active ? (active.messages || []) : [];
        } else {
          createNewChatSession('ai_rules');
        }
        renderAIRulesChatSessions();
        renderAIRulesChat();
      }
    }

    function attachFileToChat(file) {
      if (!file || !file.type.startsWith('image/')) {
        toast('يرجى اختيار أو لصق صورة صالحة (PNG/JPG/WEBP)');
        return;
      }
      const input = document.getElementById('trainingChatImageFile');
      if (input) {
        try {
          const dt = new DataTransfer();
          dt.items.add(file);
          input.files = dt.files;
        } catch (e) {
          console.warn('[ATTACH IMAGE WARN]', e);
        }
        const consentInput = document.getElementById('trainingChatImageConsent');
        if (consentInput) consentInput.checked = true;
        handleChatImageSelected(input);
      }
      toast('تم إرفاق الصورة وتجهيزها بنجاح!');
    }

    function bindImagePasteAndDrop(elementId) {
      const el = document.getElementById(elementId);
      if (!el) return;

      // 1. Clipboard Paste Handler (Ctrl+V / Paste)
      el.addEventListener('paste', function (e) {
        const clipboardData = e.clipboardData || window.clipboardData;
        if (!clipboardData || !clipboardData.items) return;
        const items = clipboardData.items;
        for (let i = 0; i < items.length; i++) {
          if (items[i].type && items[i].type.indexOf('image') !== -1) {
            e.preventDefault();
            const blob = items[i].getAsFile();
            if (blob) {
              attachFileToChat(blob);
            }
            break;
          }
        }
      });

      // 2. Drag & Drop Handlers
      el.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.stopPropagation();
        el.style.borderColor = 'var(--p)';
        el.style.background = '#f0f7fc';
      });
      el.addEventListener('dragleave', function (e) {
        e.preventDefault();
        e.stopPropagation();
        el.style.borderColor = '';
        el.style.background = '';
      });
      el.addEventListener('drop', function (e) {
        e.preventDefault();
        e.stopPropagation();
        el.style.borderColor = '';
        el.style.background = '';
        const files = e.dataTransfer ? e.dataTransfer.files : null;
        if (files && files.length > 0 && files[0].type.startsWith('image/')) {
          attachFileToChat(files[0]);
        }
      });
    }

    function initChatImageHandlers() {
      ['aiRulesChatInput', 'tenantChatInput', 'trainingChatInput'].forEach(id => {
        bindImagePasteAndDrop(id);
      });
    }

    function handleChatImageSelected(input) {
      const bar = document.getElementById('aiRulesImageOptionsBar');
      const nameEl = document.getElementById('aiRulesImageFileName');
      if (input && input.files && input.files[0]) {
        if (nameEl) nameEl.textContent = input.files[0].name;
        if (bar) bar.style.display = 'block';
      } else {
        if (bar) bar.style.display = 'none';
      }
    }

    function clearAttachedChatImage() {
      const input = document.getElementById('trainingChatImageFile');
      const bar = document.getElementById('aiRulesImageOptionsBar');
      if (input) input.value = '';
      if (bar) bar.style.display = 'none';
    }

    function renderAIRulesChat() {
      const log = document.getElementById('aiRulesChatLog');
      if (!log) return;
      if (!aiRulesChatHistory.length) {
        log.innerHTML = '<div style="text-align:center;padding:32px 20px;"><h3 style="margin:0 0 8px;color:var(--accent);">'
           + WFT('agent.title', 'وكيل الإدارة الذكي') + '</h3></div>';
        return;
      }
      log.innerHTML = aiRulesChatHistory.map(m => {
        let content = escapeHtml(m.text || '').replace(/\n/g, '<br>');
        if (m.imageUrl) {
          content = '<div>' + content + '</div><img src="' + m.imageUrl + '" style="max-width:240px;max-height:180px;object-fit:cover;border-radius:8px;margin-top:8px;border:1px solid rgba(0,0,0,0.1);display:block;">';
        }
        // Show action cards for AI messages
        if (m.role === 'ai' && m.actions && m.actions.length) {
          content += '<div style="margin-top:10px;">';
          m.actions.forEach(a => {
            const isOk = a.status === 'success';
            const icon = isOk ? '' : '';
            const bg = isOk ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)';
            const border = isOk ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)';
            const color = isOk ? '#16a34a' : '#dc2626';
            content += '<div style="background:' + bg + ';border:1px solid ' + border + ';border-radius:8px;padding:8px 12px;margin-top:6px;font-size:12px;">';
            content += '<span style="color:' + color + ';font-weight:600;">' + icon + ' ' + escapeHtml(a.message || a.tool || '') + '</span>';
            if (a.changes && Object.keys(a.changes).length) {
              content += '<div style="margin-top:4px;font-size:11px;opacity:0.8;">';
              Object.entries(a.changes).forEach(([k, v]) => {
                if (v && typeof v === 'object' && 'old' in v) {
                  content += '<div>' + escapeHtml(k) + ': <s>' + escapeHtml(String(v.old || '—')) + '</s> إلى <strong>' + escapeHtml(String(v.new)) + '</strong></div>';
                }
              });
              content += '</div>';
            }
            content += '</div>';
          });
          content += '</div>';
        }
        return '<div class="msg ' + m.role + '">' + content + '</div>';
      }).join('');
      log.scrollTop = log.scrollHeight;
    }

    const AGENT_FILE_LIMIT = 4 * 1024 * 1024;

    function readFileAsDataUri(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error('تعذر قراءة الملف'));
        reader.readAsDataURL(file);
      });
    }

    async function sendAIRulesChat() {
      const input = document.getElementById('aiRulesChatInput');
      const text = input ? input.value.trim() : '';
      const fileInput = document.getElementById('trainingChatImageFile');
      const typeInput = document.getElementById('trainingChatImageType');
      const statusEl = document.getElementById('trainingChatImageStatus');
      const file = fileInput && fileInput.files && fileInput.files[0];

      if (!text && !file) return;
      if (file && file.size > AGENT_FILE_LIMIT) {
        toast('حجم الملف أكبر من 4 م.ب');
        return;
      }

      // An attached file used to be uploaded, analysed and stored as training text, and the turn
      // ended there: the agent that answers the message never received the file, so it could not
      // act on what the file said. The file now travels with the message.
      let attachedImage = '';
      let attachedFile = null;
      let displayText = text;
      let previewUrl = '';

      if (file) {
        const isImage = file.type.startsWith('image/');
        previewUrl = isImage ? URL.createObjectURL(file) : '';
        displayText = (text ? '[' + file.name + ']\n' + text : '[' + file.name + ']');
        if (statusEl) statusEl.textContent = 'جاري قراءة الملف...';
        try {
          const dataUri = await readFileAsDataUri(file);
          if (isImage) attachedImage = dataUri;
          else attachedFile = { name: file.name, dataUri };
        } catch (error) {
          if (statusEl) statusEl.textContent = '';
          toast(error.message || 'تعذر قراءة الملف');
          return;
        }
        if (statusEl) statusEl.textContent = '';
      }

      if (input) input.value = '';
      clearAttachedChatImage();
      aiRulesChatHistory.push({ role: 'user', text: displayText, imageUrl: previewUrl || undefined });
      saveCurrentSessionState('ai_rules', aiRulesChatHistory);
      aiRulesChatHistory.push({ role: 'ai', text: ' جاري التفكير والتنفيذ...', _typing: true });
      renderAIRulesChat();

      // An image the admin wants kept as a company reference is still stored as training data.
      if (file && attachedImage) {
        const formData = new FormData();
        formData.append('image', file);
        formData.append('title', file.name);
        formData.append('category', 'chat');
        formData.append('imageType', typeInput ? typeInput.value : 'reference');
        formData.append('description', text || 'Uploaded via AI Training Chat');
        formData.append('companyDataConsent', 'true');
        try {
          await api('POST', '/api/training/upload-image', formData, true);
        } catch (error) {
          console.warn('[AGENT] Could not store the attached image as training data:', error);
        }
      }

      let data;
      try {
        data = await api('POST', '/api/training-chat', {
          message: text || 'اقرأ الملف المرفق وأخبرني بما فيه وما تقترح تنفيذه.',
          history: aiRulesChatHistory.filter(m => !m._typing).slice(0, -1),
          workspace: buildAgentWorkspacePayload(),
          attachedImage,
          attachedFile
        });
      } catch (error) {
        data = { success: false, error: error.message || 'تعذر الاتصال بخادم التدريب.' };
      } finally {
        aiRulesChatHistory = aiRulesChatHistory.filter(m => !m._typing);
      }

      if (data && data.success) {
        const msg = { role: 'ai', text: data.reply || 'تم استلام رسالتك.' };
        if (data.actions && data.actions.length) {
          msg.actions = data.actions;
        }
        aiRulesChatHistory.push(msg);
        saveCurrentSessionState('ai_rules', aiRulesChatHistory);
        if (data.actions && data.actions.length) {
          const successCount = data.actions.filter(a => a.status === 'success').length;
          if (successCount) {
            toast(WFT('training.actions_done', 'تم تنفيذ {n} إجراء بنجاح', { n: successCount }));
            await applyAgentWorkspaceActions(data.actions);
            await loadAIRules();
            await refreshSystemDataAfterAgentAction();
          }
        }
      } else {
        aiRulesChatHistory.push({ role: 'ai', text: (data && data.error) || 'فشل الرد.' });
        saveCurrentSessionState('ai_rules', aiRulesChatHistory);
      }
      renderAIRulesChat();
    }

    async function saveLastAIRulesChatMessage() {
      const lastUser = aiRulesChatHistory.slice().reverse().find(m => m.role === 'user');
      if (!lastUser) { toast('لا توجد رسالة لحفظها'); return; }
      const title = lastUser.text.split('\n')[0].trim().slice(0, 80) || 'بيانات تدريب';
      const data = await api('POST', '/api/training', { title, content: lastUser.text, category: 'chat' });
      if (data.success) {
        toast('تم حفظ البيانات');
        await loadAIRules();
      } else {
        toast(data.error || 'فشل الحفظ');
      }
    }

    async function renderAITrainingList() {
      const list = document.getElementById('aiTrainingList');
      if (!list) return;
      if (!aiRulesData.training.length) { list.innerHTML = '<p class="tenant-hint">لا توجد بيانات تدريب بعد</p>'; return; }
      list.innerHTML = aiRulesData.training.map(e =>
        '<div class="tenant-presentation-card">' +
        '<div style="display:flex;gap:12px;align-items:flex-start;">' +
        (e.imageUrl ? '<div style="width:80px;min-height:54px;padding:8px;border:1px solid var(--line);border-radius:8px;flex-shrink:0;font-size:12px;color:var(--muted);">صورة شركة محفوظة</div>' : '') +
        '<div style="flex:1"><h3>' + escapeHtml(e.title) + '</h3>' +
        '<div class="meta">' + escapeHtml(e.category || 'general') + ' | ' + (e.is_active ? 'نشط' : 'معطل') + ' | ' + escapeHtml(e.created_at || '') + '</div>' +
        '<p style="margin:8px 0 0;font-size:13px;color:var(--muted);white-space:pre-wrap;max-height:100px;overflow:auto">' + escapeHtml(e.content) + '</p></div>' +
        '</div>' +
        '<div class="tenant-actions">' +
        '<button class="btn small ' + (e.is_active ? 'danger' : 'green') + '" onclick="toggleAITrainingEntry(\'' + e.id + '\', ' + (!e.is_active) + ')">' + (e.is_active ? 'تعطيل' : 'تفعيل') + '</button>' +
        '<button class="btn small danger" onclick="deleteAITrainingEntry(\'' + e.id + '\')">حذف</button>' +
        '</div></div>'
      ).join('');
    }

    async function toggleAITrainingEntry(entryId, isActive) {
      const data = await api('PUT', '/api/training/' + entryId, { is_active: isActive });
      if (data.success) { toast(isActive ? 'تم التفعيل' : 'تم التعطيل'); await loadAIRules(); }
    }

    async function deleteAITrainingEntry(entryId) {
      if (!confirm('حذف هذه البيانات؟')) return;
      const data = await api('DELETE', '/api/training/' + entryId);
      if (data.success) { toast('تم الحذف'); await loadAIRules(); }
    }

    function renderAILogList() {
      const list = document.getElementById('aiRulesLogList');
      if (!list) return;
      const entries = (aiRulesData.training || []).slice().sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
        return tb - ta;
      });
      if (!entries.length) { list.innerHTML = '<p class="tenant-hint">لا توجد بيانات تدريب محفوظة بعد</p>'; return; }
      list.innerHTML = entries.map(e => {
        const statusText = e.is_active ? 'نشط' : 'معطل';
        const statusColor = e.is_active ? '#2e7d32' : '#c62828';
        const imgHtml = e.imageUrl ? '<div style="margin-top:8px;"><img src="' + e.imageUrl + '" style="max-width:140px;max-height:100px;object-fit:cover;border-radius:8px;border:1px solid var(--line);"></div>' : '';
        return '<div class="tenant-presentation-card" style="margin-bottom:12px;display:block;">' +
          '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">' +
          '<div style="flex:1;">' +
          '<strong>' + escapeHtml(e.title || 'بيانات تدريب') + '</strong>' +
          '<div class="meta" style="margin-top:2px;">' + escapeHtml(e.category || 'general') + ' | ' + escapeHtml(e.created_at || '') + ' | <span style="color:' + statusColor + ';font-weight:600;">' + statusText + '</span></div>' +
          '</div>' +
          '<div class="tenant-actions" style="display:flex;gap:6px;">' +
          '<button class="btn small ' + (e.is_active ? 'danger' : 'green') + '" onclick="toggleAITrainingEntry(\'' + e.id + '\', ' + (!e.is_active) + ')">' + (e.is_active ? 'تعطيل' : 'تفعيل') + '</button>' +
          '<button class="btn small danger" onclick="deleteAITrainingEntry(\'' + e.id + '\')">حذف</button>' +
          '</div>' +
          '</div>' +
          imgHtml +
          '<div style="font-size:13px;color:var(--muted);margin-top:8px;white-space:pre-wrap;max-height:120px;overflow:auto;">' + escapeHtml(e.content || '') + '</div>' +
          '</div>';
      }).join('');
    }

    // ── Approvals Hub ──
    let currentApprovalsTab = 'pending';

    function switchApprovalsTab(tab) {
      currentApprovalsTab = tab || 'pending';
      const pendingView = document.getElementById('approvalsPendingView');
      const historyView = document.getElementById('approvalsHistoryView');
      const pendingBtn = document.getElementById('tabPendingApprovalsBtn');
      const historyBtn = document.getElementById('tabHistoryApprovalsBtn');
      if (currentApprovalsTab === 'history') {
        if (pendingView) pendingView.style.display = 'none';
        if (historyView) historyView.style.display = 'block';
        if (pendingBtn) { pendingBtn.className = 'btn small ghost'; }
        if (historyBtn) { historyBtn.className = 'btn small primary'; }
      } else {
        if (pendingView) pendingView.style.display = 'block';
        if (historyView) historyView.style.display = 'none';
        if (pendingBtn) { pendingBtn.className = 'btn small primary'; }
        if (historyBtn) { historyBtn.className = 'btn small ghost'; }
      }
    }

    async function openTenantApprovals(forceRefresh) {
      showTenantPage('tenantApprovalsPage');
      await loadApprovalsList();
    }

    async function loadApprovalsList() {
      const pendingList = document.getElementById('approvalsList');
      const historyList = document.getElementById('approvalsHistoryList');
      if (!pendingList) return;
      showInlineLoader(pendingList, typeof WFT === 'function' ? WFT('common.loading', 'جاري التحميل...') : 'جاري التحميل...');

      const [data, genData, finData, histData, genAllData, finAllData] = await Promise.all([
        api('GET', '/api/approvals'),
        api('GET', '/api/generation-approvals?status=pending'),
        api('GET', '/api/final-file-approvals?status=pending'),
        api('GET', '/api/approvals/history'),
        api('GET', '/api/generation-approvals'),
        api('GET', '/api/final-file-approvals'),
      ]);

      const approvals = (data && data.success && data.approvals) ? data.approvals : [];
      const genApprovals = (genData && genData.success && genData.approvals) ? genData.approvals : [];
      const finApprovals = (finData && finData.success && finData.approvals) ? finData.approvals : [];

      const histPres = (histData && histData.success && histData.approvals) ? histData.approvals : [];
      const histGen = (genAllData && genAllData.success && genAllData.approvals)
        ? genAllData.approvals.filter(a => a.status && a.status !== 'pending') : [];
      const histFin = (finAllData && finAllData.success && finAllData.approvals)
        ? finAllData.approvals.filter(a => a.status && a.status !== 'pending') : [];

      const pendingTotal = approvals.length + genApprovals.length + finApprovals.length;
      const historyTotal = histPres.length + histGen.length + histFin.length;

      // Update counters & stats strip
      const setElText = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
      setElText('statPendingApprovals', pendingTotal);
      setElText('statGenApprovals', genApprovals.length);
      setElText('statSectionApprovals', approvals.length + finApprovals.length);
      setElText('statDecidedApprovals', historyTotal);
      setElText('approvalsCountBadge', pendingTotal);
      setElText('tabPendingCountBadge', '(' + pendingTotal + ')');
      setElText('tabHistoryCountBadge', '(' + historyTotal + ')');

      const myUserId = String((tenantUser && tenantUser._userId) || '');
      const isCompanyAdmin = Boolean(tenantUser && tenantUser.isAdmin) ||
        (tenantUser && tenantUser._userRole) === 'company_admin';

      const decideBtns = (fnName, id, requestedBy, permKey) =>
        (hasPermission(permKey) && (isCompanyAdmin || !requestedBy || String(requestedBy) !== myUserId))
          ? '<button type="button" class="btn small green" onclick="' + fnName + '(\'' + id + '\', \'approved\')">' + (typeof WFT === 'function' ? WFT('common.approve', 'اعتماد') : 'اعتماد') + '</button>' +
            '<button type="button" class="btn small danger" onclick="' + fnName + '(\'' + id + '\', \'rejected\')">' + (typeof WFT === 'function' ? WFT('common.reject', 'رفض') : 'رفض') + '</button>'
          : '<span class="tenant-hint">' + (typeof WFT === 'function' ? WFT('approvals.waiting_decision', 'بانتظار قرار المعتمد') : 'بانتظار قرار المعتمد') + '</span>';

      // 1. Render Pending View
      if (pendingTotal === 0) {
        pendingList.innerHTML = '<div class="tenant-dash-empty-state" style="text-align:center;padding:48px 20px;background:#ffffff;border:1px dashed var(--line-strong,#CBD5E1);border-radius:14px;margin-top:12px">' +
          '<h3 class="tenant-dash-empty-title" style="font-size:16px;font-weight:800;color:var(--navy,#07182c);margin-bottom:8px">' +
            (typeof WFT === 'function' ? WFT('approvals.empty_title', 'كافة العروض والأقسام معتمدة ومحدثة') : 'كافة العروض والأقسام معتمدة ومحدثة') +
          '</h3>' +
          '<p class="tenant-hint" style="margin-bottom:20px;color:var(--ink-muted,#64748b)">' +
            (typeof WFT === 'function' ? WFT('approvals.empty_desc', 'لا توجد طلبات تعميد أو اعتماد محتوى معلقة في الوقت الحالي.') : 'لا توجد طلبات تعميد أو اعتماد محتوى معلقة في الوقت الحالي.') +
          '</p>' +
          '<button type="button" class="btn small primary" onclick="openTenantPresentations()">' +
            (typeof WFT === 'function' ? WFT('approvals.view_all_projects', 'استعراض كافة المشاريع') : 'استعراض كافة المشاريع') +
          '</button>' +
          '</div>';
      } else {
        const presHtml = approvals.map(a =>
          '<div class="tenant-approval-card">' +
            '<div class="approval-main">' +
              '<div class="approval-header-line">' +
                '<h3 class="approval-title">' + escapeHtml(a.pres_title || 'عرض') + '</h3>' +
                '<span class="proposal-status-badge status-warning">' + (typeof WFT === 'function' ? WFT('approvals.tier_two_deck', 'المرحلة الثانية: تعميد عرض متكامل') : 'المرحلة الثانية: تعميد عرض متكامل') + '</span>' +
              '</div>' +
              '<div class="approval-meta">' +
                '<span>' + (typeof WFT === 'function' ? WFT('admin.offer_approval_requested_by', 'طلب بواسطة:') : 'طلب بواسطة:') + ' ' + escapeHtml(a.requested_by_name || '—') + '</span>' +
                '<span class="approval-meta-dot">•</span>' +
                '<span>' + (a.slide_count || 0) + ' ' + (typeof WFT === 'function' ? WFT('slides.count_unit', 'شريحة') : 'شريحة') + '</span>' +
                '<span class="approval-meta-dot">•</span>' +
                '<span dir="ltr">' + escapeHtml(a.created_at || '') + '</span>' +
              '</div>' +
            '</div>' +
            '<div class="approval-actions">' +
              '<button type="button" class="btn small primary" onclick="openExistingPresentation(&quot;' + a.presentation_id + '&quot;)">' + (typeof WFT === 'function' ? WFT('common.preview', 'معاينة') : 'معاينة') + '</button>' +
              (hasPermission('approvals')
                ? '<button type="button" class="btn small green" onclick="reviewApproval(&quot;' + a.id + '&quot;, &quot;approved&quot;)">' + (typeof WFT === 'function' ? WFT('common.approve', 'اعتماد') : 'اعتماد') + '</button>' +
                  '<button type="button" class="btn small danger" onclick="reviewApproval(&quot;' + a.id + '&quot;, &quot;rejected&quot;)">' + (typeof WFT === 'function' ? WFT('common.reject', 'رفض') : 'رفض') + '</button>'
                : '') +
            '</div>' +
          '</div>'
        ).join('');

        const genHtml = genApprovals.map(a =>
          '<div class="tenant-approval-card">' +
            '<div class="approval-main">' +
              '<div class="approval-header-line">' +
                '<h3 class="approval-title">' + escapeHtml(a.draft_title || 'طلب اعتماد توليد') + '</h3>' +
                '<span class="proposal-status-badge status-info">' + (typeof WFT === 'function' ? WFT('approvals.tier_one', 'المرحلة الأولى: اعتماد محتوى مولد') : 'المرحلة الأولى: اعتماد محتوى مولد') + '</span>' +
              '</div>' +
              '<div class="approval-meta">' +
                '<span>' + (a.section_key
                  ? (typeof WFT === 'function' ? WFT('admin.section_gen_approval', 'اعتماد توليد قسم «{section}»', {
                      section: escapeHtml((typeof PROJECT_SECTION_PRESENTATION_TITLES !== 'undefined' && PROJECT_SECTION_PRESENTATION_TITLES[a.section_key]) || a.section_key)
                    }) : (WFT('approvals.section_approval_prefix', 'اعتماد قسم: ') + a.section_key))
                  : (typeof WFT === 'function' ? WFT('admin.generation_start_approval', 'اعتماد بدء التوليد') : 'اعتماد بدء التوليد')) +
                  ' — ' + (typeof WFT === 'function' ? WFT('admin.requested_by_suffix', 'طلب بواسطة:') : 'طلب بواسطة:') + ' ' + escapeHtml(a.requested_by_name || '—') + '</span>' +
                '<span class="approval-meta-dot">•</span>' +
                '<span>' + formatUsageCost((Number(a.estimated_cost_usd) || 0) * 3.75) + '</span>' +
                '<span class="approval-meta-dot">•</span>' +
                '<span dir="ltr">' + escapeHtml((a.requested_at || '').slice(0, 16).replace('T', ' ')) + '</span>' +
              '</div>' +
            '</div>' +
            '<div class="approval-actions">' +
              (a.draft_id ? '<button type="button" class="btn small primary" onclick="openProjectDraftById(&quot;' + a.draft_id + '&quot;)">' + (typeof WFT === 'function' ? WFT('projects.open', 'فتح المشروع') : 'فتح المشروع') + '</button>' : '') +
              decideBtns('reviewGenerationApproval', a.id, a.requested_by, 'approve_generation') +
            '</div>' +
          '</div>'
        ).join('');

        const finHtml = finApprovals.map(a =>
          '<div class="tenant-approval-card">' +
            '<div class="approval-main">' +
              '<div class="approval-header-line">' +
                '<h3 class="approval-title">' + escapeHtml(a.presentation_title || 'طلب اعتماد ملف نهائي') + '</h3>' +
                '<span class="proposal-status-badge status-primary">' + (typeof WFT === 'function' ? WFT('approvals.tier_two_final', 'المرحلة الثانية: اعتماد ملف نهائي') : 'المرحلة الثانية: اعتماد ملف نهائي') + '</span>' +
              '</div>' +
              '<div class="approval-meta">' +
                '<span>' + (typeof WFT === 'function' ? WFT('admin.final_file_approval_requested_by', 'اعتماد الملف النهائي — طلب بواسطة:') : 'طلب بواسطة:') + ' ' + escapeHtml(a.requested_by_name || '—') + '</span>' +
                '<span class="approval-meta-dot">•</span>' +
                '<span dir="ltr">' + escapeHtml((a.requested_at || '').slice(0, 16).replace('T', ' ')) + '</span>' +
              '</div>' +
            '</div>' +
            '<div class="approval-actions">' +
              decideBtns('reviewFinalFileApproval', a.id, a.requested_by, 'approve_final_file') +
            '</div>' +
          '</div>'
        ).join('');

        pendingList.innerHTML = genHtml + finHtml + presHtml;
      }

      // 2. Render History View
      if (historyList) {
        const historyItems = [];
        histPres.forEach(p => {
          historyItems.push({
            type: 'presentation',
            title: p.pres_title || 'عرض تقديمي',
            status: p.status,
            reviewer: p.reviewed_by_name || p.approver_name || '—',
            date: p.reviewed_at || p.created_at || '',
            note: p.review_note || p.reviewer_notes || p.note || '',
            presentation_id: p.presentation_id,
            draft_id: p.draft_id
          });
        });
        histGen.forEach(g => {
          historyItems.push({
            type: 'generation',
            title: g.draft_title ? (g.draft_title + (g.section_key ? ' (' + g.section_key + ')' : '')) : WFT('approvals.generation_approval', 'اعتماد توليد'),
            status: g.status,
            reviewer: g.reviewed_by_name || g.approver_name || '—',
            date: g.reviewed_at || g.decided_at || g.requested_at || '',
            note: g.review_note || g.note || '',
            draft_id: g.draft_id
          });
        });
        histFin.forEach(f => {
          historyItems.push({
            type: 'final_file',
            title: f.presentation_title || WFT('approvals.final_file_approval', 'اعتماد ملف نهائي'),
            status: f.status,
            reviewer: f.reviewed_by_name || f.approver_name || '—',
            date: f.reviewed_at || f.decided_at || f.requested_at || '',
            note: f.review_note || f.note || '',
            presentation_id: f.presentation_id
          });
        });

        // Sort descending by date
        historyItems.sort((x, y) => (y.date || '').localeCompare(x.date || ''));

        if (historyItems.length === 0) {
          historyList.innerHTML = '<p class="tenant-hint" style="text-align:center;padding:36px">' +
            (typeof WFT === 'function' ? WFT('approvals.history_empty', 'لا يوجد سجل قرارات سابقة') : 'لا يوجد سجل قرارات سابقة') +
            '</p>';
        } else {
          historyList.innerHTML = historyItems.map(item => {
            const isApproved = item.status === 'approved';
            const badgeCls = isApproved ? 'status-approved' : 'status-danger';
            const badgeLabel = isApproved
              ? (typeof WFT === 'function' ? WFT('approvals.decision_approved', 'معتمد') : 'معتمد')
              : (typeof WFT === 'function' ? WFT('approvals.decision_rejected', 'مرفوض') : 'مرفوض');
            const reviewerPrefix = isApproved
              ? (typeof WFT === 'function' ? WFT('approvals.approved_by', 'اعتمد بواسطة:') : 'اعتمد بواسطة:')
              : (typeof WFT === 'function' ? WFT('approvals.rejected_by', 'رفض بواسطة:') : 'رفض بواسطة:');
            const noteHtml = item.note
              ? '<div class="approval-note-box">' + escapeHtml(item.note) + '</div>'
              : '';
            const actionBtn = item.presentation_id
              ? '<button type="button" class="btn small ghost" onclick="openExistingPresentation(&quot;' + item.presentation_id + '&quot;)">' + (typeof WFT === 'function' ? WFT('common.preview', 'معاينة') : 'معاينة') + '</button>'
              : (item.draft_id
                ? '<button type="button" class="btn small ghost" onclick="openProjectDraftById(&quot;' + item.draft_id + '&quot;)">' + (typeof WFT === 'function' ? WFT('projects.open', 'فتح المشروع') : 'فتح المشروع') + '</button>'
                : '');
            return '<div class="tenant-approval-card">' +
              '<div class="approval-main">' +
                '<div class="approval-header-line">' +
                  '<h3 class="approval-title">' + escapeHtml(item.title) + '</h3>' +
                  '<span class="proposal-status-badge ' + badgeCls + '">' + badgeLabel + '</span>' +
                '</div>' +
                '<div class="approval-meta">' +
                  '<span>' + reviewerPrefix + ' ' + escapeHtml(item.reviewer) + '</span>' +
                  '<span class="approval-meta-dot">•</span>' +
                  '<span dir="ltr">' + escapeHtml((item.date || '').slice(0, 16).replace('T', ' ')) + '</span>' +
                '</div>' +
                noteHtml +
              '</div>' +
              (actionBtn ? '<div class="approval-actions">' + actionBtn + '</div>' : '') +
            '</div>';
          }).join('');
        }
      }
    }

    async function reviewGenerationApproval(approvalId, decision) {
      const note = decision === 'rejected' ? prompt('سبب الرفض (اختياري):') || '' : '';
      const data = await api('POST', '/api/generation-approvals/' + approvalId + '/decision', { decision, note });
      if (data.success) { toast(decision === 'approved' ? 'تم اعتماد طلب التوليد' : 'تم رفض الطلب'); await loadApprovalsList(); }
      else { toast(data.error || 'فشل'); }
    }

    async function reviewFinalFileApproval(approvalId, decision) {
      const note = decision === 'rejected' ? prompt('سبب الرفض (اختياري):') || '' : '';
      const data = await api('POST', '/api/final-file-approvals/' + approvalId + '/decision', { decision, note });
      if (data.success) { toast(decision === 'approved' ? 'تم اعتماد الملف النهائي' : 'تم رفض الطلب'); await loadApprovalsList(); }
      else { toast(data.error || 'فشل'); }
    }

    async function reviewApproval(approvalId, status) {
      const note = status === 'rejected' ? prompt('سبب الرفض (اختياري):') || '' : '';
      const data = await api('POST', '/api/approvals/' + approvalId + '/review', { status, note });
      if (data.success) { toast(status === 'approved' ? 'تم اعتماد العرض' : 'تم رفض العرض'); await loadApprovalsList(); }
      else { toast(data.error || 'فشل'); }
    }

    async function requestPresentationApproval(presId) {
      const data = await api('POST', '/api/presentations/' + presId + '/request-approval');
      if (data.success) {
        tenantPresentationStatus = 'pending_approval';
        if (typeof renderSlidesHeader === 'function') renderSlidesHeader();
        toast('تم إرسال طلب التعميد');
      }
      else { toast(data.error || 'فشل'); }
    }

    // ── User Management ──
    async function openTenantUsers() {
      showTenantPage('tenantUsersPage');
      const list = document.getElementById('tenantUsersList');
      if (!list) return;
      showInlineLoader(list, WFT('common.loading', 'جاري التحميل...'));
      const [data, reportData] = await Promise.all([
        api('GET', '/api/users'),
        api('GET', '/api/users/report').catch(() => null)
      ]);
      if (!data.success || !data.users) { list.innerHTML = '<p>لا يوجد موظفين</p>'; return; }
      const counts = reportData?.report?.counts || {
        active: data.users.filter(u => u.is_active).length,
        invited: 0,
        disabled: data.users.filter(u => !u.is_active).length,
        total: data.users.length
      };
      const reportUsers = {};
      ((reportData && reportData.report && reportData.report.users) || []).forEach(u => { reportUsers[u.id] = u; });
      const reportBanner = '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:12px 16px;margin-bottom:14px;display:flex;gap:18px;align-items:center;flex-wrap:wrap;font-size:13px;">' +
        '<div style="font-weight:700;color:#1a3a52;">تقرير المستخدمين:</div>' +
        '<div><span>نشط:</span> <strong style="color:var(--green);">' + (counts.active || 0) + '</strong></div>' +
        '<div><span>مدعو:</span> <strong style="color:#2563eb;">' + (counts.invited || counts.pending_invites || 0) + '</strong></div>' +
        '<div><span>معطل:</span> <strong style="color:#c33;">' + (counts.disabled || 0) + '</strong></div>' +
        '<div><span>الإجمالي:</span> <strong>' + (counts.total || data.users.length) + '</strong></div>' +
        '<button type="button" class="btn small ghost" style="margin-right:auto;" onclick="showSodMatrixModal()">مصفوفة الفصل بين المهام</button>' +
        '</div>';
      const usersHtml = data.users.length ? data.users.map(u => {
        const reportUser = reportUsers[u.id] || {};
        const respLabels = (reportUser.responsibilities || [])
          .map(r => (ASSIGNMENT_ROLES.find(x => x.key === r) || {}).label || r);
        const roleLabel = u.is_primary ? WFT('role.company_admin', 'أدمن الشركة')
          : reportUser.admin_like ? 'أدمن'
          : respLabels.length ? respLabels.join('، ')
          : (USER_ROLE_LABELS[u.role] || 'موظف');
        const statusBadge = u.is_active ? '<span style="color:var(--green)">نشط</span>' : '<span style="color:#c33">معطل</span>';
        const lastLogin = reportUser.last_login_at
          ? ' | <span>' + escapeHtml(WFT('users.last_login', 'آخر دخول')) + ':</span> ' + escapeHtml(String(reportUser.last_login_at).slice(0, 16).replace('T', ' '))
          : '';
        // The primary row is the company's admin identity — it is managed
        // through the account itself, not employee permissions.
        const actions = u.is_primary ? '' :
          '<button class="btn small primary" onclick="openUserPermissionsModal(\'' + u.id + '\', \'' + escapeHtml(u.name) + '\')">صلاحيات</button>' +
          '<button class="btn small ghost" onclick="toggleUserActive(\'' + u.id + '\', ' + (u.is_active ? 0 : 1) + ')">' + (u.is_active ? 'تعطيل' : 'تفعيل') + '</button>' +
          '<button class="btn small danger" onclick="deleteTenantUser(\'' + u.id + '\', \'' + escapeHtml(u.name) + '\')">حذف</button>';
        return '<div class="tenant-presentation-card" style="margin-bottom:0">' +
          '<div><h3>' + escapeHtml(u.name) + '</h3><div class="meta">' + escapeHtml(u.email) + ' | <span>' + roleLabel + '</span> | ' + statusBadge + lastLogin + '</div></div>' +
          '<div class="tenant-actions" style="gap:6px">' + actions + '</div></div>';
      }).join('') : '<p class="tenant-hint">لم تتم إضافة موظفين بعد.</p>';
      list.innerHTML = reportBanner + usersHtml;
      renderTenantInvites((reportData && reportData.report && reportData.report.invites) || []);
      populateInviteScopePickers();
    }

    function renderTenantInvites(invites) {
      const box = document.getElementById('tenantInvitesList');
      if (!box) return;
      if (!invites.length) { box.innerHTML = ''; return; }
      const statusLabels = {
        sent: WFT('users.invite_sent', 'أرسلت'), failed: WFT('users.invite_failed', 'فشل الإرسال'),
        pending: WFT('users.invite_pending_status', 'قيد الإرسال'), queued: WFT('users.invite_pending_status', 'قيد الإرسال'),
      };
      box.innerHTML = '<h4 style="margin:8px 0;color:var(--p)">' + escapeHtml(WFT('users.invites_list', 'الدعوات')) + '</h4>' +
        invites.map(i => {
          const state = i.is_used ? '<span style="color:#1c7a2e">' + escapeHtml(WFT('users.invite_used', 'مقبولة')) + '</span>'
            : i.is_expired ? '<span style="color:#c33">' + escapeHtml(WFT('users.invite_expired', 'منتهية')) + '</span>'
            : '<span style="color:#2563eb">' + escapeHtml(WFT('users.invite_pending', 'معلقة')) + '</span>';
          const mail = i.email_status ? ' | <span>' + escapeHtml(WFT('users.invite_email_status', 'البريد')) + ':</span> ' + escapeHtml(statusLabels[i.email_status] || i.email_status) : '';
          const resend = (!i.is_used && !i.is_expired)
            ? '<button type="button" class="btn small ghost" onclick="resendTenantInvite(\'' + i.id + '\')">' + escapeHtml(WFT('users.invite_resend', 'إعادة الإرسال')) + '</button>'
            : '';
          const link = (!i.is_used && !i.is_expired && i.token)
            ? '<input type="text" readonly value="' + escapeHtml(window.location.origin + '/invite/' + i.token) + '" style="width:100%;font-size:12px;margin-top:6px" onclick="this.select()">'
            : '';
          return '<div class="tenant-presentation-card" style="margin-bottom:6px">' +
            '<div><h3 style="font-size:14px">' + escapeHtml(i.email) + '</h3>' +
            '<div class="meta">' + (i.name ? escapeHtml(i.name) + ' | ' : '') + escapeHtml(USER_ROLE_LABELS[i.role] || 'موظف') + ' | ' + state + mail + '</div>' + link + '</div>' +
            '<div class="tenant-actions" style="gap:6px">' + resend + '</div></div>';
        }).join('');
    }

    async function resendTenantInvite(inviteId) {
      const data = await api('POST', '/api/invites/' + inviteId + '/resend', {});
      if (data && data.success) {
        toast(data.emailSent ? WFT('users.invite_resent', 'أعيد إرسال الدعوة') : WFT('users.invite_resend_queued', 'سجلت إعادة الإرسال'));
        openTenantUsers();
      } else {
        toast((data && data.error) || WFT('common.error', 'حدث خطأ'));
      }
    }

    async function populateInviteScopePickers() {
      const projectsBox = document.getElementById('inviteProjectsPicker');
      if (!projectsBox) return;
      const projectsData = await api('GET', '/api/project-drafts').catch(() => null);
      if (projectsBox) {
        const drafts = (projectsData && (projectsData.drafts || projectsData.projects)) || [];
        projectsBox.innerHTML = drafts.map(d =>
          '<label style="display:flex;align-items:center;gap:4px;font-size:12px;background:#fff;border:1px solid var(--line);border-radius:8px;padding:4px 8px">' +
          '<input type="checkbox" class="inviteProjectCb" value="' + escapeHtml(d.id) + '">' + escapeHtml(d.title || d.id) + '</label>'
        ).join('') || '<span class="tenant-hint">' + escapeHtml(WFT('common.none', 'لا يوجد')) + '</span>';
      }
    }

