from numeric_precision import format_precise_number

import booking_rooms
import hotel_stay


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


def _manual_source_locked(row):
    """True when the client typed, replaced or cleared a row's source link.

    Their choice is authoritative: verification and citation passes may still
    record evidence in ``field_sources``, but must not put a URL back into the
    visible source or replace the one the client entered.
    """
    return bool(isinstance(row, dict) and (
        row.get('source_url_manual') or row.get('sourceUrlManual')))


def _browse_agent_call(system_prompt, user_content, usage_ctx=None, model=None,
                       evidence_pool=None, deadline=None, session=None,
                       **agent_kwargs):
    """One self-hosted browse-agent run for a market web task.

    The task model itself drives the loop — it decides the searches and which
    pages to open, the headless-Chromium workers execute them, and every page
    actually read rides back as a url_citation annotation. Returns the agent's
    OpenRouter-shaped reply or an ``{'error': ...}`` dict; never raises. When
    the local search layer never ran (a blocked/CAPTCHA search engine), the
    competitor scan makes one owner-ordered provider-native fallback on
    MARKET_STUDY_MODEL; a search that ran and returned zero does not.
    ``agent_kwargs`` (search_budget,
    max_steps, max_tokens, reasoning_effort) pass straight through to
    run_browse_agent, and so do the job-scoped ``evidence_pool``/``deadline``/
    ``session`` — once the agent signature carries them.

    The market research rides ``MARKET_STUDY_MODEL`` (the configured market
    model). A caller must NOT pass a model of its own: every market search
    answered on a different brain than the one the owner configured, and the
    price verification stopped being the same mind that found the page.
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
                             ('cancel_event', forwarded.pop('cancel_event', None)),
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
                        url, row.get('operation_type'), row.get('project_type'))):
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
    _apply_verified_competitor_area(row, parsed, set(prompt_matched))
    return prompt_matched, official


_HOTEL_VALUE_KEYS = (
    'price_value', 'price_from', 'price_to', 'price_type', 'price_currency',
    'price_cache', 'price_listed',
    'area_sqm', 'area_from', 'area_to', 'area_mode', 'area_cache',
    'fallback_source', 'fallback_source_name', 'fallback_source_urls',
)
_HOTEL_VALUE_SOURCE_KEYS = (
    'price_value', 'price_from', 'price_to',
    'area_sqm', 'area_from', 'area_to',
)


def _clear_ai_hotel_value_fields(row):
    """Drop AI hotel price/area before verification.

    The deterministic Booking block is the only allowed writer for an AI
    hotel row. Clearing here prevents a discovery-model figure (or a generic
    text/listing fill) from surviving when no Booking block is found.
    """
    if not isinstance(row, dict) or row.get('row_source') in ('manual', 'booking'):
        return
    folded = market_study._fold_choice(str(row.get('operation_type') or ''))
    if not any(token in folded for token in ('فندقي', 'فندق', 'hotel', 'hospitality')):
        return
    for key in _HOTEL_VALUE_KEYS:
        row.pop(key, None)
    field_sources = market_study.competitor_field_sources(row)
    for key in _HOTEL_VALUE_SOURCE_KEYS:
        field_sources.pop(key, None)
    row['field_sources'] = field_sources


def _apply_booking_rate_block(row, matched_pages, offer_lang='ar'):
    """Apply the deterministic Booking room block to an AI hotel row.

    The block is the only source that states the room-price range for the
    stay, its area and the informational current price/taxes. The model's JSON
    and the generic listing fill can
    pick another rate plan for the same area, so the block wins for AI rows;
    a row the user typed is never overwritten.
    """
    if not isinstance(row, dict) or not isinstance(matched_pages, dict):
        return False
    if row.get('row_source') == 'manual':
        return False
    folded = market_study._fold_choice(str(row.get('operation_type') or ''))
    if not any(token in folded for token in ('فندقي', 'فندق', 'hotel', 'hospitality')):
        return False
    rate = None
    page_url = ''
    for url, page in matched_pages.items():
        parsed = booking_rooms.parse_rate_block(
            str((page or {}).get('content') or ''))
        if parsed:
            rate = parsed
            page_url = str(url or '')
            break
    if not rate or rate.get('price') is None:
        return False
    source_url = str(rate.get('source_url') or page_url or '').strip()
    if 'booking.com/hotel/' not in source_url:
        source_url = page_url or source_url
    currency = market_study._canonical_price_currency(
        rate.get('currency') or 'SAR') or 'SAR'
    value = rate.get('price')
    tax_included = bool(rate.get('tax_included'))
    price_from = rate.get('price_from')
    price_to = rate.get('price_to')
    if price_from is None and price_to is None:
        price_from = price_to = booking_rooms.whole_riyal(value)
    price_from = price_from or value
    price_to = price_to or price_from
    cache = row.get('price_cache') if isinstance(row.get('price_cache'), dict) else {}
    if currency != 'SAR':
        fx_rate = market_study.price_fx_to_sar(currency)
        if not fx_rate:
            return False
        cache['original_currency'] = currency
        cache['original_price_value'] = format_precise_number(
            float(value), grouped=False)
        cache['original_price_from'] = format_precise_number(
            float(price_from), grouped=False)
        cache['original_price_to'] = format_precise_number(
            float(price_to), grouped=False)
        price_from = float(price_from) * fx_rate
        price_to = float(price_to) * fx_rate
    row.pop('price_value', None)
    row['price_from'] = format_precise_number(float(price_from), grouped=False)
    row['price_to'] = format_precise_number(float(price_to), grouped=False)
    options = market_study.price_types_for_operation('تشغيل فندقي', offer_lang)
    range_type = next(
        (option for option in options
         if option in market_study.RANGE_PRICE_TYPES
         or option in market_study.RANGE_PRICE_TYPES_EN),
        options[0])
    row['price_type'] = range_type
    row['price_currency'] = 'SAR'
    row['price_listed'] = True
    cache.update({
        'price_from': row['price_from'],
        'price_to': row['price_to'],
        'booking_current_price': rate.get('current_price'),
        'booking_taxes': rate.get('taxes'),
        'booking_current_total': rate.get('current_price_including_tax'),
        'booking_tax_included': tax_included,
        'booking_currency': currency,
        'booking_room_name': rate.get('room_name'),
        'booking_rate_policy': rate.get('rate_policy'),
        'booking_source_url': source_url,
    })
    row['price_cache'] = cache
    area = rate.get('area_sqm')
    if area is not None and 5 <= float(area) <= 500:
        row['area_mode'] = 'fixed'
        row['area_sqm'] = format_precise_number(float(area), grouped=False)
        area_cache = row.get('area_cache') if isinstance(row.get('area_cache'), dict) else {}
        area_cache['area_sqm'] = row['area_sqm']
        row['area_cache'] = area_cache
    field_sources = market_study.competitor_field_sources(row)
    for key in ('price_from', 'price_to', 'area_sqm'):
        urls = field_sources.setdefault(key, [])
        if source_url and source_url not in urls:
            urls.append(source_url)
    row['field_sources'] = field_sources
    if source_url and not _manual_source_locked(row):
        row['source_urls'] = list(dict.fromkeys(
            market_study.competitor_source_urls(row) + [source_url]))[:6]
        if not str(row.get('source_url') or '').strip():
            row['source_url'] = source_url
    source_en = f' (converted from {currency})' if currency != 'SAR' else ''
    source_ar = f' (محوّل من {currency})' if currency != 'SAR' else ''
    price_text = (row['price_from'] if row['price_from'] == row['price_to']
                  else f"{row['price_from']} - {row['price_to']}")
    stated_taxes = rate.get('taxes')
    if offer_lang == 'en':
        if tax_included and stated_taxes:
            basis = 'taxes and fees removed from the printed figure'
        elif tax_included:
            basis = 'taxes and fees included as the page prints them'
        else:
            basis = 'taxes excluded'
        note = ('Booking original pre-discount room-price range, '
                f'{basis}, for {hotel_stay.stay_nights_label_en()}: '
                f'{price_text} SAR{source_en}.')
    else:
        note = (
            f'نطاق أسعار الغرف مقابل {hotel_stay.stay_nights_label_ar()} '
            f'على Booking '
            f'({booking_rooms.note_basis_ar(tax_included, stated_taxes)}): '
            f'{price_text} ر.س{source_ar}.')
    existing = str(row.get('notes') or '').strip()
    if ('السعر الأصلي قبل الخصم' not in existing
            and 'original pre-discount room-price range' not in existing):
        row['notes'] = f'{existing} — {note}' if existing else note
    row['verify_state'] = 'verified'
    row.pop('verify_provider_error', None)
    row.pop('no_search_evidence', None)
    return True


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
    folded_operation = market_study._fold_choice(operation)
    is_hotel = any(token in folded_operation for token in ('فندقي', 'فندق', 'hotel', 'hospitality'))
    price_rule = (
        'السعر يُقبل فقط إذا ظهر في صفحة قرأتها في هذا البحث، ورابطها يوضع في '
        'price.url — إن لم تجد سعرًا أعد حقول price فارغة ولا تكتب رقمًا من ذاكرتك. '
        'اكتب قيمة السعر وعملته كما وردتا في الصفحة؛ النظام يحوّل السعر إلى الريال '
        'قبل عرضه ويحفظ عملة المصدر للتوثيق. '
    )
    if is_hotel:
        price_rule += (
            'للفندق: استخدم نطاق أسعار الغرف المعروض على Booking من صفحة الفندق '
            '(أقل سعر وأعلى سعر)، وهو السعر الأصلي قبل الخصم كما تطبعه الصفحة. '
            'إذا كانت الصفحة تقول «شامل الضرائب والرسوم» فاكتب الرقم كما هو شاملاً '
            'الضريبة ولا تخصمها، وإذا عرضت الضريبة في سطر منفصل فاكتب سعر الغرفة '
            'بدونها. '
            'لا تجمع أسعار الغرف أو الباقات في متوسط، ولا تعتمد السعر الحالي بعد الخصم. '
            'إذا ظهر قسم ## BOOKING_RATE ## في نص الصفحة فاستخدم '
            'price_range_before_discount و area_range_sqm حرفيًا. '
        )
    else:
        price_rule += (
            'إذا ظهر سعر قبل الخصم وسعر بعده، فاعتمد السعر قبل الخصم ولا تستخدم سعر العرض '
            'أو السعر النهائي بعد الخصم. '
        )
    hotel_rule = ''
    source_rule = (
        'للفنادق، استخدم صفحة الفندق التفصيلية على Booking.com بمسار /hotel/ فقط؛ '
        'صفحات /district/ و/city/ ونتائج البحث العامة لا تثبت الفندق، فلا تفتحها ولا تضعها. '
        'لا تضع روابط مواقع الفندق أو المشغل أو العلامة أو أي منصة أخرى. '
        if is_hotel else
        'لغير الفنادق يمكن استخدام موقع المطور أو المشغل أو إعلان عقار '
        '(sa.aqar.fm) أو خبر موثوق يذكر المشروع بالاسم. '
    )
    official_page_shape = (
        'رابط صفحة Booking.com المطابقة للمنافس إن وُجدت'
        if is_hotel else 'صفحة الموقع الرسمي للمشروع أو مطوّره إن وُجدت'
    )
    area_shape = (
        '"area_sqm": "مساحة الغرفة أو الوحدة بالمتر المربع كما وردت في الصفحة أو فارغ", '
        '"area_url": "رابط الصفحة التي وردت فيها المساحة حرفيًا أو فارغ"')
    if is_hotel:
        hotel_rule = (
            'تحقق من الفندق على Booking.com فقط. '
            'اعتمد صفحة الفندق التفصيلية ذات المسار /hotel/، لا صفحات الحي أو المدينة أو نتائج البحث العامة. '
            'إذا لم يظهر السعر في النتائج، افتح Booking.com بأدوات المتصفح '
            'التفاعلية، وافحص عناصر الصفحة ثم اكتب المدينة والحي في خانة الوجهة ونفّذ '
            'البحث بالضغط على العنصر المناسب. اقرأ السعر من صفحة الفندق نفسها، '
            'ولا تخمّن السعر أو تواريخ الإقامة. '
            'إذا كانت الصفحة تحديًا أمنيًا أو نسخة بوت بلا أسعار، توقف فورًا ولا تُعد المحاولة؛ '
            'أعد النتيجة بدون سعر واذكر أن الصفحة محجوبة. ')
    prompt = (
        f'ابحث في الويب عن المشروع العقاري «{name}» في مدينة {city} بالسعودية.\n'
        f'أرجع JSON فقط: {{"exists": true/false, "official_url": "{official_page_shape}", '
        '"summary": "سطر واحد عن المشروع", '
        + price_shape + ', ' + area_shape + '}.\n' + price_rule +
        source_rule +
        'أي صفحة مسترجعة تذكر المشروع بالاسم تُحتسب دليلًا وفق نوع المنافس، '
        'وروابط منصات الإعلانات الأخرى '
        '(bayut، wasalt، dealapp…) ممنوعة ولا تُعتمد، وكذلك كل روابط '
        'التواصل الاجتماعي (إنستغرام، فيسبوك، تيك توك، إكس، يوتيوب…) — '
        'ليست دليلًا ولا مصدرًا للأسعار فلا تفتحها. '
        + hotel_rule
        + 'ضع في official_url وروابط المصادر الصفحة النهائية التي تعرض المشروع أو الفندق فقط؛ '
        'لا تضع صفحات البحث أو النتائج أو الصفحة الرئيسية. '
        + 'إن لم تجد أي صفحة تذكر هذا المشروع بالاسم أعد exists=false ولا تخمّن روابط.'
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
        usage_ctx,
        search_provider='searxng',
        evidence_pool=evidence_pool, deadline=deadline,
        session=session, reasoning_effort=TEXT_REASONING_EFFORT, on_event=on_event)
    last_error = _chat_error_message(response)
    search_ran_any = False
    if response.get('error') is None:
        if _market_citation_pages(response):
            search_ran_any = True
            # The row's own source page answers before the model's figure is
            # applied — its price is what the client checks against the link.
            _fill_row_price_from_own_source(
                row, pages=_market_citation_pages(response))
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
        # A deterministic refusal (no tenant key, exhausted wallet) is not a
        # search miss: the job reports it instead of a silent, reasonless run.
        if _ai_fatal_error_dict(response) is not None:
            row['verify_provider_fatal'] = True
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
    _apply_booking_rate_block(row, matched_pages, offer_lang=offer_lang)
    row['verify_state'] = 'verified'
    if not _manual_source_locked(row):
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
    if _hotel_competitor_row(row):
        return
    price = parsed.get('price') if isinstance(parsed, dict) else None
    if not isinstance(price, dict):
        price = parsed if isinstance(parsed, dict) else {}
    url = str(price.get('url') or price.get('source_url') or price.get('sourceUrl') or '').strip()
    if not url or url not in (citation_urls or set()):
        return
    if market_study.banned_competitor_listing_host(
            url, row.get('operation_type'), row.get('project_type')):
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
                row[key] = format_precise_number(float(orig) * fx_rate, grouped=False)
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
    if not _manual_source_locked(row):
        row['source_urls'] = list(dict.fromkeys(
            market_study.competitor_source_urls(row) + [url]))


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
    _fill_row_price_from_own_source(row, pages=pages)
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
    _apply_booking_rate_block(row, matched_pages, offer_lang=offer_lang)
    row['verify_state'] = 'verified'
    if not _manual_source_locked(row):
        row['source_urls'] = list(dict.fromkeys(
            market_study.competitor_source_urls(row) + matched))[:6]
        if not str(row.get('source_url') or '').strip():
            row['source_url'] = market_study.prefer_specific_source_url(*row['source_urls'])
    if official and not str(row.get('logo_source_url') or '').strip():
        row['logo_source_url'] = official
        row['logo_official_verified'] = True
    return True


def _verify_bind_browser(browser_module, search_provider='searxng'):
    """Bind this pool thread's BrowserWorker once — the module-level helpers
    then reuse it for every fetch instead of paying a Chromium launch per
    call. No-op where the thread-local helper hasn't landed; the helpers
    one-shot a browser per call in that shape."""
    getter = getattr(browser_module, 'thread_local_browser', None)
    if callable(getter):
        try:
            getter(search_provider=search_provider)
        except Exception:
            pass


def _verify_thread_browser(search_provider='searxng'):
    """The calling thread's own BrowserWorker — Playwright's sync API is
    one-worker-per-thread, so verify-pool threads never share the job
    session. None until the thread-local helper exists."""
    try:
        import browser as _browser_module
        getter = getattr(_browser_module, 'thread_local_browser', None)
        if callable(getter):
            worker = getter(search_provider=search_provider)
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
    return _verify_thread_browser(search_provider='searxng')


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
            _verify_bind_browser(_browser_module, search_provider='searxng')

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
        if market_study.banned_competitor_listing_host(
                url, row.get('operation_type'), row.get('project_type')):
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
               and str(row.get('name') or '').strip()
               # Deterministic sources already carry their page — Booking for
               # hotels, the project page for aqar rows; an agent round would
               # only re-read what is already sourced.
               and row.get('row_source') not in ('booking', 'aqar')]
    if not targets:
        return
    for row in targets:
        _clear_ai_hotel_value_fields(row)
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

    # Phases 2+3 on the pool — each thread drives its own browser. Large
    # projects can have many rows, so allow up to 100 targeted checks at once.
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
        with ThreadPoolExecutor(max_workers=min(100, len(pending))) as workers:
            list(workers.map(verify, pending))
