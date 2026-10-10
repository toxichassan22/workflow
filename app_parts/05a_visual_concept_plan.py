


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Deterministic visual-concept plan machinery: derive the site facts,
# regulation facts and plan context from the project data, build the
# kind-specific drawing prompts and distribution spec, then normalize and
# verify the model's verification/distribution payloads before the
# plan-workflow endpoints consume them.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _visual_concept_plan_kind(slot_id, value=''):
    candidate = _visual_concept_text(value, 40).lower()
    if candidate in VISUAL_CONCEPT_PLAN_KIND_BY_ID.values():
        return candidate
    return VISUAL_CONCEPT_PLAN_KIND_BY_ID.get(str(slot_id or '').strip().lower(), '')


def _visual_concept_plan_boundary_points(value):
    parsed = value
    if isinstance(value, str):
        parsed = _visual_concept_parse_json(value, value)
    if isinstance(parsed, dict):
        parsed = parsed.get('points') or parsed.get('survey_coordinates') or parsed.get('coordinates') or []
    if not isinstance(parsed, list):
        return []
    points = []
    for index, item in enumerate(parsed):
        if isinstance(item, dict):
            east = item.get('eastings') or item.get('easting') or item.get('x')
            north = item.get('northings') or item.get('northing') or item.get('y')
            point = item.get('point') or item.get('point_number') or str(index + 1)
            parcel_id = item.get('parcel_id') or item.get('parcelId') or ''
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            east, north = item[0], item[1]
            point, parcel_id = str(index + 1), ''
        else:
            continue
        east_number = _visual_concept_number(east)
        north_number = _visual_concept_number(north)
        if east_number is None or north_number is None:
            continue
        points.append({
            'parcel_id': _visual_concept_text(parcel_id, 80),
            'point': _visual_concept_text(point, 40) or str(index + 1),
            'eastings': east_number,
            'northings': north_number,
        })
        if len(points) >= 60:
            break
    return points if len(points) >= 3 else []


_VISUAL_PLAN_FACT_LABELS = {
    'plot_number_croquis': 'رقم القطعة', 'plan_number': 'رقم المخطط',
    'croquis_land_area': 'مساحة الأرض', 'boundary_lengths': 'أطوال الحدود',
    'surrounding_streets': 'الشوارع المحيطة', 'north_direction': 'اتجاه الشمال',
    'building_ratio': 'نسبة البناء', 'coverage_ratio': 'نسبة التغطية',
    'building_ratio_coverage': 'نسبة البناء/التغطية', 'building_ratio_setbacks': 'الارتدادات',
    'setbacks': 'الارتدادات', 'floor_area_ratio': 'معامل كتلة البناء',
    'table_floors': 'عدد الأدوار', 'max_floors_height': 'أقصى ارتفاع/أدوار',
    'allowed_uses': 'الاستخدامات المسموحة', 'regulatory_constraints': 'الاشتراطات والقيود',
    'parking_requirements': 'متطلبات المواقف', 'entrances_exits_requirements': 'متطلبات المداخل والمخارج',
    'land_use': 'استخدام الأرض', 'zoning_code': 'كود التنظيم',
    'document_summary': 'ملخص المستند', 'summary': 'الملخص',
    'allowed_uses_restrictions': 'قيود الاستخدامات', 'directions': 'الاتجاهات',
}


def _visual_concept_plan_site_facts(source, analysis=None, parcel=None):
    """Site facts used to select the applicable regulation block. They are an
    input to rule lookup — never a verification target — so reading them from
    projectData is safe."""
    source = source if isinstance(source, dict) else {}
    analysis = analysis if isinstance(analysis, dict) else {}
    parcel = parcel if isinstance(parcel, dict) else {}

    def pick(*keys):
        for key in keys:
            for holder in (parcel, analysis, source):
                value = holder.get(key)
                if value not in (None, ''):
                    return value
        return ''

    widths = []
    directions = (parcel.get('directions') or analysis.get('directions')
                  or source.get('directions') or source.get('directions_table'))
    entries = directions.values() if isinstance(directions, dict) else (
        directions if isinstance(directions, list) else [])
    for entry in entries:
        if isinstance(entry, dict):
            width = _visual_concept_number(entry.get('street_width_m') or entry.get('street_width'))
            if width:
                widths.append(width)
    return {
        'zoning_code': pick('zoning_code', 'planning_code', 'zone_code'),
        'area_sqm': pick('croquis_land_area', 'area_sqm', 'land_area'),
        'street_width_m': max(widths) if widths else pick('street_width_m', 'main_street_width'),
        'building_type': pick('building_type', 'project_type'),
        'land_use': pick('land_use', 'allowed_uses'),
        'city': pick('city'),
        'project_type': pick('project_type'),
    }


