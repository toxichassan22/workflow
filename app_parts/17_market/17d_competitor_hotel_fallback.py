"""Hotel price/area fallback through native web search.

Booking answers the agent's browser with a bot page, so a hotel row can have
a name and a Booking URL but no nightly price and no room size. The market
summary already researches through OpenRouter's native web search; this part
uses the same tool for one hotel row at a time, accepts a value only when the
page that carries it was actually retrieved, and labels the row as a fallback
source so the client never mistakes it for Booking data.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from numeric_precision import format_precise_number

_FALLBACK_MAX_ROWS = 10
_FALLBACK_WORKERS = 4
_FALLBACK_MAX_TOKENS = 1800
_FALLBACK_SOURCE_LABEL = 'مصدر بديل — Booking محجوب'


def _row_has_price(row):
    return any(str((row or {}).get(key) or '').strip()
               for key in ('price_value', 'price_from', 'price_to'))


def _row_has_area(row):
    return bool(str((row or {}).get('area_sqm') or '').strip()
                or str((row or {}).get('area_from') or '').strip())


def _hotel_fallback_prompt(row, payload, offer_lang='ar'):
    city = str((payload or {}).get('city') or '').strip() or 'السعودية'
    district = str((payload or {}).get('district') or '').strip()
    stars = str((row or {}).get('hotel_stars') or '').strip()
    name = str((row or {}).get('name') or '').strip()
    place = f'{city} — {district}' if district else city
    star_line = f' مصنّف {stars} نجوم.' if stars else ''
    return (
        f'نفّذ بحث ويب الآن عن فندق «{name}» في {place}.{star_line}\n'
        'أعد JSON فقط بهذا الشكل:\n'
        '{"name":"","price_value":"","price_from":"","price_to":"",'
        '"price_currency":"","price_type":"سعر الليلة أو يبدأ من أو نطاق أسعار الغرف",'
        '"area_from":"","area_to":"","area_sqm":"",'
        '"price_source_url":"","area_source_url":"","source_name":""}\n'
        'ابحث عن سعر الليلة المعروض ومساحة الغرفة/الوحدة بالمتر المربع. '
        'لكل رقم استخدم رابط الصفحة التي ظهر فيها فعليًا في نتائج البحث المسترجعة؛ '
        'لا تكتب رابطًا من ذاكرتك ولا رابطًا لم تفتحه. '
        'لو السعر من صفحة قائمة فنادق فاجعله price_type="يبدأ من" وسجّل رابط الصفحة. '
        'لو المساحة من صفحة غرف/تفاصيل استخدم رابطها. لا تخمّن أي رقم أو رابط.'
    )


def _fallback_number(value):
    text = str(value or '').strip().translate(_ARABIC_DIGITS)
    if not text:
        return ''
    match = re.search(r'[0-9][0-9.,]*', text)
    if not match:
        return ''
    return match.group(0).replace(',', '')


def _fallback_area_range(parsed):
    """(from, to) or (value, '') from the model's area fields."""
    low = _fallback_number(parsed.get('area_from'))
    high = _fallback_number(parsed.get('area_to'))
    if low and high:
        return low, high
    raw = str(parsed.get('area_sqm') or '').strip()
    match = re.match(r'\s*([0-9][0-9.,]*)\s*[-–—]\s*([0-9][0-9.,]*)', raw)
    if match:
        return (match.group(1).replace(',', ''),
                match.group(2).replace(',', ''))
    value = _fallback_number(parsed.get('area_sqm')) or low or high
    return value, ''


_FALLBACK_BLOCKED_HOST_TOKENS = (
    'bayut', 'wasalt', 'dealapp', 'dubizzle', 'aqar.fm',
    'instagram', 'facebook', 'tiktok', 'twitter', 'youtube',
)


def _fallback_source_url(parsed, key, citations):
    url = str(parsed.get(key) or '').strip()
    if not url or url not in (citations or set()):
        return ''
    host = market_study._source_host(url)
    if any(token in host for token in _FALLBACK_BLOCKED_HOST_TOKENS):
        return ''
    if host == 'x.com' or host.endswith('.x.com'):
        return ''
    return url


