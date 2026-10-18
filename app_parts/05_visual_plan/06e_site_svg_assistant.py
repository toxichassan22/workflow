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




_VISUAL_PLAN_SITE_CONFLICT_CODES = (
    'PLANS_COVERAGE_CONFLICT',
    'PLANS_SITE_AREA_CONFLICT',
    'PLANS_SETBACK_CONFLICT',
    'PLANS_FOOTPRINT_OUTSIDE',
    'PLANS_BUILDING_OVERLAP',
    'PLANS_LAYOUT_INVALID',
    'PLANS_SITE_ITEMS_MISSING',
    'PLANS_SITE_ITEMS_DUPLICATED',
)


def _visual_plan_site_packet(data):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    has_sealed_scene = (isinstance(workflow.get('scene'), dict)
                        and bool(workflow['scene'].get('token')))
    if has_sealed_scene:
        try:
            scene, contract, context, program = _visual_plan_scene_from_request(data)
            signature = scene.get('inputSignature') or _visual_plan_input_signature(data, context)
        except visual_plan_geometry.PlanGeometryError as error:
            if error.code not in _VISUAL_PLAN_SITE_CONFLICT_CODES:
                raise
            contract, context = _visual_plan_contract(data)
            program = _visual_plan_program(contract, context)
            signature = _visual_plan_input_signature(data, context)
            scene = workflow.get('scene')
    else:
        contract, context = _visual_plan_contract(data)
        program = _visual_plan_program(contract, context)
        signature = _visual_plan_input_signature(data, context)
        scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else None
    clean_scene = {key: value for key, value in scene.items() if key not in ('token', 'inputSignature')} if scene else None
    drawing_layout = None
    if scene and isinstance(scene.get('buildings'), list):
        try:
            tenant = getattr(g, 'tenant', {})
            tenant = tenant if isinstance(tenant, dict) else {}
            drawing_layout = _visual_plan_site_projected_layout(scene, contract, program, {
                'projectName': contract.get('projectName'),
                'developerName': tenant.get('company_name_en') or tenant.get('company_name'),
            })
        except Exception:
            drawing_layout = None
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
        'You are the lead architect and planner, and the sole authority managing this master plan session. '
        'You are the single entity that commands, designs, responds, identifies conflicts, answers inquiries, '
        'and accepts modifications. There is no code or geometric engine running analysis: you alone perform '
        'the entire spatial, regulatory, and architectural analysis. '
        'On the first turn, review the complete approved land survey, coordinates, boundaries, setbacks (north, '
        'south, east, west), maximum coverage ratio, height limits, building program (names, IDs, uses, floor ranges, '
        'ground-floor footprint areas, units), site amenities (landscape, surface parking, pools, playgrounds, courts), '
        'and client notes. On continuation turns, the full packet is omitted if inputs are unchanged; continue from '
        'sessionMemory, resolvedAnswers, and recentTurns. '
        'RULES OF YOUR ARCHITECTURAL AUTHORITY:\n'
        '1. IDENTIFYING CONFLICTS: If you find any regulatory or spatial conflict (e.g. required ground-floor footprints '
        'cannot fit inside the buildable area after setbacks, total footprints exceed the allowable coverage ratio, '
        'or an entry lacks recorded street access), state the conflict explicitly in Arabic in "reply", explain the exact '
        'numerical facts and why it occurs, set ready=false, and provide 2-5 actionable choices in "choices" (e.g. reviewing '
        'setbacks, reducing ground-floor footprint and offsetting with additional floors, or adjusting the program). '
        '2. ANSWERING QUESTIONS & CALCULATIONS: When the client asks questions, disputes numbers, asks why there is a '
        'conflict, asks for area calculations (such as net buildable area after setbacks, remaining land area, or coverage), '
        'calculate and explain everything thoroughly and fluently in Arabic. '
        '3. ACCEPTING MODIFICATIONS: When the client requests adjustments, changes, or revisions, accept them, update '
        'your sessionMemory and designSpec, and respond constructively. '
        '4. DESIGN & GENERATION: When the client asks to generate or draw the master plan ("ارسم", "صمم", "ولد المخطط", '
        '"وزع المباني على الأرض"), set generateRequested=true. If ready=true with no blocking conflicts, the server '
        'generates the master plan drawing designed by you. Otherwise ask the blocking question first. '
        'Never generate code in this interview response. '
        'Return JSON only: {"ready":true|false,"generateRequested":true|false,"conflict":true|false,"question":"",'
        '"choices":[],"reply":"","memory":"","designSpec":{"palette":{},"layoutNotes":""}}.'
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


