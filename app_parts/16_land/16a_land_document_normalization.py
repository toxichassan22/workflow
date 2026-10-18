# Land document and survey coordinate normalization.

def _normalize_survey_coordinate_rows(raw_coordinates, parcel_id):
    if isinstance(raw_coordinates, dict):
        raw_coordinates = raw_coordinates.get('rows') or raw_coordinates.get('points') or []
    if not isinstance(raw_coordinates, list):
        return []
    regulation_rows = []
    for item in raw_coordinates:
        if not isinstance(item, dict):
            continue
        metadata = ' '.join(str(item.get(key) or '') for key in (
            'source', 'table', 'table_name', 'coordinates_table_name', 'point', 'point_number', 'notes', 'الجدول'
        )).casefold()
        if 'التنظيم' in metadata or 'regulation' in metadata:
            regulation_rows.append(item)
    if regulation_rows:
        raw_coordinates = regulation_rows
    normalized = []
    for item in raw_coordinates:
        if not isinstance(item, dict):
            continue
        row_parcel_id = _coordinate_value(item, {'parcel_id', 'parcelid', 'plot_number', 'رقم القطعة'}) or str(parcel_id)
        point = _coordinate_value(item, {'point', 'point_number', 'pointnumber', 'رقم النقطة', 'النقطة'})
        if 'التنظيم' in point or 'regulation' in point.casefold():
            point_match = re.search(r'[0-9\u0660-\u0669]+', point)
            if point_match:
                point = point_match.group(0)
        eastings = _coordinate_value(item, {
            'eastings', 'easting', 'easting_coordinate', 'الشرقيات', 'الشرقي', 'شرقيات'
        })
        northings = _coordinate_value(item, {
            'northings', 'northing', 'northing_coordinate', 'الشماليات', 'الشمالي', 'شماليات'
        })
        source = _coordinate_value(item, {'source', 'المصدر'}) or 'regulation_table'
        if row_parcel_id or point or eastings or northings:
            normalized.append({
                'parcel_id': row_parcel_id,
                'point': point,
                'eastings': eastings,
                'northings': northings,
                'source': source,
            })
    return normalized


_DIRECTION_ALIASES = {
    'n': 'north', 'north': 'north', 'شمال': 'north', 'الشمال': 'north',
    's': 'south', 'south': 'south', 'جنوب': 'south', 'الجنوب': 'south',
    'e': 'east', 'east': 'east', 'شرق': 'east', 'الشرق': 'east',
    'w': 'west', 'west': 'west', 'غرب': 'west', 'الغرب': 'west',
}

# The model uses several key names for a direction's setback; accept the common
# ones so the value reaches the editable table column instead of being dropped.
_DIRECTION_SETBACK_KEYS = (
    'setback', 'setback_m', 'setback_text', 'setback_value', 'setbacks',
    'setback_requirement', 'setback_meters', 'الارتداد', 'ارتداد', 'ارتدادات',
)


def _normalize_direction_map(value):
    if isinstance(value, dict):
        entries = []
        for key, item in value.items():
            if isinstance(item, dict):
                entry = dict(item)
            else:
                entry = {'notes': str(item)}
            entry['direction'] = key
            entries.append(entry)
    elif isinstance(value, list):
        entries = [item for item in value if isinstance(item, dict)]
    else:
        entries = []
    directions = {}
    for entry in entries:
        direction_key = str(entry.get('direction') or entry.get('key') or '').strip().casefold()
        direction = _DIRECTION_ALIASES.get(direction_key)
        if direction:
            clean = dict(entry)
            clean.pop('direction', None)
            clean.pop('key', None)
            if not str(clean.get('setback') or '').strip():
                for alias in _DIRECTION_SETBACK_KEYS:
                    alias_value = clean.get(alias)
                    if str(alias_value or '').strip():
                        clean['setback'] = str(alias_value).strip()
                        break
            directions[direction] = clean
    for direction in ('north', 'south', 'east', 'west'):
        directions.setdefault(direction, {})
    return directions


