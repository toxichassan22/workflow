/* 18-landloom-ops/05_support_tickets.js — client support tickets & admin support desk.
   Brand palette: Navy #07182C, White #FFFFFF, Turquoise #17C8E3.
   Shared global scope, classic scripts in order. Strictly NO emojis or icon glyphs. */

var llCurrentTicketsFilter = 'all';
var llTicketsCache = [];

function llTicketPriorityLabel(p) {
  const map = {
    normal: WFT('tickets.priority_normal', 'عادية'),
    low: WFT('tickets.priority_low', 'منخفضة'),
    high: WFT('tickets.priority_high', 'مرتفعة'),
    urgent: WFT('tickets.priority_urgent', 'عاجلة')
  };
  return map[p] || p;
}

function llTicketCategoryLabel(cat) {
  const map = {
    general: WFT('tickets.category_general', 'استفسار عام'),
    billing: WFT('tickets.category_billing', 'الفوترة والرصيد'),
    technical: WFT('tickets.category_technical', 'مشكلة تقنية'),
    generation: WFT('tickets.category_generation', 'التوليد والذكاء الاصطناعي'),
    files: WFT('tickets.category_files', 'الملفات والتنزيلات'),
    account: WFT('tickets.category_account', 'الحساب والصلاحيات'),
    other: WFT('tickets.category_other', 'أخرى')
  };
  return map[cat] || cat || WFT('tickets.category_general', 'استفسار عام');
}

function llTicketStatusBadge(status) {
  const s = status || 'open';
  const labelMap = {
    open: WFT('tickets.status_open', 'مفتوحة'),
    in_progress: WFT('tickets.status_in_progress', 'قيد المعالجة'),
    resolved: WFT('tickets.status_resolved', 'تم الحل'),
    closed: WFT('tickets.status_closed', 'مغلقة')
  };
  const label = labelMap[s] || s;
  const cls = (s === 'closed' || s === 'resolved') ? 'status-closed' : (s === 'in_progress' ? 'status-in_progress' : 'status-open');
  return '<span class="ticket-badge ' + cls + '">' + llEscape(label) + '</span>';
}

function llTicketPriorityBadge(prio) {
  const p = prio || 'normal';
  const label = llTicketPriorityLabel(p);
  const cls = 'prio-' + p;
  return '<span class="ticket-badge ' + cls + '">' + llEscape(label) + '</span>';
}

function llFilterTickets(filter) {
  llCurrentTicketsFilter = filter || 'all';
  const container = document.getElementById('llTabPane_tickets');
  if (container) {
    container.querySelectorAll('.support-filter-btn').forEach(function (btn) {
      const target = btn.getAttribute('data-filter') || 'all';
      btn.classList.toggle('active', target === llCurrentTicketsFilter);
    });
  }
  llRenderTicketsList();
}

function llRenderTicketsList() {
  const box = document.getElementById('llTicketsList');
  if (!box) return;

  let list = llTicketsCache.slice();
  if (llCurrentTicketsFilter === 'active') {
    list = list.filter(function (t) { return !['closed', 'resolved'].includes(t.status); });
  } else if (llCurrentTicketsFilter === 'closed') {
    list = list.filter(function (t) { return ['closed', 'resolved'].includes(t.status); });
  }

  if (!list.length) {
    box.innerHTML =
      '<div class="support-table-card">' +
      '<div class="support-empty-state">' +
      '<div class="support-empty-title">' + llEscape(WFT('tickets.empty_title', 'لا توجد تذاكر دعم في هذا التبويب')) + '</div>' +
      '<div class="support-empty-desc">' + llEscape(WFT('tickets.empty_desc', 'يمكنك فتح تذكرة جديدة وسيقوم فريق الدعم الفني بمراجعتها والتواصل معك.')) + '</div>' +
      '<button type="button" class="btn primary small" onclick="openLlModal(\'llTicketModal\')">' +
      llEscape(WFT('tickets.new_ticket', 'فتح تذكرة جديدة')) + '</button>' +
      '</div></div>';
    return;
  }

  box.innerHTML =
    '<div class="support-table-card">' +
    '<div class="table-wrap"><table><thead><tr>' +
    '<th>' + llEscape(WFT('tickets.col_subject', 'التذكرة والموضوع')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_category', 'التصنيف')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_priority', 'الأولوية')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_status', 'الحالة')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_date', 'تاريخ التحديث')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_action', 'الإجراء')) + '</th>' +
    '</tr></thead><tbody>' +
    list.map(function (t) {
      const date = (t.updated_at || t.created_at || '').slice(0, 16).replace('T', ' ');
      const hasAtt = t.attachment_count
        ? ' <span class="tenant-hint" style="font-size:11px">(' + llEscape(WFT('tickets.has_attachment', 'مرفق')) + ')</span>'
        : '';
      return '<tr class="ticket-row" role="button" tabindex="0" onclick="llOpenTicket(\'' + t.id + '\')">' +
        '<td><div class="ticket-subject-cell">' +
        '<span class="ticket-subject-title"><span class="ticket-number-tag">#' + llEscape(t.number) + '</span>' +
        llEscape(t.subject) + hasAtt + '</span>' +
        '</div></td>' +
        '<td><span class="ticket-category-label">' + llEscape(llTicketCategoryLabel(t.category)) + '</span></td>' +
        '<td>' + llTicketPriorityBadge(t.priority) + '</td>' +
        '<td>' + llTicketStatusBadge(t.status) + '</td>' +
        '<td><span style="font-size:12px;color:var(--muted)">' + llEscape(date) + '</span></td>' +
        '<td><button type="button" class="btn small ghost" onclick="event.stopPropagation();llOpenTicket(\'' + t.id + '\')">' +
        llEscape(WFT('common.view', 'عرض')) + '</button></td>' +
        '</tr>';
    }).join('') +
    '</tbody></table></div></div>';
}

