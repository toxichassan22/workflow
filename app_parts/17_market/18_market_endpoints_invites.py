


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Market study endpoints and jobs: payload prep, the competitors and
# summary executors with citation collection, the file-backed market job
# worker, and the /api/market-study routes.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# The market flows are the only AI surface that sees the whole project file —
# every other chat gets a hand-picked slice, but a market study cannot evaluate
# a project it cannot see, so chat and research prompts share the same bounded
# build_project_facts brief (grouped by section, per-field and total caps).
_MARKET_PROJECT_FACTS_LIMIT = 60000


def _market_project_facts(data, tenant_id=None):
    """All-sections project context for market prompts: the live client payload
    when it arrives, else the stored draft — rendered as the labeled facts
    brief, never a raw JSON dump."""
    source = data.get('projectData') or data.get('project_data')
    if not isinstance(source, dict) or not source:
        source = None
        draft_id = str(data.get('draftId') or data.get('draft_id') or '').strip()
        if draft_id:
            if tenant_id is None:
                try:
                    tenant_id = getattr(g, 'tenant_id', None)
                except Exception:
                    tenant_id = None
            if tenant_id:
                try:
                    draft = db.get_project_draft_by_id(tenant_id, draft_id) or {}
                    source = draft.get('draft_data')
                except Exception as exc:
                    print(f'[MARKET] project facts draft lookup failed: {exc}')
        if not isinstance(source, dict) or not source:
            return ''
    try:
        facts = str(slide_engine.build_project_facts(source, tenant_id) or '').strip()
    except Exception as exc:
        print(f'[MARKET] project facts build failed: {exc}')
        return ''
    if len(facts) > _MARKET_PROJECT_FACTS_LIMIT:
        facts = facts[:_MARKET_PROJECT_FACTS_LIMIT] + '\n... [تم اختصار ملف المشروع]'
    return facts


def _prepare_market_payload(data, tenant_id=None):
    payload = dict(data or {})
    payload['dataPeriodLabel'] = _market_period_label(payload)
    payload['dataPeriodBounds'] = market_study.data_period_bounds(
        payload.get('dataPeriod') or payload.get('data_period'),
        payload.get('dataPeriodFrom') or payload.get('data_period_from'),
        payload.get('dataPeriodTo') or payload.get('data_period_to'),
    )
    mixed = payload.get('projectComponents') or payload.get('project_mixed_components') or payload.get('project_components')
    payload['projectComponents'] = mixed
    raw_scope = payload.get('competitorScope') or payload.get('competitor_scope')
    if isinstance(raw_scope, str):
        try:
            raw_scope = json.loads(raw_scope)
        except (TypeError, ValueError):
            raw_scope = {}
    raw_scope = raw_scope if isinstance(raw_scope, dict) else {}
    payload['competitorScope'] = {
        'mode': 'city' if str(raw_scope.get('mode') or '').strip().lower() == 'city'
        else 'district'
    }
    raw_comparisons = (payload.get('comparisonTypes')
                       if 'comparisonTypes' in payload else payload.get('comparison_types'))
    payload['comparisonTypes'] = market_study.normalize_comparison_types(raw_comparisons)
    payload['summaryScope'] = market_study.normalize_summary_scope(
        payload.get('summaryScope') or payload.get('summary_scope'))
    payload['projectFacts'] = _market_project_facts(data, tenant_id)
    return payload


# One wall-clock budget for a whole competitors job. The same deadline rides
# into every browse call and fetch, so a stage stops handing the next stage
# work the job no longer has time for instead of draining its own step cap.
try:
    _MARKET_JOB_TIME_BUDGET = max(60, int(os.environ.get('MARKET_JOB_TIME_BUDGET') or 540))
except (TypeError, ValueError):
    _MARKET_JOB_TIME_BUDGET = 540

# Expansion rounds stop this far short of the deadline so row verification
# and the logo pass still get their share of the budget.
_MARKET_EXPANSION_DEADLINE_MARGIN = 30

