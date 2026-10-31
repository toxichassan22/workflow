# Public presentation share links: creation, listing, revocation and the
# token lookup used by the read-only viewer. The raw token is stored so the
# owner can reveal and re-copy an existing link; every read is tenant-scoped.

import uuid


def _share_timestamp():
    return _utcnow().strftime('%Y-%m-%d %H:%M:%S')


def create_presentation_share(tenant_id, presentation_id, token,
                              password_hash=None, expires_at=None, created_by=None):
    conn = get_db()
    share_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO presentation_shares '
        '(id, tenant_id, presentation_id, token, password_hash, expires_at, created_by, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (share_id, tenant_id, presentation_id, token, password_hash,
         expires_at, created_by, _share_timestamp()),
    )
    conn.commit()
    return get_presentation_share(tenant_id, share_id)


def get_presentation_share(tenant_id, share_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM presentation_shares WHERE id = ? AND tenant_id = ?',
        (share_id, tenant_id),
    ).fetchone()
    return dict(row) if row else None


def list_presentation_shares(tenant_id, presentation_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM presentation_shares WHERE tenant_id = ? AND presentation_id = ? '
        'ORDER BY created_at DESC',
        (tenant_id, presentation_id),
    ).fetchall()
    return [dict(row) for row in rows]


def get_presentation_share_by_token(token):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM presentation_shares WHERE token = ?',
        (str(token or ''),),
    ).fetchone()
    return dict(row) if row else None


def revoke_presentation_share(tenant_id, presentation_id, share_id):
    conn = get_db()
    cursor = conn.execute(
        'UPDATE presentation_shares SET revoked_at = ? '
        'WHERE id = ? AND tenant_id = ? AND presentation_id = ? AND revoked_at IS NULL',
        (_share_timestamp(), share_id, tenant_id, presentation_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def touch_presentation_share(share_id):
    conn = get_db()
    conn.execute(
        'UPDATE presentation_shares SET view_count = view_count + 1, last_viewed_at = ? WHERE id = ?',
        (_share_timestamp(), share_id),
    )
    conn.commit()
