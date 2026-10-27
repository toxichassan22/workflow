"""The draft version history — list, inspect and restore a project version.

Every save of a project file leaves a commit behind (see
``db.record_draft_commit``). These routes are the GitHub-shaped surface over
that store: the chain of versions, what one version changed, and a restore
that carries an older version forward as a NEW commit — the history is never
rewritten and the newer work is never thrown away.

The restore runs through the ordinary save path, so every guard that already
protects a project file protects it too: a locked file stays locked, a stale
revision is refused, and approvals that the restored data contradicts are
demoted instead of silently kept.
"""

DRAFT_RESTORE_COMMIT_MESSAGE = 'استرجاع نسخة سابقة'
DRAFT_SAVE_MERGE_COMMIT_MESSAGE = 'دمج تعديلات متزامنة'
# The slides and the chat belong to the session that made them: a merge takes
# them from the incoming side instead of asking the user to read a conflict
# nobody can judge.
DRAFT_SAVE_PREFER_THEIRS = ('tenantSlidesData', 'designerChat', 'slide_generation_checkpoint')


def _draft_commit_error(code, message, status=400, **extra):
    payload = {'error': message, 'error_code': code}
    payload.update(extra)
    return jsonify(payload), status


def _demote_sections_for_keys(tenant_id, changed_keys, stored_statuses):
    """Approvals of the sections a change touched go back to 'draft'.

    A section approved against the current values cannot stay approved once
    the file carries other ones — the approval described data that is no
    longer there. Only mapped keys belonging to an identified section demote that section.
    """
    statuses = dict(stored_statuses or {})
    if not changed_keys:
        return statuses, []
    try:
        section_map = _draft_field_section_map(tenant_id)
    except Exception:
        section_map = {}
    sections = set()
    for key in changed_keys:
        section = _draft_section_of_key(section_map, key)
        if section:
            sections.add(section)
    demoted = []
    for section in sorted(sections):
        if statuses.get(section) == 'approved':
            statuses[section] = 'draft'
            demoted.append(section)
    return statuses, sorted(set(demoted))


def _restore_section_statuses(tenant_id, draft, restored_data, stored_statuses):
    """Approvals the restored data contradicts go back to 'draft'."""
    current = draft.get('draft_data') or {}
    bookkeeping = set(getattr(db, 'DRAFT_BOOKKEEPING_KEYS', ()) or ())
    changed = [
        key for key in set(current) | set(restored_data)
        if key not in bookkeeping and current.get(key) != restored_data.get(key)
    ]
    return _demote_sections_for_keys(tenant_id, changed, stored_statuses)


def _record_draft_save_change(draft_id, previous_data, draft_data,
                              previous_statuses, section_statuses, previous=None):
    """Write the change-log entries of a save.

    One entry per touched section, so the log reads as a feed of named actions
    instead of one row dumping every accumulated difference. A merge and a
    restore write the same entries: they are saves like any other, and the
    owner has to see them next to the rest.
    """
    details = change_tracking.describe_draft_changes(
        previous_data, draft_data, id_names=_draft_change_id_names())
    if isinstance(section_statuses, dict) and section_statuses:
        for status_line in change_tracking.describe_section_status_changes(
                previous_statuses, section_statuses):
            details.append({'group': 'حالة الأقسام', 'text': status_line, 'kind': 'info'})
    if not previous:
        _record_change('draft', draft_id, 'إنشاء ملف مشروع',
                       details, source='manual', summary='تم إنشاء ملف المشروع')
        return
    grouped_details = {}
    for item in details:
        group_name = item.get('group') if isinstance(item, dict) else ''
        grouped_details.setdefault(str(group_name or ''), []).append(item)
    for group_name, group_items in grouped_details.items():
        if group_name == 'حالة الأقسام':
            entry_action = 'تحديث حالة الأقسام'
        elif group_name:
            entry_action = 'تعديل «%s»' % group_name
        else:
            entry_action = 'حفظ بيانات المشروع'
        _record_change('draft', draft_id, entry_action, group_items, source='manual')


