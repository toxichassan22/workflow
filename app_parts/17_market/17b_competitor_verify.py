def _browse_agent_verify(task, usage_ctx):
    """One self-hosted browse-agent run for a competitor verify.

    Returns the agent's OpenRouter-shaped reply — every page it opened rides in
    as a url_citation annotation — or an ``{'error': ...}`` dict. Never raises:
    the verify path reports the failure as search_not_run instead of falling
    back to the paid provider, and the module can be absent on a deploy that
    never enabled the flag.
    """
    try:
        from web_browse.agent import run_browse_agent
        response = run_browse_agent(task, usage_ctx=usage_ctx)
    except Exception as exc:
        return {'error': {'message': f'browse_agent: {exc}'}}
    if not isinstance(response, dict):
        return {'error': {'message': 'browse_agent: empty response'}}
    return response


def _absorb_verify_response(row, prompt_response, tokens, needed, matched_pages,
                            official='', offer_lang='ar'):
    """Token-match a verify call's retrieved pages and apply its price.

    Returns (matched_urls, official_url): pages whose title, URL or retrieved
    content carries enough distinctive name tokens feed the row's evidence,
    and a page carrying the whole distinctive name in its title or URL is the
    project's official page. The model's own price is applied only when it
    cites one of those retrieved pages.
    """
    prompt_matched = []
    for page in _market_citation_pages(prompt_response):
        url = str(page.get('url') or '').strip()
        if url and _foreign_market_host(url):
            continue
        title_url = market_study._fold_choice(f"{page.get('title') or ''} {url}")
        haystack = market_study._fold_choice(
            f"{title_url} {page.get('content') or ''}")
        hits = sum(1 for token in tokens if token in haystack)
        if hits >= needed:
            prompt_matched.append(url)
            matched_pages[url] = page
        # An official page carries the whole distinctive name in its title
        # or URL — a content-only mention is evidence the project exists,
        # not that the host belongs to it.
        if url and not official:
            title_hits = sum(1 for token in tokens if token in title_url)
            if title_hits >= len(tokens) and not any(
                    token in _normalized_web_host(url)
                    for token in _AGGREGATOR_HOST_TOKENS):
                official = url
    parsed, _parse_error = _parse_market_model_json(prompt_response)
    # A project price is only as good as the page naming this competitor —
    # the figure must come from a page this search actually retrieved.
    _apply_verified_competitor_price(row, parsed, set(prompt_matched), offer_lang=offer_lang)
    return prompt_matched, official


