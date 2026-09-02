"""
Slide Engine: Dynamic slide count & content distribution.
AI analyzes project data and proposes a balanced slide plan.
"""

import json
import os
import re
import concurrent.futures
import html as html_lib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser
from design_templates import (
    build_design_rules, contrast_ratio, dark_surface_color, extract_slide_elements,
    normalize_hex_color, readable_text_color,
)
import db
# emoji_icons is intentionally not imported: it converted emojis into inline SVG icons, which the
# icon stripper then removed. The product rule is that no icon is ever generated.

_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')

# ─────────────────────────────────────────────────────────────────────────────
# Content Distribution Rules
# ─────────────────────────────────────────────────────────────────────────────

CONTENT_DISTRIBUTION_RULES = """
## قواعد توزيع المحتوى (إلزامية — اتبعها بدقة)
1. الغلاف أولاً، ثم فهرس الأقسام مع رقم صفحة بداية كل قسم، ثم أقسام المحتوى، والخاتمة أخيراً.
2. ترتيب الأقسام لا يتغير: نبذة عن المشروع، مكونات المشروع، تحليل الأرض، تحليل الموقع الجغرافي، تحليل السوق، الجدول الزمني، الدراسة المالية، تحليل SWOT وتحليل المخاطر، فريق العمل، المخططات، التصورات الخارجية، التصورات الداخلية، الملخص التنفيذي، الخاتمة.
3. الفهرس يعرض أسماء الأقسام فقط مع أرقام الصفحات؛ لا يعرض عناوين الشرائح الفرعية ولا يستخدم مخطط محاور أو تدفق أو بطاقات صغيرة.
4. صفحة بداية كل قسم تحمل اسم القسم وحده بلا وصف وبلا ترجمة وبلا نقاط.
5. كل شريحة لها فكرة واحدة، ويُقسّم المحتوى الطويل على صفحات إضافية بدلاً من تصغيره أو حذفه.
6. لا تكرر المعلومة أو مكونات المشروع في أكثر من موضع. الإحالة المختصرة مسموحة، أما إعادة الجدول أو القائمة نفسها فممنوعة.
7. اختر الشكل بحسب طبيعة المحتوى: نص متصل للنبذات والملخصات، جدول للصفوف المنظمة، وصورة كبيرة للصور والمخططات. الرسوم البيانية محصورة حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة (مقارنة المنافسين: horizontal_bar في دراسة السوق، وتكلفة الاستثمار: waterfall، والتدفقات النقدية: combo، ومقارنة السيناريوهات: heatmap في الدراسة المالية). أي رسم خارج هذه المواقع الأربعة والأنواع الأربعة ممنوع منعاً باتاً. استخدم البطاقات فقط لعناصر مستقلة قصيرة ومتوازية، وبحد أقصى ثلاث بطاقات عند الحاجة.
8. يوضع ملخص نهائي مستند إلى بيانات البرنامج بعد جداول كل قسم تحليلي، ولا تُضاف تحسينات إنشائية أو استرسال لا يحمل معلومة واضحة.
9. شرائح الصور تستخدم كل الرموز المحددة لها بتخطيط المجموعة المعتمد، من صورة واحدة إلى ثلاث صور؛ وكل صورة تظهر مرة واحدة فقط ولا تعاد في شريحة أخرى.
10. شرائح الموقع والخرائط تبقى داخل قسم تحليل الموقع الجغرافي، وشرائح الأرض وصورها وملخصها داخل قسم تحليل الأرض.
"""

PRESENTATION_SECTION_ORDER = (
    'overview', 'components', 'land', 'location', 'market', 'timeline', 'financial',
    'swot_risks', 'team', 'plans', 'exterior', 'interior', 'executive_summary', 'closing',
)

PRESENTATION_SECTION_TITLES = {
    'overview': 'نبذة عن المشروع',
    'components': 'مكونات المشروع',
    'land': 'تحليل الأرض',
    'location': 'تحليل الموقع الجغرافي',
    'market': 'تحليل السوق',
    'timeline': 'الجدول الزمني',
    'financial': 'الدراسة المالية',
    'swot_risks': 'تحليل SWOT وتحليل المخاطر',
    'team': 'فريق العمل',
    'plans': 'المخططات',
    'exterior': 'التصورات الخارجية',
    'interior': 'التصورات الداخلية',
    'executive_summary': 'الملخص التنفيذي',
    'closing': 'الخاتمة',
}

_SECTION_KEY_ALIASES = {
    'project': 'overview', 'project_overview': 'overview', 'project_idea': 'overview',
    'project_components': 'components', 'land_analysis': 'land', 'site': 'location',
    'geographic_location': 'location', 'market_analysis': 'market', 'schedule': 'timeline',
    'finance': 'financial', 'financial_study': 'financial', 'swot': 'swot_risks',
    'risks': 'swot_risks', 'team_members': 'team', 'floorplans': 'plans',
    'moodboard': 'exterior', 'external': 'exterior', 'internal': 'interior',
    'executive': 'executive_summary', 'summary': 'executive_summary', 'conclusion': 'closing',
}

_SECTION_MATCHERS = (
    ('closing', r'(?:الخاتمة|الختام|شكرا|شكراً|closing|conclusion|thanks)'),
    ('executive_summary', r'(?:الملخص التنفيذي|executive summary)'),
    ('interior', r'(?:التصورات? الداخلية|التصميم الداخلي|interior)'),
    ('exterior', r'(?:التصورات? الخارجية|المود بورد|mood ?board|واجهات المشروع|exterior|التصور البصري)'),
    ('plans', r'(?:المخططات|المساقط|مخطط معماري|2d|floor ?plans?)'),
    ('team', r'(?:فريق العمل|فريق التطوير|المطور|الاستشاري|team)'),
    ('swot_risks', r'(?:swot|نقاط القوة|نقاط الضعف|الفرص والتهديدات|المخاطر|إدارة المخاطر|risk)'),
    ('financial', r'(?:الدراسة المالية|التحليل المالي|الجدوى|التدفقات النقدية|الإيرادات|التكاليف|العائد|roi|irr|financial|cash ?flow)'),
    ('timeline', r'(?:الجدول الزمني|الخطة الزمنية|مراحل التطوير|مراحل التنفيذ|timeline|schedule)'),
    ('market', r'(?:تحليل السوق|دراسة السوق|المنافسين|الطلب السوقي|market|competitor)'),
    ('location', r'(?:الموقع الجغرافي|تحليل الموقع|الموقع الاستراتيجي|خريطة|الطرق|المعالم|نطاق التأثير|site|location|map|access|landmarks|catchment)'),
    ('land', r'(?:تحليل الأرض|الأرض والاشتراطات|الأرض والكروكي|الكروكي|اشتراطات البناء|حدود الأرض|صور الأرض|land|croquis)'),
    ('components', r'(?:مكونات المشروع|الوحدات والمساحات|المكونات|components|units)'),
    ('overview', r'(?:نبذة عن المشروع|المشروع والفكرة|فكرة المشروع|نظرة عامة|تعريف المشروع|project overview|project brief)'),
)


def _slide_section_key(slide, current=''):
    slide = slide if isinstance(slide, dict) else {}
    explicit = str(slide.get('section_key') or slide.get('sectionKey') or slide.get('section') or '').strip().lower()
    explicit = _SECTION_KEY_ALIASES.get(explicit, explicit)
    if explicit in PRESENTATION_SECTION_ORDER:
        return explicit
    slide_type = str(slide.get('type') or '').strip().lower()
    if slide_type == 'closing':
        return 'closing'
    if slide_type == 'moodboard':
        return 'exterior'
    if slide_type.startswith('map_') or slide_type == 'site_specs':
        return 'location'
    text = ' '.join(str(value or '') for value in (
        slide.get('title'), slide.get('content_source') or slide.get('contentSource'),
        slide.get('source_table') or slide.get('sourceTable'),
        ' '.join(str(item or '') for item in (slide.get('bullets') or [])),
    )).lower()
    for key, pattern in _SECTION_MATCHERS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return key
    return current if current in PRESENTATION_SECTION_ORDER else 'overview'


def _plan_slide_signature(slide):
    title = re.sub(r'[\W_]+', '', str(slide.get('title') or '').lower(), flags=re.UNICODE)
    source = re.sub(r'\s+', '', str(slide.get('content_source') or slide.get('source_table') or '').lower())
    tokens = '|'.join(str(item or '') for item in (slide.get('image_tokens') or []))
    return ('source', source) if source else ('tokens', tokens) if tokens else ('title', title)


def _canonical_image_token(token):
    value = str(token or '').strip()
    patterns = (
        (r'#*(?:PROJECT_IMAGE|MOODBOARD_IMAGE)_(\d+)#*', 'MOODBOARD_IMAGE'),
        (r'#*(?:LAND_IMAGE|LAND_PHOTO)_(\d+)#*', 'LAND_PHOTO'),
        (r'#*(?:2D_PLAN|PLAN_IMAGE)_(\d+)#*', 'PLAN_IMAGE'),
    )
    for pattern, prefix in patterns:
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match:
            return f'##{prefix}_{int(match.group(1))}##'
    for pattern in (
        r'#*INTERIOR_COMP_(\d+)_(?:IMG|IMAGE)_(\d+)#*',
        r'#*INTERIOR_C(\d+)_(?:IMG|IMAGE)_(\d+)#*',
        r'#*INTERIOR_(\d+)_(\d+)#*',
    ):
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match:
            return f'##INTERIOR_COMP_{int(match.group(1))}_IMG_{int(match.group(2))}##'
    return value


def _canonicalize_slide_image_tokens(slide):
    if not isinstance(slide, dict):
        return slide
    normalized = []
    raw_tokens = slide.get('image_tokens') or []
    if not isinstance(raw_tokens, (list, tuple)):
        raw_tokens = [raw_tokens]
    for token in raw_tokens:
        canonical = _canonical_image_token(token)
        if canonical and canonical not in normalized:
            normalized.append(canonical)
    slide['image_tokens'] = normalized
    return slide


def _reserve_media_sections(groups):
    owners = {
        '##MOODBOARD_IMAGE_': 'exterior',
        '##LAND_PHOTO_': 'land',
        '##PLAN_IMAGE_': 'plans',
        '##INTERIOR_COMP_': 'interior',
    }
    def owner_of(token):
        return next((owner for prefix, owner in owners.items() if token.startswith(prefix)), '')

    for section_key, slides in groups.items():
        kept = []
        for slide in slides:
            _canonicalize_slide_image_tokens(slide)
            original = slide.get('image_tokens') or []
            tokens = [token for token in original if not owner_of(token) or owner_of(token) == section_key]
            slide['image_tokens'] = tokens
            if original and not tokens:
                slide['requires_image'] = False
                if slide.get('design_style') == 'image' and not slide.get('content_source') and not slide.get('bullets'):
                    continue
                if slide.get('design_style') == 'image':
                    slide['design_style'] = 'text'
            kept.append(slide)
        groups[section_key] = kept


def _deduplicate_plan_media(groups):
    used = set()
    prefixes = ('##MOODBOARD_IMAGE_', '##LAND_PHOTO_', '##PLAN_IMAGE_', '##INTERIOR_COMP_')
    for section_key in PRESENTATION_SECTION_ORDER:
        kept = []
        for slide in groups.get(section_key, []):
            _canonicalize_slide_image_tokens(slide)
            tokens = slide.get('image_tokens') or []
            unique_tokens = [token for token in tokens if not token.startswith(prefixes) or token not in used]
            if tokens and not unique_tokens:
                continue
            slide['image_tokens'] = unique_tokens
            used.update(token for token in unique_tokens if token.startswith(prefixes))
            kept.append(slide)
        groups[section_key] = kept
    return used


def _drop_redundant_generic_slides(groups):
    generic = {
        'المحتوى المعتمد لهذا القسم', 'التفاصيل المتاحة في بيانات المشروع',
        'الملخص النهائي دون تكرار', 'تعريف المشروع من البيانات المعتمدة',
        'الفكرة والاستخدامات المعتمدة', 'ملخص موجز دون تكرار',
    }
    for section_key, slides in groups.items():
        concrete = any(slide.get('content_source') or slide.get('source_table') or slide.get('image_tokens')
                       for slide in slides)
        if concrete:
            groups[section_key] = [
                slide for slide in slides
                if slide.get('content_source') or slide.get('source_table') or slide.get('image_tokens')
                or not generic.intersection(str(item or '').strip() for item in (slide.get('bullets') or []))
            ]


APPROVED_CHART_TYPES = ('horizontal_bar', 'waterfall', 'combo', 'heatmap')
FINANCIAL_CHART_TYPES = ('waterfall', 'combo', 'heatmap')

CHART_TYPE_ALIASES = {
    'bar': 'horizontal_bar',
    'horizontal_bar': 'horizontal_bar',
    'waterfall': 'waterfall',
    'combo': 'combo',
    'combo_chart': 'combo',
    'column_line': 'combo',
    'line_column': 'combo',
    'heatmap': 'heatmap',
}


def canonicalize_chart_type(chart_type):
    if not chart_type:
        return ''
    cleaned = str(chart_type).strip().lower().replace('-', '_').replace(' ', '_')
    return CHART_TYPE_ALIASES.get(cleaned, '')


def _financial_chart_type(title='', table_key='', index=0):
    text = f'{title} {table_key}'.lower()
    if re.search(r'حساسي|سيناريو|sensitivity', text):
        return 'heatmap'
    if re.search(r'تدفق|cashflow|cash flow', text):
        return 'combo'
    if re.search(r'تكال|تكلف|cost|استثمار|capex', text) and not re.search(r'تشغيل|opex', text):
        return 'waterfall'
    return ''


def _financial_report_part_slice(part, row_start, row_end, column_start=None, column_end=None):
    result = dict(part) if isinstance(part, dict) else {}
    rows = result.get('rows') if isinstance(result.get('rows'), list) else []
    selected_rows = rows[row_start:row_end]
    headers = result.get('headers') if isinstance(result.get('headers'), list) else []
    if column_start is not None and column_end is not None and headers:
        indexes = list(range(column_start, min(column_end, len(headers))))
        if column_start > 0 and 0 not in indexes:
            indexes.insert(0, 0)
        result['headers'] = [headers[index] for index in indexes]
        result['rows'] = [[row[index] if index < len(row) else '' for index in indexes]
                          if isinstance(row, (list, tuple)) else row for row in selected_rows]
    else:
        result['rows'] = selected_rows
    return result


def _financial_column_ranges(part):
    headers = part.get('headers') if isinstance(part, dict) and isinstance(part.get('headers'), list) else []
    if len(headers) <= 8:
        return [(None, None)]
    return [(start, min(start + 5, len(headers))) for start in range(1, len(headers), 5)]


