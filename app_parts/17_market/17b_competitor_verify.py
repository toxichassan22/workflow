def _agent_run_accepts(agent_module, param):
    """True when ``run_browse_agent`` declares ``param`` (or ``**kwargs``).

    evidence_pool/deadline/session arrive with the web_browse agent task —
    probing keeps this caller correct on either side of that landing instead
    of hard-failing an older agent build on an unexpected keyword argument.
    """
    try:
        import inspect
        params = inspect.signature(agent_module.run_browse_agent).parameters.values()
        return any(p.name == param or p.kind == inspect.Parameter.VAR_KEYWORD
                   for p in params)
    except Exception:
        return False


def _market_deadline_hit(deadline):
    """The job's shared wall-clock limit: None means no budget was set."""
    return deadline is not None and time.time() >= deadline


def _browse_agent_call(system_prompt, user_content, usage_ctx=None, model=None,
                       evidence_pool=None, deadline=None, session=None,
                       **agent_kwargs):
    """One self-hosted browse-agent run for a market web task.

    The task model itself drives the loop — it decides the searches and which
    pages to open, the headless-Chromium workers execute them, and every page
    actually read rides back as a url_citation annotation. Returns the agent's
    OpenRouter-shaped reply or an ``{'error': ...}`` dict; never raises — a
    caller reports the failure as search_not_run instead of falling back to a
    paid search layer (there is none left). ``agent_kwargs`` (search_budget,
    max_steps, max_tokens, reasoning_effort) pass straight through to
    run_browse_agent, and so do the job-scoped ``evidence_pool``/``deadline``/
    ``session`` — once the agent signature carries them.
    """
    try:
        # Flat module, attribute call: `web_browse.agent` would bind a second
        # module identity that `patch.object(agent, 'run_browse_agent')` in
        # tests silently misses.
        import agent as _agent_module
        task = (str(system_prompt or '').strip() + '\n\n'
                + str(user_content or '')).strip()
        forwarded = dict(agent_kwargs)
        for _key, _value in (('evidence_pool', evidence_pool),
                             ('deadline', deadline), ('session', session),
                             ('on_event', forwarded.pop('on_event', None))):
            if _value is not None and _agent_run_accepts(_agent_module, _key):
                forwarded[_key] = _value
        response = _agent_module.run_browse_agent(
            task, usage_ctx=usage_ctx, model=model or MARKET_STUDY_MODEL,
            **forwarded)
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
        if url and (_foreign_market_host(url)
                    or market_study.banned_competitor_listing_host(
                        url, row.get('operation_type'))):
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


