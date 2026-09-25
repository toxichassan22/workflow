# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Support tickets (t50): the client files and follows its own tickets,
# the super-admin desk sees every company, and status/assignment stay with
# the platform side.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── t50: support tickets ─────────────────────────────────────────────────────

def _landloom_ticket_actor_is_creator(ticket):
    """The requester keeps view/reply rights on their own ticket even without
    the desk permission — tickets filed before the gate existed, or a grant the
    company admin later revoked. Status moves stay with the platform desk."""
    return str((ticket or {}).get('created_by') or '') == str(_landloom_actor_id())


@app.route('/api/support/tickets', methods=['POST'])
@require_auth
def api_create_support_ticket():
    """Opening a ticket is a support-desk act: the company admin or a user
    granted support_tickets — not every authenticated employee."""
    if not _landloom_can('support_tickets'):
        return _landloom_forbidden('فتح تذاكر الدعم يتطلب صلاحية تذاكر الدعم')
    data = request.json or {}
    # Priority is a desk-only field: the client never sets it, every ticket
    # lands 'normal' and the platform triages from its own inbox.
    attachment_id = data.get('attachmentFileId')
    if attachment_id:
        stored = db.get_project_file_by_id(str(attachment_id))
        if not stored or str(stored.get('tenant_id')) != str(g.tenant_id):
            return jsonify({'success': False, 'error': 'المرفق غير موجود'}), 400
    row = db.create_support_ticket(
        g.tenant_id, data.get('subject'), category=data.get('category') or 'general',
        body=data.get('body'),
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
        draft_id=data.get('draftId'), project_id=data.get('projectId'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    if attachment_id:
        db.attach_support_ticket_file(g.tenant_id, row['id'], attachment_id)
    # t40/t42: the support desk sees new tickets as a task plus a notification.
    db.create_approval_task(
        g.tenant_id, 'support',
        f'تذكرة دعم — {row.get("subject")}',
        entity_type='support_ticket', entity_id=row['id'],
        payload={'priority': row.get('priority'), 'category': row.get('category')},
        draft_id=row.get('draft_id'))
    db.create_notification(
        g.tenant_id, 'تذكرة دعم جديدة',
        body=row.get('subject'), category='support',
        entity_type='support_ticket', entity_id=row['id'])
    _notify_super_admins(
        'تذكرة دعم جديدة',
        f'{(g.tenant or {}).get("company_name") or "شركة"} — {row.get("subject") or ""}',
        entity_type='support_ticket', entity_id=row['id'])
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/support/tickets', methods=['GET'])
@require_auth
def api_list_support_tickets():
    """The inbox is the desk surface — permission holders only."""
    if not _landloom_can('support_tickets'):
        return _landloom_forbidden('عرض تذاكر الدعم يتطلب صلاحية تذاكر الدعم')
    rows = db.list_support_tickets(g.tenant_id, status=request.args.get('status'))
    return jsonify({'success': True, 'tickets': rows})


@app.route('/api/support/tickets/<ticket_id>', methods=['GET'])
@require_auth
def api_get_support_ticket(ticket_id):
    row = db.get_support_ticket(g.tenant_id, ticket_id)
    if not row:
        return jsonify({'error': 'Ticket not found', 'error_code': 'ticket_not_found'}), 404
    if not _landloom_can('support_tickets') and not _landloom_ticket_actor_is_creator(row):
        return _landloom_forbidden('عرض التذكرة يتطلب صلاحية تذاكر الدعم')
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/support/tickets/<ticket_id>/messages', methods=['POST'])
@require_auth
def api_add_support_message(ticket_id):
    data = request.json or {}
    if not _landloom_can('support_tickets'):
        ticket = db.get_support_ticket(g.tenant_id, ticket_id)
        if not ticket:
            return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
        if not _landloom_ticket_actor_is_creator(ticket):
            return _landloom_forbidden('الرد على التذكرة يتطلب صلاحية تذاكر الدعم')
    row = db.add_support_message(
        g.tenant_id, ticket_id, data.get('body'), author_id=_landloom_actor_id(),
        author_name=_landloom_actor_name(), author_role='customer',
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    # t40: a customer reply moves the ticket back onto the desk's radar.
    ticket = db.get_support_ticket(g.tenant_id, ticket_id)
    if ticket and ticket.get('status') in ('waiting_customer', 'resolved'):
        db.update_support_ticket_status(g.tenant_id, ticket_id, 'reopened',
                                        actor_name=_landloom_actor_name())
    return jsonify({'success': True, 'message': row})


# ── Super-admin support inbox: tickets of every company land here ────────────

@app.route('/api/support/tickets/<ticket_id>/attachments/<file_id>', methods=['GET'])
@require_auth
def api_support_ticket_attachment(ticket_id, file_id):
    """Stream a ticket attachment. The ticket row is the scope: the owning
    company reads its own files, and the admin route below is the desk's."""
    ticket = db.get_support_ticket(g.tenant_id, ticket_id)
    if not ticket:
        return jsonify({'success': False, 'error': 'التذكرة غير موجودة'}), 404
    if not _landloom_can('support_tickets') and not _landloom_ticket_actor_is_creator(ticket):
        return _landloom_forbidden('عرض التذكرة يتطلب صلاحية تذاكر الدعم')
    return _ticket_attachment_response(ticket, file_id)


@app.route('/api/admin/support/tickets/<ticket_id>/attachments/<file_id>', methods=['GET'])
@require_permission('sag_admin_panel')
def api_admin_support_ticket_attachment(ticket_id, file_id):
    ticket = db.get_support_ticket_admin(ticket_id)
    if not ticket:
        return jsonify({'success': False, 'error': 'التذكرة غير موجودة'}), 404
    return _ticket_attachment_response(ticket, file_id)


def _ticket_attachment_response(ticket, file_id):
    match = next((a for a in (ticket.get('attachments') or [])
                  if str(a.get('file_id')) == str(file_id)), None)
    if not match:
        return jsonify({'success': False, 'error': 'المرفق غير موجود'}), 404
    stored = db.get_project_file_by_id(str(file_id))
    if not stored or not stored.get('storage_path'):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    return _send_project_file_response(stored, stored.get('tenant_id') or g.tenant_id)


@app.route('/api/admin/support/tickets', methods=['GET'])
@require_permission('sag_admin_panel')
def api_admin_list_support_tickets():
    rows = db.list_all_support_tickets(status=request.args.get('status'))
    return jsonify({'success': True, 'tickets': rows})


@app.route('/api/admin/support/tickets/<ticket_id>', methods=['GET'])
@require_permission('sag_admin_panel')
def api_admin_get_support_ticket(ticket_id):
    row = db.get_support_ticket_admin(ticket_id)
    if not row:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/admin/support/tickets/<ticket_id>/messages', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_add_support_message(ticket_id):
    ticket = db.get_support_ticket_admin(ticket_id)
    if not ticket:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    data = request.json or {}
    row = db.add_support_message(
        ticket['tenant_id'], ticket_id, data.get('body'), author_id=_landloom_actor_id(),
        author_name=_landloom_actor_name(), author_role='support',
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('support_ticket.replied', 'support_ticket', ticket_id)
    # t40: the customer sees the desk's reply; the desk marks first response.
    db.create_notification(
        ticket['tenant_id'], 'رد جديد على تذكرة الدعم',
        body=ticket.get('subject'), category='support',
        user_id=ticket.get('created_by'),
        entity_type='support_ticket', entity_id=ticket_id)
    return jsonify({'success': True, 'message': row})


@app.route('/api/admin/support/tickets/<ticket_id>/status', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_update_support_ticket_status(ticket_id):
    ticket = db.get_support_ticket_admin(ticket_id)
    if not ticket:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    data = request.json or {}
    # The desk owns triage: status and priority may move together or alone.
    priority = data.get('priority')
    if priority:
        updated = db.set_support_ticket_priority(ticket_id, priority)
        failure = _landloom_error(updated)
        if failure:
            return failure
        _record_audit_event('support_ticket.priority', 'support_ticket', ticket_id,
                            new_value=priority)
    row = ticket
    if data.get('status') and data.get('status') != ticket['status']:
        row = db.update_support_ticket_status(ticket['tenant_id'], ticket_id, data.get('status'),
                                              actor_name=_landloom_actor_name())
        failure = _landloom_error(row)
        if failure:
            return failure
        _record_audit_event('support_ticket.status', 'support_ticket', ticket_id,
                            new_value=row.get('status'))
        status_label = {'open': 'مفتوحة', 'in_progress': 'قيد المعالجة',
                        'waiting_customer': 'بانتظار العميل', 'escalated': 'مصعّدة',
                        'resolved': 'تم الحل', 'closed': 'مغلقة',
                        'reopened': 'معاد فتحها'}.get(row.get('status'), row.get('status'))
        db.create_notification(
            ticket['tenant_id'], 'تحديث حالة التذكرة',
            body=f'{ticket.get("subject") or ""} — {status_label}',
            category='support', user_id=ticket.get('created_by'),
            entity_type='support_ticket', entity_id=ticket_id)
    row = db.get_support_ticket_admin(ticket_id) or row
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/admin/support/tickets/<ticket_id>/assign', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_assign_support_ticket(ticket_id):
    """t40: route a ticket to a named owner on the desk."""
    ticket = db.get_support_ticket_admin(ticket_id)
    if not ticket:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    data = request.json or {}
    row = db.assign_support_ticket(ticket['tenant_id'], ticket_id, data.get('assigneeId'),
                                   actor_name=_landloom_actor_name())
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('support_ticket.assigned', 'support_ticket', ticket_id,
                        new_value=data.get('assigneeId'))
    return jsonify({'success': True, 'ticket': row})
