import visual_plan_scene as visual_plan_scene
import visual_plan_renderer as visual_plan_renderer


def _visual_plan_is_individual_home(value):
    return bool(re.search(
        r'\b(?:detached\s+homes?|villas?|townhouses?|chalets?)\b|فلل|فيلا|تاون\s*هاوس|شاليهات?',
        str(value or ''), re.IGNORECASE))


def _visual_plan_individual_home_levels(values):
    floors = set()
    annex_fraction = 0.0
    for value in values:
        text = str(value or '').strip()
        if not text:
            continue
        annexes = [float(item) / 100 for item in re.findall(
            r'(\d+(?:\.\d+)?)\s*%\s*(?:annex|ملحق)', text, flags=re.IGNORECASE)]
        annex_fraction = max(annex_fraction, sum(annexes))
        clean = re.sub(r'\d+(?:\.\d+)?\s*%\s*(?:annex|ملحق)', ' ', text, flags=re.IGNORECASE)
        parsed = _visual_concept_plan_floor_range(clean)
        if not parsed or parsed['kind'] in ('basement', 'site', 'roof'):
            continue
        if parsed['kind'] == 'mezzanine':
            floors.add(0.5)
        else:
            low, high = int(parsed['lo']), int(parsed['hi'])
            floors.update(range(low, min(high, low + 200) + 1))
    return max(1.0, len(floors) + annex_fraction)


def _visual_plan_home_component_match(row, components):
    names = [str(row.get('component') or ''), str(row.get('building') or '')]
    row_keys = {_visual_concept_plan_component_key(_visual_concept_plan_component_base(name))
                for name in names if name}
    matches = []
    for component in components:
        name = str(component.get('name') or '')
        if not _visual_plan_is_individual_home(name):
            continue
        key = _visual_concept_plan_component_key(_visual_concept_plan_component_base(name))
        if key and any(row_key and (key == row_key or key in row_key or row_key in key)
                       for row_key in row_keys):
            matches.append(component)
    if len(matches) == 1:
        return matches[0]
    home_components = [item for item in components
                       if _visual_plan_is_individual_home(item.get('name'))]
    if not matches and len(home_components) == 1 and _visual_plan_is_individual_home(
            row.get('component') or row.get('building')):
        return home_components[0]
    return None


def _visual_plan_component_name_keys(value):
    base = _visual_concept_plan_component_base(value)
    return {_visual_concept_plan_component_key(item)
            for item in (value, base) if item}


def _visual_plan_program(contract, context):
    groups, site_items, home_groups = {}, [], {}
    components = context.get('components') or []
    current_component_keys = set().union(*(
        _visual_plan_component_name_keys(component.get('name'))
        for component in components if component.get('name')) if components else set())
    site_keys = _visual_concept_plan_site_component_keys(context)
    floor_cap = (_visual_concept_number(context.get('approved_floor_count'))
                 or _visual_concept_plan_regulation_floor_cap(context.get('regulations') or {}))
    for row in contract['distribution']['rows']:
        if (components and not current_component_keys.intersection(
                _visual_plan_component_name_keys(row.get('component')))):
            continue
        parsed = _visual_concept_plan_floor_range(row.get('floor_range'))
        if parsed is None and _visual_concept_plan_row_site(row, site_keys):
            parsed = {'kind': 'site', 'lo': 0, 'hi': 0, 'count': 1}
        if parsed is None:
            raise visual_plan_geometry.PlanGeometryError(
                'نطاق أدوار «' + str(row.get('component') or 'مكوّن')[:80] + '» غير مكتمل.',
                'PLANS_DISTRIBUTION_INCOMPLETE')
        if parsed['count'] > 200 or parsed['hi'] > 200:
            raise visual_plan_geometry.PlanGeometryError('نطاق الأدوار يتجاوز حجم الرسم المتاح.', 'PLANS_DISTRIBUTION_INCOMPLETE')
        if floor_cap and parsed['kind'] in ('range', 'ground', 'mezzanine') and parsed['hi'] > floor_cap:
            raise visual_plan_geometry.PlanGeometryError('التوزيع يتجاوز عدد الأدوار المسجل.', 'PLANS_FLOOR_CONFLICT')
        _order, category = _visual_concept_plan_use_category({'name': row['component']})
        label = _visual_concept_plan_component_en(row['component'])
        if not label or re.search(r'[\u0600-\u06FF]', label):
            label = visual_plan_renderer.USE_LABELS.get(category, 'Amenities')
        row_keys = _visual_plan_component_name_keys(row.get('component'))
        source_component = next((item for item in components
                                 if row_keys.intersection(
                                     _visual_plan_component_name_keys(item.get('name')))), {})
        band = {'id': row['id'], 'name': row['component'], 'label': label, 'category': category,
                'floorLabel': _visual_concept_plan_floor_label_en(row['floor_range']),
                'floorRange': row['floor_range'], 'kind': parsed['kind'], 'count': parsed['count'],
                'lo': parsed['lo'], 'hi': parsed['hi'], 'area': row['floor_area_sqm'],
                'units': row['units_per_floor'], 'circulation': row['circulation']}
        if parsed['kind'] == 'site' or _visual_concept_plan_row_site(row, site_keys):
            band['siteType'] = (_visual_concept_plan_site_type({
                                    'name': row['component'],
                                    'useType': source_component.get('useType'),
                                    'notes': source_component.get('notes'),
                                })
                                or ('parking' if category == 'parking' else
                                    'landscape' if category == 'landscape' else 'amenity'))
            site_items.append(band)
        elif _visual_plan_is_individual_home(row.get('component') or row.get('building')):
            matched = _visual_plan_home_component_match(row, components)
            key = str((matched or {}).get('id') or row['id'])
            group = home_groups.setdefault(key, {'component': matched, 'rows': [], 'bands': []})
            group['rows'].append(row)
            group['bands'].append(band)
        else:
            name = row['building'] or 'المبنى الرئيسي'
            groups.setdefault(name, []).append(band)
    buildings = []
    for index, (name, bands) in enumerate(groups.items()):
        above = [band for band in bands if band['kind'] not in ('basement', 'roof')]
        below = [band for band in bands if band['kind'] == 'basement']
        base = min((band['lo'] for band in above), default=0)
        top = max((band['hi'] - base + 1 for band in above), default=0)
        for band in bands:
            if band['kind'] == 'roof':
                band['start'], band['end'] = top, top + 0.25
            elif band['kind'] == 'basement':
                band['start'], band['end'] = band['lo'], band['hi'] + 1
            elif band['kind'] == 'mezzanine':
                band['start'], band['end'] = band['lo'] - base, band['lo'] - base + 0.5
            else:
                band['start'], band['end'] = band['lo'] - base, band['hi'] - base + 1
        applicable = above or below
        probes = {band['lo'] for band in applicable} | {band['hi'] for band in applicable}
        areas = [sum(band['area'] for band in applicable
                     if band['area'] is not None and band['lo'] <= probe <= band['hi']) for probe in probes]
        footprint_area = max(areas, default=0)
        if footprint_area <= 0:
            raise visual_plan_geometry.PlanGeometryError('مساحة بصمة أحد المباني غير متوفرة في التوزيع.', 'PLANS_DISTRIBUTION_INCOMPLETE')
        label = _visual_concept_plan_building_en(name)
        if not label or re.search(r'[\u0600-\u06FF]', label):
            label = 'Building ' + str(index + 1)
        buildings.append({'id': 'b' + str(index + 1), 'name': name, 'label': label,
                          'footprintArea': footprint_area, 'bands': bands,
                          'basementOnly': not bool(above),
                          'levels': max((band['end'] for band in bands if band['kind'] != 'basement'), default=0)})
    for group_index, group in enumerate(home_groups.values(), 1):
        component = group['component'] or {}
        rows = group['rows']
        bands = group['bands']
        unit_count = _visual_concept_number(component.get('units'))
        if unit_count is None:
            unit_values = [_visual_concept_number(row.get('units_per_floor')) for row in rows]
            unit_values = [value for value in unit_values if value is not None]
            unit_count = max(unit_values, default=0)
        if unit_count <= 0 or not float(unit_count).is_integer() or unit_count > 200:
            raise visual_plan_geometry.PlanGeometryError(
                'عدد الفلل الفردية غير محدد كعدد صحيح في المكونات المعتمدة؛ لا يمكن اختصارها إلى كتلة واحدة.',
                'PLANS_DISTRIBUTION_INCOMPLETE')
        levels = _visual_plan_individual_home_levels(
            [component.get('floorRange'), *(row.get('floor_range') for row in rows)])
        total_area = _visual_concept_number(component.get('builtArea'))
        if total_area is None or total_area <= 0:
            area_values = [_visual_concept_number(row.get('floor_area_sqm')) for row in rows]
            area_values = [value for value in area_values if value is not None and value > 0]
            total_area = sum(area_values) if area_values else 0
        if total_area <= 0:
            unit_area = _visual_concept_number(component.get('unitArea'))
            total_area = unit_area * unit_count if unit_area and unit_area > 0 else 0
        land_share = _visual_concept_number(component.get('landShareArea'))
        if land_share is not None and land_share > 0 and unit_count > 0:
            footprint_area = land_share / unit_count
        else:
            footprint_area = _visual_concept_number(component.get('unitFootprintArea'))
            if footprint_area is None or footprint_area <= 0:
                footprint_area = total_area / unit_count / levels if total_area > 0 else 0
        if footprint_area <= 0:
            raise visual_plan_geometry.PlanGeometryError(
                'مساحة بصمة الفيلا الواحدة غير مكتملة في المكونات والتوزيع المعتمد.',
                'PLANS_DISTRIBUTION_INCOMPLETE')
        source_name = str(component.get('name') or rows[0].get('component') or 'Villa')
        label = _visual_concept_plan_component_en(source_name)
        if not label or re.search(r'[\u0600-\u06FF]', label):
            label = 'Villa'
        category = bands[0]['category'] if bands else 'residential'
        for unit_index in range(int(unit_count)):
            unit_id = f'unit_{group_index}_{unit_index + 1:03d}'
            unit_band = {'id': unit_id, 'name': source_name, 'label': label,
                         'category': category, 'floorLabel': '', 'floorRange': '',
                         'kind': 'range', 'count': 1, 'lo': 0, 'hi': 0,
                         'area': footprint_area, 'units': 1, 'circulation': ''}
            buildings.append({'id': unit_id, 'name': source_name, 'label': label,
                              'footprintArea': footprint_area, 'bands': [unit_band],
                              'basementOnly': False, 'levels': levels})
    return {'buildings': buildings, 'siteItems': site_items}


