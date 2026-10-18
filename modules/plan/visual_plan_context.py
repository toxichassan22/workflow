import json
import re

import plot_shape
from visual_plan_geometry import DIRECTION_VECTORS, PlanGeometryError, boundary_geometry, finite_number


DIRECTION_WORDS = {
    'north': r'(?:الشمال(?:ي(?:ة|ه)?)?|شمال(?:ي(?:ة|ه)?)?|\bnorth(?:ern)?\b)',
    'south': r'(?:الجنوب(?:ي(?:ة|ه)?)?|جنوب(?:ي(?:ة|ه)?)?|\bsouth(?:ern)?\b)',
    'east': r'(?:الشرق(?:ي(?:ة|ه)?)?|شرق(?:ي(?:ة|ه)?)?|\beast(?:ern)?\b)',
    'west': r'(?:الغرب(?:ي(?:ة|ه)?)?|غرب(?:ي(?:ة|ه)?)?|\bwest(?:ern)?\b)',
}
_DIRECTION_WORD = r'(?:' + '|'.join(DIRECTION_WORDS.values()) + r')'
MAIN_FRONTAGE = (r'(?:الواجه[ةه]\s*(?:' + _DIRECTION_WORD + r'\s+)?(?:الرئيسي[ةه]|الاساسي[ةه]|الأساسي[ةه])'
                 r'|المدخل\s*الرئيسي|(?:main|primary|principal)\s+(?:facade|frontage|entrance|entry))')
OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
LEFT = {'north': 'west', 'south': 'east', 'east': 'north', 'west': 'south'}


def parsed(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return value if value is not None else default


def text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value or '').strip()


def direction_key(value):
    candidate = text(value).lower().strip()
    return next((key for key, pattern in DIRECTION_WORDS.items()
                 if re.fullmatch(pattern, candidate, re.IGNORECASE)), '')


def stated_direction(value):
    """A recorded direction field: an exact direction word, or a short phrase
    containing exactly one direction. More than one direction stays unresolved."""
    candidate = text(value)
    key = direction_key(candidate)
    if key:
        return key
    found = list(dict.fromkeys(
        key for key, pattern in DIRECTION_WORDS.items()
        if re.search(pattern, candidate, re.IGNORECASE)))
    return found[0] if len(found) == 1 else ''


def first_value(holders, *keys):
    return next((holder[key] for holder in holders if isinstance(holder, dict)
                 for key in keys if holder.get(key) not in (None, '', [], {})), '')


def direction_rows(project, analysis, parcel):
    raw = parsed(first_value((project, analysis, parcel), 'directions_table', 'directions'), [])
    if isinstance(raw, dict):
        raw = [{'direction': key, **(value if isinstance(value, dict) else {'regulation_text': value})}
               for key, value in raw.items()]
    rows = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        direction = direction_key(item.get('direction') or item.get('label'))
        if not direction:
            continue
        prose = text(item.get('regulation_text') or item.get('regulation') or item.get('text'))
        street_name = text(item.get('street_name') or item.get('streetName'))
        width = finite_number(item.get('street_width_m') or item.get('street_width'))
        description = ' '.join(filter(None, (prose, street_name, text(item.get('uses')), text(item.get('notes')))))
        street = bool(street_name or width is not None or re.search(
            r'\bstreet\b|\broad\b|corniche|شارع|طريق|كورنيش', description, re.IGNORECASE))
        if re.search(r'no\s+(?:street|road)|ليس\s*شارع|لا\s*يوجد\s*شارع', description, re.IGNORECASE):
            street = False
        rows.append({'direction': direction, 'description': description, 'streetName': street_name,
                     'streetWidth': width, 'street': street,
                     'setback': text(item.get('setback') if item.get('setback') is not None else item.get('setback_m')),
                     'boundaryLength': plot_shape.row_length(item)})
    return rows