def _verify_competitor_row(row, payload, data, tenant_id=None):
    """One targeted web search per competitor.

    The main call's single Exa query only retrieves market-level index pages,
    so the model fills names from memory. A per-competitor query retrieves the
    pages that actually mention THIS name: they become its source links, its
    official page feeds the logo import, and a name no retrieved page mentions
    is flagged as unverified instead of being silently trusted.
    """
    name = str(row.get('name') or '').strip()
    if not name:
        return
    offer_lang = slide_engine.resolve_offer_lang(data)
    en = offer_lang == 'en'
    city = str(payload.get('city') or '').strip() or 'السعودية'
    operation = str(row.get('operation_type') or '').strip() or ('Other' if en else 'أخرى')
    price_options = '، '.join(market_study.price_types_for_operation(operation, offer_lang))
    price_shape = (
        '"price": {"type": "أحد: ' + price_options + '", "value": "الرقم فقط", '
        '"from": "الحد الأدنى للنطاق", "to": "الحد الأقصى للنطاق", '
        '"url": "رابط الصفحة التي ورد فيها السعر حرفيًا"}')
    price_rule = (
        'السعر يُقبل فقط إذا ظهر في صفحة قرأتها في هذا البحث، ورابطها يوضع في '
        'price.url — إن لم تجد سعرًا أعد حقول price فارغة ولا تكتب رقمًا من ذاكرتك. ')
    prompts = [(
        f'ابحث في الويب عن المشروع العقاري «{name}» في مدينة {city} بالسعودية.\n'
        'أرجع JSON فقط: {"exists": true/false, "official_url": "صفحة الموقع الرسمي '
        'للمشروع أو مطوّره إن وُجدت", "summary": "سطر واحد عن المشروع", '
        + price_shape + '}.\n' + price_rule +
        'أي صفحة مسترجعة تذكر المشروع بالاسم تُحتسب دليلًا — موقع المطور أو '
        'إعلانًا تفصيليًا أو خبرًا، وليس شرطًا أن تكون رسمية. '
        'إن لم تجد أي صفحة تذكر هذا المشروع بالاسم أعد exists=false ولا تخمّن روابط.'
    )]
    tokens = _competitor_name_tokens(name)
    if not tokens:
        return
    needed = 1 if len(tokens) == 1 else 2
    # Bare-token retry: a quoted «مشروع …» phrasing under-retrieves when the
    # pages that name this project drop the generic prefix or use only one
    # script of a bilingual name. It also doubles as the retry when the first
    # call errors out or returns no citations.
    prompts.append(
        f'ابحث في الويب عن {" ".join(sorted(tokens))} — {city} السعودية.\n'
        'أرجع JSON فقط: {"exists": true/false, "official_url": "صفحة الموقع '
        'الرسمي إن وُجدت", "summary": "سطر واحد", ' + price_shape + '}.\n'
        + price_rule + 'أي صفحة تذكر الاسم تُحتسب دليلًا — إعلانًا أو خبرًا أو '
        'موقع مطوّر. إن لم تجد صفحة تذكر هذا الاسم أعد exists=false.'
    )
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)
    response = None
    search_ran_any = False
    matched = []
    matched_pages = {}
    official = ''
    last_error = ''
    if os.environ.get('BROWSER_AGENT') == '1':
        # One self-hosted browse agent replaces the prompt loop: it runs the
        # searches and opens the pages itself, so every page it actually read
        # arrives as a url_citation annotation — the retrieved evidence.
        prompt_response = _browse_agent_verify(prompts[0], usage_ctx)
        response = prompt_response
        last_error = _chat_error_message(prompt_response)
        if prompt_response.get('error') is None:
            if _market_citation_pages(prompt_response):
                search_ran_any = True
                prompt_matched, official = _absorb_verify_response(
                    row, prompt_response, tokens, needed, matched_pages,
                    offer_lang=offer_lang)
                matched.extend(prompt_matched)
            else:
                # A clean reply that opened zero pages means nothing was read —
                # "no browsed evidence", never proof the name is fabricated.
                last_error = 'browse_agent: no browsed evidence'
    else:
        for prompt in prompts:
            prompt_response = None
            # Plugin-only first (Gemini can fumble tool calls), then the
            # openrouter:web_search tool — on deployments where the Exa plugin
            # returns no citations the tool is the only path that grounds.
            for tools_on in (False, True):
                try:
                    prompt_response, err = _call_market_study_model(
                        market_study.build_consultant_system_prompt(), prompt,
                        max_tokens=1200, usage_ctx=usage_ctx, server_tools=tools_on)
                except Exception:
                    prompt_response = None
                    continue
                last_error = err or last_error
                if not _market_search_ran(prompt_response):
                    continue
                search_ran_any = True
                break
            if prompt_response is None or not _market_search_ran(prompt_response):
                # A tenant-key gate refusal is deterministic — every remaining
                # angle fails identically, so stop instead of burning them all.
                gate_error = (prompt_response or {}).get('error')
                if isinstance(gate_error, dict) and gate_error.get('error_code') in (
                        'NO_TENANT_KEY', 'TENANT_KEY_CHECK_FAILED'):
                    break
                continue
            response = prompt_response
            prompt_matched, official = _absorb_verify_response(
                row, prompt_response, tokens, needed, matched_pages,
                official=official, offer_lang=offer_lang)
            matched.extend(prompt_matched)
            price_filled = any(str(row.get(key) or '').strip()
                               for key in ('price_value', 'price_from', 'price_to'))
            # Identity proven is not the job done — keep searching while the price
            # is still empty; the next query angle may surface a pricing page.
            if prompt_matched and price_filled:
                break
    if not search_ran_any:
        # The provider returned no citations at all — a search-provider miss,
        # not proof the name is fabricated. Say so instead of mislabeling it.
        row['verify_state'] = 'search_not_run'
        row['verify_provider_error'] = last_error or (
            _chat_error_message(response) if response else '') or 'empty_response'
        return
    matched = list(dict.fromkeys(matched))
    if not matched:
        # The search ran and no retrieved page mentions this name — flag the row
        # rather than silently trusting a memory-generated competitor. A manual
        # name is the user's own entry, so it is never marked fabricated.
        if (row.get('row_source') or 'ai') == 'ai':
            row['no_search_evidence'] = True
        row['verify_state'] = 'no_match'
        return
    row.pop('no_search_evidence', None)
    if not any(str(row.get(key) or '').strip()
               for key in ('price_value', 'price_from', 'price_to')):
        # The model's reply rarely carries the figure — the retrieved evidence
        # does. Search the citation excerpts first (they survive bot walls),
        # then the fetched pages, and take the median.
        _fill_competitor_price_from_listings(
            row, matched + market_study.competitor_source_urls(row),
            pages=list(matched_pages.values()))
    row['verify_state'] = 'verified'
    row['source_urls'] = list(dict.fromkeys(
        market_study.competitor_source_urls(row) + matched))[:6]
    if not str(row.get('source_url') or '').strip():
        row['source_url'] = market_study.prefer_specific_source_url(*row['source_urls'])
    if official and not str(row.get('logo_source_url') or '').strip():
        row['logo_source_url'] = official
        row['logo_official_verified'] = True


