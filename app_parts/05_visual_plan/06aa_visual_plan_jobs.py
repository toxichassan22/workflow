_VISUAL_PLAN_JOB_NAMESPACE = '.visual_plan_jobs'
_VISUAL_PLAN_JOB_TIMEOUT_SECONDS = 600
# The floor distribution thinks at maximum reasoning effort on the full project
# brief, so its turn gets a quarter hour of provider time plus the margin the
# job deadline needs to outlive it.
_VISUAL_PLAN_DISTRIBUTION_JOB_TIMEOUT_SECONDS = 1200


def _visual_plan_job_timeout_seconds(kind=''):
    """The absolute deadline of one job, per kind.

    The distribution turn answers on the slowest model the product owns, so it
    gets its own ceiling instead of inheriting the shorter one.
    """
    if kind == 'distribution':
        return _VISUAL_PLAN_DISTRIBUTION_JOB_TIMEOUT_SECONDS
    return _VISUAL_PLAN_JOB_TIMEOUT_SECONDS


def _visual_plan_job_subject(kind):
    """What the job is working on — the wording follows the job, not the plans.

    The same queue also carries the visual-concept image and chat jobs, and
    telling a client its image generation expired «المخطط الهندسي» would be
    a lie about what it was doing.
    """
    if kind == 'image':
        return 'التصور البصري'
    if kind == 'chat':
        return 'وصف التصور البصري'
    if kind == 'edit_image':
        return 'تعديل التصور البصري'
    if kind == 'distribution':
        return 'توزيع الأدوار'
    return 'المخطط الهندسي'


def _visual_plan_job_call_timeout(default=1200):
    """Keep provider requests inside their job's absolute deadline."""
    if not has_request_context():
        return default
    deadline = getattr(g, 'visual_plan_job_deadline', None)
    if deadline is None:
        return default
    remaining = deadline - time.time()
    if remaining <= 0:
        raise visual_plan_geometry.PlanGeometryError(
            'انتهت مهلة معالجة ' + _visual_plan_job_subject(
                getattr(g, 'visual_plan_job_kind', '')) + '.', 'PLANS_JOB_EXPIRED')
    return max(1, min(int(default), int(remaining)))


def _visual_plan_job_todos(kind, state='running', active_index=None):
    """Small real-work checklist exposed while a visual-plan job is active."""
    labels = {
        'prepare': ['قراءة بيانات الموقع والتوزيع', 'تكوين المشهد الهندسي', 'تجهيز بيانات المخطط'],
        'render': ['تجميع بيانات الأرض والاشتراطات', 'كتابة كود المخطط', 'فحص SVG وتجهيز المعاينة'],
        'edit': ['قراءة طلب التعديل والمخطط الحالي', 'تعديل الجزء المحدد', 'فحص SVG وتجهيز المعاينة'],
        'prompt': ['قراءة بيانات المخطط', 'تجهيز وصف التوليد'],
        'notes': ['مراجعة ملاحظات التوليد', 'تجهيز نتيجة الفحص'],
        'site_chat': ['فحص بيانات الأرض والتوزيع', 'تجهيز المشهد الهندسي',
                      'مراجعة الإجابات السابقة', 'تحليل المتطلبات وتحديد السؤال'],
        'site_generate': ['تأكيد اكتمال المتطلبات', 'كتابة أقسام كود SVG', 'فحص المخطط وتجهيز المعاينة'],
        'site_edit': ['قراءة كود SVG والطلب', 'تعديل القسم المستهدف', 'فحص المخطط وتجهيز المعاينة'],
        'distribution': ['قراءة بيانات المشروع والتوزيع', 'اقتراح توزيع الأدوار', 'مراجعة النتيجة'],
        'image': ['قراءة وصف التصور البصري', 'توليد الصورة'],
        'chat': ['قراءة طلب التعديل', 'تحديث وصف الصورة'],
        'edit_image': ['قراءة طلب التعديل والصورة الحالية', 'توليد الصورة المعدّلة'],
    }.get(kind, ['معالجة المخطط'])
    active = (active_index if active_index is not None else
              {'prepare': 0, 'render': 1, 'edit': 1, 'prompt': 1, 'notes': 0}.get(kind, 0))
    rows = []
    for index, label in enumerate(labels):
        if state == 'completed' or state in ('running', 'failed') and index < active:
            status = 'done'
        elif state == 'failed' and index == active:
            status = 'failed'
        elif state == 'running' and index == active:
            status = 'active'
        else:
            status = 'pending'
        rows.append({'id': str(index + 1), 'label': label, 'status': status})
    return rows


