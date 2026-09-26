# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Notifications and work-item tasks (t40-t42): the notification feed
# with per-user preferences and mute categories, and the approval-task
# feed with close/remind.
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
    """Wallet movements reach the company admin alone — the billing permission
    is pinned off for employees, so the notice goes straight to the
    tenant-admin address (which no employee session ever reads)."""
    try:
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


def _recipient_is_actor(tenant_id, recipient, actor_id, actor_is_admin):
    """A decision never pings its own decider. The company admin's two
    addresses — the 'tenant-admin:<id>' key and the primary user's row id —
    are one person whose rows fold onto the same feed, so «self» covers
    either spelling. A *different* decider still notifies the admin
    recipient normally."""
    if not recipient or str(recipient) == str(actor_id):
        return True
    if not actor_is_admin:
        return False
    if str(recipient).startswith('tenant-admin:'):
        return str(actor_id or '').startswith('tenant-admin:')
    try:
        return bool(db.is_primary_company_admin(tenant_id, recipient))
    except Exception:
        return False


def _recipient_is_tenant_admin(tenant_id, recipient):
    """True when a notification address belongs to the company admin — either
    spelling, 'tenant-admin:<id>' or the primary user's row id. A verdict on
    work the admin submitted himself is his own loop closing, so decision
    endpoints skip it instead of echoing it back onto his feed; the draft
    history and audit trail still record it."""
    if not recipient:
        return False
    if str(recipient).startswith('tenant-admin:'):
        return True
    try:
        return bool(db.is_primary_company_admin(tenant_id, recipient))
    except Exception:
        return False


def _notification_muted_categories():
    try:
        prefs = db.get_notification_preferences(g.tenant_id, _notification_recipient_key())
    except Exception:
        prefs = {}
    muted = [category for category, enabled in prefs.items() if not enabled]
    # The role gate is a hard wall, not just a filter list: streams the actor
    # can never receive (wallet/support for staff, tenant work queues for the
    # desk) are muted at the row level too, so a stray broadcast or a
    # misaddressed row can never surface in the feed or the badge count.
    allowed = set(_notification_categories_for_actor())
    muted += [c for c in db.NOTIFICATION_CATEGORIES if c not in allowed]
    return muted


def _notification_categories_for_actor():
    """Categories this actor may actually receive. Wallet, recharge and the
    support desk are company-admin territory (employee sessions have those
    permissions pinned off), so staff feeds never list them as filters or
    preference toggles. The platform desk's feed is narrower still: only the
    queues that actually land on it — company events, top-up requests and
    support tickets."""
    categories = list(db.NOTIFICATION_CATEGORIES)
    if getattr(g, 'is_admin', False):
        desk = {'recharge', 'support', 'platform', 'general'}
        return [category for category in categories if category in desk]
    if _landloom_actor_is_admin():
        return categories
    hidden = set()
    if not _landloom_can('billing'):
        hidden.update(('billing', 'recharge'))
    if not _landloom_can('support_tickets'):
        hidden.add('support')
    return [category for category in categories if category not in hidden]


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
                    'unreadCount': unread,
                    'categories': _notification_categories_for_actor()})


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
                    'categories': _notification_categories_for_actor()})


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
                    'categories': _notification_categories_for_actor()})


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
        mirror_admin=not _landloom_actor_is_admin(),
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
