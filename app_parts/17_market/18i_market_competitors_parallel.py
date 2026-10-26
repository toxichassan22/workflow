
# ---------------------------------------------------------------------------
# Parallel competitor scans.
#
# One browse-agent call per comparison axis, all in flight together, plus a
# second complementary angle for a single-axis project and the known-sources
# plan running alongside them. The models are the slow stage — the whole job
# used to walk axis after axis, so a two-axis project paid two full scans and
# a one-axis project still waited for the source plan first. Verification is
# already parallel (one thread per row); this module parallelizes the scan.
# ---------------------------------------------------------------------------

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import booking_destination
import booking_rooms
import booking_search
import hotel_stay
import maps_service
from numeric_precision import format_precise_number


_PARALLEL_SCAN_WORKERS = 4
# One competitor phase must finish inside the client's five-minute budget; a
# scan that keeps searching past it is cost with no result.
_MARKET_SCAN_BUDGET_SECONDS = float(
    os.environ.get('MARKET_SCAN_BUDGET_SECONDS') or 240)


def _scan_deadline(deadline):
    """The job deadline, capped by the competitor phase's own budget."""
    latest = time.time() + _MARKET_SCAN_BUDGET_SECONDS
    try:
        if deadline is not None:
            return min(float(deadline), latest)
    except (TypeError, ValueError):
        pass
    return latest


def _locked_report(report):
    lock = threading.Lock()

    def emit(pct, message=''):
        try:
            with lock:
                report(pct, message)
        except Exception:
            pass

    return emit


def _axis_scan_payload(payload, axis):
    """A payload whose only explicit comparison pick is this axis."""
    axis_type = str((axis or {}).get('type') or '')
    if axis_type == 'hotel':
        selection = [{'type': 'hotel', 'stars': [str(axis.get('stars') or '')]}]
    else:
        selection = [{
            'type': axis_type,
            'operation': [str(axis.get('operation') or '')],
        }]
    next_payload = dict(payload or {})
    next_payload['comparisonTypes'] = selection
    return next_payload


def _portals_focus_line(offer_lang='ar'):
    if offer_lang == 'en':
        return (
            '\n\nThis complementary pass focuses on detailed listing pages that '
            'currently offer units or hotel rooms (aqar.fm for residential and '
            'commercial, Booking.com for hotels), to catch named competitors that '
            'developer sites never list. Keep the same source, price and '
            'official-page rules.')
    return (
        '\n\nهذه الجولة التكميلية تركّز على صفحات الإعلانات والقوائم التفصيلية '
        'التي تعرض وحدات أو غرفًا فندقية معروضة فعليًا (عقار للسكني والتجاري، '
        'وBooking.com للفنادق) لالتقاط منافسين مسمّين لا تذكرهم مواقع المطورين. '
        'التزم بقواعد المصادر والأسعار والصفحة الرسمية نفسها.')