# The known-sources plan runs before the browse agent, serially — a chain of
# timed-out catalog entries must not eat the agent's share of the job budget,
# so the stage runs on this sub-deadline instead of the job's own.
try:
    _SOURCE_PLAN_TIME_BUDGET = max(30, int(os.environ.get('MARKET_SOURCE_PLAN_BUDGET') or 150))
except (TypeError, ValueError):
    _SOURCE_PLAN_TIME_BUDGET = 150


def _new_evidence_pool():
    """One EvidencePool per market job — shared by the source plan, every
    browse call, the verify pool and the logo pass, so no query or page is
    fetched twice. None while the web_browse evidence module isn't deployed;
    every consumer treats None as 'pool layer off' and behaves as before."""
    try:
        import evidence
        pool_cls = getattr(evidence, 'EvidencePool', None)
        return pool_cls() if pool_cls is not None else None
    except Exception:
        return None


def _market_browser_session(search_provider=None):
    """The job's shared browser for the sequential stages (source plan, main
    and expansion calls, logo discovery). A BrowserWorker is lazy: building it
    is free and Chromium launches on the first real tool call — nothing
    launches for a run that never browses. None when the browser module can't
    provide one; calls then open their own per-run sessions as before."""
    try:
        import browser as _browser_module
        worker_cls = getattr(_browser_module, 'BrowserWorker', None)
        return worker_cls(search_provider=search_provider) if worker_cls is not None else None
    except Exception:
        return None


def _market_source_fetch_http(url):
    """``fetch_http`` injected into ``run_source_plan`` — the pinned-HTTPS
    reader the pipeline already trusts for retrieved source pages. Returns the
    page markup ('' when unreadable); thin shells are the browser path's job.
    """
    html, _err = _read_market_source_page(url)
    return html or ''


def _market_agent_progress(report, lo, hi, label):
    """Map a browse-agent run's on_event dicts onto (percent, message) reports.

    The bar moves with the agent's own steps — model rounds, searches, page
    opens, and their failures — instead of freezing for the minutes a run can
    take. ``label`` is the stage name the step detail is attached to.
    """
    if not callable(report):
        return None
    span = max(1, int(hi) - int(lo))

    def _on_event(event):
        if not isinstance(event, dict):
            return
        phase = event.get('phase')
        if phase not in ('round', 'tool', 'tool_done', 'retry'):
            return
        try:
            step = max(1, int(event.get('step') or 1))
            max_steps = max(step, int(event.get('max_steps') or step))
        except (TypeError, ValueError):
            step, max_steps = 1, 1
        pct = int(lo) + int(span * min(step, max_steps) / max_steps)
        hint = str(event.get('hint') or '').strip()[:80]
        tool = str(event.get('tool') or '')
        if phase == 'retry':
            report(pct, f'{label} — تعثر المزود، إعادة المحاولة '
                        f'{int(event.get("attempt") or 1)}')
        elif phase == 'tool':
            verb = ('يبحث في الويب عن' if tool == 'web_search'
                    else 'يفتح صفحة' if tool == 'open_url' else 'ينفذ أداة')
            report(pct, f'{label} — {verb} «{hint}»' if hint
                   else f'{label} — {verb}')
        elif phase == 'tool_done':
            if event.get('ok') is False:
                report(pct, f'{label} — تعذّر «{hint}»' if hint
                       else f'{label} — تعذّرت خطوة')
        else:
            report(pct, f'{label} — يخطط الخطوة {step} من {max_steps}')

    return _on_event


