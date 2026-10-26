"""Complete a named hotel competitor from Booking's own search cards.

Manual hotel rows (and legacy AI ones) used to wait on the browse agent,
which returns no page, so the row kept a name and a star class but no
source, price or area. The hotel axes already read a Booking property page
deterministically; this completes a named row the same way: find the card
whose title matches the row's name, open its ``/hotel/`` page, read the
rate block, and write the room ranges onto the row.
"""

import os
import re
import threading
import time
import unicodedata

import booking_destination
import booking_search
from numeric_precision import format_precise_number

_HOTEL_TOKENS = ('فندق', 'فندقي', 'hotel', 'hospitality', 'تشغيل')
NAME_FILL_BUDGET_SECONDS = 300
# The completion phase has its own wall-clock limit: a per-name lookup must
# never grow into the district job's hour-long verification tail.
FILL_PHASE_BUDGET_SECONDS = 330
# Words that describe a property without naming it. They never identify a
# hotel on their own, so they take no part in token matching.
_GENERIC_NAME_TOKENS = {
    'فندق', 'فندقي', 'فندقيه', 'الفندقيه', 'هوتيل', 'شقق', 'شقه', 'منتجع',
    'hotel', 'hotels', 'apartment', 'apartments', 'aparthotel', 'apartotel',
    'suite', 'suites', 'resort', 'residence', 'residences', 'serviced',
    'the', 'and', 'by', 'a', 'an', 'of', 'in', 'at', 'stay', 'stays',
}
_HOTEL_SLUG_RE = re.compile(r'/hotel/[a-z]{2}/([^/?#]+)', re.I)


def _fold_latin(value):
    """Fold Latin accents (Mövenpick -> movenpick) before comparing."""
    decomposed = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def _name_tokens(value):
    folded = booking_search.normalize_label(_fold_latin(value))
    return [token for token in folded.split()
            if len(token) >= 3 and token not in _GENERIC_NAME_TOKENS]


def _tokens_match(wanted_tokens, candidate_text, required=None):
    if not wanted_tokens:
        return False
    have = set(_name_tokens(candidate_text))
    if not have:
        return False
    hits = sum(1 for token in wanted_tokens if token in have)
    needed = required if required is not None else min(2, len(wanted_tokens))
    return hits >= needed


def _hotel_slug_tokens(url):
    match = _HOTEL_SLUG_RE.search(str(url or ''))
    if not match:
        return []
    slug = re.sub(r'(?:\.[a-z-]{2,})+$', '', match.group(1), flags=re.I)
    return _name_tokens(slug.replace('-', ' ').replace('_', ' '))


def _url_matches_name(url, name, city_terms=''):
    """Booking's own URL slug names the property (latin names only).

    Every distinctive word of the name except the city must appear in the
    slug, so a sibling hotel sharing a brand or a city never matches.
    """
    city_tokens = set(_name_tokens(_fold_latin(city_terms)))
    wanted = [token for token in _name_tokens(_fold_latin(name))
              if re.fullmatch(r'[a-z0-9]+', token) and token not in city_tokens]
    slug_tokens = set(_hotel_slug_tokens(url))
    if not wanted or not slug_tokens:
        return False
    return all(token in slug_tokens for token in wanted)


def _is_hotel_row(row):
    folded = str((row or {}).get('operation_type')
                 or (row or {}).get('project_type') or '').casefold()
    if any(token in folded for token in _HOTEL_TOKENS):
        return True
    if str((row or {}).get('hotel_stars')
           or (row or {}).get('stars') or '').strip():
        return True
    return str((row or {}).get('price_type') or '').strip() in (
        'سعر الليلة', 'نطاق أسعار الغرف', 'متوسط سعر الغرفة ADR',
        'الإيراد لكل غرفة RevPAR')


def _needs_booking_fill(row):
    if not isinstance(row, dict) or not _is_hotel_row(row):
        return False
    source = str(row.get('source_url') or '')
    if ('booking.com/hotel/' in source
            and (row.get('price_from') or row.get('price_value'))):
        return False
    return True


def _needs_name_fill(row):
    """A non-hotel row still missing a source, price or area."""
    if not isinstance(row, dict) or not str(row.get('name') or '').strip():
        return False
    if not str(row.get('source_url') or '').strip():
        return True
    return not any(str(row.get(key) or '').strip() for key in (
        'price_value', 'price_from', 'price_to',
        'area_sqm', 'area_from', 'area_to'))


