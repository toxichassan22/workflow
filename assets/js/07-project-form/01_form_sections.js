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
      if (timelineBody) {
        // Drafts saved before «تاريخ البداية» stored calendar years against a bare start year;
        // map that year to January and rewrite the rows as project-relative years.
        const storedStart = typeof parseTimelineStartValue === 'function'
          ? parseTimelineStartValue(source.timeline_start_date) : null;
        const legacyStartYear = parseInt(source.timeline_start_year, 10);
        if (!storedStart && Number.isFinite(legacyStartYear)) {
          const startInput = document.getElementById('tlStartDate');
          if (startInput) startInput.value = legacyStartYear + '-01';
          tenantProjectData.timeline_start_date = legacyStartYear + '-01';
          ['year', 'endYear'].forEach(field => timelineRows.forEach(row => {
            const calendarYear = parseInt(row && row[field], 10);
            if (Number.isFinite(calendarYear) && calendarYear >= 1000) {
              row[field] = String(Math.max(1, calendarYear - legacyStartYear + 1));
            }
          }));
        }
        // The stored rows are authoritative even when empty: a cleared timeline hydrates to one
        // blank row instead of reviving whatever the builder left behind.
        timelineBody.innerHTML = '';
        if (timelineRows.length) {
          timelineRows.forEach(row => addTimelineRow(row));
        } else {
          addTimelineRow();
        }
        const timelineInput = document.getElementById('timelineTableData');
        if (timelineInput) timelineInput.value = JSON.stringify(timelineRows);
        if (typeof updateTimelineProjectEnd === 'function') updateTimelineProjectEnd();
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
        // A new project opens with the standard development phases already named.
        if (typeof seedDefaultTimelinePhases === 'function') seedDefaultTimelinePhases();
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
      overlay.className = 'll-modal-overlay section-versions-overlay';
      overlay.setAttribute('data-a11y-modal', '');
      overlay.addEventListener('click', event => {
        if (event.target === overlay) closeSectionVersionsPage();
      });
      const card = document.createElement('div');
      card.className = 'll-modal-card section-versions-card';
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

