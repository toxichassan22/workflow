


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Market study endpoints and jobs: payload prep, the competitors and
# summary executors with citation collection, the file-backed market job
# worker, and the /api/market-study routes.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