async function llLoadTickets() {
  const box = document.getElementById('llTicketsList');
  if (!box) return;
  llLoadSupportFaqs();
  if (!hasPermission('support_tickets')) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
    llEscape(WFT('common.loading', 'جاري التحميل...')) + '</p></div>';

  const data = await api('GET', '/api/support/tickets').catch(() => null);
  if (!data || !data.success) {
    box.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
      llEscape(WFT('tickets.load_failed', 'تعذر تحميل التذاكر حاليًا.')) + '</p></div>';
    return;
  }

  llTicketsCache = data.tickets || [];

  // Update filter pill counters
  const activeCount = llTicketsCache.filter(function (t) { return !['closed', 'resolved'].includes(t.status); }).length;
  const closedCount = llTicketsCache.filter(function (t) { return ['closed', 'resolved'].includes(t.status); }).length;
  const totalCount = llTicketsCache.length;

  const countActiveEl = document.getElementById('llCountActive');
  const countClosedEl = document.getElementById('llCountClosed');
  const countAllEl = document.getElementById('llCountAll');
  if (countActiveEl) countActiveEl.textContent = activeCount;
  if (countClosedEl) countClosedEl.textContent = closedCount;
  if (countAllEl) countAllEl.textContent = totalCount;

  llRenderTicketsList();
}

async function llOpenTicket(id) {
  const modal = document.getElementById('llTicketViewModal');
  const body = document.getElementById('llTicketViewBody');
  const titleEl = document.getElementById('llTicketViewTitle');
  if (!modal || !body || !titleEl) return;

  titleEl.textContent = WFT('tickets.ticket_details', 'تفاصيل التذكرة');
  body.innerHTML = '<div style="padding:24px;text-align:center"><p class="tenant-hint">' +
    llEscape(WFT('common.loading', 'جاري التحميل...')) + '</p></div>';

  if (modal.style.display !== 'flex') openLlModal('llTicketViewModal');

  const data = await api('GET', '/api/support/tickets/' + id).catch(() => null);
  if (!data || !data.success) {
    body.innerHTML = '<div style="padding:24px;text-align:center"><p class="tenant-hint">' +
      llEscape(WFT('tickets.open_failed', 'تعذر فتح التذكرة.')) + '</p></div>';
    return;
  }

  const t = data.ticket || {};
  titleEl.textContent = '#' + t.number + ' ' + (t.subject || '');

  const attachments = (t.attachments || []).map(function (a) {
    return '<button type="button" class="ticket-attachment-pill" onclick="llOpenTicketAttachment(\'' + id + '\',\'' + a.file_id + '\')">' +
      llEscape(a.original_name || WFT('tickets.attachment', 'مرفق')) + '</button>';
  }).join('');

  const messages = (t.messages || []).map(function (m) {
    const isSupport = m.author_role === 'support';
    const bubbleCls = isSupport ? 'support' : 'client';
    const authorName = isSupport ? WFT('tickets.support_team', 'فريق الدعم الفني') : (m.author_name || WFT('tickets.you', 'أنت'));
    const timeStr = (m.created_at || '').slice(0, 16).replace('T', ' ');
    return '<div class="ticket-msg-bubble ' + bubbleCls + '">' +
      '<div class="ticket-msg-author-row">' +
      '<span class="ticket-msg-author">' + llEscape(authorName) + '</span>' +
      (isSupport ? '<span class="ticket-support-tag">' + llEscape(WFT('tickets.platform_support', 'فريق المنصة')) + '</span>' : '') +
      '<span class="ticket-msg-time">' + llEscape(timeStr) + '</span>' +
      '</div>' +
      '<p class="ticket-msg-text">' + llEscape(m.body) + '</p>' +
      '</div>';
  }).join('');

  const isClosed = t.status === 'closed' || t.status === 'resolved';

  body.innerHTML =
    '<div class="ticket-thread-shell">' +
    '<div class="ticket-thread-meta">' +
    llTicketStatusBadge(t.status) +
    llTicketPriorityBadge(t.priority) +
    '<span style="font-size:12px;color:var(--muted)">' + llEscape(WFT('tickets.category', 'الفئة') + ': ' + llTicketCategoryLabel(t.category)) + '</span>' +
    '</div>' +
    (attachments ? '<div class="ticket-attachment-wrap">' + attachments + '</div>' : '') +
    '<div class="ticket-thread-container">' +
    (messages || '<div style="padding:16px;text-align:center"><p class="tenant-hint">' + llEscape(WFT('tickets.no_messages', 'لا توجد رسائل بعد.')) + '</p></div>') +
    '</div>' +
    (!isClosed
      ? '<div class="ticket-reply-composer">' +
        '<textarea id="llReplyBody" class="ticket-reply-textarea" data-i18n-ph="tickets.reply_placeholder" placeholder="' +
        llEscape(WFT('tickets.reply_placeholder', 'اكتب ردك أو استفسارك هنا...')) + '"></textarea>' +
        '<div style="display:flex;justify-content:flex-end">' +
        '<button type="button" class="btn primary small" onclick="llReplyTicket(\'' + id + '\')">' +
        llEscape(WFT('tickets.send_reply', 'إرسال الرد')) + '</button>' +
        '</div>' +
        '</div>'
      : '<div class="ticket-closed-notice">' +
        llEscape(WFT('tickets.closed_notice', 'هذه التذكرة مغلقة. إذا كانت لديك استفسارات إضافية، يرجى فتح تذكرة جديدة.')) +
        '</div>'
    ) +
    '</div>';
}