def _card_for_name(cards, name, city_terms=''):
    wanted = booking_search.normalize_label(name)
    if len(wanted) < 4:
        return None
    cards = [card for card in (cards or []) if isinstance(card, dict)]
    for card in cards:
        label = booking_search.normalize_label(card.get('name'))
        if not label:
            continue
        if label == wanted or wanted in label or label in wanted:
            return card
    # Cards often drop a descriptor the client's name carries (a road or a
    # spelling twin like بلس/بلاس). Two distinctive non-city tokens identify
    # the brand without ever matching a sibling that shares only the city.
    city_tokens = set(_name_tokens(_fold_latin(city_terms)))
    wanted_tokens = [token for token in _name_tokens(name)
                     if token not in city_tokens]
    for card in cards:
        if _tokens_match(wanted_tokens, card.get('name'),
                         required=min(2, len(wanted_tokens))):
            return card
    for card in cards:
        if _url_matches_name(card.get('url'), name, city_terms):
            return card
    return None


def _card_from_name_search(session, name, city_terms=''):
    """Booking's own free-text name search: the fill looks a row up by name."""
    query = str(name or '').strip()
    if len(query) < 4:
        return None
    try:
        page = session.open_url(booking_search.build_search_url(query))
    except Exception as exc:
        print(f'[MARKET STUDY] name search failed for {name!r}: {exc}',
              flush=True)
        return None
    hotels = ((page or {}).get('booking_search') or {}).get('hotels') or []
    card = _card_for_name(hotels, name, city_terms)
    print(f'[MARKET STUDY] booking name search name={name!r} '
          f'cards={len(hotels)} '
          f'match={str((card or {}).get("url") or "")[:120]!r}', flush=True)
    return card


def _money(value):
    if value in (None, ''):
        return ''
    return format_precise_number(float(value), grouped=False)


_AREA_MIN_SQM = 8.0
_AREA_MAX_SQM = 2000.0


def _sane_area(value):
    """A hotel room area, or None for an occupancy/room count read by mistake."""
    try:
        number = float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None
    return number if _AREA_MIN_SQM <= number <= _AREA_MAX_SQM else None


def _target_hotel_stars(payload):
    """The hotel star classes the client selected, as strings."""
    stars = set()
    try:
        axes = market_study.normalize_comparison_types(
            (payload or {}).get('comparisonTypes')
            or (payload or {}).get('comparison_types') or [])
    except Exception:
        axes = []
    for axis in axes:
        if (str(axis.get('type') or '') == 'hotel'
                and str(axis.get('stars') or '').strip()):
            stars.add(str(axis['stars']))
    return stars


def _apply_rate(row, rate, url, target_stars=()):
    price_from = rate.get('price_from') or rate.get('price')
    price_to = rate.get('price_to') or price_from
    raw_area_from = rate.get('area_from')
    raw_area_to = rate.get('area_to')
    if raw_area_from is None and raw_area_to is None:
        raw_area_from = rate.get('area_sqm')
        raw_area_to = raw_area_from
    area_from = _sane_area(raw_area_from)
    area_to = _sane_area(raw_area_to)
    if area_from is None or area_to is None:
        area_from = area_to = None
    current = rate.get('current_price')
    stars_value = str(rate.get('hotel_stars') or '').strip()
    if not (stars_value.isdigit() and 1 <= int(stars_value) <= 5):
        stars_value = ''
    target = {str(item) for item in (target_stars or ()) if str(item).strip()}
    effective_stars = str(row.get('hotel_stars') or stars_value or '').strip()
    note = (
        'نطاق أسعار الغرف على Booking قبل الخصم وقبل الضرائب: '
        f'{_money(price_from)} – {_money(price_to)} ر.س'
        + (f'؛ المساحات {_money(area_from)} – {_money(area_to)} م²'
           if area_from is not None else '')
        + (f'؛ أقل سعر حالي بعد الخصم {current}'
           if current is not None else '')
        + (f'؛ التصنيف {stars_value} نجوم' if stars_value else ''))
    if raw_area_from is not None and area_from is None:
        note += '؛ المساحة المقروءة غير منطقية فلم تُسجل'
    row.update({
        'project_type': row.get('project_type') or 'فندقي',
        'operation_type': row.get('operation_type') or 'تشغيل فندقي',
        'hotel_stars': effective_stars,
        'classification': row.get('classification') or (
            'غير مباشر'
            if target and effective_stars and effective_stars not in target
            else 'مباشر'),
        'status': row.get('status') or 'قائم',
        'price_type': 'نطاق أسعار الغرف',
        'price_value': '',
        'price_from': _money(price_from),
        'price_to': _money(price_to),
        'price_currency': 'SAR',
        'area_sqm': '',
        'area_mode': 'range' if area_from is not None else '',
        'area_from': _money(area_from) if area_from is not None else '',
        'area_to': _money(area_to) if area_to is not None else '',
        'source': 'Booking.com',
        'source_url': url,
        'source_urls': [url],
        'row_source': 'booking',
        'verify_state': 'verified',
        'notes': note,
        'field_sources': {
            'name': [url],
            'price_from': [url],
            'price_to': [url],
            'area_from': [url] if area_from is not None else [],
            'area_to': [url] if area_to is not None else [],
            'hotel_stars': [url] if stars_value else [],
        },
    })


