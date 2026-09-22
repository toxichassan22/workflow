

def _prepare_market_payload(data):
    payload = dict(data or {})
    radius_value = payload.get('competitorRadius') or payload.get('competitor_radius') or '10'
    custom_km = payload.get('competitorRadiusCustomKm') or payload.get('competitor_radius_custom_km')
    resolved = market_study.resolve_competitor_radius_km(radius_value, custom_km)
    payload['resolvedRadiusKm'] = resolved
    payload['competitorRadiusLabel'] = _market_radius_label(payload, resolved)
    payload['dataPeriodLabel'] = _market_period_label(payload)
    payload['dataPeriodBounds'] = market_study.data_period_bounds(
        payload.get('dataPeriod') or payload.get('data_period'),
        payload.get('dataPeriodFrom') or payload.get('data_period_from'),
        payload.get('dataPeriodTo') or payload.get('data_period_to'),
    )
    mixed = payload.get('projectComponents') or payload.get('project_mixed_components') or payload.get('project_components')
    payload['projectComponents'] = mixed
    return payload


def _execute_market_competitors(data, tenant_id=None, progress=None):
    report = progress if callable(progress) else (lambda *_args: None)
    payload = _prepare_market_payload(data)
    existing = data.get('competitors') if isinstance(data.get('competitors'), list) else []
    mode = 'fill' if str(data.get('mode') or '').strip() == 'fill' else 'generate'
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    system_prompt = market_study.build_consultant_system_prompt()
    training_context = db.get_training_context(tenant_id, surface='content') if tenant_id else ''
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    user_prompt = market_study.build_competitors_user_prompt(payload, existing, mode=mode)
    report(18, 'جاري البحث في الويب عن المنافسين وبياناتهم — قد يستغرق دقائق...')
    # The reasoning budget counts against max_tokens on this model — a tight cap
    # truncates the competitors array mid-generation and returns a thin table.
    res, provider_error = _call_market_study_model(
        system_prompt, user_prompt, max_tokens=14000, max_search_results=14,
        usage_ctx=_usage_ctx('market', data, tenant_id=tenant_id),
        search_context={'city': payload.get('city'), 'country': 'SA'})
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        reason = 'insufficient_credit' if 'afford' in (provider_error or '').lower() else parse_error
        return {
            'success': False,
            'error': 'تعذر توليد المنافسين.',
            'failureReason': reason,
            'providerError': provider_error,
        }
    # Every grounded call's retrieved pages are evidence — collect them across
    # the main call and all expansion rounds instead of keeping only the
    # richest single answer, so later rounds keep feeding verification/logos.
    citation_pages = []
    citation_urls = []
    _seen_citation_urls = set()

    def _collect_citations(response):
        for page in _market_citation_pages(response):
            if page['url'] not in _seen_citation_urls:
                _seen_citation_urls.add(page['url'])
                citation_pages.append(page)
                citation_urls.append(page['url'])

    _collect_citations(res)
    generated = parsed.get('competitors') if isinstance(parsed.get('competitors'), list) else []
    dropped_far = []
    try:
        _radius_limit = float(payload.get('resolvedRadiusKm') or 0)
    except (TypeError, ValueError):
        _radius_limit = 0
    # Flagging keeps borderline rows for review, but a competitor hundreds of
    # kilometres away is noise, not a choice — drop it before counting, so a
    # list padded with far cities still triggers the expansion pass. Whole-city
    # scope has no km bound, yet a row claiming another region is still noise:
    # cap it at 100 km.
    cutoff = (max(_radius_limit * 3, 60) if _radius_limit > 0
              else (100 if payload.get('resolvedRadiusKm') is None else 0))
    if cutoff:
        generated = [row for row in generated if isinstance(row, dict)]
        _kept = []
        for row in generated:
            distance = market_study._number_in_text(row.get('distance_km'))
            if distance is not None and distance > cutoff:
                dropped_far.append(str(row.get('name') or '').strip())
                continue
            _kept.append(row)
        generated = _kept
    named_generated = [row for row in generated
                       if isinstance(row, dict) and str(row.get('name') or '').strip()]
    # Expansion passes: a thin list usually means the model settled for the
    # first pages it saw. Each pass takes a different angle — the web plugin
    # derives fresh queries from the prompt — so later rounds surface projects
    # the generic first query missed. Stop at the minimum or when a pass
    # answers cleanly yet adds nothing.
    _scope = market_study.competitor_scope_text(payload)
    _ptype = str(payload.get('projectType') or payload.get('project_type') or 'عقاري')
    _city = str(payload.get('city') or '')
    _district = str(payload.get('district') or '')
    expansion_angles = [
        f'قوائم وأخبار أفضل المشاريع العقارية في {_city} قرب {_district or "موقع المشروع"}',
        f'مشاريع عقارية مسماة (كمبوند، برج، مجمع، مخطط، وجهة سكنية) في أحياء {_city} المجاورة لـ {_district or "موقع المشروع"}',
        f'مشاريع كبار المطورين العقاريين في {_city} — قائمة أو تحت الإنشاء',
    ]
    seen_names = {market_study._fold_choice(row.get('name')) for row in named_generated}
    round_no = 0
    while (mode != 'fill' and _market_search_ran(res)
           and len(named_generated) < market_study.COMPETITOR_MIN_DIRECT
           and round_no < len(expansion_angles)):
        report(24 + round_no,
               f'عدد المنافسين أقل من الحد الأدنى — بحث إضافي ({round_no + 1}) عن مشاريع مسماة أخرى...')
        known = '، '.join(str(row.get('name') or '') for row in named_generated) or 'لا يوجد'
        expansion_prompt = (
            f'نُجري دراسة سوق لمشروع {_ptype} في {_city}'
            + (f' — {_district}' if _district else '')
            + f'. نطاق المنافسين: {_scope}.\n'
            + f'المنافسون المسجلون حتى الآن: {known}.\n'
            + f'ابحث في الويب عن: {expansion_angles[round_no]} — مشاريع مسماة '
              'حقيقية لم ترد في القائمة. يجوز إدراج مشاريع أبعد قليلًا مع '
              'distance_km الحقيقية، ولا تُدرج صفحات مؤشرات أو إحصاءات كمنافس.\n'
              'أعد JSON فقط: {"competitors":[{"name":"","district":"","distance_km":"",'
              '"operation_type":"","price_type":"","price":"","source_urls":[]}]} '
              'مع بقية الحقول المعتادة عند توفرها.')
        res2, _err2 = _call_market_study_model(
            system_prompt, expansion_prompt, max_tokens=14000, max_search_results=20,
            usage_ctx=_usage_ctx('market', data, tenant_id=tenant_id),
            search_context={'city': payload.get('city'), 'country': 'SA'})
        provider_error = provider_error or _err2
        _collect_citations(res2)
        parsed2, _parse_err2 = _parse_market_model_json(res2)
        more = parsed2.get('competitors') if isinstance(parsed2, dict) else []
        added_this_round = 0
        if isinstance(more, list):
            for row in more:
                if not isinstance(row, dict):
                    continue
                key = market_study._fold_choice(row.get('name'))
                if not key or key in seen_names:
                    continue
                distance = market_study._number_in_text(row.get('distance_km'))
                if cutoff and distance is not None and distance > cutoff:
                    dropped_far.append(str(row.get('name') or '').strip())
                    continue
                seen_names.add(key)
                generated.append(row)
                named_generated.append(row)
                added_this_round += 1
        round_no += 1
        if not added_this_round and not _parse_err2:
            # A clean response with no new rows means retrieval is exhausted;
            # a malformed/empty response is a technical miss — try the next angle.
            break
    merged, added, updated = market_study.merge_generated_competitors(existing, generated, mode=mode)
    market_study.apply_search_citations(merged, citation_urls)
    _attach_retrieved_citations(merged, citation_pages)
    report(30, 'التحقق من كل منافس ببحث مستقل في الويب...')
    _verify_competitor_rows(merged, payload, data, tenant_id=tenant_id, progress=report)
    for row in merged:
        market_study.canonicalize_competitor_source_urls(row)
        _drop_foreign_competitor_urls(row)
    report(62, 'التحقق من روابط المصادر واحدًا واحدًا...')
    search_ran = _market_search_ran(res) or bool(citation_urls)
    if search_ran:
        # A grounded run that still leaves a row with zero source URLs means the
        # name came from the model's memory — flag it for the owner's review.
        for row in merged:
            if (row.get('row_source') or 'ai') == 'ai' and not market_study.competitor_source_urls(row):
                row['no_search_evidence'] = True
    if search_ran:
        dead_urls = _verify_market_urls(
            url for row in merged for url in _competitor_claimed_urls(row))
        for row in merged:
            _flag_dead_competitor_urls(row, dead_urls)
    else:
        # The model answered from memory: keep the links visible for review,
        # flagged — the owner accepts or rejects each one.
        for row in merged:
            if (row.get('row_source') or 'ai') == 'ai':
                market_study.flag_unverified_competitor_sources(row)
    out_of_radius = market_study.flag_out_of_radius(merged, payload.get('resolvedRadiusKm'))
    report(74, 'استيراد شعارات المنافسين من مواقعها الرسمية...')
    _auto_import_competitor_logos(
        merged, payload, data, tenant_id=tenant_id, progress=report,
        citation_pages=citation_pages)
    report(93, 'إعداد جدول المصادر والتحذيرات...')
    sources = market_study.competitor_source_rows(merged)
    market_study.flag_out_of_period_sources(sources, payload.get('dataPeriodBounds'))
    notes = str(parsed.get('notes') or '').strip()
    if dropped_far:
        far_note = 'أُسقطت من الجدول مشاريع بعيدة جدًا عن النطاق: ' + '، '.join(dropped_far)
        notes = f'{notes} — {far_note}' if notes else far_note
    expansion_note = str(parsed.get('expansionNote') or parsed.get('notes') or '').strip()
    if round_no:
        rounds_note = ('أُجريت جولة بحث إضافية واحدة عن مشاريع أخرى' if round_no == 1
                       else f'أُجريت {round_no} جولات بحث إضافية عن مشاريع أخرى')
        expansion_note = f'{expansion_note} — {rounds_note}' if expansion_note else rounds_note
    no_evidence = sum(1 for row in merged if row.get('no_search_evidence'))
    search_not_run = sum(1 for row in merged if row.get('verify_state') == 'search_not_run')
    missing_prices = sum(
        1 for row in merged
        if str(row.get('name') or '').strip()
        and not any(str(row.get(key) or '').strip()
                    for key in ('price_value', 'price_from', 'price_to')))
    # The table is a partial answer — not a clean success — whenever the search
    # layer failed to ground rows or fill their prices, or the provider
    # reported an error we recovered from. The owner must see that instead of
    # a silent «تم» over an unsourced, unpriced table.
    partial = bool(provider_error) or not search_ran or no_evidence > 0 or missing_prices > 0
    if not provider_error:
        # The main call can succeed while every per-competitor verify hits a
        # deterministic refusal (e.g. the tenant-key gate). Surface the row
        # error at job level so the UI shows the real reason, not just counts.
        verify_errors = [str(row.get('verify_provider_error') or '').strip()
                         for row in merged if row.get('verify_provider_error')]
        verify_errors = [err for err in verify_errors if err and err != 'empty_response']
        if verify_errors:
            provider_error = verify_errors[0]
    return {
        'success': True,
        'competitors': merged,
        'sources': sources,
        'added': added,
        'updated': updated,
        'searchVerified': search_ran,
        'partial': partial,
        'providerError': provider_error or None,
        'outOfRadiusCount': out_of_radius,
        'noEvidenceCount': no_evidence,
        'searchNotRunCount': search_not_run,
        'missingPriceCount': missing_prices,
        'conflictWarnings': [warning for row in merged for warning in (row.get('conflict_warnings') or [])],
        'searchExpanded': bool(parsed.get('searchExpanded')) or round_no > 0,
        'expansionNote': expansion_note,
        'notes': notes,
    }


