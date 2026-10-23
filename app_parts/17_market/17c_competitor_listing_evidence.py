"""Retrieved-page evidence: source reads, listing prices and room areas.

Loaded after 17b_competitor_verify.py; the helpers land in the same app globals
the verification pass already uses.
"""

import re

from numeric_precision import format_precise_number


def _hotel_competitor_row(row):
    folded = market_study._fold_choice(str((row or {}).get('operation_type') or ''))
    return any(token in folded for token in ('فندقي', 'فندق', 'hotel', 'hospitality'))


def _apply_verified_competitor_area(row, parsed, citation_urls):
    """Fill an empty unit/room area from a page this verification retrieved.

    Booking shows the room size only after a stay is selected, so the area
    arrives with the same retrieved page as the price. The figure is accepted
    only when its URL was actually cited and the row has no area yet; a hotel
    figure above 500 m² is a tower/property area, not a room, and is dropped.
    """
    if not isinstance(row, dict) or not isinstance(parsed, dict):
        return
    if _hotel_competitor_row(row):
        return
    if (str(row.get('area_sqm') or '').strip()
            or str(row.get('area_from') or '').strip()):
        return
    area = market_study._clean_numeric(
        parsed.get('area_sqm') or parsed.get('areaSqm'))
    price = parsed.get('price') if isinstance(parsed.get('price'), dict) else {}
    url = str(parsed.get('area_url') or parsed.get('areaUrl')
              or price.get('url') or price.get('source_url') or '').strip()
    if not area or not url or url not in (citation_urls or set()):
        return
    if market_study.banned_competitor_listing_host(
            url, row.get('operation_type'), row.get('project_type')):
        return
    try:
        value = float(area)
    except (TypeError, ValueError):
        return
    if value <= 0:
        return
    if _hotel_competitor_row(row) and not 5 <= value <= 500:
        return
    row['area_mode'] = 'fixed'
    row['area_sqm'] = area
    cache = row.get('area_cache') if isinstance(row.get('area_cache'), dict) else {}
    cache['area_sqm'] = area
    row['area_cache'] = cache
    field_sources = market_study.competitor_field_sources(row)
    urls = field_sources.setdefault('area_sqm', [])
    if url not in urls:
        urls.append(url)
    row['field_sources'] = field_sources
    if not _manual_source_locked(row):
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
# folded (همزات swiped, ة to ه) but page text isn't, so each foldable letter
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
# The owner wants the price before the discount. A page that shows a struck
# original beside a promo figure must not be read as two independent prices
# (their median would be invented), and the promo figure alone is not the
# published rate.
_DISCOUNT_ORIGINAL_RE = re.compile(
    r'line-through|text-decoration\s*:\s*line-through'
    r'|قبل\s*الخصم|السعر\s*الأصلي|original\s*price|list\s*price',
    re.IGNORECASE)
_STRIKE_TAG_RE = re.compile(r'<(del|s)\b[^>]*>([\s\S]{0,200}?)</\1>', re.IGNORECASE)
_DISCOUNT_CONTEXT_RE = re.compile(
    r'بعد\s*الخصم|سعر\s*العرض|سعر\s*الخصم|عرض\s*خاص|خصم\s*\d|تخفيض'
    r'|discounted|discount\s*price|offer\s*price|promo\s*price|sale\s*price'
    r'|final\s*price|deal\s*price|after\s*discount',
    re.IGNORECASE)

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
            # "Original" means THIS figure sits inside the struck element; a
            # promo figure whose window merely contains the struck tag is not
            # the original.
            original = any(match.group(0) in tag.group(2)
                           for tag in _STRIKE_TAG_RE.finditer(window))
            if not original and _DISCOUNT_ORIGINAL_RE.search(window) \
                    and not _DISCOUNT_CONTEXT_RE.search(window):
                original = True
            if not original and _DISCOUNT_CONTEXT_RE.search(window):
                # The figure sits in a discount/offer price, not the published
                # rate. It is skipped; the original price in the same page is
                # what the row should carry.
                continue
            found[(value, period, per_sqm, currency)] = {
                'value': value, 'period': period, 'per_sqm': per_sqm,
                'currency': currency, 'original': original}
    return list(found.values())


_AREA_MEASURE_RE = re.compile(
    r'([0-9][0-9.,\u0660-\u0669]{0,6})\s*'
    r'(?:م²|م2|متر مربع|مترمربع|m²|m2|sqm|sq\.?\s?m)(?![0-9A-Za-z])',
    re.IGNORECASE)
_AREA_ROOM_CONTEXT_RE = re.compile(
    r'(غرف|جناح|أجنحة|شقق|شقة|studio|room|suite|apartment)', re.IGNORECASE)
