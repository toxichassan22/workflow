# Deterministic SVG section rendering for the site plan.
def _visual_plan_site_component_fragment(layout):
    """Render every validated building footprint directly, without model abstraction."""
    namespace = 'http://www.w3.org/2000/svg'
    root = etree.Element('{%s}g' % namespace, id='ll-section-components')
    legend_colors = {
        str(item.get('category') or ''): str(item.get('color') or '')
        for item in layout.get('architecturalColorLegend') or [] if isinstance(item, dict)
    }
    rendered = 0
    for building in layout.get('buildings') or []:
        points = building.get('footprint') if isinstance(building, dict) else None
        if not isinstance(points, list) or len(points) < 3:
            raise visual_plan_geometry.PlanGeometryError(
                'بصمة أحد المكونات المعتمدة غير صالحة للرسم.', 'PLANS_SCENE_REQUIRED')
        serialized_points = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise visual_plan_geometry.PlanGeometryError(
                    'إحداثيات أحد المكونات المعتمدة غير صالحة للرسم.', 'PLANS_SCENE_REQUIRED')
            x = visual_plan_geometry.finite_number(point[0])
            y = visual_plan_geometry.finite_number(point[1])
            if x is None or y is None:
                raise visual_plan_geometry.PlanGeometryError(
                    'إحداثيات أحد المكونات المعتمدة غير صالحة للرسم.', 'PLANS_SCENE_REQUIRED')
            serialized_points.append((x, y))
        fill = legend_colors.get(str(building.get('category') or ''),
                                 visual_plan_renderer.COLORS.get('amenity', '#DCE6F0'))
        etree.SubElement(root, '{%s}polygon' % namespace, {
            'data-building-id': str(building.get('id') or ''),
            'class': 'll-building',
            'points': ' '.join(f'{x:g},{y:g}' for x, y in serialized_points),
            'fill': fill, 'fill-opacity': '0.82', 'stroke': '#07182C', 'stroke-width': '1.5',
        })
        rendered += 1
        label = _visual_plan_site_short_label(building.get('displayLabel') or building.get('label'))
        if label:
            center_x = sum(point[0] for point in serialized_points) / len(serialized_points)
            center_y = sum(point[1] for point in serialized_points) / len(serialized_points)
            min_width = min(max(point[0] for point in serialized_points) - min(point[0] for point in serialized_points),
                            max(point[1] for point in serialized_points) - min(point[1] for point in serialized_points))
            font_size = max(6, min(15, min_width * (0.34 if label.startswith('V ') else 0.22)))
            text = etree.SubElement(root, '{%s}text' % namespace, {
                'x': f'{center_x:g}', 'y': f'{center_y:g}', 'fill': '#07182C',
                'font-size': f'{font_size:g}', 'font-weight': '600', 'text-anchor': 'middle',
                'paint-order': 'stroke', 'stroke': '#FFFFFF', 'stroke-width': '1.8',
            })
            text.text = label
    expected = len(layout.get('buildings') or [])
    if rendered != expected:
        raise visual_plan_geometry.PlanGeometryError(
            'لم تكتمل بصمات المكونات المعتمدة في الرسم.', 'PLANS_SVG_INCOMPLETE')
    return etree.tostring(root, encoding='unicode')