def _run_market_source_plan(payload, offer_lang='ar', evidence_pool=None,
                            session=None, deadline=None, report=None):
    """Known-sources-first retrieval: the catalog's deep links (REGA datasets,
    sakani/ejar/stats, portal listing pages) feed the evidence pool before any
    model search runs. No-op until the retrieval-plan part lands in
    market_study — the plan functions resolve from its shared namespace."""
    if evidence_pool is None:
        return
    build = getattr(market_study, 'build_source_plan', None)
    run = getattr(market_study, 'run_source_plan', None)
    if not callable(build) or not callable(run):
        return
    try:
        plan = build(payload, offer_lang=offer_lang)
    except Exception as exc:
        print(f'[MARKET STUDY] source plan build failed: {exc}')
        return
    if not plan:
        return
    plan_deadline = time.time() + _SOURCE_PLAN_TIME_BUDGET
    if deadline is not None:
        try:
            plan_deadline = min(plan_deadline, float(deadline))
        except (TypeError, ValueError):
            pass
    try:
        outcome = run(plan, evidence_pool, _market_source_fetch_http,
                      session=session, deadline=plan_deadline, report=report)
        print(f'[MARKET STUDY] source plan done: {outcome}')
    except Exception as exc:
        print(f'[MARKET STUDY] source plan fetch failed: {exc}')


def _pool_covers_angle(evidence_pool, angle):
    """True when an expansion round for ``angle`` would only refetch stored
    evidence: the same query already ran (folded dedupe) or pool pages already
    carry the angle's distinctive tokens."""
    if evidence_pool is None:
        return False
    try:
        if evidence_pool.query_results(angle) is not None:
            return True
        tokens = _competitor_name_tokens(angle)
        if not tokens:
            return False
        needed = 1 if len(tokens) == 1 else 2
        return bool(evidence_pool.pages_for_name(tokens, needed))
    except Exception:
        return False


def _execute_market_competitors(data, tenant_id=None, progress=None):
    """Job entry — one evidence pool, one deadline, one shared browser session
    for everything the run searches or fetches; the pieces pass through to
    every stage that browses (source plan, main call, expansion rounds,
    row verify, logo pass)."""
    report = progress if callable(progress) else (lambda *_args: None)
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    evidence_pool = _new_evidence_pool()
    _preload_failed_run_evidence(tenant_id, 'competitors', data, evidence_pool)
    deadline = time.time() + _MARKET_JOB_TIME_BUDGET
    session = _market_browser_session(search_provider='searxng')
    try:
        result = _run_market_competitors(
            data, tenant_id=tenant_id, progress=report,
            evidence_pool=evidence_pool, deadline=deadline, session=session)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    return _attach_failure_evidence(result, evidence_pool)


