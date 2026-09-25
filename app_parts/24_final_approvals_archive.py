# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Post-generation artifacts (t15, t17, t18): final-file approval with
# stamping, the downloads ledger, proposal copies under a new unique name,
# and archive/restore/purge — the client never hard-deletes.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── t15: final file approval, stamping and the downloads ledger ─────────────

@app.route('/api/presentations/<presentation_id>/final-approval/request', methods=['POST'])
@require_permission('create_presentation')
def api_request_final_file_approval(presentation_id):
    pres = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'العرض غير موجود', 'error_code': 'presentation_not_found'}), 404
    approval = db.request_final_file_approval(
        g.tenant_id, presentation_id, _landloom_actor_id(), _landloom_actor_name(),
        revision=int((request.json or {}).get('revision') or 0),
    )
    failure = _landloom_error(approval)
    if failure:
        return failure
    try:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        title = (presentation or {}).get('title') or 'عرض'
        assigned = db.assigned_approver(
            g.tenant_id, (presentation or {}).get('draft_id'))
        db.create_approval_task(
            g.tenant_id, 'final_approval', f'اعتماد الملف النهائي «{title}»',
            entity_type='final_file_approval', entity_id=approval['id'],
            assignee_id=(assigned or {}).get('user_id'),
            assignee_name=(assigned or {}).get('user_name'),
            payload={'presentation_id': presentation_id}, due_hours=48,
            draft_id=(presentation or {}).get('draft_id'))
        recipients = ([{'id': assigned['user_id']}] if assigned
                      else db.get_users_with_permission(g.tenant_id, 'approve_final_file'))
        for approver in recipients:
            db.create_notification(
                g.tenant_id, 'طلب اعتماد ملف نهائي',
                f'«{title}» بانتظار قرار اعتماد الملف النهائي',
                category='final_approval', user_id=approver['id'],
                entity_type='final_file_approval', entity_id=approval['id'],
                mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_audit_event('final_file_approval.requested', 'final_file_approval', approval['id'],
                        new_value='pending', metadata={'presentation_id': presentation_id})
    return jsonify({'success': True, 'approval': approval})


@app.route('/api/final-file-approvals', methods=['GET'])
@require_auth
def api_list_final_file_approvals():
    approvals = db.list_final_file_approvals(
        g.tenant_id, presentation_id=request.args.get('presentationId'),
        status=request.args.get('status'),
        accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id),
    )
    return jsonify({'success': True, 'approvals': approvals})