async function llReplyTicket(id) {
  const input = document.getElementById('llReplyBody');
  const body = (input || {}).value || '';
  if (!body.trim()) return;

  const btn = event && event.target;
  if (btn) btn.disabled = true;

  const res = await api('POST', '/api/support/tickets/' + id + '/messages', { body: body.trim() }).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('tickets.reply_failed', 'تعذر إرسال الرد'));
    if (btn) btn.disabled = false;
    return;
  }

  await llOpenTicket(id);
  await llLoadTickets();
}

async function llOpenTicketAttachment(ticketId, fileId) {
  const token = getTenantToken();
  const response = await fetch(
    '/api/support/tickets/' + encodeURIComponent(ticketId) + '/attachments/' + encodeURIComponent(fileId),
    { headers: token ? { Authorization: 'Bearer ' + token } : {} }
  );
  if (!response.ok) {
    toast(WFT('downloads.load_failed', 'تعذر تحميل الملف'));
    return;
  }
  window.open(URL.createObjectURL(await response.blob()), '_blank');
}

async function adminOpenTicketAttachment(ticketId, fileId) {
  const token = getTenantToken();
  const response = await fetch(
    '/api/admin/support/tickets/' + encodeURIComponent(ticketId) + '/attachments/' + encodeURIComponent(fileId),
    { headers: token ? { Authorization: 'Bearer ' + token } : {} }
  );
  if (!response.ok) {
    toast(WFT('downloads.load_failed', 'تعذر تحميل الملف'));
    return;
  }
  window.open(URL.createObjectURL(await response.blob()), '_blank');
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

  if (!subject.trim()) {
    if (errBox) errBox.textContent = WFT('tickets.subject_required', 'موضوع التذكرة مطلوب');
    return;
  }
  if (!body.trim()) {
    if (errBox) errBox.textContent = WFT('tickets.body_required', 'تفاصيل التذكرة مطلوبة');
    return;
  }

  const attachment = await llUploadTicketAttachment();
  if (attachment && attachment.error) {
    if (errBox) errBox.textContent = attachment.error;
    return;
  }

  const data = await api('POST', '/api/support/tickets', {
    subject: subject.trim(),
    body: body.trim(),
    category: category,
    attachmentFileId: attachment ? attachment.id : null
  }).catch(e => e);

  if (!data || !data.success) {
    if (errBox) errBox.textContent = (data && data.error) || WFT('tickets.create_failed', 'تعذر إنشاء التذكرة');
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

function llToggleFaq(btn) {
  if (!btn) return;
  const item = btn.closest('.support-faq-item');
  if (!item) return;
  const isOpen = item.classList.toggle('open');
  btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}

/* ── Super Admin Support Desk ────────────────────────────────────────────── */

async function openAdminTicketsPage() {
  showTenantPage('tenantAdminTicketsPage');
  const detail = document.getElementById('adminTicketDetail');
  if (detail) detail.style.display = 'none';
  adminSwitchSupportDeskTab('tickets');
  await adminLoadTickets();
}

async function adminLoadTickets() {
  const box = document.getElementById('adminTicketsList');
  if (!box) return;
  box.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
    llEscape(WFT('common.loading', 'جاري التحميل...')) + '</p></div>';

  const status = (document.getElementById('adminTicketsStatusFilter') || {}).value || '';
  const url = '/api/admin/support/tickets' + (status ? '?status=' + encodeURIComponent(status) : '');
  const data = await api('GET', url).catch(() => null);
  if (!data || !data.success) {
    box.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
      llEscape(WFT('tickets.load_failed', 'تعذر تحميل التذاكر.')) + '</p></div>';
    return;
  }

  const tickets = data.tickets || [];
  const openCount = tickets.filter(function (t) { return !['resolved', 'closed'].includes(t.status); }).length;
  const openEl = document.getElementById('adminStatTicketsOpen');
  if (openEl) openEl.textContent = openCount;

  if (!tickets.length) {
    box.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
      llEscape(WFT('tickets.no_tickets', 'لا توجد تذاكر دعم.')) + '</p></div>';
    return;
  }

  box.innerHTML =
    '<div class="support-table-card">' +
    '<div class="table-wrap"><table><thead><tr>' +
    '<th>' + llEscape(WFT('tickets.col_ticket', 'التذكرة')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_company', 'الشركة')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_priority', 'الأولوية')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_status', 'الحالة')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_date', 'التاريخ')) + '</th>' +
    '<th>' + llEscape(WFT('tickets.col_action', 'الإجراء')) + '</th>' +
    '</tr></thead><tbody>' +
    tickets.map(function (t) {
      const date = (t.updated_at || t.created_at || '').slice(0, 16).replace('T', ' ');
      return '<tr class="ticket-row" role="button" tabindex="0" onclick="adminOpenTicket(\'' + t.id + '\')">' +
        '<td><span class="ticket-number-tag">#' + llEscape(t.number) + '</span><strong>' + llEscape(t.subject) + '</strong></td>' +
        '<td>' + llEscape(t.tenant_name || 'شركة') + '</td>' +
        '<td>' + llTicketPriorityBadge(t.priority) + '</td>' +
        '<td>' + llTicketStatusBadge(t.status) + '</td>' +
        '<td><span style="font-size:12px;color:var(--muted)">' + llEscape(date) + '</span></td>' +
        '<td><button type="button" class="btn small ghost" onclick="event.stopPropagation();adminOpenTicket(\'' + t.id + '\')">' +
        llEscape(WFT('common.view', 'عرض')) + '</button></td>' +
        '</tr>';
    }).join('') +
    '</tbody></table></div></div>';
}