def _run_market_competitors(data, tenant_id=None, progress=None,
                            evidence_pool=None, deadline=None, session=None):
    report = progress if callable(progress) else (lambda *_args: None)
    payload = _prepare_market_payload(data, tenant_id)
    offer_lang = slide_engine.resolve_offer_lang(data)
    axes = market_study.project_competitor_axes(payload)
    if not axes or not any(axis.get('explicit') for axis in axes):
        return {
            'success': False,
            'error': 'لا توجد اختيارات مقارنة صالحة.',
            'failureReason': 'comparison_scope_required',
        }
    payload['transactionBenchmarks'] = market_study.build_transaction_price_benchmarks(
        payload, axes)
    existing = data.get('competitors') if isinstance(data.get('competitors'), list) else []
    mode = 'fill' if str(data.get('mode') or '').strip() == 'fill' else 'generate'
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    system_prompt = market_study.build_consultant_system_prompt(offer_lang)
    training_context = (db.get_training_context(tenant_id, surface='content', offer_lang=offer_lang)
                        if tenant_id else '')
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    user_prompt = market_study.build_competitors_user_prompt(
        payload, existing, mode=mode, offer_lang=offer_lang)
    report(10, 'جاري البحث في الويب عن المنافسين وبياناتهم — قد يستغرق دقائق...')
    # Known sources first: the catalog's deep links land in the evidence pool
    # before the model searches, so rows built on them verify without refetch.
    _run_market_source_plan(payload, offer_lang=offer_lang,
                            evidence_pool=evidence_pool, session=session,
                            deadline=deadline, report=report)
    # A competitor scan is the widest single research task — one search per
    # plausible rival plus the market-wide ones, with room to open the pages
    # that surface. The model decides the queries; Chromium does the reads.
    res = _browse_agent_call(
        system_prompt, user_prompt,
        _usage_ctx('market', data, tenant_id=tenant_id),
        model=GEMINI_TEXT_MODEL,
        search_provider='searxng',
        evidence_pool=evidence_pool, deadline=deadline, session=session,
        search_budget=_COMPETITORS_SEARCH_BUDGET,
        max_steps=_COMPETITORS_MAX_STEPS,
        max_tokens=14000, reasoning_effort='low',
        on_event=_market_agent_progress(report, 22, 40,
                                        'البحث الرئيسي عن المنافسين'))
    provider_error = _chat_error_message(res) if res.get('error') else ''
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        fatal = _ai_fatal_error_dict(res)
        credit = (fatal is not None or _is_company_credit_error(provider_error or '')
                  or 'afford' in (provider_error or '').lower())
        wallet_msg = ((fatal or {}).get('message') or provider_error or '').strip()
        return {
            'success': False,
            'error': wallet_msg if credit and wallet_msg else 'تعذر توليد المنافسين.',
            'failureReason': 'insufficient_credit' if credit else parse_error,
            'providerError': provider_error,
            'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        }
    # Every grounded call's retrieved pages are evidence — collect them across
    # the main call and all expansion rounds instead of keeping only the
    # richest single answer, so later rounds keep feeding verification/logos.
    # Each page also lands in the shared pool, which is what phases 1-2 of
    # verification and the logo pass match against.
    citation_pages = []
    citation_urls = []
    _seen_citation_urls = set()

    def _collect_citations(response):
        for page in _market_citation_pages(response):
            if page['url'] not in _seen_citation_urls:
                _seen_citation_urls.add(page['url'])
                citation_pages.append(page)
                citation_urls.append(page['url'])
                if evidence_pool is not None:
                    try:
                        evidence_pool.add_page(
                            page['url'], title=page.get('title') or '',
                            content=page.get('content') or '', via='agent')
                    except Exception:
                        pass

    _collect_citations(res)
    generated = parsed.get('competitors') if isinstance(parsed.get('competitors'), list) else []
    generated = market_study.filter_and_cap_competitors(
        generated, axes, limit_per_axis=market_study.COMPETITOR_MIN_DIRECT,
        offer_lang=offer_lang, scope=payload.get('competitorScope'),
        city=payload.get('city'), district=payload.get('district'))
    named_generated = [row for row in generated
                       if isinstance(row, dict) and str(row.get('name') or '').strip()]
    # Expansion passes: a thin list usually means the model settled for the
    # first pages it saw. The minimum is per benchmark axis — a mixed-use
    # project needs COMPETITOR_MIN_DIRECT direct competitors for every
    # component — so deficient axes get their own targeted query first, then
    # the generic angles as a backstop. Stop when every axis is covered or a
    # pass answers cleanly yet adds nothing.
    _scope = market_study.competitor_scope_text(payload)
    _ptype = str(payload.get('projectType') or payload.get('project_type') or 'عقاري')
    _city = str(payload.get('city') or '')
    _district = str(payload.get('district') or '')
    axes = market_study.project_competitor_axes(payload)
    multi_axis = len(axes) > 1
    min_per_axis = market_study.COMPETITOR_MIN_DIRECT
    needs_benchmarks = any(axis['key'] != 'general' for axis in axes)
    axis_label_list = '، '.join(
        market_study.benchmark_axis_label(axis, offer_lang) for axis in axes)

    def _axis_deficits():
        counts = {axis['key']: 0 for axis in axes}
        for item in named_generated:
            for key in market_study.competitor_row_axis_keys(
                    item, axes, offer_lang=offer_lang):
                if key in counts:
                    counts[key] += 1
        return [axis for axis in axes if counts[axis['key']] < min_per_axis]

    axis_queries = {
        axis['key']: f'{axis["search"]} داخل {_scope} في {_city}'
        + (' عبر Booking.com' if axis.get('type') == 'hotel' else '')
        for axis in axes}
    seen_names = {market_study._fold_choice(row.get('name')) for row in named_generated}
    tried_axes = set()
    round_no = 0
    max_rounds = max(1, len(axis_queries))
    while mode != 'fill' and _market_search_ran(res) and round_no < max_rounds:
        # Near the job's deadline the loop stops so verify and logos keep
        # their share of the budget — an expansion answer that arrives after
        # the deadline lands nowhere.
        if deadline is not None and time.time() >= deadline - _MARKET_EXPANSION_DEADLINE_MARGIN:
            break
        deficits = _axis_deficits()
        if not deficits:
            break
        deficit_labels = '، '.join(
            market_study.benchmark_axis_label(axis, offer_lang) for axis in deficits)
        target = next((axis for axis in deficits
                       if axis['key'] not in tried_axes), None)
        if target is None:
            break
        tried_axes.add(target['key'])
        angle = axis_queries[target['key']]
        target_label = market_study.benchmark_axis_label(target, offer_lang)
        priority = (f'أولوية هذه الجولة اختيار العميل «{target_label}» فقط. '
                    'لا تضف أنواعًا أو عمليات أخرى.')
        if _pool_covers_angle(evidence_pool, angle):
            # The corpus already holds this angle — the same query ran before
            # or stored pages carry its tokens, so a fresh browse call would
            # mostly read pool hits instead of surfacing new names.
            continue
        round_lo = 40 + int(12 * round_no / max_rounds)
        round_hi = 40 + int(12 * (round_no + 1) / max_rounds)
        report(round_lo,
               f'عدد منافسي محور {deficit_labels} أقل من الحد الأدنى — بحث إضافي ({round_no + 1})...'
               if multi_axis else
               f'عدد المنافسين أقل من الحد الأدنى — بحث إضافي ({round_no + 1}) عن مشاريع مسماة أخرى...')
        known = '، '.join(str(row.get('name') or '') for row in named_generated) or 'لا يوجد'
        expansion_prompt = (
            f'نُجري دراسة سوق لمشروع {_ptype} في {_city}'
            + (f' — {_district}' if _district else '')
            + f'. نطاق المنافسين: {_scope}.\n'
            + 'انسخ city وdistrict حرفيًا من بيانات المشروع؛ في نطاق الحي لا تذكر حيًا آخر.\n'
            + f'المنافسون المسجلون حتى الآن: {known}.\n'
            + f'ابحث عبر SearXNG عن: {angle} — مشاريع مسماة '
              'حقيقية لم ترد في القائمة. لا تُدرج صفحات مؤشرات أو إحصاءات كمنافس.\n'
            + (priority + '\n' if priority else '')
            + (f'قيم benchmarks المسموحة حصرًا: {axis_label_list}.\n'
               if needs_benchmarks else '')
            + 'أعد JSON فقط: {"competitors":[{"name":"","city":"انسخ المدينة من بيانات المشروع حرفيًا",'
              '"district":"","hotel_stars":"",'
              '"benchmarks":[],"operation_type":"","price_type":"","price_currency":"",'
              '"price":"","source_urls":[]}]} '
              'مع بقية الحقول المعتادة عند توفرها.'
              + (' Write every field value in English using the allowed English enum '
                 'values (status: Operating/Under Construction/Off-Plan; classification: '
                 'Direct/Indirect/Benchmark; operation_type: Sale/Rent/Hotel Operation/Other).'
                 if offer_lang == 'en' else ''))
        res2 = _browse_agent_call(
            system_prompt, expansion_prompt,
            _usage_ctx('market', data, tenant_id=tenant_id),
            model=GEMINI_TEXT_MODEL,
            search_provider='searxng',
            evidence_pool=evidence_pool, deadline=deadline, session=session,
            search_budget=4, max_steps=10, max_tokens=14000,
            reasoning_effort='low',
            on_event=_market_agent_progress(
                report, round_lo, round_hi,
                f'بحث إضافي ({round_no + 1})'))
        _err2 = _chat_error_message(res2) if res2.get('error') else ''
        provider_error = provider_error or _err2
        _collect_citations(res2)
        parsed2, _parse_err2 = _parse_market_model_json(res2)
        more = parsed2.get('competitors') if isinstance(parsed2, dict) else []
        candidates = market_study.filter_and_cap_competitors(
            generated + (more if isinstance(more, list) else []), axes,
            limit_per_axis=min_per_axis, offer_lang=offer_lang,
            scope=payload.get('competitorScope'), city=payload.get('city'),
            district=payload.get('district'))
        candidate_names = {market_study._fold_choice(row.get('name')) for row in candidates}
        added_this_round = len(candidate_names - seen_names)
        generated = candidates
        named_generated = [row for row in generated if str(row.get('name') or '').strip()]
        seen_names = candidate_names
        round_no += 1
        if not added_this_round and not _parse_err2:
            # A clean response with no new rows means retrieval is exhausted;
            # a malformed/empty response is a technical miss — try the next angle.
            break
    merged, added, updated = market_study.merge_generated_competitors(
        existing, generated, mode=mode, offer_lang=offer_lang)
    if mode != 'fill':
        merged = market_study.filter_and_cap_competitors(
            merged, axes, limit_per_axis=market_study.COMPETITOR_MIN_DIRECT,
            offer_lang=offer_lang, scope=payload.get('competitorScope'),
            city=payload.get('city'), district=payload.get('district'))
    # The pool's pages are a superset of the citation list once the agent
    # layer records into it — union rather than assume, so matching works on
    # either side of that landing.
    evidence_pages = list(citation_pages)
    evidence_urls = list(citation_urls)
    if evidence_pool is not None:
        try:
            for _pool_page in evidence_pool.pages():
                _pool_url = str((_pool_page or {}).get('url') or '')
                if _pool_url and _pool_url not in _seen_citation_urls:
                    _seen_citation_urls.add(_pool_url)
                    evidence_pages.append(_pool_page)
                    evidence_urls.append(_pool_url)
        except Exception:
            pass
    market_study.apply_search_citations(merged, evidence_urls)
    _attach_retrieved_citations(merged, evidence_pages)
    report(52, 'التحقق من كل منافس ببحث مستقل في الويب...')
    _verify_competitor_rows(merged, payload, data, tenant_id=tenant_id,
                            progress=report, evidence_pool=evidence_pool,
                            deadline=deadline, band=(52, 70))
    for row in merged:
        market_study.canonicalize_competitor_source_urls(row)
        _drop_foreign_competitor_urls(row)
        _drop_banned_competitor_listing_urls(row)
    report(70, 'التحقق من روابط المصادر واحدًا واحدًا...')
    search_ran = _market_search_ran(res) or bool(citation_urls)
    if search_ran:
        # A grounded run that still leaves a row with zero source URLs means the
        # name came from the model's memory — flag it for the owner's review.
        for row in merged:
            if (row.get('row_source') or 'ai') == 'ai' and not market_study.competitor_source_urls(row):
                row['no_search_evidence'] = True
    if search_ran:
        dead_urls = _verify_market_urls(
            [url for row in merged for url in _competitor_claimed_urls(row)],
            progress=report, band=(70, 74))
        for row in merged:
            _flag_dead_competitor_urls(row, dead_urls)
    else:
        # The model answered from memory: keep the links visible for review,
        # flagged — the owner accepts or rejects each one.
        for row in merged:
            if (row.get('row_source') or 'ai') == 'ai':
                market_study.flag_unverified_competitor_sources(row)
    report(74, 'استيراد شعارات المنافسين من مواقعها الرسمية...')
    _auto_import_competitor_logos(
        merged, payload, data, tenant_id=tenant_id, progress=report,
        citation_pages=evidence_pages, evidence_pool=evidence_pool,
        deadline=deadline, session=session)
    report(93, 'إعداد جدول المصادر والتحذيرات...')
    sources = market_study.competitor_source_rows(merged)
    market_study.flag_out_of_period_sources(sources, payload.get('dataPeriodBounds'))
    notes = str(parsed.get('notes') or '').strip()
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
        'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        'partial': partial,
        'providerError': provider_error or None,
        'noEvidenceCount': no_evidence,
        'searchNotRunCount': search_not_run,
        'missingPriceCount': missing_prices,
        'conflictWarnings': [warning for row in merged for warning in (row.get('conflict_warnings') or [])],
        'searchExpanded': bool(parsed.get('searchExpanded')) or round_no > 0,
        'comparisonTypes': payload.get('comparisonTypes') or [],
        'competitorScope': payload.get('competitorScope') or {},
        'transactionBenchmarks': payload.get('transactionBenchmarks') or {},
        'expansionNote': expansion_note,
        'notes': notes,
    }


