import copy
import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP

import db
from best_use_geometry import number, parcel_shape_source, setback_envelope


SECTION_KEY = 'section-best-use'
MAP_TOKENS = ('##MAP_OVERVIEW##', '##MAP_ACCESS##', '##MAP_CATCHMENT##', '##MAP_LANDMARKS##')
SUPPORT_USES = {'services', 'parking', 'openArea', 'basement'}
INVESTMENT_MODELS = {'sale', 'dailyRent', 'monthlyRent', 'annualRent', 'operating', 'nonRevenue'}
DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
USE_TERMS = {
    'residential': r'سكني|سكنيه|سكنية|مساكن|شقق|شقة|فيلا|residential|apartment|villa',
    'retail': r'محلات|تجاري|تجارية|معارض|معرض|retail|commercial|showroom',
    'office': r'مكاتب|اداري|إداري|مكتب|office|administrative',
    'entertainment': r'ترفيه|entertainment',
    'hospitality': r'فندقي|فنادق|فندق|منتجعات|مفروشة|مفروش|فندقية|hospitality|hotel|serviced',
    'industrial': r'صناعي|صناعات|ورش|industrial',
    'logistics': r'لوجستي|مستودعات|تخزين|logistics|warehouses',
}
SUPPORT_TERMS = {
    'services': r'خدمات|مرافق|services',
    'parking': r'مواقف|جراجات|parking',
    'openArea': r'مفتوح|مفتوحة|فراغات|تشجير|landscap|open\s*area',
    'basement': r'بدروم|قبو|basement',
}


def canonical_use(value):
    """Map a model-supplied use label to its canonical key — the model often
    answers in Arabic ("سكني", "مواقف") while validations compare keys.
    Unknown labels pass through unchanged so membership checks still reject."""
    label = str(value or '').strip()
    if not label or label in USE_TERMS or label in SUPPORT_TERMS:
        return label
    for key, pattern in list(USE_TERMS.items()) + list(SUPPORT_TERMS.items()):
        if re.search(pattern, label, re.I):
            return key
    return label


def digest(value):
    canonical = json.dumps(db.normalize_generation_input(value), ensure_ascii=False,
                           sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


class ProposalError(ValueError):
    pass


def decoded(value, default):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return copy.deepcopy(default)
    return copy.deepcopy(value) if isinstance(value, (dict, list)) else copy.deepcopy(default)


def read_object(value):
    result = decoded(value, {})
    return result if isinstance(result, dict) else {}


def text(value, limit=6000):
    return str(value or '').strip()[:limit]


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def capacity(project):
    area = number(project.get('approved_financial_area')) or 0
    cadastral = number(project.get('croquis_land_area')) or 0
    area = min(area, cadastral) if cadastral > 0 else area
    coverage = number(project.get('approved_coverage_ratio')) or 0
    floors = number(project.get('approved_floor_count')) or 0
    far = number(project.get('approved_floor_area_ratio')) or 0
    coverage_footprint = area * coverage / 100
    setback, setback_issue = setback_envelope(project)
    setback_base = setback_envelope(project, 'base')[0] if setback is not None else None
    footprint = min(coverage_footprint, setback) if setback is not None else coverage_footprint
    footprint_base = min(coverage_footprint, setback_base) if setback_base is not None else coverage_footprint
    typical = number(project.get('approved_typical_floor_coverage')) or 0
    shape_source = parcel_shape_source(project)
    return {
        'landArea': area, 'coveragePercent': coverage, 'floors': floors, 'far': far,
        'coverageFootprint': coverage_footprint, 'setbackFootprint': setback,
        'setbackFootprintNoSurfaceParking': setback_base,
        'setbackVerified': setback is not None, 'setbackIssue': setback_issue,
        'boundaryShape': shape_source,
        'footprintLimit': footprint,
        'footprintLimitNoSurfaceParking': footprint_base,
        'farLimit': area * far, 'maxBuiltArea': min(area * far, footprint * floors),
        'maxBuiltAreaNoSurfaceParking': min(area * far, footprint_base * floors),
        'typicalFloorCoverage': typical,
        'typicalFloorCap': area * typical / 100 if typical else None,
        'openAreaLimit': max(0, area - coverage_footprint),
        'basementAreaLimit': max(0, area),
        'warnings': [
            'سقف البدروم تخطيطي لطبقة واحدة ضمن مساحة الأرض؛ السماح التنظيمي وغلاف الارتدادات تحت الأرض غير متحققين.'
        ] + (['شكل الأرض تقديري — مستطيل مبني على أطوال الحدود الموثقة وليس على إحداثيات مساحة؛ '
              'الأبعاد المدخلة تقرر الغلاف والتوزيع.'] if shape_source == 'dimensions' else [])
        + ([] if setback is not None else [
            'غلاف الارتدادات غير متحقق هندسيًا من البيانات المتاحة؛ المساحات توصية تخطيطية وليست مخططًا معماريًا.']),
    }


def apply_proposal(project, proposal, state_key='best_use_data'):
    updated = copy.deepcopy(project)
    model = read_object(updated.get('financial_study_model'))
    dynamic = read_object(model.get('dynamicRows'))
    old = dynamic.get('components') if isinstance(dynamic.get('components'), list) else []
    rows = [{key: value for key, value in row.items() if key not in {
        'reason', 'areaReason', 'footprintArea', 'allowedUseBasis', 'grossArea',
        'nonRevenueArea', 'revenueAreaBasis', 'revenuePotential', 'floorAllocations'}}
        for row in proposal['components']]
    old_names = {str(row.get('id')): text(row.get('name')).casefold()
                 for row in old if isinstance(row, dict)}
    new_ids = {text(row.get('name')).casefold(): row['id'] for row in rows}
    unlinked = 0
    for row in dynamic.get('revenue') or []:
        if isinstance(row, dict) and row.get('componentId'):
            linked = new_ids.get(old_names.get(str(row['componentId'])))
            row['componentId'] = linked or ''
            if not linked:
                unlinked += 1
    dynamic['components'] = rows
    model['dynamicRows'] = dynamic
    inputs = read_object(model.get('inputs'))
    inputs['builtUpAreaAbove'] = proposal['totals']['builtArea']
    inputs['basementArea'] = proposal['totals']['basementArea']
    model['inputs'] = inputs
    for key in ('parkingPlan', 'parkingSnapshot', 'projection', 'report'):
        model.pop(key, None)
    tables = read_object(model.get('tables'))
    for key in ('componentsTable', 'cashflowTable', 'debtScheduleTable', 'fundFeeScheduleTable', 'sensitivityTable'):
        tables.pop(key, None)
    if 'tables' in model:
        model['tables'] = tables
    calc = {'components': copy.deepcopy(rows)}
    model['financialCalcData'] = calc
    updated['financial_study_model'] = model
    updated['project_components_data'] = json.dumps(rows, ensure_ascii=False)
    updated['financial_calc_data'] = json.dumps(calc, ensure_ascii=False)
    updated[state_key] = dict(proposal, unlinkedRevenueRows=unlinked)
    return updated
