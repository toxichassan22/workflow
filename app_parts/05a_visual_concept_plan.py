


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
        try:
            digest = regulation_digest.build_regulation_digest(
                _visual_concept_plan_site_facts(source, analysis, parcel))
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
        'city': _visual_concept_text(_visual_concept_read(source, 'city'), 80),
        'district': _visual_concept_text(_visual_concept_read(source, 'district'), 100),
        'land_brief': _visual_concept_plan_sanitize_text(
            _visual_concept_text(_visual_concept_read(source, 'land_and_building_summary'), 6000)),
        'land_area': _visual_concept_text(_visual_concept_read(source, 'croquis_land_area', 'land_area', 'total_area_sqm'), 80),
        'design_area': _visual_concept_text(_visual_concept_read(source, 'approved_financial_area', 'land_area', 'total_area_sqm'), 80),
        'coverage_ratio': _visual_concept_text(_visual_concept_read(source, 'approved_coverage_ratio', 'coverage_ratio'), 120),
        'open_area': _visual_concept_text(_visual_concept_read(source, 'open_area', 'open_spaces', 'open_space_area'), 120),
        'floor_count': _visual_concept_text(_visual_concept_read(source, 'approved_floor_count', 'max_floors_height', 'table_floors'), 120),
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
        f"Recorded land brief: {context.get('land_brief') or 'not recorded'}\n"
        f"Land area: {context.get('land_area') or 'not recorded'}\n"
        f"Secondary recorded area figure (not the design basis when it differs): {context.get('design_area') or 'not recorded'}\n"
        f"Coverage ratio: {context.get('coverage_ratio') or 'not recorded'}\n"
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


