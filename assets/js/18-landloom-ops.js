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

    const LANDLOOM_OPS_TABS = ['recharge', 'packages', 'tickets'];
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
      // The catalog refetches on every visit so desk edits land live.
      if (target === 'packages') llLoadPackagesPage();
    }

    async function openLandloomOpsPage(tabKey) {
      showTenantPage('tenantLandloomOpsPage');
      showLandloomOpsTab(tabKey || 'recharge');

      await Promise.all([
        llLoadTickets(),
        llLoadRechargeRequests(),
        llLoadPackagesPage()
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
      if (!tickets.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد تذاكر دعم.</p>';
        return;
      }
      box.innerHTML =
        '<div class="table-wrap"><table><thead><tr>' +
        '<th>اسم التذكرة</th><th>التاريخ</th><th>الحالة</th>' +
        '</tr></thead><tbody>' +
        tickets.map(t => {
          const date = (t.created_at || t.updated_at || '').slice(0, 16).replace('T', ' ');
          return '<tr role="button" tabindex="0" style="cursor:pointer" onclick="llOpenTicket(\'' + t.id + '\')">' +
            '<td style="font-weight:700">#' + llEscape(t.number) + ' ' + llEscape(t.subject) +
            (t.attachment_count ? ' <span class="tenant-hint">(' + llEscape(WFT('tickets.has_attachment', 'يحتوي مرفقًا')) + ')</span>' : '') +
            '</td><td>' + llEscape(date) + '</td><td>' + llStatus(t.status) + '</td></tr>';
        }).join('') +
        '</tbody></table></div>';
    }

    // Row click opens the conversation in a popup — the list stays a compact
    // three-column register and the whole thread lives in the modal.
    async function llOpenTicket(id) {
      const modal = document.getElementById('llTicketViewModal');
      const body = document.getElementById('llTicketViewBody');
      const titleEl = document.getElementById('llTicketViewTitle');
      if (!modal || !body || !titleEl) return;
      titleEl.textContent = 'التذكرة';
      body.innerHTML = '<p class="tenant-hint">جاري التحميل...</p>';
      if (modal.style.display !== 'flex') openLlModal('llTicketViewModal');
      const data = await api('GET', '/api/support/tickets/' + id).catch(() => null);
      if (!data || !data.success) {
        body.innerHTML = '<p class="tenant-hint">تعذر فتح التذكرة.</p>';
        return;
      }
      const t = data.ticket || {};
      titleEl.textContent = '#' + t.number + ' ' + (t.subject || '');
      const messages = (t.messages || []).map(m =>
        '<div style="border-top:1px solid var(--line);padding:8px 0">' +
        '<strong style="font-size:12px">' + llEscape(m.author_name) + '</strong> ' +
        '<span style="font-size:11px;color:var(--muted)">' + llEscape((m.created_at || '').slice(0, 16).replace('T', ' ')) + '</span>' +
        '<p style="margin:4px 0 0;font-size:13px">' + llEscape(m.body) + '</p></div>'
      ).join('');
      const attachments = (t.attachments || []).map(a =>
        '<button type="button" class="btn small ghost" onclick="llOpenTicketAttachment(\'' + id + '\',\'' + a.file_id + '\')">' +
        llEscape(a.original_name || WFT('tickets.attachment', 'مرفق')) + '</button>').join('');
      body.innerHTML =
        '<div class="meta" style="color:var(--muted);font-size:12px"><span>' + llStatus(t.status) + '</span></div>' +
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
      if (!requests.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد طلبات شحن بعد.</p>';
        return;
      }
      const taxRate = Number.isFinite(Number(data.taxRate)) ? Number(data.taxRate) : 0.15;
      const rowsHtml = requests.map(r => {
        const date = (r.requested_at || r.created_at || '').slice(0, 16).replace('T', ' ');
        // «التكلفة» on a request means what the client actually pays: the
        // catalog price plus VAT — the same total the top-up receipt books.
        const subtotal = (r.price_sar != null && r.price_sar !== '') ? Number(r.price_sar) : null;
        const costCell = (subtotal != null && Number.isFinite(subtotal))
          ? llMoney(Math.round(subtotal * (1 + taxRate) * 100) / 100) + ' <span>ريال سعودي</span>'
          : (r.amount_sar != null ? llMoney(r.amount_sar) + ' <span>نقطة</span>' : '—');
        const refCell = (r.transfer_reference ? llEscape(r.transfer_reference) : '—') +
          (r.reference_number
            ? '<div class="tenant-hint"><span>سند مالي:</span> ' + llEscape(r.reference_number) + '</div>' : '');
        const receiptCell = r.receipt_file_id
          ? '<a href="#" onclick="llOpenRechargeAttachment(\'' + r.id + '\', \'receipt\');return false;">إيصال التحويل</a>' : '—';
        const invoiceCell = r.invoice_file_id
          ? '<a href="#" onclick="llOpenRechargeAttachment(\'' + r.id + '\', \'invoice\');return false;">الفاتورة</a>' : '—';
        const statusCell = llStatus(r.status) +
          ((r.status === 'rejected' && r.decision_note)
            ? '<div class="tenant-hint" style="color:var(--danger,#c0392b)"><span>سبب الرفض:</span> ' + llEscape(r.decision_note) + '</div>' : '');
        const companyCell = isAdmin
          ? '<td>' + llEscape(r.tenant_name || r.company_name || '—') + '</td>' : '';
        const actionsCell = isAdmin
          ? '<td>' + (r.status === 'pending'
              ? '<div class="tenant-actions" style="flex-wrap:wrap">' +
                '<button type="button" class="btn small green" onclick="llDecideRecharge(\'' + r.id + '\', \'approved\')">اعتماد الطلب</button>' +
                '<button type="button" class="btn small danger" onclick="llDecideRecharge(\'' + r.id + '\', \'rejected\')">رفض</button>' +
                '</div>'
              : '—') + '</td>'
          : '';
        return '<tr>' + companyCell +
          '<td style="font-weight:700">' + llEscape(r.package_name) + '</td>' +
          '<td>' + costCell + '</td>' +
          '<td>' + llEscape(date) + '</td>' +
          '<td>' + refCell + '</td>' +
          '<td>' + receiptCell + '</td>' +
          '<td>' + statusCell + '</td>' +
          '<td>' + invoiceCell + '</td>' +
          actionsCell + '</tr>';
      }).join('');
      box.innerHTML =
        '<div class="table-wrap"><table><thead><tr>' +
        (isAdmin ? '<th>الشركة</th>' : '') +
        '<th>اسم الباقة</th>' +
        '<th>التكلفة (شامل ضريبة القيمة المضافة 15%)</th>' +
        '<th>تاريخ الطلب</th>' +
        '<th>المرجع البنكي</th>' +
        '<th>إيصال التحويل</th>' +
        '<th>حالة الطلب</th>' +
        '<th>الفاتورة</th>' +
        (isAdmin ? '<th>الإجراءات</th>' : '') +
        '</tr></thead><tbody>' + rowsHtml + '</tbody></table></div>';
    }

    let llRechargePackages = [];
    // Desk-set «ضريبة» fraction the catalog feed returns — the custom
    // package preview mirrors the server's price − tax% → points math.
    let llPackageTaxRate = 0;
    let llCustomPackageAmount = null;

    async function llLoadPackagesPage() {
      const host = document.getElementById('llPackagesCatalog');
      const input = document.getElementById('llRechargePackage');
      if (!host) return;
      // The desk is permission-gated; skip the call for members without it.
      if (typeof hasPermission === 'function' && !hasPermission('billing')) {
        host.innerHTML = '';
        return;
      }
      const data = await api('GET', '/api/billing/packages').catch(() => null);
      llRechargePackages = (data && data.success && data.packages) || [];
      if (data && typeof data.taxRate === 'number') llPackageTaxRate = data.taxRate;
      if (llRechargePkgSlider) { llRechargePkgSlider.destroy(); llRechargePkgSlider = null; }
      // A stale pick (deleted or deactivated) never reaches the modal.
      if (input && input.value && input.value !== '__custom__' &&
          !llRechargePackages.some(p => p.id === input.value)) {
        input.value = '';
      }
      // The «باقة مخصصة» card rides the same slider as a trailing item — it
      // stays available even while the desk has published no packages.
      llRechargePkgSlider = wfCardSlider({
        container: host,
        items: llRechargePackages.concat([{ id: '__custom__', custom: true }]),
        renderCard: llRechargePackageCardHtml, maxVisible: 3,
        minCardWidth: 230, maxCardWidth: 340
      });
      llShowPackageInfo();
    }

    function llShowPackageInfo() {
      const box = document.getElementById('llRechargePackageInfo');
      const input = document.getElementById('llRechargePackage');
      if (!box || !input) return;
      if (input.value === '__custom__') {
        const pts = Math.max(0, (llCustomPackageAmount || 0) * (1 - llPackageTaxRate));
        box.textContent = WFT('recharge.custom_info',
          'باقة مخصصة — {points} نقطة — {price} ريال سعودي', {
            points: llMoney(Math.round(pts * 100) / 100),
            price: llMoney(llCustomPackageAmount || 0)
          });
        box.style.display = '';
        return;
      }
      const pkg = llRechargePackages.find(p => p.id === input.value);
      if (!pkg) { box.style.display = 'none'; box.textContent = ''; return; }
      const price = pkg.price_sar != null
        ? ' — ' + llMoney(pkg.price_sar) + ' ريال سعودي' : '';
      const parts = [
        wfBilingual(pkg.name, pkg.name_en) + ' — ' + llMoney(pkg.credit_sar) + ' نقطة' + price,
        pkg.duration_days
          ? 'الصلاحية: ' + pkg.duration_days + ' يومًا'
          : 'الصلاحية: بلا انتهاء محدد'];
      (Array.isArray(pkg.features) ? pkg.features : []).forEach(f => {
        if (f) parts.push(String(f));
      });
      box.textContent = parts.join(' — ');
      box.style.display = '';
    }

    /* The «باقة مخصصة» preview mirrors the server: paid riyals minus the
       desk tax rate become wallet points. Slider clones duplicate the card,
       so every copy of the input/points display is kept in sync. */
    function llCustomInputChanged(el) {
      document.querySelectorAll('.pkg-custom-input').forEach(i => {
        if (i !== el) i.value = el.value;
      });
      llUpdateCustomPoints();
    }
    function llUpdateCustomPoints() {
      const amount = Math.max.apply(null, [0].concat(Array.from(
        document.querySelectorAll('.pkg-custom-input')).map(i => Number(i.value || 0))));
      const pts = amount > 0 ? Math.round(amount * (1 - llPackageTaxRate) * 100) / 100 : 0;
      document.querySelectorAll('.pkg-custom-points').forEach(el => {
        el.innerHTML = llEscape(llMoney(pts)) +
          ' <span class="pkg-credit-unit">نقطة</span>';
      });
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
      const isCustom = packageId === '__custom__';
      if (isCustom && !(llCustomPackageAmount > 0)) {
        if (errBox) errBox.textContent = WFT('recharge.invalid_amount', 'أدخل مبلغًا صالحًا');
        return;
      }
      const pkg = llRechargePackages.find(p => p.id === packageId);
      const data = await api('POST', '/api/recharge-requests', {
        packageId: isCustom ? null : packageId,
        packageName: isCustom ? 'باقة مخصصة' : (pkg ? pkg.name : packageId),
        customAmountSar: isCustom ? llCustomPackageAmount : undefined,
        referenceNumber: ref.trim(),
        receiptFileId: receipt ? receipt.id : null
      }).catch(e => e);
      if (!data || !data.success) {
        if (errBox) errBox.textContent = (data && data.error) || 'تعذر إرسال الطلب.';
        return;
      }
      if (document.getElementById('llRechargeRef')) document.getElementById('llRechargeRef').value = '';
      if (document.getElementById('llRechargeReceipt')) document.getElementById('llRechargeReceipt').value = '';
      const pkgInput = document.getElementById('llRechargePackage');
      if (pkgInput) pkgInput.value = '';
      llCustomPackageAmount = null;
      document.querySelectorAll('.pkg-custom-input').forEach(i => { i.value = ''; });
      llUpdateCustomPoints();
      document.querySelectorAll('.pkg-card.selected').forEach(c => c.classList.remove('selected'));
      llShowPackageInfo();
      closeLlModal('llRechargeModal');
      toast(WFT('recharge.request_sent', 'تم إرسال طلب الشحن بنجاح'));
      await llLoadRechargeRequests();
    }

    // ── Recharge decision modal: approve (mandatory invoice) or reject (reason) ──
    const LL_RECHARGE_OTHER_REASON = '__other__';
    async function llDecideRecharge(requestId, decision) {
      const idEl = document.getElementById('llRechargeDecisionId');
      const kindEl = document.getElementById('llRechargeDecisionKind');
      const modal = document.getElementById('llRechargeDecisionModal');
      // A stale shell (an index.html from before this modal) used to swallow the
      // click on a null lookup — fail loudly so the button never feels dead.
      if (!idEl || !kindEl || !modal) {
        toast(WFT('recharge.ui_stale', 'واجهة غير متزامنة — أعد تحميل الصفحة'));
        return;
      }
      idEl.value = requestId;
      kindEl.value = decision;
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
      // The modal opens before the reasons fetch so a slow settings read never
      // looks like a dead button.
      openLlModal('llRechargeDecisionModal');
      if (!isApprove) {
        const select = document.getElementById('llRechargeReason');
        const data = await api('GET', '/api/admin/settings/rejection-reasons').catch(() => null);
        const reasons = (data && data.success && Array.isArray(data.reasons)) ? data.reasons : [];
        select.innerHTML = '<option value="">—</option>' +
          reasons.map(r => '<option value="' + llEscape(r) + '">' + llEscape(r) + '</option>').join('') +
          '<option value="' + LL_RECHARGE_OTHER_REASON + '">' +
          llEscape(WFT('recharge.reason_other', 'أخرى')) + '</option>';
        llRechargeReasonChanged();
      }
    }

    // «أخرى» turns the note field into the free-text reason itself; a preset
    // reason keeps it as an optional extra.
    function llRechargeReasonChanged() {
      const select = document.getElementById('llRechargeReason');
      const label = document.getElementById('llRechargeNoteLabel');
      const note = document.getElementById('llRechargeNote');
      if (!select || !label || !note) return;
      const custom = select.value === LL_RECHARGE_OTHER_REASON;
      label.textContent = custom
        ? WFT('recharge.reason_custom_label', 'سبب الرفض')
        : WFT('recharge.note_optional', 'ملاحظة إضافية');
      note.required = custom;
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
        // The client's invoice is part of the approval itself — never optional.
        if (!input || !input.files || !input.files[0]) {
          if (errBox) errBox.textContent = WFT('recharge.invoice_required', 'فاتورة الشحن مطلوبة لاعتماد الطلب');
          return;
        }
        const form = new FormData();
        form.append('file', input.files[0]);
        form.append('fileType', 'recharge_invoice');
        const up = await api('POST', '/api/project-files', form, true).catch(e => e);
        if (!up || !up.success) {
          if (errBox) errBox.textContent = (up && up.error) || 'تعذر رفع الفاتورة';
          return;
        }
        invoiceFileId = up.file.id;
      } else {
        const reason = (document.getElementById('llRechargeReason') || {}).value || '';
        const extra = ((document.getElementById('llRechargeNote') || {}).value || '').trim();
        note = reason === LL_RECHARGE_OTHER_REASON
          ? extra
          : (reason && extra ? reason + ' — ' + extra : (reason || extra));
        if (!note) {
          if (errBox) errBox.textContent = WFT('recharge.reason_required', 'سبب الرفض مطلوب');
          return;
        }
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
      box.innerHTML =
        '<div class="table-wrap"><table><thead><tr>' +
        '<th>اسم التذكرة</th><th>الشركة</th><th>الأولوية</th><th>الحالة</th><th>التاريخ</th>' +
        '</tr></thead><tbody>' +
        tickets.map(t => {
          const date = (t.updated_at || t.created_at || '').slice(0, 16).replace('T', ' ');
          return '<tr role="button" tabindex="0" style="cursor:pointer" onclick="adminOpenTicket(\'' + t.id + '\')">' +
            '<td style="font-weight:700">#' + llEscape(t.number) + ' ' + llEscape(t.subject) + '</td>' +
            '<td>' + llEscape(t.tenant_name || 'شركة') + '</td>' +
            '<td>' + llEscape(priorityLabels[t.priority] || t.priority || '') + '</td>' +
            '<td>' + llStatus(t.status) + '</td>' +
            '<td>' + llEscape(date) + '</td></tr>';
        }).join('') +
        '</tbody></table></div>';
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

    // ── USD/SAR rate: manual override or provider-tracked auto mode ──────
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
        if (!Number.isFinite(rate) || rate <= 0) { toast(WFT('fx.invalid_rate', 'أدخل سعرًا صالحًا')); return; }
        payload = { mode: 'manual', rate: rate };
      }
      const res = await api('PUT', '/api/admin/fx-rate', payload).catch(e => e);
      if (res && res.success) {
        toast(WFT('fx.rate_updated', 'تم تحديث سعر الصرف'));
      } else {
        toast((res && res.error) || 'تعذر تحديث سعر الصرف');
      }
      await llLoadFxRate();
    }

    // ── Recharge rejection reasons (platform settings) ────────────────────
    let llRejectionReasons = [];
    let llEditingReasonIndex = -1;

    async function llLoadRejectionReasons() {
      const list = document.getElementById('adminRejectionReasonsList');
      if (!list) return;
      const data = await api('GET', '/api/admin/settings/rejection-reasons').catch(() => null);
      if (!data || !data.success) {
        list.innerHTML = '<p class="tenant-hint">' + WFT('recharge.reasons_load_failed', 'تعذر تحميل أسباب الرفض.') + '</p>';
        return;
      }
      llRejectionReasons = (data.reasons || []).slice();
      llRenderRejectionReasons();
    }

    function llRenderRejectionReasons() {
      const list = document.getElementById('adminRejectionReasonsList');
      if (!list) return;
      if (!llRejectionReasons.length) {
        list.innerHTML = '<p class="tenant-hint">' + WFT('recharge.reasons_empty', 'لا توجد أسباب مسجلة.') + '</p>';
        return;
      }
      list.innerHTML = llRejectionReasons.map(function (reason, index) {
        return '<div class="tenant-presentation-card" style="margin-bottom:8px"><div><h3>' + llEscape(reason) + '</h3></div>' +
          '<div class="tenant-actions">' +
          '<button type="button" class="btn small ghost" onclick="adminEditRejectionReason(' + index + ')">تعديل</button>' +
          '<button type="button" class="btn small danger" onclick="adminDeleteRejectionReason(' + index + ')">حذف</button>' +
          '</div></div>';
      }).join('');
    }

    async function llPersistRejectionReasons(toastMsg) {
      const res = await api('PUT', '/api/admin/settings/rejection-reasons', { reasons: llRejectionReasons }).catch(e => e);
      if (!res || !res.success) {
        toast((res && res.error) || WFT('recharge.reasons_save_failed', 'تعذر حفظ الأسباب'));
        await llLoadRejectionReasons();
        return;
      }
      toast(toastMsg);
      adminCancelRejectionReasonEdit();
      llRenderRejectionReasons();
    }

    async function adminSubmitRejectionReason(event) {
      event.preventDefault();
      const input = document.getElementById('adminRejectionReasonInput');
      const value = ((input && input.value) || '').trim();
      if (!value) return;
      const dupe = llRejectionReasons.some(function (r, i) { return r === value && i !== llEditingReasonIndex; });
      if (dupe) { toast(WFT('recharge.reason_exists', 'السبب مسجل بالفعل')); return; }
      if (llEditingReasonIndex < 0 && llRejectionReasons.length >= 30) {
        toast(WFT('recharge.reasons_limit', 'الحد الأقصى 30 سببًا'));
        return;
      }
      if (llEditingReasonIndex >= 0) llRejectionReasons[llEditingReasonIndex] = value;
      else llRejectionReasons.push(value);
      await llPersistRejectionReasons(WFT('recharge.reasons_saved', 'تم حفظ أسباب الرفض'));
    }

    function adminEditRejectionReason(index) {
      const reason = llRejectionReasons[index];
      if (reason == null) return;
      llEditingReasonIndex = index;
      const input = document.getElementById('adminRejectionReasonInput');
      input.value = reason;
      document.getElementById('adminRejectionReasonSubmit').textContent = WFT('admin.rejection_reason_update', 'تحديث السبب');
      document.getElementById('adminRejectionReasonCancel').style.display = '';
      input.focus();
    }

    function adminCancelRejectionReasonEdit() {
      llEditingReasonIndex = -1;
      const input = document.getElementById('adminRejectionReasonInput');
      if (input) input.value = '';
      const submit = document.getElementById('adminRejectionReasonSubmit');
      if (submit) submit.textContent = WFT('admin.rejection_reason_add', 'إضافة سبب');
      const cancel = document.getElementById('adminRejectionReasonCancel');
      if (cancel) cancel.style.display = 'none';
    }

    async function adminDeleteRejectionReason(index) {
      const reason = llRejectionReasons[index];
      if (reason == null) return;
      if (!confirm(WFT('recharge.reason_delete_confirm', 'سيتم حذف سبب الرفض «{reason}». هل تريد المتابعة؟', { reason: reason }))) return;
      llRejectionReasons.splice(index, 1);
      await llPersistRejectionReasons(WFT('recharge.reason_deleted', 'تم حذف السبب'));
    }

    // ── Packages & pricing (t53): admin CRUD, deactivate keeps references ──
    let llAdminPackages = [];
    let llEditingPackageId = null;
    // The desk tax percent, echoed by GET /api/admin/packages — it drives
    // the readonly computed-points preview on the package form.
    let llAdminTaxRatePct = 15;

    function adminRefreshComputedCredit() {
      const price = Number((document.getElementById('adminPackagePrice') || {}).value || 0);
      const creditEl = document.getElementById('adminPackageCredit');
      if (creditEl) {
        creditEl.value = price > 0
          ? Math.round(price * (1 - llAdminTaxRatePct / 100) * 100) / 100 : '';
      }
    }

    async function adminSaveTaxRate() {
      const el = document.getElementById('adminPackageTaxRate');
      const res = await api('PUT', '/api/admin/package-tax-rate', {
        ratePct: Number((el || {}).value)
      }).catch(e => e);
      if (!res || !res.success) {
        toast((res && res.error) || WFT('recharge.tax_save_failed', 'تعذر حفظ النسبة'));
        return;
      }
      if (typeof res.ratePct === 'number') llAdminTaxRatePct = res.ratePct;
      adminRefreshComputedCredit();
      toast(WFT('recharge.tax_saved', 'تم حفظ النسبة'));
    }

    async function adminLoadPackages() {
      const box = document.getElementById('adminPackagesList');
      if (!box) return;
      const data = await api('GET', '/api/admin/packages').catch(() => null);
      llAdminPackages = (data && data.success && data.packages) ? data.packages : [];
      if (data && typeof data.taxRatePct === 'number') llAdminTaxRatePct = data.taxRatePct;
      const taxEl = document.getElementById('adminPackageTaxRate');
      if (taxEl) taxEl.value = llAdminTaxRatePct;
      const priceEl = document.getElementById('adminPackagePrice');
      if (priceEl && !priceEl.dataset.computedBound) {
        priceEl.dataset.computedBound = '1';
        priceEl.addEventListener('input', adminRefreshComputedCredit);
      }
      if (!llEditingPackageId) adminRefreshComputedCredit();
      if (llAdminPkgSlider) { llAdminPkgSlider.destroy(); llAdminPkgSlider = null; }
      if (!llAdminPackages.length) {
        box.innerHTML = '<p class="tenant-hint">لا توجد باقات مسجلة.</p>';
        return;
      }
      llAdminPkgSlider = wfCardSlider({
        container: box, items: llAdminPackages,
        renderCard: llAdminPackageCardHtml, maxVisible: 3, minCardWidth: 210
      });
    }

    function adminEditPackage(packageId) {
      const p = llAdminPackages.find(item => item.id === packageId);
      if (!p) return;
      llEditingPackageId = packageId;
      const llRound2 = (v) => (v == null ? '' : Math.round(Number(v) * 100) / 100);
      document.getElementById('adminPackageName').value = p.name || '';
      const nameEnEl = document.getElementById('adminPackageNameEn');
      if (nameEnEl) nameEnEl.value = p.name_en || '';
      document.getElementById('adminPackagePrice').value = llRound2(p.price_sar);
      document.getElementById('adminPackageCredit').value = llRound2(p.credit_sar);
      const pkgFieldMap = {
        adminPackageBadge: 'badge', adminPackageBadgeEn: 'badge_en',
        adminPackageTagline: 'tagline', adminPackageTaglineEn: 'tagline_en'
      };
      Object.keys(pkgFieldMap).forEach(elId => {
        const el = document.getElementById(elId);
        if (el) el.value = p[pkgFieldMap[elId]] || '';
      });
      const featEl = document.getElementById('adminPackageFeatured');
      if (featEl) featEl.checked = !!p.is_featured;
      const durEl = document.getElementById('adminPackageDuration');
      if (durEl) durEl.value = p.duration_days || '';
      const featuresEl = document.getElementById('adminPackageFeatures');
      if (featuresEl) featuresEl.value = (p.features || []).join('\n');
      const submit = document.getElementById('adminPackageSubmit');
      if (submit) submit.textContent = WFT('packages.update', 'تحديث الباقة');
      const cancel = document.getElementById('adminPackageCancel');
      if (cancel) cancel.style.display = '';
      document.getElementById('adminPackageName').focus();
    }

    function adminCancelPackageEdit() {
      llEditingPackageId = null;
      document.getElementById('adminPackageName').value = '';
      const nameEnEl = document.getElementById('adminPackageNameEn');
      if (nameEnEl) nameEnEl.value = '';
      document.getElementById('adminPackagePrice').value = '';
      document.getElementById('adminPackageCredit').value = '';
      ['adminPackageBadge', 'adminPackageBadgeEn', 'adminPackageTagline',
       'adminPackageTaglineEn', 'adminPackageDuration',
       'adminPackageFeatures'].forEach(elId => {
        const el = document.getElementById(elId);
        if (el) el.value = '';
      });
      const featEl = document.getElementById('adminPackageFeatured');
      if (featEl) featEl.checked = false;
      const submit = document.getElementById('adminPackageSubmit');
      if (submit) submit.textContent = WFT('admin.package_save', 'حفظ الباقة');
      const cancel = document.getElementById('adminPackageCancel');
      if (cancel) cancel.style.display = 'none';
    }

    async function adminSavePackage(event) {
      event.preventDefault();
      const payload = {
        name: document.getElementById('adminPackageName').value.trim(),
        nameEn: (document.getElementById('adminPackageNameEn') || {}).value
          ? document.getElementById('adminPackageNameEn').value.trim() : '',
        priceSar: Number(document.getElementById('adminPackagePrice').value),
        // Points stay server-computed from the price — never keyed here.
        durationDays: (document.getElementById('adminPackageDuration') || {}).value === ''
          ? null : parseInt(document.getElementById('adminPackageDuration').value, 10),
        features: ((document.getElementById('adminPackageFeatures') || {}).value || '')
          .split('\n').map(s => s.trim()).filter(Boolean),
        badge: (document.getElementById('adminPackageBadge') || {}).value || '',
        badgeEn: (document.getElementById('adminPackageBadgeEn') || {}).value || '',
        tagline: (document.getElementById('adminPackageTagline') || {}).value || '',
        taglineEn: (document.getElementById('adminPackageTaglineEn') || {}).value || '',
        isFeatured: !!((document.getElementById('adminPackageFeatured') || {}).checked)
      };
      payload.badge = payload.badge.trim();
      payload.badgeEn = payload.badgeEn.trim();
      payload.tagline = payload.tagline.trim();
      payload.taglineEn = payload.taglineEn.trim();
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