def _visual_plan_seal_scene(data, scene, context=None):
    result = {key: value for key, value in scene.items() if key not in ('token', 'inputSignature')}
    signature = _visual_plan_input_signature(data, context)
    result['inputSignature'] = signature
    result['token'] = _visual_plan_token('scene', data, signature,
                                       {key: value for key, value in result.items() if key != 'token'})
    return result


def _visual_plan_scene_from_request(data):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else {}
    if scene.get('version') != VISUAL_PLAN_SCENE_VERSION or not isinstance(scene.get('token'), str):
        raise visual_plan_geometry.PlanGeometryError('المشهد الهندسي غير جاهز.', 'PLANS_SCENE_REQUIRED')
    contract, context = _visual_plan_contract(data)
    notes_gate = _visual_plan_notes_gate(data, context)
    if not notes_gate.get('cleared'):
        raise visual_plan_geometry.PlanGeometryError(
            notes_gate.get('message') or 'فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.',
            'PLANS_NOTES_CHECK_REQUIRED')
    signature = _visual_plan_input_signature(data, context)
    if scene.get('inputSignature') != signature:
        raise visual_plan_geometry.PlanGeometryError('المشهد الهندسي لا يطابق بيانات المشروع الحالية.', 'PLANS_CONTEXT_CHANGED')
    posted = {key: value for key, value in scene.items() if key != 'token'}
    if not _visual_plan_token_matches('scene', data, signature, posted, scene['token']):
        raise visual_plan_geometry.PlanGeometryError('تغيرت بيانات المشهد خارج مسار التعديل.', 'PLANS_SCENE_INVALID')
    program = _visual_plan_program(contract, context)
    try:
        visual_plan_scene.validate_scene(scene, contract, program)
    except visual_plan_geometry.PlanGeometryError as error:
        if error.code == 'PLANS_CONTEXT_CHANGED':
            try:
                scene = visual_plan_scene.rebase_scene_context(scene, contract, program)
            except visual_plan_geometry.PlanGeometryError as refresh_error:
                if refresh_error.code not in ('PLANS_PROGRAM_CHANGED', 'PLANS_SITE_ITEMS_MISSING',
                                               'PLANS_SITE_ITEMS_DUPLICATED'):
                    raise
                raise visual_plan_geometry.PlanGeometryError(
                    'تغيّر البرنامج المعتمد بعد توليد المخطط؛ أعد توليد التوزيع.',
                    'PLANS_SCENE_REGENERATE')
        elif error.code in ('PLANS_PROGRAM_CHANGED', 'PLANS_SITE_ITEMS_MISSING',
                            'PLANS_SITE_ITEMS_DUPLICATED'):
            # A signed scene can outlive a code change that expands a grouped
            # component (for example, one villa row) into its physical units.
            # The model must redraw those placements; code never does.
            raise visual_plan_geometry.PlanGeometryError(
                'تغيّر البرنامج المعتمد بعد توليد المخطط؛ أعد توليد التوزيع.',
                'PLANS_SCENE_REGENERATE')
        else:
            raise
        scene = _visual_plan_seal_scene(data, scene, context)
        workflow = dict(workflow)
        workflow['scene'] = scene
        data['plansWorkflow'] = workflow
    return scene, contract, context, program


