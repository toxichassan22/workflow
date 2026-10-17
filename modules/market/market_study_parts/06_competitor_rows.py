
# ---------------------------------------------------------------------------
# Competitor rows — normalization, merge, source attachment and review flags.
# Carved out of 02_competitor_analysis.py (prompt builders + input formatting)
# to keep every part under the ~1,000-line rule; same exec'd market_study
# namespace, so helpers here call the earlier parts' functions unchanged.
# ---------------------------------------------------------------------------

def normalize_competitor_row(row, fallback_source='ai', offer_lang='ar'):
    if not isinstance(row, dict):
        return None
    name = _norm(row.get('name') or row.get('project_name') or row.get('projectName'))
    if not name:
        return None
    project_type = _norm(row.get('project_type') or row.get('projectType') or row.get('نوع المشروع'))
    price_payload = row.get('price') if isinstance(row.get('price'), dict) else {}
    raw_price_type = _first_nonempty(
        row.get('price_type'), row.get('priceType'), row.get('نوع السعر'), row.get('نوع التسعير'),
        price_payload.get('type'), price_payload.get('price_type'), price_payload.get('priceType'),
        price_payload.get('نوع السعر'),
    )
    price_value = _first_nonempty(
        row.get('price_value'), row.get('priceValue'), row.get('value'),
        row.get('القيمة'), row.get('السعر'), row.get('المبلغ'), row.get('amount'),
        price_payload.get('value'), price_payload.get('price_value'), price_payload.get('priceValue'),
        price_payload.get('القيمة'), price_payload.get('السعر'), price_payload.get('amount'),
        row.get('price') if not price_payload else '',
    )
    price_from = _first_nonempty(
        row.get('price_from'), row.get('priceFrom'), row.get('price_min'), row.get('priceMin'),
        row.get('min_price'), row.get('minPrice'), row.get('from'), row.get('من'), row.get('الحد الأدنى'),
        price_payload.get('from'), price_payload.get('price_from'), price_payload.get('priceFrom'),
        price_payload.get('من'), price_payload.get('min'), price_payload.get('minimum'),
    )
    price_to = _first_nonempty(
        row.get('price_to'), row.get('priceTo'), row.get('price_max'), row.get('priceMax'),
        row.get('max_price'), row.get('maxPrice'), row.get('to'), row.get('إلى'), row.get('الى'), row.get('الحد الأعلى'),
        price_payload.get('to'), price_payload.get('price_to'), price_payload.get('priceTo'),
        price_payload.get('إلى'), price_payload.get('الى'), price_payload.get('max'), price_payload.get('maximum'),
    )
    price_value = _clean_numeric(price_value)
    price_from = _clean_numeric(price_from)
    price_to = _clean_numeric(price_to)
    price_currency = _canonical_price_currency(_first_nonempty(
        row.get('price_currency'), row.get('priceCurrency'), row.get('currency'),
        row.get('العملة'), row.get('عملة السعر'),
        price_payload.get('currency'), price_payload.get('price_currency'),
        price_payload.get('priceCurrency'), price_payload.get('العملة'),
    ))
    area_cache = row.get('area_cache') if isinstance(row.get('area_cache'), dict) else {}
    area_sqm = _clean_numeric(_first_nonempty(
        row.get('area_sqm'), row.get('areaSqm'), row.get('area'), row.get('المساحة'), area_cache.get('area_sqm')))
    area_from = _clean_numeric(_first_nonempty(
        row.get('area_from'), row.get('areaFrom'), row.get('المساحة من'), area_cache.get('area_from')))
    area_to = _clean_numeric(_first_nonempty(
        row.get('area_to'), row.get('areaTo'), row.get('المساحة إلى'), area_cache.get('area_to')))
    requested_area_mode = _norm(row.get('area_mode') or row.get('areaMode'))
    area_mode = ('range' if requested_area_mode == 'range' else 'fixed'
                 if requested_area_mode == 'fixed' else 'range' if area_from or area_to else 'fixed')
    operation = _canonical_operation(
        row.get('operation_type') or row.get('operationType') or row.get('operation') or row.get('نوع العملية')
        or row.get('نوع التشغيل') or row.get('التشغيل'),
        raw_price_type,
        project_type,
        offer_lang=offer_lang,
    )
    price_type = _canonical_price_type(
        raw_price_type, operation, price_from, price_to, price_value, offer_lang=offer_lang)
    classification = _norm(row.get('classification') or row.get('class') or row.get('تصنيف'))
    status = _norm(row.get('status') or row.get('project_status') or row.get('حالة المشروع'))
    field_sources = competitor_field_sources(row)
    source_urls = competitor_source_urls(row)
    price_source_urls = (
        field_sources.get('price_value', [])
        + field_sources.get('price_from', [])
        + field_sources.get('price_to', [])
    )
    source_url = prefer_specific_source_url(
        row.get('source_url'), row.get('sourceUrl'), row.get('url'),
        *price_source_urls,
        *source_urls,
    )
    logo_url = _norm(row.get('logo_url') or row.get('logoUrl'))
    logo_source_url = prefer_specific_source_url(
        row.get('logo_source_url'), row.get('logoSourceUrl'),
        *(field_sources.get('logo_url') or []),
    )
    district = _norm(row.get('district') or row.get('neighborhood') or row.get('الحي'))
    distance_km = _clean_numeric(_first_nonempty(
        row.get('distance_km'), row.get('distanceKm'), row.get('distance'), row.get('المسافة')))
    lat = _clean_numeric(_first_nonempty(row.get('lat'), row.get('latitude'), row.get('خط العرض')))
    lng = _clean_numeric(_first_nonempty(
        row.get('lng'), row.get('lon'), row.get('longitude'), row.get('خط الطول')))
    conflict_warnings = row.get('conflict_warnings') if isinstance(row.get('conflict_warnings'), list) else []
    raw_benchmarks = (row.get('benchmarks') or row.get('benchmark_axes')
                      or row.get('measured_against') or row.get('serves_components')
                      or row.get('يُقاس على') or row.get('يقاس على'))
    benchmark_items = raw_benchmarks if isinstance(raw_benchmarks, (list, tuple)) else [raw_benchmarks]
    benchmarks = _unique_values(
        part for item in benchmark_items for part in _split_multi_values(item))
    result = {
        'id': _norm(row.get('id')) or str(uuid.uuid4()),
        'name': name,
        'project_type': project_type,
        'comparison_type': _norm(row.get('comparison_type') or row.get('comparisonType')),
        'hotel_stars': _clean_numeric(
            row.get('hotel_stars') or row.get('hotelStars')
            or row.get('star_rating') or row.get('stars')),
        'area_mode': area_mode,
        'area_sqm': area_sqm if area_mode == 'fixed' else '',
        'area_from': area_from if area_mode == 'range' else '',
        'area_to': area_to if area_mode == 'range' else '',
        'area_cache': {'area_sqm': area_sqm, 'area_from': area_from, 'area_to': area_to},
        'status': status,
        'classification': classification,
        'benchmarks': benchmarks,
        'logo_file_id': _norm(row.get('logo_file_id') or row.get('logoFileId')),
        'logo_path': _norm(row.get('logo_path') or row.get('logoPath')),
        'logo_url': logo_url,
        'logo_source_url': logo_source_url,
        'district': district,
        'city': _norm(row.get('city') or row.get('location_city')),
        'distance_km': distance_km,
        'lat': lat,
        'lng': lng,
        'conflict_warnings': list(conflict_warnings),
        'operation_type': operation,
        'price_type': price_type,
        'price_value': price_value,
        'price_from': price_from,
        'price_to': price_to,
        'price_currency': price_currency,
        'price_cache': row.get('price_cache') if isinstance(row.get('price_cache'), dict) else {},
        'source': _norm(row.get('source') or row.get('source_name') or row.get('sourceName')),
        'source_url': source_url,
        'source_urls': source_urls,
        'field_sources': field_sources,
        'data_date': _norm(row.get('data_date') or row.get('dataDate')),
        'notes': _norm(row.get('notes') or row.get('note')),
        'verify_state': _norm(row.get('verify_state') or row.get('verifyState')),
        'verify_provider_error': _norm(row.get('verify_provider_error') or row.get('verifyProviderError')),
        'row_source': _norm(row.get('row_source') or row.get('rowSource')) or fallback_source,
    }
    return result


