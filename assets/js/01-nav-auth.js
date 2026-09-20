/* 01-nav-auth.js - index.html lines 7353-8353, shared global scope, classic scripts in order */

    function updateDesignerChatBusy(progress, message) {
      if (!tenantDesignerChatBusy) return;
      const value = Math.max(0, Math.min(100, Math.round(Number(progress) || 0)));
      tenantDesignerChatBusy.progress = value;
      if (message) tenantDesignerChatBusy.message = String(message);
      const indicator = document.getElementById('tenantChatTypingIndicator');
      if (indicator) setInlineLoaderProgress(indicator, value, tenantDesignerChatBusy.message);
      updateDesignerChatStatus();
    }

    function clearDesignerChatBusy(workspaceKey = '') {
      if (workspaceKey && tenantDesignerChatBusy?.workspaceKey
        && tenantDesignerChatBusy.workspaceKey !== workspaceKey) return;
      tenantDesignerChatBusy = null;
      document.querySelectorAll('[data-designer-was-disabled]').forEach(button => {
        button.disabled = button.dataset.designerWasDisabled === 'true';
        delete button.dataset.designerWasDisabled;
      });
      const indicator = document.getElementById('tenantChatTypingIndicator');
      if (indicator) indicator.remove();
      updateDesignerChatStatus();
    }

    function restoreDesignerChatBusyIndicator() {
      if (!tenantDesignerChatBusy) return;
      const messages = document.getElementById('tenantChatMessages');
      if (!messages) return;
      if (document.getElementById('tenantChatTypingIndicator')) return;
      const hint = messages.querySelector('.tenant-hint');
      if (hint) hint.remove();
      const indicator = document.createElement('div');
      indicator.id = 'tenantChatTypingIndicator';
      indicator.className = 'tenant-chat-message assistant typing';
      showInlineLoader(indicator, tenantDesignerChatBusy.message);
      setInlineLoaderProgress(indicator, tenantDesignerChatBusy.progress, tenantDesignerChatBusy.message);
      messages.appendChild(indicator);
      messages.scrollTop = messages.scrollHeight;
    }

    function designerChatWorkspaceKey(presentationId = tenantPresentationId, projectData = tenantProjectData) {
      const tenantId = tenantUser && (tenantUser.id || tenantUser.tenantId);
      const draftId = projectData && (projectData.draftId || projectData.draft_id);
      const workspaceId = presentationId
        ? 'presentation:' + String(presentationId)
        : (draftId ? 'draft:' + String(draftId) : '');
      return tenantId && workspaceId ? String(tenantId) + '|' + workspaceId : '';
    }

    function designerChatWorkspaceSignature() {
      let serialized = '';
      try {
        serialized = JSON.stringify({ slides: tenantSlidesData, creativeImages: tenantCreativeImages });
      } catch (error) {
        serialized = String(tenantSlidesData.length);
      }
      let hash = 2166136261;
      for (let index = 0; index < serialized.length; index++) {
        hash ^= serialized.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
      }
      return serialized.length + ':' + (hash >>> 0).toString(16);
    }

    function readTenantDesignerJobs() {
      try {
        const parsed = JSON.parse(localStorage.getItem(T_DESIGNER_JOBS_KEY) || '{}');
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      } catch (error) {
        return {};
      }
    }

    function persistTenantDesignerJob(metadata) {
      if (!metadata || !metadata.jobId || !metadata.workspaceKey) return;
      const jobs = readTenantDesignerJobs();
      const cutoff = Date.now() - 24 * 60 * 60 * 1000;
      Object.keys(jobs).forEach(key => {
        if (!jobs[key] || Number(jobs[key].startedAt || 0) < cutoff) delete jobs[key];
      });
      jobs[metadata.workspaceKey] = {
        jobId: String(metadata.jobId),
        workspaceKey: String(metadata.workspaceKey),
        presentationId: metadata.presentationId || null,
        draftId: metadata.draftId || null,
        message: String(metadata.message || '').slice(0, 2000),
        target: String(metadata.target || 'auto'),
        scope: String(metadata.scope || metadata.target || 'auto'),
        indexes: Array.isArray(metadata.indexes) ? metadata.indexes.slice(0, 30) : [],
        slideIndex: Number.isInteger(Number(metadata.slideIndex)) ? Number(metadata.slideIndex) : 0,
        hadAttachment: !!metadata.hadAttachment,
        workspaceSignature: String(metadata.workspaceSignature || ''),
        startedAt: Number(metadata.startedAt || Date.now()),
        updatedAt: Number(metadata.updatedAt || Date.now()),
        status: String(metadata.status || 'queued')
      };
      try {
        localStorage.setItem(T_DESIGNER_JOBS_KEY, JSON.stringify(jobs));
      } catch (error) {
        console.warn('[DESIGNER JOB] Could not persist active job', error);
      }
    }

    function currentTenantDesignerJob() {
      const workspaceKey = designerChatWorkspaceKey();
      if (!workspaceKey) return null;
      const job = readTenantDesignerJobs()[workspaceKey];
      return job && job.workspaceKey === workspaceKey ? job : null;
    }

    function clearTenantDesignerJob(metadata) {
      if (!metadata || !metadata.workspaceKey) return;
      const jobs = readTenantDesignerJobs();
      const current = jobs[metadata.workspaceKey];
      if (current && (!metadata.jobId || String(current.jobId) === String(metadata.jobId))) {
        delete jobs[metadata.workspaceKey];
        try {
          localStorage.setItem(T_DESIGNER_JOBS_KEY, JSON.stringify(jobs));
        } catch (error) {
          console.warn('[DESIGNER JOB] Could not clear completed job', error);
        }
      }
    }

    function tenantDesignerJobMatchesWorkspace(metadata) {
      return !!metadata && metadata.workspaceKey === designerChatWorkspaceKey();
    }

    function tenantDesignerServerJobMatches(metadata, serverJob) {
      if (!metadata || !serverJob || typeof serverJob !== 'object') return true;
      const sameWhenPresent = (expected, actual) => !expected || !actual || String(expected) === String(actual);
      return sameWhenPresent(metadata.jobId, serverJob.jobId)
        && sameWhenPresent(metadata.presentationId, serverJob.presentationId)
        && sameWhenPresent(metadata.draftId, serverJob.draftId);
    }

    function tenantDesignerJobCanApply(metadata) {
      return !metadata?.workspaceSignature
        || metadata.workspaceSignature === designerChatWorkspaceSignature();
    }

    function designerChatPersistence(presentationId = tenantPresentationId) {
      return {
        presentationId: presentationId || null,
        messages: tenantDesignerMessages.slice(-DESIGNER_CHAT_HISTORY_KEPT * 2).map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content || '').slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })),
        memory: tenantDesignerChatMemory || '',
        focusIndexes: tenantChatFocusIndexes || []
      };
    }

    function restoreDesignerChat(source, expectedPresentationId = null) {
      const stored = source && typeof source === 'object' ? (source.designerChat || {}) : {};
      const storedPresentationId = stored && stored.presentationId ? String(stored.presentationId) : '';
      const presentationMatches = !expectedPresentationId || !storedPresentationId
        || storedPresentationId === String(expectedPresentationId);
      tenantDesignerMessages = Array.isArray(stored.messages)
        && presentationMatches
        ? stored.messages.filter(item => item && typeof item.content === 'string').map(item => ({
          role: item.role === 'user' ? 'user' : 'assistant',
          content: String(item.content).slice(0, 2000),
          slides: Array.isArray(item.slides) ? item.slides : []
        })).slice(-DESIGNER_CHAT_HISTORY_KEPT * 2)
        : [];
      tenantDesignerChatMemory = presentationMatches && typeof stored.memory === 'string'
        ? stored.memory.slice(0, 4000) : '';
      tenantChatFocusIndexes = presentationMatches && Array.isArray(stored.focusIndexes)
        ? stored.focusIndexes.map(Number).filter(value => Number.isInteger(value) && value >= 1).slice(0, 30)
        : [];
    }

    function resetDesignerChatForNewPresentation() {
      tenantDesignerMessages = [];
      tenantDesignerChatMemory = '';
      tenantChatFocusIndexes = [];
      tenantChatSlideScope = 'auto';
      tenantProjectData.designerChat = designerChatPersistence(null);
      renderTenantDesignerChat();
    }
    let tenantChatSlideIndex = 0;
    let tenantChatSlideScope = 'auto';
    let tenantMapPreviewState = null;
    let tenantMapPolygonPoints = [];
    let tenantMapDraftPolygonPoints = [];
    let tenantMapPolygonMode = false;
    let tenantMapPinMode = false;
    let tenantMapDraftPinHistory = [];
    let tenantRoadDrawingTarget = null;
    let tenantRoadEditMode = false;
    let tenantRoadEditDraft = null;
    let tenantRoadEditHistory = [];
    let tenantRoadEditSelectedIndex = -1;
    let tenantCatchmentEditMode = false;
    let tenantCatchmentEditDraft = null;
    let tenantCatchmentEditHistory = [];
    let tenantLandmarksEditMode = false;
    let tenantLandmarksEditDraft = null;
    let tenantLandmarksEditHistory = [];
    let tenantLandmarkPlacementTarget = null;
    let mapPlaceLinked = null;
    let tenantNearbyLandmarks = [];
    let tenantSelectedMapType = 'overview';

    function parseTenantPolygonPoints(value) {
      if (Array.isArray(value)) {
        return value.map(point => Array.isArray(point) ? point.map(Number) : [])
          .filter(point => point.length >= 2 && Number.isFinite(point[0]) && Number.isFinite(point[1]))
          .map(point => [point[0], point[1]]);
      }
      if (typeof value !== 'string') return [];
      return value.split(';').map(point => point.split(',').map(Number))
        .filter(point => point.length === 2 && point.every(Number.isFinite));
    }

    function resetTenantRoadModes() {
      tenantRoadDrawingTarget = null;
      tenantRoadEditMode = false;
      tenantRoadEditDraft = null;
      tenantRoadEditHistory = [];
      tenantRoadEditSelectedIndex = -1;
      mapPlaceLinked = null;
    }

    function resetTenantCatchmentMode() {
      tenantCatchmentEditMode = false;
      tenantCatchmentEditDraft = null;
      tenantCatchmentEditHistory = [];
      mapPlaceLinked = null;
    }

    function resetTenantLandmarksEditMode() {
      tenantLandmarksEditMode = false;
      tenantLandmarksEditDraft = null;
      tenantLandmarksEditHistory = [];
      mapPlaceLinked = null;
    }

    function invalidateTenantMapAssets() {
      tenantCreativeImages = {
        ...(tenantCreativeImages || {}),
        map_placeholders: {},
        map_zooms: {},
        map_centers: {},
        map_landmarks: [],
        map_lat: null,
        map_lng: null,
        maps_signature: null,
        maps_persisted: false,
        map_approvals: {}
      };
      tenantProjectData.location_polygon_source = 'auto';
      tenantMapPreviewState = null;
      tenantMapPolygonPoints = [];
      tenantMapDraftPolygonPoints = [];
      tenantMapPolygonMode = false;
      tenantMapPinMode = false;
      tenantMapDraftPinHistory = [];
      resetTenantRoadModes();
      resetTenantCatchmentMode();
      resetTenantLandmarksEditMode();
      tenantProjectData.location_polygon = '';
      syncTenantLocationPolygon();
      renderTenantMapPolygonOverlay();
      renderMapPreviewGallery();
      triggerAutoSaveDraft();
    }

    function getTenantToken() { return tenantToken || localStorage.getItem(T_TOKEN_KEY); }
    function setTenantToken(t) { tenantToken = t; localStorage.setItem(T_TOKEN_KEY, t); }
    function removeTenantToken() { tenantToken = null; localStorage.removeItem(T_TOKEN_KEY); }

    function setTenantUser(u) { tenantUser = u; localStorage.setItem(T_TENANT_KEY, JSON.stringify(u)); }


    function showTenantError(id, msg) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = msg;
      el.style.display = msg ? 'block' : 'none';
    }

    // The hosting proxy corrupts request bodies above ~8KB (measured on the live
    // site: plain 8-16KB POSTs get a 404 from the misparsing backend, >=20KB get
    // a 502 from Apache) and the failure can poison the connection for the next
    // request, so anything above 4KB goes gzipped to stay well clear of that window.
    async function gzipIfLarge(json, headers) {
      if (json.length < 4 * 1024 || typeof CompressionStream === 'undefined') return json;
      try {
        const stream = new Blob([json]).stream().pipeThrough(new CompressionStream('gzip'));
        const buf = await new Response(stream).arrayBuffer();
        headers['Content-Encoding'] = 'gzip';
        console.log('[API] gzipped body: ' + (json.length / 1024).toFixed(1) + 'KB -> ' + (buf.byteLength / 1024).toFixed(1) + 'KB');
        return buf;
      } catch (e) {
        return json;
      }
    }

    function handleApiResponse(res) {
      // chunkedPost can bail out with a plain {error} instead of a Response. Calling .json() on it
      // threw, and the generic network-error catch replaced the real reason with "Network error".
      if (!res || typeof res.json !== 'function') {
        return Promise.resolve(res && typeof res === 'object' ? res : { error: 'فشل الطلب' });
      }
      return res.json().catch(() => ({})).then(data => {
        data = data && typeof data === 'object' ? data : {};
        if (!res.ok && !data.error) data.error = 'فشل الطلب (HTTP ' + res.status + ')';
        if (res.status === 401) {
          removeTenantToken();
          showAuthPage();
        }
        return data;
      });
    }

    // The hosting edge corrupts request bodies above ~40KB: the app actually
    // receives and answers them, but the browser gets a fabricated 404/502.
    // So large bodies are uploaded in small chunk envelopes (POST /api/body-chunk)
    // and the real endpoint is then called with a tiny reassembly reference.
    const CHUNK_WIRE_LIMIT = 24 * 1024;
    const CHUNK_PART_BYTES = 12 * 1024;

    // The server stores each chunk as its own {idx}.part file, so arrival order does not matter.
    // Sending them one at a time meant a few hundred sequential round trips for a draft carrying
    // slides and images, which is most of why saving felt like nothing was happening.
    const CHUNK_CONCURRENCY = 6;

    async function chunkedPost(method, path, wire, isGzip, headers, signal, onProgress) {
      const buf = typeof wire === 'string' ? new TextEncoder().encode(wire) : new Uint8Array(wire);
      const id = crypto.randomUUID();
      const total = Math.ceil(buf.length / CHUNK_PART_BYTES);
      const chunkHeaders = Object.assign({}, headers);
      delete chunkHeaders['Content-Encoding'];
      if (total > 1024) {
        // The server refuses more than 1024 parts; say so rather than failing on chunk 1025.
        return { error: 'حجم البيانات أكبر من الحد المسموح للحفظ (' + (buf.length / 1048576).toFixed(1) + ' م.ب)' };
      }

      let sent = 0;
      let failure = null;
      const sendChunk = async index => {
        const part = buf.subarray(index * CHUNK_PART_BYTES, (index + 1) * CHUNK_PART_BYTES);
        let bin = '';
        for (let j = 0; j < part.length; j++) bin += String.fromCharCode(part[j]);
        const res = await fetch('/api/body-chunk', {
          method: 'POST',
          headers: chunkHeaders,
          body: JSON.stringify({ id, idx: index, total, data: btoa(bin) }),
          signal,
        });
        if (!res.ok) throw new Error('Chunk upload failed (' + res.status + ')');
        sent += 1;
        if (onProgress) onProgress(sent, total);
      };

      let next = 0;
      const workers = Array.from({ length: Math.min(CHUNK_CONCURRENCY, total) }, async () => {
        while (next < total && !failure) {
          const index = next++;
          try {
            await sendChunk(index);
          } catch (error) {
            failure = error;
          }
        }
      });
      await Promise.all(workers);
      if (failure) return { error: failure.message || 'Chunk upload failed' };
      console.log('[API] chunked body: ' + (buf.length / 1024).toFixed(1) + 'KB in ' + total + ' chunks');
      return fetch(path, {
        method,
        headers: chunkHeaders,
        body: JSON.stringify({ __chunked_body: { id, total, gzip: isGzip } }),
        signal,
      });
    }

    async function api(method, path, body, isFile, requestOptions = {}) {
      const token = getTenantToken();
      const headers = {};
      if (token) headers['Authorization'] = 'Bearer ' + token;
      if (!isFile && body && typeof body !== 'undefined') headers['Content-Type'] = 'application/json';
      const opts = { method, headers, signal: requestOptions.signal };
      if (body && !isFile) {
        const wire = await gzipIfLarge(JSON.stringify(body), headers);
        const isGzip = headers['Content-Encoding'] === 'gzip';
        const wireSize = typeof wire === 'string' ? wire.length : wire.byteLength;
        if (wireSize > CHUNK_WIRE_LIMIT) {
          return chunkedPost(method, path, wire, isGzip, headers, requestOptions.signal,
            requestOptions.onProgress)
            .then(handleApiResponse)
            .catch(e => ({ error: 'Network error: ' + e.message }));
        }
        opts.body = wire;
      } else if (body) {
        opts.body = body;
      }
      return fetch(path, opts).then(handleApiResponse).catch(e => ({ error: 'Network error: ' + e.message }));
    }

    async function apiWithTimeout(method, path, body, timeoutMs = 75000, timeoutMessage = 'انتهت مهلة الطلب؛ أعد المحاولة لاحقًا.', requestOptions = {}) {
      const controller = new AbortController();
      let timer;
      const timeoutResponse = new Promise(resolve => {
        timer = setTimeout(() => {
          controller.abort();
          resolve({
            success: false,
            error: timeoutMessage,
            error_code: 'CLIENT_REQUEST_TIMEOUT'
          });
        }, timeoutMs);
      });
      try {
        return await Promise.race([
          api(method, path, body, false, { ...requestOptions, signal: controller.signal }),
          timeoutResponse
        ]);
      } finally {
        clearTimeout(timer);
      }
    }

    // The planner reads every section of the project, so it can take minutes. The server queues it
    // and answers with a job id, because the hosting proxy drops a request held open that long and
    // the browser then reported a timeout for a plan the server had actually produced.
    async function pollTenantSlidePlanJob(jobId, onProgress) {
      const started = Date.now();
      let res = null;
      while (Date.now() - started < 2 * 60 * 1000) {
        await new Promise(resolve => setTimeout(resolve, 2500));
        res = await apiWithTimeout('GET', '/api/slide-plan/jobs/' + encodeURIComponent(jobId), null,
          30000);
        const status = String(res && res.status || '');
        if (typeof onProgress === 'function') onProgress(res);
        if (status === 'completed' || status === 'failed' || (res && res.plan)) break;
        if (!res || res.failureReason === 'job_not_found') break;
      }
      if (res && !res.plan && !res.error) {
        res = { success: false, error: 'تعذر إعداد خطة الشرائح في الوقت المتاح', error_code: 'PLAN_JOB_TIMEOUT' };
      }
      return res;
    }

    // A slide can take longer than the shared hosting proxy allows. Queueing the request keeps the
    // browser connected only to short status calls and guarantees that a timeout cannot start the
    // same paid AI generation three more times. While the job runs, the worker publishes the
    // streamed text as `partial`, so the caller can paint the slide live; the completed slide
    // below is still the same finalized response, never the preview.
    async function requestTenantSlideGeneration(payload, onPartial) {
      const queued = await apiWithTimeout(
        'POST', '/api/generate-slide-single-job', payload, 30000,
        'تعذر تسجيل مهمة توليد الشريحة؛ لم يبدأ استهلاك جديد.'
      );
      if (!queued?.jobId) return queued;

      const started = Date.now();
      const maxWaitMs = 10 * 60 * 1000;
      let lastPartial = '';
      while (Date.now() - started < maxWaitMs) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const result = await apiWithTimeout(
          'GET', '/api/generate-slide-single/jobs/' + encodeURIComponent(queued.jobId), null,
          30000, 'انتهت مهلة متابعة مهمة توليد الشريحة.'
        );
        if (result && typeof result.partial === 'string' && result.partial && result.partial !== lastPartial) {
          lastPartial = result.partial;
          if (typeof onPartial === 'function') {
            try { onPartial(result.partial); } catch (previewError) { /* preview-only */ }
          }
        }
        if (result?.status === 'completed' || (result?.success && result?.slide)) return result;
        if (result?.status === 'failed' || result?.status === 'not_found' || result?.error_code) return result;
        if (result?.error && !['queued', 'running'].includes(result?.status)) return result;
      }
      return {
        success: false,
        error: 'انتهت مهلة توليد الشريحة. يمكن استكمال العرض من آخر شريحة محفوظة.',
        error_code: 'SLIDE_JOB_TIMEOUT'
      };
    }

    const TENANT_SECTION_REGENERATION_TARGETS = [
      { key: 'overview', label: 'نبذة عن المشروع', pattern: /نبذة عن المشروع|نظرة عامة|فكرة المشروع/i },
      { key: 'components', label: 'مكونات المشروع', pattern: /مكونات المشروع|المكونات|الوحدات والمساحات/i },
      { key: 'land', label: 'تحليل الأرض', pattern: /تحليل الأرض|الأرض والكروكي|الكروكي|حدود الأرض/i },
      { key: 'location', label: 'تحليل الموقع الجغرافي', pattern: /تحليل الموقع الجغرافي|تحليل الموقع|الموقع الجغرافي/i },
      { key: 'market', label: 'تحليل السوق', pattern: /تحليل السوق|دراسة السوق|السوق/i },
      { key: 'timeline', label: 'الجدول الزمني', pattern: /الجدول الزمني|الخطة الزمنية|مراحل التطوير/i },
      { key: 'financial', label: 'الدراسة المالية', pattern: /الدراسة المالية|التحليل المالي|الجدوى المالية/i },
      { key: 'swot_risks', label: 'تحليل SWOT وتحليل المخاطر', pattern: /تحليل\s*swot|تحليل المخاطر|المخاطر/i },
      { key: 'team', label: 'فريق العمل', pattern: /فريق العمل|فريق التطوير/i },
      { key: 'visual_concept', label: 'التصور البصري', pattern: /قسم\s+التصورات(?:\s+(?:كامل|بالكامل))?|التصورات البصرية|التصور البصري/i },
      { key: 'plans', label: 'المخططات', pattern: /المخططات|المخطط|المساقط|المخطط المعماري/i },
      { key: 'exterior', label: 'التصورات الخارجية', pattern: /التصورات الخارجية|التصور الخارجي|الواجهات/i },
      { key: 'interior', label: 'التصورات الداخلية', pattern: /التصورات الداخلية|التصور الداخلي|التصميم الداخلي/i },
      { key: 'executive_summary', label: 'الملخص التنفيذي', pattern: /الملخص التنفيذي/i }
    ];

    function normalizeTenantSectionCommandText(value) {
      return String(value || '').trim()
        .replace(/[إأآ]/g, 'ا')
        .replace(/ة/g, 'ه')
        .replace(/ى/g, 'ي')
        .replace(/\s+/g, ' ');
    }

    function detectTenantSectionRegenerationRequest(message) {
      const text = String(message || '').trim();
      const normalized = normalizeTenantSectionCommandText(text);
      const isSectionRebuildCommand =
        /(?:اعاده|اعد)\s*(?:توليد|انشاء|بناء|تصميم|تنسيق)/i.test(normalized) ||
        /صمم\s*(?:قسم|القسم)/i.test(normalized);
      if (!text || !isSectionRebuildCommand) return null;
      if (!/(?:قسم|القسم|كامل|بالكامل)/i.test(text)) return null;
      return TENANT_SECTION_REGENERATION_TARGETS.find(item => {
        const normalizedPattern = new RegExp(item.pattern.source.replace(/ة/g, 'ه'), item.pattern.flags);
        return item.pattern.test(text) || normalizedPattern.test(normalized);
      }) || null;
    }

    function tenantSlideMatchesSection(slide, index, sectionKey) {
      const candidates = [slide, tenantSlidePlan?.slides?.[index]].filter(Boolean);
      return candidates.some(candidate => {
        const source = String(candidate.content_source || candidate.contentSource || '').toLowerCase();
        const title = String(candidate.title || '').toLowerCase();
        const type = String(candidate.type || '').toLowerCase();
        if (sectionKey === 'visual_concept') {
          const explicit = String(candidate.section_key || candidate.sectionKey || candidate.section || '').trim();
          return ['plans', 'exterior', 'interior'].includes(explicit) ||
            ['plans', 'exterior', 'interior'].includes(tenantSlideSectionKey(candidate, ''));
        }
        if (sectionKey === 'financial' && (
          source.startsWith('financial_') || source.startsWith('financial:') ||
          source.startsWith('financial_report:') || source.startsWith('financial_summary:') ||
          /الدراسة المالية|التحليل المالي|الجدوى المالية|التدفقات النقدية|مؤشرات العائد|التكاليف والاستثمار|financial|cash ?flow|roi|irr/i.test(title)
        )) return true;
        if (sectionKey === 'location' && (
          type.startsWith('map_') || type === 'site_specs' ||
          ['location_polygon', 'main_roads', 'catchment_areas', 'nearby_landmarks', 'site_analysis', 'location_detail'].includes(source)
        )) return true;
        return tenantSlideSectionKey(candidate, '') === sectionKey;
      });
    }

    const TENANT_SECTION_PLANNER_KEYS = {
      overview: 'basic',
      components: 'basic',
      land: 'land_croquis',
      location: 'location',
      market: 'section-market-study',
      swot_risks: 'section-market-study',
      timeline: 'section-timeline',
      financial: 'section-financial-calc',
      team: 'section-team',
      visual_concept: 'section-visual-concept',
      plans: 'section-visual-concept',
      exterior: 'section-visual-concept',
      interior: 'section-visual-concept',
      executive_summary: 'section-executive-content'
    };

    function tenantSectionPlanMatchesSection(slide, sectionKey) {
      if (!slide || ['cover', 'index', 'closing'].includes(String(slide.type || '').toLowerCase())) return false;
      const explicit = String(slide.section_key || slide.sectionKey || slide.section || '').trim();
      if (sectionKey === 'visual_concept') {
        return ['plans', 'exterior', 'interior'].includes(explicit) ||
          ['plans', 'exterior', 'interior'].includes(tenantSlideSectionKey(slide, ''));
      }
      if (String(slide.type || '').toLowerCase() === 'section_divider') return false;
      return explicit === sectionKey || tenantSlideSectionKey(slide, '') === sectionKey;
    }

    async function requestTenantSectionSlidePlans(sectionKey) {
      const plannerKey = TENANT_SECTION_PLANNER_KEYS[sectionKey];
      if (!plannerKey) throw new Error('القسم غير مدعوم لإعادة التخطيط');
      const response = await requestTenantSlidePlan(tenantProjectData, job => {
        setLiveGenBanner(true, 'إعادة تخطيط قسم ' + (TENANT_PRESENTATION_SECTION_TITLES[sectionKey] || sectionKey),
          (job && job.message) || 'تحليل الصور والبيانات وتحديد عدد الشرائح المناسب', 12);
      }, plannerKey);
      if (!response?.success || !response.plan) {
        throw new Error(response?.error || 'تعذر إعداد خطة القسم الجديدة');
      }
      const slides = (response.plan.slides || []).filter(slide => tenantSectionPlanMatchesSection(slide, sectionKey));
      if (!slides.length) throw new Error('لم تنتج خطة القسم شرائح قابلة للتوليد؛ لم يتم تغيير العرض.');
      return { plan: response.plan, slides };
    }

    function buildTenantSlideRegenerationSnapshot(index) {
      const slideIndex = Number(index);
      const current = Array.isArray(tenantSlidesData) ? tenantSlidesData[slideIndex] : null;
      if (!current || slideIndex < 0 || slideIndex >= tenantSlidesData.length) return null;
      const planned = tenantSlidePlan?.slides?.[slideIndex] || {};
      const snapshot = { ...planned };
      ['title', 'type', 'section_key', 'content_source', 'source_table', 'design_style', 'designStyle',
        'chart_type', 'image_tokens', 'bullets', 'metrics', 'media_only'].forEach(key => {
        const missing = snapshot[key] === undefined || snapshot[key] === null ||
          (Array.isArray(snapshot[key]) && !snapshot[key].length && Array.isArray(current[key]) && current[key].length);
        if (missing && current[key] !== undefined) snapshot[key] = current[key];
      });
      snapshot.title = snapshot.title || current.title || ('شريحة ' + (slideIndex + 1));
      snapshot.type = snapshot.type || current.type || 'content';
      snapshot.design_style = snapshot.design_style || snapshot.designStyle || current.designStyle || 'cards';
      return { slideIndex, current, snapshot };
    }

    async function generateTenantSlideFromSnapshot(snapshot, slideIndex, totalSlides, generationImages, current = {}) {
      if (!snapshot) throw new Error('خطة الشريحة غير موجودة');
      const payload = {
        projectData: slimGenerationProjectData(tenantProjectData),
        slidePlan: { slides: [snapshot] },
        images: generationImages,
        slideIndex: 0,
        _slideNum: Number(slideIndex) + 1,
        _totalSlides: Number(totalSlides) || 1
      };
      if (tenantPresentationId) payload.presentationId = tenantPresentationId;

      const data = await requestTenantSlideGeneration(payload);
      if (!data?.success || !data.slide?.html || !containsSlideRoot(data.slide.html)) {
        throw new Error(data?.error || 'تعذر إعادة توليد الشريحة');
      }

      const generatedType = data.slide.type || snapshot.type || current.type || 'content';
      const renderedHtml = processSlideHtmlClient(data.slide.html, generatedType);
      if (!renderedHtml || !containsSlideRoot(renderedHtml)) {
        throw new Error('استجابة الشريحة الجديدة غير مكتملة');
      }
      return {
        ...current,
        title: data.slide.title || snapshot.title || current.title,
        type: generatedType,
        html: renderedHtml,
        section_key: data.slide.sectionKey || snapshot.section_key || snapshot.sectionKey || current.section_key || '',
        content_source: data.slide.contentSource || snapshot.content_source || snapshot.contentSource || current.content_source || '',
        source_table: data.slide.sourceTable || snapshot.source_table || snapshot.sourceTable || current.source_table || '',
        index_entries: data.slide.indexEntries || snapshot.index_entries || snapshot.indexEntries || current.index_entries || [],
        designStyle: data.slide.designStyle || snapshot.design_style || snapshot.designStyle || current.designStyle || 'cards',
        bullets: snapshot.bullets || current.bullets || [],
        metrics: snapshot.metrics || current.metrics || []
      };
    }

    async function generateTenantSlideReplacement(index, generationImages) {
      const context = buildTenantSlideRegenerationSnapshot(index);
      if (!context) throw new Error('الشريحة غير موجودة');
      const { slideIndex, current, snapshot } = context;
      return generateTenantSlideFromSnapshot(snapshot, slideIndex, tenantSlidesData.length, generationImages, current);
    }

    async function regenerateTenantSlide(index) {
      if (!hasPermission('create_presentation')) return;
      if (isGeneratingTenantSlides || isRegeneratingTenantSlide) {
        toast('يوجد توليد جارٍ حاليًا');
        return;
      }
      if (hasResumableTenantSlideGeneration()) {
        toast('استكمل التوليد المتوقف قبل إعادة توليد شريحة');
        return;
      }

      const context = buildTenantSlideRegenerationSnapshot(index);
      if (!context) {
        toast('الشريحة غير موجودة');
        return;
      }
      if (!confirm('سيتم إعادة توليد الشريحة «' + context.snapshot.title + '» فقط، مع إبقاء باقي الشرائح كما هي. هل تريد المتابعة؟')) return;

      checkpointPresentationUndo();
      isRegeneratingTenantSlide = true;
      updatePresentationUndoButtons();
      renderTenantSlidesSidebar();
      setLiveGenBanner(true, 'إعادة توليد الشريحة ' + (context.slideIndex + 1) + ' من ' + tenantSlidesData.length,
        'لن تتأثر بقية الشرائح', 35);
      try {
        const previousHtml = tenantSlidesData[context.slideIndex] ? tenantSlidesData[context.slideIndex].html : '';
        tenantSlidesData[context.slideIndex] = await generateTenantSlideReplacement(
          context.slideIndex, buildPresentationGenerationImages());
        tenantSlidesData[context.slideIndex].html = copyWatermarkMarkup(
          previousHtml, tenantSlidesData[context.slideIndex].html);
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        renumberTenantSlides();
        renderTenantSlides();
        selectTenantSlide(context.slideIndex);
        triggerAutoSaveDraft();
        toast('تم إعادة توليد الشريحة ' + (context.slideIndex + 1) + ' فقط');
      } catch (error) {
        console.error('[SLIDE REGENERATE]', error);
        toast(error?.message || 'تعذر إعادة توليد الشريحة');
      } finally {
        isRegeneratingTenantSlide = false;
        checkpointPresentationUndo();
        renderTenantSlidesSidebar();
        setLiveGenBanner(false);
      }
    }

    async function regenerateTenantSection(sectionKey, sectionLabel) {
      if (!hasPermission('create_presentation')) return false;
      if (isGeneratingTenantSlides || isRegeneratingTenantSlide) {
        toast('يوجد توليد جارٍ حاليًا');
        return false;
      }
      if (tenantSlidePlanRequest) {
        toast('يوجد إعداد خطة جارٍ حاليًا');
        return false;
      }
      if (hasResumableTenantSlideGeneration()) {
        toast('استكمل التوليد المتوقف قبل إعادة توليد قسم');
        return false;
      }

      renumberTenantSlides();
      const targetIndexes = tenantSlidesData
        .map((slide, index) => ({ slide, index }))
        .filter(item => sectionKey === 'visual_concept'
          || !['cover', 'index', 'closing', 'section_divider'].includes(String(item.slide?.type || '').toLowerCase()))
        .filter(item => tenantSlideMatchesSection(item.slide, item.index, sectionKey))
        .map(item => item.index);
      if (!targetIndexes.length) {
        toast('لا توجد شرائح لهذا القسم داخل العرض');
        return false;
      }
      const targetNumbers = targetIndexes.map(index => index + 1).join('، ');
      if (sectionKey === 'financial' && typeof validateFinancialStudyBeforeProceed === 'function'
        && !(await validateFinancialStudyBeforeProceed())) return false;
      if (!confirm('سيتم إعادة تخطيط وتوليد قسم «' + sectionLabel + '» من صوره وبياناته الحالية. قد يزيد أو يقل عدد شرائحه، مع إبقاء باقي العرض كما هو. هل تريد المتابعة؟')) return false;

      const previousSlides = tenantSlidesData.slice();
      const previousPlan = tenantSlidePlan;
      const previousProjectData = { ...tenantProjectData };
      checkpointPresentationUndo();
      isRegeneratingTenantSlide = true;
      updatePresentationUndoButtons();
      renderTenantSlidesSidebar();
      try {
        await repairVisualConceptStoredImages();
        persistVisualConceptDraftState();
        const generationImages = buildPresentationGenerationImages();
        const sectionPlan = await requestTenantSectionSlidePlans(sectionKey);
        const plannedSlides = sectionPlan.slides;
        const firstIndex = targetIndexes[0];
        const projectedTotal = tenantSlidesData.length - targetIndexes.length + plannedSlides.length;
        const replacements = [];
        for (let position = 0; position < plannedSlides.length; position += 1) {
          const planSlide = { ...plannedSlides[position] };
          setLiveGenBanner(true, 'إعادة توليد قسم ' + sectionLabel,
            'الشريحة ' + (position + 1) + ' من ' + plannedSlides.length, 20 + Math.round((position / plannedSlides.length) * 65));
          replacements.push({
            slide: await generateTenantSlideFromSnapshot(
              planSlide, firstIndex + position, projectedTotal, generationImages, {})
          });
          // Regenerated section slides start without a watermark; the user
          // enables it per slide from the edit toolbar.
        }

        const targetSet = new Set(targetIndexes);
        const nextSlides = tenantSlidesData.filter((slide, index) => !targetSet.has(index));
        nextSlides.splice(firstIndex, 0, ...replacements.map(item => item.slide));
        tenantSlidesData = nextSlides;
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        renumberTenantSlides();
        renderTenantSlides();
        selectTenantSlide(Math.min(firstIndex, tenantSlidesData.length - 1));
        triggerAutoSaveDraft();
        tenantDesignerMessages.push({
          role: 'assistant',
          content: 'تم إعادة تخطيط وتوليد قسم ' + sectionLabel + ' فقط (' + plannedSlides.length + ' شرائح بدلًا من ' + targetIndexes.length + ')، مع إبقاء باقي العرض كما هو.',
          slides: Array.from({ length: plannedSlides.length }, (_, offset) => firstIndex + offset + 1)
        });
        renderTenantDesignerChat();
        return true;
      } catch (error) {
        console.error('[SECTION REGENERATE]', error);
        tenantSlidesData = previousSlides;
        tenantSlidePlan = previousPlan;
        tenantProjectData = previousProjectData;
        tenantProjectData.tenantSlidesData = tenantSlidesData;
        renderTenantSlides();
        tenantDesignerMessages.push({
          role: 'assistant',
          content: error?.message || 'تعذر إعادة توليد القسم؛ لم يتم استبدال الشرائح القديمة.',
          slides: targetIndexes.map(index => index + 1)
        });
        renderTenantDesignerChat();
        return false;
      } finally {
        isRegeneratingTenantSlide = false;
        checkpointPresentationUndo();
        renderTenantSlidesSidebar();
        setLiveGenBanner(false);
      }
    }

    function buildPresentationGenerationImages() {
      const externalSlots = VISUAL_CONCEPT_EXTERNAL_SLOTS.slice(1);
      const visualMoodboard = externalSlots.map(item => tenantVisualConceptState?.slots?.[item.id]?.approvedImageUrl || tenantVisualConceptState?.slots?.[item.id]?.imageUrl || '');
      const fallbackMoodboard = Array.isArray(tenantCreativeImages?.moodboard) ? tenantCreativeImages.moodboard : [];
      const moodboard = visualMoodboard.some(Boolean)
        ? visualMoodboard
        : fallbackMoodboard.map((image, index) => image || tempMoodboardImages[index] || '');
      const moodboardMeta = externalSlots.map((item, index) => {
        const slot = tenantVisualConceptState?.slots?.[item.id] || {};
        return {
          label: slot.label || visualConceptDefaultSlotLabel(item.id),
          caption: slot.caption || '',
          url: moodboard[index] || ''
        };
      });
      const interiorComponents = visualConceptInteriorComponents().map((component, componentIndex) => {
        const images = [];
        for (let view = 1; view <= VISUAL_CONCEPT_MAX_INTERIOR_IMAGES; view += 1) {
          const slot = tenantVisualConceptState?.slots?.[visualConceptInteriorSlotId(component.id, view)];
          const url = slot?.approvedImageUrl || slot?.imageUrl || '';
          if (url) images.push({
            viewIndex: view,
            url,
            label: slot?.label || component.name,
            caption: slot?.caption || ''
          });
        }
        return {
          id: component.id,
          index: componentIndex + 1,
          name: component.name,
          useType: component.useType,
          builtArea: component.builtArea,
          images
        };
      }).filter(component => component.images.length);
      const interior = interiorComponents.flatMap(component => component.images.map(image => image.url));
      const plansState = typeof visualConceptPlans === 'function' ? visualConceptPlans() : [];
      const plans = plansState.map(plan => plan?.imageUrl || '').filter(Boolean);
      const planMeta = plansState.filter(plan => plan?.imageUrl).map(plan => ({
        title: plan.title || plan.fileName || '',
        description: plan.description || '',
        url: plan.imageUrl
      }));
      const landPhotos = (Array.isArray(tenantProjectData?.land_photos_file_meta)
        ? tenantProjectData.land_photos_file_meta : []).map(photo => ({
          id: photo?.id || '',
          url: durableImageUrl(photo?.imageUrl || photo?.url || (photo?.path ? '/' + String(photo.path).replace(/^\/+/, '') : '')),
          name: photo?.originalName || photo?.name || '',
          description: photo?.description || ''
        }));
      return {
        ...(tenantCreativeImages || {}),
        cover: tenantVisualConceptState?.slots?.cover?.approvedImageUrl || tenantVisualConceptState?.slots?.cover?.imageUrl || tenantCreativeImages?.cover || tempCoverImage || '',
        moodboard,
        moodboard_meta: moodboardMeta,
        interior_components: interiorComponents,
        interior,
        plans,
        plan_meta: planMeta,
        land_photos: landPhotos
      };
    }

    function buildPresentationPlanAssets() {
      const assets = buildPresentationGenerationImages();
      return {
        cover: assets.cover ? 'available' : '',
        moodboard: (assets.moodboard || []).map(image => image ? 'available' : ''),
        moodboard_meta: (assets.moodboard_meta || []).map(item => ({
          label: item.label || '', caption: item.caption || ''
        })),
        interior_components: (assets.interior_components || []).map(component => ({
          ...component,
          images: (component.images || []).map(image => ({ ...image, url: image.url ? 'available' : '' }))
        })),
        plans: (assets.plans || []).map(image => image ? 'available' : ''),
        plan_meta: (assets.plan_meta || []).map(item => ({
          title: item.title || '', description: item.description || ''
        })),
        land_photos: assets.land_photos || [],
        // The planner must know that approved maps are real assets.  Omitting
        // this field made it instruct the model that every map was unavailable,
        // even though the later slide request had the map images in memory.
        map_placeholders: assets.map_placeholders || {},
        map_zooms: assets.map_zooms || {},
        map_centers: assets.map_centers || {}
      };
    }

    let tenantSlidePlanRequest = null;
    function requestTenantSlidePlan(projectData, onProgress, sectionKey = '') {
      if (tenantSlidePlanRequest) return tenantSlidePlanRequest;
      const payload = typeof slimGenerationProjectData === 'function'
        ? slimGenerationProjectData(projectData) : projectData;
      const requestBody = {
        images: buildPresentationPlanAssets()
      };
      if (tenantPresentationId) requestBody.presentationId = tenantPresentationId;
      if (tenantDraftDirty || !tenantPresentationId) {
        // A dirty workspace is authoritative for this turn. The saved presentation is only a
        // fallback before the first local change, so refresh can still discard unsaved work.
        requestBody.projectData = payload;
      }
      if (sectionKey) requestBody.sectionKey = sectionKey;
      tenantSlidePlanRequest = apiWithTimeout('POST', '/api/slide-plan', requestBody)
        .then(async res => {
          if (!(res && res.jobId && !res.plan)) return res;
          const completed = await pollTenantSlidePlanJob(res.jobId, onProgress);
          if (completed?.plan || !res.fallbackPlan) return completed;
          return {
            success: true,
            plan: { ...res.fallbackPlan, source: 'fallback', source_error: completed?.error || 'planner_timeout' },
            planSource: 'fallback'
          };
        })
        .finally(() => { tenantSlidePlanRequest = null; });
      return tenantSlidePlanRequest;
    }

    const TENANT_NAVIGATION_CONTEXT_PAGES = new Set([
      'tenantProjectPage',
      'tenantVisualConceptPage',
      'tenantSlidesPage',
      'tenantGenerationPage'
    ]);

    function getTenantNavigationState() {
      try {
        const raw = localStorage.getItem(T_NAVIGATION_KEY);
        const state = raw ? JSON.parse(raw) : null;
        return state && state.pageId ? state : null;
      } catch (e) {
        return null;
      }
    }

    function buildTenantNavigationState(pageId, overrides = {}) {
      const hasProjectContext = TENANT_NAVIGATION_CONTEXT_PAGES.has(pageId);
      return {
        pageId,
        tenantId: tenantUser && (tenantUser.id || tenantUser.tenantId) || null,
        mode: hasProjectContext ? (tenantProjectMode || (tenantPresentationId ? 'presentation' : 'draft')) : null,
        presentationId: hasProjectContext ? (tenantPresentationId || null) : null,
        draftId: hasProjectContext && tenantProjectData
          ? (tenantProjectData.draftId || null)
          : pageId === 'tenantProjectPresentationsPage'
            ? (overrides.draftId || currentProjectPresentationsDraftId() || null) : null,
        activeSection: hasProjectContext ? (tenantActiveProjectSection || null) : null,
        visualConceptView: pageId === 'tenantVisualConceptPage' ? (overrides.visualConceptView || document.querySelector('#tenantVisualConceptPage [data-visual-concept-view]:not([hidden])')?.dataset.visualConceptView || 'home') : null,
        opsTab: pageId === 'tenantOmranOpsPage' ? ((typeof omActiveTab !== 'undefined' && omActiveTab) || 'tasks') : null,
        railTab: localStorage.getItem('tgrTab') || 'nav',
        ...overrides
      };
    }

    function saveTenantNavigationState(pageId, overrides = {}) {
      if (!pageId || pageId === 'tenantAuthPage') return;
      const state = buildTenantNavigationState(pageId, overrides);
      try {
        localStorage.setItem(T_NAVIGATION_KEY, JSON.stringify(state));
      } catch (e) {
        console.warn('[NAVIGATION] Could not save state:', e);
      }
      return state;
    }

    function clearTenantNavigationState() {
      localStorage.removeItem(T_NAVIGATION_KEY);
    }

    // Auth UI

    function showAuthPage() {
      const app = document.querySelector('.app');
      if (app) app.style.display = 'none';
      document.getElementById('tenantAppPage').classList.remove('active');
      document.getElementById('tenantAuthPage').classList.add('active');
      // The login screen owns the bare domain: it never carries an /app/...
      // path, so a logged-out deep link or an expired session lands on '/'
      // instead of showing the login card under a workspace address.
      if (window.location.pathname !== '/') {
        window.history.replaceState({}, '', '/');
      }
    }

    function showTenantApp() {
      const app = document.querySelector('.app');
      if (app) app.style.display = 'none';
      document.getElementById('tenantAuthPage').classList.remove('active');
      document.getElementById('tenantAppPage').classList.add('active');
    }

    const TENANT_PAGE_ROUTES = {
      tenantDashboardPage: '/app/dashboard',
      tenantProjectPage: '/app/projects/new',
      tenantProjectPresentationsPage: '/app/projects/presentations',
      tenantVisualConceptPage: '/app/projects/visual-concept',
      tenantGenerationPage: '/app/projects/generation',
      tenantSlidesPage: '/app/presentations/current',
      tenantPresentationsPage: '/app/presentations',
      tenantSettingsPage: '/app/settings',
      tenantTeamPage: '/app/settings/team',
      tenantFieldsPage: '/app/settings/fields',
      tenantUsersPage: '/app/settings/users',
      tenantTrainingPage: '/app/settings/training',
      tenantAIRulesPage: '/app/settings/ai-rules',
      tenantApprovalsPage: '/app/approvals',
      tenantOmranOpsPage: '/app/operations',
      tenantNotificationsPage: '/app/notifications',
      tenantAdminPage: '/app/admin',
      tenantCompaniesPage: '/app/admin/companies',
      tenantAdminRechargePage: '/app/admin/recharges',
      tenantAdminTicketsPage: '/app/admin/tickets',
      tenantAdminPlatformPage: '/app/admin/platform',
      tenantFinlabPage: '/app/admin/finlab'
    };