def _visual_plan_site_coordinates_fragment(layout):
    namespace = 'http://www.w3.org/2000/svg'
    root = etree.Element('{%s}g' % namespace, id='ll-section-coordinates')
    etree.SubElement(root, '{%s}rect' % namespace, {
        'id': 'll-page-background', 'x': '0', 'y': '0', 'width': '1600', 'height': '900',
        'fill': '#FFFFFF',
    })
    for envelope in layout.get('buildableEnvelopes') or []:
        points = envelope.get('points') or []
        if len(points) >= 3:
            etree.SubElement(root, '{%s}polygon' % namespace, {
                'class': 'll-envelope',
                'points': ' '.join(f'{float(x):g},{float(y):g}' for x, y in points),
                'fill': '#17C8E3', 'fill-opacity': '0.035', 'stroke': '#0FA9C4',
                'stroke-width': '1.3', 'stroke-dasharray': '7 6',
            })
    for street in layout.get('streets') or []:
        points = street.get('polygon') if isinstance(street, dict) else None
        if not isinstance(points, list) or len(points) < 4:
            continue
        etree.SubElement(root, '{%s}polygon' % namespace, {
            'data-street-direction': str(street.get('direction') or ''),
            'class': 'll-street',
            'points': ' '.join(f'{float(x):g},{float(y):g}' for x, y in points),
            'fill': '#DDE3E9', 'stroke': '#AAB6C2', 'stroke-width': '1.2',
        })
    for parcel in layout.get('parcels') or []:
        points = parcel.get('points') or []
        if len(points) < 3:
            raise visual_plan_geometry.PlanGeometryError(
                'حدود قطعة الأرض غير صالحة للرسم.', 'PLANS_SCENE_REQUIRED')
        etree.SubElement(root, '{%s}polygon' % namespace, {
            'class': 'll-parcel',
            'points': ' '.join(f'{float(x):g},{float(y):g}' for x, y in points),
            'fill': '#FFFFFF', 'stroke': '#07182C', 'stroke-width': '3.2',
            'stroke-linejoin': 'round',
        })
    if not len(root):
        raise visual_plan_geometry.PlanGeometryError(
            'حدود قطعة الأرض غير متاحة للرسم.', 'PLANS_SCENE_REQUIRED')
    return etree.tostring(root, encoding='unicode')


def _visual_plan_site_colors_fragment():
    return ('<defs xmlns="http://www.w3.org/2000/svg" id="ll-section-colors">'
            '<style>.ll-parcel{stroke:#07182C;stroke-width:3.2;fill:#FFFFFF}'
            '.ll-envelope{fill:#17C8E3;fill-opacity:.035;stroke:#0FA9C4;'
            'stroke-width:1.3;stroke-dasharray:7 6}'
            '.ll-building{stroke:#07182C;stroke-width:1.5;fill-opacity:.82}'
            '.ll-open-area{stroke:#FFFFFF;stroke-width:1.2;fill-opacity:.68}'
            '</style></defs>')


