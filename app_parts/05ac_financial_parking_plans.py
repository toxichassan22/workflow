import financial_parking


def _financial_parking_refresh_context(context, project_data):
    model = financial_parking.parking_object((project_data or {}).get('financial_study_model'))
    plan = financial_parking.parking_object(model.get('parkingPlan'))
    if not plan and not any(row.get('parkingPlanId') for row in financial_parking.parking_model_components(model)):
        return context
    context['components'] = _visual_concept_components(project_data)
    context['parking'] = {
        'planId': plan.get('id'), 'approved': not financial_parking.parking_plan_error(project_data),
        'requiredSpaces': plan.get('requiredSpaces'), 'existingSpaces': plan.get('existingSpaces'),
        'additionalSpaces': plan.get('additionalSpaces'), 'parkingArea': plan.get('parkingArea'),
        'areaPerSpace': plan.get('areaPerSpace'), 'areaIsEstimate': plan.get('areaIsEstimate'),
        'areaBasis': plan.get('areaBasis'), 'footprintArea': plan.get('footprintArea'),
    }
    for target, keys in (
            ('coverage_ratio', ('approved_coverage_ratio', 'coverage_ratio')),
            ('floor_count', ('approved_floor_count', 'max_floors_height', 'table_floors')),
            ('approved_floor_count', ('approved_floor_count',)),
            ('design_area', ('approved_financial_area', 'land_area'))):
        context[target] = _visual_concept_text(_visual_concept_read(project_data, *keys), 120)
    context['regulations'] = _visual_concept_plan_regulation_facts(project_data)
    return context


def _financial_parking_visual_brief(context):
    components = [row for row in context.get('components') or [] if row.get('parkingPlanId')]
    if not components:
        return ''
    labels = {'basement': 'Basement Parking', 'surface': 'Surface Parking', 'aboveGround': 'Above-ground Parking'}
    parts = []
    for row in components:
        parts.append(f"{labels.get(row.get('parkingLocation'), 'Parking')}: "
                     f"{row.get('units')} spaces, {row.get('builtArea')} m² including circulation; "
                     f"floor allocation={row.get('floorRange') or 'recorded distribution'}")
    parking = context.get('parking') or {}
    text = 'PARKING PROGRAM FROM THE FINANCIAL STUDY — ' + '; '.join(parts) + '. '
    if parking.get('approved'):
        text += f"Regulatory demand={parking.get('requiredSpaces')} spaces; existing provision={parking.get('existingSpaces')}; additional provision={parking.get('additionalSpaces')}. "
    if parking.get('areaIsEstimate'):
        text += 'Gross parking area is a concept-planning estimate, not a documented regulatory dimension. '
    return text + 'Keep the exact recorded counts and areas. Surface parking remains outside the building floor stack; basement parking stays below ground. Account for ramps, access and circulation within the recorded parking area; never add parking capacity or floors.'


def _financial_parking_merge_distribution_rows(rows, context):
    components = [row for row in context.get('components') or [] if row.get('parkingPlanId')]
    if not components:
        return rows
    names = {row['name'] for row in components}
    kept = [row for row in rows or [] if isinstance(row, dict) and row.get('component') not in names]
    footprint = (context.get('parking') or {}).get('footprintArea')
    if not footprint:
        area = _visual_concept_number(context.get('design_area') or context.get('land_area')) or 0
        coverage = _visual_concept_number(context.get('coverage_ratio')) or 0
        footprint = area * coverage / 100
    return kept + financial_parking.parking_distribution_rows(components, footprint)


def _financial_parking_distribution_checks(rows, context):
    checks = []
    for component in context.get('components') or []:
        if not component.get('parkingPlanId'):
            continue
        matching = [row for row in rows if _visual_concept_plan_component_key(row.get('component'))
                    == _visual_concept_plan_component_key(component['name'])]
        units, area, invalid = 0, 0, False
        for row in matching:
            parsed = _visual_concept_plan_floor_range(row.get('floor_range'))
            count = parsed['count'] if parsed else 1
            spaces = financial_parking.parking_number(row.get('units_per_floor'))
            floor_area = financial_parking.parking_number(row.get('floor_area_sqm'))
            expected_kind = {'basement': 'basement', 'surface': 'site'}.get(component.get('parkingLocation'))
            wrong_location = not parsed or (expected_kind and parsed['kind'] != expected_kind)
            if component.get('parkingLocation') == 'aboveGround' and parsed and parsed['kind'] in ('basement', 'site'):
                wrong_location = True
            invalid = invalid or wrong_location or spaces is None or not float(spaces or 0).is_integer() or floor_area is None
            units += (spaces or 0) * count
            area += (floor_area or 0) * count
        wanted_units = component.get('units') or 0
        wanted_area = component.get('builtArea') or 0
        if invalid or units != wanted_units or abs(area - wanted_area) > 0.01:
            checks.append({
                'item': 'توزيع المواقف لا يطابق الدراسة المالية',
                'detail': f"«{component['name']}»: المطلوب {wanted_units:g} موقفًا ومساحة {wanted_area:g} م² في الموقع المحدد بالدراسة.",
                'result': 'متعارض', 'severity': 'high', 'fixedFact': True,
                'row_ids': [row.get('id') for row in matching],
            })
    return checks


def _financial_parking_basement_levels(model):
    levels = set()
    for band in model.get('below') or []:
        if isinstance(band, dict):
            floor_range = band.get('range')
        else:
            floor_range = band[2].get('floorRange') if len(band) > 2 else ''
        parsed = _visual_concept_plan_floor_range(floor_range)
        if parsed and parsed['kind'] == 'basement':
            levels.update(range(int(parsed['lo']), int(parsed['hi']) + 1))
        else:
            levels.add(-1)
    return len(levels)
