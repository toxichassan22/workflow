import base64
import copy
import json
import math
import re
import time
from lxml import etree


_VISUAL_PLAN_SITE_SECTIONS = (
    ('coordinates', 'White drawing sheet, parcel and recorded setback outlines with adjoining street bands.'),
    ('colors', 'Reusable SVG styles and color definitions only.'),
    ('components', 'Current approved footprints, distinct unit labels and building names.'),
    ('access', 'Recorded streets, internal access between repeated units, and building entries.'),
    ('landscape', 'Current approved planting, pools, courts, parking and other site facilities.'),
    ('legend', 'Project and developer identity, building schedule and site feature color key.'),
)
_VISUAL_PLAN_SITE_SECTION_IDS = {name for name, _description in _VISUAL_PLAN_SITE_SECTIONS}
_VISUAL_PLAN_SITE_CONTEXT_COMPACT_AT = 900000
_VISUAL_PLAN_SITE_RENDER_REVISION = 5


def _visual_plan_site_number(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _visual_plan_site_record_tokens(state, value):
    state['promptTokens'] += _visual_plan_site_number(value)
    compacted_at = _visual_plan_site_number(state.get('compactedAtTokens'))
    if state['promptTokens'] - compacted_at >= _VISUAL_PLAN_SITE_CONTEXT_COMPACT_AT:
        state['turns'] = state['turns'][-4:]
        state['answers'] = state['answers'][-12:]
        state['compactionCount'] += 1
        state['compactedAtTokens'] = state['promptTokens']


def _visual_plan_site_state(data, signature):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    source = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    if source.get('inputSignature') and source.get('inputSignature') != signature:
        source = {}
    turns = []
    for item in (source.get('turns') if isinstance(source.get('turns'), list) else [])[-12:]:
        if isinstance(item, dict) and str(item.get('text') or '').strip():
            turns.append({'role': 'assistant' if item.get('role') == 'assistant' else 'user',
                          'text': str(item['text']).strip()[:4000],
                          'choices': [str(choice).strip()[:240] for choice in
                                      (item.get('choices') if isinstance(item.get('choices'), list) else [])[:6]]})
    answers = []
    for item in (source.get('answers') if isinstance(source.get('answers'), list) else [])[-100:]:
        if isinstance(item, dict) and item.get('question') and item.get('answer'):
            answers.append({'question': str(item['question'])[:800], 'answer': str(item['answer'])[:2000]})
    checkpoints = source.get('checkpoints') if isinstance(source.get('checkpoints'), dict) else {}
    return {
        'inputSignature': signature,
        'summary': str(source.get('summary') or '')[:40000],
        'turns': turns,
        'answers': answers,
        'pendingQuestion': str(source.get('pendingQuestion') or '')[:800],
        'readyForGeneration': bool(source.get('readyForGeneration')),
        'generateRequested': bool(source.get('generateRequested')),
        'designSpec': source.get('designSpec') if isinstance(source.get('designSpec'), dict) else None,
        'checkpoints': {name: str(checkpoints[name])[:60000]
                        for name in _VISUAL_PLAN_SITE_SECTION_IDS
                        if isinstance(checkpoints.get(name), str)},
        'promptTokens': _visual_plan_site_number(source.get('promptTokens')),
        'compactionCount': _visual_plan_site_number(source.get('compactionCount')),
        'compactedAtTokens': _visual_plan_site_number(source.get('compactedAtTokens')),
        'renderRevision': _visual_plan_site_number(source.get('renderRevision')),
        'status': str(source.get('status') or 'idle'),
    }


def _visual_plan_site_reusable_checkpoints(previous, signature):
    if (not isinstance(previous, dict)
            or previous.get('inputSignature') != signature
            or _visual_plan_site_number(previous.get('renderRevision')) != _VISUAL_PLAN_SITE_RENDER_REVISION):
        return {}
    checkpoints = previous.get('checkpoints') if isinstance(previous.get('checkpoints'), dict) else {}
    return {key: value for key, value in checkpoints.items()
            if key in _VISUAL_PLAN_SITE_SECTION_IDS and isinstance(value, str)}


def _visual_plan_site_short_label(value):
    label = str(value or '').strip()
    label = re.sub(r'\([^)]*\)|\[[^]]*\]', '', label)
    label = re.sub(r'\s*[-–—|/]\s*.*$', '', label)
    label = re.sub(r'\s+', ' ', label).strip(' -–—|/,:;')
    if re.search(r'[\u0600-\u06FF]', label):
        return ''
    return label[:32]


def _visual_plan_site_identity_value(value, limit=120):
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or ''))
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def _visual_plan_site_feature_type(source, kind=''):
    text = ' '.join(str(source.get(key) or '') for key in ('name', 'label', 'siteType')).lower()
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
    try:
        polygons.extend(item['polygon'] for item in visual_plan_scene.buildable_envelopes(contract))
    except Exception:
        pass
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
        source = buildings_by_id.get(building.get('id'), {})
        label = _visual_plan_site_short_label(source.get('label') or building.get('id') or 'Building')
        if label:
            building_label_counts[label.casefold()] = building_label_counts.get(label.casefold(), 0) + 1
    for building in scene.get('buildings') or []:
        source = buildings_by_id.get(building.get('id'), {})
        bands = source.get('bands') or []
        category = next((band.get('category') for band in bands
                         if band.get('kind') not in ('basement', 'roof')),
                        (bands[0].get('category') if bands else 'amenity'))
        label = _visual_plan_site_short_label(source.get('label') or building.get('id') or 'Building')
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
            'footprint': [project(point) for point in building.get('footprint') or []],
        })
    projected_parcels = [{'id': parcel.get('id'), 'points': [project(point) for point in parcel.get('polygon') or []]}
                         for parcel in parcels if isinstance(parcel, dict)]
    envelopes = []
    try:
        envelopes = [{'parcelId': item.get('parcelId'), 'points': [project(point) for point in item['polygon']]}
                     for item in visual_plan_scene.buildable_envelopes(contract)]
    except Exception:
        pass
    entries = []
    for entry in scene.get('entries') or []:
        try:
            entries.append({**{key: entry.get(key) for key in ('id', 'kind', 'buildingId', 'side')},
                            'point': project(visual_plan_scene.entry_position(entry, scene))})
        except Exception:
            continue
    approved_site_items = program.get('siteItems') or []
    site_items = {str(item.get('id')): item for item in approved_site_items}
    for source in approved_site_items:
        site_type = _visual_plan_site_feature_type(source)
        display_category = (site_type if site_type in ('pool', 'padel', 'playground', 'landscape')
                            else source.get('category'))
        if display_category and display_category not in categories:
            categories.append(display_category)
    open_areas = []
    for item in scene.get('openAreas') or []:
        source = site_items.get(str(item.get('componentId') or ''), {})
        feature_type = _visual_plan_site_feature_type(source, item.get('kind'))
        category = (feature_type if feature_type in ('pool', 'padel', 'playground', 'landscape') else
                    source.get('category') or ('parking' if item.get('kind') == 'surface_parking' else 'landscape'))
        label = _visual_plan_site_short_label(
            source.get('label') or visual_plan_renderer.USE_LABELS.get(category, 'Open space'))
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
    street_rows = {item.get('direction'): item for item in contract.get('directions') or []}
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
        street_name = _visual_plan_site_short_label(source.get('streetName'))
        label = street_name or (direction.title() + ' Street')
        street_width = visual_plan_geometry.finite_number(source.get('streetWidth'))
        if street_width is not None:
            label += f', {street_width:g} m'
        streets.append({'direction': direction, 'label': label, 'polygon': road_polygon,
                        'centerLine': [
                            [round(start[0] + outward[0] * width / 2, 2), round(start[1] + outward[1] * width / 2, 2)],
                            [round(end[0] + outward[0] * width / 2, 2), round(end[1] + outward[1] * width / 2, 2)]],
                        'labelPoint': [round((start[0] + end[0]) / 2 + outward[0] * width / 2, 2),
                                       round((start[1] + end[1]) / 2 + outward[1] * width / 2, 2)]})
        labels.append(label)
    repeated_units = [item for item in projected_buildings
                      if re.match(r'^unit_\d+_\d+$', str(item.get('id') or ''), re.IGNORECASE)]
    site_circulation = []
    site_edges = [(a, b) for parcel in projected_parcels
                  for a, b in zip(parcel.get('points') or [],
                                  (parcel.get('points') or [])[1:] + (parcel.get('points') or [])[:1])]
    if site_edges:
        axis_a, axis_b = max(site_edges, key=lambda edge: math.dist(*edge))
        axis_angle = math.atan2(axis_b[1] - axis_a[1], axis_b[0] - axis_a[0])
    else:
        axis_angle = 0
    axis_cos, axis_sin = math.cos(axis_angle), math.sin(axis_angle)

    def site_local(point):
        return [point[0] * axis_cos + point[1] * axis_sin,
                -point[0] * axis_sin + point[1] * axis_cos]

    def site_project(point):
        return [point[0] * axis_cos - point[1] * axis_sin,
                point[0] * axis_sin + point[1] * axis_cos]

    def unit_bounds(item):
        points = [site_local(point) for point in item.get('footprint') or []]
        if len(points) < 3:
            return None
        return (min(point[0] for point in points), max(point[0] for point in points),
                min(point[1] for point in points), max(point[1] for point in points))

    for first_index, first in enumerate(repeated_units):
        first_bounds = unit_bounds(first)
        if first_bounds is None:
            continue
        first_center = ((first_bounds[0] + first_bounds[1]) / 2,
                        (first_bounds[2] + first_bounds[3]) / 2)
        for second in repeated_units[first_index + 1:]:
            second_bounds = unit_bounds(second)
            if second_bounds is None:
                continue
            second_center = ((second_bounds[0] + second_bounds[1]) / 2,
                             (second_bounds[2] + second_bounds[3]) / 2)
            horizontal_gap = (second_bounds[0] - first_bounds[1] if first_center[0] <= second_center[0]
                              else first_bounds[0] - second_bounds[1])
            vertical_overlap = min(first_bounds[3], second_bounds[3]) - max(first_bounds[2], second_bounds[2])
            if (9 <= horizontal_gap <= 90
                    and vertical_overlap >= min(first_bounds[3] - first_bounds[2],
                                                second_bounds[3] - second_bounds[2]) * 0.45):
                left, right = (first_bounds, second_bounds) if first_center[0] <= second_center[0] else (second_bounds, first_bounds)
                center_y = (max(left[2], right[2]) + min(left[3], right[3])) / 2
                site_circulation.append({'points': [site_project([left[1], center_y]),
                                                    site_project([right[0], center_y])],
                                         'width': round(min(12, max(4, horizontal_gap * 0.6)), 2)})
                continue
            vertical_gap = (second_bounds[2] - first_bounds[3] if first_center[1] <= second_center[1]
                            else first_bounds[2] - second_bounds[3])
            horizontal_overlap = min(first_bounds[1], second_bounds[1]) - max(first_bounds[0], second_bounds[0])
            if (9 <= vertical_gap <= 90
                    and horizontal_overlap >= min(first_bounds[1] - first_bounds[0],
                                                  second_bounds[1] - second_bounds[0]) * 0.45):
                top, bottom = (first_bounds, second_bounds) if first_center[1] <= second_center[1] else (second_bounds, first_bounds)
                center_x = (max(top[0], bottom[0]) + min(top[1], bottom[1])) / 2
                site_circulation.append({'points': [site_project([center_x, top[3]]),
                                                    site_project([center_x, bottom[2]])],
                                         'width': round(min(12, max(4, vertical_gap * 0.6)), 2)})
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
        'projectName': _visual_plan_site_identity_value(identity.get('projectName') or contract.get('projectName')),
        'developerName': _visual_plan_site_identity_value(identity.get('developerName')),
        'landArea': _visual_plan_site_identity_value(contract.get('landArea'), 32),
        'frontage': _visual_plan_site_identity_value(
            (contract.get('primaryFrontage') or {}).get('direction', '').title(), 32),
    }
    grouped_buildings = {}
    for item in projected_buildings:
        key = (item.get('label') or item.get('category') or 'Building').casefold()
        summary = grouped_buildings.setdefault(key, {'label': item.get('label') or 'Building',
                                                      'category': item.get('category'), 'count': 0})
        summary['count'] += 1
    return {'viewBox': f'0 0 {canvas_width} {canvas_height}', 'siteDrawingBounds': list(bounds),
            'legendBounds': [1212, 40, 352, 820],
            'parcels': projected_parcels, 'buildableEnvelopes': envelopes,
            'buildings': projected_buildings, 'buildingSchedule': list(grouped_buildings.values()),
            'entries': entries, 'streets': streets, 'siteCirculation': site_circulation,
            'openAreas': open_areas,
            'identity': identity, 'approvedLabels': list(dict.fromkeys(labels)),
            'architecturalColorLegend': legend}


