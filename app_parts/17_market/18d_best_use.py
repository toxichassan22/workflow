import best_use


db.BASE_SECTION_KEYS.add(best_use.SECTION_KEY)
slide_engine.PROMPT_SKIPPED_KEYS.update({'best_use_data', 'best_use_chat'})
_BEST_USE_JOB_NAMESPACE = '.best_use_jobs'
_BEST_USE_SOURCE_SECTIONS = ('basic', 'land_croquis', 'location', 'section-market-study',
                             'section-financial-calc', best_use.SECTION_KEY)
_BEST_USE_ERRORS = {
    'BEST_USE_APPROVAL_REQUIRED': 'اقتراح أفضل استخدامات غير معتمد.',
    'BEST_USE_INPUTS_CHANGED': 'تغيّرت بيانات الأرض أو الموقع أو دراسة السوق التي بُني عليها الاقتراح.',
    'BEST_USE_APPROVAL_LOCKED': 'اقتراح أفضل استخدامات معتمد ومقفل للتعديل.',
    'BEST_USE_PREREQUISITES_REQUIRED': 'بيانات أو اعتمادات أفضل استخدامات غير مكتملة.',
    'BEST_USE_PROPOSAL_CHANGED': 'الاقتراح غير متوفر أو تغيّر منذ آخر قراءة.',
    'BEST_USE_INVALID_PROPOSAL': 'التوزيع المولد غير مكتمل أو يتجاوز الحدود المعتمدة.',
    'BEST_USE_PROVIDER_FAILED': 'تعذر إعداد اقتراح أفضل استخدامات أو الحصول على إجابة.',
    'BEST_USE_JOB_INTERRUPTED': 'توقفت معالجة أفضل استخدامات قبل اكتمالها.',
}


def _best_use_error(code, status=400, **extra):
    return {'success': False, 'error': _BEST_USE_ERRORS.get(code, code), 'error_code': code, **extra}, status


def _best_use_hidden_sections(denied):
    denied = set(denied)
    if denied.intersection({'basic', 'land_croquis', 'location', 'section-market-study', 'section-financial-calc'}):
        denied.add(best_use.SECTION_KEY)
    return denied


def _best_use_section_error(draft, section_key):
    if section_key != best_use.SECTION_KEY:
        return None
    project = (draft or {}).get('draft_data') or {}
    if not _best_use_required(project):
        return None
    if _best_use_active_mode(project) == 'explore':
        code = best_use_workflow.section_error(project)
        return _best_use_error(code)[0] if code else None
    proposal = best_use.read_object(project.get('best_use_data'))
    code = None
    if not best_use.proposal_current(project, proposal):
        code = 'BEST_USE_INPUTS_CHANGED'
    elif not best_use.proposal_approved(project, proposal):
        code = 'BEST_USE_APPROVAL_REQUIRED'
    return _best_use_error(code)[0] if code else None


def _generated_section_error(draft, section_key):
    return _financial_parking_section_error(draft, section_key) or _best_use_section_error(draft, section_key)


def _sanitize_best_use_claims(project, stored):
    _best_use_sanitize_explore(project, stored)
    for key in ('best_use_data', 'best_use_chat'):
        if key in (stored or {}):
            project[key] = copy.deepcopy(stored[key])
        else:
            project.pop(key, None)
    proposal = best_use.read_object(project.get('best_use_data'))
    if proposal.get('id'):
        if best_use.proposal_current(project, proposal):
            proposal.pop('inputsChanged', None)
        else:
            proposal.update(approved=False, inputsChanged=True)
            for key in ('approvedAt', 'approvedBy', 'approvedContentHash', 'approvedInputHash'):
                proposal.pop(key, None)
        project['best_use_data'] = proposal


def _best_use_save_statuses(project, incoming, stored):
    statuses = dict(incoming if isinstance(incoming, dict) else stored or {})
    if not _best_use_required(project):
        statuses.pop(best_use.SECTION_KEY, None)
    elif _best_use_section_error({'draft_data': project}, best_use.SECTION_KEY):
        statuses[best_use.SECTION_KEY] = 'draft'
    return statuses