def _apply_fallback_price(row, parsed, source_url, offer_lang='ar'):
    value = _fallback_number(parsed.get('price_value'))
    low = _fallback_number(parsed.get('price_from'))
    high = _fallback_number(parsed.get('price_to'))
    if not (value or low or high):
        return ''
    currency = market_study._canonical_price_currency(
        parsed.get('price_currency') or '')
    fx_rate = (market_study.price_fx_to_sar(currency)
               if currency and currency != 'SAR' else None)
    if currency and currency != 'SAR' and not fx_rate:
        return ''
    options = market_study.price_types_for_operation(
        str(row.get('operation_type') or '').strip(), offer_lang)
    price_type = str(parsed.get('price_type') or '').strip()
    range_type = next((option for option in options
                       if option in market_study.RANGE_PRICE_TYPES
                       or option in market_study.RANGE_PRICE_TYPES_EN), '')
    single_type = next((option for option in options
                        if option in ('سعر الليلة', 'Nightly Rate')), '')
    starting_type = next((option for option in options
                          if option in ('يبدأ من', 'Starting From')), '')
    is_range = (bool(low and high)
                and price_type not in ('يبدأ من', 'Starting From'))
    if is_range:
        row['price_from'] = low
        row['price_to'] = high
        row['price_type'] = (price_type if price_type in options
                             and (price_type in market_study.RANGE_PRICE_TYPES
                                  or price_type in market_study.RANGE_PRICE_TYPES_EN)
                             else range_type or price_type or (options[0] if options else ''))
        field_keys = ('price_from', 'price_to')
    else:
        row['price_value'] = value or low or high
        if price_type in options:
            row['price_type'] = price_type
        elif starting_type and (parsed.get('price_type') in ('يبدأ من', 'Starting From')
                                or not value and low):
            row['price_type'] = starting_type
        else:
            row['price_type'] = single_type or price_type or (options[0] if options else '')
        field_keys = ('price_value',)
    row['price_currency'] = currency or 'SAR'
    cache = row.get('price_cache') if isinstance(row.get('price_cache'), dict) else {}
    if fx_rate:
        for key in ('price_value', 'price_from', 'price_to'):
            current = str(row.get(key) or '').strip()
            if not current:
                continue
            try:
                row[key] = format_precise_number(float(current) * fx_rate,
                                                 grouped=False)
            except (TypeError, ValueError):
                continue
            cache[f'original_{key}'] = current
        cache['original_currency'] = currency
        row['price_currency'] = 'SAR'
    for key in field_keys:
        cache[key] = row.get(key, '')
    row['price_cache'] = cache
    row['price_listed'] = True
    field_sources = market_study.competitor_field_sources(row)
    for key in field_keys:
        urls = field_sources.setdefault(key, [])
        if source_url not in urls:
            urls.append(source_url)
    row['field_sources'] = field_sources
    return source_url


def _apply_fallback_area(row, parsed, source_url):
    low, high = _fallback_area_range(parsed)
    if not low:
        return ''
    try:
        low_value, high_value = float(low), float(high or low)
    except (TypeError, ValueError):
        return ''
    if not (5 <= low_value <= 500 and 5 <= high_value <= 500):
        return ''
    if high and high_value > low_value:
        row['area_mode'] = 'range'
        row['area_from'] = low
        row['area_to'] = high
        field_keys = ('area_from', 'area_to')
    else:
        row['area_mode'] = 'fixed'
        row['area_sqm'] = low
        field_keys = ('area_sqm',)
    cache = row.get('area_cache') if isinstance(row.get('area_cache'), dict) else {}
    cache.update({
        'area_sqm': row.get('area_sqm', ''),
        'area_from': row.get('area_from', ''),
        'area_to': row.get('area_to', ''),
    })
    row['area_cache'] = cache
    field_sources = market_study.competitor_field_sources(row)
    for key in field_keys:
        urls = field_sources.setdefault(key, [])
        if source_url not in urls:
            urls.append(source_url)
    row['field_sources'] = field_sources
    return source_url