def _resolve_source_urls(urls, citations, operation=''):
    resolved = []
    for url in urls:
        value = resolve_source_url_from_citations(url, citations, operation)
        if value:
            resolved.append(value)
    return _unique_values(resolved)


def canonicalize_competitor_source_urls(row):
    """Normalize portal-homepage links on a competitor row to the dataset page.

    Citation resolution upgrades a homepage only when the search retrieved a
    deeper page on the same host; this pass catches the rows the retrieval left
    behind, including links merged in by the per-competitor verification.
    """
    if not isinstance(row, dict):
        return row
    operation = _norm(
        row.get('operation_type') or row.get('operationType') or row.get('operation'))
    urls = competitor_source_urls(row)
    resolved = _unique_values(canonical_index_source_url(item, operation) for item in urls)
    if resolved:
        row['source_urls'] = resolved
    field_sources = competitor_field_sources(row)
    if field_sources:
        row['field_sources'] = {
            field: _unique_values(canonical_index_source_url(item, operation) for item in urls)
            for field, urls in field_sources.items()
        }
    source_url = _norm(row.get('source_url'))
    if source_url:
        row['source_url'] = canonical_index_source_url(source_url, operation)
    return row


def apply_search_citations(rows, citations, url_key='source_url'):
    """Upgrade AI-written homepage links to the exact pages returned by the search.

    Runs even with an empty citation set: known indicator portals still resolve
    their bare homepage to the fixed dataset page for the row's operation.
    """
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if (row.get('row_source') or 'ai') != 'ai' and url_key == 'source_url':
            continue
        if url_key == 'source_url':
            operation = _norm(
                row.get('operation_type') or row.get('operationType') or row.get('operation'))
            field_sources = competitor_field_sources(row)
            resolved_field_sources = {
                field: resolved
                for field, urls in field_sources.items()
                if (resolved := _resolve_source_urls(urls, citations, operation))
            }
            urls = competitor_source_urls(row)
            resolved_urls = _resolve_source_urls(urls, citations, operation)
            if resolved_urls:
                row['source_urls'] = resolved_urls
                price_urls = (
                    resolved_field_sources.get('price_value', [])
                    + resolved_field_sources.get('price_from', [])
                    + resolved_field_sources.get('price_to', [])
                )
                row['source_url'] = prefer_specific_source_url(*price_urls, *resolved_urls)
            if resolved_field_sources:
                row['field_sources'] = resolved_field_sources
            continue
        resolved = resolve_source_url_from_citations(row.get(url_key), citations)
        if resolved:
            row[url_key] = resolved
    return rows