def _scan_search_limits(task_count):
    total_searches = max(4, int(_COMPETITORS_SEARCH_BUDGET))
    total_steps = max(10, int(_COMPETITORS_MAX_STEPS))
    per_task = max(1, task_count)
    return (
        max(3, total_searches // per_task),
        max(5, total_steps // per_task),
    )


def _project_coordinates(payload, data=None):
    sources = []
    for source in (payload, data):
        if isinstance(source, dict):
            sources.append(source)
            for key in ('projectData', 'project_data', 'fields', 'draft_data'):
                nested = source.get(key)
                if isinstance(nested, dict):
                    sources.append(nested)

    def first_number(keys):
        for source in sources:
            for key in keys:
                value = source.get(key)
                if value is not None and str(value).strip():
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
        return None

    return (first_number(('location_lat', 'locationLat', 'lat', 'latitude')),
            first_number(('location_lng', 'locationLng', 'lng', 'longitude')))


def _english_booking_location(payload, data, tenant_id=None):
    """Project district/city/country in English, for a Booking search.

    Booking does not resolve a free-text district (it redirects to the
    homepage and the search has to run on a destination id), so the project
    coordinates — or, when they are missing, an address geocode — resolve to
    the English city, district and country code. The country code is what
    locates Booking's city page.
    """
    city = str((payload or {}).get('city') or '').strip()
    district = str((payload or {}).get('district') or '').strip()
    if district.startswith('حي '):
        district = district[3:].strip()
    usage_ctx = _usage_ctx('market', data, tenant_id=tenant_id)

    def english_from(resolved):
        components = (resolved or {}).get('address_components') or []

        def component(types):
            for item in components:
                if set(item.get('types') or []) & set(types):
                    return str(item.get('long_name') or '').strip()
            return ''

        country = ''
        for item in components:
            if 'country' in (item.get('types') or []):
                country = str(item.get('short_name')
                               or item.get('long_name') or '').strip()
                break

        return (component(('locality', 'postal_town',
                           'administrative_area_level_2')),
                component(('sublocality_level_1', 'sublocality',
                           'neighborhood', 'administrative_area_level_3')),
                country)

    city_en = district_en = country_code = ''
    lat, lng = _project_coordinates(payload, data)
    if lat is not None and lng is not None:
        try:
            resolved = maps_service.reverse_geocode_location(
                lat, lng, tenant_id=tenant_id, language='en',
                usage_ctx=usage_ctx)
        except Exception as exc:
            print(f'[MARKET STUDY] English geocode failed: {exc}')
            resolved = {}
        city_en, district_en, country_code = english_from(resolved)
    if not city_en or not district_en:
        address_query = ', '.join(part for part in (
            district, city, 'السعودية') if part)
        if address_query:
            try:
                geocoded = maps_service.geocode_address(
                    address_query, tenant_id=tenant_id, usage_ctx=usage_ctx)
            except Exception as exc:
                print(f'[MARKET STUDY] Address geocode failed: {exc}')
                geocoded = {}
            if isinstance(geocoded, dict) and geocoded.get('lat') is not None:
                try:
                    resolved = maps_service.reverse_geocode_location(
                        geocoded['lat'], geocoded['lng'],
                        tenant_id=tenant_id, language='en',
                        usage_ctx=usage_ctx)
                except Exception:
                    resolved = {}
                extra_city, extra_district, extra_country = english_from(resolved)
                city_en = city_en or extra_city
                district_en = district_en or extra_district
                country_code = country_code or extra_country
    print(f'[MARKET STUDY] booking location city={city!r} '
          f'district={district!r} lat={lat!r} lng={lng!r} -> '
          f'city_en={city_en!r} district_en={district_en!r} '
          f'country={country_code!r}', flush=True)
    return city_en or city, district_en or district, country_code


def _booking_scan_citation(url, title='', text=''):
    return {'type': 'url_citation', 'url_citation': {
        'url': str(url or ''),
        'title': str(title or ''),
        'content': str(text or '')[:8000],
    }}


def _booking_scan_result(task, rows, citations, note='', search_ran=False):
    content = json.dumps(
        {'competitors': rows, 'notes': note}, ensure_ascii=False)
    reply = {'choices': [{'message': {
        'content': content,
        'annotations': citations,
    }}]}
    return {
        'task': task,
        'reply': reply,
        'parsed': {'competitors': rows, 'notes': note},
        'parse_error': '',
        'provider_error': '',
        'search_ran': bool(search_ran),
    }


def _booking_empty_note(search, *, destination, matched_district,
                        district_label, city_label, stars,
                        filter_error=''):
    """Why a Booking scan produced no hotels, naming the actual cause."""
    search = search if isinstance(search, dict) else {}
    where = (f'لحي {district_label} في {city_label}' if district_label
             else f'في {city_label}')
    stars_part = f' (النجوم {stars})' if stars else ''
    if filter_error:
        return (f'تعذّر فتح نتائج فلتر حي {district_label} على Booking '
                f'({filter_error})، فلم تُقرأ فنادق الحي{stars_part}. '
                f'لم يُستخدم أي مصدر آخر.')
    error_code = booking_search.search_error_code(search.get('final_url'))
    if error_code:
        return (f'رفض Booking البحث النصّي ({error_code}) فلم تُفتح صفحة نتائج '
                f'{where}{stars_part}. لم يُستخدم أي مصدر آخر.')
    if search.get('error'):
        return (f'تعذّر فتح صفحة نتائج Booking.com {where}{stars_part} '
                f'({search.get("error")}). لم يُستخدم أي مصدر آخر.')
    if not (destination or {}).get('dest_id'):
        return (f'تعذّر تحديد وجهة المدينة على Booking، فلم تُرجع صفحة النتائج '
                f'فنادق {where}{stars_part}. لم يُستخدم أي مصدر آخر.')
    if matched_district:
        return (f'لا توجد فنادق {stars_part or "مطابقة"} لحي {district_label} '
                f'في {city_label} على Booking.com. لم يُستخدم أي مصدر آخر.')
    return (f'لم تُرجع صفحة نتائج Booking.com فنادق {where}{stars_part} '
            f'دون فلتر حي (الحي غير معروض ضمن أحياء Booking لهذه المدينة). '
            f'لم يُستخدم أي مصدر آخر.')


def _booking_hotel_scan(task, payload, data, tenant_id=None, offer_lang='ar',
                        deadline=None):
    """Deterministic hotel discovery from Booking search + property pages.

    No model decides which hotel page to open: the project city is resolved to
    Booking's own destination id (a free-text search is refused), the city's
    hotels are filtered by Booking's neighbourhood filter for the project
    district and the selected star class, the hotel cards become the
    competitors, and each property page's ``## BOOKING_RATE ##`` block supplies
    the original pre-discount stay price and room area.
    """
    axis = task.get('axis') if isinstance(task.get('axis'), dict) else {}
    stars = str(axis.get('stars') or '').strip()
    city_ar = str((payload or {}).get('city') or '').strip()
    district_ar = str((payload or {}).get('district') or '').strip()
    display_district = (district_ar[3:].strip()
                        if district_ar.startswith('حي ') else district_ar)
    scope = ((payload or {}).get('competitorScope')
             or (payload or {}).get('competitor_scope'))
    scope = scope if isinstance(scope, dict) else {}
    scope_mode = (scope.get('mode')
                  if scope.get('mode') in ('district', 'city', 'distance')
                  else 'district')
    try:
        radius_km = float(scope.get('radius_km') or scope.get('radiusKm') or 0)
    except (TypeError, ValueError):
        radius_km = 0.0
    city_en, district_en, country_code = _english_booking_location(
        payload, data, tenant_id=tenant_id)
    if _market_deadline_hit(deadline):
        return _booking_scan_result(
            task, [], [], 'deadline_exceeded', search_ran=False)
    session = _market_browser_session(search_provider='searxng')
    rows = []
    citations = []
    try:
        cache_path = (os.path.join(
            UPLOADS_DIR, booking_destination.CACHE_FILE_NAME)
            if UPLOADS_DIR else '')
        destination = booking_destination.resolve_city_destination(
            session, country_code, city_en or city_ar, city_ar,
            cache_path=cache_path)
        dest_id = str(destination.get('dest_id') or '')
        dest_type = str(destination.get('dest_type') or 'city')
        search_url = booking_search.build_search_url(
            city_en or city_ar, stars=stars or None,
            dest_id=dest_id, dest_type=dest_type)
        print(f'[MARKET STUDY] booking hotel search city={city_en!r} '
              f'district={district_en!r} country={country_code!r} '
              f'stars={stars!r} dest_id={dest_id!r} '
              f'url={search_url}', flush=True)
        search = session.open_url(search_url)
        search = search if isinstance(search, dict) else {}
        final_url = str(search.get('final_url') or search_url)
        citations.append(_booking_scan_citation(
            final_url, search.get('title'), search.get('text')))
        matched = booking_search.match_district_facet(
            search.get('booking_districts') or [], district_ar, district_en)

        def _apply_district(district_id, as_destination=False):
            if as_destination:
                # Booking serves the district itself as a destination; that
                # page is narrower than the city and honours the class filter
                # even when the nflt neighbourhood filter is ignored.
                filtered_url = booking_search.build_search_url(
                    city_en or city_ar, stars=stars or None,
                    dest_id=district_id, dest_type='district')
            else:
                filtered_url = booking_search.build_search_url(
                    city_en or city_ar, stars=stars or None, dest_id=dest_id,
                    dest_type=dest_type, district_id=district_id)
            filtered = session.open_url(filtered_url)
            filtered = filtered if isinstance(filtered, dict) else {}
            filtered_hotels = ((filtered.get('booking_search') or {})
                               .get('hotels') or [])
            filtered_final = str(filtered.get('final_url') or filtered_url)
            if as_destination:
                applied = f'dest_id={district_id}' in filtered_final
            else:
                applied = booking_search.search_has_district(
                    filtered_final, district_id)
            print(f'[MARKET STUDY] booking district filter id={district_id!r} '
                  f'as_destination={as_destination} '
                  f'label={booking_search.facet_label(matched or {})!r} '
                  f'cards={len(filtered_hotels)} '
                  f'applied={applied} '
                  f'error={filtered.get("error")!r} '
                  f'final={filtered_final[:320]}', flush=True)
            return filtered, filtered_final, applied

        def _district_card_search():
            """The city cards whose own Booking address names the district."""
            cards = booking_search.filter_hotels_by_district(
                (search.get('booking_search') or {}).get('hotels') or [],
                district_ar, district_en)
            if not cards:
                return None
            narrowed = dict(search)
            narrowed['booking_search'] = dict(
                search.get('booking_search') or {}, hotels=cards)
            return narrowed

        def _use_filtered(district_id):
            nonlocal matched
            attempts = ((False, 'neighbourhood filter'),
                        (False, 'neighbourhood filter retry'),
                        (True, 'district destination'))
            for as_destination, label in attempts:
                filtered, filtered_final, applied = _apply_district(
                    district_id, as_destination)
                hotels = ((filtered.get('booking_search') or {})
                          .get('hotels') or [])
                kept = booking_search.filter_hotels_by_district(
                    hotels, district_ar, district_en)
                if not filtered.get('error') and applied and kept:
                    matched = dict(matched or {}, id=str(district_id))
                    narrowed = dict(filtered)
                    narrowed['booking_search'] = dict(
                        filtered.get('booking_search') or {}, hotels=kept)
                    citations.append(_booking_scan_citation(
                        filtered_final, filtered.get('title'),
                        filtered.get('text')))
                    return narrowed, ''
                print(f'[MARKET STUDY] booking district attempt '
                      f'({label}) kept={len(kept)}', flush=True)
            note = _booking_empty_note(
                filtered, destination=destination, matched_district=None,
                filter_error=str(
                    filtered.get('error') or 'filter_not_applied'),
                district_label=display_district or district_en,
                city_label=city_ar or city_en, stars=stars)
            # Booking dropped the neighbourhood filter (or the page failed):
            # fall back to its own address line before reporting nothing.
            narrowed = _district_card_search()
            if narrowed is not None:
                matched = {'id': '', 'label': display_district or district_ar}
                return narrowed, ''
            return None, note

        if matched and scope_mode == 'district':
            if matched.get('id'):
                booking_destination.remember_district_id(
                    cache_path, country_code, city_en or city_ar,
                    display_district or district_ar, matched.get('id'))
            filtered_result, note = _use_filtered(matched.get('id'))
            if note:
                return _booking_scan_result(
                    task, [], citations, note, search_ran=True)
            search = filtered_result
        elif scope and scope_mode == 'district':
            # A class-filtered page lists only the districts that have hotels
            # of that class, so a 4-star page can omit the project's district
            # even though Booking still filters by it. The district id is
            # city-scoped: read it once from the unfiltered city page, cache
            # it, and keep the scope exactly as the client set it.
            district_key_city = city_en or city_ar
            district_id = booking_destination.cached_district_id(
                cache_path, country_code, district_key_city,
                display_district or district_ar)
            if not district_id:
                wide_url = booking_search.build_search_url(
                    city_en or city_ar, dest_id=dest_id, dest_type=dest_type)
                wide = session.open_url(wide_url)
                wide = wide if isinstance(wide, dict) else {}
                wide_match = booking_search.match_district_facet(
                    wide.get('booking_districts') or [], district_ar,
                    district_en)
                if wide_match:
                    district_id = str(wide_match.get('id') or '')
                    matched = wide_match
                    booking_destination.remember_district_id(
                        cache_path, country_code, district_key_city,
                        display_district or district_ar, district_id)
            if not district_id and str(stars or '') != '5':
                # The facet list is derived from the current results, so a
                # 4-star page can hide the district that the 5-star page
                # lists. Read the id once from that page and cache it; the
                # district id is city-scoped, not class-scoped.
                probe = session.open_url(booking_search.build_search_url(
                    city_en or city_ar, stars='5', dest_id=dest_id,
                    dest_type=dest_type))
                probe = probe if isinstance(probe, dict) else {}
                probe_match = booking_search.match_district_facet(
                    probe.get('booking_districts') or [], district_ar,
                    district_en)
                if probe_match:
                    district_id = str(probe_match.get('id') or '')
                    matched = probe_match
                    booking_destination.remember_district_id(
                        cache_path, country_code, district_key_city,
                        display_district or district_ar, district_id)
            if district_id:
                filtered_result, note = _use_filtered(district_id)
                if note:
                    return _booking_scan_result(
                        task, [], citations, note, search_ran=True)
                search = filtered_result
            else:
                # Booking only lists the ten largest districts as facets. When
                # the project's district is hidden, keep the city cards whose
                # own address line names it — still the district, never the
                # whole city.
                district_cards = booking_search.filter_hotels_by_district(
                    (search.get('booking_search') or {}).get('hotels') or [],
                    district_ar, district_en)
                if district_cards:
                    search = dict(search)
                    search['booking_search'] = dict(
                        search.get('booking_search') or {},
                        hotels=district_cards)
                    matched = {'id': '', 'label': display_district or district_ar}
                elif scope_mode == 'district':
                    city_cards = ((search.get('booking_search') or {})
                                  .get('hotels') or [])
                    sample = [(card.get('location'),
                               (card.get('text') or '')[:60])
                              for card in city_cards[:3]]
                    print(f'[MARKET STUDY] booking district unavailable '
                          f'id={district_id!r} city_cards={len(city_cards)} '
                          f'names={[district_ar, district_en]!r} '
                          f'sample={sample!r}', flush=True)
                    note = (f'لم يُعرض حي {display_district or district_en} '
                            f'كفلتر على Booking.com لهذه المدينة، ولم يُوسَّع '
                            f'البحث إلى المدينة. لم يُستخدم أي مصدر آخر.')
                    return _booking_scan_result(
                        task, [], citations, note, search_ran=True)
        search_data = search.get('booking_search') \
            if isinstance(search.get('booking_search'), dict) else {}
        hotels = search_data.get('hotels') or []
        print(f'[MARKET STUDY] booking search final_url={search.get("final_url")} '
              f'cards={len(hotels)} '
              f'chars={len(str(search.get("text") or ""))}', flush=True)
        if not hotels:
            note = _booking_empty_note(
                search, destination=destination, matched_district=matched,
                district_label=display_district or district_en,
                city_label=city_ar or city_en, stars=stars)
            return _booking_scan_result(
                task, [], citations, note, search_ran=True)
        benchmark = market_study.benchmark_axis_label(axis, offer_lang)
        skipped_outside = skipped_unverified = 0
        wanted = []
        for hotel in hotels[:5]:
            hotel = hotel if isinstance(hotel, dict) else {}
            name = str(hotel.get('name') or '').strip()
            url = str(hotel.get('url') or '').strip()
            if name and url:
                wanted.append({'name': name, 'url': url})
        # Booking needs ~20 s per hotel (WAF + room table); loading the tabs
        # together overlaps that wait instead of paying it five times.
        props = session.open_urls([item['url'] for item in wanted])
        for item, prop in zip(wanted, props):
            if _market_deadline_hit(deadline):
                break
            name = item['name']
            url = item['url']
            prop = prop if isinstance(prop, dict) else {}
            prop_url = str(prop.get('final_url') or url)
            citations.append(_booking_scan_citation(
                prop_url, prop.get('title') or name, prop.get('text')))
            rate = prop.get('booking_rate')
            priced = isinstance(rate, dict) and rate.get('price') is not None
            print(f'[MARKET STUDY] booking property name={name!r} '
                  f'priced={priced} error={prop.get("error")!r} '
                  f'elapsed={prop.get("elapsed")}', flush=True)
            row = {
                'name': name,
                'project_type': 'فندقي',
                'operation_type': 'تشغيل فندقي',
                'hotel_stars': stars,
                'classification': 'مباشر',
                'status': 'قائم',
                'city': city_ar or city_en,
                'district': district_ar or district_en,
                'benchmarks': [benchmark] if benchmark else [],
                'source': 'Booking.com',
                'source_url': url,
                'source_urls': [url],
                'price_type': '',
                'price_value': '',
                'price_currency': '',
                'area_sqm': '',
                'area_mode': '',
                'row_source': 'booking',
                'verify_state': 'verified',
                'booking_discovered': True,
                'notes': '',
                'field_sources': {'name': [url]},
            }
            if priced:
                source_currency = str(rate.get('currency') or 'SAR').upper()
                fx_rate = 1.0
                if source_currency != 'SAR':
                    fx_rate = market_study.price_fx_to_sar(source_currency)
                    if not fx_rate:
                        priced = False
                if priced:
                    def _money(value):
                        if value is None:
                            return ''
                        return format_precise_number(
                            float(value) * fx_rate, grouped=False)

                    def _range(low, high):
                        low, high = _money(low), _money(high)
                        if low and high and low != high:
                            return f'من {low} إلى {high}'
                        return low or high

                    price_from = rate.get('price_from')
                    price_to = rate.get('price_to')
                    if price_from is None and price_to is None:
                        base = rate.get('price')
                        row_taxes = (0 if rate.get('tax_included')
                                     else (rate.get('taxes') or 0))
                        price_from = price_to = (
                            booking_rooms.whole_riyal(base + row_taxes)
                            if base is not None else None)
                    price_from = price_from or price_to
                    price_to = price_to or price_from
                    area_from = rate.get('area_from')
                    area_to = rate.get('area_to')
                    if area_from is None and area_to is None:
                        area_from = rate.get('area_sqm')
                        area_to = area_from
                    current = rate.get('current_price')
                    taxes = rate.get('taxes')
                    stay_label = hotel_stay.stay_nights_label_ar()
                    note = (
                        f'نطاق أسعار الغرف مقابل {stay_label} على Booking '
                        '(السعر الأصلي + الضريبة): '
                        f'{_range(price_from, price_to)} ر.س'
                        + (f' (محوّل من {source_currency})'
                           if source_currency != 'SAR' else '')
                        + (f'؛ المساحات {_range(area_from, area_to)} م²'
                           if area_from is not None else ''))
                    row.update({
                        'price_type': 'نطاق أسعار الغرف',
                        'price_value': '',
                        'price_from': _money(price_from),
                        'price_to': _money(price_to),
                        'price_currency': 'SAR',
                        'area_sqm': '',
                        'area_mode': ('range' if area_from is not None
                                      else ''),
                        'area_from': (_money(area_from)
                                      if area_from is not None else ''),
                        'area_to': (_money(area_to)
                                    if area_to is not None else ''),
                        'price_listed': True,
                        'notes': note,
                        'price_cache': {
                            'price_from': _money(price_from),
                            'price_to': _money(price_to),
                            'area_from': (_money(area_from)
                                          if area_from is not None else ''),
                            'area_to': (_money(area_to)
                                        if area_to is not None else ''),
                            'booking_current_price': current,
                            'booking_taxes': taxes,
                            'booking_currency': source_currency,
                            'booking_room_name': rate.get('room_name'),
                            'booking_source_url': url,
                        },
                        'field_sources': {
                            'name': [url],
                            'price_from': [url],
                            'price_to': [url],
                            'area_from': [url] if area_from is not None else [],
                            'area_to': [url] if area_to is not None else [],
                        },
                    })
            if not priced:
                row['notes'] = (
                    'صفحة الفندق على Booking.com لم تُرجع بلوك سعر/مساحة '
                    'لهذه الإقامة؛ السعر والمساحة غير متوفرين.')
            coords = prop.get('booking_coords')
            coords = coords if isinstance(coords, dict) else {}
            if coords:
                row['lat'] = coords.get('lat')
                row['lng'] = coords.get('lng')
            if scope_mode == 'distance':
                distance = market_study.competitor_distance_km(row, scope)
                if distance is None:
                    skipped_unverified += 1
                    continue
                if radius_km and distance > radius_km:
                    skipped_outside += 1
                    continue
                row['distance_km'] = distance
            rows.append(row)
        if not rows and scope_mode == 'distance' and (skipped_outside
                                                     or skipped_unverified):
            note = (f'لا توجد فنادق داخل نطاق {radius_km:g} كم من موقع المشروع '
                    f'(استُبعد {skipped_outside} خارج النطاق'
                    + (f' و{skipped_unverified} بلا إحداثيات موثقة'
                       if skipped_unverified else '')
                    + '). لم يُوسَّع النطاق ولم يُستخدم أي مصدر آخر.')
            return _booking_scan_result(
                task, [], citations, note, search_ran=True)
        priced_count = sum(
            1 for row in rows if row.get('price_from') or row.get('price_to'))
        if matched and matched.get('id'):
            scope_text = f' (فلتر حي {booking_search.facet_label(matched)} على Booking)'
        elif matched:
            scope_text = (f' (فلتر حي {booking_search.facet_label(matched)} '
                          f'من عنوان Booking)')
        else:
            scope_text = ' (بحث على مستوى المدينة: الحي غير معروض كفلتر على Booking)'
        if scope_mode == 'distance' and radius_km:
            scope_text = f' (داخل نطاق {radius_km:g} كم من موقع المشروع)'
        note = (
            f'تم جلب {len(rows)} فندقًا من صفحة نتائج Booking.com لحي '
            f'{display_district or district_en} في {city_ar or city_en}{scope_text}'
            + (f' — منها {priced_count} بسعر ومساحة.' if rows else '.'))
        return _booking_scan_result(task, rows, citations, note, search_ran=True)
    finally:
        try:
            session.close()
        except Exception:
            pass


def _run_single_competitor_scan(task, payload, existing, mode, offer_lang,
                                tenant_id, data, evidence_pool, deadline,
                                system_prompt, report, band, search_budget,
                                max_steps):
    """One axis (or one complementary angle) on its own browse-agent call.

    The worker owns the thread's browser and closes it in ``finally`` — a
    shared BrowserWorker is bound to the thread that opened it, so parallel
    scans must never share one.
    """
    axis = task.get('axis') if isinstance(task.get('axis'), dict) else {}
    deadline = _scan_deadline(deadline)
    if task.get('kind') == 'axis' and str(axis.get('type') or '') == 'hotel':
        return _booking_hotel_scan(
            task, payload, data, tenant_id=tenant_id,
            offer_lang=offer_lang, deadline=deadline)
    axis_payload = (payload if task.get('kind') in ('fill', 'legacy')
                    else _axis_scan_payload(payload, task.get('axis')))
    prompt = market_study.build_competitors_user_prompt(
        axis_payload, existing, mode=mode, offer_lang=offer_lang)
    if task.get('kind') == 'portals':
        prompt += _portals_focus_line(offer_lang)
    label = task.get('label') or 'البحث عن المنافسين'
    lo, hi = band
    session = _market_browser_session(search_provider='searxng')
    try:
        with _worker_app_context():
            response = _browse_agent_call(
                system_prompt, prompt,
                _usage_ctx('market', data, tenant_id=tenant_id),
                search_provider='searxng',
                evidence_pool=evidence_pool, deadline=deadline,
                session=session,
                search_budget=search_budget, max_steps=max_steps,
                max_tokens=14000, reasoning_effort='low',
                on_event=_market_agent_progress(report, lo, hi, label))
    except Exception as exc:
        return {
            'task': task, 'reply': None, 'parsed': {}, 'parse_error': '',
            'provider_error': f'browse_agent: {exc}', 'search_ran': False,
        }
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    provider_error = _chat_error_message(response) if isinstance(response, dict) and response.get('error') else ''
    parsed, parse_error = (_parse_market_model_json(response)
                           if isinstance(response, dict) else ({}, 'empty_response'))
    return {
        'task': task,
        'reply': response if isinstance(response, dict) else None,
        'parsed': parsed if isinstance(parsed, dict) else {},
        'parse_error': parse_error or '',
        'provider_error': provider_error or '',
        'search_ran': bool(isinstance(response, dict) and _market_search_ran(response)),
    }


def _run_scan_tasks(tasks, payload, existing, mode, offer_lang, tenant_id,
                    data, evidence_pool, deadline, system_prompt, report,
                    band=(22, 40)):
    if not tasks:
        return []
    report = _locked_report(report)
    search_budget, max_steps = _scan_search_limits(len(tasks))
    workers = min(_PARALLEL_SCAN_WORKERS, len(tasks)) or 1
    results = [None] * len(tasks)
    done = [0]
    total = len(tasks)
    lo, hi = band

    def _task_band(index):
        start = lo + int((hi - lo) * index / total)
        end = lo + int((hi - lo) * (index + 1) / total)
        return start, max(start + 1, end)

    with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix='market-scan') as workers_pool:
        future_map = {}
        for index, task in enumerate(tasks):
            future = workers_pool.submit(
                _run_single_competitor_scan, task, payload, existing, mode,
                offer_lang, tenant_id, data, evidence_pool, deadline,
                system_prompt, report, _task_band(index), search_budget,
                max_steps)
            future_map[future] = index
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    'task': tasks[index], 'reply': None, 'parsed': {},
                    'parse_error': '', 'provider_error': str(exc),
                    'search_ran': False,
                }
            results[index] = result
            done[0] += 1
            task = tasks[index]
            report(
                lo + int((hi - lo) * done[0] / total),
                f'اكتمل {task.get("label") or "بحث المحور"} '
                f'({done[0]} من {total})...')
    return [item for item in results if isinstance(item, dict)]


