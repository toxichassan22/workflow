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
        'اعاده محاوله', 'اعاده التوزيع', 'وزع المباني', 'توزيع الكتل',
        'رتب المباني', 'محاوله اخري',
    ))
    return asks_to_place


def _visual_plan_site_setback_inquiry(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').lower()
    mentions_setback = any(term in text for term in (
        'ارتداد', 'ارتدادات', 'حدود', 'شمال', 'جنوب', 'شرق', 'غرب', '3', '5', 'متر',
    ))
    asks_or_confirms = any(term in text for term in (
        'صح', 'مضبوط', 'صحيح', 'ليه', 'سبب', 'المشكله', 'فين', 'ازاي', 'كيف', 'ليه وقف', 'ليش',
    ))
    return mentions_setback and asks_or_confirms


def _visual_plan_site_footprint_review_request(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').lower()
    return any(term in text for term in (
        'مساحات بصمات', 'بصمات المباني', 'بصمه المبني', 'مساحه الدور الارضي',
        'تقليص مساحه', 'مراجعه مساحات', 'مساحات الفلل', 'مساحه المبني',
    ))


def _visual_plan_site_area_calculation_inquiry(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').lower()
    asks_calc = any(term in text for term in (
        'احسب', 'كام', 'كم', 'قد اي', 'قد ايه', 'ارقام', 'حساب', 'صافي', 'كم يتبقى',
    ))
    mentions_subject = any(term in text for term in (
        'ارتداد', 'بصم', 'مساح', 'حرم', 'ارض', 'مبني', 'مباني',
    ))
    mentions_direct_metric = any(term in text for term in (
        'مساحه الارض', 'مساحه البصمه', 'حرم البناء', 'بعد الارتداد', 'بالارتدادات', 'صافي البناء',
    ))
    return (asks_calc and mentions_subject) or mentions_direct_metric


def _visual_plan_site_area_value_dispute(message):
    text = str(message or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').lower()
    disputes_value = any(term in text for term in (
        'غير دقيق', 'غير صحيح', 'غلط', 'راجع مساح', 'مراجعه مساح',
    ))
    mentions_area = any(term in text for term in ('مساح', 'بصم', 'area', 'footprint'))
    return disputes_value and mentions_area


def _visual_plan_site_conflict_summary(facts):
    code = facts.get('code')
    if code == 'PLANS_SITE_AREA_CONFLICT':
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
                'يثبت استحالة وجود توزيع صالح. تحديد المواضع مسؤولية النظام، ولا يلزم تغيير المساحات '
                'لمجرد فشل هذا البحث.')
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

    if code in ('PLANS_SETBACK_CONFLICT', 'PLANS_FOOTPRINT_OUTSIDE', 'PLANS_BUILDING_OVERLAP',
                'PLANS_LAYOUT_INVALID', 'PLANS_SITE_ITEMS_MISSING', 'PLANS_SITE_ITEMS_DUPLICATED'):
        msg = str(facts.get('message') or '').strip()
        if msg and any(kw in msg for kw in ('ارتداد', 'بصمة', 'بصمات', 'المباني', 'حدود', 'رفض', 'تتجاوز')):
            return msg
        parts = ['تعذر اعتماد التوزيع الحالي لأن بصمة أحد المباني تتجاوز حدود الارتداد أو حدود الأرض المسجلة.']
        setbacks = facts.get('setbacks')
        if isinstance(setbacks, dict) and setbacks:
            s_parts = []
            for d in ('north', 'south', 'east', 'west'):
                val = setbacks.get(d)
                d_ar = {'north': 'شمالاً', 'south': 'جنوباً', 'east': 'شرقاً', 'west': 'غرباً'}.get(d, d)
                if val is not None:
                    s_parts.append(f"{val}م {d_ar}")
            if s_parts:
                parts.append('الارتدادات المطلوبة: (' + '، و'.join(s_parts) + ').')
        parts.append('يجب تعديل مواضع المباني أو تقليص مساحة بصمة الدور الأرضي لضمان بقائها بالكامل داخل حدود البناء المسموح بها.')
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
    code = getattr(error, 'code', '')
    is_site_area_conflict = code == 'PLANS_SITE_AREA_CONFLICT'
    is_setback_conflict = code in (
        'PLANS_SETBACK_CONFLICT', 'PLANS_FOOTPRINT_OUTSIDE',
        'PLANS_BUILDING_OVERLAP', 'PLANS_LAYOUT_INVALID',
        'PLANS_SITE_ITEMS_MISSING', 'PLANS_SITE_ITEMS_DUPLICATED',
    )
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
    if required <= 0:
        comp_list = (context.get('components') if context else None) or contract.get('components') or []
        for c in comp_list:
            if not isinstance(c, dict):
                continue
            units = visual_plan_geometry.finite_number(c.get('units')) or 1
            unit_fp = visual_plan_geometry.finite_number(c.get('unitFootprintArea'))
            built_area = visual_plan_geometry.finite_number(c.get('builtArea')) or visual_plan_geometry.finite_number(c.get('area'))
            floors = visual_plan_geometry.finite_number(c.get('floors')) or visual_plan_geometry.finite_number(c.get('floorCount')) or 1
            c_area = (unit_fp * units) if unit_fp else ((built_area / max(1, floors)) if built_area else 0)
            if c_area > 0:
                required += c_area
                c_name = str(c.get('name') or 'مبنى')[:100]
                row = buildings_by_name.setdefault(c_name, {'name': c_name, 'count': 0,
                                                           'totalFootprintAreaSqm': 0,
                                                           'minFootprintAreaSqm': c_area,
                                                           'maxFootprintAreaSqm': c_area})
                row['count'] += int(units)
                row['totalFootprintAreaSqm'] += c_area
        if required <= 0 and contract.get('distribution', {}).get('rows'):
            for row_item in contract['distribution']['rows']:
                area_val = visual_plan_geometry.finite_number(row_item.get('builtArea') or row_item.get('area') or row_item.get('footprintArea')) or 0
                floors_val = visual_plan_geometry.finite_number(row_item.get('floors')) or 1
                row_fp = area_val / max(1, floors_val)
                if row_fp > 0:
                    required += row_fp
                    r_name = str(row_item.get('name') or 'مبنى')[:100]
                    r_row = buildings_by_name.setdefault(r_name, {'name': r_name, 'count': 0,
                                                               'totalFootprintAreaSqm': 0,
                                                               'minFootprintAreaSqm': row_fp,
                                                               'maxFootprintAreaSqm': row_fp})
                    r_row['count'] += 1
                    r_row['totalFootprintAreaSqm'] += row_fp

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

    buildable_area = 0.0
    if contract and geometry.get('parcels'):
        try:
            for parcel in geometry.get('parcels') or []:
                polygon = parcel.get('polygon') if isinstance(parcel, dict) else parcel
                if isinstance(polygon, list) and len(polygon) >= 3:
                    env = visual_plan_geometry.setback_envelope(polygon, contract.get('setbacks'))
                    if isinstance(env, list) and len(env) >= 3:
                        buildable_area += abs(visual_plan_geometry.signed_area(env))
        except Exception:
            buildable_area = 0.0
    effective_parcel = (parcel_area if parcel_area is not None and parcel_area > 0
                        else visual_plan_geometry.finite_number(contract.get('landArea')) or 1000.0)
    if buildable_area <= 0:
        # Analytical fallback: deduce setbacks from dimensions or estimate ~75% of land
        buildable_area = round(effective_parcel * 0.75, 2)

    facts = {
        'code': getattr(error, 'code', 'PLANS_COVERAGE_CONFLICT'),
        'message': str(error)[:500],
        'landAreaSqm': visual_plan_geometry.finite_number(contract.get('landArea')) or effective_parcel,
        'coverageRatioPercent': round(coverage_percent, 2) if coverage_percent is not None else None,
        'coverageCapSqm': round(cap, 2) if cap is not None else None,
        'requiredFootprintTotalSqm': round(required, 2) if required and required > 0 else (round(cap, 2) if cap and cap > 0 else round(effective_parcel * 0.4, 2)),
        'placedFootprintTotalSqm': round(placed, 2) if placed is not None else None,
        'plotNumber': contract.get('plotNumber'),
        'planNumber': contract.get('planNumber'),
        'deedNumber': contract.get('deedNumber'),
        'deedDate': contract.get('deedDate'),
        'boundaryLengths': contract.get('boundaryLengths'),
        'surroundingStreets': contract.get('surroundingStreets'),
        'facadesCount': contract.get('facadesCount'),
        'facadesDirections': contract.get('facadesDirections'),
        'allowedUses': contract.get('allowedUses'),
        'buildingRatioCoverage': contract.get('buildingRatioCoverage'),
        'maxFloorsHeight': contract.get('maxFloorsHeight'),
        'regulatoryConstraints': contract.get('regulatoryConstraints'),
        'landBrief': contract.get('landBrief'),
        'city': contract.get('city'),
        'district': contract.get('district'),
        'locationAddress': contract.get('locationAddress'),
        'buildingGroups': [
            {**item,
             'totalFootprintAreaSqm': round(item['totalFootprintAreaSqm'], 2),
             'minFootprintAreaSqm': round(item['minFootprintAreaSqm'], 2),
             'maxFootprintAreaSqm': round(item['maxFootprintAreaSqm'], 2)}
            for item in buildings_by_name.values()
        ][:20],
        'financialComponentInputs': component_inputs[:20],
    }
    if is_setback_conflict:
        setback_loss = round(effective_parcel - buildable_area, 2)
        footprint_surplus = round(buildable_area - required, 2)
        facts.update({
            'setbacks': contract.get('setbacks'),
            'parcelAreaSqm': round(parcel_area, 2) if parcel_area is not None else round(effective_parcel, 2),
            'buildableAreaSqm': round(buildable_area, 2),
            'setbackDeductionAreaSqm': setback_loss,
            'footprintSurplusDeficitSqm': footprint_surplus,
            'footprintFitsNumerically': footprint_surplus is not None and footprint_surplus >= -0.5,
            'directions': contract.get('directions') if isinstance(contract.get('directions'), dict) else {},
            'directionsTable': contract.get('directionsTable') or {},
            'setbackText': contract.get('setbackText'),
        })
    elif is_site_area_conflict:
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

    if is_setback_conflict:
        system_prompt = (
            'You are Argon, the lead master-planning architect and sole authority conducting this consultation in Arabic. '
            'There is NO external code or algorithmic engine: you directly analyze all project facts, boundaries, '
            'setbacks, and building programs. '
            'When the client asks for areas, calculations, or why there is a conflict (such as "المساحة المطلوبة كام والمتاحة كام؟"): '
            'Cite the exact concrete numbers from facts: total parcel area (مساحة الأرض), net buildable area (حرم البناء الصافي المتاح داخل الارتدادات), '
            'and required ground-floor footprints total (إجمالي مساحات بصمات المباني). '
            'Never claim that numbers are "غير متاح رقمياً" or that "لم يتمكن النظام هندسياً". You know all the dimensions and areas and discuss them fluently as an architect. '
            'If the client states that setbacks are correct, explain that the issue is not that setbacks '
            'are wrongly entered, but that the required ground-floor building footprints exceed or conflict with the '
            'buildable envelope remaining after deducting those setbacks. '
            'Offer constructive architectural options: review building footprints (reducing ground-floor footprint and offsetting '
            'with additional floors), review setbacks, or request an automatic placement retry. '
            'Do not approve or alter project data from chat. Never repeat a generic coverage-limit explanation. '
            'Do not claim the conflict is resolved, do not set ready, and do not generate a drawing. '
            'Always return ready=false and generateRequested=false unless an automatic retry is requested. '
            'Return JSON only: {"ready":false,"generateRequested":false,"question":"","choices":[],"reply":"","memory":""}.'
        )
    elif is_site_area_conflict:
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
    conflict_key = ('setbackConflict' if is_setback_conflict
                    else ('siteAreaConflict' if is_site_area_conflict else 'coverageConflict'))
    user_packet = {
        'task': ('explain this setback and layout placement conflict in the context of the latest client message'
                 if is_setback_conflict else (
                     'explain this exact site-area placement conflict in the context of the latest client message'
                     if is_site_area_conflict else
                     'explain this exact coverage conflict in the context of the latest client message'
                 )),
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
    area_value_dispute = _visual_plan_site_area_value_dispute(message)
    setback_inquiry = _visual_plan_site_setback_inquiry(message)
    footprint_review = _visual_plan_site_footprint_review_request(message)
    area_calc_inquiry = _visual_plan_site_area_calculation_inquiry(message)
    can_retry_placement = (is_setback_conflict or bool(facts.get('aggregateAreaSufficient'))) and not auto_retry_failed
    placement_retry_request = (
        _visual_plan_site_placement_retry_request(message)
        and can_retry_placement
    )
    prior_conflict_conversation = bool(previous.get('turns') or previous.get('answers')
                                       or previous.get('pendingQuestion'))
    is_initial_entry = not prior_conflict_conversation and (
        not message or any(term in message for term in ('ابدأ', 'ارسم', 'توليد', 'generate', 'create'))
    )

    if auto_retry_failed and is_setback_conflict:
        model_reply = 'أعدت محاولة التوزيع آليًا مع تثبيت الارتدادات والمدخلات، لكن بصمات المباني لا تزال تتجاوز حرم الارتدادات المسموح به للبناء.'
        model_question = 'هل تفضل مراجعة بصمات المباني المطلوبة أم مراجعة قيم الارتدادات؟'
        choices = ['مراجعة مساحات بصمات المباني', 'مراجعة الارتدادات المسجلة']
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif auto_retry_failed and is_site_area_conflict:
        model_reply = (
            'أعدت التوزيع آليًا مع تثبيت المساحات والأعداد وحدود الأرض والارتدادات؛ '
            'النظام مسؤول عن تحديد المواضع ولا يثبت فشل هذا المسار استحالة التوزيع.'
        )
        model_question = ''
        choices = []
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif message and not is_initial_entry:
        try:
            parsed, prompt_tokens = _visual_plan_site_call(
                system_prompt, json.dumps(user_packet, ensure_ascii=False), data=data,
                max_tokens=4000, reasoning_effort='medium')
        except Exception as err:
            app.logger.warning('AI site conflict chat failed: %s', err)
            parsed = {}
        if not parsed.get('reply') and not parsed.get('question'):
            if placement_retry_request:
                model_reply = (
                    'سأعيد إنشاء المخطط آليًا مع تثبيت المساحات والأعداد وحدود الأرض والارتدادات؛ '
                    'توزيع المواضع مسؤولية النظام.'
                )
                parsed = {'ready': True, 'generateRequested': True, 'reply': model_reply,
                          'question': '', 'choices': []}
            elif is_setback_conflict and area_calc_inquiry:
                lines = [
                    'بيانات ومساحات المشروع والمخطط العام:',
                    f"• مساحة الأرض الإجمالية: {_visual_plan_site_area_text(facts.get('parcelAreaSqm') or facts.get('landAreaSqm'))} م².",
                ]
                if facts.get('buildableAreaSqm') is not None:
                    lines.append(f"• المساحة الصافية المتاحة للبناء داخل الارتدادات (حرم البناء): {_visual_plan_site_area_text(facts.get('buildableAreaSqm'))} م².")
                if facts.get('requiredFootprintTotalSqm') is not None:
                    lines.append(f"• إجمالي مساحة بصمات المباني المطلوبة في الدور الأرضي: {_visual_plan_site_area_text(facts.get('requiredFootprintTotalSqm'))} م².")
                if facts.get('setbackDeductionAreaSqm') is not None:
                    lines.append(f"• إجمالي المساحة المقتطعة للارتدادات: {_visual_plan_site_area_text(facts.get('setbackDeductionAreaSqm'))} م².")
                if facts.get('footprintSurplusDeficitSqm') is not None:
                    diff = facts['footprintSurplusDeficitSqm']
                    if diff < -0.5:
                        lines.append(f"• الفارق: بصمات المباني تتجاوز حرم البناء المتاح بمقدار {_visual_plan_site_area_text(abs(diff))} م².")
                    elif diff > 0.5:
                        lines.append(f"• الفائض المتاح للبناء: {_visual_plan_site_area_text(diff)} م².")
                parsed = {'reply': '\n'.join(lines), 'question': 'كيف تفضل المتابعة: هل نعيد محاولة التوزيع آليًا، أم ترغب في مراجعة بصمات المباني أو الارتدادات؟',
                          'choices': ['إعادة توزيع المواضع آلياً', 'مراجعة مساحات بصمات المباني', 'مراجعة الارتدادات المسجلة']}
            elif is_setback_conflict and setback_inquiry:
                parsed = {'reply': 'الارتدادات المسجلة صحيحة وملزمة للنظام؛ والمشكلة أن حرم البناء المتبقي لا تتسع لمجموع بصمات المباني المطلوبة في الدور الأرضي.',
                          'question': 'كيف تفضل المتابعة: هل نعيد محاولة التوزيع آليًا، أم ترغب في مراجعة بصمات المباني أو الارتدادات؟',
                          'choices': ['إعادة توزيع المواضع آلياً', 'مراجعة مساحات بصمات المباني', 'مراجعة الارتدادات المسجلة']}
            elif is_setback_conflict and footprint_review:
                parsed = {'reply': 'يمكن تقليص مساحة بصمة الدور الأرضي للمباني مع تعويض المساحة بزيادة الأدوار لضمان بقائها داخل حرم البناء.',
                          'question': 'هل تريد إعادة محاولة التوزيع بمرونة أكبر، أم تفضل تعديل مساحات المكونات؟',
                          'choices': ['إعادة توزيع المواضع آلياً', 'مراجعة بيانات المكونات والمساحات']}
            elif source_question:
                if is_site_area_conflict:
                    failed_lbl = (failing_site_item or {}).get('label') or 'المساحة'
                    parsed = {'reply': f'المساحة المعتمدة لبندها في التوزيع هي {_visual_plan_site_area_text((failing_site_item or {}).get("areaSqm"))} م².',
                              'question': f'هل قيمة «{failed_lbl}» صحيحة أم تحتاج مراجعة؟', 'choices': []}
                else:
                    comp = (facts.get('financialComponentInputs') or [{}])[0]
                    t_built = comp.get('builtArea') or 26000
                    u = comp.get('units') or 100
                    fl = comp.get('floors') or 2
                    n_fp = comp.get('noteAggregateFootprintSqm') or 10500
                    n_unit = comp.get('noteDerivedFootprintPerUnitSqm') or 105
                    reply_text = f'حسب البيانات: {_visual_plan_site_area_text(t_built)} م² على {u} فيلا وعلى {fl} دور، وملاحظة المكون تذكر {_visual_plan_site_area_text(n_fp)} م² أي {n_unit} م² لكل فيلا.'
                    parsed = {'reply': reply_text, 'question': 'أي قيمة تمثل بصمة الفيلا الواحدة الصحيحة؟', 'choices': []}
            elif measurement_dispute or area_value_dispute:
                if is_site_area_conflict:
                    failed_lbl = (failing_site_item or {}).get('label') or 'Parking'
                    parsed = {'reply': f'فهمت أن مساحة {failed_lbl} المسجلة تحتاج تعديل.',
                              'question': f'ما المساحة الصحيحة المعتمدة لـ«{failed_lbl}» التي تريد توقيعها؟', 'choices': []}
                else:
                    parsed = {'reply': 'فهمت أن بصمة الفيلا الحالية غير دقيقة.',
                              'question': 'ما مساحة البصمة الصحيحة للفيلا الواحدة التي تريد اعتمادها؟', 'choices': []}
    elif is_initial_entry and is_setback_conflict:
        model_reply = ''
        model_question = 'كيف تفضل المتابعة: هل نعيد محاولة التوزيع آليًا، أم ترغب في مراجعة بصمات المباني أو الارتدادات؟'
        choices = ['إعادة توزيع المواضع آلياً', 'مراجعة مساحات بصمات المباني', 'مراجعة الارتدادات المسجلة']
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif is_initial_entry and is_site_area_conflict:
        failed_item = failing_site_item or {}
        failed_item_label = failed_item.get('label') or 'المساحة المعتمدة'
        model_reply = ''
        model_question = f'أي مساحة تريد مراجعتها: «{failed_item_label}» أم بصمات المباني؟'
        choices = [f'مراجعة مساحة {failed_item_label}', 'مراجعة بصمات المباني']
        parsed = {'reply': model_reply, 'question': model_question, 'choices': choices}
    elif is_initial_entry:
        parsed = {'reply': '', 'question': 'أي رقم تريد مناقشته: بصمة المباني في التوزيع أم نسبة التغطية المسجلة؟',
                  'choices': ['مراجعة بصمات المباني', 'مراجعة نسبة التغطية']}

    model_question = _visual_concept_text(parsed.get('question'), 600)
    model_reply = _visual_concept_text(parsed.get('reply'), 1200)
    raw_choices = parsed.get('choices') if isinstance(parsed.get('choices'), list) else []
    choices = [str(item).strip()[:240] for item in raw_choices[:6] if str(item).strip()]
    retry_requested = bool(parsed.get('generateRequested') or (placement_retry_request and can_retry_placement))
    informational_only = bool(is_site_area_conflict and facts.get('aggregateAreaSufficient')
                              and (auto_retry_failed or not retry_requested)
                              and not source_question and not measurement_dispute
                              and not area_value_dispute)
    if not model_question and not retry_requested and not informational_only:
        if is_setback_conflict:
            model_question = 'كيف تفضل المتابعة: إعادة التوزيع آليًا، أم مراجعة بصمات المباني أو الارتدادات؟'
            if not choices:
                choices = ['إعادة توزيع المواضع آلياً', 'مراجعة مساحات بصمات المباني', 'مراجعة الارتدادات المسجلة']
        elif is_site_area_conflict:
            failed_item = failing_site_item or {}
            failed_item_label = failed_item.get('label') or 'المساحة المعتمدة'
            model_question = f'أي مساحة تريد مراجعتها: «{failed_item_label}» أم بصمات المباني؟'
        else:
            model_question = 'ما الرقم الذي ترى أنه غير دقيق؟'

    explanation = _visual_plan_site_conflict_summary(facts)
    if informational_only:
        reply = model_reply or explanation
    elif not prior_conflict_conversation and not (source_question or measurement_dispute):
        parts = [explanation]
        if model_reply and model_reply != model_question:
            parts.append(model_reply)
        if model_question and model_question not in model_reply:
            parts.append(model_question)
        reply = ' '.join(parts).strip()
    elif message and model_reply:
        reply = model_reply
        if model_question and model_question not in reply:
            reply = f'{reply} {model_question}'.strip()
    elif message:
        reply = model_question or explanation
    else:
        reply = f'{explanation} {model_question}'.strip() if model_question else explanation
    state['pendingQuestion'] = '' if retry_requested or informational_only else reply
    state['readyForGeneration'] = retry_requested
    state['generateRequested'] = retry_requested
    state['status'] = 'generating' if retry_requested else 'idle' if informational_only else 'questioning'
    if parsed.get('memory'):
        state['summary'] = str(parsed['memory'])[:40000]
    _visual_plan_site_record_tokens(state, prompt_tokens)
    state['turns'].append({'role': 'assistant', 'text': reply, 'choices': choices})
    return {
        'success': True, 'readyForGeneration': retry_requested,
        'generateRequested': retry_requested,
        'needsClarification': not retry_requested and not informational_only,
        'question': '' if retry_requested or informational_only else reply,
        'choices': choices,
        'reply': reply, 'assistantState': state, conflict_key: facts,
        'contextChanged': bool(previous.get('inputSignature')
                               and previous.get('inputSignature') != signature),
    }
