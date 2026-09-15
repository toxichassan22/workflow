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
      tenantOmranOpsPage: 'operations',
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
      tenantOmranOpsPage: 'openOmranOpsPage',
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
      const name = TENANT_PAGE_OPENERS[pageId];
      const opener = name && window[name];
      if (typeof opener === 'function') {
        // The operations entry remembers which sub-tab was showing; every
        // other opener takes no arguments.
        opener(pageId === 'tenantOmranOpsPage' ? getBrowserNavigationState().opsTab : undefined);
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
        return;
      }
      if (pageId === 'tenantSlidesPage') {
        if (typeof renderTenantSlides === 'function') renderTenantSlides();
        showTenantPage('tenantSlidesPage');
        return;
      }
      if (pageId === 'tenantVisualConceptPage') {
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
      showTenantPage('tenantProjectPage');
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
      const [response, draftResponse] = await Promise.all([
        apiWithTimeout('GET', '/api/presentations?' + query.toString(), null, 25000).catch(() => ({ success: false })),
        api('GET', '/api/project-draft/' + encodeURIComponent(draftId)).catch(() => ({ success: false }))
      ]);
      if (!response || !response.success) {
        renderListLoadError(host, 'loadProjectPresentationsPage()');
        return;
      }
      const title = draftResponse?.success && draftResponse.draft?.title ? draftResponse.draft.title : '';
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
        const itemMapsCost = Number(itemCost?.maps_cost_usd) || 0;
        return '<div class="tenant-presentation-card" data-presentation-id="' + item.id + '"><div><h3>' + escapeHtml(item.title || 'عرض بدون عنوان') + '</h3>' +
          '<div class="meta"><span>' + (item.slideCount || 0) + '</span> <span>شريحة</span> | <span>النسخة</span> <span>' + (item.revision || 0) + '</span> | ' + escapeHtml(date) + ' | <span>التكلفة:</span> ' + (itemCost ? formatUsageCost(itemCost.cost_usd || 0) + (itemMapsCost > 0 ? ' (<span>خرائط:</span> ' + formatUsageCost(itemMapsCost) + ')' : '') + (itemReconcile ? ' | <span>' + itemReconcile + '</span>' : '') : '—') + '</div></div>' +
          '<div class="tenant-actions"><button type="button" class="btn primary small" onclick="openExistingPresentation(\'' + item.id + '\')">فتح العرض</button>' +
          '<button type="button" class="btn ghost small" onclick="showEditLog(\'' + item.id + '\')">سجل التعديلات والنسخ</button></div></div>';
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
      tenantOmranOpsPage: ['page.operations', 'العمليات']
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
      const roleBadges = {
        section_editor: ['employee', 'role.section_editor', 'محرر أقسام'],
        section_approver: ['employee', 'role.section_approver', 'معتمد أقسام'],
        generation_approver: ['employee', 'role.generation_approver', 'معتمد توليد'],
        final_file_approver: ['employee', 'role.final_file_approver', 'معتمد ملف'],
        profile: ['employee', 'role.profile', 'بروفايل'],
        support: ['employee', 'role.support', 'دعم'],
      };
      const roleData = isSagAdmin
        ? ['superadmin', 'role.super_admin', 'سوبر أدمن']
        : role === 'company_admin'
          ? ['company-admin', 'role.company_admin', 'أدمن الشركة']
          : (roleBadges[role] || ['employee', 'role.employee', 'موظف']);
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
      const activeTab = (typeof omActiveTab !== 'undefined' && omActiveTab) || 'tasks';
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
      const balance = Number((data && data.balance_usd) || 0);
      const remaining = pkg ? Number(pkg.remaining_usd || 0) : balance;
      const consumed = pkg ? Number(pkg.consumed_usd || 0) : 0;
      const credit = pkg ? Number(pkg.credit_usd || 0) : remaining;
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
      const spendSeries = (trends.ai_spend || []).map((v, i) => v + ((trends.maps_spend || [])[i] || 0));
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

    let pendingMfaToken = null;
    let pendingMfaSetup = false;

    async function handleLogin(e) {
      e.preventDefault();
      showTenantError('loginError', '');
      const email = document.getElementById('loginEmail').value.trim();
      const password = document.getElementById('loginPassword').value;
      const data = await api('POST', '/api/auth/login', { email, password });
      if (data.success && data.mfaRequired) {
        pendingMfaToken = data.mfaToken;
        document.getElementById('loginForm').style.display = 'none';
        const mfaForm = document.getElementById('mfaForm');
        if (mfaForm) {
          mfaForm.style.display = 'block';
          const codeInput = document.getElementById('mfaCode');
          if (codeInput) { codeInput.value = ''; codeInput.focus(); }
        }
        return;
      }
      if (data.success && data.token) {
        setTenantToken(data.token);
        setTenantUser(data.tenant);
        pendingMfaSetup = !!data.mfaSetupRequired;
        await bootstrapTenant();
        if (pendingMfaSetup) openMfaSetupModal(true);
      } else {
        showTenantError('loginError', data.error || WFT('auth.login_failed', 'فشل تسجيل الدخول'));
      }
    }

    async function handleMfaVerify(e) {
      e.preventDefault();
      showTenantError('loginError', '');
      const code = (document.getElementById('mfaCode') || {}).value || '';
      const data = await api('POST', '/api/auth/mfa/verify', { mfaToken: pendingMfaToken, code: code.trim() });
      if (data.success && data.token) {
        pendingMfaToken = null;
        document.getElementById('mfaForm').style.display = 'none';
        document.getElementById('loginForm').style.display = 'block';
        setTenantToken(data.token);
        setTenantUser(data.tenant);
        await bootstrapTenant();
        if (data.mfaMethod === 'recovery' && typeof data.recoveryCodesRemaining === 'number' && data.recoveryCodesRemaining <= 2) {
          toast(WFT('auth.mfa_recovery_low', 'رموز الاسترداد المتبقية قليلة'));
        }
      } else {
        showTenantError('loginError', data.error || WFT('auth.mfa_invalid', 'رمز التحقق غير صحيح'));
      }
    }

    function cancelMfaChallenge() {
      pendingMfaToken = null;
      const mfaForm = document.getElementById('mfaForm');
      if (mfaForm) mfaForm.style.display = 'none';
      const loginForm = document.getElementById('loginForm');
      if (loginForm) loginForm.style.display = 'block';
    }

    async function openMfaSetupModal(mandatory, reauth) {
      document.getElementById('mfaSetupModal')?.remove();
      const modal = document.createElement('div');
      modal.id = 'mfaSetupModal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10001;display:flex;align-items:center;justify-content:center;padding:16px;';
      modal.innerHTML =
        '<div style="background:#fff;border-radius:16px;max-width:480px;width:100%;max-height:85vh;overflow:auto;padding:24px;direction:rtl;text-align:right;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
        '<h3 style="margin:0;color:#1a3a52;font-size:18px;">' + escapeHtml(WFT('auth.mfa_setup_title', 'تفعيل التحقق الثنائي')) + '</h3>' +
        (mandatory ? '' : '<button type="button" class="btn ghost small" onclick="document.getElementById(\'mfaSetupModal\').remove()">' + escapeHtml(WFT('common.close', 'إغلاق')) + '</button>') +
        '</div>' +
        '<div id="mfaSetupBody"><p class="tenant-hint">' + escapeHtml(WFT('common.loading', 'جاري التحميل...')) + '</p></div>' +
        '</div>';
      document.body.appendChild(modal);
      const data = await api('POST', '/api/auth/mfa/setup', reauth || {});
      const body = document.getElementById('mfaSetupBody');
      if (!body) return;
      if (!data || !data.success) {
        body.innerHTML = '<p style="color:#c33">' + escapeHtml((data && data.error) || WFT('common.error', 'حدث خطأ')) + '</p>';
        return;
      }
      body.innerHTML =
        '<p class="tenant-hint" style="margin:0 0 8px">' + escapeHtml(WFT('auth.mfa_secret_label', 'المفتاح السري')) + '</p>' +
        '<input type="text" readonly dir="ltr" value="' + escapeHtml(data.secret) + '" style="width:100%;font-size:13px;margin-bottom:8px" onclick="this.select()">' +
        '<input type="text" readonly dir="ltr" value="' + escapeHtml(data.otpauthUri || '') + '" style="width:100%;font-size:11px;margin-bottom:12px;color:#64748b" onclick="this.select()">' +
        '<label style="display:block;margin-bottom:4px">' + escapeHtml(WFT('auth.mfa_code', 'رمز التحقق الثنائي')) + '</label>' +
        '<input type="text" id="mfaSetupCode" inputmode="numeric" autocomplete="one-time-code" dir="ltr" style="width:100%;margin-bottom:12px">' +
        '<div id="mfaSetupError" style="color:#c33;font-size:12px;min-height:16px;margin-bottom:8px"></div>' +
        '<button type="button" class="btn primary" onclick="enableMfaFromModal()">' + escapeHtml(WFT('auth.mfa_enable', 'تفعيل')) + '</button>';
    }

    async function enableMfaFromModal() {
      const code = ((document.getElementById('mfaSetupCode') || {}).value || '').trim();
      const errBox = document.getElementById('mfaSetupError');
      if (errBox) errBox.textContent = '';
      const data = await api('POST', '/api/auth/mfa/enable', { code });
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || WFT('auth.mfa_invalid', 'رمز التحقق غير صحيح');
        return;
      }
      pendingMfaSetup = false;
      const body = document.getElementById('mfaSetupBody');
      if (!body) return;
      const codes = (data.recoveryCodes || []).map(c =>
        '<code dir="ltr" style="display:block;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:4px 8px;margin-bottom:4px;font-size:13px;">' + escapeHtml(c) + '</code>'
      ).join('');
      body.innerHTML =
        '<p style="margin:0 0 8px;color:#1c7a2e;font-weight:700">' + escapeHtml(WFT('auth.mfa_enabled_ok', 'تم تفعيل التحقق الثنائي')) + '</p>' +
        '<p class="tenant-hint" style="margin:0 0 8px">' + escapeHtml(WFT('auth.mfa_recovery_title', 'رموز الاسترداد')) + '</p>' +
        '<div style="margin-bottom:12px">' + codes + '</div>' +
        '<button type="button" class="btn primary" onclick="document.getElementById(\'mfaSetupModal\').remove()">' + escapeHtml(WFT('common.close', 'إغلاق')) + '</button>';
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
          case 'tenantOmranOpsPage':
            await openOmranOpsPage(state.opsTab);
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
        } else if (requestedPage === 'tenantOmranOpsPage') {
          // Reopen the sub-tab the refresh was sitting on — the route carries
          // no tab, so it comes from the remembered navigation state.
          const opsNavigation = getTenantNavigationState();
          const opsTenantId = tenantUser && (tenantUser.id || tenantUser.tenantId);
          const savedOpsTab = opsNavigation && opsNavigation.opsTab &&
            (!opsNavigation.tenantId || opsNavigation.tenantId === opsTenantId)
            ? opsNavigation.opsTab : null;
          await openOmranOpsPage(savedOpsTab);
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