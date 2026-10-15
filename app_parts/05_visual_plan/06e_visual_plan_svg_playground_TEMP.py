# TEMPORARY — SVG model playground (remove by reverting this file's commit).
#
# Stage 4 of the plans section (مقارنة الموديلات): the same 4 text models draw
# the simplified site plan (plan_site) as raw SVG from the sealed visual-plan
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
    'anthropic/claude-sonnet-5.5',
    'anthropic/claude-haiku-5.5',
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
    system_prompt = (
        'You are an architect drawing a conceptual site plan as vector SVG — the kind '
        'pinned on a developer brochure: a fully designed layout inside a real surveyed '
        'parcel, not a set of blocks dropped on a canvas. You receive the exact surveyed '
        'parcel boundary as finished pixel coordinates plus the full building program. '
        'Draw ONE standalone <svg> element. '
        'HARD RULES: reuse every parcel-boundary and setback-envelope coordinate number '
        'EXACTLY as given — never recompute, rescale, round differently or invent the '
        'boundary; every mass footprint and open area must sit wholly inside the parcel; '
        'every program mass must appear once with its recorded footprint area and use; '
        'all visible text is English only. '
        'STYLE is natural daylight cartography, exactly like a printed site plan: '
        'the very first element is a full-canvas white rect (width 1600 height 900 fill #FFFFFF); '
        'parcel = very light green-grey fill #EDF3E8 with navy #172B4D outline width 4 and '
        'vertex dots; setback envelope = dashed #81939F width 2, no fill; masses = their '
        'given pastel fill with navy outline width 3 and a centered navy label carrying name, '
        'area in m2 and floor range; basement-only masses are drawn as a hatched zone, never '
        'as a surface block; surface parking = light grey with drawn white stall lines and a '
        'tree row; landscape = pale green with scattered tree circles; entries = color-coded '
        'arrows (main red, residential blue, service orange) pointing into the site with navy '
        'labels; streets = recorded name plus width on their edge, neighbors marked Neighbor; '
        'all text and outlines dark navy on light fills — NEVER a dark or night background, '
        'no black/navy canvas, no photorealism, no satellite imagery, no invented dimensions. '
        'DESIGN MANDATE: compose a real layout — group related masses, wrap housing wings '
        'around a central landscaped courtyard with pool and play areas where the program '
        'lists them, place towers on the high-rise side, keep the front setback open for '
        'surface parking and the main entry, fill leftovers with landscape. A drawing of '
        'loose scattered rectangles is a failure. '
        'Output ONLY the raw SVG markup — no markdown fences, no explanation, no surrounding text.')
    user_prompt = (
        'FIXED PARCEL FRAME (boundary and setback coordinates: reuse verbatim):\n'
        + json.dumps({key: payload.get(key) for key in
                       ('canvas', 'parcels', 'setback_envelopes', 'setbacks', 'primary_frontage')},
                      ensure_ascii=False)
        + '\nPROGRAM TO LAY OUT INSIDE IT (design the arrangement yourself):\n'
        + json.dumps({key: payload.get(key) for key in
                       ('masses', 'site_program', 'entries', 'streets')}, ensure_ascii=False)
        + '\nPROJECT BRIEF (same facts as the permanent site-plan prompt):\n'
        + (_svg_playground_brief(contract) or '—')
        + '\nCANVAS (fixed): <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" '
        'width="1600" height="900"> starting with '
        '<rect width="1600" height="900" fill="#FFFFFF"/>; '
        "title top-left 'CONCEPTUAL SITE PLAN' 30px navy #172B4D plus project name and city; "
        "caption bottom-right 'ILLUSTRATIVE REFERENCE - NOT TO SCALE' 18px navy; "
        "north arrow 'N' pointing up; bottom-left legend box 'SITE PLAN LEGEND & APPROVED PROGRAM' "
        'with a color chip per use present plus Parcel Boundary and Setback Envelope keys.')
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


def _svg_playground_run_model(model, system_prompt, user_prompt, data, usage_ctx=None):
    """Run one model, measuring wall time. A model failure is recorded on its
    own result — it never aborts the remaining models.

    Each model runs on its owner-ordered budget (argon 66K/high, the rest
    128K/max) with a 10-minute provider timeout: a length-truncated reply is
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
                usage_ctx=usage_ctx)
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
                    '_ms': int((time.perf_counter() - started) * 1000)}
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
                'chars': 0, 'score': 0.0, 'svg': '',
                'error': (detail or 'لا يوجد SVG صالح في رد الموديل') + ' — أعد التشغيل'}
    return {'model': model, 'ok': False, 'ms': int((time.perf_counter() - started) * 1000),
            'chars': 0, 'score': 0.0, 'svg': '', 'error': 'لا يوجد SVG صالح في رد الموديل — أعد التشغيل'}


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
    """Build the SVG prompt from the sealed scene, then run the 4 models.

    `on_model` receives the finished results after each model, so a worker can
    publish every model's exact wall time as soon as it lands instead of holding
    all four until the slowest one returns.
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
    results = []
    for model in SVG_PLAYGROUND_MODELS:
        raw = _svg_playground_run_model(model, system_prompt, user_prompt, data)
        if '_svg' in raw:
            raw = _svg_playground_finalize(raw, required_texts, required_numbers)
        results.append(raw)
        if on_model is not None:
            on_model(list(results))
    return {'success': True, 'results': results, 'models': list(SVG_PLAYGROUND_MODELS),
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
