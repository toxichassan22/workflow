    function applyTenantDesignerChatResult(data, message, input = null) {
      const reply = data && data.data ? data.data : null;
      if (!data?.success || !reply) {
        tenantDesignerMessages.push({
          role: 'assistant',
          content: (data && data.error) || 'تعذر تنفيذ الطلب. لم يتم تغيير العرض.'
        });
        tenantProjectData.designerChat = designerChatPersistence();
        renderTenantDesignerChat();
        triggerAutoSaveDraft();
        return false;
      }

      applyDesignerChatHistory(reply);
      applyDesignerChatMemory(reply);

      // The designer asked instead of guessing: show the question, change nothing, keep the answer
      // in the input's turn. Guessing and then editing wrongly is worse than one question.
      if (reply.action === 'ask' || reply.action === 'chat_only') {
        if (!Array.isArray(reply.chatHistory)) {
          tenantDesignerMessages.push({
            role: 'assistant',
            content: reply.response || 'تعذر تحديد التعديل دون معلومات إضافية.',
            slides: tenantChatFocusIndexes.slice()
          });
        }
        tenantProjectData.designerChat = designerChatPersistence();
        renderTenantDesignerChat();
        triggerAutoSaveDraft();
        if (input) input.focus();
        return true;
      }

      checkpointPresentationUndo();
      const undoSlidesBefore = JSON.stringify(tenantSlidesData);
      // The executor owns structural positions; do not reinterpret the message
      // and move its last slide a second time after applying the returned workspace.
      if (reply.action === 'add_slide' || reply.action === 'insert_slide') {
        const insertAfter = reply.insertAfterIndex !== undefined ? Number(reply.insertAfterIndex) : (tenantChatSlideIndex + 1);
        const insertIdx = Math.max(0, Math.min(insertAfter, tenantSlidesData.length));
        const newSlide = {
          title: reply.title || 'شريحة جديدة',
          html: reply.html,
          type: reply.type || 'content',
          section_key: reply.sectionKey || reply.section_key || '',
          content_source: reply.contentSource || reply.content_source || ''
        };
        tenantSlidesData.splice(insertIdx, 0, newSlide);
        // New slides start without a watermark; the user enables it per
        // slide from the edit toolbar or the designer chat.
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        selectTenantSlide(insertIdx);
      } else if (Array.isArray(reply.slidesData)) {
        const oldLength = tenantSlidesData.length;
        // Guard against a model reply that silently drops slides: entries without a
        // slide root would render as broken cards, and a shorter deck without a delete
        // request means slides were lost. Neither is applied quietly.
        const incoming = reply.slidesData.filter(item => item && typeof item.html === 'string' && containsSlideRoot(item.html));
        const deleteIntent = Array.isArray(reply.actions) && reply.actions.some(action =>
          action?.status === 'success' && ['delete_slide', 'remove_slide', 'merge_slides', 'combine_slides'].includes(action.tool));
        if (!incoming.length || incoming.length !== reply.slidesData.length) {
          tenantDesignerMessages.push({
            role: 'assistant',
            content: 'تعذر تنفيذ الطلب. لم يتم تغيير العرض.',
            slides: tenantChatFocusIndexes.slice()
          });
          tenantProjectData.designerChat = designerChatPersistence();
          renderTenantDesignerChat();
          triggerAutoSaveDraft();
          return false;
        }
        if (incoming.length < oldLength && !deleteIntent) {
          tenantDesignerMessages.push({
            role: 'assistant',
            content: 'لم يتم تطبيق التعديل لأن النتيجة أسقطت ' + (oldLength - incoming.length) + ' من ' + oldLength + ' شريحة.',
            slides: tenantChatFocusIndexes.slice()
          });
          tenantProjectData.designerChat = designerChatPersistence();
          renderTenantDesignerChat();
          triggerAutoSaveDraft();
          return false;
        }
        tenantSlidesData = incoming;
        if (tenantSlidesData.length < oldLength) {
          activeSlideIndex = Math.max(0, Math.min(activeSlideIndex, tenantSlidesData.length - 1));
          tenantChatSlideIndex = Math.max(0, Math.min(tenantChatSlideIndex, tenantSlidesData.length - 1));
        }
      }

      if (JSON.stringify(tenantSlidesData) !== undoSlidesBefore && typeof tenantPresentationProvenance !== 'undefined') {
        tenantPresentationProvenance = data.provenance || reply.provenance || tenantPresentationProvenance;
      }
      if (reply.creativeImages && typeof reply.creativeImages === 'object') {
        tenantCreativeImages = reply.creativeImages;
        tenantProjectData = { ...tenantProjectData, tenantCreativeImages };
      }
      if (!Array.isArray(reply.chatHistory)) {
        tenantDesignerMessages.push({
          role: 'assistant',
          content: reply.response || 'تم تنفيذ الطلب وتحديث العرض.',
          slides: tenantChatFocusIndexes.slice()
        });
      }
      tenantProjectData.designerChat = designerChatPersistence();
      if (!Array.isArray(reply.slidesData)) renumberTenantSlides();
      tenantProjectData.tenantSlidesData = tenantSlidesData;
      renderTenantSlides();
      renderTenantDesignerChat();
      triggerAutoSaveDraft();
      checkpointPresentationUndo();
      return true;
    }

    async function resumeTenantDesignerChatJob() {
      const workspaceKey = designerChatWorkspaceKey();
      if (tenantDesignerChatBusy?.workspaceKey && tenantDesignerChatBusy.workspaceKey !== workspaceKey) {
        clearDesignerChatBusy(tenantDesignerChatBusy.workspaceKey);
      }
      const job = currentTenantDesignerJob();
      if (!job || !tenantDesignerJobMatchesWorkspace(job)) return;
      if (tenantDesignerChatBusy?.workspaceKey === workspaceKey) return;
      if (tenantDesignerJobPollPromise?.workspaceKey === workspaceKey) return;

      const lastTurn = tenantDesignerMessages[tenantDesignerMessages.length - 1];
      if (job.message && (!lastTurn || lastTurn.role !== 'user' || lastTurn.content !== job.message)) {
        tenantDesignerMessages.push({ role: 'user', content: job.message, slides: [] });
        tenantProjectData.designerChat = designerChatPersistence();
        triggerAutoSaveDraft();
      }
      const resumeJob = {
        ...job,
        workspaceSignature: designerChatWorkspaceSignature(),
        updatedAt: Date.now()
      };
      persistTenantDesignerJob(resumeJob);
      setDesignerChatBusy('جاري استعادة مهمة تعديل العرض...', workspaceKey);
      renderTenantDesignerChat();
      restoreDesignerChatBusyIndicator();
      const indicator = document.getElementById('tenantChatTypingIndicator');
      const input = document.getElementById('tenantChatInput');
      const recoveryPayload = resumeJob.hadAttachment ? null : {
        message: resumeJob.message,
        target: resumeJob.target || 'auto',
        scope: resumeJob.scope || resumeJob.target || 'auto',
        indexes: Array.isArray(resumeJob.indexes) ? resumeJob.indexes : [],
        history: tenantDesignerMessages.slice(0, -1).slice(-DESIGNER_CHAT_HISTORY_KEPT).map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content || '').slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })),
        memory: tenantDesignerChatMemory,
        focusIndexes: tenantChatFocusIndexes,
        slideIndex: Number(resumeJob.slideIndex || 0),
        presentationId: resumeJob.presentationId || tenantPresentationId,
        projectData: buildDesignerChatProjectData(tenantProjectData),
        creativeImages: buildPresentationGenerationImages()
      };
      if (recoveryPayload && (tenantDraftDirty || !recoveryPayload.presentationId)) {
        recoveryPayload.slideHtml = tenantSlidesData[recoveryPayload.slideIndex]?.html || '';
        recoveryPayload.slideTitle = tenantSlidesData[recoveryPayload.slideIndex]?.title || '';
        recoveryPayload.slidesData = tenantSlidesData;
        recoveryPayload.slidePlan = tenantSlidePlan;
      }
      const promise = requestTenantDesignerChat(recoveryPayload, indicator, resumeJob);
      const pollRecord = { workspaceKey, promise };
      tenantDesignerJobPollPromise = pollRecord;
      try {
        const data = await promise;
        if (!tenantDesignerJobMatchesWorkspace(resumeJob)) return;
        if (!tenantDesignerJobCanApply(resumeJob)) {
          applyTenantDesignerChatResult({
            success: false,
            status: 'failed',
            error: 'لم تُطبق النتيجة لأن العرض تغير أثناء تنفيذ المهمة.'
          }, resumeJob.message, input);
          clearTenantDesignerJob(resumeJob);
          return;
        }
        applyTenantDesignerChatResult(data, resumeJob.message, input);
        if (isTerminalDesignerChatJob(data)) clearTenantDesignerJob(resumeJob);
      } catch (error) {
        if (tenantDesignerJobMatchesWorkspace(job)) {
          applyTenantDesignerChatResult({
            success: false,
            status: 'waiting',
            error: error?.message || 'تعذر استعادة نتيجة تعديل العرض مؤقتًا.'
          }, resumeJob.message, input);
        }
      } finally {
        if (tenantDesignerJobPollPromise === pollRecord) tenantDesignerJobPollPromise = null;
        clearDesignerChatBusy(workspaceKey);
      }
    }

    async function sendTenantDesignerChat() {
      const input = document.getElementById('tenantChatInput');
      const message = input ? input.value.trim() : '';
      const attachedImage = tenantChatAttachedImage;
      const attachedGallery = (tenantChatAttachedImages.length ? tenantChatAttachedImages : (attachedImage ? [attachedImage] : []))
        .filter(item => item && String(item.dataUri || '').startsWith('data:image/'))
        .slice(0, TENANT_CHAT_MAX_IMAGES);
      if (!message) { toast('التعديل المطلوب فارغ'); return; }
      if (!tenantSlidesData.length && !tenantPresentationId) {
        toast('لا يوجد عرض مفتوح للتعديل');
        return;
      }

      const activeJob = currentTenantDesignerJob();
      if (activeJob) {
        void resumeTenantDesignerChatJob();
        return;
      }
      if (tenantDesignerChatBusy) return;
      let requestWorkspaceKey = designerChatWorkspaceKey();
      setDesignerChatBusy('جاري تجهيز بيانات المشروع...', requestWorkspaceKey);
      try {
        if (typeof collectTenantFormData === 'function' && document.getElementById('tenantProjectForm')) {
          const currentFormData = await collectTenantFormData();
          tenantProjectData = { ...tenantProjectData, ...currentFormData };
        }
      } catch (error) {
        clearDesignerChatBusy(requestWorkspaceKey);
        toast(error?.message || 'تعذر تجهيز بيانات المشروع الحالية.');
        return;
      }
      requestWorkspaceKey = designerChatWorkspaceKey();
      if (tenantDesignerChatBusy) tenantDesignerChatBusy.workspaceKey = requestWorkspaceKey;
      // Send the untouched message and conversation. A number is not a client-side
      // command, and even a slide reference does not authorize an edit or navigation.
      const targetScope = tenantChatSlideScope === 'all' ? 'all' : 'auto';
      const target1BasedIndexes = [];

      tenantDesignerMessages.push({
        role: 'user',
        content: message,
        image: attachedImage ? attachedImage.dataUri : '',
        images: attachedGallery.map(item => item.dataUri),
        slides: target1BasedIndexes
      });
      if (input) { input.value = ''; growTenantChatInput(input); }
      clearTenantChatAttachment();
      tenantProjectData.designerChat = designerChatPersistence();
      renderTenantDesignerChat();
      triggerAutoSaveDraft();

      const messagesDiv = document.getElementById('tenantChatMessages');
      updateDesignerChatBusy(5, 'جاري تجهيز الطلب...');
      restoreDesignerChatBusyIndicator();
      const indicator = document.getElementById('tenantChatTypingIndicator');
      if (messagesDiv) messagesDiv.scrollTop = messagesDiv.scrollHeight;

      // The turn carries the conversation behind it: recent turns verbatim and the older ones as
      // the memory the server compressed. A dirty workspace also carries its current slides so
      // multiple unsaved chat edits build on one another instead of reverting to the saved deck.
      const chatPayload = {
        message,
        target: targetScope,
        scope: targetScope,
        indexes: target1BasedIndexes,
        history: tenantDesignerMessages.slice(0, -1).slice(-DESIGNER_CHAT_HISTORY_KEPT).map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content || '').slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })),
        memory: tenantDesignerChatMemory,
        focusIndexes: tenantChatFocusIndexes,
        slideIndex: tenantChatSlideIndex,
        presentationId: tenantPresentationId,
        projectData: buildDesignerChatProjectData(tenantProjectData),
        creativeImages: buildPresentationGenerationImages(),
        attachedImage: attachedImage ? attachedImage.dataUri : '',
        attachedImages: attachedGallery.map(item => item.dataUri)
      };
      // Once the workspace is dirty, send the in-memory copy as the source for the next turn.
      // The server must not reload the last saved presentation and discard an earlier unsaved
      // change made in this same chat session.
      if (tenantDraftDirty || !tenantPresentationId) {
        chatPayload.slideHtml = tenantSlidesData[tenantChatSlideIndex]?.html || '';
        chatPayload.slideTitle = tenantSlidesData[tenantChatSlideIndex]?.title || '';
        chatPayload.slidesData = tenantSlidesData;
        chatPayload.slidePlan = tenantSlidePlan;
      }
      let data = null;
      try {
        data = await requestTenantDesignerChat(chatPayload, indicator);
      } catch (error) {
        data = { success: false, status: 'waiting', error: error?.message || 'تعذر تنفيذ الطلب.' };
      } finally {
        clearDesignerChatBusy(requestWorkspaceKey);
      }

      const job = data?._designerJob || null;
      if (data?.status === 'superseded') {
        applyTenantDesignerChatResult(data, message, input);
        return;
      }
      if (job && !tenantDesignerJobMatchesWorkspace(job)) return;
      if (job && !tenantDesignerJobCanApply(job)) {
        applyTenantDesignerChatResult({
          success: false,
          status: 'failed',
          error: 'لم تُطبق النتيجة لأن العرض تغير أثناء تنفيذ المهمة.'
        }, message, input);
        clearTenantDesignerJob(job);
        return;
      }
      applyTenantDesignerChatResult(data, message, input);
      if (job && isTerminalDesignerChatJob(data)) clearTenantDesignerJob(job);
    }

    async function renderPresentationFontStatus() {
      const line = document.getElementById('presentationFontStatus');
      if (!line) return;
      const data = await api('GET', '/api/branding/font-status');
      const status = (data && data.status) || null;
      if (!status) { line.textContent = ''; return; }
      const scripts = status.scripts || {};
      const label = key => {
        const item = scripts[key] || {};
        return (item.font || trDynamicI18n('الافتراضي')) + (item.chosen ? '' : ' ' + trDynamicI18n('(افتراضي)'));
      };
      const renders = {
        'embedded file': 'ملف خط مضمّن مع العرض',
        'served file': 'ملف خط من الخادم',
        'google web font': 'خط ويب من Google — يحتاج اتصالًا',
        'installed name only': 'اسم خط فقط — لا يظهر إلا على جهاز مثبَّت عليه',
        'installed name only with shipped fallback':
          'خط نظام — يظهر على الأجهزة المثبَّت عليها، والعربي له خط مضمّن بديل في التصدير',
        'nothing': 'لا يوجد خط'
      }[status.renders] || status.renders;
      const arabic = label('arabic');
      const latin = label('latin');
      line.innerHTML = (arabic === latin ? '<span>المطبَّق الآن:</span> ' + escapeHtml(arabic)
        : '<span>المطبَّق الآن</span> — <span>عربي:</span> ' + escapeHtml(arabic) + ' | <span>لاتيني:</span> ' + escapeHtml(latin)) +
        ' | <span>' + escapeHtml(renders) + '</span>';
      refreshDynamicI18n(line);
    }
    document.addEventListener('wf:lang', () => { try { renderPresentationFontStatus(); } catch (e) { /* ignore */ } });

    // One entry per family: the weights of a family are applied together, so listing each weight as
    // its own choice only invited picking half a font.
    function presentationFontFamilies(data) {
      const available = (data.available || []).concat(data.custom_uploaded || []);
      const families = new Map();
      available.forEach(font => {
        const name = font.font_family || font.font_name;
        if (!name) return;
        if (!families.has(name)) families.set(name, { name, faces: [] });
        families.get(name).faces.push(font);
      });
      return Array.from(families.values());
    }

    async function openPresentationFontSettings() {
      const panel = document.getElementById('presentationFontSettingsPanel');
      const select = document.getElementById('presentationFontSelect');
      if (!panel || !select) return;
      panel.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(panel);
      select.disabled = true;
      select.innerHTML = '<option value="">جاري تحميل الخطوط...</option>';
      try {
        const data = await api('GET', '/api/branding/fonts');
        if (!data.success) throw new Error(data.error || 'Font list unavailable');
        const families = presentationFontFamilies(data);
        const selections = data.selections || [];
        const chosenIds = new Set(selections.map(item => item.font_id).filter(Boolean));
        const chosenPaths = new Set(selections.map(item => item.custom_font_path).filter(Boolean));
        window.tenantPresentationFontFamilies = families;
        select.innerHTML = '<option value="">الخط الافتراضي</option>' + families.map(family => {
          const selected = family.faces.some(face =>
            chosenIds.has(face.id) || (face.custom_font_path && chosenPaths.has(face.custom_font_path)));
          const scripts = new Set(family.faces.map(face => face.script || 'arabic'));
          const coverage = scripts.has('arabic') && scripts.has('latin') ? trDynamicI18n('عربي ولاتيني')
            : scripts.has('arabic') ? trDynamicI18n('عربي') : trDynamicI18n('لاتيني');
          return '<option value="' + escapeHtml(family.name) + '"' + (selected ? ' selected' : '') +
            '>' + escapeHtml(family.name + ' — ' + coverage) + '</option>';
        }).join('');
        select.disabled = false;
        refreshDynamicI18n(select);
        await renderPresentationFontStatus();
      } catch (error) {
        console.warn('[PRESENTATION FONT] load failed:', error);
        select.innerHTML = '<option value="">تعذر تحميل الخطوط</option>';
        refreshDynamicI18n(select);
      }
    }
    document.addEventListener('wf:lang', () => {
      try {
        const panel = document.getElementById('presentationFontSettingsPanel');
        if (panel && panel.style.display === 'flex') openPresentationFontSettings();
      } catch (e) { /* ignore */ }
    });

    function closePresentationFontSettings() {
      const panel = document.getElementById('presentationFontSettingsPanel');
      if (panel) {
        panel.style.display = 'none';
        if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
      }
    }

    // The chosen family is applied to the whole deck: both scripts and every weight. A family that
    // ships faces for one script only is used for the other script too, otherwise half the text
    // would silently stay on the platform default and the choice would look like it did nothing.
    async function selectPresentationFont(familyName) {
      const select = document.getElementById('presentationFontSelect');
      if (!select || select.disabled) return;
      select.disabled = true;
      const weights = ['light', 'regular', 'medium', 'bold', 'black'];
      try {
        await Promise.all(['arabic', 'latin'].flatMap(script =>
          weights.map(weight => api('DELETE', '/api/branding/fonts/' + script + '/' + weight))));
        if (familyName) {
          let families = window.tenantPresentationFontFamilies;
          if (!families) {
            families = presentationFontFamilies(await api('GET', '/api/branding/fonts'));
          }
          const family = families.find(item => item.name === familyName);
          if (!family) throw new Error('Unknown font family');
          for (const script of ['arabic', 'latin']) {
            const own = family.faces.filter(face => (face.script || 'arabic') === script);
            for (const face of (own.length ? own : family.faces)) {
              const body = { script, weight: face.weight || 'regular' };
              if (face.custom_font_path) body.custom_font_path = face.custom_font_path;
              else body.font_id = face.id;
              await api('PUT', '/api/branding/fonts', body);
            }
          }
          await api('PUT', '/api/branding', { font_family: familyName, font_arabic: familyName });
        }
        await loadTenantBranding();
        await renderPresentationFontStatus();
        if (typeof renderTenantSlides === 'function') renderTenantSlides();
        toast(familyName ? 'تم تطبيق الخط على العرض' : 'تم الرجوع للخط الافتراضي');
      } catch (error) {
        console.error('[PRESENTATION FONT] save failed:', error);
        toast('تعذر تحديث خط العرض');
      } finally {
        select.disabled = false;
      }
    }

    function toggleMapStylePanel() {
      const panel = document.getElementById('mapStylePanel');
      if (panel) {
        if (panel.style.display === 'none' || !panel.style.display) {
          const pStyles = (tenantProjectData && tenantProjectData.map_styles) || {};
          const bStyles = tenantBranding || {};
          const setSelect = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
          setSelect('mapStyleOverview', pStyles.overview || bStyles.map_style_overview || 'satellite');
          setSelect('mapStyleLandmarks', pStyles.landmarks || bStyles.map_style_landmarks || 'satellite');
          setSelect('mapStyleAccess', pStyles.access || bStyles.map_style_access || 'satellite');
          setSelect('mapStyleCatchment', pStyles.catchment || bStyles.map_style_catchment || 'satellite');
          panel.style.display = 'flex';
        } else {
          panel.style.display = 'none';
        }
      }
    }

    function editSlideHtml(index) {
      if (!hasPermission('create_presentation')) return;
      const slide = tenantSlidesData[index];
      if (!slide) return;
      const existing = document.getElementById('slideEditModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'slideEditModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:24px;max-width:800px;width:100%;max-height:90vh;overflow:auto">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
        '<h3>تعديل شريحة ' + (index + 1) + '</h3>' +
        '<button class="btn ghost" onclick="this.closest(\'#slideEditModal\').remove()">إغلاق</button></div>' +
        '<label>عنوان الشريحة</label>' +
        '<input type="text" id="slideEditTitle" value="' + escapeHtml(slide.title || '') + '" style="width:100%;margin-bottom:10px">' +
        '<label>HTML المحتوى</label>' +
        '<textarea id="slideEditHtml" style="width:100%;min-height:300px;font-family:monospace;font-size:13px">' + escapeHtml(slide.html || '') + '</textarea>' +
        '<div class="tenant-btns" style="margin-top:12px">' +
        '<button class="btn primary" onclick="saveSlideEdit(' + index + ')">حفظ</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    function saveSlideEdit(index) {
      if (!hasPermission('create_presentation')) return;
      const title = document.getElementById('slideEditTitle').value;
      const html = document.getElementById('slideEditHtml').value;
      beginPresentationUndoChange();
      tenantSlidesData[index].title = title;
      tenantSlidesData[index].html = html;
      tenantSlidesData[index]._designer_keep_html = true;
      tenantSlidesData[index].is_custom = true;
      document.getElementById('slideEditModal').remove();
      renderTenantSlides();
      triggerAutoSaveDraft();
      toast('تم تعديل الشريحة');
    }

    function moveSlide(index, direction) {
      const newIndex = index + direction;
      if (newIndex < 0 || newIndex >= tenantSlidesData.length) return;
      beginPresentationUndoChange();
      const temp = tenantSlidesData[index];
      tenantSlidesData[index] = tenantSlidesData[newIndex];
      tenantSlidesData[newIndex] = temp;
      renumberTenantSlides();
      renderTenantSlides();
      triggerAutoSaveDraft();
    }

    function deleteSlide(index) {
      if (!hasPermission('create_presentation')) return;
      if (tenantSlidesData.length <= 1) { toast('لا يمكن حذف آخر شريحة'); return; }
      if (!confirm('حذف الشريحة ' + (index + 1) + '؟')) return;
      beginPresentationUndoChange();
      tenantSlidesData.splice(index, 1);
      activeSlideIndex = Math.min(activeSlideIndex, tenantSlidesData.length - 1);
      tenantChatSlideIndex = Math.min(tenantChatSlideIndex, tenantSlidesData.length - 1);
      renumberTenantSlides();
      renderTenantSlides();
      triggerAutoSaveDraft();
      toast('تم حذف الشريحة');
    }

    async function commitTenantPresentation(snapshot, presentationId, title, options = {}) {
      if (tenantPresentationSavePromise) return tenantPresentationSavePromise;
      const initialRevision = options.expectedRevision ?? tenantPresentationRevision;
      const provenance = tenantPresentationProvenance;
      const button = document.getElementById('presentationSaveButton');
      if (button) { button.disabled = true; button.textContent = 'جاري الحفظ...'; }
      tenantPresentationSavePromise = (async () => {
        let currentRevision = initialRevision;
        let attempts = 0;
        while (attempts < 2) {
          attempts++;
          // api('POST', '/api/presentations'
          const response = await api(presentationId ? 'PUT' : 'POST',
            '/api/presentations' + (presentationId ? '/' + encodeURIComponent(presentationId) : ''), {
              title, projectData: snapshot, slidesData: snapshot.tenantSlidesData,
              slideCount: snapshot.tenantSlidesData.length,
              ...(presentationId ? { expectedRevision: currentRevision } : {}),
              changeSource: provenance ? 'ai' : 'manual', provenance,
              operation: options.operation || 'save'
            });
          if (!response?.success) {
            if (response?.error_code === 'PRESENTATION_REVISION_CONFLICT') {
              const serverRevision = Number(response.currentRevision);
              const isInteractive = typeof options.interactive !== 'undefined' ? options.interactive : !options.silent;
              if (attempts === 1 && (options.force || isInteractive) && Number.isInteger(serverRevision) && typeof confirm === 'function') {
                const confirmOverwrite = options.force || confirm(
                  WFT('presentation.conflict_confirm', 'توجد نسخة أحدث محفوظة على الخادم (النسخة {rev}). هل تريد حفظ تعديلاتك الحالية فوقها؟', { rev: serverRevision })
                );
                if (confirmOverwrite) {
                  currentRevision = serverRevision;
                  continue;
                }
              }
              throw new Error('العرض له نسخة أحدث محفوظة على الخادم. تعديلاتك ما زالت مفتوحة ولم تُستبدل النسخة المحفوظة.');
            }
            const saveError = new Error(response?.error || 'تعذر حفظ العرض');
            saveError.response = response || {};
            throw saveError;
          }
          if (!presentationId || tenantPresentationId === presentationId) {
            tenantPresentationId = response.presentationId || presentationId;
            tenantPresentationRevision = Number(response.revision) || 0;
            tenantPresentationTitle = title;
            tenantProjectMode = 'presentation';
            clearPresentationUndoProvenance();
            setSlidesEditorInfo(title, tenantSlidesData.length);
          }
          tenantArchiveCache = null;
          return response;
        }
      })();
      updatePresentationUndoButtons();
      try { return await tenantPresentationSavePromise; }
      finally {
        tenantPresentationSavePromise = null;
        if (button) { button.disabled = false; button.textContent = 'حفظ كمسودة'; }
        updatePresentationUndoButtons();
      }
    }

    async function saveTenantPresentation(titleOverride = '', options = {}) {
      const title = String(titleOverride || tenantPresentationTitle
        || tenantProjectData.project_name || tenantProjectData.projectName || 'عرض بدون عنوان').trim();
      renumberTenantSlides();
      // api('POST', '/api/presentations'
      tenantProjectData = {
        ...tenantProjectData, tenantSlidePlan, tenantCreativeImages,
        designerChat: designerChatPersistence(), tenantSlidesData
      };
      const snapshot = JSON.parse(JSON.stringify(tenantProjectData));
      try {
        const response = await commitTenantPresentation(snapshot, tenantPresentationId, title, options);
        tenantProjectData.designerChat = designerChatPersistence(response.presentationId);
        return true;
      } catch (error) {
        if (typeof options.onError === 'function') options.onError(error);
        setDraftDirty(true);
        toast(error.message || 'تعذر حفظ العرض');
        return false;
      }
    }

    async function savePresentationFromToolbar() {
      if (tenantPresentationSavePromise || isGeneratingTenantSlides) return;
      if (tenantPresentationId) await saveExistingPresentation();
      else if (tenantSlidesData.length) await saveTenantPresentation();
      else await saveProjectAsDraft();
    }

    async function savePresentationCopy() {
      if (!tenantSlidesData.length || tenantPresentationSavePromise || isGeneratingTenantSlides) return;
      const name = prompt('اسم العرض المستقل', (tenantPresentationTitle || 'عرض') + ' - نسخة مستقلة');
      if (!name?.trim()) return;
      const original = { id: tenantPresentationId, revision: tenantPresentationRevision,
        title: tenantPresentationTitle, scope: tenantProjectData.presentation_scope };
      tenantPresentationId = null;
      tenantPresentationRevision = 0;
      tenantProjectData.presentation_scope = 'copy:' + crypto.randomUUID();
      if (await saveTenantPresentation(name.trim())) {
        resetPresentationUndo();
        toast('تم حفظ عرض مستقل');
      } else {
        tenantPresentationId = original.id;
        tenantPresentationRevision = original.revision;
        tenantPresentationTitle = original.title;
        tenantProjectData.presentation_scope = original.scope;
      }
    }

    async function preparePresentationGenerationTarget(scope) {
      if (tenantPresentationSavePromise) await tenantPresentationSavePromise;
      const saveCurrentPresentation = async () => {
        let saveError = null;
        const saved = await saveTenantPresentation('', {
          onError: error => { saveError = error; }
        });
        return saved ? true : ((saveError && saveError.response) || false);
      };
      if (tenantPresentationId && tenantSlidesData.length) {
        let saved = await saveCurrentPresentation();
        if (saved !== true && saved?.error_code === 'DRAFT_LOCKED' && saved?.status === 'generating'
          && await cancelActiveTenantGenerationRun(tenantProjectData.draftId || tenantProjectData.draft_id)) {
          saved = await saveCurrentPresentation();
        }
        if (saved !== true) return false;
      }
      let target = null;
      const currentScope = tenantProjectData.presentation_scope;
      if (tenantPresentationId && (currentScope === scope || (!currentScope && scope === 'full')
        || (scope === 'full' && String(currentScope || '').startsWith('copy:')))) {
        target = { id: tenantPresentationId, revision: tenantPresentationRevision };
      } else {
        const draftId = tenantProjectData.draftId;
        if (draftId) {
          const response = await api('GET', '/api/presentations?draftId=' + encodeURIComponent(draftId));
          if (!response?.success) { toast(response?.error || 'تعذر تحميل عروض المشروع'); return false; }
          target = (response.presentations || []).find(item => item.presentationScope === scope) || null;
        }
      }
      if (target && target.id !== tenantPresentationId) {
        const response = await api('GET', '/api/presentations/' + encodeURIComponent(target.id));
        if (!response?.success) { toast(response?.error || 'تعذر تحميل النسخة الحالية'); return false; }
        const saved = response.presentation;
        let checkpoint = await api('PUT', '/api/presentations/' + encodeURIComponent(target.id), {
          title: saved.title, projectData: saved.projectData, slidesData: saved.slidesData,
          expectedRevision: Number(saved.revision) || 0
        });
        if (!checkpoint?.success && checkpoint?.error_code === 'DRAFT_LOCKED'
          && checkpoint?.status === 'generating'
          && await cancelActiveTenantGenerationRun(saved.draftId || saved.projectData?.draftId || tenantProjectData.draftId)) {
          checkpoint = await api('PUT', '/api/presentations/' + encodeURIComponent(target.id), {
            title: saved.title, projectData: saved.projectData, slidesData: saved.slidesData,
            expectedRevision: Number(saved.revision) || 0
          });
        }
        if (!checkpoint?.success) { toast(checkpoint?.error || 'تعذر حماية النسخة الحالية'); return false; }
        target.revision = checkpoint.revision;
        tenantSlidesData = saved.slidesData || [];
        tenantSlidePlan = recoverTenantSlidePlan(saved.projectData || {}, tenantSlidesData);
        resetPresentationUndo();
      }
      tenantPresentationId = target?.id || null;
      tenantPresentationRevision = Number(target?.revision) || 0;
      tenantPresentationProvenance = null;
      tenantProjectMode = target ? 'presentation' : 'new';
      tenantProjectData.presentation_scope = target && String(currentScope || '').startsWith('copy:')
        ? currentScope : scope;
      checkpointPresentationUndo();
      return true;
    }