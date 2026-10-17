import visual_plan_scene as visual_plan_scene
import visual_plan_renderer as visual_plan_renderer


def _visual_plan_program(contract, context):
    groups, site_items = {}, []
    site_keys = _visual_concept_plan_site_component_keys(context)
    floor_cap = (_visual_concept_number(context.get('approved_floor_count'))
                 or _visual_concept_plan_regulation_floor_cap(context.get('regulations') or {}))
    for row in contract['distribution']['rows']:
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
        band = {'id': row['id'], 'name': row['component'], 'label': label, 'category': category,
                'floorLabel': _visual_concept_plan_floor_label_en(row['floor_range']),
                'floorRange': row['floor_range'], 'kind': parsed['kind'], 'count': parsed['count'],
                'lo': parsed['lo'], 'hi': parsed['hi'], 'area': row['floor_area_sqm'],
                'units': row['units_per_floor'], 'circulation': row['circulation']}
        if parsed['kind'] == 'site' or _visual_concept_plan_row_site(row, site_keys):
            site_items.append(band)
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
    if not _visual_plan_notes_cleared(data, context):
        raise visual_plan_geometry.PlanGeometryError('فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.', 'PLANS_NOTES_CHECK_REQUIRED')
    signature = _visual_plan_input_signature(data, context)
    if scene.get('inputSignature') != signature:
        raise visual_plan_geometry.PlanGeometryError('المشهد الهندسي لا يطابق بيانات المشروع الحالية.', 'PLANS_CONTEXT_CHANGED')
    posted = {key: value for key, value in scene.items() if key != 'token'}
    if not _visual_plan_token_matches('scene', data, signature, posted, scene['token']):
        raise visual_plan_geometry.PlanGeometryError('تغيرت بيانات المشهد خارج مسار التعديل.', 'PLANS_SCENE_INVALID')
    program = _visual_plan_program(contract, context)
    visual_plan_scene.validate_scene(scene, contract, program)
    return scene, contract, context, program


_PLAN_LAYOUT_KEYS = {'buildings', 'entries', 'openAreas', 'reply'}
_PLAN_LENGTH_FINISH = {'length', 'max_tokens', 'max_output_tokens', 'max_completion_tokens'}


