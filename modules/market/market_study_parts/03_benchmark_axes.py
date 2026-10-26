

# ---------------------------------------------------------------------------
# Benchmark axes — a mixed-use project's revenue components each need their own
# COMPETITOR_MIN_DIRECT direct competitors. project_competitor_axes derives the
# axes from the payload (components table, then subtypes, then main types), and
# competitor_row_axis_keys attributes each competitor row to the axes it
# benchmarks so the expansion passes can count per axis instead of per table.
# ---------------------------------------------------------------------------


def _split_multi_values(value):
    """Split a joined multi-select value ('، '-joined, JSON list, or list)."""
    if isinstance(value, (list, tuple, set)):
        return [_norm(item) for item in value if _norm(item)]
    text = _norm(value)
    if not text:
        return []
    if text.startswith('['):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [_norm(item) for item in parsed if _norm(item)]
    return [part.strip() for part in re.split(r'[,،\n;|]', text) if part.strip()]


def _iter_payload_components(payload):
    """The structured components list the frontend sends ('components')."""
    components = (payload or {}).get('components')
    if isinstance(components, str):
        try:
            components = json.loads(components)
        except Exception:
            components = None
    if not isinstance(components, list):
        return []
    return [item for item in components if isinstance(item, dict)]


_COMPARISON_TYPE_ALIASES = {
    'hotel': {'hotel', 'hospitality', 'فندقي', 'فندق'},
    'residential': {'residential', 'سكني'},
    'commercial': {'commercial', 'تجاري'},
}


