/* 19-notifications.js - smart notification center: topbar badge + dropdown,
   full page with filters, and per-user category preferences.
   Shared global scope, classic scripts in order. */

    const NOTIF_CATEGORY_FALLBACKS = {
      general: 'عام', section_approval: 'اعتماد الأقسام', generation_approval: 'اعتماد التوليد',
      final_approval: 'اعتماد الملف النهائي', recharge: 'طلبات الشحن', billing: 'المحفظة والفوترة',
      support: 'الدعم الفني', task: 'المهام', job: 'مهام التوليد', platform: 'المنصة'
    };
    const NOTIF_CATEGORY_KEYS = Object.keys(NOTIF_CATEGORY_FALLBACKS);
    let notifPollTimer = null;
    let notifDropdownOpen = false;
    let notifLastItems = [];
    let notifLastCategories = null;
    let notifStatusState = 'all';

    function notifCategoryLabel(cat) {
      return WFT('notif.cat.' + cat, NOTIF_CATEGORY_FALLBACKS[cat] || cat);
    }

    // ── Badge polling ────────────────────────────────────────────────────
    function startNotificationsPolling() {
      if (notifPollTimer) clearInterval(notifPollTimer);
      refreshNotificationBadge();
      notifPollTimer = setInterval(refreshNotificationBadge, 45000);
    }

    async function refreshNotificationBadge() {
      const badge = document.getElementById('tenantNotifBadge');
      if (!badge || typeof getTenantToken !== 'function' || !getTenantToken()) return;
      const data = await api('GET', '/api/notifications/unread-count').catch(() => null);
      if (!data || !data.success) return;
      const n = parseInt(data.unread, 10) || 0;
      badge.textContent = n > 99 ? '99+' : String(n);
      badge.hidden = n <= 0;
      if (typeof setTenantBellDot === 'function') setTenantBellDot(n);
      if (notifDropdownOpen) renderNotificationsDropdown();
    }

    // ── Topbar dropdown ──────────────────────────────────────────────────
    function toggleNotificationsDropdown() {
      const dd = document.getElementById('tenantNotifDropdown');
      if (!dd) return;
      notifDropdownOpen = dd.hidden;
      dd.hidden = !notifDropdownOpen;
      if (notifDropdownOpen) renderNotificationsDropdown();
    }

    function closeNotificationsDropdown() {
      notifDropdownOpen = false;
      const dd = document.getElementById('tenantNotifDropdown');
      if (dd) dd.hidden = true;
    }

    document.addEventListener('click', (ev) => {
      if (!notifDropdownOpen) return;
      const wrap = document.querySelector('.tenant-notif');
      if (wrap && !wrap.contains(ev.target)) closeNotificationsDropdown();
    });

    async function renderNotificationsDropdown() {
      const list = document.getElementById('tenantNotifDropdownList');
      if (!list) return;
      const data = await api('GET', '/api/notifications?limit=5').catch(() => null);
      if (!data || !data.success) {
        list.innerHTML = '<p class="tenant-hint">' + llEscape(WFT('notif.load_failed', 'تعذر تحميل الإشعارات')) + '</p>';
        return;
      }
      notifLastItems = data.notifications || [];
      if (!notifLastItems.length) {
        list.innerHTML = '<p class="tenant-hint">' + llEscape(WFT('notif.empty', 'لا توجد إشعارات')) + '</p>';
        return;
      }
      list.innerHTML = notifLastItems.map(n => notifItemHtml(n)).join('');
    }

    function notifItemHtml(n) {
      const unread = !n.read_at;
      const when = (n.created_at || '').slice(0, 16).replace('T', ' ');
      const cat = n.category && n.category !== 'general'
        ? '<span class="tenant-notif-cat">' + llEscape(notifCategoryLabel(n.category)) + '</span>' : '';
      return '<div class="tenant-notif-item' + (unread ? ' unread' : '') + '" role="button" tabindex="0"' +
        ' onclick="notificationOpen(\'' + llEscape(n.id) + '\')"' +
        ' onkeydown="if(event.key===\'Enter\')notificationOpen(\'' + llEscape(n.id) + '\')">' +
        '<div class="tenant-notif-item-head"><strong>' + llEscape(n.title) + '</strong>' +
        '<span class="tenant-notif-head-side">' +
        (unread ? '<span class="tenant-notif-dot" title="' + llEscape(WFT('notif.new', 'جديد')) + '"></span>' : '') +
        '<button type="button" class="tenant-notif-del"' +
        ' onclick="notificationDelete(event,\'' + llEscape(n.id) + '\')"' +
        ' onkeydown="event.stopPropagation()">' + llEscape(WFT('common.delete', 'حذف')) + '</button>' +
        '</span></div>' +
        (n.body ? '<p>' + llEscape(n.body) + '</p>' : '') +
        '<div class="tenant-notif-meta">' + cat + '<bdi>' + llEscape(when) + '</bdi></div></div>';
    }

    // ── Click-through: entity type to its screen ────────────────────────
    function notificationTargetOpener(n) {
      if (!n) return null;
      const isAdmin = Boolean(tenantUser && tenantUser.isAdmin);
      const opsTab = (tab) => () => openLandloomOpsPage().then(() => showLandloomOpsTab(tab));
      const map = isAdmin ? {
        recharge_request: () => openAdminRechargePage(),
        support_ticket: () => openAdminTicketsPage(),
        tenant: () => openTenantCompanies(),
      } : {
        section_version: () => openTenantApprovals(),
        project_draft: () => openTenantApprovals(),
        generation_approval: () => openTenantApprovals(),
        final_file_approval: () => openTenantApprovals(),
        approval_task: () => openTenantApprovals(),
        support_ticket: opsTab('tickets'),
        recharge_request: opsTab('recharge'),
        wallet: opsTab('recharge'),
        generation_job: () => openTenantPresentations(),
        admin_access_request: () => openTenantUsers(),
      };
      return map[n.entity_type] || null;
    }

    async function notificationOpen(id) {
      const n = (notifLastItems || []).find(x => String(x.id) === String(id)) || null;
      api('POST', '/api/notifications/read', { ids: [id] }).catch(() => null);
      refreshNotificationBadge();
      const opener = notificationTargetOpener(n);
      closeNotificationsDropdown();
      if (opener) {
        opener(n);
      } else if (document.getElementById('tenantNotificationsList')) {
        renderNotificationsPage();
      }
    }

    async function notificationsMarkAllRead() {
      await api('POST', '/api/notifications/read', {}).catch(() => null);
      refreshNotificationBadge();
      if (notifDropdownOpen) renderNotificationsDropdown();
      if (document.getElementById('tenantNotificationsPage')
          && document.getElementById('tenantNotificationsPage').classList.contains('active')) {
        renderNotificationsPage();
      }
      if (document.getElementById('llNotificationsList')) llLoadNotifications();
    }

    // One delete per row, on every surface the feed renders on. The server
    // scopes the delete to rows this actor can see (broadcasts + their own).
    async function notificationDelete(ev, id) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      const data = await api('POST', '/api/notifications/delete', { ids: [id] }).catch(() => null);
      if (!data || !data.success) {
        toast(WFT('notif.delete_failed', 'تعذر حذف الإشعار'));
        return;
      }
      notifLastItems = (notifLastItems || []).filter(x => String(x.id) !== String(id));
      refreshNotificationBadge();
      if (notifDropdownOpen) renderNotificationsDropdown();
      if (document.getElementById('tenantNotificationsPage')
          && document.getElementById('tenantNotificationsPage').classList.contains('active')) {
        renderNotificationsPage();
      }
      if (document.getElementById('llNotificationsList')) llLoadNotifications();
      if (document.getElementById('adminNotificationsList')) llLoadNotifications('adminNotificationsList');
    }

    // ── Full notifications page ──────────────────────────────────────────
    async function openNotificationsPage() {
      closeNotificationsDropdown();
      showTenantPage('tenantNotificationsPage');
      // The page is shared between the super admin and company workspaces, so
      // its kicker follows the role instead of a static label.
      const isAdmin = Boolean(tenantUser && tenantUser.isAdmin);
      const kicker = document.getElementById('notifPageKicker');
      if (kicker) {
        const key = isAdmin ? 'chrome.platform' : 'chrome.workspace';
        kicker.dataset.i18n = key;
        kicker.textContent = WFT(key, isAdmin ? 'إدارة المنصة' : 'مساحة العمل');
      }
      const announcePanel = document.getElementById('notifAnnouncePanel');
      if (announcePanel) announcePanel.hidden = !isAdmin;
      const jobs = [renderNotificationsPage(), renderNotificationPrefs()];
      if (isAdmin) jobs.push(fillAnnounceTargets(document.getElementById('notifAnnounceTarget')));
      await Promise.all(jobs);
    }

    function setNotifStatusFilter(status) {
      notifStatusState = ['all', 'unread', 'read'].indexOf(status) !== -1 ? status : 'all';
      document.querySelectorAll('#tenantNotificationsPage [data-notif-status]').forEach(btn => {
        const active = btn.getAttribute('data-notif-status') === notifStatusState;
        btn.classList.toggle('primary', active);
        btn.classList.toggle('ghost', !active);
      });
      renderNotificationsPage();
    }

    function fillNotifCategoryFilter(categories) {
      const sel = document.getElementById('notifCategoryFilter');
      if (!sel || sel.dataset.filled) return;
      const cats = (categories && categories.length ? categories : NOTIF_CATEGORY_KEYS);
      sel.innerHTML = '<option value="">' + llEscape(WFT('notif.category_all', 'كل التصنيفات')) + '</option>' +
        cats.map(c => '<option value="' + llEscape(c) + '">' + llEscape(notifCategoryLabel(c)) + '</option>').join('');
      sel.dataset.filled = '1';
    }

    async function renderNotificationsPage() {
      const list = document.getElementById('tenantNotificationsList');
      if (!list) return;
      const params = ['limit=100'];
      const cat = (document.getElementById('notifCategoryFilter') || {}).value || '';
      if (cat) params.push('category=' + encodeURIComponent(cat));
      if (notifStatusState !== 'all') params.push('status=' + encodeURIComponent(notifStatusState));
      const data = await api('GET', '/api/notifications?' + params.join('&')).catch(() => null);
      if (!data || !data.success) {
        list.innerHTML = '<p class="tenant-hint">' + llEscape(WFT('notif.load_failed', 'تعذر تحميل الإشعارات')) + '</p>';
        return;
      }
      notifLastCategories = data.categories || null;
      fillNotifCategoryFilter(data.categories);
      notifLastItems = data.notifications || [];
      const unreadChip = document.getElementById('notifUnreadCount');
      if (unreadChip) {
        const unread = parseInt(data.unreadCount, 10) || 0;
        unreadChip.hidden = unread <= 0;
        unreadChip.textContent = unread > 0
          ? WFT('notif.unread_count', '{count} غير مقروءة', { count: unread }) : '';
      }
      if (!notifLastItems.length) {
        list.innerHTML = '<p class="tenant-hint">' + llEscape(WFT('notif.empty', 'لا توجد إشعارات')) + '</p>';
        return;
      }
      list.innerHTML = notifLastItems.map(n => notifCardHtml(n)).join('');
    }

    // One card layout shared by the full page, the operations tab and the
    // admin dashboard's latest-notifications panel.
    function notifCardHtml(n) {
      const unread = !n.read_at;
      return '<div class="tenant-presentation-card tenant-notif-card' + (unread ? ' unread' : '') + '"' +
        ' role="button" tabindex="0" onclick="notificationOpen(\'' + llEscape(n.id) + '\')"' +
        ' onkeydown="if(event.key===\'Enter\')notificationOpen(\'' + llEscape(n.id) + '\')">' +
        '<div class="tenant-notif-main">' +
        '<h3>' + (unread ? '<span class="tenant-notif-dot" aria-hidden="true"></span>' : '') +
        llEscape(n.title) +
        (unread ? ' <span class="tenant-notif-new">(' + llEscape(WFT('notif.new', 'جديد')) + ')</span>' : '') + '</h3>' +
        (n.body ? '<p class="tenant-notif-body">' + llEscape(n.body) + '</p>' : '') +
        '<div class="meta">' +
        '<span class="tenant-notif-cat">' + llEscape(notifCategoryLabel(n.category || 'general')) + '</span>' +
        '<bdi class="tenant-notif-time">' + llEscape((n.created_at || '').slice(0, 16).replace('T', ' ')) + '</bdi>' +
        '</div></div>' +
        '<div class="tenant-actions">' +
        '<button type="button" class="btn small ghost"' +
        ' onclick="notificationDelete(event,\'' + llEscape(n.id) + '\')"' +
        ' onkeydown="event.stopPropagation()">' + llEscape(WFT('common.delete', 'حذف')) + '</button>' +
        '</div></div>';
    }

    // The announce dropdown is filled from the tenants list the dashboard
    // already loaded; when the admin lands here first, fetch it once and
    // share the same cache instead of paying a second request.
    async function fillAnnounceTargets(sel, tenants) {
      if (!sel) return;
      let list = Array.isArray(tenants) ? tenants : null;
      if (!list) {
        if (!Array.isArray(sagAllTenants) || !sagAllTenants.length) {
          const data = await api('GET', '/api/admin/tenants').catch(() => null);
          if (data && data.success && Array.isArray(data.tenants)) sagAllTenants = data.tenants;
        }
        list = sagAllTenants || [];
      }
      const current = sel.value;
      sel.innerHTML = '<option value="all">' + llEscape(WFT('admin.announce_all', 'كل الشركات')) + '</option>' +
        list.filter(t => !t.is_admin).map(t =>
          '<option value="' + llEscape(t.id) + '">' + llEscape(t.company_name || t.name || t.email || t.id) + '</option>').join('');
      if (current) sel.value = current;
    }

    // ── Per-user category preferences ────────────────────────────────────
    async function renderNotificationPrefs() {
      const box = document.getElementById('tenantNotifPrefs');
      if (!box) return;
      const data = await api('GET', '/api/notifications/preferences').catch(() => null);
      const summary = document.getElementById('notifPrefsSummary');
      if (!data || !data.success) {
        box.innerHTML = '';
        if (summary) summary.textContent = '';
        return;
      }
      const prefs = data.preferences || {};
      const cats = (data.categories && data.categories.length) ? data.categories : NOTIF_CATEGORY_KEYS;
      if (summary) {
        const on = cats.filter(c => prefs[c] !== false).length;
        summary.textContent = WFT('notif.prefs_enabled_count', '{on} من {total} مفعّلة',
          { on: on, total: cats.length });
      }
      box.innerHTML = cats.map(c => {
        const on = prefs[c] !== false;
        return '<label class="tenant-notif-pref' + (on ? ' on' : '') + '">' +
          '<input type="checkbox" ' + (on ? 'checked ' : '') +
          'onchange="setNotificationPreference(\'' + llEscape(c) + '\', this.checked)">' +
          '<span>' + llEscape(notifCategoryLabel(c)) + '</span></label>';
      }).join('');
    }

    async function setNotificationPreference(category, enabled) {
      const data = await api('PUT', '/api/notifications/preferences',
        { category: category, enabled: enabled }).catch(() => null);
      if (!data || !data.success) {
        toast(WFT('notif.prefs_failed', 'تعذر حفظ التفضيلات'));
        renderNotificationPrefs();
        return;
      }
      refreshNotificationBadge();
      renderNotificationsPage();
      renderNotificationPrefs();
    }

    // The category select and the preference pills render through WFT at fill
    // time, so a language switch has to refill them — options are skipped by
    // the DOM auto-translator by design.
    document.addEventListener('wf:lang', () => {
      const sel = document.getElementById('notifCategoryFilter');
      if (sel && sel.dataset.filled) {
        const current = sel.value;
        delete sel.dataset.filled;
        fillNotifCategoryFilter(notifLastCategories);
        sel.value = current;
      }
      const page = document.getElementById('tenantNotificationsPage');
      if (page && page.classList.contains('active')) {
        renderNotificationsPage();
        renderNotificationPrefs();
      }
    });
