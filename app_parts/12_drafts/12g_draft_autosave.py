"""The autosave patch of a project file.

The editor writes the draft row every few seconds while people type, but the
history must not grow a commit for every keystroke. This route writes only the
keys the client changed and leaves the commit to the open autosave window:
one commit every 60 seconds of active saving, after 30 seconds of quiet, when
the client says it went idle, or around an AI generation (pinned).
"""

import json
import uuid

AUTOSAVE_MAX_KEYS = 400
AUTOSAVE_MAX_PATCH_BYTES = 2 * 1024 * 1024
AUTOSAVE_EVENTS = ('ai_before', 'ai_after')


def _autosave_json_size(value):
    try:
        return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
    except (TypeError, ValueError):
        return AUTOSAVE_MAX_PATCH_BYTES + 1


def _autosave_close_and_log(draft_id, closed):
    if not closed or not closed.get('commitId'):
        return closed
    try:
        _record_draft_save_change(
            draft_id, closed.get('before') or {}, closed.get('after') or {},
            {}, {}, {'id': draft_id})
    except Exception as exc:  # the log must never fail the save
        app.logger.warning('[DRAFT AUTOSAVE] could not record the change log: %s', exc)
    return closed


@app.route('/api/project-draft/autosave', methods=['POST'])
@require_auth
def api_autosave_project_draft():
    """Write a patch of the open project file and fold it into one commit window."""
    if g.user_id is not None and not _landloom_can('create_presentation'):
        return _landloom_forbidden('تحرير المشاريع يخص المحررين')
    data = request.get_json(silent=True) or {}
    patch = data.get('patch') if isinstance(data.get('patch'), dict) else None
    idle = bool(data.get('idle'))
    event = str(data.get('event') or '').strip()
    if event and event not in AUTOSAVE_EVENTS:
        return jsonify({'error': 'event is not supported'}), 400
    if patch is None:
        return jsonify({'error': 'patch must be an object'}), 400
    if not patch and not idle and not event:
        return jsonify({'error': 'لا توجد تعديلات للحفظ'}), 400
    if len(patch) > AUTOSAVE_MAX_KEYS or _autosave_json_size(patch) > AUTOSAVE_MAX_PATCH_BYTES:
        return jsonify({'error': 'حجم التعديلات أكبر من المسموح'}), 413
    if any(not isinstance(key, str) or not key for key in patch):
        return jsonify({'error': 'patch keys are invalid'}), 400
    clear_keys = data.get('clearKeys')
    clear_keys = [str(key) for key in clear_keys] if isinstance(clear_keys, list) else None
    requested_id = str(data.get('draftId') or '').strip()
    previous = None
    if requested_id:
        previous = db.get_project_draft_by_id(g.tenant_id, requested_id)
        if previous and not db.user_may_access_draft(g.user_id, previous):
            return jsonify({'error': 'Draft not found'}), 404
    base_revision = data.get('baseRevision')
    if base_revision is not None:
        try:
            base_revision = int(base_revision)
            if base_revision < 0:
                raise ValueError('negative')
        except (TypeError, ValueError):
            return jsonify({'error': 'baseRevision must be a non-negative integer'}), 400
    if requested_id and previous is None and (base_revision or 0) > 0:
        return jsonify({'error': 'Draft not found'}), 404
    if previous is not None and base_revision is None:
        return jsonify({
            'error': 'تعذر الحفظ: لم تحدد النسخة التي بُني عليها التعديل.',
            'error_code': 'DRAFT_REVISION_REQUIRED',
            'currentRevision': int(previous.get('revision') or 0),
        }), 409
    if previous is None and not patch:
        return jsonify({'error': 'Draft not found'}), 404

    previous_data = (previous or {}).get('draft_data') or {}
    previous_statuses = (previous or {}).get('section_statuses') or {}
    requested_keys = [key for key in patch if key not in ('draftId', 'draft_id')]
    if g.user_id and not g.is_admin and patch:
        forbidden_sections, _restored = _enforce_draft_field_sections(
            patch, previous_data, None, previous_statuses)
        if forbidden_sections:
            return jsonify({
                'error': 'لا تملك صلاحية حفظ بيانات قسم: ' + '، '.join(forbidden_sections),
                'error_code': 'SECTION_FORBIDDEN',
                'sections': forbidden_sections,
            }), 403

    draft_id = previous['id'] if previous else (requested_id or str(uuid.uuid4()))
    closed = None
    if patch:
        patch = _sanitize_save_workflow_claims(g.tenant_id, draft_id, patch, previous_data)
        try:
            db.save_project_draft(
                g.tenant_id, _project_draft_actor_id(), patch, None, 'draft',
                draft_id=draft_id,
                expected_revision=base_revision if previous is not None else None,
                existing_row=previous,
                clear_keys=clear_keys,
                defer_commit=True,
                commit_author_id=g.user_id,
                commit_author_name=_landloom_actor_name(),
            )
        except db.DraftRevisionConflict as conflict:
            return jsonify({
                'error': 'المسودة تغيّرت في نسخة أخرى — أعد تحميلها قبل الحفظ',
                'error_code': 'DRAFT_REVISION_CONFLICT',
                'expectedRevision': conflict.expected_revision,
                'currentRevision': conflict.current_revision,
            }), 409
        except db.DraftLocked as locked:
            return _draft_locked_response(locked.status)
        except db.DraftOverwriteRefused as refused:
            reason = getattr(refused, 'reason', 'empty')
            if reason == 'nameless':
                return jsonify({
                    'error': 'لم يتم الحفظ: البيانات المرسلة لمشروع جديد فارغ.',
                    'error_code': 'DRAFT_BLANK_PROJECT_OVERWRITE'
                }), 409
            if reason == 'different_project':
                return jsonify({
                    'error': 'لم يتم الحفظ: الطلب لا يحدد المسودة.',
                    'error_code': 'DRAFT_UNNAMED_PROJECT_MISMATCH'
                }), 409
            return jsonify({
                'error': 'لم يتم الحفظ: البيانات المرسلة فارغة والمسودة تحتوي بيانات.',
                'error_code': 'DRAFT_EMPTY_OVERWRITE'
            }), 409
        window = db.autosave_window_begin(
            g.tenant_id, draft_id, base_revision or 0, previous_data,
            requested_keys, author_id=g.user_id,
            author_name=_landloom_actor_name())
        closed = window.get('closed')
    if idle or event:
        if patch:
            closed = db.autosave_window_close(
                g.tenant_id, draft_id, kind=event or 'autosave',
                pinned=bool(event)) or closed
        elif event:
            closed = db.autosave_window_close(
                g.tenant_id, draft_id, kind=event, pinned=True) or closed
        else:
            closed = db.autosave_window_close(
                g.tenant_id, draft_id, kind='autosave') or closed
    _autosave_close_and_log(draft_id, closed)
    row = db.get_db().execute(
        'SELECT revision FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (draft_id, g.tenant_id)).fetchone()
    revision = int(row['revision'] or 0) if row else 0
    db.publish_live_base_revision(g.tenant_id, draft_id, revision)
    return jsonify({
        'success': True,
        'draftId': draft_id,
        'revision': revision,
        'committed': bool(closed and closed.get('commitId')),
        'windowOpen': not (idle or event),
        'pinned': bool(event),
    })
