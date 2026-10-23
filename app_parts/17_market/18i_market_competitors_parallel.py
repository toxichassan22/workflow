
# ---------------------------------------------------------------------------
# Parallel competitor scans.
#
# One browse-agent call per comparison axis, all in flight together, plus a
# second complementary angle for a single-axis project and the known-sources
# plan running alongside them. The models are the slow stage — the whole job
# used to walk axis after axis, so a two-axis project paid two full scans and
# a one-axis project still waited for the source plan first. Verification is
# already parallel (one thread per row); this module parallelizes the scan.
# ---------------------------------------------------------------------------

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import hotel_stay


_PARALLEL_SCAN_WORKERS = 4


def _locked_report(report):
    lock = threading.Lock()

    def emit(pct, message=''):
        try:
            with lock:
                report(pct, message)
        except Exception:
            pass

    return emit


def _axis_scan_payload(payload, axis):
    """A payload whose only explicit comparison pick is this axis."""
    axis_type = str((axis or {}).get('type') or '')
    if axis_type == 'hotel':
        selection = [{'type': 'hotel', 'stars': [str(axis.get('stars') or '')]}]
    else:
        selection = [{
            'type': axis_type,
            'operation': [str(axis.get('operation') or '')],
        }]
    next_payload = dict(payload or {})
    next_payload['comparisonTypes'] = selection
    return next_payload


def _portals_focus_line(offer_lang='ar'):
    if offer_lang == 'en':
        return (
            '\n\nThis complementary pass focuses on detailed listing pages that '
            'currently offer units or hotel rooms (aqar.fm for residential and '
            'commercial, Booking.com for hotels), to catch named competitors that '
            'developer sites never list. Keep the same source, price and '
            'official-page rules.')
    return (
        '\n\nهذه الجولة التكميلية تركّز على صفحات الإعلانات والقوائم التفصيلية '
        'التي تعرض وحدات أو غرفًا فندقية معروضة فعليًا (عقار للسكني والتجاري، '
        'وBooking.com للفنادق) لالتقاط منافسين مسمّين لا تذكرهم مواقع المطورين. '
        'التزم بقواعد المصادر والأسعار والصفحة الرسمية نفسها.')


def _scan_search_limits(task_count):
    total_searches = max(4, int(_COMPETITORS_SEARCH_BUDGET))
    total_steps = max(10, int(_COMPETITORS_MAX_STEPS))
    per_task = max(1, task_count)
    return (
        max(4, total_searches // per_task),
        max(8, total_steps // per_task),
    )


def _run_single_competitor_scan(task, payload, existing, mode, offer_lang,
                                tenant_id, data, evidence_pool, deadline,
                                system_prompt, report, band, search_budget,
                                max_steps):
    """One axis (or one complementary angle) on its own browse-agent call.

    The worker owns the thread's browser and closes it in ``finally`` — a
    shared BrowserWorker is bound to the thread that opened it, so parallel
    scans must never share one.
    """
    axis_payload = (payload if task.get('kind') in ('fill', 'legacy')
                    else _axis_scan_payload(payload, task.get('axis')))
    prompt = market_study.build_competitors_user_prompt(
        axis_payload, existing, mode=mode, offer_lang=offer_lang)
    if task.get('kind') == 'portals':
        prompt += _portals_focus_line(offer_lang)
    label = task.get('label') or 'البحث عن المنافسين'
    lo, hi = band
    session = _market_browser_session(search_provider='searxng')
    try:
        with _worker_app_context():
            response = _browse_agent_call(
                system_prompt, prompt,
                _usage_ctx('market', data, tenant_id=tenant_id),
                search_provider='searxng',
                evidence_pool=evidence_pool, deadline=deadline,
                session=session,
                search_budget=search_budget, max_steps=max_steps,
                max_tokens=14000, reasoning_effort='low',
                on_event=_market_agent_progress(report, lo, hi, label))
    except Exception as exc:
        return {
            'task': task, 'reply': None, 'parsed': {}, 'parse_error': '',
            'provider_error': f'browse_agent: {exc}', 'search_ran': False,
        }
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    provider_error = _chat_error_message(response) if isinstance(response, dict) and response.get('error') else ''
    parsed, parse_error = (_parse_market_model_json(response)
                           if isinstance(response, dict) else ({}, 'empty_response'))
    return {
        'task': task,
        'reply': response if isinstance(response, dict) else None,
        'parsed': parsed if isinstance(parsed, dict) else {},
        'parse_error': parse_error or '',
        'provider_error': provider_error or '',
        'search_ran': bool(isinstance(response, dict) and _market_search_ran(response)),
    }


def _run_scan_tasks(tasks, payload, existing, mode, offer_lang, tenant_id,
                    data, evidence_pool, deadline, system_prompt, report,
                    band=(22, 40)):
    if not tasks:
        return []
    report = _locked_report(report)
    search_budget, max_steps = _scan_search_limits(len(tasks))
    workers = min(_PARALLEL_SCAN_WORKERS, len(tasks)) or 1
    results = [None] * len(tasks)
    done = [0]
    total = len(tasks)
    lo, hi = band

    def _task_band(index):
        start = lo + int((hi - lo) * index / total)
        end = lo + int((hi - lo) * (index + 1) / total)
        return start, max(start + 1, end)

    with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix='market-scan') as workers_pool:
        future_map = {}
        for index, task in enumerate(tasks):
            future = workers_pool.submit(
                _run_single_competitor_scan, task, payload, existing, mode,
                offer_lang, tenant_id, data, evidence_pool, deadline,
                system_prompt, report, _task_band(index), search_budget,
                max_steps)
            future_map[future] = index
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    'task': tasks[index], 'reply': None, 'parsed': {},
                    'parse_error': '', 'provider_error': str(exc),
                    'search_ran': False,
                }
            results[index] = result
            done[0] += 1
            task = tasks[index]
            report(
                lo + int((hi - lo) * done[0] / total),
                f'اكتمل {task.get("label") or "بحث المحور"} '
                f'({done[0]} من {total})...')
    return [item for item in results if isinstance(item, dict)]


