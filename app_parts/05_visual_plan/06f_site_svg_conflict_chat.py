def _visual_plan_site_area_text(value):
    number = visual_plan_geometry.finite_number(value)
    return f'{number:,.2f}'.rstrip('0').rstrip('.') if number is not None else ''


def _visual_plan_site_note_aggregate_footprint(notes):
    text = str(notes or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').lower()
    patterns = (
        r'(?:اجمال\w*|مجموع)\D{0,32}(?:بصم\w*|footprint)\D{0,32}([\d][\d,٬]*(?:[.٫][\d]+)?)',
        r'(?:بصم\w*|footprint)\D{0,32}(?:اجمال\w*|مجموع)\D{0,32}([\d][\d,٬]*(?:[.٫][\d]+)?)',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return visual_plan_geometry.finite_number(match.group(1).replace(',', '').replace('٬', '').replace('٫', '.'))
    return None


def _visual_plan_site_measurement_dispute(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').lower()
    disputes = ('غير دقيق', 'غير صحيح', 'غير مضبوط', 'غلط', 'incorrect', 'inaccurate', 'wrong')
    return ('بصم' in text or 'footprint' in text) and any(item in text for item in disputes)


def _visual_plan_site_footprint_source_question(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').lower()
    asks_source = any(item in text for item in ('منين', 'مصدر', 'جبت', 'حسبت', 'ازاي', 'كيف', 'where', 'how'))
    mentions_area = any(item in text for item in ('بصم', 'مساح', 'footprint', 'area'))
    return asks_source and mentions_area


def _visual_plan_site_placement_retry_request(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').lower()
    asks_to_place = any(term in text for term in (
        'مناقشه توزيع', 'اعاده توزيع', 'توزيع parking', 'وزع parking',
        'توزيع المواضع', 'توزيع المساحات', 'يوزعها على الارض',
        'النظام يوزع', 'وزعها على الارض', 'رتب الموقع',
    ))
    return asks_to_place


def _visual_plan_site_conflict_summary(facts):
    if facts.get('code') == 'PLANS_SITE_AREA_CONFLICT':
        failed_item = facts.get('failingSiteItem') or {}
        failed_label = str(failed_item.get('label') or failed_item.get('name') or 'المساحة المعتمدة')
        failed_area = visual_plan_geometry.finite_number(failed_item.get('areaSqm'))
        occupied = facts.get('requiredFootprintTotalSqm')
        parcel_area = facts.get('parcelAreaSqm') or facts.get('landAreaSqm')
        parts = [f'فشل البحث الهندسي الحالي في إيجاد موضع لـ«{failed_label}» مع التوزيع الذي جرّبه.']
        available = visual_plan_geometry.finite_number(facts.get('availableAreaBeforeFailingSqm'))
        surplus = visual_plan_geometry.finite_number(facts.get('aggregateAreaSurplusSqm'))
        if facts.get('aggregateAreaSufficient') and available is not None and surplus is not None:
            parts.append(
                f'حسابيًا، يتبقى بعد البصمات والعناصر الأخرى {_visual_plan_site_area_text(available)} م²، '
                f'مقابل {_visual_plan_site_area_text(failed_area)} م² لـ«{failed_label}»، '
                f'أي فائض {_visual_plan_site_area_text(surplus)} م².')
            parts.append(
                'إذًا لا يظهر عجز في مجموع المساحات. مسار التوزيع الاحتياطي يختبر أكثر من ترتيب للمباني '
                'وعناصر الموقع، لكنه لا يستكشف كل الأشكال والمواضع الهندسية الممكنة؛ لذلك فشل البحث لا '
                'يثبت استحالة وجود توزيع صالح.')
        else:
            if failed_area is not None:
                parts.append(f'مساحة «{failed_label}» المسجلة {_visual_plan_site_area_text(failed_area)} م².')
            if available is not None:
                parts.append(f'المتاح حسابيًا قبل هذه المساحة {_visual_plan_site_area_text(available)} م².')
            parts.append('نحتاج مراجعة المساحات أو إعادة توزيع المواضع قبل اعتبار ذلك عجزًا هندسيًا مؤكدًا.')
        if occupied is not None:
            parts.append(f'إجمالي بصمات المباني المسجلة {_visual_plan_site_area_text(occupied)} م².')
        if parcel_area is not None:
            parts.append(f'مساحة حدود الإحداثيات المستخدمة في الفحص {_visual_plan_site_area_text(parcel_area)} م².')
        land_area = visual_plan_geometry.finite_number(facts.get('landAreaSqm'))
        if (parcel_area is not None and land_area is not None
                and abs(parcel_area - land_area) > 0.5):
            parts.append(
                f'مساحة الأرض المسجلة {_visual_plan_site_area_text(land_area)} م²؛ '
                f'يوجد فرق {_visual_plan_site_area_text(abs(parcel_area - land_area))} م² عن مساحة الحدود.')
        return ' '.join(parts)

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


def _visual_plan_site_conflict_interview(data, error, auto_retry_failed=False):
    is_site_area_conflict = getattr(error, 'code', '') == 'PLANS_SITE_AREA_CONFLICT'
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

    component_inputs = []
    if context:
        for component in context.get('components') or []:
            if not _visual_plan_is_individual_home(component.get('name')):
                continue
            units = visual_plan_geometry.finite_number(component.get('units'))
            unit_footprint = visual_plan_geometry.finite_number(component.get('unitFootprintArea'))
            notes = str(component.get('notes') or '')[:300]
            aggregate_note = _visual_plan_site_note_aggregate_footprint(notes)
            note_unit_footprint = (aggregate_note / units if aggregate_note is not None
                                   and units is not None and units > 0 else None)
            component_keys = _visual_plan_component_name_keys(component.get('name'))
            program_buildings = [item for item in source_buildings.values()
                                 if component_keys.intersection(
                                     _visual_plan_component_name_keys(item.get('name')))]
            program_footprints = [visual_plan_geometry.finite_number(item.get('footprintArea'))
                                  for item in program_buildings]
            program_footprints = [value for value in program_footprints if value is not None and value > 0]
            component_inputs.append({
                'name': str(component.get('name') or '')[:100],
                'units': units,
                'unitAreaSqm': visual_plan_geometry.finite_number(component.get('unitArea')),
                'builtAreaSqm': visual_plan_geometry.finite_number(component.get('builtArea')),
                'unitFootprintAreaSqm': unit_footprint,
                'derivedFootprintPerUnitSqm': program_footprints[0] if program_footprints else None,
                'levels': visual_plan_geometry.finite_number(
                    program_buildings[0].get('levels')) if program_buildings else None,
                'notes': notes,
                'noteAggregateFootprintSqm': aggregate_note,
                'noteDerivedFootprintPerUnitSqm': round(note_unit_footprint, 2)
                if note_unit_footprint is not None else None,
            })

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
    site_items = []
    for item in program.get('siteItems', []):
        if not isinstance(item, dict):
            continue
        area = visual_plan_geometry.finite_number(item.get('area'))
        site_items.append({
            'id': str(item.get('id') or '')[:120],
            'label': str(item.get('label') or item.get('name') or item.get('id') or 'مساحة موقع')[:120],
            'name': str(item.get('name') or '')[:120],
            'siteType': str(item.get('siteType') or '')[:40],
            'areaSqm': area,
        })
    failed_label_match = re.search(r'«([^»]{1,120})»', str(error))
    failed_label = failed_label_match.group(1) if failed_label_match else ''
    failing_site_item = next((item for item in site_items
                              if failed_label and failed_label.casefold() in
                              (item['label'] + ' ' + item['name']).casefold()), None)
    if failing_site_item is None and site_items:
        failing_site_item = max(site_items, key=lambda item: item.get('areaSqm') or 0)
    geometry = contract.get('geometry') if isinstance(contract.get('geometry'), dict) else {}
    parcel_area = 0
    for parcel in geometry.get('parcels') or []:
        polygon = parcel.get('polygon') if isinstance(parcel, dict) else parcel
        if isinstance(polygon, list) and len(polygon) >= 3:
            try:
                parcel_area += abs(visual_plan_geometry.signed_area(polygon))
            except (IndexError, TypeError, ValueError):
                continue
    if parcel_area <= 0:
        parcel_area = visual_plan_geometry.finite_number(contract.get('landArea'))

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
        'financialComponentInputs': component_inputs[:20],
    }
    if is_site_area_conflict:
        failing_site_area = (visual_plan_geometry.finite_number(failing_site_item.get('areaSqm'))
                             if isinstance(failing_site_item, dict) else None)
        other_site_area = sum(
            item.get('areaSqm') or 0 for item in site_items
            if not failing_site_item or item.get('id') != failing_site_item.get('id'))
        available_area_before_failing = (parcel_area - required - other_site_area
                                         if parcel_area is not None else None)
        area_surplus = (available_area_before_failing - failing_site_area
                        if available_area_before_failing is not None
                        and failing_site_area is not None else None)
        facts.update({
            'requiredSiteItems': site_items[:20],
            'requiredSiteAreaTotalSqm': round(sum(item.get('areaSqm') or 0 for item in site_items), 2),
            'failingSiteItem': failing_site_item,
            'parcelAreaSqm': round(parcel_area, 2) if parcel_area is not None else None,
            'otherSiteAreaTotalSqm': round(other_site_area, 2),
            'availableAreaBeforeFailingSqm': (round(available_area_before_failing, 2)
                                              if available_area_before_failing is not None else None),
            'aggregateAreaSurplusSqm': round(area_surplus, 2) if area_surplus is not None else None,
            'aggregateAreaSufficient': area_surplus is not None and area_surplus >= -0.5,
            'placementSearchExhaustive': False,
        })
    state = _visual_plan_site_state(data, signature)
    message = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if message:
        if state['pendingQuestion']:
            state['answers'].append({'question': state['pendingQuestion'], 'answer': message})
            state['answers'] = state['answers'][-100:]
        state['turns'].append({'role': 'user', 'text': message})

    if is_site_area_conflict:
        system_prompt = (
            'You are the site-planning assistant continuing a client conversation in Arabic. '
            'The automatic placement search did not find a placement for the approved site area. '
            'The client supplies the approved building and site-area program; the system is responsible '
            'for placing those items on the land. Never ask the client to arrange or position buildings, '
            'parking, or other site elements. Only the approved areas, surveyed parcel, setbacks and '
            'project requirements may be used. Use only the supplied facts and '
            'conversation history. If aggregateAreaSufficient is true, explicitly say that the total area '
            'arithmetic is sufficient by the supplied surplus and that this search failure does not prove '
            'a valid arrangement is impossible. Do not claim the remaining spaces are fragmented unless '
            'the supplied scene geometry proves it. If the client asks the system to distribute the items, '
            'request an automatic retry with all inputs fixed; do not ask where anything should go. '
            'When totals are insufficient or the retry still fails, ask only whether a recorded area or '
            'project input needs review. Do not change or '
            'approve any project input, survey geometry, or approved distribution. Never repeat a generic '
            'coverage-limit explanation. Do not claim the conflict is resolved, do not set ready, and do not '
            'generate a drawing. Always return ready=false and generateRequested=false. Return JSON only: '
            '{"ready":false,"generateRequested":false,'
            '"question":"","choices":[],"reply":"","memory":""}.'
        )
    else:
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
            'Financial component notes and the per-unit footprint field are client-provided facts; '
            'read them when the client disputes a building footprint, and ask for a precise replacement when '
            'the correct value is not explicit. Never repeat the full conflict summary after a client reply. '
            'Do not claim the conflict is resolved, do not set ready, and do not generate a drawing. '
            'Always return ready=false and '
            'generateRequested=false. '
            'Return JSON only: {"ready":false,"generateRequested":false,"question":"",'
            '"choices":[],"reply":"","memory":""}.'
        )
    conflict_key = 'siteAreaConflict' if is_site_area_conflict else 'coverageConflict'
    user_packet = {
        'task': ('explain this exact site-area placement conflict in the context of the latest client message'
                 if is_site_area_conflict else
                 'explain this exact coverage conflict in the context of the latest client message'),
        conflict_key: facts,
        'resolvedAnswers': state['answers'][-8:],
        'sessionMemory': state['summary'],
        'recentTurns': state['turns'][-8:],
        'latestClientMessage': message,
    }
    parsed = {}
    prompt_tokens = 0
    source_question = _visual_plan_site_footprint_source_question(message)
    measurement_dispute = _visual_plan_site_measurement_dispute(message)
    placement_retry_request = (_visual_plan_site_placement_retry_request(message)
                               and facts.get('aggregateAreaSufficient') and not auto_retry_failed)
    prior_conflict_conversation = bool(previous.get('turns') or previous.get('answers')
                                       or previous.get('pendingQuestion'))
    if placement_retry_request:
        model_reply = (
            'سأعيد إنشاء المخطط آليًا مع تثبيت المساحات والأعداد وحدود الأرض والارتدادات؛ '
            'توزيع المواضع مسؤولية النظام.'
        )
        parsed = {'ready': True, 'generateRequested': True, 'reply': model_reply,
                  'question': '', 'choices': []}
    elif auto_retry_failed and is_site_area_conflict:
        model_reply = (
            'أعدت التوزيع آليًا مع تثبيت المدخلات، لكن المحاولات لم تنتج مشهدًا يجتاز فحوص حدود الأرض '
            'والارتدادات والتداخل. كفاية مجموع المساحات لا تثبت وحدها إمكان ترتيب كل الأشكال هندسيًا. '
            'النظام مسؤول عن تحديد المواضع؛ لا يلزمك اقتراحها.'
        )
        model_question = 'هل توجد مساحة معتمدة أو معلومة في المشروع تريد مراجعتها؟'
        parsed = {'reply': model_reply, 'question': model_question,
                  'choices': ['مراجعة مساحات العناصر المعتمدة']}
    elif is_site_area_conflict and not prior_conflict_conversation:
        failed_item = failing_site_item or {}
        failed_item_label = failed_item.get('label') or 'المساحة المعتمدة'
        if facts.get('aggregateAreaSufficient'):
            model_reply = (
                'مجموع المساحات المسجل يكفي حسابيًا، لكن محاولات النظام لم تجد موضعًا صالحًا يجتاز '
                'فحوص الكروكي والارتدادات وعدم التداخل. هذا لا يثبت استحالة التوزيع. '
                'النظام مسؤول عن توزيع المباني والعناصر على الأرض.'
            )
            model_question = 'هل توجد مساحة معتمدة أو معلومة في المشروع تريد مراجعتها؟'
            choices = ['مراجعة مساحات العناصر المعتمدة']
        else:
            model_reply = (
                'الحساب الإجمالي للمساحات يحتاج مراجعة قيمة أو أكثر قبل أن يحدد النظام توزيعًا صالحًا. '
                'تحديد مواضع المباني والعناصر مسؤولية النظام.'
            )
            model_question = 'أي مساحة معتمدة تريد مراجعتها؟'
            choices = [f'مراجعة مساحة {failed_item_label}', 'مراجعة بصمات المباني']
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif (is_site_area_conflict and facts.get('aggregateAreaSufficient')
          and any(term in message for term in ('المتبقي', 'المساحة المتبقية', 'قد اي', 'كم يتبقى', 'كم المساحة'))):
        available = facts.get('availableAreaBeforeFailingSqm')
        failed_item = failing_site_item or {}
        failed_item_label = failed_item.get('label') or 'المساحة المعتمدة'
        failed_item_area = failed_item.get('areaSqm')
        surplus = facts.get('aggregateAreaSurplusSqm')
        model_reply = (
            f'بحسب مساحة حدود الإحداثيات المستخدمة في الفحص، المتبقي بعد المباني وبقية العناصر '
            f'{_visual_plan_site_area_text(available)} م²؛ وبعد خصم «{failed_item_label}» '
            f'({_visual_plan_site_area_text(failed_item_area)} م²) يبقى فائض '
            f'{_visual_plan_site_area_text(surplus)} م². هذا يثبت كفاية المجموع حسابيًا، لا نجاح البحث '
            'الهندسي المحدود في إيجاد موضع.'
        )
        land_area = facts.get('landAreaSqm')
        parcel_area = facts.get('parcelAreaSqm')
        if land_area is not None and parcel_area is not None and abs(parcel_area - land_area) > 0.5:
            model_reply += (
                f' مساحة الأرض المسجلة {_visual_plan_site_area_text(land_area)} م²، '
                f'ومساحة الحدود المحسوبة {_visual_plan_site_area_text(parcel_area)} م²؛ '
                f'الفرق {_visual_plan_site_area_text(abs(parcel_area - land_area))} م².'
            )
        model_question = 'هل توجد مساحة معتمدة تريد مراجعتها؟'
        choices = ['مراجعة مساحة Parking']
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif (is_site_area_conflict and facts.get('aggregateAreaSufficient')
          and any(term in message for term in ('مناقشة توزيع', 'توزيع parking', 'إعادة ترتيب', 'اعادة ترتيب'))):
        available = facts.get('availableAreaBeforeFailingSqm')
        surplus = facts.get('aggregateAreaSurplusSqm')
        model_reply = (
            f'الأرقام لا تُظهر عجزًا في المساحة: يتبقى حسابيًا {_visual_plan_site_area_text(available)} م² '
            f'مقابل المساحة المعتمدة، مع فائض {_visual_plan_site_area_text(surplus)} م². '
            'محاولات النظام لم تجد ترتيبًا يجتاز الفحوص الهندسية، لكن ذلك لا يثبت استحالة توزيع المواقف. '
            'النظام مسؤول عن تحديد المواضع مع إبقاء المساحات المسجلة.'
        )
        model_question = 'هل توجد مساحة معتمدة تريد مراجعتها؟'
        choices = []
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif is_site_area_conflict and source_question:
        failed_item = failing_site_item or {}
        failed_item_label = failed_item.get('label') or 'المساحة المعتمدة'
        failed_item_area = failed_item.get('areaSqm')
        if failed_item_area is not None:
            model_reply = (f"مساحة «{failed_item_label}» مأخوذة من المساحة المعتمدة لبندها في التوزيع، "
                           f"والمسجل {_visual_plan_site_area_text(failed_item_area)} م².")
            model_question = f'هل قيمة «{failed_item_label}» صحيحة، أم تريد تحديد مساحة أخرى؟'
            choices = [f'القيمة صحيحة: {_visual_plan_site_area_text(failed_item_area)} م²',
                       'سأحدد مساحة أخرى']
        else:
            model_reply = f'لم أجد قيمة مساحة مسجلة لبند «{failed_item_label}» في بيانات التوزيع.'
            model_question = f'ما المساحة الصحيحة المعتمدة لـ«{failed_item_label}» بالمتر المربع؟'
            choices = []
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif is_site_area_conflict and any(term in message for term in ('غير دقيق', 'غير دقيقة', 'غير صحيح',
                                                                    'غير صحيحة', 'غلط', 'راجع مساحة',
                                                                    'مراجعة مساحة')):
        failed_item = failing_site_item or {}
        failed_item_label = failed_item.get('label') or 'المساحة المعتمدة'
        parsed = {
            'reply': f'فهمت أن مساحة «{failed_item_label}» تحتاج مراجعة. لن أغيّر القيمة المعتمدة من المحادثة.',
            'question': f'ما المساحة الصحيحة المعتمدة لـ«{failed_item_label}» بالمتر المربع؟',
            'choices': [],
        }
    elif source_question:
        component = next((item for item in component_inputs
                          if item.get('derivedFootprintPerUnitSqm') is not None
                          or item.get('noteDerivedFootprintPerUnitSqm') is not None), None)
        if component and component.get('unitFootprintAreaSqm') is not None:
            candidate = component['unitFootprintAreaSqm']
            model_reply = (f"مساحة بصمة الوحدة جاءت من الحقل المسجل في مكونات الدراسة المالية: "
                           f"{_visual_plan_site_area_text(candidate)} م² لكل وحدة.")
        elif component and component.get('derivedFootprintPerUnitSqm') is not None:
            candidate = component['derivedFootprintPerUnitSqm']
            levels = component.get('levels') or 1
            model_reply = (
                f"قيمة {_visual_plan_site_area_text(candidate)} م² لكل فيلا حُسبت من قسمة المساحة المبنية "
                f"{_visual_plan_site_area_text(component.get('builtAreaSqm'))} م² على "
                f"{_visual_plan_site_area_text(component.get('units'))} فيلا وعلى "
                f"{_visual_plan_site_area_text(levels)} دور.")
        else:
            candidate = None
            model_reply = 'لم أجد في بيانات المكونات قيمة كافية لتحديد مصدر مساحة بصمة الفيلا.'
        note_candidate = component.get('noteDerivedFootprintPerUnitSqm') if component else None
        if note_candidate is not None:
            model_reply += (
                f" وتذكر ملاحظة المكونات إجمالي بصمة "
                f"{_visual_plan_site_area_text(component['noteAggregateFootprintSqm'])} م²، "
                f"أي {_visual_plan_site_area_text(note_candidate)} م² لكل فيلا.")
            model_question = 'أي قيمة تمثل بصمة الفيلا الواحدة الصحيحة؟'
            choices = [f"{_visual_plan_site_area_text(note_candidate)} م² حسب الملاحظة",
                       'سأحدد مساحة أخرى']
        elif candidate is not None:
            model_question = 'هل المساحة المبنية وعدد الأدوار المسجلان صحيحان؟'
            choices = []
        else:
            model_question = 'ما مساحة البصمة الصحيحة للفيلا الواحدة بالمتر المربع؟'
            choices = []
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif measurement_dispute:
        component = next((item for item in component_inputs
                          if item.get('unitFootprintAreaSqm') is not None
                          or item.get('noteDerivedFootprintPerUnitSqm') is not None), None)
        candidate = None
        source_text = ''
        if component and component.get('unitFootprintAreaSqm') is not None:
            candidate = component['unitFootprintAreaSqm']
            source_text = f"حقل بصمة الوحدة يسجل {_visual_plan_site_area_text(candidate)} م²"
        elif component and component.get('noteDerivedFootprintPerUnitSqm') is not None:
            candidate = component['noteDerivedFootprintPerUnitSqm']
            source_text = (
                f"الملاحظة تسجل إجمالي بصمة {_visual_plan_site_area_text(component['noteAggregateFootprintSqm'])} م² "
                f"لعدد {_visual_plan_site_area_text(component['units'])} فيلا"
            )
        if candidate is not None and candidate > 0:
            model_reply = (f"فهمت أن مساحة بصمة الفيلا غير دقيقة. {source_text}، "
                           f"وهذا يساوي {_visual_plan_site_area_text(candidate)} م² لكل فيلا.")
            model_question = (f"هل تؤكد أن مساحة البصمة الصحيحة هي "
                              f"{_visual_plan_site_area_text(candidate)} م² لكل فيلا؟")
            choices = [f"نعم، {_visual_plan_site_area_text(candidate)} م² لكل فيلا",
                       'لا، سأحدد مساحة أخرى']
        else:
            model_reply = 'فهمت أن مساحة بصمة الفيلا غير دقيقة، ولم أجد قيمة مؤكدة للبصمة في بيانات المكونات.'
            model_question = 'ما مساحة البصمة الصحيحة للفيلا الواحدة بالمتر المربع؟'
            choices = []
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    else:
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
    retry_requested = bool(parsed.get('generateRequested') and placement_retry_request)
    if not model_question and not retry_requested:
        if is_site_area_conflict:
            failed_item = failing_site_item or {}
            failed_item_label = failed_item.get('label') or 'المساحة المعتمدة'
            model_question = (f'أي مساحة تريد مراجعتها: «{failed_item_label}» أم بصمات المباني؟'
                              if message else
                              f'أي مساحة معتمدة تريد مراجعتها: «{failed_item_label}» أم بصمات المباني؟')
        else:
            model_question = ('ما الرقم الذي ترى أنه غير دقيق؟' if message else
                              'أي رقم تريد مناقشته: بصمة المباني في التوزيع أم نسبة التغطية المسجلة؟')
    explanation = _visual_plan_site_conflict_summary(facts)
    has_prior_conversation = prior_conflict_conversation
    reply_parts = [explanation] if not has_prior_conversation and not (
        source_question or measurement_dispute) else []
    if model_reply and model_reply != model_question:
        reply_parts.append(model_reply)
    reply_parts.append(model_question)
    reply = ' '.join(reply_parts)
    state['pendingQuestion'] = '' if retry_requested else reply
    state['readyForGeneration'] = retry_requested
    state['generateRequested'] = retry_requested
    state['status'] = 'generating' if retry_requested else 'questioning'
    if parsed.get('memory'):
        state['summary'] = str(parsed['memory'])[:40000]
    _visual_plan_site_record_tokens(state, prompt_tokens)
    state['turns'].append({'role': 'assistant', 'text': reply, 'choices': choices})
    return {
        'success': True, 'readyForGeneration': retry_requested,
        'generateRequested': retry_requested,
        'needsClarification': not retry_requested, 'question': '' if retry_requested else reply,
        'choices': choices,
        'reply': reply, 'assistantState': state, conflict_key: facts,
        'contextChanged': bool(previous.get('inputSignature')
                               and previous.get('inputSignature') != signature),
    }
