@app.route('/api/project-draft/section-status', methods=['POST'])
@require_auth
def api_update_section_status():
    """Update one section's status, or several in a single atomic merge."""
    data = request.json or {}
    bulk = data.get('sectionStatuses')
    if isinstance(bulk, dict) and bulk:
        # Approving every section used to fire one request per section in parallel, and the
        # concurrent read-modify-write on the shared JSON column lost half of them.
        if any(not isinstance(key, str) or not key or value not in {'draft', 'approved'} for key, value in bulk.items()):
            return jsonify({'error': 'A valid sectionStatuses map is required'}), 400
        draft_id = _resolve_draft_id(data.get('draftId'))
        before = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
        # ISS-014/ISS-015: the draft must be in scope and a hidden section's
        # status is never the caller's to change.
        if before and not db.user_may_access_draft(g.user_id, before):
            return jsonify({'error': 'Draft not found'}), 404
        denied_sections = _hidden_field_sections()
        if denied_sections and any(key in denied_sections for key in bulk):
            return jsonify({'error': 'قسم غير متاح لهذا المستخدم',
                            'error_code': 'SECTION_FORBIDDEN'}), 403
        if bulk.get('location') == 'approved' and not _location_workflow_complete(before):
            return jsonify({'error': 'Site analysis approval and the four generated maps are required first',
                            'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
        if bulk.get('section-financial-calc') == 'approved':
            parking_error = _financial_parking_section_error(before, 'section-financial-calc')
            if parking_error:
                return jsonify(parking_error), 400
        if draft_id:
            blocked = db.pending_section_versions(g.tenant_id, draft_id, list(bulk))
            if blocked:
                return jsonify({'error': 'These sections await a version decision; decide on the sent version first',
                                'error_code': 'SECTION_VERSION_PENDING', 'sections': blocked}), 409
            versioned_blocked = []
            if before:
                section_map = _draft_field_section_map(g.tenant_id)
                for key, value in bulk.items():
                    if value != 'approved':
                        continue
                    state, _meta = _section_version_readiness(before, key, section_map)
                    if state in {'not_approved', 'stale', 'expired'}:
                        versioned_blocked.append(key)
            if versioned_blocked:
                return jsonify({'error': 'These sections have version snapshots; send and approve the version instead of toggling directly',
                                'error_code': 'SECTION_VERSION_REQUIRED', 'sections': versioned_blocked}), 409
        try:
            result = db.update_draft_section_statuses(
                g.tenant_id, _project_draft_actor_id(), bulk, draft_id=data.get('draftId')
            )
        except db.DraftLocked as locked:
            return _draft_locked_response(locked.status)
        if not result:
            return jsonify({'error': 'Unable to update section status'}), 400
        _record_change('draft', draft_id or _resolve_draft_id(), 'اعتماد الأقسام',
                       change_tracking.describe_section_status_changes(
                           (before or {}).get('section_statuses') if isinstance(before, dict) else {}, bulk))
        return jsonify({'success': True})
    section_key = data.get('sectionKey')
    section_status = data.get('sectionStatus')
    if not isinstance(section_key, str) or not section_key or section_status not in {'draft', 'approved'}:
        return jsonify({'error': 'A valid sectionKey and sectionStatus are required'}), 400
    draft_id = _resolve_draft_id(data.get('draftId'))
    before = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
    if before and not db.user_may_access_draft(g.user_id, before):
        return jsonify({'error': 'Draft not found'}), 404
    if _section_key_forbidden(section_key):
        return jsonify({'error': 'قسم غير متاح لهذا المستخدم',
                        'error_code': 'SECTION_FORBIDDEN'}), 403
    if section_key == 'location' and section_status == 'approved' and not _location_workflow_complete(before):
        return jsonify({'error': 'Site analysis approval and the four generated maps are required first',
                        'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
    if section_status == 'approved':
        parking_error = _financial_parking_section_error(before, section_key)
        if parking_error:
            return jsonify(parking_error), 400
    if draft_id and db.pending_section_versions(g.tenant_id, draft_id, [section_key]):
        return jsonify({'error': 'This section awaits a version decision; decide on the sent version first',
                        'error_code': 'SECTION_VERSION_PENDING', 'sections': [section_key]}), 409
    if section_status == 'approved' and before:
        state, meta = _section_version_readiness(
            before, section_key, _draft_field_section_map(g.tenant_id))
        if state in {'not_approved', 'stale', 'expired'}:
            code = {'not_approved': 'SECTION_VERSION_PENDING',
                    'stale': 'SECTION_VERSION_STALE',
                    'expired': 'SECTION_VERSION_EXPIRED'}[state]
            return jsonify({'error': 'This section has version snapshots; send and approve the version instead of toggling directly',
                            'error_code': code, 'sections': [section_key],
                            'version': (meta or {}).get('version_number')}), 409
    try:
        result = db.update_draft_section_status(
            g.tenant_id, _project_draft_actor_id(), section_key, section_status, draft_id=data.get('draftId')
        )
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    if not result:
        return jsonify({'error': 'Unable to update section status'}), 400
    _record_change('draft', draft_id or _resolve_draft_id(), 'اعتماد قسم',
                   change_tracking.describe_section_status_changes(
                       (before or {}).get('section_statuses') if isinstance(before, dict) else {},
                       {section_key: section_status}))
    return jsonify({'success': True})


@app.route('/api/project-draft/section-version', methods=['POST'])
@require_auth
def api_send_section_for_approval():
    """Freeze this moment's section inputs as a new pending version for approval."""
    data = request.json or {}
    section_key = data.get('sectionKey')
    if not isinstance(section_key, str) or not section_key.strip():
        return jsonify({'error': 'A valid sectionKey is required'}), 400
    section_key = section_key.strip()
    draft, error = _versioned_draft_or_404(_resolve_draft_id(data.get('draftId')))
    if error:
        return jsonify(error), 404
    # ISS-015: a section hidden from the caller cannot be sent for approval.
    if _section_key_forbidden(section_key):
        return jsonify({'error': 'قسم غير متاح لهذا المستخدم',
                        'error_code': 'SECTION_FORBIDDEN'}), 403
    if section_key == 'location' and not _location_workflow_complete(draft):
        return jsonify({'error': 'Site analysis approval and the four generated maps are required first',
                        'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
    parking_error = _financial_parking_section_error(draft, section_key)
    if parking_error:
        return jsonify(parking_error), 400
    stored = draft.get('draft_data') or {}
    section_map = _draft_field_section_map(g.tenant_id)
    snapshot = _section_snapshot_slice(stored, section_key, section_map)
    missing = _section_required_missing_labels(g.tenant_id, section_key, snapshot)
    if missing:
        return jsonify({'error': 'Required section fields are missing',
                        'error_code': 'SECTION_VERSION_INCOMPLETE', 'missing': missing}), 400
    version = db.create_section_version(
        g.tenant_id, draft['id'], section_key, snapshot,
        _project_draft_actor_id(), _project_draft_actor_name(),
        allow_supersede=bool(data.get('supersede')),
    )
    if version.get('error') == 'draft_not_found':
        return jsonify({'error': 'No project draft found'}), 404
    if version.get('error') == 'unknown_section':
        return jsonify({'error': 'Unknown project section'}), 400
    if version.get('error') == 'draft_locked':
        return _draft_locked_response(version.get('status'))
    if version.get('error') == 'version_pending_exists':
        # t13-04: a send already under review is never dropped silently; the
        # client either cancels it or resubmits with supersede=true.
        return jsonify({'error': 'يوجد إصدار قيد المراجعة لهذا القسم بالفعل',
                        'error_code': 'SECTION_VERSION_PENDING_EXISTS',
                        'version_id': version.get('version_id'),
                        'version_number': version.get('version_number')}), 409
    if version.get('error'):
        return jsonify({'error': 'Unable to store the section snapshot'}), 400
    try:
        # t13-01: every send opens an approver task and notifies the approvers
        # whose section scope covers this key. When the draft carries an
        # assigned approver the request goes to them alone — responsibility
        # assignments outrank the permission broadcast.
        assigned = db.assigned_approver(g.tenant_id, draft['id'])
        db.create_approval_task(
            g.tenant_id, 'section_approval',
            f'اعتماد قسم «{_section_version_label(section_key)}»',
            entity_type='section_version', entity_id=version['id'],
            section_key=section_key,
            assignee_id=(assigned or {}).get('user_id'),
            assignee_name=(assigned or {}).get('user_name'),
            payload={'draft_id': draft['id'], 'version_number': version['version_number']},
            due_hours=48, draft_id=draft['id'])
        if assigned:
            db.create_notification(
                g.tenant_id, 'إصدار قسم بانتظار الاعتماد',
                f'«{draft.get("title") or "مشروع"}» — القسم {_section_version_label(section_key)} بانتظار قرارك',
                category='section_approval', user_id=assigned['user_id'],
                entity_type='section_version', entity_id=version['id'],
                mirror_admin=not _landloom_actor_is_admin(), email_to=None)
        else:
            for approver in db.get_users_with_permission(g.tenant_id, 'approvals'):
                try:
                    if not db.get_user_field_sections(approver['id'], g.tenant_id).get(section_key, True):
                        continue
                except Exception:
                    continue
                db.create_notification(
                    g.tenant_id, 'إصدار قسم بانتظار الاعتماد',
                    f'«{draft.get("title") or "مشروع"}» — القسم {_section_version_label(section_key)} بانتظار قرارك',
                    category='section_approval', user_id=approver['id'],
                    entity_type='section_version', entity_id=version['id'],
                    mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_change('draft', draft['id'], 'إرسال قسم للاعتماد',
                   [f'القسم {_section_version_label(section_key)}: لقطة رقم {version["version_number"]} بانتظار القرار'])
    _record_audit_event(
        action='section_version_submitted',
        entity_type='section_version',
        entity_id=version['id'],
        entity_name=f'القسم {_section_version_label(section_key)} (إصدار {version["version_number"]})',
        new_value=version.get('snapshot'),
        metadata={'draft_id': draft['id'], 'section_key': section_key, 'version_number': version['version_number']},
    )
    return jsonify({'success': True, 'version': version})


@app.route('/api/project-draft/section-versions', methods=['GET'])
@require_auth
def api_list_section_versions():
    """Newest-first version history of a draft, metadata only."""
    draft, error = _versioned_draft_for_read(_resolve_draft_id(request.args.get('draftId')))
    if error:
        return jsonify(error), 404
    section_key = request.args.get('sectionKey') or None
    versions = db.list_section_versions(g.tenant_id, draft['id'], section_key)
    # ISS-015: versions of hidden sections are not the caller's to see.
    denied = _hidden_field_sections()
    if denied:
        versions = [v for v in versions if v.get('section_key') not in denied]
    return jsonify({'success': True, 'versions': versions})


@app.route('/api/project-draft/section-versions/<version_id>', methods=['GET'])
@require_auth
def api_get_section_version(version_id):
    """One version with its immutable snapshot, for history and comparison."""
    version = db.get_section_version(g.tenant_id, version_id, include_snapshot=True)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    _draft, error = _versioned_draft_for_read(version.get('draft_id'))
    if error:
        return jsonify({'error': 'Section version not found'}), 404
    # ISS-015: a hidden section's snapshot never leaves the server.
    if _section_key_forbidden(version.get('section_key')):
        return jsonify({'error': 'Section version not found'}), 404
    return jsonify({'success': True, 'version': version})


@app.route('/api/project-draft/section-version/decision', methods=['POST'])
@require_auth
def api_decide_section_version():
    """Approve, return or reject one sent version; the decision names its number."""
    data = request.json or {}
    version_id = data.get('versionId')
    decision = data.get('decision')
    if not version_id or decision not in {'approved', 'returned', 'rejected'}:
        return jsonify({'error': 'A valid versionId and decision are required'}), 400
    version = db.get_section_version(g.tenant_id, version_id, include_snapshot=False)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    draft, error = _versioned_draft_for_decide(version.get('draft_id'))
    if error:
        return jsonify(error), 404
    actor_id = _project_draft_actor_id()
    # t13-02: a non-admin approver decides only inside their granted field
    # sections; keys outside the field map stay governed by the approvals
    # permission that already let this caller reach the decision. The draft's
    # assigned approver is responsible for every section in it.
    assigned_approver = False
    try:
        assigned_approver = db.user_is_assigned_approver(
            g.tenant_id, g.user_id, draft.get('id'))
    except Exception:
        pass
    if not _landloom_actor_is_admin() and str(draft.get('user_id')) != str(actor_id) \
            and not assigned_approver:
        section_key = version['section_key']
        if section_key in db.DEFAULT_FIELD_SECTIONS:
            try:
                granted = db.get_user_field_sections(g.user_id, g.tenant_id)
            except Exception:
                granted = {}
            if not granted.get(section_key):
                return jsonify({'error': 'هذا القسم خارج نطاق اعتمادك',
                                'error_code': 'section_scope_forbidden'}), 403
    if decision == 'approved' and version['section_key'] == 'section-financial-calc':
        parking_error = _financial_parking_section_error(draft, version['section_key'])
        if not parking_error:
            snapshot = (db.get_section_version(g.tenant_id, version_id, include_snapshot=True) or {}).get('snapshot') or {}
            parking_error = _financial_parking_section_error(
                {'draft_data': {**(draft.get('draft_data') or {}), **snapshot}}, version['section_key'])
        if parking_error:
            return jsonify(parking_error), 400
    decided = db.decide_section_version(
        g.tenant_id, version_id, decision,
        actor_id, _project_draft_actor_name(), data.get('note'),
    )
    if decided.get('error') == 'version_not_found':
        return jsonify({'error': 'Section version not found'}), 404
    if decided.get('error') == 'version_not_pending':
        return jsonify({'error': 'This version was already decided',
                        'error_code': 'SECTION_VERSION_DECIDED'}), 409
    if decided.get('error') == 'draft_locked':
        return _draft_locked_response(decided.get('status'))
    if decided.get('error') == 'note_required':
        return jsonify({'error': 'A reason is required to return or reject a version'}), 400
    if decided.get('error') == 'self_approval_blocked_by_policy':
        return jsonify({'error': 'سياسة الشركة تمنع المحرر من اعتماد قسمه بنفسه',
                        'error_code': 'self_approval_blocked_by_policy'}), 403
    if decided.get('error'):
        return jsonify({'error': 'Unable to record the version decision'}), 400
    mirror = 'approved' if decision == 'approved' else 'draft'
    try:
        db.update_draft_section_status_by_id(
            g.tenant_id, draft['id'], {version['section_key']: mirror}
        )
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    action = {'approved': 'اعتماد نسخة قسم', 'returned': 'إعادة نسخة قسم للتعديل', 'rejected': 'رفض نسخة قسم'}[decision]
    detail = f'القسم {_section_version_label(version["section_key"])}: لقطة رقم {version["version_number"]} — {action}'
    if decided.get('decision_note'):
        detail += f' (السبب: {decided["decision_note"]})'
    if (version.get('created_by') or '') == actor_id:
        detail += ' (اعتماد ذاتي)'
    try:
        # t13-03: the decision closes the approver task; a return opens an
        # editor task for the version's sender and notifies them.
        db.close_approval_tasks_for_entity(
            g.tenant_id, 'section_version', version_id,
            closed_by_name=_project_draft_actor_name())
        sender = str(version.get('created_by') or '')
        if decision in {'returned', 'rejected'}:
            db.create_approval_task(
                g.tenant_id, 'revision',
                f'إعادة قسم «{_section_version_label(version["section_key"])}» للتعديل',
                entity_type='project_draft', entity_id=draft['id'],
                section_key=version['section_key'],
                assignee_id=None if sender.startswith('tenant-admin:') else sender or None,
                payload={'version_id': version_id, 'note': decided.get('decision_note')},
                draft_id=draft['id'])
        # The admin sees every staff exchange, but a verdict on work he
        # submitted himself is his own loop closing — it stays in the draft
        # history and audit trail without pinging his feed.
        if not _recipient_is_actor(g.tenant_id, sender, actor_id, _landloom_actor_is_admin()) \
                and not _recipient_is_tenant_admin(g.tenant_id, sender):
            message = {'approved': 'اعتُمد قسمك',
                       'returned': 'أُعيد قسمك للتعديل',
                       'rejected': 'رُفض قسمك'}[decision]
            db.create_notification(
                g.tenant_id, message,
                f'«{draft.get("title") or "مشروع"}» — القسم {_section_version_label(version["section_key"])}',
                category='section_approval',
                user_id=sender,
                entity_type='section_version', entity_id=version_id,
                mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_change('draft', draft['id'], action, [detail])
    _record_audit_event(
        action=f'section_version_{decision}',
        entity_type='section_version',
        entity_id=version_id,
        entity_name=f'القسم {_section_version_label(version["section_key"])} (إصدار {version["version_number"]})',
        old_value={'status': 'pending'},
        new_value={'status': decided.get('status'), 'decision_note': data.get('note')},
        metadata={'draft_id': draft['id'], 'section_key': version['section_key'], 'version_number': version['version_number']},
    )
    return jsonify({'success': True, 'version': decided})


@app.route('/api/project-draft/section-version/cancel', methods=['POST'])
@require_auth
def api_cancel_section_version():
    """Withdraw a pending send so the editor keeps working on a later draft."""
    data = request.json or {}
    version_id = data.get('versionId')
    if not version_id:
        section_key = (data.get('sectionKey') or '').strip() if isinstance(data.get('sectionKey'), str) else ''
        draft, error = _versioned_draft_or_404(_resolve_draft_id(data.get('draftId')))
        if error:
            return jsonify(error), 404
        if not section_key:
            return jsonify({'error': 'A valid versionId is required'}), 400
        pending = [item for item in db.list_section_versions(g.tenant_id, draft['id'], section_key)
                   if (item.get('status') or '') == 'pending']
        if not pending:
            return jsonify({'error': 'No pending version to cancel'}), 404
        version_id = pending[0]['id']
    version = db.get_section_version(g.tenant_id, version_id, include_snapshot=False)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    draft, error = _versioned_draft_for_read(version.get('draft_id'))
    if error:
        return jsonify(error), 404
    if _section_key_forbidden(version.get('section_key')):
        return jsonify({'error': 'Section version not found'}), 404
    if draft.get('user_id') != _project_draft_actor_id() and not _has_approvals_permission() \
            and str(version.get('created_by') or '') != str(_project_draft_actor_id()):
        return jsonify({'error': 'Section version not found'}), 404
    cancelled = db.cancel_section_version(
        g.tenant_id, version_id,
        _project_draft_actor_id(), _project_draft_actor_name(),
    )
    if cancelled.get('error') == 'version_not_found':
        return jsonify({'error': 'Section version not found'}), 404
    if cancelled.get('error') == 'version_not_pending':
        return jsonify({'error': 'This version was already decided',
                        'error_code': 'SECTION_VERSION_DECIDED'}), 409
    if cancelled.get('error') == 'draft_locked':
        return _draft_locked_response(cancelled.get('status'))
    if cancelled.get('error'):
        return jsonify({'error': 'Unable to cancel the section version'}), 400
    try:
        db.close_approval_tasks_for_entity(
            g.tenant_id, 'section_version', version_id,
            closed_by_name=_project_draft_actor_name(), cancel_reason='سحب طلب الاعتماد')
    except Exception:
        pass
    _record_change('draft', draft['id'], 'إلغاء طلب اعتماد قسم',
                   [f'القسم {_section_version_label(version["section_key"])}: لقطة رقم {version["version_number"]} أُلغيت'])
    _record_audit_event(
        action='section_version_cancelled',
        entity_type='section_version',
        entity_id=version_id,
        entity_name=f'القسم {_section_version_label(version["section_key"])} (إصدار {version["version_number"]})',
        old_value={'status': 'pending'},
        new_value={'status': 'cancelled'},
        metadata={'draft_id': draft['id'], 'section_key': version['section_key']},
    )
    return jsonify({'success': True, 'version': cancelled})
