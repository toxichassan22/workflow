

# ── t41/t24/t42: notifications and the approval task center ─────────────────

NOTIFICATION_CATEGORIES = ('section_approval', 'generation_approval', 'final_approval', 'recharge',
                           'billing', 'support', 'task', 'job', 'platform', 'general')


def create_notification(tenant_id, title, body=None, category='general', user_id=None,
                        entity_type=None, entity_id=None, email_to=None):
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
                        section_key=None, limit=100):
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
        notified = set()
        recipients = [row['assignee_id']] + [a['id'] for a in tenant_admin_contacts(row['tenant_id'])]
        admin_emails = {a['id']: a['email'] for a in tenant_admin_contacts(row['tenant_id'])}
        for user_id in recipients:
            if not user_id or user_id in notified:
                continue
            notified.add(user_id)
            create_notification(
                row['tenant_id'], 'مهمة اعتماد متأخرة صعّدت',
                body=row['title'], category='task',
                entity_type='approval_task', entity_id=row['id'],
                user_id=user_id,
                email_to=admin_emails.get(user_id) or _user_email(user_id))
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


# ── t32/t33: recharge (package purchase) requests ───────────────────────────

def create_recharge_request(tenant_id, package_name, amount_usd=0, price_sar=None,
                            transfer_reference=None, requested_by=None, requested_by_name=None,
                            package_id=None, receipt_file_id=None):
    """File a package purchase request (t33).

    When a ``package_id`` is supplied the amount and price come from the
    catalog row, not the client; a bank-transfer reference may only back one
    request so the same receipt cannot be submitted twice. Every request must
    carry proof of the transfer: the bank reference number or an uploaded
    receipt (either one suffices).
    """
    transfer_reference = str(transfer_reference or '').strip() or None
    if not transfer_reference and not str(receipt_file_id or '').strip():
        return {'error': 'reference_or_receipt_required'}
    conn = get_db()
    if transfer_reference:
        duplicate = conn.execute(
            """SELECT id FROM recharge_requests
               WHERE transfer_reference = ? AND status != 'rejected'""",
            (transfer_reference,),
        ).fetchone()
        if duplicate:
            return {'error': 'duplicate_transfer_reference'}
    if package_id:
        package = conn.execute(
            'SELECT * FROM billing_packages WHERE id = ? AND is_active = 1',
            (str(package_id),),
        ).fetchone()
        if not package:
            return {'error': 'package_not_found'}
        package = dict(package)
        package_name = package.get('name')
        amount_usd = package.get('credit_usd') or 0
        price_sar = package.get('price_sar')
    if not str(package_name or '').strip():
        return {'error': 'package_name_required'}
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO recharge_requests
           (id, tenant_id, package_id, package_name, amount_usd, price_sar, transfer_reference,
            receipt_file_id, requested_by, requested_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, tenant_id, package_id, str(package_name).strip(), float(amount_usd or 0),
         float(price_sar) if price_sar is not None else None, transfer_reference, receipt_file_id,
         requested_by, requested_by_name),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM recharge_requests WHERE id = ?', (row_id,)).fetchone())