def _visual_plan_job_terminal_todos(kind, state, current_todos=None, active_index=None):
    rows = current_todos if isinstance(current_todos, list) else []
    has_site_svg_steps = (kind in ('site_chat', 'site_generate') and any(
        isinstance(item, dict) and item.get('stage') in ('site_svg_section', 'site_svg_assembly')
        for item in rows))
    if has_site_svg_steps:
        target_index = next((index for index, item in enumerate(rows)
                            if isinstance(item, dict) and item.get('status') == 'active'), None)
        if target_index is None:
            target_index = next((index for index, item in enumerate(rows)
                                if isinstance(item, dict) and item.get('status') == 'pending'), None)
        result = []
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if state == 'completed':
                row['status'] = 'done'
            elif index == target_index:
                row['status'] = 'failed'
            elif row.get('status') == 'active':
                row['status'] = 'pending'
            result.append(row)
        return result
    return _visual_plan_job_todos(kind, state, active_index=active_index)


def _visual_plan_report_site_chat_progress(active_index, progress):
    if not has_request_context() or getattr(g, 'visual_plan_job_kind', '') not in ('site_chat', 'site_edit', 'site_generate'):
        return
    callback = getattr(g, 'visual_plan_job_progress', None)
    if callable(callback):
        callback(progress=progress,
                 todos=_visual_plan_job_todos(getattr(g, 'visual_plan_job_kind', 'site_chat'), active_index=active_index))


def _visual_plan_report_site_chat_timing(name, started_at):
    if not has_request_context() or getattr(g, 'visual_plan_job_kind', '') not in (
            'site_chat', 'site_edit', 'site_generate'):
        return
    callback = getattr(g, 'visual_plan_job_progress', None)
    if callable(callback):
        callback(timing={name: max(0, round((time.perf_counter() - started_at) * 1000))})


def _visual_plan_edit_diagram(data, slot_id, kind_type):
    if kind_type == 'uses':
        return _visual_plan_edit_uses_svg(data, slot_id)
    if kind_type == 'massing':
        return _visual_plan_edit_massing_svg(data, slot_id)
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        raise visual_plan_geometry.PlanGeometryError('طلب تعديل المخطط غير متوفر.', 'MESSAGE_REQUIRED')
    context = _visual_plan_prompt_context(data)
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    prompt = _visual_plan_slot_prompt(workflow, kind_type, context)
    base_image = _visual_concept_edit_base_image(data, g.tenant_id)
    if not base_image:
        raise visual_plan_geometry.PlanGeometryError('لا توجد صورة حالية قابلة للتعديل.', 'IMAGE_REQUIRED')
    references = [base_image]
    plan_images = data.get('planImages') if isinstance(data.get('planImages'), dict) else {}
    site_image = plan_images.get('site') or ''
    if site_image and site_image not in references:
        site_uris = _visual_concept_reference_uris(urls=[site_image], tenant_id=g.tenant_id)
        references.extend(site_uris)
    edit_prompt = (
        f"{prompt}\n\nUSER MODIFICATION INSTRUCTION: Apply this specific change to the attached current plan: {instruction}. "
        "Keep all other details, building layout, and colors consistent."
    )
    image = call_images_api(edit_prompt, references, model=VISUAL_CONCEPT_IMAGE_MODEL,
                            timeout=_visual_plan_job_call_timeout(180),
                            usage_ctx=_usage_ctx('image', data))
    if not image:
        err = last_images_api_error() or {}
        if err.get('fatal') or err.get('error_code') in _FATAL_AI_ERROR_CODES:
            raise FatalAICallError(err.get('message'), error_code=err.get('error_code'),
                                   http_status=err.get('http_status'),
                                   provider_message=err.get('provider_message'))
        raise visual_plan_geometry.PlanGeometryError(
            _client_safe_llm_error(err.get('message') or 'تعذر تعديل صورة المخطط.'),
            'PLANS_PROVIDER_FAILED')
    return {'success': True, 'slotId': slot_id, 'image': persist_generated_image(image, g.tenant_id),
            'prompt': prompt, 'reply': 'تم تعديل المخطط.', 'model': VISUAL_CONCEPT_IMAGE_MODEL}


