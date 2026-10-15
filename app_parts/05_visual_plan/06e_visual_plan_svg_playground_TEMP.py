# TEMPORARY — SVG model playground (remove by reverting this file's commit).
#
# Stage 4 of the plans section (مقارنة الموديلات): the two finalist text models
# draw the simplified site plan (plan_site) as raw SVG from the sealed visual-plan
# scene, measuring wall time per model so the owner can pick the winner to fix
# as the permanent SVG path.
#
# The tool lives inside the plans workflow now — the standalone
# /playground-plans-svg page was retired — and it reads the same payload the
# generation stages do (current project data + plansWorkflow), so no draft
# picker is involved. The two routes here are the only entry points:
#   POST /api/visual-concept/plans-svg-playground
#   GET  /api/visual-concept/plans-svg-playground/jobs/<job_id>
#
# Deliberately isolated: not wired into generation, slides, exports or billing
# flows, persists nothing, returns inline SVG only. Revert this file's commit
# to remove the whole tool (plus tests/visual_plan/test_svg_playground_TEMP.py).

SVG_PLAYGROUND_MODELS = (
    'openai/gpt-6.1-sol',
    'google/gemini-4-argon',
)
_SVG_PLAYGROUND_NAMESPACE = '.svg_playground_jobs'
_SVG_PLAYGROUND_WIDTH = 1600
_SVG_PLAYGROUND_HEIGHT = 900


def _svg_playground_extract_svg(text):
    """Pull the first <svg>…</svg> block out of a model reply.

    Models often wrap markup in ```svg fences or add a sentence around it;
    only the markup itself is kept. Anything without a complete svg element
    is treated as empty output, never rendered.
    """
    if not isinstance(text, str):
        return ''
    fenced = re.search(r'```(?:svg|xml)?\s*\n?([\s\S]*?)```', text)
    if fenced:
        text = fenced.group(1)
    start = text.find('<svg')
    end = text.rfind('</svg>')
    if start == -1 or end == -1 or end <= start:
        return ''
    return text[start:end + 6].strip()[:200000]


def _svg_playground_sanitize_svg(svg):
    """Strip active content from model-produced SVG before display.

    The markup is rendered through <img> (no script execution there), and the
    server additionally removes script blocks, event-handler attributes,
    javascript: references and foreignObject islands. Returns '' when nothing
    safe remains.
    """
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
    return svg[:200000]


