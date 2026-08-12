"""
Database layer for Multi-Tenant SaaS.
SQLite-based with full migration support.
"""

import os
import re
import uuid
import json
from datetime import datetime
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
        _migrate_project_file_table(conn)
        _migrate_location_fields(conn)
        _migrate_font_system(conn)

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
        subdomain TEXT UNIQUE,
        domain TEXT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        plan TEXT DEFAULT 'free',
        is_active INTEGER DEFAULT 1,
        is_admin INTEGER DEFAULT 0,
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
    CREATE INDEX IF NOT EXISTS idx_exports_tenant ON exports(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_templates_tenant ON tenant_slide_templates(tenant_id);

    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'employee',
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
    CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

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
    """)

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
                conn.execute(f'ALTER TABLE project_drafts ADD COLUMN {column} {definition}')
                print(f'[DB] Migration: added {column} column to project_drafts')


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

def create_tenant(company_name, email, password_hash, subdomain=None, plan='free'):
    """Create a new tenant with branding row and default fields."""
    conn = get_db()
    tenant_id = str(uuid.uuid4())

    conn.execute(
        'INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan) VALUES (?, ?, ?, ?, ?, ?)',
        (tenant_id, company_name, subdomain, email, password_hash, plan)
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


def get_all_tenants():
    """Fetch all tenants (admin only)."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM tenants ORDER BY created_at DESC').fetchall()
    return [dict(r) for r in rows]


def update_tenant(tenant_id, **fields):
    """Update tenant fields dynamically."""
    conn = get_db()
    allowed = {'company_name', 'subdomain', 'plan', 'is_active', 'settings_json'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [tenant_id]
    conn.execute(f'UPDATE tenants SET {set_clause} WHERE id = ?', values)
    conn.commit()
    return True


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
        'logo_path', 'company_name', 'tagline', 'font_family', 'font_arabic',
        'design_template', 'reference_image_path',
        'header_enabled', 'footer_enabled', 'header_height', 'footer_height',
        'card_style', 'slide_ratio', 'moodboard_enabled', 'cover_image_enabled', 'moodboard_count',
        'default_slide_count', 'lock_slide_count', 'min_slides', 'max_slides',
        'default_map_type', 'map_style_overview', 'map_style_landmarks', 'map_style_access', 'map_style_catchment',
        'draw_compass', 'draw_inset', 'font_file_path', 'font_file_data',
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    # Guard against missing columns on databases that haven't run the latest migration
    existing_cols = {row['name'] for row in conn.execute('PRAGMA table_info(tenant_branding)')}
    updates = {k: v for k, v in updates.items() if k in existing_cols}
    if not updates:
        return False
    updates['updated_at'] = datetime.now().isoformat()
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
]

DEFAULT_FIELD_SECTIONS = {s['key']: True for s in FIELD_SECTIONS}

REMOVED_PREBUILT_FIELDS = {
    'land_image_file', 'regulation_reference_file', 'croquis_file', 'building_permit_file',
    'north_direction', 'croquis_expiry_date', 'subdivision_number',
    'project_idea', 'project_goal', 'target_audience', 'initial_features', 'initial_strengths',
    'building_ratio_setbacks', 'allowed_uses_restrictions',
}

PREBUILT_FIELDS = [
    {'key': 'project_name', 'label': 'اسم المشروع', 'type': 'text', 'required': True, 'section_key': 'basic', 'ai_hint': 'اسم المشروع الرئيسي', 'sort_order': 1},
    {'key': 'project_type', 'label': 'نوع المشروع', 'type': 'select', 'options': ['مختلط', 'سكني', 'تجاري', 'إداري', 'فندقي', 'ترفيهي', 'صناعي', 'لوجستي', 'طبي', 'تعليمي', 'سيارات وترفيه', 'أخرى'], 'required': True, 'section_key': 'basic', 'ai_hint': 'نوع المشروع العقاري', 'sort_order': 2},
    {'key': 'project_stage', 'label': 'مرحلة المشروع الحالية', 'type': 'select', 'options': ['فكرة أولية', 'فرصة استثمارية', 'دراسة جدوى', 'تصميم', 'تحت التنفيذ', 'قائم لإعادة التطوير', 'أخرى'], 'required': False, 'section_key': 'basic', 'ai_hint': 'المرحلة الحالية التي يمر بها المشروع', 'sort_order': 3},
    {'key': 'project_logo', 'label': 'شعار المشروع (Logo)', 'type': 'image', 'required': False, 'section_key': 'basic', 'ai_hint': 'صورة شعار المشروع', 'sort_order': 4},
    {'key': 'location_address', 'label': 'رابط موقع الأرض في Google Maps', 'type': 'text', 'required': True, 'section_key': 'location', 'ai_hint': 'رابط Google Maps مباشر لنقطة الأرض؛ يستخدم لتحديد الإحداثيات والبيانات المكانية والاشتراطات المرتبطة بالموقع', 'sort_order': 10},
    {'key': 'land_documents_files', 'label': 'رفع رخصة البناء والكروكي أو المستندات (ملفان كحد أقصى)', 'type': 'file', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ارفع ملف رخصة البناء وملف الكروكي معًا ليتم تحليلهما في طلب AI واحد', 'sort_order': 11},
    {'key': 'plot_number_croquis', 'label': 'رقم القطعة', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم قطعة الأرض وحده بدون رقم المخطط أو القسم', 'sort_order': 12},
    {'key': 'plan_number', 'label': 'رقم المخطط', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم المخطط وحده كما هو في الصك أو الكروكي', 'sort_order': 13},
    {'key': 'deed_number', 'label': 'رقم الصك أو المرجع', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'رقم صك الملكية أو المرجع الرسمي', 'sort_order': 14},
    {'key': 'deed_date', 'label': 'تاريخ الصك', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'تاريخ إصدار الصك كما هو مكتوب (هجري أو ميلادي) — ليس تاريخ الكروكي', 'sort_order': 15},
    {'key': 'croquis_land_area', 'label': 'مساحة الأرض حسب الكروكي (م²)', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'المساحة الإجمالية للأرض بالمتر المربع حسب الكروكي', 'sort_order': 16},
    {'key': 'approved_financial_area', 'label': 'المساحة المعتمدة للدراسة المالية (م²)', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يكتبها العميل فقط بعد أي استقطاعات — AI ممنوع من تعبئتها أو تعديلها', 'sort_order': 17},
    {'key': 'boundary_lengths', 'label': 'أطوال الأضلاع وحدود الأرض', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ملخص مشتق من جدول الاتجاهات — لا تُعد كتابته يدويًا إن كان الجدول مكتملًا', 'sort_order': 18},
    {'key': 'surrounding_streets', 'label': 'الشوارع المحيطة وعروضها', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'ملخص مشتق من جدول الاتجاهات — أسماء الشوارع وعروضها', 'sort_order': 19},
    {'key': 'facades_count', 'label': 'عدد الواجهات المطلة على شوارع', 'type': 'number', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'عدد الحدود المطلة على شوارع فقط (1 إلى 4) — الحد المجاور لقطعة ليس واجهة', 'sort_order': 20},
    {'key': 'facades_directions', 'label': 'اتجاهات الواجهات المطلة على شوارع', 'type': 'text', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'اتجاهات الحدود المطلة على شوارع فقط (مثل: شمالية، غربية) — لا تُكتب الاتجاهات الأربعة إلا إن كانت مطلة على أربعة شوارع', 'sort_order': 21},
    {'key': 'building_ratio_coverage', 'label': 'نسبة البناء والتغطية', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI من ملفات الأمانة: نسبة البناء، نسبة التغطية، FAR، وعدد الأدوار المرتبط بشريحة مساحة الأرض، بدون ذكر أرقام الصفحات', 'sort_order': 22},
    {'key': 'setbacks', 'label': 'الارتدادات', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI من ملفات الأمانة: الارتداد الأمامي والخلفي والجانبيان، أو يوضح أنها غير محددة في المرجع المتاح، بدون ذكر أرقام الصفحات', 'sort_order': 23},
    {'key': 'max_floors_height', 'label': 'الارتفاع أو عدد الأدوار المسموح', 'type': 'textarea', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'عدد الأدوار المسموح بها أو الحد الأقصى للارتفاع بالمتر، مع شرح شريحة الأرض إن وجدت', 'sort_order': 24},
    {'key': 'approved_floor_count', 'label': 'الأدوار المعتمدة', 'type': 'number', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'عدد الأدوار الفعلي الذي يعتمده العميل للمبنى — يكتبه العميل فقط ولا يملؤه AI', 'sort_order': 25},
    {'key': 'allowed_uses', 'label': 'الاستخدامات المسموحة', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'قائمة الاستخدامات المسموحة تنظيميًا لهذه الأرض من ملفات الأمانة وجدول التنظيم، بدون كتابة حالة السماح داخل الحقل', 'sort_order': 26},
    {'key': 'regulatory_constraints', 'label': 'القيود التنظيمية', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'القيود التنظيمية المنطبقة على الموقع والمشروع، بما فيها المواقف والمداخل والمخارج والتحميل والخدمات، بدون ذكر أرقام الصفحات', 'sort_order': 27},
    {'key': 'land_photos', 'label': 'صور الأرض (حتى 4 صور — اختياري)', 'type': 'file', 'required': False, 'section_key': 'land_croquis', 'ai_hint': 'صور فوتوغرافية للأرض من العميل مع وصف لكل صورة (لا يحللها AI)', 'sort_order': 28},
    {'key': 'land_and_building_summary', 'label': 'ملخص بيانات الأرض والاشتراطات', 'type': 'textarea', 'required': True, 'section_key': 'land_croquis', 'ai_hint': 'يملؤه AI كملخص موثق من ملفات الأمانة يشمل الارتدادات، الاستخدامات، القيود، المواقف، المداخل والمخارج، الفرص، المخاطر والتعارضات، بدون الإحالة إلى أرقام صفحات أو أماكن داخل الملفات', 'sort_order': 29},
    {'key': 'location_lat', 'label': 'خط العرض (Latitude)', 'type': 'text', 'section_key': 'location', 'ai_hint': 'خط العرض للموقع (إختياري)', 'sort_order': 31},
    {'key': 'location_lng', 'label': 'خط الطول (Longitude)', 'type': 'text', 'section_key': 'location', 'ai_hint': 'خط الطول للموقع (إختياري)', 'sort_order': 32},
    {'key': 'plot_number', 'label': 'رقم المخطط / القطعة', 'type': 'text', 'section_key': 'location', 'ai_hint': 'رقم المخطط أو القطعة', 'sort_order': 33},
    {'key': 'land_area', 'label': 'مساحة الأرض', 'type': 'text', 'section_key': 'location', 'ai_hint': 'مساحة الأرض بالمتر المربع', 'sort_order': 34},
    {'key': 'built_area', 'label': 'مساحة البناء', 'type': 'text', 'section_key': 'location', 'ai_hint': 'مساحة البناء بالمتر المربع', 'sort_order': 35},
    {'key': 'building_system', 'label': 'نظام البناء', 'type': 'text', 'section_key': 'location', 'ai_hint': 'نظام البناء والارتفاعات المسموح بها', 'sort_order': 36},
    {'key': 'infrastructure', 'label': 'البنية التحتية', 'type': 'text', 'section_key': 'location', 'ai_hint': 'مياه، كهرباء، اتصالات، إلخ', 'sort_order': 37},
    {'key': 'main_roads', 'label': 'الطرق الرئيسية المحيطة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'أسماء الطرق الرئيسية المحيطة بالمشروع وتمثل طرق الوصول إليه', 'sort_order': 38},
    {'key': 'secondary_roads', 'label': 'طرق الوصول الفرعية', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'المداخل وطرق الوصول الفرعية مع المسافة ومدة القيادة', 'sort_order': 39},
    {'key': 'nearby_landmarks', 'label': 'أهم المعالم القريبة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'قائمة المعالم القريبة مع أوقات القيادة (مثلاً: ميدان السارية - 1 دقيقة)', 'sort_order': 40},
    {'key': 'city_landmarks', 'label': 'المعالم الرئيسية في المدينة', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'أهم المعالم الرئيسية في المدينة والمناطق المحيطة', 'sort_order': 41},
    {'key': 'catchment_areas', 'label': 'مناطق نطاق التأثير', 'type': 'textarea', 'section_key': 'location', 'ai_hint': 'المناطق الرئيسية والثانوية المتأثرة بالمشروع', 'sort_order': 42},
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
    updates['updated_at'] = datetime.now().isoformat()
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
    now = datetime.now().isoformat()
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
        existing_cols = {row[1] for row in cursor.fetchall()}
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
        existing_cols = {row[1] for row in cursor.fetchall()}
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

def create_presentation(tenant_id, title, project_data=None, slides_data=None, slide_count=0):
    """Create a new presentation record."""
    conn = get_db()
    pres_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO presentations (id, tenant_id, title, project_data, slides_data, slide_count) VALUES (?, ?, ?, ?, ?, ?)',
        (
            pres_id, tenant_id, title,
            json.dumps(project_data, ensure_ascii=False) if project_data else None,
            json.dumps(slides_data, ensure_ascii=False) if slides_data else None,
            slide_count
        )
    )
    if project_data and isinstance(project_data, dict):
        draft_id = project_data.get('draft_id') or project_data.get('draftId')
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


def get_presentations(tenant_id):
    """Get all presentations for a tenant."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM presentations WHERE tenant_id = ? ORDER BY created_at DESC',
        (tenant_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def update_presentation(pres_id, tenant_id=None, **fields):
    """Update a presentation, optionally scoped to a tenant."""
    conn = get_db()
    allowed = {'title', 'project_data', 'slides_data', 'slide_count', 'status'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'project_data' in updates and updates['project_data'] and not isinstance(updates['project_data'], str):
        updates['project_data'] = json.dumps(updates['project_data'], ensure_ascii=False)
    if 'slides_data' in updates and updates['slides_data'] and not isinstance(updates['slides_data'], str):
        updates['slides_data'] = json.dumps(updates['slides_data'], ensure_ascii=False)
    updates['updated_at'] = datetime.now().isoformat()
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

def create_export(presentation_id, tenant_id, format, file_path):
    """Record an exported file."""
    conn = get_db()
    export_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO exports (id, presentation_id, tenant_id, format, file_path) VALUES (?, ?, ?, ?, ?)',
        (export_id, presentation_id, tenant_id, format, file_path)
    )
    conn.commit()
    return export_id


def get_exports(tenant_id):
    """Get all exports for a tenant."""
    conn = get_db()
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

def create_user(tenant_id, name, email, password_hash, role='employee'):
    """Create a user (employee or company admin) within a tenant."""
    conn = get_db()
    user_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO users (id, tenant_id, name, email, password_hash, role, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)',
        (user_id, tenant_id, name, email.lower(), password_hash, role)
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


def get_user_by_id(user_id):
    """Fetch a user by ID."""
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def get_users_by_tenant(tenant_id):
    """Get all users for a tenant."""
    conn = get_db()
    rows = conn.execute(
        'SELECT id, name, email, role, is_active, created_at FROM users WHERE tenant_id = ? ORDER BY created_at',
        (tenant_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def update_user(user_id, **fields):
    """Update a user."""
    conn = get_db()
    allowed = {'name', 'email', 'password_hash', 'role', 'is_active'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'email' in updates:
        updates['email'] = updates['email'].lower()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [user_id]
    conn.execute(f'UPDATE users SET {set_clause} WHERE id = ?', values)
    conn.commit()
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
    'company_settings',
    'custom_fields',
    'manage_users',
    'ai_rules',
    'training_data',
    'approvals',
    'export_files',
    'sag_admin_panel',
]

DEFAULT_PERMISSIONS = {
    'company_admin': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'company_settings': True,
        'custom_fields': True,
        'manage_users': True,
        'ai_rules': True,
        'training_data': True,
        'approvals': True,
        'export_files': True,
        'sag_admin_panel': False,
    },
    'employee': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'export_files': False,
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
    now = datetime.now().isoformat()
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
    now = datetime.now().isoformat()
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
    vals.append(datetime.now().isoformat())
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
        (*allowed.values(), datetime.now().isoformat(), tenant_id, entity_id)
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
# Invite Links
# ─────────────────────────────────────────────────────────────────────────────

def create_invite(tenant_id, email, expiry_days=7):
    """Create an invite link for an employee."""
    import secrets as _secrets
    conn = get_db()
    invite_id = str(uuid.uuid4())
    token = _secrets.token_urlsafe(32)
    from datetime import timedelta
    expires = (datetime.now() + timedelta(days=expiry_days)).isoformat()
    conn.execute(
        'INSERT INTO invite_links (id, tenant_id, email, token, expires_at) VALUES (?, ?, ?, ?, ?)',
        (invite_id, tenant_id, email.lower(), token, expires)
    )
    conn.commit()
    return token


def get_invite_by_token(token):
    """Get an invite by token. Returns None if expired or used."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM invite_links WHERE token = ? AND used_at IS NULL AND expires_at > ?",
        (token, datetime.now().isoformat())
    ).fetchone()
    return dict(row) if row else None


def mark_invite_used(token):
    """Mark an invite as used."""
    conn = get_db()
    conn.execute('UPDATE invite_links SET used_at = ? WHERE token = ?', (datetime.now().isoformat(), token))
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

PROJECT_DRAFT_STATUSES = {'draft', 'submitted', 'pending_approval', 'approved'}
SECTION_DRAFT_STATUSES = {'draft', 'approved'}


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


def save_project_draft(tenant_id, user_id, draft_data, section_statuses=None, status='draft', draft_id=None):
    """Save one unified draft per tenant actor without losing section approvals.

    ``user_id`` is an actor identifier.  Company administrators use a stable
    tenant-admin identifier supplied by the API because their JWT has no user id.
    """
    conn = get_db()
    if draft_id:
        existing = conn.execute(
            'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ? AND user_id = ?',
            (draft_id, tenant_id, user_id)
        ).fetchone()
    else:
        existing = conn.execute(
            'SELECT * FROM project_drafts WHERE tenant_id = ? AND user_id = ? ORDER BY updated_at DESC LIMIT 1',
            (tenant_id, user_id)
        ).fetchone()

    # Determine the stable draft id before serializing
    draft_id = existing['id'] if existing else (draft_id or str(uuid.uuid4()))

    requested_status = status if status in PROJECT_DRAFT_STATUSES else 'draft'
    now = datetime.now().isoformat()

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
        data_changed = save_data != old_data
        statuses_changed = statuses_json != (existing['section_statuses'] or '{}')
        old_overall_status = existing['status'] or 'draft'

        if old_overall_status in {'pending_approval', 'approved'} and (data_changed or statuses_changed):
            next_status = 'draft'
            clear_approval = True
        elif old_overall_status in {'pending_approval', 'approved'} and requested_status in {'draft', 'submitted'}:
            # Re-saving unchanged data does not undo a valid approval request/result.
            next_status = old_overall_status
            clear_approval = False
        else:
            next_status = requested_status
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
    conn.execute(
        '''INSERT INTO project_drafts
           (id, tenant_id, user_id, title, draft_data, section_statuses, status,
            revision, data_bytes, has_slides, has_maps, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (draft_id, tenant_id, user_id, title, draft_json, json.dumps(statuses, ensure_ascii=False),
         requested_status, 1, data_bytes, has_slides, has_maps, now, now)
    )
    conn.commit()
    return draft_id


def get_project_draft(tenant_id, user_id):
    """Get the latest unified draft for one tenant actor."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_drafts WHERE tenant_id = ? AND user_id = ? ORDER BY updated_at DESC LIMIT 1',
        (tenant_id, user_id)
    ).fetchone()
    return _hydrate_project_draft(row)


def get_all_project_draft_summaries(tenant_id, limit=50, offset=0):
    """Return lightweight draft metadata without hydrating project payloads."""
    conn = get_db()
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    rows = conn.execute(
        '''SELECT id, tenant_id, user_id, title, section_statuses, status, revision,
                  data_bytes, has_slides, has_maps, requested_by, requested_by_name,
                  requested_at, reviewed_by, reviewed_by_name, review_note, reviewed_at,
                  created_at, updated_at
           FROM project_drafts
           WHERE tenant_id = ?
           ORDER BY updated_at DESC
           LIMIT ? OFFSET ?''',
        (tenant_id, limit, offset)
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
        "SELECT * FROM project_drafts WHERE tenant_id = ? AND status = 'pending_approval' ORDER BY requested_at DESC",
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
    if section_status not in SECTION_DRAFT_STATUSES:
        return False
    draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
    if draft and draft.get('user_id') != user_id:
        draft = None
    if not draft:
        # A status click can occur before the first explicit Save action.
        save_project_draft(tenant_id, user_id, {}, {}, 'draft', draft_id=draft_id)
        draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
    statuses = draft.get('section_statuses', {})
    changed = statuses.get(section_key) != section_status
    statuses[section_key] = section_status
    conn = get_db()
    if changed and draft.get('status') in {'pending_approval', 'approved'}:
        next_status = 'draft'
    else:
        next_status = draft.get('status') or 'draft'
    conn.execute(
        '''UPDATE project_drafts SET section_statuses = ?, status = ?, updated_at = ? WHERE id = ?''',
        (json.dumps(statuses, ensure_ascii=False), next_status, datetime.now().isoformat(), draft['id'])
    )
    if changed and draft.get('status') in {'pending_approval', 'approved'}:
        _clear_draft_approval_fields(conn, draft['id'])
    conn.commit()
    return True


def request_project_draft_approval(tenant_id, user_id, requested_by, requested_by_name, draft_id=None):
    """Submit a draft only after every tracked section is approved."""
    draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
    if draft and draft.get('user_id') != user_id:
        draft = None
    if not draft:
        return {'error': 'draft_not_found'}
    statuses = draft.get('section_statuses', {})
    if not statuses or any(value != 'approved' for value in statuses.values()):
        return {'error': 'sections_not_approved', 'section_statuses': statuses}
    conn = get_db()
    conn.execute(
        '''UPDATE project_drafts SET status = 'pending_approval', requested_by = ?,
           requested_by_name = ?, requested_at = ?, reviewed_by = NULL,
           reviewed_by_name = NULL, review_note = NULL, reviewed_at = NULL, updated_at = ?
           WHERE id = ? AND tenant_id = ?''',
        (requested_by, requested_by_name, datetime.now().isoformat(), datetime.now().isoformat(),
         draft['id'], tenant_id)
    )
    conn.commit()
    return get_project_draft_by_id(tenant_id, draft['id'])


def review_project_draft(tenant_id, draft_id, review_status, reviewed_by, reviewed_by_name, note=None):
    """Record a tenant-scoped approval or return a draft for correction."""
    if review_status not in {'approved', 'rejected'}:
        return False
    conn = get_db()
    draft = conn.execute(
        "SELECT id FROM project_drafts WHERE id = ? AND tenant_id = ? AND status = 'pending_approval'",
        (draft_id, tenant_id)
    ).fetchone()
    if not draft:
        return False
    final_status = 'approved' if review_status == 'approved' else 'draft'
    conn.execute(
        '''UPDATE project_drafts SET status = ?, reviewed_by = ?, reviewed_by_name = ?,
           review_note = ?, reviewed_at = ?, updated_at = ? WHERE id = ?''',
        (final_status, reviewed_by, reviewed_by_name, note, datetime.now().isoformat(),
         datetime.now().isoformat(), draft_id)
    )
    conn.commit()
    return True



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