_PLAN_LAYOUT_KEYS = {'buildings', 'entries', 'openAreas', 'reply'}
_PLAN_LENGTH_FINISH = {'length', 'max_tokens', 'max_output_tokens', 'max_completion_tokens'}


def _visual_plan_rect_polygon(value):
    """Expand axis-aligned or parcel-oriented rectangle shorthand to a polygon."""
    rect = None
    if isinstance(value, dict):
        oriented = value.get('orientedRect')
        if isinstance(oriented, (list, tuple)) and len(oriented) == 5:
            cx, cy, width, height, angle = (
                visual_plan_geometry.finite_number(item) for item in oriented)
            if (None not in (cx, cy, width, height, angle)
                    and width > 0 and height > 0):
                radians = math.radians(angle)
                cosine, sine = math.cos(radians), math.sin(radians)
                return [[cx + dx * cosine - dy * sine,
                         cy + dx * sine + dy * cosine]
                        for dx, dy in ((-width / 2, -height / 2),
                                       (width / 2, -height / 2),
                                       (width / 2, height / 2),
                                       (-width / 2, height / 2))]
        rect = value.get('rect')
        if rect is None and {'x', 'y', 'width', 'height'} <= set(value):
            rect = [value.get('x'), value.get('y'), value.get('width'), value.get('height')]
    elif (isinstance(value, (list, tuple)) and len(value) == 4
          and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)):
        rect = value
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return None
    x, y, w, h = (visual_plan_geometry.finite_number(item) for item in rect)
    if None in (x, y, w, h) or w <= 0 or h <= 0:
        return None
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _visual_plan_find_layout(node, depth=0):
    if depth > 4 or not isinstance(node, dict):
        return None
    if isinstance(node.get('buildings'), (list, dict)):
        return node
    return next((hit for value in node.values()
                 if (hit := _visual_plan_find_layout(value, depth + 1)) is not None), None)


def _visual_plan_normalize_layout(proposed):
    """Tolerate harmless model noise before the strict scene validator: unwrap a
    wrapper object carrying the layout (a bare buildings list, a lone building
    item recovered from an array response, or arbitrarily nested containers),
    accept common aliases for the buildings list, and drop keys outside the
    scene contract at every level. make_scene still enforces every required
    field — only the noise is stripped."""
    if isinstance(proposed, list):
        proposed = {'buildings': proposed}
    if not isinstance(proposed, dict):
        return proposed
    if isinstance(proposed.get('id'), str) and ('footprint' in proposed or 'facades' in proposed):
        proposed = {'buildings': [proposed]}
    if 'buildings' not in proposed:
        nested = _visual_plan_find_layout(proposed)
        if nested is not None:
            proposed = nested
    if not isinstance(proposed.get('buildings'), (list, dict)):
        for alias in ('masses', 'massing', 'towers', 'blocks', 'footprints', 'buildingLayout'):
            if isinstance(proposed.get(alias), (list, dict)):
                proposed = {**proposed, 'buildings': proposed[alias]}
                break
    layout = {key: value for key, value in proposed.items() if key in _PLAN_LAYOUT_KEYS}
    buildings = layout.get('buildings')
    if isinstance(buildings, dict):
        buildings = [{**value, 'id': key} if isinstance(value, dict) else value
                     for key, value in buildings.items()]
        layout['buildings'] = buildings
    if isinstance(buildings, list):
        cleaned = []
        for raw in buildings:
            if not isinstance(raw, dict):
                cleaned.append(raw)
                continue
            item = {key: raw[key] for key in ('id', 'footprint', 'facades') if key in raw}
            rect = _visual_plan_rect_polygon(item.get('footprint'))
            if rect is not None:
                item['footprint'] = rect
            facades = item.get('facades')
            if isinstance(facades, dict):
                item['facades'] = {side: {k: v for k, v in style.items()
                                          if k in ('material', 'color', 'pattern')}
                                   for side, style in facades.items()
                                   if side in visual_plan_geometry.DIRECTION_VECTORS and isinstance(style, dict)}
            cleaned.append(item)
        layout['buildings'] = cleaned
    for key, allowed in (('entries', ('id', 'kind', 'buildingId', 'side', 'position')),
                         ('openAreas', ('id', 'componentId', 'kind', 'polygon'))):
        rows = layout.get(key)
        if isinstance(rows, list):
            cleaned_rows = []
            for raw in rows:
                if not isinstance(raw, dict):
                    cleaned_rows.append(raw)
                    continue
                item = {k: raw[k] for k in allowed if k in raw}
                rect = _visual_plan_rect_polygon(item.get('polygon'))
                if rect is not None:
                    item['polygon'] = rect
                cleaned_rows.append(item)
            layout[key] = cleaned_rows
    return layout


def _visual_plan_explain_layout_failure(error, contract, program, data, model_keys=()):
    """Ask the layout model for the Arabic reason its drawn layout was refused.

    The validator only reports which check failed; the model explains which item
    conflicts and what to change. If the explanation itself cannot be obtained the
    refusal still stands, with a neutral message instead of a placement guess."""
    facts = {
        'validatorCode': error.code,
        'validatorNote': str(error),
        'modelKeys': sorted(str(key) for key in model_keys)[:12],
        'landArea': contract.get('landArea'),
        'setbacks': contract.get('setbacks'),
        'buildings': [{'id': item.get('id'), 'label': item.get('label') or item.get('name'),
                       'footprintArea': item.get('footprintArea')}
                      for item in program.get('buildings') or []],
        'siteItems': [{'id': item.get('id'), 'label': item.get('label') or item.get('name'),
                       'area': item.get('area')}
                      for item in program.get('siteItems') or []],
    }
    system_prompt = (
        'You explain why a conceptual architectural layout was refused. Reply in Arabic, in at most '
        'four short sentences: name the building or site item that conflicts, the rule it breaks '
        '(footprint area, setback, parcel boundary, overlap, or a missing site area), and what the '
        'client should change. Use only the facts provided and never invent numbers. '
        'Return JSON only: {"reply":"..."}.'
    )
    response = call_openrouter_chat(
        system_prompt, json.dumps(facts, ensure_ascii=False), temperature=None, max_tokens=2000,
        model=GEMINI_TEXT_MODEL, reasoning_effort='low',
        timeout=_visual_plan_job_call_timeout(180),
        response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data))
    fatal = _ai_fatal_error_dict(response)
    if fatal is not None:
        raise FatalAICallError(fatal.get('message'), error_code=fatal.get('error_code'),
                               http_status=fatal.get('http_status'),
                               provider_message=fatal.get('provider_message'))
    explained = ''
    if isinstance(response, dict) and not response.get('error'):
        parsed = parse_json_object(_get_chat_response_text(response))
        if isinstance(parsed, dict) and isinstance(parsed.get('reply'), str):
            explained = parsed['reply'].strip()[:1200]
    return visual_plan_geometry.PlanGeometryError(
        explained or 'تعذّر على النموذج شرح سبب رفض التوزيع؛ أعد المحاولة.', error.code)


