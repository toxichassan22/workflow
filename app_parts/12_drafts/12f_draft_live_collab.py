"""The live editing session of a project file.

People typing in the same project see each other's text and carets between
saves. The session is a CRDT exchange, not a draft write: the browser sends
small opaque updates, the server assigns them a common order, and every
client reads the ones after its cursor. The project draft changes only when
somebody presses save, exactly as before.

Transport is short polling because the hosting account cannot hold a socket
open. The poll is small (deltas after a cursor, never the draft payload) and
the browser runs it only while the project page is visible and active.
"""

import base64
import binascii
import re
from datetime import timedelta

LIVE_MAX_UPDATES_PER_REQUEST = 64
LIVE_MAX_UPDATE_BYTES = 131072
LIVE_MAX_BATCH_BYTES = 524288
LIVE_MAX_SNAPSHOT_BYTES = 2097152
LIVE_MAX_UPDATES_PER_READ = 1000
LIVE_PRESENCE_TTL_SECONDS = 20
LIVE_CLIENT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{8,80}$')


def _live_draft_state_or_none(draft_id):
    """The light draft row, when the caller may follow it."""
    draft = db.get_project_draft_state(g.tenant_id, draft_id)
    if not draft or not db.user_may_access_draft(g.user_id, draft):
        return None
    return draft


def _live_actor():
    return g.user_id or ('tenant-admin:%s' % g.tenant_id)


def _live_actor_name():
    return (getattr(g, 'user_name', None) or '').strip() or 'مستخدم'


def _live_cutoff():
    return (db._utcnow() - timedelta(seconds=LIVE_PRESENCE_TTL_SECONDS)).isoformat()


def _live_refused_field(field_key, section_map=None, section_statuses=None):
    """A live update may only touch a field the caller can edit.

    The browser may not render a blocked section at all, so a value arriving
    for it is a write the caller has no business making. Unknown keys are
    refused too: the session stores text fields that exist in this tenant.
    An approved section is locked until it is unapproved, exactly like its
    inputs on screen.
    """
    if not field_key:
        return False
    section_map = section_map if section_map is not None else _draft_field_section_map(g.tenant_id)
    section_key = _draft_section_of_key(section_map, field_key)
    if not section_key:
        return True
    if (section_statuses or {}).get(section_key) == 'approved':
        return True
    denied = _hidden_field_sections()
    if not denied:
        return False
    return section_key in denied


def _live_decode_payload(value, max_bytes=LIVE_MAX_UPDATE_BYTES):
    """Decode one base64 CRDT update, or None when it is not a valid one."""
    if not isinstance(value, str) or not value:
        return None
    if len(value) > max_bytes * 2:
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not decoded or len(decoded) > max_bytes:
        return None
    return decoded


def _live_presence_rows(conn, document_id, client_id):
    rows = conn.execute(
        '''SELECT client_id, user_id, user_name, field_key, section_key,
                  caret_start, caret_end, updated_at
           FROM draft_live_presence
           WHERE document_id = ? AND tenant_id = ? AND updated_at >= ?
           ORDER BY updated_at DESC''',
        (document_id, g.tenant_id, _live_cutoff())
    ).fetchall()
    presence = []
    for row in rows:
        item = dict(row)
        if client_id and item.get('client_id') == client_id:
            continue
        item.pop('client_id', None)
        presence.append(item)
    return presence


@app.route('/api/project-draft/<draft_id>/live', methods=['GET'])
@require_auth
def api_draft_live_read(draft_id):
    """Deltas after a cursor plus whoever is editing where."""
    draft = _live_draft_state_or_none(draft_id)
    if not draft:
        return jsonify({'error': 'No project draft found'}), 404
    try:
        since = max(0, int(request.args.get('since') or 0))
    except (TypeError, ValueError):
        since = 0
    client_id = str(request.args.get('clientId') or '')
    conn = db.get_db()
    document = conn.execute(
        'SELECT * FROM draft_live_documents WHERE id = ? AND tenant_id = ?',
        (draft_id, g.tenant_id)
    ).fetchone()
    if not document:
        return jsonify({
            'success': True,
            'draftId': draft_id,
            'hasSession': False,
            'seq': 0,
            'reset': False,
            'snapshot': '',
            'snapshotSeq': 0,
            'baseRevision': int(draft.get('revision') or 0),
            'updates': [],
            'presence': [],
            'hasMore': False,
        })
    document = dict(document)
    state_seq = int(document.get('state_seq') or 0)
    reset = since < state_seq
    if reset:
        since = state_seq
    rows = conn.execute(
        '''SELECT seq, payload, field_key, author_id, author_name
           FROM draft_live_updates
           WHERE document_id = ? AND tenant_id = ? AND seq > ?
           ORDER BY seq ASC LIMIT ?''',
        (draft_id, g.tenant_id, since, LIVE_MAX_UPDATES_PER_READ)
    ).fetchall()
    updates = [dict(row) for row in rows]
    has_more = len(updates) >= LIVE_MAX_UPDATES_PER_READ
    cursor = updates[-1]['seq'] if updates else since
    return jsonify({
        'success': True,
        'draftId': draft_id,
        'hasSession': True,
        'seq': cursor,
        'serverSeq': int(document.get('seq') or 0),
        'reset': reset,
        'snapshot': document.get('state') or '' if reset else '',
        'snapshotSeq': state_seq if reset else 0,
        'baseRevision': int(document.get('base_revision') or 0),
        'updatedAt': document.get('updated_at') or '',
        'updates': updates,
        'presence': _live_presence_rows(conn, draft_id, client_id),
        'hasMore': has_more,
    })