def _competitor_scan_tasks(axes, offer_lang='ar', mode='generate'):
    """One task per axis; a lone axis also gets a portal-focused twin."""
    if mode == 'fill':
        return [{'kind': 'fill', 'axis': None, 'label': 'إكمال بيانات المنافسين'}]
    if not any(axis.get('explicit') for axis in axes or []):
        # A legacy request without explicit comparison picks has one broad
        # table to build — no per-axis payload to filter.
        return [{'kind': 'legacy', 'axis': None, 'label': 'البحث عن المنافسين'}]
    tasks = []
    for axis in axes or []:
        tasks.append({
            'kind': 'axis',
            'axis': axis,
            'label': 'البحث عن ' + market_study.benchmark_axis_label(axis, offer_lang),
        })
    if len(tasks) == 1:
        tasks.append({
            'kind': 'portals',
            'axis': tasks[0]['axis'],
            'label': 'البحث التكميلي عن ' + market_study.benchmark_axis_label(
                tasks[0]['axis'], offer_lang),
        })
    return tasks


def _expansion_scan_tasks(payload, axes, deficits, named_generated,
                          offer_lang='ar', multi_axis=False,
                          needs_benchmarks=False, evidence_pool=None):
    """Targeted tasks for axes still short of the minimum, one per axis."""
    if not deficits:
        return []
    scope = market_study.competitor_scope_text(payload)
    city = str((payload or {}).get('city') or '')
    district = str((payload or {}).get('district') or '')
    ptype = str((payload or {}).get('projectType')
                or (payload or {}).get('project_type') or 'عقاري')
    axis_label_list = '، '.join(
        market_study.benchmark_axis_label(axis, offer_lang) for axis in axes)
    known = '، '.join(str(row.get('name') or '') for row in named_generated or []) or 'لا يوجد'
    distance_field = (
        ', "distance_km":"المسافة الموثقة من موقع المشروع بالكيلومتر"'
        if (payload or {}).get('competitorScope', {}).get('mode') == 'distance' else '')
    tasks = []
    for axis in deficits:
        angle = (f'{axis["search"]} داخل {scope} في {city}'
                 + (' عبر Booking.com' if axis.get('type') == 'hotel' else ''))
        if evidence_pool is not None and _pool_covers_angle(evidence_pool, angle):
            continue
        target_label = market_study.benchmark_axis_label(axis, offer_lang)
        priority = (f'أولوية هذه الجولة اختيار العميل «{target_label}» فقط. '
                    'لا تضف أنواعًا أو عمليات أخرى.')
        hotel_source_rule = (
            'لأن هذا محور فندقي، استخدم صفحات Booking.com فقط ولا تضع روابط فنادق من أي نطاق آخر. '
            if axis.get('type') == 'hotel' else '')
        hotel_stay_rule = ''
        if axis.get('type') == 'hotel':
            check_in, check_out = hotel_stay.booking_stay_window()
            hotel_stay_rule = (
                f'افتح كل صفحة فندق بتواريخ الإقامة من {check_in.isoformat()} إلى '
                f'{check_out.isoformat()}، غرفة واحدة، بالغان، دون أطفال، بالعملة SAR؛ '
                'أضف معاملات checkin وcheckout وgroup_adults=2 وgroup_children=0 '
                'وno_rooms=1 وselected_currency=SAR إلى الرابط، واضغط «عرض الأسعار» '
                'إن بقيت الأسعار مخفية. اقرأ مساحة الغرفة بالمتر المربع من تفاصيل الغرفة، '
                'ولا تستخدم مساحة الفندق أو البرج أو الأرض. '
            )
        prompt = (
            f'نُجري دراسة سوق لمشروع {ptype} في {city}'
            + (f' — {district}' if district else '')
            + f'. نطاق المنافسين: {scope}.\n'
            + 'انسخ city وdistrict حرفيًا من بيانات المشروع؛ في نطاق الحي لا تذكر حيًا آخر.\n'
            + f'المنافسون المسجلون حتى الآن: {known}.\n'
            + f'ابحث عبر SearXNG عن: {angle} — مشاريع مسماة '
              'حقيقية لم ترد في القائمة. لا تُدرج صفحات مؤشرات أو إحصاءات كمنافس.\n'
            + (priority + '\n' if priority else '')
            + (f'قيم benchmarks المسموحة حصرًا: {axis_label_list}.\n'
               if needs_benchmarks else '')
            + hotel_source_rule
            + hotel_stay_rule
            + 'أعد JSON فقط: {"competitors":[{"name":"","city":"انسخ المدينة من بيانات المشروع حرفيًا",'
              '"district":"","hotel_stars":"",'
              '"benchmarks":[],"operation_type":"","price_type":"","price_currency":"",'
              '"price":"","source_urls":[]' + distance_field + '}]} '
              'مع بقية الحقول المعتادة عند توفرها.'
              + (' Write every field value in English using the allowed English enum '
                 'values (status: Operating/Under Construction/Off-Plan; classification: '
                 'Direct/Indirect/Benchmark; operation_type: Sale/Rent/Hotel Operation/Other).'
                 if offer_lang == 'en' else ''))
        tasks.append({
            'kind': 'expansion',
            'axis': axis,
            'label': 'بحث إضافي عن ' + target_label,
            'prompt': prompt,
        })
    return tasks


