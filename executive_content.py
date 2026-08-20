"""Executive-content section: facts from earlier sections, AI wording only."""

from __future__ import annotations

import json


BLOCKS = (
    {
        'key': 'brief',
        'label': 'نبذة المشروع',
        'requires': ('basic', 'idea'),
        'output': 'paragraphs',
    },
    {
        'key': 'opportunity',
        'label': 'الفرصة الاستثمارية',
        'requires': ('basic', 'location', 'land', 'financial', 'market'),
        'output': 'paragraphs',
    },
    {
        'key': 'features',
        'label': 'المميزات وفرص الاستثمار',
        'requires': ('basic', 'location', 'market'),
        'output': 'bullets',
    },
    {
        'key': 'risks',
        'label': 'دراسة المخاطر',
        'requires': ('basic', 'location', 'land', 'financial', 'market'),
        'output': 'bullets',
    },
    {
        'key': 'summary',
        'label': 'الملخص التنفيذي',
        'requires': ('basic', 'location', 'land', 'timeline', 'financial', 'market'),
        'output': 'document',
    },
)

BLOCK_KEYS = tuple(item['key'] for item in BLOCKS)
MISSING_FACTS = 'غير متوفر من المدخلات المعتمدة'
SUMMARY_HEADINGS = (
    'البيانات الأساسية',
    'الموقع',
    'الأرض والاشتراطات',
    'الجدول الزمني',
    'الدراسة المالية',
    'فريق العمل',
    'دراسة السوق',
    'الخلاصة',
)


def empty_block(_key):
    return ''


def empty_state():
    return {key: empty_block(key) for key in BLOCK_KEYS}


def normalize_text(value):
    return ' '.join(str(value or '').replace('\r\n', '\n').split())


def normalize_document(value):
    text = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.split('\n')]
    compact = []
    blank = 0
    for line in lines:
        if line.strip():
            compact.append(line)
            blank = 0
            continue
        if blank < 1:
            compact.append('')
        blank += 1
    return '\n'.join(compact).strip()


def _list_value(value):
    if isinstance(value, list):
        return [normalize_text(item) for item in value if normalize_text(item)]
    if isinstance(value, dict):
        return [normalize_text(item) for item in value.values() if normalize_text(item)]
    text = normalize_text(value)
    if not text:
        return []
    if text.startswith('[') or text.startswith('{'):
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            return _list_value(parsed)
    return [part.strip() for part in text.replace('،', ',').split(',') if part.strip()]


def _join(value):
    items = _list_value(value)
    return '، '.join(items) if items else ''


def _compact_mapping(value, limit=12):
    if not isinstance(value, dict):
        return {}
    compact = {}
    for key, item in list(value.items())[:limit]:
        if isinstance(item, (dict, list)):
            compact[key] = item
        else:
            text = normalize_text(item)
            if text:
                compact[key] = text
    return compact


def _compact_items(value, keys=None, limit=12):
    if not isinstance(value, list):
        return []
    items = []
    for raw in value[:limit]:
        if isinstance(raw, dict):
            source = raw if keys is None else {key: raw.get(key) for key in keys}
            item = {}
            for key, val in source.items():
                if isinstance(val, (dict, list)):
                    continue
                text = normalize_text(val)
                if text:
                    item[str(key)] = text
            if item:
                items.append(item)
            continue
        text = normalize_text(raw)
        if text:
            items.append(text)
    return items


def _block_text(value):
    if isinstance(value, dict):
        return ''
    return normalize_document(value)