def _visual_plan_site_packet(data):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    _visual_plan_report_site_chat_progress(0, 22)
    scene_prepare_started = time.perf_counter()
    if 'scene' not in workflow or workflow.get('scene') is None:
        scene, _context, _reference_url = _visual_plan_create_scene(data)
        workflow = dict(workflow)
        workflow['scene'] = scene
        data['plansWorkflow'] = workflow
    else:
        _visual_plan_report_site_chat_progress(1, 35)
    _visual_plan_report_site_chat_timing('scene_prepare_ms', scene_prepare_started)
    validation_started = time.perf_counter()
    scene, contract, context, program = _visual_plan_scene_from_request(data)
    signature = scene.get('inputSignature') or _visual_plan_input_signature(data, context)
    clean_scene = {key: value for key, value in scene.items() if key not in ('token', 'inputSignature')}
    _visual_plan_report_site_chat_timing('scene_validation_ms', validation_started)
    layout_started = time.perf_counter()
    tenant = getattr(g, 'tenant', {})
    tenant = tenant if isinstance(tenant, dict) else {}
    drawing_layout = _visual_plan_site_projected_layout(scene, contract, program, {
        'projectName': contract.get('projectName'),
        'developerName': tenant.get('company_name_en') or tenant.get('company_name'),
    })
    _visual_plan_report_site_chat_timing('layout_projection_ms', layout_started)
    packet = {
        'project': {'name': contract.get('projectName'), 'idea': contract.get('projectIdea')},
        'landAndRegulations': contract,
        'validatedScene': clean_scene,
        'program': program,
        'drawingLayout': drawing_layout,
        'financialComponents': context.get('components') or [],
    }
    _visual_plan_report_site_chat_progress(2, 68)
    return packet, contract, context, signature