def competitor_source_rows(competitors):
    rows = []
    for competitor in competitors or []:
        if not isinstance(competitor, dict):
            continue
        name = _norm(competitor.get('name'))
        if not name:
            continue
        source_name = _norm(competitor.get('source')) or 'مصدر المنافس'
        note = _norm(competitor.get('notes') or competitor.get('note'))
        competitor_id = _norm(competitor.get('id'))
        field_sources = competitor_field_sources(competitor)
        dead_keys = {str(item).casefold() for item in (competitor.get('dead_source_urls') or [])}
        for url in competitor_source_urls(competitor):
            source_fields = [
                _COMPETITOR_SOURCE_FIELD_LABELS.get(field, field)
                for field, urls in field_sources.items()
                if any(str(item).casefold() == url.casefold() for item in urls)
            ]
            field_note = 'الحقول: ' + '، '.join(source_fields) if source_fields else ''
            unverified_note = 'رابط غير موثق — لم يصل من نتائج البحث' if competitor.get('sources_unverified') else ''
            dead_note = 'الرابط لم يعد يعمل' if str(url).casefold() in dead_keys else ''
            source_note = ' — '.join(item for item in (note, field_note, unverified_note, dead_note) if item)
            rows.append({
                'id': str(uuid.uuid4()),
                'competitor_id': competitor_id,
                'competitor_name': name,
                'source_kind': 'competitor',
                'source_fields': source_fields,
                'name': source_name,
                'url': url,
                'data_date': _norm(competitor.get('data_date')),
                'accessed_at': date.today().isoformat(),
                'reliability': official_source_reliability(name, source_name, url),
                'note': source_note,
            })
    return rows


def _competitor_value_filled(value):
    if value is None:
        return False
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return bool(_norm(value))


def _competitor_values_equal(left, right):
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return left == right
    return _norm(left).casefold() == _norm(right).casefold()


