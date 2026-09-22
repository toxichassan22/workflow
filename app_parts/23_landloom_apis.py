

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Landloom platform APIs (t14-t63): generation and final-file approvals with
# points reservation, downloads ledger, proposal copies, archive/restore,
# notifications, approval tasks, event tasks, role templates, users report,
# separation-of-duties matrix, recharge requests, support tickets
# and the file-type registry. Money stays in tenant_ledger; these endpoints
# track workflow state only.
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
        # The request opens an approver task and pings every generation
        # approver so the gate does not wait on somebody noticing.
        db.create_approval_task(
            g.tenant_id, 'generation_approval',
            f'اعتماد توليد «{draft.get("title") or "مشروع"}»',
            entity_type='generation_approval', entity_id=approval['id'],
            payload={'draft_id': draft_id,
                     'estimated_points': approval.get('estimated_points')},
            due_hours=48, draft_id=draft_id)
        for approver in db.get_users_with_permission(g.tenant_id, 'approve_generation'):
            db.create_notification(
                g.tenant_id, 'طلب اعتماد توليد جديد',
                f'«{draft.get("title") or "مشروع"}» بانتظار قرار اعتماد التوليد',
                category='generation_approval', user_id=approver['id'],
                entity_type='generation_approval', entity_id=approval['id'])
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
    if decision in {'approved', 'rejected'} and not _landloom_can('approve_generation') \
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
        if requester and requester != str(_landloom_actor_id()):
            message = {'approved': 'اعتُمد طلب التوليد',
                       'rejected': 'رُفض طلب التوليد',
                       'cancelled': 'أُلغي طلب التوليد'}.get(decision)
            if message:
                db.create_notification(
                    g.tenant_id, message, str(data.get('note') or '').strip() or None,
                    category='generation_approval',
                    user_id=None if requester.startswith('tenant-admin:') else requester,
                    entity_type='generation_approval', entity_id=approval_id)
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
            and not _landloom_can('approve_generation'):
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
            and not _landloom_can('approve_generation'):
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
    reservations = db.list_point_reservations(g.tenant_id, status=request.args.get('status'))
    return jsonify({'success': True, 'reservations': reservations})


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
        db.create_approval_task(
            g.tenant_id, 'final_approval', f'اعتماد الملف النهائي «{title}»',
            entity_type='final_file_approval', entity_id=approval['id'],
            payload={'presentation_id': presentation_id}, due_hours=48,
            draft_id=(presentation or {}).get('draft_id'))
        for approver in db.get_users_with_permission(g.tenant_id, 'approve_final_file'):
            db.create_notification(
                g.tenant_id, 'طلب اعتماد ملف نهائي',
                f'«{title}» بانتظار قرار اعتماد الملف النهائي',
                category='final_approval', user_id=approver['id'],
                entity_type='final_file_approval', entity_id=approval['id'])
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
    if data.get('decision') in {'approved', 'rejected'} and not _landloom_can('approve_final_file'):
        return _landloom_forbidden('اعتماد أو رفض الملف النهائي يتطلب صلاحية معتمد الملف')
    # ISS-014: the decision must stay inside the caller's project scope too.
    existing = db.get_final_file_approval(g.tenant_id, approval_id)
    if not existing:
        return jsonify({'error': 'الاعتماد غير موجود', 'error_code': 'approval_not_found'}), 404
    pres = db.get_presentation(existing['presentation_id'], tenant_id=g.tenant_id) \
        if existing.get('presentation_id') else None
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
        if requester and requester != str(_landloom_actor_id()):
            message = 'اعتُمد الملف النهائي' if data.get('decision') == 'approved' \
                else 'أُعيد الملف النهائي للتعديل'
            db.create_notification(
                g.tenant_id, message, str(data.get('note') or '').strip() or None,
                category='final_approval',
                user_id=None if requester.startswith('tenant-admin:') else requester,
                entity_type='final_file_approval', entity_id=approval_id)
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


# ── t40: notifications ───────────────────────────────────────────────────────