def _visual_concept_plan_regulation_facts(project_data):
    """Documented regulatory facts for verification: the verified rules digest
    (rules/*.json, built from the municipal اشتراطات) supplies authoritative
    values first, then land-document analysis fills what the digest does not
    cover. ProjectData is never a source — the project cannot verify itself."""
    source = project_data if isinstance(project_data, dict) else {}
    analysis = source.get('land_documents_analysis')
    if isinstance(analysis, str):
        analysis = _visual_concept_parse_json(analysis, {})
    analysis = analysis if isinstance(analysis, dict) else {}
    parcels = analysis.get('parcels') if isinstance(analysis.get('parcels'), list) else []
    parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    keys = (
        'plot_number_croquis', 'plan_number', 'croquis_land_area', 'boundary_lengths',
        'surrounding_streets', 'north_direction', 'building_ratio', 'coverage_ratio',
        'building_ratio_coverage', 'building_ratio_setbacks', 'setbacks', 'floor_area_ratio',
        'table_floors', 'max_floors_height', 'allowed_uses', 'regulatory_constraints',
        'parking_requirements', 'entrances_exits_requirements', 'land_use', 'zoning_code',
        'document_summary', 'summary', 'allowed_uses_restrictions', 'directions',
    )
    facts = {}
    review_points = []
    sources = []

    digest = {}
    if REGULATION_DIGEST_ENABLED:
        facts_input = _visual_concept_plan_site_facts(source, analysis, parcel)
        # The verified digest covers Jeddah only — a declared different city
        # must not borrow its values.
        if city_regulations.is_local_city(
                city_regulations.resolve_site_city(facts_input.get('city'))[0]):
            try:
                digest = regulation_digest.build_regulation_digest(facts_input)
            except Exception:
                digest = {}
    if digest.get('matched'):
        zone_label = _visual_concept_plan_sanitize_text(digest.get('zone_key'))
        if zone_label:
            facts['regulatory_zone'] = zone_label
            sources.append(f'القواعد الموثقة للمنطقة «{zone_label}»')
        if digest.get('text'):
            facts['zone_rules'] = _visual_concept_plan_sanitize_text(
                _visual_concept_text(digest['text'], 3000))
        for key, value in (digest.get('fields') or {}).items():
            if value not in (None, '', []):
                facts[key] = _visual_concept_plan_sanitize_text(_visual_concept_text(value, 1800))
    for note in digest.get('notes') or []:
        text = _visual_concept_plan_sanitize_text(note)
        if text:
            review_points.append(text)
    for conflict in digest.get('conflicts') or []:
        detail = conflict.get('detail') if isinstance(conflict, dict) else str(conflict)
        text = _visual_concept_plan_sanitize_text(detail)
        if text:
            review_points.append(text)

    for key in keys:
        value = parcel.get(key)
        if value in (None, ''):
            value = analysis.get(key)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        text = _visual_concept_plan_sanitize_text(_visual_concept_text(value, 1800))
        if not text:
            continue
        sources.append('مستندات الأرض والكروكي')
        existing = facts.get(key)
        if existing and existing != text:
            review_points.append(
                f'قيمة «{_VISUAL_PLAN_FACT_LABELS.get(key, key)}» في مستندات الأرض ({text}) '
                f'تختلف عن القاعدة الموثقة ({existing}).')
            continue
        facts.setdefault(key, text)

    conflicts = analysis.get('conflicts') if isinstance(analysis.get('conflicts'), list) else []
    coordinate_rows = parcel.get('survey_coordinates') or analysis.get('survey_coordinates') or source.get('survey_coordinates') or []
    facts['survey_coordinate_count'] = len(coordinate_rows) if isinstance(coordinate_rows, list) else 0
    for item in conflicts:
        text = _visual_concept_plan_sanitize_text(
            item if isinstance(item, str) else item.get('description') or item.get('field') or '')
        if text:
            review_points.append(text)
    facts['existing_review_points'] = list(dict.fromkeys(review_points))[:30]
    facts['regulatory_sources'] = list(dict.fromkeys(sources))
    return facts


def _visual_concept_plan_context(project_data, boundary_points=None, verification=None):
    source = project_data if isinstance(project_data, dict) else {}
    points = _visual_concept_plan_boundary_points(
        boundary_points or source.get('survey_coordinates') or source.get('regulation_coordinates'))
    directions = _visual_concept_directions(source)
    components = _visual_concept_components(source)
    context = {
        'project_name': _visual_concept_text(_visual_concept_read(source, 'project_name', 'projectName'), 160),
        'project_idea': _visual_concept_plan_sanitize_text(
            _visual_concept_text(_visual_concept_read(source, 'project_idea', 'projectIdea'), 4000)),
        'city': _visual_concept_text(_visual_concept_read(source, 'city'), 80),
        'district': _visual_concept_text(_visual_concept_read(source, 'district'), 100),
        'land_brief': _visual_concept_plan_sanitize_text(
            _visual_concept_text(_visual_concept_read(source, 'land_and_building_summary'), 6000)),
        'land_area': _visual_concept_text(_visual_concept_read(source, 'croquis_land_area', 'land_area', 'total_area_sqm'), 80),
        'design_area': _visual_concept_text(_visual_concept_read(source, 'approved_financial_area', 'land_area', 'total_area_sqm'), 80),
        'coverage_ratio': _visual_concept_text(_visual_concept_read(source, 'approved_coverage_ratio', 'coverage_ratio'), 120),
        'floor_area_ratio': _visual_concept_text(_visual_concept_read(source, 'approved_floor_area_ratio', 'floor_area_ratio'), 40),
        'open_area': _visual_concept_text(_visual_concept_read(source, 'open_area', 'open_spaces', 'open_space_area'), 120),
        'floor_count': _visual_concept_text(_visual_concept_read(source, 'approved_floor_count', 'max_floors_height', 'table_floors'), 120),
        'approved_floor_count': _visual_concept_text(_visual_concept_read(source, 'approved_floor_count'), 40),
        'north_direction': _visual_concept_text(_visual_concept_read(source, 'north_direction'), 80),
        'directions': directions,
        'surrounding_streets': _visual_concept_text(_visual_concept_read(source, 'surrounding_streets'), 1800),
        'setbacks': _visual_concept_text(_visual_concept_read(source, 'setbacks', 'building_ratio_setbacks'), 1800),
        'components': components,
        'boundary_points': points,
        'regulations': _visual_concept_plan_regulation_facts(source),
        'verification': verification if isinstance(verification, dict) else {},
        'colors': [{'use': use, 'color': color} for use, color in VISUAL_CONCEPT_PLAN_COLORS],
    }
    return _financial_parking_refresh_context(context, source)


def _visual_concept_plan_context_ensure_idea(context, project_data):
    """Backfill the recorded project idea into a cached planContext — workflows
    saved before the idea joined the context would still distribute the project
    as one undifferentiated mass without it."""
    if isinstance(context, dict) and not context.get('project_idea'):
        context['project_idea'] = _visual_concept_plan_sanitize_text(
            _visual_concept_text(
                _visual_concept_read(project_data, 'project_idea', 'projectIdea'), 4000))
    return context


