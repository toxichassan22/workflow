"""Deterministic Booking.com room sample for the market summary.

The summary's source researchers run provider web search, which cannot read
Booking's room table (JavaScript, stay window, per-row taxes). The competitor
scan already reads it deterministically; this feeds the same sample into the
summary's evidence pool so the summary quotes advertised room rates for its
exact stay window instead of reporting that no Booking sample exists.
"""

import hotel_stay


_SUMMARY_BOOKING_BLOCK_START = '## BOOKING_HOTEL_SAMPLE ##'
_SUMMARY_BOOKING_BLOCK_END = '## END BOOKING_HOTEL_SAMPLE ##'


def _summary_booking_selected(payload):
    """True when the project's selected activities include stays."""
    try:
        profile = market_study.summary_activity_profile(payload)
    except Exception:
        return False
    return bool(set(profile.get('kinds') or set()) & {'hospitality', 'residential'})


def _summary_booking_price_text(row):
    price_from = str(row.get('price_from') or '').strip()
    price_to = str(row.get('price_to') or '').strip()
    if price_from and price_to and price_from != price_to:
        return f'{price_from}–{price_to}'
    return price_from or price_to or 'غير متوفر'


def _summary_booking_area_text(row):
    area_from = str(row.get('area_from') or '').strip()
    area_to = str(row.get('area_to') or '').strip()
    if area_from and area_to and area_from != area_to:
        return f'{area_from}–{area_to} م²'
    return f'{area_from} م²' if area_from else ''


def _summary_booking_block(rows, note, payload):
    """The Arabic evidence block the summary aggregator reads verbatim."""
    check_in, check_out = hotel_stay.booking_stay_window()
    city = str((payload or {}).get('city') or '').strip()
    district = str((payload or {}).get('district') or '').strip()
    scope = f'{city} — {district}' if district else f'{city} كاملة'
    lines = [
        _SUMMARY_BOOKING_BLOCK_START,
        'source: Booking.com',
        f'scope: {scope}',
        f'stay: {check_in.isoformat()} → {check_out.isoformat()} '
        f'(غرفة واحدة، بالغان، {hotel_stay.stay_nights_label_ar()}، SAR)',
    ]
    if note:
        lines.append(f'scan_note: {note}')
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or '').strip()
        if not name:
            continue
        stars = str(row.get('hotel_stars') or '').strip()
        lines.append(f'[{index}] {name}' + (f' ({stars} نجوم)' if stars else ''))
        lines.append(f'price_per_night_sar: {_summary_booking_price_text(row)}')
        area = _summary_booking_area_text(row)
        if area:
            lines.append(f'room_area: {area}')
        basis = str(row.get('notes') or '').strip()
        if basis:
            lines.append(f'basis: {basis}')
        url = str(row.get('source_url') or '').strip()
        if url:
            lines.append(f'url: {url}')
    lines.append(_SUMMARY_BOOKING_BLOCK_END)
    return '\n'.join(lines)


def _summary_booking_citation_pages(scan, limit=5):
    pages = []
    reply = scan.get('reply') if isinstance(scan, dict) else {}
    choices = (reply or {}).get('choices') or []
    message = (choices[0] or {}).get('message') if choices else {}
    for item in (message or {}).get('annotations') or []:
        data = (item or {}).get('url_citation') or {}
        url = str(data.get('url') or '').strip()
        if not url:
            continue
        pages.append({
            'url': url,
            'title': str(data.get('title') or 'Booking.com'),
            'content': str(data.get('content') or '')[:8000],
        })
        if len(pages) >= limit:
            break
    return pages


def _summary_booking_evidence(payload, data, tenant_id, deadline=None):
    """One city/district Booking scan for the whole summary, or None.

    Only a scan that actually read a rate produces evidence; a blocked or empty
    scan returns None so the regular Booking research gap stays visible.
    """
    if not _summary_booking_selected(payload):
        return None
    task = {'axis': {'label': 'فندقي', 'base': 'hospitality', 'stars': ''}}
    try:
        scan = _booking_hotel_scan(
            task, payload, data, tenant_id=tenant_id, deadline=deadline)
    except Exception as exc:
        print(f'[MARKET SUMMARY] booking sample failed: {exc}')
        return None
    parsed = (scan or {}).get('parsed') or {}
    rows = [row for row in (parsed.get('competitors') or [])
            if isinstance(row, dict)]
    priced = [row for row in rows
              if str(row.get('price_from') or row.get('price_to') or '').strip()]
    if not priced:
        return None
    pages = _summary_booking_citation_pages(scan)
    return {
        'rows': len(rows),
        'priced': len(priced),
        'search_url': pages[0]['url'] if pages else 'https://www.booking.com/',
        'block': _summary_booking_block(
            rows, str(parsed.get('notes') or ''), payload),
        'pages': pages,
        'note': str(parsed.get('notes') or ''),
    }


def _summary_booking_evidence_into(payload, data, tenant_id, evidence_pool,
                                   deadline=None, report=None):
    """Store the deterministic Booking sample in the summary evidence pool."""
    if evidence_pool is None or not _summary_booking_selected(payload):
        return None
    report = report if callable(report) else (lambda *_args: None)
    report(22, 'جاري قراءة أسعار الغرف من Booking.com لإقامة محددة...')
    result = _summary_booking_evidence(payload, data, tenant_id, deadline=deadline)
    if not result:
        return None
    try:
        evidence_pool.add_page(
            result['search_url'], title='Booking.com — عينة أسعار الغرف',
            content=result['block'], final_url=result['search_url'],
            via='booking_sample')
        for page in result.get('pages') or []:
            if page.get('url'):
                evidence_pool.add_page(
                    page['url'], title=page.get('title') or 'Booking.com',
                    content=page.get('content') or '', final_url=page['url'],
                    via='booking_sample')
    except Exception as exc:
        print(f'[MARKET SUMMARY] booking evidence store failed: {exc}')
    payload['_summaryBookingSample'] = {
        'rows': result['rows'], 'priced': result['priced'],
    }
    report(22, f"قرأت Booking.com {result['priced']} فندقًا بسعر ومساحة "
               'لإقامة محددة.')
    return result


def _summary_deterministic_stage_allowed():
    """The real scans are browser work; unittest runs must stay offline."""
    try:
        return not current_app.config.get('TESTING')
    except Exception:
        return True


def _run_market_summary_research_with_booking(payload, usage_ctx, evidence_pool,
                                              deadline, data=None, tenant_id=None,
                                              session=None, **kwargs):
    """Summary research entry: deterministic reader evidence, then the fan-out.

    Defined here so the job entry stays one call and the large market-part file
    does not grow.
    """
    if _summary_deterministic_stage_allowed():
        _summary_booking_evidence_into(
            payload, data or {}, tenant_id, evidence_pool,
            deadline=deadline, report=kwargs.get('report'))
        _summary_aqar_evidence_into(
            payload, session, evidence_pool,
            deadline=deadline, report=kwargs.get('report'))
    return _run_market_summary_research(
        payload, usage_ctx, evidence_pool, deadline, **kwargs)