def _svg_playground_geometry(scene, contract, program=None):
    """Fixed parcel frame plus a free interior program for the SVG designer.

    Only the surveyed parcel boundary (and the setback envelopes derived from
    it) are pre-projected to exact 1600x900 pixel coordinates that the model
    must reuse verbatim — that keeps every proposal faithful to the surveyed
    land. Everything INSIDE the parcel is a design task: the model lays out
    the program masses (with their required areas, uses and floor ranges),
    the recorded entries, the street edges and the open areas itself, like a
    printed conceptual site plan. Returns (payload, required_texts,
    required_numbers).
    """
    geometry = scene.get('geometry') if isinstance(scene, dict) else {}
    parcels = [parcel['polygon'] for parcel in (geometry.get('parcels') or [])
               if isinstance(parcel, dict) and parcel.get('polygon')]
    flat = [point for polygon in parcels for point in polygon]
    if len(flat) < 3:
        raise visual_plan_geometry.PlanGeometryError(
            'هندسة المشهد لا تحمل حدودًا صالحة للرسم.', 'PLANS_SCENE_INVALID')
    project = visual_plan_geometry.fit_projection(
        flat, _SVG_PLAYGROUND_WIDTH - 100, _SVG_PLAYGROUND_HEIGHT - 170, 110)

    def screen(point):
        x, y = project(point)
        return [round(x + 50, 1), round(y + 85, 1)]

    envelopes = []
    try:
        for envelope in visual_plan_scene.buildable_envelopes(contract):
            envelopes.append([screen(point) for point in envelope['polygon']])
    except Exception:
        envelopes = []
    colors = getattr(visual_plan_renderer, 'COLORS', {})
    labels = getattr(visual_plan_renderer, 'USE_LABELS', {})
    program = program if isinstance(program, dict) else {}
    masses = []
    for building in program.get('buildings') or []:
        try:
            if not isinstance(building, dict):
                continue
            bands = []
            for band in building.get('bands') or []:
                if not isinstance(band, dict):
                    continue
                bands.append({
                    'use': labels.get(band.get('category'), band.get('label') or ''),
                    'floors': band.get('floorRange') or band.get('floorLabel') or '',
                    'area_m2': band.get('area'), 'units': band.get('units')})
            above = [band for band in (building.get('bands') or [])
                     if isinstance(band, dict) and band.get('kind') not in ('basement', 'roof')]
            category = above[0].get('category') if above else 'amenity'
            masses.append({
                'name': building.get('name') or building.get('label') or 'Building',
                'label': building.get('label') or 'Building',
                'footprint_area_m2': building.get('footprintArea'),
                'levels': building.get('levels'),
                'fill': colors.get(category, '#E7C4D3'),
                'basement_only': bool(building.get('basementOnly')),
                'bands': bands})
        except Exception:
            continue
    site_program = []
    for item in program.get('siteItems') or []:
        try:
            if not isinstance(item, dict):
                continue
            site_program.append({
                'name': item.get('name') or item.get('label') or '',
                'use': labels.get(item.get('category'), item.get('label') or ''),
                'area_m2': item.get('area'), 'units': item.get('units')})
        except Exception:
            continue
    entries = []
    for entry in scene.get('entries') or []:
        try:
            if not isinstance(entry, dict):
                continue
            entries.append({'kind': str(entry.get('kind') or 'entry'),
                            'label': str(entry.get('kind') or 'entry').title() + ' Entry',
                            'side': entry.get('side') or ''})
        except Exception:
            continue
    streets = []
    try:
        rows = {item.get('direction'): item for item in (contract.get('directions') or [])
                if isinstance(item, dict) and item.get('direction')}
        for edge in visual_plan_geometry.parcel_edges(geometry):
            direction = edge.get('direction') or ''
            row = rows.get(direction) or {}
            name = (row.get('streetName') or '').strip()
            if not name and row.get('description'):
                name = str(row['description']).split(';')[0].strip()[:80]
            if row.get('street'):
                title = (name + ' ' if name else direction.title() + ' Street ')
                if row.get('streetWidth') is not None:
                    title += '(' + str(row['streetWidth']) + ' m)'
            elif name:
                title = name
            else:
                title = direction.title() + ' Edge'
            streets.append({'label': title.strip(), 'side': direction,
                            'street': bool(row.get('street')),
                            'setback_m': row.get('setback') or ''})
    except Exception:
        streets = []
    payload = {'canvas': {'width': _SVG_PLAYGROUND_WIDTH, 'height': _SVG_PLAYGROUND_HEIGHT},
               'parcels': parcels and [[screen(point) for point in polygon] for polygon in parcels],
               'setback_envelopes': envelopes,
               'masses': masses, 'site_program': site_program,
               'entries': entries, 'streets': streets,
               'primary_frontage': (scene.get('primaryFrontage') or {}).get('direction') or '',
               'setbacks': contract.get('setbacks') or {}}
    required_texts = ['CONCEPTUAL SITE PLAN', 'ILLUSTRATIVE REFERENCE - NOT TO SCALE']
    required_texts += [item['label'] for item in masses]
    required_texts += [item['label'] for item in entries]
    required_texts += [item['label'] for item in streets]
    required_numbers = []
    for polygon in (payload['parcels'] or []) + envelopes:
        required_numbers += [str(value) for point in polygon for value in point]
    return payload, required_texts, required_numbers