async function adminOpenTicket(id) {
  const detail = document.getElementById('adminTicketDetail');
  if (!detail) return;
  detail.style.display = 'block';
  detail.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
    llEscape(WFT('common.loading', 'جاري التحميل...')) + '</p></div>';

  const data = await api('GET', '/api/admin/support/tickets/' + id).catch(() => null);
  if (!data || !data.success) {
    detail.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
      llEscape(WFT('tickets.open_failed', 'تعذر فتح التذكرة.')) + '</p></div>';
    return;
  }

  const t = data.ticket || {};
  const messages = (t.messages || []).map(function (m) {
    const isSupport = m.author_role === 'support';
    const bubbleCls = isSupport ? 'support' : 'client';
    const authorName = m.author_name || (isSupport ? WFT('tickets.platform_team', 'فريق المنصة') : WFT('tickets.client', 'العميل'));
    const timeStr = (m.created_at || '').slice(0, 16).replace('T', ' ');
    return '<div class="ticket-msg-bubble ' + bubbleCls + '">' +
      '<div class="ticket-msg-author-row">' +
      '<span class="ticket-msg-author">' + llEscape(authorName) + '</span>' +
      (isSupport ? '<span class="ticket-support-tag">' + llEscape(WFT('tickets.platform_support', 'فريق المنصة')) + '</span>' : '') +
      '<span class="ticket-msg-time">' + llEscape(timeStr) + '</span>' +
      '</div>' +
      '<p class="ticket-msg-text">' + llEscape(m.body) + '</p>' +
      '</div>';
  }).join('');

  const attachments = (t.attachments || []).map(function (a) {
    return '<button type="button" class="ticket-attachment-pill" onclick="adminOpenTicketAttachment(\'' + id + '\',\'' + a.file_id + '\')">' +
      llEscape(a.original_name || WFT('tickets.attachment', 'مرفق')) + '</button>';
  }).join('');

  const isClosed = t.status === 'closed';

  const statusActions = !isClosed
    ? '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0">' +
      [['in_progress', WFT('tickets.status_in_progress', 'قيد المعالجة'), 'ghost'], ['closed', WFT('tickets.status_resolve_close', 'تم الحل وإغلاق التذكرة'), 'primary']]
        .filter(function (a) { return a[0] !== t.status; })
        .map(function (a) {
          return '<button type="button" class="btn small ' + a[2] + '" onclick="adminSetTicketStatus(\'' + id + '\', \'' + a[0] + '\')">' +
            llEscape(a[1]) + '</button>';
        }).join('') +
      '</div>' +
      '<div class="ticket-reply-composer">' +
      '<textarea id="adminReplyBody" class="ticket-reply-textarea" data-i18n-ph="tickets.admin_reply_placeholder" placeholder="' +
      llEscape(WFT('tickets.admin_reply_placeholder', 'اكتب الرد الرسمي من فريق الدعم الفني...')) + '"></textarea>' +
      '<div style="display:flex;justify-content:flex-end">' +
      '<button type="button" class="btn primary small" onclick="adminReplyTicket(\'' + id + '\')">' +
      llEscape(WFT('tickets.send_reply', 'إرسال الرد')) + '</button>' +
      '</div></div>'
    : '<div class="ticket-closed-notice">' + llEscape(WFT('tickets.admin_closed_notice', 'هذه التذكرة مغلقة.')) + '</div>';

  detail.innerHTML =
    '<div class="support-table-card" style="padding:18px">' +
    '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:12px">' +
    '<h3 style="margin:0;font-size:16px"><span class="ticket-number-tag">#' + llEscape(t.number) + '</span>' +
    llEscape(t.subject) + ' — ' + llTicketStatusBadge(t.status) + '</h3>' +
    '<button type="button" class="btn ghost small" onclick="document.getElementById(\'adminTicketDetail\').style.display=\'none\'">' +
    llEscape(WFT('common.close', 'إغلاق')) + '</button>' +
    '</div>' +
    '<div class="tenant-grid" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;padding:10px;background:#f8fafc;border-radius:8px;margin-bottom:12px">' +
    '<div><span style="font-size:11px;color:var(--muted)">' + llEscape(WFT('tickets.company', 'الشركة')) + ':</span> <strong style="font-size:12.5px">' + llEscape(t.tenant_name || '') + '</strong></div>' +
    '<div><span style="font-size:11px;color:var(--muted)">' + llEscape(WFT('tickets.category', 'الفئة')) + ':</span> <strong style="font-size:12.5px">' + llEscape(llTicketCategoryLabel(t.category)) + '</strong></div>' +
    '<div><span style="font-size:11px;color:var(--muted)">' + llEscape(WFT('tickets.assignee', 'المكلف')) + ':</span> <strong id="adminTicketAssignee" style="font-size:12.5px">' + llEscape(t.assignee_name || '—') + '</strong></div>' +
    '</div>' +
    (attachments ? '<div class="ticket-attachment-wrap">' + attachments + '</div>' : '') +
    '<div id="adminTicketPriorityRow" style="display:flex;gap:8px;margin:12px 0;align-items:center">' +
    '<span style="font-size:12px;font-weight:600">' + llEscape(WFT('tickets.priority', 'الأولوية')) + ':</span>' +
    '<select id="adminTicketPrioritySel" style="font-size:12px;padding:4px 8px">' +
    ['normal', 'low', 'high', 'urgent'].map(function (p) {
      return '<option value="' + p + '"' + ((t.priority || 'normal') === p ? ' selected' : '') + '>' +
        llEscape(llTicketPriorityLabel(p)) + '</option>';
    }).join('') +
    '</select>' +
    '<button type="button" class="btn small ghost" onclick="adminSetTicketPriority(\'' + id + '\')">' +
    llEscape(WFT('tickets.update_priority', 'تحديث الأولوية')) + '</button>' +
    '</div>' +
    '<div id="adminTicketAssignRow" style="display:flex;gap:8px;margin:12px 0;align-items:center"></div>' +
    '<div class="ticket-thread-container">' + (messages || '<p class="tenant-hint">' + llEscape(WFT('tickets.no_messages', 'لا توجد رسائل بعد.')) + '</p>') + '</div>' +
    statusActions +
    '</div>';

  detail.scrollIntoView({ block: 'nearest' });

  const tenantUsers = await api('GET', '/api/admin/tenants/' + t.tenant_id + '/users').catch(() => null);
  const assignRow = document.getElementById('adminTicketAssignRow');
  const users = (tenantUsers && tenantUsers.success && tenantUsers.users) ? tenantUsers.users : [];
  if (assignRow && users.length && !isClosed) {
    assignRow.innerHTML = '<span style="font-size:12px;font-weight:600">' + llEscape(WFT('tickets.assign_to', 'إسناد إلى')) + ':</span> ' +
      '<select id="adminTicketAssignSelect" style="flex:1;font-size:12px;padding:4px 8px">' +
      users.map(function (u) {
        return '<option value="' + llEscape(u.id) + '"' +
          (String(u.id) === String(t.assigned_to) ? ' selected' : '') + '>' +
          llEscape(u.name || u.email) + '</option>';
      }).join('') + '</select>' +
      '<button type="button" class="btn small ghost" onclick="adminAssignTicket(\'' + id + '\')">' +
      llEscape(WFT('tickets.assign_action', 'إسناد')) + '</button>';
  } else if (assignRow) {
    assignRow.innerHTML = '';
  }
}

