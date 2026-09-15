/* 18-omran-ops.js - t40/t50 operations page: event tasks, notifications,
   support tickets. Shared global scope, classic scripts in order. */

    function omEscape(text) {
      return String(text == null ? '' : text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function omStatus(status) {
      const labels = {
        open: 'مفتوحة', done: 'مغلقة', completed: 'منجزة', cancelled: 'ملغاة',
        pending: 'قيد المراجعة', approved: 'معتمد', rejected: 'مرفوض',
        in_progress: 'قيد المعالجة', resolved: 'تم الحل', closed: 'مغلقة',
        waiting_customer: 'بانتظار العميل', escalated: 'مصعّدة', reopened: 'معاد فتحها',
        consumed: 'مسوّى', expired: 'منتهية الصلاحية',
      };
      return labels[status] || status || '';
    }

    function openOmModal(id) {
      const m = document.getElementById(id);
      if (m) {
        m.style.display = 'flex';
        const err = m.querySelector('[id$="Error"]');
        if (err) err.textContent = '';
        if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(m);
      }
    }

    function closeOmModal(id) {
      const m = document.getElementById(id);
      if (m) {
        m.style.display = 'none';
        if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
      }
    }

    const OMRAN_OPS_TABS = ['tasks', 'recharge', 'tickets', 'contracts'];
    let omActiveTab = 'tasks';

    function omranOpsTabVisible(t) {
      const btn = document.getElementById('omTabBtn_' + t);
      return btn && btn.style.display !== 'none';
    }

    function showOmranOpsTab(tabKey) {
      // Permission-gated tabs hide their button; a request for a hidden tab
      // lands on the first one the member may see.
      const target = omranOpsTabVisible(tabKey)
        ? tabKey
        : (OMRAN_OPS_TABS.find(omranOpsTabVisible) || 'tasks');
      omActiveTab = target;
      OMRAN_OPS_TABS.forEach(t => {
        const pane = document.getElementById('omTabPane_' + t);
        const btn = document.getElementById('omTabBtn_' + t);
        const isActive = (t === target);
        if (pane) pane.style.display = isActive ? 'block' : 'none';
        if (btn) {
          btn.classList.toggle('primary', isActive);
          btn.classList.toggle('ghost', !isActive);
        }
      });
      // The sidebar carries one link per tab, so its active marker follows
      // in-page tab switches too.
      const opsPage = document.getElementById('tenantOmranOpsPage');
      if (typeof updateTenantChrome === 'function' && opsPage && opsPage.classList.contains('active')) {
        updateTenantChrome('tenantOmranOpsPage');
      }
    }

    async function openOmranOpsPage(tabKey) {
      showTenantPage('tenantOmranOpsPage');
      showOmranOpsTab(tabKey || 'tasks');

      await Promise.all([
        omLoadEventTasks(),
        omLoadNotifications(),
        omLoadTickets(),
        omLoadPointsOverview(),
        omLoadRechargeRequests(),
        omLoadContracts()
      ]);
    }

    // ── Event tasks + approver task center (t24/t42) ───────────────────────
    let omAllTasks = [];

    async function omLoadEventTasks() {
      const box = document.getElementById('omTasksList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const [data, approvals] = await Promise.all([
        api('GET', '/api/event-tasks').catch(() => null),
        api('GET', '/api/approval-tasks?status=all').catch(() => null),
      ]);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل المهام.</p>';
        return;
      }
      const tasks = (data.tasks || []).map(t => Object.assign({}, t, { _kind: 'event' }));
      const approvalTasks = ((approvals && approvals.tasks) || []).map(t => Object.assign({}, t, { _kind: 'approval' }));
      omAllTasks = tasks.concat(approvalTasks).sort((a, b) =>
        String(a.due_at || a.event_date || '').localeCompare(String(b.due_at || b.event_date || '')));
      const openCount = omAllTasks.filter(t => t.status === 'open').length;
      const stat = document.getElementById('omStatTasks');
      if (stat) stat.textContent = openCount;
      omPopulateTaskFilters();
      omRenderTasks();
    }

    // t24: project and section filter options follow whatever the loaded
    // tasks actually reference — the list stays honest even mid-review.
    function omPopulateTaskFilters() {
      const projectSelect = document.getElementById('omTasksProjectFilter');
      const sectionSelect = document.getElementById('omTasksSectionFilter');
      if (projectSelect) {
        const previous = projectSelect.value;
        const projects = {};
        omAllTasks.forEach(t => {
          if (t.draft_id) projects[t.draft_id] = t.project_name || t.draft_id;
        });
        projectSelect.innerHTML = '<option value="">كل المشاريع</option>' +
          Object.keys(projects).sort((a, b) => String(projects[a]).localeCompare(String(projects[b])))
            .map(id => '<option value="' + omEscape(id) + '">' + omEscape(projects[id]) + '</option>').join('');
        projectSelect.value = projects[previous] ? previous : '';
      }
      if (sectionSelect) {
        const previous = sectionSelect.value;
        const sections = {};
        omAllTasks.forEach(t => {
          if (t.section_key) {
            sections[t.section_key] = (typeof PROJECT_SECTION_PRESENTATION_TITLES !== 'undefined'
              && PROJECT_SECTION_PRESENTATION_TITLES[t.section_key]) || t.section_key;
          }
        });
        sectionSelect.innerHTML = '<option value="">كل الأقسام</option>' +
          Object.keys(sections).sort((a, b) => String(sections[a]).localeCompare(String(sections[b])))
            .map(key => '<option value="' + omEscape(key) + '">' + omEscape(sections[key]) + '</option>').join('');
        sectionSelect.value = sections[previous] ? previous : '';
      }
    }

    function omRenderTasks() {
      const box = document.getElementById('omTasksList');
      if (!box) return;
      const kindFilter = (document.getElementById('omTasksKindFilter') || {}).value || '';
      const prioFilter = (document.getElementById('omTasksPriorityFilter') || {}).value || '';
      const statusFilter = (document.getElementById('omTasksStatusFilter') || {}).value || 'open';
      const projectFilter = (document.getElementById('omTasksProjectFilter') || {}).value || '';
      const sectionFilter = (document.getElementById('omTasksSectionFilter') || {}).value || '';
      const filtered = omAllTasks.filter(t => {
        const kind = t._kind === 'approval' ? (t.kind || 'approval') : 'manual';
        if (kindFilter && kind !== kindFilter) return false;
        if (prioFilter && (t.priority || 'normal') !== prioFilter) return false;
        if (statusFilter === 'open' && t.status !== 'open') return false;
        if (statusFilter === 'done' && ['done', 'completed', 'cancelled'].indexOf(t.status) === -1) return false;
        if (projectFilter && String(t.draft_id || '') !== projectFilter) return false;
        if (sectionFilter && String(t.section_key || '') !== sectionFilter) return false;
        return true;
      });
      if (!filtered.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد مهام بعد.</p>';
        return;
      }
      const myUserId = String((tenantUser && tenantUser._userId) || '');
      const myActorId = myUserId || ('tenant-admin:' + ((tenantUser && tenantUser.id) || ''));
      const canManageTasks = hasPermission('manage_users');
      const isApprover = hasPermission('approvals') || hasPermission('approve_generation') ||
        hasPermission('approve_final_file');
      const kindLabel = { section_approval: 'اعتماد قسم', generation_approval: 'اعتماد توليد',
        final_approval: 'اعتماد ملف نهائي', recharge: 'طلب شحن',
        support: 'تذكرة دعم', revision: 'مراجعة', manual: 'مهمة يدوية' };
      box.innerHTML = filtered.map(t => {
        const due = (t.due_at || t.event_date || '').slice(0, 16).replace('T', ' ');
        const recurring = t.recurrence && t.recurrence !== 'none'
          ? ' | <span>متكررة:</span> ' + ({ daily: 'يوميًا', weekly: 'أسبوعيًا', monthly: 'شهريًا' }[t.recurrence] || t.recurrence)
          : '';
        const prio = t.priority && t.priority !== 'normal'
          ? ' | <span>الأولوية:</span> ' + omEscape(({ high: 'عالية', urgent: 'عاجلة', low: 'منخفضة' }[t.priority] || t.priority))
          : '';
        const kind = t._kind === 'approval'
          ? ' | <span style="color:#8a5a00;">' + omEscape(kindLabel[t.kind] || 'اعتماد') + '</span>' : '';
        const project = t.project_name ? ' | <span>المشروع:</span> ' + omEscape(t.project_name) : '';
        const assignee = t.assignee_name ? ' | <span>المكلف:</span> ' + omEscape(t.assignee_name) : '';
        const escalated = t.escalated_at ? ' | <span style="color:#c33;font-weight:700">مصعّدة</span>' : '';
        const overdue = t.is_overdue ? ' | <span style="color:#c33;font-weight:700">متأخرة</span>' : '';
        const isMine = canManageTasks || String(t.assignee_user_id || t.assignee_id || '') === myUserId ||
          String(t.created_by || '') === myActorId;
        const remindBtn = t.status === 'open' && t._kind === 'approval' && (isMine || isApprover)
          ? '<button class="btn ghost" onclick="omRemindApprovalTask(\'' + t.id + '\')">تذكير</button>' : '';
        const action = t.status === 'open' && isMine
          ? (t._kind === 'approval'
            ? '<button class="btn ghost" onclick="omCloseApprovalTask(\'' + t.id + '\')">إغلاق</button>'
            : '<button class="btn ghost" onclick="omCompleteTask(\'' + t.id + '\')">إتمام</button>')
          : '';
        return '<div class="tenant-presentation-card"><div><h3>' + omEscape(t.title) + '</h3>' +
          '<div class="meta"><span>' + omStatus(t.status) + '</span>' + kind + project +
          (due ? ' | <span>الاستحقاق:</span> ' + omEscape(due) : '') + recurring + prio + assignee + escalated + overdue + '</div></div>' +
          '<div style="display:flex;gap:6px">' + remindBtn + action + '</div></div>';
      }).join('');
    }

    async function omRemindApprovalTask(id) {
      const data = await api('POST', '/api/approval-tasks/' + id + '/remind', {}).catch(() => null);
      if (data && data.success) toast(WFT('tasks.reminder_sent', 'أُرسل التذكير'));
      await omLoadEventTasks();
    }

    async function omCloseApprovalTask(id) {
      await api('POST', '/api/approval-tasks/' + id + '/close', {}).catch(() => null);
      await omLoadEventTasks();
    }

    async function omCompleteTask(id) {
      await api('POST', '/api/event-tasks/' + id + '/status', { status: 'completed' }).catch(() => null);
      await omLoadEventTasks();
    }

    async function omCreateTask() {
      const title = (document.getElementById('omTaskTitle') || {}).value || '';
      const dueAt = (document.getElementById('omTaskDue') || {}).value || '';
      const recurrence = (document.getElementById('omTaskRecurrence') || {}).value || 'none';
      const errBox = document.getElementById('omTasksError');
      if (errBox) errBox.textContent = '';
      const data = await api('POST', '/api/event-tasks', { title: title.trim(), dueAt, recurrence }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر إنشاء المهمة.';
        return;
      }
      document.getElementById('omTaskTitle').value = '';
      document.getElementById('omTaskDue').value = '';
      closeOmModal('omTaskModal');
      toast(WFT('tasks.created', 'تم إضافة المهمة بنجاح'));
      await omLoadEventTasks();
    }

    // ── Notifications ────────────────────────────────────────────────────
    async function omLoadNotifications(targetBoxId) {
      const box = document.getElementById(targetBoxId || 'omNotificationsList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/notifications').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل التنبيهات.</p>';
        return;
      }
      const items = data.notifications || [];
      const unreadCount = items.filter(n => !n.read_at).length;
      const noteStat = document.getElementById('omStatNotifications');
      if (noteStat) noteStat.textContent = unreadCount;
      if (!items.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تنبيهات.</p>';
        return;
      }
      box.innerHTML = items.map(n => {
        const unread = !n.read_at;
        const when = (n.created_at || '').slice(0, 16).replace('T', ' ');
        return '<div class="tenant-presentation-card" style="' + (unread ? 'border-color:var(--p);' : 'opacity:.75;') + '">' +
          '<div><h3>' + omEscape(n.title) + (unread ? ' <span style="color:var(--p);font-size:11px">(جديد)</span>' : '') + '</h3>' +
          '<div class="meta">' + (n.body ? '<span>' + omEscape(n.body) + '</span> | ' : '') + omEscape(when) + '</div></div></div>';
      }).join('') +
      '<button class="btn ghost" onclick="omMarkAllRead()">تحديد الكل كمقروء</button>';
    }

    async function omMarkAllRead() {
      await api('POST', '/api/notifications/read', {}).catch(() => null);
      await omLoadNotifications();
      await omLoadNotifications('adminNotificationsList');
    }

    // ── Support tickets ──────────────────────────────────────────────────
    async function omLoadTickets() {
      const box = document.getElementById('omTicketsList');
      if (!box) return;
      // The desk is permission-gated; skip the call for members without it.
      if (!hasPermission('support_tickets')) { box.innerHTML = ''; return; }
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/support/tickets').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل التذاكر.</p>';
        return;
      }
      const tickets = data.tickets || [];
      const activeCount = tickets.filter(t => t.status !== 'closed' && t.status !== 'resolved').length;
      const tStat = document.getElementById('omStatTickets');
      if (tStat) tStat.textContent = activeCount;

      if (!tickets.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تذاكر دعم.</p>';
        return;
      }
      box.innerHTML = tickets.map(t => {
        const priorityLabels = { urgent: 'حرجة', high: 'عاجلة', normal: 'عادية', low: 'منخفضة' };
        return '<div class="tenant-presentation-card" style="cursor:pointer" role="button" tabindex="0" onclick="omOpenTicket(\'' + t.id + '\')">' +
          '<div><h3>#' + omEscape(t.number) + ' ' + omEscape(t.subject) + '</h3>' +
          '<div class="meta"><span>' + omStatus(t.status) + '</span> | <span>الأولوية:</span> <span>' + omEscape(priorityLabels[t.priority] || t.priority) + '</span></div></div></div>';
      }).join('');
    }

    async function omOpenTicket(id) {
      const detail = document.getElementById('omTicketDetail');
      if (!detail) return;
      detail.style.display = 'block';
      detail.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/support/tickets/' + id).catch(() => null);
      if (!data || !data.success) {
        detail.innerHTML = '<p class="tenant-hint">تعذر فتح التذكرة.</p>';
        return;
      }
      const t = data.ticket || {};
      const messages = (t.messages || []).map(m =>
        '<div style="border-top:1px solid var(--line);padding:8px 0">' +
        '<strong style="font-size:12px">' + omEscape(m.author_name) + '</strong> ' +
        '<span style="font-size:11px;color:var(--muted)">' + omEscape((m.created_at || '').slice(0, 16).replace('T', ' ')) + '</span>' +
        '<p style="margin:4px 0 0;font-size:13px">' + omEscape(m.body) + '</p></div>'
      ).join('');
      const myUserId = String((tenantUser && tenantUser._userId) || '');
      const myActorId = myUserId || ('tenant-admin:' + ((tenantUser && tenantUser.id) || ''));
      const canSupport = hasPermission('support_tickets');
      const isCreator = String(t.created_by || '') === myActorId;
      const statusActions = canSupport
        ? '<div style="display:flex;gap:6px;margin:12px 0;flex-wrap:wrap">' +
          '<button class="btn small ghost" onclick="omSetTicketStatus(\'' + id + '\', \'in_progress\')">قيد المعالجة</button>' +
          '<button class="btn small ghost" onclick="omSetTicketStatus(\'' + id + '\', \'waiting_customer\')">بانتظار العميل</button>' +
          '<button class="btn small ghost" onclick="omSetTicketStatus(\'' + id + '\', \'resolved\')">تم الحل</button>' +
          '<button class="btn small danger" onclick="omSetTicketStatus(\'' + id + '\', \'closed\')">إغلاق التذكرة</button></div>'
        : (t.status !== 'closed' && isCreator
          ? '<div style="margin:12px 0"><button class="btn small danger" onclick="omSetTicketStatus(\'' + id + '\', \'closed\')">إغلاق التذكرة</button></div>'
          : '');
      detail.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<h3 style="margin:0">#' + omEscape(t.number) + ' ' + omEscape(t.subject) + ' — <span>' + omStatus(t.status) + '</span></h3>' +
        '<button class="btn ghost" onclick="document.getElementById(\'omTicketDetail\').style.display=\'none\'">إغلاق</button></div>' +
        statusActions +
        '<div style="margin:12px 0">' + (messages || '<p class="tenant-hint">لا رسائل.</p>') + '</div>' +
        (t.status !== 'closed'
          ? '<div style="display:flex;gap:8px"><input type="text" id="omReplyBody" style="flex:1">' +
            '<button class="btn primary" onclick="omReplyTicket(\'' + id + '\')">إرسال</button></div>'
          : '');
    }

    async function omSetTicketStatus(id, status) {
      const res = await api('POST', '/api/support/tickets/' + id + '/status', { status }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر تحديث الحالة'); return; }
      await omOpenTicket(id);
      await omLoadTickets();
    }

    async function omReplyTicket(id) {
      const input = document.getElementById('omReplyBody');
      const body = (input || {}).value || '';
      if (!body.trim()) return;
      await api('POST', '/api/support/tickets/' + id + '/messages', { body: body.trim() }).catch(() => null);
      await omOpenTicket(id);
      await omLoadTickets();
    }

    async function omCreateTicket() {
      const subject = (document.getElementById('omTicketSubject') || {}).value || '';
      const body = (document.getElementById('omTicketBody') || {}).value || '';
      const errBox = document.getElementById('omTicketsError');
      if (errBox) errBox.textContent = '';
      const category = (document.getElementById('omTicketCategory') || {}).value || 'general';
      const priority = (document.getElementById('omTicketPriority') || {}).value || 'normal';
      const data = await api('POST', '/api/support/tickets', {
        subject: subject.trim(), body: body.trim(), category: category, priority: priority
      }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر إنشاء التذكرة.';
        return;
      }
      document.getElementById('omTicketSubject').value = '';
      document.getElementById('omTicketBody').value = '';
      closeOmModal('omTicketModal');
      toast(WFT('tickets.created', 'تم إرسال تذكرة الدعم بنجاح'));
      await omLoadTickets();
    }

    // ── Points overview (t30) ─────────────────────────────────────────────
    async function omLoadPointsOverview() {
      const box = document.getElementById('omPointsOverview');
      if (!box) return;
      if (!hasPermission('billing')) { box.innerHTML = ''; return; }
      const data = await api('GET', '/api/points/overview').catch(() => null);
      if (!data || !data.success || !data.points) {
        box.innerHTML = '';
        return;
      }
      const p = data.points;
      const card = (label, value, suffix) =>
        '<div class="tenant-dash-card stat"><p>' + label + '</p><h3>' + omEscape(String(value)) +
        ' <span style="font-size:12px;font-weight:400;color:#64748b;">' + suffix + '</span></h3></div>';
      box.innerHTML = '<div class="tenant-dashboard-stats">' +
        card('الرصيد الحالي', p.current_points, 'نقطة') +
        card('المحجوز', p.reserved_points, 'نقطة') +
        card('المتاح', p.available_points, 'نقطة') +
        card('المنتهي', p.expired_points, 'نقطة') +
        '</div>';
    }

    // ── Recharge requests (t33, d09) ──────────────────────────────────────
    async function omLoadRechargeRequests(targetBoxId) {
      const box = document.getElementById(targetBoxId || 'omRechargeList');
      if (!box) return;
      if (!hasPermission('billing')) { box.innerHTML = ''; return; }
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const isAdmin = (typeof hasPermission === 'function' && hasPermission('sag_admin_panel')) || targetBoxId === 'sagRechargeRequestsList';
      const url = isAdmin ? '/api/admin/recharge-requests' : '/api/recharge-requests';
      const data = await api('GET', url).catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل طلبات الشحن.</p>';
        return;
      }
      const requests = data.requests || [];
      const pendingCount = requests.filter(r => r.status === 'pending').length;
      const rStat = document.getElementById('omStatRecharges');
      if (rStat) rStat.textContent = pendingCount;

      if (!requests.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد طلبات شحن بعد.</p>';
        return;
      }
      box.innerHTML = requests.map(r => {
        const date = (r.created_at || '').slice(0, 16).replace('T', ' ');
        const tenantInfo = (isAdmin && (r.tenant_name || r.company_name)) ? ('<span>الشركة:</span> ' + omEscape(r.tenant_name || r.company_name) + ' | ') : '';
        const ref = r.transfer_reference ? (' | <span>المرجع البنكي:</span> ' + omEscape(r.transfer_reference)) : '';
        const inv = r.reference_number ? (' | <span style="color:#1c7a2e;font-weight:600;">سند مالي:</span> ' + omEscape(r.reference_number)) : '';
        const actions = (isAdmin && r.status === 'pending')
          ? '<div style="display:flex;gap:6px;margin-top:6px;">' +
            '<button type="button" class="btn small green" onclick="omDecideRecharge(\'' + r.id + '\', \'approved\')">اعتماد الطلب</button>' +
            '<button type="button" class="btn small danger" onclick="omDecideRecharge(\'' + r.id + '\', \'rejected\')">رفض</button>' +
            '</div>'
          : '';
        return '<div class="tenant-presentation-card">' +
          '<div><h3><span>' + omEscape(r.package_name) + '</span> — ' + (r.price_sar ? r.price_sar + ' <span>ريال</span>' : (r.amount_usd + ' <span>دولار</span>')) + '</h3>' +
          '<div class="meta">' + tenantInfo + '<span>' + omStatus(r.status) + '</span> | <span>' + omEscape(date) + '</span>' + ref + inv + '</div>' +
          actions +
          '</div></div>';
      }).join('');
    }

    let omRechargePackages = [];

    async function omLoadRechargePackages() {
      const select = document.getElementById('omRechargePackage');
      if (!select) return;
      const data = await api('GET', '/api/billing/packages').catch(() => null);
      omRechargePackages = (data && data.success && data.packages) || [];
      if (!omRechargePackages.length) return;
      select.innerHTML = omRechargePackages.map(p =>
        '<option value="' + omEscape(p.id) + '">' + omEscape(p.name) +
        ' (' + (p.credit_usd || 0) + ' <span>دولار</span>' +
        (p.price_sar ? ' — ' + p.price_sar + ' <span>ريال</span>' : '') + ')</option>'
      ).join('');
      omShowPackageInfo();
    }

    function omShowPackageInfo() {
      const box = document.getElementById('omRechargePackageInfo');
      const select = document.getElementById('omRechargePackage');
      if (!box || !select) return;
      const pkg = omRechargePackages.find(p => p.id === select.value);
      if (!pkg) { box.style.display = 'none'; box.textContent = ''; return; }
      const parts = [pkg.duration_days
        ? 'الصلاحية: ' + pkg.duration_days + ' يومًا'
        : 'الصلاحية: بلا انتهاء محدد'];
      (Array.isArray(pkg.features) ? pkg.features : []).forEach(f => {
        if (f) parts.push(String(f));
      });
      box.textContent = parts.join(' — ');
      box.style.display = '';
    }

    async function omUploadRechargeReceipt() {
      const input = document.getElementById('omRechargeReceipt');
      if (!input || !input.files || !input.files[0]) return null;
      const form = new FormData();
      form.append('file', input.files[0]);
      form.append('fileType', 'recharge_receipt');
      const data = await api('POST', '/api/project-files', form, true).catch(e => e);
      if (!data || !data.success) return { error: (data && data.error) || 'تعذر رفع الإيصال' };
      return data.file;
    }

    async function omCreateRechargeRequest() {
      const packageId = (document.getElementById('omRechargePackage') || {}).value || '';
      const ref = (document.getElementById('omRechargeRef') || {}).value || '';
      const errBox = document.getElementById('omRechargeError');
      if (errBox) errBox.textContent = '';
      const receipt = await omUploadRechargeReceipt();
      if (receipt && receipt.error) {
        if (errBox) errBox.textContent = receipt.error;
        return;
      }
      const pkg = omRechargePackages.find(p => p.id === packageId);
      const data = await api('POST', '/api/recharge-requests', {
        packageId: packageId || null,
        packageName: pkg ? pkg.name : packageId,
        referenceNumber: ref.trim(),
        receiptFileId: receipt ? receipt.id : null
      }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر إرسال الطلب.';
        return;
      }
      if (document.getElementById('omRechargeRef')) document.getElementById('omRechargeRef').value = '';
      if (document.getElementById('omRechargeReceipt')) document.getElementById('omRechargeReceipt').value = '';
      closeOmModal('omRechargeModal');
      toast(WFT('recharge.request_sent', 'تم إرسال طلب الشحن بنجاح'));
      await omLoadRechargeRequests();
    }

    async function omDecideRecharge(requestId, decision) {
      const data = await api('POST', '/api/admin/recharge-requests/' + encodeURIComponent(requestId) + '/decision', {
        decision: decision
      }).catch(e => e);
      if (data && data.success) {
        toast(decision === 'approved' ? WFT('recharge.approved', 'تم اعتماد الشحن وتوليد الرقم المرجعي المالي') : WFT('recharge.rejected', 'تم رفض طلب الشحن'));
        if (typeof omLoadRechargeRequests === 'function') {
          await omLoadRechargeRequests('omRechargeList');
        }
        if (typeof adminLoadRecharges === 'function') await adminLoadRecharges();
      } else {
        toast(WFT('recharge.decision_failed', 'تعذر تسجيل القرار'));
      }
    }

    // ── Contracts & NDAs (t52, d06) ──────────────────────────────────────
    async function omLoadContracts() {
      const box = document.getElementById('omContractsList');
      if (!box) return;
      if (!hasPermission('company_settings')) { box.innerHTML = ''; return; }
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/contracts').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل العقود.</p>';
        return;
      }
      const contracts = data.contracts || [];
      if (!contracts.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد عقود مسجلة بعد.</p>';
        return;
      }
      box.innerHTML = contracts.map(c => {
        const expires = c.expires_at ? (' | <span>ينتهي:</span> ' + omEscape(c.expires_at)) : '';
        const kindLabel = c.kind === 'nda' ? 'اتفاقية سرية' : 'عقد رئيسي';
        const isExpired = c.status === 'expired' || (c.expires_at && new Date(c.expires_at) < new Date());
        const statusLabel = isExpired ? '<span style="color:#c33;">منتهي (محفوظ 365 يوماً)</span>' : '<span style="color:var(--green);">سارٍ</span>';
        return '<div class="tenant-presentation-card">' +
          '<div><h3>' + omEscape(c.title) + ' — <span>' + kindLabel + '</span></h3>' +
          '<div class="meta">' + statusLabel + expires + '</div></div></div>';
      }).join('');
    }

    async function omCreateContract() {
      const title = (document.getElementById('omContractTitle') || {}).value || '';
      const kind = (document.getElementById('omContractKind') || {}).value || 'nda';
      const startsAt = (document.getElementById('omContractStarts') || {}).value || '';
      const expiresAt = (document.getElementById('omContractExpires') || {}).value || '';
      const signatureStatus = (document.getElementById('omContractSignature') || {}).value || 'unsigned';
      const errBox = document.getElementById('omContractError');
      if (errBox) errBox.textContent = '';
      if (!title.trim()) {
        if (errBox) errBox.textContent = 'مسمى العقد مطلوب.';
        return;
      }
      let fileId = null;
      const fileInput = document.getElementById('omContractFile');
      if (fileInput && fileInput.files && fileInput.files[0]) {
        const form = new FormData();
        form.append('file', fileInput.files[0]);
        form.append('fileType', 'contract_file');
        const uploaded = await api('POST', '/api/project-files', form, true).catch(e => e);
        if (!uploaded || !uploaded.success) {
          if (errBox) errBox.textContent = (uploaded && uploaded.error) || 'تعذر رفع ملف الوثيقة.';
          return;
        }
        fileId = uploaded.file.id;
      }
      const data = await api('POST', '/api/contracts', {
        title: title.trim(),
        kind: kind,
        fileId: fileId,
        startsAt: startsAt || null,
        expiresAt: expiresAt || null,
        signatureStatus: signatureStatus
      }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر حفظ العقد.';
        return;
      }
      if (document.getElementById('omContractTitle')) document.getElementById('omContractTitle').value = '';
      if (document.getElementById('omContractExpires')) document.getElementById('omContractExpires').value = '';
      if (document.getElementById('omContractStarts')) document.getElementById('omContractStarts').value = '';
      if (fileInput) fileInput.value = '';
      closeOmModal('omContractModal');
      toast(WFT('contracts.saved', 'تم حفظ العقد بنجاح'));
      await omLoadContracts();
    }

    // ── File types registry (t62, d10) — lives on the platform settings page ──
    async function omLoadFileTypes(targetBoxId) {
      const box = document.getElementById(targetBoxId || 'adminFileTypesList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/file-types').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل سجل أنواع الملفات.</p>';
        return;
      }
      const types = data.fileTypes || [];
      if (!types.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد أنواع ملفات مسجلة.</p>';
        return;
      }
      box.innerHTML =
        '<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;">' +
        '<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:right;">' +
        '<thead><tr style="background:#f8fafc;border-bottom:1px solid #e2e8f0;color:#475569;">' +
        '<th style="padding:10px 8px;">نوع الملف</th>' +
        '<th style="padding:10px 8px;">المفتاح</th>' +
        '<th style="padding:10px 8px;">الحد الأقصى</th>' +
        '<th style="padding:10px 8px;">الامتدادات المسموحة</th>' +
        '<th style="padding:10px 8px;">الإجراء</th>' +
        '</tr></thead><tbody>' +
        types.map(t =>
          '<tr style="border-bottom:1px solid #e2e8f0;">' +
          '<td style="padding:10px 8px;font-weight:600;">' + omEscape(t.label_ar) + '</td>' +
          '<td style="padding:10px 8px;font-family:monospace;font-size:12px;">' + omEscape(t.key) + '</td>' +
          '<td style="padding:10px 8px;">' + (t.max_size_mb || 25) + ' <span>ميجابايت</span></td>' +
          '<td style="padding:10px 8px;font-size:12px;color:#64748b;">' + omEscape(t.allowed_extensions || 'جميع الامتدادات المدعومة') + '</td>' +
          '<td style="padding:10px 8px;">' +
          '<button type="button" class="btn small ghost" onclick="omUpdateFileTypePrompt(\'' + omEscape(t.key) + '\', \'' + omEscape(t.label_ar) + '\', ' + (t.max_size_mb || 25) + ', \'' + omEscape(t.allowed_extensions || '') + '\')">تعديل الحد</button>' +
          '</td></tr>'
        ).join('') +
        '</tbody></table></div>';
    }

    async function omUpdateFileTypePrompt(key, label, currentMaxMb, currentExts) {
      const newMbStr = prompt(WFT('file_types.max_prompt', 'الحد الأقصى بالـ MB لنوع ({label}):', { label }), currentMaxMb);
      if (!newMbStr) return;
      const newMb = parseInt(newMbStr, 10);
      if (isNaN(newMb) || newMb <= 0) { toast(WFT('common.invalid_value', 'قيمة غير صالحة')); return; }
      const res = await api('POST', '/api/file-types/' + encodeURIComponent(key), {
        labelAr: label,
        maxSizeMb: newMb,
        allowedExtensions: currentExts
      }).catch(e => e);
      if (res && res.success) {
        toast(WFT('file_types.updated', 'تم تحديث حد نوع الملف'));
        await omLoadFileTypes();
      } else {
        toast((res && res.error) || 'تعذر التحديث');
      }
    }

    // ── Super-admin pages: recharge queue, support inbox, platform settings ──

    async function openAdminRechargePage() {
      showTenantPage('tenantAdminRechargePage');
      await adminLoadRecharges();
    }

    async function adminLoadRecharges() {
      const box = document.getElementById('sagRechargeRequestsList');
      if (!box) return;
      await omLoadRechargeRequests('sagRechargeRequestsList');
      const data = await api('GET', '/api/admin/recharge-requests').catch(() => null);
      const requests = (data && data.success && data.requests) ? data.requests : [];
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      set('adminStatRechargePending', requests.filter(r => r.status === 'pending').length);
      set('adminStatRechargeApproved', requests.filter(r => r.status === 'approved').length);
      set('adminStatRechargeRejected', requests.filter(r => r.status === 'rejected').length);
    }

    async function openAdminTicketsPage() {
      showTenantPage('tenantAdminTicketsPage');
      const detail = document.getElementById('adminTicketDetail');
      if (detail) detail.style.display = 'none';
      await adminLoadTickets();
    }

    async function adminLoadTickets() {
      const box = document.getElementById('adminTicketsList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const status = (document.getElementById('adminTicketsStatusFilter') || {}).value || '';
      const url = '/api/admin/support/tickets' + (status ? '?status=' + encodeURIComponent(status) : '');
      const data = await api('GET', url).catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل التذاكر.</p>';
        return;
      }
      const tickets = data.tickets || [];
      const openCount = tickets.filter(t => !['resolved', 'closed'].includes(t.status)).length;
      const openEl = document.getElementById('adminStatTicketsOpen');
      if (openEl) openEl.textContent = openCount;
      if (!tickets.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تذاكر دعم.</p>';
        return;
      }
      const priorityLabels = { urgent: 'حرجة', high: 'عاجلة', normal: 'عادية', low: 'منخفضة' };
      box.innerHTML = tickets.map(t => {
        return '<div class="tenant-presentation-card" style="cursor:pointer" role="button" tabindex="0" onclick="adminOpenTicket(\'' + t.id + '\')">' +
          '<div><h3>#' + omEscape(t.number) + ' ' + omEscape(t.subject) + '</h3>' +
          '<div class="meta"><span style="font-weight:700">' + omEscape(t.tenant_name || 'شركة') + '</span>' +
          ' | <span>' + omStatus(t.status) + '</span>' +
          ' | <span>الأولوية:</span> <span>' + omEscape(priorityLabels[t.priority] || t.priority) + '</span>' +
          '</div></div></div>';
      }).join('');
    }

    async function adminOpenTicket(id) {
      const detail = document.getElementById('adminTicketDetail');
      if (!detail) return;
      detail.style.display = 'block';
      detail.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/admin/support/tickets/' + id).catch(() => null);
      if (!data || !data.success) {
        detail.innerHTML = '<p class="tenant-hint">تعذر فتح التذكرة.</p>';
        return;
      }
      const t = data.ticket || {};
      const messages = (t.messages || []).map(m =>
        '<div style="border-top:1px solid var(--line);padding:8px 0">' +
        '<strong style="font-size:12px">' + omEscape(m.author_name) + '</strong>' +
        (m.author_role === 'support' ? ' <span style="font-size:11px;color:var(--p)">(فريق المنصة)</span>' : '') +
        ' <span style="font-size:11px;color:var(--muted)">' + omEscape((m.created_at || '').slice(0, 16).replace('T', ' ')) + '</span>' +
        '<p style="margin:4px 0 0;font-size:13px">' + omEscape(m.body) + '</p></div>'
      ).join('');
      const statusActions = t.status !== 'closed'
        ? '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:10px 0">' +
          '<button type="button" class="btn small ghost" onclick="adminSetTicketStatus(\'' + id + '\', \'in_progress\')">قيد المعالجة</button>' +
          '<button type="button" class="btn small green" onclick="adminSetTicketStatus(\'' + id + '\', \'resolved\')">تم الحل</button>' +
          '<button type="button" class="btn small danger" onclick="adminSetTicketStatus(\'' + id + '\', \'closed\')">إغلاق</button>' +
          '</div>' +
          '<div style="display:flex;gap:8px"><input type="text" id="adminReplyBody" style="flex:1">' +
          '<button class="btn primary" onclick="adminReplyTicket(\'' + id + '\')">إرسال</button></div>'
        : '';
      detail.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">' +
        '<h3 style="margin:0">#' + omEscape(t.number) + ' ' + omEscape(t.subject) + ' — <span>' + omStatus(t.status) + '</span></h3>' +
        '<button class="btn ghost" onclick="document.getElementById(\'adminTicketDetail\').style.display=\'none\'">إغلاق</button></div>' +
        '<div class="meta" style="margin-top:4px"><span>الشركة:</span> ' + omEscape(t.tenant_name || '') +
        ' | <span>الفئة:</span> ' + omEscape(t.category || 'عامة') +
        ' | <span>المكلف:</span> <span id="adminTicketAssignee">' + omEscape(t.assignee_name || '—') + '</span></div>' +
        '<div id="adminTicketAssignRow" style="display:flex;gap:8px;margin:10px 0;align-items:center"></div>' +
        '<div style="margin:12px 0">' + (messages || '<p class="tenant-hint">لا رسائل.</p>') + '</div>' +
        statusActions;
      detail.scrollIntoView({ block: 'nearest' });
      const tenantUsers = await api('GET', '/api/admin/tenants/' + t.tenant_id + '/users').catch(() => null);
      const assignRow = document.getElementById('adminTicketAssignRow');
      const users = (tenantUsers && tenantUsers.success && tenantUsers.users) ? tenantUsers.users : [];
      if (assignRow && users.length && t.status !== 'closed') {
        assignRow.innerHTML = '<select id="adminTicketAssignSelect" style="flex:1">' +
          users.map(u => '<option value="' + omEscape(u.id) + '"' +
            (String(u.id) === String(t.assigned_to) ? ' selected' : '') + '>' +
            omEscape(u.name || u.email) + '</option>').join('') + '</select>' +
          '<button type="button" class="btn small ghost" onclick="adminAssignTicket(\'' + id + '\')">إسناد</button>';
      } else if (assignRow) {
        assignRow.innerHTML = '';
      }
    }

    async function adminAssignTicket(id) {
      const select = document.getElementById('adminTicketAssignSelect');
      const assigneeId = (select || {}).value || '';
      const res = await api('POST', '/api/admin/support/tickets/' + id + '/assign', { assigneeId }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر إسناد التذكرة'); return; }
      toast(WFT('tickets.assigned', 'تم إسناد التذكرة'));
      await adminOpenTicket(id);
      await adminLoadTickets();
    }

    async function adminReplyTicket(id) {
      const input = document.getElementById('adminReplyBody');
      const body = (input || {}).value || '';
      if (!body.trim()) return;
      const res = await api('POST', '/api/admin/support/tickets/' + id + '/messages', { body: body.trim() }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر إرسال الرد'); return; }
      await adminOpenTicket(id);
      await adminLoadTickets();
    }

    async function adminSetTicketStatus(id, status) {
      const res = await api('POST', '/api/admin/support/tickets/' + id + '/status', { status }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر تحديث الحالة'); return; }
      await adminOpenTicket(id);
      await adminLoadTickets();
    }

    async function openAdminPlatformPage() {
      showTenantPage('tenantAdminPlatformPage');
      await Promise.all([omLoadFileTypes(), adminLoadPackages()]);
    }

    // ── Packages & pricing (t53): admin CRUD, deactivate keeps references ──
    async function adminLoadPackages() {
      const box = document.getElementById('adminPackagesList');
      if (!box) return;
      const data = await api('GET', '/api/admin/packages').catch(() => null);
      const packages = (data && data.success && data.packages) ? data.packages : [];
      if (!packages.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد باقات مسجلة.</p>';
        return;
      }
      box.innerHTML = packages.map(p =>
        '<div class="tenant-presentation-card" style="margin-bottom:8px"><div><h3>' + omEscape(p.name) + '</h3>' +
        '<div class="meta"><span>' + (p.price_sar != null ? omEscape(String(p.price_sar)) + ' <span>ريال</span>' : 'بلا سعر') + '</span>' +
        ' | <span>' + omEscape(String(p.credit_usd || 0)) + ' <span>دولار رصيد</span></span>' +
        ' | <span>' + (p.is_active ? 'نشطة' : 'موقوفة') + '</span></div></div>' +
        '<div class="tenant-actions"><button type="button" class="btn small ' + (p.is_active ? 'danger' : 'green') +
        '" onclick="adminTogglePackage(\'' + omEscape(p.id) + '\', ' + (p.is_active ? 0 : 1) + ')">' +
        (p.is_active ? 'إيقاف' : 'تفعيل') + '</button></div></div>'
      ).join('');
    }

    async function adminSavePackage(event) {
      event.preventDefault();
      const res = await api('POST', '/api/admin/packages', {
        name: document.getElementById('adminPackageName').value.trim(),
        priceSar: Number(document.getElementById('adminPackagePrice').value),
        creditUsd: Number(document.getElementById('adminPackageCredit').value),
        isCustom: true
      }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر حفظ الباقة'); return; }
      document.getElementById('adminPackageName').value = '';
      toast(WFT('packages.saved', 'تم حفظ الباقة'));
      await adminLoadPackages();
    }

    async function adminTogglePackage(packageId, active) {
      const res = await api('PUT', '/api/admin/packages/' + packageId, { isActive: !!active }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر تحديث الباقة'); return; }
      await adminLoadPackages();
    }