_DIRECTION_SETBACK_TEXT_WORDS = (
    ('north', r'(?:الجهة\s+)?(?:ال)?شمالي?(?:ة)?'),
    ('south', r'(?:الجهة\s+)?(?:ال)?جنوبي?(?:ة)?'),
    ('east', r'(?:الجهة\s+)?(?:ال)?شرقي?(?:ة)?'),
    ('west', r'(?:الجهة\s+)?(?:ال)?غربي?(?:ة)?'),
)


def _fill_direction_setbacks_from_text(parcel):
    """Copy compass-named setbacks out of the free-text ``setbacks`` value into
    the matching direction rows — only where the model left the cell empty.
    The number must follow the direction word directly, so a boundary length
    («الشمال بطول 20م») is never mistaken for a setback.
    """
    if not isinstance(parcel, dict):
        return
    directions = parcel.get('directions')
    if not isinstance(directions, dict):
        return
    text = str(parcel.get('setbacks') or parcel.get('setback_requirements') or '').strip()
    if not text:
        return
    for direction, word in _DIRECTION_SETBACK_TEXT_WORDS:
        entry = directions.get(direction)
        if not isinstance(entry, dict) or str(entry.get('setback') or '').strip():
            continue
        match = re.search(
            word + r'\s*[:=\-–—]?\s*([0-9٠-٩]+(?:[.,][0-9]+)?\s*(?:متر|م\.?))',
            text)
        if match:
            entry['setback'] = match.group(1).strip()


def _compose_setbacks_from_directions(directions):
    """Flatten per-direction setbacks into the summary text used by the legacy
    «الارتدادات» field, so the two never disagree."""
    if not isinstance(directions, dict):
        return ''
    parts = []
    for direction, label in (('north', 'شمال'), ('south', 'جنوب'), ('east', 'شرق'), ('west', 'غرب')):
        entry = directions.get(direction)
        value = str((entry or {}).get('setback') or '').strip()
        if value:
            parts.append(f'{label}: {value}')
    return ' | '.join(parts)


def _directions_have_content(directions):
    if not isinstance(directions, dict):
        return False
    return any(
        any(str(value.get(key) or '').strip() for key in (
            'regulation_text', 'street_name', 'street_width_m', 'boundary_length_m', 'uses', 'notes', 'setback'
        )) if isinstance(value, dict) else bool(str(value or '').strip())
        for value in directions.values()
    )


def _apply_regulation_digest_fields(resp_json, reg_digest):
    """Force-fill verified numeric regulation fields from the digest.

    When the digest matched a zone, its values are the source of truth for the
    numeric requirements — the model narrates them but may not override them.
    Fields absent from the digest (e.g. conflicting values) are left untouched
    so an unverified number is never force-written.
    """
    fields = reg_digest.get('fields') or {}
    if not fields:
        return
    if reg_digest.get('conflicts'):
        existing = resp_json.get('conflicts')
        merged = list(existing) if isinstance(existing, list) else []
        for conflict in reg_digest['conflicts']:
            if conflict not in merged:
                merged.append(conflict)
        resp_json['conflicts'] = merged
    targets = []
    parcels = resp_json.get('parcels')
    if isinstance(parcels, list):
        targets.extend(p for p in parcels if isinstance(p, dict))
    if not targets:
        targets.append(resp_json)
    for target in targets:
        for key, value in fields.items():
            if key == 'allowed_uses':
                continue
            if value not in (None, '', []):
                target[key] = value


