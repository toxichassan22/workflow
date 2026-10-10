import copy
import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal, ROUND_CEILING


PARKING_PLANNING_AREA_PER_SPACE = 30
PARKING_LOCATIONS = ('basement', 'surface', 'aboveGround')
NON_PARKING_DEMAND_USES = {'parking', 'basement', 'openArea', 'services'}
PARKING_LOCATION_LABELS = {
    'basement': 'البدروم', 'surface': 'سطحية', 'aboveGround': 'فوق الأرض',
}


def parking_object(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value) if isinstance(value, str) else None
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parking_number(value):
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789'))
    text = re.sub(r'[\s,٬،]', '', text).replace('٫', '.')
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def is_parking_component(row):
    return row.get('useType') == 'parking' or (
        row.get('useType') in {'basement', 'openArea'} and bool(re.search(
            r'مواقف|جراج|باركينج|\bparking\b|\bgarage\b', str(row.get('name') or ''), re.I)))


def parking_area_pool(row):
    if is_parking_component(row):
        location = row.get('parkingLocation')
        if location in PARKING_LOCATIONS:
            return location
    return {'basement': 'basement', 'openArea': 'surface'}.get(row.get('useType'), 'aboveGround')


def parking_model_components(model):
    rows = parking_object(parking_object(model).get('dynamicRows')).get('components')
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def parking_snapshot(project):
    project = parking_object(project)
    model = parking_object(project.get('financial_study_model'))
    inputs = parking_object(model.get('inputs'))
    plan = parking_object(model.get('parkingPlan'))
    rows = parking_model_components(model)
    basement = parking_number(inputs.get('basementArea')) or 0
    if any(row.get('parkingPlanId') for row in rows) and basement in (
            plan.get('basementAreaTarget'), plan.get('previousBasementAreaTarget')):
        basement = parking_number(plan.get('baseBasementArea')) or 0
    components = []
    for row in rows:
        if row.get('parkingPlanId'):
            continue
        component = {key: str(row.get(key) or '').strip() for key in (
            'id', 'name', 'useType', 'investmentModel', 'parkingLocation')}
        component.update({key: parking_number(row.get(key)) for key in (
            'units', 'unitArea', 'builtArea', 'revenueArea')})
        components.append(component)
    analysis = parking_object(project.get('land_documents_analysis'))
    parcels = analysis.get('parcels') if isinstance(analysis.get('parcels'), list) else []
    analysis_texts = []
    for holder in [analysis, *parcels]:
        if isinstance(holder, dict):
            for key in ('parking_requirements', 'regulatory_constraints'):
                text = str(holder.get(key) or '').strip()
                if text and text not in analysis_texts:
                    analysis_texts.append(text)
    return {
        'landArea': parking_number(project.get('approved_financial_area', inputs.get('landArea'))),
        'croquisArea': parking_number(project.get('croquis_land_area')),
        'coverageRate': parking_number(project.get('approved_coverage_ratio', inputs.get('coverageRate'))),
        'floorCount': parking_number(project.get('approved_floor_count', inputs.get('floorCount'))),
        'builtUpAreaAbove': parking_number(inputs.get('builtUpAreaAbove')),
        'basementArea': basement,
        'city': str(project.get('city') or '').strip(),
        'zoningCode': str(project.get('zoning_code') or '').strip(),
        'regulatoryConstraints': str(project.get('regulatory_constraints') or '').strip(),
        'parkingRequirements': str(project.get('parking_requirements') or '').strip(),
        'analysisParkingRequirements': '\n'.join(analysis_texts),
        'components': sorted(components, key=lambda row: row['id']),
    }


def parking_snapshot_hash(snapshot):
    return hashlib.sha256(json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def _quote_text(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))
    text = re.sub(r'[\u064b-\u065f\u0670]', '', text).replace('ـ', '')
    return re.sub(r'\s+', ' ', text).strip()


def _source_quote(quote, source_texts):
    normalized = _quote_text(quote)
    return bool(normalized) and len(normalized) >= 8 and any(
        normalized in _quote_text(text) for text in source_texts)


def _number_in_quote(number, quote):
    normalized = _quote_text(quote).replace('٬', '').replace('٫', '.')
    normalized = re.sub(r'(?:م|m)\s*[23]\b', '', normalized)
    values = [parking_number(value) for value in re.findall(r'\d+(?:\.\d+)?', normalized)]
    if number in values:
        return True
    if number == 1:
        return bool(re.search(r'\bموقف(?:ا)?\b|لكل\s+(?:وحدة|غرفة|شقة|فيلا)|one|per\s+(?:unit|room)', normalized))
    return number == 2 and bool(re.search(r'موقفان|موقفين|اثنان|اثنين|غرفتين|وحدتين|two', normalized))