def _competitor_scan_tasks(axes, offer_lang='ar', mode='generate'):
    """One task per axis; a lone axis also gets a portal-focused twin."""
    if mode == 'fill':
        return [{'kind': 'fill', 'axis': None, 'label': 'إكمال بيانات المنافسين'}]
    if not any(axis.get('explicit') for axis in axes or []):
        # A legacy request without explicit comparison picks has one broad
        # table to build — no per-axis payload to filter.
        return [{'kind': 'legacy', 'axis': None, 'label': 'البحث عن المنافسين'}]
    tasks = []
    for axis in axes or []:
        tasks.append({
            'kind': 'axis',
            'axis': axis,
            'label': 'البحث عن ' + market_study.benchmark_axis_label(axis, offer_lang),
        })
    if len(tasks) == 1 and str(
            (tasks[0].get('axis') or {}).get('type') or '') != 'hotel':
        tasks.append({
            'kind': 'portals',
            'axis': tasks[0]['axis'],
            'label': 'البحث التكميلي عن ' + market_study.benchmark_axis_label(
                tasks[0]['axis'], offer_lang),
        })
    return tasks


def _expansion_scan_tasks(payload, axes, deficits, named_generated,
                          offer_lang='ar', multi_axis=False,
                          needs_benchmarks=False, evidence_pool=None):
    """Targeted tasks for axes still short of the minimum, one per axis."""
    if not deficits:
        return []
    scope = market_study.competitor_scope_text(payload)
    city = str((payload or {}).get('city') or '')
    district = str((payload or {}).get('district') or '')
    ptype = str((payload or {}).get('projectType')
                or (payload or {}).get('project_type') or 'عقاري')
    axis_label_list = '، '.join(
        market_study.benchmark_axis_label(axis, offer_lang) for axis in axes)
    known = '، '.join(str(row.get('name') or '') for row in named_generated or []) or 'لا يوجد'
    distance_field = (
        ', "distance_km":"المسافة الموثقة من موقع المشروع بالكيلومتر"'
        if (payload or {}).get('competitorScope', {}).get('mode') == 'distance' else '')
    tasks = []
    for axis in deficits:
        if str((axis or {}).get('type') or '') == 'hotel':
            continue
        angle = (f'{axis["search"]} داخل {scope} في {city}'
                 + (' عبر Booking.com' if axis.get('type') == 'hotel' else ''))
        if evidence_pool is not None and _pool_covers_angle(evidence_pool, angle):
            continue
        target_label = market_study.benchmark_axis_label(axis, offer_lang)
        priority = (f'أولوية هذه الجولة اختيار العميل «{target_label}» فقط. '
                    'لا تضف أنواعًا أو عمليات أخرى.')
        hotel_source_rule = (
            'لأن هذا محور فندقي، استخدم صفحات Booking.com فقط ولا تضع روابط فنادق من أي نطاق آخر. '
            'إذا أعادت صفحة الفندق تحديًا أمنيًا أو نسخة بوت بلا أسعار، لا تُعد المحاولة؛ '
            'أعد الصف بدون سعر ومساحة أو اذكر أنه غير موثق. '
            if axis.get('type') == 'hotel' else '')
        prompt = (
            f'نُجري دراسة سوق لمشروع {ptype} في {city}'
            + (f' — {district}' if district else '')
            + f'. نطاق المنافسين: {scope}.\n'
            + 'انسخ city وdistrict حرفيًا من بيانات المشروع؛ في نطاق الحي لا تذكر حيًا آخر.\n'
            + f'المنافسون المسجلون حتى الآن: {known}.\n'
            + f'ابحث عبر SearXNG عن: {angle} — مشاريع مسماة '
              'حقيقية لم ترد في القائمة. لا تُدرج صفحات مؤشرات أو إحصاءات كمنافس.\n'
            + (priority + '\n' if priority else '')
            + (f'قيم benchmarks المسموحة حصرًا: {axis_label_list}.\n'
               if needs_benchmarks else '')
            + hotel_source_rule
            + 'أعد JSON فقط: {"competitors":[{"name":"","city":"انسخ المدينة من بيانات المشروع حرفيًا",'
              '"district":"","hotel_stars":"",'
              '"benchmarks":[],"operation_type":"","price_type":"","price_currency":"",'
              '"price":"","source_urls":[]' + distance_field + '}]} '
              'مع بقية الحقول المعتادة عند توفرها.'
              + (' Write every field value in English using the allowed English enum '
                 'values (status: Operating/Under Construction/Off-Plan; classification: '
                 'Direct/Indirect/Benchmark; operation_type: Sale/Rent/Hotel Operation/Other).'
                 if offer_lang == 'en' else ''))
        tasks.append({
            'kind': 'expansion',
            'axis': axis,
            'label': 'بحث إضافي عن ' + target_label,
            'prompt': prompt,
        })
    return tasks


