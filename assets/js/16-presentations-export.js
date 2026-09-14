/* 16-presentations-export.js - index.html lines 26148-27658, shared global scope, classic scripts in order */

    async function openExistingPresentation(presId) {
      const data = await api('GET', '/api/presentations/' + presId);
      if (!data.success || !data.presentation) { toast('فشل تحميل العرض'); return; }
      const p = data.presentation;
      setDraftDirty(false);
      tenantPresentationId = p.id;
      tenantPresentationRevision = Number(p.revision) || 0;
      tenantPresentationProvenance = null;
      tenantPresentationTitle = p.title || '';
      tenantProjectMode = 'presentation';
      tenantProjectData = { ...(p.projectData || {}) };
      // Keep saving to the draft this presentation was generated from. Without an
      // id the next save mints a random one and forks a second draft row, so a
      // later reopen can land on the older row and read as "saved but lost".
      if (p.draft_id) {
        tenantProjectData.draftId = p.draft_id;
        tenantProjectData.draft_id = p.draft_id;
      } else if (!tenantProjectData.draftId) {
        tenantProjectData.draftId = p.draftId || tenantProjectData.draft_id || null;
      }
      tenantSlidesData = Array.isArray(p.slidesData)
        ? p.slidesData
        : (Array.isArray(tenantProjectData.tenantSlidesData) ? tenantProjectData.tenantSlidesData : []);
      tenantSlideGenerationCheckpoint = tenantProjectData.slide_generation_checkpoint || null;
      tenantSlidePlan = recoverTenantSlidePlan(tenantProjectData, tenantSlidesData);
      if (tenantSlidePlan) tenantProjectData.tenantSlidePlan = tenantSlidePlan;
      restoreDesignerChat(tenantProjectData, tenantPresentationId);
      tenantChatSlideIndex = 0;
      activeSlideIndex = 0;
      tempCoverImage = null;
      tempMoodboardImages = {};
      tenantMapPreviewState = null;
      tenantMapPolygonPoints = [];
      tenantMapDraftPolygonPoints = [];
      tenantMapPolygonMode = false;
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      resetTenantRoadModes();
      resetTenantCatchmentMode();
      resetTenantLandmarksEditMode();
      tenantLandmarkPlacementTarget = null;
      tenantNearbyLandmarks = [];
      tenantActiveProjectSection = null;
      const ci = tenantProjectData.tenantCreativeImages || {};
      tenantCreativeImages = {
        ...ci,
        cover: ci.cover || ci.mainImageData || '',
        moodboard: Array.isArray(ci.moodboard) ? ci.moodboard : [],
        map_placeholders: ci.map_placeholders || {},
        map_landmarks: ci.map_landmarks || [],
        images_signature: ci.images_signature || null,
        maps_signature: ci.maps_signature || null,
        cover_prompt: ci.cover_prompt || '',
        moodboard_prompts: Array.isArray(ci.moodboard_prompts) ? ci.moodboard_prompts : []
      };
      tenantProjectData.tenantCreativeImages = tenantCreativeImages;
      tenantVisualConceptState = normalizeVisualConceptState(tenantProjectData.visual_concept);
      tenantProjectSectionStatuses = {
        ...(p.sectionStatuses || {}),
        ...(tenantProjectData.sectionStatuses || {}),
        ...((tenantProjectData.pageDrafts || {}).project?.sectionStatuses || {})
      };
      await loadTenantProjectForm();
      hydrateTenantProjectForm(tenantProjectData);
      applySectionStatuses(tenantProjectSectionStatuses);
      renderTenantSlides();
      resetPresentationUndo();
      setSlidesEditorInfo(p.title || '', p.slideCount || tenantSlidesData.length);
      showTenantPage('tenantSlidesPage');
      refreshGlobalRail();
      toast('تم فتح العرض: ' + (p.title || ''));
      void resumeTenantDesignerChatJob();
    }

    async function openTenantPresentations(force = false) {
      showTenantPage('tenantPresentationsPage');
      const list = document.getElementById('tenantPresentationsList');
      if (!list) return;
      const filters = {
        search: document.getElementById('projectArchiveSearch')?.value?.trim() || '',
        status: document.getElementById('projectArchiveStatus')?.value || '',
        from: document.getElementById('projectArchiveFrom')?.value || '',
        to: document.getElementById('projectArchiveTo')?.value || ''
      };
      const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
      const tenantKey = (tenantUser && (tenantUser.id || tenantUser.tenantId)) || 'tenant';
      const listLang = ((typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang && window.WFI18n.getLang()) || 'ar');
      const cacheKey = tenantKey + '|' + listLang + '|' + query.toString();
      if (!force && tenantArchiveCache && tenantArchiveCache.key === cacheKey && Date.now() - tenantArchiveCache.timestamp < 15000) {
        list.innerHTML = tenantArchiveCache.html;
        return;
      }
      const renderDraftCard = (d, recovery, projectCost) => {
        const title = d.title || 'مشروع بدون عنوان';
        const statusText = d.status === 'pending_approval' ? 'بانتظار التعميد' : d.status === 'approved' ? 'معتمد' : 'مسودة';
        const date = (d.updated_at || d.created_at || '').slice(0, 16).replace('T', ' ');
        const projectMapsCost = Number(projectCost?.maps_cost_usd) || 0;
        const costText = '<span>التكلفة:</span> ' + (projectCost ? formatUsageCost(projectCost.cost_usd || 0) + (projectMapsCost > 0 ? ' (<span>خرائط:</span> ' + formatUsageCost(projectMapsCost) + ')' : '') : '—');
        const fieldsHtml = recovery ? '<span>' + recovery.fieldCount + '</span> <span>حقل ممتلئ</span>' : '';
        // Admins (approvals permission) approve directly whenever they want; employees
        // only send a request and the draft stays pending until an admin approves it.
        const canReview = hasPermission('approvals');
        const isApproved = d.status === 'approved';
        const isPending = d.status === 'pending_approval';
        const approveBtn = (isApproved || (isPending && !canReview)) ? ''
          : '<button class="btn small green" onclick="' +
          (canReview ? 'approveProjectDraftById' : 'requestProjectDraftApprovalById') +
          '(\'' + d.id + '\')">اعتماد</button>';
        return '<div class="tenant-presentation-card" data-draft-id="' + d.id + '" style="background:#f8fafc;border:1px solid ' +
          (recovery?.isEmpty ? '#f59e0b' : '#cbd5e1') + ';margin-bottom:12px">' +
          '<div><h3>' + escapeHtml(title) + '</h3><div class="meta"><span>' + statusText + '</span> | ' + escapeHtml(date) +
          (fieldsHtml ? ' | ' + fieldsHtml : '') + ' | ' + costText + '</div></div><div class="tenant-actions">' +
          '<button class="btn small primary" onclick="openProjectDraftById(\'' + d.id + '\')">فتح المشروع</button>' +
          '<button class="btn small ghost" onclick="showDraftEditLog(\'' + d.id + '\')">سجل التعديلات</button>' +
          approveBtn +
          '<button class="btn small danger" onclick="deleteProjectDraftById(\'' + d.id + '\')">حذف المشروع</button>' +
          '</div></div>';
      };
      showInlineLoader(list, 'جاري تحميل المشاريع...');
      const stamp = String(Date.now()) + Math.random().toString(16).slice(2);
      list.dataset.archiveStamp = stamp;
      // Render the list from the lightweight drafts query alone, then enrich each
      // card with recovery and cost data in the background. Waiting for all three
      // calls kept the spinner up for seconds on two rows because usage-totals
      // held the response for a provider reconcile and recovery parsed every
      // presentation payload of the tenant.
      const draftsData = await apiWithTimeout('GET', '/api/project-drafts?' + query.toString(), null, 25000).catch(() => ({ success: false }));
      if (!draftsData || !draftsData.success) {
        if (list.dataset.archiveStamp === stamp) {
          renderListLoadError(list, 'openTenantPresentations(true)');
        }
        return;
      }
      const drafts = Array.isArray(draftsData.drafts) ? draftsData.drafts : [];
      const projectIds = drafts.map(d => d.id).filter(Boolean);
      if (!drafts.length) {
        const emptyHtml = '<p class="tenant-hint">لا توجد مشاريع مطابقة.</p>';
        if (list.dataset.archiveStamp === stamp) {
          list.innerHTML = emptyHtml;
          tenantArchiveCache = { key: cacheKey, timestamp: Date.now(), html: emptyHtml };
        }
        return;
      }
      list.innerHTML = drafts.map(d => renderDraftCard(d, null, null)).join('');
      tenantArchiveCache = { key: cacheKey, timestamp: Date.now(), html: list.innerHTML };
      if (!projectIds.length) return;
      const [recoveryData, totalsData] = await Promise.all([
        api('GET', '/api/project-drafts/recovery?draftIds=' + encodeURIComponent(projectIds.join(','))).catch(() => ({ success: false })),
        apiWithTimeout('GET', '/api/usage-totals?draftIds=' + encodeURIComponent(projectIds.join(',')), null, 25000).catch(() => null)
      ]);
      if (list.dataset.archiveStamp !== stamp) return;
      if (!document.contains(list) || !list.querySelector('[data-draft-id]')) return;
      const recoveryByDraft = {};
      if (recoveryData?.success) {
        (recoveryData.drafts || []).forEach(item => { recoveryByDraft[item.draftId] = item; });
      }
      let costByProject = {};
      if (totalsData?.success && totalsData.projects) costByProject = totalsData.projects;
      let patched = false;
      drafts.forEach(d => {
        const node = list.querySelector('[data-draft-id="' + d.id + '"]');
        if (!node) return;
        const projectCost = costByProject[d.id];
        const next = renderDraftCard(d, recoveryByDraft[d.id] || null, projectCost);
        if (node.outerHTML !== next) { node.outerHTML = next; patched = true; }
      });
      if (patched || recoveryData?.success || totalsData?.success) {
        tenantArchiveCache = { key: cacheKey, timestamp: Date.now(), html: list.innerHTML };
      }
    }

    async function restoreProjectDraft(draftId, presentationId) {
      const resp = await api('POST', '/api/project-draft/' + encodeURIComponent(draftId) + '/restore',
        { presentationId });
      if (!resp || !resp.success) {
        toast(resp?.error || 'تعذر استرجاع البيانات');
        return;
      }
      tenantArchiveCache = null;
      if (!resp.restoredCount) {
        toast('لا توجد حقول ناقصة يمكن استرجاعها في هذه المسودة');
        return;
      }
      toast('تم استرجاع ' + resp.restoredCount + ' حقلًا');
      await openProjectDraftById(draftId);
    }

    async function requestProjectDraftApprovalById(draftId) {
      if (!draftId) return;
      const result = await api('POST', '/api/project-draft/request-approval', { draftId });
      if (!result || !result.success) {
        toast(result && result.error_code === 'SECTIONS_NOT_APPROVED'
          ? 'يجب اعتماد جميع أقسام المشروع قبل طلب الاعتماد'
          : ((result && result.error) || 'تعذر إرسال طلب الاعتماد'));
        return;
      }
      tenantArchiveCache = null;
      toast('تم إرسال المسودة للاعتماد');
      await openTenantPresentations(true);
    }

    async function approveProjectDraftById(draftId) {
      if (!draftId) return;
      const result = await api('POST', '/api/project-draft/review', { draftId, status: 'approved' });
      if (!result || !result.success) {
        toast((result && result.error) || 'تعذر اعتماد المشروع');
        return;
      }
      tenantArchiveCache = null;
      toast(WFT('admin.project_approved', 'تم اعتماد المشروع'));
      await openTenantPresentations(true);
    }

    async function openProjectDraftById(draftId) {
      showLoader('جاري تحميل المسودة', '');
      try {
        const resp = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId));
        hideLoader();
        if (!resp.success || !resp.draft) {
          toast(resp.error || 'تعذر تحميل المسودة');
          return false;
        }

        const draft = resp.draft;
        setDraftDirty(false);
        const draftData = draft.draft_data || draft.draftData || {};
        const pageDrafts = draftData.pageDrafts || {};
        const sectionStatuses = draft.section_statuses || {};
        tenantPresentationId = null;
        tenantPresentationRevision = 0;
        tenantPresentationProvenance = null;
        tenantPresentationTitle = '';
        tenantProjectMode = 'draft';
        tenantProjectData = { ...draftData, draftId: draftData.draftId || draft.id || draftId };
        tenantSlidesData = Array.isArray(draftData.tenantSlidesData) ? draftData.tenantSlidesData : [];
        tenantSlideGenerationCheckpoint = draftData.slide_generation_checkpoint || null;
        tenantSlidePlan = recoverTenantSlidePlan(tenantProjectData, tenantSlidesData);
        if (tenantSlidePlan) tenantProjectData.tenantSlidePlan = tenantSlidePlan;
        restoreDesignerChat(draftData);
        tenantChatSlideIndex = 0;
        tenantMapPreviewState = null;
        tenantMapPolygonPoints = [];
        tenantMapDraftPolygonPoints = [];
        tenantMapPolygonMode = false;
        tenantMapPinMode = false;
        tenantMapDraftPinHistory = [];
        resetTenantRoadModes();
        resetTenantCatchmentMode();
        resetTenantLandmarksEditMode();
        tenantNearbyLandmarks = [];
        tenantActiveProjectSection = null;
        tempCoverImage = null;
        tempMoodboardImages = {};
        tenantProjectSectionStatuses = { ...sectionStatuses };
        tenantProjectDraftApproval = draft;

        if (draftData.location_polygon_source === 'manual' && typeof draftData.location_polygon === 'string') {
          tenantMapPolygonPoints = draftData.location_polygon.split(';')
            .map(point => point.split(',').map(Number))
            .filter(point => point.length === 2 && point.every(Number.isFinite));
        }
        if (pageDrafts.mainImage && !pageDrafts.mainImage.approved) {
          tempCoverImage = pageDrafts.mainImage.image || null;
        }
        if (pageDrafts.moodboard && pageDrafts.moodboard.images) {
          tempMoodboardImages = { ...pageDrafts.moodboard.images };
        }

        const ci = tenantProjectData.tenantCreativeImages || {};
        const savedMoodboard = Array.isArray(ci.moodboard) ? ci.moodboard.slice() : [];
        const savedMoodboardPrompts = Array.isArray(ci.moodboard_prompts) ? ci.moodboard_prompts.slice() : [];
        const pageMoodboard = pageDrafts.moodboard || {};
        VISUAL_CONCEPT_SLOTS.slice(1).forEach((item, index) => {
          if (!savedMoodboard[index] && pageMoodboard.images && pageMoodboard.images[index]) {
            savedMoodboard[index] = pageMoodboard.images[index];
          }
          if (!savedMoodboardPrompts[index] && Array.isArray(pageMoodboard.prompts) && pageMoodboard.prompts[index]) {
            savedMoodboardPrompts[index] = pageMoodboard.prompts[index];
          }
        });
        tenantCreativeImages = {
          ...ci,
          cover: ci.cover || ci.mainImageData || '',
          moodboard: savedMoodboard,
          map_placeholders: ci.map_placeholders || {},
          map_landmarks: ci.map_landmarks || [],
          images_signature: ci.images_signature || null,
          maps_signature: ci.maps_signature || null,
          cover_prompt: ci.cover_prompt || (pageDrafts.mainImage && pageDrafts.mainImage.prompt) || '',
          moodboard_prompts: savedMoodboardPrompts.length
            ? savedMoodboardPrompts
            : (pageMoodboard.prompts || [])
        };
        if (pageDrafts.mainImage && pageDrafts.mainImage.approved && pageDrafts.mainImage.image && !tenantCreativeImages.cover) {
          tenantCreativeImages.cover = pageDrafts.mainImage.image;
        }
        tenantProjectData.tenantCreativeImages = tenantCreativeImages;
        tenantVisualConceptState = normalizeVisualConceptState(tenantProjectData.visual_concept);

        showTenantPage('tenantProjectPage');
        await loadTenantProjectForm();
        hydrateTenantProjectForm(tenantProjectData);
        applySectionStatuses(sectionStatuses);
        renderTenantSlides();
        setSlidesEditorInfo(tenantProjectData.project_name || tenantProjectData.projectName || '',
          tenantSlidesData.length);
        resetPresentationUndo();
        refreshGlobalRail();
        toast('تم فتح المسودة المحفوظة بنجاح');
        void resumeTenantDesignerChatJob();
        return true;
      } catch (e) {
        hideLoader();
        toast('خطأ في تحميل المسودة');
        return false;
      }
    }

    async function deleteProjectDraftById(draftId) {
      if (!confirm('هل أنت تأكد من حذف هذه المسودة؟')) return;
      const resp = await api('DELETE', '/api/project-draft/' + encodeURIComponent(draftId));
      if (resp.success) {
        tenantArchiveCache = null;
        toast('تم حذف المسودة');
        openTenantPresentations();
      } else {
        toast(resp.error || 'فشل حذف المسودة');
      }
    }

    async function saveExistingPresentation() {
      if (!tenantPresentationId) { toast('لا يوجد عرض مفتوح'); return false; }
      // The draft carries the same snapshot including the slides, so back it up
      // first: a presentation-save failure must never lose the open workspace.
      try { await saveProjectAsDraftNow(true, false); } catch (backupError) {
        console.error('[DRAFT BACKUP]', backupError);
      }
      renumberTenantSlides();
      // api('PUT', '/api/presentations/'
      const saved = await saveTenantPresentation();
      if (saved) toast('تم حفظ نسخة العرض');
      return saved;
    }

    async function regeneratePresentationMaps() {
      collectMapStylePanel();
      return regenerateMapPreview(tenantSelectedMapType || 'overview');
    }

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
          <div onclick="selectChatSession('training', '${s.id}')" style="background:${bg};border:1px solid ${border};border-radius:8px;padding:8px 10px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:6px;transition:all 0.15s ease;">
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
          <div onclick="selectChatSession('ai_rules', '${s.id}')" style="background:${bg};border:1px solid ${border};border-radius:8px;padding:8px 10px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:6px;transition:all 0.15s ease;">
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

    async function exportTenantSlides(format) {
      if (!Array.isArray(tenantSlidesData) || !tenantSlidesData.length) {
        toast('لا توجد شرائح للتصدير');
        return;
      }
      await repairVisualConceptStoredImages();
      persistVisualConceptDraftState();
      const projectName = tenantProjectData.project_name || tenantProjectData.projectName || 'presentation';
      renumberTenantSlides();
      try { syncSlideEditSessionsAfterRender(); } catch (err) {}
      tenantProjectData = { ...tenantProjectData, tenantSlidePlan };
      const exportProjectData = { ...tenantProjectData };
      delete exportProjectData.tenantSlidesData;
      delete exportProjectData.designerChat;
      delete exportProjectData.tenantArchiveCache;
      delete exportProjectData.draftHistory;
      delete exportProjectData.chatHistory;
      delete exportProjectData.designerChatSessions;
      const exportCover = (
        (tenantCreativeImages && (tenantCreativeImages.cover || tenantCreativeImages.coverImage || tenantCreativeImages.mainImageData)) ||
        (exportProjectData && (exportProjectData.cover || exportProjectData.coverImage || exportProjectData.mainImageData)) ||
        ''
      );
      if (exportCover && Array.isArray(tenantSlidesData)) {
        tenantSlidesData.forEach(item => {
          if (!item || typeof item !== 'object') return;
          let sHtml = String(item.html || '');
          const sType = String(item.type || '').toLowerCase();
          sHtml = sHtml.replace(/#*(?:IMAGE_COVER|COVER_IMAGE|MAIN_IMAGE|PROJECT_IMAGE_COVER)#*/gi, exportCover);
          if (sType === 'section_divider') {
            sHtml = forceSectionDividerBackgroundHtml(sHtml, exportCover);
          }
          item.html = sHtml;
        });
      }
      const payload = {
        format: format,
        presentationId: tenantPresentationId,
        projectName: projectName,
        projectData: exportProjectData,
        slidesData: tenantSlidesData
      };
      let data = null;
      showLoader('جاري تصدير الملف', 'الصيغة: ' + format.toUpperCase(), 8);
      try {
        data = await api('POST', '/api/export', payload);
        if (!data.success || !data.url) {
          toast(data.error || 'فشل التصدير');
          return;
        }
        updateLoaderProgress(82, 'تم إنشاء الملف، جاري بدء التحميل...');
        const token = getTenantToken();
        const resp = await fetch(data.url, { headers: token ? { 'Authorization': 'Bearer ' + token } : {} });
        if (!resp.ok) throw new Error('Download failed');
        const blob = await readBlobWithProgress(resp, 84, 98);
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = data.url.split('/').pop() || ('presentation.' + format);
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);
        updateLoaderProgress(100, 'اكتمل تحميل الملف');
        toast('تم تحميل الملف');
      } catch (e) {
        console.warn('Export download:', e);
        if (data && data.url) {
          window.open(data.url, '_blank');
          toast('تم إنشاء الملف، افتح نافذة التحميل');
        } else {
          toast('تعذر إكمال التصدير');
        }
      } finally {
        hideLoader();
      }
    }

    async function deleteTenantPresentation(presId) {
      if (!confirm('هل أنت متأكد من حذف هذا العرض؟ لا يمكن التراجع عن هذا الإجراء.')) return;
      const data = await api('DELETE', '/api/presentations/' + presId);
      if (data.success) {
        toast('تم حذف العرض بنجاح');
        openTenantPresentations();
      } else {
        toast(data.error || 'فشل حذف العرض');
      }
    }



    // SAG Super Admin
    let sagAllTenants = [];
    let sagCurrentTenantId = null;
    let sagTenantActiveTab = 'company';
    let sagModalUsers = [];

    function openSagCompanyCreate() {
      const modal = document.getElementById('sagCompanyCreateModal');
      const form = document.getElementById('sagCompanyCreateForm');
      form.reset();
      document.getElementById('sagCreateStatus').value = 'active';
      document.getElementById('sagCreatePasswordMode').value = 'set_link';
      document.getElementById('sagCreatePassword').type = 'password';
      document.getElementById('sagCreateWelcomeEmail').checked = true;
      showSagCompanyCreateError('');
      document.getElementById('sagCompanyCreateResult').style.display = 'none';
      form.style.display = 'block';
      toggleSagCompanyPassword();
      modal.style.display = 'flex';
    }

    function closeSagCompanyCreate() {
      document.getElementById('sagCompanyCreateModal').style.display = 'none';
    }

    function toggleSagCompanyPassword() {
      const manual = document.getElementById('sagCreatePasswordMode').value === 'manual';
      const wrap = document.getElementById('sagCreatePasswordWrap');
      const input = document.getElementById('sagCreatePassword');
      wrap.style.display = manual ? 'block' : 'none';
      input.required = manual;
      if (!manual) {
        input.value = '';
        input.type = 'password';
        const toggle = input.parentElement ? input.parentElement.querySelector('button') : null;
        if (toggle) toggle.textContent = 'إظهار';
      }
    }

    function generateStrongPassword() {
      const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
      const bytes = new Uint8Array(16);
      let password = '';
      do {
        crypto.getRandomValues(bytes);
        password = Array.from(bytes, (b) => alphabet[b % alphabet.length]).join('');
      } while (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password));
      return password;
    }

    function generateSagCompanyPassword() {
      const mode = document.getElementById('sagCreatePasswordMode');
      if (mode) mode.value = 'manual';
      toggleSagCompanyPassword();
      const input = document.getElementById('sagCreatePassword');
      input.value = generateStrongPassword();
      input.type = 'text';
      const toggle = input.parentElement ? input.parentElement.querySelector('button') : null;
      if (toggle) toggle.textContent = 'إخفاء';
    }

    async function copySagText(value) {
      try {
        await navigator.clipboard.writeText(value);
        toast('تم النسخ');
      } catch (error) {
        const input = document.createElement('textarea');
        input.value = value;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        input.remove();
        toast('تم النسخ');
      }
    }

    function renderSagSetupResult(host, title, setupUrl, emailSent) {
      host.style.display = 'block';
      host.innerHTML =
        '<h3 style="margin:0 0 12px;color:var(--p)">' + escapeHtml(title) + '</h3>' +
        '<div class="tenant-grid full">' +
        '<div class="tenant-field"><label>رابط تعيين كلمة المرور</label>' +
        '<input type="text" value="' + escapeHtml(setupUrl || '') + '" readonly></div>' +
        '<div class="tenant-field"><label>حالة رسالة الترحيب</label><p style="margin:0">' +
        (emailSent ? 'تم الإرسال' : 'لم يتم الإرسال') + '</p></div></div>' +
        '<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:16px">' +
        '<button type="button" class="btn ghost" data-copy-setup-url>نسخ الرابط</button>' +
        '<button type="button" class="btn primary" onclick="closeSagCompanyCreate()">إغلاق</button></div>';
      host.querySelector('[data-copy-setup-url]').addEventListener('click', () => copySagText(setupUrl || ''));
    }

    function sagCompanyErrorArabic(raw) {
      const text = String(raw || '');
      const map = {
        'Email already registered': 'البريد الإلكتروني مسجل بالفعل لشركة أخرى',
        'Username already registered': 'اسم المستخدم مسجل بالفعل، اختر اسم مستخدم آخر',
        'Email or username already registered': 'البريد الإلكتروني أو اسم المستخدم مسجل بالفعل',
        'All company and account fields are required': 'جميع حقول الشركة والحساب مطلوبة',
        'Company or account manager name is too long': 'اسم الشركة أو اسم مدير الحساب طويل جدا',
        'Invalid email address': 'البريد الإلكتروني غير صالح',
        'Invalid username': 'اسم المستخدم غير صالح',
        'Invalid phone number': 'رقم الجوال غير صالح',
        'Invalid plan': 'الخطة غير صالحة',
        'Invalid password mode': 'طريقة إعداد كلمة المرور غير صالحة',
        'Credit balance must be a valid number': 'الرصيد الائتماني يجب أن يكون رقما صالحا',
        'Credit balance cannot be negative': 'الرصيد الائتماني لا يمكن أن يكون سالبا',
        'Password must be at least 10 characters': 'كلمة المرور يجب أن تكون 10 أحرف على الأقل',
        'Password must include letters and numbers': 'كلمة المرور يجب أن تحتوي على حروف وأرقام'
      };
      if (map[text]) return map[text];
      const lower = text.toLowerCase();
      if (lower.includes('email') && lower.includes('already')) return map['Email already registered'];
      if (lower.includes('username') && lower.includes('already')) return map['Username already registered'];
      return text || 'تعذر إنشاء حساب الشركة';
    }

    function showSagCompanyCreateError(msg) {
      const el = document.getElementById('sagCompanyCreateError');
      if (!el) return;
      if (typeof showTenantError === 'function') {
        showTenantError('sagCompanyCreateError', msg);
        return;
      }
      el.textContent = msg;
      el.style.display = msg ? 'block' : 'none';
    }

    async function createSagCompany(event) {
      event.preventDefault();
      const submit = document.getElementById('sagCreateCompanySubmit');
      const payload = {
        companyName: document.getElementById('sagCreateCompanyName').value.trim(),
        accountManagerName: document.getElementById('sagCreateManagerName').value.trim(),
        email: document.getElementById('sagCreateEmail').value.trim().toLowerCase(),
        phone: document.getElementById('sagCreatePhone').value.trim(),
        username: document.getElementById('sagCreateUsername').value.trim().toLowerCase(),
        isActive: document.getElementById('sagCreateStatus').value === 'active',
        passwordMode: document.getElementById('sagCreatePasswordMode').value,
        password: document.getElementById('sagCreatePassword').value,
        sendWelcomeEmail: document.getElementById('sagCreateWelcomeEmail').checked
      };
      showSagCompanyCreateError('');
      submit.disabled = true;
      showLoader('جاري إنشاء حساب الشركة', 'إنشاء الشركة والمستخدم الرئيسي', 12);
      try {
        const data = await api('POST', '/api/admin/tenants', payload);
        if (!data.success) {
          showSagCompanyCreateError(sagCompanyErrorArabic(data.error));
          return;
        }
        document.getElementById('sagCompanyCreateForm').style.display = 'none';
        renderSagSetupResult(
          document.getElementById('sagCompanyCreateResult'),
          'تم إنشاء حساب الشركة والمستخدم الرئيسي بنجاح',
          data.setupUrl,
          data.welcomeEmailSent
        );
        const tenantsData = await api('GET', '/api/admin/tenants');
        sagAllTenants = tenantsData.success ? tenantsData.tenants || [] : sagAllTenants;
        renderSagTenants(sagAllTenants);
      } finally {
        submit.disabled = false;
        hideLoader();
      }
    }

    async function openTenantAdmin() {
      showTenantPage('tenantAdminPage');
      const list = document.getElementById('sagTenantsList');
      const statsEl = document.getElementById('sagAdminStats');
      showInlineLoader(list, 'جاري التحميل...');
      statsEl.innerHTML = '';
      const [tenantsData, statsData] = await Promise.all([api('GET', '/api/admin/tenants'), api('GET', '/api/admin/stats')]);
      sagAllTenants = (tenantsData.success && tenantsData.tenants) ? tenantsData.tenants : [];
      const stats = (statsData.success && statsData.stats) ? statsData.stats : {};
      renderSagStats(stats);
      renderSagTenants(sagAllTenants);
    }

    async function sagEnsureAllKeys() {
      const btn = document.getElementById('sagEnsureKeysBtn');
      if (btn) btn.disabled = true;
      showLoader(WFT('admin.keys_issuing', 'جاري إصدار مفاتيح الشركات...'), '', 5);
      try {
        let offset = 0, created = 0, failed = 0, remaining = Infinity, rounds = 0, firstError = '';
        while (offset < remaining && rounds < 40) {
          rounds += 1;
          const data = await api('POST', '/api/admin/openrouter-keys/ensure-all', { batch: 25, offset });
          if (!data || !data.success) {
            toast(WFT('admin.keys_failed', 'تعذر إصدار المفاتيح'));
            if (data && data.error) toast(String(data.error).slice(0, 300));
            return;
          }
          created += data.created || 0;
          failed += data.failed || 0;
          if (!firstError && Array.isArray(data.results)) {
            const bad = data.results.find(r => !r.ok && r.error);
            if (bad) firstError = String(bad.error).slice(0, 300);
          }
          remaining = data.total_keyless || 0;
          offset += (data.results || []).length;
          updateLoaderProgress(Math.min(95, Math.round((offset / Math.max(1, remaining)) * 100)));
          if (!data.results || !data.results.length) break;
        }
        if (!created && !failed) {
          toast(WFT('admin.keys_none', 'كل الشركات لديها مفاتيح'));
        } else {
          toast(WFT('admin.keys_done', 'تم إصدار {created} من أصل {total}', { created, total: created + failed }));
          if (firstError) toast(firstError);
        }
        const tenantsData = await api('GET', '/api/admin/tenants');
        sagAllTenants = tenantsData.success ? tenantsData.tenants || [] : sagAllTenants;
        renderSagTenants(sagAllTenants);
      } finally {
        if (btn) btn.disabled = false;
        hideLoader();
      }
    }

    async function sagCleanOrphanKeys() {
      const btn = document.getElementById('sagCleanOrphansBtn');
      if (btn) btn.disabled = true;
      showLoader(WFT('admin.orphans_check', 'فحص المفاتيح اليتيمة'), '', 5);
      try {
        const report = await api('GET', '/api/admin/openrouter-keys/orphans');
        if (!report || !report.success) {
          toast(WFT('admin.orphans_failed', 'تعذر حذف المفاتيح اليتيمة'));
          return;
        }
        if (!report.count) {
          toast(WFT('admin.orphans_none', 'لا توجد مفاتيح يتيمة'));
          return;
        }
        const names = (report.orphans || []).map(o => o.name).filter(Boolean).join(', ');
        if (!confirm(WFT('admin.orphans_confirm', 'حذف {count} مفاتيح يتيمة؟', { count: report.count }) + (names ? ' ' + names : ''))) return;
        const done = await api('DELETE', '/api/admin/openrouter-keys/orphans', { confirm: true });
        if (!done || !done.success) {
          toast(WFT('admin.orphans_failed', 'تعذر حذف المفاتيح اليتيمة'));
          return;
        }
        toast(WFT('admin.orphans_deleted', 'تم حذف {count} مفاتيح يتيمة', { count: done.deleted_count || 0 }));
      } finally {
        if (btn) btn.disabled = false;
        hideLoader();
      }
    }

    function renderSagStats(stats) {
      const el = document.getElementById('sagAdminStats');
      const cards = [
        { label: 'إجمالي الشركات', value: stats.tenants || stats.total_tenants || sagAllTenants.length },
        { label: 'شركات نشطة', value: sagAllTenants.filter(t => t.isActive).length },
        { label: 'إجمالي الأفراد (الموظفين)', value: stats.users || 0 },
        { label: 'إجمالي العروض', value: stats.presentations || stats.total_presentations || 0 },
        { label: 'إجمالي التصديرات', value: stats.exports || stats.total_exports || 0 },
      ];
      el.innerHTML = cards.map(c =>
        '<div class="tenant-dash-card stat">' +
        '<h3>' + c.value + '</h3>' +
        '<p>' + c.label + '</p></div>'
      ).join('');
    }

    function renderSagTenants(tenants) {
      const list = document.getElementById('sagTenantsList');
      if (!tenants.length) { list.innerHTML = '<p class="tenant-hint">لا توجد شركات</p>'; return; }
      list.innerHTML = tenants.map(t => {
        const planBadge = { 'free': '<span style="color:var(--muted)">Free</span>', 'pro': '<span style="color:var(--green)">Pro</span>', 'enterprise': '<span style="color:#7c3aed">Enterprise</span>' }[t.plan || 'free'] || t.plan;
        const statusBadge = t.isActive ? '<span style="color:var(--green)">نشط</span>' : '<span style="color:#c33">معطل</span>';
        const adminBadge = t.isAdmin ? ' | <span style="color:#7c3aed;font-weight:600">SAG Admin</span>' : '';
        return '<div class="tenant-presentation-card">' +
          '<div><h3>' + escapeHtml(t.companyName || '') + adminBadge + '</h3>' +
          '<div class="meta">' + escapeHtml(t.accountManagerName || '') + ' | ' +
          escapeHtml(t.email) + ' | ' + escapeHtml(t.username || '') + ' | ' +
          planBadge + ' | ' + statusBadge + ' | <span>رصيد</span> ' +
          Number(t.creditBalance || 0).toLocaleString('en-US') +
          (t.createdAt ? ' | ' + t.createdAt.slice(0, 10) : '') +
          '</div></div>' +
          '<div class="tenant-actions" style="gap:6px">' +
          '<button class="btn small primary" onclick="showSagTenantDetails(\'' + t.id + '\')">عرض الحساب</button>' +
          '<button class="btn small ' + (t.isActive ? 'danger' : 'green') + '" onclick="sagToggleTenant(\'' + t.id + '\', ' + (!t.isActive) + ')">' + (t.isActive ? 'إيقاف' : 'تفعيل') + '</button>' +
          '<button class="btn small ghost" onclick="openSagResetPassword(\'' + t.id + '\')">إعادة تعيين كلمة المرور</button>' +
          (t.isAdmin ? '' : '<button class="btn small danger" onclick="sagDeleteTenant(\'' + t.id + '\')">حذف</button>') +
          '</div></div>';
      }).join('');
    }

    function filterSagTenants() {
      const q = (document.getElementById('sagSearchInput').value || '').toLowerCase();
      const plan = document.getElementById('sagFilterPlan').value;
      const status = document.getElementById('sagFilterStatus').value;
      let filtered = sagAllTenants.filter(t => {
        const searchValue = [
          t.companyName, t.accountManagerName, t.email, t.username, t.phone
        ].filter(Boolean).join(' ').toLowerCase();
        if (q && !searchValue.includes(q)) return false;
        if (plan && t.plan !== plan) return false;
        if (status === 'active' && !t.isActive) return false;
        if (status === 'inactive' && t.isActive) return false;
        return true;
      });
      renderSagTenants(filtered);
    }

    const SAG_TENANT_TABS = ['company', 'users', 'drafts', 'presentations', 'exports', 'activity'];

    function sagTenantPaneId(tab) {
      return 'sagTenantTab' + tab.charAt(0).toUpperCase() + tab.slice(1);
    }

    function sagTenantBtnId(tab) {
      return 'sagTabBtn' + tab.charAt(0).toUpperCase() + tab.slice(1);
    }

    function showSagTenantTab(tab) {
      if (!SAG_TENANT_TABS.includes(tab)) tab = 'company';
      sagTenantActiveTab = tab;
      SAG_TENANT_TABS.forEach(name => {
        const pane = document.getElementById(sagTenantPaneId(name));
        const btn = document.getElementById(sagTenantBtnId(name));
        const active = name === tab;
        if (pane) pane.style.display = active ? '' : 'none';
        if (btn) { btn.classList.toggle('primary', active); btn.classList.toggle('ghost', !active); }
      });
      if (['drafts', 'presentations', 'exports', 'activity'].includes(tab)) {
        sagLoadTenantDataPane(sagCurrentTenantId, tab);
      }
    }

    async function sagLoadTenantDataPane(tenantId, tab) {
      const bodies = {
        drafts: 'sagTenantDraftsList',
        presentations: 'sagTenantPresentationsList',
        exports: 'sagTenantExportsList',
        activity: 'sagTenantActivityList'
      };
      const host = document.getElementById(bodies[tab]);
      if (!host || !tenantId || host.dataset.loaded === '1') return;
      showInlineLoader(host, 'جاري التحميل...');
      const data = await api('GET', '/api/admin/tenants/' + tenantId + '/' + tab).catch(() => ({ success: false }));
      if (!data || !data.success) { host.innerHTML = '<p class="tenant-hint">تعذر التحميل</p>'; return; }
      host.dataset.loaded = '1';
      if (tab === 'drafts') host.innerHTML = renderSagTenantDrafts(data.drafts || []);
      else if (tab === 'presentations') host.innerHTML = renderSagTenantPresentations(data.presentations || [], tenantId);
      else if (tab === 'exports') host.innerHTML = renderSagTenantExports(data.exports || []);
      else host.innerHTML = renderSagTenantActivity(data.activity || []);
    }

    function renderSagTenantDrafts(drafts) {
      if (!drafts.length) return '<p class="tenant-hint">لا توجد ملفات مشاريع</p>';
      return drafts.map(d => {
        const status = d.status === 'pending_approval' ? 'بانتظار التعميد' : d.status === 'approved' ? 'معتمد' : 'مسودة';
        const date = (d.updated_at || d.created_at || '').slice(0, 16).replace('T', ' ');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(d.title || 'مشروع بدون عنوان') + '</h3>' +
          '<div class="meta"><span>' + status + '</span> | ' + escapeHtml(date) + '</div></div></div>';
      }).join('');
    }

    function renderSagTenantPresentations(presentations, tenantId) {
      if (!presentations.length) return '<p class="tenant-hint">لا توجد عروض</p>';
      return presentations.map(p => {
        const status = p.status === 'pending_approval' ? 'بانتظار التعميد' : p.status === 'approved' ? 'معتمد' : 'مسودة';
        const date = (p.updatedAt || p.createdAt || '').slice(0, 16).replace('T', ' ');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(p.title || 'عرض بدون عنوان') + '</h3>' +
          '<div class="meta"><span>' + (p.slideCount || 0) + '</span> <span>شريحة</span> | <span>' + status + '</span> | ' + escapeHtml(date) + '</div></div>' +
          '<div class="tenant-actions">' +
          '<button type="button" class="btn small primary" onclick="openSagPresentationPreview(\'' + tenantId + '\', \'' + p.id + '\')">معاينة</button>' +
          '</div></div>';
      }).join('');
    }

    let sagPreviewSlides = [];
    let sagPreviewIndex = 0;

    async function openSagPresentationPreview(tenantId, presId) {
      showLoader('جاري تحميل العرض', '');
      try {
        const data = await api('GET', '/api/admin/tenants/' + tenantId + '/presentations/' + presId);
        if (!data.success) { toast('تعذر تحميل العرض'); return; }
        sagPreviewSlides = ((data.presentation && data.presentation.slidesData) || []).filter(s => s && s.html);
        if (!sagPreviewSlides.length) { toast('العرض بدون شرائح'); return; }
        sagPreviewIndex = 0;
        const existing = document.getElementById('sagPreviewModal');
        if (existing) existing.remove();
        const modal = document.createElement('div');
        modal.id = 'sagPreviewModal';
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
        modal.innerHTML = '<div class="sag-modal-card" style="max-width:1100px">' +
          '<div class="sag-modal-head"><h2>' + escapeHtml(data.presentation.title || 'عرض') + '</h2>' +
          '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' +
          '<span id="sagPreviewCounter" class="tenant-hint"></span>' +
          '<button class="btn ghost" onclick="document.getElementById(\'sagPreviewModal\').remove()">إغلاق</button>' +
          '</div></div>' +
          '<div id="sagPreviewWrap" style="overflow:hidden;border:1px solid var(--line);border-radius:12px;background:#fff">' +
          '<div id="sagPreviewStage"></div></div>' +
          '<div class="sag-modal-actions" style="justify-content:space-between">' +
          '<button type="button" class="btn ghost" onclick="sagPreviewStep(-1)">السابق</button>' +
          '<button type="button" class="btn ghost" onclick="sagPreviewStep(1)">التالي</button>' +
          '</div></div>';
        document.body.appendChild(modal);
        renderSagPreviewSlide();
        if (!window._sagPreviewResizeBound) {
          window._sagPreviewResizeBound = true;
          window.addEventListener('resize', () => { fitSagPreviewStage(); });
        }
      } finally {
        hideLoader();
      }
    }

    function sagPreviewStep(delta) {
      sagPreviewIndex += delta;
      renderSagPreviewSlide();
    }

    function renderSagPreviewSlide() {
      const host = document.getElementById('sagPreviewStage');
      const counter = document.getElementById('sagPreviewCounter');
      if (!host) return;
      const total = sagPreviewSlides.length;
      if (!total) return;
      sagPreviewIndex = Math.max(0, Math.min(sagPreviewIndex, total - 1));
      if (counter) counter.textContent = (sagPreviewIndex + 1) + ' / ' + total;
      host.innerHTML = sagPreviewSlides[sagPreviewIndex].html || '';
      host.querySelectorAll('img[data-team-logo]').forEach(img => {
        attachProjectFileThumbnail(img, img.dataset.teamLogo);
      });
      host.querySelectorAll('img[src*="/api/project-files/"]').forEach(img => {
        const match = /\/api\/project-files\/([^/?#]+)/.exec(img.getAttribute('src') || '');
        if (match) attachProjectFileThumbnail(img, match[1]);
      });
      fitSagPreviewStage();
    }

    function fitSagPreviewStage() {
      const wrap = document.getElementById('sagPreviewWrap');
      const stage = document.getElementById('sagPreviewStage');
      if (!wrap || !stage) return;
      const scale = Math.min(1, wrap.clientWidth / 1280);
      stage.style.width = '1280px';
      stage.style.transform = 'scale(' + scale + ')';
      stage.style.transformOrigin = 'top right';
      wrap.style.height = (720 * scale) + 'px';
    }

    function renderSagTenantExports(exports) {
      if (!exports.length) return '<p class="tenant-hint">لا توجد تصديرات</p>';
      return exports.map(e => {
        const date = (e.createdAt || '').slice(0, 16).replace('T', ' ');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(e.format || 'ملف') + '</h3>' +
          '<div class="meta">' + escapeHtml(date) + '</div></div></div>';
      }).join('');
    }

    function renderSagTenantActivity(activity) {
      if (!activity.length) return '<p class="tenant-hint">لا يوجد سجل تعديلات</p>';
      return activity.map(a => {
        const date = (a.created_at || '').slice(0, 16).replace('T', ' ');
        const target = a.target_type === 'presentation' ? 'عرض' : a.target_type === 'draft' ? 'ملف مشروع' : escapeHtml(a.target_type || '');
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(a.action || 'تعديل') + '</h3>' +
          '<div class="meta">' + escapeHtml(a.user_name || '') + ' | ' + escapeHtml(a.summary || '') + ' | ' + target + ' | ' + escapeHtml(date) + '</div></div></div>';
      }).join('');
    }

    async function showSagTenantDetails(tenantId) {
      const data = await api('GET', '/api/admin/tenants/' + tenantId + '/details');
      if (!data.success) { toast('فشل تحميل التفاصيل'); return; }
      const t = data.tenant;
      const c = data.counts;
      const users = data.users || [];
      if (sagCurrentTenantId !== tenantId) sagTenantActiveTab = 'company';
      sagCurrentTenantId = tenantId;
      sagModalUsers = users;
      const modal = document.getElementById('sagTenantModal');
      modal.style.display = 'flex';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div class="sag-modal-card">' +
        '<div class="sag-modal-head">' +
        '<h2>' + escapeHtml(t.companyName) + '</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagTenantModal\').style.display=\'none\'">إغلاق</button></div>' +
        '<div class="tenant-dashboard-cards" style="margin-bottom:14px">' +
        '<div class="tenant-dash-card stat"><h3>' + c.users + '</h3><p>مستخدمون</p></div>' +
        '<div class="tenant-dash-card stat"><h3>' + c.projects + '</h3><p>دراسات</p></div>' +
        '<div class="tenant-dash-card stat"><h3>' + c.presentations + '</h3><p>عروض</p></div>' +
        '<div class="tenant-dash-card stat"><h3>' + c.exports + '</h3><p>تصديرات</p></div>' +
        '</div>' +
        '<div class="sag-tabs">' +
        '<button type="button" id="sagTabBtnCompany" class="btn small primary" onclick="showSagTenantTab(\'company\')">معلومات الشركة</button>' +
        '<button type="button" id="sagTabBtnUsers" class="btn small ghost" onclick="showSagTenantTab(\'users\')">المستخدمون</button>' +
        '<button type="button" id="sagTabBtnDrafts" class="btn small ghost" onclick="showSagTenantTab(\'drafts\')">المشاريع</button>' +
        '<button type="button" id="sagTabBtnPresentations" class="btn small ghost" onclick="showSagTenantTab(\'presentations\')">العروض</button>' +
        '<button type="button" id="sagTabBtnExports" class="btn small ghost" onclick="showSagTenantTab(\'exports\')">التصديرات</button>' +
        '<button type="button" id="sagTabBtnActivity" class="btn small ghost" onclick="showSagTenantTab(\'activity\')">سجل التعديلات</button>' +
        '</div>' +
        '<div id="sagTenantTabCompany">' +
        '<form onsubmit="saveSagTenant(event, \'' + tenantId + '\')"><div class="tenant-grid">' +
        '<div class="tenant-field"><label>اسم الشركة</label><input id="sagDetailCompanyName" value="' + escapeHtml(t.companyName || '') + '" required></div>' +
        '<div class="tenant-field"><label>اسم مدير الحساب</label><input id="sagDetailManagerName" value="' + escapeHtml(t.accountManagerName || '') + '" required></div>' +
        '<div class="tenant-field"><label>البريد الإلكتروني</label><input type="email" id="sagDetailEmail" value="' + escapeHtml(t.email || '') + '" required></div>' +
        '<div class="tenant-field"><label>رقم الجوال</label><input id="sagDetailPhone" value="' + escapeHtml(t.phone || '') + '" required></div>' +
        '<div class="tenant-field"><label>اسم المستخدم</label><input id="sagDetailUsername" value="' + escapeHtml(t.username || '') + '" required></div>' +
        '<div class="tenant-field"><label>تاريخ إنشاء الحساب</label><p style="margin:0">' + escapeHtml(t.createdAt || '') + '</p></div>' +
        '<div class="tenant-field"><label>الباقة</label><select id="sagDetailPlan">' +
        '<option value="free"' + (t.plan === 'free' ? ' selected' : '') + '>Free</option>' +
        '<option value="pro"' + (t.plan === 'pro' ? ' selected' : '') + '>Pro</option>' +
        '<option value="enterprise"' + (t.plan === 'enterprise' ? ' selected' : '') + '>Enterprise</option></select></div>' +
        '<div class="tenant-field"><label>الرصيد</label><input type="number" id="sagDetailCredit" min="0" step="0.01" value="' + Number(t.creditBalance || 0) + '" required></div>' +
        '<div class="tenant-field full"><label>حالة الحساب</label><select id="sagDetailStatus">' +
        '<option value="active"' + (t.isActive ? ' selected' : '') + '>نشط</option>' +
        '<option value="inactive"' + (!t.isActive ? ' selected' : '') + '>موقوف</option></select></div>' +
        '</div><div class="sag-modal-actions">' +
        '<button type="submit" class="btn primary">حفظ بيانات الشركة</button></div></form>' +
        '</div>' +
        '<div id="sagTenantTabUsers" style="display:none">' +
        '<h3 class="dash-section-title">المستخدمون</h3>' +
        '<div id="sagTenantUsers">' + renderSagTenantUsers(tenantId, t.primaryUserId, users) + '</div>' +
        '<h3 class="dash-section-title" style="margin-top:18px">إضافة مستخدم</h3>' +
        '<form onsubmit="sagAddTenantUser(event, \'' + tenantId + '\')"><div class="tenant-grid">' +
        '<div class="tenant-field"><label>الاسم</label><input id="sagNewUserName" required></div>' +
        '<div class="tenant-field"><label>البريد الإلكتروني</label><input type="email" id="sagNewUserEmail" required></div>' +
        '<div class="tenant-field"><label>اسم المستخدم</label><input id="sagNewUserUsername" minlength="3" maxlength="40" required></div>' +
        '<div class="tenant-field"><label>رقم الجوال</label><input id="sagNewUserPhone" required></div>' +
        '<div class="tenant-field full"><label>الدور</label><select id="sagNewUserRole">' +
        '<option value="employee">موظف</option><option value="company_admin">أدمن شركة</option></select></div>' +
        '</div><div class="sag-modal-actions">' +
        '<button type="submit" class="btn primary">إضافة المستخدم</button></div></form>' +
        '</div>' +
        '<div id="sagTenantTabDrafts" style="display:none">' +
        '<h3 class="dash-section-title">المشاريع</h3><div id="sagTenantDraftsList"></div></div>' +
        '<div id="sagTenantTabPresentations" style="display:none">' +
        '<h3 class="dash-section-title">العروض</h3><div id="sagTenantPresentationsList"></div></div>' +
        '<div id="sagTenantTabExports" style="display:none">' +
        '<h3 class="dash-section-title">التصديرات</h3><div id="sagTenantExportsList"></div></div>' +
        '<div id="sagTenantTabActivity" style="display:none">' +
        '<h3 class="dash-section-title">سجل التعديلات</h3><div id="sagTenantActivityList"></div></div>' +
        '</div>';
      showSagTenantTab(sagTenantActiveTab);
    }

    function renderSagTenantUsers(tenantId, primaryUserId, users) {
      if (!users.length) return '<p class="tenant-hint">لا يوجد مستخدمون</p>';
      return users.map(user => {
        const primary = user.id === primaryUserId;
        return '<div class="tenant-presentation-card"><div><h3>' + escapeHtml(user.name) +
          (primary ? ' <span style="font-size:11px;color:var(--p)">مدير الحساب</span>' : '') + '</h3>' +
          '<div class="meta">' + escapeHtml(user.email) + ' | ' + escapeHtml(user.username || '') +
          ' | ' + escapeHtml(user.phone || '') + ' | <span>' +
          (user.role === 'company_admin' ? 'أدمن شركة' : 'موظف') + '</span> | <span>' +
          (user.is_active ? 'نشط' : 'موقوف') + '</span></div></div>' +
          '<div class="tenant-actions">' +
          '<button type="button" class="btn small ghost" onclick="openSagUserEdit(\'' +
            tenantId + '\', \'' + user.id + '\')">تعديل</button>' +
          '<button type="button" class="btn small primary" onclick="openSagUserPermissions(\'' +
            tenantId + '\', \'' + user.id + '\', \'' + escapeHtml(user.name) + '\')">صلاحيات</button>' +
          (primary ? '' : '<button type="button" class="btn small ghost" onclick="sagSetPrimaryUser(\'' +
            tenantId + '\', \'' + user.id + '\')">تعيين مدير الحساب</button>') +
          '<button type="button" class="btn small ' + (user.is_active ? 'danger' : 'green') +
          '" onclick="sagToggleTenantUser(\'' + tenantId + '\', \'' + user.id + '\', ' +
          (!user.is_active) + ')">' + (user.is_active ? 'إيقاف' : 'تفعيل') + '</button>' +
          (primary ? '' : '<button type="button" class="btn small danger" onclick="sagDeleteTenantUser(\'' +
            tenantId + '\', \'' + user.id + '\')">حذف</button>') +
          '</div></div>';
      }).join('');
    }

    async function saveSagTenant(event, tenantId) {
      event.preventDefault();
      const payload = {
        companyName: document.getElementById('sagDetailCompanyName').value.trim(),
        accountManagerName: document.getElementById('sagDetailManagerName').value.trim(),
        email: document.getElementById('sagDetailEmail').value.trim().toLowerCase(),
        phone: document.getElementById('sagDetailPhone').value.trim(),
        username: document.getElementById('sagDetailUsername').value.trim().toLowerCase(),
        plan: document.getElementById('sagDetailPlan').value,
        creditBalance: document.getElementById('sagDetailCredit').value,
        isActive: document.getElementById('sagDetailStatus').value === 'active'
      };
      const data = await api('PUT', '/api/admin/tenants/' + tenantId, payload);
      if (!data.success) {
        toast(data.error || 'تعذر حفظ بيانات الشركة');
        return;
      }
      toast('تم حفظ بيانات الشركة');
      await openTenantAdmin();
      await showSagTenantDetails(tenantId);
    }

    async function sagAddTenantUser(event, tenantId) {
      event.preventDefault();
      showLoader('جاري إضافة المستخدم', 'إنشاء الحساب ورابط كلمة المرور', 15);
      try {
        const data = await api('POST', '/api/admin/tenants/' + tenantId + '/users', {
          name: document.getElementById('sagNewUserName').value.trim(),
          email: document.getElementById('sagNewUserEmail').value.trim().toLowerCase(),
          username: document.getElementById('sagNewUserUsername').value.trim().toLowerCase(),
          phone: document.getElementById('sagNewUserPhone').value.trim(),
          role: document.getElementById('sagNewUserRole').value,
          useSetupLink: true
        });
        if (!data.success) {
          toast(data.error || 'تعذر إضافة المستخدم');
          return;
        }
        if (data.setupUrl) await copySagText(data.setupUrl);
        toast('تمت إضافة المستخدم');
        await showSagTenantDetails(tenantId);
      } finally {
        hideLoader();
      }
    }

    async function sagSetPrimaryUser(tenantId, userId) {
      const data = await api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId, { isPrimary: true });
      if (!data.success) {
        toast(data.error || 'تعذر تغيير مدير الحساب');
        return;
      }
      toast('تم تغيير مدير الحساب');
      await openTenantAdmin();
      await showSagTenantDetails(tenantId);
    }

    async function sagToggleTenantUser(tenantId, userId, isActive) {
      const data = await api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId, { is_active: isActive });
      if (!data.success) {
        toast(data.error || 'تعذر تحديث المستخدم');
        return;
      }
      toast(isActive ? 'تم تفعيل المستخدم' : 'تم إيقاف المستخدم');
      await showSagTenantDetails(tenantId);
    }

    async function sagDeleteTenantUser(tenantId, userId) {
      if (!confirm('حذف المستخدم نهائياً؟')) return;
      const data = await api('DELETE', '/api/admin/tenants/' + tenantId + '/users/' + userId);
      if (!data.success) {
        toast(data.error || 'تعذر حذف المستخدم');
        return;
      }
      toast('تم حذف المستخدم');
      await showSagTenantDetails(tenantId);
    }

    let editingSagUserPermissions = null;

    async function openSagUserPermissions(tenantId, userId, userName) {
      const [permData, sectionData] = await Promise.all([
        api('GET', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/permissions'),
        api('GET', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/field-sections')
      ]);
      if (!permData.success || !sectionData.success) { toast('تعذر تحميل الصلاحيات'); return; }
      const perms = permData.permissions || {};
      const keys = permData.availableKeys || [];
      const sections = sectionData.sections || {};
      const availableSections = sectionData.available || [];
      editingSagUserPermissions = { tenantId, userId, userName, availableSections };

      const permRows = keys.map(key => {
        const label = PERMISSION_LABELS[key] || key;
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + label + '</label>' +
          '<input type="checkbox" id="sperm_' + key + '" ' + (perms[key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const sectionRows = availableSections.map(s => {
        return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)">' +
          '<label>' + escapeHtml(s.label) + '</label>' +
          '<input type="checkbox" id="ssection_' + s.key + '" ' + (sections[s.key] ? 'checked' : '') + '>' +
          '</div>';
      }).join('');

      const existing = document.getElementById('sagUserPermissionsModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'sagUserPermissionsModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:16px;padding:20px;max-width:520px;width:100%;max-height:85vh;overflow:auto">' +
        '<div class="sag-modal-head">' +
        '<h2>صلاحيات: ' + escapeHtml(userName) + '</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagUserPermissionsModal\').remove()">إغلاق</button></div>' +
        '<h4 style="margin:12px 0 8px;color:var(--pd)">صلاحيات التطبيق</h4>' +
        permRows +
        '<h4 style="margin:16px 0 8px;color:var(--pd)">أقسام فورم المشروع</h4>' +
        sectionRows +
        '<div class="sag-modal-actions">' +
        '<button class="btn primary" onclick="saveSagUserPermissions()">حفظ الصلاحيات</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    async function saveSagUserPermissions() {
      if (!editingSagUserPermissions) return;
      const { tenantId, userId } = editingSagUserPermissions;
      const permissions = {};
      Object.keys(PERMISSION_LABELS).forEach(key => {
        const cb = document.getElementById('sperm_' + key);
        permissions[key] = cb ? cb.checked : false;
      });
      const sections = {};
      (editingSagUserPermissions.availableSections || []).forEach(s => {
        const cb = document.getElementById('ssection_' + s.key);
        sections[s.key] = cb ? cb.checked : false;
      });
      showLoader('جاري حفظ الصلاحيات', '');
      const [permRes, sectionRes] = await Promise.all([
        api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/permissions', { permissions }),
        api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId + '/field-sections', { sections })
      ]);
      hideLoader();
      const modal = document.getElementById('sagUserPermissionsModal');
      if (modal) modal.remove();
      if (permRes.success && sectionRes.success) { toast('تم حفظ الصلاحيات'); }
      else { toast(permRes.error || sectionRes.error || 'فشل الحفظ'); }
    }

    function openSagUserEdit(tenantId, userId) {
      const user = (sagModalUsers || []).find(u => u.id === userId);
      if (!user) { toast('تعذر تحميل بيانات المستخدم'); return; }
      const existing = document.getElementById('sagUserEditModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'sagUserEditModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:16px;padding:20px;max-width:560px;width:100%;max-height:85vh;overflow:auto">' +
        '<div class="sag-modal-head">' +
        '<h2>تعديل المستخدم</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagUserEditModal\').remove()">إغلاق</button></div>' +
        '<div class="tenant-grid">' +
        '<div class="tenant-field"><label>الاسم</label><input id="sagEditUserName" value="' + escapeHtml(user.name || '') + '" required></div>' +
        '<div class="tenant-field"><label>البريد الإلكتروني</label><input type="email" id="sagEditUserEmail" value="' + escapeHtml(user.email || '') + '" required></div>' +
        '<div class="tenant-field"><label>اسم المستخدم</label><input id="sagEditUserUsername" value="' + escapeHtml(user.username || '') + '" minlength="3" maxlength="40" required></div>' +
        '<div class="tenant-field"><label>رقم الجوال</label><input id="sagEditUserPhone" value="' + escapeHtml(user.phone || '') + '"></div>' +
        '<div class="tenant-field full"><label>كلمة مرور جديدة</label>' +
        '<div style="display:flex;gap:8px">' +
        '<input type="text" id="sagEditUserPassword" minlength="10" autocomplete="new-password" placeholder="فارغة للإبقاء على الحالية" style="flex:1;min-width:0">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagEditUserPassword\').value = generateStrongPassword()">توليد تلقائي</button>' +
        '</div></div>' +
        '<div class="tenant-field full"><label>الدور</label><select id="sagEditUserRole">' +
        '<option value="employee"' + (user.role !== 'company_admin' ? ' selected' : '') + '>موظف</option>' +
        '<option value="company_admin"' + (user.role === 'company_admin' ? ' selected' : '') + '>أدمن شركة</option></select></div>' +
        '</div>' +
        '<div class="sag-modal-actions">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagUserEditModal\').remove()">إلغاء</button>' +
        '<button type="button" class="btn primary" onclick="sagSaveUserEdit(\'' + tenantId + '\', \'' + user.id + '\')">حفظ</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    async function sagSaveUserEdit(tenantId, userId) {
      const payload = {
        name: document.getElementById('sagEditUserName').value.trim(),
        email: document.getElementById('sagEditUserEmail').value.trim().toLowerCase(),
        username: document.getElementById('sagEditUserUsername').value.trim().toLowerCase(),
        phone: document.getElementById('sagEditUserPhone').value.trim(),
        role: document.getElementById('sagEditUserRole').value
      };
      const newPassword = document.getElementById('sagEditUserPassword').value;
      if (newPassword) {
        if (newPassword.length < 10) {
          toast('كلمة المرور 10 أحرف على الأقل');
          return;
        }
        payload.password = newPassword;
      }
      if (!payload.name || !payload.email || !payload.username) {
        toast('الاسم والبريد واسم المستخدم مطلوبة');
        return;
      }
      showLoader('جاري حفظ بيانات المستخدم', '');
      try {
        const data = await api('PUT', '/api/admin/tenants/' + tenantId + '/users/' + userId, payload);
        if (!data.success) {
          toast(data.error || 'تعذر حفظ بيانات المستخدم');
          return;
        }
        document.getElementById('sagUserEditModal').remove();
        toast('تم حفظ بيانات المستخدم');
        await showSagTenantDetails(tenantId);
      } finally {
        hideLoader();
      }
    }

    async function sagToggleTenant(tenantId, isActive) {
      const data = await api('PUT', '/api/admin/tenants/' + tenantId, { is_active: isActive });
      if (data.success) { toast(isActive ? 'تم التفعيل' : 'تم التعطيل'); openTenantAdmin(); }
      else { toast(data.error || 'فشل'); }
    }

    async function sagDeleteTenant(tenantId) {
      if (!confirm('حذف الشركة وكل بياناتها نهائياً؟')) return;
      const data = await api('DELETE', '/api/admin/tenants/' + tenantId);
      if (data.success) { toast('تم حذف الشركة'); openTenantAdmin(); }
      else { toast(data.error || 'فشل الحذف'); }
    }

    function openSagResetPassword(tenantId) {
      const existing = document.getElementById('sagResetPasswordModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'sagResetPasswordModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
      modal.innerHTML = '<div style="background:#fff;border-radius:20px;padding:28px;max-width:520px;width:100%">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">' +
        '<h2 style="margin:0">إعادة تعيين كلمة المرور</h2>' +
        '<button class="btn ghost" onclick="document.getElementById(\'sagResetPasswordModal\').remove()">إغلاق</button></div>' +
        '<div class="tenant-field"><label>كلمة مرور جديدة</label>' +
        '<div style="display:flex;gap:8px">' +
        '<input type="text" id="sagResetPasswordValue" minlength="10" autocomplete="new-password" style="flex:1;min-width:0">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagResetPasswordValue\').value = generateStrongPassword()">توليد تلقائي</button>' +
        '</div></div>' +
        '<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:16px;flex-wrap:wrap">' +
        '<button type="button" class="btn ghost" onclick="document.getElementById(\'sagResetPasswordModal\').remove()">إلغاء</button>' +
        '<button type="button" class="btn ghost" onclick="sagResetPasswordWithLink(\'' + tenantId + '\')">رابط تعيين</button>' +
        '<button type="button" class="btn primary" onclick="sagResetPasswordWithValue(\'' + tenantId + '\')">اعتماد</button>' +
        '</div></div>';
      document.body.appendChild(modal);
    }

    async function sagResetPasswordWithValue(tenantId) {
      const password = document.getElementById('sagResetPasswordValue').value;
      if (!password || password.length < 10) {
        toast('كلمة المرور 10 أحرف على الأقل');
        return;
      }
      showLoader('جاري تعيين كلمة المرور', 'حفظ كلمة المرور الجديدة', 15);
      try {
        const data = await api('POST', '/api/admin/tenants/' + tenantId + '/reset-password', { password });
        if (!data.success) {
          toast(data.error || 'تعذر تعيين كلمة المرور');
          return;
        }
        document.getElementById('sagResetPasswordModal').remove();
        toast('تم تعيين كلمة المرور');
      } finally {
        hideLoader();
      }
    }

    async function sagResetPasswordWithLink(tenantId) {
      showLoader('جاري إنشاء رابط كلمة المرور', 'تأمين رابط جديد للاستخدام مرة واحدة', 15);
      try {
        const data = await api('POST', '/api/admin/tenants/' + tenantId + '/reset-password', { useSetupLink: true });
        if (!data.success) {
          toast(data.error || 'تعذر إنشاء الرابط');
          return;
        }
        await copySagText(data.setupUrl);
        document.getElementById('sagResetPasswordModal').remove();
        toast('تم إنشاء رابط كلمة المرور');
      } finally {
        hideLoader();
      }
    }





    function escapeHtml(text) {
      if (!text) return '';
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function formatUsageCost(usd) {
      const value = Number(usd) || 0;
      const digits = value >= 1 ? 2 : value >= 0.01 ? 2 : 4;
      const text = '$' + (value >= 1
        ? value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : value.toFixed(digits));
      return '<span dir="ltr">' + text + '</span>';
    }

    function aiReconcileStatusText(entry) {
      if (!entry || typeof entry !== 'object') return '';
      const state = entry.state || '';
      if (state === 'pending') return 'قيد الاستكمال';
      if (state === 'needs_review') return 'تحتاج مطابقة';
      if (state === 'settled') return 'التكلفة المسجلة';
      const pending = Number(entry.pending || 0) + Number(entry.in_flight || 0);
      const review = Number(entry.unresolved || 0) + Number(entry.needs_review || 0);
      if (pending > 0) return 'قيد الاستكمال';
      if (review > 0) return 'تحتاج مطابقة';
      return '';
    }

    async function fetchAiUsageEvents(draftId, page, pageSize) {
      const params = [];
      if (draftId) params.push('draftId=' + encodeURIComponent(draftId));
      params.push('page=' + encodeURIComponent(page || 1));
      params.push('pageSize=' + encodeURIComponent(pageSize || 20));
      return api('GET', '/api/ai-usage?' + params.join('&')).catch(() => null);
    }

    async function reconcileAiUsage(draftId, presentationId, includeSettled) {
      const payload = {};
      if (draftId) payload.draftId = draftId;
      if (presentationId) payload.presentationId = presentationId;
      if (includeSettled) payload.includeSettled = true;
      return api('POST', '/api/ai-usage/reconcile', payload).catch(() => null);
    }


    function renderTrainingChat() {
      const log = document.getElementById('trainingChatLog');
      if (!log) return;
      if (!trainingChatHistory.length) {
        log.innerHTML = '<div style="text-align:center;padding:32px 20px;"><h3 style="margin:0 0 8px;color:var(--accent);">وكيل الإدارة الذكي</h3></div>';
        return;
      }
      log.innerHTML = trainingChatHistory.map(m => {
        if (m.role === 'user') {
          return '<div class="msg user">' + escapeHtml(m.text) + '</div>';
        }
        // AI message — check for executed actions
        let html = '<div class="msg ai">' + escapeHtml(m.text).replace(/\n/g, '<br>');
        if (m.actions && m.actions.length) {
          html += '<div style="margin-top:10px;">';
          m.actions.forEach(a => {
            const isOk = a.status === 'success';
            const icon = isOk ? '' : '';
            const bg = isOk ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)';
            const border = isOk ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)';
            const color = isOk ? '#16a34a' : '#dc2626';
            html += '<div style="background:' + bg + ';border:1px solid ' + border + ';border-radius:8px;padding:8px 12px;margin-top:6px;font-size:12px;">';
            html += '<span style="color:' + color + ';font-weight:600;">' + icon + ' ' + escapeHtml(a.message || a.tool || '') + '</span>';
            if (a.changes && Object.keys(a.changes).length) {
              html += '<div style="margin-top:4px;font-size:11px;opacity:0.8;">';
              Object.entries(a.changes).forEach(([k, v]) => {
                if (v && typeof v === 'object' && 'old' in v) {
                  html += '<div>' + escapeHtml(k) + ': <s>' + escapeHtml(String(v.old || '—')) + '</s> إلى <strong>' + escapeHtml(String(v.new)) + '</strong></div>';
                }
              });
              html += '</div>';
            }
            html += '</div>';
          });
          html += '</div>';
        }
        html += '</div>';
        return html;
      }).join('');
      log.scrollTop = log.scrollHeight;
    }

    function buildAgentWorkspacePayload() {
      return {
        presentationId: tenantPresentationId,
        projectData: tenantProjectData || {},
        slidePlan: tenantSlidePlan || {},
        slidesData: Array.isArray(tenantSlidesData) ? tenantSlidesData : [],
        creativeImages: tenantCreativeImages || {},
        title: (tenantProjectData && (tenantProjectData.project_name || tenantProjectData.projectName)) || 'عرض بدون عنوان'
      };
    }

    async function applyAgentWorkspaceActions(actions) {
      checkpointPresentationUndo();
      let changed = false;
      let planChanged = false;
      let dataChanged = false;
      (actions || []).forEach(action => {
        const data = action && action.data;
        if (!data || typeof data !== 'object') return;
        if (Array.isArray(data.slidesData)) {
          tenantSlidesData = data.slidesData;
          changed = true;
        }
        if (data.presentationId) {
          tenantPresentationId = data.presentationId;
          changed = true;
        }
        if (data.revision) {
          tenantPresentationRevision = Number(data.revision) || tenantPresentationRevision;
        }
        if (data.projectData && typeof data.projectData === 'object') {
          tenantProjectData = { ...(tenantProjectData || {}), ...data.projectData };
          dataChanged = true;
        }
        if (data.slidePlan && typeof data.slidePlan === 'object' && Array.isArray(data.slidePlan.slides)) {
          tenantSlidePlan = data.slidePlan;
          planChanged = true;
        }
        if (data.url && data.exportId) {
          window.open(data.url, '_blank', 'noopener');
        }
      });
      if (dataChanged) {
        const form = document.getElementById('tenantProjectForm');
        if (form) {
          Object.entries(tenantProjectData || {}).forEach(([key, value]) => {
            const input = form.querySelector('[data-key="' + key + '"]');
            if (input && input.type !== 'file') input.value = value;
          });
          refreshLocationTables();
        }
      }
      if (changed) {
        renumberTenantSlides();
        renderTenantSlides();
        renderTenantSlidesSidebar();
        updateTenantChatSlideSelect();
        triggerAutoSaveDraft();
      }
      if (changed || planChanged || dataChanged) triggerAutoSaveDraft();
      if (changed || planChanged) checkpointPresentationUndo();
      return changed || planChanged || dataChanged;
    }