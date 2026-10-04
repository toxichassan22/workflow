

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Join requests: the public "request access" form on the landing page. These
# are leads, not accounts — a row here is what the desk uses to reach out and
# then provision a tenant. Platform-level table: no tenant FK because the
# requester has no tenant yet.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _create_join_requests_table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS join_requests (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        company TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        message TEXT,
        status TEXT NOT NULL DEFAULT 'new',
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_join_requests_status ON join_requests(status, created_at DESC)')


def create_join_request(name, company, email, phone=None, message=None):
    conn = get_db()
    request_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO join_requests (id, name, company, email, phone, message)'
        ' VALUES (?, ?, ?, ?, ?, ?)',
        (request_id, name, company, email, phone or None, message or None))
    conn.commit()
    row = conn.execute(
        'SELECT * FROM join_requests WHERE id = ?', (request_id,)).fetchone()
    return dict(row)


def list_join_requests(status=None, limit=200):
    conn = get_db()
    if status:
        rows = conn.execute(
            'SELECT * FROM join_requests WHERE status = ? ORDER BY created_at DESC LIMIT ?',
            (status, limit)).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM join_requests ORDER BY created_at DESC LIMIT ?',
            (limit,)).fetchall()
    return [dict(row) for row in rows]
