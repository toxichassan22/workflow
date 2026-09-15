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
        list.innerHTML = '<p class="tenant-hint">' + omEscape(WFT('notif.load_failed', 'تعذر تحميل الإشعارات')) + '</p>';
        return;
      }
      notifLastItems = data.notifications || [];
      if (!notifLastItems.length) {
        list.innerHTML = '<p class="tenant-hint">' + omEscape(WFT('notif.empty', 'لا توجد إشعارات')) + '</p>';
        return;
      }
      list.innerHTML = notifLastItems.map(n => notifItemHtml(n)).join('');
    }

    function notifItemHtml(n) {
      const unread = !n.read_at;
      const when = (n.created_at || '').slice(0, 16).replace('T', ' ');
      const cat = n.category && n.category !== 'general'
        ? '<span class="tenant-notif-cat">' + omEscape(notifCategoryLabel(n.category)) + '</span>' : '';
      return '<div class="tenant-notif-item' + (unread ? ' unread' : '') + '" role="button" tabindex="0"' +
        ' onclick="notificationOpen(\'' + omEscape(n.id) + '\')"' +
        ' onkeydown="if(event.key===\'Enter\')notificationOpen(\'' + omEscape(n.id) + '\')">' +
        '<div class="tenant-notif-item-head"><strong>' + omEscape(n.title) + '</strong>' +
        '<span class="tenant-notif-head-side">' +
        (unread ? '<span class="tenant-notif-dot" title="' + omEscape(WFT('notif.new', 'جديد')) + '"></span>' : '') +
        '<button type="button" class="tenant-notif-del"' +
        ' onclick="notificationDelete(event,\'' + omEscape(n.id) + '\')"' +
        ' onkeydown="event.stopPropagation()">' + omEscape(WFT('common.delete', 'حذف')) + '</button>' +
        '</span></div>' +
        (n.body ? '<p>' + omEscape(n.body) + '</p>' : '') +
        '<div class="tenant-notif-meta">' + cat + '<span>' + omEscape(when) + '</span></div></div>';
    }

    // ── Click-through: entity type → its screen ─────────────────────────
    function notificationTargetOpener(n) {
      if (!n) return null;
      const isAdmin = Boolean(tenantUser && tenantUser.isAdmin);
      const opsTab = (tab) => () => openOmranOpsPage().then(() => showOmranOpsTab(tab));
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
        event_task: opsTab('tasks'),
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
      if (document.getElementById('omNotificationsList')) omLoadNotifications();
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
      if (document.getElementById('omNotificationsList')) omLoadNotifications();
      if (document.getElementById('adminNotificationsList')) omLoadNotifications('adminNotificationsList');
    }

    // ── Full notifications page ──────────────────────────────────────────
    async function openNotificationsPage() {
      closeNotificationsDropdown();
      showTenantPage('tenantNotificationsPage');
      await Promise.all([renderNotificationsPage(), renderNotificationPrefs()]);
    }

    function fillNotifCategoryFilter(categories) {
      const sel = document.getElementById('notifCategoryFilter');
      if (!sel || sel.dataset.filled) return;
      const cats = (categories && categories.length ? categories : NOTIF_CATEGORY_KEYS);
      sel.innerHTML = '<option value="">' + omEscape(WFT('notif.category_all', 'كل التصنيفات')) + '</option>' +
        cats.map(c => '<option value="' + omEscape(c) + '">' + omEscape(notifCategoryLabel(c)) + '</option>').join('');
      sel.dataset.filled = '1';
    }

    async function renderNotificationsPage() {
      const list = document.getElementById('tenantNotificationsList');
      if (!list) return;
      const params = ['limit=100'];
      const cat = (document.getElementById('notifCategoryFilter') || {}).value || '';
      const status = (document.getElementById('notifStatusFilter') || {}).value || 'all';
      if (cat) params.push('category=' + encodeURIComponent(cat));
      if (status && status !== 'all') params.push('status=' + encodeURIComponent(status));
      const data = await api('GET', '/api/notifications?' + params.join('&')).catch(() => null);
      if (!data || !data.success) {
        list.innerHTML = '<p class="tenant-hint">' + omEscape(WFT('notif.load_failed', 'تعذر تحميل الإشعارات')) + '</p>';
        return;
      }
      fillNotifCategoryFilter(data.categories);
      notifLastItems = data.notifications || [];
      if (!notifLastItems.length) {
        list.innerHTML = '<p class="tenant-hint">' + omEscape(WFT('notif.empty', 'لا توجد إشعارات')) + '</p>';
        return;
      }
      list.innerHTML = notifLastItems.map(n =>
        '<div class="tenant-presentation-card tenant-notif-card' + (!n.read_at ? ' unread' : '') + '"' +
        ' role="button" tabindex="0" onclick="notificationOpen(\'' + omEscape(n.id) + '\')"' +
        ' onkeydown="if(event.key===\'Enter\')notificationOpen(\'' + omEscape(n.id) + '\')">' +
        '<div><h3>' + omEscape(n.title) +
        (!n.read_at ? ' <span class="tenant-notif-new">(' + omEscape(WFT('notif.new', 'جديد')) + ')</span>' : '') + '</h3>' +
        '<div class="meta">' +
        '<span class="tenant-notif-cat">' + omEscape(notifCategoryLabel(n.category || 'general')) + '</span>' +
        (n.body ? ' | <span>' + omEscape(n.body) + '</span>' : '') +
        ' | ' + omEscape((n.created_at || '').slice(0, 16).replace('T', ' ')) +
        '</div></div>' +
        '<div class="tenant-actions">' +
        '<button type="button" class="btn small ghost"' +
        ' onclick="notificationDelete(event,\'' + omEscape(n.id) + '\')"' +
        ' onkeydown="event.stopPropagation()">' + omEscape(WFT('common.delete', 'حذف')) + '</button>' +
        '</div></div>').join('');
    }

    // ── Per-user category preferences ────────────────────────────────────
    async function renderNotificationPrefs() {
      const box = document.getElementById('tenantNotifPrefs');
      if (!box) return;
      const data = await api('GET', '/api/notifications/preferences').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '';
        return;
      }
      const prefs = data.preferences || {};
      const cats = (data.categories && data.categories.length) ? data.categories : NOTIF_CATEGORY_KEYS;
      box.innerHTML = cats.map(c => {
        const on = prefs[c] !== false;
        return '<label class="tenant-notif-pref"><input type="checkbox" ' + (on ? 'checked ' : '') +
          'onchange="setNotificationPreference(\'' + omEscape(c) + '\', this.checked)">' +
          '<span>' + omEscape(notifCategoryLabel(c)) + '</span></label>';
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
    }