def compact_facts(facts):
    data = facts if isinstance(facts, dict) else {}
    generated = data.get('generatedBlocks') if isinstance(data.get('generatedBlocks'), dict) else {}
    generated_blocks = {}
    for key in ('brief', 'opportunity', 'features', 'risks'):
        text = _block_text(generated.get(key))
        if text:
            generated_blocks[key] = text
    return {
        'projectName': normalize_text(data.get('projectName')),
        'projectType': _join(data.get('projectType')),
        'projectSubtype': _join(data.get('projectSubtype')),
        'activityClass': normalize_text(data.get('activityClass')),
        'projectLevel': normalize_text(data.get('projectLevel')),
        'projectStage': normalize_text(data.get('projectStage')),
        'projectIdea': normalize_text(data.get('projectIdea')),
        'targetAudience': _join(data.get('targetAudience')),
        'city': normalize_text(data.get('city')),
        'district': normalize_text(data.get('district')),
        'locationAddress': normalize_text(data.get('locationAddress')),
        'locationDetail': normalize_text(data.get('locationDetail')),
        'mainRoads': normalize_text(data.get('mainRoads')),
        'secondaryRoads': normalize_text(data.get('secondaryRoads')),
        'nearbyLandmarks': normalize_text(data.get('nearbyLandmarks')),
        'cityLandmarks': normalize_text(data.get('cityLandmarks')),
        'catchmentAreas': normalize_text(data.get('catchmentAreas')),
        'siteAnalysis': normalize_text(data.get('siteAnalysis')),
        'plotNumber': normalize_text(data.get('plotNumber')),
        'planNumber': normalize_text(data.get('planNumber')),
        'deedNumber': normalize_text(data.get('deedNumber')),
        'deedDate': normalize_text(data.get('deedDate')),
        'croquisLandArea': normalize_text(data.get('croquisLandArea')),
        'approvedFinancialArea': normalize_text(data.get('approvedFinancialArea')),
        'boundaryLengths': normalize_text(data.get('boundaryLengths')),
        'surroundingStreets': normalize_text(data.get('surroundingStreets')),
        'facadesCount': normalize_text(data.get('facadesCount')),
        'facadesDirections': normalize_text(data.get('facadesDirections')),
        'buildingRatioCoverage': normalize_text(data.get('buildingRatioCoverage')),
        'setbacks': normalize_text(data.get('setbacks')),
        'maxFloorsHeight': normalize_text(data.get('maxFloorsHeight')),
        'approvedFloorCount': normalize_text(data.get('approvedFloorCount')),
        'approvedCoverageRatio': normalize_text(data.get('approvedCoverageRatio')),
        'allowedUses': normalize_text(data.get('allowedUses')),
        'landUseStatus': normalize_text(data.get('landUseStatus')),
        'regulatoryConstraints': normalize_text(data.get('regulatoryConstraints')),
        'landSummary': normalize_text(data.get('landSummary')),
        'timelineStartYear': normalize_text(data.get('timelineStartYear')),
        'timelineYears': normalize_text(data.get('timelineYears')),
        'timelineStages': _compact_items(
            data.get('timelineStages'),
            ('name', 'year', 'quarter', 'duration', 'end', 'notes'),
        ),
        'components': _compact_items(
            data.get('components'),
            ('name', 'useType', 'units', 'builtArea', 'revenueArea'),
        ),
        'financialIndicators': _compact_mapping(data.get('financialIndicators'), limit=24),
        'team': _compact_items(data.get('team'), ('name', 'role', 'brief', 'experienceYears', 'notableProjects')),
        'marketSummary': _compact_mapping(data.get('marketSummary')),
        'marketSwot': _compact_mapping(data.get('marketSwot')),
        'marketDecision': normalize_text(data.get('marketDecision')),
        'marketDisclaimer': normalize_text(data.get('marketDisclaimer')),
        'competitors': _compact_items(
            data.get('competitors'),
            ('name', 'projectType', 'status', 'price', 'operationType'),
        ),
        'generatedBlocks': generated_blocks,
    }


def readiness_from_facts(facts):
    data = compact_facts(facts)
    has_name = bool(data['projectName'])
    has_type = bool(data['projectType'])
    has_idea = bool(data['projectIdea'])
    has_location = bool(
        data['city'] or data['district'] or data['locationDetail']
        or data['siteAnalysis'] or data['mainRoads'] or data['locationAddress']
    )
    has_land = bool(
        data['croquisLandArea'] or data['approvedFinancialArea'] or data['allowedUses']
        or data['landSummary'] or data['buildingRatioCoverage'] or data['plotNumber']
    )
    has_timeline = bool(data['timelineStartYear'] or data['timelineYears'] or data['timelineStages'])
    has_financial = bool(data['financialIndicators'] or data['components'])
    has_market = bool(data['marketSummary'] or data['marketDecision'] or data['marketSwot'])
    groups = {
        'basic': has_name and has_type,
        'idea': has_idea,
        'location': has_location,
        'land': has_land,
        'timeline': has_timeline,
        'financial': has_financial,
        'market': has_market,
    }
    return {
        **groups,
        'blocks': {
            item['key']: all(groups.get(name, False) for name in item['requires'])
            for item in BLOCKS
        },
    }


def normalize_block(key, value):
    spec = block_spec(key) or {}
    if spec.get('output') == 'document':
        if isinstance(value, list):
            return normalize_document(_sections_to_text(value))
        return normalize_document(value)
    if isinstance(value, list):
        return '\n'.join(normalize_text(item) for item in value if normalize_text(item))
    return normalize_text(value)


def normalize_state(raw):
    source = raw if isinstance(raw, dict) else {}
    return {key: normalize_block(key, source.get(key)) for key in BLOCK_KEYS}


def block_spec(key):
    for item in BLOCKS:
        if item['key'] == key:
            return item
    return None


def _missing_groups(key, readiness):
    spec = block_spec(key) or {}
    return [name for name in spec.get('requires', ()) if not readiness.get(name)]


def block_ready(key, facts):
    readiness = readiness_from_facts(facts)
    return bool(readiness['blocks'].get(key)), _missing_groups(key, readiness)