def _best_use_field_matches(stored, incoming):
    """Posted fields are normalized (JSON strings decoded, numbers as numbers)
    while drafts store raw input values — a shape-only difference is not an
    edit, and writing it would falsely stale approved section snapshots."""
    if stored == incoming:
        return True
    if isinstance(stored, str) and isinstance(incoming, (dict, list)):
        try:
            return json.loads(stored) == incoming
        except (TypeError, ValueError):
            return False
    if isinstance(incoming, str) and isinstance(stored, (dict, list)):
        try:
            return stored == json.loads(incoming)
        except (TypeError, ValueError):
            return False
    if isinstance(stored, str) != isinstance(incoming, str) or (
            isinstance(stored, float) != isinstance(incoming, float)):
        try:
            return float(stored) == float(incoming)
        except (TypeError, ValueError):
            return str(stored or '') == str(incoming or '')
    return False


def _best_use_merge_fields(draft, data, source_fields):
    # The request carries the fields this flow consumes instead of a
    # pre-request draft save, so only these keys overlay the stored draft —
    # unrelated pending edits elsewhere in the form are never swept in.
    fields = data.get('fields')
    project = draft.get('draft_data') if isinstance(draft, dict) else None
    if not isinstance(fields, dict) or not isinstance(project, dict):
        return
    for key in source_fields:
        if key != 'draftId' and key in fields \
                and not _best_use_field_matches(project.get(key), fields[key]):
            project[key] = fields[key]
    maps = fields.get('maps')
    if isinstance(maps, dict):
        creative = best_use.read_object(project.get('tenantCreativeImages'))
        placeholders = best_use.read_object(creative.get('map_placeholders'))
        for token in best_use.MAP_TOKENS:
            value = best_use.text(maps.get(token), 2000)
            if value:
                placeholders[token] = value
            else:
                placeholders.pop(token, None)
        creative['map_placeholders'] = placeholders
        project['tenantCreativeImages'] = creative


def _best_use_draft(data, applying=False):
    draft_id = data.get('draftId')
    if not isinstance(draft_id, str) or not draft_id or len(draft_id) > 120:
        return None, (jsonify({'success': False, 'error': 'معرّف المسودة غير متوفر.',
                               'error_code': 'DRAFT_ID_REQUIRED'}), 400)
    required = _BEST_USE_SOURCE_SECTIONS + (('section-financial-calc',) if applying else ())
    if any(_section_key_forbidden(key) for key in required):
        return None, (jsonify({'success': False, 'error': 'قسم غير متاح لهذا المستخدم',
                               'error_code': 'SECTION_FORBIDDEN'}), 403)
    draft, error = _versioned_draft_or_404(draft_id)
    if error:
        return None, (jsonify({'success': False, **error}), 404)
    if _best_use_active_mode(draft.get('draft_data')) != 'guided':
        result, status = _best_use_error('BEST_USE_WRONG_MODE', 409)
        return None, (jsonify(result), status)
    status = db.normalize_proposal_status(draft.get('status'))
    if db.proposal_status_is_locked(status):
        return None, _draft_locked_response(status)
    expected = data.get('expectedRevision')
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int)
                                 or expected != draft.get('revision')):
        return None, (jsonify({'success': False, 'error': 'المسودة تغيّرت منذ آخر قراءة.',
                               'error_code': 'DRAFT_REVISION_CONFLICT',
                               'currentRevision': draft.get('revision')}), 409)
    _best_use_merge_fields(draft, data, best_use.SOURCE_FIELDS)
    return draft, None


def _best_use_documents_backed(draft):
    project = draft.get('draft_data') or {}
    ids = best_use.decoded(project.get('land_documents_files_file_ids'), [])
    if not isinstance(ids, list) or not ids:
        return False
    for file_id in ids:
        if not isinstance(file_id, str):
            return False
        record = db.get_project_file(g.tenant_id, file_id)
        if not record or record.get('file_type') not in {'land_document', 'croquis'}:
            return False
        if record.get('draft_id') and str(record['draft_id']) != str(draft['id']):
            return False
    return True