def _rule_spaces(rule, component, snapshot, source_texts):
    quote = str(rule.get('sourceQuote') or '').strip()
    basis = rule.get('basis')
    spaces, per = parking_number(rule.get('spaces')), parking_number(rule.get('per'))
    fixed = parking_number(rule.get('fixedSpaces', 0))
    threshold = parking_number(rule.get('threshold', 0))
    if not _source_quote(quote, source_texts) or basis not in {'units', 'builtArea', 'revenueArea', 'landArea'}:
        return None
    if spaces is None or per is None or not 0 < spaces <= 1000 or not 0 < per <= 10000000:
        return None
    if fixed is None or threshold is None or not _number_in_quote(spaces, quote) or not _number_in_quote(per, quote):
        return None
    if fixed and not _number_in_quote(fixed, quote) or threshold and not _number_in_quote(threshold, quote):
        return None
    normalized = _quote_text(quote)
    area_word = bool(re.search(r'م\s*2|متر|مساحة|sqm|square|\bm2\b|area', normalized))
    if basis == 'units' and (area_word or not re.search(r'وحد|غرف|شقق|شقة|فيل|unit|room|dwelling|apartment', normalized)):
        return None
    if basis != 'units' and not area_word:
        return None
    if basis == 'landArea' and not re.search(r'أرض|ارض|land|plot', normalized):
        return None
    if basis == 'revenueArea' and not re.search(r'بيعي|تأجير|تاجير|saleable|leasable|lettable', normalized):
        return None
    quantity = snapshot['landArea'] if basis == 'landArea' else component.get(basis)
    if quantity is None or quantity <= 0 or basis == 'units' and not float(quantity).is_integer():
        return None
    value = Decimal(str(fixed)) + max(Decimal(0), Decimal(str(quantity)) - Decimal(str(threshold))) * Decimal(str(spaces)) / Decimal(str(per))
    count = int(value.to_integral_value(rounding=ROUND_CEILING))
    visitor_percent = parking_number(rule.get('visitorPercent', 0))
    visitor_quote = str(rule.get('visitorSourceQuote') or '').strip()
    if visitor_percent is None or visitor_percent > 100:
        return None
    if visitor_percent:
        if not _source_quote(visitor_quote, source_texts) or not _number_in_quote(visitor_percent, visitor_quote):
            return None
        count += int((Decimal(count) * Decimal(str(visitor_percent)) / 100).to_integral_value(rounding=ROUND_CEILING))
    if count > 1000000:
        return None
    return {'spaces': count, 'basis': basis, 'quantity': quantity, 'spacesPer': spaces,
            'per': per, 'fixedSpaces': fixed, 'threshold': threshold,
            'sourceQuote': quote, 'visitorPercent': visitor_percent, 'visitorSourceQuote': visitor_quote}