def _booking_hotel_candidates(session, name, city=''):
    """Candidate Booking /hotel/ pages for a name, from one search."""
    query = f'site:booking.com/hotel {name} {city}'.strip()
    try:
        hits = session.web_search(query, max_results=8) or []
    except Exception:
        return []
    candidates = []
    seen = set()
    for hit in hits:
        hit = hit if isinstance(hit, dict) else {}
        url = str(hit.get('url') or '')
        if 'booking.com/hotel/' not in url or url in seen:
            continue
        seen.add(url)
        candidates.append({'url': url, 'title': str(hit.get('title') or '')})
    return candidates[:3]


def _title_matches(title, name, city_terms=''):
    label = booking_search.normalize_label(title)
    wanted = booking_search.normalize_label(name)
    if not label or len(wanted) < 4:
        return False
    if wanted in label or label in wanted:
        return True
    city_tokens = set(_name_tokens(_fold_latin(city_terms)))
    tokens = [token for token in _name_tokens(name)
              if token not in city_tokens]
    return _tokens_match(tokens, title, required=min(2, len(tokens)))


def _fill_from_candidate_pages(session, row, city_ar, city_terms='',
                               target_stars=()):
    """Open the searched Booking pages and accept the one whose own title, or
    whose search title together with Booking's URL slug, names the hotel."""
    name = row.get('name')
    rate_seen = False
    identity_seen = False
    for candidate in _booking_hotel_candidates(session, name, city_ar):
        url = candidate.get('url')
        prop = session.open_url(url)
        prop = prop if isinstance(prop, dict) else {}
        rate = prop.get('booking_rate')
        title = str(prop.get('title') or (rate or {}).get('page_title') or '')
        identity = _title_matches(title, name, city_terms) or (
            _title_matches(candidate.get('title') or '', name, city_terms)
            and _url_matches_name(url, name, city_terms))
        print(f'[MARKET STUDY] booking candidate name={name!r} '
              f'url={url[:120]!r} page_title={title[:80]!r} '
              f'identity={identity} '
              f'rate={rate.get("price") if isinstance(rate, dict) else None} '
              f'error={prop.get("error")!r}', flush=True)
        if identity:
            identity_seen = True
        if isinstance(rate, dict) and rate.get('price') is not None:
            rate_seen = True
            if identity:
                _apply_rate(row, rate, url, target_stars=target_stars)
                return True
    if identity_seen:
        row['notes'] = ('صفحة الفندق على Booking.com لا تُظهر أسعارًا '
                        'لحجوزات هذه الإقامة.')
    elif rate_seen:
        row['notes'] = ('وُجدت صفحة فندق على Booking.com بأسعار لكن اسمها '
                        'لا يطابق اسم المنافس.')
    return False


def _fill_hotel_rows_from_booking(rows, payload, data, tenant_id=None,
                                  budget_seconds=None,
                                  progress=None, band=(12, 48)):
    """Give every named hotel row its Booking price, area and source."""
    targets = [row for row in (rows or []) if _needs_booking_fill(row)]
    print(f'[MARKET STUDY] booking name fill scan rows={len(rows or [])} '
          f'targets={len(targets)}', flush=True)
    if not targets:
        return 0
    budget = float(budget_seconds or NAME_FILL_BUDGET_SECONDS)
    result = {'filled': 0}
    timed_out = threading.Event()

    def _report(pct, message):
        # A timed-out join hands the job to the next stage; a late line from
        # this thread must not drag the job's progress backwards.
        if not timed_out.is_set() and callable(progress):
            progress(pct, message)

    def _worker():
        # The browser is thread-bound; a session opened elsewhere fails with
        # «cannot switch to a different thread». The fill owns its thread and
        # its browser, and the join bounds it.
        result['filled'] = _fill_rows(targets, payload, data, tenant_id,
                                      budget, progress=_report, band=band)

    thread = threading.Thread(target=_worker, name='booking-name-fill',
                              daemon=True)
    thread.start()
    thread.join(timeout=budget + 30)
    if thread.is_alive():
        timed_out.set()
    return result['filled']


