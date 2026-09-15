"""
Database layer for Multi-Tenant SaaS.
SQLite-based with full migration support.
"""

import os
import re
import uuid
import json
import hashlib
from datetime import datetime, timedelta, timezone
from flask import g

import db_driver as sqlite3

DB_PATH = (
    os.environ.get('DB_PATH')
    or os.environ.get('DATABASE_URL')
    or os.path.join(os.path.dirname(__file__), 'app.db')
)


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
        _create_omran_tables(conn)
        _create_omran_role_tables(conn)
        _create_identity_tables(conn)
        _create_omran_event_tables(conn)
        _create_platform_tables(conn)
        _seed_file_type_registry(conn)
        _ensure_omran_columns(conn)
        _ensure_platform_columns(conn)
        _dedupe_open_workflow_rows(conn)
        _platform_unique_indexes(conn)
        _migrate_generation_approval_columns(conn)
        _migrate_point_reservation_columns(conn)
        _migrate_workflow_gate_columns(conn)

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

    -- AuditEvent: Unified immutable audit log (Omran spec sections 6, 15, 18).
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
        assigned_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_package_history_tenant ON tenant_package_history(tenant_id, assigned_at);

    CREATE TABLE IF NOT EXISTS tenant_ledger (
        id TEXT PRIMARY KEY,
        tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'debit',
        amount_usd REAL NOT NULL DEFAULT 0,
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
    ):
        if column not in cols:
            conn.execute(f'ALTER TABLE tenants ADD COLUMN {column} {definition}')
            print(f'[DB] Migration: added {column} column to tenants')

    user_cols = [row['name'] for row in conn.execute('PRAGMA table_info(users)').fetchall()]
    for column, definition in (
        ('username', 'TEXT'),
        ('phone', 'TEXT'),
        ('require_password_change', 'INTEGER DEFAULT 0'),
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


# ─────────────────────────────────────────────────────────────────────────────
# Tenant CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_tenant(company_name, email, password_hash, subdomain=None, plan='free',
                  account_manager_name=None, username=None, phone=None,
                  credit_balance=0, require_password_change=False):
    """Create a new tenant with branding row and default fields."""
    conn = get_db()
    tenant_id = str(uuid.uuid4())

    conn.execute(
        '''INSERT INTO tenants
           (id, company_name, account_manager_name, username, phone, subdomain, email,
            password_hash, plan, credit_balance, require_password_change, activated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (tenant_id, company_name, account_manager_name, username, phone, subdomain, email,
         password_hash, plan, credit_balance, 1 if require_password_change else 0,
         _utcnow().isoformat())
    )
    conn.execute(
        'INSERT INTO tenant_branding (tenant_id, company_name, primary_color, secondary_color, accent_color, background_color, lock_slide_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (tenant_id, company_name, '#3B6E91', '#254B66', '#6DA3C3', '#F4F9FC', 0)
    )
    _seed_default_fields(conn, tenant_id)
    conn.commit()
    return tenant_id


def get_tenant_by_email(email):
    """Fetch a tenant by email."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenants WHERE email = ?', (email,)).fetchone()
    return dict(row) if row else None


def get_tenant_by_username(username):
    """Fetch a tenant by username."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenants WHERE LOWER(username) = LOWER(?)',
        (str(username or '').strip(),)
    ).fetchone()
    return dict(row) if row else None


def get_tenant_by_id(tenant_id):
    """Fetch a tenant by ID."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenants WHERE id = ?', (tenant_id,)).fetchone()
    return dict(row) if row else None


def get_tenant_by_subdomain(subdomain):
    """Fetch a tenant by subdomain."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenants WHERE subdomain = ? AND is_active = 1', (subdomain,)).fetchone()
    return dict(row) if row else None


_SLUG_RE = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')


def _normalize_slug(value):
    """Lowercase a candidate and fold username characters into URL-safe form."""
    slug = re.sub(r'[^a-z0-9-]', '', str(value or '').strip().lower().replace('_', '-').replace('.', '-').replace(' ', '-'))
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    return slug if slug and _SLUG_RE.fullmatch(slug) else ''


def tenant_slug(tenant):
    """Stable latin slug identifying a company in role-prefixed URLs.

    Prefers the explicit ``subdomain``, then the latin ``username`` (folded to
    URL-safe form). Both are already UNIQUE values. Arabic company names are
    never used: they break URL encoding and every rename would invalidate
    bookmarks. The ``t-<id8>`` fallback keeps tenants without either value
    addressable.
    """
    if not tenant:
        return ''
    for key in ('slug', 'subdomain', 'username'):
        slug = _normalize_slug(tenant.get(key))
        if slug:
            return slug
    tenant_id = str(tenant.get('id') or '').strip()
    return ('t-' + re.sub(r'[^a-z0-9]', '', tenant_id.lower())[:8]) if tenant_id else ''


def get_tenant_by_slug(slug):
    """Resolve a URL slug back to its tenant (subdomain, username, or id fallback)."""
    raw = str(slug or '').strip().lower()
    if not raw:
        return None
    conn = get_db()
    for candidate in dict.fromkeys([raw, _normalize_slug(raw)]):
        if not candidate:
            continue
        row = conn.execute(
            'SELECT * FROM tenants WHERE LOWER(subdomain) = ? AND is_active = 1', (candidate,)
        ).fetchone()
        if row:
            return dict(row)
        row = conn.execute(
            'SELECT * FROM tenants WHERE LOWER(REPLACE(REPLACE(username, ?, ?), ?, ?)) = ? AND is_active = 1',
            ('_', '-', '.', '-', candidate)
        ).fetchone()
        if row:
            return dict(row)
    if raw.startswith('t-'):
        suffix = re.sub(r'[^a-z0-9]', '', raw[2:])
        if suffix:
            row = conn.execute(
                'SELECT * FROM tenants WHERE REPLACE(LOWER(id), ?, ?) LIKE ? AND is_active = 1',
                ('-', '', suffix + '%')
            ).fetchone()
            return dict(row) if row else None
    return None


def get_all_tenants():
    """Fetch all tenants (admin only)."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM tenants ORDER BY created_at DESC').fetchall()
    return [dict(r) for r in rows]


def update_tenant(tenant_id, **fields):
    """Update tenant fields dynamically."""
    conn = get_db()
    allowed = {
        'company_name', 'account_manager_name', 'username', 'phone', 'subdomain',
        'domain', 'email', 'password_hash', 'plan', 'credit_balance', 'is_active',
        'primary_user_id', 'require_password_change', 'settings_json', 'package_id',
        'legal_name', 'commercial_name', 'tax_number', 'cr_number',
        'country', 'region', 'address', 'contact_title', 'trial_ends_at',
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [tenant_id]
    conn.execute(f'UPDATE tenants SET {set_clause} WHERE id = ?', values)
    conn.commit()
    return True


def create_company_with_admin(company_name, manager_name, email, username, phone,
                              password_hash, plan='free', credit_balance=0,
                              is_active=True, require_password_change=False,
                              profile=None, slug=None, package_id=None,
                              trial_days=None, contracts=None):
    """Create a company, its workspace, and its primary company administrator atomically.

    The whole opening file lands in one transaction (t50-05): tenant row with
    the legal profile, the URL slug, branding, default fields, the admin user,
    the package subscription/trial window, and any uploaded contract documents.
    A failure anywhere rolls everything back so no half-opened company exists.
    """
    conn = get_db()
    profile = dict(profile or {})
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    normalized_slug = None
    if slug:
        normalized_slug = _normalize_slug(slug)
        if not normalized_slug:
            raise ValueError('invalid_slug')
    now = _utcnow().isoformat()
    trial_ends_at = None
    if trial_days:
        from datetime import timedelta
        trial_ends_at = (_utcnow() + timedelta(days=int(trial_days))).isoformat()
    profile_columns = [c for c in TENANT_COMPANY_PROFILE_FIELDS if profile.get(c)]
    try:
        columns = ['id', 'company_name', 'account_manager_name', 'username', 'phone',
                   'email', 'password_hash', 'plan', 'credit_balance', 'is_active',
                   'primary_user_id', 'require_password_change']
        values = [tenant_id, company_name, manager_name, username.lower(), phone,
                  email.lower(), password_hash, plan, credit_balance,
                  1 if is_active else 0, user_id, 1 if require_password_change else 0]
        if normalized_slug:
            columns.append('slug')
            values.append(normalized_slug)
        if package_id:
            columns.append('package_id')
            values.append(str(package_id))
        if trial_ends_at:
            columns.append('trial_ends_at')
            values.append(trial_ends_at)
        if is_active:
            columns.append('activated_at')
            values.append(now)
        for column in profile_columns:
            columns.append(column)
            values.append(str(profile[column]).strip())
        conn.execute(
            f'INSERT INTO tenants ({", ".join(columns)}) VALUES ({", ".join("?" for _ in columns)})',
            values,
        )
        conn.execute(
            '''INSERT INTO tenant_branding
               (tenant_id, company_name, primary_color, secondary_color, accent_color,
                background_color, lock_slide_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (tenant_id, company_name, '#3B6E91', '#254B66', '#6DA3C3', '#F4F9FC', 0)
        )
        _seed_default_fields(conn, tenant_id)
        conn.execute(
            '''INSERT INTO users
               (id, tenant_id, name, username, phone, email, password_hash, role,
                is_active, require_password_change)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'company_admin', ?, ?)''',
            (user_id, tenant_id, manager_name, username.lower(), phone, email.lower(),
             password_hash, 1 if is_active else 0, 1 if require_password_change else 0)
        )
        if package_id or trial_ends_at:
            conn.execute(
                '''INSERT INTO tenant_subscriptions
                   (id, tenant_id, package_id, status, starts_at, trial_ends_at)
                   VALUES (?, ?, ?, 'active', ?, ?)''',
                (str(uuid.uuid4()), tenant_id, str(package_id) if package_id else None,
                 now, trial_ends_at),
            )
        for document in (contracts or []):
            contract_id = str(uuid.uuid4())
            doc_kind = document.get('kind') if document.get('kind') in {'contract', 'nda'} else 'contract'
            signature = document.get('signature_status')
            if signature not in CONTRACT_SIGNATURE_STATUSES:
                signature = 'unsigned'
            conn.execute(
                '''INSERT INTO tenant_contracts
                   (id, tenant_id, kind, title, file_id, starts_at, expires_at, notes,
                    status, signature_status, version, retention_until, created_by,
                    created_by_name, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 1, ?, ?, ?, ?)''',
                (contract_id, tenant_id, doc_kind,
                 str(document.get('title') or 'عقد').strip(), document.get('file_id'),
                 document.get('starts_at'), document.get('expires_at'),
                 document.get('notes'), signature, document.get('retention_until'),
                 document.get('created_by'), document.get('created_by_name'), now),
            )
            conn.execute(
                '''INSERT INTO tenant_contract_versions
                   (id, contract_id, tenant_id, version, file_id, signature_status,
                    starts_at, expires_at, retention_until, notes, created_by, created_by_name)
                   VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (str(uuid.uuid4()), contract_id, tenant_id, document.get('file_id'),
                 signature, document.get('starts_at'), document.get('expires_at'),
                 document.get('retention_until'), document.get('notes'),
                 document.get('created_by'), document.get('created_by_name')),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return tenant_id, user_id


def get_tenant_profile_counts(tenant_id):
    """Return company account totals without loading tenant-owned payloads."""
    conn = get_db()
    return {
        'users': conn.execute(
            'SELECT COUNT(*) AS c FROM users WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
        'projects': conn.execute(
            'SELECT COUNT(*) AS c FROM project_drafts WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
        'presentations': conn.execute(
            'SELECT COUNT(*) AS c FROM presentations WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
        'exports': conn.execute(
            'SELECT COUNT(*) AS c FROM exports WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()['c'],
    }


def delete_tenant(tenant_id):
    """Delete a tenant and all related data."""
    conn = get_db()
    conn.execute('DELETE FROM tenants WHERE id = ?', (tenant_id,))
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Branding CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_branding(tenant_id):
    """Get branding settings for a tenant."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenant_branding WHERE tenant_id = ?', (tenant_id,)).fetchone()
    return dict(row) if row else None


def update_branding(tenant_id, **fields):
    """Update branding settings."""
    conn = get_db()
    allowed = {
        'primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color',
        'logo_path', 'watermark_path', 'company_name', 'tagline', 'font_family', 'font_arabic',
        'design_template', 'reference_image_path',
        'header_enabled', 'footer_enabled', 'header_height', 'footer_height',
        'card_style', 'slide_ratio', 'moodboard_enabled', 'cover_image_enabled', 'moodboard_count',
        'default_slide_count', 'lock_slide_count', 'min_slides', 'max_slides',
        'default_map_type', 'map_style_overview', 'map_style_landmarks', 'map_style_access', 'map_style_catchment',
        'draw_compass', 'draw_inset', 'font_file_path', 'font_file_data',
        # Company-written rules that ride with every slide-generation prompt.
        'generation_rules',
        # d05: how many days a decided section approval stays valid.
        'section_approval_days',
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    # Guard against missing columns on databases that haven't run the latest migration
    existing_cols = {row['name'] for row in conn.execute('PRAGMA table_info(tenant_branding)')}
    updates = {k: v for k, v in updates.items() if k in existing_cols}
    if not updates:
        return False
    updates['updated_at'] = _utcnow().isoformat()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [tenant_id]
    conn.execute(f'UPDATE tenant_branding SET {set_clause} WHERE tenant_id = ?', values)
    conn.commit()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Input Fields CRUD
# ─────────────────────────────────────────────────────────────────────────────

FIELD_SECTIONS = [
    {'key': 'basic', 'label': 'معلومات أساسية'},
    {'key': 'location', 'label': 'الموقع والخرائط'},
    {'key': 'land_croquis', 'label': 'الأرض والكروكي'},
    {'key': 'contact', 'label': 'بيانات التواصل'},
]

DEFAULT_FIELD_SECTIONS = {s['key']: True for s in FIELD_SECTIONS}

REMOVED_PREBUILT_FIELDS = {
    'land_image_file', 'regulation_reference_file', 'croquis_file', 'building_permit_file',
    'north_direction', 'croquis_expiry_date', 'subdivision_number',
    'project_goal', 'initial_features', 'initial_strengths',
    'building_ratio_setbacks', 'allowed_uses_restrictions',
}

PREBUILT_FIELDS = [
    {'key': 'project_name', 'label': 'اسم المشروع', 'type': 'text', 'required': True, 'section_key': 'basic', 'ai_hint': 'اسم المشروع الرئيسي', 'sort_order': 1},
    {'key': 'project_type', 'label': 'نوع المشروع الرئيسي', 'type': 'select', 'options': ['سكني', 'تجاري', 'فندقي', 'صناعي ولوجستي'], 'required': True, 'section_key': 'basic', 'ai_hint': 'نوع أو أكثر من الأنواع الرئيسية للمشروع حسب دراسة السوق', 'sort_order': 2},
    {'key': 'project_mixed_components', 'label': 'أنواع المشروع متعدد الاستخدامات', 'type': 'text', 'required': False, 'section_key': 'basic', 'ai_hint': 'الأنواع الرئيسية داخل مشروع متعدد الاستخدامات', 'sort_order': 3},
    {'key': 'project_subtype', 'label': 'الأنواع الفرعية للمشروع', 'type': 'textarea', 'options': [], 'required': False, 'section_key': 'basic', 'ai_hint': 'اختيار نوع فرعي واحد أو أكثر حسب النوع الرئيسي', 'sort_order': 4},
    {'key': 'activity_class', 'label': 'تصنيف النشاط', 'type': 'select', 'options': [], 'required': False, 'section_key': 'basic', 'ai_hint': '', 'sort_order': 5},
    {'key': 'project_idea', 'label': 'فكرة المشروع', 'type': 'textarea', 'required': False, 'section_key': 'basic', 'ai_hint': 'فكرة المشروع كما يدخلها العميل يدويًا', 'sort_order': 6},
    {'key': 'project_level', 'label': 'مستوى المشروع', 'type': 'select', 'options': ['اقتصادي', 'متوسط', 'فوق المتوسط', 'متميز', 'فاخر', 'فائق الفخامة', 'أخرى'], 'required': False, 'section_key': 'basic', 'ai_hint': '', 'sort_order': 7},
    {'key': 'target_audience', 'label': 'الفئة المستهدفة', 'type': 'textarea', 'required': False, 'section_key': 'basic', 'ai_hint': 'الفئة المستهدفة متعددة الاختيارات وتتغير حسب نوع المشروع', 'sort_order': 8},
    {'key': 'project_stage', 'label': 'مرحلة المشروع الحالية', 'type': 'select', 'options': ['فكرة أولية', 'فرصة استثمارية', 'دراسة جدوى', 'تصميم', 'تحت التنفيذ', 'قائم لإعادة التطوير', 'أخرى'], 'required': False, 'section_key': 'basic', 'ai_hint': 'المرحلة الحالية التي يمر بها المشروع', 'sort_order': 9},
    {'key': 'project_logo', 'label': 'شعار المشروع (Logo)', 'type': 'image', 'required': False, 'section_key': 'basic', 'ai_hint': 'صورة شعار المشروع', 'sort_order': 10},
    {'key': 'location_address', 'label': 'رابط موقع الأرض في Google Maps', 'type': 'text', 'required': True, 'section_key': 'location', 'ai_hint': 'رابط Google Maps مباشر لنقطة الأرض؛ يستخدم لتحديد الإحداثيات والبيانات المكانية والاشتراطات المرتبطة بالموقع', 'sort_order': 11},
    {'key': 'land_documents_files', 'label': 'رفع رخصة البناء والكروكي أو المستندات (ملفان كحد أقصى)', 'type': 'file', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ارفع ملف رخصة البناء وملف الكروكي معًا ليتم تحليلهما في طلب AI واحد', 'sort_order': 11},
    {'key': 'plot_number_croquis', 'label': 'رقم القطعة', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم قطعة الأرض وحده بدون رقم المخطط أو القسم', 'sort_order': 12},
    {'key': 'plan_number', 'label': 'رقم المخطط', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم المخطط وحده كما هو في الصك أو الكروكي', 'sort_order': 13},
    {'key': 'deed_number', 'label': 'رقم الصك أو المرجع', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم صك الملكية أو المرجع الرسمي', 'sort_order': 14},
    {'key': 'deed_date', 'label': 'تاريخ الصك', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'تاريخ إصدار الصك كما هو مكتوب (هجري أو ميلادي) — ليس تاريخ الكروكي', 'sort_order': 15},
    {'key': 'croquis_land_area', 'label': 'مساحة الأرض حسب الكروكي (م²)', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'المساحة الإجمالية للأرض بالمتر المربع حسب الكروكي', 'sort_order': 16},
    {'key': 'approved_financial_area', 'label': 'المساحة المعتمدة للدراسة المالية (م²)', 'placeholder': 'يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يكتبها العميل فقط بعد أي استقطاعات — AI ممنوع من تعبئتها أو تعديلها', 'sort_order': 17},
    {'key': 'boundary_lengths', 'label': 'أطوال الأضلاع وحدود الأرض', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ملخص مشتق من جدول الاتجاهات — لا تُعد كتابته يدويًا إن كان الجدول مكتملًا', 'sort_order': 18},
    {'key': 'surrounding_streets', 'label': 'الشوارع المحيطة وعروضها', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ملخص مشتق من جدول الاتجاهات — أسماء الشوارع وعروضها', 'sort_order': 19},
    {'key': 'facades_count', 'label': 'عدد الواجهات المطلة على شوارع', 'type': 'number', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'عدد الحدود المطلة على شوارع فقط (1 إلى 4) — الحد المجاور لقطعة ليس واجهة', 'sort_order': 20},
    {'key': 'facades_directions', 'label': 'اتجاهات الواجهات المطلة على شوارع', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'اتجاهات الحدود المطلة على شوارع فقط (مثل: شمالية، غربية) — لا تُكتب الاتجاهات الأربعة إلا إن كانت مطلة على أربعة شوارع', 'sort_order': 21},
    {'key': 'building_ratio_coverage', 'label': 'نسبة البناء والتغطية', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI من ملفات الأمانة: نسبة البناء، نسبة التغطية، FAR، وعدد الأدوار المرتبط بشريحة مساحة الأرض، بدون ذكر أرقام الصفحات', 'sort_order': 22},
    {'key': 'setbacks', 'label': 'الارتدادات', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI من ملفات الأمانة: الارتداد الأمامي والخلفي والجانبيان، أو يوضح أنها غير محددة في المرجع المتاح، بدون ذكر أرقام الصفحات', 'sort_order': 23},
    {'key': 'max_floors_height', 'label': 'الارتفاع أو عدد الأدوار المسموح', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'عدد الأدوار المسموح بها أو الحد الأقصى للارتفاع بالمتر، مع شرح شريحة الأرض إن وجدت', 'sort_order': 24},
    {'key': 'approved_floor_count', 'label': 'الأدوار المعتمدة', 'placeholder': 'يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'عدد الأدوار الفعلي الذي يعتمده العميل للمبنى — يكتبه العميل فقط ولا يملؤه AI', 'sort_order': 25},
    {'key': 'approved_coverage_ratio', 'label': 'التغطية المعتمدة (%)', 'placeholder': 'يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'نسبة التغطية التي يعتمدها العميل للدراسة المالية — يكتبها العميل فقط ولا يملؤها AI', 'sort_order': 26},
    {'key': 'allowed_uses', 'label': 'الاستخدامات المسموحة', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'قائمة الاستخدامات المسموحة تنظيميًا لهذه الأرض من ملفات الأمانة وجدول التنظيم، بدون كتابة حالة السماح داخل الحقل', 'sort_order': 27},
    {'key': 'regulatory_constraints', 'label': 'القيود التنظيمية', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'القيود التنظيمية المنطبقة على الموقع والمشروع، بما فيها المواقف والمداخل والمخارج والتحميل والخدمات، بدون ذكر أرقام الصفحات', 'sort_order': 28},
    {'key': 'land_photos', 'label': 'صور الأرض (حتى 4 صور — اختياري)', 'type': 'file', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'صور فوتوغرافية للأرض من العميل مع وصف لكل صورة (لا يحللها AI)', 'sort_order': 29},
    {'key': 'land_and_building_summary', 'label': 'ملخص بيانات الأرض والاشتراطات', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI كملخص موثق من ملفات الأمانة يشمل الارتدادات، الاستخدامات، القيود، المواقف، المداخل والمخارج، الفرص، المخاطر والتعارضات، بدون الإحالة إلى أرقام صفحات أو أماكن داخل الملفات', 'sort_order': 30},
    {'key': 'location_lat', 'label': 'خط العرض (Latitude)', 'type': 'text', 'section_key': 'location', 'ai_hint': 'خط العرض للموقع (إختياري)', 'sort_order': 31},
    {'key': 'location_lng', 'label': 'خط الطول (Longitude)', 'type': 'text', 'section_key': 'location', 'ai_hint': 'خط الطول للموقع (إختياري)', 'sort_order': 32},
    {'key': 'city', 'label': 'المدينة', 'type': 'text', 'section_key': 'location', 'ai_hint': 'المدينة المستخرجة تلقائيًا من رابط الموقع والخرائط — لا يكتبها العميل يدويًا', 'sort_order': 33},
    {'key': 'district', 'label': 'الحي', 'type': 'text', 'section_key': 'location', 'ai_hint': 'الحي المستخرج تلقائيًا من رابط الموقع والخرائط — لا يكتبه العميل يدويًا', 'sort_order': 34},
    {'key': 'plot_number', 'label': 'رقم المخطط / القطعة', 'type': 'text', 'section_key': 'location', 'ai_hint': 'رقم المخطط أو القطعة', 'sort_order': 35},
    {'key': 'land_area', 'label': 'مساحة الأرض', 'type': 'text', 'section_key': 'location', 'ai_hint': 'مساحة الأرض بالمتر المربع', 'sort_order': 36},
    {'key': 'built_area', 'label': 'مساحة البناء', 'type': 'text', 'section_key': 'location', 'ai_hint': 'مساحة البناء بالمتر المربع', 'sort_order': 37},
    {'key': 'building_system', 'label': 'نظام البناء', 'type': 'text', 'section_key': 'location', 'ai_hint': 'نظام البناء والارتفاعات المسموح بها', 'sort_order': 38},
    {'key': 'infrastructure', 'label': 'البنية التحتية', 'type': 'text', 'section_key': 'location', 'ai_hint': 'مياه، كهرباء، اتصالات، إلخ', 'sort_order': 39},
    {'key': 'main_roads', 'label': 'الطرق الرئيسية المحيطة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'أسماء الطرق الرئيسية المحيطة بالمشروع وتمثل طرق الوصول إليه', 'sort_order': 40},
    {'key': 'secondary_roads', 'label': 'طرق الوصول الفرعية', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'المداخل وطرق الوصول الفرعية مع المسافة ومدة القيادة', 'sort_order': 41},
    {'key': 'nearby_landmarks', 'label': 'أهم المعالم القريبة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'قائمة المعالم القريبة مع أوقات القيادة (مثلاً: ميدان السارية - 1 دقيقة)', 'sort_order': 42},
    {'key': 'city_landmarks', 'label': 'المعالم الرئيسية في المدينة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'أهم المعالم الرئيسية في المدينة والمناطق المحيطة', 'sort_order': 43},
    {'key': 'catchment_areas', 'label': 'مناطق نطاق التأثير', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'المناطق الرئيسية والثانوية المتأثرة بالمشروع', 'sort_order': 44},
    {'key': 'location_data_fetched_at', 'label': 'وقت آخر تحديث بيانات الموقع', 'type': 'text', 'section_key': 'location', 'ai_hint': 'وقت آخر جلب لبيانات الموقع والمعالم بتوقيت السعودية', 'sort_order': 44},
    {'key': 'contact_name', 'label': 'الاسم', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'اسم مسؤول التواصل بالمشروع', 'sort_order': 45},
    {'key': 'contact_position', 'label': 'المنصب', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'المسمى الوظيفي أو المنصب لمسؤول التواصل', 'sort_order': 46},
    {'key': 'contact_email', 'label': 'البريد الإلكتروني', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'البريد الإلكتروني للتواصل', 'sort_order': 47},
    {'key': 'contact_phone', 'label': 'الهاتف', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'رقم هاتف أو جوال التواصل', 'sort_order': 48},
    {'key': 'contact_website', 'label': 'الموقع الإلكتروني', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'رابط الموقع الإلكتروني الرسمي', 'sort_order': 49},
    {'key': 'contact_address', 'label': 'الموقع الجغرافي', 'type': 'text', 'required': False, 'section_key': 'contact', 'ai_hint': 'العنوان الجغرافي أو المقر الرئيسي', 'sort_order': 50},
    {'key': 'contact_social_media', 'label': 'السوشل ميديا (X, LinkedIn, Instagram, TikTok)', 'type': 'textarea', 'required': False, 'section_key': 'contact', 'ai_hint': 'حسابات التواصل الاجتماعي للمشروع أو الشركة', 'sort_order': 51},
]


def _seed_default_fields(conn, tenant_id):
    """Seed pre-built fields for a new tenant (all active by default)."""
    for f in PREBUILT_FIELDS:
        field_id = str(uuid.uuid4())
        conn.execute(
            'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)',
            (
                field_id, tenant_id, f['key'], f['label'], f['type'],
                json.dumps(f.get('options', []), ensure_ascii=False) if f.get('options') else None,
                f.get('section_key', 'general'),
                1 if f.get('required') else 0,
                1, f.get('sort_order', 0), f.get('ai_hint', '')
            )
        )


def _migrate_location_fields(conn):
    """Add missing pre-built location fields to existing tenants and update prebuilt options."""
    existing_tenants = [row['id'] for row in conn.execute('SELECT id FROM tenants').fetchall()]
    for tenant_id in existing_tenants:
        existing_rows = {
            row['field_key']: row for row in
            conn.execute('SELECT id, field_key, section_key, field_options FROM tenant_input_fields WHERE tenant_id = ?', (tenant_id,)).fetchall()
        }
        if REMOVED_PREBUILT_FIELDS:
            placeholders = ','.join('?' for _ in REMOVED_PREBUILT_FIELDS)
            conn.execute(
                f'UPDATE tenant_input_fields SET is_active = 0 WHERE tenant_id = ? AND field_key IN ({placeholders})',
                [tenant_id, *sorted(REMOVED_PREBUILT_FIELDS)]
            )
        for f in PREBUILT_FIELDS:
            opts_json = json.dumps(f.get('options', []), ensure_ascii=False) if f.get('options') else None
            if f['key'] in existing_rows:
                row_id = existing_rows[f['key']]['id']
                conn.execute(
                    'UPDATE tenant_input_fields SET field_options = ?, section_key = ?, field_label = ?, field_type = ?, sort_order = ?, is_active = 1 WHERE id = ?',
                    (opts_json, f.get('section_key', 'general'), f['label'], f['type'], f.get('sort_order', 0), row_id)
                )
                continue
            field_id = str(uuid.uuid4())
            conn.execute(
                'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)',
                (
                    field_id, tenant_id, f['key'], f['label'], f['type'],
                    opts_json,
                    f.get('section_key', 'general'),
                    1 if f.get('required') else 0,
                    f.get('sort_order', 0), f.get('ai_hint', '')
                )
            )
            print(f'[DB] Migration: added field {f["key"]} to tenant {tenant_id}')
    conn.commit()


def ensure_tenant_prebuilt_fields_active(tenant_id):
    """Re-sync the prebuilt field definitions onto a tenant.

    This runs on every /api/fields call, which is every time the project form opens. It used to
    issue one UPDATE per prebuilt field unconditionally — 39 writes and a commit on every load,
    none of which changed anything in the normal case. It now compares first and writes only what
    actually differs, so a steady-state call performs a single SELECT and no transaction at all.
    """
    if not tenant_id:
        return
    conn = get_db()
    existing_rows = {
        row['field_key']: row for row in
        conn.execute(
            'SELECT id, field_key, field_label, field_type, field_options, section_key, sort_order,'
            ' is_active FROM tenant_input_fields WHERE tenant_id = ?', (tenant_id,)
        ).fetchall()
    }
    dirty = False

    if REMOVED_PREBUILT_FIELDS:
        stale = [key for key in sorted(REMOVED_PREBUILT_FIELDS)
                 if key in existing_rows and existing_rows[key]['is_active']]
        if stale:
            placeholders = ','.join('?' for _ in stale)
            conn.execute(
                f'UPDATE tenant_input_fields SET is_active = 0 WHERE tenant_id = ? AND field_key IN ({placeholders})',
                [tenant_id, *stale]
            )
            dirty = True

    for f in PREBUILT_FIELDS:
        opts_json = json.dumps(f.get('options', []), ensure_ascii=False) if f.get('options') else None
        section = f.get('section_key', 'general')
        order = f.get('sort_order', 0)
        row = existing_rows.get(f['key'])
        if row is None:
            conn.execute(
                'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?)',
                (
                    str(uuid.uuid4()), tenant_id, f['key'], f['label'], f['type'],
                    opts_json, section,
                    1 if f.get('required') else 0,
                    order, f.get('ai_hint', '')
                )
            )
            print(f'[DB] Migration: added field {f["key"]} to tenant {tenant_id}')
            dirty = True
            continue
        unchanged = (
            row['field_label'] == f['label']
            and row['field_type'] == f['type']
            and (row['field_options'] or None) == opts_json
            and row['section_key'] == section
            and (row['sort_order'] or 0) == order
            and row['is_active']
        )
        if unchanged:
            continue
        conn.execute(
            'UPDATE tenant_input_fields SET field_options = ?, section_key = ?, field_label = ?, field_type = ?, sort_order = ?, is_active = 1 WHERE id = ?',
            (opts_json, section, f['label'], f['type'], order, row['id'])
        )
        dirty = True

    if dirty:
        conn.commit()


def _migrate_font_system(conn):
    """Create central SAG font registry and tenant font overrides."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sag_fonts (
        id TEXT PRIMARY KEY,
        font_name TEXT NOT NULL,
        font_family TEXT NOT NULL,
        script TEXT NOT NULL,
        weight TEXT NOT NULL,
        style TEXT DEFAULT 'normal',
        source_type TEXT NOT NULL DEFAULT 'preset',
        source_data TEXT,
        file_data TEXT,
        is_active INTEGER DEFAULT 1,
        is_default INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS tenant_font_selections (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        script TEXT NOT NULL,
        weight TEXT NOT NULL,
        font_id TEXT REFERENCES sag_fonts(id) ON DELETE SET NULL,
        custom_font_path TEXT,
        custom_font_data TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(tenant_id, script, weight)
    );
    CREATE INDEX IF NOT EXISTS idx_sag_fonts_script_weight ON sag_fonts(script, weight);
    CREATE INDEX IF NOT EXISTS idx_tenant_font_selections_tenant ON tenant_font_selections(tenant_id);
    """)
    defaults = [
        ('sag-default-arabic-regular', 'The Sans Arabic', 'The Sans Arabic', 'arabic', 'regular'),
        ('sag-default-arabic-bold', 'The Sans Arabic Bold', 'The Sans Arabic', 'arabic', 'bold'),
        ('sag-default-latin-regular', 'Arial', 'Arial', 'latin', 'regular'),
        ('sag-default-latin-bold', 'Arial Bold', 'Arial', 'latin', 'bold'),
    ]
    for font_id, name, family, script, weight in defaults:
        conn.execute(
            """INSERT OR IGNORE INTO sag_fonts
               (id, font_name, font_family, script, weight, source_type, source_data, is_active, is_default)
               VALUES (?, ?, ?, ?, ?, 'preset', ?, 1, 1)""",
            (font_id, name, family, script, weight, family),
        )
    conn.commit()


def get_sag_fonts(script=None, weight=None, active_only=True):
    conn = get_db()
    query = 'SELECT id, font_name, font_family, script, weight, style, source_type, source_data, is_active, is_default, created_at, updated_at FROM sag_fonts WHERE 1=1'
    params = []
    if active_only:
        query += ' AND is_active = 1'
    if script:
        query += ' AND script = ?'
        params.append(script)
    if weight:
        query += ' AND weight = ?'
        params.append(weight)
    query += ' ORDER BY script, weight, is_default DESC, font_name'
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_sag_font(font_id):
    row = get_db().execute('SELECT * FROM sag_fonts WHERE id = ?', (font_id,)).fetchone()
    return dict(row) if row else None


def create_sag_font(font_name, font_family, script, weight, style='normal', source_type='uploaded', source_data=None, file_data=None):
    font_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        '''INSERT INTO sag_fonts
           (id, font_name, font_family, script, weight, style, source_type, source_data, file_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (font_id, font_name, font_family, script, weight, style, source_type, source_data, file_data),
    )
    conn.commit()
    return font_id


def update_sag_font(font_id, **fields):
    allowed = {'font_name', 'font_family', 'is_active', 'is_default'}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return False
    if updates.get('is_default'):
        current = get_sag_font(font_id)
        if current:
            get_db().execute(
                'UPDATE sag_fonts SET is_default = 0 WHERE script = ? AND weight = ?',
                (current['script'], current['weight']),
            )
    updates['updated_at'] = _utcnow().isoformat()
    clause = ', '.join(f'{key} = ?' for key in updates)
    get_db().execute(f'UPDATE sag_fonts SET {clause} WHERE id = ?', list(updates.values()) + [font_id])
    get_db().commit()
    return True


def get_tenant_font_selections(tenant_id):
    rows = get_db().execute(
        'SELECT * FROM tenant_font_selections WHERE tenant_id = ? ORDER BY script, weight',
        (tenant_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_tenant_font_selection(tenant_id, script, weight):
    row = get_db().execute(
        'SELECT * FROM tenant_font_selections WHERE tenant_id = ? AND script = ? AND weight = ?',
        (tenant_id, script, weight),
    ).fetchone()
    return dict(row) if row else None


def set_tenant_font_selection(tenant_id, script, weight, font_id=None, custom_font_path=None, custom_font_data=None):
    selection_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    get_db().execute(
        '''INSERT INTO tenant_font_selections
           (id, tenant_id, script, weight, font_id, custom_font_path, custom_font_data, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, script, weight) DO UPDATE SET
           font_id = excluded.font_id,
           custom_font_path = excluded.custom_font_path,
           custom_font_data = excluded.custom_font_data,
           updated_at = excluded.updated_at''',
        (selection_id, tenant_id, script, weight, font_id, custom_font_path, custom_font_data, now, now),
    )
    get_db().commit()
    return selection_id


def delete_tenant_font_selection(tenant_id, script, weight):
    get_db().execute(
        'DELETE FROM tenant_font_selections WHERE tenant_id = ? AND script = ? AND weight = ?',
        (tenant_id, script, weight),
    )
    get_db().commit()


def _migrate_field_sections(conn):
    """Set section_key for existing pre-built fields without one."""
    section_map = {f['key']: f.get('section_key', 'general') for f in PREBUILT_FIELDS}
    rows = conn.execute('SELECT id, field_key FROM tenant_input_fields WHERE section_key IS NULL OR section_key = \'general\'').fetchall()
    for row in rows:
        key = row['field_key']
        if key in section_map:
            conn.execute(
                'UPDATE tenant_input_fields SET section_key = ? WHERE id = ?',
                (section_map[key], row['id'])
            )
    conn.commit()


def get_fields(tenant_id, active_only=True):
    """Get all input fields for a tenant."""
    conn = get_db()
    if active_only:
        rows = conn.execute(
            'SELECT * FROM tenant_input_fields WHERE tenant_id = ? AND is_active = 1 ORDER BY sort_order, created_at',
            (tenant_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM tenant_input_fields WHERE tenant_id = ? ORDER BY sort_order, created_at',
            (tenant_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_field_by_id(field_id):
    """Get a single field by ID."""
    conn = get_db()
    row = conn.execute('SELECT * FROM tenant_input_fields WHERE id = ?', (field_id,)).fetchone()
    return dict(row) if row else None


def _normalize_options_list(val):
    if not val:
        return []
    if isinstance(val, list):
        res = []
        for item in val:
            if isinstance(item, str):
                parts = [p.strip() for p in re.split(r'[,،;\n]+', item) if p.strip()]
                res.extend(parts)
            elif item is not None:
                res.append(str(item).strip())
        return [r for r in res if r]
    if isinstance(val, str):
        val_str = val.strip()
        if val_str.startswith('[') and val_str.endswith(']'):
            try:
                parsed = json.loads(val_str)
                if isinstance(parsed, list):
                    return _normalize_options_list(parsed)
            except Exception:
                pass
        return [p.strip() for p in re.split(r'[,،;\n]+', val_str) if p.strip()]
    return []


def _repair_field_options(conn):
    """Repair existing custom fields that have unparsed options or missing select type."""
    try:
        rows = conn.execute("SELECT id, field_type, field_options FROM tenant_input_fields WHERE field_options IS NOT NULL AND field_options != ''").fetchall()
        for row in rows:
            field_id = row['id']
            raw_opts = row['field_options']
            parsed_opts = _normalize_options_list(raw_opts)
            if parsed_opts:
                json_str = json.dumps(parsed_opts, ensure_ascii=False)
                if json_str != raw_opts or row['field_type'] != 'select':
                    conn.execute(
                        "UPDATE tenant_input_fields SET field_options = ?, field_type = 'select' WHERE id = ?",
                        (json_str, field_id)
                    )
        conn.commit()
    except Exception as e:
        print(f"[DB REPAIR ERR] {e}")


def _deduplicate_fields(conn):
    """Remove duplicate fields for same tenant that share label, key, or transliteration, keeping the best one."""
    try:
        ar_map = {
            'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
            'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
            'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
            'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
            'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
            ' ': '_', 'ـ': '',
        }

        rows = conn.execute('SELECT * FROM tenant_input_fields WHERE is_custom = 1').fetchall()
        by_group = {}
        for r in rows:
            dict_r = dict(r)
            tid = dict_r['tenant_id']
            key_raw = dict_r['field_key'].strip().lower()
            lbl_raw = dict_r['field_label'].strip().lower()

            lbl_trans = ''.join(ar_map.get(ch, ch) for ch in lbl_raw)
            lbl_trans_clean = re.sub(r'[^a-zA-Z0-9]', '', lbl_trans)
            key_clean = re.sub(r'[^a-zA-Z0-9]', '', key_raw)

            if 'license' in key_clean or 'license' in lbl_trans_clean or 'trkhs' in lbl_trans_clean or 'trkhs' in key_clean or 'ترخيص' in lbl_raw:
                group_id = (tid, 'building_license_status')
            else:
                group_id = (tid, key_clean or lbl_trans_clean)

            by_group.setdefault(group_id, []).append(dict_r)

        for (tid, grp), field_list in by_group.items():
            if len(field_list) > 1:
                best = max(field_list, key=lambda f: (1 if f.get('field_options') and f['field_options'] != '[]' else 0, 1 if f.get('field_type') == 'select' else 0, f.get('created_at') or ''))
                for f in field_list:
                    if f['id'] != best['id']:
                        conn.execute('DELETE FROM tenant_input_fields WHERE id = ?', (f['id'],))

            # Ensure building_license_status field has standard Arabic label & correct 6 options
            if grp == 'building_license_status' and field_list:
                best = max(field_list, key=lambda f: (1 if f.get('field_options') and f['field_options'] != '[]' else 0, 1 if f.get('field_type') == 'select' else 0, f.get('created_at') or ''))
                opts = ["مرخص", "قيد الترخيص", "مرخص جزئياً", "غير مرخص", "مرفوض", "لا يحتاج ترخيص"]
                conn.execute(
                    "UPDATE tenant_input_fields SET field_key = 'building_license_status', field_label = 'حالة ترخيص البناء', field_type = 'select', field_options = ?, section_key = 'compliance' WHERE id = ?",
                    (json.dumps(opts, ensure_ascii=False), best['id'])
                )
        conn.commit()
    except Exception as e:
        print(f"[DB DEDUP ERR] {e}")


def _cleanup_accidental_map_fields(conn):
    """Delete custom fields created accidentally when asking AI to add map slides."""
    try:
        conn.execute("""
            DELETE FROM tenant_input_fields 
            WHERE field_key IN ('khryta_alhy_alkaml', 'khryta_altrq_almhyta') 
               OR field_label LIKE '%خريطة الحي%' 
               OR field_label LIKE '%خريطة الطرق%'
        """)
        conn.commit()
    except Exception as e:
        print(f"[DB CLEANUP ERR] {e}")


def _migrate_map_images_presentation_fk(conn):
    """Remove the presentations FK from map_images so draft_* ids can be cached."""
    try:
        if isinstance(conn, sqlite3.PostgresConnection):
            constraints = conn.execute('''
                SELECT tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = current_schema()
                  AND tc.table_name = 'map_images'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = 'presentation_id'
            ''').fetchall()
            for row in constraints:
                validated = re.fullmatch(r'[A-Za-z0-9_]+', str(row['constraint_name'] or ''))
                if validated:
                    conn.execute(f'ALTER TABLE map_images DROP CONSTRAINT "{validated.group(0)}"')
            conn.commit()
            return
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='map_images'")
        if not cur or not cur.fetchone():
            return
        fks = conn.execute("PRAGMA foreign_key_list(map_images)").fetchall()
        has_fk = any(row['from'] == 'presentation_id' or row[2] == 'presentations' for row in fks)
        if not has_fk:
            return
        conn.executescript("""
            BEGIN TRANSACTION;
            CREATE TABLE map_images_new (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                presentation_id TEXT,
                image_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                placeholder TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO map_images_new SELECT * FROM map_images;
            DROP TABLE map_images;
            ALTER TABLE map_images_new RENAME TO map_images;
            CREATE INDEX IF NOT EXISTS idx_mapimages_tenant ON map_images(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_mapimages_pres ON map_images(presentation_id);
            CREATE INDEX IF NOT EXISTS idx_mapimages_type ON map_images(image_type);
            COMMIT;
        """)
        conn.commit()
        print("[DB MIGRATION] map_images presentation_id foreign key removed")
    except Exception as e:
        print(f"[DB MIGRATION ERR] {e}")


def _migrate_project_draft_columns(conn):
    """Add lightweight list metadata to historical project drafts."""
    try:
        cursor = conn.execute("PRAGMA table_info(project_drafts)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        migrations = {
            'title': "ALTER TABLE project_drafts ADD COLUMN title TEXT",
            'revision': "ALTER TABLE project_drafts ADD COLUMN revision INTEGER DEFAULT 1",
            'data_bytes': "ALTER TABLE project_drafts ADD COLUMN data_bytes INTEGER DEFAULT 0",
            'has_slides': "ALTER TABLE project_drafts ADD COLUMN has_slides INTEGER DEFAULT 0",
            'has_maps': "ALTER TABLE project_drafts ADD COLUMN has_maps INTEGER DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in existing_cols:
                conn.execute(sql)
                print(f"[DB MIGRATION] Added project draft column: {column}")
        conn.execute("""
            UPDATE project_drafts
            SET title = COALESCE(NULLIF(title, ''), 'مسودة مشروع بدون عنوان'),
                revision = COALESCE(revision, 1),
                data_bytes = CASE WHEN COALESCE(data_bytes, 0) = 0 THEN length(COALESCE(draft_data, '')) ELSE data_bytes END,
                has_slides = CASE WHEN COALESCE(draft_data, '') LIKE '%tenantSlidesData%' THEN 1 ELSE COALESCE(has_slides, 0) END,
                has_maps = CASE WHEN COALESCE(draft_data, '') LIKE '%map_placeholders%' THEN 1 ELSE COALESCE(has_maps, 0) END
        """)
        conn.commit()
    except Exception as e:
        print(f"[DB DRAFT MIGRATION ERR] {e}")


def _migrate_generation_approval_columns(conn):
    """Add the lifecycle bookkeeping column to historical generation approvals."""
    try:
        cursor = conn.execute("PRAGMA table_info(generation_approvals)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        if 'prior_status' not in existing_cols:
            conn.execute("ALTER TABLE generation_approvals ADD COLUMN prior_status TEXT")
            print("[DB MIGRATION] Added generation_approvals column: prior_status")
        conn.commit()
    except Exception as e:
        print(f"[DB GENERATION MIGRATION ERR] {e}")


def _migrate_point_reservation_columns(conn):
    """Add expiry + the one-active-hold-per-operation index to older DBs."""
    try:
        cursor = conn.execute("PRAGMA table_info(point_reservations)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        if 'expires_at' not in existing_cols:
            conn.execute("ALTER TABLE point_reservations ADD COLUMN expires_at TEXT")
            print("[DB MIGRATION] Added point_reservations column: expires_at")
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS uq_point_reservations_active_op
                        ON point_reservations(generation_approval_id) WHERE status = 'reserved' ''')
        conn.commit()
    except Exception as e:
        print(f"[DB RESERVATION MIGRATION ERR] {e}")


def _migrate_workflow_gate_columns(conn):
    """Columns for the file-gate / generation / archive workflow requirements."""
    additions = (
        ('generation_approvals', (('input_snapshot', 'TEXT'),)),
        ('generation_jobs', (('heartbeat_at', 'TEXT'),)),
        ('final_file_approvals', (('request_hash', 'TEXT'), ('stamped_export_id', 'TEXT'))),
        ('presentation_downloads', (('export_id', 'TEXT'),)),
        ('exports', (('content_hash', 'TEXT'), ('regen_policy', 'TEXT'), ('cost_usd', 'REAL DEFAULT 0'))),
        ('project_drafts', (('archived_at', 'TEXT'),)),
        ('presentations', (('archived_at', 'TEXT'),)),
        ('section_versions', (('expires_at', 'TEXT'),)),
        ('tenant_branding', (('section_approval_days', 'INTEGER'),)),
        ('tenant_ledger', (('actor', 'TEXT'), ('reversal_of', 'TEXT'))),
    )
    try:
        for table, cols in additions:
            existing = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
            for name, definition in cols:
                if name not in existing:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
                    print(f"[DB MIGRATION] Added {table} column: {name}")
        conn.commit()
    except Exception as e:
        print(f"[DB WORKFLOW GATE MIGRATION ERR] {e}")


def _migrate_presentation_revision_schema(conn):
    """Add full snapshots without rewriting historical slides-only backups.

    Run before unrelated optional migrations. Introspection works through the
    SQLite/Postgres shim and avoids failed ALTERs aborting Postgres transactions.
    Revision zero denotes an existing identity whose baseline is captured lazily
    under the same write lock as its first revision-aware save.
    """
    for table, additions in (
        ('presentations', (('revision', 'INTEGER NOT NULL DEFAULT 0'),
                           ('current_revision_id', 'TEXT'), ('creation_key', 'TEXT'))),
        ('change_log', (('revision_id', 'TEXT'), ('previous_revision_id', 'TEXT'))),
    ):
        columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        for name, definition in additions:
            if name not in columns:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS presentation_revisions (
        id TEXT PRIMARY KEY,
        presentation_id TEXT NOT NULL REFERENCES presentations(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL,
        title TEXT NOT NULL,
        project_data TEXT,
        slides_data TEXT,
        slide_count INTEGER NOT NULL,
        draft_id TEXT,
        status TEXT,
        content_hash TEXT NOT NULL,
        user_id TEXT,
        user_name TEXT,
        source TEXT NOT NULL,
        action TEXT NOT NULL,
        summary TEXT NOT NULL,
        details TEXT NOT NULL,
        previous_revision_id TEXT,
        restored_from_revision_id TEXT,
        change_log_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (presentation_id, revision)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_changelog_revision ON change_log(revision_id)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_presentation_creation_key ON presentations(tenant_id, creation_key)')


def _migrate_presentation_draft_link(conn):
    try:
        cursor = conn.execute("PRAGMA table_info(presentations)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        if 'draft_id' not in existing_cols:
            conn.execute("ALTER TABLE presentations ADD COLUMN draft_id TEXT")
            print("[DB MIGRATION] Added presentation draft link")
        rows = conn.execute(
            "SELECT id, project_data FROM presentations WHERE draft_id IS NULL OR draft_id = ''"
        ).fetchall()
        for row in rows:
            try:
                project_data = json.loads(row['project_data'] or '{}')
            except (TypeError, ValueError):
                project_data = {}
            draft_id = project_data.get('draftId') or project_data.get('draft_id') if isinstance(project_data, dict) else None
            if draft_id:
                conn.execute('UPDATE presentations SET draft_id = ? WHERE id = ?', (str(draft_id), row['id']))
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_presentations_tenant_draft '
            'ON presentations(tenant_id, draft_id, updated_at)'
        )
        conn.commit()
    except Exception as e:
        print(f"[DB PRESENTATION MIGRATION ERR] {e}")


def _migrate_project_file_table(conn):
    """Create the project file registry for document uploads on older databases."""
    try:
        conn.execute('''
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
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_files_tenant ON project_files(tenant_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_files_draft ON project_files(tenant_id, draft_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_files_hash ON project_files(tenant_id, sha256)')
        conn.commit()
    except Exception as e:
        print(f"[DB FILE MIGRATION ERR] {e}")


def _migrate_branding_columns(conn):
    """Add new columns to tenant_branding if they don't exist."""
    try:
        cursor = conn.execute("PRAGMA table_info(tenant_branding)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        migrations = {
            'default_slide_count': "ALTER TABLE tenant_branding ADD COLUMN default_slide_count INTEGER DEFAULT 16",
            'lock_slide_count': "ALTER TABLE tenant_branding ADD COLUMN lock_slide_count INTEGER DEFAULT 0",
            'min_slides': "ALTER TABLE tenant_branding ADD COLUMN min_slides INTEGER DEFAULT 8",
            'max_slides': "ALTER TABLE tenant_branding ADD COLUMN max_slides INTEGER DEFAULT 30",
            'default_map_type': "ALTER TABLE tenant_branding ADD COLUMN default_map_type TEXT DEFAULT 'satellite'",
            'moodboard_count': "ALTER TABLE tenant_branding ADD COLUMN moodboard_count INTEGER DEFAULT 4",
            'map_style_overview': "ALTER TABLE tenant_branding ADD COLUMN map_style_overview TEXT DEFAULT 'satellite'",
            'map_style_landmarks': "ALTER TABLE tenant_branding ADD COLUMN map_style_landmarks TEXT DEFAULT 'satellite'",
            'map_style_access': "ALTER TABLE tenant_branding ADD COLUMN map_style_access TEXT DEFAULT 'satellite'",
            'map_style_catchment': "ALTER TABLE tenant_branding ADD COLUMN map_style_catchment TEXT DEFAULT 'satellite'",
            'draw_compass': "ALTER TABLE tenant_branding ADD COLUMN draw_compass INTEGER DEFAULT 1",
            'draw_inset': "ALTER TABLE tenant_branding ADD COLUMN draw_inset INTEGER DEFAULT 1",
            'font_file_path': "ALTER TABLE tenant_branding ADD COLUMN font_file_path TEXT",
            'font_file_data': "ALTER TABLE tenant_branding ADD COLUMN font_file_data TEXT",
            'generation_rules': "ALTER TABLE tenant_branding ADD COLUMN generation_rules TEXT",
            'watermark_path': "ALTER TABLE tenant_branding ADD COLUMN watermark_path TEXT",
        }
        for col, sql in migrations.items():
            if col not in existing_cols:
                conn.execute(sql)
                print(f"[DB MIGRATION] Added column: {col}")
        # Fix rows created during the brief window when lock_slide_count defaulted to 1.
        conn.execute('UPDATE tenant_branding SET lock_slide_count = 0 WHERE lock_slide_count = 1')
        conn.commit()
    except Exception as e:
        print(f"[DB MIGRATION ERR] {e}")


def add_custom_field(tenant_id, field_key, field_label, field_type, field_options=None,
                     is_required=False, placeholder=None, default_value=None, ai_hint=None, sort_order=100, section_key='general'):
    """Add or update a custom field for a tenant."""
    conn = get_db()
    norm_opts = _normalize_options_list(field_options)
    if norm_opts:
        field_type = 'select'
        opts_json = json.dumps(norm_opts, ensure_ascii=False)
    else:
        opts_json = json.dumps(field_options, ensure_ascii=False) if field_options else None

    # Check if a field with same tenant_id and field_key OR same field_label exists
    existing = conn.execute(
        'SELECT id, field_options FROM tenant_input_fields WHERE tenant_id = ? AND (field_key = ? OR LOWER(TRIM(field_label)) = LOWER(TRIM(?)))',
        (tenant_id, field_key, field_label)
    ).fetchone()

    if existing:
        field_id = existing['id']
        if not opts_json and existing['field_options']:
            opts_json = existing['field_options']
            try:
                if json.loads(opts_json):
                    field_type = 'select'
            except Exception:
                pass

        conn.execute(
            'UPDATE tenant_input_fields SET field_key = ?, field_label = ?, field_type = ?, field_options = ?, section_key = ?, is_required = ?, is_active = 1, placeholder = ?, default_value = ?, ai_hint = ? WHERE id = ?',
            (
                field_key, field_label, field_type, opts_json, section_key,
                1 if is_required else 0, placeholder, default_value, ai_hint, field_id
            )
        )
        conn.commit()
        return field_id

    field_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO tenant_input_fields (id, tenant_id, field_key, field_label, field_type, field_options, section_key, is_required, is_active, is_custom, sort_order, placeholder, default_value, ai_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)',
        (
            field_id, tenant_id, field_key, field_label, field_type,
            opts_json,
            section_key, 1 if is_required else 0, sort_order, placeholder, default_value, ai_hint
        )
    )
    conn.commit()
    return field_id


def update_field(field_id, **fields):
    """Update a field."""
    conn = get_db()
    allowed = {'field_key', 'field_label', 'field_type', 'field_options', 'section_key', 'is_required', 'is_active', 'sort_order', 'placeholder', 'default_value', 'ai_hint'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'field_options' in updates:
        val = updates['field_options']
        norm_opts = _normalize_options_list(val)
        if norm_opts:
            updates['field_options'] = json.dumps(norm_opts, ensure_ascii=False)
            updates['field_type'] = 'select'
        else:
            updates['field_options'] = None

    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [field_id]
    conn.execute(f'UPDATE tenant_input_fields SET {set_clause} WHERE id = ?', values)
    conn.commit()
    return True


def delete_field(field_id):
    """Delete a field."""
    conn = get_db()
    conn.execute('DELETE FROM tenant_input_fields WHERE id = ?', (field_id,))
    conn.commit()


def reorder_fields(tenant_id, field_ids):
    """Reorder fields only when every ID belongs to the tenant."""
    conn = get_db()
    placeholders = ','.join('?' for _ in field_ids)
    if not placeholders:
        return True
    owned = conn.execute(
        f'SELECT id FROM tenant_input_fields WHERE tenant_id = ? AND id IN ({placeholders})',
        [tenant_id, *field_ids]
    ).fetchall()
    if len(owned) != len(set(field_ids)):
        return False
    for index, field_id in enumerate(field_ids, start=1):
        conn.execute(
            'UPDATE tenant_input_fields SET sort_order = ? WHERE id = ? AND tenant_id = ?',
            (index, field_id, tenant_id)
        )
    conn.commit()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Slide Templates CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_slide_templates(tenant_id, active_only=True):
    """Get slide templates for a tenant."""
    conn = get_db()
    if active_only:
        rows = conn.execute(
            'SELECT * FROM tenant_slide_templates WHERE tenant_id = ? AND is_active = 1 ORDER BY sort_order',
            (tenant_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM tenant_slide_templates WHERE tenant_id = ? ORDER BY sort_order',
            (tenant_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def add_slide_template(tenant_id, slide_type, slide_name, design_instructions=None, sort_order=0):
    """Add a slide template."""
    conn = get_db()
    template_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO tenant_slide_templates (id, tenant_id, slide_type, slide_name, design_instructions, is_active, sort_order) VALUES (?, ?, ?, ?, ?, 1, ?)',
        (template_id, tenant_id, slide_type, slide_name, design_instructions, sort_order)
    )
    conn.commit()
    return template_id


# ─────────────────────────────────────────────────────────────────────────────
# Presentations CRUD
# ─────────────────────────────────────────────────────────────────────────────

_PRESENTATION_UNSET = object()
# Ignore only presentation-independent UI bookkeeping, not project facts/media.
_PRESENTATION_BOOKKEEPING_KEYS = {'designerChat', 'pageDrafts', 'sectionStatuses'}


class PresentationRevisionConflict(Exception):
    """The supplied base revision is stale. No state or history was committed."""

    def __init__(self, expected_revision, current_revision):
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__(f'Presentation revision conflict: expected {expected_revision}, current {current_revision}')


def _presentation_json(value, kind, strict=False):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            if strict:
                raise ValueError(f'Invalid presentation {kind} JSON')
    if value is None:
        value = [] if kind == 'slides_data' else {}
    if strict and not isinstance(value, list if kind == 'slides_data' else dict):
        raise ValueError(f'Invalid presentation {kind}')
    return value


def _presentation_content_hash(state):
    project = _presentation_json(state.get('project_data'), 'project_data')
    if isinstance(project, dict):
        project = {key: value for key, value in project.items() if key not in _PRESENTATION_BOOKKEEPING_KEYS}
    content = [state.get('title'), _presentation_json(state.get('slides_data'), 'slides_data'), project]
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _presentation_revision_metadata(row, legacy=False):
    item = dict(row)
    item['legacy'] = legacy
    item['snapshot_kind'] = 'legacy-slides' if legacy else 'full'
    item['details'] = _json_list(item.get('details'))
    if legacy:
        item.update(revision=None, source='manual', summary='نسخة قديمة للشرائح فقط',
                    previous_revision_id=None, restored_from_revision_id=None,
                    change_log_id=None, title=None, project_data=None, draft_id=None, status=None)
        slides = _presentation_json(item.get('slides_data'), 'slides_data')
        item['slide_count'] = len(slides) if isinstance(slides, list) else 0
    return item


def get_presentation_revisions(presentation_id, tenant_id, limit=200):
    """Tenant-scoped metadata, newest full revisions followed by legacy backups."""
    if not tenant_id:
        return []
    conn = get_db()
    limit = max(1, min(int(limit or 200), 500))
    rows = conn.execute('''SELECT r.id, r.presentation_id, r.revision, r.title, r.slide_count,
        r.user_id, r.user_name, r.source, r.action, r.summary, r.details,
        r.previous_revision_id, r.restored_from_revision_id, r.change_log_id, r.created_at
        FROM presentation_revisions r JOIN presentations p ON p.id = r.presentation_id
        WHERE p.id = ? AND p.tenant_id = ? ORDER BY r.revision DESC LIMIT ?''',
        (presentation_id, tenant_id, limit)).fetchall()
    entries = [_presentation_revision_metadata(row) for row in rows]
    if len(entries) < limit:
        legacy = conn.execute('''SELECT v.* FROM presentation_versions v
            JOIN presentations p ON p.id = v.presentation_id
            WHERE p.id = ? AND p.tenant_id = ? ORDER BY v.created_at DESC, v.id DESC LIMIT ?''',
            (presentation_id, tenant_id, limit - len(entries))).fetchall()
        for row in legacy:
            item = _presentation_revision_metadata(row, legacy=True)
            for key in ('slides_data', 'project_data', 'draft_id', 'status'):
                item.pop(key, None)
            entries.append(item)
    return entries


def get_presentation_revision(presentation_id, version_id, tenant_id):
    """Return immutable full contents or an explicitly labeled slides-only backup.

    JSON columns remain serialized, matching get_presentation()/legacy callers.
    Version IDs are UUIDs, while revision numbers are per-presentation integers.
    """
    if not tenant_id:
        return None
    conn = get_db()
    for table, legacy in (('presentation_revisions', False), ('presentation_versions', True)):
        row = conn.execute(f'''SELECT r.* FROM {table} r
            JOIN presentations p ON p.id = r.presentation_id
            WHERE p.id = ? AND p.tenant_id = ? AND r.id = ?''',
            (presentation_id, tenant_id, version_id)).fetchone()
        if row:
            return _presentation_revision_metadata(row, legacy=legacy)
    return None


def _insert_presentation_revision(conn, state, revision, *, user_id, user_name, source,
                                  action, summary, details, previous_id=None, restored_from=None):
    """Transaction-internal append only. Never calls a committing legacy helper."""
    version_id, change_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = _utcnow().isoformat()
    details_json = json.dumps(details, ensure_ascii=False)
    slides = _presentation_json(state.get('slides_data'), 'slides_data')
    slide_count = len(slides) if isinstance(slides, list) else int(state.get('slide_count') or 0)
    conn.execute('''INSERT INTO presentation_revisions
        (id, presentation_id, revision, title, project_data, slides_data, slide_count,
         draft_id, status, content_hash, user_id, user_name, source, action, summary, details,
         previous_revision_id, restored_from_revision_id, change_log_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (version_id, state['id'], revision, state['title'], state.get('project_data'),
         state.get('slides_data'), slide_count, state.get('draft_id'), state.get('status'),
         _presentation_content_hash(state), user_id, user_name, source, action, summary,
         details_json, previous_id, restored_from, change_id, now))
    conn.execute('''INSERT INTO change_log
        (id, tenant_id, target_type, target_id, user_id, user_name, source, action, summary,
         details, created_at, revision_id, previous_revision_id)
        VALUES (?, ?, 'presentation', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (change_id, state['tenant_id'], state['id'], user_id, user_name, source, action,
         summary, details_json, now, version_id, previous_id))
    return version_id


def _transform_presentation_snapshot(state, transform):
    if transform is None:
        return state
    transformed = transform(dict(state))
    if not isinstance(transformed, dict):
        raise ValueError('snapshot_transform must return a presentation state dict')
    result = dict(state)
    # Asset publication cannot change identity, workflow approval or project linkage.
    for key in ('project_data', 'slides_data'):
        if key in transformed:
            result[key] = json.dumps(_presentation_json(transformed[key], key, strict=True),
                                     ensure_ascii=False, allow_nan=False)
    return result


def commit_presentation_revision(tenant_id, presentation_id=None, *,
                                 title=_PRESENTATION_UNSET, project_data=_PRESENTATION_UNSET,
                                 slides_data=_PRESENTATION_UNSET, draft_id=_PRESENTATION_UNSET,
                                 status=_PRESENTATION_UNSET, expected_revision=None,
                                 user_id=None, user_name=None, source='manual', action='edit',
                                 summary='', details=None, restore_version_id=None,
                                 snapshot_transform=None, creation_key=None):
    """Atomically create/update/restore one identity, full snapshot and readable history.

    Expected revision is an integer (zero for an unversioned legacy identity).
    None is reserved for trusted server/legacy integrations that cannot supply it.
    Stale writes fail even when their content would be a no-op. Restore always
    appends, keeps the current draft link, resets approval, and never edits a draft.
    Ordinary identical saves do not add history, including bookkeeping-only edits.
    All JSON is snapshotted, even ignored bookkeeping. Legacy helpers remain intact.
    snapshot_transform receives a copied raw DB state and returns asset-frozen
    project_data/slides_data (serialized or decoded). It runs on current and next
    states under the write lock and must be deterministic and never commit the DB.
    This helper owns the connection transaction: call without pending writes.
    creation_key is an optional tenant-scoped create idempotency token. Reusing
    it returns the existing current identity unchanged, even after later edits.
    """
    if not tenant_id:
        raise ValueError('tenant_id is required')
    if expected_revision is not None:
        if isinstance(expected_revision, bool) or not str(expected_revision).isdigit():
            raise ValueError('expected_revision must be a nonnegative integer')
        expected_revision = int(expected_revision)
    if source not in CHANGE_SOURCES:
        raise ValueError('Invalid presentation change source')
    created = presentation_id is None
    if creation_key is not None:
        if not created or not isinstance(creation_key, str) or not creation_key.strip() or len(creation_key) > 255:
            raise ValueError('creation_key requires a new identity and a nonempty token up to 255 characters')
    if created and restore_version_id:
        raise ValueError('Restoration requires a presentation identity')
    if created and expected_revision not in (None, 0):
        raise PresentationRevisionConflict(expected_revision, 0)
    conn = get_db()
    try:
        if created:
            presentation_id = str(uuid.uuid4())
            if title is _PRESENTATION_UNSET or not isinstance(title, str) or not title.strip():
                raise ValueError('Presentation title is required')
            inserted = conn.execute('''INSERT INTO presentations (id, tenant_id, title, creation_key)
                VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id, creation_key) DO NOTHING''',
                (presentation_id, tenant_id, title, creation_key))
            if inserted.rowcount == 0:
                existing = dict(conn.execute('SELECT * FROM presentations WHERE tenant_id = ? AND creation_key = ?',
                                             (tenant_id, creation_key)).fetchone())
                conn.commit()
                return {'presentation_id': existing['id'], 'revision': int(existing.get('revision') or 0),
                        'version_id': existing.get('current_revision_id'), 'changed': False,
                        'created': False, 'presentation': existing}
        else:
            # A write before the read serializes writers on SQLite AND Postgres.
            # Unlike read-then-CAS, SQLite cannot fail a read snapshot upgrade here.
            locked = conn.execute('''UPDATE presentations SET revision = revision
                WHERE id = ? AND tenant_id = ?''', (presentation_id, tenant_id))
            if locked.rowcount != 1:
                raise LookupError('Presentation not found')
        current = dict(conn.execute('SELECT * FROM presentations WHERE id = ? AND tenant_id = ?',
                                    (presentation_id, tenant_id)).fetchone())
        revision = int(current.get('revision') or 0)
        if expected_revision is not None and expected_revision != revision:
            raise PresentationRevisionConflict(expected_revision, revision)
        if not created:
            current = _transform_presentation_snapshot(current, snapshot_transform)
        target = None
        if restore_version_id:
            target = get_presentation_revision(presentation_id, restore_version_id, tenant_id)
            if not target:
                raise LookupError('Presentation revision not found')
            # Legacy backups never claimed to store a title or project facts.
            slides_data = target['slides_data']
            title = current['title'] if target['legacy'] else target['title']
            project_data = current['project_data'] if target['legacy'] else target['project_data']
            draft_id, status = current.get('draft_id'), 'draft'
            action = 'restore'
        state = dict(current)
        for key, value in (('title', title), ('project_data', project_data),
                           ('slides_data', slides_data), ('draft_id', draft_id), ('status', status)):
            if value is _PRESENTATION_UNSET:
                continue
            if key in ('slides_data', 'project_data'):
                value = json.dumps(_presentation_json(value, key, strict=True), ensure_ascii=False, allow_nan=False)
            if key == 'title' and (not isinstance(value, str) or not value.strip()):
                raise ValueError('Presentation title is required')
            state[key] = value
        if created and draft_id is _PRESENTATION_UNSET:
            project = _presentation_json(state.get('project_data'), 'project_data', strict=True)
            state['draft_id'] = project.get('draft_id') or project.get('draftId')
        state = _transform_presentation_snapshot(state, snapshot_transform)
        slides = _presentation_json(state.get('slides_data'), 'slides_data', strict=True)
        state['slide_count'] = len(slides)
        changed = created or bool(target) or _presentation_content_hash(current) != _presentation_content_hash(state)
        if changed and not created and status is _PRESENTATION_UNSET and current.get('status') in ('approved', 'pending_approval'):
            state['status'] = 'draft'
        previous_id = current.get('current_revision_id')
        if not created:
            previous = conn.execute('SELECT content_hash FROM presentation_revisions WHERE id = ?',
                                    (previous_id,)).fetchone() if previous_id else None
            # Preserve the actual current state even if an unmigrated legacy caller
            # changed it since the last revision-aware save. Never credit that to this actor.
            if not previous or previous['content_hash'] != _presentation_content_hash(current):
                if previous:
                    revision += 1
                previous_id = _insert_presentation_revision(
                    conn, current, revision, user_id=None, user_name=None, source='system',
                    action='baseline', summary='حفظ الحالة السابقة للعرض', details=[],
                    previous_id=previous_id)
        version_id = previous_id
        if changed:
            revision += 1
            lines = [str(line).strip() for line in (details or []) if str(line or '').strip()]
            if not lines:
                from change_tracking import describe_slide_changes, describe_draft_changes
                lines = describe_slide_changes(
                    _presentation_json(current.get('slides_data'), 'slides_data'), slides)
                lines += describe_draft_changes(
                    _presentation_json(current.get('project_data'), 'project_data'),
                    _presentation_json(state.get('project_data'), 'project_data'))
                if current.get('title') != state['title']:
                    lines.insert(0, f'عنوان العرض: من «{current.get("title") or ""}» إلى «{state["title"]}»')
            summary = str(summary or '').strip() or (
                'استعادة نسخة قديمة للشرائح فقط' if target and target['legacy'] else
                'استعادة مراجعة العرض' if target else 'إنشاء العرض' if created else 'تعديل العرض')
            record_action = action if action not in ('create', 'edit') else ('إنشاء العرض' if created else action)
            version_id = _insert_presentation_revision(
                conn, state, revision, user_id=user_id, user_name=user_name, source=source,
                action=record_action, summary=summary, details=lines,
                previous_id=previous_id, restored_from=restore_version_id)
        # No-op saves may update bookkeeping/status but never mutate a past snapshot.
        updated_at = _utcnow().isoformat() if changed else current.get('updated_at')
        conn.execute('''UPDATE presentations SET title = ?, project_data = ?, slides_data = ?,
            slide_count = ?, draft_id = ?, status = ?, revision = ?, current_revision_id = ?, updated_at = ?
            WHERE id = ? AND tenant_id = ?''',
            (state['title'], state.get('project_data'), state.get('slides_data'), state['slide_count'],
             state.get('draft_id'), state.get('status'), revision, version_id, updated_at,
             presentation_id, tenant_id))
        if created and state.get('draft_id'):
            conn.execute('UPDATE map_images SET presentation_id = ? WHERE tenant_id = ? AND presentation_id = ?',
                         (presentation_id, tenant_id, f"draft_{state['draft_id']}"))
        result = dict(conn.execute('SELECT * FROM presentations WHERE id = ? AND tenant_id = ?',
                                  (presentation_id, tenant_id)).fetchone())
        conn.commit()
        return {'presentation_id': presentation_id, 'revision': revision, 'version_id': version_id,
                'changed': changed, 'created': created, 'presentation': result}
    except Exception:
        conn.rollback()
        raise


def create_presentation(tenant_id, title, project_data=None, slides_data=None, slide_count=0, draft_id=None):
    """Create a new presentation record."""
    conn = get_db()
    pres_id = str(uuid.uuid4())
    if not draft_id and isinstance(project_data, dict):
        draft_id = project_data.get('draft_id') or project_data.get('draftId')
    conn.execute(
        'INSERT INTO presentations (id, tenant_id, title, draft_id, project_data, slides_data, slide_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            pres_id, tenant_id, title, draft_id,
            json.dumps(project_data, ensure_ascii=False) if project_data else None,
            json.dumps(slides_data, ensure_ascii=False) if slides_data else None,
            slide_count
        )
    )
    if project_data and isinstance(project_data, dict):
        draft_id = draft_id or project_data.get('draft_id') or project_data.get('draftId')
        if draft_id:
            conn.execute(
                'UPDATE map_images SET presentation_id = ? WHERE tenant_id = ? AND presentation_id = ?',
                (pres_id, tenant_id, f"draft_{draft_id}")
            )
    conn.commit()
    return pres_id


def get_presentation(pres_id, tenant_id=None):
    """Get a presentation by ID, optionally scoped to a tenant."""
    conn = get_db()
    if tenant_id:
        row = conn.execute('SELECT * FROM presentations WHERE id = ? AND tenant_id = ?', (pres_id, tenant_id)).fetchone()
    else:
        row = conn.execute('SELECT * FROM presentations WHERE id = ?', (pres_id,)).fetchone()
    return dict(row) if row else None


def _presentation_list_clauses(tenant_id, draft_id=None, search='', status='', date_from='', date_to='', accessible_draft_ids=None):
    """Shared WHERE clauses for the presentation list and its total count.

    ``accessible_draft_ids`` limits the list to presentations of drafts the
    caller may reach (t20); presentations with no draft stay visible to all."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(str(draft_id))
    if str(search or '').strip():
        clauses.append('LOWER(title) LIKE ?')
        params.append('%' + str(search).strip().lower() + '%')
    if status == 'draft':
        clauses.append("COALESCE(status, 'draft') IN ('draft', 'edited', 'generated_draft')")
    elif status in {'pending_approval', 'pending'}:
        clauses.append("status IN ('pending_approval', 'final_approval_pending', 'generation_approval_pending', 'section_approval_pending')")
    elif status == 'approved':
        clauses.append("status IN ('approved', 'sections_approved')")
    elif status in PROPOSAL_LIFECYCLE_STATES:
        clauses.append('status = ?')
        params.append(status)
    if date_from:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) >= ?')
        params.append(str(date_from)[:10])
    if date_to:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) <= ?')
        params.append(str(date_to)[:10])
    if accessible_draft_ids is not None:
        ids = [str(i) for i in accessible_draft_ids]
        if ids:
            clauses.append('(draft_id IS NULL OR draft_id IN (' + ','.join('?' * len(ids)) + '))')
            params.extend(ids)
        else:
            clauses.append('draft_id IS NULL')
    return clauses, params


def count_presentations(tenant_id, draft_id=None, search='', status='', date_from='', date_to='', accessible_draft_ids=None):
    """Cheap total for a presentation list without touching any payload column."""
    conn = get_db()
    clauses, params = _presentation_list_clauses(tenant_id, draft_id, search, status, date_from, date_to, accessible_draft_ids)
    row = conn.execute(
        'SELECT COUNT(*) AS c FROM presentations WHERE ' + ' AND '.join(clauses),
        params,
    ).fetchone()
    return int((dict(row) if row else {}).get('c') or 0)


def get_presentations(tenant_id, draft_id=None, search='', status='', date_from='', date_to='', limit=200, offset=0, accessible_draft_ids=None):
    """Get tenant presentations with optional project and archive filters.

    List-only: selects metadata columns, never project_data/slides_data. Those
    payloads are kilobytes-to-megabytes per row and the dashboard used to fetch
    (and JSON-parse twice) up to 200 of them just to render five titles.
    presentation_scope and the legacy draft fallback are extracted in SQL.
    """
    conn = get_db()
    clauses, params = _presentation_list_clauses(tenant_id, draft_id, search, status, date_from, date_to, accessible_draft_ids)
    limit = max(1, min(int(limit or 200), 500))
    offset = max(0, int(offset or 0))
    params.extend([limit, offset])
    try:
        rows = conn.execute(
            'SELECT id, tenant_id, title, '
            "COALESCE(NULLIF(draft_id, ''), "
            "json_extract(project_data, '$.draftId'), "
            "json_extract(project_data, '$.draft_id')) AS draft_id, "
            'revision, slide_count, status, created_at, updated_at, '
            "json_extract(project_data, '$.presentation_scope') AS presentation_scope "
            'FROM presentations WHERE ' + ' AND '.join(clauses)
            + ' ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ? OFFSET ?',
            params,
        ).fetchall()
    except Exception:
        # SQLite without the JSON1 extension: fall back to metadata columns only.
        rows = conn.execute(
            'SELECT id, tenant_id, title, draft_id, revision, slide_count, status, '
            'created_at, updated_at FROM presentations WHERE ' + ' AND '.join(clauses)
            + ' ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ? OFFSET ?',
            params,
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        scope = item.get('presentation_scope')
        if isinstance(scope, str) and scope.strip().startswith(('{', '[')):
            try:
                scope = json.loads(scope)
            except (TypeError, ValueError):
                scope = None
        item['presentation_scope'] = scope
        result.append(item)
    return result


def update_presentation(pres_id, tenant_id=None, **fields):
    """Update a presentation, optionally scoped to a tenant."""
    conn = get_db()
    allowed = {'title', 'draft_id', 'project_data', 'slides_data', 'slide_count', 'status'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'project_data' in updates and updates['project_data'] and not isinstance(updates['project_data'], str):
        updates['project_data'] = json.dumps(updates['project_data'], ensure_ascii=False)
    if 'slides_data' in updates and updates['slides_data'] and not isinstance(updates['slides_data'], str):
        updates['slides_data'] = json.dumps(updates['slides_data'], ensure_ascii=False)
    updates['updated_at'] = _utcnow().isoformat()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [pres_id]
    if tenant_id:
        values.append(tenant_id)
        conn.execute(f'UPDATE presentations SET {set_clause} WHERE id = ? AND tenant_id = ?', values)
    else:
        conn.execute(f'UPDATE presentations SET {set_clause} WHERE id = ?', values)
    conn.commit()
    return True


def delete_presentation(presentation_id, tenant_id=None):
    """Delete a presentation if it belongs to the optional tenant."""
    conn = get_db()
    if tenant_id:
        cursor = conn.execute('DELETE FROM presentations WHERE id = ? AND tenant_id = ?', (presentation_id, tenant_id))
    else:
        cursor = conn.execute('DELETE FROM presentations WHERE id = ?', (presentation_id,))
    conn.commit()
    return cursor.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Exports CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_export(presentation_id, tenant_id, format, file_path, content_hash=None,
                  cost_usd=0, regen_policy=None):
    """Record an exported file with the content hash it was produced from.

    ``content_hash`` ties the physical file to the presentation content the
    final gate approved, so a later export of edited content can never pass
    as the approved file (d03)."""
    conn = get_db()
    export_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO exports (id, presentation_id, tenant_id, format, file_path,
           content_hash, cost_usd, regen_policy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (export_id, presentation_id, tenant_id, format, file_path, content_hash,
         float(cost_usd or 0), regen_policy)
    )
    conn.commit()
    return export_id


def get_exports(tenant_id, accessible_draft_ids=None):
    """Get all exports for a tenant.

    ``accessible_draft_ids`` keeps only exports whose presentation belongs to a
    reachable draft (t20); exports with no presentation or whose presentation
    carries no draft stay visible."""
    conn = get_db()
    if accessible_draft_ids is not None:
        ids = [str(i) for i in accessible_draft_ids]
        placeholders = ','.join('?' * len(ids)) if ids else "''"
        rows = conn.execute(
            '''SELECT e.* FROM exports e LEFT JOIN presentations p
               ON p.id = e.presentation_id AND p.tenant_id = e.tenant_id
               WHERE e.tenant_id = ?
               AND (e.presentation_id IS NULL OR p.draft_id IS NULL OR p.draft_id IN (''' + placeholders + '''))
               ORDER BY e.created_at DESC''',
            (tenant_id, *ids)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM exports WHERE tenant_id = ? ORDER BY created_at DESC',
            (tenant_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_export(export_id, tenant_id):
    """Get one export scoped to its tenant."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM exports WHERE id = ? AND tenant_id = ?',
        (export_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Stats (Admin)
# ─────────────────────────────────────────────────────────────────────────────

def get_stats():
    """Get global stats for admin dashboard."""
    conn = get_db()
    tenants_count = conn.execute('SELECT COUNT(*) as c FROM tenants WHERE is_admin = 0').fetchone()['c']
    presentations_count = conn.execute('SELECT COUNT(*) as c FROM presentations').fetchone()['c']
    exports_count = conn.execute('SELECT COUNT(*) as c FROM exports').fetchone()['c']
    active_tenants = conn.execute('SELECT COUNT(*) as c FROM tenants WHERE is_active = 1 AND is_admin = 0').fetchone()['c']
    users_count = conn.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
    return {
        'tenants': tenants_count,
        'active_tenants': active_tenants,
        'users': users_count,
        'presentations': presentations_count,
        'exports': exports_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Users CRUD (company employees/admins within a tenant)
# ─────────────────────────────────────────────────────────────────────────────

def create_user(tenant_id, name, email, password_hash, role='employee',
                username=None, phone=None, require_password_change=False):
    """Create a user (employee or company admin) within a tenant."""
    conn = get_db()
    user_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO users
           (id, tenant_id, name, username, phone, email, password_hash, role,
            is_active, require_password_change)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)''',
        (user_id, tenant_id, name, username.lower() if username else None, phone,
         email.lower(), password_hash, role, 1 if require_password_change else 0)
    )
    conn.commit()
    return user_id


def get_user_by_email(email):
    """Fetch a user by email (for login). Returns user dict with tenant info."""
    conn = get_db()
    row = conn.execute(
        'SELECT u.*, t.company_name, t.is_active as tenant_active, t.is_admin as tenant_is_admin '
        'FROM users u JOIN tenants t ON u.tenant_id = t.id '
        'WHERE u.email = ?', (email.lower(),)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_username(username):
    """Fetch a user by username with tenant account state."""
    conn = get_db()
    row = conn.execute(
        '''SELECT u.*, t.company_name, t.is_active AS tenant_active,
                  t.is_admin AS tenant_is_admin
           FROM users u JOIN tenants t ON u.tenant_id = t.id
           WHERE LOWER(u.username) = LOWER(?)''',
        (str(username or '').strip(),)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id):
    """Fetch a user by ID."""
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def get_users_by_tenant(tenant_id):
    """Get all users for a tenant."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT id, name, username, phone, email, role, is_active,
                  require_password_change, mfa_enabled, last_login_at, created_at
           FROM users WHERE tenant_id = ? ORDER BY created_at''',
        (tenant_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def update_user(user_id, **fields):
    """Update a user."""
    conn = get_db()
    allowed = {
        'name', 'username', 'phone', 'email', 'password_hash', 'role',
        'is_active', 'require_password_change'
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'email' in updates:
        updates['email'] = updates['email'].lower()
    if 'username' in updates and updates['username']:
        updates['username'] = updates['username'].lower()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [user_id]
    conn.execute(f'UPDATE users SET {set_clause} WHERE id = ?', values)
    conn.commit()
    return True


def set_primary_company_admin(tenant_id, user_id):
    """Assign an existing tenant user as the primary company administrator."""
    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE id = ? AND tenant_id = ?',
        (user_id, tenant_id)
    ).fetchone()
    if not user:
        return False
    tenant = conn.execute(
        'SELECT primary_user_id FROM tenants WHERE id = ?', (tenant_id,)
    ).fetchone()
    previous_user_id = tenant['primary_user_id'] if tenant else None
    try:
        if previous_user_id and previous_user_id != user_id:
            conn.execute(
                "UPDATE users SET role = 'employee' WHERE id = ? AND tenant_id = ?",
                (previous_user_id, tenant_id)
            )
        conn.execute(
            "UPDATE users SET role = 'company_admin', is_active = 1 WHERE id = ?",
            (user_id,)
        )
        conn.execute(
            '''UPDATE tenants
               SET primary_user_id = ?, account_manager_name = ?, username = ?, phone = ?,
                   email = ?, password_hash = ?, require_password_change = ?
               WHERE id = ?''',
            (user_id, user['name'], user['username'], user['phone'], user['email'],
             user['password_hash'], user['require_password_change'], tenant_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def sync_primary_company_admin(tenant_id, **fields):
    """Update the tenant account and its primary company administrator together."""
    conn = get_db()
    tenant = conn.execute(
        'SELECT * FROM tenants WHERE id = ?', (tenant_id,)
    ).fetchone()
    if not tenant:
        return False
    user_id = tenant['primary_user_id']
    user_updates = {}
    tenant_updates = {}
    mapping = {
        'account_manager_name': 'name',
        'username': 'username',
        'phone': 'phone',
        'email': 'email',
        'password_hash': 'password_hash',
        'require_password_change': 'require_password_change',
        'is_active': 'is_active',
    }
    for key, value in fields.items():
        tenant_updates[key] = value
        if key in mapping:
            user_updates[mapping[key]] = value
    try:
        if tenant_updates:
            set_clause = ', '.join(f'{key} = ?' for key in tenant_updates)
            conn.execute(
                f'UPDATE tenants SET {set_clause} WHERE id = ?',
                [*tenant_updates.values(), tenant_id]
            )
        if user_id and user_updates:
            set_clause = ', '.join(f'{key} = ?' for key in user_updates)
            conn.execute(
                f'UPDATE users SET {set_clause} WHERE id = ? AND tenant_id = ?',
                [*user_updates.values(), user_id, tenant_id]
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def delete_user(user_id):
    """Delete a user."""
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()


# Available permissions per section
PERMISSION_KEYS = [
    'dashboard',
    'create_presentation',
    'view_presentations',
    'generate_images',
    'generate_maps',
    'company_settings',
    'custom_fields',
    'manage_users',
    'ai_rules',
    'training_data',
    'approvals',
    'approve_generation',
    'approve_final_file',
    'export_files',
    'support_tickets',
    'copy_presentation',
    'post_approval_edit',
    'billing',
    'audit_log',
    'sag_admin_panel',
]

# Roles the tenant may assign to its users (t20). company_admin holds every
# permission through the role defaults below; the rest are least-privilege
# presets that a company admin can still refine per user.
USER_ROLES = (
    'employee',
    'company_admin',
    'section_editor',
    'section_approver',
    'generation_approver',
    'final_file_approver',
    'profile',
    'support',
)

DEFAULT_PERMISSIONS = {
    'company_admin': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'generate_images': True,
        'generate_maps': True,
        'company_settings': True,
        'custom_fields': True,
        'manage_users': True,
        'ai_rules': True,
        'training_data': True,
        'approvals': True,
        'approve_generation': True,
        'approve_final_file': True,
        'export_files': True,
        'support_tickets': True,
        'copy_presentation': True,
        'post_approval_edit': True,
        'billing': True,
        'audit_log': True,
        'sag_admin_panel': False,
    },
    'employee': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': True,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'section_editor': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'generate_images': True,
        'generate_maps': True,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': True,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'section_approver': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': True,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'generation_approver': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': True,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'final_file_approver': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': True,
        'export_files': True,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'profile': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': False,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': True,
        'custom_fields': True,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'support': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': True,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': True,
        'audit_log': False,
        'sag_admin_panel': False,
    },
}


def get_user_permissions(user_id, default_role='employee'):
    """Get effective permissions for a user. Defaults apply when no override exists."""
    conn = get_db()
    defaults = DEFAULT_PERMISSIONS.get(default_role, DEFAULT_PERMISSIONS['employee']).copy()
    rows = conn.execute(
        'SELECT permission_key, granted FROM user_permissions WHERE user_id = ?',
        (user_id,)
    ).fetchall()
    for row in rows:
        defaults[row['permission_key']] = bool(row['granted'])
    return defaults


def set_user_permission(user_id, permission_key, granted):
    """Set or override a permission for a user."""
    if permission_key not in PERMISSION_KEYS:
        return False
    conn = get_db()
    perm_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO user_permissions (id, user_id, permission_key, granted, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, permission_key) DO UPDATE SET
           granted = excluded.granted, updated_at = excluded.updated_at''',
        (perm_id, user_id, permission_key, 1 if granted else 0, now, now)
    )
    conn.commit()
    return True


def has_permission(user_id, permission_key, default_role='employee'):
    """Check if a user has a specific permission."""
    perms = get_user_permissions(user_id, default_role)
    return perms.get(permission_key, False)


def get_user_field_sections(user_id, tenant_id=None):
    """Get effective field section visibility for a user. Defaults to all granted."""
    conn = get_db()
    if tenant_id is None:
        # Try to get tenant_id from user
        user_row = conn.execute('SELECT tenant_id FROM users WHERE id = ?', (user_id,)).fetchone()
        tenant_id = user_row['tenant_id'] if user_row else None
    defaults = DEFAULT_FIELD_SECTIONS.copy()
    # Add custom sections as granted by default
    if tenant_id:
        custom = get_custom_sections(tenant_id)
        for s in custom:
            if s.get('is_active', 1):
                defaults[s['section_key']] = True
    rows = conn.execute(
        'SELECT section_key, granted FROM user_field_sections WHERE user_id = ?',
        (user_id,)
    ).fetchall()
    for row in rows:
        defaults[row['section_key']] = bool(row['granted'])
    return defaults


def set_user_field_section(user_id, section_key, granted):
    """Set or override visibility for a field section for a user."""
    conn = get_db()
    section_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO user_field_sections (id, user_id, section_key, granted, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, section_key) DO UPDATE SET
           granted = excluded.granted, updated_at = excluded.updated_at''',
        (section_id, user_id, section_key, 1 if granted else 0, now, now)
    )
    conn.commit()
    return True


def has_field_section(user_id, section_key):
    """Check if a user can see a specific field section."""
    sections = get_user_field_sections(user_id)
    return sections.get(section_key, False)


def get_custom_sections(tenant_id):
    """Get all custom sections for a tenant."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM tenant_custom_sections WHERE tenant_id = ? ORDER BY sort_order, created_at',
        (tenant_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_custom_section(tenant_id, section_key):
    """Get one tenant-owned custom section, if it exists."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_custom_sections WHERE tenant_id = ? AND section_key = ?',
        (tenant_id, section_key)
    ).fetchone()
    return dict(row) if row else None


def get_all_sections(tenant_id):
    """Get built-in + custom sections for a tenant."""
    custom = get_custom_sections(tenant_id)
    custom_list = [{'key': s['section_key'], 'label': s['section_label'], 'custom': True} for s in custom if s.get('is_active', 1)]
    return FIELD_SECTIONS + custom_list


def add_custom_section(tenant_id, section_key, section_label, sort_order=100):
    """Add a custom section for a tenant."""
    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM tenant_custom_sections WHERE tenant_id = ? AND section_key = ?',
        (tenant_id, section_key)
    ).fetchone()
    if existing:
        return None
    section_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO tenant_custom_sections (id, tenant_id, section_key, section_label, section_icon, sort_order, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)',
        (section_id, tenant_id, section_key, section_label, 'file', sort_order)
    )
    conn.commit()
    return section_id


def update_custom_section(tenant_id, section_key, **updates):
    """Update a custom section."""
    conn = get_db()
    allowed = {'section_label', 'sort_order', 'is_active'}
    sets = []
    vals = []
    for k, v in updates.items():
        db_k = {'label': 'section_label'}.get(k, k)
        if db_k in allowed:
            sets.append(f'{db_k} = ?')
            vals.append(v)
    if not sets:
        return False
    vals.append(_utcnow().isoformat())
    sets.append('updated_at = ?')
    vals.extend([tenant_id, section_key])
    cursor = conn.execute(
        f'UPDATE tenant_custom_sections SET {", ".join(sets)} WHERE tenant_id = ? AND section_key = ?',
        vals
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_custom_section(tenant_id, section_key):
    """Delete a custom section. Fields in it fall back to 'general'."""
    conn = get_db()
    conn.execute(
        'UPDATE tenant_input_fields SET section_key = ? WHERE tenant_id = ? AND section_key = ?',
        ('general', tenant_id, section_key)
    )
    cursor = conn.execute(
        'DELETE FROM tenant_custom_sections WHERE tenant_id = ? AND section_key = ?',
        (tenant_id, section_key)
    )
    conn.commit()
    return cursor.rowcount > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Project team library (فريق العمل)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEAM_ENTITY_FIELDS = ('name', 'logo_file_id', 'brief',
                      'experience_years', 'notable_projects', 'role', 'sort_order')


def _row_to_team_entity(row):
    if not row:
        return None
    return {
        'id': row['id'],
        'name': row['name'] or '',
        'logoFileId': row['logo_file_id'] or '',
        'brief': row['brief'] or '',
        'experienceYears': row['experience_years'] or '',
        'notableProjects': row['notable_projects'] or '',
        'role': row['role'] or '',
        'sortOrder': row['sort_order'] if row['sort_order'] is not None else 100,
    }


def get_team_entities(tenant_id):
    """Company-wide team entities as a flat list, in the order they were added."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM tenant_team_entities WHERE tenant_id = ? ORDER BY sort_order, created_at',
        (tenant_id,)
    ).fetchall()
    return [_row_to_team_entity(row) for row in rows]


def get_team_entity(tenant_id, entity_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_team_entities WHERE tenant_id = ? AND id = ?',
        (tenant_id, entity_id)
    ).fetchone()
    return _row_to_team_entity(row)


def create_team_entity(tenant_id, name, **fields):
    conn = get_db()
    entity_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_team_entities
           (id, tenant_id, name, logo_file_id, brief,
            experience_years, notable_projects, role, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (entity_id, tenant_id, name,
         fields.get('logo_file_id') or None, fields.get('brief') or '',
         str(fields.get('experience_years') or ''), fields.get('notable_projects') or '',
         fields.get('role') or '', fields.get('sort_order') or 100)
    )
    conn.commit()
    return entity_id


def update_team_entity(tenant_id, entity_id, **updates):
    allowed = {key: value for key, value in updates.items() if key in TEAM_ENTITY_FIELDS}
    if not allowed:
        return False
    conn = get_db()
    assignments = ', '.join(f'{key} = ?' for key in allowed)
    cursor = conn.execute(
        f'UPDATE tenant_team_entities SET {assignments}, updated_at = ? WHERE tenant_id = ? AND id = ?',
        (*allowed.values(), _utcnow().isoformat(), tenant_id, entity_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_team_entity(tenant_id, entity_id):
    conn = get_db()
    cursor = conn.execute(
        'DELETE FROM tenant_team_entities WHERE tenant_id = ? AND id = ?',
        (tenant_id, entity_id)
    )
    conn.commit()
    return cursor.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Tenant domain support
# ─────────────────────────────────────────────────────────────────────────────

def get_tenant_by_domain(domain):
    """Fetch a tenant by email domain."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM tenants WHERE domain = ? AND is_active = 1 AND is_admin = 0",
        (domain.lower(),)
    ).fetchone()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Presentation Versions (backup snapshots)
# ─────────────────────────────────────────────────────────────────────────────

def save_presentation_version(presentation_id, user_id, user_name, slides_data, action='edit'):
    """Save a snapshot of the presentation before a change."""
    conn = get_db()
    version_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO presentation_versions (id, presentation_id, user_id, user_name, slides_data, action) VALUES (?, ?, ?, ?, ?, ?)',
        (version_id, presentation_id, user_id, user_name,
         json.dumps(slides_data, ensure_ascii=False) if slides_data else None, action)
    )
    conn.commit()
    return version_id


def get_presentation_versions(presentation_id):
    """Get all versions for a presentation."""
    conn = get_db()
    rows = conn.execute(
        'SELECT id, user_name, action, created_at FROM presentation_versions WHERE presentation_id = ? ORDER BY created_at DESC',
        (presentation_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_presentation_version(version_id):
    """Get a specific version with full slides_data."""
    conn = get_db()
    row = conn.execute('SELECT * FROM presentation_versions WHERE id = ?', (version_id,)).fetchone()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Edit Log (audit trail)
# ─────────────────────────────────────────────────────────────────────────────

def log_edit(presentation_id, user_id, user_name, action, details=None):
    """Record an edit action on a presentation."""
    conn = get_db()
    log_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO edit_log (id, presentation_id, user_id, user_name, action, details) VALUES (?, ?, ?, ?, ?, ?)',
        (log_id, presentation_id, user_id, user_name, action, details)
    )
    conn.commit()
    return log_id


def get_edit_log(presentation_id):
    """Get edit history for a presentation."""
    conn = get_db()
    rows = conn.execute(
        'SELECT user_name, action, details, created_at FROM edit_log WHERE presentation_id = ? ORDER BY created_at DESC',
        (presentation_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Change log: what changed, by whom, by hand or by the AI — for a presentation
# or a project draft. `edit_log` could only reference presentations and recorded
# one generic line such as "تعديل المحتوى", so a reader could not tell what had
# actually changed, and AI edits were not recorded at all.
# ─────────────────────────────────────────────────────────────────────────────

CHANGE_TARGETS = ('presentation', 'draft')
CHANGE_SOURCES = ('manual', 'ai', 'system')


def log_change(tenant_id, target_type, target_id, user_id, user_name, action,
               summary='', details=None, source='manual', revision_id=None, previous_revision_id=None):
    """Record one change with the individual differences it produced.

    ``details`` is a list of human-readable Arabic lines; it is stored as JSON so the reader can
    show them one per line instead of a single sentence. Presentation events such as
    approval/export link to the current revision without creating a content revision.
    Explicit links must refer to this tenant's same presentation.
    """
    if target_type not in CHANGE_TARGETS or not target_id:
        return None
    lines = [str(line).strip() for line in (details or []) if str(line or '').strip()]
    summary = str(summary or '').strip()
    if not summary and not lines:
        return None
    conn = get_db()
    if target_type == 'presentation':
        presentation = conn.execute('SELECT current_revision_id FROM presentations WHERE id = ? AND tenant_id = ?',
                                    (str(target_id), tenant_id)).fetchone()
        # Deletion audit may run after the presentation row was removed, and
        # legacy callers historically could record such an unlinked event.
        if presentation:
            revision_id = revision_id or presentation['current_revision_id']
        for linked_id in (revision_id, previous_revision_id):
            if linked_id and not conn.execute('''SELECT r.id FROM presentation_revisions r
                JOIN presentations p ON p.id = r.presentation_id
                WHERE r.id = ? AND p.id = ? AND p.tenant_id = ?''',
                (linked_id, str(target_id), tenant_id)).fetchone():
                raise ValueError('Revision does not belong to the history target')
    elif revision_id or previous_revision_id:
        raise ValueError('Presentation revision links require a presentation target')
    change_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO change_log
           (id, tenant_id, target_type, target_id, user_id, user_name, source, action, summary, details,
            created_at, revision_id, previous_revision_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (change_id, tenant_id, target_type, str(target_id), user_id, user_name,
         source if source in CHANGE_SOURCES else 'manual', action, summary,
         json.dumps(lines, ensure_ascii=False), _utcnow().isoformat(), revision_id, previous_revision_id)
    )
    conn.commit()
    return change_id


def get_change_log(tenant_id, target_type, target_id, limit=200):
    """Newest-first history for one presentation or draft, including legacy edit_log rows."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT c.id, c.user_id, c.user_name, c.source, c.action, c.summary, c.details, c.created_at,
                  c.revision_id, c.previous_revision_id, r.revision, r.restored_from_revision_id
           FROM change_log c LEFT JOIN presentation_revisions r ON r.id = c.revision_id
           WHERE c.tenant_id = ? AND c.target_type = ? AND c.target_id = ?
           ORDER BY c.created_at DESC LIMIT ?''',
        (tenant_id, target_type, str(target_id), max(1, min(int(limit or 200), 500)))
    ).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        item['details'] = _json_list(item.get('details'))
        entries.append(item)
    if target_type == 'presentation':
        # History written before this table existed still belongs to the reader.
        legacy = conn.execute(
            '''SELECT e.user_name, e.action, e.details, e.created_at FROM edit_log e
               JOIN presentations p ON p.id = e.presentation_id
               WHERE e.presentation_id = ? AND p.tenant_id = ? ORDER BY e.created_at DESC''',
            (str(target_id), tenant_id)
        ).fetchall()
        for row in legacy:
            item = dict(row)
            entries.append({
                'user_name': item.get('user_name'),
                'source': 'manual',
                'action': item.get('action'),
                'summary': item.get('details') or '',
                'details': [],
                'created_at': item.get('created_at'),
                'legacy': True,
            })
    entries.sort(key=lambda entry: str(entry.get('created_at') or ''), reverse=True)
    return entries


def get_tenant_recent_activity(tenant_id, limit=100):
    """Newest-first change_log rows across a whole tenant (super-admin visibility)."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT user_name, source, action, summary, target_type, target_id, created_at
           FROM change_log
           WHERE tenant_id = ?
           ORDER BY created_at DESC LIMIT ?''',
        (tenant_id, max(1, min(int(limit or 100), 300)))
    ).fetchall()
    return [dict(row) for row in rows]


def _json_list(value):
    if isinstance(value, list):
        return list(value)
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []


# ─────────────────────────────────────────────────────────────────────────────
# AuditEvent: Immutable unified audit log (Omran spec sections 6, 15, 18).
#
# Captures user, timestamp, action/operation, affected entity, old_value,
# new_value, and contextual metadata. Strictly append-only.
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_audit_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _deserialize_audit_value(text):
    if not text or not isinstance(text, str):
        return text
    stripped = text.strip()
    if (stripped.startswith('{') and stripped.endswith('}')) or (stripped.startswith('[') and stripped.endswith(']')):
        try:
            return json.loads(stripped)
        except (ValueError, TypeError):
            return text
    return text


def _audit_event_public(row):
    if not row:
        return None
    item = dict(row)
    item['old_value_raw'] = item.get('old_value')
    item['new_value_raw'] = item.get('new_value')
    item['old_value'] = _deserialize_audit_value(item.get('old_value'))
    item['new_value'] = _deserialize_audit_value(item.get('new_value'))
    item['metadata'] = _deserialize_audit_value(item.get('metadata')) or {}
    return item


def record_audit_event(tenant_id, action, entity_type, entity_id,
                       user_id=None, user_name=None, user_role=None,
                       entity_name=None, old_value=None, new_value=None,
                       metadata=None, created_at=None):
    """Record one immutable audit event into the platform audit log."""
    if not tenant_id or not action or not entity_type or not entity_id:
        raise ValueError('tenant_id, action, entity_type, and entity_id are required for audit events')
    conn = get_db()
    event_id = str(uuid.uuid4())
    ts = created_at or _utcnow().isoformat()
    old_str = _serialize_audit_value(old_value)
    new_str = _serialize_audit_value(new_value)
    meta_str = _serialize_audit_value(metadata)

    conn.execute(
        '''INSERT INTO audit_events
           (id, tenant_id, user_id, user_name, user_role, action,
            entity_type, entity_id, entity_name, old_value, new_value,
            metadata, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (event_id, tenant_id, user_id, user_name, user_role, str(action).strip(),
         str(entity_type).strip(), str(entity_id).strip(), entity_name,
         old_str, new_str, meta_str, ts)
    )
    conn.commit()
    row = conn.execute('SELECT * FROM audit_events WHERE id = ?', (event_id,)).fetchone()
    return _audit_event_public(row)


def get_audit_event(tenant_id, event_id):
    """Fetch a single audit event with tenant isolation."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM audit_events WHERE id = ? AND tenant_id = ?',
        (str(event_id), tenant_id)
    ).fetchone()
    return _audit_event_public(row)


def list_audit_events(tenant_id, entity_type=None, entity_id=None,
                      action=None, user_id=None, from_date=None,
                      to_date=None, limit=50, offset=0):
    """Query audit events with filtering and pagination, sorted newest first."""
    conn = get_db()
    conditions = ['tenant_id = ?']
    params = [tenant_id]

    if entity_type:
        conditions.append('entity_type = ?')
        params.append(str(entity_type).strip())
    if entity_id:
        conditions.append('entity_id = ?')
        params.append(str(entity_id).strip())
    if action:
        conditions.append('action = ?')
        params.append(str(action).strip())
    if user_id:
        conditions.append('user_id = ?')
        params.append(str(user_id).strip())
    if from_date:
        conditions.append('created_at >= ?')
        params.append(str(from_date).strip())
    if to_date:
        conditions.append('created_at <= ?')
        params.append(str(to_date).strip())

    where_clause = ' AND '.join(conditions)

    count_row = conn.execute(
        f'SELECT COUNT(*) AS total FROM audit_events WHERE {where_clause}',
        params
    ).fetchone()
    total = count_row['total'] if count_row else 0

    lim = max(1, min(int(limit or 50), 500))
    off = max(0, int(offset or 0))

    query_params = list(params) + [lim, off]
    rows = conn.execute(
        f'''SELECT * FROM audit_events
            WHERE {where_clause}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?''',
        query_params
    ).fetchall()

    return {
        'events': [_audit_event_public(r) for r in rows],
        'total': total,
        'limit': lim,
        'offset': off,
    }


def export_audit_events_csv(tenant_id, entity_type=None, entity_id=None,
                            action=None, user_id=None, from_date=None,
                            to_date=None, limit=5000):
    """Export audit events as a UTF-8 BOM CSV text for corporate compliance and reporting."""
    result = list_audit_events(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=0,
    )
    import csv
    import io
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        'معرف الحدث',
        'التاريخ والوقت',
        'معرف المستخدم',
        'اسم المستخدم',
        'الدور',
        'نوع العملية',
        'نوع الكيان',
        'معرف الكيان',
        'اسم الكيان',
        'القيمة السابقة',
        'القيمة الجديدة',
        'بيانات إضافية',
    ])
    for event in result.get('events', []):
        old_val = event.get('old_value')
        new_val = event.get('new_value')
        meta = event.get('metadata')
        writer.writerow([
            event.get('id') or '',
            event.get('created_at') or '',
            event.get('user_id') or '',
            event.get('user_name') or '',
            event.get('user_role') or '',
            event.get('action') or '',
            event.get('entity_type') or '',
            event.get('entity_id') or '',
            event.get('entity_name') or '',
            json.dumps(old_val, ensure_ascii=False) if isinstance(old_val, (dict, list)) else str(old_val or ''),
            json.dumps(new_val, ensure_ascii=False) if isinstance(new_val, (dict, list)) else str(new_val or ''),
            json.dumps(meta, ensure_ascii=False) if isinstance(meta, (dict, list)) else str(meta or ''),
        ])
    return output.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Invite Links
# ─────────────────────────────────────────────────────────────────────────────

def create_invite(tenant_id, email, expiry_days=7, role='employee', name=None,
                  phone=None, sections=None, projects=None):
    """Create an invite link carrying the pre-assigned role and scope (t21)."""
    import secrets as _secrets
    conn = get_db()
    invite_id = str(uuid.uuid4())
    token = _secrets.token_urlsafe(32)
    from datetime import timedelta
    expires = (_utcnow() + timedelta(days=expiry_days)).isoformat()
    clean_role = role if role in USER_ROLES else 'employee'
    sections_json = json.dumps(list(sections), ensure_ascii=False) if sections is not None else None
    projects_json = json.dumps(list(projects), ensure_ascii=False) if projects is not None else None
    conn.execute(
        '''INSERT INTO invite_links
           (id, tenant_id, email, token, expires_at, name, phone, role, sections_json, projects_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (invite_id, tenant_id, email.lower(), token, expires,
         str(name or '').strip() or None, str(phone or '').strip() or None, clean_role,
         sections_json, projects_json)
    )
    conn.commit()
    return {'id': invite_id, 'token': token, 'expires_at': expires}


def get_invite(tenant_id, invite_id):
    """One invite row for the tenant, whatever its state."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM invite_links WHERE id = ? AND tenant_id = ?', (invite_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


def mark_invite_email(invite_id, status, error=None):
    """Record the outcome of one invite-email send attempt (t21)."""
    conn = get_db()
    conn.execute(
        '''UPDATE invite_links SET email_status = ?, email_error = ?,
           email_attempts = COALESCE(email_attempts, 0) + 1, email_sent_at = ?
           WHERE id = ?''',
        (status, str(error or '')[:400] or None, _utcnow().isoformat(), invite_id),
    )
    conn.commit()


def apply_invite_scope(user_id, invite):
    """Give a newly registered user the sections and projects named on the invite."""
    conn = get_db()
    tenant_id = invite.get('tenant_id')
    sections = _json_or(invite.get('sections_json'), None)
    if isinstance(sections, list) and sections:
        allowed = set(str(s) for s in sections)
        for key in get_user_field_sections(user_id, tenant_id):
            set_user_field_section(user_id, key, key in allowed)
    projects = _json_or(invite.get('projects_json'), None)
    if isinstance(projects, list) and projects:
        valid = {
            row['id'] for row in conn.execute(
                'SELECT id FROM project_drafts WHERE tenant_id = ?', (tenant_id,)
            ).fetchall()
        }
        for draft_id in projects:
            if draft_id in valid:
                conn.execute(
                    'INSERT OR IGNORE INTO user_project_scopes (id, tenant_id, user_id, draft_id) VALUES (?, ?, ?, ?)',
                    (str(uuid.uuid4()), tenant_id, user_id, draft_id),
                )
        conn.commit()


def create_password_setup_token(tenant_id, user_id, expiry_hours=24):
    """Create a one-time password setup token and return its raw value."""
    import hashlib as _hashlib
    import secrets as _secrets
    from datetime import timedelta
    conn = get_db()
    raw_token = _secrets.token_urlsafe(32)
    token_hash = _hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    token_id = str(uuid.uuid4())
    expires_at = (_utcnow() + timedelta(hours=expiry_hours)).isoformat()
    conn.execute(
        '''UPDATE password_setup_tokens
           SET used_at = ?
           WHERE tenant_id = ? AND user_id = ? AND used_at IS NULL''',
        (_utcnow().isoformat(), tenant_id, user_id)
    )
    conn.execute(
        '''INSERT INTO password_setup_tokens
           (id, tenant_id, user_id, token_hash, expires_at)
           VALUES (?, ?, ?, ?, ?)''',
        (token_id, tenant_id, user_id, token_hash, expires_at)
    )
    conn.commit()
    return raw_token


def get_password_setup_token(raw_token):
    """Return a valid one-time password setup token."""
    import hashlib as _hashlib
    conn = get_db()
    token_hash = _hashlib.sha256(str(raw_token or '').encode('utf-8')).hexdigest()
    row = conn.execute(
        '''SELECT pst.*, t.company_name, t.username, t.email
           FROM password_setup_tokens pst
           JOIN tenants t ON t.id = pst.tenant_id
           WHERE pst.token_hash = ? AND pst.used_at IS NULL AND pst.expires_at > ?''',
        (token_hash, _utcnow().isoformat())
    ).fetchone()
    return dict(row) if row else None


def complete_password_setup(raw_token, password_hash):
    """Set the password for a valid setup token and consume it atomically."""
    import hashlib as _hashlib
    conn = get_db()
    token_hash = _hashlib.sha256(str(raw_token or '').encode('utf-8')).hexdigest()
    token = conn.execute(
        '''SELECT * FROM password_setup_tokens
           WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?''',
        (token_hash, _utcnow().isoformat())
    ).fetchone()
    if not token:
        return None
    used_at = _utcnow().isoformat()
    try:
        conn.execute(
            '''UPDATE users
               SET password_hash = ?, require_password_change = 0, is_active = 1
               WHERE id = ? AND tenant_id = ?''',
            (password_hash, token['user_id'], token['tenant_id'])
        )
        conn.execute(
            '''UPDATE tenants
               SET password_hash = ?, require_password_change = 0
               WHERE id = ? AND primary_user_id = ?''',
            (password_hash, token['tenant_id'], token['user_id'])
        )
        conn.execute(
            'UPDATE password_setup_tokens SET used_at = ? WHERE id = ?',
            (used_at, token['id'])
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        'tenant_id': token['tenant_id'],
        'user_id': token['user_id'],
    }


def get_invite_by_token(token):
    """Get an invite by token. Returns None if expired or used."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM invite_links WHERE token = ? AND used_at IS NULL AND expires_at > ?",
        (token, _utcnow().isoformat())
    ).fetchone()
    return dict(row) if row else None


def mark_invite_used(token):
    """Mark an invite as used."""
    conn = get_db()
    conn.execute('UPDATE invite_links SET used_at = ? WHERE token = ?', (_utcnow().isoformat(), token))
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Training Data (per-tenant GLM training)
# ─────────────────────────────────────────────────────────────────────────────

def get_training_data(tenant_id, active_only=False):
    """Get training data that belongs to exactly one tenant."""
    conn = get_db()
    query = 'SELECT * FROM tenant_training_data WHERE tenant_id = ?'
    params = [tenant_id]
    if active_only:
        query += ' AND is_active = 1'
    query += ' ORDER BY created_at DESC'
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_training_entry(tenant_id, entry_id):
    """Return one training record only if it belongs to the requesting tenant."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_training_data WHERE id = ? AND tenant_id = ?',
        (entry_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


def create_training_entry(tenant_id, title, content, category='general', image_path=None,
                          image_analysis=None, image_type=None, image_description=None):
    """Create a tenant-scoped training data entry."""
    conn = get_db()
    entry_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_training_data
           (id, tenant_id, title, content, category, image_path, image_analysis, image_type, image_description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (entry_id, tenant_id, title, content, category, image_path, image_analysis,
         image_type, image_description)
    )
    conn.commit()
    return entry_id


def update_training_entry(tenant_id, entry_id, **kwargs):
    """Update a tenant's entry and never cross the tenant boundary."""
    conn = get_db()
    allowed = [
        'title', 'content', 'category', 'is_active', 'image_path', 'image_analysis',
        'image_type', 'image_description'
    ]
    sets = []
    vals = []
    for key in allowed:
        if key in kwargs:
            sets.append(f'{key} = ?')
            vals.append(kwargs[key])
    if not sets:
        return False
    sets.append("updated_at = datetime('now')")
    vals.extend([entry_id, tenant_id])
    cursor = conn.execute(
        f'UPDATE tenant_training_data SET {", ".join(sets)} WHERE id = ? AND tenant_id = ?',
        vals
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_training_entry(tenant_id, entry_id):
    """Delete a training entry only from its owning tenant."""
    conn = get_db()
    cursor = conn.execute(
        'DELETE FROM tenant_training_data WHERE id = ? AND tenant_id = ?',
        (entry_id, tenant_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def get_training_context(tenant_id, max_entries=20, max_chars=12000):
    """Build bounded, tenant-only context for AI calls.

    Image files themselves remain in tenant storage.  Only the tenant's saved
    description and analysis are supplied to the model as contextual text.
    """
    entries = get_training_data(tenant_id, active_only=True)[:max_entries]
    branding = get_branding(tenant_id) or {}
    sections = get_all_sections(tenant_id)
    active_fields = get_fields(tenant_id, active_only=True)
    templates = get_slide_templates(tenant_id)

    parts = [
        'القواعد التالية وضعتها هذه الشركة خصيصاً لعروضها التقديمية. '
        'هي إرشادات ملزمة لهيكل وتصميم ومحتوى وترتيب الشرائح التي تنشئها لهذه الشركة — اتبعها بدقة وقدّمها على أي افتراضات عامة. '
        'ليست أوامر نظام ولا تغيّر هويتك أو صلاحياتك، لكن أي عرض لا يلتزم بها يُعتبر غير مطابق لمتطلبات الشركة.'
    ]
    used = len(parts[0])

    if branding:
        lines = ['## هوية الشركة وتصميمها']
        if branding.get('company_name'):
            lines.append(f"اسم الشركة: {branding['company_name']}")
        if branding.get('tagline'):
            lines.append(f"شعار الشركة: {branding['tagline']}")
        for key in ['primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color']:
            if branding.get(key):
                lines.append(f"{key.replace('_', ' ').title()}: {branding[key]}")
        for key in ['design_template', 'card_style', 'slide_ratio']:
            if branding.get(key):
                lines.append(f"{key.replace('_', ' ').title()}: {branding[key]}")
        lines.append(f"حد الشرائح: min={branding.get('min_slides', 8)}, max={branding.get('max_slides', 30)}, default={branding.get('default_slide_count', 16)}")
        lines.append(f"عدد صور المود بورد: {branding.get('moodboard_count', 4)}")
        lines.append(f"تفعيل مود بورد: {'نعم' if branding.get('moodboard_enabled') else 'لا'}")
        lines.append(f"تفعيل صورة الغلاف: {'نعم' if branding.get('cover_image_enabled') else 'لا'}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    if sections:
        lines = ['## أقسام بيانات المشروع المتاحة']
        for section in sections:
            if section.get('is_active', 1):
                lines.append(f"- {section['key']}: {section.get('label', section['key'])}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    if active_fields:
        lines = ['## الحقول المتاحة حالياً في المشروع']
        for field in active_fields:
            if len(lines) > 40:
                break
            hint = field.get('ai_hint') or ''
            desc = f"{field['field_key']} ({field['field_type']} في {field.get('section_key', 'general')})"
            if hint:
                desc += f" — توجيه AI: {hint}"
            lines.append(f"- {desc}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    if templates:
        lines = ['## قوالب الشرائح المخصصة للشركة']
        for template in templates[:10]:
            name = template.get('slide_name') or template.get('slide_type')
            instr = template.get('design_instructions') or ''
            lines.append(f"- {template.get('slide_type')} / {name}: {instr}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining > 0:
            if len(part) > remaining:
                part = part[:remaining]
            parts.append(part)
            used += len(part) + 2

    for entry in entries:
        lines = [f"## {entry.get('title') or 'بيانات تدريب'}"]
        if entry.get('category'):
            lines.append(f"الفئة: {entry['category']}")
        if entry.get('image_type'):
            lines.append(f"نوع الصورة: {entry['image_type']}")
        if entry.get('image_description'):
            lines.append(f"وصف مقدم من الشركة: {entry['image_description']}")
        content = (entry.get('content') or '').strip()
        analysis = (entry.get('image_analysis') or '').strip()
        if content:
            lines.append(content)
        if analysis and analysis != content:
            lines.append(f"تحليل الصورة: {analysis}")
        part = '\n'.join(lines)
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(part) > remaining:
            part = part[:remaining]
        parts.append(part)
        used += len(part) + 2

    return '\n\n'.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Presentation Approvals
# ─────────────────────────────────────────────────────────────────────────────

def create_approval(presentation_id, tenant_id, requested_by, requested_by_name):
    """Create an approval request for a presentation."""
    conn = get_db()
    approval_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO presentation_approvals (id, presentation_id, tenant_id, requested_by, requested_by_name, status) VALUES (?, ?, ?, ?, ?, ?)',
        (approval_id, presentation_id, tenant_id, requested_by, requested_by_name, 'pending')
    )
    conn.execute("UPDATE presentations SET status = 'pending_approval' WHERE id = ?", (presentation_id,))
    conn.commit()
    return approval_id


def get_pending_approvals(tenant_id):
    """Get all pending approval requests for a tenant."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT pa.*, p.title as pres_title, p.slide_count 
           FROM presentation_approvals pa 
           JOIN presentations p ON pa.presentation_id = p.id 
           WHERE pa.tenant_id = ? AND pa.status = 'pending' 
           ORDER BY pa.created_at DESC''',
        (tenant_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_approval(approval_id, tenant_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM presentation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    return dict(row) if row else None


def review_approval(approval_id, tenant_id, status, reviewed_by, reviewed_by_name, note=None):
    """Approve or reject a presentation."""
    conn = get_db()
    approval = conn.execute('SELECT * FROM presentation_approvals WHERE id = ? AND tenant_id = ?', (approval_id, tenant_id)).fetchone()
    if not approval:
        return False
    conn.execute(
        'UPDATE presentation_approvals SET status = ?, reviewed_by = ?, reviewed_by_name = ?, review_note = ?, reviewed_at = datetime(\'now\') WHERE id = ?',
        (status, reviewed_by, reviewed_by_name, note, approval_id)
    )
    pres_status = 'approved' if status == 'approved' else 'draft'
    conn.execute('UPDATE presentations SET status = ? WHERE id = ?', (pres_status, approval['presentation_id']))
    conn.commit()
    return True


def get_approval_status(presentation_id):
    """Get the latest approval status for a presentation."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM presentation_approvals WHERE presentation_id = ? ORDER BY created_at DESC LIMIT 1',
        (presentation_id,)
    ).fetchone()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Project Drafts
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Proposal Lifecycle: 11 official states (Omran spec section 7 & 8)
#
#  1. draft: مسودة (المدخلات قابلة للتعديل ولم ترسل للاعتماد)
#  2. sections_in_progress: قيد إعداد الأقسام (يعمل المحررون على الأقسام بشكل متوازٍ)
#  3. section_approval_pending: بانتظار اعتماد قسم (القسم مقفل مؤقتًا على الإصدار المرسل)
#  4. rejected_for_revision: معاد للتعديل (رفض المعتمد القسم أو طلب تعديل مع ملاحظات)
#  5. sections_approved: الأقسام معتمدة (جميع الأقسام المطلوبة معتمدة على إصدارات محددة)
#  6. generation_approval_pending: بانتظار اعتماد التوليد (تم احتساب التكلفة التقديرية وتنتظر الموافقة)
#  7. generating: قيد التوليد (وظيفة التوليد تعمل في الخلفية)
#  8. generated_draft: مسودة ملف مولد (الملف قابل للتعديل بالشات أو النص وفق النطاق المنفذ)
#  9. final_approval_pending: بانتظار اعتماد الملف النهائي (نسخة محددة مرسلة للمعتمد النهائي)
# 10. approved: معتمد نهائيًا (نسخة رسمية مقفلة وقابلة للتنزيل)
# 11. archived: مؤرشف (غير نشط مع الاحتفاظ الكامل بالسجل)
# ─────────────────────────────────────────────────────────────────────────────

PROPOSAL_LIFECYCLE_STATES = {
    'draft': {
        'label': 'مسودة',
        'label_en': 'Draft',
        'phase': 'inputs',
        'description': 'المدخلات قابلة للتعديل ولم ترسل للاعتماد',
        'is_locked': False,
        'order': 1,
    },
    'sections_in_progress': {
        'label': 'قيد إعداد الأقسام',
        'label_en': 'Sections In Progress',
        'phase': 'inputs',
        'description': 'يعمل المحررون على الأقسام بشكل متوازٍ',
        'is_locked': False,
        'order': 2,
    },
    'section_approval_pending': {
        'label': 'بانتظار اعتماد قسم',
        'label_en': 'Section Approval Pending',
        'phase': 'inputs',
        'description': 'القسم مقفل مؤقتًا على الإصدار المرسل',
        'is_locked': False,
        'order': 3,
    },
    'rejected_for_revision': {
        'label': 'معاد للتعديل',
        'label_en': 'Returned For Revision',
        'phase': 'inputs',
        'description': 'رفض المعتمد القسم أو طلب تعديل مع ملاحظات',
        'is_locked': False,
        'order': 4,
    },
    'sections_approved': {
        'label': 'الأقسام معتمدة',
        'label_en': 'Sections Approved',
        'phase': 'inputs',
        'description': 'جميع الأقسام المطلوبة معتمدة على إصدارات محددة',
        'is_locked': False,
        'order': 5,
    },
    'generation_approval_pending': {
        'label': 'بانتظار اعتماد التوليد',
        'label_en': 'Generation Approval Pending',
        'phase': 'generation',
        'description': 'تم احتساب التكلفة التقديرية وتنتظر الموافقة',
        'is_locked': True,
        'order': 6,
    },
    'generating': {
        'label': 'قيد التوليد',
        'label_en': 'Generating',
        'phase': 'generation',
        'description': 'وظيفة التوليد تعمل في الخلفية',
        'is_locked': True,
        'order': 7,
    },
    'generated_draft': {
        'label': 'مسودة ملف مولد',
        'label_en': 'Generated Draft',
        'phase': 'output',
        'description': 'الملف قابل للتعديل بالشات أو النص وفق النطاق المنفذ',
        'is_locked': False,
        'order': 8,
    },
    'final_approval_pending': {
        'label': 'بانتظار اعتماد الملف النهائي',
        'label_en': 'Final Approval Pending',
        'phase': 'output',
        'description': 'نسخة محددة مرسلة للمعتمد النهائي',
        'is_locked': True,
        'order': 9,
    },
    'approved': {
        'label': 'معتمد نهائيًا',
        'label_en': 'Approved',
        'phase': 'output',
        'description': 'نسخة رسمية مقفلة وقابلة للتنزيل',
        'is_locked': True,
        'order': 10,
    },
    'archived': {
        'label': 'مؤرشف',
        'label_en': 'Archived',
        'phase': 'archived',
        'description': 'غير نشط مع الاحتفاظ الكامل بالسجل',
        'is_locked': True,
        'order': 11,
    },
}

PROPOSAL_ALLOWED_TRANSITIONS = {
    'draft': {'sections_in_progress', 'section_approval_pending', 'sections_approved', 'archived'},
    'sections_in_progress': {'section_approval_pending', 'sections_approved', 'rejected_for_revision', 'archived'},
    'section_approval_pending': {'sections_in_progress', 'rejected_for_revision', 'sections_approved', 'archived'},
    'rejected_for_revision': {'sections_in_progress', 'section_approval_pending', 'archived'},
    'sections_approved': {'generation_approval_pending', 'generating', 'sections_in_progress', 'rejected_for_revision', 'archived'},
    'generation_approval_pending': {'generating', 'generated_draft', 'sections_approved', 'sections_in_progress', 'archived'},
    'generating': {'generated_draft', 'sections_approved', 'archived'},
    'generated_draft': {'final_approval_pending', 'generation_approval_pending', 'generating', 'sections_in_progress', 'archived'},
    'final_approval_pending': {'approved', 'generated_draft', 'rejected_for_revision', 'archived'},
    'approved': {'archived', 'generated_draft', 'sections_in_progress'},
    'archived': {'draft', 'sections_in_progress'},
}

# The subset a user may pick through the manual transition endpoint. Gate states
# (generation_approval_pending, generating, generated_draft, final_approval_pending,
# approved) are entered only by their own backend workflows, never by hand.
PROPOSAL_MANUAL_TRANSITIONS = {
    'draft': {'sections_in_progress', 'section_approval_pending', 'archived'},
    'sections_in_progress': {'section_approval_pending', 'rejected_for_revision', 'archived'},
    'section_approval_pending': {'sections_in_progress', 'rejected_for_revision', 'sections_approved', 'archived'},
    'rejected_for_revision': {'sections_in_progress', 'section_approval_pending', 'archived'},
    'sections_approved': {'sections_in_progress', 'rejected_for_revision', 'archived'},
    'generation_approval_pending': {'sections_approved', 'sections_in_progress', 'archived'},
    'generating': {'archived'},
    'generated_draft': {'sections_in_progress', 'archived'},
    'final_approval_pending': {'generated_draft', 'archived'},
    'approved': {'generated_draft', 'sections_in_progress', 'archived'},
    'archived': {'draft', 'sections_in_progress'},
}

PROPOSAL_STATUS_ALIASES = {
    'pending_approval': 'section_approval_pending',
    'submitted': 'section_approval_pending',
    'edited': 'sections_in_progress',
}

PROJECT_DRAFT_STATUSES = set(PROPOSAL_LIFECYCLE_STATES.keys()) | {'pending_approval', 'submitted', 'edited'}
SECTION_DRAFT_STATUSES = {'draft', 'approved', 'pending'}


def normalize_proposal_status(status):
    """Normalize any historical or alias status to a canonical 11-state key."""
    if not status or not isinstance(status, str):
        return 'draft'
    clean = status.strip().lower()
    if clean in PROPOSAL_LIFECYCLE_STATES:
        return clean
    if clean in PROPOSAL_STATUS_ALIASES:
        return PROPOSAL_STATUS_ALIASES[clean]
    return 'draft'


def can_transition_proposal_status(current_status, next_status):
    """Check if a transition from current_status to next_status is valid."""
    curr = normalize_proposal_status(current_status)
    target = normalize_proposal_status(next_status)
    if curr == target:
        return True
    allowed = PROPOSAL_ALLOWED_TRANSITIONS.get(curr, set())
    return target in allowed


def proposal_status_is_locked(status):
    """True when the normalized lifecycle state freezes user edits."""
    return bool(PROPOSAL_LIFECYCLE_STATES.get(normalize_proposal_status(status), {}).get('is_locked'))


class DraftLocked(Exception):
    """Raised when a write targets a draft whose lifecycle state is locked."""

    def __init__(self, draft_id, status):
        super().__init__(f'Project draft {draft_id} is locked in state {status}')
        self.draft_id = draft_id
        self.status = status

# Keys every save carries as bookkeeping: they say nothing about whether the payload still
# holds the project itself, so they are ignored when judging a destructive overwrite.
DRAFT_BOOKKEEPING_KEYS = {
    'draftId', 'draft_id', 'pageDrafts', 'sectionStatuses',
    'map_styles', 'map_type', 'calculate_landmark_driving', 'site_analysis_approved',
    'designerChat', 'presentation_scope',
}

# Below this many stored fields a draft is still being started, and blanking it can be a real
# edit. Above it, a payload that would leave nothing behind is a fault, not an instruction.
DRAFT_EMPTY_OVERWRITE_FLOOR = 3


class DraftOverwriteRefused(Exception):
    """Raised instead of blanking a stored draft that still holds project content."""

    def __init__(self, draft_id, stored_keys, incoming_keys):
        super().__init__(f'Refusing to empty project draft {draft_id}')
        self.draft_id = draft_id
        self.stored_keys = stored_keys
        self.incoming_keys = incoming_keys


def _has_content(value):
    """True when a stored value carries something a user would recognise as their data."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_content(item) for item in value)
    return True


def _draft_content_keys(payload):
    """Field names in a draft payload that actually carry project content."""
    if not isinstance(payload, dict):
        return set()
    return {
        key for key, value in payload.items()
        if key not in DRAFT_BOOKKEEPING_KEYS and _has_content(value)
    }


def _json_object(value):
    """Decode a JSON object safely; malformed historical data becomes empty."""
    if isinstance(value, dict):
        return value.copy()
    if not value:
        return {}
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _hydrate_project_draft(row):
    if not row:
        return None
    result = dict(row)
    result['draft_data'] = _json_object(result.get('draft_data'))
    result['section_statuses'] = _json_object(result.get('section_statuses'))
    if result.get('draft_data') and result.get('id'):
        result['draft_data']['draftId'] = result['id']
    return result


def _clear_draft_approval_fields(conn, draft_id):
    conn.execute(
        '''UPDATE project_drafts SET requested_by = NULL, requested_by_name = NULL,
           requested_at = NULL, reviewed_by = NULL, reviewed_by_name = NULL,
           review_note = NULL, reviewed_at = NULL WHERE id = ?''',
        (draft_id,)
    )


def save_project_draft(tenant_id, user_id, draft_data, section_statuses=None, status='draft',
                       draft_id=None, allow_generating=False):
    """Save one unified draft per tenant actor without losing section approvals.

    ``user_id`` is an actor identifier.  Company administrators use a stable
    tenant-admin identifier supplied by the API because their JWT has no user id.

    A save that does not name its draft still lands on the row this actor updated most recently,
    which is the single-draft contract older clients rely on.  That is also why an unnamed save
    reaching the wrong project is possible, so it is logged: a current client always sends an id.

    A locked lifecycle state refuses the write with ``DraftLocked``; the only exception is
    ``generating``, which a generation checkpoint may still update when the caller explicitly
    passes ``allow_generating``.  The ``status`` argument is a legacy hint, not a lifecycle
    command: a save never advances or regresses the stored state — only the approval-void
    reset below may move it, and new drafts always start as ``draft``.
    """
    conn = get_db()
    if draft_id:
        existing = conn.execute(
            'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ? AND user_id = ?',
            (draft_id, tenant_id, user_id)
        ).fetchone()
    else:
        # The single-draft fallback targets the newest EDITABLE row: a locked
        # lifecycle state sealed that file, so work continues on the draft that
        # is still open instead of overwriting a sealed one.
        existing = conn.execute(
            '''SELECT * FROM project_drafts WHERE tenant_id = ? AND user_id = ?
               AND COALESCE(status, 'draft') NOT IN (
                   'generation_approval_pending', 'generating',
                   'final_approval_pending', 'approved', 'archived')
               ORDER BY updated_at DESC LIMIT 1''',
            (tenant_id, user_id)
        ).fetchone()
        if existing:
            print(f'[DRAFT SAVE] Save without a draft id applied to newest editable draft {existing["id"]} '
                  f'of actor {user_id}')

    # Determine the stable draft id before serializing
    draft_id = existing['id'] if existing else (draft_id or str(uuid.uuid4()))

    now = _utcnow().isoformat()

    # Strip client-supplied draftId so it doesn't trigger false data_changed or bloat the row
    save_data = dict(draft_data) if isinstance(draft_data, dict) else {}
    save_data.pop('draftId', None)
    save_data.pop('draft_id', None)
    draft_json = json.dumps(save_data, ensure_ascii=False)
    title = str(save_data.get('project_name') or save_data.get('projectName') or save_data.get('name') or 'مسودة مشروع بدون عنوان').strip()[:200]
    creative = save_data.get('tenantCreativeImages') if isinstance(save_data.get('tenantCreativeImages'), dict) else {}
    has_slides = 1 if isinstance(save_data.get('tenantSlidesData'), list) and save_data.get('tenantSlidesData') else 0
    has_maps = 1 if isinstance(creative.get('map_placeholders'), dict) and any(creative.get('map_placeholders').values()) else 0
    data_bytes = len(draft_json.encode('utf-8'))

    if existing:
        norm_existing = normalize_proposal_status(existing['status'])
        if proposal_status_is_locked(norm_existing) \
                and not (allow_generating and norm_existing == 'generating'):
            raise DraftLocked(existing['id'], norm_existing)

        old_statuses = _json_object(existing['section_statuses'])
        # Older clients send {} whenever they autosave.  Treat that as "unchanged"
        # instead of silently erasing every section's review state.
        if isinstance(section_statuses, dict) and section_statuses:
            new_statuses = section_statuses
        elif section_statuses is None or section_statuses == {}:
            new_statuses = old_statuses
        else:
            new_statuses = _json_object(section_statuses)
        statuses_json = json.dumps(new_statuses, ensure_ascii=False)
        old_data = _json_object(existing['draft_data']) or {}
        old_data.pop('draftId', None)
        old_data.pop('draft_id', None)

        # A save that would leave the row with no project content at all is never a real edit:
        # emptying a project file is DELETE /api/project-draft/<id>.  Writing it used to answer
        # success, which is how a saved project could appear to empty itself with no error.
        stored_content = _draft_content_keys(old_data)
        incoming_content = _draft_content_keys(save_data)
        if len(stored_content) >= DRAFT_EMPTY_OVERWRITE_FLOOR and not incoming_content:
            raise DraftOverwriteRefused(existing['id'], sorted(stored_content), sorted(save_data))
        if stored_content and len(incoming_content) * 2 < len(stored_content):
            print(f'[DRAFT SAVE] Draft {existing["id"]} shrank from {len(stored_content)} to '
                  f'{len(incoming_content)} filled fields, '
                  f'{existing["data_bytes"] or 0} to {data_bytes} bytes. Dropped: '
                  f'{sorted(stored_content - incoming_content)[:12]}')

        data_changed = save_data != old_data
        statuses_changed = statuses_json != (existing['section_statuses'] or '{}')
        old_overall_status = existing['status'] or 'draft'

        norm_old_status = normalize_proposal_status(old_overall_status)
        if norm_old_status == 'section_approval_pending':
            if any(v == 'pending' for v in new_statuses.values()):
                # A live section-version review keeps the draft pending even when
                # unrelated fields change — the snapshot under review is immutable.
                next_status = old_overall_status
                clear_approval = False
            elif data_changed or statuses_changed:
                # Editing while a review request is open voids it; resubmit after fixing.
                next_status = 'draft'
                clear_approval = True
            else:
                next_status = old_overall_status
                clear_approval = False
        elif norm_old_status == 'approved' and (data_changed or statuses_changed):
            # Only reachable for a legacy raw 'approved' row: the canonical state is
            # locked above and a real reopen goes through transition with a reason.
            next_status = 'draft'
            clear_approval = True
        else:
            # The status hint ('draft'/'submitted') is never a lifecycle command: a save
            # neither regresses a reviewed draft nor submits it past the section gate.
            next_status = old_overall_status
            clear_approval = False

        conn.execute(
            '''UPDATE project_drafts
               SET title = ?, draft_data = ?, section_statuses = ?, status = ?,
                   revision = COALESCE(revision, 0) + 1, data_bytes = ?,
                   has_slides = ?, has_maps = ?, updated_at = ?
               WHERE id = ?''',
            (title, draft_json, statuses_json, next_status, data_bytes, has_slides, has_maps, now, existing['id'])
        )
        if clear_approval:
            _clear_draft_approval_fields(conn, existing['id'])
        conn.commit()
        return draft_id

    statuses = section_statuses if isinstance(section_statuses, dict) else {}
    # A draft is born 'draft' — no save payload may create one already inside a
    # gate state; every state past it is earned through the lifecycle.
    conn.execute(
        '''INSERT INTO project_drafts
           (id, tenant_id, user_id, title, draft_data, section_statuses, status,
            revision, data_bytes, has_slides, has_maps, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (draft_id, tenant_id, user_id, title, draft_json, json.dumps(statuses, ensure_ascii=False),
         'draft', 1, data_bytes, has_slides, has_maps, now, now)
    )
    conn.commit()
    return draft_id


def find_draft_snapshots(tenant_id, draft_ids=None):
    """Snapshots of project data that survive an emptied draft, newest first.

    Every generated presentation stored the whole ``tenantProjectData`` of the moment, and it
    carries its own draft id, so a draft that lost its fields can be read back from here.

    When ``draft_ids`` is given, only presentations linked to those drafts are
    read and parsed, so a list screen showing a page of drafts does not pay for
    parsing every presentation payload of the tenant.
    """
    conn = get_db()
    wanted = None
    if draft_ids is not None:
        wanted = {str(d) for d in (draft_ids or []) if str(d or '').strip()}
        if not wanted:
            return []
        marks = ', '.join(['?'] * len(wanted))
        rows = conn.execute(
            '''SELECT id, title, draft_id, project_data, slide_count, created_at, updated_at
               FROM presentations WHERE tenant_id = ? AND draft_id IN (%s)
               ORDER BY created_at DESC''' % marks,
            [tenant_id] + sorted(wanted),
        ).fetchall()
        legacy = conn.execute(
            '''SELECT id, title, draft_id, project_data, slide_count, created_at, updated_at
               FROM presentations WHERE tenant_id = ? AND (draft_id IS NULL OR draft_id = '')
               ORDER BY created_at DESC''',
            (tenant_id,),
        ).fetchall()
        rows = list(rows) + [r for r in legacy if _snapshot_draft_id(r) in wanted]
        try:
            rows.sort(key=lambda r: str(r['created_at'] or ''), reverse=True)
        except Exception:
            pass
    else:
        rows = conn.execute(
            '''SELECT id, title, project_data, slide_count, created_at, updated_at
               FROM presentations WHERE tenant_id = ? ORDER BY created_at DESC''',
            (tenant_id,),
        ).fetchall()
    snapshots = []
    for row in rows:
        payload = _json_object(row['project_data'])
        if not payload:
            continue
        snapshots.append({
            'presentation_id': row['id'],
            'title': row['title'] or '',
            'draft_id': payload.get('draftId') or payload.get('draft_id') or '',
            'slide_count': row['slide_count'] or 0,
            'created_at': row['created_at'],
            'field_count': len(_draft_content_keys(payload)),
            'project_data': payload,
        })
    return snapshots


def _snapshot_draft_id(row):
    """Draft id carried by a presentation row, via column or legacy payload."""
    try:
        direct = (row['draft_id'] if 'draft_id' in row.keys() else '') or ''
    except Exception:
        direct = ''
    if direct:
        return str(direct)
    try:
        payload = _json_object(row['project_data'])
    except Exception:
        return ''
    return str(payload.get('draftId') or payload.get('draft_id') or '')


def get_draft_field_counts(tenant_id, draft_ids):
    """Filled-field counts for a page of drafts with one query and no hydration."""
    wanted = [str(d) for d in (draft_ids or []) if str(d or '').strip()][:200]
    if not wanted:
        return {}
    conn = get_db()
    marks = ', '.join(['?'] * len(wanted))
    counts = {}
    for row in conn.execute(
        'SELECT id, draft_data FROM project_drafts WHERE tenant_id = ? AND id IN (%s)' % marks,
        [tenant_id] + wanted,
    ).fetchall():
        try:
            payload = _json_object(row['draft_data'])
        except Exception:
            payload = {}
        counts[str(row['id'])] = len(_draft_content_keys(payload))
    return counts


def restore_draft_from_snapshot(tenant_id, draft_id, snapshot_data):
    """Fill a draft's missing fields from a snapshot without overwriting what it still holds."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ?', (draft_id, tenant_id)
    ).fetchone()
    if not row or not isinstance(snapshot_data, dict):
        return None
    current = _json_object(row['draft_data'])
    merged = dict(current)
    restored = []
    for key, value in snapshot_data.items():
        if key in ('draftId', 'draft_id'):
            continue
        if _has_content(current.get(key)) or not _has_content(value):
            continue
        merged[key] = value
        restored.append(key)
    if not restored:
        return []
    merged.pop('draftId', None)
    merged.pop('draft_id', None)
    draft_json = json.dumps(merged, ensure_ascii=False)
    title = str(merged.get('project_name') or merged.get('projectName')
                or row['title'] or 'مسودة مشروع بدون عنوان').strip()[:200]
    conn.execute(
        '''UPDATE project_drafts
           SET title = ?, draft_data = ?, data_bytes = ?,
               revision = COALESCE(revision, 0) + 1, updated_at = ?
           WHERE id = ?''',
        (title, draft_json, len(draft_json.encode('utf-8')), _utcnow().isoformat(), draft_id)
    )
    conn.commit()
    print(f'[DRAFT RESTORE] Draft {draft_id} regained {len(restored)} fields: {sorted(restored)[:12]}')
    return restored


def get_project_draft(tenant_id, user_id):
    """Get the latest unified draft for one tenant actor."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_drafts WHERE tenant_id = ? AND user_id = ? ORDER BY updated_at DESC LIMIT 1',
        (tenant_id, user_id)
    ).fetchone()
    return _hydrate_project_draft(row)


def get_all_project_draft_summaries(tenant_id, limit=50, offset=0, search='', status='', date_from='', date_to='', accessible_ids=None):
    """Return lightweight draft metadata without hydrating project payloads.

    ``accessible_ids`` scopes the list to the drafts a project-scoped user may
    see (t20); ``None`` keeps the tenant-wide listing."""
    conn = get_db()
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if accessible_ids is not None:
        ids = [str(i) for i in accessible_ids]
        if not ids:
            return []
        clauses.append('id IN (' + ','.join('?' * len(ids)) + ')')
        params.extend(ids)
    if str(search or '').strip():
        clauses.append('LOWER(title) LIKE ?')
        params.append('%' + str(search).strip().lower() + '%')
    if status == 'draft':
        clauses.append("COALESCE(status, 'draft') NOT IN ('pending_approval', 'approved', 'sections_approved', 'final_approval_pending')")
    elif status in {'pending_approval', 'pending'}:
        clauses.append("status IN ('pending_approval', 'section_approval_pending', 'generation_approval_pending', 'final_approval_pending')")
    elif status == 'approved':
        clauses.append("status IN ('approved', 'sections_approved')")
    elif status in PROPOSAL_LIFECYCLE_STATES:
        clauses.append('status = ?')
        params.append(status)
    elif status:
        clauses.append('status = ?')
        params.append(status)
    if date_from:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) >= ?')
        params.append(str(date_from)[:10])
    if date_to:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) <= ?')
        params.append(str(date_to)[:10])
    params.extend([limit, offset])
    rows = conn.execute(
        '''SELECT id, tenant_id, user_id, title, section_statuses, status, revision,
                  data_bytes, has_slides, has_maps, requested_by, requested_by_name,
                  requested_at, reviewed_by, reviewed_by_name, review_note, reviewed_at,
                  created_at, updated_at
           FROM project_drafts
           WHERE ''' + ' AND '.join(clauses) + '''
           ORDER BY updated_at DESC
           LIMIT ? OFFSET ?''',
        params
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['section_statuses'] = _json_object(item.get('section_statuses'))
        item['title'] = item.get('title') or 'مسودة مشروع بدون عنوان'
        item['has_slides'] = bool(item.get('has_slides'))
        item['has_maps'] = bool(item.get('has_maps'))
        result.append(item)
    return result


def get_all_project_drafts(tenant_id):
    """Get all saved project drafts for a tenant, including full payloads."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM project_drafts WHERE tenant_id = ? ORDER BY updated_at DESC',
        (tenant_id,)
    ).fetchall()
    return [_hydrate_project_draft(row) for row in rows]


def get_project_draft_by_id(tenant_id, draft_id):
    """Fetch a draft for review while enforcing tenant isolation."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (draft_id, tenant_id)
    ).fetchone()
    return _hydrate_project_draft(row)


def delete_project_draft_by_id(tenant_id, draft_id):
    """Delete a specific project draft by ID."""
    conn = get_db()
    conn.execute('DELETE FROM project_drafts WHERE id = ? AND tenant_id = ?', (draft_id, tenant_id))
    conn.commit()
    return True


def get_pending_project_drafts(tenant_id):
    """Return only this tenant's drafts awaiting overall approval."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM project_drafts WHERE tenant_id = ? AND status IN ('pending_approval', 'section_approval_pending', 'generation_approval_pending', 'final_approval_pending') ORDER BY requested_at DESC",
        (tenant_id,)
    ).fetchall()
    return [_hydrate_project_draft(row) for row in rows]


def delete_project_draft(tenant_id, user_id):
    """Delete a user's own draft from the current tenant."""
    conn = get_db()
    cursor = conn.execute(
        'DELETE FROM project_drafts WHERE tenant_id = ? AND user_id = ?',
        (tenant_id, user_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def update_draft_section_status(tenant_id, user_id, section_key, section_status, draft_id=None):
    """Update one section in a unified draft, resetting overall approval if needed."""
    return update_draft_section_statuses(tenant_id, user_id, {section_key: section_status}, draft_id=draft_id)


def update_draft_section_statuses(tenant_id, user_id, updates, draft_id=None):
    """Merge section statuses into a draft without losing a concurrent update.

    The whole statuses map lives in one JSON column, so eight parallel 'approve' calls each
    read the same snapshot and the last write won: the screen showed every section approved
    while the database had kept only some. The write is therefore conditional on the value
    that was read, and retried when another request got there first.
    """
    if not isinstance(updates, dict) or not updates:
        return False
    if any(status not in SECTION_DRAFT_STATUSES for status in updates.values()):
        return False
    conn = get_db()
    for attempt in range(6):
        draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
        if draft and draft.get('user_id') != user_id:
            draft = None
        if not draft:
            # A status click can occur before the first explicit Save action.
            save_project_draft(tenant_id, user_id, {}, {}, 'draft', draft_id=draft_id)
            draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
            if not draft:
                return False
        norm_status = normalize_proposal_status(draft.get('status'))
        if proposal_status_is_locked(norm_status):
            raise DraftLocked(draft['id'], norm_status)
        statuses = dict(draft.get('section_statuses') or {})
        expected = json.dumps(statuses, ensure_ascii=False)
        changed = any(statuses.get(key) != value for key, value in updates.items())
        statuses.update(updates)
        # Toggling a section after the draft entered review or passed the section
        # gate voids that state; the draft goes back to sections being worked on.
        resets_approval = changed and norm_status in {
            'section_approval_pending', 'sections_approved', 'generated_draft'}
        next_status = 'sections_in_progress' if resets_approval else (draft.get('status') or 'draft')
        cursor = conn.execute(
            '''UPDATE project_drafts SET section_statuses = ?, status = ?, updated_at = ?
               WHERE id = ? AND COALESCE(section_statuses, '') IN (?, ?)''',
            (json.dumps(statuses, ensure_ascii=False), next_status, _utcnow().isoformat(),
             draft['id'], expected, '' if expected == '{}' else expected)
        )
        if getattr(cursor, 'rowcount', 1) == 0:
            conn.commit()
            continue
        if resets_approval:
            _clear_draft_approval_fields(conn, draft['id'])
        conn.commit()
        if resets_approval:
            try:
                record_audit_event(
                    tenant_id=tenant_id,
                    action='proposal_status_transition',
                    entity_type='project_draft',
                    entity_id=draft['id'],
                    user_id=user_id,
                    entity_name=draft.get('title') or 'مشروع',
                    old_value={'status': norm_status},
                    new_value={'status': 'sections_in_progress'},
                    metadata={
                        'from_status': norm_status,
                        'to_status': 'sections_in_progress',
                        'reason': 'تعديل حالة قسم أبطل حالة الاعتماد القائمة',
                    },
                    created_at=_utcnow().isoformat(),
                )
            except Exception:
                pass
        return True
    print(f'[DRAFT SECTIONS] gave up merging {list(updates)} after repeated concurrent writes')
    return False


def update_draft_section_status_by_id(tenant_id, draft_id, updates):
    """Merge section statuses into one draft by id without an owner check.

    Version decisions are recorded by an approver who may not own the draft,
    so the mirror write cannot require the actor to match the draft owner.
    Tenant isolation still applies. The concurrent-merge guard matches
    update_draft_section_statuses.
    """
    if not isinstance(updates, dict) or not updates:
        return False
    if any(status not in SECTION_DRAFT_STATUSES for status in updates.values()):
        return False
    if not draft_id:
        return False
    conn = get_db()
    for _attempt in range(6):
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if not draft:
            return False
        norm_status = normalize_proposal_status(draft.get('status'))
        if proposal_status_is_locked(norm_status):
            raise DraftLocked(draft['id'], norm_status)
        statuses = dict(draft.get('section_statuses') or {})
        expected = json.dumps(statuses, ensure_ascii=False)
        changed = any(statuses.get(key) != value for key, value in updates.items())
        statuses.update(updates)
        resets_approval = changed and norm_status in {
            'section_approval_pending', 'sections_approved', 'generated_draft'}
        next_status = 'sections_in_progress' if resets_approval else (draft.get('status') or 'draft')
        cursor = conn.execute(
            '''UPDATE project_drafts SET section_statuses = ?, status = ?, updated_at = ?
               WHERE id = ? AND tenant_id = ? AND COALESCE(section_statuses, '') IN (?, ?)''',
            (json.dumps(statuses, ensure_ascii=False), next_status, _utcnow().isoformat(),
             draft['id'], tenant_id, expected, '' if expected == '{}' else expected)
        )
        if getattr(cursor, 'rowcount', 1) == 0:
            conn.commit()
            continue
        if resets_approval:
            _clear_draft_approval_fields(conn, draft['id'])
        conn.commit()
        return True
    print(f'[DRAFT SECTIONS] gave up merging {list(updates)} by id after repeated concurrent writes')
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Section versions: immutable per-section snapshots tied to approval.
#
# Spec (Omran analysis sections 6, 8.1, 19): every send for approval stores an
# independent copy of that section inputs under the next version number, and
# the approval decision names that number instead of the live values. Sections
# without any version keep the legacy toggle path, while a section that has a
# version must be approved through its snapshot.
# ─────────────────────────────────────────────────────────────────────────────

SECTION_VERSION_STATUSES = {'pending', 'approved', 'returned', 'rejected', 'superseded', 'cancelled'}
SECTION_VERSION_DECISIONS = {'approved', 'returned', 'rejected'}

BASE_SECTION_KEYS = {
    'basic', 'location', 'land_croquis', 'contact',
    'section-timeline', 'section-financial-calc', 'section-team',
    'section-market-study', 'section-visual-concept', 'section-executive-content',
}


def section_snapshot_hash(snapshot):
    """Stable sha256 over the canonical JSON of a section snapshot."""
    try:
        canonical = json.dumps(snapshot if isinstance(snapshot, dict) else {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        canonical = '{}'
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _known_section_keys(conn, tenant_id, draft_statuses=None):
    """Section keys a version may be opened for: base, custom and already stored."""
    keys = set(BASE_SECTION_KEYS)
    try:
        for row in conn.execute(
            'SELECT section_key FROM tenant_custom_sections WHERE tenant_id = ? AND is_active = 1',
            (tenant_id,),
        ).fetchall():
            if row['section_key']:
                keys.add(row['section_key'])
    except Exception:
        pass
    for key in (draft_statuses or {}):
        if key:
            keys.add(key)
    return keys


def _section_version_public(row, include_snapshot=False):
    item = dict(row)
    raw = item.pop('snapshot_data', None)
    if include_snapshot:
        try:
            item['snapshot'] = json.loads(raw or '{}')
        except (TypeError, ValueError):
            item['snapshot'] = {}
        if not isinstance(item.get('snapshot'), dict):
            item['snapshot'] = {}
    # d05: an approved version past its validity window is no longer a gate
    # the project can rely on — it must be sent and approved again.
    item['is_expired'] = False
    if item.get('status') == 'approved' and item.get('expires_at'):
        try:
            item['is_expired'] = datetime.fromisoformat(str(item['expires_at'])) < _utcnow()
        except (TypeError, ValueError):
            item['is_expired'] = False
    return item


def create_section_version(tenant_id, draft_id, section_key, snapshot, created_by, created_by_name,
                           allow_supersede=False):
    """Store an immutable snapshot as the next version of a draft section.

    A live pending version blocks a new send (t13-04) unless the caller
    explicitly supersedes it, so a request under review is never dropped
    silently. Returns the stored row metadata, or a dict with an error key
    when the draft or section is unknown.
    """
    if not isinstance(section_key, str) or not section_key.strip() or len(section_key) > 64:
        return {'error': 'unknown_section'}
    if not isinstance(snapshot, dict):
        return {'error': 'invalid_snapshot'}
    section_key = section_key.strip()
    conn = get_db()
    draft = conn.execute(
        'SELECT id, status, section_statuses FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (draft_id, tenant_id),
    ).fetchone()
    if not draft:
        return {'error': 'draft_not_found'}
    if proposal_status_is_locked(draft['status']):
        return {'error': 'draft_locked', 'status': normalize_proposal_status(draft['status'])}
    if section_key not in _known_section_keys(conn, tenant_id, _json_object(draft['section_statuses'])):
        return {'error': 'unknown_section'}
    pending = conn.execute(
        "SELECT id, version_number FROM section_versions "
        "WHERE draft_id = ? AND section_key = ? AND status = 'pending'",
        (draft_id, section_key),
    ).fetchone()
    if pending and not allow_supersede:
        return {'error': 'version_pending_exists', 'version_id': pending['id'],
                'version_number': pending['version_number']}
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    digest = section_snapshot_hash(snapshot)
    version_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    for _attempt in range(3):
        current = conn.execute(
            'SELECT COALESCE(MAX(version_number), 0) AS top FROM section_versions WHERE draft_id = ? AND section_key = ?',
            (draft_id, section_key),
        ).fetchone()
        next_number = int((current['top'] if current else 0) or 0) + 1
        try:
            conn.execute(
                'UPDATE section_versions SET status = ? WHERE draft_id = ? AND section_key = ? AND status = ?',
                ('superseded', draft_id, section_key, 'pending'),
            )
            conn.execute(
                '''INSERT INTO section_versions
                   (id, tenant_id, draft_id, section_key, version_number, snapshot_data,
                    snapshot_hash, status, created_by, created_by_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (version_id, tenant_id, draft_id, section_key, next_number, snapshot_json,
                 digest, 'pending', created_by, created_by_name, now),
            )
            conn.commit()
            break
        except Exception:
            conn.rollback()
    else:
        return {'error': 'version_conflict'}
    row = conn.execute('SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()
    if not row:
        return {'error': 'version_conflict'}
    try:
        update_draft_section_status_by_id(tenant_id, draft_id, {section_key: 'pending'})
    except Exception:
        pass
    try:
        draft_row = get_project_draft_by_id(tenant_id, draft_id)
        if draft_row:
            curr_status = normalize_proposal_status(draft_row.get('status'))
            if curr_status in {'draft', 'sections_in_progress', 'rejected_for_revision'}:
                transition_project_draft_status(
                    tenant_id, draft_id, 'section_approval_pending',
                    actor_id=created_by, actor_name=created_by_name,
                    reason=f'إرسال قسم {section_key} للاعتماد',
                )
    except Exception:
        pass
    return _section_version_public(row)


def list_section_versions(tenant_id, draft_id, section_key=None):
    """Newest-first version metadata for a draft, without snapshot payloads."""
    conn = get_db()
    if section_key:
        rows = conn.execute(
            '''SELECT * FROM section_versions WHERE tenant_id = ? AND draft_id = ? AND section_key = ?
               ORDER BY version_number DESC''',
            (tenant_id, draft_id, section_key),
        ).fetchall()
    else:
        rows = conn.execute(
            '''SELECT * FROM section_versions WHERE tenant_id = ? AND draft_id = ?
               ORDER BY section_key ASC, version_number DESC''',
            (tenant_id, draft_id),
        ).fetchall()
    return [_section_version_public(row) for row in rows]


def get_section_version(tenant_id, version_id, include_snapshot=True):
    """One tenant-scoped version, with its immutable snapshot on request."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM section_versions WHERE id = ? AND tenant_id = ?', (version_id, tenant_id)
    ).fetchone()
    return _section_version_public(row, include_snapshot=include_snapshot) if row else None


def section_versions_overview(tenant_id, draft_id):
    """Latest version per section: number, status and hash for gates and locks."""
    overview = {}
    for item in list_section_versions(tenant_id, draft_id):
        if item['section_key'] not in overview:
            overview[item['section_key']] = item
    return overview


def pending_section_versions(tenant_id, draft_id, section_keys):
    """Subset of the given sections that currently await a version decision."""
    wanted = [key for key in (section_keys or []) if isinstance(key, str) and key]
    if not wanted:
        return []
    overview = section_versions_overview(tenant_id, draft_id)
    return [key for key in wanted if (overview.get(key) or {}).get('status') == 'pending']


SECTION_APPROVAL_DEFAULT_DAYS = int(os.environ.get('SECTION_APPROVAL_DAYS', '30'))


def get_section_approval_validity_days(tenant_id):
    """d05: how long a decided section approval stays valid before re-review.

    The tenant sets the window through ``section_approval_days`` in branding;
    missing or non-positive values fall back to the platform default so the
    expiry rule can never be switched off by accident.
    """
    try:
        branding = get_branding(tenant_id) or {}
        raw = branding.get('section_approval_days')
        days = int(raw) if raw not in (None, '') else SECTION_APPROVAL_DEFAULT_DAYS
        return days if days > 0 else SECTION_APPROVAL_DEFAULT_DAYS
    except Exception:
        return SECTION_APPROVAL_DEFAULT_DAYS


def expired_approved_sections(tenant_id, draft_id):
    """Sections whose latest approved version passed its validity window."""
    overview = section_versions_overview(tenant_id, draft_id)
    return [key for key, meta in overview.items()
            if meta.get('status') == 'approved' and meta.get('is_expired')]


GENERATION_INPUT_EXCLUDED_KEYS = {
    # Generation outputs and run state — never part of the priced inputs.
    'tenantSlidesData', 'tenantSlidePlan', 'slide_generation_checkpoint',
    'tenantCreativeImages', 'pageDrafts',
    # Working/chat state that does not feed the generation prompts.
    'designerChat', 'designerChatSessions', 'chatHistory', 'draftHistory',
    'tenantArchiveCache',
    # Identity/bookkeeping fields the client round-trips.
    'draftId', 'draft_id', 'schema_version', 'sectionStatuses',
}


def draft_generation_input_hash(draft_data):
    """Stable hash over a draft's generation inputs — outputs excluded.

    Slide data, the plan and checkpoints are written by the run itself, so
    hashing them in would make the approved snapshot drift mid-run while the
    real inputs stay untouched.
    """
    data = draft_data if isinstance(draft_data, dict) else {}
    inputs = {key: value for key, value in data.items()
              if key not in GENERATION_INPUT_EXCLUDED_KEYS}
    return section_snapshot_hash(inputs)


def _presentation_review_hash(presentation):
    """Semantic hash of what the final approver reviews: slides + project data."""
    slides = presentation.get('slides_data')
    if isinstance(slides, str):
        try:
            slides = json.loads(slides)
        except (TypeError, ValueError):
            slides = None
    project = presentation.get('project_data')
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (TypeError, ValueError):
            project = None
    try:
        canonical = json.dumps({'slides': slides, 'project': project},
                               sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = '{}'
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def decide_section_version(tenant_id, version_id, decision, decided_by, decided_by_name, note=None):
    """Record an approval decision against one immutable version.

    Only a pending version can be decided. A return or rejection needs a reason,
    because the editor must know what to fix before the next send.
    """
    if decision not in SECTION_VERSION_DECISIONS:
        return {'error': 'invalid_decision'}
    clean_note = str(note or '').strip()
    if decision in {'returned', 'rejected'} and not clean_note:
        return {'error': 'note_required'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM section_versions WHERE id = ? AND tenant_id = ?', (version_id, tenant_id)
    ).fetchone()
    if not row:
        return {'error': 'version_not_found'}
    if row['status'] != 'pending':
        return {'error': 'version_not_pending'}
    draft_row = conn.execute(
        'SELECT status FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (row['draft_id'], tenant_id),
    ).fetchone()
    if draft_row and proposal_status_is_locked(draft_row['status']):
        return {'error': 'draft_locked', 'status': normalize_proposal_status(draft_row['status'])}

    is_self_approval = bool(row['created_by'] and decided_by and str(row['created_by']) == str(decided_by))
    if is_self_approval:
        # d01: self-approval of one's own section is a tenant policy — the
        # default 'allow' records it with an audit note; 'block' refuses it.
        policy = get_tenant_policy(tenant_id, 'section_self_approval', 'allow')
        if policy == 'block':
            return {'error': 'self_approval_blocked_by_policy'}

    expires_at = None
    if decision == 'approved':
        # d05: an approval is valid for a bounded window; after it the section
        # has to be sent and decided again before the file can move forward.
        expires_at = (_utcnow() + timedelta(
            days=get_section_approval_validity_days(tenant_id))).isoformat()
    conn.execute(
        '''UPDATE section_versions SET status = ?, decided_by = ?, decided_by_name = ?,
           decision_note = ?, decided_at = ?, expires_at = ? WHERE id = ?''',
        (decision, decided_by, decided_by_name, clean_note or None,
         _utcnow().isoformat(), expires_at, version_id),
    )
    conn.commit()
    updated = conn.execute('SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()
    res = _section_version_public(updated)
    if is_self_approval:
        res['is_self_approval'] = True

    draft_id = row['draft_id']
    section_key = row['section_key']
    try:
        mirror = 'approved' if decision == 'approved' else 'draft'
        update_draft_section_status_by_id(tenant_id, draft_id, {section_key: mirror})
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if draft:
            if decision == 'approved':
                statuses = draft.get('section_statuses') or {}
                if statuses and all(v == 'approved' for v in statuses.values()):
                    transition_project_draft_status(
                        tenant_id, draft_id, 'sections_approved',
                        actor_id=decided_by, actor_name=decided_by_name,
                        reason='اعتماد جميع أقسام العرض',
                    )
            elif decision in {'returned', 'rejected'}:
                transition_project_draft_status(
                    tenant_id, draft_id, 'rejected_for_revision',
                    actor_id=decided_by, actor_name=decided_by_name,
                    reason=clean_note or f'إعادة قسم {section_key} للتعديل',
                )
    except Exception:
        pass

    return res


def cancel_section_version(tenant_id, version_id, cancelled_by, cancelled_by_name):
    """Withdraw a pending send so the editor can keep working on a later draft.

    Only a pending version can be cancelled. The row stays in history with
    status cancelled and the actor who withdrew it, so the request does not
    vanish without a trace.
    """
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM section_versions WHERE id = ? AND tenant_id = ?', (version_id, tenant_id)
    ).fetchone()
    if not row:
        return {'error': 'version_not_found'}
    if row['status'] != 'pending':
        return {'error': 'version_not_pending'}
    draft_row = conn.execute(
        'SELECT status FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (row['draft_id'], tenant_id),
    ).fetchone()
    if draft_row and proposal_status_is_locked(draft_row['status']):
        return {'error': 'draft_locked', 'status': normalize_proposal_status(draft_row['status'])}
    conn.execute(
        '''UPDATE section_versions SET status = ?, decided_by = ?, decided_by_name = ?,
           decided_at = ? WHERE id = ?''',
        ('cancelled', cancelled_by, cancelled_by_name,
         _utcnow().isoformat(), version_id),
    )
    conn.commit()
    updated = conn.execute('SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()

    draft_id = row['draft_id']
    section_key = row['section_key']
    try:
        update_draft_section_status_by_id(tenant_id, draft_id, {section_key: 'draft'})
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if draft:
            curr = normalize_proposal_status(draft.get('status'))
            if curr == 'section_approval_pending':
                overview = section_versions_overview(tenant_id, draft_id)
                has_pending = any(v.get('status') == 'pending' for v in overview.values())
                if not has_pending:
                    transition_project_draft_status(
                        tenant_id, draft_id, 'sections_in_progress',
                        actor_id=cancelled_by, actor_name=cancelled_by_name,
                        reason=f'إلغاء طلب اعتماد قسم {section_key}',
                    )
    except Exception:
        pass

    return _section_version_public(updated)


def diff_section_versions(tenant_id, version_id, base_version_id=None):
    """Structured comparison between a target section version and a base version.

    If base_version_id is not specified, compares against the immediately preceding
    version number for the same section. If no previous version exists, compares against empty.
    Returns categorized fields, attachments, validation readiness, and change counters.
    """
    target = get_section_version(tenant_id, version_id, include_snapshot=True)
    if not target:
        return {'error': 'version_not_found'}

    conn = get_db()
    draft_id = target['draft_id']
    section_key = target['section_key']

    if base_version_id:
        base = get_section_version(tenant_id, base_version_id, include_snapshot=True)
        if not base or base.get('draft_id') != draft_id or base.get('section_key') != section_key:
            return {'error': 'base_version_not_found'}
        base_snapshot = base.get('snapshot') or {}
        base_version_number = base.get('version_number')
        base_created_at = base.get('created_at')
    else:
        prev_row = conn.execute(
            '''SELECT * FROM section_versions
               WHERE tenant_id = ? AND draft_id = ? AND section_key = ? AND version_number < ?
               ORDER BY version_number DESC LIMIT 1''',
            (tenant_id, draft_id, section_key, target['version_number']),
        ).fetchone()
        if prev_row:
            prev = _section_version_public(prev_row, include_snapshot=True)
            base_version_id = prev['id']
            base_version_number = prev['version_number']
            base_created_at = prev.get('created_at')
            base_snapshot = prev.get('snapshot') or {}
        else:
            base_version_id = None
            base_version_number = None
            base_created_at = None
            base_snapshot = {}

    target_snapshot = target.get('snapshot') or {}

    field_labels = {}
    for f in PREBUILT_FIELDS:
        field_labels[f['key']] = f.get('label') or f['key']
    try:
        for f in get_fields(tenant_id):
            if f.get('field_key'):
                field_labels[f['field_key']] = f.get('field_label') or f['field_key']
    except Exception:
        pass

    known_labels = {
        'timeline_table_data': 'الجدول الزمني ومراحل المشروع',
        'financial_study_model': 'الدراسة المالية والمؤشرات',
        'team_selection': 'فريق العمل والجهات المشاركة',
        'market_study_data': 'دراسة السوق وتحليل المنافسين',
        'visual_concept': 'التصور البصري والمخططات',
        'executive_content': 'المحتوى التنفيذي والملخص',
        'location_analysis_approved': 'اعتماد تحليل الموقع',
        'location_data_fetched_at': 'تاريخ جلب بيانات الموقع',
        'location_polygon_source': 'مصدر مضلع الموقع',
        'map_approvals': 'اعتمادات الخرائط',
        'land_documents_files': 'وثائق ومستندات الأرض',
        'land_photos': 'صور الأرض والموقع',
        'project_logo': 'شعار المشروع',
    }
    field_labels.update(known_labels)

    def _val_eq(v1, v2):
        if v1 == v2:
            return True
        try:
            return json.dumps(v1, ensure_ascii=False, sort_keys=True) == json.dumps(v2, ensure_ascii=False, sort_keys=True)
        except Exception:
            return False

    def _val_has_content(v):
        if v is None or v is False:
            return False
        if isinstance(v, str):
            return bool(v.strip())
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, dict):
            return any(_val_has_content(item) for item in v.values())
        if isinstance(v, (list, tuple, set)):
            return any(_val_has_content(item) for item in v)
        return True

    all_keys = sorted(set(target_snapshot.keys()) | set(base_snapshot.keys()))
    attachment_keys = {'land_documents_files', 'land_photos', 'project_logo', 'deed_file', 'croquis_file'}

    fields = []
    attachments = []
    modified_count = 0
    added_count = 0
    removed_count = 0
    unchanged_count = 0

    for key in all_keys:
        old_val = base_snapshot.get(key)
        new_val = target_snapshot.get(key)
        in_base = key in base_snapshot
        in_target = key in target_snapshot

        if not in_base and in_target:
            c_status = 'added'
            added_count += 1
        elif in_base and not in_target:
            c_status = 'removed'
            removed_count += 1
        elif _val_eq(old_val, new_val):
            c_status = 'unchanged'
            unchanged_count += 1
        else:
            c_status = 'modified'
            modified_count += 1

        label = field_labels.get(key) or key
        item = {
            'key': key,
            'label': label,
            'old_value': old_val,
            'new_value': new_val,
            'status': c_status,
        }
        if key in attachment_keys or 'file' in key or 'photo' in key:
            attachments.append(item)
        else:
            fields.append(item)

    missing_required = []
    for f in PREBUILT_FIELDS:
        if f.get('section_key') == section_key and f.get('required'):
            if not _val_has_content(target_snapshot.get(f['key'])):
                missing_required.append(f.get('label') or f['key'])
    try:
        for f in get_fields(tenant_id):
            if (f.get('section_key') or '') == section_key and f.get('is_required') and f.get('is_active', 1):
                fk = f.get('field_key')
                if fk and not _val_has_content(target_snapshot.get(fk)):
                    lbl = f.get('field_label') or fk
                    if lbl not in missing_required:
                        missing_required.append(lbl)
    except Exception:
        pass

    return {
        'version_id': target['id'],
        'draft_id': draft_id,
        'section_key': section_key,
        'version_number': target['version_number'],
        'status': target['status'],
        'created_at': target['created_at'],
        'created_by': target['created_by'],
        'created_by_name': target['created_by_name'],
        'decided_at': target.get('decided_at'),
        'decided_by': target.get('decided_by'),
        'decided_by_name': target.get('decided_by_name'),
        'decision_note': target.get('decision_note'),
        'is_self_approval': bool(target.get('created_by') and target.get('decided_by') and str(target['created_by']) == str(target['decided_by'])),
        'base_version_id': base_version_id,
        'base_version_number': base_version_number,
        'base_created_at': base_created_at,
        'summary': {
            'total_changes': modified_count + added_count + removed_count,
            'modified': modified_count,
            'added': added_count,
            'removed': removed_count,
            'unchanged': unchanged_count,
        },
        'fields': fields,
        'attachments': attachments,
        'validation': {
            'is_complete': len(missing_required) == 0,
            'missing_fields': missing_required,
        },
    }


def request_project_draft_approval(tenant_id, user_id, requested_by, requested_by_name, draft_id=None):
    """Submit a draft only after every tracked section is approved."""
    draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
    if draft and draft.get('user_id') != user_id:
        draft = None
    if not draft:
        return {'error': 'draft_not_found'}
    norm = normalize_proposal_status(draft.get('status'))
    if proposal_status_is_locked(norm):
        return {'error': 'draft_locked', 'status': norm}
    if norm == 'sections_approved':
        # Already past the section gate — asking again is a no-op success so a
        # client that re-submits after fixing staleness still lands cleanly.
        return get_project_draft_by_id(tenant_id, draft['id'])
    if norm not in {'draft', 'sections_in_progress', 'rejected_for_revision', 'section_approval_pending'}:
        # A draft already past the section gate cannot be re-submitted through it.
        return {'error': 'invalid_transition', 'current_status': norm}
    statuses = draft.get('section_statuses', {})
    if not statuses or any(value != 'approved' for value in statuses.values()):
        return {'error': 'sections_not_approved', 'section_statuses': statuses}
    expired = expired_approved_sections(tenant_id, draft['id'])
    if expired:
        return {'error': 'section_version_expired', 'sections': expired}
    conn = get_db()
    conn.execute(
        '''UPDATE project_drafts SET requested_by = ?, requested_by_name = ?,
           requested_at = ?, reviewed_by = NULL,
           reviewed_by_name = NULL, review_note = NULL, reviewed_at = NULL, updated_at = ?
           WHERE id = ? AND tenant_id = ?''',
        (requested_by, requested_by_name, _utcnow().isoformat(), _utcnow().isoformat(),
         draft['id'], tenant_id)
    )
    conn.commit()
    if norm != 'section_approval_pending':
        # Canonical state + audit event + presentation sync all come from the
        # transition authority; 'pending_approval' remains a readable alias.
        res = transition_project_draft_status(
            tenant_id, draft['id'], 'section_approval_pending',
            actor_id=requested_by, actor_name=requested_by_name,
            reason='طلب اعتماد المشروع',
        )
        if res.get('error'):
            return res
    return get_project_draft_by_id(tenant_id, draft['id'])


def review_project_draft(tenant_id, draft_id, review_status, reviewed_by, reviewed_by_name, note=None):
    """Record a tenant-scoped approval or return a draft for correction.

    Approval lands on the canonical ``sections_approved`` state — the draft passed
    the section gate and may now request generation. Returning for correction only
    makes sense for a pending request and requires a reason, matching the
    lifecycle rule for ``rejected_for_revision``.
    """
    if review_status not in {'approved', 'rejected'}:
        return {'error': 'invalid_status'}
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return {'error': 'draft_not_found'}
    norm = normalize_proposal_status(draft.get('status'))
    if review_status == 'approved':
        if norm not in {'draft', 'sections_in_progress', 'section_approval_pending'}:
            return {'error': 'draft_not_reviewable', 'status': norm}
        # The project-level approve cannot stand in for missing section
        # approvals — every tracked section must hold a valid approval first.
        statuses = draft.get('section_statuses') or {}
        if statuses and any(value != 'approved' for value in statuses.values()):
            return {'error': 'sections_not_approved', 'section_statuses': statuses}
        expired = expired_approved_sections(tenant_id, draft_id)
        if expired:
            return {'error': 'section_version_expired', 'sections': expired}
        target = 'sections_approved'
    else:
        if norm != 'section_approval_pending':
            return {'error': 'draft_not_pending', 'status': norm}
        if not str(note or '').strip():
            return {'error': 'reason_required'}
        target = 'rejected_for_revision'
    res = transition_project_draft_status(
        tenant_id, draft_id, target,
        actor_id=reviewed_by, actor_name=reviewed_by_name,
        reason=str(note or '').strip() or ('اعتماد المشروع' if review_status == 'approved' else None),
    )
    if res.get('error'):
        return res
    conn = get_db()
    conn.execute(
        '''UPDATE project_drafts SET reviewed_by = ?, reviewed_by_name = ?,
           review_note = ?, reviewed_at = ?, updated_at = ? WHERE id = ?''',
        (reviewed_by, reviewed_by_name, note, _utcnow().isoformat(),
         _utcnow().isoformat(), draft_id)
    )
    conn.commit()
    return {'success': True, 'draft': res.get('draft')}


def transition_project_draft_status(tenant_id, draft_id, target_status,
                                    actor_id=None, actor_name=None,
                                    actor_role=None, reason=None, metadata=None,
                                    manual=False):
    """Transition a project draft through the 11-state lifecycle with validation and immutable audit logging."""
    if not tenant_id or not draft_id or not target_status:
        return {'error': 'missing_arguments'}
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return {'error': 'draft_not_found'}

    current_status = draft.get('status') or 'draft'
    norm_current = normalize_proposal_status(current_status)
    norm_target = normalize_proposal_status(target_status)

    if not can_transition_proposal_status(norm_current, norm_target):
        return {
            'error': 'invalid_transition',
            'current_status': norm_current,
            'target_status': norm_target,
            'allowed_transitions': sorted(list(PROPOSAL_ALLOWED_TRANSITIONS.get(norm_current, []))),
        }

    if manual and norm_target not in PROPOSAL_MANUAL_TRANSITIONS.get(norm_current, set()):
        # A user may never hand-move a draft into a gate state; those belong to
        # the approval workflows that guard them.
        return {
            'error': 'manual_transition_not_allowed',
            'current_status': norm_current,
            'target_status': norm_target,
        }

    # Spec Section 8.4: Reopening an approved proposal requires a mandatory reason
    if norm_current == 'approved' and norm_target != 'archived':
        if not reason or not str(reason).strip():
            return {'error': 'reason_required', 'message': 'سبب التعديل بعد التعميد إلزامي'}

    # Spec Section 8.1 & 7: Rejection/Returning for revision requires a mandatory reason
    if norm_target == 'rejected_for_revision':
        if not reason or not str(reason).strip():
            return {'error': 'reason_required', 'message': 'سبب إعادة العرض للتعديل إلزامي'}

    now_iso = _utcnow().isoformat()
    conn = get_db()
    conn.execute(
        '''UPDATE project_drafts SET status = ?, updated_at = ? WHERE id = ? AND tenant_id = ?''',
        (norm_target, now_iso, draft_id, tenant_id)
    )
    # Also sync associated presentation status if any
    try:
        conn.execute(
            '''UPDATE presentations SET status = ?, updated_at = ?
               WHERE tenant_id = ? AND (draft_id = ? OR json_extract(project_data, '$.draftId') = ?)''',
            (norm_target, now_iso, tenant_id, draft_id, draft_id)
        )
    except Exception:
        pass
    # t18: archiving stamps the retention clock; restoring clears it.
    try:
        if norm_target == 'archived':
            conn.execute('UPDATE project_drafts SET archived_at = ? WHERE id = ?', (now_iso, draft_id))
            conn.execute(
                '''UPDATE presentations SET archived_at = ?
                   WHERE tenant_id = ? AND (draft_id = ? OR json_extract(project_data, '$.draftId') = ?)''',
                (now_iso, tenant_id, draft_id, draft_id)
            )
        elif norm_current == 'archived':
            conn.execute('UPDATE project_drafts SET archived_at = NULL WHERE id = ?', (draft_id,))
            conn.execute(
                '''UPDATE presentations SET archived_at = NULL
                   WHERE tenant_id = ? AND (draft_id = ? OR json_extract(project_data, '$.draftId') = ?)''',
                (tenant_id, draft_id, draft_id)
            )
    except Exception:
        pass
    # Leaving a gate state voids the request that put the draft there: a still-pending
    # approval would otherwise stay open and could later decide on a stale state.
    try:
        if norm_current == 'generation_approval_pending' and norm_target != 'generating':
            conn.execute(
                '''UPDATE generation_approvals SET status = 'cancelled', decision_note = ?
                   WHERE tenant_id = ? AND draft_id = ? AND status = 'pending' ''',
                ('أُلغي تلقائيًا عند مغادرة حالة انتظار اعتماد التوليد', tenant_id, draft_id),
            )
        if norm_current == 'final_approval_pending' and norm_target != 'approved':
            conn.execute(
                '''UPDATE final_file_approvals SET status = 'cancelled', decision_note = ?
                   WHERE tenant_id = ? AND status = 'pending' AND presentation_id IN (
                       SELECT id FROM presentations WHERE tenant_id = ? AND draft_id = ?)''',
                ('أُلغي تلقائيًا عند مغادرة حالة انتظار اعتماد الملف النهائي', tenant_id, tenant_id, draft_id),
            )
        if norm_current == 'generating' and norm_target != 'generated_draft':
            # Abandoning a run refunds its escrowed hold and closes the
            # approval it belonged to — never a bare status flip.
            stale = conn.execute(
                """SELECT * FROM point_reservations
                   WHERE tenant_id = ? AND status = 'reserved' AND draft_id = ?""",
                (tenant_id, draft_id),
            ).fetchall()
            for stale_row in stale:
                _settle_reservation_tx(
                    conn, tenant_id, stale_row, 'released', settled_by=actor_id,
                    note='تحرير تلقائي عند مغادرة حالة التوليد')
                if stale_row['generation_approval_id']:
                    conn.execute(
                        """UPDATE generation_approvals SET status = 'rejected', decision_note = ?
                           WHERE id = ? AND status = 'approved'""",
                        ('أُلغي عند مغادرة المسودة حالة التوليد', stale_row['generation_approval_id']),
                    )
    except Exception:
        pass
    conn.commit()

    # Record immutable audit event (T11 integration)
    event_meta = dict(metadata or {})
    if reason:
        event_meta['reason'] = str(reason).strip()
    event_meta['from_status'] = norm_current
    event_meta['to_status'] = norm_target

    try:
        record_audit_event(
            tenant_id=tenant_id,
            action='proposal_status_transition',
            entity_type='project_draft',
            entity_id=draft_id,
            user_id=actor_id,
            user_name=actor_name,
            user_role=actor_role,
            entity_name=draft.get('title') or 'مشروع',
            old_value={'status': norm_current},
            new_value={'status': norm_target, 'reason': reason},
            metadata=event_meta,
            created_at=now_iso,
        )
    except Exception as e:
        print(f'[AUDIT LOG] Warning: failed to log status transition: {e}')

    updated_draft = get_project_draft_by_id(tenant_id, draft_id)
    return {
        'success': True,
        'draft': updated_draft,
        'previous_status': norm_current,
        'current_status': norm_target,
        'state_info': PROPOSAL_LIFECYCLE_STATES.get(norm_target),
    }


def get_proposal_lifecycle_info(tenant_id, draft_id):
    """Return current state metadata, allowed next transitions, and transition history for a draft."""
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return None
    raw_status = draft.get('status') or 'draft'
    norm_status = normalize_proposal_status(raw_status)
    state_info = PROPOSAL_LIFECYCLE_STATES.get(norm_status, PROPOSAL_LIFECYCLE_STATES['draft'])
    allowed_keys = sorted(list(PROPOSAL_ALLOWED_TRANSITIONS.get(norm_status, set())))
    next_states = [
        {
            'status': k,
            'label': PROPOSAL_LIFECYCLE_STATES[k]['label'],
            'label_en': PROPOSAL_LIFECYCLE_STATES[k]['label_en'],
            'phase': PROPOSAL_LIFECYCLE_STATES[k]['phase'],
            'description': PROPOSAL_LIFECYCLE_STATES[k]['description'],
            'is_locked': PROPOSAL_LIFECYCLE_STATES[k]['is_locked'],
        }
        for k in allowed_keys if k in PROPOSAL_LIFECYCLE_STATES
    ]

    # Retrieve recent transitions from audit_events
    history = []
    try:
        audit_res = list_audit_events(
            tenant_id=tenant_id,
            entity_type='project_draft',
            entity_id=draft_id,
            action='proposal_status_transition',
            limit=20,
        )
        for ev in audit_res.get('events', []):
            history.append({
                'id': ev.get('id'),
                'created_at': ev.get('created_at'),
                'user_id': ev.get('user_id'),
                'user_name': ev.get('user_name'),
                'user_role': ev.get('user_role'),
                'from_status': (ev.get('old_value') or {}).get('status') if isinstance(ev.get('old_value'), dict) else None,
                'to_status': (ev.get('new_value') or {}).get('status') if isinstance(ev.get('new_value'), dict) else None,
                'reason': (ev.get('metadata') or {}).get('reason'),
            })
    except Exception:
        history = []

    return {
        'draft_id': draft_id,
        'title': draft.get('title') or 'مشروع بدون عنوان',
        'current_status': norm_status,
        'state_info': state_info,
        'is_locked': state_info.get('is_locked', False),
        'allowed_transitions': allowed_keys,
        'next_states': next_states,
        'history': history,
    }



def log_ai_rule_change(tenant_id, rule_category, rule_key, old_value, new_value,
                       risk_level='green', user_id=None, user_name=None):
    """Log a change to AI rules for audit and rollback."""
    conn = get_db()
    log_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO ai_rules_log
           (id, tenant_id, user_id, user_name, rule_category, rule_key, old_value, new_value, risk_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (log_id, tenant_id, user_id, user_name, rule_category, rule_key,
         str(old_value) if old_value is not None else None,
         str(new_value) if new_value is not None else None, risk_level)
    )
    conn.commit()
    return log_id


def get_ai_rules_log(tenant_id, limit=50):
    """Get recent AI rule changes for a tenant."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM ai_rules_log WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?',
        (tenant_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# AI Usage Metering (OpenRouter consumption per tenant, draft and presentation)
# ─────────────────────────────────────────────────────────────────────────────

AI_ATTEMPT_STATUSES = ('in_flight', 'pending', 'settled', 'unresolved', 'needs_review')
AI_COST_SOURCES = ('response', 'generation', 'review')


def _ai_usage_now_text():
    return _utcnow().strftime('%Y-%m-%d %H:%M:%S')


def _ai_usage_columns(conn):
    try:
        return {row['name'] for row in conn.execute('PRAGMA table_info(ai_usage_events)').fetchall()}
    except Exception:
        return set()


def _coerce_ai_cost(value):
    """Validate a provider dollar figure without ever turning unknown into zero.

    Returns (cost_float_or_None, raw_text_or_None). Unknown, non-numeric,
    non-finite and negative values all return (None, None) so the caller
    keeps the attempt pending instead of storing a misleading zero.
    """
    try:
        if value is None:
            return None, None
        if isinstance(value, bool):
            return None, None
        from decimal import Decimal, InvalidOperation
        import math as _math
        if isinstance(value, float) and (not _math.isfinite(value)):
            return None, None
        text = str(value).strip()
        if not text:
            return None, None
        amount = Decimal(text)
        if not amount.is_finite():
            return None, None
        if amount < 0:
            return None, None
        return float(amount), text
    except Exception:
        return None, None


def _derive_attempt_status(cost_usd, generation_id, explicit=None):
    if explicit in AI_ATTEMPT_STATUSES:
        return explicit
    if cost_usd is not None:
        return 'settled'
    if generation_id:
        return 'pending'
    return 'unresolved'


def _tenant_active_package_id(conn, tenant_id):
    """Package a new spend row burns under. None when the tenant has none."""
    try:
        if not tenant_id:
            return None
        row = conn.execute(
            'SELECT package_id FROM tenants WHERE id = ?', (str(tenant_id),)).fetchone()
        package_id = dict(row).get('package_id') if row else None
        return str(package_id) if package_id else None
    except Exception:
        return None


def record_ai_usage_event(tenant_id, model, flow='other', status='ok',
                          prompt_tokens=0, completion_tokens=0, total_tokens=0,
                          cost_usd=None, generation_id=None,
                          draft_id=None, presentation_id=None,
                          cost_source=None, attempt_status=None,
                          response_cost_usd=None, generation_cost_usd=None,
                          cost_raw=None, reconcile_attempts=0,
                          next_retry_at=None, package_id=None):
    """Persist one metered OpenRouter call.

    Token figures are copied verbatim from the provider response, never
    estimated. A row is written even when the provider returned no usage so
    the attempt itself stays visible. Unknown cost stays NULL and is never
    stored as zero. The source precision is preserved in cost_raw.
    """
    conn = get_db()
    cols = _ai_usage_columns(conn)
    cost_value, cost_text = _coerce_ai_cost(cost_usd)
    if cost_usd is not None and cost_value is None:
        cost_value, cost_text = None, None
    if cost_raw is None:
        cost_raw = cost_text
    if response_cost_usd is None and cost_source == 'response' and cost_value is not None:
        response_cost_usd = cost_value
    if generation_cost_usd is None and cost_source in ('generation', 'review') and cost_value is not None:
        generation_cost_usd = cost_value
    derived = _derive_attempt_status(cost_value, generation_id, attempt_status)
    if cost_source is not None and cost_source not in AI_COST_SOURCES:
        cost_source = None
    if cost_value is None:
        cost_source = None
    if package_id is None:
        package_id = _tenant_active_package_id(conn, tenant_id)
    event_id = str(uuid.uuid4())
    now_text = _ai_usage_now_text()
    has_package_col = 'package_id' in cols
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        conn.execute(
            '''INSERT INTO ai_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, model, status,
                prompt_tokens, completion_tokens, total_tokens, cost_usd, generation_id,
                cost_source, attempt_status, reconcile_attempts, next_retry_at, updated_at,
                response_cost_usd, generation_cost_usd, cost_raw{})
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?{})'''.format(
                ', package_id' if has_package_col else '',
                ', ?' if has_package_col else ''),
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other', model,
             status or 'ok', int(prompt_tokens or 0), int(completion_tokens or 0),
             int(total_tokens or 0), cost_value, generation_id,
             cost_source, derived, int(reconcile_attempts or 0), next_retry_at, now_text,
             response_cost_usd, generation_cost_usd, cost_raw)
            + ((package_id,) if has_package_col else ())
        )
    else:
        conn.execute(
            '''INSERT INTO ai_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, model, status,
                prompt_tokens, completion_tokens, total_tokens, cost_usd, generation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other', model,
             status or 'ok', int(prompt_tokens or 0), int(completion_tokens or 0),
             int(total_tokens or 0), cost_value, generation_id)
        )
    conn.commit()
    return event_id


def begin_ai_usage_attempt(tenant_id, model, flow='other', draft_id=None, presentation_id=None):
    """Create the single unified row for one real provider attempt before sending.

    The same row is later settled with the response, so one attempt never
    becomes two rows. Futures cancelled before sending must not call this.
    """
    return record_ai_usage_event(
        tenant_id, model or 'unknown', flow=flow or 'other', status='ok',
        prompt_tokens=0, completion_tokens=0, total_tokens=0,
        cost_usd=None, generation_id=None,
        draft_id=draft_id, presentation_id=presentation_id,
        cost_source=None, attempt_status='in_flight',
    )


def update_ai_usage_attempt(event_id, status=None, prompt_tokens=None,
                            completion_tokens=None, total_tokens=None,
                            generation_id=None, cost_usd=None, cost_source=None,
                            cost_raw=None, response_cost_usd=None,
                            generation_cost_usd=None, attempt_status=None,
                            reconcile_attempts=None, next_retry_at=None,
                            clear_next_retry=False):
    """Update the single row that owns one attempt. Never inserts a new cost row."""
    conn = get_db()
    cols = _ai_usage_columns(conn)
    row = conn.execute('SELECT * FROM ai_usage_events WHERE id = ?', (str(event_id),)).fetchone()
    if row is None:
        return False
    current = dict(row)
    assignments = []
    params = []
    if status is not None:
        assignments.append('status = ?')
        params.append(status)
    for key, value in (('prompt_tokens', prompt_tokens), ('completion_tokens', completion_tokens),
                       ('total_tokens', total_tokens)):
        if value is not None:
            try:
                assignments.append(f'{key} = ?')
                params.append(int(value or 0))
            except (TypeError, ValueError):
                pass
    if generation_id is not None:
        assignments.append('generation_id = ?')
        params.append(generation_id or None)
    if cost_usd is not None or cost_source is not None or cost_raw is not None:
        candidate = cost_usd if cost_usd is not None else current.get('cost_usd')
        coerced, raw = _coerce_ai_cost(candidate)
        if candidate is not None and coerced is None:
            pass
        else:
            if cost_usd is not None:
                assignments.append('cost_usd = ?')
                params.append(coerced)
                if 'cost_raw' in cols:
                    assignments.append('cost_raw = ?')
                    params.append(cost_raw if cost_raw is not None else raw)
            if cost_source is not None and 'cost_source' in cols:
                valid_source = cost_source if cost_source in AI_COST_SOURCES else None
                if coerced is None:
                    valid_source = None
                assignments.append('cost_source = ?')
                params.append(valid_source)
    if response_cost_usd is not None and 'response_cost_usd' in cols:
        coerced, _raw = _coerce_ai_cost(response_cost_usd)
        if coerced is not None:
            assignments.append('response_cost_usd = ?')
            params.append(coerced)
    if generation_cost_usd is not None and 'generation_cost_usd' in cols:
        coerced, _raw = _coerce_ai_cost(generation_cost_usd)
        if coerced is not None:
            assignments.append('generation_cost_usd = ?')
            params.append(coerced)
    if attempt_status is not None and 'attempt_status' in cols:
        if attempt_status in AI_ATTEMPT_STATUSES:
            assignments.append('attempt_status = ?')
            params.append(attempt_status)
    if reconcile_attempts is not None and 'reconcile_attempts' in cols:
        try:
            assignments.append('reconcile_attempts = ?')
            params.append(int(reconcile_attempts))
        except (TypeError, ValueError):
            pass
    if 'next_retry_at' in cols:
        if clear_next_retry:
            assignments.append('next_retry_at = ?')
            params.append(None)
        elif next_retry_at is not None:
            assignments.append('next_retry_at = ?')
            params.append(next_retry_at)
    if 'updated_at' in cols:
        assignments.append('updated_at = ?')
        params.append(_ai_usage_now_text())
    if not assignments:
        return True
    params.append(str(event_id))
    conn.execute(f"UPDATE ai_usage_events SET {', '.join(assignments)} WHERE id = ?", params)
    conn.commit()
    return True


def update_ai_usage_cost(event_id, cost_usd, cost_source='generation'):
    """Fill in the dollar cost of a usage event once the provider reports it.

    Existing rows are updated in place so a review never appends a second
    cost row. Invalid figures leave the attempt pending instead of zero.
    """
    coerced, raw = _coerce_ai_cost(cost_usd)
    if coerced is None:
        return False
    source = cost_source if cost_source in AI_COST_SOURCES else 'generation'
    conn = get_db()
    cols = _ai_usage_columns(conn)
    if {'cost_source', 'attempt_status', 'updated_at', 'generation_cost_usd',
        'response_cost_usd', 'cost_raw'} <= cols:
        extra_gen = ', generation_cost_usd = ?' if source in ('generation', 'review') else ''
        extra_resp = ', response_cost_usd = ?' if source == 'response' else ''
        params = [coerced, source, raw, _ai_usage_now_text()]
        if source in ('generation', 'review'):
            params.append(coerced)
        if source == 'response':
            params.append(coerced)
        params.append(str(event_id))
        conn.execute(
            'UPDATE ai_usage_events SET cost_usd = ?, cost_source = ?, cost_raw = ?, '
            f"attempt_status = 'settled', updated_at = ?{extra_gen}{extra_resp} WHERE id = ?",
            params
        )
    else:
        conn.execute(
            'UPDATE ai_usage_events SET cost_usd = ? WHERE id = ?',
            (coerced, str(event_id))
        )
    conn.commit()
    return True


def claim_ai_usage_reconcile_row(event_id, delay_seconds=300):
    """Claim one row for reconcile so parallel reviews never process it twice."""
    conn = get_db()
    cols = _ai_usage_columns(conn)
    if {'reconcile_attempts', 'next_retry_at', 'updated_at'} <= cols:
        from datetime import timedelta
        next_text = (_utcnow() + timedelta(seconds=max(1, int(delay_seconds or 0)))).strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute(
            'UPDATE ai_usage_events SET reconcile_attempts = COALESCE(reconcile_attempts, 0) + 1, '
            'next_retry_at = ?, updated_at = ? WHERE id = ? '
            "AND (next_retry_at IS NULL OR next_retry_at <= datetime('now'))",
            (next_text, _ai_usage_now_text(), str(event_id))
        )
        conn.commit()
        return (cursor.rowcount or 0) > 0
    return True


def get_ai_events_needing_reconcile(limit=10, tenant_id=None, draft_id=None,
                                    presentation_id=None, include_settled=False):
    """Oldest-first rows whose dollar cost still needs the provider.

    No age cutoff is applied here. Rows older than 24 hours stay eligible
    until they settle or exhaust their attempts and move to needs_review.
    """
    conn = get_db()
    cols = _ai_usage_columns(conn)
    has_status = 'attempt_status' in cols
    clauses = []
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    if include_settled:
        clauses.append('generation_id IS NOT NULL')
        if has_status:
            clauses.append("(attempt_status IS NULL OR attempt_status != 'needs_review')")
    else:
        clauses.append('generation_id IS NOT NULL')
        has_verify_cols = {'cost_source', 'generation_cost_usd'} <= cols
        if has_verify_cols:
            # /generation total_cost is the source of truth. Rows settled from
            # the chat response keep their provisional figure until one
            # generation lookup overwrites it, so the stored total converges
            # to the dashboard figure instead of sticking at a stale value.
            clauses.append("(cost_usd IS NULL OR (cost_source = 'response' AND generation_cost_usd IS NULL))")
        else:
            clauses.append('cost_usd IS NULL')
        if has_status:
            if has_verify_cols:
                clauses.append("(attempt_status IS NULL OR attempt_status NOT IN ('settled', 'needs_review') OR (attempt_status = 'settled' AND cost_source = 'response' AND generation_cost_usd IS NULL))")
            else:
                clauses.append("(attempt_status IS NULL OR attempt_status NOT IN ('settled', 'needs_review'))")
            clauses.append("(next_retry_at IS NULL OR next_retry_at <= datetime('now'))")
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    select_cols = ('id, tenant_id, draft_id, presentation_id, flow, model, status, '
                   'prompt_tokens, completion_tokens, total_tokens, cost_usd, generation_id, created_at')
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        select_cols += (', cost_source, attempt_status, reconcile_attempts, next_retry_at, '
                        'updated_at, response_cost_usd, generation_cost_usd, cost_raw')
    params.append(int(limit))
    rows = conn.execute(
        f'SELECT {select_cols} FROM ai_usage_events {where} '
        'ORDER BY created_at ASC LIMIT ?',
        params
    ).fetchall()
    return [dict(r) for r in rows]


def get_ai_usage_status_counts(tenant_id, draft_id=None, presentation_id=None):
    """Auditable per-scope counts with no misleading capped total."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    cols = _ai_usage_columns(conn)
    counts = {'total': 0, 'settled': 0, 'pending': 0, 'in_flight': 0,
              'unresolved': 0, 'needs_review': 0, 'unknown_cost': 0, 'pending_costs': 0}
    if 'attempt_status' in cols:
        for row in conn.execute(
            'SELECT COALESCE(attempt_status, '
            "CASE WHEN cost_usd IS NOT NULL THEN 'settled' "
            "WHEN generation_id IS NOT NULL THEN 'pending' "
            "ELSE 'unresolved' END) AS st, COUNT(*) AS n "
            f'FROM ai_usage_events {where} GROUP BY st',
            params
        ).fetchall():
            row = dict(row)
            key = str(row.get('st') or '')
            if key in counts:
                counts[key] = int(row.get('n') or 0)
            counts['total'] += int(row.get('n') or 0)
    else:
        row = dict(conn.execute(f'SELECT COUNT(*) AS n FROM ai_usage_events {where}', params).fetchone())
        counts['total'] = int(row.get('n') or 0)
        row = dict(conn.execute(
            f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NOT NULL', params).fetchone())
        counts['settled'] = int(row.get('n') or 0)
        row = dict(conn.execute(
            f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NULL AND generation_id IS NOT NULL',
            params).fetchone())
        counts['pending'] = int(row.get('n') or 0)
        counts['unresolved'] = counts['total'] - counts['settled'] - counts['pending']
    unknown = dict(conn.execute(
        f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NULL', params).fetchone())
    counts['unknown_cost'] = int(unknown.get('n') or 0)
    pending = dict(conn.execute(
        f'SELECT COUNT(*) AS n FROM ai_usage_events {where} AND cost_usd IS NULL AND generation_id IS NOT NULL',
        params).fetchone())
    counts['pending_costs'] = int(pending.get('n') or 0)
    if counts['in_flight'] or counts['pending']:
        state, label = 'pending', 'قيد الاستكمال'
    elif counts['unresolved'] or counts['needs_review']:
        state, label = 'needs_review', 'تحتاج مطابقة'
    else:
        state, label = 'settled', 'التكلفة المسجلة'
    counts['state'] = state
    counts['state_label'] = label
    return counts


def get_ai_usage_events_page(tenant_id, draft_id=None, presentation_id=None,
                             page=1, page_size=20):
    """Paginated provider attempts with generation id, cost, source and state."""
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(100, int(page_size or 20)))
    except (TypeError, ValueError):
        page_size = 20
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    cols = _ai_usage_columns(conn)
    total = int(dict(conn.execute(
        f'SELECT COUNT(*) AS n FROM ai_usage_events {where}', params).fetchone()).get('n') or 0)
    select_cols = ('id, draft_id, presentation_id, flow, model, status, prompt_tokens, '
                   'completion_tokens, total_tokens, cost_usd, generation_id, created_at')
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        select_cols += (', cost_source, attempt_status, reconcile_attempts, next_retry_at, '
                        'updated_at, response_cost_usd, generation_cost_usd, cost_raw')
    offset = (page - 1) * page_size
    rows = [dict(r) for r in conn.execute(
        f'SELECT {select_cols} FROM ai_usage_events {where} '
        'ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params + [page_size, offset]
    ).fetchall()]
    return {'items': rows, 'page': page, 'page_size': page_size, 'total': total,
            'pages': ((total + page_size - 1) // page_size) if total else 0}


def decimal_cost_total(values):
    """Sum dollar figures with Decimal so display rounding never rewrites history."""
    from decimal import Decimal
    total = Decimal('0')
    for value in (values or []):
        if value is None:
            continue
        try:
            if isinstance(value, bool):
                continue
            total += Decimal(str(value))
        except Exception:
            continue
    return total


def get_ai_usage_summary(tenant_id, draft_id=None, presentation_id=None, limit=50):
    """Tenant-scoped consumption totals grouped by flow and model, plus recent events."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    cols = _ai_usage_columns(conn)
    totals = dict(conn.execute(
        'SELECT COUNT(*) AS calls, '
        'COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, '
        'COALESCE(SUM(completion_tokens), 0) AS completion_tokens, '
        'COALESCE(SUM(total_tokens), 0) AS total_tokens, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {where}',
        params
    ).fetchone())
    by_flow = [dict(r) for r in conn.execute(
        'SELECT flow, COUNT(*) AS calls, '
        'COALESCE(SUM(total_tokens), 0) AS total_tokens, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {where} GROUP BY flow ORDER BY total_tokens DESC',
        params
    ).fetchall()]
    by_model = [dict(r) for r in conn.execute(
        'SELECT model, COUNT(*) AS calls, '
        'COALESCE(SUM(total_tokens), 0) AS total_tokens, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {where} GROUP BY model ORDER BY total_tokens DESC',
        params
    ).fetchall()]
    select_cols = ('id, draft_id, presentation_id, flow, model, status, prompt_tokens, '
                   'completion_tokens, total_tokens, cost_usd, generation_id, created_at')
    if {'cost_source', 'attempt_status', 'reconcile_attempts', 'next_retry_at',
        'updated_at', 'response_cost_usd', 'generation_cost_usd', 'cost_raw'} <= cols:
        select_cols += (', cost_source, attempt_status, reconcile_attempts, next_retry_at, '
                        'updated_at, response_cost_usd, generation_cost_usd, cost_raw')
    recent = [dict(r) for r in conn.execute(
        f'SELECT {select_cols} '
        f'FROM ai_usage_events {where} ORDER BY created_at DESC LIMIT ?',
        params + [int(limit)]
    ).fetchall()]
    try:
        status = get_ai_usage_status_counts(tenant_id, draft_id=draft_id, presentation_id=presentation_id)
    except Exception:
        status = {}
    return {'totals': totals, 'by_flow': by_flow, 'by_model': by_model, 'recent': recent, 'status': status}


def get_ai_usage_pending_costs(limit=15, tenant_id=None):
    """Oldest-first events that carry a generation id but no dollar cost yet.

    Oldest first so a busy project never starves its earliest attempts.
    No age cutoff is applied here so rows older than 24 hours stay visible
    until they settle or move to needs_review through the review path.
    """
    conn = get_db()
    cols = _ai_usage_columns(conn)
    clauses = ['cost_usd IS NULL', 'generation_id IS NOT NULL']
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    if 'attempt_status' in cols:
        clauses.append("(attempt_status IS NULL OR attempt_status NOT IN ('settled', 'needs_review'))")
    params.append(int(limit))
    select_cols = 'id, generation_id, created_at'
    if {'tenant_id', 'draft_id', 'presentation_id', 'attempt_status',
        'reconcile_attempts', 'cost_source'} <= cols:
        select_cols = ('id, tenant_id, draft_id, presentation_id, generation_id, created_at, '
                       'attempt_status, reconcile_attempts, cost_source')
    rows = conn.execute(
        'SELECT ' + select_cols + ' FROM ai_usage_events '
        f"WHERE {' AND '.join(clauses)} ORDER BY created_at ASC LIMIT ?",
        params
    ).fetchall()
    return [dict(r) for r in rows]


def record_maps_usage_event(tenant_id, sku, units, unit_price_usd,
                            flow='other', draft_id=None, presentation_id=None):
    """Persist one billable Google Maps call.

    The unit price is stored on the row, so a later price change never rewrites
    history. Only completed provider requests are recorded: cached reads and
    failed calls carry no spend.
    """
    conn = get_db()
    event_id = str(uuid.uuid4())
    units = max(0, int(units or 0))
    price = float(unit_price_usd or 0.0)
    try:
        cols = {row['name'] for row in conn.execute('PRAGMA table_info(map_usage_events)').fetchall()}
    except Exception:
        cols = set()
    package_id = _tenant_active_package_id(conn, tenant_id)
    if 'package_id' in cols:
        conn.execute(
            '''INSERT INTO map_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, sku, units, unit_price_usd, cost_usd, package_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other',
             sku, units, price, units * price, package_id)
        )
    else:
        conn.execute(
            '''INSERT INTO map_usage_events
               (id, tenant_id, draft_id, presentation_id, flow, sku, units, unit_price_usd, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (event_id, tenant_id, draft_id, presentation_id, flow or 'other',
             sku, units, price, units * price)
        )
    conn.commit()
    return event_id


def get_maps_usage_summary(tenant_id, draft_id=None, presentation_id=None, limit=50):
    """Tenant-scoped Maps spend grouped by flow and SKU, plus recent events."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    where = 'WHERE ' + ' AND '.join(clauses)
    conn = get_db()
    totals = dict(conn.execute(
        'SELECT COUNT(*) AS calls, '
        'COALESCE(SUM(units), 0) AS units, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM map_usage_events {where}',
        params
    ).fetchone())
    by_flow = [dict(r) for r in conn.execute(
        'SELECT flow, COUNT(*) AS calls, '
        'COALESCE(SUM(units), 0) AS units, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM map_usage_events {where} GROUP BY flow ORDER BY cost_usd DESC',
        params
    ).fetchall()]
    by_sku = [dict(r) for r in conn.execute(
        'SELECT sku, COUNT(*) AS calls, '
        'COALESCE(SUM(units), 0) AS units, '
        'COALESCE(SUM(cost_usd), 0) AS cost_usd, '
        'COALESCE(MAX(unit_price_usd), 0) AS unit_price_usd '
        f'FROM map_usage_events {where} GROUP BY sku ORDER BY cost_usd DESC',
        params
    ).fetchall()]
    recent = [dict(r) for r in conn.execute(
        'SELECT id, draft_id, presentation_id, flow, sku, units, unit_price_usd, '
        'cost_usd, created_at '
        f'FROM map_usage_events {where} ORDER BY created_at DESC LIMIT ?',
        params + [int(limit)]
    ).fetchall()]
    return {'totals': totals, 'by_flow': by_flow, 'by_sku': by_sku, 'recent': recent}


def get_maps_discovery_cache(tenant_id, cache_key):
    """Cached Google discovery payload, or None on miss/expiry. Never raises."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT payload_json FROM maps_discovery_cache '
            "WHERE cache_key = ? AND expires_at > datetime('now')",
            (str(cache_key),)
        ).fetchone()
        if row is None:
            return None
        return json.loads(dict(row).get('payload_json') or 'null')
    except Exception:
        return None


def set_maps_discovery_cache(tenant_id, cache_key, payload, ttl_days=30):
    """Store one Google discovery payload. Never raises."""
    try:
        from datetime import timedelta
        days = max(1, int(ttl_days or 30))
        expires_at = (_utcnow() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        conn = get_db()
        conn.execute(
            'INSERT INTO maps_discovery_cache (cache_key, tenant_id, payload_json, expires_at) '
            'VALUES (?, ?, ?, ?) '
            'ON CONFLICT (cache_key) DO UPDATE SET tenant_id = excluded.tenant_id, '
            "payload_json = excluded.payload_json, created_at = datetime('now'), "
            "expires_at = excluded.expires_at",
            (str(cache_key), tenant_id, json.dumps(payload, ensure_ascii=False), expires_at)
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[MAPS CACHE] store failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Billing ledger (tenant wallet debits backed by unbilled usage events)
# ─────────────────────────────────────────────────────────────────────────────

BILLING_MULTIPLIER_DEFAULT = 1.6


class InsufficientBalance(Exception):
    """Raised when a tenant wallet cannot cover a billing amount."""

    def __init__(self, required_usd=0.0, available_usd=0.0):
        self.required_usd = float(required_usd or 0.0)
        self.available_usd = float(available_usd or 0.0)
        super().__init__(
            f'Insufficient balance: required ${self.required_usd:.2f}, '
            f'available ${self.available_usd:.2f}'
        )


# The app layer registers a callable here that re-syncs the tenant's
# provider-side spend cap whenever the wallet moves (top-up, debit, hold,
# release, adjustment). Assigned once at import; None in tests and CLI use.
BALANCE_CHANGE_HOOK = None


def _fire_balance_change(tenant_id):
    """Notify the registered listener that a wallet moved. Never raises."""
    hook = BALANCE_CHANGE_HOOK
    if not hook or not tenant_id:
        return
    try:
        hook(tenant_id)
    except Exception as exc:
        print(f'[BILLING] balance-change hook failed for {tenant_id}: {exc}')


def get_billing_multiplier():
    """Markup applied to raw provider cost at billing time. Env-overridable."""
    try:
        value = float(os.environ.get('BILLING_MULTIPLIER') or BILLING_MULTIPLIER_DEFAULT)
    except (TypeError, ValueError):
        value = BILLING_MULTIPLIER_DEFAULT
    return max(0.0, value)


def billing_enforcement_enabled():
    """Pre-flight balance checks run only when explicitly enabled."""
    return str(os.environ.get('BILLING_ENFORCE') or '').strip() == '1'


def get_billing_flow_estimates():
    """Conservative billed-USD estimates per expensive flow. Env-overridable."""
    defaults = {
        'analyze_site': 1.0,
        'site_analysis': 0.5,
        'map_image': 0.5,
        'slide_plan': 0.5,
        'slide_single': 0.25,
        'market_competitors': 1.0,
        'market_summary': 1.0,
        'croquis': 0.5,
    }
    try:
        overrides = json.loads(os.environ.get('BILLING_PREFLIGHT_ESTIMATES') or '{}')
    except (TypeError, ValueError):
        overrides = {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            try:
                defaults[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return defaults


# Product price per generation unit in USD. This is what the client is charged
# (converted to points at POINTS_PER_USD), independent of the provider cost that
# usage events record — env-overridable as the effective pricing policy.
POINTS_PER_USD = 1000
GENERATION_UNIT_PRICES_DEFAULT = {
    'slide': 0.05,
    'map': 0.15,
    'image': 0.10,
    'plan': 0.25,
}
RESERVATION_TTL_HOURS = 6


def get_generation_unit_prices():
    """Effective per-unit generation pricing. Env-overridable via JSON."""
    defaults = dict(GENERATION_UNIT_PRICES_DEFAULT)
    try:
        overrides = json.loads(os.environ.get('GENERATION_UNIT_PRICES') or '{}')
    except (TypeError, ValueError):
        overrides = {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            try:
                defaults[key] = max(0.0, float(value))
            except (TypeError, ValueError):
                continue
    return defaults


def get_tenant_balance(tenant_id):
    """Current wallet balance in USD. Never raises for a missing tenant."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT credit_balance FROM tenants WHERE id = ?', (tenant_id,)
        ).fetchone()
    except Exception:
        return 0.0
    if row is None:
        return 0.0
    try:
        return float(dict(row).get('credit_balance') or 0.0)
    except (TypeError, ValueError):
        return 0.0


# AI events checkout may claim: a verified cost ('settled'), a completed call
# with nothing left to reconcile ('unresolved'), or a legacy row that predates
# attempt tracking but already carries a cost. 'pending', 'in_flight' and
# 'needs_review' rows stay unbilled until the reconcile loop prices them —
# claiming them early would lock them at $0 forever.
_AI_BILLABLE_STATUS_CLAUSE = (
    "COALESCE(attempt_status, CASE WHEN cost_usd IS NOT NULL THEN 'settled' "
    "ELSE 'pending' END) IN ('settled', 'unresolved')"
)


def _unbilled_scope_clause(tenant_id, draft_id=None, presentation_id=None,
                           ai_settled_only=False):
    # package_id IS NULL: a usage row burned under an assigned package is
    # consumed against that package's credit — it is never wallet-billable
    # and must not be double-charged by checkout or counted as unbilled.
    clauses = ['tenant_id = ?', 'billed_ledger_id IS NULL', 'package_id IS NULL']
    params = [tenant_id]
    if ai_settled_only:
        clauses.append(_AI_BILLABLE_STATUS_CLAUSE)
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(presentation_id)
    return 'WHERE ' + ' AND '.join(clauses), params


def get_unbilled_usage(tenant_id, draft_id=None, presentation_id=None):
    """Raw cost of usage events that no ledger entry has billed yet."""
    conn = get_db()
    ai_where, ai_params = _unbilled_scope_clause(tenant_id, draft_id, presentation_id)
    maps_where, maps_params = _unbilled_scope_clause(tenant_id, draft_id, presentation_id)
    ai_row = conn.execute(
        'SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM ai_usage_events {ai_where}',
        ai_params
    ).fetchone()
    maps_row = conn.execute(
        'SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost_usd '
        f'FROM map_usage_events {maps_where}',
        maps_params
    ).fetchone()
    ai_calls = int(dict(ai_row).get('calls') or 0)
    maps_calls = int(dict(maps_row).get('calls') or 0)
    ai_cost = float(dict(ai_row).get('cost_usd') or 0.0)
    maps_cost = float(dict(maps_row).get('cost_usd') or 0.0)
    return {
        'ai_calls': ai_calls,
        'maps_calls': maps_calls,
        'ai_cost_usd': ai_cost,
        'maps_cost_usd': maps_cost,
        'raw_cost_usd': ai_cost + maps_cost,
    }


def bill_unbilled_usage(tenant_id, draft_id=None, presentation_id=None,
                        idempotency_key=None, multiplier=None, note=None):
    """Bill every unbilled usage event in scope. Fully idempotent.

    The claim step marks unbilled rows with the new ledger id in a single
    UPDATE, so a retry or a parallel request finds an empty unbilled scope
    instead of billing the same events twice. The wallet debit is a
    conditional UPDATE on the balance it read, so a lost race surfaces as
    InsufficientBalance rather than an overdraft. One commit covers the
    claim, the ledger row and the debit. Any failure rolls everything back.
    """
    conn = get_db()
    if idempotency_key:
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (tenant_id, idempotency_key)
        ).fetchone()
        if existing:
            return {'billed': False, 'reason': 'idempotency_key_replayed',
                    'entry': dict(existing)}
    ledger_id = str(uuid.uuid4())
    try:
        try:
            active_multiplier = float(multiplier) if multiplier is not None else get_billing_multiplier()
        except (TypeError, ValueError):
            active_multiplier = get_billing_multiplier()
        active_multiplier = max(0.0, active_multiplier)
        ai_where, ai_params = _unbilled_scope_clause(
            tenant_id, draft_id, presentation_id, ai_settled_only=True)
        maps_where, maps_params = _unbilled_scope_clause(tenant_id, draft_id, presentation_id)
        ai_claim = conn.execute(
            'UPDATE ai_usage_events SET billed_ledger_id = ? ' + ai_where,
            tuple([ledger_id] + ai_params)
        )
        maps_claim = conn.execute(
            'UPDATE map_usage_events SET billed_ledger_id = ? ' + maps_where,
            tuple([ledger_id] + maps_params)
        )
        ai_count = ai_claim.rowcount if ai_claim.rowcount is not None else 0
        maps_count = maps_claim.rowcount if maps_claim.rowcount is not None else 0
        if ai_count <= 0 and maps_count <= 0:
            conn.rollback()
            return {'billed': False, 'reason': 'no_unbilled_events'}
        ai_cost = float(dict(conn.execute(
            'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM ai_usage_events WHERE billed_ledger_id = ?',
            (ledger_id,)
        ).fetchone()).get('total') or 0.0)
        maps_cost = float(dict(conn.execute(
            'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM map_usage_events WHERE billed_ledger_id = ?',
            (ledger_id,)
        ).fetchone()).get('total') or 0.0)
        raw_cost = ai_cost + maps_cost
        billed_amount = round(raw_cost * active_multiplier + 1e-9, 2)
        debit = conn.execute(
            'UPDATE tenants SET credit_balance = credit_balance - ? '
            'WHERE id = ? AND credit_balance >= ?',
            (billed_amount, tenant_id, billed_amount)
        )
        if (debit.rowcount or 0) <= 0:
            conn.rollback()
            raise InsufficientBalance(billed_amount, get_tenant_balance(tenant_id))
        conn.execute(
            '''INSERT INTO tenant_ledger
               (id, tenant_id, kind, amount_usd, raw_cost_usd, multiplier,
                maps_cost_usd, ai_cost_usd, maps_events_count, ai_events_count,
                draft_id, presentation_id, idempotency_key, note)
               VALUES (?, ?, 'debit', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (ledger_id, tenant_id, billed_amount, raw_cost, active_multiplier,
             maps_cost, ai_cost, max(0, int(maps_count)), max(0, int(ai_count)),
             draft_id, presentation_id, idempotency_key, note)
        )
        conn.commit()
    except InsufficientBalance:
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    _fire_balance_change(tenant_id)
    entry = conn.execute(
        'SELECT * FROM tenant_ledger WHERE id = ?', (ledger_id,)
    ).fetchone()
    return {'billed': True, 'entry': dict(entry),
            'balance_usd': get_tenant_balance(tenant_id)}


def record_ledger_credit(tenant_id, amount_usd, note=None, idempotency_key=None, actor=None):
    """Top up a tenant wallet. Records a credit entry and adds the balance.

    ``actor`` names who created the movement — 'platform_admin' for the
    recharge-decision path, 'client_admin' for a client-side top-up — so the
    separation-of-duties matrix can flag credits from the wrong side (t23).
    """
    amount = round(float(amount_usd or 0.0) + 1e-9, 2)
    if amount <= 0:
        raise ValueError('Credit amount must be positive')
    conn = get_db()
    if idempotency_key:
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (tenant_id, idempotency_key)
        ).fetchone()
        if existing:
            return {'credited': False, 'reason': 'idempotency_key_replayed',
                    'entry': dict(existing)}
    ledger_id = str(uuid.uuid4())
    try:
        conn.execute(
            'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
            (amount, tenant_id)
        )
        conn.execute(
            '''INSERT INTO tenant_ledger
               (id, tenant_id, kind, amount_usd, raw_cost_usd, multiplier,
                maps_cost_usd, ai_cost_usd, maps_events_count, ai_events_count,
                draft_id, presentation_id, idempotency_key, note, actor)
               VALUES (?, ?, 'credit', ?, 0, 1, 0, 0, 0, 0, NULL, NULL, ?, ?, ?)''',
            (ledger_id, tenant_id, amount, idempotency_key, note, actor)
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    _fire_balance_change(tenant_id)
    entry = conn.execute(
        'SELECT * FROM tenant_ledger WHERE id = ?', (ledger_id,)
    ).fetchone()
    return {'credited': True, 'entry': dict(entry),
            'balance_usd': get_tenant_balance(tenant_id)}


def reset_all_company_balances(clear_usage=True):
    """Forced fresh start: zero wallets and unassign packages, optionally
    wiping spend history too. Super-admin tenants are never touched.
    Provider key rows stay (identity only); limits re-sync on next assign."""
    conn = get_db()
    scope = 'COALESCE(is_admin, 0) != 1'
    try:
        affected_tenants = [row[0] for row in conn.execute(
            f'SELECT id FROM tenants WHERE {scope}').fetchall()]
    except Exception:
        affected_tenants = []
    wallets = conn.execute(
        f'UPDATE tenants SET credit_balance = 0, package_id = NULL WHERE {scope}')
    result = {'tenants_reset': wallets.rowcount or 0, 'ai_deleted': 0,
              'maps_deleted': 0, 'history_deleted': 0, 'ledger_deleted': 0}
    if clear_usage:
        for table, key in (('ai_usage_events', 'ai_deleted'),
                           ('map_usage_events', 'maps_deleted'),
                           ('tenant_package_history', 'history_deleted'),
                           ('tenant_ledger', 'ledger_deleted')):
            try:
                cur = conn.execute(
                    f'DELETE FROM {table} WHERE tenant_id IN '
                    f'(SELECT id FROM tenants WHERE {scope})')
                result[key] = cur.rowcount or 0
            except Exception:
                pass
    conn.commit()
    for _tid in affected_tenants:
        _fire_balance_change(_tid)
    return result


def _norm_range_bound(value, is_end=False):
    """Normalize a UI date/datetime bound ('YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM')
    to the stored 'YYYY-MM-DD HH:MM:SS' format so string comparison works."""
    s = str(value or '').strip().replace('T', ' ')
    if not s:
        return ''
    if len(s) == 10:
        return s + (' 23:59:59' if is_end else ' 00:00:00')
    if len(s) == 16:
        return s + (':59' if is_end else ':00')
    return s


def get_ledger_entries(tenant_id, limit=50, kind=None, from_date=None, to_date=None,
                       draft_id=None, presentation_id=None, actor=None):
    """Newest ledger entries for a tenant, with the t32 report filters:
    period, project file, presentation, movement kind and actor."""
    conn = get_db()
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if kind:
        clauses.append('kind = ?')
        params.append(str(kind))
    if from_date:
        clauses.append('created_at >= ?')
        params.append(_norm_range_bound(from_date))
    if to_date:
        clauses.append('created_at <= ?')
        params.append(_norm_range_bound(to_date, is_end=True))
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(str(draft_id))
    if presentation_id:
        clauses.append('presentation_id = ?')
        params.append(str(presentation_id))
    if actor:
        clauses.append('actor = ?')
        params.append(str(actor))
    rows = conn.execute(
        'SELECT id, kind, amount_usd, raw_cost_usd, multiplier, maps_cost_usd, '
        'ai_cost_usd, maps_events_count, ai_events_count, draft_id, '
        'presentation_id, idempotency_key, note, actor, reversal_of, created_at '
        'FROM tenant_ledger WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY created_at DESC LIMIT ?',
        params + [int(limit)]
    ).fetchall()
    return [dict(r) for r in rows]


def points_overview(tenant_id):
    """t30: one read of the wallet — current balance, live holds, expired and
    consumed totals, all in USD with the points conversion alongside."""
    release_stale_reservations(tenant_id)
    conn = get_db()
    balance = get_tenant_balance(tenant_id)
    rows = conn.execute(
        '''SELECT status, COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS n
           FROM point_reservations WHERE tenant_id = ? GROUP BY status''',
        (str(tenant_id),),
    ).fetchall()
    buckets = {row['status']: {'usd': float(row['total'] or 0), 'count': int(row['n'])}
               for row in rows}
    reserved_usd = buckets.get('reserved', {}).get('usd', 0.0)
    expired_usd = buckets.get('expired', {}).get('usd', 0.0)
    total_usd = balance + reserved_usd
    return {
        'balance_usd': round(total_usd, 2),
        'balance_points': int(round(total_usd * POINTS_PER_USD)),
        'current_points': int(round(total_usd * POINTS_PER_USD)),
        'reserved_usd': round(reserved_usd, 2),
        'reserved_points': int(round(reserved_usd * POINTS_PER_USD)),
        'available_usd': round(balance, 2),
        'available_points': int(round(balance * POINTS_PER_USD)),
        'expired_usd': round(expired_usd, 2),
        'expired_points': int(round(expired_usd * POINTS_PER_USD)),
        'consumed_usd': round(buckets.get('consumed', {}).get('usd', 0.0), 2),
        'released_usd': round(buckets.get('released', {}).get('usd', 0.0), 2),
        'reservations': buckets,
    }


LEDGER_ADJUSTMENT_KINDS = ('refund', 'correction', 'expiry')


def record_ledger_adjustment(tenant_id, amount_usd, kind, note=None, actor=None,
                             reversal_of=None, idempotency_key=None):
    """t32: refund, correction and expiry movements on the wallet.

    A positive amount credits the wallet, a negative amount debits it
    (conditional — never overdrawn). ``reversal_of`` links the movement back
    to the original ledger entry it reverses. Admin-only at the route level.
    """
    if kind not in LEDGER_ADJUSTMENT_KINDS:
        return {'error': 'invalid_kind'}
    amount = round(float(amount_usd or 0.0) + 1e-9, 2)
    if amount == 0:
        return {'error': 'amount_required'}
    conn = get_db()
    if reversal_of:
        original = conn.execute(
            'SELECT * FROM tenant_ledger WHERE id = ? AND tenant_id = ?',
            (str(reversal_of), tenant_id),
        ).fetchone()
        if not original:
            return {'error': 'original_entry_not_found'}
    if idempotency_key:
        existing = conn.execute(
            'SELECT * FROM tenant_ledger WHERE tenant_id = ? AND idempotency_key = ?',
            (tenant_id, idempotency_key),
        ).fetchone()
        if existing:
            return {'adjusted': False, 'reason': 'idempotency_key_replayed',
                    'entry': dict(existing)}
    if amount < 0:
        debit = conn.execute(
            'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? '
            'WHERE id = ? AND COALESCE(credit_balance, 0) >= ?',
            (amount, tenant_id, -amount),
        )
        if (debit.rowcount or 0) <= 0:
            return {'error': 'insufficient_balance',
                    'available_usd': get_tenant_balance(tenant_id)}
    else:
        conn.execute(
            'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
            (amount, tenant_id),
        )
    ledger_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_ledger
           (id, tenant_id, kind, amount_usd, idempotency_key, note, actor, reversal_of)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (ledger_id, tenant_id, kind, amount, idempotency_key,
         str(note or '').strip() or None, actor, reversal_of),
    )
    conn.commit()
    _fire_balance_change(tenant_id)
    return {'adjusted': True,
            'entry': dict(conn.execute(
                'SELECT * FROM tenant_ledger WHERE id = ?', (ledger_id,)).fetchone()),
            'balance_usd': get_tenant_balance(tenant_id)}


# ─────────────────────────────────────────────────────────────────────────────
# Per-tenant OpenRouter keys. One row per company. Managed keys are created
# through the OpenRouter Management API so they show in the owner dashboard
# with their own spend limit. Manual keys are pasted by a super admin.
# The raw value is stored encrypted and metadata reads never return it.
# ─────────────────────────────────────────────────────────────────────────────

TENANT_KEY_PROVENANCES = ('auto', 'manual')
TENANT_KEY_LIMIT_RESETS = ('daily', 'weekly', 'monthly', 'none')


def _tenant_key_secret():
    """Bytes used to obscure stored provider keys. Env-overridable."""
    configured = (os.environ.get('OPENROUTER_KEY_ENCRYPTION_SECRET') or '').strip()
    if configured:
        return configured.encode('utf-8')
    fallback = (os.environ.get('JWT_SECRET') or '').strip()
    if fallback:
        return fallback.encode('utf-8')
    try:
        base_dir = os.path.abspath(os.path.dirname(__file__))
        secret_path = os.path.abspath(os.path.join(base_dir, '.jwt_secret'))
        if os.path.commonpath([base_dir, secret_path]) == base_dir and os.path.exists(secret_path):
            with open(secret_path, 'r', encoding='utf-8') as secret_file:
                stored = secret_file.read().strip()
                if stored:
                    return stored.encode('utf-8')
    except Exception:
        pass
    return b'dev-only-tenant-key-secret'


def _tenant_key_stream(secret, nonce, length):
    """SHA256 counter stream for XOR obscuring without new dependencies."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(secret + nonce + counter.to_bytes(4, 'big')).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_tenant_openrouter_key(raw_key):
    """Obscure a provider key for storage with tamper detection."""
    import base64 as _b64
    import hmac as _hmac
    import secrets as _secrets
    secret = _tenant_key_secret()
    raw = (raw_key or '').strip().encode('utf-8')
    if not raw:
        raise ValueError('Empty provider key')
    nonce = _secrets.token_bytes(16)
    stream = _tenant_key_stream(secret, nonce, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream))
    tag = _hmac.new(secret, nonce + cipher, hashlib.sha256).hexdigest()
    return 'v1.' + _b64.urlsafe_b64encode(nonce).decode('ascii') + '.' \
        + _b64.urlsafe_b64encode(cipher).decode('ascii') + '.' + tag


def decrypt_tenant_openrouter_key(enc_value):
    """Reverse encrypt_tenant_openrouter_key. Returns None when tampered."""
    import base64 as _b64
    import hmac as _hmac
    try:
        if not enc_value or not isinstance(enc_value, str):
            return None
        parts = enc_value.split('.')
        if len(parts) != 4 or parts[0] != 'v1':
            return None
        secret = _tenant_key_secret()
        nonce = _b64.urlsafe_b64decode(parts[1].encode('ascii'))
        cipher = _b64.urlsafe_b64decode(parts[2].encode('ascii'))
        tag = parts[3]
        expected = _hmac.new(secret, nonce + cipher, hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, tag):
            return None
        stream = _tenant_key_stream(secret, nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode('utf-8')
    except Exception:
        return None


def _tenant_key_public(row):
    """Public metadata for a key row. The raw secret never leaves the server."""
    if row is None:
        return {'has_key': False}
    try:
        data = dict(row)
    except Exception:
        return {'has_key': False}
    key_hash = str(data.get('key_hash') or '')
    return {
        'has_key': True,
        'key_hint': ('...' + key_hash[-4:]) if len(key_hash) >= 4 else '...',
        'key_label': data.get('key_label'),
        'openrouter_key_hash': data.get('openrouter_key_hash'),
        'limit_usd': data.get('limit_usd'),
        'limit_reset': data.get('limit_reset'),
        'provenance': data.get('provenance') or 'auto',
        'is_active': bool(data.get('is_active')),
        'last_limit_remaining': data.get('last_limit_remaining'),
        'last_usage': data.get('last_usage'),
        'last_checked_at': data.get('last_checked_at'),
        'updated_at': data.get('updated_at'),
        'created_at': data.get('created_at'),
    }


def get_tenant_openrouter_key_meta(tenant_id):
    """Public key status for one tenant. Never includes the secret."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT * FROM tenant_openrouter_keys WHERE tenant_id = ?',
            (str(tenant_id),)
        ).fetchone()
    except Exception:
        return {'has_key': False}
    return _tenant_key_public(row)


def get_tenant_openrouter_key_raw(tenant_id):
    """Decrypted provider key for server-side calls only. None when absent."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT key_enc FROM tenant_openrouter_keys WHERE tenant_id = ? AND is_active = 1',
            (str(tenant_id),)
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        enc = dict(row).get('key_enc')
    except Exception:
        return None
    raw = decrypt_tenant_openrouter_key(enc)
    return raw if raw else None


def set_tenant_openrouter_key(tenant_id, raw_key, key_label=None, limit_usd=None,
                              limit_reset=None, provenance='manual',
                              openrouter_key_hash=None):
    """Create or replace one tenant key. Returns public metadata only."""
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        raise ValueError('tenant_id is required')
    raw = (raw_key or '').strip()
    if len(raw) < 16:
        raise ValueError('Invalid provider key')
    if provenance not in TENANT_KEY_PROVENANCES:
        provenance = 'manual'
    if limit_reset is not None and limit_reset not in TENANT_KEY_LIMIT_RESETS:
        raise ValueError('Invalid limit_reset')
    amount = None
    if limit_usd is not None:
        try:
            amount = float(limit_usd)
        except (TypeError, ValueError):
            raise ValueError('Invalid limit_usd')
        if amount < 0:
            raise ValueError('Invalid limit_usd')
    enc = encrypt_tenant_openrouter_key(raw)
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    conn = get_db()
    now = _utcnow().strftime('%Y-%m-%d %H:%M:%S')
    existing = conn.execute(
        'SELECT id FROM tenant_openrouter_keys WHERE tenant_id = ?', (tenant_id,)
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE tenant_openrouter_keys SET key_enc = ?, key_hash = ?, key_label = ?, '
            'openrouter_key_hash = ?, limit_usd = ?, limit_reset = ?, provenance = ?, '
            'is_active = 1, updated_at = ? WHERE tenant_id = ?',
            (enc, digest, (key_label or None), (openrouter_key_hash or None),
             amount, limit_reset, provenance, now, tenant_id)
        )
    else:
        conn.execute(
            'INSERT INTO tenant_openrouter_keys (id, tenant_id, key_enc, key_hash, key_label, '
            'openrouter_key_hash, limit_usd, limit_reset, provenance, is_active, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)',
            (str(uuid.uuid4()), tenant_id, enc, digest, (key_label or None),
             (openrouter_key_hash or None), amount, limit_reset, provenance, now)
        )
    conn.commit()
    return get_tenant_openrouter_key_meta(tenant_id)


def update_tenant_openrouter_key_meta(tenant_id, limit_usd=None, limit_reset=None,
                                      is_active=None, last_limit_remaining=None,
                                      last_usage=None, openrouter_key_hash=None):
    """Update key metadata without touching the secret. Returns public metadata."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_openrouter_keys WHERE tenant_id = ?', (str(tenant_id),)
    ).fetchone()
    if row is None:
        return {'has_key': False}
    assignments = []
    params = []
    if limit_usd is not None:
        try:
            amount = float(limit_usd)
        except (TypeError, ValueError):
            raise ValueError('Invalid limit_usd')
        if amount < 0:
            raise ValueError('Invalid limit_usd')
        assignments.append('limit_usd = ?')
        params.append(amount)
    if limit_reset is not None:
        if limit_reset not in TENANT_KEY_LIMIT_RESETS:
            raise ValueError('Invalid limit_reset')
        assignments.append('limit_reset = ?')
        params.append(limit_reset)
    if is_active is not None:
        assignments.append('is_active = ?')
        params.append(1 if is_active else 0)
    if last_limit_remaining is not None:
        try:
            assignments.append('last_limit_remaining = ?')
            params.append(float(last_limit_remaining))
        except (TypeError, ValueError):
            pass
    if last_usage is not None:
        try:
            assignments.append('last_usage = ?')
            params.append(float(last_usage))
        except (TypeError, ValueError):
            pass
    if openrouter_key_hash is not None:
        assignments.append('openrouter_key_hash = ?')
        params.append(str(openrouter_key_hash or None))
    if last_limit_remaining is not None or last_usage is not None:
        assignments.append('last_checked_at = ?')
        params.append(_utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    if not assignments:
        return get_tenant_openrouter_key_meta(tenant_id)
    assignments.append('updated_at = ?')
    params.append(_utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(str(tenant_id))
    conn.execute(
        'UPDATE tenant_openrouter_keys SET ' + ', '.join(assignments) + ' WHERE tenant_id = ?',
        tuple(params)
    )
    conn.commit()
    return get_tenant_openrouter_key_meta(tenant_id)


def deactivate_tenant_openrouter_key(tenant_id):
    """Disable a tenant key locally. Returns public metadata."""
    return update_tenant_openrouter_key_meta(tenant_id, is_active=False)


# ─────────────────────────────────────────────────────────────────────────────
# Billing packages and the USD to SAR rate for riyal-denominated balances.
# ─────────────────────────────────────────────────────────────────────────────

FX_PAIR_USD_SAR = 'USD_SAR'
FX_DEFAULT_USD_SAR = 3.75
FX_REFRESH_SECONDS = 24 * 3600


def list_billing_packages(active_only=False):
    """All packages, newest last, each carrying the current active version's
    validity window and feature terms for the purchase screen. Never raises."""
    try:
        conn = get_db()
        rows = conn.execute(
            'SELECT p.*, v.duration_days, v.features_json '
            'FROM billing_packages p '
            'LEFT JOIN billing_package_versions v ON v.id = ('
            '  SELECT id FROM billing_package_versions '
            '  WHERE package_id = p.id AND is_active = 1 '
            '  ORDER BY version DESC LIMIT 1) '
            + ('WHERE p.is_active = 1 ' if active_only else '')
            + 'ORDER BY p.created_at ASC'
        ).fetchall()
        items = []
        for r in rows:
            item = dict(r)
            item['features'] = _json_or(item.get('features_json'), [])
            items.append(item)
        return items
    except Exception:
        return []


def get_billing_package(package_id):
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def create_billing_package(name, credit_usd=0.0, price_sar=None, is_custom=True):
    """Create a package. credit_usd may be zero (prepaid, topped up later)."""
    label = str(name or '').strip()
    if not label or len(label) > 120:
        raise ValueError('Invalid package name')
    try:
        credit = float(credit_usd or 0.0)
    except (TypeError, ValueError):
        raise ValueError('Invalid credit_usd')
    if credit < 0:
        raise ValueError('Invalid credit_usd')
    price = None
    if price_sar is not None:
        try:
            price = float(price_sar)
        except (TypeError, ValueError):
            raise ValueError('Invalid price_sar')
        if price < 0:
            raise ValueError('Invalid price_sar')
    conn = get_db()
    package_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO billing_packages (id, name, credit_usd, price_sar, is_active, is_custom) '
        'VALUES (?, ?, ?, ?, 1, ?)',
        (package_id, label, credit, price, 1 if is_custom else 0)
    )
    conn.commit()
    return get_billing_package(package_id)


def update_billing_package(package_id, name=None, credit_usd=None, price_sar=None,
                           is_active=None):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
    if row is None:
        return None
    assignments = []
    params = []
    if name is not None:
        label = str(name or '').strip()
        if not label or len(label) > 120:
            raise ValueError('Invalid package name')
        assignments.append('name = ?')
        params.append(label)
    if credit_usd is not None:
        try:
            credit = float(credit_usd)
        except (TypeError, ValueError):
            raise ValueError('Invalid credit_usd')
        if credit < 0:
            raise ValueError('Invalid credit_usd')
        assignments.append('credit_usd = ?')
        params.append(credit)
    if price_sar is not None:
        try:
            price = float(price_sar)
        except (TypeError, ValueError):
            raise ValueError('Invalid price_sar')
        if price < 0:
            raise ValueError('Invalid price_sar')
        assignments.append('price_sar = ?')
        params.append(price)
    if is_active is not None:
        assignments.append('is_active = ?')
        params.append(1 if is_active else 0)
    if not assignments:
        return dict(row)
    assignments.append("updated_at = datetime('now')")
    params.append(str(package_id))
    conn.execute(
        'UPDATE billing_packages SET ' + ', '.join(assignments) + ' WHERE id = ?',
        tuple(params)
    )
    conn.commit()
    return get_billing_package(package_id)


def delete_billing_package(package_id):
    """Delete a package; tenants on it keep their key limit, package unset."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
    if row is None:
        return False
    try:
        conn.execute('UPDATE tenants SET package_id = NULL WHERE package_id = ?',
                     (str(package_id),))
    except Exception:
        pass
    conn.execute('DELETE FROM billing_packages WHERE id = ?', (str(package_id),))
    conn.commit()
    return True


def assign_tenant_package(tenant_id, package_id):
    """Attach a tenant to a package. Returns (tenant, package)."""
    conn = get_db()
    tenant = conn.execute(
        'SELECT * FROM tenants WHERE id = ?', (str(tenant_id),)).fetchone()
    if tenant is None:
        raise ValueError('Tenant not found')
    package = None
    if package_id:
        package = conn.execute(
            'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),)).fetchone()
        if package is None:
            raise ValueError('Package not found')
        package = dict(package)
    try:
        conn.execute('UPDATE tenants SET package_id = ? WHERE id = ?',
                     (str(package_id) if package_id else None, str(tenant_id)))
        conn.commit()
    except Exception:
        pass
    if package is not None:
        try:
            conn.execute(
                'INSERT INTO tenant_package_history '
                '(id, tenant_id, package_id, package_name, credit_usd) '
                'VALUES (?, ?, ?, ?, ?)',
                (str(uuid.uuid4()), str(tenant_id), str(package.get('id')),
                 package.get('name'), float(package.get('credit_usd') or 0.0))
            )
            conn.commit()
        except Exception as exc:
            print(f"[PACKAGES] history failed: {exc}")
    return dict(tenant), package


def get_client_overview(tenant_id):
    """Client card figures in raw USD: totals, current package, lifetime.

    Every spend row carries the package it burned under at write time, so
    per-package consumption is exact and never depends on clock comparisons.
    Remaining is floored at zero and the package reads expired exactly when
    nothing remains.
    """
    conn = get_db()
    tenant_id = str(tenant_id)
    counts = get_tenant_profile_counts(tenant_id)

    def _tagged_sum(table, package_id):
        try:
            cols = {row['name'] for row in conn.execute(
                f'PRAGMA table_info({table})').fetchall()}
        except Exception:
            cols = set()
        if 'package_id' not in cols:
            return None
        try:
            return float(dict(conn.execute(
                f'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {table} '
                'WHERE tenant_id = ? AND package_id = ?',
                (tenant_id, str(package_id))).fetchone()).get('total') or 0.0)
        except Exception:
            return 0.0

    def _lifetime_sum(table):
        try:
            return float(dict(conn.execute(
                f'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {table} WHERE tenant_id = ?',
                (tenant_id,)).fetchone()).get('total') or 0.0)
        except Exception:
            return 0.0

    lifetime = _lifetime_sum('ai_usage_events') + _lifetime_sum('map_usage_events')
    tenant = conn.execute(
        'SELECT package_id FROM tenants WHERE id = ?', (tenant_id,)).fetchone()
    package_id = dict(tenant).get('package_id') if tenant else None
    package = get_billing_package(package_id) if package_id else None
    assigned_at = None
    if package is not None:
        try:
            row = conn.execute(
                'SELECT assigned_at FROM tenant_package_history '
                'WHERE tenant_id = ? ORDER BY assigned_at DESC LIMIT 1',
                (tenant_id,)).fetchone()
            assigned_at = dict(row).get('assigned_at') if row else None
        except Exception:
            assigned_at = None
    block = None
    if package is not None:
        try:
            credit = float(package.get('credit_usd') or 0.0)
        except (TypeError, ValueError):
            credit = 0.0
        ai_tagged = _tagged_sum('ai_usage_events', package.get('id'))
        maps_tagged = _tagged_sum('map_usage_events', package.get('id'))
        if ai_tagged is None or maps_tagged is None:
            consumed = lifetime
        else:
            consumed = ai_tagged + maps_tagged
        remaining = max(0.0, credit - consumed)
        block = {
            'id': package.get('id'),
            'name': package.get('name'),
            'credit_usd': credit,
            'consumed_usd': consumed,
            'remaining_usd': remaining,
            'status': 'expired' if remaining <= 0 else 'active',
            'assigned_at': assigned_at,
        }
    return {
        'projects': int(counts.get('projects') or 0),
        'presentations': int(counts.get('presentations') or 0),
        'consumption_usd': lifetime,
        'package': block,
        'lifetime_consumed_usd': lifetime,
    }


def get_fx_rate(pair=FX_PAIR_USD_SAR):
    """Current stored rate with source and age. Defaults without raising."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT rate, source, updated_at FROM fx_rates WHERE pair = ?',
            (str(pair),)).fetchone()
        if row:
            data = dict(row)
            return {'pair': str(pair), 'rate': float(data.get('rate') or 0) or FX_DEFAULT_USD_SAR,
                    'source': data.get('source') or 'auto', 'updated_at': data.get('updated_at')}
    except Exception:
        pass
    try:
        configured = float(os.environ.get('FX_USD_SAR') or 0)
        if configured > 0:
            return {'pair': str(pair), 'rate': configured, 'source': 'env', 'updated_at': None}
    except (TypeError, ValueError):
        pass
    return {'pair': str(pair), 'rate': FX_DEFAULT_USD_SAR, 'source': 'default',
            'updated_at': None}


def set_fx_rate(pair, rate, source='manual'):
    """Super-admin override (manual) or fetched value (auto)."""
    try:
        value = float(rate)
    except (TypeError, ValueError):
        raise ValueError('Invalid rate')
    if value <= 0:
        raise ValueError('Invalid rate')
    if source not in ('auto', 'manual'):
        source = 'manual'
    conn = get_db()
    conn.execute(
        'INSERT INTO fx_rates (pair, rate, source, updated_at) VALUES (?, ?, ?, ?) '
        'ON CONFLICT (pair) DO UPDATE SET rate = excluded.rate, source = excluded.source, '
        "updated_at = datetime('now')",
        (str(pair), value, source, _utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    return get_fx_rate(pair)


def usd_to_sar(amount_usd, rate=None):
    """Convert dollars to riyals for display, rounded to 2."""
    try:
        active = float(rate) if rate else float(get_fx_rate()['rate'])
    except (TypeError, ValueError):
        active = FX_DEFAULT_USD_SAR
    try:
        return round(float(amount_usd or 0.0) * active + 1e-9, 2)
    except (TypeError, ValueError):
        return 0.0


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
    return {'projects': projects, 'presentations': presentations}


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
# contracts and the file-type registry. Money stays USD in tenant_ledger;
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
        prior_status TEXT
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

    # t52: contracts and NDAs with expiry dates the admin screens watch.
    conn.execute('''CREATE TABLE IF NOT EXISTS tenant_contracts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'contract',
        title TEXT NOT NULL,
        file_id TEXT,
        starts_at TEXT,
        expires_at TEXT,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_contracts_tenant ON tenant_contracts(tenant_id, expires_at)')

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

    # t21/t63: TOTP two-factor state on both login identities (tenant account
    # and individual users). mfa_pending_secret holds a not-yet-verified setup.
    for table in ('users', 'tenants'):
        _add(table, 'mfa_secret', 'mfa_secret TEXT')
        _add(table, 'mfa_pending_secret', 'mfa_pending_secret TEXT')
        _add(table, 'mfa_enabled', 'mfa_enabled INTEGER DEFAULT 0')

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

CONTRACT_SIGNATURE_STATUSES = ('unsigned', 'pending_signature', 'signed', 'expired')
# t52: 'framework' is a first-class kind — the UI offered it and the backend
# used to silently coerce it to 'contract', losing the distinction.
CONTRACT_KINDS = ('contract', 'nda', 'framework')
CONTRACT_RETENTION_DAYS = int(os.environ.get('CONTRACT_RETENTION_DAYS', '365'))


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

    # t60-03: contract versions carry the signed document and signature state;
    # tenant_contracts stays the head row pointing at the latest version.
    conn.execute('''CREATE TABLE IF NOT EXISTS tenant_contract_versions (
        id TEXT PRIMARY KEY,
        contract_id TEXT NOT NULL REFERENCES tenant_contracts(id) ON DELETE CASCADE,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        version INTEGER NOT NULL DEFAULT 1,
        file_id TEXT REFERENCES project_files(id) ON DELETE SET NULL,
        signature_status TEXT NOT NULL DEFAULT 'unsigned',
        starts_at TEXT,
        expires_at TEXT,
        retention_until TEXT,
        notes TEXT,
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_contract_version ON tenant_contract_versions(contract_id, version)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_contract_versions_tenant ON tenant_contract_versions(tenant_id)')

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
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_generation_jobs_idem ON generation_jobs(idempotency_key) WHERE idempotency_key IS NOT NULL')
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

    # t50/t52/t60-03: signature state and versioning on the contract head row.
    _add('tenant_contracts', 'signature_status', "TEXT DEFAULT 'unsigned'")
    _add('tenant_contracts', 'version', 'INTEGER DEFAULT 1')
    _add('tenant_contracts', 'retention_until', 'TEXT')
    _add('tenant_contracts', 'updated_at', 'TEXT')

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
    {'key': 'contract_file', 'label_ar': 'العقد أو اتفاقية السرية', 'label_en': 'Contract or NDA', 'kind': 'document',
     'max_size_mb': 25, 'allowed_extensions': ['.pdf']},
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
        'mfa_enabled, last_login_at, created_at FROM users WHERE tenant_id = ? ORDER BY created_at DESC',
        (tenant_id,),
    ).fetchall():
        item = dict(row)
        item['mfa_enabled'] = bool(item.get('mfa_enabled'))
        users.append(item)
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


# ── t14/t30: generation approval + atomic points reservation ────────────────

def estimate_generation_cost(tenant_id, draft_id=None, slides_count=0, presentation_id=None):
    """Price one generation run from real units, not billing history.

    A company with no usage history used to get a zero estimate and a free
    approval. The estimate is now the product price: one plan plus every
    slide plus each map and creative image the draft already asks for, at
    the effective unit prices (``GENERATION_UNIT_PRICES``).
    """
    prices = get_generation_unit_prices()
    slides = max(1, int(slides_count or 0))
    maps_count = 0
    images_count = 0
    if draft_id:
        try:
            draft = get_project_draft_by_id(tenant_id, draft_id)
            data = (draft or {}).get('draft_data') or {}
            if isinstance(data, str):
                data = json.loads(data) if data.strip() else {}
            creative = data.get('tenantCreativeImages') if isinstance(data, dict) else {}
            if isinstance(creative, dict):
                maps = creative.get('map_placeholders')
                if isinstance(maps, dict):
                    maps_count = sum(1 for value in maps.values() if value)
                moodboard = creative.get('moodboard')
                if isinstance(moodboard, list):
                    images_count = sum(1 for value in moodboard if value)
        except Exception:
            maps_count = images_count = 0
    units = {'plan': 1, 'slide': slides, 'map': maps_count, 'image': images_count}
    estimated = round(
        sum(units[key] * prices.get(key, 0.0) for key in units) + 1e-9, 4)
    return {
        'estimated_cost_usd': estimated,
        'estimated_points': int(round(estimated * POINTS_PER_USD)),
        'slides_count': slides,
        'units': units,
        'unit_prices': prices,
        'draft_id': draft_id,
        'presentation_id': presentation_id,
    }


def _draft_gate_transition(tenant_id, draft_id, target_status, actor_id, actor_name, reason):
    """Move a draft as part of an approval gate, warning instead of raising.

    Gate helpers already committed their own rows; a lifecycle failure here must
    surface in the result and the log without rolling the decision back.
    """
    if not draft_id:
        return None
    try:
        res = transition_project_draft_status(
            tenant_id, draft_id, target_status,
            actor_id=actor_id, actor_name=actor_name, reason=reason,
        )
    except Exception as exc:
        print(f'[LIFECYCLE] gate transition {draft_id} -> {target_status} crashed: {exc}')
        return None
    if res.get('error'):
        print(f"[LIFECYCLE] gate transition {draft_id} -> {target_status} refused: {res.get('error')}")
        return None
    return res


def create_generation_approval(tenant_id, draft_id, estimate, requested_by, requested_by_name,
                               presentation_id=None, input_snapshot=None):
    """Open a generation approval carrying the estimate shown to the approver.

    The request is what moves the draft into ``generation_approval_pending``:
    every tracked section must already be approved (the request itself fails
    early otherwise), one pending request per draft at a time, and a locked or
    generating draft refuses a new request. ``prior_status`` remembers where a
    rejected or released request returns the draft. ``input_snapshot`` freezes
    the priced inputs so the decision can verify nothing drifted meanwhile.
    """
    conn = get_db()
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return {'error': 'draft_not_found'}
    pending = conn.execute(
        "SELECT id FROM generation_approvals WHERE tenant_id = ? AND draft_id = ? AND status = 'pending'",
        (tenant_id, draft_id),
    ).fetchone()
    if pending:
        return {'error': 'approval_already_pending', 'approval_id': pending['id']}
    norm = normalize_proposal_status(draft.get('status'))
    if proposal_status_is_locked(norm):
        return {'error': 'draft_locked', 'status': norm}
    expired = expired_approved_sections(tenant_id, draft_id)
    if expired:
        return {'error': 'section_version_expired', 'sections': expired}
    if norm == 'generated_draft':
        # Regeneration: the file exists, a new gate opens on top of it.
        prior_status = 'generated_draft'
    elif norm in {'draft', 'sections_in_progress', 'section_approval_pending',
                  'rejected_for_revision', 'sections_approved'}:
        statuses = draft.get('section_statuses') or {}
        if statuses and any(value != 'approved' for value in statuses.values()):
            return {'error': 'sections_not_approved', 'section_statuses': statuses}
        prior_status = 'sections_approved'
        if norm != 'sections_approved':
            res = _draft_gate_transition(
                tenant_id, draft_id, 'sections_approved', requested_by, requested_by_name,
                'جميع أقسام المشروع معتمدة — تأهيل تلقائي قبل طلب التوليد')
            if res is None:
                return {'error': 'invalid_transition', 'current_status': norm,
                        'target_status': 'sections_approved'}
    else:
        return {'error': 'invalid_transition', 'current_status': norm}
    approval_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO generation_approvals
           (id, tenant_id, draft_id, presentation_id, estimated_cost_usd, estimated_points,
            slides_count, status, requested_by, requested_by_name, prior_status, input_snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)''',
        (approval_id, tenant_id, draft_id, presentation_id,
         float(estimate.get('estimated_cost_usd') or 0), int(estimate.get('estimated_points') or 0),
         int(estimate.get('slides_count') or 0), requested_by, requested_by_name, prior_status,
         json.dumps(input_snapshot, ensure_ascii=False) if isinstance(input_snapshot, dict) else None),
    )
    conn.commit()
    _draft_gate_transition(
        tenant_id, draft_id, 'generation_approval_pending', requested_by, requested_by_name,
        'طلب اعتماد التوليد')
    row = conn.execute('SELECT * FROM generation_approvals WHERE id = ?', (approval_id,)).fetchone()
    return dict(row)


def decide_generation_approval(tenant_id, approval_id, decision, decided_by, decided_by_name,
                               note=None, allow_self=False):
    """Approve, reject or cancel. Approval reserves the points atomically.

    Separation of duties (d02): the requester cannot approve or reject their own
    request. Only a company-level administrator may combine both hats, which the
    route expresses through allow_self.
    """
    if decision not in {'approved', 'rejected', 'cancelled'}:
        return {'error': 'invalid_decision'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM generation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'approval_not_found'}
    if row['status'] != 'pending':
        return {'error': 'approval_not_pending'}
    if decision == 'cancelled' and row['requested_by'] and str(row['requested_by']) != str(decided_by):
        return {'error': 'cancel_not_allowed'}
    if decision in {'approved', 'rejected'} and not allow_self \
            and row['requested_by'] and str(row['requested_by']) == str(decided_by):
        return {'error': 'self_approval_not_allowed'}
    if decision == 'approved' and row['draft_id']:
        # Approving generation confirms the gate behind it: every tracked
        # section of the draft must already be approved.
        draft = get_project_draft_by_id(tenant_id, row['draft_id'])
        statuses = (draft or {}).get('section_statuses') or {}
        if statuses and any(value != 'approved' for value in statuses.values()):
            return {'error': 'sections_not_approved', 'section_statuses': statuses}
        # d05: an approval that expired while the request waited is no
        # longer a gate the run can rely on.
        expired = expired_approved_sections(tenant_id, row['draft_id'])
        if expired:
            return {'error': 'section_version_expired', 'sections': expired}
        # t14-04/t15-01: the inputs the approver saw and priced must still be
        # what generation will run on — edits after the request void it.
        snapshot = _json_object(row['input_snapshot'] if 'input_snapshot' in row.keys() else None)
        wanted_hash = snapshot.get('draft_hash')
        if wanted_hash and draft \
                and draft_generation_input_hash(draft.get('draft_data') or {}) != wanted_hash:
            return {'error': 'inputs_changed'}
        # And the draft must be able to enter 'generating' right now — an
        # approved reservation on an unreachable state would strand the run.
        if draft and not can_transition_proposal_status(draft.get('status'), 'generating'):
            return {'error': 'invalid_transition',
                    'current_status': normalize_proposal_status(draft.get('status')),
                    'target_status': 'generating'}
        # Free any expired holds first so the balance check below reads the
        # real available wallet, not one inflated by dead runs.
        release_stale_reservations(tenant_id)
    reservation_id = None
    conn.execute(
        '''UPDATE generation_approvals SET status = ?, decided_by = ?, decided_by_name = ?,
           decided_at = ?, decision_note = ? WHERE id = ?''',
        (decision, decided_by, decided_by_name, _utcnow().isoformat(), str(note or '').strip() or None, approval_id),
    )
    if decision == 'approved' and int(row['estimated_points'] or 0) > 0:
        # One commit covers the decision and the escrow: an approval that
        # cannot hold its points rolls the decision back with it.
        reservation = _hold_points_tx(
            conn, tenant_id, row['estimated_points'], row['estimated_cost_usd'],
            reserved_by=decided_by, reserved_by_name=decided_by_name,
            generation_approval_id=approval_id, draft_id=row['draft_id'],
            presentation_id=(row['presentation_id'] if 'presentation_id' in row.keys() else None),
        )
        if reservation.get('error'):
            conn.rollback()
            return reservation
        reservation_id = reservation['id']
    conn.commit()
    if reservation_id:
        _fire_balance_change(tenant_id)
    updated = dict(conn.execute('SELECT * FROM generation_approvals WHERE id = ?', (approval_id,)).fetchone())
    if decision == 'approved':
        if reservation_id:
            updated['reservation_id'] = reservation_id
        # Approval starts the run: the draft leaves the queue for 'generating'.
        lifecycle = _draft_gate_transition(
            tenant_id, row['draft_id'], 'generating', decided_by, decided_by_name,
            'اعتماد طلب التوليد — بدء التنفيذ')
        if lifecycle:
            updated['draft_status'] = lifecycle.get('current_status')
        elif row['draft_id']:
            # The gate could not open — roll the decision and the reservation
            # back so nothing is approved against a draft that never started.
            if reservation_id:
                release_points(tenant_id, reservation_id, settled_by=decided_by,
                               note='تراجع الاعتماد: تعذر الانتقال إلى التوليد')
            conn.execute(
                "UPDATE generation_approvals SET status = 'pending', decided_by = NULL, "
                'decided_by_name = NULL, decided_at = NULL WHERE id = ?',
                (approval_id,),
            )
            conn.commit()
            return {'error': 'lifecycle_transition_failed', 'target_status': 'generating'}
    else:
        # Rejected or withdrawn: the draft returns to the state it was requested
        # from — approved sections, or the generated file for a re-run.
        prior = ((row['prior_status'] if 'prior_status' in row.keys() else '') or '').strip()
        if prior not in PROPOSAL_LIFECYCLE_STATES:
            prior = 'sections_approved'
        lifecycle = _draft_gate_transition(
            tenant_id, row['draft_id'], prior, decided_by, decided_by_name,
            str(note or '').strip() or 'قرار على طلب اعتماد التوليد')
        if lifecycle:
            updated['draft_status'] = lifecycle.get('current_status')
    return updated


def settle_generation_approval(tenant_id, approval_id, job_id, consumed=True, settled_by=None, note=None):
    """After the generation job finishes: consume the reservation once, or release it.

    Settlement is also the lifecycle boundary: a consumed run lands the draft on
    ``generated_draft``; a released one returns it to the state the request came
    from so a new approval can be opened.
    """
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM generation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'approval_not_found'}
    if row['status'] != 'approved':
        return {'error': 'approval_not_approved'}
    reservations = conn.execute(
        "SELECT * FROM point_reservations WHERE generation_approval_id = ? AND status = 'reserved'",
        (approval_id,),
    ).fetchall()
    settled = []
    for reservation in reservations:
        if consumed:
            result = consume_points(tenant_id, reservation['id'], settled_by=settled_by, note=note or job_id)
        else:
            result = release_points(tenant_id, reservation['id'], settled_by=settled_by, note=note or job_id)
        if result.get('error'):
            return result
        settled.append(result['id'])
    conn.execute(
        'UPDATE generation_approvals SET status = ?, job_id = ? WHERE id = ?',
        ('consumed' if consumed else 'rejected', job_id, approval_id),
    )
    conn.commit()
    if consumed:
        lifecycle = _draft_gate_transition(
            tenant_id, row['draft_id'], 'generated_draft', settled_by, settled_by,
            'اكتمال التوليد وحفظ العرض')
    else:
        prior = ((row['prior_status'] if 'prior_status' in row.keys() else '') or '').strip()
        if prior not in PROPOSAL_LIFECYCLE_STATES:
            prior = 'sections_approved'
        lifecycle = _draft_gate_transition(
            tenant_id, row['draft_id'], prior, settled_by, settled_by,
            str(note or '').strip() or 'تحرير حجز التوليد بعد فشل أو إلغاء')
    result = {'id': approval_id, 'status': 'consumed' if consumed else 'rejected', 'reservations': settled}
    if lifecycle:
        result['draft_status'] = lifecycle.get('current_status')
    return result


def _reservation_hold_key(reservation_id):
    return f'hold:{reservation_id}'


def _hold_points_tx(conn, tenant_id, points, cost_usd, reserved_by=None, reserved_by_name=None,
                    generation_approval_id=None, draft_id=None, presentation_id=None, note=None):
    """Escrow the hold inside an open transaction — never commits.

    The wallet debit is a conditional UPDATE, so two parallel holds cannot
    spend the same balance: the loser sees rowcount 0 and reports
    ``insufficient_balance``. A live hold on the same approval is returned
    as-is (the unique index makes a second row impossible anyway).
    """
    points = int(points or 0)
    cost = round(float(cost_usd or 0.0) + 1e-9, 2)
    if points <= 0 or cost <= 0:
        return {'error': 'nothing_to_reserve'}
    if generation_approval_id:
        existing = conn.execute(
            "SELECT * FROM point_reservations WHERE generation_approval_id = ? AND status = 'reserved'",
            (generation_approval_id,),
        ).fetchone()
        if existing:
            return dict(existing)
    debit = conn.execute(
        'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) - ? '
        'WHERE id = ? AND COALESCE(credit_balance, 0) >= ?',
        (cost, tenant_id, cost),
    )
    if (debit.rowcount or 0) <= 0:
        return {'error': 'insufficient_balance',
                'available_usd': get_tenant_balance(tenant_id),
                'required_usd': cost}
    reservation_id = str(uuid.uuid4())
    now = _utcnow()
    expires = (now + timedelta(hours=RESERVATION_TTL_HOURS)).isoformat()
    conn.execute(
        '''INSERT INTO point_reservations
           (id, tenant_id, generation_approval_id, draft_id, points, cost_usd,
            status, reserved_by, reserved_by_name, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?)''',
        (reservation_id, tenant_id, generation_approval_id, draft_id, points,
         cost, reserved_by, reserved_by_name, expires),
    )
    conn.execute(
        '''INSERT INTO tenant_ledger
           (id, tenant_id, kind, amount_usd, draft_id, presentation_id, idempotency_key, note)
           VALUES (?, ?, 'hold', ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), tenant_id, cost, draft_id, presentation_id,
         _reservation_hold_key(reservation_id),
         str(note or '').strip() or 'حجز نقاط التوليد'),
    )
    row = conn.execute('SELECT * FROM point_reservations WHERE id = ?', (reservation_id,)).fetchone()
    return dict(row)


def _claim_run_usage_tx(conn, tenant_id, ledger_id, draft_id=None, presentation_id=None):
    """Attach the run's unbilled usage events to the settling ledger row.

    The reservation price is what the client pays; claiming the usage events
    under the same entry records the provider cost on it and keeps checkout
    from billing the run a second time. Events are attributed to the draft or
    the presentation — either link counts as this run.
    """
    empty = {'ai_events_count': 0, 'maps_events_count': 0, 'raw_cost_usd': 0.0,
             'ai_cost_usd': 0.0, 'maps_cost_usd': 0.0}
    if not ledger_id:
        return empty
    clauses = ['tenant_id = ?', 'billed_ledger_id IS NULL']
    params = [tenant_id]
    links = []
    if draft_id:
        links.append('draft_id = ?')
        params.append(draft_id)
    if presentation_id:
        links.append('presentation_id = ?')
        params.append(presentation_id)
    if not links:
        return empty
    where = 'WHERE ' + clauses[0] + ' AND ' + clauses[1] + ' AND (' + ' OR '.join(links) + ')'
    ai_claim = conn.execute(
        'UPDATE ai_usage_events SET billed_ledger_id = ? ' + where,
        tuple([ledger_id] + params),
    )
    maps_claim = conn.execute(
        'UPDATE map_usage_events SET billed_ledger_id = ? ' + where,
        tuple([ledger_id] + params),
    )
    ai_count = max(0, int(ai_claim.rowcount or 0))
    maps_count = max(0, int(maps_claim.rowcount or 0))
    ai_cost = float(dict(conn.execute(
        'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM ai_usage_events WHERE billed_ledger_id = ?',
        (ledger_id,),
    ).fetchone()).get('total') or 0.0)
    maps_cost = float(dict(conn.execute(
        'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM map_usage_events WHERE billed_ledger_id = ?',
        (ledger_id,),
    ).fetchone()).get('total') or 0.0)
    return {'ai_events_count': ai_count, 'maps_events_count': maps_count,
            'raw_cost_usd': ai_cost + maps_cost, 'ai_cost_usd': ai_cost,
            'maps_cost_usd': maps_cost}


def _settle_reservation_tx(conn, tenant_id, row, new_status, settled_by=None, note=None):
    """Flip a live reservation once, inside an open transaction — never commits.

    ``consumed`` reclassifies the escrow hold as the debit that pays the run
    and claims the run's usage events onto it. ``released`` refunds the hold
    to the wallet. Both are guarded by the status flip, so a settled
    reservation can never settle again.
    """
    reservation_id = row['id']
    settled = conn.execute(
        "UPDATE point_reservations SET status = ?, settled_at = ?, settled_by = ?, note = ? "
        "WHERE id = ? AND status = 'reserved'",
        (new_status, _utcnow().isoformat(), settled_by,
         str(note or '').strip() or None, reservation_id),
    )
    if (settled.rowcount or 0) <= 0:
        return {'error': 'reservation_not_reserved'}
    hold = conn.execute(
        'SELECT * FROM tenant_ledger WHERE idempotency_key = ?',
        (_reservation_hold_key(reservation_id),),
    ).fetchone()
    if new_status == 'consumed':
        usage = _claim_run_usage_tx(
            conn, tenant_id, hold['id'] if hold else None,
            draft_id=row['draft_id'],
            presentation_id=(hold['presentation_id'] if hold and 'presentation_id' in hold.keys() else None))
        if hold:
            conn.execute(
                '''UPDATE tenant_ledger SET kind = 'debit', raw_cost_usd = ?, multiplier = ?,
                   maps_cost_usd = ?, ai_cost_usd = ?, maps_events_count = ?, ai_events_count = ?,
                   note = ? WHERE id = ?''',
                (usage['raw_cost_usd'], get_billing_multiplier(), usage['maps_cost_usd'],
                 usage['ai_cost_usd'], usage['maps_events_count'], usage['ai_events_count'],
                 str(note or '').strip() or 'تسوية حجز التوليد', hold['id']),
            )
        else:
            # A legacy hold with no escrow: debit the wallet directly so the
            # consumption still lands on the real ledger.
            amount = float(row['cost_usd'] or 0.0)
            if amount > 0:
                debit = conn.execute(
                    'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) - ? '
                    'WHERE id = ? AND COALESCE(credit_balance, 0) >= ?',
                    (amount, tenant_id, amount),
                )
                if (debit.rowcount or 0) <= 0:
                    raise InsufficientBalance(amount, get_tenant_balance(tenant_id))
                conn.execute(
                    '''INSERT INTO tenant_ledger
                       (id, tenant_id, kind, amount_usd, draft_id, idempotency_key, note)
                       VALUES (?, ?, 'debit', ?, ?, ?, ?)''',
                    (str(uuid.uuid4()), tenant_id, amount, row['draft_id'],
                     f'consume:{reservation_id}', str(note or '').strip() or 'تسوية حجز التوليد'),
                )
    elif new_status == 'released':
        if hold:
            # Refund the escrow: the hold row becomes the release movement so
            # the ledger still nets out to the real balance.
            conn.execute(
                "UPDATE tenant_ledger SET kind = 'release', note = ? WHERE id = ?",
                (str(note or '').strip() or 'تحرير حجز التوليد', hold['id']),
            )
            conn.execute(
                'UPDATE tenants SET credit_balance = COALESCE(credit_balance, 0) + ? WHERE id = ?',
                (float(row['cost_usd'] or 0.0), tenant_id),
            )
    return dict(conn.execute('SELECT * FROM point_reservations WHERE id = ?', (reservation_id,)).fetchone())


def reserve_points(tenant_id, points, cost_usd=0, reserved_by=None, reserved_by_name=None,
                   generation_approval_id=None, draft_id=None, presentation_id=None, note=None):
    """t31: escrow points against the wallet before a generation run.

    Atomic with the balance: stale holds are swept first, the conditional
    debit and the reservation row commit together, and a live hold on the
    same approval is returned instead of duplicated.
    """
    release_stale_reservations(tenant_id)
    conn = get_db()
    result = _hold_points_tx(
        conn, tenant_id, points, cost_usd,
        reserved_by=reserved_by, reserved_by_name=reserved_by_name,
        generation_approval_id=generation_approval_id, draft_id=draft_id,
        presentation_id=presentation_id, note=note)
    if result.get('error'):
        conn.rollback()
        return result
    conn.commit()
    _fire_balance_change(tenant_id)
    return result


def consume_points(tenant_id, reservation_id, settled_by=None, note=None):
    """Settle a reservation exactly once; a second call is refused."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM point_reservations WHERE id = ? AND tenant_id = ?',
        (reservation_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'reservation_not_found'}
    if row['status'] != 'reserved':
        return {'error': 'reservation_not_reserved'}
    try:
        result = _settle_reservation_tx(conn, tenant_id, row, 'consumed',
                                        settled_by=settled_by, note=note)
    except InsufficientBalance as short:
        conn.rollback()
        return {'error': 'insufficient_balance', 'required_usd': short.required_usd,
                'available_usd': short.available_usd}
    if result.get('error'):
        conn.rollback()
        return result
    conn.commit()
    _fire_balance_change(tenant_id)
    return result


def release_points(tenant_id, reservation_id, settled_by=None, note=None):
    """Free a reservation after a failed generation; the escrow is refunded."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM point_reservations WHERE id = ? AND tenant_id = ?',
        (reservation_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'reservation_not_found'}
    if row['status'] != 'reserved':
        return {'error': 'reservation_not_reserved'}
    result = _settle_reservation_tx(conn, tenant_id, row, 'released',
                                    settled_by=settled_by, note=note)
    if result.get('error'):
        conn.rollback()
        return result
    conn.commit()
    _fire_balance_change(tenant_id)
    return result


def release_stale_reservations(tenant_id=None):
    """Reaper for orphaned holds: expire them, refund the escrow, and return
    their drafts from ``generating`` to the state the request came from.

    A browser that dies mid-run leaves the hold, the approved request and the
    draft state behind; this sweep heals all three. It runs lazily on the
    paths that touch the wallet (new holds, reservation lists).
    """
    conn = get_db()
    now = _utcnow().isoformat()
    clauses = ["status = 'reserved'", "expires_at IS NOT NULL", 'expires_at < ?']
    params = [now]
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    try:
        rows = conn.execute(
            'SELECT * FROM point_reservations WHERE ' + ' AND '.join(clauses),
            tuple(params),
        ).fetchall()
    except Exception:
        return 0
    released = []
    for row in rows:
        result = _settle_reservation_tx(conn, row['tenant_id'], row, 'released',
                                        settled_by='system', note='انتهت صلاحية حجز التوليد')
        if not result.get('error'):
            released.append(row)
    if not released:
        return 0
    for row in released:
        if row['generation_approval_id']:
            conn.execute(
                """UPDATE generation_approvals SET status = 'expired', job_id = ?
                   WHERE id = ? AND status = 'approved'""",
                ('reservation-expired', row['generation_approval_id']),
            )
    conn.commit()
    for _tid in {row['tenant_id'] for row in released}:
        _fire_balance_change(_tid)
    for row in released:
        # After the money is settled, bring back a draft the dead run left in
        # 'generating'. Transitions commit themselves — they stay out of the
        # wallet transaction on purpose.
        approval_id = row['generation_approval_id']
        if not approval_id or not row['draft_id']:
            continue
        approval = conn.execute(
            'SELECT prior_status FROM generation_approvals WHERE id = ?', (approval_id,),
        ).fetchone()
        draft = get_project_draft_by_id(row['tenant_id'], row['draft_id'])
        if draft and normalize_proposal_status(draft.get('status')) == 'generating':
            prior = ((approval['prior_status'] if approval and 'prior_status' in approval.keys() else '') or '').strip()
            if prior not in PROPOSAL_LIFECYCLE_STATES:
                prior = 'sections_approved'
            _draft_gate_transition(
                row['tenant_id'], row['draft_id'], prior, 'system', 'النظام',
                'استرداد حجز منتهي — إعادة الملف لحالته السابقة')
    return len(released)


def list_point_reservations(tenant_id, status=None, limit=100):
    release_stale_reservations(tenant_id)
    conn = get_db()
    if status:
        rows = conn.execute(
            'SELECT * FROM point_reservations WHERE tenant_id = ? AND status = ? ORDER BY reserved_at DESC LIMIT ?',
            (tenant_id, status, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM point_reservations WHERE tenant_id = ? ORDER BY reserved_at DESC LIMIT ?',
            (tenant_id, int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def get_active_hold_total_usd(tenant_id):
    """Wallet amount currently escrowed in live generation holds.

    Held money is already spent from the wallet but still entitles the run
    to provider spend, so the key-limit sync adds it back on top of the
    free balance. Pure read — the stale sweep is the caller's job.
    """
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM point_reservations "
            "WHERE tenant_id = ? AND status = 'reserved'", (str(tenant_id),),
        ).fetchone()
        return float(dict(row).get('total') or 0.0)
    except Exception:
        return 0.0


def get_package_remaining_usd(tenant_id):
    """Unburned credit of the tenant's assigned package, in raw USD.

    Package consumption is implicit — usage rows tagged with the package id
    at write time — so remaining = package credit minus tagged spend. No
    assigned package means no package credit, never an error.
    """
    try:
        conn = get_db()
        tenant = conn.execute(
            'SELECT package_id FROM tenants WHERE id = ?', (str(tenant_id),),
        ).fetchone()
        package_id = dict(tenant).get('package_id') if tenant else None
        if not package_id:
            return 0.0
        package = get_billing_package(package_id)
        if not package:
            return 0.0
        credit = float(package.get('credit_usd') or 0.0)
        consumed = 0.0
        for table in ('ai_usage_events', 'map_usage_events'):
            try:
                row = conn.execute(
                    f'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM {table} '
                    'WHERE tenant_id = ? AND package_id = ?',
                    (str(tenant_id), str(package_id)),
                ).fetchone()
                consumed += float(dict(row).get('total') or 0.0)
            except Exception:
                pass
        return max(0.0, credit - consumed)
    except Exception:
        return 0.0


def list_tenants_with_billable_usage(limit=200):
    """Tenants holding usage a ledger entry could bill right now.

    Feeds the periodic billing sweep: AI rows qualify only once their cost
    is settled (the checkout claim uses the same clause), Maps rows always
    qualify. Super admins are never billed.
    """
    conn = get_db()
    rows = conn.execute(
        'SELECT tenant_id FROM ('
        '  SELECT DISTINCT tenant_id FROM ai_usage_events '
        '   WHERE billed_ledger_id IS NULL AND tenant_id IS NOT NULL '
        '     AND package_id IS NULL AND ' + _AI_BILLABLE_STATUS_CLAUSE +
        '  UNION '
        '  SELECT DISTINCT tenant_id FROM map_usage_events '
        '   WHERE billed_ledger_id IS NULL AND tenant_id IS NOT NULL '
        '     AND package_id IS NULL'
        ') WHERE tenant_id NOT IN (SELECT id FROM tenants WHERE COALESCE(is_admin, 0) = 1) '
        'LIMIT ?', (int(limit),),
    ).fetchall()
    return [row[0] for row in rows]


def get_generation_approval(tenant_id, approval_id):
    sweep_stale_generation_jobs(tenant_id)
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM generation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    return dict(row) if row else None


def list_generation_approvals(tenant_id, status=None, limit=50):
    sweep_stale_generation_jobs(tenant_id)
    conn = get_db()
    query = ('SELECT ga.*, pd.title AS draft_title FROM generation_approvals ga '
             'LEFT JOIN project_drafts pd ON pd.id = ga.draft_id AND pd.tenant_id = ga.tenant_id '
             'WHERE ga.tenant_id = ?')
    params = [tenant_id]
    if status:
        query += ' AND ga.status = ?'
        params.append(status)
    query += ' ORDER BY ga.requested_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(row) for row in conn.execute(query, params).fetchall()]


# ── t15: final approval, digital stamp and the downloads library ────────────

def _file_sha256(path):
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def stamp_final_file(app_root, tenant_id, presentation_id, revision=0):
    """A stamp is not a decoration: the sha256 of the file bytes plus who decided."""
    conn = get_db()
    approval = conn.execute(
        "SELECT * FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ? AND status = 'approved' "
        'ORDER BY decided_at DESC LIMIT 1',
        (tenant_id, presentation_id),
    ).fetchone()
    if not approval:
        return {'error': 'not_approved'}
    row = conn.execute(
        'SELECT id, file_path FROM exports WHERE presentation_id = ? ORDER BY created_at DESC LIMIT 1',
        (presentation_id,),
    ).fetchone()
    if not row or not row['file_path']:
        return {'error': 'no_export_file'}
    path = row['file_path']
    if not os.path.isabs(path):
        path = os.path.join(app_root, path)
    digest = _file_sha256(path)
    if not digest:
        return {'error': 'stamp_failed'}
    conn.execute(
        'UPDATE final_file_approvals SET content_hash = ?, stamped_export_id = ? WHERE id = ?',
        (digest, row['id'], approval['id']))
    conn.commit()
    return {
        'approval_id': approval['id'],
        'content_hash': digest,
        'export_id': row['id'],
        'decided_by_name': approval['decided_by_name'],
        'decided_at': approval['decided_at'],
        'revision': int(revision or 0),
        'algorithm': 'sha256',
    }


def request_final_file_approval(tenant_id, presentation_id, requested_by, requested_by_name, revision=0):
    """Send a generated file to the final approver.

    The request itself moves the linked draft to ``final_approval_pending``
    before the approval row exists, so a draft that cannot legally enter the
    gate refuses the request instead of opening an approval on a stale state.
    A presentation without a linked draft keeps the legacy unlinked behaviour.
    """
    conn = get_db()
    presentation = get_presentation(presentation_id, tenant_id=tenant_id)
    if not presentation:
        return {'error': 'presentation_not_found'}
    pending = conn.execute(
        "SELECT id FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ? AND status = 'pending'",
        (tenant_id, presentation_id),
    ).fetchone()
    if pending:
        return {'error': 'approval_already_pending', 'approval_id': pending['id']}
    # The request pins the exact file content being sent. Re-sending the same
    # content after a rejection is refused — the next request must carry an
    # actual revision (t15-07) — and an unchanged re-request on an approved
    # file is a no-op.
    request_hash = _presentation_review_hash(presentation)
    latest = conn.execute(
        "SELECT id, status, request_hash FROM final_file_approvals "
        "WHERE tenant_id = ? AND presentation_id = ? AND status != 'pending' "
        'ORDER BY requested_at DESC LIMIT 1',
        (tenant_id, presentation_id),
    ).fetchone()
    if latest is not None and 'request_hash' in latest.keys() \
            and latest['request_hash'] and latest['request_hash'] == request_hash:
        if latest['status'] == 'approved':
            return {'error': 'already_approved', 'approval_id': latest['id']}
        if latest['status'] == 'rejected':
            return {'error': 'unchanged_since_rejection', 'approval_id': latest['id']}
    draft_id = presentation.get('draft_id')
    if draft_id and get_project_draft_by_id(tenant_id, draft_id):
        res = transition_project_draft_status(
            tenant_id, draft_id, 'final_approval_pending',
            actor_id=requested_by, actor_name=requested_by_name,
            reason='إرسال الملف النهائي للاعتماد',
        )
        if res.get('error'):
            return res
    approval_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO final_file_approvals
           (id, tenant_id, presentation_id, revision, status, requested_by, requested_by_name, request_hash)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)''',
        (approval_id, tenant_id, presentation_id, int(revision or 0), requested_by, requested_by_name,
         request_hash),
    )
    conn.commit()
    row = conn.execute('SELECT * FROM final_file_approvals WHERE id = ?', (approval_id,)).fetchone()
    return dict(row)


def decide_final_file_approval(tenant_id, approval_id, decision, decided_by, decided_by_name,
                               note=None, allow_self=False, app_root=None):
    """Decide the final-file gate. The requester may not self-approve (d02);
    allow_self is reserved for company-level administrators.

    The decision drives the draft lifecycle: approval lands the draft on
    ``approved`` (and the presentation follows through the transition sync),
    while a rejection — which needs a written reason — returns it to
    ``generated_draft`` for rework. Approving also stamps the produced file:
    its content hash and the exact export become the download gate's proof.
    """
    if decision not in {'approved', 'rejected'}:
        return {'error': 'invalid_decision'}
    clean_note = str(note or '').strip()
    if decision == 'rejected' and not clean_note:
        return {'error': 'note_required'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM final_file_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'approval_not_found'}
    if row['status'] != 'pending':
        return {'error': 'approval_not_pending'}
    if not allow_self and row['requested_by'] and str(row['requested_by']) == str(decided_by):
        return {'error': 'self_approval_not_allowed'}
    pres = conn.execute(
        'SELECT draft_id, status, project_data, slides_data FROM presentations WHERE id = ? AND tenant_id = ?',
        (row['presentation_id'], tenant_id),
    ).fetchone()
    if decision == 'approved' and pres is not None:
        # The approver decides on the content that was sent — a file edited
        # after the request must be sent again, not approved blind.
        request_hash = row['request_hash'] if 'request_hash' in row.keys() else None
        if request_hash and _presentation_review_hash(dict(pres)) != request_hash:
            return {'error': 'content_changed'}
    draft_id = pres['draft_id'] if pres else None
    target_status = 'approved' if decision == 'approved' else 'generated_draft'
    if draft_id:
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if draft and not can_transition_proposal_status(draft.get('status'), target_status):
            return {'error': 'invalid_transition',
                    'current_status': normalize_proposal_status(draft.get('status')),
                    'target_status': target_status}
    conn.execute(
        '''UPDATE final_file_approvals SET status = ?, decided_by = ?, decided_by_name = ?,
           decided_at = ?, decision_note = ? WHERE id = ?''',
        (decision, decided_by, decided_by_name, _utcnow().isoformat(),
         clean_note or None, approval_id),
    )
    if decision == 'approved':
        conn.execute(
            "UPDATE presentations SET status = 'approved' WHERE id = ? AND tenant_id = ?",
            (row['presentation_id'], tenant_id),
        )
    conn.commit()
    lifecycle = _draft_gate_transition(
        tenant_id, draft_id, target_status, decided_by, decided_by_name,
        clean_note or ('اعتماد الملف النهائي' if decision == 'approved' else 'إعادة الملف النهائي للتعديل'))
    if lifecycle is None and draft_id:
        # The decision must not stand while the linked draft stayed behind.
        conn.execute(
            "UPDATE final_file_approvals SET status = 'pending', decided_by = NULL, "
            'decided_by_name = NULL, decided_at = NULL, decision_note = NULL WHERE id = ?',
            (approval_id,),
        )
        if decision == 'approved':
            conn.execute(
                'UPDATE presentations SET status = ? WHERE id = ? AND tenant_id = ?',
                ((pres['status'] if pres else None) or 'generated_draft', row['presentation_id'], tenant_id),
            )
        conn.commit()
        return {'error': 'lifecycle_transition_failed', 'target_status': target_status}
    updated = dict(conn.execute('SELECT * FROM final_file_approvals WHERE id = ?', (approval_id,)).fetchone())
    if lifecycle:
        updated['draft_status'] = lifecycle.get('current_status')
    if decision == 'approved' and app_root:
        # The stamp binds the approved content hash to the produced export;
        # a missing export leaves the approval standing but reports why the
        # file is not stamped yet.
        stamp = stamp_final_file(app_root, tenant_id, row['presentation_id'],
                                 revision=row['revision'])
        if stamp.get('error'):
            updated['stamp_error'] = stamp['error']
        else:
            updated['stamped_file'] = stamp
            updated['content_hash'] = stamp['content_hash']
            updated['stamped_export_id'] = stamp['export_id']
    return updated


def latest_final_file_approval(tenant_id, presentation_id, status=None):
    """The newest final-file approval of a presentation, status-filtered."""
    conn = get_db()
    query = ('SELECT * FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ?')
    params = [tenant_id, presentation_id]
    if status:
        query += ' AND status = ?'
        params.append(status)
    query += ' ORDER BY requested_at DESC LIMIT 1'
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


def list_final_file_approvals(tenant_id, presentation_id=None, status=None, limit=50):
    conn = get_db()
    query = ('SELECT ffa.*, p.title AS presentation_title FROM final_file_approvals ffa '
             'LEFT JOIN presentations p ON p.id = ffa.presentation_id AND p.tenant_id = ffa.tenant_id '
             'WHERE ffa.tenant_id = ?')
    params = [tenant_id]
    if presentation_id:
        query += ' AND ffa.presentation_id = ?'
        params.append(presentation_id)
    if status:
        query += ' AND ffa.status = ?'
        params.append(status)
    query += ' ORDER BY ffa.requested_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def record_download(tenant_id, file_name, presentation_id=None, draft_id=None, format='pdf',
                    version_label=None, approval_status=None, generated_by=None,
                    generated_by_name=None, file_size=0, export_id=None):
    """t15: every generated file enters the library with who made and approved it.

    The approval state is read from the final-file gate, never trusted from
    the client: an approved decision names its approver, a pending request
    marks the row pending, and anything else is a draft.
    """
    conn = get_db()
    if export_id:
        export_row = conn.execute(
            'SELECT * FROM exports WHERE id = ? AND tenant_id = ?',
            (export_id, tenant_id),
        ).fetchone()
        if export_row:
            presentation_id = presentation_id or export_row['presentation_id']
            if not file_size and export_row['file_path']:
                try:
                    file_size = os.path.getsize(export_row['file_path'])
                except OSError:
                    file_size = 0
    if not draft_id and presentation_id:
        pres_row = conn.execute(
            'SELECT draft_id FROM presentations WHERE id = ? AND tenant_id = ?',
            (presentation_id, tenant_id),
        ).fetchone()
        if pres_row:
            draft_id = pres_row['draft_id']
    approval = None
    if presentation_id:
        approval = conn.execute(
            "SELECT * FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ? "
            "AND status = 'approved' ORDER BY decided_at DESC LIMIT 1",
            (tenant_id, presentation_id),
        ).fetchone()
    if approval_status is None:
        approval_status = 'approved' if approval else 'pending'
    approved_by_name = approval['decided_by_name'] if approval else None
    if not version_label and presentation_id:
        pres_row = conn.execute(
            'SELECT revision FROM presentations WHERE id = ? AND tenant_id = ?',
            (presentation_id, tenant_id),
        ).fetchone()
        if pres_row:
            version_label = f"v{int(pres_row['revision'] or 0)}"
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO presentation_downloads
           (id, tenant_id, presentation_id, draft_id, file_name, format, version_label,
            approval_status, generated_by, generated_by_name, approved_by_name, file_size, export_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, tenant_id, presentation_id, draft_id, file_name, format, version_label,
         approval_status, generated_by, generated_by_name, approved_by_name,
         int(file_size or 0), export_id),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM presentation_downloads WHERE id = ?', (row_id,)).fetchone())


def mark_download_downloaded(tenant_id, download_id, downloaded_by_name=None):
    conn = get_db()
    now = _utcnow().isoformat()
    cursor = conn.execute(
        'UPDATE presentation_downloads SET downloaded_at = ?, downloaded_by_name = ? '
        'WHERE id = ? AND tenant_id = ? AND downloaded_at IS NULL',
        (now, downloaded_by_name, download_id, tenant_id),
    )
    conn.commit()
    if cursor.rowcount:
        return dict(conn.execute('SELECT * FROM presentation_downloads WHERE id = ?', (download_id,)).fetchone())
    return None


def list_downloads(tenant_id, presentation_id=None, limit=100):
    conn = get_db()
    if presentation_id:
        rows = conn.execute(
            'SELECT * FROM presentation_downloads WHERE tenant_id = ? AND presentation_id = ? ORDER BY generated_at DESC LIMIT ?',
            (tenant_id, presentation_id, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM presentation_downloads WHERE tenant_id = ? ORDER BY generated_at DESC LIMIT ?',
            (tenant_id, int(limit)),
        ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        # The library serves the file through the gated export endpoint only,
        # and only a row whose final approval landed carries a usable URL.
        item['download_url'] = (
            f"/api/exports/{item['export_id']}/download"
            if item.get('export_id') and item.get('approval_status') == 'approved' else None)
    return items


# ── t17/t18: copy a proposal, archive and restore ───────────────────────────

# Keys that describe the source proposal's workflow, approvals or generated
# output — none of them may cross into a copy (t17).
DRAFT_COPY_STRIPPED_KEYS = {
    # Section approvals and overall lifecycle bookkeeping.
    'sectionStatuses', 'draftHistory', 'tenantArchiveCache',
    # Generated artifacts the copy must re-earn through the gates.
    'tenantSlidesData', 'tenantSlidePlan', 'slide_generation_checkpoint',
    'tenantCreativeImages', 'pageDrafts',
    # Designer/chat working state of the source file.
    'designerChat', 'designerChatSessions', 'chatHistory',
    # Identity fields that must not point back at the source draft.
    'draftId', 'draft_id',
    # Approval flags stamped on generated analysis.
    'location_analysis_approved', 'site_analysis_approved',
    'location_coordinates_confirmed',
}

# Inside visual_concept slots: the client's prompt/label/caption inputs stay,
# while image URLs and approval markers are dropped.
VISUAL_SLOT_APPROVAL_KEYS = {'imageUrl', 'approvedImageUrl', 'approved',
                             'stated', 'chat', 'status'}


def _remap_copied_value(value, file_id_map):
    """Rewrite project-file ids so a copy references its own file rows."""
    if isinstance(value, str):
        if value in file_id_map:
            return file_id_map[value]
        stripped = value.strip()
        if stripped.startswith('{') or stripped.startswith('['):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError):
                return value
            return json.dumps(_remap_copied_value(decoded, file_id_map), ensure_ascii=False)
        return value
    if isinstance(value, dict):
        return {key: _remap_copied_value(val, file_id_map) for key, val in value.items()}
    if isinstance(value, list):
        return [_remap_copied_value(item, file_id_map) for item in value]
    return value


def _sanitize_visual_concept(concept):
    """Keep the client's concept inputs, drop per-slot image approvals."""
    cleaned = dict(concept)
    slots = cleaned.get('slots')
    if isinstance(slots, dict):
        cleaned['slots'] = {
            slot_id: ({key: val for key, val in slot.items()
                       if key not in VISUAL_SLOT_APPROVAL_KEYS}
                      if isinstance(slot, dict) else slot)
            for slot_id, slot in slots.items()
        }
    for marker in ('stated', 'approved', 'approvedImageUrl'):
        cleaned.pop(marker, None)
    return cleaned


def sanitize_copied_draft_data(data, file_id_map=None):
    """Strip approvals and generated outputs from copied draft_data.

    ``file_id_map`` rewrites references to the source's file rows so the copy
    points at its own copies instead of the originals.
    """
    file_id_map = file_id_map or {}
    cleaned = {}
    for key, value in (data or {}).items():
        if key in DRAFT_COPY_STRIPPED_KEYS:
            continue
        cleaned[key] = _remap_copied_value(value, file_id_map)
    concept = cleaned.get('visual_concept')
    was_string = isinstance(concept, str)
    if was_string:
        try:
            concept = json.loads(concept)
        except (TypeError, ValueError):
            concept = None
    if isinstance(concept, dict):
        concept = _sanitize_visual_concept(concept)
        cleaned['visual_concept'] = json.dumps(concept, ensure_ascii=False) if was_string else concept
    elif 'visual_concept' in cleaned:
        cleaned['visual_concept'] = concept
    return cleaned


def copy_project_draft(tenant_id, source_draft_id, new_title, copied_by, copied_by_name, actor_user_id=None):
    """Copy inputs and attachments under a new mandatory unique name.

    Approvals, section statuses, lifecycle history, audit trail and the ledger
    are never copied: the copy is an independent proposal starting as a draft.
    File rows are re-created for the copy — sharing the same storage path, so
    no bytes are duplicated — and every reference inside the copied data is
    remapped to the new row ids.
    """
    conn = get_db()
    source = get_project_draft_by_id(tenant_id, source_draft_id)
    if not source:
        return {'error': 'draft_not_found'}
    title = str(new_title or '').strip()
    if not title:
        return {'error': 'title_required'}
    normalized = title.lower()
    for row in conn.execute('SELECT title FROM project_drafts WHERE tenant_id = ?', (tenant_id,)).fetchall():
        if str(row['title'] or '').strip().lower() == normalized:
            return {'error': 'title_exists'}
    data = source.get('draft_data') if isinstance(source.get('draft_data'), dict) else {}
    data = json.loads(json.dumps(data, ensure_ascii=False)) if data else {}
    new_draft_id = str(uuid.uuid4())

    file_rows = conn.execute(
        'SELECT * FROM project_files WHERE tenant_id = ? AND draft_id = ?',
        (tenant_id, source_draft_id),
    ).fetchall()
    file_id_map = {file_row['id']: str(uuid.uuid4()) for file_row in file_rows}
    data = sanitize_copied_draft_data(data, file_id_map)

    conn.execute(
        '''INSERT INTO project_drafts
           (id, tenant_id, user_id, title, draft_data, section_statuses, status, revision, data_bytes, has_slides, has_maps)
           VALUES (?, ?, ?, ?, ?, '{}', 'draft', 1, ?, 0, 0)''',
        (new_draft_id, tenant_id, actor_user_id or source.get('user_id'), title,
         json.dumps(data, ensure_ascii=False), len(json.dumps(data, ensure_ascii=False))),
    )
    conn.execute(
        '''INSERT INTO proposal_copies (id, tenant_id, source_draft_id, new_draft_id, new_title, copied_by, copied_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), tenant_id, source_draft_id, new_draft_id, title, copied_by, copied_by_name),
    )
    try:
        for file_row in file_rows:
            conn.execute(
                '''INSERT INTO project_files
                   (id, tenant_id, draft_id, project_id, file_type, original_name, storage_path,
                    mime_type, file_size, sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (file_id_map[file_row['id']], tenant_id, new_draft_id, file_row['project_id'],
                 file_row['file_type'], file_row['original_name'], file_row['storage_path'],
                 file_row['mime_type'], file_row['file_size'], file_row['sha256']),
            )
    except Exception:
        pass
    conn.commit()
    return {
        'draft_id': new_draft_id,
        'title': title,
        'source_draft_id': source_draft_id,
        'copied_fields': len(data),
        'copied_files': len(file_rows),
    }


def list_proposal_copies(tenant_id, limit=50, accessible_ids=None):
    conn = get_db()
    scope_sql = ''
    params = [tenant_id]
    if accessible_ids is not None:
        ids = [str(i) for i in accessible_ids]
        if not ids:
            return []
        placeholders = ','.join('?' * len(ids))
        scope_sql = (' AND (pc.source_draft_id IN (' + placeholders + ')'
                     ' OR pc.new_draft_id IN (' + placeholders + '))')
        params.extend(ids * 2)
    params.append(int(limit))
    rows = conn.execute(
        '''SELECT pc.id, pc.source_draft_id, pc.new_draft_id, pc.new_title, pc.copied_by_name, pc.created_at,
                  d.title AS source_title
           FROM proposal_copies pc LEFT JOIN project_drafts d ON d.id = pc.source_draft_id
           WHERE pc.tenant_id = ?''' + scope_sql + ''' ORDER BY pc.created_at DESC LIMIT ?''',
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def archive_presentation(tenant_id, presentation_id, archived_by, archived_by_name):
    """Archive: inactive with the full record kept; never a delete."""
    conn = get_db()
    row = conn.execute(
        'SELECT id FROM presentations WHERE id = ? AND tenant_id = ?',
        (presentation_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'presentation_not_found'}
    now = _utcnow().isoformat()
    conn.execute(
        "UPDATE presentations SET status = 'archived', archived_at = ?, updated_at = ? WHERE id = ?",
        (now, now, presentation_id),
    )
    conn.commit()
    return {'id': presentation_id, 'status': 'archived', 'archived_by_name': archived_by_name}


def restore_presentation(tenant_id, presentation_id):
    conn = get_db()
    row = conn.execute(
        "SELECT id, draft_id FROM presentations WHERE id = ? AND tenant_id = ? AND status = 'archived'",
        (presentation_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'presentation_not_archived'}
    now = _utcnow().isoformat()
    conn.execute(
        "UPDATE presentations SET status = 'draft', archived_at = NULL, updated_at = ? WHERE id = ?",
        (now, presentation_id),
    )
    conn.commit()
    # A presentation archived through its draft comes back through the draft:
    # transition the linked draft out of 'archived' so both records agree.
    draft_id = row['draft_id'] if 'draft_id' in row.keys() else None
    if draft_id:
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if draft and normalize_proposal_status(draft.get('status')) == 'archived':
            transition_project_draft_status(
                tenant_id, draft_id, 'draft', reason='استعادة من الأرشيف')
    return {'id': presentation_id, 'status': 'draft'}


ARCHIVE_RETENTION_DAYS = int(os.environ.get('ARCHIVE_RETENTION_DAYS', '365'))


def purge_expired_archives(tenant_id=None, retention_days=None):
    """Retention sweep for t18: archived records past the retention window.

    Archiving is the default end-state and a restore always works inside the
    window; only records that outlived the configured retention are removed,
    and only through this explicit admin-run sweep — never a user action.
    """
    days = int(retention_days or ARCHIVE_RETENTION_DAYS)
    cutoff = (_utcnow() - timedelta(days=days)).isoformat()
    conn = get_db()
    clauses = ["status = 'archived'", 'archived_at IS NOT NULL', 'archived_at < ?']
    params = [cutoff]
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    where = ' AND '.join(clauses)
    purged = {'drafts': 0, 'presentations': 0}
    try:
        cursor = conn.execute(f'DELETE FROM presentations WHERE {where}', tuple(params))
        purged['presentations'] = max(0, int(cursor.rowcount or 0))
        cursor = conn.execute(f'DELETE FROM project_drafts WHERE {where}', tuple(params))
        purged['drafts'] = max(0, int(cursor.rowcount or 0))
        conn.commit()
    except Exception:
        conn.rollback()
    return purged


# ── t41/t24/t42: notifications and the approval task center ─────────────────

NOTIFICATION_CATEGORIES = ('section_approval', 'generation_approval', 'final_approval', 'recharge',
                           'billing', 'support', 'task', 'job', 'platform', 'general')


def create_notification(tenant_id, title, body=None, category='general', user_id=None,
                        entity_type=None, entity_id=None, email_to=None):
    conn = get_db()
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
    """Active company admins — the human escalation target per company."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, email FROM users WHERE tenant_id = ? "
            "AND role = 'company_admin' AND COALESCE(is_active, 1) = 1",
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
    request so the same receipt cannot be submitted twice.
    """
    transfer_reference = str(transfer_reference or '').strip() or None
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
    return [dict(row) for row in conn.execute(query, params).fetchall()]


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


# ── t52: contracts and NDAs ─────────────────────────────────────────────────

def create_tenant_contract(tenant_id, title, kind='contract', file_id=None, starts_at=None,
                           expires_at=None, notes=None, created_by=None, created_by_name=None,
                           signature_status='unsigned', retention_until=None):
    if not str(title or '').strip():
        return {'error': 'title_required'}
    if kind not in CONTRACT_KINDS:
        kind = 'contract'
    if signature_status not in CONTRACT_SIGNATURE_STATUSES:
        signature_status = 'unsigned'
    conn = get_db()
    row_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO tenant_contracts
           (id, tenant_id, kind, title, file_id, starts_at, expires_at, notes, status,
            signature_status, version, retention_until, created_by, created_by_name, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 1, ?, ?, ?, ?)''',
        (row_id, tenant_id, kind, str(title).strip(), file_id, starts_at, expires_at, notes,
         signature_status, retention_until, created_by, created_by_name, now),
    )
    conn.execute(
        '''INSERT INTO tenant_contract_versions
           (id, contract_id, tenant_id, version, file_id, signature_status,
            starts_at, expires_at, retention_until, notes, created_by, created_by_name)
           VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), row_id, tenant_id, file_id, signature_status,
         starts_at, expires_at, retention_until, notes, created_by, created_by_name),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM tenant_contracts WHERE id = ?', (row_id,)).fetchone())


def add_contract_version(tenant_id, contract_id, file_id=None, signature_status=None,
                         starts_at=None, expires_at=None, retention_until=None, notes=None,
                         created_by=None, created_by_name=None):
    """Append a new version to a contract and advance the head row (t60-03)."""
    conn = get_db()
    head = conn.execute(
        'SELECT * FROM tenant_contracts WHERE id = ? AND tenant_id = ?',
        (str(contract_id), str(tenant_id)),
    ).fetchone()
    if not head:
        return {'error': 'contract_not_found'}
    head = dict(head)
    next_version = int(head.get('version') or 0) + 1
    signature_status = signature_status if signature_status in CONTRACT_SIGNATURE_STATUSES \
        else (head.get('signature_status') or 'unsigned')
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO tenant_contract_versions
           (id, contract_id, tenant_id, version, file_id, signature_status,
            starts_at, expires_at, retention_until, notes, created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), str(contract_id), str(tenant_id), next_version,
         file_id if file_id is not None else head.get('file_id'), signature_status,
         starts_at if starts_at is not None else head.get('starts_at'),
         expires_at if expires_at is not None else head.get('expires_at'),
         retention_until if retention_until is not None else head.get('retention_until'),
         notes if notes is not None else head.get('notes'), created_by, created_by_name),
    )
    conn.execute(
        '''UPDATE tenant_contracts SET version = ?, file_id = ?, signature_status = ?,
           starts_at = ?, expires_at = ?, retention_until = ?, notes = ?, updated_at = ?
           WHERE id = ?''',
        (next_version,
         file_id if file_id is not None else head.get('file_id'), signature_status,
         starts_at if starts_at is not None else head.get('starts_at'),
         expires_at if expires_at is not None else head.get('expires_at'),
         retention_until if retention_until is not None else head.get('retention_until'),
         notes if notes is not None else head.get('notes'), now, str(contract_id)),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM tenant_contracts WHERE id = ?', (str(contract_id),)).fetchone())


def list_contract_versions(contract_id, tenant_id=None):
    conn = get_db()
    if tenant_id:
        rows = conn.execute(
            'SELECT * FROM tenant_contract_versions WHERE contract_id = ? AND tenant_id = ? ORDER BY version DESC',
            (str(contract_id), str(tenant_id)),
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM tenant_contract_versions WHERE contract_id = ? ORDER BY version DESC',
            (str(contract_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def list_tenant_contracts(tenant_id, include_expired=True):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM tenant_contracts WHERE tenant_id = ? ORDER BY expires_at IS NULL, expires_at',
        (tenant_id,),
    ).fetchall()
    now = _utcnow()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item['is_expired'] = bool(item.get('expires_at')) and datetime.fromisoformat(item['expires_at']) < now
        except (TypeError, ValueError):
            item['is_expired'] = False
        if include_expired or not item['is_expired']:
            result.append(item)
    return result


def enforce_contract_retention(tenant_id=None):
    """d06: apply the retention policy — not just display it.

    Expired contracts get stamped ``retention_until`` (expiry +
    CONTRACT_RETENTION_DAYS, default 365) and flip to 'expired'. A contract
    whose retention window has fully lapsed flips to 'retention_expired' and
    the owning tenant is marked for purge review — the rows are listed so an
    admin acts on them, never silently deleted. Returns the sweep counts.
    """
    conn = get_db()
    now = _utcnow()
    scope = 'AND c.tenant_id = ?' if tenant_id else ''
    params = [str(tenant_id)] if tenant_id else []
    expired = conn.execute(
        """SELECT c.id, c.tenant_id, c.expires_at FROM tenant_contracts c
           WHERE c.status = 'active' AND c.expires_at IS NOT NULL AND c.expires_at < ? """ + scope,
        [now.isoformat()] + params,
    ).fetchall()
    marked = 0
    for row in expired:
        try:
            expiry = datetime.fromisoformat(row['expires_at'])
        except (TypeError, ValueError):
            continue
        retention_until = (expiry + timedelta(days=CONTRACT_RETENTION_DAYS)).isoformat()
        conn.execute(
            """UPDATE tenant_contracts SET status = 'expired',
               retention_until = COALESCE(retention_until, ?), updated_at = ?
               WHERE id = ? AND status = 'active'""",
            (retention_until, now.isoformat(), row['id']),
        )
        marked += 1
    # Lapse after stamping: a contract that expired long ago (retention window
    # already in the past) flips in the same sweep, while one expiring now got
    # a future retention_until and keeps its full window.
    lapsed = conn.execute(
        """SELECT c.id, c.tenant_id FROM tenant_contracts c
           WHERE c.status = 'expired' AND c.retention_until IS NOT NULL
           AND c.retention_until < ? """ + scope,
        [now.isoformat()] + params,
    ).fetchall()
    for row in lapsed:
        conn.execute(
            "UPDATE tenant_contracts SET status = 'retention_expired', updated_at = ? WHERE id = ?",
            (now.isoformat(), row['id']),
        )
    if expired or lapsed:
        conn.commit()
    return {'contracts_expired': marked, 'retention_lapsed': len(lapsed),
            'tenants_pending_review': sorted({row['tenant_id'] for row in lapsed})}


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
        'tickets': monthly_map('support_tickets', bucket=bucket),
    }
    trends = {'labels': labels}
    for key, mmap in series_maps.items():
        trends[key] = [round(mmap.get(k, 0), 2) for k in bucket_keys]

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
        },
        'spend': {
            'month_usd': round(spend_map.get(bucket_keys[-1], 0) + maps_map.get(bucket_keys[-1], 0), 2),
            'total_usd': round(sum(spend_map.values()) + sum(maps_map.values()), 2),
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
    trends = {'labels': labels}
    for key, mmap in series_maps.items():
        trends[key] = [round(mmap.get(k, 0), 2) for k in bucket_keys]
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

    return {
        'overdue_sections': overdue_sections,
        'overdue_count': len(overdue_sections),
        'avg_approval_hours': avg_approval_hours,
        'pending_section_approvals': pending_approvals,
        'spend_by_project': spend_by_project,
        'activity_by_user': spend_by_user,
    }


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
    headers = ['التاريخ', 'الشركة', 'النوع', 'المبلغ USD', 'التكلفة الخام', 'المضاعف',
               'أحداث AI', 'أحداث الخرائط', 'مرجع عدم التكرار', 'ملاحظة']
    body = [[r['created_at'], r['company_name'], r['kind'], r['amount_usd'],
             r['raw_cost_usd'], r['multiplier'], r['ai_events_count'],
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


# ═════════════════════════════════════════════════════════════════════════════
# t20 roles: a tenant may clone the built-in defaults into an editable role
# template. The built-ins themselves stay code-defined (DEFAULT_PERMISSIONS).
# ═════════════════════════════════════════════════════════════════════════════


def _create_omran_role_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS tenant_roles (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        base_role TEXT DEFAULT 'employee',
        permissions_json TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tenant_roles ON tenant_roles(tenant_id, name)')


def _create_identity_tables(conn):
    """Identity and access-control tables (t20/t21/t63/d07)."""
    # t20: a user may be restricted to named project files. Rows here mean
    # "only these drafts"; an empty set means the legacy unrestricted access.
    conn.execute('''CREATE TABLE IF NOT EXISTS user_project_scopes (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        draft_id TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_user_project_scopes ON user_project_scopes(user_id, draft_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_user_project_scopes_tenant ON user_project_scopes(tenant_id, user_id)')

    # t63: one-time recovery codes for the second factor, stored hashed.
    conn.execute('''CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
        code_hash TEXT NOT NULL,
        used_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_mfa_recovery ON mfa_recovery_codes(tenant_id, user_id, used_at)')

    # d07: a platform admin may read client content only through an explicit,
    # reasoned, time-boxed grant the client's company admin approved.
    conn.execute('''CREATE TABLE IF NOT EXISTS admin_access_requests (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        admin_tenant_id TEXT,
        scope TEXT NOT NULL DEFAULT 'tenant',
        target_id TEXT,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_by_name TEXT,
        decided_by TEXT,
        decided_by_name TEXT,
        decision_note TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        decided_at TEXT,
        expires_at TEXT,
        access_count INTEGER NOT NULL DEFAULT 0,
        first_accessed_at TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_admin_access_tenant ON admin_access_requests(tenant_id, status, created_at DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_admin_access_admin ON admin_access_requests(admin_tenant_id, status)')


def list_tenant_role_templates(tenant_id):
    """Return every grantable permission with default state for a new template."""
    conn = get_db()
    employee_defaults = DEFAULT_PERMISSIONS.get('employee', {})
    keys = []
    for key in PERMISSION_KEYS:
        keys.append({'key': key, 'default_granted': bool(employee_defaults.get(key, False))})
    custom = conn.execute(
        'SELECT id, name, base_role, permissions_json, created_at, updated_at '
        'FROM tenant_roles WHERE tenant_id = ? ORDER BY created_at', (tenant_id,)
    ).fetchall()
    return {
        'permission_keys': keys,
        'roles': [dict(r) for r in custom],
    }


def create_tenant_role(tenant_id, name, base_role, permissions):
    conn = get_db()
    if not name or not str(name).strip():
        return {'error': 'name_required'}
    clean = {k: bool(v) for k, v in (permissions or {}).items() if k in PERMISSION_KEYS}
    role_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    existing = conn.execute(
        'SELECT id FROM tenant_roles WHERE tenant_id = ? AND name = ?',
        (tenant_id, str(name).strip())
    ).fetchone()
    if existing:
        return {'error': 'role_name_exists'}
    try:
        conn.execute(
            '''INSERT INTO tenant_roles (id, tenant_id, name, base_role, permissions_json,
               created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (role_id, tenant_id, str(name).strip(), base_role if base_role in DEFAULT_PERMISSIONS else 'employee',
             json.dumps(clean), now, now)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return {'error': 'role_name_exists'}
    return get_tenant_role(tenant_id, role_id)


def get_tenant_role(tenant_id, role_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_roles WHERE id = ? AND tenant_id = ?', (role_id, tenant_id)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result['permissions'] = json.loads(result.pop('permissions_json') or '{}')
    except (ValueError, TypeError):
        result['permissions'] = {}
    return result


def update_tenant_role(tenant_id, role_id, name=None, permissions=None):
    conn = get_db()
    role = conn.execute(
        'SELECT id FROM tenant_roles WHERE id = ? AND tenant_id = ?', (role_id, tenant_id)
    ).fetchone()
    if not role:
        return None
    if name is not None:
        if not str(name).strip():
            return {'error': 'name_required'}
        conn.execute('UPDATE tenant_roles SET name = ?, updated_at = ? WHERE id = ?',
                     (str(name).strip(), _utcnow().isoformat(), role_id))
    if permissions is not None:
        clean = {k: bool(v) for k, v in permissions.items() if k in PERMISSION_KEYS}
        conn.execute('UPDATE tenant_roles SET permissions_json = ?, updated_at = ? WHERE id = ?',
                     (json.dumps(clean), _utcnow().isoformat(), role_id))
    conn.commit()
    return get_tenant_role(tenant_id, role_id)


def delete_tenant_role(tenant_id, role_id):
    conn = get_db()
    cursor = conn.execute('DELETE FROM tenant_roles WHERE id = ? AND tenant_id = ?', (role_id, tenant_id))
    conn.commit()
    return cursor.rowcount > 0


def assign_tenant_role_to_user(tenant_id, user_id, role_id):
    """Clone the template onto the user's per-key permission overrides."""
    role = get_tenant_role(tenant_id, role_id)
    if not role:
        return None
    for key in PERMISSION_KEYS:
        if key in role['permissions']:
            set_user_permission(user_id, key, role['permissions'][key])
    return get_user_permissions(user_id)


def separation_of_duties_matrix(tenant_id):
    """t21: flag self-approvals and decisions without a mandatory reason."""
    conn = get_db()
    matrix = {'tenant_id': tenant_id, 'self_approvals': [], 'missing_reason_decisions': []}
    rows = conn.execute(
        'SELECT * FROM section_versions WHERE tenant_id = ? AND decided_at IS NOT NULL',
        (tenant_id,)
    ).fetchall()
    for row in rows:
        item = dict(row)
        if item.get('decided_by') and item.get('created_by') == item.get('decided_by'):
            matrix['self_approvals'].append({
                'kind': 'section_version', 'entity_id': item['id'],
                'draft_id': item.get('draft_id'), 'section_key': item.get('section_key'),
                'version_number': item.get('version_number'),
                'sent_by': item.get('created_by'), 'decided_by': item.get('decided_by'),
                'decision': item.get('status'), 'decided_at': item.get('decided_at'),
            })
        # A reason is mandatory for return/reject; approval may stand without one.
        if item.get('status') in ('returned', 'rejected') and not item.get('decision_note'):
            matrix['missing_reason_decisions'].append({
                'kind': 'section_version', 'entity_id': item['id'],
                'decision': item.get('status'), 'decided_by': item.get('decided_by'),
                'decided_at': item.get('decided_at'),
            })
    try:
        drafts = conn.execute(
            'SELECT id, title, requested_by, requested_by_name, reviewed_by, reviewed_by_name,'
            ' review_note, status, reviewed_at FROM project_drafts'
            ' WHERE tenant_id = ? AND reviewed_at IS NOT NULL',
            (tenant_id,)
        ).fetchall()
        for row in drafts:
            item = dict(row)
            if item.get('reviewed_by') and item.get('requested_by') == item.get('reviewed_by'):
                matrix['self_approvals'].append({
                    'kind': 'overall_draft', 'entity_id': item['id'],
                    'requested_by': item.get('requested_by_name'), 'decided_by': item.get('reviewed_by_name'),
                    'decision': item.get('status'), 'decided_at': item.get('reviewed_at'),
                })
            if item.get('status') in ('rejected', 'returned') and not item.get('review_note'):
                matrix['missing_reason_decisions'].append({
                    'kind': 'overall_draft', 'entity_id': item['id'],
                    'decision': item.get('status'), 'decided_by': item.get('reviewed_by'),
                    'decided_at': item.get('reviewed_at'),
                })
    except sqlite3.OperationalError:
        pass
    for table, kind, name_col in (
            ('generation_approvals', 'generation_approval', 'draft_id'),
            ('final_file_approvals', 'final_file_approval', 'presentation_id')):
        try:
            rows = conn.execute(
                f'SELECT id, {name_col} AS ref_id, requested_by, requested_by_name, decided_by,'
                f' decided_by_name, decided_at, status, decision_note FROM {table}'
                ' WHERE tenant_id = ? AND decided_at IS NOT NULL',
                (tenant_id,)
            ).fetchall()
            for row in rows:
                item = dict(row)
                if item.get('decided_by') and item.get('requested_by') == item.get('decided_by'):
                    matrix['self_approvals'].append({
                        'kind': kind, 'entity_id': item['id'], 'ref_id': item.get('ref_id'),
                        'sent_by': item.get('requested_by'), 'decided_by': item.get('decided_by'),
                        'decided_by_name': item.get('decided_by_name'),
                        'decision': item.get('status'), 'decided_at': item.get('decided_at'),
                    })
                if item.get('status') == 'rejected' and not item.get('decision_note'):
                    matrix['missing_reason_decisions'].append({
                        'kind': kind, 'entity_id': item['id'],
                        'decision': item.get('status'), 'decided_by': item.get('decided_by'),
                        'decided_at': item.get('decided_at'),
                    })
        except sqlite3.OperationalError:
            pass

    # t23: one person may not hold both gates of the same file unless they are
    # a company administrator (d02's decided exception).
    matrix['cross_gate_approvals'] = []
    try:
        rows = conn.execute(
            '''SELECT ga.draft_id, ga.presentation_id AS ga_pres, fa.presentation_id,
                      ga.decided_by AS gen_by, ga.decided_by_name AS gen_by_name,
                      fa.decided_by AS file_by, fa.decided_by_name AS file_by_name,
                      fa.decided_at
               FROM generation_approvals ga
               JOIN final_file_approvals fa
                 ON fa.tenant_id = ga.tenant_id
                AND (fa.presentation_id = ga.presentation_id
                     OR fa.presentation_id IN (
                        SELECT id FROM presentations WHERE tenant_id = ga.tenant_id AND draft_id = ga.draft_id))
               WHERE ga.tenant_id = ? AND ga.status = 'approved' AND fa.status = 'approved'
                 AND ga.decided_by IS NOT NULL AND ga.decided_by = fa.decided_by''',
            (tenant_id,)
        ).fetchall()
        admin_ids = {
            r[0] for r in conn.execute(
                "SELECT id FROM users WHERE tenant_id = ? AND role = 'company_admin'", (tenant_id,)
            ).fetchall()
        }
        for row in rows:
            item = dict(row)
            if item['gen_by'] in admin_ids:
                continue
            matrix['cross_gate_approvals'].append({
                'kind': 'generation_plus_final_file', 'presentation_id': item['presentation_id'],
                'decided_by': item['gen_by'], 'decided_by_name': item['gen_by_name'],
                'decided_at': item['decided_at'],
            })
    except sqlite3.OperationalError:
        pass

    # t23: the final-file approver should not be the last editor of that file.
    matrix['last_editor_conflicts'] = []
    try:
        rows = conn.execute(
            '''SELECT fa.id, fa.presentation_id, fa.decided_by, fa.decided_by_name, fa.decided_at,
                      (SELECT cl.user_id FROM change_log cl
                        WHERE cl.tenant_id = fa.tenant_id AND cl.target_type = 'presentation'
                          AND cl.target_id = fa.presentation_id
                        ORDER BY cl.created_at DESC LIMIT 1) AS last_editor_id,
                      (SELECT cl.user_name FROM change_log cl
                        WHERE cl.tenant_id = fa.tenant_id AND cl.target_type = 'presentation'
                          AND cl.target_id = fa.presentation_id
                        ORDER BY cl.created_at DESC LIMIT 1) AS last_editor_name
               FROM final_file_approvals fa
               WHERE fa.tenant_id = ? AND fa.status = 'approved' AND fa.decided_by IS NOT NULL''',
            (tenant_id,)
        ).fetchall()
        for row in rows:
            item = dict(row)
            if item.get('last_editor_id') and item['last_editor_id'] == item['decided_by']:
                matrix['last_editor_conflicts'].append({
                    'kind': 'final_file_approver_is_last_editor',
                    'entity_id': item['id'], 'presentation_id': item['presentation_id'],
                    'decided_by': item['decided_by'], 'decided_by_name': item['decided_by_name'],
                    'last_editor_name': item['last_editor_name'], 'decided_at': item['decided_at'],
                })
    except sqlite3.OperationalError:
        pass

    # t23: edits made after the final approval by a user without the sensitive
    # post_approval_edit permission are a separation-of-duties violation.
    matrix['post_approval_edits'] = []
    try:
        rows = conn.execute(
            '''SELECT cl.id, cl.target_type, cl.target_id, cl.user_id, cl.user_name,
                      cl.action, cl.created_at
               FROM change_log cl
               JOIN final_file_approvals fa
                 ON fa.tenant_id = cl.tenant_id
                AND ((cl.target_type = 'presentation' AND cl.target_id = fa.presentation_id)
                     OR (cl.target_type = 'draft' AND cl.target_id IN (
                        SELECT draft_id FROM presentations
                        WHERE tenant_id = fa.tenant_id AND id = fa.presentation_id)))
               WHERE cl.tenant_id = ? AND fa.status = 'approved'
                 AND cl.created_at > fa.decided_at AND cl.user_id IS NOT NULL''',
            (tenant_id,)
        ).fetchall()
        for row in rows:
            item = dict(row)
            holder = conn.execute('SELECT role FROM users WHERE id = ?', (item['user_id'],)).fetchone()
            if holder and holder['role'] == 'company_admin':
                continue
            if get_user_permissions(item['user_id']).get('post_approval_edit'):
                continue
            matrix['post_approval_edits'].append({
                'kind': 'edit_after_final_approval', 'entity_id': item['id'],
                'target_type': item['target_type'], 'target_id': item['target_id'],
                'user_id': item['user_id'], 'user_name': item['user_name'],
                'action': item['action'], 'created_at': item['created_at'],
            })
    except sqlite3.OperationalError:
        pass

    # t23: wallet top-ups must come from the platform admin recharge path; a
    # credit recorded by a client-side actor breaks the rule.
    matrix['client_side_topups'] = []
    try:
        rows = conn.execute(
            '''SELECT id, amount_usd, note, actor, created_at FROM tenant_ledger
               WHERE tenant_id = ? AND kind = 'credit' AND COALESCE(actor, '') NOT IN
                     ('platform_admin', 'recharge_decision', 'system')''',
            (tenant_id,)
        ).fetchall()
        for row in rows:
            item = dict(row)
            matrix['client_side_topups'].append({
                'kind': 'client_side_topup', 'entity_id': item['id'],
                'amount_usd': item['amount_usd'], 'actor': item['actor'],
                'note': item['note'], 'created_at': item['created_at'],
            })
    except sqlite3.OperationalError:
        pass

    matrix['self_approvals_count'] = len(matrix['self_approvals'])
    matrix['missing_reason_count'] = len(matrix['missing_reason_decisions'])
    matrix['cross_gate_count'] = len(matrix['cross_gate_approvals'])
    matrix['last_editor_conflicts_count'] = len(matrix['last_editor_conflicts'])
    matrix['post_approval_edits_count'] = len(matrix['post_approval_edits'])
    matrix['client_side_topups_count'] = len(matrix['client_side_topups'])
    matrix['policies'] = get_tenant_policies(tenant_id)
    return matrix


# ═════════════════════════════════════════════════════════════════════════════
# Identity & access-control helpers (t20/t21/t23/t63/d01/d07)
# ═════════════════════════════════════════════════════════════════════════════

TENANT_POLICY_DEFAULTS = {
    # d01: whether the section editor may decide a version they sent.
    # 'allow' records it with a self-approval audit note, 'warn' allows it and
    # flags it in the matrix, 'block' refuses the decision outright.
    'section_self_approval': 'allow',
    # d02 relaxed: whether a requester may approve their own generation
    # request. 'block' keeps the mandatory separation — only approvers and
    # company admins decide; 'allow' lets the requester pass their own gate
    # (the request is still priced and the points still reserved).
    'generation_self_approval': 'block',
}
TENANT_POLICY_VALUES = {
    'section_self_approval': ('allow', 'warn', 'block'),
    'generation_self_approval': ('allow', 'block'),
}


def get_tenant_policies(tenant_id):
    """All tenant policy settings, with defaults filled in."""
    conn = get_db()
    row = conn.execute('SELECT settings_json FROM tenants WHERE id = ?', (tenant_id,)).fetchone()
    stored = _json_or(row['settings_json'], {}) if row else {}
    if not isinstance(stored, dict):
        stored = {}
    policies = dict(TENANT_POLICY_DEFAULTS)
    for key in TENANT_POLICY_DEFAULTS:
        value = stored.get(key)
        if value in TENANT_POLICY_VALUES.get(key, ()):
            policies[key] = value
    return policies


def get_tenant_policy(tenant_id, key, default=None):
    return get_tenant_policies(tenant_id).get(key, default)


def set_tenant_policies(tenant_id, updates):
    """Update policy keys inside tenants.settings_json; rejects bad values."""
    clean = {}
    for key, value in (updates or {}).items():
        if key not in TENANT_POLICY_DEFAULTS:
            continue
        if value not in TENANT_POLICY_VALUES[key]:
            return {'error': 'invalid_policy_value', 'key': key}
        clean[key] = value
    if not clean:
        return {'error': 'no_policy_updates'}
    conn = get_db()
    row = conn.execute('SELECT settings_json FROM tenants WHERE id = ?', (tenant_id,)).fetchone()
    if not row:
        return {'error': 'tenant_not_found'}
    settings = _json_or(row['settings_json'], {})
    if not isinstance(settings, dict):
        settings = {}
    settings.update(clean)
    conn.execute('UPDATE tenants SET settings_json = ? WHERE id = ?',
                 (json.dumps(settings, ensure_ascii=False), tenant_id))
    conn.commit()
    return get_tenant_policies(tenant_id)


def is_last_active_company_admin(tenant_id, user_id):
    """True when removing/disabling this user would leave no active company admin."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE tenant_id = ? AND role = 'company_admin' "
        'AND is_active = 1 AND id != ?',
        (tenant_id, user_id),
    ).fetchone()
    target = conn.execute(
        "SELECT role, is_active FROM users WHERE id = ? AND tenant_id = ?", (user_id, tenant_id)
    ).fetchone()
    if not target or target['role'] != 'company_admin':
        return False
    return int(row['n'] or 0) == 0


# ── t20: per-user project scope ──────────────────────────────────────────────

def get_user_project_scope_ids(user_id):
    """Draft ids the user is restricted to; empty set means unrestricted."""
    conn = get_db()
    rows = conn.execute(
        'SELECT draft_id FROM user_project_scopes WHERE user_id = ?', (user_id,)
    ).fetchall()
    return {r['draft_id'] for r in rows}


def user_project_scope_limited(user_id):
    if not user_id:
        return False
    conn = get_db()
    row = conn.execute(
        'SELECT 1 FROM user_project_scopes WHERE user_id = ? LIMIT 1', (user_id,)
    ).fetchone()
    return bool(row)


def user_accessible_draft_ids(user_id, tenant_id):
    """t20: draft ids a project-scoped user may touch — their scope plus their
    own files. ``None`` when the user carries no scope rows (the legacy
    unrestricted access) or has no user id (tenant-direct logins)."""
    if not user_id:
        return None
    conn = get_db()
    scope = {row['draft_id'] for row in conn.execute(
        'SELECT draft_id FROM user_project_scopes WHERE user_id = ? AND tenant_id = ?',
        (user_id, tenant_id)).fetchall()}
    if not scope:
        return None
    own = {row['id'] for row in conn.execute(
        'SELECT id FROM project_drafts WHERE tenant_id = ? AND user_id = ?',
        (tenant_id, user_id)).fetchall()}
    return scope | own


def user_may_access_draft(user_id, draft):
    """t20: scoped users act only on their listed drafts, plus drafts they own.

    An actor with no scope rows keeps the legacy unrestricted access, and the
    draft's owner always keeps access to their own file.
    """
    if not user_id or not draft:
        return True
    if draft.get('user_id') and str(draft['user_id']) == str(user_id):
        return True
    scope = get_user_project_scope_ids(user_id)
    if not scope:
        return True
    return draft.get('id') in scope


def set_user_project_scope(tenant_id, user_id, draft_ids):
    """Replace the user's draft scope; an empty list lifts the restriction."""
    conn = get_db()
    user = conn.execute(
        'SELECT id FROM users WHERE id = ? AND tenant_id = ?', (user_id, tenant_id)
    ).fetchone()
    if not user:
        return {'error': 'user_not_found'}
    valid = {
        r['id'] for r in conn.execute(
            'SELECT id FROM project_drafts WHERE tenant_id = ?', (tenant_id,)
        ).fetchall()
    }
    wanted = [d for d in (draft_ids or []) if d in valid]
    try:
        conn.execute('DELETE FROM user_project_scopes WHERE user_id = ?', (user_id,))
        for draft_id in wanted:
            conn.execute(
                'INSERT INTO user_project_scopes (id, tenant_id, user_id, draft_id) VALUES (?, ?, ?, ?)',
                (str(uuid.uuid4()), tenant_id, user_id, draft_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {'scope': sorted(wanted), 'limited': bool(wanted)}


# ── t21/t63: two-factor state (TOTP + one-time recovery codes) ──────────────

def get_mfa_state(scope, row_id):
    """{enabled, has_secret} for a 'user' or 'tenant' login identity."""
    if scope not in ('user', 'tenant') or not row_id:
        return {'enabled': False}
    conn = get_db()
    table = 'users' if scope == 'user' else 'tenants'
    row = conn.execute(
        f'SELECT mfa_enabled, mfa_secret, mfa_pending_secret FROM {table} WHERE id = ?',
        (row_id,),
    ).fetchone()
    if not row:
        return {'enabled': False}
    return {
        'enabled': bool(row['mfa_enabled']),
        'has_secret': bool(row['mfa_secret']),
        'pending': bool(row['mfa_pending_secret']),
    }


def get_mfa_secrets(scope, row_id):
    """Internal: the active and pending TOTP secrets for verification."""
    conn = get_db()
    table = 'users' if scope == 'user' else 'tenants'
    row = conn.execute(
        f'SELECT mfa_enabled, mfa_secret, mfa_pending_secret FROM {table} WHERE id = ?',
        (row_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def set_mfa_pending_secret(scope, row_id, secret):
    conn = get_db()
    table = 'users' if scope == 'user' else 'tenants'
    conn.execute(f'UPDATE {table} SET mfa_pending_secret = ? WHERE id = ?', (secret, row_id))
    conn.commit()


def activate_mfa(scope, row_id):
    """Move the verified pending secret into place and flag MFA on."""
    conn = get_db()
    table = 'users' if scope == 'user' else 'tenants'
    row = conn.execute(
        f'SELECT mfa_pending_secret FROM {table} WHERE id = ?', (row_id,)
    ).fetchone()
    if not row or not row['mfa_pending_secret']:
        return False
    conn.execute(
        f'UPDATE {table} SET mfa_secret = mfa_pending_secret, mfa_pending_secret = NULL,'
        ' mfa_enabled = 1 WHERE id = ?',
        (row_id,),
    )
    conn.commit()
    return True


def clear_mfa(scope, row_id):
    conn = get_db()
    table = 'users' if scope == 'user' else 'tenants'
    conn.execute(
        f'UPDATE {table} SET mfa_secret = NULL, mfa_pending_secret = NULL, mfa_enabled = 0'
        ' WHERE id = ?',
        (row_id,),
    )
    if scope == 'user':
        conn.execute('DELETE FROM mfa_recovery_codes WHERE user_id = ?', (row_id,))
    else:
        conn.execute('DELETE FROM mfa_recovery_codes WHERE tenant_id = ? AND user_id IS NULL', (row_id,))
    conn.commit()


def store_recovery_codes(tenant_id, user_id, codes):
    """Replace the recovery set with freshly generated codes (stored hashed)."""
    import hashlib as _hashlib
    conn = get_db()
    if user_id:
        conn.execute('DELETE FROM mfa_recovery_codes WHERE user_id = ?', (user_id,))
    else:
        conn.execute('DELETE FROM mfa_recovery_codes WHERE tenant_id = ? AND user_id IS NULL', (tenant_id,))
    for code in codes:
        conn.execute(
            'INSERT INTO mfa_recovery_codes (id, tenant_id, user_id, code_hash) VALUES (?, ?, ?, ?)',
            (str(uuid.uuid4()), tenant_id, user_id,
             _hashlib.sha256(str(code).encode('utf-8')).hexdigest()),
        )
    conn.commit()


def consume_recovery_code(tenant_id, user_id, code):
    """Mark a matching unused recovery code as spent. True when it matched."""
    import hashlib as _hashlib
    digest = _hashlib.sha256(str(code or '').strip().encode('utf-8')).hexdigest()
    conn = get_db()
    if user_id:
        row = conn.execute(
            'SELECT id FROM mfa_recovery_codes WHERE user_id = ? AND code_hash = ? AND used_at IS NULL',
            (user_id, digest),
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT id FROM mfa_recovery_codes WHERE tenant_id = ? AND user_id IS NULL'
            ' AND code_hash = ? AND used_at IS NULL',
            (tenant_id, digest),
        ).fetchone()
    if not row:
        return False
    conn.execute(
        'UPDATE mfa_recovery_codes SET used_at = ? WHERE id = ?',
        (_utcnow().isoformat(), row['id']),
    )
    conn.commit()
    return True


def count_unused_recovery_codes(tenant_id, user_id):
    conn = get_db()
    if user_id:
        row = conn.execute(
            'SELECT COUNT(*) AS n FROM mfa_recovery_codes WHERE user_id = ? AND used_at IS NULL',
            (user_id,),
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT COUNT(*) AS n FROM mfa_recovery_codes WHERE tenant_id = ? AND user_id IS NULL AND used_at IS NULL',
            (tenant_id,),
        ).fetchone()
    return int(row['n'] or 0)


# ── d07: exceptional admin access to client content ─────────────────────────

ADMIN_ACCESS_SCOPES = ('tenant', 'presentation', 'file')
ADMIN_ACCESS_STATUSES = ('pending', 'approved', 'denied', 'revoked', 'expired')


def create_admin_access_request(admin_tenant_id, tenant_id, scope, target_id,
                                reason, hours, requested_by_name):
    """A platform admin asks the client for time-boxed read access (d07)."""
    reason = str(reason or '').strip()
    if not reason:
        return {'error': 'reason_required'}
    if scope not in ADMIN_ACCESS_SCOPES:
        return {'error': 'invalid_scope'}
    conn = get_db()
    if not conn.execute('SELECT id FROM tenants WHERE id = ?', (tenant_id,)).fetchone():
        return {'error': 'tenant_not_found'}
    request_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO admin_access_requests
           (id, tenant_id, admin_tenant_id, scope, target_id, reason, requested_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (request_id, tenant_id, admin_tenant_id, scope, target_id or None,
         reason, requested_by_name),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM admin_access_requests WHERE id = ?', (request_id,)
    ).fetchone())


def get_admin_access_request(request_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM admin_access_requests WHERE id = ?', (request_id,)
    ).fetchone()
    return dict(row) if row else None


def list_admin_access_requests(tenant_id=None, admin_tenant_id=None, status=None, limit=100):
    conn = get_db()
    expire_admin_access_requests()
    clauses, params = [], []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(tenant_id)
    if admin_tenant_id:
        clauses.append('admin_tenant_id = ?')
        params.append(admin_tenant_id)
    if status:
        clauses.append('status = ?')
        params.append(status)
    query = 'SELECT * FROM admin_access_requests'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def expire_admin_access_requests():
    """Approved grants past their expiry close themselves."""
    conn = get_db()
    conn.execute(
        "UPDATE admin_access_requests SET status = 'expired' "
        "WHERE status = 'approved' AND expires_at IS NOT NULL AND expires_at < ?",
        (_utcnow().isoformat(),),
    )
    conn.commit()


def decide_admin_access_request(request_id, tenant_id, decision, decided_by,
                                decided_by_name, note=None, hours=None):
    """The client's company admin approves or denies an access request (d07).

    An approval opens a grant that expires after ``hours`` (default 24, max 72).
    """
    if decision not in ('approved', 'denied'):
        return {'error': 'invalid_decision'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM admin_access_requests WHERE id = ? AND tenant_id = ?',
        (request_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'request_not_found'}
    if row['status'] != 'pending':
        return {'error': 'request_not_pending'}
    from datetime import timedelta
    now = _utcnow()
    expires_at = None
    if decision == 'approved':
        grant_hours = max(1, min(int(hours or 24), 72))
        expires_at = (now + timedelta(hours=grant_hours)).isoformat()
    conn.execute(
        '''UPDATE admin_access_requests SET status = ?, decided_by = ?, decided_by_name = ?,
           decision_note = ?, decided_at = ?, expires_at = ? WHERE id = ?''',
        (decision, decided_by, decided_by_name, str(note or '').strip() or None,
         now.isoformat(), expires_at, request_id),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM admin_access_requests WHERE id = ?', (request_id,)
    ).fetchone())


def revoke_admin_access_request(request_id, tenant_id, revoked_by_name):
    """The client closes an active grant early."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM admin_access_requests WHERE id = ? AND tenant_id = ?',
        (request_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'request_not_found'}
    if row['status'] != 'approved':
        return {'error': 'request_not_active'}
    conn.execute(
        "UPDATE admin_access_requests SET status = 'revoked', decided_at = ?, "
        'decision_note = COALESCE(decision_note, \'\') || ? WHERE id = ?',
        (_utcnow().isoformat(), f' [revoked by {revoked_by_name}]', request_id),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM admin_access_requests WHERE id = ?', (request_id,)
    ).fetchone())


def active_admin_access_grant(tenant_id, scope=None, target_id=None):
    """The broadest still-valid grant covering (scope, target_id), if any.

    A 'tenant' grant covers every scope; a scoped grant covers only its target.
    """
    conn = get_db()
    expire_admin_access_requests()
    now = _utcnow().isoformat()
    rows = conn.execute(
        "SELECT * FROM admin_access_requests WHERE tenant_id = ? AND status = 'approved' "
        'AND expires_at IS NOT NULL AND expires_at > ? ORDER BY decided_at DESC',
        (tenant_id, now),
    ).fetchall()
    for row in rows:
        grant = dict(row)
        if grant['scope'] == 'tenant':
            return grant
        if scope and grant['scope'] == scope and (not grant['target_id'] or grant['target_id'] == target_id):
            return grant
    return None


def mark_admin_access_used(grant_id):
    conn = get_db()
    conn.execute(
        '''UPDATE admin_access_requests SET access_count = access_count + 1,
           first_accessed_at = COALESCE(first_accessed_at, ?) WHERE id = ?''',
        (_utcnow().isoformat(), grant_id),
    )
    conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# t40: event tasks — one-off or recurring checklist items attached to
# presentations, drafts or events, assignable to a user with a due date.
# ═════════════════════════════════════════════════════════════════════════════


def _create_omran_event_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS event_tasks (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        description TEXT,
        event_date TEXT,
        due_at TEXT,
        assignee_user_id TEXT,
        entity_type TEXT,
        entity_id TEXT,
        priority TEXT DEFAULT 'normal',
        escalated_at TEXT,
        reminded_at TEXT,
        recurrence TEXT DEFAULT 'none',
        status TEXT DEFAULT 'open',
        completed_at TEXT,
        completed_by_name TEXT,
        created_by TEXT,
        created_by_name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_event_tasks ON event_tasks(tenant_id, status, due_at)')


EVENT_TASK_PRIORITIES = ('low', 'normal', 'high', 'urgent')


def create_event_task(tenant_id, title, description=None, event_date=None, due_at=None,
                      assignee_user_id=None, recurrence='none', created_by=None, created_by_name=None,
                      entity_type=None, entity_id=None, priority='normal'):
    if not title or not str(title).strip():
        return {'error': 'title_required'}
    if recurrence not in ('none', 'daily', 'weekly', 'monthly'):
        return {'error': 'invalid_recurrence'}
    if priority not in EVENT_TASK_PRIORITIES:
        priority = 'normal'
    conn = get_db()
    task_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO event_tasks (id, tenant_id, title, description, event_date, due_at,
           assignee_user_id, entity_type, entity_id, priority, recurrence, created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (task_id, tenant_id, str(title).strip(), description, event_date, due_at,
         assignee_user_id, entity_type, entity_id, priority, recurrence, created_by, created_by_name)
    )
    conn.commit()
    return get_event_task(tenant_id, task_id)


def get_event_task(tenant_id, task_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM event_tasks WHERE id = ? AND tenant_id = ?', (task_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


def list_event_tasks(tenant_id, status=None, assignee_user_id=None, limit=100, own_actor_id=None):
    conn = get_db()
    query = 'SELECT * FROM event_tasks WHERE tenant_id = ?'
    params = [tenant_id]
    if status:
        query += ' AND status = ?'
        params.append(status)
    if assignee_user_id:
        query += ' AND assignee_user_id = ?'
        params.append(assignee_user_id)
    if own_actor_id:
        query += ' AND (assignee_user_id = ? OR created_by = ?)'
        params.extend([own_actor_id, own_actor_id])
    query += ' ORDER BY COALESCE(due_at, event_date, created_at) LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def update_event_task_status(tenant_id, task_id, new_status, actor_name=None):
    if new_status not in ('open', 'completed', 'cancelled'):
        return {'error': 'invalid_status'}
    conn = get_db()
    existing = conn.execute(
        'SELECT id, recurrence FROM event_tasks WHERE id = ? AND tenant_id = ?', (task_id, tenant_id)
    ).fetchone()
    if not existing:
        return None
    now = _utcnow().isoformat()
    conn.execute(
        'UPDATE event_tasks SET status = ?, completed_at = ?, completed_by_name = ? WHERE id = ?',
        (new_status, now if new_status == 'completed' else None, actor_name if new_status == 'completed' else None, task_id)
    )
    # Recurring tasks reopen themselves with the next due date pushed forward.
    if new_status == 'completed' and existing['recurrence'] and existing['recurrence'] != 'none':
        from datetime import timedelta
        base = _utcnow()
        step = {'daily': timedelta(days=1), 'weekly': timedelta(weeks=1), 'monthly': timedelta(days=30)}[existing['recurrence']]
        conn.execute(
            '''INSERT INTO event_tasks (id, tenant_id, title, description, event_date, due_at,
               assignee_user_id, recurrence, created_by, created_by_name)
               SELECT ?, tenant_id, title, description, event_date, ?, assignee_user_id, recurrence,
               created_by, created_by_name FROM event_tasks WHERE id = ?''',
            (str(uuid.uuid4()), (base + step).isoformat(), task_id)
        )
    conn.commit()
    return get_event_task(tenant_id, task_id)


def _omran_ready():
    """True once the t14+ Omran tables exist in the current database."""
    conn = get_db()
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_approvals'"
    ).fetchall()}
    return 'generation_approvals' in names and 'final_file_approvals' in names


# ═════════════════════════════════════════════════════════════════════════════
# t51: explicit company slug — unique, reserved-word safe, stable after launch
# ═════════════════════════════════════════════════════════════════════════════

# Slugs that collide with platform routes or are unsafe as tenant addresses.
RESERVED_SLUGS = frozenset({
    'api', 'admin', 'app', 'assets', 'auth', 'billing', 'c', 'dashboard',
    'docs', 'download', 'downloads', 'exports', 'files', 'fonts', 'healthz',
    'index', 'landloom', 'login', 'logout', 'mail', 'manafe', 'maps', 'null',
    'omran', 'outputs', 'platform', 'preview', 'register', 'root', 'sag',
    'settings', 'static', 'support', 'system', 'tenant-assets', 'undefined',
    'uploads', 'www',
})


def validate_company_slug(slug, exclude_tenant_id=None):
    """Normalize and validate a company slug.

    Returns ``{'slug': value}`` or ``{'error': code}`` where code is one of
    ``invalid``, ``reserved`` or ``taken``. The check is case-insensitive and
    the stored value is always lowercase.
    """
    normalized = _normalize_slug(slug)
    if not normalized:
        return {'error': 'invalid'}
    if len(normalized) < 3:
        return {'error': 'invalid'}
    if normalized in RESERVED_SLUGS:
        return {'error': 'reserved'}
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM tenants WHERE LOWER(slug) = ? OR LOWER(subdomain) = ? "
        "OR LOWER(REPLACE(REPLACE(COALESCE(username, ''), '_', '-'), '.', '-')) = ?",
        (normalized, normalized, normalized),
    ).fetchone()
    if row and str(row['id']) != str(exclude_tenant_id or ''):
        return {'error': 'taken'}
    redirect = conn.execute(
        'SELECT tenant_id FROM tenant_slug_redirects WHERE old_slug = ?',
        (normalized,),
    ).fetchone()
    if redirect and str(redirect['tenant_id']) != str(exclude_tenant_id or ''):
        return {'error': 'taken'}
    return {'slug': normalized}


def set_tenant_slug(tenant_id, slug, actor_id=None, actor_name=None,
                    allow_after_activation=False, create_redirect=True):
    """Set the explicit company slug.

    Once the company is active the slug is locked: a change is refused unless
    ``allow_after_activation`` is passed, and every change after activation
    leaves a permanent redirect row so old links keep resolving.
    """
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return {'error': 'tenant_not_found'}
    verdict = validate_company_slug(slug, exclude_tenant_id=tenant_id)
    if 'error' in verdict:
        return verdict
    new_slug = verdict['slug']
    old_slug = tenant.get('slug') or tenant_slug(tenant)
    if old_slug == new_slug:
        return {'slug': new_slug, 'unchanged': True, 'tenant': tenant}
    is_active = bool(tenant.get('is_active'))
    if is_active and not allow_after_activation:
        return {'error': 'slug_locked'}
    conn = get_db()
    try:
        conn.execute('UPDATE tenants SET slug = ? WHERE id = ?', (new_slug, tenant_id))
        if is_active and create_redirect and old_slug:
            conn.execute(
                'INSERT OR IGNORE INTO tenant_slug_redirects '
                '(old_slug, tenant_id, new_slug, created_by, created_by_name) '
                'VALUES (?, ?, ?, ?, ?)',
                (old_slug, tenant_id, new_slug, actor_id, actor_name),
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if 'unique' in str(exc).lower() or 'UNIQUE' in str(exc):
            return {'error': 'taken'}
        raise
    return {'slug': new_slug, 'previous': old_slug, 'redirect_created': bool(
        is_active and create_redirect and old_slug and old_slug != new_slug)}


def resolve_company_slug(slug):
    """Resolve a URL slug to ``(tenant, redirect_slug)``.

    The explicit ``slug`` column wins, then subdomain and username, then the
    ``t-<id8>`` fallback. A retired slug answers ``(None, new_slug)`` so the
    caller can issue a permanent redirect instead of a 404.
    """
    raw = str(slug or '').strip().lower()
    if not raw:
        return None, None
    conn = get_db()
    for candidate in dict.fromkeys([raw, _normalize_slug(raw)]):
        if not candidate:
            continue
        row = conn.execute(
            'SELECT * FROM tenants WHERE LOWER(slug) = ? AND is_active = 1',
            (candidate,),
        ).fetchone()
        if row:
            return dict(row), None
    tenant = get_tenant_by_slug(raw)
    if tenant:
        return tenant, None
    redirect = conn.execute(
        'SELECT new_slug FROM tenant_slug_redirects WHERE old_slug = ?', (raw,),
    ).fetchone()
    if redirect:
        return None, redirect['new_slug']
    return None, None


# ═════════════════════════════════════════════════════════════════════════════
# t50: activation gate — a company may only go live with a complete file
# ═════════════════════════════════════════════════════════════════════════════

# Fields and documents that must exist before the account is activated.
COMPANY_ACTIVATION_REQUIRED_FIELDS = ('legal_name', 'tax_number', 'cr_number', 'country')
COMPANY_ACTIVATION_REQUIRED_DOCS = {'contract'}


def tenant_activation_checklist(tenant):
    """Return the missing pieces blocking activation for a tenant row.

    ``missing`` lists stable keys the UI can label: a profile field name or
    ``doc:contract`` / ``doc:nda`` for a required document kind.
    """
    tenant = tenant or {}
    missing = [field for field in COMPANY_ACTIVATION_REQUIRED_FIELDS
               if not str(tenant.get(field) or '').strip()]
    conn = get_db()
    try:
        kinds = {r['kind'] for r in conn.execute(
            "SELECT DISTINCT kind FROM tenant_contracts WHERE tenant_id = ? AND status = 'active'",
            (tenant.get('id'),),
        ).fetchall()}
    except Exception:
        kinds = set()
    for kind in sorted(COMPANY_ACTIVATION_REQUIRED_DOCS):
        if kind not in kinds:
            missing.append('doc:' + kind)
    return {'complete': not missing, 'missing': missing}


def set_tenant_active(tenant_id, is_active, actor_id=None, actor_name=None, reason=None):
    """Flip the tenant's active flag with the activation gate and audit trail.

    Activating requires a complete company file (legal profile + contract on
    record); the first activation stamps ``activated_by``/``activated_at``.
    Deactivating stores the reason. Returns the updated tenant or an error
    dict carrying the missing checklist.
    """
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return {'error': 'tenant_not_found'}
    conn = get_db()
    now = _utcnow().isoformat()
    if is_active:
        checklist = tenant_activation_checklist(tenant)
        if not checklist['complete'] and not tenant.get('activated_at'):
            return {'error': 'activation_incomplete', 'missing': checklist['missing']}
        updates = ['is_active = 1', 'deactivated_reason = NULL']
        params = []
        if not tenant.get('activated_at'):
            updates += ['activated_by = ?', 'activated_by_name = ?', 'activated_at = ?']
            params += [actor_id, actor_name, now]
        params.append(tenant_id)
        conn.execute('UPDATE tenants SET ' + ', '.join(updates) + ' WHERE id = ?', params)
    else:
        conn.execute(
            'UPDATE tenants SET is_active = 0, deactivated_reason = ? WHERE id = ?',
            (str(reason or '').strip() or None, tenant_id),
        )
    conn.commit()
    return get_tenant_by_id(tenant_id)


# ═════════════════════════════════════════════════════════════════════════════
# t60-04: immutable package versions, subscriptions and top-up receipts
# ═════════════════════════════════════════════════════════════════════════════


def create_package_version(package_id, name=None, credit_usd=None, price_sar=None,
                           duration_days=None, limits=None, features=None,
                           actor_id=None, actor_name=None):
    """Snapshot a package into an immutable version row (next version number)."""
    conn = get_db()
    package = conn.execute(
        'SELECT * FROM billing_packages WHERE id = ?', (str(package_id),),
    ).fetchone()
    if package is None:
        return {'error': 'package_not_found'}
    package = dict(package)
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM billing_package_versions WHERE package_id = ?',
        (str(package_id),),
    ).fetchone()
    version = int(row['next'])
    version_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO billing_package_versions
           (id, package_id, version, name, credit_usd, price_sar, duration_days,
            limits_json, features_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (version_id, str(package_id), version,
         name if name is not None else package.get('name'),
         float(credit_usd) if credit_usd is not None else float(package.get('credit_usd') or 0.0),
         price_sar if price_sar is not None else package.get('price_sar'),
         duration_days,
         json.dumps(limits or {}, ensure_ascii=False),
         json.dumps(features or {}, ensure_ascii=False)),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM billing_package_versions WHERE id = ?', (version_id,)).fetchone())


def list_package_versions(package_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM billing_package_versions WHERE package_id = ? ORDER BY version DESC',
        (str(package_id),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['limits'] = _json_or(item.get('limits_json'), {})
        item['features'] = _json_or(item.get('features_json'), {})
        result.append(item)
    return result


def create_subscription(tenant_id, package_id=None, package_version_id=None,
                        starts_at=None, ends_at=None, trial_ends_at=None,
                        status='active', created_by=None, created_by_name=None):
    """Record a subscription window for a tenant (one active at a time)."""
    conn = get_db()
    if status == 'active':
        conn.execute(
            "UPDATE tenant_subscriptions SET status = 'expired' "
            "WHERE tenant_id = ? AND status = 'active'",
            (str(tenant_id),),
        )
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_subscriptions
           (id, tenant_id, package_id, package_version_id, status,
            starts_at, ends_at, trial_ends_at, created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id), str(package_id) if package_id else None,
         str(package_version_id) if package_version_id else None, status,
         starts_at or _utcnow().isoformat(), ends_at, trial_ends_at,
         created_by, created_by_name),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM tenant_subscriptions WHERE id = ?', (row_id,)).fetchone())


def current_subscription(tenant_id):
    conn = get_db()
    row = conn.execute(
        "SELECT s.*, p.name AS package_name, p.price_sar AS package_price_sar "
        "FROM tenant_subscriptions s LEFT JOIN billing_packages p ON p.id = s.package_id "
        "WHERE s.tenant_id = ? AND s.status = 'active' ORDER BY s.starts_at DESC LIMIT 1",
        (str(tenant_id),),
    ).fetchone()
    return dict(row) if row else None


def list_subscriptions(tenant_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT s.*, p.name AS package_name FROM tenant_subscriptions s '
        'LEFT JOIN billing_packages p ON p.id = s.package_id '
        'WHERE s.tenant_id = ? ORDER BY s.starts_at DESC',
        (str(tenant_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def current_package_limits(tenant_id):
    """d10: the limits dict of the tenant's active package version — empty
    when no subscription pins one. Uploads read ``max_file_mb`` from it."""
    conn = get_db()
    row = conn.execute(
        '''SELECT v.limits_json FROM tenant_subscriptions s
           JOIN billing_package_versions v ON v.id = s.package_version_id
           WHERE s.tenant_id = ? AND s.status = 'active'
           ORDER BY s.starts_at DESC LIMIT 1''',
        (str(tenant_id),),
    ).fetchone()
    if not row:
        return {}
    return _json_or(row['limits_json'], {})


def _next_invoice_number_tx(conn):
    """Sequential financial document number: INV-<year>-<six digits>."""
    year = _utcnow().year
    row = conn.execute(
        "SELECT invoice_number FROM topup_receipts WHERE invoice_number LIKE ? "
        "ORDER BY invoice_number DESC LIMIT 1",
        (f'INV-{year}-%',),
    ).fetchone()
    sequence = 1
    if row and row['invoice_number']:
        try:
            sequence = int(str(row['invoice_number']).rsplit('-', 1)[-1]) + 1
        except (ValueError, IndexError):
            sequence = 1
    return f'INV-{year}-{sequence:06d}'


TAX_RATE_SAR = float(os.environ.get('TOPUP_TAX_RATE', '0.15'))


def _create_topup_receipt_tx(conn, tenant_id, recharge_request_id=None, receipt_file_id=None,
                             receipt_sha256=None, transfer_reference=None, amount_usd=0,
                             price_sar=None, issued_by=None, issued_by_name=None):
    """d09: one financial document per approved top-up, inside the caller's
    transaction — never commits. Carries the VAT breakdown on the SAR price."""
    if recharge_request_id:
        existing = conn.execute(
            'SELECT * FROM topup_receipts WHERE recharge_request_id = ?',
            (str(recharge_request_id),),
        ).fetchone()
        if existing:
            return dict(existing)
    receipt_id = str(uuid.uuid4())
    invoice_number = _next_invoice_number_tx(conn)
    subtotal = float(price_sar) if price_sar is not None else None
    tax_amount = round(subtotal * TAX_RATE_SAR, 2) if subtotal is not None else None
    total_sar = round(subtotal + tax_amount, 2) if subtotal is not None else None
    conn.execute(
        '''INSERT INTO topup_receipts
           (id, tenant_id, recharge_request_id, receipt_file_id, receipt_sha256,
            transfer_reference, invoice_number, amount_usd, price_sar,
            tax_rate, tax_amount_sar, total_sar, status,
            issued_by, issued_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?, ?)''',
        (receipt_id, str(tenant_id),
         str(recharge_request_id) if recharge_request_id else None,
         str(receipt_file_id) if receipt_file_id else None,
         receipt_sha256, transfer_reference, invoice_number,
         float(amount_usd or 0.0), subtotal,
         TAX_RATE_SAR if subtotal is not None else None,
         tax_amount, total_sar,
         issued_by, issued_by_name),
    )
    return dict(conn.execute(
        'SELECT * FROM topup_receipts WHERE id = ?', (receipt_id,)).fetchone())


def create_topup_receipt(tenant_id, recharge_request_id=None, receipt_file_id=None,
                         receipt_sha256=None, transfer_reference=None, amount_usd=0,
                         price_sar=None, issued_by=None, issued_by_name=None):
    """Issue the financial document for an approved top-up (d09/t60-04).

    The receipt is created once per recharge request — a repeat call returns
    the existing row — and carries an immutable invoice number, the VAT
    breakdown and the receipt fingerprint so a duplicate bank transfer can be
    detected.
    """
    conn = get_db()
    row = _create_topup_receipt_tx(
        conn, tenant_id, recharge_request_id=recharge_request_id,
        receipt_file_id=receipt_file_id, receipt_sha256=receipt_sha256,
        transfer_reference=transfer_reference, amount_usd=amount_usd,
        price_sar=price_sar, issued_by=issued_by, issued_by_name=issued_by_name)
    conn.commit()
    return row


def list_topup_receipts(tenant_id, limit=100):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM topup_receipts WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?',
        (str(tenant_id), int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def get_topup_receipt(tenant_id, receipt_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM topup_receipts WHERE id = ? AND tenant_id = ?',
        (str(receipt_id), str(tenant_id)),
    ).fetchone()
    return dict(row) if row else None


# ═════════════════════════════════════════════════════════════════════════════
# t60-01: notification delivery rows per channel
# ═════════════════════════════════════════════════════════════════════════════

NOTIFICATION_CHANNELS = ('in_app', 'email')
DELIVERY_STATUSES = ('queued', 'sent', 'delivered', 'failed')


def queue_notification_deliveries(notification_id, tenant_id, channels=None, email_to=None):
    """Fan a notification out to per-channel delivery rows (t60-01).

    The in-app channel is delivered the moment it exists; the email channel is
    queued into ``email_outbox`` so a worker can retry it. Returns the created
    delivery rows.
    """
    conn = get_db()
    channels = list(channels or ('in_app',))
    now = _utcnow().isoformat()
    deliveries = []
    for channel in channels:
        if channel not in NOTIFICATION_CHANNELS:
            continue
        delivery_id = str(uuid.uuid4())
        if channel == 'in_app':
            status, sent_at, delivered_at = 'delivered', now, now
        else:
            status, sent_at, delivered_at = 'queued', None, None
        conn.execute(
            '''INSERT INTO notification_deliveries
               (id, notification_id, tenant_id, channel, status, attempts,
                last_attempt_at, sent_at, delivered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (delivery_id, notification_id, str(tenant_id), channel, status,
             1 if channel == 'in_app' else 0,
             now if channel == 'in_app' else None, sent_at, delivered_at),
        )
        if channel == 'email' and email_to:
            notification = conn.execute(
                'SELECT title, body FROM notifications WHERE id = ?', (notification_id,)
            ).fetchone()
            if notification:
                conn.execute(
                    '''INSERT INTO email_outbox
                       (id, tenant_id, notification_id, to_email, subject, body_text)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(uuid.uuid4()), str(tenant_id), notification_id, email_to,
                     notification['title'], notification['body']),
                )
        deliveries.append(dict(conn.execute(
            'SELECT * FROM notification_deliveries WHERE id = ?', (delivery_id,)
        ).fetchone()))
    conn.commit()
    return deliveries


def record_delivery_attempt(delivery_id, status, error=None):
    """Record one delivery attempt: attempts++ plus the terminal state."""
    if status not in DELIVERY_STATUSES:
        return {'error': 'invalid_status'}
    conn = get_db()
    now = _utcnow().isoformat()
    sent_at = now if status in ('sent', 'delivered') else None
    conn.execute(
        '''UPDATE notification_deliveries
           SET status = ?, attempts = attempts + 1, last_error = ?, last_attempt_at = ?,
               sent_at = COALESCE(?, sent_at), delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END
           WHERE id = ?''',
        (status, error, now, sent_at, status, now, str(delivery_id)),
    )
    conn.commit()
    row = conn.execute(
        'SELECT * FROM notification_deliveries WHERE id = ?', (str(delivery_id),)
    ).fetchone()
    return dict(row) if row else None


def mark_notification_read(notification_id, tenant_id):
    """Stamp read_at on the in-app delivery when the feed marks it read."""
    conn = get_db()
    now = _utcnow().isoformat()
    conn.execute(
        '''UPDATE notification_deliveries SET read_at = ?
           WHERE notification_id = ? AND tenant_id = ? AND channel = 'in_app' AND read_at IS NULL''',
        (now, str(notification_id), str(tenant_id)),
    )
    conn.commit()


def notification_delivery_report(tenant_id=None, limit=200):
    """Delivery rows joined with their notification for the delivery log UI."""
    conn = get_db()
    query = ('SELECT d.*, n.title, n.category, n.user_id FROM notification_deliveries d '
             'JOIN notifications n ON n.id = d.notification_id')
    params = []
    if tenant_id:
        query += ' WHERE d.tenant_id = ?'
        params.append(str(tenant_id))
    query += ' ORDER BY d.created_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


# ═════════════════════════════════════════════════════════════════════════════
# t60-02: ticket attachments and project links
# ═════════════════════════════════════════════════════════════════════════════


def attach_support_ticket_file(tenant_id, ticket_id, file_id, message_id=None):
    """Attach a stored project file to a support ticket."""
    conn = get_db()
    ticket = conn.execute(
        'SELECT id FROM support_tickets WHERE id = ? AND tenant_id = ?',
        (str(ticket_id), str(tenant_id)),
    ).fetchone()
    if not ticket:
        return {'error': 'ticket_not_found'}
    file_row = conn.execute(
        'SELECT id FROM project_files WHERE id = ? AND tenant_id = ?',
        (str(file_id), str(tenant_id)),
    ).fetchone()
    if not file_row:
        return {'error': 'file_not_found'}
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO support_ticket_attachments (id, ticket_id, message_id, tenant_id, file_id)
           VALUES (?, ?, ?, ?, ?)''',
        (row_id, str(ticket_id), str(message_id) if message_id else None,
         str(tenant_id), str(file_id)),
    )
    conn.commit()
    return dict(conn.execute(
        'SELECT * FROM support_ticket_attachments WHERE id = ?', (row_id,)).fetchone())


def list_support_ticket_attachments(ticket_id):
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.*, f.original_name, f.mime_type, f.file_size
           FROM support_ticket_attachments a
           JOIN project_files f ON f.id = a.file_id
           WHERE a.ticket_id = ? ORDER BY a.created_at''',
        (str(ticket_id),),
    ).fetchall()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# t60-05: generation jobs and document versions
# ═════════════════════════════════════════════════════════════════════════════

GENERATION_JOB_STATUSES = ('queued', 'running', 'completed', 'failed', 'cancelled')


def create_generation_job(tenant_id, approval_id=None, draft_id=None, presentation_id=None,
                          model=None, template_version=None, schema_version=None,
                          input_snapshot=None, estimated_cost_usd=None, slides_total=None,
                          created_by=None, created_by_name=None, idempotency_key=None,
                          correlation_id=None):
    """Register one generation run tied to its approval and input snapshot.

    ``idempotency_key`` makes a retried client call return the same job
    instead of a duplicate row.
    """
    conn = get_db()
    if idempotency_key:
        existing = conn.execute(
            'SELECT * FROM generation_jobs WHERE idempotency_key = ?',
            (str(idempotency_key),),
        ).fetchone()
        if existing:
            return dict(existing)
    job_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO generation_jobs
           (id, tenant_id, approval_id, draft_id, presentation_id, status, model,
            template_version, schema_version, input_snapshot_json, estimated_cost_usd,
            slides_total, correlation_id, idempotency_key, created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (job_id, str(tenant_id), approval_id, draft_id, presentation_id, model,
         template_version, schema_version,
         json.dumps(input_snapshot, ensure_ascii=False) if input_snapshot is not None else None,
         estimated_cost_usd, slides_total, correlation_id,
         str(idempotency_key) if idempotency_key else None, created_by, created_by_name),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (job_id,)).fetchone())


def update_generation_job(job_id, status=None, progress=None, slides_done=None,
                          slides_total=None, actual_cost_usd=None, error=None):
    """Advance a generation job; first 'running' stamps started_at, terminal
    states stamp finished_at."""
    conn = get_db()
    row = conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (str(job_id),)).fetchone()
    if not row:
        return {'error': 'job_not_found'}
    row = dict(row)
    updates = []
    params = []
    now = _utcnow().isoformat()
    if status is not None:
        if status not in GENERATION_JOB_STATUSES:
            return {'error': 'invalid_status'}
        updates.append('status = ?')
        params.append(status)
        if status == 'running' and not row.get('started_at'):
            updates.append('started_at = ?')
            params.append(now)
        if status in ('completed', 'failed', 'cancelled'):
            updates.append('finished_at = ?')
            params.append(now)
    if progress is not None:
        updates.append('progress = ?')
        params.append(max(0, min(100, int(progress))))
    if slides_done is not None:
        updates.append('slides_done = ?')
        params.append(int(slides_done))
    if slides_total is not None:
        updates.append('slides_total = ?')
        params.append(int(slides_total))
    if actual_cost_usd is not None:
        updates.append('actual_cost_usd = ?')
        params.append(float(actual_cost_usd))
    if error is not None:
        updates.append('error = ?')
        params.append(str(error)[:2000])
    # Every update doubles as the heartbeat the stale-job sweeper reads.
    updates.append('heartbeat_at = ?')
    params.append(now)
    params.append(str(job_id))
    conn.execute('UPDATE generation_jobs SET ' + ', '.join(updates) + ' WHERE id = ?', params)
    conn.commit()
    return dict(conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (str(job_id),)).fetchone())


GENERATION_JOB_TIMEOUT_MINUTES = int(os.environ.get('GENERATION_JOB_TIMEOUT_MINUTES', '30'))


def sweep_stale_generation_jobs(tenant_id=None, timeout_minutes=None):
    """Fail generation jobs whose heartbeat went silent and free their holds.

    A client that dies mid-run leaves the job 'running' forever with the
    reservation still held; this sweep is the server-side safety net behind
    the client releases (t14-06). It runs lazily on the read paths that list
    jobs and approvals.
    """
    conn = get_db()
    limit = int(timeout_minutes or GENERATION_JOB_TIMEOUT_MINUTES)
    cutoff = (_utcnow() - timedelta(minutes=limit)).isoformat()
    clauses = ["status IN ('queued', 'running')",
               "COALESCE(heartbeat_at, started_at, created_at) < ?"]
    params = [cutoff]
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(str(tenant_id))
    try:
        rows = conn.execute(
            'SELECT * FROM generation_jobs WHERE ' + ' AND '.join(clauses),
            tuple(params),
        ).fetchall()
    except Exception:
        return 0
    for job in rows:
        conn.execute(
            "UPDATE generation_jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
            ('job_timeout', _utcnow().isoformat(), job['id']),
        )
        conn.commit()
        try:
            create_notification(
                job['tenant_id'], 'فشلت مهمة التوليد',
                'انتهت مهلة التوليد — حُرر الحجز تلقائيًا',
                category='job', user_id=job['created_by'] or None,
                entity_type='generation_job', entity_id=job['id'])
        except Exception:
            pass
        if job['approval_id']:
            try:
                settle_generation_approval(
                    job['tenant_id'], job['approval_id'], job['id'], consumed=False,
                    settled_by='system',
                    note='انتهت مهلة مهمة التوليد — تحرير الحجز تلقائيًا')
            except Exception:
                pass
    return len(rows)


def get_generation_job(job_id, tenant_id=None):
    conn = get_db()
    if tenant_id:
        row = conn.execute(
            'SELECT * FROM generation_jobs WHERE id = ? AND tenant_id = ?',
            (str(job_id), str(tenant_id)),
        ).fetchone()
    else:
        row = conn.execute('SELECT * FROM generation_jobs WHERE id = ?', (str(job_id),)).fetchone()
    return dict(row) if row else None


def list_generation_jobs(tenant_id=None, status=None, limit=100):
    if tenant_id:
        sweep_stale_generation_jobs(tenant_id)
    conn = get_db()
    clauses = []
    params = []
    if tenant_id:
        clauses.append('tenant_id = ?')
        params.append(str(tenant_id))
    if status:
        clauses.append('status = ?')
        params.append(status)
    query = 'SELECT * FROM generation_jobs'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def create_document_version(tenant_id, document_type, document_id, file_id=None,
                            content_hash=None, approval_id=None, generated_by=None,
                            generated_by_name=None):
    """Version every produced document; the next number is per document id."""
    conn = get_db()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM document_versions '
        'WHERE tenant_id = ? AND document_type = ? AND document_id = ?',
        (str(tenant_id), str(document_type), str(document_id)),
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO document_versions
           (id, tenant_id, document_type, document_id, version, file_id, content_hash,
            approval_id, generated_by, generated_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id), str(document_type), str(document_id), version,
         file_id, content_hash, approval_id, generated_by, generated_by_name),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM document_versions WHERE id = ?', (row_id,)).fetchone())


def list_document_versions(tenant_id, document_type=None, document_id=None):
    conn = get_db()
    clauses = ['tenant_id = ?']
    params = [str(tenant_id)]
    if document_type:
        clauses.append('document_type = ?')
        params.append(str(document_type))
    if document_id:
        clauses.append('document_id = ?')
        params.append(str(document_id))
    rows = conn.execute(
        'SELECT * FROM document_versions WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY created_at DESC', params,
    ).fetchall()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# t61: persistent job queue + email outbox (survive process restarts)
# ═════════════════════════════════════════════════════════════════════════════


def enqueue_job(job_type, payload=None, tenant_id=None, priority=100, run_after=None,
                correlation_id=None, max_attempts=3):
    """Put a unit of background work on the durable queue."""
    conn = get_db()
    job_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO job_queue
           (id, tenant_id, job_type, payload_json, priority, run_after, max_attempts, correlation_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (job_id, str(tenant_id) if tenant_id else None, str(job_type),
         json.dumps(payload or {}, ensure_ascii=False), int(priority), run_after,
         int(max_attempts), correlation_id),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM job_queue WHERE id = ?', (job_id,)).fetchone())


def claim_due_jobs(worker_id, limit=5, now=None):
    """Atomically mark due queued jobs running for this worker and return them."""
    conn = get_db()
    now = now or _utcnow().isoformat()
    conn.execute(
        '''UPDATE job_queue SET status = 'running', locked_by = ?, locked_at = ?,
           started_at = COALESCE(started_at, ?), attempts = attempts + 1
           WHERE id IN (
               SELECT id FROM job_queue
               WHERE status = 'queued' AND (run_after IS NULL OR run_after <= ?)
               ORDER BY priority, created_at LIMIT ?
           )''',
        (str(worker_id), now, now, now, int(limit)),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM job_queue WHERE status = 'running' AND locked_by = ? ORDER BY priority, created_at",
        (str(worker_id),),
    ).fetchall()
    result = []
    for row in rows[:int(limit)]:
        item = dict(row)
        item['payload'] = _json_or(item.get('payload_json'), {})
        result.append(item)
    return result


def complete_job(job_id, worker_id=None):
    conn = get_db()
    conn.execute(
        "UPDATE job_queue SET status = 'done', finished_at = ?, locked_by = NULL "
        "WHERE id = ? AND status = 'running'",
        (_utcnow().isoformat(), str(job_id)),
    )
    conn.commit()


def fail_job(job_id, error=None, retry_delay_seconds=60, worker_id=None):
    """Record a failure; retry while attempts remain, then mark dead."""
    conn = get_db()
    row = conn.execute('SELECT * FROM job_queue WHERE id = ?', (str(job_id),)).fetchone()
    if not row:
        return
    now = _utcnow()
    from datetime import timedelta
    error_text = str(error or '')[:2000]
    if int(row['attempts'] or 0) < int(row['max_attempts'] or 1):
        run_after = (now + timedelta(seconds=int(retry_delay_seconds))).isoformat()
        conn.execute(
            """UPDATE job_queue SET status = 'queued', run_after = ?, locked_by = NULL,
               last_error = ? WHERE id = ?""",
            (run_after, error_text, str(job_id)),
        )
    else:
        conn.execute(
            "UPDATE job_queue SET status = 'dead', finished_at = ?, last_error = ? WHERE id = ?",
            (now.isoformat(), error_text, str(job_id)),
        )
    conn.commit()


def requeue_dead_jobs(job_type=None, limit=100):
    """Operator action: put dead jobs back on the queue with attempts reset."""
    conn = get_db()
    clauses = ["status = 'dead'"]
    params = []
    if job_type:
        clauses.append('job_type = ?')
        params.append(str(job_type))
    rows = conn.execute(
        'SELECT id FROM job_queue WHERE ' + ' AND '.join(clauses) + ' LIMIT ?',
        list(params) + [int(limit)],
    ).fetchall()
    now = _utcnow().isoformat()
    for row in rows:
        conn.execute(
            """UPDATE job_queue SET status = 'queued', attempts = 0, run_after = ?,
               locked_by = NULL, locked_at = NULL, last_error = NULL WHERE id = ?""",
            (now, row['id']),
        )
    conn.commit()
    return len(rows)


def list_jobs(status=None, job_type=None, limit=100):
    conn = get_db()
    clauses = []
    params = []
    if status:
        clauses.append('status = ?')
        params.append(str(status))
    if job_type:
        clauses.append('job_type = ?')
        params.append(str(job_type))
    query = 'SELECT * FROM job_queue'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(int(limit))
    result = []
    for row in conn.execute(query, params).fetchall():
        item = dict(row)
        item['payload'] = _json_or(item.get('payload_json'), {})
        result.append(item)
    return result


def enqueue_email(to_email, subject, body_text=None, body_html=None, tenant_id=None,
                  notification_id=None, related_type=None, related_id=None):
    """Outbound mail goes through the outbox so SMTP outages lose nothing."""
    conn = get_db()
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO email_outbox
           (id, tenant_id, notification_id, to_email, subject, body_text, body_html,
            related_type, related_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id) if tenant_id else None,
         str(notification_id) if notification_id else None,
         str(to_email or ''), str(subject or ''), body_text, body_html,
         related_type, str(related_id) if related_id else None),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM email_outbox WHERE id = ?', (row_id,)).fetchone())


def claim_due_emails(limit=20):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM email_outbox WHERE status = 'queued'
           ORDER BY created_at LIMIT ?""",
        (int(limit),),
    ).fetchall()
    claimed = []
    for row in rows:
        cursor = conn.execute(
            "UPDATE email_outbox SET status = 'sending', attempts = attempts + 1 "
            "WHERE id = ? AND status = 'queued'",
            (row['id'],),
        )
        if cursor.rowcount:
            claimed.append(row)
    conn.commit()
    return [dict(r) for r in claimed]


def mark_email_sent(email_id):
    conn = get_db()
    conn.execute(
        "UPDATE email_outbox SET status = 'sent', sent_at = ? WHERE id = ?",
        (_utcnow().isoformat(), str(email_id)),
    )
    conn.commit()


def mark_email_delivery(notification_id, status, error=None):
    """Reflect an outbox send result on the notification's email delivery row."""
    if not notification_id:
        return
    conn = get_db()
    now = _utcnow().isoformat()
    conn.execute(
        """UPDATE notification_deliveries
           SET status = ?, attempts = attempts + 1, last_attempt_at = ?,
               last_error = ?,
               sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END,
               delivered_at = CASE WHEN ? = 'sent' THEN ? ELSE delivered_at END
           WHERE notification_id = ? AND channel = 'email'""",
        (status, now, str(error or '')[:2000] or None,
         status, now, status, now, str(notification_id)),
    )
    conn.commit()


def mark_email_failed(email_id, error=None):
    conn = get_db()
    row = conn.execute('SELECT * FROM email_outbox WHERE id = ?', (str(email_id),)).fetchone()
    if not row:
        return
    error_text = str(error or '')[:2000]
    if int(row['attempts'] or 0) < 5:
        conn.execute(
            "UPDATE email_outbox SET status = 'queued', last_error = ? WHERE id = ?",
            (error_text, str(email_id)),
        )
    else:
        conn.execute(
            "UPDATE email_outbox SET status = 'dead', last_error = ? WHERE id = ?",
            (error_text, str(email_id)),
        )
    conn.commit()


def list_email_outbox(status=None, limit=100):
    conn = get_db()
    clauses = []
    params = []
    if status:
        clauses.append('status = ?')
        params.append(str(status))
    query = 'SELECT * FROM email_outbox'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(r) for r in conn.execute(query, params).fetchall()]


# ═════════════════════════════════════════════════════════════════════════════
# t62: study-type registry, generator registry, feature flags, schema versions
# ═════════════════════════════════════════════════════════════════════════════


def register_study_type(key, name_ar, name_en=None, definition=None,
                        supersedes_version=None, created_by=None, created_by_name=None):
    """Register a new immutable version of a study type (t62).

    The definition carries sections, fields, validation rules, the approval
    sequence and pricing hints as JSON. A re-register of the same key creates
    the next version; older versions stay addressable.
    """
    key = str(key or '').strip().lower()
    if not key or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,60}', key):
        return {'error': 'invalid_key'}
    if not str(name_ar or '').strip():
        return {'error': 'name_required'}
    conn = get_db()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM study_types WHERE key = ?', (key,)
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO study_types
           (id, key, version, name_ar, name_en, definition_json, supersedes_version,
            created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, key, version, str(name_ar).strip(), name_en,
         json.dumps(definition or {}, ensure_ascii=False), supersedes_version,
         created_by, created_by_name),
    )
    conn.commit()
    return _study_type_public(conn.execute(
        'SELECT * FROM study_types WHERE id = ?', (row_id,)).fetchone())


def _study_type_public(row):
    if not row:
        return None
    item = dict(row)
    item['definition'] = _json_or(item.get('definition_json'), {})
    return item


def get_study_type(key, version=None, active_only=True):
    conn = get_db()
    clauses = ['key = ?']
    params = [str(key).strip().lower()]
    if version is not None:
        clauses.append('version = ?')
        params.append(int(version))
    if active_only:
        clauses.append('is_active = 1')
    row = conn.execute(
        'SELECT * FROM study_types WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY version DESC LIMIT 1', params,
    ).fetchone()
    return _study_type_public(row)


def list_study_types(active_only=False, latest_only=True):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM study_types' + (' WHERE is_active = 1' if active_only else '') +
        ' ORDER BY key, version DESC'
    ).fetchall()
    seen = set()
    result = []
    for row in rows:
        item = _study_type_public(row)
        if latest_only and item['key'] in seen:
            continue
        seen.add(item['key'])
        result.append(item)
    return result


def register_generator(kind, key, config=None, label_ar=None, label_en=None,
                       supersedes_version=None):
    """Register a new version of a generator entry (slide/PDF template, output
    model, processor)."""
    kind = str(kind or '').strip().lower()
    key = str(key or '').strip().lower()
    if kind not in ('slide_template', 'pdf_template', 'content_template', 'ai_model',
                    'processor', 'exporter'):
        return {'error': 'invalid_kind'}
    if not key or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{1,60}', key):
        return {'error': 'invalid_key'}
    conn = get_db()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM generator_registry WHERE kind = ? AND key = ?',
        (kind, key),
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO generator_registry
           (id, kind, key, version, label_ar, label_en, config_json, supersedes_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, kind, key, version, label_ar, label_en,
         json.dumps(config or {}, ensure_ascii=False), supersedes_version),
    )
    conn.commit()
    item = dict(conn.execute('SELECT * FROM generator_registry WHERE id = ?', (row_id,)).fetchone())
    item['config'] = _json_or(item.get('config_json'), {})
    return item


def list_generators(kind=None, active_only=True):
    conn = get_db()
    clauses = []
    params = []
    if kind:
        clauses.append('kind = ?')
        params.append(str(kind))
    if active_only:
        clauses.append('is_active = 1')
    query = 'SELECT * FROM generator_registry'
    if clauses:
        query += ' WHERE ' + ' AND '.join(clauses)
    query += ' ORDER BY kind, key, version DESC'
    result = []
    seen = set()
    for row in conn.execute(query, params).fetchall():
        item = dict(row)
        item['config'] = _json_or(item.get('config_json'), {})
        marker = (item['kind'], item['key'])
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def get_generator(kind, key, version=None):
    conn = get_db()
    clauses = ['kind = ?', 'key = ?', 'is_active = 1']
    params = [str(kind), str(key)]
    if version is not None:
        clauses.append('version = ?')
        params.append(int(version))
    row = conn.execute(
        'SELECT * FROM generator_registry WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY version DESC LIMIT 1', params,
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item['config'] = _json_or(item.get('config_json'), {})
    return item


def snapshot_field_schema(tenant_id, created_by=None, created_by_name=None):
    """Freeze the tenant's active input fields as the next schema version."""
    conn = get_db()
    fields = conn.execute(
        'SELECT field_key, field_label, field_type, field_options, section_key, is_required, '
        'is_active, is_custom, sort_order FROM tenant_input_fields WHERE tenant_id = ? '
        'ORDER BY section_key, sort_order',
        (str(tenant_id),),
    ).fetchall()
    row = conn.execute(
        'SELECT COALESCE(MAX(version), 0) + 1 AS next FROM field_schema_versions WHERE tenant_id = ?',
        (str(tenant_id),),
    ).fetchone()
    version = int(row['next'])
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO field_schema_versions (id, tenant_id, version, schema_json, created_by, created_by_name)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (row_id, str(tenant_id), version,
         json.dumps([dict(f) for f in fields], ensure_ascii=False), created_by, created_by_name),
    )
    conn.commit()
    item = dict(conn.execute('SELECT * FROM field_schema_versions WHERE id = ?', (row_id,)).fetchone())
    item['schema'] = _json_or(item.get('schema_json'), [])
    return item


def latest_field_schema_version(tenant_id):
    conn = get_db()
    row = conn.execute(
        'SELECT version FROM field_schema_versions WHERE tenant_id = ? ORDER BY version DESC LIMIT 1',
        (str(tenant_id),),
    ).fetchone()
    return int(row['version']) if row else None


def get_file_type_rule(file_type):
    """Registry-driven upload rule for one file type (t62/d10).

    Returns the active registry row or None when the type is unknown or
    disabled — uploads must refuse types the registry does not carry.
    """
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM file_type_registry WHERE key = ? AND is_active = 1',
        (str(file_type or '').strip().lower(),),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item['allowed_extensions'] = _json_or(item.get('allowed_extensions'), [])
    return item


# ═════════════════════════════════════════════════════════════════════════════
# t63: backup registry — RPO is measurable, restore tests are recorded
# ═════════════════════════════════════════════════════════════════════════════

RPO_TARGET_HOURS = int(os.environ.get('BACKUP_RPO_HOURS', '24'))
RTO_TARGET_HOURS = int(os.environ.get('BACKUP_RTO_HOURS', '4'))


def record_backup(kind='full', path=None, size_bytes=None, sha256=None,
                  encrypted=False, note=None):
    conn = get_db()
    row_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO backup_history
           (id, kind, status, path, size_bytes, sha256, encrypted, note, created_at, completed_at)
           VALUES (?, ?, 'done', ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, str(kind), path, size_bytes, sha256, 1 if encrypted else 0, note, now, now),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM backup_history WHERE id = ?', (row_id,)).fetchone())


def list_backups(limit=50):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM backup_history ORDER BY created_at DESC LIMIT ?', (int(limit),)
    ).fetchall()
    return [dict(r) for r in rows]


def latest_successful_backup():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM backup_history WHERE status = 'done' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def mark_backup_restore_tested(backup_id, note=None):
    conn = get_db()
    conn.execute(
        "UPDATE backup_history SET restore_tested_at = ?, note = COALESCE(?, note) WHERE id = ?",
        (_utcnow().isoformat(), note, str(backup_id)),
    )
    conn.commit()
    row = conn.execute('SELECT * FROM backup_history WHERE id = ?', (str(backup_id),)).fetchone()
    return dict(row) if row else None


# ═════════════════════════════════════════════════════════════════════════════
# t54: operational monitoring — metrics without client content
# ═════════════════════════════════════════════════════════════════════════════


def storage_overview():
    """Storage usage per company: file bytes and object counts, no content."""
    conn = get_db()
    per_tenant = []
    try:
        rows = conn.execute(
            '''SELECT pf.tenant_id, COALESCE(SUM(pf.file_size), 0) AS bytes, COUNT(*) AS files,
                      tn.company_name
               FROM project_files pf LEFT JOIN tenants tn ON tn.id = pf.tenant_id
               GROUP BY pf.tenant_id ORDER BY bytes DESC'''
        ).fetchall()
        per_tenant = [{'tenant_id': r['tenant_id'], 'company_name': r['company_name'],
                       'bytes': int(r['bytes'] or 0), 'files': int(r['files'] or 0)}
                      for r in rows]
    except Exception:
        per_tenant = []
    total_bytes = sum(item['bytes'] for item in per_tenant)
    return {'total_bytes': total_bytes, 'per_tenant': per_tenant}


def generation_job_metrics():
    """Generation throughput, failures and durations for the ops dashboard."""
    conn = get_db()
    metrics = {'total': 0, 'by_status': {}, 'failed_24h': 0, 'completed_24h': 0,
               'avg_duration_seconds': None, 'success_rate': None}
    try:
        rows = conn.execute(
            'SELECT status, COUNT(*) AS n FROM generation_jobs GROUP BY status'
        ).fetchall()
        for r in rows:
            metrics['by_status'][r['status']] = int(r['n'] or 0)
        metrics['total'] = sum(metrics['by_status'].values())
        from datetime import timedelta
        cutoff = (_utcnow() - timedelta(hours=24)).isoformat()
        metrics['failed_24h'] = int(conn.execute(
            "SELECT COUNT(*) AS n FROM generation_jobs WHERE status = 'failed' AND finished_at >= ?",
            (cutoff,),
        ).fetchone()['n'] or 0)
        metrics['completed_24h'] = int(conn.execute(
            "SELECT COUNT(*) AS n FROM generation_jobs WHERE status = 'completed' AND finished_at >= ?",
            (cutoff,),
        ).fetchone()['n'] or 0)
        durations = conn.execute(
            """SELECT started_at, finished_at FROM generation_jobs
               WHERE status = 'completed' AND started_at IS NOT NULL AND finished_at IS NOT NULL
               ORDER BY finished_at DESC LIMIT 200"""
        ).fetchall()
        total_seconds = 0.0
        counted = 0
        for row in durations:
            try:
                total_seconds += (datetime.fromisoformat(row['finished_at'])
                                  - datetime.fromisoformat(row['started_at'])).total_seconds()
                counted += 1
            except (TypeError, ValueError):
                continue
        if counted:
            metrics['avg_duration_seconds'] = round(total_seconds / counted, 1)
        decided = metrics['by_status'].get('completed', 0) + metrics['by_status'].get('failed', 0)
        if decided:
            metrics['success_rate'] = round(metrics['by_status'].get('completed', 0) / decided * 100, 1)
    except Exception:
        pass
    return metrics


def platform_alerts():
    """Computed alert list: failures, stale work, overdue backups (t54)."""
    conn = get_db()
    alerts = []
    now = _utcnow()
    from datetime import timedelta

    stale_recharges = 0
    try:
        cutoff = (now - timedelta(hours=24)).isoformat()
        stale_recharges = int(conn.execute(
            "SELECT COUNT(*) AS n FROM recharge_requests WHERE status = 'pending' AND requested_at < ?",
            (cutoff,),
        ).fetchone()['n'] or 0)
    except Exception:
        pass
    if stale_recharges:
        alerts.append({'kind': 'recharge_sla', 'severity': 'warning',
                       'count': stale_recharges,
                       'message_ar': 'طلبات شحن تجاوزت مهلة المراجعة ٢٤ ساعة'})
    try:
        failed_jobs = int(conn.execute(
            "SELECT COUNT(*) AS n FROM generation_jobs WHERE status = 'failed' AND finished_at >= ?",
            ((now - timedelta(hours=24)).isoformat(),),
        ).fetchone()['n'] or 0)
    except Exception:
        failed_jobs = 0
    if failed_jobs:
        alerts.append({'kind': 'generation_failures', 'severity': 'critical',
                       'count': failed_jobs, 'message_ar': 'مهام توليد فاشلة خلال ٢٤ ساعة'})
    try:
        dead_jobs = int(conn.execute(
            "SELECT COUNT(*) AS n FROM job_queue WHERE status = 'dead'"
        ).fetchone()['n'] or 0)
    except Exception:
        dead_jobs = 0
    if dead_jobs:
        alerts.append({'kind': 'dead_jobs', 'severity': 'critical', 'count': dead_jobs,
                       'message_ar': 'مهام خلفية استنفدت محاولاتها'})
    try:
        expiring = int(conn.execute(
            """SELECT COUNT(*) AS n FROM tenant_contracts
               WHERE status = 'active' AND expires_at IS NOT NULL
               AND expires_at < ? AND expires_at >= ?""",
            ((now + timedelta(days=30)).isoformat(), now.isoformat()),
        ).fetchone()['n'] or 0)
    except Exception:
        expiring = 0
    if expiring:
        alerts.append({'kind': 'contract_expiry', 'severity': 'warning', 'count': expiring,
                       'message_ar': 'عقود تنتهي خلال ٣٠ يومًا'})
    try:
        retention = enforce_contract_retention()
        lapsed = int(retention.get('retention_lapsed') or 0)
    except Exception:
        lapsed = 0
    if lapsed:
        alerts.append({'kind': 'retention_due', 'severity': 'critical', 'count': lapsed,
                       'message_ar': 'عقود تجاوزت مدة الاحتفاظ — بياناتها مستحقة المراجعة'})
    return alerts


def email_outbox_stats():
    """Queued/sent/failed counts for the outbound mail worker table."""
    conn = get_db()
    stats = {'queued': 0, 'sent': 0, 'failed': 0, 'dead': 0}
    try:
        rows = conn.execute(
            'SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status'
        ).fetchall()
        for r in rows:
            stats[str(r['status'])] = int(r['n'] or 0)
    except Exception:
        pass
    return stats


def job_queue_stats():
    """Queue depth per status for the background worker table."""
    conn = get_db()
    stats = {'queued': 0, 'running': 0, 'done': 0, 'failed': 0, 'dead': 0}
    try:
        rows = conn.execute(
            'SELECT status, COUNT(*) AS n FROM job_queue GROUP BY status'
        ).fetchall()
        for r in rows:
            stats[str(r['status'])] = int(r['n'] or 0)
    except Exception:
        pass
    return stats
