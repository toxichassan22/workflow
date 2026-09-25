# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Notifications and work-item tasks (t40-t42): the notification feed
# with per-user preferences and mute categories, the approval-task feed
# with close/remind, and event tasks with status transitions.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _notify_tenant_admins(tenant_id, title, body, entity_type=None, entity_id=None):
    """In-app + email notification to every active company admin of the tenant."""
    try:
        # The company admin reads its feed under the tenant-admin address —
        # employees must not see platform-access escalations in theirs.
        tenant = db.get_tenant_by_id(tenant_id)
        db.create_notification(
            tenant_id, title, body, category='general',
            user_id='tenant-admin:' + str(tenant_id),
            entity_type=entity_type, entity_id=entity_id,
            email_to=(tenant or {}).get('email'))
    except Exception as exc:
        print(f'[ACCESS REQUEST] client notification failed: {exc}')


def _notify_super_admins(title, body, entity_type=None, entity_id=None, category='platform'):
    """A platform event lands in every active super admin's feed — the admin
    tenant's own notification stream, visible to all of its logins."""
    try:
        for admin_tenant_id in db.list_admin_tenant_ids():
            db.create_notification(
                admin_tenant_id, title, body, category=category,
                user_id=None, entity_type=entity_type, entity_id=entity_id)
    except Exception as exc:
        print(f'[NOTIFY] super-admin notification failed: {exc}')


def _notify_tenant_billing(tenant_id, title, body, entity_type=None, entity_id=None):
    """Wallet movements reach the users holding the billing permission plus
    the company-owner login (addressed as 'tenant-admin:<id>', which employee
    accounts never match)."""
    try:
        notified = set()
        for user in db.get_users_with_permission(tenant_id, 'billing'):
            if user['id'] in notified:
                continue
            notified.add(user['id'])
            db.create_notification(
                tenant_id, title, body, category='billing', user_id=user['id'],
                entity_type=entity_type, entity_id=entity_id)
        db.create_notification(
            tenant_id, title, body, category='billing',
            user_id='tenant-admin:' + str(tenant_id),
            entity_type=entity_type, entity_id=entity_id)
    except Exception as exc:
        print(f'[NOTIFY] billing notification failed: {exc}')


def _notification_recipient_key():
    """The actor's notification address: their user id for staff logins, or
    the tenant-admin address for the direct company login."""
    return getattr(g, 'user_id', None) or 'tenant-admin:' + str(g.tenant_id)


def _notification_muted_categories():
    try:
        prefs = db.get_notification_preferences(g.tenant_id, _notification_recipient_key())
    except Exception:
        return []
    return [category for category, enabled in prefs.items() if not enabled]


# ── t40: notifications ───────────────────────────────────────────────────────

