


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


def _market_draft_data(data, tenant_id=None):
    """The stored project blob for a market job that arrived without one."""
    draft_id = str((data or {}).get('draftId')
                   or (data or {}).get('draft_id') or '').strip()
    if not draft_id:
        return {}
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    if not tenant_id:
        return {}
    try:
        draft = db.get_project_draft_by_id(tenant_id, draft_id) or {}
    except Exception as exc:
        print(f'[MARKET] draft location lookup failed: {exc}', flush=True)
        return {}
    stored = draft.get('draft_data')
    return stored if isinstance(stored, dict) else {}


def _prepare_market_payload(data, tenant_id=None):
    payload = dict(data or {})
    project_data = payload.get('projectData') or payload.get('project_data')
    project_data = project_data if isinstance(project_data, dict) else {}
    location_keys = (
        'city', 'district', 'location_lat', 'location_lng',
        'location_address', 'locationLat', 'locationLng', 'locationAddress',
    )
    if not any(payload.get(key) for key in location_keys):
        draft_data = _market_draft_data(data, tenant_id)
        if draft_data:
            for key in location_keys:
                if not payload.get(key) and draft_data.get(key):
                    payload[key] = draft_data[key]
            if any(payload.get(key) for key in location_keys):
                print(
                    '[MARKET STUDY] location backfilled from draft '
                    f'city={payload.get("city")!r} '
                    f'district={payload.get("district")!r} '
                    f'lat={payload.get("location_lat")!r} '
                    f'lng={payload.get("location_lng")!r}',
                    flush=True)
    if not payload.get('city'):
        payload['city'] = (project_data.get('city')
                           or project_data.get('City') or '')
    if not payload.get('district'):
        payload['district'] = (project_data.get('district')
                              or project_data.get('District') or '')
    if not payload.get('location_lat'):
        payload['location_lat'] = (project_data.get('location_lat')
                                  or project_data.get('locationLat') or '')
    if not payload.get('location_lng'):
        payload['location_lng'] = (project_data.get('location_lng')
                                  or project_data.get('locationLng') or '')
    payload['dataPeriodLabel'] = _market_period_label(payload)
    payload['dataPeriodBounds'] = market_study.data_period_bounds(
        payload.get('dataPeriod') or payload.get('data_period'),
        payload.get('dataPeriodFrom') or payload.get('data_period_from'),
        payload.get('dataPeriodTo') or payload.get('data_period_to'),
    )
    # The summary has its own period window; older drafts that predate it fall
    # back to the competitors period they used to share.
    summary_period = (payload.get('summaryPeriod') or payload.get('summary_period'))
    if summary_period or payload.get('summaryPeriodFrom') or payload.get('summaryPeriodTo'):
        payload['summaryPeriodLabel'] = _market_period_label({
            'dataPeriod': summary_period,
            'dataPeriodFrom': (payload.get('summaryPeriodFrom')
                               or payload.get('summary_period_from')),
            'dataPeriodTo': (payload.get('summaryPeriodTo')
                             or payload.get('summary_period_to')),
        })
        payload['summaryPeriodBounds'] = market_study.data_period_bounds(
            summary_period,
            payload.get('summaryPeriodFrom') or payload.get('summary_period_from'),
            payload.get('summaryPeriodTo') or payload.get('summary_period_to'),
        )
    else:
        payload['summaryPeriodLabel'] = payload['dataPeriodLabel']
        payload['summaryPeriodBounds'] = payload['dataPeriodBounds']
    payload['summaryResearchDepth'] = summary_research_depth(payload)
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
        payload.get('summaryScope') or payload.get('summary_scope'),
        payload.get('city'))
    payload['summaryLocalBenchmarks'] = market_study.build_summary_local_benchmarks(
        payload)
    payload['projectFacts'] = _market_project_facts(data, tenant_id)
    return payload


# One wall-clock budget for a whole competitors job, capped at two hours.
# The same deadline rides into every browse call and fetch, so a stage stops
# handing the next stage work the job no longer has time for.
def _market_job_time_budget(raw_value):
    try:
        configured = int(raw_value) if str(raw_value or '').strip() else 3600
    except (TypeError, ValueError):
        configured = 3600
    return min(7200, max(60, configured))


