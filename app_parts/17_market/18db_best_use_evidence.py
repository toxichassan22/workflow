def _best_use_extract_regulations(draft, data):
    # The croquis analysis already distilled the parcel's regulation text into
    # the declared fields — the summary is the permitted-uses source, so parcel
    # documents and municipal files are never re-read here.
    return best_use_regulations.declared(draft.get('draft_data') or {})


def _best_use_verify_regulations(draft):
    project = draft.get('draft_data') or {}
    stored = (project.get('best_use_explore_data') or {}).get('regulations') or {}
    if not best_use_workflow.current(project, 'regulations'):
        raise best_use_contract.ProposalError('regulatory_inputs_changed')
    current = best_use_regulations.declared(project)
    if current['permittedUses'] != stored.get('permittedUses'):
        raise best_use_contract.ProposalError('regulatory_inputs_changed')
    return stored


def _best_use_price_page(url):
    pool, response, final_url = _pinned_https_get(url)
    if response is None:
        return None
    try:
        if response.status != 200:
            return None
        mime = str(response.headers.get('Content-Type') or '').lower()
        if not any(value in mime for value in ('text/html', 'text/plain', 'application/xhtml')):
            return None
        body = response.read(1024 * 1024 + 1, decode_content=True)
        if len(body) > 1024 * 1024:
            return None
        parser = best_use_prices.PageText()
        parser.feed(body.decode('utf-8', errors='replace'))
        return dict(parser.result(), url=url, finalUrl=final_url)
    except Exception:
        return None
    finally:
        response.release_conn()
        pool.close()


def _best_use_scan_prices(draft, regulation_data, data, progress=None):
    project = draft.get('draft_data') or {}
    uses = regulation_data['permittedUses']
    city, district = best_use_contract.text(project.get('city'), 150), best_use_contract.text(project.get('district'), 150)
    if not city:
        raise best_use_contract.ProposalError('price_city_missing')
    usage_ctx = _usage_ctx('best_use_price_scan', data, draft_id=draft['id'])

    def _scan_use(use):
        prompt = json.dumps({'city': city, 'district': district, 'use': use,
                            'maximumSearches': 2, 'maximumObservations': 6}, ensure_ascii=False)
        with _worker_app_context():
            try:
                # Google-native grounding first: the provider's own search answers
                # fast and reads Arabic listing queries well.
                rows, response = _best_use_price_scan_use(
                    use, prompt, city, draft, data,
                    {'engine': 'native', 'max_uses': 2, 'max_tool_calls': 3, 'timeout': 120,
                     'reasoning_effort': 'low'},
                    6, usage_ctx)
            except best_use_contract.ProposalError as error:
                # A native grounding pass that leaves no detectable search trace
                # falls through to the deeper Exa pass instead of failing the scan.
                if not str(error).startswith('price_search_not_run'):
                    raise
                rows, response = [], None
            if not rows:
                rows, response = _best_use_price_scan_use(
                    use, prompt, city, draft, data,
                    {'engine': 'exa', 'mode': 'auto', 'max_uses': 3, 'max_total_results': 16,
                     'max_tool_calls': 5, 'timeout': 120, 'max_results': 8,
                     'reasoning_effort': 'low'}, 8, usage_ctx)
        return use, rows, response

    candidates, retrieved = [], []
    done = [0]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if progress:
        progress(15, 'prices', {'index': 0, 'total': len(uses)})
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(uses)))) as pool:
        futures = {pool.submit(_scan_use, use): use for use in uses}
        for future in as_completed(futures):
            use, rows, response = future.result()
            done[0] += 1
            if progress:
                progress(20 + int(35 * done[0] / max(1, len(uses))), 'prices',
                         {'use': use, 'index': done[0], 'total': len(uses)})
            if response:
                retrieved.extend(_market_citation_pages(response))
            candidates.extend(row for row in rows[:6] if isinstance(row, dict) and row.get('use') == use)
    # verify_observation needs the excerpt inside a retrieved page — grounding
    # pages already carry the cited text, so only fetch URLs the search did not.
    covered = {best_use_prices.clean_url(page.get('url')) for page in retrieved if page.get('content')}
    pages = []
    urls = list(dict.fromkeys(best_use_prices.clean_url(row.get('url')) for row in candidates))
    for index, url in enumerate(urls):
        if progress:
            progress(55 + int(8 * index / max(1, len(urls))), 'priceEvidence',
                     {'index': index + 1, 'total': len(urls)})
        if not url or url in covered:
            continue
        page = _best_use_price_page(url)
        if page:
            pages.append(page)
    pages.extend(page for page in retrieved if page.get('content'))
    return best_use_prices.build_scan(uses, candidates, pages, db._utcnow().isoformat(), city, district,
                                      preliminary=True)


