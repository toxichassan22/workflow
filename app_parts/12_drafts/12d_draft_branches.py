"""Branches of a project file — work in parallel, merge like git.

A branch is a forked copy of the project file: the person opens the version
they are working from, forks it, and their edits land on the branch instead
of over the main line. When the work is ready, the merge is a three-way merge
over the payload keys — a key one side changed is taken, a key both sides
changed differently is a conflict the person resolves by hand.

Nothing here adds an approval gate: the merge is a save, and it lands as a
new commit on the main line.
"""

DRAFT_BRANCH_DEFAULT_NAME = 'فرع'


def _branch_error(code, message, status=400, **extra):
    payload = {'error': message, 'error_code': code}
    payload.update(extra)
    return jsonify(payload), status


def _editable_draft_or_404(draft_id):
    """The draft the caller may write to: their own, or one assigned to them."""
    draft, error = _versioned_draft_or_404(draft_id)
    if error:
        return None, error
    if g.user_id is not None and not _landloom_can('create_presentation'):
        return None, {'error': 'تحرير الفروع يخص المحررين'}
    return draft, None


@app.route('/api/project-draft/<draft_id>/branches', methods=['GET'])
@require_auth
def api_list_draft_branches(draft_id):
    """The branches of a project file."""
    draft, error = _versioned_draft_for_read(draft_id)
    if error:
        return jsonify(error), 404
    branches = db.list_draft_branches(g.tenant_id, draft_id)
    return jsonify({'success': True, 'draftId': draft_id, 'branches': branches})


@app.route('/api/project-draft/<draft_id>/branches', methods=['POST'])
@require_auth
def api_create_draft_branch(draft_id):
    """Fork the project file into a branch."""
    draft, error = _editable_draft_or_404(draft_id)
    if error:
        return jsonify(error), 404
    data = request.json or {}
    created = db.create_draft_branch(
        g.tenant_id, draft_id,
        author_id=g.user_id,
        author_name=_landloom_actor_name(),
        name=(data.get('name') or '').strip() or DRAFT_BRANCH_DEFAULT_NAME,
        base_commit_id=(data.get('baseCommitId') or '').strip() or None,
    )
    if created.get('error'):
        code = created['error']
        if code == 'draft_not_found':
            return _branch_error(code, 'المشروع غير موجود', 404)
        if code == 'draft_locked':
            return _draft_locked_response(created.get('status'))
        if code == 'commit_not_found':
            return _branch_error(code, 'النسخة غير موجودة', 404)
        return _branch_error(code, 'تعذر إنشاء الفرع', 409, detail=created.get('detail'))
    return jsonify(created)


@app.route('/api/project-draft/<draft_id>/branches/<branch_id>/preview', methods=['GET'])
@require_auth
def api_preview_draft_branch_merge(draft_id, branch_id):
    """What merging the branch would change, and where it would conflict."""
    draft, error = _versioned_draft_for_read(draft_id)
    if error:
        return jsonify(error), 404
    preview = db.draft_branch_merge_preview(g.tenant_id, draft_id, branch_id)
    if preview.get('error'):
        code = preview['error']
        if code in ('branch_not_found', 'draft_not_found'):
            return _branch_error(code, 'الفرع غير موجود', 404)
        if code == 'branch_already_merged':
            return _branch_error(code, 'تم دمج هذا الفرع بالفعل', 409)
        return _branch_error(code, 'تعذر قراءة الفرع', 409)
    return jsonify(preview)