def _visual_plan_site_call(system_prompt, user_prompt, data=None, max_tokens=12000,
                           reasoning_effort='high'):
    timeout = _visual_plan_job_call_timeout(1200)
    response = call_openrouter_chat(
        system_prompt, user_prompt, temperature=None, max_tokens=max_tokens,
        model=GEMINI_TEXT_MODEL, reasoning_effort=reasoning_effort, timeout=timeout,
        response_format={'type': 'json_object'}, usage_ctx=_usage_ctx('image', data or {}))
    fatal = _ai_fatal_error_dict(response)
    if fatal is not None:
        raise FatalAICallError(fatal.get('message'), error_code=fatal.get('error_code'),
                               http_status=fatal.get('http_status'), provider_message=fatal.get('provider_message'))
    if isinstance(response, dict) and response.get('error'):
        raise visual_plan_geometry.PlanGeometryError(
            _client_safe_llm_error(_chat_error_message(response)), 'PLANS_PROVIDER_FAILED')
    parsed = parse_json_object(_get_chat_response_text(response))
    if not isinstance(parsed, dict):
        raise visual_plan_geometry.PlanGeometryError('ردّ Argon غير مكتمل أو غير منظم.', 'PLANS_PROVIDER_FAILED')
    usage = response.get('usage') if isinstance(response, dict) and isinstance(response.get('usage'), dict) else {}
    return parsed, _visual_plan_site_number(usage.get('prompt_tokens') or usage.get('input_tokens'))


