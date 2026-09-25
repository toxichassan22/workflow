

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Landloom platform API core + generation approvals (t14): the shared
# Landloom error-code maps and actor/permission helpers every later part
# reuses, then cost-estimated generation approvals gated on points
# reservation and the background generation-job lifecycle
# (create/list/get/heartbeat/finish) with the client-visible reservations
# list. Money stays in tenant_ledger; these endpoints track workflow state
# only.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_LANDLOOM_NOT_FOUND = {
    'draft_not_found', 'presentation_not_found', 'request_not_found',
    'reservation_not_found', 'ticket_not_found', 'task_not_found', 'approval_not_found',
    'user_not_found', 'tenant_not_found', 'job_not_found', 'package_not_found',
}
_LANDLOOM_CONFLICT = {'title_exists', 'role_name_exists', 'approval_already_pending', 'presentation_not_archived',
                   'invalid_transition', 'approval_not_pending', 'request_not_pending', 'reservation_not_reserved',
                   'request_not_active', 'version_pending_exists', 'inputs_changed', 'content_changed',
                   'unchanged_since_rejection', 'already_approved', 'section_version_expired',
                   'sections_not_approved', 'section_not_approved', 'archive_required',
                   'job_not_approved', 'job_not_active'}
_LANDLOOM_FORBIDDEN = {'self_approval_not_allowed', 'cancel_not_allowed', 'platform_tenant_recharge_forbidden',
                    'manual_transition_not_allowed', 'self_approval_blocked_by_policy',
                    'section_scope_forbidden', 'post_approval_edit_required', 'admin_required',
                    'final_approval_required'}

