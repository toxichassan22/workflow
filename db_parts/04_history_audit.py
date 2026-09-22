


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# History and audit: presentation version snapshots, the per-slide edit
# log, the tenant change log with recent-activity reads, and the immutable
# audit-event stream with CSV export.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
# AuditEvent: Immutable unified audit log (Landloom spec sections 6, 15, 18).
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
