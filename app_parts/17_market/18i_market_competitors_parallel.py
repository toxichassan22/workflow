
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

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import booking_destination
import booking_rooms
import booking_search
import hotel_stay
import maps_service
from numeric_precision import format_precise_number


_PARALLEL_SCAN_WORKERS = 4
# One competitor phase must finish inside the client's five-minute budget; a
# scan that keeps searching past it is cost with no result.
_MARKET_SCAN_BUDGET_SECONDS = float(
    os.environ.get('MARKET_SCAN_BUDGET_SECONDS') or 240)
# A radius scope has to look past the first few cards to prove what sits inside
# it. Ten property pages in batches of five cost roughly a minute of the scan
# budget and still leave room for the district and verification stages.
_BOOKING_SCAN_MAX_HOTELS = max(
    5, int(os.environ.get('BOOKING_SCAN_MAX_HOTELS') or 10))
_BOOKING_SCAN_TAB_BATCH = max(1, int(
    os.environ.get('BOOKING_SCAN_TAB_BATCH') or 5))


def _scan_deadline(deadline):
    """The job deadline, capped by the competitor phase's own budget."""
    latest = time.time() + _MARKET_SCAN_BUDGET_SECONDS
    try:
        if deadline is not None:
            return min(float(deadline), latest)
    except (TypeError, ValueError):
        pass
    return latest


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
        selection = [{'type': 'hotel'}]
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
    per_task = max(1, min(task_count, 2))
    return (
        max(4, int(_COMPETITORS_SEARCH_BUDGET) // per_task),
        max(14, int(_COMPETITORS_MAX_STEPS) // per_task),
    )


def _project_coordinates(payload, data=None):
    sources = []
    for source in (payload, data):
        if isinstance(source, dict):
            sources.append(source)
            for key in ('projectData', 'project_data', 'fields', 'draft_data'):
                nested = source.get(key)
                if isinstance(nested, dict):
                    sources.append(nested)

    def first_number(keys):
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value is not None and str(value).strip():
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
        return None

    return (first_number(('location_lat', 'locationLat', 'lat', 'latitude')),
            first_number(('location_lng', 'locationLng', 'lng', 'longitude')))


def _native_fallback_needed(result):
    """True when the local search layer never ran or was blocked; a searched
    empty market is a real answer and must not trigger the paid fallback."""
    if not isinstance(result, dict):
        return True
    if result.get('search_blocked') or result.get('pages_blocked'):
        return True
    if result.get('provider_error'):
        return True
    if not result.get('search_ran'):
        return True
    return False


def _native_fallback_prompt(prompt_or_task, task_or_payload=None, payload_or_lang=None, offer_lang='ar'):
    if isinstance(prompt_or_task, dict):
        task = prompt_or_task
        payload = task_or_payload or {}
        lang = payload_or_lang or offer_lang or 'ar'
    else:
        task = task_or_payload or {}
        payload = payload_or_lang or {}
        lang = offer_lang or 'ar'
    offer_lang = lang
    axis = (task or {}).get('axis') if isinstance((task or {}).get('axis'), dict) else {}
    city = str((payload or {}).get('city') or 'جدة').strip()
    scope = (payload or {}).get('competitorScope') or (payload or {}).get('competitor_scope') or {}
    districts = market_study.competitor_scope_districts(
        scope, (payload or {}).get('district') or (payload or {}).get('neighborhood'))
    districts_str = '، '.join(districts) if districts else str((payload or {}).get('district') or '')
    axis_label = market_study.benchmark_axis_label(axis, offer_lang) if axis else str((task or {}).get('label') or 'المنافسين')
    project_type = str(axis.get('type') or axis.get('base') or 'سكني').strip()
    operation_type = str(axis.get('operation') or 'بيع').strip()

    all_unit_types = market_study.competitor_scope_unit_types(scope)
    res_opts = getattr(market_study, 'RESIDENTIAL_UNIT_TYPES', ())
    com_opts = getattr(market_study, 'COMMERCIAL_UNIT_TYPES', ())
    if project_type in ('سكني', 'residential'):
        matching_units = [u for u in all_unit_types if u in res_opts] or all_unit_types
    elif project_type in ('تجاري', 'commercial'):
        matching_units = [u for u in all_unit_types if u in com_opts] or all_unit_types
    else:
        matching_units = all_unit_types

    if offer_lang == 'en':
        units_clause_en = (
            f"Required property or unit types strictly: {', '.join(matching_units)} (exclude other property types).\n"
            if matching_units else ""
        )
        search_scope_en = (
            f"developments, compounds, or listings for ({', '.join(matching_units)})"
            if matching_units else
            f"developments, compounds, or listings matching '{axis_label}'"
        )
        default_unit_en = matching_units[0] if matching_units else "unit type"
        return (
            f"Identify real competitors for a real estate project in {city} matching '{axis_label}'.\n"
            f"Target neighborhoods: {districts_str or city}.\n"
            f"{units_clause_en}"
            f"Search the web for real {search_scope_en} in these specific neighborhoods or in {city}.\n"
            f"Assign the exact neighborhood to the 'district' field.\n"
            f"Respond STRICTLY with JSON formatted as:\n"
            "{\n"
            '  "competitors": [\n'
            "    {\n"
            '      "name": "Project, compound, or listing name",\n'
            f'      "city": "{city}",\n'
            '      "district": "Neighborhood name",\n'
            f'      "project_type": "{project_type}",\n'
            f'      "operation_type": "{operation_type}",\n'
            f'      "unit_type": "{default_unit_en}",\n'
            '      "price_type": "unit price or price per sqm or rent",\n'
            '      "price_value": "price as number or string",\n'
            '      "area_sqm": "area in sqm as number or string",\n'
            '      "status": "active, under construction, or off-plan",\n'
            '      "classification": "مباشر",\n'
            '      "source": "source URL or portal name"\n'
            "    }\n"
            "  ],\n"
            '  "notes": "documentation notes"\n'
            "}\n"
            "List 3 to 5 real competitors with prices and areas instead of returning an empty list."
        )

    units_clause_ar = (
        f"نوع العقار أو الوحدات المطلوبة حصراً: {' أو '.join(matching_units)} (استبعد أي أنواع عقارية أخرى مختلفة مثل الشقق أو الأراضي).\n"
        if matching_units else ""
    )
    search_scope_ar = (
        f"عروض أو مشاريع لوحدات ({' أو '.join(matching_units)})"
        if matching_units else
        f"مشاريع حقيقية أو مجمعات أو عروض معلنة تطابق «{axis_label}»"
    )
    default_unit_ar = matching_units[0] if matching_units else "نوع الوحدة"
    return (
        f"المطلوب حصر منافسين لمشروع عقاري في {city} ({axis_label}).\n"
        f"نطاق الأحياء المستهدفة: {districts_str or city}.\n"
        f"{units_clause_ar}"
        f"ابحث في الويب عن {search_scope_ar} في هذه الأحياء بالتحديد أو في {city}.\n"
        f"يجب كتابة اسم الحي في حقل 'district' مطابقاً لأحد الأحياء المستهدفة كلما أمكن.\n"
        "أعد الناتج بتنسيق JSON حصراً بالشكل التالي:\n"
        "{\n"
        '  "competitors": [\n'
        "    {\n"
        '      "name": "اسم المشروع أو المجمع أو البرج أو وصف العقار المعلن",\n'
        f'      "city": "{city}",\n'
        '      "district": "اسم الحي",\n'
        f'      "project_type": "{project_type}",\n'
        f'      "operation_type": "{operation_type}",\n'
        f'      "unit_type": "{default_unit_ar}",\n'
        '      "price_type": "سعر الوحدة أو سعر المتر أو الإيجار السنوي",\n'
        '      "price_value": "السعر كرقم أو نص",\n'
        '      "area_sqm": "المساحة بالمتر المربع كرقم أو نص",\n'
        '      "status": "قائم أو تحت الإنشاء أو على الخارطة",\n'
        '      "classification": "مباشر",\n'
        '      "source": "رابط المصدر أو اسم الموقع"\n'
        "    }\n"
        "  ],\n"
        '  "notes": "ملاحظات توثيقية عن المشاريع والأسعار المسترجعة"\n'
        "}\n"
        "اذكر من 3 إلى 5 منافسين حقيقيين مع أسعارهم ومساحاتهم ومصادرهم بدلاً من إرجاع قائمة فارغة."
    )


def _native_search_fallback(system_prompt, prompt, usage_ctx, evidence_pool,
                            deadline, search_budget=3, max_steps=6,
                            task=None, payload=None, offer_lang='ar'):
    """One provider-native OpenRouter web search when the browser search layer
    is blocked. The owner ordered this fallback for genuinely refused search
    engines; it runs on MARKET_STUDY_MODEL, never a model of its own."""
    try:
        clean_sys = (
            "You are a real estate market research expert in Saudi Arabia. Always respond with JSON only."
            if offer_lang == 'en' else
            "أنت خبير دراسات سوق عقاري في المملكة العربية السعودية. أجب دائمًا بتنسيق JSON فقط."
        )
        # The fallback talks to the provider directly, so it must carry the
        # company's own market training just like the regular browse path. The
        # scan thread has no request/app context, so the block is carried from
        # the already-built system prompt instead of reading the database here.
        marker = '## بيانات خاصة بالشركة'
        if marker in str(system_prompt or ''):
            clean_sys += "\n\n" + marker + str(system_prompt).split(marker, 1)[1]
        else:
            tenant_id = (usage_ctx or {}).get('tenant_id') if isinstance(usage_ctx, dict) else None
            if tenant_id:
                try:
                    import db as _training_db
                    training_context = _training_db.get_training_context(
                        tenant_id, surface='content', offer_lang=offer_lang)
                    if training_context:
                        clean_sys += "\n\n" + marker + "\n" + training_context
                except Exception:
                    pass
        effective_prompt = _native_fallback_prompt(
            task, payload, offer_lang=offer_lang) if task else prompt
        response = _browse_agent_call(
            clean_sys, effective_prompt, usage_ctx,
            evidence_pool=evidence_pool, deadline=deadline,
            local_tools=False,
            plugins=[{'id': 'web', 'max_results': 5}],
            search_budget=search_budget, max_steps=max_steps,
            max_tokens=14000, reasoning_effort=TEXT_REASONING_EFFORT)
    except Exception as exc:
        print(f'[MARKET STUDY] native search fallback failed: {exc}',
              flush=True)
        return None
    if not isinstance(response, dict) or response.get('error'):
        return None
    parsed, parse_error = _parse_market_model_json(response)
    rows = (parsed or {}).get('competitors')
    if not isinstance(rows, list) or not rows:
        return None
    axis = (task or {}).get('axis') if isinstance((task or {}).get('axis'), dict) else {}
    scope = (payload or {}).get('competitorScope') or (payload or {}).get('competitor_scope') or {}
    all_unit_types = market_study.competitor_scope_unit_types(scope)
    res_opts = getattr(market_study, 'RESIDENTIAL_UNIT_TYPES', ())
    com_opts = getattr(market_study, 'COMMERCIAL_UNIT_TYPES', ())
    p_type = str(axis.get('type') or axis.get('base') or '').strip()
    if p_type in ('سكني', 'residential'):
        matching_units = [u for u in all_unit_types if u in res_opts] or all_unit_types
    elif p_type in ('تجاري', 'commercial'):
        matching_units = [u for u in all_unit_types if u in com_opts] or all_unit_types
    else:
        matching_units = all_unit_types

    for row in rows:
        if isinstance(row, dict):
            if axis.get('type') and not row.get('project_type'):
                row['project_type'] = 'سكني' if axis.get('type') == 'residential' else 'تجاري'
            if axis.get('operation') and not row.get('operation_type'):
                row['operation_type'] = 'بيع' if axis.get('operation') == 'sale' else 'إيجار'
            if matching_units and not row.get('unit_type'):
                row_name = str(row.get('name') or '')
                found_u = next((u for u in matching_units if u in row_name), None)
                row['unit_type'] = found_u or matching_units[0]
            if not row.get('city') and (payload or {}).get('city'):
                row['city'] = (payload or {}).get('city')
            if not row.get('classification'):
                row['classification'] = 'مباشر'
            if not row.get('status'):
                row['status'] = 'قائم'
            if row.get('source') and not row.get('source_url'):
                m = re.search(r'\((https?://[^\s)]+)\)', str(row['source']))
                if m:
                    row['source_url'] = m.group(1)
                elif str(row['source']).startswith('http'):
                    row['source_url'] = str(row['source'])
            if row.get('source_url') and not row.get('source_urls'):
                row['source_urls'] = [row['source_url']]
    return {
        'task': None,
        'reply': response,
        'parsed': parsed,
        'parse_error': '',
        'provider_error': '',
        'search_ran': True,
    }


def _run_single_competitor_scan(task, payload, existing, mode, offer_lang,
                                tenant_id, data, evidence_pool, deadline,
                                system_prompt, report, band, search_budget,
                                max_steps):
    """One axis (or one complementary angle) on its own browse-agent call.

    The worker owns the thread's browser and closes it in ``finally`` — a
    shared BrowserWorker is bound to the thread that opened it, so parallel
    scans must never share one.
    """
    axis = task.get('axis') if isinstance(task.get('axis'), dict) else {}
    deadline = _scan_deadline(deadline)
    if task.get('kind') == 'axis' and str(axis.get('type') or '') == 'hotel':
        return _booking_hotel_scan(
            task, payload, data, tenant_id=tenant_id,
            offer_lang=offer_lang, deadline=deadline)
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
                max_tokens=14000, reasoning_effort=TEXT_REASONING_EFFORT,
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
    search_blocked = bool(session is not None and getattr(session, 'search_blocked', False))
    pages_blocked = bool(session is not None and getattr(session, 'pages_blocked', False))
    search_ran = bool(isinstance(response, dict) and _market_search_ran(response))
    if search_blocked or pages_blocked:
        search_ran = False
    result = {
        'task': task,
        'reply': response if isinstance(response, dict) else None,
        'parsed': parsed if isinstance(parsed, dict) else {},
        'parse_error': parse_error or '',
        'provider_error': provider_error or '',
        'search_ran': search_ran,
        'search_blocked': search_blocked,
        'pages_blocked': pages_blocked,
    }
    competitor_count = len(parsed.get('competitors') or []) if isinstance(parsed, dict) else 0
    if (str(task.get('kind') or '') != 'fill'
            and (_native_fallback_needed(result)
                 or (competitor_count < 2 and str(task.get('kind') or '') == 'axis'))):
        fallback_deadline = max(float(deadline or 0), time.time() + 30.0)
        fallback = _native_search_fallback(
            system_prompt, prompt,
            _usage_ctx('market', data, tenant_id=tenant_id),
            evidence_pool, fallback_deadline, search_budget=3, max_steps=6,
            task=task, payload=payload, offer_lang=offer_lang)
        fallback_count = len((fallback or {}).get('parsed', {}).get('competitors') or [])
        if fallback and fallback_count > competitor_count:
            fallback['task'] = task
            print(f'[MARKET STUDY] native search fallback used for '
                  f'{task.get("label") or "scan"} (found {fallback_count} vs {competitor_count})',
                  flush=True)
            result = fallback
    return result


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
    if len(tasks) == 1 and str(
            (tasks[0].get('axis') or {}).get('type') or '') != 'hotel':
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
    scope_raw = payload.get('competitorScope') or payload.get('competitor_scope')
    districts_list = market_study.competitor_scope_districts(scope_raw, district)
    for axis in deficits:
        if str((axis or {}).get('type') or '') == 'hotel':
            continue
        if len(districts_list) > 1:
            dist_phrase = ' أو '.join(f'حي {d}' for d in districts_list[:3])
            angle = f'{axis["search"]} في {dist_phrase} بمدينة {city}'
        else:
            angle = (f'{axis["search"]} داخل {scope} في {city}'
                     + (' عبر Booking.com' if axis.get('type') == 'hotel' else ''))
        if evidence_pool is not None and _pool_covers_angle(evidence_pool, angle):
            continue
        target_label = market_study.benchmark_axis_label(axis, offer_lang)
        priority = (f'أولوية هذه الجولة اختيار العميل «{target_label}» فقط. '
                    'لا تضف أنواعًا أو عمليات أخرى.')
        hotel_source_rule = (
            'لأن هذا محور فندقي، استخدم صفحات Booking.com فقط ولا تضع روابط فنادق من أي نطاق آخر. '
            'إذا أعادت صفحة الفندق تحديًا أمنيًا أو نسخة بوت بلا أسعار، لا تُعد المحاولة؛ '
            'أعد الصف بدون سعر ومساحة أو اذكر أنه غير موثق. '
            if axis.get('type') == 'hotel' else '')
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
            + 'أعد JSON فقط: {"competitors":[{"name":"","city":"انسخ المدينة من بيانات المشروع حرفيًا",'
              '"district":"",'
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
                max_tokens=14000, reasoning_effort=TEXT_REASONING_EFFORT,
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
    search_blocked = bool(session is not None and getattr(session, 'search_blocked', False))
    pages_blocked = bool(session is not None and getattr(session, 'pages_blocked', False))
    search_ran = bool(isinstance(response, dict) and _market_search_ran(response))
    if search_blocked or pages_blocked:
        search_ran = False
    result = {
        'task': task,
        'reply': response if isinstance(response, dict) else None,
        'parsed': parsed if isinstance(parsed, dict) else {},
        'parse_error': parse_error or '',
        'provider_error': provider_error or '',
        'search_ran': search_ran,
        'search_blocked': search_blocked,
        'pages_blocked': pages_blocked,
    }
    competitor_count = len(parsed.get('competitors') or []) if isinstance(parsed, dict) else 0
    if _native_fallback_needed(result) or competitor_count < 2:
        fallback = _native_search_fallback(
            system_prompt, prompt,
            _usage_ctx('market', data, tenant_id=tenant_id),
            evidence_pool, deadline, search_budget=3, max_steps=6,
            task=task, payload=payload, offer_lang=offer_lang)
        fallback_count = len((fallback or {}).get('parsed', {}).get('competitors') or [])
        if fallback and fallback_count > competitor_count:
            fallback['task'] = task
            print(f'[MARKET STUDY] native search fallback used for '
                  f'{task.get("label") or "expansion"}', flush=True)
            result = fallback
    return result


def _run_parallel_expansions(tasks, payload, existing, mode, offer_lang,
                             tenant_id, data, evidence_pool, deadline,
                             system_prompt, report, band=(40, 52)):
    if not tasks:
        return []
    report = _locked_report(report)
    search_budget = max(4, int(_COMPETITORS_SEARCH_BUDGET) // max(1, min(len(tasks), 2)))
    max_steps = max(12, int(_COMPETITORS_MAX_STEPS) // max(1, min(len(tasks), 2)))
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