def _visual_plan_site_ai_design_scene(data, packet, contract, program, context):
    """AI model as sole architect and planner designs the conceptual site layout placement."""
    geometry = contract.get('geometry') if isinstance(contract.get('geometry'), dict) else {}
    parcels = geometry.get('parcels') or []
    parcel_polygon = []
    for p in parcels:
        poly = p.get('polygon') if isinstance(p, dict) else p
        if isinstance(poly, list) and len(poly) >= 3:
            parcel_polygon = poly
            break
    if not parcel_polygon:
        survey = contract.get('recordedSurvey') or geometry.get('surveyPoints') or []
        if isinstance(survey, list) and len(survey) >= 3:
            parcel_polygon = survey
    if not parcel_polygon:
        parcel_polygon = [[0, 0], [100, 0], [100, 100], [0, 100]]

    xs = [pt[0] for pt in parcel_polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    ys = [pt[1] for pt in parcel_polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    min_x, max_x = (min(xs), max(xs)) if xs else (0, 100)
    min_y, max_y = (min(ys), max(ys)) if ys else (0, 100)
    width = max(10.0, max_x - min_x)
    height = max(10.0, max_y - min_y)

    buildings_spec = []
    for b in (program.get('buildings') or []):
        if not isinstance(b, dict):
            continue
        buildings_spec.append({
            'id': b.get('id'),
            'name': b.get('name'),
            'label': b.get('label'),
            'footprintAreaSqm': b.get('footprintArea'),
            'levels': b.get('levels', 1),
            'category': b.get('bands', [{}])[0].get('category') if b.get('bands') else 'residential',
        })

    site_items_spec = []
    for s in (program.get('siteItems') or []):
        if not isinstance(s, dict):
            continue
        site_items_spec.append({
            'id': s.get('id'),
            'name': s.get('name'),
            'label': s.get('label'),
            'siteType': s.get('siteType') or 'amenity',
            'areaSqm': s.get('area'),
        })

    design_context = {
        'projectName': contract.get('projectName'),
        'projectIdea': contract.get('projectIdea'),
        'plotNumber': contract.get('plotNumber'),
        'planNumber': contract.get('planNumber'),
        'deedNumber': contract.get('deedNumber'),
        'deedDate': contract.get('deedDate'),
        'city': contract.get('city'),
        'district': contract.get('district'),
        'locationAddress': contract.get('locationAddress'),
        'landAreaSqm': contract.get('landArea'),
        'landParcelBoundary': parcel_polygon,
        'boundaryLengths': contract.get('boundaryLengths'),
        'directions': contract.get('directions'),
        'directionsTable': contract.get('directionsTable'),
        'surroundingStreets': contract.get('surroundingStreets'),
        'facadesCount': contract.get('facadesCount'),
        'facadesDirections': contract.get('facadesDirections'),
        'primaryFrontage': contract.get('primaryFrontage'),
        'northDirection': contract.get('northDirection'),
        'setbacks': contract.get('setbacks') or {'north': 2, 'south': 2, 'east': 2, 'west': 2},
        'setbackText': contract.get('setbackText'),
        'coverageRatioPercent': contract.get('coverageRatio'),
        'buildingRatioCoverage': contract.get('buildingRatioCoverage'),
        'floorAreaRatio': contract.get('floorAreaRatio'),
        'floorCount': contract.get('floorCount'),
        'maxFloorsHeight': contract.get('maxFloorsHeight'),
        'allowedUses': contract.get('allowedUses'),
        'regulatoryConstraints': contract.get('regulatoryConstraints'),
        'landBrief': contract.get('landBrief'),
        'parkingRequirements': contract.get('parkingRequirements'),
        'entrancesExitsRequirements': contract.get('entrancesExitsRequirements'),
        'clientNotes': contract.get('clientNotes'),
        'buildingsToPlace': buildings_spec,
        'siteItemsToPlace': site_items_spec,
    }

    system_prompt = (
        'You are the lead architect and master site planner. You are the sole designer responsible for '
        'laying out the project on the parcel. There is no external layout algorithm: you determine the spatial '
        'positions, footprints, and geometry for all buildings, open spaces, parking, landscape, and access entries. '
        'Take into full consideration all provided land and croquis data: boundaries, surrounding streets, street widths, '
        'facades, setback rules, boundary lengths, orientation with north, and regulatory constraints. '
        'RULES:\n'
        '1. Place every building in buildingsToPlace inside landParcelBoundary with coordinates [x, y] in the '
        'exact coordinate system of landParcelBoundary.\n'
        '2. For each building, output a footprint polygon of 4 points [[x, y], [x, y], [x, y], [x, y]] whose area '
        'closely matches footprintAreaSqm.\n'
        '3. Respect setbacks from boundary edges where possible. Do not overlap buildings.\n'
        '4. Place site items (parking, landscape, amenities) in openAreas with polygon coordinates.\n'
        '5. Specify at least one access entry along the street frontage.\n'
        'Return JSON only: {"buildings":[{"id":"","footprint":[[x,y],...]}],"openAreas":[{"id":"","polygon":[[x,y],...],"featureType":""}],"entries":[{"id":"","point":[x,y],"entryType":"main","label":"Main Entry"}]}'
    )

    try:
        parsed, _tokens = _visual_plan_site_call(
            system_prompt, json.dumps(design_context, ensure_ascii=False),
            data=data, max_tokens=8000, reasoning_effort='high')
    except Exception as err:
        app.logger.warning('AI site design call failed, using baseline geometric layout: %s', err)
        parsed = {}

    ai_buildings_map = {}
    if isinstance(parsed, dict) and isinstance(parsed.get('buildings'), list):
        for b in parsed['buildings']:
            if isinstance(b, dict) and b.get('id') and isinstance(b.get('footprint'), list):
                valid_pts = [[visual_plan_geometry.finite_number(pt[0]), visual_plan_geometry.finite_number(pt[1])]
                             for pt in b['footprint'] if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                if len(valid_pts) >= 3 and all(p[0] is not None and p[1] is not None for p in valid_pts):
                    ai_buildings_map[str(b['id'])] = valid_pts

    ai_open_areas_map = {}
    if isinstance(parsed, dict) and isinstance(parsed.get('openAreas'), list):
        for a in parsed['openAreas']:
            if isinstance(a, dict) and a.get('id') and isinstance(a.get('polygon'), list):
                valid_pts = [[visual_plan_geometry.finite_number(pt[0]), visual_plan_geometry.finite_number(pt[1])]
                             for pt in a['polygon'] if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                if len(valid_pts) >= 3 and all(p[0] is not None and p[1] is not None for p in valid_pts):
                    ai_open_areas_map[str(a['id'])] = {
                        'polygon': valid_pts,
                        'featureType': str(a.get('featureType') or 'amenity'),
                    }

    sb_inset = 4.0
    usable_w = max(5.0, width - 2 * sb_inset)
    usable_h = max(5.0, height - 2 * sb_inset)
    b_count = max(1, len(program.get('buildings', [])))
    cols = max(1, int(math.ceil(math.sqrt(b_count))))
    rows = max(1, int(math.ceil(b_count / cols)))
    cell_w = usable_w / cols
    cell_h = usable_h / rows

    scene_buildings = []
    for idx, b in enumerate(program.get('buildings', [])):
        if not isinstance(b, dict):
            continue
        bid = str(b.get('id') or f'b{idx+1}')
        footprint = ai_buildings_map.get(bid)
        if not footprint:
            r_idx, c_idx = idx // cols, idx % cols
            area = visual_plan_geometry.finite_number(b.get('footprintArea')) or 100.0
            side = min(math.sqrt(area), min(cell_w * 0.8, cell_h * 0.8))
            cx = min_x + sb_inset + c_idx * cell_w + cell_w / 2
            cy = min_y + sb_inset + r_idx * cell_h + cell_h / 2
            footprint = [
                [round(cx - side / 2, 2), round(cy - side / 2, 2)],
                [round(cx + side / 2, 2), round(cy - side / 2, 2)],
                [round(cx + side / 2, 2), round(cy + side / 2, 2)],
                [round(cx - side / 2, 2), round(cy + side / 2, 2)],
            ]
        category = b.get('bands', [{}])[0].get('category') if b.get('bands') else 'residential'
        scene_buildings.append({
            'id': bid,
            'name': b.get('name') or 'Building',
            'label': b.get('label') or 'Building',
            'category': category,
            'displayLabel': b.get('label') or 'Building',
            'footprint': footprint,
            'levels': b.get('levels', 1),
            'footprintArea': b.get('footprintArea'),
        })

    scene_open_areas = []
    for idx, s in enumerate(program.get('siteItems', [])):
        if not isinstance(s, dict):
            continue
        sid = str(s.get('id') or f'site_{idx+1}')
        ai_area = ai_open_areas_map.get(sid)
        if ai_area:
            polygon, ftype = ai_area['polygon'], ai_area['featureType']
        else:
            ftype = s.get('siteType') or 'landscape'
            area_val = visual_plan_geometry.finite_number(s.get('area')) or 50.0
            side = min(math.sqrt(area_val), min(usable_w * 0.3, usable_h * 0.3))
            cx = min_x + sb_inset + (idx % 3) * (usable_w / 3) + 10
            cy = min_y + sb_inset + 5
            polygon = [
                [round(cx, 2), round(cy, 2)],
                [round(cx + side, 2), round(cy, 2)],
                [round(cx + side, 2), round(cy + side, 2)],
                [round(cx, 2), round(cy + side, 2)],
            ]
        scene_open_areas.append({
            'id': sid,
            'name': s.get('name') or 'Site Area',
            'label': s.get('label') or 'Site Area',
            'featureType': ftype,
            'polygon': polygon,
        })

    scene_entries = []
    if isinstance(parsed, dict) and isinstance(parsed.get('entries'), list):
        for e in parsed['entries']:
            if isinstance(e, dict) and isinstance(e.get('point'), (list, tuple)) and len(e['point']) >= 2:
                px = visual_plan_geometry.finite_number(e['point'][0])
                py = visual_plan_geometry.finite_number(e['point'][1])
                if px is not None and py is not None:
                    scene_entries.append({
                        'id': str(e.get('id') or 'entry_ai'),
                        'point': [px, py],
                        'entryType': str(e.get('entryType') or 'main'),
                        'label': str(e.get('label') or 'Main Entry'),
                    })
    if not scene_entries:
        frontage_edge = parcel_polygon[:2] if len(parcel_polygon) >= 2 else [[0, 0], [10, 0]]
        mid_x = (frontage_edge[0][0] + frontage_edge[1][0]) / 2
        mid_y = (frontage_edge[0][1] + frontage_edge[1][1]) / 2
        scene_entries.append({
            'id': 'entry_main',
            'point': [round(mid_x, 2), round(mid_y, 2)],
            'entryType': 'main',
            'label': 'Main Entry',
        })

    scene = {
        'geometry': contract.get('geometry') or {'parcels': [{'polygon': parcel_polygon}]},
        'buildings': scene_buildings,
        'openAreas': scene_open_areas,
        'entries': scene_entries,
    }
    return _visual_plan_seal_scene(data, scene, context)


def _visual_plan_site_generate(data, interview):
    if interview.get('needsClarification') or not interview.get('readyForGeneration'):
        return interview
    packet, contract, context, signature = _visual_plan_site_packet(data)
    state = interview['assistantState']
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    if not packet.get('drawingLayout') or state.get('redesignRequested'):
        ai_scene = _visual_plan_site_ai_design_scene(data, packet, contract, packet.get('program') or {}, context)
        workflow = dict(workflow)
        workflow['scene'] = ai_scene
        data['plansWorkflow'] = workflow
        packet, contract, context, signature = _visual_plan_site_packet(data)
    previous = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    checkpoints = _visual_plan_site_reusable_checkpoints(previous, signature)
    state.update({'status': 'generating', 'inputSignature': signature,
                  'renderRevision': _VISUAL_PLAN_SITE_RENDER_REVISION,
                  'checkpoints': checkpoints})
    drawing_layout = packet.get('drawingLayout')
    if not drawing_layout and workflow.get('scene'):
        tenant = getattr(g, 'tenant', {})
        tenant = tenant if isinstance(tenant, dict) else {}
        drawing_layout = _visual_plan_site_projected_layout(workflow['scene'], contract, packet.get('program') or {}, {
            'projectName': contract.get('projectName'),
            'developerName': tenant.get('company_name_en') or tenant.get('company_name'),
        })
        packet['drawingLayout'] = drawing_layout
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
        if error.code not in _VISUAL_PLAN_SITE_CONFLICT_CODES:
            raise
        interview = _visual_plan_site_conflict_interview(
            data, error, auto_retry_failed=automatic_placement_retry)
        if (action != 'generate' and not automatic_placement_retry
                and interview.get('generateRequested')):
            try:
                return _visual_plan_site_generate(data, interview), 200
            except visual_plan_geometry.PlanGeometryError as retry_error:
                if retry_error.code not in _VISUAL_PLAN_SITE_CONFLICT_CODES:
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
