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
    const CHUNK_CONCURRENCY = 12;

    async function chunkedPost(method, path, wire, isGzip, headers, signal, onProgress) {
      const buf = typeof wire === 'string' ? new TextEncoder().encode(wire) : new Uint8Array(wire);
      const id = crypto.randomUUID();
      const total = Math.ceil(buf.length / CHUNK_PART_BYTES);
      const chunkHeaders = Object.assign({}, headers);
      delete chunkHeaders['Content-Encoding'];
      if (total > 1024) {
        // The server refuses more than 1024 parts; say so rather than failing on chunk 1025.
        return { error: WFT('error.payload_too_large', 'حجم البيانات أكبر من الحد المسموح للحفظ ({size} م.ب)', { size: (buf.length / 1048576).toFixed(1) }) };
      }

      let sent = 0;
      let failure = null;
      const sendChunk = async index => {
        const part = buf.subarray(index * CHUNK_PART_BYTES, (index + 1) * CHUNK_PART_BYTES);
        let bin = '';
        for (let j = 0; j < part.length; j++) bin += String.fromCharCode(part[j]);
        const body = JSON.stringify({ id, idx: index, total, data: btoa(bin) });
        // Chunks are idempotent ({idx}.part is rewritten with the same bytes),
        // so retrying a flaky connection or a worker restart is safe.
        const chunkSignal = signal || (typeof AbortSignal !== 'undefined' && AbortSignal.timeout
          ? AbortSignal.timeout(60000) : undefined);
        let lastError = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            const res = await fetch('/api/body-chunk', {
              method: 'POST',
              headers: chunkHeaders,
              body,
              signal: chunkSignal,
            });
            if (!res.ok) throw new Error('Chunk upload failed (' + res.status + ')');
            sent += 1;
            if (onProgress) onProgress(sent, total);
            return;
          } catch (error) {
            if (signal && signal.aborted) throw error;
            lastError = error;
          }
        }
        throw lastError;
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
      const trialBanner = document.getElementById('trialBanner');
      if (trialBanner) trialBanner.remove();
      document.getElementById('tenantAppPage').classList.remove('active');
      document.getElementById('tenantAuthPage').classList.add('active');
      const loginForm = document.getElementById('loginForm');
      const otpForm = document.getElementById('loginOtpForm');
      if (loginForm) loginForm.style.display = 'block';
      if (otpForm) otpForm.style.display = 'none';
      showTenantError('loginError', '');
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
      tenantAdminPackagesPage: '/app/admin/packages',
      tenantAdminPlatformPage: '/app/admin/platform'
    };

    // ─────────────────────────────────────────────────────────────────────────
    // Device Trust & OTP Authentication
    // ─────────────────────────────────────────────────────────────────────────

    const T_DEVICE_ID_KEY = 'landloom_device_id';
    const T_TRUSTED_DEVICE_KEY = 'landloom_trusted_device_token';
    let currentLoginChallengeToken = null;
    let otpResendCooldownTimer = null;

    function getOrCreateDeviceId() {
      let id = null;
      try { id = localStorage.getItem(T_DEVICE_ID_KEY); } catch (e) {}
      if (!id) {
        try {
          id = (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID()
            : ('dev_' + Math.random().toString(36).slice(2) + Date.now().toString(36));
        } catch (e) {
          id = 'dev_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
        }
        try { localStorage.setItem(T_DEVICE_ID_KEY, id); } catch (e) {}
      }
      return id;
    }

    function getDeviceFingerprint() {
      try {
        const parts = [
          getOrCreateDeviceId(),
          navigator.userAgent || '',
          navigator.platform || '',
          (screen && (screen.width + 'x' + screen.height)) || '',
          (Intl && Intl.DateTimeFormat && Intl.DateTimeFormat().resolvedOptions().timeZone) || '',
          navigator.language || ''
        ];
        return parts.join('|');
      } catch (e) {
        return getOrCreateDeviceId();
      }
    }

    function getDeviceName() {
      try {
        const ua = navigator.userAgent || '';
        let browser = 'المتصفح';
        if (ua.includes('Chrome')) browser = 'Chrome';
        else if (ua.includes('Safari')) browser = 'Safari';
        else if (ua.includes('Firefox')) browser = 'Firefox';
        else if (ua.includes('Edge')) browser = 'Edge';

        let os = 'جهاز';
        if (ua.includes('Windows')) os = 'Windows';
        else if (ua.includes('Macintosh') || ua.includes('Mac OS')) os = 'macOS';
        else if (ua.includes('iPhone') || ua.includes('iPad')) os = 'iOS';
        else if (ua.includes('Android')) os = 'Android';
        return browser + ' على ' + os;
      } catch (e) {
        return 'متصفح ويب';
      }
    }

    function initOtpDigitBoxes() {
      const container = document.getElementById('loginOtpBoxes');
      const hiddenInput = document.getElementById('loginOtpInput');
      if (!container || container.dataset.ready) return;
      container.dataset.ready = '1';

      const boxes = Array.from(container.querySelectorAll('.otp-digit-box'));

      function syncOtp() {
        const val = boxes.map(b => b.value.trim()).join('');
        if (hiddenInput) hiddenInput.value = val;
        boxes.forEach(b => {
          if (b.value.trim()) b.classList.add('filled');
          else b.classList.remove('filled');
        });
        return val;
      }

      boxes.forEach((box, idx) => {
        box.addEventListener('input', () => {
          const char = box.value.replace(/[^0-9a-zA-Z]/g, '').slice(-1);
          box.value = char;
          const full = syncOtp();
          if (char && idx < boxes.length - 1) {
            boxes[idx + 1].focus();
            boxes[idx + 1].select();
          }
          if (full.length === boxes.length) {
            const btn = document.getElementById('loginOtpSubmitBtn');
            if (btn) btn.focus();
          }
        });

        box.addEventListener('keydown', (e) => {
          if (e.key === 'Backspace') {
            if (!box.value && idx > 0) {
              boxes[idx - 1].focus();
              boxes[idx - 1].value = '';
              syncOtp();
              e.preventDefault();
            } else {
              box.value = '';
              syncOtp();
            }
          } else if (e.key === 'ArrowLeft') {
            if (idx > 0) boxes[idx - 1].focus();
          } else if (e.key === 'ArrowRight') {
            if (idx < boxes.length - 1) boxes[idx + 1].focus();
          }
        });

        box.addEventListener('paste', (e) => {
          e.preventDefault();
          const pasteData = (e.clipboardData || window.clipboardData).getData('text') || '';
          const cleaned = pasteData.trim().replace(/[^0-9a-zA-Z]/g, '').slice(0, boxes.length);
          if (!cleaned) return;
          for (let i = 0; i < boxes.length; i++) {
            boxes[i].value = cleaned[i] || '';
          }
          const full = syncOtp();
          const nextIdx = Math.min(cleaned.length, boxes.length - 1);
          boxes[nextIdx].focus();
          if (full.length === boxes.length) {
            const btn = document.getElementById('loginOtpSubmitBtn');
            if (btn) btn.focus();
          }
        });

        box.addEventListener('focus', () => {
          box.select();
        });
      });
    }

    function resetOtpBoxes() {
      const boxes = document.querySelectorAll('#loginOtpBoxes .otp-digit-box');
      boxes.forEach(b => {
        b.value = '';
        b.classList.remove('filled');
      });
      const hiddenInput = document.getElementById('loginOtpInput');
      if (hiddenInput) hiddenInput.value = '';
    }

    async function handleLogin(e) {
      e.preventDefault();
      showTenantError('loginError', '');
      const email = document.getElementById('loginEmail').value.trim();
      const password = document.getElementById('loginPassword').value;
      const deviceId = getOrCreateDeviceId();
      let trustedDeviceToken = '';
      try { trustedDeviceToken = localStorage.getItem(T_TRUSTED_DEVICE_KEY) || ''; } catch (e) {}
      const deviceFingerprint = getDeviceFingerprint();

      const data = await api('POST', '/api/auth/login', {
        email,
        password,
        deviceId,
        trustedDeviceToken,
        deviceFingerprint
      });

      if (data && data.otpRequired && data.challengeToken) {
        currentLoginChallengeToken = data.challengeToken;
        const loginForm = document.getElementById('loginForm');
        const otpForm = document.getElementById('loginOtpForm');
        const hint = document.getElementById('loginOtpHint');
        initOtpDigitBoxes();
        resetOtpBoxes();
        if (hint && data.maskedEmail) {
          hint.textContent = 'رمز التحقق مرسل إلى ' + data.maskedEmail;
        }
        if (loginForm) loginForm.style.display = 'none';
        if (otpForm) otpForm.style.display = 'block';
        const firstBox = document.querySelector('#loginOtpBoxes .otp-digit-box');
        if (firstBox) {
          setTimeout(() => { firstBox.focus(); firstBox.select(); }, 50);
        }
        startOtpResendCooldown(60);
        return;
      }

      if (data && data.success && data.token) {
        setTenantToken(data.token);
        setTenantUser(data.tenant);
        await bootstrapTenant();
      } else {
        showTenantError('loginError', (data && data.error) || WFT('auth.login_failed', 'فشل تسجيل الدخول'));
      }
    }

    async function handleLoginOtpVerify(e) {
      e.preventDefault();
      showTenantError('loginError', '');
      const otpInput = document.getElementById('loginOtpInput');
      const otp = otpInput ? otpInput.value.trim() : '';
      if (!otp || !currentLoginChallengeToken) return;

      const deviceId = getOrCreateDeviceId();
      const deviceFingerprint = getDeviceFingerprint();
      const deviceName = getDeviceName();

      const submitBtn = document.getElementById('loginOtpSubmitBtn');
      if (submitBtn) submitBtn.disabled = true;

      const data = await api('POST', '/api/auth/login/verify-otp', {
        challengeToken: currentLoginChallengeToken,
        otp,
        deviceId,
        deviceFingerprint,
        deviceName
      });

      if (submitBtn) submitBtn.disabled = false;

      if (data && data.success && data.token) {
        if (data.trustedDeviceToken) {
          try { localStorage.setItem(T_TRUSTED_DEVICE_KEY, data.trustedDeviceToken); } catch (err) {}
        }
        clearInterval(otpResendCooldownTimer);
        setTenantToken(data.token);
        setTenantUser(data.tenant);
        await bootstrapTenant();
      } else {
        let msg = (data && data.error) || WFT('auth.otp_invalid', 'رمز التحقق غير صحيح');
        if (data && typeof data.remainingAttempts === 'number' && data.remainingAttempts > 0) {
          msg += ' (المحاولات المتبقية: ' + data.remainingAttempts + ')';
        }
        showTenantError('loginError', msg);
        if (data && data.remainingAttempts === 0) {
          handleLoginOtpCancel();
        }
      }
    }

    async function handleLoginOtpResend() {
      if (!currentLoginChallengeToken) return;
      const resendBtn = document.getElementById('loginOtpResendBtn');
      if (resendBtn && resendBtn.disabled) return;
      showTenantError('loginError', '');

      const data = await api('POST', '/api/auth/login/resend-otp', {
        challengeToken: currentLoginChallengeToken
      });

      if (data && data.success && data.challengeToken) {
        currentLoginChallengeToken = data.challengeToken;
        toast(WFT('auth.otp_resent', 'تم إرسال رمز تحقق جديد إلى بريدك'));
        startOtpResendCooldown(60);
      } else {
        showTenantError('loginError', (data && data.error) || 'تعذر إعادة إرسال الرمز');
      }
    }

    function startOtpResendCooldown(seconds) {
      const resendBtn = document.getElementById('loginOtpResendBtn');
      if (!resendBtn) return;
      clearInterval(otpResendCooldownTimer);
      let remaining = seconds;
      resendBtn.disabled = true;
      resendBtn.textContent = 'إعادة إرسال الرمز (' + remaining + ')';
      otpResendCooldownTimer = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
          clearInterval(otpResendCooldownTimer);
          resendBtn.disabled = false;
          resendBtn.textContent = 'إعادة إرسال الرمز';
        } else {
          resendBtn.textContent = 'إعادة إرسال الرمز (' + remaining + ')';
        }
      }, 1000);
    }

    function handleLoginOtpCancel() {
      currentLoginChallengeToken = null;
      clearInterval(otpResendCooldownTimer);
      resetOtpBoxes();
      const loginForm = document.getElementById('loginForm');
      const otpForm = document.getElementById('loginOtpForm');
      if (otpForm) otpForm.style.display = 'none';
      if (loginForm) loginForm.style.display = 'block';
      showTenantError('loginError', '');
    }
