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
            toast('تم تنفيذ ' + successCount + ' إجراء بنجاح');
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
        el.style.borderColor = '#3B6E91';
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
        log.innerHTML = '<div style="text-align:center;padding:32px 20px;"><h3 style="margin:0 0 8px;color:var(--accent);">وكيل الإدارة الذكي</h3></div>';
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
            toast('تم تنفيذ ' + successCount + ' إجراء بنجاح');
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

    // ── Approvals ──
    async function openTenantApprovals() {
      showTenantPage('tenantApprovalsPage');
      await loadApprovalsList();
    }

    async function loadApprovalsList() {
      const list = document.getElementById('approvalsList');
      if (!list) return;
      showInlineLoader(list, 'جاري التحميل...');
      const data = await api('GET', '/api/approvals');
      const approvals = (data.success && data.approvals) ? data.approvals : [];
      if (!approvals.length) { list.innerHTML = '<p class="tenant-hint">لا توجد عروض في انتظار التعميد</p>'; return; }
      list.innerHTML = approvals.map(a =>
        '<div class="tenant-presentation-card">' +
        '<div><h3>' + escapeHtml(a.pres_title || 'عرض') + '</h3>' +
        '<div class="meta"><span>طلب بواسطة:</span> ' + escapeHtml(a.requested_by_name || '') + ' | <span>' + (a.slide_count || 0) + '</span> <span>شريحة</span> | ' + escapeHtml(a.created_at || '') + '</div></div>' +
        '<div class="tenant-actions">' +
        '<button class="btn small primary" onclick="openExistingPresentation(\'' + a.presentation_id + '\')">معاينة</button>' +
        '<button class="btn small green" onclick="reviewApproval(\'' + a.id + '\', \'approved\')">اعتماد</button>' +
        '<button class="btn small danger" onclick="reviewApproval(\'' + a.id + '\', \'rejected\')">رفض</button>' +
        '</div></div>'
      ).join('');
    }

    async function reviewApproval(approvalId, status) {
      const note = status === 'rejected' ? prompt('سبب الرفض (اختياري):') || '' : '';
      const data = await api('POST', '/api/approvals/' + approvalId + '/review', { status, note });
      if (data.success) { toast(status === 'approved' ? 'تم اعتماد العرض' : 'تم رفض العرض'); await loadApprovalsList(); }
      else { toast(data.error || 'فشل'); }
    }

    async function requestPresentationApproval(presId) {
      const data = await api('POST', '/api/presentations/' + presId + '/request-approval');
      if (data.success) { toast('تم إرسال طلب التعميد'); }
      else { toast(data.error || 'فشل'); }
    }

    // ── User Management ──
    async function openTenantUsers() {
      showTenantPage('tenantUsersPage');
      const list = document.getElementById('tenantUsersList');
      if (!list) return;
      showInlineLoader(list, 'جاري التحميل...');
      const data = await api('GET', '/api/users');
      if (!data.success || !data.users) { list.innerHTML = '<p>لا يوجد موظفين</p>'; return; }
      if (!data.users.length) { list.innerHTML = '<p class="tenant-hint">لم تتم إضافة موظفين بعد.</p>'; return; }
      list.innerHTML = data.users.map(u => {
        const roleLabel = u.role === 'company_admin' ? 'أدمن' : 'موظف';
        const statusBadge = u.is_active ? '<span style="color:var(--green)">نشط</span>' : '<span style="color:#c33">معطل</span>';
        return '<div class="tenant-presentation-card" style="margin-bottom:0">' +
          '<div><h3>' + escapeHtml(u.name) + '</h3><div class="meta">' + escapeHtml(u.email) + ' | <span>' + roleLabel + '</span> | ' + statusBadge + '</div></div>' +
          '<div class="tenant-actions" style="gap:6px">' +
          '<button class="btn small primary" onclick="openUserPermissionsModal(\'' + u.id + '\', \'' + escapeHtml(u.name) + '\')">صلاحيات</button>' +
          '<button class="btn small ghost" onclick="toggleUserActive(\'' + u.id + '\', ' + (u.is_active ? 0 : 1) + ')">' + (u.is_active ? 'تعطيل' : 'تفعيل') + '</button>' +
          '<button class="btn small danger" onclick="deleteTenantUser(\'' + u.id + '\', \'' + escapeHtml(u.name) + '\')">حذف</button>' +
          '</div></div>';
      }).join('');
    }

    async function addTenantUser() {
      const name = document.getElementById('newUserName').value.trim();
      const email = document.getElementById('newUserEmail').value.trim();
      const password = document.getElementById('newUserPassword').value;
      const role = document.getElementById('newUserRole').value;
      if (!name || !email || !password) { toast('كل الحقول مطلوبة'); return; }
      if (password.length < 6) { toast('كلمة المرور 6 أحرف على الأقل'); return; }
      const data = await api('POST', '/api/users', { name, email, password, role });
      if (data.success) {
        toast('تم إضافة الموظف');
        document.getElementById('newUserName').value = '';
        document.getElementById('newUserEmail').value = '';
        document.getElementById('newUserPassword').value = '';
        openTenantUsers();
      } else {
        toast(data.error || 'فشل إضافة الموظف');
      }
    }

    async function toggleUserActive(userId, isActive) {
      const data = await api('PUT', '/api/users/' + userId, { is_active: isActive });
      if (data.success) { toast(isActive ? 'تم التفعيل' : 'تم التعطيل'); openTenantUsers(); }
      else { toast(data.error || 'فشل'); }
    }

    async function deleteTenantUser(userId, userName) {
      if (!confirm('حذف الموظف: ' + userName + '؟')) return;
      const data = await api('DELETE', '/api/users/' + userId);
      if (data.success) { toast('تم الحذف'); openTenantUsers(); }
      else { toast(data.error || 'فشل الحذف'); }
    }

    let editingUserPermissions = null;
    const PERMISSION_LABELS = {
      dashboard: 'الرئيسية',
      create_presentation: 'إنشاء عرض جديد',
      view_presentations: 'عرض العروض السابقة',
      generate_images: 'توليد الصور',
      generate_maps: 'توليد الخرائط',
      company_settings: 'إعدادات الشركة',
      custom_fields: 'الحقول المخصصة',
      manage_users: 'إدارة الموظفين',
      ai_rules: 'قواعد AI',
      training_data: 'تدريب GLM',
      approvals: 'تعميد العروض',
      export_files: 'تصدير الملفات',
      sag_admin_panel: 'لوحة المدير العام',
    };

    async function openUserPermissionsModal(userId, userName) {
      const [permData, sectionData] = await Promise.all([
        api('GET', '/api/users/' + userId + '/permissions'),
        api('GET', '/api/users/' + userId + '/field-sections')
      ]);
      if (!permData.success || !sectionData.success) { toast('تعذر تحميل الصلاحيات'); return; }
      const perms = permData.permissions || {};
      const keys = permData.availableKeys || [];
      const sections = sectionData.sections || {};
      const availableSections = sectionData.available || [];
      editingUserPermissions = { userId, userName, availableSections };

      const permRows = keys.map(key => {
        const label = PERMISSION_LABELS[key] || key;
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + label + '</label>' +
          '<input type="checkbox" id="perm_' + key + '" ' + (perms[key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const sectionRows = availableSections.map(s => {
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + escapeHtml(s.label) + '</label>' +
          '<input type="checkbox" id="section_' + s.key + '" ' + (sections[s.key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const modal = document.createElement('div');
      modal.id = 'userPermissionsModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:24px;max-width:520px;width:100%;max-height:85vh;overflow:auto">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">' +
        '<h3><span>صلاحيات:</span> ' + escapeHtml(userName) + '</h3>' +
        '<button class="btn ghost" onclick="document.getElementById(\'userPermissionsModal\').remove()">إغلاق</button></div>' +
        '<h4 style="margin:12px 0 8px;color:var(--p)">صلاحيات التطبيق</h4>' +
        '' +
        permRows +
        '<h4 style="margin:20px 0 8px;color:var(--p)">أقسام فورم المشروع</h4>' +
        '' +
        sectionRows +
        '<div class="tenant-btns" style="margin-top:16px">' +
        '<button class="btn primary" onclick="saveUserPermissions()">حفظ الصلاحيات</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    async function saveUserPermissions() {
      if (!editingUserPermissions) return;
      const keys = Object.keys(PERMISSION_LABELS);
      const permissions = {};
      keys.forEach(key => {
        const cb = document.getElementById('perm_' + key);
        permissions[key] = cb ? cb.checked : false;
      });
      const sections = {};
      (editingUserPermissions.availableSections || []).forEach(s => {
        const cb = document.getElementById('section_' + s.key);
        sections[s.key] = cb ? cb.checked : false;
      });
      showLoader('جاري حفظ الصلاحيات', '');
      const [permRes, sectionRes] = await Promise.all([
        api('PUT', '/api/users/' + editingUserPermissions.userId + '/permissions', { permissions }),
        api('PUT', '/api/users/' + editingUserPermissions.userId + '/field-sections', { sections })
      ]);
      hideLoader();
      const modal = document.getElementById('userPermissionsModal');
      if (modal) modal.remove();
      if (permRes.success && sectionRes.success) { toast('تم حفظ الصلاحيات'); }
      else { toast(permRes.error || sectionRes.error || 'فشل الحفظ'); }
    }

    async function sendTenantInvite() {
      const email = document.getElementById('inviteEmail').value.trim();
      if (!email) { toast('أدخل بريد الموظف'); return; }
      const result = document.getElementById('inviteResult');
      showInlineLoader(result, 'جاري الإرسال...');
      const data = await api('POST', '/api/invites', { email });
      if (data.success) {
        const fullUrl = window.location.origin + data.inviteUrl;
        result.innerHTML = '<div style="background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:8px">' +
          '<p style="margin:0 0 8px"><strong>تم إنشاء الدعوة!</strong></p>' +
          '<p style="margin:0 0 8px" class="tenant-hint">شارك هذا الرابط مع الموظف (صالح لمدة 7 أيام):</p>' +
          '<input type="text" readonly value="' + fullUrl + '" style="width:100%;font-size:13px" onclick="this.select()">' +
          '</div>';
        document.getElementById('inviteEmail').value = '';
      } else {
        result.innerHTML = '<p style="color:#c33">' + (data.error || 'فشل') + '</p>';
      }
    }

    // ── Presentation Versions & Edit Log ──
    async function showPresentationVersions(presId) {
      if (!presId) { toast('لا توجد نسخة محفوظة لهذا العرض'); return; }
      document.getElementById('versionsModal')?.remove();
      const modal = document.createElement('div');
      modal.id = 'versionsModal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-label', 'سجل التعديلات والنسخ');
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,.65);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;direction:rtl';
      modal.innerHTML = '<div style="background:#fff;border-radius:18px;padding:24px;width:min(1180px,100%);max-height:92vh;overflow:auto">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;gap:16px"><h3 style="margin:0">سجل التعديلات والنسخ</h3>' +
        '<button class="btn ghost" id="closePresentationHistory">إغلاق</button></div>' +
        '<div id="presentationHistoryContent" aria-live="polite" style="margin-top:18px">جاري تحميل النسخ والسجل...</div></div>';
      document.body.appendChild(modal);
      modal.querySelector('#closePresentationHistory').onclick = () => { modal.remove(); tenantPresentationHistory = null; };
      const host = modal.querySelector('#presentationHistoryContent');
      try {
        const [versions, log] = await Promise.all([
          api('GET', '/api/presentations/' + encodeURIComponent(presId) + '/versions'),
          api('GET', '/api/presentations/' + encodeURIComponent(presId) + '/edit-log')
        ]);
        if (!versions?.success || !log?.success) throw new Error(versions?.error || log?.error || 'تعذر تحميل سجل العرض');
        if (!modal.isConnected) return;
        tenantPresentationHistory = { presId, revision: Number(versions.currentRevision) || 0,
          versions: versions.versions || [], log: log.log || [], previewRequest: 0 };
        const entries = tenantPresentationHistory.versions;
        host.innerHTML = '<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:16px">' +
          '<strong>النسخة الحالية: ' + tenantPresentationHistory.revision + '</strong>' +
          '<span class="tenant-hint">' + entries.length + ' نسخة محفوظة</span></div>' +
          '<div id="presentationRevisionPreview" hidden style="margin-bottom:24px;padding:16px;border:1px solid #cbd5e1;border-radius:12px"></div>' +
          (entries.length ? '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:12px">' + entries.map((v, index) => {
            const linked = tenantPresentationHistory.log.find(entry => entry.revision_id === v.id && entry.id === v.change_log_id);
            const source = v.source === 'ai' ? 'بمساعدة الذكاء الاصطناعي' : v.source === 'system' ? 'النظام' : 'يدوي';
            const title = v.snapshotKind === 'legacy-slides' || v.legacy ? 'نسخة قديمة للشرائح فقط' : 'النسخة ' + v.revision;
            return '<article style="padding:16px;border:1px solid #dbe2ea;border-radius:12px;background:#f8fafc">' +
              '<div style="display:flex;justify-content:space-between;gap:8px"><strong>' + escapeHtml(title) + '</strong>' +
              (Number(v.revision) === tenantPresentationHistory.revision && !v.legacy ? '<span>الحالية</span>' : '') + '</div>' +
              '<div style="margin-top:8px">' + escapeHtml(v.user_name || 'غير مسجل') + ' | ' + source + '</div>' +
              '<div class="meta" style="margin-top:4px">' + escapeHtml(String(v.created_at || '').replace('T', ' ').slice(0,19)) +
              ' | ' + (v.slide_count || 0) + ' شريحة</div>' +
              '<div style="margin-top:10px;line-height:1.8">' + escapeHtml(v.summary || linked?.summary || revisionActionLabel(v.action)) + '</div>' +
              ((v.details || linked?.details || []).slice(0, 5).map(line => '<div style="font-size:13px;line-height:1.8">' + escapeHtml(line) + '</div>').join('')) +
              '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">' +
              '<button class="btn small ghost" data-version-preview="' + index + '">معاينة ومقارنة</button>' +
              (hasPermission('create_presentation') ? '<button class="btn small ghost" data-version-restore="' + index + '">استعادة</button>' : '') + '</div></article>';
          }).join('') + '</div>' : '<p class="tenant-hint">لا توجد نسخ سابقة محفوظة.</p>') +
          '<h3 style="margin-top:28px">كل الأحداث</h3>' +
          (tenantPresentationHistory.log.length ? tenantPresentationHistory.log.map(renderChangeLogEntry).join('') : '<p class="tenant-hint">لا توجد أحداث مسجلة.</p>');
        host.querySelectorAll('[data-version-preview]').forEach(button => {
          button.onclick = () => previewPresentationVersion(presId, entries[Number(button.dataset.versionPreview)].id, button);
        });
        host.querySelectorAll('[data-version-restore]').forEach(button => {
          button.onclick = () => restoreVersion(presId, entries[Number(button.dataset.versionRestore)].id, button);
        });
      } catch (error) {
        host.textContent = error.message || 'تعذر تحميل سجل العرض';
      }
    }

    function revisionActionLabel(action) {
      return ({ create: 'إنشاء العرض', edit: 'تعديل العرض', restore: 'استعادة نسخة سابقة',
        baseline: 'الحالة السابقة قبل تفعيل سجل النسخ', generation: 'توليد العرض' })[action] || action || 'حفظ العرض';
    }

    function revisionPreviewFrame(host, slide, projectData) {
      host.replaceChildren();
      if (!slide) { host.textContent = 'لا توجد شريحة في هذه النسخة'; return; }
      const frame = document.createElement('iframe');
      frame.title = slide.title || 'معاينة شريحة محفوظة';
      frame.setAttribute('sandbox', '');
      frame.style.cssText = 'width:1280px;height:720px;border:0;transform-origin:top left;position:absolute;left:0;top:0;pointer-events:none;background:white';
      const fontCss = projectData?._presentation_font_css || document.getElementById('tenantFontCss')?.textContent || '';
      frame.srcdoc = '<!doctype html><html dir="rtl"><head><meta charset="utf-8">' +
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src https: http: data:; font-src https: http: data:; style-src \'unsafe-inline\' https:; script-src \'none\'; form-action \'none\'; base-uri ' + window.location.origin + '">' +
        '<base href="' + escapeHtml(window.location.origin + '/') + '"><style>html,body{margin:0;width:1280px;height:720px;overflow:hidden}*{box-sizing:border-box}' +
        fontCss.replace(/<\/style/gi, '') + '</style></head><body>' + String(slide.html || '') + '</body></html>';
      host.style.cssText = 'position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;background:#e2e8f0;border:1px solid #cbd5e1;border-radius:8px';
      host.appendChild(frame);
      const resize = () => { frame.style.transform = 'scale(' + host.clientWidth / 1280 + ')'; };
      resize();
      const observer = new ResizeObserver(() => {
        if (!host.isConnected) observer.disconnect();
        else resize();
      });
      observer.observe(host);
    }

    async function previewPresentationVersion(presId, versionId, button) {
      const context = tenantPresentationHistory;
      const host = document.getElementById('presentationRevisionPreview');
      if (!context || context.presId !== presId || !host) return;
      const request = ++context.previewRequest;
      host.hidden = false;
      host.textContent = 'جاري تحميل المعاينة والمقارنة...';
      if (button) button.disabled = true;
      try {
        const prefix = '/api/presentations/' + encodeURIComponent(presId);
        const [detail, current, comparison] = await Promise.all([
          api('GET', prefix + '/versions/' + encodeURIComponent(versionId)),
          api('GET', prefix),
          api('GET', prefix + '/versions/compare?from=' + encodeURIComponent(versionId) + '&to=current')
        ]);
        if (!detail?.success || !current?.success || !comparison?.success) throw new Error('تعذر تحميل المعاينة');
        if (tenantPresentationHistory !== context || context.previewRequest !== request) return;
        const snapshot = detail.version.snapshot;
        const latest = current.presentation;
        const count = Math.max(snapshot.slidesData?.length || 0, latest.slidesData?.length || 0);
        host.innerHTML = '<div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap"><h3>مقارنة النسخ</h3>' +
          '<label>الشريحة <select id="revisionPreviewSlide">' + Array.from({ length: count }, (_, i) => '<option value="' + i + '">' + (i + 1) + '</option>').join('') + '</select></label></div>' +
          '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:16px;margin-top:12px">' +
          '<div><h4>النسخة المحددة</h4><div id="revisionBeforeFrame"></div></div>' +
          '<div><h4>النسخة الحالية المحفوظة</h4><div id="revisionAfterFrame"></div></div></div>' +
          '<div style="margin-top:16px;line-height:1.9">' + (comparison.changes?.length
            ? comparison.changes.map(line => '<div>' + escapeHtml(line) + '</div>').join('') : 'لا توجد اختلافات في المحتوى') + '</div>';
        const render = () => {
          const index = Number(host.querySelector('#revisionPreviewSlide').value) || 0;
          revisionPreviewFrame(host.querySelector('#revisionBeforeFrame'), snapshot.slidesData?.[index], snapshot.projectData);
          revisionPreviewFrame(host.querySelector('#revisionAfterFrame'), latest.slidesData?.[index], latest.projectData);
        };
        host.querySelector('#revisionPreviewSlide').onchange = render;
        render();
        host.scrollIntoView({ block: 'nearest' });
      } catch (error) { if (context.previewRequest === request) host.textContent = error.message; }
      finally { if (button) button.disabled = false; }
    }

    async function restoreVersion(presId, versionId, button) {
      if (tenantPresentationSavePromise || isGeneratingTenantSlides) { toast('العرض قيد الحفظ أو التوليد'); return; }
      if (!confirm('استعادة هذه النسخة كنسخة جديدة؟ النسخ المحفوظة الحالية ستبقى في السجل.')) return;
      const context = tenantPresentationHistory;
      if (!context || context.presId !== presId) return;
      if (button) { button.disabled = true; button.textContent = 'جاري الاستعادة...'; }
      try {
        let expectedRevision = context.revision;
        if (tenantPresentationId === presId && tenantSlidesData.length) {
          const saved = await saveTenantPresentation();
          if (!saved) return;
          expectedRevision = tenantPresentationRevision;
        }
        const data = await api('POST', '/api/presentations/' + encodeURIComponent(presId) + '/versions/' + encodeURIComponent(versionId) + '/restore', { expectedRevision });
        if (!data?.success) throw new Error(data?.error_code === 'PRESENTATION_REVISION_CONFLICT'
          ? 'ظهرت نسخة أحدث للعرض. لم يتم استبدالها.' : data?.error || 'تعذر الاستعادة');
        tenantArchiveCache = null;
        if (tenantPresentationId === presId) await openExistingPresentation(presId);
        toast('تمت استعادة العرض كنسخة جديدة، وبقيت بيانات المشروع دون تغيير');
        await showPresentationVersions(presId);
      } catch (error) { toast(error.message || 'تعذر الاستعادة'); }
      finally { if (button) { button.disabled = false; button.textContent = 'استعادة'; } }
    }

    // Every entry names its author, whether it was done by hand or by the AI, and the individual
    // differences it produced. It used to read «تعديل نصي» with nothing behind it.
    function renderChangeLogEntry(entry) {
      const source = entry.source === 'ai' ? 'الذكاء الاصطناعي' : entry.source === 'system' ? 'النظام' : 'يدوي';
      const lines = Array.isArray(entry.details) ? entry.details : [];
      const stamp = String(entry.created_at || '').slice(0, 19).replace('T', ' ');
      return '<div style="padding:12px 0;border-bottom:1px solid var(--line)">' +
        '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' +
        '<strong>' + escapeHtml(entry.user_name || 'نظام') + '</strong>' +
        '<span class="tenant-hint">' + escapeHtml(entry.action || '') + '</span>' +
        '<span style="font-size:11px;padding:2px 8px;border-radius:10px;background:' +
        (entry.source === 'ai' ? '#eef5fb;color:#123B6D' : '#f1f5f9;color:#475569') + '">' +
        source + '</span></div>' +
        (entry.summary ? '<div style="margin-top:4px">' + escapeHtml(entry.summary) + '</div>' : '') +
        (lines.length
          ? '<ul style="margin:6px 0 0;padding-inline-start:18px;font-size:13px;line-height:1.9">' +
          lines.map(line => '<li>' + escapeHtml(line) + '</li>').join('') + '</ul>'
          : '') +
        '<div class="meta" style="margin-top:4px">' + escapeHtml(stamp) + '</div></div>';
    }

    async function showEditLog(presId) {
      return showPresentationVersions(presId);
    }

    async function showDraftEditLog(draftId) {
      const data = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId) + '/edit-log');
      if (!data.success) { toast(data.error || 'فشل تحميل السجل'); return; }
      if (!data.log.length) { toast('لا يوجد سجل تعديلات لهذه المسودة'); return; }
      const existing = document.getElementById('editLogModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'editLogModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:24px;max-width:600px;width:100%;max-height:80vh;overflow:auto">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">' +
        '<h3>سجل تعديلات المشروع</h3><button class="btn ghost" onclick="this.closest(\'#editLogModal\').remove()">إغلاق</button></div>' +
        data.log.map(renderChangeLogEntry).join('') + '</div>';
      document.body.appendChild(modal);
    }

    function initTenant() {
      initScrollSpy();
      const path = window.location.pathname;
      const passwordSetupMatch = path.match(/^\/set-password\/(.+)$/);
      if (passwordSetupMatch) {
        showPasswordSetupPage(passwordSetupMatch[1]);
        initGlobalRail();
        return;
      }
      const token = getTenantToken();
      if (token) {
        bootstrapTenant();
      } else {
        const inviteMatch = path.match(/^\/invite\/(.+)$/);
        if (inviteMatch) {
          showInvitePage(inviteMatch[1]);
        } else {
          showAuthPage();
        }
      }
      initGlobalRail();
    }

    async function showPasswordSetupPage(rawToken) {
      const data = await api('GET', '/api/auth/password-setup/' + encodeURIComponent(rawToken));
      const authPage = document.getElementById('tenantAuthPage');
      document.getElementById('tenantAppPage').classList.remove('active');
      authPage.classList.add('active');
      if (!data.success) {
        authPage.innerHTML = '<div class="auth-card"><h2>رابط كلمة المرور غير صالح</h2>' +
          '<p>انتهت صلاحية الرابط أو تم استخدامه.</p>' +
          '<button class="auth-btn" onclick="window.location.href=\'/\'">العودة لتسجيل الدخول</button></div>';
        return;
      }
      authPage.innerHTML = '<div class="auth-card">' +
        '<h2>تعيين كلمة المرور</h2>' +
        '<p>' + escapeHtml(data.companyName || '') + '</p>' +
        '<div class="tenant-grid full" style="margin-bottom:16px;text-align:right">' +
        '<div class="tenant-field"><label>اسم المستخدم</label><p style="margin:0">' +
        escapeHtml(data.username || '') + '</p></div></div>' +
        '<div id="passwordSetupError" class="auth-error"></div>' +
        '<form class="auth-form active" onsubmit="handlePasswordSetup(event, \'' +
        rawToken.replace(/'/g, '') + '\')">' +
        '<label>كلمة المرور الجديدة</label>' +
        '<div style="position:relative;margin-bottom:12px">' +
        '<input type="password" id="passwordSetupValue" minlength="10" autocomplete="new-password" required style="padding-left:70px;margin-bottom:0">' +
        '<button type="button" onclick="togglePasswordSetupVisibility(\'passwordSetupValue\', this)" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--p);font-weight:800;font-size:13px;font-family:inherit;cursor:pointer;padding:4px 6px">إظهار</button></div>' +
        '<label>تأكيد كلمة المرور</label>' +
        '<div style="position:relative">' +
        '<input type="password" id="passwordSetupConfirm" minlength="10" autocomplete="new-password" required style="padding-left:70px;margin-bottom:0">' +
        '<button type="button" onclick="togglePasswordSetupVisibility(\'passwordSetupConfirm\', this)" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--p);font-weight:800;font-size:13px;font-family:inherit;cursor:pointer;padding:4px 6px">إظهار</button></div>' +
        '<button type="submit" class="auth-btn">اعتماد كلمة المرور</button>' +
        '</form></div>';
    }

    function togglePasswordVisibility(inputId, btn) {
      const input = document.getElementById(inputId);
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      if (btn) btn.textContent = show ? 'إخفاء' : 'إظهار';
    }

    function togglePasswordSetupVisibility(inputId, btn) {
      togglePasswordVisibility(inputId, btn);
    }

    async function handlePasswordSetup(event, rawToken) {
      event.preventDefault();
      const password = document.getElementById('passwordSetupValue').value;
      const confirmation = document.getElementById('passwordSetupConfirm').value;
      const errorHost = document.getElementById('passwordSetupError');
      errorHost.textContent = '';
      if (password !== confirmation) {
        errorHost.textContent = 'كلمتا المرور غير متطابقتين';
        return;
      }
      const data = await api(
        'POST',
        '/api/auth/password-setup/' + encodeURIComponent(rawToken),
        { password }
      );
      if (!data.success || !data.token) {
        errorHost.textContent = data.error || 'تعذر اعتماد كلمة المرور';
        return;
      }
      setTenantToken(data.token);
      setTenantUser(data.tenant);
      try {
        tenantUser = data.tenant;
        const next = (typeof tenantCanonicalRoute === 'function' && tenantCanonicalRoute('tenantDashboardPage')) || '/app/dashboard';
        window.history.replaceState({}, '', next);
      } catch (e) { window.history.replaceState({}, '', '/app/dashboard'); }
      await bootstrapTenant();
    }

    async function showInvitePage(inviteToken) {
      const data = await api('GET', '/api/invite/' + inviteToken);
      const authPage = document.getElementById('tenantAuthPage');
      if (!data.success) {
        authPage.innerHTML = '<div class="auth-card"><h2>الدعوة غير صالحة</h2><p>رابط الدعوة منتهي أو مستخدم بالفعل.</p><button class="auth-btn" onclick="window.location.href=\'/\'">العودة للرئيسية</button></div>';
        authPage.style.display = 'flex';
        return;
      }
      authPage.innerHTML = '<div class="auth-card">' +
        '<h2>دعوة انضمام للشركة</h2>' +
        '<p>تمت دعوتك للانضمام لـ <strong>' + escapeHtml(data.companyName) + '</strong></p>' +
        '<p class="tenant-hint">البريد: ' + escapeHtml(data.email) + '</p>' +
        '<div id="inviteError" class="auth-error"></div>' +
        '<form class="auth-form active" onsubmit="handleInviteRegister(event, \'' + inviteToken + '\')">' +
        '<label>الاسم الكامل *</label>' +
        '<input type="text" id="inviteName" placeholder="اسمك الكامل" required>' +
        '<label>كلمة المرور (6 أحرف على الأقل) *</label>' +
        '<div style="position:relative">' +
        '<input type="password" id="invitePassword" placeholder="كلمة المرور" required minlength="6" style="padding-left:64px">' +
        '<button type="button" onclick="togglePasswordVisibility(\'invitePassword\', this)" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--p);font-weight:800;font-size:13px;font-family:inherit;cursor:pointer;padding:4px 6px">إظهار</button></div>' +
        '<button type="submit" class="auth-btn">إنشاء حسابي</button>' +
        '</form></div>';
      authPage.style.display = 'flex';
    }

    async function handleInviteRegister(e, inviteToken) {
      e.preventDefault();
      const name = document.getElementById('inviteName').value.trim();
      const password = document.getElementById('invitePassword').value;
      showTenantError('inviteError', '');
      const data = await api('POST', '/api/invite/' + inviteToken + '/register', { name, password });
      if (data.success && data.token) {
        setTenantToken(data.token);
        setTenantUser(data.tenant);
        window.history.replaceState({}, '', '/');
        await bootstrapTenant();
      } else {
        showTenantError('inviteError', data.error || 'فشل إنشاء الحساب');
      }
    }

    initTenant();