def _plan_allocations(snapshot, response, required, area_per_space, source_texts, plan_id):
    rows = snapshot['components']
    used = {location: 0 for location in PARKING_LOCATIONS}
    existing = 0
    for row in rows:
        used[parking_area_pool(row)] += row.get('builtArea') or 0
        if is_parking_component(row):
            units = row.get('units')
            if units is not None and float(units).is_integer():
                existing += int(units)
    additional = max(0, required - existing)
    land = snapshot['landArea'] or 0
    site = snapshot['croquisArea'] or land
    coverage = snapshot['coverageRate']
    footprint = min(land, site) * coverage / 100 if coverage is not None and 0 < coverage <= 100 else 0
    available = {
        'basement': max(0, snapshot['basementArea'] - used['basement']),
        'surface': max(0, min(land, site) - footprint - used['surface']) if footprint else 0,
        'aboveGround': max(0, min(footprint, (snapshot['builtUpAreaAbove'] or 0) - used['aboveGround'])),
    }
    basement_allowed = response.get('basementAllowed')
    basement_quote = str(response.get('basementSourceQuote') or '').strip()
    basement_words = r'بدروم|قبو|أقبية|اقبية|basement'
    if not isinstance(basement_allowed, bool) or not _source_quote(basement_quote, source_texts) or not re.search(basement_words, _quote_text(basement_quote)):
        basement_allowed = None
    ban = r'(?:لا\s*(?:يسمح|يجوز)|ممنوع|غير\s*مسموح|not\s*(?:allowed|permitted)|prohibited)[^.؛\n]{0,60}(?:' + basement_words + ')'
    if any(re.search(ban, _quote_text(text)) for text in source_texts):
        basement_allowed = False
    max_levels = parking_number(response.get('maxBasementLevels'))
    if max_levels is not None and (not max_levels.is_integer() or not _source_quote(basement_quote, source_texts)
                                   or not re.search(basement_words, _quote_text(basement_quote))
                                   or not _number_in_quote(max_levels, basement_quote)):
        max_levels = None
    if max_levels is not None and footprint:
        available['basement'] = max(0, min(snapshot['basementArea'], max_levels * footprint) - used['basement'])
    preferred = response.get('preferredLocation')
    order = [preferred] if preferred in PARKING_LOCATIONS else []
    order += [location for location in PARKING_LOCATIONS if location not in order]
    allocations = {location: 0 for location in PARKING_LOCATIONS}
    remaining = additional
    for location in order:
        if location == 'basement' and basement_allowed is False:
            continue
        capacity = max(0, math.floor(available[location] / area_per_space))
        take = min(remaining, capacity)
        allocations[location] += take
        remaining -= take
    basement_target = snapshot['basementArea']
    warnings = []
    if remaining and footprint >= area_per_space and basement_allowed is not False:
        target = max(basement_target, used['basement'] + (allocations['basement'] + remaining) * area_per_space)
        levels = math.ceil(target / footprint)
        if levels <= (max_levels if max_levels is not None else 20):
            allocations['basement'] += remaining
            basement_target = target
            remaining = 0
            warnings.append('مساحة بدروم إضافية مقترحة ضمن الدراسة المالية.')
            if basement_allowed is None:
                warnings.append('إمكانية إنشاء البدروم الإضافي غير موثقة في الاشتراطات المتاحة.')
    if remaining:
        warnings.append('المساحة المتاحة لا تستوعب جميع المواقف المطلوبة.')
    if not footprint:
        warnings.append('مساحة الأرض أو نسبة التغطية اللازمة لتوزيع المواقف غير متوفرة.')
    components = []
    for location, count in allocations.items():
        if not count:
            continue
        levels = max(1, math.ceil(count / max(1, math.floor(footprint / area_per_space)))) if location == 'basement' else 1
        floor_range = ('بدروم 1' + (f'-{levels}' if levels > 1 else '') if location == 'basement'
                       else 'مساحة مفتوحة' if location == 'surface' else 'أرضي')
        components.append({
            'id': f'parking_regulatory_{location}',
            'name': 'مواقف السيارات — ' + PARKING_LOCATION_LABELS[location],
            'useType': 'parking', 'parkingLocation': location,
            'units': count, 'unitArea': area_per_space, 'builtArea': round(count * area_per_space, 2),
            'revenueArea': 0, 'investmentModel': 'nonRevenue',
            'parkingPlanId': plan_id, 'floorRange': floor_range,
        })
    return {'existingSpaces': existing, 'additionalSpaces': additional,
            'unallocatedSpaces': remaining, 'components': components,
            'baseBasementArea': snapshot['basementArea'], 'basementAreaTarget': round(basement_target, 2),
            'footprintArea': round(footprint, 2), 'warnings': warnings}


def build_parking_plan(project, response, plan_id):
    response = parking_object(response)
    snapshot = parking_snapshot(project)
    source_texts = [snapshot[key] for key in (
        'regulatoryConstraints', 'parkingRequirements', 'analysisParkingRequirements') if snapshot[key]]
    facts = parking_object(parking_object(project).get('parking_regulation_facts'))
    source_texts += [str(facts[key]) for key in ('parking_requirements', 'regulatory_constraints', 'zone_rules') if facts.get(key)]
    rules = response.get('rules') if isinstance(response.get('rules'), list) else []
    requirements, missing = [], []
    demand = [row for row in snapshot['components']
              if row['useType'] not in NON_PARKING_DEMAND_USES and not is_parking_component(row)]
    for component in demand:
        selected = [rule for rule in rules if isinstance(rule, dict) and rule.get('componentId') == component['id']]
        calculated = [_rule_spaces(rule, component, snapshot, source_texts) for rule in selected]
        valid = bool(calculated) and all(item is not None for item in calculated)
        if not valid:
            missing.append('اشتراط المواقف أو أساس حسابه غير موثق للمكون: ' + (component['name'] or component['id']))
        combined = (sum(item['spaces'] for item in calculated)
                    if valid and all(rule.get('combination') == 'sum' for rule in selected)
                    else max((item['spaces'] for item in calculated), default=0) if valid else None)
        first = calculated[0] if valid else {}
        requirements.append({'componentId': component['id'], 'name': component['name'],
                             'spaces': combined, 'quantity': first.get('quantity'),
                             'basis': first.get('basis'), 'rules': calculated if valid else [],
                             'sourceQuote': '\n'.join(item['sourceQuote'] for item in calculated) if valid else ''})
    if not demand:
        missing.append('مكونات المشروع التي تتطلب مواقف غير متوفرة.')
    documented_area = parking_number(response.get('grossAreaPerSpace'))
    area_quote = str(response.get('grossAreaSourceQuote') or '').strip()
    area_documented = (documented_area is not None and 5 <= documented_area <= 200
                       and _source_quote(area_quote, source_texts) and _number_in_quote(documented_area, area_quote)
                       and bool(re.search(r'حركة|ممر|إجمالي|اجمالي|gross|circulation', _quote_text(area_quote))))
    area_per_space = documented_area if area_documented else PARKING_PLANNING_AREA_PER_SPACE
    required = sum(item['spaces'] or 0 for item in requirements)
    plan = {'id': plan_id, 'approved': False, 'sourceSnapshot': snapshot,
            'sourceHash': parking_snapshot_hash(snapshot), 'requirements': requirements,
            'missing': missing, 'requiredSpaces': required if not missing else None,
            'areaPerSpace': area_per_space, 'areaIsEstimate': not area_documented,
            'areaSourceQuote': area_quote if area_documented else '',
            'areaBasis': ('مساحة الموقف شاملة الحركة وفق الاشتراط الموثق.' if area_documented
                          else 'تقدير تخطيطي: 30 م² لكل موقف شاملة الحركة والخدمات، وليس اشتراطًا تنظيميًا.')}
    allocations = _plan_allocations(snapshot, response, required if not missing else 0,
                                    area_per_space, source_texts, plan_id)
    plan.update(allocations)
    plan['parkingArea'] = round(sum(row['builtArea'] for row in plan['components']), 2)
    plan['canApply'] = not missing and not plan['unallocatedSpaces'] and (snapshot['landArea'] or 0) > 0
    if missing:
        plan['components'] = []
    return plan


