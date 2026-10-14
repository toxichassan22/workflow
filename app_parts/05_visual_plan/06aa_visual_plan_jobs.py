_VISUAL_PLAN_JOB_NAMESPACE = '.visual_plan_jobs'


def _visual_plan_execute(kind, data, slot_id=''):
    try:
        if kind == 'prepare':
            scene, context, reference_url = _visual_plan_create_scene(data)
            context['client_notes'] = _visual_plan_notes(data)
            distribution = (data.get('plansWorkflow') or {}).get('distribution') or {}
            model = (_visual_concept_plan_model_from_distribution(distribution, context, context.get('regulations') or {})
                     or _visual_concept_plan_model(context, context.get('regulations') or {}))
            result = {'success': True, 'scene': scene,
                      'prompts': _visual_concept_plan_prompt_templates(context, model),
                      'context': context, 'referenceUrl': reference_url}
        elif kind == 'prompt':
            # The drawing prompt is fully derived from the fixed context and the
            # approved distribution — the sealed scene only proves the inputs are
            # still identical. Render and edit keep demanding it; the prompt text
            # stays available so a stale draft can be refreshed before re-sealing.
            workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
            posted_scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
            scene = None
            if (posted_scene and posted_scene.get('version') == VISUAL_PLAN_SCENE_VERSION
                    and isinstance(posted_scene.get('token'), str) and posted_scene['token'].strip()):
                scene, _contract, context, _program = _visual_plan_scene_from_request(data)
            else:
                context = _visual_plan_prompt_context(data)
                if not _visual_plan_notes_cleared(data, context):
                    raise visual_plan_geometry.PlanGeometryError('فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.', 'PLANS_NOTES_CHECK_REQUIRED')
            context['client_notes'] = _visual_plan_notes(data)
            distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
            model = (_visual_concept_plan_model_from_distribution(distribution, context, context.get('regulations') or {})
                     or _visual_concept_plan_model(context, context.get('regulations') or {}))
            result = {'success': True, 'slotId': slot_id, 'scene': scene,
                      'prompt': _visual_concept_plan_drawing_prompt(_visual_concept_plan_kind(slot_id), context, model),
                      'engine': 'surveyed_geometry' if scene else 'deterministic', 'reply': ''}
        elif kind == 'notes':
            review, frontage = _visual_plan_review_notes(data)
            result = {'success': True, 'notesReview': review, 'primaryFrontage': frontage}
        elif kind == 'edit':
            result = _visual_plan_edit_scene(data, slot_id)
        elif kind == 'render':
            result = _visual_plan_render_response(data, slot_id)
        else:
            return {'success': False, 'error_code': 'PLANS_OPERATION_INVALID'}, 400
        return result, 200
    except visual_plan_geometry.PlanGeometryError as error:
        status = 503 if error.code in ('PLANS_NOTES_CHECK_FAILED', 'PLANS_PROVIDER_FAILED') else 400
        return {'success': False, 'error': str(error), 'error_code': error.code}, status
    except (TypeError, ValueError) as error:
        app.logger.warning('Visual plan data refused: %s', type(error).__name__)
        return {'success': False, 'error': 'بيانات المشهد الهندسي غير صالحة.', 'error_code': 'PLANS_DATA_INVALID'}, 400
    except Exception as error:
        fatal = _ai_fatal_http_response(error)
        if fatal is not None:
            response = app.make_response(fatal)
            return response.get_json(), response.status_code
        app.logger.warning('Visual plan operation failed: %s', type(error).__name__)
        return {'success': False, 'error': 'تعذرت معالجة المخطط الهندسي.', 'error_code': 'PLANS_PROVIDER_FAILED'}, 503


