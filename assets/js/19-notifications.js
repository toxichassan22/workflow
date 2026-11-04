/* 19-notifications.js - smart notification center: topbar badge + dropdown,
   full page with filters, and per-user category preferences.
   Shared global scope, classic scripts in order. */

    const NOTIF_CATEGORY_FALLBACKS = {
      general: 'عام', section_approval: 'اعتماد الأقسام', generation_approval: 'اعتماد التوليد',
      final_approval: 'اعتماد الملف النهائي', recharge: 'طلبات الشحن', billing: 'المحفظة والفوترة',
      support: 'الدعم الفني', job: 'مهام التوليد', platform: 'المنصة'
    };
    const NOTIF_CATEGORY_KEYS = Object.keys(NOTIF_CATEGORY_FALLBACKS);
    let notifPollTimer = null;
    let notifDropdownOpen = false;
    let notifLastItems = [];
    let notifLastCategories = null;
    let notifStatusState = 'all';
    let notifCategoryGroup = 'all';
    let notifSelectedIds = new Set();
    let notifRenderedItems = [];
    let notifSearchTimer = null;
    const NOTIF_GROUP_CATEGORIES = {
      projects: ['section_approval', 'generation_approval', 'final_approval', 'job'],
      finance: ['billing', 'recharge'],
      support: ['support', 'platform', 'general']
    };

    function formatNotifNumberSanitized(str) {
      if (!str) return '';
      return String(str).replace(/(\d+)\.(\d{3,})/g, (match) => {
        const val = parseFloat(match);
        return isNaN(val) ? match : val.toFixed(2);
      });
    }

    function notifActionBtn(n) {
      if (!n) return '';
      const isAdmin = Boolean(tenantUser && tenantUser.isAdmin);
      const t = (k, fb) => (typeof WFT === 'function' ? WFT(k, fb) : fb);
      if (isAdmin) {
        if (n.entity_type === 'recharge_request') {
          return '<button type="button" class="btn small primary" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_review_recharge', 'مراجعة الشحن')) + '</button>';
        }
        if (n.entity_type === 'support_ticket') {
          return '<button type="button" class="btn small primary" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_review_ticket', 'مراجعة التذكرة')) + '</button>';
        }
        if (n.entity_type === 'join_request') {
          return '<button type="button" class="btn small primary" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_review_join', 'مراجعة الطلب')) + '</button>';
        }
      } else {
        if (['section_version', 'project_draft', 'generation_approval', 'final_file_approval', 'approval_task'].indexOf(n.entity_type) !== -1) {
          return '<button type="button" class="btn small primary" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_review_approval', 'مراجعة الاعتماد')) + '</button>';
        }
        if (n.entity_type === 'generation_job') {
          return '<button type="button" class="btn small primary" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_view_project', 'عرض المشاريع')) + '</button>';
        }
        if (['recharge_request', 'wallet'].indexOf(n.entity_type) !== -1) {
          return '<button type="button" class="btn small primary" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_view_wallet', 'عرض المحفظة')) + '</button>';
        }
        if (n.entity_type === 'support_ticket') {
          return '<button type="button" class="btn small primary" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_view_ticket', 'عرض التذكرة')) + '</button>';
        }
      }
      if (n.title && (n.title.indexOf('مشروع') !== -1 || n.title.indexOf('عرض') !== -1 || n.title.indexOf('كروكي') !== -1)) {
        return '<button type="button" class="btn small ghost" onclick="event.stopPropagation();notificationOpen(\'' + llEscape(n.id) + '\')">' + llEscape(t('notif.act_view_details', 'معاينة')) + '</button>';
      }
      return '';
    }

    function notifEmptyHtml(isFiltered) {
      const t = (k, fb) => (typeof WFT === 'function' ? WFT(k, fb) : fb);
      const title = isFiltered
        ? t('notif.empty_search_title', 'لا توجد نتائج مطابقة للبحث')
        : t('notif.empty_title', 'لا توجد إشعارات حالياً');
      const desc = isFiltered
        ? t('notif.empty_search_desc', 'جرّب البحث بكلمات أخرى أو تغيير خيارات التصفية والوقت.')
        : t('notif.empty_desc', 'كافة التنبيهات والعمليات محدثة ولا توجد إشعارات جديدة بانتظار المتابعة.');
      return '<div class="tenant-notif-empty-state">' +
        '<h3 class="notif-empty-title">' + llEscape(title) + '</h3>' +
        '<p class="notif-empty-desc">' + llEscape(desc) + '</p>' +
        (isFiltered
          ? '<button type="button" class="btn small ghost" onclick="clearNotifFilters()">' + llEscape(t('notif.clear_filters', 'إعادة ضبط الفلاتر')) + '</button>'
          : '<button type="button" class="btn small ghost" onclick="openTenantPresentations()">' + llEscape(t('notif.empty_cta', 'الانتقال إلى المشاريع')) + '</button>') +
        '</div>';
    }

    function clearNotifFilters() {
      const s = document.getElementById('notifSearchInput');
      if (s) s.value = '';
      const t = document.getElementById('notifTimeFilter');
      if (t) t.value = 'all';
      setNotifCategoryGroup('all');
      setNotifStatusFilter('all');
    }

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
        join_request: () => openAdminJoinPage(),
        tenant: () => openTenantCompanies(),
        subscription: (n) => openNotificationsPage().then(() => prefillAnnounceForTenant(n)),
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
      if (document.getElementById('adminNotificationsList')) llLoadNotifications('adminNotificationsList');
    }

    // ── Full notifications page ──────────────────────────────────────────
    async function openNotificationsPage() {
      closeNotificationsDropdown();
      showTenantPage('tenantNotificationsPage');
      if (typeof hydrateWorkspaceIcons === 'function') {
        hydrateWorkspaceIcons(document.getElementById('tenantNotificationsPage'));
      }
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
      const jobs = [renderNotificationsPage()];
      if (isAdmin) jobs.push(fillAnnounceTargets(document.getElementById('notifAnnounceTarget')));
      await Promise.all(jobs);
    }

    function setNotifCategoryGroup(grp) {
      notifCategoryGroup = ['all', 'projects', 'finance', 'support'].indexOf(grp) !== -1 ? grp : 'all';
      document.querySelectorAll('#tenantNotificationsPage [data-notif-category]').forEach(btn => {
        const active = btn.getAttribute('data-notif-category') === notifCategoryGroup;
        btn.classList.toggle('primary', active);
        btn.classList.toggle('ghost', !active);
      });
      renderNotificationsPage();
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

    function notifNormalizeText(s) {
      if (!s) return '';
      return String(s)
        .toLowerCase()
        .replace(/[ً-ٰٟ]/g, '')
        .replace(/[أإآٱ]/g, 'ا')
        .replace(/ة/g, 'ه')
        .replace(/ى/g, 'ي');
    }

    function notifMatchesQuery(n, q) {
      if (!q) return true;
      const cleanQ = String(q).trim();
      if (!cleanQ) return true;
      const tokens = notifNormalizeText(cleanQ).split(/\s+/).filter(Boolean);
      if (!tokens.length) return true;
      const catLabel = typeof notifCategoryLabel === 'function' ? notifCategoryLabel(n.category || '') : (n.category || '');
      const haystack = notifNormalizeText(
        (n.title || '') + ' ' + (n.body || '') + ' ' + catLabel + ' ' + (n.entity_type || '')
      );
      return tokens.every(tok => haystack.indexOf(tok) !== -1);
    }

    function notifMatchesTime(createdAt, timeFilter) {
      if (!timeFilter || timeFilter === 'all') return true;
      if (!createdAt) return false;
      const itemDate = new Date(createdAt);
      if (isNaN(itemDate.getTime())) return true;
      const now = new Date();
      if (timeFilter === 'today') {
        return itemDate.toDateString() === now.toDateString();
      }
      if (timeFilter === 'week') {
        const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        return itemDate >= weekAgo;
      }
      if (timeFilter === 'month') {
        const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        return itemDate >= monthAgo;
      }
      return true;
    }

    function onNotifSearchInput() {
      applyNotifFilters();
    }

    function applyNotifFilters() {
      const list = document.getElementById('tenantNotificationsList');
      if (!list || !Array.isArray(notifLastItems)) return;
      const allItems = notifLastItems;

      let itemsToRender = allItems;
      if (notifCategoryGroup && notifCategoryGroup !== 'all' && NOTIF_GROUP_CATEGORIES[notifCategoryGroup]) {
        const allowed = NOTIF_GROUP_CATEGORIES[notifCategoryGroup];
        itemsToRender = itemsToRender.filter(x => allowed.indexOf(x.category) !== -1);
      }

      const query = (document.getElementById('notifSearchInput') || {}).value || '';
      if (query) {
        itemsToRender = itemsToRender.filter(x => notifMatchesQuery(x, query));
      }

      const timeVal = (document.getElementById('notifTimeFilter') || {}).value || 'all';
      if (timeVal !== 'all') {
        itemsToRender = itemsToRender.filter(x => notifMatchesTime(x.created_at, timeVal));
      }

      notifRenderedItems = itemsToRender;

      if (!itemsToRender.length) {
        notifSelectedIds.clear();
        updateNotifSelectionUI();
        const isFiltered = Boolean(query || (timeVal && timeVal !== 'all') || (notifCategoryGroup && notifCategoryGroup !== 'all') || (notifStatusState && notifStatusState !== 'all'));
        list.innerHTML = notifEmptyHtml(isFiltered);
        return;
      }
      list.innerHTML = itemsToRender.map(n => notifCardHtml(n)).join('');
      updateNotifSelectionUI();
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

      // Update counters & stats strip
      const allItems = notifLastItems;
      const total = parseInt(data.total, 10) || allItems.length;
      const unread = parseInt(data.unreadCount, 10) || allItems.filter(x => !x.read_at).length;
      const projCount = allItems.filter(x => (NOTIF_GROUP_CATEGORIES.projects || []).indexOf(x.category) !== -1).length;
      const sysCount = allItems.filter(x => (NOTIF_GROUP_CATEGORIES.finance || []).concat(NOTIF_GROUP_CATEGORIES.support || []).indexOf(x.category) !== -1).length;

      const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = String(v); };
      setEl('notifStatTotal', total);
      setEl('notifStatUnread', unread);
      setEl('notifStatProjects', projCount);
      setEl('notifStatSystem', sysCount);

      const unreadChip = document.getElementById('notifUnreadCount');
      if (unreadChip) {
        unreadChip.hidden = unread <= 0;
        unreadChip.textContent = unread > 0
          ? WFT('notif.unread_count', '{count} غير مقروءة', { count: unread }) : '';
      }

      applyNotifFilters();
    }

    // ── Multi-selection and bulk actions ─────────────────────────────────
    function toggleNotifSelect(ev, id) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      const strId = String(id);
      if (notifSelectedIds.has(strId)) {
        notifSelectedIds.delete(strId);
      } else {
        notifSelectedIds.add(strId);
      }
      updateNotifSelectionUI();
    }

    function toggleNotifSelectAll(checked) {
      if (!checked) {
        notifSelectedIds.clear();
      } else {
        (notifRenderedItems || []).forEach(n => notifSelectedIds.add(String(n.id)));
      }
      updateNotifSelectionUI();
    }

    function clearNotifSelection() {
      notifSelectedIds.clear();
      updateNotifSelectionUI();
    }

    function updateNotifSelectionUI() {
      const count = notifSelectedIds.size;
      const bar = document.getElementById('notifBulkActions');
      const countEl = document.getElementById('notifSelectedCount');
      const masterCb = document.getElementById('notifSelectAll');
      if (bar) bar.style.display = count > 0 ? 'inline-flex' : 'none';
      if (countEl) countEl.textContent = WFT('notif.selected_count', 'تم تحديد {count}', { count: count });
      if (masterCb && (notifRenderedItems || []).length > 0) {
        masterCb.checked = count > 0 && notifRenderedItems.every(n => notifSelectedIds.has(String(n.id)));
        masterCb.indeterminate = count > 0 && !masterCb.checked;
      } else if (masterCb) {
        masterCb.checked = false;
        masterCb.indeterminate = false;
      }
      document.querySelectorAll('#tenantNotificationsList .tenant-notif-card-revamp').forEach(card => {
        const cb = card.querySelector('.notif-card-checkbox');
        if (cb) {
          const isSel = notifSelectedIds.has(cb.getAttribute('data-notif-id'));
          cb.checked = isSel;
          card.classList.toggle('selected', isSel);
        }
      });
    }

    async function notificationMarkSingleRead(ev, id) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      const data = await api('POST', '/api/notifications/read', { ids: [id] }).catch(() => null);
      if (!data || !data.success) {
        toast(WFT('notif.mark_read_failed', 'تعذر تحديث حالة الإشعار'));
        return;
      }
      notifSelectedIds.delete(String(id));
      refreshNotificationBadge();
      renderNotificationsPage();
    }

    async function bulkMarkNotificationsRead() {
      if (!notifSelectedIds.size) return;
      const ids = Array.from(notifSelectedIds);
      const data = await api('POST', '/api/notifications/read', { ids: ids }).catch(() => null);
      if (!data || !data.success) {
        toast(WFT('notif.bulk_read_failed', 'تعذر تحديث حالة الإشعارات'));
        return;
      }
      notifSelectedIds.clear();
      refreshNotificationBadge();
      renderNotificationsPage();
    }

    async function bulkDeleteNotifications() {
      if (!notifSelectedIds.size) return;
      const ids = Array.from(notifSelectedIds);
      const data = await api('POST', '/api/notifications/delete', { ids: ids }).catch(() => null);
      if (!data || !data.success) {
        toast(WFT('notif.bulk_delete_failed', 'تعذر حذف الإشعارات'));
        return;
      }
      notifSelectedIds.clear();
      notifLastItems = (notifLastItems || []).filter(x => !ids.includes(String(x.id)));
      refreshNotificationBadge();
      renderNotificationsPage();
    }

    // One card layout shared by the full page, the operations tab and the
    // admin dashboard's latest-notifications panel.
    function notifCardHtml(n) {
      const unread = !n.read_at;
      const isSelected = notifSelectedIds.has(String(n.id));
      const actionBtn = notifActionBtn(n);
      const title = formatNotifNumberSanitized(n.title || '');
      const body = formatNotifNumberSanitized(n.body || '');
      const when = (n.created_at || '').slice(0, 16).replace('T', ' ');
      const singleReadBtn = unread
        ? '<button type="button" class="btn small ghost" onclick="notificationMarkSingleRead(event,\'' + llEscape(n.id) + '\')">' + llEscape(WFT('notif.mark_read', 'تعليم كمقروء')) + '</button>'
        : '';
      const checkboxHtml = '<input type="checkbox" class="notif-card-checkbox" data-notif-id="' + llEscape(n.id) + '"' +
        (isSelected ? ' checked' : '') +
        ' onclick="toggleNotifSelect(event,\'' + llEscape(n.id) + '\')"' +
        ' aria-label="' + llEscape(title) + '">';

      return '<div class="tenant-notif-card tenant-notif-card-revamp' + (unread ? ' unread' : '') + (isSelected ? ' selected' : '') + '"' +
        ' role="button" tabindex="0" onclick="notificationOpen(\'' + llEscape(n.id) + '\')"' +
        ' onkeydown="if(event.key===\'Enter\')notificationOpen(\'' + llEscape(n.id) + '\')">' +
        checkboxHtml +
        '<div class="tenant-notif-main notif-main-area">' +
        '<div class="notif-header-line">' +
        '<h3 class="notif-card-title">' + (unread ? '<span class="tenant-notif-dot" aria-hidden="true"></span>' : '') +
        llEscape(title) +
        (unread ? ' <span class="tenant-notif-new">(' + llEscape(WFT('notif.new', 'جديد')) + ')</span>' : '') + '</h3>' +
        '</div>' +
        (body ? '<p class="tenant-notif-body notif-card-body">' + llEscape(body) + '</p>' : '') +
        '<div class="meta notif-card-meta">' +
        '<span class="tenant-notif-cat tenant-notif-cat-badge">' + llEscape(notifCategoryLabel(n.category || 'general')) + '</span>' +
        '<bdi class="tenant-notif-time">' + llEscape(when) + '</bdi>' +
        '</div></div>' +
        '<div class="tenant-actions notif-card-actions">' +
        singleReadBtn +
        actionBtn +
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
          '<option value="' + llEscape(t.id) + '">' +
        llEscape(wfBilingual(t.company_name || t.name, t.company_name_en) || t.email || t.id) +
        '</option>').join('');
      if (current) sel.value = current;
    }

    // A subscription-expiry notice carries «tenant:state:end-date» in
    // entity_id — landing here pre-picks that company in the announce
    // composer so the renewal message is one send away.
    function prefillAnnounceForTenant(n) {
      const parts = String((n && n.entity_id) || '').split(':');
      const tenantId = parts[0];
      const sel = document.getElementById('notifAnnounceTarget');
      if (sel && tenantId) sel.value = tenantId;
      const title = document.getElementById('notifAnnounceTitle');
      if (title && !title.value) title.value = 'تجديد الباقة';
      const body = document.getElementById('notifAnnounceBody');
      if (body && !body.value && parts[2]) {
        body.value = parts[1] === 'expired'
          ? WFT('notif.package_expired', 'انتهت باقتكم في {date} — إن رجبتم في التجديد يسعدنا تواصلكم معنا.', { date: parts[2] })
          : WFT('notif.package_expiring', 'باقتكم تنتهي في {date} — إن رجبتم في التجديد يسعدنا تواصلكم معنا.', { date: parts[2] });
      }
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