def _merge_conflicting_draft_save(tenant_id, draft_id, base_revision, incoming, resolutions):
    """Merge a save that lost the race instead of overwriting the newer work.

    The base is the state the other side started from, rebuilt from the
    commit chain — the client only sends the revision it saved against. A
    field only the incoming side changed comes over, a field both sides
    changed differently is a conflict the caller has to decide on, and the
    merge lands on the main line as a new commit.
    """
    merged, changes, conflicts = db.draft_merge_preview_for_save(
        tenant_id, draft_id, base_revision, incoming,
        prefer_theirs=DRAFT_SAVE_PREFER_THEIRS)
    payload, unresolved = db.apply_merge_resolutions(merged, conflicts, resolutions)
    current = db.get_project_draft_by_id(tenant_id, draft_id) or {}
    if unresolved:
        return jsonify({
            'error': 'في تعارضات محتاجة قرار قبل الحفظ',
            'error_code': 'DRAFT_MERGE_CONFLICTS',
            'conflicts': unresolved,
            'currentRevision': int(current.get('revision') or 0),
        }), 409
    payload.pop('draftId', None)
    payload.pop('draft_id', None)
    stored = current.get('draft_data') or {}
    payload = _sanitize_save_workflow_claims(tenant_id, draft_id, payload, stored)
    changed_keys = [item.get('key') for item in (changes or [])]
    changed_keys += [item.get('key') for item in (conflicts or [])]
    statuses, demoted = _demote_sections_for_keys(
        tenant_id, [key for key in changed_keys if key], current.get('section_statuses') or {})
    try:
        db.save_project_draft(
            tenant_id, _project_draft_actor_id(), payload, statuses, 'draft',
            draft_id=draft_id,
            expected_revision=int(current.get('revision') or 0),
            commit_author_id=g.user_id,
            commit_author_name=_landloom_actor_name(),
            commit_message=DRAFT_SAVE_MERGE_COMMIT_MESSAGE,
            commit_kind='merge',
        )
    except db.DraftRevisionConflict as conflict:
        return jsonify({
            'error': 'المسودة تغيّرت في نسخة أخرى — أعد المحاولة',
            'error_code': 'DRAFT_REVISION_CONFLICT',
            'expectedRevision': conflict.expected_revision,
            'currentRevision': conflict.current_revision,
        }), 409
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    except db.DraftOverwriteRefused:
        return jsonify({
            'error': 'لم يتم الحفظ: البيانات المرسلة فارغة والمسودة المحفوظة تحتوي بيانات المشروع',
            'error_code': 'DRAFT_EMPTY_OVERWRITE',
        }), 409
    stored_draft = db.get_project_draft_by_id(tenant_id, draft_id) or {}
    _record_draft_save_change(
        draft_id, stored, payload, current.get('section_statuses') or {},
        statuses, current)
    return jsonify({
        'success': True,
        'merged': True,
        'draftId': draft_id,
        'revision': int(stored_draft.get('revision') or 0),
        'demotedSections': demoted,
        'sectionStatuses': stored_draft.get('section_statuses') or {},
    })


@app.route('/api/project-draft/<draft_id>/commits', methods=['GET'])
@require_auth
def api_list_draft_commits(draft_id):
    """The version chain of a project file, newest first."""
    draft, error = _versioned_draft_for_read(draft_id)
    if error:
        return jsonify(error), 404
    commits = db.list_draft_commits(g.tenant_id, draft_id, limit=200)
    return jsonify({
        'success': True,
        'draftId': draft_id,
        'title': draft.get('title') or '',
        'revision': int(draft.get('revision') or 0),
        'commits': commits,
    })


@app.route('/api/project-draft/<draft_id>/commits/<commit_id>', methods=['GET'])
@require_auth
def api_get_draft_commit(draft_id, commit_id):
    """What one version changed."""
    draft, error = _versioned_draft_for_read(draft_id)
    if error:
        return jsonify(error), 404
    commit = db.draft_commit_diff(g.tenant_id, draft_id, commit_id)
    if not commit:
        return _draft_commit_error('commit_not_found', 'النسخة غير موجودة', 404)
    for change in commit.get('changes') or []:
        change['label'] = _draft_commit_key_label(change.get('key'))
    return jsonify({'success': True, 'commit': commit})