def _visual_plan_site_access_fragment(layout):
    namespace = 'http://www.w3.org/2000/svg'
    root = etree.Element('{%s}g' % namespace, id='ll-section-access')
    buildings = {str(item.get('id')): item for item in layout.get('buildings') or []
                 if isinstance(item, dict)}
    for road in layout.get('siteCirculation') or []:
        points = road.get('points') if isinstance(road, dict) else None
        if not isinstance(points, list) or len(points) != 2:
            continue
        d = f'M {float(points[0][0]):g} {float(points[0][1]):g} L {float(points[1][0]):g} {float(points[1][1]):g}'
        etree.SubElement(root, '{%s}path' % namespace, {
            'class': 'll-internal-road', 'd': d, 'fill': 'none',
            'stroke': '#C7CFD7', 'stroke-width': f"{float(road.get('width') or 4):g}",
            'stroke-linecap': 'round',
        })
        etree.SubElement(root, '{%s}path' % namespace, {
            'class': 'll-internal-road-centerline', 'd': d, 'fill': 'none',
            'stroke': '#FFFFFF', 'stroke-width': '1.1', 'stroke-dasharray': '4 5',
        })
    for entry in layout.get('entries') or []:
        if not isinstance(entry, dict):
            continue
        point = entry.get('point')
        building = buildings.get(str(entry.get('buildingId') or ''))
        polygon = building.get('footprint') if isinstance(building, dict) else None
        if not isinstance(point, list) or len(point) != 2 or not isinstance(polygon, list) or len(polygon) < 3:
            continue
        start = [visual_plan_geometry.finite_number(value) for value in point]
        if any(value is None for value in start):
            continue
        nearest = None
        nearest_distance = None
        for index, first in enumerate(polygon):
            second = polygon[(index + 1) % len(polygon)]
            if (not isinstance(first, list) or not isinstance(second, list)
                    or len(first) != 2 or len(second) != 2):
                continue
            ax, ay = float(first[0]), float(first[1])
            bx, by = float(second[0]), float(second[1])
            dx, dy = bx - ax, by - ay
            length_sq = dx * dx + dy * dy
            fraction = 0 if length_sq <= 0 else max(0, min(1, ((start[0] - ax) * dx + (start[1] - ay) * dy) / length_sq))
            candidate = [ax + fraction * dx, ay + fraction * dy]
            distance = math.dist(start, candidate)
            if nearest_distance is None or distance < nearest_distance:
                nearest, nearest_distance = candidate, distance
        if nearest is None or nearest_distance <= 2:
            continue
        d = f'M {start[0]:g} {start[1]:g} L {nearest[0]:g} {nearest[1]:g}'
        etree.SubElement(root, '{%s}path' % namespace, {
            'class': 'll-access-road', 'd': d, 'fill': 'none',
            'stroke': '#C7CFD7', 'stroke-width': '14', 'stroke-linecap': 'round',
        })
        etree.SubElement(root, '{%s}path' % namespace, {
            'class': 'll-access-road-centerline', 'd': d, 'fill': 'none',
            'stroke': '#FFFFFF', 'stroke-width': '1.4', 'stroke-dasharray': '5 6',
        })
    for street in layout.get('streets') or []:
        line = street.get('centerLine') if isinstance(street, dict) else None
        if isinstance(line, list) and len(line) == 2:
            etree.SubElement(root, '{%s}line' % namespace, {
                'class': 'll-street-centerline',
                'x1': f'{float(line[0][0]):g}', 'y1': f'{float(line[0][1]):g}',
                'x2': f'{float(line[1][0]):g}', 'y2': f'{float(line[1][1]):g}',
                'stroke': '#FFFFFF', 'stroke-width': '1.5', 'stroke-dasharray': '8 8',
            })
        label_point = street.get('labelPoint')
        if isinstance(label_point, list) and len(label_point) == 2 and street.get('label'):
            label = etree.SubElement(root, '{%s}text' % namespace, {
                'x': f'{float(label_point[0]):g}', 'y': f'{float(label_point[1]):g}',
                'fill': '#07182C', 'font-size': '11', 'font-weight': '600',
                'text-anchor': 'middle', 'paint-order': 'stroke',
                'stroke': '#FFFFFF', 'stroke-width': '2.5',
            })
            label.text = str(street['label'])
    for entry in layout.get('entries') or []:
        point = entry.get('point') if isinstance(entry, dict) else None
        if not isinstance(point, list) or len(point) != 2:
            continue
        x = visual_plan_geometry.finite_number(point[0])
        y = visual_plan_geometry.finite_number(point[1])
        if x is None or y is None:
            continue
        kind = str(entry.get('kind') or '')
        etree.SubElement(root, '{%s}circle' % namespace, {
            'cx': f'{x:g}', 'cy': f'{y:g}', 'r': '6' if kind == 'main' else '4.5',
            'fill': '#07182C' if kind == 'main' else '#FFFFFF',
            'stroke': '#FFFFFF' if kind == 'main' else '#07182C', 'stroke-width': '2',
        })
    return etree.tostring(root, encoding='unicode')


