


# ── t15: final approval, digital stamp and the downloads library ────────────

def _file_sha256(path):
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def stamp_final_file(app_root, tenant_id, presentation_id, revision=0):
    """A stamp is not a decoration: the sha256 of the file bytes plus who decided."""
    conn = get_db()
    approval = conn.execute(
        "SELECT * FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ? AND status = 'approved' "
        'ORDER BY decided_at DESC LIMIT 1',
        (tenant_id, presentation_id),
    ).fetchone()
    if not approval:
        return {'error': 'not_approved'}
    row = conn.execute(
        'SELECT id, file_path FROM exports WHERE presentation_id = ? ORDER BY created_at DESC LIMIT 1',
        (presentation_id,),
    ).fetchone()
    if not row or not row['file_path']:
        return {'error': 'no_export_file'}
    path = row['file_path']
    if not os.path.isabs(path):
        path = os.path.join(app_root, path)
    digest = _file_sha256(path)
    if not digest:
        return {'error': 'stamp_failed'}
    conn.execute(
        'UPDATE final_file_approvals SET content_hash = ?, stamped_export_id = ? WHERE id = ?',
        (digest, row['id'], approval['id']))
    conn.commit()
    return {
        'approval_id': approval['id'],
        'content_hash': digest,
        'export_id': row['id'],
        'decided_by_name': approval['decided_by_name'],
        'decided_at': approval['decided_at'],
        'revision': int(revision or 0),
        'algorithm': 'sha256',
    }