def _svg_playground_brief(contract):
    """The same project facts stage 3 feeds its site-plan drawing prompt:
    recorded survey, land brief, regulatory constraints, street edges,
    setbacks, approved distribution rows and the stage-2 client notes.
    Geometry stays fixed (payload above); this brief is the creative context
    the four models lay out from — identical inputs, different hands."""
    contract = contract if isinstance(contract, dict) else {}
    lines = []
    if contract.get('projectName'):
        lines.append('Project: ' + str(contract['projectName'])[:160])
    if contract.get('projectIdea'):
        lines.append('Project idea: ' + str(contract['projectIdea'])[:2000])
    if contract.get('landBrief'):
        lines.append('Land brief: ' + str(contract['landBrief'])[:8000])
    if contract.get('regulatoryConstraints'):
        lines.append('Regulatory constraints: ' + str(contract['regulatoryConstraints'])[:8000])
    if contract.get('recordedSurvey'):
        try:
            lines.append('Recorded survey coordinates (metres, x east / y north): '
                         + json.dumps(contract['recordedSurvey'], ensure_ascii=False)[:6000])
        except Exception:
            pass
    directions = contract.get('directions') or []
    if directions:
        try:
            lines.append('Recorded edges: ' + json.dumps(directions, ensure_ascii=False)[:4000])
        except Exception:
            pass
    if contract.get('setbackText'):
        lines.append('Recorded setbacks: ' + str(contract['setbackText'])[:2000])
    if contract.get('boundaryLengths'):
        lines.append('Documented boundary lengths: ' + str(contract['boundaryLengths'])[:2000])
    distribution = contract.get('distribution') or {}
    rows = distribution.get('rows') or []
    if rows:
        try:
            lines.append('Approved distribution (stage-2 table): '
                         + json.dumps(rows, ensure_ascii=False)[:8000])
        except Exception:
            pass
    if contract.get('clientNotes'):
        lines.append('Stage-2 generation notes (apply every one): '
                     + str(contract['clientNotes'])[:8000])
    return '\n'.join(lines)[:30000]


def _svg_playground_prompts(payload, contract=None):
    colors = getattr(visual_plan_renderer, 'COLORS', {}) or {}
    labels = getattr(visual_plan_renderer, 'USE_LABELS', {}) or {}
    color_code = '; '.join(f'{labels.get(key, key)} = {value}' for key, value in colors.items())
    system_prompt = (
        'You are a specialist in designing real-estate site plans by writing SVG code. '
        'You must comply with the component counts, footprint areas, coordinates and every '
        'field below — they are recorded facts, not suggestions. Draw ONE standalone <svg> '
        'element and output ONLY the raw SVG markup — no markdown fences, no explanation. '
        'All visible text is English only. '
        'FIXED COLOR IDENTITY — use exactly these fills, no substitutes: ' + (color_code or 'pastel fills') + '; '
        'parcel #EDF3E8 with navy #172B4D outline width 4 and vertex dots; '
        'setback envelope dashed #81939F width 2, no fill; '
        'basement-only masses hatched, never surface blocks; '
        'surface parking light grey with white stall lines and a tree row; '
        'landscape pale green with scattered tree circles; '
        'entries as color-coded arrows (main red, residential blue, service orange) with navy labels. '
        'Daylight cartography on white — first element a full-canvas #FFFFFF rect; '
        'NEVER a dark background, no photorealism, no invented dimensions. '
        'Compose a real brochure layout, not scattered rectangles: group related masses, wrap '
        'housing around a landscaped courtyard with the listed pool and play areas, towers on '
        'the high-rise side, front setback open for surface parking and the main entry. '
        'The first attached images are owner-approved site plans — imitate their colors, '
        'legend, parking stalls, trees and entry arrows. The last attached image is the '
        'true surveyed parcel outline — trace its exact shape and proportions for the '
        'parcel boundary.')
    fields = {
        'project': {key: (contract or {}).get(key) for key in
                    ('projectName', 'projectIdea') if isinstance(contract, dict)},
        'parcel_pixels': payload.get('parcels'),
        'setback_envelope_pixels': payload.get('setback_envelopes'),
        'setbacks_m': payload.get('setbacks'),
        'streets': payload.get('streets'),
        'masses': payload.get('masses'),
        'site_program': payload.get('site_program'),
        'entries': payload.get('entries'),
        'primary_frontage': payload.get('primary_frontage'),
        'notes': (contract or {}).get('clientNotes') if isinstance(contract, dict) else '',
        'land_brief': (contract or {}).get('landBrief') if isinstance(contract, dict) else '',
        'regulatory_constraints': (contract or {}).get('regulatoryConstraints')
        if isinstance(contract, dict) else '',
    }
    user_prompt = (
        'PROJECT DATA FIELDS (reuse every parcel coordinate number EXACTLY as given; '
        'every mass footprint stays wholly inside the parcel; every program mass appears '
        'once with its recorded area and use):\n'
        + json.dumps(fields, ensure_ascii=False)
        + '\nREQUIRED OUTPUT: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" '
        'width="1600" height="900">; '
        "top-left title 'CONCEPTUAL SITE PLAN' 30px navy plus project name and city; "
        "bottom-right caption 'ILLUSTRATIVE REFERENCE - NOT TO SCALE'; "
        "north arrow 'N' pointing up; "
        "bottom-left legend 'SITE PLAN LEGEND & APPROVED PROGRAM' with one chip per use color above."
    )
    return system_prompt, user_prompt


