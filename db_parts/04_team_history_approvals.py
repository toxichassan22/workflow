

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


def _change_detail_items(details):
    """Detail items as stored: readable strings, or structured dicts kept as-is.

    change_tracking emits dicts {group, path, field, old, new, kind} so the log
    page can render a grouped before/after; plain strings stay untouched.
    """
    items = []
    for item in (details or []):
        if isinstance(item, dict):
            cleaned = {str(k): v for k, v in item.items()
                       if v is not None and str(v).strip() != ''}
            if cleaned:
                items.append(cleaned)
        elif str(item or '').strip():
            items.append(str(item).strip())
    return items


def log_change(tenant_id, target_type, target_id, user_id, user_name, action,
               summary='', details=None, source='manual', revision_id=None, previous_revision_id=None):
    """Record one change with the individual differences it produced.

    ``details`` is a list of human-readable Arabic lines — or structured dicts —
    stored as JSON so the reader can show them one per line instead of a single
    sentence. Presentation events such as approval/export link to the current
    revision without creating a content revision.
    Explicit links must refer to this tenant's same presentation.
    """
    if target_type not in CHANGE_TARGETS or not target_id:
        return None
    lines = _change_detail_items(details)
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


def _revoke_password_setup_tokens(conn, user_id=None, tenant_id=None):
    """Consume every unused password-setup link for a user or a whole company.

    Runs when the account is deactivated: a link issued before the
    deactivation must not be able to reactivate the user afterwards.
    """
    now = _utcnow().isoformat()
    if user_id:
        conn.execute(
            'UPDATE password_setup_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL',
            (now, user_id)
        )
    if tenant_id:
        conn.execute(
            'UPDATE password_setup_tokens SET used_at = ? WHERE tenant_id = ? AND used_at IS NULL',
            (now, tenant_id)
        )


def complete_password_setup(raw_token, password_hash):
    """Set the password for a valid setup token and consume it atomically."""
    import hashlib as _hashlib
    conn = get_db()
    token_hash = _hashlib.sha256(str(raw_token or '').encode('utf-8')).hexdigest()
    token = conn.execute(
        'SELECT * FROM password_setup_tokens WHERE token_hash = ?',
        (token_hash,)
    ).fetchone()
    if not token:
        return None
    used_at = _utcnow().isoformat()
    try:
        claimed = conn.execute(
            '''UPDATE password_setup_tokens SET used_at = ?
               WHERE id = ? AND used_at IS NULL AND expires_at > ?''',
            (used_at, token['id'], used_at)
        )
        if claimed.rowcount != 1:
            conn.rollback()
            return None
        conn.execute(
            '''UPDATE users
               SET password_hash = ?, require_password_change = 0, is_active = 1,
                   session_version = COALESCE(session_version, 0) + 1
               WHERE id = ? AND tenant_id = ?''',
            (password_hash, token['user_id'], token['tenant_id'])
        )
        conn.execute(
            '''UPDATE tenants
               SET password_hash = ?, require_password_change = 0,
                   session_version = COALESCE(session_version, 0) + 1
               WHERE id = ? AND primary_user_id = ?''',
            (password_hash, token['tenant_id'], token['user_id'])
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        'tenant_id': token['tenant_id'],
        'user_id': token['user_id'],
    }


# ── Session revocation ────────────────────────────────────────────────────────
# Session JWTs carry the identity's ``session_version`` (``sv``) plus a unique
# ``jti``. A password write bumps the version so every earlier token goes stale;
# logout records the jti in ``revoked_tokens`` until the token's natural exp.


def get_session_version(scope, row_id):
    """Current session epoch for an identity ('user' or 'tenant'); missing rows read 0."""
    if not row_id:
        return 0
    table = 'users' if scope == 'user' else 'tenants'
    conn = get_db()
    try:
        row = conn.execute(
            f'SELECT session_version FROM {table} WHERE id = ?', (row_id,)
        ).fetchone()
    except Exception:
        return 0
    if not row:
        return 0
    try:
        return int(row['session_version'] or 0)
    except (TypeError, ValueError):
        return 0


