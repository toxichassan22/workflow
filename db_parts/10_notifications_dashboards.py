# ── t41/t24/t42: notifications and the approval task center ─────────────────

NOTIFICATION_CATEGORIES = ('section_approval', 'generation_approval', 'final_approval', 'recharge',
                           'billing', 'support', 'task', 'job', 'platform', 'general')


def create_notification(tenant_id, title, body=None, category='general', user_id=None,
                        entity_type=None, entity_id=None, email_to=None, mirror_admin=True):
    conn = get_db()
    # A notice addressed to the primary user row belongs to the company admin —
    # its session runs tenant-direct and reads under the tenant-admin address,
    # so the row is rewritten to that address instead of sitting unread.
    if user_id and not str(user_id).startswith('tenant-admin:'):
        try:
            primary = conn.execute(
                'SELECT primary_user_id FROM tenants WHERE id = ?', (tenant_id,)
            ).fetchone()
            if primary and str(primary['primary_user_id']) == str(user_id):
                user_id = 'tenant-admin:' + str(tenant_id)
        except Exception:
            pass
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO notifications (id, tenant_id, user_id, category, title, body, entity_type, entity_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, tenant_id, user_id, category if category in NOTIFICATION_CATEGORIES else 'general',
         title, body, entity_type, entity_id),
    )
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO notification_deliveries (id, notification_id, tenant_id, channel, status, delivered_at)
           VALUES (?, ?, ?, 'in_app', 'delivered', ?)''',
        (str(uuid.uuid4()), row_id, tenant_id, now),
    )
    # The company admin sees every notice exchanged between staff members: a
    # row addressed to a specific employee is copied onto the tenant-admin
    # feed (its own row, so the admin's read/delete state never touches the
    # employee's). Callers that already address the admin themselves pass
    # mirror_admin=False to avoid a duplicate.
    if mirror_admin and user_id and not str(user_id).startswith('tenant-admin:'):
        mirror_id = str(uuid.uuid4())
        conn.execute(
            '''INSERT INTO notifications (id, tenant_id, user_id, category, title, body, entity_type, entity_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (mirror_id, tenant_id, 'tenant-admin:' + str(tenant_id),
             category if category in NOTIFICATION_CATEGORIES else 'general',
             title, body, entity_type, entity_id),
        )
        conn.execute(
            '''INSERT INTO notification_deliveries (id, notification_id, tenant_id, channel, status, delivered_at)
               VALUES (?, ?, ?, 'in_app', 'delivered', ?)''',
            (str(uuid.uuid4()), mirror_id, tenant_id, now),
        )
    if email_to:
        delivery_id = str(uuid.uuid4())
        conn.execute(
            '''INSERT INTO notification_deliveries (id, notification_id, tenant_id, channel, status)
               VALUES (?, ?, ?, 'email', 'queued')''',
            (delivery_id, row_id, tenant_id),
        )
        # t41: the email channel actually leaves through the outbox so the
        # worker can retry it — a queued delivery row alone goes nowhere.
        conn.execute(
            '''INSERT INTO email_outbox (id, tenant_id, notification_id, to_email, subject, body_text)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (str(uuid.uuid4()), tenant_id, row_id, str(email_to), title, body),
        )
    conn.commit()
    return dict(conn.execute('SELECT * FROM notifications WHERE id = ?', (row_id,)).fetchone())


def _notification_feed_clauses(tenant_id, user_id, unread_only, category, muted_categories, read_state):
    """Shared WHERE for the notification feed and its count.

    ``user_id`` is the actor's recipient key — a user id for staff logins or
    'tenant-admin:<tenant_id>' for the direct company login — so rows
    addressed to the owner stay invisible to employee accounts while
    broadcasts (user_id NULL) reach everyone."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if user_id:
        clauses.append('(user_id IS NULL OR user_id = ?)')
        params.append(user_id)
    state = read_state or ('unread' if unread_only else None)
    if state == 'unread':
        clauses.append('read_at IS NULL')
    elif state == 'read':
        clauses.append('read_at IS NOT NULL')
    if category:
        clauses.append('category = ?')
        params.append(category)
    muted = [c for c in (muted_categories or []) if c]
    if muted:
        clauses.append('category NOT IN (' + ','.join('?' * len(muted)) + ')')
        params.extend(muted)
    return clauses, params


def list_notifications(tenant_id, user_id=None, unread_only=False, limit=50,
                       category=None, muted_categories=None, offset=0, read_state=None):
    conn = get_db()
    clauses, params = _notification_feed_clauses(
        tenant_id, user_id, unread_only, category, muted_categories, read_state)
    query = ('SELECT * FROM notifications WHERE ' + ' AND '.join(clauses)
             + ' ORDER BY created_at DESC LIMIT ? OFFSET ?')
    params.extend([int(limit), max(0, int(offset or 0))])
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def count_notifications(tenant_id, user_id=None, unread_only=False,
                        category=None, muted_categories=None, read_state=None):
    """Cheap COUNT over the same feed clauses — the badge polls this."""
    conn = get_db()
    clauses, params = _notification_feed_clauses(
        tenant_id, user_id, unread_only, category, muted_categories, read_state)
    row = conn.execute(
        'SELECT COUNT(*) AS c FROM notifications WHERE ' + ' AND '.join(clauses), params,
    ).fetchone()
    return int((dict(row) if row else {}).get('c') or 0)


def get_notification_preferences(tenant_id, user_key):
    """Effective category switches for one actor; every category defaults on."""
    prefs = {category: True for category in NOTIFICATION_CATEGORIES}
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT category, enabled FROM notification_preferences WHERE tenant_id = ? AND user_key = ?',
            (tenant_id, str(user_key)),
        ).fetchall()
    except Exception:
        return prefs
    for row in rows:
        if row['category'] in prefs:
            prefs[row['category']] = bool(row['enabled'])
    return prefs


def set_notification_preference(tenant_id, user_key, category, enabled):
    if category not in NOTIFICATION_CATEGORIES:
        return {'error': 'invalid_category'}
    conn = get_db()
    conn.execute(
        '''INSERT INTO notification_preferences (tenant_id, user_key, category, enabled, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (tenant_id, user_key, category)
           DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at''',
        (tenant_id, str(user_key), category, 1 if enabled else 0, _utcnow().isoformat()),
    )
    conn.commit()
    return {'ok': True}


def list_admin_tenant_ids():
    """Active platform-admin tenant ids — the super-admin notification feed."""
    conn = get_db()
    rows = conn.execute(
        'SELECT id FROM tenants WHERE COALESCE(is_admin, 0) = 1 AND COALESCE(is_active, 1) = 1'
    ).fetchall()
    return [r['id'] for r in rows]


def recent_notification_exists(tenant_id, entity_type, entity_id, since_hours=24):
    """Dedup helper: did this exact event already notify within the window?"""
    conn = get_db()
    from datetime import timedelta
    cutoff = (_utcnow() - timedelta(hours=int(since_hours))).isoformat()
    row = conn.execute(
        '''SELECT 1 AS x FROM notifications
           WHERE tenant_id = ? AND entity_type = ? AND entity_id = ? AND created_at >= ?
           LIMIT 1''',
        (tenant_id, entity_type, entity_id, cutoff),
    ).fetchone()
    return row is not None


def mark_notifications_read(tenant_id, user_id, notification_ids=None):
    conn = get_db()
    now = _utcnow().isoformat()
    if notification_ids:
        placeholders = ','.join('?' for _ in notification_ids)
        cursor = conn.execute(
            f'UPDATE notifications SET read_at = ? WHERE tenant_id = ? AND read_at IS NULL '
            f'AND (user_id IS NULL OR user_id = ?) AND id IN ({placeholders})',
            [now, tenant_id, user_id, *notification_ids],
        )
    else:
        cursor = conn.execute(
            'UPDATE notifications SET read_at = ? WHERE tenant_id = ? AND read_at IS NULL AND (user_id IS NULL OR user_id = ?)',
            (now, tenant_id, user_id),
        )
    conn.commit()
    return cursor.rowcount


def delete_notifications(tenant_id, user_id, notification_ids):
    """Remove feed rows the actor can see — broadcasts plus rows addressed to
    them, never another user's mail. Same visibility scope as the read path."""
    ids = [str(i) for i in (notification_ids or []) if i]
    if not ids:
        return 0
    conn = get_db()
    placeholders = ','.join('?' for _ in ids)
    cursor = conn.execute(
        f'DELETE FROM notifications WHERE tenant_id = ? '
        f'AND (user_id IS NULL OR user_id = ?) AND id IN ({placeholders})',
        [tenant_id, user_id, *ids],
    )
    # A queued email for a deleted notification must not still leave.
    conn.execute(
        "DELETE FROM email_outbox WHERE tenant_id = ? AND status = 'queued' "
        'AND notification_id IS NOT NULL '
        'AND notification_id NOT IN (SELECT id FROM notifications WHERE tenant_id = ?)',
        (tenant_id, tenant_id),
    )
    conn.commit()
    return cursor.rowcount


APPROVAL_TASK_KINDS = ('section_approval', 'generation_approval', 'final_approval', 'revision',
                       'recharge', 'support')


def create_approval_task(tenant_id, kind, title, entity_type=None, entity_id=None,
                         section_key=None, assignee_id=None, assignee_name=None,
                         payload=None, due_hours=None, draft_id=None):
    """t24: a task stays open until the approver or editor resolves it."""
    conn = get_db()
    row_id = str(uuid.uuid4())
    from datetime import timedelta
    due_at = (_utcnow() + timedelta(hours=int(due_hours or 48))).isoformat() if due_hours else None
    if draft_id is None and isinstance(payload, dict):
        draft_id = payload.get('draft_id')
    conn.execute(
        '''INSERT INTO approval_tasks
           (id, tenant_id, kind, title, entity_type, entity_id, section_key, assignee_id, assignee_name, payload, due_at, draft_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, tenant_id, kind if kind in APPROVAL_TASK_KINDS else 'general', title,
         entity_type, entity_id, section_key, assignee_id, assignee_name,
         json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else None, due_at,
         draft_id),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM approval_tasks WHERE id = ?', (row_id,)).fetchone())


def list_approval_tasks(tenant_id, status='open', kind=None, assignee_id=None, draft_id=None,
                        section_key=None, pool_user_id=None, limit=100):
    conn = get_db()
    query = ('SELECT t.*, d.title AS project_name FROM approval_tasks t '
             'LEFT JOIN project_drafts d ON d.id = t.draft_id AND d.tenant_id = t.tenant_id '
             'WHERE t.tenant_id = ?')
    params = [tenant_id]
    if status and status != 'all':
        query += ' AND t.status = ?'
        params.append(status)
    if kind:
        query += ' AND t.kind = ?'
        params.append(kind)
    if assignee_id:
        query += ' AND t.assignee_id = ?'
        params.append(assignee_id)
    if pool_user_id:
        # Employee view: own assigned tasks plus the unassigned pool — a task
        # assigned to a colleague stays invisible to the rest of the pool.
        query += ' AND (t.assignee_id IS NULL OR t.assignee_id = ?)'
        params.append(pool_user_id)
    if draft_id:
        query += ' AND t.draft_id = ?'
        params.append(draft_id)
    if section_key:
        query += ' AND t.section_key = ?'
        params.append(section_key)
    query += ' ORDER BY t.opened_at DESC LIMIT ?'
    params.append(int(limit))
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    now = _utcnow()
    for item in rows:
        try:
            item['is_overdue'] = bool(item.get('due_at')) and datetime.fromisoformat(item['due_at']) < now
        except (TypeError, ValueError):
            item['is_overdue'] = False
    return rows


def close_approval_task(tenant_id, task_id, closed_by_name=None, cancel_reason=None):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM approval_tasks WHERE id = ? AND tenant_id = ?', (task_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'task_not_found'}
    if row['status'] != 'open':
        return {'error': 'task_not_open'}
    cancel_reason = str(cancel_reason or '').strip() or None
    conn.execute(
        'UPDATE approval_tasks SET status = ?, closed_at = ?, closed_by_name = ?, cancel_reason = ? WHERE id = ?',
        ('cancelled' if cancel_reason else 'done', _utcnow().isoformat(), closed_by_name,
         cancel_reason, task_id),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM approval_tasks WHERE id = ?', (task_id,)).fetchone())


def close_approval_tasks_for_entity(tenant_id, entity_type, entity_id, closed_by_name=None,
                                    cancel_reason=None):
    """Close every open task on one entity — t13-03: a decision or a withdrawn
    request must never leave its task open in the approver's queue."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id FROM approval_tasks WHERE tenant_id = ? AND entity_type = ? "
        "AND entity_id = ? AND status = 'open'",
        (tenant_id, entity_type, str(entity_id or '')),
    ).fetchall()
    closed = 0
    for row in rows:
        result = close_approval_task(
            tenant_id, row['id'], closed_by_name=closed_by_name, cancel_reason=cancel_reason)
        if not result.get('error'):
            closed += 1
    return closed


def get_users_with_permission(tenant_id, permission_key):
    """Tenant users whose effective permissions grant ``permission_key``."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, role FROM users WHERE tenant_id = ? AND COALESCE(is_active, 1) = 1",
            (tenant_id,),
        ).fetchall()
    except Exception:
        return []
    users = []
    for row in rows:
        try:
            perms = get_user_permissions(row['id'], row['role'] or 'employee')
        except Exception:
            continue
        if perms.get(permission_key):
            users.append({'id': row['id'], 'name': row['name'], 'role': row['role']})
    return users


def _user_email(user_id):
    """Resolve a notification recipient's mailbox; None when unknown."""
    if not user_id:
        return None
    try:
        row = get_user_by_id(user_id)
    except Exception:
        return None
    email = (row or {}).get('email')
    return str(email).strip() if email else None


def tenant_admin_contacts(tenant_id):
    """The company's admin — the primary user linked from the tenants row."""
    conn = get_db()
    try:
        rows = conn.execute(
            '''SELECT u.id, u.name, u.email FROM users u
               JOIN tenants t ON t.primary_user_id = u.id
               WHERE u.tenant_id = ? AND COALESCE(u.is_active, 1) = 1''',
            (tenant_id,),
        ).fetchall()
    except Exception:
        return []
    return [{'id': r['id'], 'name': r['name'], 'email': r['email']} for r in rows]


def remind_approval_task(tenant_id, task_id):
    """t24: remind the assignee — stamps reminded_at AND notifies them."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM approval_tasks WHERE id = ? AND tenant_id = ?', (task_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'task_not_found'}
    if row['status'] != 'open':
        return {'error': 'task_not_open'}
    conn.execute('UPDATE approval_tasks SET reminded_at = ? WHERE id = ?', (_utcnow().isoformat(), task_id))
    conn.commit()
    if row['assignee_id']:
        create_notification(
            tenant_id, 'تذكير بمهمة معلقة', body=row['title'], category='task',
            entity_type='approval_task', entity_id=task_id,
            user_id=row['assignee_id'],
            email_to=_user_email(row['assignee_id']))
    return dict(conn.execute('SELECT * FROM approval_tasks WHERE id = ?', (task_id,)).fetchone())


def send_due_approval_reminders(tenant_id=None, due_window_hours=12, cooldown_hours=24):
    """t24: automatic reminder pass — open tasks whose due time is near or past
    get reminded once per cooldown window; the assignee is notified in-app and
    by email when they have a mailbox."""
    conn = get_db()
    from datetime import timedelta
    now = _utcnow()
    due_limit = (now + timedelta(hours=int(due_window_hours))).isoformat()
    cooldown = (now - timedelta(hours=int(cooldown_hours))).isoformat()
    clauses = [
        "status = 'open'", 'due_at IS NOT NULL', 'due_at <= ?',
        '(reminded_at IS NULL OR reminded_at < ?)',
    ]
    params = [due_limit, cooldown]
    if tenant_id:
        clauses.insert(0, 'tenant_id = ?')
        params.insert(0, tenant_id)
    rows = conn.execute(
        'SELECT * FROM approval_tasks WHERE ' + ' AND '.join(clauses), params,
    ).fetchall()
    reminded = []
    for row in rows:
        conn.execute(
            'UPDATE approval_tasks SET reminded_at = ? WHERE id = ?',
            (now.isoformat(), row['id']),
        )
        reminded.append(row['id'])
    conn.commit()
    for row in rows:
        create_notification(
            row['tenant_id'], 'تذكير بمهمة معلقة', body=row['title'], category='task',
            entity_type='approval_task', entity_id=row['id'],
            user_id=row['assignee_id'],
            email_to=_user_email(row['assignee_id']))
    return reminded


def escalate_overdue_approval_tasks(tenant_id=None, overdue_hours=24):
    """t24: tasks open past their due time escalate once — stamped and the
    company admin is notified so the escalation reaches a human. With no
    tenant_id the pass covers every company."""
    conn = get_db()
    from datetime import timedelta
    threshold = (_utcnow() - timedelta(hours=int(overdue_hours))).isoformat()
    clauses = ["status = 'open'", 'escalated_at IS NULL',
               'due_at IS NOT NULL', 'due_at < ?']
    params = [threshold]
    if tenant_id:
        clauses.insert(0, 'tenant_id = ?')
        params.insert(0, tenant_id)
    rows = conn.execute(
        'SELECT id, tenant_id, title, assignee_id FROM approval_tasks WHERE '
        + ' AND '.join(clauses), params,
    ).fetchall()
    escalated = []
    for row in rows:
        conn.execute('UPDATE approval_tasks SET escalated_at = ? WHERE id = ?', (_utcnow().isoformat(), row['id']))
        escalated.append(row['id'])
    conn.commit()
    for row in rows:
        admin_email = next(
            (a['email'] for a in tenant_admin_contacts(row['tenant_id']) if a.get('email')),
            None)
        create_notification(
            row['tenant_id'], 'مهمة اعتماد متأخرة صعّدت',
            body=row['title'], category='task',
            entity_type='approval_task', entity_id=row['id'],
            user_id='tenant-admin:' + str(row['tenant_id']),
            email_to=admin_email)
    return escalated


def send_due_event_task_reminders(tenant_id=None, due_window_hours=12, cooldown_hours=24):
    """Event tasks whose due time is near or past remind once per cooldown
    window — the assignee when there is one, otherwise the company-owner
    login (an unassigned task is the owner's job)."""
    conn = get_db()
    from datetime import timedelta
    now = _utcnow()
    due_limit = (now + timedelta(hours=int(due_window_hours))).isoformat()
    cooldown = (now - timedelta(hours=int(cooldown_hours))).isoformat()
    clauses = [
        "status = 'open'", 'due_at IS NOT NULL', 'due_at <= ?',
        '(reminded_at IS NULL OR reminded_at < ?)',
    ]
    params = [due_limit, cooldown]
    if tenant_id:
        clauses.insert(0, 'tenant_id = ?')
        params.insert(0, tenant_id)
    try:
        rows = conn.execute(
            'SELECT * FROM event_tasks WHERE ' + ' AND '.join(clauses), params,
        ).fetchall()
    except Exception:
        return []
    reminded = []
    for row in rows:
        conn.execute(
            'UPDATE event_tasks SET reminded_at = ? WHERE id = ?',
            (now.isoformat(), row['id']),
        )
        reminded.append(row['id'])
    conn.commit()
    for row in rows:
        assignee = row['assignee_user_id']
        create_notification(
            row['tenant_id'], 'مهمة تقترب من موعدها', body=row['title'], category='task',
            entity_type='event_task', entity_id=row['id'],
            user_id=assignee or 'tenant-admin:' + str(row['tenant_id']),
            email_to=_user_email(assignee))
    return reminded