def _visual_plan_site_landscape_fragment(layout):
    namespace = 'http://www.w3.org/2000/svg'
    root = etree.Element('{%s}g' % namespace, id='ll-section-landscape')
    colors = {str(item.get('category') or ''): str(item.get('color') or '')
              for item in layout.get('architecturalColorLegend') or [] if isinstance(item, dict)}
    for area in layout.get('openAreas') or []:
        points = area.get('points') if isinstance(area, dict) else None
        if not isinstance(points, list) or len(points) < 3:
            continue
        serialized = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                serialized = []
                break
            x = visual_plan_geometry.finite_number(point[0])
            y = visual_plan_geometry.finite_number(point[1])
            if x is None or y is None:
                serialized = []
                break
            serialized.append((x, y))
        if not serialized:
            continue
        category = str(area.get('category') or '')
        feature_type = str(area.get('featureType') or '')
        fill = {'pool': '#B6E1EF', 'padel': '#E7DDB8',
                'playground': '#F5E5AB'}.get(
                    feature_type, colors.get(category, visual_plan_renderer.COLORS.get(category, '#DCE6F0')))
        etree.SubElement(root, '{%s}polygon' % namespace, {
            'data-site-item-id': str(area.get('componentId') or ''),
            'data-site-feature': feature_type,
            'class': 'll-open-area',
            'points': ' '.join(f'{x:g},{y:g}' for x, y in serialized),
            'fill': fill,
            'fill-opacity': '0.68', 'stroke': '#FFFFFF', 'stroke-width': '1.2',
            'stroke-linejoin': 'round',
        })
        center_x = sum(point[0] for point in serialized) / len(serialized)
        center_y = sum(point[1] for point in serialized) / len(serialized)
        if feature_type in ('pool', 'padel') and len(serialized) == 4:
            first_mid = [(serialized[0][i] + serialized[3][i]) / 2 for i in (0, 1)]
            second_mid = [(serialized[1][i] + serialized[2][i]) / 2 for i in (0, 1)]
            etree.SubElement(root, '{%s}line' % namespace, {
                'x1': f'{first_mid[0]:g}', 'y1': f'{first_mid[1]:g}',
                'x2': f'{second_mid[0]:g}', 'y2': f'{second_mid[1]:g}',
                'stroke': '#FFFFFF' if feature_type == 'pool' else '#07182C',
                'stroke-width': '1.3',
            })
            if feature_type == 'padel':
                etree.SubElement(root, '{%s}line' % namespace, {
                    'x1': f'{center_x:g}', 'y1': f'{center_y:g}',
                    'x2': f'{(center_x + second_mid[0]) / 2:g}',
                    'y2': f'{(center_y + second_mid[1]) / 2:g}',
                    'stroke': '#07182C', 'stroke-width': '0.9',
                })
        label_value = _visual_plan_site_short_label(area.get('label'))
        if label_value:
            label = etree.SubElement(root, '{%s}text' % namespace, {
                'x': f'{center_x:g}', 'y': f'{center_y:g}', 'fill': '#07182C',
                'font-size': '10', 'font-weight': '600', 'text-anchor': 'middle',
                'paint-order': 'stroke', 'stroke': '#FFFFFF', 'stroke-width': '2.5',
            })
            label.text = label_value
    return etree.tostring(root, encoding='unicode')