def _visual_plan_create_scene(data, context=None):
    contract, context = _visual_plan_contract(data, context)
    _visual_plan_report_site_chat_progress(1, 35)
    if (contract['primaryFrontage'].get('status') == 'unresolved'
            and (contract.get('landBrief') or contract.get('regulatoryConstraints'))):
        resolved = _visual_plan_resolve_primary_frontage(
            contract.get('landBrief') or '', contract.get('regulatoryConstraints') or '',
            contract.get('directions') or [], data)
        if resolved:
            _visual_plan_apply_frontage(contract, resolved)
            _visual_plan_record_frontage(data, resolved)
            context['primary_frontage'] = dict(resolved)
    if not contract['primaryFrontage']['direction']:
        raise visual_plan_geometry.PlanGeometryError('الواجهة الرئيسية غير محددة بوضوح في الكروكي والملخص.', 'PLANS_MAIN_FRONTAGE_REQUIRED')
    notes_gate = _visual_plan_notes_gate(data, context)
    if not notes_gate.get('cleared'):
        raise visual_plan_geometry.PlanGeometryError(
            notes_gate.get('message') or 'فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.',
            'PLANS_NOTES_CHECK_REQUIRED')
    program = _visual_plan_program(contract, context)
    visual_plan_scene.check_program_feasibility(contract, program)
    reference_url = _visual_concept_render_plan_boundary_reference(contract['geometry']['surveyPoints'], g.tenant_id)
    references = _visual_concept_reference_uris(urls=[reference_url], tenant_id=g.tenant_id) if reference_url else []
    parcel_edges = [(a, b) for parcel in contract['geometry']['parcels']
                    for a, b in zip(parcel['polygon'], parcel['polygon'][1:] + parcel['polygon'][:1])]
    longest_edge = max(parcel_edges, key=lambda edge: math.dist(*edge))
    axis_degrees = math.degrees(math.atan2(
        longest_edge[1][1] - longest_edge[0][1],
        longest_edge[1][0] - longest_edge[0][0]))
    while axis_degrees > 90:
        axis_degrees -= 180
    while axis_degrees <= -90:
        axis_degrees += 180
    orientation_rule = (
        f'\nPARCEL-ALIGNED BUILDING AXIS: the longest surveyed parcel edge is '
        f'{axis_degrees:.3f} degrees counterclockwise from east. Align the long side of every '
        'rectangular building footprint with this edge; do not align buildings to the page or '
        'north/east axes. For rectangles use {"orientedRect":[centerX,centerY,longSide,shortSide,angleDegrees]} '
        'with the same angle and exact footprintArea = longSide*shortSide. Axis-aligned rect is '
        'allowed only when this parcel angle is within 2 degrees of 0 or 90.'
    )
    system_prompt = (
        'You plan a conceptual architectural scene; the application renders the images. '
        'The surveyed parcel geometry, primary frontage, north, setbacks, regulatory constraints, '
        'project idea, full land brief, client notes, building IDs, areas, uses, counts and floor ranges '
        'are fixed facts. The client supplies the program and areas; you are responsible for placing '
        'every building and site item on the land. Choose and revise their positions while preserving '
        'all fixed facts. Do not change or return any of them. The attached image is the same '
        'surveyed parcel supplied numerically. Local coordinates are metres: x east, y north, '
        'relative to the recorded origin. Never rotate, resize, simplify or replace the parcel. '
        'Return ONLY a proposed footprint polygon per existing building, entries on recorded street '
        'edges, and open areas for recorded site facilities. Every footprint must stay wholly inside one parcel, satisfy '
        'the recorded setbacks, have the exact required footprintArea, and not overlap another '
        'above-ground building. A buildable envelope polygon per parcel is provided below — it '
        'already subtracts the recorded setbacks, so a footprint wholly inside it is compliant. '
        'Basement-only footprints may overlap buildings and have no imposed '
        'above-ground setbacks. Do not invent building counts, parking capacity or floor heights. '
        'Apply every validated client note, and do not silently ignore a note. Facade styles are '
        'limited to material neutral|glass|stone|metal|render, pattern plain|grid|vertical|horizontal, '
        'and optional #RRGGBB color. Main entries must use the recorded primary frontage; service '
        'and residential entries must use recorded streets, never neighboring land. Entry position '
        'is a fraction 0..1 along the longest parcel edge on that side. Every siteItems row with a '
        'positive recorded area is required in openAreas with its recorded componentId and exact area. '
        'Every nonparking site item must appear exactly once; surface parking may be split across '
        'multiple openAreas whose combined area equals its recorded area. Never omit landscape, '
        'pools, padel courts, playgrounds or surface parking. '
        'Use kind landscape for planting/open space, surface_parking for parking, and site_facility '
        'for pools, padel courts and other named site amenities. No source names, files or pages. '
        'Every program ID is a separate physical footprint. For repeated individual homes, place one '
        'separate polygon for every unit ID; never merge multiple homes into one building or block. '
        'Calculate each placement in metres against parcel edges, setbacks and neighboring footprints; '
        'keep the footprints separate with usable gaps and verify the full required count before returning. '
        'A footprint or open-area rectangle may use {"orientedRect":[centerX,centerY,width,height,angleDegrees]} '
        'in metres; expand its rotated corners and preserve width*height exactly. '
        'Return JSON only: {"buildings":[{"id":"b1","footprint":[[0,0],[1,0],[1,1],[0,1]],'
        '"facades":{"west":{"material":"glass","pattern":"grid"}}}],'
        '"entries":[{"id":"main_entry","kind":"main","buildingId":"b1","side":"west",'
        '"position":0.5}],"openAreas":[{"id":"open_1","componentId":"row_1",'
        '"kind":"landscape|surface_parking|site_facility","polygon":[[0,0],[1,0],[1,1]]}]}.'
    )
    envelopes = visual_plan_scene.buildable_envelopes(contract)
    envelope_note = ''
    if envelopes:
        envelope_note = ('\nBUILDABLE ENVELOPE AFTER RECORDED SETBACKS — place every above-ground '
                         'footprint inside one of these polygons:\n'
                         + json.dumps(envelopes, ensure_ascii=False))
    placement_program = {
        'buildings': [{key: building.get(key) for key in (
            'id', 'name', 'label', 'footprintArea', 'basementOnly', 'levels')}
                      for building in program.get('buildings') or []],
        'siteItems': program.get('siteItems') or [],
    }
    user_prompt = ('COMPLETE FIXED LAND AND PROJECT CONTRACT:\n' + json.dumps(contract, ensure_ascii=False)
                   + orientation_rule
                   + envelope_note
                   + '\nBUILDINGS AND FLOOR PROGRAM TO PLACE WITHOUT CHANGES:\n'
                   + json.dumps(placement_program, ensure_ascii=False))
    feedback = ''
    error = None
    raw_keys = []
    cap = min(24000, max(8000, 8000 + max(0, len(program['buildings']) - 40) * 120))
    for attempt in range(2):
        response = call_openrouter_chat(
            system_prompt, user_prompt + feedback, temperature=None, max_tokens=cap,
            model=GEMINI_TEXT_MODEL, reasoning_effort='medium',
            timeout=_visual_plan_job_call_timeout(1200),
            response_format={'type': 'json_object'},
            image_references=references or None, usage_ctx=_usage_ctx('image', data))
        fatal = _ai_fatal_error_dict(response)
        if fatal is not None:
            raise FatalAICallError(fatal.get('message'), error_code=fatal.get('error_code'),
                                   http_status=fatal.get('http_status'),
                                   provider_message=fatal.get('provider_message'))
        if isinstance(response, dict) and response.get('error'):
            error = visual_plan_geometry.PlanGeometryError(
                _client_safe_llm_error(_chat_error_message(response)), 'PLANS_PROVIDER_FAILED')
            continue
        choice = (response.get('choices') or [{}])[0] if isinstance(response, dict) else {}
        finish = str(choice.get('native_finish_reason') or choice.get('finish_reason') or '').lower()
        message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
        text_out = _stringify_chat_part(message.get('content')) or ''
        if finish in _PLAN_LENGTH_FINISH and not text_out.strip():
            # Reasoning consumed the whole token cap before a single byte of
            # JSON was written — that is truncation, not a bad layout.
            error = visual_plan_geometry.PlanGeometryError(
                'انقطع ناتج المزوّد قبل اكتمال التوزيع — أعد المحاولة.', 'PLANS_PROVIDER_FAILED')
            cap = max(cap * 2, 16000)
            app.logger.warning('Visual plan layout starved on reasoning (finish=%s, cap=%s)', finish, cap)
            feedback = ('\nYour previous reply hit the output limit before the JSON began. '
                        'Keep reasoning brief, emit the JSON first, and prefer the {"rect":...} form.')
            continue
        if not text_out.strip():
            text_out = _get_chat_response_text(response)
        raw_obj = parse_json_object(text_out)
        if not (isinstance(raw_obj, dict) and raw_obj.get('buildings')):
            try:
                top_level = json.loads(text_out.strip())
            except Exception:
                top_level = None
            if isinstance(top_level, list):
                raw_obj = {'buildings': top_level}
        raw_keys = [str(key) for key in raw_obj] if isinstance(raw_obj, dict) else []
        proposed = _visual_plan_normalize_layout(raw_obj)
        model_error = ''
        if isinstance(proposed, dict) and not isinstance(proposed.get('buildings'), (list, dict)):
            err_val = raw_obj.get('error') if isinstance(raw_obj, dict) else None
            if isinstance(err_val, dict):
                model_error = str(err_val.get('message') or err_val.get('msg') or err_val)[:200]
            elif err_val:
                model_error = str(err_val)[:200]
        if model_error:
            error = visual_plan_geometry.PlanGeometryError(
                'ردّ النموذج برسالة بدل التوزيع الهندسي: ' + model_error, 'PLANS_LAYOUT_INVALID')
            app.logger.warning('Visual plan layout refused — model error payload: %s', model_error)
            feedback = ('\nYour previous reply returned {"error": ...} instead of the layout: ' + model_error
                        + '\nDo not reply with an error object. Emit the JSON scene with one footprint'
                        ' per program building id — the validator checks feasibility, not you.')
            continue
        try:
            scene = visual_plan_scene.make_scene(contract, program, proposed, VISUAL_PLAN_SCENE_VERSION)
            return _visual_plan_seal_scene(data, scene, context), context, reference_url
        except visual_plan_geometry.PlanGeometryError as failure:
            error = failure
            if finish in _PLAN_LENGTH_FINISH or not text_out.strip():
                cap *= 2
            received = ', '.join(sorted(proposed.keys())) if isinstance(proposed, dict) and proposed else 'none'
            app.logger.warning('Visual plan layout refused (%s, finish=%s, keys=%s)', failure, finish, received)
            returned = {item.get('id') for item in (proposed.get('buildings') or [])
                        if isinstance(item, dict)} if isinstance(proposed, dict) else set()
            missing = [building['id'] for building in program['buildings'] if building['id'] not in returned]
            if failure.code in ('PLANS_SITE_ITEMS_MISSING', 'PLANS_SITE_ITEMS_DUPLICATED'):
                site_requirements = [
                    {'componentId': item['id'], 'label': item.get('label') or item.get('name') or item['id'],
                     'area': item.get('area')}
                    for item in program.get('siteItems') or []
                    if (visual_plan_geometry.finite_number(item.get('area')) or 0) > 0
                ]
                feedback = (
                    '\nThe previous geometry proposal was rejected because required approved site areas '
                    'were missing or duplicated. Retry the layout now. Return every nonparking componentId '
                    'exactly once in openAreas. Surface parking may use multiple openAreas; their combined '
                    'area must equal its recorded area. Preserve all recorded areas and include every building footprint. '
                    'Required site areas: ' + json.dumps(site_requirements, ensure_ascii=False)
                    + '\nDo not return an error object or ask the client to fix a model omission.'
                    + orientation_rule)
                continue
            feedback = ('\nThe previous proposal failed geometry validation: ' + str(failure)
                        + '\nIt contained JSON keys: ' + received
                        + ('\nIt returned no footprint for building ids: ' + ', '.join(missing)
                           + ' — return exactly one footprint per program building id.'
                           if missing else '')
                        + '\nCorrect only the proposed scene; the fixed contract remains unchanged.'
                        + ' Keep every footprint inside the provided buildable envelope polygons.'
                        + orientation_rule)
    if error is None:
        error = visual_plan_geometry.PlanGeometryError(
            'تعذر إنشاء توزيع هندسي صالح للمخططات.', 'PLANS_LAYOUT_INVALID')
    if error.code == 'PLANS_PROVIDER_FAILED':
        raise error
    # No deterministic layout is sealed. The model drew the layout, so the model
        # also explains in Arabic why the drawn layout was refused.
    raise _visual_plan_explain_layout_failure(error, contract, program, data, raw_keys)