_MARKET_JOB_TIME_BUDGET = _market_job_time_budget(
    os.environ.get('MARKET_JOB_TIME_BUDGET'))

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
                            session=None, deadline=None, report=None,
                            market_wide=False):
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
    district_regions = None
    if not market_wide and session is not None:
        try:
            import aqar_projects
            city = str((payload or {}).get('city') or '').strip()
            cache_path = (os.path.join(
                UPLOADS_DIR, aqar_projects.REGION_CACHE_FILE_NAME)
                if UPLOADS_DIR else '')
            district_regions = aqar_projects.learn_district_regions(
                session, city, cache_path=cache_path)
            if district_regions:
                print(f'[MARKET STUDY] aqar district regions learned='
                      f'{len(district_regions)}', flush=True)
        except Exception as exc:
            print(f'[MARKET STUDY] aqar district regions skipped: {exc}')
    try:
        plan = build(payload, offer_lang=offer_lang, market_wide=market_wide,
                     district_regions=district_regions)
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


_BLOCKED_SOURCE_REASONS = {'blocked', 'http_401', 'http_403', 'http_429'}


def _blocked_sources_note(evidence_pool):
    """Name the hosts whose planned read was refused, so a block is never
    presented as an empty market. A timeout is a different failure and stays
    out of this line."""
    if evidence_pool is None or not hasattr(evidence_pool, 'to_dict'):
        return ''
    try:
        failures = (evidence_pool.to_dict() or {}).get('failures') or {}
    except Exception:
        return ''
    hosts = []
    for url, reason in (failures or {}).items():
        if str(reason or '').strip().lower() not in _BLOCKED_SOURCE_REASONS:
            continue
        host = market_study._source_host(url)
        if host and host not in hosts:
            hosts.append(host)
    if not hosts:
        return ''
    return (f'تعذر قراءة {len(hosts)} مصدرًا محجوبًا '
            f'({"، ".join(hosts[:5])})؛ لم يُعد الحظر سوقًا فارغًا.')


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
    raw_scope = (data or {}).get('competitorScope') or (data or {}).get('competitor_scope')
    if not raw_scope:
        raw_radius = ((data or {}).get('competitorRadius')
                      or (data or {}).get('competitor_radius'))
        if raw_radius:
            raw_scope = {
                'mode': 'city' if str(raw_radius).strip().lower() == 'city' else 'distance',
                'radius': raw_radius,
                'radius_custom_km': ((data or {}).get('competitorRadiusCustomKm')
                                     or (data or {}).get('competitor_radius_custom_km')),
            }
    competitor_scope = market_study.normalize_competitor_scope(raw_scope)
    if competitor_scope.get('mode') == 'distance':
        project_data = payload.get('projectData') or payload.get('project_data') or {}
        if not isinstance(project_data, dict):
            project_data = {}
        origin_lat = next((value for value in (
            payload.get('location_lat'), payload.get('locationLat'),
            project_data.get('location_lat'), project_data.get('locationLat'),
            project_data.get('lat'), project_data.get('latitude'))
            if value is not None and str(value).strip()), None)
        origin_lng = next((value for value in (
            payload.get('location_lng'), payload.get('locationLng'),
            project_data.get('location_lng'), project_data.get('locationLng'),
            project_data.get('lng'), project_data.get('longitude'))
            if value is not None and str(value).strip()), None)
        if origin_lat is not None and origin_lng is not None:
            competitor_scope['origin_lat'] = origin_lat
            competitor_scope['origin_lng'] = origin_lng
    payload['competitorScope'] = competitor_scope
    offer_lang = slide_engine.resolve_offer_lang(data)
    existing = data.get('competitors') if isinstance(data.get('competitors'), list) else []
    mode = 'fill' if str(data.get('mode') or '').strip() == 'fill' else 'generate'
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    if mode == 'fill':
        # Completion is a per-name lookup over the table's own rows. It must
        # never ride the district discovery pipeline — that run's failure used
        # to abort the whole fill before a single row was completed.
        return _run_market_competitors_fill(
            data, payload, existing, offer_lang=offer_lang,
            tenant_id=tenant_id, deadline=deadline, report=report)
    axes = market_study.project_competitor_axes(payload)
    if not axes:
        return {
            'success': False,
            'error': 'لا توجد اختيارات مقارنة صالحة.',
            'failureReason': 'comparison_scope_required',
        }
    payload['transactionBenchmarks'] = market_study.build_transaction_price_benchmarks(
        payload, axes)
    # The property kinds the client picked are a rule, not a hint: a row that
    # states a different kind is outside the request and never reaches the
    # table, while a row naming no kind at all is kept.
    scope_unit_types = market_study.competitor_scope_unit_types(
        payload.get('competitorScope') or {})
    system_prompt = market_study.build_consultant_system_prompt(offer_lang)
    training_context = (db.get_training_context(tenant_id, surface='content', offer_lang=offer_lang)
                        if tenant_id else '')
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    report(10, 'جاري البحث في الويب عن المنافسين وبياناتهم بالتوازي — قد يستغرق دقائق...')
    # The known-sources plan used to block the model scan. It now runs beside
    # the scans on its own browser thread; its pages still land in the shared
    # pool before verification and the logo pass read it.
    locked_report = _locked_report(report)
    # The named-project directory on aqar is a deterministic source beside
    # the agent scans: same city, same district promise, real price/area
    # ranges. It owns its browser thread and never blocks the scans.
    aqar_handle = _start_aqar_projects_scan(
        payload, axes, report=locked_report, deadline=deadline,
        offer_lang=offer_lang)
    source_thread = _start_source_plan_async(
        payload, offer_lang=offer_lang, evidence_pool=evidence_pool,
        deadline=deadline, report=locked_report, session=None)
    # One scan per comparison axis (plus a complementary portal angle for a
    # single-axis project), all in flight together. Each thread owns its
    # browser, and the shared evidence pool keeps them from refetching.
    scan_results = _run_scan_tasks(
        _competitor_scan_tasks(axes, offer_lang, mode),
        payload, existing, mode, offer_lang, tenant_id, data,
        evidence_pool, deadline, system_prompt, report, band=(22, 40))
    _await_source_plan(source_thread)
    aqar_rows = _await_aqar_projects_scan(aqar_handle, timeout=110)
    aggregate = _aggregate_scan_results(scan_results)
    provider_error = aggregate['provider_error']
    if not aggregate['usable'] and not aqar_rows:
        fatal = next((fatal for fatal in (
            _ai_fatal_error_dict(item.get('reply') or {})
            for item in scan_results) if fatal is not None), None)
        credit = (fatal is not None or _is_company_credit_error(provider_error or '')
                  or 'afford' in (provider_error or '').lower())
        wallet_msg = ((fatal or {}).get('message') or provider_error or '').strip()
        parse_error = aggregate['parse_error'] or 'empty_response'
        return {
            'success': False,
            'error': wallet_msg if credit and wallet_msg else 'تعذر توليد المنافسين.',
            'failureReason': 'insufficient_credit' if credit else parse_error,
            'providerError': provider_error,
            'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        }
    # Every grounded call's retrieved pages are evidence — collect them across
    # the parallel scans and the expansion round instead of keeping only the
    # richest single answer, so verification and logos keep their feed.
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

    for result in scan_results:
        if result.get('reply'):
            _collect_citations(result['reply'])
    # The aqar projects are already sourced; the agent's duplicates would
    # only spend a verification slot. Sourced rows go first so the per-axis
    # cap keeps them.
    aqar_names = {market_study._fold_choice(row.get('name'))
                  for row in aqar_rows if row.get('name')}
    combined_rows = list(aqar_rows) + [
        row for row in aggregate['competitors']
        if market_study._fold_choice(row.get('name')) not in aqar_names]
    generated = market_study.filter_and_cap_competitors(
        combined_rows, axes, limit_per_axis=market_study.COMPETITOR_MIN_DIRECT,
        offer_lang=offer_lang, scope=payload.get('competitorScope'),
        city=payload.get('city'), district=payload.get('district'),
        unit_types=scope_unit_types)
    named_generated = [row for row in generated
                       if isinstance(row, dict) and str(row.get('name') or '').strip()]
    axes = market_study.project_competitor_axes(payload)
    multi_axis = len(axes) > 1
    min_per_axis = market_study.COMPETITOR_MIN_DIRECT
    needs_benchmarks = any(axis['key'] != 'general' for axis in axes)

    def _axis_deficits():
        counts = {axis['key']: 0 for axis in axes}
        for item in named_generated:
            for key in market_study.competitor_row_axis_keys(
                    item, axes, offer_lang=offer_lang):
                if key in counts:
                    counts[key] += 1
        return [axis for axis in axes if counts[axis['key']] < min_per_axis]

    seen_names = {market_study._fold_choice(row.get('name')) for row in named_generated}
    round_no = 0
    # One expansion round, run for every deficient axis in parallel. The scans
    # already search per axis; a single round covers a thin first answer
    # without turning the job back into a sequential chain.
    if (mode != 'fill' and aggregate['search_ran']
            and not (deadline is not None
                     and time.time() >= deadline - _MARKET_EXPANSION_DEADLINE_MARGIN)):
        expansion_tasks = _expansion_scan_tasks(
            payload, axes, _axis_deficits(), named_generated,
            offer_lang=offer_lang, multi_axis=multi_axis,
            needs_benchmarks=needs_benchmarks, evidence_pool=evidence_pool)
        if expansion_tasks:
            report(40, 'عدد المنافسين أقل من الحد الأدنى — بحث إضافي بالتوازي...'
                   if multi_axis else
                   'عدد المنافسين أقل من الحد الأدنى — بحث إضافي بالتوازي عن مشاريع مسماة أخرى...')
            expansion_results = _run_parallel_expansions(
                expansion_tasks, payload, existing, mode, offer_lang,
                tenant_id, data, evidence_pool, deadline, system_prompt,
                report, band=(40, 52))
            for result in expansion_results:
                provider_error = (provider_error
                                  or str(result.get('provider_error') or '').strip())
                if result.get('reply'):
                    _collect_citations(result['reply'])
            more = []
            for result in expansion_results:
                rows = (result.get('parsed') or {}).get('competitors')
                if isinstance(rows, list):
                    more.extend(row for row in rows if isinstance(row, dict))
            candidates = market_study.filter_and_cap_competitors(
                generated + more, axes,
                limit_per_axis=min_per_axis, offer_lang=offer_lang,
                scope=payload.get('competitorScope'), city=payload.get('city'),
                district=payload.get('district'),
                unit_types=scope_unit_types)
            candidate_names = {market_study._fold_choice(row.get('name')) for row in candidates}
            if candidate_names - seen_names:
                generated = candidates
                named_generated = [row for row in generated
                                   if str(row.get('name') or '').strip()]
                seen_names = candidate_names
                round_no = 1
    merged, added, updated = market_study.merge_generated_competitors(
        existing, generated, mode=mode, offer_lang=offer_lang)
    # A named hotel row (typed by the client or left by an older AI pass) gets
    # its Booking price here; the browse agent cannot open Booking reliably.
    if not current_app.config.get('TESTING'):
        try:
            _fill_hotel_rows_from_booking(
                merged, payload, data, tenant_id=tenant_id)
        except Exception as exc:
            print(f'[MARKET STUDY] hotel name fill skipped: {exc}', flush=True)
    # Residential and commercial rows are completed from aqar's named-project
    # directory the same way, so a named project's figures never rest on a
    # model search. The discovery scan already read that directory; its links
    # are reused instead of fetching the page a second time.
    if not current_app.config.get('TESTING'):
        try:
            aqar_catalog = None
            if aqar_handle:
                aqar_result = ((aqar_handle.get('holder') or {})
                               .get('result') or {})
                if aqar_result.get('project_links'):
                    aqar_catalog = {
                        'links': aqar_result.get('project_links') or [],
                        'cards': aqar_result.get('card_rows') or [],
                    }
            _fill_project_rows_from_aqar(
                merged, payload, data, tenant_id=tenant_id,
                deadline=deadline, progress=report, band=(48, 52),
                catalog=aqar_catalog)
        except Exception as exc:
            print(f'[MARKET STUDY] aqar name fill skipped: {exc}', flush=True)
    if mode != 'fill':
        # The scope filter decides which rows THIS run may add; it is not a
        # licence to delete what the table already held. A hotel row completed
        # from Booking carries no district, so filtering the merged list used
        # to drop every existing row and leave an empty table after a run that
        # discovered nothing new.
        existing_keys = {
            market_study._fold_choice(row.get('name'))
            for row in existing
            if isinstance(row, dict) and str(row.get('name') or '').strip()
        }
        fresh_rows = [row for row in merged
                      if market_study._fold_choice(row.get('name'))
                      not in existing_keys]
        carried_rows = [row for row in merged
                        if market_study._fold_choice(row.get('name'))
                        in existing_keys]
        merged = market_study.filter_and_cap_competitors(
            fresh_rows, axes, limit_per_axis=market_study.COMPETITOR_MIN_DIRECT,
            offer_lang=offer_lang, scope=payload.get('competitorScope'),
            city=payload.get('city'), district=payload.get('district'),
            unit_types=scope_unit_types) + carried_rows
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
    report(74, 'التحقق من روابط المصادر واحدًا واحدًا...')
    search_ran = (aggregate['search_ran'] or bool(citation_urls))
    if search_ran:
        # A grounded run that still leaves a row with zero source URLs means the
        # name came from the model's memory — flag it for the owner's review.
        for row in merged:
            if (row.get('row_source') or 'ai') == 'ai' and not market_study.competitor_source_urls(row):
                row['no_search_evidence'] = True
    if search_ran:
        dead_urls = _verify_market_urls(
            [url for row in merged for url in _competitor_claimed_urls(row)],
            progress=report, band=(74, 78))
        for row in merged:
            _flag_dead_competitor_urls(row, dead_urls)
    else:
        # The model answered from memory: keep the links visible for review,
        # flagged — the owner accepts or rejects each one.
        for row in merged:
            if (row.get('row_source') or 'ai') == 'ai':
                market_study.flag_unverified_competitor_sources(row)
    report(78, 'استيراد شعارات المنافسين من مواقعها الرسمية...')
    _auto_import_competitor_logos(
        merged, payload, data, tenant_id=tenant_id, progress=report,
        citation_pages=evidence_pages, evidence_pool=evidence_pool,
        deadline=deadline, session=session)
    for row in merged:
        market_study.canonicalize_competitor_source_urls(row)
        _drop_foreign_competitor_urls(row)
        _drop_banned_competitor_listing_urls(row)
    report(93, 'إعداد جدول المصادر والتحذيرات...')
    sources = market_study.competitor_source_rows(merged)
    market_study.flag_out_of_period_sources(sources, payload.get('dataPeriodBounds'))
    notes = aggregate['notes']
    blocked_note = _blocked_sources_note(evidence_pool)
    if blocked_note:
        notes = f'{notes} — {blocked_note}' if notes else blocked_note
    if aqar_rows:
        aqar_note = (f'Read {len(aqar_rows)} named projects from aqar.'
                     if offer_lang == 'en' else
                     f'قُرئت {len(aqar_rows)} مشاريع مسماة من عقار.')
        notes = f'{notes} — {aqar_note}' if notes else aqar_note
    elif aqar_handle:
        aqar_holder = aqar_handle.get('holder') or {}
        aqar_result = aqar_holder.get('result') or {}
        aqar_error = aqar_holder.get('error') or aqar_result.get('error') or ''
        if aqar_error:
            aqar_note = (f'Could not read aqar projects: {aqar_error}'
                         if offer_lang == 'en' else
                         f'تعذر قراءة مشاريع عقار: {aqar_error}')
        elif not aqar_result.get('cards'):
            aqar_note = ('The aqar projects page returned no projects for this city.'
                         if offer_lang == 'en' else
                         'لم تُعد صفحة مشاريع عقار أي مشروع لهذه المدينة.')
        elif not aqar_result.get('matched'):
            scope_mode = (payload.get('competitorScope') or {}).get('mode')
            if offer_lang == 'en':
                aqar_note = ('No aqar projects matched the selected axes'
                             + (' inside the selected district.'
                                if scope_mode == 'district' else '.'))
            else:
                aqar_note = ('لم تُطابق مشاريع عقار المحاور المختارة'
                             + (' داخل الحي المحدد.' if scope_mode == 'district'
                                else '.'))
        else:
            aqar_note = ''
        if aqar_note:
            notes = f'{notes} — {aqar_note}' if notes else aqar_note
    expansion_note = aggregate['notes']
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
    nothing_generated = not [row for row in generated or []
                             if isinstance(row, dict)
                             and str(row.get('name') or '').strip()]
    partial = (bool(provider_error) or bool(blocked_note) or not search_ran
               or no_evidence > 0 or missing_prices > 0 or nothing_generated)
    if nothing_generated and merged:
        kept_note = ('No new competitors were found; the existing rows were kept.'
                     if offer_lang == slide_engine.OFFER_LANG_ENGLISH else
                     'لم يُعثر على منافسين جدد؛ أُبقيت الصفوف الحالية.')
        notes = f'{notes} — {kept_note}' if notes else kept_note
    elif nothing_generated:
        place = (str(payload.get('district') or '').strip()
                 or str(payload.get('city') or '').strip())
        if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
            empty_note = ('No matching competitors were found'
                          + (f' in {place}.' if place
                             else ' in the selected scope.'))
        else:
            empty_note = ('لم يُعثر على منافسين مطابقين'
                          + (f' في «{place}».' if place
                             else ' في النطاق المحدد.'))
        notes = f'{notes} — {empty_note}' if notes else empty_note
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
        # Hotel price/area comes only from the deterministic Booking block.
        'fallbackCount': 0,
        'conflictWarnings': [warning for row in merged for warning in (row.get('conflict_warnings') or [])],
        'searchExpanded': round_no > 0,
        'comparisonTypes': payload.get('comparisonTypes') or [],
        'competitorScope': payload.get('competitorScope') or {},
        'transactionBenchmarks': payload.get('transactionBenchmarks') or {},
        'expansionNote': expansion_note,
        'notes': notes,
    }


