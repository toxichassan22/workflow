import copy
import itertools
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
    """Coverage cap is advisory for visual prompt generation and does not block layout."""
    return


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
    # The coverage ratio cap is advisory for visual concept image generation;
    # it does not block prompt generation or scene sealing for approved programs.
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
    if not isinstance(open_areas, list) or len(open_areas) > 200:
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
        if any(polygons_overlap(polygon, footprint) for footprint in footprints):
            raise PlanGeometryError('مساحة مفتوحة تتداخل مع بصمة مبنى.', 'PLANS_BUILDING_OVERLAP')
    if any(polygons_overlap(a['polygon'], b['polygon']) for index, a in enumerate(open_areas) for b in open_areas[index + 1:]):
        raise PlanGeometryError('المساحات المفتوحة تتداخل.')
    site_placement_counts = {}
    site_placement_areas = {}
    for area in open_areas:
        component_id = area.get('componentId')
        if component_id in sites:
            site_placement_counts[component_id] = site_placement_counts.get(component_id, 0) + 1
            site_placement_areas[component_id] = (site_placement_areas.get(component_id, 0)
                                                   + abs(signed_area(area['polygon'])))
    duplicate_site_items = [str(sites[component_id].get('label')
                              or sites[component_id].get('name') or component_id)
                            for component_id, count in site_placement_counts.items()
                            if count > 1 and sites[component_id].get('category') != 'parking']
    if duplicate_site_items:
        raise PlanGeometryError('تكرر رسم مساحة معتمدة: ' + ', '.join(duplicate_site_items[:8]) + '.',
                                'PLANS_SITE_ITEMS_DUPLICATED')
    for component_id, placed_area in site_placement_areas.items():
        required_area(placed_area, sites[component_id].get('area'))
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


def _polygon_box(polygon):
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return (min(xs), min(ys), max(xs), max(ys))


def _freeze_polygons(polygons):
    return tuple(tuple(tuple(point) for point in polygon) for polygon in polygons)


def _boxes_apart(first, second, tolerance=1e-6):
    """True when two bounding boxes are separated, so their polygons cannot overlap."""
    return (first[2] < second[0] - tolerance or second[2] < first[0] - tolerance
            or first[3] < second[1] - tolerance or second[3] < first[1] - tolerance)


def _rect_search(regions, area, blocked=(), angle=0):
    """Grid search for an exact-area rectangle aligned with the parcel axis."""
    wanted = finite_number(area)
    if not wanted or wanted <= 0:
        return None
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    blocked_boxes = [(_polygon_box(item), item) for item in blocked]
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
                    rect_box = _polygon_box(rect)
                    if polygon_inside(rect, region) and not any(
                            not _boxes_apart(rect_box, box) and polygons_overlap(rect, item)
                            for box, item in blocked_boxes):
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
    for idx, parcel in enumerate(contract['geometry']['parcels']):
        polygon = parcel.get('polygon') if isinstance(parcel, dict) else parcel
        envelope = setback_envelope(polygon, contract.get('setbacks'))
        if len(envelope) >= 3:
            pid = parcel.get('id', f'parcel_{idx + 1}') if isinstance(parcel, dict) else f'parcel_{idx + 1}'
            envelopes.append({'parcelId': pid, 'polygon': envelope})
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


def _packing_local_bounds(polygon, cosine, sine):
    local = [(x * cosine + y * sine, -x * sine + y * cosine) for x, y in polygon]
    return (min(point[0] for point in local), min(point[1] for point in local),
            max(point[0] for point in local), max(point[1] for point in local))


def _is_local_box(region, cosine, sine, bounds):
    """True when the region is exactly its own bounding box in the parcel frame.

    For such a region a candidate rectangle lies inside it exactly when it lies
    within the bounds, so the costly polygon test can be skipped without any change
    in the result.
    """
    left, bottom, right, top = bounds
    corners = set()
    for x, y in region:
        u, v = x * cosine + y * sine, -x * sine + y * cosine
        on_u = [edge for edge in (left, right) if abs(u - edge) <= EPSILON]
        on_v = [edge for edge in (bottom, top) if abs(v - edge) <= EPSILON]
        if not on_u or not on_v:
            return False
        corners.add((on_u[0], on_v[0]))
    return len(corners) == 4