def normalize_comparison_types(value):
    """Return only the explicit hotel/residential/commercial comparison picks."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = []
    if not isinstance(value, list):
        return []
    normalized = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        raw_type = _fold_choice(item.get('type') or item.get('kind') or item.get('category'))
        kind = next((key for key, aliases in _COMPARISON_TYPE_ALIASES.items()
                     if raw_type in {_fold_choice(alias) for alias in aliases}), '')
        if not kind:
            continue
        raw_operation = (item.get('operation') or item.get('operations')
                         or item.get('operationType'))
        raw_stars = item.get('stars') or item.get('hotelStars') or item.get('hotel_stars')
        if kind == 'hotel':
            for raw_star in _split_multi_values(raw_stars):
                try:
                    stars = int(str(raw_star).translate(
                        str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).strip())
                except (TypeError, ValueError):
                    continue
                if stars < 1 or stars > 5:
                    continue
                key = f'hotel:{stars}'
                if key in seen:
                    continue
                seen.add(key)
                normalized.append({
                    'key': key, 'type': kind, 'base': kind,
                    'operation': 'hotel_operation', 'stars': stars,
                    'label': f'فندقي - {stars} نجوم',
                    'label_en': f'{stars}-star hotel',
                    'search': f'فنادق مصنفة {stars} نجوم',
                    'names': [], 'explicit': True,
                })
        else:
            for raw_choice in _split_multi_values(raw_operation):
                operation = _fold_choice(raw_choice)
                if operation in {'sale', 'بيع', 'for sale'}:
                    operation = 'sale'
                    operation_ar, operation_en = 'بيع', 'for sale'
                elif operation in {'rent', 'rental', 'إيجار', 'تأجير', 'for rent'}:
                    operation = 'rent'
                    operation_ar, operation_en = 'إيجار', 'for rent'
                else:
                    continue
                key = f'{kind}:{operation}'
                if key in seen:
                    continue
                seen.add(key)
                type_ar, type_en = (('سكني', 'residential') if kind == 'residential'
                                    else ('تجاري', 'commercial'))
                label, label_en = f'{type_ar} - {operation_ar}', f'{type_en} {operation_en}'
                search = (f'مشاريع {type_ar} {operation_ar} مسماة'
                          if kind == 'residential' else
                          f'مشاريع تجارية {operation_ar} مسماة')
                normalized.append({
                    'key': key, 'type': kind, 'base': kind, 'operation': operation,
                    'stars': '', 'label': label, 'label_en': label_en,
                    'search': search, 'names': [], 'explicit': True,
                })
    return normalized


def project_competitor_axes(payload):
    """Ordered benchmark axes for the competitor table.

    One axis per distinct revenue-bearing component use; falls back to the
    project subtypes (mixed-use selections), then the main type(s), then a
    single 'general' axis — which reproduces the old whole-table minimum.
    """
    payload = payload or {}
    if 'comparisonTypes' in payload or 'comparison_types' in payload:
        selected = (payload.get('comparisonTypes')
                    if 'comparisonTypes' in payload else payload.get('comparison_types'))
        normalized = normalize_comparison_types(selected)
        if normalized:
            return normalized
        # A legacy request with no explicit comparison picks derives its axes
        # from the project type/components below, as it did before the field
        # existed instead of failing with «لا توجد اختيارات مقارنة صالحة».
    axes = []

    def add(key, base=None, label='', name=''):
        definition = COMPONENT_USE_AXES.get(base or key)
        if not definition:
            return
        existing = next((axis for axis in axes if axis['key'] == key), None)
        if existing:
            if name and name not in existing['names']:
                existing['names'].append(name)
            return
        axes.append({
            'key': key,
            'base': base or key,
            'label': label or definition['label'],
            'label_en': label if key.startswith('other:') else definition['label_en'],
            'search': definition['search'],
            'names': [name] if name else [],
        })

    for component in _iter_payload_components(payload):
        model = _fold_choice(
            component.get('investmentModel') or component.get('investment_model'))
        if model == 'nonrevenue':
            continue
        use = _norm(component.get('useType') or component.get('use_type')).lower()
        if not use or use in COMPONENT_NON_COMPETING_USES:
            continue
        name = _norm(component.get('name'))
        if use in COMPONENT_USE_AXES:
            add(use, name=name)
        else:
            add(f'other:{name or "أخرى"}', base='other', label=name or 'أخرى', name=name)
    if not axes:
        subtypes = _split_multi_values(
            payload.get('projectSubtype') or payload.get('project_subtype'))
        subtypes += _split_multi_values(
            payload.get('projectComponents') or payload.get('project_components')
            or payload.get('project_mixed_components'))
        for subtype in subtypes:
            key = MIXED_COMPONENT_AXIS_KEYS.get(subtype)
            if key:
                add(key, name=subtype)
    if not axes:
        for main in _split_multi_values(
                payload.get('projectType') or payload.get('project_type')):
            key = PROJECT_MAIN_AXIS_KEYS.get(main)
            if key:
                add(key, name=main)
    if not axes:
        add('general')
    return axes


def benchmark_axis_label(axis, offer_lang='ar'):
    """The label the model must write in benchmarks for this axis."""
    if offer_lang == 'en':
        return axis.get('label_en') or axis.get('label') or ''
    return axis.get('label') or ''


def _axis_alias_set(axis):
    """Folded benchmark values that attribute a row to this axis."""
    aliases = {
        _fold_choice(axis.get('label')),
        _fold_choice(axis.get('label_en')),
    }
    aliases.update(_fold_choice(name) for name in axis.get('names') or [])
    if axis.get('base') != 'other':
        aliases.update(
            _fold_choice(item)
            for item in BENCHMARK_AXIS_ALIASES.get(axis.get('base'), ()))
    return {alias for alias in aliases if alias}


def competitor_row_axis_keys(row, axes, offer_lang='ar'):
    """The axes a competitor row benchmarks.

    Priority: the row's benchmarks field (the model's explicit tag, which may
    legitimately cover several axes for a mixed-use competitor), then a
    project_type fallback for untagged/legacy rows, then a single 'general'
    axis counts every named row — the old whole-table semantics.
    """
    axis_keys = {axis['key'] for axis in axes}
    if axis_keys == {'general'}:
        return {'general'}
    if not isinstance(row, dict):
        return set()
    if any(axis.get('explicit') for axis in axes):
        return {axis['key'] for axis in axes
                if competitor_matches_comparison_axis(row, axis)}
    keys = set()
    raw = (row.get('benchmarks') or row.get('benchmark_axes')
           or row.get('measured_against') or row.get('serves_components')
           or row.get('يُقاس على') or row.get('يقاس على'))
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    alias_sets = {axis['key']: _axis_alias_set(axis) for axis in axes}
    for item in items:
        for part in _split_multi_values(item):
            folded = _fold_choice(part)
            if not folded:
                continue
            for axis in axes:
                if folded in alias_sets[axis['key']]:
                    keys.add(axis['key'])
    if not keys:
        fallback = BENCHMARK_PROJECT_TYPE_FALLBACK.get(
            _fold_choice(row.get('project_type')))
        if fallback == '*':
            keys = set(axis_keys)
        elif fallback:
            keys = {
                axis['key'] for axis in axes
                if axis['key'] in fallback
                or (axis.get('base') == 'other' and 'other' in fallback)}
    return keys


def competitor_matches_comparison_axis(row, axis):
    """Match an AI row to exactly one selected type, operation, and hotel class."""
    if not isinstance(row, dict) or not isinstance(axis, dict):
        return False
    project_type = _fold_choice(row.get('project_type') or row.get('projectType'))
    if axis.get('type') == 'hotel':
        if not any(token in project_type for token in ('فندقي', 'فندق', 'hotel', 'hospitality')):
            return False
        raw_stars = (row.get('hotel_stars') or row.get('hotelStars')
                     or row.get('star_rating') or row.get('stars'))
        if not raw_stars:
            text = _fold_choice(' '.join(str(row.get(key) or '')
                                         for key in ('name', 'notes', 'classification')))
            match = re.search(r'(?<!\d)([1-5])\s*(?:نجوم|star)', text)
            raw_stars = match.group(1) if match else ''
        star_text = str(raw_stars or '').translate(
            str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
        star_match = re.search(r'(?<!\d)([1-5])(?!\d)', star_text)
        try:
            actual_stars = int(star_match.group(1)) if star_match else int(star_text.strip())
        except (TypeError, ValueError):
            # A hotel inside the client's scope whose class never reached the
            # page is still a competitor of that scope (owner decision
            # 2026-10-27); it is kept with an empty class, never guessed.
            return True
        axis_stars = str(axis.get('stars') or '').strip()
        if not axis_stars:
            return True
        try:
            return actual_stars == int(float(axis_stars))
        except (TypeError, ValueError):
            return True
    wanted_type = axis.get('type')
    if wanted_type == 'residential':
        type_match = any(token in project_type for token in ('سكني', 'residential', 'housing'))
    elif wanted_type == 'commercial':
        type_match = any(token in project_type for token in (
            'تجاري', 'commercial', 'retail', 'office', 'مكاتب', 'محلات'))
    else:
        return False
    if not type_match:
        return False
    operation = _fold_choice(row.get('operation_type') or row.get('operationType'))
    if axis.get('operation') == 'sale':
        return any(token in operation for token in ('بيع', 'sale'))
    if axis.get('operation') == 'rent':
        return any(token in operation for token in ('ايجار', 'تاجير', 'rent', 'rental'))
    return False


def _competitor_distance_from_coordinates(row, scope):
    """Compute straight-line distance when the project and row coordinates exist."""
    scope = scope if isinstance(scope, dict) else {}
    def first_value(*candidates):
        return next((value for value in candidates
                     if value is not None and str(value).strip()), None)

    values = (
        first_value(row.get('lat'), row.get('latitude')),
        first_value(row.get('lng'), row.get('lon'), row.get('longitude')),
        first_value(scope.get('origin_lat'), scope.get('originLat')),
        first_value(scope.get('origin_lng'), scope.get('originLng')),
    )
    try:
        lat, lng, origin_lat, origin_lng = (float(str(value).strip().replace(',', '.'))
                                           for value in values)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -90 <= origin_lat <= 90
            and -180 <= lng <= 180 and -180 <= origin_lng <= 180):
        return None
    import math
    lat1, lat2 = math.radians(origin_lat), math.radians(lat)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(lng - origin_lng)
    haversine = (math.sin(delta_lat / 2) ** 2
                 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2)
    return round(6371.0 * 2 * math.asin(math.sqrt(min(1.0, haversine))), 2)


def competitor_distance_km(row, scope):
    """Straight-line distance in km when the row and the site both carry coordinates."""
    return _competitor_distance_from_coordinates(row, scope)


def competitor_matches_location_scope(row, scope, city='', district=''):
    """Enforce the selected distance, city or exact neighborhood."""
    if not isinstance(row, dict):
        return False
    scope = scope if isinstance(scope, dict) else {}
    mode = scope.get('mode') if scope.get('mode') in ('district', 'city', 'distance') else 'district'
    if mode == 'distance':
        distance = _competitor_distance_from_coordinates(row, scope)
        if distance is None:
            distance = _number_in_text(row.get('distance_km') or row.get('distanceKm'))
        radius = _number_in_text(
            scope.get('radius_km') or scope.get('radiusKm') or scope.get('radius'))
        if radius is None:
            radius = float(DEFAULT_COMPETITOR_RADIUS_KM)
        return distance is not None and distance <= radius
    row_city = _fold_choice(row.get('city') or row.get('location_city'))
    if not row_city or row_city != _fold_choice(city):
        return False
    if mode == 'city':
        return True
    row_district = _fold_choice(row.get('district') or row.get('neighborhood'))
    if not row_district:
        return False
    # A district scope may cover several neighborhoods the client picked; any
    # one of them is inside the scope and nothing outside it is.
    wanted = [district]
    if isinstance(scope.get('districts'), (list, tuple)):
        wanted.extend(scope.get('districts') or [])
    wanted_keys = {_fold_choice(item) for item in wanted if _fold_choice(item)}
    return row_district in wanted_keys


def filter_and_cap_competitors(rows, axes, limit_per_axis=5, offer_lang='ar',
                               scope=None, city='', district=''):
    """Drop rows outside explicit selections and cap each selected group."""
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    explicit = bool(axes) and any(axis.get('explicit') for axis in axes)
    if not explicit:
        # A distance scope is a promise to the client: rows outside the radius
        # never reach the table, with or without a comparison selection.
        scope = scope if isinstance(scope, dict) else {}
        if scope.get('mode') != 'distance':
            return rows
        return [row for row in rows
                if competitor_matches_location_scope(row, scope, city, district)]
    counts = {axis['key']: 0 for axis in axes}
    accepted = []
    seen_names = set()
    for row in rows or []:
        if not isinstance(row, dict) or not _norm(row.get('name')):
            continue
        if not competitor_matches_location_scope(row, scope, city, district):
            continue
        name_key = _fold_choice(row.get('name'))
        if not name_key or name_key in seen_names:
            continue
        matched = [axis for axis in axes
                   if competitor_matches_comparison_axis(row, axis)]
        available = [axis for axis in matched
                     if counts[axis['key']] < limit_per_axis]
        if not available:
            continue
        chosen = available[0]
        row = dict(row)
        row['benchmarks'] = [benchmark_axis_label(chosen, offer_lang)]
        row['comparison_type'] = chosen['type']
        row['comparison_operation'] = chosen['operation']
        # The class column belongs to the row's own page: an unknown class
        # stays empty instead of being relabelled with the selected one.
        row['hotel_stars'] = (str(row.get('hotel_stars') or '').strip()
                              if chosen['type'] == 'hotel' else '')
        counts[chosen['key']] += 1
        seen_names.add(name_key)
        accepted.append(row)
    return accepted