def _balanced_row_ranges(total_rows, max_per_slide=12, min_per_slide=4):
    """Chunk rows into balanced, readable ranges without leaving orphan 1-2 row slides."""
    if total_rows <= 0:
        return []
    if total_rows <= max_per_slide:
        return [(0, total_rows)]
    num_chunks = (total_rows + 9) // 10
    while num_chunks > 1 and (total_rows // num_chunks) < min_per_slide:
        num_chunks -= 1
    base_size = total_rows // num_chunks
    remainder = total_rows % num_chunks
    ranges = []
    start = 0
    for i in range(num_chunks):
        size = base_size + (1 if i < remainder else 0)
        ranges.append((start, start + size))
        start += size
    return ranges


def _financial_table_chartable(part, rows, column_start=None, column_end=None):
    if column_start is not None:
        return False
    headers = part.get('headers') if isinstance(part, dict) and isinstance(part.get('headers'), list) else []
    column_count = len(headers) if column_start is None else min(column_end, len(headers)) - column_start + 1
    return 2 <= len(rows) <= 12 and 2 <= column_count <= 8 and _rows_have_comparable_numbers(rows)


def _financial_chart_score(slide):
    text = ' '.join(str(slide.get(key) or '') for key in ('title', 'content_source', 'source_table', 'chart_type')).lower()
    priorities = (
        (r'تكال|تكلف|cost|waterfall', 100),
        (r'تدفق|cashflow|cash flow|combo', 90),
        (r'حساسي|سيناريو|sensitivity|heatmap', 80),
    )
    return next((score for pattern, score in priorities if re.search(pattern, text)), 50)


def _limit_presentation_charts(groups, limit=4):
    chart_styles = {'chart', 'bar', 'column', 'grouped_bar', 'grouped_column', 'line', 'area',
                    'pie', 'donut', 'treemap', 'scatter', 'histogram', 'heatmap', 'candlestick',
                    'horizontal_bar', 'waterfall', 'combo'}
    for section_key, slides in groups.items():
        if section_key in ('market', 'financial'):
            continue
        for slide in slides:
            if slide.get('chart_type') or slide.get('design_style') in chart_styles:
                slide['chart_type'] = ''
                slide['design_style'] = 'table' if slide.get('source_table') else 'text'

    market_slides = groups.get('market', [])
    kept_market_chart = False
    for slide in market_slides:
        c_type = canonicalize_chart_type(slide.get('chart_type'))
        text = ' '.join(str(slide.get(k) or '') for k in ('title', 'content_source', 'source_table')).lower()
        is_competitor = bool(re.search(r'منافس|competitor', text))
        if c_type == 'horizontal_bar' and is_competitor and not kept_market_chart:
            slide['chart_type'] = 'horizontal_bar'
            slide['design_style'] = 'chart'
            kept_market_chart = True
        else:
            if slide.get('chart_type') or slide.get('design_style') in chart_styles:
                slide['chart_type'] = ''
                slide['design_style'] = 'table' if slide.get('source_table') else 'text'

    financial = groups.get('financial', [])
    candidates = []
    for index, slide in enumerate(financial):
        c_type = canonicalize_chart_type(slide.get('chart_type'))
        if c_type in FINANCIAL_CHART_TYPES:
            candidates.append((index, slide, c_type))

    seen_types = set()
    keep_indices = set()
    for index, slide, c_type in sorted(
        candidates, key=lambda item: (-_financial_chart_score(item[1]), item[0])):
        if c_type not in seen_types and len(keep_indices) < 3:
            seen_types.add(c_type)
            keep_indices.add(index)
            slide['chart_type'] = c_type
            slide['design_style'] = 'chart'

    for index, slide in enumerate(financial):
        if index not in keep_indices:
            if slide.get('chart_type') or slide.get('design_style') in chart_styles:
                slide['chart_type'] = ''
                slide['design_style'] = 'table'


def _merge_sparse_plan_slides(groups):
    for section_key, slides in groups.items():
        merged = []
        for slide in slides:
            source = str(slide.get('content_source') or '')
            sparse_financial = (section_key == 'financial' and slide.get('row_count') == 1
                                and not source.startswith(('financial_summary:', 'financial_indicators')))
            sparse_generic = (not source and not slide.get('image_tokens')
                              and len([item for item in (slide.get('bullets') or []) if str(item or '').strip()]) <= 1)
            if (sparse_financial or sparse_generic) and merged:
                target = merged[-1]
                if source:
                    target['content_sources'] = list(target.get('content_sources') or [target.get('content_source')])
                    target['content_sources'].append(source)
                    target['row_count'] = int(target.get('row_count') or 0) + int(slide.get('row_count') or 0)
                else:
                    target['bullets'] = list(target.get('bullets') or []) + list(slide.get('bullets') or [])
                continue
            merged.append(slide)
        if len(merged) > 1:
            first = merged[0]
            first_source = str(first.get('content_source') or '')
            first_sparse = (section_key == 'financial' and first.get('row_count') == 1
                            and not first_source.startswith(('financial_summary:', 'financial_indicators')))
            first_generic = (not first_source and not first.get('image_tokens')
                             and len([item for item in (first.get('bullets') or []) if str(item or '').strip()]) <= 1)
            if first_sparse or first_generic:
                target = merged[1]
                if first_source:
                    target['content_sources'] = list(first.get('content_sources') or [first_source]) + list(
                        target.get('content_sources') or [target.get('content_source')])
                    target['row_count'] = int(first.get('row_count') or 0) + int(target.get('row_count') or 0)
                else:
                    target['bullets'] = list(first.get('bullets') or []) + list(target.get('bullets') or [])
                merged.pop(0)
        groups[section_key] = merged


def _financial_summary_from_report(model):
    report = model.get('report') if isinstance(model, dict) and isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    groups = {'التكاليف والاستثمار': [], 'مؤشرات العائد والاسترداد': []}
    current = ''
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get('type') == 'heading':
            current = str(part.get('text') or '').strip()
            continue
        target = next((name for name in groups if name in current), None)
        if target and part.get('type') == 'fields':
            groups[target].extend(row for row in (part.get('rows') or [])
                                  if isinstance(row, (list, tuple)) and len(row) >= 2)
    return groups if any(groups.values()) else {}


def _financial_summary_plan_slides(model):
    summary = _financial_summary_from_report(model)
    available = [(name, rows) for name, rows in summary.items() if rows]
    if not available:
        return [{
            'title': 'الملخص المالي', 'type': 'content', 'design_style': 'table',
            'chart_type': '', 'content_density': 'high', 'requires_image': False,
            'content_source': 'financial_indicators', 'row_count': 2, 'bullets': [],
        }]
    slides = []
    for name, rows in available:
        row_ranges = _balanced_row_ranges(len(rows), max_per_slide=12, min_per_slide=5)
        for chunk_index, (start, end) in enumerate(row_ranges, 1):
            chunk = rows[start:end]
            key = 'costs' if name == 'التكاليف والاستثمار' else 'returns'
            suffix = f' — {chunk_index}' if len(row_ranges) > 1 else ''
            slides.append({
                'title': f'الملخص المالي — {name}{suffix}',
                'type': 'content', 'design_style': 'table', 'chart_type': '',
                'content_density': 'high', 'requires_image': False,
                'content_source': f'financial_summary:{key}:{start}:{end}',
                'row_count': len(chunk), 'bullets': [],
            })
    return slides[:3]


_FINANCIAL_PLAN_TABLES = (
    ('revenueTable', 'بنود الإيرادات', 'table'),
    ('costTable', 'تكاليف المشروع', 'chart'),
    ('scheduleTable', 'مراحل التطوير المالية', 'flow'),
    ('opexTable', 'المصروفات التشغيلية', 'table'),
    ('graceScheduleTable', 'جدول فترة السماح', 'table'),
    ('financeDrawTable', 'جدول سحب التمويل', 'flow'),
    ('financeRepaymentTable', 'جدول سداد التمويل', 'flow'),
    ('fundAdditionalFeesTable', 'أتعاب الصندوق الإضافية', 'table'),
    ('externalTable', 'البنود الخارجية', 'table'),
    ('cashflowTable', 'التدفقات النقدية السنوية', 'chart'),
    ('sensitivityAssumptionsTable', 'افتراضات تحليل الحساسية', 'table'),
    ('sensitivityTable', 'نتائج تحليل الحساسية', 'chart'),
)

USE_TYPE_LABELS = {
    'retail': 'تجاري / تجزئة',
    'residential': 'سكني',
    'hospitality': 'فندقي / ضيافة',
    'office': 'مكاتب / إداري',
    'entertainment': 'ترفيهي',
    'services': 'خدمات ومرافق',
    'parking': 'مواقف سيارات',
    'industrial': 'صناعي',
    'logistics': 'لوجستي / مستودعات',
    'other': 'أخرى',
}

INVESTMENT_MODEL_LABELS = {
    'sale': 'بيع وحدات',
    'dailyRent': 'إيجار يومي',
    'monthlyRent': 'إيجار شهري',
    'annualRent': 'إيجار سنوي',
    'operating': 'تشغيل / تأجير آخر',
    'nonRevenue': 'بدون إيراد / مرافق عامة',
}


def _format_component_row(row):
    if not isinstance(row, dict):
        return {}
    name = row.get('name') or row.get('اسم المكون') or row.get('المكون') or ''
    use_type = row.get('useType') or row.get('use_type') or row.get('نوع الاستخدام') or ''
    use_type_label = USE_TYPE_LABELS.get(use_type, use_type)
    units_count = row.get('units') or row.get('unitsCount') or row.get('units_count') or row.get('عدد الوحدات') or ''
    unit_area = row.get('unitArea') or row.get('unit_area') or row.get('مساحة الوحدة') or row.get('مساحة الوحدة م²') or ''
    built_area = row.get('builtArea') or row.get('built_area') or row.get('المساحة المبنية') or row.get('المساحة المبنية م²') or ''
    leasable_area = row.get('revenueArea') or row.get('revenue_area') or row.get('leasableArea') or row.get('leasable_area') or row.get('totalArea') or row.get('المساحة البيعية / التأجيرية') or row.get('المساحة البيعية / التأجيرية م²') or row.get('المساحة التأجيرية') or ''
    inv_model = row.get('investmentModel') or row.get('investment_model') or row.get('نموذج الاستفادة') or row.get('نموذج الاستثمار') or ''
    inv_model_label = INVESTMENT_MODEL_LABELS.get(inv_model, inv_model)

    formatted = {}
    if name:
        formatted['اسم المكون'] = name
    if use_type_label:
        formatted['نوع الاستخدام'] = use_type_label
    if units_count:
        formatted['عدد الوحدات'] = units_count
    if unit_area:
        formatted['مساحة الوحدة م²'] = unit_area
    if built_area:
        formatted['المساحة المبنية م²'] = built_area
    if leasable_area:
        formatted['المساحة البيعية / التأجيرية م²'] = leasable_area
    if inv_model_label:
        formatted['نموذج الاستفادة'] = inv_model_label

    for k, v in row.items():
        if k not in ('name', 'useType', 'use_type', 'units', 'unitsCount', 'units_count', 'unitArea', 'unit_area',
                     'builtArea', 'built_area', 'leasableArea', 'leasable_area', 'revenueArea', 'revenue_area',
                     'totalArea', 'total_area', 'investmentModel', 'investment_model', 'idx', 'id', 'leasable',
                     'اسم المكون', 'نوع الاستخدام', 'عدد الوحدات', 'مساحة الوحدة', 'مساحة الوحدة م²',
                     'المساحة المبنية', 'المساحة المبنية م²', 'المساحة البيعية / التأجيرية',
                     'المساحة البيعية / التأجيرية م²', 'المساحة التأجيرية', 'نموذج الاستفادة', 'نموذج الاستثمار') and k not in formatted:
            if v not in (None, '', [], {}):
                formatted[k] = v
    return formatted if formatted else row


def _project_component_rows(project_data):
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    dynamic = model.get('dynamicRows') if isinstance(model.get('dynamicRows'), dict) else {}
    rows = dynamic.get('components') if isinstance(dynamic.get('components'), list) else []
    if not rows:
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get('componentsTable') if isinstance(tables.get('componentsTable'), list) else []
    if not rows:
        decoded = _decode_json_fact((project_data or {}).get('project_components_data'))
        rows = decoded if isinstance(decoded, list) else []
    valid_rows = [row for row in rows if isinstance(row, dict) and any(str(value or '').strip() for value in row.values())]
    return [_format_component_row(row) for row in valid_rows]


def _available_asset_items(values):
    items = []
    seen = set()
    for index, value in enumerate(values if isinstance(values, list) else [], 1):
        source = value if isinstance(value, dict) else {'url': value}
        url = str(source.get('url') or source.get('imageUrl') or '').strip()
        identity = str(source.get('id') or url).split('?', 1)[0]
        if url and identity not in seen:
            seen.add(identity)
            items.append((index, source))
    return items


def _balanced_media_chunks(items, single=False):
    items = list(items or [])
    if single:
        return [[item] for item in items]
    if len(items) <= 2:
        return [items] if items else []
    sizes = [2] * (len(items) // 2)
    if len(items) % 2:
        if sizes:
            sizes[-1] = 3
        else:
            sizes = [1]
    chunks = []
    start = 0
    for size in sizes:
        chunks.append(items[start:start + size])
        start += size
    return chunks


def _rows_have_comparable_numbers(rows):
    values = []
    for row in rows if isinstance(rows, list) else []:
        cells = row.values() if isinstance(row, dict) else row if isinstance(row, (list, tuple)) else []
        for value in cells:
            text = str(value or '').replace(',', '').replace('٬', '').strip()
            if re.fullmatch(r'-?\d+(?:\.\d+)?%?', text):
                values.append(text)
    return len(values) >= 2


def _is_substantive_financial_cell(val, label=''):
    s = str(val or '').strip()
    if not s or s in ('—', '-', 'null', 'undefined'):
        return False
    if s in ('لا', 'no', 'غير مفعل', 'غير مطبق', 'معطل', 'لا يوجد'):
        return False
    if s in ('0', '0.00', '0%', '0.0%', '0 ر.س', '0 م²') and any(k in str(label) for k in ('سماح', 'خصم', 'أتعاب إضافية')):
        return False
    return True


def _filter_substantive_financial_rows(rows, part_type='table'):
    if not isinstance(rows, list):
        return []
    filtered = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            if len(row) >= 2:
                label, val = row[0], row[1]
                if _is_substantive_financial_cell(val, label):
                    filtered.append(row)
            elif any(_is_substantive_financial_cell(c) for c in row):
                filtered.append(row)
        elif isinstance(row, dict):
            if any(_is_substantive_financial_cell(v, k) for k, v in row.items()):
                filtered.append(row)
        elif _is_substantive_financial_cell(row):
            filtered.append(row)
    return filtered


def _ensure_required_plan_content(groups, project_data=None, images=None, tenant_id=None):
    source = project_data if isinstance(project_data, dict) else {}
    images = images if isinstance(images, dict) else {}
    map_placeholders = images.get('map_placeholders') if isinstance(images.get('map_placeholders'), dict) else {}
    has_map_context = any(str(source.get(key) or '').strip() for key in (
        'location_address', 'location_lat', 'location_lng', 'site_analysis')) or any(map_placeholders.values())
    overview_map_tokens = ['##MAP_OVERVIEW##'] if has_map_context else []

    def add(section_key, slide, replace=False):
        slide = _canonicalize_slide_image_tokens(dict(slide))
        slide['section_key'] = section_key
        if replace:
            groups[section_key] = []
        signature = _plan_slide_signature(slide)
        if any(_plan_slide_signature(existing) == signature for existing in groups.get(section_key, [])):
            return
        groups.setdefault(section_key, []).append(slide)

    _reserve_media_sections(groups)
    used_media_tokens = _deduplicate_plan_media(groups)
    moodboard_tokens = [f'##MOODBOARD_IMAGE_{index}##' for index, _item in _available_asset_items(images.get('moodboard'))]
    if not groups.get('overview') and source:
        add('overview', {
            'title': 'نبذة عن المشروع', 'type': 'content', 'design_style': 'text',
            'content_density': 'medium', 'requires_image': False,
            'content_source': 'project_overview', 'image_tokens': [], 'bullets': [],
        })
    elif groups.get('overview'):
        groups['overview'][0]['title'] = 'نبذة عن المشروع'
        groups['overview'][0]['content_source'] = groups['overview'][0].get('content_source') or 'project_overview'

    moodboard_items = _available_asset_items(images.get('moodboard'))
    moodboard_meta = images.get('moodboard_meta') if isinstance(images.get('moodboard_meta'), list) else []
    groups['exterior'] = [slide for slide in groups.get('exterior', [])
                          if not any(token.startswith('##MOODBOARD_IMAGE_') for token in (slide.get('image_tokens') or []))]
    uncovered_ext = moodboard_items
    if len(moodboard_items) > 1:
        for group_number, chunk in enumerate(_balanced_media_chunks(moodboard_items), 1):
            tokens = [f'##MOODBOARD_IMAGE_{idx}##' for idx, _ in chunk]
            titles = [str(moodboard_meta[idx - 1].get('label') if idx <= len(moodboard_meta) and isinstance(moodboard_meta[idx - 1], dict) else it.get('label') or f'التصور الخارجي {idx}').strip() for idx, it in chunk]
            combined_title = ' — '.join(titles) if len(titles) > 1 else titles[0]
            if len(moodboard_items) > 2:
                combined_title = f'التصورات الخارجية — {group_number}'
            bullets = [str(moodboard_meta[idx - 1].get('caption') if idx <= len(moodboard_meta) and isinstance(moodboard_meta[idx - 1], dict) else it.get('caption') or '').strip() for idx, it in chunk]
            add('exterior', {
                'title': combined_title, 'type': 'content', 'design_style': 'image',
                'content_density': 'medium' if len(chunk) > 1 else 'low', 'requires_image': True,
                'content_source': f'exterior_images_group:{chunk[0][0]}:{chunk[-1][0]}',
                'image_tokens': tokens, 'image_layout': f'balanced_{len(chunk)}',
                'bullets': [b for b in bullets if b],
            })
    else:
        for index, item in uncovered_ext:
            meta = moodboard_meta[index - 1] if index <= len(moodboard_meta) and isinstance(moodboard_meta[index - 1], dict) else {}
            title = str(meta.get('label') or item.get('label') or f'التصور الخارجي {index}').strip()
            caption = str(meta.get('caption') or item.get('caption') or '').strip()
            add('exterior', {
                'title': title, 'type': 'content', 'design_style': 'image',
                'content_density': 'low', 'requires_image': True,
                'content_source': f'exterior_image:{index}',
                'image_tokens': [f'##MOODBOARD_IMAGE_{index}##'],
                'bullets': [caption] if caption else [],
            })

    land_items = _available_asset_items(images.get('land_photos'))
    groups['land'] = [slide for slide in groups.get('land', [])
                      if not any(token.startswith('##LAND_PHOTO_') for token in (slide.get('image_tokens') or []))]
    uncovered_land = land_items
    if len(land_items) > 1:
        for group_number, chunk in enumerate(_balanced_media_chunks(land_items), 1):
            tokens = [f'##LAND_PHOTO_{idx}##' for idx, _ in chunk]
            titles = [str(it.get('name') or f'صورة الأرض {idx}').strip() for idx, it in chunk]
            combined_title = ' — '.join(titles) if len(titles) > 1 else titles[0]
            if len(land_items) > 2:
                combined_title = f'صور الأرض — {group_number}'
            bullets = [str(it.get('description') or it.get('caption') or '').strip() for _, it in chunk]
            add('land', {
                'title': combined_title, 'type': 'content', 'design_style': 'image',
                'content_density': 'medium' if len(chunk) > 1 else 'low', 'requires_image': True,
                'content_source': f'land_photos_group:{chunk[0][0]}:{chunk[-1][0]}',
                'image_tokens': tokens, 'image_layout': f'balanced_{len(chunk)}',
                'bullets': [b for b in bullets if b],
            })
    else:
        for index, item in uncovered_land:
            description = str(item.get('description') or item.get('caption') or '').strip()
            title = str(item.get('name') or f'صورة الأرض {index}').strip()
            add('land', {
                'title': title, 'type': 'content', 'design_style': 'image',
                'content_density': 'low', 'requires_image': True,
                'content_source': f'land_photo:{index}',
                'image_tokens': [f'##LAND_PHOTO_{index}##'],
                'bullets': [description] if description else [],
            })

    has_boundary_data = any(str(source.get(k) or '').strip() for k in (
        'boundary_lengths', 'surrounding_streets', 'facades_count', 'facades_directions'
    ))
    if has_boundary_data:
        directional = [slide for slide in groups.get('land', [])
                       if slide.get('content_source') == 'land_boundary_diagram'
                       or slide.get('design_style') == 'diagram'
                       or re.search(r'(?:مخطط اتجاهي|حدود الأرض والواجهات)', str(slide.get('title') or ''))]
        groups['land'] = [slide for slide in groups.get('land', []) if slide not in directional]
        canonical = dict(directional[0]) if directional else {}
        canonical.update({
            'title': 'مخطط اتجاهي لحدود الأرض',
            'type': 'content',
            'design_style': 'diagram',
            'content_density': 'medium',
            'requires_image': False,
            'content_source': 'land_boundary_diagram',
            'bullets': [],
        })
        add('land', canonical)

    plans = _available_asset_items(images.get('plans'))
    plan_meta = images.get('plan_meta') if isinstance(images.get('plan_meta'), list) else []
    groups['plans'] = [slide for slide in groups.get('plans', [])
                       if not any(token.startswith('##PLAN_IMAGE_') for token in (slide.get('image_tokens') or []))]
    for index, item in plans:
        meta = plan_meta[index - 1] if index <= len(plan_meta) and isinstance(plan_meta[index - 1], dict) else {}
        title = str(meta.get('title') or meta.get('name') or item.get('title') or f'المخطط {index}').strip()
        description = str(meta.get('description') or item.get('description') or '').strip()
        add('plans', {
            'title': title, 'type': 'content', 'design_style': 'image',
            'content_density': 'low', 'requires_image': True,
            'content_source': f'plan_image:{index}', 'source_table': 'conceptual_plans',
            'image_tokens': [f'##PLAN_IMAGE_{index}##'], 'image_layout': 'single',
            'bullets': [description] if description else [],
        })

    interior_components = images.get('interior_components') if isinstance(images.get('interior_components'), list) else []
    groups['interior'] = [slide for slide in groups.get('interior', [])
                          if not any(token.startswith('##INTERIOR_COMP_') for token in (slide.get('image_tokens') or []))]
    for component_index, component in enumerate(interior_components, 1):
        if not isinstance(component, dict):
            continue
        component_name = str(component.get('name') or f'المكون {component_index}').strip()
        comp_items = _available_asset_items(component.get('images'))
        uncovered_comp_items = comp_items
        if len(comp_items) > 1:
            for chunk in _balanced_media_chunks(comp_items):
                tokens = [f'##INTERIOR_COMP_{component_index}_IMG_{j}##' for j, _ in chunk]
                labels = [str(it.get('label') or component_name).strip() for _, it in chunk]
                combined_title = f'{component_name} — ' + ' / '.join(labels) if len(labels) > 1 else f'{component_name} — {labels[0]}'
                bullets = [str(it.get('caption') or '').strip() for _, it in chunk]
                add('interior', {
                    'title': combined_title, 'type': 'content', 'design_style': 'image',
                    'content_density': 'medium' if len(chunk) > 1 else 'low', 'requires_image': True,
                    'content_source': f'interior_images_group:{component_index}:{chunk[0][0]}:{chunk[-1][0]}',
                    'image_tokens': tokens, 'image_layout': f'balanced_{len(chunk)}',
                    'bullets': [b for b in bullets if b],
                })
        else:
            for image_index, item in uncovered_comp_items:
                label = str(item.get('label') or component_name).strip()
                caption = str(item.get('caption') or '').strip()
                add('interior', {
                    'title': f'{component_name} — {label}' if label != component_name else component_name,
                    'type': 'content', 'design_style': 'image', 'content_density': 'low',
                    'requires_image': True,
                    'content_source': f'interior_image:{component_index}:{image_index}',
                    'image_tokens': [f'##INTERIOR_COMP_{component_index}_IMG_{image_index}##'],
                    'bullets': [caption] if caption else [],
                })

    components = _project_component_rows(source)
    if components:
        groups['components'] = []
        for start in range(0, len(components), 6):
            chunk = components[start:start + 6]
            number = start // 6 + 1
            add('components', {
                'title': 'مكونات المشروع' + (f' — {number}' if len(components) > 6 else ''),
                'type': 'content', 'design_style': 'table', 'content_density': 'high',
                'requires_image': False, 'content_source': f'project_components:{start}:{start + len(chunk)}',
                'bullets': [],
            })

    phases = parse_timeline_phases(source)
    if phases and not groups.get('timeline'):
        add('timeline', {
            'title': 'الجدول الزمني ومراحل التطوير', 'type': 'content',
            'design_style': 'timeline', 'content_density': 'high', 'requires_image': False,
            'content_source': 'timeline_table_data', 'bullets': [],
        })

    model = _parse_financial_dict(source.get('financial_study_model'))
    if financial_study_has_real_input(model, _parse_financial_dict(source.get('financial_calc_data'))):
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        report_parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        groups['financial'] = []
        if report_parts:
            heading = 'الدراسة المالية'
            subheading = ''
            for part_index, part in enumerate(report_parts):
                if not isinstance(part, dict):
                    continue
                if part.get('type') == 'heading':
                    text = str(part.get('text') or '').strip()
                    if part.get('level') == 3:
                        subheading = text
                    else:
                        heading = text or heading
                        subheading = ''
                    continue
                rows = part.get('rows') if isinstance(part.get('rows'), list) else []
                rows = _filter_substantive_financial_rows(rows, part.get('type'))
                if not rows:
                    continue
                part_title = subheading or heading
                if part.get('type') == 'fields' and any(name in part_title for name in (
                        'التكاليف والاستثمار', 'مؤشرات العائد والاسترداد')):
                    continue
                target_section = 'components' if 'مكونات المشروع' in heading else 'financial'
                if target_section == 'components':
                    continue
                column_ranges = _financial_column_ranges(part) if part.get('type') == 'table' else [(None, None)]
                row_ranges = _balanced_row_ranges(len(rows), max_per_slide=12, min_per_slide=4)
                for row_number, (start, end) in enumerate(row_ranges, 1):
                    for column_number, (column_start, column_end) in enumerate(column_ranges, 1):
                        title_suffixes = []
                        if len(row_ranges) > 1:
                            title_suffixes.append(str(row_number))
                        if len(column_ranges) > 1:
                            title_suffixes.append(f'جزء {column_number}')
                        chart_cand = _financial_chart_type(part_title, index=part_index)
                        chartable = (len(column_ranges) == 1 and start == 0 and column_number == 1
                                     and part.get('type') == 'table'
                                     and bool(chart_cand)
                                     and _financial_table_chartable(
                                         part, rows[start:end], column_start, column_end))
                        source_suffix = (f':{column_start}:{column_end}'
                                         if column_start is not None and column_end is not None else '')
                        add(target_section, {
                            'title': part_title + (f" — {' / '.join(title_suffixes)}" if title_suffixes else ''),
                            'type': 'content', 'design_style': 'chart' if chartable else 'table',
                            'chart_type': chart_cand if chartable else '',
                            'content_density': 'high', 'requires_image': False,
                            'content_source': f'financial_report:{part_index}:{start}:{end}{source_suffix}',
                            'source_table': f'report_part_{part_index}', 'row_count': end - start,
                            'financial_template': 'report', 'bullets': [],
                        })
        else:
            for table_key, title, style in _FINANCIAL_PLAN_TABLES:
                rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
                row_ranges = _balanced_row_ranges(len(rows), max_per_slide=12, min_per_slide=4)
                for number, (start, end) in enumerate(row_ranges, 1):
                    is_chart = (style == 'chart' and start == 0)
                    c_type = _financial_chart_type(title, table_key, number - 1) if is_chart else ''
                    add('financial', {
                        'title': title + (f' — {number}' if len(row_ranges) > 1 else ''),
                        'type': 'content', 'design_style': 'chart' if c_type else ('table' if style == 'chart' else style),
                        'chart_type': c_type,
                        'content_density': 'high', 'requires_image': False,
                        'content_source': f'financial_table:{table_key}:{start}:{end}',
                        'source_table': table_key, 'row_count': end - start,
                        'financial_template': 'report', 'bullets': [],
                    })
        for summary_slide in _financial_summary_plan_slides(model):
            add('financial', summary_slide)

    team_entries = _selected_team_entries(source, tenant_id)
    if team_entries:
        groups['team'] = []
        for index, entry in enumerate(team_entries, 1):
            bullets = [str(entry.get(key) or '').strip() for key in ('الدور', 'نبذة', 'سنوات الخبرة', 'أعمال سابقة')]
            add('team', {
                'title': str(entry.get('الجهة') or f'الجهة {index}').strip(),
                'type': 'content', 'design_style': 'image' if entry.get('_logo_file_id') else 'text',
                'content_density': 'medium', 'requires_image': bool(entry.get('_logo_file_id')),
                'content_source': f'team_member:{index}',
                'image_tokens': [f'##TEAM_LOGO_{index}##'] if entry.get('_logo_file_id') else [],
                'bullets': [value for value in bullets if value],
            })

    market = _decode_json_fact(source.get('market_study_data'))
    market = market if isinstance(market, dict) else {}
    competitors = market.get('competitors') if isinstance(market.get('competitors'), list) else []
    valid_competitors = [
        c for c in competitors
        if isinstance(c, dict) and (c.get('price_value') or c.get('price_from') or c.get('price_to') or c.get('price'))
    ]
    if valid_competitors:
        existing_comp = next((s for s in groups.get('market', [])
                              if s.get('content_source') == 'market_study_data.competitors'
                              or re.search(r'منافس', str(s.get('title') or ''))), None)
        if existing_comp:
            existing_comp.update({
                'title': 'مقارنة المنافسين',
                'type': 'content',
                'design_style': 'chart',
                'chart_type': 'horizontal_bar',
                'content_source': 'market_study_data.competitors',
                'source_table': 'competitors',
            })
        else:
            add('market', {
                'title': 'مقارنة المنافسين',
                'type': 'content',
                'design_style': 'chart',
                'chart_type': 'horizontal_bar',
                'content_density': 'high',
                'requires_image': False,
                'content_source': 'market_study_data.competitors',
                'source_table': 'competitors',
                'bullets': [],
            })
    swot = market.get('swot') if isinstance(market.get('swot'), dict) else {}
    groups['swot_risks'] = []
    if any(str(value or '').strip() for value in swot.values()):
        add('swot_risks', {
            'title': 'تحليل SWOT', 'type': 'content', 'design_style': 'swot',
            'content_density': 'high', 'requires_image': False,
            'content_source': 'market_study_data.swot', 'bullets': [],
        })
    executive = _decode_json_fact(source.get('executive_content'))
    executive = executive if isinstance(executive, dict) else {}
    if str(executive.get('summary') or '').strip():
        existing_summary = groups.get('executive_summary', [])[:1]
        groups['executive_summary'] = []
        summary_slide = dict(existing_summary[0]) if existing_summary else {}
        summary_slide.update({
            'title': 'الملخص التنفيذي', 'type': 'content', 'design_style': 'map' if overview_map_tokens else 'text',
            'content_density': 'high', 'requires_image': bool(overview_map_tokens),
            'content_source': 'executive_content.summary', 'image_tokens': overview_map_tokens, 'bullets': [],
        })
        add('executive_summary', summary_slide)

    summaries = (
        ('land', 'ملخص تحليل الأرض', 'land_and_building_summary', str(source.get('land_and_building_summary') or '').strip()),
        ('location', 'ملخص الموقع الجغرافي', 'site_analysis', str(source.get('site_analysis') or '').strip()),
        ('market', 'ملخص تحليل السوق', 'market_study_data.one_block_summary', str(market.get('one_block_summary') or '').strip()),
    )
    for section_key, title, content_source, value in summaries:
        if not value:
            continue
        existing = next((slide for slide in groups.get(section_key, [])
                         if slide.get('content_source') == content_source or 'ملخص' in str(slide.get('title') or '')), None)
        summary_tokens = overview_map_tokens if section_key == 'location' else []
        summary_style = 'map' if summary_tokens else 'text'
        if existing:
            groups[section_key].remove(existing)
            existing.update({'title': title, 'content_source': content_source,
                             'design_style': summary_style, 'section_key': section_key,
                             'requires_image': bool(summary_tokens), 'image_tokens': summary_tokens})
            groups[section_key].append(existing)
        else:
            add(section_key, {
                'title': title, 'type': 'content', 'design_style': summary_style,
                'content_density': 'medium', 'requires_image': bool(summary_tokens),
                'content_source': content_source, 'image_tokens': summary_tokens, 'bullets': [],
            })

    _merge_sparse_plan_slides(groups)
    _limit_presentation_charts(groups)
    _deduplicate_plan_media(groups)

    land_keys = ('croquis_land_area', 'approved_financial_area', 'boundary_lengths',
                 'surrounding_streets', 'facades_count', 'facades_directions',
                 'building_ratio_coverage', 'setbacks', 'max_floors_height',
                 'allowed_uses', 'regulatory_constraints', 'land_and_building_summary')
    location_keys = ('location_address', 'location_lat', 'location_lng', 'city', 'district',
                     'main_roads', 'nearby_landmarks', 'city_landmarks',
                     'catchment_areas', 'site_analysis')
    has_interior = any(_available_asset_items(component.get('images'))
                       for component in interior_components if isinstance(component, dict))
    map_placeholders = images.get('map_placeholders') if isinstance(images.get('map_placeholders'), dict) else {}
    has_location = (any(str(source.get(key) or '').strip() for key in location_keys)
                    or any(map_placeholders.values()))
    availability = {
        'overview': bool(source),
        'components': bool(components),
        'land': bool(land_items or any(str(source.get(key) or '').strip() for key in land_keys)),
        'location': bool(has_location),
        'market': bool(_readable_fact(market)),
        'timeline': bool(phases),
        'financial': financial_study_has_real_input(model, _parse_financial_dict(source.get('financial_calc_data'))),
        'swot_risks': bool(any(str(value or '').strip() for value in swot.values())),
        'team': bool(team_entries),
        'plans': bool(plans),
        'exterior': bool(moodboard_items),
        'interior': has_interior,
        'executive_summary': bool(str(executive.get('summary') or '').strip()),
    }
    for section_key, available in availability.items():
        if not available:
            groups[section_key] = []


def refresh_index_entries(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    entries = []
    seen = set()
    for page, slide in enumerate(plan['slides'], 1):
        if not isinstance(slide, dict):
            continue
        section_key = _slide_section_key(slide)
        if slide.get('type') == 'section_divider' or section_key == 'closing':
            if section_key in seen:
                continue
            seen.add(section_key)
            entries.append({'section_key': section_key,
                            'title': PRESENTATION_SECTION_TITLES[section_key], 'page': page})
    for slide in plan['slides']:
        if isinstance(slide, dict) and slide.get('type') == 'index':
            slide['title'] = 'محتويات العرض'
            slide['design_style'] = 'text'
            slide['index_entries'] = entries
            slide['bullets'] = []
            break
    plan['proposed_count'] = len(plan['slides'])
    return plan


def filter_presentation_plan_sections(plan, section_keys):
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return None
    requested = {
        _SECTION_KEY_ALIASES.get(str(key or '').strip().lower(), str(key or '').strip().lower())
        for key in (section_keys or [])
    }
    requested.intersection_update(PRESENTATION_SECTION_ORDER)
    if not requested:
        return None

    slides = [slide for slide in plan['slides'] if isinstance(slide, dict)]
    cover = next((slide for slide in slides if slide.get('type') == 'cover'), None)
    index = next((slide for slide in slides if slide.get('type') == 'index'), None)
    closing = next((slide for slide in reversed(slides) if slide.get('type') == 'closing'), None)
    body = [
        slide for slide in slides
        if slide.get('type') not in ('cover', 'index', 'closing')
        and _slide_section_key(slide) in requested
    ]
    if not body and not ('closing' in requested and closing):
        return None

    selected = []
    if cover:
        selected.append(cover)
    if index:
        selected.append(index)
    selected.extend(body)
    if closing:
        selected.append(closing)
    filtered = dict(plan)
    filtered['slides'] = selected
    return refresh_index_entries(filtered)


def normalize_presentation_plan(plan, project_data=None, images=None, tenant_id=None):
    if not isinstance(plan, dict):
        plan = {}
    source_slides = plan.get('slides') if isinstance(plan.get('slides'), list) else []
    source_slides = [_canonicalize_slide_image_tokens(dict(slide))
                     for slide in source_slides if isinstance(slide, dict)]
    cover = next((slide for slide in source_slides if slide.get('type') == 'cover'), None)
    if cover is None and source_slides:
        cover = source_slides[0]
    cover = dict(cover or {})
    cover.update({'title': 'الغلاف', 'type': 'cover', 'section_key': 'cover',
                  'design_style': 'image', 'requires_image': True})
    index = next((slide for slide in source_slides if slide.get('type') == 'index'), None)
    index = dict(index or {})
    index.update({'title': 'محتويات العرض', 'type': 'index', 'section_key': 'index',
                  'design_style': 'text', 'requires_image': False, 'bullets': []})
    closing = next((slide for slide in reversed(source_slides) if slide.get('type') == 'closing'), None)
    if closing is None and source_slides:
        closing = source_slides[-1]
    closing = dict(closing or {})
    has_cover_image = bool((images or {}).get('cover')) if isinstance(images, dict) else False
    closing.update({'title': PRESENTATION_SECTION_TITLES['closing'], 'type': 'closing',
                    'section_key': 'closing', 'design_style': 'image' if has_cover_image else 'minimal',
                    'requires_image': has_cover_image, 'content_source': 'contact_closing',
                    'image_tokens': ['##IMAGE_COVER##'] if has_cover_image else [], 'bullets': []})

    groups = {key: [] for key in PRESENTATION_SECTION_ORDER if key != 'closing'}
    signatures = set()
    current = ''
    for slide in source_slides:
        slide_type = str(slide.get('type') or 'content')
        if slide is cover or slide is index or slide is closing or slide_type in ('cover', 'index', 'closing'):
            continue
        section_key = _slide_section_key(slide, current)
        if slide_type == 'section_divider':
            current = section_key
            continue
        current = section_key
        if section_key == 'closing':
            continue
        item = dict(slide)
        item['section_key'] = section_key
        if item.get('type') == 'moodboard':
            if not _available_asset_items((images or {}).get('moodboard') if isinstance(images, dict) else []):
                continue
            item['type'] = 'content'
            item['design_style'] = 'image'
        signature = (section_key,) + _plan_slide_signature(item)
        if signature in signatures:
            continue
        signatures.add(signature)
        groups.setdefault(section_key, []).append(item)

    _ensure_required_plan_content(groups, project_data, images, tenant_id)
    _drop_redundant_generic_slides(groups)

    if not any(groups.values()) and project_data:
        groups['overview'].append({
            'title': PRESENTATION_SECTION_TITLES['overview'], 'type': 'content',
            'section_key': 'overview', 'design_style': 'text', 'content_density': 'medium',
            'requires_image': False,
            'bullets': ['تعريف المشروع من البيانات المعتمدة', 'الفكرة والاستخدامات المعتمدة',
                        'ملخص موجز دون تكرار'],
        })

    slides = [cover, index]
    for section_key in PRESENTATION_SECTION_ORDER:
        if section_key == 'closing' or not groups.get(section_key):
            continue
        slides.append({
            'title': PRESENTATION_SECTION_TITLES[section_key], 'type': 'section_divider',
            'section_key': section_key, 'design_style': 'divider', 'content_density': 'low',
            'requires_image': True, 'bullets': [],
        })
        slides.extend(groups[section_key])
    slides.append(closing)
    normalized = dict(plan)
    normalized['slides'] = slides
    return refresh_index_entries(normalized)


def _suggest_design_style(title, bullets=None, slide_type='content'):
    """Pick a varied design style from the title, bullets, and slide type."""
    title = (title or '').lower()
    bullets_text = ' '.join(b or '' for b in (bullets or [])).lower()
    text = f"{title} {bullets_text}"

    fixed = {
        'cover': 'image',
        'index': 'text',
        'section_divider': 'divider',
        'moodboard': 'image',
        'closing': 'minimal',
    }
    if slide_type in fixed:
        return fixed[slide_type]
    if slide_type.startswith('map_') or slide_type == 'site_specs':
        return 'map'

    if re.search(r'(?:مؤشر|أداء|قيمة مضافة|عائد|roi|noi|ربح|تكلفة|مالي|جدوى|إيراد|نسبة|رقم|إحصائية|تكلفة|دخل|استثمار|profit|cost|financial|revenue)', text):
        if re.search(r'(?:توزيع|مساحات|حصص|نسب الاستخدام|مصادر التمويل|pie|donut)', text):
            return 'pie'
        if re.search(r'(?:حساسية|سيناريو|نطاق|مخاطر العائد|candlestick)', text):
            return 'candlestick'
        if re.search(r'(?:سحب|سداد|تدفق نقدي|قنوات|pipeline|flow)', text):
            return 'flow'
        return 'dashboard'
    if re.search(r'(?:توزيع الوحدات|فئات المساحات|مدرج تكراري|histogram)', text):
        return 'histogram'
    if re.search(r'(?:انتشار|علاقة|مقارنة السوق|scatter)', text):
        return 'scatter'
    if re.search(r'(?:وحدات|مساحات|مواصفات|جدول|مقارنة|أنواع|تفاصيل|مكونات|قائمة|بيانات|units|areas|specs|table|components|details|list|data)', text):
        return 'table'
    if re.search(r'(?:خطة|زمن|جدول|مراحل|تنفيذ|تطوير|خطوات|مدة|timeline|schedule|phases|plan|stages|duration)', text):
        return 'timeline'
    if re.search(r'(?:موقع|خريطة|وصول|معالم|محيط|منطقة|location|map|access|landmarks|area|surrounding)', text):
        return 'map'
    if re.search(r'(?:swot|قوة|ضعف|فرص|تحديات|منافسة|مزايا تنافسية|مخاطر|strength|weakness|opportunities|threats|competitive)', text):
        return 'swot'
    if re.search(r'(?:عملية|تدفق|خطوات|عملاء|رحلة|عمل|process|flow|customer journey|steps)', text):
        return 'flow'
    if re.search(r'(?:مخطط اتجاهي|حدود الأرض|اتجاهي|أبعاد الأرض|diagram|boundary)', text):
        return 'diagram'
    if re.search(r'(?:صورة|واجهة|تصميم معماري|انطباع|visual|image|facade|architectural|render)', text):
        return 'image'
    if re.search(r'(?:نظرة|نبذة|مقدمة|شرح|وصف|ملخص|تعريف|رؤية|رسالة|فلسفة|overview|introduction|description|summary|vision|mission)', text):
        return 'text'
    return 'text'


def _maybe_map_slide_type(title, project_data):
    """If a content slide title matches a map topic and location data exists, return a map type."""
    if not project_data:
        return None
    has_location = (
        bool(project_data.get('location_lat') and project_data.get('location_lng'))
        or bool(project_data.get('location_address'))
    )
    if not has_location:
        return None
    t = (title or '').lower()
    if re.search(r'(?:موقع المشروع|الموقع|موقع)', t):
        return 'map_overview'
    if re.search(r'(?:معالم|محيط|القرب|المسافات|landmarks)', t):
        return 'map_landmarks'
    if re.search(r'(?:وصول|طرق|مداخل|access|roads)', t):
        return 'map_access'
    if re.search(r'(?:نطاق|catchment|دوائر)', t):
        return 'map_catchment'
    if re.search(r'(?:خصائص|مواصفات|site specs)', t):
        return 'site_specs'
    return None


TIMELINE_QUARTERS = ('Q1', 'Q2', 'Q3', 'Q4')


def compute_timeline_end(year, quarter, duration):
    """Return the inclusive end year/quarter from a start quarter and duration in months."""
    try:
        start_year = int(year)
        quarter_index = TIMELINE_QUARTERS.index(str(quarter or '').strip())
        months = int(duration)
    except (TypeError, ValueError):
        return None
    if months <= 0:
        return None
    end_month = start_year * 12 + quarter_index * 3 + months - 1
    return {
        'year': str(end_month // 12),
        'quarter': TIMELINE_QUARTERS[(end_month % 12) // 3],
    }


def parse_timeline_phases(project_data):
    """Return named timeline phases from the draft table, including notes."""
    source = project_data if isinstance(project_data, dict) else {}
    raw = source.get('timeline_table_data')
    if raw in (None, '', []):
        raw = source.get('timelineRows')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    if not isinstance(raw, list):
        return []
    phases = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            continue
        year = str(item.get('year') or '').strip()
        quarter = str(item.get('quarter') or '').strip()
        duration = str(item.get('duration') or '').strip()
        end_year = str(item.get('endYear') or '').strip()
        end_quarter = str(item.get('endQuarter') or '').strip()
        if not end_year or not end_quarter:
            computed = compute_timeline_end(year, quarter, duration)
            if computed:
                end_year = end_year or computed['year']
                end_quarter = end_quarter or computed['quarter']
        phases.append({
            'name': name,
            'year': year,
            'quarter': quarter,
            'duration': duration,
            'endYear': end_year,
            'endQuarter': end_quarter,
            'notes': str(item.get('notes') or '').strip(),
        })
    return phases


def format_timeline_phase_line(phase):
    start = ' '.join(part for part in (phase.get('year'), phase.get('quarter')) if part)
    end = ' '.join(part for part in (phase.get('endYear'), phase.get('endQuarter')) if part)
    span = f'{start} إلى {end}' if start and end else (start or end)
    duration = phase.get('duration')
    duration_text = f' لمدة {duration} شهر' if duration else ''
    notes = phase.get('notes')
    notes_text = f' — {notes}' if notes else ''
    detail = f'{span}{duration_text}' if span or duration_text else ''
    return f"{phase['name']}: {detail}{notes_text}".strip(': ').strip()


def _timeline_data_note(project_data):
    """Keep the phase table, including notes, outside the truncated project JSON."""
    phases = parse_timeline_phases(project_data)
    if not phases:
        return ''
    return (
        "\n\n## الجدول الزمني للمشروع — إلزامي في شريحة الجدول الزمني\n"
        "هذه المراحل مصدر الحقيقة. اعرض كل مرحلة مع بدايتها ومدتها ونهايتها المحسوبة.\n"
        "إذا وُجدت ملاحظة لمرحلة فاعرضها تحتها أو بجانبها دون حذف أو اختصار. إذا كانت الملاحظة فارغة فلا تعرض عنوانًا أو حقلًا أو مساحة للملاحظات في تلك المرحلة.\n"
        + '\n'.join(f'- {format_timeline_phase_line(phase)}' for phase in phases)
    )


# The system never produces photographs of the streets around a site: the Street View fetch is
# not part of any workflow the user can run, and the visual-concept board holds renders of the
# project itself, not its surroundings. The rules used to advertise ##STREET_VIEW_1..4## anyway,
# the model built a four-card «قراءة بصرية للموقع» slide out of them, and the unresolved tokens
# were blanked — the slide shipped as four empty frames. Say it, do not imply it.
NO_STREET_VIEW_RULE = (
    "ممنوع نهائياً: لا توجد صور فوتوغرافية للشوارع أو للموقع أو لمحيط الأرض، ولا تُولَّد من الخرائط "
    "ولا من التصور البصري. لا تكتب ##STREET_VIEW_1## أو أي رمز مشابه، ولا تنشئ شريحة صور موقع أو "
    "«قراءة بصرية للمحيط» أو بطاقات صور للواجهات المحيطة. الصور المتوفرة هي المذكورة في «الصور "
    "المتوفرة» فقط، والموقع يُعرض بالخرائط والبيانات لا بالصور."
)


def _location_data_note(project_data):
    """Build an extra prompt note when map/location data is present."""
    if not project_data:
        return ''
    has_location = (
        bool(project_data.get('location_lat') and project_data.get('location_lng'))
        or bool(project_data.get('location_address'))
    )
    if not has_location:
        return ''
    parts = []
    if project_data.get('location_lat') and project_data.get('location_lng'):
        parts.append('إحداثيات الموقع متاحة.')
    if project_data.get('location_address'):
        parts.append(f"عنوان الموقع: {project_data.get('location_address')}")
    if project_data.get('landmarks_matrix'):
        parts.append('بيانات المعالم المحيطة متاحة.')
    if project_data.get('main_roads'):
        parts.append('بيانات الطرق الرئيسية متاحة.')
    if project_data.get('catchment_areas'):
        parts.append('بيانات نطاق التأثير متاحة.')
    if not parts:
        return ''
    return (
        "\n\n## بيانات الموقع/الخرائط المتاحة — يجب استخدامها\n"
        + '\n'.join(f'- {p}' for p in parts)
        + "\n\n"
        "الزامياً: أضف الشرائح التالية بعد الفهرس إن وُجدت البيانات المطلوبة:\n"
        "- map_overview (يتطلب إحداثيات)\n"
        "- map_landmarks (يتطلب landmarks_matrix)\n"
        "- map_access (يتطلب main_roads)\n"
        "- site_specs (يتطلب بيانات الموقع)\n"
        "- map_catchment (يتطلب catchment_areas)\n"
        "استخدم placeholders ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##\n"
        + NO_STREET_VIEW_RULE
    )


def _parse_financial_dict(val):
    """Safely parse a JSON string or return dict."""
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val.strip().startswith('{'):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _financial_number(value):
    """A stored financial value as a number; text such as "18%" or "1,200" still counts."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r'[^\d.\-]', '', str(value or ''))
    try:
        return float(text)
    except ValueError:
        return 0.0


def financial_study_has_real_input(model, calc=None):
    """True only when someone actually entered figures in the financial study.

    The financial section is rendered for every project and `collectFinancialStudyModel()` snapshots
    every one of its controls plus the computed projection, so an untouched project still carries a
    ~35KB model of markup defaults and zeros. Sending that made the prompt state that zero-value
    tables were "الجداول المالية المعتمدة", which is worse than saying nothing.
    """
    model = _parse_financial_dict(model)
    calc = _parse_financial_dict(calc)
    dynamic_rows = model.get('dynamicRows') if isinstance(model.get('dynamicRows'), dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    row_sets = list(dynamic_rows.values()) + list(tables.values()) + [calc.get('components')]
    for rows in row_sets:
        if isinstance(rows, list) and any(isinstance(row, dict) and any(
                str(value or '').strip() for value in row.values()) for row in rows):
            return True
    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
    # Rates, durations and counts carry markup defaults, so only the money and area figures
    # distinguish an entered study from an untouched one.
    for key in ('projectCost', 'adjustedProjectCost', 'landValue', 'manualLandValue',
                'equityRequired', 'facilityAmount', 'totalBuiltUpArea', 'builtUpAreaAbove',
                'basementArea', 'landArea', 'totalRevenue', 'netProfit'):
        if _financial_number(inputs.get(key) or projection.get(key) or calc.get(key)) > 0:
            return True
    return False


# Saying nothing about an empty financial study is not neutral: the model treats the gap as
# something to fill, which is where invented costs and returns came from. The absence is stated.
FINANCIAL_ABSENT_NOTE = (
    "\n\n## الدراسة المالية غير مُدخلة في هذا الملف"
    "\n- لا توجد أي أرقام مالية: لا تكلفة ولا قيمة أرض ولا رأس مال ولا تمويل ولا إيرادات ولا عائد"
    " ولا مؤشرات ولا مساحات مبنية ولا جداول."
    "\n- ممنوع إنشاء شريحة مالية أو شريحة مؤشرات أو رسم بياني مالي أو جدول أرقام."
    "\n- ممنوع ذكر أي رقم أو نسبة أو عائد أو تكلفة في أي شريحة أخرى، ولو كتقدير أو مدى أو مثال"
    " أو من معرفة عامة عن السوق."
)

# A financial title in a plan that has no financial data can only be filled by inventing numbers.
FINANCIAL_SLIDE_TITLE_RE = re.compile(
    r'(?:مالي|ماليّ|تكلفة|تكاليف|إيراد|ايراد|عائد|عوائد|ربح|أرباح|جدوى|ميزانية|تمويل|استثمار|'
    r'مؤشرات|مؤشر|قيمة مضافة|هيكل رأس المال|روي|financial|cost|revenue|profit|roi|irr|noi|'
    r'budget|feasibility|metrics|dashboard)'
)


def project_has_financial_study(project_data):
    """True when this project file carries entered financial figures."""
    source = project_data if isinstance(project_data, dict) else {}
    return financial_study_has_real_input(source.get('financial_study_model'),
                                         source.get('financial_calc_data'))


def strip_street_view_slides(plan):
    """Drop a site-photos slide from a plan: there are no photographs of the site to put in it.

    The type is gone from the prompt, but an older draft can still carry a plan that has one, and a
    model can still guess the name. Left in, it becomes a slide of empty image frames.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    kept = [slide for slide in plan['slides']
            if not (isinstance(slide, dict) and slide.get('type') == 'site_photos')]
    if len(kept) != len(plan['slides']):
        print(f"[SLIDE-PLAN] dropped {len(plan['slides']) - len(kept)} site_photos slide(s): no site photographs exist")
        plan['slides'] = kept
        plan['proposed_count'] = len(kept)
    return plan


def strip_financial_slides(plan, project_data):
    """Drop financial slides from a plan for a project that has no financial study.

    The planner, the fallback plan and the minimum-count padding all offer titles such as
    «التحليل المالي والجدوى» and «مؤشرات الأداء والقيمة المضافة», and a slide with that title and no
    figures behind it can only be written by inventing them.
    """
    if not isinstance(plan, dict) or project_has_financial_study(project_data):
        return plan
    slides = plan.get('slides') if isinstance(plan.get('slides'), list) else []
    kept = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        text = f"{slide.get('title') or ''} {' '.join(str(b or '') for b in (slide.get('bullets') or []))}"
        financial = (slide.get('design_style') == 'dashboard'
                     or slide.get('content_source') == 'financial'
                     or bool(FINANCIAL_SLIDE_TITLE_RE.search(text.lower())))
        if financial and slide.get('type') not in ('cover', 'index', 'moodboard', 'closing'):
            print(f"[SLIDE-PLAN] Dropped financial slide «{slide.get('title')}»: no financial study entered")
            continue
        kept.append(slide)
    plan['slides'] = kept
    plan['proposed_count'] = len(kept)
    return plan


_FINANCIAL_INDICATOR_LABELS = (
    ('projectCost', 'إجمالي تكلفة المشروع'),
    ('projectCostWithFinance', 'التكلفة شاملة التمويل'),
    ('adjustedProjectCost', 'إجمالي تكلفة الاستثمار'),
    ('developerCost', 'أتعاب المطور'),
    ('landValue', 'قيمة الأرض'),
    ('landRent', 'إيجار الأرض السنوي'),
    ('saleRevenueTotal', 'إجمالي إيرادات البيع'),
    ('revenueY1', 'إيرادات السنة الأولى'),
    ('opexY1', 'مصروفات السنة الأولى'),
    ('noiY1', 'NOI — السنة الأولى'),
    ('fullOccupancyRevenue', 'الإيرادات عند الإشغال المستهدف'),
    ('fullOccupancyNOI', 'NOI عند الإشغال المستهدف'),
    ('totalGraceDiscount', 'إجمالي خصم فترة السماح'),
    ('facilityAmount', 'قيمة التسهيل التمويلي'),
    ('arrangementFee', 'رسوم ترتيب التمويل'),
    ('totalFinanceInterest', 'إجمالي فوائد التمويل'),
    ('totalFinanceCost', 'إجمالي كلفة التمويل'),
    ('totalFundFees', 'إجمالي أتعاب الصندوق'),
    ('saleExitValue', 'صافي التخارج البيعي'),
    ('operatingExitValue', 'صافي التخارج التشغيلي'),
    ('terminal', 'إجمالي قيمة التخارج'),
    ('landEquityContribution', 'مساهمة الأرض العينية'),
    ('totalCashEquity', 'حقوق الملكية النقدية'),
    ('totalEquityRequired', 'إجمالي حقوق الملكية المطلوبة'),
    ('totalEquityDistributions', 'إجمالي التوزيعات'),
    ('roi', 'ROI'),
    ('projectIrr', 'Project IRR'),
    ('equityIrr', 'Equity IRR'),
    ('payback', 'فترة استرداد رأس المال'),
    ('equityPayback', 'فترة استرداد حقوق الملكية'),
    ('totalBuiltUpArea', 'إجمالي المساحات المبنية م²'),
    ('developmentYears', 'مدة التطوير (سنوات)'),
)

_FINANCIAL_TABLE_TITLES = {
    'componentsTable': 'مكونات المشروع',
    **{key: title for key, title, _style in _FINANCIAL_PLAN_TABLES},
}


def _financial_data_note(project_data):
    """Extract and format financial study tables and metrics so they are never lost or distorted."""
    if not project_data or not isinstance(project_data, dict):
        return ''
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    calc = _parse_financial_dict(project_data.get('financial_calc_data'))
    if not financial_study_has_real_input(model, calc):
        return FINANCIAL_ABSENT_NOTE

    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    report = model.get('report') if isinstance(model.get('report'), dict) else {}
    report_parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    lines = [
        "\n\n## الدراسة المالية المعتمدة — نفس محتوى تقرير PDF",
        "- اعرض جميع الأقسام والجداول والمؤشرات الموجودة أدناه، وبالترتيب والمسميات والقيم والوحدات نفسها. لا تختصر الدراسة في لوحة مؤشرات واحدة.",
        "- أضف فواصل الآلاف بصرياً فقط من دون تقريب أو تحويل إلى ألف أو مليون أو تغيير عدد الخانات العشرية.",
        "- لا تغيّر أسماء المؤشرات، وبخاصة ROI وProject IRR وEquity IRR وNOI، ولا تستبدلها بتسميات جديدة.",
        "- لا تحذف صفاً أو عموداً أو سنة. قسّم الجدول على صفحات إضافية عند الحاجة، ولا تعِد عرض مكونات المشروع خارج قسمها المخصص.",
        "- عند وجود قيم قابلة للمقارنة أضف رسماً بيانياً بألوان الهوية، مع جدول القيم الأصلي الكامل بجانبه.",
        "- الرقم أو المؤشر غير الموجود لا يُكتب، ولا يُقدّر، ولا يُعاد حسابه أو اشتقاقه.",
    ]

    if report_parts:
        lines.append("\n### نسخة الشاشة المعتمدة بالترتيب والمسميات الظاهرة للمستخدم:")
        lines.append(json.dumps(report_parts, ensure_ascii=False, indent=2))
        return '\n'.join(lines)

    indicators = {}
    for key, label in _FINANCIAL_INDICATOR_LABELS:
        value = projection.get(key)
        if value in (None, '', [], {}) and inputs.get(key) not in (None, '', [], {}):
            value = inputs.get(key)
        if value in (None, '', [], {}) and calc.get(key) not in (None, '', [], {}):
            value = calc.get(key)
        if value not in (None, '', [], {}, -1):
            indicators[label] = value
    if indicators:
        lines.append("\n### المؤشرات المالية بمسمياتها الأصلية:")
        lines.append(json.dumps(indicators, ensure_ascii=False, indent=2))

    dynamic_rows = model.get('dynamicRows') if isinstance(model.get('dynamicRows'), dict) else {}
    components = dynamic_rows.get('components') if isinstance(dynamic_rows.get('components'), list) else []
    if components and not tables.get('componentsTable'):
        lines.append("\n### مكونات المشروع كما أُدخلت في الدراسة:")
        lines.append(json.dumps(components, ensure_ascii=False, indent=2))

    ordered_keys = list(_FINANCIAL_TABLE_TITLES)
    ordered_keys.extend(key for key in tables if key not in ordered_keys)
    for table_key in ordered_keys:
        rows = tables.get(table_key)
        if not isinstance(rows, list) or not rows:
            continue
        clean_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            cleaned = {key: value for key, value in row.items()
                       if key not in ('ترتيب / حذف', 'ترتيب', 'حذف', 'idx', 'id')}
            if any(str(value or '').strip() for value in cleaned.values()):
                clean_rows.append(cleaned)
        if clean_rows:
            title = _FINANCIAL_TABLE_TITLES.get(table_key, table_key)
            lines.append(f"\n### {title} ({len(clean_rows)} صفًا) — المفتاح {table_key}:")
            lines.append(json.dumps(clean_rows, ensure_ascii=False, indent=2))

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Project facts for the prompt
# ─────────────────────────────────────────────────────────────────────────────
#
# The payload of a real project file is ~230,000 characters. It used to be dumped as raw JSON and
# cut at 4,000 characters, so 98% of it never reached the model: the market study, the executive
# content, the team, and most of the location section were always beyond the cut, and which fields
# survived depended on the draft's key order. The model now receives every fact under an Arabic
# heading, with the noise removed instead of the facts.

# Sent to the model by another route, so repeating them here only burns context:
#   financial/timeline    -> _financial_data_note / _timeline_data_note
#   images                -> _get_images_info
#   landmark drive times  -> the landmarks matrix note
#   the slide plan        -> the user message
PROMPT_COVERED_ELSEWHERE = {
    'financial_study_model', 'financial_calc_data', 'project_components_data',
    'timeline_table_data', 'timelineRows',
    'tenantCreativeImages', 'visual_concept', 'tenantSlidePlan', 'slidePlan',
    'landmarks_matrix', 'nearby_landmarks_data', 'street_view_images', 'company_branding',
}

# The deck itself. Feeding a model the slides it produced last time invites it to copy them.
# `designerChat` is the editing conversation: it belongs to the chat, never to a slide prompt.
PROMPT_PREVIOUS_OUTPUT = {'tenantSlidesData', 'pageDrafts', 'slides', 'designerChat'}

# Machine artefacts of the land analysis and the map pipeline: the facts they produced are already
# in the visible land and location fields.
PROMPT_INTERNAL_KEYS = {
    'land_documents_analysis', 'land_documents_analysis_status', 'regulation_evidence',
    'regulation_coordinates', 'coordinate_tables', 'survey_coordinates', 'directions_table',
    'parcels', 'conflicts', 'warnings', 'extraction_diagnostics', 'document_processing',
    'land_document_processing', 'document_summary', 'source_priority',
    'location_polygon', 'location_polygon_source', 'location_coordinates_confirmed',
    'location_coordinates_source', 'refresh_maps', 'regen_seed', 'enabled_maps',
    'map_styles', 'map_type', 'north_direction', '_resolved_location',
    'draftId', 'draft_id', 'sectionStatuses', 'site_analysis_approved',
    'conceptual_plans', 'land_documents_files', 'land_photos', 'project_logo',
    'land_use_status',
    # Superseded by building_ratio_coverage / setbacks and allowed_uses; kept in drafts for
    # backwards compatibility only.
    'building_ratio_setbacks', 'allowed_uses_restrictions', 'secondary_roads',
}

PROMPT_SKIPPED_KEYS = PROMPT_COVERED_ELSEWHERE | PROMPT_PREVIOUS_OUTPUT | PROMPT_INTERNAL_KEYS
PROMPT_SKIPPED_SUFFIXES = ('_file_id', '_file_ids', '_file_meta')

# Facts with no PREBUILT_FIELDS entry, so they carry no label of their own.
EXTRA_FIELD_LABELS = {
    'site_analysis': 'تحليل الموقع',
    'location_detail': 'تفصيل الموقع',
    'land_use': 'استخدام الأرض',
    'zoning_code': 'كود التنظيم',
    'population_density': 'الكثافة السكانية',
    'population_density_source': 'مصدر الكثافة السكانية',
    'timeline_start_year': 'سنة بداية المشروع',
    'timeline_years': 'عدد سنوات المشروع',
}

# A single field cannot flood the brief, and the brief cannot flood the request.
FACT_VALUE_LIMIT = 6000
PROJECT_FACTS_LIMIT = 120000


def _field_label_map():
    """key -> (Arabic label, section key, sort order) for every prebuilt field."""
    labels = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            labels[key] = (field.get('label') or key,
                           field.get('section_key') or 'basic',
                           field.get('sort_order') or 0)
    return labels


def _readable_fact(value):
    """Render one stored value as text a writer can read."""
    if value is None or isinstance(value, bool):
        return '' if value is None else ('نعم' if value else '')
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('{') or text.startswith('['):
            decoded = _decode_json_fact(text)
            if decoded is not None:
                return _readable_fact(decoded)
        return text[:FACT_VALUE_LIMIT]
    if isinstance(value, dict):
        if len(value) == 1 and 'general' in value:
            return _readable_fact(value['general'])
        parts = []
        for key, item in value.items():
            text = _readable_fact(item)
            raw_label = str(key).split('::')[-1]
            label = USE_TYPE_LABELS.get(raw_label, INVESTMENT_MODEL_LABELS.get(raw_label, raw_label))
            if text:
                parts.append(f'{label}: {text}' if label != 'general' else text)
        return ' | '.join(parts)[:FACT_VALUE_LIMIT]
    if isinstance(value, (list, tuple)):
        parts = [_readable_fact(item) for item in value]
        parts = [part for part in parts if part]
        if not parts:
            return ''
        inline = '، '.join(parts)
        if len(inline) <= 200 and '\n' not in inline:
            return inline[:FACT_VALUE_LIMIT]
        return '\n'.join(f'  - {part}' for part in parts)[:FACT_VALUE_LIMIT]
    return str(value)[:FACT_VALUE_LIMIT]


def _decode_json_fact(value):
    """Sections are stored as JSON strings inside the draft, so they must be decoded first."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _market_study_facts(project_data):
    """The market study: the written summary, the competitor rows, SWOT and the decision."""
    state = _decode_json_fact(project_data.get('market_study_data'))
    if not isinstance(state, dict):
        return ''
    lines = []
    summary = str(state.get('one_block_summary') or '').strip()
    if summary:
        lines.append(summary)
    competitors = state.get('competitors') if isinstance(state.get('competitors'), list) else []
    rows = []
    for index, competitor in enumerate(competitors, 1):
        if not isinstance(competitor, dict):
            continue
        # Per-field source URLs are provenance for the study screen, not slide content.
        row = {key: value for key, value in competitor.items()
               if key not in ('id', 'field_sources', 'source_urls', 'row_source', 'logo_file_id',
                              'logo_path', 'logo_url', 'logo_source_url', 'conflict_warnings',
                              'logo_import_warning', 'price_cache', 'area_cache') and value not in (None, '', [])}
        if competitor.get('logo_file_id') or competitor.get('logo_path'):
            row['شعار المنافس'] = f'##COMPETITOR_LOGO_{index}##'
        if row:
            rows.append(row)
    if rows:
        lines.append('### المنافسون (أرقامهم كما هي، ممنوع تعديلها)')
        lines.append(json.dumps(rows, ensure_ascii=False, indent=2))
    for key, title in (('summary', 'محاور دراسة السوق'), ('swot', 'تحليل SWOT')):
        block = state.get(key)
        if isinstance(block, dict):
            filled = {k: v for k, v in block.items() if str(v or '').strip()}
            if filled and not (key == 'summary' and summary):
                lines.append(f'### {title}')
                lines.append(json.dumps(filled, ensure_ascii=False, indent=2))
    for key, title in (('decision', 'تصنيف القرار'), ('disclaimer', 'إخلاء المسؤولية')):
        text = str(state.get(key) or '').strip()
        if text:
            lines.append(f'{title}: {text}')
    if not lines:
        return ''
    return '### دراسة السوق\n' + '\n'.join(lines)


def _executive_content_facts(project_data):
    """The approved executive texts, each under its own Arabic label."""
    state = _decode_json_fact(project_data.get('executive_content'))
    if not isinstance(state, dict):
        return ''
    try:
        import executive_content
        blocks = [(item['key'], item['label']) for item in executive_content.BLOCKS]
    except Exception:
        blocks = [(key, key) for key in state]
    lines = []
    for key, label in blocks:
        text = str(state.get(key) or '').strip()
        if text:
            lines.append(f'#### {label}\n{text[:FACT_VALUE_LIMIT]}')
    if not lines:
        return ''
    return ('### المحتوى التنفيذي المعتمد (نصوص معتمدة — أعد صياغتها للشرائح ولا تخترع غيرها)\n'
            + '\n\n'.join(lines))


def _selected_team_entries(project_data, tenant_id=None):
    selection = _decode_json_fact((project_data or {}).get('team_selection'))
    selection = selection if isinstance(selection, dict) else {}
    excluded = set(selection.get('excluded') or [])
    overrides = selection.get('roles') if isinstance(selection.get('roles'), dict) else {}
    entries = []
    if tenant_id:
        try:
            library = db.get_team_entities(tenant_id) or []
        except Exception:
            library = []
        for entity in library:
            if entity.get('id') in excluded:
                continue
            entries.append({
                'الجهة': entity.get('name') or '',
                'الدور': overrides.get(entity.get('id')) or entity.get('role') or '',
                'نبذة': entity.get('brief') or '',
                'سنوات الخبرة': entity.get('experienceYears') or '',
                'أعمال سابقة': entity.get('notableProjects') or '',
                '_logo_file_id': entity.get('logoFileId') or '',
            })
    for local in selection.get('local') or []:
        if not isinstance(local, dict):
            continue
        entries.append({
            'الجهة': local.get('name') or '',
            'الدور': local.get('role') or '',
            'نبذة': local.get('brief') or '',
            'سنوات الخبرة': local.get('experienceYears') or '',
            'أعمال سابقة': local.get('notableProjects') or '',
            '_logo_file_id': local.get('logoFileId') or '',
        })
    return [{key: value for key, value in entry.items() if str(value or '').strip()}
            for entry in entries if str(entry.get('الجهة') or '').strip()]


def _team_facts(project_data, tenant_id=None):
    """The team actually chosen for this file: the company library minus exclusions, plus locals.

    The library lives in ``tenant_team_entities`` and the draft only stores ids, so without
    resolving it the prompt would carry no names at all.
    """
    entries = []
    for index, source in enumerate(_selected_team_entries(project_data, tenant_id), 1):
        entry = {key: value for key, value in source.items() if not key.startswith('_')}
        if source.get('_logo_file_id'):
            entry['الشعار'] = f'##TEAM_LOGO_{index}##'
        entries.append(entry)
    if not entries:
        return ''
    return '### فريق العمل (بنفس الترتيب والحقول، وشعار كل جهة إلزامي عند توفره)\n' + json.dumps(entries, ensure_ascii=False, indent=2)


def _contact_facts(project_data, tenant_id=None):
    source = project_data if isinstance(project_data, dict) else {}
    fields = (
        ('الاسم', ('contact_name', 'name')),
        ('المنصب', ('contact_position', 'position', 'job_title')),
        ('الهاتف', ('contact_phone', 'company_phone', 'phone', 'mobile')),
        ('البريد الإلكتروني', ('contact_email', 'company_email', 'email')),
        ('الموقع الإلكتروني', ('contact_website', 'company_website', 'website')),
        ('الموقع الجغرافي', ('contact_address', 'company_address', 'address')),
        ('السوشل ميديا', ('contact_social_media', 'social_media')),
    )
    values = {}
    for label, keys in fields:
        value = next((str(source.get(key) or '').strip() for key in keys if str(source.get(key) or '').strip()), '')
        if value:
            values[label] = value
    if not values:
        return ''
    return '### بيانات التواصل المعتمدة للخاتمة (انقل المتاح فقط كما هو)\n' + json.dumps(values, ensure_ascii=False, indent=2)


def build_project_facts(project_data, tenant_id=None):
    """Every collected fact, grouped by its section and labelled in Arabic.

    Replaces dumping the raw draft and cutting it at a character count.
    """
    if not isinstance(project_data, dict) or not project_data:
        return 'لا توجد بيانات مشروع.'
    labels = _field_label_map()
    section_titles = {item['key']: item['label']
                      for item in (getattr(db, 'FIELD_SECTIONS', []) or [])}
    grouped = {key: [] for key in section_titles}
    extra = []
    for key, value in project_data.items():
        if key in PROMPT_SKIPPED_KEYS or key.startswith('_'):
            continue
        if key.endswith(PROMPT_SKIPPED_SUFFIXES):
            continue
        if key in ('market_study_data', 'executive_content', 'team_selection'):
            continue
        text = _readable_fact(value)
        if not text:
            continue
        if key in labels:
            label, section, order = labels[key]
            grouped.setdefault(section, []).append((order, label, text))
        else:
            label = EXTRA_FIELD_LABELS.get(key)
            if not label and key.endswith('_other'):
                base = labels.get(key[:-6])
                label = f'{base[0]} (أخرى)' if base else None
            extra.append((label or key, text))

    blocks = []
    for section_key, title in section_titles.items():
        # Same order as the form, so the brief reads the way the client filled it.
        rows = sorted(grouped.get(section_key) or [], key=lambda row: row[0])
        if rows:
            blocks.append(f'### {title}\n'
                          + '\n'.join(f'- {label}: {text}' for _order, label, text in rows))
    if extra:
        blocks.append('### بيانات إضافية\n'
                      + '\n'.join(f'- {label}: {text}' for label, text in extra))
    for note in (_team_facts(project_data, tenant_id),
                 _market_study_facts(project_data),
                 _executive_content_facts(project_data),
                 _contact_facts(project_data, tenant_id)):
        if note:
            blocks.append(note)
    facts = '\n\n'.join(blocks) or 'لا توجد بيانات مشروع.'
    if len(facts) > PROJECT_FACTS_LIMIT:
        facts = facts[:PROJECT_FACTS_LIMIT] + '\n... [تم اختصار البيانات]'
    return facts


# ─────────────────────────────────────────────────────────────────────────────
# Slide Plan Proposal
# ─────────────────────────────────────────────────────────────────────────────

SLIDE_PLAN_PROMPT = """أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية الاستثمارية.

## بيانات المشروع
{project_json}

## المهمة
1. حلل كمية ونوع المحتوى المتاح في بيانات المشروع
2. اقترح عدد شرائح شامل وتفصيلي يبدأ من {min_slides} شريحة كحد أدنى، والحد الأعلى مفتوح ومرن تماماً حسب حجم المشروع وتفاصيله (مثل عدد المكونات الاستثمارية، المخططات، أبعاد السوق، الجداول المالية، إلخ) بحيث تعطي كل محور حقه الكامل دون اختصار أو حصر مصطنع.
3. وزع المحتوى بحيث:
   - لا توجد شريحة فارغة أو مزدحمة
   - كل شريحة لها فكرة واحدة واضحة ومصدر بيانات محدد
   - الجداول تبقى جداول كاملة، والأرقام القابلة للمقارنة تجمع بين جدول ورسم بياني
   - النبذات والملخصات نصوص واضحة وليست شبكات مربعات
   - الصور والمخططات كبيرة وواضحة، وتستخدم كل رموز الخطة بتوزيع متوازن من صورة إلى ثلاث صور

{distribution_rules}

## أنواع الشرائح المسموحة
- cover: شريحة الغلاف (1 فقط، في البداية)
- index: فهرس الأقسام مع أرقام صفحات بدايتها (1 فقط، بعد الغلاف)
- content: شريحة محتوى (عدد متغير)
- section_divider: صفحة بداية قسم تحمل الاسم العربي وحده بلا وصف أو ترجمة
- moodboard: صورة خارجية كبيرة؛ يمكن توزيع الصور على أكثر من صفحة داخل قسم التصورات الخارجية
- closing: الخاتمة وبيانات التواصل (1 فقط، في النهاية)
- map_overview: خريطة الموقع + المعالم المحيطة (يتطلب إحداثيات)
- map_landmarks: خريطة + جدول أوقات القيادة (يتطلب nearby_landmarks)
- map_access: خريطة الطرق + المداخل (يتطلب main_roads)
- map_catchment: خريطة نطاق التأثير + دوائر القيادة (يتطلب catchment_areas)
- site_specs: جدول خصائص الموقع (يتطلب location data)

## أنماط تصميم الشرائح (design_style)
- dashboard: مؤشرات رقمية محدودة بمسميات الدراسة الأصلية
- cards: بطاقتان أو ثلاث فقط لعناصر مستقلة قصيرة
- timeline: مراحل زمنية مع الملاحظات الموجودة فقط
- table: جدول بيانات كامل
- chart: رسم بياني محصور حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة مع جدول البيانات بجانبه (مقارنة المنافسين: horizontal_bar في دراسة السوق، وتكوين إجمالي تكلفة الاستثمار: waterfall، والتدفقات النقدية السنوية والتراكمية: combo، ومقارنة السيناريوهات المالية: heatmap في الدراسة المالية). أي نوع أو موقع آخر ممنوع منعاً باتاً
- text: فقرة أو قائمة منظمة للنبذات والملخصات
- image: صورة كبيرة + وصفها الصحيح
- flow: تسلسل نصي بسيط عند وجود خطوات فعلية
- swot: تحليل SWOT بألوان الهوية
- map: خريطة مع جدول أو ملخص دون تكرار البيانات

## تنبيه مهم
- اختر نوع الشريحة (`type`) ونمط التصميم (`design_style`) تلقائياً بناءً على بيانات المشروع وسياق التدريب الخاص بالشركة.
- لا تترك أي قرار لواجهة المستخدم بشأن النوع أو النمط.
- لا تطلب من المستخدم اختيار `type` أو `design_style` لاحقاً.

## أعد JSON فقط بالصيغة التالية:
{{
  "proposed_count": <عدد الشرائح الإجمالي>,
  "reasoning": "<سبب اختيار هذا العدد بالعربي>",
  "slides": [
    {{
      "title": "عنوان الشريحة بالعربي",
      "type": "cover|index|content|section_divider|moodboard|closing|map_overview|map_landmarks|map_access|map_catchment|site_specs",
      "section_key": "overview|components|land|location|market|timeline|financial|swot_risks|team|plans|exterior|interior|executive_summary|closing",
      "content_density": "low|medium|high",
      "design_style": "dashboard|cards|timeline|table|chart|text|image|flow|swot|map|diagram|divider",
      "chart_type": "horizontal_bar|waterfall|combo|heatmap أو فارغ",
      "bullets": ["نقطة 1", "نقطة 2", "نقطة 3"],
      "requires_image": true أو false,
      "content_source": "<الحقل أو الجدول الذي يغذي هذه الشريحة>",
      "image_tokens": ["<رموز الصور المتاحة لهذه الشريحة فقط>"]
    }}
  ]
}}

## قواعد إضافية:
- الشريحة الأولى غلاف، والثانية فهرس أقسام، والأخيرة خاتمة. لا يوجد موضع ثابت لأي صورة أو مود بورد خارج ترتيب الأقسام المحدد.
- استخدم `section_key` في كل شريحة، والتزم بترتيب الأقسام الوارد أعلاه دون تقديم أو تأخير.
- ضع `section_divider` واحدًا قبل محتوى كل قسم موجود. عنوانه هو اسم القسم العربي المعتمد فقط، وحقول `title_en` و`subtitle` غير مستخدمة ويجب ألا تظهر.
- لا تكرر مكونات المشروع أو جداول الموقع أو السوق. اعرض الجدول مرة واحدة، ثم اختم القسم بملخصه النهائي بعد الجداول.
- نبذة عن المشروع نصية ولا تستخدم رموز التصورات الخارجية؛ كل صورة خارجية محفوظة لقسم التصورات الخارجية فقط حتى تظهر مرة واحدة ولا تضيع من قسمها.
- صور الأرض تُعرض مع الوصف المحفوظ لكل صورة، ثم ملخص تحليل الأرض المعتمد. لا تستخدم صورة أرض بلا وصف إن كان الوصف متاحًا.
- عند توفر أبعاد وحدود للأرض والشوارع المحيطة، يتم تضمين شريحة «مخطط اتجاهي لحدود الأرض» بنمط diagram لتمثيل الأرض والجهات الأربع والشوارع والإطلالات بيانياً بالـ CSS و HTML النقي دون الحاجة لرسومات خارجية.
- الدراسة المالية تأخذ عدد الشرائح الذي تحتاجه جميع جداول تقرير المعاينة ومؤشراته، ثم يأتي الملخص المالي في نهاية القسم مقسمًا إلى شريحتين أو ثلاث. الرسوم البيانية محصورة حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة فقط في كامل العرض: 1) مقارنة المنافسين (horizontal_bar) في قسم دراسة السوق، 2) تكوين إجمالي تكلفة الاستثمار (waterfall) في الدراسة المالية، 3) التدفقات النقدية السنوية والتراكمية (combo) في الدراسة المالية، 4) مقارنة السيناريوهات المالية (heatmap) في الدراسة المالية. يمنع منعاً باتاً إضافة أي رسم بياني خارج هذه المواقع الأربعة أو استخدام أي نوع آخر.
- فريق العمل يحافظ على ترتيب الجهات وحقولها كما أُدخلت، ويستخدم شعار كل جهة عند الحديث عنها. لا ينشئ فئات أو مسميات جديدة.
- كل مخطط مرفوع له صفحة مستقلة أو مساحة كبيرة مع عنوانه ووصفه؛ ممنوع جمع مخططات كثيرة في شبكة صغيرة.
- التصورات الخارجية والداخلية تستخدم كل رموز الصور المحددة لكل شريحة، من صورة إلى ثلاث، ضمن تخطيط متوازن للمجموعة كلها ودون تكرار.
- الملخصات والتحسينات لا تتجاوز الحقائق المعتمدة، ولا تستخدم عبارات عامة أو استرسالًا لا يضيف قيمة واضحة.
- الخاتمة تعرض بيانات التواصل المتاحة، وتمنع عبارات «فرصة واعدة بشروط» أو أي تقييم مشروط مشابه.
- قواعد الشركة في بداية الرسالة ملزمة ما لم تخالف ترتيب الأقسام أو دقة البيانات أو منع الأيقونات.
- {no_street_view}
"""


# There is no upper limit on how many slides a project may need. The stored max_slides used to
# trim the plan — a project with more content than the number allowed simply lost the surplus
# slides, and the planner was told to obey a ceiling the prompt itself calls open. Only
# lock_slide_count still binds the count, and then it binds it exactly.
SLIDE_COUNT_OPEN = 100000


def resolve_slide_bounds(branding):
    """Resolve (min_slides, max_slides, default_count) from branding.

    When lock_slide_count is enabled the tenant's default_slide_count becomes an
    exact requirement. Otherwise only the minimum applies and the upper end is open:
    the planner decides the count from the amount of content.
    """
    branding = branding or {}
    default_count = int(branding.get('default_slide_count') or 16)
    if branding.get('lock_slide_count'):
        return default_count, default_count, default_count
    min_slides = int(branding.get('min_slides') or 14)
    return min(min_slides, SLIDE_COUNT_OPEN), SLIDE_COUNT_OPEN, default_count


def build_fallback_plan(branding):
    """Build a default slide plan when AI slide planning fails.

    Uses the tenant's min/max/default slide count bounds.
    """
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    count = max(min_s, min(default_count, max_s))
    slides = [
        {'title': 'الغلاف', 'type': 'cover', 'design_style': 'image', 'requires_image': True, 'bullets': [], 'content_density': 'low'},
        {'title': 'محتويات العرض', 'type': 'index', 'design_style': 'text', 'requires_image': False, 'bullets': [], 'content_density': 'low'},
    ]
    content_sections = PRESENTATION_SECTION_ORDER[:-1]
    needed = max(0, count - 3)
    for section_key in content_sections[:needed]:
        title = PRESENTATION_SECTION_TITLES[section_key]
        slides.append({
            'title': title,
            'type': 'content',
            'section_key': section_key,
            'design_style': _suggest_design_style(title, slide_type='content'),
            'requires_image': section_key in {'plans', 'exterior', 'interior'},
            'bullets': ['المحتوى المعتمد لهذا القسم', 'التفاصيل المتاحة في بيانات المشروع',
                        'الملخص النهائي دون تكرار'],
            'content_density': 'medium',
        })
    while len(slides) < count - 1:
        slides.append({
            'title': PRESENTATION_SECTION_TITLES['overview'], 'type': 'content',
            'section_key': 'overview', 'design_style': 'text', 'requires_image': False,
            'bullets': ['تفصيل إضافي من بيانات المشروع', 'صياغة موجزة', 'دون اختراع معلومات'],
            'content_density': 'medium',
        })
    slides.append({'title': 'الخاتمة', 'type': 'closing', 'section_key': 'closing', 'design_style': 'minimal', 'requires_image': False, 'bullets': [], 'content_density': 'low'})
    return {'proposed_count': len(slides), 'slides': slides}


def _plan_asset_note(images):
    if not isinstance(images, dict):
        return ''
    moodboard = _available_asset_items(images.get('moodboard'))
    land_photos = _available_asset_items(images.get('land_photos'))
    plans = _available_asset_items(images.get('plans'))
    interiors = []
    for component_index, component in enumerate(images.get('interior_components') or [], 1):
        if not isinstance(component, dict):
            continue
        for image_index, item in _available_asset_items(component.get('images')):
            interiors.append({
                'component': component.get('name') or f'المكون {component_index}',
                'token': f'##INTERIOR_COMP_{component_index}_IMG_{image_index}##',
                'label': item.get('label') or '', 'caption': item.get('caption') or '',
            })
    summary = {
        'التصورات الخارجية': [f'##MOODBOARD_IMAGE_{index}##' for index, _item in moodboard],
        'صور الأرض': [{
            'token': f'##LAND_PHOTO_{index}##',
            'description': item.get('description') or item.get('caption') or '',
        } for index, item in land_photos],
        'المخططات': [f'##PLAN_IMAGE_{index}##' for index, _item in plans],
        'التصورات الداخلية': interiors,
        'فريق العمل': [{
            'name': item.get('name') or '', 'has_logo': bool(item.get('logo')),
            'token': f'##TEAM_LOGO_{index}##' if item.get('logo') else '',
        } for index, item in enumerate(images.get('team_members') or [], 1) if isinstance(item, dict)],
    }
    if not any(summary.values()):
        return ''
    return '\n\n## وسائط العرض المتوفرة وتوزيعها الإلزامي\n' + json.dumps(summary, ensure_ascii=False, indent=2)


def build_slide_plan_prompt(project_data, branding, tenant_id=None, images=None):
    """Build the prompt for AI to propose a slide plan.

    The plan decides which slides exist, so it has to see every section. Cutting the payload at
    6,000 characters meant the market study, the executive content and the team never reached the
    planner, and it could not propose slides for facts it was never shown.
    """
    project_json = build_project_facts(project_data, tenant_id)

    min_slides, max_slides, _default_count = resolve_slide_bounds(branding)

    prompt = SLIDE_PLAN_PROMPT.format(
        project_json=project_json,
        min_slides=min_slides,
        max_slides=max_slides,
        distribution_rules=CONTENT_DISTRIBUTION_RULES,
        no_street_view=NO_STREET_VIEW_RULE,
    )
    asset_note = _plan_asset_note(images)
    if asset_note:
        prompt += asset_note
    location_note = _location_data_note(project_data)
    if location_note:
        prompt += location_note
    timeline_note = _timeline_data_note(project_data)
    if timeline_note:
        prompt += timeline_note
    financial_note = _financial_data_note(project_data)
    if financial_note:
        prompt += financial_note
    return prompt


def _extract_json_from_text(response_text):
    """Robustly extract the first JSON object from AI response text."""
    if not response_text:
        return None

    # Try markdown code blocks first
    code_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', response_text)
    if code_match:
        candidate = code_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Balanced brace parser: find the outermost { } object
    start = response_text.find('{')
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(response_text)):
            ch = response_text[i]
            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == '\\':
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = response_text[start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break

    # Fallback to greedy regex
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        return json_match.group()

    return None


def _enforce_slide_count(slides, target_count):
    """Trim or pad a slide list to exactly target_count, keeping fixed slides intact.

    The cover, index and closing slides keep their reserved positions;
    only content slides are removed or appended.
    """
    if target_count < 1 or len(slides) == target_count:
        return slides

    reserved_tail_types = {'closing'}

    if len(slides) > target_count:
        head = slides[:2]                      # cover + index
        tail = [s for s in slides[-2:] if s.get('type') in reserved_tail_types]
        middle = slides[len(head):len(slides) - len(tail)]
        keep_middle = max(0, target_count - len(head) - len(tail))
        return (head + middle[:keep_middle] + tail)[:target_count]

    tail = [s for s in slides[-2:] if s.get('type') in reserved_tail_types]
    body = slides[:len(slides) - len(tail)]
    while len(body) + len(tail) < target_count:
        title = f'تفاصيل إضافية {len(body)}'
        style = _suggest_design_style(title, slide_type='content')
        if body and body[-1].get('design_style') == style and style == 'cards':
            style = 'text'
        body.append({
            'title': title,
            'type': 'content',
            'design_style': style,
            'content_density': 'medium',
            'requires_image': False,
            'bullets': ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة'],
        })
    return body + tail


def parse_slide_plan(response_text, branding=None, project_data=None):
    """Parse the AI response into a slide plan dict."""
    json_text = _extract_json_from_text(response_text)
    if not json_text:
        raise ValueError("No JSON found in AI response")

    try:
        plan = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    # Validate structure
    if 'slides' not in plan or not isinstance(plan['slides'], list):
        raise ValueError("Missing 'slides' array in response")

    # A locked slide count is a hard tenant requirement: reshape the plan
    # instead of failing validation and burning another generation round.
    if branding and branding.get('lock_slide_count'):
        _min_s, _max_s, default_count = resolve_slide_bounds(branding)
        if len(plan['slides']) != default_count:
            print(f"[SLIDE-PLAN] lock_slide_count active: reshaping "
                  f"{len(plan['slides'])} -> {default_count} slides")
            plan['slides'] = _enforce_slide_count(plan['slides'], default_count)

    plan['proposed_count'] = len(plan['slides'])

    # Ensure first slide is cover and last is closing
    if plan['slides']:
        plan['slides'][0]['type'] = 'cover'
        plan['slides'][-1]['type'] = 'closing'

    # Ensure second slide is index when there are at least three slides
    if len(plan['slides']) > 2:
        plan['slides'][1]['type'] = 'index'

    # If location data exists but the AI marked a location slide as plain content,
    # convert it to the appropriate map type so the map image is actually used.
    if project_data:
        for slide in plan['slides']:
            if slide.get('type') == 'content':
                map_type = _maybe_map_slide_type(slide.get('title'), project_data)
                if map_type:
                    slide['type'] = map_type
                    if 'design_style' not in slide or slide.get('design_style') == 'cards':
                        slide['design_style'] = 'map'
                    if 'requires_image' not in slide:
                        slide['requires_image'] = True

    # Fill defaults for any missing slide metadata, and avoid long runs of 4-card layouts
    prev_content_style = None
    for slide in plan['slides']:
        slide_type = slide.get('type', 'content')
        if 'design_style' not in slide:
            slide['design_style'] = _suggest_design_style(
                slide.get('title'), slide.get('bullets', []), slide_type
            )
        if slide_type == 'content':
            if slide.get('design_style') == prev_content_style and prev_content_style == 'cards':
                slide['design_style'] = 'text'
            prev_content_style = slide.get('design_style')
        if 'content_density' not in slide:
            slide['content_density'] = 'medium'
        if 'requires_image' not in slide:
            slide['requires_image'] = (
                slide_type in ('cover', 'moodboard', 'section_divider')
                or slide_type.startswith('map_')
                or slide.get('design_style') == 'image'
            )

    return plan


def validate_slide_plan(plan, branding):
    """
    Validate the slide plan against content distribution rules.
    Returns (is_valid, issues_list).
    """
    issues = []
    slides = plan.get('slides', [])

    if not slides:
        issues.append("No slides in plan")
        return False, issues

    # Check min/max slides
    min_s, max_s, _default_count = resolve_slide_bounds(branding)
    count = len(slides)
    if count < min_s:
        issues.append(f"Too few slides: {count} (min: {min_s})")
    if count > max_s:
        issues.append(f"Too many slides: {count} (max: {max_s})")

    # Check fixed-position slides
    valid_types = {'cover', 'index', 'content', 'section_divider', 'moodboard', 'closing',
                   'map_overview', 'map_landmarks', 'map_access', 'map_catchment',
                   'site_specs'}

    if slides[0].get('type') != 'cover':
        issues.append("First slide must be 'cover'")
    if len(slides) > 1 and slides[1].get('type') != 'index':
        issues.append("Second slide must be 'index'")
    if slides[-1].get('type') != 'closing':
        issues.append("Last slide must be 'closing'")

    # Check each slide type and content
    for i, slide in enumerate(slides):
        slide_type = slide.get('type', 'content')
        if slide_type not in valid_types:
            issues.append(f"Slide {i+1} has unknown type '{slide_type}'")

        if slide_type in ('content', 'site_specs', 'map_landmarks'):
            bullets = slide.get('bullets', [])
            has_structured_source = bool(slide.get('content_source') or slide.get('source_table') or slide.get('image_tokens'))
            if len(bullets) < 3 and not has_structured_source:
                issues.append(f"Slide {i+1} '{slide.get('title', '?')}' has only {len(bullets)} bullets (min: 3)")
            if len(bullets) > 6:
                issues.append(f"Slide {i+1} '{slide.get('title', '?')}' has {len(bullets)} bullets (max: 6)")

    return len(issues) == 0, issues


# ─────────────────────────────────────────────────────────────────────────────
# Single Slide Generation
# ─────────────────────────────────────────────────────────────────────────────

def _slide_source_data_note(slide, project_data):
    content_sources = (slide or {}).get('content_sources') if isinstance(slide, dict) else None
    if isinstance(content_sources, list) and content_sources:
        notes = []
        for content_source in content_sources:
            item = dict(slide)
            item.pop('content_sources', None)
            item['content_source'] = content_source
            note = _slide_source_data_note(item, project_data)
            if note:
                notes.append(note)
        return '\n\n'.join(notes)
    source = str((slide or {}).get('content_source') or '')
    project_data = project_data if isinstance(project_data, dict) else {}
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    if (slide or {}).get('type') == 'map_landmarks' or source == 'nearby_landmarks':
        matrix = project_data.get('landmarks_matrix')
        if isinstance(matrix, list) and matrix:
            return 'جدول المعالم والمسافات وأوقات القيادة كما هو دون حذف:\n' + json.dumps(matrix, ensure_ascii=False, indent=2)
        value = str(project_data.get('nearby_landmarks') or '').strip()
        return 'المعالم والمسافات وأوقات القيادة كما هي دون حذف:\n' + value if value else ''
    if source == 'market_study_data.swot':
        market = _decode_json_fact(project_data.get('market_study_data'))
        swot = market.get('swot') if isinstance(market, dict) and isinstance(market.get('swot'), dict) else {}
        return 'تحليل SWOT الأصلي الوحيد، انقل المحاور الأربعة دون إضافة أو تكرار:\n' + json.dumps(swot, ensure_ascii=False, indent=2) if swot else ''
    if source == 'market_study_data.competitors' or (slide or {}).get('source_table') == 'competitors':
        market = _decode_json_fact(project_data.get('market_study_data'))
        market = market if isinstance(market, dict) else {}
        competitors = market.get('competitors') if isinstance(market.get('competitors'), list) else []
        items = []
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            name = str(comp.get('name') or comp.get('project_name') or '').strip()
            price_val = comp.get('price_value') or comp.get('value') or comp.get('price')
            p_from = comp.get('price_from') or comp.get('min_price')
            p_to = comp.get('price_to') or comp.get('max_price')
            p_type = comp.get('price_type') or comp.get('type') or ''
            if name and (price_val or p_from or p_to):
                items.append({
                    'name': name,
                    'price_value': price_val,
                    'price_from': p_from,
                    'price_to': p_to,
                    'price_type': p_type,
                    'unit': comp.get('unit') or (comp.get('area_cache') if isinstance(comp.get('area_cache'), dict) else {}).get('unit') or '',
                })
        return (
            'جدول المنافسين الرئيسيين لرسم مقارنة المنافسين (horizontal_bar):\n'
            + json.dumps(items, ensure_ascii=False, indent=2)
            + '\n\nقواعد رسم مقارنة المنافسين المعتمدة:\n'
            '- ترتيب تنازلي حسب السعر (من الأعلى إلى الأقل).\n'
            '- مقارنة الأسعار لنفس وحدة القياس ونوع السعر (سعر المتر بيع أو تأجير، أو إجمالي سعر الوحدة).\n'
            '- إبراز مشروعنا بلون الهوية المعتمد إذا كان له سعر مقترح، لتمييزه فوراً عن المنافسين.\n'
            '- استبعاد أي منافس لا يملك قيمة رقمية موثقة (لا تدرج منافس بسعر صفر أو مجهول).\n'
            '- نطاق السعر يمثل كشريط من الأدنى للأعلى (وليس متوسطاً افتراضياً).\n'
            '- تنبيه المبرمج: يمنع منعاً باتاً اختراع قيم افتراضية أو متوسطات تقديرية.'
        )
    if source == 'site_analysis':
        value = str(project_data.get('site_analysis') or '').strip()
        return 'ملخص الموقع المعتمد دون إضافة أو تكرار:\n' + value if value else ''
    if source == 'executive_content.summary':
        executive = _decode_json_fact(project_data.get('executive_content'))
        value = str(executive.get('summary') or '').strip() if isinstance(executive, dict) else ''
        return 'الملخص التنفيذي المعتمد دون إضافة أو تكرار:\n' + value if value else ''
    if source == 'contact_closing':
        contact = _contact_facts(project_data)
        if contact:
            return contact + '\nاعرض جميع الحقول المذكورة فقط، مع صورة المشروع الرئيسية وشعاري الشركة والمشروع.'
        project_name = str(project_data.get('project_name') or project_data.get('projectName') or 'المشروع').strip()
        return f'لا توجد بيانات تواصل مدخلة. اعرض شكرًا موجزًا واسم المشروع فقط: {project_name}.'
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
            return 'المحتوى الحرفي المطلوب في هذه الشريحة فقط:\n' + json.dumps(part, ensure_ascii=False, indent=2)
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        return f'جدول هذه الشريحة فقط ({table_key}):\n' + json.dumps(rows[start:end], ensure_ascii=False, indent=2)
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        group_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        group_name = 'التكاليف والاستثمار' if group_key == 'costs' else 'مؤشرات العائد والاسترداد'
        rows = _financial_summary_from_report(model).get(group_name, [])[start:end]
        return f'{group_name} من نفس تقرير PDF دون إعادة حساب:\n' + json.dumps(rows, ensure_ascii=False, indent=2)
    if source == 'financial_indicators':
        report_summary = _financial_summary_from_report(model)
        if report_summary:
            return (
                'الملخص المالي من نفس بيانات تقرير PDF — أنشئ جدول التكاليف والاستثمار وجدول مؤشرات العائد والاسترداد بالقيم والمسميات نفسها دون حذف أو إعادة حساب:\n'
                + json.dumps(report_summary, ensure_ascii=False, indent=2)
            )
        inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
        projection = model.get('projection') if isinstance(model.get('projection'), dict) else {}
        calc = _parse_financial_dict(project_data.get('financial_calc_data'))

        cost_investment_keys = (
            ('projectCost', 'إجمالي تكلفة المشروع'),
            ('projectCostWithFinance', 'التكلفة شاملة التمويل'),
            ('adjustedProjectCost', 'إجمالي تكلفة الاستثمار'),
            ('developerCost', 'أتعاب المطور'),
            ('landValue', 'قيمة الأرض'),
            ('landRent', 'إيجار الأرض السنوي'),
            ('totalCashEquity', 'حقوق الملكية النقدية المطلوبة'),
            ('facilityAmount', 'قيمة التسهيل التمويلي'),
            ('totalFinanceCost', 'إجمالي كلفة التمويل'),
            ('totalFundFees', 'إجمالي أتعاب الصندوق'),
        )
        returns_payback_keys = (
            ('roi', 'معدل العائد على الاستثمار (ROI)'),
            ('projectIrr', 'معدل العائد الداخلي للمشروع (Project IRR)'),
            ('equityIrr', 'معدل العائد الداخلي للملكية (Equity IRR)'),
            ('payback', 'فترة استرداد رأس المال (سنوات)'),
            ('equityPayback', 'فترة استرداد حقوق الملكية (سنوات)'),
            ('totalEquityDistributions', 'إجمالي توزيعات الأرباح'),
            ('saleExitValue', 'صافي التخارج البيعي'),
            ('operatingExitValue', 'صافي التخارج التشغيلي'),
            ('terminal', 'إجمالي قيمة التخارج'),
        )

        def _extract_group(keys):
            res = {}
            for key, label in keys:
                value = projection.get(key)
                if value in (None, '', [], {}) and inputs.get(key) not in (None, '', [], {}):
                    value = inputs.get(key)
                if value in (None, '', [], {}) and calc.get(key) not in (None, '', [], {}):
                    value = calc.get(key)
                if value not in (None, '', [], {}, -1):
                    res[label] = value
            return res

        cost_investment_table = _extract_group(cost_investment_keys)
        returns_payback_table = _extract_group(returns_payback_keys)

        payload = {
            'جدول التكاليف والاستثمار': cost_investment_table,
            'جدول مؤشرات العائد والاسترداد': returns_payback_table,
        }
        return (
            'المؤشرات المالية المطلوبة — نسّقها في جدولين منظمين متجاورين أو متتاليين (جدول التكاليف والاستثمار + جدول مؤشرات العائد والاسترداد) مع إبراز المؤشرات الكبرى بخط عريض 800:\n'
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        return 'مكونات هذه الشريحة فقط:\n' + json.dumps(_project_component_rows(project_data)[start:end], ensure_ascii=False, indent=2)
    if source == 'land_boundary_diagram':
        data = _extract_land_boundary_diagram_data(project_data)
        return (
            'بيانات المخطط الاتجاهي لحدود الأرض والواجهات — أنشئ مخططاً اتجاهياً هندسياً راقياً (Directional Boundary Diagram) '
            'يتوسطه صندوق عريض يمثل «أرض المشروع» مع أطوال الأضلاع على حوافه الأربع وملخص الواجهات في وسطه، وتحيط به بطاقات '
            'الاتجاهات الأربعة (شمال، جنوب، شرق، غرب) مبيناً عليها أطوال الأضلاع وعروض الشوارع والواجهات مع تمييز الشوارع بلون التمييز (مثل الذهبي) '
            'وبطاقة بارزة ومميزة لجهة الإطلالة أو الطريق الرئيسي إن وجدت:\n'
            + json.dumps(data, ensure_ascii=False, indent=2)
        )
    return ''


def _extract_land_boundary_diagram_data(project_data):
    """Extract structured data for the directional land boundary diagram."""
    source = project_data if isinstance(project_data, dict) else {}

    facades_count = str(source.get('facades_count') or '').strip()
    facades_directions = str(source.get('facades_directions') or '').strip()

    facades_summary = ''
    if facades_count and facades_directions:
        if facades_count in ('2', 'واجهتان'):
            count_text = 'واجهتان'
        elif facades_count in ('1', 'واجهة'):
            count_text = 'واجهة واحدة'
        elif facades_count.isdigit() and int(facades_count) > 2:
            count_text = f'{facades_count} واجهات'
        else:
            count_text = f'{facades_count} واجهات' if 'واجه' not in facades_count else facades_count
        facades_summary = f'{count_text} ({facades_directions})'
    elif facades_directions:
        facades_summary = f'الواجهات: {facades_directions}'
    elif facades_count:
        facades_summary = f'عدد الواجهات: {facades_count}'

    directions = {
        'north': {'label': 'الشمال', 'length': '', 'description': '', 'is_facade': False},
        'south': {'label': 'الجنوب', 'length': '', 'description': '', 'is_facade': False},
        'east': {'label': 'الشرق', 'length': '', 'description': '', 'is_facade': False},
        'west': {'label': 'الغرب', 'length': '', 'description': '', 'is_facade': False},
    }
    dir_aliases = {
        'north': ('north', 'شمال', 'الشمال'),
        'south': ('south', 'جنوب', 'الجنوب'),
        'east': ('east', 'شرق', 'الشرق'),
        'west': ('west', 'غرب', 'الغرب'),
    }

    raw_dt = source.get('directions_table')
    dt_rows = _decode_json_fact(raw_dt) if isinstance(raw_dt, str) else raw_dt
    if isinstance(dt_rows, list):
        for row in dt_rows:
            if not isinstance(row, dict):
                continue
            dir_key = str(row.get('direction') or row.get('label') or '').strip().lower()
            reg_text = str(row.get('regulation_text') or row.get('text') or row.get('description') or '').strip()
            for std_key, aliases in dir_aliases.items():
                if dir_key in aliases or any(a in dir_key for a in aliases):
                    directions[std_key]['description'] = reg_text
                    break

    land_analysis = _decode_json_fact(source.get('land_documents_analysis_data') or source.get('landDocumentsAnalysisData') or source.get('land_documents_analysis'))
    if isinstance(land_analysis, dict):
        parcels = land_analysis.get('parcels') if isinstance(land_analysis.get('parcels'), list) else []
        parcel_dirs = parcels[0].get('directions') if parcels and isinstance(parcels[0], dict) and isinstance(parcels[0].get('directions'), dict) else {}
        if not parcel_dirs and isinstance(land_analysis.get('directions'), dict):
            parcel_dirs = land_analysis.get('directions')
        for std_key, aliases in dir_aliases.items():
            for alias in aliases:
                if alias in parcel_dirs and isinstance(parcel_dirs[alias], dict):
                    p_info = parcel_dirs[alias]
                    desc = str(p_info.get('regulation_text') or p_info.get('uses') or p_info.get('street_name') or '').strip()
                    length = p_info.get('boundary_length_m') or p_info.get('length')
                    width = p_info.get('street_width_m') or p_info.get('width')
                    street = str(p_info.get('street_name') or '').strip()
                    if desc and not directions[std_key]['description']:
                        directions[std_key]['description'] = desc
                    if length and not directions[std_key]['length']:
                        directions[std_key]['length'] = f"{length} م"
                    if street and not directions[std_key].get('street_name'):
                        directions[std_key]['street_name'] = street
                    if width and not directions[std_key].get('street_width'):
                        directions[std_key]['street_width'] = f"{width} م"
                    break

    raw_lengths = str(source.get('boundary_lengths') or '').strip()
    if raw_lengths:
        for part in re.split(r'[|,\n،]', raw_lengths):
            part = part.strip()
            if not part:
                continue
            for std_key, aliases in dir_aliases.items():
                if any(part.startswith(a) or f"{a}:" in part or f"{a} :" in part for a in aliases):
                    val = re.sub(r'^(?:' + '|'.join(aliases) + r')\s*[:=\-—]\s*', '', part).strip()
                    if val and not directions[std_key]['length']:
                        directions[std_key]['length'] = val if 'م' in val else f"{val} م"
                    break

    raw_streets = str(source.get('surrounding_streets') or '').strip()
    for std_key, d in directions.items():
        desc = f"{d.get('description', '')} {d.get('street_name', '')} {raw_streets}"
        if re.search(r'(?:شارع|طريق|ممر|ميدان|نافذ|street|road|avenue|boulevard)', desc):
            d['is_facade'] = True
            d['type'] = 'street'
        else:
            d['type'] = 'neighbor'

    key_view = ''
    full_text = f"{raw_streets} {json.dumps(directions, ensure_ascii=False)}"
    if re.search(r'(?:كورنيش|بحر|إطلالة بحرية|شاطئ|واجهة بحرية|sea view|corniche)', full_text, re.IGNORECASE):
        for std_key in ('west', 'north', 'east', 'south'):
            dir_text = json.dumps(directions.get(std_key, {}), ensure_ascii=False)
            if re.search(r'(?:كورنيش|بحر|إطلالة بحرية|شاطئ|واجهة بحرية)', dir_text):
                lbl = directions[std_key]['label']
                key_view = f"جهة {lbl} — جهة الإطلالة البحرية وطريق الكورنيش"
                break
        if not key_view:
            key_view = "جهة الإطلالة البحرية وطريق الكورنيش"
    elif re.search(r'(?:طريق رئيسي|محور|بوليفارد|شريان)', full_text):
        for std_key in ('west', 'north', 'east', 'south'):
            dir_text = json.dumps(directions.get(std_key, {}), ensure_ascii=False)
            if re.search(r'(?:طريق رئيسي|محور|طريق|بوليفارد)', dir_text):
                lbl = directions[std_key]['label']
                key_view = f"جهة {lbl} — واجهة الطريق الرئيسي"
                break

    return {
        'plot_name': 'أرض المشروع',
        'facades_summary': facades_summary or 'الواجهات المحيطة بالأرض',
        'north': directions['north'],
        'south': directions['south'],
        'east': directions['east'],
        'west': directions['west'],
        'key_view': key_view,
        'boundary_lengths_summary': raw_lengths,
        'surrounding_streets_summary': raw_streets,
    }


def build_slide_user_msg(slide, slide_num, total_slides, branding, project_data=None):
    """Build the user message for generating a single slide."""
    title = slide.get('title', f'شريحة {slide_num}')
    slide_type = slide.get('type', 'content')
    design_style = slide.get('design_style', 'cards')
    chart_type = str(slide.get('chart_type') or '').strip().lower()
    canonical_type = canonicalize_chart_type(chart_type)
    chart_type = canonical_type or chart_type
    bullets = slide.get('bullets', [])
    density = slide.get('content_density', 'medium')
    section_key = _slide_section_key(slide)
    background = normalize_hex_color((branding or {}).get('background_color'), '#f8fafc')
    preferred_text = normalize_hex_color((branding or {}).get('text_color'), '#1e293b')
    readable_body = readable_text_color(preferred_text, background)
    readable_heading = readable_text_color((branding or {}).get('primary_color'), background, (readable_body,))

    bullets_text = '\n'.join(f'- {b}' for b in bullets) if bullets else '(لا توجد نقاط محددة — استخرج من بيانات المشروع)'

    style_instructions = {
        'dashboard': 'لوحة مؤشرات مالية تعتمد جداول HTML نظامية كاملة بعمودين للتكاليف والاستثمار ومؤشرات العائد بجانب بعضهما بنفس تصميم ومساحات تقرير PDF مع منع الكروت العائمة والمربعات الإحصائية',
        'cards': 'بطاقتان أو ثلاث فقط لعناصر مستقلة عريضة وغنية؛ استخدم الفقرات النصية أو الجداول بدلاً من التقطيع المفرط إلى مربعات صغيرة',
        'timeline': 'مراحل زمنية واضحة ومسار تدفق زمني، واعرض الملاحظة فقط تحت المرحلة التي تحتوي ملاحظة فعلية',
        'table': 'جدول احترافي كامل مطابق لتصميم تقرير PDF المالي بحدود واضحة 1px solid ورؤوس مظللة بألوان الهوية وفواصل آلاف للأرقام ومنع تحويل الجدول إلى كروت عائمة',
        'chart': 'رسم بياني احترافي حصراً من الأنواع الأربعة المعتمدة (مقارنة المنافسين: horizontal_bar في دراسة السوق، تكوين إجمالي تكلفة الاستثمار: waterfall، التدفقات النقدية السنوية والتراكمية: combo، مقارنة السيناريوهات المالية: heatmap في المالية) بـ HTML و CSS النقي مع جدول الأرقام بجانبه وبألوان الهوية ومنع أي نوع آخر',
        'text': 'عنوان وفقرة غنية ووافية أو قائمة منظمة تشرح الفكرة بالكامل بلا اختصار مخل وبلا تجزئة لمربعات فارغة',
        'image': 'استخدم جميع رموز الصور المحددة في الخطة بتوزيع متوازن واحد للمجموعة، وبحد أقصى ثلاث صور في الشريحة',
        'flow': 'مخطط تدفق بصري هندسي راقٍ (Flowchart / Visual Pipeline) يربط الكتل بمسارات تدفق واضحة وبألوان الهوية مع إبراز القيم والمراحل والمبالغ',
        'diagram': 'مخطط اتجاهي هندسي راقٍ (Directional Diagram) لأرض المشروع وحدودها الأربعة والواجهات والشوارع المحيطة والإطلالة وفق الهيكل المعتمد',
        'swot': 'تحليل SWOT وتحليل المخاطر بتقسيم واضح وبألوان الهوية وحدها',
        'map': 'خريطة كاملة بلا قص باستخدام contain ومضبوطة في المنتصف تماماً (center center) مع جدول أو ملخص واحد دون إعادة الأرقام في أكثر من شكل',
        'grid': 'استخدم جميع رموز الصور المحددة في الخطة بتوزيع متوازن من صورة إلى ثلاث صور',
        'minimal': 'خاتمة بسيطة تتضمن بيانات التواصل المتاحة بلا تقييمات أو عبارات مشروطة',
    }.get(design_style, 'نص منظم يناسب طبيعة المحتوى')
    chart_instructions = {
        'horizontal_bar': (
            'مخطط الأعمدة الأفقية (Horizontal Bar Chart) لمقارنة المنافسين: '
            'ترتيب تنازلي حسب السعر (من الأعلى إلى الأقل). مقارنة الأسعار لنفس وحدة القياس ونوع السعر (سعر المتر بيع أو تأجير، أو إجمالي سعر الوحدة). '
            'إبراز مشروعنا بلون الهوية المعتمد إذا كان له سعر مقترح لتمييزه فوراً. استبعاد أي منافس لا يملك قيمة رقمية موثقة (لا تدرج منافس بسعر صفر أو مجهول). '
            'نطاق السعر يمثل كشريط من الأدنى للأعلى (وليس متوسطاً افتراضياً). يمنع اختراع قيم أو متوسطات افتراضية.'
        ),
        'waterfall': (
            'المخطط الشلالي (Waterfall Chart) لتكوين إجمالي تكلفة الاستثمار: '
            'يوضح مساهمة كل بند رئيسي وفرعي (تكاليف التطوير، قيمة الأرض، الرسوم، التمويل، الصندوق) وصولاً لإجمالي تكلفة الاستثمار. '
            'إظهار تكلفة المشروع وتكلفة الاستثمار كأعمدة إجمالية كاملة (Full Columns). إظهار بنود التكاليف كأعمدة عائمة/متزايدة (Floating Bars/Increments). '
            'عدم تكرار البنود أو إدخال مجاميع وسيطة داخل الإجمالي لمنع التكرار (No Double Counting). '
            'استبعاد مبالغ التسهيلات التمويلية من التكلفة (التسهيل مصدر تمويل وليس تكلفة؛ يدرج فقط أتعاب ترتيب التمويل وتكلفة التمويل/الفائدة).'
        ),
        'combo': (
            'المخطط المركب: أعمدة وخط (Combo Chart: Column + Line) للتدفقات النقدية السنوية والتراكمية: '
            'أعمدة رأسية لصافي التدفق السنوي (Net Cash Flow) لكل سنة على المحور الأفقي، مع خط بياني متصل للرصيد النقدي التراكمي (Cumulative Balance). '
            'تمثيل جميع سنوات الدراسة في رسم بياني واحد. تمييز التدفقات السالبة بلون مختلف تماماً عن الموجبة لتوضيح مراحل العجز والربحية. '
            'خط الصفر واضح لتحديد نقطة التعادل ونهاية الاسترداد (Payback). عدم تكرار الرصيد التراكمي كأعمدة مستقلة. '
            'خط الرصيد التراكمي يحسب بجمع التدفقات النقدية السنوية إذا لم يكن مخزناً مسبقاً.'
        ),
        'heatmap': (
            'الخريطة الحرارية (Heatmap) لمقارنة السيناريوهات المالية: '
            'مقارنة السيناريوهات (المتحفظ، الأساسي، المتفائل) لمؤشرات: إجمالي الاستثمار، الإيرادات، صافي الربح، ROI، Project IRR، Equity IRR، فترة الاسترداد. '
            'تلوين اتجاهي ذكي بحسب قطبية المؤشر (Directional/Polarity-Aware Coloring): '
            'الأخضر/الإيجابي للأعلى في مؤشرات الربح والإيراد والعوائد (Higher is better)، '
            'والأخضر/الإيجابي للأقل في التكاليف وفترة الاسترداد (Lower is better). '
            'توحيد وحدات القياس، وتقريب الأرقام لنسبة مئوية أو خانة عشرية واحدة، ومطابقة أرقام السيناريو الأساسي تماماً مع ملخص المؤشرات المعتمد بالمشروع.'
        ),
    }
    chart_note = chart_instructions.get(chart_type, '')

    density_instructions = {
        'low': 'محتوى خفيف — صورة كبيرة أو عنصران وافيان مع شرح تفصيلي',
        'medium': 'محتوى متوسط — نص غني أو جدول كامل ممتلئ بصرياً',
        'high': 'محتوى كثيف — جدول بيانات متكامل أو مخطط تدفق شامل بدون ازدحام',
    }.get(density, 'محتوى متوسط')

    # Explicit image/map placeholder for this slide
    placeholder_note = ''
    image_tokens = [str(token) for token in (slide.get('image_tokens') or []) if str(token or '').strip()]
    if image_tokens:
        placeholder_note = 'استخدم كل رموز الصور التالية مرة واحدة وبحجم واضح، ولا تستبدلها بصورة الغلاف: ' + '، '.join(image_tokens)
        if slide.get('image_layout'):
            placeholder_note += f". التخطيط المعتمد لهذه المجموعة هو {slide.get('image_layout')} ولا تغيّر عدد الصور"
    elif slide_type == 'cover':
        placeholder_note = 'يجب استخدام ##IMAGE_COVER## كخلفية كاملة على كامل الشريحة، ووضع طبقة فوقها تحمل data-cover-overlay. لون الطبقة سيُثبت من اللون الأساسي للهوية؛ ممنوع كحلي ثابت أو لون خارج الهوية.'
    elif slide_type == 'map_overview':
        placeholder_note = 'يجب استخدام ##MAP_OVERVIEW## كخلفية رئيسية لهذه الشريحة مع ضبط الصورة في المنتصف تماماً (center center) بدون أي إزاحة أو قطع.'
    elif slide_type == 'map_landmarks':
        placeholder_note = 'يجب استخدام ##MAP_LANDMARKS## كخلفية مع ضبطها في المنتصف (center center) مع جدول أوقات القيادة والمسافات من البيانات.'
    elif slide_type == 'map_access':
        placeholder_note = 'يجب استخدام ##MAP_ACCESS## لعرض خريطة الطرق والمداخل مع ضبط الصورة في المنتصف (center center).'
    elif slide_type == 'map_catchment':
        placeholder_note = 'يجب استخدام ##MAP_CATCHMENT## لعرض دوائر نطاق التأثير مع ضبط الصورة في المنتصف (center center).'
    elif slide_type == 'site_specs':
        placeholder_note = 'استخدم جدول بيانات احترافي لخصائص الموقع.'
    elif slide_type == 'moodboard':
        placeholder_note = 'استخدم كل رموز صور التصورات الخارجية المحددة للشريحة وفق التخطيط المعتمد، دون حذف أو تكرار.'
    elif design_style == 'image':
        placeholder_note = 'لا تستخدم صورة ما لم يكن رمزها محددًا في خطة هذه الشريحة أو في الصور المتوفرة لموضوعها.'

    notes = [
        f'أنشئ فقط الشريحة {slide_num} لا غير',
        'اكتب HTML في div class="slide" واحد فقط',
        'لا تكتب شرح أو markdown أو كود إضافي',
        'استخدم خط الشركة نفسه في كل العناصر من دون font-family، بوزن 800 للعناوين الرئيسية والأرقام والمؤشرات الكبرى، و700 للعناوين الفرعية ورؤوس الجداول، و600 للتسميات، و400 للنصوص مع إبراز الكلمات المفتاحية بوزن 700',
        f'استخدم {readable_heading} للعناوين و{readable_body} للنص فوق الخلفية {background}. لا تستخدم أي لون نص قبل التحقق أن نسبة تباينه مع خلفيته 4.5:1 على الأقل، ولا تضع نصًا داكنًا فوق مساحة داكنة أو نصًا فاتحًا فوق مساحة فاتحة',
        'لا تختصر الكلام اختصاراً مخلاً ولا تقسم الشريحة إلى 4 أو 6 مربعات صغيرة فارغة؛ اعتمد على فقرات وافية وجداول متكاملة وتدفقات بصرية منظمة',
        'لا تكرر معلومة وردت في شريحة أخرى أو قسم آخر؛ تحليل SWOT يستخدم مصدر market_study_data.swot مرة واحدة فقط، والمكونات في قسم المكونات فقط',
        'ممنوع وضع شارات أو بطاقات مكررة مثل «* مشروع متعدد الاستخدامات *» أو شارات تصنيف عامة أعلى شرائح المحتوى العادية',
        'الرسوم البيانية محصورة حصراً في 4 أنواع معتمدة لـ 4 مواقع محددة (مقارنة المنافسين: horizontal_bar في السوق، وتكلفة الاستثمار: waterfall، والتدفقات النقدية: combo، ومقارنة السيناريوهات: heatmap في المالية) وأي رسم خارجها ممنوع منعاً باتاً؛ ولا تستخدم البطاقات إلا لعناصر مستقلة عريضة وبحد أقصى ثلاث',
        'لا تنشئ شريحة كاملة لإجابة قصيرة أو قيمة واحدة؛ ادمجها مع أقرب محتوى منطقي داخل المحور نفسه',
        'استخدم فواصل الآلاف بصريًا للمبالغ والمساحات والكميات دون تقريب، ولا تستخدمها للسنوات أو الهواتف أو الوثائق أو المعرفات أو الإحداثيات',
        'املأ الشريحة بالمحتوى الضروري والوافي؛ وشرائح الملخص المالي تستخدم جداول التقرير نفسها دون ضغط أو حذف',
    ]
    company_tone = str((project_data or {}).get('_company_logo_tone') or (branding or {}).get('_logo_tone') or '').strip().lower()
    project_tone = str((project_data or {}).get('_project_logo_tone') or '').strip().lower()
    logo_dark_background = dark_surface_color(
        (branding or {}).get('primary_color'), (branding or {}).get('secondary_color'))
    if company_tone == 'light':
        notes.append(f'شعار الشركة فاتح: ضع ##LOGO## على خلفية {logo_dark_background} فقط، ولا تعكس القرار ولا تضعه على الأبيض')
    elif company_tone == 'dark':
        notes.append('شعار الشركة داكن: ضع ##LOGO## على خلفية #ffffff فقط، ولا تعكس القرار ولا تضعه على خلفية داكنة')
    if project_tone == 'light':
        notes.append(f'شعار المشروع فاتح: ضع ##PROJECT_LOGO## على خلفية {logo_dark_background} مستقلة عن شعار الشركة')
    elif project_tone == 'dark':
        notes.append('شعار المشروع داكن: ضع ##PROJECT_LOGO## على خلفية #ffffff مستقلة عن شعار الشركة')
    if placeholder_note:
        notes.insert(0, placeholder_note)
    source_note = _slide_source_data_note(slide, project_data)
    if source_note:
        notes.append(source_note)
    content_source = str(slide.get('content_source') or '')
    if content_source in ('site_analysis', 'executive_content.summary') and '##MAP_OVERVIEW##' in (slide.get('image_tokens') or []):
        marker_side = str((project_data or {}).get('_map_marker_side') or 'right')
        if marker_side == 'left':
            notes.append('ضع ##MAP_OVERVIEW## في عنصر يحمل data-map-summary-background، وعلامة الموقع في النصف الأيسر؛ ضع بطاقة الملخص كطبقة في اليمين تحمل data-map-summary-card ولا تغط العلامة.')
        else:
            notes.append('ضع ##MAP_OVERVIEW## في عنصر يحمل data-map-summary-background، وعلامة الموقع في النصف الأيمن؛ ضع بطاقة الملخص في اليسار تحمل data-map-summary-card ولا تغط العلامة.')
    if section_key == 'overview':
        notes.append('اعرض نبذة المشروع المعتمدة كنص واضح بلا أي رمز صورة؛ صور التصورات الخارجية مخصصة لقسمها فقط، وبلا تكرار مكونات المشروع التفصيلية.')
    if section_key in ('land', 'location', 'market'):
        notes.append('بعد الجداول أو البيانات، اكتب الملخص النهائي المحفوظ لهذا القسم مرة واحدة في نهاية الشريحة أو في آخر شريحة من القسم.')
    if section_key == 'closing':
        notes.append('استخدم الصورة الرئيسية بوضوح كخلفية كاملة أو صورة جانبية، واعرض شعاري الشركة والمشروع بالحجم الكبير نفسه. اعرض حقول التواصل المدخلة فقط كما هي؛ وإذا كانت فارغة فاقتصر على شكر موجز واسم المشروع دون أي بيانات وهمية. ممنوع كتابة «فرصة واعدة بشروط» أو أي تقييم استثماري.')
    if design_style == 'diagram' or slide.get('content_source') == 'land_boundary_diagram' or re.search(r'(?:مخطط اتجاهي|حدود الأرض|اتجاهي)', title):
        notes.append(
            'في شريحة المخطط الاتجاهي لحدود الأرض: صمّم هيكلاً اتجاهياً متناسقاً وراقياً بـ HTML و CSS النقي بألوان الهوية فقط ودون أيقونات أو إيموجي. '
            'يتوسط الشريحة صندوق عريض يمثل «أرض المشروع» مع أطوال الأضلاع الأربعة على حوافه وملخص الواجهات في وسطه، '
            'وتحيط به بطاقات واضحة للاتجاهات الأربعة (شمال، جنوب، شرق، غرب) توضح أطوال الأضلاع والمجاورات وعروض الشوارع والواجهات مع تمييز الشوارع بلون التمييز (مثل الذهبي)، '
            'وبطاقة بارزة ومميزة لجهة الإطلالة البحرية أو الطريق الرئيسي إن وجدت، '
            'مع كتابة «الأبعاد بالمتر» في الزاوية العلوية المقابلة للعنوان، وملاحظة توضيحية أسفل الشريحة: «تمثل القراءة اتجاهات الحدود وعلاقتها بالشوارع دون محاكاة مساحية للنسب.»'
        )
    if design_style == 'timeline' or re.search(r'(?:خطة|زمن|جدول|مراحل)', title):
        notes.append('اعرض مراحل الجدول الزمني كما وردت. أظهر الملاحظة بجانب مرحلتها فقط عندما يكون نصها موجودًا، ولا تنشئ حقل ملاحظات فارغًا لأي مرحلة.')
        timeline_note = _timeline_data_note(project_data)
        if timeline_note:
            notes.append(timeline_note.strip())
    if section_key == 'financial':
        notes.append('قالب تقرير الدراسة المالية ملزم: انقل جميع الجداول والمؤشرات المطلوبة بمسمياتها الأصلية وبالقيم والوحدات والترتيب نفسها، ولا تغيّر إلا ألوان الهوية والتنسيق المحدود.')
        notes.append('تصميم جداول تقرير PDF المالي هو التصميم الأساسي والإلزامي: انقل جميع الجداول والمؤشرات بمسمياتها الأصلية وبالقيم والترتيب نفسها، وطبّق ألوان الهوية فقط دون تغيير هيكل الجدول أو مساحاته.')
        notes.append('ممنوع منعاً باتاً: تحويل الجداول المالية إلى كروت عائمة (cards)، أو شبكة مربعات إحصائية (KPI boxes)، أو تصميم الشريحة على شكل 4 خانات عائمة أو شريحة بها خانة واحدة. يجب استخدام وسم <table> نظامي كامل بحدود واضحة 1px solid وخلفيات ترويسة هادئة.')
        notes.append('لجداول المؤشرات والملخصات (Key-Value): استخدم جدولاً بعمودين (<table class="summary-table">) بعرض 35%-40% لعمود اسم البند بخلفية هادئة بلون الهوية، وعمود القيمة بخط عريض bold وفواصل آلاف للأرقام. عند وجود جدولين مترابطين رصهما بجانب بعضهما في عمودين متجاورين (display:grid; grid-template-columns:1fr 1fr; gap:24px;) بنفس فكرة ومساحات تقرير PDF المالي.')
        notes.append('نسّق الأعداد بفواصل الآلاف للعرض فقط، من دون تقريب أو تحويل إلى ألف أو مليون أو تغيير عدد الخانات العشرية.')
        if chart_type:
            notes.append(f'أنشئ الرسم المحدد فقط ({chart_type}: {chart_note}) بجانب جدول مصدره، مع بقاء الجدول كاملًا ومقروءًا ومنع position:absolute للرسم أو الجدول أو النصوص.')
        else:
            notes.append('هذه الشريحة ليست واحدة من الرسوم المالية الثلاثة المعتمدة (waterfall, combo, heatmap)؛ اعرض جدول التقرير فقط وممنوع إضافة أي رسم بياني.')
        notes.append('الجدول لا يقل عن 12px ولا يزيد على 6 أعمدة في الشريحة، ويُقسّم على شرائح إضافية بدل التصغير أو القص.')
        financial_note = _financial_data_note(project_data)
        if financial_note and not source_note:
            notes.append(financial_note.strip())
    elif section_key == 'market':
        if chart_type == 'horizontal_bar':
            notes.append(f'أنشئ رسم مقارنة المنافسين المحدد ({chart_type}: {chart_note}) بجانب جدول المنافسين، مع بقاء الجدول كاملًا ومقروءًا ومنع اختراع أرقام أو متوسطات افتراضية.')
        else:
            notes.append('ممنوع إضافة أي رسم بياني في دراسة السوق إلا في شريحة مقارنة المنافسين المعتمدة (horizontal_bar).')
    else:
        notes.append('الرسوم البيانية ممنوعة تماماً في هذا القسم؛ اعرض المحتوى بالجداول أو النصوص أو الصور حسب النمط المحدد.')
    notes_text = '\n'.join(f'- {n}' for n in notes)

    return f"""أنشئ شريحة {slide_num}/{total_slides}: {title}
النوع: {slide_type}
نمط التصميم: {design_style} — {style_instructions}
{f'نوع الرسم المطلوب: {chart_type} — {chart_note}' if chart_note else ''}
كثافة المحتوى: {density} — {density_instructions}

النقاط الأساسية:
{bullets_text}

ملاحظات:
{notes_text}"""


def _block_external_images(html):
    """Block external image URLs (http/https) except allowed placeholders."""
    if not html:
        return html
    # ##STREET_VIEW_N## is deliberately absent: no such image exists, so an <img> carrying one is
    # removed here instead of surviving to be blanked into an empty frame.
    allowed = {'##MAP_OVERVIEW##', '##MAP_LANDMARKS##', '##MAP_ACCESS##', '##MAP_CATCHMENT##',
               '##IMAGE_COVER##', '##LOGO##', '##PROJECT_LOGO##', '##MOODBOARD_IMAGE_1##', '##MOODBOARD_IMAGE_2##',
               '##MOODBOARD_IMAGE_3##', '##MOODBOARD_IMAGE_4##'}

    def _replace_src(match):
        url = match.group(1)
        if any(url.startswith(p) for p in allowed) or url.startswith('##INTERIOR_') or url.startswith('##PLAN_IMAGE_') or url.startswith('##2D_PLAN_') or url.startswith('/uploads/') or url.startswith('/assets/'):
            return match.group(0)
        if url.startswith('http://') or url.startswith('https://') or url.startswith('data:'):
            return ''
        return match.group(0)

    # Remove <img src="external"> tags
    html = re.sub(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', _replace_src, html, flags=re.IGNORECASE)
    # Remove external background-image CSS values
    html = re.sub(r'background-image\s*:\s*url\(["\']?(https?://[^"\')]+|data:[^"\')]+)["\']?\)', '', html, flags=re.IGNORECASE)
    return html


def _ensure_map_placeholder(html, slide_type):
    """Ensure map slides contain the expected placeholder."""
    expected = {
        'map_overview': '##MAP_OVERVIEW##',
        'map_landmarks': '##MAP_LANDMARKS##',
        'map_access': '##MAP_ACCESS##',
        'map_catchment': '##MAP_CATCHMENT##',
    }
    if slide_type not in expected:
        return html
    marker = expected[slide_type]
    if marker in html:
        return html
    def apply(match):
        return _set_tag_style(
            match.group(0), ('background-image', 'background-size', 'background-position', 'background-repeat'),
            f'background-image:url({marker})!important;background-size:contain!important;'
            'background-position:center center!important;background-repeat:no-repeat!important;')

    html = re.sub(r'<div\b(?=[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b)[^>]*>',
                  apply, html, count=1, flags=re.IGNORECASE)
    print(f"[POST] Injected fallback placeholder {marker} into slide background")
    return html


def _set_tag_style(tag, property_names, declarations):
    style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', tag, re.IGNORECASE)
    if style_match:
        style = style_match.group(2)
        names = '|'.join(re.escape(name) for name in property_names)
        style = re.sub(rf'(?:^|;)\s*(?:{names})\s*:[^;]*;?', ';', style, flags=re.IGNORECASE)
        style = style.strip('; ')
        style = (style + ';' if style else '') + declarations
        return tag[:style_match.start(2)] + style + tag[style_match.end(2):]
    if tag.rstrip().endswith('/>'):
        position = tag.rfind('/>')
        return tag[:position].rstrip() + f' style="{declarations}" />'
    return tag.replace('>', f' style="{declarations}">', 1)


def _map_media_contain(html):
    indicators = ('MAP_', '/uploads/maps/', '/api/map-images/')

    def normalize_img(match):
        tag = match.group(0)
        if not any(indicator.lower() in tag.lower() for indicator in indicators):
            return tag
        return _set_tag_style(
            tag, ('object-fit', 'object-position', 'object-position-x', 'object-position-y'),
            'object-fit:contain!important;object-position:center center!important;')

    def normalize_background(match):
        tag = match.group(0)
        lowered = tag.lower()
        if 'background' not in lowered or not any(indicator.lower() in lowered for indicator in indicators):
            return tag
        return _set_tag_style(
            tag, ('background-size', 'background-position', 'background-position-x',
                  'background-position-y', 'background-repeat'),
            'background-size:contain!important;background-position:center center!important;'
            'background-repeat:no-repeat!important;')

    html = re.sub(r'<img\b[^>]*>', normalize_img, html, flags=re.IGNORECASE)
    return re.sub(r'<[a-z][^>]*\bstyle\s*=\s*["\'][^"\']*["\'][^>]*>',
                  normalize_background, html, flags=re.IGNORECASE)


def _ensure_map_summary_structure(html):
    opening_end = html.find('>')
    closing_start = html.rfind('</div>')
    if opening_end < 0 or closing_start <= opening_end:
        return html
    opening = html[:opening_end + 1]
    inner = html[opening_end + 1:closing_start]
    closing = html[closing_start:]
    inner = re.sub(r'<img\b[^>]*(?:##MAP_OVERVIEW##|/uploads/maps/|/api/map-images/)[^>]*>',
                   '', inner, flags=re.IGNORECASE)
    if 'data-map-summary-card' not in inner:
        inner = f'<div data-map-summary-card>{inner}</div>'
    background = ('<div data-map-summary-background '
                  'style="background-image:url(##MAP_OVERVIEW##);"></div>')
    return opening + background + inner + closing


def _location_data_timestamp(project_data):
    value = str((project_data or {}).get('location_data_fetched_at') or '').strip()
    if not value:
        return ''
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        saudi = parsed.astimezone(timezone(timedelta(hours=3)))
        return saudi.strftime('%Y-%m-%d %H:%M') + ' بتوقيت السعودية'
    except (TypeError, ValueError):
        return value


def _inject_location_data_timestamp(html, project_data):
    timestamp = _location_data_timestamp(project_data)
    if not timestamp or timestamp in html:
        return html
    label = html_lib.escape('آخر تحديث لبيانات الموقع: ' + timestamp)
    marker = (f'<div data-location-data-timestamp style="position:absolute;bottom:40px;right:24px;z-index:20;'
              f'font-size:11px;background:#ffffff;color:#172033;padding:4px 8px;border-radius:5px;">{label}</div>')
    return re.sub(r'(</div>\s*)$', marker + r'\1', html, count=1)


def _normalize_map_summary_layout(html, marker_side='right'):
    def normalize_background(match):
        return _set_tag_style(
            match.group(0),
            ('position', 'top', 'right', 'bottom', 'left', 'width', 'height', 'object-fit',
             'object-position', 'background-size', 'background-position', 'background-repeat', 'z-index'),
            'position:absolute!important;top:56px!important;right:0!important;bottom:36px!important;'
            'left:0!important;width:100%!important;height:calc(100% - 92px)!important;object-fit:contain!important;'
            'object-position:center center!important;background-size:contain!important;'
            'background-position:center center!important;background-repeat:no-repeat!important;z-index:0!important;')

    card_side = ('right:24px!important;left:auto!important;' if marker_side == 'left'
                 else 'left:24px!important;right:auto!important;')

    def normalize_card(match):
        return _set_tag_style(
            match.group(0), ('position', 'top', 'right', 'bottom', 'left', 'width', 'max-height', 'z-index'),
            'position:absolute!important;top:76px!important;bottom:56px!important;width:40%!important;'
            f'max-height:588px!important;z-index:2!important;{card_side}')

    html = re.sub(r'<[a-z][^>]*\bdata-map-summary-background\b[^>]*>',
                  normalize_background, html, flags=re.IGNORECASE)
    return re.sub(r'<[a-z][^>]*\bdata-map-summary-card\b[^>]*>',
                  normalize_card, html, flags=re.IGNORECASE)


_PRESENTATION_EXACT_NUMBER_CONTEXT = re.compile(
    r'تاريخ|هاتف|جوال|وثيقة|صك|مخطط|قطعة|معرف|إحداث|خط العرض|خط الطول|'
    r'phone|mobile|date|document|identifier|latitude|longitude|\blat\b|\blng\b|\bid\b',
    re.IGNORECASE,
)


def _format_presentation_numeric_text(html):
    parts = re.split(r'(<[^>]+>)', html)
    ignored = False
    number_pattern = re.compile(r'(?<![\d,٬])(-?(?:\d{4,}(?:\.\d+)?|\d+\.\d{2,}))(?![\d,٬])')

    def format_text(text, prefix=''):
        numeric_only = bool(re.fullmatch(r'\s*-?\d+(?:\.\d+)?%?\s*', text or ''))

        def format_number(match):
            value = match.group(1)
            window = (prefix[-64:] if numeric_only else '') + text[max(0, match.start() - 48):match.end() + 24]
            if _PRESENTATION_EXACT_NUMBER_CONTEXT.search(window):
                return value
            if '.' not in value and 1900 <= abs(int(value)) <= 2100:
                return value
            if '.' not in value and value.lstrip('-').startswith('0') and len(value.lstrip('-')) >= 7:
                return value
            try:
                rounded = Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
            except (InvalidOperation, ValueError):
                return value
            if rounded == rounded.to_integral_value():
                return f'{int(rounded):,}'
            return f'{rounded:,.1f}'

        return number_pattern.sub(format_number, text)

    recent_text = ''
    for index, part in enumerate(parts):
        if part.startswith('<'):
            if re.match(r'<\s*(?:style|script)\b', part, flags=re.IGNORECASE):
                ignored = True
            elif re.match(r'<\s*/\s*(?:style|script)\b', part, flags=re.IGNORECASE):
                ignored = False
        elif not ignored:
            parts[index] = format_text(part, recent_text)
            recent_text = (recent_text + ' ' + part)[-160:]
    return ''.join(parts)


def _normalize_table_readability(html):
    def normalize_table(match):
        return _set_tag_style(
            match.group(0), ('width', 'border-collapse', 'table-layout'),
            'width:100%!important;border-collapse:collapse!important;table-layout:fixed!important;')

    def normalize_header(match):
        return _set_tag_style(
            match.group(0), ('font-size', 'line-height', 'padding', 'overflow-wrap'),
            'font-size:13px!important;line-height:1.35!important;padding:8px!important;overflow-wrap:anywhere!important;')

    def normalize_cell(match):
        return _set_tag_style(
            match.group(0), ('font-size', 'line-height', 'padding', 'vertical-align', 'overflow-wrap'),
            'font-size:12px!important;line-height:1.4!important;padding:7px!important;vertical-align:middle!important;overflow-wrap:anywhere!important;')

    html = re.sub(r'<table\b[^>]*>', normalize_table, html, flags=re.IGNORECASE)
    html = re.sub(r'<th\b[^>]*>', normalize_header, html, flags=re.IGNORECASE)
    return re.sub(r'<td\b[^>]*>', normalize_cell, html, flags=re.IGNORECASE)


def _normalize_brand_overlay(html, branding):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    value = primary.lstrip('#')
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    html = re.sub(r'rgba\(\s*11\s*,\s*31\s*,\s*51\s*,\s*([0-9.]+)\s*\)',
                  lambda match: f'rgba({red},{green},{blue},{match.group(1)})', html, flags=re.IGNORECASE)
    return re.sub(r'#0b1f33\b', primary, html, flags=re.IGNORECASE)


def _normalize_cover_overlay_element(html, branding):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    value = primary.lstrip('#')
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))

    def normalize_overlay(match):
        return _set_tag_style(
            match.group(0), ('position', 'inset', 'background', 'z-index'),
            f'position:absolute!important;inset:0!important;background:linear-gradient(135deg,'
            f'rgba({red},{green},{blue},0.88) 0%,rgba({red},{green},{blue},0.55) 50%,'
            f'rgba({red},{green},{blue},0.92) 100%)!important;z-index:1!important;')

    return re.sub(r'<[a-z][^>]*\bdata-cover-overlay\b[^>]*>',
                  normalize_overlay, html, flags=re.IGNORECASE)


def _css_solid_color(value):
    text = re.sub(r'\s*!important\s*$', '', str(value or '').strip().lower())
    named = {'white': '#ffffff', 'black': '#000000', 'navy': '#000080'}
    if text in named:
        return named[text]
    if re.fullmatch(r'#[0-9a-f]{3}|#[0-9a-f]{6}', text):
        return normalize_hex_color(text)
    match = re.fullmatch(r'rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([\d.]+))?\s*\)', text)
    if not match or (match.group(4) is not None and float(match.group(4)) < 0.95):
        return None
    channels = [max(0, min(255, int(match.group(index)))) for index in (1, 2, 3)]
    return '#' + ''.join(f'{channel:02x}' for channel in channels)


def _inline_style_properties(style):
    properties = {}
    for declaration in str(style or '').split(';'):
        if ':' not in declaration:
            continue
        name, value = declaration.split(':', 1)
        properties[name.strip().lower()] = value.strip()
    return properties


class _SlideContrastAudit(HTMLParser):
    _VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.issues = []

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else ('', '#000000', '#ffffff')
        foreground, background = parent[1], parent[2]
        attributes = dict(attrs)
        styles = _inline_style_properties(attributes.get('style'))
        if 'color' in styles:
            foreground = _css_solid_color(styles['color'])
        background_value = styles.get('background-color') or styles.get('background')
        if background_value and background_value.lower() != 'transparent':
            background = _css_solid_color(background_value)
        state = (tag.lower(), foreground, background)
        if tag.lower() not in self._VOID_TAGS:
            self.stack.append(state)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == lowered:
                del self.stack[index:]
                break

    def handle_data(self, data):
        text = re.sub(r'\s+', ' ', data).strip()
        if not text or not self.stack or self.stack[-1][0] in ('style', 'script'):
            return
        foreground, background = self.stack[-1][1], self.stack[-1][2]
        if foreground and background:
            ratio = contrast_ratio(foreground, background)
            if ratio < 4.5:
                self.issues.append((text[:40], foreground, background, ratio))


def slide_contrast_issues(html):
    parser = _SlideContrastAudit()
    try:
        parser.feed(str(html or ''))
    except Exception:
        return []
    return parser.issues


def _required_slide_texts(slide, project_data):
    content_sources = (slide or {}).get('content_sources') if isinstance(slide, dict) else None
    if isinstance(content_sources, list) and content_sources:
        required = []
        for content_source in content_sources:
            item = dict(slide)
            item.pop('content_sources', None)
            item['content_source'] = content_source
            required.extend(_required_slide_texts(item, project_data))
        return list(dict.fromkeys(required))
    source = str((slide or {}).get('content_source') or '')
    project_data = project_data if isinstance(project_data, dict) else {}
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    if (slide or {}).get('type') == 'map_landmarks' or source == 'nearby_landmarks':
        matrix = project_data.get('landmarks_matrix')
        if isinstance(matrix, list):
            return list(dict.fromkeys(str(value).strip() for row in matrix if isinstance(row, dict)
                                      for value in row.values() if str(value or '').strip()))
        value = str(project_data.get('nearby_landmarks') or '').strip()
        return [item.strip() for item in re.split(r'[\n|]', value) if item.strip()]
    if source == 'market_study_data.swot':
        market = _decode_json_fact(project_data.get('market_study_data'))
        swot = market.get('swot') if isinstance(market, dict) and isinstance(market.get('swot'), dict) else {}
        return [str(value).strip() for value in swot.values() if str(value or '').strip()]
    if source == 'contact_closing':
        values = [str(project_data.get(key) or '').strip() for key in (
            'contact_name', 'contact_position', 'contact_phone', 'contact_email',
            'contact_website', 'contact_address', 'contact_social_media')]
        entered = [value for value in values if value]
        return entered or [str(project_data.get('project_name') or 'المشروع').strip(), 'شكر']

    def row_values(row):
        values = row.values() if isinstance(row, dict) else row if isinstance(row, (list, tuple)) else []
        return [str(value).strip() for value in values if str(value or '').strip()]

    def row_anchor(row):
        return next(iter(row_values(row)), '')

    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        return [str(row.get('اسم المكون') or '').strip()
                for row in _project_component_rows(project_data)[start:end]
                if str(row.get('اسم المكون') or '').strip()]
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        if part_index >= len(parts) or not isinstance(parts[part_index], dict):
            return []
        part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
        required = [str(header).strip() for header in (part.get('headers') or []) if str(header or '').strip()]
        required.extend(value for row in (part.get('rows') or []) for value in row_values(row))
        return list(dict.fromkeys(required))
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        return list(dict.fromkeys(value for row in rows[start:end] for value in row_values(row)))
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        group_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        group_name = 'التكاليف والاستثمار' if group_key == 'costs' else 'مؤشرات العائد والاسترداد'
        rows = _financial_summary_from_report(model).get(group_name, [])[start:end]
        return list(dict.fromkeys(value for row in rows for value in row_values(row)))
    if source == 'financial_indicators':
        summary = _financial_summary_from_report(model)
        return list(dict.fromkeys(value for rows in summary.values() for row in rows for value in row_values(row)))
    return []


def _missing_required_slide_texts(html, slide, project_data):
    visible = html_lib.unescape(re.sub(r'<[^>]+>', ' ', str(html or '')))

    def normalized(value):
        value = str(value or '').replace(',', '').replace('٬', '').replace('\u00a0', ' ')
        return re.sub(r'\s+', ' ', value).strip()

    compact = normalized(visible)
    return [text for text in _required_slide_texts(slide, project_data)
            if normalized(text) and normalized(text) not in compact]


def _fallback_table_data(slide, project_data):
    source = str((slide or {}).get('content_source') or '')
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
            return part.get('headers') or ['البند', 'القيمة'], part.get('rows') or []
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        name = 'التكاليف والاستثمار' if key == 'costs' else 'مؤشرات العائد والاسترداد'
        return ['البند', 'القيمة'], _financial_summary_from_report(model).get(name, [])[start:end]
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(key) if isinstance(tables.get(key), list) else []
        selected = rows[start:end]
        if selected and isinstance(selected[0], dict):
            headers = list(selected[0].keys())
            return headers, [[row.get(header, '') for header in headers] for row in selected]
        return [], selected
    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        rows = _project_component_rows(project_data)[start:end]
        headers = list(rows[0].keys()) if rows else []
        return headers, [[row.get(header, '') for header in headers] for row in rows]
    return [], []


def _render_fallback_table(headers, rows, primary):
    header_html = ''.join(
        f'<th style="background:{primary};color:#fff;padding:8px;font-size:13px;">{html_lib.escape(str(value))}</th>'
        for value in headers)
    body = []
    for row in rows:
        values = list(row.values()) if isinstance(row, dict) else list(row) if isinstance(row, (list, tuple)) else [row]
        body.append('<tr>' + ''.join(
            f'<td style="border:1px solid #dbe3ea;padding:7px;font-size:12px;overflow-wrap:anywhere;">{html_lib.escape(str(value))}</td>'
            for value in values) + '</tr>')
    return ('<table style="width:100%;border-collapse:collapse;table-layout:fixed;">'
            f'<thead><tr>{header_html}</tr></thead><tbody>{"".join(body)}</tbody></table>')


def _build_structured_fallback_slide(slide, project_data, branding):
    source = project_data if isinstance(project_data, dict) else {}
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    title = html_lib.escape(str((slide or {}).get('title') or 'المحتوى'))
    slide_type = str((slide or {}).get('type') or 'content')
    content_source = str((slide or {}).get('content_source') or '')
    tokens = [str(token) for token in ((slide or {}).get('image_tokens') or []) if str(token or '').strip()]
    if slide_type == 'cover':
        name = html_lib.escape(str(source.get('project_name') or source.get('projectName') or title))
        project_logo = '<img src="##PROJECT_LOGO##" style="height:80px;width:auto;object-fit:contain;">' if source.get('project_logo') else ''
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:{primary};color:#fff;">'
                '<div style="position:absolute;inset:0;background-image:url(##IMAGE_COVER##);background-size:cover;background-position:center;"></div>'
                '<div data-cover-overlay></div>'
                f'<div style="position:absolute;z-index:2;inset:64px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;">'
                f'<div style="display:flex;align-items:center;gap:18px;"><img src="##LOGO##" style="height:80px;width:auto;object-fit:contain;">{project_logo}</div>'
                f'<div style="font-size:48px;font-weight:800;">{name}</div></div></div>')
    if slide_type == 'closing':
        name = html_lib.escape(str(source.get('project_name') or source.get('projectName') or title))
        contact = html_lib.escape(_slide_source_data_note({'content_source': 'contact_closing'}, source)).replace('\n', '<br>')
        project_logo = '<img src="##PROJECT_LOGO##" style="height:80px;width:auto;object-fit:contain;">' if source.get('project_logo') else ''
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:{primary};color:#fff;">'
                '<div style="position:absolute;inset:0;background-image:url(##IMAGE_COVER##);background-size:cover;background-position:center;"></div>'
                '<div data-cover-overlay></div><div style="position:absolute;z-index:2;inset:70px;display:flex;flex-direction:column;justify-content:center;">'
                f'<div style="display:flex;gap:18px;align-items:center;"><img src="##LOGO##" style="height:80px;width:auto;object-fit:contain;">{project_logo}</div>'
                f'<h2 style="font-size:42px;margin:28px 0 16px;">{name}</h2><div style="font-size:18px;line-height:1.8;">{contact}</div></div></div>')
    if content_source in ('site_analysis', 'executive_content.summary'):
        note = html_lib.escape(_slide_source_data_note(slide, source)).replace('\n', '<br>')
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;">'
                '<div data-map-summary-background style="background-image:url(##MAP_OVERVIEW##);"></div>'
                f'<div data-map-summary-card style="background:{primary};color:#fff;padding:24px;overflow:hidden;">'
                f'<h2 style="font-size:28px;margin:0 0 18px;">{title}</h2><div style="font-size:14px;line-height:1.7;">{note}</div></div></div>')
    if slide_type == 'map_landmarks':
        matrix = source.get('landmarks_matrix') if isinstance(source.get('landmarks_matrix'), list) else []
        headers = list(matrix[0].keys()) if matrix and isinstance(matrix[0], dict) else []
        rows = [[row.get(header, '') for header in headers] for row in matrix if isinstance(row, dict)]
        table = _render_fallback_table(headers, rows, primary)
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:76px 28px 52px;box-sizing:border-box;">'
                f'<h2 style="font-size:26px;margin:0 0 14px;">{title}</h2><div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;height:540px;">'
                f'<img src="##MAP_LANDMARKS##" style="width:100%;height:100%;object-fit:contain;">'
                f'<div style="overflow:hidden;">{table}</div></div></div>')
    if tokens:
        columns = 1 if len(tokens) == 1 else len(tokens)
        images = ''.join(
            f'<img src="{html_lib.escape(token)}" style="width:100%;height:100%;object-fit:contain;min-width:0;min-height:0;">'
            for token in tokens)
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:76px 28px 52px;box-sizing:border-box;">'
                f'<h2 style="font-size:26px;margin:0 0 14px;">{title}</h2>'
                f'<div style="display:grid;grid-template-columns:repeat({columns},1fr);gap:12px;height:540px;">{images}</div></div>')
    headers, rows = _fallback_table_data(slide, source)
    if rows:
        table = _render_fallback_table(headers, rows, primary)
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:76px 28px 52px;box-sizing:border-box;">'
                f'<h2 style="font-size:26px;margin:0 0 16px;color:{primary};">{title}</h2>{table}</div>')
    note = _slide_source_data_note(slide, source) or '\n'.join(str(item) for item in ((slide or {}).get('bullets') or []))
    if note:
        content = html_lib.escape(note).replace('\n', '<br>')
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:90px 48px 60px;box-sizing:border-box;">'
                f'<h2 style="font-size:28px;color:{primary};">{title}</h2><div style="font-size:16px;line-height:1.8;">{content}</div></div>')
    return None


def generate_single_slide(system_prompt, slide, slide_num, total_slides, branding, call_glm_fn, max_retries=2, project_data=None):
    """
    Generate a single slide's HTML.
    call_glm_fn: function(system_prompt, user_msg, max_tokens) -> response_dict
    """
    # A section divider is one fixed layout with different text, so it is rendered here instead of
    # being asked from the model on every deck: identical on every divider, and no call at all.
    if (slide or {}).get('type') == 'index':
        return build_index_slide(slide, slide_num, total_slides, branding, project_data)
    if (slide or {}).get('type') == 'section_divider':
        return build_section_divider_slide(slide, slide_num, total_slides, branding, project_data)

    user_msg = build_slide_user_msg(slide, slide_num, total_slides, branding, project_data=project_data)
    slide_title = slide.get('title', f'شريحة {slide_num}')
    slide_type = slide.get('type', 'content')
    retry_note = ''

    for attempt in range(1, max_retries + 2):
        try:
            print(f"[SLIDE-{slide_num}] Attempt {attempt}: {slide_title}")
            response = call_glm_fn(system_prompt, user_msg + retry_note, max_tokens=6000)
            if 'choices' not in response or not response['choices']:
                print(f"[SLIDE-{slide_num}] ERROR: no choices (attempt {attempt})")
                continue

            content = response['choices'][0].get('message', {}).get('content', '')
            html = extract_html_from_glm(content)
            if not html:
                print(f"[SLIDE-{slide_num}] ERROR: no HTML extracted (attempt {attempt})")
                retry_note = '\n\nإعادة المحاولة: لم يصل HTML صالح. أخرج div class="slide" واحدًا مكتملًا فقط.'
                continue
            content_source = str(slide.get('content_source') or '')
            if not slide.get('chart_type') and re.search(
                    r'(?:data-chart|class\s*=\s*["\'][^"\']*(?:chart|treemap|heatmap)|conic-gradient\s*\()',
                    html, flags=re.IGNORECASE):
                print(f"[SLIDE-{slide_num}] ERROR: unplanned chart outside selected financial charts (attempt {attempt})")
                retry_note = '\n\nإعادة المحاولة: هذه الشريحة لا تحمل chart_type؛ احذف الرسم البياني واعرض النص أو الجدول فقط.'
                continue
            if _slide_section_key(slide) == 'financial' and not slide.get('chart_type') and '<table' not in html.lower():
                print(f"[SLIDE-{slide_num}] ERROR: financial slide must use table, not cards/boxes (attempt {attempt})")
                retry_note = '\n\nإعادة المحاولة: شريحة الدراسة المالية ملزمة باستخدام جداول HTML نظامية (table) بتصميم تقرير PDF. احذف الكروت العائمة والمربعات واعرض البيانات داخل جدول كامل.'
                continue
            missing_images = [token for token in (slide.get('image_tokens') or []) if token not in html]
            if missing_images:
                missing = '، '.join(missing_images)
                print(f"[SLIDE-{slide_num}] ERROR: missing required images: {missing} (attempt {attempt})")
                retry_note = (
                    f'\n\nإعادة المحاولة: الاستجابة السابقة حذفت الصور الإلزامية التالية: {missing}. '
                    'أعد الشريحة كاملة واستخدم كل رمز صورة مرة واحدة فقط وبحجم واضح.'
                )
                continue
            missing_texts = _missing_required_slide_texts(html, slide, project_data)
            if missing_texts:
                missing = '، '.join(missing_texts[:12])
                print(f"[SLIDE-{slide_num}] ERROR: missing required content: {missing} (attempt {attempt})")
                retry_note = (
                    f'\n\nإعادة المحاولة: الاستجابة السابقة حذفت البنود الإلزامية التالية: {missing}. '
                    'أعد الشريحة كاملة وانقل كل صف مطلوب دون اختصار أو حذف.'
                )
                continue
            contrast_issues = slide_contrast_issues(html)
            if contrast_issues:
                sample, foreground, surface, ratio = contrast_issues[0]
                print(f"[SLIDE-{slide_num}] ERROR: contrast {ratio:.2f}:1 for {foreground} on {surface} (attempt {attempt})")
                retry_note = (
                    f'\n\nإعادة المحاولة: فشل التباين في النص «{sample}»: اللون {foreground} فوق {surface} '
                    f'بنسبة {ratio:.2f}:1. أعد الشريحة كاملة واجعل كل نص 4.5:1 على الأقل، ولا تغيّر المحتوى.'
                )
                continue

            html = postprocess_slide(
                html, slide_type, slide_num=slide_num, slide_title=slide_title,
                total_slides=total_slides, tenant_id=branding.get('tenant_id'),
                branding=branding, project_data=project_data)
            roots = extract_slide_elements(html)
            if len(roots) == 1:
                print(f"[SLIDE-{slide_num}] OK: {len(html)} chars")
                return roots[0]
            print(f"[SLIDE-{slide_num}] ERROR: expected one slide div, found {len(roots)} (attempt {attempt})")
            retry_note = f'\n\nإعادة المحاولة: أخرج جذر شريحة واحدًا فقط؛ الاستجابة السابقة احتوت {len(roots)} جذور.'
        except Exception as e:
            print(f"[SLIDE-{slide_num}] Exception: {e}")

    fallback = _build_structured_fallback_slide(slide, project_data, branding)
    if fallback:
        fallback = postprocess_slide(
            fallback, slide_type, slide_num=slide_num, slide_title=slide_title,
            total_slides=total_slides, tenant_id=branding.get('tenant_id'),
            branding=branding, project_data=project_data)
        roots = extract_slide_elements(fallback)
        if len(roots) == 1:
            print(f"[SLIDE-{slide_num}] Using deterministic fallback after {max_retries + 1} attempts")
            return roots[0]
    print(f"[SLIDE-{slide_num}] FAILED after {max_retries + 1} attempts")
    return None


def _canonicalize_slide_root_class(html):
    match = re.match(r'^(<div\b[^>]*?)\bclass\s*=\s*(["\'])([^"\']*)\2', str(html or '').lstrip(), re.IGNORECASE)
    if not match or 'slide' not in match.group(3).split():
        return html
    stripped = str(html or '').lstrip()
    leading = str(html or '')[:len(str(html or '')) - len(stripped)]
    return leading + match.group(1) + 'class="slide"' + stripped[match.end():]


def extract_html_from_glm(content):
    """Extract HTML from GLM response content."""
    if not content:
        return None

    # Try to extract from code block first
    code_match = re.search(r'```(?:html)?\s*\n?([\s\S]*?)```', content)
    if code_match:
        html = code_match.group(1).strip()
    else:
        html = content.strip()

    # Basic cleanup
    html = html.replace('```html', '').replace('```', '').strip()

    slides = extract_slide_elements(html)
    if slides:
        return '\n'.join(_canonicalize_slide_root_class(slide) for slide in slides)

    # If no slide div, wrap the whole HTML in one as a fallback
    if 'class="slide"' not in html and "class='slide'" not in html:
        if '<html' in html or '<body' in html or '<div' in html:
            html = f'<div class="slide" style="width:1280px;height:720px;direction:rtl;font-family:sans-serif;">{html}</div>'
        else:
            return None

    return html


# ─────────────────────────────────────────────────────────────────────────────
# Full Slide Generation (Parallel)
# ─────────────────────────────────────────────────────────────────────────────

def _replace_map_placeholders(html, map_placeholders):
    """Replace map image placeholders with actual URLs/paths."""
    if not html or not map_placeholders:
        return html
    for placeholder, path in map_placeholders.items():
        if path:
            html = html.replace(placeholder, path)

    # Fallback: if the model used the generic placeholder but only a satellite/roadmap
    # variant was generated, substitute the first available variant.
    base_variants = {
        '##MAP_OVERVIEW##': [
            '##MAP_OVERVIEW_SATELLITE##',
            '##MAP_OVERVIEW_ROADMAP##',
        ],
        '##MAP_LANDMARKS##': [
            '##MAP_LANDMARKS_SATELLITE##',
            '##MAP_LANDMARKS_ROADMAP##',
        ],
        '##MAP_ACCESS##': [
            '##MAP_ACCESS_SATELLITE##',
            '##MAP_ACCESS_ROADMAP##',
        ],
        '##MAP_CATCHMENT##': [
            '##MAP_CATCHMENT_SATELLITE##',
            '##MAP_CATCHMENT_ROADMAP##',
        ],
    }
    for base, variants in base_variants.items():
        if base in html:
            for variant in variants:
                path = map_placeholders.get(variant)
                if path:
                    html = html.replace(base, path)
                    break
    return html


def _creative_image_values(images):
    """Return the generated cover and moodboard image URLs in a safe shape with fallbacks."""
    if not isinstance(images, dict):
        return '', []
    cover = images.get('cover') or images.get('mainImageData') or ''
    moodboard = images.get('moodboard') or images.get('moodboardImages') or []
    if not isinstance(moodboard, list):
        moodboard = []
    return str(cover), [str(img) if img else '' for img in moodboard]


def _moodboard_url(index, moodboard):
    """Pick the exact uploaded/generated image for a moodboard token."""
    if index < len(moodboard) and moodboard[index]:
        return moodboard[index]
    return ''


def _css_url(image_url):
    """Escape the small subset of characters that can break url('...') CSS."""
    return image_url.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '').replace('\r', '')


def _build_moodboard_fallback(images):
    """Build a deterministic moodboard layout matching the exact number of images."""
    images = [str(image) for image in (images or []) if image]
    count = len(images)

    # Dynamic CSS grid layout calculation based on image count
    if count <= 1:
        cols, rows = "1fr", "1fr"
    elif count == 2:
        cols, rows = "1fr 1fr", "1fr"
    elif count <= 4:
        cols, rows = "1fr 1fr", "1fr 1fr"
    elif count <= 6:
        cols, rows = "1fr 1fr 1fr", "1fr 1fr"
    elif count <= 8:
        cols, rows = "1fr 1fr 1fr 1fr", "1fr 1fr"
    else:
        cols, rows = f"repeat(auto-fill, minmax(220px, 1fr))", "auto"

    tiles = []
    for image in images:
        background = "background-image:url('" + _css_url(image) + "');"
        tiles.append(
            '<div style="min-width:0;min-height:0;background-size:cover;background-position:center;'
            + background + '"></div>'
        )
    return (
        '<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;'
        'background:#171717;color:#fff;font-family:Arial,sans-serif;box-sizing:border-box;padding:42px;">'
        '<div style="display:flex;align-items:center;justify-content:space-between;height:52px;margin-bottom:20px;">'
        '<div style="font-size:30px;font-weight:700;">لوحة الإلهام (Moodboard)</div>'
        '<div style="width:170px;height:4px;background:#C2A176;"></div></div>'
        f'<div style="height:560px;display:grid;grid-template-columns:{cols};grid-template-rows:{rows};gap:8px;">'
        + ''.join(tiles) + '</div></div>'
    )


def _hex_to_rgba(color, alpha):
    """CSS rgba() from a #rgb/#rrggbb brand colour, so the veil follows the tenant's palette."""
    value = str(color or '').strip().lstrip('#')
    if len(value) == 3:
        value = ''.join(part * 2 for part in value)
    if len(value) != 6:
        value = '0b1f33'
    try:
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        red, green, blue = 11, 31, 51
    return f'rgba({red},{green},{blue},{alpha})'


def build_index_slide(slide, slide_num, total_slides, branding=None, project_data=None):
    branding = branding or {}
    slide = slide or {}
    background = normalize_hex_color(branding.get('background_color'), '#f8fafc')
    text_color = readable_text_color(branding.get('text_color'), background)
    primary = readable_text_color(branding.get('primary_color'), background, (text_color,))
    accent = readable_text_color(branding.get('accent_color'), background, (primary, text_color))
    separator = _hex_to_rgba(text_color, '0.30')
    slide_ratio = branding.get('slide_ratio', '16:9')
    width, height = (1280, 960) if slide_ratio == '4:3' else (1280, 720)
    entries = [entry for entry in (slide.get('index_entries') or []) if isinstance(entry, dict)]
    midpoint = (len(entries) + 1) // 2

    def column(items):
        rows = []
        for entry in items:
            title = html_lib.escape(str(entry.get('title') or '').strip())
            section_key = html_lib.escape(str(entry.get('section_key') or '').strip(), quote=True)
            try:
                page = int(entry.get('page'))
            except (TypeError, ValueError):
                page = 0
            rows.append(
                f'<div data-index-section="{section_key}" style="min-height:48px;display:flex;align-items:center;gap:18px;'
                f'border-bottom:1px solid {separator};padding:9px 2px;box-sizing:border-box;">'
                f'<div style="font-size:16px;font-weight:600;color:{text_color};flex:1;">{title}</div>'
                f'<div data-index-page="{section_key}" dir="ltr" style="font-size:16px;font-weight:700;color:{accent};min-width:34px;'
                f'text-align:left;">{page:02d}</div></div>'
            )
        return ''.join(rows)

    columns = [entries[:midpoint], entries[midpoint:]]
    return (
        f'<div class="slide" dir="rtl" style="width:{width}px;height:{height}px;position:relative;'
        f'overflow:hidden;box-sizing:border-box;background:{background};color:{text_color};">'
        f'<div style="position:absolute;top:82px;right:52px;left:52px;bottom:58px;box-sizing:border-box;">'
        f'<div style="font-size:30px;font-weight:700;color:{primary};margin-bottom:24px;">محتويات العرض</div>'
        f'<div style="width:86px;height:3px;background:{accent};margin-bottom:24px;"></div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:26px 54px;align-items:start;">'
        f'<div>{column(columns[0])}</div><div>{column(columns[1])}</div>'
        '</div></div></div>'
    )


def build_section_divider_slide(slide, slide_num, total_slides, branding=None, project_data=None):
    """Render a section divider: the main image, darkened, with the section name over it.

    The layout is identical on every divider and only the text changes, so it is built here
    instead of being asked from the model on every deck: that keeps all dividers pixel-identical,
    costs no tokens, and cannot drift between slides.
    """
    branding = branding or {}
    project_data = project_data or {}
    slide = slide or {}
    primary = normalize_hex_color(branding.get('primary_color'), '#0b1f33')
    divider_background = dark_surface_color(primary, branding.get('secondary_color'))
    accent = readable_text_color(branding.get('accent_color'), divider_background, ('#ffffff',))
    slide_ratio = branding.get('slide_ratio', '16:9')
    width, height = (1280, 960) if slide_ratio == '4:3' else (1280, 720)

    title = html_lib.escape(str(slide.get('title') or 'القسم').strip())
    project_name = html_lib.escape(str(project_data.get('project_name') or project_data.get('projectName') or '').strip())
    project_logo = str(project_data.get('project_logo') or '').strip()

    logos = '<img src="##LOGO##" alt="" style="height:80px;width:auto;object-fit:contain;" />'
    if project_logo:
        logos += (
            f'<div style="width:1px;height:52px;background:rgba(255,255,255,0.35);margin:0 18px;"></div>'
            '<img src="##PROJECT_LOGO##" alt="" style="height:80px;width:auto;object-fit:contain;" />'
        )

    rule = f'<div style="width:200px;height:3px;background:{accent};margin:18px 0 0 auto;"></div>'
    footer_number = f'{slide_num:02d} — {int(total_slides or slide_num):02d}' if slide_num else ''

    return (
        f'<div class="slide" dir="rtl" style="width:{width}px;height:{height}px;position:relative;'
        f'overflow:hidden;box-sizing:border-box;background:{divider_background};">'
        # The approved main image, full bleed.
        '<div style="position:absolute;top:0;right:0;left:0;bottom:0;background-image:url(##IMAGE_COVER##);'
        'background-size:cover;background-position:center center;"></div>'
        # Navy veil: dark enough for white text on any photo, light enough that the photo shows.
        f'<div style="position:absolute;top:0;right:0;left:0;bottom:0;background:linear-gradient(160deg,'
        f'{_hex_to_rgba(divider_background, "0.94")} 0%,{_hex_to_rgba(divider_background, "0.82")} 45%,'
        f'{_hex_to_rgba(divider_background, "0.62")} 100%);"></div>'
        f'<div style="position:absolute;top:0;bottom:0;left:0;width:10px;background:{accent};"></div>'
        f'<div style="position:absolute;top:44px;left:48px;display:flex;align-items:center;">{logos}</div>'
        # padding-bottom biases the block slightly above the optical centre, as in the reference.
        '<div style="position:absolute;top:0;bottom:0;right:64px;width:58%;display:flex;flex-direction:column;'
        'justify-content:center;text-align:right;padding-bottom:56px;box-sizing:border-box;">'
        f'<div style="font-size:58px;line-height:1.15;font-weight:700;color:#ffffff;">{title}</div>'
        f'{rule}'
        '</div>'
        # dir="ltr": inside the RTL slide "06 — 60" would be reordered into "60 — 06".
        f'<div data-slide-counter="1" dir="ltr" style="position:absolute;bottom:34px;left:48px;font-size:13px;letter-spacing:1px;'
        f'color:rgba(255,255,255,0.55);">{footer_number}</div>'
        f'<div style="position:absolute;bottom:34px;right:48px;font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;color:{accent};">{project_name}</div>'
        '</div>'
    )


def _replace_creative_image_placeholders(html, creative_images, slide_type, content_source=None):
    """Resolve image tokens after generation so browser previews always have real sources."""
    if not html:
        return html
    cover, moodboard = _creative_image_values(creative_images)

    # Replace cover tokens
    for cover_pat in [r'#*IMAGE_COVER#*', r'#*COVER_IMAGE#*', r'#*MAIN_IMAGE#*', r'#*PROJECT_IMAGE_COVER#*']:
        html = re.sub(cover_pat, cover, html, flags=re.IGNORECASE)

    # Replace moodboard & project image tokens (including malformed variations)
    def _replace_moodboard_token(match):
        index = int(match.group(1)) - 1
        return _moodboard_url(index, moodboard)

    html = re.sub(r'#*MOODBOARD_IMAGE_(\d+)#*', _replace_moodboard_token, html, flags=re.IGNORECASE)
    html = re.sub(r'#*PROJECT_IMAGE_(\d+)#*', _replace_moodboard_token, html, flags=re.IGNORECASE)

    land_photos = creative_images.get('land_photos') if isinstance(creative_images, dict) else []
    for index, item in enumerate(land_photos if isinstance(land_photos, list) else [], 1):
        source = item if isinstance(item, dict) else {'url': item}
        url = str(source.get('url') or source.get('imageUrl') or '').strip()
        if url:
            html = re.sub(rf'#*LAND_(?:PHOTO|IMAGE)_{index}#*', _css_url(url), html, flags=re.IGNORECASE)

    team_members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
    for index, item in enumerate(team_members if isinstance(team_members, list) else [], 1):
        source = item if isinstance(item, dict) else {'logo': item}
        url = str(source.get('logo') or source.get('url') or '').strip()
        if url:
            html = re.sub(rf'#*TEAM_LOGO_{index}#*', _css_url(url), html, flags=re.IGNORECASE)

    competitor_logos = creative_images.get('competitor_logos') if isinstance(creative_images, dict) else []
    for index, item in enumerate(competitor_logos if isinstance(competitor_logos, list) else [], 1):
        source = item if isinstance(item, dict) else {'logo': item}
        url = str(source.get('logo') or source.get('url') or '').strip()
        if url:
            html = re.sub(rf'#*COMPETITOR_LOGO_{index}#*', _css_url(url), html, flags=re.IGNORECASE)
    html = re.sub(r'#*COMPETITOR_LOGO_\d+#*', '', html, flags=re.IGNORECASE)

    # Replace component-specific interior tokens
    interior_comps = []
    if isinstance(creative_images, dict):
        interior_comps = creative_images.get('interior_components') or []
    for c_idx, comp in enumerate(interior_comps, 1):
        c_imgs = comp.get('images', []) if isinstance(comp, dict) else []
        for j_idx, img_item in enumerate(c_imgs, 1):
            url = img_item.get('url', '') if isinstance(img_item, dict) else str(img_item or '')
            if url:
                css_u = _css_url(url)
                html = re.sub(rf'#*INTERIOR_COMP_{c_idx}_(?:IMG|IMAGE)_{j_idx}#*', css_u, html, flags=re.IGNORECASE)
                html = re.sub(rf'#*INTERIOR_C{c_idx}_(?:IMG|IMAGE)_{j_idx}#*', css_u, html, flags=re.IGNORECASE)
                html = re.sub(rf'#*INTERIOR_{c_idx}_{j_idx}#*', css_u, html, flags=re.IGNORECASE)

    # Replace flat interior tokens
    interiors = []
    if isinstance(creative_images, dict):
        interiors = creative_images.get('interior') or creative_images.get('interior_images') or []
        if not isinstance(interiors, list):
            interiors = [interiors]
    for idx, url in enumerate(interiors):
        num = idx + 1
        if url:
            html = re.sub(rf'#*INTERIOR_IMAGE_{num}#*', _css_url(str(url)), html, flags=re.IGNORECASE)
    html = re.sub(r'#*INTERIOR_(?:COMP_\d+_(?:IMG|IMAGE)_\d+|C\d+_(?:IMG|IMAGE)_\d+|\d+_\d+|IMAGE_\d+|\d+)#*', '', html, flags=re.IGNORECASE)

    # Replace 2D plan tokens
    plans = []
    if isinstance(creative_images, dict):
        plans = creative_images.get('plans') or creative_images.get('plans2d') or []
        if not isinstance(plans, list):
            plans = [plans]
    for idx, url in enumerate(plans):
        num = idx + 1
        if url:
            html = re.sub(rf'#*PLAN_IMAGE_{num}#*', _css_url(str(url)), html, flags=re.IGNORECASE)
            html = re.sub(rf'#*2D_PLAN_{num}#*', _css_url(str(url)), html, flags=re.IGNORECASE)
    html = re.sub(r'#*(?:PLAN_IMAGE|2D_PLAN)_\d+#*', '', html, flags=re.IGNORECASE)

    # Do not leave the cover blank simply because the model forgot its token.
    if slide_type == 'cover' and cover and cover not in html:
        background = (
            '<div aria-hidden="true" style="position:absolute;inset:0;z-index:0;'
            "background-image:url('" + _css_url(cover) + "');background-size:cover;background-position:center;\"></div>"
        )
        html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1' + background, html, count=1)

    # A moodboard slide should show the exact moodboard images
    if slide_type == 'moodboard' or 'moodboard' in str(slide_type).lower() or 'مودبورد' in html:
        if any(moodboard) and not re.search(r'<img|background-image', html, re.IGNORECASE):
            html = _build_moodboard_fallback(moodboard)
    logo_items = []
    for item in competitor_logos if isinstance(competitor_logos, list) else []:
        source = item if isinstance(item, dict) else {'logo': item}
        url = str(source.get('logo') or source.get('url') or '').strip()
        if url:
            logo_items.append((str(source.get('name') or '').strip(), url))
    missing_logo_items = [(name, url) for name, url in logo_items if url not in html]
    if str(content_source or '').startswith('market_study_data') and missing_logo_items:
        logos = ''.join(
            '<img src="' + html_lib.escape(url, quote=True) + '" alt="' + html_lib.escape(name, quote=True)
            + '" style="width:64px;height:40px;object-fit:contain;background:#fff;border-radius:7px;padding:4px;box-sizing:border-box;">'
            for name, url in missing_logo_items[:6]
        )
        strip = ('<div data-competitor-logos="1" style="position:absolute;left:50px;bottom:58px;z-index:20;'
                 'display:flex;gap:8px;align-items:center;">' + logos + '</div>')
        html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1' + strip, html, count=1)
    return html


def _replace_data_placeholders(html, project_data, branding=None):
    """Replace all field & data tokens (like ##PROJECT_NAME##, ##land_area##, ##noi##, ##LOGO##) with real values."""
    if not html:
        return html

    project_data = project_data or {}
    branding = branding or {}

    replacements = {}

    # 1. Logo replacement
    logo_url = branding.get('logo_path') or branding.get('logo') or branding.get('logo_url')
    if not logo_url:
        print('[REPLACE] WARNING: no logo_path in branding; falling back to /assets/logo.png')
        logo_url = '/assets/logo.png'
    elif not logo_url.startswith('/') and not logo_url.startswith('http'):
        logo_url = f"/{logo_url.lstrip('/')}"
    replacements['##LOGO##'] = logo_url

    # 2. Add all dynamic key-value pairs from project_data
    for k, v in project_data.items():
        if v is None or isinstance(v, (dict, list)):
            continue
        val_str = str(v)
        replacements[f'##{k}##'] = val_str
        replacements[f'##{k.lower()}##'] = val_str
        replacements[f'##{k.upper()}##'] = val_str

    # 3. Known key aliases & fallback mappings for template placeholders
    aliases = {
        'PROJECT_NAME': project_data.get('project_name') or project_data.get('projectName') or project_data.get('name') or 'المشروع الاستثماري',
        'PROJECT_TYPE': project_data.get('project_type') or project_data.get('projectType') or 'مشروع عقاري',
        'PROJECT_DESCRIPTION': project_data.get('project_description') or project_data.get('description') or '',
        'land_area': project_data.get('land_area') or project_data.get('total_area_sqm') or project_data.get('landArea') or '—',
        'built_area': project_data.get('built_area') or project_data.get('total_built_area') or project_data.get('builtArea') or '—',
        'location_address': project_data.get('location_address') or project_data.get('location') or project_data.get('address') or 'المملكة العربية السعودية',
        'location_lat': str(project_data.get('location_lat') or project_data.get('lat') or ''),
        'location_lng': str(project_data.get('location_lng') or project_data.get('lng') or ''),
        'altsnyf_altkhtyty': project_data.get('altsnyf_altkhtyty') or project_data.get('zoning') or project_data.get('planning_classification') or '—',
        'building_system': project_data.get('building_system') or project_data.get('buildingSystem') or '—',
        'nsba_albna__far': project_data.get('nsba_albna__far') or project_data.get('far') or project_data.get('building_ratio') or '—',
        'plot_number': project_data.get('plot_number') or project_data.get('plotNumber') or project_data.get('plan_number') or '—',
        'infrastructure': project_data.get('infrastructure') or project_data.get('utilities') or 'مكتملة الخدمات',
        'budget': project_data.get('budget') or project_data.get('total_cost') or project_data.get('totalCost') or '—',
        'noi': project_data.get('noi') or project_data.get('annual_profit') or project_data.get('net_operating_income') or '—',
        'roi': project_data.get('roi') or project_data.get('return_on_investment') or '—',
        'alqrma_almdafa_almtwqaa__cap_rate': project_data.get('cap_rate') or project_data.get('capRate') or project_data.get('alqrma_almdafa_almtwqaa__cap_rate') or '—',
        'nsba_alashgal_almtwqaa': project_data.get('occupancy_rate') or project_data.get('occupancy') or '—',
        'PROJECT_LOGO': project_data.get('project_logo') or project_data.get('projectLogo') or '',
    }

    for a_key, a_val in aliases.items():
        if a_val is not None:
            val_s = str(a_val)
            replacements[f'##{a_key}##'] = val_s
            replacements[f'##{a_key.lower()}##'] = val_s
            replacements[f'##{a_key.upper()}##'] = val_s

    # Perform replacements
    for token, value in replacements.items():
        if token in html:
            html = html.replace(token, value)

    # Regex search for any custom tokens generated by LLM (e.g. ##custom_key##)
    def token_replacer(match):
        token_str = match.group(0)
        # An image token is left standing for _drop_unresolved_image_placeholders to deal with.
        # Blanking it here is what produced empty framed boxes: src="" / url() render as a card
        # with nothing in it, and the reader saw it as part of the design.
        if IMAGE_TOKEN_RE.fullmatch(token_str):
            return token_str
        raw_key = token_str.replace('##', '').strip()
        for k, v in project_data.items():
            if k.lower() == raw_key.lower() and v is not None:
                return str(v)
        return ''

    html = re.sub(r'##[a-zA-Z0-9_]+##', token_replacer, html)

    return html


# A token naming an image. Anything matching this that survives the whole pipeline has no image
# behind it, so its carrier is removed rather than emptied.
IMAGE_TOKEN_RE = re.compile(
    r'##[A-Za-z0-9_]*(?:IMAGE|IMG|PHOTO|STREET_VIEW|MAP_|PLAN|INTERIOR|MOODBOARD|COVER|LOGO)[A-Za-z0-9_]*##',
    re.IGNORECASE,
)


def _drop_unresolved_image_placeholders(html):
    """Remove image carriers that ended up with no image, instead of leaving an empty frame.

    A slide came out with four empty cards because it used ##STREET_VIEW_1..4##, which no workflow
    produces: the tokens were blanked into `src=""` / `url()` and the frames stayed. An image that
    does not exist must leave nothing behind, not a hole.
    """
    if not html:
        return html
    html = re.sub(r'<img\b[^>]*>',
                  lambda m: '' if IMAGE_TOKEN_RE.search(m.group(0)) else m.group(0),
                  html, flags=re.IGNORECASE)
    # background / background-image declarations pointing at a leftover token or at nothing.
    html = re.sub(r'background(?:-image)?\s*:\s*url\(\s*["\']?[^)"\']*##[^)"\']*["\']?\s*\)\s*;?',
                  '', html, flags=re.IGNORECASE)
    html = re.sub(r'background(?:-image)?\s*:\s*url\(\s*["\']?\s*["\']?\s*\)\s*;?',
                  '', html, flags=re.IGNORECASE)
    html = re.sub(r'<img\b[^>]*src=["\']\s*["\'][^>]*>', '', html, flags=re.IGNORECASE)
    # Whatever token text is left is not an image reference the reader should see.
    return IMAGE_TOKEN_RE.sub('', html)


def _apply_logo_contrast_styles(html, branding, project_data, slide_type='content'):
    if not html:
        return html
    branding = branding or {}
    project_data = project_data or {}
    dark_background = dark_surface_color(
        branding.get('primary_color'), branding.get('secondary_color'))
    profiles = {
        '##LOGO##': str(project_data.get('_company_logo_tone') or branding.get('_logo_tone') or 'unknown').lower(),
        '##PROJECT_LOGO##': str(project_data.get('_project_logo_tone') or 'unknown').lower(),
    }

    content_header = slide_type not in ('cover', 'closing', 'moodboard', 'section_divider')
    hero_logo = slide_type in ('cover', 'closing', 'section_divider')

    def style_token(source, token, tone):
        background = dark_background if tone == 'light' else '#ffffff'
        size = ('height:48px!important;max-height:48px!important;' if content_header else
                'height:80px!important;max-height:80px!important;' if hero_logo else '')
        padding = '4px 10px' if content_header else '6px 12px'
        declarations = (
            f'{size}background:{background}!important;padding:{padding}!important;'
            'border-radius:8px!important;box-sizing:border-box!important;object-fit:contain!important;'
        )

        def apply(match):
            tag = match.group(0)
            style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', tag, re.IGNORECASE)
            if style_match:
                style = style_match.group(2).rstrip(';') + ';' + declarations
                return tag[:style_match.start(2)] + style + tag[style_match.end(2):]
            return tag.replace('<img', f'<img style="{declarations}"', 1)

        pattern = rf'<img\b(?=[^>]*\bsrc\s*=\s*["\'][^"\']*{re.escape(token)}[^"\']*["\'])[^>]*>'
        return re.sub(pattern, apply, source, flags=re.IGNORECASE)

    for token, tone in profiles.items():
        html = style_token(html, token, tone)
    return html


def resolve_logo_in_html(html, tenant_id=None, _branding_cache=None, project_logo=None):
    """Replace all logo placeholders and broken logo paths with tenant's logo URL.

    ``project_logo`` is the already-resolved path of the project's own logo. It has to be known
    here: this function rewrites the ``src`` of every ``<img>`` whose tag mentions "logo", and by
    the time it runs ``##PROJECT_LOGO##`` has already been replaced with a real path. A project
    logo stored at a path containing the word "logo" was therefore replaced by the company logo.
    """
    if not html:
        return html
    project_logo = str(project_logo or '').strip()
    logo_url = '/assets/logo.png'
    if tenant_id:
        branding = _branding_cache if _branding_cache is not None else (db.get_branding(tenant_id) or {})
        if branding.get('logo_path'):
            logo_url = branding['logo_path']
            if not logo_url.startswith('http') and '?t=' not in logo_url:
                logo_url = f"{logo_url}?t=1"
        else:
            logo_url = f"/tenant-assets/{tenant_id}/logo?t=1"
    else:
        logo_url = '/assets/logo.png'

    if not logo_url.startswith('/') and not logo_url.startswith('http'):
        logo_url = f"/{logo_url}"

    html = html.replace('##LOGO##', logo_url)
    html = re.sub(
        r'src=["\'](?:/?assets/logo\.png|logo\.png|/logo\.png|undefined|null|none)["\']',
        f'src="{logo_url}"',
        html,
        flags=re.IGNORECASE
    )

    def _fix_logo_img(match):
        img_tag = match.group(0)
        if 'project_logo' in img_tag.lower() or '##project_logo##' in img_tag.lower() or 'project-logo' in img_tag.lower():
            return img_tag
        if project_logo and project_logo in img_tag:
            return img_tag
        if '/uploads/creative/' in img_tag.lower():
            return img_tag
        if 'logo' in img_tag.lower() or '##LOGO##' in img_tag or 'tenant-assets' in img_tag:
            if 'src=' in img_tag.lower():
                img_tag = re.sub(r'src=["\'][^"\']*["\']', f'src="{logo_url}"', img_tag, flags=re.IGNORECASE)
            else:
                img_tag = img_tag.replace('<img', f'<img src="{logo_url}"')

            # Only add the logo sizing style once, and never over an explicit height: the cover,
            # closing and section dividers set a much larger logo on purpose.
            _LOGO_STYLE = 'max-height:50px;width:auto;object-fit:contain;display:inline-block;'
            has_explicit_height = re.search(r'(?:max-)?height\s*:', img_tag, flags=re.IGNORECASE)
            if _LOGO_STYLE not in img_tag and not has_explicit_height:
                if 'style=' in img_tag.lower():
                    img_tag = re.sub(
                        r'style=["\']([^"\']*)["\']',
                        lambda m: f'style="{m.group(1).rstrip(";")};{_LOGO_STYLE}"',
                        img_tag,
                        flags=re.IGNORECASE
                    )
                else:
                    img_tag = img_tag.replace('<img', f'<img style="{_LOGO_STYLE}"')
        return img_tag

    html = re.sub(r'<img\s[^>]*>', _fix_logo_img, html, flags=re.IGNORECASE)
    return html


def _remove_unapproved_contact_elements(html, project_data):
    source = project_data if isinstance(project_data, dict) else {}
    allowed = [str(source.get(key) or '').strip() for key in (
        'contact_name', 'contact_position', 'contact_phone', 'contact_email',
        'contact_website', 'contact_address', 'contact_social_media') if str(source.get(key) or '').strip()]
    contact_pattern = re.compile(r'(?:هاتف|جوال|بريد|إيميل|email|موقع إلكتروني|عنوان|سوشل|تواصل)', re.IGNORECASE)

    def remove_if_unapproved(match):
        text = html_lib.unescape(re.sub(r'<[^>]+>', ' ', match.group(0)))
        if not contact_pattern.search(text):
            return match.group(0)
        approved = any(re.search(rf'(?<![\w@.]){re.escape(value)}(?![\w@.])', text)
                       for value in allowed)
        return match.group(0) if approved else ''

    return re.sub(r'<(?:p|li|span|small|div)\b[^>]*>[^<>]*</(?:p|li|span|small|div)\s*>',
                  remove_if_unapproved, html, flags=re.IGNORECASE)


def _strip_presentation_icons(html):
    """Remove all icon markup and emoji, keeping company logo images.

    Emojis used to be converted into inline SVG icons first, which the SVG removal below then
    deleted anyway. The product rule is that no icon is ever produced, so they are simply stripped.
    """
    if not html:
        return html
    html = re.sub(r'<svg\b[^>]*>[\s\S]*?</svg\s*>', '', html, flags=re.IGNORECASE)
    html = re.sub(
        r'<(?:i|span|div)\b[^>]*(?:class|id)=["\'][^"\']*(?:icon|emoji|lucide|fa-|material-icons)[^"\']*["\'][^>]*>[\s\S]*?</(?:i|span|div)\s*>',
        '', html, flags=re.IGNORECASE
    )
    return _ICON_RE.sub('', html)


def _slide_counter_text(slide_num, total_slides=None):
    try:
        number = int(slide_num)
    except (TypeError, ValueError):
        return ''
    try:
        total = int(total_slides)
    except (TypeError, ValueError):
        total = number
    return f'{number:02d} — {max(number, total):02d}'


def _with_data_attribute(open_tag, name):
    if re.search(rf'\b{re.escape(name)}\s*=', open_tag, flags=re.IGNORECASE):
        return open_tag
    return open_tag[:-1] + f' {name}="1">'


def _rewrite_slide_counter(html, slide_type, slide_num, total_slides=None):
    if not html:
        return html
    counter = _slide_counter_text(slide_num, total_slides)
    if not counter:
        return html
    marker = re.compile(
        r'(<(?P<tag>span|div)\b[^>]*\bdata-slide-counter=["\'][^"\']*["\'][^>]*>)'
        r'[\s\S]*?(</(?P=tag)\s*>)', re.IGNORECASE,
    )
    html, replaced = marker.subn(lambda match: match.group(1) + counter + match.group(3), html)
    if replaced:
        return html
    if slide_type == 'section_divider':
        legacy = re.compile(
            r'(<div\b(?=[^>]*bottom:\s*34px)(?=[^>]*left:\s*48px)[^>]*)>'
            r'\s*\d{1,3}\s*[—–-]\s*\d{1,3}\s*</div\s*>', re.IGNORECASE,
        )
        return legacy.sub(lambda match: _with_data_attribute(match.group(1) + '>', 'data-slide-counter')
                          + counter + '</div>', html, count=1)

    footer = re.compile(
        r'(?P<open><div\b[^>]*height:\s*36px[^>]*>)(?P<body>[\s\S]*?)</div\s*>', re.IGNORECASE,
    )

    def replace_footer(match):
        spans = list(re.finditer(
            r'(?P<open><span\b[^>]*>)(?P<value>\s*\d{1,3}(?:\s*[—–/-]\s*\d{1,3})?\s*)</span\s*>',
            match.group('body'), flags=re.IGNORECASE,
        ))
        if not spans:
            return match.group(0)
        target = spans[-1]
        span_open = _with_data_attribute(target.group('open'), 'data-slide-counter')
        body = (match.group('body')[:target.start()] + span_open + counter + '</span>'
                + match.group('body')[target.end():])
        return _with_data_attribute(match.group('open'), 'data-slide-footer') + body + '</div>'

    return footer.sub(replace_footer, html, count=1)


def _remove_managed_slide_footer(html):
    return re.sub(
        r'<div\b[^>]*\bdata-slide-footer=["\'][^"\']*["\'][^>]*>[\s\S]*?</div\s*>',
        '', html or '', count=1, flags=re.IGNORECASE,
    )


def postprocess_slide(html, slide_type, slide_num=None, slide_title=None, total_slides=None,
                       tenant_id=None, branding=None, project_data=None):
    """Post-process a slide while keeping cover and closing free of header/footer.

    slide_type is the semantic type (cover, index, content, closing, ...).
    slide_num / total_slides are used for page numbers and cover/closing detection.
    """
    # No icons are ever produced: strip any SVG, icon markup and emoji the model emitted.
    html = _strip_presentation_icons(html)

    # Enforce image/placeholder rules.
    html = _block_external_images(html)
    html = _ensure_map_placeholder(html, slide_type)

    # Cover and closing must never receive the universal header/footer.
    normalized_title = str(slide_title or '').strip().lower()
    is_cover = slide_type == 'cover' or int(slide_num or 0) == 1 or bool(
        re.search(r'غلاف|cover|front', normalized_title)
    )
    is_closing = slide_type == 'closing' or bool(
        re.search(r'ختام|closing|شكراً|thanks', normalized_title)
    ) or (total_slides is not None and int(slide_num or 0) == int(total_slides))
    is_cover_or_closing = is_cover or is_closing
    if is_cover_or_closing or slide_type == 'moodboard':
        html = _remove_managed_slide_footer(html)
    else:
        html = _rewrite_slide_counter(html, slide_type, slide_num, total_slides)
    if is_cover_or_closing:
        html = _normalize_brand_overlay(html, branding)
    if is_cover:
        html = _normalize_cover_overlay_element(html, branding)
    if is_closing:
        html = re.sub(
            r'<(p|h[1-6]|span)\b[^>]*>[^<]*(?:فرصة\s+(?:واعدة|مشروطة)|واعدة\s+بشروط|بشروط)[^<]*</\1\s*>',
            '', html, flags=re.IGNORECASE,
        )
        html = _remove_unapproved_contact_elements(html, project_data)

    # Strip repetitive badges like "* مشروع متعدد الاستخدامات *" or floating project type chips from content slides
    if not is_cover and slide_type not in ('cover', 'overview'):
        html = re.sub(
            r'<(?:div|span|p|small)\b[^>]*>\s*(?:[*•-]?\s*(?:مشروع\s+)?متعدد\s+الاستخدامات\s*[*•-]?)\s*</(?:div|span|p|small)>',
            '', html, flags=re.IGNORECASE
        )
        html = re.sub(
            r'<(?:div|span|p|small|button|a)\b[^>]*class=["\']?[^"\'>]*(?:badge|tag|chip|pill|meta-pill|type-tag)[^"\'>]*[^>]*>[\s\S]*?(?:مشروع\s+متعدد\s+الاستخدامات|متعدد\s+الاستخدامات)[\s\S]*?</(?:div|span|p|small|button|a)>',
            '', html, flags=re.IGNORECASE
        )

    # Ensure map containers are centered without awkward crop shifts
    if 'MAP_' in html or (isinstance(slide_type, str) and slide_type.startswith('map_')):
        html = _map_media_contain(html)

    if '<table' in html.lower():
        html = _normalize_table_readability(html)

    # Clean out empty/broken img tags across all slides
    html = re.sub(
        r'<img\b[^>]*(?:src=["\']\s*["\']|src=["\']#(?:["\']|$)|\bsrc=["\'](?:undefined|null|none)["\'])[^>]*>',
        '',
        html,
        flags=re.IGNORECASE
    )

    def _strip_srcless_img(match):
        tag = match.group(0)
        if 'src=' not in tag.lower():
            return ''
        return tag
    html = re.sub(r'<img\s[^>]*>', _strip_srcless_img, html, flags=re.IGNORECASE)

    # Content/map/site slides get a header/footer; cover, dividers, moodboard and closing never do:
    # a divider carries its own logo, section name, slide number and project name.
    if slide_type not in ('cover', 'closing', 'moodboard', 'section_divider') and not is_cover_or_closing:
        has_header = bool(re.search(r'height:\s*56px', html))
        has_footer = bool(re.search(r'height:\s*36px', html))

        title = slide_title or f'شريحة {slide_num}' or 'العنوان'
        primary = '#7A0C0C'
        accent = '#C4A35A'
        company_name = 'منافع الاقتصادية للعقار'

        if branding is None and tenant_id:
            branding = db.get_branding(tenant_id) or {}
        if branding:
            primary = branding.get('primary_color') or primary
            accent = branding.get('accent_color') or accent
            company_name = branding.get('company_name') or company_name
            if not company_name:
                tenant = db.get_tenant(tenant_id) if tenant_id else None
                company_name = tenant.get('company_name') if tenant else 'منافع الاقتصادية للعقار'

        primary = normalize_hex_color(primary, '#7a0c0c')
        accent = normalize_hex_color(accent, '#c4a35a')
        header_title = readable_text_color(primary, '#ffffff', ('#0f172a',))
        footer_background = dark_surface_color(primary, branding.get('secondary_color') if branding else None)
        footer_text = readable_text_color('#ffffff', footer_background, ('#0f172a',))
        footer_accent = readable_text_color(accent, footer_background, (footer_text,))

        if not has_header:
            # The project logo belongs next to the company logo. This fallback used to carry the
            # company logo alone, so a slide the model built without a header lost it entirely.
            project_logo = str((project_data or {}).get('project_logo') or '').strip()
            project_logo_html = (
                f'<div style="width:1px;height:26px;background:#e2e8f0;margin:0 10px;"></div>'
                f'<img src="##PROJECT_LOGO##" alt="" style="height:36px;width:auto;object-fit:contain;" />'
            ) if project_logo else ''
            header_html = (
                f'<div style="position:absolute;top:0;right:0;left:0;height:56px;background:#fff;border-bottom:2px solid {primary};display:flex;align-items:center;padding:0 20px;z-index:10;">'
                '<img src="##LOGO##" style="height:40px;margin-right:12px;" />'
                + project_logo_html +
                f'<div style="width:3px;height:28px;background:{accent};margin:0 12px;"></div>'
                f'<span style="font-size:16px;font-weight:600;color:{header_title};">{title}</span>'
                '</div>'
            )
            html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1\n' + header_html, html, count=1)

        if not has_footer:
            footer_number = _slide_counter_text(slide_num, total_slides)
            footer_html = (
                f'<div data-slide-footer="1" style="position:absolute;bottom:0;right:0;left:0;height:36px;background:{footer_background};display:flex;align-items:center;padding:0 16px;z-index:10;">'
                f'<span style="font-size:13px;color:{footer_text};">{title}</span>'
                f'<span style="font-size:13px;color:{footer_text};opacity:0.7;margin-right:auto;margin-left:8px;">{company_name}</span>'
                f'<span data-slide-counter="1" style="color:{footer_accent};font-size:12px;font-weight:700;min-width:52px;text-align:left;">{footer_number}</span>'
                '</div>'
            )
            html = re.sub(r'(</div>\s*)$', '\n' + footer_html + r'\1', html, count=1)

    return html


def finalize_slide_html(html, slide_type, project_data, branding, creative_images=None,
                        map_placeholders=None, tenant_id=None, slide_num=None, slide_title=None,
                        total_slides=None, content_source=None):
    """Unified post-processing pipeline for every generated slide."""
    html = _canonicalize_slide_root_class(html)
    if content_source in ('site_analysis', 'executive_content.summary'):
        html = _ensure_map_summary_structure(html)
    html = postprocess_slide(
        html, slide_type, slide_num=slide_num, slide_title=slide_title,
        total_slides=total_slides, tenant_id=tenant_id, branding=branding,
        project_data=project_data
    )
    if (isinstance(slide_type, str) and (slide_type.startswith('map_') or slide_type == 'site_specs')
            or content_source in ('site_analysis', 'executive_content.summary', 'location_detail')):
        html = _inject_location_data_timestamp(html, project_data)
    if map_placeholders:
        html = _replace_map_placeholders(html, map_placeholders)
    if (isinstance(slide_type, str) and slide_type.startswith('map_')) or content_source in ('site_analysis', 'executive_content.summary'):
        html = _map_media_contain(html)
    if content_source in ('site_analysis', 'executive_content.summary'):
        html = _normalize_map_summary_layout(html, str((project_data or {}).get('_map_marker_side') or 'right'))
    html = _apply_logo_contrast_styles(html, branding, project_data, slide_type)
    html = _replace_creative_image_placeholders(html, creative_images, slide_type, content_source)
    html = _replace_data_placeholders(html, project_data, branding)
    html = resolve_logo_in_html(
        html, tenant_id, _branding_cache=branding,
        project_logo=(project_data or {}).get('project_logo')
    )
    html = _format_presentation_numeric_text(html)
    return _drop_unresolved_image_placeholders(html)


def renumber_presentation_slides(slides, branding=None, project_data=None, tenant_id=None):
    source = slides if isinstance(slides, list) else []
    total = len(source)
    if not total:
        return []
    branding = dict(branding or (db.get_branding(tenant_id) if tenant_id else {}) or {})
    project_data = dict(project_data or {})
    normalized = []
    current_section = ''
    for index, raw in enumerate(source):
        item = dict(raw) if isinstance(raw, dict) else {'html': str(raw or '')}
        slide_type = str(item.get('type') or '').strip().lower()
        title = str(item.get('title') or '').strip()
        html = str(item.get('html') or '')
        if not slide_type:
            if index == 0:
                slide_type = 'cover'
            elif re.search(r'محتويات\s+العرض|فهرس|index', title + ' ' + html, flags=re.IGNORECASE):
                slide_type = 'index'
            elif index == total - 1:
                slide_type = 'closing'
            else:
                slide_type = 'content'
            item['type'] = slide_type
        if slide_type == 'cover':
            item['section_key'] = 'cover'
        elif slide_type == 'index':
            item['section_key'] = 'index'
        else:
            section_key = _slide_section_key(item, current_section)
            item['section_key'] = section_key
            if slide_type == 'section_divider' and section_key in PRESENTATION_SECTION_ORDER:
                current_section = section_key
        normalized.append(item)

    refresh_index_entries({'slides': normalized})
    for index, item in enumerate(normalized, 1):
        slide_type = str(item.get('type') or 'content')
        if slide_type == 'index':
            index_html = build_index_slide(item, index, total, branding, project_data)
            item['html'] = finalize_slide_html(
                index_html, slide_type, project_data, branding, tenant_id=tenant_id,
                slide_num=index, slide_title=item.get('title') or 'محتويات العرض',
                total_slides=total, content_source=item.get('content_source'),
            )
        elif slide_type in ('cover', 'closing', 'moodboard'):
            item['html'] = _remove_managed_slide_footer(item.get('html') or '')
        else:
            item['html'] = _rewrite_slide_counter(
                item.get('html') or '', slide_type, index, total)
    return normalized


def generate_all_slides(slide_plan, project_data, branding, images_info, call_glm_fn, map_placeholders=None,
                        creative_images=None):
    """
    Generate all slides in parallel.
    Returns list of HTML strings.
    """
    slides = slide_plan.get('slides', [])
    total = len(slides)

    # Build system prompt with tenant's design rules
    design_rules = build_design_rules(branding)
    project_json = build_project_facts(project_data, branding.get('tenant_id'))

    landmarks_matrix = project_data.get('landmarks_matrix')
    landmarks_note = ''
    if landmarks_matrix:
        landmarks_note = (
            "إرشادات هامة لعرض المعالم:\n"
            "يجب عرض المسافة والوقت معاً لكل معلم بدون استثناء بالصيغة التاعية: (اسم المعلم - المسافة بالكم - الوقت بالدقائق)، مثل: 'ميدان السارية (1.5 كم - 5 دقائق)'.\n"
            "استخدم البيانات الموثقة التالية كما هي وممنوع تعديل الأرقام:\n" +
            json.dumps(landmarks_matrix, ensure_ascii=False, indent=2)
        )
    timeline_note = _timeline_data_note(project_data)
    financial_note = _financial_data_note(project_data)

    system_prompt = f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}