# Arabic-first messages: these strings land directly in UI toasts.
_LANDLOOM_ERROR_MESSAGES_AR = {
    'draft_not_found': 'لا يوجد مشروع مطابق',
    'presentation_not_found': 'العرض غير موجود',
    'request_not_found': 'الطلب غير موجود',
    'reservation_not_found': 'الحجز غير موجود',
    'ticket_not_found': 'التذكرة غير موجودة',
    'task_not_found': 'العنصر غير موجود',
    'approval_not_found': 'الاعتماد غير موجود',
    'title_exists': 'يوجد عرض بنفس الاسم',
    'role_name_exists': 'يوجد دور بنفس الاسم',
    'approval_already_pending': 'يوجد اعتماد قيد المراجعة بالفعل',
    'presentation_not_archived': 'العرض ليس في الأرشيف',
    'insufficient_balance': 'الرصيد غير كافٍ لتغطية التكلفة التقديرية',
    'title_required': 'العنوان مطلوب',
    'name_required': 'الاسم مطلوب',
    'subject_required': 'موضوع التذكرة مطلوب',
    'body_required': 'نص الرسالة مطلوب',
    'invalid_decision': 'قرار غير معروف',
    'invalid_status': 'حالة غير معروفة',
    'invalid_recurrence': 'قيمة التكرار غير صحيحة',
    'cancel_not_allowed': 'لا يمكن إلا لمقدم الطلب إلغاء الاعتماد',
    'not_approved': 'يجب اعتماد العرض قبل طلب الملف النهائي',
    'no_export_file': 'صدّر العرض قبل طلب الملف',
    'approval_not_approved': 'لم يُعتمد الاعتماد بعد',
    'approval_not_pending': 'انتهت مراجعة هذا الاعتماد بالفعل',
    'request_not_pending': 'انتهت مراجعة هذا الطلب بالفعل',
    'self_approval_not_allowed': 'لا يمكن اعتماد أو رفض طلب قدّمه نفس المستخدم؛ القرار لمعتمد آخر',
    'platform_tenant_recharge_forbidden': 'حساب المنصة لا يستقبل شحن محفظة',
    'sections_not_approved': 'يجب اعتماد جميع أقسام المشروع قبل اعتماد التوليد',
    'task_not_open': 'المهمة مغلقة بالفعل',
    'key_and_label_required': 'المفتاح والتسمية العربية مطلوبان',
    'package_name_required': 'اختر الباقة المطلوب شراؤها',
    'package_required': 'اختر الباقة المطلوب شراؤها',
    'package_not_found': 'الباقة غير موجودة أو موقوفة',
    'reference_or_receipt_required': 'رقم الحوالة أو إيصال التحويل مطلوب',
    'stamp_failed': 'تعذر ختم الملف',
    'nothing_to_reserve': 'لا توجد نقاط لحجزها',
    'reservation_not_reserved': 'تم تسوية الحجز مسبقًا',
    'draft_locked': 'المشروع مقفل في حالته الحالية ولا يقبل هذا الإجراء',
    'invalid_transition': 'لا يمكن الانتقال إلى هذه الحالة من الحالة الحالية',
    'manual_transition_not_allowed': 'هذه الحالة تصل إليها مسارات الاعتماد فقط، لا الانتقال اليدوي',
    'reason_required': 'السبب إلزامي لهذا الإجراء',
    'note_required': 'سبب الرفض إلزامي',
    'lifecycle_transition_failed': 'تعذر تحديث حالة المشروع المرتبطة بالاعتماد',
    'missing_arguments': 'بيانات ناقصة لإتمام الإجراء',
    'user_not_found': 'المستخدم غير موجود',
    'tenant_not_found': 'الشركة غير موجودة',
    'invalid_scope': 'نطاق الوصول غير معروف',
    'request_not_active': 'لا يوجد وصول نشط لإلغائه',
    'invalid_policy_value': 'قيمة السياسة غير معروفة',
    'no_policy_updates': 'لا توجد سياسات لتحديثها',
    'self_approval_blocked_by_policy': 'سياسة الشركة تمنع المحرر من اعتماد قسمه بنفسه',
    'version_pending_exists': 'يوجد إصدار قيد المراجعة لهذا القسم بالفعل',
    'inputs_changed': 'مدخلات المشروع تغيّرت منذ طلب اعتماد التوليد — أعد الطلب',
    'content_changed': 'محتوى الملف تغيّر بعد إرساله للاعتماد — أعد الإرسال',
    'unchanged_since_rejection': 'الملف مرفوض ولم يتغير محتواه — عدّل الملف ثم أعد الإرسال',
    'already_approved': 'هذا الملف معتمد بالفعل ولم يتغير محتواه',
    'section_version_expired': 'انتهت صلاحية اعتماد بعض الأقسام — أعد إرسالها للاعتماد',
    'sections_not_approved': 'يجب اعتماد جميع أقسام المشروع قبل هذه الخطوة',
    'section_not_approved': 'توليد هذا القسم يتطلب اعتماده أولًا',
    'invalid_section': 'قسم المشروع غير صالح',
    'archive_required': 'لهذا السجل مسار اعتماد محفوظ — استخدم الأرشفة بدل الحذف',
    'job_not_found': 'مهمة التوليد غير موجودة',
    'job_not_approved': 'مهمة التوليد تتطلب اعتمادًا ساريًا',
    'job_not_active': 'المهمة ليست قيد التنفيذ',
    'invalid_job_status': 'حالة المهمة غير معروفة',
    'section_scope_forbidden': 'هذا القسم خارج نطاق اعتمادك',
    'post_approval_edit_required': 'تعديل ملف معتمد يتطلب صلاحية التعديل بعد الاعتماد وسببًا مسجلًا',
    'admin_required': 'هذا الإجراء يتطلب صلاحية مدير الشركة',
    'final_approval_required': 'الملف غير معتمد نهائيًا — التنزيل الرسمي بعد الاعتماد فقط',
}


def _landloom_error(result):
    """Map a db-layer error dict to the right HTTP response, or None on success."""
    if not isinstance(result, dict) or not result.get('error'):
        return None
    code = result['error']
    default_message = _LANDLOOM_ERROR_MESSAGES_AR.get(code, 'حدث خطأ، أعد المحاولة')
    payload = {'error': default_message, 'error_code': code}
    # Machine-readable companions: the client reuses a pending approval or shows
    # which lifecycle state refused the move.
    for extra_key in ('approval_id', 'current_status', 'target_status', 'status',
                      'sections', 'version_id', 'version_number', 'job_id'):
        if result.get(extra_key):
            payload[extra_key] = result[extra_key]
    if code in _LANDLOOM_NOT_FOUND:
        return jsonify(payload), 404
    if code in _LANDLOOM_CONFLICT:
        return jsonify(payload), 409
    if code in _LANDLOOM_FORBIDDEN:
        return jsonify(payload), 403
    if code == 'insufficient_balance':
        return jsonify(payload), 402
    if code == 'draft_locked':
        return _draft_locked_response(result.get('status'))
    return jsonify(payload), 400


def _landloom_actor_id():
    return getattr(g, 'user_id', None) or f'tenant-admin:{g.tenant_id}'