async function adminAssignTicket(id) {
  const select = document.getElementById('adminTicketAssignSelect');
  const assigneeId = (select || {}).value || '';
  const res = await api('POST', '/api/admin/support/tickets/' + id + '/assign', { assigneeId: assigneeId }).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('tickets.assign_failed', 'تعذر إسناد التذكرة'));
    return;
  }
  toast(WFT('tickets.assigned', 'تم إسناد التذكرة'));
  await adminOpenTicket(id);
  await adminLoadTickets();
}

async function adminReplyTicket(id) {
  const input = document.getElementById('adminReplyBody');
  const body = (input || {}).value || '';
  if (!body.trim()) return;
  const res = await api('POST', '/api/admin/support/tickets/' + id + '/messages', { body: body.trim() }).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('tickets.reply_failed', 'تعذر إرسال الرد'));
    return;
  }
  await adminOpenTicket(id);
  await adminLoadTickets();
}

async function adminSetTicketPriority(id) {
  const sel = document.getElementById('adminTicketPrioritySel');
  if (!sel) return;
  const res = await api('POST', '/api/admin/support/tickets/' + id + '/status', { priority: sel.value }).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('tickets.update_failed', 'تعذر تحديث الأولوية'));
    return;
  }
  toast(WFT('tickets.updated', 'تم التحديث'));
  await adminOpenTicket(id);
  await adminLoadTickets();
}

