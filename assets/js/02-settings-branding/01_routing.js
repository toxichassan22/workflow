/* 02-settings-branding.js - index.html lines 8354-9747, shared global scope, classic scripts in order */
    const TENANT_ROUTE_PAGES = Object.fromEntries(Object.entries(TENANT_PAGE_ROUTES).map(([page, route]) => [route, page]));

    // Role-prefixed URLs: super-admin lives under /superadmin, each company under
    // /c/<slug> where slug is the stable latin subdomain/username (never the Arabic
    // company name or a user name). /app/* stays as a legacy alias that resolves
    // to the canonical address instead of breaking bookmarks.
    const TENANT_ROUTE_SUFFIXES = {
      tenantDashboardPage: 'dashboard',
      tenantProjectPage: 'projects/new',
      tenantProjectPresentationsPage: 'projects/presentations',
      tenantVisualConceptPage: 'projects/visual-concept',
      tenantGenerationPage: 'projects/generation',
      tenantSlidesPage: 'presentations/current',
      tenantPresentationsPage: 'presentations',
      tenantSettingsPage: 'settings',
      tenantTeamPage: 'settings/team',
      tenantFieldsPage: 'settings/fields',
      tenantUsersPage: 'settings/users',
      tenantTrainingPage: 'settings/training',
      tenantAIRulesPage: 'settings/ai-rules',
      tenantApprovalsPage: 'approvals',
      tenantLandloomOpsPage: 'operations',
      tenantAdminPage: 'admin',
      tenantCompaniesPage: 'admin/companies',
      tenantAdminRechargePage: 'admin/recharges',
      tenantAdminTicketsPage: 'admin/tickets',
      tenantAdminPlatformPage: 'admin/platform'
    };
    const TENANT_SUFFIX_PAGES = Object.fromEntries(Object.entries(TENANT_ROUTE_SUFFIXES).map(([page, suffix]) => [suffix, page]));

    function tenantUrlSlug() {
      const raw = (tenantUser && (tenantUser.slug || tenantUser.subdomain || tenantUser.username)) || '';
      const slug = String(raw).trim().toLowerCase().replace(/[_.]+/g, '-').replace(/[^a-z0-9-]+/g, '').replace(/-{2,}/g, '-').replace(/^-+|-+$/g, '');
      return /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(slug) ? slug : '';
    }

    function tenantPathPrefix() {
      if (tenantUser && tenantUser.isAdmin) return '/superadmin';
      const slug = tenantUrlSlug();
      return slug ? '/c/' + slug : '/app';
    }

    function tenantCanonicalRoute(pageId) {
      const suffix = TENANT_ROUTE_SUFFIXES[pageId];
      if (!suffix) return null;
      if (tenantUser && tenantUser.isAdmin) {
        return pageId === 'tenantAdminPage' ? '/superadmin/admin' : '/superadmin/' + suffix;
      }
      return tenantPathPrefix() + '/' + suffix;
    }

    function resolveTenantRoutePath(path) {
      const clean = String(path || '/').replace(/\/+$/, '') || '/';
      if (clean === '/superadmin') return { pageId: 'tenantAdminPage', prefix: '/superadmin', urlSlug: '' };
      if (clean.startsWith('/superadmin/')) {
        const suffix = clean.slice('/superadmin/'.length);
        const pageId = TENANT_SUFFIX_PAGES[suffix];
        return pageId ? { pageId, prefix: '/superadmin', urlSlug: '' } : null;
      }
      const companyMatch = clean.match(/^\/c\/([^\/]+)(\/(.*))?$/);
      if (companyMatch) {
        const urlSlug = companyMatch[1].toLowerCase();
        const suffix = (companyMatch[3] || '').replace(/\/+$/, '');
        if (!suffix) return { pageId: 'tenantDashboardPage', prefix: '/c/' + urlSlug, urlSlug };
        const pageId = TENANT_SUFFIX_PAGES[suffix];
        return pageId ? { pageId, prefix: '/c/' + urlSlug, urlSlug } : null;
      }
      return null;
    }

    const TENANT_ADMIN_ONLY_PAGES = new Set([
      'tenantAdminPage', 'tenantCompaniesPage', 'tenantAdminRechargePage',
      'tenantAdminTicketsPage', 'tenantAdminPlatformPage'
    ]);

    function enforceTenantRouteGuard(pageId, urlSlug) {
      if (!tenantUser) return pageId;
      const isSagAdmin = !!tenantUser.isAdmin;
      if (urlSlug && !isSagAdmin && urlSlug !== tenantUrlSlug() && tenantUrlSlug()) return 'TENANT_SLUG_MISMATCH';
      if (TENANT_ADMIN_ONLY_PAGES.has(pageId) && !isSagAdmin) return 'TENANT_ADMIN_FORBIDDEN';
      return pageId;
    }

    function canonicalizeTenantUrl(pageId, replace) {
      const canonical = (typeof tenantCanonicalRoute === 'function') ? tenantCanonicalRoute(pageId) : null;
      const current = window.location.pathname;
      if (!canonical || current === canonical) return;
      const resolved = (typeof resolveTenantRoutePath === 'function') ? resolveTenantRoutePath(current) : null;
      const legacy = !resolved && !!(TENANT_PAGE_ROUTES[pageId] && current === TENANT_PAGE_ROUTES[pageId]);
      if (replace || legacy || (resolved && resolved.prefix !== tenantPathPrefix())) {
        const state = buildTenantNavigationState(pageId, {});
        window.history.replaceState(state, '', canonical + window.location.search);
      }
    }

    function getBrowserNavigationState() {
      const query = new URLSearchParams(window.location.search);
      const state = history.state && typeof history.state === 'object' ? history.state : {};
      return {
        ...state,
        draftId: state.draftId || query.get('draftId') || null,
        activeSection: state.activeSection || query.get('section') || null,
        railTab: state.railTab || query.get('rail') || localStorage.getItem('tgrTab') || 'nav'
      };
    }

    function tenantNavigationUrl(pageId, state) {
      const canonical = (typeof tenantCanonicalRoute === 'function') ? tenantCanonicalRoute(pageId) : null;
      const route = canonical || TENANT_PAGE_ROUTES[pageId] || window.location.pathname;
      const query = new URLSearchParams();
      if (pageId === 'tenantProjectPage' && state.activeSection) query.set('section', state.activeSection);
      if (pageId === 'tenantProjectPresentationsPage' && state.draftId) query.set('draftId', state.draftId);
      if (state.railTab === 'inputs') query.set('rail', 'inputs');
      const queryString = query.toString();
      return queryString ? route + '?' + queryString : route;
    }

    function syncTenantBrowserHistory(pageId, overrides = {}, replace = false) {
      const state = buildTenantNavigationState(pageId, overrides);
      const url = tenantNavigationUrl(pageId, state);
      const current = window.location.pathname + window.location.search;
      if (replace || current !== url) {
        const method = replace ? 'replaceState' : 'pushState';
        window.history[method](state, '', url);
      }
      saveTenantNavigationState(pageId, overrides);
    }

    function showTenantPage(pageId, fromHistory = false) {
      if (!fromHistory && (TENANT_PAGE_ROUTES[pageId] || (typeof tenantCanonicalRoute === 'function' && tenantCanonicalRoute(pageId)))) syncTenantBrowserHistory(pageId);
      document.querySelectorAll('.tenant-page').forEach(el => el.classList.remove('active'));
      // Admin modals live outside the page sections (position:fixed needs a
      // visible ancestor), so page switches have to close them explicitly.
      ['sagTenantModal', 'sagCompanyCreateModal'].forEach(modalId => {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'none';
      });
      const el = document.getElementById(pageId);
      if (el) el.classList.add('active');
      updateTenantChrome(pageId);
      closeTenantSidebar();
      closeTenantBellPanel();

      const appPage = document.getElementById('tenantAppPage');
      if (appPage) {
        if (pageId === 'tenantSlidesPage') {
          appPage.classList.add('preview-active');
        } else {
          appPage.classList.remove('preview-active');
        }
      }

      saveTenantNavigationState(pageId);
      if (fromHistory) {
        const browserState = getBrowserNavigationState();
        if (browserState.railTab) setGlobalRailTab(browserState.railTab, true);
        if (pageId === 'tenantProjectPage' && browserState.activeSection) showSection(browserState.activeSection, true);
      }

      if (pageId === 'tenantDashboardPage') loadDashboard();
      renderWorkflowStageSidebars(pageId);
      refreshGlobalRail();
      updatePresentationUndoButtons();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    window.addEventListener('popstate', () => {
      // The bare `tenantToken` variable is null on every page load: the session is restored from
      // localStorage through getTenantToken(). Guarding on the variable made Back change the
      // address bar and leave the screen untouched.
      if (!getTenantToken()) return;
      const path = window.location.pathname;
      const resolved = (typeof resolveTenantRoutePath === 'function') ? resolveTenantRoutePath(path) : null;
      const pageId = (resolved && resolved.pageId) || TENANT_ROUTE_PAGES[path];
      if (resolved && typeof enforceTenantRouteGuard === 'function') {
        const guard = enforceTenantRouteGuard(pageId, resolved.urlSlug);
        if (guard === 'TENANT_SLUG_MISMATCH' || guard === 'TENANT_ADMIN_FORBIDDEN') {
          showTenantPage('tenantDashboardPage', true);
          syncTenantBrowserHistory('tenantDashboardPage', {}, true);
          return;
        }
        if (typeof canonicalizeTenantUrl === 'function') canonicalizeTenantUrl(pageId, true);
      }
      if (pageId) {
        if (pageId === 'tenantProjectPresentationsPage') {
          const draftId = new URLSearchParams(window.location.search).get('draftId');
          loadProjectPresentationsPage(draftId || currentProjectPresentationsDraftId());
        } else {
          openTenantPageById(pageId);
        }
        return;
      }
      // "/" and any unmapped path used to fall through here, leaving the view on the old page
      // while the address bar said something else — so the next Back left the site entirely.
      // Land on the dashboard and put a real route back in the bar instead.
      showTenantPage('tenantDashboardPage', true);
      syncTenantBrowserHistory('tenantDashboardPage', {}, true);
    });

    // Pages whose content is loaded by a dedicated opener. Used by popstate so
    // Back/Forward lands on a populated page, not an empty shell.
    const TENANT_PAGE_OPENERS = {
      tenantAdminPage: 'openTenantAdmin',
      tenantCompaniesPage: 'openTenantCompanies',
      tenantAdminRechargePage: 'openAdminRechargePage',
      tenantAdminTicketsPage: 'openAdminTicketsPage',
      tenantAdminPlatformPage: 'openAdminPlatformPage',
      tenantLandloomOpsPage: 'openLandloomOpsPage',
      tenantPresentationsPage: 'openTenantPresentations',
      tenantSettingsPage: 'openTenantSettings',
      tenantTeamPage: 'openTenantTeam',
      tenantFieldsPage: 'openTenantFields',
      tenantUsersPage: 'openTenantUsers',
      tenantTrainingPage: 'openTenantTraining',
      tenantAIRulesPage: 'openTenantAIRules',
      tenantApprovalsPage: 'openTenantApprovals',
      tenantNotificationsPage: 'openNotificationsPage'
    };

    function openTenantPageById(pageId) {
      if (pageId === 'tenantProjectPage' && tenantProjectMode === 'presentation') {
        navigateTenantWorkflow('tenantProjectPage');
        return;
      }
      const name = TENANT_PAGE_OPENERS[pageId];
      const opener = name && window[name];
      if (typeof opener === 'function') {
        // The operations entry remembers which sub-tab was showing; every
        // other opener takes no arguments.
        opener(pageId === 'tenantLandloomOpsPage' ? getBrowserNavigationState().opsTab : undefined);
        return;
      }
      showTenantPage(pageId, true);
    }

    const TENANT_WORKFLOW_ITEMS = [
      { pageId: 'tenantProjectPage', label: 'بيانات المشروع' },
      { pageId: 'tenantSlidesPage', label: 'صفحة التصميم والمعاينة' }
    ];

    async function navigateTenantWorkflow(pageId) {
      if (pageId === 'tenantProjectPage') {
        showTenantPage(pageId);
        if (typeof tenantProjectMode !== 'undefined' && tenantProjectMode === 'presentation') {
          const draftId = tenantProjectData?.draftId || tenantProjectData?.draft_id;
          if (draftId && typeof openProjectDraftById === 'function') {
            await openProjectDraftById(draftId);
          }
        }
        return;
      }
      if (pageId === 'tenantSlidesPage') {
        if (typeof renderTenantSlides === 'function') renderTenantSlides();
        showTenantPage('tenantSlidesPage');
        return;
      }
      if (pageId === 'tenantVisualConceptPage') {
        if (tenantProjectMode === 'presentation') {
          const draftId = tenantProjectData?.draftId || tenantProjectData?.draft_id;
          if (draftId && typeof openProjectDraftById === 'function') {
            await openProjectDraftById(draftId);
            return openTenantVisualConceptPage();
          }
        }
        return openTenantVisualConceptPage();
      }
    }

    function currentProjectPresentationsDraftId() {
      return new URLSearchParams(window.location.search).get('draftId')
        || tenantProjectData?.draftId || tenantProjectData?.draft_id || '';
    }

    function openProjectPresentationsTab() {
      const draftId = tenantProjectData?.draftId || tenantProjectData?.draft_id || '';
      if (!draftId) {
        toast('يجب حفظ المشروع قبل عرض عروضه السابقة');
        return;
      }
      loadProjectPresentationsPage(draftId);
    }

    function closeProjectPresentationsTab() {
      navigateTenantWorkflow('tenantProjectPage');
    }

    async function loadProjectPresentationsPage(draftId = currentProjectPresentationsDraftId()) {
      const host = document.getElementById('projectPresentationsPageList');
      if (!host) return;
      showTenantPage('tenantProjectPresentationsPage', true);
      if (!draftId) {
        host.innerHTML = '<p class="tenant-hint">ملف المشروع غير محدد.</p>';
        return;
      }
      const filters = {
        draftId: String(draftId),
        search: document.getElementById('projectPresentationsSearch')?.value?.trim() || '',
        status: document.getElementById('projectPresentationsStatus')?.value || '',
        from: document.getElementById('projectPresentationsFrom')?.value || '',
        to: document.getElementById('projectPresentationsTo')?.value || ''
      };
      const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
      host.innerHTML = '<p class="tenant-hint">جاري تحميل العروض...</p>';
      // The page only needs the draft's title. When the draft is already open its
      // row is in memory, and otherwise the lightweight summaries list answers it —
      // a full draft GET here re-downloaded megabytes of slides for one string.
      const draftOpenInMemory = tenantProjectData && String(tenantProjectData.draftId || '') === String(draftId);
      const [response, draftsResponse] = await Promise.all([
        apiWithTimeout('GET', '/api/presentations?' + query.toString(), null, 25000).catch(() => ({ success: false })),
        draftOpenInMemory
          ? Promise.resolve(null)
          : api('GET', '/api/project-drafts?limit=200').catch(() => ({ success: false }))
      ]);
      if (!response || !response.success) {
        renderListLoadError(host, 'loadProjectPresentationsPage()');
        return;
      }
      const title = draftOpenInMemory
        ? String((tenantProjectDraftApproval && tenantProjectDraftApproval.title)
          || tenantProjectData.project_name || tenantProjectData.projectName || '')
        : String(((draftsResponse && draftsResponse.drafts) || [])
          .find(item => String(item.id) === String(draftId))?.title || '');
      const titleNode = document.getElementById('projectPresentationsPageTitle');
      if (titleNode) titleNode.innerHTML = title ? '<span>العروض السابقة</span> — ' + escapeHtml(title) : 'العروض السابقة';
      const presentations = response?.success && Array.isArray(response.presentations)
        ? response.presentations.slice().sort((a, b) => new Date(b.updatedAt || b.createdAt || 0) - new Date(a.updatedAt || a.createdAt || 0))
        : [];
      // Render the groups from the presentations query alone, then patch the
      // per-file cost lines when usage-totals answers. Waiting for the totals
      // kept this list on its loader while the server reconciled costs.
      const renderPresentationCard = (item, itemCost, itemReconcile) => {
        const date = (item.updatedAt || item.createdAt || '').slice(0, 16).replace('T', ' ');
        const itemMapsCost = Number(itemCost?.maps_cost_sar) || 0;
        return '<div class="tenant-presentation-card" data-presentation-id="' + item.id + '"><div><h3>' + escapeHtml(item.title || 'عرض بدون عنوان') + '</h3>' +
          '<div class="meta"><span>' + (item.slideCount || 0) + '</span> <span>شريحة</span> | <span>النسخة</span> <span>' + (item.revision || 0) + '</span> | ' + escapeHtml(date) + ' | <span>التكلفة:</span> ' + (itemCost ? formatUsageCost(itemCost.cost_sar || 0) + (itemMapsCost > 0 ? ' (<span>خرائط:</span> ' + formatUsageCost(itemMapsCost) + ')' : '') + (itemReconcile ? ' | <span>' + itemReconcile + '</span>' : '') : '—') + '</div></div>' +
          '<div class="tenant-actions"><button type="button" class="btn primary small" onclick="openExistingPresentation(\'' + item.id + '\')">فتح العرض</button>' +
          '<button type="button" class="btn ghost small" onclick="showEditLog(\'' + item.id + '\')">سجل التعديلات والنسخ</button>' +
          '<button type="button" class="btn ghost small" onclick="showDownloadsLibraryModal(\'' + item.id + '\')">مكتبة التنزيلات</button></div></div>';
      };
      const renderPresentationGroups = (costByPresentation, reconcileByPresentation) => {
        const groups = [
          { key: 'draft', label: 'مسودة', items: presentations.filter(item => !['pending_approval', 'approved'].includes(item.status)) },
          { key: 'pending_approval', label: 'بانتظار التعميد', items: presentations.filter(item => item.status === 'pending_approval') },
          { key: 'approved', label: 'معتمد', items: presentations.filter(item => item.status === 'approved') }
        ].filter(group => group.items.length);
        return groups.length ? groups.map(group =>
          '<section style="margin:0 0 22px"><h3 style="margin-bottom:10px;color:var(--p)">' + group.label + '</h3>' +
          group.items.map(item => renderPresentationCard(
            item, costByPresentation[item.id],
            aiReconcileStatusText(reconcileByPresentation[item.id]))).join('') + '</section>'
        ).join('') : '<p class="tenant-hint">لا توجد عروض سابقة مطابقة.</p>';
      };
      const presStamp = String(Date.now()) + Math.random().toString(16).slice(2);
      host.dataset.presentationsStamp = presStamp;
      host.innerHTML = renderPresentationGroups({}, {});
      const presentationIds = presentations.map(item => item.id).filter(Boolean);
      if (presentationIds.length) {
        const totalsData = await apiWithTimeout('GET', '/api/usage-totals?presentationIds=' + encodeURIComponent(presentationIds.join(',')), null, 25000).catch(() => null);
        if (host.dataset.presentationsStamp !== presStamp || !document.contains(host)) return;
        let costByPresentation = {};
        let reconcileByPresentation = {};
        if (totalsData?.success && totalsData.presentations) costByPresentation = totalsData.presentations;
        if (totalsData?.reconcile_by_scope?.by_presentation) reconcileByPresentation = totalsData.reconcile_by_scope.by_presentation;
        if (!totalsData?.success) return;
        presentations.forEach(item => {
          const node = host.querySelector('[data-presentation-id="' + item.id + '"]');
          if (!node) return;
          const next = renderPresentationCard(item, costByPresentation[item.id],
            aiReconcileStatusText(reconcileByPresentation[item.id]));
          if (node.outerHTML !== next) node.outerHTML = next;
        });
      }
    }

    function appendWorkflowNavigation(sidebar, activePageId, includeProject) {
      if (!sidebar) return;
      if (sidebar.childElementCount) {
        const divider = document.createElement('div');
        divider.className = 'workflow-sidebar-divider';
        sidebar.appendChild(divider);
      }
      const title = document.createElement('p');
      title.className = 'project-form-sidebar-title';
      title.textContent = includeProject ? 'أقسام العرض' : 'التوليد والتصميم';
      sidebar.appendChild(title);

      if (!includeProject && hasPermission('create_presentation')) {
        const genButton = document.createElement('button');
        genButton.type = 'button';
        genButton.className = 'project-section-nav-item workflow-sidebar-action';
        genButton.style.cssText = 'background:#1a4d6f;color:#fff;font-weight:700;margin-bottom:6px;';
        genButton.textContent = 'توليد العرض';
        genButton.addEventListener('click', () => directGenerateProposalFile());
        sidebar.appendChild(genButton);
      }

      if (!includeProject && hasPermission('view_presentations')) {
        const previousButton = document.createElement('button');
        previousButton.type = 'button';
        previousButton.className = 'project-section-nav-item';
        previousButton.style.cssText = 'margin-top:6px;font-weight:700;';
        previousButton.textContent = 'العروض السابقة';
        previousButton.addEventListener('click', openProjectPresentationsTab);
        sidebar.appendChild(previousButton);
      }

      const items = [...TENANT_WORKFLOW_ITEMS];

      items
        .filter(item => includeProject || item.pageId !== 'tenantProjectPage')
        .forEach(item => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'project-section-nav-item';
          button.textContent = item.label;
          button.classList.toggle('active', item.pageId === activePageId);
          if (item.pageId === activePageId) button.setAttribute('aria-current', 'page');
          button.addEventListener('click', () => navigateTenantWorkflow(item.pageId));
          sidebar.appendChild(button);
        });
    }

    function renderWorkflowStageSidebars(activePageId) {
      document.querySelectorAll('.workflow-stage-sidebar').forEach(sidebar => {
        sidebar.innerHTML = '';
        appendWorkflowNavigation(sidebar, activePageId, true);
      });
    }

    /* ===== Tenant Global Rail ===== */
    const TGR_STAGES = [
      { id: 'tenantProjectPage', label: 'بيانات المشروع' },
      { id: 'tenantSlidesPage', label: 'معاينة الشرائح' }
    ];

    const TGR_HIDE_ON = [
      'tenantAuthPage',
      'tenantDashboardPage',
      'tenantSettingsPage',
      'tenantFieldsPage',
      'tenantPresentationsPage',
      'tenantProjectPresentationsPage',
      'tenantUsersPage',
      'tenantTrainingPage',
      'tenantAIRulesPage',
      'tenantApprovalsPage',
      'tenantAdminPage'
    ];

    function tgrCurrentPageId() {
      const el = document.querySelector('.tenant-page.active') ||
        Array.from(document.querySelectorAll('.tenant-page')).find(p => p.offsetParent !== null);
      return el ? el.id : null;
    }

    function renderGlobalRailNav() {
      const host = document.getElementById('tgrNav');
      if (!host) return;
      const cur = tgrCurrentPageId();
      host.innerHTML = TGR_STAGES.map(s => {
        const exists = !!document.getElementById(s.id);
        const isCurrent = s.id === cur;
        return '<button class="tgr-stage' + (isCurrent ? ' current' : '') + '"' +
          (exists ? '' : ' disabled') +
          ' onclick="tgrGoStage(\'' + s.id + '\')"><span>' + s.label + '</span></button>';
      }).join('');
    }

    function tgrGoStage(pageId) {
      if (typeof navigateTenantWorkflow === 'function') {
        navigateTenantWorkflow(pageId);
      } else if (typeof showTenantPage === 'function') {
        showTenantPage(pageId);
      } else {
        document.querySelectorAll('.tenant-page').forEach(p => p.classList.remove('active'));
        const t = document.getElementById(pageId);
        if (t) t.classList.add('active');
      }
      refreshGlobalRail();
    }

    function setGlobalRailTab(tab, fromHistory = false) {
      tab = tab === 'inputs' ? 'inputs' : 'nav';
      document.querySelectorAll('[data-tgr-tab]').forEach(b =>
        b.classList.toggle('active', b.getAttribute('data-tgr-tab') === tab));
      const navBody = document.getElementById('tgrNav');
      const inputsBody = document.getElementById('tgrInputs');
      if (navBody) navBody.classList.toggle('tgr-hidden', tab !== 'nav');
      if (inputsBody) inputsBody.classList.toggle('tgr-hidden', tab !== 'inputs');
      if (tab === 'inputs') renderGlobalRailInputs();
      localStorage.setItem('tgrTab', tab);
      if (!fromHistory) {
        const pageId = tgrCurrentPageId() || 'tenantDashboardPage';
        syncTenantBrowserHistory(pageId, { railTab: tab });
      }
    }

    function toggleGlobalRail() {
      const collapsed = document.body.classList.toggle('tgr-collapsed');
      localStorage.setItem('tgrCollapsed', collapsed ? '1' : '0');
      setTimeout(tgrRefit, 220);
    }

    function tgrRefit() {
      if (typeof autoFitSlideContent !== 'function') return;
      // Resize slide preview stages so they fit inside the remaining width when the rail is open.
      document.querySelectorAll('.tenant-slide-stage').forEach(st => {
        const canvas = autoFitSlideContent(st) || { width: 1280, height: 720 };
        const main = st.closest('.ge-main') || st.closest('#tenantSlidesMain');
        const maxW = main ? main.clientWidth - 32 : 1280;
        const minStageW = window.innerWidth <= 900 ? 280 : 480;
        const stageW = Math.min(1280, Math.max(minStageW, maxW));
        st.style.setProperty('--stage-w', stageW + 'px');
        st.style.setProperty('--stage-h', (stageW * canvas.height / canvas.width).toFixed(2) + 'px');
        st.style.setProperty('--slide-scale', (stageW / canvas.width).toFixed(4));
      });
      document.querySelectorAll('.ge-slide-stage').forEach(st => autoFitSlideContent(st));
    }

    function renderGlobalRailInputs() {
      const host = document.getElementById('tgrInputs');
      const form = document.getElementById('tenantProjectForm');
      if (!host) return;
      if (!form) { host.innerHTML = '<div class="tgr-empty">افتح بيانات المشروع أولاً</div>'; return; }

      const tgrOpen = new Set();
      host.querySelectorAll('details').forEach(d => {
        const k = d.querySelector('summary')?.textContent || '';
        if (d.open && k) tgrOpen.add(k);
      });

      let html = '';
      const groups = form.querySelectorAll('.tenant-form-section, fieldset');
      (groups.length ? groups : [form]).forEach(sec => {
        const t = sec.querySelector('.tenant-section-title, h3, h4, legend');
        const title = (t && t.textContent.trim()) || 'بيانات';
        let rows = '';
        sec.querySelectorAll('input, select, textarea').forEach(el => {
          if (el.type === 'file' || el.type === 'hidden'
            || el.closest('.dynamic-off,.conditional-off,.hidden,[hidden]')) return;
          const fieldId = el.dataset.key || el.id;
          if (!fieldId) return;
          const fieldWrap = el.closest('.tenant-field');
          const lab = fieldWrap ? fieldWrap.querySelector('label') : null;
          const label = (lab && lab.textContent.trim()) || el.name || fieldId;
          let val;
          if (el.type === 'checkbox') val = el.checked ? 'نعم' : 'لا';
          else if (el.tagName === 'SELECT') val = (el.options[el.selectedIndex] || {}).text || '—';
          else val = el.value || '—';
          val = String(val).replace(/\s+/g, ' ').trim().slice(0, 32) || '—';
          rows += '<div class="tgr-row"><span title="' + escapeHtml(label) + '">' + escapeHtml(label) + ': <b>' + escapeHtml(val) +
            '</b></span><button type="button" class="tgr-edit" data-field="' + escapeHtml(fieldId) + '">تعديل</button></div>';
        });
        const openAttr = (tgrOpen.size === 0 || tgrOpen.has(title)) ? ' open' : '';
        if (rows) html += '<details' + openAttr + '><summary>' + escapeHtml(title) + '</summary>' + rows + '</details>';
      });
      host.innerHTML = html || '<div class="tgr-empty">لا توجد مدخلات بعد</div>';
    }

    function tgrGoField(fieldId) {
      tgrGoStage('tenantProjectPage');
      setTimeout(() => {
        const el = document.querySelector('#tenantProjectForm [data-key="' + fieldId + '"]') ||
          document.getElementById(fieldId);
        if (!el) return;
        const det = el.closest('details');
        if (det) det.open = true;
        const sec = el.closest('.tenant-form-section');
        if (sec && sec.dataset.section) showSection(sec.dataset.section);
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.focus({ preventScroll: true });
        el.style.outline = '2px solid #C4A35A';
        setTimeout(() => { el.style.outline = ''; }, 1300);
      }, 80);
    }

    function refreshGlobalRail() {
      const cur = tgrCurrentPageId();
      const show = !!cur && TGR_HIDE_ON.indexOf(cur) === -1;
      document.body.classList.toggle('tgr-on', show);
      if (!show) return;
      renderGlobalRailNav();
      const inputsBody = document.getElementById('tgrInputs');
      if (inputsBody && !inputsBody.classList.contains('tgr-hidden')) renderGlobalRailInputs();
      if (cur === 'tenantSlidesPage') setTimeout(tgrRefit, 220);
    }

    function initGlobalRail() {
      if (localStorage.getItem('tgrCollapsed') === '1') document.body.classList.add('tgr-collapsed');
      const inputsHost = document.getElementById('tgrInputs');
      if (inputsHost) {
        inputsHost.addEventListener('click', e => {
          const b = e.target.closest('.tgr-edit');
          if (b && b.dataset.field) tgrGoField(b.dataset.field);
        });
      }
      setGlobalRailTab(localStorage.getItem('tgrTab') || 'nav', true);
      refreshGlobalRail();
      if (!window._tgrResizeBound) {
        window.addEventListener('resize', tgrRefit);
        window._tgrResizeBound = true;
      }
    }

    const TENANT_PAGE_CHROME = Object.freeze({
      tenantDashboardPage: ['page.dashboard', 'لوحة التحكم'],
      tenantProjectPage: ['page.project_new', 'مشروع جديد'],
      tenantProjectPresentationsPage: ['page.project_presentations', 'عروض المشروع'],
      tenantVisualConceptPage: ['page.visual_concept', 'التصور البصري'],
      tenantGenerationPage: ['page.generation', 'تجهيز العرض'],
      tenantSlidesPage: ['page.presentation_editor', 'محرر العرض'],
      tenantPresentationsPage: ['page.projects', 'المشاريع'],
      tenantSettingsPage: ['page.company_settings', 'إعدادات الشركة'],
      tenantTeamPage: ['page.team', 'فريق التطوير'],
      tenantFieldsPage: ['page.fields', 'الحقول'],
      tenantUsersPage: ['page.staff', 'الموظفون'],
      tenantTrainingPage: ['page.training', 'بيانات التدريب'],
      tenantAIRulesPage: ['page.ai_rules', 'قواعد AI'],
      tenantApprovalsPage: ['page.approvals', 'تعميد العروض'],
      tenantNotificationsPage: ['page.notifications', 'الإشعارات'],
      tenantAdminPage: ['page.admin_dashboard', 'لوحة المدير'],
      tenantCompaniesPage: ['page.companies', 'إدارة الشركات'],
      tenantAdminRechargePage: ['page.recharge_requests', 'طلبات الشحن'],
      tenantAdminTicketsPage: ['page.support_desk', 'الدعم الفني'],
      tenantAdminPlatformPage: ['page.platform_settings', 'إعدادات المنصة'],
      tenantLandloomOpsPage: ['page.operations', 'العمليات']
    });

    function refreshTenantNavGroups() {
      document.querySelectorAll('.tenant-nav-group').forEach(group => {
        const visible = Array.from(group.querySelectorAll('.tenant-sidebar-link')).some(link =>
          link.style.display !== 'none' && !link.classList.contains('tenant-hidden'));
        group.style.display = visible ? '' : 'none';
      });
    }

    const TENANT_NAV_COLLAPSED_KEY = 'wf.navCollapsed';

    function getCollapsedTenantNavGroups() {
      try {
        const raw = JSON.parse(localStorage.getItem(TENANT_NAV_COLLAPSED_KEY) || '[]');
        return new Set(Array.isArray(raw) ? raw : []);
      } catch (e) {
        return new Set();
      }
    }

    function setTenantNavGroupCollapsed(group, collapsed, persist = true) {
      group.classList.toggle('nav-collapsed', collapsed);
      const toggle = group.querySelector('.tenant-nav-toggle');
      if (toggle) toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      if (!persist) return;
      const stored = getCollapsedTenantNavGroups();
      const key = group.getAttribute('data-nav-group');
      if (collapsed) stored.add(key); else stored.delete(key);
      try { localStorage.setItem(TENANT_NAV_COLLAPSED_KEY, JSON.stringify(Array.from(stored))); } catch (e) {}
    }

    function toggleTenantNavGroup(groupKey) {
      const group = document.querySelector('.tenant-nav-collapsible[data-nav-group="' + groupKey + '"]');
      if (!group) return;
      setTenantNavGroupCollapsed(group, !group.classList.contains('nav-collapsed'));
    }

    // Collapse choices are per device; the group holding the active page
    // always reopens in updateTenantChrome so the current link stays visible.
    function applyTenantNavGroupState() {
      const stored = getCollapsedTenantNavGroups();
      document.querySelectorAll('.tenant-nav-collapsible').forEach(group => {
        setTenantNavGroupCollapsed(group, stored.has(group.getAttribute('data-nav-group')), false);
      });
    }

    function updateTenantChrome(pageId) {
      const app = document.getElementById('tenantAppPage');
      if (!app) return;
      const isSagAdmin = Boolean(tenantUser && tenantUser.isAdmin);
      const role = (tenantUser && tenantUser._userRole) || 'company_admin';
      const roleData = isSagAdmin
        ? ['superadmin', 'role.super_admin', 'سوبر أدمن']
        : role === 'company_admin'
          ? ['company-admin', 'role.company_admin', 'أدمن الشركة']
          : ['employee', 'role.employee', 'موظف'];
      app.dataset.role = roleData[0];

      const roleEl = document.getElementById('tenantWorkspaceRole');
      if (roleEl) {
        roleEl.dataset.i18n = roleData[1];
        roleEl.textContent = WFT(roleData[1], roleData[2]);
      }
      const contextEl = document.getElementById('tenantCurrentPageContext');
      if (contextEl) {
        const contextKey = isSagAdmin ? 'chrome.platform' : 'chrome.workspace';
        const contextFallback = isSagAdmin ? 'إدارة المنصة' : 'مساحة العمل';
        contextEl.dataset.i18n = contextKey;
        contextEl.textContent = WFT(contextKey, contextFallback);
      }
      const pageData = TENANT_PAGE_CHROME[pageId] || TENANT_PAGE_CHROME.tenantDashboardPage;
      const titleEl = document.getElementById('tenantCurrentPageTitle');
      if (titleEl) {
        titleEl.dataset.i18n = pageData[0];
        titleEl.textContent = WFT(pageData[0], pageData[1]);
      }
      const searchWrap = document.querySelector('.tenant-topbar-search');
      const searchInput = document.getElementById('tenantGlobalSearch');
      if (searchWrap) {
        const canSearch = isSagAdmin || hasPermission('view_presentations');
        searchWrap.classList.toggle('tenant-hidden', !canSearch);
        if (searchInput && canSearch) {
          const searchKey = isSagAdmin ? 'chrome.search_companies' : 'chrome.search_projects';
          searchInput.setAttribute('data-i18n-ph', searchKey);
          searchInput.placeholder = WFT(searchKey, isSagAdmin ? 'بحث في الشركات' : 'بحث في المشاريع');
        }
      }
      const parentPages = {
        tenantProjectPresentationsPage: 'tenantPresentationsPage',
        tenantVisualConceptPage: 'tenantProjectPage',
        tenantGenerationPage: 'tenantProjectPage',
        tenantSlidesPage: 'tenantProjectPage'
      };
      const activePageId = parentPages[pageId] || pageId;
      const activeTab = (typeof llActiveTab !== 'undefined' && llActiveTab) || 'tasks';
      document.querySelectorAll('[data-nav-page]').forEach(link => {
        const navTab = link.getAttribute('data-nav-tab');
        const active = link.dataset.navPage === activePageId && (!navTab || navTab === activeTab);
        link.classList.toggle('active', active);
        if (active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
      document.querySelectorAll('.tenant-nav-collapsible').forEach(group => {
        if (group.querySelector('.tenant-sidebar-link.active')) setTenantNavGroupCollapsed(group, false, false);
      });
      refreshTenantNavGroups();
    }

    function toggleTenantSidebar() {
      const app = document.getElementById('tenantAppPage');
      if (!app) return;
      const open = app.classList.toggle('sidebar-open');
      const button = document.getElementById('tenantMobileMenuBtn');
      if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function closeTenantSidebar() {
      const app = document.getElementById('tenantAppPage');
      if (app) app.classList.remove('sidebar-open');
      const button = document.getElementById('tenantMobileMenuBtn');
      if (button) button.setAttribute('aria-expanded', 'false');
    }

    function toggleTenantDropdown(btn) {
      const drop = btn.closest('.tenant-dropdown');
      if (!drop) return;
      const isOpen = drop.classList.contains('open');
      document.querySelectorAll('.tenant-dropdown').forEach(d => d.classList.remove('open'));
      if (!isOpen) drop.classList.add('open');
    }

    function closeTenantDropdown() {
      document.querySelectorAll('.tenant-dropdown').forEach(d => d.classList.remove('open'));
    }

    function closeTenantBellPanel() {
      const panel = document.getElementById('tenantBellPanel');
      if (panel) panel.hidden = true;
      if (typeof closeNotificationsDropdown === 'function') closeNotificationsDropdown();
    }

    // The bell prefers the real notification dropdown once that module ships;
    // until then it opens the visual placeholder panel.
    function tenantBellClicked(event) {
      if (typeof toggleNotificationsDropdown === 'function') {
        toggleNotificationsDropdown();
        return;
      }
      const panel = document.getElementById('tenantBellPanel');
      if (panel) panel.hidden = !panel.hidden;
    }

    // Placeholder until the smart-notification feed ships: the dot turns on
    // with any positive unread count.
    function setTenantBellDot(unreadCount) {
      const dot = document.getElementById('tenantBellDot');
      if (dot) dot.classList.toggle('hidden', !(Number(unreadCount) > 0));
    }

    function tenantGlobalSearchKeydown(event) {
      if (!event || event.key !== 'Enter') return;
      event.preventDefault();
      runTenantGlobalSearch();
    }

    async function runTenantGlobalSearch() {
      const input = document.getElementById('tenantGlobalSearch');
      const q = String((input && input.value) || '').trim();
      if (tenantUser && tenantUser.isAdmin) {
        const box = document.getElementById('sagSearchInput');
        if (box) box.value = q;
        await openTenantCompanies();
        if (typeof filterSagTenants === 'function') filterSagTenants();
        return;
      }
      if (!hasPermission('view_presentations')) return;
      const box = document.getElementById('projectArchiveSearch');
      if (box) box.value = q;
      await openTenantPresentations(true);
    }

    document.addEventListener('click', function (e) {
      if (!e.target.closest('.tenant-dropdown')) closeTenantDropdown();
      if (!e.target.closest('.tenant-bellbox')) closeTenantBellPanel();
      document.querySelectorAll('.project-multi-select[open]').forEach(dropdown => {
        if (!dropdown.contains(e.target)) dropdown.open = false;
      });
    });

    async function loadDashboard() {
      const totalEl = document.getElementById('dashStatTotal');
      const pendingEl = document.getElementById('dashStatPending');
      // The presentation count needs metadata only, so fetch the small page.
      // When boot already started these requests, reuse them instead of
      // refetching.
      const boot = (typeof consumeTenantBootPrefetch === 'function') ? consumeTenantBootPrefetch() : null;
      const wantsBalance = hasPermission('billing');
      const [presData, approvalsData, dashData, overviewData] = await Promise.all([
        withBootTimeout((boot && boot.pres) || apiWithTimeout('GET', '/api/presentations?limit=5', null, 25000)),
        withBootTimeout((boot && boot.appr) || api('GET', '/api/approvals').catch(() => ({ success: false }))),
        api('GET', '/api/dashboard').catch(() => null),
        wantsBalance ? api('GET', '/api/client/overview').catch(() => null) : Promise.resolve(null)
      ]);
      renderDashboardOverview(dashData && dashData.dashboard);
      renderDashboardBalance(overviewData);
      tenantApplyChartRange();
      if (presData && presData.success && totalEl) {
        totalEl.textContent = Number.isFinite(Number(presData.total)) ? presData.total : (presData.presentations || []).length;
      }
      if (approvalsData && approvalsData.success && pendingEl) {
        pendingEl.textContent = (approvalsData.approvals || []).length;
      }
    }

    function renderDashboardOverview(dash) {
      const lifecycleEl = document.getElementById('dashboardLifecycle');
      if (!lifecycleEl) return;
      if (!dash) {
        lifecycleEl.innerHTML = '';
        return;
      }
      const buckets = (dash.lifecycle || []).filter(b => b.count > 0 || ['draft', 'approved'].includes(b.key));
      lifecycleEl.innerHTML = buckets.map(b =>
        '<div class="tenant-dash-card stat"><h3>' + (b.count || 0) + '</h3><p>' + escapeHtml(b.label || b.key) + '</p></div>'
      ).join('');
    }

    var tenantLastOverview = null;
    var tenantLastTrends = null;
    var tenantChartRange = { preset: '12', from: '', to: '' };

    function renderDashboardBalance(data) {
      const card = document.getElementById('dashboardBalanceCard');
      if (!card) return;
      tenantLastOverview = data || null;
      const pkg = (data && data.package) || null;
      // The server resolves the quota: a real package carries its own credit,
      // and a bare wallet reports everything the platform ever credited.
      const balance = Number((data && (data.balance_sar ?? data.balance_usd)) || 0);
      const remaining = pkg ? Number((pkg.remaining_sar ?? pkg.remaining_usd) || 0) : balance;
      const consumed = pkg ? Number((pkg.consumed_sar ?? pkg.consumed_usd) || 0) : 0;
      const credit = pkg ? Number((pkg.credit_sar ?? pkg.credit_usd) || 0) : remaining;
      const pct = credit > 0 ? Math.max(0, Math.min(100, (consumed / credit) * 100)) : 0;
      const valueEl = document.getElementById('dashBalanceValue');
      if (valueEl) valueEl.textContent = sagFmtMoney(remaining);
      const pillEl = document.getElementById('dashBalancePill');
      if (pillEl) {
        const name = pkg && pkg.name ? String(pkg.name) : '';
        pillEl.textContent = name;
        pillEl.hidden = !name;
      }
      const barEl = document.getElementById('dashBalanceBar');
      if (barEl) barEl.style.width = pct.toFixed(1) + '%';
      const subEl = document.getElementById('dashBalanceSub');
      if (subEl) {
        subEl.textContent = credit > 0
          ? WFT('dashboard.consumed_of', 'مستهلك {used} من {total}', { used: sagFmtMoney(consumed), total: sagFmtMoney(credit) })
          : '';
      }
    }

    // The company activity chart mirrors the super-admin platform chart — same
    // builders, same range presets — but every series is tenant-scoped and the
    // second line counts this company's new presentations instead of new
    // companies.
    function renderTenantActivityChart(trends) {
      trends = trends || {};
      tenantLastTrends = trends;
      const el = document.getElementById('tenantActivityChart');
      if (!el || typeof sagLineChart !== 'function') return;
      const labels = trends.labels || [];
      const spendSeries = (trends.ai_spend_sar || trends.ai_spend || []).map((v, i) => v + (((trends.maps_spend_sar || trends.maps_spend) || [])[i] || 0));
      const series = [
        { name: WFT('admin.legend_spend', 'المصروفات'), values: spendSeries, color: 'var(--chart-3)', fmt: sagFmtMoney },
        { name: WFT('dashboard.legend_presentations', 'عروض جديدة'), values: trends.presentations || [], color: 'var(--chart-2)', fmt: sagFmtNum },
      ];
      const chart = sagLineChart(labels, series);
      el.innerHTML = labels.length ? chart.svg : '';
      if (labels.length) sagBindChartTooltip(el, labels, series, chart.geom);
      sagLegend(document.getElementById('tenantActivityLegend'), series);
      renderTenantRangeControls();
    }

    function renderTenantRangeControls() {
      const box = document.getElementById('tenantActivityRange');
      if (!box) return;
      const presets = [
        { v: '3', t: WFT('admin.range_3m', 'آخر 3 شهور') },
        { v: '6', t: WFT('admin.range_6m', 'آخر 6 شهور') },
        { v: '12', t: WFT('admin.range_12m', 'آخر 12 شهرًا') },
        { v: '24', t: WFT('admin.range_24m', 'آخر سنتين') },
        { v: 'ytd', t: WFT('admin.range_ytd', 'هذه السنة') },
        { v: 'custom', t: WFT('admin.range_custom', 'نطاق مخصص') },
      ];
      box.innerHTML =
        '<select id="tenantRangePreset" class="admin-range-select" onchange="tenantChartRange.preset=this.value; renderTenantRangeControls(); tenantApplyChartRange()">' +
        presets.map(p => '<option value="' + p.v + '"' + (tenantChartRange.preset === p.v ? ' selected' : '') + '>' + p.t + '</option>').join('') +
        '</select>' +
        '<span class="admin-range-custom" style="display:' + (tenantChartRange.preset === 'custom' ? 'inline-flex' : 'none') + '">' +
        '<input type="date" id="tenantRangeFromDate" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_from', 'من')) + '" value="' + escapeHtml(tenantChartRange.from.slice(0, 10)) + '" onchange="tenantRangeChanged()">' +
        '<input type="time" id="tenantRangeFromTime" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_from_time', 'وقت البداية (اختياري)')) + '" value="' + escapeHtml(tenantChartRange.from.slice(11, 16)) + '" onchange="tenantRangeChanged()">' +
        '<input type="date" id="tenantRangeToDate" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_to', 'إلى')) + '" value="' + escapeHtml(tenantChartRange.to.slice(0, 10)) + '" onchange="tenantRangeChanged()">' +
        '<input type="time" id="tenantRangeToTime" dir="ltr" aria-label="' + escapeHtml(WFT('admin.range_to_time', 'وقت النهاية (اختياري)')) + '" value="' + escapeHtml(tenantChartRange.to.slice(11, 16)) + '" onchange="tenantRangeChanged()">' +
        '</span>';
    }

    function tenantRangeChanged() {
      const fd = document.getElementById('tenantRangeFromDate');
      const ft = document.getElementById('tenantRangeFromTime');
      const td = document.getElementById('tenantRangeToDate');
      const tt = document.getElementById('tenantRangeToTime');
      tenantChartRange.from = fd && fd.value ? fd.value + (ft && ft.value ? 'T' + ft.value : '') : '';
      tenantChartRange.to = td && td.value ? td.value + (tt && tt.value ? 'T' + tt.value : '') : '';
      tenantApplyChartRange();
    }

