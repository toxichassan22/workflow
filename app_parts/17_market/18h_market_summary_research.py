"""Parallel, evidence-first research and Argon synthesis for market summaries."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote


_SUMMARY_RESEARCH_GROUPS = (
    {
        'key': 'transactions_and_rents',
        'label': 'الصفقات والإيجارات والمؤشرات العقارية',
        'hosts': {'rega.gov.sa', 'sakani.sa', 'ejar.sa', 'rer.sa', 'moj.gov.sa',
                  'aqar.fm', 'bayut.sa', 'wasalt.sa', 'dealapp.sa'},
        'focus': ('REGA city indicators and transaction activity; Sakani detailed rental indicators; '
                  'Ejar and available official records; current residential, commercial and industrial '
                  'asking listings. Separate realized transaction values from advertised asking prices.'),
    },
    {
        'key': 'development_and_supply',
        'label': 'المعروض والمشروعات والتخطيط',
        'hosts': {'momah.gov.sa', 'balady.gov.sa', 'nhc.sa', 'sbc.gov.sa'},
        'focus': ('Current and pipeline supply, licensed off-plan projects, permits and planning, '
                  'official city/developer project announcements, delivery timing, and type/use where '
                  'published. Do not treat announcements as delivered stock.'),
    },
    {
        'key': 'hospitality_and_tourism',
        'label': 'السياحة والفنادق والضيافة',
        'hosts': {'mt.gov.sa', 'str.com', 'costar.com', 'gaca.gov.sa'},
        'focus': ('Ministry of Tourism and GASTAT performance reports, visitor flows and seasonality, '
                  'airport traffic, licensed establishments, rooms, occupancy, ADR and RevPAR when '
                  'published; city-level tourism events and hotel supply. Booking pages may compare a '
                  'specific date and property only, never annual performance.'),
    },
    {
        'key': 'economy_commercial_industrial',
        'label': 'الاقتصاد والتجاري والصناعة واللوجستيات',
        'hosts': {'stats.gov.sa', 'open.data.gov.sa', 'sama.gov.sa', 'mc.gov.sa',
                  'mim.gov.sa', 'modon.gov.sa', 'ecza.gov.sa', 'mawani.gov.sa',
                  'mot.gov.sa'},
        'focus': ('Population, households, businesses and purchasing capacity; office and retail demand; '
                  'industrial licenses and activity, industrial cities, special economic zones, ports, '
                  'freight and transport links. Label every metric city, region or national.'),
    },
    {
        'key': 'professional_and_city_context',
        'label': 'التقارير المهنية والمصادر الرسمية المساندة',
        'hosts': set(),
        'focus': ('Use every remaining source category from the market source catalog, including official '
                  'project/developer/operator pages, Tadawul, CBRE, JLL, Knight Frank, Colliers, Savills, '
                  'ValuStrat, Deloitte, PwC, KPMG, EY, SPA, municipal pages and location services. Use '
                  'maps only for city context/accessibility, never as a price or transaction source.'),
    },
)

_SUMMARY_RESEARCH_MAX_WORKERS = 100
_SUMMARY_RESEARCH_MAX_STEPS = 24
_SUMMARY_RESEARCH_SEARCH_BUDGET = 8
_SUMMARY_RESEARCH_REQUIRED_URLS = {
    'rei.rega.gov.sa': [
        'https://rei.rega.gov.sa',
        'https://rei.rega.gov.sa/ar/advanced-search',
        'https://rei.rega.gov.sa/ar/advanced-search/deals',
        'https://rei.rega.gov.sa/ar/advanced-search/live',
        'https://rei.rega.gov.sa/ar/advanced-search/rental-market/detailed-indicator',
        'https://rei.rega.gov.sa/ar/advanced-search/rental-market/comparison',
        'https://rei.rega.gov.sa/ar/advanced-search/ads-supply-market',
    ],
    'sakani.sa': ['https://sakani.sa/reports-and-data'],
}


def _summary_research_sources_by_group():
    lines = [line for tier_lines in market_study.SOURCE_PRIORITY.values()
             for line in tier_lines]
    for source_lines in market_study.TYPE_SOURCE_PRIORITY.values():
        lines.extend(source_lines)
    domains = sorted({market_study._source_host(url)
                      for line in lines
                      for url in market_study._catalog_urls(line)
                      if market_study._source_host(url)})
    result = {item['key']: [] for item in _SUMMARY_RESEARCH_GROUPS}
    for host in domains:
        registrable = market_study._registrable_host(host)
        targets = [item for item in _SUMMARY_RESEARCH_GROUPS[:-1]
                   if host in item['hosts'] or registrable in item['hosts']]
        if not targets:
            targets = [_SUMMARY_RESEARCH_GROUPS[-1]]
        for target in targets:
            result[target['key']].append(host)
    # These sites are required by the owner even if a future catalog edit
    # temporarily omits a deep link for them.
    result['transactions_and_rents'] = sorted(set(
        result['transactions_and_rents'] + ['rei.rega.gov.sa', 'sakani.sa', 'ejar.sa']))
    result['development_and_supply'] = sorted(set(
        result['development_and_supply'] + ['red.rega.gov.sa', 'nhc.sa', 'momah.gov.sa']))
    result['hospitality_and_tourism'] = sorted(set(
        result['hospitality_and_tourism'] + ['mt.gov.sa', 'stats.gov.sa', 'gaca.gov.sa']))
    result['economy_commercial_industrial'] = sorted(set(
        result['economy_commercial_industrial'] + ['stats.gov.sa', 'open.data.gov.sa']))
    return result


def _summary_research_catalog_urls_by_host():
    lines = [line for tier_lines in market_study.SOURCE_PRIORITY.values()
             for line in tier_lines]
    for source_lines in market_study.TYPE_SOURCE_PRIORITY.values():
        lines.extend(source_lines)
    urls_by_host = {}
    for line in lines:
        for url in market_study._catalog_urls(line):
            host = market_study._source_host(url)
            if host:
                urls_by_host.setdefault(host, set()).add(url)
    for host, required_urls in _SUMMARY_RESEARCH_REQUIRED_URLS.items():
        urls_by_host.setdefault(host, set()).update(required_urls)
    return {host: sorted(urls) for host, urls in urls_by_host.items()}


def _summary_research_prompt(payload, group, hosts, city, district='',
                             offer_lang='ar'):
    requested_sites = '\n'.join(f'- {host}' for host in hosts) or 'ابحث في المصادر المهنية والرسمية المساندة.'
    catalog_urls = sorted({url for host in hosts
                           for url in _summary_research_catalog_urls_by_host().get(host, [])})
    if 'rei.rega.gov.sa' in hosts and city:
        city_url = 'https://rei.rega.gov.sa/ar/cities/' + quote(str(city).strip())
        if city_url not in catalog_urls:
            catalog_urls.append(city_url)
            catalog_urls.sort()
    requested_pages = ('\nالروابط المحددة في قائمة مصادر دراسة السوق لهذا الموقع؛ افتح كل رابط منها '
                       'وابحث في البيانات المرتبطة بمهمتك داخل كل صفحة:\n'
                       + '\n'.join(f'- {url}' for url in catalog_urls) + '\n'
                       if catalog_urls else '')
    site_queries = '، '.join(f'site:{host}' for host in hosts)
    place = f'حي {district}، مدينة {city}' if district else f'مدينة {city} كاملة'
    listing_urls = []
    if any(market_study._registrable_host(host) == 'aqar.fm' for host in hosts):
        listing_urls = [url for url, _label in market_study._listing_urls(
            list(market_study.TYPE_SOURCE_PRIORITY), {'بيع', 'إيجار'}, city)]
    listings_block = ('\nروابط قوائم المدينة للمقارنة في الأسعار المطلوبة:\n'
                      + '\n'.join(f'- {url}' for url in listing_urls)
                      + '\nاستخدم فلتر الحي داخل الصفحة عند تحليل حي محدد.\n'
                      if listing_urls else '')
    return (
        f"أنت باحث متخصص في {group['label']} ضمن دراسة سوق سعودية مهنية. هذا بحث منفصل عن بقية الباحثين؛ "
        'قدّم أدلة خامًا دقيقة ومهيكلة، ولا تكتب دراسة سوق عامة.\n'
        f'النطاق الجغرافي الموكّل لهذا البحث فقط: {place}. لا تبحث في مدينة أو حي آخر.\n'
        + 'نطاق المهمة: ' + group['focus'] + '\n'
        + 'هذا الباحث مسؤول عن مصدر محدد؛ ابحث داخله أولًا وحاول الوصول إلى صفحة البيانات أو التقرير ذات الصلة، '
        'ولا تكتفِ بالصفحة الرئيسية. إذا لم يعرض المصدر بيانات لهذا المكان أو الفترة فسجّل فجوة تغطية.\n'
        'المصدر الموكّل لهذا الباحث:\n' + requested_sites + '\n'
        + requested_pages
        + listings_block
        + 'فتح الموقع أو الرابط وحده لا يُعد بحثًا مكتملًا. تفاعل فعليًا مع المصدر واجمع كل البيانات ذات الصلة '
        'بالمدينة/الحي والفترة والنشاط الموكّل لك: افتح كل صفحة محددة، افحص عناصرها، اكتب المدينة أو الحي '
        'والتاريخ ونوع المؤشر في الحقول، اختر القيم من القوائم، واضغط بحث/تطبيق. افحص كل التبويبات والجداول '
        'والرسوم، افتح التفاصيل، تنقّل بين الصفحات والنتائج، ووسّع الفلاتر ذات الصلة حتى تستنفد البيانات '
        'المتاحة للنطاق. استخدم click_element وtype_text مع submit=true وscroll_page وinspect_page؛ '
        'لا تكتفِ بالمقتطفات أو أول صفحة ولا تنتقِ رقمًا واحدًا إذا كان المصدر يعرض مؤشرات أخرى. '
        'سجّل كل المؤشرات والتقسيمات ذات الصلة، والفترة وعدد السجلات أو الصفحات التي ظهرت. إذا تعذّر '
        'استنفاد النتائج أو تصديرها، حدّد ما جُمِع وما بقي غير متاح بدل ادعاء اكتمال المصدر. '
        'عند البحث عبر SearXNG قيّد الاستعلام بواحد من هذه النطاقات: ' + site_queries + '. لا تدّعِ '
        'استخراج نتائج من لوحة لم تعرضها الصفحة فعلًا. ابدأ بالصفحات الحكومية والمصدر الأصلي، واستخدم مصدرًا '
        'مهنيًا أو إعلانًا فقط لقياس النوع الذي يتيحه.\n'
        + 'لكل دليل أعد: القيمة كما ظهرت، الوحدة، المدينة والحي أو المستوى الجغرافي، الفترة، تاريخ البيانات، '
        'اسم المصدر، رابط الصفحة المفتوحة المحددة، مستوى الموثوقية، وملاحظة المنهج/القيود. افصل الصفقة المنفذة '
        'عن سعر الطلب والإيجار المعلن، ولا تستنتج متوسطًا من عينة صغيرة. لا تستخدم معلومات من الذاكرة. إذا كانت '
        'صفحة تتطلب نفاذ أو لا تعرض نتائج أو بيانات حديثة، سجّل فجوة التغطية بوضوح.\n'
        + 'أرجع JSON فقط: {"group":"' + group['key'] + '","coverage":[{"url":"",'
        '"interaction_steps":[],"datasets_opened":[],"records_or_pages_seen":"",'
        '"completeness":"complete|partial|unavailable","gaps":""}],"findings":[{"metric":"","value":"",'
        '"unit":"","city":"","district":"","period":"","data_date":"","source_name":"",'
        '"source_url":"","reliability":"","limitations":""}],"sources":[{"name":"","url":"",'
        '"data_date":"","reliability":"","note":""}],"coverage_gaps":[]}\n'
        + ("Write the JSON text values in English. Search around " + place + '.\n'
           if offer_lang == 'en' else '')
    )


def _run_summary_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar'):
    worker_pool = _new_evidence_pool()
    prompt = _summary_research_prompt(payload, group, hosts, city, district,
                                      offer_lang=offer_lang)
    result = _browse_agent_call(
        'أنت باحث ويب تستخدم أدوات المتصفح المحلي. لا تخترع نتائج ولا تنهِ المهمة قبل فتح صفحات مصادر.',
        prompt, dict(usage_ctx or {}), model=GEMINI_TEXT_MODEL, evidence_pool=worker_pool,
        deadline=deadline, local_tools=True, search_provider='searxng',
        search_budget=_SUMMARY_RESEARCH_SEARCH_BUDGET,
        max_steps=_SUMMARY_RESEARCH_MAX_STEPS, max_tokens=8000,
        reasoning_effort='low')
    pages = worker_pool.pages() if worker_pool is not None else []
    parsed, parse_error = _parse_market_model_json(result)
    searched = _market_search_ran(result) or bool(pages)
    return {
        'key': group['key'], 'label': group['label'], 'city': city,
        'district': district, 'hosts': list(hosts), 'result': result,
        'parsed': parsed, 'parse_error': parse_error, 'pages': pages,
        'searched': searched,
    }


def _run_market_summary_research(payload, usage_ctx, evidence_pool, deadline,
                                 report=None, offer_lang='ar'):
    """Run source-specific Playwright/SearXNG researchers concurrently."""
    report = report if callable(report) else (lambda *_args: None)
    source_map = _summary_research_sources_by_group()
    scope = market_study.normalize_summary_scope(
        payload.get('summaryScope'), payload.get('city'))
    jobs = []
    for city_scope in scope['cities']:
        locations = [('', city_scope['name'])]
        locations.extend((district, city_scope['name'])
                         for district in city_scope['districts'])
        for district, city in locations:
            for group in _SUMMARY_RESEARCH_GROUPS:
                for host in source_map.get(group['key']) or []:
                    jobs.append((group, [host], city, district))
    if not jobs:
        return {'success': False, 'error': 'summary_scope_required',
                'outcomes': [], 'citation_urls': []}
    report(12, f'بدء {len(jobs)} مهمة بحث للمصادر، بحد أقصى 100 باحث بالتوازي')
    outcomes = []
    with ThreadPoolExecutor(max_workers=min(_SUMMARY_RESEARCH_MAX_WORKERS, len(jobs)),
                            thread_name_prefix='market-research') as executor:
        futures = {
            executor.submit(_run_summary_researcher, group, hosts, payload,
                            city, district, usage_ctx, deadline, offer_lang):
            (group, hosts, city, district)
            for group, hosts, city, district in jobs
        }
        for future in as_completed(futures):
            group, hosts, city, district = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:
                outcome = {'key': group['key'], 'label': group['label'],
                           'city': city, 'district': district,
                           'hosts': list(hosts),
                           'result': {'error': {'message': str(exc)}},
                           'parsed': {}, 'parse_error': 'worker_error',
                           'pages': [], 'searched': False}
            outcomes.append(outcome)
            if evidence_pool is not None:
                for page in outcome.get('pages') or []:
                    evidence_pool.add_page(page.get('url'), page.get('title'),
                                           page.get('content'), final_url=page.get('url'),
                                           via='parallel_browser')
            report(12 + int(56 * len(outcomes) / max(1, len(jobs))),
                   f"اكتملت مهمة البحث {len(outcomes)} من {len(jobs)}: "
                   f"{outcome['label']} — {city}" + (f' — {district}' if district else ''))
    outcomes.sort(key=lambda item: next(
        (index for index, group in enumerate(_SUMMARY_RESEARCH_GROUPS)
         if group['key'] == item['key']), len(_SUMMARY_RESEARCH_GROUPS)))
    opened = [item for item in outcomes if item.get('searched')]
    if not opened:
        return {'success': False, 'error': 'لم ينجح أي مسار في فتح دليل ويب',
                'outcomes': outcomes, 'citation_urls': []}
    reports = []
    citations = []
    for item in outcomes:
        parsed = item.get('parsed') if isinstance(item.get('parsed'), dict) else {}
        coverage = parsed.get('coverage') if isinstance(parsed.get('coverage'), list) else []
        declared_gaps = parsed.get('coverage_gaps')
        declared_gaps = ([str(gap).strip() for gap in declared_gaps if str(gap).strip()]
                         if isinstance(declared_gaps, list) else [])
        incomplete = [row for row in coverage if not isinstance(row, dict)
                      or str(row.get('completeness') or '').strip().lower() != 'complete'
                      or str(row.get('gaps') or '').strip()]
        coverage_status = (
            'unavailable' if not item.get('searched') else
            'complete' if coverage and not incomplete and not declared_gaps else 'partial')
        coverage_gap = ''
        if coverage_status == 'unavailable':
            coverage_gap = 'لم يفتح هذا المصدر دليلًا؛ اعتبر بياناته فجوة تغطية.'
        elif coverage_status == 'partial':
            coverage_gap = ('لم يثبت الباحث استنفاد البيانات المرتبطة بالمهمة داخل المصدر؛ '
                            'تحقق من تفاصيل التغطية والفجوات.')
        if incomplete or declared_gaps:
            details = [str(row.get('gaps') or '').strip() for row in incomplete
                       if isinstance(row, dict) and str(row.get('gaps') or '').strip()]
            details.extend(declared_gaps)
            if details:
                coverage_gap += ' ' + '؛ '.join(dict.fromkeys(details))
        reports.append({
            'research_group': item['key'],
            'source_hosts': item.get('hosts') or [],
            'city': item.get('city'), 'district': item.get('district'),
            'opened_evidence': bool(item.get('searched')),
            'coverage_status': coverage_status,
            'research_output': parsed or _get_chat_response_text(item.get('result') or {}),
            'coverage_gap': coverage_gap,
        })
        citations.extend(_market_citation_urls(item.get('result') or {}))
        citations.extend(page.get('url') for page in item.get('pages') or [])
    for local_group in ((payload.get('summaryLocalBenchmarks') or {}).get('groups') or []):
        citations.extend(local_group.get('source_urls') or [])
    return {
        'success': True,
        'outcomes': outcomes,
        'reports': reports,
        'citation_urls': list(dict.fromkeys(url for url in citations if url)),
    }


def _run_market_summary_aggregator(system_prompt, prompt, usage_ctx,
                                   research, deadline=None):
    remaining = None
    if deadline is not None:
        remaining = max(1, int(float(deadline) - time.time()))
        if remaining <= 1:
            return {'error': {'message': 'deadline_exceeded'}}
    result = call_text_chat(
        system_prompt, prompt, model=GEMINI_TEXT_MODEL,
        max_tokens=MARKET_STUDY_MAX_TOKENS,
        reasoning_effort='medium', timeout=min(300, remaining or 300),
        usage_ctx=usage_ctx)
    if not isinstance(result, dict):
        return {'error': {'message': 'aggregator returned an empty response'}}
    choices = result.get('choices') or []
    if choices:
        message = choices[0].setdefault('message', {})
        annotations = message.setdefault('annotations', [])
        seen = {str(((item or {}).get('url_citation') or {}).get('url') or '')
                for item in annotations if isinstance(item, dict)}
        for url in research.get('citation_urls') or []:
            if url and url not in seen:
                annotations.append({'url_citation': {'url': url,
                                  'title': 'مصدر مفتوح أثناء البحث', 'content': ''}})
                seen.add(url)
    result['browse_trace'] = [
        {'url': url, 'title': '', 'chars': 0}
        for url in research.get('citation_urls') or []]
    return result
