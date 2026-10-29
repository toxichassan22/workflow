
@app.route('/api/market-study/catalog', methods=['GET'])
@require_auth
def api_market_study_catalog():
    return jsonify({'success': True, 'catalog': market_study.catalog_payload()})


@app.route('/api/market-study/competitors', methods=['POST'])
@require_permission('create_presentation')
def api_market_study_competitors():
    return _start_market_job('competitors', _execute_market_competitors)


@app.route('/api/market-study/summary', methods=['POST'])
@require_permission('create_presentation')
def api_market_study_summary():
    return _start_market_job('summary', _execute_market_summary)


@app.route('/api/market-study/competitors/logo', methods=['POST'])
@require_permission('create_presentation')
def api_market_study_competitor_logo():
    data = request.json or {}
    competitor = market_study.normalize_competitor_row(
        data.get('competitor') or {}, fallback_source='manual',
        offer_lang=slide_engine.resolve_offer_lang(data))
    if not competitor:
        return jsonify({'success': False, 'error': 'بيانات المنافس غير صالحة'}), 400
    if competitor.get('logo_file_id') or competitor.get('logo_path'):
        return jsonify({'success': True, 'competitor': competitor})
    official_url = competitor.get('logo_source_url') or competitor.get('source_url')
    # Only a page retrieval already proved counts as the official source; a
    # source label or a name inside the host is not proof, so the discovery
    # call runs and its citations must confirm the official host.
    verified_official = bool(official_url and competitor.get('logo_official_verified'))
    if not verified_official:
        _billing_guard = _require_billing_balance('ai_text')
        if _billing_guard is not None:
            return _billing_guard
        discovery_prompt = (
            f'ابحث عن الموقع الرسمي وشعار «{competitor["name"]}». '
            'أعد JSON فقط بالمفاتيح official_url وlogo_url وlogo_source_url. '
            'official_url صفحة HTTPS من الموقع الرسمي للمشروع أو المطور، '
            'logo_url رابط HTTPS مباشر لصورة PNG أو JPG أو WEBP من الموقع الرسمي أو نطاق الصور التابع له، '
            'وlogo_source_url الصفحة الرسمية التي تثبت الشعار. إذا لم تجد دليلًا رسميًا أعد القيم فارغة.'
        )
        response = _browse_agent_call(
            market_study.build_consultant_system_prompt(), discovery_prompt,
            _usage_ctx('market', data),
            search_provider='searxng',
            search_budget=3, max_steps=8, max_tokens=1600,
            reasoning_effort=TEXT_REASONING_EFFORT)
        provider_error = _chat_error_message(response) if response.get('error') else ''
        parsed, parse_error = _parse_market_model_json(response)
        discovered_official = str(parsed.get('official_url') or parsed.get('logo_source_url') or '').strip()
        citations = _market_citation_urls(response)
        cited_official = bool(discovered_official and any(
            _related_official_hosts(discovered_official, citation) for citation in citations))
        if parse_error or not cited_official:
            return jsonify({'success': False, 'error': provider_error or 'لم يُعثر على موقع رسمي موثق'}), 404
        official_url = discovered_official
        competitor['logo_url'] = str(parsed.get('logo_url') or '').strip()
        competitor['logo_source_url'] = str(parsed.get('logo_source_url') or official_url).strip()
        competitor['logo_official_verified'] = True
    else:
        competitor['logo_official_verified'] = True
    if not competitor.get('logo_url'):
        prompt = (
            f'ابحث داخل الموقع الرسمي فقط عن شعار «{competitor["name"]}»: {official_url}. '
            'أعد JSON فقط بالمفتاحين logo_url وlogo_source_url. '
            'logo_url رابط HTTPS مباشر لصورة PNG أو JPG أو WEBP على النطاق الرسمي أو نطاق الصور التابع له، '
            'وlogo_source_url صفحة الموقع الرسمي. إذا لم تجده أعد القيمتين فارغتين.'
        )
        response = _browse_agent_call(
            market_study.build_consultant_system_prompt(), prompt,
            _usage_ctx('market', data),
            search_provider='searxng',
            search_budget=2, max_steps=6, max_tokens=1200,
            reasoning_effort=TEXT_REASONING_EFFORT)
        provider_error = _chat_error_message(response) if response.get('error') else ''
        parsed, parse_error = _parse_market_model_json(response)
        if parse_error:
            return jsonify({'success': False, 'error': provider_error or 'لم يُعثر على شعار رسمي'}), 404
        competitor['logo_url'] = str(parsed.get('logo_url') or '').strip()
        competitor['logo_source_url'] = str(parsed.get('logo_source_url') or official_url).strip()
    logo_source_url = competitor.get('logo_source_url') or official_url
    if logo_source_url:
        field_sources = market_study.competitor_field_sources(competitor)
        field_sources['logo_url'] = [logo_source_url]
        competitor['field_sources'] = field_sources
        competitor['source_urls'] = list(dict.fromkeys(
            market_study.competitor_source_urls(competitor) + [logo_source_url]))
    competitor = _store_imported_competitor_logo(
        competitor, draft_id=data.get('draftId') or data.get('draft_id'))
    if not competitor.get('logo_file_id'):
        return jsonify({'success': False, 'error': competitor.get('logo_import_warning') or 'لم يُعثر على شعار رسمي'}), 404
    draft_id = data.get('draftId') or data.get('draft_id')
    if draft_id:
        _record_change('draft', draft_id, 'استيراد شعار منافس',
                       [f'استُورد شعار «{competitor.get("name")}» من الموقع الرسمي'], source='ai')
    return jsonify({'success': True, 'competitor': competitor})