# The whole summary job — source plan, parallel browser work and synthesis —
# gets three hours by default, with an environment override.
try:
    _SUMMARY_JOB_TIME_BUDGET = max(60, int(os.environ.get('SUMMARY_JOB_TIME_BUDGET') or 10800))
except (TypeError, ValueError):
    _SUMMARY_JOB_TIME_BUDGET = 10800

# The competitors sweep is wider still: roughly one search per plausible rival
# plus the market-level listings, each paired with page opens.
_COMPETITORS_SEARCH_BUDGET = 10
_COMPETITORS_MAX_STEPS = 20


def _execute_market_summary(data, tenant_id=None, progress=None,
                            resume_state=None, checkpoint=None,
                            trace_writer=None):
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
    if not (isinstance(resume_state, dict) and resume_state):
        _preload_failed_run_evidence(tenant_id, 'summary', data, evidence_pool)
    deadline = time.time() + _SUMMARY_JOB_TIME_BUDGET
    session = _market_browser_session(search_provider='searxng')
    try:
        result = _run_market_summary(
            data, tenant_id=tenant_id, progress=report,
            evidence_pool=evidence_pool, deadline=deadline, session=session,
            resume_state=resume_state, checkpoint=checkpoint,
            trace_writer=trace_writer)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    result = _attach_failure_evidence(result, evidence_pool)
    if callable(trace_writer):
        trace_writer({'event': 'summary_result', 'success': bool(result.get('success')),
                      'summary': result.get('summary'), 'sources': result.get('sources'),
                      'error': result.get('error'),
                      'failure_reason': result.get('failureReason')})
    return result