def _run_expansion_scan_task(task, payload, existing, mode, offer_lang,
                             tenant_id, data, evidence_pool, deadline,
                             system_prompt, report, band, search_budget,
                             max_steps):
    prompt = task.get('prompt') or market_study.build_competitors_user_prompt(
        _axis_scan_payload(payload, task.get('axis')), existing,
        mode=mode, offer_lang=offer_lang)
    lo, hi = band
    session = _market_browser_session(search_provider='searxng')
    try:
        with _worker_app_context():
            response = _browse_agent_call(
                system_prompt, prompt,
                _usage_ctx('market', data, tenant_id=tenant_id),
                search_provider='searxng',
                evidence_pool=evidence_pool, deadline=deadline,
                session=session,
                search_budget=search_budget, max_steps=max_steps,
                max_tokens=14000, reasoning_effort='low',
                on_event=_market_agent_progress(report, lo, hi,
                                                task.get('label') or 'بحث إضافي'))
    except Exception as exc:
        return {
            'task': task, 'reply': None, 'parsed': {}, 'parse_error': '',
            'provider_error': f'browse_agent: {exc}', 'search_ran': False,
        }
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    provider_error = _chat_error_message(response) if isinstance(response, dict) and response.get('error') else ''
    parsed, parse_error = (_parse_market_model_json(response)
                           if isinstance(response, dict) else ({}, 'empty_response'))
    return {
        'task': task,
        'reply': response if isinstance(response, dict) else None,
        'parsed': parsed if isinstance(parsed, dict) else {},
        'parse_error': parse_error or '',
        'provider_error': provider_error or '',
        'search_ran': bool(isinstance(response, dict) and _market_search_ran(response)),
    }