def merge_generated_competitors(existing, generated, mode='generate', offer_lang='ar'):
    current = []
    for row in existing or []:
        if not isinstance(row, dict):
            continue
        normalized = normalize_competitor_row(
            row, fallback_source=_norm(row.get('row_source')) or 'manual', offer_lang=offer_lang)
        if normalized:
            current.append(normalized)
    if mode != 'fill':
        replaced = []
        for raw in generated or []:
            incoming = normalize_competitor_row(raw, offer_lang=offer_lang)
            if incoming:
                replaced.append(incoming)
        return replaced, len(replaced), 0
    by_id = {str(row.get('id')): index for index, row in enumerate(current)}
    by_name = {_norm(row.get('name')).casefold(): index for index, row in enumerate(current)}
    updated = 0
    protected = {
        'id', 'name', 'row_source', 'field_sources', 'source_urls', 'conflict_warnings',
        'area_mode', 'area_sqm', 'area_from', 'area_to', 'area_cache',
    }
    official_label = 'Official source' if offer_lang == 'en' else 'مصدر رسمي للجهة'
    for raw in generated or []:
        incoming = normalize_competitor_row(raw, offer_lang=offer_lang)
        if not incoming:
            continue
        index = by_id.get(incoming['id'])
        if index is None:
            index = by_name.get(incoming['name'].casefold())
        if index is None:
            continue
        target = current[index]
        target_sources = competitor_field_sources(target)
        incoming_sources = competitor_field_sources(incoming)
        warnings = list(target.get('conflict_warnings') or [])
        has_manual_logo = bool(target.get('logo_file_id') or target.get('logo_path'))
        target_has_price = any(_competitor_value_filled(target.get(key))
                               for key in ('price_value', 'price_from', 'price_to'))
        incoming_has_price = any(_competitor_value_filled(incoming.get(key))
                                 for key in ('price_value', 'price_from', 'price_to'))
        target_has_area = any(_competitor_value_filled(target.get(key))
                              for key in ('area_sqm', 'area_from', 'area_to'))
        incoming_has_area = any(_competitor_value_filled(incoming.get(key))
                                for key in ('area_sqm', 'area_from', 'area_to'))
        if incoming_has_area and not target_has_area:
            for key in ('area_mode', 'area_sqm', 'area_from', 'area_to', 'area_cache'):
                target[key] = incoming.get(key)
            for key in ('area_sqm', 'area_from', 'area_to'):
                if incoming_sources.get(key):
                    target_sources[key] = _unique_values(incoming_sources[key])
            updated += 1
        elif incoming_has_area and target_has_area:
            target_area = (target.get('area_mode'), target.get('area_sqm'), target.get('area_from'), target.get('area_to'))
            incoming_area = (incoming.get('area_mode'), incoming.get('area_sqm'), incoming.get('area_from'), incoming.get('area_to'))
            area_urls = _unique_values(
                (incoming_sources.get('area_sqm') or [])
                + (incoming_sources.get('area_from') or [])
                + (incoming_sources.get('area_to') or [])
            )
            official_url = next((url for url in area_urls if official_source_reliability(
                incoming.get('name'), incoming.get('source'), url)), '')
            if target_area != incoming_area and official_url:
                warnings.append({
                    'field': 'area_mode', 'existing': target_area, 'incoming': incoming_area,
                    'source': incoming.get('source') or official_label, 'source_url': official_url,
                })
        for key, value in incoming.items():
            if key in protected or (has_manual_logo and key in {'logo_url', 'logo_source_url'}):
                continue
            if key == 'price_currency':
                # A currency tag only travels with the price it labels — merged
                # alone it would brand the row's existing SAR figure as foreign.
                continue
            current_value = target.get(key)
            if _competitor_value_filled(value) and not _competitor_value_filled(current_value):
                target[key] = value
                if incoming_sources.get(key):
                    target_sources[key] = _unique_values(
                        (target_sources.get(key) or []) + incoming_sources[key]
                    )
                updated += 1
                continue
            if not (_competitor_value_filled(value) and _competitor_value_filled(current_value)):
                continue
            if _competitor_values_equal(current_value, value):
                continue
            urls = incoming_sources.get(key) or []
            official_url = next((url for url in urls if official_source_reliability(
                incoming.get('name'), incoming.get('source'), url)), '')
            if official_url:
                warning = {
                    'field': key,
                    'existing': current_value,
                    'incoming': value,
                    'source': incoming.get('source') or official_label,
                    'source_url': official_url,
                }
                signature = (key, str(current_value), str(value), official_url)
                existing_signatures = {
                    (item.get('field'), str(item.get('existing')), str(item.get('incoming')), item.get('source_url'))
                    for item in warnings if isinstance(item, dict)
                }
                if signature not in existing_signatures:
                    warnings.append(warning)
        if (not target_has_price and incoming_has_price
                and _competitor_value_filled(incoming.get('price_currency'))):
            target['price_currency'] = incoming['price_currency']
        target['field_sources'] = target_sources
        target['source_urls'] = _unique_values(competitor_source_urls(target) + competitor_source_urls(incoming))
        target['source_url'] = prefer_specific_source_url(target.get('source_url'), *target['source_urls'])
        target['conflict_warnings'] = warnings
    return current, 0, updated


