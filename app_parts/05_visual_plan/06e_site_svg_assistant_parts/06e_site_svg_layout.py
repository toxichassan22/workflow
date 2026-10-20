# Projected SVG layout computation for the master site plan.

def _visual_plan_site_short_label(value, fallback='Building'):
    """English label for the drawing — never the Arabic source text.

    The general site plan is drawn in English whatever language the project
    data is in, so an unmatched Arabic label falls back to an English generic
    label instead of leaking Arabic characters into the drawing.
    """
    label = str(value or '').strip()
    label = re.sub(r'\([^)]*\)|\[[^]]*\]', '', label)
    label = re.sub(r'\s*[-–—|/]\s*.*$', '', label)
    label = re.sub(r'\s+', ' ', label).strip(' -–—|/,:;')
    if re.search(r'[\u0600-\u06FF]', label):
        english = _visual_concept_plan_component_en(label) if callable(globals().get('_visual_concept_plan_component_en')) else ''
        if english and not re.search(r'[\u0600-\u06FF]', english):
            return english[:32]
        if re.search(r'مول|تجار|معارض|محل', label):
            return 'Retail & Strip Mall'
        if re.search(r'فندق|ضياف', label):
            return 'Hotel Tower'
        if re.search(r'فلل|تاون|شاليه', label):
            return 'Townhouses'
        if re.search(r'مكتب|اداري|إداري', label):
            return 'Offices'
        if re.search(r'سكن|شقق', label):
            return 'Residential'
        if re.search(r'حديق|خضراء|لاندسكيب', label):
            return 'Landscaping'
        if re.search(r'موقف|مواقف|باركن', label):
            return 'Parking'
        if re.search(r'مسبح', label):
            return 'Swimming Pool'
        if re.search(r'بادل', label):
            return 'Padel Court'
        if re.search(r'أطفال|اطفال', label):
            return "Children's Playground"
        return fallback
    return label[:32] or fallback


def _visual_plan_site_street_label(source, direction=''):
    name = str(source.get('streetName') or '').strip()
    width = visual_plan_geometry.finite_number(source.get('streetWidth'))
    width_str = f', {width:g} m' if width is not None else ''
    if not name:
        return (direction.title() + ' Street' + width_str) if direction else ('Street' + width_str)
    if re.search(r'المدينة\s*(?:المنورة)?', name):
        clean_name = 'Madinah Road'
    elif re.search(r'الملك\s*عبد\s*العزيز', name):
        clean_name = 'King Abdulaziz Road'
    elif re.search(r'الملك\s*فهد', name):
        clean_name = 'King Fahd Road'
    elif re.search(r'الملك\s*عبد\s*الله', name):
        clean_name = 'King Abdullah Road'
    elif re.search(r'الأمير\s*سلطان|الامير\s*سلطان', name):
        clean_name = 'Prince Sultan Road'
    elif re.search(r'الأندلس|الاندلس', name):
        clean_name = 'Al Andalus Road'
    elif re.search(r'حراء', name):
        clean_name = 'Hira Street'
    elif re.search(r'صاري', name):
        clean_name = 'Sari Street'
    elif re.search(r'التحلية', name):
        clean_name = 'Tahlia Street'
    elif re.search(r'طريق\s+(.+)', name):
        m = re.search(r'طريق\s+(.+)', name)
        clean_name = (m.group(1).strip() + ' Road') if m else name
    elif re.search(r'شارع\s+(.+)', name):
        m = re.search(r'شارع\s+(.+)', name)
        clean_name = (m.group(1).strip() + ' Street') if m else name
    else:
        clean = _visual_plan_site_short_label(name, 'Street')
        clean_name = clean or (direction.title() + ' Street' if direction else 'Street')
    if re.search(r'[\u0600-\u06FF]', clean_name):
        # The plan is drawn in English: a recorded Arabic street name is named
        # by its position instead of being printed in Arabic.
        clean_name = (direction.title() + ' Street') if direction else 'Street'
    return clean_name + width_str


def _visual_plan_site_english_identity(value, limit=120):
    """Identity text for the drawing — English only.

    The plan is drawn in English whatever language the project data is in, so
    an Arabic project or developer name is left out instead of printed in
    Arabic: the fixed English title already identifies the drawing.
    """
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or ''))
    value = re.sub(r'\s+', ' ', value).strip()[:limit]
    if re.search(r'[\u0600-\u06FF]', value):
        return ''
    return value