def _normalize_land_document_result(resp_json, text_content='', project_type=''):
    """Normalize multi-parcel document output while keeping legacy flat fields compatible."""
    if not isinstance(resp_json, dict):
        resp_json = {}
    raw_parcels = resp_json.get('parcels')
    if not isinstance(raw_parcels, list) or not raw_parcels:
        legacy = normalize_croquis_fields(resp_json, text_content)
        directions = _normalize_direction_map(
            legacy.get('directions') or resp_json.get('directions') or resp_json.get('directions_table')
        )
        survey_coordinates = _normalize_survey_coordinate_rows(
            _coordinate_rows_from_payload(resp_json), 'P-1'
        )
        parcel = {
            'parcel_id': 'P-1',
            'plot_number': legacy.get('plot_number_croquis', ''),
            'plan_number': legacy.get('plan_number', ''),
            'subdivision_number': legacy.get('subdivision_number', ''),
            'deed_number': legacy.get('deed_number', ''),
            'deed_date': legacy.get('deed_date', ''),
            'area_sqm': legacy.get('croquis_land_area'),
            'approved_financial_area_sqm': None,
            'facades_count': legacy.get('facades_count'),
            'facades_directions': legacy.get('facades_directions', ''),
            'main_facade_direction': legacy.get('main_facade_direction', ''),
            'directions': directions,
            'north_direction': legacy.get('north_direction', ''),
            'building_ratio_coverage': legacy.get('building_ratio_coverage', ''),
            'setbacks': legacy.get('setbacks', ''),
            'building_ratio': legacy.get('building_ratio', legacy.get('building_ratio_setbacks', '')),
            'coverage_ratio': legacy.get('coverage_ratio', ''),
            'floor_area_ratio': legacy.get('floor_area_ratio', ''),
            'table_floors': legacy.get('table_floors', ''),
            'building_ratio_setbacks': legacy.get('building_ratio_setbacks', ''),
            'max_floors_height': legacy.get('max_floors_height', ''),
            'allowed_uses': legacy.get('allowed_uses', legacy.get('allowed_uses_restrictions', '')),
            'regulatory_constraints': legacy.get('regulatory_constraints', ''),
            'land_use_status': legacy.get('land_use_status', ''),
            'allowed_uses_restrictions': legacy.get('allowed_uses_restrictions', ''),
                'coordinates': {'lat': None, 'lng': None, 'source': '', 'confidence': ''},
            'survey_coordinates': survey_coordinates,
            'confidence': {},
            'sources': [],
            'summary': legacy.get('land_and_building_summary', ''),
        }
        _normalize_parcel_scalar_fields(parcel, text_content)
        result = dict(legacy)
        result['parcels'] = [parcel]
        result['survey_coordinates'] = survey_coordinates
        result['source_priority'] = ['regulation_table', 'official_regulation', 'croquis', 'building_license']
        result['conflicts'] = resp_json.get('conflicts') if isinstance(resp_json.get('conflicts'), list) else []
        result['document_summary'] = result.get('land_and_building_summary', '')
        strip_regulation_references_from_payload(result)
        return apply_entered_land_use_status(result, project_type)

    normalized_parcels = []
    for index, raw in enumerate(raw_parcels):
        if not isinstance(raw, dict):
            continue
        directions = _normalize_direction_map(
            raw.get('directions') or raw.get('directions_table') or raw.get('regulation_directions')
        )
        if index == 0 and not _directions_have_content(directions):
            directions = _normalize_direction_map(
                resp_json.get('directions') or resp_json.get('directions_table')
            )
        parcel = dict(raw)
        parcel['parcel_id'] = str(raw.get('parcel_id') or raw.get('parcelId') or f'P-{index + 1}')
        parcel['survey_coordinates'] = _normalize_survey_coordinate_rows(
            _coordinate_rows_from_payload(raw), parcel['parcel_id']
        )
        parcel['directions'] = directions
        coords = raw.get('coordinates') if isinstance(raw.get('coordinates'), dict) else {}
        parcel['coordinates'] = {
            'lat': coords.get('lat'), 'lng': coords.get('lng'),
            'source': coords.get('source', ''), 'confidence': coords.get('confidence', '')
        }
        parcel['sources'] = raw.get('sources') if isinstance(raw.get('sources'), list) else []
        parcel['confidence'] = raw.get('confidence') if isinstance(raw.get('confidence'), dict) else {}
        _normalize_parcel_scalar_fields(parcel, text_content)
        normalized_parcels.append(parcel)

    if not normalized_parcels:
        return _normalize_land_document_result({}, text_content)
    result = dict(resp_json)
    result.pop('approved_floor_count', None)
    result.pop('approved_floors', None)
    result.pop('approved_coverage_ratio', None)
    result.pop('approved_floor_area_ratio', None)
    result.pop('approved_typical_floor_coverage', None)
    result['parcels'] = normalized_parcels
    aggregate_coordinates = [row for parcel in normalized_parcels for row in parcel.get('survey_coordinates', [])]
    top_regulation_rows = _regulation_coordinate_rows_from_payload(resp_json)
    top_coordinates = _normalize_survey_coordinate_rows(
        top_regulation_rows or _coordinate_rows_from_payload(resp_json), normalized_parcels[0]['parcel_id']
    )
    if top_regulation_rows:
        aggregate_coordinates = top_coordinates
        normalized_parcels[0]['survey_coordinates'] = top_coordinates
    elif not aggregate_coordinates:
        aggregate_coordinates = top_coordinates
    result['survey_coordinates'] = aggregate_coordinates
    result['source_priority'] = ['regulation_table', 'official_regulation', 'croquis', 'building_license']
    result['conflicts'] = resp_json.get('conflicts') if isinstance(resp_json.get('conflicts'), list) else []
    # One canonical narrative: keep document_summary as a mirror for older stored drafts.
    summary = str(resp_json.get('land_and_building_summary') or resp_json.get('document_summary') or '').strip()
    if not summary:
        summary = str(normalized_parcels[0].get('summary') or '').strip()
    result['land_and_building_summary'] = summary
    result['document_summary'] = summary
    first = normalized_parcels[0]
    legacy_map = {
        'plot_number_croquis': first.get('plot_number', ''),
        'plan_number': first.get('plan_number', ''),
        'subdivision_number': first.get('subdivision_number', ''),
        'deed_number': first.get('deed_number', ''),
        'deed_date': first.get('deed_date', ''),
        'croquis_land_area': first.get('area_sqm'),
        'facades_count': first.get('facades_count'),
        'facades_directions': first.get('facades_directions', ''),
        'north_direction': first.get('north_direction', ''),
        'building_ratio_coverage': first.get('building_ratio_coverage') or land_rule_text(first),
        'setbacks': first.get('setbacks', ''),
        'building_ratio_setbacks': first.get('building_ratio_setbacks') or land_rule_text(first, include_setbacks=True),
        'max_floors_height': first.get('max_floors_height', ''),
        'allowed_uses': first.get('allowed_uses', ''),
        'regulatory_constraints': first.get('regulatory_constraints', ''),
        'land_use_status': first.get('land_use_status', ''),
        'allowed_uses_restrictions': first.get('allowed_uses_restrictions', ''),
    }
    for key, value in legacy_map.items():
        if value not in (None, ''):
            result.setdefault(key, value)
    strip_regulation_references_from_payload(result)
    return apply_entered_land_use_status(result, project_type)