def _execute_market_summary(data, tenant_id=None, progress=None):
    report = progress if callable(progress) else (lambda *_args: None)
    payload = _prepare_market_payload(data)
    competitors = data.get('competitors') if isinstance(data.get('competitors'), list) else []
    raw_current = data.get('currentSummary')
    current_summary = raw_current if isinstance(raw_current, (dict, str)) else None
    current_sources = data.get('currentSources') if isinstance(data.get('currentSources'), list) else None
    current_swot = data.get('currentSwot') if isinstance(data.get('currentSwot'), dict) else None
    offer_lang = slide_engine.resolve_offer_lang(data)
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    system_prompt = market_study.build_consultant_system_prompt(offer_lang=offer_lang)
    training_context = db.get_training_context(tenant_id, surface='content') if tenant_id else ''
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    user_prompt = market_study.build_summary_user_prompt(
        payload, competitors, current_summary, current_sources=current_sources, current_swot=current_swot,
        offer_lang=offer_lang,
    )
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
        user_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    report(18, 'جاري تحليل السوق والمنافسين بالبحث في الويب — قد يستغرق دقائق...')
    res, provider_error = _call_market_study_model(
        system_prompt, user_prompt, max_tokens=MARKET_STUDY_MAX_TOKENS,
        usage_ctx=_usage_ctx('market', data, tenant_id=tenant_id),
        search_context={'city': payload.get('city'), 'country': 'SA'})
    report(72, 'التحقق من مصادر الملخص وفترة بياناتها...')
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        reason = 'insufficient_credit' if 'afford' in (provider_error or '').lower() else parse_error
        return {
            'success': False,
            'error': 'تعذر توليد ملخص السوق. لم يُستبدل النص الحالي.',
            'failureReason': reason,
            'providerError': provider_error,
        }
    normalized = market_study.normalize_summary(parsed)
    if not market_study.summary_has_content(normalized.get('summary')):
        return {
            'success': False,
            'error': 'عاد النموذج ملخصًا فارغًا. لم يُستبدل النص الحالي.',
            'failureReason': 'empty_response',
            'providerError': provider_error,
        }
    search_verified = _market_search_ran(res)
    market_study.apply_search_citations(normalized.get('sources'), _market_citation_urls(res), url_key='url')
    sources = normalized.get('sources') or []
    if search_verified:
        dead_urls = _verify_market_urls(
            row.get('url') for row in sources if isinstance(row, dict))
        for row in sources:
            url = str(row.get('url') or '').strip()
            if url and url in dead_urls:
                row['dead_url'] = url
                row['note'] = (str(row.get('note') or '').strip() + ' — ' if row.get('note') else '') + 'الرابط لم يعد يعمل'
    else:
        # Memory answers keep their links — flagged unverified so the owner
        # can inspect the claimed origin instead of losing the trail.
        for row in sources:
            if str(row.get('url') or '').strip():
                row['sources_unverified'] = True
            marker = 'رابط غير موثق — لم يصل من نتائج البحث'
            note = str(row.get('note') or '').strip()
            if marker not in note:
                row['note'] = f'{note} — {marker}' if note else marker
    market_study.flag_out_of_period_sources(sources, payload.get('dataPeriodBounds'))
    return {
        'success': True,
        'searchVerified': search_verified,
        **normalized,
    }


def _market_job_worker(app, tenant_id, kind, data, job_id, actor=None):
    with app.app_context():
        # ISS-033: helpers that read the caller identity from g (upload dir,
        # logo publish, audit) must see this job's tenant — an app context
        # starts empty, so the worker stamps it the way require_auth would.
        g.tenant_id = tenant_id
        if isinstance(actor, dict):
            g.user_id = actor.get('user_id')
            g.user_name = actor.get('user_name')
            g.user_role = actor.get('user_role')
        _write_market_job(tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري البحث في المصادر الرسمية وإعداد النتائج...',
            'kind': kind,
            'progress': 8,
        })

        def report(pct, message):
            try:
                pct_value = max(0, min(99, int(pct)))
            except (TypeError, ValueError):
                pct_value = 0
            _write_market_job(tenant_id, job_id, {
                'status': 'running',
                'success': True,
                'kind': kind,
                'progress': pct_value,
                'message': str(message or '').strip() or 'جاري إعداد دراسة السوق...',
            })

        try:
            if kind == 'competitors':
                payload = _execute_market_competitors(data, tenant_id, progress=report)
            else:
                payload = _execute_market_summary(data, tenant_id, progress=report)
            status = 'completed' if payload.get('success') else 'failed'
            _write_market_job(tenant_id, job_id, {
                **payload,
                'status': status,
                'kind': kind,
                'progress': 100,
                'message': payload.get('error') or 'اكتملت دراسة السوق',
            })
        except Exception as exc:
            _write_market_job(tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'kind': kind,
                'error': f'حدث خطأ في دراسة السوق: {exc}',
                'failureReason': 'job_failed',
            })


def _start_market_job(kind, executor):
    data = request.json or {}
    _billing_guard = _require_billing_balance(
        'market_competitors' if kind == 'competitors' else 'market_summary')
    if _billing_guard is not None:
        return _billing_guard
    use_background = (not current_app.config.get('TESTING')) or bool(data.get('background'))
    if not use_background:
        result = executor(data)
        status = 200 if result.get('success') else 422
        return jsonify(result), status
    job_id = str(_uuid.uuid4())
    tenant_id = g.tenant_id
    _write_market_job(tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'kind': kind,
        'message': 'تم استلام طلب دراسة السوق',
        'payload': {'kind': kind, 'data': data},
        'actor': {
            'user_id': getattr(g, 'user_id', None),
            'user_name': getattr(g, 'user_name', None),
            'user_role': getattr(g, 'user_role', None),
        },
    })
    threading.Thread(
        target=_market_job_worker,
        args=(current_app._get_current_object(), tenant_id, kind, data, job_id),
        kwargs={'actor': {
            'user_id': getattr(g, 'user_id', None),
            'user_name': getattr(g, 'user_name', None),
            'user_role': getattr(g, 'user_role', None),
        }},
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'kind': kind,
        'message': 'بدأت دراسة السوق في الخلفية',
    }), 202


