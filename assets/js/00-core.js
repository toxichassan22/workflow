/* 00-core.js - index.html lines 6647-7352, shared global scope, classic scripts in order */
    function toast(m, duration = 2400) {
      const t = document.getElementById('toast');
      t.innerHTML = m;
      t.classList.add('active');
      setTimeout(() => t.classList.remove('active'), duration);
    }

    // Mirrors _password_validation_error in app.py so every password form
    // enforces the same rule before the request leaves the page.
    function passwordPolicyError(password) {
      const pw = String(password || '');
      if (pw.length < 10) return 'كلمة المرور يجب أن تكون 10 أحرف على الأقل';
      if (!/[A-Za-z]/.test(pw) || !/[0-9]/.test(pw)) return 'كلمة المرور يجب أن تحتوي على حروف وأرقام';
      return '';
    }

    async function readBlobWithProgress(response, startPct, endPct) {
      const total = Number(response.headers.get('content-length') || 0);
      if (!response.body || !total) {
        updateLoaderStep(WFT('loader.preparing_file', 'جاري تجهيز الملف للتحميل...'));
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
        // Bytes actually received out of a known length: a real fraction.
        updateLoaderProgress(pct, WFT('loader.uploading_file', 'جاري تحميل الملف ({pct}%)...', { pct: pct }), true);
      }
      return new Blob(chunks, { type: response.headers.get('content-type') || 'application/octet-stream' });
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
    let tenantDraftRevision = 0;
    // The newest revision of the followed file this client already knows
    // about. The live poll compares the server's revision against it, so it
    // moves with our own saves too — otherwise a save of our own reads as
    // somebody else's change and reloads the workspace under the person who
    // just saved. See 07-project-form/07_draft_live_sync.js.
    let draftLiveSyncRevision = 0;
    // The file as it was loaded (or last saved). A save may only clear a field
    // that still had a value here AND a visible input now reports empty — a
    // field that simply fails to load is never treated as "the user erased it".
    let tenantDraftLoadedSnapshot = {};

    // Blank enough that a save would erase a stored value if it carried it.
    function isBlankDraftValue(value) {
      if (value === null || value === undefined) return true;
      if (typeof value === 'string') return !value.trim();
      if (Array.isArray(value)) return value.length === 0;
      if (typeof value === 'object') return Object.keys(value).length === 0;
      return false;
    }

    // Move the workspace revision and the poll baseline together. Every write
    // path goes through this setter, so the two can never drift apart.
    function setTenantDraftRevision(revision) {
      if (revision === null || revision === undefined || revision === '') return tenantDraftRevision;
      const value = Number(revision);
      if (!Number.isFinite(value) || value < 0) return tenantDraftRevision;
      tenantDraftRevision = value;
      if (value > draftLiveSyncRevision) draftLiveSyncRevision = value;
      return value;
    }
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

    // Stable per-slide identities for the designer agent: positions shuffle on
    // every structural edit, ids do not. Same scheme as designer_agent_ids.py
    // (`s_` + 8 hex); valid existing ids are kept and duplicates are rewritten.
    function wfNewSlideId() {
      const bytes = new Uint8Array(4);
      if (window.crypto && window.crypto.getRandomValues) {
        window.crypto.getRandomValues(bytes);
      } else {
        for (let i = 0; i < 4; i++) bytes[i] = Math.floor(Math.random() * 256);
      }
      return 's_' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    }

    function ensureSlideIds(slides) {
      if (!Array.isArray(slides)) return slides;
      const seen = new Set();
      const valid = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/.test(value);
      for (const slide of slides) {
        if (!slide || typeof slide !== 'object') continue;
        let sid = slide.id;
        if (!valid(sid) || seen.has(sid)) {
          do { sid = wfNewSlideId(); } while (seen.has(sid));
          slide.id = sid;
        }
        seen.add(sid);
      }
      return slides;
    }

    function mapsSignature(d, highlightSite = true) {
      d = d || tenantProjectData || {};
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
        highlightSite: highlightSite !== false
      });
    }

    function imagesSignature(d) {
      d = d || tenantProjectData || {};
      return JSON.stringify({
        name: d.project_name || '',
        type: d.project_type || '',
        desc: d.project_description || '',
        count: 4
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

    function mapPreviewIsVisible(view) {
      return !!mapPreviewStoredUrl(view);
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

    // Fields actually read by maps_service.generate_all_map_images on the server.
    // Sending the whole project data pushed the request past ~35KB, where the shared
    // hosting proxy corrupts the body and the request fails (404/502).
    const MAP_PAYLOAD_FIELDS = [
      'catchment_areas', 'catchment_label_positions', 'catchment_map_landmarks', 'city_landmarks', 'calculate_landmark_driving',
      'draft_id', 'draftId',
      'enabled_maps', 'landmark_label_positions', 'landmark_map_items', 'landmarks_matrix', 'lat', 'latitude', 'lng', 'location',
      'location_address', 'location_detail', 'location_lat', 'location_lng', 'location_maps_link',
      'locationLat', 'locationLng', 'location_polygon', 'location_polygon_source', 'longitude',
      'access_road_label_positions', 'access_road_label_sizes', 'access_roads_data', 'location_coordinates_confirmed',
      'main_roads', 'main_roads_data', 'manual_road_paths', 'maps_link',
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
        // No row cap: checked rows are the client's choice and all of them render. Large
        // tables grow the request, and api() chunks the wire body past 24KB anyway.
        slim.nearby_landmarks_data = slim.nearby_landmarks_data.map(item => {
          if (!item || typeof item !== 'object') return item;
          return Object.fromEntries(
            ['name', 'category', 'distance_km', 'distance_meters', 'duration_minutes', 'distance_text', 'lat', 'lng', 'show_on_map', 'selected', 'row_source', 'manual_position']
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
      'location_polygon', 'designerChat', 'presentation_scope', 'best_use_data', 'best_use_chat', 'parkingChat'
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
        if (key === 'project_language') return false;
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
      // Refresh project data if the form is present
      if (typeof collectTenantFormData === 'function' && document.getElementById('tenantProjectForm')) {
        const fresh = await collectTenantFormData();
        tenantProjectData = { ...tenantProjectData, ...fresh };
      }

      const totalSteps = (needImages ? 1 : 0) + (needMaps ? 1 : 0);
      const globalLoader = document.getElementById('globalLoader');
      const ownsGlobalLoader = totalSteps > 0 && globalLoader && globalLoader.style.display !== 'flex';
      if (ownsGlobalLoader) {
        const task = needImages && needMaps ? 'جاري تجهيز الصور والخرائط...' : (needImages ? 'جاري توليد الصور...' : 'جاري توليد خرائط الموقع...');
        showLoader('جاري تجهيز أصول العرض', task, 5);
      }

      function recordError(res, fallback) {
        tenantCreativeImages.last_error =
          (res && res.error_code === 'NO_API_KEY')
            ? 'خدمة الذكاء الاصطناعي غير متاحة حاليًا — تواصل مع الدعم الفني.'
            : ((res && res.error) || fallback || null);
        tenantCreativeImages.last_warning = null;
      }

      if (needImages) {
        const staleImages = !hasStoredImages();
        if (!force && !staleImages) {
          console.log('[ASSETS] reusing stored cover/moodboard');
        } else {
          updateLoaderStep('جاري توليد الصور الإبداعية...');
          const payload = {
            projectData: tenantProjectData,
            includeCover: includeCover !== false,
            count: 4,
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
          updateLoaderStep('اكتمل توليد الصور');
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
        message: String(message || 'جاري تنفيذ التعديل...'),
        workspaceKey: String(workspaceKey || '')
      };
      document.querySelectorAll('[onclick*="sendTenantDesignerChat"]').forEach(button => {
        button.dataset.designerWasDisabled = String(button.disabled);
        button.disabled = true;
      });
      updateDesignerChatStatus();
    }

    // Proposal 11-State Lifecycle Configuration & Helpers (t12)
    const PROPOSAL_LIFECYCLE_CONFIG = {
      'draft': { label: 'مسودة', labelEn: 'Draft', cls: 'status-draft' },
      'sections_in_progress': { label: 'قيد إعداد الأقسام', labelEn: 'Sections in progress', cls: 'status-sections' },
      'section_approval_pending': { label: 'بانتظار اعتماد قسم', labelEn: 'Section approval pending', cls: 'status-pending' },
      'rejected_for_revision': { label: 'معاد للتعديل', labelEn: 'Returned for revision', cls: 'status-revision' },
      'sections_approved': { label: 'الأقسام معتمدة', labelEn: 'Sections approved', cls: 'status-approved-sec' },
      'generation_approval_pending': { label: 'بانتظار اعتماد التوليد', labelEn: 'Generation approval pending', cls: 'status-pending' },
      'generating': { label: 'قيد التوليد', labelEn: 'Generating', cls: 'status-generating' },
      'generated_draft': { label: 'مسودة ملف مولد', labelEn: 'Generated draft', cls: 'status-generated' },
      'final_approval_pending': { label: 'بانتظار اعتماد الملف النهائي', labelEn: 'Final approval pending', cls: 'status-pending' },
      'approved': { label: 'معتمد نهائيًا', labelEn: 'Fully approved', cls: 'status-approved' },
      'archived': { label: 'مؤرشف', labelEn: 'Archived', cls: 'status-archived' },
      'pending_approval': { label: 'بانتظار التعميد', labelEn: 'Pending approval', cls: 'status-pending' },
      'submitted': { label: 'بانتظار الاعتماد', labelEn: 'Submitted', cls: 'status-pending' },
      'edited': { label: 'قيد إعداد الأقسام', labelEn: 'Edited', cls: 'status-sections' }
    };

    function getProposalStatusMeta(status) {
      const s = String(status || 'draft').trim();
      return PROPOSAL_LIFECYCLE_CONFIG[s] || { label: s || 'مسودة', labelEn: s || 'Draft', cls: 'status-draft' };
    }

    const APPROVER_PENDING_STATUSES = new Set([
      'pending_approval', 'submitted', 'section_approval_pending',
      'generation_approval_pending', 'final_approval_pending',
    ]);

    function getProposalStatusLabel(status, approverName) {
      const meta = getProposalStatusMeta(status);
      const s = String(status || 'draft').trim();
      let label = meta.label;
      if (typeof WFT === 'function') {
        label = WFT('lifecycle.' + s, meta.label);
      }
      if (approverName && APPROVER_PENDING_STATUSES.has(s)) {
        label += ' — ' + approverName;
      }
      return label;
    }

    // ── Accessibility (t63): shared modal behaviour ──────────────────────
    // Any overlay carrying data-a11y-modal gets Escape-to-close, a Tab focus
    // trap, and focus restoration. Openers call a11yModalDidOpen(modal) so the
    // first field is focused and the previously focused element is remembered.
    const A11Y_FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), ' +
      'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    let a11yPreviousFocus = null;

    function a11yVisibleModal() {
      let top = null;
      document.querySelectorAll('[data-a11y-modal]').forEach(el => {
        if (window.getComputedStyle(el).display !== 'none') top = el;
      });
      return top;
    }

    function a11yModalDidOpen(modal) {
      if (!modal) return;
      a11yPreviousFocus = document.activeElement;
      const first = modal.querySelector(A11Y_FOCUSABLE);
      if (first) {
        try { first.focus({ preventScroll: true }); } catch (e) { first.focus(); }
      }
    }

    function a11yModalDidClose() {
      const back = a11yPreviousFocus;
      a11yPreviousFocus = null;
      if (back && document.contains(back)) {
        try { back.focus({ preventScroll: true }); } catch (e) {}
      }
    }

    document.addEventListener('keydown', function (event) {
      const modal = a11yVisibleModal();
      if (event.key === 'Escape' && modal) {
        modal.style.display = 'none';
        a11yModalDidClose();
        return;
      }
      if (event.key === 'Tab' && modal) {
        const focusables = Array.prototype.slice.call(modal.querySelectorAll(A11Y_FOCUSABLE));
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (!modal.contains(document.activeElement)) {
          event.preventDefault();
          first.focus();
        } else if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
        return;
      }
      // Elements opted into button behaviour activate on Enter/Space like a
      // native button; real <button>/<a> keep their own handling, so a nested
      // control inside a clickable card still fires its own action.
      if ((event.key === 'Enter' || event.key === ' ') && event.target && event.target.closest) {
        if (event.target.closest('button, a[href], input, select, textarea, [contenteditable]')) return;
        const pseudo = event.target.closest('[role="button"]');
        if (pseudo && pseudo.tagName !== 'BUTTON' && pseudo.tagName !== 'A') {
          event.preventDefault();
          pseudo.click();
        }
      }
    });