def _build_land_extraction_diagnostics(result, document_processing=None):
    parcels = result.get('parcels') if isinstance(result, dict) else []
    parcels = parcels if isinstance(parcels, list) else []
    coordinate_rows = result.get('survey_coordinates') if isinstance(result, dict) else []
    if not isinstance(coordinate_rows, list):
        coordinate_rows = []
    first_parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    if not coordinate_rows:
        coordinate_rows = first_parcel.get('survey_coordinates') if isinstance(first_parcel.get('survey_coordinates'), list) else []
    directions = first_parcel.get('directions') if isinstance(first_parcel.get('directions'), dict) else {}
    direction_values = 0
    direction_lengths = 0
    for direction in ('north', 'south', 'east', 'west'):
        value = directions.get(direction)
        if isinstance(value, dict):
            has_value = any(str(value.get(key) or '').strip() for key in (
                'regulation_text', 'street_name', 'street_width_m', 'boundary_length_m', 'uses', 'notes'
            ))
            has_length = bool(str(value.get('boundary_length_m') or '').strip())
        else:
            has_value = bool(str(value or '').strip())
            has_length = False
        direction_values += int(has_value)
        direction_lengths += int(has_length)
    complete_coordinates = sum(
        bool(str(row.get('eastings') or '').strip() and str(row.get('northings') or '').strip())
        for row in coordinate_rows if isinstance(row, dict)
    )
    conflicts = result.get('conflicts') if isinstance(result, dict) else []
    conflicts = conflicts if isinstance(conflicts, list) else []
    missing_tables = []
    if not coordinate_rows:
        missing_tables.append('إحداثيات التنظيم')
    if direction_values < 4:
        missing_tables.append('بموجب التنظيم')
    if not missing_tables:
        status = 'complete'
    elif coordinate_rows or direction_values:
        status = 'partial'
    else:
        status = 'empty'
    return {
        'status': status,
        'coordinates_rows': len(coordinate_rows),
        'coordinates_complete_rows': complete_coordinates,
        'directions_rows': 4,
        'directions_with_values': direction_values,
        'directions_with_lengths': direction_lengths,
        'missing_tables': missing_tables,
        'conflict_count': len(conflicts),
        'coordinates_table_name': str(first_parcel.get('coordinates_table_name') or ''),
        'document_processing': document_processing if isinstance(document_processing, list) else [],
    }


