# ---------------------------------------------------------------------------
# Booking.com deterministic hotel scan.
#
# Resolves project coordinates to Booking's destination ID and retrieves
# verified hotel properties within the project's district/city scope.
# ---------------------------------------------------------------------------

import json
import os
import time

import booking_destination
import booking_rooms
import booking_search
import hotel_stay
import maps_service
from numeric_precision import format_precise_number


# A radius scope has to look past the first few cards to prove what sits inside
# it. Ten property pages in batches of five cost roughly a minute of the scan
# budget and still leave room for the district and verification stages.
_BOOKING_SCAN_MAX_HOTELS = max(
    5, int(os.environ.get('BOOKING_SCAN_MAX_HOTELS') or 10))
_BOOKING_SCAN_TAB_BATCH = max(1, int(
    os.environ.get('BOOKING_SCAN_TAB_BATCH') or 5))


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
                        district_label, city_label, filter_error=''):
    """Why a Booking scan produced no hotels, naming the actual cause."""
    search = search if isinstance(search, dict) else {}
    where = (f'لحي {district_label} في {city_label}' if district_label
             else f'في {city_label}')
    if filter_error:
        return (f'تعذّر فتح نتائج فلتر حي {district_label} على Booking '
                f'({filter_error})، فلم تُقرأ فنادق الحي. '
                f'لم يُستخدم أي مصدر آخر.')
    error_code = booking_search.search_error_code(search.get('final_url'))
    if error_code:
        return (f'رفض Booking البحث النصّي ({error_code}) فلم تُفتح صفحة نتائج '
                f'{where}. لم يُستخدم أي مصدر آخر.')
    if search.get('error'):
        return (f'تعذّر فتح صفحة نتائج Booking.com {where} '
                f'({search.get("error")}). لم يُستخدم أي مصدر آخر.')
    if not (destination or {}).get('dest_id'):
        return (f'تعذّر تحديد وجهة المدينة على Booking، فلم تُرجع صفحة النتائج '
                f'فنادق {where}. لم يُستخدم أي مصدر آخر.')
    if matched_district:
        return (f'لا توجد فنادق مطابقة لحي {district_label} '
                f'في {city_label} على Booking.com. لم يُستخدم أي مصدر آخر.')
    return (f'لم تُرجع صفحة نتائج Booking.com فنادق {where} '
            f'دون فلتر حي (الحي غير معروض ضمن أحياء Booking لهذه المدينة). '
            f'لم يُستخدم أي مصدر آخر.')


