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
_VISUAL_PLAN_SITE_MAX_OUTPUT_TOKENS = 66000
_VISUAL_PLAN_SITE_REPLY_MAX_CHARS = 300000
VISUAL_PLAN_SITE_MODEL = (os.environ.get('VISUAL_PLAN_SITE_MODEL') or 'openai/gpt-6.1-sol').strip()


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
    old_revision = _visual_plan_site_number(source.get('renderRevision'))
    if (source.get('inputSignature') != signature
            or (old_revision and old_revision != _VISUAL_PLAN_SITE_RENDER_REVISION)):
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
        'redesignRequested': bool(source.get('redesignRequested')),
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




def _visual_plan_site_call(system_prompt, user_prompt, data=None,
                           max_tokens=_VISUAL_PLAN_SITE_MAX_OUTPUT_TOKENS,
                           reasoning_effort=TEXT_REASONING_EFFORT):
    timeout = _visual_plan_job_call_timeout(1200)
    response = call_openrouter_chat(
        system_prompt, user_prompt, temperature=None, max_tokens=max_tokens,
        model=VISUAL_PLAN_SITE_MODEL, reasoning_effort=reasoning_effort, timeout=timeout,
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
        raise visual_plan_geometry.PlanGeometryError('ردّ الموديل غير مكتمل أو غير منظم.', 'PLANS_PROVIDER_FAILED')
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
        'On EVERY turn, review the focused project packet: '
        '1. Land & Croquis: approved land area (approvedFinancialAreaSqm), boundary lengths and coordinates polygon (surveyCoordinates), '
        'surrounding streets and widths (surroundingStreets), facades count and directions, approved floor count, coverage ratio, floor area ratio (FAR), '
        'typical floor coverage, total building area (buildingAreaSqm), and directions table (directions, including setbacks). '
        '2. Project Financial Components: financialComponents (name, category, units, ground landShareArea / unitFootprintArea). '
        '3. Phase 2 Visual Plan Notes: distributionNotes and clientNotes. '
        '4. Project Name: projectName. '
        'Treat approvedFinancialAreaSqm as the sole authoritative project land area. '
        'Do not audit or dispute minor coordinate precision differences or vertical building heights: this is strictly a 2D top-down site plan. '
        'Component rows carry landShareArea as the whole component ground-level land share in sqm; legacy rows may carry unitFootprintArea. '
        'No deterministic geometry or engineering engine calculates or rejects the design; all spatial reasoning is yours. '
        'Continue the discussion using sessionMemory, resolvedAnswers, and recentTurns while re-reading the focused packet. '
        'RULES OF YOUR ARCHITECTURAL AUTHORITY:\n'
        '1. IDENTIFYING CONFLICTS: If you find any critical regulatory or spatial conflict (e.g. total footprints exceed allowable coverage ratio, '
        'or footprints cannot fit inside buildable area), state the conflict explicitly in Arabic in "reply", explain the exact '
        'numerical facts, set ready=false, and provide 2-5 actionable choices in "choices". '
        'Once the client answers, selects an option, or confirms proceeding, accept the client direction immediately: '
        'do NOT re-raise previously noted caveats, and do NOT ask endless follow-up bonus questions. '
        '2. ANSWERING QUESTIONS & CALCULATIONS: When the client asks questions, disputes numbers, asks why there is a '
        'conflict, asks for area calculations (such as net buildable area after setbacks, remaining land area, or coverage), '
        'calculate and explain everything thoroughly and fluently in Arabic. '
        '3. ACCEPTING MODIFICATIONS: When the client requests adjustments, changes, or revisions, accept them, update '
        'your sessionMemory and designSpec, and respond constructively. '
        '4. DESIGN & GENERATION (EXECUTIVE MASTER SITE PLAN): This output is strictly a 2D Executive Conceptual Master Site Plan '
        '(مخطط عام أفقي تصوري 2D) showing ground footprints, parking, roads, setbacks, and landscape from a top-down view. '
        'Vertical building height, floor counts, and internal room distribution are completely irrelevant to a 2D ground plan. '
        'NEVER block, interrogate, question, or withhold readiness over floor counts, vertical heights, or municipal permitting. '
        'Once coverage ratio, setbacks, and ground footprints fit the parcel, conceptual readiness is 100% satisfied. '
        'When the client asks to generate or draw the master plan or confirms continuation ("ارسم", "صمم", "ولد المخطط", "قم بالتوليد", "تابع", "نعم", "وزع المباني على الأرض"), '
        'set ready=true, generateRequested=true, question="", design the layout, and provide the complete SVG in "svgCode" directly!\n'
        '5. ARCHITECTURAL PRESENTATION STANDARDS: When planning or drawing the master plan SVG, always adhere to: '
        '(a) Canvas & Safe Zone: Pure white/light background (#FFFFFF, viewBox 0 0 1600 1000) - NEVER dark or black. '
        'All drawing elements, text, and tables MUST stay strictly within SAFE ZONE: x between 80 and 1520 (80px side margins), y between 40 and 960 (40px top/bottom margins). Nothing may touch or exceed canvas borders. '
        '(b) Top Header: Anchor project title & subtitle at top-right (x=1480, text-anchor="end", y=50..75) so RTL text flows inward to the left without clipping. North arrow and scale bar on top-left (x=100..260, y=50..90). '
        '(c) 100% visual presentation: draw real striped parking bays with asphalt lanes (#475569) and trees - never solid block grids like stadium seats; realistic swimming pool with lane markers and deck; padel court lines; lush tree clusters with soft shadows. '
        '(d) Clean building roofs with title ONLY - never print BUA formulas, floor breakdowns, or paragraphs on roofs. '
        '(e) Directional arrows for entrances and ramps instead of text boxes. '
        '(f) Exactly 2 clean summary cards at the bottom on light cards (#F8FAFC, stroke #E2E8F0, rx 10) in a fixed grid: '
        'Card 1 (Ground Footprint): x="80" y="820" width="690" height="150". '
        'Card 2 (Open Spaces & Parking): x="830" y="820" width="690" height="150" (ends at x=1520, leaving 80px safe margin to the right canvas edge). '
        'TABLE COLUMN ALIGNMENT (NO SHIFTING OR OVERFLOW): Inside each card, never shift text or bunch columns against the right wall. Maintain an exact balanced column grid: '
        'Card 1 columns: Name (x=740, text-anchor="end"), Floors (x=530, text-anchor="middle"), Footprint (x=370, text-anchor="middle"), Total BUA (x=200, text-anchor="middle"). '
        'Card 2 columns: Item (x=1480, text-anchor="end"), Description (x=1240, text-anchor="middle"), Area/Capacity (x=980, text-anchor="middle"). '
        'Row texts must align vertically on the exact same X as headers. Keep at least 25px inner padding from all card edges. Never include a 3rd table. '
        'Return JSON only: {"ready":true|false,"generateRequested":true|false,"conflict":true|false,"question":"",'
        '"redesignRequested":true|false,"choices":[],"reply":"","svgCode":"","memory":"",'
        '"designSpec":{"palette":{},"layoutNotes":""}}.'
    )
    compact_mode = state['promptTokens'] >= _VISUAL_PLAN_SITE_CONTEXT_COMPACT_AT
    if action == 'generate':
        task = 'confirm readiness for generation; ask a blocking question if needed'
    elif message and len(state.get('turns') or []) <= 1:
        task = 'review all available approved site-plan inputs together with the client initial instructions, acknowledge the client notes, address any design conflicts, and confirm readiness to draw the master plan'
    elif not state['turns'] and not message:
        task = 'review all available approved site-plan inputs and begin the client interview; ask only a blocking design question if needed'
    else:
        task = 'continue the site-plan interview'
    user_packet = {
        'task': task,
        'continuation': continuing,
        'validatedProjectData': packet,
        'resolvedAnswers': state['answers'][-8:] if continuing else state['answers'],
        'sessionMemory': state['summary'],
        'recentTurns': state['turns'][-4:] if continuing else state['turns'][-8:],
        'latestClientMessage': message,
        'compactContext': compact_mode,
    }
    _visual_plan_report_site_chat_progress(3)
    model_started = time.perf_counter()
    reasoning_effort = 'medium' if continuing else 'high'
    max_tokens = _VISUAL_PLAN_SITE_MAX_OUTPUT_TOKENS
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
    reply = _visual_concept_text(parsed.get('reply'), _VISUAL_PLAN_SITE_REPLY_MAX_CHARS)
    if question:
        reply = reply or question
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
    raw_svg = str(parsed.get('svgCode') or '').strip()
    image = None
    if raw_svg and '<svg' in raw_svg:
        fenced = re.search(r'```(?:svg|xml)?\s*\n?([\s\S]*?)```', raw_svg)
        if fenced:
            raw_svg = fenced.group(1).strip()
        raw_svg = _visual_plan_site_ensure_section_markers(raw_svg)
        sanitized = _visual_plan_sanitize_svg(raw_svg)
        if sanitized and '<svg' in sanitized:
            raw_svg = sanitized
            encoded = base64.b64encode(sanitized.encode('utf-8')).decode('ascii')
            image = persist_generated_image('data:image/svg+xml;base64,' + encoded, g.tenant_id)
            state['checkpoints'] = _visual_plan_site_extract_checkpoints(sanitized)
            state['status'] = 'review'
            state['readyForGeneration'] = True
    inputs_changed = bool(prior_assistant.get('inputSignature')
                          and prior_assistant.get('inputSignature') != signature)
    state['redesignRequested'] = (bool(parsed.get('redesignRequested'))
                                  or state['redesignRequested']
                                  or (inputs_changed and bool(scene_after))
                                  or bool(scene_after and scene_after.get('inputSignature') != signature))
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
            'image': image,
            'svgCode': raw_svg,
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


