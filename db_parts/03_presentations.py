


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Slide templates, presentations and exports: per-tenant slide
# template rows, the presentation store with content-hash revision commits
# (PresentationRevisionConflict), and the exports ledger.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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

_PRESENTATION_UNSET = object()
# Ignore only presentation-independent UI bookkeeping, not project facts/media.
_PRESENTATION_BOOKKEEPING_KEYS = {'designerChat', 'pageDrafts', 'sectionStatuses'}


class PresentationRevisionConflict(Exception):
    """The supplied base revision is stale. No state or history was committed."""

    def __init__(self, expected_revision, current_revision):
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__(f'Presentation revision conflict: expected {expected_revision}, current {current_revision}')


def _presentation_json(value, kind, strict=False):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            if strict:
                raise ValueError(f'Invalid presentation {kind} JSON')
    if value is None:
        value = [] if kind == 'slides_data' else {}
    if strict and not isinstance(value, list if kind == 'slides_data' else dict):
        raise ValueError(f'Invalid presentation {kind}')
    return value


def _presentation_content_hash(state):
    project = _presentation_json(state.get('project_data'), 'project_data')
    if isinstance(project, dict):
        project = {key: value for key, value in project.items() if key not in _PRESENTATION_BOOKKEEPING_KEYS}
    content = [state.get('title'), _presentation_json(state.get('slides_data'), 'slides_data'), project]
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _presentation_revision_metadata(row, legacy=False):
    item = dict(row)
    item['legacy'] = legacy
    item['snapshot_kind'] = 'legacy-slides' if legacy else 'full'
    item['details'] = _json_list(item.get('details'))
    if legacy:
        item.update(revision=None, source='manual', summary='نسخة قديمة للشرائح فقط',
                    previous_revision_id=None, restored_from_revision_id=None,
                    change_log_id=None, title=None, project_data=None, draft_id=None, status=None)
        slides = _presentation_json(item.get('slides_data'), 'slides_data')
        item['slide_count'] = len(slides) if isinstance(slides, list) else 0
    return item


def get_presentation_revisions(presentation_id, tenant_id, limit=200):
    """Tenant-scoped metadata, newest full revisions followed by legacy backups."""
    if not tenant_id:
        return []
    conn = get_db()
    limit = max(1, min(int(limit or 200), 500))
    rows = conn.execute('''SELECT r.id, r.presentation_id, r.revision, r.title, r.slide_count,
        r.user_id, r.user_name, r.source, r.action, r.summary, r.details,
        r.previous_revision_id, r.restored_from_revision_id, r.change_log_id, r.created_at
        FROM presentation_revisions r JOIN presentations p ON p.id = r.presentation_id
        WHERE p.id = ? AND p.tenant_id = ? ORDER BY r.revision DESC LIMIT ?''',
        (presentation_id, tenant_id, limit)).fetchall()
    entries = [_presentation_revision_metadata(row) for row in rows]
    if len(entries) < limit:
        legacy = conn.execute('''SELECT v.* FROM presentation_versions v
            JOIN presentations p ON p.id = v.presentation_id
            WHERE p.id = ? AND p.tenant_id = ? ORDER BY v.created_at DESC, v.id DESC LIMIT ?''',
            (presentation_id, tenant_id, limit - len(entries))).fetchall()
        for row in legacy:
            item = _presentation_revision_metadata(row, legacy=True)
            for key in ('slides_data', 'project_data', 'draft_id', 'status'):
                item.pop(key, None)
            entries.append(item)
    return entries


def get_presentation_revision(presentation_id, version_id, tenant_id):
    """Return immutable full contents or an explicitly labeled slides-only backup.

    JSON columns remain serialized, matching get_presentation()/legacy callers.
    Version IDs are UUIDs, while revision numbers are per-presentation integers.
    """
    if not tenant_id:
        return None
    conn = get_db()
    for table, legacy in (('presentation_revisions', False), ('presentation_versions', True)):
        row = conn.execute(f'''SELECT r.* FROM {table} r
            JOIN presentations p ON p.id = r.presentation_id
            WHERE p.id = ? AND p.tenant_id = ? AND r.id = ?''',
            (presentation_id, tenant_id, version_id)).fetchone()
        if row:
            return _presentation_revision_metadata(row, legacy=legacy)
    return None