def bump_session_version(scope, row_id):
    """Invalidate every outstanding session token for this identity."""
    if not row_id:
        return
    table = 'users' if scope == 'user' else 'tenants'
    conn = get_db()
    conn.execute(
        f'UPDATE {table} SET session_version = COALESCE(session_version, 0) + 1 WHERE id = ?',
        (row_id,)
    )
    conn.commit()


def revoke_token_jti(jti, tenant_id, expires_at):
    """Denylist a single token id until its natural expiry (logout)."""
    if not jti:
        return
    conn = get_db()
    now = int(datetime.now(timezone.utc).timestamp())
    conn.execute('DELETE FROM revoked_tokens WHERE expires_at < ?', (now,))
    conn.execute(
        'INSERT OR IGNORE INTO revoked_tokens (jti, tenant_id, expires_at) VALUES (?, ?, ?)',
        (str(jti), str(tenant_id or ''), int(expires_at or now))
    )
    conn.commit()


def is_token_revoked(jti):
    """True when this token id was revoked before its exp."""
    if not jti:
        return False
    conn = get_db()
    row = conn.execute(
        'SELECT 1 FROM revoked_tokens WHERE jti = ?', (str(jti),)
    ).fetchone()
    return row is not None


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


# Training categories each AI surface accepts. 'general' and 'chat' entries
# reach every surface. A surface absent from the map — or None — hears every
# active entry (slides mix text and visuals, so they take everything).
_TRAINING_SURFACE_CATEGORIES = {
    'design':  {'general', 'chat', 'design', 'style', 'image_reference'},
    'content': {'general', 'chat', 'content'},
}


def get_training_context(tenant_id, max_entries=20, max_chars=12000, surface=None):
    """Build bounded, tenant-only context for AI calls.

    ``surface`` optionally scopes which training entries apply: a 'content'
    surface hears general/chat and content entries, a 'design' surface hears
    the visual categories plus anything carrying a reference image. Entries
    with no category count as 'general'.

    Image files themselves remain in tenant storage.  Only the tenant's saved
    description and analysis are supplied to the model as contextual text.
    """
    entries = get_training_data(tenant_id, active_only=True)
    allowed = _TRAINING_SURFACE_CATEGORIES.get(surface)
    if allowed is not None:
        if surface == 'design':
            entries = [e for e in entries
                       if (e.get('category') or 'general') in allowed
                       or e.get('image_path') or e.get('image_analysis')]
        else:
            entries = [e for e in entries if (e.get('category') or 'general') in allowed]
    entries = entries[:max_entries]
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

def _final_gate_reachable(tenant_id, presentation):
    """Whether the presentation's linked draft belongs to the formal gate.

    A draft already inside the lifecycle (a gate state or one that can enter
    ``final_approval_pending``) must be approved through ``final_file_approvals``
    — the legacy table cannot drive it, so a legacy request on such a file is
    refused rather than stamped in parallel.
    """
    draft_id = (presentation or {}).get('draft_id')
    if not draft_id:
        return False
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return False
    norm = normalize_proposal_status(draft.get('status'))
    if norm in {'generation_approval_pending', 'generating', 'generated_draft',
                'final_approval_pending', 'approved'}:
        return True
    return can_transition_proposal_status(norm, 'final_approval_pending')


def create_approval(presentation_id, tenant_id, requested_by, requested_by_name):
    """Create an approval request for a presentation.

    ISS-027: the request pins the content it sends (``request_hash``), and a
    presentation whose draft belongs to the formal lifecycle must go through
    the final-file gate instead — the legacy table only governs files outside
    that flow.
    """
    conn = get_db()
    pres = conn.execute(
        'SELECT draft_id, status, project_data, slides_data FROM presentations WHERE id = ? AND tenant_id = ?',
        (presentation_id, tenant_id),
    ).fetchone()
    if not pres:
        return {'error': 'presentation_not_found'}
    if _final_gate_reachable(tenant_id, dict(pres)):
        return {'error': 'use_final_approval_gate'}
    approval_id = str(uuid.uuid4())
    conn.execute(
        'INSERT INTO presentation_approvals (id, presentation_id, tenant_id, requested_by, requested_by_name, status, request_hash) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (approval_id, presentation_id, tenant_id, requested_by, requested_by_name, 'pending',
         _presentation_review_hash(dict(pres)))
    )
    conn.execute("UPDATE presentations SET status = 'pending_approval' WHERE id = ?", (presentation_id,))
    conn.commit()
    return {'approval_id': approval_id}