def decide_recharge_request(tenant_id, request_id, decision, reviewed_by, reviewed_by_name,
                            note=None, reference_number=None):
    """Approve or reject a recharge request atomically (t33/d09).

    One commit covers the decision, the wallet credit and the financial
    document: an approval that cannot credit rolls the decision back, and a
    repeated approval cannot mint a second credit or a second invoice.
    """
    if decision not in {'approved', 'rejected'}:
        return {'error': 'invalid_decision'}
    conn = get_db()
    if tenant_id:
        row = conn.execute(
            'SELECT * FROM recharge_requests WHERE id = ? AND tenant_id = ?', (request_id, tenant_id),
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT * FROM recharge_requests WHERE id = ?', (request_id,),
        ).fetchone()
    if not row:
        return {'error': 'request_not_found'}
    if row['status'] != 'pending':
        return {'error': 'request_not_pending'}
    target_tenant_id = row['tenant_id']
    if decision == 'approved':
        target = conn.execute('SELECT is_admin FROM tenants WHERE id = ?', (target_tenant_id,)).fetchone()
        if target and target['is_admin']:
            return {'error': 'platform_tenant_recharge_forbidden'}
    reference = str(reference_number or '').strip()
    if decision == 'approved' and not reference:
        reference = 'RCH-' + _utcnow().strftime('%Y%m%d') + '-' + request_id[:8].upper()
    conn.execute(
        '''UPDATE recharge_requests SET status = ?, reviewed_by = ?, reviewed_by_name = ?,
           reviewed_at = ?, decision_note = ?, reference_number = ? WHERE id = ?''',
        (decision, reviewed_by, reviewed_by_name, _utcnow().isoformat(),
         str(note or '').strip() or None, reference if decision == 'approved' else row['reference_number'],
         request_id),
    )
    if decision == 'approved' and float(row['amount_usd'] or 0) > 0:
        amount = round(float(row['amount_usd']) + 1e-9, 2)
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (target_tenant_id, 'recharge:' + request_id),
        ).fetchone()
        if not existing:
            conn.execute(
                'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
                (amount, target_tenant_id),
            )
            conn.execute(
                '''INSERT INTO tenant_ledger
                   (id, tenant_id, kind, amount_usd, raw_cost_usd, multiplier,
                    maps_cost_usd, ai_cost_usd, maps_events_count, ai_events_count,
                    draft_id, presentation_id, idempotency_key, note, actor)
                   VALUES (?, ?, 'credit', ?, 0, 1, 0, 0, 0, 0, NULL, NULL, ?, ?, ?)''',
                (str(uuid.uuid4()), target_tenant_id, amount, 'recharge:' + request_id,
                 'شحن رصيد بالمرجع ' + reference, 'recharge_decision'),
            )
        _create_topup_receipt_tx(
            conn, target_tenant_id, recharge_request_id=request_id,
            receipt_file_id=row['receipt_file_id'] if 'receipt_file_id' in row.keys() else None,
            transfer_reference=row['transfer_reference'] if 'transfer_reference' in row.keys() else None,
            amount_usd=amount, price_sar=row['price_sar'] if 'price_sar' in row.keys() else None,
            issued_by=reviewed_by, issued_by_name=reviewed_by_name)
    conn.commit()
    if decision == 'approved' and float(row['amount_usd'] or 0) > 0:
        _fire_balance_change(target_tenant_id)
    return dict(conn.execute('SELECT * FROM recharge_requests WHERE id = ?', (request_id,)).fetchone())


def list_recharge_requests(tenant_id=None, status=None, limit=100):
    conn = get_db()
    query = 'SELECT * FROM recharge_requests'
    clauses = []
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    if status:
        clauses.append('status = ?')
        params.append(status)
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY requested_at DESC LIMIT ?'
    params.append(int(limit))
    return with_sar_fields([dict(row) for row in conn.execute(query, params).fetchall()])


# ── t40: support tickets ────────────────────────────────────────────────────

def create_support_ticket(tenant_id, subject, category='general', priority='normal',
                          created_by=None, created_by_name=None, body=None,
                          draft_id=None, project_id=None):
    subject = str(subject or '').strip()
    if not subject:
        return {'error': 'subject_required'}
    if category not in SUPPORT_TICKET_CATEGORIES:
        return {'error': 'invalid_category'}
    if priority not in SUPPORT_TICKET_PRIORITIES:
        priority = 'normal'
    conn = get_db()
    ticket_id = str(uuid.uuid4())
    number = conn.execute(
        'SELECT COALESCE(MAX(number), 0) + 1 AS next FROM support_tickets WHERE tenant_id = ?',
        (tenant_id,),
    ).fetchone()
    conn.execute(
        '''INSERT INTO support_tickets
           (id, tenant_id, number, subject, category, priority, status, created_by, created_by_name,
            draft_id, project_id)
           VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)''',
        (ticket_id, tenant_id, int(number['next']), subject, category, priority,
         created_by, created_by_name, draft_id, project_id),
    )
    if body:
        conn.execute(
            '''INSERT INTO support_ticket_messages (id, ticket_id, tenant_id, author_id, author_name, author_role, body)
               VALUES (?, ?, ?, ?, ?, 'customer', ?)''',
            (str(uuid.uuid4()), ticket_id, tenant_id, created_by, created_by_name or 'عميل', body),
        )
    conn.commit()
    return dict(conn.execute('SELECT * FROM support_tickets WHERE id = ?', (ticket_id,)).fetchone())