def _fill_rows(targets, payload, data, tenant_id, budget,
               progress=None, band=(12, 48)):
    city_ar = str((payload or {}).get('city') or '').strip()
    report = progress if callable(progress) else (lambda *_args: None)
    lo, hi = band if isinstance(band, (tuple, list)) and len(band) == 2 else (12, 48)
    total = max(1, len(targets))
    try:
        city_en, _district_en, country = _english_booking_location(
            payload, data, tenant_id=tenant_id)
    except Exception:
        city_en, country = '', ''
    city_terms = ' '.join(part for part in (city_ar, city_en) if part)
    target_stars = _target_hotel_stars(payload)
    deadline = time.time() + float(budget or NAME_FILL_BUDGET_SECONDS)
    filled = [0]
    done = [0]
    lock = threading.Lock()

    def _worker(chunk):
        session = _market_browser_session()
        if session is None:
            return
        # One city-results page per worker: the cards are the fast path for
        # names Booking's free-text search refuses or ranks differently.
        city_cards = []
        try:
            cache_path = (os.path.join(
                UPLOADS_DIR, booking_destination.CACHE_FILE_NAME)
                if UPLOADS_DIR else '')
            destination = booking_destination.resolve_city_destination(
                session, country, city_en or city_ar, city_ar,
                cache_path=cache_path)
            dest_id = str(destination.get('dest_id') or '')
            if dest_id:
                search = session.open_url(booking_search.build_search_url(
                    city_en or city_ar, dest_id=dest_id,
                    dest_type=str(destination.get('dest_type') or 'city')))
                city_cards = (
                    (search or {}).get('booking_search') or {}).get('hotels') or []
                print(f'[MARKET STUDY] booking city cards={len(city_cards)}',
                      flush=True)
        except Exception as exc:
            print(f'[MARKET STUDY] booking city cards skipped: {exc}',
                  flush=True)
        try:
            for _index, row in chunk:
                if time.time() > deadline:
                    row['notes'] = ('لم تُكمل بيانات الفندق في الوقت '
                                    'المتاح لهذه المحاولة.')
                    continue
                card = _card_for_name(city_cards, row.get('name'), city_terms)
                if card:
                    print(f'[MARKET STUDY] booking city card match '
                          f'name={row.get("name")!r} '
                          f'url={str(card.get("url") or "")[:120]!r}',
                          flush=True)
                else:
                    card = _card_from_name_search(session, row.get('name'),
                                                  city_terms)
                url = str((card or {}).get('url') or '').strip()
                if not url:
                    if _fill_from_candidate_pages(session, row, city_ar,
                                                  city_terms, target_stars):
                        with lock:
                            filled[0] += 1
                    else:
                        row.setdefault('notes', (
                            'لم يُعثر على هذا الفندق في Booking؛ '
                            'لم تُضف أسعار أو مساحات.'))
                else:
                    prop = session.open_url(url)
                    rate = (prop or {}).get('booking_rate')
                    if isinstance(rate, dict) and rate.get('price') is not None:
                        _apply_rate(row, rate, url, target_stars=target_stars)
                        with lock:
                            filled[0] += 1
                    else:
                        row['notes'] = ('صفحة الفندق على Booking.com لم تُظهر '
                                        'جدول أسعار لهذه الإقامة.')
                with lock:
                    done[0] += 1
                    report(lo + int((hi - lo - 5) * done[0] / total),
                           f'اكتمل «{row.get("name") or "منافس"}» '
                           f'({done[0]} من {total})...')
        except Exception as exc:
            print(f'[MARKET STUDY] booking fill worker failed: {exc}',
                  flush=True)
        finally:
            try:
                session.close()
            except Exception:
                pass

    worker_count = min(3, len(targets))
    chunks = [[] for _ in range(worker_count)]
    for index, row in enumerate(targets):
        chunks[index % worker_count].append((index, row))
    report(lo, f'البحث باسم كل فندق على Booking.com '
               f'({len(targets)} فندق)...')
    threads = [threading.Thread(target=_worker, args=(chunk,),
                                name=f'booking-name-fill-{number}',
                                daemon=True)
               for number, chunk in enumerate(chunks)]
    for thread in threads:
        thread.start()
    for thread in threads:
        remaining = max(5, deadline + 30 - time.time())
        thread.join(timeout=remaining)
    report(hi, 'اكتمل إكمال بيانات الفنادق من Booking.com.')
    return filled[0]