# The summary researches through provider-native search only (Google
# grounding via the OpenRouter server tool — owner-ordered): the model asks
# Google's own search inside the request and cites it, so no page is opened
# by our browser and the datacenter bot-wall never comes into play.
# Competitors and row verification stay on the self-hosted browse agent.
_SUMMARY_NATIVE_SEARCH_TOOLS = [
    {"type": "openrouter:web_search", "engine": "native"},
]
# Forced (not model-optional): the server tool alone lets the model answer
# from memory, which failed twice as search_not_run. Naming the tool in
# tool_choice compels at least one provider search per request.
_SUMMARY_NATIVE_TOOL_CHOICE = {"type": _SUMMARY_NATIVE_SEARCH_TOOLS[0]["type"]}
# The native call answers inside one request, but the loop cap stays as a
# guard so a stalled model cannot spin rounds against the job deadline.
_SUMMARY_MAX_STEPS = 16

# The whole summary job — source plan plus the one wide browse call — spends
# the same wall-clock minutes; env-overridable like _MARKET_JOB_TIME_BUDGET.
try:
    _SUMMARY_JOB_TIME_BUDGET = max(60, int(os.environ.get('SUMMARY_JOB_TIME_BUDGET') or 420))
except (TypeError, ValueError):
    _SUMMARY_JOB_TIME_BUDGET = 420