def _visual_plan_site_identity_value(value, limit=120):
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or ''))
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def _visual_plan_site_feature_type(source, kind=''):
    text = ' '.join(str(source.get(key) or '') for key in
                    ('name', 'label', 'siteType', 'featureType')).lower()
    if re.search(r'\bpadel\b|بادل', text, re.IGNORECASE):
        return 'padel'
    if re.search(r'\bswimming\s*pool\b|\bpool\b|مسبح|حمام\s*سباحة', text, re.IGNORECASE):
        return 'pool'
    if re.search(r'\bplayground\b|\bchildren.?s?\s+play\b|ملعب\s*أطفال|العاب\s*أطفال', text, re.IGNORECASE):
        return 'playground'
    if kind == 'surface_parking' or re.search(r'\bparking\b|مواقف|جراج|باركينج', text, re.IGNORECASE):
        return 'parking'
    if re.search(r'\blandscape\b|\bopen\s*space\b|\bgreen\s*area\b|حدائق|مسطحات\s*خضراء|لاندسكيب|ممشى', text, re.IGNORECASE):
        return 'landscape'
    return 'landscape' if kind == 'landscape' else 'amenity'


def _visual_plan_site_projected_layout(scene, contract, program, identity=None):
    """Project current geometry and short labels onto a full-size SVG canvas."""
    polygons = []
    geometry = scene.get('geometry') or {}
    parcels = geometry.get('parcels') or []
    for parcel in parcels:
        if isinstance(parcel, dict) and isinstance(parcel.get('polygon'), list):
            polygons.append(parcel['polygon'])
    for building in scene.get('buildings') or []:
        if isinstance(building, dict) and isinstance(building.get('footprint'), list):
            polygons.append(building['footprint'])
    for area in scene.get('openAreas') or []:
        if isinstance(area, dict) and isinstance(area.get('polygon'), list):
            polygons.append(area['polygon'])
    points = [point for polygon in polygons for point in polygon
              if isinstance(point, (list, tuple)) and len(point) == 2
              and all(visual_plan_geometry.finite_number(axis) is not None for axis in point)]
    if not points:
        raise visual_plan_geometry.PlanGeometryError('حدود الأرض غير متاحة لرسم المخطط.', 'PLANS_SCENE_REQUIRED')
    min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
    min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
    span_x, span_y = max(max_x - min_x, 1), max(max_y - min_y, 1)
    canvas_width, canvas_height = 1600, 900
    bounds = (90, 150, 1000, 690)
    scale = min(bounds[2] / span_x, bounds[3] / span_y)
    offset_x = bounds[0] + (bounds[2] - span_x * scale) / 2
    offset_y = bounds[1] + (bounds[3] - span_y * scale) / 2

    def project(point):
        return [round(offset_x + (point[0] - min_x) * scale, 2),
                round(offset_y + (max_y - point[1]) * scale, 2)]

    buildings_by_id = {item['id']: item for item in program.get('buildings', [])}
    projected_buildings = []
    labels = []
    categories = []
    building_label_counts = {}
    for building in scene.get('buildings') or []:
        source = buildings_by_id.get(building.get('id')) or building
        label = _visual_plan_site_short_label(
            source.get('label') or source.get('name') or building.get('id') or 'Building')
        if label:
            building_label_counts[label.casefold()] = building_label_counts.get(label.casefold(), 0) + 1
    for building in scene.get('buildings') or []:
        source = buildings_by_id.get(building.get('id')) or building
        bands = source.get('bands') or []
        category = next((band.get('category') for band in bands
                         if band.get('kind') not in ('basement', 'roof')),
                        (bands[0].get('category') if bands else source.get('category') or 'amenity'))
        label = _visual_plan_site_short_label(
            source.get('label') or source.get('name') or building.get('id') or 'Building')
        unit_match = re.search(r'^unit_\d+_(\d+)$', str(building.get('id') or ''), re.IGNORECASE)
        display_label = ('V ' + unit_match.group(1).lstrip('0') if unit_match else label)
        if not unit_match and building_label_counts.get(label.casefold(), 0) > 1:
            id_suffix = re.search(r'(\d+)$', str(building.get('id') or ''))
            if id_suffix:
                display_label = (label[:19] + ' ' + id_suffix.group(1))[:24]
        if display_label:
            labels.append(display_label)
        if category not in categories:
            categories.append(category)
        projected_buildings.append({
            'id': building.get('id'), 'label': label, 'displayLabel': display_label,
            'category': category,
            'units': int(building.get('units') or source.get('units') or 1),
            'footprint': [project(point) for point in building.get('footprint') or []],
        })
    projected_parcels = [{'id': parcel.get('id'), 'points': [project(point) for point in parcel.get('polygon') or []]}
                         for parcel in parcels if isinstance(parcel, dict)]
    envelopes = []
    entries = []
    for entry in scene.get('entries') or []:
        try:
            point = entry.get('point')
            if isinstance(point, (list, tuple)) and len(point) == 2:
                entries.append({**{key: entry.get(key) for key in ('id', 'kind', 'buildingId', 'side')},
                                'point': project(point)})
                continue
            entries.append({**{key: entry.get(key) for key in ('id', 'kind', 'buildingId', 'side')},
                            'point': project(visual_plan_scene.entry_position(entry, scene))})
        except Exception:
            continue
    approved_site_items = program.get('siteItems') or scene.get('siteItems') or []
    site_items = {str(item.get('id')): item for item in approved_site_items}
    for source in approved_site_items:
        site_type = _visual_plan_site_feature_type(source)
        display_category = (site_type if site_type in ('pool', 'padel', 'playground', 'landscape')
                            else source.get('category'))
        if display_category and display_category not in categories:
            categories.append(display_category)
    open_areas = []
    for item in scene.get('openAreas') or []:
        source = site_items.get(str(item.get('componentId') or '')) or item
        feature_type = _visual_plan_site_feature_type(source, item.get('kind'))
        category = (feature_type if feature_type in ('pool', 'padel', 'playground', 'landscape') else
                    source.get('category') or ('parking' if item.get('kind') == 'surface_parking' else 'landscape'))
        label = _visual_plan_site_short_label(
            source.get('label') or visual_plan_renderer.USE_LABELS.get(category, 'Open space'),
            'Open space')
        if feature_type in ('pool', 'padel', 'playground'):
            label = {'pool': 'Swimming Pool', 'padel': 'Padel Court',
                     'playground': "Children's Playground"}[feature_type]
        if label and (feature_type != 'parking' or label not in labels):
            labels.append(label)
        if category not in categories:
            categories.append(category)
        open_areas.append({'id': item.get('id'), 'componentId': item.get('componentId'),
                           'kind': item.get('kind'), 'featureType': feature_type,
                           'category': category, 'label': label,
                           'points': [project(point) for point in item.get('polygon') or []]})
    # Ensure amenity facilities (pool, padel, playground) don't overlap directly on top of each other
    amenity_centroids = []
    for oa in open_areas:
        pts = oa.get('points') or []
        if len(pts) >= 3 and oa.get('featureType') in ('pool', 'padel', 'playground'):
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            for prev_cx, prev_cy in amenity_centroids:
                if abs(cx - prev_cx) < 45 and abs(cy - prev_cy) < 45:
                    shift_y = 48.0 if oa.get('featureType') != 'pool' else -48.0
                    shift_x = 35.0 if oa.get('featureType') == 'padel' else -35.0 if oa.get('featureType') == 'playground' else 0.0
                    oa['points'] = [[round(p[0] + shift_x, 2), round(p[1] + shift_y, 2)] for p in pts]
                    cx += shift_x
                    cy += shift_y
                    break
            amenity_centroids.append((cx, cy))
    raw_directions = contract.get('directions') or []
    if isinstance(raw_directions, dict):
        street_rows = raw_directions
    elif isinstance(raw_directions, list):
        street_rows = {item.get('direction'): item for item in raw_directions if isinstance(item, dict)}
    else:
        street_rows = {}
    streets = []
    for edge in visual_plan_scene.parcel_edges({'parcels': parcels}):
        direction = edge.get('direction')
        source = street_rows.get(direction, {})
        if not source.get('street'):
            continue
        start, end = project(edge['a']), project(edge['b'])
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            continue
        parcel = next((item for item in parcels if item.get('id') == edge.get('parcelId')), None)
        projected_parcel = [project(point) for point in (parcel or {}).get('polygon') or []]
        area = 0
        for index, point in enumerate(projected_parcel):
            following = projected_parcel[(index + 1) % len(projected_parcel)]
            area += point[0] * following[1] - following[0] * point[1]
        outward = (dy / length, -dx / length) if area > 0 else (-dy / length, dx / length)
        width = 28
        road_polygon = [start, end,
                        [round(end[0] + outward[0] * width, 2), round(end[1] + outward[1] * width, 2)],
                        [round(start[0] + outward[0] * width, 2), round(start[1] + outward[1] * width, 2)]]
        label = _visual_plan_site_street_label(source, direction)
        streets.append({'direction': direction, 'label': label, 'polygon': road_polygon,
                        'centerLine': [
                            [round(start[0] + outward[0] * width / 2, 2), round(start[1] + outward[1] * width / 2, 2)],
                            [round(end[0] + outward[0] * width / 2, 2), round(end[1] + outward[1] * width / 2, 2)]],
                        'labelPoint': [round((start[0] + end[0]) / 2 + outward[0] * width / 2, 2),
                                       round((start[1] + end[1]) / 2 + outward[1] * width / 2, 2)]})
        labels.append(label)
    site_circulation = []
    category_labels = {
        'pool': 'Swimming Pool', 'padel': 'Padel Court',
        'playground': "Children's Playground", 'landscape': 'Landscape/Open space',
        'parking': 'Parking',
    }
    legend = [{'label': category_labels.get(category, visual_plan_renderer.USE_LABELS.get(category, 'Amenities')),
               'category': category, 'color': visual_plan_renderer.COLORS.get(category,
                   {'pool': '#B6E1EF', 'padel': '#E7DDB8', 'playground': '#F5E5AB'}.get(
                       category, visual_plan_renderer.COLORS['amenity']))}
              for category in categories]
    for feature_type in ('pool', 'padel', 'playground'):
        if any(item.get('featureType') == feature_type for item in open_areas) and feature_type not in categories:
            categories.append(feature_type)
            legend.append({'label': category_labels[feature_type], 'category': feature_type,
                           'color': {'pool': '#B6E1EF', 'padel': '#E7DDB8',
                                     'playground': '#F5E5AB'}[feature_type]})
    identity = identity if isinstance(identity, dict) else {}
    identity = {
        'projectName': _visual_plan_site_english_identity(
            identity.get('projectNameEn') or contract.get('projectNameEn')
            or identity.get('projectName') or contract.get('projectName')),
        'developerName': _visual_plan_site_english_identity(identity.get('developerName')),
        'landArea': _visual_plan_site_identity_value(contract.get('landArea'), 32),
        'frontage': _visual_plan_site_identity_value(
            (contract.get('primaryFrontage') or {}).get('direction', '').title(), 32),
    }
    grouped_buildings = {}
    for item in projected_buildings:
        raw_label = item.get('label') or item.get('category') or 'Building'
        clean_label = re.sub(r'\s*\(\d+\)\s*$', '', raw_label).strip()
        if not clean_label or clean_label.lower() == 'building':
            category = item.get('category')
            clean_label = {
                'residential': 'Townhouses',
                'hospitality': 'Hotel Tower',
                'commercial': 'Strip Mall',
                'retail': 'Retail & F&B',
                'office': 'Offices',
            }.get(category, 'Building')
        key = clean_label.casefold()
        summary = grouped_buildings.setdefault(key, {'label': clean_label,
                                                      'category': item.get('category'), 'count': 0})
        summary['count'] += int(item.get('units') or 1)
    return {'viewBox': f'0 0 {canvas_width} {canvas_height}', 'siteDrawingBounds': list(bounds),
            'legendBounds': [1212, 40, 352, 820],
            'parcels': projected_parcels, 'buildableEnvelopes': envelopes,
            'buildings': projected_buildings, 'buildingSchedule': list(grouped_buildings.values()),
            'entries': entries, 'streets': streets, 'siteCirculation': site_circulation,
            'openAreas': open_areas,
            'identity': identity, 'approvedLabels': list(dict.fromkeys(labels)),
            'architecturalColorLegend': legend}