def _visual_concept_plan_context_text(context, diagram_rules=True):
    context = context if isinstance(context, dict) else {}
    location = '، '.join(item for item in (context.get('city'), context.get('district')) if item)
    boundary = context.get('boundary_points') or []
    boundary_text = '; '.join(
        f"{item.get('point')}: E {item.get('eastings')} / N {item.get('northings')}"
        for item in boundary)
    directions = '\n'.join(
        f"- {item.get('direction')}: {item.get('regulation_text')}"
        for item in context.get('directions') or [] if item.get('regulation_text')) or 'غير متوفر'
    components = []
    for item in context.get('components') or []:
        parts = [item.get('name') or 'مكون غير مسمى']
        for label, key in (
            ('use', 'useType'), ('building', 'building'), ('floors', 'floorRange'),
            ('units', 'units'), ('area', 'unitArea'), ('built area', 'builtArea'), ('notes', 'notes')):
            if item.get(key) not in (None, ''):
                parts.append(f'{label}={item[key]}')
        components.append('- ' + '; '.join(parts))
    regulations = json.dumps(context.get('regulations') or {}, ensure_ascii=False)
    colors = ', '.join(f"{item['use']}={item['color']}" for item in context.get('colors') or [])
    text = (
        'APPROVED PLAN CONTEXT — use only these recorded facts; do not invent or recalculate values.\n'
        f"Project: {context.get('project_name') or 'unnamed'}\n"
        f"Location: {location or 'not recorded'}\n"
        f"Recorded project idea: {context.get('project_idea') or 'not recorded'}\n"
        f"Recorded land brief: {context.get('land_brief') or 'not recorded'}\n"
        f"Land area: {context.get('land_area') or 'not recorded'}\n"
        f"Secondary recorded area figure (not the design basis when it differs): {context.get('design_area') or 'not recorded'}\n"
        f"Coverage ratio: {context.get('coverage_ratio') or 'not recorded'}\n"
        f"Approved building coefficient (FAR): {context.get('floor_area_ratio') or 'not recorded'}\n"
        f"Open area: {context.get('open_area') or 'not recorded'}\n"
        f"Approved floor count/height: {context.get('floor_count') or 'not recorded'}\n"
        f"North direction: {context.get('north_direction') or 'not recorded'}\n"
        f"Setbacks: {context.get('setbacks') or 'not recorded'}\n"
        f"Surrounding streets: {context.get('surrounding_streets') or 'not recorded'}\n"
        f"Surveyed boundary points: {boundary_text or 'not recorded'}\n"
        f"Directions and edges:\n{directions}\n"
        f"Approved project components:\n{chr(10).join(components) or 'not recorded'}\n"
        f"Regulatory facts:\n{regulations}\n"
    )
    parking_brief = _financial_parking_visual_brief(context)
    if parking_brief:
        text += parking_brief + '\n'
    if diagram_rules:
        text += (
            f"Fixed color code: {colors}\n"
            'All image labels must be English. The result is conceptual and NOT TO SCALE.\n'
        )
    return text


def _visual_concept_plan_context_has_measurements(context):
    context = context if isinstance(context, dict) else {}
    if context.get('boundary_points') or context.get('components') or context.get('directions'):
        return True
    return any(context.get(key) for key in (
        'land_area', 'design_area', 'coverage_ratio', 'open_area', 'floor_count',
        'setbacks', 'surrounding_streets', 'north_direction'))


def _visual_concept_plan_prompt_header(kind, context):
    titles = {
        'site': ('مخطط الموقع العام المبسط', 'conceptual site plan'),
        'uses': ('مخطط توزيع الاستخدامات على الأدوار', 'vertical program'),
        'massing': ('منظور كتلي ثلاثي الأبعاد', 'conceptual massing'),
    }
    arabic, english = titles.get(kind) or titles['massing']
    name = _visual_concept_text(context.get('project_name'), 160) or 'the project'
    place = '، '.join(part for part in (
        _visual_concept_text(context.get('city'), 80),
        _visual_concept_text(context.get('district'), 100)) if part)
    return (f'اسم المشروع: {name}' + (f' — {place}' if place else '')
            + f'\nنوع الصورة المطلوبة: {arabic} {english}\n')


def _visual_concept_plan_direction_key(direction):
    labels = {'شمال': 'north', 'الشمال': 'north', 'الشمالي': 'north',
              'northern': 'north', 'north': 'north',
              'جنوب': 'south', 'الجنوب': 'south', 'الجنوبي': 'south',
              'southern': 'south', 'south': 'south',
              'شرق': 'east', 'الشرق': 'east', 'الشرقي': 'east',
              'eastern': 'east', 'east': 'east',
              'غرب': 'west', 'الغرب': 'west', 'الغربي': 'west',
              'western': 'west', 'west': 'west'}
    return labels.get(str(direction or '').strip().lower(), '')


def _visual_concept_plan_edge_text(text):
    text = _visual_concept_plan_sanitize_text(text).rstrip('.')
    if not text:
        return ''
    if re.match(r'^[A-Z][a-z]+\s+[A-Z]', text):
        return text
    if re.match(r'^[A-Z]', text):
        return text[:1].lower() + text[1:]
    return text


def _visual_concept_plan_edge_english(text):
    """English edge phrase built from recorded features — keeps the recorded
    widths and maps the common Arabic edge types (dead-end street, corniche,
    beautification strip, sea) so raw source text never leaks into a bullet."""
    if not re.search(r'[\u0600-\u06FF]', text):
        return _visual_concept_plan_edge_text(text)

    def width_near(pattern):
        match = re.search(r'(?:' + pattern + r')[^0-9.]{0,40}?(\d+(?:\.\d+)?)\s*(?:م(?:تر)?|m\b)',
                          text, flags=re.IGNORECASE)
        return match.group(1) if match else ''

    bits = []
    if re.search(r'غير\s*نافذ|dead[\s-]?end', text, flags=re.IGNORECASE):
        width = width_near(r'شارع|street')
        bits.append(f'a {width} m-wide dead-end street' if width else 'a dead-end street')
    elif not re.search(r'كورنيش|corniche', text, flags=re.IGNORECASE) and re.search(
            r'شارع|طريق|street|road', text, flags=re.IGNORECASE):
        width = width_near(r'شارع|طريق|street|road')
        bits.append(f'a {width} m-wide street' if width else 'a street')
    if re.search(r'تجميل|beautif', text, flags=re.IGNORECASE):
        width = width_near(r'تجميلي[ةه]?|beautif\w*')
        bits.append(f'a beautification strip averaging {width} m wide'
                    if width else 'a beautification strip')
    if re.search(r'كورنيش|corniche', text, flags=re.IGNORECASE):
        width = width_near(r'كورنيش|corniche')
        bits.append(f'Corniche Road averaging {width} m wide' if width else 'Corniche Road')
    if re.search(r'بحر|sea\b|shore|coast', text, flags=re.IGNORECASE):
        bits.append('the sea beyond')
    if bits:
        return ' and then '.join(bits)
    return _visual_concept_plan_edge_text(text)


