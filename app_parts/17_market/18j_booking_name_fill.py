"""Complete a named hotel competitor from Booking's own search cards.

Manual hotel rows (and legacy AI ones) used to wait on the browse agent,
which returns no page, so the row kept a name and a star class but no
source, price or area. The hotel axes already read a Booking property page
deterministically; this completes a named row the same way: find the card
whose title matches the row's name, open its ``/hotel/`` page, read the
rate block, and write the room ranges onto the row.
"""

import threading
import time

import booking_destination
import booking_search
from numeric_precision import format_precise_number

_HOTEL_TOKENS = ('فندق', 'فندقي', 'hotel', 'hospitality', 'تشغيل')
NAME_FILL_BUDGET_SECONDS = 150


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


def _card_for_name(cards, name):
    wanted = booking_search.normalize_label(name)
    if len(wanted) < 4:
        return None
    for card in cards or []:
        label = booking_search.normalize_label((card or {}).get('name'))
        if not label:
            continue
        if label == wanted or wanted in label or label in wanted:
            return card
    return None


def _money(value):
    if value in (None, ''):
        return ''
    return format_precise_number(float(value), grouped=False)


def _apply_rate(row, rate, url):
    price_from = rate.get('price_from') or rate.get('price')
    price_to = rate.get('price_to') or price_from
    area_from = rate.get('area_from')
    area_to = rate.get('area_to')
    if area_from is None and area_to is None:
        area_from = rate.get('area_sqm')
        area_to = area_from
    current = rate.get('current_price')
    note = (
        'نطاق أسعار الغرف على Booking قبل الخصم وقبل الضرائب: '
        f'{_money(price_from)} – {_money(price_to)} ر.س'
        + (f'؛ المساحات {_money(area_from)} – {_money(area_to)} م²'
           if area_from is not None else '')
        + (f'؛ أقل سعر حالي بعد الخصم {current}'
           if current is not None else ''))
    row.update({
        'project_type': row.get('project_type') or 'فندقي',
        'operation_type': row.get('operation_type') or 'تشغيل فندقي',
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
        },
    })


def _booking_hotel_candidates(session, name, city=''):
    """Candidate Booking /hotel/ URLs for a name, from one search."""
    query = f'site:booking.com/hotel {name} {city}'.strip()
    try:
        hits = session.web_search(query, max_results=8) or []
    except Exception:
        return []
    urls = []
    for hit in hits:
        hit = hit if isinstance(hit, dict) else {}
        url = str(hit.get('url') or '')
        if 'booking.com/hotel/' in url and url not in urls:
            urls.append(url)
    return urls[:3]


def _title_matches(title, name):
    label = booking_search.normalize_label(title)
    wanted = booking_search.normalize_label(name)
    if not label or len(wanted) < 4:
        return False
    if wanted in label or label in wanted:
        return True
    token = next((part for part in wanted.split() if len(part) >= 4), '')
    return bool(token and token in label)


def _fill_from_candidate_pages(session, row, city_ar):
    """Open the searched Booking pages and accept the one whose own title
    carries the hotel name; the search snippet title is unreliable."""
    for candidate in _booking_hotel_candidates(
            session, row.get('name'), city_ar):
        prop = session.open_url(candidate)
        prop = prop if isinstance(prop, dict) else {}
        rate = prop.get('booking_rate')
        title = str(prop.get('title') or (rate or {}).get('page_title') or '')
        if (isinstance(rate, dict) and rate.get('price') is not None
                and _title_matches(title, row.get('name'))):
            _apply_rate(row, rate, candidate)
            return True
    return False


def _fill_hotel_rows_from_booking(rows, payload, data, tenant_id=None,
                                  cache_path='', budget_seconds=None):
    """Give every named hotel row its Booking price, area and source."""
    targets = [row for row in (rows or []) if _needs_booking_fill(row)]
    print(f'[MARKET STUDY] booking name fill scan rows={len(rows or [])} '
          f'targets={len(targets)}', flush=True)
    if not targets:
        return 0
    budget = float(budget_seconds or NAME_FILL_BUDGET_SECONDS)
    result = {'filled': 0}

    def _worker():
        # The browser is thread-bound; a session opened elsewhere fails with
        # «cannot switch to a different thread». The fill owns its thread and
        # its browser, and the join bounds it.
        result['filled'] = _fill_rows(targets, payload, data, tenant_id,
                                      cache_path, budget)

    thread = threading.Thread(target=_worker, name='booking-name-fill',
                              daemon=True)
    thread.start()
    thread.join(timeout=budget + 30)
    return result['filled']


def _fill_rows(targets, payload, data, tenant_id, cache_path, budget):
    city_ar = str((payload or {}).get('city') or '').strip()
    try:
        city_en, _district_en, country = _english_booking_location(
            payload, data, tenant_id=tenant_id)
    except Exception:
        city_en, country = '', ''
    session = _market_browser_session()
    if session is None:
        return 0
    filled = 0
    deadline = time.time() + float(budget or NAME_FILL_BUDGET_SECONDS)
    try:
        destination = booking_destination.resolve_city_destination(
            session, country, city_en or city_ar, city_ar,
            cache_path=cache_path)
        dest_id = str(destination.get('dest_id') or '')
        search = session.open_url(booking_search.build_search_url(
            city_en or city_ar, dest_id=dest_id,
            dest_type=str(destination.get('dest_type') or 'city')))
        cards = ((search or {}).get('booking_search') or {}).get('hotels') or []
        print(f'[MARKET STUDY] booking name fill cards={len(cards)} '
              f'targets={len(targets)}', flush=True)
        for row in targets:
            if time.time() > deadline:
                break
            card = _card_for_name(cards, row.get('name'))
            if not card:
                # Booking ignores the free text once a destination id is set,
                # so a name outside the city's top cards is found through one
                # search, then verified on the page's own title.
                if _fill_from_candidate_pages(session, row, city_ar):
                    filled += 1
                else:
                    row['notes'] = ('لم يُعثر على هذا الفندق في Booking؛ '
                                    'لم تُضف أسعار أو مساحات.')
                continue
            url = str(card.get('url') or '')
            prop = session.open_url(url)
            rate = (prop or {}).get('booking_rate')
            if not isinstance(rate, dict) or rate.get('price') is None:
                row['notes'] = ('صفحة الفندق على Booking.com لم تُظهر جدول '
                                'أسعار لهذه الإقامة.')
                continue
            _apply_rate(row, rate, url)
            filled += 1
    except Exception as exc:
        print(f'[MARKET STUDY] booking name fill failed: {exc}', flush=True)
    finally:
        try:
            session.close()
        except Exception:
            pass
    return filled