def _verify_competitor_row(row, payload, data, tenant_id=None,
                           evidence_pool=None, deadline=None, session=None,
                           on_event=None):
    """One targeted browse-agent run per competitor — the last-resort path.

    A market-wide listing query only surfaces index pages, so the model fills
    names from memory. A per-competitor agent retrieves the pages that
    actually mention THIS name: they become its source links, its official
    page feeds the logo import, and a name no retrieved page mentions is
    flagged as unverified instead of being silently trusted. Rows reach this
    only when the evidence pool already failed to match them (phases 1-2);
    pool/deadline/the thread's browser ride along so the run never refetches
    stored pages and stops when the job's time budget is gone.
    """
    name = str(row.get('name') or '').strip()
    if not name:
        return
    if _market_deadline_hit(deadline):
        row['verify_state'] = 'search_not_run'
        row['verify_provider_error'] = 'deadline_exceeded'
        return
    offer_lang = slide_engine.resolve_offer_lang(data)
    en = offer_lang == 'en'
    city = str(payload.get('city') or '').strip() or 'السعودية'
    operation = str(row.get('operation_type') or '').strip() or ('Other' if en else 'أخرى')
    price_options = '، '.join(market_study.price_types_for_operation(operation, offer_lang))
    price_shape = (
        '"price": {"type": "أحد: ' + price_options + '", "value": "الرقم فقط", '
        '"from": "الحد الأدنى للنطاق", "to": "الحد الأقصى للنطاق", '
        '"currency": "عملة السعر كما وردت في الصفحة — SAR أو EUR أو USD…", '
        '"url": "رابط الصفحة التي ورد فيها السعر حرفيًا"}')
    price_rule = (
        'السعر يُقبل فقط إذا ظهر في صفحة قرأتها في هذا البحث، ورابطها يوضع في '
        'price.url — إن لم تجد سعرًا أعد حقول price فارغة ولا تكتب رقمًا من ذاكرتك. '
        'السعر بعملة غير الريال (كيورو منصات الحجز) مقبول — اكتب العملة في '
        'price.currency ولا تحوّلها ولا تسقط السعر لأجلها. ')
    prompt = (
        f'ابحث في الويب عن المشروع العقاري «{name}» في مدينة {city} بالسعودية.\n'
        'أرجع JSON فقط: {"exists": true/false, "official_url": "صفحة الموقع الرسمي '
        'للمشروع أو مطوّره إن وُجدت", "summary": "سطر واحد عن المشروع", '
        + price_shape + '}.\n' + price_rule +
        'أي صفحة مسترجعة تذكر المشروع بالاسم تُحتسب دليلًا — موقع المطور أو '
        'إعلانًا على منصة عقار (sa.aqar.fm) أو تريفاجو لمنافس فندقي أو خبرًا، '
        'وليس شرطًا أن تكون رسمية — وروابط منصات الإعلانات الأخرى '
        '(bayut، wasalt، dealapp…) ممنوعة ولا تُعتمد، وكذلك كل روابط '
        'التواصل الاجتماعي (إنستغرام، فيسبوك، تيك توك، إكس، يوتيوب…) — '
        'ليست دليلًا ولا مصدرًا للأسعار فلا تفتحها. '
        'إن لم تجد أي صفحة تذكر هذا المشروع بالاسم أعد exists=false ولا تخمّن روابط.'
    )
    tokens = _competitor_name_tokens(name)
    if not tokens:
        return
    needed = 1 if len(tokens) == 1 else 2
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)
    matched = []
    matched_pages = {}
    official = ''
    # The agent runs the searches and opens the pages itself, so every page
    # it actually read arrives as a url_citation annotation — the retrieved
    # evidence. A transport failure or a clean reply with zero opened pages
    # is search_not_run, never proof the name is fabricated.
    response = _browse_agent_call(
        market_study.build_consultant_system_prompt(offer_lang), prompt,
        usage_ctx, evidence_pool=evidence_pool, deadline=deadline,
        session=session, reasoning_effort='low', on_event=on_event)
    last_error = _chat_error_message(response)
    search_ran_any = False
    if response.get('error') is None:
        if _market_citation_pages(response):
            search_ran_any = True
            prompt_matched, official = _absorb_verify_response(
                row, response, tokens, needed, matched_pages,
                offer_lang=offer_lang)
            matched.extend(prompt_matched)
        else:
            last_error = 'browse_agent: no browsed evidence'
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
    if market_study.banned_competitor_listing_host(url, row.get('operation_type')):
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
    currency = market_study._canonical_price_currency(
        price.get('currency') or price.get('price_currency') or price.get('priceCurrency'))
    fx_rate = (market_study.price_fx_to_sar(currency)
               if currency and currency != 'SAR' else None)
    if currency and currency != 'SAR' and not fx_rate:
        # The (ر.س) cell can only hold riyals — a foreign figure with no
        # resolvable rate is dropped, not relabeled. Blank stays honest.
        for key in ('price_value', 'price_from', 'price_to',
                    'price_type', 'price_cache'):
            row.pop(key, None)
        return
    if fx_rate:
        # Same rule as the listing fill — the (ر.س) cell carries riyals; the
        # figure the page printed rides along as price_cache.original_*.
        cache = row.get('price_cache') if isinstance(row.get('price_cache'), dict) else {}
        cache['original_currency'] = currency
        for key, orig in (('price_value', value), ('price_from', from_v),
                          ('price_to', to_v)):
            if not orig or not str(row.get(key) or '').strip():
                continue
            try:
                row[key] = str(int(round(float(orig) * fx_rate)))
            except (TypeError, ValueError):
                continue
            cache[key] = row[key]
            cache[f'original_{key}'] = str(orig)
        row['price_cache'] = cache
        currency = 'SAR'
    if currency:
        row['price_currency'] = currency
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
# Currency-word alternation built from the alias table — the keys are stored
# folded (همزات swiped, ة→ه) but page text isn't, so each foldable letter
# widens back to a class. Longest first keeps «دينار اردني» ahead of «دينار».
_LISTING_CURRENCY_WORD_RE = '|'.join(
    re.escape(key)
      .replace('ا', '[اأإآ]').replace('ه', '[هة]').replace('ي', '[يى]')
    for key in sorted(market_study._PRICE_CURRENCY_ALIASES,
                      key=len, reverse=True))