def _section_gate_states(draft, section_keys):
    """Version-readiness per gated section, named for the client.

    Only failure states land in the map: ``not_approved`` splits into
    ``pending`` (the newest version still awaits a decision) and
    ``unapproved``, so the message can say what is actually missing instead of
    a bare «اعتماد» that looks identical to a never-approved section.
    """
    overview = db.section_versions_overview(g.tenant_id, (draft or {}).get('id'))
    section_map = _draft_field_section_map(g.tenant_id)
    states = {}
    for key in section_keys:
        state, meta = _section_version_readiness(draft, key, section_map, overview=overview)
        if state not in {'not_approved', 'stale', 'expired'}:
            continue
        states[key] = ('pending' if (meta or {}).get('status') == 'pending' else 'unapproved') \
            if state == 'not_approved' else state
    return states


def _section_gate_statuses(draft, section_keys):
    """Stored flat statuses for the gated keys — lets the caller's badges
    resync against server truth when a gate refuses the action."""
    stored = (draft or {}).get('section_statuses') or {}
    return {key: stored[key] for key in section_keys if stored.get(key)}


def _best_use_readiness(draft):
    project = draft.get('draft_data') or {}
    missing = best_use.missing_inputs(project, draft.get('section_statuses') or {})
    if not _best_use_documents_backed(draft) and 'croquis' not in missing:
        missing.append('croquis')
    gated = ('land_croquis', 'location', 'section-market-study')
    states = _section_gate_states(draft, gated)
    for key in states:
        if key not in missing:
            missing.append(key)
    if not missing:
        return None
    return _best_use_error('BEST_USE_PREREQUISITES_REQUIRED', missing=missing,
                           sectionStatuses=_section_gate_statuses(draft, gated), sectionStates=states)


def _best_use_map_references(draft):
    rows = db.get_map_images(g.tenant_id, draft_id=draft['id'])
    references = []
    for view in ('overview', 'access', 'catchment', 'landmarks'):
        token = '##MAP_' + view.upper()
        record = next((row for row in rows if row.get('placeholder') == token + '##'), None)
        if record is None:
            record = next((row for row in rows
                           if str(row.get('placeholder') or '').startswith(token + '_')
                           and not str(row.get('placeholder')).endswith('_EDITABLE##')), None)
        if not record or not record.get('file_path'):
            continue
        path = os.path.abspath(record['file_path'])
        try:
            if os.path.commonpath([os.path.abspath(UPLOADS_DIR), path]) != os.path.abspath(UPLOADS_DIR):
                continue
        except ValueError:
            continue
        reference = '/uploads/' + os.path.relpath(path, UPLOADS_DIR).replace(os.sep, '/')
        prepared = _prepare_image_reference_for_model(reference, tenant_id=g.tenant_id)
        if prepared:
            references.append({'data_uri': prepared})
    return references


def _best_use_response(draft, components_applied=False):
    project = draft.get('draft_data') or {}
    statuses = draft.get('section_statuses') or {}
    result = {'success': True, 'draftId': draft['id'], 'revision': draft.get('revision'),
              'bestUse': best_use.read_object(project.get('best_use_data')),
              'chat': best_use.read_object(project.get('best_use_chat')),
              'componentsApplied': components_applied,
              'sectionStatuses': {key: statuses[key] for key in
                                  (best_use.SECTION_KEY, 'section-financial-calc', 'section-executive-content',
                                   'land_croquis', 'location', 'section-market-study')
                                  if key in statuses}}
    if components_applied:
        result['financialModel'] = best_use.read_object(project.get('financial_study_model'))
        result['projectComponentsData'] = project.get('project_components_data') or '[]'
        result['financialCalcData'] = project.get('financial_calc_data') or '{}'
    return result