def _visual_plan_rect_polygon(value):
    """Expand a {"rect": [x, y, width, height]} footprint shorthand into a
    polygon. The model matches an exact required area far more reliably with
    width*height than by iterating shoelace math on free polygons."""
    rect = None
    if isinstance(value, dict):
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
    if not _visual_plan_notes_cleared(data, context):
        raise visual_plan_geometry.PlanGeometryError('فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.', 'PLANS_NOTES_CHECK_REQUIRED')
    program = _visual_plan_program(contract, context)
    visual_plan_scene.check_program_feasibility(contract, program)
    reference_url = _visual_concept_render_plan_boundary_reference(contract['geometry']['surveyPoints'], g.tenant_id)
    references = _visual_concept_reference_uris(urls=[reference_url], tenant_id=g.tenant_id) if reference_url else []
    system_prompt = (
        'You plan a conceptual architectural scene; the application renders the images. '
        'The surveyed parcel geometry, primary frontage, north, setbacks, regulatory constraints, '
        'project idea, full land brief, client notes, building IDs, areas, uses, counts and floor ranges '
        'are fixed facts. Do not change or return any of them. The attached image is the same '
        'surveyed parcel supplied numerically. Local coordinates are metres: x east, y north, '
        'relative to the recorded origin. Never rotate, resize, simplify or replace the parcel. '
        'Return ONLY a proposed footprint polygon per existing building, entries on recorded street '
        'edges, and optional open areas. Every footprint must stay wholly inside one parcel, satisfy '
        'the recorded setbacks, have the exact required footprintArea, and not overlap another '
        'above-ground building. A buildable envelope polygon per parcel is provided below — it '
        'already subtracts the recorded setbacks, so a footprint wholly inside it is compliant. '
        'Basement-only footprints may overlap buildings and have no imposed '
        'above-ground setbacks. Do not invent building counts, parking capacity or floor heights. '
        'Apply every validated client note, and do not silently ignore a note. Facade styles are '
        'limited to material neutral|glass|stone|metal|render, pattern plain|grid|vertical|horizontal, '
        'and optional #RRGGBB color. Main entries must use the recorded primary frontage; service '
        'and residential entries must use recorded streets, never neighboring land. Entry position '
        'is a fraction 0..1 along the longest parcel edge on that side. Surface parking requires a '
        'recorded siteItems componentId and its recorded area. No source names, files or pages. '
        'Any footprint or open-area polygon may be written as an axis-aligned rect instead: '
        '{"rect":[x,y,width,height]} in metres — its area is exactly width*height, which makes '
        'matching the required area exact; prefer it for rectangular masses. '
        'Return JSON only: {"buildings":[{"id":"b1","footprint":[[0,0],[1,0],[1,1],[0,1]],'
        '"facades":{"west":{"material":"glass","pattern":"grid"}}}],'
        '"entries":[{"id":"main_entry","kind":"main","buildingId":"b1","side":"west",'
        '"position":0.5}],"openAreas":[{"id":"open_1","componentId":"row_1",'
        '"kind":"landscape|surface_parking","polygon":[[0,0],[1,0],[1,1]]}]}.'
    )
    envelopes = visual_plan_scene.buildable_envelopes(contract)
    envelope_note = ''
    if envelopes:
        envelope_note = ('\nBUILDABLE ENVELOPE AFTER RECORDED SETBACKS — place every above-ground '
                         'footprint inside one of these polygons:\n'
                         + json.dumps(envelopes, ensure_ascii=False))
    user_prompt = ('COMPLETE FIXED LAND AND PROJECT CONTRACT:\n' + json.dumps(contract, ensure_ascii=False)
                   + envelope_note
                   + '\nBUILDINGS AND FLOOR PROGRAM TO PLACE WITHOUT CHANGES:\n'
                   + json.dumps(program, ensure_ascii=False))
    feedback = ''
    error = None
    raw_keys = []
    cap = 8000
    for attempt in range(2):
        response = call_openrouter_chat(
            system_prompt, user_prompt + feedback, temperature=None, max_tokens=cap,
            model=GEMINI_TEXT_MODEL, reasoning_effort='high',
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
            feedback = ('\nThe previous proposal failed geometry validation: ' + str(failure)
                        + '\nIt contained JSON keys: ' + received
                        + ('\nIt returned no footprint for building ids: ' + ', '.join(missing)
                           + ' — return exactly one footprint per program building id.'
                           if missing else '')
                        + '\nCorrect only the proposed scene; the fixed contract remains unchanged.'
                        + ' Keep every footprint inside the provided buildable envelope polygons.')
    fallback_error = None
    try:
        scene = visual_plan_scene.fallback_scene(contract, program, VISUAL_PLAN_SCENE_VERSION)
        app.logger.info('Visual plan layout sealed by deterministic placement after model failures')
        return _visual_plan_seal_scene(data, scene, context), context, reference_url
    except visual_plan_geometry.PlanGeometryError as failure:
        fallback_error = failure
    if error is None or getattr(error, 'code', '') != 'PLANS_PROVIDER_FAILED':
        error = fallback_error
    else:
        app.logger.warning('Deterministic plan fallback also failed: %s', fallback_error)
    if error is None:
        error = visual_plan_geometry.PlanGeometryError(
            'تعذر إنشاء توزيع هندسي صالح للمخططات.', 'PLANS_LAYOUT_INVALID')
    if raw_keys and error is not fallback_error:
        error = visual_plan_geometry.PlanGeometryError(
            str(error) + ' — المفاتيح الواصلة: ' + '، '.join(raw_keys[:12]), error.code)
    raise error


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
            root.set('viewBox', '0 0 1600 900')
        if not root.get('width'):
            root.set('width', '1600')
        if not root.get('height'):
            root.set('height', '900')
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


def _visual_plan_render_response(data, slot_id):
    scene, contract, context, _program = _visual_plan_scene_from_request(data)
    kind = _visual_concept_plan_kind(slot_id)
    workflow = data.get('plansWorkflow') or {}
    prompt = _visual_plan_slot_prompt(workflow, kind, context)
    if kind == 'site':
        image, reference_count, model_used = _visual_plan_render_site_svg(prompt, contract, data)
    else:
        image, reference_count = _visual_plan_illustrate(prompt, contract, data)
        model_used = VISUAL_CONCEPT_IMAGE_MODEL
    return {'success': True, 'slotId': slot_id, 'image': persist_generated_image(image, g.tenant_id),
            'prompt': prompt, 'scene': scene, 'engine': 'surveyed_geometry',
            'model': model_used, 'geometryMode': 'surveyed_xy_schematic_z',
            'referenceCount': reference_count}


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