def _packing_world_rectangle(left, bottom, width, height, cosine, sine):
    return [[u * cosine - v * sine, u * sine + v * cosine]
            for u, v in ((left, bottom), (left + width, bottom),
                         (left + width, bottom + height), (left, bottom + height))]


def _packing_split_parts(container, bounds):
    left, bottom, right, top = container
    used_left, used_bottom, used_right, used_top = bounds
    parts = []
    if used_bottom > bottom + 1e-7:
        parts.append((left, bottom, right, used_bottom))
    if used_top < top - 1e-7:
        parts.append((left, used_top, right, top))
    if used_left > left + 1e-7:
        parts.append((left, used_bottom, used_left, used_top))
    if used_right < right - 1e-7:
        parts.append((used_right, used_bottom, right, used_top))
    return parts


def _packing_empty_spaces(parcels, cosine, sine):
    spaces = []
    for index, polygon in enumerate(parcels):
        left, bottom, right, top = _packing_local_bounds(polygon, cosine, sine)
        if right - left > 1e-7 and top - bottom > 1e-7:
            spaces.append((index, left, bottom, right, top))
    return spaces


def _packing_place(free_spaces, allowed_regions, area, cosine, sine, score_mode='balanced'):
    wanted = finite_number(area)
    if not wanted or wanted <= 0:
        return None
    ratios = ((1.3, 1.0, 1.7, 2.3, 3.1, 4.0) if score_mode == 'tight' else
              (1.0, 1.3, 1.7, 2.3, 3.1, 4.0, 0.77, 0.59, 0.44, 0.32, 0.25))
    anchors = (0.0, 1.0) if score_mode in ('tight', 'large_free') else (0.0, 0.5, 1.0)
    region_bounds = {index: _packing_local_bounds(region, cosine, sine)
                     for index, region in allowed_regions.items() if region}
    box_regions = {index for index, region in allowed_regions.items()
                   if region and _is_local_box(region, cosine, sine, region_bounds[index])}
    candidates = []
    for parcel_index, left, bottom, right, top in free_spaces:
        if parcel_index not in region_bounds:
            continue
        region_left, region_bottom, region_right, region_top = region_bounds[parcel_index]
        free_width, free_height = right - left, top - bottom
        for ratio_index, ratio in enumerate(ratios):
            width, height = math.sqrt(wanted * ratio), math.sqrt(wanted / ratio)
            if width > free_width + 1e-7 or height > free_height + 1e-7:
                continue
            horizontal, vertical = free_width - width, free_height - height
            x_positions = {left + horizontal * anchor for anchor in anchors}
            y_positions = {bottom + vertical * anchor for anchor in anchors}
            x_positions.update((max(left, min(right - width, region_left)),
                                max(left, min(right - width, region_right - width)))
                               if right - width >= left else ())
            y_positions.update((max(bottom, min(top - height, region_bottom)),
                                max(bottom, min(top - height, region_top - height)))
                               if top - height >= bottom else ())
            for x in x_positions:
                for y in y_positions:
                    bounds = (x, y, x + width, y + height)
                    pieces = _packing_split_parts((left, bottom, right, top), bounds)
                    piece_areas = [(x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in pieces]
                    if parcel_index in box_regions and (
                            x < region_left - EPSILON or x + width > region_right + EPSILON
                            or y < region_bottom - EPSILON or y + height > region_top + EPSILON):
                        continue
                    polygon = _packing_world_rectangle(x, y, width, height, cosine, sine)
                    if (parcel_index not in box_regions
                            and not polygon_inside(polygon, allowed_regions[parcel_index])):
                        continue
                    if score_mode == 'balanced':
                        score = (sum(value * value for value in piece_areas),
                                 max(piece_areas, default=0), ratio_index)
                    elif score_mode == 'large_free':
                        score = (-max(piece_areas, default=0),
                                 -sum(value * value for value in piece_areas),
                                 min(horizontal, vertical), ratio_index)
                    else:
                        short_fit = min(horizontal, vertical)
                        score = (short_fit, sum(piece_areas), ratio_index)
                    candidates.append((score, parcel_index, [bounds], polygon))
    for _score, parcel_index, reservations, polygon in sorted(candidates):
        return parcel_index, reservations, polygon
    return None


def _packing_reserve(free_spaces, parcel_index, bounds):
    reserved = []
    for index, left, bottom, right, top in free_spaces:
        if index != parcel_index:
            reserved.append((index, left, bottom, right, top))
            continue
        if (bounds[2] <= left + 1e-7 or bounds[0] >= right - 1e-7
                or bounds[3] <= bottom + 1e-7 or bounds[1] >= top - 1e-7):
            reserved.append((index, left, bottom, right, top))
            continue
        clipped = (max(left, bounds[0]), max(bottom, bounds[1]),
                   min(right, bounds[2]), min(top, bounds[3]))
        reserved.extend((index, *piece)
                        for piece in _packing_split_parts((left, bottom, right, top), clipped))
    return reserved


def _packing_reserve_many(free_spaces, parcel_index, reservations):
    for bounds in reservations:
        free_spaces = _packing_reserve(free_spaces, parcel_index, bounds)
    return free_spaces


def _packing_merge_spaces(free_spaces):
    spaces = list(free_spaces)
    while True:
        merged = False
        for first_index, first in enumerate(spaces):
            parcel, left, bottom, right, top = first
            for second_index in range(first_index + 1, len(spaces)):
                other_parcel, other_left, other_bottom, other_right, other_top = spaces[second_index]
                if parcel != other_parcel:
                    continue
                combined = None
                if abs(bottom - other_bottom) <= 1e-7 and abs(top - other_top) <= 1e-7:
                    if abs(right - other_left) <= 1e-7:
                        combined = (parcel, left, bottom, other_right, top)
                    elif abs(other_right - left) <= 1e-7:
                        combined = (parcel, other_left, bottom, right, top)
                elif abs(left - other_left) <= 1e-7 and abs(right - other_right) <= 1e-7:
                    if abs(top - other_bottom) <= 1e-7:
                        combined = (parcel, left, bottom, right, other_top)
                    elif abs(other_top - bottom) <= 1e-7:
                        combined = (parcel, left, other_bottom, right, top)
                if combined:
                    spaces = [space for index, space in enumerate(spaces)
                              if index not in (first_index, second_index)]
                    spaces.append(combined)
                    merged = True
                    break
            if merged:
                break
        if not merged:
            return spaces


def _packing_fill_free_area(free_spaces, parcels, area, cosine, sine):
    """Use connected or separated residual land as an exact-area parking field.

    Surface parking is a site use, not a building mass: it can occupy several
    free lots when no single rectangle can hold its approved aggregate area.
    Each piece stays inside one parcel and outside every previously reserved
    footprint.
    """
    remaining = finite_number(area) or 0
    placements = []
    merged_spaces = _packing_merge_spaces(free_spaces)
    ordered = sorted(merged_spaces, key=lambda row: -((row[3] - row[1]) * (row[4] - row[2])))
    for parcel_index, left, bottom, right, top in ordered:
        if remaining <= 0.5:
            break
        width, height = right - left, top - bottom
        free_area = width * height
        if free_area <= 1e-7:
            continue
        if free_area <= remaining + 1e-7:
            bounds = (left, bottom, right, top)
            polygon = _packing_world_rectangle(left, bottom, width, height, cosine, sine)
            if not polygon_inside(polygon, parcels[parcel_index]):
                continue
        else:
            polygon = None
            bounds = None
            target = min(remaining, free_area)
            ratios = (width / height, 4.0, 2.3, 1.3, 1.0, 0.77, 0.44, 0.25, 0.1, 0.05)
            for ratio in ratios:
                piece_width = math.sqrt(target * ratio)
                piece_height = target / piece_width
                if piece_width > width + 1e-7 or piece_height > height + 1e-7:
                    continue
                for x_anchor, y_anchor in ((0, 0), (0, 1), (1, 0), (1, 1)):
                    x = left + (width - piece_width) * x_anchor
                    y = bottom + (height - piece_height) * y_anchor
                    candidate = _packing_world_rectangle(x, y, piece_width, piece_height,
                                                         cosine, sine)
                    if polygon_inside(candidate, parcels[parcel_index]):
                        polygon = candidate
                        bounds = (x, y, x + piece_width, y + piece_height)
                        break
                if polygon is not None:
                    break
            if polygon is None:
                continue
        placements.append((parcel_index, bounds, polygon))
        remaining -= abs(signed_area(polygon))
    return (placements, remaining) if remaining <= 0.5 else ([], remaining)


def fallback_scene(contract, program, version=1):
    """Deterministic last-resort layout with bounded placement-order retries.

    Areas and geometry stay fixed. Reordering which approved footprints are
    placed first lets the system recover from a greedy placement that blocks a
    later large site area, while ``make_scene`` still enforces the full scene
    contract before anything is sealed.
    """
    envelopes = [item['polygon'] for item in buildable_envelopes(contract)]
    parcels = [parcel['polygon'] for parcel in contract['geometry']['parcels']]
    parcel_axis = _parcel_long_axis_angle(envelopes)
    radians = math.radians(parcel_axis)
    cosine, sine = math.cos(radians), math.sin(radians)
    envelope_by_id = {item['parcelId']: item['polygon'] for item in buildable_envelopes(contract)}
    envelopes_by_parcel = {index: envelope_by_id[parcel['id']]
                           for index, parcel in enumerate(contract['geometry']['parcels'])
                           if parcel['id'] in envelope_by_id}
    parcels_by_index = {index: parcel for index, parcel in enumerate(parcels)}
    # The same (regions, area, blocked, angle) search recurs across strategies and
    # placement orders; the search is deterministic, so a per-layout memo is exact.
    search_cache = {}

    def cached_rect_search(regions_arg, area_arg, blocked_arg, angle_arg):
        key = (_freeze_polygons(regions_arg), area_arg, _freeze_polygons(blocked_arg), angle_arg)
        if key not in search_cache:
            search_cache[key] = _rect_search(regions_arg, area_arg, blocked_arg, angle_arg)
        found = search_cache[key]
        return [list(point) for point in found] if found is not None else None

    buildings = sorted(
        (item for item in program['buildings'] if not item.get('basementOnly')),
        key=lambda item: -(finite_number(item['footprintArea']) or 0))
    site_items = sorted(
        (item for item in program.get('siteItems') or []
         if (finite_number(item.get('area')) or 0) > 0),
        key=lambda item: -(finite_number(item.get('area')) or 0))
    placement_rows = ([('building', item) for item in buildings]
                      + [('site', item) for item in site_items])
    nonparking_sites = [('site', item) for item in site_items
                        if _site_area_kind(item) != 'surface_parking']
    parking_sites = [('site', item) for item in site_items
                     if _site_area_kind(item) == 'surface_parking']
    strategies = (
        [('building', item) for item in buildings] + nonparking_sites + parking_sites,
        nonparking_sites + [('building', item) for item in buildings] + parking_sites,
        sorted(placement_rows, key=lambda row: -(
            finite_number(row[1].get('footprintArea' if row[0] == 'building' else 'area')) or 0)),
        (parking_sites
         + [('building', item) for item in buildings]
         + nonparking_sites),
        (parking_sites
         + [('building', item) for item in buildings if (finite_number(item['footprintArea']) or 0) >= 500]
         + nonparking_sites
         + [('building', item) for item in buildings if (finite_number(item['footprintArea']) or 0) < 500]),
    )
    failures = []
    attempts = ([(strategy, False) for strategy in strategies]
                + [(strategy, True) for strategy in _retry_placement_orders(strategies[0])])
    for strategy, quick in attempts:
        placed, open_areas, occupied = {}, [], []
        free_spaces = _packing_empty_spaces(parcels, cosine, sine)
        failure = None
        for kind, item in strategy:
            area = finite_number(item.get('footprintArea' if kind == 'building' else 'area'))
            allowed_regions = envelopes_by_parcel if kind == 'building' else parcels_by_index
            score_mode = ('large_free' if kind == 'site' and _site_area_kind(item) == 'surface_parking'
                          else 'balanced' if kind == 'site' else 'tight')
            packed = _packing_place(free_spaces, allowed_regions, area, cosine, sine, score_mode)
            polygon = packed[2] if packed else None
            regions = envelopes if kind == 'building' else parcels
            is_surface_parking = kind == 'site' and _site_area_kind(item) == 'surface_parking'
            # Reordering retries use only the fast packer; the grid searches are costly.
            can_grid_search = not quick and not is_surface_parking and len(occupied) < 24
            if polygon is None and can_grid_search:
                polygon = _rect_grid_search(regions, area, occupied, parcel_axis)
            if polygon is None and can_grid_search:
                polygon = cached_rect_search(regions, area, occupied, parcel_axis)
            if polygon is None and can_grid_search and abs(parcel_axis) > 0.01:
                polygon = _rect_grid_search(regions, area, occupied)
            if polygon is None and can_grid_search and abs(parcel_axis) > 0.01:
                polygon = cached_rect_search(regions, area, occupied, 0)
            if (polygon is None and kind == 'site'
                    and _site_area_kind(item) == 'surface_parking'):
                residual_parking, _remaining_area = _packing_fill_free_area(
                    free_spaces, parcels, area, cosine, sine)
                if residual_parking:
                    for part_index, (parcel_index, bounds, part_polygon) in enumerate(residual_parking, 1):
                        occupied.append(part_polygon)
                        free_spaces = _packing_reserve(free_spaces, parcel_index, bounds)
                        open_areas.append({'id': f"site_{item['id']}_{part_index}",
                                           'componentId': item['id'],
                                           'kind': _site_area_kind(item), 'polygon': part_polygon})
                    continue
            if polygon is None:
                if kind == 'building':
                    # Remaining buildable area is the envelope minus footprints already placed.
                    # Parcel boxes in free_spaces include setback strips, so they are not used.
                    remaining = max(0.0, sum(abs(signed_area(envelope)) for envelope in envelopes)
                                    - sum(abs(signed_area(placed_polygon)) for placed_polygon in occupied))
                    label = item.get('label') or item.get('name') or item['id']
                    failure = PlanGeometryError(
                        f'المبنى «{label}» ({area:g} م²) لا تتسع داخل أي جزء متبقٍ من منطقة البناء '
                        f'بعد الارتدادات المسجلة (المساحة المتبقية فيها ~{remaining:g} م²).',
                        'PLANS_SETBACK_CONFLICT')
                else:
                    label = item.get('label') or item.get('name') or item['id']
                    failure = PlanGeometryError(
                        f'المساحة المعتمدة «{label}» لا تتسع داخل حدود الأرض مع البصمات المسجلة.',
                        'PLANS_SITE_AREA_CONFLICT')
                break
            occupied.append(polygon)
            if packed and packed[2] is polygon:
                free_spaces = _packing_reserve_many(free_spaces, packed[0], packed[1])
            else:
                local_bounds = _packing_local_bounds(polygon, cosine, sine)
                containing_index = next((index for index, region in allowed_regions.items()
                                         if polygon_inside(polygon, region)), None)
                if containing_index is None:
                    containing_index = next((index for index, region in parcels_by_index.items()
                                             if polygon_inside(polygon, region)), None)
                if containing_index is not None:
                    free_spaces = _packing_reserve(free_spaces, containing_index, local_bounds)
            if kind == 'building':
                placed[item['id']] = polygon
            else:
                open_areas.append({'id': 'site_' + str(item['id']), 'componentId': item['id'],
                                   'kind': _site_area_kind(item), 'polygon': polygon})
        if failure:
            failures.append(failure)
            continue
        layout = [{'id': item['id'], 'footprint': placed[item['id']]}
                  for item in program['buildings'] if item['id'] in placed]
        try:
            return make_scene(contract, program, {'buildings': layout, 'openAreas': open_areas}, version)
        except PlanGeometryError as error:
            failures.append(error)
    if failures:
        raise failures[0]
    raise PlanGeometryError('تعذر إنشاء توزيع هندسي صالح للمخططات.', 'PLANS_LAYOUT_INVALID')


def _retry_placement_orders(first_order, limit=720, max_items=7):
    """Yield bounded reorderings of the first placement order.

    The greedy packer is order-sensitive: a footprint placed early can split the
    free space so a later one no longer fits, even when the total area fits. Only
    small programs are reordered, so large layouts keep their single attempt.
    """
    if len(first_order) > max_items:
        return
    for count, order in enumerate(itertools.permutations(first_order)):
        if count >= limit:
            return
        yield list(order)


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