def normalize_summary(raw):
    data = raw if isinstance(raw, dict) else {}
    raw_summary = data.get('summary')
    summary_source = raw_summary if isinstance(raw_summary, dict) else None
    if summary_source is None:
        top_level = {item['key']: data.get(item['key']) for item in SUMMARY_SECTIONS}
        if any(_norm(value) for value in top_level.values()):
            summary_source = top_level
    if isinstance(summary_source, dict):
        summary = {
            item['key']: _norm(summary_source.get(item['key'])) or MISSING_VALUE_PHRASE
            for item in SUMMARY_SECTIONS
        }
    else:
        # Keep a paragraph returned by an older model readable until the next
        # generation. New responses always use the structured object above.
        summary = _norm(raw_summary) if isinstance(raw_summary, str) else {}
    decision = _norm(data.get('decision'))
    if decision not in DECISION_OPTIONS:
        matched = next((option for option in DECISION_OPTIONS if option in decision), '')
        decision = matched or 'البيانات غير كافية'
    sources = []
    raw_sources = data.get('sources')
    if isinstance(raw_sources, list):
        for row in raw_sources:
            if not isinstance(row, dict):
                continue
            name = _norm(row.get('name'))
            if not name:
                continue
            url = prefer_specific_source_url(row.get('url'), row.get('source_url'), row.get('sourceUrl'))
            sources.append({
                'id': _norm(row.get('id')) or str(uuid.uuid4()),
                'name': name,
                'url': url,
                'data_date': _norm(row.get('data_date') or row.get('dataDate')),
                'accessed_at': _norm(row.get('accessed_at') or row.get('accessedAt')) or date.today().isoformat(),
                'reliability': _norm(row.get('reliability')) or official_source_reliability('', name, url),
                'note': _norm(row.get('note')),
            })
    disclaimer = _norm(data.get('disclaimer')) or (
        'هذه دراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا.'
    )
    raw_swot = data.get('swot') if isinstance(data.get('swot'), dict) else {}
    swot = {}
    aliases = {
        'strengths': ('strengths', 'swot_strengths', 'نقاط القوة'),
        'weaknesses': ('weaknesses', 'swot_weaknesses', 'نقاط الضعف'),
        'opportunities': ('opportunities', 'swot_opportunities', 'الفرص'),
        'threats': ('threats', 'swot_threats', 'التهديدات'),
    }
    for item in SWOT_SECTIONS:
        value = ''
        for key in aliases[item['key']]:
            value = _norm(raw_swot.get(key) or data.get(key))
            if value:
                break
        swot[item['key']] = value
    raw_one_block = (
        data.get('one_block_summary')
        or data.get('oneBlockSummary')
        or data.get('market_summary_block')
        or data.get('executive_summary')
    )
    one_block_summary = str(raw_one_block or '').strip()
    one_block_summary = one_block_summary.replace('\\r\\n', '\n').replace('\\n', '\n')
    one_block_summary = re.sub(r'[ \t]+', ' ', one_block_summary)
    one_block_summary = re.sub(r'\n{3,}', '\n\n', one_block_summary)
    if one_block_summary and not is_market_summary_paragraph(one_block_summary):
        fallback_paragraph = summary_prose(summary)
        if isinstance(raw_summary, str) and raw_summary.strip():
            fallback_paragraph = raw_summary.strip()
        one_block_summary = fallback_paragraph
    if not one_block_summary:
        one_block_summary = summary_prose(summary)
    one_block_summary = re.sub(r'\s+', ' ', one_block_summary).strip()
    return {
        'title': SUMMARY_TITLE,
        'summary': summary,
        'swot': swot,
        'decision': decision,
        'sources': sources,
        'disclaimer': disclaimer,
        'one_block_summary': one_block_summary,
    }