def _visual_plan_site_report_progress(todos, checkpoints, signature=None):
    callback = getattr(g, 'visual_plan_job_progress', None)
    if callable(callback):
        callback(todos=todos, checkpoint={
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


def _visual_plan_site_ai_design_scene(data, packet, contract, assistant_state=None):
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
    assistant_state = assistant_state if isinstance(assistant_state, dict) else {}
    design_context = {
        **packet,
        'landParcelBoundary': parcel_polygon,
        'sessionMemory': assistant_state.get('summary') or '',
        'resolvedDecisions': assistant_state.get('answers') or [],
        'designSpec': assistant_state.get('designSpec') or {},
        'recentTurns': assistant_state.get('turns')[-6:] if assistant_state.get('turns') else [],
    }

    system_prompt = (
        'You are Argon, the lead architect and master site planner. You are the sole designer responsible for '
        'laying out the project on the parcel. There is no external layout algorithm: you determine the spatial '
        'positions, footprints, geometry, calculations, distribution, conflict checks, and client-facing explanation '
        'for all buildings, open spaces, parking, landscape, and access entries. No engineering or geometry engine '
        'will calculate, validate, rearrange, reject, or repair your design.\n'
        'You are fully empowered to generate the complete, production-ready master plan SVG directly in the "svgCode" '
        'property of your response!\n'
        'Take into full consideration the clean project data: boundaries, surrounding streets and widths, '
        'facades, setback rules, boundary lengths, orientation with north, financial components, '
        'distributionNotes, and clientNotes.\n'
        'Use projectMeasurements.landAreaSqm as the declared project land area.\n'
        'ARCHITECTURAL ZONING & PROGRAM:\n'
        '1. Honor all architectural agreements in sessionMemory, resolvedDecisions, and clientNotes:\n'
        '   - Frontage on the primary recorded street (e.g. Madinah Road).\n'
        '   - Depth 0-15m from frontage: Front setback, drop-off, and surface parking stalls (5.5m setback + 10m parking).\n'
        '   - Depth 15-45m (depth 30m): Commercial & Hospitality zone (Tower A + Tower B with ground floor strip mall and central pedestrian gateway).\n'
        '   - Depth 45-250m (depth 205m): Residential & Central Recreation zone:\n'
        '     * U-shaped townhouses/villas along North, West, and South perimeters.\n'
        '     * 6.5m dedicated vehicular driveway behind the townhouses with one-way circulation loop and parking stalls.\n'
        '     * Central courtyard: Olympic swimming pool (20x40m with lane lines and wooden deck), 2 padel courts (with court markings), health club, children playground, and central landscape.\n'
        '2. VISUAL STYLING & ARCHITECTURAL PRESENTATION STANDARD (STRICT RULES):\n'
        '   - Canvas & Safe Zone: WIDE crisp clean white or light architectural background viewBox="0 0 1600 1000" width="100%" height="100%" style="background-color: #FFFFFF; font-family: \'Segoe UI\', Roboto, sans-serif;". NEVER use dark, black, or navy backgrounds.\n'
        '     * STRICT SAFE ZONE: All boundaries, buildings, text, and tables MUST stay within x=80..1520 and y=40..960. Keep 80px minimum margin from left/right canvas borders so nothing is clipped.\n'
        '     * TOP HEADER: Anchor Arabic project title & metadata at x=1480 with text-anchor="end" (y=50..75) so RTL text flows inward to the left. Scale bar and North arrow at top-left (x=100..260, y=50..90).\n'
        '   - PURE VISUAL PRESENTATION (100% architectural elegance, NOT a data dump or math hell):\n'
        '     * Buildings: Clean roof plans with architectural outlines and clean title ONLY (e.g. "البرج الفندقي (18 طابقاً)", "ستريب مول تجاري", "مخطط الفلل السكنية (100 فيلا)"). NEVER print BUA calculations, formulas, floor breakdown paragraphs, or spreadsheets on top of building footprints!\n'
        '     * Surface Parking (200 stalls): Draw REAL architectural parking bays with white stall lines and dark asphalt lanes (#475569 / #64748b) with tree circles between stalls. NEVER draw solid colored blocks or seat-like squares.\n'
        '     * Swimming Pool: Realistic pool rendering with water tones (#0284c7 / #38bdf8), distinct lane dividers, and surrounding wooden/tiled deck border.\n'
        '     * Padel & Playground: Distinct court lines for padel, and dedicated colorful play equipment/sandbox zones.\n'
        '     * Landscape & Central Spine: Rich architectural foliage (clusters of tree circles in varied shades of green with soft shadows), green grass lawns, and winding paved pedestrian paths connecting villas to the park and pool. NEVER replace greenery with a long text box.\n'
        '     * Access & Circulation: Use sleek directional architectural arrows (أسهم انسيابية) for entry/exit gates and ramp directions instead of bulky text boxes.\n'
        '   - BOTTOM SCHEDULE & LEGEND (EXACTLY TWO CLEAN LIGHT CARDS IN FIXED GRID):\n'
        '     * Card 1: المباني والبصمة الأرضية: rect x="80" y="820" width="690" height="150" rx="10" fill="#F8FAFC" stroke="#E2E8F0". Columns: name, floors, footprint area (م²), total BUA (م²).\n'
        '     * Card 2: المساحات المفتوحة والمواقف السطحية: rect x="830" y="820" width="690" height="150" rx="10" fill="#F8FAFC" stroke="#E2E8F0" (ends at x=1520, leaving 80px safe margin to canvas edge). Columns: central park, pool & sports, surface parking & circulation area.\n'
        '     * TABLE COLUMN ALIGNMENT (NO SHIFTING OR OVERFLOW): Never bunch columns together on the right edge or shift text into borders. Distribute columns evenly across the card width:\n'
        '       Card 1 columns: Name at x=740 (text-anchor="end"), Floors at x=530 (text-anchor="middle"), Footprint at x=370 (text-anchor="middle"), Total BUA at x=200 (text-anchor="middle").\n'
        '       Card 2 columns: Item at x=1480 (text-anchor="end"), Description at x=1240 (text-anchor="middle"), Area/Capacity at x=980 (text-anchor="middle"). Card title at x=1490 (text-anchor="end", y=845).\n'
        '       Every table row text must align on the exact same X coordinate as its column header. Keep 25px minimum inner padding from all card borders.\n'
        '     * DO NOT include a 3rd card with FAR regulations, calculations, or walls of text.\n'
        '   - Parcel boundary stroke: #07182C (stroke-width 3.2).\n'
        '   - Soft pastel category fills: Residential Townhouses #E8DFC8/#F5EBE1, Hospitality Towers #2563EB/#3B82F6, '
        'Commercial Retail #D97706/#F59E0B, Swimming Pool #38BDF8 with lane markings, Padel Courts #10B981 with court lines, '
        'Playground #FBBF24, Landscape #86EFAC, Parking #94A3B8 with stalls.\n'
        '   - Include drop shadow filter cardShadow, circulation flow arrow markers, clear dimension lines, '
        'north arrow, scale bar, legend, and building schedule table.\n'
        '   - Structure the SVG with 6 modular layer comments so sections remain interactive:\n'
        '     <!-- LL_SECTION_START:coordinates -->\n'
        '     <g id="ll-section-coordinates">...</g>\n'
        '     <!-- LL_SECTION_END:coordinates -->\n'
        '     <!-- LL_SECTION_START:colors -->\n'
        '     <defs id="ll-section-colors">...</defs>\n'
        '     <!-- LL_SECTION_END:colors -->\n'
        '     <!-- LL_SECTION_START:components -->\n'
        '     <g id="ll-section-components">...</g>\n'
        '     <!-- LL_SECTION_END:components -->\n'
        '     <!-- LL_SECTION_START:access -->\n'
        '     <g id="ll-section-access">...</g>\n'
        '     <!-- LL_SECTION_END:access -->\n'
        '     <!-- LL_SECTION_START:landscape -->\n'
        '     <g id="ll-section-landscape">...</g>\n'
        '     <!-- LL_SECTION_END:landscape -->\n'
        '     <!-- LL_SECTION_START:legend -->\n'
        '     <g id="ll-section-legend">...</g>\n'
        '     <!-- LL_SECTION_END:legend -->\n'
        '   - NO emojis or emoji icons anywhere.\n'
        'Return JSON only: {"ready":true,"reply":"Arabic explanation of the master layout and zoning distribution",'
        '"svgCode":"<svg xmlns=\\"http://www.w3.org/2000/svg\\" viewBox=\\"0 0 1600 1000\\" width=\\"100%\\" height=\\"100%\\" style=\\"background-color: #FFFFFF; font-family: \'Segoe UI\', Roboto, sans-serif;\\">...</svg>",'
        '"buildings":[{"id":"","name":"","label":"","category":"","levels":1,"units":1,"footprint":[[x,y],...]}],'
        '"openAreas":[{"id":"","name":"","label":"","componentId":"","polygon":[[x,y],...],"featureType":""}],'
        '"entries":[{"id":"","point":[x,y],"entryType":"main","label":"Main Entry"}]}'
    )

    parsed, _tokens = _visual_plan_site_call(
        system_prompt, json.dumps(design_context, ensure_ascii=False),
        data=data, max_tokens=_VISUAL_PLAN_SITE_MAX_OUTPUT_TOKENS, reasoning_effort=TEXT_REASONING_EFFORT)
    if (parsed.get('ready') is False or parsed.get('conflict')) and not parsed.get('svgCode'):
        return {'assistantDecision': parsed}

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

    scene_buildings = []
    raw_buildings = parsed.get('buildings') if isinstance(parsed.get('buildings'), list) else []
    for idx, b in enumerate(raw_buildings):
        if not isinstance(b, dict) or not b.get('id'):
            continue
        bid = str(b['id'])
        footprint = ai_buildings_map.get(bid)
        if not footprint:
            continue
        scene_buildings.append({
            'id': bid,
            'name': str(b.get('name') or 'Building'),
            'label': str(b.get('label') or b.get('name') or 'Building'),
            'category': str(b.get('category') or 'residential'),
            'displayLabel': str(b.get('label') or b.get('name') or 'Building'),
            'footprint': footprint,
            'levels': b.get('levels') or 1,
            'footprintArea': b.get('footprintArea'),
            'units': int(b.get('units') or 1),
        })

    scene_open_areas = []
    raw_open_areas = parsed.get('openAreas') if isinstance(parsed.get('openAreas'), list) else []
    for s in raw_open_areas:
        if not isinstance(s, dict) or not s.get('id'):
            continue
        sid = str(s['id'])
        ai_area = ai_open_areas_map.get(sid)
        if not ai_area:
            continue
        polygon, ftype = ai_area['polygon'], ai_area['featureType']
        scene_open_areas.append({
            'id': sid,
            'componentId': str(s.get('componentId') or sid),
            'name': str(s.get('name') or 'Site Area'),
            'label': str(s.get('label') or s.get('name') or 'Site Area'),
            'category': str(s.get('category') or 'landscape'),
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
    scene = {
        'version': VISUAL_PLAN_SCENE_VERSION,
        'geometry': contract.get('geometry') or {'parcels': [{'polygon': parcel_polygon}]},
        'primaryFrontage': contract.get('primaryFrontage'),
        'setbacks': contract.get('setbacks') or {},
        'directions': contract.get('directions') or [],
        'siteItems': scene_open_areas,
        'buildings': scene_buildings,
        'openAreas': scene_open_areas,
        'entries': scene_entries,
        'svgCode': str(parsed.get('svgCode') or ''),
        'reply': str(parsed.get('reply') or ''),
    }
    signature = _visual_plan_site_context_signature(data)
    return _visual_plan_site_seal_scene(data, scene, signature)


def _visual_plan_site_extract_checkpoints(svg):
    if not svg or not isinstance(svg, str):
        return {}
    checkpoints = {}
    for section, _desc in _VISUAL_PLAN_SITE_SECTIONS:
        start_marker = '<!-- LL_SECTION_START:' + section + ' -->'
        end_marker = '<!-- LL_SECTION_END:' + section + ' -->'
        start_idx = svg.find(start_marker)
        end_idx = svg.find(end_marker)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            chunk = svg[start_idx + len(start_marker):end_idx].strip()
            if chunk:
                checkpoints[section] = chunk
                continue
        elem_tag = 'defs' if section == 'colors' else 'g'
        pattern = re.compile(rf'(<{elem_tag}[^>]*\bid=["\']ll-section-{section}["\'][\s\S]*?</{elem_tag}>)', re.IGNORECASE)
        match = pattern.search(svg)
        if match:
            checkpoints[section] = match.group(1).strip()
    return checkpoints


def _visual_plan_site_ensure_section_markers(svg):
    if not svg or not isinstance(svg, str):
        return svg
    result = svg
    for section, _desc in _VISUAL_PLAN_SITE_SECTIONS:
        start_marker = '<!-- LL_SECTION_START:' + section + ' -->'
        end_marker = '<!-- LL_SECTION_END:' + section + ' -->'
        if start_marker in result and end_marker in result:
            continue
        elem_tag = 'defs' if section == 'colors' else 'g'
        pattern = re.compile(rf'(<{elem_tag}[^>]*\bid=["\']ll-section-{section}["\'][\s\S]*?</{elem_tag}>)', re.IGNORECASE)
        match = pattern.search(result)
        if match:
            target = match.group(1)
            wrapped = f"{start_marker}\n{target}\n{end_marker}"
            result = result.replace(target, wrapped, 1)
        else:
            placeholder = (f"\n{start_marker}\n<defs id=\"ll-section-{section}\"></defs>\n{end_marker}"
                           if section == 'colors' else
                           f"\n{start_marker}\n<g id=\"ll-section-{section}\"></g>\n{end_marker}")
            svg_close = result.rfind('</svg>')
            if svg_close != -1:
                result = result[:svg_close] + placeholder + '\n' + result[svg_close:]
            else:
                result += placeholder
    return result


def _visual_plan_site_generate(data, interview):
    if interview.get('needsClarification') or not interview.get('readyForGeneration'):
        return interview
    packet, contract, _context, signature = _visual_plan_site_packet(data)
    state = interview['assistantState']
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    ai_scene = None
    direct_svg = ''
    if isinstance(interview.get('svgCode'), str) and interview.get('svgCode'):
        direct_svg = str(interview['svgCode']).strip()
    elif isinstance(workflow.get('scene'), dict) and workflow['scene'].get('svgCode') and not state.get('redesignRequested'):
        direct_svg = str(workflow['scene']['svgCode']).strip()

    if not direct_svg and (not packet.get('drawingLayout') or state.get('redesignRequested')):
        ai_scene = _visual_plan_site_ai_design_scene(data, packet, contract, assistant_state=state)
        decision = ai_scene.get('assistantDecision') if isinstance(ai_scene, dict) else None
        if isinstance(decision, dict):
            reply = _visual_concept_text(decision.get('reply'), _VISUAL_PLAN_SITE_REPLY_MAX_CHARS)
            question = _visual_concept_text(decision.get('question'), 800)
            raw_choices = decision.get('choices') if isinstance(decision.get('choices'), list) else []
            choices = [str(item).strip()[:240] for item in raw_choices[:6] if str(item).strip()]
            if question:
                state['pendingQuestion'] = question
            state['readyForGeneration'] = False
            state['generateRequested'] = True
            state['status'] = 'questioning'
            state['summary'] = str(decision.get('memory') or state.get('summary') or '')[:40000]
            state['turns'].append({'role': 'assistant', 'text': reply or question or 'لم يعتمد Argon التوزيع بعد.',
                                   'choices': choices})
            return {'success': True, 'readyForGeneration': False, 'generateRequested': True,
                    'needsClarification': bool(question), 'reply': reply, 'question': question,
                    'choices': choices, 'assistantState': state, 'scene': workflow.get('scene')}
        workflow = dict(workflow)
        workflow['scene'] = ai_scene
        data['plansWorkflow'] = workflow
        packet, contract, _context, signature = _visual_plan_site_packet(data)
        workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
        if isinstance(ai_scene, dict) and ai_scene.get('svgCode'):
            direct_svg = str(ai_scene['svgCode']).strip()

    if direct_svg:
        fenced = re.search(r'```(?:svg|xml)?\s*\n?([\s\S]*?)```', direct_svg)
        if fenced:
            direct_svg = fenced.group(1).strip()
        direct_svg = _visual_plan_site_ensure_section_markers(direct_svg)
        sanitized = _visual_plan_sanitize_svg(direct_svg)
        if sanitized and '<svg' in sanitized:
            checkpoints = _visual_plan_site_extract_checkpoints(sanitized)
            encoded = base64.b64encode(sanitized.encode('utf-8')).decode('ascii')
            image = persist_generated_image('data:image/svg+xml;base64,' + encoded, g.tenant_id)
            state.update({
                'status': 'review',
                'readyForGeneration': True,
                'generateRequested': False,
                'redesignRequested': False,
                'renderRevision': _VISUAL_PLAN_SITE_RENDER_REVISION,
                'checkpoints': checkpoints,
                'inputSignature': signature,
            })
            _visual_plan_site_report_progress(
                _visual_plan_site_section_todos(checkpoints, complete=True), checkpoints, signature)
            reply = (ai_scene.get('reply') if isinstance(ai_scene, dict) and ai_scene.get('reply')
                     else interview.get('reply') or (workflow.get('scene') if isinstance(workflow.get('scene'), dict) else {}).get('reply')
                     or 'تم إنشاء المخطط بنجاح لمراجعته.')
            state['turns'].append({'role': 'assistant', 'text': reply})

            return {
                'success': True,
                'slotId': 'plan_site',
                'image': image,
                'svgCode': sanitized,
                'model': VISUAL_PLAN_SITE_MODEL,
                'reply': reply,
                'assistantState': state,
                'scene': workflow.get('scene'),
            }
    previous = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    checkpoints = _visual_plan_site_reusable_checkpoints(previous, signature)
    state.update({'status': 'generating', 'inputSignature': signature,
                  'renderRevision': _VISUAL_PLAN_SITE_RENDER_REVISION,
                  'checkpoints': checkpoints})
    drawing_layout = packet.get('drawingLayout')
    if not drawing_layout and workflow.get('scene'):
        tenant = getattr(g, 'tenant', {})
        tenant = tenant if isinstance(tenant, dict) else {}
        drawing_layout = _visual_plan_site_projected_layout(workflow['scene'], contract, {}, {
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
    for section, _description in _VISUAL_PLAN_SITE_SECTIONS:
        if section in checkpoints:
            continue
        _visual_plan_site_report_progress(
            _visual_plan_site_section_todos(checkpoints, active_section=section), checkpoints, signature)
        checkpoints[section] = renderers[section]()
        state['checkpoints'] = checkpoints
        next_section = next((name for name, _label in _VISUAL_PLAN_SITE_SECTIONS
                             if name not in checkpoints), None)
        _visual_plan_site_report_progress(
            _visual_plan_site_section_todos(
                checkpoints, active_section=next_section,
                assembly_active=next_section is None), checkpoints, signature)
    svg = _visual_plan_site_svg_from_blocks(checkpoints)
    if not svg or any('LL_SECTION_START:' + section not in svg for section in _VISUAL_PLAN_SITE_SECTION_IDS):
        raise visual_plan_geometry.PlanGeometryError('تعذر تركيب أقسام SVG في مخطط صالح.', 'PLANS_SVG_INVALID')
    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    image = persist_generated_image('data:image/svg+xml;base64,' + encoded, g.tenant_id)
    state.update({'status': 'review', 'readyForGeneration': True,
                  'generateRequested': False, 'redesignRequested': False,
                  'renderRevision': _VISUAL_PLAN_SITE_RENDER_REVISION,
                  'checkpoints': checkpoints})
    _visual_plan_site_report_progress(
        _visual_plan_site_section_todos(checkpoints, complete=True), checkpoints, signature)
    reply = 'تم إنشاء المخطط لمراجعته.'
    return {'success': True, 'slotId': 'plan_site', 'image': image, 'svgCode': svg,
            'model': VISUAL_PLAN_SITE_MODEL, 'reply': reply,
            'assistantState': state, 'scene': workflow.get('scene')}


def _visual_plan_site_edit_facts(packet):
    """The compact drawing context, without the full regulation corpus."""
    packet = packet if isinstance(packet, dict) else {}
    contract = (packet.get('landAndRegulations')
                if isinstance(packet.get('landAndRegulations'), dict) else {})
    drawing = (packet.get('drawingLayout')
               if isinstance(packet.get('drawingLayout'), dict) else {})
    facts = {
        'projectName': packet.get('projectName') or contract.get('projectName'),
        'landAreaSqm': packet.get('approvedFinancialAreaSqm'),
        'surroundingStreets': packet.get('surroundingStreets'),
        'approvedFloorCount': packet.get('approvedFloorCount'),
        'coverageRatio': packet.get('coverageRatio'),
        'floorAreaRatio': packet.get('floorAreaRatio'),
        'buildingAreaSqm': packet.get('buildingAreaSqm'),
        'setbacks': contract.get('setbacks') or packet.get('setbacks'),
        'directions': packet.get('directions'),
        'components': packet.get('financialComponents') or [],
        'approvedLabels': drawing.get('approvedLabels') or [],
        'buildings': drawing.get('buildings') or [],
        'openAreas': drawing.get('siteItems') or drawing.get('openAreas') or [],
        'legend': drawing.get('architecturalColorLegend') or [],
    }
    return {key: value for key, value in facts.items()
            if value not in (None, '', [], {})}


def _visual_plan_site_infer_edit_section(instruction):
    """Pick the most likely section for a scoped edit, or '' when ambiguous."""
    text = str(instruction or '').casefold()

    def has(*words):
        return any(word in text for word in words)

    if has('خلفية', 'background'):
        return 'coordinates'
    if has('جدول', 'مفتاح', 'أسطورة', 'اسطورة', 'legend', 'schedule'):
        return 'legend'
    if has('طريق', 'طرق', 'مدخل', 'مداخل', 'حركة', 'مواقف', 'دخول', 'خروج',
           'road', 'entry', 'access', 'parking', 'driveway'):
        return 'access'
    if has('حديقة', 'حدائق', 'مسبح', 'ملعب', 'تشجير', 'أشجار', 'اشجار', 'نخيل',
           'landscape', 'pool', 'garden', 'tree', 'playground', 'padel'):
        return 'landscape'
    if has('مبنى', 'مباني', 'برج', 'فندق', 'سكني', 'تجاري', 'مكون', 'مكونات',
           'building', 'tower', 'component'):
        return 'components'
    if has('لون', 'ألوان', 'الوان', 'color', 'fill', 'stroke'):
        return 'colors'
    if has('حدود', 'إحداثيات', 'احداثيات', 'قطعة', 'أرض', 'parcel', 'boundary',
           'coordinates', 'setback', 'ارتداد', 'مساحة'):
        return 'coordinates'
    return ''


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
    _visual_plan_report_site_chat_progress(0)
    checkpoints = _visual_plan_site_extract_checkpoints(svg)
    target_section = str(data.get('targetSection') or '').strip()
    if target_section not in _VISUAL_PLAN_SITE_SECTION_IDS:
        target_section = _visual_plan_site_infer_edit_section(instruction)
    section_code = checkpoints.get(target_section, '') if target_section else ''
    if not section_code:
        target_section = ''
    edit_facts = _visual_plan_site_edit_facts(packet) if target_section else {}
    system_prompt = (
        'You are Google Gemini 4 Argon editing a modular architectural site plan SVG. '
        'You have two ways to respond:\n'
        '1. If the edit affects a single modular section, return JSON: '
        '{"clear":true,"targetSection":"sectionId","code":"complete replacement fragment","reply":""}.\n'
        '2. If the edit involves a spatial redesign or full regeneration, return JSON: '
        '{"clear":true,"svgCode":"<svg ...>...</svg>","reply":""}.\n'
        'Change only what is necessary, preserving every other byte and all source facts. '
        'ALWAYS prioritize Option 1 (targetSection + code fragment) whenever the edit targets a specific section (e.g. landscape, components, access, legend) to minimize output size and latency. Only use Option 2 if the user explicitly requested a total redesign. '
        'Follow architectural presentation standards: crisp white/light canvas (#FFFFFF/#f8fafc, viewBox 0 0 1600 1000). '
        'STRICT SAFE ZONE: All elements and text must fit within x=80..1520 and y=40..960 (80px side margins, 40px top/bottom). '
        'Top header title anchored at x=1480 text-anchor="end" (y=50..75). '
        '100% visual rendering (realistic parking bays with white stall lines, realistic pool with deck/lanes, tree circles, '
        'padel court markings, directional arrows for access). NEVER dump BUA math or paragraphs on roofs. '
        'Keep bottom legend to exactly 2 clean light cards (Card 1: x="80" y="820" width="690" height="150"; '
        'Card 2: x="830" y="820" width="690" height="150" ending safely at x=1520) with 25px inner padding and balanced column text, '
        'never shifted against card borders or canvas edge.'
    )
    if target_section:
        system_prompt += (
            '\n\n## بيانات المشروع (مختصرة)\n'
            + json.dumps(edit_facts, ensure_ascii=False)
            + '\n\n## القسم الحالي: ' + target_section + '\n' + section_code
            + '\n\n## التعليمات: عدّل القسم الحالي فقط وأعد JSON بالصيغة أعلاه.')
        user_packet = {
            'request': instruction,
            'targetSection': target_section,
            'resolvedAnswers': state['answers'][-8:],
            'sessionMemory': state['summary'],
            'recentTurns': state['turns'][-6:],
        }
    else:
        # Ambiguous scope: keep the full edit context rather than guessing a
        # section the user did not name.
        user_packet = {'projectFacts': packet, 'currentSvg': svg,
                       'resolvedAnswers': state['answers'][-8:], 'sessionMemory': state['summary'],
                       'recentTurns': state['turns'][-6:], 'request': instruction}
    parsed, prompt_tokens = _visual_plan_site_call(
        system_prompt, json.dumps(user_packet, ensure_ascii=False), data=data,
        max_tokens=_VISUAL_PLAN_SITE_MAX_OUTPUT_TOKENS)
    _visual_plan_site_record_tokens(state, prompt_tokens)
    _visual_plan_report_site_chat_progress(1)
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
    if parsed.get('svgCode'):
        revised_raw = str(parsed['svgCode']).strip()
        fenced = re.search(r'```(?:svg|xml)?\s*\n?([\s\S]*?)```', revised_raw)
        if fenced:
            revised_raw = fenced.group(1).strip()
        revised_raw = _visual_plan_site_ensure_section_markers(revised_raw)
        revised = _visual_plan_sanitize_svg(revised_raw)
        if not revised or '<svg' not in revised:
            raise visual_plan_geometry.PlanGeometryError('نتج عن التعديل كود SVG غير صالح.', 'PLANS_SVG_INVALID')
        encoded = base64.b64encode(revised.encode('utf-8')).decode('ascii')
        image = persist_generated_image('data:image/svg+xml;base64,' + encoded, g.tenant_id)
        checkpoints = _visual_plan_site_extract_checkpoints(revised)
        state['checkpoints'].update(checkpoints)
        state['status'] = 'review'
        reply = _visual_concept_text(parsed.get('reply'), _VISUAL_PLAN_SITE_REPLY_MAX_CHARS) or 'تم تحديث المخطط.'
        state['turns'].append({'role': 'assistant', 'text': reply})

        _visual_plan_report_site_chat_progress(2)
        return {'success': True, 'slotId': 'plan_site', 'image': image, 'svgCode': revised,
                'model': VISUAL_PLAN_SITE_MODEL, 'reply': reply,
                'assistantState': state, 'scene': workflow.get('scene')}
    section = str(parsed.get('targetSection') or target_section or '')
    if section not in _VISUAL_PLAN_SITE_SECTION_IDS:
        raise visual_plan_geometry.PlanGeometryError('قسم التعديل غير معروف.', 'PLANS_EDIT_INVALID')
    sanitized_sections = []
    drawing_layout = (packet.get('drawingLayout')
                      if isinstance(packet.get('drawingLayout'), dict) else {})
    approved_labels = (drawing_layout.get('approvedLabels')
                       if isinstance(drawing_layout.get('approvedLabels'), list) else [])
    color_legend = (drawing_layout.get('architecturalColorLegend')
                    if isinstance(drawing_layout.get('architecturalColorLegend'), list) else [])
    legend_labels = [item.get('label') for item in color_legend
                     if isinstance(item, dict) and item.get('label')]
    allowed_text = (approved_labels if section == 'components' else
                    ['PROJECT SITE PLAN', 'BUILDING SCHEDULE', 'SITE FEATURES',
                     'Recorded street', 'Internal access', 'Road and access',
                     'CONCEPTUAL PLAN | NOT TO SCALE'] + legend_labels
                    if section == 'legend' else [])
    replacement = _visual_plan_site_section_fragment(
        parsed.get('code'), section, sanitized_sections, allowed_text=allowed_text)
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
    reply = _visual_concept_text(parsed.get('reply'), _VISUAL_PLAN_SITE_REPLY_MAX_CHARS) or 'Updated the requested SVG section.'
    if sanitized_sections:
        reply += ' حُذفت تسميات غير إنجليزية من القسم المعدل.'
    state['turns'].append({'role': 'assistant', 'text': reply})
    _visual_plan_report_site_chat_progress(2)
    return {'success': True, 'slotId': 'plan_site', 'image': image, 'svgCode': revised,
            'targetSection': section, 'model': VISUAL_PLAN_SITE_MODEL,
            'reply': reply,
            'assistantState': state, 'scene': workflow.get('scene')}

def _visual_plan_site_assistant_execute(data, action):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    has_scene = isinstance(workflow.get('scene'), dict)
    scene_matches_inputs = _visual_plan_site_verify_scene(data) if has_scene else False
    if has_scene and not scene_matches_inputs:
        # Keep the fact that a prior plan existed for the redesign decision
        # below, but do not let an obsolete scene reach Argon or the response.
        workflow = dict(workflow)
        workflow['scene'] = None
        data['plansWorkflow'] = workflow
    if action == 'edit':
        assistant = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
        _packet, _contract, _context, signature = _visual_plan_site_packet(data)
        if (_visual_plan_site_number(assistant.get('renderRevision')) != _VISUAL_PLAN_SITE_RENDER_REVISION
                or assistant.get('inputSignature') != signature):
            workflow = dict(workflow)
            workflow['siteAssistant'] = {}
            workflow['scene'] = None
            data['plansWorkflow'] = workflow
            rebased = _visual_plan_site_interview(data, 'chat')
            rebased['contextChanged'] = True
            return rebased, 200
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
    if has_scene and not scene_matches_inputs:
        state = interview.get('assistantState') if isinstance(interview.get('assistantState'), dict) else {}
        state['redesignRequested'] = True
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