def _booking_hotel_scan(task, payload, data, tenant_id=None, offer_lang='ar',
                        deadline=None, session=None):
    """Deterministic hotel discovery from Booking search + property pages.

    No model decides which hotel page to open: the project city is resolved to
    Booking's own destination id (a free-text search is refused), the city's
    hotels are filtered by Booking's neighbourhood filter for the project
    district, the hotel cards become the competitors, and each property page's
    ``## BOOKING_RATE ##`` block supplies the original pre-discount stay price
    and room area. Stars are not a competitor dimension (owner decision
    2026-10-27), so no class filter is applied.
    """
    axis = task.get('axis') if isinstance(task.get('axis'), dict) else {}
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
    owns_session = session is None
    if owns_session:
        session = _market_browser_session(search_provider='searxng')
    if session is None:
        return _booking_scan_result(
            task, [], [], 'browser_unavailable', search_ran=False)
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
            city_en or city_ar, dest_id=dest_id, dest_type=dest_type)
        print(f'[MARKET STUDY] booking hotel search city={city_en!r} '
              f'district={district_en!r} country={country_code!r} '
              f'dest_id={dest_id!r} url={search_url}', flush=True)
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
                # page is narrower than the city when the nflt neighbourhood
                # filter is ignored.
                filtered_url = booking_search.build_search_url(
                    city_en or city_ar, dest_id=district_id,
                    dest_type='district')
            else:
                filtered_url = booking_search.build_search_url(
                    city_en or city_ar, dest_id=dest_id,
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

        # The Booking filter runs once per district the client picked — the
        # project's own district plus every one added on the market screen —
        # and their cards are merged. It used to run for the project district
        # alone, so a widened scope never reached the hotel axis.
        scope_districts = ([district_ar] if scope_mode != 'district'
                           else market_study.competitor_scope_districts(
                               scope, district_ar))

        def _district_aliases(name):
            """The names Booking may print for one selected district."""
            text = str(name or '').strip()
            aliases = [text]
            if text == district_ar and district_en:
                aliases.append(district_en)
            return tuple(alias for alias in aliases if alias)

        def _display_name(name):
            text = str(name or '').strip()
            return text[3:].strip() if text.startswith('حي ') else text

        def _district_cards_from_city(names_list=None):
            """The initial city cards whose own Booking address names one of
            the selected districts."""
            names = tuple(alias for name in (names_list or scope_districts)
                           for alias in _district_aliases(name))
            cards = booking_search.filter_hotels_by_district(
                (search.get('booking_search') or {}).get('hotels') or [],
                *names)
            if not cards:
                return None
            narrowed = dict(search)
            narrowed['booking_search'] = dict(
                search.get('booking_search') or {}, hotels=cards)
            return narrowed

        def _use_filtered(district_id, name):
            nonlocal matched
            aliases = _district_aliases(name)
            attempts = ((False, 'neighbourhood filter'),
                        (False, 'neighbourhood filter retry'),
                        (True, 'district destination'))
            for as_destination, label in attempts:
                filtered, filtered_final, applied = _apply_district(
                    district_id, as_destination)
                cards = ((filtered.get('booking_search') or {})
                         .get('hotels') or [])
                kept = booking_search.filter_hotels_by_district(
                    cards, *aliases)
                if not filtered.get('error') and applied and kept:
                    matched = dict(matched or {}, id=str(district_id))
                    citations.append(_booking_scan_citation(
                        filtered_final, filtered.get('title'),
                        filtered.get('text')))
                    return kept, ''
                print(f'[MARKET STUDY] booking district attempt '
                      f'({label}) kept={len(kept)}', flush=True)
            note = _booking_empty_note(
                filtered, destination=destination, matched_district=None,
                filter_error=str(
                    filtered.get('error') or 'filter_not_applied'),
                district_label=_display_name(name) or district_en,
                city_label=city_ar or city_en)
            return [], note

        collected_hotels = []
        collected_urls = set()
        used_districts = []
        failure_notes = []

        def _collect(cards):
            added = 0
            for card in cards or []:
                if not isinstance(card, dict):
                    continue
                key = str(card.get('url') or card.get('name') or '').strip()
                if not key or key in collected_urls:
                    continue
                collected_urls.add(key)
                collected_hotels.append(card)
                added += 1
            return added

        if scope_mode == 'district' and (scope or matched):
            district_key_city = city_en or city_ar
            for name in scope_districts:
                if _market_deadline_hit(deadline):
                    break
                label = _display_name(name) or district_en
                district_id = str((booking_search.match_district_facet(
                    search.get('booking_districts') or [],
                    *_district_aliases(name)) or {}).get('id') or '')
                if not district_id:
                    district_id = booking_destination.cached_district_id(
                        cache_path, country_code, district_key_city, label)
                if district_id:
                    booking_destination.remember_district_id(
                        cache_path, country_code, district_key_city, label,
                        district_id)
                    kept, note = _use_filtered(district_id, name)
                    if kept:
                        used_districts.append((name, 'facet'))
                        _collect(kept)
                        continue
                    failure_notes.append(note)
                else:
                    failure_notes.append(
                        f'لم يُعرض حي {label} كفلتر على Booking.com لهذه '
                        f'المدينة، ولم يُوسَّع البحث إلى المدينة. لم يُستخدم أي '
                        f'مصدر آخر.')
                # Booking only lists the ten largest districts as facets. When
                # this district is hidden, keep the city cards whose own
                # address line names it — still that district, never the
                # whole city.
                address_cards = _district_cards_from_city([name])
                if address_cards is not None and _collect(
                        (address_cards.get('booking_search') or {})
                        .get('hotels') or []):
                    used_districts.append((name, 'address'))
                    print(f'[MARKET STUDY] booking district {name!r} read '
                          f'from its own address lines', flush=True)
            if not collected_hotels:
                city_cards = ((search.get('booking_search') or {})
                              .get('hotels') or [])
                sample = [(card.get('location'), (card.get('text') or '')[:60])
                          for card in city_cards[:3]]
                print(f'[MARKET STUDY] booking districts unavailable '
                      f'districts={scope_districts!r} '
                      f'city_cards={len(city_cards)} sample={sample!r}',
                      flush=True)
                note = failure_notes[0] if failure_notes else (
                    'لم تُعرض أحياء البحث كفلتر على Booking.com لهذه المدينة، '
                    'ولم يُوسَّع البحث إلى المدينة. لم يُستخدم أي مصدر آخر.')
                return _booking_scan_result(
                    task, [], citations, note, search_ran=True)
        else:
            matched = None
        search_data = search.get('booking_search') \
            if isinstance(search.get('booking_search'), dict) else {}
        hotels = collected_hotels or (search_data.get('hotels') or [])
        print(f'[MARKET STUDY] booking search final_url={search.get("final_url")} '
              f'cards={len(hotels)} '
              f'chars={len(str(search.get("text") or ""))}', flush=True)
        if not hotels:
            note = _booking_empty_note(
                search, destination=destination, matched_district=matched,
                district_label=display_district or district_en,
                city_label=city_ar or city_en)
            return _booking_scan_result(
                task, [], citations, note, search_ran=True)
        benchmark = market_study.benchmark_axis_label(axis, offer_lang)
        skipped_outside = skipped_unverified = 0
        wanted = []
        for hotel in hotels[:_BOOKING_SCAN_MAX_HOTELS]:
            hotel = hotel if isinstance(hotel, dict) else {}
            name = str(hotel.get('name') or '').strip()
            url = str(hotel.get('url') or '').strip()
            if name and url:
                wanted.append({'name': name, 'url': url})
        # Booking needs ~20 s per hotel (WAF + room table); loading a batch of
        # tabs together overlaps that wait. A radius scope has to look past the
        # first five cards, so the scan reads in batches until it has enough
        # candidates or the deadline arrives.
        props = []
        for start in range(0, len(wanted), _BOOKING_SCAN_TAB_BATCH):
            if _market_deadline_hit(deadline):
                break
            props.extend(session.open_urls(
                [item['url'] for item in
                 wanted[start:start + _BOOKING_SCAN_TAB_BATCH]]))
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
                        price_from = price_to = (
                            booking_rooms.whole_riyal(base)
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
                        f"({booking_rooms.note_basis_ar(rate.get('tax_included'), rate.get('taxes'))}): "
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
        used_labels = '، '.join(_display_name(name) for name, _source in used_districts)
        if scope_mode == 'district' and used_districts:
            if len(used_districts) == 1:
                label = _display_name(used_districts[0][0])
                scope_text = (f' (فلتر حي {label} على Booking)'
                              if used_districts[0][1] == 'facet' else
                              f' (فلتر حي {label} من عنوان Booking)')
            else:
                scope_text = f' (فلتر أحياء {used_labels} على Booking)'
        elif scope_mode == 'distance':
            scope_text = (f' (داخل نطاق {radius_km:g} كم من موقع المشروع)'
                          if radius_km else '')
        else:
            scope_text = (f' (بحث على مستوى مدينة {city_ar or city_en}: '
                          f'الحي غير مختار كفلتر)')
        if scope_mode == 'district' and len(used_districts) > 1:
            place = f'لأحياء {used_labels} في {city_ar or city_en}'
        elif scope_mode == 'district':
            single = (_display_name(used_districts[0][0]) if used_districts
                      else (display_district or district_en))
            place = f'لحي {single} في {city_ar or city_en}'
        else:
            place = f'لمدينة {city_ar or city_en}'
        note = (
            f'تم جلب {len(rows)} فندقًا من صفحة نتائج Booking.com {place}{scope_text}'
            + (f' — منها {priced_count} بسعر ومساحة.' if rows else '.'))
        return _booking_scan_result(task, rows, citations, note, search_ran=True)
    finally:
        if owns_session:
            try:
                session.close()
            except Exception:
                pass