def _best_use_store(draft, project, statuses, action, components_applied=False):
    try:
        db.save_project_draft(g.tenant_id, draft.get('user_id') or _project_draft_actor_id(),
                              project, statuses, draft_id=draft['id'],
                              expected_revision=draft.get('revision'), existing_row=draft)
    except db.DraftRevisionConflict as conflict:
        return {'success': False, 'error': 'المسودة تغيّرت أثناء معالجة أفضل استخدامات.',
                'error_code': 'DRAFT_REVISION_CONFLICT', 'currentRevision': conflict.current_revision}, 409
    except db.DraftLocked as locked:
        response = app.make_response(_draft_locked_response(locked.status))
        return response.get_json(), response.status_code
    try:
        # The request fields were just persisted: a gated section whose content
        # drifted from its approved snapshot can no longer stand as approved.
        _void_stale_section_approvals(
            g.tenant_id, draft['id'], project, statuses=statuses)
    except Exception:
        pass
    saved = db.get_project_draft_by_id(g.tenant_id, draft['id'])
    labels = {'generate': 'توليد اقتراح أفضل استخدامات', 'revise': 'تعديل اقتراح أفضل استخدامات بالشات',
              'chat': 'مناقشة توزيع أفضل استخدامات', 'approved': 'اعتماد توزيع أفضل استخدامات واستبدال المكونات',
              'rejected': 'رفض توزيع أفضل استخدامات دون تغيير المكونات', 'unapproved': 'إلغاء اعتماد توزيع أفضل استخدامات'}
    _record_change('draft', draft['id'], labels[action], [labels[action]],
                   source='ai' if action in {'generate', 'revise', 'chat'} else 'manual')
    if action in {'generate', 'revise', 'chat'}:
        _bill_tenant_unbilled_usage_async(g.tenant_id)
    return _best_use_response(saved, components_applied), 200


def _best_use_provider_result(response):
    result = openrouter_response_message(response, 'BEST-USE')
    if result.get('finish_reason') not in (None, 'stop', 'end_turn'):
        raise best_use.ProposalError('استجابة التوزيع غير مكتملة.')
    parsed = parse_json_object(result.get('content'))
    if not isinstance(parsed, dict):
        raise best_use.ProposalError('استجابة التوزيع ليست بيانات صالحة.')
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            return _land_chat_clean_reply(slide_engine._strip_presentation_icons(value))
        return value
    return clean(parsed)


