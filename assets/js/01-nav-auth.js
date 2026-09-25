/* 01-nav-auth.js - index.html lines 7353-8353, shared global scope, classic scripts in order */


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
        opsTab: pageId === 'tenantLandloomOpsPage' ? ((typeof llActiveTab !== 'undefined' && llActiveTab) || 'recharge') : null,
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
      tenantLandloomOpsPage: '/app/operations',
      tenantNotificationsPage: '/app/notifications',
      tenantAdminPage: '/app/admin',
      tenantCompaniesPage: '/app/admin/companies',
      tenantAdminRechargePage: '/app/admin/recharges',
      tenantAdminTicketsPage: '/app/admin/tickets',
      tenantAdminPlatformPage: '/app/admin/platform'
    };
