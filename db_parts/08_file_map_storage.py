

# ─────────────────────────────────────────────────────────────────────────────
# Project File Storage
# ─────────────────────────────────────────────────────────────────────────────

def create_project_file(tenant_id, file_type, original_name, storage_path, mime_type, file_size, sha256,
                        draft_id=None, project_id=None):
    conn = get_db()
    file_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO project_files
           (id, tenant_id, draft_id, project_id, file_type, original_name, storage_path,
            mime_type, file_size, sha256)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (file_id, tenant_id, draft_id, project_id, file_type, original_name, storage_path,
         mime_type, int(file_size or 0), sha256)
    )
    conn.commit()
    return file_id


def get_project_file(tenant_id, file_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_files WHERE id = ? AND tenant_id = ?',
        (file_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


def get_project_file_by_id(file_id):
    """Cross-tenant lookup, used only behind a super-admin check."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_files WHERE id = ?',
        (file_id,)
    ).fetchone()
    return dict(row) if row else None


def delete_project_file(tenant_id, file_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_files WHERE id = ? AND tenant_id = ?',
        (file_id, tenant_id)
    ).fetchone()
    if not row:
        return None
    conn.execute(
        'DELETE FROM project_files WHERE id = ? AND tenant_id = ?',
        (file_id, tenant_id)
    )
    conn.commit()
    return dict(row)


def get_project_files(tenant_id, draft_id=None, project_id=None, file_type=None):
    conn = get_db()
    query = 'SELECT * FROM project_files WHERE tenant_id = ?'
    params = [tenant_id]
    if draft_id:
        query += ' AND draft_id = ?'
        params.append(draft_id)
    if project_id:
        query += ' AND project_id = ?'
        params.append(project_id)
    if file_type:
        query += ' AND file_type = ?'
        params.append(file_type)
    query += ' ORDER BY created_at DESC, rowid DESC'
    return [dict(row) for row in conn.execute(query, params).fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Map Images Storage
# ─────────────────────────────────────────────────────────────────────────────

def add_map_image(tenant_id, image_type, file_path, placeholder, presentation_id=None, metadata=None):
    """Store a reference to a generated map image."""
    conn = get_db()
    image_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO map_images
           (id, tenant_id, presentation_id, image_type, file_path, placeholder, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (image_id, tenant_id, presentation_id, image_type, file_path, placeholder,
         json.dumps(metadata, ensure_ascii=False) if metadata else None)
    )
    conn.commit()
    return image_id


def update_map_image(image_id, tenant_id, file_path, placeholder, metadata=None):
    conn = get_db()
    conn.execute(
        '''UPDATE map_images SET file_path = ?, placeholder = ?, metadata_json = ?
           WHERE id = ? AND tenant_id = ?''',
        (file_path, placeholder, json.dumps(metadata, ensure_ascii=False) if metadata else None,
         image_id, tenant_id)
    )
    conn.commit()


def get_map_images(tenant_id, presentation_id=None, draft_id=None, image_type=None):
    """Get map images for a tenant, optionally filtered by presentation, draft, and type."""
    conn = get_db()
    query = 'SELECT * FROM map_images WHERE tenant_id = ?'
    params = [tenant_id]
    if presentation_id:
        query += ' AND presentation_id = ?'
        params.append(presentation_id)
    elif draft_id:
        query += ' AND presentation_id = ?'
        params.append(f"draft_{draft_id}")
    if image_type:
        query += ' AND image_type = ?'
        params.append(image_type)
    query += ' ORDER BY created_at DESC, rowid DESC'
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def delete_map_images(tenant_id, presentation_id=None, image_type=None):
    """Delete map image records for a tenant (does not delete files)."""
    conn = get_db()
    query = 'DELETE FROM map_images WHERE tenant_id = ?'
    params = [tenant_id]
    if presentation_id:
        query += ' AND presentation_id = ?'
        params.append(presentation_id)
    if image_type:
        query += ' AND image_type = ?'
        params.append(image_type)
    conn.execute(query, params)
    conn.commit()


def get_usage_totals(tenant_id, draft_ids=(), presentation_ids=()):
    """Bulk spend per project and per presentation for list screens.

    A project total covers its own draft rows plus every presentation linked
    to it through presentations.draft_id. A presentation total covers only
    its own rows. AI and Maps costs are summed separately and combined.
    """
    draft_ids = [str(d) for d in (draft_ids or []) if d][:200]
    presentation_ids = [str(p) for p in (presentation_ids or []) if p][:200]

    def _zero():
        return {'cost_usd': 0.0, 'ai_cost_usd': 0.0, 'maps_cost_usd': 0.0, 'calls': 0, 'total_tokens': 0}

    projects = {d: _zero() for d in draft_ids}
    presentations = {p: _zero() for p in presentation_ids}
    if not draft_ids and not presentation_ids:
        return {'projects': projects, 'presentations': presentations}
    conn = get_db()

    pres_of_draft = {}
    if draft_ids:
        marks = ', '.join(['?'] * len(draft_ids))
        for row in conn.execute(
            'SELECT id, draft_id FROM presentations '
            f'WHERE tenant_id = ? AND draft_id IN ({marks})',
            [tenant_id] + draft_ids,
        ).fetchall():
            row = dict(row)
            if row.get('draft_id') and row.get('id'):
                pres_of_draft.setdefault(str(row['draft_id']), []).append(str(row['id']))

    all_pres = set(presentation_ids)
    for pres_list in pres_of_draft.values():
        all_pres.update(pres_list)

    if draft_ids:
        marks = ', '.join(['?'] * len(draft_ids))
        for row in conn.execute(
            'SELECT draft_id, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost, '
            'COALESCE(SUM(total_tokens), 0) AS tokens '
            'FROM ai_usage_events WHERE tenant_id = ? AND draft_id IN '
            f'({marks}) AND presentation_id IS NULL GROUP BY draft_id',
            [tenant_id] + draft_ids,
        ).fetchall():
            row = dict(row)
            target = projects.get(str(row.get('draft_id')))
            if target is not None:
                target['calls'] += int(row['calls'] or 0)
                target['ai_cost_usd'] += float(row['cost'] or 0.0)
                target['total_tokens'] += int(row['tokens'] or 0)
        for row in conn.execute(
            'SELECT draft_id, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost '
            'FROM map_usage_events WHERE tenant_id = ? AND draft_id IN '
            f'({marks}) AND presentation_id IS NULL GROUP BY draft_id',
            [tenant_id] + draft_ids,
        ).fetchall():
            row = dict(row)
            target = projects.get(str(row.get('draft_id')))
            if target is not None:
                target['calls'] += int(row['calls'] or 0)
                target['maps_cost_usd'] += float(row['cost'] or 0.0)

    if all_pres:
        pres_list = sorted(all_pres)
        marks = ', '.join(['?'] * len(pres_list))
        for row in conn.execute(
            'SELECT presentation_id, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost, '
            'COALESCE(SUM(total_tokens), 0) AS tokens '
            'FROM ai_usage_events WHERE tenant_id = ? AND presentation_id IN '
            f'({marks}) GROUP BY presentation_id',
            [tenant_id] + pres_list,
        ).fetchall():
            row = dict(row)
            pres_id = str(row.get('presentation_id'))
            calls = int(row['calls'] or 0)
            cost = float(row['cost'] or 0.0)
            tokens = int(row['tokens'] or 0)
            if pres_id in presentations:
                presentations[pres_id]['calls'] += calls
                presentations[pres_id]['ai_cost_usd'] += cost
                presentations[pres_id]['total_tokens'] += tokens
            for draft_id, linked in pres_of_draft.items():
                if pres_id in linked:
                    projects[draft_id]['calls'] += calls
                    projects[draft_id]['ai_cost_usd'] += cost
                    projects[draft_id]['total_tokens'] += tokens
        marks = ', '.join(['?'] * len(pres_list))
        for row in conn.execute(
            'SELECT presentation_id, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost '
            f'FROM map_usage_events WHERE tenant_id = ? AND presentation_id IN ({marks}) GROUP BY presentation_id',
            [tenant_id] + pres_list,
        ).fetchall():
            row = dict(row)
            pres_id = str(row.get('presentation_id'))
            calls = int(row['calls'] or 0)
            cost = float(row['cost'] or 0.0)
            if pres_id in presentations:
                presentations[pres_id]['calls'] += calls
                presentations[pres_id]['maps_cost_usd'] += cost
            for draft_id, linked in pres_of_draft.items():
                if pres_id in linked:
                    projects[draft_id]['calls'] += calls
                    projects[draft_id]['maps_cost_usd'] += cost

    for entry in list(projects.values()) + list(presentations.values()):
        entry['cost_usd'] = entry['ai_cost_usd'] + entry['maps_cost_usd']
    return with_sar_fields({'projects': projects, 'presentations': presentations})


def link_draft_usage_to_presentation(tenant_id, draft_id, presentation_id):
    """Attribute unattributed draft spend to a newly saved presentation.

    Slide generation runs before the presentation exists, so its rows carry
    the draft id but no presentation id. Linking them at save time is what
    puts a cost on the presentation row. Rows already linked to an earlier
    presentation are never stolen: only unattributed rows move.
    """
    if not tenant_id or not draft_id or not presentation_id:
        return 0
    conn = get_db()
    linked = 0
    for table in ('ai_usage_events', 'map_usage_events'):
        cursor = conn.execute(
            f'UPDATE {table} SET presentation_id = ? '
            'WHERE tenant_id = ? AND draft_id = ? AND presentation_id IS NULL',
            (str(presentation_id), tenant_id, str(draft_id)),
        )
        linked += cursor.rowcount or 0
    conn.commit()
    return linked


def get_ai_reconcile_by_scope(tenant_id, draft_ids=(), presentation_ids=()):
    """Uncapped pending and unresolved counts per project and presentation.

    Used so list screens never show a capped number as a complete total.
    Tenant isolation is enforced and Maps grouping is untouched.
    """
    draft_ids = [str(d) for d in (draft_ids or []) if d][:200]
    presentation_ids = [str(p) for p in (presentation_ids or []) if p][:200]
    by_draft = {d: {'pending': 0, 'unresolved': 0, 'needs_review': 0, 'in_flight': 0,
                    'state': 'settled', 'state_label': 'التكلفة المسجلة'} for d in draft_ids}
    by_presentation = {p: {'pending': 0, 'unresolved': 0, 'needs_review': 0, 'in_flight': 0,
                           'state': 'settled', 'state_label': 'التكلفة المسجلة'} for p in presentation_ids}
    if not draft_ids and not presentation_ids:
        return {'by_draft': by_draft, 'by_presentation': by_presentation}
    conn = get_db()
    cols = _ai_usage_columns(conn)

    def _state_for(entry):
        if entry.get('in_flight') or entry.get('pending'):
            return 'pending', 'قيد الاستكمال'
        if entry.get('unresolved') or entry.get('needs_review'):
            return 'needs_review', 'تحتاج مطابقة'
        return 'settled', 'التكلفة المسجلة'

    def _status_expr():
        if 'attempt_status' in cols:
            return ("COALESCE(attempt_status, CASE WHEN cost_usd IS NOT NULL THEN 'settled' "
                    "WHEN generation_id IS NOT NULL THEN 'pending' ELSE 'unresolved' END)")
        return ("CASE WHEN cost_usd IS NOT NULL THEN 'settled' "
                "WHEN generation_id IS NOT NULL THEN 'pending' ELSE 'unresolved' END")
    expr = _status_expr()
    if draft_ids:
        marks = ', '.join(['?'] * len(draft_ids))
        for row in conn.execute(
            f'SELECT draft_id, {expr} AS st, COUNT(*) AS n FROM ai_usage_events '
            f'WHERE tenant_id = ? AND draft_id IN ({marks}) GROUP BY draft_id, st',
            [tenant_id] + draft_ids,
        ).fetchall():
            row = dict(row)
            target = by_draft.get(str(row.get('draft_id')))
            if target is None:
                continue
            key = str(row.get('st') or '')
            if key == 'pending':
                target['pending'] += int(row.get('n') or 0)
            elif key == 'unresolved':
                target['unresolved'] += int(row.get('n') or 0)
            elif key == 'needs_review':
                target['needs_review'] += int(row.get('n') or 0)
            elif key == 'in_flight':
                target['in_flight'] += int(row.get('n') or 0)
    if presentation_ids:
        marks = ', '.join(['?'] * len(presentation_ids))
        for row in conn.execute(
            f'SELECT presentation_id, {expr} AS st, COUNT(*) AS n FROM ai_usage_events '
            f'WHERE tenant_id = ? AND presentation_id IN ({marks}) GROUP BY presentation_id, st',
            [tenant_id] + presentation_ids,
        ).fetchall():
            row = dict(row)
            target = by_presentation.get(str(row.get('presentation_id')))
            if target is None:
                continue
            key = str(row.get('st') or '')
            if key == 'pending':
                target['pending'] += int(row.get('n') or 0)
            elif key == 'unresolved':
                target['unresolved'] += int(row.get('n') or 0)
            elif key == 'needs_review':
                target['needs_review'] += int(row.get('n') or 0)
            elif key == 'in_flight':
                target['in_flight'] += int(row.get('n') or 0)
    for entry in list(by_draft.values()) + list(by_presentation.values()):
        state, label = _state_for(entry)
        entry['state'] = state
        entry['state_label'] = label
    return {'by_draft': by_draft, 'by_presentation': by_presentation}

# ═════════════════════════════════════════════════════════════════════════════
# Omran platform tasks (t14-t63): generation approvals, final approvals,
# downloads, proposal copies, notification tasks, invites, users report,
# approval tasks, points reservations, recharge requests, support tickets,
# and the file-type registry. Money stays USD in tenant_ledger;
# these tables track workflow state, not money.
# ═════════════════════════════════════════════════════════════════════════════

GENERATION_APPROVAL_STATUSES = ('pending', 'approved', 'rejected', 'cancelled', 'consumed')
# t40: the seven-state support board — 'reopened' is a real state so a
# regression never masquerades as a fresh ticket.
SUPPORT_TICKET_STATUSES = ('open', 'in_progress', 'waiting_customer', 'escalated',
                         'resolved', 'reopened', 'closed')
SUPPORT_TICKET_CATEGORIES = ('general', 'billing', 'technical', 'generation',
                           'files', 'account', 'other')
SUPPORT_TICKET_PRIORITIES = ('low', 'normal', 'high', 'urgent')
RECHARGE_REQUEST_STATUSES = ('pending', 'approved', 'rejected')


def _create_omran_tables(conn):
    """Tables added by the Omran platform tasks. Every statement is IF NOT EXISTS."""
    # t14: one explicit approval to start generation, carrying the cost
    # estimate and the reserved points the job will consume.
    conn.execute('''CREATE TABLE IF NOT EXISTS generation_approvals (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        draft_id TEXT,
        presentation_id TEXT,
        estimated_cost_usd REAL NOT NULL DEFAULT 0,
        estimated_points INTEGER NOT NULL DEFAULT 0,
        slides_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by TEXT,
        requested_by_name TEXT,
        requested_at TEXT DEFAULT (datetime('now')),
        decided_by TEXT,
        decided_by_name TEXT,
        decided_at TEXT,
        decision_note TEXT,
        job_id TEXT,
        prior_status TEXT,
        section_key TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_approvals_tenant ON generation_approvals(tenant_id, status, requested_at DESC)')

    # t15: the final-file approval locks one presentation revision and stamps
    # it; the downloads library records every generated or downloaded file.
    conn.execute('''CREATE TABLE IF NOT EXISTS final_file_approvals (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        presentation_id TEXT NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by TEXT,
        requested_by_name TEXT,
        requested_at TEXT DEFAULT (datetime('now')),
        decided_by TEXT,
        decided_by_name TEXT,
        decided_at TEXT,
        decision_note TEXT,
        content_hash TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_final_approvals_tenant ON final_file_approvals(tenant_id, presentation_id, status)')

    conn.execute('''CREATE TABLE IF NOT EXISTS presentation_downloads (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        presentation_id TEXT,
        draft_id TEXT,
        file_name TEXT NOT NULL,
        format TEXT NOT NULL DEFAULT 'pdf',
        version_label TEXT,
        approval_status TEXT NOT NULL DEFAULT 'pending',
        generated_by TEXT,
        generated_by_name TEXT,
        approved_by_name TEXT,
        generated_at TEXT DEFAULT (datetime('now')),
        downloaded_at TEXT,
        downloaded_by_name TEXT,
        file_size INTEGER DEFAULT 0
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_downloads_tenant ON presentation_downloads(tenant_id, generated_at DESC)')

    # t17/t18: a copy is an independent proposal; archiving never deletes.
    conn.execute('''CREATE TABLE IF NOT EXISTS proposal_copies (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        source_draft_id TEXT NOT NULL,
        new_draft_id TEXT NOT NULL,
        new_title TEXT NOT NULL,
        copied_by TEXT,
        copied_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_proposal_copies_tenant ON proposal_copies(tenant_id, created_at DESC)')

    # t41: in-app notification feed; every row is user- or tenant-scoped and
    # carries the exact payload a screen needs to render the event.
    conn.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT,
        category TEXT NOT NULL DEFAULT 'general',
        title TEXT NOT NULL,
        body TEXT,
        entity_type TEXT,
        entity_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        read_at TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_notifications_feed ON notifications(tenant_id, user_id, created_at DESC)')

    # t24/t42: tasks that stay open until the approver or editor acts.
    conn.execute('''CREATE TABLE IF NOT EXISTS approval_tasks (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'section_approval',
        title TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        section_key TEXT,
        assignee_id TEXT,
        assignee_name TEXT,
        payload TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        opened_at TEXT DEFAULT (datetime('now')),
        due_at TEXT,
        reminded_at TEXT,
        escalated_at TEXT,
        closed_at TEXT,
        closed_by_name TEXT,
        cancel_reason TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_approval_tasks_feed ON approval_tasks(tenant_id, status, opened_at DESC)')

    # t30/t31: atomic reservations, one active per operation, consumed once.
    conn.execute('''CREATE TABLE IF NOT EXISTS point_reservations (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        generation_approval_id TEXT,
        draft_id TEXT,
        points INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'reserved',
        reserved_by TEXT,
        reserved_by_name TEXT,
        reserved_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT,
        settled_at TEXT,
        settled_by TEXT,
        note TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_point_reservations_tenant ON point_reservations(tenant_id, status)')
    # One live hold per approval operation: a retried or double-fired reserve
    # finds the existing row instead of holding the same balance twice.
    conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_point_reservations_active_op
                    ON point_reservations(generation_approval_id) WHERE status = 'reserved' ''')

    # t32/t33: client recharge (package purchase) requests reviewed by the
    # super-admin within 24 hours; the approved request mints a reference
    # number and the ledger credit stays in record_ledger_credit.
    conn.execute('''CREATE TABLE IF NOT EXISTS recharge_requests (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        package_id TEXT,
        package_name TEXT NOT NULL,
        amount_usd REAL NOT NULL DEFAULT 0,
        price_sar REAL,
        transfer_reference TEXT,
        receipt_file_id TEXT,
        requested_by TEXT,
        requested_by_name TEXT,
        requested_at TEXT DEFAULT (datetime('now')),
        reviewed_by TEXT,
        reviewed_by_name TEXT,
        reviewed_at TEXT,
        decision_note TEXT,
        reference_number TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_recharge_requests_tenant ON recharge_requests(tenant_id, status, requested_at DESC)')

    # t40: support tickets with statuses, categories and one linear comment
    # thread per ticket.
    conn.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        number INTEGER,
        subject TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'general',
        priority TEXT NOT NULL DEFAULT 'normal',
        status TEXT NOT NULL DEFAULT 'open',
        created_by TEXT,
        created_by_name TEXT,
        assigned_to TEXT,
        first_response_at TEXT,
        resolved_at TEXT,
        closed_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_support_tickets_tenant ON support_tickets(tenant_id, status, updated_at DESC)')

    conn.execute('''CREATE TABLE IF NOT EXISTS support_ticket_messages (
        id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        author_id TEXT,
        author_name TEXT NOT NULL,
        author_role TEXT NOT NULL DEFAULT 'customer',
        body TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_ticket_messages(ticket_id, created_at)')

    # t62: versioned registry of allowed file types and their limits.
    conn.execute('''CREATE TABLE IF NOT EXISTS file_type_registry (
        key TEXT PRIMARY KEY,
        label_ar TEXT NOT NULL,
        label_en TEXT,
        kind TEXT NOT NULL DEFAULT 'document',
        max_size_mb INTEGER NOT NULL DEFAULT 25,
        allowed_extensions TEXT NOT NULL DEFAULT '[]',
        version INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT DEFAULT (datetime('now'))
    )''')


def _ensure_omran_columns(conn):
    """Additive migrations on existing installs: last_login on users/tenants."""
    def _columns(table):
        return {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}

    def _add(table, column, ddl):
        try:
            if column not in _columns(table):
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {ddl}')
        except Exception:
            pass

    _add('users', 'last_login_at', 'last_login_at TEXT')
    _add('tenants', 'last_login_at', 'last_login_at TEXT')

    # t21: an invite carries the pre-assigned identity and scope, plus the
    # delivery state of its email so a failed send can be retried.
    _add('invite_links', 'name', 'name TEXT')
    _add('invite_links', 'phone', 'phone TEXT')
    _add('invite_links', 'role', "role TEXT DEFAULT 'employee'")
    _add('invite_links', 'sections_json', 'sections_json TEXT')
    _add('invite_links', 'projects_json', 'projects_json TEXT')
    _add('invite_links', 'email_status', "email_status TEXT DEFAULT 'pending'")
    _add('invite_links', 'email_error', 'email_error TEXT')
    _add('invite_links', 'email_attempts', 'email_attempts INTEGER DEFAULT 0')
    _add('invite_links', 'email_sent_at', 'email_sent_at TEXT')

    # t23: ledger movements name the actor class so the duties matrix can flag
    # a credit that did not come from the platform-admin recharge path.
    _add('tenant_ledger', 'actor', 'actor TEXT')
    # t32: a refund/correction/expiry movement links back to the entry it reverses.
    _add('tenant_ledger', 'reversal_of', 'TEXT')

    # Event tasks got the reminder clock approval tasks always had.
    _add('event_tasks', 'reminded_at', 'reminded_at TEXT')


# ═════════════════════════════════════════════════════════════════════════════
# Mission-5 graph completion (t50/t51/t54/t60/t61/t62/t63): every statement is
# IF NOT EXISTS so the schema lands on existing installs the same as new ones.
# ═════════════════════════════════════════════════════════════════════════════

TENANT_COMPANY_PROFILE_FIELDS = (
    'legal_name', 'commercial_name', 'tax_number', 'cr_number',
    'country', 'region', 'address', 'contact_title',
)

def _create_platform_tables(conn):
    """Graph-model completion tables (t60) plus the mission-5 subsystem tables."""
    # t60-01: every notification fans out to per-channel delivery rows so the
    # platform can report sent / delivered / failed and retry counts per event.
    conn.execute('''CREATE TABLE IF NOT EXISTS notification_deliveries (
        id TEXT PRIMARY KEY,
        notification_id TEXT NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        channel TEXT NOT NULL DEFAULT 'in_app',
        status TEXT NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        last_attempt_at TEXT,
        sent_at TEXT,
        delivered_at TEXT,
        read_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_notif_deliveries_notification ON notification_deliveries(notification_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_notif_deliveries_tenant ON notification_deliveries(tenant_id, status, created_at DESC)')

    # Per-actor category switches: one row per (tenant, user_key, category).
    # user_key is the user id for staff logins or 'tenant-admin:<tenant_id>'
    # for the direct company login — the same address list_notifications
    # filters by, so a muted category hides broadcast and addressed rows alike.
    conn.execute('''CREATE TABLE IF NOT EXISTS notification_preferences (
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_key TEXT NOT NULL,
        category TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT,
        PRIMARY KEY (tenant_id, user_key, category)
    )''')

    # t60-02: ticket attachments point at stored files.
    conn.execute('''CREATE TABLE IF NOT EXISTS support_ticket_attachments (
        id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
        message_id TEXT REFERENCES support_ticket_messages(id) ON DELETE SET NULL,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        file_id TEXT NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_ticket_attachments ON support_ticket_attachments(ticket_id)')

    # t60-04: subscriptions tie a tenant to an immutable package version with a
    # real validity window; topup receipts are the financial documents of a
    # recharge decision.
    conn.execute('''CREATE TABLE IF NOT EXISTS billing_package_versions (
        id TEXT PRIMARY KEY,
        package_id TEXT NOT NULL REFERENCES billing_packages(id) ON DELETE CASCADE,
        version INTEGER NOT NULL DEFAULT 1,
        name TEXT NOT NULL,
        credit_usd REAL NOT NULL DEFAULT 0,
        price_sar REAL,
        duration_days INTEGER,
        limits_json TEXT,
        features_json TEXT,
        valid_from TEXT DEFAULT (datetime('now')),
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_package_version ON billing_package_versions(package_id, version)')

    conn.execute('''CREATE TABLE IF NOT EXISTS tenant_subscriptions (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        package_id TEXT REFERENCES billing_packages(id) ON DELETE SET NULL,
        package_version_id TEXT REFERENCES billing_package_versions(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'active',
        starts_at TEXT,
        ends_at TEXT,
        trial_ends_at TEXT,
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON tenant_subscriptions(tenant_id, status, ends_at)')

    conn.execute('''CREATE TABLE IF NOT EXISTS topup_receipts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        recharge_request_id TEXT REFERENCES recharge_requests(id) ON DELETE SET NULL,
        receipt_file_id TEXT REFERENCES project_files(id) ON DELETE SET NULL,
        receipt_sha256 TEXT,
        transfer_reference TEXT,
        invoice_number TEXT,
        amount_usd REAL NOT NULL DEFAULT 0,
        price_sar REAL,
        status TEXT NOT NULL DEFAULT 'issued',
        issued_by TEXT,
        issued_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_topup_receipts_request ON topup_receipts(recharge_request_id) WHERE recharge_request_id IS NOT NULL')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_topup_receipts_invoice ON topup_receipts(invoice_number) WHERE invoice_number IS NOT NULL')

    # t60-05: one job row per generation run, linked to the approval, the model
    # and template versions, the input snapshot and the final cost or error.
    conn.execute('''CREATE TABLE IF NOT EXISTS generation_jobs (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        approval_id TEXT REFERENCES generation_approvals(id) ON DELETE SET NULL,
        draft_id TEXT,
        presentation_id TEXT,
        status TEXT NOT NULL DEFAULT 'queued',
        progress INTEGER NOT NULL DEFAULT 0,
        model TEXT,
        template_version TEXT,
        schema_version TEXT,
        input_snapshot_json TEXT,
        estimated_cost_usd REAL,
        actual_cost_usd REAL,
        slides_total INTEGER,
        slides_done INTEGER,
        error TEXT,
        correlation_id TEXT,
        idempotency_key TEXT,
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        started_at TEXT,
        finished_at TEXT
    )''')
    # Idempotent replay is scoped to the (tenant, approval) pair that owns the
    # request: the old global index let one company's key return — or block —
    # another company's job.
    try:
        conn.execute('DROP INDEX IF EXISTS ux_generation_jobs_idem')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_generation_jobs_tenant_idem ON generation_jobs(tenant_id, COALESCE(approval_id, ''), idempotency_key) WHERE idempotency_key IS NOT NULL")
    except Exception as exc:
        print(f'[DB] unique index skipped (ux_generation_jobs_tenant_idem): {exc}')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_jobs_tenant ON generation_jobs(tenant_id, status, created_at DESC)')

    # t60-05: document versions for every produced file, tied to the approval
    # and the content hash that was stamped.
    conn.execute('''CREATE TABLE IF NOT EXISTS document_versions (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        document_type TEXT NOT NULL,
        document_id TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        file_id TEXT,
        content_hash TEXT,
        approval_id TEXT,
        generated_by TEXT,
        generated_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_document_versions ON document_versions(tenant_id, document_type, document_id, version)')

    # t51: old slugs keep resolving forever once a company is active.
    conn.execute('''CREATE TABLE IF NOT EXISTS tenant_slug_redirects (
        old_slug TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        new_slug TEXT NOT NULL,
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # t62: versioned study-type registry. definition_json carries the sections,
    # fields, validation rules, approval sequence and pricing hints for the
    # whole study kind.
    conn.execute('''CREATE TABLE IF NOT EXISTS study_types (
        id TEXT PRIMARY KEY,
        key TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        name_ar TEXT NOT NULL,
        name_en TEXT,
        definition_json TEXT NOT NULL DEFAULT '{}',
        supersedes_version INTEGER,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_study_types ON study_types(key, version)')

    # t62: generator registry — the pluggable file generators, processors,
    # output models and PDF templates, each versioned separately.
    conn.execute('''CREATE TABLE IF NOT EXISTS generator_registry (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        key TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        label_ar TEXT,
        label_en TEXT,
        config_json TEXT NOT NULL DEFAULT '{}',
        supersedes_version INTEGER,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_generator_registry ON generator_registry(kind, key, version)')

    # t62: versioned input-schema snapshots; drafts record which schema version
    # they were captured against.
    conn.execute('''CREATE TABLE IF NOT EXISTS field_schema_versions (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        version INTEGER NOT NULL DEFAULT 1,
        schema_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_field_schema_versions ON field_schema_versions(tenant_id, version)')

    # t61: a persistent job queue so background work survives a process
    # restart instead of living on in-process threads.
    conn.execute('''CREATE TABLE IF NOT EXISTS job_queue (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        job_type TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'queued',
        priority INTEGER NOT NULL DEFAULT 100,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        run_after TEXT,
        locked_by TEXT,
        locked_at TEXT,
        last_error TEXT,
        correlation_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        started_at TEXT,
        finished_at TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_job_queue_poll ON job_queue(status, run_after, priority, created_at)')

    # t61/t41: outbound mail is queued, never sent inline; the worker table
    # keeps every attempt, the error and the final state per message.
    conn.execute('''CREATE TABLE IF NOT EXISTS email_outbox (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        notification_id TEXT,
        to_email TEXT NOT NULL,
        subject TEXT NOT NULL,
        body_text TEXT,
        body_html TEXT,
        status TEXT NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        related_type TEXT,
        related_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        sent_at TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_email_outbox_status ON email_outbox(status, created_at)')

    # t63: every backup run is registered so RPO compliance is measurable.
    conn.execute('''CREATE TABLE IF NOT EXISTS backup_history (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL DEFAULT 'full',
        status TEXT NOT NULL DEFAULT 'running',
        path TEXT,
        size_bytes INTEGER,
        sha256 TEXT,
        encrypted INTEGER NOT NULL DEFAULT 0,
        restore_tested_at TEXT,
        note TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        completed_at TEXT
    )''')


def _platform_unique_indexes(conn):
    """t60-06: uniqueness enforced by the database, not by app-side checks.

    Each index is partial so existing NULL/blank rows never block creation;
    legacy duplicates only stop the index when the collision is real, in which
    case the failure is logged and visible instead of silently skipped.
    """
    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_tenants_slug ON tenants(slug) WHERE slug IS NOT NULL AND slug != ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_tenants_username ON tenants(LOWER(username)) WHERE username IS NOT NULL AND username != ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_recharge_transfer ON recharge_requests(transfer_reference) WHERE transfer_reference IS NOT NULL AND transfer_reference != ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_point_reservations_active ON point_reservations(generation_approval_id) WHERE status = 'reserved' AND generation_approval_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_approval_tasks_open ON approval_tasks(tenant_id, kind, COALESCE(entity_type,''), COALESCE(entity_id,'')) WHERE status = 'open' AND entity_id IS NOT NULL",
    )
    for sql in statements:
        try:
            conn.execute(sql)
        except Exception as exc:
            print(f'[DB] unique index skipped ({sql.split()[5]}): {exc}')


def _ensure_platform_columns(conn):
    """Additive columns on existing tables for the mission-5 scope."""
    def _columns(table):
        try:
            return {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        except Exception:
            return set()

    def _add(table, column, definition):
        if column not in _columns(table):
            try:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
                print(f'[DB] Migration: added {column} column to {table}')
            except Exception as exc:
                print(f'[DB] Migration notice: {table}.{column}: {exc}')

    # t50: legal profile + activation audit on tenants.
    for column in TENANT_COMPANY_PROFILE_FIELDS:
        _add('tenants', column, 'TEXT')
    for column in ('slug', 'activated_by', 'activated_by_name', 'activated_at',
                   'trial_ends_at', 'deactivated_reason'):
        _add('tenants', column, 'TEXT')
    try:
        conn.execute(
            'UPDATE tenants SET activated_at = COALESCE(created_at, ?) '
            'WHERE is_active = 1 AND activated_at IS NULL',
            (_utcnow().isoformat(),),
        )
        conn.commit()
    except Exception as exc:
        print(f'[DB] Migration notice: tenants.activated_at backfill: {exc}')

    # Contracts feature removed: drop the tables and its file-type rule on
    # existing installs so no dead schema or upload type survives.
    try:
        conn.execute('DROP TABLE IF EXISTS tenant_contract_versions')
        conn.execute('DROP TABLE IF EXISTS tenant_contracts')
        conn.execute("DELETE FROM file_type_registry WHERE key = 'contract_file'")
        conn.commit()
    except Exception as exc:
        print(f'[DB] Migration notice: contract tables drop: {exc}')

    # t60-02: tickets can hang off a project file/draft.
    _add('support_tickets', 'draft_id', 'TEXT')
    _add('support_tickets', 'project_id', 'TEXT')
    _add('support_tickets', 'reopened_count', 'INTEGER DEFAULT 0')

    # t42: event tasks link back to the object that raised them and carry a
    # priority so the board can escalate what matters first.
    for column, definition in (
            ('entity_type', 'TEXT'), ('entity_id', 'TEXT'),
            ('priority', "TEXT DEFAULT 'normal'"), ('escalated_at', 'TEXT')):
        _add('event_tasks', column, definition)

    # t24: the approver task center filters by project — pin the draft the task
    # belongs to instead of digging it back out of the payload JSON.
    _add('approval_tasks', 'draft_id', 'TEXT')
    try:
        for row in conn.execute(
                "SELECT id, payload FROM approval_tasks WHERE draft_id IS NULL").fetchall():
            try:
                payload = json.loads(row['payload'] or '{}')
            except Exception:
                payload = {}
            if payload.get('draft_id'):
                conn.execute('UPDATE approval_tasks SET draft_id = ? WHERE id = ?',
                             (payload['draft_id'], row['id']))
        conn.commit()
    except Exception as exc:
        print(f'[DB] Migration notice: approval_tasks.draft_id backfill: {exc}')

    # t60-04: a purchase request pins the package version it was priced from.
    _add('recharge_requests', 'package_version_id', 'TEXT')

    # d09: the financial document carries the VAT breakdown on the SAR price.
    _add('topup_receipts', 'tax_rate', 'REAL')
    _add('topup_receipts', 'tax_amount_sar', 'REAL')
    _add('topup_receipts', 'total_sar', 'REAL')
    # t33: one bank transfer may only ever back one request.
    try:
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS ux_recharge_transfer_ref
                        ON recharge_requests(transfer_reference)
                        WHERE transfer_reference IS NOT NULL AND transfer_reference != '' ''')
    except Exception as exc:
        print(f'[DB] Migration notice: recharge transfer-ref index: {exc}')

    # t63: uploads carry their scan verdict so a quarantined file is visible.
    _add('project_files', 'scan_status', "TEXT DEFAULT 'clean'")

    # t62: drafts record the input-schema version they were captured with.
    _add('project_drafts', 'schema_version', 'TEXT')


def _dedupe_open_workflow_rows(conn):
    """Collapse legacy duplicates so the unique workflow indexes can exist.

    Keeps the newest row per key and settles the rest; the unique indexes
    created afterwards then prove no second open row can appear.
    """
    try:
        conn.execute('''UPDATE point_reservations SET status = 'released', settled_at = datetime('now')
            WHERE status = 'reserved' AND generation_approval_id IS NOT NULL AND id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY generation_approval_id
                        ORDER BY reserved_at DESC, id DESC) AS rn
                    FROM point_reservations
                    WHERE status = 'reserved' AND generation_approval_id IS NOT NULL
                ) ranked WHERE rn > 1)''')
    except Exception as exc:
        print(f'[DB] point_reservations dedupe notice: {exc}')
    try:
        conn.execute('''UPDATE approval_tasks SET status = 'cancelled', closed_at = datetime('now'),
            cancel_reason = 'superseded_by_newer_open_task'
            WHERE status = 'open' AND entity_id IS NOT NULL AND id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY tenant_id, kind, COALESCE(entity_type, ''), entity_id
                        ORDER BY opened_at DESC, id DESC) AS rn
                    FROM approval_tasks
                    WHERE status = 'open' AND entity_id IS NOT NULL
                ) ranked WHERE rn > 1)''')
    except Exception as exc:
        print(f'[DB] approval_tasks dedupe notice: {exc}')


FILE_TYPE_REGISTRY_DEFAULTS = [
    {'key': 'deed_file', 'label_ar': 'صك الملكية', 'label_en': 'Ownership deed', 'kind': 'document',
     'max_size_mb': 25, 'allowed_extensions': ['.pdf', '.png', '.jpg', '.jpeg']},
    {'key': 'croquis_file', 'label_ar': 'الكروكي', 'label_en': 'Croquis survey', 'kind': 'document',
     'max_size_mb': 25, 'allowed_extensions': ['.pdf', '.png', '.jpg', '.jpeg']},
    {'key': 'land_documents_files', 'label_ar': 'رخصة البناء والكروكي', 'label_en': 'Building licence and croquis',
     'kind': 'document', 'max_size_mb': 40, 'allowed_extensions': ['.pdf']},
    {'key': 'land_photos', 'label_ar': 'صور الأرض', 'label_en': 'Land photos', 'kind': 'image',
     'max_size_mb': 10, 'allowed_extensions': ['.png', '.jpg', '.jpeg', '.webp']},
    {'key': 'project_logo', 'label_ar': 'شعار المشروع', 'label_en': 'Project logo', 'kind': 'image',
     'max_size_mb': 5, 'allowed_extensions': ['.png', '.jpg', '.jpeg', '.webp']},
    {'key': 'team_logo', 'label_ar': 'شعار الجهة', 'label_en': 'Team logo', 'kind': 'image',
     'max_size_mb': 5, 'allowed_extensions': ['.png', '.jpg', '.jpeg', '.webp']},
    {'key': 'competitor_logo', 'label_ar': 'شعار المنافس', 'label_en': 'Competitor logo', 'kind': 'image',
     'max_size_mb': 5, 'allowed_extensions': ['.png', '.jpg', '.jpeg', '.webp']},
    {'key': 'recharge_receipt', 'label_ar': 'إيصال تحويل شحن الرصيد', 'label_en': 'Recharge transfer receipt',
     'kind': 'document', 'max_size_mb': 15, 'allowed_extensions': ['.pdf', '.png', '.jpg', '.jpeg']},
]


def _seed_file_type_registry(conn):
    for item in FILE_TYPE_REGISTRY_DEFAULTS:
        conn.execute(
            '''INSERT INTO file_type_registry (key, label_ar, label_en, kind, max_size_mb, allowed_extensions, version)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(key) DO NOTHING''',
            (item['key'], item['label_ar'], item['label_en'], item['kind'],
             item['max_size_mb'], json.dumps(item['allowed_extensions'])),
        )


def _json_or(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed is not None else fallback


def record_login(tenant_id, user_id=None):
    """Stamp last_login_at on the tenant row or the user row after a login."""
    conn = get_db()
    now = _utcnow().isoformat()
    if user_id:
        conn.execute('UPDATE users SET last_login_at = ? WHERE id = ?', (now, user_id))
    else:
        conn.execute('UPDATE tenants SET last_login_at = ? WHERE id = ?', (now, tenant_id))
    conn.commit()
    return now


def tenant_users_report(tenant_id):
    """t22: active, invited, disabled users plus the newest invite links."""
    conn = get_db()
    users = []
    for row in conn.execute(
        'SELECT id, name, email, username, role, is_active, require_password_change, '
        'last_login_at, created_at FROM users WHERE tenant_id = ? ORDER BY created_at DESC',
        (tenant_id,),
    ).fetchall():
        users.append(dict(row))
    invites = []
    try:
        for row in conn.execute(
            'SELECT id, email, token, expires_at, used_at, name, role, email_status, '
            'email_error, email_attempts, email_sent_at FROM invite_links '
            'WHERE tenant_id = ? ORDER BY expires_at DESC LIMIT 25',
            (tenant_id,),
        ).fetchall():
            invite = dict(row)
            try:
                invite['is_expired'] = bool(invite['expires_at']) and datetime.fromisoformat(invite['expires_at']) < _utcnow()
            except (TypeError, ValueError):
                invite['is_expired'] = False
            invite['is_used'] = bool(invite.get('used_at'))
            invites.append(invite)
    except Exception:
        invites = []
    active = [u for u in users if u['is_active']]
    return {
        'users': users,
        'invites': invites,
        'counts': {
            'total': len(users),
            'active': len(active),
            'disabled': len(users) - len(active),
            'pending_invites': len([i for i in invites if not i['is_used'] and not i['is_expired']]),
        },
    }


def expire_stale_invites(tenant_id):
    """t21: invites past their expiry can no longer be accepted."""
    conn = get_db()
    now = _utcnow().isoformat()
    cursor = conn.execute(
        'UPDATE invite_links SET used_at = ? WHERE tenant_id = ? AND used_at IS NULL AND expires_at < ?',
        (now, tenant_id, now),
    )
    conn.commit()
    return cursor.rowcount


def get_file_type_registry(active_only=True):
    """t62: the versioned registry of allowed file types."""
    conn = get_db()
    query = ('SELECT key, label_ar, label_en, kind, max_size_mb, allowed_extensions, '
             'version, is_active, updated_at FROM file_type_registry')
    if active_only:
        query += ' WHERE is_active = 1'
    query += ' ORDER BY key'
    rows = conn.execute(query).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['allowed_extensions'] = _json_or(item.get('allowed_extensions'), [])
        result.append(item)
    return result


def upsert_file_type(key, label_ar, kind='document', max_size_mb=25,
                     allowed_extensions=None, label_en=None, is_active=True):
    """Create or evolve one registry entry; a content-affecting change bumps version."""
    if not key or not label_ar:
        return {'error': 'key_and_label_required'}
    conn = get_db()
    existing = conn.execute('SELECT * FROM file_type_registry WHERE key = ?', (key,)).fetchone()
    extensions_json = json.dumps(list(allowed_extensions or []))
    now = _utcnow().isoformat()
    if existing:
        changed = (
            existing['label_ar'] != label_ar or existing['kind'] != kind
            or int(existing['max_size_mb'] or 0) != int(max_size_mb)
            or existing['allowed_extensions'] != extensions_json
        )
        version = int(existing['version'] or 1) + (1 if changed else 0)
        conn.execute(
            '''UPDATE file_type_registry SET label_ar = ?, label_en = ?, kind = ?, max_size_mb = ?,
               allowed_extensions = ?, version = ?, is_active = ?, updated_at = ? WHERE key = ?''',
            (label_ar, label_en, kind, int(max_size_mb), extensions_json,
             version, 1 if is_active else 0, now, key),
        )
    else:
        conn.execute(
            '''INSERT INTO file_type_registry (key, label_ar, label_en, kind, max_size_mb, allowed_extensions, version, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)''',
            (key, label_ar, label_en, kind, int(max_size_mb), extensions_json,
             1 if is_active else 0, now),
        )
    conn.commit()
    row = conn.execute('SELECT * FROM file_type_registry WHERE key = ?', (key,)).fetchone()
    item = dict(row)
    item['allowed_extensions'] = _json_or(item.get('allowed_extensions'), [])
    return item