def _apply_verified_competitor_price(row, parsed, citation_urls, offer_lang='ar'):
    """Fill empty price fields from the per-competitor verification search.

    That call already retrieves real pages for this competitor — accept its
    price only when the cited page was actually retrieved, so the figure stays
    grounded in a fetched page and a memory number never slips through. A price
    the main pass already filled is never overwritten.
    """
    price = parsed.get('price') if isinstance(parsed, dict) else None
    if not isinstance(price, dict):
        price = parsed if isinstance(parsed, dict) else {}
    url = str(price.get('url') or price.get('source_url') or price.get('sourceUrl') or '').strip()
    if not url or url not in (citation_urls or set()):
        return
    value = market_study._clean_numeric(price.get('value') or price.get('price_value'))
    from_v = market_study._clean_numeric(price.get('from') or price.get('price_from'))
    to_v = market_study._clean_numeric(price.get('to') or price.get('price_to'))
    if not (value or from_v or to_v):
        return
    if str(row.get('price_value') or '').strip() or str(row.get('price_from') or '').strip():
        return
    url = market_study.canonical_index_source_url(url, row.get('operation_type'))
    price_type = str(price.get('type') or price.get('price_type') or '').strip()
    options = market_study.price_types_for_operation(
        str(row.get('operation_type') or '').strip(), offer_lang)
    if price_type not in options:
        price_type = ''
    is_range = market_study.price_uses_range(price_type) or (from_v and to_v)
    if is_range:
        row['price_from'] = from_v or value
        row['price_to'] = to_v or ''
        row['price_cache'] = {'price_from': row['price_from'], 'price_to': row['price_to']}
        field_key = 'price_from'
        if not price_type:
            price_type = next((o for o in options if market_study.price_uses_range(o)), options[-1])
    else:
        row['price_value'] = value or from_v
        row['price_cache'] = {'price_value': row['price_value']}
        field_key = 'price_value'
    if price_type:
        row['price_type'] = price_type
    field_sources = market_study.competitor_field_sources(row)
    urls = field_sources.setdefault(field_key, [])
    if url not in urls:
        urls.append(url)
    row['field_sources'] = field_sources
    row['source_urls'] = list(dict.fromkeys(
        market_study.competitor_source_urls(row) + [url]))