# Fixed stack order for the derived concept distribution: tuple order is both the
# keyword-match priority and the vertical band order (parking lowest, service on
# the roof). Each category maps to a fixed palette use.
_VISUAL_PLAN_USE_CATEGORIES = (
    ('parking', 'Parking/Service',
     ('parking', 'garage', 'basement', 'car park', 'جراج', 'مواقف', 'باركينج', 'سرداب')),
    ('retail', 'Retail & F&B',
     ('retail', 'restaurant', 'f&b', 'food', 'shop', 'showroom', 'cafe', 'café',
      'تجزئة', 'مطاعم', 'مطعم', 'محلات', 'تجاري', 'كافيه')),
    ('office', 'Amenities',
     ('office', 'admin', 'workspace', 'مكاتب', 'مكتبي', 'إداري', 'اداري')),
    ('amenity', 'Amenities',
     ('amenit', 'spa', 'wellness', 'hall', 'event', 'gym', 'club', 'lounge', 'recreation',
      'سبا', 'قاعات', 'قاعة', 'مرافق', 'ترفيه', 'نادي')),
    ('hotel', 'Hotel',
     ('hotel', 'hospitality', 'resort', 'motel', 'فندق', 'فنادق', 'فندقي', 'ضيافة', 'منتجع')),
    ('residential', 'Residential',
     ('residential', 'apartment', 'housing', 'villa', 'duplex', 'flat',
      'سكني', 'سكن', 'شقق', 'شقة', 'فلل', 'فيلا')),
    ('service', 'Parking/Service',
     ('service', 'mechanical', 'facilit', 'maintenance', 'utility',
      'خدمات', 'تشغيل', 'ميكانيكا', 'صيانة')),
    ('landscape', 'Landscape/Open space',
     ('landscape', 'open space', 'green', 'park', 'plaza',
      'لاندسكيب', 'فراغات', 'حدائق', 'مسطحات', 'بلازا')),
)
_VISUAL_PLAN_USE_ORDER = {key: index for index, (key, _label, _kw)
                          in enumerate(_VISUAL_PLAN_USE_CATEGORIES)}
_VISUAL_PLAN_USE_LABEL = {key: label for key, label, _kw in _VISUAL_PLAN_USE_CATEGORIES}


def _visual_concept_plan_use_category(item):
    text = ' '.join(filter(None, (
        str(item.get('useType') or ''), str(item.get('name') or ''),
        str(item.get('notes') or '')))).lower()
    for key, _label, keywords in _VISUAL_PLAN_USE_CATEGORIES:
        if any(keyword in text for keyword in keywords):
            return _VISUAL_PLAN_USE_ORDER[key], key
    return _VISUAL_PLAN_USE_ORDER['amenity'], 'amenity'


def _visual_concept_plan_sector_hints(regulations):
    """Sector floor caps, e.g. «الجزء الغربي بلا حد» / «بارتفاع حتى 4 طوابق للجزء الشرقي».

    A cap may be written before its direction word, so every «N floors» occurrence is
    attributed to the nearest sector-direction mention in the same field, whichever
    side of the number the direction sits on. Mentions require a sector word nearby
    (الجزء/القطاع/sector/...) so street names carrying a direction («الطريق الشمالي»)
    do not count.
    """
    keys = (
        'floor_area_ratio', 'table_floors', 'max_floors_height', 'land_use',
        'allowed_uses', 'allowed_uses_restrictions', 'zoning_code',
        'regulatory_constraints', 'building_ratio', 'building_ratio_coverage',
        'building_ratio_setbacks',
    )
    direction_word = (
        r'(\b(?:western|eastern|northern|southern|west|east|north|south)\b'
        r'|الغربي?|الشرقي?|الشمالي?|الجنوبي?|غرب|شرق|شمال|جنوب)')
    sector_word = (
        r'(?:القطاع|النطاق|الجزء|جزء|قطاع|نطاق|الشريحة|شريحة|المحور|محور'
        r'|\b(?:sector|zone|part|axis)\b)')
    mention_patterns = (
        direction_word + r'[\w\u0600-\u06FF\- ]{0,30}?' + sector_word,
        sector_word + r'[\w\u0600-\u06FF\- ]{0,30}?' + direction_word,
    )
    cap_pattern = re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:residential\s+|above[\w\- ]*\s+|سكنية?\s+|عمائر\s+)?'
        r'(?:floors?|storeys?|أدوار|ادوار|طوابق|طابق|دور)',
        flags=re.IGNORECASE)
    uncapped_pattern = re.compile(
        r'(?:بدون|دون|بلا|لا)\s*حد|غير\s*محدود[ةه]?|مفتوح[ةه]?|مرن[ةه]?\b|مرونة'
        r'|no\s*maximum|without\s*(?:a\s*)?(?:maximum|limit|cap)|unlimited'
        r'|flexible|open[- ]ended',
        flags=re.IGNORECASE)
    stats = {}
    for key in keys:
        text = str(regulations.get(key) or '')
        if not text:
            continue
        mentions = []
        for pattern in mention_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                direction = _visual_concept_plan_direction_key(match.group(1))
                if direction:
                    mentions.append((match.start(1), direction))
        if not mentions:
            continue
        mentions.sort()
        for _pos, direction in mentions:
            stats.setdefault(direction, {'direction': direction, 'cap': None,
                                         'cap_dist': 10 ** 9, 'uncapped': False})
        for match in cap_pattern.finditer(text):
            pos, direction = min(mentions, key=lambda item: abs(match.start() - item[0]))
            dist = abs(match.start() - pos)
            if dist <= 200 and dist < stats[direction]['cap_dist']:
                stats[direction]['cap'] = int(float(match.group(1)))
                stats[direction]['cap_dist'] = dist
        for match in uncapped_pattern.finditer(text):
            pos, direction = min(mentions, key=lambda item: abs(match.start() - item[0]))
            if abs(match.start() - pos) <= 160:
                stats[direction]['uncapped'] = True
    return [{'direction': entry['direction'], 'cap': entry['cap'],
             'uncapped': entry['uncapped']} for entry in stats.values()]


