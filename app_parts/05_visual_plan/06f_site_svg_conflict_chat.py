def _visual_plan_site_conflict_interview(data, error):
    workflow = data.get('plansWorkflow') if isinstance(data.get('plansWorkflow'), dict) else {}
    previous = workflow.get('siteAssistant') if isinstance(workflow.get('siteAssistant'), dict) else {}
    contract, context, program = {}, {}, {'buildings': []}
    signature = str(previous.get('inputSignature') or '')
    try:
        contract, context = _visual_plan_contract(data)
        program = _visual_plan_program(contract, context)
        signature = _visual_plan_input_signature(data, context)
    except (visual_plan_geometry.PlanGeometryError, KeyError, TypeError, ValueError):
        pass

    cap = visual_plan_scene._coverage_cap(contract) if contract else None
    source_buildings = {item.get('id'): item for item in program.get('buildings', [])
                        if isinstance(item, dict)}
    required = sum(visual_plan_geometry.finite_number(item.get('footprintArea')) or 0
                   for item in source_buildings.values() if not item.get('basementOnly'))
    buildings_by_name = {}
    for item in source_buildings.values():
        if item.get('basementOnly'):
            continue
        name = str(item.get('name') or 'مبنى')[:100]
        row = buildings_by_name.setdefault(name, {'name': name, 'count': 0,
                                                   'totalFootprintAreaSqm': 0})
        row['count'] += 1
        row['totalFootprintAreaSqm'] += visual_plan_geometry.finite_number(
            item.get('footprintArea')) or 0

    placed = None
    scene = workflow.get('scene') if isinstance(workflow.get('scene'), dict) else {}
    if isinstance(scene.get('buildings'), list):
        placed = 0
        for item in scene['buildings']:
            if not isinstance(item, dict):
                continue
            source = source_buildings.get(item.get('id'), {})
            if source.get('basementOnly'):
                continue
            polygon = item.get('footprint')
            if not isinstance(polygon, list) or len(polygon) < 3:
                continue
            try:
                placed += abs(visual_plan_geometry.signed_area(polygon))
            except (IndexError, TypeError, ValueError):
                continue

    coverage_ratio = visual_plan_geometry.finite_number(contract.get('coverageRatio'))
    coverage_percent = (coverage_ratio * 100 if coverage_ratio is not None and coverage_ratio <= 1
                        else coverage_ratio)
    facts = {
        'code': getattr(error, 'code', 'PLANS_COVERAGE_CONFLICT'),
        'message': str(error)[:500],
        'landAreaSqm': visual_plan_geometry.finite_number(contract.get('landArea')),
        'coverageRatioPercent': round(coverage_percent, 2) if coverage_percent is not None else None,
        'coverageCapSqm': round(cap, 2) if cap is not None else None,
        'requiredFootprintTotalSqm': round(required, 2),
        'placedFootprintTotalSqm': round(placed, 2) if placed is not None else None,
        'buildingGroups': [
            {**item, 'totalFootprintAreaSqm': round(item['totalFootprintAreaSqm'], 2)}
            for item in buildings_by_name.values()
        ][:20],
    }
    state = _visual_plan_site_state(data, signature)
    message = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if message:
        if state['pendingQuestion']:
            state['answers'].append({'question': state['pendingQuestion'], 'answer': message})
            state['answers'] = state['answers'][-100:]
        state['turns'].append({'role': 'user', 'text': message})

    system_prompt = (
        'You are the site-planning assistant continuing a client conversation in Arabic. '
        'The validated project inputs currently have a hard building-coverage conflict. '
        'Use only the supplied conflict facts and conversation history. Explain the conflict briefly '
        'with the supplied figures when available, then ask one concise question about which recorded '
        'input the client wants to review, such as the approved building areas/distribution or the '
        'recorded coverage ratio. Do not change, approve, or reinterpret any project input, survey '
        'geometry, or approved distribution. Do not claim the conflict is resolved, do not set ready, '
        'and do not generate a drawing. Always return ready=false and generateRequested=false. '
        'Return JSON only: {"ready":false,"generateRequested":false,"question":"",'
        '"choices":[],"reply":"","memory":""}.'
    )
    user_packet = {
        'task': 'discuss the current coverage conflict and ask what approved input should be reviewed',
        'coverageConflict': facts,
        'resolvedAnswers': state['answers'][-8:],
        'sessionMemory': state['summary'],
        'recentTurns': state['turns'][-8:],
        'latestClientMessage': message,
    }
    parsed = {}
    prompt_tokens = 0
    try:
        parsed, prompt_tokens = _visual_plan_site_call(
            system_prompt, json.dumps(user_packet, ensure_ascii=False), data=data,
            max_tokens=3000, reasoning_effort='medium')
    except Exception:
        # Keep the failed geometry check discussable if the chat provider is unavailable.
        pass

    question = _visual_concept_text(parsed.get('question'), 800)
    choices = [str(item).strip()[:240] for item in
               (parsed.get('choices') if isinstance(parsed.get('choices'), list) else [])[:6]
               if str(item).strip()]
    if not question:
        cap_text = f"{cap:g} م²" if cap is not None else 'الحد المسجل'
        conflict_total = placed if placed is not None else required
        total_text = f"{conflict_total:g} م²" if conflict_total else 'المساحة المسجلة'
        total_label = 'إجمالي البصمات المرسومة' if placed is not None else 'إجمالي البصمات المطلوبة'
        question = (f'{total_label} {total_text} يتجاوز حد التغطية {cap_text}. '
                    'هل تريد مراجعة مساحات المباني في التوزيع المعتمد أم نسبة التغطية المسجلة؟')
    state['pendingQuestion'] = question
    state['readyForGeneration'] = False
    state['generateRequested'] = False
    state['status'] = 'questioning'
    if parsed.get('memory'):
        state['summary'] = str(parsed['memory'])[:40000]
    _visual_plan_site_record_tokens(state, prompt_tokens)
    state['turns'].append({'role': 'assistant', 'text': question, 'choices': choices})
    return {
        'success': True, 'readyForGeneration': False, 'generateRequested': False,
        'needsClarification': True, 'question': question, 'choices': choices,
        'reply': question, 'assistantState': state, 'coverageConflict': facts,
        'contextChanged': bool(previous.get('inputSignature')
                               and previous.get('inputSignature') != signature),
    }