def _run_parallel_expansions(tasks, payload, existing, mode, offer_lang,
                             tenant_id, data, evidence_pool, deadline,
                             system_prompt, report, band=(40, 52)):
    if not tasks:
        return []
    report = _locked_report(report)
    search_budget = max(3, int(_COMPETITORS_SEARCH_BUDGET) // max(1, len(tasks) + 2))
    max_steps = max(5, int(_COMPETITORS_MAX_STEPS) // max(1, len(tasks) + 1))
    workers = min(_PARALLEL_SCAN_WORKERS, len(tasks)) or 1
    results = [None] * len(tasks)
    done = [0]
    total = len(tasks)
    lo, hi = band

    def _task_band(index):
        start = lo + int((hi - lo) * index / total)
        end = lo + int((hi - lo) * (index + 1) / total)
        return start, max(start + 1, end)

    with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix='market-expand') as workers_pool:
        future_map = {}
        for index, task in enumerate(tasks):
            future = workers_pool.submit(
                _run_expansion_scan_task, task, payload, existing, mode,
                offer_lang, tenant_id, data, evidence_pool, deadline,
                system_prompt, report, _task_band(index), search_budget,
                max_steps)
            future_map[future] = index
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = {
                    'task': tasks[index], 'reply': None, 'parsed': {},
                    'parse_error': '', 'provider_error': str(exc),
                    'search_ran': False,
                }
            done[0] += 1
            report(
                lo + int((hi - lo) * done[0] / total),
                f'اكتمل البحث الإضافي ({done[0]} من {total})...')
    return [item for item in results if isinstance(item, dict)]


def _aggregate_scan_results(results):
    """Combine parallel replies: rows, citations source, note and errors."""
    usable = [item for item in results or []
              if isinstance(item, dict) and item.get('parsed')]
    provider_error = next(
        (str(item.get('provider_error') or '').strip()
         for item in results or []
         if str(item.get('provider_error') or '').strip()), '')
    parse_error = '' if usable else next(
        (str(item.get('parse_error') or '').strip()
         for item in results or []
         if str(item.get('parse_error') or '').strip()), '')
    notes = []
    for item in usable:
        note = str((item.get('parsed') or {}).get('notes') or '').strip()
        if note and note not in notes:
            notes.append(note)
    competitors = []
    for item in usable:
        rows = (item.get('parsed') or {}).get('competitors')
        if isinstance(rows, list):
            competitors.extend(row for row in rows if isinstance(row, dict))
    return {
        'usable': usable,
        'competitors': competitors,
        'notes': ' — '.join(notes),
        'provider_error': provider_error,
        'parse_error': parse_error,
        'search_ran': any(item.get('search_ran') for item in results or []),
    }