def _svg_playground_score(svg, required_texts, required_numbers):
    """Fidelity score 0..100: share of required labels and coordinate values
    present verbatim in the produced SVG. Lets the owner compare models on
    faithfulness to the sealed inputs, not on looks."""
    if not svg:
        return 0.0
    texts = [item for item in required_texts if item]
    numbers = [item for item in required_numbers if item]
    total = len(texts) + len(numbers)
    if not total:
        return 0.0
    found = sum(1 for item in texts if item in svg)
    found += sum(1 for item in numbers if item in svg)
    return round(found / total * 100, 1)


_SVG_PLAYGROUND_LENGTH_FINISH = {'length', 'max_tokens', 'max_output_tokens', 'max_completion_tokens'}


# Owner-ordered budgets: argon caps at 66K, the other three at 128K, and all
# four reason at medium effort to keep the token burn economical.
_SVG_PLAYGROUND_MODEL_BUDGETS = {
    'google/gemini-4-argon': {'max_tokens': 66000, 'reasoning_effort': 'medium'},
}
_SVG_PLAYGROUND_DEFAULT_BUDGET = {'max_tokens': 128000, 'reasoning_effort': 'medium'}
_SVG_PLAYGROUND_TIMEOUT = 600


def _svg_playground_finish_reason(response):
    try:
        choice = (response.get('choices') or [{}])[0] if isinstance(response, dict) else {}
        return str(choice.get('native_finish_reason') or choice.get('finish_reason') or '').lower()
    except Exception:
        return ''


def _svg_playground_thinking(response):
    """The model's reasoning excerpt, for the owner's live inspection.

    With max-effort budgets a model can think for minutes before drawing;
    this surfaces what it is thinking about (kept on every result, success or
    failure, truncated to 4000 chars) instead of a silent clock."""
    try:
        choice = (response.get('choices') or [{}])[0] if isinstance(response, dict) else {}
        message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
        parts = []
        for key in ('reasoning', 'reasoning_content'):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        details = message.get('reasoning_details')
        if isinstance(details, list):
            for item in details:
                text = item.get('text') if isinstance(item, dict) else None
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        thinking = '\n\n'.join(parts).strip()
        return thinking[:4000]
    except Exception:
        return ''


_SVG_PLAYGROUND_STYLE_IMAGES = (
    'svg_playground_style_site_1.jpg',
    'svg_playground_style_site_2.jpg',
    'svg_playground_style_site_3.jpg',
)


def _svg_playground_style_references():
    """Owner-approved site-plan style examples, shipped beside this file.
    Missing files are skipped, never fatal — the comparison still runs."""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return []
    references = []
    for name in _SVG_PLAYGROUND_STYLE_IMAGES:
        try:
            path = os.path.join(root, 'app_parts', '05_visual_plan', name)
            if not os.path.isfile(path) or os.path.getsize(path) > 5 * 1024 * 1024:
                continue
            with open(path, 'rb') as handle:
                encoded = base64.b64encode(handle.read()).decode('ascii')
            references.append('data:image/jpeg;base64,' + encoded)
        except OSError:
            continue
    return references


def _svg_playground_references(contract):
    """Attached reference images, built once per run: first the owner-approved
    style examples to imitate, last the surveyed-parcel outline to trace — so
    the models copy a seen look and a seen shape instead of guessing from
    numbers. Any failure degrades to text-only rather than breaking the
    comparison."""
    references = []
    try:
        references += _svg_playground_style_references()
    except Exception:
        pass
    try:
        geometry = (contract or {}).get('geometry') or {}
        points = geometry.get('surveyPoints') or []
        if len(points) < 3:
            return references
        url = _visual_concept_render_plan_boundary_reference(points, g.tenant_id)
        if not url:
            return references
        return references + (_visual_concept_reference_uris(urls=[url], tenant_id=g.tenant_id) or [])
    except Exception:
        return references


