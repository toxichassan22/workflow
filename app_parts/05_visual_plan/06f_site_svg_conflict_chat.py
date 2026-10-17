def _visual_plan_site_area_text(value):
    number = visual_plan_geometry.finite_number(value)
    return f'{number:,.2f}'.rstrip('0').rstrip('.') if number is not None else ''


def _visual_plan_site_conflict_summary(facts):
    land = facts.get('landAreaSqm')
    ratio = facts.get('coverageRatioPercent')
    cap = facts.get('coverageCapSqm')
    required = facts.get('requiredFootprintTotalSqm')
    placed = facts.get('placedFootprintTotalSqm')
    parts = ['سبب التعارض هو تجاوز حد التغطية المحسوب من بيانات الأرض.']
    if land is not None and ratio is not None and cap is not None:
        parts.append(
            f"الحساب: مساحة الأرض {_visual_plan_site_area_text(land)} م² × "
            f"نسبة التغطية {_visual_plan_site_area_text(ratio)}% = "
            f"حد أقصى {_visual_plan_site_area_text(cap)} م² للبصمات الأرضية.")
    elif cap is not None:
        parts.append(f"حد التغطية المسجل هو {_visual_plan_site_area_text(cap)} م² للبصمات الأرضية.")
    if placed is not None:
        parts.append(f"مجموع البصمات في المخطط الحالي {_visual_plan_site_area_text(placed)} م².")
    if required:
        parts.append(f"المجموع المطلوب من التوزيع المعتمد {_visual_plan_site_area_text(required)} م².")

    compared = [('المخطط الحالي', placed), ('التوزيع المعتمد', required)]
    excess = [(label, total - cap) for label, total in compared
              if total is not None and cap is not None and total > cap + 0.5]
    if excess:
        if len(excess) == 1:
            label, amount = excess[0]
            parts.append(f"زيادة {label} عن الحد {_visual_plan_site_area_text(amount)} م².")
        elif abs(excess[0][1] - excess[1][1]) <= 0.5:
            parts.append(f"الزيادة عن الحد {_visual_plan_site_area_text(excess[0][1])} م².")
        else:
            parts.append('المخطط والتوزيع يتجاوزان حد التغطية المسجل.')

    group_details = []
    for item in facts.get('buildingGroups', [])[:4]:
        count = item.get('count') or 0
        total = item.get('totalFootprintAreaSqm') or 0
        low = item.get('minFootprintAreaSqm')
        high = item.get('maxFootprintAreaSqm')
        if not count or not total:
            continue
        if low is not None and high is not None and abs(high - low) <= 0.5:
            area_detail = (f"{count} × {_visual_plan_site_area_text(low)} م² لكل مبنى")
        else:
            area_detail = f"إجمالي {_visual_plan_site_area_text(total)} م²"
        group_details.append(f"{item.get('name')}: {area_detail}")
    if group_details:
        parts.append('تفصيل البصمات: ' + '؛ '.join(group_details) + '.')
    parts.append('المقارنة هنا مع مساحة الدور الأرضي المشغولة، لا مجموع مساحات جميع الأدوار.')
    return ' '.join(parts)


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
        area = visual_plan_geometry.finite_number(item.get('footprintArea')) or 0
        row = buildings_by_name.setdefault(name, {'name': name, 'count': 0,
                                                   'totalFootprintAreaSqm': 0,
                                                   'minFootprintAreaSqm': area,
                                                   'maxFootprintAreaSqm': area})
        row['count'] += 1
        row['totalFootprintAreaSqm'] += area
        row['minFootprintAreaSqm'] = min(row['minFootprintAreaSqm'], area)
        row['maxFootprintAreaSqm'] = max(row['maxFootprintAreaSqm'], area)

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
            {**item,
             'totalFootprintAreaSqm': round(item['totalFootprintAreaSqm'], 2),
             'minFootprintAreaSqm': round(item['minFootprintAreaSqm'], 2),
             'maxFootprintAreaSqm': round(item['maxFootprintAreaSqm'], 2)}
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
        'Use only the supplied conflict facts and conversation history. Respond to the latest client '
        'message instead of repeating a generic menu. Put a brief direct response in reply, then one '
        'specific follow-up in question. Acknowledge when the client says they reviewed '
        'the data or drew the same plan: visual similarity does not remove the numeric coverage limit. '
        'Do not repeat the exact figures in reply; the server displays its calculation separately. Ask one '
        'specific follow-up about which source number is disputed. Do not change, approve, or reinterpret '
        'any project input, survey geometry, or approved distribution. Do not claim the conflict is '
        'resolved, do not set ready, and do not generate a drawing. Always return ready=false and '
        'generateRequested=false. '
        'Return JSON only: {"ready":false,"generateRequested":false,"question":"",'
        '"choices":[],"reply":"","memory":""}.'
    )
    user_packet = {
        'task': 'explain this exact coverage conflict in the context of the latest client message',
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

    model_question = _visual_concept_text(parsed.get('question'), 600)
    model_reply = _visual_concept_text(parsed.get('reply'), 500)
    choices = [str(item).strip()[:240] for item in
               (parsed.get('choices') if isinstance(parsed.get('choices'), list) else [])[:6]
               if str(item).strip()]
    if not model_question:
        model_question = 'أي رقم تريد مناقشته: بصمة المباني في التوزيع أم نسبة التغطية المسجلة؟'
    explanation = _visual_plan_site_conflict_summary(facts)
    reply_parts = [explanation]
    if model_reply and model_reply != model_question:
        reply_parts.append(model_reply)
    reply_parts.append(model_question)
    reply = ' '.join(reply_parts)
    state['pendingQuestion'] = reply
    state['readyForGeneration'] = False
    state['generateRequested'] = False
    state['status'] = 'questioning'
    if parsed.get('memory'):
        state['summary'] = str(parsed['memory'])[:40000]
    _visual_plan_site_record_tokens(state, prompt_tokens)
    state['turns'].append({'role': 'assistant', 'text': reply, 'choices': choices})
    return {
        'success': True, 'readyForGeneration': False, 'generateRequested': False,
        'needsClarification': True, 'question': reply, 'choices': choices,
        'reply': reply, 'assistantState': state, 'coverageConflict': facts,
        'contextChanged': bool(previous.get('inputSignature')
                               and previous.get('inputSignature') != signature),
    }