async function adminSetTicketStatus(id, status) {
  const res = await api('POST', '/api/admin/support/tickets/' + id + '/status', { status: status }).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('tickets.update_failed', 'تعذر تحديث الحالة'));
    return;
  }
  await adminOpenTicket(id);
  await adminLoadTickets();
}

async function llLoadSupportFaqs() {
  const container = document.getElementById('llClientFaqList');
  if (!container) return;
  const res = await api('GET', '/api/support/faqs').catch(() => null);
  if (!res || !res.success || !Array.isArray(res.faqs) || res.faqs.length === 0) {
    container.innerHTML = '<div style="padding:12px 0;text-align:center;"><span class="tenant-hint">' +
      llEscape(WFT('tickets.faq_empty', 'لا توجد أسئلة شائعة حالياً')) + '</span></div>';
    return;
  }
  container.innerHTML = res.faqs.map(function (faq) {
    const q = (typeof wfBilingual === 'function' ? wfBilingual(faq.question_ar, faq.question_en) : faq.question_ar) || faq.question_ar || faq.question_en || '';
    const a = (typeof wfBilingual === 'function' ? wfBilingual(faq.answer_ar, faq.answer_en) : faq.answer_ar) || faq.answer_ar || faq.answer_en || '';
    return '<div class="support-faq-item">' +
      '<button type="button" class="support-faq-q" aria-expanded="false" onclick="llToggleFaq(this)">' +
        '<span>' + llEscape(q) + '</span>' +
        '<span class="support-faq-chevron" aria-hidden="true">' + wsIcon('chevron') + '</span>' +
      '</button>' +
      '<div class="support-faq-a">' + llEscape(a) + '</div>' +
    '</div>';
  }).join('');
}

/* ── Super Admin FAQ Desk ────────────────────────────────────────────────── */

var adminFaqsCache = [];

function adminSwitchSupportDeskTab(tab) {
  const isTickets = (tab === 'tickets');
  const btnTickets = document.getElementById('adminSupportSubTabTickets');
  const btnFaq = document.getElementById('adminSupportSubTabFaq');
  const paneTickets = document.getElementById('adminSupportPaneTickets');
  const paneFaq = document.getElementById('adminSupportPaneFaq');
  const headingActions = document.getElementById('adminTicketsHeadingActions');

  if (btnTickets) btnTickets.classList.toggle('active', isTickets);
  if (btnFaq) btnFaq.classList.toggle('active', !isTickets);
  if (paneTickets) paneTickets.style.display = isTickets ? '' : 'none';
  if (paneFaq) paneFaq.style.display = !isTickets ? '' : 'none';
  if (headingActions) headingActions.style.display = isTickets ? '' : 'none';

  if (!isTickets) {
    adminLoadFaqs();
  }
}

