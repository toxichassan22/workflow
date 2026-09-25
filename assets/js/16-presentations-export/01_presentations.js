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
        const statusText = typeof getProposalStatusLabel === 'function' ? getProposalStatusLabel(d.status, d.approver_name) : (stMeta.label || 'مسودة');
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