def remove_parking_plan(model):
    model = copy.deepcopy(parking_object(model))
    plan = parking_object(model.get('parkingPlan'))
    inputs = model.setdefault('inputs', {})
    if parking_number(inputs.get('basementArea')) in (plan.get('basementAreaTarget'), plan.get('previousBasementAreaTarget')):
        inputs['basementArea'] = plan.get('baseBasementArea', inputs.get('basementArea'))
    dynamic = model.setdefault('dynamicRows', {})
    dynamic['components'] = [row for row in parking_model_components(model) if not row.get('parkingPlanId')]
    if isinstance(model.get('financialCalcData'), dict):
        model['financialCalcData']['components'] = copy.deepcopy(dynamic['components'])
    model.pop('parkingPlan', None)
    model.pop('parkingSnapshot', None)
    return model


def apply_parking_plan(model, plan):
    model = remove_parking_plan(model)
    model['dynamicRows']['components'].extend(copy.deepcopy(plan.get('components') or []))
    model['inputs']['basementArea'] = plan['basementAreaTarget']
    model['parkingPlan'] = copy.deepcopy(plan)
    if isinstance(model.get('financialCalcData'), dict):
        model['financialCalcData']['components'] = copy.deepcopy(model['dynamicRows']['components'])
    return model


def parking_plan_error(project):
    model = parking_object(parking_object(project).get('financial_study_model'))
    plan = parking_object(model.get('parkingPlan'))
    actual = [row for row in parking_model_components(model) if row.get('parkingPlanId')]
    if not plan:
        return 'PARKING_APPROVAL_REQUIRED' if actual else None
    if plan.get('approved') is not True or not plan.get('canApply'):
        return 'PARKING_APPROVAL_REQUIRED'
    if parking_snapshot_hash(parking_snapshot(project)) != plan.get('sourceHash'):
        return 'PARKING_INPUTS_CHANGED'
    keys = ('id', 'name', 'useType', 'units', 'unitArea', 'builtArea', 'revenueArea',
            'investmentModel', 'parkingLocation', 'parkingPlanId', 'floorRange')
    normalized = lambda rows: sorted(
        [{key: row.get(key) for key in keys} for row in rows], key=lambda row: str(row['id']))
    if normalized(actual) != normalized(plan.get('components') or []):
        return 'PARKING_COMPONENTS_CHANGED'
    return None


def parking_distribution_rows(components, footprint_area):
    rows = []
    for component in components:
        if not component.get('parkingPlanId'):
            continue
        spaces = int(parking_number(component.get('units')) or 0)
        area_per_space = parking_number(component.get('unitArea')) or PARKING_PLANNING_AREA_PER_SPACE
        location = component.get('parkingLocation')
        capacity = max(1, math.floor((parking_number(footprint_area) or 0) / area_per_space)) if location == 'basement' else spaces
        level = 1
        while spaces > 0:
            take = min(spaces, capacity)
            rows.append({'building': 'الموقع العام' if location == 'surface' else 'المبنى الرئيسي',
                         'floor_range': f'بدروم {level}' if location == 'basement' else 'مساحة مفتوحة' if location == 'surface' else 'أرضي',
                         'component': component['name'], 'units_per_floor': take,
                         'floor_area_sqm': round(take * area_per_space, 2),
                         'circulation': 'المساحة تشمل الحركة والخدمات.'})
            spaces -= take
            level += 1
    return rows
