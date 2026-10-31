def _migrate_presentation_shares(conn):
    """Public read-only share links for a presentation.

    The token is the credential, so it is random and unique. A share may carry a
    password hash and an explicit expiry; revoking it keeps the row for audit
    while refusing every later read.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS presentation_shares (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            presentation_id TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            expires_at TEXT,
            revoked_at TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            last_viewed_at TEXT,
            view_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_presentation_shares_presentation '
        'ON presentation_shares(presentation_id)'
    )
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_presentation_shares_token '
        'ON presentation_shares(token)'
    )