@app.route('/api/project-draft/<draft_id>/branches/<branch_id>/merge', methods=['POST'])
@require_auth
def api_merge_draft_branch(draft_id, branch_id):
    """Merge a branch into the main line as a new commit."""
    draft, error = _editable_draft_or_404(draft_id)
    if error:
        return jsonify(error), 404
    status = db.normalize_proposal_status(draft.get('status'))
    if db.proposal_status_is_locked(status):
        return _draft_locked_response(status)
    data = request.json or {}
    preview = db.draft_branch_merge_preview(g.tenant_id, draft_id, branch_id)
    if preview.get('error'):
        code = preview['error']
        if code in ('branch_not_found', 'draft_not_found'):
            return _branch_error(code, 'الفرع غير موجود', 404)
        if code == 'branch_already_merged':
            return _branch_error(code, 'تم دمج هذا الفرع بالفعل', 409)
        return _branch_error(code, 'تعذر قراءة الفرع', 409)
    branch = preview.get('branch') or {}
    branch_draft = db.get_project_draft_by_id(g.tenant_id, branch.get('branch_draft_id')) or {}
    branch_status = db.normalize_proposal_status(branch_draft.get('status'))
    if db.proposal_status_is_locked(branch_status):
        return _draft_locked_response(branch_status)
    merged, unresolved = db.apply_merge_resolutions(
        preview.get('merged') or {}, preview.get('conflicts') or [], data.get('resolutions'))
    if unresolved:
        return _branch_error(
            'MERGE_CONFLICTS_UNRESOLVED',
            'في تعارضات محتاجة قرار قبل الدمج',
            409,
            conflicts=unresolved,
        )
    merged.pop('draftId', None)
    merged.pop('draft_id', None)
    stored = draft.get('draft_data') or {}
    merged = _sanitize_save_workflow_claims(g.tenant_id, draft_id, merged, stored)
    changed_keys = [item.get('key') for item in (preview.get('changes') or [])]
    changed_keys += [item.get('key') for item in (preview.get('conflicts') or [])]
    statuses, demoted = _demote_sections_for_keys(
        g.tenant_id, [key for key in changed_keys if key], draft.get('section_statuses') or {})
    branch_name = branch.get('name') or branch.get('branch_label') or DRAFT_BRANCH_DEFAULT_NAME
    try:
        db.save_project_draft(
            g.tenant_id, _project_draft_actor_id(), merged, statuses, 'draft',
            draft_id=draft_id,
            expected_revision=int(draft.get('revision') or 0),
            commit_author_id=g.user_id,
            commit_author_name=_landloom_actor_name(),
            commit_message=f'دمج فرع: {branch_name}',
            commit_kind='merge',
        )
    except db.DraftRevisionConflict as conflict:
        return _branch_error(
            'DRAFT_REVISION_CONFLICT',
            'المسودة تغيّرت في نسخة أخرى منذ آخر قراءة — أعد تحميلها قبل الدمج',
            409,
            expectedRevision=conflict.expected_revision,
            currentRevision=conflict.current_revision,
        )
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    except db.DraftOverwriteRefused:
        return _branch_error(
            'DRAFT_EMPTY_OVERWRITE',
            'لم يتم الدمج: النسخة المطلوبة لا تحمل بيانات المشروع',
            409,
        )
    commits = db.list_draft_commits(g.tenant_id, draft_id, limit=1)
    merged_commit_id = commits[0]['id'] if commits else None
    db.finish_draft_branch_merge(g.tenant_id, draft_id, branch_id, merged_commit_id)
    current = db.get_project_draft_by_id(g.tenant_id, draft_id) or {}
    return jsonify({
        'success': True,
        'merged': True,
        'draftId': draft_id,
        'revision': int(current.get('revision') or 0),
        'mergedCommitId': merged_commit_id,
        'demotedSections': demoted,
        'sectionStatuses': current.get('section_statuses') or {},
    })


@app.route('/api/project-draft/<draft_id>/branches/<branch_id>', methods=['DELETE'])
@require_auth
def api_discard_draft_branch(draft_id, branch_id):
    """Drop a branch and the forked copy that carried it."""
    draft, error = _editable_draft_or_404(draft_id)
    if error:
        return jsonify(error), 404
    result = db.discard_draft_branch(g.tenant_id, draft_id, branch_id)
    if result.get('error'):
        code = result['error']
        if code == 'branch_not_found':
            return _branch_error(code, 'الفرع غير موجود', 404)
        if code == 'branch_already_merged':
            return _branch_error(code, 'تم دمج هذا الفرع بالفعل', 409)
        return _branch_error(code, 'تعذر حذف الفرع', 409)
    return jsonify(result)
