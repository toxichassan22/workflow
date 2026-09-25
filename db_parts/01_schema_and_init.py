

def get_db():
    """Get a SQLite connection for the current request context."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
        g.db.execute('PRAGMA journal_mode = WAL')
    return g.db


def close_db(e=None):
    """Close the database connection at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _utcnow():
    """One clock for the whole layer: naive-UTC ISO strings, the same clock the
    ``datetime('now')`` SQL column defaults already stamp. Python-side writes
    used to run on the server's local time, so a row could hold two different
    clocks in neighbouring columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_db():
    """Create all tables if they don't exist and seed defaults."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys = ON')
        except Exception:
            pass

        _create_tables(conn)
        _seed_admin(conn)
        _repair_field_options(conn)
        _deduplicate_fields(conn)
        _cleanup_accidental_map_fields(conn)
        _migrate_branding_columns(conn)
        _migrate_map_images_presentation_fk(conn)
        _migrate_project_draft_columns(conn)
        _migrate_presentation_draft_link(conn)
        _migrate_project_file_table(conn)
        _migrate_location_fields(conn)
        _migrate_font_system(conn)
        _create_landloom_tables(conn)
        _create_landloom_role_tables(conn)
        _create_identity_tables(conn)
        _create_landloom_event_tables(conn)
        _create_platform_tables(conn)
        _seed_file_type_registry(conn)
        _ensure_landloom_columns(conn)
        _ensure_platform_columns(conn)
        _dedupe_open_workflow_rows(conn)
        _platform_unique_indexes(conn)
        _migrate_generation_approval_columns(conn)
        _migrate_point_reservation_columns(conn)
        _migrate_workflow_gate_columns(conn)
        _migrate_user_assignments_cleanup(conn)
        # Runs after _create_tables: the primary-user backfill there still keys
        # off the legacy 'company_admin' role before it is collapsed here.
        _collapse_legacy_user_roles(conn)

        try:
            conn.commit()
            conn.close()
        except Exception:
            pass
        print(f"[DB] Initialized at {DB_PATH}")
    except Exception as exc:
        print(f"[DB INIT NOTICE] Database initialization notice: {exc}")


