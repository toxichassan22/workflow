import visual_plan_scene as visual_plan_scene
import visual_plan_renderer as visual_plan_renderer


def _visual_plan_program(contract, context):
    groups, site_items = {}, []
    floor_cap = (_visual_concept_number(context.get('approved_floor_count'))
                 or _visual_concept_plan_regulation_floor_cap(context.get('regulations') or {}))
    for row in contract['distribution']['rows']:
        parsed = _visual_concept_plan_floor_range(row.get('floor_range'))
        if parsed is None:
            raise visual_plan_geometry.PlanGeometryError('نطاق أدوار أحد المكونات غير مكتمل.', 'PLANS_DISTRIBUTION_INCOMPLETE')
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
        if parsed['kind'] == 'site':
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
    if not _visual_plan_notes_review_valid(data, context):
        raise visual_plan_geometry.PlanGeometryError('فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.', 'PLANS_NOTES_CHECK_REQUIRED')
    signature = _visual_plan_input_signature(data, context)
    if scene.get('inputSignature') != signature:
        raise visual_plan_geometry.PlanGeometryError('المشهد الهندسي لا يطابق بيانات المشروع الحالية.', 'PLANS_CONTEXT_CHANGED')
    expected = _visual_plan_token('scene', data, signature,
                                 {key: value for key, value in scene.items() if key != 'token'})
    if not _visual_plan_hmac.compare_digest(expected, scene['token']):
        raise visual_plan_geometry.PlanGeometryError('تغيرت بيانات المشهد خارج مسار التعديل.', 'PLANS_SCENE_INVALID')
    program = _visual_plan_program(contract, context)
    visual_plan_scene.validate_scene(scene, contract, program)
    return scene, contract, context, program


def _visual_plan_create_scene(data, context=None):
    contract, context = _visual_plan_contract(data, context)
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
    if not _visual_plan_notes_review_valid(data, context):
        raise visual_plan_geometry.PlanGeometryError('فحص الملاحظات الحالية غير مكتمل أو يحتوي تعارضًا.', 'PLANS_NOTES_CHECK_REQUIRED')
    program = _visual_plan_program(contract, context)
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
        'above-ground building. Basement-only footprints may overlap buildings and have no imposed '
        'above-ground setbacks. Do not invent building counts, parking capacity or floor heights. '
        'Apply every validated client note, and do not silently ignore a note. Facade styles are '
        'limited to material neutral|glass|stone|metal|render, pattern plain|grid|vertical|horizontal, '
        'and optional #RRGGBB color. Main entries must use the recorded primary frontage; service '
        'and residential entries must use recorded streets, never neighboring land. Entry position '
        'is a fraction 0..1 along the longest parcel edge on that side. Surface parking requires a '
        'recorded siteItems componentId and its recorded area. No source names, files or pages. '
        'Return JSON only: {"buildings":[{"id":"b1","footprint":[[0,0],[1,0],[1,1],[0,1]],'
        '"facades":{"west":{"material":"glass","pattern":"grid"}}}],'
        '"entries":[{"id":"main_entry","kind":"main","buildingId":"b1","side":"west",'
        '"position":0.5}],"openAreas":[{"id":"open_1","componentId":"row_1",'
        '"kind":"landscape|surface_parking","polygon":[[0,0],[1,0],[1,1]]}]}.'
    )
    user_prompt = ('COMPLETE FIXED LAND AND PROJECT CONTRACT:\n' + json.dumps(contract, ensure_ascii=False)
                   + '\nBUILDINGS AND FLOOR PROGRAM TO PLACE WITHOUT CHANGES:\n'
                   + json.dumps(program, ensure_ascii=False))
    feedback = ''
    error = None
    cap = 7000
    for attempt in range(2):
        response = call_openrouter_chat(
            system_prompt, user_prompt + feedback, temperature=None, max_tokens=cap,
            model=SLIDE_TEXT_MODEL, reasoning_effort='medium', response_format={'type': 'json_object'},
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
        text_out = _get_chat_response_text(response)
        proposed = parse_json_object(text_out)
        choice = (response.get('choices') or [{}])[0] if isinstance(response, dict) else {}
        finish = str(choice.get('native_finish_reason') or choice.get('finish_reason') or '').lower()
        try:
            scene = visual_plan_scene.make_scene(contract, program, proposed, VISUAL_PLAN_SCENE_VERSION)
            return _visual_plan_seal_scene(data, scene, context), context, reference_url
        except visual_plan_geometry.PlanGeometryError as failure:
            error = failure
            if finish == 'length' or not text_out.strip():
                cap *= 2
            received = ', '.join(sorted(proposed.keys())) if isinstance(proposed, dict) and proposed else 'none'
            app.logger.warning('Visual plan layout refused (%s, finish=%s, keys=%s)', failure, finish, received)
            feedback = ('\nThe previous proposal failed geometry validation: ' + str(failure)
                        + '\nIt contained JSON keys: ' + received
                        + '\nCorrect only the proposed scene; the fixed contract remains unchanged.')
    raise error


def _visual_plan_render_response(data, slot_id):
    scene, _contract, _context, _program = _visual_plan_scene_from_request(data)
    kind = _visual_concept_plan_kind(slot_id)
    image = visual_plan_renderer.render_plan(scene, kind)
    workflow = data.get('plansWorkflow') or {}
    return {'success': True, 'slotId': slot_id, 'image': persist_generated_image(image, g.tenant_id),
            'prompt': (workflow.get('prompts') or {}).get(kind) or '', 'scene': scene,
            'engine': 'surveyed_geometry', 'geometryMode': 'surveyed_xy_schematic_z',
            'referenceCount': len(scene['geometry']['surveyPoints'])}


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
        model=SLIDE_TEXT_MODEL, reasoning_effort='medium', response_format={'type': 'json_object'},
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
    if isinstance(result, dict) and result.get('clear') is False:
        return {'success': True, 'slotId': slot_id, 'needsClarification': True,
                'question': _visual_concept_text(result.get('question'), 600) or 'العنصر المقصود بالتعديل غير واضح.'}
    if not isinstance(result, dict) or result.get('clear') is not True:
        raise visual_plan_geometry.PlanGeometryError('لم يصل تعديل منظم صالح للمخطط.', 'PLANS_EDIT_INVALID')
    edited = visual_plan_scene.apply_edits(scene, result.get('edits'), contract, program, facade_only)
    edited = _visual_plan_seal_scene(data, edited, context)
    image = visual_plan_renderer.render_plan(edited, _visual_concept_plan_kind(slot_id))
    return {'success': True, 'slotId': slot_id, 'image': persist_generated_image(image, g.tenant_id),
            'scene': edited, 'engine': 'surveyed_geometry',
            'reply': _visual_concept_plan_sanitize_text(_visual_concept_text(result.get('reply'), 1200)) or 'تم تعديل العنصر المحدد في المخطط.'}