def _landloom_actor_name():
    return getattr(g, 'user_name', None) or 'Company administrator'


def _landloom_actor_is_admin():
    """Company-level administrators may combine requester and approver hats (d02).

    The company admin is the tenant-direct identity: ``g.user_id`` is None for
    it (a primary-admin token is normalized to it), so employees — including
    ones holding every company permission — stay distinguishable from it."""
    return bool(getattr(g, 'is_admin', False)) or getattr(g, 'user_id', None) is None


def _landloom_can(permission_key):
    """True when the actor holds permission_key; admins and tenant-direct logins always do."""
    if _landloom_actor_is_admin():
        return True
    perms = getattr(g, 'user_permissions', None)
    if not perms:
        perms = db.get_user_permissions(g.user_id, getattr(g, 'user_role', None) or 'employee')
    return bool(perms.get(permission_key))


def _landloom_can_decide(permission_key, draft_id):
    """One approver per project: when the draft carries an assigned approver,
    only they (or a company admin) may decide — the bare permission no longer
    outranks the assignment. Without an assignment the permission pool stays."""
    if draft_id:
        try:
            assigned = db.assigned_approver(g.tenant_id, draft_id)
        except Exception:
            assigned = None
        if assigned:
            if _landloom_actor_is_admin():
                return True
            return str(assigned.get('user_id') or '') == str(g.user_id or '')
    if _landloom_can(permission_key):
        return True
    try:
        return db.user_is_assigned_approver(g.tenant_id, g.user_id, draft_id)
    except Exception:
        return False


def _landloom_has_approver_assignment():
    """Any approver row for this user — gates the approver-facing lists."""
    try:
        rows = db.list_user_assignments(g.tenant_id, g.user_id)
        return any(r.get('role') == 'approver' for r in rows)
    except Exception:
        return False


def _landloom_forbidden(message='هذا الإجراء يتطلب صلاحية الاعتماد المختصة'):
    return jsonify({'error': message, 'error_code': 'permission_required'}), 403



# ── t14: generation approval with cost estimate and points reservation ──────