LAND_ANALYSIS_SITE_CONTEXT_KEYS = (
    'location_address', 'location_detail', 'location_lat', 'location_lng', 'location_polygon',
    'city', 'district', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
    'city_landmarks', 'catchment_areas', 'population_density', 'population_density_source',
    'zoning_code', 'land_use', 'project_language',
)


def build_land_analysis_site_context(data, tenant_id, lat, lng):
    source = data.get('siteContext') if isinstance(data.get('siteContext'), dict) else {}
    context = {}
    for key in LAND_ANALYSIS_SITE_CONTEXT_KEYS:
        value = source.get(key)
        if value in (None, '', [], {}):
            value = data.get(key)
        if value not in (None, '', [], {}):
            context[key] = value
    context['location_address'] = data.get('locationAddress') or data.get('location_address') or context.get('location_address') or ''
    context['location_lat'] = lat
    context['location_lng'] = lng
    warnings = []
    needs_enrichment = any(context.get(key) in (None, '', [], {}) for key in (
        'location_detail', 'main_roads', 'nearby_landmarks', 'city_landmarks'))
    if data.get('includeMapContext') is True and needs_enrichment:
        try:
            # The croquis job runs on a worker thread, so the scope must be
            # opened here — a request-thread scope would never reach it, and
            # the Google calls below would record as unbillable NULL-tenant rows.
            site_maps_ctx = maps_service.maps_usage_ctx('site', tenant_id=tenant_id, data=data)
            with maps_service.maps_usage_scope(site_maps_ctx):
                enriched, nearby_items, *_rest, diagnostics = _collect_site_fields(context, tenant_id, lat, lng)
            for key, value in (enriched or {}).items():
                if value not in (None, '', [], {}) and context.get(key) in (None, '', [], {}):
                    context[key] = value
            if nearby_items and not context.get('nearby_landmarks_data'):
                context['nearby_landmarks_data'] = nearby_items
            warnings.extend(value for value in (
                (diagnostics or {}).get('nearby_landmarks_error'),
                (diagnostics or {}).get('nearby_landmarks_warning'),
                (diagnostics or {}).get('city_landmarks_error'),
                (diagnostics or {}).get('city_landmarks_warning'),
            ) if value)
        except Exception as error:
            warnings.append('تعذر استكمال بعض بيانات الموقع والخرائط: ' + str(error))
    return context, warnings


# claude-haiku-5.5 emits up to 128K output tokens — the cap tracks the
# model's ceiling so a full-axes summary is never truncated mid-JSON.
MARKET_STUDY_MAX_TOKENS = int(os.environ.get('MARKET_STUDY_MAX_TOKENS', '128000'))
MARKET_STUDY_MODEL = os.environ.get('MARKET_STUDY_MODEL') or GEMINI_TEXT_MODEL
_MARKET_JOB_LOCK = threading.Lock()