_VISUAL_PLAN_SETBACK_EN = (
    (r'في حال وجود مواقف سيارات متعامدة بالارتداد|في حال(?:ة)? وجود مواقف متعامدة',
     'where perpendicular parking is provided within the setback'),
    (r'مواقف سيارات متعامدة|مواقف متعامدة', 'perpendicular parking'),
    (r'ارتداد الملحق العلوي|الملحق العلوي', 'upper-annex setback'),
    (r'الشارع الجانبي|جهة الشارع الجانبي|الشوارع الجانبية', 'side street'),
    (r'الشوارع المحيطة|الشوارع المجاورة', 'surrounding streets'),
    (r'جهة الجوار|جهات الجوار|الجوار', 'neighbors'),
    (r'الأمامي|الأمامية|أمامي|الواجهة الأمامية', 'front'),
    (r'الجانبي|الجانبية|جانبي', 'side'),
    (r'الخلفي|الخلفية|خلفي', 'rear'),
    (r'من جهة', 'from'),
    (r'حتى|بحد أقصى', 'up to'),
    (r'إلى', 'to'),
    (r'طوابق|طابقاً|طابق|أدوار|ادوار|دور', 'floors'),
    (r'أو', 'or'),
    (r'و(?=\s*\d)', ' and '),
    (r'من', 'from'),
    (r'في', 'in'),
    (r'(?<=\d)\s*م(?=\s|$|[،,;.²])', ' m'),
)


def _visual_concept_plan_setback_en(text):
    """Light deterministic Arabic-to-English for recorded setback phrasing —
    keeps every number and condition, maps the standard setback vocabulary."""
    text = str(text or '').strip()
    if not re.search(r'[\u0600-\u06FF]', text):
        return text
    for pattern, replacement in _VISUAL_PLAN_SETBACK_EN:
        text = re.sub(pattern, replacement, text)
    return re.sub(r'\s+', ' ', text.replace('،', ', ').replace('؛', '; ')).strip()


_VISUAL_PLAN_NAME_EN = (
    (r'خمس[ةه]?\s*نجوم|5\s*نجوم', 'Five-Star Hotel'),
    (r'شقق[^.]*فاخر|فاخر[^.]*شقق|سكنية?\s*فاخرة?|فاخرة?\s*سكنية?', 'Luxury Residential Apartments'),
    (r'فندق|فنادق|ضيافة', 'Hotel'),
    (r'شقق|سكني|سكن\b|وحدات\s*سكنية', 'Residential Apartments'),
    (r'مطاعم|مطعم|كافيه|كافيتيريا', 'Restaurants'),
    (r'قاعات|فعاليات|مناسبات|احتفالات', 'Halls and Events'),
    (r'سبا|صحية|عافية|نادي\s*صحي', 'Spa and Wellness Facilities'),
    (r'خدمات|مرافق\s*مشتركة|مشتركة', 'Shared Services and Facilities'),
    (r'مكاتب|إداري|اداري|مكتبي', 'Offices'),
    (r'مواقف|جراج|سرداب|باركينج', 'Parking'),
    (r'تجاري|تجزئة|محلات|معارض|تجارية', 'Retail'),
    (r'لاندسكيب|حدائق|مسطحات\s*خضراء|مناظر', 'Landscaping'),
)


def _visual_concept_plan_component_en(name):
    """English display name for a component — maps the common Arabic program
    vocabulary; anything unrecognized stays as recorded."""
    name = str(name or '').strip()
    if not name or not re.search(r'[\u0600-\u06FF]', name):
        return name
    for pattern, english in _VISUAL_PLAN_NAME_EN:
        if re.search(pattern, name):
            return english
    return name


_VISUAL_PLAN_CITY_EN = {
    'الرياض': 'Riyadh', 'جدة': 'Jeddah', 'مكة': 'Makkah', 'مكة المكرمة': 'Makkah',
    'المدينة': 'Madinah', 'المدينة المنورة': 'Madinah', 'الدمام': 'Dammam',
    'الخبر': 'Al Khobar', 'الظهران': 'Dhahran', 'الطائف': 'Taif', 'أبها': 'Abha',
    'ابها': 'Abha', 'تبوك': 'Tabuk', 'بريدة': 'Buraidah', 'خميس مشيط': 'Khamis Mushait',
    'حائل': 'Hail', 'جازان': 'Jazan', 'نجران': 'Najran', 'الباحة': 'Al Baha',
    'سكاكا': 'Sakaka', 'عرعر': 'Arar', 'ينبع': 'Yanbu', 'الأحساء': 'Al Ahsa',
    'الاحساء': 'Al Ahsa', 'الهفوف': 'Hofuf', 'القطيف': 'Qatif', 'الجبيل': 'Jubail',
    'رابغ': 'Rabigh', 'العلا': 'AlUla', 'نيوم': 'NEOM', 'حفر الباطن': 'Hafar Al Batin',
    'المبرز': 'Al Mubarraz', 'عنيزة': 'Unaizah', 'الرس': 'Ar Rass', 'الخرج': 'Al Kharj',
    'الدوادمي': 'Dawadmi', 'المجمعة': 'Majmaah', 'القريات': 'Qurayyat', 'رفحاء': 'Rafha',
    'طريف': 'Turaif', 'بيشة': 'Bisha', 'صبيا': 'Sabya',
}


def _visual_concept_plan_place_en(context):
    """English-only place for the spec's project line: the city map covers the
    Saudi names; an unmappable Arabic district is dropped — the Arabic header
    line above it already carries the full place."""
    parts = []
    city = _visual_concept_plan_sanitize_text(context.get('city'))
    district = _visual_concept_plan_sanitize_text(context.get('district'))
    city_en = _VISUAL_PLAN_CITY_EN.get(city, city)
    if city_en and not re.search(r'[\u0600-\u06FF]', city_en):
        parts.append(city_en)
    if district and not re.search(r'[\u0600-\u06FF]', district):
        parts.append(district)
    return ', '.join(parts)


