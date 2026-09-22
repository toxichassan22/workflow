


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Presentation approvals: the final-gate reachability check plus the
# approval row lifecycle (create, list pending, review, status).
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