# Each pattern pairs with the currency it proves: a figure the page priced in
# euros or dollars stays in that currency on the row — never re-read as SAR.
# TOK1/TOK2 resolve the captured currency word through the alias table; ISO1/
# ISO2 accept any 3-letter code and the FX gate drops the non-currencies
# (SQM, THE, …). None means the markup itself must declare the unit
# (JSON-LD priceCurrency).
_LISTING_PRICE_PATTERNS = (
    (re.compile(r'(?:ريال|ر\.?\s?س|SAR|SR)\s*[:=]?\s*([0-9][0-9,.\u0660-\u0669]{2,})', re.IGNORECASE), 'SAR'),
    (re.compile(r'([0-9][0-9,.\u0660-\u0669]{2,})\s*(?:ريال|ر\.?\s?س|SAR|SR)\b', re.IGNORECASE), 'SAR'),
    (re.compile(r'(?:يورو|EUR|€)\s*[:=]?\s*([0-9][0-9,.]{2,})', re.IGNORECASE), 'EUR'),
    (re.compile(r'([0-9][0-9,.]{2,})\s*(?:يورو|EUR|€)\b', re.IGNORECASE), 'EUR'),
    (re.compile(r'(?:دولار|USD|US\$|\$)\s*[:=]?\s*([0-9][0-9,.]{2,})', re.IGNORECASE), 'USD'),
    (re.compile(r'([0-9][0-9,.]{2,})\s*(?:دولار|USD|US\$|\$)\b', re.IGNORECASE), 'USD'),
    (re.compile(r'([0-9][0-9,.\u0660-\u0669]{2,})\s*(' + _LISTING_CURRENCY_WORD_RE + r')\b', re.IGNORECASE), 'TOK2'),
    (re.compile(r'\b(' + _LISTING_CURRENCY_WORD_RE + r')\s*[:=]?\s*([0-9][0-9,.\u0660-\u0669]{2,})', re.IGNORECASE), 'TOK1'),
    (re.compile(r'([0-9][0-9,.\u0660-\u0669]{2,})\s*\b([A-Za-z]{3})\b'), 'ISO2'),
    (re.compile(r'\b([A-Za-z]{3})\s*[:=]?\s*([0-9][0-9,.\u0660-\u0669]{2,})'), 'ISO1'),
    (re.compile(r'"price"\s*:\s*"?([0-9][0-9,.]{2,})"?'), None),
)
_LISTING_PRICE_MIN = 300.0
# A sub-300 SAR figure is a date or a percentage, but a €25 night rate is real —
# foreign-currency mentions pass on a much lower floor.
_LISTING_PRICE_MIN_FOREIGN = 20.0
_LISTING_PRICE_MAX = 2_000_000_000.0