def _visual_plan_execute(kind, data, slot_id=''):
    try:
        if kind == 'prepare':
            workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
            context = _visual_plan_prompt_context(data)
            context['client_notes'] = _visual_plan_notes(data)
            distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
            model = (_visual_concept_plan_model_from_distribution(distribution, context, context.get('regulations') or {})
                     or _visual_concept_plan_model(context, context.get('regulations') or {}))
            prompts = _visual_concept_plan_prompt_templates(context, model)
            scene = workflow.get('scene')
            reference_url = None
            if isinstance(scene, dict):
                reference_url = scene.get('referenceUrl')
            if not reference_url and context.get('survey_points'):
                try:
                    reference_url = _visual_concept_render_plan_boundary_reference(
                        context['survey_points'], g.tenant_id)
                except Exception:
                    reference_url = None
            result = {'success': True, 'scene': scene,
                      'prompts': prompts,
                      'context': context, 'referenceUrl': reference_url}
        elif kind == 'prompt':
            workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
            kind_type = _visual_concept_plan_kind(slot_id)
            if kind_type in ('uses', 'massing'):
                context = _visual_plan_prompt_context(data)
                context['client_notes'] = _visual_plan_notes(data)
                distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
                model = (_visual_concept_plan_model_from_distribution(distribution, context, context.get('regulations') or {})
                         or _visual_concept_plan_model(context, context.get('regulations') or {}))
                scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
                result = {'success': True, 'slotId': slot_id, 'scene': scene,
                          'prompt': _visual_concept_plan_drawing_prompt(kind_type, context, model),
                          'engine': 'surveyed_geometry' if scene else 'image_generation', 'reply': ''}
            else:
                posted_scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
                scene = None
                if (posted_scene and posted_scene.get('version') == VISUAL_PLAN_SCENE_VERSION
                        and isinstance(posted_scene.get('token'), str) and posted_scene['token'].strip()):
                    scene, _contract, context, _program = _visual_plan_scene_from_request(data)
                else:
                    context = _visual_plan_prompt_context(data)
                    notes_gate = _visual_plan_notes_gate(data, context)
                    if not notes_gate.get('cleared'):
                        raise visual_plan_geometry.PlanGeometryError(
                            notes_gate.get('message') or 'فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.',
                            'PLANS_NOTES_CHECK_REQUIRED')
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
            kind_type = _visual_concept_plan_kind(slot_id)
            if kind_type == 'uses':
                result = _visual_plan_edit_uses_svg(data, slot_id)
            elif kind_type == 'massing':
                result = _visual_plan_edit_diagram(data, slot_id, kind_type)
            else:
                result = _visual_plan_edit_scene(data, slot_id)
        elif kind == 'render':
            result = _visual_plan_render_response(data, slot_id)
        elif kind in ('site_chat', 'site_generate', 'site_edit'):
            result, status = _visual_plan_site_assistant_execute(data, kind.removeprefix('site_'))
            return result, status
        elif kind == 'image':
            result, status = _visual_concept_generate_image_result(data, slot_id)
            return result, status
        elif kind == 'chat':
            result, status = _visual_concept_chat_result(data, slot_id)
            return result, status
        elif kind == 'edit_image':
            result, status = _visual_concept_edit_result(data, slot_id)
            return result, status
        elif kind == 'distribution':
            result, status = _plans_distribution_chat_execute(data)
            return result, status
        else:
            return {'success': False, 'error_code': 'PLANS_OPERATION_INVALID'}, 400
        return result, 200
    except visual_plan_geometry.PlanGeometryError as error:
        status = 503 if error.code in ('PLANS_NOTES_CHECK_FAILED', 'PLANS_PROVIDER_FAILED',
                                       'PLANS_JOB_EXPIRED') else 400
        return {'success': False, 'error': str(error), 'error_code': error.code}, status
    except (TypeError, ValueError) as error:
        app.logger.warning('Visual plan data refused: %s', type(error).__name__)
        return {'success': False, 'error': 'بيانات المشهد الهندسي غير صالحة.', 'error_code': 'PLANS_DATA_INVALID'}, 400
    except Exception as error:
        fatal = _ai_fatal_http_response(error)
        if fatal is not None:
            response = app.make_response(fatal)
            return response.get_json(), response.status_code
        app.logger.warning('Visual plan operation failed: %s: %s', type(error).__name__, error, exc_info=True)
        return {'success': False,
                'error': 'تعذرت معالجة ' + _visual_plan_job_subject(kind) + '.',
                'error_code': 'PLANS_PROVIDER_FAILED'}, 503