def _insert_presentation_revision(conn, state, revision, *, user_id, user_name, source,
                                  action, summary, details, previous_id=None, restored_from=None):
    """Transaction-internal append only. Never calls a committing legacy helper."""
    version_id, change_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = _utcnow().isoformat()
    details_json = json.dumps(details, ensure_ascii=False)
    slides = _presentation_json(state.get('slides_data'), 'slides_data')
    slide_count = len(slides) if isinstance(slides, list) else int(state.get('slide_count') or 0)
    conn.execute('''INSERT INTO presentation_revisions
        (id, presentation_id, revision, title, project_data, slides_data, slide_count,
         draft_id, status, content_hash, user_id, user_name, source, action, summary, details,
         previous_revision_id, restored_from_revision_id, change_log_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (version_id, state['id'], revision, state['title'], state.get('project_data'),
         state.get('slides_data'), slide_count, state.get('draft_id'), state.get('status'),
         _presentation_content_hash(state), user_id, user_name, source, action, summary,
         details_json, previous_id, restored_from, change_id, now))
    conn.execute('''INSERT INTO change_log
        (id, tenant_id, target_type, target_id, user_id, user_name, source, action, summary,
         details, created_at, revision_id, previous_revision_id)
        VALUES (?, ?, 'presentation', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (change_id, state['tenant_id'], state['id'], user_id, user_name, source, action,
         summary, details_json, now, version_id, previous_id))
    return version_id


def _transform_presentation_snapshot(state, transform):
    if transform is None:
        return state
    transformed = transform(dict(state))
    if not isinstance(transformed, dict):
        raise ValueError('snapshot_transform must return a presentation state dict')
    result = dict(state)
    # Asset publication cannot change identity, workflow approval or project linkage.
    for key in ('project_data', 'slides_data'):
        if key in transformed:
            result[key] = json.dumps(_presentation_json(transformed[key], key, strict=True),
                                     ensure_ascii=False, allow_nan=False)
    return result


def commit_presentation_revision(tenant_id, presentation_id=None, *,
                                 title=_PRESENTATION_UNSET, project_data=_PRESENTATION_UNSET,
                                 slides_data=_PRESENTATION_UNSET, draft_id=_PRESENTATION_UNSET,
                                 status=_PRESENTATION_UNSET, expected_revision=None,
                                 user_id=None, user_name=None, source='manual', action='edit',
                                 summary='', details=None, restore_version_id=None,
                                 snapshot_transform=None, creation_key=None):
    """Atomically create/update/restore one identity, full snapshot and readable history.

    Expected revision is an integer (zero for an unversioned legacy identity).
    None is reserved for trusted server/legacy integrations that cannot supply it.
    Stale writes fail even when their content would be a no-op. Restore always
    appends, keeps the current draft link, resets approval, and never edits a draft.
    Ordinary identical saves do not add history, including bookkeeping-only edits.
    All JSON is snapshotted, even ignored bookkeeping. Legacy helpers remain intact.
    snapshot_transform receives a copied raw DB state and returns asset-frozen
    project_data/slides_data (serialized or decoded). It runs on current and next
    states under the write lock and must be deterministic and never commit the DB.
    This helper owns the connection transaction: call without pending writes.
    creation_key is an optional tenant-scoped create idempotency token. Reusing
    it returns the existing current identity unchanged, even after later edits.
    """
    if not tenant_id:
        raise ValueError('tenant_id is required')
    if expected_revision is not None:
        if isinstance(expected_revision, bool) or not str(expected_revision).isdigit():
            raise ValueError('expected_revision must be a nonnegative integer')
        expected_revision = int(expected_revision)
    if source not in CHANGE_SOURCES:
        raise ValueError('Invalid presentation change source')
    created = presentation_id is None
    if creation_key is not None:
        if not created or not isinstance(creation_key, str) or not creation_key.strip() or len(creation_key) > 255:
            raise ValueError('creation_key requires a new identity and a nonempty token up to 255 characters')
    if created and restore_version_id:
        raise ValueError('Restoration requires a presentation identity')
    if created and expected_revision not in (None, 0):
        raise PresentationRevisionConflict(expected_revision, 0)
    conn = get_db()
    try:
        if created:
            presentation_id = str(uuid.uuid4())
            if title is _PRESENTATION_UNSET or not isinstance(title, str) or not title.strip():
                raise ValueError('Presentation title is required')
            inserted = conn.execute('''INSERT INTO presentations (id, tenant_id, title, creation_key)
                VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id, creation_key) DO NOTHING''',
                (presentation_id, tenant_id, title, creation_key))
            if inserted.rowcount == 0:
                existing = dict(conn.execute('SELECT * FROM presentations WHERE tenant_id = ? AND creation_key = ?',
                                             (tenant_id, creation_key)).fetchone())
                conn.commit()
                return {'presentation_id': existing['id'], 'revision': int(existing.get('revision') or 0),
                        'version_id': existing.get('current_revision_id'), 'changed': False,
                        'created': False, 'presentation': existing}
        else:
            # A write before the read serializes writers on SQLite AND Postgres.
            # Unlike read-then-CAS, SQLite cannot fail a read snapshot upgrade here.
            locked = conn.execute('''UPDATE presentations SET revision = revision
                WHERE id = ? AND tenant_id = ?''', (presentation_id, tenant_id))
            if locked.rowcount != 1:
                raise LookupError('Presentation not found')
        current = dict(conn.execute('SELECT * FROM presentations WHERE id = ? AND tenant_id = ?',
                                    (presentation_id, tenant_id)).fetchone())
        revision = int(current.get('revision') or 0)
        if expected_revision is not None and expected_revision != revision:
            raise PresentationRevisionConflict(expected_revision, revision)
        if not created:
            current = _transform_presentation_snapshot(current, snapshot_transform)
        target = None
        if restore_version_id:
            target = get_presentation_revision(presentation_id, restore_version_id, tenant_id)
            if not target:
                raise LookupError('Presentation revision not found')
            # Legacy backups never claimed to store a title or project facts.
            slides_data = target['slides_data']
            title = current['title'] if target['legacy'] else target['title']
            project_data = current['project_data'] if target['legacy'] else target['project_data']
            draft_id, status = current.get('draft_id'), 'draft'
            action = 'restore'
        state = dict(current)
        for key, value in (('title', title), ('project_data', project_data),
                           ('slides_data', slides_data), ('draft_id', draft_id), ('status', status)):
            if value is _PRESENTATION_UNSET:
                continue
            if key in ('slides_data', 'project_data'):
                value = json.dumps(_presentation_json(value, key, strict=True), ensure_ascii=False, allow_nan=False)
            if key == 'title' and (not isinstance(value, str) or not value.strip()):
                raise ValueError('Presentation title is required')
            state[key] = value
        if created and draft_id is _PRESENTATION_UNSET:
            project = _presentation_json(state.get('project_data'), 'project_data', strict=True)
            state['draft_id'] = project.get('draft_id') or project.get('draftId')
        state = _transform_presentation_snapshot(state, snapshot_transform)
        slides = _presentation_json(state.get('slides_data'), 'slides_data', strict=True)
        state['slide_count'] = len(slides)
        changed = created or bool(target) or _presentation_content_hash(current) != _presentation_content_hash(state)
        if changed and not created and status is _PRESENTATION_UNSET and current.get('status') in ('approved', 'pending_approval'):
            state['status'] = 'draft'
        previous_id = current.get('current_revision_id')
        if not created:
            previous = conn.execute('SELECT content_hash FROM presentation_revisions WHERE id = ?',
                                    (previous_id,)).fetchone() if previous_id else None
            # Preserve the actual current state even if an unmigrated legacy caller
            # changed it since the last revision-aware save. Never credit that to this actor.
            if not previous or previous['content_hash'] != _presentation_content_hash(current):
                if previous:
                    revision += 1
                previous_id = _insert_presentation_revision(
                    conn, current, revision, user_id=None, user_name=None, source='system',
                    action='baseline', summary='حفظ الحالة السابقة للعرض', details=[],
                    previous_id=previous_id)
        version_id = previous_id
        if changed:
            revision += 1
            lines = _change_detail_items(details)
            if not lines:
                from change_tracking import describe_slide_changes, describe_draft_changes
                lines = describe_slide_changes(
                    _presentation_json(current.get('slides_data'), 'slides_data'), slides)
                lines += describe_draft_changes(
                    _presentation_json(current.get('project_data'), 'project_data'),
                    _presentation_json(state.get('project_data'), 'project_data'))
                if current.get('title') != state['title']:
                    lines.insert(0, f'عنوان العرض: من «{current.get("title") or ""}» إلى «{state["title"]}»')
            summary = str(summary or '').strip() or (
                'استعادة نسخة قديمة للشرائح فقط' if target and target['legacy'] else
                'استعادة مراجعة العرض' if target else 'إنشاء العرض' if created else 'تعديل العرض')
            record_action = action if action not in ('create', 'edit') else ('إنشاء العرض' if created else action)
            version_id = _insert_presentation_revision(
                conn, state, revision, user_id=user_id, user_name=user_name, source=source,
                action=record_action, summary=summary, details=lines,
                previous_id=previous_id, restored_from=restore_version_id)
        # No-op saves may update bookkeeping/status but never mutate a past snapshot.
        updated_at = _utcnow().isoformat() if changed else current.get('updated_at')
        conn.execute('''UPDATE presentations SET title = ?, project_data = ?, slides_data = ?,
            slide_count = ?, draft_id = ?, status = ?, revision = ?, current_revision_id = ?, updated_at = ?
            WHERE id = ? AND tenant_id = ?''',
            (state['title'], state.get('project_data'), state.get('slides_data'), state['slide_count'],
             state.get('draft_id'), state.get('status'), revision, version_id, updated_at,
             presentation_id, tenant_id))
        if created and state.get('draft_id'):
            conn.execute('UPDATE map_images SET presentation_id = ? WHERE tenant_id = ? AND presentation_id = ?',
                         (presentation_id, tenant_id, f"draft_{state['draft_id']}"))
        result = dict(conn.execute('SELECT * FROM presentations WHERE id = ? AND tenant_id = ?',
                                  (presentation_id, tenant_id)).fetchone())
        conn.commit()
        return {'presentation_id': presentation_id, 'revision': revision, 'version_id': version_id,
                'changed': changed, 'created': created, 'presentation': result}
    except Exception:
        conn.rollback()
        raise


def create_presentation(tenant_id, title, project_data=None, slides_data=None, slide_count=0, draft_id=None):
    """Create a new presentation record."""
    conn = get_db()
    pres_id = str(uuid.uuid4())
    if not draft_id and isinstance(project_data, dict):
        draft_id = project_data.get('draft_id') or project_data.get('draftId')
    conn.execute(
        'INSERT INTO presentations (id, tenant_id, title, draft_id, project_data, slides_data, slide_count) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (
            pres_id, tenant_id, title, draft_id,
            json.dumps(project_data, ensure_ascii=False) if project_data else None,
            json.dumps(slides_data, ensure_ascii=False) if slides_data else None,
            slide_count
        )
    )
    if project_data and isinstance(project_data, dict):
        draft_id = draft_id or project_data.get('draft_id') or project_data.get('draftId')
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


