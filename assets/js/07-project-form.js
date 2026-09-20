/* 07-project-form.js - index.html lines 13568-14085, shared global scope, classic scripts in order */

    // A rebuilt form is empty until hydrateTenantProjectForm() fills it from the draft. Its blank
    // inputs are unknown values, not cleared ones, so collectTenantFormData() must not report them
    // as the project's data — that is how one save could blank every field of a stored draft.
    function markTenantProjectFormFilled() {
      const form = document.getElementById('tenantProjectForm');
      if (form) form.dataset.projectFormFilled = '1';
    }

    function tenantProjectFormIsFilled() {
      const form = document.getElementById('tenantProjectForm');
      if (!form || !form.querySelector('[data-key]')) return true;
      return form.dataset.projectFormFilled === '1';
    }

    function isBlankProjectValue(value) {
      if (value === null || value === undefined || value === 0) return true;
      if (typeof value === 'string') return !value.trim();
      if (Array.isArray(value)) return value.length === 0;
      return false;
    }

    function updateProposalLifecycleBadge(status) {
      const badge = document.getElementById('proposalLifecycleBadge');
      if (!badge) return;
      const s = status || (tenantProjectDraftApproval && tenantProjectDraftApproval.status) || (tenantProjectData && tenantProjectData.status) || 'draft';
      const meta = typeof getProposalStatusMeta === 'function' ? getProposalStatusMeta(s) : { cls: 'status-draft', label: s };
      const label = typeof getProposalStatusLabel === 'function' ? getProposalStatusLabel(s) : (meta.label || s);
      badge.textContent = label;
      badge.className = 'proposal-lifecycle-badge ' + meta.cls;
      badge.style.display = 'inline-block';
    }

    function hydrateTenantProjectForm(data) {
      const form = document.getElementById('tenantProjectForm');
      if (!form) return;
      editingProjectLocalTeamId = null;
      projectLocalTeamDraft = null;
      const source = data || {};
      updateProposalLifecycleBadge(source.status || (tenantProjectDraftApproval && tenantProjectDraftApproval.status) || 'draft');
      if (Array.isArray(source.nearby_landmarks_data)) {
        tenantNearbyLandmarks = source.nearby_landmarks_data;
      }
      tenantProjectData = { ...tenantProjectData, ...source };
      tenantMapPolygonPoints = source.location_polygon_source === 'cleared' ? [] : parseTenantPolygonPoints(source.location_polygon);
      tenantVisualConceptState = normalizeVisualConceptState(source.visual_concept);
      // Stored as a JSON string in a hidden input, so it must be parsed before use.
      const storedAnalysis = parseStoredLandTable(source.land_documents_analysis) || {};
      storeLandDocumentAnalysis(storedAnalysis);
      renderSurveyCoordinates(source.survey_coordinates || storedAnalysis.survey_coordinates || []);
      renderSurveyDirections(source.directions_table || storedAnalysis.directions_table || storedAnalysis.parcels?.[0]?.directions || {});
      renderLandDocumentsUploadState(source.land_documents_files_file_meta || []);
      showLandAnalysisDiagnostics(storedAnalysis);
      renderLandPhotos(source.land_photos_file_meta || []);
      renderProjectLogoState(source.project_logo_file_meta || (source.project_logo_file_id ? { id: source.project_logo_file_id, originalName: 'شعار المشروع' } : (source.project_logo ? { path: source.project_logo, originalName: 'شعار المشروع' } : null)));
      refreshAllowedUsesStatusNote();
      renderProjectTeam();

      form.querySelectorAll('[data-key]').forEach(input => {
        const key = input.dataset.key;
        if (!(key in source) || input.type === 'file') return;
        const value = source[key];
        if (input.classList.contains('location-table-value')) {
          setLocationTableValue(key, value);
        } else if (value === null || value === undefined) {
          input.value = '';
        } else if (typeof value === 'object') {
          input.value = JSON.stringify(value);
        } else if (key === 'allowed_uses') {
          const stripped = stripLandUseStatusFromText(value);
          input.value = stripped.text;
          if (stripped.status && !tenantProjectData.land_use_status) {
            tenantProjectData.land_use_status = stripped.status;
          }
        } else if (key === 'project_type') {
          persistProjectTypes(value);
        } else if (key === 'project_mixed_components' || key === 'project_subtype' || key === 'target_audience' || key === 'activity_class') {
          const encoded = Array.isArray(value) || (value && typeof value === 'object')
            ? JSON.stringify(value)
            : String(value || '');
          input.value = encoded;
          tenantProjectData[key] = encoded;
        } else {
          input.value = String(value);
        }
      });
      refreshClientEnteredLandFieldStates();
      const timelineRows = parseStoredProjectTable(source.timeline_table_data || source.timelineRows);
      const timelineBody = document.getElementById('timelineTableBody');
      if (timelineBody && timelineRows.length) {
        timelineBody.innerHTML = '';
        timelineRows.forEach(row => addTimelineRow(row));
        const timelineInput = document.getElementById('timelineTableData');
        if (timelineInput) timelineInput.value = JSON.stringify(timelineRows);
      }
      const legacyFinancial = parseFinancialStudySnapshot(source.financial_calc_data);
      const compatibleComponents = parseStoredProjectTable(source.project_components_data);
      const savedComponents = compatibleComponents.length ? compatibleComponents : (legacyFinancial?.components || []);
      hydrateFinancialStudyModel(source.financial_study_model, savedComponents);

      refreshLocationTables();
      // Mirror the restored timeline and land/croquis inputs into the financial study
      // before recalculating, so read-only fields always reflect their single source of truth.
      if (typeof syncFinancialFromTimeline === 'function') syncFinancialFromTimeline();
      if (typeof syncFinancialFromLand === 'function') syncFinancialFromLand();
      if (typeof calculateAll === 'function') {
        try { calculateAll(); } catch (e) { console.warn('calculateAll failed:', e); }
      }
      recalcFinancials();
      const storedMaps = hasStoredMaps();
      renderMapPreviewGallery();
      if (source.location_lat && source.location_lng && storedMaps) {
        selectMapPreviewView('overview');
      } else if (source.location_lat && source.location_lng) {
        const hint = document.getElementById('mapPreviewHint');
        if (hint) {
          hint.textContent = 'لا توجد خرائط محفوظة لهذه المسودة.';
          hint.style.display = 'block';
        }
      }
      window._lastAnalyzedAddress = (source.location_address || '').trim();
      enhanceProjectClassificationFields();
      applyMarketStudyState(parseStoredLandTable(source.market_study_data) || getMarketStudyState());
      // Marked last on purpose: if anything above throws, the form stays unfilled and a save keeps
      // the stored values instead of writing this form's blanks over them.
      markTenantProjectFormFilled();
    }

    function recoverTenantSlidePlan(projectData, slidesData) {
      const storedPlan = projectData && (projectData.tenantSlidePlan || projectData.slidePlan);
      if (storedPlan && Array.isArray(storedPlan.slides) && storedPlan.slides.length) return storedPlan;
      if (!Array.isArray(slidesData) || !slidesData.length) return null;
      return {
        proposed_count: slidesData.length,
        reasoning: 'تم استعادة هيكل العرض من الشرائح المحفوظة.',
        slides: slidesData.map(slide => ({
          title: slide.title || '',
          type: slide.type || 'content',
          section_key: slide.section_key || slide.sectionKey || '',
          content_source: slide.content_source || slide.contentSource || '',
          source_table: slide.source_table || slide.sourceTable || '',
          index_entries: slide.index_entries || slide.indexEntries || [],
          design_style: slide.designStyle || slide.design_style || 'cards',
          bullets: slide.bullets || [],
          metrics: slide.metrics || []
        }))
      };
    }

    async function startTenantProject() {
      setDraftDirty(false);
      tenantPresentationId = null;
      tenantPresentationRevision = 0;
      tenantDraftRevision = 0;
      tenantPresentationProvenance = null;
      tenantPresentationTitle = '';
      tenantProjectMode = 'new';
      tenantProjectData = { draftId: crypto.randomUUID() };
      tenantVisualConceptState = null;
      tenantSlidesData = [];
      tenantSlidePlan = null;
      tenantSlideGenerationCheckpoint = null;
      tenantCreativeImages = { cover: '', moodboard: [], map_placeholders: {}, map_landmarks: [] };
      tenantFinancialPresentationReport = null;
      tempCoverImage = null;
      tempMoodboardImages = {};
      restoreDesignerChat(null);
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
      tenantLandmarkPlacementTarget = null;
      tenantNearbyLandmarks = [];
      tenantProjectSectionStatuses = {};
      tenantProjectDraftApproval = null;
      tenantActiveProjectSection = null;
      clearSlidesEditorSurface();
      resetPresentationUndo();
      showTenantPage('tenantProjectPage');
      if (await loadTenantProjectForm()) {
        // A new project is legitimately blank, so its freshly built form counts as filled.
        markTenantProjectFormFilled();
        refreshGlobalRail();
      }
    }

    function getProjectSectionElement(sectionKey) {
      return Array.from(document.querySelectorAll('#tenantProjectForm .tenant-form-section[data-section]'))
        .find(section => section.dataset.section === sectionKey) || document.getElementById(sectionKey);
    }

    function updateProjectSidebarStatus(sectionKey, status) {
      const approved = status === 'approved';
      document.querySelectorAll('#tenantProjectSidebar [data-section-key]').forEach(button => {
        if (button.dataset.sectionKey !== sectionKey) return;
        const statusLabel = button.querySelector('.project-section-nav-status');
        if (!statusLabel) return;
        statusLabel.textContent = approved ? 'معتمد' : 'مسودة';
        statusLabel.classList.toggle('approved', approved);
      });
    }

    const PROJECT_SECTION_PRESENTATION_TITLES = Object.freeze({
      basic: 'بيانات المشروع',
      location: 'الموقع الجغرافي',
      land_croquis: 'تحليل الأرض',
      'section-timeline': 'الجدول الزمني',
      'section-financial-calc': 'الدراسة المالية والمؤشرات',
      'section-team': 'فريق العمل',
      'section-market-study': 'دراسة السوق',
      'section-visual-concept': 'التصور البصري',
      'section-executive-content': 'المحتوى التنفيذي',
      contact: 'بيانات التواصل'
    });

    function createProjectSectionHeader(sectionKey, label, options = {}) {
      const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
      const dict = (typeof window.WFI18n !== 'undefined' && window.WFI18n.autoDict) || (typeof WFI18N_EN_AUTO !== 'undefined' ? WFI18N_EN_AUTO : (window.WFI18N_EN_AUTO || null));
      const tr = text => (isEn && dict && dict[text]) ? dict[text] : text;

      const title = document.createElement('h3');
      title.className = 'tenant-section-title';
      title.dataset.sectionKey = sectionKey;
      title.dataset.arLabel = label;

      const underConstruction = !!options.underConstruction;
      const status = underConstruction ? 'draft' : (tenantProjectSectionStatuses[sectionKey] === 'approved' ? 'approved' : 'draft');
      const badge = document.createElement('span');
      badge.id = 'badge-' + sectionKey;
      badge.className = 'section-status-badge ' + status;
      badge.textContent = underConstruction ? tr('تحت الإنشاء') : (status === 'approved' ? tr('معتمد') : tr('مسودة'));
      badge.dataset.arText = underConstruction ? 'تحت الإنشاء' : (status === 'approved' ? 'معتمد' : 'مسودة');
      title.appendChild(badge);

      const titleText = document.createElement('span');
      titleText.className = 'project-section-title-label';
      titleText.textContent = tr(label);
      titleText.dataset.arText = label;
      title.appendChild(titleText);

      if (!underConstruction) {
        if (PROJECT_SECTION_PRESENTATION_TITLES[sectionKey] && hasPermission('create_presentation')) {
          const generateButton = document.createElement('button');
          generateButton.type = 'button';
          generateButton.className = 'section-approve-btn section-presentation-btn';
          generateButton.dataset.sectionLockIgnore = '1';
          generateButton.textContent = 'توليد عرض القسم';
          if (typeof tr === 'function') generateButton.textContent = tr(generateButton.textContent);
          generateButton.dataset.arText = 'توليد عرض القسم';
          generateButton.addEventListener('click', () => generateProjectSectionPresentation(sectionKey, label));
          title.appendChild(generateButton);
        }
        const toggleButton = document.createElement('button');
        toggleButton.type = 'button';
        toggleButton.className = 'section-approve-btn';
        toggleButton.id = 'section-lock-toggle-' + sectionKey;
        toggleButton.dataset.sectionLockIgnore = '1';
        toggleButton.textContent = status === 'approved' ? 'الغاء الاعتماد' : 'اعتماد';
        if (typeof tr === 'function') toggleButton.textContent = tr(toggleButton.textContent);
        toggleButton.dataset.arText = status === 'approved' ? 'الغاء الاعتماد' : 'اعتماد';
        toggleButton.addEventListener('click', () => {
          const next = (tenantProjectSectionStatuses[sectionKey] === 'approved') ? 'draft' : 'approved';
          setSectionStatus(sectionKey, next);
        });
        title.appendChild(toggleButton);
        const sendButton = document.createElement('button');
        sendButton.type = 'button';
        sendButton.className = 'section-approve-btn';
        sendButton.id = 'section-send-' + sectionKey;
        sendButton.dataset.sectionLockIgnore = '1';
        sendButton.textContent = 'إرسال للاعتماد';
        if (typeof tr === 'function') sendButton.textContent = tr(sendButton.textContent);
        sendButton.dataset.arText = 'إرسال للاعتماد';
        sendButton.addEventListener('click', () => sendSectionVersion(sectionKey));
        title.appendChild(sendButton);
        const versionsButton = document.createElement('button');
        versionsButton.type = 'button';
        versionsButton.className = 'section-approve-btn';
        versionsButton.id = 'section-versions-toggle-' + sectionKey;
        versionsButton.dataset.sectionLockIgnore = '1';
        versionsButton.textContent = 'الإصدارات';
        if (typeof tr === 'function') versionsButton.textContent = tr(versionsButton.textContent);
        versionsButton.dataset.arText = 'الإصدارات';
        versionsButton.addEventListener('click', () => toggleSectionVersions(sectionKey));
        title.appendChild(versionsButton);
      }
      return title;
    }

    function applySectionLockState(sectionKey, status) {
      const section = getProjectSectionElement(sectionKey);
      if (!section) return;
      const approved = status === 'approved';
      section.classList.remove('section-draft', 'section-approved', 'section-locked');
      section.classList.add(approved ? 'section-approved' : 'section-draft');
      section.classList.toggle('section-locked', approved);
      section.querySelectorAll('input,select,textarea,button').forEach(control => {
        if (control.dataset.sectionLockIgnore === '1' || control.type === 'hidden') {
          control.disabled = false;
          return;
        }
        if (approved) {
          if (!Object.prototype.hasOwnProperty.call(control.dataset, 'sectionLockWasDisabled')) {
            control.dataset.sectionLockWasDisabled = control.disabled ? '1' : '0';
          }
          control.disabled = true;
        } else if (Object.prototype.hasOwnProperty.call(control.dataset, 'sectionLockWasDisabled')) {
          control.disabled = control.dataset.sectionLockWasDisabled === '1';
          delete control.dataset.sectionLockWasDisabled;
        }
      });
    }

    function applySectionStatuses(statuses) {
      tenantProjectSectionStatuses = { ...tenantProjectSectionStatuses, ...(statuses || {}) };
      const keys = new Set([
        ...Object.keys(statuses || {}),
        ...Array.from(document.querySelectorAll('#tenantProjectForm .tenant-form-section[data-section]:not([data-under-construction="1"])')).map(section => section.dataset.section)
      ]);
      const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
      const dict = (typeof window.WFI18n !== 'undefined' && window.WFI18n.autoDict) || (typeof WFI18N_EN_AUTO !== 'undefined' ? WFI18N_EN_AUTO : (window.WFI18N_EN_AUTO || null));
      const tr = text => (isEn && dict && dict[text]) ? dict[text] : text;
      keys.forEach(sectionKey => {
        if (!sectionKey) return;
        const section = getProjectSectionElement(sectionKey);
        if (section && section.dataset.underConstruction === '1') return;
        const normalizedStatus = tenantProjectSectionStatuses[sectionKey] === 'approved' ? 'approved' : 'draft';
        applySectionLockState(sectionKey, normalizedStatus);
        const badge = document.getElementById('badge-' + sectionKey);
        if (badge) {
          badge.className = 'section-status-badge ' + normalizedStatus;
          badge.textContent = normalizedStatus === 'approved' ? tr('معتمد') : tr('مسودة');
          badge.dataset.arText = normalizedStatus === 'approved' ? 'معتمد' : 'مسودة';
        }
        const toggle = document.getElementById('section-lock-toggle-' + sectionKey);
        if (toggle) {
          toggle.textContent = normalizedStatus === 'approved' ? tr('الغاء الاعتماد') : tr('اعتماد');
          toggle.dataset.arText = normalizedStatus === 'approved' ? 'الغاء الاعتماد' : 'اعتماد';
        }
        updateProjectSidebarStatus(sectionKey, normalizedStatus);
      });
      try { if (typeof refreshAllSectionVersionLines === 'function') refreshAllSectionVersionLines(); } catch (e) {}
    }

    async function setSectionStatus(sectionKey, status) {
      if (sectionKey === 'location' && status === 'approved') {
        const approvals = tenantCreativeImages.map_approvals || {};
        if (!tenantProjectData.location_analysis_approved || MAP_PREVIEW_VIEW_DEFS.some(view => !approvals[view.mapType])) {
          toast('اعتماد تحليل الموقع والخرائط الأربع مطلوب قبل اعتماد قسم الموقع');
          return;
        }
      }
      if (sectionKey === 'land_croquis' && status === 'approved') {
        const errors = validateLandCroquisClientFields();
        if (errors.length > 0) {
          toast(errors[0].message);
          const firstInput = document.querySelector('#tenantProjectForm [data-key="' + errors[0].key + '"]');
          if (firstInput) {
            firstInput.focus();
            firstInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
          return;
        }
      }
      if (status === 'approved') {
        // t10: an approval must name the snapshot it approved. The direct status
        // write left sections "approved" with an empty version history and no
        // frozen copy to audit, so approving now freezes this moment's inputs as
        // a version and decides it in the same step.
        await approveSectionWithVersion(sectionKey);
        return;
      }
      const result = await api('POST', '/api/project-draft/section-status', { draftId: tenantProjectData.draftId, sectionKey: sectionKey, sectionStatus: status });
      if (!result.success) { toast(result.error || 'تعذر تحديث حالة القسم'); return; }
      applySectionStatuses({ [sectionKey]: status });
    }

    // Approve through the version flow: the section's current inputs are frozen
    // as the next version and decided in one step. A version still pending is
    // decided as sent — unless the form carried unsaved edits, in which case a
    // fresh snapshot supersedes it so approval never lands on stale data.
    async function approveSectionWithVersion(sectionKey, options = {}) {
      const hadUnsaved = options.pendingStale === undefined
        ? (tenantDraftDirty || !tenantProjectData.draftId)
        : options.pendingStale;
      if (!options.skipSave && (tenantDraftDirty || !tenantProjectData.draftId)) {
        // The server snapshots the stored draft, and autosave only marks the
        // form dirty — without this flush a send freezes stale data, or fails
        // the required-field gate on fields filled on screen but never saved.
        const saved = await saveProjectAsDraft(true);
        if (!saved) {
          toast(WFT('sectionver.send_save_failed', 'تعذر حفظ المسودة قبل الإرسال'));
          return false;
        }
      }
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        await loadAllSectionVersions();
        const pending = (sectionVersionCache[sectionKey] || []).find(version => version.status === 'pending');
        let versionId = (pending && !hadUnsaved) ? pending.id : null;
        if (!versionId) {
          const sent = await api('POST', '/api/project-draft/section-version', {
            draftId: tenantProjectData.draftId, sectionKey: sectionKey, supersede: true });
          if (!sent || !sent.success) {
            if (sent && sent.error_code === 'SECTION_VERSION_INCOMPLETE') {
              const missing = Array.isArray(sent.missing) ? sent.missing.join('، ') : '';
              toast(WFT('sectionver.incomplete', 'حقول إلزامية ناقصة') + (missing ? ': ' + missing : ''));
              return false;
            }
            // A caller versions cannot reach (e.g. a scoped user approving on
            // someone else's draft) keeps the previous direct toggle.
            const legacy = await api('POST', '/api/project-draft/section-status', {
              draftId: tenantProjectData.draftId, sectionKey: sectionKey, sectionStatus: 'approved' });
            if (!legacy || !legacy.success) {
              toast((legacy && legacy.error) || (sent && sent.error) || WFT('sectionver.send_failed', 'تعذر إرسال القسم للاعتماد'));
              return false;
            }
            applySectionStatuses({ [sectionKey]: 'approved' });
            return true;
          }
          versionId = sent.version.id;
        }
        const decided = await api('POST', '/api/project-draft/section-version/decision', {
          versionId: versionId, decision: 'approved' });
        if (!decided || !decided.success) {
          toast((decided && decided.error) || WFT('sectionver.decide_failed', 'تعذر تسجيل القرار'));
          await loadAllSectionVersions();
          return false;
        }
        applySectionStatuses({ [sectionKey]: 'approved' });
        toast(WFT('sectionver.decide_done', 'تم تسجيل القرار'));
        await loadAllSectionVersions();
        return true;
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    async function approveAllSections() {
      const sections = document.querySelectorAll('.tenant-form-section[data-section]');
      const keys = [];
      let landCroquisBlocked = false;
      let locationBlocked = false;
      sections.forEach(sec => {
        if (sec.dataset.underConstruction === '1') return;
        const key = sec.dataset.section;
        if (key === 'location') {
          const approvals = tenantCreativeImages.map_approvals || {};
          if (!tenantProjectData.location_analysis_approved || MAP_PREVIEW_VIEW_DEFS.some(view => !approvals[view.mapType])) {
            locationBlocked = true;
            return;
          }
        }
        if (key === 'land_croquis') {
          const errors = validateLandCroquisClientFields();
          if (errors.length > 0) {
            landCroquisBlocked = true;
            toast(errors[0].message);
            const firstInput = document.querySelector('#tenantProjectForm [data-key="' + errors[0].key + '"]');
            if (firstInput) {
              firstInput.focus();
              firstInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            return;
          }
        }
        keys.push(key);
      });
      if (!keys.length) return;
      // One flush before the batch: every approval freezes the stored draft, so
      // unsaved edits must land first — and a version still pending predates
      // them, so it is superseded rather than decided.
      const hadUnsaved = tenantDraftDirty || !tenantProjectData.draftId;
      if (hadUnsaved && !(await saveProjectAsDraft(true))) {
        toast(WFT('sectionver.send_save_failed', 'تعذر حفظ المسودة قبل الإرسال'));
        return;
      }
      let failed = 0;
      for (const key of keys) {
        try {
          if (!(await approveSectionWithVersion(key, { skipSave: true, pendingStale: hadUnsaved }))) failed += 1;
        } catch (e) {
          failed += 1;
        }
      }
      if (failed || landCroquisBlocked || locationBlocked) {
        toast('تم اعتماد الأقسام المكتملة، وبقي قسم يحتاج استكمال متطلبات الاعتماد');
      } else {
        toast('تم اعتماد جميع الأقسام');
      }
    }

    async function requestProjectDraftApproval() {
      // Same stored-draft caveat as the section sends: the request must review
      // the edits on screen, not the last saved copy.
      if (tenantDraftDirty || !tenantProjectData.draftId) {
        const saved = await saveProjectAsDraft(true);
        if (!saved) { toast(WFT('sectionver.send_save_failed', 'تعذر حفظ المسودة قبل الإرسال')); return; }
      }
      const result = await api('POST', '/api/project-draft/request-approval', { draftId: tenantProjectData.draftId });
      if (!result.success) {
        toast(result.error_code === 'SECTIONS_NOT_APPROVED'
          ? 'يجب اعتماد جميع أقسام المشروع قبل طلب الاعتماد'
          : (result.error || 'لا يمكن طلب الاعتماد الآن'));
        return;
      }
      tenantProjectDraftApproval = result.draft || null;
      updateProposalLifecycleBadge((result.draft && result.draft.status) || 'section_approval_pending');
      toast('تم إرسال المسودة للاعتماد');
    }

    // ── Section versions (t10): immutable snapshots bound to approval ────
    // One send freezes the section inputs of this moment under the next
    // version number, and every decision names that number. History stays
    // intact: restoring an old version opens a new pending version from it.
    const sectionVersionCache = {};
    const sectionVersionsOpen = {};
    let sectionVersionsLoading = false;

    function trSectionVersionChrome(text) {
      try {
        const isEn = typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en';
        const dict = (typeof window.WFI18n !== 'undefined' && window.WFI18n.autoDict) || window.WFI18N_EN_AUTO || null;
        if (isEn && dict && dict[text]) return dict[text];
      } catch (e) {}
      return text;
    }

    function setSectionVersionChrome(el, arText) {
      el.textContent = trSectionVersionChrome(arText);
      el.dataset.arText = arText;
    }

    function sectionVersionLineText(version) {
      if (!version) return WFT('sectionver.line_none', 'لا توجد إصدارات');
      const n = version.version_number;
      if (version.status === 'approved') return WFT('sectionver.line_approved', 'إصدار {n} معتمد', { n: n });
      if (version.status === 'returned') return WFT('sectionver.line_returned', 'إصدار {n} معاد للتعديل', { n: n });
      if (version.status === 'rejected') return WFT('sectionver.line_rejected', 'إصدار {n} مرفوض', { n: n });
      if (version.status === 'cancelled') return WFT('sectionver.line_cancelled', 'إصدار {n} ملغي', { n: n });
      if (version.status === 'superseded') return WFT('sectionver.line_superseded', 'إصدار {n} مستبدل', { n: n });
      return WFT('sectionver.line_pending', 'إصدار {n} بانتظار القرار', { n: n });
    }

    function attachSectionVersionBlock(sectionKey) {
      const section = getProjectSectionElement(sectionKey);
      if (!section || section.dataset.underConstruction === '1') return null;
      const header = section.querySelector(':scope > h3.tenant-section-title');
      // The status line is title chrome: it sits beside the status badge in the
      // header row instead of taking a row of its own above the fields.
      let line = document.getElementById('section-version-line-' + sectionKey);
      if (!line && header) {
        line = document.createElement('span');
        line.className = 'tenant-hint section-version-line';
        line.id = 'section-version-line-' + sectionKey;
        line.hidden = true;
        const badge = header.querySelector('.section-status-badge');
        if (badge && badge.nextSibling) header.insertBefore(line, badge.nextSibling);
        else header.appendChild(line);
      }
      return line;
    }

    // ── Versions page: a dedicated overlay instead of an inline panel ────────
    // The section's "الإصدارات" button opens a page of its own listing every
    // snapshot; "معاينة" renders one version like the section itself with each
    // field's previous and new value side by side.
    let sectionVersionsPageKey = null;

    function ensureSectionVersionsPage() {
      let overlay = document.getElementById('sectionVersionsPage');
      if (overlay) return overlay;
      overlay = document.createElement('div');
      overlay.id = 'sectionVersionsPage';
      overlay.className = 'om-modal-overlay section-versions-overlay';
      overlay.setAttribute('data-a11y-modal', '');
      overlay.addEventListener('click', event => {
        if (event.target === overlay) closeSectionVersionsPage();
      });
      const card = document.createElement('div');
      card.className = 'om-modal-card section-versions-card';
      card.setAttribute('role', 'dialog');
      card.setAttribute('aria-modal', 'true');
      const head = document.createElement('div');
      head.className = 'sag-modal-head';
      const title = document.createElement('h2');
      title.id = 'sectionVersionsPageTitle';
      head.appendChild(title);
      const closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'btn ghost small';
      closeBtn.textContent = WFT('common.close', 'إغلاق');
      closeBtn.addEventListener('click', closeSectionVersionsPage);
      head.appendChild(closeBtn);
      card.appendChild(head);
      const body = document.createElement('div');
      body.id = 'sectionVersionsPageBody';
      card.appendChild(body);
      overlay.appendChild(card);
      document.body.appendChild(overlay);
      return overlay;
    }

    function openSectionVersionsPage(sectionKey) {
      const overlay = ensureSectionVersionsPage();
      sectionVersionsPageKey = sectionKey;
      sectionVersionsOpen[sectionKey] = true;
      const title = document.getElementById('sectionVersionsPageTitle');
      const section = getProjectSectionElement(sectionKey);
      const header = section && section.querySelector(':scope > h3.tenant-section-title');
      const label = (header && header.dataset.arLabel) || PROJECT_SECTION_PRESENTATION_TITLES[sectionKey] || sectionKey;
      title.textContent = WFT('sectionver.page_title', 'إصدارات القسم — {s}', { s: label });
      const body = document.getElementById('sectionVersionsPageBody');
      body.innerHTML = '';
      const history = document.createElement('div');
      history.className = 'section-version-history';
      history.id = 'section-version-history-' + sectionKey;
      body.appendChild(history);
      overlay.style.display = 'flex';
      if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(overlay);
      renderSectionVersionBlock(sectionKey);
      if (!(sectionVersionCache[sectionKey] || []).length) {
        void loadAllSectionVersions().then(() => {
          if (sectionVersionsPageKey === sectionKey) renderSectionVersionBlock(sectionKey);
        });
      }
    }

    function closeSectionVersionsPage() {
      const overlay = document.getElementById('sectionVersionsPage');
      if (overlay) overlay.style.display = 'none';
      sectionVersionsPageKey = null;
      if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
    }

    function renderSectionVersionBlock(sectionKey) {
      attachSectionVersionBlock(sectionKey);
      const line = document.getElementById('section-version-line-' + sectionKey);
      const history = document.getElementById('section-version-history-' + sectionKey);
      const versions = sectionVersionCache[sectionKey] || [];
      // The empty state holds no permanent space: the status line renders only
      // once a version exists, and the versions list itself lives on the
      // dedicated versions page — without it open there is nothing to render into.
      if (line) {
        line.hidden = !versions.length;
        line.textContent = versions.length ? sectionVersionLineText(versions[0]) : '';
      }
      if (!history) return;
      history.hidden = false;
      history.innerHTML = '';
      const hint = document.createElement('p');
      hint.className = 'tenant-hint';
      if (sectionVersionsLoading && !versions.length) {
        hint.textContent = WFT('loader.loading', 'جاري التحميل...');
        history.appendChild(hint);
        return;
      }
      if (!versions.length) {
        hint.textContent = WFT('sectionver.line_none', 'لا توجد إصدارات');
        history.appendChild(hint);
        return;
      }
      versions.forEach(version => {
        const row = document.createElement('div');
        row.className = 'section-version-row';
        const meta = document.createElement('span');
        meta.className = 'section-version-meta';
        let text = sectionVersionLineText(version);
        if (version.created_at) text += ' — ' + String(version.created_at).slice(0, 16).replace('T', ' ');
        const decider = version.decided_by_name || version.created_by_name || '';
        if (decider) text += ' — ' + decider;
        if (version.decision_note) text += ' — ' + version.decision_note;
        // مصفوفة الفصل بين المهام: اعتماد المحرر لقسم شارك فيه يبقى مسموحًا لكنه يُسجل كتنبيه تدقيقي.
        if (version.decided_at && version.created_by && version.decided_by
            && String(version.created_by) === String(version.decided_by)) {
          text += ' — ' + WFT('sectionver.self_approval', 'اعتماد ذاتي');
        }
        // القرار d05: مدة اعتماد القسم قبل اعتباره قديماً (30 يوماً)
        if (version.status === 'approved' && version.decided_at) {
          const decidedTime = new Date(version.decided_at).getTime();
          const ageDays = (Date.now() - decidedTime) / (1000 * 60 * 60 * 24);
          if (ageDays > 30) {
            text += ' — ' + WFT('sectionver.stale', 'اعتماد قديم (>30 يوم)');
          }
        }
        meta.textContent = text;
        row.appendChild(meta);
        const addBtn = (arText, onClick) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'section-approve-btn';
          btn.dataset.sectionLockIgnore = '1';
          setSectionVersionChrome(btn, arText);
          btn.addEventListener('click', onClick);
          row.appendChild(btn);
          return btn;
        };
        addBtn(WFT('sectionver.preview', 'معاينة'), () => toggleSectionVersionDiff(version.id, sectionKey));
        if (version.status === 'pending') {
          addBtn('اعتماد', () => decideSectionVersion(version.id, sectionKey, 'approved'));
          addBtn('إعادة للتعديل', () => decideSectionVersion(version.id, sectionKey, 'returned'));
          addBtn('رفض', () => decideSectionVersion(version.id, sectionKey, 'rejected'));
          addBtn('إلغاء الطلب', () => cancelSectionVersion(version.id, sectionKey));
        } else {
          addBtn('استعادة', () => restoreSectionVersion(version.id, sectionKey));
        }
        history.appendChild(row);
      });
      renderSectionDiffPanel(sectionKey);
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
        try { window.WFI18n.autoTranslate(history); } catch (e) {}
      }
    }

    async function loadAllSectionVersions() {
      if (!tenantProjectData || !tenantProjectData.draftId) return;
      if (sectionVersionsLoading) return;
      sectionVersionsLoading = true;
      try {
        const result = await api('GET', '/api/project-draft/section-versions?draftId=' + encodeURIComponent(tenantProjectData.draftId));
        if (!result || !result.success) return;
        const grouped = {};
        (result.versions || []).forEach(version => {
          const key = version.section_key;
          if (!grouped[key]) grouped[key] = [];
          grouped[key].push(version);
        });
        Object.keys(grouped).forEach(key => { sectionVersionCache[key] = grouped[key]; });
        document.querySelectorAll('#tenantProjectForm .tenant-form-section[data-section]').forEach(section => {
          const key = section.dataset.section;
          if (!key || section.dataset.underConstruction === '1') return;
          if (!sectionVersionCache[key]) sectionVersionCache[key] = [];
          renderSectionVersionBlock(key);
        });
      } finally {
        sectionVersionsLoading = false;
      }
    }

    function refreshAllSectionVersionLines() {
      if (!tenantProjectData || !tenantProjectData.draftId) return;
      document.querySelectorAll('#tenantProjectForm .tenant-form-section[data-section]').forEach(section => {
        const key = section.dataset.section;
        if (!key || section.dataset.underConstruction === '1') return;
        attachSectionVersionBlock(key);
      });
      void loadAllSectionVersions();
    }

    function toggleSectionVersions(sectionKey) {
      openSectionVersionsPage(sectionKey);
    }

    async function sendSectionVersion(sectionKey) {
      const btn = document.getElementById('section-send-' + sectionKey);
      if (btn) btn.disabled = true;
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        // The snapshot freezes the stored draft, and autosave only marks the
        // form dirty — flush pending edits first or the send validates stale
        // data and fails on required fields that are filled on screen.
        if (tenantDraftDirty || !tenantProjectData.draftId) {
          const saved = await saveProjectAsDraft(true);
          if (!saved) {
            hideLoader();
            toast(WFT('sectionver.send_save_failed', 'تعذر حفظ المسودة قبل الإرسال'));
            return;
          }
        }
        const result = await api('POST', '/api/project-draft/section-version', { draftId: tenantProjectData.draftId, sectionKey: sectionKey });
        hideLoader();
        if (!result || !result.success) {
          if (result && result.error_code === 'SECTION_VERSION_INCOMPLETE') {
            const missing = Array.isArray(result.missing) ? result.missing.join('، ') : '';
            toast(WFT('sectionver.incomplete', 'حقول إلزامية ناقصة') + (missing ? ': ' + missing : ''));
          } else {
            toast((result && result.error) || WFT('sectionver.send_failed', 'تعذر إرسال القسم للاعتماد'));
          }
          return;
        }
        toast(WFT('sectionver.send_done', 'تم إرسال القسم للاعتماد'));
        openSectionVersionsPage(sectionKey);
        await loadAllSectionVersions();
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function decideSectionVersion(versionId, sectionKey, decision) {
      let note = null;
      if (decision === 'returned' || decision === 'rejected') {
        note = prompt(WFT('sectionver.note_prompt', 'سبب الإعادة'));
        if (!note || !String(note).trim()) { toast(WFT('sectionver.note_required', 'سبب الإعادة مطلوب')); return; }
      }
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        const result = await api('POST', '/api/project-draft/section-version/decision', { versionId: versionId, decision: decision, note: note });
        hideLoader();
        if (!result || !result.success) { toast((result && result.error) || WFT('sectionver.decide_failed', 'تعذر تسجيل القرار')); return; }
        applySectionStatuses({ [sectionKey]: decision === 'approved' ? 'approved' : 'draft' });
        toast(WFT('sectionver.decide_done', 'تم تسجيل القرار'));
        await loadAllSectionVersions();
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    async function cancelSectionVersion(versionId, sectionKey) {
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        const result = await api('POST', '/api/project-draft/section-version/cancel', { versionId: versionId });
        hideLoader();
        if (!result || !result.success) { toast((result && result.error) || WFT('sectionver.cancel_failed', 'تعذر إلغاء طلب الاعتماد')); return; }
        toast(WFT('sectionver.cancel_done', 'تم إلغاء طلب الاعتماد'));
        await loadAllSectionVersions();
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    async function restoreSectionVersion(versionId, sectionKey) {
      showLoader(WFT('sectionver.send_title', 'إرسال القسم للاعتماد'), '', 10);
      try {
        const result = await api('POST', '/api/project-draft/section-version/restore', { versionId: versionId });
        hideLoader();
        if (!result || !result.success) { toast((result && result.error) || WFT('sectionver.restore_failed', 'تعذر الاستعادة')); return; }
        if (result.revision !== undefined) tenantDraftRevision = Number(result.revision) || tenantDraftRevision;
        toast(WFT('sectionver.restore_done', 'تمت الاستعادة كإصدار جديد'));
        openSectionVersionsPage(sectionKey);
        await loadAllSectionVersions();
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    // ── Section version comparison (t13): what changed between two snapshots ──
    // The approver opens the differences of a sent version against its
    // predecessor (or an explicit one) before deciding. One cached diff per
    // section stays visible until it is closed or another version is compared.
    const sectionVersionDiffCache = {};

    // Blob values (objects/arrays) never render as raw JSON in the preview —
    // they are laid out as labelled key/value rows, and a uniform array of flat
    // objects becomes a real table. Telemetry keys (diagnostics, confidence
    // maps, per-document processing) are processing metadata, not land data, so
    // they stay out of the view.
    const DIFF_BLOB_SKIP_KEYS = new Set(['extraction_diagnostics', 'document_processing', 'confidence']);

    const DIFF_BLOB_KEY_LABELS = {
      parcel_id: 'القطعة', plot_number: 'رقم القطعة', plan_number: 'رقم المخطط',
      subdivision_number: 'البلك', deed_number: 'رقم الصك', deed_date: 'تاريخ الصك',
      area_sqm: 'المساحة (م²)', zoning_code: 'كود التنظيم', allowed_uses: 'الاستخدامات',
      allowed_uses_restrictions: 'قيود الاستخدامات', building_ratio: 'نسبة البناء',
      building_ratio_coverage: 'نسب البناء والتغطية', building_ratio_setbacks: 'نسب البناء والارتدادات',
      coverage_ratio: 'نسبة التغطية', floor_area_ratio: 'معامل مسطح البناء (FAR)',
      max_floors_height: 'الأدوار والارتفاع', table_floors: 'الأدوار بموجب الجدول',
      setbacks: 'الارتدادات', facades_count: 'عدد الواجهات', facades_directions: 'اتجاهات الواجهات',
      north_direction: 'اتجاه الشمال', summary: 'الملخص',
      north: 'شمال', south: 'جنوب', east: 'شرق', west: 'غرب',
      point: 'النقطة', eastings: 'شرقيات', northings: 'شماليات',
      boundary_length_m: 'طول الحد (م)', street_name: 'اسم الشارع', street_width_m: 'عرض الشارع (م)',
      uses: 'الحد/الاستخدام', setback: 'الارتداد', lat: 'خط العرض', lng: 'خط الطول',
      directions: 'الاتجاهات', coordinates: 'الإحداثية', survey_coordinates: 'إحداثيات المساحة',
      regulation_coordinates: 'إحداثيات التنظيم', coordinate_tables: 'جداول الإحداثيات',
      coordinates_table_name: 'جدول الإحداثيات', coordinates_table_source_page: 'صفحة جدول الإحداثيات',
      regulation_text: 'النص التنظيمي', table_name: 'الجدول', rows: 'الصفوف',
      parcels: 'القطع', conflicts: 'التعارضات', sources: 'المصادر', source: 'المصدر',
      source_priority: 'أولوية المصادر', land_use_status: 'حالة الاستخدام',
      parking_requirements: 'اشتراطات المواقف', entrances_exits_requirements: 'اشتراطات المداخل والمخارج',
      regulatory_constraints: 'القيود التنظيمية',
      name: 'الاسم', category: 'النوع', type: 'النوع', value: 'القيمة', field: 'الحقل',
      label: 'الوصف', description: 'الوصف', role: 'الدور', company: 'الشركة',
      status: 'الحالة', date: 'التاريخ', amount: 'المبلغ', price: 'السعر',
      total: 'الإجمالي', count: 'العدد', percent: 'النسبة', notes: 'ملاحظات',
      distance_km: 'المسافة (كم)', duration_minutes: 'المدة (دقيقة)',
      duration_min: 'المدة (دقيقة)', show_on_map: 'يظهر على الخريطة',
      audience: 'الفئة المستهدفة', components: 'المكونات', segments: 'الفئات',
      access: 'خريطة الوصول', catchment: 'خريطة التغطية', landmarks: 'خريطة المعالم',
      overview: 'الخريطة العامة', enabled: 'مفعّل', visible: 'ظاهر',
      residential: 'سكني', commercial: 'تجاري', offices: 'مكاتب', retail: 'تجزئة',
      hotel: 'فندقي', mixed: 'مختلط', area: 'المساحة', floors: 'الأدوار',
      revenue: 'الإيراد', cost: 'التكلفة', year: 'السنة', month: 'الشهر',
      start: 'البداية', end: 'النهاية', phase: 'المرحلة', milestone: 'المرحلة',
      task: 'المهمة', owner: 'المسؤول', duration: 'المدة', progress: 'التقدم',
    };

    function diffBlobKeyLabel(key) {
      return DIFF_BLOB_KEY_LABELS[key] || key;
    }

    // Some fields store structured data as serialized JSON text; a string that
    // parses to an object/array renders structured like a real blob — printing
    // it raw would also garble the braces under RTL bidi.
    function diffParseJsonString(value) {
      if (typeof value !== 'string') return null;
      const trimmed = value.trim();
      if (trimmed.length < 2) return null;
      const first = trimmed[0];
      const last = trimmed[trimmed.length - 1];
      if ((first !== '{' || last !== '}') && (first !== '[' || last !== ']')) return null;
      try {
        const parsed = JSON.parse(trimmed);
        return (parsed && typeof parsed === 'object') ? parsed : null;
      } catch (e) {
        return null;
      }
    }

    function diffScalarText(value) {
      if (typeof value === 'boolean') return value ? 'نعم' : 'لا';
      return String(value);
    }

    function sectionVersionValueIsEmpty(value) {
      if (value === null || value === undefined || value === '') return true;
      if (Array.isArray(value)) return !value.length;
      if (typeof value === 'object') return !Object.keys(value).length;
      return false;
    }

    function diffValueNode(value) {
      const box = document.createElement('div');
      box.className = 'section-version-diff-struct';
      if (Array.isArray(value)) {
        const items = value.filter(item => !sectionVersionValueIsEmpty(item));
        if (!items.length) { box.textContent = '—'; return box; }
        const allScalar = items.every(item => typeof item !== 'object' || item === null);
        const flatObjects = !allScalar && items.every(item =>
          item && typeof item === 'object' && !Array.isArray(item) &&
          Object.keys(item).every(key => item[key] === null || typeof item[key] !== 'object'));
        if (allScalar) {
          items.forEach(item => {
            const line = document.createElement('div');
            line.className = 'section-version-diff-line';
            line.textContent = diffScalarText(item);
            box.appendChild(line);
          });
          return box;
        }
        if (flatObjects) {
          const cols = [];
          items.forEach(item => Object.keys(item).forEach(key => {
            if (!DIFF_BLOB_SKIP_KEYS.has(key) && !cols.includes(key)) cols.push(key);
          }));
          if (cols.length && cols.length <= 6) {
            const table = document.createElement('table');
            table.className = 'section-version-diff-table';
            const headRow = document.createElement('tr');
            cols.forEach(key => {
              const th = document.createElement('th');
              th.textContent = diffBlobKeyLabel(key);
              headRow.appendChild(th);
            });
            table.appendChild(headRow);
            items.forEach(item => {
              const tr = document.createElement('tr');
              cols.forEach(key => {
                const td = document.createElement('td');
                const cell = item[key];
                td.textContent = cell === null || cell === undefined || cell === '' ? '—' : diffScalarText(cell);
                tr.appendChild(td);
              });
              table.appendChild(tr);
            });
            box.appendChild(table);
            return box;
          }
        }
        items.forEach(item => {
          const sub = document.createElement('div');
          sub.className = 'section-version-diff-sub';
          const parsed = diffParseJsonString(item);
          if (item && typeof item === 'object') sub.appendChild(diffValueNode(item));
          else if (parsed) sub.appendChild(diffValueNode(parsed));
          else { sub.classList.add('section-version-diff-line'); sub.textContent = diffScalarText(item); }
          box.appendChild(sub);
        });
        return box;
      }
      Object.keys(value).forEach(key => {
        if (DIFF_BLOB_SKIP_KEYS.has(key)) return;
        const item = value[key];
        if (sectionVersionValueIsEmpty(item)) return;
        const kv = document.createElement('div');
        kv.className = 'section-version-diff-kv';
        const k = document.createElement('span');
        k.className = 'section-version-diff-key';
        k.textContent = diffBlobKeyLabel(key);
        kv.appendChild(k);
        const parsed = diffParseJsonString(item);
        if (item && typeof item === 'object') {
          const nested = document.createElement('div');
          nested.className = 'section-version-diff-nested';
          nested.appendChild(diffValueNode(item));
          kv.appendChild(nested);
        } else if (parsed) {
          const nested = document.createElement('div');
          nested.className = 'section-version-diff-nested';
          nested.appendChild(diffValueNode(parsed));
          kv.appendChild(nested);
        } else {
          const val = document.createElement('span');
          val.className = 'section-version-diff-val';
          val.textContent = diffScalarText(item);
          kv.appendChild(val);
        }
        box.appendChild(kv);
      });
      if (!box.children.length) box.textContent = '—';
      return box;
    }

    // A modified text field gets an inline diff: only the lines that actually
    // changed are tinted, and inside a changed pair of lines the differing
    // words are marked, so the approver sees exactly what moved.
    function diffPlainTextValue(value) {
      if (value === null || value === undefined) return null;
      if (typeof value === 'object') return null;
      if (diffParseJsonString(value)) return null;
      return String(value);
    }

    function diffLines(oldText, newText) {
      const a = String(oldText).split('\n');
      const b = String(newText).split('\n');
      if (a.length > 400 || b.length > 400) return null;
      const m = a.length;
      const n = b.length;
      const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
      for (let i = m - 1; i >= 0; i--) {
        for (let j = n - 1; j >= 0; j--) {
          dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
      const ops = [];
      let i = 0;
      let j = 0;
      while (i < m && j < n) {
        if (a[i] === b[j]) { ops.push({ type: 'same', oldLine: a[i], newLine: b[j] }); i++; j++; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ type: 'del', oldLine: a[i] }); i++; }
        else { ops.push({ type: 'add', newLine: b[j] }); j++; }
      }
      while (i < m) ops.push({ type: 'del', oldLine: a[i++] });
      while (j < n) ops.push({ type: 'add', newLine: b[j++] });
      return ops;
    }

    function diffWordMarks(line, paired) {
      // Token-level LCS that keeps whitespace: only the differing tokens mark.
      const mine = String(line).split(/(\s+)/);
      const other = String(paired).split(/(\s+)/);
      const m = mine.length;
      const n = other.length;
      if (m > 300 || n > 300) return null;
      const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
      for (let i = m - 1; i >= 0; i--) {
        for (let j = n - 1; j >= 0; j--) {
          dp[i][j] = mine[i] === other[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
      const marks = new Array(m).fill(false);
      let i = 0;
      let j = 0;
      while (i < m && j < n) {
        if (mine[i] === other[j]) { i++; j++; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) { marks[i] = true; i++; }
        else { j++; }
      }
      while (i < m) marks[i++] = true;
      const frags = [];
      for (let k = 0; k < m; k++) {
        const changed = marks[k] && mine[k].trim() !== '';
        const last = frags[frags.length - 1];
        if (last && last.changed === changed) last.text += mine[k];
        else frags.push({ text: mine[k], changed: changed });
      }
      return frags;
    }

    function renderDiffLines(ops, side) {
      const box = document.createElement('div');
      box.className = 'section-version-diff-text';
      let i = 0;
      while (i < ops.length) {
        if (ops[i].type === 'same') {
          const line = document.createElement('div');
          line.className = 'section-version-diff-tline';
          line.textContent = (side === 'old' ? ops[i].oldLine : ops[i].newLine) || ' ';
          box.appendChild(line);
          i++;
          continue;
        }
        const block = [];
        while (i < ops.length && ops[i].type !== 'same') { block.push(ops[i]); i++; }
        const dels = block.filter(op => op.type === 'del');
        const adds = block.filter(op => op.type === 'add');
        const source = side === 'old' ? dels : adds;
        const other = side === 'old' ? adds : dels;
        const pairs = Math.min(dels.length, adds.length);
        source.forEach((entry, idx) => {
          const lineText = side === 'old' ? entry.oldLine : entry.newLine;
          const pairedEntry = idx < pairs ? other[idx] : null;
          const pairedText = pairedEntry ? (side === 'old' ? pairedEntry.newLine : pairedEntry.oldLine) : null;
          const div = document.createElement('div');
          div.className = 'section-version-diff-tline ' + (side === 'old' ? 'diff-del' : 'diff-ins');
          const marks = pairedText === null ? null : diffWordMarks(lineText, pairedText);
          if (!marks) {
            div.textContent = lineText || ' ';
          } else {
            let wrote = false;
            marks.forEach(frag => {
              if (!frag.text) return;
              wrote = true;
              if (!frag.changed) { div.appendChild(document.createTextNode(frag.text)); return; }
              const mark = document.createElement('span');
              mark.className = 'diff-word';
              mark.textContent = frag.text;
              div.appendChild(mark);
            });
            if (!wrote) div.textContent = ' ';
          }
          box.appendChild(div);
        });
      }
      return box;
    }

    function fillScalarDiffCells(oldCell, newCell, oldValue, newValue) {
      const oldText = diffPlainTextValue(oldValue);
      const newText = diffPlainTextValue(newValue);
      if (oldText === null || newText === null || oldText === newText) return;
      const ops = diffLines(oldText, newText);
      if (!ops) return;
      const oldBox = oldCell.querySelector('.section-version-diff-value');
      const newBox = newCell.querySelector('.section-version-diff-value');
      if (!oldBox || !newBox) return;
      oldBox.innerHTML = '';
      newBox.innerHTML = '';
      oldBox.appendChild(renderDiffLines(ops, 'old'));
      newBox.appendChild(renderDiffLines(ops, 'new'));
    }

    // One side of the comparison: a captioned box so the previous value always
    // sits next to the new value, even when one of them is empty (added fields
    // have no previous value, removed fields have no new one).
    function sectionVersionDiffCell(side, value, isAttachment) {
      const cell = document.createElement('div');
      cell.className = 'section-version-diff-cell section-version-diff-' + side;
      const cap = document.createElement('span');
      cap.className = 'section-version-diff-cap';
      cap.textContent = side === 'old'
        ? WFT('sectionver.diff_col_old', 'القيمة السابقة')
        : side === 'same'
          ? WFT('sectionver.diff_col_value', 'القيمة')
          : WFT('sectionver.diff_col_new', 'القيمة الجديدة');
      cell.appendChild(cap);
      const val = document.createElement('div');
      val.className = 'section-version-diff-value';
      if (sectionVersionValueIsEmpty(value)) {
        val.textContent = '—';
        val.classList.add('is-empty');
      } else if (isAttachment) {
        const names = diffAttachmentNames(value);
        if (names.length) val.textContent = names.join('\n');
        else val.appendChild(diffValueNode(value));
      } else {
        const parsed = diffParseJsonString(value);
        if (parsed) val.appendChild(diffValueNode(parsed));
        else if (typeof value === 'object') val.appendChild(diffValueNode(value));
        else val.textContent = diffScalarText(value);
      }
      cell.appendChild(val);
      return cell;
    }

    // Attachment snapshots store file objects/ids; names read better than JSON.
    function diffAttachmentNames(value) {
      const names = [];
      const walk = item => {
        if (!item) return;
        if (Array.isArray(item)) { item.forEach(walk); return; }
        if (typeof item === 'object') {
          const name = item.originalName || item.original_name || item.name || item.filename;
          if (typeof name === 'string' && name.trim()) names.push(name);
          else Object.keys(item).forEach(key => walk(item[key]));
          return;
        }
        if (typeof item === 'string' && item.trim()) names.push(item);
      };
      walk(value);
      return names;
    }

    // The preview mirrors the section's own field order: controls carry
    // data-key, so their DOM position orders the diff rows. Snapshot-only keys
    // (stored blobs, attachments) keep their diff order at the end.
    function sectionFieldOrderMap(sectionKey) {
      const order = {};
      const section = getProjectSectionElement(sectionKey);
      if (section) {
        section.querySelectorAll('[data-key]').forEach((el, idx) => {
          const key = el.dataset ? el.dataset.key : '';
          if (key && order[key] === undefined) order[key] = idx;
        });
      }
      return order;
    }

    function sectionVersionDiffStatusText(status) {
      if (status === 'added') return WFT('sectionver.diff_added', 'مضاف');
      if (status === 'removed') return WFT('sectionver.diff_removed', 'محذوف');
      if (status === 'modified') return WFT('sectionver.diff_modified', 'معدل');
      return WFT('sectionver.diff_unchanged', 'بدون تغيير');
    }

    function renderSectionDiffPanel(sectionKey) {
      const body = document.getElementById('sectionVersionsPageBody');
      const history = document.getElementById('section-version-history-' + sectionKey);
      if (!body || !history) return;
      let panel = body.querySelector(':scope > .section-version-diff');
      if (!panel) {
        panel = document.createElement('div');
        panel.className = 'section-version-diff';
        body.appendChild(panel);
      }
      const diff = sectionVersionDiffCache[sectionKey];
      if (!diff) { panel.hidden = true; panel.innerHTML = ''; history.hidden = false; return; }
      // The preview takes over the versions page: the list stays mounted but
      // hidden until the approver goes back.
      panel.hidden = false;
      history.hidden = true;
      panel.innerHTML = '';
      const head = document.createElement('div');
      head.className = 'section-version-diff-head';
      const title = document.createElement('strong');
      title.textContent = diff.base_version_number
        ? WFT('sectionver.preview_title_between', 'معاينة الإصدار {n} — مقارنة مع الإصدار {b}', { n: diff.version_number, b: diff.base_version_number })
        : WFT('sectionver.preview_title_first', 'معاينة الإصدار {n}', { n: diff.version_number });
      head.appendChild(title);
      const closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'section-approve-btn';
      closeBtn.dataset.sectionLockIgnore = '1';
      closeBtn.textContent = WFT('common.back', 'رجوع');
      closeBtn.addEventListener('click', () => {
        delete sectionVersionDiffCache[sectionKey];
        renderSectionVersionBlock(sectionKey);
      });
      head.appendChild(closeBtn);
      panel.appendChild(head);
      const summary = diff.summary || {};
      const counts = document.createElement('p');
      counts.className = 'tenant-hint';
      counts.textContent = WFT('sectionver.diff_counts', 'تعديلات {m} — إضافات {a} — حذف {r}',
        { m: summary.modified || 0, a: summary.added || 0, r: summary.removed || 0 });
      panel.appendChild(counts);
      const attachments = Array.isArray(diff.attachments) ? diff.attachments : [];
      const order = sectionFieldOrderMap(sectionKey);
      // Only what changed: unchanged fields add noise and are already counted
      // in the summary line above.
      const items = (Array.isArray(diff.fields) ? diff.fields : [])
        .concat(attachments.map(att => Object.assign({ _diffAttachment: true }, att)))
        .filter(item => item && item.key && item.status !== 'unchanged')
        .map((item, idx) => ({ item: item, idx: idx }))
        .sort((a, b) => {
          const oa = order[a.item.key];
          const ob = order[b.item.key];
          const ia = oa === undefined ? Number.MAX_SAFE_INTEGER : oa;
          const ib = ob === undefined ? Number.MAX_SAFE_INTEGER : ob;
          return ia === ib ? a.idx - b.idx : ia - ib;
        })
        .map(x => x.item);
      if (!items.length) {
        const empty = document.createElement('p');
        empty.className = 'tenant-hint';
        empty.textContent = WFT('sectionver.diff_none', 'لا توجد تغييرات بين الإصدارين');
        panel.appendChild(empty);
        return;
      }
      const grid = document.createElement('div');
      grid.className = 'section-version-diff-grid';
      items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'tenant-field section-version-diff-row diff-' + item.status;
        const rowHead = document.createElement('div');
        rowHead.className = 'section-version-diff-row-head';
        const label = document.createElement('label');
        label.className = 'section-version-diff-label';
        label.textContent = (item._diffAttachment ? WFT('sectionver.diff_attachment', 'مرفق') + ': ' : '') + (item.label || item.key);
        rowHead.appendChild(label);
        const status = document.createElement('span');
        status.className = 'section-version-diff-status';
        status.textContent = sectionVersionDiffStatusText(item.status);
        rowHead.appendChild(status);
        row.appendChild(rowHead);
        const cols = document.createElement('div');
        cols.className = 'section-version-diff-cols';
        if (item.status === 'unchanged') {
          // Identical on both sides — one box states the value without
          // duplicating long content such as polygon or table data.
          cols.classList.add('single');
          cols.appendChild(sectionVersionDiffCell('same', item.new_value, item._diffAttachment));
        } else {
          const oldCell = sectionVersionDiffCell('old', item.old_value, item._diffAttachment);
          const newCell = sectionVersionDiffCell('new', item.new_value, item._diffAttachment);
          if (!item._diffAttachment && item.status === 'modified') {
            fillScalarDiffCells(oldCell, newCell, item.old_value, item.new_value);
          }
          cols.appendChild(oldCell);
          cols.appendChild(newCell);
        }
        row.appendChild(cols);
        grid.appendChild(row);
      });
      panel.appendChild(grid);
      if (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en') {
        try { window.WFI18n.autoTranslate(panel); } catch (e) {}
      }
    }

    async function toggleSectionVersionDiff(versionId, sectionKey) {
      const cached = sectionVersionDiffCache[sectionKey];
      if (cached && cached.version_id === versionId) {
        delete sectionVersionDiffCache[sectionKey];
        renderSectionDiffPanel(sectionKey);
        return;
      }
      showLoader(WFT('sectionver.diff_loading', 'جلب المقارنة'), '', 10);
      try {
        const result = await api('GET', '/api/project-draft/section-versions/' + encodeURIComponent(versionId) + '/diff');
        hideLoader();
        if (!result || !result.success) {
          toast((result && result.error) || WFT('sectionver.diff_failed', 'تعذر جلب المقارنة'));
          return;
        }
        sectionVersionDiffCache[sectionKey] = result.diff;
        sectionVersionsOpen[sectionKey] = true;
        renderSectionVersionBlock(sectionKey);
      } finally {
        try { hideLoader(); } catch (e) {}
      }
    }

    // ── Location data tables (roads / landmarks / catchment) ──────────────
    // These fields stay plain text in project data (each row serialized as
    // "name — X كم — Y دقائق") so maps/AI keep working, but the UI edits them
    // as proper tables with add/delete rows.
    const LOCATION_TABLE_FIELDS = {
      main_roads: { nameLabel: 'الطريق الرئيسي', nameHint: 'مثال: طريق الملك فهد', nameOnly: true, road: true, mapType: 'access' },
      nearby_landmarks: { nameLabel: 'المَعلم القريب', nameHint: 'مثال: مجمع الراشد', categoryLabel: 'النوع', mapSelectable: true, mapType: 'landmarks' },
      city_landmarks: { nameLabel: 'مَعلم المدينة', nameHint: 'مثال: الواجهة البحرية', categoryLabel: 'النوع', mapSelectable: true, mapType: 'catchment' },
    };

    function parseLocationFieldText(key, value) {
      if (Array.isArray(value)) {
        return value.map(item => ({
          name: (item && (item.name || item.area || item.title)) || '',
          category: item && (item.category || item.type || ''),
          distance_km: item && (item.distance_km ?? item.distance ?? ''),
          duration_minutes: item && (item.duration_minutes ?? item.duration_min ?? item.minutes ?? ''),
          lat: item && (item.lat ?? item.latitude ?? ''),
          lng: item && (item.lng ?? item.longitude ?? ''),
          show_on_map: !!(item && (item.show_on_map || item.selected)),
          row_source: item && (item.row_source || item.rowSource || 'manual'),
        })).filter(r => r.name);
      }
      const rows = [];
      String(value == null ? '' : value).split('\n').forEach(rawLine => {
        const line = rawLine.trim().replace(/^[-•*]\s*/, '');
        if (!line) return;
        const dur = line.match(/(\d+(?:\.\d+)?)\s*(?:دقيقة|دقائق|min|mins|minutes)/i);
        const dist = line.match(/(\d+(?:\.\d+)?)\s*(?:كم|كـم|km|kms|kilometers?)/i);
        let name = line;
        if (dur) name = name.replace(dur[0], '');
        if (dist) name = name.replace(dist[0], '');
        name = name.replace(/^[\s:：\-—–,،]+|[\s:：\-—–,،]+$/g, '').trim();
        let category = '';
        if (key === 'nearby_landmarks' || key === 'city_landmarks') {
          const categoryMatch = name.match(/\s+-\s+(ترفيهي|تعليمي|صحي|تجاري|ديني(?: ومركزي)?|ثقافي\/سياحي|حكومي\/خدمي|اجتماعي\/خدمي|النقل(?: العام)?|المشاعر|المحاور)\s*$/);
          if (categoryMatch) {
            category = categoryMatch[1];
            name = name.slice(0, categoryMatch.index).trim();
          } else {
            const pieces = name.split(/\s+[—-]\s+/).map(part => part.trim()).filter(Boolean);
            if (pieces.length > 1) {
              category = pieces.pop();
              name = pieces.join(' — ');
            }
          }
        }
        if (!name) name = line;
        rows.push({ name: name, category: category, distance_km: dist ? dist[1] : '', duration_minutes: dur ? dur[1] : '' });
      });
      return rows;
    }

    function normalizeAccessRoadNames(value) {
      const values = Array.isArray(value) ? value : String(value || '').split(/[\n,،;|]+/);
      const seen = new Set();
      const result = [];
      values.forEach(raw => {
        const name = String(raw || '').trim();
        if (!name) return;
        const prefix = name.match(/^(طريق|شارع|جادة|ممر)\s+/)?.[1] || '';
        name.split(/\s+و(?=\s|ال|شارع|طريق|جادة|ممر)\s*/).map(part => part.trim()).filter(Boolean).forEach(part => {
          if (prefix && !/^(طريق|شارع|جادة|ممر)\s+/.test(part)) part = prefix + ' ' + part;
          const key = part.replace(/^(طريق|شارع|جادة|ممر)\s+/, '').replace(/[\sـ]+/g, ' ').trim().toLowerCase();
          if (!key || seen.has(key)) return;
          seen.add(key);
          result.push(part);
        });
      });
      return result;
    }

    function formatLocationDataFetchedAt(value) {
      const date = new Date(value || '');
      if (!Number.isFinite(date.getTime())) return '';
      return new Intl.DateTimeFormat('ar-SA-u-ca-gregory', {
        timeZone: 'Asia/Riyadh', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
      }).format(date) + ' بتوقيت السعودية';
    }

    function setLocationDataFetchedAt(value = new Date().toISOString()) {
      tenantProjectData.location_data_fetched_at = value;
      const input = document.getElementById('locationDataFetchedAt');
      if (input) input.value = value;
      const display = document.getElementById('locationDataFetchedAtDisplay');
      if (display) display.textContent = value ? 'آخر تحديث للبيانات: ' + formatLocationDataFetchedAt(value) : '';
    }

    function serializeLocationTable(key) {
      const table = document.querySelector('#tenantProjectForm table.location-table[data-location-table="' + key + '"]');
      const hidden = document.querySelector('#tenantProjectForm [data-key="' + key + '"].location-table-value');
      if (!table || !hidden) return;
      const lines = [];
      const structuredRows = [];
      table.querySelectorAll('tbody tr').forEach(tr => {
        const name = (tr.querySelector('.lt-name-input').value || '').trim();
        if (!name) return;
        const category = (tr.querySelector('.lt-category-input')?.value || '').trim();
        const dist = (tr.querySelector('.lt-dist-input')?.value || '').trim();
        const dur = (tr.querySelector('.lt-dur-input')?.value || '').trim();
        const parts = [name];
        if (category) parts.push(category);
        if (dist) parts.push(dist + ' كم');
        if (dur) parts.push(dur + ' دقائق');
        lines.push(parts.join(' — '));
        structuredRows.push({
          name, category, distance_km: dist, duration_minutes: dur,
          lat: tr.dataset.lat || '', lng: tr.dataset.lng || '',
          show_on_map: !!tr.querySelector('.lt-map-select')?.checked,
          row_source: tr.dataset.rowSource || 'manual'
        });
      });
      hidden.value = (key === 'main_roads' ? normalizeAccessRoadNames(lines) : lines).join('\n');
      if (key === 'main_roads') {
        tenantProjectData.main_roads = hidden.value;
        tenantProjectData.main_roads_data = structuredRows;
      } else if (key === 'nearby_landmarks') {
        tenantNearbyLandmarks = structuredRows;
        tenantProjectData.nearby_landmarks_data = structuredRows;
      } else if (key === 'city_landmarks') {
        tenantProjectData.city_landmarks_data = structuredRows;
      }
    }