def _visual_plan_job_worker(flask_app, actor, data, kind, slot_id, job_id):
    tenant_id = actor['tenant_id']
    with flask_app.test_request_context('/api/visual-concept/plans-jobs/' + job_id, method='POST', json=data):
        # The stop button reaches this plan through the run registry; the
        # thread dies with the worker, so the handle cannot leak.
        run_control.bind_run(job_id, tenant_id)
        for key, value in actor.items():
            setattr(g, key, value)
        initial_job = _read_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id) or {}
        try:
            g.visual_plan_job_deadline = float(initial_job.get('deadlineAt'))
        except (TypeError, ValueError):
            g.visual_plan_job_deadline = time.time() + _visual_plan_job_timeout_seconds(kind)
        g.visual_plan_job_kind = kind
        def report_progress(progress=None, todos=None, checkpoint=None, timing=None):
            try:
                current = _read_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id) or {}
            except Exception:
                current = {}
            if progress is not None or todos is not None or checkpoint is not None:
                current.update({'status': 'running', 'success': True})
            if progress is not None:
                current['progress'] = max(5, min(99, int(progress)))
            if todos is not None:
                current['todos'] = todos
            if checkpoint is not None:
                current['checkpoint'] = checkpoint
            if isinstance(timing, dict):
                timings = current.get('timings') if isinstance(current.get('timings'), dict) else {}
                timings.update({str(name): max(0, int(duration)) for name, duration in timing.items()})
                current['timings'] = timings
            _write_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id, current)
        g.visual_plan_job_progress = report_progress
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
                           {'status': 'running', 'success': True, 'progress': 20,
                            'createdAt': initial_job.get('createdAt'),
                            'deadlineAt': g.visual_plan_job_deadline,
                            'timeoutSeconds': initial_job.get('timeoutSeconds', _VISUAL_PLAN_JOB_TIMEOUT_SECONDS),
                            'todos': _visual_plan_job_todos(kind)})
                if time.time() >= g.visual_plan_job_deadline:
                    result, status = {'success': False,
                                      'error': 'انتهت مهلة معالجة ' + _visual_plan_job_subject(kind) + '.',
                                      'error_code': 'PLANS_JOB_EXPIRED'}, 503
                else:
                    result, status = _visual_plan_execute(kind, data, slot_id)
            if time.time() >= g.visual_plan_job_deadline:
                result, status = {'success': False,
                                  'error': 'انتهت مهلة معالجة ' + _visual_plan_job_subject(kind) + '.',
                                  'error_code': 'PLANS_JOB_EXPIRED'}, 503
            final_job = _read_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id) or {}
            existing_result = final_job.get('result') if isinstance(final_job.get('result'), dict) else {}
            if final_job.get('status') == 'failed' and existing_result.get('error_code') == 'PLANS_JOB_EXPIRED':
                if not flask_app.config.get('TESTING'):
                    _bill_tenant_unbilled_usage_async(tenant_id)
                return
            result_state = 'completed' if result.get('success') else 'failed'
            active_index = next((index for index, item in enumerate(final_job.get('todos') or [])
                                 if isinstance(item, dict) and item.get('status') == 'active'), None)
            final_job.update({'status': 'completed' if result.get('success') else 'failed',
                              'success': bool(result.get('success')), 'progress': 100,
                              'todos': _visual_plan_job_terminal_todos(
                                  kind, result_state, current_todos=final_job.get('todos'),
                                  active_index=active_index),
                              'result': result, 'httpStatus': status})
            _write_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id, final_job)
            if not flask_app.config.get('TESTING'):
                _bill_tenant_unbilled_usage_async(tenant_id)
        except Exception as error:
            app.logger.warning('Visual plan worker failed: %s', type(error).__name__)
            failed_job = _read_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id) or {}
            existing_result = failed_job.get('result') if isinstance(failed_job.get('result'), dict) else {}
            if failed_job.get('status') == 'failed' and existing_result.get('error_code') == 'PLANS_JOB_EXPIRED':
                return
            active_index = next((index for index, item in enumerate(failed_job.get('todos') or [])
                                 if isinstance(item, dict) and item.get('status') == 'active'), None)
            expired = time.time() >= g.visual_plan_job_deadline
            failed_job.update({'status': 'failed', 'success': False, 'progress': 100,
                               'todos': _visual_plan_job_terminal_todos(
                                   kind, 'failed', current_todos=failed_job.get('todos'),
                                   active_index=active_index),
                               'httpStatus': 503,
                               'result': {'success': False,
                                          'error': ('انتهت مهلة معالجة ' + _visual_plan_job_subject(kind) + '.'
                                                    if expired
                                                    else 'تعذرت معالجة ' + _visual_plan_job_subject(kind) + '.'),
                                          'error_code': ('PLANS_JOB_EXPIRED' if expired
                                                         else 'PLANS_PROVIDER_FAILED')}})
            _write_job(_VISUAL_PLAN_JOB_NAMESPACE, tenant_id, job_id, failed_job)