def _presentation_list_clauses(tenant_id, draft_id=None, search='', status='', date_from='', date_to='', accessible_draft_ids=None):
    """Shared WHERE clauses for the presentation list and its total count.

    ``accessible_draft_ids`` limits the list to presentations of drafts the
    caller may reach (t20); presentations with no draft stay visible to all."""
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if draft_id:
        clauses.append('draft_id = ?')
        params.append(str(draft_id))
    if str(search or '').strip():
        clauses.append('LOWER(title) LIKE ?')
        params.append('%' + str(search).strip().lower() + '%')
    if status == 'draft':
        clauses.append("COALESCE(status, 'draft') IN ('draft', 'edited', 'generated_draft')")
    elif status in {'pending_approval', 'pending'}:
        clauses.append("status IN ('pending_approval', 'final_approval_pending', 'generation_approval_pending', 'section_approval_pending')")
    elif status == 'approved':
        clauses.append("status IN ('approved', 'sections_approved')")
    elif status in PROPOSAL_LIFECYCLE_STATES:
        clauses.append('status = ?')
        params.append(status)
    if date_from:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) >= ?')
        params.append(str(date_from)[:10])
    if date_to:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) <= ?')
        params.append(str(date_to)[:10])
    if accessible_draft_ids is not None:
        ids = [str(i) for i in accessible_draft_ids]
        if ids:
            clauses.append('(draft_id IS NULL OR draft_id IN (' + ','.join('?' * len(ids)) + '))')
            params.extend(ids)
        else:
            clauses.append('draft_id IS NULL')
    return clauses, params


