import copy
import re

from visual_plan_geometry import (DIRECTION_VECTORS, EPSILON, PlanGeometryError, finite_number,
                                  parcel_edges, polygon_inside, polygons_overlap, signed_area,
                                  validate_footprint, validate_polygon)


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


def entry_position(entry, scene):
    edges = [edge for edge in parcel_edges(scene['geometry']) if edge['direction'] == entry['side']]
    if not edges:
        raise PlanGeometryError('جهة المدخل لا تطابق حدود الأرض.', 'PLANS_ENTRY_CONFLICT')
    edge = max(edges, key=lambda item: (item['b'][0] - item['a'][0]) ** 2 + (item['b'][1] - item['a'][1]) ** 2)
    return [edge['a'][i] + (edge['b'][i] - edge['a'][i]) * entry['position'] for i in (0, 1)]


def validate_scene(scene, contract, program):
    if not isinstance(scene, dict) or scene.get('geometry') != contract['geometry']:
        raise PlanGeometryError('حدود المشهد لا تطابق مرجع الأرض الثابت.', 'PLANS_BOUNDARY_CHANGED')
    if (scene.get('primaryFrontage') != contract['primaryFrontage'] or scene.get('setbacks') != contract['setbacks']
            or scene.get('directions') != contract['directions'] or scene.get('siteItems') != program['siteItems']):
        raise PlanGeometryError('الواجهة الرئيسية أو الارتدادات لا تطابق الكروكي.', 'PLANS_CONTEXT_CHANGED')
    source = {building['id']: building for building in program['buildings']}
    buildings = scene.get('buildings')
    if not isinstance(buildings, list) or len(buildings) != len(source):
        raise PlanGeometryError('المباني لا تطابق التوزيع المعتمد.', 'PLANS_PROGRAM_CHANGED')
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
    coverage = finite_number(str(contract.get('coverageRatio') or '').replace('%', ''))
    land_area = finite_number(contract.get('landArea'))
    if coverage is not None and land_area is not None and land_area > 0:
        ratio = coverage / 100 if coverage > 1 else coverage
        if sum(abs(signed_area(polygon)) for polygon in footprints) > land_area * ratio + 0.5:
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
        if area.get('kind') not in ('landscape', 'surface_parking'):
            raise PlanGeometryError('نوع المساحة المفتوحة غير صالح.')
        item = sites.get(area.get('componentId'))
        if area['kind'] == 'surface_parking' and (not item or item['category'] != 'parking'):
            raise PlanGeometryError('مواقف سطحية غير موجودة في التوزيع.', 'PLANS_PROGRAM_CHANGED')
        if item:
            required_area(abs(signed_area(polygon)), item.get('area'))
        if any(polygons_overlap(polygon, footprint) for footprint in footprints):
            raise PlanGeometryError('مساحة مفتوحة تتداخل مع بصمة مبنى.', 'PLANS_BUILDING_OVERLAP')
    if any(polygons_overlap(a['polygon'], b['polygon']) for index, a in enumerate(open_areas) for b in open_areas[index + 1:]):
        raise PlanGeometryError('المساحات المفتوحة تتداخل.')
    return scene


def make_scene(contract, program, layout, version=1):
    if not isinstance(layout, dict) or set(layout) - {'buildings', 'entries', 'openAreas', 'reply'}:
        raise PlanGeometryError('نتيجة تخطيط المشهد تحتوي بيانات غير مسموحة.', 'PLANS_LAYOUT_INVALID')
    proposed = layout.get('buildings')
    if not isinstance(proposed, list):
        raise PlanGeometryError('لم يصل توزيع هندسي صالح للمباني.', 'PLANS_LAYOUT_INVALID')
    by_id = {building['id']: building for building in program['buildings']}
    buildings = []
    for raw in proposed:
        if not isinstance(raw, dict) or set(raw) - {'id', 'footprint', 'facades'} or raw.get('id') not in by_id:
            raise PlanGeometryError('نتيجة تخطيط أحد المباني غير صالحة.', 'PLANS_LAYOUT_INVALID')
        facades = raw.get('facades') or {}
        if not isinstance(facades, dict) or set(facades) - set(DIRECTION_VECTORS):
            raise PlanGeometryError('نتيجة تخطيط إحدى الواجهات غير صالحة.', 'PLANS_LAYOUT_INVALID')
        buildings.append({**copy.deepcopy(by_id[raw['id']]),
                          'footprint': validate_polygon(raw.get('footprint'), 24),
                          'facades': {side: facade_style(style) for side, style in facades.items()}})
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