async function adminLoadFaqs() {
  const container = document.getElementById('adminFaqListContainer');
  if (!container) return;
  container.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
    llEscape(WFT('common.loading', 'جاري التحميل...')) + '</p></div>';

  const res = await api('GET', '/api/admin/support/faqs').catch(() => null);
  if (!res || !res.success) {
    container.innerHTML = '<div class="support-table-card" style="padding:24px;text-align:center"><p class="tenant-hint">' +
      llEscape(WFT('admin.faq_save_failed', 'تعذر حفظ الأسئلة الشائعة')) + '</p></div>';
    return;
  }
  adminFaqsCache = res.faqs || [];
  adminRenderFaqsList();
}

function adminRenderFaqsList() {
  const container = document.getElementById('adminFaqListContainer');
  if (!container) return;
  if (!adminFaqsCache.length) {
    container.innerHTML = '<div class="support-table-card" style="padding:32px;text-align:center"><p class="tenant-hint">' +
      llEscape(WFT('admin.faq_empty', 'لا توجد أسئلة شائعة مضافة حالياً')) + '</p></div>';
    return;
  }

  container.innerHTML = '<div class="admin-faq-list">' + adminFaqsCache.map(function (faq, idx) {
    const isFirst = (idx === 0);
    const isLast = (idx === adminFaqsCache.length - 1);
    const statusBadge = faq.is_active
      ? '<span class="admin-faq-status-badge active">' + llEscape(WFT('admin.faq_active', 'نشط للعملاء')) + '</span>'
      : '<span class="admin-faq-status-badge inactive">' + llEscape(WFT('admin.faq_inactive', 'معطل مؤقتاً')) + '</span>';

    return '<div class="admin-faq-item-card ' + (faq.is_active ? '' : 'is-inactive') + '">' +
      '<div class="admin-faq-item-head">' +
        '<div class="admin-faq-item-tags">' +
          '<span class="admin-faq-order-tag">' + (idx + 1) + '</span>' +
          statusBadge +
        '</div>' +
        '<div class="admin-faq-item-actions">' +
          '<button type="button" class="btn small ghost" onclick="adminMoveFaq(' + idx + ', -1)" ' + (isFirst ? 'disabled style="opacity:0.4"' : '') + '>' +
            llEscape(WFT('admin.faq_order_up', 'أعلى')) +
          '</button>' +
          '<button type="button" class="btn small ghost" onclick="adminMoveFaq(' + idx + ', 1)" ' + (isLast ? 'disabled style="opacity:0.4"' : '') + '>' +
            llEscape(WFT('admin.faq_order_down', 'أسفل')) +
          '</button>' +
          '<button type="button" class="btn small ghost" onclick="adminToggleFaqActive(' + idx + ')">' +
            llEscape(faq.is_active ? WFT('admin.faq_deactivate', 'تعطيل') : WFT('admin.faq_activate', 'تفعيل')) +
          '</button>' +
          '<button type="button" class="btn small ghost" onclick="adminOpenFaqModal(' + idx + ')">' +
            llEscape(WFT('common.edit', 'تعديل')) +
          '</button>' +
          '<button type="button" class="btn small danger" onclick="adminDeleteFaq(' + idx + ')">' +
            llEscape(WFT('common.delete', 'حذف')) +
          '</button>' +
        '</div>' +
      '</div>' +
      '<div class="admin-faq-item-body">' +
        '<div class="admin-faq-col">' +
          '<span class="admin-faq-col-label">العربية</span>' +
          '<div class="admin-faq-col-q">' + llEscape(faq.question_ar || '—') + '</div>' +
          '<div class="admin-faq-col-a">' + llEscape(faq.answer_ar || '—') + '</div>' +
        '</div>' +
        '<div class="admin-faq-col">' +
          '<span class="admin-faq-col-label">English</span>' +
          '<div class="admin-faq-col-q">' + llEscape(faq.question_en || '—') + '</div>' +
          '<div class="admin-faq-col-a">' + llEscape(faq.answer_en || '—') + '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }).join('') + '</div>';
}

function adminOpenFaqModal(index) {
  const editIdxInput = document.getElementById('adminFaqEditIndex');
  const qArInput = document.getElementById('adminFaqQuestionAr');
  const qEnInput = document.getElementById('adminFaqQuestionEn');
  const aArInput = document.getElementById('adminFaqAnswerAr');
  const aEnInput = document.getElementById('adminFaqAnswerEn');
  const activeInput = document.getElementById('adminFaqIsActive');
  const errEl = document.getElementById('adminFaqError');
  const titleEl = document.getElementById('adminFaqModalTitle');
  const submitBtn = document.getElementById('adminFaqSubmitBtn');

  if (errEl) errEl.textContent = '';

  const isEdit = (typeof index === 'number' && index >= 0 && index < adminFaqsCache.length);
  if (isEdit) {
    const item = adminFaqsCache[index];
    if (editIdxInput) editIdxInput.value = index;
    if (qArInput) qArInput.value = item.question_ar || '';
    if (qEnInput) qEnInput.value = item.question_en || '';
    if (aArInput) aArInput.value = item.answer_ar || '';
    if (aEnInput) aEnInput.value = item.answer_en || '';
    if (activeInput) activeInput.checked = !!item.is_active;
    if (titleEl) titleEl.textContent = WFT('admin.faq_update_btn', 'تحديث السؤال');
    if (submitBtn) submitBtn.textContent = WFT('admin.faq_update_btn', 'تحديث السؤال');
  } else {
    if (editIdxInput) editIdxInput.value = '-1';
    if (qArInput) qArInput.value = '';
    if (qEnInput) qEnInput.value = '';
    if (aArInput) aArInput.value = '';
    if (aEnInput) aEnInput.value = '';
    if (activeInput) activeInput.checked = true;
    if (titleEl) titleEl.textContent = WFT('admin.faq_add_btn', 'إضافة سؤال جديد');
    if (submitBtn) submitBtn.textContent = WFT('admin.faq_add_btn', 'إضافة سؤال جديد');
  }

  openLlModal('adminFaqModal');
}

async function adminSubmitFaqForm() {
  const editIdx = parseInt((document.getElementById('adminFaqEditIndex') || {}).value, 10);
  const qAr = ((document.getElementById('adminFaqQuestionAr') || {}).value || '').trim();
  const qEn = ((document.getElementById('adminFaqQuestionEn') || {}).value || '').trim();
  const aAr = ((document.getElementById('adminFaqAnswerAr') || {}).value || '').trim();
  const aEn = ((document.getElementById('adminFaqAnswerEn') || {}).value || '').trim();
  const isActive = !!(document.getElementById('adminFaqIsActive') || {}).checked;
  const errEl = document.getElementById('adminFaqError');

  if (!qAr && !qEn) {
    if (errEl) errEl.textContent = WFT('admin.faq_empty_q', 'يجب إدخال السؤال بالعربية أو الإنجليزية على الأقل');
    return;
  }
  if (!aAr && !aEn) {
    if (errEl) errEl.textContent = WFT('admin.faq_empty_a', 'يجب إدخال الإجابة بالعربية أو الإنجليزية على الأقل');
    return;
  }

  if (editIdx >= 0 && editIdx < adminFaqsCache.length) {
    adminFaqsCache[editIdx].question_ar = qAr;
    adminFaqsCache[editIdx].question_en = qEn;
    adminFaqsCache[editIdx].answer_ar = aAr;
    adminFaqsCache[editIdx].answer_en = aEn;
    adminFaqsCache[editIdx].is_active = isActive;
  } else {
    adminFaqsCache.push({
      id: 'faq_' + Date.now().toString(36) + Math.random().toString(36).substr(2, 5),
      question_ar: qAr,
      question_en: qEn,
      answer_ar: aAr,
      answer_en: aEn,
      is_active: isActive,
      order: adminFaqsCache.length + 1
    });
  }

  closeLlModal('adminFaqModal');
  await adminPersistFaqs();
}

async function adminMoveFaq(index, dir) {
  const target = index + dir;
  if (target < 0 || target >= adminFaqsCache.length) return;
  const temp = adminFaqsCache[index];
  adminFaqsCache[index] = adminFaqsCache[target];
  adminFaqsCache[target] = temp;
  adminFaqsCache.forEach(function (f, i) { f.order = i + 1; });
  await adminPersistFaqs();
}

async function adminToggleFaqActive(index) {
  if (index < 0 || index >= adminFaqsCache.length) return;
  adminFaqsCache[index].is_active = !adminFaqsCache[index].is_active;
  await adminPersistFaqs();
}

async function adminDeleteFaq(index) {
  if (index < 0 || index >= adminFaqsCache.length) return;
  const ok = confirm(WFT('admin.faq_delete_confirm', 'هل أنت متأكد من حذف هذا السؤال؟'));
  if (!ok) return;
  adminFaqsCache.splice(index, 1);
  adminFaqsCache.forEach(function (f, i) { f.order = i + 1; });
  await adminPersistFaqs();
}

async function adminPersistFaqs() {
  adminRenderFaqsList();
  const res = await api('PUT', '/api/admin/support/faqs', { faqs: adminFaqsCache }).catch(e => e);
  if (!res || !res.success) {
    toast((res && res.error) || WFT('admin.faq_save_failed', 'تعذر حفظ الأسئلة الشائعة'));
    return;
  }
  toast(WFT('admin.faq_save_success', 'تم حفظ الأسئلة الشائعة بنجاح'));
  adminFaqsCache = res.faqs || adminFaqsCache;
  adminRenderFaqsList();
  llLoadSupportFaqs();
}