@app.route('/api/notifications', methods=['GET'])
@require_auth
def api_list_notifications():
    recipient = _notification_recipient_key()
    muted = _notification_muted_categories()
    category = request.args.get('category')
    if category not in db.NOTIFICATION_CATEGORIES:
        category = None
    read_state = (request.args.get('status') or '').strip()
    if read_state not in ('unread', 'read'):
        read_state = None
    unread_only = read_state == 'unread' or request.args.get('unreadOnly') == '1'
    try:
        limit = max(1, min(int(request.args.get('limit') or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = max(0, int(request.args.get('offset') or 0))
    except (TypeError, ValueError):
        offset = 0
    items = db.list_notifications(
        g.tenant_id, user_id=recipient, unread_only=unread_only, limit=limit,
        offset=offset, category=category, muted_categories=muted,
        read_state=read_state)
    total = db.count_notifications(
        g.tenant_id, user_id=recipient, category=category,
        muted_categories=muted, read_state=read_state)
    unread = db.count_notifications(
        g.tenant_id, user_id=recipient, unread_only=True, muted_categories=muted)
    return jsonify({'success': True, 'notifications': items, 'total': total,
                    'unreadCount': unread, 'categories': list(db.NOTIFICATION_CATEGORIES)})


@app.route('/api/notifications/unread-count', methods=['GET'])
@require_auth
def api_notifications_unread_count():
    """The topbar badge polls this — a COUNT, not the feed."""
    count = db.count_notifications(
        g.tenant_id, user_id=_notification_recipient_key(), unread_only=True,
        muted_categories=_notification_muted_categories())
    return jsonify({'success': True, 'unread': count})


@app.route('/api/notifications/preferences', methods=['GET'])
@require_auth
def api_get_notification_preferences():
    prefs = db.get_notification_preferences(g.tenant_id, _notification_recipient_key())
    return jsonify({'success': True, 'preferences': prefs,
                    'categories': list(db.NOTIFICATION_CATEGORIES)})


@app.route('/api/notifications/preferences', methods=['PUT'])
@require_auth
def api_set_notification_preferences():
    data = request.json or {}
    updates = dict(data.get('categories') or {})
    if data.get('category'):
        updates[data['category']] = data.get('enabled')
    recipient = _notification_recipient_key()
    for category, enabled in updates.items():
        if category in db.NOTIFICATION_CATEGORIES:
            db.set_notification_preference(g.tenant_id, recipient, category, bool(enabled))
    prefs = db.get_notification_preferences(g.tenant_id, recipient)
    return jsonify({'success': True, 'preferences': prefs,
                    'categories': list(db.NOTIFICATION_CATEGORIES)})


@app.route('/api/notifications', methods=['POST'])
@require_auth
def api_create_notification():
    """Create an in-app notification (t41).

    A notification aimed at someone else — or broadcast to the whole company
    (no ``userId``) — is an administrative act and needs ``manage_users``;
    workflows notify through ``db.create_notification`` directly, not here.
    """
    data = request.json or {}
    if not str(data.get('title') or '').strip():
        return jsonify({'error': 'A title is required', 'error_code': 'title_required'}), 400
    target_user = data.get('userId')
    if (not target_user or str(target_user) != str(g.user_id)) \
            and not _landloom_can('manage_users'):
        return _landloom_forbidden('إشعار مستخدم آخر أو إشعار عام يتطلب صلاحية إدارة المستخدمين')
    row = db.create_notification(
        g.tenant_id, data.get('title'), body=data.get('body'), category=data.get('category') or 'general',
        user_id=target_user,
        entity_type=data.get('entityType'), entity_id=data.get('entityId'),
        email_to=data.get('emailTo'),
    )
    return jsonify({'success': True, 'notification': row})


@app.route('/api/notifications/read', methods=['POST'])
@require_auth
def api_mark_notifications_read():
    data = request.json or {}
    result = db.mark_notifications_read(
        g.tenant_id, _notification_recipient_key(), notification_ids=data.get('ids'))
    return jsonify({'success': True, 'updated': result})


@app.route('/api/notifications/delete', methods=['POST'])
@require_auth
def api_delete_notifications():
    data = request.json or {}
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({'error': 'Notification ids are required',
                        'error_code': 'ids_required'}), 400
    result = db.delete_notifications(
        g.tenant_id, _notification_recipient_key(), ids[:200])
    return jsonify({'success': True, 'deleted': result})


# ── t41: approval tasks feed ─────────────────────────────────────────────────

_APPROVAL_TASK_KIND_PERMISSION = {
    'section_approval': 'approvals',
    'generation_approval': 'approve_generation',
    'final_approval': 'approve_final_file',
    'support': 'support_tickets',
    'recharge': 'company_settings',
}


def _landloom_is_approver():
    """Any gate-keeping permission makes the actor part of the approver pool."""
    return _landloom_can('approvals') or _landloom_can('approve_generation') \
        or _landloom_can('approve_final_file')


def _landloom_task_actor_allowed(task):
    """Close/remind belong to the assigned approver or a holder of the task
    kind's decision permission; administrators pass through _landloom_can."""
    if not task:
        return False
    if task.get('assignee_id') and str(task['assignee_id']) == str(g.user_id):
        return True
    return _landloom_can(_APPROVAL_TASK_KIND_PERMISSION.get(task.get('kind'), 'approvals'))


@app.route('/api/approval-tasks', methods=['GET'])
@require_auth
def api_list_approval_tasks():
    tasks = db.list_approval_tasks(
        g.tenant_id, status=request.args.get('status') or 'open', kind=request.args.get('kind'),
        assignee_id=None if _landloom_is_approver() else g.user_id,
        draft_id=request.args.get('draftId') or None,
        section_key=request.args.get('sectionKey') or None,
    )
    return jsonify({'success': True, 'tasks': tasks})


@app.route('/api/approval-tasks/<task_id>/close', methods=['POST'])
@require_auth
def api_close_approval_task(task_id):
    conn = db.get_db()
    task_row = conn.execute(
        'SELECT * FROM approval_tasks WHERE id = ? AND tenant_id = ?', (task_id, g.tenant_id)
    ).fetchone()
    if not task_row:
        return jsonify({'error': 'العنصر غير موجود', 'error_code': 'task_not_found'}), 404
    if not _landloom_task_actor_allowed(dict(task_row)):
        return _landloom_forbidden('إغلاق المهمة يخص المعتمد المكلف بها')
    data = request.json or {}
    result = db.close_approval_task(g.tenant_id, task_id, closed_by_name=_landloom_actor_name(),
                                    cancel_reason=data.get('cancelReason'))
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('approval_task.closed', 'approval_task', task_id,
                        old_value='open', new_value='closed',
                        metadata={'cancel_reason': data.get('cancelReason')})
    return jsonify({'success': True, 'task': result})


@app.route('/api/approval-tasks/<task_id>/remind', methods=['POST'])
@require_auth
def api_remind_approval_task(task_id):
    conn = db.get_db()
    task_row = conn.execute(
        'SELECT * FROM approval_tasks WHERE id = ? AND tenant_id = ?', (task_id, g.tenant_id)
    ).fetchone()
    if not task_row:
        return jsonify({'error': 'العنصر غير موجود', 'error_code': 'task_not_found'}), 404
    if not _landloom_task_actor_allowed(dict(task_row)) and not _landloom_is_approver():
        return _landloom_forbidden('التذكير بالمهمة يخص المعتمدين')
    result = db.remind_approval_task(g.tenant_id, task_id)
    failure = _landloom_error(result)
    if failure:
        return failure
    return jsonify({'success': True, 'task': result})


# ── t42: event tasks ─────────────────────────────────────────────────────────

@app.route('/api/event-tasks', methods=['GET'])
@require_auth
def api_list_event_tasks():
    # Staff see their own tasks (assigned to or created by them); managers and
    # administrators keep the company-wide board.
    own_only = None if _landloom_can('manage_users') else _landloom_actor_id()
    tasks = db.list_event_tasks(
        g.tenant_id, status=request.args.get('status'),
        assignee_user_id=request.args.get('assigneeId'), own_actor_id=own_only,
    )
    return jsonify({'success': True, 'tasks': tasks})


@app.route('/api/event-tasks', methods=['POST'])
@require_auth
def api_create_event_task():
    data = request.json or {}
    assignee_id = data.get('assigneeId')
    if assignee_id:
        assignee = db.get_user_by_id(assignee_id)
        if not assignee or str(assignee.get('tenant_id')) != str(g.tenant_id):
            return jsonify({'error': 'المكلف بالمهمة غير موجود في هذه الشركة',
                            'error_code': 'assignee_not_found'}), 404
    row = db.create_event_task(
        g.tenant_id, data.get('title'), description=data.get('description'),
        event_date=data.get('eventDate'), due_at=data.get('dueAt'),
        assignee_user_id=assignee_id, recurrence=data.get('recurrence') or 'none',
        entity_type=data.get('entityType'), entity_id=data.get('entityId'),
        priority=data.get('priority') or 'normal',
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('event_task.created', 'event_task', row['id'], entity_name=row['title'],
                        metadata={'recurrence': row.get('recurrence'), 'due_at': row.get('due_at')})
    if row.get('assignee_user_id'):
        try:
            db.create_notification(
                g.tenant_id, 'أُسندت إليك مهمة جديدة', body=row.get('title'),
                category='task', user_id=row['assignee_user_id'],
                entity_type='event_task', entity_id=row['id'])
        except Exception:
            pass
    return jsonify({'success': True, 'task': row})


@app.route('/api/event-tasks/<task_id>/status', methods=['POST'])
@require_auth
def api_update_event_task_status(task_id):
    task = db.get_event_task(g.tenant_id, task_id)
    if not task:
        return jsonify({'error': 'Task not found', 'error_code': 'task_not_found'}), 404
    actor_id = _landloom_actor_id()
    if str(task.get('assignee_user_id') or '') != str(g.user_id or '') \
            and str(task.get('created_by') or '') != actor_id \
            and not _landloom_can('manage_users'):
        return _landloom_forbidden('تحديث المهمة يخص المكلف بها أو منشئها')
    result = db.update_event_task_status(g.tenant_id, task_id, (request.json or {}).get('status'),
                                         actor_name=_landloom_actor_name())
    if result is None:
        return jsonify({'error': 'Task not found', 'error_code': 'task_not_found'}), 404
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('event_task.status', 'event_task', task_id,
                        new_value=result.get('status'))
    return jsonify({'success': True, 'task': result})


# ── t20: role templates cloned onto users; built-ins stay code-defined ───────

@app.route('/api/roles/template', methods=['GET'])
@require_permission('manage_users')
def api_role_template():
    return jsonify({'success': True, **db.list_tenant_role_templates(g.tenant_id)})


@app.route('/api/roles', methods=['POST'])
@require_permission('manage_users')
def api_create_tenant_role():
    data = request.json or {}
    row = db.create_tenant_role(g.tenant_id, data.get('name'), data.get('baseRole') or 'employee',
                                data.get('permissions'))
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('role.created', 'tenant_role', row['id'], entity_name=row['name'],
                        new_value=json.dumps(row.get('permissions') or {}, ensure_ascii=False))
    return jsonify({'success': True, 'role': row})


@app.route('/api/roles/<role_id>/update', methods=['POST'])
@require_permission('manage_users')
def api_update_tenant_role(role_id):
    data = request.json or {}
    row = db.update_tenant_role(g.tenant_id, role_id, name=data.get('name'),
                                permissions=data.get('permissions'))
    if not row:
        return jsonify({'error': 'Role not found', 'error_code': 'task_not_found'}), 404
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('role.updated', 'tenant_role', role_id, entity_name=row.get('name'),
                        new_value=json.dumps(row.get('permissions') or {}, ensure_ascii=False))
    return jsonify({'success': True, 'role': row})


@app.route('/api/roles/<role_id>/delete', methods=['POST'])
@require_permission('manage_users')
def api_delete_tenant_role(role_id):
    if not db.delete_tenant_role(g.tenant_id, role_id):
        return jsonify({'error': 'Role not found', 'error_code': 'task_not_found'}), 404
    _record_audit_event('role.deleted', 'tenant_role', role_id)
    return jsonify({'success': True})


@app.route('/api/roles/<role_id>/assign', methods=['POST'])
@require_permission('manage_users')
def api_assign_tenant_role(role_id):
    data = request.json or {}
    user_id = data.get('userId')
    user = db.get_user_by_id(user_id) if user_id else None
    if not user or user.get('tenant_id') != g.tenant_id:
        return jsonify({'error': 'User not found in this company', 'error_code': 'task_not_found'}), 404
    permissions = db.assign_tenant_role_to_user(g.tenant_id, user_id, role_id)
    if not permissions:
        return jsonify({'error': 'Role not found', 'error_code': 'task_not_found'}), 404
    _record_audit_event('role.assigned', 'user', user_id,
                        metadata={'role_id': role_id, 'role_name': (db.get_tenant_role(g.tenant_id, role_id) or {}).get('name')})
    return jsonify({'success': True, 'permissions': permissions})


# ── t22: users report; t21: separation-of-duties matrix ─────────────────────

@app.route('/api/users/report', methods=['GET'])
@require_permission('manage_users')
def api_tenant_users_report():
    return jsonify({'success': True, 'report': db.tenant_users_report(g.tenant_id)})


@app.route('/api/approvals/sod-matrix', methods=['GET'])
@require_auth
def api_sod_matrix():
    if not (_landloom_can('approvals') or _landloom_can('manage_users')):
        return _landloom_forbidden('عرض مصفوفة فصل المهام يتطلب صلاحية الاعتمادات أو إدارة المستخدمين')
    return jsonify({'success': True, 'matrix': db.separation_of_duties_matrix(g.tenant_id)})


@app.route('/api/policies', methods=['GET'])
@require_auth
def api_get_policies():
    """Tenant policy settings (d01 and siblings); read by approver tooling."""
    if not (_landloom_can('approvals') or _landloom_can('manage_users') or _landloom_can('company_settings')):
        return _landloom_forbidden('عرض سياسات الشركة يتطلب صلاحية مناسبة')
    return jsonify({'success': True, 'policies': db.get_tenant_policies(g.tenant_id)})


@app.route('/api/policies', methods=['PUT'])
@require_permission('company_settings')
def api_update_policies():
    """Update tenant policies; only known keys with allowed values apply."""
    result = db.set_tenant_policies(g.tenant_id, request.json or {})
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('policies.updated', 'tenant', g.tenant_id, new_value=result)
    return jsonify({'success': True, 'policies': result})


# ── t30: package purchase (recharge) requests ────────────────────────────────

@app.route('/api/recharge-requests', methods=['POST'])
@require_auth
def api_create_recharge_request():
    # The platform tenant reviews company top-ups; it must never request one for
    # itself — that would let the super-admin mint wallet credit self-approved.
    if getattr(g, 'is_admin', False):
        return _landloom_forbidden('طلبات الشحن تنشأ من حسابات الشركات فقط')
    if not _landloom_can('billing'):
        return _landloom_forbidden('رفع طلبات الشحن يتطلب صلاحية الفوترة')
    data = request.json or {}
    # The catalog owns the numbers: a purchase request must point at an active
    # billing_packages row — client-supplied names, amounts and prices are
    # never trusted (they only reach the db layer through admin tooling).
    package_id = data.get('packageId') or data.get('package_id')
    if not str(package_id or '').strip():
        return jsonify({'error': 'اختر الباقة المطلوب شراؤها',
                        'error_code': 'package_required'}), 400
    row = db.create_recharge_request(
        g.tenant_id, data.get('packageName'), amount_usd=data.get('amountUsd') or 0,
        price_sar=data.get('priceSar'), transfer_reference=data.get('referenceNumber'),
        package_id=package_id,
        receipt_file_id=data.get('receiptFileId'), requested_by=_landloom_actor_id(),
        requested_by_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('recharge.requested', 'recharge_request', row['id'],
                        entity_name=row.get('package_name'),
                        metadata={'amount_usd': row.get('amount_usd')})
    # t33: the platform desk gets a task and a notification for the 24h review window.
    db.create_approval_task(
        g.tenant_id, 'recharge',
        f'طلب شحن رصيد — {row.get("package_name") or "باقة"}',
        entity_type='recharge_request', entity_id=row['id'],
        payload={'amount_usd': row.get('amount_usd'), 'price_sar': row.get('price_sar')},
        due_hours=24)
    db.create_notification(
        g.tenant_id, 'طلب شحن جديد بانتظار المراجعة',
        body=f'{row.get("package_name") or ""} — {row.get("price_sar") or row.get("amount_usd") or ""}',
        category='recharge', entity_type='recharge_request', entity_id=row['id'])
    _notify_super_admins(
        'طلب شحن جديد',
        f'{(g.tenant or {}).get("company_name") or "شركة"} — {row.get("package_name") or ""}'
        f' — {row.get("price_sar") or row.get("amount_usd") or ""}',
        entity_type='recharge_request', entity_id=row['id'])
    return jsonify({'success': True, 'request': row})


@app.route('/api/recharge-requests', methods=['GET'])
@require_auth
def api_list_recharge_requests():
    rows = db.list_recharge_requests(g.tenant_id, status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/admin/recharge-requests', methods=['GET'])
@require_admin
def api_admin_list_recharge_requests():
    rows = db.list_recharge_requests(status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/billing/packages', methods=['GET'])
@require_auth
def api_billing_packages():
    """t33: the purchase screen lists every active package the super admin
    manages, never hardcoded prices."""
    packages = db.with_sar_fields(db.list_billing_packages(active_only=True))
    return jsonify({'success': True, 'packages': packages, 'taxRate': db.TAX_RATE_SAR})


@app.route('/api/billing/receipts', methods=['GET'])
@require_permission('billing')
def api_billing_receipts():
    """d09: the tenant's issued financial documents for approved top-ups."""
    return jsonify({'success': True, 'receipts': db.list_topup_receipts(g.tenant_id)})


@app.route('/api/billing/receipts/<receipt_id>', methods=['GET'])
@require_permission('billing')
def api_billing_receipt(receipt_id):
    row = db.get_topup_receipt(g.tenant_id, receipt_id)
    if not row:
        return jsonify({'error': 'المستند غير موجود', 'error_code': 'receipt_not_found'}), 404
    return jsonify({'success': True, 'receipt': row})


@app.route('/api/points/overview', methods=['GET'])
@require_auth
def api_points_overview():
    """t30: current, reserved, available and expired balances in one read."""
    return jsonify({'success': True, 'points': db.points_overview(g.tenant_id)})


@app.route('/api/admin/ledger/adjust', methods=['POST'])
@require_admin
def api_admin_ledger_adjust():
    """t32: refund, correction and expiry movements are a super-admin act,
    linked to the original entry they reverse when one is given."""
    data = request.json or {}
    kind = data.get('kind')
    if kind not in db.LEDGER_ADJUSTMENT_KINDS:
        return jsonify({'error': 'نوع الحركة غير معروف', 'error_code': 'invalid_kind'}), 400
    tenant_id = data.get('tenantId')
    if not tenant_id:
        return jsonify({'error': 'الشركة مطلوبة', 'error_code': 'tenant_required'}), 400
    # The desk keys adjustments in riyals; the ledger books them in USD.
    amount_usd = data.get('amountUsd')
    amount_sar = data.get('amountSar', data.get('amount_sar'))
    if amount_sar is not None:
        try:
            fx_rate = float((db.get_fx_rate() or {}).get('rate') or db.FX_DEFAULT_USD_SAR)
            amount_usd = float(amount_sar) / fx_rate
        except (TypeError, ValueError):
            return jsonify({'error': 'مبلغ الحركة غير صالح', 'error_code': 'invalid_amount'}), 400
    result = db.record_ledger_adjustment(
        tenant_id, amount_usd, kind, note=data.get('note'),
        actor=_landloom_actor_id() or 'platform_admin', reversal_of=data.get('reversalOf'),
        idempotency_key=data.get('idempotencyKey'))
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('ledger.adjusted', 'tenant_ledger',
                        (result.get('entry') or {}).get('id') or '', entity_name=kind,
                        metadata={'tenant_id': tenant_id, 'amount_usd': data.get('amountUsd'),
                                  'reversal_of': data.get('reversalOf')})
    return jsonify({'success': True, 'result': result})


@app.route('/api/admin/recharge-requests/<request_id>/decision', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_decide_recharge_request(request_id):
    data = request.json or {}
    decision = data.get('decision')
    row = db.decide_recharge_request(
        None, request_id, decision, _landloom_actor_id(), _landloom_actor_name(),
        note=data.get('note'), reference_number=data.get('transactionReference'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    try:
        approved = row.get('status') == 'approved'
        _notify_tenant_billing(
            row['tenant_id'],
            'اعتُمد طلب الشحن' if approved else 'رُفض طلب الشحن',
            f'{row.get("package_name") or ""} — {row.get("amount_usd") or ""}'
            + (f' — {data.get("note")}' if data.get('note') else ''),
            entity_type='recharge_request', entity_id=row['id'])
    except Exception:
        pass
    return jsonify({'success': True, 'request': row})


# ── t50: support tickets ─────────────────────────────────────────────────────

def _landloom_ticket_actor_is_creator(ticket):
    """The requester keeps view/reply rights on their own ticket even without
    the desk permission — tickets filed before the gate existed, or a grant the
    company admin later revoked. Status moves stay with the platform desk."""
    return str((ticket or {}).get('created_by') or '') == str(_landloom_actor_id())


@app.route('/api/support/tickets', methods=['POST'])
@require_auth
def api_create_support_ticket():
    """Opening a ticket is a support-desk act: the company admin or a user
    granted support_tickets — not every authenticated employee."""
    if not _landloom_can('support_tickets'):
        return _landloom_forbidden('فتح تذاكر الدعم يتطلب صلاحية تذاكر الدعم')
    data = request.json or {}
    row = db.create_support_ticket(
        g.tenant_id, data.get('subject'), category=data.get('category') or 'general',
        priority=data.get('priority') or 'normal', body=data.get('body'),
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
        draft_id=data.get('draftId'), project_id=data.get('projectId'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    # t40/t42: the support desk sees new tickets as a task plus a notification.
    db.create_approval_task(
        g.tenant_id, 'support',
        f'تذكرة دعم — {row.get("subject")}',
        entity_type='support_ticket', entity_id=row['id'],
        payload={'priority': row.get('priority'), 'category': row.get('category')},
        draft_id=row.get('draft_id'))
    db.create_notification(
        g.tenant_id, 'تذكرة دعم جديدة',
        body=row.get('subject'), category='support',
        entity_type='support_ticket', entity_id=row['id'])
    _notify_super_admins(
        'تذكرة دعم جديدة',
        f'{(g.tenant or {}).get("company_name") or "شركة"} — {row.get("subject") or ""}',
        entity_type='support_ticket', entity_id=row['id'])
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/support/tickets', methods=['GET'])
@require_auth
def api_list_support_tickets():
    """The inbox is the desk surface — permission holders only."""
    if not _landloom_can('support_tickets'):
        return _landloom_forbidden('عرض تذاكر الدعم يتطلب صلاحية تذاكر الدعم')
    rows = db.list_support_tickets(g.tenant_id, status=request.args.get('status'))
    return jsonify({'success': True, 'tickets': rows})


@app.route('/api/support/tickets/<ticket_id>', methods=['GET'])
@require_auth
def api_get_support_ticket(ticket_id):
    row = db.get_support_ticket(g.tenant_id, ticket_id)
    if not row:
        return jsonify({'error': 'Ticket not found', 'error_code': 'ticket_not_found'}), 404
    if not _landloom_can('support_tickets') and not _landloom_ticket_actor_is_creator(row):
        return _landloom_forbidden('عرض التذكرة يتطلب صلاحية تذاكر الدعم')
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/support/tickets/<ticket_id>/messages', methods=['POST'])
@require_auth
def api_add_support_message(ticket_id):
    data = request.json or {}
    if not _landloom_can('support_tickets'):
        ticket = db.get_support_ticket(g.tenant_id, ticket_id)
        if not ticket:
            return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
        if not _landloom_ticket_actor_is_creator(ticket):
            return _landloom_forbidden('الرد على التذكرة يتطلب صلاحية تذاكر الدعم')
    row = db.add_support_message(
        g.tenant_id, ticket_id, data.get('body'), author_id=_landloom_actor_id(),
        author_name=_landloom_actor_name(), author_role='customer',
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    # t40: a customer reply moves the ticket back onto the desk's radar.
    ticket = db.get_support_ticket(g.tenant_id, ticket_id)
    if ticket and ticket.get('status') in ('waiting_customer', 'resolved'):
        db.update_support_ticket_status(g.tenant_id, ticket_id, 'reopened',
                                        actor_name=_landloom_actor_name())
    return jsonify({'success': True, 'message': row})


# ── Super-admin support inbox: tickets of every company land here ────────────

@app.route('/api/admin/support/tickets', methods=['GET'])
@require_permission('sag_admin_panel')
def api_admin_list_support_tickets():
    rows = db.list_all_support_tickets(status=request.args.get('status'))
    return jsonify({'success': True, 'tickets': rows})


@app.route('/api/admin/support/tickets/<ticket_id>', methods=['GET'])
@require_permission('sag_admin_panel')
def api_admin_get_support_ticket(ticket_id):
    row = db.get_support_ticket_admin(ticket_id)
    if not row:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/admin/support/tickets/<ticket_id>/messages', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_add_support_message(ticket_id):
    ticket = db.get_support_ticket_admin(ticket_id)
    if not ticket:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    data = request.json or {}
    row = db.add_support_message(
        ticket['tenant_id'], ticket_id, data.get('body'), author_id=_landloom_actor_id(),
        author_name=_landloom_actor_name(), author_role='support',
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('support_ticket.replied', 'support_ticket', ticket_id)
    # t40: the customer sees the desk's reply; the desk marks first response.
    db.create_notification(
        ticket['tenant_id'], 'رد جديد على تذكرة الدعم',
        body=ticket.get('subject'), category='support',
        user_id=ticket.get('created_by'),
        entity_type='support_ticket', entity_id=ticket_id)
    return jsonify({'success': True, 'message': row})


@app.route('/api/admin/support/tickets/<ticket_id>/status', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_update_support_ticket_status(ticket_id):
    ticket = db.get_support_ticket_admin(ticket_id)
    if not ticket:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    data = request.json or {}
    row = db.update_support_ticket_status(ticket['tenant_id'], ticket_id, data.get('status'),
                                          actor_name=_landloom_actor_name())
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('support_ticket.status', 'support_ticket', ticket_id,
                        new_value=row.get('status'))
    db.create_notification(
        ticket['tenant_id'], 'تحديث حالة التذكرة',
        body=f'{ticket.get("subject") or ""} — {row.get("status")}',
        category='support', user_id=ticket.get('created_by'),
        entity_type='support_ticket', entity_id=ticket_id)
    return jsonify({'success': True, 'ticket': row})


@app.route('/api/admin/support/tickets/<ticket_id>/assign', methods=['POST'])
@require_permission('sag_admin_panel')
def api_admin_assign_support_ticket(ticket_id):
    """t40: route a ticket to a named owner on the desk."""
    ticket = db.get_support_ticket_admin(ticket_id)
    if not ticket:
        return jsonify({'error': 'التذكرة غير موجودة', 'error_code': 'ticket_not_found'}), 404
    data = request.json or {}
    row = db.assign_support_ticket(ticket['tenant_id'], ticket_id, data.get('assigneeId'),
                                   actor_name=_landloom_actor_name())
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('support_ticket.assigned', 'support_ticket', ticket_id,
                        new_value=data.get('assigneeId'))
    return jsonify({'success': True, 'ticket': row})


# ── t51: operational overview; t63: file-type registry ─────────────────────

@app.route('/api/admin/operational-overview', methods=['GET'])
@require_admin
def api_operational_overview():
    return jsonify({'success': True, 'overview': db.operational_overview(
        months=request.args.get('months'),
        from_month=request.args.get('from'),
        to_month=request.args.get('to'))})


@app.route('/api/file-types', methods=['GET'])
@require_auth
def api_list_file_types():
    return jsonify({'success': True, 'fileTypes': db.get_file_type_registry()})


@app.route('/api/file-types/<key>', methods=['POST'])
@require_admin
def api_upsert_file_type(key):
    data = request.json or {}
    row = db.upsert_file_type(key, data.get('labelAr'), kind=data.get('kind') or 'document',
                              max_size_mb=data.get('maxSizeMb') or 25,
                              allowed_extensions=data.get('allowedExtensions'))
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('file_type.updated', 'file_type_registry', key, entity_name=row.get('label_ar'))
    return jsonify({'success': True, 'fileType': row})


# ── Mission 5: company file, slug, activation, subscriptions ────────────────

_COMPANY_PROFILE_KEY_MAP = {
    'legalName': 'legal_name', 'commercialName': 'commercial_name',
    'taxNumber': 'tax_number', 'crNumber': 'cr_number', 'country': 'country',
    'region': 'region', 'address': 'address', 'contactTitle': 'contact_title',
}


@app.route('/api/admin/tenants/<tenant_id>/slug', methods=['PUT'])
@require_admin
def api_admin_set_tenant_slug(tenant_id):
    """t51: set the company's URL slug; locked once the company is active."""
    tenant, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    data = request.json or {}
    allow_locked = bool(data.get('allowAfterActivation'))
    result = db.set_tenant_slug(
        tenant_id, data.get('slug'), actor_id=_landloom_actor_id(),
        actor_name=_landloom_actor_name(), allow_after_activation=allow_locked,
    )
    if result.get('error') == 'slug_locked':
        return jsonify({'error': 'slug_locked',
                        'message': 'الشركة نشطة — تغيير الرابط يتطلب تأكيدًا'}), 409
    if result.get('error') in ('invalid', 'reserved', 'taken'):
        return jsonify({'error': result['error']}), 409 if result['error'] == 'taken' else 400
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('tenant.slug_changed', 'tenant', tenant_id,
                        entity_name=tenant.get('company_name'),
                        old_value=result.get('previous'), new_value=result.get('slug'))
    return jsonify({'success': True, 'slug': result['slug'],
                    'redirectCreated': bool(result.get('redirect_created'))})


@app.route('/api/admin/tenants/<tenant_id>/activation', methods=['GET'])
@require_admin
def api_admin_tenant_activation_checklist(tenant_id):
    """t50: what is still missing before this company may go live."""
    tenant, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    checklist = db.tenant_activation_checklist(tenant)
    return jsonify({'success': True, 'isActive': bool(tenant.get('is_active')),
                    'activatedAt': tenant.get('activated_at'),
                    'activatedByName': tenant.get('activated_by_name'),
                    'checklist': checklist})


@app.route('/api/admin/tenants/<tenant_id>/activation', methods=['POST'])
@require_admin
def api_admin_set_tenant_activation(tenant_id):
    """t50: activate or suspend a company; activation passes through the gate."""
    tenant, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    data = request.json or {}
    is_active = bool(data.get('isActive', True))
    if is_active and tenant.get('is_active'):
        return jsonify({'success': True, 'tenant': _company_payload(tenant), 'unchanged': True})
    if not is_active and not tenant.get('is_active'):
        return jsonify({'success': True, 'tenant': _company_payload(tenant), 'unchanged': True})
    result = db.set_tenant_active(
        tenant_id, is_active, actor_id=_landloom_actor_id(),
        actor_name=_landloom_actor_name(), reason=data.get('reason'),
    )
    if result.get('error') == 'activation_incomplete':
        return jsonify({'error': 'activation_incomplete',
                        'missing': result.get('missing') or []}), 409
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('tenant.activated' if is_active else 'tenant.deactivated',
                        'tenant', tenant_id, entity_name=tenant.get('company_name'),
                        new_value={'reason': data.get('reason')} if not is_active else None)
    _notify_super_admins(
        'فُعّلت شركة' if is_active else 'عُلّقت شركة',
        tenant.get('company_name') or '',
        entity_type='tenant', entity_id=tenant_id)
    return jsonify({'success': True, 'tenant': _company_payload(result)})


@app.route('/api/admin/tenants/<tenant_id>/subscription', methods=['GET', 'POST'])
@require_admin
def api_admin_tenant_subscription(tenant_id):
    """t60: subscription window per company (one active at a time)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    if request.method == 'GET':
        return jsonify({'success': True,
                        'current': db.current_subscription(tenant_id),
                        'history': db.list_subscriptions(tenant_id)})
    data = request.json or {}
    row = db.create_subscription(
        tenant_id, package_id=data.get('packageId'),
        package_version_id=data.get('packageVersionId'),
        starts_at=data.get('startsAt'), ends_at=data.get('endsAt'),
        trial_ends_at=data.get('trialEndsAt'),
        status=data.get('status') or 'active',
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
    )
    _record_audit_event('tenant.subscription_changed', 'tenant', tenant_id,
                        new_value=row.get('package_id'))
    return jsonify({'success': True, 'subscription': row}), 201


@app.route('/api/admin/packages/<package_id>/versions', methods=['GET', 'POST'])
@require_admin
def api_admin_package_versions(package_id):
    """t60: immutable package versions — pricing changes never rewrite history."""
    if request.method == 'GET':
        return jsonify({'success': True,
                        'versions': db.list_package_versions(package_id)})
    data = request.json or {}
    row = db.create_package_version(
        package_id, name=data.get('name'), credit_usd=data.get('creditUsd'),
        price_sar=data.get('priceSar'), duration_days=data.get('durationDays'),
        limits=data.get('limits'), features=data.get('features'),
        actor_id=_landloom_actor_id(), actor_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('package.version_created', 'billing_package', package_id,
                        new_value=row.get('version'))
    return jsonify({'success': True, 'version': row}), 201


# ── Mission 5: registries, flags, queue, outbox, backups ────────────────────

@app.route('/api/admin/study-types', methods=['GET', 'POST'])
@require_admin
def api_admin_study_types():
    """t62: versioned study-type registry."""
    if request.method == 'GET':
        active_only = request.args.get('all') != '1'
        return jsonify({'success': True,
                        'studyTypes': db.list_study_types(active_only=active_only)})
    data = request.json or {}
    row = db.register_study_type(
        data.get('key'), data.get('nameAr'), name_en=data.get('nameEn'),
        definition=data.get('definition'),
        supersedes_version=data.get('supersedesVersion'),
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('study_type.registered', 'study_type', row['key'],
                        new_value=row.get('version'))
    return jsonify({'success': True, 'studyType': row}), 201


@app.route('/api/admin/generators', methods=['GET', 'POST'])
@require_admin
def api_admin_generators():
    """t62: versioned generator registry (templates, models, processors)."""
    if request.method == 'GET':
        return jsonify({'success': True,
                        'generators': db.list_generators(kind=request.args.get('kind'))})
    data = request.json or {}
    row = db.register_generator(
        data.get('kind'), data.get('key'), config=data.get('config'),
        label_ar=data.get('labelAr'), label_en=data.get('labelEn'),
        supersedes_version=data.get('supersedesVersion'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('generator.registered', 'generator_registry',
                        f"{row['kind']}:{row['key']}", new_value=row.get('version'))
    return jsonify({'success': True, 'generator': row}), 201


@app.route('/api/admin/jobs', methods=['GET'])
@require_admin
def api_admin_jobs():
    """t61: inspect the persistent background queue."""
    return jsonify({'success': True,
                    'jobs': db.list_jobs(status=request.args.get('status'),
                                         job_type=request.args.get('type')),
                    'stats': db.job_queue_stats()})


@app.route('/api/admin/jobs/requeue', methods=['POST'])
@require_admin
def api_admin_jobs_requeue():
    data = request.json or {}
    count = db.requeue_dead_jobs(job_type=data.get('type'))
    _record_audit_event('job_queue.requeue', 'job_queue', data.get('type'),
                        new_value=count)
    return jsonify({'success': True, 'requeued': count})


@app.route('/api/admin/email-outbox', methods=['GET'])
@require_admin
def api_admin_email_outbox():
    """t61/t41: outbound mail queue state."""
    return jsonify({'success': True,
                    'emails': db.list_email_outbox(status=request.args.get('status')),
                    'stats': db.email_outbox_stats()})


@app.route('/api/admin/housekeeping/run', methods=['POST'])
@require_admin
def api_admin_housekeeping_run():
    """t24/t41: run one housekeeping pass on demand — the same tick the
    background thread performs, so an operator or a cron can force it."""
    summary = _run_housekeeping_tick()
    _record_audit_event('housekeeping.run', 'housekeeping', 'manual',
                        metadata={'summary': summary})
    return jsonify({'success': True, 'summary': summary})


@app.route('/api/admin/backups', methods=['GET', 'POST'])
@require_admin
def api_admin_backups():
    """t63: backup registry — the run script POSTs each completed backup."""
    if request.method == 'GET':
        return jsonify({'success': True, 'backups': db.list_backups(),
                        'latest': db.latest_successful_backup(),
                        'rpoHours': db.RPO_TARGET_HOURS, 'rtoHours': db.RTO_TARGET_HOURS})
    data = request.json or {}
    row = db.record_backup(
        kind=data.get('kind') or 'full', path=data.get('path'),
        size_bytes=data.get('sizeBytes'), sha256=data.get('sha256'),
        encrypted=bool(data.get('encrypted')), note=data.get('note'),
    )
    _record_audit_event('backup.recorded', 'backup', row['id'],
                        new_value={'kind': row['kind'], 'size_bytes': row.get('size_bytes')})
    return jsonify({'success': True, 'backup': row}), 201


@app.route('/api/admin/backups/<backup_id>/restore-tested', methods=['POST'])
@require_admin
def api_admin_backup_restore_tested(backup_id):
    row = db.mark_backup_restore_tested(backup_id, note=(request.json or {}).get('note'))
    if not row:
        return jsonify({'error': 'Backup not found'}), 404
    _record_audit_event('backup.restore_tested', 'backup', backup_id)
    return jsonify({'success': True, 'backup': row})


# ── t55: dashboards and exportable reports ───────────────────────────────────

@app.route('/api/dashboard', methods=['GET'])
@require_auth
def api_client_dashboard():
    """Client home numbers: lifecycle buckets, open work, month spend."""
    return jsonify({'success': True, 'dashboard': db.client_dashboard(g.tenant_id)})


@app.route('/api/dashboard/activity', methods=['GET'])
@require_auth
def api_client_dashboard_activity():
    """Company activity chart series scoped to the caller's tenant."""
    return jsonify({'success': True, 'trends': db.client_activity_trends(
        g.tenant_id,
        months=request.args.get('months'),
        from_month=request.args.get('from'),
        to_month=request.args.get('to'))})


@app.route('/api/company/dashboard', methods=['GET'])
@require_permission('company_settings')
def api_company_dashboard():
    """Company super-admin view: overdue approvals, speed, spend split."""
    return jsonify({'success': True, 'dashboard': db.company_admin_dashboard(g.tenant_id)})


_ADMIN_REPORTS = {
    'ledger': ('حركات الرصيد', db.ledger_report_rows),
    'tickets': ('تذاكر الدعم', db.tickets_report_rows),
}


def _report_pdf_html(title, headers, rows, generated_note):
    """A4-landscape RTL table document for the platform report exports."""
    from design_templates import _load_bundled_fonts
    font_face = ''
    bundled = (_load_bundled_fonts().get('TheSansArabic-Light')
               or _load_bundled_fonts().get('TheSansArabic-Bold'))
    if bundled:
        data, fmt = bundled
        mime = {'truetype': 'font/ttf', 'opentype': 'font/otf',
                'woff2': 'font/woff2', 'woff': 'font/woff'}.get(fmt, 'font/ttf')
        font_face = ("@font-face{font-family:'report-arabic';"
                     f"src:url(data:{mime};base64,{data}) format('{fmt}');"
                     "font-display:swap;}")
    head_cells = ''.join(f'<th>{html_lib.escape(str(h))}</th>' for h in headers)
    body_rows = ''.join(
        '<tr>' + ''.join(
            f'<td>{html_lib.escape("" if cell is None else str(cell))}</td>'
            for cell in row) + '</tr>'
        for row in rows)
    return (
        '<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">'
        f'<style>{font_face}'
        "body{font-family:'report-arabic','IBM Plex Sans Arabic',Tahoma,Arial,sans-serif;"
        'direction:rtl;color:#1a1a1a;margin:0}'
        'h1{font-size:15px;color:#123B6D;margin:0 0 2px}'
        '.note{font-size:9px;color:#666;margin:0 0 10px}'
        'table{width:100%;border-collapse:collapse;font-size:9px}'
        'thead{display:table-header-group}'
        'th{background:#123B6D;color:#fff;border:1px solid #123B6D;padding:5px 6px;'
        'text-align:right;font-weight:600}'
        'td{border:1px solid #c9d2dc;padding:4px 6px;text-align:right;'
        'vertical-align:top;word-break:break-word}'
        'tr:nth-child(even) td{background:#f5f7fa}'
        '</style></head><body>'
        f'<h1>{html_lib.escape(title)}</h1>'
        f'<div class="note">{html_lib.escape(generated_note)}</div>'
        f'<table><thead><tr>{head_cells}</tr></thead>'
        f'<tbody>{body_rows}</tbody></table>'
        '</body></html>')


def _serve_report_pdf(report_name, tenant_id=None):
    """Shared admin/company report export: register rows -> RTL HTML -> PDF."""
    entry = _ADMIN_REPORTS.get(report_name)
    if not entry:
        return jsonify({'error': 'Unknown report'}), 404
    title, row_fn = entry
    try:
        limit = max(1, min(int(request.args.get('limit') or 5000), 5000))
    except (TypeError, ValueError):
        limit = 5000
    headers, rows = row_fn(
        tenant_id=tenant_id,
        from_date=request.args.get('from'),
        to_date=request.args.get('to'),
        limit=limit)
    note = datetime.now().strftime('%Y-%m-%d %H:%M') + f' — {len(rows)} صف'
    if len(rows) >= limit:
        note += ' — وصل التقرير الحد الأقصى للصفوف'
    report_html = _report_pdf_html(title, headers, rows, note)
    import tempfile
    fd, pdf_path = tempfile.mkstemp(prefix=f'{report_name}-report-', suffix='.pdf')
    os.close(fd)
    try:
        generate_financial_pdf(report_html, pdf_path, min_text=20)
        with open(pdf_path, 'rb') as handle:
            payload = handle.read()
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass
    response = app.make_response(payload)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = \
        f'attachment; filename="{report_name}-report.pdf"'
    return response


@app.route('/api/admin/reports/<report_name>', methods=['GET'])
@require_admin
def api_admin_export_report(report_name):
    """t55: PDF export of the operational/financial registers."""
    return _serve_report_pdf(report_name, tenant_id=request.args.get('tenantId'))


@app.route('/api/company/reports/<report_name>', methods=['GET'])
@require_permission('company_settings')
def api_company_export_report(report_name):
    """t55: the company admin exports only their own registers."""
    if report_name not in ('ledger', 'tickets'):
        return jsonify({'error': 'Unknown report'}), 404
    return _serve_report_pdf(report_name, tenant_id=g.tenant_id)



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == '__main__':
    print("=" * 60)
    print("  Real Estate Proposal Generator - GLM-First Architecture")
    print("=" * 60)
    print(f"  GLM Model: {GLM_MODEL}")
    print(f"  Image Model: {IMAGE_MODEL}")
    print(f"  Output Dir: {OUTPUT_DIR}")
    print("=" * 60)
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
    print(f"  Image Model: {IMAGE_MODEL}")
    print(f"  Output Dir: {OUTPUT_DIR}")
    print("=" * 60)
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
    print("=" * 60)
    print("  Real Estate Proposal Generator - GLM-First Architecture")
    print("=" * 60)
    print(f"  GLM Model: {GLM_MODEL}")
    print(f"  Image Model: {IMAGE_MODEL}")
    print(f"  Output Dir: {OUTPUT_DIR}")
    print("=" * 60)
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
    print(f"  Image Model: {IMAGE_MODEL}")
    print(f"  Output Dir: {OUTPUT_DIR}")
    print("=" * 60)
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