def _visual_plan_site_interview(data, action='chat'):
    interview_started = time.perf_counter()
    workflow_before = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    scene_before = workflow_before.get('scene') if isinstance(workflow_before.get('scene'), dict) else {}
    scene_token_before = scene_before.get('token')
    packet, _contract, _context, signature = _visual_plan_site_packet(data)
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    scene_after = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else {}
    scene_rebased = bool(scene_token_before and scene_after.get('token')
                         and scene_token_before != scene_after.get('token'))
    if scene_rebased:
        workflow = dict(workflow)
        workflow['siteAssistant'] = {}
        data['plansWorkflow'] = workflow
    state = _visual_plan_site_state(data, signature)
    message = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if message:
        if state['pendingQuestion']:
            state['answers'].append({'question': state['pendingQuestion'], 'answer': message})
            state['answers'] = state['answers'][-100:]
        state['turns'].append({'role': 'user', 'text': message})
    prior_assistant = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    continuing = bool(prior_assistant.get('inputSignature') == signature
                      and state['summary'] and any(
        item.get('role') == 'assistant' for item in state['turns']))
    system_prompt = (
        'You are Google Gemini 4 Argon and the only assistant for this site-plan session. '
        'On the first interview turn, use the complete approved land, croquis, regulations, financial components, '
        'distribution, validated geometry, and client notes. On a continuation turn, the full project packet is '
        'omitted because the approved inputs are unchanged; continue from sessionMemory, resolvedAnswers, and recentTurns. '
        'Do not repeat the initial site analysis on continuation turns. Keep the same project context across this conversation. '
        'Do not ask for a fact already present in the data or in resolved answers. Ask only when an '
        'important design decision is genuinely unresolved. Ask one concise Arabic question at a time, '
        'and offer 2-5 short choices when the answer can be chosen. Otherwise return ready=true. '
        'Memory must compactly preserve the approved facts, constraints, and every resolved design choice needed '
        'for remaining questions, so follow-up turns can continue without the full project packet. '
        'When the client asks to generate or draw the plan, set generateRequested=true and keep that intent '
        'across clarification turns. If ready=true, the server will generate the drawing. Otherwise ask the '
        'blocking question first. Never generate code in this interview response. '
        'Return JSON only: {"ready":true|false,"generateRequested":true|false,"question":"","choices":[],"reply":"",'
        '"memory":"","designSpec":{"palette":{},"layoutNotes":""}}. The drawing itself must use English.'
    )
    compact_mode = state['promptTokens'] >= _VISUAL_PLAN_SITE_CONTEXT_COMPACT_AT
    if action == 'generate':
        task = 'confirm readiness for generation; ask a blocking question if needed'
    elif not state['turns'] and not message:
        task = 'review all available approved site-plan inputs and begin the client interview; ask only a blocking design question if needed'
    else:
        task = 'continue the site-plan interview'
    user_packet = {
        'task': task,
        'continuation': continuing,
        'validatedProjectData': None if continuing else packet,
        'resolvedAnswers': state['answers'][-8:] if continuing else state['answers'],
        'sessionMemory': state['summary'],
        'recentTurns': state['turns'][-4:] if continuing else state['turns'][-8:],
        'latestClientMessage': message,
        'compactContext': compact_mode,
    }
    _visual_plan_report_site_chat_progress(3, 82)
    model_started = time.perf_counter()
    reasoning_effort = 'medium' if continuing else 'high'
    max_tokens = 6000 if continuing else 12000
    try:
        parsed, prompt_tokens = _visual_plan_site_call(
            system_prompt, json.dumps(user_packet, ensure_ascii=False), data=data,
            max_tokens=max_tokens, reasoning_effort=reasoning_effort)
    finally:
        _visual_plan_report_site_chat_timing('interview_model_ms', model_started)
    question = _visual_concept_text(parsed.get('question'), 800)
    raw_choices = parsed.get('choices') if isinstance(parsed.get('choices'), list) else []
    choices = [str(item).strip()[:240] for item in raw_choices[:6] if str(item).strip()]
    ready = bool(parsed.get('ready')) and not question
    generate_requested = bool(parsed.get('generateRequested')) or state['generateRequested'] or action == 'generate'
    reply = _visual_concept_text(parsed.get('reply'), 1200)
    if question:
        reply = question
        state['pendingQuestion'] = question
        state['readyForGeneration'] = False
        state['generateRequested'] = generate_requested
        state['status'] = 'questioning'
    else:
        state['pendingQuestion'] = ''
        state['readyForGeneration'] = ready
        state['generateRequested'] = generate_requested
        state['status'] = 'ready' if ready else 'questioning'
    state['summary'] = str(parsed.get('memory') or state['summary'])[:40000]
    if isinstance(parsed.get('designSpec'), dict):
        state['designSpec'] = parsed['designSpec']
    _visual_plan_site_record_tokens(state, prompt_tokens)
    state['turns'].append({'role': 'assistant',
                           'text': reply or ('جاهز للتوليد.' if ready else 'أحتاج توضيحًا قبل التوليد.'),
                           'choices': choices if question else []})
    _visual_plan_report_site_chat_timing('interview_total_ms', interview_started)
    previous_assistant = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    return {'success': True, 'readyForGeneration': ready, 'generateRequested': generate_requested,
            'needsClarification': bool(question),
            'question': question, 'choices': choices, 'reply': reply,
            'assistantState': state, 'scene': workflow.get('scene'),
            'contextChanged': bool(previous_assistant.get('inputSignature')
                                                            and previous_assistant.get('inputSignature') != signature)
            or scene_rebased}