def _run_expansion_scan_task(task, payload, existing, mode, offer_lang,
                             tenant_id, data, evidence_pool, deadline,
                             system_prompt, report, band, search_budget,
                             max_steps):
    prompt = task.get('prompt') or market_study.build_competitors_user_prompt(
        _axis_scan_payload(payload, task.get('axis')), existing,
        mode=mode, offer_lang=offer_lang)
    lo, hi = band
    session = _market_browser_session(search_provider='searxng')
    try:
        with _worker_app_context():
            response = _browse_agent_call(
                system_prompt, prompt,
                _usage_ctx('market', data, tenant_id=tenant_id),
                search_provider='searxng',
                evidence_pool=evidence_pool, deadline=deadline,
                session=session,
                search_budget=search_budget, max_steps=max_steps,
                max_tokens=14000, reasoning_effort='low',
                on_event=_market_agent_progress(report, lo, hi,
                                                task.get('label') or 'بحث إضافي'))
    except Exception as exc:
        return {
            'task': task, 'reply': None, 'parsed': {}, 'parse_error': '',
            'provider_error': f'browse_agent: {exc}', 'search_ran': False,
        }
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    provider_error = _chat_error_message(response) if isinstance(response, dict) and response.get('error') else ''
    parsed, parse_error = (_parse_market_model_json(response)
                           if isinstance(response, dict) else ({}, 'empty_response'))
    return {
        'task': task,
        'reply': response if isinstance(response, dict) else None,
        'parsed': parsed if isinstance(parsed, dict) else {},
        'parse_error': parse_error or '',
        'provider_error': provider_error or '',
        'search_ran': bool(isinstance(response, dict) and _market_search_ran(response)),
    }