def request_final_file_approval(tenant_id, presentation_id, requested_by, requested_by_name, revision=0):
    """Send a generated file to the final approver.

    The request itself moves the linked draft to ``final_approval_pending``
    before the approval row exists, so a draft that cannot legally enter the
    gate refuses the request instead of opening an approval on a stale state.
    A presentation without a linked draft keeps the legacy unlinked behaviour.
    """
    conn = get_db()
    presentation = get_presentation(presentation_id, tenant_id=tenant_id)
    if not presentation:
        return {'error': 'presentation_not_found'}
    pending = conn.execute(
        "SELECT id FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ? AND status = 'pending'",
        (tenant_id, presentation_id),
    ).fetchone()
    if pending:
        return {'error': 'approval_already_pending', 'approval_id': pending['id']}
    # The request pins the exact file content being sent. Re-sending the same
    # content after a rejection is refused — the next request must carry an
    # actual revision (t15-07) — and an unchanged re-request on an approved
    # file is a no-op.
    request_hash = _presentation_review_hash(presentation)
    latest = conn.execute(
        "SELECT id, status, request_hash FROM final_file_approvals "
        "WHERE tenant_id = ? AND presentation_id = ? AND status != 'pending' "
        'ORDER BY requested_at DESC LIMIT 1',
        (tenant_id, presentation_id),
    ).fetchone()
    if latest is not None and 'request_hash' in latest.keys() \
            and latest['request_hash'] and latest['request_hash'] == request_hash:
        if latest['status'] == 'approved':
            return {'error': 'already_approved', 'approval_id': latest['id']}
        if latest['status'] == 'rejected':
            return {'error': 'unchanged_since_rejection', 'approval_id': latest['id']}
    draft_id = presentation.get('draft_id')
    if draft_id and get_project_draft_by_id(tenant_id, draft_id):
        res = transition_project_draft_status(
            tenant_id, draft_id, 'final_approval_pending',
            actor_id=requested_by, actor_name=requested_by_name,
            reason='إرسال الملف النهائي للاعتماد',
        )
        if res.get('error'):
            return res
    approval_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO final_file_approvals
           (id, tenant_id, presentation_id, revision, status, requested_by, requested_by_name, request_hash)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)''',
        (approval_id, tenant_id, presentation_id, int(revision or 0), requested_by, requested_by_name,
         request_hash),
    )
    conn.commit()
    row = conn.execute('SELECT * FROM final_file_approvals WHERE id = ?', (approval_id,)).fetchone()
    return dict(row)


def decide_final_file_approval(tenant_id, approval_id, decision, decided_by, decided_by_name,
                               note=None, allow_self=False, app_root=None):
    """Decide the final-file gate. The requester may not self-approve (d02);
    allow_self is reserved for company-level administrators.

    The decision drives the draft lifecycle: approval lands the draft on
    ``approved`` (and the presentation follows through the transition sync),
    while a rejection — which needs a written reason — returns it to
    ``generated_draft`` for rework. Approving also stamps the produced file:
    its content hash and the exact export become the download gate's proof.
    """
    if decision not in {'approved', 'rejected'}:
        return {'error': 'invalid_decision'}
    clean_note = str(note or '').strip()
    if decision == 'rejected' and not clean_note:
        return {'error': 'note_required'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM final_file_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    if not row:
        return {'error': 'approval_not_found'}
    if row['status'] != 'pending':
        return {'error': 'approval_not_pending'}
    if not allow_self and row['requested_by'] and str(row['requested_by']) == str(decided_by):
        return {'error': 'self_approval_not_allowed'}
    pres = conn.execute(
        'SELECT draft_id, status, project_data, slides_data FROM presentations WHERE id = ? AND tenant_id = ?',
        (row['presentation_id'], tenant_id),
    ).fetchone()
    if decision == 'approved' and pres is not None:
        # The approver decides on the content that was sent — a file edited
        # after the request must be sent again, not approved blind.
        request_hash = row['request_hash'] if 'request_hash' in row.keys() else None
        if request_hash and _presentation_review_hash(dict(pres)) != request_hash:
            return {'error': 'content_changed'}
    draft_id = pres['draft_id'] if pres else None
    target_status = 'approved' if decision == 'approved' else 'generated_draft'
    if draft_id:
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if draft and not can_transition_proposal_status(draft.get('status'), target_status):
            return {'error': 'invalid_transition',
                    'current_status': normalize_proposal_status(draft.get('status')),
                    'target_status': target_status}
    # ISS-028: the decide itself is the atomic claim — a second reviewer who
    # passed the pending check above loses the conditional UPDATE rather than
    # overwriting the first decision.
    updated_row = conn.execute(
        '''UPDATE final_file_approvals SET status = ?, decided_by = ?, decided_by_name = ?,
           decided_at = ?, decision_note = ? WHERE id = ? AND status = 'pending' ''',
        (decision, decided_by, decided_by_name, _utcnow().isoformat(),
         clean_note or None, approval_id),
    )
    if updated_row.rowcount != 1:
        return {'error': 'approval_not_pending'}
    if decision == 'approved':
        conn.execute(
            "UPDATE presentations SET status = 'approved' WHERE id = ? AND tenant_id = ?",
            (row['presentation_id'], tenant_id),
        )
    conn.commit()
    lifecycle = _draft_gate_transition(
        tenant_id, draft_id, target_status, decided_by, decided_by_name,
        clean_note or ('اعتماد الملف النهائي' if decision == 'approved' else 'إعادة الملف النهائي للتعديل'))
    if lifecycle is None and draft_id:
        # The decision must not stand while the linked draft stayed behind.
        conn.execute(
            "UPDATE final_file_approvals SET status = 'pending', decided_by = NULL, "
            'decided_by_name = NULL, decided_at = NULL, decision_note = NULL WHERE id = ?',
            (approval_id,),
        )
        if decision == 'approved':
            conn.execute(
                'UPDATE presentations SET status = ? WHERE id = ? AND tenant_id = ?',
                ((pres['status'] if pres else None) or 'generated_draft', row['presentation_id'], tenant_id),
            )
        conn.commit()
        return {'error': 'lifecycle_transition_failed', 'target_status': target_status}
    updated = dict(conn.execute('SELECT * FROM final_file_approvals WHERE id = ?', (approval_id,)).fetchone())
    if lifecycle:
        updated['draft_status'] = lifecycle.get('current_status')
    if decision == 'approved' and app_root:
        # The stamp binds the approved content hash to the produced export;
        # a missing export leaves the approval standing but reports why the
        # file is not stamped yet.
        stamp = stamp_final_file(app_root, tenant_id, row['presentation_id'],
                                 revision=row['revision'])
        if stamp.get('error'):
            updated['stamp_error'] = stamp['error']
        else:
            updated['stamped_file'] = stamp
            updated['content_hash'] = stamp['content_hash']
            updated['stamped_export_id'] = stamp['export_id']
    return updated


def latest_final_file_approval(tenant_id, presentation_id, status=None):
    """The newest final-file approval of a presentation, status-filtered."""
    conn = get_db()
    query = ('SELECT * FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ?')
    params = [tenant_id, presentation_id]
    if status:
        query += ' AND status = ?'
        params.append(status)
    query += ' ORDER BY requested_at DESC LIMIT 1'
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


def get_final_file_approval(tenant_id, approval_id):
    """One final-file approval row inside the tenant, or None."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM final_file_approvals WHERE id = ? AND tenant_id = ?',
        (approval_id, tenant_id),
    ).fetchone()
    return dict(row) if row else None


def list_final_file_approvals(tenant_id, presentation_id=None, status=None, limit=50,
                              accessible_draft_ids=None):
    conn = get_db()
    query = ('SELECT ffa.*, p.title AS presentation_title FROM final_file_approvals ffa '
             'LEFT JOIN presentations p ON p.id = ffa.presentation_id AND p.tenant_id = ffa.tenant_id '
             'WHERE ffa.tenant_id = ?')
    params = [tenant_id]
    if presentation_id:
        query += ' AND ffa.presentation_id = ?'
        params.append(presentation_id)
    if status:
        query += ' AND ffa.status = ?'
        params.append(status)
    if accessible_draft_ids is not None:
        # ISS-014: a project-scoped member sees only approvals whose
        # presentation links a draft inside their scope.
        ids = [str(i) for i in accessible_draft_ids]
        if ids:
            query += ' AND (p.draft_id IS NULL OR p.draft_id IN (' + ','.join('?' * len(ids)) + '))'
            params.extend(ids)
        else:
            query += ' AND p.draft_id IS NULL'
    query += ' ORDER BY ffa.requested_at DESC LIMIT ?'
    params.append(int(limit))
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def record_download(tenant_id, file_name, presentation_id=None, draft_id=None, format='pdf',
                    version_label=None, approval_status=None, generated_by=None,
                    generated_by_name=None, file_size=0, export_id=None):
    """t15: every generated file enters the library with who made and approved it.

    The approval state is read from the final-file gate, never trusted from
    the client: an approved decision names its approver, a pending request
    marks the row pending, and anything else is a draft.
    """
    conn = get_db()
    if export_id:
        export_row = conn.execute(
            'SELECT * FROM exports WHERE id = ? AND tenant_id = ?',
            (export_id, tenant_id),
        ).fetchone()
        if export_row:
            presentation_id = presentation_id or export_row['presentation_id']
            if not file_size and export_row['file_path']:
                try:
                    file_size = os.path.getsize(export_row['file_path'])
                except OSError:
                    file_size = 0
    if not draft_id and presentation_id:
        pres_row = conn.execute(
            'SELECT draft_id FROM presentations WHERE id = ? AND tenant_id = ?',
            (presentation_id, tenant_id),
        ).fetchone()
        if pres_row:
            draft_id = pres_row['draft_id']
    approval = None
    if presentation_id:
        approval = conn.execute(
            "SELECT * FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ? "
            "AND status = 'approved' ORDER BY decided_at DESC LIMIT 1",
            (tenant_id, presentation_id),
        ).fetchone()
    if approval_status is None:
        approval_status = 'approved' if approval else 'pending'
    approved_by_name = approval['decided_by_name'] if approval else None
    if not version_label and presentation_id:
        pres_row = conn.execute(
            'SELECT revision FROM presentations WHERE id = ? AND tenant_id = ?',
            (presentation_id, tenant_id),
        ).fetchone()
        if pres_row:
            version_label = f"v{int(pres_row['revision'] or 0)}"
    row_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO presentation_downloads
           (id, tenant_id, presentation_id, draft_id, file_name, format, version_label,
            approval_status, generated_by, generated_by_name, approved_by_name, file_size, export_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row_id, tenant_id, presentation_id, draft_id, file_name, format, version_label,
         approval_status, generated_by, generated_by_name, approved_by_name,
         int(file_size or 0), export_id),
    )
    conn.commit()
    return dict(conn.execute('SELECT * FROM presentation_downloads WHERE id = ?', (row_id,)).fetchone())


def get_download(tenant_id, download_id):
    """One downloads-ledger row inside the tenant, or None."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM presentation_downloads WHERE id = ? AND tenant_id = ?',
        (download_id, tenant_id),
    ).fetchone()
    return dict(row) if row else None


def mark_download_downloaded(tenant_id, download_id, downloaded_by_name=None):
    conn = get_db()
    now = _utcnow().isoformat()
    cursor = conn.execute(
        'UPDATE presentation_downloads SET downloaded_at = ?, downloaded_by_name = ? '
        'WHERE id = ? AND tenant_id = ? AND downloaded_at IS NULL',
        (now, downloaded_by_name, download_id, tenant_id),
    )
    conn.commit()
    if cursor.rowcount:
        return dict(conn.execute('SELECT * FROM presentation_downloads WHERE id = ?', (download_id,)).fetchone())
    return None


def list_downloads(tenant_id, presentation_id=None, limit=100, accessible_draft_ids=None):
    conn = get_db()
    query = ('SELECT d.* FROM presentation_downloads d '
             'LEFT JOIN presentations p ON p.id = d.presentation_id AND p.tenant_id = d.tenant_id '
             'WHERE d.tenant_id = ?')
    params = [tenant_id]
    if presentation_id:
        query += ' AND d.presentation_id = ?'
        params.append(presentation_id)
    if accessible_draft_ids is not None:
        # ISS-014: a project-scoped member sees only downloads whose
        # presentation links a draft inside their scope.
        ids = [str(i) for i in accessible_draft_ids]
        if ids:
            query += ' AND (p.draft_id IS NULL OR p.draft_id IN (' + ','.join('?' * len(ids)) + '))'
            params.extend(ids)
        else:
            query += ' AND p.draft_id IS NULL'
    query += ' ORDER BY d.generated_at DESC LIMIT ?'
    params.append(int(limit))
    rows = conn.execute(query, params).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        # The library serves the file through the gated export endpoint only,
        # and only a row whose final approval landed carries a usable URL.
        item['download_url'] = (
            f"/api/exports/{item['export_id']}/download"
            if item.get('export_id') and item.get('approval_status') == 'approved' else None)
    return items
