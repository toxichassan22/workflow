/* 16-presentations-export.js - index.html lines 26148-27658, shared global scope, classic scripts in order */

    async function openExistingPresentation(presId) {
      const data = await api('GET', '/api/presentations/' + presId);
      if (!data.success || !data.presentation) { toast('فشل تحميل العرض'); return; }
      const p = data.presentation;
      setDraftDirty(false);
      tenantPresentationId = p.id;
      tenantPresentationRevision = Number(p.revision) || 0;
      tenantDraftRevision = Number(p.draftRevision) || 0;
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
        const stMeta = typeof getProposalStatusMeta === 'function' ? getProposalStatusMeta(d.status) : { cls: 'status-draft', label: d.status };
        const statusText = typeof getProposalStatusLabel === 'function' ? getProposalStatusLabel(d.status) : (stMeta.label || 'مسودة');
        const date = (d.updated_at || d.created_at || '').slice(0, 16).replace('T', ' ');
        const projectMapsCost = Number(projectCost?.maps_cost_sar) || 0;
        const costText = '<span>التكلفة:</span> ' + (projectCost ? formatUsageCost(projectCost.cost_sar || 0) + (projectMapsCost > 0 ? ' (<span>خرائط:</span> ' + formatUsageCost(projectMapsCost) + ')' : '') : '—');
        const fieldsHtml = recovery ? '<span>' + recovery.fieldCount + '</span> <span>حقل ممتلئ</span>' : '';
        // Admins (approvals permission) approve directly whenever they want; employees
        // only send a request and the draft stays pending until an admin approves it.
        const canReview = hasPermission('approvals');
        const isApproved = d.status === 'approved' || d.status === 'sections_approved';
        const isPending = d.status === 'pending_approval' || d.status === 'section_approval_pending' || d.status === 'generation_approval_pending' || d.status === 'final_approval_pending';
        const approveBtn = (isApproved || (isPending && !canReview)) ? ''
          : '<button class="btn small green" onclick="' +
          (canReview ? 'approveProjectDraftById' : 'requestProjectDraftApprovalById') +
          '(\'' + d.id + '\')">اعتماد</button>';
        const isArchived = d.status === 'archived';
        const archiveBadge = isArchived
          ? '<span class="proposal-status-badge status-archived" title="محفوظ لمدة 365 يوماً وفق سياسة الحفظ">أرشيف (محفوظ 365 يوماً)</span>'
          : '';
        const statusBadgeHtml = archiveBadge || ('<span class="proposal-status-badge ' + stMeta.cls + '">' + escapeHtml(statusText) + '</span>');
        const copyBtn = hasPermission('copy_presentation')
          ? '<button class="btn small ghost" onclick="copyProjectDraftById(\'' + d.id + '\')">نسخ العرض</button>'
          : '';
        const actionsHtml = isArchived
          ? '<button class="btn small primary" onclick="restoreProposalById(\'' + d.id + '\')">استعادة</button>' +
            '<button class="btn small ghost" onclick="showDraftEditLog(\'' + d.id + '\')">سجل التعديلات</button>'
          : '<button class="btn small primary" onclick="openProjectDraftById(\'' + d.id + '\')">فتح المشروع</button>' +
            copyBtn +
            '<button class="btn small ghost" onclick="showDraftEditLog(\'' + d.id + '\')">سجل التعديلات</button>' +
            approveBtn +
            '<button class="btn small ghost danger" onclick="archiveProposalById(\'' + d.id + '\')">أرشفة</button>';
        return '<div class="tenant-presentation-card" data-draft-id="' + d.id + '" style="background:' + (isArchived ? '#f1f5f9' : '#f8fafc') + ';border:1px solid ' +
          (isArchived ? '#94a3b8' : (recovery?.isEmpty ? '#f59e0b' : '#cbd5e1')) + ';margin-bottom:12px">' +
          '<div><h3>' + escapeHtml(title) + '</h3><div class="meta">' + statusBadgeHtml + ' | ' + escapeHtml(date) +
          (fieldsHtml ? ' | ' + fieldsHtml : '') + ' | ' + costText + '</div></div><div class="tenant-actions">' +
          actionsHtml +
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
        // The form schema does not depend on the draft, so its two GETs ride in
        // parallel with the (much heavier) draft fetch instead of queuing behind it.
        const formSchemaRequest = Promise.all([
          api('GET', '/api/fields'),
          api('GET', '/api/field-sections')
        ]);
        const resp = await api('GET', '/api/project-draft/' + encodeURIComponent(draftId));
        hideLoader();
        if (!resp.success || !resp.draft) {
          toast(resp.error || 'تعذر تحميل المسودة');
          return false;
        }

        const draft = resp.draft;
        setDraftDirty(false);
        tenantDraftRevision = Number(draft.revision) || 0;
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
        await loadTenantProjectForm(formSchemaRequest);
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

    async function copyProjectDraftById(draftId) {
      if (!draftId) return;
      const newTitle = prompt(WFT('admin.new_deck_name', 'اسم العرض الجديد:'));
      if (!newTitle || !newTitle.trim()) return;
      const res = await api('POST', '/api/project-draft/copy', { draftId, newTitle: newTitle.trim() });
      if (res && res.success) {
        toast(WFT('proposal.cloned_with_name', 'تم نسخ العرض بنجاح باسم:') + ' ' + (res.copy?.title || newTitle));
        tenantArchiveCache = null;
        openTenantPresentations(true);
      } else {
        toast(res?.error || 'فشل نسخ العرض');
      }
    }

    async function archiveProposalById(draftId) {
      if (!draftId) return;
      if (!confirm(WFT('proposal.archive_confirm', 'هل تريد أرشفة هذا العرض؟ سيتم حفظه في الأرشيف لمدة 365 يوماً مع إمكانية استعادته.'))) return;
      const res = await api('POST', '/api/project-draft/' + encodeURIComponent(draftId) + '/transition-status', {
        targetStatus: 'archived',
        reason: 'أرشفة العرض من قائمة المشاريع'
      });
      if (res && res.success) {
        toast(WFT('proposal.archived', 'تم نقل العرض إلى الأرشيف'));
        tenantArchiveCache = null;
        openTenantPresentations(true);
      } else {
        toast(res?.error || 'فشل أرشفة العرض');
      }
    }

    async function restoreProposalById(draftId) {
      if (!draftId) return;
      const res = await api('POST', '/api/project-draft/' + encodeURIComponent(draftId) + '/transition-status', {
        targetStatus: 'draft',
        reason: 'استعادة العرض من الأرشيف'
      });
      if (res && res.success) {
        toast(WFT('proposal.restored', 'تمت استعادة العرض من الأرشيف'));
        tenantArchiveCache = null;
        openTenantPresentations(true);
      } else {
        toast(res?.error || 'فشل استعادة العرض');
      }
    }

    async function deleteProjectDraftById(draftId) {
      if (!confirm(WFT('admin.confirm_delete_draft', 'هل أنت تأكد من حذف هذه المسودة؟'))) return;
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
      try {
        const backupSaved = await saveProjectAsDraftNow(true, false);
        if (!backupSaved) console.error('[DRAFT BACKUP] save reported failure');
      } catch (backupError) {
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
        const fileName = data.url.split('/').pop() || ('presentation.' + format);
        let downloadRecord = null;
        try {
          const recResp = await api('POST', '/api/downloads', {
            fileName,
            presentationId: tenantPresentationId,
            draftId: tenantProjectData && (tenantProjectData.draftId || tenantProjectData.draft_id),
            format,
            versionLabel: 'v' + (tenantPresentationRevision || 1),
            exportId: data.exportId || null
          });
          if (recResp && recResp.success) downloadRecord = recResp.download;
        } catch (recErr) {
          console.warn('Download ledger record error:', recErr);
        }

        const token = getTenantToken();
        const resp = await fetch(data.url, { headers: token ? { 'Authorization': 'Bearer ' + token } : {} });
        if (!resp.ok) throw new Error('Download failed');
        const blob = await readBlobWithProgress(resp, 84, 98);
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);

        if (downloadRecord && downloadRecord.id) {
          api('POST', '/api/downloads/' + encodeURIComponent(downloadRecord.id) + '/delivered').catch(() => {});
        }

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

    async function showFinalApprovalModal() {
      if (!tenantPresentationId) {
        toast(WFT('proposal.open_first_for_final', 'افتح عرضاً أولاً لطلب الاعتماد النهائي'));
        return;
      }
      let approvals = [];
      try {
        const resp = await api('GET', '/api/final-file-approvals?presentationId=' + encodeURIComponent(tenantPresentationId));
        if (resp && resp.success) approvals = resp.approvals || [];
      } catch (err) {
        console.warn('Final file approvals fetch:', err);
      }

      const pendingApproval = approvals.find(a => a.status === 'pending');
      const latestApproved = approvals.find(a => a.status === 'approved');
      const canApprove = hasPermission('approve_final_file');
      const isCompanyAdmin = Boolean(tenantUser && tenantUser.isAdmin) ||
        ((tenantUser && tenantUser._userRole) === 'company_admin');
      const isOwnRequest = Boolean(pendingApproval && pendingApproval.requested_by &&
        String(pendingApproval.requested_by) === String((tenantUser && tenantUser._userId) || ''));
      const canDecide = canApprove && (!isOwnRequest || isCompanyAdmin);

      const modal = document.createElement('div');
      modal.id = 'finalApprovalModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;';
      modal.innerHTML =
        '<div style="background:#fff;border-radius:16px;max-width:540px;width:100%;padding:24px;box-shadow:0 12px 32px rgba(0,0,0,.2);direction:rtl;text-align:right;">' +
        '<h3 style="margin:0 0 8px;color:#1a3a52;font-size:18px;">اعتماد الملف النهائي</h3>' +
        '<p style="margin:0 0 16px;color:#64748b;font-size:13px;">بوابة الاعتماد الثالثة — قفل إصدار العرض وختم البصمة الرقمية للملف</p>' +
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px;margin-bottom:16px;font-size:13px;line-height:1.8;">' +
        '<div><span style="color:#64748b;">العرض الحالي:</span> <strong>' + escapeHtml(tenantPresentationTitle || 'عرض بدون عنوان') + '</strong></div>' +
        '<div><span style="color:#64748b;">رقم الإصدار:</span> <strong>v' + (tenantPresentationRevision || 1) + '</strong></div>' +
        (latestApproved
          ? '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;color:#1c7a2e;">' +
            '<strong>معتمد نهائياً:</strong> معتمد بواسطة ' + escapeHtml(latestApproved.decided_by_name || '') +
            (latestApproved.stamped_file ? '<br><span style="font-size:11px;color:#475569;">البصمة الرقمية: ' + escapeHtml(latestApproved.stamped_file) + '</span>' : '') +
            '</div>'
          : '') +
        (pendingApproval
          ? '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;color:#a67c00;">' +
            'يوجد طلب اعتماد قيد المراجعة مقدم من ' + escapeHtml(pendingApproval.requested_by_name || '') +
            '</div>'
          : '') +
        '</div>' +
        '<div style="display:flex;gap:10px;justify-content:flex-end;">' +
        '<button type="button" id="closeFinalApproveBtn" class="btn ghost" style="padding:8px 18px;">إغلاق</button>' +
        (pendingApproval && canDecide
          ? '<button type="button" id="decideFinalApproveBtn" class="btn primary green" style="padding:8px 20px;">اعتماد وختم الملف</button>'
          : (!pendingApproval && !latestApproved
            ? '<button type="button" id="requestFinalApproveBtn" class="btn primary" style="padding:8px 20px;">إرسال طلب الاعتماد</button>'
            : '')) +
        '</div></div>';

      document.body.appendChild(modal);

      const close = () => { if (modal.parentNode) modal.parentNode.removeChild(modal); };
      const closeBtn = modal.querySelector('#closeFinalApproveBtn');
      if (closeBtn) closeBtn.onclick = close;

      const reqBtn = modal.querySelector('#requestFinalApproveBtn');
      if (reqBtn) {
        reqBtn.onclick = async () => {
          reqBtn.disabled = true;
          const res = await api('POST', '/api/presentations/' + encodeURIComponent(tenantPresentationId) + '/final-approval/request', {
            revision: tenantPresentationRevision || 1
          });
          if (res && res.success) {
            toast(WFT('proposal.final_approval_requested', 'تم إرسال طلب اعتماد الملف النهائي'));
            close();
          } else {
            toast(res?.error || 'فشل إرسال طلب الاعتماد');
            reqBtn.disabled = false;
          }
        };
      }

      const decideBtn = modal.querySelector('#decideFinalApproveBtn');
      if (decideBtn) {
        decideBtn.onclick = async () => {
          decideBtn.disabled = true;
          const res = await api('POST', '/api/final-file-approvals/' + encodeURIComponent(pendingApproval.id) + '/decision', {
            decision: 'approved'
          });
          if (res && res.success) {
            toast(WFT('proposal.final_approval_sealed', 'تم اعتماد وختم الملف النهائي بنجاح'));
            close();
          } else {
            toast(res?.error || 'فشل الاعتماد');
            decideBtn.disabled = false;
          }
        };
      }
    }

    async function showDownloadsLibraryModal(presentationId) {
      const scopePresentationId = presentationId || tenantPresentationId;
      let downloads = [];
      try {
        const query = scopePresentationId ? '?presentationId=' + encodeURIComponent(scopePresentationId) : '';
        const resp = await api('GET', '/api/downloads' + query);
        if (resp && resp.success) downloads = resp.downloads || [];
      } catch (err) {
        console.warn('Load downloads error:', err);
      }

      const modal = document.createElement('div');
      modal.id = 'downloadsLibraryModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center;padding:16px;';
      const rows = downloads.length
        ? downloads.map(d => {
            const date = (d.downloaded_at || d.created_at || d.generated_at || '').slice(0, 16).replace('T', ' ');
            const approved = d.approval_status === 'approved';
            const statusLabel = approved
              ? (d.downloaded_at ? 'معتمد — تم التحميل' : 'معتمد — متاح للتحميل')
              : 'بانتظار الاعتماد النهائي';
            const statusStyle = approved
              ? 'background:#eef7ee;color:#1c7a2e;'
              : 'background:#fef3c7;color:#92400e;';
            const safeName = escapeHtml(d.file_name || 'ملف');
            const safeUrl = approved && d.download_url ? String(d.download_url) : '';
            return '<tr style="border-bottom:1px solid #e2e8f0;">' +
              '<td style="padding:10px 8px;font-weight:600;">' + safeName + '</td>' +
              '<td style="padding:10px 8px;text-transform:uppercase;">' + escapeHtml(d.format || '') + '</td>' +
              '<td style="padding:10px 8px;">' + escapeHtml(d.version_label || 'v1') + '</td>' +
              '<td style="padding:10px 8px;color:#64748b;font-size:12px;">' + escapeHtml(date) + '</td>' +
              '<td style="padding:10px 8px;"><span style="font-size:11px;padding:3px 8px;border-radius:10px;' + statusStyle + '">' + statusLabel + '</span></td>' +
              '<td style="padding:10px 8px;">' +
              (safeUrl
                ? '<button type="button" class="btn small primary" onclick="downloadLibraryFile(\'' + safeUrl + '\', \'' + safeName + '\', \'' + d.id + '\')">تحميل</button>'
                : '—') +
              '</td></tr>';
          }).join('')
        : '<tr><td colspan="6" style="padding:24px;text-align:center;color:#64748b;">لا توجد ملفات مصدرة في السجل</td></tr>';

      modal.innerHTML =
        '<div style="background:#fff;border-radius:16px;max-width:760px;width:100%;max-height:85vh;display:flex;flex-direction:column;padding:24px;box-shadow:0 12px 32px rgba(0,0,0,.2);direction:rtl;text-align:right;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
        '<h3 style="margin:0;color:#1a3a52;font-size:18px;">مكتبة التنزيلات وسجل الملفات المصدرة</h3>' +
        '<button type="button" id="closeDownloadsModalBtn" class="btn ghost small" style="padding:4px 12px;">إغلاق</button>' +
        '</div>' +
        '<p style="margin:0 0 16px;color:#64748b;font-size:13px;">تنزيل مجاني مكرر للملفات المعتمدة طالما لم يتغير المحتوى أو الإصدار</p>' +
        '<div style="flex:1;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px;">' +
        '<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:right;">' +
        '<thead><tr style="background:#f8fafc;border-bottom:1px solid #e2e8f0;color:#475569;">' +
        '<th style="padding:10px 8px;">اسم الملف</th>' +
        '<th style="padding:10px 8px;">الصيغة</th>' +
        '<th style="padding:10px 8px;">الإصدار</th>' +
        '<th style="padding:10px 8px;">التاريخ</th>' +
        '<th style="padding:10px 8px;">الحالة</th>' +
        '<th style="padding:10px 8px;">الإجراء</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table>' +
        '</div></div>';

      document.body.appendChild(modal);
      const closeBtn = modal.querySelector('#closeDownloadsModalBtn');
      if (closeBtn) closeBtn.onclick = () => { if (modal.parentNode) modal.parentNode.removeChild(modal); };
    }

    async function downloadLibraryFile(url, fileName, downloadId) {
      try {
        const token = getTenantToken();
        const resp = await fetch(url, { headers: token ? { 'Authorization': 'Bearer ' + token } : {} });
        if (!resp.ok) throw new Error('Download failed');
        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);
        if (downloadId) {
          api('POST', '/api/downloads/' + encodeURIComponent(downloadId) + '/delivered').catch(() => {});
        }
        toast(WFT('downloads.download_started', 'تم بدء التحميل'));
      } catch (err) {
        toast(WFT('downloads.load_failed', 'تعذر تحميل الملف'));
      }
    }

    async function deleteTenantPresentation(presId) {
      if (!confirm(WFT('admin.confirm_delete_deck', 'هل أنت متأكد من حذف هذا العرض؟ لا يمكن التراجع عن هذا الإجراء.'))) return;
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
    let sagLastOverview = null;
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
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(modal);
    }

    function closeSagCompanyCreate() {
      document.getElementById('sagCompanyCreateModal').style.display = 'none';
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
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
      const trialDaysEl = document.getElementById('sagCreateTrialDays');
      const payload = {
        companyName: document.getElementById('sagCreateCompanyName').value.trim(),
        accountManagerName: document.getElementById('sagCreateManagerName').value.trim(),
        email: document.getElementById('sagCreateEmail').value.trim().toLowerCase(),
        phone: document.getElementById('sagCreatePhone').value.trim(),
        username: document.getElementById('sagCreateUsername').value.trim().toLowerCase(),
        slug: (document.getElementById('sagCreateSlug') || {}).value || '',
        isActive: document.getElementById('sagCreateStatus').value === 'active',
        trialDays: trialDaysEl && trialDaysEl.value !== '' ? Number(trialDaysEl.value) : null,
        legalName: (document.getElementById('sagCreateLegalName') || {}).value || '',
        taxNumber: (document.getElementById('sagCreateTaxNumber') || {}).value || '',
        crNumber: (document.getElementById('sagCreateCrNumber') || {}).value || '',
        country: (document.getElementById('sagCreateCountry') || {}).value || '',
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
        sagSyncPlanFilter();
        renderSagTenants(sagAllTenants);
      } finally {
        submit.disabled = false;
        hideLoader();
      }
    }

    async function openTenantAdmin() {
      showTenantPage('tenantAdminPage');
      await loadAdminDashboard();
    }

    async function loadAdminDashboard() {
      const statsEl = document.getElementById('sagAdminStats');
      const pendingEl = document.getElementById('sagPendingActions');
      if (statsEl) statsEl.innerHTML = '';
      if (pendingEl) showInlineLoader(pendingEl, WFT('common.loading', 'جاري التحميل...'));
      const [overviewData, tenantsData] = await Promise.all([
        api('GET', '/api/admin/operational-overview').catch(() => null),
        api('GET', '/api/admin/tenants').catch(() => null)
      ]);
      const overview = (overviewData && overviewData.overview) || {};
      sagAllTenants = (tenantsData && tenantsData.success && tenantsData.tenants) ? tenantsData.tenants : [];
      sagLastOverview = overview;
      renderAdminDashboard(overview);
      if (sagChartRange.preset !== '12') sagApplyChartRange();
      if (typeof llLoadNotifications === 'function') llLoadNotifications('adminNotificationsList');
    }

    // Re-render on language toggle: every dashboard label is built through
    // WFT at render time, so switching ar/en redraws KPIs, legends, month
    // ticks, status bars and pending actions instead of leaving stale Arabic.
    document.addEventListener('wf:lang', function () {
      const page = document.getElementById('tenantAdminPage');
      if (!page || !sagLastOverview) return;
      const visible = page.classList.contains('active') || (page.style.display !== 'none' && page.style.display !== '');
      if (visible) renderAdminDashboard(sagLastOverview);
    });

    // ── Super-admin dashboard: SVG data-viz helpers (no icon glyphs; charts
    //    are genuine data rendering and keep the no-icons rule intact) ──

    const SAG_MONTHS = {
      ar: ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'],
      en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
    };

    function sagMonthLabel(iso) {
      const lang = (window.WFI18n && WFI18n.getLang && WFI18n.getLang()) || 'ar';
      const names = SAG_MONTHS[lang === 'en' ? 'en' : 'ar'];
      const s = String(iso);
      const parts = s.split('-');
      const m = parseInt(parts[1], 10);
      const name = names[(m || 1) - 1] || s;
      if (parts.length >= 3) {
        const day = parseInt(parts[2], 10);
        const time = s.includes(' ') ? s.split(' ')[1] : (s.includes('T') ? s.split('T')[1] : '');
        const base = day + ' ' + name + ' ' + parts[0];
        return time ? base + ' ' + time.slice(0, 5) : base;
      }
      return name + ' ' + (parts[0] || '');
    }

    function sagFmtNum(v) {
      return Number(v || 0).toLocaleString('en-US');
    }

    function sagFmtMoney(v) {
      const n = Number(v || 0);
      const digits = n !== 0 && Math.abs(n) < 100 ? 2 : 0;
      return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) + ' ريال';
    }

    function sagDeltaChip(d) {
      if (d === null || d === undefined || isNaN(d)) {
        return '<span class="admin-delta flat">' + WFT('admin.delta_na', '—') + '</span>';
      }
      const cls = d > 0 ? 'up' : (d < 0 ? 'down' : 'flat');
      const txt = (d > 0 ? '+' : '') + d + '%';
      return '<span class="admin-delta ' + cls + '">' + txt + '</span>';
    }

    function sagSmoothPath(pts) {
      if (pts.length < 3) {
        return 'M' + pts.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L');
      }
      let d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
      for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
        const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
        const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
        d += ' C' + c1x.toFixed(1) + ' ' + c1y.toFixed(1) + ' ' + c2x.toFixed(1) + ' ' + c2y.toFixed(1) + ' ' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1);
      }
      return d;
    }

    function sagSparkline(values, color) {
      const w = 140, h = 40, pad = 3;
      const vals = (values && values.length ? values : [0, 0]);
      const max = Math.max(1, ...vals);
      const pts = vals.map((v, i) => [pad + i * (w - 2 * pad) / (vals.length - 1), h - pad - (v / max) * (h - 2 * pad)]);
      const line = sagSmoothPath(pts);
      const area = line + ' L' + pts[pts.length - 1][0].toFixed(1) + ' ' + h + ' L' + pts[0][0].toFixed(1) + ' ' + h + ' Z';
      return '<svg class="admin-spark-svg" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<path d="' + area + '" fill="' + color + '" opacity="0.14"/>' +
        '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round"/></svg>';
    }

    function sagNiceScale(maxV) {
      const steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 5000, 10000];
      const step = steps.find(s => maxV <= s * 3) || 50000;
      return { top: step * 3, step: step };
    }

    function sagTickText(v, top) {
      return top < 10 ? String(Math.round(v * 10) / 10) : sagFmtNum(Math.round(v));
    }

    function sagLineChart(labels, series) {
      const W = 660, H = 240, padL = 34, padR = 10, padT = 16, padB = 28;
      const innerW = W - padL - padR, innerH = H - padT - padB;
      const maxV = Math.max(0.01, ...series.flatMap(s => s.values));
      const sc = sagNiceScale(maxV), top = sc.top;
      const n = labels.length;
      const x = i => padL + (n === 1 ? innerW / 2 : i * innerW / (n - 1));
      const y = v => padT + innerH - (v / top) * innerH;
      let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">';
      for (let g = 0; g <= 3; g++) {
        const gv = sc.step * g, gy = y(gv);
        svg += '<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '" class="admin-chart-grid"/>' +
          '<text x="' + (padL - 6) + '" y="' + (gy + 4) + '" class="admin-chart-tick" text-anchor="end">' + sagTickText(gv, top) + '</text>';
      }
      const tickStep = Math.max(1, Math.ceil(n / 7));
      labels.forEach((lb, i) => {
        if (i % tickStep !== 0 && i !== n - 1) return;
        svg += '<text x="' + x(i) + '" y="' + (H - 8) + '" class="admin-chart-tick" text-anchor="middle">' + sagMonthLabel(lb) + '</text>';
      });
      series.forEach(s => {
        const fmt = s.fmt || sagFmtNum;
        const pts = s.values.map((v, i) => [x(i), y(v)]);
        const line = sagSmoothPath(pts);
        const area = line + ' L' + x(n - 1) + ' ' + (padT + innerH) + ' L' + x(0) + ' ' + (padT + innerH) + ' Z';
        svg += '<path d="' + area + '" fill="' + s.color + '" opacity="0.10"/>' +
          '<path d="' + line + '" fill="none" stroke="' + s.color + '" stroke-width="2.4" stroke-linecap="round"/>';
        pts.forEach((p, i) => {
          svg += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="3.2" fill="' + s.color + '">' +
            '<title>' + s.name + ': ' + fmt(s.values[i]) + ' — ' + sagMonthLabel(labels[i]) + '</title></circle>';
        });
      });
      return { svg: svg + '</svg>', geom: { W, H, padL, padR, padT, padB, top, n } };
    }

    function sagBindChartTooltip(container, labels, series, geom) {
      const svg = container.querySelector('svg');
      if (!svg || !geom.n) return;
      const NS = 'http://www.w3.org/2000/svg';
      const innerW = geom.W - geom.padL - geom.padR;
      const innerH = geom.H - geom.padT - geom.padB;
      const xFor = i => geom.padL + (geom.n === 1 ? innerW / 2 : i * innerW / (geom.n - 1));
      const yFor = v => geom.padT + innerH - (v / geom.top) * innerH;
      const guide = document.createElementNS(NS, 'line');
      guide.setAttribute('class', 'admin-chart-guide');
      guide.setAttribute('x1', '0');
      guide.setAttribute('x2', '0');
      guide.setAttribute('y1', String(geom.padT));
      guide.setAttribute('y2', String(geom.H - geom.padB));
      guide.style.display = 'none';
      svg.appendChild(guide);
      const dots = series.map(s => {
        const c = document.createElementNS(NS, 'circle');
        c.setAttribute('r', '4.5');
        c.setAttribute('fill', s.color);
        c.setAttribute('class', 'admin-chart-hover-dot');
        c.style.display = 'none';
        svg.appendChild(c);
        return c;
      });
      const tip = document.createElement('div');
      tip.className = 'admin-chart-tip';
      tip.style.display = 'none';
      container.appendChild(tip);
      svg.addEventListener('mousemove', (ev) => {
        const rect = svg.getBoundingClientRect();
        if (!rect.width) return;
        const vbX = (ev.clientX - rect.left) * (geom.W / rect.width);
        const span = innerW / Math.max(1, geom.n - 1);
        let i = Math.round((vbX - geom.padL) / span);
        i = Math.max(0, Math.min(geom.n - 1, i));
        const px = xFor(i);
        guide.setAttribute('x1', px.toFixed(1));
        guide.setAttribute('x2', px.toFixed(1));
        guide.style.display = '';
        series.forEach((s, si) => {
          dots[si].setAttribute('cx', px.toFixed(1));
          dots[si].setAttribute('cy', yFor(s.values[i] || 0).toFixed(1));
          dots[si].style.display = '';
        });
        tip.innerHTML = '<div class="tip-title">' + escapeHtml(sagMonthLabel(labels[i])) + '</div>' +
          series.map(s =>
            '<div class="tip-row"><span class="admin-legend-dot" style="background:' + s.color + '"></span>' +
            '<span>' + s.name + '</span><strong>' + escapeHtml(String((s.fmt || sagFmtNum)(s.values[i] || 0))) + '</strong></div>'
          ).join('');
        tip.style.display = 'block';
        const cRect = container.getBoundingClientRect();
        const half = tip.offsetWidth / 2;
        tip.style.left = Math.max(half + 4, Math.min(cRect.width - half - 4, ev.clientX - cRect.left)) + 'px';
      });
      svg.addEventListener('mouseleave', () => {
        guide.style.display = 'none';
        dots.forEach(c => { c.style.display = 'none'; });
        tip.style.display = 'none';
      });
    }