def _visual_concept_plan_model(context, regulations):
    """One derived concept distribution shared by all three plan prompts —
    bands in fixed stack order, tower on the uncapped sector, low block on the
    floor-capped sector, parking below grade, service on the roof."""
    components = [item for item in context.get('components') or []
                  if isinstance(item, dict) and item.get('name')]
    if not components:
        return None
    below, roof, bands, open_uses = [], [], [], []
    for index, item in enumerate(components):
        order, category = _visual_concept_plan_use_category(item)
        entry = (order, index, item, category)
        if category == 'parking':
            below.append(entry)
        elif category == 'service':
            roof.append(entry)
        elif category == 'landscape':
            open_uses.append(entry)
        else:
            bands.append(entry)
    bands.sort(key=lambda row: (row[0], row[1]))

    groups = []
    for _order, _index, item, category in bands:
        if groups and groups[-1][0] == category:
            groups[-1][1].append(item)
        else:
            groups.append((category, [item]))

    hints = _visual_concept_plan_sector_hints(regulations)
    capped = [hint for hint in hints if hint.get('cap')]
    low_sector = min(capped, key=lambda hint: hint['cap']) if capped else None
    # The high-rise axis is the sector recorded with no height cap; a sector that
    # simply has no cap recorded still outranks the floor-capped low block.
    explicit_open = [hint for hint in hints
                     if hint.get('uncapped') and hint is not low_sector]
    open_hints = [hint for hint in hints
                  if not hint.get('cap') and hint is not low_sector]
    high_sector = (explicit_open or open_hints or [None])[0]

    street_dirs, _other_dirs, sea_dir = _visual_concept_plan_direction_scan(context)

    floor_count = _visual_concept_number(context.get('floor_count'))
    floor_count = int(floor_count) if floor_count else 0
    floors, ranges = [], []
    if floor_count and groups:
        areas = []
        for _category, items in groups:
            area = 0.0
            for part in items:
                area += (_visual_concept_number(part.get('builtArea'))
                         or _visual_concept_number(part.get('unitArea')) or 0.0)
            areas.append(area)
        total_area = sum(areas) or 1.0
        raw = [area / total_area * floor_count for area in areas]
        floors = [max(1, int(value)) for value in raw]
        remainder = floor_count - sum(floors)
        order = sorted(range(len(groups)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
        index = 0
        while remainder > 0 and order:
            floors[order[index % len(order)]] += 1
            remainder -= 1
            index += 1
        while remainder < 0:
            for i in sorted(range(len(groups)), key=lambda i: floors[i], reverse=True):
                if remainder >= 0:
                    break
                if floors[i] > 1:
                    floors[i] -= 1
                    remainder += 1
        start = 1
        for count in floors:
            end = start + count - 1
            lo = 'G' if start == 1 else str(start)
            ranges.append(f'{lo}-{end}' if end > start else lo)
            start = end + 1

    bands_out = []
    for position, (category, items) in enumerate(groups):
        label = _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')
        if position > 0 and len(items) == 1:
            # A band label becomes callout text in the drawing, so it must stay
            # English: a recorded Arabic name the lexicon cannot map falls back to
            # the use category label — the name itself still reaches the prompt as
            # data inside the component brief.
            name = _visual_concept_plan_component_en(
                _visual_concept_plan_sanitize_text(items[0].get('name')))
            if name and not re.search(r'[\u0600-\u06FF]', name):
                label = name
        bands_out.append({
            'category': category,
            'label': label,
            'items': items,
            'floors': floors[position] if position < len(floors) else 0,
            'range': ranges[position] if position < len(ranges) else '',
            'color': _visual_concept_plan_use_color(
                context, _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')),
        })

    main_dir, res_dir, svc_dir = _visual_concept_plan_entry_dirs(street_dirs, sea_dir, high_sector)
    has_residential = any(band['category'] == 'residential' for band in bands_out)
    block_label = (f"{low_sector['direction'].title()} Block"
                   if low_sector and low_sector.get('direction') else 'Low Block')
    blocks = []
    if low_sector:
        blocks.append({
            'label': block_label,
            'cap': low_sector.get('cap') or 0,
            'direction': low_sector.get('direction') or '',
            'use': 'Residential' if has_residential else 'Low-rise',
            'color': _visual_concept_plan_use_color(context, 'Residential') or 'soft-blue',
            'bands': [],
        })
    return {
        'bands': bands_out,
        'below': below,
        'roof': roof,
        'open_uses': open_uses,
        'high_sector': high_sector,
        'low_sector': low_sector,
        'blocks': blocks,
        'floor_count': floor_count,
        'main_dir': main_dir,
        'res_dir': res_dir,
        'svc_dir': svc_dir,
        'sea_dir': sea_dir,
        'has_residential': has_residential,
        'block_label': block_label,
    }


def _visual_concept_plan_distribution_spec(context, model, regulations):
    """The shared APPROVED DISTRIBUTION MODEL block — same shape the bench used."""
    name = _visual_concept_text(context.get('project_name'), 160) or 'the project'
    place = _visual_concept_plan_place_en(context)
    lines = [f"- Project: '{name}'" + (f' — {place}.' if place else '.')]

    points = context.get('boundary_points') or []
    parcel = (f'an irregular {len(points)}-vertex plot' if len(points) >= 3 else 'a plot')
    area = _visual_concept_plan_sanitize_text(context.get('land_area')
                                              or regulations.get('croquis_land_area'))
    if area:
        parcel += f' (~{area} m²)'
    lines.append(f'- Parcel: {parcel}. Where an outline reference image is attached it is the '
                 'TRUE surveyed parcel outline — trace it exactly, same vertices and '
                 'proportions. North is up.')

    edge_bits, neighbor_dirs = [], []
    sea_dir = model['sea_dir'] if model else ''
    for item in context.get('directions') or []:
        text = _visual_concept_plan_sanitize_text(item.get('regulation_text'))
        key = _visual_concept_plan_direction_key(item.get('direction'))
        if not text or not key:
            continue
        if re.search(r'neighbor|adjacent|propert|مجاور|جار', text, flags=re.IGNORECASE):
            neighbor_dirs.append(key)
            continue
        bit = f'{key} edge faces {_visual_concept_plan_edge_english(text)}'
        if key == sea_dir:
            bit += ' — this is the sea-frontage side'
        edge_bits.append(bit)
    if sea_dir:
        edge_bits.sort(key=lambda bit: 0 if bit.startswith(sea_dir + ' edge') else 1)
    if neighbor_dirs:
        edge_bits.append(' and '.join(neighbor_dirs) + ' edges touch neighboring plots')
    if edge_bits:
        lines.append('- Edges: ' + '; '.join(edge_bits) + '.')

    if model and model['high_sector'] and model['low_sector']:
        lines.append(
            f"- Two zoning zones: the {model['high_sector']['direction'].upper()} part is a "
            f"high-rise axis — the tall tower stands there; the "
            f"{model['low_sector']['direction'].upper()} part is low-rise, "
            f"max {model['low_sector']['cap']} floors.")

    setbacks = _visual_concept_plan_setback_en(_visual_concept_plan_sanitize_text(
        context.get('setbacks') or regulations.get('setbacks')
        or regulations.get('building_ratio_setbacks')))
    if setbacks:
        lines.append(f'- Setback envelope: {setbacks} — shown as a dashed inner line.')

    if model:
        tower_dir = model['high_sector']['direction'] if model['high_sector'] else ''
        if model.get('from_distribution'):
            tower = 'a mixed-use building'
        else:
            tower = (f"a {model['floor_count']}-storey mixed-use tower"
                     if model['floor_count'] else 'a mixed-use tower')
        if tower_dir:
            tower += f' on the {tower_dir} part'
        band_phrases = []
        last = len(model['bands']) - 1
        for position, band in enumerate(model['bands']):
            if len(band['items']) == 1 and position > 0:
                item = band['items'][0]
                bits = []
                if item.get('units') not in (None, ''):
                    units = str(item['units']).strip()
                    bits.append(f"{units} {'unit' if units in ('1', '1.0') else 'units'}")
                area = item.get('builtArea') or item.get('unitArea')
                if area not in (None, ''):
                    bits.append(f'{area} m²')
                briefs = '; '.join(bits)
            else:
                briefs = '; '.join(_visual_concept_plan_component_brief(i)
                                   for i in band['items'])
            article = 'an' if band['label'][:1].lower() in 'aeiou' else 'a'
            if position == 0:
                storey = f"{band['floors']}-storey " if band['floors'] else ''
                if model.get('from_distribution'):
                    noun = 'ground band'
                else:
                    noun = ('podium base' if len(model['bands']) > 1
                            and (band['floors'] or 0) <= 8 else 'base')
                phrase = f"{article} {storey}{band['label']} {noun}"
            elif position == last:
                phrase = f"{article} {band['label']} top band"
            else:
                phrase = f"{article} {band['label']} band"
            band_phrases.append(phrase + (f' ({briefs})' if briefs else ''))
        if band_phrases:
            tower += ' — ' + ', '.join(band_phrases[:-1]) + (
                f', and {band_phrases[-1]}' if len(band_phrases) > 1 else band_phrases[0])
        masses = [f'(1) {tower}']
        for index, block in enumerate(model.get('blocks') or [], 2):
            cap_text = f"{block['cap']}-storey " if block.get('cap') else 'low-rise '
            on_part = f" on the {block['direction']} part" if block.get('direction') else ''
            masses.append(f"({index}) a {cap_text}{block.get('use') or 'mixed-use'} "
                          f"'{block['label']}'{on_part}")
        if model.get('below'):
            masses.append(f"({len(masses) + 1}) multi-level basement parking across the parcel — "
                          'drawn only in the floor-distribution stack')
        lines.append('- Approved masses: ' + '; '.join(masses) + '.')
        open_bits = []
        if model['sea_dir']:
            open_bits.append(f"along the {model['sea_dir']} edge")
        block_labels = [block['label'] for block in model.get('blocks') or [] if block.get('label')]
        if block_labels:
            open_bits.append('around ' + ', '.join(f"the '{label}'" for label in block_labels))
        lines.append('- Open areas: landscaping '
                     + (' and '.join(open_bits) if open_bits
                        else 'on the remaining open ground inside the setback envelope') + '.')
        entries = []
        if model['main_dir']:
            entries.append(f"main lobby entry on the {model['main_dir']} side")
        if model['res_dir'] and model['svc_dir'] and model['svc_dir'] != model['res_dir']:
            entries.append(f"residential entry on the {model['res_dir']} street")
            entries.append(f"service entry on the {model['svc_dir']} street")
        elif model['res_dir']:
            entries.append(f"residential and service entries on the {model['res_dir']} street")
        elif model['main_dir']:
            entries.append('residential and service entries beside the main lobby entry')
        if entries:
            lines.append('- Entries: ' + '; '.join(entries) + '.')
    else:
        lines.append('- No approved building masses are recorded; keep the parcel a neutral '
                     'regulated-development field.')

    colors = '; '.join(f"{item['use']} = {item['color']}"
                       for item in context.get('colors') or [] if item.get('use'))
    if colors:
        lines.append(f'- FIXED color code, identical in every drawing: {colors}.')
    lines.append('- All text in the image English only. Bottom-right caption: '
                 "'ILLUSTRATIVE REFERENCE - NOT TO SCALE'.")
    return 'APPROVED DISTRIBUTION MODEL — render exactly this, invent nothing:\n' + '\n'.join(lines)


def _visual_concept_plan_site_body(context, model, regulations):
    parts = [
        "DRAWING REQUESTED — 'CONCEPTUAL SITE PLAN': a simplified flat 2D site plan, top-down "
        'orthographic view on a white background, same pastel style and fixed color code. The '
        'attached reference image is the TRUE surveyed parcel outline — trace it exactly, same '
        'vertices and proportions, as a dark navy outline. Inside it draw the dashed setback '
        'envelope, then the approved footprints: ']
    if model:
        high_dir = model['high_sector']['direction'] if model['high_sector'] else ''
        podium_color = model['bands'][0]['color'] if model['bands'] else 'soft-teal'
        crown_color = (model['bands'][-1]['color'] if model['bands'] else '') or 'soft-blue'
        # Same podium heuristic the spec uses: a short first band under a taller
        # stack is a podium base; otherwise the tower sits on the ground directly.
        # An approved-distribution model names no podium — its bands are floors.
        has_podium = (not model.get('from_distribution')
                      and len(model['bands']) > 1 and (model['bands'][0]['floors'] or 0) <= 8)
        building_name = next((str(item.get('building') or '')
                              for band in model['bands'] for item in band.get('items') or []
                              if item.get('building')), '')
        mass_label = _visual_concept_plan_building_en(building_name)
        if model.get('from_distribution'):
            footprints = [f"the building zone" + (f' on the {high_dir} part' if high_dir else '')
                          + f" ({(podium_color + ' ') if podium_color else ''}footprint "
                            f"labeled '{mass_label}')"]
        elif has_podium:
            footprints = [f"the podium+tower zone" + (f' on the {high_dir} part' if high_dir else '')
                          + f' ({podium_color} podium footprint with a smaller {crown_color} tower '
                            "footprint inside it labeled 'Tower')"]
        else:
            footprints = [f"the tower zone" + (f' on the {high_dir} part' if high_dir else '')
                          + f" ({crown_color} tower footprint labeled 'Tower')"]
        for block in model.get('blocks') or []:
            cap_text = f"{block['cap']}-storey " if block.get('cap') else ''
            on_part = f" on the {block['direction']} part" if block.get('direction') else ''
            footprints.append(f"the {cap_text}{block.get('color') or 'muted'} "
                              f"'{block['label']}' footprint{on_part}")
        footprints.append('pale-green landscaping filling the rest')
        if model.get('below'):
            pocket_dir = model['svc_dir'] or model['res_dir']
            footprints.append('a light-grey service/parking pocket'
                              + (f' on the {pocket_dir} part' if pocket_dir else ''))
        parts.append(', '.join(footprints) + '. ')
        entries = []
        if model['main_dir']:
            entries.append(f"'Main Entry' on the {model['main_dir']}")
        if model['res_dir']:
            entries.append(f"'Residential Entry' on the {model['res_dir']}")
        if model['svc_dir'] and model['svc_dir'] not in (model['main_dir'], model['res_dir']):
            entries.append(f"'Service Entry' on the {model['svc_dir']}")
        elif model['res_dir']:
            entries.append(f"'Service Entry' beside it")
        parts.append('Streets: label each recorded street and open-space strip on its edge with '
                     'its recorded name and width, each neighboring plot "Neighbor"'
                     + (', and a pale-cyan "Sea" band beyond the waterfront edge'
                        if model['sea_dir'] else '')
                     + '. Entry arrows: '
                     + ('; '.join(entries) if entries
                        else 'the recorded entries on their recorded edges')
                     + '. ')
    else:
        parts.append('keep the parcel a neutral regulated-development field — no approved '
                     'building masses are recorded, so draw no tower, podium, block, entry arrow, '
                     'or parking layout, and note "Approved building footprints not recorded." ')
    parts.append(
        'North arrow pointing up. Bottom-left legend with the fixed color chips plus "Parcel '
        'Boundary" and "Setback Envelope" line keys. Top-left title "CONCEPTUAL SITE PLAN". Flat '
        'cartographic style, muted colors, no photorealism, no satellite imagery. Only verified '
        'labels — no invented dimensions.')
    return ''.join(parts)


def _visual_concept_plan_uses_body(context, model, regulations):
    parts = [
        "DRAWING REQUESTED — 'VERTICAL PROGRAM DISTRIBUTION': a clean vertical stacked-floor "
        'diagram of the approved distribution on a white background, same pastel style and fixed '
        'color code. ']
    if model:
        stacks = []
        tower_bits = []
        below_count = len(model.get('below') or [])
        if below_count:
            tower_bits.append(f"{below_count} light-grey 'Basement Parking' level"
                              + ('s' if below_count > 1 else '')
                              + " below a dark navy 'Ground Level' line")
        else:
            tower_bits.append("a dark navy 'Ground Level' line at the base")
        for band in model['bands']:
            color = band['color'] or 'muted'
            count = band['floors']
            rng = _visual_concept_plan_floor_label_en(band['range'])
            if count and rng:
                tower_bits.append(f"{count} {color} '{band['label']} ({rng})' bands")
            else:
                tower_bits.append(f"{color} '{band['label']}' bands")
        if model['roof']:
            tower_bits.append("a thin grey 'Roof & Services' cap")
        if model.get('from_distribution'):
            tower_name = 'building'
        else:
            tower_name = (f"{model['floor_count']}-storey tower" if model['floor_count']
                          else 'mixed-use tower')
        stacks.append('Left stack — the ' + tower_name + ', bands bottom to top exactly: '
                      + ', '.join(tower_bits) + '.')
        for position, block in enumerate(model.get('blocks') or []):
            side = 'Right' if not position else f"Side stack {position + 1}"
            if block.get('bands'):
                block_bits = []
                for band in block['bands']:
                    band_text = (f"{band['floors']} {band['color'] or 'muted'} '{band['label']}"
                                 + (f" ({_visual_concept_plan_floor_label_en(band['range'])})'"
                                    if band.get('range') else "'")
                                 + ' bands')
                    block_bits.append(band_text)
                stacks.append(f"{side} stack — the '{block['label']}': "
                              + ', '.join(block_bits)
                              + ' above its own ground line.')
            else:
                cap = block.get('cap') or 0
                stacks.append(f"{side} stack — the {cap or 'low'}-storey '{block['label']}': "
                              f"{cap or 'several'} {block.get('color') or 'muted'} "
                              f"'{block.get('use') or block['label']} (G-{cap})' bands above the "
                              'same ground line'
                              + (' with its own light-grey parking band below' if below_count else '')
                              + '.')
        count_word = {1: 'ONE stack. ', 2: 'TWO stacks side by side. '}.get(
            len(stacks), f'{len(stacks)} stacks side by side. ')
        parts.append(count_word + ' '.join(stacks) + ' ')
    else:
        parts.append('No distribution is recorded; draw one generic stack per recorded component '
                     'with no labeled floors. ')
    parts.append(
        'English callout labels with dotted leader lines per band group. Bottom-left legend with '
        'the fixed color chips for the uses present. Top-left title "VERTICAL PROGRAM '
        'DISTRIBUTION". Flat infographic style, crisp readable English labels, no photorealism, '
        'no people, no furniture. Only the approved floor counts — no invented floors.')
    return ''.join(parts)


def _visual_concept_plan_massing_body(context, model, regulations):
    parts = [
        "DRAWING REQUESTED — 'CONCEPTUAL MASSING': a clean conceptual 3D massing diagram in a "
        'flat pastel architectural style on a white background. Isometric view from a high '
        'corner' + (
            f", rotated so the {model['main_dir']} edge faces front-left"
            if model and model['main_dir'] else '')
        + '. The attached reference image is the TRUE surveyed parcel outline — the parcel plate '
        'must match its exact shape and proportions. ']
    if model:
        high_dir = model['high_sector']['direction'] if model['high_sector'] else ''
        tiers = []
        last = len(model['bands']) - 1
        for position, band in enumerate(model['bands']):
            color = band['color'] or 'muted'
            noun = _VISUAL_PLAN_USE_LABEL.get(band['category'], 'Amenities').lower()
            if position == 0:
                storey = f"{band['floors']}-storey " if band['floors'] else ''
                if model.get('from_distribution'):
                    base_noun = 'ground band'
                else:
                    base_noun = ('podium base' if len(model['bands']) > 1
                                 and (band['floors'] or 0) <= 8 else 'base')
                tiers.append(f'{color} {storey}{base_noun}')
            elif position == last:
                tiers.append(f'{color} {noun} crown')
            else:
                tiers.append(f'{color} {noun} band')
        if model.get('from_distribution'):
            tower_name = 'building'
        else:
            tower_name = (f"{model['floor_count']}-storey tower" if model['floor_count'] else 'tower')
        parts.append(
            'On it, extrude only the approved masses as simple matte boxes with thin white '
            'horizontal floor lines and dark navy outlines: the ' + tower_name
            + (f' on the {high_dir} part' if high_dir else '')
            + ', shown as one volume banded by use (' + ', '.join(tiers) + ')')
        for block in model.get('blocks') or []:
            cap_text = f"{block['cap']}-storey " if block.get('cap') else 'low '
            on_part = f" on the {block['direction']} part" if block.get('direction') else ''
            parts.append(f" plus the separate {cap_text}{block.get('color') or 'muted'} "
                         f"'{block['label']}'{on_part}")
        parts.append('. Pale-green landscaping with round trees fills the open areas')
        if model['sea_dir']:
            parts.append(f"; a pale-cyan 'Sea' band runs beyond the {model['sea_dir']} edge")
        callouts = [band['label'] + (' Podium' if i == 0 and not model.get('from_distribution')
                                     and len(model['bands']) > 1
                                     and (band['floors'] or 0) <= 8 else '')
                    for i, band in enumerate(model['bands'])]
        callouts += [block['label'] for block in model.get('blocks') or [] if block.get('label')]
        parts.append('. English callout labels on dotted leader lines: '
                     + ', '.join(f"'{label}'" for label in callouts)
                     + '. Edge labels: each recorded street and neighbor named with its '
                     'recorded name and width. ')
    else:
        parts.append('No approved masses are recorded — do not extrude speculative volumes; show '
                     'a restrained dashed development field labeled "Approved building footprints '
                     'not recorded." ')
    parts.append(
        'Bottom-left legend with the fixed color chips. Top-left title "CONCEPTUAL MASSING". Flat '
        'vector look, muted pastel palette, dark navy text, no photorealism, no people, no cars, '
        'no shadows. Do not add room detail, furniture, facades or any element not in the '
        'approved model.')
    return ''.join(parts)


def _visual_concept_plan_drawing_prompt(kind, context, model=None):
    context = context if isinstance(context, dict) else {}
    regulations = context.get('regulations') if isinstance(context.get('regulations'), dict) else {}
    if model is None:
        model = _visual_concept_plan_model(context, regulations)
    spec = _visual_concept_plan_distribution_spec(context, model, regulations)
    body = {
        'site': _visual_concept_plan_site_body,
        'uses': _visual_concept_plan_uses_body,
        'massing': _visual_concept_plan_massing_body,
    }.get(kind, _visual_concept_plan_massing_body)(context, model, regulations)
    return (_visual_concept_plan_prompt_header(kind, context) + spec + '\n' + body)


def _visual_concept_plan_prompt_templates(context, model=None):
    return {
        definition['kind']: _visual_concept_plan_drawing_prompt(definition['kind'], context, model=model)
        for definition in VISUAL_CONCEPT_PLAN_DEFINITIONS
    }


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


def _visual_concept_plan_floor_range(text):
    """Parse an approved-table floor cell: 'G', 'B1-B3', '5-12', 'Roof' into
    {kind, lo, hi, count}. Basement lo/hi are negative; ground lo=hi=0; a lone
    mezzanine/مسروق sits at 0.5 — a slab inside the ground level, so it never
    collides with plain «أرضي» yet still overlaps a range that spans it."""
    value = str(text or '').strip()
    if not value:
        return None
    lowered = value.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).lower()
    if re.search(r'roof|سطح|روف|ملحق|ملاحق', lowered):
        return {'kind': 'roof', 'lo': 0, 'hi': 0, 'count': 1}
    if re.search(r'\bb\s*\d|basement|بدروم|قبو|سرداب|تحت\s*الأرض', lowered):
        digits = [int(d) for d in re.findall(r'\d+', lowered)]
        count = max(digits) if digits else 1
        return {'kind': 'basement', 'lo': -count, 'hi': -1, 'count': count}
    numbers = [int(d) for d in re.findall(r'\d+', lowered)]
    if not numbers:
        ordinals = {'اول': 1, 'ثاني': 2, 'ثالث': 3, 'رابع': 4, 'خامس': 5,
                    'سادس': 6, 'سابع': 7, 'ثامن': 8, 'تاسع': 9, 'عاشر': 10}
        found = [ordinals.get(_visual_concept_plan_component_key(token) or '')
                 for token in re.split(r'[-–—]', value)]
        numbers = [n for n in found if n]
    mezzanine = bool(re.search(r'ميزانين|mezzanine|مسروق', lowered))
    ground = bool(re.search(r'\bg\b|ground|أرضي|الارضي|الأرضي', lowered))
    if mezzanine and not ground:
        return {'kind': 'mezzanine', 'lo': 0.5, 'hi': 0.5, 'count': 1}
    if not numbers:
        return {'kind': 'ground', 'lo': 0, 'hi': 0, 'count': 1} if ground else None
    lo, hi = (0, numbers[-1]) if ground else (numbers[0], numbers[-1])
    return {'kind': 'range', 'lo': lo, 'hi': hi, 'count': max(1, hi - lo + 1)}


_VISUAL_PLAN_FLOOR_LABEL_AR = {
    'g': 'أرضي', 'gf': 'أرضي', 'ground': 'أرضي', 'ground floor': 'أرضي',
    'm': 'ميزانين', 'mezzanine': 'ميزانين', 'mezz': 'ميزانين',
    'roof': 'ملحق علوي', 'rooftop': 'ملحق علوي', 'r': 'ملحق علوي',
    'podium': 'بوديوم', 'basement': 'بدروم', 'b': 'بدروم',
}


def _visual_concept_plan_floor_label(text):
    """Display label for a floor cell: Latin tokens the model emits (G, M,
    B1-B3, Roof) become the Arabic names the client actually reads. Ranges and
    already-Arabic labels pass through."""
    value = str(text or '').strip()
    if not value:
        return value
    lowered = value.casefold()
    if lowered in _VISUAL_PLAN_FLOOR_LABEL_AR:
        return _VISUAL_PLAN_FLOOR_LABEL_AR[lowered]
    basement = re.fullmatch(r'b\s*(\d+)(?:\s*-\s*b?\s*(\d+))?', lowered)
    if basement:
        start, end = basement.group(1), basement.group(2)
        return f'بدروم {start}' + (f'-{end}' if end else '')
    return value


def _visual_concept_plan_component_key(name):
    """Match key for component names — unifies hamza/taa/ya variants and drops
    word-initial «ال» so «طابق أرضي - سكني» matches «الطابق الأرضي سكني»."""
    text = str(name or '').translate(
        str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).casefold()
    text = re.sub(r'[أإآٱ]', 'ا', text).replace('ى', 'ي').replace('ة', 'ه')
    text = text.replace('ـ', '')
    text = re.sub(r'(?<!\w)ال', '', text)
    return re.sub(r'[^\w\u0600-\u06FF]+', '', text)


def _visual_concept_plan_component_base(name):
    """Component name without a leading floor tag: «طابق أرضي - سكني» resolves to
    «سكني» and «ملحق علوي - خدمات أخرى» to «خدمات أخرى», so the study's
    per-floor rows and the distribution's per-use rows compare like for like.
    Names without a dash tag pass through unchanged."""
    text = _visual_concept_plan_sanitize_text(name)
    stripped = re.sub(
        r'^(?:ال)?(?:طابق|دور|ملحق|بدروم|سطح|floor|level|basement|roof)\s+[^-–—:]*[-–—:]\s*',
        '', text).strip()
    return stripped or text


def _visual_concept_plan_distribution_totals(rows, context):
    """Per-component totals from the distribution table, each matched against the
    required figure recorded in the project components / financial study rows.
    Both sides group on the base component name, so the study's per-floor rows
    («طابق أرضي - سكني» …) aggregate to the whole-component figure before the
    comparison instead of matching only the first floor's row."""
    groups = {}
    order = []
    for row in rows:
        name = _visual_concept_plan_sanitize_text(row.get('component')) or 'غير محدد'
        base = _visual_concept_plan_component_base(name)
        key = _visual_concept_plan_component_key(base) or _visual_concept_plan_component_key(name) or name
        if key not in groups:
            groups[key] = {'component': base, 'units': 0.0, 'area': 0.0,
                           'has_units': False, 'has_area': False}
            order.append(key)
        parsed = _visual_concept_plan_floor_range(row.get('floor_range'))
        count = parsed['count'] if parsed else 1
        units = row.get('units_per_floor')
        area = row.get('floor_area_sqm')
        if isinstance(units, (int, float)):
            groups[key]['units'] += units * count
            groups[key]['has_units'] = True
        if isinstance(area, (int, float)):
            groups[key]['area'] += area * count
            groups[key]['has_area'] = True
    required = []
    for comp in context.get('components') or []:
        comp_name = _visual_concept_plan_sanitize_text(comp.get('name'))
        required.append({
            'key': _visual_concept_plan_component_key(comp_name),
            'base_key': _visual_concept_plan_component_key(
                _visual_concept_plan_component_base(comp_name)),
            'component': _visual_concept_plan_component_base(comp_name) or comp_name,
            'required_units': comp.get('units'),
            'required_area': comp.get('builtArea') or comp.get('unitArea'),
        })

    def match_rank(item, key):
        if item['key'] == key or item['base_key'] == key:
            return 0
        if item['key'] and (item['key'] in key or key in item['key']):
            return 1
        if item['base_key'] and (item['base_key'] in key or key in item['base_key']):
            return 2
        return None

    matched = {key: [] for key in order}
    leftovers = []
    for item in required:
        if not (item['key'] or item['base_key']):
            continue
        best_key = best_rank = None
        for key in order:
            rank = match_rank(item, key)
            if rank is not None and (best_rank is None or rank < best_rank
                                     or (rank == best_rank and len(key) > len(best_key or ''))):
                best_key, best_rank = key, rank
        if best_key is None:
            leftovers.append(item)
        else:
            matched[best_key].append(item)

    def summed(field, items):
        numbers = [item[field] for item in items if isinstance(item[field], (int, float))]
        return round(sum(numbers), 2) if numbers else None

    totals = []
    for key in order:
        entry = groups[key]
        total = {
            'component': entry['component'],
            'units': round(entry['units'], 2) if entry['has_units'] else None,
            'area': round(entry['area'], 2) if entry['has_area'] else None,
            'required_units': summed('required_units', matched[key]),
            'required_area': summed('required_area', matched[key]),
        }
        for pair in (('units', 'required_units', 'delta_units'),
                     ('area', 'required_area', 'delta_area')):
            value, wanted = total[pair[0]], total[pair[1]]
            total[pair[2]] = (round(value - wanted, 2)
                              if isinstance(value, (int, float)) and isinstance(wanted, (int, float))
                              else None)
        totals.append(total)
    merged = {}
    merged_order = []
    for item in leftovers:
        group_key = item['base_key'] or item['key'] or item['component']
        if group_key not in merged:
            merged[group_key] = {'component': item['component'], 'items': []}
            merged_order.append(group_key)
        merged[group_key]['items'].append(item)
    for group_key in merged_order:
        entry = merged[group_key]
        req_units = summed('required_units', entry['items'])
        req_area = summed('required_area', entry['items'])
        totals.append({'component': entry['component'], 'units': 0, 'area': 0,
                       'required_units': req_units, 'required_area': req_area,
                       'delta_units': -req_units if isinstance(req_units, (int, float)) else None,
                       'delta_area': -req_area if isinstance(req_area, (int, float)) else None})
    return totals


def _visual_concept_plan_distribution_checks(rows, totals, context, regulations):
    """Deterministic re-check of an (edited) distribution table — instant, no model:
    floor-range overlaps per building, height caps, coverage footprint, and the
    per-component deltas against the recorded program."""
    checks = []
    by_building = {}
    ids_by_component = {}
    parsed_rows = []
    for row in rows:
        parsed = _visual_concept_plan_floor_range(row.get('floor_range'))
        parsed_rows.append((row, parsed))
        row_key = _visual_concept_plan_component_key(
            _visual_concept_plan_component_base(row.get('component')))
        if row_key:
            ids_by_component.setdefault(row_key, []).append(row.get('id'))
        if not parsed or parsed['kind'] in ('basement', 'roof'):
            continue
        building = _visual_concept_plan_sanitize_text(row.get('building')) or 'المبنى الرئيسي'
        by_building.setdefault(building, []).append((parsed, row))
    for building, entries in by_building.items():
        # Hard conflict only when the SAME component claims overlapping ranges —
        # different components sharing a floor is normal mixed use, so it is a
        # soft "confirm the share" note instead of a blocker.
        by_component = {}
        for parsed, row in entries:
            key = _visual_concept_plan_component_key(
                _visual_concept_plan_component_base(row.get('component')))
            if key:
                by_component.setdefault(key, []).append((parsed, row))
        for comp_entries in by_component.values():
            ordered = sorted(comp_entries, key=lambda item: item[0]['lo'])
            for (first, row_a), (second, row_b) in zip(ordered, ordered[1:]):
                if second['lo'] <= first['hi']:
                    checks.append({
                        'item': f'نطاقان متداخلان لمكوّن واحد — {building}',
                        'detail': (f'«{row_a.get("component") or "مكوّن"}» مسجل على «{row_a.get("floor_range")}» '
                                   f'و«{row_b.get("floor_range")}» — ادمج الصفين أو عدّل النطاق'),
                        'result': 'متعارض', 'severity': 'high',
                        'row_ids': [row_a.get('id'), row_b.get('id')]})

    cap = _visual_concept_number(regulations.get('max_floors_height') or regulations.get('table_floors'))
    if cap:
        for row, parsed in parsed_rows:
            if parsed and parsed['kind'] == 'range' and parsed['hi'] > cap:
                checks.append({
                    'item': 'تجاوز سقف الأدوار الموثق',
                    'detail': f'«{row.get("component") or "مكون"}» ({row.get("floor_range")}) يتجاوز الحد {cap}',
                    'result': 'متعارض', 'severity': 'high', 'row_ids': [row.get('id')]})
    land = _visual_concept_number(context.get('land_area') or regulations.get('croquis_land_area'))
    coverage = _visual_concept_number(context.get('coverage_ratio') or regulations.get('coverage_ratio')
                                      or regulations.get('building_ratio_coverage'))
    if land and coverage:
        ratio = coverage / 100 if coverage > 1.5 else coverage
        footprint_cap = land * ratio
        for row, _parsed in parsed_rows:
            area = row.get('floor_area_sqm')
            if isinstance(area, (int, float)) and area > footprint_cap * 1.02:
                checks.append({
                    'item': 'مساحة الدور تتجاوز حد التغطية',
                    'detail': f'«{row.get("component") or "مكون"}» {area:g} م² والحد التقريبي {footprint_cap:g} م²',
                    'result': 'يحتاج تأكيد', 'severity': 'medium', 'row_ids': [row.get('id')]})
    far = _visual_concept_number(regulations.get('floor_area_ratio'))
    if not far:
        far_match = re.search(r'معامل[^\d]{0,15}(\d+(?:[.,]\d+)?)',
                              str(regulations.get('zone_rules') or '') + ' ' +
                              str(regulations.get('building_ratio') or ''))
        far = _visual_concept_number(far_match.group(1)) if far_match else None
    if land and far:
        total_built = sum(
            row.get('floor_area_sqm') * (parsed['count'] if parsed else 1)
            for row, parsed in parsed_rows
            if isinstance(row.get('floor_area_sqm'), (int, float))
            and (not parsed or parsed['kind'] != 'basement'))
        cap_area = land * far
        if total_built > cap_area * 1.02:
            checks.append({
                'item': 'إجمالي المسطحات يتجاوز معامل البناء',
                'detail': (f'مجموع مساحات الأدوار {total_built:g} م² يتجاوز حد المعامل '
                           f'{cap_area:g} م² ({far:g} × أرض {land:g} م²) — قلّل مساحات الأدوار'),
                'result': 'يحتاج تأكيد', 'severity': 'medium',
                'row_ids': [row.get('id') for row, parsed in parsed_rows
                            if isinstance(row.get('floor_area_sqm'), (int, float))
                            and (not parsed or parsed['kind'] != 'basement')]})
    for total in totals:
        for delta_key, label in (('delta_units', 'الوحدات'), ('delta_area', 'المساحة')):
            delta = total.get(delta_key)
            required_key = 'required_units' if delta_key == 'delta_units' else 'required_area'
            wanted = total.get(required_key)
            if isinstance(delta, (int, float)) and isinstance(wanted, (int, float)) and wanted:
                if abs(delta) > max(1.0, abs(wanted) * 0.1):
                    checks.append({
                        'item': f'فرق {label} — {total["component"]}',
                        'detail': f'التوزيع {total[delta_key.replace("delta_", "")]:g} مقابل المطلوب {wanted:g}',
                        'result': 'يحتاج تأكيد', 'severity': 'medium',
                        'row_ids': ids_by_component.get(
                            _visual_concept_plan_component_key(total['component']), [])})
    return checks


def _visual_concept_plan_normalize_distribution(raw, context, regulations):
    """Normalize the distribution table (proposed or client-edited) and attach the
    deterministic totals + checks so every edit re-verifies the same way."""
    source = raw if isinstance(raw, dict) else {}
    rows = []
    for item in (source.get('rows') if isinstance(source.get('rows'), list) else []):
        if not isinstance(item, dict):
            continue
        component = _visual_concept_plan_sanitize_text(
            item.get('component') or item.get('use') or item.get('name'))
        building = _visual_concept_plan_sanitize_text(item.get('building') or item.get('mass'))
        floor_range = _visual_concept_plan_floor_label(
            _visual_concept_plan_sanitize_text(
                item.get('floor_range') or item.get('floors') or item.get('range')))
        if not (component or building or floor_range):
            continue
        rows.append({
            'id': _visual_concept_plan_sanitize_text(item.get('id'))[:40] or f'row_{len(rows) + 1}',
            'building': building[:160],
            'floor_range': floor_range[:80],
            'component': component[:160],
            'units_per_floor': _visual_concept_number(item.get('units_per_floor') or item.get('units')),
            'floor_area_sqm': _visual_concept_number(item.get('floor_area_sqm') or item.get('floor_area')),
            'circulation': _visual_concept_plan_sanitize_text(
                item.get('circulation') or item.get('services'))[:400],
        })
        if len(rows) >= 60:
            break
    totals = _visual_concept_plan_distribution_totals(rows, context)
    return {
        'rows': rows,
        'totals': totals,
        'checks': _visual_concept_plan_distribution_checks(rows, totals, context, regulations),
        'issues': _visual_concept_plan_normalize_issues(source.get('issues') or []),
        'approved': False,
    }



def _visual_concept_plan_fallback_distribution(context, regulations):
    """No-model proposal: flatten the inferred plan model into table rows so the
    client still gets an editable starting point when the text call fails."""
    model = _visual_concept_plan_model(context, regulations)
    rows = []
    if model:
        for band in model.get('bands') or []:
            names = '، '.join(_visual_concept_plan_sanitize_text(item.get('name'))
                              for item in band.get('items') or [] if item.get('name'))
            floors = band.get('floors') or 1
            units = sum(item['units'] for item in band.get('items') or []
                        if isinstance(item.get('units'), (int, float)))
            area = sum(item['builtArea'] for item in band.get('items') or []
                       if isinstance(item.get('builtArea'), (int, float)))
            rows.append({
                'building': 'المبنى الرئيسي', 'floor_range': band.get('range') or '',
                'component': names or band.get('label') or '',
                'units_per_floor': round(units / floors, 2) if units else None,
                'floor_area_sqm': round(area / floors, 2) if area else None,
                'circulation': ''})
        for block in model.get('blocks') or []:
            rows.append({
                'building': block.get('label') or 'مبنى ثانٍ', 'floor_range': f"1-{block.get('cap') or 1}",
                'component': block.get('use') or '', 'units_per_floor': None,
                'floor_area_sqm': None, 'circulation': ''})
        if model.get('below'):
            rows.append({'building': 'المبنى الرئيسي', 'floor_range': 'B1',
                         'component': 'مواقف سيارات', 'units_per_floor': None,
                         'floor_area_sqm': None, 'circulation': 'اتصال رأسي بالمبنى'})
        if model.get('roof'):
            rows.append({'building': 'المبنى الرئيسي', 'floor_range': 'Roof',
                         'component': 'خدمات وسطح', 'units_per_floor': None,
                         'floor_area_sqm': None, 'circulation': ''})
    return {'rows': rows, 'notes': ['توزيع آلي أولي من البيانات المعتمدة — يحتاج مراجعة.']}


def _visual_concept_plan_model_from_distribution(distribution, context, regulations):
    """Build the shared plan model from the CLIENT-APPROVED distribution table
    instead of the inferred banding. Returns None when no usable rows exist so
    callers can fall back to the inferred model."""
    raw_rows = (distribution or {}).get('rows')
    rows = [row for row in raw_rows or [] if isinstance(row, dict)
            and (str(row.get('component') or '').strip() or str(row.get('floor_range') or '').strip())]
    if not rows:
        return None

    def parsed_of(row):
        return _visual_concept_plan_floor_range(row.get('floor_range'))

    def top_floor(group_rows):
        top = 0
        for row in group_rows:
            parsed = parsed_of(row)
            if parsed and parsed['kind'] not in ('basement', 'roof'):
                top = max(top, parsed['hi'])
        return int(-(-top // 1)) if top else 0

    def band_for(row):
        parsed = parsed_of(row) or {'kind': 'range', 'lo': 0, 'hi': 0, 'count': 1}
        component = _visual_concept_plan_sanitize_text(row.get('component'))
        _order, category = _visual_concept_plan_use_category({'name': component})
        count = parsed['count']
        units = row.get('units_per_floor')
        area = row.get('floor_area_sqm')
        label = _visual_concept_plan_component_en(component)
        if not label or re.search(r'[\u0600-\u06FF]', label):
            label = _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')
        return {
            'category': category,
            'label': label,
            'items': [{
                'name': component,
                'units': (units * count) if isinstance(units, (int, float)) else units,
                'builtArea': (area * count) if isinstance(area, (int, float)) else area,
                'floorRange': _visual_concept_plan_sanitize_text(row.get('floor_range')),
                'building': _visual_concept_plan_sanitize_text(row.get('building')),
                'notes': _visual_concept_plan_sanitize_text(row.get('circulation')),
            }],
            'floors': count,
            'range': _visual_concept_plan_sanitize_text(row.get('floor_range')),
            'color': _visual_concept_plan_use_color(
                context, _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities')),
            'kind': parsed['kind'],
        }

    buildings, by_key = [], {}
    for row in rows:
        name = _visual_concept_plan_sanitize_text(row.get('building')) or 'المبنى الرئيسي'
        key = name.casefold()
        if key not in by_key:
            by_key[key] = len(buildings)
            buildings.append({'name': name, 'rows': []})
        buildings[by_key[key]]['rows'].append(row)
    tower = max(buildings, key=lambda group: top_floor(group['rows']))
    secondaries = [group for group in buildings if group is not tower]

    def sort_bands(bands):
        return sorted(bands, key=lambda band: (
            parsed_of({'floor_range': band['range']}) or {'lo': 0})['lo'])

    bands, below, roof, open_uses = [], [], [], []
    for row in tower['rows']:
        band = band_for(row)
        if band['kind'] == 'basement' or band['category'] == 'parking':
            below.append(band)
        elif band['kind'] == 'roof' or band['category'] == 'service':
            roof.append(band)
        elif band['category'] == 'landscape':
            open_uses.append(band)
        else:
            bands.append(band)
    bands = sort_bands(bands)
    blocks = []
    for index, group in enumerate(secondaries):
        block_bands = []
        for row in group['rows']:
            band = band_for(row)
            if band['kind'] == 'basement' or band['category'] == 'parking':
                below.append(band)
            elif band['kind'] == 'roof' or band['category'] == 'service':
                roof.append(band)
            elif band['category'] == 'landscape':
                open_uses.append(band)
            else:
                block_bands.append(band)
        block_bands = sort_bands(block_bands)
        label_en = _visual_concept_plan_component_en(group['name'])
        if not label_en or re.search(r'[\u0600-\u06FF]', label_en):
            label_en = (block_bands[0]['label'] if block_bands
                        else f'Block {chr(66 + index)}')
        category = block_bands[0]['category'] if block_bands else 'amenity'
        blocks.append({
            'label': label_en,
            'cap': top_floor(group['rows']) or sum(b['floors'] for b in block_bands),
            'direction': _visual_concept_plan_direction_key(group['name']) or '',
            'use': _VISUAL_PLAN_USE_LABEL.get(category, 'Amenities'),
            'color': (block_bands[0]['color'] if block_bands
                      else _visual_concept_plan_use_color(context, 'Amenities')),
            'bands': block_bands,
        })

    hints = _visual_concept_plan_sector_hints(regulations)
    capped = [hint for hint in hints if hint.get('cap')]
    low_sector = min(capped, key=lambda hint: hint['cap']) if capped else None
    explicit_open = [hint for hint in hints
                     if hint.get('uncapped') and hint is not low_sector]
    open_hints = [hint for hint in hints
                  if not hint.get('cap') and hint is not low_sector]
    high_sector = (explicit_open or open_hints or [None])[0]
    street_dirs, _other_dirs, sea_dir = _visual_concept_plan_direction_scan(context)
    main_dir, res_dir, svc_dir = _visual_concept_plan_entry_dirs(street_dirs, sea_dir, high_sector)
    all_bands = bands + [band for block in blocks for band in block['bands']]
    return {
        'bands': bands,
        'below': below,
        'roof': roof,
        'open_uses': open_uses,
        'high_sector': high_sector,
        'low_sector': low_sector,
        'blocks': blocks,
        'floor_count': top_floor(tower['rows']),
        'main_dir': main_dir,
        'res_dir': res_dir,
        'svc_dir': svc_dir,
        'sea_dir': sea_dir,
        'has_residential': any(band['category'] == 'residential' for band in all_bands),
        'block_label': blocks[0]['label'] if blocks else 'Low Block',
        'from_distribution': True,
    }


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
