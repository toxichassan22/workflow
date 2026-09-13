/* 00-core.js - index.html lines 6647-7352, shared global scope, classic scripts in order */
    function toast(m, duration = 2400) {
      const t = document.getElementById('toast');
      t.innerHTML = m;
      t.classList.add('active');
      setTimeout(() => t.classList.remove('active'), duration);
    }

    let loaderProgressTimer = null;
    let loaderHideTimer = null;
    let loaderProgressValue = 0;
    let loaderProgressStartValue = 0;
    let loaderProgressMax = 92;
    let loaderSessionActive = false;
    let genProgressValue = 0;
    const inlineLoaderTimers = new WeakMap();

    function clampLoaderProgress(pct) {
      const value = Number(pct);
      return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0;
    }

    function renderLoaderProgress(pct, stepText, options = {}) {
      const requested = clampLoaderProgress(pct);
      const allowDecrease = !!options.allowDecrease;
      const value = allowDecrease ? requested : Math.max(loaderProgressValue, requested);
      const bar = document.getElementById('globalLoaderBar');
      const pctEl = document.getElementById('globalLoaderPct');
      const stepEl = document.getElementById('globalLoaderStep');
      const track = bar ? bar.parentElement : null;
      loaderProgressValue = value;
      if (bar) bar.style.width = value + '%';
      if (pctEl) pctEl.textContent = value + '%';
      if (stepEl && stepText !== undefined && stepText !== null) stepEl.textContent = stepText || '';
      if (track) track.setAttribute('aria-valuenow', String(value));
    }

    function stopLoaderProgressTimer() {
      if (loaderProgressTimer) {
        clearInterval(loaderProgressTimer);
        loaderProgressTimer = null;
      }
    }

    function startLoaderProgressTimer() {
      stopLoaderProgressTimer();
      const startedAt = Date.now();
      loaderProgressStartValue = loaderProgressValue;
      loaderProgressTimer = setInterval(() => {
        const elapsed = Date.now() - startedAt;
        const estimated = Math.min(loaderProgressMax, loaderProgressStartValue + Math.max(1, Math.floor(elapsed / 900)));
        if (estimated > loaderProgressValue) renderLoaderProgress(estimated);
      }, 700);
    }

    function showLoader(title, text, pct, options = {}) {
      const loader = document.getElementById('globalLoader');
      if (!loader) return;
      const alreadyVisible = loader.style.display === 'flex';
      const continueExisting = alreadyVisible && loaderSessionActive && options.reset !== true;
      clearTimeout(loaderHideTimer);
      document.getElementById('globalLoaderTitle').textContent = title || WFT('loader.loading', 'جاري التحميل...');
      document.getElementById('globalLoaderText').textContent = text || '';
      document.getElementById('globalLoaderProgress').style.display = 'block';
      loaderProgressMax = Number.isFinite(Number(options.maxProgress)) ? Math.max(1, Math.min(99, Number(options.maxProgress))) : 92;
      const nextPct = pct === undefined || pct === null ? (continueExisting ? loaderProgressValue : 5) : pct;
      if (continueExisting) {
        renderLoaderProgress(nextPct, text || WFT('loader.preparing', 'جاري التحضير...'));
      } else {
        loaderSessionActive = true;
        loaderProgressValue = 0;
        renderLoaderProgress(nextPct, text || WFT('loader.preparing', 'جاري التحضير...'), { allowDecrease: true });
      }
      loader.style.display = 'flex';
      startLoaderProgressTimer();
    }

    function updateLoaderProgress(pct, stepText) {
      const prog = document.getElementById('globalLoaderProgress');
      if (prog) prog.style.display = 'block';
      renderLoaderProgress(pct, stepText);
    }

    function hideLoader(completionText) {
      const loader = document.getElementById('globalLoader');
      if (!loader || loader.style.display === 'none') return;
      stopLoaderProgressTimer();
      renderLoaderProgress(100, completionText || WFT('loader.done', 'اكتمل'));
      const textEl = document.getElementById('globalLoaderText');
      if (textEl) textEl.textContent = completionText || WFT('loader.loaded', 'اكتمل التحميل');
      clearTimeout(loaderHideTimer);
      loaderHideTimer = setTimeout(() => {
        loader.style.display = 'none';
        loaderSessionActive = false;
        loaderProgressMax = 92;
        renderLoaderProgress(0, WFT('loader.preparing', 'جاري التحضير...'), { allowDecrease: true });
      }, 420);
    }

    async function readBlobWithProgress(response, startPct, endPct) {
      const total = Number(response.headers.get('content-length') || 0);
      if (!response.body || !total) {
        updateLoaderProgress(endPct - 2, WFT('loader.preparing_file', 'جاري تجهيز الملف للتحميل...'));
        return response.blob();
      }
      const reader = response.body.getReader();
      const chunks = [];
      let received = 0;
      while (true) {
        const result = await reader.read();
        if (result.done) break;
        chunks.push(result.value);
        received += result.value.byteLength;
        const ratio = Math.min(1, received / total);
        const pct = startPct + Math.round(ratio * (endPct - startPct));
        updateLoaderProgress(pct, WFT('loader.uploading_file', 'جاري تحميل الملف ({pct}%)...', { pct: pct }));
      }
      return new Blob(chunks, { type: response.headers.get('content-type') || 'application/octet-stream' });
    }

    function showInlineLoader(container, text) {
      if (!container) return;
      const previousTimer = inlineLoaderTimers.get(container);
      if (previousTimer) clearInterval(previousTimer);
      const label = String(text || 'جاري التحميل...')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
      container.innerHTML =
        '<div class="inline-loading-box">' +
        '<div class="inline-loading-header"><span>' + label + '</span><strong data-inline-loader-pct>5%</strong></div>' +
        '<div class="inline-loading-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="5">' +
        '<div class="inline-loading-fill" data-inline-loader-bar style="width:5%"></div>' +
        '</div></div>';
      inlineLoaderTimers.delete(container);
    }

    function setInlineLoaderProgress(container, pct, text) {
      if (!container) return;
      const bar = container.querySelector('[data-inline-loader-bar]');
      const pctEl = container.querySelector('[data-inline-loader-pct]');
      const track = bar?.parentElement;
      const value = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
      if (bar) bar.style.width = value + '%';
      if (pctEl) pctEl.textContent = value + '%';
      if (track) track.setAttribute('aria-valuenow', String(value));
      if (text) {
        const labelEl = container.querySelector('.inline-loading-header span:first-child');
        if (labelEl) labelEl.textContent = text;
      }
    }

    // ═══════════════════════════════════════════════════════════════
    // FULL-PAGE GENERATION PROGRESS
    // ═══════════════════════════════════════════════════════════════
    const GEN_STEPS = [
      { id: 'plan', label: 'إعداد خطة الشرائح' },
      { id: 'prompts', label: 'صياغة أوصاف الصور' },
      { id: 'images', label: 'توليد الصور الإبداعية' },
      { id: 'maps', label: 'توليد خرائط الموقع' },
      { id: 'slides', label: 'توليد الشرائح' },
      { id: 'save', label: 'حفظ العرض' }
    ];
    let genStartMs = 0;

    function showGenProgress() {
      genStartMs = Date.now();
      genProgressValue = 0;
      showTenantPage('tenantSlidesPage');
    }

    function setGenPct(pct, subtitle) {
      const requested = clampLoaderProgress(pct);
      const value = Math.max(genProgressValue, requested);
      genProgressValue = value;
      const bar = document.getElementById('genBar');
      const pctEl = document.getElementById('genPct');
      const subEl = document.getElementById('genSubtitle');
      const etaEl = document.getElementById('genEta');
      if (bar) bar.style.width = value + '%';
      if (pctEl) pctEl.textContent = value + '%';
      if (subEl && subtitle) subEl.textContent = subtitle;
      if (etaEl && genStartMs && value > 2) {
        const elapsed = (Date.now() - genStartMs) / 1000;
        const remaining = Math.max(0, Math.round((elapsed / value) * (100 - value)));
        etaEl.innerHTML = '<span>متبقي ~</span>' + remaining + ' <span>ثانية</span>';
      }
    }

    function setGenStep(stepId, state) {
      const el = document.getElementById('genStep_' + stepId);
      if (!el) return;
      const dot = el.querySelector('.gen-dot-wrapper');
      const label = el.querySelector('span:first-child');
      const status = el.querySelector('.gen-step-status');
      if (state === 'active') {
        el.style.background = 'var(--soft)';
        el.style.borderColor = 'var(--p)';
        el.style.boxShadow = '0 2px 6px rgba(0,0,0,0.08)';
        if (dot) { dot.style.background = 'var(--p)'; dot.style.color = '#fff'; }
        if (label) { label.style.color = 'var(--p)'; label.style.fontWeight = '700'; }
        if (status) { status.textContent = 'جاري التنفيذ...'; status.style.color = 'var(--p)'; status.style.fontWeight = '600'; }
      } else if (state === 'done') {
        el.style.background = '#f0fdf4';
        el.style.borderColor = '#bbf7d0';
        el.style.boxShadow = 'none';
        if (dot) { dot.style.background = '#16a34a'; dot.style.color = '#fff'; }
        if (label) { label.style.color = '#166534'; label.style.fontWeight = '600'; }
        if (status) { status.textContent = 'مكتمل'; status.style.color = '#16a34a'; status.style.fontWeight = '500'; }
      } else if (state === 'error') {
        el.style.background = '#fef2f2';
        el.style.borderColor = '#fecaca';
        el.style.boxShadow = 'none';
        if (dot) { dot.style.background = '#dc2626'; dot.style.color = '#fff'; }
        if (label) { label.style.color = '#991b1b'; }
        if (status) { status.textContent = 'تخطي / غير متاح'; status.style.color = '#dc2626'; }
      }
    }

    function hideGenProgress() {
      const bar = document.getElementById('genBar');
      if (bar) bar.style.width = '100%';
      setGenPct(100, 'اكتمل!');
      setTimeout(() => {
        hideLoader();
      }, 600);
    }

    function setLiveGenBanner(visible, title, details, pct) {
      const banner = document.getElementById('tenantLiveGenBanner');
      if (!banner) return;
      if (!visible) {
        banner.style.display = 'none';
        return;
      }
      banner.style.display = 'block';
      const titleEl = document.getElementById('liveGenSlideTitle');
      const detailsEl = document.getElementById('liveGenSlideDetails');
      const barEl = document.getElementById('liveGenProgressBar');
      const pctEl = document.getElementById('liveGenProgressPct');
      const resumeButton = document.getElementById('liveGenResumeButton');
      if (titleEl && title) titleEl.textContent = title;
      if (detailsEl) detailsEl.textContent = details || '';
      if (resumeButton) {
        const checkpoint = tenantSlideGenerationCheckpoint || tenantProjectData?.slide_generation_checkpoint;
        const resumable = checkpoint?.status === 'paused' && checkpoint?.active !== false;
        resumeButton.style.display = resumable ? 'inline-flex' : 'none';
      }
      if (typeof pct === 'number') {
        const clampedPct = Math.max(0, Math.min(100, Math.round(pct)));
        if (barEl) barEl.style.width = clampedPct + '%';
        if (pctEl) pctEl.textContent = clampedPct + '%';
      }
    }

    //  TENANT UI (Multi-Tenant Frontend)
    // ═══════════════════════════════════════════════════════════════════════
    const T_TOKEN_KEY = 'tenant_token';
    const T_TENANT_KEY = 'tenant_user';
    const T_NAVIGATION_KEY = 'tenant_navigation_state';
    const T_DESIGNER_JOBS_KEY = 'tenant_designer_jobs_v1';
    let tenantToken = null;
    let tenantUser = null;
    let tenantBranding = null;
    let tenantFields = [];
    let tenantFieldSections = [];
    let editingTenantFieldId = null;
    let tenantAllowedFieldSections = {};
    let tenantProjectData = {};
    let tenantProjectSectionStatuses = {};
    let tenantProjectDraftApproval = null;
    let tenantActiveProjectSection = null;
    let tenantSlidePlan = null;
    let tenantSlidesData = [];
    let tenantSlideGenerationCheckpoint = null;
    let tenantPresentationId = null;
    let tenantPresentationRevision = 0;
    let tenantPresentationProvenance = null;
    let tenantPresentationSavePromise = null;
    let tenantPresentationHistory = null;
    let tenantPresentationTitle = '';
    let tenantProjectMode = 'new';
    let tenantCreativeImages = { cover: '', moodboard: [], map_placeholders: {}, map_landmarks: [] };
    let tenantFinancialPresentationReport = null;
    let tenantVisualConceptState = null;
    let tenantArchiveCache = null;
    let tenantLocationGeocodeRequest = null;

    function mapsSignature(d, highlightSite = true) {
      d = d || tenantProjectData || {};
      const projectStyles = d.map_styles || {};
      return JSON.stringify({
        lat: d.location_lat || '',
        lng: d.location_lng || '',
        addr: d.location_address || '',
        landmarks: d.nearby_landmarks || '',
        landmarksData: d.nearby_landmarks_data || '',
        polygon: d.location_polygon || '',
        roads: d.main_roads || '',
        catchment: d.catchment_areas || '',
        cityLandmarks: d.city_landmarks || '',
        locationDetail: d.location_detail || '',
        mapType: d.map_type || (tenantBranding && tenantBranding.default_map_type) || '',
        projectStyles: projectStyles,
        styles: [
          projectStyles.overview || (tenantBranding || {}).map_style_overview,
          projectStyles.landmarks || (tenantBranding || {}).map_style_landmarks,
          projectStyles.access || (tenantBranding || {}).map_style_access,
          projectStyles.catchment || (tenantBranding || {}).map_style_catchment
        ],
        highlightSite: highlightSite !== false
      });
    }

    function imagesSignature(d) {
      d = d || tenantProjectData || {};
      return JSON.stringify({
        name: d.project_name || '',
        type: d.project_type || '',
        desc: d.project_description || '',
        count: (tenantBranding && tenantBranding.moodboard_count) || 4
      });
    }

    function shouldHighlightTenantSite() {
      // 'none' only means no boundary has been found yet, so the server must still try the
      // croquis coordinates and the other automatic sources. Highlighting is off only after
      // the user explicitly clears the boundary.
      const source = tenantProjectData && tenantProjectData.location_polygon_source;
      return source !== 'cleared';
    }

    function mapPreviewStoredUrl(view) {
      const placeholders = tenantCreativeImages?.map_placeholders || {};
      const keys = [...(view?.keys || []), ...(view?.editableKeys || [])];
      return keys.map(key => placeholders[key]).find(Boolean) || '';
    }

    function mapPreviewIsGenerated(view) {
      return !!mapPreviewStoredUrl(view);
    }

    function mapPreviewIsVisible(view, approvals = tenantCreativeImages?.map_approvals || {}) {
      if (!tenantProjectData?.location_analysis_approved) return false;
      return view?.mapType === 'overview' || !!approvals.overview;
    }

    function hasStoredMaps(highlightSite) {
      const expectedHighlight = highlightSite === undefined ? shouldHighlightTenantSite() : highlightSite !== false;
      const c = tenantCreativeImages || {};
      const complete = typeof MAP_PREVIEW_VIEW_DEFS !== 'undefined' && MAP_PREVIEW_VIEW_DEFS.every(mapPreviewIsGenerated);
      if (!complete) return false;
      return c.map_highlight_site === expectedHighlight &&
        (c.maps_persisted || c.maps_signature === mapsSignature(tenantProjectData, expectedHighlight));
    }

    function hasStoredImages() {
      const c = tenantCreativeImages || {};
      const mb = Array.isArray(c.moodboard) ? c.moodboard.filter(Boolean) : [];
      return !!c.cover && mb.length > 0 && c.images_signature === imagesSignature();
    }

    // Collect map style panel values into tenantProjectData.map_styles
    function collectMapStylePanel() {
      tenantProjectData = tenantProjectData || {};
      tenantProjectData.map_styles = {
        overview: document.getElementById('mapStyleOverview')?.value || 'auto',
        landmarks: document.getElementById('mapStyleLandmarks')?.value || 'auto',
        access: document.getElementById('mapStyleAccess')?.value || 'auto',
        catchment: document.getElementById('mapStyleCatchment')?.value || 'auto'
      };
    }

    // Fields actually read by maps_service.generate_all_map_images on the server.
    // Sending the whole project data pushed the request past ~35KB, where the shared
    // hosting proxy corrupts the body and the request fails (404/502).
    const MAP_PAYLOAD_FIELDS = [
      'catchment_areas', 'catchment_label_positions', 'catchment_map_landmarks', 'city_landmarks', 'calculate_landmark_driving',
      'draft_id', 'draftId', 'draw_compass', 'draw_inset',
      'enabled_maps', 'landmark_label_positions', 'landmark_map_items', 'landmarks_matrix', 'lat', 'latitude', 'lng', 'location',
      'location_address', 'location_detail', 'location_lat', 'location_lng', 'location_maps_link',
      'locationLat', 'locationLng', 'location_polygon', 'location_polygon_source', 'longitude',
      'access_road_label_positions', 'access_road_label_sizes', 'access_roads_data', 'location_analysis_approved', 'location_coordinates_confirmed',
      'main_roads', 'main_roads_data', 'manual_road_paths', 'map_styles', 'map_type', 'maps_link',
      'nearby_landmarks', 'nearby_landmarks_data', 'city_landmarks', 'city_landmarks_data', 'regen_seed',
      'refresh_maps',
      // The croquis coordinates are the real plot boundary, so the server needs them to
      // highlight the plot without anyone drawing anything.
      'survey_coordinates', 'city'
    ];

    // A drawn/detected boundary can carry thousands of points, which alone exceeds the
    // request size the hosting proxy can forward intact. Sampling it down keeps the
    // shape visually identical while keeping the payload small.
    const MAX_POLYGON_POINTS = 400;

    function decimatePolygon(poly) {
      const shrink = (arr) => {
        if (arr.length <= MAX_POLYGON_POINTS) return arr;
        const step = arr.length / MAX_POLYGON_POINTS;
        const out = [];
        for (let i = 0; i < MAX_POLYGON_POINTS; i++) out.push(arr[Math.floor(i * step)]);
        out.push(arr[arr.length - 1]);
        return out;
      };
      if (typeof poly === 'string') {
        const pts = poly.split(';').filter(p => p.includes(','));
        return pts.length <= MAX_POLYGON_POINTS ? poly : shrink(pts).join(';');
      }
      if (Array.isArray(poly)) return shrink(poly);
      return poly;
    }

    function slimMapProjectData(data) {
      const src = data || {};
      const slim = {};
      MAP_PAYLOAD_FIELDS.forEach(key => {
        if (src[key] !== undefined && src[key] !== null && src[key] !== '') slim[key] = src[key];
      });
      if (Array.isArray(slim.nearby_landmarks_data)) {
        slim.nearby_landmarks_data = slim.nearby_landmarks_data.slice(0, 20).map(item => {
          if (!item || typeof item !== 'object') return item;
          return Object.fromEntries(
            ['name', 'category', 'distance_km', 'distance_meters', 'duration_minutes', 'distance_text', 'lat', 'lng', 'show_on_map', 'selected', 'row_source']
              .filter(key => item[key] !== undefined && item[key] !== null && item[key] !== '')
              .map(key => [key, item[key]])
          );
        });
      }
      if (slim.location_polygon) slim.location_polygon = decimatePolygon(slim.location_polygon);
      return slim;
    }

    // Slide generation is one request per slide, so whatever rides in projectData is re-uploaded
    // for every slide. Two thirds of it was the previously generated deck and the image state,
    // which the server never reads here: images travel in `images`, the plan in `slidePlan`.
    // A drop list is used rather than a keep list so a new project field is never lost silently.
    const GENERATION_PAYLOAD_DROPPED = [
      'tenantSlidesData', 'pageDrafts', 'tenantSlidePlan', 'tenantCreativeImages', 'visual_concept',
      'land_documents_analysis', 'regulation_evidence', 'regulation_coordinates', 'coordinate_tables',
      'survey_coordinates', 'directions_table', 'parcels', 'conflicts', 'warnings',
      'extraction_diagnostics', 'document_processing', 'land_document_processing',
      'document_summary', 'source_priority', 'company_branding',
      'location_polygon', 'designerChat', 'presentation_scope'
    ];

    // Mirrors slide_engine.financial_study_has_real_input(). The financial section is rendered for
    // every project and its snapshot holds every control plus the computed projection, so a project
    // where nobody entered a figure still carries ~35KB of markup defaults and zeros — re-uploaded
    // with every single slide request, and worthless to the model.
    const FINANCIAL_REAL_INPUT_KEYS = [
      'projectCost', 'adjustedProjectCost', 'landValue', 'manualLandValue', 'equityRequired',
      'facilityAmount', 'totalBuiltUpArea', 'builtUpAreaAbove', 'basementArea', 'landArea',
      'totalRevenue', 'netProfit'
    ];

    function financialStudyHasRealInput(model) {
      const snapshot = (typeof parseFinancialStudySnapshot === 'function'
        ? parseFinancialStudySnapshot(model) : model) || {};
      const rows = snapshot.dynamicRows || {};
      const tables = snapshot.tables || {};
      const hasRow = [...Object.values(rows), ...Object.values(tables)]
        .some(set => Array.isArray(set) && set.some(row => row && typeof row === 'object'
          && Object.values(row).some(value => String(value ?? '').trim())));
      if (hasRow) return true;
      const inputs = snapshot.inputs || {};
      const projection = snapshot.projection || {};
      return FINANCIAL_REAL_INPUT_KEYS.some(key => {
        const raw = inputs[key] !== undefined ? inputs[key] : projection[key];
        return parseFloat(String(raw ?? '').replace(/[^\d.\-]/g, '')) > 0;
      });
    }

    function slimGenerationProjectData(data) {
      const src = data || {};
      const slim = {};
      Object.keys(src).forEach(key => {
        if (GENERATION_PAYLOAD_DROPPED.includes(key)) return;
        const value = src[key];
        if (value === undefined || value === null || value === '') return;
        if (key === 'land_photos_file_meta') {
          slim[key] = (Array.isArray(value) ? value : []).map(photo => ({
            id: photo?.id || '',
            imageUrl: durableImageUrl(photo?.imageUrl || photo?.url || ''),
            originalName: photo?.originalName || photo?.name || '',
            description: photo?.description || ''
          }));
          return;
        }
        if (key.endsWith('_file_meta')) return;
        if (key === 'financial_study_model') {
          if (!financialStudyHasRealInput(value)) return;
          const model = (typeof parseFinancialStudySnapshot === 'function'
            ? parseFinancialStudySnapshot(value) : value) || {};
          const report = tenantFinancialPresentationReport
            || (typeof collectFinancialStudyReport === 'function' ? collectFinancialStudyReport() : null);
          slim[key] = report ? { ...model, report } : model;
          return;
        }
        slim[key] = value;
      });
      return slim;
    }

    const DESIGNER_PROJECT_PAYLOAD_DROPPED = [
      'tenantSlidesData', 'tenantSlidePlan', 'pageDrafts', 'tenantCreativeImages', 'designerChat'
    ];

    function buildDesignerChatProjectData(data) {
      const source = data && typeof data === 'object' ? data : {};
      return Object.fromEntries(Object.entries(source).filter(
        ([key]) => !DESIGNER_PROJECT_PAYLOAD_DROPPED.includes(key)
      ));
    }

    // Generating from a name alone leaves the model nothing to work from, and the design rules
    // forbid inventing facts, so the deck comes back fabricated. The button still works.
    const GENERATION_MIN_FACTS = 6;

    function countProjectFacts(data) {
      const src = data || {};
      return Object.keys(src).filter(key => {
        if (GENERATION_PAYLOAD_DROPPED.includes(key)) return false;
        if (key === 'financial_study_model' || key === 'financial_calc_data') return false;
        if (key === 'draftId' || key === 'draft_id' || key === 'sectionStatuses') return false;
        if (key.startsWith('map_') || key.endsWith('_file_meta') || key.endsWith('_file_ids')) return false;
        const value = src[key];
        if (value === undefined || value === null || value === '' || value === false) return false;
        if (Array.isArray(value)) return value.length > 0;
        if (typeof value === 'object') return Object.keys(value).length > 0;
        return String(value).trim() !== '';
      }).length;
    }

    function slimLandAnalysisSiteContext(context) {
      const source = context || {};
      const slim = {};
      const scalarKeys = [
        'project_name', 'project_type', 'project_subtype', 'project_stage', 'location_address',
        'location_lat', 'location_lng', 'city', 'district', 'zoning_code', 'land_use'
      ];
      const shortKeys = {
        location_detail: 400,
        main_roads: 400,
        nearby_landmarks: 400,
        city_landmarks: 400
      };
      scalarKeys.forEach(key => {
        const value = source[key];
        if (value === undefined || value === null || value === '') return;
        slim[key] = typeof value === 'string' ? value.slice(0, 400) : value;
      });
      Object.entries(shortKeys).forEach(([key, limit]) => {
        const value = source[key];
        if (value === undefined || value === null || value === '') return;
        slim[key] = String(value).slice(0, limit);
      });
      if (source.location_polygon) slim.location_polygon = decimatePolygon(source.location_polygon);
      if (Array.isArray(source.nearby_landmarks_data)) {
        slim.nearby_landmarks_data = source.nearby_landmarks_data.slice(0, 20).map(item => {
          if (!item || typeof item !== 'object') return item;
          return Object.fromEntries(
            ['name', 'category', 'distance_km', 'duration_minutes', 'distance_text', 'duration_text', 'address', 'lat', 'lng']
              .filter(key => item[key] !== undefined && item[key] !== null && item[key] !== '')
              .map(key => [key, item[key]])
          );
        });
      }
      return slim;
    }

    function replaceCurrentSlideMapAssets(placeholders) {
      if (!tenantSlidesData || !tenantSlidesData.length || !placeholders) return false;
      let changed = false;
      Object.entries(placeholders).forEach(([token, url]) => {
        if (!url) return;
        const mapType = token.replace(/##/g, '').replace(/^MAP_/, '').toLowerCase();
        const oldPathPattern = new RegExp("/uploads/maps/[^\"' )]+_" + mapType + "_[^\"' )]+\\.png", "g");
        tenantSlidesData.forEach(slide => {
          if (!slide || typeof slide.html !== 'string') return;
          const before = slide.html;
          slide.html = slide.html.split(token).join(url).replace(oldPathPattern, url);
          if (slide.html !== before) changed = true;
        });
      });
      return changed;
    }

    async function ensureProjectAssets({ force = false, needImages = true, needMaps = false, includeCover = true, highlightSite } = {}) {
      if (highlightSite === undefined) highlightSite = shouldHighlightTenantSite();
      tenantCreativeImages = tenantCreativeImages || { cover: '', moodboard: [], map_placeholders: {}, map_landmarks: [] };
      if (!tenantProjectData) tenantProjectData = {};
      if (!tenantProjectData.draftId) tenantProjectData.draftId = crypto.randomUUID();
      // Collect map style panel overrides (map_styles is not in #tenantProjectForm)
      collectMapStylePanel();
      // Refresh project data if the form is present
      if (typeof collectTenantFormData === 'function' && document.getElementById('tenantProjectForm')) {
        const fresh = await collectTenantFormData();
        tenantProjectData = { ...tenantProjectData, ...fresh };
      }

      const totalSteps = (needImages ? 1 : 0) + (needMaps ? 1 : 0);
      let currentStep = 0;
      const generationPageActive = document.getElementById('tenantGenerationPage')?.classList.contains('active');
      const globalLoader = document.getElementById('globalLoader');
      const ownsGlobalLoader = totalSteps > 0 && !generationPageActive && globalLoader && globalLoader.style.display !== 'flex';
      if (ownsGlobalLoader) {
        const task = needImages && needMaps ? 'جاري تجهيز الصور والخرائط...' : (needImages ? 'جاري توليد الصور...' : 'جاري توليد خرائط الموقع...');
        showLoader('جاري تجهيز أصول العرض', task, 5);
      }
      const basePct = ownsGlobalLoader ? 5 : 60;
      const progressSpan = ownsGlobalLoader ? 87 : 30;
      const stepPct = totalSteps > 0 ? Math.round(progressSpan / totalSteps) : 0;

      function recordError(res, fallback) {
        tenantCreativeImages.last_error =
          (res && res.error_code === 'NO_API_KEY')
            ? 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env'
            : ((res && res.error) || fallback || null);
        tenantCreativeImages.last_warning = null;
      }

      if (needImages) {
        const staleImages = !hasStoredImages();
        if (!force && !staleImages) {
          console.log('[ASSETS] reusing stored cover/moodboard');
          currentStep++;
          if (document.getElementById('tenantGenerationPage')?.classList.contains('active')) {
            setGenStep('images', 'done');
          }
        } else {
          if (document.getElementById('tenantGenerationPage')?.classList.contains('active')) {
            setGenStep('prompts', 'active');
            setGenPct(22, 'صياغة أوصاف الصور بالذكاء الاصطناعي...');
          }
          updateLoaderProgress(basePct, 'جاري توليد الصور الإبداعية...');
          const count = (tenantBranding && tenantBranding.moodboard_count) || 4;
          const payload = {
            projectData: tenantProjectData,
            includeCover: includeCover !== false,
            count: count,
            referenceImage: (includeCover === false ? (tenantCreativeImages.cover || null) : null)
          };
          let res = null;
          try {
            res = await api('POST', '/api/generate-images', payload);
          } catch (e) {
            res = (e && (e.body || e.response || e.data || e.message)) || null;
          }
          if (res && res.success && res.images) {
            if (includeCover !== false) tenantCreativeImages.cover = res.images.cover || tenantCreativeImages.cover;
            tenantCreativeImages.moodboard = res.images.moodboard || tenantCreativeImages.moodboard;
            tenantCreativeImages.images_signature = imagesSignature();
            tenantCreativeImages.last_error = null;
            tenantCreativeImages.last_warning = res.warning || null;
          } else {
            recordError(res, 'تعذر الاتصال بالسيرفر أثناء توليد الصور');
          }
          currentStep++;
          updateLoaderProgress(basePct + stepPct * currentStep, 'اكتمل توليد الصور');
        }
      }

      if (needMaps) recordError(null, 'توليد الخرائط متاح لكل خريطة على حدة');

      await saveProjectAsDraft(true);
      if (ownsGlobalLoader) hideLoader();
      return tenantCreativeImages;
    }

    // The designer chat keeps its conversation for the open presentation: the turns, the compressed
    // memory of older ones, and the slides the conversation is currently about.
    let tenantDesignerMessages = [];
    let tenantDesignerChatMemory = '';
    let tenantChatFocusIndexes = [];
    const DESIGNER_CHAT_HISTORY_KEPT = 40;
    // Busy state for the designer chat progress indicator. renderTenantDesignerChat() rebuilds
    // #tenantChatMessages from tenantDesignerMessages, so a DOM-only typing indicator would be
    // wiped by any re-render (for example opening a slide edit session mid-generation).
    // Keeping progress here lets the indicator survive those re-renders.
    let tenantDesignerChatBusy = null;
    let tenantDesignerJobPollPromise = null;

    function updateDesignerChatStatus() {
      const status = document.querySelector('#tenantSlidesChat .ge-chat-panel-status');
      if (!status) return;
      if (tenantDesignerChatBusy && tenantDesignerChatBusy.message) {
        status.textContent = tenantDesignerChatBusy.message;
      } else {
        status.textContent = 'جاهز للتعديل';
      }
    }

    function setDesignerChatBusy(message, workspaceKey = designerChatWorkspaceKey()) {
      tenantDesignerChatBusy = {
        progress: 5,
        message: String(message || 'جاري تنفيذ التعديل...'),
        workspaceKey: String(workspaceKey || '')
      };
      document.querySelectorAll('[onclick*="sendTenantDesignerChat"]').forEach(button => {
        button.dataset.designerWasDisabled = String(button.disabled);
        button.disabled = true;
      });
      updateDesignerChatStatus();
    }