def list_support_tickets(tenant_id, status=None, limit=100):
    conn = get_db()
    if status:
        rows = conn.execute(
            'SELECT * FROM support_tickets WHERE tenant_id = ? AND status = ? ORDER BY updated_at DESC LIMIT ?',
            (tenant_id, status, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM support_tickets WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT ?',
            (tenant_id, int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_support_ticket(tenant_id, ticket_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM support_tickets WHERE id = ? AND tenant_id = ?', (ticket_id, tenant_id),
    ).fetchone()
    if not row:
        return None
    ticket = dict(row)
    ticket['messages'] = [dict(m) for m in conn.execute(
        'SELECT * FROM support_ticket_messages WHERE ticket_id = ? ORDER BY created_at', (ticket_id,),
    ).fetchall()]
    try:
        ticket['attachments'] = list_support_ticket_attachments(ticket_id)
    except Exception:
        ticket['attachments'] = []
    return ticket


def list_all_support_tickets(status=None, limit=200):
    """Platform inbox: tickets of every company with the company name attached."""
    conn = get_db()
    query = ('SELECT t.*, tn.company_name AS tenant_name '
             'FROM support_tickets t LEFT JOIN tenants tn ON tn.id = t.tenant_id')
    params = []
    if status:
        query += ' WHERE t.status = ?'
        params.append(status)
    query += ' ORDER BY t.updated_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_support_ticket_admin(ticket_id):
    """Ticket plus its messages and owning company, without tenant scoping."""
    conn = get_db()
    row = conn.execute(
        'SELECT t.*, tn.company_name AS tenant_name FROM support_tickets t '
        'LEFT JOIN tenants tn ON tn.id = t.tenant_id WHERE t.id = ?',
        (ticket_id,),
    ).fetchone()
    if not row:
        return None
    ticket = dict(row)
    ticket['messages'] = [dict(m) for m in conn.execute(
        'SELECT * FROM support_ticket_messages WHERE ticket_id = ? ORDER BY created_at', (ticket_id,),
    ).fetchall()]
    try:
        ticket['attachments'] = list_support_ticket_attachments(ticket_id)
    except Exception:
        ticket['attachments'] = []
    return ticket


def add_support_message(tenant_id, ticket_id, body, author_id=None, author_name=None, author_role='customer'):
    body = str(body or '').strip()
    if not body:
        return {'error': 'body_required'}
    conn = get_db()
    ticket = conn.execute(
        'SELECT * FROM support_tickets WHERE id = ? AND tenant_id = ?', (ticket_id, tenant_id),
    ).fetchone()
    if not ticket:
        return {'error': 'ticket_not_found'}
    now = _utcnow().isoformat()
    message_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO support_ticket_messages (id, ticket_id, tenant_id, author_id, author_name, author_role, body)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (message_id, ticket_id, tenant_id, author_id, author_name or 'مستخدم', author_role, body),
    )
    updates = ['updated_at = ?']
    params = [now]
    if author_role != 'customer' and not ticket['first_response_at']:
        updates.append('first_response_at = ?')
        params.append(now)
    if ticket['status'] == 'resolved' and author_role == 'customer':
        updates.append("status = 'open'")
    conn.execute(
        'UPDATE support_tickets SET ' + ', '.join(updates) + ' WHERE id = ?',
        [*params, ticket_id],
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM support_ticket_messages WHERE id = ?', (message_id,)).fetchone())


def update_support_ticket_status(tenant_id, ticket_id, new_status, actor_name=None):
    if new_status not in SUPPORT_TICKET_STATUSES:
        return {'error': 'invalid_status'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM support_tickets WHERE id = ? AND tenant_id = ?', (ticket_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'ticket_not_found'}
    # t40: a waiting/resolved/closed ticket can only move forward through
    # 'reopened', which keeps the resolution timestamps and counts the regression.
    if new_status == 'reopened' and row['status'] not in ('waiting_customer', 'resolved', 'closed'):
        return {'error': 'invalid_transition', 'current_status': row['status']}
    now = _utcnow().isoformat()
    updates = ["status = ?", "updated_at = ?"]
    params = [new_status, now]
    if new_status == 'resolved':
        updates.append('resolved_at = ?')
        params.append(now)
    if new_status == 'closed':
        updates.append('closed_at = ?')
        params.append(now)
    if new_status == 'reopened':
        updates.append('reopened_count = COALESCE(reopened_count, 0) + 1')
        updates.append('resolved_at = NULL')
        updates.append('closed_at = NULL')
    conn.execute(
        'UPDATE support_tickets SET ' + ', '.join(updates) + ' WHERE id = ?',
        [*params, ticket_id],
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM support_tickets WHERE id = ?', (ticket_id,)).fetchone())


def assign_support_ticket(tenant_id, ticket_id, assignee_id, actor_name=None):
    """Route a ticket to a named owner; assignee must be a live tenant user."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM support_tickets WHERE id = ? AND tenant_id = ?', (ticket_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'ticket_not_found'}
    assignee_name = None
    if assignee_id:
        assignee = conn.execute(
            'SELECT id, name FROM users WHERE id = ? AND tenant_id = ?',
            (str(assignee_id), str(tenant_id)),
        ).fetchone()
        if not assignee:
            return {'error': 'assignee_not_found'}
        assignee_name = assignee['name']
    conn.execute(
        'UPDATE support_tickets SET assigned_to = ?, updated_at = ? WHERE id = ?',
        (assignee_id, _utcnow().isoformat(), ticket_id),
    )
    conn.commit()
    result = dict(conn.execute('SELECT * FROM support_tickets WHERE id = ?', (ticket_id,)).fetchone())
    result['assignee_name'] = assignee_name
    return result


# ── t54: operational monitoring that never exposes client content ───────────

def _activity_bucket_pairs(months=12, from_month=None, to_month=None):
    """Bucket grid shared by the platform and company activity charts.

    Returns (labels, bucket_keys, bucket): display labels, the substr() prefix
    per bucket, and the prefix width (7 = month, 10 = day, 13 = hour).
    """
    now = _utcnow()

    def _parse_range_dt(value, is_end=False):
        s = str(value or '').strip()
        try:
            if len(s) >= 16:
                return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]),
                                int(s[11:13]), int(s[14:16])), True
            if len(s) >= 10:
                d = datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]))
                return (d + timedelta(days=1) - timedelta(seconds=1)) if is_end else d, False
            if len(s) == 7:
                y, m = int(s[0:4]), int(s[5:7])
                d = datetime(y, m, 1)
                if is_end:
                    d = datetime(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1) - timedelta(seconds=1)
                return d, False
        except (ValueError, IndexError):
            pass
        return None, False

    pairs = []  # (display label, substr bucket key)
    (start_dt, s_has_time), (end_dt, e_has_time) = _parse_range_dt(from_month), _parse_range_dt(to_month, is_end=True)
    bucket = 7
    if start_dt and end_dt:
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt
        span = end_dt - start_dt
        hourly = span <= timedelta(hours=48) if (s_has_time or e_has_time) else start_dt.date() == end_dt.date()
        if hourly:
            bucket = 13
            cur = start_dt.replace(minute=0, second=0, microsecond=0)
            while cur <= end_dt and len(pairs) < 96:
                pairs.append(('%04d-%02d-%02d %02d:00' % (cur.year, cur.month, cur.day, cur.hour),
                              '%04d-%02d-%02d %02d' % (cur.year, cur.month, cur.day, cur.hour)))
                cur += timedelta(hours=1)
        elif span <= timedelta(days=95):
            bucket = 10
            cur = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            while cur <= end_dt and len(pairs) < 96:
                key = '%04d-%02d-%02d' % (cur.year, cur.month, cur.day)
                pairs.append((key, key))
                cur += timedelta(days=1)
        else:
            cur = start_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while cur <= end_dt and len(pairs) < 37:
                key = '%04d-%02d' % (cur.year, cur.month)
                pairs.append((key, key))
                cur = datetime(cur.year + (1 if cur.month == 12 else 0),
                               1 if cur.month == 12 else cur.month + 1, 1)
    if not pairs:
        try:
            months = max(1, min(int(months or 12), 36))
        except (TypeError, ValueError):
            months = 12
        for i in range(months - 1, -1, -1):
            mm = now.month - i
            yy = now.year + (mm - 1) // 12
            mm = (mm - 1) % 12 + 1
            key = '%04d-%02d' % (yy, mm)
            pairs.append((key, key))
    return [p[0] for p in pairs], [p[1] for p in pairs], bucket


def operational_overview(months=12, from_month=None, to_month=None):
    """Counts and activity shape only: the super-admin never sees client content."""
    conn = get_db()
    def count(table, where='1 = 1', params=()):
        try:
            row = conn.execute('SELECT COUNT(*) AS n FROM ' + table + ' WHERE ' + where, params).fetchone()
            return int(row['n'] or 0)
        except Exception:
            return 0

    def monthly_map(table, value_sql='COUNT(*)', date_col='created_at', where='1 = 1', bucket=7):
        try:
            rows = conn.execute(
                'SELECT substr(' + date_col + ', 1, ' + str(int(bucket)) + ') AS m, ' + value_sql + ' AS v FROM ' + table +
                ' WHERE ' + where + ' AND ' + date_col + ' IS NOT NULL GROUP BY m'
            ).fetchall()
            return {r['m']: float(r['v'] or 0) for r in rows if r['m']}
        except Exception:
            return {}

    now = _utcnow()
    labels, bucket_keys, bucket = _activity_bucket_pairs(months, from_month, to_month)

    series_maps = {
        'companies': monthly_map('tenants', where='is_admin = 0', bucket=bucket),
        'presentations': monthly_map('presentations', bucket=bucket),
        'users': monthly_map('users', bucket=bucket),
        'ai_spend': monthly_map('ai_usage_events', 'COALESCE(SUM(cost_usd), 0)', bucket=bucket),
        'maps_spend': monthly_map('map_usage_events', 'COALESCE(SUM(cost_usd), 0)', bucket=bucket),
        'revenue': monthly_map('recharge_requests', 'COALESCE(SUM(amount_usd), 0)',
                               date_col='reviewed_at', where="status = 'approved'", bucket=bucket),
        # Recharges are paid in riyals — the SAR series reads price_sar
        # directly instead of converting the wallet-dollar figure.
        'revenue_sar': monthly_map('recharge_requests', 'COALESCE(SUM(price_sar), 0)',
                                   date_col='reviewed_at', where="status = 'approved'", bucket=bucket),
        'tickets': monthly_map('support_tickets', bucket=bucket),
    }
    try:
        fx_rate = float((get_fx_rate() or {}).get('rate') or FX_DEFAULT_USD_SAR)
    except (TypeError, ValueError):
        fx_rate = FX_DEFAULT_USD_SAR
    trends = {'labels': labels}
    for key, mmap in series_maps.items():
        trends[key] = [round(mmap.get(k, 0), 2) for k in bucket_keys]
    trends['ai_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['ai_spend']]
    trends['maps_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['maps_spend']]

    def delta(mmap):
        cur = mmap.get(bucket_keys[-1], 0)
        prev = mmap.get(bucket_keys[-2], 0)
        if not prev:
            return None
        return round((cur - prev) / float(prev) * 100)

    ticket_status = {}
    try:
        for r in conn.execute('SELECT status, COUNT(*) AS n FROM support_tickets GROUP BY status').fetchall():
            ticket_status[r['status'] or 'open'] = int(r['n'] or 0)
    except Exception:
        pass

    spend_map = series_maps['ai_spend']
    maps_map = series_maps['maps_spend']
    revenue_map = series_maps['revenue']
    return {
        'tenants': {
            'total': count('tenants'),
            'companies': count('tenants', 'is_admin = 0'),
            'active': count('tenants', 'is_active = 1'),
            'active_companies': count('tenants', 'is_active = 1 AND is_admin = 0'),
        },
        'users': {'total': count('users'), 'active': count('users', 'is_active = 1')},
        'drafts': {'total': count('project_drafts')},
        'presentations': {'total': count('presentations'), 'approved': count('presentations', "status = 'approved'")},
        'workflows': {
            'pending_recharges': count('recharge_requests', "status = 'pending'"),
            'open_support_tickets': count('support_tickets', "status IN ('open', 'in_progress', 'waiting_customer')"),
            'open_tasks': count('approval_tasks', "status = 'open'"),
        },
        'tickets_by_status': ticket_status,
        'revenue': {
            'month_usd': round(revenue_map.get(bucket_keys[-1], 0), 2),
            'total_usd': round(sum(revenue_map.values()), 2),
            'month_sar': round(series_maps['revenue_sar'].get(bucket_keys[-1], 0), 2),
            'total_sar': round(sum(series_maps['revenue_sar'].values()), 2),
        },
        'spend': {
            'month_usd': round(spend_map.get(bucket_keys[-1], 0) + maps_map.get(bucket_keys[-1], 0), 2),
            'total_usd': round(sum(spend_map.values()) + sum(maps_map.values()), 2),
            'month_sar': usd_to_sar(
                spend_map.get(bucket_keys[-1], 0) + maps_map.get(bucket_keys[-1], 0), fx_rate),
            'total_sar': usd_to_sar(
                sum(spend_map.values()) + sum(maps_map.values()), fx_rate),
        },
        'trends': trends,
        'deltas': {
            'companies': delta(series_maps['companies']),
            'presentations': delta(series_maps['presentations']),
            'users': delta(series_maps['users']),
            'spend': delta({k: spend_map.get(k, 0) + maps_map.get(k, 0) for k in bucket_keys}),
            'revenue': delta(revenue_map),
            'tickets': delta(series_maps['tickets']),
        },
        'storage': storage_overview(),
        'generation': generation_job_metrics(),
        'queue': _job_queue_metrics(),
        'email': _email_outbox_metrics(),
        'alerts': platform_alerts(),
        'backup': {
            'rpo_hours': RPO_TARGET_HOURS,
            'rto_hours': RTO_TARGET_HOURS,
            'latest': latest_successful_backup(),
        },
        'generated_at': now.isoformat(),
    }


def _job_queue_metrics():
    conn = get_db()
    result = {'queued': 0, 'running': 0, 'done': 0, 'failed': 0, 'dead': 0}
    try:
        for row in conn.execute('SELECT status, COUNT(*) AS n FROM job_queue GROUP BY status').fetchall():
            if row['status'] in result:
                result[row['status']] = int(row['n'] or 0)
    except Exception:
        pass
    return result


def _email_outbox_metrics():
    conn = get_db()
    result = {'queued': 0, 'sent': 0, 'failed': 0}
    try:
        for row in conn.execute('SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status').fetchall():
            if row['status'] in result:
                result[row['status']] = int(row['n'] or 0)
    except Exception:
        pass
    return result


# ═════════════════════════════════════════════════════════════════════════════
# t55: dashboards and exportable reports
# ═════════════════════════════════════════════════════════════════════════════


def client_dashboard(tenant_id):
    """Client home: lifecycle buckets, open work, balance and month spend (t55)."""
    conn = get_db()
    tenant_id = str(tenant_id)
    by_status = {}
    try:
        for row in conn.execute(
            'SELECT status, COUNT(*) AS n FROM project_drafts WHERE tenant_id = ? GROUP BY status',
            (tenant_id,),
        ).fetchall():
            by_status[normalize_proposal_status(row['status'])] = \
                by_status.get(normalize_proposal_status(row['status']), 0) + int(row['n'] or 0)
    except Exception:
        pass
    lifecycle = [{'key': key, 'label': meta.get('label'), 'label_en': meta.get('label_en'),
                  'count': by_status.get(key, 0)}
                 for key, meta in sorted(PROPOSAL_LIFECYCLE_STATES.items(),
                                         key=lambda kv: kv[1].get('order', 0))]

    def _count(table, where='1 = 1', params=()):
        try:
            return int(conn.execute(
                f'SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = ? AND {where}',
                (tenant_id,) + tuple(params)).fetchone()['n'] or 0)
        except Exception:
            return 0

    month_prefix = _utcnow().strftime('%Y-%m')
    month_ai = 0.0
    month_maps = 0.0
    try:
        month_ai = float(conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS t FROM ai_usage_events "
            "WHERE tenant_id = ? AND substr(created_at, 1, 7) = ?",
            (tenant_id, month_prefix)).fetchone()['t'] or 0.0)
        month_maps = float(conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS t FROM map_usage_events "
            "WHERE tenant_id = ? AND substr(created_at, 1, 7) = ?",
            (tenant_id, month_prefix)).fetchone()['t'] or 0.0)
    except Exception:
        pass
    recent_files = []
    try:
        for row in conn.execute(
            '''SELECT id, title, status, updated_at FROM project_drafts
               WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT 8''',
            (tenant_id,),
        ).fetchall():
            item = dict(row)
            item['status'] = normalize_proposal_status(item.get('status'))
            item['status_label'] = PROPOSAL_LIFECYCLE_STATES.get(item['status'], {}).get('label')
            recent_files.append(item)
    except Exception:
        pass
    notifications_unread = 0
    try:
        notifications_unread = int(conn.execute(
            'SELECT COUNT(*) AS n FROM notifications WHERE tenant_id = ? AND read_at IS NULL',
            (tenant_id,),
        ).fetchone()['n'] or 0)
    except Exception:
        pass
    return {
        'lifecycle': lifecycle,
        'open_approval_tasks': _count('approval_tasks', "status = 'open'"),
        'open_event_tasks': _count('event_tasks', "status = 'open'"),
        'open_tickets': _count('support_tickets', "status IN ('open', 'in_progress', 'waiting_customer')"),
        'unread_notifications': notifications_unread,
        'month_consumption_usd': round(month_ai + month_maps, 4),
        'month_consumption_sar': usd_to_sar(month_ai + month_maps),
        'recent_files': recent_files,
        'pending_generation': _count('generation_approvals', "status = 'pending'"),
        'pending_final': _count('final_file_approvals', "status = 'pending'"),
    }


def client_activity_trends(tenant_id, months=12, from_month=None, to_month=None):
    """Company-scoped series for the dashboard activity chart.

    Same bucket grid as the super-admin platform chart, but every series is
    filtered to the tenant: spend (AI + maps) and newly created presentations.
    """
    conn = get_db()
    tenant_id = str(tenant_id)
    labels, bucket_keys, bucket = _activity_bucket_pairs(months, from_month, to_month)

    def monthly_map(table, value_sql='COUNT(*)', date_col='created_at'):
        try:
            rows = conn.execute(
                'SELECT substr(' + date_col + ', 1, ' + str(int(bucket)) + ') AS m, ' + value_sql + ' AS v FROM ' + table +
                ' WHERE tenant_id = ? AND ' + date_col + ' IS NOT NULL GROUP BY m',
                (tenant_id,)).fetchall()
            return {r['m']: float(r['v'] or 0) for r in rows if r['m']}
        except Exception:
            return {}

    series_maps = {
        'presentations': monthly_map('presentations'),
        'ai_spend': monthly_map('ai_usage_events', 'COALESCE(SUM(cost_usd), 0)'),
        'maps_spend': monthly_map('map_usage_events', 'COALESCE(SUM(cost_usd), 0)'),
    }
    try:
        fx_rate = float((get_fx_rate() or {}).get('rate') or FX_DEFAULT_USD_SAR)
    except (TypeError, ValueError):
        fx_rate = FX_DEFAULT_USD_SAR
    trends = {'labels': labels}
    for key, mmap in series_maps.items():
        trends[key] = [round(mmap.get(k, 0), 2) for k in bucket_keys]
    trends['ai_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['ai_spend']]
    trends['maps_spend_sar'] = [usd_to_sar(v, fx_rate) for v in trends['maps_spend']]
    return trends


def company_admin_dashboard(tenant_id):
    """Company super-admin view: overdue sections, approval speed, spend split."""
    conn = get_db()
    tenant_id = str(tenant_id)
    now = _utcnow()
    from datetime import timedelta

    overdue_sections = []
    try:
        cutoff = (now - timedelta(hours=72)).isoformat()
        rows = conn.execute(
            '''SELECT sv.id, sv.draft_id, sv.section_key, sv.version_number, sv.created_at,
                      pd.title AS draft_title
               FROM section_versions sv LEFT JOIN project_drafts pd ON pd.id = sv.draft_id
               WHERE sv.tenant_id = ? AND sv.status = 'pending' AND sv.created_at < ?
               ORDER BY sv.created_at LIMIT 50''',
            (tenant_id, cutoff),
        ).fetchall()
        overdue_sections = [dict(r) for r in rows]
    except Exception:
        overdue_sections = []

    avg_approval_hours = None
    try:
        rows = conn.execute(
            '''SELECT created_at, decided_at FROM section_versions
               WHERE tenant_id = ? AND decided_at IS NOT NULL
               ORDER BY decided_at DESC LIMIT 200''',
            (tenant_id,),
        ).fetchall()
        total = 0.0
        counted = 0
        for row in rows:
            try:
                total += (datetime.fromisoformat(row['decided_at'])
                          - datetime.fromisoformat(row['created_at'])).total_seconds()
                counted += 1
            except (TypeError, ValueError):
                continue
        if counted:
            avg_approval_hours = round(total / counted / 3600, 1)
    except Exception:
        pass

    spend_by_project = []
    try:
        rows = conn.execute(
            '''SELECT COALESCE(draft_id, presentation_id) AS ref, COALESCE(SUM(cost_usd), 0) AS total
               FROM ai_usage_events WHERE tenant_id = ?
               GROUP BY ref ORDER BY total DESC LIMIT 20''',
            (tenant_id,),
        ).fetchall()
        titles = {}
        for row in conn.execute(
            'SELECT id, title FROM project_drafts WHERE tenant_id = ?', (tenant_id,),
        ).fetchall():
            titles[row['id']] = row['title']
        for row in conn.execute(
            'SELECT id, title FROM presentations WHERE tenant_id = ?', (tenant_id,),
        ).fetchall():
            titles[row['id']] = row['title']
        for row in rows:
            spend_by_project.append({
                'ref': row['ref'],
                'title': titles.get(row['ref']) or row['ref'],
                'total_usd': round(float(row['total'] or 0), 4),
            })
    except Exception:
        spend_by_project = []

    spend_by_user = []
    try:
        rows = conn.execute(
            '''SELECT user_name, COUNT(*) AS events FROM audit_events
               WHERE tenant_id = ? AND user_name IS NOT NULL
               GROUP BY user_name ORDER BY events DESC LIMIT 20''',
            (tenant_id,),
        ).fetchall()
        spend_by_user = [{'user_name': r['user_name'], 'events': int(r['events'] or 0)}
                         for r in rows]
    except Exception:
        spend_by_user = []

    pending_approvals = 0
    try:
        pending_approvals = int(conn.execute(
            "SELECT COUNT(*) AS n FROM section_versions WHERE tenant_id = ? AND status = 'pending'",
            (tenant_id,),
        ).fetchone()['n'] or 0)
    except Exception:
        pass

    return with_sar_fields({
        'overdue_sections': overdue_sections,
        'overdue_count': len(overdue_sections),
        'avg_approval_hours': avg_approval_hours,
        'pending_section_approvals': pending_approvals,
        'spend_by_project': spend_by_project,
        'activity_by_user': spend_by_user,
    })


def ledger_report_rows(tenant_id=None, from_date=None, to_date=None, kind=None, limit=5000):
    """Points-ledger report rows: every wallet movement (t32/t55)."""
    conn = get_db()
    clauses = []
    params = []
    if tenant_id:
        clauses.append('l.tenant_id = ?')
        params.append(str(tenant_id))
    if kind:
        clauses.append('l.kind = ?')
        params.append(str(kind))
    if from_date:
        clauses.append('l.created_at >= ?')
        params.append(_norm_range_bound(from_date))
    if to_date:
        clauses.append('l.created_at <= ?')
        params.append(_norm_range_bound(to_date, is_end=True))
    query = ('SELECT l.*, t.company_name FROM tenant_ledger l '
             'LEFT JOIN tenants t ON t.id = l.tenant_id')
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY l.created_at DESC LIMIT ?'
    params.append(int(limit))
    rows = conn.execute(query, params).fetchall()
    headers = ['التاريخ', 'الشركة', 'النوع', 'المبلغ (ريال)', 'التكلفة الخام (ريال)', 'المضاعف',
               'أحداث AI', 'أحداث الخرائط', 'مرجع عدم التكرار', 'ملاحظة']
    body = [[r['created_at'], r['company_name'], r['kind'], usd_to_sar(r['amount_usd']),
             usd_to_sar(r['raw_cost_usd']), r['multiplier'], r['ai_events_count'],
             r['maps_events_count'], r['idempotency_key'], r['note']] for r in rows]
    return headers, body


def tickets_report_rows(tenant_id=None, from_date=None, to_date=None, limit=5000):
    """Support tickets report rows."""
    conn = get_db()
    clauses = []
    params = []
    if tenant_id:
        clauses.append('t.tenant_id = ?')
        params.append(str(tenant_id))
    if from_date:
        clauses.append('t.created_at >= ?')
        params.append(_norm_range_bound(from_date))
    if to_date:
        clauses.append('t.created_at <= ?')
        params.append(_norm_range_bound(to_date, is_end=True))
    query = ('SELECT t.*, tn.company_name FROM support_tickets t '
             'LEFT JOIN tenants tn ON tn.id = t.tenant_id')
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY t.created_at DESC LIMIT ?'
    params.append(int(limit))
    rows = conn.execute(query, params).fetchall()
    headers = ['الرقم', 'الشركة', 'العنوان', 'الفئة', 'الأولوية', 'الحالة', 'المنشئ',
               'أول استجابة', 'أنشئت', 'حُلّت', 'أُغلقت']
    body = [[r['number'], r['company_name'], r['subject'], r['category'], r['priority'],
             r['status'], r['created_by_name'], r['first_response_at'],
             r['created_at'], r['resolved_at'], r['closed_at']]
            for r in rows]
    return headers, body