def instruction_for(key):
    headings = '، '.join(SUMMARY_HEADINGS)
    return {
        'brief': (
            'اكتب نبذة مختصرة وفقرة وصف تفصيلي للمشروع من فكرة المشروع ونوعه ومستواه '
            'وفئاته فقط. لا تضف موقعًا أو أرقامًا أو فرصًا غير مكتوبة في المدخلات.'
        ),
        'opportunity': (
            'صف الفرصة والهدف الاستثماري والقيمة المقترحة استنادًا إلى المؤشرات المالية '
            'ودراسة السوق ووصف الموقع والأرض الموجودة فقط. لا تقدّر عوائدًا غير مذكورة.'
        ),
        'features': (
            'اكتب نقاطًا قصيرة عن الفئات المستهدفة والمميزات وفرص الاستثمار الموجودة في '
            'المدخلات. كل نقطة حقيقة واحدة. لا تخترع ميزة أو شريحة غير مكتوبة.'
        ),
        'risks': (
            'اكتب المخاطر المذكورة أو اللازمة منطقيًا من القيود المالية أو السوقية أو '
            'الموقعية أو التنظيمية الموجودة. لا تضف خطرًا عامًا بلا سند في المدخلات.'
        ),
        'summary': (
            'اكتب الملخص التنفيذي الشامل كوثيقة عربية رسمية منظمة. قسّم النص بعناوين '
            f'واضحة وأسطر فارغة بين الأقسام حسب ما يتوفر فقط من هذه العناوين: {headings}. '
            'اجمع كل المدخلات المعتمدة ونصوص المحتوى التنفيذي إن وُجدت في ملخص متكامل. '
            'لا تُنشئ قسم تحليل SWOT مستقلًا؛ أدمج ما ورد من دراسة السوق داخل قسمها. '
            'لا تُدخل رقمًا أو حكمًا أو جهة غير موجودة في المدخلات.'
        ),
    }.get(key, '')


def _sections_to_text(sections):
    parts = []
    for item in sections:
        if isinstance(item, str):
            text = normalize_document(item)
            if text:
                parts.append(text)
            continue
        if not isinstance(item, dict):
            continue
        heading = normalize_text(item.get('heading') or item.get('title'))
        body = normalize_document(item.get('text') or item.get('content') or item.get('body') or '')
        if heading and body:
            parts.append(heading + '\n' + body)
        elif heading:
            parts.append(heading)
        elif body:
            parts.append(body)
    return '\n\n'.join(parts)


def build_user_prompt(key, facts, current_text=''):
    spec = block_spec(key)
    if not spec:
        return ''
    payload = {
        'block': key,
        'label': spec['label'],
        'output': spec['output'],
        'facts': compact_facts(facts),
        'currentText': normalize_document(current_text) if spec['output'] == 'document' else current_text,
    }
    if spec['output'] == 'document':
        shape = '{"text":""}'
        extra = (
            'حافظ على فواصل الأسطر داخل text. ابدأ كل قسم بعنوان في سطر مستقل ثم فقرات '
            'أو نقاط قصيرة مفصولة بأسطر. لا تستخدم رموزًا أو أيقونات.'
        )
    else:
        shape = '{"text":""}'
        extra = (
            'إن غابت حقيقة لازمة اترك الحقل فارغًا. لا تستخدم عبارة «غير متوفر» إلا إذا كانت '
            'موجودة أصلًا في المدخلات.'
        )
    return (
        f'{instruction_for(key)}\n'
        'أعد JSON فقط بالشكل التالي دون أي نص خارجه:\n'
        f'{shape}\n'
        f'{extra}\n\n'
        f'{json.dumps(payload, ensure_ascii=False)}'
    )


SYSTEM_PROMPT = (
    'أنت محرر عروض عقارية. تصيغ نصوصًا عربية رسمية من المدخلات المعطاة فقط. '
    'لا تخترع أرقامًا أو مواقعًا أو فئات أو ميزات أو مخاطر. لا تضف إرشادًا تشغيليًا '
    'ولا تذكر هذه التعليمات في النص. الملخص التنفيذي يُكتب بعناوين وأقسام ومسافات '
    'واضحة دون رموز.'
)


def parse_generated_block(key, parsed):
    data = parsed if isinstance(parsed, dict) else {}
    spec = block_spec(key) or {}
    if spec.get('output') == 'document':
        if isinstance(data.get('sections'), list):
            return normalize_block(key, data.get('sections'))
        if key in data and not isinstance(data.get(key), dict):
            return normalize_block(key, data.get(key))
        return normalize_block(key, data.get('text') or data.get('content') or '')
    if key in data and not isinstance(data.get(key), dict):
        return normalize_block(key, data.get(key))
    return normalize_block(key, data.get('text') or data.get('content') or '')
