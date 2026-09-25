


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Second schema wave: the Landloom workflow and platform tables
# with their status enums, follow-up column ensures, the open-workflow
# dedupe and the file-type registry seed. init_db() calls these after the
# base tables exist.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


GENERATION_APPROVAL_STATUSES = ('pending', 'approved', 'rejected', 'cancelled', 'consumed')
# t40: the seven-state support board — 'reopened' is a real state so a
# regression never masquerades as a fresh ticket.
SUPPORT_TICKET_STATUSES = ('open', 'in_progress', 'waiting_customer', 'escalated',
                         'resolved', 'reopened', 'closed')
SUPPORT_TICKET_CATEGORIES = ('general', 'billing', 'technical', 'generation',
                           'files', 'account', 'other')
SUPPORT_TICKET_PRIORITIES = ('low', 'normal', 'high', 'urgent')
RECHARGE_REQUEST_STATUSES = ('pending', 'approved', 'rejected')


def _create_landloom_tables(conn):
    """Tables added by the Landloom platform tasks. Every statement is IF NOT EXISTS."""
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
        cost_sar REAL,
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
        amount_sar REAL,
        price_sar REAL,
        transfer_reference TEXT,
        receipt_file_id TEXT,
        invoice_file_id TEXT,
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


def _ensure_landloom_columns(conn):
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
        credit_sar REAL,
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
        amount_sar REAL,
        price_sar REAL,
        invoice_file_id TEXT,
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
    # Wallet SAR denomination plus the platform-issued invoice upload.
    _add('topup_receipts', 'amount_sar', 'REAL')
    _add('topup_receipts', 'invoice_file_id', 'TEXT')
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

    # Wallet SAR denomination: the wallet and every package/ledger movement is
    # a riyal figure while the *_usd columns stay as the provider-cost audit.
    _add('tenant_ledger', 'amount_sar', 'REAL')
    _add('tenant_ledger', 'fx_rate', 'REAL')
    _add('billing_packages', 'credit_sar', 'REAL')
    _add('billing_package_versions', 'credit_sar', 'REAL')
    _add('tenant_package_history', 'credit_sar', 'REAL')
    _add('point_reservations', 'cost_sar', 'REAL')
    _add('recharge_requests', 'amount_sar', 'REAL')
    _add('recharge_requests', 'invoice_file_id', 'TEXT')
    # sag_admin_panel is a platform-session attribute, not a grantable company
    # permission — drop stale grant rows written before the guard existed.
    try:
        conn.execute("DELETE FROM user_permissions WHERE permission_key = 'sag_admin_panel'")
        conn.commit()
    except Exception as exc:
        print(f'[DB] Migration notice: sag_admin_panel grant cleanup: {exc}')
    _migrate_wallet_to_sar(conn)
    _round_sar_money_columns(conn)


def _migrate_wallet_to_sar(conn):
    """One-time conversion of wallet money columns from USD to SAR.

    Guarded by platform_settings.wallet_currency: installs that already ran it
    (or were born on the SAR schema) skip it. Existing USD figures convert at
    the stored exchange rate, and the whole pass commits as one transaction
    so a failure cannot leave half-converted balances.
    """
    try:
        flag = conn.execute(
            "SELECT value FROM platform_settings WHERE key = 'wallet_currency'").fetchone()
    except Exception:
        flag = None
    if flag and str(flag[0]) == 'sar':
        return
    try:
        rate = float((get_fx_rate() or {}).get('rate') or FX_DEFAULT_USD_SAR)
    except Exception:
        rate = FX_DEFAULT_USD_SAR
    if rate <= 0:
        rate = FX_DEFAULT_USD_SAR
    try:
        conn.execute('UPDATE tenants SET credit_balance = ROUND(COALESCE(credit_balance, 0) * ?, 2)', (rate,))
        conn.execute('UPDATE tenant_ledger SET amount_sar = ROUND(amount_usd * ?, 2) WHERE amount_sar IS NULL', (rate,))
        conn.execute('UPDATE billing_packages SET credit_sar = ROUND(credit_usd * ?, 2) WHERE credit_sar IS NULL', (rate,))
        conn.execute('UPDATE billing_package_versions SET credit_sar = ROUND(credit_usd * ?, 2) WHERE credit_sar IS NULL', (rate,))
        conn.execute('UPDATE tenant_package_history SET credit_sar = ROUND(credit_usd * ?, 2) WHERE credit_sar IS NULL', (rate,))
        conn.execute('UPDATE point_reservations SET cost_sar = ROUND(cost_usd * ?, 2) WHERE cost_sar IS NULL', (rate,))
        conn.execute('UPDATE recharge_requests SET amount_sar = ROUND(amount_usd * ?, 2) WHERE amount_sar IS NULL', (rate,))
        conn.execute(
            "INSERT INTO platform_settings (key, value, updated_at) VALUES ('wallet_currency', 'sar', datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = 'sar', updated_at = datetime('now')")
        conn.commit()
    except Exception as exc:
        print(f'[DB] Migration notice: wallet SAR conversion: {exc}')


def _round_sar_money_columns(conn):
    """Snap every stored SAR money figure to the halala.

    The wallet migration and a few write paths once stored raw float products
    (``credit_usd * rate``), which baked sub-halala noise like 499.9875 into
    catalog and ledger rows. Idempotent: rows already at 2dp fail the WHERE
    and the UPDATE is a no-op.
    """
    targets = (
        ('tenants', 'credit_balance'),
        ('tenant_ledger', 'amount_sar'),
        ('billing_packages', 'credit_sar'),
        ('billing_packages', 'price_sar'),
        ('billing_package_versions', 'credit_sar'),
        ('tenant_package_history', 'credit_sar'),
        ('point_reservations', 'cost_sar'),
        ('recharge_requests', 'amount_sar'),
        ('recharge_requests', 'price_sar'),
        ('topup_receipts', 'amount_sar'),
        ('topup_receipts', 'price_sar'),
        ('topup_receipts', 'tax_amount_sar'),
        ('topup_receipts', 'total_sar'),
    )
    for table, column in targets:
        try:
            conn.execute(
                f'UPDATE {table} SET {column} = ROUND({column}, 2) '
                f'WHERE {column} IS NOT NULL AND ABS({column} - ROUND({column}, 2)) > 1e-9')
        except Exception:
            # A column absent on an older schema is the _add helpers' job.
            pass
    try:
        conn.commit()
    except Exception:
        pass


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
    {'key': 'recharge_invoice', 'label_ar': 'فاتورة شحن الرصيد', 'label_en': 'Recharge invoice',
     'kind': 'document', 'max_size_mb': 15, 'allowed_extensions': ['.pdf', '.png', '.jpg', '.jpeg']},
    {'key': 'ticket_attachment', 'label_ar': 'مرفق تذكرة دعم', 'label_en': 'Support ticket attachment',
     'kind': 'document', 'max_size_mb': 30, 'allowed_extensions': []},
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