# The competitors sweep is wider still: roughly one search per plausible rival
# plus the market-level listings, each paired with page opens.
_COMPETITORS_SEARCH_BUDGET = 10
_COMPETITORS_MAX_STEPS = 20


def _execute_market_summary(data, tenant_id=None, progress=None):
    """Job entry — one evidence pool, one deadline, one shared browser
    session for the source plan and the main browse call, mirroring the
    competitors job's wiring."""
    report = progress if callable(progress) else (lambda *_args: None)
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    evidence_pool = _new_evidence_pool()
    _preload_failed_run_evidence(tenant_id, 'summary', data, evidence_pool)
    deadline = time.time() + _SUMMARY_JOB_TIME_BUDGET
    session = _market_browser_session()
    try:
        result = _run_market_summary(
            data, tenant_id=tenant_id, progress=report,
            evidence_pool=evidence_pool, deadline=deadline, session=session)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    return _attach_failure_evidence(result, evidence_pool)


def _run_market_summary(data, tenant_id=None, progress=None,
                        evidence_pool=None, deadline=None, session=None):
    report = progress if callable(progress) else (lambda *_args: None)
    payload = _prepare_market_payload(data, tenant_id)
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
    training_context = (db.get_training_context(tenant_id, surface='content', offer_lang=offer_lang)
                        if tenant_id else '')
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    report(10, 'جاري فحص المصادر الأساسية وتحليل السوق والمنافسين بالبحث في الويب — قد يستغرق دقائق...')
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)
    # Native Google search inside the request itself: the model queries and
    # cites provider search (AI-overview style) with zero page opens, so the
    # reply's url_citation annotations — or provider grounding metadata — are
    # the retrieved evidence. A transport failure, or a clean reply with
    # neither, is an explicit search_not_run, never a silent memory answer.
    # Known sources first: the catalog's deep links land in the shared pool
    # before the model searches, so their pages still enrich the sources table
    # and feed extracted evidence directly into the summary model prompt.
    _run_market_source_plan(payload, offer_lang=offer_lang,
                            evidence_pool=evidence_pool, session=session,
                            deadline=deadline, report=report)
    retrieved_evidence = market_study.format_retrieved_evidence_block(
        evidence_pool, offer_lang=offer_lang)
    user_prompt = market_study.build_summary_user_prompt(
        payload, competitors, current_summary, current_sources=current_sources, current_swot=current_swot,
        offer_lang=offer_lang, retrieved_evidence=retrieved_evidence,
    )
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        user_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    res = _browse_agent_call(
        system_prompt, user_prompt, usage_ctx,
        evidence_pool=evidence_pool, deadline=deadline, session=session,
        server_tools=_SUMMARY_NATIVE_SEARCH_TOOLS, local_tools=False,
        tool_choice=_SUMMARY_NATIVE_TOOL_CHOICE,
        max_steps=_SUMMARY_MAX_STEPS,
        max_tokens=MARKET_STUDY_MAX_TOKENS, reasoning_effort='low',
        on_event=_market_agent_progress(report, 24, 70,
                                        'بحث الويب لملخص السوق'))
    failed = res.get('error') is not None
    provider_error = _chat_error_message(res) if failed else ''
    if not failed and not _market_search_ran(res):
        provider_error = 'browse_agent: no browsed evidence'
        failed = True
    if failed and _ai_fatal_error_dict(res) is None:
        return {
            'success': False,
            'error': 'تعذر تنفيذ بحث الويب لملخص السوق. لم يُستبدل النص الحالي.',
            'failureReason': 'search_not_run',
            'providerError': provider_error,
            'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        }
    report(72, 'التحقق من مصادر الملخص وفترة بياناتها...')
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        fatal = _ai_fatal_error_dict(res)
        credit = (fatal is not None or _is_company_credit_error(provider_error or '')
                  or 'afford' in (provider_error or '').lower())
        wallet_msg = ((fatal or {}).get('message') or provider_error or '').strip()
        return {
            'success': False,
            'error': wallet_msg if credit and wallet_msg
                     else 'تعذر توليد ملخص السوق. لم يُستبدل النص الحالي.',
            'failureReason': 'insufficient_credit' if credit else parse_error,
            'providerError': provider_error,
            'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        }
    normalized = market_study.normalize_summary(parsed)
    if not market_study.summary_has_content(normalized.get('summary')):
        return {
            'success': False,
            'error': 'عاد النموذج ملخصًا فارغًا. لم يُستبدل النص الحالي.',
            'failureReason': 'empty_response',
            'providerError': provider_error,
            'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        }
    search_verified = _market_search_ran(res)
    # Citation collection unions the pool's fetched pages — a source-plan or
    # tool-read page is retrieved evidence even when the agent never cited it.
    citation_urls = list(_market_citation_urls(res))
    if evidence_pool is not None:
        for _pool_page in evidence_pool.pages():
            _pool_url = str((_pool_page or {}).get('url') or '').strip()
            if _pool_url:
                citation_urls.append(_pool_url)
    citation_urls = list(dict.fromkeys(citation_urls))
    market_study.apply_search_citations(normalized.get('sources'), citation_urls, url_key='url')
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
        'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
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
            elif kind == 'summary_chat':
                payload = _execute_market_summary_chat(data, tenant_id, progress=report)
            elif kind == 'summary_consolidate':
                payload = _execute_market_summary_consolidate(data, tenant_id, progress=report)
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
            if getattr(exc, 'fatal_ai_error', False):
                _write_market_job(tenant_id, job_id, {
                    'status': 'failed',
                    'success': False,
                    'kind': kind,
                    'error': _client_safe_llm_error(
                        getattr(exc, 'ai_message', '') or str(exc)),
                    'error_code': getattr(exc, 'error_code', None) or 'GENERATION_FAILED',
                    'failureReason': 'billing_refused',
                })
                return
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
        status = int(result.get('httpStatus') or (200 if result.get('success') else 422))
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