def _svg_playground_run_model(model, system_prompt, user_prompt, data, usage_ctx=None,
                              image_references=None):
    """Run one model, measuring wall time. A model failure is recorded on its
    own result — it never aborts the remaining models.

    Each model runs on its owner-ordered budget (argon 66K, the rest 128K,
    all at medium effort) with a 10-minute provider timeout: a length-truncated reply is
    retried once at the same cap with an emit-markup-only nudge before it is
    reported as a failure."""
    started = time.perf_counter()
    budget = _SVG_PLAYGROUND_MODEL_BUDGETS.get(model, _SVG_PLAYGROUND_DEFAULT_BUDGET)
    cap = budget['max_tokens']
    effort = budget['reasoning_effort']
    if usage_ctx is None:
        usage_ctx = _usage_ctx('image', data)
    content = user_prompt
    for attempt in range(2):
        try:
            response = call_openrouter_chat(
                system_prompt, content, temperature=None, max_tokens=cap,
                model=model, reasoning_effort=effort, timeout=_SVG_PLAYGROUND_TIMEOUT,
                image_references=image_references or None, usage_ctx=usage_ctx)
        except Exception as error:
            fatal = _ai_fatal_http_response(error)
            if fatal is not None:
                detail = _client_safe_llm_error(str(error)[:300])
            else:
                detail = str(error)[:300]
            return {'model': model, 'ok': False, 'ms': int((time.perf_counter() - started) * 1000),
                    'chars': 0, 'score': 0.0, 'svg': '', 'error': detail or 'تعذر التوليد'}
        fatal = _ai_fatal_error_dict(response)
        if fatal is not None:
            return {'model': model, 'ok': False, 'ms': int((time.perf_counter() - started) * 1000),
                    'chars': 0, 'score': 0.0, 'svg': '',
                    'error': _client_safe_llm_error(fatal.get('message')) or 'تعذر التوليد'}
        if isinstance(response, dict) and response.get('error'):
            return {'model': model, 'ok': False, 'ms': int((time.perf_counter() - started) * 1000),
                    'chars': 0, 'score': 0.0, 'svg': '',
                    'error': _client_safe_llm_error(_chat_error_message(response)) or 'تعذر التوليد'}
        text = _get_chat_response_text(response)
        if _svg_playground_extract_svg(text):
            return {'model': model, '_svg': text,
                    '_ms': int((time.perf_counter() - started) * 1000),
                    'thinking': _svg_playground_thinking(response)}
        finish = _svg_playground_finish_reason(response)
        if finish in _SVG_PLAYGROUND_LENGTH_FINISH and attempt == 0:
            # Truncated mid-drawing, not a refusal — the cap is already at the
            # model maximum, so retry at the same budget asking for markup only.
            content = (user_prompt
                       + '\nYour previous reply hit the output limit before </svg>. '
                         'Emit the complete <svg> now with minimal preamble — no reasoning text, '
                         'no explanation, just the markup.')
            continue
        detail = 'انقطع رد الموديل قبل اكتمال SVG' if finish in _SVG_PLAYGROUND_LENGTH_FINISH else ''
        received = len(text or '')
        if received:
            detail += f' (وصل {received} حرفًا' + (f'، السبب: {finish}' if finish else '') + ')'
        return {'model': model, 'ok': False, 'ms': int((time.perf_counter() - started) * 1000),
                'chars': 0, 'score': 0.0, 'svg': '', 'thinking': _svg_playground_thinking(response),
                'error': (detail or 'لا يوجد SVG صالح في رد الموديل') + ' — أعد التشغيل'}
    return {'model': model, 'ok': False, 'ms': int((time.perf_counter() - started) * 1000),
            'chars': 0, 'score': 0.0, 'svg': '', 'thinking': '',
            'error': 'لا يوجد SVG صالح في رد الموديل — أعد التشغيل'}


def _svg_playground_finalize(raw, payload_texts, payload_numbers):
    svg = _svg_playground_sanitize_svg(_svg_playground_extract_svg(raw.pop('_svg', '')))
    raw['ms'] = raw.pop('_ms', 0)
    if not svg:
        raw.update(ok=False, svg='', chars=0, score=0.0,
                   error=raw.get('error') or 'لا يوجد SVG صالح في رد الموديل')
    else:
        raw.update(ok=True, svg=svg, chars=len(svg),
                   score=_svg_playground_score(svg, payload_texts, payload_numbers),
                   error='')
    return raw


