import copy
import math
import re

from visual_plan_geometry import (DIRECTION_VECTORS, EPSILON, PlanGeometryError, finite_number,
                                  parcel_edges, polygon_inside, polygons_overlap, setback_envelope,
                                  signed_area, validate_footprint, validate_polygon)


MATERIALS = ('neutral', 'glass', 'stone', 'metal', 'render')
PATTERNS = ('plain', 'grid', 'vertical', 'horizontal')


def facade_style(raw):
    if not isinstance(raw, dict) or set(raw) - {'material', 'color', 'pattern'}:
        raise PlanGeometryError('خصائص الواجهة غير صالحة.', 'PLANS_EDIT_INVALID')
    style = {}
    for key, options in (('material', MATERIALS), ('pattern', PATTERNS)):
        if key in raw:
            value = str(raw[key]).lower()
            if value not in options:
                raise PlanGeometryError('خاصية الواجهة غير مدعومة في المخطط المفاهيمي.', 'PLANS_EDIT_INVALID')
            style[key] = value
    if 'color' in raw:
        if not isinstance(raw['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', raw['color']):
            raise PlanGeometryError('لون الواجهة غير صالح.', 'PLANS_EDIT_INVALID')
        style['color'] = raw['color'].upper()
    return style


def required_area(actual, wanted):
    wanted = finite_number(wanted)
    if wanted is not None and wanted > 0 and abs(actual - wanted) > max(0.5, wanted * 0.02):
        raise PlanGeometryError('مساحة البصمة لا تطابق المساحة المستمدة من التوزيع.', 'PLANS_FOOTPRINT_AREA_CONFLICT')


def _site_area_kind(item):
    if item.get('category') == 'parking' or item.get('siteType') == 'parking':
        return 'surface_parking'
    if item.get('siteType') == 'landscape' or item.get('category') == 'landscape':
        return 'landscape'
    return 'site_facility'


def entry_position(entry, scene):
    edges = [edge for edge in parcel_edges(scene['geometry']) if edge['direction'] == entry['side']]
    if not edges:
        raise PlanGeometryError('جهة المدخل لا تطابق حدود الأرض.', 'PLANS_ENTRY_CONFLICT')
    edge = max(edges, key=lambda item: (item['b'][0] - item['a'][0]) ** 2 + (item['b'][1] - item['a'][1]) ** 2)
    return [edge['a'][i] + (edge['b'][i] - edge['a'][i]) * entry['position'] for i in (0, 1)]


def _coverage_cap(contract):
    coverage = finite_number(str(contract.get('coverageRatio') or '').replace('%', ''))
    land_area = finite_number(contract.get('landArea'))
    if coverage is None or land_area is None or land_area <= 0:
        return None
    return land_area * (coverage / 100 if coverage > 1 else coverage)


def check_program_feasibility(contract, program):
    """Refuse a building program no layout could satisfy, before any model call:
    the sum of mandatory above-ground footprints already exceeds the recorded
    coverage cap regardless of footprint shapes or placement (basement-only
    masses are exempt — they sit below ground and may overlap)."""
    cap = _coverage_cap(contract)
    if cap is None:
        return
    required = sum(building['footprintArea'] for building in program['buildings']
                   if not building.get('basementOnly'))
    if required > cap + 0.5:
        raise PlanGeometryError(
            f'مجموع البصمات المطلوبة {required:g} م² يتجاوز حد التغطية المسجل {cap:g} م² — '
            'لا يوجد ترتيب كتل يحقق التوزيع؛ قلّل أكبر مساحة دور بكل مبنى أو راجع نسبة التغطية.',
            'PLANS_COVERAGE_CONFLICT')


def validate_scene(scene, contract, program):
    if not isinstance(scene, dict) or scene.get('geometry') != contract['geometry']:
        raise PlanGeometryError('حدود المشهد لا تطابق مرجع الأرض الثابت.', 'PLANS_BOUNDARY_CHANGED')
    if (scene.get('primaryFrontage') != contract['primaryFrontage'] or scene.get('setbacks') != contract['setbacks']
            or scene.get('directions') != contract['directions'] or scene.get('siteItems') != program['siteItems']):
        raise PlanGeometryError('الواجهة الرئيسية أو الارتدادات لا تطابق الكروكي.', 'PLANS_CONTEXT_CHANGED')
    source = {building['id']: building for building in program['buildings']}
    buildings = scene.get('buildings')
    if not isinstance(buildings, list):
        raise PlanGeometryError('المباني لا تطابق التوزيع المعتمد.', 'PLANS_PROGRAM_CHANGED')
    placed_ids = {building.get('id') for building in buildings if isinstance(building, dict)}
    missing = [source[key]['name'] for key in source if key not in placed_ids]
    if len(buildings) != len(source) or missing:
        raise PlanGeometryError(
            'المباني لا تطابق التوزيع المعتمد'
            + (' — لم تصل بصمات: ' + '، '.join(missing) if missing else '') + '.',
            'PLANS_PROGRAM_CHANGED')
    seen, footprints = set(), []
    for building in buildings:
        if not isinstance(building, dict) or building.get('id') not in source or building['id'] in seen:
            raise PlanGeometryError('معرّف أحد المباني غير صالح.', 'PLANS_PROGRAM_CHANGED')
        seen.add(building['id'])
        recorded = source[building['id']]
        if any(building.get(key) != value for key, value in recorded.items()):
            raise PlanGeometryError('تغيرت بيانات أحد المباني خارج نطاق الرسم.', 'PLANS_PROGRAM_CHANGED')
        polygon = validate_footprint(building.get('footprint'), scene['geometry'],
                                     {} if recorded.get('basementOnly') else scene['setbacks'])
        required_area(abs(signed_area(polygon)), recorded['footprintArea'])
        facades = building.get('facades', {})
        if not isinstance(facades, dict) or set(facades) - set(DIRECTION_VECTORS):
            raise PlanGeometryError('جهة إحدى الواجهات غير صالحة.', 'PLANS_EDIT_INVALID')
        for style in facades.values():
            facade_style(style)
        if not recorded.get('basementOnly'):
            if any(polygons_overlap(polygon, previous) for previous in footprints):
                raise PlanGeometryError('بصمات المباني تتداخل.', 'PLANS_BUILDING_OVERLAP')
            footprints.append(polygon)
    cap = _coverage_cap(contract)
    if cap is not None:
        if sum(abs(signed_area(polygon)) for polygon in footprints) > cap + 0.5:
            raise PlanGeometryError('إجمالي بصمات المباني يتجاوز نسبة التغطية المسجلة.', 'PLANS_COVERAGE_CONFLICT')
    street_sides = {row['direction'] for row in contract['directions'] if row['street']}
    entries = scene.get('entries', [])
    if not isinstance(entries, list) or len(entries) > 30:
        raise PlanGeometryError('بيانات المداخل غير صالحة.', 'PLANS_ENTRY_CONFLICT')
    entry_ids = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {'id', 'kind', 'buildingId', 'side', 'position'}:
            raise PlanGeometryError('صيغة أحد المداخل غير صالحة.', 'PLANS_ENTRY_CONFLICT')
        if not isinstance(entry.get('id'), str) or not entry['id'] or entry['id'] in entry_ids:
            raise PlanGeometryError('معرّف أحد المداخل غير صالح.', 'PLANS_ENTRY_CONFLICT')
        entry_ids.add(entry['id'])
        fraction = finite_number(entry.get('position'))
        if entry.get('buildingId') not in source or entry.get('kind') not in ('main', 'residential', 'service') or entry.get('side') not in street_sides or fraction is None or not 0 <= fraction <= 1:
            raise PlanGeometryError('أحد المداخل لا يقع على شارع مسجل.', 'PLANS_ENTRY_CONFLICT')
        if entry['kind'] == 'main' and entry['side'] != contract['primaryFrontage']['direction']:
            raise PlanGeometryError('المدخل الرئيسي لا يطابق الواجهة الرئيسية.', 'PLANS_ENTRY_CONFLICT')
        entry_position(entry, scene)
    open_areas = scene.get('openAreas', [])
    if not isinstance(open_areas, list) or len(open_areas) > 30:
        raise PlanGeometryError('بيانات المساحات المفتوحة غير صالحة.')
    sites = {item['id']: item for item in program['siteItems']}
    open_ids = set()
    for area in open_areas:
        if not isinstance(area, dict) or set(area) - {'id', 'componentId', 'kind', 'polygon'}:
            raise PlanGeometryError('صيغة إحدى المساحات المفتوحة غير صالحة.')
        if not isinstance(area.get('id'), str) or not area['id'] or area['id'] in open_ids:
            raise PlanGeometryError('معرّف إحدى المساحات المفتوحة غير صالح.')
        open_ids.add(area['id'])
        polygon = validate_polygon(area.get('polygon'), 24)
        if not any(polygon_inside(polygon, parcel['polygon']) for parcel in scene['geometry']['parcels']):
            raise PlanGeometryError('مساحة مفتوحة تتجاوز حدود الأرض.', 'PLANS_FOOTPRINT_OUTSIDE')
        if area.get('kind') not in ('landscape', 'surface_parking', 'site_facility'):
            raise PlanGeometryError('نوع المساحة المفتوحة غير صالح.')
        item = sites.get(area.get('componentId'))
        if area['kind'] == 'surface_parking' and (not item or item['category'] != 'parking'):
            raise PlanGeometryError('مواقف سطحية غير موجودة في التوزيع.', 'PLANS_PROGRAM_CHANGED')
        if area['kind'] == 'site_facility' and not item:
            raise PlanGeometryError('مرفق الموقع غير موجود في البرنامج المعتمد.', 'PLANS_PROGRAM_CHANGED')
        if item:
            required_area(abs(signed_area(polygon)), item.get('area'))
        if any(polygons_overlap(polygon, footprint) for footprint in footprints):
            raise PlanGeometryError('مساحة مفتوحة تتداخل مع بصمة مبنى.', 'PLANS_BUILDING_OVERLAP')
    if any(polygons_overlap(a['polygon'], b['polygon']) for index, a in enumerate(open_areas) for b in open_areas[index + 1:]):
        raise PlanGeometryError('المساحات المفتوحة تتداخل.')
    site_placement_counts = {}
    for area in open_areas:
        component_id = area.get('componentId')
        if component_id in sites:
            site_placement_counts[component_id] = site_placement_counts.get(component_id, 0) + 1
    duplicate_site_items = [str(sites[component_id].get('label')
                              or sites[component_id].get('name') or component_id)
                            for component_id, count in site_placement_counts.items() if count > 1]
    if duplicate_site_items:
        raise PlanGeometryError('تكرر رسم مساحة معتمدة: ' + ', '.join(duplicate_site_items[:8]) + '.',
                                'PLANS_SITE_ITEMS_DUPLICATED')
    placed_site_ids = set(site_placement_counts)
    missing_site_items = [item for item in program['siteItems']
                          if (finite_number(item.get('area')) or 0) > 0
                          and item['id'] not in placed_site_ids]
    if missing_site_items:
        labels = ', '.join(str(item.get('label') or item.get('name') or item['id'])
                           for item in missing_site_items[:8])
        raise PlanGeometryError('المساحات المعتمدة غير مرسومة: ' + labels + '.',
                                'PLANS_SITE_ITEMS_MISSING')
    return scene


def rebase_scene_context(scene, contract, program):
    """Refresh only derived contract fields on an authenticated scene.

    The caller must verify the scene token and input signature before using
    this helper. Revalidate the full scene after replacing the derived fields
    so a changed frontage, setback, direction, or site program can still refuse
    geometry that no longer fits.
    """
    refreshed = copy.deepcopy(scene)
    refreshed.update({
        'primaryFrontage': copy.deepcopy(contract['primaryFrontage']),
        'setbacks': copy.deepcopy(contract['setbacks']),
        'directions': copy.deepcopy(contract['directions']),
        'siteItems': copy.deepcopy(program['siteItems']),
    })
    return validate_scene(refreshed, contract, program)


def _rect_search(regions, area, blocked=(), angle=0):
    """Grid search for an exact-area rectangle aligned with the parcel axis."""
    wanted = finite_number(area)
    if not wanted or wanted <= 0:
        return None
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    for region in sorted((r for r in regions if len(r) >= 3),
                         key=lambda item: -abs(signed_area(item))):
        min_x = min(point[0] for point in region)
        max_x = max(point[0] for point in region)
        min_y = min(point[1] for point in region)
        max_y = max(point[1] for point in region)
        for ratio in (1.0, 1.3, 1.7, 2.3, 0.77, 0.59, 0.44, 3.1, 0.32, 4.0, 0.25):
            width = math.sqrt(wanted * ratio)
            height = wanted / width
            half_x = (width * abs(cosine) + height * abs(sine)) / 2
            half_y = (width * abs(sine) + height * abs(cosine)) / 2
            if 2 * half_x > max_x - min_x or 2 * half_y > max_y - min_y:
                continue
            for fy in range(21):
                for fx in range(21):
                    cx = min_x + half_x + (max_x - min_x - 2 * half_x) * fx / 20
                    cy = min_y + half_y + (max_y - min_y - 2 * half_y) * fy / 20
                    rect = [[cx + dx * cosine - dy * sine,
                             cy + dx * sine + dy * cosine]
                            for dx, dy in ((-width / 2, -height / 2),
                                           (width / 2, -height / 2),
                                           (width / 2, height / 2),
                                           (-width / 2, height / 2))]
                    if polygon_inside(rect, region) and not any(
                            polygons_overlap(rect, item) for item in blocked):
                        return rect
    return None


def _rect_grid_search(regions, area, blocked=(), angle=0):
    """Pack exact-area footprints on a parcel-aligned grid for dense programs."""
    wanted = finite_number(area)
    if not wanted or wanted <= 0:
        return None
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    ratios = (1.3, 1.0, 1.7, 0.77, 2.3, 0.59, 3.1, 0.44, 4.0, 0.32, 0.25)
    blocked_bounds = [(min(point[0] for point in item), max(point[0] for point in item),
                       min(point[1] for point in item), max(point[1] for point in item))
                      for item in blocked if item]
    for region in sorted((r for r in regions if len(r) >= 3),
                         key=lambda item: -abs(signed_area(item))):
        local = [(x * cosine + y * sine, -x * sine + y * cosine) for x, y in region]
        min_x, max_x = min(point[0] for point in local), max(point[0] for point in local)
        min_y, max_y = min(point[1] for point in local), max(point[1] for point in local)
        for ratio in ratios:
            width, height = math.sqrt(wanted * ratio), math.sqrt(wanted / ratio)
            columns = int((max_x - min_x) // width)
            rows = int((max_y - min_y) // height)
            if columns <= 0 or rows <= 0:
                continue
            for row in range(rows):
                cy = min_y + height / 2 + row * height
                for column in range(columns):
                    cx = min_x + width / 2 + column * width
                    rect = []
                    for u, v in ((cx - width / 2, cy - height / 2),
                                 (cx + width / 2, cy - height / 2),
                                 (cx + width / 2, cy + height / 2),
                                 (cx - width / 2, cy + height / 2)):
                        rect.append([u * cosine - v * sine, u * sine + v * cosine])
                    if not polygon_inside(rect, region):
                        continue
                    left, right = min(point[0] for point in rect), max(point[0] for point in rect)
                    bottom, top = min(point[1] for point in rect), max(point[1] for point in rect)
                    possible_collisions = [item for item, bounds in zip(blocked, blocked_bounds)
                                           if not (right <= bounds[0] + 1e-8
                                                   or left >= bounds[1] - 1e-8
                                                   or top <= bounds[2] + 1e-8
                                                   or bottom >= bounds[3] - 1e-8)]
                    if not any(polygons_overlap(rect, item) for item in possible_collisions):
                        return rect
    return None


def _basement_footprint(geometry, area):
    """Deterministic footprint for a basement-only mass the layout omitted: an
    axis-aligned rect of the exact recorded area searched inside the largest
    parcel. Basements carry no setbacks and may overlap other masses, so any
    in-parcel position validates — the layout model only picks a shape."""
    return _rect_search([parcel['polygon'] for parcel in geometry['parcels']], area)


def buildable_envelopes(contract):
    """Per-parcel buildable region after the recorded setbacks — handed to the
    layout model and to the deterministic fallback so footprints start inside
    the legal zone instead of discovering it by rejection."""
    envelopes = []
    for parcel in contract['geometry']['parcels']:
        envelope = setback_envelope(parcel['polygon'], contract.get('setbacks'))
        if len(envelope) >= 3:
            envelopes.append({'parcelId': parcel['id'], 'polygon': envelope})
    return envelopes


def _parcel_long_axis_angle(regions):
    edges = [(a, b) for region in regions
             for a, b in zip(region, region[1:] + region[:1])]
    if not edges:
        return 0.0
    a, b = max(edges, key=lambda edge: math.dist(*edge))
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    while angle > 90:
        angle -= 180
    while angle <= -90:
        angle += 180
    return angle


def fallback_scene(contract, program, version=1):
    """Deterministic last-resort layout — exact-area rects placed inside the
    setback envelopes — tried only when the layout model fails, so prepare
    still seals a valid scene or refuses with the precise capacity reason."""
    envelopes = [item['polygon'] for item in buildable_envelopes(contract)]
    parcel_axis = _parcel_long_axis_angle(envelopes)
    placed = {}
    for building in sorted(program['buildings'],
                           key=lambda item: -(finite_number(item['footprintArea']) or 0)):
        if building.get('basementOnly'):
            continue
        footprint = _rect_grid_search(envelopes, building['footprintArea'], list(placed.values()), parcel_axis)
        if footprint is None:
            footprint = _rect_search(envelopes, building['footprintArea'], list(placed.values()), parcel_axis)
        if footprint is None and abs(parcel_axis) > 0.01:
            footprint = _rect_grid_search(envelopes, building['footprintArea'], list(placed.values()))
        if footprint is None and abs(parcel_axis) > 0.01:
            footprint = _rect_search(envelopes, building['footprintArea'], list(placed.values()))
        if footprint is None:
            required = sum(finite_number(item['footprintArea']) or 0
                           for item in program['buildings'] if not item.get('basementOnly'))
            available = sum(abs(signed_area(item)) for item in envelopes)
            raise PlanGeometryError(
                f'بصمات المباني المطلوبة {required:g} م² لا تتسع داخل منطقة البناء بعد الارتدادات المسجلة '
                f'(~{available:g} م² متاحة) — قلّل مساحة أكبر دور في التوزيع أو راجع الارتدادات.',
                'PLANS_SETBACK_CONFLICT')
        placed[building['id']] = footprint
    layout = [{'id': building['id'], 'footprint': placed[building['id']]}
              for building in program['buildings'] if building['id'] in placed]
    open_areas = []
    occupied = [placed[item['id']] for item in program['buildings']
                if item['id'] in placed and not item.get('basementOnly')]
    for item in sorted(program.get('siteItems') or [],
                       key=lambda source: -(finite_number(source.get('area')) or 0)):
        area = finite_number(item.get('area'))
        if area is None or area <= 0:
            continue
        polygon = _rect_grid_search(
            [parcel['polygon'] for parcel in contract['geometry']['parcels']], area,
            occupied, parcel_axis)
        if polygon is None:
            polygon = _rect_search(
                [parcel['polygon'] for parcel in contract['geometry']['parcels']], area,
                occupied, parcel_axis)
        if polygon is None:
            raise PlanGeometryError(
                f'المساحة المعتمدة «{item.get("label") or item.get("name") or item["id"]}» '
                'لا تتسع داخل حدود الأرض مع البصمات المسجلة.', 'PLANS_SITE_AREA_CONFLICT')
        occupied.append(polygon)
        open_areas.append({'id': 'site_' + str(item['id']), 'componentId': item['id'],
                           'kind': _site_area_kind(item), 'polygon': polygon})
    return make_scene(contract, program, {'buildings': layout, 'openAreas': open_areas}, version)


def make_scene(contract, program, layout, version=1):
    if not isinstance(layout, dict) or set(layout) - {'buildings', 'entries', 'openAreas', 'reply'}:
        raise PlanGeometryError('نتيجة تخطيط المشهد تحتوي بيانات غير مسموحة.', 'PLANS_LAYOUT_INVALID')
    proposed = layout.get('buildings')
    if not isinstance(proposed, list):
        raise PlanGeometryError('لم يصل توزيع هندسي صالح للمباني.', 'PLANS_LAYOUT_INVALID')
    by_id = {building['id']: building for building in program['buildings']}
    named = {}
    for building in program['buildings']:
        for variant in (building.get('name'), building.get('label')):
            if isinstance(variant, str) and variant.strip():
                named.setdefault(variant.strip(), building['id'])
                named.setdefault(variant.strip().casefold(), building['id'])
    buildings = []
    for raw in proposed:
        bid = raw.get('id') if isinstance(raw, dict) else None
        if isinstance(bid, str) and bid not in by_id:
            bid = named.get(bid.strip()) or named.get(bid.strip().casefold())
        if not isinstance(raw, dict) or set(raw) - {'id', 'footprint', 'facades'} or bid not in by_id:
            raise PlanGeometryError('نتيجة تخطيط أحد المباني غير صالحة.', 'PLANS_LAYOUT_INVALID')
        facades = raw.get('facades') or {}
        if not isinstance(facades, dict) or set(facades) - set(DIRECTION_VECTORS):
            raise PlanGeometryError('نتيجة تخطيط إحدى الواجهات غير صالحة.', 'PLANS_LAYOUT_INVALID')
        buildings.append({**copy.deepcopy(by_id[bid]),
                          'footprint': validate_polygon(raw.get('footprint'), 24),
                          'facades': {side: facade_style(style) for side, style in facades.items()}})
    placed = {building['id'] for building in buildings}
    for item in program['buildings']:
        if item['id'] in placed or not item.get('basementOnly'):
            continue
        footprint = _basement_footprint(contract['geometry'], item['footprintArea'])
        if footprint is not None:
            buildings.append({**copy.deepcopy(item), 'footprint': footprint, 'facades': {}})
    entries = copy.deepcopy(layout.get('entries') or [])
    if not entries and buildings and any(row['street'] and row['direction'] == contract['primaryFrontage']['direction'] for row in contract['directions']):
        entries = [{'id': 'main_entry', 'buildingId': buildings[0]['id'], 'kind': 'main',
                    'side': contract['primaryFrontage']['direction'], 'position': 0.5}]
    scene = {'version': version, 'geometry': copy.deepcopy(contract['geometry']),
             'primaryFrontage': copy.deepcopy(contract['primaryFrontage']),
             'setbacks': copy.deepcopy(contract['setbacks']), 'directions': copy.deepcopy(contract['directions']),
             'buildings': buildings, 'siteItems': copy.deepcopy(program['siteItems']),
             'entries': entries, 'openAreas': copy.deepcopy(layout.get('openAreas') or [])}
    return validate_scene(scene, contract, program)


def apply_edits(scene, edits, contract, program, facade_only=False):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 12:
        raise PlanGeometryError('طلب تعديل المشهد غير صالح.', 'PLANS_EDIT_INVALID')
    result = copy.deepcopy(scene)
    buildings = {building['id']: building for building in result['buildings']}
    for edit in edits:
        if not isinstance(edit, dict):
            raise PlanGeometryError('طلب تعديل المشهد غير صالح.', 'PLANS_EDIT_INVALID')
        kind = edit.get('type')
        if facade_only and kind != 'facade':
            raise PlanGeometryError('طلب تعديل الواجهة لا يسمح بتغيير التوزيع أو الأرض.', 'PLANS_EDIT_SCOPE')
        if kind == 'facade':
            if set(edit) - {'type', 'buildingId', 'side', 'style'} or edit.get('buildingId') not in buildings or edit.get('side') not in DIRECTION_VECTORS:
                raise PlanGeometryError('العنصر المقصود بتعديل الواجهة غير صالح.', 'PLANS_EDIT_INVALID')
            building = buildings[edit['buildingId']]
            previous = building['facades'].get(edit['side'], {})
            building['facades'][edit['side']] = {**previous, **facade_style(edit.get('style'))}
        elif kind == 'footprint':
            if set(edit) - {'type', 'buildingId', 'footprint'} or edit.get('buildingId') not in buildings:
                raise PlanGeometryError('العنصر المقصود بتعديل البصمة غير صالح.', 'PLANS_EDIT_INVALID')
            buildings[edit['buildingId']]['footprint'] = validate_polygon(edit.get('footprint'), 24)
        elif kind == 'entry':
            if set(edit) - {'type', 'id', 'kind', 'buildingId', 'side', 'position'}:
                raise PlanGeometryError('طلب تعديل المدخل غير صالح.', 'PLANS_EDIT_INVALID')
            replacement = {key: value for key, value in edit.items() if key != 'type'}
            existing = next((index for index, entry in enumerate(result['entries']) if entry['id'] == edit.get('id')), None)
            if existing is None:
                result['entries'].append(replacement)
            else:
                result['entries'][existing] = replacement
        else:
            raise PlanGeometryError('هذا التعديل خارج نطاق عناصر المخطط.', 'PLANS_EDIT_SCOPE')
    return validate_scene(result, contract, program)