_AREA_NON_ROOM_CONTEXT_RE = re.compile(
    r'(اجتماعات|مؤتمرات|قاعة|meeting|conference|hall|spa|جيم|gym|مسبح|pool|لوبي|lobby)',
    re.IGNORECASE)


def _extract_room_areas(text):
    """Plausible room/unit areas (5–500 m²) found in a retrieved page.

    A figure only counts when its surrounding text names a room, suite, or
    apartment — a meeting hall, spa or pool has an m² figure too, and none of
    them is the unit size the competitor row asks for.
    """
    text = str(text or '').translate(_ARABIC_DIGITS)
    values = []
    for match in _AREA_MEASURE_RE.finditer(text):
        prefix = text[max(0, match.start() - 120):match.start()]
        rooms = list(_AREA_ROOM_CONTEXT_RE.finditer(prefix))
        if not rooms:
            continue
        non_rooms = list(_AREA_NON_ROOM_CONTEXT_RE.finditer(prefix))
        if non_rooms and non_rooms[-1].start() > rooms[-1].start():
            continue
        try:
            value = float(match.group(1).replace(',', '.'))
        except (TypeError, ValueError):
            continue
        if 5 <= value <= 500:
            values.append(value)
    return values




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
    but aqar.fm and Booking.com for hotel rows) never feed a row at all.
    The median of the mentions becomes a «متوسط» price; a single mention
    keeps its own type. price_listed flags it as listing evidence, not an
    officially documented tariff. A row with no project-specific page keeps
    its price fields empty — an empty cell is honest, a borrowed median is
    not.
    """
    if _hotel_competitor_row(row):
        return False
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
        if market_study.banned_competitor_listing_host(
                url, operation, row.get('project_type')):
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
    original_mentions = [item for item in mentions if item.get('original')]
    if original_mentions:
        # A struck-through original is the price before the discount; the
        # promo figure beside it never joins the pool.
        mentions = original_mentions
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
    values = (sorted(v * fx_rate for v in orig_values)
              if fx_rate else orig_values)
    if fx_rate:
        currency = 'SAR'
    median = (values[len(values) // 2] if len(values) % 2
              else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2)
    if operation == 'تشغيل فندقي':
        # The owner compares the original pre-discount nightly rate of the
        # cheapest base room. A range/median across room categories and
        # breakfast/flexible plans reads ~20% high, so keep the lowest
        # original as one nightly rate.
        median = values[0]
    if len(values) > 1:
        if operation == 'إيجار':
            price_type = _option('متوسط إيجار المتر' if per_sqm else 'متوسط إيجار الوحدة')
        elif operation == 'بيع':
            price_type = _option('متوسط سعر المتر' if per_sqm else 'متوسط سعر الوحدة')
        elif operation == 'تشغيل فندقي':
            price_type = _option('سعر الليلة')
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
        row['price_from'] = format_precise_number(values[0], grouped=False)
        row['price_to'] = format_precise_number(values[-1], grouped=False)
        row['price_cache'] = {'price_from': row['price_from'], 'price_to': row['price_to']}
        field_key = 'price_from'
    else:
        row['price_value'] = format_precise_number(median, grouped=False)
        row['price_cache'] = {'price_value': row['price_value']}
        field_key = 'price_value'
    row['price_type'] = price_type
    row['price_listed'] = True
    row['price_currency'] = currency
    if fx_rate:
        if operation == 'تشغيل فندقي':
            orig_median = orig_values[0]
        else:
            orig_median = (orig_values[len(orig_values) // 2] if len(orig_values) % 2
                else (orig_values[len(orig_values) // 2 - 1]
                      + orig_values[len(orig_values) // 2]) / 2)
        cache = row.get('price_cache') if isinstance(row.get('price_cache'), dict) else {}
        cache['original_currency'] = source_currency
        if field_key == 'price_value':
            cache['original_price_value'] = format_precise_number(
                orig_median, grouped=False)
        else:
            cache['original_price_from'] = format_precise_number(orig_values[0], grouped=False)
            cache['original_price_to'] = format_precise_number(orig_values[-1], grouped=False)
        row['price_cache'] = cache
    field_sources = market_study.competitor_field_sources(row)
    bucket = field_sources.setdefault(field_key, [])
    for url in used_urls:
        if url not in bucket:
            bucket.append(url)
    row['field_sources'] = field_sources
    if not _manual_source_locked(row):
        row['source_urls'] = list(dict.fromkeys(
            market_study.competitor_source_urls(row) + used_urls))[:6]
    if operation == 'تشغيل فندقي':
        marker = ('سعر الغرفة الأساسية الأصلي قبل الخصم '
                  + (f'محوّل من {source_currency} (≈{fx_rate:g} ر.س) ' if fx_rate else '')
                  + 'من إعلان مسترجع — غير موثق رسميًا')
    elif fx_rate:
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