def primary_frontage(summary, constraints, rows, facade_directions='', main_direction=''):
    candidates = []
    for prose in (summary, constraints):
        for fragment in re.split(r'[\n.;؛]', text(prose)):
            marker = re.search(MAIN_FRONTAGE, fragment, re.IGNORECASE)
            if not marker or re.search(r'\bnot\b|ليست|ليس|غير\s*الرئيسي', fragment, re.IGNORECASE):
                continue
            found = [(key, match.start(), match.end()) for key, pattern in DIRECTION_WORDS.items()
                     for match in re.finditer(pattern, fragment, re.IGNORECASE)]
            after = [item for item in found if marker.start() <= item[1] <= marker.end() + 55]
            before = [item for item in found if marker.start() - 30 <= item[2] <= marker.start()]
            nearest = min(after, key=lambda item: item[1]) if after else (
                max(before, key=lambda item: item[2]) if before else None)
            if nearest:
                candidates.append((nearest[0], fragment.strip()))
    for row in rows:
        if row['street'] and re.search(MAIN_FRONTAGE + r'|(?:main|primary)\s+(?:street|road)|شارع\s*رئيسي',
                                      row['description'], re.IGNORECASE):
            candidates.append((row['direction'], row['description']))
    streets = list(dict.fromkeys(row['direction'] for row in rows if row['street']))
    stated_facades = list(dict.fromkeys(key for key, pattern in DIRECTION_WORDS.items()
                                       if re.search(pattern, text(facade_directions), re.IGNORECASE)))
    streets = streets or stated_facades
    directions = list(dict.fromkeys(item[0] for item in candidates))
    stated_main = stated_direction(main_direction)
    if stated_main:
        if streets and stated_main not in streets:
            return {'direction': '', 'status': 'conflicting',
                    'evidence': [item[1] for item in candidates] + [text(main_direction)]}
        evidence = [item[1] for item in candidates if item[0] == stated_main] or [text(main_direction)]
        return {'direction': stated_main, 'status': 'recorded', 'evidence': evidence}
    if len(directions) > 1:
        return {'direction': '', 'status': 'conflicting', 'evidence': [item[1] for item in candidates]}
    if directions:
        if streets and directions[0] not in streets:
            return {'direction': '', 'status': 'conflicting', 'evidence': [item[1] for item in candidates]}
        return {'direction': directions[0], 'status': 'recorded', 'evidence': [item[1] for item in candidates]}
    if len(streets) == 1:
        return {'direction': streets[0], 'status': 'single_frontage',
                'evidence': [row['description'] for row in rows if row['direction'] == streets[0]] or [text(facade_directions)]}
    return {'direction': '', 'status': 'unresolved', 'evidence': []}


def meter_value(value):
    numeric = finite_number(value)
    if numeric is not None:
        return numeric if numeric >= 0 else None
    source = text(value).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    if re.search(r'\d\s*/\s*\d|نسبة|حسب|بحسب|وفق|depending|if\b|where\b', source, re.IGNORECASE):
        return None
    match = re.search(r'(?<![\d.])(\d+(?:[.,]\d+)?)\s*(?:متر|م\b|met(?:er|re)s?\b|m\b)', source, re.IGNORECASE)
    if not match:
        match = re.search(r'(?<![\d.])(\d+(?:[.,]\d+)?)(?!\s*%)', source, re.IGNORECASE)
    return finite_number(match.group(1)) if match else None


