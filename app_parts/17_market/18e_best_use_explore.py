def _best_use_explore_provider(response):
    result = openrouter_response_message(response, 'BEST-USE-EXPLORE')
    if result.get('finish_reason') not in (None, 'stop', 'end_turn'):
        raise best_use_contract.ProposalError('استجابة الاستكشاف غير مكتملة.')
    parsed = parse_json_object(result.get('content'))
    if not isinstance(parsed, dict):
        raise best_use_contract.ProposalError('استجابة الاستكشاف ليست JSON صالحًا.')
    def clean(value, key=''):
        if isinstance(value, dict):
            return {name: clean(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [clean(item, key) for item in value]
        if isinstance(value, str) and key not in {'excerpt', 'url', 'documentId', 'parcelScope', 'landClassification'}:
            return _land_chat_clean_reply(slide_engine._strip_presentation_icons(value))
        return value
    return clean(parsed)


def _best_use_explore_targets(kind, data):
    if kind == 'concepts':
        return ('regulations', 'priceScan', 'concepts')
    if kind == 'chat' and data.get('revise') is not True:
        return ()
    return ('landDistribution',) if data.get('stage') == 'land' else ('floorDistribution',)


def _best_use_explore_stage_error(project, kind, data):
    if kind == 'concepts':
        return None
    stage = data.get('stage')
    if not isinstance(stage, str) or stage not in {'land', 'floors'}:
        return _best_use_error('BEST_USE_STAGE_REQUIRED', 400)
    required = 'concepts' if stage == 'land' else 'landDistribution'
    if not best_use_workflow.current(project, required) or not best_use_workflow.selected_concept(project):
        return _best_use_error('BEST_USE_STAGE_REQUIRED', 409)
    return None


def _best_use_explore_execute(draft, data, kind, job=None):
    project = copy.deepcopy(draft.get('draft_data') or {})
    state = best_use_contract.read_object(project.get('best_use_explore_data'))
    state.setdefault('mode', 'explore')
    project['best_use_explore_data'] = state
    if (draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved' and (kind != 'chat' or data.get('revise') is True):
        return _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
    targets = _best_use_explore_targets(kind, data)
    if any(best_use_workflow.approved(project, name) for name in targets):
        return _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
    stage_error = _best_use_explore_stage_error(project, kind, data)
    if stage_error:
        return stage_error
    # The step name is the progress here: the stages are real, the constant
    # percentage that used to ride along with them was not.
    def progress(step, detail=None):
        if job:
            payload = {'status': 'running', 'flow': 'explore',
                'draftId': draft['id'], 'step': step}
            if detail:
                payload['detail'] = detail
            _write_job(_BEST_USE_JOB_NAMESPACE, job[0], job[1], payload)
    try:
        if kind == 'concepts':
            progress('regulations')
            regulation_data = _best_use_extract_regulations(draft, data)
            state['regulations'] = best_use_workflow.make_artifact(project, 'regulations', regulation_data,
                                                                  _uuid.uuid4().hex, state.get('regulations'))
            scan = _best_use_scan_prices(draft, regulation_data, data, progress)
            state['priceScan'] = best_use_workflow.make_artifact(project, 'priceScan', scan,
                                                                _uuid.uuid4().hex, state.get('priceScan'))
            state.pop('selectedConceptId', None)
            state.pop('selectedConceptVersion', None)
            best_use_workflow.invalidate(state, ('landDistribution', 'floorDistribution'))
            stage, name, system = 'concepts', 'concepts', best_use_explore.CONCEPT_PROMPT
        else:
            regulation_data = _best_use_verify_regulations(draft)
            stage = data['stage']
            name = 'landDistribution' if stage == 'land' else 'floorDistribution'
            system = best_use_explore.LAND_PROMPT if stage == 'land' else best_use_explore.FLOOR_PROMPT
        prompt = json.dumps(best_use_explore.context(project, stage), ensure_ascii=False)
        chat = best_use_contract.read_object(project.get('best_use_explore_chat'))
        history = chat.get(stage) if isinstance(chat.get(stage), list) else []
        if kind == 'chat':
            message = best_use_contract.text(data.get('message'), 4000)
            if not message:
                return {'success': False, 'error_code': 'MESSAGE_REQUIRED'}, 400
            system += (' أجب مباشرة بلغة الرسالة. المخرج {"reply":"","proposal":null} للتفسير فقط. '
                       'إذا revise=true أعد {"reply":"","proposal":{التوزيع الكامل}} دون تطبيق في الحاسبة.')
            prompt += '\n' + json.dumps({'currentDistribution': state.get(name), 'history': history[-20:],
                                        'message': message, 'revise': data.get('revise') is True}, ensure_ascii=False)
        feedback, parsed, normalized = '', None, None
        for attempt in range(3):
            progress(stage, {'index': attempt + 1, 'total': 3})
            map_references = _best_use_map_references(draft)
            vision = bool(map_references)
            response = call_text_chat(system, prompt + feedback, max_tokens=10000 if targets else 2500,
                                      timeout=100,
                                      reasoning_effort='low' if (vision or kind != 'chat') else TEXT_REASONING_EFFORT,
                                      response_format={'type': 'json_object'},
                                      image_references=map_references,
                                      model=VISION_MODEL if vision else (GEMINI_TEXT_MODEL if kind == 'chat' else SLIDE_TEXT_MODEL),
                                      usage_ctx=_usage_ctx('best_use_explore_' + stage, data, draft_id=draft['id']))
            try:
                parsed = _best_use_explore_provider(response)
                artifact_id = _uuid.uuid4().hex
                if kind == 'concepts':
                    normalized = best_use_explore.concepts(parsed, project, regulation_data, scan, artifact_id)
                elif targets:
                    raw = parsed.get('proposal') if kind == 'chat' else parsed
                    concept = best_use_workflow.selected_concept(project)
                    normalized = best_use_explore.distribution(raw, project, regulation_data, artifact_id,
                        stage=stage, land=state.get('landDistribution'), allowed_uses=concept['uses'])
                    if not normalized['rationale'] or not normalized['setbackExplanation']:
                        raise best_use_contract.ProposalError('شرح التوزيع أو الارتدادات غير مكتمل.')
                    normalized['revenuePotential'] = best_use_prices.revenue_potential(normalized['components'], state['priceScan'])
                if kind == 'chat' and not best_use_contract.text(parsed.get('reply')):
                    raise best_use_contract.ProposalError('إجابة الشات غير متوفرة.')
                break
            except best_use_contract.ProposalError as error:
                if attempt == 2:
                    raise
                feedback = '\nالنتيجة رُفضت: ' + str(error) + '\nأعد JSON كاملًا مع تصحيح هذه المخالفة دون تغيير حدود المدخلات.'
        if targets:
            state[name] = best_use_workflow.make_artifact(project, name, normalized, artifact_id, state.get(name))
            if name == 'landDistribution':
                best_use_workflow.invalidate(state, ('floorDistribution',))
            state.update(sourceSnapshot=best_use_workflow.source_snapshot(project), sourceHash=best_use_workflow.source_hash(project))
        if kind == 'chat':
            chat[stage] = (history + [{'role': 'user', 'content': message},
                                     {'role': 'assistant', 'content': best_use_contract.text(parsed['reply'], 16000)}])[-100:]
            project['best_use_explore_chat'] = chat
        project['best_use_explore_data'] = state
        statuses = dict(draft.get('section_statuses') or {})
        if targets:
            statuses[best_use.SECTION_KEY] = 'draft'
        progress('saving')
        return _best_use_explore_store(draft, project, statuses, 'توليد محتوى الاستكشاف' if targets else 'مناقشة توزيع الاستكشاف')
    except best_use_contract.ProposalError as error:
        code = ('BEST_USE_SEARCH_FAILED' if str(error).startswith('price_') else
                'BEST_USE_EVIDENCE_REQUIRED' if str(error).startswith('regulatory_') or str(error).startswith('land_development_')
                else 'BEST_USE_INVALID_PROPOSAL')
        return _best_use_error(code, 422, validation=str(error))
    except Exception as error:
        fatal = _ai_fatal_http_response(error)
        if fatal is not None:
            response = app.make_response(fatal)
            return response.get_json(), response.status_code
        app.logger.warning('Best Use exploration failed: %s', type(error).__name__)
        return _best_use_error('BEST_USE_PROVIDER_FAILED', 503)


def _best_use_explore_worker(flask_app, actor, data, kind, job_id):
    tenant_id = actor['tenant_id']
    try:
        with flask_app.test_request_context('/api/best-use/explore/' + kind, method='POST', json=data):
            for key, value in actor.items():
                setattr(g, key, value)
            g.tenant = db.get_tenant_by_id(tenant_id)
            if g.user_id:
                g.user_permissions = db.get_user_permissions(g.user_id, g.user_role)
            draft, error = _best_use_explore_draft(data)
            if error is not None:
                response = flask_app.make_response(error)
                result, status = response.get_json(), response.status_code
            elif not _landloom_can('create_presentation'):
                result, status = {'success': False, 'error_code': 'SECTION_FORBIDDEN'}, 403
            else:
                readiness = _best_use_explore_readiness(draft)
                result, status = readiness if readiness else _best_use_explore_execute(draft, data, kind, (tenant_id, job_id))
            _write_job(_BEST_USE_JOB_NAMESPACE, tenant_id, job_id, {'status': 'completed' if status < 400 else 'failed',
                'flow': 'explore', 'draftId': data['draftId'], 'result': result, 'httpStatus': status})
    except Exception:
        app.logger.exception('Best Use exploration job failed')
        result, status = _best_use_error('BEST_USE_PROVIDER_FAILED', 503)
        _write_job(_BEST_USE_JOB_NAMESPACE, tenant_id, job_id, {'status': 'failed', 'flow': 'explore',
            'draftId': data['draftId'], 'result': result, 'httpStatus': status})


def _best_use_explore_start(kind):
    data = request.get_json(silent=True) or {}
    draft, error = _best_use_explore_draft(data)
    if error is not None:
        return error
    readiness = _best_use_explore_readiness(draft)
    if readiness:
        result, status = readiness
        return jsonify(result), status
    stage_error = _best_use_explore_stage_error(draft.get('draft_data') or {}, kind, data)
    if stage_error:
        result, status = stage_error
        return jsonify(result), status
    if kind == 'chat' and not best_use_contract.text(data.get('message')):
        return jsonify({'success': False, 'error_code': 'MESSAGE_REQUIRED'}), 400
    project = draft.get('draft_data') or {}
    targets = _best_use_explore_targets(kind, data)
    if ((draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved' and targets) or any(
            best_use_workflow.approved(project, name) for name in targets):
        result, status = _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
        return jsonify(result), status
    guard = _require_billing_balance('ai_text')
    if guard is not None:
        return guard
    data = dict(data, expectedRevision=draft.get('revision'))
    if not current_app.config.get('TESTING') or data.get('background') is True:
        job_id = _uuid.uuid4().hex
        actor = {key: getattr(g, key, None) for key in ('tenant_id', 'user_id', 'user_name', 'user_role', 'is_admin')}
        _write_job(_BEST_USE_JOB_NAMESPACE, g.tenant_id, job_id, {'status': 'queued', 'flow': 'explore',
            'draftId': draft['id']})
        threading.Thread(target=_best_use_explore_worker,
            args=(current_app._get_current_object(), actor, data, kind, job_id), daemon=True).start()
        return jsonify({'success': True, 'jobId': job_id, 'status': 'queued'}), 202
    result, status = _best_use_explore_execute(draft, data, kind)
    return jsonify(result), status


@app.route('/api/best-use/explore/concepts', methods=['POST'])
@require_permission('create_presentation')
def api_best_use_explore_concepts():
    return _best_use_explore_start('concepts')


@app.route('/api/best-use/explore/generate', methods=['POST'])
@require_permission('create_presentation')
def api_best_use_explore_generate():
    return _best_use_explore_start('generate')


@app.route('/api/best-use/explore/chat', methods=['POST'])
@require_permission('create_presentation')
def api_best_use_explore_chat():
    return _best_use_explore_start('chat')


@app.route('/api/best-use/explore/jobs/<job_id>', methods=['GET'])
@require_permission('create_presentation')
def api_best_use_explore_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', job_id):
        return jsonify({'success': False, 'error_code': 'JOB_NOT_FOUND'}), 404
    job = _read_job(_BEST_USE_JOB_NAMESPACE, g.tenant_id, job_id)
    if not job or job.get('flow') != 'explore':
        return jsonify({'success': False, 'error_code': 'JOB_NOT_FOUND'}), 404
    draft, error = _best_use_explore_draft({'draftId': job.get('draftId')})
    if error is not None:
        return error
    if job.get('status') in {'completed', 'failed'}:
        return jsonify(dict(job.get('result') or {}, status=job['status'], jobId=job_id)), job.get('httpStatus', 200)
    if time.time() - float(job.get('updatedAt') or 0) > 300:
        result, status = _best_use_error('BEST_USE_JOB_INTERRUPTED', 503)
        return jsonify(result), status
    return jsonify({'success': True, 'status': job.get('status') or 'running', 'jobId': job_id,
                    'step': job.get('step') or 'regulations',
                    'detail': job.get('detail')})


@app.route('/api/best-use/explore/concepts/select', methods=['POST'])
@require_permission('create_presentation')
def api_best_use_explore_select():
    data = request.get_json(silent=True) or {}
    draft, error = _best_use_explore_draft(data)
    if error is not None:
        return error
    if (draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved':
        result, status = _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
        return jsonify(result), status
    project = copy.deepcopy(draft.get('draft_data') or {})
    artifact = (project.get('best_use_explore_data') or {}).get('concepts') or {}
    if data.get('artifactId') != artifact.get('id') or data.get('contentHash') != artifact.get('contentHash'):
        result, status = _best_use_error('BEST_USE_ARTIFACT_CHANGED', 409)
        return jsonify(result), status
    try:
        best_use_workflow.select_concept(project, data.get('conceptId'))
    except best_use_contract.ProposalError as error:
        result, status = _best_use_error('BEST_USE_STAGE_REQUIRED', 409, validation=str(error))
        return jsonify(result), status
    statuses = dict(draft.get('section_statuses') or {}, **{best_use.SECTION_KEY: 'draft'})
    result, status = _best_use_explore_store(draft, project, statuses, 'اختيار مفهوم الاستكشاف')
    return jsonify(result), status


@app.route('/api/best-use/explore/decision', methods=['POST'])
@require_permission('create_presentation')
def api_best_use_explore_decision():
    data = request.get_json(silent=True) or {}
    if (not isinstance(data, dict) or not isinstance(data.get('decision'), str)
            or data['decision'] not in {'approved', 'unapproved', 'rejected'}
            or not isinstance(data.get('artifact'), str) or data['artifact'] not in best_use_workflow.ARTIFACTS):
        return jsonify({'success': False, 'error_code': 'BEST_USE_DECISION_REQUIRED'}), 400
    name, decision = data['artifact'], data['decision']
    applied = name == 'floorDistribution' and decision == 'approved'
    draft, error = _best_use_explore_draft(data, applying=applied)
    if error is not None:
        return error
    project = copy.deepcopy(draft.get('draft_data') or {})
    state = best_use_contract.read_object(project.get('best_use_explore_data'))
    artifact = state.get(name) or {}
    if (not artifact.get('id') or data.get('artifactId') != artifact['id']
            or data.get('contentHash') != artifact.get('contentHash') or data.get('inputHash') != artifact.get('inputHash')):
        result, status = _best_use_error('BEST_USE_ARTIFACT_CHANGED', 409)
        return jsonify(result), status
    if (draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved':
        result, status = _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
        return jsonify(result), status
    statuses = dict(draft.get('section_statuses') or {}, **{best_use.SECTION_KEY: 'draft'})
    if decision == 'approved':
        readiness = _best_use_explore_readiness(draft)
        if readiness:
            result, status = readiness
            return jsonify(result), status
        if not best_use_workflow.current(project, name):
            result, status = _best_use_error('BEST_USE_INPUTS_CHANGED', 409)
            return jsonify(result), status
        try:
            _best_use_verify_regulations(draft)
        except best_use_contract.ProposalError as error:
            result, status = _best_use_error('BEST_USE_EVIDENCE_REQUIRED', 409, validation=str(error))
            return jsonify(result), status
        if best_use_workflow.approved(project, name):
            return jsonify(_best_use_explore_response(draft))
        artifact.update(approved=True, rejected=False, approvedAt=db._utcnow().isoformat(),
            approvedBy=_project_draft_actor_id(), approvedContentHash=artifact['contentHash'], approvedInputHash=artifact['inputHash'])
        state[name] = artifact
        project['best_use_explore_data'] = state
        if applied:
            project = best_use_contract.apply_proposal(project, artifact, state_key='best_use_explore_applied')
            state['appliedFloorId'] = artifact['id']
            state['unlinkedRevenueRows'] = project.pop('best_use_explore_applied')['unlinkedRevenueRows']
            project['best_use_explore_data'] = state
            statuses['section-financial-calc'] = 'draft'
            if 'section-executive-content' in statuses:
                statuses['section-executive-content'] = 'draft'
    else:
        artifact.update(approved=False, rejected=decision == 'rejected')
        for key in ('approvedAt', 'approvedBy', 'approvedContentHash', 'approvedInputHash'):
            artifact.pop(key, None)
        state[name] = artifact
        if decision == 'rejected':
            best_use_workflow.invalidate(state, [key for key in best_use_workflow.ARTIFACTS
                                                if name in best_use_workflow.DEPENDENCIES[key]])
        project['best_use_explore_data'] = state
    result, status = _best_use_explore_store(draft, project, statuses, 'قرار محتوى الاستكشاف', applied)
    return jsonify(result), status