_VISUAL_PLAN_FLOOR_LABEL_EN = {
    'ارضي': 'ground', 'ميزانين': 'mezzanine', 'مسروق': 'mezzanine',
    'ملحقعلوي': 'roof annex', 'ملحق': 'roof annex', 'سطح': 'roof', 'بدروم': 'basement',
}


def _visual_concept_plan_floor_label_en(text):
    """English floor tag for the spec's masses line: «أرضي» -> «ground»,
    «بدروم 1-3» -> «basement 1-3», a numeric range passes through."""
    value = str(text or '').strip()
    if not value:
        return value
    basement = re.match(r'بدروم\s*(\d+(?:\s*-\s*\d+)?)\s*$', value)
    if basement:
        return 'basement ' + re.sub(r'\s+', '', basement.group(1))
    key = _visual_concept_plan_component_key(value)
    if key in _VISUAL_PLAN_FLOOR_LABEL_EN:
        return _VISUAL_PLAN_FLOOR_LABEL_EN[key]
    return value


_VISUAL_PLAN_BUILDING_EN = {'المبنى الرئيسي': 'Main Building'}


def _visual_concept_plan_building_en(name):
    """Building label for English spec text: our own default names translate;
    anything the client recorded stays a proper name."""
    text = str(name or '').strip()
    return _VISUAL_PLAN_BUILDING_EN.get(text, text) or 'Main Building'


def _visual_concept_plan_component_brief(item):
    name = _visual_concept_plan_component_en(_visual_concept_plan_sanitize_text(item.get('name')))
    bits = []
    if item.get('units') not in (None, ''):
        units = str(item['units']).strip()
        bits.append(f"{units} {'unit' if units in ('1', '1.0') else 'units'}")
    area = item.get('builtArea') or item.get('unitArea')
    if area not in (None, ''):
        bits.append(f'{area} m²')
    if item.get('floorRange') not in (None, ''):
        bits.append(f"floors {_visual_concept_plan_floor_label_en(item['floorRange'])}")
    if item.get('building') not in (None, ''):
        bits.append(f"building {_visual_concept_plan_building_en(item['building'])}")
    return name + (f" ({'; '.join(bits)})" if bits else '')


def _visual_concept_plan_use_color(context, use_label):
    for item in context.get('colors') or []:
        if str(item.get('use') or '').strip().lower() == str(use_label).strip().lower():
            return str(item.get('color') or '').strip()
    return ''


def _visual_concept_plan_direction_scan(context):
    """Classify recorded direction rows: which edges are streets, which is the
    sea/corniche frontage. Returns (street_dirs, other_dirs, sea_dir)."""
    street_dirs, other_dirs, sea_dir = [], [], ''
    for item in context.get('directions') or []:
        text = _visual_concept_plan_sanitize_text(item.get('regulation_text'))
        key = _visual_concept_plan_direction_key(item.get('direction'))
        if not key:
            continue
        if re.search(r'sea|shore|coast|بحر|شاطئ|كورنيش|corniche|waterfront|واجهة\s+بحرية',
                     text, flags=re.IGNORECASE):
            sea_dir = sea_dir or key
        if re.search(r'street|road|corniche|شارع|طريق|كورنيش', text, flags=re.IGNORECASE):
            street_dirs.append(key)
        else:
            other_dirs.append(key)
    return street_dirs, other_dirs, sea_dir


def _visual_concept_plan_entry_dirs(street_dirs, sea_dir, high_sector):
    """The main entry belongs on the sea/corniche frontage when one is recorded;
    the residential entry takes the next street and the service entry a third
    street when one exists — never a neighbor edge (no entry crosses a plot line)."""
    main_dir = sea_dir or (street_dirs[0] if street_dirs else (
        high_sector['direction'] if high_sector else ''))
    res_dir = next((direction for direction in street_dirs if direction != main_dir), '')
    svc_dir = next((direction for direction in street_dirs
                    if direction not in (main_dir, res_dir)), res_dir)
    return main_dir, res_dir, svc_dir


def _visual_concept_plan_sanitize_text(value):
    text = str(value or '').strip()
    text = re.sub(r'اشتراطات\s*[12](?:\.pdf)?', 'المرجع التنظيمي', text, flags=re.IGNORECASE)
    text = re.sub(r'SBC\s*201[\s_-]*AR[\s_-]*2024(?:\.pdf)?|SBC201_AR2024(?:\.pdf)?',
                  'كود البناء السعودي', text, flags=re.IGNORECASE)
    text = re.sub(r'(?:صفحة|صفحات|ص)\s*[0-9٠-٩]+(?:\s*[-–—]\s*[0-9٠-٩]+)?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:source_file|filename|source|document_processing)\b\s*[:=][^،\n]+', '', text, flags=re.IGNORECASE)
    return re.sub(r'\s{2,}', ' ', text).strip(' -–—')


def _visual_concept_plan_bullets(value, limit=12):
    values = value if isinstance(value, list) else re.split(r'\n+|•|\s+-\s+', str(value or ''))
    result = []
    for item in values:
        text = _visual_concept_plan_sanitize_text(item)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _visual_concept_plan_normalize_verification(raw):
    source = raw if isinstance(raw, dict) else {}
    checks = []
    for item in (source.get('checks') if isinstance(source.get('checks'), list) else [])[:40]:
        if not isinstance(item, dict):
            continue
        name = _visual_concept_plan_sanitize_text(item.get('item') or item.get('check'))
        if not name:
            continue
        result = _visual_concept_plan_sanitize_text(item.get('result') or item.get('status'))
        if result not in {'مطابق', 'متعارض', 'يحتاج تأكيد', 'غير متوفر'}:
            result = 'يحتاج تأكيد'
        issues = _visual_concept_plan_bullets(item.get('issues') or item.get('note') or item.get('action'))
        checks.append({
            'item': name,
            'field': _visual_concept_plan_sanitize_text(item.get('field') or item.get('key'))[:160],
            'section': _visual_concept_plan_sanitize_text(item.get('section'))[:160],
            'project': _visual_concept_plan_sanitize_text(item.get('project') or item.get('project_value'))[:600],
            'regulatory': _visual_concept_plan_sanitize_text(item.get('regulatory') or item.get('reference') or item.get('constraint'))[:600],
            'result': result,
            'issues': issues,
            'suggestion': _visual_concept_plan_sanitize_text(
                item.get('suggestion') or item.get('resolution') or item.get('solution') or item.get('action')
            )[:800],
            'action': _visual_concept_plan_sanitize_text(item.get('action') or item.get('recommendation'))[:600],
        })
    issues = _visual_concept_plan_normalize_issues(
        source.get('issues') or source.get('blocking_issues') or [])
    summary = _visual_concept_plan_sanitize_text(source.get('summary'))
    return {
        'checks': checks,
        'issues': issues[:30],
        'summary': summary[:1600],
        'canProceed': bool(source.get('canProceed', source.get('can_proceed', True))),
        'approved': False,
    }