def recorded_setbacks(source, rows, frontage):
    setbacks = {row['direction']: meter_value(row['setback']) for row in rows if row.get('setback')}
    prose = text(source).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    labels = dict(DIRECTION_WORDS)
    if frontage:
        labels[frontage] += r'|(?:الأمامي|الامامي|أمامي|امامي|\bfront\b)'
        labels[OPPOSITE[frontage]] += r'|(?:الخلفي|خلفي|\brear\b|\bback\b)'
    pattern = (r'[;؛\n|,،]|\s+(?:و\s*)?(?:عدا|باستثناء|ما عدا|إلا|أما|لكن)\s*'
               r'|\s+(?:و\s*|و(?=[^\s]))(?=(?:\d+|[٠-٩]+)|(?:الشارع|الواجهة|الحد|جهة|(?:ال)?(?:شمال|جنوب|شرق|غرب)(?:ي|ية)?)\s*(?:ال\w+\s+)?(?:\d+|[٠-٩]+))')
    fragments = [part.strip() for part in re.split(pattern, prose) if part and part.strip()]
    general_keys = set()
    for fragment in fragments:
        value = meter_value(fragment)
        if value is None:
            continue
        keys = [key for key, pattern_dir in labels.items() if re.search(pattern_dir, fragment, re.IGNORECASE)]
        is_general = bool(re.search(r'كل\s*(?:الجهات|الجوانب)|جميع\s*(?:الجهات|الجوانب)|all\s*(?:sides|edges)', fragment, re.IGNORECASE))
        if is_general:
            keys = list(DIRECTION_VECTORS)
            general_keys.update(keys)
        elif frontage and re.search(r'الجانبي|جانبي|\bside\b', fragment, re.IGNORECASE):
            keys += [LEFT[frontage], OPPOSITE[LEFT[frontage]]]
        for key in keys:
            existing = setbacks.get(key)
            if existing is not None and abs(existing - value) > 1e-7:
                if key in general_keys and not is_general:
                    setbacks[key] = value
                    continue
                if any(row.get('direction') == key and meter_value(row.get('setback')) is not None for row in rows) and is_general:
                    continue
                raise PlanGeometryError('قيم الارتدادات المسجلة متعارضة.', 'PLANS_SETBACK_CONFLICT')
            setbacks[key] = value
    return setbacks


def croquis_contract(project, context, points=None):
    project = project if isinstance(project, dict) else {}
    analysis = parsed(project.get('land_documents_analysis'), {})
    analysis = analysis if isinstance(analysis, dict) else {}
    parcels = analysis.get('parcels') or []
    parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    holders = (project, analysis, parcel)
    summary = text(first_value(holders, 'land_and_building_summary', 'document_summary', 'summary'))
    constraints = text(first_value((project, parcel, analysis), 'regulatory_constraints', 'allowed_uses_restrictions'))
    if len(summary) > 32000 or len(constraints) > 32000:
        raise PlanGeometryError('بيانات الكروكي النصية تتجاوز حجم المعالجة المتاح.', 'PLANS_CONTEXT_TOO_LARGE')
    rows = direction_rows(project, analysis, parcel)
    facade = primary_frontage(
        summary, constraints, rows, first_value(holders, 'facades_directions'),
        first_value(holders, 'main_facade_direction', 'primary_facade_direction', 'main_frontage_direction'))
    raw_points = points or first_value(holders, 'survey_coordinates', 'regulation_coordinates')
    if not raw_points:
        raw_points = plot_shape.dimension_survey_rows(project)
    geometry = boundary_geometry(raw_points)
    setback_text = text(first_value((project, parcel, analysis), 'setbacks', 'building_ratio_setbacks'))
    boundary_lengths_text = text(first_value(holders, 'boundary_lengths'))
    if not boundary_lengths_text:
        # Structured direction rows may carry the lengths without a summary —
        # the prompt still needs the documented dimensions.
        labels = {'north': 'الشمالي', 'south': 'الجنوبي', 'east': 'الشرقي', 'west': 'الغربي'}
        boundary_lengths_text = '، '.join(
            f'{labels[key]} {value:g}م' for key, value in
            plot_shape.direction_lengths(project).items() if value)
    return {'geometry': geometry, 'primaryFrontage': facade, 'directions': rows,
            'setbacks': recorded_setbacks(setback_text, rows, facade['direction']),
            'setbackText': setback_text, 'landBrief': summary, 'regulatoryConstraints': constraints,
            'boundaryLengths': boundary_lengths_text,
            'northDirection': text(first_value(holders, 'north_direction')),
            'surroundingStreets': text(first_value(holders, 'surrounding_streets')),
            'landArea': context.get('land_area'), 'coverageRatio': context.get('coverage_ratio'),
            'floorCount': context.get('floor_count'), 'floorAreaRatio': context.get('floor_area_ratio'),
            'documentedRegulations': context.get('regulations') or {}}
