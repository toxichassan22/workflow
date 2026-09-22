    async function tenantApplyChartRange() {
      const params = new URLSearchParams();
      if (tenantChartRange.preset === 'custom') {
        if (!tenantChartRange.from || !tenantChartRange.to) return;
        params.set('from', tenantChartRange.from);
        params.set('to', tenantChartRange.to);
      } else if (tenantChartRange.preset === 'ytd') {
        params.set('months', String(new Date().getMonth() + 1));
      } else {
        params.set('months', tenantChartRange.preset);
      }
      const data = await api('GET', '/api/dashboard/activity?' + params.toString()).catch(() => null);
      if (data && data.trends) {
        renderTenantActivityChart(data.trends);
      }
    }

    // Re-render the dashboard widgets on language toggle, same contract the
    // super-admin charts follow: labels rebuild through WFT at render time.
    document.addEventListener('wf:lang', function () {
      const page = document.getElementById('tenantDashboardPage');
      if (!page || !page.classList.contains('active')) return;
      renderDashboardBalance(tenantLastOverview);
      if (tenantLastTrends) renderTenantActivityChart(tenantLastTrends);
    });

    async function handleLogin(e) {
      e.preventDefault();
      showTenantError('loginError', '');
      const email = document.getElementById('loginEmail').value.trim();
      const password = document.getElementById('loginPassword').value;
      const data = await api('POST', '/api/auth/login', { email, password });
      if (data.success && data.token) {
        setTenantToken(data.token);
        setTenantUser(data.tenant);
        await bootstrapTenant();
      } else {
        showTenantError('loginError', data.error || WFT('auth.login_failed', 'فشل تسجيل الدخول'));
      }
    }

    function tenantLogout() {
      api('POST', '/api/auth/logout', {});
      removeTenantToken();
      localStorage.removeItem(T_TENANT_KEY);
      clearTenantNavigationState();
      tenantUser = null;
      tenantBranding = null;
      showAuthPage();
    }

    async function restoreTenantNavigation(preferredPageId = null) {
      const state = getTenantNavigationState();
      if (!state) return false;
      // A refresh on a workspace route must land on the page the URL names, while still reopening
      // the presentation or draft that page was showing.
      if (preferredPageId && document.getElementById(preferredPageId)) state.pageId = preferredPageId;

      const currentTenantId = tenantUser && (tenantUser.id || tenantUser.tenantId);
      if (state.tenantId && currentTenantId && state.tenantId !== currentTenantId) {
        clearTenantNavigationState();
        return false;
      }
      if (!state.pageId || !document.getElementById(state.pageId)) {
        clearTenantNavigationState();
        return false;
      }

      try {
        if (state.presentationId && TENANT_NAVIGATION_CONTEXT_PAGES.has(state.pageId)) {
          await openExistingPresentation(state.presentationId);
          if (tenantPresentationId !== state.presentationId) {
            clearTenantNavigationState();
            return false;
          }
          if (state.pageId === 'tenantGenerationPage') showTenantPage('tenantSlidesPage');
          else if (state.pageId !== 'tenantSlidesPage') {
            await navigateTenantWorkflow(state.pageId);
            if (state.pageId === 'tenantProjectPage' && state.activeSection) showSection(state.activeSection, true);
          }
          return true;
        }

        if (state.draftId && TENANT_NAVIGATION_CONTEXT_PAGES.has(state.pageId)) {
          const loaded = await openProjectDraftById(state.draftId);
          if (!loaded) {
            if (state.mode === 'new') {
              await startTenantProject();
              if (state.pageId === 'tenantProjectPage') return true;
              if (state.pageId === 'tenantGenerationPage') showTenantPage('tenantSlidesPage');
              else await navigateTenantWorkflow(state.pageId);
              return true;
            }
            clearTenantNavigationState();
            return false;
          }
          tenantActiveProjectSection = state.activeSection || tenantActiveProjectSection;
          if (state.pageId === 'tenantProjectPage') {
            showTenantPage(state.pageId);
            if (tenantActiveProjectSection) showSection(tenantActiveProjectSection, true);
          } else if (state.pageId === 'tenantGenerationPage') {
            showTenantPage('tenantSlidesPage');
          } else {
            await navigateTenantWorkflow(state.pageId);
          }
          return true;
        }

        if (TENANT_NAVIGATION_CONTEXT_PAGES.has(state.pageId)) {
          await startTenantProject();
          if (state.pageId === 'tenantProjectPage') return true;
          if (state.pageId === 'tenantGenerationPage') showTenantPage('tenantSlidesPage');
          else await navigateTenantWorkflow(state.pageId);
          return true;
        }

        switch (state.pageId) {
          case 'tenantDashboardPage':
            showTenantPage(state.pageId);
            return true;
          case 'tenantSettingsPage':
            await openTenantSettings();
            return true;
          case 'tenantTeamPage':
            await openTenantTeam();
            return true;
          case 'tenantFieldsPage':
            await openTenantFields();
            return true;
          case 'tenantPresentationsPage':
            await openTenantPresentations();
            return true;
          case 'tenantProjectPresentationsPage': {
            const presentationsDraftId = state.draftId || currentProjectPresentationsDraftId();
            if (presentationsDraftId) await openProjectDraftById(presentationsDraftId);
            await loadProjectPresentationsPage(presentationsDraftId);
            return true;
          }
          case 'tenantUsersPage':
            await openTenantUsers();
            return true;
          case 'tenantTrainingPage':
            await openTenantTraining();
            return true;
          case 'tenantAIRulesPage':
            await openTenantAIRules();
            return true;
          case 'tenantApprovalsPage':
            await openTenantApprovals();
            return true;
          case 'tenantLandloomOpsPage':
            await openLandloomOpsPage(state.opsTab);
            return true;
          case 'tenantNotificationsPage':
            await openNotificationsPage();
            return true;
          case 'tenantAdminPage':
            if (!tenantUser.isAdmin) return false;
            await openTenantAdmin();
            return true;
          case 'tenantCompaniesPage':
            if (!tenantUser.isAdmin) return false;
            await openTenantCompanies();
            return true;
          case 'tenantAdminRechargePage':
            if (!tenantUser.isAdmin) return false;
            await openAdminRechargePage();
            return true;
          case 'tenantAdminTicketsPage':
            if (!tenantUser.isAdmin) return false;
            await openAdminTicketsPage();
            return true;
          case 'tenantAdminPlatformPage':
            if (!tenantUser.isAdmin) return false;
            await openAdminPlatformPage();
            return true;
          default:
            clearTenantNavigationState();
            return false;
        }
      } catch (error) {
        console.warn('[NAVIGATION] Restore failed:', error);
        clearTenantNavigationState();
        return false;
      }
    }

    // One-shot dashboard prefetch started during boot so the list requests fly
    // while the shell renders instead of after. Consumed once by loadDashboard.
    let tenantBootPrefetch = null;

    function consumeTenantBootPrefetch() {
      const prefetch = tenantBootPrefetch;
      tenantBootPrefetch = null;
      return prefetch;
    }

    // A boot promise started with the plain api() helper waits forever when the
    // server holds the connection without answering. Race it so a wedged list
    // request fails fast into the retry state instead of a permanent loader.
    function withBootTimeout(promise, ms = 25000) {
      if (!promise || typeof promise.then !== 'function') {
        return Promise.resolve({ success: false, error_code: 'CLIENT_REQUEST_TIMEOUT' });
      }
      let timer = null;
      const timeout = new Promise(resolve => {
        timer = setTimeout(() => resolve({ success: false, error_code: 'CLIENT_REQUEST_TIMEOUT' }), ms);
      });
      return Promise.race([
        promise.then(
          value => { if (timer) clearTimeout(timer); return value; },
          () => { if (timer) clearTimeout(timer); return { success: false }; }
        ),
        timeout
      ]);
    }

    function renderListLoadError(host, retryCall) {
      if (!host) return;
      host.innerHTML = '<p class="tenant-hint">' + escapeHtml(WFT('list.load_failed', 'تعذر تحميل القائمة')) + '</p>' +
        '<button type="button" class="btn small ghost" onclick="' + retryCall + '">' + escapeHtml(WFT('list.retry', 'إعادة المحاولة')) + '</button>';
    }
    async function bootstrapTenant() {
      // me, branding and the font CSS depend on the token only, so they run
      // as one wave instead of three sequential round trips on every refresh.
      const [me, brandingData] = await Promise.all([
        api('GET', '/api/auth/me'),
        api('GET', '/api/branding'),
        loadTenantFontCss(),
      ]);
      if (!me.success || !me.tenant) {
        showAuthPage();
        return;
      }
      tenantUser = me.tenant;
      // Store user info (role, name, permissions)
      if (me.user) {
        tenantUser._userName = me.user.name;
        tenantUser._userRole = me.user.role;
        tenantUser._permissions = me.user.permissions || {};
        tenantUser._userId = me.user.id || null;
      }
      setTenantUser(tenantUser);
      updateTenantTopbar();
      applyRolePermissions();
      applyTenantBrandingData(brandingData);
      // A path the user actually asked for wins over the last-visited page, so deep links and
      // refreshes land where the URL says instead of somewhere remembered in localStorage.
      const resolvedRequested = (typeof resolveTenantRoutePath === 'function') ? resolveTenantRoutePath(window.location.pathname) : null;
      const requestedPage = (resolvedRequested && resolvedRequested.pageId) || TENANT_ROUTE_PAGES[window.location.pathname];
      const requestedSection = new URLSearchParams(window.location.search).get('section');
      // The dashboard list is tiny now, so start it while the route resolves
      // instead of waiting for the page to ask for it.
      if (!requestedPage || requestedPage === 'tenantDashboardPage') {
        tenantBootPrefetch = {
          pres: api('GET', '/api/presentations?limit=5'),
          appr: api('GET', '/api/approvals').catch(() => ({ success: false })),
        };
      }
      showTenantApp();
      if (typeof startNotificationsPolling === 'function') startNotificationsPolling();
      if (resolvedRequested && typeof enforceTenantRouteGuard === 'function') {
        const guard = enforceTenantRouteGuard(requestedPage, resolvedRequested.urlSlug);
        if (guard === 'TENANT_SLUG_MISMATCH' || guard === 'TENANT_ADMIN_FORBIDDEN') {
          showTenantPage('tenantDashboardPage', true);
          syncTenantBrowserHistory('tenantDashboardPage', {}, true);
          return;
        }
      }
      if (requestedPage && typeof canonicalizeTenantUrl === 'function') canonicalizeTenantUrl(requestedPage, true);
      if (requestedPage) {
        if (requestedPage === 'tenantVisualConceptPage') {
          const navigation = getTenantNavigationState();
          const currentTenantId = tenantUser && (tenantUser.id || tenantUser.tenantId);
          const savedDraftId = navigation && navigation.draftId &&
            (!navigation.tenantId || navigation.tenantId === currentTenantId)
            ? navigation.draftId : null;
          if (savedDraftId) await openProjectDraftById(savedDraftId);
          await openTenantVisualConceptPage();
        } else if (requestedPage === 'tenantProjectPage') {
          // The project-form route carries no draft identity in the URL, so a refresh must
          // reopen the draft remembered in localStorage instead of showing a blank new-project
          // form. Read the state first: showTenantPage() rewrites it from the still-empty
          // tenantProjectData, which would erase the draft id we are about to restore.
          const navigation = getTenantNavigationState();
          const currentTenantId = tenantUser && (tenantUser.id || tenantUser.tenantId);
          const savedDraftId = navigation && navigation.draftId &&
            (!navigation.tenantId || navigation.tenantId === currentTenantId)
            ? navigation.draftId : null;
          if (!(savedDraftId && await openProjectDraftById(savedDraftId))) {
            await startTenantProject();
          }
          const sectionToShow = requestedSection ||
            (navigation && navigation.pageId === 'tenantProjectPage' && navigation.activeSection) || null;
          if (sectionToShow) showSection(sectionToShow, true);
        } else if (requestedPage === 'tenantProjectPresentationsPage') {
          const requestedDraftId = new URLSearchParams(window.location.search).get('draftId');
          if (requestedDraftId) {
            await openProjectDraftById(requestedDraftId);
            await loadProjectPresentationsPage(requestedDraftId);
          } else {
            await loadProjectPresentationsPage();
          }
        } else if (TENANT_NAVIGATION_CONTEXT_PAGES.has(requestedPage)) {
          // The slides route carries no identity either, and it used to be shown as-is: a refresh
          // landed on an empty workspace with no slides, no plan and no project data, while the
          // presentation it was editing sat on the server.
          if (!(await restoreTenantNavigation(requestedPage))) {
            showTenantPage(requestedPage, true);
            renderTenantSlides();
            setSlidesEditorInfo('', 0);
          }
        } else if (requestedPage === 'tenantDashboardPage') {
          showTenantPage(requestedPage, true);
        } else if (requestedPage === 'tenantPresentationsPage') {
          await openTenantPresentations();
        } else if (requestedPage === 'tenantSettingsPage') {
          await openTenantSettings();
        } else if (requestedPage === 'tenantTeamPage') {
          await openTenantTeam();
        } else if (requestedPage === 'tenantFieldsPage') {
          await openTenantFields();
        } else if (requestedPage === 'tenantUsersPage') {
          await openTenantUsers();
        } else if (requestedPage === 'tenantTrainingPage') {
          await openTenantTraining();
        } else if (requestedPage === 'tenantAIRulesPage') {
          await openTenantAIRules();
        } else if (requestedPage === 'tenantApprovalsPage') {
          await openTenantApprovals();
        } else if (requestedPage === 'tenantLandloomOpsPage') {
          // Reopen the sub-tab the refresh was sitting on — the route carries
          // no tab, so it comes from the remembered navigation state.
          const opsNavigation = getTenantNavigationState();
          const opsTenantId = tenantUser && (tenantUser.id || tenantUser.tenantId);
          const savedOpsTab = opsNavigation && opsNavigation.opsTab &&
            (!opsNavigation.tenantId || opsNavigation.tenantId === opsTenantId)
            ? opsNavigation.opsTab : null;
          await openLandloomOpsPage(savedOpsTab);
        } else if (requestedPage === 'tenantNotificationsPage') {
          await openNotificationsPage();
        } else if (requestedPage === 'tenantAdminPage') {
          if (tenantUser.isAdmin) await openTenantAdmin();
          else { showTenantPage('tenantDashboardPage', true); syncTenantBrowserHistory('tenantDashboardPage', {}, true); }
        } else if (requestedPage === 'tenantCompaniesPage') {
          await openTenantCompanies();
        } else if (requestedPage === 'tenantAdminRechargePage') {
          await openAdminRechargePage();
        } else if (requestedPage === 'tenantAdminTicketsPage') {
          await openAdminTicketsPage();
        } else if (requestedPage === 'tenantAdminPlatformPage') {
          await openAdminPlatformPage();
        } else {
          showTenantPage(requestedPage, true);
        }
      } else if (!(await restoreTenantNavigation())) {
        // Restore the last page for every role; SAG super admin falls back to the admin panel.
        if (tenantUser.isAdmin) openTenantAdmin();
        else showTenantPage('tenantDashboardPage');
      }
      // The bare domain is not a page. Rewrite it to the real route of whatever is on screen so
      // every part of the app has an address, and Back has somewhere to return to.
      if (window.location.pathname === '/') {
        const current = tgrCurrentPageId();
        if (current && TENANT_PAGE_ROUTES[current]) syncTenantBrowserHistory(current, {}, true);
      }
    }

    function hasPermission(key) {
      if (!tenantUser) return false;
      if (tenantUser.isAdmin) return true;
      const perms = tenantUser._permissions || {};
      return perms[key] === true;
    }

    function applyRolePermissions() {
      const role = tenantUser._userRole || 'company_admin';
      const isSagAdmin = tenantUser.isAdmin;
      const isCompanyAdmin = role === 'company_admin' || isSagAdmin;
      // Show/hide elements with data-permission attribute
      document.querySelectorAll('[data-permission]').forEach(el => {
        const key = el.getAttribute('data-permission');
        el.style.display = hasPermission(key) ? '' : 'none';
      });
      // data-permission-any shows the element when the user holds any listed key
      document.querySelectorAll('[data-permission-any]').forEach(el => {
        const keys = (el.getAttribute('data-permission-any') || '')
          .split(',').map(k => k.trim()).filter(Boolean);
        el.style.display = keys.some(k => hasPermission(k)) ? '' : 'none';
      });
      // Legacy admin-only elements still controlled by role (skip if already handled by a permission attribute)
      document.querySelectorAll('.tenant-admin-only').forEach(el => {
        if (el.hasAttribute('data-permission') || el.hasAttribute('data-permission-any')) return;
        el.style.display = isCompanyAdmin ? '' : 'none';
      });
      // Show user info in sidebar
      const userInfo = document.getElementById('tenantUserInfo');
      if (userInfo) userInfo.textContent = tenantUser._userName || tenantUser.companyName || '';
      // SAG admin: hide company-specific nav items, show admin panel button
      if (isSagAdmin) {
        document.querySelectorAll('.tenant-dash-card.tenant-admin-only').forEach(el => {
          el.style.display = 'none';
        });
      }
      applyTenantNavGroupState();
      updateTenantChrome(tgrCurrentPageId() || (isSagAdmin ? 'tenantAdminPage' : 'tenantDashboardPage'));
    }

    function updateTenantTopbar() {
      if (!tenantUser) return;
      document.getElementById('tenantName').textContent = tenantUser.companyName || 'الشركة';
      document.getElementById('tenantPlan').textContent = tenantUser.plan || 'free';
      updateTenantLogoMark();
      const adminBtn = document.getElementById('tenantAdminBtn');
      if (adminBtn) adminBtn.classList.toggle('tenant-hidden', !tenantUser.isAdmin);
    }

    async function loadTenantFontCss() {
      const token = getTenantToken();
      const headers = {};
      if (token) headers['Authorization'] = 'Bearer ' + token;
      try {
        const res = await fetch('/api/branding/font.css', { headers });
        const css = res.ok ? await res.text() : '';
        let style = document.getElementById('tenantFontCss');
        if (!style) {
          style = document.createElement('style');
          style.id = 'tenantFontCss';
          document.head.appendChild(style);
        }
        style.textContent = css || '';
      } catch (e) {
        console.warn('[FONT CSS] load failed', e);
      }
    }

    async function loadTenantBranding() {
      const data = await api('GET', '/api/branding');
      applyTenantBrandingData(data);
    }

    function updateTenantLogoMark() {
      const markEl = document.getElementById('tenantLogoMark');
      if (!markEl) return;
      const name = (tenantUser && tenantUser.companyName) || (tenantBranding && tenantBranding.company_name) || '';
      markEl.textContent = name.trim().charAt(0) || '—';
    }

    function applyTenantBrandingData(data) {
      if (!data || !data.success || !data.branding) return false;
      tenantBranding = data.branding;
      const b = data.branding;
      // The workspace keeps the platform palette: company colors reach the
      // generated slides only, so no CSS variables are written here.
      // Logo: an uploaded logo wins; otherwise the company initial stands in
      // for it (the product ships no placeholder images).
      const logoEl = document.getElementById('tenantLogo');
      const markEl = document.getElementById('tenantLogoMark');
      updateTenantLogoMark();
      if (logoEl) {
        if (b.logo_path) {
          logoEl.onerror = () => {
            logoEl.classList.add('hidden');
            if (markEl) markEl.classList.remove('hidden');
          };
          const logoSrc = b.logo_path.startsWith('http') ? b.logo_path : b.logo_path + '?t=' + Date.now();
          logoEl.src = logoSrc;
          logoEl.classList.remove('hidden');
          if (markEl) markEl.classList.add('hidden');
        } else {
          logoEl.classList.add('hidden');
          if (markEl) markEl.classList.remove('hidden');
        }
      }
      return true;
    }

    const MANAGED_FONT_WEIGHTS = ['light', 'regular', 'medium', 'bold', 'black'];

    async function loadTenantFonts() {
      const host = document.getElementById('tenantFontSelections');
      if (!host) return;
      const data = await api('GET', '/api/branding/fonts');
      if (!data.success) { host.textContent = 'تعذر تحميل الخطوط'; return; }
      const selections = data.selections || [];
      const available = data.available || [];
      window.tenantAvailableFonts = available;
      selections.forEach(sel => {
        if (sel.font_id && !sel.font_family) {
          const matched = available.find(f => f.id === sel.font_id);
          if (matched) sel.font_family = matched.font_family;
        } else if (sel.custom_font_path && !sel.font_family) {
          sel.font_family = (sel.custom_font_path.split('/').pop() || '').replace(/\.[^.]+$/, '').replace(/_(light|regular|medium|bold|black)$/i, '').replace(/_/g, ' ');
        }
      });
      const currentArabic = selections.find(item => item.script === 'arabic' && item.weight === 'regular')
        || selections.find(item => item.script === 'arabic')
        || {};
      const currentLatin = selections.find(item => item.script === 'latin' && item.weight === 'regular')
        || selections.find(item => item.script === 'latin')
        || {};
      const activeBranding = (typeof tenantBranding !== 'undefined' && tenantBranding) ? tenantBranding : (window.tenantBranding || null);
      const matchedBrandingSel = activeBranding && activeBranding.font_family
        ? selections.find(item => item.font_family && item.font_family.toLowerCase() === activeBranding.font_family.toLowerCase())
        : null;
      const currentSelection = matchedBrandingSel
        || ((currentArabic.font_id || currentArabic.custom_font_path) ? currentArabic : currentLatin);
      const uniqueFonts = [];
      available.forEach(font => {
        const existing = uniqueFonts.find(item => item.font_family === font.font_family);
        if (!existing) {
          uniqueFonts.push(font);
        } else if (font.weight === 'regular' && existing.weight !== 'regular') {
          uniqueFonts[uniqueFonts.indexOf(existing)] = font;
        }
      });
      const customUploaded = data.custom_uploaded || [];
      const customFonts = [];
      customUploaded.forEach(c => {
        if (!uniqueFonts.find(f => f.font_family.toLowerCase() === c.font_family.toLowerCase())) {
          customFonts.push(c);
        }
      });
      selections.forEach(sel => {
        if (sel.custom_font_path && !sel.font_id) {
          const name = sel.font_family || (sel.custom_font_path.split('/').pop() || 'خط مخصص').replace(/\.[^.]+$/, '').replace(/_(light|regular|medium|bold|black)$/i, '').replace(/_/g, ' ');
          const already = uniqueFonts.find(f => f.font_family.toLowerCase() === name.toLowerCase()) || customFonts.find(f => f.font_family.toLowerCase() === name.toLowerCase());
          if (!already) {
            customFonts.push({ id: 'custom_' + sel.script + '_' + sel.weight, font_family: name, font_name: name, script: sel.script, weight: sel.weight, is_custom: true, custom_font_path: sel.custom_font_path });
          }
        }
      });
      window.tenantCustomFonts = customFonts;
      const allFonts = uniqueFonts.concat(customFonts);
      const fontUiEn = (typeof window.WFI18n !== 'undefined' && window.WFI18n.getLang() === 'en');
      const fontScriptName = script => trDynamicI18n(script === 'arabic' ? 'عربي' : 'لاتيني');
      const fontUploadedMark = trDynamicI18n('(مرفوع)');
      const summary = selections.length
        ? selections.map(item => fontScriptName(item.script) + ' ' + item.weight + (item.custom_font_path ? ' ' + fontUploadedMark : '')).join(fontUiEn ? ', ' : '، ')
        : 'سيتم استخدام الخط الافتراضي';
      host.innerHTML = '<div style="display:grid;gap:10px;border:1px solid var(--line);border-radius:10px;padding:10px;">' +
        '<select id="tenantPrimaryFontSelect" onchange="selectTenantPrimaryFont(this.value)" style="width:100%;padding:9px;border:1px solid var(--line);border-radius:8px;font-family:inherit;">' +
        '<option value="">استخدام الخط الافتراضي</option>' +
        allFonts.map(font => {
          const isSelected = (currentSelection.font_id && font.id === currentSelection.font_id)
            || (currentSelection.font_family && font.font_family && font.font_family.toLowerCase() === currentSelection.font_family.toLowerCase());
          return '<option value="' + escapeHtml(font.id) + '"' + (isSelected ? ' selected' : '') + '>' + escapeHtml(font.font_name || font.font_family) + ' — ' + fontScriptName(font.script) + (font.is_custom ? ' ' + fontUploadedMark : '') + '</option>';
        }).join('') +
        '</select>' +
        '<label id="tenantAutoFontDropzone" style="display:flex;align-items:center;justify-content:center;min-height:72px;border:2px dashed var(--line);border-radius:10px;cursor:pointer;color:var(--muted);text-align:center;padding:12px;">اسحب ملف الخط هنا أو اضغط لاختياره<input id="tenantAutoFontFile" type="file" accept=".ttf,.otf,.woff,.woff2" style="display:none" onchange="uploadTenantFontAutomatically(this)"></label>' +
        '<span style="font-size:12px;color:var(--muted);">' + escapeHtml(summary) + '</span>' +
        '</div>';
      const dropzone = document.getElementById('tenantAutoFontDropzone');
      if (dropzone) {
        dropzone.ondragover = event => { event.preventDefault(); dropzone.style.borderColor = 'var(--p)'; };
        dropzone.ondragleave = () => { dropzone.style.borderColor = 'var(--line)'; };
        dropzone.ondrop = event => {
          event.preventDefault();
          dropzone.style.borderColor = 'var(--line)';
          uploadTenantFontAutomatically({ files: event.dataTransfer.files });
        };
      }
      refreshDynamicI18n(host);
    }
    document.addEventListener('wf:lang', () => { try { loadTenantFonts(); } catch (e) { /* ignore */ } });

    async function selectTenantPrimaryFont(fontId) {
      if (fontId === 'custom') return;
      if (fontId.startsWith('custom_')) {
        const allCustom = (window.tenantCustomFonts || []);
        const targetFont = allCustom.find(f => f.id === fontId);
        const name = targetFont ? targetFont.font_family : 'خط مخصص';
        if (targetFont && targetFont.custom_font_path) {
          await api('PUT', '/api/branding/fonts', { script: targetFont.script || 'arabic', weight: targetFont.weight || 'regular', custom_font_path: targetFont.custom_font_path });
        }
        await api('PUT', '/api/branding', { font_family: name, font_arabic: name });
        await loadTenantBranding();
        await loadTenantFonts();
        toast('تم تخصيص الخط للشركة');
        return;
      }
      if (!fontId) {
        const weights = ['light', 'regular', 'medium', 'bold', 'black'];
        await Promise.all(weights.flatMap(w => [
          api('DELETE', '/api/branding/fonts/arabic/' + w),
          api('DELETE', '/api/branding/fonts/latin/' + w)
        ]));
        await api('PUT', '/api/branding', { font_family: 'The Sans Arabic', font_arabic: 'The Sans Arabic' });
        await loadTenantBranding();
        await loadTenantFonts();
        return;
      }
      const selected = (window.tenantAvailableFonts || []).find(font => font.id === fontId);
      if (!selected) return;
      const weight = selected.weight || 'regular';
      const matches = (window.tenantAvailableFonts || []).filter(font => font.font_family === selected.font_family);
      const target = matches.length ? matches : [selected];
      // Replace the previous family completely. The PDF renderer will reuse
      // the nearest available face when the new family has only one weight.
      await Promise.all(MANAGED_FONT_WEIGHTS.flatMap(w => [
        api('DELETE', '/api/branding/fonts/arabic/' + w),
        api('DELETE', '/api/branding/fonts/latin/' + w)
      ]));
      for (const font of target) {
        await setTenantFontSelection(font.script, font.weight || weight, font.id, true);
      }
      if (selected.font_family) {
        await api('PUT', '/api/branding', { font_family: selected.font_family, font_arabic: selected.font_family });
      }
      await loadTenantBranding();
      await loadTenantFonts();
      toast('تم تخصيص الخط للشركة');
    }

    async function uploadTenantFontAutomatically(input) {
      if (!input.files || !input.files[0]) return;
      const form = new FormData();
      form.append('font', input.files[0]);
      const data = await api('POST', '/api/branding/fonts/auto-upload', form, true);
      if (!data.success) { toast(data.error || 'فشل رفع الخط'); return; }
      const detected = data.detected || {};
      const familyName = detected.family || (input.files[0].name.split('/').pop() || 'خط مخصص').replace(/\.[^.]+$/, '').replace(/_(light|regular|medium|bold|black)$/i, '').replace(/_/g, ' ');
      await api('PUT', '/api/branding', { font_family: familyName, font_arabic: familyName });
      await loadTenantBranding();
      await loadTenantFonts();
      toast('تم التعرف على الخط تلقائيًا: ' + familyName + ' — ' + (detected.weight || 'regular'));
    }

    async function setTenantFontSelection(script, weight, fontId, skipReload) {
      const data = await api('PUT', '/api/branding/fonts', { script, weight, font_id: fontId || null });
      if (!data.success) { toast(data.error || 'فشل اختيار الخط'); return; }
      if (skipReload) return;
      await loadTenantBranding();
      await loadTenantFonts();
      toast('تم تحديث خط العرض');
    }

    async function uploadTenantFontVariant(script, weight, input) {
      if (!input.files || !input.files[0]) return;
      const form = new FormData();
      form.append('script', script);
      form.append('weight', weight);
      form.append('font', input.files[0]);
      const data = await api('POST', '/api/branding/fonts/upload', form, true);
      if (!data.success) { toast(data.error || 'فشل رفع الخط'); return; }
      const familyName = (input.files[0].name.split('/').pop() || 'خط مخصص').replace(/\.[^.]+$/, '').replace(/_(light|regular|medium|bold|black)$/i, '').replace(/_/g, ' ');
      await api('PUT', '/api/branding', { font_family: familyName, font_arabic: familyName });
      await loadTenantBranding();
      await loadTenantFonts();
      toast('تم رفع خط الشركة');
    }

    // Settings
    async function openTenantSettings() {
      showTenantPage('tenantSettingsPage');
      showTenantError('settingsError', '');
      const data = await api('GET', '/api/branding');
      if (!data.success || !data.branding) { toast('تعذر تحميل الإعدادات'); return; }
      tenantBranding = data.branding;
      const b = data.branding;
      setValue('settingsCompanyName', b.company_name || '');
      setValue('settingsTagline', b.tagline || '');
      setValue('settingsPrimaryColor', b.primary_color || '#07182C');
      setValue('settingsSecondaryColor', b.secondary_color || '#03E1CE');
      setValue('settingsAccentColor', b.accent_color || '#6DA3C3');
      setValue('settingsBackgroundColor', b.background_color || '#F4F9FC');
      setValue('settingsTextColor', b.text_color || '#333333');
      setValue('settingsFontFamily', b.font_family || 'The Sans Arabic');
      setValue('settingsDesignTemplate', b.design_template || 'modern');
      setValue('settingsCardStyle', b.card_style || 'bordered');
      setValue('settingsSlideRatio', b.slide_ratio || '16:9');
      setChecked('settingsHeaderEnabled', b.header_enabled);
      setChecked('settingsFooterEnabled', b.footer_enabled);
      setValue('settingsHeaderHeight', b.header_height || 56);
      setValue('settingsFooterHeight', b.footer_height || 36);
      setValue('settingsMinSlides', b.min_slides || 8);
      setValue('settingsDefaultSlideCount', b.default_slide_count || 16);
      setChecked('settingsLockSlideCount', b.lock_slide_count !== 0);
      setValue('settingsMoodboardCount', b.moodboard_count || 4);
      setValue('settingsDefaultMapType', b.default_map_type || 'auto');
      setValue('settingsMapStyleOverview', b.map_style_overview || 'auto');
      setValue('settingsMapStyleLandmarks', b.map_style_landmarks || 'auto');
      setValue('settingsMapStyleAccess', b.map_style_access || 'auto');
      setValue('settingsMapStyleCatchment', b.map_style_catchment || 'auto');
      setChecked('settingsDrawCompass', b.draw_compass !== 0);
      setChecked('settingsDrawInset', b.draw_inset !== 0);
      refreshSettingsColorFields();
      // previews
      const logoPreview = document.getElementById('settingsLogoPreview');
      if (logoPreview) logoPreview.innerHTML = b.logo_path ? '<img src="/tenant-assets/' + tenantUser.id + '/logo?t=' + Date.now() + '" alt="logo" style="max-height:120px">' : 'اضغط لرفع لوجو الشركة (PNG/JPG/WEBP)';
      renderSettingsWatermarkPreview(b);
      const refPreview = document.getElementById('settingsRefPreview');
      if (refPreview) refPreview.textContent = b.reference_image_path ? 'تم رفع صورة مرجعية' : 'اضغط لرفع صورة مرجعية للاستيل التصميمي';
      await loadTenantFonts();
    }

    function refreshSettingsColorFields() {
      document.querySelectorAll('.tenant-color-value[data-color-for]').forEach(el => {
        const input = document.getElementById(el.getAttribute('data-color-for'));
        el.textContent = input && input.value ? String(input.value).toUpperCase() : '';
      });
    }

    document.addEventListener('input', e => {
      const t = e.target;
      if (!t || t.type !== 'color' || !t.id) return;
      const el = document.querySelector('.tenant-color-value[data-color-for="' + t.id + '"]');
      if (el) el.textContent = String(t.value).toUpperCase();
    });

    function setValue(id, v) { const el = document.getElementById(id); if (el) el.value = v || ''; }
    function getValue(id) { const el = document.getElementById(id); return el ? el.value : ''; }
    function setChecked(id, v) { const el = document.getElementById(id); if (el) el.checked = Boolean(v); }
    function getChecked(id) { const el = document.getElementById(id); return el ? el.checked : false; }

    function collectSettings() {
      const fontFamily = getValue('settingsFontFamily');
      const isCustomFont = fontFamily === 'custom';
      const storedFontName = (tenantBranding && tenantBranding.font_family) || 'The Sans Arabic';
      const fontToSave = isCustomFont ? storedFontName : fontFamily;
      const settings = {
        company_name: getValue('settingsCompanyName'),
        tagline: getValue('settingsTagline'),
        primary_color: getValue('settingsPrimaryColor'),
        secondary_color: getValue('settingsSecondaryColor'),
        accent_color: getValue('settingsAccentColor'),
        background_color: getValue('settingsBackgroundColor'),
        text_color: getValue('settingsTextColor'),
        font_family: fontToSave,
        font_arabic: fontToSave,
        design_template: getValue('settingsDesignTemplate'),
        card_style: getValue('settingsCardStyle'),
        slide_ratio: getValue('settingsSlideRatio'),
        header_enabled: getChecked('settingsHeaderEnabled') ? 1 : 0,
        footer_enabled: getChecked('settingsFooterEnabled') ? 1 : 0,
        header_height: parseInt(getValue('settingsHeaderHeight') || '56', 10),
        footer_height: parseInt(getValue('settingsFooterHeight') || '36', 10),
        min_slides: parseInt(getValue('settingsMinSlides') || '8', 10),
        default_slide_count: parseInt(getValue('settingsDefaultSlideCount') || '16', 10),
        lock_slide_count: getChecked('settingsLockSlideCount') ? 1 : 0,
        moodboard_count: parseInt(getValue('settingsMoodboardCount') || '4', 10),
        default_map_type: getValue('settingsDefaultMapType') || 'auto',
        map_style_overview: getValue('settingsMapStyleOverview') || 'auto',
        map_style_landmarks: getValue('settingsMapStyleLandmarks') || 'auto',
        map_style_access: getValue('settingsMapStyleAccess') || 'auto',
        map_style_catchment: getValue('settingsMapStyleCatchment') || 'auto',
        draw_compass: getChecked('settingsDrawCompass') ? 1 : 0,
        draw_inset: getChecked('settingsDrawInset') ? 1 : 0,
      };
      // Only keep custom uploaded font when 'custom' is selected; otherwise clear the file path.
      if (isCustomFont) {
        if (tenantBranding && tenantBranding.font_file_path) {
          settings.font_file_path = tenantBranding.font_file_path;
        }
      } else {
        settings.font_file_path = null;
      }
      return settings;
    }

    async function saveTenantSettings() {
      showTenantError('settingsError', '');
      const updates = collectSettings();
      const data = await api('PUT', '/api/branding', updates);
      if (data.success) {
        tenantBranding = data.branding;
        await loadTenantBranding();
        toast('تم حفظ إعدادات الشركة');
      } else {
        showTenantError('settingsError', data.error || 'فشل الحفظ');
      }
    }

    async function applyTemplateToSettings() {
      const template = getValue('settingsDesignTemplate');
      const data = await api('POST', '/api/branding/template', { template });
      if (data.success) {
        tenantBranding = data.branding;
        openTenantSettings();
        toast('تم تطبيق القالب');
      } else {
        toast(data.error || 'فشل تطبيق القالب');
      }
    }

    async function handleLogoUpload(input) {
      if (!input.files || !input.files[0]) return;
      const form = new FormData();
      form.append('file', input.files[0]);
      const data = await api('POST', '/api/upload/logo', form, true);
      if (data.success) {
        await loadTenantBranding();
        const preview = document.getElementById('settingsLogoPreview');
        if (preview) preview.innerHTML = '<img src="/tenant-assets/' + tenantUser.id + '/logo?r=' + Date.now() + '" alt="logo">';
        toast('تم رفع اللوجو');
      } else {
        toast(data.error || 'فشل رفع اللوجو');
      }
    }

    function renderSettingsWatermarkPreview(branding) {
      const current = branding || tenantBranding || {};
      const preview = document.getElementById('settingsWatermarkPreview');
      const deleteButton = document.getElementById('settingsWatermarkDeleteButton');
      const uploadButton = document.getElementById('settingsWatermarkUploadButton');
      if (preview) {
        preview.replaceChildren();
        if (current.watermark_path) {
          const image = document.createElement('img');
          const separator = String(current.watermark_path).includes('?') ? '&' : '?';
          image.src = current.watermark_path + separator + 't=' + Date.now();
          image.alt = 'العلامة المائية';
          preview.appendChild(image);
        } else {
          preview.textContent = 'لا توجد علامة مائية';
        }
      }
      if (deleteButton) deleteButton.disabled = !current.watermark_path;
      if (uploadButton) uploadButton.textContent = current.watermark_path ? 'استبدال العلامة المائية' : 'رفع علامة مائية';
    }

    function setWatermarkSettingsBusy(busy) {
      const uploadButton = document.getElementById('settingsWatermarkUploadButton');
      const deleteButton = document.getElementById('settingsWatermarkDeleteButton');
      const input = document.getElementById('watermarkFileInput');
      if (uploadButton) uploadButton.disabled = !!busy;
      if (deleteButton) deleteButton.disabled = !!busy || !(tenantBranding && tenantBranding.watermark_path);
      if (input) input.disabled = !!busy;
    }

    async function handleWatermarkUpload(input) {
      if (!input.files || !input.files[0]) return;
      const form = new FormData();
      form.append('file', input.files[0]);
      let completion = 'تعذر رفع العلامة المائية';
      setWatermarkSettingsBusy(true);
      showLoader('رفع العلامة المائية', 'جاري رفع الملف...', 10, { reset: true, maxProgress: 90 });
      try {
        const data = await api('POST', '/api/upload/watermark', form, true);
        if (!data.success) {
          toast(data.error || completion);
          return;
        }
        updateLoaderProgress(82, 'جاري تحديث الهوية البصرية...');
        tenantBranding = data.branding || { ...(tenantBranding || {}), watermark_path: data.watermarkPath };
        renderSettingsWatermarkPreview(tenantBranding);
        completion = 'تم رفع العلامة المائية';
        toast(completion);
      } finally {
        input.value = '';
        setWatermarkSettingsBusy(false);
        hideLoader(completion);
      }
    }

    async function deleteTenantWatermark() {
      if (!(tenantBranding && tenantBranding.watermark_path)) return;
      let completion = 'تعذر حذف العلامة المائية';
      setWatermarkSettingsBusy(true);
      showLoader('حذف العلامة المائية', 'جاري تحديث الهوية البصرية...', 15, { reset: true, maxProgress: 90 });
      try {
        const data = await api('DELETE', '/api/upload/watermark');
        if (!data.success) {
          toast(data.error || completion);
          return;
        }
        tenantBranding = data.branding || { ...(tenantBranding || {}), watermark_path: null };
        renderSettingsWatermarkPreview(tenantBranding);
        completion = 'تم حذف العلامة المائية';
        toast(completion);
      } finally {
        setWatermarkSettingsBusy(false);
        hideLoader(completion);
      }
    }

    async function handleRefUpload(input) {
      if (!input.files || !input.files[0]) return;
      const form = new FormData();
      form.append('file', input.files[0]);
      const data = await api('POST', '/api/upload/reference-image', form, true);
      if (data.success) {
        const preview = document.getElementById('settingsRefPreview');
        if (preview) preview.textContent = 'تم رفع الصورة المرجعية';
        toast('تم رفع الصورة المرجعية');
      } else {
        toast(data.error || 'فشل رفع الصورة');
      }
    }

    async function handleFontUpload(input) {
      if (!input.files || !input.files[0]) return;
      const file = input.files[0];
      const ext = file.name.split('.').pop().toLowerCase();
      if (!['ttf', 'otf', 'woff', 'woff2'].includes(ext)) {
        toast('الصيغة غير مدعومة. استخدم TTF أو OTF أو WOFF');
        return;
      }
      const form = new FormData();
      form.append('font', file);
      const data = await api('POST', '/api/branding/font', form, true);
      if (data.success) {
        tenantBranding.font_file_path = data.font_file_path || data.font_url;
        tenantBranding.font_family = data.font_name;
        setValue('settingsFontFamily', 'custom');
        const preview = document.getElementById('settingsFontPreview');
        if (preview) preview.innerHTML = '<span>تم رفع الخط:</span> ' + escapeHtml(file.name);
        await loadTenantFontCss();
        toast('تم رفع الخط بنجاح');
      } else {
        toast(data.error || 'فشل رفع الخط');
      }
    }

    function toggleFontUpload(value) {
      const uploadInput = document.getElementById('settingsFontUpload');
      const preview = document.getElementById('settingsFontPreview');
      if (uploadInput) {
        uploadInput.style.display = value === 'custom' ? 'block' : 'none';
      }
      if (preview && value !== 'custom') {
        preview.textContent = '';
      }
    }

    async function analyzeReferenceImage() {
      toast('جاري تحليل الصورة المرجعية...');
      const data = await api('POST', '/api/branding/analyze-reference', {});
      if (data.success) {
        tenantBranding = data.branding;
        openTenantSettings();
        toast('تم تحليل الصورة وتطبيق الألوان');
      } else {
        toast(data.error || 'فشل التحليل');
      }
    }

    // A text monogram stands in for a missing logo: the product carries no icons or emojis.
    function teamMonogramHtml(name, size) {
      const letter = String(name || '').trim().charAt(0) || '—';
      return '<div style="width:' + size + 'px;height:' + size + 'px;border-radius:10px;background:#f2f4f7;' +
        'display:flex;align-items:center;justify-content:center;flex:none;font-weight:900;color:#6f7780;' +
        'font-size:' + Math.round(size / 2.4) + 'px">' + escapeHtml(letter) + '</div>';
    }