def _read_market_source_page(url, max_bytes=2 * 1024 * 1024):
    """(html, error) — fetch a retrieved source page through the DNS-pinned pool.

    Model-supplied URLs stay on _pinned_https_get so redirects can never leave
    the original site and private hosts remain blocked. Returns raw markup:
    JSON-LD prices live inside <script> tags that visible-text stripping
    would discard."""
    pool, response, outcome = _pinned_https_get(url)
    if pool is None:
        return '', _official_fetch_error(outcome)
    try:
        if response.status != 200:
            return '', f'HTTP {response.status}'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > max_bytes:
                break
        return bytes(content).decode('utf-8', errors='replace'), ''
    except Exception as exc:
        return '', str(exc)
    finally:
        response.release_conn()
        pool.close()


_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
_LISTING_PRICE_PATTERNS = (
    re.compile(r'(?:ريال|ر\.?\s?س|SAR|SR)\s*[:=]?\s*([0-9][0-9,.\u0660-\u0669]{2,})', re.IGNORECASE),
    re.compile(r'([0-9][0-9,.\u0660-\u0669]{2,})\s*(?:ريال|ر\.?\s?س|SAR|SR)\b', re.IGNORECASE),
    re.compile(r'"price"\s*:\s*"?([0-9][0-9,.]{2,})"?'),
)
_LISTING_PRICE_MIN = 300.0
_LISTING_PRICE_MAX = 2_000_000_000.0


def _extract_listing_prices(html):
    """[{value, period, per_sqm}] — price mentions inside a fetched listing page."""
    if not html:
        return []
    found = {}
    for pattern in _LISTING_PRICE_PATTERNS:
        for match in pattern.finditer(html):
            raw = (match.group(1) or '').translate(_ARABIC_DIGITS)
            raw = raw.replace(',', '').replace(' ', '')
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not (_LISTING_PRICE_MIN <= value <= _LISTING_PRICE_MAX):
                continue
            window = html[max(0, match.start() - 100):match.end() + 100]
            if re.search(r'سنوي|سنة|annual|yearly|per\s*year|/yr', window, re.IGNORECASE):
                period = 'سنوي'
            elif re.search(r'شهري|شهر|monthly|per\s*month|/mo', window, re.IGNORECASE):
                period = 'شهري'
            elif re.search(r'ليلة|per\s*night|nightly', window, re.IGNORECASE):
                period = 'ليلة'
            else:
                period = ''
            per_sqm = bool(re.search(r'متر|sqm|م²|per\s*sq', window, re.IGNORECASE))
            found[(value, period, per_sqm)] = {'value': value, 'period': period, 'per_sqm': per_sqm}
    return list(found.values())


