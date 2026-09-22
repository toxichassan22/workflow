


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
