

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

    # ISS-005: fixed-window attempt counters with a temporary lock, shared by
    # the login, registration and invite endpoints. Kept in the database so
    # every worker and process enforces the same counters. Timestamps are naive
    # UTC ISO strings, like the rest of the schema.
    conn.execute('''CREATE TABLE IF NOT EXISTS rate_limit_buckets (
        bucket_key TEXT PRIMARY KEY,
        attempts INTEGER NOT NULL DEFAULT 0,
        reset_at TEXT,
        locked_until TEXT,
        updated_at TEXT
    )''')

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
        # The company admin acts through the tenant-direct identity — its
        # writes carry the 'tenant-admin:<id>' actor id, and the linked primary
        # user id is the same person. Employees with both approvals are still
        # flagged: holding both permissions is exactly what this check watches.
        admin_row = conn.execute(
            'SELECT primary_user_id FROM tenants WHERE id = ?', (tenant_id,)
        ).fetchone()
        admin_ids = {f'tenant-admin:{tenant_id}'}
        if admin_row and admin_row['primary_user_id']:
            admin_ids.add(admin_row['primary_user_id'])
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
            # The tenant-direct company admin (sentinel actor or its linked
            # primary user) is exempt — the check exists to catch employees
            # editing without post_approval_edit.
            if str(item['user_id'] or '').startswith('tenant-admin:'):
                continue
            holder = conn.execute(
                'SELECT 1 FROM tenants WHERE id = ? AND primary_user_id = ?',
                (tenant_id, item['user_id'])
            ).fetchone()
            if holder:
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
    """Guard kept for callers: the only company admin is the primary user.

    Under the three-level model there is exactly one admin — the primary row
    linked from ``tenants.primary_user_id`` — and it is never deletable or
    deactivatable through user management, so this now just answers whether
    the target is that row.
    """
    return is_primary_company_admin(tenant_id, user_id)


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


# ── ISS-005: attempt counters with temporary lockout ─────────────────────────
# Buckets are plain strings ("login:id:mail@x", "register:ip:<ip>")
# so every endpoint picks its own subject. All timestamps are naive-UTC ISO text;
# lexicographic comparison on them is a chronological comparison.

def rate_limit_status(bucket_key, now=None):
    """Seconds the bucket stays locked; 0 when the key may proceed."""
    now_iso = (now or _utcnow()).isoformat()
    conn = get_db()
    row = conn.execute(
        'SELECT locked_until FROM rate_limit_buckets WHERE bucket_key = ?',
        (bucket_key,),
    ).fetchone()
    if not row or not row['locked_until'] or row['locked_until'] <= now_iso:
        return 0.0
    try:
        locked = datetime.fromisoformat(row['locked_until'])
        current = datetime.fromisoformat(now_iso)
        return max(0.0, (locked - current).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def rate_limit_hit(bucket_key, max_attempts, window_seconds, lock_seconds, now=None):
    """Record one attempt atomically; return lock seconds remaining, 0 if allowed.

    A single UPSERT keeps check-and-increment atomic across threads, workers and
    processes. While ``locked_until`` lies in the future the counters stay
    untouched — hammering a locked bucket does not extend the lock. An expired
    window restarts the counter; crossing ``max_attempts`` inside an open window
    sets the lock.
    """
    now_dt = now or _utcnow()
    now_iso = now_dt.isoformat()
    reset_iso = (now_dt + timedelta(seconds=window_seconds)).isoformat()
    lock_iso = (now_dt + timedelta(seconds=lock_seconds)).isoformat()
    max_attempts = max(1, int(max_attempts))
    conn = get_db()
    conn.execute(
        '''INSERT INTO rate_limit_buckets (bucket_key, attempts, reset_at, locked_until, updated_at)
           VALUES (?, 1, ?, NULL, ?)
           ON CONFLICT(bucket_key) DO UPDATE SET
             attempts = CASE
               WHEN rate_limit_buckets.locked_until IS NOT NULL
                    AND rate_limit_buckets.locked_until > ? THEN rate_limit_buckets.attempts
               WHEN rate_limit_buckets.reset_at IS NOT NULL
                    AND rate_limit_buckets.reset_at > ? THEN rate_limit_buckets.attempts + 1
               ELSE 1 END,
             reset_at = CASE
               WHEN rate_limit_buckets.locked_until IS NOT NULL
                    AND rate_limit_buckets.locked_until > ? THEN rate_limit_buckets.reset_at
               WHEN rate_limit_buckets.reset_at IS NOT NULL
                    AND rate_limit_buckets.reset_at > ? THEN rate_limit_buckets.reset_at
               ELSE ? END,
             locked_until = CASE
               WHEN rate_limit_buckets.locked_until IS NOT NULL
                    AND rate_limit_buckets.locked_until > ? THEN rate_limit_buckets.locked_until
               WHEN rate_limit_buckets.reset_at IS NOT NULL
                    AND rate_limit_buckets.reset_at > ?
                    AND rate_limit_buckets.attempts + 1 > ? THEN ?
               ELSE NULL END,
             updated_at = ?''',
        (bucket_key, reset_iso, now_iso,
         now_iso, now_iso, now_iso, now_iso, reset_iso,
         now_iso, now_iso, max_attempts, lock_iso, now_iso),
    )
    row = conn.execute(
        'SELECT locked_until FROM rate_limit_buckets WHERE bucket_key = ?',
        (bucket_key,),
    ).fetchone()
    conn.commit()
    if not row or not row['locked_until'] or row['locked_until'] <= now_iso:
        return 0.0
    try:
        return max(0.0, (datetime.fromisoformat(row['locked_until']) - now_dt).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def rate_limit_reset(bucket_key):
    """Drop the bucket — a successful authentication should not carry a debt."""
    conn = get_db()
    conn.execute('DELETE FROM rate_limit_buckets WHERE bucket_key = ?', (bucket_key,))
    conn.commit()


def rate_limit_cleanup(now=None):
    """Forget buckets whose window and lock both expired; called by housekeeping."""
    now_iso = (now or _utcnow()).isoformat()
    conn = get_db()
    cursor = conn.execute(
        'DELETE FROM rate_limit_buckets WHERE (locked_until IS NULL OR locked_until <= ?)'
        ' AND (reset_at IS NULL OR reset_at <= ?)',
        (now_iso, now_iso),
    )
    conn.commit()
    return {'removed': cursor.rowcount}


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

# Fields that must exist before the account is activated.
COMPANY_ACTIVATION_REQUIRED_FIELDS = ('legal_name', 'tax_number', 'cr_number', 'country')


def tenant_activation_checklist(tenant):
    """Return the missing pieces blocking activation for a tenant row.

    ``missing`` lists stable keys the UI can label: a profile field name.
    """
    tenant = tenant or {}
    missing = [field for field in COMPANY_ACTIVATION_REQUIRED_FIELDS
               if not str(tenant.get(field) or '').strip()]
    return {'complete': not missing, 'missing': missing}


def set_tenant_active(tenant_id, is_active, actor_id=None, actor_name=None, reason=None):
    """Flip the tenant's active flag with the activation gate and audit trail.

    Activating requires a complete company file (legal profile);
    the first activation stamps ``activated_by``/``activated_at``.
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
        _revoke_password_setup_tokens(conn, tenant_id=tenant_id)
    conn.commit()
    return get_tenant_by_id(tenant_id)
