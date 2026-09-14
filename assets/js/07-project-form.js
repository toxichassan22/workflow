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

    function hydrateTenantProjectForm(data) {
      const form = document.getElementById('tenantProjectForm');
      if (!form) return;
      editingProjectLocalTeamId = null;
      projectLocalTeamDraft = null;
      const source = data || {};
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
      const result = await api('POST', '/api/project-draft/section-status', { draftId: tenantProjectData.draftId, sectionKey: sectionKey, sectionStatus: status });
      if (!result.success) { toast(result.error || 'تعذر تحديث حالة القسم'); return; }
      applySectionStatuses({ [sectionKey]: status });
    }

    async function approveAllSections() {
      const sections = document.querySelectorAll('.tenant-form-section[data-section]');
      const statuses = {};
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
        statuses[key] = 'approved';
      });
      if ((landCroquisBlocked || locationBlocked) && Object.keys(statuses).length === 0) return;
      // One merged request: parallel per-section calls raced on the same JSON column and the
      // screen ended up showing sections as approved that the server had never stored.
      const result = await api('POST', '/api/project-draft/section-status', {
        draftId: tenantProjectData.draftId,
        sectionStatuses: statuses
      });
      if (!result.success) { toast(result.error || 'تعذر اعتماد قسم أو أكثر'); return; }
      applySectionStatuses(statuses);
      if (landCroquisBlocked || locationBlocked) {
        toast('تم اعتماد الأقسام المكتملة، وبقي قسم يحتاج استكمال متطلبات الاعتماد');
      } else {
        toast('تم اعتماد جميع الأقسام');
      }
    }

    async function requestProjectDraftApproval() {
      const result = await api('POST', '/api/project-draft/request-approval', { draftId: tenantProjectData.draftId });
      if (!result.success) {
        toast(result.error_code === 'SECTIONS_NOT_APPROVED'
          ? 'يجب اعتماد جميع أقسام المشروع قبل طلب الاعتماد'
          : (result.error || 'لا يمكن طلب الاعتماد الآن'));
        return;
      }
      tenantProjectDraftApproval = result.draft || null;
      toast('تم إرسال المسودة للاعتماد');
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