def _fill_competitor_price_from_listings(row, urls, pages=None):
    """Derive a grounded price from the retrieved pages themselves.

    The verify searches leave the price fields empty when the model's reply
    omits the figure — but the retrieved evidence carries it in two places:
    the citation content the search provider already returned (free, works
    even on bot-walled portals like bayut) and the fetched page markup for
    pages that are readable directly. The median of the mentions becomes a
    «متوسط» price; a single mention keeps its own type. price_listed flags
    it as listing evidence, not an officially documented tariff.
    """
    dead = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
    page_content = {}
    for page in pages or []:
        if isinstance(page, dict):
            page_content[str(page.get('url') or '').strip()] = str(page.get('content') or '')
    mentions = []
    searched = 0
    unreadable = 0
    for url in list(dict.fromkeys(urls or []))[:4]:
        if str(url).strip().casefold() in dead:
            continue
        # The citation excerpt is searched first — fetching is the fallback
        # for pages the provider did not quote (or quoted too thinly).
        html = page_content.get(url) or ''
        if not html:
            html, _err = _read_market_source_page(url)
        if not html:
            unreadable += 1
            continue
        searched += 1
        for item in _extract_listing_prices(html):
            item['url'] = url
            mentions.append(item)
        if len(mentions) >= 4:
            break
    if not mentions:
        print(f"[MARKET STUDY] «{row.get('name') or 'منافس'}» no listing prices "
              f"({searched} pages searched, {unreadable} unreadable)")
        return False
    print(f"[MARKET STUDY] «{row.get('name') or 'منافس'}» listing prices: "
          f"{len(mentions)} mentions from {len({m['url'] for m in mentions})} pages")
    operation = str(row.get('operation_type') or '').strip() or 'أخرى'
    options = market_study.PRICE_TYPE_BY_OPERATION.get(
        operation, market_study.PRICE_TYPE_BY_OPERATION['أخرى'])

    def _option(*names):
        for name in names:
            if name in options:
                return name
        return 'أخرى' if 'أخرى' in options else options[0]

    if operation == 'إيجار':
        pool = [m for m in mentions if m['period'] in ('سنوي', 'شهري')] or mentions
    elif operation == 'تشغيل فندقي':
        pool = [m for m in mentions if m['period'] == 'ليلة'] or mentions
    else:
        pool = [m for m in mentions if not m['period']] or mentions
    values = sorted({m['value'] for m in pool})
    per_sqm = any(m['per_sqm'] for m in pool)
    used_urls = list(dict.fromkeys(m['url'] for m in pool))
    median = int(round(values[len(values) // 2] if len(values) % 2
                       else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2))
    if len(values) > 1:
        if operation == 'إيجار':
            price_type = _option('متوسط إيجار المتر' if per_sqm else 'متوسط إيجار الوحدة')
        elif operation == 'بيع':
            price_type = _option('متوسط سعر المتر' if per_sqm else 'متوسط سعر الوحدة')
        elif operation == 'تشغيل فندقي':
            price_type = _option('متوسط سعر الغرفة ADR')
        else:
            price_type = _option('نطاق سعري')
    else:
        period = (pool[0] if pool else {}).get('period') or ''
        if operation == 'إيجار':
            if per_sqm:
                price_type = _option('إيجار المتر الشهري' if period == 'شهري' else 'إيجار المتر السنوي')
            else:
                price_type = _option('إيجار الوحدة الشهري' if period == 'شهري' else 'إيجار الوحدة السنوي')
        elif operation == 'بيع':
            price_type = _option('سعر المتر المربع' if per_sqm else 'سعر الوحدة')
        elif operation == 'تشغيل فندقي':
            price_type = _option('سعر الليلة')
        else:
            price_type = _option('قيمة واحدة')
    if price_type in market_study.RANGE_PRICE_TYPES and len(values) > 1:
        row['price_from'], row['price_to'] = str(int(values[0])), str(int(values[-1]))
        row['price_cache'] = {'price_from': row['price_from'], 'price_to': row['price_to']}
        field_key = 'price_from'
    else:
        row['price_value'] = str(median)
        row['price_cache'] = {'price_value': row['price_value']}
        field_key = 'price_value'
    row['price_type'] = price_type
    row['price_listed'] = True
    field_sources = market_study.competitor_field_sources(row)
    bucket = field_sources.setdefault(field_key, [])
    for url in used_urls:
        if url not in bucket:
            bucket.append(url)
    row['field_sources'] = field_sources
    row['source_urls'] = list(dict.fromkeys(
        market_study.competitor_source_urls(row) + used_urls))[:6]
    marker = 'السعر متوسط إعلانات مسترجعة — غير موثق رسميًا'
    note = str(row.get('note') or '').strip()
    if marker not in note:
        row['note'] = f'{note} — {marker}' if note else marker
    return True


def _verify_competitor_rows(rows, payload, data, tenant_id=None, progress=None):
    report = progress if callable(progress) else (lambda *_args: None)
    # Manual rows verify too: fill mode exists to complete the cells the user
    # left empty, and the per-name search is the only priced lookup they get.
    targets = [row for row in (rows or [])
               if isinstance(row, dict)
               and str(row.get('name') or '').strip()]
    if not targets:
        return
    done = [0]
    total = len(targets)

    def verify(row):
        try:
            # Pool threads share no Flask context — without one the key gate
            # misreads every company as unkeyed and db-backed helpers die.
            with _worker_app_context():
                _verify_competitor_row(row, payload, data, tenant_id=tenant_id)
        finally:
            done[0] += 1
            report(30 + int(28 * done[0] / total),
                   f'التحقق من «{row.get("name") or "منافس"}» ({done[0]} من {total})...')

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, total)) as pool:
        list(pool.map(verify, targets))