@app.route('/api/generation-approvals', methods=['POST'])
@require_permission('create_presentation')
def api_create_generation_approval():
    """Open a generation approval carrying the estimate shown to the approver."""
    data = request.json or {}
    draft_id = data.get('draftId') or _resolve_draft_id()
    if not draft_id:
        return jsonify({'error': 'No project draft found', 'error_code': 'draft_not_found'}), 404
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return jsonify({'error': 'No project draft found', 'error_code': 'draft_not_found'}), 404
    # t20: a scope-limited user may only request generation for drafts in scope.
    if not _landloom_actor_is_admin() and not db.user_may_access_draft(g.user_id, draft):
        return jsonify({'error': 'No project draft found', 'error_code': 'draft_not_found'}), 404
    # A section-scoped request gates on that section's own approval instead of
    # the whole file — the all-sections requirement stays with the full run.
    section_key = str(data.get('sectionKey') or '').strip() or None
    if section_key and section_key not in PROJECT_SECTION_PRESENTATION_TARGETS:
        return jsonify({'error': 'قسم المشروع غير صالح', 'error_code': 'invalid_section'}), 400
    estimate = db.estimate_generation_cost(
        g.tenant_id, draft_id=draft_id,
        slides_count=int(data.get('slidesCount') or draft.get('slide_count') or 0),
    )
    # t14-04: freeze the priced inputs — the decision later verifies the draft
    # still matches this snapshot, and the job record carries it.
    overview = db.section_versions_overview(g.tenant_id, draft_id)
    input_snapshot = {
        'section_hashes': {key: meta.get('snapshot_hash') for key, meta in overview.items()},
        'captured_at': db._utcnow().isoformat(),
        'slides_count': estimate['slides_count'],
        'units': estimate['units'],
        'unit_prices': estimate['unit_prices'],
        'estimated_cost_usd': estimate['estimated_cost_usd'],
        'estimated_points': estimate['estimated_points'],
    }
    if section_key:
        # The drift check for a section run watches only that section's
        # inputs — an edit anywhere else must not void its approval.
        input_snapshot['section_key'] = section_key
        input_snapshot['section_hash'] = db.section_snapshot_hash(
            _section_snapshot_slice(draft.get('draft_data') or {}, section_key,
                                    _draft_field_section_map(g.tenant_id)))
    else:
        input_snapshot['draft_hash'] = db.draft_generation_input_hash(draft.get('draft_data') or {})
    approval = db.create_generation_approval(
        g.tenant_id, draft_id, estimate, _landloom_actor_id(), _landloom_actor_name(),
        presentation_id=data.get('presentationId'), input_snapshot=input_snapshot,
        section_key=section_key,
    )
    failure = _landloom_error(approval)
    if failure:
        return failure
    try:
        # The request opens an approver task and pings the approvers so the
        # gate does not wait on somebody noticing. An assigned approver for
        # this draft owns the request alone; without one, every generation-
        # permission holder hears it as before.
        assigned = db.assigned_approver(g.tenant_id, draft_id)
        db.create_approval_task(
            g.tenant_id, 'generation_approval',
            f'اعتماد توليد «{draft.get("title") or "مشروع"}»',
            entity_type='generation_approval', entity_id=approval['id'],
            assignee_id=(assigned or {}).get('user_id'),
            assignee_name=(assigned or {}).get('user_name'),
            payload={'draft_id': draft_id,
                     'estimated_points': approval.get('estimated_points')},
            due_hours=48, draft_id=draft_id)
        recipients = ([{'id': assigned['user_id']}] if assigned
                      else db.get_users_with_permission(g.tenant_id, 'approve_generation'))
        for approver in recipients:
            db.create_notification(
                g.tenant_id, 'طلب اعتماد توليد جديد',
                f'«{draft.get("title") or "مشروع"}» بانتظار قرار اعتماد التوليد',
                category='generation_approval', user_id=approver['id'],
                entity_type='generation_approval', entity_id=approval['id'],
                mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_audit_event('generation_approval.requested', 'generation_approval', approval['id'],
                        entity_name=draft.get('title'),
                        new_value=approval['status'],
                        metadata={'estimated_points': approval.get('estimated_points'),
                                  'estimated_cost_usd': approval.get('estimated_cost_usd')})
    can_self_decide = _landloom_actor_is_admin() \
        or db.get_tenant_policy(g.tenant_id, 'generation_self_approval', 'block') == 'allow'
    return jsonify({'success': True, 'approval': approval, 'estimate': estimate,
                    'can_self_decide': can_self_decide})


@app.route('/api/generation-approvals', methods=['GET'])
@require_auth
def api_list_generation_approvals():
    approvals = db.list_generation_approvals(g.tenant_id, status=request.args.get('status'))
    return jsonify({'success': True, 'approvals': approvals})


@app.route('/api/generation-approvals/<approval_id>', methods=['GET'])
@require_auth
def api_get_generation_approval(approval_id):
    approval = db.get_generation_approval(g.tenant_id, approval_id)
    if not approval:
        return jsonify({'error': 'الاعتماد غير موجود', 'error_code': 'approval_not_found'}), 404
    return jsonify({'success': True, 'approval': approval})


@app.route('/api/generation-approvals/<approval_id>/decision', methods=['POST'])
@require_auth
def api_decide_generation_approval(approval_id):
    """Approve, reject or cancel. Approval reserves the points atomically.

    Decide acts need the dedicated approve_generation permission; cancelling a
    pending request stays with its requester. Self-decisions are refused unless
    the actor is a company-level administrator (d02) — or the tenant's
    generation_self_approval policy is 'allow', which lets a requester pass
    their own gate.
    """
    data = request.json or {}
    decision = data.get('decision')
    approval_row = db.get_generation_approval(g.tenant_id, approval_id)
    self_decision = bool(approval_row) \
        and str(approval_row.get('requested_by') or '') == str(_landloom_actor_id())
    policy_self_ok = db.get_tenant_policy(g.tenant_id, 'generation_self_approval', 'block') == 'allow'
    if decision in {'approved', 'rejected'} \
            and not _landloom_can_decide('approve_generation', (approval_row or {}).get('draft_id')) \
            and not (self_decision and policy_self_ok):
        return _landloom_forbidden('اعتماد أو رفض طلب التوليد يتطلب صلاحية معتمد التوليد')
    # A section-scoped request is drift-checked against its own section's live
    # inputs — the whole-draft hash is meaningless for it.
    current_section_hash = None
    approval_section = str((approval_row or {}).get('section_key') or '').strip()
    if approval_section and (approval_row or {}).get('draft_id'):
        scoped_draft = db.get_project_draft_by_id(g.tenant_id, approval_row['draft_id'])
        current_section_hash = db.section_snapshot_hash(_section_snapshot_slice(
            (scoped_draft or {}).get('draft_data') or {}, approval_section,
            _draft_field_section_map(g.tenant_id)))
    result = db.decide_generation_approval(
        g.tenant_id, approval_id, decision, _landloom_actor_id(), _landloom_actor_name(),
        note=data.get('note'),
        allow_self=_landloom_actor_is_admin() or (self_decision and policy_self_ok),
        current_section_hash=current_section_hash,
    )
    failure = _landloom_error(result)
    if failure:
        return failure
    try:
        # The decision closes the approver task and tells the requester.
        db.close_approval_tasks_for_entity(
            g.tenant_id, 'generation_approval', approval_id,
            closed_by_name=_landloom_actor_name())
        requester = str(result.get('requested_by') or '')
        if not _recipient_is_actor(g.tenant_id, requester, _landloom_actor_id(),
                                   _landloom_actor_is_admin()):
            message = {'approved': 'اعتُمد طلب التوليد',
                       'rejected': 'رُفض طلب التوليد',
                       'cancelled': 'أُلغي طلب التوليد'}.get(decision)
            if message:
                db.create_notification(
                    g.tenant_id, message, str(data.get('note') or '').strip() or None,
                    category='generation_approval',
                    user_id=requester,
                    entity_type='generation_approval', entity_id=approval_id,
                    mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_audit_event(f'generation_approval.{decision}', 'generation_approval', approval_id,
                        old_value='pending', new_value=decision,
                        metadata={'note': data.get('note'), 'reservation_id': result.get('reservation_id')})
    return jsonify({'success': True, 'approval': result})


@app.route('/api/generation-approvals/<approval_id>/settle', methods=['POST'])
@require_auth
def api_settle_generation_approval(approval_id):
    """After the generation job finishes: consume the reservation once, or release it.

    Settlement is bookkeeping for a real run, so only the requester, a
    generation approver, or an administrator may settle it — a random tenant
    user cannot release somebody else's reservation.
    """
    approval = db.get_generation_approval(g.tenant_id, approval_id)
    if not approval:
        return jsonify({'error': 'الاعتماد غير موجود', 'error_code': 'approval_not_found'}), 404
    if str(approval.get('requested_by')) != str(_landloom_actor_id()) \
            and not _landloom_can_decide('approve_generation', approval.get('draft_id')):
        return _landloom_forbidden('تسوية الحجز تخص مقدم الطلب أو معتمد التوليد')
    data = request.json or {}
    job_id = str(data.get('jobId') or '').strip()
    consumed = bool(data.get('consumed', True))
    # The caller's claim about the run is checked against server state: a
    # named job must belong to this approval and agree with the outcome, and
    # a live run can never have its escrow released under it.
    jobs = _approval_generation_jobs(g.tenant_id, approval_id)
    job = None
    if job_id:
        job = next((j for j in jobs if str(j.get('id')) == job_id), None)
        if job is None:
            return jsonify({'error': 'مهمة التوليد لا تتبع هذا الاعتماد',
                            'error_code': 'job_mismatch'}), 409
        if consumed and job.get('status') != 'completed':
            return jsonify({'error': 'لا يمكن استهلاك الحجز قبل اكتمال مهمة التوليد',
                            'error_code': 'job_not_completed'}), 409
        if not consumed and job.get('status') in ('queued', 'running'):
            return jsonify({'error': 'لا يمكن تحرير الحجز ومهمة التوليد ما زالت تعمل',
                            'error_code': 'job_still_running'}), 409
    elif jobs:
        # A registered run exists for this approval — settling under a bare
        # 'unknown-job' label would orphan its bookkeeping.
        return jsonify({'error': 'تسوية هذا الاعتماد تتطلب معرف مهمة التوليد',
                        'error_code': 'job_required'}), 409
    result = db.settle_generation_approval(
        g.tenant_id, approval_id, job_id or 'unknown-job',
        consumed=consumed, settled_by=_landloom_actor_id(),
        note=data.get('note'),
    )
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('generation_approval.settled', 'generation_approval', approval_id,
                        new_value=result.get('status'), metadata={'job_id': data.get('jobId')})
    _bill_tenant_unbilled_usage_async(g.tenant_id)
    return jsonify({'success': True, 'result': result})


# ── t14-05: background generation jobs — the run is a record, not a request ──

@app.route('/api/generation-approvals/<approval_id>/jobs', methods=['POST'])
@require_auth
def api_create_generation_job(approval_id):
    """Register the generation run for an approved gate decision.

    Only the requester or a generation approver may start the job, and the
    approval must already be approved. The job carries the input snapshot the
    approver priced, so the run is always attributable to what was decided.
    """
    approval = db.get_generation_approval(g.tenant_id, approval_id)
    if not approval:
        return jsonify({'error': 'الاعتماد غير موجود', 'error_code': 'approval_not_found'}), 404
    if approval.get('status') != 'approved':
        return jsonify({'error': 'مهمة التوليد تتطلب اعتمادًا ساريًا',
                        'error_code': 'job_not_approved'}), 409
    if str(approval.get('requested_by')) != str(_landloom_actor_id()) \
            and not _landloom_can_decide('approve_generation', approval.get('draft_id')):
        return _landloom_forbidden('مهمة التوليد تخص مقدم الطلب أو معتمد التوليد')
    data = request.json or {}
    snapshot = db._json_object(approval.get('input_snapshot'))
    job = db.create_generation_job(
        g.tenant_id, approval_id=approval_id, draft_id=approval.get('draft_id'),
        presentation_id=approval.get('presentation_id'),
        model=data.get('model'), input_snapshot=snapshot or None,
        estimated_cost_usd=approval.get('estimated_cost_usd'),
        slides_total=int(data.get('slidesTotal') or approval.get('slides_count') or 0),
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
        idempotency_key=data.get('idempotencyKey') or request.headers.get('X-Idempotency-Key'),
        correlation_id=data.get('correlationId'),
    )
    try:
        # The link is only written when the returned job is this approval's own
        # run — a replayed key can never point this approval at a foreign job.
        if str(job.get('approval_id') or '') == str(approval_id):
            conn = db.get_db()
            conn.execute('UPDATE generation_approvals SET job_id = ? WHERE id = ? AND tenant_id = ?',
                         (job['id'], approval_id, g.tenant_id))
            conn.commit()
    except Exception:
        pass
    return jsonify({'success': True, 'job': job})


@app.route('/api/generation-jobs', methods=['GET'])
@require_auth
def api_list_generation_jobs():
    jobs = db.list_generation_jobs(
        g.tenant_id, status=request.args.get('status'),
        limit=request.args.get('limit') or 50,
        accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))
    draft_id = request.args.get('draftId')
    if draft_id:
        jobs = [job for job in jobs if job.get('draft_id') == draft_id]
    return jsonify({'success': True, 'jobs': jobs})


def _approval_generation_jobs(tenant_id, approval_id):
    """Registered runs of one approval — what settle/finish claims are checked
    against instead of trusting the client's job label."""
    try:
        rows = db.get_db().execute(
            'SELECT * FROM generation_jobs WHERE tenant_id = ? AND approval_id = ? '
            'ORDER BY created_at ASC, rowid ASC',
            (str(tenant_id), str(approval_id))).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _generation_job_in_scope(job):
    """ISS-014: a job stays inside the caller's project scope — its own draft
    link, or the draft its presentation carries."""
    if not job:
        return False
    accessible = db.user_accessible_draft_ids(g.user_id, g.tenant_id)
    if accessible is None:
        return True
    draft_id = job.get('draft_id')
    if not draft_id and job.get('presentation_id'):
        pres = db.get_presentation(job['presentation_id'], tenant_id=g.tenant_id)
        draft_id = (pres or {}).get('draft_id')
    return not draft_id or str(draft_id) in accessible


@app.route('/api/generation-jobs/<job_id>', methods=['GET'])
@require_auth
def api_get_generation_job(job_id):
    job = db.get_generation_job(job_id, tenant_id=g.tenant_id)
    if not job or not _generation_job_in_scope(job):
        return jsonify({'error': 'مهمة التوليد غير موجودة', 'error_code': 'job_not_found'}), 404
    return jsonify({'success': True, 'job': job})


def _generation_job_actor_allowed(job):
    """The run belongs to its creator, a generation approver, or an admin."""
    if not _generation_job_in_scope(job):
        return False
    if str(job.get('created_by')) == str(_landloom_actor_id()):
        return True
    return _landloom_can('approve_generation')


@app.route('/api/generation-jobs/<job_id>/heartbeat', methods=['POST'])
@require_auth
def api_generation_job_heartbeat(job_id):
    """Progress ping from the running job — also the stale-sweep's clock."""
    job = db.get_generation_job(job_id, tenant_id=g.tenant_id)
    if not job:
        return jsonify({'error': 'مهمة التوليد غير موجودة', 'error_code': 'job_not_found'}), 404
    if not _generation_job_actor_allowed(job):
        return _landloom_forbidden('هذه المهمة تخص مشغّلها أو معتمد التوليد')
    if job.get('status') not in ('queued', 'running'):
        return jsonify({'error': 'المهمة ليست قيد التنفيذ', 'error_code': 'job_not_active'}), 409
    data = request.json or {}
    updated = db.update_generation_job(
        job_id, status='running' if job.get('status') == 'queued' else None,
        progress=data.get('progress'), slides_done=data.get('slidesDone'),
        slides_total=data.get('slidesTotal'))
    return jsonify({'success': True, 'job': updated})


@app.route('/api/generation-jobs/<job_id>/finish', methods=['POST'])
@require_auth
def api_finish_generation_job(job_id):
    """Close the run and settle its reservation server-side (t14-06).

    'completed' consumes the hold; 'failed'/'cancelled' release it — so a
    finished job can never strand the escrow even when the client dies.
    """
    job = db.get_generation_job(job_id, tenant_id=g.tenant_id)
    if not job:
        return jsonify({'error': 'مهمة التوليد غير موجودة', 'error_code': 'job_not_found'}), 404
    if not _generation_job_actor_allowed(job):
        return _landloom_forbidden('هذه المهمة تخص مشغّلها أو معتمد التوليد')
    data = request.json or {}
    status = data.get('status')
    if status not in ('completed', 'failed', 'cancelled'):
        return jsonify({'error': 'حالة المهمة غير معروفة', 'error_code': 'invalid_job_status'}), 400
    if job.get('status') not in ('queued', 'running'):
        return jsonify({'error': 'المهمة ليست قيد التنفيذ', 'error_code': 'job_not_active'}), 409
    updated = db.update_generation_job(
        job_id, status=status, progress=data.get('progress'),
        slides_done=data.get('slidesDone'), actual_cost_usd=data.get('actualCostUsd'),
        error=data.get('error'))
    settlement_error = None
    if job.get('approval_id'):
        try:
            settlement = db.settle_generation_approval(
                g.tenant_id, job['approval_id'], job_id,
                consumed=(status == 'completed'), settled_by=_landloom_actor_id(),
                note=str(data.get('note') or data.get('error') or '').strip() or None)
            if isinstance(settlement, dict) and settlement.get('error'):
                settlement_error = settlement.get('error')
        except Exception as exc:
            settlement_error = str(exc) or 'settlement_failed'
    if settlement_error:
        # The job is closed but its escrow is still live — reporting the
        # failure lets the caller retry settle instead of believing the run
        # was paid for (or refunded) when it was not. 503, not 502: the edge
        # fabricates 502s of its own for large bodies, so an app-emitted one
        # would be indistinguishable from a proxy failure.
        return jsonify({
            'success': False,
            'error': 'تعذر تسوية حجز التوليد بعد إنهاء المهمة',
            'error_code': 'settlement_failed',
            'detail': str(settlement_error)[:300],
            'job': updated,
        }), 503
    try:
        titles = {'completed': 'اكتمل توليد العرض', 'failed': 'فشل توليد العرض',
                  'cancelled': 'أُلغيت مهمة التوليد'}
        draft = db.get_project_draft_by_id(
            g.tenant_id, job['draft_id']) if job.get('draft_id') else None
        db.create_notification(
            g.tenant_id, titles.get(status, 'تحديث مهمة التوليد'),
            body=(draft or {}).get('title') or data.get('error'),
            category='job', user_id=job.get('created_by') or None,
            entity_type='generation_job', entity_id=job_id)
    except Exception:
        pass
    _bill_tenant_unbilled_usage_async(g.tenant_id)
    return jsonify({'success': True, 'job': updated})


@app.route('/api/points/reservations', methods=['GET'])
@require_auth
def api_list_point_reservations():
    """Active wallet holds — the same company-admin-only wallet surface."""
    if not _landloom_can('billing'):
        return _landloom_forbidden('عرض حجوزات المحفظة يتطلب صلاحية الفوترة')
    reservations = db.list_point_reservations(g.tenant_id, status=request.args.get('status'))
    return jsonify({'success': True, 'reservations': reservations})
