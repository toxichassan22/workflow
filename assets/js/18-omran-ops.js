/* 18-omran-ops.js - t40/t50 operations page: event tasks, notifications,
   support tickets. Shared global scope, classic scripts in order. */

    function omEscape(text) {
      return String(text == null ? '' : text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function omStatus(status) {
      const labels = {
        open: 'مفتوحة', completed: 'منجزة', cancelled: 'ملغاة',
        pending: 'قيد المراجعة', approved: 'معتمد', rejected: 'مرفوض',
        in_progress: 'قيد المعالجة', resolved: 'تم الحل', closed: 'مغلقة',
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
      }
    }

    function closeOmModal(id) {
      const m = document.getElementById(id);
      if (m) m.style.display = 'none';
    }

    function showOmranOpsTab(tabKey) {
      const tabs = ['tasks', 'recharge', 'tickets', 'contracts'];
      tabs.forEach(t => {
        const pane = document.getElementById('omTabPane_' + t);
        const btn = document.getElementById('omTabBtn_' + t);
        const isActive = (t === tabKey);
        if (pane) pane.style.display = isActive ? 'block' : 'none';
        if (btn) {
          if (isActive) {
            btn.classList.add('primary');
            btn.classList.remove('ghost');
          } else {
            btn.classList.add('ghost');
            btn.classList.remove('primary');
          }
        }
      });
    }

    async function openOmranOpsPage() {
      showTenantPage('tenantOmranOpsPage');
      showOmranOpsTab('tasks');

      await Promise.all([
        omLoadEventTasks(),
        omLoadNotifications(),
        omLoadTickets(),
        omLoadRechargeRequests(),
        omLoadContracts()
      ]);
    }

    // ── Event tasks ──────────────────────────────────────────────────────
    async function omLoadEventTasks() {
      const box = document.getElementById('omTasksList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/event-tasks').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل المهام.</p>';
        return;
      }
      const tasks = data.tasks || [];
      const openCount = tasks.filter(t => t.status === 'open').length;
      const stat = document.getElementById('omStatTasks');
      if (stat) stat.textContent = openCount;

      if (!tasks.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد مهام بعد.</p>';
        return;
      }
      const myUserId = String((tenantUser && tenantUser._userId) || '');
      const myActorId = myUserId || ('tenant-admin:' + ((tenantUser && tenantUser.id) || ''));
      const canManageTasks = hasPermission('manage_users');
      box.innerHTML = tasks.map(t => {
        const due = (t.due_at || t.event_date || '').slice(0, 16).replace('T', ' ');
        const recurring = t.recurrence && t.recurrence !== 'none'
          ? ' | <span>متكررة:</span> ' + ({ daily: 'يوميًا', weekly: 'أسبوعيًا', monthly: 'شهريًا' }[t.recurrence] || t.recurrence)
          : '';
        const action = t.status === 'open' &&
          (canManageTasks || String(t.assignee_user_id || '') === myUserId || String(t.created_by || '') === myActorId)
          ? '<button class="btn ghost" onclick="omCompleteTask(\'' + t.id + '\')">إتمام</button>'
          : '';
        return '<div class="tenant-presentation-card"><div><h3>' + omEscape(t.title) + '</h3>' +
          '<div class="meta"><span>' + omStatus(t.status) + '</span>' +
          (due ? ' | <span>الاستحقاق:</span> ' + omEscape(due) : '') + recurring + '</div></div>' +
          '<div>' + action + '</div></div>';
      }).join('');
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
        const sla = t.sla_due_at ? (' | <span>استحقاق SLA:</span> ' + omEscape(t.sla_due_at.slice(0, 16).replace('T', ' '))) : '';
        return '<div class="tenant-presentation-card" style="cursor:pointer" onclick="omOpenTicket(\'' + t.id + '\')">' +
          '<div><h3>#' + omEscape(t.number) + ' ' + omEscape(t.subject) + '</h3>' +
          '<div class="meta"><span>' + omStatus(t.status) + '</span> | <span>الأولوية:</span> <span>' + omEscape(priorityLabels[t.priority] || t.priority) + '</span>' + sla + '</div></div></div>';
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
      const data = await api('POST', '/api/support/tickets', { subject: subject.trim(), body: body.trim(), category: 'general' }).catch(e => e);
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

    // ── Recharge requests (t33, d09) ──────────────────────────────────────
    async function omLoadRechargeRequests(targetBoxId) {
      const box = document.getElementById(targetBoxId || 'omRechargeList');
      if (!box) return;
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

    async function omCreateRechargeRequest() {
      const pkg = (document.getElementById('omRechargePackage') || {}).value || 'باقة نمو';
      const ref = (document.getElementById('omRechargeRef') || {}).value || '';
      const errBox = document.getElementById('omRechargeError');
      if (errBox) errBox.textContent = '';
      const amounts = {
        'باقة نمو': { usd: 100, sar: 375 },
        'باقة شركات': { usd: 250, sar: 937.5 },
        'باقة احترافية': { usd: 500, sar: 1875 }
      };
      const sel = amounts[pkg] || { usd: 100, sar: 375 };
      const data = await api('POST', '/api/recharge-requests', {
        packageName: pkg,
        amountUsd: sel.usd,
        priceSar: sel.sar,
        referenceNumber: ref.trim()
      }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر إرسال الطلب.';
        return;
      }
      if (document.getElementById('omRechargeRef')) document.getElementById('omRechargeRef').value = '';
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
      const expiresAt = (document.getElementById('omContractExpires') || {}).value || '';
      const errBox = document.getElementById('omContractError');
      if (errBox) errBox.textContent = '';
      if (!title.trim()) {
        if (errBox) errBox.textContent = 'مسمى العقد مطلوب.';
        return;
      }
      const data = await api('POST', '/api/contracts', {
        title: title.trim(),
        kind: kind,
        expiresAt: expiresAt || null
      }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر حفظ العقد.';
        return;
      }
      if (document.getElementById('omContractTitle')) document.getElementById('omContractTitle').value = '';
      if (document.getElementById('omContractExpires')) document.getElementById('omContractExpires').value = '';
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
      const overdueCount = tickets.filter(t => t.sla_overdue).length;
      const openEl = document.getElementById('adminStatTicketsOpen');
      const overdueEl = document.getElementById('adminStatTicketsOverdue');
      if (openEl) openEl.textContent = openCount;
      if (overdueEl) overdueEl.textContent = overdueCount;
      if (!tickets.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تذاكر دعم.</p>';
        return;
      }
      const priorityLabels = { urgent: 'حرجة', high: 'عاجلة', normal: 'عادية', low: 'منخفضة' };
      box.innerHTML = tickets.map(t => {
        const sla = t.sla_due_at
          ? (' | <span' + (t.sla_overdue ? ' style="color:#c33;font-weight:700"' : '') + '>استحقاق SLA:</span> ' +
             omEscape(t.sla_due_at.slice(0, 16).replace('T', ' ')))
          : '';
        return '<div class="tenant-presentation-card" style="cursor:pointer" onclick="adminOpenTicket(\'' + t.id + '\')">' +
          '<div><h3>#' + omEscape(t.number) + ' ' + omEscape(t.subject) + '</h3>' +
          '<div class="meta"><span style="font-weight:700">' + omEscape(t.tenant_name || 'شركة') + '</span>' +
          ' | <span>' + omStatus(t.status) + '</span>' +
          ' | <span>الأولوية:</span> <span>' + omEscape(priorityLabels[t.priority] || t.priority) + '</span>' + sla +
          (t.sla_overdue ? ' | <span style="color:#c33;font-weight:700">متأخرة</span>' : '') +
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
        '<div class="meta" style="margin-top:4px"><span>الشركة:</span> ' + omEscape(t.tenant_name || '') + '</div>' +
        '<div style="margin:12px 0">' + (messages || '<p class="tenant-hint">لا رسائل.</p>') + '</div>' +
        statusActions;
      detail.scrollIntoView({ block: 'nearest' });
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
      await Promise.all([omLoadFileTypes(), adminLoadSlaPolicies(), adminLoadFeatureFlags()]);
    }

    // ── SLA policies (d08): response/resolve targets per priority ──
    async function adminLoadSlaPolicies() {
      const box = document.getElementById('adminSlaPoliciesList');
      if (!box) return;
      const data = await api('GET', '/api/admin/support/sla-policies').catch(() => null);
      const policies = (data && data.success && data.policies) ? data.policies : [];
      const priorityLabels = { urgent: 'حرجة', high: 'عاجلة', normal: 'عادية', low: 'منخفضة' };
      if (!policies.length) {
        box.innerHTML = '<p class="tenant-hint">الأهداف الافتراضية مطبقة: حرجة ٤/٢٤، عاجلة ٨/٤٨، عادية ٢٤/٧٢، منخفضة ٤٨/١٢٠ ساعة.</p>';
        return;
      }
      box.innerHTML =
        '<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;">' +
        '<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:right;">' +
        '<thead><tr style="background:#f8fafc;border-bottom:1px solid #e2e8f0;color:#475569;">' +
        '<th style="padding:10px 8px;">الأولوية</th><th style="padding:10px 8px;">الباقة</th>' +
        '<th style="padding:10px 8px;">أول استجابة</th><th style="padding:10px 8px;">الحل</th>' +
        '</tr></thead><tbody>' +
        policies.map(p =>
          '<tr style="border-bottom:1px solid #e2e8f0;">' +
          '<td style="padding:10px 8px;font-weight:600;">' + omEscape(priorityLabels[p.priority] || p.priority) + '</td>' +
          '<td style="padding:10px 8px;">' + omEscape(p.package_name || 'الكل') + '</td>' +
          '<td style="padding:10px 8px;">' + (p.first_response_hours || 0) + ' <span>ساعة</span></td>' +
          '<td style="padding:10px 8px;">' + (p.resolve_hours || 0) + ' <span>ساعة</span></td></tr>'
        ).join('') +
        '</tbody></table></div>';
    }

    async function adminSaveSlaPolicy(event) {
      event.preventDefault();
      const res = await api('PUT', '/api/admin/support/sla-policies', {
        priority: document.getElementById('adminSlaPriority').value,
        firstResponseHours: Number(document.getElementById('adminSlaFirstResponse').value),
        resolveHours: Number(document.getElementById('adminSlaResolve').value)
      }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || WFT('sla.save_failed', 'تعذر حفظ الهدف')); return; }
      toast(WFT('sla.saved', 'تم حفظ هدف الاستجابة'));
      await adminLoadSlaPolicies();
    }

    // ── Feature flags (t62): platform-wide switches with rollback history ──
    async function adminLoadFeatureFlags() {
      const box = document.getElementById('adminFeatureFlagsList');
      if (!box) return;
      const data = await api('GET', '/api/admin/feature-flags').catch(() => null);
      const flags = (data && data.success && data.flags) ? data.flags : [];
      if (!flags.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد مفاتيح ميزات مسجلة.</p>';
        return;
      }
      box.innerHTML = flags.map(f =>
        '<div class="tenant-presentation-card" style="margin-bottom:8px"><div><h3>' + omEscape(f.flag_key) + '</h3>' +
        '<div class="meta"><span>' + (f.tenant_id ? 'شركة محددة' : 'المنصة') + '</span>' +
        ' | <span>' + omEscape((f.updated_at || '').slice(0, 16).replace('T', ' ')) + '</span></div></div>' +
        '<div class="tenant-actions"><button type="button" class="btn small ' + (f.enabled ? 'danger' : 'green') +
        '" onclick="adminToggleFeatureFlag(\'' + omEscape(f.flag_key) + '\', ' + (f.enabled ? 0 : 1) + ', ' +
        (f.tenant_id ? ('\'' + omEscape(f.tenant_id) + '\'') : 'null') + ')">' +
        (f.enabled ? 'إيقاف' : 'تفعيل') + '</button></div></div>'
      ).join('');
    }

    async function adminToggleFeatureFlag(flagKey, enabled, tenantId) {
      const res = await api('PUT', '/api/admin/feature-flags', {
        flag: flagKey, enabled: !!enabled, tenantId: tenantId || null
      }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر تحديث المفتاح'); return; }
      await adminLoadFeatureFlags();
    }

    async function adminAddFeatureFlag(event) {
      event.preventDefault();
      const res = await api('PUT', '/api/admin/feature-flags', {
        flag: document.getElementById('adminFlagKey').value.trim(),
        enabled: document.getElementById('adminFlagEnabled').value === '1'
      }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || WFT('flags.save_failed', 'تعذر حفظ المفتاح')); return; }
      document.getElementById('adminFlagKey').value = '';
      toast(WFT('flags.saved', 'تم حفظ مفتاح الميزة'));
      await adminLoadFeatureFlags();
    }