def _visual_plan_dispatch(kind, data, slot_id=''):
    if current_app.config.get('TESTING') and data.get('background') is not True:
        result, status = _visual_plan_execute(kind, data, slot_id)
        return jsonify(result), status
    job_id = _uuid.uuid4().hex
    created_at = time.time()
    timeout_seconds = _visual_plan_job_timeout_seconds(kind)
    deadline_at = created_at + timeout_seconds
    actor = {key: getattr(g, key, None) for key in
             ('tenant_id', 'user_id', 'user_name', 'user_role', 'is_admin', 'token_payload')}
    _write_job(_VISUAL_PLAN_JOB_NAMESPACE, g.tenant_id, job_id,
               {'status': 'queued', 'success': True, 'progress': 5, 'actor': actor,
                'createdAt': created_at, 'deadlineAt': deadline_at,
                'timeoutSeconds': timeout_seconds,
                'todos': _visual_plan_job_todos(kind, 'queued'),
                'payload': {'data': data, 'kind': kind, 'slotId': slot_id}})
    threading.Thread(target=_visual_plan_job_worker,
                     args=(current_app._get_current_object(), actor, data, kind, slot_id, job_id),
                     daemon=True).start()
    return jsonify({'success': True, 'jobId': job_id, 'status': 'queued', 'progress': 5,
                    'timeoutSeconds': timeout_seconds}), 202


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
    try:
        deadline_at = float(job.get('deadlineAt'))
    except (TypeError, ValueError):
        deadline_at = (float(job.get('createdAt') or job.get('updatedAt') or time.time())
                       + _visual_plan_job_timeout_seconds(
                           ((job.get('payload') or {}).get('kind') or '')))
    if job.get('status') in ('queued', 'running') and time.time() >= deadline_at:
        kind = ((job.get('payload') or {}).get('kind') or 'render')
        todos = job.get('todos') if isinstance(job.get('todos'), list) else []
        active_index = next((index for index, item in enumerate(todos)
                             if isinstance(item, dict) and item.get('status') == 'active'), None)
        if active_index is None:
            active_index = next((index for index, item in enumerate(todos)
                                 if isinstance(item, dict) and item.get('status') == 'pending'), 0)
        job = dict(job)
        job.update({'status': 'failed', 'success': False, 'progress': 100, 'httpStatus': 503,
                    'todos': _visual_plan_job_terminal_todos(
                        kind, 'failed', current_todos=todos, active_index=active_index),
                    'result': {'success': False, 'error': 'انتهت مهلة معالجة المشهد الهندسي.',
                               'error_code': 'PLANS_JOB_EXPIRED'}})
        created_at = job.get('createdAt')
        if created_at is not None:
            try:
                timings = job.get('timings') if isinstance(job.get('timings'), dict) else {}
                timings['job_total_ms'] = max(0, round((time.time() - float(created_at)) * 1000))
                job['timings'] = timings
            except (TypeError, ValueError):
                pass
        _write_job(_VISUAL_PLAN_JOB_NAMESPACE, g.tenant_id, job_id, job)
    return jsonify({key: job[key] for key in
                    ('status', 'success', 'progress', 'todos', 'checkpoint', 'result', 'httpStatus',
                     'timeoutSeconds', 'createdAt', 'updatedAt', 'timings', 'partial') if key in job})
