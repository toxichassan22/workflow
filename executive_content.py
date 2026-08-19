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
        'requires': ('basic', 'location', 'financial', 'market'),
        'output': 'paragraphs',
    },
    {
        'key': 'features',
        'label': 'المميزات وفرص الاستثمار',
        'requires': ('basic', 'market'),
        'output': 'bullets',
    },
    {
        'key': 'swot',
        'label': 'تحليل SWOT',
        'requires': ('basic', 'location', 'financial', 'market'),
        'output': 'swot',
    },
    {
        'key': 'risks',
        'label': 'دراسة المخاطر',
        'requires': ('basic', 'location', 'financial', 'market'),
        'output': 'bullets',
    },
    {
        'key': 'summary',
        'label': 'الملخص التنفيذي',
        'requires': ('basic', 'location', 'financial', 'market'),
        'output': 'paragraphs',
    },
)

SWOT_KEYS = ('strengths', 'weaknesses', 'opportunities', 'threats')
SWOT_LABELS = {
    'strengths': 'نقاط القوة',
    'weaknesses': 'نقاط الضعف',
    'opportunities': 'الفرص',
    'threats': 'التهديدات',
}
BLOCK_KEYS = tuple(item['key'] for item in BLOCKS)
MISSING_FACTS = 'غير متوفر من المدخلات المعتمدة'


def empty_block(key):
    if key == 'swot':
        return {item: '' for item in SWOT_KEYS}
    return ''


def empty_state():
    return {key: empty_block(key) for key in BLOCK_KEYS}


def normalize_text(value):
    return ' '.join(str(value or '').replace('\r\n', '\n').split())


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


def compact_facts(facts):
    data = facts if isinstance(facts, dict) else {}
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
        'locationDetail': normalize_text(data.get('locationDetail')),
        'allowedUses': normalize_text(data.get('allowedUses')),
        'landUseStatus': normalize_text(data.get('landUseStatus')),
        'siteAnalysis': normalize_text(data.get('siteAnalysis')),
        'components': _join(data.get('components')),
        'financialIndicators': _compact_mapping(data.get('financialIndicators')),
        'marketSummary': _compact_mapping(data.get('marketSummary')),
        'marketSwot': _compact_mapping(data.get('marketSwot')),
        'marketDecision': normalize_text(data.get('marketDecision')),
    }


def readiness_from_facts(facts):
    data = compact_facts(facts)
    has_name = bool(data['projectName'])
    has_type = bool(data['projectType'])
    has_idea = bool(data['projectIdea'])
    has_location = bool(data['city'] or data['district'] or data['locationDetail'] or data['siteAnalysis'])
    has_financial = bool(data['financialIndicators'] or data['components'])
    has_market = bool(data['marketSummary'] or data['marketDecision'] or data['marketSwot'])
    groups = {
        'basic': has_name and has_type,
        'idea': has_idea,
        'location': has_location,
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
    if key == 'swot':
        source = value if isinstance(value, dict) else {}
        return {item: normalize_text(source.get(item)) for item in SWOT_KEYS}
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
    return {
        'brief': (
            'اكتب نبذة مختصرة وفقرة وصف تفصيلي للمشروع من فكرة المشروع ونوعه ومستواه '
            'وفئاته فقط. لا تضف موقعًا أو أرقامًا أو فرصًا غير مكتوبة في المدخلات.'
        ),
        'opportunity': (
            'صف الفرصة والهدف الاستثماري والقيمة المقترحة استنادًا إلى المؤشرات المالية '
            'ودراسة السوق ووصف الموقع الموجودة فقط. لا تقدّر عوائدًا غير مذكورة.'
        ),
        'features': (
            'اكتب نقاطًا قصيرة عن الفئات المستهدفة والمميزات وفرص الاستثمار الموجودة في '
            'المدخلات. كل نقطة حقيقة واحدة. لا تخترع ميزة أو شريحة غير مكتوبة.'
        ),
        'swot': (
            'املأ مفاتيح strengths و weaknesses و opportunities و threats من المدخلات فقط. '
            'إن غاب أحد الأركان اتركه فارغًا ولا تكمله بعبارة عامة.'
        ),
        'risks': (
            'اكتب المخاطر المذكورة أو اللازمة منطقيًا من القيود المالية أو السوقية أو '
            'الموقعية الموجودة. لا تضف خطرًا عامًا بلا سند في المدخلات.'
        ),
        'summary': (
            'لخّص النتائج الموجودة في المدخلات وباقي نصوص المحتوى التنفيذي إن وُجدت. '
            'لا تُدخل رقمًا أو حكمًا غير موجود في تلك المدخلات.'
        ),
    }.get(key, '')


def build_user_prompt(key, facts, current_text=''):
    spec = block_spec(key)
    if not spec:
        return ''
    payload = {
        'block': key,
        'label': spec['label'],
        'output': spec['output'],
        'facts': compact_facts(facts),
        'currentText': current_text if key != 'swot' else (current_text or empty_block('swot')),
    }
    if spec['output'] == 'swot':
        shape = '{"strengths":"","weaknesses":"","opportunities":"","threats":""}'
    else:
        shape = '{"text":""}'
    return (
        f'{instruction_for(key)}\n'
        'أعد JSON فقط بالشكل التالي دون أي نص خارجه:\n'
        f'{shape}\n'
        'إن غابت حقيقة لازمة اترك الحقل فارغًا. لا تستخدم عبارة «غير متوفر» إلا إذا كانت '
        'موجودة أصلًا في المدخلات.\n\n'
        f'{json.dumps(payload, ensure_ascii=False)}'
    )


SYSTEM_PROMPT = (
    'أنت محرر عروض عقارية. تصيغ نصوصًا عربية رسمية من المدخلات المعطاة فقط. '
    'لا تخترع أرقامًا أو مواقعًا أو فئات أو ميزات أو مخاطر. لا تضف إرشادًا تشغيليًا '
    'ولا تذكر هذه التعليمات في النص.'
)


def parse_generated_block(key, parsed):
    data = parsed if isinstance(parsed, dict) else {}
    if key == 'swot':
        nested = data.get('swot') if isinstance(data.get('swot'), dict) else data
        return normalize_block('swot', nested)
    if key in data and not isinstance(data.get(key), dict):
        return normalize_block(key, data.get(key))
    return normalize_block(key, data.get('text') or data.get('content') or '')