def _visual_plan_site_legend_fragment(layout):
    namespace = 'http://www.w3.org/2000/svg'
    root = etree.Element('{%s}g' % namespace, id='ll-section-legend')
    bounds = layout.get('legendBounds') or [1212, 40, 352, 820]
    x, y, width, _height = [float(value) for value in bounds]
    etree.SubElement(root, '{%s}line' % namespace, {
        'x1': f'{x:g}', 'y1': f'{y:g}', 'x2': f'{x:g}', 'y2': '860',
        'stroke': '#D8E2EC', 'stroke-width': '1.4',
    })
    etree.SubElement(root, '{%s}rect' % namespace, {
        'x': f'{x + 22:g}', 'y': f'{y + 17:g}', 'width': '38', 'height': '4',
        'fill': '#17C8E3',
    })

    def add_text(value, tx, ty, size=14, weight='500', color='#07182C', max_length=46, parent=None):
        value = _visual_plan_site_identity_value(value, max_length)
        if not value:
            return
        arabic = bool(re.search(r'[\u0600-\u06FF]', value))
        element = etree.SubElement(parent if parent is not None else root, '{%s}text' % namespace, {
            'x': f'{tx:g}', 'y': f'{ty:g}', 'fill': color,
            'font-size': f'{size:g}', 'font-weight': weight,
            'text-anchor': 'end' if arabic else 'start',
            'direction': 'rtl' if arabic else 'ltr', 'unicode-bidi': 'plaintext',
        })
        element.text = value

    identity = layout.get('identity') if isinstance(layout.get('identity'), dict) else {}
    identity_group = etree.SubElement(root, '{%s}g' % namespace, id='ll-project-identity')
    add_text('PROJECT SITE PLAN', x + 22, y + 48, 20, '700', parent=identity_group)
    add_text(identity.get('projectName'), x + width - 20, y + 82, 17, '700', max_length=40, parent=identity_group)
    add_text(identity.get('developerName'), x + width - 20, y + 111, 13, '500', '#526577', 42,
             parent=identity_group)
    meta = []
    if identity.get('landArea'):
        meta.append('Land Area: ' + str(identity['landArea']) + ' m²')
    if identity.get('frontage'):
        meta.append('Frontage: ' + str(identity['frontage']).upper())
    add_text(' | '.join(meta), x + 22, y + 143, 11, '500', '#526577', 52, parent=identity_group)
    etree.SubElement(root, '{%s}line' % namespace, {
        'x1': f'{x + 22:g}', 'y1': f'{y + 160:g}',
        'x2': f'{x + width - 18:g}', 'y2': f'{y + 160:g}',
        'stroke': '#D8E2EC', 'stroke-width': '1',
    })
    schedule = layout.get('buildingSchedule') or []
    add_text('BUILDING SCHEDULE', x + 22, y + 190, 13, '700', '#0A829B', parent=identity_group)
    visible_schedule = schedule[:6]
    for index, item in enumerate(visible_schedule):
        row_y = y + 220 + index * 25
        color = visual_plan_renderer.COLORS.get(item.get('category'), '#DCE6F0')
        etree.SubElement(root, '{%s}rect' % namespace, {
            'x': f'{x + 22:g}', 'y': f'{row_y - 10:g}', 'width': '10', 'height': '10',
            'fill': color, 'stroke': '#07182C', 'stroke-width': '0.7',
        })
        count = int(item.get('count') or 0)
        add_text(f"{item.get('label') or 'Building'} ({count})", x + 40, row_y,
                 12, '500', '#07182C', 43, parent=identity_group)
    if len(schedule) > len(visible_schedule):
        add_text(f'Additional building groups: {len(schedule) - len(visible_schedule)}',
                 x + 22, y + 220 + len(visible_schedule) * 25, 11, '500', '#526577', 48,
                 parent=identity_group)
    legend_y = y + 232 + min(len(schedule), 6) * 25
    if len(schedule) > 6:
        legend_y += 22
    etree.SubElement(root, '{%s}line' % namespace, {
        'x1': f'{x + 22:g}', 'y1': f'{legend_y - 17:g}',
        'x2': f'{x + width - 18:g}', 'y2': f'{legend_y - 17:g}',
        'stroke': '#D8E2EC', 'stroke-width': '1',
    })
    add_text('SITE FEATURES', x + 22, legend_y, 13, '700', '#0A829B')
    legend_items = layout.get('architecturalColorLegend') or []
    row_height = max(21, min(30, (y + 830 - (legend_y + 24)) / max(1, len(legend_items))))
    for index, item in enumerate(legend_items):
        row_y = legend_y + 28 + index * row_height
        etree.SubElement(root, '{%s}rect' % namespace, {
            'x': f'{x + 22:g}', 'y': f'{row_y - 10:g}', 'width': '12', 'height': '12',
            'fill': str(item.get('color') or '#DCE6F0'),
            'stroke': '#07182C', 'stroke-width': '0.8',
        })
        add_text(item.get('label'), x + 44, row_y, 12, '500', '#07182C', 42)
    road_y = min(y + 838, legend_y + 34 + len(legend_items) * row_height)
    if layout.get('streets') or layout.get('siteCirculation'):
        etree.SubElement(root, '{%s}line' % namespace, {
            'x1': f'{x + 22:g}', 'y1': f'{road_y - 4:g}',
            'x2': f'{x + 36:g}', 'y2': f'{road_y - 4:g}',
            'stroke': '#AAB6C2', 'stroke-width': '7',
        })
        road_label = 'Road and access' if layout.get('streets') and layout.get('siteCirculation') else (
            'Recorded street' if layout.get('streets') else 'Internal access')
        add_text(road_label, x + 44, road_y, 11, '500', '#526577', 40)
    add_text('CONCEPTUAL PLAN | NOT TO SCALE', x + 22, y + 850, 10, '500', '#718296', 44)
    return etree.tostring(root, encoding='unicode')


def _visual_plan_site_svg_from_blocks(blocks):
    missing = _VISUAL_PLAN_SITE_SECTION_IDS - set(blocks)
    if missing:
        raise visual_plan_geometry.PlanGeometryError('لم تكتمل أقسام كود SVG.', 'PLANS_SVG_INCOMPLETE')
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">']
    for section, _description in _VISUAL_PLAN_SITE_SECTIONS:
        parts.extend(['<!-- LL_SECTION_START:' + section + ' -->', blocks[section],
                      '<!-- LL_SECTION_END:' + section + ' -->'])
    parts.append('</svg>')
    return _visual_plan_sanitize_svg('\n'.join(parts))