def _best_use_price_scan_use(use, prompt, city, draft, data, budget, results_cap, usage_ctx):
    response, error = _call_market_study_model(
        'مسح أسعار حي من الويب للاستخدام والمنطقة المحددين فقط. '
        'بحث بيع وبحث إيجار، لا دراسة سوق ولا بيانات مشروع أساسية. '
        'لا تؤلف أسعارًا ولا تستخدم ذاكرة الموديل. '
        'لكل سعر انقل جملة إجابة البحث الموثقة كما وردت في excerpt دون إعادة صياغة — يجوز أن تكون '
        'متوسطًا أو نطاقًا أو خلاصة منشورة، فالجملة نفسها هي الدليل. كل مشاهدة تخص عملية واحدة '
        '(بيع أو إيجار) وتظهر في جملتها القيمة والعملة والوحدة والفترة والمدينة، والحي عند ذكره. '
        'الحي غير المتوفر يبقى فارغًا ولا تنسب بيانات المدينة إلى حي. لا تحول سعر الوحدة أو الغرفة إلى متر. '
        'تاريخ نشر السعر غير المثبت null. معرف الإعلان الحرفي في propertyId، أو اسم المشروع في entityName. '
        'أعد JSON {"observations":[{"use":"' + use + '","revenueMode":"sale|rent",'
        '"value":100,"currency":"SAR","unit":"sqm|unit|room","period":"oneOff|year|month|night",'
        '"city":"","district":"","url":"","excerpt":"","publishedAt":null,"propertyId":"","entityName":""}]}. '
        'إذا لم يوجد سعر موثق observations=[]؛ لا تعوض النقص بأرقام مفترضة.',
        prompt, max_tokens=12000, usage_ctx=usage_ctx,
        search_context={'city': city, 'country': 'SA'},
        max_search_results=results_cap, search_budget=budget)
    if error or not _market_search_ran(response):
        # Surface the provider's real reason — quota, timeout, malformed
        # tool call — instead of a bare code that reads as "no results".
        detail = (error or '').strip() or 'no_search_executed'
        raise best_use_contract.ProposalError('price_search_not_run: ' + detail[:240])
    parsed = _best_use_explore_provider(response)
    rows = parsed.get('observations')
    if not isinstance(rows, list):
        raise best_use_contract.ProposalError('price_scan_invalid')
    return rows, response


def _best_use_guided_prices(project):
    market = best_use.read_object(project.get('market_study_data'))
    candidates, pages = [], []
    mapping = {'سعر المتر المربع': ('sale', 'oneOff'), 'Price per SQM': ('sale', 'oneOff'),
               'إيجار المتر السنوي': ('rent', 'year'), 'Annual Rent per SQM': ('rent', 'year')}
    for row in (market.get('competitors') or [])[:18]:
        if not isinstance(row, dict) or row.get('price_type') not in mapping:
            continue
        mode, period = mapping[row['price_type']]
        value = best_use_prices.number(row.get('price_value'))
        if value is None or value <= 0:
            continue
        urls = row.get('source_urls') or [row.get('source_url') or row.get('source')]
        if not isinstance(urls, list):
            urls = []
        for url in urls[:2]:
            url = best_use_prices.clean_url(url)
            if not url:
                continue
            page = next((page for page in pages if page['url'] == url), None)
            if page is None:
                page = _best_use_price_page(url)
                if page:
                    pages.append(page)
            if not page:
                continue
            for excerpt in re.split(r'\n+', page['content']):
                if not excerpt.strip():
                    continue
                for use, pattern in best_use_regulations.USE_TERMS.items():
                    if re.search(pattern, excerpt, re.I):
                        candidates.append({'use': use, 'revenueMode': mode, 'period': period, 'unit': 'sqm',
                            'value': value, 'currency': 'SAR', 'city': project.get('city') or '',
                            'district': row.get('district') or '', 'url': url, 'excerpt': excerpt[:5000],
                            'entityName': row.get('name') or '', 'publishedAt': page.get('publishedAt')})
    uses = sorted(set().union(*(best_use.MAIN_USES.get(kind, set()) for kind in best_use.project_types(project))))
    return best_use_prices.build_scan(uses, candidates, pages, db._utcnow().isoformat(),
                                     project.get('city') or '', project.get('district') or '', search_ran=True)