def _run_market_summary(data, tenant_id=None, progress=None,
                        evidence_pool=None, deadline=None, session=None,
                        resume_state=None, checkpoint=None, trace_writer=None):
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
    system_prompt += ('\n\nحلل دراسة السوق وفق الأنشطة والمكونات الاستثمارية المختارة للمشروع فقط. '
                      'اقصر القطاعات الأخرى على مؤشرات سياقية تخدم نشاطًا مختارًا بوضوح، ولا تنشئ لها تحليلًا مستقلًا.')
    training_context = (db.get_training_context(tenant_id, surface='content', offer_lang=offer_lang)
                        if tenant_id else '')
    if training_context:
        system_prompt += f"\n\n## بيانات خاصة بالشركة\n{training_context}"
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        system_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    if not payload['summaryScope'].get('cities'):
        return {'success': False,
                'error': 'حدد مدينة واحدة على الأقل لنطاق ملخص السوق.',
                'failureReason': 'summary_scope_required'}
    report(10, 'جاري فحص المصادر المرتبطة بأنشطة المشروع المختارة — قد يستغرق دقائق...')
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)
    usage_ctx['billing_flow'] = 'market_summary'
    reaggregate_only = bool(data.get('reaggregateOnly') or data.get('reaggregate_only'))
    cached_trace_job = str(data.get('jobId') or data.get('traceJobId') or '').strip()
    research = None
    if reaggregate_only:
        report(20, 'استرجاع أدلة البحث السابقة لإعادة التحليل...')
        trace_path = _find_market_research_trace_file(tenant_id, cached_trace_job)
        loaded_reports, loaded_citations = _load_market_research_trace_reports(trace_path)
        if loaded_reports:
            research = {'success': True, 'reports': loaded_reports, 'citation_urls': loaded_citations}
    if research is None:
        # Load known deep links and city datasets before model-led source research.
        _run_market_source_plan(payload, offer_lang=offer_lang,
                                evidence_pool=evidence_pool, session=session,
                                deadline=deadline, report=report)
        # Dispatch independent browser tasks for the selected activity and
        # geography; each researcher opens only its assigned relevant sources.
        research = _run_market_summary_research_with_booking(
            payload, usage_ctx, evidence_pool, deadline, report=report,
            offer_lang=offer_lang, resume_state=resume_state,
            checkpoint=checkpoint, trace_writer=trace_writer,
            data=data, tenant_id=tenant_id, session=session)
    if not research.get('success'):
        fatal = next((_ai_fatal_error_dict(item.get('result') or {})
                      for item in research.get('outcomes') or []
                      if _ai_fatal_error_dict(item.get('result') or {})), None)
        provider_error = ((fatal or {}).get('message')
                          or research.get('error')
                          or 'no researcher opened evidence')
        return {
            'success': False,
            'error': (provider_error if fatal else
                      'تعذر فتح أدلة ويب لملخص السوق. لم يُستبدل النص الحالي.'),
            'failureReason': 'insufficient_credit' if fatal else 'search_not_run',
            'providerError': provider_error,
            'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        }
    retrieved_evidence = market_study.format_retrieved_evidence_block(
        evidence_pool, offer_lang=offer_lang)
    researcher_block = json.dumps(research.get('reports') or [],
                                  ensure_ascii=False, indent=2, default=str)
    deterministic_evidence = str(
        payload.get('_summaryDeterministicEvidence') or '').strip()
    evidence_block = '\n\n'.join(part for part in
                                  (deterministic_evidence, retrieved_evidence,
                                   researcher_block) if part)
    user_prompt = market_study.build_summary_user_prompt(
        payload, competitors, current_summary, current_sources=current_sources, current_swot=current_swot,
        offer_lang=offer_lang, retrieved_evidence=evidence_block,
    )
    if offer_lang == slide_engine.OFFER_LANG_ENGLISH:
        user_prompt += '\n\n' + slide_engine.OFFER_LANGUAGE_DIRECTIVE_EN
    report(68, 'تجميع الأدلة وكتابة تحليل السوق الكامل')
    res = _run_market_summary_aggregator(
        system_prompt, user_prompt, usage_ctx, research, deadline=deadline)
    failed = res.get('error') is not None
    aggregator_returned_error = failed
    provider_error = _chat_error_message(res) if failed else ''
    if not failed and not _market_search_ran(res):
        provider_error = 'browse_agent: no browsed evidence'
        failed = True
    if failed and _ai_fatal_error_dict(res) is None:
        safe_provider_error = _client_safe_llm_error(
            provider_error,
            fallback='تعذر تحديد سبب تعذر تجميع نتائج البحث.')
        is_credit_failure = (_is_company_credit_error(provider_error)
                             or 'afford' in str(provider_error or '').lower())
        error = 'تعذر تجميع نتائج بحث الويب لملخص السوق. لم يُستبدل النص الحالي.'
        if safe_provider_error and safe_provider_error != error:
            error += f' السبب: {safe_provider_error}'
        return {
            'success': False,
            'error': error,
            'failureReason': ('insufficient_credit' if is_credit_failure
                              else 'aggregator_failed' if aggregator_returned_error
                              else 'search_not_run'),
            'providerError': safe_provider_error,
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
    # Two model rows can resolve to the same retrieved page; the register shows
    # each source once.
    sources = market_study.dedupe_source_rows(normalized.get('sources') or [])
    normalized['sources'] = sources
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
    market_study.flag_out_of_period_sources(
        sources, payload.get('summaryPeriodBounds') or payload.get('dataPeriodBounds'))
    return {
        'success': True,
        'searchVerified': search_verified,
        'searchStats': evidence_pool.stats() if evidence_pool is not None else None,
        **normalized,
    }


def _market_job_worker(app, tenant_id, kind, data, job_id, actor=None):
    with app.app_context():
        # The stop button reaches this study through the run registry; the
        # thread dies with the worker, so the handle cannot leak.
        run_control.bind_run(job_id, tenant_id)
        # ISS-033: helpers that read the caller identity from g (upload dir,
        # logo publish, audit) must see this job's tenant — an app context
        # starts empty, so the worker stamps it the way require_auth would.
        g.tenant_id = tenant_id
        if isinstance(actor, dict):
            g.user_id = actor.get('user_id')
            g.user_name = actor.get('user_name')
            g.user_role = actor.get('user_role')
        stored_job = _read_market_job(tenant_id, job_id) or {}
        resume_state = (stored_job.get('resumeState')
                        if isinstance(stored_job.get('resumeState'), dict) else {})
        _write_market_job(tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري البحث في المصادر الرسمية وإعداد النتائج...',
            'kind': kind,
            'resumeState': resume_state,
        })

        def stop_if_cancelled():
            """Leave at the next phase boundary, before the next paid step."""
            if not run_control.current_run_cancelled():
                return
            _write_market_job(tenant_id, job_id, {
                **run_control.cancelled_job_patch(), 'kind': kind,
            })
            raise run_control.RunCancelledError()

        def report(_pct, message):
            # The stage message is what the job publishes; the percentage the
            # workers compute for their own budget is not a measurement of the
            # study, so it must not reach the job document.
            stop_if_cancelled()
            _write_market_job(tenant_id, job_id, {
                'status': 'running',
                'success': True,
                'kind': kind,
                'message': str(message or '').strip() or 'جاري إعداد دراسة السوق...',
            })

        def checkpoint(state):
            nonlocal resume_state
            if not isinstance(state, dict):
                return
            resume_state = state
            _write_market_job(tenant_id, job_id, {
                'status': 'running', 'success': True, 'kind': kind,
                'message': 'حُفظ تقدم باحثي السوق المكتمل',
                'resumeState': resume_state,
            })

        try:
            if kind == 'competitors':
                payload = _execute_market_competitors(data, tenant_id, progress=report)
            elif kind == 'summary_chat':
                payload = _execute_market_summary_chat(data, tenant_id, progress=report)
            elif kind == 'summary_consolidate':
                payload = _execute_market_summary_consolidate(data, tenant_id, progress=report)
            elif kind == 'summary':
                try:
                    trace_writer = _market_research_trace_writer(tenant_id, job_id)
                except Exception as exc:
                    trace_writer = lambda *_args, **_kwargs: None
                    print(f'[MARKET SUMMARY] research trace unavailable: {exc}')
                trace_writer({
                    'event': 'market_study_job_started', 'job_id': job_id,
                    'resumed': bool(resume_state), 'started_at_epoch': time.time(),
                })
                payload = _execute_market_summary(
                    data, tenant_id, progress=report,
                    resume_state=resume_state, checkpoint=checkpoint,
                    trace_writer=trace_writer)
            else:
                payload = _execute_market_summary(data, tenant_id, progress=report)
            # A stop that landed after the executor's last report still wins:
            # the study is closed as cancelled, never published as a result
            # the client asked not to produce.
            if run_control.current_run_cancelled():
                _write_market_job(tenant_id, job_id, {
                    **run_control.cancelled_job_patch(), 'kind': kind,
                })
                return
            status = 'completed' if payload.get('success') else 'failed'
            _write_market_job(tenant_id, job_id, {
                **payload,
                'status': status,
                'kind': kind,
                'message': payload.get('error') or 'اكتملت دراسة السوق',
            })
        except Exception as exc:
            if (getattr(exc, 'error_code', None) == run_control.CANCELLED_ERROR_CODE
                    or run_control.current_run_cancelled()):
                _write_market_job(tenant_id, job_id, {
                    **run_control.cancelled_job_patch(), 'kind': kind,
                })
                return
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