def _run_parallel_expansions(tasks, payload, existing, mode, offer_lang,
                             tenant_id, data, evidence_pool, deadline,
                             system_prompt, report, band=(40, 52)):
    if not tasks:
        return []
    report = _locked_report(report)
    search_budget = max(3, int(_COMPETITORS_SEARCH_BUDGET) // max(1, len(tasks) + 2))
    max_steps = max(8, int(_COMPETITORS_MAX_STEPS) // max(1, len(tasks) + 1))
    workers = min(_PARALLEL_SCAN_WORKERS, len(tasks)) or 1
    results = [None] * len(tasks)
    done = [0]
    total = len(tasks)
    lo, hi = band

    def _task_band(index):
        start = lo + int((hi - lo) * index / total)
        end = lo + int((hi - lo) * (index + 1) / total)
        return start, max(start + 1, end)

    with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix='market-expand') as workers_pool:
        future_map = {}
        for index, task in enumerate(tasks):
            future = workers_pool.submit(
                _run_expansion_scan_task, task, payload, existing, mode,
                offer_lang, tenant_id, data, evidence_pool, deadline,
                system_prompt, report, _task_band(index), search_budget,
                max_steps)
            future_map[future] = index
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = {
                    'task': tasks[index], 'reply': None, 'parsed': {},
                    'parse_error': '', 'provider_error': str(exc),
                    'search_ran': False,
                }
            done[0] += 1
            report(
                lo + int((hi - lo) * done[0] / total),
                f'اكتمل البحث الإضافي ({done[0]} من {total})...')
    return [item for item in results if isinstance(item, dict)]


def _start_source_plan_async(payload, offer_lang, evidence_pool, deadline,
                             report, session=None, market_wide=False):
    """Run the known-sources plan beside the scans instead of before them.

    It keeps the job's shared browser (the scans own their own), so the plan
    still reaches the pages a plain HTTP read cannot and the job closes that
    session once, after every stage.
    """
    if evidence_pool is None:
        return None

    def _worker():
        try:
            with _worker_app_context():
                kwargs = dict(
                    offer_lang=offer_lang,
                    evidence_pool=evidence_pool,
                    session=session,
                    deadline=deadline,
                    report=report)
                if market_wide:
                    kwargs['market_wide'] = True
                _run_market_source_plan(payload, **kwargs)
        except Exception as exc:
            print(f'[MARKET STUDY] parallel source plan failed: {exc}')

    thread = threading.Thread(target=_worker, name='market-source-plan', daemon=True)
    thread.start()
    return thread


def _await_source_plan(thread, timeout=None):
    if thread is None:
        return
    thread.join(timeout=timeout)


def _aggregate_scan_results(results):
    """Combine parallel replies: rows, citations source, note and errors."""
    usable = [item for item in results or []
              if isinstance(item, dict) and item.get('parsed')]
    provider_error = next(
        (str(item.get('provider_error') or '').strip()
         for item in results or []
         if str(item.get('provider_error') or '').strip()), '')
    parse_error = '' if usable else next(
        (str(item.get('parse_error') or '').strip()
         for item in results or []
         if str(item.get('parse_error') or '').strip()), '')
    notes = []
    for item in usable:
        note = str((item.get('parsed') or {}).get('notes') or '').strip()
        if note and note not in notes:
            notes.append(note)
    competitors = []
    for item in usable:
        rows = (item.get('parsed') or {}).get('competitors')
        if isinstance(rows, list):
            competitors.extend(row for row in rows if isinstance(row, dict))
    return {
        'usable': usable,
        'competitors': competitors,
        'notes': ' — '.join(notes),
        'provider_error': provider_error,
        'parse_error': parse_error,
        'search_ran': any(item.get('search_ran') for item in results or []),
    }