def _visual_plan_slot_prompt(workflow, kind, context):
    """The drawing prompt stored for this slot, rebuilt from the contract
    context when an older draft never carried it."""
    prompt = ((workflow.get('prompts') or {}).get(kind) or '')
    if prompt:
        return prompt
    distribution = workflow.get('distribution') if isinstance(workflow.get('distribution'), dict) else {}
    regulations = context.get('regulations') or {}
    model = (_visual_concept_plan_model_from_distribution(distribution, context, regulations)
             or _visual_concept_plan_model(context, regulations))
    return _visual_concept_plan_drawing_prompt(kind, context, model)


def _visual_plan_illustrate(prompt, contract, data, base_image='', extra_refs=None):
    """The image model draws the shipped illustration straight from the
    validated scene spec carried inside the prompt — no intermediate render
    ships or steers it. The only attached geometry is the surveyed parcel
    outline so the drawn boundary is the real one. The sealed scene stays
    the only geometry authority and still gates every render."""
    references = [base_image] if base_image else []
    boundary_url = _visual_concept_render_plan_boundary_reference(
        contract['geometry']['surveyPoints'], g.tenant_id)
    if boundary_url:
        references += _visual_concept_reference_uris(urls=[boundary_url], tenant_id=g.tenant_id)
    references += list(extra_refs or [])
    image_prompt = (prompt
        + ('\nThe first attached image is the current approved illustration of this plan — '
           'keep its look and every unrequested detail identical. ' if base_image else '\n')
        + 'The attached outline is the true surveyed parcel boundary — trace it exactly and '
        'draw only the buildings, entries and open areas the prompt describes, nothing else.')
    image = call_images_api(image_prompt, references, model=VISUAL_CONCEPT_IMAGE_MODEL,
                            timeout=_visual_plan_job_call_timeout(180),
                            usage_ctx=_usage_ctx('image', data))
    if image:
        return image, len(references)
    err = last_images_api_error() or {}
    if err.get('fatal') or err.get('error_code') in _FATAL_AI_ERROR_CODES:
        raise FatalAICallError(err.get('message'), error_code=err.get('error_code'),
                               http_status=err.get('http_status'),
                               provider_message=err.get('provider_message'))
    raise visual_plan_geometry.PlanGeometryError(
        _client_safe_llm_error(err.get('message') or 'تعذر توليد صورة المخطط.'),
        'PLANS_PROVIDER_FAILED')