@app.route('/api/final-file-approvals/<approval_id>/decision', methods=['POST'])
@require_auth
def api_decide_final_file_approval(approval_id):
    """Final-file gate decision: approve_final_file holders only, and never the
    requester unless the actor is a company-level administrator (d02)."""
    data = request.json or {}
    # ISS-014: the decision must stay inside the caller's project scope too.
    existing = db.get_final_file_approval(g.tenant_id, approval_id)
    if not existing:
        return jsonify({'error': 'الاعتماد غير موجود', 'error_code': 'approval_not_found'}), 404
    pres = db.get_presentation(existing['presentation_id'], tenant_id=g.tenant_id) \
        if existing.get('presentation_id') else None
    if data.get('decision') in {'approved', 'rejected'} \
            and not _landloom_can_decide('approve_final_file', (pres or {}).get('draft_id')):
        return _landloom_forbidden('اعتماد أو رفض الملف النهائي يتطلب صلاحية معتمد الملف')
    if not _presentation_in_scope(pres):
        return jsonify({'error': 'الاعتماد غير موجود', 'error_code': 'approval_not_found'}), 404
    result = db.decide_final_file_approval(
        g.tenant_id, approval_id, data.get('decision'), _landloom_actor_id(), _landloom_actor_name(),
        note=data.get('note'), allow_self=_landloom_actor_is_admin(), app_root=app.root_path,
    )
    failure = _landloom_error(result)
    if failure:
        return failure
    try:
        db.close_approval_tasks_for_entity(
            g.tenant_id, 'final_file_approval', approval_id,
            closed_by_name=_landloom_actor_name())
        requester = str(result.get('requested_by') or '')
        if not _recipient_is_actor(g.tenant_id, requester, _landloom_actor_id(),
                                   _landloom_actor_is_admin()):
            message = 'اعتُمد الملف النهائي' if data.get('decision') == 'approved' \
                else 'أُعيد الملف النهائي للتعديل'
            db.create_notification(
                g.tenant_id, message, str(data.get('note') or '').strip() or None,
                category='final_approval',
                user_id=requester,
                entity_type='final_file_approval', entity_id=approval_id,
                mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_audit_event(f"final_file_approval.{data.get('decision')}", 'final_file_approval',
                        approval_id, new_value=result.get('status'),
                        metadata={'note': data.get('note'), 'stamped_file': result.get('stamped_file')})
    return jsonify({'success': True, 'approval': result})


@app.route('/api/downloads', methods=['POST'])
@require_auth
def api_record_download():
    data = request.json or {}
    # ISS-014: the ledger entry must not point at a draft or presentation the
    # caller's project scope excludes.
    draft_id = data.get('draftId')
    if draft_id:
        draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
        if draft and not db.user_may_access_draft(g.user_id, draft):
            return jsonify({'error': 'Draft not found'}), 404
    if data.get('presentationId'):
        pres = db.get_presentation(data['presentationId'], tenant_id=g.tenant_id)
        if pres and not _presentation_in_scope(pres):
            return jsonify({'error': 'Presentation not found'}), 404
    row = db.record_download(
        g.tenant_id, data.get('fileName') or '', presentation_id=data.get('presentationId'),
        draft_id=data.get('draftId'), format=data.get('format') or 'pdf',
        version_label=data.get('versionLabel'),
        generated_by=_landloom_actor_id(), generated_by_name=_landloom_actor_name(),
        export_id=data.get('exportId'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('download.requested', 'presentation_download', row['id'],
                        metadata={'file_name': row.get('file_name'), 'format': row.get('format')})
    return jsonify({'success': True, 'download': row})


@app.route('/api/downloads', methods=['GET'])
@require_auth
def api_list_downloads():
    downloads = db.list_downloads(
        g.tenant_id, presentation_id=request.args.get('presentationId'),
        accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))
    return jsonify({'success': True, 'downloads': downloads})


@app.route('/api/downloads/<download_id>/delivered', methods=['POST'])
@require_auth
def api_mark_download_delivered(download_id):
    existing = db.get_download(g.tenant_id, download_id)
    if not existing:
        return jsonify({'error': 'التنزيل غير موجود', 'error_code': 'not_found'}), 404
    if existing.get('presentation_id'):
        pres = db.get_presentation(existing['presentation_id'], tenant_id=g.tenant_id)
        if not _presentation_in_scope(pres):
            return jsonify({'error': 'التنزيل غير موجود', 'error_code': 'not_found'}), 404
    result = db.mark_download_downloaded(g.tenant_id, download_id, downloaded_by_name=_landloom_actor_name())
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('download.delivered', 'presentation_download', download_id, new_value='downloaded')
    return jsonify({'success': True, 'download': result})


# ── t17: copy a proposal under a new mandatory unique name ──────────────────

@app.route('/api/project-draft/copy', methods=['POST'])
@require_permission('copy_presentation')
def api_copy_project_draft():
    data = request.json or {}
    source_draft_id = data.get('draftId') or _resolve_draft_id()
    source = db.get_project_draft_by_id(g.tenant_id, source_draft_id) if source_draft_id else None
    if source and not db.user_may_access_draft(g.user_id, source):
        return jsonify({'error': 'Draft not found', 'error_code': 'draft_not_found'}), 404
    result = db.copy_project_draft(
        g.tenant_id, source_draft_id, data.get('newTitle'),
        _landloom_actor_id(), _landloom_actor_name(), actor_user_id=g.user_id,
    )
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('proposal.copied', 'project_draft', result['draft_id'],
                        entity_name=result['title'],
                        metadata={'source_draft_id': result['source_draft_id']})
    return jsonify({'success': True, 'copy': result})


@app.route('/api/project-draft/copies', methods=['GET'])
@require_auth
def api_list_proposal_copies():
    return jsonify({'success': True, 'copies': db.list_proposal_copies(
        g.tenant_id, accessible_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))})


# ── t18: archive and restore; the client never hard-deletes ─────────────────

@app.route('/api/presentations/<presentation_id>/archive', methods=['POST'])
@require_auth
def api_archive_presentation(presentation_id):
    pres = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'العرض غير موجود', 'error_code': 'not_found'}), 404
    result = db.archive_presentation(g.tenant_id, presentation_id, _landloom_actor_id(), _landloom_actor_name())
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('presentation.archived', 'presentation', presentation_id,
                        old_value='active', new_value='archived')
    return jsonify({'success': True, 'presentation': result})


@app.route('/api/presentations/<presentation_id>/restore', methods=['POST'])
@require_auth
def api_restore_presentation(presentation_id):
    pres = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
    if not pres or not _presentation_in_scope(pres):
        return jsonify({'error': 'العرض غير موجود', 'error_code': 'not_found'}), 404
    result = db.restore_presentation(g.tenant_id, presentation_id)
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('presentation.restored', 'presentation', presentation_id,
                        old_value='archived', new_value='draft')
    return jsonify({'success': True, 'presentation': result})


@app.route('/api/admin/retention/purge', methods=['POST'])
@require_admin
def api_purge_expired_archives():
    """t18: the only delete path left — a platform sweep that removes archives
    older than the configured retention window. Never a user action."""
    result = db.purge_expired_archives()
    _record_audit_event('retention.purged', 'retention', 'archives',
                        new_value=result)
    return jsonify({'success': True, 'purged': result})
