# Request connections and startup schema lifecycle.


def get_db():
    """Get a SQLite connection for the current request context."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
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
        _migrate_draft_commit_columns(conn)
        _migrate_presentation_draft_link(conn)
        _migrate_project_file_table(conn)
        _migrate_location_fields(conn)
        _migrate_font_system(conn)
        _create_landloom_tables(conn)
        _create_landloom_role_tables(conn)
        _create_identity_tables(conn)
        _create_landloom_event_tables(conn)
        _create_platform_tables(conn)
        _create_join_requests_table(conn)
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