@app.route('/api/executive-content/generate', methods=['POST'])
@require_permission('create_presentation')
def api_generate_executive_content():
    """Rewrite one executive-content block from already collected project facts."""
    data = request.json or {}
    _billing_guard = _require_billing_balance('executive_content')
    if _billing_guard is not None:
        return _billing_guard
    key = str(data.get('block') or '').strip()
    spec = executive_content.block_spec(key)
    if not spec:
        return jsonify({'success': False, 'error': 'عنصر محتوى غير صالح'}), 400
    facts = data.get('facts') if isinstance(data.get('facts'), dict) else {}
    ready, missing = executive_content.block_ready(key, facts)
    if not ready:
        labels = {
            'basic': 'البيانات الأساسية',
            'location': 'الموقع',
            'land': 'الأرض والكروكي',
            'timeline': 'الجدول الزمني',
            'financial': 'الدراسة المالية',
            'market': 'دراسة السوق',
        }
        needed = ' و'.join(labels.get(name, name) for name in missing) or 'المدخلات المطلوبة'
        return jsonify({
            'success': False,
            'error': 'استكمل ' + needed + ' قبل توليد هذا النص',
            'missing': missing,
        }), 400
    current = data.get('currentText')
    offer_lang = slide_engine.resolve_offer_lang(facts)
    prompt = executive_content.build_user_prompt(key, facts, current, offer_lang=offer_lang)
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    cap = EXECUTIVE_SUMMARY_MAX_TOKENS if key in ('summary', 'risks') else EXECUTIVE_CONTENT_MAX_TOKENS
    system_prompt = executive_content.SYSTEM_PROMPT
    training_context = db.get_training_context(g.tenant_id, surface='content') or ''
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    raw = None
    last_error = None
    try:
        for attempt in range(3):
            try:
                response = call_zai_chat(
                    system_prompt, prompt, temperature=0.2,
                    max_tokens=cap,
                    reasoning_effort='low',
                    response_format={'type': 'json_object'},
                    usage_ctx=_usage_ctx('executive', data),
                )
                if isinstance(response, dict) and 'error' in response:
                    msg = _chat_error_message(response)
                    affordable = _AFFORDABLE_TOKENS_RE.search(msg)
                    if affordable:
                        retry_cap = max(8000, int(int(affordable.group(1)) * 0.85))
                        if retry_cap < cap:
                            print(f'[EXECUTIVE CONTENT] provider cap refused={cap}; retrying with {retry_cap}')
                            cap = retry_cap
                            continue
                    raise RuntimeError(msg)
                raw = _get_chat_response_text(response) or extract_chat_content(response, 'EXECUTIVE-CONTENT')
                break
            except Exception as primary_error:
                last_error = primary_error
                if not _has_any_openrouter_key(_usage_ctx('executive', data)):
                    raise
                print(f'[EXECUTIVE CONTENT PRIMARY ERROR] {primary_error}. Trying OpenRouter fallback...')
                fallback = call_openrouter_chat(
                    system_prompt,
                    prompt,
                    temperature=0.2,
                    max_tokens=cap,
                    model=LUNA_TEXT_MODEL,
                    reasoning_effort='low',
                    usage_ctx=_usage_ctx('executive', data),
                    response_format={'type': 'json_object'},
                )
                if isinstance(fallback, dict) and 'error' in fallback:
                    msg = _chat_error_message(fallback)
                    affordable = _AFFORDABLE_TOKENS_RE.search(msg)
                    if affordable:
                        retry_cap = max(8000, int(int(affordable.group(1)) * 0.85))
                        if retry_cap < cap:
                            print(f'[EXECUTIVE CONTENT] fallback cap refused={cap}; retrying with {retry_cap}')
                            cap = retry_cap
                            continue
                raw = _get_chat_response_text(fallback) or extract_chat_content(fallback, 'EXECUTIVE-CONTENT-FALLBACK')
                if raw:
                    break
        if not raw and last_error:
            raise last_error
        parsed = parse_json_object(raw) or {}
        text = executive_content.parse_generated_block(key, parsed)
        if not text and raw and isinstance(raw, str):
            cleaned_raw = executive_content.clean_raw_json_string(raw)
            cleaned_raw = re.sub(r'^```(?:json)?\s*', '', str(cleaned_raw).strip(), flags=re.MULTILINE)
            cleaned_raw = re.sub(r'\s*```$', '', cleaned_raw.strip(), flags=re.MULTILINE)
            text = executive_content.normalize_document(cleaned_raw) if spec.get('output') in ('document', 'risks') else executive_content.normalize_text(cleaned_raw)
        empty = not str(text or '').strip()
        if empty:
            return jsonify({'success': False, 'error': 'عاد النموذج نصًا فارغًا. لم يُستبدل النص الحالي.'}), 422
        return jsonify({'success': True, 'block': key, 'text': text})
    except Exception as error:
        print(f'[EXECUTIVE CONTENT AI ERROR] {error}')
        return jsonify({
            'success': False,
            'error': 'تعذر توليد المحتوى التنفيذي: ' + str(error),
        }), 503


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
    competitor = market_study.normalize_competitor_row(data.get('competitor') or {}, fallback_source='manual')
    if not competitor:
        return jsonify({'success': False, 'error': 'بيانات المنافس غير صالحة'}), 400
    if competitor.get('logo_file_id') or competitor.get('logo_path'):
        return jsonify({'success': True, 'competitor': competitor})
    official_url = competitor.get('logo_source_url') or competitor.get('source_url')
    verified_official = bool(official_url and market_study.official_source_reliability(
        competitor.get('name'), competitor.get('source'), official_url))
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
        response, provider_error = _call_market_study_model(
            market_study.build_consultant_system_prompt(), discovery_prompt, max_tokens=1600,
            usage_ctx=_usage_ctx('market', data))
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
        response, provider_error = _call_market_study_model(
            market_study.build_consultant_system_prompt(), prompt, max_tokens=1200,
            usage_ctx=_usage_ctx('market', data))
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
    return jsonify(_public_job(job))


def _land_job_dir(tenant_id):
    return _job_dir('.land_jobs', tenant_id)


def _land_job_path(tenant_id, job_id):
    return _job_path('.land_jobs', tenant_id, job_id)


def _write_land_job(tenant_id, job_id, payload):
    _write_job('.land_jobs', tenant_id, job_id, payload)


def _read_land_job(tenant_id, job_id):
    return _read_job('.land_jobs', tenant_id, job_id)


def _land_job_worker(app, tenant_id, data, job_id):
    """Run the long land extraction off the HTTP request so the hosting proxy cannot 404 it."""
    with app.app_context():
        _write_land_job(tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري تحليل المستندات والاشتراطات...',
        })
        try:
            with app.test_request_context('/api/extract-croquis', method='POST', json=data):
                g.tenant_id = tenant_id
                response = _execute_extract_croquis()
            http_status = getattr(response, 'status_code', 500)
            if isinstance(response, tuple):
                http_status = response[1] if len(response) > 1 else 200
                response = response[0]
            payload = response.get_json(silent=True) if response is not None else {}
            if not isinstance(payload, dict):
                payload = {}
            payload.pop('rawText', None)
            status = 'completed' if payload.get('success') else 'failed'
            _write_land_job(tenant_id, job_id, {
                **payload,
                'status': status,
                'httpStatus': http_status,
                'message': payload.get('error') or 'اكتمل التحليل',
            })
        except Exception as exc:
            _write_land_job(tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'error': f'حدث خطأ في قراءة ملف الكروكي: {exc}',
                'failureReason': 'job_failed',
            })


def _land_document_key(filename, provided=''):
    """Give each uploaded land document a stable kind for the prompt.

    The client tags every file 'land_document', so the filename carries the
    only real signal about whether the model is looking at the croquis, the
    building licence, or the deed — the identity matters because the source
    priority order references it.
    """
    lowered = str(filename or '').casefold()
    if any(token in lowered for token in ('رخصة', 'رخصه', 'licen', 'permit')):
        return 'building_license'
    if any(token in lowered for token in ('كروكي', 'croquis', 'krooki')):
        return 'croquis'
    if any(token in lowered for token in ('صك', 'deed')):
        return 'deed'
    return provided or 'land_document'