## بيانات المسافات والأوقات (ممنوع تعديل الأرقام)
{landmarks_note}
{timeline_note}
{financial_note}

## قواعد عامة
- كل شريحة 1280x720px (أو حسب نسبة العرض المحددة)
- CSS inline فقط
- ممنوع box-shadow/filter/backdrop-filter
- استخدم ##LOGO## للشعار، ##IMAGE_COVER## لصورة الغلاف، ##MOODBOARD_IMAGE_N## لصور المود بورد
- للخرائط: ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##
- ممنوع base64 أو روابط صور خارجية
- """ + NO_STREET_VIEW_RULE + """
"""

    results = [None] * total

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_idx = {}
        for i, slide in enumerate(slides):
            future = executor.submit(
                generate_single_slide,
                system_prompt, slide, i + 1, total, branding, call_glm_fn,
                project_data=project_data
            )
            future_to_idx[future] = i

        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            slide = slides[idx]
            html = future.result()
            if not html:
                # Fallback HTML so the rest of the pipeline keeps working
                title = slide.get('title', f'شريحة {idx + 1}')
                html = f'<div class="slide" style="width:1280px;height:720px;direction:rtl;font-family:sans-serif;display:flex;align-items:center;justify-content:center;text-align:center;background:#fff;"><h1>{title}</h1></div>'
                print(f"[SLIDE-{idx + 1}] Using fallback HTML")
            html = finalize_slide_html(
                html,
                slide.get('type', 'content'),
                project_data,
                branding,
                creative_images=creative_images,
                map_placeholders=map_placeholders,
                tenant_id=branding.get('tenant_id'),
                slide_num=idx + 1,
                slide_title=slide.get('title', f'شريحة {idx + 1}'),
                total_slides=total,
                content_source=slide.get('content_source'),
            )
            results[idx] = html

    return results