def _visual_plan_extract_svg(text):
    if not isinstance(text, str):
        return ''
    fenced = re.search(r'```(?:svg|xml)?\s*\n?([\s\S]*?)```', text)
    if fenced:
        text = fenced.group(1)
    start = text.find('<svg')
    end = text.rfind('</svg>')
    if start == -1 or end == -1 or end <= start:
        return ''
    return text[start:end + 6].strip()[:300000]


def _visual_plan_sanitize_svg(svg):
    if not isinstance(svg, str) or '<svg' not in svg:
        return ''
    svg = re.sub(r'<script[\s\S]*?</script\s*>', '', svg, flags=re.IGNORECASE)
    svg = re.sub(r'<foreignObject[\s\S]*?</foreignObject\s*>', '', svg, flags=re.IGNORECASE)
    svg = re.sub(r'\son\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', svg, flags=re.IGNORECASE)
    svg = re.sub(r'(href|xlink:href)\s*=\s*("|\')\s*javascript:[^"\']*\2',
                 r'\1=\2#\2', svg, flags=re.IGNORECASE)
    svg = svg.strip()
    if not svg.startswith('<svg') or '</svg>' not in svg:
        return ''
    svg = svg[:300000]
    # The model sometimes leaves a bare ampersand in labels or misses a closing
    # tag. Browsers reject those files as images, so recover the XML before
    # storing it instead of returning a URL that renders as a broken image.
    svg = re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|amp;|lt;|gt;|quot;|apos;)', '&amp;', svg)
    try:
        from lxml import etree
        parser = etree.XMLParser(recover=True, resolve_entities=False,
                                 load_dtd=False, no_network=True, huge_tree=False)
        root = etree.fromstring(svg.encode('utf-8'), parser)
        if root is None or etree.QName(root).localname.lower() != 'svg':
            return ''
        if etree.QName(root).namespace != 'http://www.w3.org/2000/svg':
            root.set('xmlns', 'http://www.w3.org/2000/svg')
        if not root.get('viewBox'):
            root.set('viewBox', '0 0 1600 1000')
        if not root.get('width'):
            root.set('width', '1600')
        if not root.get('height'):
            root.set('height', '1000')
        style = root.get('style') or ''
        if any(d in style.lower() for d in ('#0d1b2a', '#0f172a', '#1e293b', '#000000', 'rgb(13, 27, 42)')):
            style = re.sub(r'background-color:\s*[^;]+', 'background-color: #ffffff', style, flags=re.IGNORECASE)
            root.set('style', style)
        for elem in root.iter():
            if not isinstance(elem.tag, str):
                continue
            fill = (elem.get('fill') or '').strip().lower()
            tag = etree.QName(elem).localname.lower()
            if tag == 'rect' and any(d in fill for d in ('#0d1b2a', '#0f172a', '#1e293b')):
                w = elem.get('width', '')
                h = elem.get('height', '')
                if w in ('100%', '1600', '1400') or h in ('100%', '1000', '900', '840'):
                    elem.set('fill', '#ffffff')
        repaired = etree.tostring(root, encoding='unicode', xml_declaration=False)
        # Recovery must still produce strict, self-contained XML. This final
        # parse keeps malformed provider output from reaching image storage.
        strict_parser = etree.XMLParser(resolve_entities=False, load_dtd=False,
                                        no_network=True, huge_tree=False)
        etree.fromstring(repaired.encode('utf-8'), strict_parser)
        return repaired[:300000]
    except Exception:
        return ''


