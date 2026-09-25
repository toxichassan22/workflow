/* 18-landloom-ops.js - t40/t50 operations page: event tasks, notifications,
   support tickets. Shared global scope, classic scripts in order. */

    function llEscape(text) {
      return String(text == null ? '' : text)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function llMoney(value) {
      // Money renders at halala precision — a raw float like 499.98750000000001
      // (stored by an old unrounded conversion) must never reach the screen.
      if (value == null || value === '') return '0';
      const n = Number(value);
      return Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '0';
    }

    function llStatus(status) {
      const labels = {
        open: 'مفتوحة', done: 'مغلقة', completed: 'منجزة', cancelled: 'ملغاة',
        pending: 'قيد المراجعة', approved: 'معتمد', rejected: 'مرفوض',
        in_progress: 'قيد المعالجة', resolved: 'تم الحل', closed: 'مغلقة',
        waiting_customer: 'بانتظار العميل', escalated: 'مصعّدة', reopened: 'معاد فتحها',
        consumed: 'مسوّى', expired: 'منتهية الصلاحية',
      };
      return labels[status] || status || '';
    }

    function openLlModal(id) {
      const m = document.getElementById(id);
      if (m) {
        m.style.display = 'flex';
        const err = m.querySelector('[id$="Error"]');
        if (err) err.textContent = '';
        if (typeof a11yModalDidOpen === 'function') a11yModalDidOpen(m);
      }
    }

    function closeLlModal(id) {
      const m = document.getElementById(id);
      if (m) {
        m.style.display = 'none';
        if (typeof a11yModalDidClose === 'function') a11yModalDidClose();
      }
    }

    const LANDLOOM_OPS_TABS = ['recharge', 'tickets'];
    let llActiveTab = 'recharge';

    function landloomOpsTabVisible(t) {
      const btn = document.getElementById('llTabBtn_' + t);
      return btn && btn.style.display !== 'none';
    }

    function showLandloomOpsTab(tabKey) {
      // Permission-gated tabs hide their button; a request for a hidden tab
      // lands on the first one the member may see.
      const target = landloomOpsTabVisible(tabKey)
        ? tabKey
        : (LANDLOOM_OPS_TABS.find(landloomOpsTabVisible) || 'recharge');
      llActiveTab = target;
      LANDLOOM_OPS_TABS.forEach(t => {
        const pane = document.getElementById('llTabPane_' + t);
        const btn = document.getElementById('llTabBtn_' + t);
        const isActive = (t === target);
        if (pane) pane.style.display = isActive ? 'block' : 'none';
        if (btn) {
          btn.classList.toggle('primary', isActive);
          btn.classList.toggle('ghost', !isActive);
        }
      });
      // The sidebar carries one link per tab, so its active marker follows
      // in-page tab switches too.
      const opsPage = document.getElementById('tenantLandloomOpsPage');
      if (opsPage && opsPage.classList.contains('active')) {
        if (typeof updateTenantChrome === 'function') updateTenantChrome('tenantLandloomOpsPage');
        // Remember the tab so a refresh on the operations route reopens it.
        if (typeof saveTenantNavigationState === 'function') saveTenantNavigationState('tenantLandloomOpsPage', { opsTab: target });
      }
    }

    async function openLandloomOpsPage(tabKey) {
      showTenantPage('tenantLandloomOpsPage');
      showLandloomOpsTab(tabKey || 'recharge');

      await Promise.all([
        llLoadTickets(),
        llLoadPointsOverview(),
        llLoadRechargeRequests()
      ]);
    }

    // ── Notifications ────────────────────────────────────────────────────
    async function llLoadNotifications(targetBoxId) {
      const box = document.getElementById(targetBoxId || 'llNotificationsList');
      if (!box) return;
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      const data = await api('GET', '/api/notifications').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل التنبيهات.</p>';
        return;
      }
      const items = data.notifications || [];
      const unreadCount = items.filter(n => !n.read_at).length;
      const noteStat = document.getElementById('llStatNotifications');
      if (noteStat) noteStat.textContent = unreadCount;
      if (!items.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تنبيهات.</p>';
        return;
      }
      box.innerHTML = items.map(n => notifCardHtml(n)).join('') +
      '<button class="btn ghost" onclick="llMarkAllRead()">' +
      llEscape(WFT('admin.mark_all_read', 'تحديد الكل كمقروء')) + '</button>';
    }

    async function llMarkAllRead() {
      await api('POST', '/api/notifications/read', {}).catch(() => null);
      await llLoadNotifications();
      await llLoadNotifications('adminNotificationsList');
    }

    // ── Support tickets ──────────────────────────────────────────────────
    async function llLoadTickets() {
      const box = document.getElementById('llTicketsList');
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
      const tStat = document.getElementById('llStatTickets');
      if (tStat) tStat.textContent = activeCount;

      if (!tickets.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تذاكر دعم.</p>';
        return;
      }
      box.innerHTML = tickets.map(t => {
        return '<div class="tenant-presentation-card" style="cursor:pointer" role="button" tabindex="0" onclick="llOpenTicket(\'' + t.id + '\')">' +
          '<div><h3>#' + llEscape(t.number) + ' ' + llEscape(t.subject) + '</h3>' +
          '<div class="meta"><span>' + llStatus(t.status) + '</span>' +
          (t.attachment_count ? ' | <span>' + llEscape(WFT('tickets.has_attachment', 'يحتوي مرفقًا')) + '</span>' : '') +
          '</div></div></div>';
      }).join('');
    }

    async function llOpenTicket(id) {
      const detail = document.getElementById('llTicketDetail');
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
        '<strong style="font-size:12px">' + llEscape(m.author_name) + '</strong> ' +
        '<span style="font-size:11px;color:var(--muted)">' + llEscape((m.created_at || '').slice(0, 16).replace('T', ' ')) + '</span>' +
        '<p style="margin:4px 0 0;font-size:13px">' + llEscape(m.body) + '</p></div>'
      ).join('');
      const attachments = (t.attachments || []).map(a =>
        '<button type="button" class="btn small ghost" onclick="llOpenTicketAttachment(\'' + id + '\',\'' + a.file_id + '\')">' +
        llEscape(a.original_name || WFT('tickets.attachment', 'مرفق')) + '</button>').join('');
      detail.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<h3 style="margin:0">#' + llEscape(t.number) + ' ' + llEscape(t.subject) + ' — <span>' + llStatus(t.status) + '</span></h3>' +
        '<button class="btn ghost" onclick="document.getElementById(\'llTicketDetail\').style.display=\'none\'">إغلاق</button></div>' +
        (attachments ? '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">' + attachments + '</div>' : '') +
        '<div style="margin:12px 0">' + (messages || '<p class="tenant-hint">لا رسائل.</p>') + '</div>' +
        (t.status !== 'closed'
          ? '<div style="display:flex;gap:8px"><input type="text" id="llReplyBody" style="flex:1">' +
            '<button class="btn primary" onclick="llReplyTicket(\'' + id + '\')">إرسال</button></div>'
          : '');
    }

    async function llOpenTicketAttachment(ticketId, fileId) {
      const token = getTenantToken();
      const response = await fetch(
        '/api/support/tickets/' + encodeURIComponent(ticketId) + '/attachments/' + encodeURIComponent(fileId),
        { headers: token ? { Authorization: 'Bearer ' + token } : {} });
      if (!response.ok) { toast(WFT('downloads.load_failed', 'تعذر تحميل الملف')); return; }
      window.open(URL.createObjectURL(await response.blob()), '_blank');
    }

    async function adminOpenTicketAttachment(ticketId, fileId) {
      const token = getTenantToken();
      const response = await fetch(
        '/api/admin/support/tickets/' + encodeURIComponent(ticketId) + '/attachments/' + encodeURIComponent(fileId),
        { headers: token ? { Authorization: 'Bearer ' + token } : {} });
      if (!response.ok) { toast(WFT('downloads.load_failed', 'تعذر تحميل الملف')); return; }
      window.open(URL.createObjectURL(await response.blob()), '_blank');
    }

    async function llReplyTicket(id) {
      const input = document.getElementById('llReplyBody');
      const body = (input || {}).value || '';
      if (!body.trim()) return;
      await api('POST', '/api/support/tickets/' + id + '/messages', { body: body.trim() }).catch(() => null);
      await llOpenTicket(id);
      await llLoadTickets();
    }

    async function llUploadTicketAttachment() {
      const input = document.getElementById('llTicketAttachment');
      if (!input || !input.files || !input.files[0]) return null;
      const form = new FormData();
      form.append('file', input.files[0]);
      form.append('fileType', 'ticket_attachment');
      const data = await api('POST', '/api/project-files', form, true).catch(e => e);
      if (!data || !data.success) return { error: (data && data.error) || WFT('tickets.attachment_failed', 'تعذر رفع المرفق') };
      return data.file;
    }

    async function llCreateTicket() {
      const subject = (document.getElementById('llTicketSubject') || {}).value || '';
      const body = (document.getElementById('llTicketBody') || {}).value || '';
      const errBox = document.getElementById('llTicketsError');
      if (errBox) errBox.textContent = '';
      const category = (document.getElementById('llTicketCategory') || {}).value || 'general';
      const attachment = await llUploadTicketAttachment();
      if (attachment && attachment.error) {
        if (errBox) errBox.textContent = attachment.error;
        return;
      }
      const data = await api('POST', '/api/support/tickets', {
        subject: subject.trim(), body: body.trim(), category: category,
        attachmentFileId: attachment ? attachment.id : null
      }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر إنشاء التذكرة.';
        return;
      }
      document.getElementById('llTicketSubject').value = '';
      document.getElementById('llTicketBody').value = '';
      const attInput = document.getElementById('llTicketAttachment');
      if (attInput) attInput.value = '';
      closeLlModal('llTicketModal');
      toast(WFT('tickets.created', 'تم إرسال تذكرة الدعم بنجاح'));
      await llLoadTickets();
    }

    // ── Wallet overview: the four riyal figures ───────────────────────────
    async function llLoadPointsOverview() {
      const box = document.getElementById('llPointsOverview');
      if (!box) return;
      if (!hasPermission('billing')) { box.innerHTML = ''; return; }
      const data = await api('GET', '/api/client/overview').catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '';
        return;
      }
      const fmt = (v) => (v == null ? '0' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }));
      const cycleConsumed = (data.package && data.package.consumed_sar != null)
        ? data.package.consumed_sar
        : ((data.lifetime || {}).consumed_sar || 0);
      const card = (label, value) =>
        '<div class="tenant-dash-card stat"><p>' + label + '</p><h3>' + llEscape(fmt(value)) +
        ' <span style="font-size:12px;font-weight:400;color:#64748b;">ريال</span></h3></div>';
      box.innerHTML = '<div class="tenant-dashboard-stats">' +
        card('الرصيد الحالي', data.balance_sar) +
        card('المحجوز', data.reserved_sar) +
        card('المستهلك', cycleConsumed) +
        card('إجمالي المستهلك', (data.lifetime || {}).consumed_sar) +
        '</div>';
    }

    // ── Recharge requests (t33, d09) ──────────────────────────────────────
    async function llOpenRechargeAttachment(requestId, slot) {
      const token = getTenantToken();
      const response = await fetch(
        '/api/recharge-requests/' + encodeURIComponent(requestId) + '/attachment/' + slot,
        { headers: token ? { Authorization: 'Bearer ' + token } : {} });
      if (!response.ok) { toast(WFT('downloads.load_failed', 'تعذر تحميل الملف')); return; }
      window.open(URL.createObjectURL(await response.blob()), '_blank');
    }

    async function llLoadRechargeRequests(targetBoxId) {
      const box = document.getElementById(targetBoxId || 'llRechargeList');
      if (!box) return;
      if (!hasPermission('billing')) { box.innerHTML = ''; return; }
      box.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      // The platform flag on the session is authoritative — a permission grant
      // can be stale or wrong, isAdmin comes straight from the token check.
      const isAdmin = (typeof tenantUser !== 'undefined' && tenantUser && tenantUser.isAdmin) || targetBoxId === 'sagRechargeRequestsList';
      const filterId = isAdmin ? 'sagRechargeStatusFilter' : 'llRechargeStatusFilter';
      const status = (document.getElementById(filterId) || {}).value || '';
      const base = isAdmin ? '/api/admin/recharge-requests' : '/api/recharge-requests';
      const url = base + (status ? '?status=' + encodeURIComponent(status) : '');
      const data = await api('GET', url).catch(() => null);
      if (!data || !data.success) {
        box.innerHTML = '<p class="tenant-hint">تعذر تحميل طلبات الشحن.' +
          (data && data.error ? ' ' + llEscape(data.error) : '') + '</p>';
        return;
      }
      const requests = data.requests || [];
      const pendingCount = requests.filter(r => r.status === 'pending').length;
      const rStat = document.getElementById('llStatRecharges');
      if (rStat) rStat.textContent = pendingCount;

      if (!requests.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد طلبات شحن بعد.</p>';
        return;
      }
      box.innerHTML = requests.map(r => {
        const date = (r.requested_at || r.created_at || '').slice(0, 16).replace('T', ' ');
        const tenantInfo = (isAdmin && (r.tenant_name || r.company_name)) ? ('<span>الشركة:</span> ' + llEscape(r.tenant_name || r.company_name) + ' | ') : '';
        const ref = r.transfer_reference ? (' | <span>المرجع البنكي:</span> ' + llEscape(r.transfer_reference)) : '';
        const inv = r.reference_number ? (' | <span style="color:#1c7a2e;font-weight:600;">سند مالي:</span> ' + llEscape(r.reference_number)) : '';
        const receiptLink = r.receipt_file_id
          ? ' | <a href="#" onclick="llOpenRechargeAttachment(\'' + r.id + '\', \'receipt\');return false;">إيصال التحويل</a>' : '';
        const invoiceLink = r.invoice_file_id
          ? ' | <a href="#" onclick="llOpenRechargeAttachment(\'' + r.id + '\', \'invoice\');return false;">الفاتورة</a>' : '';
        const note = (r.status === 'rejected' && r.decision_note)
          ? '<div class="meta" style="color:var(--danger,#c0392b);margin-top:4px"><span>سبب الرفض:</span> ' + llEscape(r.decision_note) + '</div>' : '';
        const actions = (isAdmin && r.status === 'pending')
          ? '<div style="display:flex;gap:6px;margin-top:6px;">' +
            '<button type="button" class="btn small green" onclick="llDecideRecharge(\'' + r.id + '\', \'approved\')">اعتماد الطلب</button>' +
            '<button type="button" class="btn small danger" onclick="llDecideRecharge(\'' + r.id + '\', \'rejected\')">رفض</button>' +
            '</div>'
          : '';
        return '<div class="tenant-presentation-card">' +
          '<div><h3><span>' + llEscape(r.package_name) + '</span> — ' + (llMoney(r.price_sar != null ? r.price_sar : r.amount_sar) + ' <span>ريال</span>') + '</h3>' +
          '<div class="meta">' + tenantInfo + '<span>' + llStatus(r.status) + '</span> | <span>' + llEscape(date) + '</span>' + ref + inv + receiptLink + invoiceLink + '</div>' +
          note +
          actions +
          '</div></div>';
      }).join('');
    }

    let llRechargePackages = [];

    async function llLoadRechargePackages() {
      const select = document.getElementById('llRechargePackage');
      if (!select) return;
      const data = await api('GET', '/api/billing/packages').catch(() => null);
      llRechargePackages = (data && data.success && data.packages) || [];
      if (!llRechargePackages.length) {
        select.innerHTML = '<option value="" disabled selected>' +
          llEscape(WFT('recharge.no_packages', 'لا توجد باقات متاحة')) + '</option>';
        llShowPackageInfo();
        return;
      }
      select.innerHTML = llRechargePackages.map(p =>
        '<option value="' + llEscape(p.id) + '">' + llEscape(p.name) +
        ' (' + llMoney(p.credit_sar) + ' <span>ريال</span>' +
        (p.price_sar ? ' — ' + llMoney(p.price_sar) + ' <span>ريال</span>' : '') + ')</option>'
      ).join('');
      llShowPackageInfo();
    }

    function llShowPackageInfo() {
      const box = document.getElementById('llRechargePackageInfo');
      const select = document.getElementById('llRechargePackage');
      if (!box || !select) return;
      const pkg = llRechargePackages.find(p => p.id === select.value);
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

    async function llUploadRechargeReceipt() {
      const input = document.getElementById('llRechargeReceipt');
      if (!input || !input.files || !input.files[0]) return null;
      const form = new FormData();
      form.append('file', input.files[0]);
      form.append('fileType', 'recharge_receipt');
      const data = await api('POST', '/api/project-files', form, true).catch(e => e);
      if (!data || !data.success) return { error: (data && data.error) || 'تعذر رفع الإيصال' };
      return data.file;
    }

    async function llCreateRechargeRequest() {
      const packageId = (document.getElementById('llRechargePackage') || {}).value || '';
      const ref = (document.getElementById('llRechargeRef') || {}).value || '';
      const receiptInput = document.getElementById('llRechargeReceipt');
      const hasReceipt = !!(receiptInput && receiptInput.files && receiptInput.files[0]);
      const errBox = document.getElementById('llRechargeError');
      if (errBox) errBox.textContent = '';
      if (!packageId) {
        if (errBox) errBox.textContent = WFT('recharge.package_required', 'اختر الباقة المطلوب شراؤها');
        return;
      }
      if (!ref.trim() && !hasReceipt) {
        if (errBox) errBox.textContent = WFT('recharge.reference_or_receipt_required', 'رقم الحوالة أو إيصال التحويل مطلوب');
        return;
      }
      const receipt = await llUploadRechargeReceipt();
      if (receipt && receipt.error) {
        if (errBox) errBox.textContent = receipt.error;
        return;
      }
      const pkg = llRechargePackages.find(p => p.id === packageId);
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
      if (document.getElementById('llRechargeRef')) document.getElementById('llRechargeRef').value = '';
      if (document.getElementById('llRechargeReceipt')) document.getElementById('llRechargeReceipt').value = '';
      closeLlModal('llRechargeModal');
      toast(WFT('recharge.request_sent', 'تم إرسال طلب الشحن بنجاح'));
      await llLoadRechargeRequests();
    }

    // ── Recharge decision modal: approve (optional invoice) or reject (reason) ──
    async function llDecideRecharge(requestId, decision) {
      document.getElementById('llRechargeDecisionId').value = requestId;
      document.getElementById('llRechargeDecisionKind').value = decision;
      const isApprove = decision === 'approved';
      document.getElementById('llRechargeDecisionTitle').textContent =
        isApprove ? 'اعتماد طلب الشحن' : 'رفض طلب الشحن';
      document.getElementById('llRechargeInvoiceField').style.display = isApprove ? '' : 'none';
      document.getElementById('llRechargeReasonField').style.display = isApprove ? 'none' : '';
      document.getElementById('llRechargeNoteField').style.display = isApprove ? 'none' : '';
      const err = document.getElementById('llRechargeDecisionError');
      if (err) err.textContent = '';
      const invoice = document.getElementById('llRechargeInvoice');
      if (invoice) invoice.value = '';
      const note = document.getElementById('llRechargeNote');
      if (note) note.value = '';
      if (!isApprove) {
        const select = document.getElementById('llRechargeReason');
        const data = await api('GET', '/api/admin/settings/rejection-reasons').catch(() => null);
        const reasons = (data && data.success && data.reasons) || [];
        select.innerHTML = '<option value="">—</option>' +
          reasons.map(r => '<option value="' + llEscape(r) + '">' + llEscape(r) + '</option>').join('');
      }
      openLlModal('llRechargeDecisionModal');
    }

    async function llSubmitRechargeDecision() {
      const requestId = document.getElementById('llRechargeDecisionId').value;
      const decision = document.getElementById('llRechargeDecisionKind').value;
      const errBox = document.getElementById('llRechargeDecisionError');
      if (errBox) errBox.textContent = '';
      let invoiceFileId = null;
      let note = '';
      if (decision === 'approved') {
        const input = document.getElementById('llRechargeInvoice');
        if (input && input.files && input.files[0]) {
          const form = new FormData();
          form.append('file', input.files[0]);
          form.append('fileType', 'recharge_invoice');
          const up = await api('POST', '/api/project-files', form, true).catch(e => e);
          if (!up || !up.success) {
            if (errBox) errBox.textContent = (up && up.error) || 'تعذر رفع الفاتورة';
            return;
          }
          invoiceFileId = up.file.id;
        }
      } else {
        const reason = (document.getElementById('llRechargeReason') || {}).value || '';
        const extra = ((document.getElementById('llRechargeNote') || {}).value || '').trim();
        note = reason && extra ? reason + ' — ' + extra : (reason || extra);
      }
      const payload = { decision: decision };
      if (invoiceFileId) payload.invoiceFileId = invoiceFileId;
      if (note) payload.note = note;
      const data = await api('POST', '/api/admin/recharge-requests/' + encodeURIComponent(requestId) + '/decision', payload).catch(e => e);
      if (data && data.success) {
        closeLlModal('llRechargeDecisionModal');
        toast(decision === 'approved' ? WFT('recharge.approved', 'تم اعتماد الشحن وتوليد الرقم المرجعي المالي') : WFT('recharge.rejected', 'تم رفض طلب الشحن'));
        if (typeof adminLoadRecharges === 'function') await adminLoadRecharges();
        if (typeof llLoadRechargeRequests === 'function') await llLoadRechargeRequests('llRechargeList');
      } else {
        const msg = (data && data.error) || WFT('recharge.decision_failed', 'تعذر تسجيل القرار');
        if (errBox) { errBox.textContent = msg; } else { toast(msg); }
      }
    }

    // ── File types registry (t62, d10) — lives on the platform settings page ──
    async function llLoadFileTypes(targetBoxId) {
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
          '<td style="padding:10px 8px;font-weight:600;">' + llEscape(t.label_ar) + '</td>' +
          '<td style="padding:10px 8px;font-family:monospace;font-size:12px;">' + llEscape(t.key) + '</td>' +
          '<td style="padding:10px 8px;">' + (t.max_size_mb || 25) + ' <span>ميجابايت</span></td>' +
          '<td style="padding:10px 8px;font-size:12px;color:#64748b;">' + llEscape(t.allowed_extensions || 'جميع الامتدادات المدعومة') + '</td>' +
          '<td style="padding:10px 8px;">' +
          '<button type="button" class="btn small ghost" onclick="llUpdateFileTypePrompt(\'' + llEscape(t.key) + '\', \'' + llEscape(t.label_ar) + '\', ' + (t.max_size_mb || 25) + ', \'' + llEscape(t.allowed_extensions || '') + '\')">تعديل الحد</button>' +
          '</td></tr>'
        ).join('') +
        '</tbody></table></div>';
    }

    async function llUpdateFileTypePrompt(key, label, currentMaxMb, currentExts) {
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
        await llLoadFileTypes();
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
      await llLoadRechargeRequests('sagRechargeRequestsList');
      const data = await api('GET', '/api/admin/recharge-requests').catch(() => null);
      const requests = (data && data.success && data.requests) ? data.requests : [];
      // Counts always reflect the full queue, not the active status filter.
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
          '<div><h3>#' + llEscape(t.number) + ' ' + llEscape(t.subject) + '</h3>' +
          '<div class="meta"><span style="font-weight:700">' + llEscape(t.tenant_name || 'شركة') + '</span>' +
          ' | <span>' + llStatus(t.status) + '</span>' +
          ' | <span>الأولوية:</span> <span>' + llEscape(priorityLabels[t.priority] || t.priority) + '</span>' +
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
        '<strong style="font-size:12px">' + llEscape(m.author_name) + '</strong>' +
        (m.author_role === 'support' ? ' <span style="font-size:11px;color:var(--p)">(فريق المنصة)</span>' : '') +
        ' <span style="font-size:11px;color:var(--muted)">' + llEscape((m.created_at || '').slice(0, 16).replace('T', ' ')) + '</span>' +
        '<p style="margin:4px 0 0;font-size:13px">' + llEscape(m.body) + '</p></div>'
      ).join('');
      const attachments = (t.attachments || []).map(a =>
        '<button type="button" class="btn small ghost" onclick="adminOpenTicketAttachment(\'' + id + '\',\'' + a.file_id + '\')">' +
        llEscape(a.original_name || WFT('tickets.attachment', 'مرفق')) + '</button>').join('');
      const statusActions = t.status !== 'closed'
        ? '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:10px 0">' +
          // «تم الحل» is the terminal act — it closes the ticket directly,
          // so a solved ticket never sits in a separate resolved state.
          [['in_progress', 'قيد المعالجة', 'ghost'], ['closed', 'تم الحل', 'green']]
            .filter(a => a[0] !== t.status)
            .map(a => '<button type="button" class="btn small ' + a[2] + '" onclick="adminSetTicketStatus(\'' + id + '\', \'' + a[0] + '\')">' + a[1] + '</button>')
            .join('') +
          '</div>' +
          '<div style="display:flex;gap:8px"><input type="text" id="adminReplyBody" style="flex:1">' +
          '<button class="btn primary" onclick="adminReplyTicket(\'' + id + '\')">إرسال</button></div>'
        : '';
      detail.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">' +
        '<h3 style="margin:0">#' + llEscape(t.number) + ' ' + llEscape(t.subject) + ' — <span>' + llStatus(t.status) + '</span></h3>' +
        '<button class="btn ghost" onclick="document.getElementById(\'adminTicketDetail\').style.display=\'none\'">إغلاق</button></div>' +
        '<div class="meta" style="margin-top:4px"><span>الشركة:</span> ' + llEscape(t.tenant_name || '') +
        ' | <span>الفئة:</span> ' + llEscape(t.category || 'عامة') +
        ' | <span>المكلف:</span> <span id="adminTicketAssignee">' + llEscape(t.assignee_name || '—') + '</span></div>' +
        (attachments ? '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">' + attachments + '</div>' : '') +
        '<div id="adminTicketPriorityRow" style="display:flex;gap:8px;margin:10px 0;align-items:center">' +
        '<span style="font-size:12px">' + llEscape(WFT('tickets.priority', 'الأولوية')) + ':</span>' +
        '<select id="adminTicketPrioritySel">' +
        ['normal', 'low', 'high', 'urgent'].map(p =>
          '<option value="' + p + '"' + ((t.priority || 'normal') === p ? ' selected' : '') + '>' +
          llEscape(llTicketPriorityLabel(p)) + '</option>').join('') +
        '</select>' +
        '<button type="button" class="btn small ghost" onclick="adminSetTicketPriority(\'' + id + '\')">' +
        llEscape(WFT('tickets.update_priority', 'تحديث الأولوية')) + '</button></div>' +
        '<div id="adminTicketAssignRow" style="display:flex;gap:8px;margin:10px 0;align-items:center"></div>' +
        '<div style="margin:12px 0">' + (messages || '<p class="tenant-hint">لا رسائل.</p>') + '</div>' +
        statusActions;
      detail.scrollIntoView({ block: 'nearest' });
      const tenantUsers = await api('GET', '/api/admin/tenants/' + t.tenant_id + '/users').catch(() => null);
      const assignRow = document.getElementById('adminTicketAssignRow');
      const users = (tenantUsers && tenantUsers.success && tenantUsers.users) ? tenantUsers.users : [];
      if (assignRow && users.length && t.status !== 'closed') {
        assignRow.innerHTML = '<select id="adminTicketAssignSelect" style="flex:1">' +
          users.map(u => '<option value="' + llEscape(u.id) + '"' +
            (String(u.id) === String(t.assigned_to) ? ' selected' : '') + '>' +
            llEscape(u.name || u.email) + '</option>').join('') + '</select>' +
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

    function llTicketPriorityLabel(p) {
      const fallback = { normal: 'عادية', low: 'منخفضة', high: 'مرتفعة', urgent: 'عاجلة' }[p] || p;
      return WFT('tickets.priority_' + p, fallback);
    }

    async function adminSetTicketPriority(id) {
      const sel = document.getElementById('adminTicketPrioritySel');
      if (!sel) return;
      const res = await api('POST', '/api/admin/support/tickets/' + id + '/status', { priority: sel.value }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر تحديث الأولوية'); return; }
      toast(WFT('tickets.updated', 'تم التحديث'));
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
      await Promise.all([llLoadFileTypes(), adminLoadPackages(), llLoadRejectionReasons(), llLoadFxRate()]);
    }

    // ── USD→SAR rate: manual override or provider-tracked auto mode ──────
    async function llLoadFxRate() {
      const input = document.getElementById('adminFxRate');
      if (!input) return;
      const data = await api('GET', '/api/admin/fx-rate').catch(() => null);
      const fx = (data && data.fx) || {};
      if (fx.rate != null) input.value = fx.rate;
      const info = document.getElementById('adminFxInfo');
      if (info) {
        const src = ({ manual: 'يدوي', auto: 'تلقائي', env: 'من إعدادات الخادم', default: 'افتراضي' })[fx.source] || fx.source || '';
        info.textContent = (fx.rate != null ? '1 USD = ' + llMoney(fx.rate) + ' SAR' : '') +
          (src ? ' — المصدر: ' + src : '') +
          (fx.updated_at ? ' — ' + String(fx.updated_at).slice(0, 16).replace('T', ' ') : '');
      }
    }

    async function adminSaveFxRate(event, auto) {
      if (event) event.preventDefault();
      let payload;
      if (auto) {
        payload = { mode: 'auto' };
      } else {
        const rate = parseFloat((document.getElementById('adminFxRate') || {}).value);
        if (!Number.isFinite(rate) || rate <= 0) { toast('أدخل سعرًا صالحًا'); return; }
        payload = { mode: 'manual', rate: rate };
      }
      const res = await api('PUT', '/api/admin/fx-rate', payload).catch(e => e);
      if (res && res.success) {
        toast('تم تحديث سعر الصرف');
      } else {
        toast((res && res.error) || 'تعذر تحديث سعر الصرف');
      }
      await llLoadFxRate();
    }

    // ── Recharge rejection reasons (platform settings) ────────────────────
    async function llLoadRejectionReasons() {
      const box = document.getElementById('adminRejectionReasons');
      if (!box) return;
      const data = await api('GET', '/api/admin/settings/rejection-reasons').catch(() => null);
      const reasons = (data && data.success && data.reasons) || [];
      box.value = reasons.join('\n');
    }

    async function adminSaveRejectionReasons() {
      const box = document.getElementById('adminRejectionReasons');
      if (!box) return;
      const reasons = box.value.split('\n').map(s => s.trim()).filter(Boolean);
      const res = await api('PUT', '/api/admin/settings/rejection-reasons', { reasons: reasons }).catch(e => e);
      if (res && res.success) {
        toast(WFT('recharge.reasons_saved', 'تم حفظ أسباب الرفض'));
      } else {
        toast((res && res.error) || 'تعذر حفظ الأسباب');
      }
    }

    // ── Packages & pricing (t53): admin CRUD, deactivate keeps references ──
    let llAdminPackages = [];
    let llEditingPackageId = null;

    async function adminLoadPackages() {
      const box = document.getElementById('adminPackagesList');
      if (!box) return;
      const data = await api('GET', '/api/admin/packages').catch(() => null);
      llAdminPackages = (data && data.success && data.packages) ? data.packages : [];
      if (!llAdminPackages.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد باقات مسجلة.</p>';
        return;
      }
      box.innerHTML = llAdminPackages.map(p => {
        const cost = (p.est_cost_sar != null)
          ? ' | <span>التكلفة التقديرية: ' + llEscape(llMoney(p.est_cost_sar)) + ' <span>ريال</span></span>' : '';
        const margin = (p.est_margin_sar != null)
          ? ' | <span>الربح التقديري: ' + llEscape(llMoney(p.est_margin_sar)) + ' <span>ريال</span></span>' : '';
        return '<div class="tenant-presentation-card" style="margin-bottom:8px"><div><h3>' + llEscape(p.name) + '</h3>' +
          '<div class="meta"><span>' + (p.price_sar != null ? llEscape(llMoney(p.price_sar)) + ' <span>ريال</span>' : 'بلا سعر') + '</span>' +
          ' | <span>' + llEscape(llMoney(p.credit_sar)) + ' <span>ريال رصيد</span></span>' + cost + margin +
          ' | <span>' + (p.is_active ? 'نشطة' : 'موقوفة') + '</span></div></div>' +
          '<div class="tenant-actions">' +
          '<button type="button" class="btn small ghost" onclick="adminEditPackage(\'' + llEscape(p.id) + '\')">تعديل</button>' +
          '<button type="button" class="btn small ' + (p.is_active ? 'danger' : 'green') +
          '" onclick="adminTogglePackage(\'' + llEscape(p.id) + '\', ' + (p.is_active ? 0 : 1) + ')">' +
          (p.is_active ? 'إيقاف' : 'تفعيل') + '</button>' +
          '<button type="button" class="btn small danger" onclick="adminDeletePackage(\'' + llEscape(p.id) + '\')">حذف</button>' +
          '</div></div>';
      }).join('');
    }

    function adminEditPackage(packageId) {
      const p = llAdminPackages.find(item => item.id === packageId);
      if (!p) return;
      llEditingPackageId = packageId;
      const llRound2 = (v) => (v == null ? '' : Math.round(Number(v) * 100) / 100);
      document.getElementById('adminPackageName').value = p.name || '';
      document.getElementById('adminPackagePrice').value = llRound2(p.price_sar);
      document.getElementById('adminPackageCredit').value = llRound2(p.credit_sar);
      const submit = document.getElementById('adminPackageSubmit');
      if (submit) submit.textContent = WFT('packages.update', 'تحديث الباقة');
      const cancel = document.getElementById('adminPackageCancel');
      if (cancel) cancel.style.display = '';
      document.getElementById('adminPackageName').focus();
    }

    function adminCancelPackageEdit() {
      llEditingPackageId = null;
      document.getElementById('adminPackageName').value = '';
      document.getElementById('adminPackagePrice').value = '';
      document.getElementById('adminPackageCredit').value = '';
      const submit = document.getElementById('adminPackageSubmit');
      if (submit) submit.textContent = WFT('admin.package_save', 'حفظ الباقة');
      const cancel = document.getElementById('adminPackageCancel');
      if (cancel) cancel.style.display = 'none';
    }

    async function adminSavePackage(event) {
      event.preventDefault();
      const payload = {
        name: document.getElementById('adminPackageName').value.trim(),
        priceSar: Number(document.getElementById('adminPackagePrice').value),
        creditSar: Number(document.getElementById('adminPackageCredit').value)
      };
      const res = llEditingPackageId
        ? await api('PUT', '/api/admin/packages/' + llEditingPackageId, payload).catch(e => e)
        : await api('POST', '/api/admin/packages', Object.assign({ isCustom: false }, payload)).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر حفظ الباقة'); return; }
      adminCancelPackageEdit();
      toast(WFT('packages.saved', 'تم حفظ الباقة'));
      await adminLoadPackages();
    }

    async function adminTogglePackage(packageId, active) {
      const res = await api('PUT', '/api/admin/packages/' + packageId, { isActive: !!active }).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر تحديث الباقة'); return; }
      await adminLoadPackages();
    }

    async function adminDeletePackage(packageId) {
      const p = llAdminPackages.find(item => item.id === packageId);
      if (!confirm(WFT('packages.delete_confirm', 'سيتم حذف باقة «{name}» نهائيًا. هل تريد المتابعة؟', { name: p ? p.name : '' }))) return;
      const res = await api('DELETE', '/api/admin/packages/' + packageId).catch(e => e);
      if (!res || !res.success) { toast((res && res.error) || 'تعذر حذف الباقة'); return; }
      if (llEditingPackageId === packageId) adminCancelPackageEdit();
      toast(WFT('packages.deleted', 'تم حذف الباقة'));
      await adminLoadPackages();
    }