def _extract_listing_prices(html):
    """[{value, period, per_sqm, currency}] — price mentions inside a fetched listing page."""
    if not html:
        return []
    found = {}
    for pattern, pattern_currency in _LISTING_PRICE_PATTERNS:
        for match in pattern.finditer(html):
            raw = (match.group(1) or '').translate(_ARABIC_DIGITS)
            raw = raw.replace(',', '').replace(' ', '')
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            window = html[max(0, match.start() - 100):match.end() + 100]
            if pattern_currency in ('TOK1', 'ISO1'):
                currency = market_study._canonical_price_currency(match.group(1))
            elif pattern_currency in ('TOK2', 'ISO2'):
                currency = market_study._canonical_price_currency(match.group(2))
            elif pattern_currency:
                currency = pattern_currency
            else:
                declared = re.search(
                    r'"priceCurrency"\s*:\s*"?([A-Za-z]{3})"?',
                    html[max(0, match.start() - 300):match.end() + 300])
                # A bare "price": N with no declared unit is a number, not a
                # price — points, ids and unrelated offers serialize the same
                # way. Reading one as SAR fabricates the row's figure.
                if not declared:
                    continue
                currency = market_study._canonical_price_currency(declared.group(1))
            if not currency:
                continue
            if currency != 'SAR' and not market_study.price_fx_to_sar(currency):
                # A foreign mention we cannot convert cannot sit in the (ر.س)
                # cell — this also drops the ISO pattern's false positives.
                continue
            floor = _LISTING_PRICE_MIN if currency == 'SAR' else _LISTING_PRICE_MIN_FOREIGN
            if not (floor <= value <= _LISTING_PRICE_MAX):
                continue
            if re.search(r'سنوي|سنة|annual|yearly|per\s*year|/yr', window, re.IGNORECASE):
                period = 'سنوي'
            elif re.search(r'شهري|شهر|monthly|per\s*month|/mo', window, re.IGNORECASE):
                period = 'شهري'
            elif re.search(r'ليلة|per\s*night|nightly', window, re.IGNORECASE):
                period = 'ليلة'
            else:
                period = ''
            per_sqm = bool(re.search(r'متر|sqm|م²|per\s*sq', window, re.IGNORECASE))
            found[(value, period, per_sqm, currency)] = {
                'value': value, 'period': period, 'per_sqm': per_sqm, 'currency': currency}
    return list(found.values())