@app.route('/api/market-study/jobs/<job_id>', methods=['GET'])
@require_auth
def api_market_study_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_market_job(g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'error': 'مهمة دراسة السوق غير موجودة',
            'failureReason': 'job_not_found',
        }), 404
    public_job = _public_job(job, job_id, g.tenant_id)
    public_job['jobId'] = job_id
    if str(job.get('kind') or '') == 'summary':
        public_job['researchTraceUrl'] = f'/api/market-study/jobs/{job_id}/trace'
    return jsonify(public_job)


@app.route('/api/market-study/jobs/<job_id>/trace', methods=['GET'])
@require_auth
def api_market_study_research_trace(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_market_job(g.tenant_id, job_id)
    if not job or str(job.get('kind') or '') != 'summary':
        return jsonify({
            'success': False,
            'error': 'سجل بحث دراسة السوق غير موجود',
            'failureReason': 'job_not_found',
        }), 404
    trace_path = _market_research_trace_path(g.tenant_id, job_id)
    if not os.path.isfile(trace_path):
        return jsonify({
            'success': False,
            'error': 'لم يبدأ سجل البحث بعد',
            'failureReason': 'trace_not_started',
        }), 404
    return send_file(
        trace_path, mimetype='application/x-ndjson', as_attachment=True,
        download_name=f'market-research-{job_id}.jsonl', conditional=True)


@app.route('/api/market-study/jobs/<job_id>/resume', methods=['POST'])
@require_permission('create_presentation')
def api_resume_market_study_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    with _MARKET_JOB_RESUME_LOCK:
        job = _read_market_job(g.tenant_id, job_id)
        if not job:
            return jsonify({
                'success': False, 'error': 'مهمة دراسة السوق غير موجودة',
                'failureReason': 'job_not_found',
            }), 404
        if not _market_job_can_resume(job):
            return jsonify({
                'success': False,
                'error': 'هذه المهمة غير متاحة للاستكمال',
                'failureReason': 'job_not_resumable',
            }), 409
        stored_payload = job.get('payload') if isinstance(job.get('payload'), dict) else {}
        data = stored_payload.get('data') if isinstance(stored_payload.get('data'), dict) else {}
        actor = job.get('actor') if isinstance(job.get('actor'), dict) else {
            'user_id': getattr(g, 'user_id', None),
            'user_name': getattr(g, 'user_name', None),
            'user_role': getattr(g, 'user_role', None),
        }
        resumable = {key: job[key] for key in ('payload', 'actor', 'resumeState')
                     if key in job}
        _write_market_job(g.tenant_id, job_id, {
            **resumable,
            'status': 'queued', 'success': True, 'kind': 'summary',
            'resumed': True,
            'message': 'استُؤنفت دراسة السوق من آخر مرحلة محفوظة',
        })
    threading.Thread(
        target=_market_job_worker,
        args=(current_app._get_current_object(), g.tenant_id,
              'summary', data, job_id),
        kwargs={'actor': actor}, daemon=True,
    ).start()
    return jsonify({
        'success': True, 'jobId': job_id, 'status': 'queued',
        'kind': 'summary', 'resumed': True,
        'message': 'استُؤنفت دراسة السوق من آخر مرحلة محفوظة',
    }), 202