def _create_tables(conn):
    """Create any missing table.

    This used to return early when the ``tenants`` table already existed, which meant the schema
    below only ever ran on a brand-new database. Every table added after the first deploy was
    therefore missing forever on existing installs, and the failure surfaced far away as a 500 from
    whichever endpoint touched it. Every statement is ``IF NOT EXISTS``, so running it every time is
    both safe and the only way new tables arrive.
    """
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tenants (
        id TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        account_manager_name TEXT,
        username TEXT,
        phone TEXT,
        subdomain TEXT UNIQUE,
        domain TEXT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        plan TEXT DEFAULT 'free',
        credit_balance REAL DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        is_admin INTEGER DEFAULT 0,
        primary_user_id TEXT,
        require_password_change INTEGER DEFAULT 0,
        session_version INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        settings_json TEXT
    );
    CREATE TABLE IF NOT EXISTS tenant_branding (
        tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
        primary_color TEXT DEFAULT '#3B6E91',
        secondary_color TEXT DEFAULT '#254B66',
        accent_color TEXT DEFAULT '#6DA3C3',
        background_color TEXT DEFAULT '#F4F9FC',
        text_color TEXT DEFAULT '#333333',
        logo_path TEXT,
        watermark_path TEXT,
        company_name TEXT,
        tagline TEXT,
        font_family TEXT DEFAULT 'The Sans Arabic',
        font_arabic TEXT DEFAULT 'The Sans Arabic',
        design_template TEXT DEFAULT 'modern',
        reference_image_path TEXT,
        header_enabled INTEGER DEFAULT 1,
        footer_enabled INTEGER DEFAULT 1,
        header_height INTEGER DEFAULT 56,
        footer_height INTEGER DEFAULT 36,
        card_style TEXT DEFAULT 'bordered',
        slide_ratio TEXT DEFAULT '16:9',
        moodboard_enabled INTEGER DEFAULT 1,
        cover_image_enabled INTEGER DEFAULT 1,
        moodboard_count INTEGER DEFAULT 4,
        default_slide_count INTEGER DEFAULT 16,
        lock_slide_count INTEGER DEFAULT 0,
        min_slides INTEGER DEFAULT 8,
        max_slides INTEGER DEFAULT 30,
        default_map_type TEXT DEFAULT 'satellite',
        map_style_overview TEXT DEFAULT 'satellite',
        map_style_landmarks TEXT DEFAULT 'satellite',
        map_style_access TEXT DEFAULT 'satellite',
        map_style_catchment TEXT DEFAULT 'satellite',
        draw_compass INTEGER DEFAULT 1,
        draw_inset INTEGER DEFAULT 1,
        font_file_path TEXT,
        font_file_data TEXT,
        generation_rules TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS tenant_input_fields (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        field_key TEXT NOT NULL,
        field_label TEXT NOT NULL,
        field_type TEXT NOT NULL,
        field_options TEXT,
        section_key TEXT DEFAULT 'general',
        is_required INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        is_custom INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        placeholder TEXT,
        default_value TEXT,
        ai_hint TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS tenant_slide_templates (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        slide_type TEXT NOT NULL,
        slide_name TEXT NOT NULL,
        design_instructions TEXT,
        is_active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS presentations (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        draft_id TEXT,
        project_data TEXT,
        slides_data TEXT,
        slide_count INTEGER,
        status TEXT DEFAULT 'draft',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS exports (
        id TEXT PRIMARY KEY,
        presentation_id TEXT REFERENCES presentations(id) ON DELETE CASCADE,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        format TEXT NOT NULL,
        file_path TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_fields_tenant ON tenant_input_fields(tenant_id);
    -- get_fields() filters on is_active and orders by sort_order on every form load.
    CREATE INDEX IF NOT EXISTS idx_fields_tenant_active ON tenant_input_fields(tenant_id, is_active, sort_order);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_fields_tenant_key ON tenant_input_fields(tenant_id, field_key);
    CREATE INDEX IF NOT EXISTS idx_presentations_tenant ON presentations(tenant_id);
    -- The presentation list filters by tenant and shows newest first.
    CREATE INDEX IF NOT EXISTS idx_presentations_tenant_recent ON presentations(tenant_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_exports_tenant ON exports(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_templates_tenant ON tenant_slide_templates(tenant_id);

    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        username TEXT,
        phone TEXT,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'employee',
        is_active INTEGER DEFAULT 1,
        require_password_change INTEGER DEFAULT 0,
        session_version INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
    CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

    CREATE TABLE IF NOT EXISTS password_setup_tokens (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
        token_hash TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_password_setup_tokens_tenant ON password_setup_tokens(tenant_id);

    CREATE TABLE IF NOT EXISTS revoked_tokens (
        jti TEXT PRIMARY KEY,
        tenant_id TEXT,
        expires_at INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_revoked_tokens_exp ON revoked_tokens(expires_at);

    CREATE TABLE IF NOT EXISTS user_permissions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        permission_key TEXT NOT NULL,
        granted INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_user_permissions_key ON user_permissions(user_id, permission_key);
    CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON user_permissions(user_id);

    CREATE TABLE IF NOT EXISTS user_field_sections (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        section_key TEXT NOT NULL,
        granted INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_user_field_sections_key ON user_field_sections(user_id, section_key);
    CREATE INDEX IF NOT EXISTS idx_user_field_sections_user ON user_field_sections(user_id);

    CREATE TABLE IF NOT EXISTS tenant_custom_sections (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        section_key TEXT NOT NULL,
        section_label TEXT NOT NULL,
        section_icon TEXT DEFAULT 'file',
        sort_order INTEGER DEFAULT 100,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_custom_sections_key ON tenant_custom_sections(tenant_id, section_key);

    -- Company-wide project-team library. A flat list: each entity says what it does in its own
    -- role field, so a separate category layer earned nothing.
    -- Entities defined here appear in every project file. A draft can exclude one, or add
    -- project-only entities of its own.
    -- The logo reuses project_files (tenant-scoped storage plus the authenticated preview route).
    -- Do not use a semicolon inside these comments: the schema runner splits statements on it.
    CREATE TABLE IF NOT EXISTS tenant_team_entities (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        logo_file_id TEXT,
        brief TEXT,
        experience_years TEXT,
        notable_projects TEXT,
        role TEXT,
        sort_order INTEGER DEFAULT 100,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_tenant_team_entities_tenant ON tenant_team_entities(tenant_id, sort_order);

    CREATE TABLE IF NOT EXISTS presentation_versions (
        id TEXT PRIMARY KEY,
        presentation_id TEXT NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
        user_id TEXT,
        user_name TEXT,
        slides_data TEXT,
        action TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_versions_pres ON presentation_versions(presentation_id);

    CREATE TABLE IF NOT EXISTS edit_log (
        id TEXT PRIMARY KEY,
        presentation_id TEXT NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
        user_id TEXT,
        user_name TEXT,
        action TEXT NOT NULL,
        details TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_editlog_pres ON edit_log(presentation_id);

    CREATE TABLE IF NOT EXISTS change_log (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        user_id TEXT,
        user_name TEXT,
        source TEXT NOT NULL DEFAULT 'manual',
        action TEXT NOT NULL,
        summary TEXT,
        details TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_changelog_target ON change_log(target_type, target_id, created_at);

    CREATE TABLE IF NOT EXISTS invite_links (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        email TEXT NOT NULL,
        token TEXT UNIQUE NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_invites_tenant ON invite_links(tenant_id);

    CREATE TABLE IF NOT EXISTS tenant_training_data (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        image_path TEXT,
        image_analysis TEXT,
        image_type TEXT,
        image_description TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_training_tenant ON tenant_training_data(tenant_id);

    CREATE TABLE IF NOT EXISTS presentation_approvals (
        id TEXT PRIMARY KEY,
        presentation_id TEXT NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        requested_by TEXT,
        requested_by_name TEXT,
        status TEXT DEFAULT 'pending',
        reviewed_by TEXT,
        reviewed_by_name TEXT,
        review_note TEXT,
        request_hash TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        reviewed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_approvals_tenant ON presentation_approvals(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_approvals_pres ON presentation_approvals(presentation_id);

    CREATE TABLE IF NOT EXISTS project_drafts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT,
        title TEXT,
        draft_data TEXT,
        section_statuses TEXT,
        status TEXT DEFAULT 'draft',
        revision INTEGER DEFAULT 1,
        data_bytes INTEGER DEFAULT 0,
        has_slides INTEGER DEFAULT 0,
        has_maps INTEGER DEFAULT 0,
        requested_by TEXT,
        requested_by_name TEXT,
        requested_at TEXT,
        reviewed_by TEXT,
        reviewed_by_name TEXT,
        review_note TEXT,
        reviewed_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_drafts_tenant ON project_drafts(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_drafts_user ON project_drafts(user_id);
    -- The hot lookup is "newest draft for this actor", which the single-column indexes above
    -- cannot serve: they find the tenant's rows but still sort every one of them.
    CREATE INDEX IF NOT EXISTS idx_drafts_actor_recent ON project_drafts(tenant_id, user_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_drafts_tenant_recent ON project_drafts(tenant_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_drafts_tenant_status ON project_drafts(tenant_id, status);

    -- Immutable per-section snapshots for the approval workflow. Every send for
    -- approval copies the section inputs of that moment into a new row with the
    -- next version number, and every approval decision names that number instead
    -- of the live values that keep changing. Rows are never updated in place
    -- apart from the single decision columns, so history survives intact.
    -- Older pending rows are marked superseded when a newer send arrives.
    -- Keep every comment here free of the statement separator.
    CREATE TABLE IF NOT EXISTS section_versions (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        draft_id TEXT NOT NULL,
        section_key TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        snapshot_data TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_by TEXT,
        created_by_name TEXT,
        decided_by TEXT,
        decided_by_name TEXT,
        decision_note TEXT,
        decided_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_section_versions_number ON section_versions(draft_id, section_key, version_number);
    CREATE INDEX IF NOT EXISTS idx_section_versions_lookup ON section_versions(tenant_id, draft_id, section_key, created_at DESC);

    -- AuditEvent: Unified immutable audit log (Landloom spec sections 6, 15, 18).
    -- Captures user, time, action, entity, old_value, new_value, and metadata.
    -- Append-only ledger: modifications and deletions are strictly forbidden.
    -- Keep every comment here free of the statement separator.
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT,
        user_name TEXT,
        user_role TEXT,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        entity_name TEXT,
        old_value TEXT,
        new_value TEXT,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_audit_events_tenant ON audit_events(tenant_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(tenant_id, entity_type, entity_id);
    CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(tenant_id, action);

    CREATE TABLE IF NOT EXISTS ai_rules_log (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT,
        user_name TEXT,
        rule_category TEXT NOT NULL,
        rule_key TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        risk_level TEXT DEFAULT 'green',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_airules_tenant ON ai_rules_log(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_airules_created ON ai_rules_log(created_at);

    CREATE TABLE IF NOT EXISTS agent_chat_log (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT,
        user_name TEXT,
        message TEXT,
        reply TEXT,
        actions_json TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_agentchat_tenant ON agent_chat_log(tenant_id, created_at DESC);

    CREATE TABLE IF NOT EXISTS map_images (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        presentation_id TEXT,
        image_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        placeholder TEXT NOT NULL,
        metadata_json TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_mapimages_tenant ON map_images(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_mapimages_pres ON map_images(presentation_id);
    CREATE INDEX IF NOT EXISTS idx_mapimages_type ON map_images(image_type);

    CREATE TABLE IF NOT EXISTS project_files (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        draft_id TEXT,
        project_id TEXT,
        file_type TEXT NOT NULL,
        original_name TEXT,
        storage_path TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        file_size INTEGER DEFAULT 0,
        sha256 TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_project_files_tenant ON project_files(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_project_files_draft ON project_files(tenant_id, draft_id);
    CREATE INDEX IF NOT EXISTS idx_project_files_hash ON project_files(tenant_id, sha256);

    CREATE TABLE IF NOT EXISTS ai_usage_events (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        draft_id TEXT,
        presentation_id TEXT,
        flow TEXT NOT NULL DEFAULT 'other',
        model TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok',
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        cost_usd REAL,
        generation_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        cost_source TEXT,
        attempt_status TEXT DEFAULT 'pending',
        reconcile_attempts INTEGER DEFAULT 0,
        next_retry_at TEXT,
        updated_at TEXT DEFAULT (datetime('now')),
        response_cost_usd REAL,
        generation_cost_usd REAL,
        cost_raw TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_aiusage_tenant ON ai_usage_events(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_aiusage_draft ON ai_usage_events(draft_id);
    CREATE INDEX IF NOT EXISTS idx_aiusage_presentation ON ai_usage_events(presentation_id);
    CREATE INDEX IF NOT EXISTS idx_aiusage_created ON ai_usage_events(created_at);
    CREATE INDEX IF NOT EXISTS idx_aiusage_reconcile ON ai_usage_events(tenant_id, attempt_status, next_retry_at);

    CREATE TABLE IF NOT EXISTS map_usage_events (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        draft_id TEXT,
        presentation_id TEXT,
        flow TEXT NOT NULL DEFAULT 'other',
        sku TEXT NOT NULL,
        units INTEGER DEFAULT 0,
        unit_price_usd REAL DEFAULT 0,
        cost_usd REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_mapusage_tenant ON map_usage_events(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_mapusage_draft ON map_usage_events(draft_id);
    CREATE INDEX IF NOT EXISTS idx_mapusage_presentation ON map_usage_events(presentation_id);
    CREATE INDEX IF NOT EXISTS idx_mapusage_created ON map_usage_events(created_at);

    -- Persistent Google discovery cache. Roads, landmarks, geocodes and matrix
    -- answers for one rounded coordinate do not change between analyses, so a
    -- re-analysis of the same site must not pay Google a second time. Rows are
    -- tenant-scoped and carry an expiry. Cached hits record no spend.
    CREATE TABLE IF NOT EXISTS maps_discovery_cache (
        cache_key TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        payload_json TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_maps_cache_tenant ON maps_discovery_cache(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_maps_cache_expiry ON maps_discovery_cache(expires_at);

    -- Billing packages (bundles) sold to companies. credit_usd is the
    -- canonical spend allowance (what the provider key limit follows);
    -- price_sar is the selling price shown to clients. The super admin
    -- edits both freely and adds custom packages at any time.
    CREATE TABLE IF NOT EXISTS billing_packages (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        credit_usd REAL NOT NULL DEFAULT 0,
        credit_sar REAL,
        price_sar REAL,
        is_active INTEGER DEFAULT 1,
        is_custom INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    -- USD to SAR rate used to display balances in riyals. source is auto
    -- (fetched provider rate, refreshed daily) or manual (super-admin
    -- override that auto-refresh never overwrites).
    CREATE TABLE IF NOT EXISTS fx_rates (
        pair TEXT PRIMARY KEY,
        rate REAL NOT NULL,
        source TEXT DEFAULT 'auto',
        updated_at TEXT DEFAULT (datetime('now'))
    );
    -- Package subscription history. Every assignment snapshots the credit so
    -- per-package consumption and the lifetime total across all packages stay
    -- exact even after the package itself is edited or deleted.
    CREATE TABLE IF NOT EXISTS tenant_package_history (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        package_id TEXT,
        package_name TEXT,
        credit_usd REAL NOT NULL DEFAULT 0,
        credit_sar REAL,
        assigned_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_package_history_tenant ON tenant_package_history(tenant_id, assigned_at);

    CREATE TABLE IF NOT EXISTS platform_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS tenant_ledger (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'debit',
        amount_usd REAL NOT NULL DEFAULT 0,
        amount_sar REAL,
        fx_rate REAL,
        raw_cost_usd REAL NOT NULL DEFAULT 0,
        multiplier REAL NOT NULL DEFAULT 1,
        maps_cost_usd REAL NOT NULL DEFAULT 0,
        ai_cost_usd REAL NOT NULL DEFAULT 0,
        maps_events_count INTEGER NOT NULL DEFAULT 0,
        ai_events_count INTEGER NOT NULL DEFAULT 0,
        draft_id TEXT,
        presentation_id TEXT,
        idempotency_key TEXT UNIQUE,
        note TEXT,
        actor TEXT,
        reversal_of TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_ledger_tenant ON tenant_ledger(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_ledger_created ON tenant_ledger(created_at);
    CREATE INDEX IF NOT EXISTS idx_ledger_idempotency ON tenant_ledger(idempotency_key);

    -- One OpenRouter key per tenant company. Managed keys are created through
    -- the OpenRouter Management API so they appear in the owner dashboard
    -- with their own spend limit. Manual keys are pasted by a super admin.
    -- The raw value is stored encrypted and is never returned by metadata reads.
    CREATE TABLE IF NOT EXISTS tenant_openrouter_keys (
        id TEXT PRIMARY KEY,
        tenant_id TEXT UNIQUE NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        key_enc TEXT NOT NULL,
        key_hash TEXT NOT NULL,
        key_label TEXT,
        openrouter_key_hash TEXT,
        limit_usd REAL,
        limit_reset TEXT,
        provenance TEXT DEFAULT 'auto',
        is_active INTEGER DEFAULT 1,
        last_limit_remaining REAL,
        last_usage REAL,
        last_checked_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_tenant_or_keys_tenant ON tenant_openrouter_keys(tenant_id);
    """)

    _ensure_audit_events_triggers(conn)
    _migrate_presentation_revision_schema(conn)

    branding_cols = [row['name'] for row in conn.execute('PRAGMA table_info(tenant_branding)').fetchall()]
    if 'moodboard_count' not in branding_cols:
        conn.execute('ALTER TABLE tenant_branding ADD COLUMN moodboard_count INTEGER DEFAULT 4')
        print('[DB] Migration: added moodboard_count column to tenant_branding')
    if 'lock_slide_count' not in branding_cols:
        conn.execute('ALTER TABLE tenant_branding ADD COLUMN lock_slide_count INTEGER DEFAULT 0')
        print('[DB] Migration: added lock_slide_count column to tenant_branding')
    if 'default_map_type' not in branding_cols:
        conn.execute("ALTER TABLE tenant_branding ADD COLUMN default_map_type TEXT DEFAULT 'satellite'")
        print('[DB] Migration: added default_map_type column to tenant_branding')

    # Migration: add domain column to existing tenants table
    cols = [row['name'] for row in conn.execute('PRAGMA table_info(tenants)').fetchall()]
    if 'domain' not in cols:
        conn.execute('ALTER TABLE tenants ADD COLUMN domain TEXT')
        print('[DB] Migration: added domain column to tenants')
    for column, definition in (
        ('account_manager_name', 'TEXT'),
        ('username', 'TEXT'),
        ('phone', 'TEXT'),
        ('credit_balance', 'REAL DEFAULT 0'),
        ('primary_user_id', 'TEXT'),
        ('require_password_change', 'INTEGER DEFAULT 0'),
        ('package_id', 'TEXT'),
        ('session_version', 'INTEGER DEFAULT 0'),
    ):
        if column not in cols:
            conn.execute(f'ALTER TABLE tenants ADD COLUMN {column} {definition}')
            print(f'[DB] Migration: added {column} column to tenants')

    user_cols = [row['name'] for row in conn.execute('PRAGMA table_info(users)').fetchall()]
    for column, definition in (
        ('username', 'TEXT'),
        ('phone', 'TEXT'),
        ('require_password_change', 'INTEGER DEFAULT 0'),
        ('session_version', 'INTEGER DEFAULT 0'),
    ):
        if column not in user_cols:
            conn.execute(f'ALTER TABLE users ADD COLUMN {column} {definition}')
            print(f'[DB] Migration: added {column} column to users')

    # Billing ledger link. Each usage row carries the id of the ledger entry
    # that billed it, so checkout bills the unbilled scope only and a retry
    # or a parallel request can never bill the same event twice.
    for _usage_table in ('ai_usage_events', 'map_usage_events'):
        try:
            _usage_cols = [row['name'] for row in conn.execute(f'PRAGMA table_info({_usage_table})').fetchall()]
        except Exception:
            _usage_cols = []
        if _usage_cols and 'billed_ledger_id' not in _usage_cols:
            conn.execute(f'ALTER TABLE {_usage_table} ADD COLUMN billed_ledger_id TEXT')
            print(f'[DB] Migration: added billed_ledger_id column to {_usage_table}')
        # Write-time package attribution: every spend row carries the package
        # it was burned under, so per-package totals never depend on clock
        # comparisons between an assignment and later usage.
        if _usage_cols and 'package_id' not in _usage_cols:
            conn.execute(f'ALTER TABLE {_usage_table} ADD COLUMN package_id TEXT')
            print(f'[DB] Migration: added package_id column to {_usage_table}')
        # Legacy rows stored the literal string 'None' where no package was
        # active — normalize it to NULL so package filters read real data.
        try:
            conn.execute(
                f"UPDATE {_usage_table} SET package_id = NULL "
                "WHERE package_id IN ('', 'None', 'none')")
        except Exception:
            pass
    try:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_aiusage_billed ON ai_usage_events(billed_ledger_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_mapusage_billed ON map_usage_events(billed_ledger_id)')
    except Exception:
        pass
    _migrate_ai_usage_attempt_columns(conn)
    # Backfill the primary company admin in two correlated steps. SQLite does not
    # resolve an outer-table reference inside ORDER BY of an UPDATE subquery
    # (no such column: tenants.email), so the email preference and the
    # earliest-admin fallback run as separate statements that only correlate
    # in WHERE and only order by inner columns.
    conn.execute(
        '''UPDATE tenants
           SET primary_user_id = (
               SELECT users.id FROM users
               WHERE users.tenant_id = tenants.id
                 AND users.role = 'company_admin'
                 AND LOWER(users.email) = LOWER(tenants.email)
               LIMIT 1
           )
           WHERE primary_user_id IS NULL'''
    )
    conn.execute(
        '''UPDATE tenants
           SET primary_user_id = (
               SELECT users.id FROM users
               WHERE users.tenant_id = tenants.id
                 AND users.role = 'company_admin'
               ORDER BY users.created_at
               LIMIT 1
           )
           WHERE primary_user_id IS NULL'''
    )
    conn.execute(
        '''UPDATE tenants
           SET account_manager_name = (
               SELECT users.name FROM users WHERE users.id = tenants.primary_user_id
           )
           WHERE COALESCE(account_manager_name, '') = ''
             AND primary_user_id IS NOT NULL'''
    )

    # Migration: add section_key column to tenant_input_fields
    cols = [row['name'] for row in conn.execute('PRAGMA table_info(tenant_input_fields)').fetchall()]
    if 'section_key' not in cols:
        conn.execute('ALTER TABLE tenant_input_fields ADD COLUMN section_key TEXT DEFAULT \'general\'')
        print('[DB] Migration: added section_key column to tenant_input_fields')

    # Migration: set section_key for existing pre-built fields
    _migrate_field_sections(conn)

    # Migration: ensure new pre-built location fields exist for all tenants
    _migrate_location_fields(conn)

    # Migration: add image_path and image_analysis columns to tenant_training_data
    training_cols = [row['name'] for row in conn.execute('PRAGMA table_info(tenant_training_data)').fetchall()]
    if 'image_path' not in training_cols:
        conn.execute('ALTER TABLE tenant_training_data ADD COLUMN image_path TEXT')
        print('[DB] Migration: added image_path column to tenant_training_data')
    if 'image_analysis' not in training_cols:
        conn.execute('ALTER TABLE tenant_training_data ADD COLUMN image_analysis TEXT')
        print('[DB] Migration: added image_analysis column to tenant_training_data')
    if 'image_type' not in training_cols:
        conn.execute('ALTER TABLE tenant_training_data ADD COLUMN image_type TEXT')
        print('[DB] Migration: added image_type column to tenant_training_data')
    if 'image_description' not in training_cols:
        conn.execute('ALTER TABLE tenant_training_data ADD COLUMN image_description TEXT')
        print('[DB] Migration: added image_description column to tenant_training_data')

    # Migration: normalize historical company-admin drafts and add approval audit fields.
    # Company-admin JWTs intentionally have no user_id, so NULL cannot be used as the
    # draft owner (SQL NULL never equals NULL). A stable tenant-scoped actor fixes that.
    draft_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='project_drafts'"
    ).fetchone()
    draft_cols = [row['name'] for row in conn.execute('PRAGMA table_info(project_drafts)').fetchall()] if draft_table else []
    if draft_table:
        conn.execute("UPDATE project_drafts SET user_id = 'tenant-admin:' || tenant_id WHERE user_id IS NULL")
    if draft_table:
        for column, definition in (
            ('requested_by', 'TEXT'),
            ('requested_by_name', 'TEXT'),
            ('requested_at', 'TEXT'),
            ('reviewed_by', 'TEXT'),
            ('reviewed_by_name', 'TEXT'),
            ('review_note', 'TEXT'),
            ('reviewed_at', 'TEXT'),
        ):
            if column not in draft_cols:
                if not re.fullmatch(r'[A-Za-z0-9_]+', column) or not re.fullmatch(r'[A-Za-z0-9() ,]+', definition):
                    raise ValueError('Invalid migration column definition')
                conn.execute(f'ALTER TABLE project_drafts ADD COLUMN {column} {definition}')
                print(f'[DB] Migration: added {column} column to project_drafts')


def _migrate_ai_usage_attempt_columns(conn):
    """Add attempt and settlement columns to ai_usage_events on existing databases.

    Old rows keep their stored cost and are never marked complete here
    verification of their generation id happens only through the explicit
    review path.
    """
    try:
        existing = [row['name'] for row in conn.execute('PRAGMA table_info(ai_usage_events)').fetchall()]
    except Exception:
        return
    if not existing:
        return
    for column, definition in (
        ('cost_source', 'TEXT'),
        ('attempt_status', "TEXT DEFAULT 'pending'"),
        ('reconcile_attempts', 'INTEGER DEFAULT 0'),
        ('next_retry_at', 'TEXT'),
        ('updated_at', 'TEXT'),
        ('response_cost_usd', 'REAL'),
        ('generation_cost_usd', 'REAL'),
        ('cost_raw', 'TEXT'),
    ):
        if column not in existing:
            conn.execute(f'ALTER TABLE ai_usage_events ADD COLUMN {column} {definition}')
            print(f'[DB] Migration: added {column} column to ai_usage_events')
    try:
        conn.execute('CREATE INDEX IF NOT EXISTS idx_aiusage_reconcile ON ai_usage_events(tenant_id, attempt_status, next_retry_at)')
    except Exception:
        pass


def _is_postgres_conn(conn):
    """True when the connection is the psycopg2-backed Postgres wrapper."""
    return isinstance(conn, sqlite3.PostgresConnection)


def _ensure_audit_events_triggers(conn):
    """Enforce immutability on audit_events at database level.

    Audit events must be strictly append-only on both backends. SQLite uses
    RAISE(ABORT) triggers; PostgreSQL gets a plpgsql function fired by
    BEFORE UPDATE/DELETE triggers. Failure is reported, never swallowed, so a
    missing trigger can never look like a healthy install.
    """
    if _is_postgres_conn(conn):
        try:
            conn.execute("""
                CREATE OR REPLACE FUNCTION audit_events_immutable()
                RETURNS trigger AS $func$
                BEGIN
                    RAISE EXCEPTION 'audit_events are immutable and cannot be modified';
                END;
                $func$ LANGUAGE plpgsql
            """)
            conn.execute('DROP TRIGGER IF EXISTS trg_audit_events_no_update ON audit_events')
            conn.execute('DROP TRIGGER IF EXISTS trg_audit_events_no_delete ON audit_events')
            conn.execute("""
                CREATE TRIGGER trg_audit_events_no_update
                BEFORE UPDATE ON audit_events
                FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()
            """)
            conn.execute("""
                CREATE TRIGGER trg_audit_events_no_delete
                BEFORE DELETE ON audit_events
                FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()
            """)
            conn.commit()
        except Exception as exc:
            print(f'[DB] audit_events immutability triggers failed on PostgreSQL: {exc}')
        return
    try:
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are immutable and cannot be updated');
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are immutable and cannot be deleted');
            END
        """)
    except Exception as exc:
        print(f'[DB] audit_events immutability triggers failed on SQLite: {exc}')


def _seed_admin(conn):
    """Seed or update a super admin from environment credentials."""
    from auth import hash_password

    conn.execute(
        "UPDATE tenants SET is_active = 0 WHERE email = 'admin@system.local' AND is_admin = 1"
    )

    admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    admin_password = os.environ.get('ADMIN_PASSWORD', '')
    admin_name = os.environ.get('ADMIN_COMPANY_NAME', 'System Administration').strip()
    if not admin_email or len(admin_password) < 12:
        print('[DB] Admin seed skipped; set ADMIN_EMAIL and ADMIN_PASSWORD (12+ chars)')
        return

    existing = conn.execute('SELECT id FROM tenants WHERE email = ?', (admin_email,)).fetchone()
    if existing:
        conn.execute(
            'UPDATE tenants SET company_name = ?, password_hash = ?, plan = ?, is_admin = 1, is_active = 1 WHERE id = ?',
            (admin_name, hash_password(admin_password), 'enterprise', existing['id'])
        )
        conn.execute(
            'INSERT OR IGNORE INTO tenant_branding (tenant_id, company_name, primary_color, secondary_color, accent_color, background_color, lock_slide_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (existing['id'], admin_name, '#3B6E91', '#254B66', '#6DA3C3', '#F4F9FC', 0)
        )
        return

    admin_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO tenants (id, company_name, email, password_hash, plan, is_admin, is_active) VALUES (?, ?, ?, ?, ?, 1, 1)',
        (admin_id, admin_name, admin_email, hash_password(admin_password), 'enterprise')
    )
    conn.execute(
        'INSERT INTO tenant_branding (tenant_id, company_name, primary_color, secondary_color, accent_color, background_color, lock_slide_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (admin_id, admin_name, '#3B6E91', '#254B66', '#6DA3C3', '#F4F9FC', 0)
    )
    print(f"[DB] Seeded super admin: {admin_email}")


def _json_or(value, fallback):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed is not None else fallback
