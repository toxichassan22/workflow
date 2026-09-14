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
      };
      return labels[status] || status || '';
    }

    async function openOmranOpsPage() {
      showTenantPage('tenantOmranOpsPage');
      await Promise.all([omLoadEventTasks(), omLoadNotifications(), omLoadTickets()]);
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
      if (!tasks.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد مهام بعد.</p>';
        return;
      }
      box.innerHTML = tasks.map(t => {
        const due = (t.due_at || t.event_date || '').slice(0, 16).replace('T', ' ');
        const recurring = t.recurrence && t.recurrence !== 'none'
          ? ' | متكررة: ' + ({ daily: 'يوميًا', weekly: 'أسبوعيًا', monthly: 'شهريًا' }[t.recurrence] || t.recurrence)
          : '';
        const action = t.status === 'open'
          ? '<button class="btn ghost" onclick="omCompleteTask(\'' + t.id + '\')">إتمام</button>'
          : '';
        return '<div class="tenant-presentation-card"><div><h3>' + omEscape(t.title) + '</h3>' +
          '<div class="meta"><span>' + omStatus(t.status) + '</span>' +
          (due ? ' | <span>الاستحقاق: ' + omEscape(due) + '</span>' : '') + recurring + '</div></div>' +
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
      await omLoadEventTasks();
    }

    // ── Notifications ────────────────────────────────────────────────────
    async function omLoadNotifications() {
      const box = document.getElementById('omNotificationsList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/notifications').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل التنبيهات.</p>';
        return;
      }
      const items = data.notifications || [];
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
      if (!tickets.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تذاكر دعم.</p>';
        return;
      }
      box.innerHTML = tickets.map(t =>
        '<div class="tenant-presentation-card" style="cursor:pointer" onclick="omOpenTicket(\'' + t.id + '\')">' +
        '<div><h3>#' + omEscape(t.number) + ' ' + omEscape(t.subject) + '</h3>' +
        '<div class="meta"><span>' + omStatus(t.status) + '</span> | <span>الأولوية: ' + omEscape(t.priority) + '</span></div></div></div>'
      ).join('');
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
      detail.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<h3 style="margin:0">#' + omEscape(t.number) + ' ' + omEscape(t.subject) + ' — ' + omStatus(t.status) + '</h3>' +
        '<button class="btn ghost" onclick="document.getElementById(\'omTicketDetail\').style.display=\'none\'">إغلاق</button></div>' +
        '<div style="margin:12px 0">' + (messages || '<p class="tenant-hint">لا رسائل.</p>') + '</div>' +
        (t.status !== 'closed'
          ? '<div style="display:flex;gap:8px"><input type="text" id="omReplyBody" placeholder="اكتب ردك هنا" style="flex:1">' +
            '<button class="btn primary" onclick="omReplyTicket(\'' + id + '\')">إرسال</button></div>'
          : '');
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
      await omLoadTickets();
    }