# Stage 4 sits after verification, boundary and distribution — never after the
# generation stage. A scene that stage 3 has not sealed yet, or sealed against
# other inputs, is rebuilt here from the same contract stage 3 uses, so the
# comparison is reachable as soon as stages 1 and 2 are approved.
_SVG_PLAYGROUND_RESEAL_CODES = ('PLANS_SCENE_REQUIRED', 'PLANS_SCENE_INVALID',
                                'PLANS_CONTEXT_CHANGED')


def _svg_playground_scene(data):
    """Return (scene, contract, created) for the comparison.

    A sealed scene already stored by the generation stage is reused as-is.
    Anything missing or stale is sealed right here and handed back in `created`
    so the client can keep it — the exact information stage 3 consumes, just
    obtained without stage 3.
    """
    try:
        scene, contract, _context, program = _visual_plan_scene_from_request(data)
        return scene, contract, program, None
    except visual_plan_geometry.PlanGeometryError as error:
        if error.code not in _SVG_PLAYGROUND_RESEAL_CODES:
            raise
    created_scene, _context, _reference_url = _visual_plan_create_scene(data)
    sealed = dict(data)
    sealed['plansWorkflow'] = {**(data.get('plansWorkflow') or {}), 'scene': created_scene}
    scene, contract, _context, program = _visual_plan_scene_from_request(sealed)
    return scene, contract, program, created_scene