def _draft_commit_key_label(key):
    """The visible Arabic name of a payload key, so a version reads as fields."""
    try:
        label = change_tracking.BLOB_KEY_LABELS.get(key)
        if label:
            return label
    except Exception:
        pass
    try:
        for field in db.PREBUILT_FIELDS:
            if field.get('key') == key:
                return field.get('label') or key
    except Exception:
        pass
    return key


@app.route('/api/project-draft/<draft_id>/commits/<commit_id>/restore', methods=['POST'])
@require_auth
def api_restore_draft_commit(draft_id, commit_id):
    """Carry an older version forward as a new commit."""
    draft, error = _versioned_draft_or_404(draft_id)
    if error:
        return jsonify(error), 404
    if g.user_id is not None and not _landloom_can('create_presentation'):
        return _landloom_forbidden('استرجاع نسخ المشروع يخص المحررين')
    status = db.normalize_proposal_status(draft.get('status'))
    if db.proposal_status_is_locked(status):
        return _draft_locked_response(status)
    target, meta = db.draft_state_at_commit(g.tenant_id, draft_id, commit_id)
    if target is None:
        return _draft_commit_error('commit_not_found', 'النسخة غير موجودة', 404)
    restored = dict(target)
    restored.pop('draftId', None)
    restored.pop('draft_id', None)
    stored = draft.get('draft_data') or {}
    restored = _sanitize_save_workflow_claims(g.tenant_id, draft_id, restored, stored)
    statuses, demoted = _restore_section_statuses(
        g.tenant_id, draft, restored, draft.get('section_statuses') or {})
    try:
        db.save_project_draft(
            g.tenant_id, _project_draft_actor_id(), restored, statuses, 'draft',
            draft_id=draft_id,
            expected_revision=int(draft.get('revision') or 0),
            commit_author_id=g.user_id,
            commit_author_name=_landloom_actor_name(),
            commit_message=DRAFT_RESTORE_COMMIT_MESSAGE,
            commit_kind='restore',
        )
    except db.DraftRevisionConflict as conflict:
        return _draft_commit_error(
            'DRAFT_REVISION_CONFLICT',
            'المسودة تغيّرت في نسخة أخرى منذ آخر قراءة — أعد تحميلها قبل الاسترجاع',
            409,
            expectedRevision=conflict.expected_revision,
            currentRevision=conflict.current_revision,
        )
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    except db.DraftOverwriteRefused as refused:
        return _draft_commit_error(
            'DRAFT_EMPTY_OVERWRITE',
            'لم يتم الاسترجاع: النسخة المطلوبة لا تحمل بيانات المشروع',
            409,
        )
    current = db.get_project_draft_by_id(g.tenant_id, draft_id) or {}
    saved_data = current.get('draft_data') or {}
    bookkeeping = set(getattr(db, 'DRAFT_BOOKKEEPING_KEYS', ()) or ())
    unverified = sorted(set((meta or {}).get('unverified_keys') or ()))
    unrestored = sorted(key for key in set(restored) | set(saved_data)
                        if key not in bookkeeping and key not in ('draftId', 'draft_id')
                        and saved_data.get(key) != restored.get(key))
    _record_draft_save_change(
        draft_id, stored, restored, draft.get('section_statuses') or {},
        statuses, draft)
    return jsonify({
        'success': True,
        'restored': True,
        'draftId': draft_id,
        'revision': int(current.get('revision') or 0),
        'demotedSections': demoted,
        'skippedKeys': (meta or {}).get('skipped_keys') or [],
        'unverifiedKeys': unverified,
        'unrestoredKeys': sorted(set(unrestored) | set(unverified)),
        'sectionStatuses': current.get('section_statuses') or {},
    })