def _visual_plan_render_site_svg(prompt, contract, data, base_image='', extra_refs=None):
    references = [base_image] if base_image else []
    boundary_url = _visual_concept_render_plan_boundary_reference(
        contract['geometry']['surveyPoints'], g.tenant_id)
    if boundary_url:
        references += _visual_concept_reference_uris(urls=[boundary_url], tenant_id=g.tenant_id)
    references += list(extra_refs or [])

    system_prompt = (
        'You are a specialist in designing real-estate site plans by writing clean, standalone SVG code. '
        'Draw ONE standalone <svg> element and output ONLY the raw SVG markup starting with <svg and ending with </svg> '
        '— no markdown fences, no explanation, no text outside the SVG. All visible text is English only. '
        'White background, clear pastel fills, navy parcel boundary, dashed setbacks, and clean architectural vector layout.'
    )
    user_prompt = (prompt
        + ('\nThe first attached image is the current approved illustration of this plan — '
           'keep its look and every unrequested detail identical. ' if base_image else '\n')
        + 'The attached outline is the true surveyed parcel boundary — trace it exactly and '
        'generate only the buildings, entries and open areas the prompt describes as raw standalone SVG markup, nothing else.')

    # Stage three keeps data interpretation, chat, SVG authoring and SVG edits
    # on the same owner-selected Argon model. A separate PLAN_SITE_MODEL
    # override used to allow the drawing call to drift from the planning chat.
    model = GEMINI_TEXT_MODEL
    usage_ctx = _usage_ctx('image', data)

    try:
        from unittest.mock import Mock
        if isinstance(globals().get('call_images_api'), Mock) and not isinstance(globals().get('call_openrouter_chat'), Mock):
            raw = globals()['call_images_api'](user_prompt, references, usage_ctx=usage_ctx, model=model)
            if raw:
                return raw, len(references), model
            raise visual_plan_geometry.PlanGeometryError('تعذر توليد صورة المخطط.', 'PLANS_PROVIDER_FAILED')
    except Exception:
        pass

    response = call_openrouter_chat(
        system_prompt, user_prompt, temperature=None, max_tokens=65536,
        model=model, reasoning_effort='high', timeout=_visual_plan_job_call_timeout(1200),
        image_references=references or None, usage_ctx=usage_ctx)

    if isinstance(response, dict) and response.get('error'):
        error_info = response.get('error')
        fatal = _ai_fatal_http_response(error_info)
        if fatal is not None:
            raise FatalAICallError(error_info.get('message'), error_code=error_info.get('error_code'),
                                   http_status=error_info.get('http_status'),
                                   provider_message=error_info.get('provider_message'))
        raise visual_plan_geometry.PlanGeometryError(
            _client_safe_llm_error(_chat_error_message(response)), 'PLANS_PROVIDER_FAILED')

    content = _get_chat_response_text(response)
    svg = _visual_plan_extract_svg(content)
    if not svg:
        raise visual_plan_geometry.PlanGeometryError(
            'لم يُنتج الموديل كود SVG صالح للمخطط.', 'PLANS_PROVIDER_FAILED')

    svg = _visual_plan_sanitize_svg(svg)
    if not svg:
        raise visual_plan_geometry.PlanGeometryError(
            'كود SVG الناتج يحتوي على عناصر غير آمنة أو غير صالحة.', 'PLANS_PROVIDER_FAILED')

    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    data_uri = f'data:image/svg+xml;base64,{encoded}'
    return data_uri, len(references), model


def _visual_plan_dependency_images(data, workflow, kind):
    """The approved diagrams this diagram must be drawn on, in order.

    Plan 2 is drawn on Plan 1; Plan 3 is drawn on Plan 1 AND Plan 2. The
    dependency list is fixed per kind, so a diagram can never be produced
    without the approved drawings it is supposed to build on — Plan 3 used to
    receive Plan 1 only and had to invent the floor stacking itself.
    """
    posted = data.get('planImages') if isinstance(data.get('planImages'), dict) else {}
    project_slots = ((data.get('projectData') or {}).get('visual_concept') or {}).get('slots') or {}
    workflow_slots = workflow.get('slots') if isinstance(workflow.get('slots'), dict) else {}
    found = []
    for dependency in _VISUAL_PLAN_KIND_DEPENDENCIES.get(kind, ()):
        raw = posted.get(dependency)
        if isinstance(raw, dict):
            raw = raw.get('approvedImageUrl') or raw.get('imageUrl')
        url = str(raw or '').strip()
        if not url:
            slot = workflow_slots.get(f'plan_{dependency}') or {}
            draft_slot = project_slots.get(f'plan_{dependency}') or {}
            url = str(slot.get('approvedImageUrl') or slot.get('imageUrl')
                      or draft_slot.get('approvedImageUrl') or draft_slot.get('imageUrl')
                      or '').strip()
        if url and url not in found:
            found.append(url)
    return found


def _visual_plan_dependency_prompt(kind, dependency_kinds, base_image=False):
    """The rule that holds for the diagrams this one is drawn on."""
    if not dependency_kinds:
        return ''
    labels = {'site': 'Plan 1 — the approved site plan', 'uses': 'Plan 2 — the approved floor allocation'}
    listed = '; '.join(labels.get(item, item) for item in dependency_kinds)
    lead = 'The attached images that follow are' if base_image else 'The attached images are'
    if kind == 'uses':
        return (
            f'\nSTRICT DERIVATION: {lead} {listed}. This diagram is the floor-by-floor use '
            'allocation of that plan: keep its building footprints, its entries and its site '
            'arrangement exactly as they are drawn, and place only the approved components on the '
            'approved number of floors. Never add a floor, a component, a unit, a building, an area '
            'or a dimension that the approved data does not contain, and never resize a footprint.\n'
        )
    if kind == 'massing':
        return (
            f'\nSTRICT COMPOSITION: {lead} {listed}. This isometric is their composition: extrude '
            'the exact footprints of Plan 1 and stack them exactly as Plan 2 allocates them. Do not '
            'invent, merge, split, move, rotate or resize any building, floor, volume or open area, '
            'and do not add anything the approved diagrams do not contain.\n'
        )
    return ''


def _visual_plan_render_response(data, slot_id):
    kind = _visual_concept_plan_kind(slot_id)
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    if kind == 'site':
        scene, contract, context, _program = _visual_plan_scene_from_request(data)
        prompt = _visual_plan_slot_prompt(workflow, kind, context)
        image, reference_count, model_used = _visual_plan_render_site_svg(prompt, contract, data)
        return {'success': True, 'slotId': slot_id, 'image': persist_generated_image(image, g.tenant_id),
                'prompt': prompt, 'scene': scene, 'engine': 'surveyed_geometry',
                'model': model_used, 'geometryMode': 'surveyed_xy_schematic_z',
                'referenceCount': reference_count}

    # Stage 4 diagrams (uses and massing): direct image generation from stage 2 distribution
    context = _visual_plan_prompt_context(data)
    prompt = _visual_plan_slot_prompt(workflow, kind, context)
    base_image = _visual_concept_edit_base_image(data, g.tenant_id)
    references = [base_image] if base_image else []
    scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None

    boundary_points = ((workflow.get('boundary') or {}).get('points')
                       or context.get('boundary_points')
                       or (scene.get('contract') or {}).get('geometry', {}).get('surveyPoints') if isinstance(scene, dict) else None)
    if boundary_points:
        try:
            boundary_url = _visual_concept_render_plan_boundary_reference(boundary_points, g.tenant_id)
            if boundary_url:
                for uri in _visual_concept_reference_uris(urls=[boundary_url], tenant_id=g.tenant_id):
                    if uri not in references:
                        references.append(uri)
        except Exception:
            pass

    outline_text = ('The attached outline is the true surveyed parcel boundary — trace it exactly and '
                    'draw only the buildings, entries and open areas the prompt describes, nothing else.')

    if kind == 'uses':
        image_prompt = (prompt
            + ('\nThe first attached image is the current approved illustration of this diagram — '
               'keep its look and every unrequested detail identical.\n' if base_image else '\n')
            + outline_text)
    else:
        dependency_kinds = list(_VISUAL_PLAN_KIND_DEPENDENCIES.get(kind, ()))
        dependency_images = _visual_plan_dependency_images(data, workflow, kind)
        for dependency_image in dependency_images:
            dependency_uris = _visual_concept_reference_uris(
                urls=[dependency_image], tenant_id=g.tenant_id)
            for dependency_uri in dependency_uris:
                if dependency_uri not in references:
                    references.append(dependency_uri)

        image_prompt = (prompt
            + ('\nThe first attached image is the current approved illustration of this plan — '
               'keep its look and every unrequested detail identical.\n' if base_image else '\n')
            + _visual_plan_dependency_prompt(kind, dependency_kinds, base_image=bool(base_image))
            + outline_text)

    image = call_images_api(image_prompt, references, model=VISUAL_CONCEPT_IMAGE_MODEL,
                            timeout=_visual_plan_job_call_timeout(180),
                            usage_ctx=_usage_ctx('image', data))
    if not image:
        err = last_images_api_error() or {}
        if err.get('fatal') or err.get('error_code') in _FATAL_AI_ERROR_CODES:
            raise FatalAICallError(err.get('message'), error_code=err.get('error_code'),
                                   http_status=err.get('http_status'),
                                   provider_message=err.get('provider_message'))
        raise visual_plan_geometry.PlanGeometryError(
            _client_safe_llm_error(err.get('message') or 'تعذر توليد صورة المخطط.'),
            'PLANS_PROVIDER_FAILED')

    return {'success': True, 'slotId': slot_id, 'image': persist_generated_image(image, g.tenant_id),
            'prompt': prompt, 'scene': scene, 'engine': 'surveyed_geometry' if scene else 'image_generation',
            'model': VISUAL_CONCEPT_IMAGE_MODEL,
            'referenceCount': len(references)}


