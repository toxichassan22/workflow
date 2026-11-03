/* 16-presentations-export.js - index.html lines 26148-27658, shared global scope, classic scripts in order */

    async function openExistingPresentation(presId) {
      const data = await api('GET', '/api/presentations/' + presId);
      if (!data.success || !data.presentation) { toast('فشل تحميل العرض'); return; }
      const p = data.presentation;
      setDraftDirty(false);
      tenantPresentationId = p.id;
      tenantPresentationRevision = Number(p.revision) || 0;
      setTenantDraftRevision(p.draftRevision);
      tenantPresentationProvenance = null;
      tenantPresentationTitle = p.title || '';
      tenantPresentationStatus = p.status || 'draft';
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
      if (typeof resetInteractiveMapState === 'function') resetInteractiveMapState();
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
      toast(WFT('pres.opened', 'تم فتح العرض: {title}', { title: p.title || '' }));
      void resumeTenantDesignerChatJob();
    }

    let tenantArchiveAbortController = null;
    let tenantFilterDebounceTimer = null;

    function renderDraftRow(d, projectCost) {
      const title = d.title || (typeof WFT === 'function' ? WFT('dashboard.untitled_deck', 'مشروع بدون عنوان') : 'مشروع بدون عنوان');
      const stMeta = typeof getProposalStatusMeta === 'function' ? getProposalStatusMeta(d.status) : { cls: 'status-draft', label: d.status };
      const statusText = typeof getProposalStatusLabel === 'function' ? getProposalStatusLabel(d.status, d.approver_name) : (stMeta.label || 'مسودة');
      const createdAt = (d.created_at || '').slice(0, 16).replace('T', ' ') || '—';
      const updatedAt = (d.updated_at || d.created_at || '').slice(0, 16).replace('T', ' ') || '—';
      const projectMapsCost = Number(projectCost?.maps_cost_sar) || 0;
      const totalCostCell = projectCost ? formatUsageCost(projectCost.cost_sar || 0) : '—';
      const mapsCostCell = projectCost ? formatUsageCost(projectMapsCost) : '—';
      const isArchived = d.status === 'archived';
      const archiveBadge = isArchived
        ? '<span class="proposal-status-badge status-archived" title="محفوظ لمدة 365 يوماً وفق سياسة الحفظ">أرشيف (محفوظ 365 يوماً)</span>'
        : '';
      const statusBadgeHtml = archiveBadge || ('<span class="proposal-status-badge ' + stMeta.cls + '">' + escapeHtml(statusText) + '</span>');
      const copyBtn = hasPermission('copy_presentation')
        ? '<button type="button" class="btn small ghost" onclick="closeTenantDropdown(); copyProjectDraftById(\'' + d.id + '\')">' + (typeof WFT === 'function' ? WFT('projects.copy', 'نسخ العرض') : 'نسخ العرض') + '</button>'
        : '';
      // Final delete is a company-admin-only cleanup: the server also refuses
      // drafts that already carry approval history.
      const canDelete = Boolean(tenantUser && tenantUser.isAdmin) ||
        ((tenantUser || {})._userRole || 'company_admin') === 'company_admin';
      const deleteBtn = canDelete
        ? '<button type="button" class="btn small ghost danger" onclick="closeTenantDropdown(); deleteProjectDraftById(\'' + d.id + '\')">' + (typeof WFT === 'function' ? WFT('projects.delete', 'حذف') : 'حذف') + '</button>'
        : '';
      const editLogBtn = '<button type="button" class="btn small ghost" onclick="closeTenantDropdown(); showDraftEditLog(\'' + d.id + '\')">' + (typeof WFT === 'function' ? WFT('projects.edit_log', 'سجل التعديلات') : 'سجل التعديلات') + '</button>';
      const versionsBtn = '<button type="button" class="btn small ghost" onclick="closeTenantDropdown(); showDraftVersions(\'' + d.id + '\')">' +
        (typeof WFT === 'function' ? WFT('draft_versions.button', 'الإصدارات') : 'الإصدارات') + '</button>';
      const moreBtn = '<div class="tenant-dropdown">' +
        '<button type="button" class="btn small ghost" onclick="toggleTenantDropdown(this)" aria-haspopup="true">' + (typeof WFT === 'function' ? WFT('projects.more', 'المزيد') : 'المزيد') + '</button>' +
        '<div class="tenant-dropdown-menu">' +
          (!isArchived ? copyBtn : '') +
          editLogBtn +
          versionsBtn +
          deleteBtn +
        '</div>' +
        '</div>';
      const primaryBtn = isArchived
        ? '<button type="button" class="btn small primary" onclick="restoreProposalById(\'' + d.id + '\')">' + (typeof WFT === 'function' ? WFT('projects.restore', 'استعادة') : 'استعادة') + '</button>'
        : '<button type="button" class="btn small primary" onclick="openProjectDraftById(\'' + d.id + '\')">' + (typeof WFT === 'function' ? WFT('projects.open', 'فتح المشروع') : 'فتح المشروع') + '</button>';
      const actionsHtml = primaryBtn + moreBtn;
      const rowCls = isArchived ? 'll-row-archived' : '';
      return '<tr data-draft-id="' + d.id + '"' + (rowCls ? ' class="' + rowCls + '"' : '') + '>' +
        '<td class="project-title-cell" style="font-weight:700">' + escapeHtml(title) + '</td>' +
        '<td>' + statusBadgeHtml + '</td>' +
        '<td>' + totalCostCell + '</td>' +
        '<td>' + mapsCostCell + '</td>' +
        '<td><span dir="ltr">' + escapeHtml(createdAt) + '</span></td>' +
        '<td><span dir="ltr">' + escapeHtml(updatedAt) + '</span></td>' +
        '<td class="project-actions-cell"><div class="tenant-actions" style="gap:8px">' + actionsHtml + '</div></td>' +
        '</tr>';
    }

    function draftTableHtml(rowsHtml, count) {
      const showingText = typeof WFT === 'function'
        ? WFT('projects.showing', 'عرض {shown} من إجمالي {total} مشروعاً', { shown: count, total: count })
        : ('عرض ' + count + ' من إجمالي ' + count + ' مشروعاً');
      return '<div class="tenant-content-panel tenant-projects-table-panel" style="padding:0;overflow:visible">' +
        '<div class="table-wrap" style="border:none;border-radius:10px 10px 0 0;overflow-x:auto;overflow-y:visible"><table class="tenant-projects-table"><thead><tr>' +
        '<th>' + (typeof WFT === 'function' ? WFT('projects.name', 'اسم المشروع') : 'اسم المشروع') + '</th>' +
        '<th>' + (typeof WFT === 'function' ? WFT('projects.status', 'حالة المشروع') : 'حالة المشروع') + '</th>' +
        '<th>' + (typeof WFT === 'function' ? WFT('projects.total_cost', 'التكلفة الإجمالية') : 'التكلفة الإجمالية') + '</th>' +
        '<th>' + (typeof WFT === 'function' ? WFT('projects.maps_cost', 'تكلفة الخرائط') : 'تكلفة الخرائط') + '</th>' +
        '<th>' + (typeof WFT === 'function' ? WFT('projects.created_at', 'تاريخ الإنشاء') : 'تاريخ الإنشاء') + '</th>' +
        '<th>' + (typeof WFT === 'function' ? WFT('projects.updated_at', 'تاريخ آخر تعديل') : 'تاريخ آخر تعديل') + '</th>' +
        '<th style="width:160px;min-width:160px">' + (typeof WFT === 'function' ? WFT('projects.actions', 'الإجراءات') : 'الإجراءات') + '</th>' +
        '</tr></thead><tbody>' + rowsHtml + '</tbody></table></div>' +
        '<div class="tenant-table-footer">' +
          '<span>' + escapeHtml(showingText) + '</span>' +
        '</div>' +
        '</div>';
    }

    function getProjectArchiveCurrentFilters() {
      return {
        search: document.getElementById('projectArchiveSearch')?.value?.trim() || '',
        status: document.getElementById('projectArchiveStatus')?.value || '',
        from: document.getElementById('projectArchiveFrom')?.value || '',
        to: document.getElementById('projectArchiveTo')?.value || ''
      };
    }

    function applyProjectArchiveFiltersInMemory(items, filters) {
      if (!Array.isArray(items)) return [];
      const searchVal = (filters.search || '').toLowerCase();
      const statusVal = filters.status || '';
      const fromVal = filters.from || '';
      const toVal = filters.to || '';

      return items.filter(d => {
        if (searchVal) {
          const t = (d.title || '').toLowerCase();
          if (!t.includes(searchVal)) return false;
        }
        if (statusVal) {
          const s = d.status || 'draft';
          if (statusVal === 'draft') {
            if (['pending_approval', 'approved', 'sections_approved', 'final_approval_pending'].includes(s)) return false;
          } else if (statusVal === 'approved') {
            if (!['approved', 'sections_approved'].includes(s)) return false;
          } else if (statusVal === 'pending_approval' || statusVal === 'pending') {
            if (!['pending_approval', 'section_approval_pending', 'generation_approval_pending', 'final_approval_pending'].includes(s)) return false;
          } else if (s !== statusVal) {
            return false;
          }
        }
        const itemDate = (d.updated_at || d.created_at || '').slice(0, 10);
        if (fromVal && itemDate && itemDate < fromVal) return false;
        if (toVal && itemDate && itemDate > toVal) return false;
        return true;
      });
    }

    function filterProjectArchiveInstant() {
      const list = document.getElementById('tenantPresentationsList');
      if (!list) return;
      const filters = getProjectArchiveCurrentFilters();

      if (Array.isArray(tenantAllDraftsMaster)) {
        const filtered = applyProjectArchiveFiltersInMemory(tenantAllDraftsMaster, filters);
        updateProjectArchiveStats(filtered);
        if (!filtered.length) {
          const emptyHtml = '<div class="tenant-dash-empty-state">' +
            '<p class="tenant-dash-empty-title">' + escapeHtml(typeof WFT === 'function' ? WFT('projects.empty_title', 'لا توجد مشاريع مطابقة') : 'لا توجد مشاريع مطابقة') + '</p>' +
            '<p class="tenant-hint">' + escapeHtml(typeof WFT === 'function' ? WFT('projects.empty_hint', 'لم يتم العثور على مشاريع تطابق معايير البحث والتصفية المحددة.') : 'لم يتم العثور على مشاريع تطابق معايير البحث والتصفية المحددة.') + '</p>' +
            '<button type="button" class="btn ghost small" onclick="clearProjectArchiveFilters()">' + escapeHtml(typeof WFT === 'function' ? WFT('projects.reset', 'إعادة ضبط الفلاتر') : 'إعادة ضبط الفلاتر') + '</button>' +
            '</div>';
          list.innerHTML = emptyHtml;
        } else {
          list.innerHTML = draftTableHtml(filtered.map(d => renderDraftRow(d, tenantProjectsCostMap[d.id] || null)).join(''), filtered.length);
        }
      }

      if (tenantFilterDebounceTimer) clearTimeout(tenantFilterDebounceTimer);
      tenantFilterDebounceTimer = setTimeout(() => {
        openTenantPresentations(true, { background: true });
      }, 350);
    }

    function clearProjectArchiveFilters() {
      const search = document.getElementById('projectArchiveSearch');
      const status = document.getElementById('projectArchiveStatus');
      const from = document.getElementById('projectArchiveFrom');
      const to = document.getElementById('projectArchiveTo');
      if (search) search.value = '';
      if (status) status.value = '';
      if (from) from.value = '';
      if (to) to.value = '';
      tenantArchiveCache = null;
      if (Array.isArray(tenantAllDraftsMaster)) {
        const list = document.getElementById('tenantPresentationsList');
        if (list) {
          updateProjectArchiveStats(tenantAllDraftsMaster);
          list.innerHTML = draftTableHtml(tenantAllDraftsMaster.map(d => renderDraftRow(d, tenantProjectsCostMap[d.id] || null)).join(''), tenantAllDraftsMaster.length);
        }
      }
      openTenantPresentations(true, { background: Boolean(tenantAllDraftsMaster) });
    }

    function updateProjectArchiveStats(items) {
      const totalEl = document.getElementById('presStatTotal');
      const inProgressEl = document.getElementById('presStatInProgress');
      const approvedEl = document.getElementById('presStatApproved');
      const draftsEl = document.getElementById('presStatDrafts');
      const badgeEl = document.getElementById('presentationsCountBadge');
      if (!totalEl && !badgeEl) return;
      const total = items.length;
      let inProgress = 0;
      let approved = 0;
      let draftCount = 0;
      items.forEach(d => {
        const s = d.status || 'draft';
        if (s === 'approved') approved++;
        else if (s === 'draft') draftCount++;
        else inProgress++;
      });
      if (totalEl) totalEl.textContent = formatExactSystemNumber(total, true);
      if (inProgressEl) inProgressEl.textContent = formatExactSystemNumber(inProgress, true);
      if (approvedEl) approvedEl.textContent = formatExactSystemNumber(approved, true);
      if (draftsEl) draftsEl.textContent = formatExactSystemNumber(draftCount, true);
      if (badgeEl) badgeEl.textContent = '(' + formatExactSystemNumber(total, true) + ' ' + (typeof WFT === 'function' ? WFT('projects.unit', 'مشروعاً') : 'مشروعاً') + ')';
    }

    async function openTenantPresentations(force = false, options = {}) {
      showTenantPage('tenantPresentationsPage');
      const list = document.getElementById('tenantPresentationsList');
      if (!list) return;
      const background = Boolean(options && options.background);
      const filters = getProjectArchiveCurrentFilters();
      const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
      const tenantKey = (tenantUser && (tenantUser.id || tenantUser.tenantId)) || 'tenant';
      const listLang = ((typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang && window.WFI18n.getLang()) || 'ar');
      const cacheKey = tenantKey + '|' + listLang + '|' + query.toString();
      if (!force && tenantArchiveCache && tenantArchiveCache.key === cacheKey && Date.now() - tenantArchiveCache.timestamp < 15000) {
        list.innerHTML = tenantArchiveCache.html;
        return;
      }

      // If we already have items in memory and background refresh, don't show blank spinner
      const hasExistingRows = Boolean(list.querySelector('[data-draft-id]'));
      if (!background && !hasExistingRows && !Array.isArray(tenantAllDraftsMaster)) {
        showInlineLoader(list, typeof WFT === 'function' ? WFT('i18n.loading_projects', 'جاري تحميل المشاريع...') : 'جاري تحميل المشاريع...');
      }

      const stamp = String(Date.now()) + Math.random().toString(16).slice(2);
      list.dataset.archiveStamp = stamp;

      // Abort prior in-flight request if rapid filter changes occurred
      if (tenantArchiveAbortController) {
        try { tenantArchiveAbortController.abort(); } catch (_) {}
      }
      tenantArchiveAbortController = typeof AbortController !== 'undefined' ? new AbortController() : null;

      // Fetch with limit=200 for fast single-roundtrip retrieval
      const fetchParams = new URLSearchParams(query);
      if (!fetchParams.has('limit')) fetchParams.set('limit', '200');

      let draftsData = null;
      try {
        draftsData = await apiWithTimeout(
          'GET',
          '/api/project-drafts?' + fetchParams.toString(),
          null,
          25000,
          undefined,
          { signal: tenantArchiveAbortController ? tenantArchiveAbortController.signal : undefined }
        );
      } catch (err) {
        draftsData = { success: false, error: err?.message };
      }

      if (!draftsData || !draftsData.success) {
        if (tenantArchiveAbortController && tenantArchiveAbortController.signal?.aborted) {
          return;
        }
        if (list.dataset.archiveStamp === stamp && !list.querySelector('[data-draft-id]')) {
          renderListLoadError(list, 'openTenantPresentations(true)');
        }
        return;
      }

      const rawDrafts = Array.isArray(draftsData.drafts) ? draftsData.drafts : [];
      if (!filters.search && !filters.status && !filters.from && !filters.to) {
        tenantAllDraftsMaster = rawDrafts;
      } else if (!tenantAllDraftsMaster) {
        tenantAllDraftsMaster = rawDrafts;
      }

      const currentFilters = getProjectArchiveCurrentFilters();
      const drafts = (currentFilters.search || currentFilters.status || currentFilters.from || currentFilters.to)
        ? applyProjectArchiveFiltersInMemory(tenantAllDraftsMaster || rawDrafts, currentFilters)
        : rawDrafts;

      updateProjectArchiveStats(drafts);

      if (!drafts.length) {
        const emptyHtml = '<div class="tenant-dash-empty-state">' +
          '<p class="tenant-dash-empty-title">' + escapeHtml(typeof WFT === 'function' ? WFT('projects.empty_title', 'لا توجد مشاريع مطابقة') : 'لا توجد مشاريع مطابقة') + '</p>' +
          '<p class="tenant-hint">' + escapeHtml(typeof WFT === 'function' ? WFT('projects.empty_hint', 'لم يتم العثور على مشاريع تطابق معايير البحث والتصفية المحددة.') : 'لم يتم العثور على مشاريع تطابق معايير البحث والتصفية المحددة.') + '</p>' +
          '<button type="button" class="btn ghost small" onclick="clearProjectArchiveFilters()">' + escapeHtml(typeof WFT === 'function' ? WFT('projects.reset', 'إعادة ضبط الفلاتر') : 'إعادة ضبط الفلاتر') + '</button>' +
          '</div>';
        if (list.dataset.archiveStamp === stamp) {
          list.innerHTML = emptyHtml;
          tenantArchiveCache = { key: cacheKey, timestamp: Date.now(), html: emptyHtml };
        }
        return;
      }

      if (list.dataset.archiveStamp === stamp) {
        list.innerHTML = draftTableHtml(drafts.map(d => renderDraftRow(d, tenantProjectsCostMap[d.id] || null)).join(''), drafts.length);
        tenantArchiveCache = { key: cacheKey, timestamp: Date.now(), html: list.innerHTML };
      }

      // Check which displayed projects need cost data
      const missingCostIds = drafts.map(d => d.id).filter(id => id && !(id in tenantProjectsCostMap));
      if (!missingCostIds.length) return;

      const totalsData = await apiWithTimeout('GET', '/api/usage-totals?draftIds=' + encodeURIComponent(missingCostIds.join(',')), null, 25000).catch(() => null);
      if (list.dataset.archiveStamp !== stamp) return;
      if (!document.contains(list) || !list.querySelector('[data-draft-id]')) return;

      let costByProject = {};
      if (totalsData?.success && totalsData.projects) {
        Object.assign(tenantProjectsCostMap, totalsData.projects);
      }
      costByProject = tenantProjectsCostMap;

      let patched = false;
      drafts.forEach(d => {
        const node = list.querySelector('[data-draft-id="' + d.id + '"]');
        if (!node) return;
        const projectCost = costByProject[d.id];
        if (!projectCost) return;
        const next = renderDraftRow(d, projectCost);
        if (node.outerHTML !== next) { node.outerHTML = next; patched = true; }
      });
      if (patched) {
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
      toast(WFT('pres.fields_restored', 'تم استرجاع {n} حقلًا', { n: resp.restoredCount }));
      await openProjectDraftById(draftId);
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
        setTenantDraftRevision(draft.revision);
        const draftData = draft.draft_data || draft.draftData || {};
        const pageDrafts = draftData.pageDrafts || {};
        const sectionStatuses = draft.section_statuses || {};
        tenantPresentationId = null;
        tenantPresentationRevision = 0;
        tenantPresentationProvenance = null;
        tenantPresentationTitle = '';
        tenantProjectMode = 'draft';
        tenantProjectData = { ...draftData, draftId: draftData.draftId || draft.id || draftId };
        // The baseline a later save compares against when deciding whether a
        // blank field is a deliberate clear or a section that never loaded.
        tenantDraftLoadedSnapshot = JSON.parse(JSON.stringify(tenantProjectData));
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
        if (typeof resetInteractiveMapState === 'function') resetInteractiveMapState();
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
        // The file is followed once the form is on screen: the live session
        // binds to the real inputs and a merge by somebody else shows up
        // without a manual refresh.
        if (typeof startDraftLiveSync === 'function') {
          startDraftLiveSync(draft.id, tenantDraftRevision);
        }
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
        tenantArchiveCache = null; tenantAllDraftsMaster = null;
        openTenantPresentations(true);
      } else {
        toast(res?.error || 'فشل نسخ العرض');
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
        tenantArchiveCache = null; tenantAllDraftsMaster = null;
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
      // in parallel: a presentation-save failure must never lose the open
      // workspace, and the two big uploads no longer serialize after each other.
      const backupPromise = saveProjectAsDraft(true, false)
        .then(backupSaved => {
          if (!backupSaved) console.error('[DRAFT BACKUP] save reported failure');
        })
        .catch(backupError => {
          console.error('[DRAFT BACKUP]', backupError);
        });
      renumberTenantSlides();
      // api('PUT', '/api/presentations/'
      const saved = await saveTenantPresentation();
      await backupPromise;
      if (saved) toast('تم حفظ نسخة العرض');
      return saved;
    }

    async function regeneratePresentationMaps() {
      return regenerateMapPreview(tenantSelectedMapType || 'overview');
    }


    // The deck is translated as markup, not regenerated: the Arabic copy stays
    // untouched and the English one comes back with the same design.
    async function translateTenantPresentationToEnglish() {
      if (!tenantPresentationId) {
        toast(WFT('ws.translate_none', 'افتح العرض أولًا.'));
        return;
      }
      if (!confirm(WFT('ws.translate_confirm', 'إنشاء نسخة إنجليزية من هذا العرض بنفس التصميم؟ العرض العربي يبقى كما هو.'))) return;
      showLoader(WFT('ws.translate_busy', 'جاري ترجمة العرض...'));
      try {
        const data = await api('POST', '/api/presentations/' + tenantPresentationId + '/translate', { targetLang: 'en' });
        if (!data || !data.success) {
          toast((data && data.error) || WFT('ws.translate_failed', 'تعذرت ترجمة العرض.'));
          return;
        }
        toast(WFT('ws.translate_done', 'تم إنشاء النسخة الإنجليزية ({count} شريحة).', { count: data.slideCount }));
        await openExistingPresentation(data.presentationId);
      } finally {
        hideLoader();
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


    function renderDashboardRecentProjects(presentations) {
      const container = document.getElementById('dashRecentProjects');
      if (!container) return;
      const list = Array.isArray(presentations) ? presentations.slice(0, 5) : [];
      if (!list.length) {
        container.innerHTML = '<div class="tenant-dash-empty-state">' +
          '<p class="tenant-dash-empty-title">' + escapeHtml(WFT('dashboard.empty_title', 'لا توجد عروض عقارية بعد')) + '</p>' +
          '<p class="tenant-hint">' + escapeHtml(WFT('dashboard.empty_hint', 'لم يتم إنشاء أي عرض عقاري في هذه المنظومة بعد.')) + '</p>' +
          '<button type="button" class="btn primary small" onclick="startTenantProject()">' + escapeHtml(WFT('nav.new_proposal', 'مشروع جديد')) + '</button>' +
          '</div>';
        return;
      }
      const statusLabels = {
        'draft': WFT('dashboard.status_draft', 'مسودة'),
        'pending_approval': WFT('dashboard.status_pending', 'بانتظار التعميد'),
        'approved': WFT('dashboard.status_approved', 'معتمد'),
        'completed': WFT('dashboard.status_completed', 'مكتمل')
      };
      const rows = list.map(item => {
        const title = escapeHtml(item.title || WFT('dashboard.untitled_deck', 'عرض بدون عنوان'));
        const slides = Number(item.slideCount || 0);
        const rev = Number(item.revision || 0);
        const date = (item.updatedAt || item.createdAt || '').slice(0, 10);
        const statusKey = item.status || 'draft';
        const statusText = statusLabels[statusKey] || statusLabels.draft;
        const statusClass = 'tenant-badge status-' + (statusKey === 'approved' ? 'success' : (statusKey === 'pending_approval' ? 'warning' : 'neutral'));
        const draftBtn = item.draftId
          ? '<button type="button" class="btn ghost small" onclick="openProjectDraftById(\'' + escapeHtml(item.draftId) + '\')">' + escapeHtml(WFT('dashboard.edit_project', 'بيانات المشروع')) + '</button>'
          : '';
        return '<div class="tenant-recent-project-row" data-id="' + escapeHtml(item.id) + '">' +
          '<div class="tenant-recent-project-info">' +
            '<div class="tenant-recent-project-title-line">' +
              '<h4 class="tenant-recent-project-title">' + title + '</h4>' +
              '<span class="' + statusClass + '">' + escapeHtml(statusText) + '</span>' +
            '</div>' +
            '<div class="tenant-recent-project-meta">' +
              '<span>' + slides + ' ' + escapeHtml(WFT('ws.slides_count_unit', 'شريحة')) + '</span>' +
              '<span class="tenant-recent-dot">•</span>' +
              '<span>' + escapeHtml(WFT('ws.revision_label', 'النسخة')) + ' ' + rev + '</span>' +
              (date ? '<span class="tenant-recent-dot">•</span><span>' + escapeHtml(date) + '</span>' : '') +
            '</div>' +
          '</div>' +
          '<div class="tenant-recent-project-actions">' +
            '<button type="button" class="btn primary small" onclick="openExistingPresentation(\'' + escapeHtml(item.id) + '\')">' + escapeHtml(WFT('dashboard.open_deck', 'فتح العرض')) + '</button>' +
            draftBtn +
          '</div>' +
        '</div>';
      }).join('');
      container.innerHTML = '<div class="tenant-recent-projects-list">' + rows + '</div>';
    }