def get_pending_approvals(tenant_id, accessible_draft_ids=None):
    """Get all pending approval requests for a tenant.

    ``accessible_draft_ids`` (ISS-014) keeps a project-scoped member from
    seeing approvals whose presentation links a draft outside their scope;
    presentations with no draft stay visible, matching the list route."""
    conn = get_db()
    query = '''SELECT pa.*, p.title as pres_title, p.slide_count
           FROM presentation_approvals pa
           JOIN presentations p ON pa.presentation_id = p.id
           WHERE pa.tenant_id = ? AND pa.status = 'pending' '''
    params = [tenant_id]
    if accessible_draft_ids is not None:
        ids = [str(i) for i in accessible_draft_ids]
        if ids:
            query += ' AND (p.draft_id IS NULL OR p.draft_id IN (' + ','.join('?' * len(ids)) + '))'
            params.extend(ids)
        else:
            query += ' AND p.draft_id IS NULL'
    query += ' ORDER BY pa.created_at DESC'
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_approval(approval_id, tenant_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM presentation_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    return dict(row) if row else None


def review_approval(approval_id, tenant_id, status, reviewed_by, reviewed_by_name,
                    note=None, allow_self=False):
    """Approve or reject a presentation — the final gate's invariants (ISS-027).

    Only a pending row may be decided, the conditional UPDATE makes the decide
    itself race-safe, the requester cannot self-decide unless a company admin
    (``allow_self``), rejection needs a written reason, approval verifies the
    file still matches the reviewed content, and a file whose draft entered the
    formal lifecycle must be decided through the final-file gate instead.
    """
    if status not in {'approved', 'rejected'}:
        return {'error': 'invalid_decision'}
    clean_note = str(note or '').strip()
    if status == 'rejected' and not clean_note:
        return {'error': 'note_required'}
    conn = get_db()
    approval = conn.execute('SELECT * FROM presentation_approvals WHERE id = ? AND tenant_id = ?', (approval_id, tenant_id)).fetchone()
    if not approval:
        return {'error': 'approval_not_found'}
    if approval['status'] != 'pending':
        return {'error': 'approval_not_pending'}
    if not allow_self and approval['requested_by'] \
            and str(approval['requested_by']) == str(reviewed_by):
        return {'error': 'self_approval_not_allowed'}
    pres = conn.execute(
        'SELECT draft_id, status, project_data, slides_data FROM presentations WHERE id = ? AND tenant_id = ?',
        (approval['presentation_id'], tenant_id)).fetchone()
    if pres is not None and _final_gate_reachable(tenant_id, dict(pres)):
        return {'error': 'use_final_approval_gate'}
    if status == 'approved' and pres is not None:
        request_hash = approval['request_hash'] if 'request_hash' in approval.keys() else None
        if request_hash and _presentation_review_hash(dict(pres)) != request_hash:
            return {'error': 'content_changed'}
    updated = conn.execute(
        '''UPDATE presentation_approvals SET status = ?, reviewed_by = ?, reviewed_by_name = ?,
           review_note = ?, reviewed_at = datetime('now')
           WHERE id = ? AND status = 'pending' ''',
        (status, reviewed_by, reviewed_by_name, clean_note or None, approval_id)
    )
    if updated.rowcount != 1:
        return {'error': 'approval_not_pending'}
    pres_status = 'approved' if status == 'approved' else 'draft'
    conn.execute('UPDATE presentations SET status = ? WHERE id = ? AND tenant_id = ?',
                 (pres_status, approval['presentation_id'], tenant_id))
    conn.commit()
    return {'status': status}


def get_approval_status(presentation_id, tenant_id=None):
    """Get the latest approval status for a presentation."""
    conn = get_db()
    if tenant_id:
        row = conn.execute(
            'SELECT * FROM presentation_approvals WHERE presentation_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 1',
            (presentation_id, tenant_id)
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT * FROM presentation_approvals WHERE presentation_id = ? ORDER BY created_at DESC LIMIT 1',
            (presentation_id,)
        ).fetchone()
    return dict(row) if row else None