def _visual_plan_job_worker(flask_app, actor, data, kind, slot_id, job_id):
    tenant_id = actor['tenant_id']
    with flask_app.test_request_context('/api/visual-concept/plans-jobs/' + job_id, method='POST', json=data):
        for key, value in actor.items():
            setattr(g, key, value)
        try:
            tenant = db.get_tenant_by_id(tenant_id)
            payload = actor.get('token_payload') or {}
            user, auth_error = auth._load_token_user(payload, tenant) if tenant else (None, None)
            session_error = auth._session_state_error(payload, tenant, user) if tenant and tenant.get('is_active') and auth_error is None else None
            g.tenant = tenant
            g.user_id = (user or {}).get('id')
            g.user_role = (user or {}).get('role') or actor.get('user_role')
            g.is_admin = auth._is_platform_admin_session(tenant, payload) if tenant else False
            g.user_permissions = db.get_user_permissions(g.user_id, g.user_role) if g.user_id else {}
            if not tenant or not tenant.get('is_active') or auth_error is not None or session_error is not None or payload.get('exp', 0) < time.time() or not _landloom_can('generate_images'):
                result, status = {'success': False, 'error': 'صلاحية معالجة المخططات غير متاحة.',
                                  'error_code': 'PLANS_PERMISSION_REQUIRED'}, 403
            else:
                _write_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id,
                           {'status': 'running', 'success': True, 'progress': 20})
                result, status = _visual_plan_execute(kind, data, slot_id)
            _write_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id,
                       {'status': 'completed' if result.get('success') else 'failed',
                        'success': bool(result.get('success')), 'progress': 100,
                        'result': result, 'httpStatus': status})
            if not flask_app.config.get('TESTING'):
                _bill_tenant_unbilled_usage_async(tenant_id)
        except Exception as error:
            app.logger.warning('Visual plan worker failed: %s', type(error).__name__)
            _write_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id,
                       {'status': 'failed', 'success': False, 'progress': 100, 'httpStatus': 503,
                        'result': {'success': False, 'error': 'تعذرت معالجة المخطط الهندسي.',
                                   'error_code': 'PLANS_PROVIDER_FAILED'}})


def _visual_plan_dispatch(kind, data, slot_id=''):
    if kind == 'render' or current_app.config.get('TESTING') and data.get('background') is not True:
        result, status = _visual_plan_execute(kind, data, slot_id)
        return jsonify(result), status
    job_id = _uuid.uuid4().hex
    actor = {key: getattr(g, key, None) for key in
             ('tenant_id', 'user_id', 'user_name', 'user_role', 'is_admin', 'token_payload')}
    _write_job(_VISUAL_PLAN_JOB_NAMESPACE, g.tenant_id, job_id,
               {'status': 'queued', 'success': True, 'progress': 5, 'actor': actor,
                'payload': {'data': data, 'kind': kind, 'slotId': slot_id}})
    threading.Thread(target=_visual_plan_job_worker,
                     args=(current_app._get_current_object(), actor, data, kind, slot_id, job_id),
                     daemon=True).start()
    return jsonify({'success': True, 'jobId': job_id, 'status': 'queued', 'progress': 5}), 202


@app.route('/api/visual-concept/plans-notes-check', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plan_notes_check():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error_code': 'INVALID_REQUEST'}), 400
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    if _visual_plan_notes(data):
        billing_guard = _require_billing_balance('visual_concept')
        if billing_guard is not None:
            return billing_guard
    return _visual_plan_dispatch('notes', data)


@app.route('/api/visual-concept/plans-notes-acknowledge', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_plan_notes_acknowledge():
    """Mints the signed responsibility acknowledgement that clears written
    notes which are unchecked or failed their review — the acknowledge call
    itself is the client's signature, so it stays instant and free."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error_code': 'INVALID_REQUEST'}), 400
    workflow_error = _visual_concept_plan_workflow_error(data, 'plan_site')
    if workflow_error:
        return jsonify(workflow_error), 400
    try:
        return jsonify({'success': True, 'notesAck': _visual_plan_notes_ack(data)})
    except visual_plan_geometry.PlanGeometryError as error:
        return jsonify({'success': False, 'error': str(error), 'error_code': error.code}), 400


@app.route('/api/visual-concept/plans-jobs/<job_id>', methods=['GET'])
@require_permission('generate_images')
def api_visual_concept_plan_job(job_id):
    try:
        job = _read_job(_VISUAL_PLAN_JOB_NAMESPACE, g.tenant_id, job_id)
    except ValueError:
        job = None
    if not job:
        return jsonify({'success': False, 'error': 'مهمة المخططات غير موجودة.', 'error_code': 'JOB_NOT_FOUND'}), 404
    if job.get('status') in ('queued', 'running') and time.time() - job.get('updatedAt', 0) > 240:
        job = {'status': 'failed', 'success': False, 'progress': 100, 'httpStatus': 503,
               'result': {'success': False, 'error': 'انتهت مهلة معالجة المشهد الهندسي.',
                          'error_code': 'PLANS_JOB_EXPIRED'}}
        _write_job(_VISUAL_PLAN_JOB_NAMESPACE, g.tenant_id, job_id, job)
    return jsonify({key: job[key] for key in ('status', 'success', 'progress', 'result', 'httpStatus') if key in job})