def _visual_concept_plan_fallback_verification(context):
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    checks = []
    pairs = (
        ('مساحة الأرض', context.get('land_area'), regulations.get('croquis_land_area')),
        ('نسبة التغطية', context.get('coverage_ratio'), regulations.get('coverage_ratio') or regulations.get('building_ratio_coverage')),
        ('عدد الأدوار', context.get('floor_count'), regulations.get('table_floors') or regulations.get('max_floors_height')),
        ('معامل البناء', context.get('floor_area_ratio'), regulations.get('floor_area_ratio')),
        ('الارتدادات', context.get('setbacks'), regulations.get('setbacks') or regulations.get('building_ratio_setbacks')),
        ('الإحداثيات', len(context.get('boundary_points') or []), regulations.get('survey_coordinate_count') or 0),
        ('مكونات المشروع', len(context.get('components') or []), len(context.get('components') or [])),
    )
    for name, project_value, regulatory_value in pairs:
        project_text = _visual_concept_plan_sanitize_text(project_value) if not isinstance(project_value, int) else str(project_value)
        regulatory_text = _visual_concept_plan_sanitize_text(regulatory_value) if not isinstance(regulatory_value, int) else str(regulatory_value)
        result = 'مطابق' if project_text and regulatory_text and project_text == regulatory_text else ('يحتاج تأكيد' if project_text or regulatory_text else 'غير متوفر')
        suggestion = '' if result == 'مطابق' else f'راجع قيمة «{name}» في قسم بيانات المشروع مقابل القيمة الموثقة، وثبّت القيمة المعتمدة قبل الاعتماد.'
        checks.append({'item': name, 'field': name, 'section': 'بيانات المشروع', 'project': project_text, 'regulatory': regulatory_text, 'result': result, 'issues': [], 'suggestion': suggestion, 'action': ''})
    issues = []
    for item in checks:
        if item['result'] in {'يحتاج تأكيد', 'غير متوفر'}:
            issues.append({'id': str(len(issues) + 1), 'title': item['item'], 'points': ['القيمة تحتاج مراجعة يدوية قبل اعتمادها.'], 'action': 'مراجعة القيمة وتأكيدها.', 'suggestion': item.get('suggestion') or '', 'severity': 'medium'})
    return {'checks': checks, 'issues': issues, 'summary': 'تمت مقارنة المدخلات المتاحة مع البيانات التنظيمية المسجلة.', 'canProceed': True, 'approved': False}


