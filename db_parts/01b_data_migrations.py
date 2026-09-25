


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data migrations and fixups run by init_db() on every boot:
# column adds, FK rebuilds and the field/section repair passes that keep
# older databases aligned with the current schema.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
        if 'section_key' not in existing_cols:
            conn.execute("ALTER TABLE generation_approvals ADD COLUMN section_key TEXT")
            print("[DB MIGRATION] Added generation_approvals column: section_key")
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
        ('presentation_approvals', (('request_hash', 'TEXT'),)),
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


def _migrate_user_assignments_cleanup(conn):
    """Drop assignment rows whose user no longer exists.

    ``user_assignments.user_id`` carries no foreign key, so users removed
    before ``delete_user`` learned to sweep left orphan rows behind — an
    orphan approver kept the one-approver slot on its drafts and ghost
    editors still counted toward the five-editor cap."""
    try:
        conn.execute(
            'DELETE FROM user_assignments WHERE user_id NOT IN (SELECT id FROM users)')
        conn.commit()
    except Exception as e:
        print(f"[DB MIGRATION ERR] {e}")