def _best_use_execute(draft, data, kind, job=None):
    project = copy.deepcopy(draft.get('draft_data') or {})
    proposal = best_use.read_object(project.get('best_use_data'))
    revise = kind == 'chat' and data.get('revise') is True
    if (kind == 'generate' or revise) and (proposal.get('approved') is True
            or (draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved'):
        return _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
    message = best_use.text(data.get('message'), 4000)
    if kind == 'chat' and not message:
        return {'success': False, 'error': 'الرسالة غير متوفرة.', 'error_code': 'MESSAGE_REQUIRED'}, 400
    context = best_use.prompt_context(project)
    price_scan = _best_use_guided_prices(project) if kind == 'generate' or revise else proposal.get('priceScan') or {}
    context['priceEvidence'] = price_scan
    evidence = _land_chat_regulation_evidence(message or 'الاستخدامات والتغطية والارتدادات ومعامل مسطح البناء', project)
    chat = best_use.read_object(project.get('best_use_chat'))
    history = chat.get('messages') if isinstance(chat.get('messages'), list) else []
    prompt = 'بيانات المشروع المعتمدة:\n' + json.dumps(context, ensure_ascii=False)
    if evidence:
        prompt += '\n\nنصوص موثقة من ملفات الأمانة:\n' + evidence
    if kind == 'chat':
        prompt_proposal = {key: proposal[key] for key in
                           ('title', 'rationale', 'setbackExplanation', 'components', 'totals') if key in proposal}
        prompt += '\n\nالتوزيع الحالي:\n' + json.dumps(prompt_proposal, ensure_ascii=False)
        prior = [{'role': 'user' if turn.get('role') == 'user' else 'assistant',
                  'content': best_use.text(turn.get('content'), 4000)}
                 for turn in history[-20:] if isinstance(turn, dict)]
        prompt += '\n\nالمحادثة السابقة:\n' + json.dumps(prior, ensure_ascii=False)
        prompt += '\n\nrevise=' + ('true' if revise else 'false') + '\nرسالة العميل: ' + message
    system = best_use.CHAT_PROMPT if kind == 'chat' else best_use.SYSTEM_PROMPT
    map_references = _best_use_map_references(draft)
    feedback, last_output = '', None
    prior_version = proposal.get('version')
    generation_version = prior_version + 1 if isinstance(prior_version, int) and not isinstance(prior_version, bool) else 1
    for attempt in range(4):
        try:
            response = call_text_chat(system, prompt + feedback,
                                      max_tokens=8000 if kind == 'generate' or revise else 3000,
                                      timeout=120, reasoning_effort='low', response_format={'type': 'json_object'},
                                      image_references=map_references,
                                      model=GEMINI_TEXT_MODEL if kind == 'chat' else SLIDE_TEXT_MODEL,
                                      usage_ctx=_usage_ctx('best_use', data, draft_id=draft['id']))
            parsed = _best_use_provider_result(response)
            raw = parsed.get('proposal') if revise else parsed
            last_output = raw if isinstance(raw, dict) else parsed
            if kind == 'generate' or revise:
                proposal = best_use.normalize_proposal(raw, project, _uuid.uuid4().hex, version=generation_version)
                proposal['generatedAt'] = db._utcnow().isoformat()
                proposal['priceScan'] = price_scan
                proposal['revenuePotential'] = best_use_prices.revenue_potential(proposal['components'], price_scan)
                proposal['contentHash'] = best_use.proposal_content_hash(proposal)
                project['best_use_data'] = proposal
                if kind == 'generate':
                    project['best_use_chat'] = {'messages': []}
            if kind == 'chat':
                reply = _land_chat_clean_reply(best_use.text(parsed.get('reply'), 16000))
                reply = re.sub(r'\s*[(（]?\s*revise\s*=\s*(?:true|false)\s*[)）]?', '', reply, flags=re.I).strip()
                if not reply:
                    raise best_use.ProposalError('إجابة الشات غير متوفرة.')
                project['best_use_chat'] = {'messages': (history + [
                    {'role': 'user', 'content': message}, {'role': 'assistant', 'content': reply}])[-100:]}
            break
        except best_use.ProposalError as error:
            if attempt == 3:
                return _best_use_error('BEST_USE_INVALID_PROPOSAL', 422, validation=str(error))
            rejected = json.dumps(last_output, ensure_ascii=False)[:8000] if isinstance(last_output, dict) else ''
            feedback = ('\n\nالرد السابق رُفض: ' + best_use.text(str(error), 400) + '.'
                        + ('\nالرد المرفوض:\n' + rejected if rejected else '')
                        + '\nأخرج الرد كاملًا مرة أخرى بنفس عقد JSON مع تصحيح المخالفة فقط '
                          'دون كسر أي قيد آخر ضمن الحدود المعتمدة.')
            if job:
                _write_job(_BEST_USE_JOB_NAMESPACE, job[0], job[1], {
                    'status': 'running', 'progress': 30 + attempt * 15, 'draftId': data['draftId']})
        except Exception as error:
            fatal = _ai_fatal_http_response(error)
            if fatal is not None:
                response = app.make_response(fatal)
                return response.get_json(), response.status_code
            app.logger.warning('Best Use provider failed: %s', type(error).__name__)
            return _best_use_error('BEST_USE_PROVIDER_FAILED', 503)
    statuses = dict(draft.get('section_statuses') or {})
    if kind == 'generate' or revise:
        statuses[best_use.SECTION_KEY] = 'draft'
    return _best_use_store(draft, project, statuses, 'revise' if revise else kind)


def _best_use_job_worker(flask_app, actor, data, kind, job_id):
    tenant_id = actor['tenant_id']
    try:
        with flask_app.test_request_context('/api/best-use/' + kind, method='POST', json=data):
            for key, value in actor.items():
                setattr(g, key, value)
            g.tenant = db.get_tenant_by_id(tenant_id)
            if g.user_id:
                g.user_permissions = db.get_user_permissions(g.user_id, g.user_role)
            _write_job(_BEST_USE_JOB_NAMESPACE, tenant_id, job_id, {'status': 'running', 'progress': 20,
                                                                  'draftId': data['draftId']})
            draft, error = _best_use_draft(data)
            if error is not None:
                refusal = flask_app.make_response(error)
                result, status = refusal.get_json(), refusal.status_code
            elif not _landloom_can('create_presentation'):
                result, status = {'success': False, 'error': 'قسم غير متاح لهذا المستخدم',
                                  'error_code': 'SECTION_FORBIDDEN'}, 403
            else:
                readiness = _best_use_readiness(draft)
                result, status = readiness if readiness else _best_use_execute(draft, data, kind,
                                                                               job=(tenant_id, job_id))
            _write_job(_BEST_USE_JOB_NAMESPACE, tenant_id, job_id, {
                'status': 'completed' if status < 400 else 'failed', 'progress': 100,
                'draftId': data['draftId'], 'result': result, 'httpStatus': status})
    except Exception:
        app.logger.exception('Best Use job failed')
        result, status = _best_use_error('BEST_USE_PROVIDER_FAILED', 503)
        _write_job(_BEST_USE_JOB_NAMESPACE, tenant_id, job_id, {
            'status': 'failed', 'progress': 100, 'draftId': data['draftId'], 'result': result, 'httpStatus': status})


def _best_use_start(kind):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error_code': 'INVALID_REQUEST'}), 400
    draft, error = _best_use_draft(data)
    if error is not None:
        return error
    readiness = _best_use_readiness(draft)
    if readiness:
        result, status = readiness
        return jsonify(result), status
    proposal = best_use.read_object((draft.get('draft_data') or {}).get('best_use_data'))
    if (kind == 'generate' or data.get('revise') is True) and (proposal.get('approved') is True
            or (draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved'):
        result, status = _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
        return jsonify(result), status
    if kind == 'chat' and not best_use.text(data.get('message'), 4000):
        return jsonify({'success': False, 'error': 'الرسالة غير متوفرة.', 'error_code': 'MESSAGE_REQUIRED'}), 400
    guard = _require_billing_balance('ai_text')
    if guard is not None:
        return guard
    data = {**data, 'expectedRevision': draft.get('revision')}
    if not current_app.config.get('TESTING') or data.get('background') is True:
        job_id = _uuid.uuid4().hex
        actor = {key: getattr(g, key, None) for key in ('tenant_id', 'user_id', 'user_name', 'user_role', 'is_admin')}
        _write_job(_BEST_USE_JOB_NAMESPACE, g.tenant_id, job_id, {
            'status': 'queued', 'progress': 5, 'draftId': draft['id'], 'actor': actor,
            'payload': {'draftId': draft['id'], 'expectedRevision': draft.get('revision'),
                        'message': data.get('message'), 'revise': data.get('revise') is True, 'kind': kind}})
        threading.Thread(target=_best_use_job_worker,
                         args=(current_app._get_current_object(), actor, data, kind, job_id), daemon=True).start()
        return jsonify({'success': True, 'jobId': job_id, 'status': 'queued', 'progress': 5}), 202
    result, status = _best_use_execute(draft, data, kind)
    return jsonify(result), status


@app.route('/api/best-use/generate', methods=['POST'])
@require_permission('create_presentation')
def api_generate_best_use():
    return _best_use_start('generate')


@app.route('/api/best-use/chat', methods=['POST'])
@require_permission('create_presentation')
def api_chat_best_use():
    return _best_use_start('chat')


@app.route('/api/best-use/jobs/<job_id>', methods=['GET'])
@require_permission('create_presentation')
def api_best_use_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', job_id):
        return jsonify({'success': False, 'error_code': 'JOB_NOT_FOUND'}), 404
    job = _read_job(_BEST_USE_JOB_NAMESPACE, g.tenant_id, job_id)
    if not job:
        return jsonify({'success': False, 'error_code': 'JOB_NOT_FOUND'}), 404
    draft, error = _best_use_draft({'draftId': job.get('draftId')})
    if error is not None:
        return error
    if job.get('status') in {'completed', 'failed'}:
        return jsonify({**(job.get('result') or {}), 'status': job['status'], 'jobId': job_id}), job.get('httpStatus', 200)
    if time.time() - float(job.get('updatedAt') or 0) > 300:
        result, status = _best_use_error('BEST_USE_JOB_INTERRUPTED', 503)
        return jsonify(result), status
    return jsonify({'success': True, 'status': job.get('status') or 'running', 'jobId': job_id,
                    'progress': job.get('progress') or 10})


@app.route('/api/best-use/decision', methods=['POST'])
@require_permission('create_presentation')
def api_decide_best_use():
    data = request.get_json(silent=True) or {}
    if (not isinstance(data, dict) or not isinstance(data.get('decision'), str)
            or data['decision'] not in {'approved', 'rejected', 'unapproved'}):
        return jsonify({'success': False, 'error': 'قرار الاقتراح غير صالح.', 'error_code': 'BEST_USE_DECISION_REQUIRED'}), 400
    decision = data['decision']
    draft, error = _best_use_draft(data, applying=decision == 'approved')
    if error is not None:
        return error
    project = copy.deepcopy(draft.get('draft_data') or {})
    proposal = best_use.read_object(project.get('best_use_data'))
    if not proposal.get('id') or data.get('proposalId') != proposal['id']:
        result, status = _best_use_error('BEST_USE_PROPOSAL_CHANGED', 409)
        return jsonify(result), status
    if (draft.get('section_statuses') or {}).get(best_use.SECTION_KEY) == 'approved':
        result, status = _best_use_error('BEST_USE_APPROVAL_LOCKED', 409)
        return jsonify(result), status
    statuses = dict(draft.get('section_statuses') or {})
    if decision == 'approved':
        if not best_use.proposal_current(project, proposal):
            result, status = _best_use_error('BEST_USE_INPUTS_CHANGED', 409)
            return jsonify(result), status
        readiness = _best_use_readiness(draft)
        if readiness:
            result, status = readiness
            return jsonify(result), status
        if proposal.get('approved') is True:
            return jsonify(_best_use_response(draft))
        if proposal.get('priceScan') and not best_use_prices.evidence_current(proposal['priceScan']):
            result, status = _best_use_error('BEST_USE_INPUTS_CHANGED', 409)
            return jsonify(result), status
        validated = best_use.normalize_proposal(proposal, project, proposal['id'],
                                                version=proposal['version'])
        proposal.update(validated, approved=True, rejected=False, approvedBy=_project_draft_actor_id(),
                        approvedAt=db._utcnow().isoformat())
        if proposal.get('priceScan'):
            proposal['revenuePotential'] = best_use_prices.revenue_potential(
                proposal['components'], proposal['priceScan'])
        proposal['contentHash'] = best_use.proposal_content_hash(proposal)
        proposal['approvedContentHash'] = proposal['contentHash']
        proposal['approvedInputHash'] = proposal['inputHash']
        project = best_use.apply_proposal(project, proposal)
        statuses['section-financial-calc'] = 'draft'
        if 'section-executive-content' in statuses:
            statuses['section-executive-content'] = 'draft'
        statuses[best_use.SECTION_KEY] = 'draft'
    else:
        proposal.update(approved=False, rejected=decision == 'rejected')
        proposal.pop('approvedAt', None)
        proposal.pop('approvedBy', None)
        project['best_use_data'] = proposal
        if decision == 'rejected':
            statuses.pop(best_use.SECTION_KEY, None)
        else:
            statuses[best_use.SECTION_KEY] = 'draft'
    result, status = _best_use_store(draft, project, statuses, decision, components_applied=decision == 'approved')
    return jsonify(result), status