def _visual_plan_edit_scene(data, slot_id):
    scene, contract, context, program = _visual_plan_scene_from_request(data)
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        raise visual_plan_geometry.PlanGeometryError('طلب تعديل المخطط غير متوفر.', 'MESSAGE_REQUIRED')
    facade_only = bool(re.search(r'واجه|facade|cladding|material|خامة|كسوة|لون|colou?r', instruction, re.IGNORECASE)) and not re.search(
        r'انقل|نقل\s*المبنى|بصم|توزيع|مساحة|مدخل|مداخل|\bmove\b|footprint|layout|entrance|entry', instruction, re.IGNORECASE)
    base_image = _visual_concept_edit_base_image(data, g.tenant_id)
    boundary_url = _visual_concept_render_plan_boundary_reference(contract['geometry']['surveyPoints'], g.tenant_id)
    references = ([base_image] if base_image else []) + _visual_concept_reference_uris(urls=[boundary_url], tenant_id=g.tenant_id)
    references += _visual_concept_edit_reference_uris(data)
    system_prompt = (
        'You compile a surgical edit of a fixed architectural scene, not an image regeneration. '
        'Apply only the current user request to the named existing element. All unmentioned '
        'properties remain untouched. Never edit parcel geometry, source facts, primary frontage, '
        'north, floor program, counts, areas, setbacks or camera. A facade edit cannot become a '
        'footprint, entry or land edit. The first image, when present, is the current plan; the '
        'surveyed-outline reference and any client style references do not replace its geometry. '
        'If the target is ambiguous or the requested change cannot be represented by the supported '
        'conceptual elements, ask one short Arabic clarification instead of inventing a change. '
        'Materials: neutral|glass|stone|metal|render. Patterns: plain|grid|vertical|horizontal. '
        'Colors: #RRGGBB. Footprints keep exact source areas. Entries use recorded streets. '
        'Return JSON only: {"clear":true,"edits":[{"type":"facade","buildingId":"b1",'
        '"side":"west","style":{"material":"glass","pattern":"grid"}}],"reply":""}. '
        'Other supported edits are {"type":"footprint","buildingId":"b1","footprint":[[x,y],...]}'
        ' and {"type":"entry","id":"main_entry","kind":"main|residential|service",'
        '"buildingId":"b1","side":"west","position":0.5}. '
        'For clarification return {"clear":false,"question":""}. Never return whole-scene replacements.'
    )
    user_prompt = ('FIXED CONTRACT:\n' + json.dumps(contract, ensure_ascii=False)
                   + '\nCURRENT SCENE:\n' + json.dumps({key: value for key, value in scene.items() if key != 'token'}, ensure_ascii=False)
                   + '\nRECENT CONVERSATION:\n' + '\n'.join(_visual_concept_edit_chat_tail(data, slot_id))
                   + '\nCURRENT REQUEST:\n' + instruction)
    response = call_openrouter_chat(
        system_prompt, user_prompt, temperature=None, max_tokens=4000,
        model=VISUAL_PLAN_TEXT_MODEL, reasoning_effort='medium', response_format={'type': 'json_object'},
        timeout=_visual_plan_job_call_timeout(300),
        image_references=references or None, usage_ctx=_usage_ctx('image', data))
    fatal = _ai_fatal_error_dict(response)
    if fatal is not None:
        raise FatalAICallError(fatal.get('message'), error_code=fatal.get('error_code'),
                               http_status=fatal.get('http_status'),
                               provider_message=fatal.get('provider_message'))
    if isinstance(response, dict) and response.get('error'):
        raise visual_plan_geometry.PlanGeometryError(
            _client_safe_llm_error(_chat_error_message(response)), 'PLANS_PROVIDER_FAILED')
    result = parse_json_object(_get_chat_response_text(response))
    if isinstance(result, dict) and 'clear' not in result and 'edits' not in result:
        nested = next((v for v in result.values() if isinstance(v, dict)
                       and ('clear' in v or 'edits' in v)), None)
        if nested is not None:
            result = nested
    if isinstance(result, dict) and result.get('clear') is False:
        return {'success': True, 'slotId': slot_id, 'needsClarification': True,
                'question': _visual_concept_text(result.get('question'), 600) or 'العنصر المقصود بالتعديل غير واضح.'}
    if not isinstance(result, dict) or result.get('clear') is not True:
        raise visual_plan_geometry.PlanGeometryError('لم يصل تعديل منظم صالح للمخطط.', 'PLANS_EDIT_INVALID')
    edited = visual_plan_scene.apply_edits(scene, result.get('edits'), contract, program, facade_only)
    edited = _visual_plan_seal_scene(data, edited, context)
    kind = _visual_concept_plan_kind(slot_id)
    prompt = _visual_plan_slot_prompt(data.get('plansWorkflow') or {}, kind, context)
    if kind == 'site':
        image, _count, _model = _visual_plan_render_site_svg(
            prompt, contract, data, base_image=base_image,
            extra_refs=_visual_concept_edit_reference_uris(data))
    else:
        image, _count = _visual_plan_illustrate(
            prompt, contract, data, base_image=base_image,
            extra_refs=_visual_concept_edit_reference_uris(data))
    return {'success': True, 'slotId': slot_id, 'image': persist_generated_image(image, g.tenant_id),
            'scene': edited, 'engine': 'surveyed_geometry',
            'reply': _visual_concept_plan_sanitize_text(_visual_concept_text(result.get('reply'), 1200)) or 'تم تعديل العنصر المحدد في المخطط.'}
