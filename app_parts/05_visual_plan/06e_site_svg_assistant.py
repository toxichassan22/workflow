import base64
import json
import re
import time
from lxml import etree


_VISUAL_PLAN_SITE_SECTIONS = (
    ('coordinates', 'Surveyed parcel, north direction, setbacks and area dimensions.'),
    ('colors', 'A restrained, internationally familiar planning palette and reusable SVG styles.'),
    ('components', 'Every approved building and component footprint, labels and approved areas.'),
    ('access', 'Main and service entries, basement access when present, and pedestrian and vehicle circulation.'),
    ('landscape', 'Approved open areas, planted zones and individual trees.'),
    ('legend', 'A clear English legend and area table using named color swatches, with no numbered keys.'),
)
_VISUAL_PLAN_SITE_SECTION_IDS = {name for name, _description in _VISUAL_PLAN_SITE_SECTIONS}
_VISUAL_PLAN_SITE_CONTEXT_COMPACT_AT = 900000
_VISUAL_PLAN_SITE_SECTION_OUTPUT_LIMIT = 32000


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
        'status': str(source.get('status') or 'idle'),
    }


def _visual_plan_site_projected_layout(scene, contract, program):
    """Project the validated metre-based scene to one shared SVG canvas."""
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
    scale = min(900 / span_x, 720 / span_y)
    offset_x = 70 + (900 - span_x * scale) / 2
    offset_y = 70 + (720 - span_y * scale) / 2

    def project(point):
        return [round(offset_x + (point[0] - min_x) * scale, 2),
                round(offset_y + (max_y - point[1]) * scale, 2)]

    buildings_by_id = {item['id']: item for item in program.get('buildings', [])}
    projected_buildings = []
    for building in scene.get('buildings') or []:
        source = buildings_by_id.get(building.get('id'), {})
        projected_buildings.append({
            'id': building.get('id'), 'label': source.get('label') or building.get('id'),
            'footprintAreaSqm': building.get('footprintArea'),
            'basementOnly': bool(building.get('basementOnly')),
            'levels': source.get('levels', []),
            'components': [{'label': band.get('label'), 'floorLabel': band.get('floorLabel'),
                            'areaSqm': band.get('area'), 'units': band.get('units')}
                           for band in source.get('bands', [])],
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
    open_areas = [{'id': item.get('id'), 'componentId': item.get('componentId'), 'kind': item.get('kind'),
                   'points': [project(point) for point in item.get('polygon') or []]}
                  for item in scene.get('openAreas') or []]
    return {'viewBox': '0 0 1600 900', 'siteDrawingBounds': [70, 70, 900, 720],
            'parcels': projected_parcels, 'buildableEnvelopes': envelopes,
            'buildings': projected_buildings, 'entries': entries, 'openAreas': open_areas,
            'approvedSiteAreaSqm': contract.get('landArea'),
            'approvedBuildingAreaSqm': contract.get('approvedBuildingArea'),
            'distribution': contract.get('distribution') or {},
            'northDirection': contract.get('northDirection') or contract.get('north') or '',
            'streets': contract.get('streets') or contract.get('surroundingStreets') or [],
            'regulations': contract.get('regulatoryConstraints') or {},
            'clientNotes': contract.get('clientNotes') or ''}


def _visual_plan_site_packet(data):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    if 'scene' not in workflow or workflow.get('scene') is None:
        scene, _context, _reference_url = _visual_plan_create_scene(data)
        workflow = dict(workflow)
        workflow['scene'] = scene
        data['plansWorkflow'] = workflow
    scene, contract, context, program = _visual_plan_scene_from_request(data)
    signature = _visual_plan_input_signature(data, context)
    clean_scene = {key: value for key, value in scene.items() if key not in ('token', 'inputSignature')}
    packet = {
        'project': {'name': contract.get('projectName'), 'idea': contract.get('projectIdea')},
        'landAndRegulations': contract,
        'validatedScene': clean_scene,
        'program': program,
        'drawingLayout': _visual_plan_site_projected_layout(scene, contract, program),
        'financialComponents': context.get('components') or [],
    }
    return packet, contract, context, signature


def _visual_plan_site_call(system_prompt, user_prompt, data=None, max_tokens=12000):
    timeout = 1200
    deadline = getattr(g, 'visual_plan_job_deadline', None)
    if deadline is not None:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise visual_plan_geometry.PlanGeometryError('انتهت مهلة معالجة المخطط الهندسي.', 'PLANS_JOB_EXPIRED')
        timeout = min(timeout, max(1, int(remaining)))
    response = call_openrouter_chat(
        system_prompt, user_prompt, temperature=None, max_tokens=max_tokens,
        model=GEMINI_TEXT_MODEL, reasoning_effort='high', timeout=timeout,
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
    packet, _contract, _context, signature = _visual_plan_site_packet(data)
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    state = _visual_plan_site_state(data, signature)
    message = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if message:
        if state['pendingQuestion']:
            state['answers'].append({'question': state['pendingQuestion'], 'answer': message})
            state['answers'] = state['answers'][-100:]
        state['turns'].append({'role': 'user', 'text': message})
    system_prompt = (
        'You are Google Gemini 4 Argon and the only assistant for this site-plan session. '
        'You receive the complete approved land, croquis, regulations, financial components, distribution, '
        'validated geometry, and client notes. Keep the same project context across this conversation. '
        'Do not ask for a fact already present in the data or in resolved answers. Ask only when an '
        'important design decision is genuinely unresolved. Ask one concise Arabic question at a time, '
        'and offer 2-5 short choices when the answer can be chosen. Otherwise return ready=true. '
        'Memory must preserve every resolved design choice and constraint so older turns and answers can be compacted safely. '
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
        'validatedProjectData': packet,
        'resolvedAnswers': state['answers'],
        'sessionMemory': state['summary'],
        'recentTurns': state['turns'][-8:],
        'latestClientMessage': message,
        'compactContext': compact_mode,
    }
    parsed, prompt_tokens = _visual_plan_site_call(
        system_prompt, json.dumps(user_packet, ensure_ascii=False), data=data, max_tokens=12000)
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
    previous_assistant = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    return {'success': True, 'readyForGeneration': ready, 'generateRequested': generate_requested,
            'needsClarification': bool(question),
            'question': question, 'choices': choices, 'reply': reply,
            'assistantState': state, 'scene': workflow.get('scene'),
            'contextChanged': bool(previous_assistant.get('inputSignature')
                                                            and previous_assistant.get('inputSignature') != signature)}


def _visual_plan_site_section_fragment(raw, section):
    raw_text = str(raw or '').strip()
    parsed = {} if raw_text.startswith('<') else parse_json_object(raw_text)
    fragment = parsed.get('code', raw_text) if isinstance(parsed, dict) else raw_text
    fragment = str(fragment or '').strip()
    fenced = re.search(r'```(?:svg|xml)?\s*\n?([\s\S]*?)```', fragment)
    if fenced:
        fragment = fenced.group(1).strip()
    if re.search(r'[\u0600-\u06FF]', fragment):
        raise visual_plan_geometry.PlanGeometryError('يحتوي قسم SVG على نص غير إنجليزي.', 'PLANS_SVG_INVALID')
    try:
        root = etree.fromstring(('<svg xmlns="http://www.w3.org/2000/svg">' + fragment + '</svg>').encode('utf-8'),
                                etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        if len(root) != 1:
            raise ValueError('expected one root section')
        element = root[0]
        expected = 'defs' if section == 'colors' else 'g'
        if etree.QName(element).localname != expected or element.get('id') != 'll-section-' + section:
            raise ValueError('section ID or element type mismatch')
        return etree.tostring(element, encoding='unicode')
    except Exception as error:
        raise visual_plan_geometry.PlanGeometryError(
            'كود قسم «' + section + '» غير صالح.', 'PLANS_SVG_INVALID') from error


def _visual_plan_site_svg_from_blocks(blocks):
    missing = _VISUAL_PLAN_SITE_SECTION_IDS - set(blocks)
    if missing:
        raise visual_plan_geometry.PlanGeometryError('لم تكتمل أقسام كود SVG.', 'PLANS_SVG_INCOMPLETE')
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900">',
             '<title>CONCEPTUAL SITE PLAN</title>']
    for section, _description in _VISUAL_PLAN_SITE_SECTIONS:
        parts.extend(['<!-- LL_SECTION_START:' + section + ' -->', blocks[section],
                      '<!-- LL_SECTION_END:' + section + ' -->'])
    parts.append('</svg>')
    return _visual_plan_sanitize_svg('\n'.join(parts))


def _visual_plan_site_report_progress(progress, todos, checkpoints):
    callback = getattr(g, 'visual_plan_job_progress', None)
    if callable(callback):
        callback(progress=progress, todos=todos, checkpoint={'svgSections': checkpoints})


def _visual_plan_site_generate(data, interview):
    if interview.get('needsClarification') or not interview.get('readyForGeneration'):
        return interview
    packet, _contract, _context, signature = _visual_plan_site_packet(data)
    state = interview['assistantState']
    spec = state.get('designSpec') if isinstance(state.get('designSpec'), dict) else {}
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    previous = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    checkpoints = previous.get('checkpoints') if isinstance(previous.get('checkpoints'), dict) else {}
    checkpoints = {key: value for key, value in checkpoints.items()
                  if key in _VISUAL_PLAN_SITE_SECTION_IDS and isinstance(value, str)}
    state.update({'status': 'generating', 'inputSignature': signature, 'checkpoints': checkpoints})
    total = len(_VISUAL_PLAN_SITE_SECTIONS)
    for index, (section, description) in enumerate(_VISUAL_PLAN_SITE_SECTIONS):
        if section in checkpoints:
            continue
        system_prompt = (
            'You are Google Gemini 4 Argon writing one named, editable section of a real-estate site-plan SVG. '
            'Use only the validated pixel geometry and fixed project facts supplied. Output JSON only: '
            '{"code":"<one SVG section>"}. Visible labels are English only. Keep the plan calm and legible: '
            'no overlapping text, no narrative paragraphs, and only essential dimensions. Use the supplied '
            'named color palette consistently. Do not number legend entries. Use text labels for entrances, '
            'exits, basement access, pedestrian routes, vehicle routes, landscape, and areas when applicable. '
            'The code must be a single <g> with id="ll-section-' + section + '"; for the colors section use '
            'a single <defs id="ll-section-colors">. Preserve all given coordinates exactly.'
        )
        user_packet = {'section': section, 'sectionPurpose': description,
                       'projectFacts': packet, 'designSpec': spec,
                       'resolvedAnswers': state.get('answers') or [],
                       'sessionMemory': state.get('summary') or '',
                       'existingSections': sorted(checkpoints)}
        parsed, _tokens = _visual_plan_site_call(
            system_prompt, json.dumps(user_packet, ensure_ascii=False), data=data,
            max_tokens=_VISUAL_PLAN_SITE_SECTION_OUTPUT_LIMIT)
        checkpoints[section] = _visual_plan_site_section_fragment(parsed.get('code'), section)
        state['checkpoints'] = checkpoints
        _visual_plan_site_record_tokens(state, _tokens)
        _visual_plan_site_report_progress(
            20 + int(65 * (index + 1) / total),
            [{'id': str(i + 1), 'label': label,
              'status': ('done' if i <= index else 'pending')}
             for i, (_name, label) in enumerate(_VISUAL_PLAN_SITE_SECTIONS)], checkpoints)
    svg = _visual_plan_site_svg_from_blocks(checkpoints)
    if not svg or any('LL_SECTION_START:' + section not in svg for section in _VISUAL_PLAN_SITE_SECTION_IDS):
        raise visual_plan_geometry.PlanGeometryError('تعذر تركيب أقسام SVG في مخطط صالح.', 'PLANS_SVG_INVALID')
    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    image = persist_generated_image('data:image/svg+xml;base64,' + encoded, g.tenant_id)
    state.update({'status': 'review', 'readyForGeneration': True,
                  'generateRequested': False, 'checkpoints': checkpoints})
    _visual_plan_site_report_progress(
        98, [{'id': str(i + 1), 'label': label, 'status': 'done'}
            for i, (_name, label) in enumerate(_VISUAL_PLAN_SITE_SECTIONS)], checkpoints)
    return {'success': True, 'slotId': 'plan_site', 'image': image, 'svgCode': svg,
            'model': GEMINI_TEXT_MODEL, 'reply': 'تم إنشاء المخطط لمراجعته.',
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
    replacement = _visual_plan_site_section_fragment(parsed.get('code'), section)
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
    state['turns'].append({'role': 'assistant', 'text': reply})
    return {'success': True, 'slotId': 'plan_site', 'image': image, 'svgCode': revised,
            'targetSection': section, 'model': GEMINI_TEXT_MODEL,
            'reply': reply,
            'assistantState': state, 'scene': workflow.get('scene')}


def _visual_plan_site_assistant_execute(data, action):
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
    return _visual_plan_site_generate(data, interview), 200


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