def _visual_concept_plan_scrub_internal_ids(text):
    """Strip internal row ids (row_4) the review model sometimes echoes — they
    mean nothing to the client."""
    if not text:
        return ''
    cleaned = re.sub(r'(?<![A-Za-z0-9_])(?:و\s*)?row_\w+', '', str(text))
    cleaned = re.sub(r'(\s*[،,]\s*){2,}', '، ', cleaned)
    cleaned = re.sub(r'\bو\s*و\b', 'و', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
    return re.sub(r'^\s*(?:,\s*|،\s*|و(?=\s|$)\s*)+', '', cleaned)


def _visual_concept_plan_normalize_issues(issue_source, limit=30):
    issues = []
    for index, item in enumerate(issue_source if isinstance(issue_source, list) else [issue_source], 1):
        if isinstance(item, dict):
            title = _visual_concept_plan_scrub_internal_ids(_visual_concept_plan_sanitize_text(
                item.get('title') or item.get('item') or f'ملاحظة {index}'))
            bullets = [_visual_concept_plan_scrub_internal_ids(bullet) for bullet in
                       _visual_concept_plan_bullets(item.get('points') or item.get('issues') or item.get('description'))]
            bullets = [bullet for bullet in bullets if bullet]
            action = _visual_concept_plan_scrub_internal_ids(
                _visual_concept_plan_sanitize_text(item.get('action') or item.get('recommendation')))
            suggestion = _visual_concept_plan_scrub_internal_ids(_visual_concept_plan_sanitize_text(
                item.get('suggestion') or item.get('resolution') or item.get('solution') or action))
            severity = _visual_concept_plan_sanitize_text(item.get('severity') or 'medium')
        else:
            title = f'ملاحظة {index}'
            bullets = _visual_concept_plan_bullets(item)
            action = ''
            suggestion = ''
            severity = 'medium'
        if bullets or title:
            issues.append({'id': str(index), 'title': title, 'points': bullets,
                           'action': action, 'suggestion': suggestion, 'severity': severity})
    return issues[:limit]


_PLAN_BODY_TITLES = {
    'site': 'CONCEPTUAL SITE PLAN',
    'uses': 'VERTICAL PROGRAM',
    'massing': 'CONCEPTUAL MASSING',
}


def _visual_concept_plan_adapt_bodies(distribution, bodies, data):
    """sol rewrites each fixed DRAWING REQUESTED paragraph so the template matches
    the client-approved distribution (no podium without a base row, no basement
    without parking rows, extra approved buildings added). Only the body leaves
    the model — the header and the APPROVED DISTRIBUTION MODEL block are spliced
    back verbatim, so an approved fact can never be dropped by the adaptation."""
    rows = (distribution or {}).get('rows') or []
    if not rows or not isinstance(bodies, dict):
        return {}
    system_prompt = (
        'You adapt fixed architectural diagram prompts to an approved project distribution. '
        'For each kind, rewrite ONLY the DRAWING REQUESTED paragraph so it matches the approved '
        'distribution: drop any element the distribution does not contain (podium, low block, '
        'basement parking, sea band, extra entries), and add approved elements the template lacks. '
        'But the APPROVED DISTRIBUTION MODEL block above the body is fact: every mass, entry, '
        'street, and setback it lists stays in the drawing — never remove, forbid, or contradict '
        'an element the spec lists; only drop template elements the spec itself does not contain. '
        'Keep the flat pastel style, English labels, legend, titles, and "NOT TO SCALE" caption. '
        'Never change an approved number, direction, color, or label; never mention sources or files. '
        'Return JSON only: {"site":"...","uses":"...","massing":"..."} with the full adapted '
        'DRAWING REQUESTED paragraph per kind.'
    )
    user_prompt = (
        'APPROVED DISTRIBUTION (client-approved, the only program truth):\n'
        + json.dumps({'rows': rows, 'totals': distribution.get('totals') or []}, ensure_ascii=False)
        + '\n\nFIXED PROMPT BODIES TO ADAPT:\n'
        + '\n\n'.join(f"=== {kind} ===\n{bodies[kind]}" for kind in ('site', 'uses', 'massing')
                      if kind in bodies)
    )
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=9000,
            model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
            response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
        parsed = parse_json_object(_get_chat_response_text(response))
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    adapted = {}
    for kind in bodies:
        title = _PLAN_BODY_TITLES.get(kind, '')
        text = str(parsed.get(kind) or '').strip()
        if len(text) >= 200 and 'DRAWING REQUESTED' in text and (not title or title in text):
            adapted[kind] = text
    return adapted


def _visual_concept_render_plan_boundary_reference(points, tenant_id):
    points = _visual_concept_plan_boundary_points(points)
    if len(points) < 3:
        return ''
    try:
        from io import BytesIO
        from PIL import Image, ImageDraw
        eastings = [float(item['eastings']) for item in points]
        northings = [float(item['northings']) for item in points]
        min_e, max_e = min(eastings), max(eastings)
        min_n, max_n = min(northings), max(northings)
        span = max(max_e - min_e, max_n - min_n) or 1
        width = height = 1200
        margin = 150
        scale = (width - 2 * margin) / span
        def to_pixel(east, north):
            x = margin + (east - min_e) * scale + (width - 2 * margin - (max_e - min_e) * scale) / 2
            y = height - (margin + (north - min_n) * scale + (height - 2 * margin - (max_n - min_n) * scale) / 2)
            return int(round(x)), int(round(y))
        image = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(image)
        polygon = [to_pixel(east, north) for east, north in zip(eastings, northings)]
        draw.polygon(polygon, fill=(232, 240, 232), outline=(23, 43, 77))
        draw.line(polygon + [polygon[0]], fill=(23, 43, 77), width=8, joint='curve')
        for point in polygon:
            draw.ellipse([point[0] - 9, point[1] - 9, point[0] + 9, point[1] + 9], fill=(23, 43, 77))
        arrow_x, arrow_y = margin, margin
        draw.line([(arrow_x, arrow_y + 75), (arrow_x, arrow_y)], fill=(23, 43, 77), width=8)
        draw.polygon([(arrow_x, arrow_y - 16), (arrow_x - 15, arrow_y + 12), (arrow_x + 15, arrow_y + 12)], fill=(23, 43, 77))
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
        return persist_generated_image(f'data:image/png;base64,{encoded}', tenant_id) or ''
    except Exception as error:
        app.logger.warning('Could not render plan boundary reference: %s', error)
        return ''


def _visual_concept_plan_regulation_input(project_data, context):
    return {
        'project_facts': {
            'land_area': context.get('land_area'),
            'coverage_ratio': context.get('coverage_ratio'),
            'open_area': context.get('open_area'),
            'floor_count': context.get('floor_count'),
            'setbacks': context.get('setbacks'),
            'directions': context.get('directions'),
            'components': context.get('components'),
            'boundary_point_count': len(context.get('boundary_points') or []),
        },
        'regulatory_facts': context.get('regulations') or {},
    }


def _visual_concept_plan_workflow_error(data, slot_id, require_boundary=False, require_distribution=False):
    if _visual_concept_plan_kind(slot_id) not in VISUAL_CONCEPT_PLAN_KIND_BY_ID.values():
        return None
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    verification = workflow.get('verification') if isinstance(workflow.get('verification'), dict) else {}
    boundary = workflow.get('boundary') if isinstance(workflow.get('boundary'), dict) else {}
    distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
    if not verification.get('approved'):
        return {'success': False, 'error': 'اعتماد نتيجة التحقق مطلوب قبل متابعة المخططات', 'error_code': 'PLANS_VERIFICATION_REQUIRED'}
    if require_boundary and not boundary.get('approved'):
        return {'success': False, 'error': 'اعتماد حدود الأرض مطلوب قبل متابعة المخططات', 'error_code': 'PLANS_BOUNDARY_REQUIRED'}
    if require_distribution and not distribution.get('approved'):
        return {'success': False, 'error': 'اعتماد توزيع المكونات مطلوب قبل متابعة المخططات', 'error_code': 'PLANS_DISTRIBUTION_REQUIRED'}
    # Sequential generation: each diagram is drawn on the previous approved
    # image(s), so a later kind cannot run before its predecessors are approved.
    kind = _visual_concept_plan_kind(slot_id, data.get('planKind'))
    plan_images = _visual_concept_plan_image_map(data)
    missing = [dep for dep in _VISUAL_PLAN_KIND_DEPENDENCIES.get(kind, ())
               if not plan_images.get(dep)]
    if missing:
        missing_labels = ' و'.join(_VISUAL_PLAN_KIND_LABELS[dep] for dep in missing)
        return {'success': False,
                'error': f'اعتمد {missing_labels} قبل توليد {_VISUAL_PLAN_KIND_LABELS.get(kind, "المخطط")}',
                'error_code': 'PLANS_ORDER_REQUIRED'}
    return None