@app.route('/api/project-draft/<draft_id>/live', methods=['POST'])
@require_auth
def api_draft_live_write(draft_id):
    """Append CRDT deltas, heartbeat the caret, and optionally compact state."""
    draft = _live_draft_state_or_none(draft_id)
    if not draft:
        return jsonify({'error': 'No project draft found'}), 404
    if g.user_id is not None and not _landloom_can('create_presentation'):
        return _landloom_forbidden('تحرير المشاريع يخص المحررين')
    status = db.normalize_proposal_status(draft.get('status'))
    if db.proposal_status_is_locked(status):
        return _draft_locked_response(status)
    data = request.json or {}
    client_id = str(data.get('clientId') or '').strip()
    if not LIVE_CLIENT_ID_RE.match(client_id):
        return jsonify({'error': 'clientId is invalid'}), 400
    section_map = _draft_field_section_map(g.tenant_id)
    section_statuses = draft.get('section_statuses') or {}
    raw_updates = data.get('updates') or []
    if not isinstance(raw_updates, list) or len(raw_updates) > LIVE_MAX_UPDATES_PER_REQUEST:
        return jsonify({'error': 'too many updates'}), 400
    total_bytes = 0
    updates = []
    for item in raw_updates:
        if not isinstance(item, dict):
            return jsonify({'error': 'update must be an object'}), 400
        payload = _live_decode_payload(item.get('payload'))
        if payload is None:
            return jsonify({'error': 'update payload is invalid'}), 400
        field_key = str(item.get('fieldKey') or '').strip()[:120]
        if not field_key:
            return jsonify({'error': 'fieldKey is required'}), 400
        if _live_refused_field(field_key, section_map, section_statuses):
            return jsonify({
                'error': 'لا تملك صلاحية تعديل هذا الحقل',
                'error_code': 'LIVE_FIELD_FORBIDDEN',
            }), 403
        total_bytes += len(payload)
        if total_bytes > LIVE_MAX_BATCH_BYTES:
            return jsonify({'error': 'update batch is too large'}), 400
        updates.append((payload, field_key))
    presence = data.get('presence') if isinstance(data.get('presence'), dict) else None
    if presence:
        field_key = str(presence.get('fieldKey') or '').strip()[:120]
        if _live_refused_field(field_key, section_map, section_statuses):
            presence = None
    snapshot = data.get('snapshot')
    snapshot_bytes = (_live_decode_payload(snapshot, LIVE_MAX_SNAPSHOT_BYTES)
                      if snapshot else None)
    if snapshot and snapshot_bytes is None:
        return jsonify({'error': 'snapshot is invalid'}), 400
    if snapshot_bytes and len(snapshot_bytes) > LIVE_MAX_SNAPSHOT_BYTES:
        return jsonify({'error': 'snapshot is too large'}), 400
    try:
        snapshot_seq = max(0, int(data.get('snapshotSeq') or 0))
    except (TypeError, ValueError):
        snapshot_seq = 0
    base_revision = None
    if data.get('baseRevision') is not None:
        try:
            base_revision = max(0, int(data.get('baseRevision')))
        except (TypeError, ValueError):
            base_revision = None

    conn = db.get_db()
    try:
        document = conn.execute(
            'SELECT seq, state, state_seq, base_revision FROM draft_live_documents '
            'WHERE id = ? AND tenant_id = ?',
            (draft_id, g.tenant_id)
        ).fetchone()
        if not document:
            conn.execute(
                '''INSERT INTO draft_live_documents
                   (id, tenant_id, state, state_seq, seq, base_revision, updated_at)
                   VALUES (?, ?, '', 0, 0, ?, ?)''',
                (draft_id, g.tenant_id, int(draft.get('revision') or 0),
                 db._utcnow().isoformat())
            )
            base_seq = 0
            state = ''
            state_seq = 0
        else:
            document = dict(document)
            base_seq = int(document.get('seq') or 0)
            state = document.get('state') or ''
            state_seq = int(document.get('state_seq') or 0)
        next_seq = base_seq
        for payload, field_key in updates:
            next_seq += 1
            conn.execute(
                '''INSERT INTO draft_live_updates
                   (document_id, tenant_id, seq, payload, field_key,
                    author_id, author_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (draft_id, g.tenant_id, next_seq, base64.b64encode(payload).decode('ascii'),
                 field_key or None, _live_actor(), _live_actor_name(),
                 db._utcnow().isoformat())
            )
        if snapshot_bytes and snapshot_seq >= state_seq:
            # A client may compact only up to the seq it had actually applied
            # before this batch. Anything newer may not be in its snapshot.
            snapshot_seq = min(snapshot_seq, base_seq)
            if snapshot_seq >= state_seq:
                state = base64.b64encode(snapshot_bytes).decode('ascii')
                state_seq = snapshot_seq
                conn.execute(
                    'DELETE FROM draft_live_updates WHERE document_id = ? AND tenant_id = ? AND seq <= ?',
                    (draft_id, g.tenant_id, snapshot_seq)
                )
        conn.execute(
            '''UPDATE draft_live_documents
               SET seq = ?, state = ?, state_seq = ?, base_revision = COALESCE(?, base_revision),
                   updated_at = ?
               WHERE id = ? AND tenant_id = ?''',
            (next_seq, state, state_seq, base_revision, db._utcnow().isoformat(),
             draft_id, g.tenant_id)
        )
        if presence:
            now = db._utcnow().isoformat()
            conn.execute(
                'DELETE FROM draft_live_presence WHERE document_id = ? AND tenant_id = ? '
                'AND updated_at < ?',
                (draft_id, g.tenant_id, _live_cutoff())
            )
            if presence.get('leave'):
                conn.execute(
                    'DELETE FROM draft_live_presence WHERE document_id = ? AND tenant_id = ? AND client_id = ?',
                    (draft_id, g.tenant_id, client_id)
                )
            else:
                values = (
                    str(presence.get('fieldKey') or '')[:120] or None,
                    str(presence.get('sectionKey') or '')[:120] or None,
                    _live_clamped_int(presence.get('caretStart')),
                    _live_clamped_int(presence.get('caretEnd')),
                    now,
                )
                changed = conn.execute(
                    '''UPDATE draft_live_presence
                       SET tenant_id = ?, user_id = ?, user_name = ?, field_key = ?,
                           section_key = ?, caret_start = ?, caret_end = ?, updated_at = ?
                       WHERE document_id = ? AND client_id = ?''',
                    (g.tenant_id, _live_actor(), _live_actor_name()) + values + (draft_id, client_id)
                ).rowcount
                if not changed:
                    conn.execute(
                        '''INSERT INTO draft_live_presence
                           (document_id, client_id, tenant_id, user_id, user_name,
                            field_key, section_key, caret_start, caret_end, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (draft_id, client_id, g.tenant_id, _live_actor(), _live_actor_name()) + values
                    )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        app.logger.warning(
            '[DRAFT LIVE] could not append updates for tenant=%s draft=%s: %s',
            g.tenant_id, draft_id, exc)
        return jsonify({'error': 'تعذر تحديث جلسة التحرير', 'error_code': 'LIVE_WRITE_FAILED'}), 500
    return jsonify({
        'success': True,
        'draftId': draft_id,
        'seq': next_seq,
        'hasSession': True,
        'reset': False,
        'snapshot': '',
        'snapshotSeq': state_seq,
        'baseRevision': int(base_revision if base_revision is not None else
                            (document.get('base_revision') if document else 0) or 0),
        'updates': [],
        'presence': [],
    })


@app.route('/api/project-draft/<draft_id>/live/leave', methods=['POST'])
@require_auth
def api_draft_live_leave(draft_id):
    """Drop this tab's presence immediately on close or navigation."""
    draft = _live_draft_state_or_none(draft_id)
    if not draft:
        return jsonify({'error': 'No project draft found'}), 404
    data = request.get_json(silent=True) or {}
    client_id = str(data.get('clientId') or request.args.get('clientId') or '').strip()
    if client_id and LIVE_CLIENT_ID_RE.match(client_id):
        conn = db.get_db()
        conn.execute(
            'DELETE FROM draft_live_presence WHERE document_id = ? AND tenant_id = ? AND client_id = ?',
            (draft_id, g.tenant_id, client_id)
        )
        conn.commit()
    return jsonify({'success': True})


def _live_clamped_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(number, 1000000))
