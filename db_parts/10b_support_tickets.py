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