def _number_in_text(value):
    """First number inside a possibly unit-suffixed string («3.5 كم» → 3.5)."""
    text = str(value or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    match = re.search(r'\d+(?:[.,]\d+)?', text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(',', '.'))
    except ValueError:
        return None


def flag_out_of_radius(competitors, resolved_km):
    """Mark AI rows whose self-declared distance escapes the chosen radius.

    The model declares each row's distance; when it places a competitor beyond
    the bound the row stays (the user may still want it) but carries an
    ``out_of_radius`` flag and a conflict warning that surfaces in the UI.
    A 25% slack absorbs the model's approximate distance estimates.
    """
    try:
        limit = float(resolved_km)
    except (TypeError, ValueError):
        limit = 0
    if not limit or limit <= 0:
        return 0
    flagged = 0
    for row in competitors or []:
        if not isinstance(row, dict):
            continue
        if _norm(row.get('row_source')) != 'ai':
            continue
        distance = _number_in_text(row.get('distance_km'))
        if distance is None or distance <= limit * 1.25:
            continue
        warnings = list(row.get('conflict_warnings') or [])
        signature = ('distance_km', str(distance))
        if not any(isinstance(item, dict) and (item.get('field'), str(item.get('incoming'))) == signature
                   for item in warnings):
            warnings.append({
                'field': 'distance_km',
                'existing': f'نطاق {limit:g} كم',
                'incoming': f'{distance:g} كم',
                'source': 'خارج نطاق المنافسين',
                'source_url': '',
            })
        row['conflict_warnings'] = warnings
        row['out_of_radius'] = True
        flagged += 1
    return flagged


def flag_out_of_period_sources(sources, bounds):
    """Mark source rows whose data_date escapes the binding period window.

    ``data_date`` arrives as free text («2025», «الربع الأول 2025»,
    «2025-03»); the honest granularity is the year, so a row is flagged only
    when a stated year clearly falls outside the window.
    """
    if not isinstance(bounds, dict) or not bounds:
        return 0
    start_year = int(str(bounds.get('from') or '0000')[:4] or 0)
    end_year = int(str(bounds.get('to') or '9999')[:4] or 9999)
    if not start_year and end_year == 9999:
        return 0
    flagged = 0
    for row in sources or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get('data_date') or '').translate(
            str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        years = [int(item) for item in re.findall(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)', text)]
        if not years:
            continue
        if any(year < start_year or year > end_year for year in years):
            row['outside_data_period'] = True
            note = _norm(row.get('note'))
            marker = 'خارج فترة البيانات المحددة'
            if marker not in note:
                row['note'] = f'{note} — {marker}' if note else marker
            flagged += 1
    return flagged


def flag_unverified_competitor_sources(row):
    """Mark AI-written links from a search-less answer without deleting them.

    When the response reports zero executed searches and no citations, every
    ``source_url`` the model wrote is memory rather than retrieved evidence.
    The links stay on the row — the owner reviews them and decides to keep or
    reject — while ``sources_unverified`` makes sure they are never passed off
    as sourced results.
    """
    if isinstance(row, dict):
        row['sources_unverified'] = True
    return row


def extract_city_district(address_components, formatted_address=''):
    """Pull Arabic city / district names from Google address components."""
    components = address_components if isinstance(address_components, list) else []
    city = ''
    district = ''
    city_types = {'locality', 'postal_town', 'administrative_area_level_2'}
    district_types = {'sublocality', 'sublocality_level_1', 'neighborhood', 'political'}
    for component in components:
        types = set(component.get('types') or [])
        name = _norm(component.get('long_name') or component.get('short_name'))
        if not name:
            continue
        if not city and types & city_types:
            city = name
        if not district and types & district_types and 'locality' not in types:
            district = name
    if not city:
        for component in components:
            types = set(component.get('types') or [])
            if 'administrative_area_level_1' in types:
                city = _norm(component.get('long_name'))
                break
    if not district:
        formatted = _norm(formatted_address)
        if formatted:
            parts = [part.strip() for part in formatted.split(',') if part.strip()]
            if len(parts) >= 2 and not district:
                district = parts[0]
            if not city and len(parts) >= 2:
                city = parts[-2] if len(parts) > 2 else parts[-1]
    return {'city': city, 'district': district}