def _visual_plan_site_strip_non_english_text(element):
    arabic = re.compile(r'[\u0600-\u06FF]')
    changed = False
    parents = {}
    for parent in element.iter():
        if not isinstance(parent.tag, str):
            continue
        for child in parent:
            parents[child] = parent
    for node in list(element.iter()):
        if not isinstance(node.tag, str):
            if isinstance(node, etree._Comment) and arabic.search(node.text or ''):
                parent = parents.get(node)
                if parent is not None:
                    parent.remove(node)
                    changed = True
            continue
        if arabic.search(node.text or ''):
            node.text = ''
            changed = True
        if arabic.search(node.tail or ''):
            node.tail = ''
            changed = True
        for name, value in list(node.attrib.items()):
            if arabic.search(value):
                del node.attrib[name]
                changed = True
    return changed


def _visual_plan_site_section_fragment(raw, section, sanitized_sections=None, allowed_text=None):
    raw_text = str(raw or '').strip()
    parsed = {} if raw_text.startswith('<') else parse_json_object(raw_text)
    fragment = parsed.get('code', raw_text) if isinstance(parsed, dict) else raw_text
    fragment = str(fragment or '').strip()
    fenced = re.search(r'```(?:svg|xml)?\s*\n?([\s\S]*?)```', fragment)
    if fenced:
        fragment = fenced.group(1).strip()
    try:
        root = etree.fromstring(('<svg xmlns="http://www.w3.org/2000/svg">' + fragment + '</svg>').encode('utf-8'),
                                etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if len(root) != 1:
            raise ValueError('expected one root section')
        element = root[0]
        expected = 'defs' if section == 'colors' else 'g'
        if etree.QName(element).localname != expected or element.get('id') != 'll-section-' + section:
            raise ValueError('section ID or element type mismatch')
        changed = _visual_plan_site_strip_non_english_text(element)
        if allowed_text is not None:
            allowed = {str(item).strip().casefold() for item in allowed_text if str(item).strip()}
            for node in list(element.iter()):
                if not isinstance(node.tag, str) or etree.QName(node).localname.lower() not in ('text', 'title', 'desc'):
                    continue
                text = ' '.join(' '.join(node.itertext()).split()).casefold()
                if text not in allowed:
                    parent = node.getparent()
                    if parent is not None:
                        parent.remove(node)
                        changed = True
        if changed:
            if isinstance(sanitized_sections, list) and section not in sanitized_sections:
                sanitized_sections.append(section)
        return etree.tostring(element, encoding='unicode')
    except Exception as error:
        raise visual_plan_geometry.PlanGeometryError(
            'كود قسم «' + section + '» غير صالح.', 'PLANS_SVG_INVALID') from error


def _visual_plan_site_retain_project_identity(fragment, current_svg):
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    replacement_root = etree.fromstring(fragment.encode('utf-8'), parser)
    current_root = etree.fromstring(current_svg.encode('utf-8'), parser)
    existing = next((node for node in current_root.iter()
                     if isinstance(node.tag, str) and node.get('id') == 'll-project-identity'), None)
    if existing is None:
        return fragment
    for node in list(replacement_root.iter()):
        if isinstance(node.tag, str) and node.get('id') == 'll-project-identity':
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
    replacement_root.insert(0, copy.deepcopy(existing))
    return etree.tostring(replacement_root, encoding='unicode')


def _visual_plan_site_report_progress(progress, todos, checkpoints, signature=None):
    callback = getattr(g, 'visual_plan_job_progress', None)
    if callable(callback):
        callback(progress=progress, todos=todos, checkpoint={
            'svgSections': checkpoints,
            'svgRenderRevision': _VISUAL_PLAN_SITE_RENDER_REVISION,
            'svgInputSignature': signature or '',
        })


def _visual_plan_site_section_todos(checkpoints=None, active_section=None,
                                    assembly_active=False, complete=False):
    completed = set(checkpoints) if isinstance(checkpoints, dict) else set()
    rows = []
    for section, label in _VISUAL_PLAN_SITE_SECTIONS:
        if complete or section in completed:
            status = 'done'
        elif section == active_section:
            status = 'active'
        else:
            status = 'pending'
        rows.append({'id': 'site-svg-' + section, 'label': label,
                     'status': status, 'stage': 'site_svg_section'})
    rows.append({'id': 'site-svg-assembly', 'label': 'تركيب المخطط وفحصه',
                 'status': ('done' if complete else 'active' if assembly_active else 'pending'),
                 'stage': 'site_svg_assembly'})
    return rows


def _visual_plan_site_generate(data, interview):
    if interview.get('needsClarification') or not interview.get('readyForGeneration'):
        return interview
    packet, _contract, _context, signature = _visual_plan_site_packet(data)
    state = interview['assistantState']
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    previous = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    checkpoints = _visual_plan_site_reusable_checkpoints(previous, signature)
    state.update({'status': 'generating', 'inputSignature': signature,
                  'renderRevision': _VISUAL_PLAN_SITE_RENDER_REVISION,
                  'checkpoints': checkpoints})
    drawing_layout = packet['drawingLayout']
    renderers = {
        'coordinates': lambda: _visual_plan_site_coordinates_fragment(drawing_layout),
        'colors': _visual_plan_site_colors_fragment,
        'components': lambda: _visual_plan_site_component_fragment(drawing_layout),
        'access': lambda: _visual_plan_site_access_fragment(drawing_layout),
        'landscape': lambda: _visual_plan_site_landscape_fragment(drawing_layout),
        'legend': lambda: _visual_plan_site_legend_fragment(drawing_layout),
    }
    total = len(_VISUAL_PLAN_SITE_SECTIONS)
    for section, _description in _VISUAL_PLAN_SITE_SECTIONS:
        if section in checkpoints:
            continue
        _visual_plan_site_report_progress(
            20 + int(65 * len(checkpoints) / total),
            _visual_plan_site_section_todos(checkpoints, active_section=section), checkpoints, signature)
        checkpoints[section] = renderers[section]()
        state['checkpoints'] = checkpoints
        next_section = next((name for name, _label in _VISUAL_PLAN_SITE_SECTIONS
                             if name not in checkpoints), None)
        _visual_plan_site_report_progress(
            20 + int(65 * len(checkpoints) / total),
            _visual_plan_site_section_todos(
                checkpoints, active_section=next_section,
                assembly_active=next_section is None), checkpoints, signature)
    svg = _visual_plan_site_svg_from_blocks(checkpoints)
    if not svg or any('LL_SECTION_START:' + section not in svg for section in _VISUAL_PLAN_SITE_SECTION_IDS):
        raise visual_plan_geometry.PlanGeometryError('تعذر تركيب أقسام SVG في مخطط صالح.', 'PLANS_SVG_INVALID')
    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    image = persist_generated_image('data:image/svg+xml;base64,' + encoded, g.tenant_id)
    state.update({'status': 'review', 'readyForGeneration': True,
                  'generateRequested': False, 'renderRevision': _VISUAL_PLAN_SITE_RENDER_REVISION,
                  'checkpoints': checkpoints})
    _visual_plan_site_report_progress(
        98, _visual_plan_site_section_todos(checkpoints, complete=True), checkpoints, signature)
    reply = 'تم إنشاء المخطط لمراجعته.'
    return {'success': True, 'slotId': 'plan_site', 'image': image, 'svgCode': svg,
            'model': GEMINI_TEXT_MODEL, 'reply': reply,
            'assistantState': state, 'scene': workflow.get('scene')}


def _visual_plan_site_edit(data):
    packet, _contract, _context, signature = _visual_plan_site_packet(data)
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    workflow_assistant = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    state = _visual_plan_site_state(data, signature)
    svg = str(data.get('siteSvgCode') or '')[:300000]
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not svg or not instruction:
        raise visual_plan_geometry.PlanGeometryError('كود المخطط أو طلب التعديل غير متاح.', 'MESSAGE_REQUIRED')
    if workflow_assistant.get('inputSignature') and workflow_assistant.get('inputSignature') != signature:
        return {'success': True, 'needsClarification': True, 'contextChanged': True,
                'question': 'تغيرت بيانات الأرض أو التوزيع منذ توليد هذا المخطط. أعد بناء المخطط قبل تعديله.',
                'choices': [], 'assistantState': state}
    if _visual_plan_site_number(workflow_assistant.get('renderRevision')) != _VISUAL_PLAN_SITE_RENDER_REVISION:
        return {'success': True, 'needsClarification': True, 'contextChanged': True,
                'question': 'المخطط الحالي أُنشئ بإصدار سابق. أعد بناء المخطط قبل تعديله.',
                'choices': [], 'assistantState': state}
    if state['pendingQuestion']:
        state['answers'].append({'question': state['pendingQuestion'], 'answer': instruction})
        state['answers'] = state['answers'][-100:]
        state['pendingQuestion'] = ''
    state['turns'].append({'role': 'user', 'text': instruction})
    system_prompt = (
        'You are Google Gemini 4 Argon making a surgical edit to an existing modular SVG source file. '
        'Do not regenerate or return the whole SVG. Return JSON only: {"clear":true|false,"question":"",'
        '"choices":[],"targetSection":"one section ID","code":"complete replacement fragment",'
        '"reply":""}. Change exactly one named section, preserving every other byte and all source facts. '
        'Use English visible labels, preserve the supplied palette and geometry, and keep the drawing uncluttered. '
        'The replacement must be a single <g id="ll-section-X"> or the <defs id="ll-section-colors"> section.'
    )
    user_packet = {'projectFacts': packet, 'currentSvg': svg,
                   'resolvedAnswers': state['answers'], 'sessionMemory': state['summary'],
                   'recentTurns': state['turns'][-8:], 'request': instruction}
    parsed, prompt_tokens = _visual_plan_site_call(
        system_prompt, json.dumps(user_packet, ensure_ascii=False), data=data, max_tokens=24000)
    _visual_plan_site_record_tokens(state, prompt_tokens)
    if parsed.get('clear') is False:
        question = _visual_concept_text(parsed.get('question'), 800) or 'حدد العنصر المطلوب تعديله.'
        raw_choices = parsed.get('choices') if isinstance(parsed.get('choices'), list) else []
        choices = [str(item).strip()[:240] for item in raw_choices[:6] if str(item).strip()]
        state['pendingQuestion'] = question
        state['status'] = 'questioning'
        state['turns'].append({'role': 'assistant', 'text': question, 'choices': choices})
        return {'success': True, 'needsClarification': True, 'question': question,
                'choices': choices,
                'assistantState': state}
    section = str(parsed.get('targetSection') or '')
    if section not in _VISUAL_PLAN_SITE_SECTION_IDS:
        raise visual_plan_geometry.PlanGeometryError('قسم التعديل غير معروف.', 'PLANS_EDIT_INVALID')
    sanitized_sections = []
    replacement = _visual_plan_site_section_fragment(
        parsed.get('code'), section, sanitized_sections,
        allowed_text=(packet['drawingLayout']['approvedLabels'] if section == 'components' else
                      ['PROJECT SITE PLAN', 'BUILDING SCHEDULE', 'SITE FEATURES',
                       'Recorded street', 'Internal access', 'Road and access',
                       'CONCEPTUAL PLAN | NOT TO SCALE', *[item['label'] for item in
                                                packet['drawingLayout']['architecturalColorLegend']]]
                      if section == 'legend' else []))
    if section == 'legend':
        replacement = _visual_plan_site_retain_project_identity(replacement, svg)
    start, end = '<!-- LL_SECTION_START:' + section + ' -->', '<!-- LL_SECTION_END:' + section + ' -->'
    pattern = re.compile(re.escape(start) + r'[\s\S]*?' + re.escape(end))
    if len(pattern.findall(svg)) != 1:
        raise visual_plan_geometry.PlanGeometryError('تعذر تحديد قسم الكود المطلوب بدقة.', 'PLANS_EDIT_INVALID')
    revised = pattern.sub(lambda _match: start + '\n' + replacement + '\n' + end, svg, count=1)
    revised = _visual_plan_sanitize_svg(revised)
    if not revised or start not in revised or end not in revised:
        raise visual_plan_geometry.PlanGeometryError('نتج عن التعديل كود SVG غير صالح.', 'PLANS_SVG_INVALID')
    encoded = base64.b64encode(revised.encode('utf-8')).decode('ascii')
    image = persist_generated_image('data:image/svg+xml;base64,' + encoded, g.tenant_id)
    state['checkpoints'][section] = replacement
    state['status'] = 'review'
    reply = _visual_concept_text(parsed.get('reply'), 1200) or 'Updated the requested SVG section.'
    if sanitized_sections:
        reply += ' حُذفت تسميات غير إنجليزية من القسم المعدل.'
    state['turns'].append({'role': 'assistant', 'text': reply})
    return {'success': True, 'slotId': 'plan_site', 'image': image, 'svgCode': revised,
            'targetSection': section, 'model': GEMINI_TEXT_MODEL,
            'reply': reply,
            'assistantState': state, 'scene': workflow.get('scene')}


def _visual_plan_site_assistant_execute(data, action):
    automatic_placement_retry = False
    try:
        if action == 'edit':
            return _visual_plan_site_edit(data), 200
        interview = None
        if action == 'generate':
            _packet, _contract, _context, signature = _visual_plan_site_packet(data)
            state = _visual_plan_site_state(data, signature)
            if state['readyForGeneration'] and not state['pendingQuestion']:
                interview = {'success': True, 'readyForGeneration': True,
                             'needsClarification': False, 'assistantState': state}
        if interview is None:
            interview = _visual_plan_site_interview(data, 'generate' if action == 'generate' else 'chat')
        if interview.get('needsClarification'):
            return interview, 200
        if action != 'generate' and not interview.get('generateRequested'):
            return interview, 200
        automatic_placement_retry = action != 'generate' and bool(interview.get('generateRequested'))
        return _visual_plan_site_generate(data, interview), 200
    except visual_plan_geometry.PlanGeometryError as error:
        if error.code not in ('PLANS_COVERAGE_CONFLICT', 'PLANS_SITE_AREA_CONFLICT'):
            raise
        interview = _visual_plan_site_conflict_interview(
            data, error, auto_retry_failed=automatic_placement_retry)
        if (action != 'generate' and not automatic_placement_retry
                and interview.get('generateRequested')):
            try:
                return _visual_plan_site_generate(data, interview), 200
            except visual_plan_geometry.PlanGeometryError as retry_error:
                if retry_error.code not in ('PLANS_COVERAGE_CONFLICT', 'PLANS_SITE_AREA_CONFLICT'):
                    raise
                return _visual_plan_site_conflict_interview(
                    data, retry_error, auto_retry_failed=True), 200
        return interview, 200


@app.route('/api/visual-concept/site-plan-assistant', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_site_plan_assistant():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error_code': 'INVALID_REQUEST'}), 400
    action = str(data.get('planAssistantAction') or 'chat')
    if action not in ('chat', 'generate', 'edit'):
        return jsonify({'success': False, 'error_code': 'PLANS_OPERATION_INVALID'}), 400
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'plan_site')
    if slot_id != 'plan_site':
        return jsonify({'success': False, 'error_code': 'SLOT_INVALID'}), 400
    workflow_error = _visual_concept_plan_workflow_error(data, slot_id, require_distribution=True)
    if workflow_error:
        return jsonify(workflow_error), 400
    billing_guard = _require_billing_balance('image_generation' if action != 'chat' else 'designer_chat')
    if billing_guard is not None:
        return billing_guard
    return _visual_plan_dispatch('site_' + action, data, slot_id)