def _apply_hotel_fallback_evidence(row, parsed, citations, offer_lang='ar'):
    if not isinstance(row, dict) or not isinstance(parsed, dict):
        return False
    shared = _fallback_source_url(parsed, 'source_url', citations)
    price_source = (_fallback_source_url(parsed, 'price_source_url', citations)
                    or shared)
    area_source = (_fallback_source_url(parsed, 'area_source_url', citations)
                   or shared)
    applied = []
    if not _row_has_price(row) and price_source:
        source = _apply_fallback_price(
            row, parsed, price_source, offer_lang=offer_lang)
        if source:
            applied.append(source)
    if not _row_has_area(row) and area_source:
        source = _apply_fallback_area(row, parsed, area_source)
        if source:
            applied.append(source)
    if not applied:
        return False
    source_name = str(parsed.get('source_name') or '').strip()
    label = f'{source_name} — {_FALLBACK_SOURCE_LABEL}' if source_name else _FALLBACK_SOURCE_LABEL
    row['fallback_source'] = True
    row['fallback_source_name'] = source_name
    row['fallback_source_urls'] = list(dict.fromkeys(applied))
    row['verify_state'] = 'verified'
    row.pop('verify_provider_error', None)
    row.pop('no_search_evidence', None)
    if not _manual_source_locked(row):
        row['source'] = label
        row['source_urls'] = list(dict.fromkeys(
            market_study.competitor_source_urls(row) + applied))[:6]
        if not str(row.get('source_url') or '').strip():
            row['source_url'] = market_study.prefer_specific_source_url(*applied)
    note = f'{label}: {", ".join(dict.fromkeys(applied))}'
    existing_note = str(row.get('notes') or '').strip()
    if note not in existing_note:
        row['notes'] = f'{existing_note} — {note}' if existing_note else note
    return True


def _hotel_native_fallback_search(row, payload, data, tenant_id=None,
                                  deadline=None):
    if not isinstance(row, dict) or not _hotel_competitor_row(row):
        return False
    if _row_has_price(row) and _row_has_area(row):
        return False
    if _market_deadline_hit(deadline):
        return False
    offer_lang = slide_engine.resolve_offer_lang(data)
    response = _browse_agent_call(
        'أنت باحث سوق. يجب أن تنفذ بحث ويب قبل الإجابة، ولا تخترع رابطًا أو رقمًا.',
        _hotel_fallback_prompt(row, payload, offer_lang),
        _usage_ctx('market', data, tenant_id=tenant_id),
        local_tools=False,
        server_tools=[{'type': 'openrouter:web_search'}],
        tool_choice={'type': 'openrouter:web_search'},
        max_steps=2, max_tokens=_FALLBACK_MAX_TOKENS,
        reasoning_effort='low', deadline=deadline)
    parsed, parse_error = _parse_market_model_json(response)
    if parse_error or not isinstance(parsed, dict):
        return False
    citations = set(_market_citation_urls(response))
    if not citations:
        return False
    return _apply_hotel_fallback_evidence(
        row, parsed, citations, offer_lang=offer_lang)


def _fill_hotel_rows_with_native_search(rows, payload, data, tenant_id=None,
                                        progress=None, deadline=None,
                                        band=(70, 74)):
    """Fill empty hotel price/area cells from cited native-search pages."""
    report = progress if callable(progress) else (lambda *_args: None)
    targets = [row for row in rows or []
               if isinstance(row, dict) and _hotel_competitor_row(row)
               and not (_row_has_price(row) and _row_has_area(row))]
    if not targets:
        return 0
    targets = targets[:_FALLBACK_MAX_ROWS]
    lo, hi = band
    done = [0]
    total = len(targets)
    report(lo, f'البحث عن سعر ومساحة {total} فندق من مصادر بديلة...')

    def _worker(row):
        try:
            with _worker_app_context():
                return _hotel_native_fallback_search(
                    row, payload, data, tenant_id=tenant_id, deadline=deadline)
        except Exception as exc:
            print(f"[MARKET STUDY] hotel fallback failed for "
                  f"«{row.get('name') or 'فندق'}»: {exc}")
            return False

    filled = 0
    with ThreadPoolExecutor(
            max_workers=min(_FALLBACK_WORKERS, total)) as workers:
        futures = [workers.submit(_worker, row) for row in targets]
        for future in as_completed(futures):
            done[0] += 1
            try:
                if future.result():
                    filled += 1
            except Exception:
                pass
            report(lo + int((hi - lo) * done[0] / total),
                   f'اكتمل بحث بديل لفندق ({done[0]} من {total})...')
    if filled:
        print(f'[MARKET STUDY] hotel fallback filled {filled}/{total} rows')
    return filled