def _svg_playground_execute(data, on_model=None):
    """Build the SVG prompt from the sealed scene, then run the finalist models in
    parallel threads — sequential runs summed every model's wall time, which is
    why a comparison took several minutes with nothing on screen.

    `on_model` receives the finished results (in model order) after each model
    lands, so a worker can publish every model's exact wall time as soon as it
    arrives instead of holding all four until the slowest one returns. The
    metering context is built once up front: worker threads have no Flask `g`.
    """
    try:
        scene, contract, program, created_scene = _svg_playground_scene(data)
    except visual_plan_geometry.PlanGeometryError as error:
        status = 503 if error.code in ('PLANS_NOTES_CHECK_FAILED', 'PLANS_PROVIDER_FAILED') else 400
        return {'success': False, 'error': str(error), 'error_code': error.code}, status
    except (TypeError, ValueError):
        return {'success': False, 'error': 'بيانات المشهد الهندسي غير صالحة.',
                'error_code': 'PLANS_DATA_INVALID'}, 400
    payload, required_texts, required_numbers = _svg_playground_geometry(scene, contract, program)
    system_prompt, user_prompt = _svg_playground_prompts(payload, contract)
    ctx = _usage_ctx('image', data)
    references = _svg_playground_references(contract)
    slots = [None] * len(SVG_PLAYGROUND_MODELS)
    lock = threading.Lock()

    def run_index(index, model):
        raw = _svg_playground_run_model(model, system_prompt, user_prompt, data, usage_ctx=ctx,
                                        image_references=references)
        if '_svg' in raw:
            raw = _svg_playground_finalize(raw, required_texts, required_numbers)
        with lock:
            slots[index] = raw
            snapshot = [item for item in slots if item is not None]
        if on_model is not None:
            on_model(snapshot)

    workers = [threading.Thread(target=run_index, args=(index, model), daemon=True)
               for index, model in enumerate(SVG_PLAYGROUND_MODELS)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return {'success': True, 'results': list(slots), 'models': list(SVG_PLAYGROUND_MODELS),
            'scene': created_scene}, 200


def _svg_playground_worker(flask_app, actor, data, job_id):
    tenant_id = actor['tenant_id']
    with flask_app.test_request_context('/api/visual-concept/plans-svg-playground/' + job_id,
                                        method='POST', json=data):
        for key, value in actor.items():
            setattr(g, key, value)
        try:
            tenant = db.get_tenant_by_id(tenant_id)
            payload = actor.get('token_payload') or {}
            user, auth_error = auth._load_token_user(payload, tenant) if tenant else (None, None)
            session_error = auth._session_state_error(payload, tenant, user) if tenant and tenant.get('is_active') and auth_error is None else None
            g.tenant = tenant
            g.user_id = (user or {}).get('id')
            g.user_role = (user or {}).get('role') or actor.get('user_role')
            g.is_admin = auth._is_platform_admin_session(tenant, payload) if tenant else False
            g.user_permissions = db.get_user_permissions(g.user_id, g.user_role) if g.user_id else {}
            if not tenant or not tenant.get('is_active') or auth_error is not None or session_error is not None or payload.get('exp', 0) < time.time() or not _landloom_can('generate_images'):
                result, status = {'success': False, 'error': 'صلاحية معالجة المخططات غير متاحة.',
                                  'error_code': 'PLANS_PERMISSION_REQUIRED'}, 403
            else:
                _write_job(_SVG_PLAYGROUND_NAMESPACE, tenant_id, job_id,
                           {'status': 'running', 'success': True, 'progress': 15})

                def report_finished(results):
                    _write_job(_SVG_PLAYGROUND_NAMESPACE, tenant_id, job_id,
                               {'status': 'running', 'success': True,
                                'progress': 15 + int(80 * len(results) / len(SVG_PLAYGROUND_MODELS)),
                                'partial': {'success': True, 'results': results,
                                            'models': list(SVG_PLAYGROUND_MODELS)}})

                result, status = _svg_playground_execute(data, on_model=report_finished)
            _write_job(_SVG_PLAYGROUND_NAMESPACE, tenant_id, job_id,
                       {'status': 'completed' if result.get('success') else 'failed',
                        'success': bool(result.get('success')), 'progress': 100,
                        'result': result, 'httpStatus': status})
            if not flask_app.config.get('TESTING'):
                _bill_tenant_unbilled_usage_async(tenant_id)
        except Exception:
            app.logger.warning('SVG playground worker failed')
            _write_job(_SVG_PLAYGROUND_NAMESPACE, tenant_id, job_id,
                       {'status': 'failed', 'success': False, 'progress': 100, 'httpStatus': 503,
                        'result': {'success': False, 'error': 'تعذرت مقارنة الموديلات.',
                                   'error_code': 'PLANS_PROVIDER_FAILED'}})


def _svg_playground_dispatch(data):
    if current_app.config.get('TESTING') and data.get('background') is not True:
        result, status = _svg_playground_execute(data)
        return jsonify(result), status
    job_id = _uuid.uuid4().hex
    actor = {key: getattr(g, key, None) for key in
             ('tenant_id', 'user_id', 'user_name', 'user_role', 'is_admin', 'token_payload')}
    _write_job(_SVG_PLAYGROUND_NAMESPACE, g.tenant_id, job_id,
               {'status': 'queued', 'success': True, 'progress': 5, 'actor': actor,
                'payload': {'data': data}})
    threading.Thread(target=_svg_playground_worker,
                     args=(current_app._get_current_object(), actor, data, job_id),
                     daemon=True).start()
    return jsonify({'success': True, 'jobId': job_id, 'status': 'queued', 'progress': 5}), 202


@app.route('/api/visual-concept/plans-svg-playground', methods=['POST'])
@require_permission('generate_images')
def api_visual_concept_svg_playground():
    # TEMPORARY playground endpoint (revert with this file's commit).
    data = request.get_json(silent=True) or {}
    workflow_error = _visual_concept_plan_workflow_error(
        data, 'plan_site', require_boundary=True, require_distribution=True)
    if workflow_error:
        return jsonify(workflow_error), 400
    _billing_guard = _require_billing_balance('visual_concept')
    if _billing_guard is not None:
        return _billing_guard
    return _svg_playground_dispatch(data)


@app.route('/api/visual-concept/plans-svg-playground/jobs/<job_id>', methods=['GET'])
@require_permission('generate_images')
def api_visual_concept_svg_playground_job(job_id):
    # TEMPORARY playground polling (revert with this file's commit).
    try:
        job = _read_job(_SVG_PLAYGROUND_NAMESPACE, g.tenant_id, job_id)
    except ValueError:
        job = None
    if not job:
        return jsonify({'success': False, 'error': 'مهمة المقارنة غير موجودة.',
                        'error_code': 'JOB_NOT_FOUND'}), 404
    if job.get('status') in ('queued', 'running') and time.time() - job.get('updatedAt', 0) > 600:
        job = {'status': 'failed', 'success': False, 'progress': 100, 'httpStatus': 503,
               'result': {'success': False, 'error': 'انتهت مهلة مقارنة الموديلات.',
                          'error_code': 'PLANS_JOB_EXPIRED'}}
        _write_job(_SVG_PLAYGROUND_NAMESPACE, g.tenant_id, job_id, job)
    # `partial` carries the models that already finished, so the client shows
    # each one's time without waiting for the slower ones.
    return jsonify({key: job[key] for key in ('status', 'success', 'progress', 'result',
                                              'httpStatus', 'partial') if key in job})