@app.route('/api/extract-croquis', methods=['POST'])
@require_permission('create_presentation')
def api_extract_croquis():
    """Accept a land-analysis request.

    The hosting proxy fabricates a 404 if this route stays open for the whole
    vision + regulation pipeline. Production therefore queues the work and
    returns immediately; the client polls GET /api/extract-croquis/<job_id>.
    Tests keep the original synchronous response unless they pass background=true.
    """
    data = request.json or {}
    _billing_guard = _require_billing_balance('croquis')
    if _billing_guard is not None:
        return _billing_guard
    use_background = (not current_app.config.get('TESTING')) or bool(data.get('background'))
    if not use_background:
        return _execute_extract_croquis()
    job_id = str(_uuid.uuid4())
    tenant_id = g.tenant_id
    _write_land_job(tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'message': 'تم استلام طلب التحليل',
        'payload': {'data': data},
    })
    threading.Thread(
        target=_land_job_worker,
        args=(current_app._get_current_object(), tenant_id, data, job_id),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'message': 'بدأ التحليل في الخلفية',
    }), 202


@app.route('/api/extract-croquis/<job_id>', methods=['GET'])
@require_auth
def api_extract_croquis_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_land_job(g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'error': 'مهمة التحليل غير موجودة',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(_public_job(job))


def _execute_extract_croquis():
    """Extract one or more land documents together using vision AI."""
    import traceback
    try:
        data = request.json or {}
        location_address = str(
            data.get('locationAddress') or data.get('location_address') or ''
        ).strip()
        try:
            location_lat = float(data.get('locationLat') or data.get('location_lat'))
            location_lng = float(data.get('locationLng') or data.get('location_lng'))
        except (TypeError, ValueError):
            location_lat = location_lng = None
        if (
            not location_address.startswith('http')
            or location_lat is None or location_lng is None
            or not (-90 <= location_lat <= 90)
            or not (-180 <= location_lng <= 180)
        ):
            return jsonify({
                'success': False,
                'error': 'رابط Google Maps صالح وإحداثيات الموقع مطلوبان قبل بدء تحليل الأرض والكروكي',
                'failureReason': 'location_required',
            }), 400
        legacy_file_data = data.get('fileData') or data.get('croquis_file') or ''
        if not data.get('documents') and not legacy_file_data:
            return jsonify({'success': False, 'error': 'يرجى رفع صورة الأرض أو الكروكي أو الرخصة أولاً'}), 400

        site_context, site_context_warnings = build_land_analysis_site_context(
            data, g.tenant_id, location_lat, location_lng)
        regulation_query = ' '.join(str(data.get(key) or '') for key in (
            'zoningCode', 'zoning_code', 'projectType', 'city', 'landUse'
        )).strip()
        project_context_fields = (
            ('اسم المشروع', 'projectName'),
            ('نوع المشروع', 'projectType'),
            ('مرحلة المشروع الحالية', 'projectStage'),
            ('رابط Google Maps', 'locationAddress'),
            ('خط العرض', 'locationLat'),
            ('خط الطول', 'locationLng'),
        )
        project_context_block = '\n'.join(
            f'- {label}: {str(data.get(key) or "").strip() or "غير مدخل"}'
            for label, key in project_context_fields
        ) + '\nبيانات الموقع والخرائط المحللة:\n' + json.dumps(
            site_context, ensure_ascii=False, indent=2, default=str)

        documents = []
        raw_documents = data.get('documents')
        if isinstance(raw_documents, list) and len(raw_documents) > 10:
            return jsonify({'success': False, 'error': 'الحد الأقصى لتحليل الملفات معًا هو 10 ملفات'}), 400
        if isinstance(raw_documents, list):
            for index, item in enumerate(raw_documents):
                if not isinstance(item, dict):
                    continue
                file_data = item.get('fileData') or item.get('data') or ''
                file_id = item.get('fileId')
                if not file_data and file_id:
                    stored = db.get_project_file(g.tenant_id, str(file_id))
                    if stored and stored.get('storage_path') and os.path.isfile(stored['storage_path']):
                        with open(stored['storage_path'], 'rb') as source:
                            encoded = base64.b64encode(source.read()).decode('ascii')
                        file_data = f"data:{stored.get('mime_type') or 'application/octet-stream'};base64,{encoded}"
                if not file_data:
                    continue
                filename = os.path.basename(str(item.get('filename') or item.get('originalName') or f'document_{index + 1}'))
                documents.append({
                    'key': _land_document_key(filename, str(item.get('key') or item.get('fileType') or '')),
                    'filename': filename,
                    'fileData': file_data,
                    'mimeType': item.get('mimeType') or ('application/pdf' if 'application/pdf' in file_data else 'image/*'),
                })
        if not documents:
            file_data = data.get('fileData') or data.get('croquis_file') or ''
            if file_data:
                documents = [{
                    'key': 'croquis',
                    'filename': 'croquis.pdf' if 'application/pdf' in file_data else 'croquis-image',
                    'fileData': file_data,
                    'mimeType': 'application/pdf' if 'application/pdf' in file_data else 'image/*',
                }]
        if not documents:
            return jsonify({'success': False, 'error': 'يرجى رفع صورة الأرض أو الكروكي أو الرخصة أولاً'}), 400

        system_prompt = (
            "أنت مهندس مساح وخبير عقاري ومدقق مستندات تنظيمية. حلل كل الملفات المرفقة معًا، مع الحفاظ على هوية كل ملف ومصدر كل معلومة.\n"
            "ملفا الاشتراطات الرسميان اشتراطات1 واشتراطات2 متاحان لك بمحتواهما الكامل؛ استخدمهما كاملين ولا تعتمد على جزء أو صفحات منتقاة فقط.\n"
            "أعد JSON فقط بدون Markdown. لا تخترع قيمة غير مقروءة؛ استخدم null أو نصًا فارغًا، وسجل التعارضات بدل اختيار قيمة من نفسك.\n"
            "أولوية المصادر إلزامية: جدول التنظيم الرسمي أولًا، ثم أي مرجع تنظيمي رسمي، ثم الكروكي، ثم رخصة البناء. إذا ظهرت جداول متعددة للإحداثيات أو الاتجاهات، استخدم جدول التنظيم واربط كل قيمة بـ source=regulation_table، وسجل البدائل والتعارضات في conflicts.\n"
            "ستجد في مستندات PDF صورة كاملة للصفحة وقصاصات مكبرة عالية الدقة، وقد توجد قصاصات بديلة باتجاه دوران آخر. استخدم النسخة التي يكون النص فيها أفقيًا واضحًا، ولا تعتبر النسخة المقلوبة مصدرًا مستقلًا.\n"
            "إذا وجدت أكثر من قطعة أرض، أعد كل قطعة داخل parcels منفصلة ولا تدمج مساحاتها أو حدودها.\n"
            "استخرج جدول الاتجاهات الأربعة بشكل مستقل من جدول الجهات أو الحدود الذي يوضح «بموجب التنظيم» أولًا، وليس من وصف عام في الرخصة أو الكروكي. اقرأ أسماء الشوارع وعروضها وأطوال الحدود والواجهات من صورة الجدول.\n"
            "بالنسبة للإحداثيات، إذا وجدت أكثر من جدول فافصل الجداول أولًا داخل coordinate_tables، وضع عنوان كل جدول في table_name وصفوفه في rows.\n"
            "الجدول المطلوب حصريًا هو الجدول الذي عنوانه «إحداثيات التنظيم» أو «جدول إحداثيات التنظيم» أو «احداثيات التنظيم». جدول «إحداثيات الموقع» أو «إحداثيات الصك» ليس بديلًا ولا يجوز أخذ أي صف منه.\n"
            "بعد فصل الجداول، انسخ صفوف جدول إحداثيات التنظيم وحده إلى regulation_coordinates ثم إلى survey_coordinates بنفس الترتيب. لا تخلط أو تنتقي صفوفًا من الجدولين.\n"
            "إذا لم تجد جدول إحداثيات التنظيم أو لم يكن عنوانه وصفوفه مقروءة بوضوح، أعد regulation_coordinates وsurvey_coordinates فارغين وسجل تعارضًا يوضح السبب، ولا تستنتج الإحداثيات من الحدود أو الاتجاهات.\n"
            "استخرج من جدول إحداثيات التنظيم كما هو: رقم القطعة، رقم النقطة، الشرقيات، الشماليات، بدون تحويل إلى latitude/longitude أو حساب أي نقطة.\n"
            "الصيغة المطلوبة:\n"
            "{\n"
            '  "parcels": [{\n'
            '    "parcel_id": "P-1", "plot_number": "", "plan_number": "", "subdivision_number": "",\n'
            '    "deed_number": "", "deed_date": "", "area_sqm": null,\n'
            '    "facades_count": null, "facades_directions": "",\n'
            '    "directions": {\n'
            '      "north": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"},\n'
            '      "south": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"},\n'
            '      "east": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"},\n'
            '      "west": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "setback": "", "source": "regulation_table"}\n'
            '    },\n'
            '    "north_direction": "", "setbacks": "", "building_ratio": "", "coverage_ratio": "",\n'
            '    "building_ratio_coverage": "", "floor_area_ratio": "", "table_floors": "", "max_floors_height": "",\n'
            '    "parking_requirements": "", "entrances_exits_requirements": "",\n'
            '    "allowed_uses": "", "regulatory_constraints": "",\n'
            '    "allowed_uses_restrictions": "", "zoning_code": "",\n'
            '    "coordinates": {"lat": null, "lng": null, "source": "", "confidence": ""},\n'
            '    "coordinates_table_name": "إحداثيات التنظيم", "coordinates_table_source_page": "",\n'
            '    "coordinate_tables": [{"table_name": "", "rows": [{"point": "", "eastings": "", "northings": "", "source": ""}]}],\n'
            '    "regulation_coordinates": [{"point": "", "eastings": "", "northings": "", "source": "regulation_table"}],\n'
            '    "survey_coordinates": [{"point": "", "eastings": "", "northings": "", "source": "regulation_table"}],\n'
            '    "confidence": {}, "sources": [], "summary": ""\n'
            '  }],\n'
            '  "coordinate_tables": [], "regulation_coordinates": [],\n'
            '  "survey_coordinates": [], "source_priority": ["regulation_table", "official_regulation", "croquis", "building_license"],\n'
            '  "conflicts": [{"field": "", "description": ""}],\n'
            '  "land_and_building_summary": ""\n'
            "}\n"
            "قواعد إلزامية لأرقام الهوية — لا تخلط بينها أبدًا:\n"
            "- plot_number: رقم قطعة الأرض وحده (مثل 9991). لا تضع فيه رقم المخطط ولا رقم القسم ولا كلمة (قطعة).\n"
            "- plan_number: رقم المخطط وحده (مثل 3/س/125).\n"
            "- subdivision_number: رقم القسم أو الجزء إن وُجد فقط، وإلا اتركه فارغًا. لا تضعه في plot_number.\n"
            "- إذا كان المستند يذكر رقمًا واحدًا فقط ولم يوضح نوعه، اتركه في الحقل المؤكد فقط وسجّل الغموض في conflicts.\n"
             "قواعد إلزامية للصك:\n"
             "- deed_number: رقم الصك رقميًا فقط.\n"
             "- deed_date: تاريخ إصدار الصك كما هو مكتوب (هجري أو ميلادي) بصيغة YYYY/MM/DD، وبيّن نوع التقويم في summary. لا تخلطه مع تاريخ الكروكي أو تاريخ الرخصة.\n"
             "قاعدة حاسمة لمساحة الأرض حسب الكروكي (area_sqm / croquis_land_area):\n"
             "- أخرج فقط المساحة المكتوبة في جدول التنظيم بجوار عبارة «بموجب التنظيم» لكل قطعة. هذه هي مساحة الأرض المعتمدة لهذا الحقل.\n"
             "- إذا وُجدت مساحات متعددة مثل مساحة الصك، أو المساحة المقاسة على الطبيعة، أو الرفع المساحي، أو مساحة حدود مختلفة، فلا تستخدم أيًا منها بدل مساحة «بموجب التنظيم».\n"
             "- استخدم مساحة «بموجب التنظيم» وحدها لاختيار شريحة جدول الاشتراطات، وسجّل أي مساحة أخرى في conflicts أو summary كمعلومة متعارضة فقط.\n"
             "- إذا لم تكن مساحة «بموجب التنظيم» مقروءة بوضوح، اترك area_sqm فارغًا وسجّل ذلك في conflicts، ولا تخمّن أو تحسب مساحة بديلة.\n"
             "قواعد إلزامية للواجهات — الواجهة هي الحد المطل على شارع فقط:\n"
            "- لكل قطعة أربعة حدود دائمًا، لكن الواجهات هي الحدود المطلة على شوارع وحدها. "
            "الحد المجاور لقطعة أو جار ليس واجهة.\n"
            "- facades_count: عدد الحدود المطلة على شوارع فقط، رقم صحيح (1 إلى 4). "
            "يُمنع منعًا تامًا كتابة أي كلمة اتجاه هنا.\n"
            "- facades_directions: اتجاهات تلك الواجهات فقط (مثل: شمالية، غربية). "
            "لا تكتب الاتجاهات الأربعة كلها إلا إذا كانت القطعة فعلًا مطلة على أربعة شوارع.\n"
            "- في directions املأ street_name و street_width_m للحدود المطلة على شوارع، "
            "واذكر في uses أن الحد يجاور قطعة/جار للحدود غير المطلة على شارع.\n"
            "- setback داخل كل اتجاه: الارتداد المخصص لذلك الاتجاه بالمتر. جدول الجهات والحدود في الكروكي أو الرخصة "
            "يحمل غالبًا عمود «الارتداد» لكل جهة — انسخ قيمته لكل اتجاه كما هي (مثل «5م»). وإذا وردت الارتدادات بصيغة "
            "أمامي/خلفي/جانبي، فالأمامي يخص جهة الواجهة على الشارع الرئيسي، والخلفي الجهة المقابلة لها، والجانبي "
            "الجهتين المتبقيتين؛ املأ الاتجاهات المقابلة بهذه القيم وسجّل في conflicts أن الربط استُنتج. "
            "لا تترك setback فارغًا إلا إذا لم يذكر أي مستند ارتدادًا لتلك الجهة.\n"
            "قواعد منع التكرار:\n"
            "- لا تكرر نفس المعلومة في أكثر من حقل. building_ratio_coverage لنسب البناء والتغطية وFAR والأدوار، وsetbacks للارتدادات فقط.\n"
            "- allowed_uses للاستخدامات، وregulatory_constraints للقيود فقط.\n"
            "- أطوال الحدود وأسماء الشوارع تُكتب داخل directions فقط، ولا تُعاد في summary كقائمة.\n"
            "قواعد الاشتراطات — ممنوع إعادة رقم مجرد أو إحالة المستخدم إلى مكان داخل ملف:\n"
            "- zoning_code: كود التنظيم/الاستخدام كما هو في الرخصة أو جدول التنظيم إن وُجد.\n"
            "- building_ratio: اكتب النسبة بجملة كاملة توضّح مجال تطبيقها، ولا تكتب «60%» وحدها. لا تذكر اسم الملف أو رقم الصفحة في القيمة.\n"
            "- coverage_ratio: نسبة التغطية إن ذُكرت منفصلة عن نسبة البناء، وإلا اتركها فارغة ولا تكرر نسبة البناء فيها.\n"
            "- building_ratio_coverage: اجمع نسبة البناء والتغطية وFAR وعدد الأدوار المرتبط بشريحة مساحة الأرض في قيمة مفهومة، بدون إحالات إلى الصفحات.\n"
            "- floor_area_ratio: معامل مسطح البناء (FAR) رقمًا مع شرح نطاق تطبيقه إن وُجد.\n"
            "- table_floors: عدد الأدوار المقابل لمساحة هذه الأرض، مع ذكر شريحة المساحة أو المحور بالكلمات فقط.\n"
            "- setbacks: الارتدادات الأربعة كل واحد برقمه بالمتر (أمامي/خلفي/جانبي أيمن/جانبي أيسر). إن لم تجدها فاكتب «غير محددة في المرجع المتاح» ولا تخترع أرقامًا.\n"
            "- parking_requirements: استخرج اشتراطات المواقف كاملة: العدد أو النسبة، نوع الاستخدام، وأبعاد الموقف أو المسار إن ذُكرت، دون ذكر أرقام الصفحات. إذا لم توجد فاكتب «غير محددة في المرجع المتاح».\n"
            "- entrances_exits_requirements: استخرج اشتراطات مداخل ومخارج السيارات والمشاة والخدمات والتحميل والفصل بين المداخل إن ذُكرت، دون ذكر أرقام الصفحات. إذا لم توجد فاكتب «غير محددة في المرجع المتاح».\n"
            "- allowed_uses: اكتب قائمة الاستخدامات المسموحة تنظيميًا لهذه الأرض من جدول التنظيم وملفي الاشتراطات "
            "(مثل: سكني، تجاري، فندقي، صناعي ولوجستي). لا تكتب حالة توافق نوع المشروع، ولا تكتب «حالة استخدام المشروع». "
            "إذا لم تُستخرج استخدامات واضحة فاكتب «غير محددة في المرجع المتاح».\n"
            "- regulatory_constraints: اذكر القيود التنظيمية المنطبقة على الموقع والمشروع، واجمع فيها المواقف والمداخل والمخارج والتحميل والخدمات عند وجودها، دون تكرار قائمة الاستخدامات.\n"
            "- allowed_uses_restrictions: اجمع allowed_uses وregulatory_constraints للتوافق مع البيانات القديمة فقط.\n"
            "- استخدم مساحة الأرض المستخرجة لاختيار الشريحة الصحيحة من جدول التنظيم؛ الجداول مفتاحها مساحة الأرض ونوع المحور/المنطقة.\n"
            "- لا تنسب اشتراطات إلى مدينة أو أمانة إلا إذا كانت المدينة ومصدر اللائحة واضحين في الملفات أو في المرجع المرفق.\n"
            "- لا تكتب في أي حقل عبارات مثل «صفحة كذا» أو «راجع الملف» أو اسم ملف كمصدر؛ اكتب الاشتراط نفسه مباشرة.\n"
            "قواعد التعارضات (conflicts) — لا تُعرض للمستخدم مباشرة:\n"
            "- عند اختلاف قيمة بين مستندين، سجّل التعارض هنا بجملة واحدة بدل اختيار قيمة من نفسك بصمت.\n"
            "- الشرح المفصّل للتعارض وأثره يُكتب داخل land_and_building_summary في فقرة المخاطر.\n"
            "- إذا لا توجد تعارضات أعد قائمة فارغة.\n"
            "قواعد الملخص (land_and_building_summary):\n"
            "- نص عربي مسترسل من ٣ إلى ٥ فقرات (١٨٠ كلمة على الأقل) وليس قائمة حقول مفصولة بشرطات.\n"
            "- لا تُعد سرد الأرقام التي وردت في الحقول؛ اربطها وحلّلها باختصار.\n"
            "- يغطي بالترتيب: (١) هوية القطعة وموقعها وصكها، (٢) المساحات والحدود والاتجاهات والواجهات، (٣) اشتراطات البناء، (٤) الاستخدامات المسموحة وحالة توافق نوع المشروع، (٥) القيود والمواقف والمداخل والمخارج، (٦) الفرص التطويرية المستنبطة من الاشتراطات، (٧) المخاطر والتعارضات وما يحتاج مراجعة.\n"
            "- يجب أن يذكر الملخص بوضوح الارتدادات والمواقف والمداخل والمخارج حتى لو وردت التفاصيل في الحقول الأخرى.\n"
            "- اربط ملاءمة الاشتراطات بنوع المشروع ومرحلته المدخلين، ولا تستبدلها بتحليل عام منفصل عن المشروع.\n"
            "- لا تذكر أرقام الصفحات أو أسماء الملفات أو مكان الاشتراط داخل الملخص؛ اذكر الاشتراط نفسه مباشرة.\n"
            "- اذكر صراحة أي معلومة غير متوفرة بدل تخطيها بصمت.\n"
            "ملاحظة: لا تُخرج حقل المساحة المعتمدة للدراسة المالية إطلاقًا؛ العميل هو من يحددها."
        )

        raw_resp = ""
        response_finish_reason = None
        model_error = ''
        vision_warnings = list(site_context_warnings)
        document_processing = []
        regulation_evidence_metadata = []
        reg_digest = {'matched': False}
        if _has_any_openrouter_key(_usage_ctx('land', data)):
            vision_parts = []
            document_descriptions = []
            per_document_budget = PDF_VISION_MAX_TOTAL_BYTES // max(1, len(documents))
            for doc in documents:
                try:
                    vision_diagnostics = {}
                    parts, warnings, page_count, mode = _prepare_document_vision_parts(
                        doc, budget=per_document_budget, diagnostics=vision_diagnostics)
                    vision_parts.extend(parts)
                    vision_warnings.extend(warnings)
                    processing = {
                        'filename': doc['filename'],
                        'mode': mode,
                        'page_count': page_count,
                        'dpi': PDF_VISION_DPI if mode == 'pdf_rendered' else None
                    }
                    processing.update({
                        key: vision_diagnostics[key]
                        for key in ('page_rotations', 'rotated_page_count', 'tile_count', 'image_count', 'encoded_base64_bytes')
                        if key in vision_diagnostics
                    })
                    document_processing.append(processing)
                    document_descriptions.append(f"- {doc['key']}: {doc['filename']} ({mode}, {page_count} صفحة/صورة)")
                except Exception as render_error:
                    print(f"[EXTRACT LAND DOCUMENTS RENDER ERROR] {doc['filename']}: {render_error}")
                    return jsonify({
                        'success': False,
                        'error': f'تعذر تجهيز المستند بصريًا: {doc["filename"]}. لم يتم إرسال PDF كملف عادي حتى لا ينتج AI بيانات غير دقيقة.',
                        'documentProcessing': document_processing,
                        'details': str(render_error)
                    }), 422

            request_facts = {
                'zoning_code': data.get('zoningCode') or data.get('zoning_code') or site_context.get('zoning_code') or '',
                'land_use': data.get('landUse') or data.get('land_use') or site_context.get('land_use') or '',
                'city': data.get('city') or site_context.get('city') or '',
                'project_type': data.get('projectType') or '',
                'location_address': data.get('locationAddress') or data.get('location_address') or '',
                'location_lat': data.get('locationLat') or data.get('location_lat') or location_lat,
                'location_lng': data.get('locationLng') or data.get('location_lng') or location_lng,
            }
            facts_prompt = (
                "أنت مستخرج حقائق أولي من صور مستندات الأرض والكروكي. أعد JSON فقط بهذا الشكل: "
                '{"site_facts":{"plot_number":"","area_sqm":null,"zoning_code":"",'
                '"land_use":"","city":"","project_type":"","axis_type":"","building_type":"",'
                '"location_address":"","location_lat":null,"location_lng":null},'
                '"uncertainties":[]} '
                "اقرأ الصور فقط ولا تستخدم أي لائحة أو تخمين. area_sqm يجب أن تكون مساحة «بموجب التنظيم» إن ظهرت، "
                "وإذا لم تكن واضحة اتركها null. هذا استخراج تمهيدي لا يكتب الملخص النهائي."
            )
            facts_payload = [{
                'type': 'text',
                'text': facts_prompt + '\nالمستندات المرفقة:\n' + '\n'.join(document_descriptions)
            }] + vision_parts
            facts_result, facts_cap, facts_error = _run_land_json_stage(
                'site_facts', facts_prompt, facts_payload,
                LAND_FACTS_MAX_TOKENS, LAND_FACTS_MIN_TOKENS, LAND_FACTS_MAX_TOKENS * 2,
                usage_ctx=_usage_ctx('land', data),
            )
            if facts_error:
                vision_warnings.append('تعذر استخراج حقائق الكروكي الأولية؛ تم استخدام بيانات المشروع المدخلة فقط.')
                print(f'[LAND ANALYSIS STAGE ERROR] site_facts cap={facts_cap} {facts_error}')
            site_facts = _extract_land_site_facts(facts_result, request_facts)
            if REGULATION_DIGEST_ENABLED:
                try:
                    reg_digest = regulation_digest.build_regulation_digest(site_facts)
                except Exception as digest_error:
                    reg_digest = {'matched': False}
                    vision_warnings.append(f'تعذر قراءة قاعدة بيانات الاشتراطات الموثقة: {digest_error}')
                    print(f'[REGULATION DIGEST ERROR] {digest_error}')
            evidence_results = []
            if reg_digest.get('matched'):
                regulation_evidence_metadata = [{
                    'name': 'قاعدة بيانات الأنظمة الموثقة (rules/)',
                    'zone': reg_digest.get('zone_key'),
                    'special_plan_required': reg_digest.get('special_plan_required'),
                    'sources': reg_digest.get('sources', []),
                }]
                print(f"[REGULATION DIGEST] zone={reg_digest.get('zone_key')} "
                      f"fields={sorted(reg_digest.get('fields') or {})} "
                      f"special={reg_digest.get('special_plan_required')}")
            else:
                regulation_query = ' '.join(str(value) for value in site_facts.values() if value not in (None, ''))
                try:
                    evidence_package, evidence_warnings = search_official_regulations_evidence(
                        regulation_query, site_facts)
                except Exception as evidence_error:
                    evidence_package = {'context': '', 'documents': [], 'table_pages': []}
                    evidence_warnings = [f'تعذر تجهيز أدلة الاشتراطات: {evidence_error}']
                vision_warnings.extend(evidence_warnings)
                for source in evidence_package.get('documents', []):
                    source_name = source.get('name') or 'ملف اشتراطات'
                    source_tables = [
                        entry for entry in evidence_package.get('table_pages', [])
                        if entry.get('name') == source_name
                    ]
                    source_for_evidence = {**source, 'table_pages': source_tables}
                    extracted_evidence = _extract_full_regulation_evidence(
                        source_for_evidence, site_facts, usage_ctx=_usage_ctx('land', data))
                    vision_warnings.extend(extracted_evidence.get('warnings', []))
                    if not extracted_evidence.get('evidence') and not extracted_evidence.get('uncertainties'):
                        if not source.get('context') and not source_tables:
                            vision_warnings.append(f'لم يتوفر محتوى قابل للقراءة في {source_name}؛ لن يتم تخمين اشتراطاته.')
                        evidence_results.append({
                            'source_file': source_name,
                            'evidence': {},
                            'error': 'لا يوجد محتوى قابل للقراءة أو تعذر استخراج أدلة',
                        })
                        continue
                    evidence_results.append({
                        'source_file': source_name,
                        'evidence': extracted_evidence.get('evidence', []),
                        'uncertainties': extracted_evidence.get('uncertainties', []),
                    })
                regulation_evidence_metadata = [
                    {
                        'name': source.get('name'),
                        'text_pages': source.get('text_pages', []),
                        'table_pages': source.get('table_pages', []),
                    }
                    for source in evidence_package.get('documents', [])
                ]
                print(
                    f"[REGULATION EVIDENCE] documents={len(regulation_evidence_metadata)} "
                    f"text_chars={sum(len(source.get('context') or '') for source in evidence_package.get('documents', []))} "
                    f"table_pages={len(evidence_package.get('table_pages', []))}"
                )

            if reg_digest.get('matched'):
                instructions = (
                    "لديك نوعان من المدخلات، لا تخلط بينهما:\n"
                    "١) مستندات العميل (الصك/الكروكي/الرخصة): مُرسلة صورًا عالية الدقة. اقرأها بصريًا فقط "
                    "ولا تعتمد على OCR أو نص مستخرج، واقرأ جداولها من الصورة نفسها.\n"
                    "٢) بلوك اشتراطات موثق مختار حتميًا من قاعدة بيانات الأنظمة المبنية على ملفي الاشتراطات. "
                    "قيمه الرقمية ملزمة: استخدمها حرفيًا ولا تخترع قاعدة غير موجودة فيه.\n"
                    "أولوية جدول التنظيم الرسمية مطلقة عند التعارض، وخاصة لجدول الإحداثيات وجدول الاتجاهات. "
                    "لا تخلط بين شرقيات/شماليات المساحية وبين latitude/longitude. لا تذكر أرقام الصفحات أو أسماء الملفات في أي قيمة للمستخدم.\n"
                )
                regulation_block = regulation_digest.digest_prompt_block(reg_digest) + "\n\n"
            else:
                instructions = (
                    "لديك نوعان من المدخلات، لا تخلط بينهما:\n"
                    "١) مستندات العميل (الصك/الكروكي/الرخصة): مُرسلة صورًا عالية الدقة. اقرأها بصريًا فقط "
                    "ولا تعتمد على OCR أو نص مستخرج، واقرأ جداولها من الصورة نفسها.\n"
                    "٢) نتائج استخلاص مبنية على المحتوى الكامل لملفي اشتراطات1 واشتراطات2، بما في ذلك جداول كل ملف. "
                    "استخدم القواعد التي تنطبق على حقائق الموقع فقط، ولا تخترع قاعدة غير موجودة في المحتوى الكامل.\n"
                    "أولوية جدول التنظيم الرسمية مطلقة عند التعارض، وخاصة لجدول الإحداثيات وجدول الاتجاهات. "
                    "لا تخلط بين شرقيات/شماليات المساحية وبين latitude/longitude. لا تذكر أرقام الصفحات أو أسماء الملفات في أي قيمة للمستخدم.\n"
                )
                regulation_block = (
                    "نتائج استخلاص الاشتراطات من المحتوى الكامل للملفين:\n"
                    + json.dumps(evidence_results, ensure_ascii=False)
                    + "\n\n"
                    if evidence_results else
                    "تنبيه: لم تتوفر نتائج قابلة للاستخدام من الملفين كاملين. لا تخترع اشتراطات، وسجّل ذلك في conflicts.\n\n"
                )
            user_content = [{
                "type": "text",
                "text": instructions
                        + "بيانات المعلومات الأساسية ورؤية المشروع التي أدخلها العميل:\n"
                        + project_context_block + "\n\n"
                        + "حقائق الموقع الأولية المستخرجة من الكروكي:\n"
                        + json.dumps(site_facts, ensure_ascii=False) + "\n\n"
                        + "استخدم هذه البيانات كسياق فعلي لربط الملخص بالمشروع، ولا تنسبها إلى الصك أو الكروكي أو اللائحة إذا لم يذكر مصدرها.\n\n"
                        + regulation_block
                        + "مستندات العميل المرفقة:\n" + "\n".join(document_descriptions)
            }] + vision_parts

            try:
                res, used_cap, provider_error = _call_land_analysis_model(
                    system_prompt, user_content, LAND_ANALYSIS_MAX_TOKENS,
                    usage_ctx=_usage_ctx('land', data))
                if _has_chat_choices(res):
                    raw_resp = _get_chat_response_text(res)
                    choices = res.get('choices') if isinstance(res, dict) else []
                    response_finish_reason = choices[0].get('finish_reason') if choices and isinstance(choices[0], dict) else None
                    print(f"[EXTRACT LAND DOCUMENTS] analyzed {len(documents)} document(s), "
                          f"cap={used_cap}, finish_reason={response_finish_reason}, chars={len(raw_resp)}")
                else:
                    model_error = provider_error
                    print(f"[EXTRACT LAND DOCUMENTS ERROR] cap={used_cap} {provider_error}")
            except Exception as model_err:
                model_error = str(model_err)
                print(f"[EXTRACT LAND DOCUMENTS EXCEPTION] {model_err}")

        # Partial JSON is never accepted: half a parcel is worse than no parcel. But the failure
        # must say so plainly, otherwise a rejected re-analysis just looks like "nothing changed".
        if response_finish_reason == 'length':
            print(f"[EXTRACT LAND DOCUMENTS TRUNCATED] {len(raw_resp)} chars at cap {used_cap}")
            return jsonify({
                'success': False,
                'error': (f'انقطعت استجابة الذكاء الاصطناعي عند الحد الأقصى ({used_cap} رمز) '
                          'فلم يُعتمد أي حقل، ولهذا لم تتغير البيانات. أعد المحاولة، '
                          'أو ارفع LAND_ANALYSIS_MAX_TOKENS إن تكرر ذلك.'),
                'failureReason': 'truncated',
                'documentProcessing': document_processing
            }), 503
        if not raw_resp.strip():
            # Report what the provider actually said. "Check your API keys" was misleading when the
            # real cause was an insufficient credit balance for the reserved max_tokens.
            insufficient_credit = 'afford' in model_error or 'credit' in model_error.lower()
            blocked_format = bool(_JSON_MODE_BLOCK_RE.search(model_error or ''))
            if insufficient_credit:
                message = ('رصيد OpenRouter لا يكفي لهذا الطلب، فلم يُعتمد أي حقل ولم تتغير البيانات. '
                           'أضف رصيدًا أو قلّل LAND_ANALYSIS_MAX_TOKENS.')
                return jsonify({
                    'success': False,
                    'error': message,
                    'failureReason': 'insufficient_credit',
                    'providerError': model_error,
                    'documentProcessing': document_processing
                }), 503
            if blocked_format:
                message = ('مزوّد الذكاء الاصطناعي رفض صيغة JSON الإجبارية، فلم يُعتمد أي حقل ولم تتغير البيانات. '
                           f'سبب المزوّد: {model_error}')
                return jsonify({
                    'success': False,
                    'error': message,
                    'failureReason': 'provider_blocked',
                    'providerError': model_error,
                    'documentProcessing': document_processing
                }), 503
            if model_error:
                message = f'لم يرد الذكاء الاصطناعي بأي محتوى فلم تتغير البيانات. سبب المزوّد: {model_error}'
            else:
                message = ('لم يرد الذكاء الاصطناعي بأي محتوى، فلم تتغير البيانات. '
                           'تأكد من مفاتيح API ثم أعد المحاولة.')
            return jsonify({
                'success': False,
                'error': message,
                'failureReason': 'empty_response',
                'providerError': model_error,
                'documentProcessing': document_processing
            }), 503
        parsed_response = parse_json_object(raw_resp)
        if parsed_response and reg_digest.get('matched'):
            _apply_regulation_digest_fields(parsed_response, reg_digest)
        if not parsed_response:
            print(f"[EXTRACT LAND DOCUMENTS UNPARSEABLE] first 400 chars: {raw_resp[:400]}")
            return jsonify({
                'success': False,
                'error': 'استجابة الذكاء الاصطناعي ليست JSON صالحًا، فلم يُعتمد أي حقل ولم تتغير البيانات.',
                'failureReason': 'invalid_json',
                'providerError': raw_resp[:400],
                'documentProcessing': document_processing
            }), 503
        resp_json = _normalize_land_document_result(
            parsed_response,
            raw_resp,
            project_type=str(data.get('projectType') or data.get('project_type') or '').strip(),
        )
        if vision_warnings:
            resp_json['warnings'] = vision_warnings
        resp_json['document_processing'] = document_processing
        resp_json['regulation_evidence'] = regulation_evidence_metadata
        extraction_diagnostics = _build_land_extraction_diagnostics(resp_json, document_processing)
        resp_json['extraction_diagnostics'] = extraction_diagnostics
        print(
            '[EXTRACT LAND DOCUMENTS TABLES] '
            f"coordinates={extraction_diagnostics['coordinates_rows']} "
            f"complete_coordinates={extraction_diagnostics['coordinates_complete_rows']} "
            f"directions={extraction_diagnostics['directions_with_values']}/4 "
            f"conflicts={extraction_diagnostics['conflict_count']}"
        )

        # Check if there are actual non-empty values extracted
        parcels = resp_json.get('parcels') if isinstance(resp_json, dict) else []
        has_scalar_values = bool(parcels) and any(
            any(value not in (None, '', [], {}) for key, value in parcel.items() if key not in {'parcel_id', 'directions', 'coordinates', 'confidence', 'sources'})
            for parcel in parcels if isinstance(parcel, dict)
        )
        has_table_values = bool(extraction_diagnostics['coordinates_rows'] or extraction_diagnostics['directions_with_values'])
        has_non_empty_values = bool(raw_resp.strip()) and bool(parcels) and (has_scalar_values or has_table_values)

        if not resp_json or not has_non_empty_values:
            print(f"[CROQUIS DEBUG RAW RESP]\n{raw_resp}")
            return jsonify({'success': False, 'error': f'لم يتم التوصل لبيانات مؤكدة في الصورة أو المستند المرفق. يرجى التأكد من وضوح الصورة.'})

        return jsonify({'success': True, 'extractedData': resp_json, 'rawText': raw_resp, 'documentProcessing': document_processing})
    except Exception as exc:
        err_msg = traceback.format_exc()
        print(f"[EXTRACT CROQUIS ERROR]\n{err_msg}")
        return jsonify({'success': False, 'error': f'حدث خطأ في قراءة ملف الكروكي: {str(exc)}'})


@app.route('/api/field-sections/custom/<section_key>', methods=['DELETE'])
@require_permission('custom_fields')
def api_delete_custom_section(section_key):
    """Delete a custom field section. Fields move to 'general'."""
    # Prevent deleting built-in sections
    builtin_keys = {s['key'] for s in db.FIELD_SECTIONS}
    if section_key in builtin_keys:
        return jsonify({'error': 'لا يمكن حذف قسم أساسي'}), 400
    if not db.get_custom_section(g.tenant_id, section_key):
        return jsonify({'error': 'Custom section not found'}), 404
    db.delete_custom_section(g.tenant_id, section_key)
    return jsonify({'success': True})


@app.route('/api/users/<user_id>/field-sections', methods=['GET'])
@require_permission('manage_users')
def api_get_user_field_sections(user_id):
    """Get effective field section visibility for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    sections = db.get_user_field_sections(user_id, g.tenant_id)
    return jsonify({'success': True, 'sections': sections, 'available': db.get_all_sections(g.tenant_id)})


@app.route('/api/users/<user_id>/field-sections', methods=['PUT'])
@require_permission('manage_users')
def api_set_user_field_sections(user_id):
    """Set field section visibility for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404

    data = request.json or {}
    sections = data.get('sections', {})
    all_keys = {s['key'] for s in db.get_all_sections(g.tenant_id)}
    for key, granted in sections.items():
        db.set_user_field_section(user_id, key, bool(granted))

    sections = db.get_user_field_sections(user_id)
    return jsonify({'success': True, 'sections': sections})


def _send_invite_email(invite, tenant, email=None):
    """Deliver one invite email and record the outcome on the row (t21)."""
    recipient = email or invite.get('email')
    company_name = (tenant and tenant.get('company_name')) or 'الشركة'
    base_url = _current_base_url().rstrip('/')
    full_invite_url = f"{base_url}/invite/{invite['token']}"
    ok = send_platform_email(
        recipient,
        f'دعوة للانضمام إلى {company_name}',
        f'مرحبًا،\n\nتمت دعوتك للانضمام إلى فريق {company_name} في منصة LandLoom AI.\n'
        f'لإكمال التسجيل وتعيين كلمة المرور، يرجى زيارة الرابط التالي:\n{full_invite_url}\n\n'
        'هذا الرابط صالح للاستخدام لمدة 7 أيام.'
    )
    db.mark_invite_email(invite['id'], 'sent' if ok else 'failed',
                         None if ok else 'smtp_send_failed')
    return ok


@app.route('/api/invites', methods=['POST'])
@require_permission('manage_users')
def api_create_invite():
    """Create an invite carrying the pre-assigned role and scope (t21)."""
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    if not email or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Valid email required'}), 400
    role = data.get('role') or 'employee'
    if role not in db.USER_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    invite = db.create_invite(
        g.tenant_id, email,
        role=role,
        name=data.get('name'), phone=data.get('phone'),
        sections=data.get('sections') if isinstance(data.get('sections'), list) else None,
        projects=data.get('projects') if isinstance(data.get('projects'), list) else None,
    )
    tenant = db.get_tenant_by_id(g.tenant_id)
    email_sent = _send_invite_email(invite, tenant, email)
    invite_url = f"/invite/{invite['token']}"
    _record_audit_event('invite.created', 'invite_link', invite['id'], entity_name=email,
                        metadata={'role': role, 'email_sent': email_sent})
    return jsonify({'success': True, 'inviteUrl': invite_url, 'token': invite['token'],
                    'inviteId': invite['id'], 'emailSent': email_sent})


@app.route('/api/invite/<token>', methods=['GET'])
def api_get_invite(token):
    """Get invite info (public, no auth needed)."""
    limited = _rate_limit_attempt('invite:ip', _rate_limit_client_ip())
    if limited:
        return limited
    invite = db.get_invite_by_token(token)
    if not invite:
        return jsonify({'error': 'Invalid or expired invite'}), 404
    tenant = db.get_tenant_by_id(invite['tenant_id'])
    return jsonify({
        'success': True,
        'email': invite['email'],
        'companyName': tenant['company_name'] if tenant else '',
    })


@app.route('/api/invite/<token>/register', methods=['POST'])
def api_accept_invite(token):
    """Register a user via invite link."""
    limited = _rate_limit_attempt('invite:ip', _rate_limit_client_ip())
    if limited:
        return limited
    invite = db.get_invite_by_token(token)
    if not invite:
        return jsonify({'error': 'Invalid or expired invite'}), 404

    data = request.json or {}
    name = (data.get('name') or invite.get('name') or '').strip()
    password = data.get('password', '')
    if not password:
        return jsonify({'error': 'password is required'}), 400
    password_error = _password_validation_error(password)
    if password_error:
        return jsonify({'error': password_error}), 400

    existing = db.get_user_by_email(invite['email'])
    if existing:
        return jsonify({'error': 'Email already registered'}), 409

    # The invite fixes the role and scope; the registrant only picks a name and
    # password (t21). The name defaults to the one the admin typed on the invite.
    invite_role = invite.get('role') if invite.get('role') in db.USER_ROLES else 'employee'
    if not name:
        return jsonify({'error': 'name is required'}), 400
    user_id = db.create_user(
        invite['tenant_id'], name, invite['email'], hash_password(password),
        role=invite_role, phone=invite.get('phone'),
    )
    try:
        db.apply_invite_scope(user_id, invite)
    except Exception:
        pass
    db.mark_invite_used(token)
    db.record_login(invite['tenant_id'], user_id)

    tenant = db.get_tenant_by_id(invite['tenant_id'])
    jwt_token = create_token(tenant['id'], invite['email'], is_admin=False,
                             user_id=user_id, user_name=name, user_role=invite_role)
    return jsonify({
        'success': True,
        'token': jwt_token,
        'tenant': {
            'id': tenant['id'],
            'companyName': tenant['company_name'],
            'email': tenant['email'],
        },
        'user': {'id': user_id, 'name': name, 'email': invite['email'], 'role': invite_role}
    }), 201


@app.route('/api/invites/<invite_id>/resend', methods=['POST'])
@require_permission('manage_users')
def api_resend_invite(invite_id):
    """Retry the invite email for a still-pending invite (t21)."""
    invite = db.get_invite(g.tenant_id, invite_id)
    if not invite:
        return jsonify({'error': 'Invite not found'}), 404
    if invite.get('used_at'):
        return jsonify({'error': 'Invite already used'}), 409
    try:
        expired = invite.get('expires_at') and datetime.fromisoformat(invite['expires_at']) < datetime.now(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        expired = False
    if expired:
        return jsonify({'error': 'Invite already expired'}), 409
    tenant = db.get_tenant_by_id(g.tenant_id)
    sent = _send_invite_email(invite, tenant)
    _record_audit_event('invite.resent', 'invite_link', invite_id,
                        entity_name=invite.get('email'), metadata={'email_sent': sent})
    return jsonify({'success': True, 'emailSent': sent,
                    'emailAttempts': int(invite.get('email_attempts') or 0) + 1})