@app.route('/api/notifications', methods=['GET'])
@require_auth
def api_list_notifications():
    recipient = _notification_recipient_key()
    muted = _notification_muted_categories()
    category = request.args.get('category')
    if category not in db.NOTIFICATION_CATEGORIES:
        category = None
    read_state = (request.args.get('status') or '').strip()
    if read_state not in ('unread', 'read'):
        read_state = None
    unread_only = read_state == 'unread' or request.args.get('unreadOnly') == '1'
    try:
        limit = max(1, min(int(request.args.get('limit') or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = max(0, int(request.args.get('offset') or 0))
    except (TypeError, ValueError):
        offset = 0
    items = db.list_notifications(
        g.tenant_id, user_id=recipient, unread_only=unread_only, limit=limit,
        offset=offset, category=category, muted_categories=muted,
        read_state=read_state)
    total = db.count_notifications(
        g.tenant_id, user_id=recipient, category=category,
        muted_categories=muted, read_state=read_state)
    unread = db.count_notifications(
        g.tenant_id, user_id=recipient, unread_only=True, muted_categories=muted)
    return jsonify({'success': True, 'notifications': items, 'total': total,
                    'unreadCount': unread, 'categories': list(db.NOTIFICATION_CATEGORIES)})


@app.route('/api/notifications/unread-count', methods=['GET'])
@require_auth
def api_notifications_unread_count():
    """The topbar badge polls this — a COUNT, not the feed."""
    count = db.count_notifications(
        g.tenant_id, user_id=_notification_recipient_key(), unread_only=True,
        muted_categories=_notification_muted_categories())
    return jsonify({'success': True, 'unread': count})


@app.route('/api/notifications/preferences', methods=['GET'])
@require_auth
def api_get_notification_preferences():
    prefs = db.get_notification_preferences(g.tenant_id, _notification_recipient_key())
    return jsonify({'success': True, 'preferences': prefs,
                    'categories': list(db.NOTIFICATION_CATEGORIES)})


@app.route('/api/notifications/preferences', methods=['PUT'])
@require_auth
def api_set_notification_preferences():
    data = request.json or {}
    updates = dict(data.get('categories') or {})
    if data.get('category'):
        updates[data['category']] = data.get('enabled')
    recipient = _notification_recipient_key()
    for category, enabled in updates.items():
        if category in db.NOTIFICATION_CATEGORIES:
            db.set_notification_preference(g.tenant_id, recipient, category, bool(enabled))
    prefs = db.get_notification_preferences(g.tenant_id, recipient)
    return jsonify({'success': True, 'preferences': prefs,
                    'categories': list(db.NOTIFICATION_CATEGORIES)})


@app.route('/api/notifications', methods=['POST'])
@require_auth
def api_create_notification():
    """Create an in-app notification (t41).

    A notification aimed at someone else — or broadcast to the whole company
    (no ``userId``) — is an administrative act and needs ``manage_users``;
    workflows notify through ``db.create_notification`` directly, not here.
    """
    data = request.json or {}
    if not str(data.get('title') or '').strip():
        return jsonify({'error': 'A title is required', 'error_code': 'title_required'}), 400
    target_user = data.get('userId')
    if (not target_user or str(target_user) != str(g.user_id)) \
            and not _landloom_can('manage_users'):
        return _landloom_forbidden('إشعار مستخدم آخر أو إشعار عام يتطلب صلاحية إدارة المستخدمين')
    row = db.create_notification(
        g.tenant_id, data.get('title'), body=data.get('body'), category=data.get('category') or 'general',
        user_id=target_user,
        entity_type=data.get('entityType'), entity_id=data.get('entityId'),
        email_to=data.get('emailTo'),
    )
    return jsonify({'success': True, 'notification': row})


@app.route('/api/notifications/read', methods=['POST'])
@require_auth
def api_mark_notifications_read():
    data = request.json or {}
    result = db.mark_notifications_read(
        g.tenant_id, _notification_recipient_key(), notification_ids=data.get('ids'))
    return jsonify({'success': True, 'updated': result})


@app.route('/api/notifications/delete', methods=['POST'])
@require_auth
def api_delete_notifications():
    data = request.json or {}
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({'error': 'Notification ids are required',
                        'error_code': 'ids_required'}), 400
    result = db.delete_notifications(
        g.tenant_id, _notification_recipient_key(), ids[:200])
    return jsonify({'success': True, 'deleted': result})


# ── t41: approval tasks feed ─────────────────────────────────────────────────

_APPROVAL_TASK_KIND_PERMISSION = {
    'section_approval': 'approvals',
    'generation_approval': 'approve_generation',
    'final_approval': 'approve_final_file',
    'support': 'support_tickets',
    'recharge': 'company_settings',
}


def _landloom_is_approver():
    """Any gate-keeping permission makes the actor part of the approver pool."""
    return _landloom_can('approvals') or _landloom_can('approve_generation') \
        or _landloom_can('approve_final_file')


def _landloom_task_actor_allowed(task):
    """An assigned task belongs to its assignee alone (admins excepted); an
    unassigned one stays in the pool of the kind's permission holders."""
    if not task:
        return False
    if task.get('assignee_id'):
        if str(task['assignee_id']) == str(g.user_id):
            return True
        return _landloom_actor_is_admin()
    return _landloom_can(_APPROVAL_TASK_KIND_PERMISSION.get(task.get('kind'), 'approvals'))


@app.route('/api/approval-tasks', methods=['GET'])
@require_auth
def api_list_approval_tasks():
    tasks = db.list_approval_tasks(
        g.tenant_id, status=request.args.get('status') or 'open', kind=request.args.get('kind'),
        assignee_id=request.args.get('assigneeId') or None,
        draft_id=request.args.get('draftId') or None,
        section_key=request.args.get('sectionKey') or None,
        pool_user_id=None if _landloom_actor_is_admin() or not g.user_id else g.user_id,
    )
    return jsonify({'success': True, 'tasks': tasks})


@app.route('/api/approval-tasks/<task_id>/close', methods=['POST'])
@require_auth
def api_close_approval_task(task_id):
    conn = db.get_db()
    task_row = conn.execute(
        'SELECT * FROM approval_tasks WHERE id = ? AND tenant_id = ?', (task_id, g.tenant_id)
    ).fetchone()
    if not task_row:
        return jsonify({'error': 'العنصر غير موجود', 'error_code': 'task_not_found'}), 404
    if not _landloom_task_actor_allowed(dict(task_row)):
        return _landloom_forbidden('إغلاق المهمة يخص المعتمد المكلف بها')
    data = request.json or {}
    result = db.close_approval_task(g.tenant_id, task_id, closed_by_name=_landloom_actor_name(),
                                    cancel_reason=data.get('cancelReason'))
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('approval_task.closed', 'approval_task', task_id,
                        old_value='open', new_value='closed',
                        metadata={'cancel_reason': data.get('cancelReason')})
    return jsonify({'success': True, 'task': result})


@app.route('/api/approval-tasks/<task_id>/remind', methods=['POST'])
@require_auth
def api_remind_approval_task(task_id):
    conn = db.get_db()
    task_row = conn.execute(
        'SELECT * FROM approval_tasks WHERE id = ? AND tenant_id = ?', (task_id, g.tenant_id)
    ).fetchone()
    if not task_row:
        return jsonify({'error': 'العنصر غير موجود', 'error_code': 'task_not_found'}), 404
    if not _landloom_task_actor_allowed(dict(task_row)) \
            and not (not task_row['assignee_id'] and _landloom_is_approver()):
        return _landloom_forbidden('التذكير بالمهمة يخص المعتمدين')
    result = db.remind_approval_task(g.tenant_id, task_id)
    failure = _landloom_error(result)
    if failure:
        return failure
    return jsonify({'success': True, 'task': result})


# ── t42: event tasks ─────────────────────────────────────────────────────────

@app.route('/api/event-tasks', methods=['GET'])
@require_auth
def api_list_event_tasks():
    # Staff see their own tasks (assigned to or created by them); managers and
    # administrators keep the company-wide board.
    own_only = None if _landloom_can('manage_users') else _landloom_actor_id()
    tasks = db.list_event_tasks(
        g.tenant_id, status=request.args.get('status'),
        assignee_user_id=request.args.get('assigneeId'), own_actor_id=own_only,
    )
    return jsonify({'success': True, 'tasks': tasks})


@app.route('/api/event-tasks', methods=['POST'])
@require_auth
def api_create_event_task():
    data = request.json or {}
    assignee_id = data.get('assigneeId')
    if assignee_id:
        assignee = db.get_user_by_id(assignee_id)
        if not assignee or str(assignee.get('tenant_id')) != str(g.tenant_id):
            return jsonify({'error': 'المكلف بالمهمة غير موجود في هذه الشركة',
                            'error_code': 'assignee_not_found'}), 404
    row = db.create_event_task(
        g.tenant_id, data.get('title'), description=data.get('description'),
        event_date=data.get('eventDate'), due_at=data.get('dueAt'),
        assignee_user_id=assignee_id, recurrence=data.get('recurrence') or 'none',
        entity_type=data.get('entityType'), entity_id=data.get('entityId'),
        priority=data.get('priority') or 'normal',
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('event_task.created', 'event_task', row['id'], entity_name=row['title'],
                        metadata={'recurrence': row.get('recurrence'), 'due_at': row.get('due_at')})
    if row.get('assignee_user_id'):
        try:
            db.create_notification(
                g.tenant_id, 'أُسندت إليك مهمة جديدة', body=row.get('title'),
                category='task', user_id=row['assignee_user_id'],
                entity_type='event_task', entity_id=row['id'])
        except Exception:
            pass
    return jsonify({'success': True, 'task': row})


@app.route('/api/event-tasks/<task_id>/status', methods=['POST'])
@require_auth
def api_update_event_task_status(task_id):
    task = db.get_event_task(g.tenant_id, task_id)
    if not task:
        return jsonify({'error': 'Task not found', 'error_code': 'task_not_found'}), 404
    actor_id = _landloom_actor_id()
    if str(task.get('assignee_user_id') or '') != str(g.user_id or '') \
            and str(task.get('created_by') or '') != actor_id \
            and not _landloom_can('manage_users'):
        return _landloom_forbidden('تحديث المهمة يخص المكلف بها أو منشئها')
    result = db.update_event_task_status(g.tenant_id, task_id, (request.json or {}).get('status'),
                                         actor_name=_landloom_actor_name())
    if result is None:
        return jsonify({'error': 'Task not found', 'error_code': 'task_not_found'}), 404
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('event_task.status', 'event_task', task_id,
                        new_value=result.get('status'))
    return jsonify({'success': True, 'task': result})


# ── Super-admin announcements: one notice to a company or to all of them ─────

@app.route('/api/admin/notifications', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_send_notification():
    """The platform desk addresses one company or broadcasts to every active
    one. The row lands tenant-wide (user_id NULL) so every login of the
    company sees it in the notifications feed."""
    data = request.json or {}
    title = str(data.get('title') or '').strip()
    body = str(data.get('body') or '').strip() or None
    if not title:
        return jsonify({'success': False, 'error': 'عنوان الإشعار مطلوب'}), 400
    target = str(data.get('tenantId') or 'all').strip()
    admin_ids = set(db.list_admin_tenant_ids())
    if target == 'all':
        tenants = [t for t in db.get_all_tenants()
                   if t['id'] not in admin_ids and t.get('is_active', 1)]
    else:
        tenant = db.get_tenant_by_id(target)
        if not tenant or target in admin_ids:
            return jsonify({'success': False, 'error': 'الشركة غير موجودة'}), 404
        tenants = [tenant]
    sent = 0
    for tenant in tenants:
        db.create_notification(
            tenant['id'], title, body=body, category='platform',
            user_id=None, entity_type='admin_announcement', entity_id=None)
        sent += 1
    _record_audit_event('admin_notification.sent', 'tenant', target,
                        new_value=title)
    return jsonify({'success': True, 'sent': sent})