def count_presentations(tenant_id, draft_id=None, search='', status='', date_from='', date_to='', accessible_draft_ids=None):
    """Cheap total for a presentation list without touching any payload column."""
    conn = get_db()
    clauses, params = _presentation_list_clauses(tenant_id, draft_id, search, status, date_from, date_to, accessible_draft_ids)
    row = conn.execute(
        'SELECT COUNT(*) AS c FROM presentations WHERE ' + ' AND '.join(clauses),
        params,
    ).fetchone()
    return int((dict(row) if row else {}).get('c') or 0)


def get_presentations(tenant_id, draft_id=None, search='', status='', date_from='', date_to='', limit=200, offset=0, accessible_draft_ids=None):
    """Get tenant presentations with optional project and archive filters.

    List-only: selects metadata columns, never project_data/slides_data. Those
    payloads are kilobytes-to-megabytes per row and the dashboard used to fetch
    (and JSON-parse twice) up to 200 of them just to render five titles.
    presentation_scope and the legacy draft fallback are extracted in SQL.
    """
    conn = get_db()
    clauses, params = _presentation_list_clauses(tenant_id, draft_id, search, status, date_from, date_to, accessible_draft_ids)
    limit = max(1, min(int(limit or 200), 500))
    offset = max(0, int(offset or 0))
    params.extend([limit, offset])
    try:
        rows = conn.execute(
            'SELECT id, tenant_id, title, '
            "COALESCE(NULLIF(draft_id, ''), "
            "json_extract(project_data, '$.draftId'), "
            "json_extract(project_data, '$.draft_id')) AS draft_id, "
            'revision, slide_count, status, created_at, updated_at, '
            "json_extract(project_data, '$.presentation_scope') AS presentation_scope "
            'FROM presentations WHERE ' + ' AND '.join(clauses)
            + ' ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ? OFFSET ?',
            params,
        ).fetchall()
    except Exception:
        # SQLite without the JSON1 extension: fall back to metadata columns only.
        rows = conn.execute(
            'SELECT id, tenant_id, title, draft_id, revision, slide_count, status, '
            'created_at, updated_at FROM presentations WHERE ' + ' AND '.join(clauses)
            + ' ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ? OFFSET ?',
            params,
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        scope = item.get('presentation_scope')
        if isinstance(scope, str) and scope.strip().startswith(('{', '[')):
            try:
                scope = json.loads(scope)
            except (TypeError, ValueError):
                scope = None
        item['presentation_scope'] = scope
        result.append(item)
    return result


def update_presentation(pres_id, tenant_id=None, **fields):
    """Update a presentation, optionally scoped to a tenant."""
    conn = get_db()
    allowed = {'title', 'draft_id', 'project_data', 'slides_data', 'slide_count', 'status'}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'project_data' in updates and updates['project_data'] and not isinstance(updates['project_data'], str):
        updates['project_data'] = json.dumps(updates['project_data'], ensure_ascii=False)
    if 'slides_data' in updates and updates['slides_data'] and not isinstance(updates['slides_data'], str):
        updates['slides_data'] = json.dumps(updates['slides_data'], ensure_ascii=False)
    updates['updated_at'] = _utcnow().isoformat()
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

def create_export(presentation_id, tenant_id, format, file_path, content_hash=None,
                  cost_usd=0, regen_policy=None):
    """Record an exported file with the content hash it was produced from.

    ``content_hash`` ties the physical file to the presentation content the
    final gate approved, so a later export of edited content can never pass
    as the approved file (d03)."""
    conn = get_db()
    export_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO exports (id, presentation_id, tenant_id, format, file_path,
           content_hash, cost_usd, regen_policy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (export_id, presentation_id, tenant_id, format, file_path, content_hash,
         float(cost_usd or 0), regen_policy)
    )
    conn.commit()
    return export_id


def get_exports(tenant_id, accessible_draft_ids=None):
    """Get all exports for a tenant.

    ``accessible_draft_ids`` keeps only exports whose presentation belongs to a
    reachable draft (t20); exports with no presentation or whose presentation
    carries no draft stay visible."""
    conn = get_db()
    if accessible_draft_ids is not None:
        ids = [str(i) for i in accessible_draft_ids]
        placeholders = ','.join('?' * len(ids)) if ids else "''"
        rows = conn.execute(
            '''SELECT e.* FROM exports e LEFT JOIN presentations p
               ON p.id = e.presentation_id AND p.tenant_id = e.tenant_id
               WHERE e.tenant_id = ?
               AND (e.presentation_id IS NULL OR p.draft_id IS NULL OR p.draft_id IN (''' + placeholders + '''))
               ORDER BY e.created_at DESC''',
            (tenant_id, *ids)
        ).fetchall()
    else:
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