def _filled_row_signature(row):
    """The cells a completion pass fills — used to count changed rows."""
    return tuple(str((row or {}).get(key) or '').strip() for key in (
        'price_value', 'price_from', 'price_to',
        'area_sqm', 'area_from', 'area_to', 'source_url'))


def _run_market_competitors_fill(data, payload, existing, offer_lang='ar',
                                 tenant_id=None, deadline=None, report=None):
    """Complete the table's own rows: hotels from Booking, others by name.

    The completion mode never discovers competitors, so it never runs the
    district scans, the known-source plan or the logo discovery call. A row
    whose per-name lookup finds nothing keeps its values and says so — one
    miss never turns the whole run into «تعذر توليد المنافسين».
    """
    report = report if callable(report) else (lambda *_args: None)
    report(10, 'إكمال بيانات المنافسين المسجلين بالبحث باسم كل منافس...')
    merged, _added, _updated = market_study.merge_generated_competitors(
        existing, [], mode='fill', offer_lang=offer_lang)
    targets = [row for row in merged
               if isinstance(row, dict) and str(row.get('name') or '').strip()]
    if not targets:
        return {
            'success': False,
            'error': 'لا توجد صفوف منافسين بأسماء لإكمال بياناتها.',
            'failureReason': 'no_rows_to_fill',
        }
    fill_deadline = time.time() + float(FILL_PHASE_BUDGET_SECONDS)
    try:
        if deadline is not None:
            fill_deadline = min(fill_deadline, float(deadline))
    except (TypeError, ValueError):
        pass
    before = {id(row): _filled_row_signature(row) for row in targets}
    hotel_targets = [row for row in targets if _needs_booking_fill(row)]
    other_targets = [row for row in targets
                     if not _is_hotel_row(row) and _needs_name_fill(row)]
    attempted = len(hotel_targets) + len(other_targets)
    if hotel_targets and not current_app.config.get('TESTING'):
        try:
            _fill_hotel_rows_from_booking(
                merged, payload, data, tenant_id=tenant_id,
                budget_seconds=min(
                    NAME_FILL_BUDGET_SECONDS,
                    max(30, int(fill_deadline - time.time()))),
                progress=report, band=(12, 48))
        except Exception as exc:
            print(f'[MARKET STUDY] hotel name fill skipped: {exc}', flush=True)
    if other_targets:
        _verify_competitor_rows(
            other_targets, payload, data, tenant_id=tenant_id,
            progress=report, evidence_pool=None, deadline=fill_deadline,
            band=(52, 88))
    for row in merged:
        market_study.canonicalize_competitor_source_urls(row)
        _drop_foreign_competitor_urls(row)
        _drop_banned_competitor_listing_urls(row)
    changed = sum(1 for row in targets
                  if _filled_row_signature(row) != before.get(id(row)))
    sources = market_study.competitor_source_rows(merged)
    market_study.flag_out_of_period_sources(
        sources, payload.get('dataPeriodBounds'))
    missing_prices = sum(
        1 for row in merged
        if str(row.get('name') or '').strip()
        and not any(str(row.get(key) or '').strip()
                    for key in ('price_value', 'price_from', 'price_to')))
    verify_errors = [str(row.get('verify_provider_error') or '').strip()
                     for row in other_targets if row.get('verify_provider_error')]
    verify_errors = [err for err in verify_errors if err and err != 'empty_response']
    provider_error = verify_errors[0] if verify_errors else ''
    search_not_run = sum(1 for row in merged
                         if row.get('verify_state') == 'search_not_run')
    report(93, 'إعداد جدول المصادر والتحذيرات...')
    return {
        'success': True,
        'competitors': merged,
        'sources': sources,
        'added': 0,
        'updated': changed,
        'filledCount': changed,
        'searchVerified': not provider_error,
        'searchStats': None,
        'partial': bool(provider_error) or missing_prices > 0,
        'providerError': provider_error or None,
        'noEvidenceCount': 0,
        'searchNotRunCount': search_not_run,
        'missingPriceCount': missing_prices,
        'fallbackCount': 0,
        'conflictWarnings': [warning for row in merged
                             for warning in (row.get('conflict_warnings') or [])],
        'searchExpanded': False,
        'comparisonTypes': payload.get('comparisonTypes') or [],
        'competitorScope': payload.get('competitorScope') or {},
        'transactionBenchmarks': None,
        'expansionNote': '',
        'notes': (f'أُكملت بيانات {changed} من {attempted} منافس '
                  'بالبحث باسم كل منافس.' if attempted else
                  'كل صفوف المنافسين مكتملة بالفعل.'),
    }