def _fill_competitor_price_from_listings(row, urls, pages=None):
    """Derive a grounded price from the retrieved pages themselves.

    The verify searches leave the price fields empty when the model's reply
    omits the figure — but the retrieved evidence carries it in two places:
    the citation content the search provider already returned (free, works
    even on bot-walled portals) and the fetched page markup for pages that
    are readable directly. Only a page that names THIS competitor in its
    title or URL may yield a price — an index page that drops the name once
    among a hundred listings would otherwise stamp the portal's whole-stock
    median on every competitor it mentions. Banned classifieds hosts (all
    but aqar.fm, and trivago for hotel rows) never feed a row at all.
    The median of the mentions becomes a «متوسط» price; a single mention
    keeps its own type. price_listed flags it as listing evidence, not an
    officially documented tariff. A row with no project-specific page keeps
    its price fields empty — an empty cell is honest, a borrowed median is
    not.
    """
    dead = {str(item).strip().casefold() for item in (row.get('dead_source_urls') or [])}
    page_content = {}
    page_titles = {}
    for page in pages or []:
        if isinstance(page, dict):
            page_url = str(page.get('url') or '').strip()
            page_content[page_url] = str(page.get('content') or '')
            page_titles[page_url] = str(page.get('title') or '')
    operation = str(row.get('operation_type') or '').strip() or 'أخرى'
    tokens = _competitor_name_tokens(row.get('name'))
    mentions = []
    searched = 0
    unreadable = 0
    for url in list(dict.fromkeys(urls or []))[:4]:
        url_key = str(url).strip().casefold()
        if url_key in dead:
            continue
        if market_study.banned_competitor_listing_host(url, operation):
            continue
        # The citation excerpt is searched first — fetching is the fallback
        # for pages the provider did not quote (or quoted too thinly).
        html = page_content.get(url) or ''
        if not html:
            html, _err = _read_market_source_page(url)
        if not html:
            unreadable += 1
            continue
        title = page_titles.get(url) or market_study._html_title(html)
        if tokens and not all(token in market_study._fold_choice(f'{title} {url}')
                              for token in tokens):
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
    # A median can only live inside one currency — mixing € and SAR figures
    # into one number is a fabrication. SAR mentions win; otherwise the first
    # foreign currency carries its own pool.
    sar_mentions = [m for m in pool if (m.get('currency') or 'SAR') == 'SAR']
    if sar_mentions:
        currency = 'SAR'
        pool = sar_mentions
    else:
        currency = next((m.get('currency') for m in pool if m.get('currency')), 'SAR')
        pool = [m for m in pool if (m.get('currency') or 'SAR') == currency] or pool
    orig_values = sorted({m['value'] for m in pool})
    per_sqm = any(m['per_sqm'] for m in pool)
    used_urls = list(dict.fromkeys(m['url'] for m in pool))
    source_currency = currency
    fx_rate = (market_study.price_fx_to_sar(source_currency)
               if source_currency != 'SAR' else None)
    # The (ر.س) column stores riyals — convert at a fixed rate and keep the
    # source figure in price_cache.original_* rather than relabeling it.
    values = (sorted(int(round(v * fx_rate)) for v in orig_values)
              if fx_rate else orig_values)
    if fx_rate:
        currency = 'SAR'
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
    row['price_currency'] = currency
    if fx_rate:
        orig_median = int(round(
            orig_values[len(orig_values) // 2] if len(orig_values) % 2
            else (orig_values[len(orig_values) // 2 - 1]
                  + orig_values[len(orig_values) // 2]) / 2))
        cache = row.get('price_cache') if isinstance(row.get('price_cache'), dict) else {}
        cache['original_currency'] = source_currency
        if field_key == 'price_value':
            cache['original_price_value'] = str(orig_median)
        else:
            cache['original_price_from'] = str(int(orig_values[0]))
            cache['original_price_to'] = str(int(orig_values[-1]))
        row['price_cache'] = cache
    field_sources = market_study.competitor_field_sources(row)
    bucket = field_sources.setdefault(field_key, [])
    for url in used_urls:
        if url not in bucket:
            bucket.append(url)
    row['field_sources'] = field_sources
    row['source_urls'] = list(dict.fromkeys(
        market_study.competitor_source_urls(row) + used_urls))[:6]
    if fx_rate:
        marker = (f'السعر متوسط إعلانات مسترجعة محوّل من {source_currency} '
                  f'(≈{fx_rate:g} ر.س) — غير موثق رسميًا')
    elif currency == 'SAR':
        marker = 'السعر متوسط إعلانات مسترجعة — غير موثق رسميًا'
    else:
        marker = f'السعر متوسط إعلانات مسترجعة بعملة {currency} — غير موثق رسميًا'
    note = str(row.get('note') or '').strip()
    if marker not in note:
        row['note'] = f'{note} — {marker}' if note else marker
    return True


def _pages_as_agent_response(pages):
    """Pool pages in the OpenRouter reply shape ``_market_citation_pages``
    reads — url_citation annotations — so stored evidence absorbs through the
    exact same code path as a live browse run (``_absorb_verify_response``).
    """
    annotations = []
    for page in pages or []:
        url = str((page or {}).get('url') or '').strip()
        if not url:
            continue
        annotations.append({'url_citation': {
            'url': url,
            'title': str(page.get('title') or ''),
            'content': str(page.get('content') or ''),
        }})
    return {'choices': [{'message': {'role': 'assistant', 'content': '',
                                    'annotations': annotations}}]}


def _verify_row_from_pool(row, payload, data, evidence_pool):
    """Match a competitor row against pages the job already retrieved.

    The source plan and the earlier browse calls leave every fetched page in
    the shared pool; a row whose distinctive name tokens appear in stored
    pages absorbs them as evidence and verifies with zero new searches.
    Returns True only when the row was actually marked verified — a pool hit
    that absorbs to nothing (e.g. all matches on foreign-market hosts) leaves
    the row for the next phase.
    """
    if evidence_pool is None or not isinstance(row, dict):
        return False
    tokens = _competitor_name_tokens(row.get('name'))
    if not tokens:
        return False
    needed = 1 if len(tokens) == 1 else 2
    try:
        pages = evidence_pool.pages_for_name(tokens, needed)
    except Exception:
        pages = []
    if not pages:
        return False
    offer_lang = slide_engine.resolve_offer_lang(data)
    matched_pages = {}
    matched, official = _absorb_verify_response(
        row, _pages_as_agent_response(pages), tokens, needed, matched_pages,
        offer_lang=offer_lang)
    matched = list(dict.fromkeys(matched))
    if not matched:
        return False
    row.pop('no_search_evidence', None)
    if not any(str(row.get(key) or '').strip()
               for key in ('price_value', 'price_from', 'price_to')):
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
    return True


def _verify_bind_browser(browser_module):
    """Bind this pool thread's BrowserWorker once — the module-level helpers
    then reuse it for every fetch instead of paying a Chromium launch per
    call. No-op where the thread-local helper hasn't landed; the helpers
    one-shot a browser per call in that shape."""
    getter = getattr(browser_module, 'thread_local_browser', None)
    if callable(getter):
        try:
            getter()
        except Exception:
            pass


def _verify_thread_browser():
    """The calling thread's own BrowserWorker — Playwright's sync API is
    one-worker-per-thread, so verify-pool threads never share the job
    session. None until the thread-local helper exists."""
    try:
        import browser as _browser_module
        getter = getattr(_browser_module, 'thread_local_browser', None)
        if callable(getter):
            worker = getter()
            if worker is not None:
                return worker
    except Exception:
        pass
    return None


def _verify_agent_session():
    """The verify thread's browser for the agent's ``session=`` — resolved
    only when ``run_browse_agent`` accepts the parameter, so an agent build
    without it never pays a Chromium launch it cannot use. None means the
    agent opens its own per-run session, as before."""
    try:
        import agent as _agent_module
        if not _agent_run_accepts(_agent_module, 'session'):
            return None
    except Exception:
        return None
    return _verify_thread_browser()


def _close_verify_thread_browser():
    """Release a verify thread's browser — no-op while the module-level
    helpers (one-shot, self-closing) carry the fallback."""
    try:
        import browser as _browser_module
        close = getattr(_browser_module, 'close_thread_browser', None)
        if callable(close):
            close()
    except Exception:
        pass


def _verify_row_deterministic(row, payload, data, evidence_pool, deadline):
    """Phase 2: one deterministic «name city» search on the thread's browser,
    top hits opened into the pool, then a re-match — the decision stays in
    Python, no model round involved. Returns True when the row verified.

    Fetches go through browser.py's contract helpers (``web_search`` /
    ``open_url``): they reuse the thread's bound worker — or the job session
    on the main thread — and one-shot a browser only when nothing is bound.
    """
    if evidence_pool is None:
        return False
    name = str(row.get('name') or '').strip()
    tokens = _competitor_name_tokens(name)
    if not name or not tokens:
        return False
    if _market_deadline_hit(deadline):
        return False
    try:
        import browser as _browser_module
    except Exception:
        return False
    search_fn = getattr(_browser_module, 'web_search', None)
    open_fn = getattr(_browser_module, 'open_url', None)
    if not callable(search_fn):
        return False
    bound = [False]

    def _bind():
        if not bound[0]:
            bound[0] = True
            _verify_bind_browser(_browser_module)

    city = str(payload.get('city') or '').strip() or 'السعودية'
    query = f'«{name}» {city}'
    try:
        cached = evidence_pool.query_results(query)
    except Exception:
        cached = None
    if cached is not None:
        results = cached
    else:
        _bind()
        try:
            results = search_fn(query)
        except Exception:
            results = []
        results = [item for item in (results or []) if isinstance(item, dict)]
        try:
            evidence_pool.add_query(query, results)
        except Exception:
            pass
    for item in results[:3]:
        url = str(item.get('url') or '').strip()
        if not url or not callable(open_fn):
            continue
        if market_study.banned_competitor_listing_host(url, row.get('operation_type')):
            continue
        if _market_deadline_hit(deadline):
            break
        try:
            if evidence_pool.get_page(url) is not None or evidence_pool.page_failed(url):
                continue
        except Exception:
            pass
        _bind()
        try:
            opened = open_fn(url)
        except Exception as exc:
            opened = {'error': str(exc) or exc.__class__.__name__}
        opened = opened if isinstance(opened, dict) else {}
        try:
            if opened.get('error'):
                evidence_pool.mark_failed(url, str(opened.get('error')))
            else:
                evidence_pool.add_page(
                    url, title=str(opened.get('title') or ''),
                    content=str(opened.get('text') or opened.get('content') or ''),
                    final_url=str(opened.get('final_url') or url), via='browser')
        except Exception:
            pass
    return _verify_row_from_pool(row, payload, data, evidence_pool)


def _verify_competitor_row_pooled(row, payload, data, tenant_id=None,
                                  evidence_pool=None, deadline=None,
                                  on_event=None):
    """Pool-thread phases: deterministic search first, the browse agent only
    for rows still without any evidence. An expired job deadline is an honest
    search_not_run — the row never silently skipped its verdict."""
    if _market_deadline_hit(deadline):
        row['verify_state'] = 'search_not_run'
        row['verify_provider_error'] = 'deadline_exceeded'
        return
    if evidence_pool is not None and _verify_row_deterministic(
            row, payload, data, evidence_pool, deadline):
        return
    _verify_competitor_row(row, payload, data, tenant_id=tenant_id,
                           evidence_pool=evidence_pool, deadline=deadline,
                           session=_verify_agent_session(), on_event=on_event)


def _verify_competitor_rows(rows, payload, data, tenant_id=None, progress=None,
                            evidence_pool=None, deadline=None, band=(52, 70)):
    report = progress if callable(progress) else (lambda *_args: None)
    # Manual rows verify too: fill mode exists to complete the cells the user
    # left empty, and the per-name search is the only priced lookup they get.
    targets = [row for row in (rows or [])
               if isinstance(row, dict)
               and str(row.get('name') or '').strip()]
    if not targets:
        return
    lo, hi = band
    done = [0]
    total = len(targets)

    def _floor():
        return lo + int((hi - lo) * done[0] / total)

    def _tick(row):
        done[0] += 1
        report(_floor(),
               f'التحقق من «{row.get("name") or "منافس"}» ({done[0]} من {total})...')

    def _row_event(row, event):
        # A row's agent run can browse for minutes between ticks — narrate its
        # searches/opens at the current floor so the bar never looks dead.
        if not isinstance(event, dict) or event.get('phase') != 'tool':
            return
        hint = str(event.get('hint') or '').strip()[:80]
        tool = str(event.get('tool') or '')
        verb = ('يبحث عن' if tool == 'web_search'
                else 'يفتح صفحة' if tool == 'open_url' else 'ينفذ')
        report(_floor(),
               f'التحقق من «{row.get("name") or "منافس"}» — {verb} {hint}'.rstrip())

    # Phase 1 — pure matching, sequential: pages the source plan and earlier
    # browse calls already fetched carry most names; those rows absorb the
    # stored evidence and verify without a single new search.
    pending = []
    for row in targets:
        if evidence_pool is not None and not _market_deadline_hit(deadline):
            try:
                if _verify_row_from_pool(row, payload, data, evidence_pool):
                    _tick(row)
                    continue
            except Exception as exc:
                print(f"[MARKET STUDY] pool verify failed for "
                      f"«{row.get('name') or 'منافس'}»: {exc}")
        pending.append(row)

    # Phases 2+3 on the pool — each thread drives its own browser.
    def verify(row):
        try:
            # Pool threads share no Flask context — without one the key gate
            # misreads every company as unkeyed and db-backed helpers die.
            with _worker_app_context():
                _verify_competitor_row_pooled(
                    row, payload, data, tenant_id=tenant_id,
                    evidence_pool=evidence_pool, deadline=deadline,
                    on_event=lambda event: _row_event(row, event))
        finally:
            _close_verify_thread_browser()
            _tick(row)

    if pending:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as workers:
            list(workers.map(verify, pending))
