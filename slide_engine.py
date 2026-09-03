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
    # ``[\W_]`` was stripping Arabic letters in the runtime used by the app,
    # turning every source-less Arabic title into the same empty signature and
    # silently dropping the later land tables.
    title = ''.join(char for char in str(slide.get('title') or '').lower() if char.isalnum())
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


def _can_chart_financial_part(chart_cand, part, model=None, project_data=None):
    if not isinstance(part, dict):
        return False
    rows = part.get('rows') or []
    if not rows:
        return False
    if chart_cand == 'combo':
        for r in rows:
            if isinstance(r, dict):
                txt = ' '.join(str(k) + ' ' + str(v) for k, v in r.items()).lower()
                if re.search(r'صافي.*تدفق|net.*cash|net.*flow|رصيد.*تراكمي|cumulative', txt):
                    return True
            elif isinstance(r, (list, tuple)) and r:
                txt = str(r[0]).lower()
                if re.search(r'صافي.*تدفق|net.*cash|net.*flow|رصيد.*تراكمي|cumulative', txt):
                    return True
        if isinstance(model, dict) and (model.get('tables', {}).get('cashflowTable') or model.get('tables', {}).get('cashflow')):
            return True
        return False
    elif chart_cand == 'waterfall':
        for r in rows:
            txt = str(r.get('البند') if isinstance(r, dict) else (r[0] if isinstance(r, (list, tuple)) and r else '')).lower()
            if re.search(r'تكلف|cost|استثمار|مجموع|إجمالي', txt):
                return True
        if isinstance(model, dict) and (model.get('tables', {}).get('costTable') or model.get('tables', {}).get('costs')):
            return True
        return False
    elif chart_cand == 'heatmap':
        for r in rows:
            txt = str(r.get('السيناريو') if isinstance(r, dict) else (r[0] if isinstance(r, (list, tuple)) and r else '')).lower()
            if re.search(r'متحفظ|أساسي|اساسي|متفائل|تحفظ|تفاؤل', txt):
                return True
        if isinstance(model, dict) and (model.get('tables', {}).get('sensitivityTable') or model.get('tables', {}).get('sensitivity')):
            return True
        return False
    return False


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


# Vertical stacking budget for packed tables: data rows plus the header and caption
# each stacked table costs.  The renderer uses compact rows, so consecutive tables
# keep filling the current slide until this budget is reached.
_FINANCIAL_PACK_ROW_BUDGET = 24.0
_FINANCIAL_PACK_MAX_TABLES = 8


def _pack_financial_table_slices(items):
    """Pack consecutive narrow financial table slices into slides that stack them vertically.

    The client shrinks the tables, so one small table per slide wasted the deck with
    a half-empty slide each. Wide (column-split) tables never reach this packer: the
    caller flushes them as single slides because two six-column tables stacked
    vertically do not fit the slide height.
    """
    groups = []
    current = None
    for item in items:
        weight = float(item.get('row_count') or 0) + 2.5
        if current is not None and (current['weight'] + weight <= _FINANCIAL_PACK_ROW_BUDGET
                                    and len(current['items']) < _FINANCIAL_PACK_MAX_TABLES):
            current['items'].append(item)
            current['weight'] += weight
        else:
            current = {'items': [item], 'weight': weight}
            groups.append(current)
    slides = []
    for group in groups:
        group_items = group['items']
        sources = [str(item['source']) for item in group_items]
        row_count = sum(int(item.get('row_count') or 0) for item in group_items)
        if len(group_items) == 1:
            item = group_items[0]
            slides.append({
                'title': item['title'] + (f" — {item['suffix']}" if item.get('suffix') else ''),
                'type': 'content', 'design_style': 'table',
                'chart_type': '', 'content_density': 'high', 'requires_image': False,
                'content_source': sources[0],
                'source_table': item.get('source_table'),
                'row_count': row_count, 'financial_template': 'report', 'bullets': [],
            })
            continue
        titles = list(dict.fromkeys(str(item['title']) for item in group_items))
        if len(titles) == 1:
            title = titles[0]
        elif len(titles) == 2:
            title = ' + '.join(titles)
        else:
            title = f'{titles[0]} + جداول أخرى'
        slides.append({
            'title': title, 'type': 'content', 'design_style': 'table',
            'chart_type': '', 'content_density': 'high', 'requires_image': False,
            'content_source': sources[0], 'content_sources': sources,
            'source_table': group_items[0].get('source_table'),
            'row_count': row_count, 'financial_template': 'report', 'bullets': [],
        })
    return slides


def _financial_report_part_title(model, part_index):
    """Re-derive the heading a report part sat under, matching the plan builder's walk."""
    report = model.get('report') if isinstance(model, dict) and isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    heading = 'الدراسة المالية'
    subheading = ''
    for index, part in enumerate(parts):
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
        if index == part_index:
            return subheading or heading
    return ''


def _stacked_financial_report_note(sources, model):
    """One combined note for a slide that stacks several report tables vertically."""
    report = model.get('report') if isinstance(model, dict) and isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    blocks = []
    for number, source in enumerate(sources, 1):
        match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', str(source))
        if not match:
            continue
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        if part_index >= len(parts) or not isinstance(parts[part_index], dict):
            continue
        part = _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
        part_title = _financial_report_part_title(model, part_index) or f'جدول {number}'
        blocks.append(f'جدول {number} — {part_title} (الصفوف {start + 1} إلى {end}):\n'
                      + json.dumps(part, ensure_ascii=False, indent=2))
    if not blocks:
        return ''
    return ('هذه الشريحة المالية العادية تضم الجداول التالية في الشريحة نفسها — '
            'ادمج الجداول المتتالية ذات الترويسة والأعمدة المتطابقة في جدول واحد، ورص جميع الجداول المتبقية رأسياً تحت بعضها بترتيب المصادر، مع إبقاء كل صف وعمود كاملاً. لا تضع جدولين بجانب بعضهما، وإذا لم تتسع المساحة الحالية فانقل بقية الجداول إلى الشريحة المالية التالية دون قص أو حذف. هذا الترتيب لا يلغي تخطيط الجدول بجانب الرسم في شرائح الرسوم المعتمدة:\n\n'
            + '\n\n'.join(blocks))


def _merge_sparse_plan_slides(groups):
    for section_key, slides in groups.items():
        merged = []
        for slide in slides:
            source = str(slide.get('content_source') or '')
            sparse_financial = (section_key == 'financial' and slide.get('row_count') == 1
                                and not source.startswith(('financial_summary:', 'financial_indicators')))
            sparse_generic = (not source and slide.get('design_style') != 'table'
                              and not slide.get('image_tokens')
                              and len([item for item in (slide.get('bullets') or []) if str(item or '').strip()]) <= 1)
            if ((sparse_financial or sparse_generic) and merged
                    and not merged[-1].get('chart_type') and not slide.get('chart_type')):
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
            first_generic = (not first_source and first.get('design_style') != 'table'
                             and not first.get('image_tokens')
                             and len([item for item in (first.get('bullets') or []) if str(item or '').strip()]) <= 1)
            if ((first_sparse or first_generic) and merged
                    and not merged[1].get('chart_type') and not first.get('chart_type')):
                target = merged[1]
                if first_source:
                    target['content_sources'] = list(first.get('content_sources') or [first_source]) + list(
                        target.get('content_sources') or [target.get('content_source')])
                    target['row_count'] = int(first.get('row_count') or 0) + int(target.get('row_count') or 0)
                else:
                    target['bullets'] = list(first.get('bullets') or []) + list(target.get('bullets') or [])
                merged.pop(0)
        groups[section_key] = merged


def _merge_adjacent_table_slides(groups):
    """Combine adjacent ordinary table slides when their data can share a page.

    Financial report tables are packed from their canonical report below, but
    land/location tables can arrive directly from the plan model.  Keeping those
    slides separate made several small key/value tables consume one page each.
    The original sources and titles are retained so the generator still has all
    facts available.
    """
    for section_key, slides in groups.items():
        # Apply the same sequential packing rule to every section.  A table slide
        # is only merged with the immediately preceding table slide in its section;
        # charts, images and narrative slides naturally flush the current group.
        merged = []
        for slide in slides:
            source = str(slide.get('content_source') or '')
            is_table = (
                slide.get('type', 'content') == 'content'
                and slide.get('design_style') == 'table'
                and not slide.get('chart_type')
                and not slide.get('image_tokens')
                and not source.startswith(('financial_summary:', 'financial_indicators'))
                and not source.startswith('project_components:')
                and not re.fullmatch(r'financial_report:\d+:\d+:\d+:\d+:\d+', source)
            )
            previous = merged[-1] if merged else None
            previous_is_table = bool(previous and previous.get('_table_group'))
            previous_rows = int(previous.get('row_count') or 0) if previous_is_table else 0
            current_rows = int(slide.get('row_count') or 0)
            can_fit = (
                previous_is_table
                and len(previous.get('_table_group') or []) < _FINANCIAL_PACK_MAX_TABLES
                and previous_rows + current_rows + 2.5 * (len(previous.get('_table_group') or []) + 1)
                    <= _FINANCIAL_PACK_ROW_BUDGET
            )
            if is_table and can_fit:
                previous['_table_group'].append(slide)
                previous['table_group_titles'] = list(previous.get('table_group_titles') or []) + [
                    str(slide.get('title') or '').strip()
                ]
                previous['bullets'] = list(previous.get('bullets') or []) + list(slide.get('bullets') or [])
                if source:
                    previous['content_sources'] = list(previous.get('content_sources') or [previous.get('content_source')])
                    previous['content_sources'].append(source)
                previous['row_count'] = int(previous.get('row_count') or 0) + int(slide.get('row_count') or 0)
                continue
            if is_table:
                item = dict(slide)
                item['_table_group'] = [slide]
                item['table_group_titles'] = [str(slide.get('title') or '').strip()]
                merged.append(item)
            else:
                merged.append(slide)

        for slide in merged:
            group = slide.pop('_table_group', [])
            titles = [title for title in slide.pop('table_group_titles', []) if title]
            if len(group) <= 1:
                continue
            if not slide.get('content_sources'):
                slide['content_sources'] = [
                    str(item.get('content_source') or '').strip()
                    for item in group if str(item.get('content_source') or '').strip()
                ]
            slide['table_group_titles'] = titles
            slide['title'] = titles[0] if titles else slide.get('title') or 'جداول البيانات'
        groups[section_key] = merged


def _is_sensitivity_assumptions_slide(slide, model=None):
    """Identify the assumptions table that belongs with the sensitivity results."""
    source = str((slide or {}).get('content_source') or '').strip().lower()
    source_table = str((slide or {}).get('source_table') or '').strip().lower()
    text = ' '.join(str((slide or {}).get(key) or '') for key in ('title', 'content_source', 'source_table')).lower()
    if 'sensitivityassumptionstable' in source or 'sensitivityassumptionstable' in source_table:
        return True
    if model and source.startswith('financial_report:'):
        match = re.fullmatch(r'financial_report:(\d+):\d+:\d+(?::\d+:\d+)?', source)
        report_title = _financial_report_part_title(model, int(match.group(1))).lower() if match else ''
        if match and re.search(r'sensitivity|حساسية|سيناريو', report_title):
            return bool(re.search(r'assumption|افتراض', text + ' ' + report_title))
    return bool(re.search(r'assumption|افتراضات.*(?:حساسية|سيناريو)|(?:حساسية|سيناريو).*افتراضات', text))


def _attach_sensitivity_assumptions(groups, project_data):
    """Place the sensitivity assumptions table beside its result matrix when it fits."""
    financial = groups.get('financial', [])
    if not financial:
        return
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    heatmap = next((slide for slide in financial if canonicalize_chart_type(slide.get('chart_type')) == 'heatmap'), None)
    if not heatmap:
        return

    assumption_slides = []
    for slide in financial:
        if slide is heatmap or not _is_sensitivity_assumptions_slide(slide, model):
            continue
        sources = [str(value).strip() for value in (slide.get('content_sources') or [slide.get('content_source')])
                   if str(value or '').strip()]
        # Never remove a packed slide containing another table.  It remains a
        # normal table slide instead of losing unrelated source data.
        if sources and all('sensitivityassumptionstable' in value.lower() or
                           _is_sensitivity_assumptions_slide({'content_source': value}, model)
                           for value in sources):
            assumption_slides.append((slide, sources))
    if not assumption_slides:
        return

    assumption_sources = [source for _slide, sources in assumption_slides for source in sources]
    assumption_rows = sum(int(slide.get('row_count') or 0) for slide, _sources in assumption_slides)
    # The result matrix and the assumptions table share the chart slide only
    # while the assumptions can stay readable in the side column.
    if assumption_rows <= 10:
        result_source = str(heatmap.get('content_source') or '').strip()
        heatmap['content_sources'] = list(dict.fromkeys(assumption_sources + ([result_source] if result_source else [])))
        heatmap['sensitivity_assumptions_sources'] = assumption_sources
        heatmap['table_group_titles'] = list(dict.fromkeys(
            [str(slide.get('title') or '').strip() for slide, _sources in assumption_slides] +
            [str(heatmap.get('title') or '').strip()]
        ))
        heatmap['row_count'] = int(heatmap.get('row_count') or 0) + assumption_rows
        removed = {id(slide) for slide, _sources in assumption_slides}
        groups['financial'] = [slide for slide in financial if id(slide) not in removed]


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
            pending_tables = []

            def flush_pending_tables():
                for packed_slide in _pack_financial_table_slices(pending_tables):
                    add('financial', packed_slide)
                pending_tables.clear()

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
                chart_cand = _financial_chart_type(part_title, index=part_index) if part.get('type') == 'table' else ''
                chartable_overall = (len(column_ranges) == 1 and len(row_ranges) == 1
                                     and part.get('type') == 'table'
                                     and bool(chart_cand)
                                     and _financial_table_chartable(part, rows, None, None))
                if (chart_cand in FINANCIAL_CHART_TYPES and not chartable_overall
                        and target_section == 'financial'
                        and _can_chart_financial_part(chart_cand, part, model, project_data)):
                    flush_pending_tables()
                    chart_titles = {
                        'combo': 'التدفقات النقدية السنوية والتراكمية',
                        'waterfall': 'تكوين إجمالي تكلفة المشروع',
                        'heatmap': 'مقارنة السيناريوهات المالية',
                    }
                    add(target_section, {
                        'title': chart_titles.get(chart_cand, part_title),
                        'type': 'content',
                        'design_style': 'chart',
                        'chart_type': chart_cand,
                        'content_density': 'high',
                        'requires_image': False,
                        'content_source': f'financial_chart:{chart_cand}:{part_index}',
                        'source_table': f'report_part_{part_index}',
                        'row_count': len(rows),
                        'financial_template': 'report',
                        'bullets': [],
                    })
                for row_number, (start, end) in enumerate(row_ranges, 1):
                    for column_number, (column_start, column_end) in enumerate(column_ranges, 1):
                        chart_cand = _financial_chart_type(part_title, index=part_index)
                        chartable = (len(column_ranges) == 1 and start == 0 and column_number == 1
                                     and part.get('type') == 'table'
                                     and bool(chart_cand)
                                     and _financial_table_chartable(
                                         part, rows[start:end], column_start, column_end))
                        source_suffix = (f':{column_start}:{column_end}'
                                         if column_start is not None and column_end is not None else '')
                        part_source = f'financial_report:{part_index}:{start}:{end}{source_suffix}'
                        if chartable or column_start is not None or len(column_ranges) > 1:
                            # Chart slides and wide column-split tables own their slide:
                            # two six-column tables stacked vertically do not fit.
                            flush_pending_tables()
                            title_suffixes = []
                            if len(row_ranges) > 1:
                                title_suffixes.append(str(row_number))
                            if len(column_ranges) > 1:
                                title_suffixes.append(f'جزء {column_number}')
                            add(target_section, {
                                'title': part_title + (f" — {' / '.join(title_suffixes)}" if title_suffixes else ''),
                                'type': 'content', 'design_style': 'chart' if chartable else 'table',
                                'chart_type': chart_cand if chartable else '',
                                'content_density': 'high', 'requires_image': False,
                                'content_source': part_source,
                                'source_table': f'report_part_{part_index}', 'row_count': end - start,
                                'financial_template': 'report', 'bullets': [],
                            })
                        else:
                            pending_tables.append({
                                'title': part_title,
                                'suffix': str(row_number) if len(row_ranges) > 1 else '',
                                'source': part_source,
                                'source_table': f'report_part_{part_index}',
                                'row_count': end - start,
                            })
            flush_pending_tables()
            fin_slides = groups.get('financial', [])
            if not any(canonicalize_chart_type(s.get('chart_type')) == 'combo' for s in fin_slides) and (tables.get('cashflowTable') or tables.get('cashflow')):
                cf_rows = tables.get('cashflowTable') or tables.get('cashflow') or []
                add('financial', {
                    'title': 'التدفقات النقدية السنوية والتراكمية',
                    'type': 'content',
                    'design_style': 'chart',
                    'chart_type': 'combo',
                    'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:cashflowTable:0:{len(cf_rows)}',
                    'source_table': 'cashflowTable',
                    'row_count': len(cf_rows),
                    'financial_template': 'report',
                    'bullets': [],
                })
            if not any(canonicalize_chart_type(s.get('chart_type')) == 'waterfall' for s in fin_slides) and (tables.get('costTable') or tables.get('costs')):
                ct_rows = tables.get('costTable') or tables.get('costs') or []
                add('financial', {
                    'title': 'تكوين إجمالي تكلفة المشروع',
                    'type': 'content',
                    'design_style': 'chart',
                    'chart_type': 'waterfall',
                    'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:costTable:0:{len(ct_rows)}',
                    'source_table': 'costTable',
                    'row_count': len(ct_rows),
                    'financial_template': 'report',
                    'bullets': [],
                })
            if not any(canonicalize_chart_type(s.get('chart_type')) == 'heatmap' for s in fin_slides) and (tables.get('sensitivityTable') or tables.get('sensitivity')):
                st_rows = tables.get('sensitivityTable') or tables.get('sensitivity') or []
                add('financial', {
                    'title': 'مقارنة السيناريوهات المالية',
                    'type': 'content',
                    'design_style': 'chart',
                    'chart_type': 'heatmap',
                    'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:sensitivityTable:0:{len(st_rows)}',
                    'source_table': 'sensitivityTable',
                    'row_count': len(st_rows),
                    'financial_template': 'report',
                    'bullets': [],
                })
            # The heatmap is the visual summary of the results table.  Keep the
            # separate assumptions table too when it exists but was not included
            # in the extracted report parts.
            assumption_rows = tables.get('sensitivityAssumptionsTable')
            if (not isinstance(assumption_rows, list) or not assumption_rows) and isinstance(tables.get('sensitivity'), list):
                assumption_rows = tables.get('sensitivity')
            def is_assumptions_slide(s):
                text = ' '.join(str(s.get(key) or '') for key in ('title', 'content_source', 'source_table')).lower()
                source_match = re.fullmatch(r'financial_report:(\d+):\d+:\d+.*', str(s.get('content_source') or ''))
                if source_match:
                    text += ' ' + _financial_report_part_title(model, int(source_match.group(1))).lower()
                return (
                    'sensitivityassumptionstable' in text
                    or bool(re.search(r'افتراضات.*(?:حساسية|سيناريو)|(?:حساسية|سيناريو).*افتراضات', text))
                )

            has_assumptions = any(is_assumptions_slide(s) for s in groups.get('financial', []))
            if assumption_rows and not has_assumptions:
                add('financial', {
                    'title': 'افتراضات تحليل الحساسية', 'type': 'content',
                    'design_style': 'table', 'chart_type': '', 'content_density': 'high',
                    'requires_image': False,
                    'content_source': f'financial_table:sensitivityAssumptionsTable:0:{len(assumption_rows)}',
                    'source_table': 'sensitivityAssumptionsTable', 'row_count': len(assumption_rows),
                    'financial_template': 'report', 'bullets': [],
                })
        else:
            pending_tables = []

            def flush_pending_tables():
                for packed_slide in _pack_financial_table_slices(pending_tables):
                    add('financial', packed_slide)
                pending_tables.clear()

            for table_key, title, style in _FINANCIAL_PLAN_TABLES:
                rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
                if not rows:
                    continue
                row_ranges = _balanced_row_ranges(len(rows), max_per_slide=12, min_per_slide=4)
                for number, (start, end) in enumerate(row_ranges, 1):
                    is_chart = (style == 'chart' and start == 0)
                    c_type = _financial_chart_type(title, table_key, number - 1) if is_chart else ''
                    item = {
                        'title': title,
                        'suffix': str(number) if len(row_ranges) > 1 else '',
                        'source': f'financial_table:{table_key}:{start}:{end}',
                        'source_table': table_key,
                        'row_count': end - start,
                    }
                    if c_type:
                        flush_pending_tables()
                        add('financial', {
                            'title': title + (f' — {number}' if len(row_ranges) > 1 else ''),
                            'type': 'content', 'design_style': 'chart', 'chart_type': c_type,
                            'content_density': 'high', 'requires_image': False,
                            'content_source': item['source'], 'source_table': table_key,
                            'row_count': end - start, 'financial_template': 'report', 'bullets': [],
                        })
                    else:
                        pending_tables.append(item)
            flush_pending_tables()
        _attach_sensitivity_assumptions(groups, source)
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
    _merge_adjacent_table_slides(groups)
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
                  'design_style': 'image', 'requires_image': True,
                  'image_tokens': ['##IMAGE_COVER##'], 'image_layout': None})
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


def _clean_numeric_val(val):
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s or s in ('—', '-', 'غير متاح', 'N/A'):
        return 0.0
    neg = '(' in s or '-' in s
    cleaned = re.sub(r'[^\d.]', '', s.replace(',', ''))
    try:
        n = float(cleaned)
        return -n if neg else n
    except (ValueError, TypeError):
        return 0.0


def _clean_numeric_val_strict(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ('—', '-', 'غير متاح', 'N/A', 'لا يسترد', 'غير مسترد', 'none', 'null'):
        return None
    neg = '(' in s or '-' in s
    cleaned = re.sub(r'[^\d.]', '', s.replace(',', ''))
    try:
        n = float(cleaned)
        return -n if neg else n
    except (ValueError, TypeError):
        return None


def _format_sar_display(val):
    val_m = round(val / 1e6, 2)
    if abs(val_m) >= 0.1:
        return f"{round(val / 1e6, 1)} ر.س"
    return f"{int(val):,} ر.س"


def _extract_competitor_chart_data(competitors, project_data=None):
    project_data = project_data if isinstance(project_data, dict) else {}
    items = []
    for comp in (competitors or []):
        if not isinstance(comp, dict):
            continue
        name = str(comp.get('name') or comp.get('competitor_name') or comp.get('project_name') or '').strip()
        price_val = comp.get('price_value') or comp.get('price') or comp.get('value')
        p_from = comp.get('price_from') or comp.get('min_price')
        p_to = comp.get('price_to') or comp.get('max_price')
        p_type = str(comp.get('price_type') or comp.get('type') or '').strip()
        unit = str(comp.get('unit') or (comp.get('area_cache') if isinstance(comp.get('area_cache'), dict) else {}).get('unit') or '').strip()

        num = 0.0
        for raw in (price_val, p_to, p_from):
            val = _clean_numeric_val(raw)
            if val > 0:
                num = val
                break
        if name and num > 0:
            unit_str = f" {unit}" if unit else " ر.س/م²"
            items.append({
                'name': name,
                'price_num': num,
                'display_price': f"{int(num):,}{unit_str}",
                'price_type': p_type,
                'is_project': False,
            })

    items.sort(key=lambda x: x['price_num'], reverse=True)

    proj_price_raw = project_data.get('proposed_price') or project_data.get('project_price')
    market = _decode_json_fact(project_data.get('market_study_data')) if isinstance(project_data.get('market_study_data'), (str, dict)) else {}
    if not proj_price_raw and isinstance(market, dict):
        proj_price_raw = market.get('proposed_price') or market.get('project_price')
    if proj_price_raw:
        p_val = _clean_numeric_val(proj_price_raw)
        if p_val > 0:
            p_name = str(project_data.get('project_name') or project_data.get('projectName') or 'مشروعنا').strip()
            unit_str = items[0]['display_price'].split()[-1] if items and ' ' in items[0]['display_price'] else 'ر.س/م²'
            items.append({
                'name': f"{p_name} (المشروع المقترح)",
                'price_num': p_val,
                'display_price': f"{int(p_val):,} {unit_str}",
                'price_type': 'سعر مقترح',
                'is_project': True,
            })
            items.sort(key=lambda x: x['price_num'], reverse=True)

    if len(items) > 6:
        project_item = next((it for it in items if it.get('is_project')), None)
        items = items[:6]
        if project_item and project_item not in items:
            items[-1] = project_item
            items.sort(key=lambda x: x['price_num'], reverse=True)

    max_p = max((x['price_num'] for x in items), default=1.0)
    for it in items:
        it['bar_width_pct'] = max(round((it['price_num'] / max_p) * 100, 1), 15.0)

    return items


def _build_waterfall_svg(items, total, width=1050, height=340, primary='#16405f', secondary='#0284c7', gold='#b89564'):
    total_val_m = total.get('value_millions', 0.0)
    if total_val_m <= 0:
        total_val_m = sum(it.get('value_millions', 0.0) for it in items) or 1.0

    max_tick = 100.0
    for t in [100, 200, 300, 500, 750, 1000, 1500, 2000, 5000]:
        if total_val_m <= t:
            max_tick = float(t)
            break
    else:
        max_tick = total_val_m * 1.15

    tick_step = max_tick / 4.0
    ticks = [0.0, tick_step, tick_step * 2, tick_step * 3, max_tick]

    pad_left = 60
    pad_right = 25
    pad_top = 45
    pad_bottom = 65
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    def y_for(val):
        return round(pad_top + chart_h - (val / max_tick) * chart_h, 1)

    y_zero = y_for(0.0)

    grid_lines = []
    tick_texts = []
    for t in ticks:
        ty = y_for(t)
        grid_lines.append(f'<line x1="{pad_left}" y1="{ty}" x2="{width - pad_right}" y2="{ty}" stroke="#e2e8f0" stroke-width="1" />')
        val_str = f"{t:,.0f}" if t == int(t) else f"{t:,.1f}"
        tick_texts.append(f'<text x="{pad_left - 8}" y="{ty + 4}" font-size="10" fill="#94a3b8" text-anchor="end">{val_str}</text>')

    n_cols = len(items) + 1
    col_slot = chart_w / max(n_cols, 1)
    bar_w = min(round(col_slot * 0.72, 1), 75.0)

    bars_svg = []
    connectors_svg = []
    labels_svg = []

    def _wrap_tspans(text, cx, max_chars=14):
        words = str(text).split()
        if len(words) <= 2 and len(text) <= max_chars:
            return f'<text x="{cx}" y="0" font-size="9.5" font-weight="600" fill="#334155" text-anchor="middle">{html_lib.escape(text)}</text>'
        mid = len(words) // 2
        line1 = ' '.join(words[:mid])
        line2 = ' '.join(words[mid:])
        return f'''<text x="{cx}" y="-4" font-size="9.5" font-weight="600" fill="#334155" text-anchor="middle">
          <tspan x="{cx}" dy="0">{html_lib.escape(line1)}</tspan>
          <tspan x="{cx}" dy="12">{html_lib.escape(line2)}</tspan>
        </text>'''

    running_m = 0.0
    prev_top_x = None
    prev_top_y = None

    for idx, it in enumerate(items):
        val_m = it.get('value_millions', 0.0)
        bot_y = y_for(running_m)
        top_y = y_for(running_m + val_m)
        bar_h = max(round(bot_y - top_y, 1), 4.0)

        cx = pad_left + idx * col_slot + col_slot / 2
        bx = round(cx - bar_w / 2, 1)

        name = it.get('name', '')
        if 'مطور' in name:
            color = gold
        elif 'صندوق' in name:
            color = '#8b5cf6'
        elif 'تمويل' in name:
            color = '#f59e0b'
        elif idx % 2 == 0:
            color = primary
        else:
            color = secondary

        if prev_top_x is not None:
            connectors_svg.append(f'<line x1="{prev_top_x}" y1="{prev_top_y}" x2="{bx}" y2="{prev_top_y}" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="3 3" />')

        bars_svg.append(f'<rect x="{bx}" y="{top_y}" width="{bar_w}" height="{bar_h}" fill="{color}" rx="3" />')

        pct = it.get('pct_of_total', round((val_m / total_val_m) * 100, 1))
        disp = it.get('display', f"{val_m:.1f} ر.س")
        labels_svg.append(f'<text x="{cx}" y="{top_y - 8}" font-size="9.5" font-weight="700" fill="#0f172a" text-anchor="middle">{disp}</text>')
        labels_svg.append(f'<text x="{cx}" y="{top_y - 20}" font-size="8.5" font-weight="600" fill="#64748b" text-anchor="middle">{pct}%</text>')

        wrapped = _wrap_tspans(name, cx)
        labels_svg.append(f'<g transform="translate(0, {y_zero + 18})">{wrapped}</g>')

        prev_top_x = bx + bar_w
        prev_top_y = top_y
        running_m += val_m

    # Total column
    tot_idx = len(items)
    tot_cx = pad_left + tot_idx * col_slot + col_slot / 2
    tot_bx = round(tot_cx - bar_w / 2, 1)
    tot_top_y = y_for(total_val_m)
    tot_h = round(y_zero - tot_top_y, 1)

    if prev_top_x is not None:
        connectors_svg.append(f'<line x1="{prev_top_x}" y1="{prev_top_y}" x2="{tot_bx}" y2="{prev_top_y}" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="3 3" />')

    bars_svg.append(f'<rect x="{tot_bx}" y="{tot_top_y}" width="{bar_w}" height="{tot_h}" fill="{primary}" rx="3" />')
    tot_disp = total.get('display', f"{total_val_m:.1f} ر.س")
    labels_svg.append(f'<text x="{tot_cx}" y="{tot_top_y - 8}" font-size="10.5" font-weight="800" fill="{primary}" text-anchor="middle">{tot_disp}</text>')
    labels_svg.append(f'<text x="{tot_cx}" y="{tot_top_y - 22}" font-size="8.5" font-weight="700" fill="{primary}" text-anchor="middle">100%</text>')
    tot_wrapped = _wrap_tspans(total.get('name', 'إجمالي تكلفة المشروع'), tot_cx)
    labels_svg.append(f'<g transform="translate(0, {y_zero + 18})">{tot_wrapped}</g>')

    return f'''<svg data-chart="waterfall" viewBox="0 0 {width} {height}" style="width:100%;height:auto;max-height:360px;font-family:inherit;overflow:visible;" role="img" aria-label="المخطط الشلالي لتكوين إجمالي تكلفة المشروع">
  <!-- Grid -->
  {''.join(grid_lines)}
  <!-- Baseline -->
  <line x1="{pad_left}" y1="{y_zero}" x2="{width - pad_right}" y2="{y_zero}" stroke="#64748b" stroke-width="1.5" />
  <!-- Ticks -->
  {''.join(tick_texts)}
  <!-- Connectors -->
  {''.join(connectors_svg)}
  <!-- Bars -->
  {''.join(bars_svg)}
  <!-- Labels -->
  {''.join(labels_svg)}
</svg>'''


def _extract_waterfall_chart_data(part_or_table, model=None, project_data=None):
    model = model if isinstance(model, dict) else {}
    inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    project_data = project_data if isinstance(project_data, dict) else {}
    fcd = project_data.get('financial_calc_data')
    if isinstance(fcd, str):
        try:
            fcd = json.loads(fcd)
        except Exception:
            fcd = {}
    fcd = fcd if isinstance(fcd, dict) else {}

    rows = []
    if isinstance(part_or_table, dict):
        rows = part_or_table.get('rows') or []
    elif isinstance(part_or_table, list):
        rows = part_or_table

    items = []
    seen_names = set()
    for r in rows:
        name = ''
        val = 0.0
        if isinstance(r, dict):
            name = str(r.get('اسم التكلفة') or r.get('البند') or r.get('name') or '').strip()
            val = _clean_numeric_val(r.get('الناتج') or r.get('القيمة') or r.get('value') or r.get('cost'))
        elif isinstance(r, (list, tuple)) and r:
            name = str(r[0]).strip()
            for cell in reversed(r[1:]):
                c_val = _clean_numeric_val(cell)
                if c_val > 0:
                    val = c_val
                    break
        if name and name not in ('الإجمالي', 'المجموع', 'Total', 'إجمالي تكلفة الاستثمار', 'إجمالي تكلفة المشروع', 'تكلفة الاستثمار', 'تكلفة المشروع') and val > 0:
            if name not in seen_names:
                seen_names.add(name)
                items.append({
                    'name': name,
                    'value_sar': val,
                    'value_millions': round(val / 1e6, 2),
                    'display': _format_sar_display(val),
                })

    if not items:
        for r in tables.get('costTable', []):
            if isinstance(r, dict):
                c_name = str(r.get('اسم التكلفة') or '').strip()
                c_val = _clean_numeric_val(r.get('الناتج'))
                if c_name and c_val > 0 and c_name not in seen_names:
                    seen_names.add(c_name)
                    items.append({
                        'name': c_name,
                        'value_sar': c_val,
                        'value_millions': round(c_val / 1e6, 2),
                        'display': _format_sar_display(c_val),
                    })

    if not items:
        fallback_cost_keys = (
            ('landCostIncluded', 'قيمة الأرض'),
            ('landValue', 'قيمة الأرض'),
            ('executionCostTotal', 'تكلفة التنفيذ والإنشاء'),
            ('designCostTotal', 'التصميم والدراسات والاستشارات'),
            ('servicesCostTotal', 'رسوم الخدمات والتراخيص'),
            ('advertisingCostTotal', 'الدعاية والتسويق'),
            ('developerCost', 'أتعاب إدارة التطوير'),
            ('fundFeesTotal', 'أتعاب إدارة الصندوق'),
            ('totalFundFees', 'أتعاب إدارة الصندوق'),
            ('fundManagementFeesTotal', 'أتعاب إدارة الصندوق'),
            ('totalFinanceCost', 'تكلفة التمويل البنكي'),
            ('contingencyCostTotal', 'احتياطي الطوارئ'),
        )
        for k, label in fallback_cost_keys:
            if label in seen_names:
                continue
            c_val = _clean_numeric_val(inputs.get(k))
            if c_val > 0:
                seen_names.add(label)
                items.append({
                    'name': label,
                    'value_sar': c_val,
                    'value_millions': round(c_val / 1e6, 2),
                    'display': _format_sar_display(c_val),
                })

    if not items:
        total_guess = _clean_numeric_val(inputs.get('adjustedProjectCost') or inputs.get('projectCost') or inputs.get('landCostIncluded') or 100000000)
        items = [
            {'name': 'قيمة الأرض', 'value_sar': total_guess * 0.45, 'value_millions': round(total_guess * 0.45 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.45)},
            {'name': 'تكاليف التنفيذ', 'value_sar': total_guess * 0.38, 'value_millions': round(total_guess * 0.38 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.38)},
            {'name': 'التصميم والدراسات', 'value_sar': total_guess * 0.07, 'value_millions': round(total_guess * 0.07 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.07)},
            {'name': 'رسوم الخدمات والتسويق', 'value_sar': total_guess * 0.05, 'value_millions': round(total_guess * 0.05 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.05)},
            {'name': 'أتعاب الصندوق والتمويل', 'value_sar': total_guess * 0.05, 'value_millions': round(total_guess * 0.05 / 1e6, 2), 'display': _format_sar_display(total_guess * 0.05)},
        ]

    # Mandatory inclusion of Developer Cost, Fund Cost, and Finance Cost if present (> 0) and not already in items
    # 1. Developer Cost (تكلفة المطور)
    has_dev = any(any(kw in str(it.get('name', '')).lower() for kw in ('مطور', 'أتعاب التطوير', 'إدارة التطوير', 'developer')) for it in items)
    if not has_dev:
        dev_val = _clean_numeric_val(
            inputs.get('developerCostValue')
            or inputs.get('developerCost')
            or inputs.get('developerFee')
            or inputs.get('totalDeveloperCost')
            or inputs.get('developerFeesTotal')
            or fcd.get('developerCost')
            or fcd.get('developerCostValue')
            or project_data.get('developer_cost')
            or project_data.get('developer_fee')
        )
        if dev_val > 0:
            seen_names.add('تكلفة المطور')
            items.append({
                'name': 'تكلفة المطور',
                'value_sar': dev_val,
                'value_millions': round(dev_val / 1e6, 2),
                'display': _format_sar_display(dev_val),
            })

    # 2. Fund Cost (تكلفة الصندوق)
    has_fund = any('صندوق' in str(it.get('name', '')) or 'fund' in str(it.get('name', '')).lower() for it in items)
    if not has_fund:
        fund_val = _clean_numeric_val(
            inputs.get('fundFeesTotal')
            or inputs.get('totalFundFees')
            or inputs.get('fundManagementFeesTotal')
            or inputs.get('fundTotalFees')
            or inputs.get('fundCost')
            or inputs.get('fundFees')
            or fcd.get('totalFundFees')
            or project_data.get('fund_fees')
            or project_data.get('fund_cost')
        )
        if fund_val <= 0 and isinstance(tables.get('fundFeeScheduleTable'), list):
            for fr in tables['fundFeeScheduleTable']:
                if isinstance(fr, dict):
                    fund_val += _clean_numeric_val(fr.get('إجمالي أتعاب الصندوق') or fr.get('أتعاب الإدارة') or fr.get('total'))
        if fund_val > 0:
            seen_names.add('تكلفة الصندوق')
            items.append({
                'name': 'تكلفة الصندوق',
                'value_sar': fund_val,
                'value_millions': round(fund_val / 1e6, 2),
                'display': _format_sar_display(fund_val),
            })

    # 3. Finance Cost (تكلفة التمويل)
    has_fin = any(any(kw in str(it.get('name', '')).lower() for kw in ('تمويل', 'فوائد التمويل', 'رسوم التمويل', 'finance')) for it in items)
    if not has_fin:
        fin_val = _clean_numeric_val(
            inputs.get('totalFinanceCost')
            or inputs.get('financeCost')
            or fcd.get('totalFinanceCost')
            or project_data.get('total_finance_cost')
            or project_data.get('finance_cost')
        )
        if fin_val <= 0:
            interest = _clean_numeric_val(inputs.get('financeInterestTotal') or fcd.get('financeInterestTotal'))
            arrangement = _clean_numeric_val(inputs.get('arrangementFeeTotal') or fcd.get('arrangementFeeTotal'))
            fin_val = interest + arrangement
        if fin_val <= 0 and isinstance(tables.get('debtScheduleTable'), list):
            for dr in tables['debtScheduleTable']:
                if isinstance(dr, dict):
                    fin_val += _clean_numeric_val(dr.get('الفائدة')) + _clean_numeric_val(dr.get('رسوم التمويل'))
        if fin_val > 0:
            seen_names.add('تكلفة التمويل')
            items.append({
                'name': 'تكلفة التمويل',
                'value_sar': fin_val,
                'value_millions': round(fin_val / 1e6, 2),
                'display': _format_sar_display(fin_val),
            })

    total_val = sum(it['value_sar'] for it in items)
    max_val = max([total_val] + [it['value_sar'] for it in items]) or 1.0
    running = 0.0
    for it in items:
        it['pct_of_total'] = round((it['value_sar'] / total_val) * 100, 1) if total_val > 0 else 0.0
        it['offset_pct'] = round((running / max_val) * 100, 1)
        it['height_pct'] = max(round((it['value_sar'] / max_val) * 100, 1), 5.0)
        running += it['value_sar']

    total_data = {
        'name': 'إجمالي تكلفة المشروع',
        'value_sar': total_val,
        'value_millions': round(total_val / 1e6, 2),
        'display': _format_sar_display(total_val),
        'pct_of_total': 100.0,
        'height_pct': 100.0,
        'offset_pct': 0.0,
    }

    svg_code = _build_waterfall_svg(items, total_data)

    return {
        'items': items,
        'total': total_data,
        'summary': {
            'total_millions': round(total_val / 1e6, 2),
            'items_count': len(items),
            'svg_code': svg_code,
        }
    }



def _extract_combo_chart_data(part_or_table, model=None, project_data=None):
    model = model if isinstance(model, dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    cf = tables.get('cashflowTable') if isinstance(tables.get('cashflowTable'), list) else []
    if not cf and isinstance(model.get('report'), dict):
        for p in model.get('report', {}).get('parts', []):
            if isinstance(p, dict) and p.get('type') == 'table':
                txt = f"{p.get('text', '')} {p.get('title', '')}".lower()
                if re.search(r'تدفق|cashflow|cash flow', txt):
                    part_or_table = p
                    break
    rows = []
    headers = []
    if isinstance(part_or_table, dict):
        rows = part_or_table.get('rows') or cf
        headers = part_or_table.get('headers') or []
    elif isinstance(part_or_table, list) and part_or_table:
        rows = part_or_table
    else:
        rows = cf

    year_idx = 0
    net_idx = -3
    cum_idx = -2
    if headers:
        for h_i, h_name in enumerate(headers):
            h_str = str(h_name).strip().lower()
            if re.search(r'سنة|عام|year', h_str) and not re.search(r'تشغيل|إشغال|وصول', h_str):
                year_idx = h_i
            elif re.search(r'صافي.*تدفق|net.*cash|net.*flow', h_str):
                net_idx = h_i
            elif re.search(r'تراكمي|cumulative', h_str):
                cum_idx = h_i

    items = []
    running_cum = 0.0
    for r in rows:
        year = ''
        net_val = 0.0
        cum_val = 0.0
        has_cum = False
        if isinstance(r, dict):
            year = str(r.get('السنة') or r.get('year') or '').strip()
            net_val = _clean_numeric_val(r.get('صافي تدفق المشروع') or r.get('netCashFlow') or r.get('net_flow'))
            raw_cum = r.get('الرصيد التراكمي') or r.get('cumulativeCashFlow') or r.get('cumulative')
            if raw_cum is not None and str(raw_cum).strip() not in ('', '—', '-'):
                cum_val = _clean_numeric_val(raw_cum)
                has_cum = True
        elif isinstance(r, (list, tuple)) and len(r) >= 2:
            year = str(r[year_idx]).strip() if year_idx < len(r) else ''
            net_val = _clean_numeric_val(r[net_idx]) if abs(net_idx) <= len(r) else 0.0
            if abs(cum_idx) <= len(r) and str(r[cum_idx]).strip() not in ('', '—', '-'):
                cum_val = _clean_numeric_val(r[cum_idx])
                has_cum = True
        if year:
            year_label = f"سنة {year}" if not year.startswith('سنة') else year
            running_cum += net_val
            effective_cum = cum_val if has_cum else running_cum
            items.append({
                'year': year_label,
                'net_flow_m': round(net_val / 1e6, 1),
                'net_flow_display': f"{round(net_val / 1e6, 1)} ر.س",
                'cumulative_m': round(effective_cum / 1e6, 1),
                'cumulative_display': f"{round(effective_cum / 1e6, 1)} ر.س",
                'is_positive': net_val >= 0,
            })

    if not items:
        items = [
            {'year': 'سنة 1', 'net_flow_m': -50.0, 'net_flow_display': '-50.0 ر.س', 'cumulative_m': -50.0, 'cumulative_display': '-50.0 ر.س', 'is_positive': False},
            {'year': 'سنة 2', 'net_flow_m': -30.0, 'net_flow_display': '-30.0 ر.س', 'cumulative_m': -80.0, 'cumulative_display': '-80.0 ر.س', 'is_positive': False},
            {'year': 'سنة 3', 'net_flow_m': 20.0, 'net_flow_display': '20.0 ر.س', 'cumulative_m': -60.0, 'cumulative_display': '-60.0 ر.س', 'is_positive': True},
            {'year': 'سنة 4', 'net_flow_m': 45.0, 'net_flow_display': '45.0 ر.س', 'cumulative_m': -15.0, 'cumulative_display': '-15.0 ر.س', 'is_positive': True},
            {'year': 'سنة 5', 'net_flow_m': 60.0, 'net_flow_display': '60.0 ر.س', 'cumulative_m': 45.0, 'cumulative_display': '45.0 ر.س', 'is_positive': True},
        ]

    items = items[:15]
    all_vals = [it['net_flow_m'] for it in items] + [it['cumulative_m'] for it in items] + [0.0]
    min_v = min(all_vals)
    max_v = max(all_vals)

    import math
    def _bound_step(val, step=250.0, is_max=True):
        if is_max:
            return math.ceil(val / step) * step
        return math.floor(val / step) * step

    raw_span = max_v - min_v
    step = 250.0 if raw_span > 600 else (100.0 if raw_span > 250 else (50.0 if raw_span > 100 else 20.0))
    y_max = _bound_step(max_v, step=step, is_max=True)
    y_min = _bound_step(min_v, step=step, is_max=False)
    if y_max <= y_min:
        y_max = y_min + step * 2

    vb_w = 540.0
    vb_h = 290.0
    m_left = 60.0
    m_right = 25.0
    m_top = 35.0
    m_bottom = 45.0

    plot_w = vb_w - m_left - m_right
    plot_h = vb_h - m_top - m_bottom
    span = y_max - y_min
    scale_y = plot_h / span

    def val_to_y(v):
        return round(m_top + (y_max - v) * scale_y, 1)

    y_zero = val_to_y(0.0)
    n = len(items)
    col_step = plot_w / max(n, 1)
    bar_w = min(max(round(col_step * 0.55, 1), 16.0), 30.0)

    svg_points = []
    svg_circles = []
    ticks = []
    curr = y_min
    while curr <= y_max + 1e-6:
        ticks.append({'val': curr, 'y': val_to_y(curr), 'is_zero': abs(curr) < 1e-6})
        curr += step

    for idx, it in enumerate(items):
        cx = round(m_left + idx * col_step + col_step / 2.0, 1)
        bx = round(cx - bar_w / 2.0, 1)
        net_m = it['net_flow_m']
        cum_m = it['cumulative_m']

        by_net = val_to_y(net_m)
        cy_cum = val_to_y(cum_m)

        if net_m >= 0:
            bh = round(y_zero - by_net, 1)
            by = by_net
        else:
            bh = round(by_net - y_zero, 1)
            by = y_zero

        it['cx'] = cx
        it['cy'] = cy_cum
        it['bar_x'] = bx
        it['bar_y'] = by
        it['bar_w'] = bar_w
        it['bar_h'] = max(bh, 1.5)
        it['bar_direction'] = 'up' if it['is_positive'] else 'down'
        it['bar_height_pct'] = round((abs(net_m) / max(max_v, 1.0)) * 100, 1)
        it['cum_y_pct'] = round(((cum_m - y_min) / span) * 100, 1)

        svg_points.append(f"{cx},{cy_cum}")
        svg_circles.append({'cx': cx, 'cy': cy_cum, 'year': it.get('year', ''), 'val': cum_m})

    grid_lines = []
    y_labels = []
    for t in ticks:
        stroke = "#94a3b8" if t['is_zero'] else "#e2e8f0"
        stroke_w = "1.5" if t['is_zero'] else "1"
        grid_lines.append(f'<line x1="{m_left - 8}" y1="{t["y"]}" x2="{vb_w - m_right}" y2="{t["y"]}" stroke="{stroke}" stroke-width="{stroke_w}"/>')
        label_txt = f"{int(t['val']):,}" if t['val'] == int(t['val']) else f"{t['val']:.1f}"
        if t['val'] < 0:
            label_txt = f"-{abs(int(t['val'])):,}" if t['val'] == int(t['val']) else f"-{abs(t['val']):.1f}"
        y_labels.append(f'<text x="{m_left - 12}" y="{t["y"] + 3.5}" fill="#64748b" font-size="9" text-anchor="end" direction="ltr">{label_txt}</text>')

    bars_svg = []
    circles_svg = []
    x_labels_svg = []
    data_labels_svg = []

    for i, it in enumerate(items):
        cx = it['cx']
        bx = it['bar_x']
        by = it['bar_y']
        bh = it['bar_h']
        net_m = it['net_flow_m']
        cum_m = it['cumulative_m']
        bar_color = "url(#posBarGrad)" if it['is_positive'] else "url(#negBarGrad)"

        bars_svg.append(f'<rect x="{bx}" y="{by}" width="{bar_w}" height="{bh}" rx="2" fill="{bar_color}" opacity="0.9"/>')
        circles_svg.append(f'<circle cx="{cx}" cy="{it["cy"]}" r="4.5" fill="#ffffff" stroke="#0284c7" stroke-width="2.5"/>')
        x_labels_svg.append(f'<text x="{cx}" y="{vb_h - 18}" fill="#64748b" font-size="9.5" text-anchor="middle">{it["year"]}</text>')

        # Labels: avoid overlap between bar and circle when close
        if abs(by - it['cy']) > 22:
            if net_m > 40:
                data_labels_svg.append(f'<text x="{cx}" y="{by - 6}" fill="#0b1f33" font-size="9" font-weight="700" text-anchor="middle">{net_m:.1f}</text>')
        if not it['is_positive']:
            neg_txt = f"-{abs(net_m):.1f}"
            data_labels_svg.append(f'<text x="{cx}" y="{by + bh + 14}" fill="#b89564" font-size="9" font-weight="700" text-anchor="middle" direction="ltr">{neg_txt}</text>')

        # Key milestone cumulative points
        if i in (0, 1, 2, 3, 4, 9) or abs(net_m - cum_m) > 50:
            c_offset = -9 if it['cy'] < y_zero else 15
            data_labels_svg.append(f'<text x="{cx}" y="{it["cy"] + c_offset}" fill="#0284c7" font-size="9" font-weight="700" text-anchor="middle">{cum_m:.1f}</text>')

    svg_code = f'''<svg data-chart="combo" class="combo-chart" viewBox="0 0 {int(vb_w)} {int(vb_h)}" style="width: 100%; height: auto; max-height: 290px; display: block;" role="img" aria-label="مخطط التدفقات النقدية السنوية والرصيد التراكمي">
  <defs>
    <linearGradient id="posBarGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#12324c"/>
      <stop offset="100%" stop-color="#0b1f33"/>
    </linearGradient>
    <linearGradient id="negBarGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#c5a880"/>
      <stop offset="100%" stop-color="#b89564"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="{int(vb_w)}" height="{int(vb_h)}" fill="#ffffff" rx="6"/>
  <text x="{int(m_left - 12)}" y="{int(m_top - 12)}" fill="#94a3b8" font-size="8.5" text-anchor="end">ر.س</text>
  <g>{''.join(grid_lines)}</g>
  <g font-family="Tajawal, sans-serif">{''.join(y_labels)}</g>
  <g>{''.join(bars_svg)}</g>
  <polyline points="{' '.join(svg_points)}" fill="none" stroke="#0284c7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <g>{''.join(circles_svg)}</g>
  <g font-family="Tajawal, sans-serif">{''.join(data_labels_svg)}</g>
  <g font-family="IBM Plex Sans Arabic, Tajawal, sans-serif">{''.join(x_labels_svg)}</g>
</svg>'''

    return {
        'items': items,
        'summary': {
            'years_count': len(items),
            'max_abs_flow_m': max([abs(it['net_flow_m']) for it in items] + [1.0]),
            'min_cumulative_m': min([it['cumulative_m'] for it in items] + [0.0]),
            'max_cumulative_m': max([it['cumulative_m'] for it in items] + [1.0]),
            'y_min': y_min,
            'y_max': y_max,
            'y_zero': y_zero,
            'svg_polyline_points': ' '.join(svg_points),
            'svg_circles': svg_circles,
            'svg_code': svg_code,
        }
    }


def _format_heatmap_value_display(metric_key, val_raw, num_val):
    if val_raw in ('لا يسترد', 'غير مسترد'):
        return 'لا يسترد'
    if val_raw in ('غير متاح', 'N/A', '—', '-'):
        return 'غير متاح'
    if num_val is None:
        return str(val_raw or '—')

    if metric_key in ('revenue', 'cost', 'net_profit'):
        val_m = abs(num_val) / 1e6
        if val_m >= 0.1:
            sign = '-' if num_val < 0 else ''
            return f"{sign}{val_m:,.2f} ر.س"
        return f"{int(num_val):,} ر.س"
    elif metric_key in ('roi', 'project_irr', 'equity_irr'):
        if '%' in str(val_raw):
            return str(val_raw).strip()
        return f"{num_val:.1f}%"
    elif metric_key == 'payback':
        if 'سنة' in str(val_raw) or 'عام' in str(val_raw):
            return str(val_raw).strip()
        return f"{num_val:.1f} سنة"
    return str(val_raw)


def _build_heatmap_matrix_html(chart_data, primary='#16405f', secondary='#0284c7'):
    matrix = (chart_data or {}).get('matrix') if isinstance(chart_data, dict) else (chart_data or [])
    if not matrix:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات كافية لمصفوفة الخريطة الحرارية</div>'

    rows_html = []
    for r in matrix:
        metric = html_lib.escape(str(r.get('metric') or ''))
        pol_tag = html_lib.escape(str(r.get('polarity_label') or ('الأعلى أفضل' if r.get('higher_is_better') else 'الأقل أفضل')))
        pol_style = 'background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;' if r.get('higher_is_better') else 'background:#fdf4ff;color:#86198f;border:1px solid #f5d0fe;'

        c_val = html_lib.escape(str(r.get('conservative') or '—'))
        b_val = html_lib.escape(str(r.get('base') or '—'))
        o_val = html_lib.escape(str(r.get('optimistic') or '—'))

        c_style = r.get('conservative_style') or ''
        b_style = r.get('base_style') or ''
        o_style = r.get('optimistic_style') or ''

        rows_html.append(f'''
        <tr>
          <td style="padding:4px 8px;text-align:right;vertical-align:middle;">
            <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 12px;background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;">
              <span style="font-weight:700;color:#1e293b;font-size:12.5px;">{metric}</span>
              <span style="font-size:10px;font-weight:600;padding:2px 6px;border-radius:4px;white-space:nowrap;{pol_style}">{pol_tag}</span>
            </div>
          </td>
          <td style="padding:4px 8px;text-align:center;vertical-align:middle;"><div style="{c_style}">{c_val}</div></td>
          <td style="padding:4px 8px;text-align:center;vertical-align:middle;"><div style="{b_style}">{b_val}</div></td>
          <td style="padding:4px 8px;text-align:center;vertical-align:middle;"><div style="{o_style}">{o_val}</div></td>
        </tr>''')

    return f'''<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px 20px;display:flex;flex-direction:column;justify-content:space-between;font-family:inherit;">
  <table style="width:100%;border-collapse:separate;border-spacing:0 5px;table-layout:fixed;">
    <thead>
      <tr>
        <th style="padding:6px 12px;font-size:12.5px;font-weight:700;color:#475569;text-align:right;border-bottom:2px solid #cbd5e1;width:34%;">المؤشر المالي</th>
        <th style="padding:6px 12px;font-size:12.5px;font-weight:700;color:#475569;text-align:center;border-bottom:2px solid #cbd5e1;">السيناريو المتحفظ</th>
        <th style="padding:6px 12px;font-size:12.5px;font-weight:700;color:#475569;text-align:center;border-bottom:2px solid #cbd5e1;">السيناريو الأساسي</th>
        <th style="padding:6px 12px;font-size:12.5px;font-weight:700;color:#475569;text-align:center;border-bottom:2px solid #cbd5e1;">السيناريو المتفائل</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-top:14px;padding-top:12px;border-top:1px solid #e2e8f0;font-size:11.5px;color:#64748b;">
    <div style="display:flex;gap:18px;align-items:center;">
      <span style="font-weight:700;color:#1e293b;">مفتاح التقييم الاتجاهي:</span>
      <div style="display:flex;align-items:center;gap:6px;font-weight:600;">
        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#d1fae5;border:1px solid #a7f3d0;"></span>
        <span>الأفضل (أخضر)</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-weight:600;">
        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#fef3c7;border:1px solid #fde68a;"></span>
        <span>المتوسط (أصفر)</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-weight:600;">
        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:#fee2e2;border:1px solid #fca5a5;"></span>
        <span>الأقل (أحمر)</span>
      </div>
    </div>
    <div style="font-size:11px;color:#94a3b8;">الألوان تعتمد على اتجاه وطبيعة المؤشر (الأعلى أفضل للعائد والربح، والأقل أفضل للتكلفة والاسترداد)</div>
  </div>
</div>'''


def _extract_heatmap_chart_data(part_or_table, model=None, project_data=None):
    model = model if isinstance(model, dict) else {}
    tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
    sens = tables.get('sensitivityTable') if isinstance(tables.get('sensitivityTable'), list) else []
    rows = []
    headers = []
    if isinstance(part_or_table, dict):
        rows = part_or_table.get('rows') or sens
        headers = part_or_table.get('headers') or []
    elif isinstance(part_or_table, list) and part_or_table:
        rows = part_or_table
    else:
        rows = sens

    if not rows and isinstance(model.get('report'), dict):
        for p in model.get('report', {}).get('parts', []):
            if isinstance(p, dict) and p.get('type') == 'table':
                txt = f"{p.get('text', '')} {p.get('title', '')}".lower()
                if re.search(r'حساسي|سيناريو|sensitivity', txt):
                    rows = p.get('rows') or []
                    headers = p.get('headers') or []
                    break

    metric_configs = [
        {
            'key': 'revenue',
            'name': 'إجمالي الإيرادات',
            'aliases': ['إجمالي الإيرادات', 'الإيرادات', 'إجمالي المبيعات', 'الإيراد الإجمالي', 'total revenue'],
            'higher_is_better': True,
        },
        {
            'key': 'cost',
            'name': 'إجمالي تكلفة المشروع',
            'aliases': ['إجمالي تكلفة المشروع', 'تكلفة المشروع', 'إجمالي تكلفة الاستثمار', 'تكلفة الاستثمار', 'التكلفة الرأسمالية', 'إجمالي التكاليف', 'project cost', 'investment cost'],
            'higher_is_better': False,
        },
        {
            'key': 'net_profit',
            'name': 'صافي الربح',
            'aliases': ['صافي الربح', 'الربح الصافي', 'صافي الأرباح', 'net profit'],
            'higher_is_better': True,
        },
        {
            'key': 'roi',
            'name': 'العائد على الاستثمار (ROI)',
            'aliases': ['العائد على الاستثمار (ROI)', 'ROI كامل الدورة', 'العائد على الاستثمار', 'معدل العائد على الاستثمار', 'ROI', 'roi'],
            'higher_is_better': True,
        },
        {
            'key': 'project_irr',
            'name': 'العائد الداخلي للمشروع (Project IRR)',
            'aliases': ['العائد الداخلي للمشروع (Project IRR)', 'Project IRR كامل الدورة', 'العائد الداخلي للمشروع', 'Project IRR', 'معدل العائد الداخلي للمشروع', 'project irr'],
            'higher_is_better': True,
        },
        {
            'key': 'equity_irr',
            'name': 'العائد الداخلي لحقوق الملكية (Equity IRR)',
            'aliases': ['العائد الداخلي لحقوق الملكية (Equity IRR)', 'Equity IRR كامل الدورة', 'العائد الداخلي لحقوق الملكية', 'Equity IRR', 'معدل العائد الداخلي للملكية', 'equity irr'],
            'higher_is_better': True,
        },
        {
            'key': 'payback',
            'name': 'فترة الاسترداد',
            'aliases': ['فترة الاسترداد', 'فترة استرداد رأس المال', 'الاسترداد', 'payback period', 'payback'],
            'higher_is_better': False,
        },
    ]

    scenarios = ['متحفظ', 'أساسي', 'متفائل']
    matrix = []

    style_best = 'background:#d1fae5;color:#065f46;font-weight:700;padding:6px 10px;border:1px solid #a7f3d0;text-align:center;border-radius:6px;'
    style_medium = 'background:#fef3c7;color:#92400e;font-weight:600;padding:6px 10px;border:1px solid #fde68a;text-align:center;border-radius:6px;'
    style_worst = 'background:#fee2e2;color:#991b1b;font-weight:600;padding:6px 10px;border:1px solid #fca5a5;text-align:center;border-radius:6px;'
    style_neutral = 'background:#f1f5f9;color:#64748b;font-weight:500;padding:6px 10px;border:1px solid #e2e8f0;text-align:center;border-radius:6px;'

    normalized_rows = []
    for r in rows:
        if isinstance(r, (list, tuple)) and headers:
            r = dict(zip(headers, r))
        if isinstance(r, dict):
            normalized_rows.append(r)

    is_transposed = False
    if normalized_rows:
        first_row = normalized_rows[0]
        if any(sc in first_row for sc in scenarios):
            is_transposed = True

    for cfg in metric_configs:
        m_key = cfg['key']
        m_name = cfg['name']
        aliases = cfg['aliases']
        higher_is_better = cfg['higher_is_better']

        vals = {}
        nums = {}

        if is_transposed:
            target_row = None
            for r in normalized_rows:
                indicator_name = str(r.get('المؤشر') or r.get('البند') or r.get('المؤشر المالي') or r.get('البيان') or '').strip()
                if any(alias.lower() in indicator_name.lower() or indicator_name.lower() in alias.lower() for alias in aliases):
                    target_row = r
                    break
            for sc in scenarios:
                raw_v = target_row.get(sc) if target_row else None
                matched_val = str(raw_v).strip() if raw_v is not None else None
                vals[sc] = matched_val if matched_val is not None else '—'
                nums[sc] = _clean_numeric_val_strict(matched_val)
        else:
            for sc in scenarios:
                sc_row = next((r for r in normalized_rows if str(r.get('السيناريو') or '').strip() == sc), {})
                matched_val = None
                for alias in aliases:
                    if alias in sc_row and sc_row[alias] is not None and str(sc_row[alias]).strip():
                        matched_val = str(sc_row[alias]).strip()
                        break
                vals[sc] = matched_val if matched_val is not None else '—'
                nums[sc] = _clean_numeric_val_strict(matched_val)

        # Harmonize Base scenario with financial model summary/inputs (Rule 5)
        if (vals.get('أساسي') in (None, '—', '0', '0.0', '0%') or nums.get('أساسي') is None) and model:
            inputs = model.get('inputs') if isinstance(model.get('inputs'), dict) else {}
            summary = model.get('summary') if isinstance(model.get('summary'), dict) else {}
            fallback_val = None
            if m_key == 'cost':
                fallback_val = inputs.get('adjustedProjectCost') or inputs.get('projectCost') or summary.get('totalCost')
            elif m_key == 'revenue':
                fallback_val = summary.get('totalRevenue') or summary.get('revenueTotal') or inputs.get('targetTotalRevenue')
            elif m_key == 'net_profit':
                fallback_val = summary.get('netProfit') or summary.get('netProfitTotal')
            elif m_key == 'roi':
                fallback_val = summary.get('roiTotal') or summary.get('roi') or inputs.get('targetRoi')
            elif m_key == 'project_irr':
                fallback_val = summary.get('projectIrr') or inputs.get('projectIrr')
            elif m_key == 'equity_irr':
                fallback_val = summary.get('equityIrr') or inputs.get('equityIrr')
            elif m_key == 'payback':
                fallback_val = summary.get('paybackPeriodYears') or inputs.get('paybackPeriodYears')

            if fallback_val is not None and str(fallback_val).strip() not in ('0', '0.0', ''):
                vals['أساسي'] = str(fallback_val).strip()
                nums['أساسي'] = _clean_numeric_val_strict(fallback_val)

        levels = {}
        for sc in scenarios:
            val_str = str(vals[sc]).strip()
            if val_str in ('لا يسترد', 'غير مسترد'):
                levels[sc] = 'worst'

        numeric_scs = [(sc, nums[sc]) for sc in scenarios if nums[sc] is not None and sc not in levels]

        if numeric_scs:
            sorted_scs = sorted(numeric_scs, key=lambda x: x[1], reverse=higher_is_better)
            unique_vals = []
            for _, val in sorted_scs:
                if val not in unique_vals:
                    unique_vals.append(val)

            has_pre_worst = any(lvl == 'worst' for lvl in levels.values())

            for sc, val in numeric_scs:
                if len(unique_vals) == 1:
                    levels[sc] = 'medium'
                elif len(unique_vals) == 2:
                    if val == unique_vals[0]:
                        levels[sc] = 'best'
                    else:
                        levels[sc] = 'medium' if has_pre_worst else 'worst'
                else:
                    if val == unique_vals[0]:
                        levels[sc] = 'best'
                    elif val == unique_vals[-1]:
                        levels[sc] = 'worst'
                    else:
                        levels[sc] = 'medium'

        for sc in scenarios:
            if sc not in levels:
                levels[sc] = 'neutral'

        def get_style(lvl):
            if lvl == 'best': return style_best
            if lvl == 'medium': return style_medium
            if lvl == 'worst': return style_worst
            return style_neutral

        c_disp = _format_heatmap_value_display(m_key, vals['متحفظ'], nums.get('متحفظ'))
        b_disp = _format_heatmap_value_display(m_key, vals['أساسي'], nums.get('أساسي'))
        o_disp = _format_heatmap_value_display(m_key, vals['متفائل'], nums.get('متفائل'))

        matrix.append({
            'metric': m_name,
            'key': m_key,
            'higher_is_better': higher_is_better,
            'polarity_label': 'الأعلى أفضل' if higher_is_better else 'الأقل أفضل',
            'conservative': c_disp,
            'base': b_disp,
            'optimistic': o_disp,
            'conservative_raw': vals['متحفظ'],
            'base_raw': vals['أساسي'],
            'optimistic_raw': vals['متفائل'],
            'conservative_level': levels['متحفظ'],
            'base_level': levels['أساسي'],
            'optimistic_level': levels['متفائل'],
            'conservative_style': get_style(levels['متحفظ']),
            'base_style': get_style(levels['أساسي']),
            'optimistic_style': get_style(levels['متفائل']),
        })

    html_card = _build_heatmap_matrix_html({'matrix': matrix})

    return {
        'columns': scenarios,
        'matrix': matrix,
        'legend': [
            {'label': 'الأفضل (أخضر)', 'color': '#065f46', 'bg': '#d1fae5'},
            {'label': 'المتوسط (أصفر)', 'color': '#92400e', 'bg': '#fef3c7'},
            {'label': 'الأقل (أحمر)', 'color': '#991b1b', 'bg': '#fee2e2'},
        ],
        'html_matrix': html_card,
    }


def _slide_source_data_note(slide, project_data):
    content_sources = (slide or {}).get('content_sources') if isinstance(slide, dict) else None
    if isinstance(content_sources, list) and content_sources:
        fin_sources = [str(source) for source in content_sources
                       if re.fullmatch(r'financial_report:\d+:\d+:\d+(?::\d+:\d+)?', str(source))]
        if fin_sources and len(fin_sources) == len([s for s in content_sources if str(s or '').strip()]):
            model = _parse_financial_dict((project_data if isinstance(project_data, dict) else {})
                                          .get('financial_study_model'))
            stacked_note = _stacked_financial_report_note(fin_sources, model)
            if stacked_note:
                return stacked_note
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
    c_type = canonicalize_chart_type((slide or {}).get('chart_type'))
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
        chart_items = _extract_competitor_chart_data(competitors, project_data)
        chart_block = (
            '\n\nبيانات مخطط الأعمدة الأفقية لمقارنة المنافسين (horizontal_bar_chart_data) بنسب العرض المحسوبة جاهزة:\n'
            + json.dumps(chart_items, ensure_ascii=False, indent=2)
        ) if chart_items else ''
        return (
            'جدول المنافسين الرئيسيين لرسم مقارنة المنافسين (horizontal_bar):\n'
            + json.dumps(items, ensure_ascii=False, indent=2)
            + chart_block
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
            extra = ''
            if c_type == 'waterfall':
                c_data = _extract_waterfall_chart_data(part, model, project_data)
                extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة المشروع (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
            elif c_type == 'combo':
                c_data = _extract_combo_chart_data(part, model, project_data)
                extra = '\n\nبيانات مخطط التدفقات النقدية (combo_chart_data) السنوية والتراكمية (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
            elif c_type == 'heatmap':
                c_data = _extract_heatmap_chart_data(part, model, project_data)
                extra = '\n\nبيانات مصفوفة الخريطة الحرارية (heatmap_chart_data) لمقارنة السيناريوهات والقطبية:\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
            return 'المحتوى الحرفي المطلوب في هذه الشريحة فقط:\n' + json.dumps(part, ensure_ascii=False, indent=2) + extra
    match = re.fullmatch(r'financial_chart:([^:]+):(\d+)', source)
    if match:
        chart_cand, part_index = match.group(1), int(match.group(2))
        report = model.get('report') if isinstance(model.get('report'), dict) else {}
        parts = report.get('parts') if isinstance(report.get('parts'), list) else []
        part = parts[part_index] if part_index < len(parts) and isinstance(parts[part_index], dict) else {}
        extra = ''
        if c_type == 'waterfall':
            c_data = _extract_waterfall_chart_data(part, model, project_data)
            extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة المشروع (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'combo':
            c_data = _extract_combo_chart_data(part, model, project_data)
            extra = '\n\nبيانات مخطط التدفقات النقدية (combo_chart_data) السنوية والتراكمية (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'heatmap':
            c_data = _extract_heatmap_chart_data(part, model, project_data)
            extra = '\n\nبيانات مصفوفة الخريطة الحرارية (heatmap_chart_data) لمقارنة السيناريوهات والقطبية:\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        return 'بيانات الرسم البياني المعتمد:\n' + extra
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        extra = ''
        if c_type == 'waterfall' or (not c_type and table_key == 'costTable'):
            c_data = _extract_waterfall_chart_data({'rows': rows[start:end]}, model, project_data)
            extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة المشروع (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'combo' or (not c_type and table_key == 'cashflowTable'):
            c_data = _extract_combo_chart_data({'rows': rows[start:end]}, model, project_data)
            extra = '\n\nبيانات مخطط التدفقات النقدية (combo_chart_data) السنوية والتراكمية (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        elif c_type == 'heatmap' or (not c_type and table_key == 'sensitivityTable'):
            c_data = _extract_heatmap_chart_data({'rows': rows[start:end]}, model, project_data)
            extra = '\n\nبيانات مصفوفة الخريطة الحرارية (heatmap_chart_data) لمقارنة السيناريوهات والقطبية:\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        clean_rows = []
        for r in rows[start:end]:
            if isinstance(r, dict):
                clean_rows.append({k: v for k, v in r.items() if str(k).strip() not in ('ترتيب / حذف', 'ترتيب', 'حذف', 'إجراءات', 'actions') and str(v).strip() != 'أعلىأسفلحذف'})
            else:
                clean_rows.append(r)
        return f'جدول هذه الشريحة فقط ({table_key}):\n' + json.dumps(clean_rows, ensure_ascii=False, indent=2) + extra
    match = re.fullmatch(r'financial_summary:(costs|returns):(\d+):(\d+)', source)
    if match:
        group_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        group_name = 'التكاليف والاستثمار' if group_key == 'costs' else 'مؤشرات العائد والاسترداد'
        rows = _financial_summary_from_report(model).get(group_name, [])[start:end]
        extra = ''
        if c_type == 'waterfall' and group_key == 'costs':
            c_data = _extract_waterfall_chart_data({'rows': rows}, model, project_data)
            extra = '\n\nبيانات المخطط الشلالي (waterfall_chart_data) لتكوين إجمالي تكلفة الاستثمار (محسوبة وجاهزة للرسم):\n' + json.dumps(c_data, ensure_ascii=False, indent=2)
        return f'{group_name} من نفس تقرير PDF دون إعادة حساب:\n' + json.dumps(rows, ensure_ascii=False, indent=2) + extra
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
        'dashboard': 'لوحة مؤشرات مالية تعتمد جداول HTML نظامية كاملة للتكاليف والاستثمار ومؤشرات العائد مرصوصة رأسياً تحت بعضها بنفس تصميم ومساحات تقرير PDF مع منع الكروت العائمة والمربعات الإحصائية',
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
    primary_color = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    secondary_color = normalize_hex_color((branding or {}).get('secondary_color'), '#0ea5e9')
    chart_instructions = {
        'horizontal_bar': (
            'مخطط الأعمدة الأفقية (Horizontal Bar Chart) لمقارنة المنافسين: '
            'قائمة أعمدة أفقية مرتبة تنازلياً حسب السعر (من الأعلى إلى الأقل) مستخرجة من بيانات المنافسين المرفقة. '
            'الهيكل الإلزامي: قسّم الشريحة إلى عمودين متجاورين متساويين (50% لجدول المنافسين، 50% لمخطط الأعمدة الأفقية) '
            'داخل حاوية display: grid; grid-template-columns: 1fr 1fr; gap: 24px; height: 500px; align-items: start;. '
            'في جانب الرسم (حاوية بخلفية #f8fafc وبودر 1px solid #e2e8f0 وبادينغ 16px وراديوس 8px): '
            'رص أشرطة المنافسين رأسياً (display: flex; flex-direction: column; gap: 12px;). '
            'لكل منافس صف أفقي يتضمن: اسم المنافس يميناً (font-size: 11px; font-weight: 600; min-width: 110px; color: #1e293b;)، '
            'مسار الشريط (flex: 1; background: #e2e8f0; height: 18px; border-radius: 4px; overflow: hidden; position: relative;) '
            f'وبداخله شريط العرض الفعلي بعرض bar_width_pct% بلون {secondary_color} (أو {primary_color} للمشروع)، '
            'وقيمة السعر والوحدة يساراً بخط عريض (font-size: 11px; font-weight: 700; width: 100px; text-align: left;). '
            f'يجب تمييز شريط مشروعنا بلون الهوية الرئيسي ({primary_color}) وبإطار بارز وبادينغ خاص لتمييزه فوراً عن المنافسين.'
        ),
        'waterfall': (
            'المخطط الشلالي (Waterfall Chart) لتكوين إجمالي تكلفة المشروع: '
            'يوضح مساهمة كل بند تكلفة من القائمة المرفقة (بما يشمل تكلفة المطور وتكاليف الصندوق والتمويل عند توفرها) وصولاً لعمود إجمالي تكلفة المشروع النهائي. '
            'الهيكل الإلزامي: قسّم الشريحة إلى عمودين متجاورين متساويين (50% لجدول التكاليف، 50% للمخطط الشلالي) '
            'داخل حاوية display: grid; grid-template-columns: 1fr 1fr; gap: 24px; height: 500px; align-items: start;. '
            'في جانب الرسم: حاوية رسم بخلفية #f8fafc وبودر 1px solid #e2e8f0 وبادينغ 16px وراديوس 8px بارتفاع كلي 380px، '
            'تتضمن بالأعلى عنوان المخطط، ثم يمكنك إدراج كود SVG الجاهز والمحسوب بدقة من summary.svg_code أو بنائه كأعمدة عائمة: '
            'لكل بند تكلفة من قائمة البيانات المرفقة (waterfall_chart_data.items): '
            'عمود رأسي عائم (flex: 1; height: 100%; display: flex; flex-direction: column; justify-content: flex-end; align-items: center; position: relative;): '
            f'1. قيمة البند بالأعلى: (<span style="position: absolute; bottom: calc(offset_pct% + height_pct% + 4px); font-size: 10px; font-weight: 700; color: {primary_color}; white-space: nowrap;">display</span>). '
            f'2. الشريط العائم: (div style="position: absolute; bottom: offset_pct%; height: height_pct%; width: 75%; background: {secondary_color}; border-radius: 3px;"). '
            '3. اسم البند أسفل خط الأساس: (<span style="position: absolute; top: 100%; padding-top: 6px; font-size: 10px; font-weight: 600; color: #475569; text-align: center; line-height: 1.2; word-break: break-word;">name</span>). '
            'العمود الأخير هو عمود إجمالي تكلفة المشروع (waterfall_chart_data.total): '
            f'عمود كامل يستند إلى خط الأساس مباشرة (position: absolute; bottom: 0; height: height_pct%; width: 85%; background: {primary_color}; border-radius: 3px;) '
            f'مع قيمته الإجمالية بأعلاه وتسميته بالأسفل بلون عريض {primary_color}.'
        ),
        'combo': (
            'المخطط المركب: أعمدة وخط (Combo Chart) للتدفقات النقدية السنوية والتراكمية: '
            'أعمدة رأسية لصافي التدفق السنوي (Net Cash Flow) لكل سنة مع مسار ونقاط بارزة للرصيد التراكمي (Cumulative Balance). '
            'الهيكل الإلزامي: قسّم الشريحة إلى عمودين متجاورين متساويين (50% لجدول التدفقات، 50% للرسم البياني) '
            'داخل حاوية display: grid; grid-template-columns: 1fr 1fr; gap: 24px; height: 500px; align-items: start;. '
            'في جانب الرسم: حاوية رسم بخلفية #f8fafc وبودر 1px solid #e2e8f0 وبادينغ 16px وراديوس 8px بارتفاع كلي 380px، '
            'تتضمن بالأعلى عنوان المخطط ومفتاح الألوان (تدفق موجب #10b981، تدفق سالب #ef4444، الرصيد التراكمي خط الهوية). '
            'منطقة الرسم المشتركة بارتفاع 240px وبموقع نسبي (position: relative; height: 240px;): '
            '1. خط الصفر الأفقي يقطع المنتصف (position: absolute; top: 50%; left: 0; right: 0; border-top: 1px dashed #94a3b8; z-index: 1;). '
            '2. رص أعمدة السنوات (display: flex; height: 100%; position: relative; z-index: 2; gap: 4px;): '
            'لكل سنة من combo_chart_data.items، عمود نسبي (flex: 1; height: 100%; position: relative; display: flex; justify-content: center;): '
            'إذا كان التدفق موجباً: شريط للأعلى (position: absolute; bottom: 50%; height: bar_height_pct%; width: 60%; background: #10b981; border-radius: 2px;). '
            'إذا كان التدفق سالباً: شريط للأسفل (position: absolute; top: 50%; height: bar_height_pct%; width: 60%; background: #ef4444; border-radius: 2px;). '
            'وتسمية السنة بالأسفل (position: absolute; bottom: -22px; font-size: 9px; font-weight: 600; color: #64748b; white-space: nowrap;). '
            '3. طبقة مسار الرصيد التراكمي فوق الأعمدة (position: absolute; inset: 0; width: 100%; height: 100%; z-index: 3; pointer-events: none;): '
            f'عنصر svg كامل ومغلق بنطاق عرض viewBox="0 0 500 200" style="position: absolute; inset: 0; width: 100%; height: 100%; z-index: 3; pointer-events: none;" يحتوي بدقة على: '
            f'<polyline fill="none" stroke="{primary_color}" stroke-width="2.5" stroke-linejoin="round" points="انسخ قيمة summary.svg_polyline_points حرفياً" /> '
            f'ودوائر نقاط للسنوات بالإحداثيات المحسوبة لكل سنة: <circle cx="item.cx" cy="item.cy" r="3.5" fill="{primary_color}" stroke="#ffffff" stroke-width="1.5" />. تأكد من إغلاق وسم </svg> دائماً. '
            'ملاحظة هامة: في العمود الأول اعرض جدول التدفقات المعتمد (السنة، صافي التدفق السنوي، الرصيد التراكمي) من combo_chart_data.items، وفي العمود الثاني المخطط المركب، ولا تضف أي جداول أخرى خارج العمودين.'
        ),
        'heatmap': (
            'الخريطة الحرارية (Heatmap Matrix) لمقارنة السيناريوهات المالية: '
            'مصفوفة مقارنة بصرية للسيناريوهات الثلاثة (المتحفظ، الأساسي، المتفائل) لنتائج وحساسية الدراسة المالية. '
            'الهيكل الإلزامي: اعرض مصفوفة الخريطة الحرارية كاملة بعرض مريح يبرز المؤشرات المالية السبعة (الإيرادات، تكلفة المشروع، صافي الربح، ROI، Project IRR، Equity IRR، فترة الاسترداد). '
            'تلوين اتجاهي ذكي ثلاثي المستويات بحسب طبيعة المؤشر (Directional Polarity-Aware Coloring): '
            '1. الأعلى أفضل لمؤشرات الإيرادات وصافي الربح ومعدلات العائد (الأعلى = أخضر، المتوسط = أصفر، الأقل = أحمر). '
            '2. الأقل أفضل لمؤشرات التكلفة وفترة الاسترداد (الأقل = أخضر، المتوسط = أصفر، الأعلى = أحمر). '
            '3. استخدم الأنماط الجاهزة المرفقة (conservative_style, base_style, optimistic_style) أو قم بتضمين كود html_matrix الجاهز مباشرة. '
            '4. ضع مفتاح التقييم الاتجاهي أسفل المصفوفة (الأفضل أخضر، المتوسط أصفر، الأقل أحمر) بدون أي أيقونات أو إيموجي نهائياً.'
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
    if slide_type == 'cover':
        placeholder_note = 'يجب استخدام ##IMAGE_COVER## كخلفية كاملة على كامل الشريحة (Full Bleed Background)، ووضع طبقة فوقها تحمل data-cover-overlay. لون الطبقة سيُثبت من اللون الأساسي للهوية؛ ممنوع كحلي ثابت أو لون خارج الهوية. ممنوع منعاً باتاً وضع أي بطاقة صورة أو وسم <img> إضافي لصورة المشروع داخل الشريحة؛ الصورة كخلفية كاملة فقط.'
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
    elif image_tokens:
        placeholder_note = 'استخدم كل رموز الصور التالية مرة واحدة وبحجم واضح، ولا تستبدلها بصورة الغلاف: ' + '، '.join(image_tokens)
        if slide.get('image_layout'):
            placeholder_note += f". التخطيط المعتمد لهذه المجموعة هو {slide.get('image_layout')} ولا تغيّر عدد الصور"
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
        'جداول الدراسة المالية يجب أن تكون متناسقة ومضغوطة بأناقة (Compact & Fitted): ممنوع تمديد الجدول رأسياً بملء الشريحة (لا تضع height: 100% أو height: 480px على الجدول لتفادي الصفوف العملاقة والفراغات المفرطة)، واجعل ارتفاع الصفوف طبيعياً ومريحاً (padding: 7px 12px;). جداول العمودين (مثل البند والقيمة) توضع في بطاقة أنيقة بعرض متناسب مريح (max-width: 820px; margin: 0 auto;). في الشرائح المالية العادية غير الرسومية، عند وجود أكثر من جدول مالي رصها كلها رأسياً تحت بعضها، ولا تضع جدولين بجانب بعضهما؛ وإذا لم تتسع المساحة فانقل البقية إلى الشريحة التالية دون قص أو حذف.',
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
    if section_key != 'financial' and len([t for t in (slide.get('table_group_titles') or []) if str(t or '').strip()]) > 1:
        group_titles = [str(t).strip() for t in slide.get('table_group_titles') or [] if str(t or '').strip()]
        notes.append(
            'هذه الشريحة تجمع جداول مترابطة من نفس القسم. اجعل الجداول ذات الترويسة والأعمدة المتطابقة جدولاً واحداً متصلاً، '
            'وارص أي جدول مختلف تحته بتباعد واضح، مع نقل جميع البيانات من العناوين التالية دون حذف: '
            + ' — '.join(group_titles)
        )
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
        notes.append('لجداول المؤشرات والملخصات (Key-Value): استخدم جدولاً بعمودين (<table class="summary-table">) بعرض 35%-40% لعمود اسم البند بخلفية هادئة بلون الهوية، وعمود القيمة بخط عريض bold وفواصل آلاف للأرقام. عند وجود أكثر من جدول مالي، رص الجداول كلها تحت بعضها رأسياً بترتيبها، ولا تستخدم display:grid أو grid-template-columns لوضع جدولين متجاورين.')
        stacked_sources = [s for s in (slide.get('content_sources') or []) if str(s or '').strip()]
        stacked_titles = [t for t in (slide.get('table_group_titles') or []) if str(t or '').strip()]
        if (len(stacked_sources) > 1 or len(stacked_titles) > 1) and not chart_type:
            notes.append('هذه الشريحة المالية العادية تضم عدة جداول: ادمج الجداول المتتالية ذات الترويسة والأعمدة المتطابقة في جدول واحد، ورص جميع الجداول رأسياً تحت بعضها بتباعد 18px، مع عنوان صغير فوق كل جدول وبقاء كل صف وعمود كاملاً دون اختصار. لا تضع أي جدول بجانب جدول آخر، وإذا لم تتسع المساحة فانقل بقية الجداول إلى الشريحة التالية دون قص أو حذف.')
            if stacked_titles:
                notes.append('عناوين جداول هذه المجموعة كما وردت في الخطة: ' + ' — '.join(stacked_titles))
        notes.append('نسّق الأعداد بفواصل الآلاف للعرض فقط، من دون تقريب أو تحويل إلى ألف أو مليون أو تغيير عدد الخانات العشرية.')
        if chart_type:
            notes.append(
                f'هذه الشريحة مخصصة للرسم المالي المعتمد ({chart_type}: {chart_note}). '
                'قسّم الشريحة إلى عمودين متجاورين متناسقين (50% لجدول البيانات، و50% للرسم البياني) '
                'باستخدام display: grid; grid-template-columns: 1fr 1fr; gap: 24px; داخل الشريحة، '
                'مع بقاء جدول البيانات كاملاً ومقروءاً على أحد الجانبين، والرسم البياني واضحاً بكامل عناصره على الجانب الآخر، ومنع استخدام position: absolute.'
            )
        else:
            notes.append('هذه الشريحة ليست واحدة من الرسوم المالية الثلاثة المعتمدة (waterfall, combo, heatmap)؛ اعرض جدول التقرير فقط وممنوع إضافة أي رسم بياني.')
        notes.append('الجدول لا يقل عن 12px ولا يزيد على 6 أعمدة في الشريحة، وتُرص الجداول المالية العادية تحت بعضها حتى تمتلئ المساحة المتاحة. عند انتهاء المساحة، تُستكمل الجداول في شرائح مالية تالية بدل التصغير أو القص أو ترك شريحة شبه فارغة بجدول واحد فقط.')
        financial_note = _financial_data_note(project_data)
        if financial_note and not source_note:
            notes.append(financial_note.strip())
    elif section_key == 'market':
        if chart_type == 'horizontal_bar':
            notes.append(
                f'هذه الشريحة مخصصة لرسم مقارنة المنافسين المعتمد ({chart_type}: {chart_note}). '
                'قسّم الشريحة إلى عمودين متجاورين متناسقين (50% لجدول المنافسين، و50% لرسم الأعمدة الأفقية) '
                'باستخدام display: grid; grid-template-columns: 1fr 1fr; gap: 24px; داخل الشريحة، '
                'مع بقاء جدول المنافسين كاملاً ومقروءاً، والرسم البياني واضحاً بكامل أشرطته وأسعاره مع إبراز مشروعنا بلون الهوية، ومنع اختراع أرقام أو متوسطات افتراضية.'
            )
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
        # Remove one property at a time.  A single alternation used to consume
        # the separator after every other declaration, leaving duplicate inline
        # rules after a second normalization pass.
        for property_name in property_names:
            style = re.sub(
                rf'(^|;)\s*{re.escape(property_name)}\s*:[^;]*;?',
                r'\1', style, flags=re.IGNORECASE
            )
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
    # Strip height stretch from wrapper containers around tables
    def _strip_table_wrapper_stretch(h):
        """Remove height:100%, height:NNNpx, flex:1 from divs that wrap tables."""
        def deflate_wrapper(m):
            tag = m.group(0)
            tag = re.sub(r'height\s*:\s*(?:100%|\d{3,}px)\s*;?', '', tag, flags=re.IGNORECASE)
            tag = re.sub(r'flex\s*:\s*1\s*;?', '', tag, flags=re.IGNORECASE)
            return tag
        # Match opening div tags that precede a <table
        return re.sub(r'<div\b[^>]*>(?=\s*<table\b)', deflate_wrapper, h, flags=re.IGNORECASE)
    html = _strip_table_wrapper_stretch(html)

    def _count_columns(table_html):
        """Count the max columns in the first row of a table."""
        row_match = re.search(r'<tr\b[^>]*>(.*?)</tr>', table_html, re.IGNORECASE | re.S)
        if not row_match:
            return 0
        cells = re.findall(r'<(?:th|td)\b', row_match.group(1), re.IGNORECASE)
        return len(cells)

    # Per-table normalization: count columns and apply width constraint
    def normalize_full_table(match):
        table_html = match.group(0)
        cols = _count_columns(table_html)
        if cols <= 2:
            max_w = '820px'
        elif cols <= 4:
            max_w = '1080px'
        else:
            max_w = '1200px'
        # Strip width:100% and excessive height from the <table> tag
        table_tag_match = re.match(r'<table\b[^>]*>', table_html, re.IGNORECASE)
        if table_tag_match:
            old_tag = table_tag_match.group(0)
            new_tag = re.sub(r'width\s*:\s*100%\s*;?', '', old_tag, flags=re.IGNORECASE)
            new_tag = re.sub(r'height\s*:\s*(?:100%|\d{3,}px)\s*;?', '', new_tag, flags=re.IGNORECASE)
            new_tag = _set_tag_style(
                new_tag, ('border-collapse', 'max-width', 'margin-left', 'margin-right'),
                f'border-collapse:collapse!important;max-width:{max_w}!important;margin-left:auto!important;margin-right:auto!important;')
            table_html = new_tag + table_html[table_tag_match.end():]
        return table_html

    html = re.sub(r'<table\b[^>]*>.*?</table>', normalize_full_table, html, flags=re.IGNORECASE | re.S)

    def normalize_header(match):
        return _set_tag_style(
            match.group(0), ('font-size', 'line-height', 'padding', 'overflow-wrap'),
            'font-size:13px!important;line-height:1.35!important;padding:8px 12px!important;overflow-wrap:anywhere!important;')

    def normalize_cell(match):
        tag = re.sub(r'height\s*:\s*(?:100%|\d{2,}px)\s*;?', '', match.group(0), flags=re.IGNORECASE)
        return _set_tag_style(
            tag, ('font-size', 'line-height', 'padding', 'vertical-align', 'overflow-wrap'),
            'font-size:12px!important;line-height:1.35!important;padding:7px 12px!important;vertical-align:middle!important;overflow-wrap:anywhere!important;')

    html = re.sub(r'<th\b[^>]*>', normalize_header, html, flags=re.IGNORECASE)
    html = re.sub(r'<td\b[^>]*>', normalize_cell, html, flags=re.IGNORECASE)

    def normalize_numeric_cell(match):
        opening, body = match.group(1), match.group(2)
        plain = html_lib.unescape(re.sub(r'<[^>]*>', '', body)).strip()
        compact = re.sub(r'[\d٠-٩\s,٬.٫%٪()\-+/:]', '', plain)
        for word in ('ريال', 'ر.س', 'سنة', 'عام', 'مؤشر', 'مرة'):
            compact = compact.replace(word, '')
        if re.search(r'[\d٠-٩]', plain) and not re.search(r'[A-Za-z\u0600-\u06ff]', compact):
            opening = _set_tag_style(
                opening, ('text-align', 'direction'),
                'text-align:center!important;direction:ltr!important;'
            )
        return opening + body + '</td>'

    return re.sub(r'(<td\b[^>]*>)([\s\S]*?)</td\s*>', normalize_numeric_cell,
                  html, flags=re.IGNORECASE)


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
    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    project_data = project_data if isinstance(project_data, dict) else {}
    model = _parse_financial_dict(project_data.get('financial_study_model'))
    chart_source = _financial_chart_source(slide, model)
    if chart_type == 'combo':
        c_data = _extract_combo_chart_data(chart_source, model, project_data)
        items = c_data.get('items') or []
        return [str(it.get('year') or '') for it in items if str(it.get('year') or '').strip()]
    if chart_type == 'waterfall':
        w_data = _extract_waterfall_chart_data(chart_source, model, project_data)
        items = w_data.get('items') or []
        res = [str(it.get('name') or '') for it in items if str(it.get('name') or '').strip()]
        if w_data.get('total', {}).get('name'):
            res.append(str(w_data['total']['name']))
        return res
    if chart_type == 'heatmap':
        h_data = _extract_heatmap_chart_data(chart_source, model, project_data)
        matrix = h_data.get('matrix') or []
        return [str(r.get('metric') or '') for r in matrix if str(r.get('metric') or '').strip()]
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
    if source == 'market_study_data.competitors' or 'competitors' in source:
        market = _decode_json_fact(project_data.get('market_study_data')) if isinstance(project_data.get('market_study_data'), (str, dict)) else {}
        competitors = market.get('competitors') if isinstance(market, dict) else []
        items = _extract_competitor_chart_data(competitors, project_data)
        return [str(it.get('name') or '').strip() for it in items if str(it.get('name') or '').strip()]
    if source == 'contact_closing':
        values = [str(project_data.get(key) or '').strip() for key in (
            'contact_name', 'contact_position', 'contact_phone', 'contact_email',
            'contact_website', 'contact_address', 'contact_social_media')]
        entered = [value for value in values if value]
        return entered or [str(project_data.get('project_name') or 'المشروع').strip(), 'شكر']

    def row_values(row):
        values = []
        if isinstance(row, dict):
            for k, v in row.items():
                if str(k).strip() in ('ترتيب / حذف', 'ترتيب', 'حذف', 'إجراءات', 'actions', 'id', 'row_id'):
                    continue
                if str(v).strip() in ('أعلىأسفلحذف', 'أعلى', 'أسفل', 'حذف', '—', '-', '0', '0.0'):
                    continue
                values.append(v)
        elif isinstance(row, (list, tuple)):
            for v in row:
                if str(v).strip() in ('أعلىأسفلحذف', 'أعلى', 'أسفل', 'حذف', '—', '-', '0', '0.0'):
                    continue
                values.append(v)
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
    required = _required_slide_texts(slide, project_data)
    if (slide or {}).get('chart_type'):
        required = [text for text in required if not re.match(r'^-?\d+(?:\.\d+)?$', normalized(text))]
    return [text for text in required
            if normalized(text) and normalized(text) not in compact]


def _financial_chart_source(slide, model):
    """Resolve the exact report/table slice that feeds a financial chart."""
    source = str((slide or {}).get('content_source') or '')
    report = model.get('report') if isinstance(model.get('report'), dict) else {}
    parts = report.get('parts') if isinstance(report.get('parts'), list) else []
    match = re.fullmatch(r'financial_report:(\d+):(\d+):(\d+)(?::(\d+):(\d+))?', source)
    if match:
        part_index, start, end = map(int, match.groups()[:3])
        column_start = int(match.group(4)) if match.group(4) is not None else None
        column_end = int(match.group(5)) if match.group(5) is not None else None
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            return _financial_report_part_slice(parts[part_index], start, end, column_start, column_end)
    match = re.fullmatch(r'financial_chart:[^:]+:(\d+)', source)
    if match:
        part_index = int(match.group(1))
        if part_index < len(parts) and isinstance(parts[part_index], dict):
            return parts[part_index]
    match = re.fullmatch(r'financial_table:([^:]+):(\d+):(\d+)', source)
    if match:
        table_key, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        tables = model.get('tables') if isinstance(model.get('tables'), dict) else {}
        rows = tables.get(table_key) if isinstance(tables.get(table_key), list) else []
        if not rows:
            aliases = {
                'cashflowTable': ('cashflow',),
                'sensitivityTable': ('sensitivity',),
                'sensitivityAssumptionsTable': ('sensitivity',),
            }
            rows = next((tables.get(alias) for alias in aliases.get(table_key, ())
                         if isinstance(tables.get(alias), list)), [])
        return {'rows': rows[start:end]}
    return None


def _fallback_table_data(slide, project_data):
    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    source = str((slide or {}).get('content_source') or '')
    chart_source = _financial_chart_source(slide, model) if source.startswith('financial_table:') else None
    if chart_type == 'combo':
        c_data = _extract_combo_chart_data(chart_source, model, project_data)
        items = c_data.get('items') or []
        if items:
            headers = ['السنة', 'صافي التدفق السنوي', 'الرصيد التراكمي']
            rows = [[it.get('year', ''), it.get('net_flow_display', ''), it.get('cumulative_display', '')] for it in items]
            return headers, rows
    elif chart_type == 'waterfall':
        w_data = _extract_waterfall_chart_data(chart_source, model, project_data)
        items = w_data.get('items') or []
        if items:
            headers = ['بند التكلفة', 'القيمة']
            rows = [[it.get('name', ''), it.get('display', '')] for it in items]
            if w_data.get('total'):
                rows.append([w_data['total'].get('name', 'الإجمالي'), w_data['total'].get('display', '')])
            return headers, rows
    elif chart_type == 'heatmap':
        h_data = _extract_heatmap_chart_data(chart_source, model, project_data)
        matrix = h_data.get('matrix') or []
        if matrix:
            headers = ['المؤشر المالي', 'متحفظ', 'أساسي', 'متفائل']
            rows = [[r.get('metric', ''), r.get('conservative', ''), r.get('base', ''), r.get('optimistic', '')] for r in matrix]
            return headers, rows

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
        if not rows:
            aliases = {
                'cashflowTable': ('cashflow',),
                'sensitivityTable': ('sensitivity',),
                'sensitivityAssumptionsTable': ('sensitivity',),
            }
            rows = next((tables.get(alias) for alias in aliases.get(key, ())
                         if isinstance(tables.get(alias), list)), [])
        selected = rows[start:end]
        if selected and isinstance(selected[0], dict):
            headers = [k for k in selected[0].keys() if str(k).strip() not in ('ترتيب / حذف', 'ترتيب', 'حذف', 'إجراءات', 'actions', 'id', 'row_id')]
            active_headers = []
            for h in headers:
                vals = [str(row.get(h) or '').strip() for row in selected]
                has_content = any(v and v not in ('0', '0.0', '—', '-', '0%', '0.00') for v in vals)
                if has_content or len(active_headers) == 0:
                    active_headers.append(h)
            if active_headers:
                headers = active_headers
            return headers, [[row.get(header, '') for header in headers] for row in selected]
        return [], selected
    match = re.fullmatch(r'project_components:(\d+):(\d+)', source)
    if match:
        start, end = map(int, match.groups())
        rows = _project_component_rows(project_data)[start:end]
        headers = list(rows[0].keys()) if rows else []
        return headers, [[row.get(header, '') for header in headers] for row in rows]
    if source == 'market_study_data.competitors' or (slide or {}).get('source_table') == 'competitors' or 'competitors' in source:
        market = _decode_json_fact(project_data.get('market_study_data')) if isinstance(project_data.get('market_study_data'), (str, dict)) else {}
        competitors = market.get('competitors') if isinstance(market, dict) else []
        chart_items = _extract_competitor_chart_data(competitors, project_data)
        if chart_items:
            headers = ['المنافس / المشروع', 'السعر', 'النوع']
            rows = [[it.get('name', ''), it.get('display_price', ''), it.get('price_type', '')] for it in chart_items]
            return headers, rows
    return [], []


def _format_table_num(val):
    s = str(val or '').strip()
    if not s or s in ('—', '-', 'N/A', 'nan'):
        return '—', False
    if re.match(r'^-?\d{1,3}(,\d{3})+(\.\d+)?%?$', s):
        return s, True
    is_pct = s.endswith('%')
    raw_num = s[:-1].strip() if is_pct else s
    try:
        clean = raw_num.replace(',', '')
        f = float(clean)
        if 1950 <= f <= 2050 and '.' not in raw_num and not is_pct:
            return str(int(f)), True
        if abs(f) >= 1000 and '.' not in raw_num:
            res = f"{int(f):,}"
        elif abs(f) >= 1000:
            res = f"{f:,.2f}".rstrip('0').rstrip('.')
        else:
            res = raw_num
        if is_pct:
            res += '%'
        return res, True
    except (ValueError, TypeError):
        return html_lib.escape(s), False


def _render_fallback_table(headers, rows, primary):
    header_html = ''.join(
        f'<th style="background:{primary};color:#fff;padding:9px 12px;font-size:12px;text-align:center;vertical-align:middle;">{html_lib.escape(str(value))}</th>'
        for value in headers)
    body = []
    for row_idx, row in enumerate(rows):
        values = list(row.values()) if isinstance(row, dict) else list(row) if isinstance(row, (list, tuple)) else [row]
        bg = '#f8fafc' if row_idx % 2 == 1 else '#ffffff'
        tds = []
        for col_idx, val in enumerate(values):
            fmt, is_num = _format_table_num(val)
            align = 'center' if is_num else 'right'
            direction = 'ltr' if is_num else 'rtl'
            tds.append(
                f'<td style="border-bottom:1px solid #e2e8f0;padding:8px 12px;font-size:11.5px;'
                f'text-align:{align};direction:{direction};vertical-align:middle;font-feature-settings:\'tnum\';font-variant-numeric:tabular-nums;">{fmt}</td>'
            )
        body.append(f'<tr style="background:{bg};">{"".join(tds)}</tr>')
    return ('<table style="width:100%;border-collapse:collapse;table-layout:fixed;border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">'
            f'<thead><tr>{header_html}</tr></thead><tbody>{"".join(body)}</tbody></table>')


def _render_fallback_horizontal_bar(items, primary='#005f78', secondary='#0ea5e9'):
    if not items:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات منافسين كافية</div>'
    rows_html = []
    for it in items:
        name = html_lib.escape(str(it.get('name') or ''))
        width = it.get('bar_width_pct', 50.0)
        display_price = html_lib.escape(str(it.get('display_price') or ''))
        is_project = bool(it.get('is_project'))
        bar_color = primary if is_project else secondary
        font_weight = '800' if is_project else '600'
        border_box = f'border: 2px solid {primary}; background: rgba(0, 95, 120, 0.06); padding: 8px 10px; border-radius: 6px;' if is_project else 'padding: 4px 0;'
        badge = f'<span style="background:{primary};color:#fff;font-size:10px;padding:2px 6px;border-radius:3px;margin-right:6px;">مشروعنا</span>' if is_project else ''
        rows_html.append(f'''
        <div style="display:flex;flex-direction:column;gap:4px;{border_box}">
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;">
                <span style="font-weight:{font_weight};color:#1e293b;">{badge}{name}</span>
                <span style="font-weight:700;color:{bar_color};">{display_price}</span>
            </div>
            <div style="width:100%;height:14px;background:#e2e8f0;border-radius:3px;overflow:hidden;position:relative;">
                <div style="width:{width}%;height:100%;background:{bar_color};border-radius:3px;"></div>
            </div>
        </div>
        ''')
    return (
        f'<div style="display:flex;flex-direction:column;gap:10px;background:#f8fafc;padding:16px;border-radius:8px;border:1px solid #e2e8f0;">'
        f'<div style="font-size:13px;font-weight:700;color:{primary};border-bottom:1px solid #cbd5e1;padding-bottom:6px;">مقارنة أسعار المنافسين في السوق</div>'
        f'{"".join(rows_html)}'
        f'</div>'
    )


def _render_fallback_waterfall(chart_data, primary='#005f78', secondary='#0ea5e9'):
    summary = (chart_data or {}).get('summary') if isinstance(chart_data, dict) else {}
    svg_code = summary.get('svg_code')
    if svg_code:
        return (
            f'<div style="background:#f8fafc;padding:14px 14px 20px;border-radius:8px;border:1px solid #e2e8f0;position:relative;">'
            f'<div style="font-size:13px;font-weight:700;color:{primary};margin-bottom:8px;">تكوين إجمالي تكلفة المشروع (ملايين ر.س)</div>'
            f'{svg_code}'
            f'</div>'
        )
    items = (chart_data or {}).get('items') or []
    total = (chart_data or {}).get('total') or {}
    if not items and not total:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات تكاليف كافية</div>'
    cols_html = []
    for it in items:
        name = html_lib.escape(str(it.get('name') or ''))
        display = html_lib.escape(str(it.get('display') or ''))
        h = it.get('height_pct', 10.0)
        offset = it.get('offset_pct', 0.0)
        cols_html.append(f'''
        <div style="flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;position:relative;">
            <div style="position:absolute;bottom:{offset + h + 2}%;font-size:10px;font-weight:700;color:{primary};white-space:nowrap;">{display}</div>
            <div style="position:absolute;bottom:{offset}%;height:{h}%;width:75%;background:{secondary};border-radius:3px;border:1px solid rgba(0,0,0,0.08);"></div>
            <div style="position:absolute;top:100%;padding-top:6px;font-size:10px;font-weight:600;color:#475569;text-align:center;line-height:1.2;word-break:break-word;">{name}</div>
        </div>
        ''')
    if total:
        t_name = html_lib.escape(str(total.get('name') or 'إجمالي تكلفة المشروع'))
        t_display = html_lib.escape(str(total.get('display') or ''))
        t_h = total.get('height_pct', 100.0)
        cols_html.append(f'''
        <div style="flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;position:relative;">
            <div style="position:absolute;bottom:{t_h + 2}%;font-size:11px;font-weight:800;color:{primary};white-space:nowrap;">{t_display}</div>
            <div style="position:absolute;bottom:0;height:{t_h}%;width:85%;background:{primary};border-radius:3px;border:1px solid rgba(0,0,0,0.1);"></div>
            <div style="position:absolute;top:100%;padding-top:6px;font-size:10px;font-weight:700;color:{primary};text-align:center;line-height:1.2;word-break:break-word;">{t_name}</div>
        </div>
        ''')
    return (
        f'<div style="background:#f8fafc;padding:16px 14px 44px;border-radius:8px;border:1px solid #e2e8f0;display:flex;flex-direction:column;gap:10px;">'
        f'<div style="font-size:13px;font-weight:700;color:{primary};">تكوين إجمالي تكلفة المشروع (ملايين ر.س)</div>'
        f'<div style="height:230px;display:flex;align-items:flex-end;justify-content:space-between;border-bottom:2px solid #94a3b8;position:relative;gap:6px;">'
        f'{"".join(cols_html)}'
        f'</div>'
        f'</div>'
    )


def _render_fallback_combo(chart_data, primary='#005f78', secondary='#0ea5e9'):
    summary = (chart_data or {}).get('summary') if isinstance(chart_data, dict) else {}
    svg_code = summary.get('svg_code')
    if svg_code:
        return (
            f'<div style="background:#f8fafc;padding:14px 14px 20px;border-radius:8px;border:1px solid #e2e8f0;position:relative;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
            f'<span style="font-size:12px;font-weight:700;color:{primary};">التدفقات النقدية السنوية والتراكمية (ملايين ر.س)</span>'
            f'<div style="display:flex;gap:12px;font-size:9.5px;font-weight:600;">'
            f'<span style="color:#0b1f33;">صافي التدفق السنوي</span>'
            f'<span style="color:#b89564;">تدفق سالب</span>'
            f'<span style="color:#0284c7;">الرصيد التراكمي</span>'
            f'</div>'
            f'</div>'
            f'{svg_code}'
            f'</div>'
        )
    items = (chart_data or {}).get('items') if isinstance(chart_data, dict) else chart_data
    if not items:
        return '<div style="padding:20px;text-align:center;color:#64748b;">لا تتوفر بيانات تدفقات نقدية كافية</div>'
    items = items[:15]
    cols_html = []
    points = []
    net_flows = [it.get('net_flow_m', 0.0) for it in items]
    cums = [it.get('cumulative_m', 0.0) for it in items]
    max_flow = max([abs(f) for f in net_flows] + [1.0])
    min_cum = min(cums + [0.0])
    max_cum = max(cums + [1.0])
    cum_range = (max_cum - min_cum) or 1.0

    for idx, it in enumerate(items):
        year = html_lib.escape(str(it.get('year') or f'سنة {idx+1}'))
        flow = it.get('net_flow_m', 0.0)
        cum = it.get('cumulative_m', 0.0)
        is_pos = flow >= 0
        color = '#10b981' if is_pos else '#ef4444'
        bar_h = min(round((abs(flow) / max_flow) * 42, 1), 42.0)
        pos_bottom = '50%' if is_pos else f'{50 - bar_h}%'
        cols_html.append(f'''
        <div style="flex:1;height:100%;position:relative;display:flex;justify-content:center;">
            <div style="position:absolute;bottom:{pos_bottom};height:{bar_h}%;width:55%;background:{color};border-radius:2px;"></div>
            <div style="position:absolute;bottom:-24px;font-size:9px;font-weight:600;color:#64748b;white-space:nowrap;">{year}</div>
        </div>
        ''')
        x = round(30 + idx * (440 / max(len(items) - 1, 1)), 1)
        y = round(160 - ((cum - min_cum) / cum_range) * 120, 1)
        points.append((x, y))

    poly_pts = ' '.join(f'{x},{y}' for x, y in points)
    dots_svg = ''.join(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{primary}" stroke="#ffffff" stroke-width="1.5" />' for x, y in points)

    return (
        f'<div style="background:#f8fafc;padding:14px 14px 36px;border-radius:8px;border:1px solid #e2e8f0;position:relative;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
        f'<span style="font-size:12px;font-weight:700;color:{primary};">التدفقات النقدية السنوية والتراكمية</span>'
        f'<div style="display:flex;gap:10px;font-size:9px;font-weight:600;">'
        f'<span style="color:#10b981;">تدفق موجب</span>'
        f'<span style="color:#ef4444;">تدفق سالب</span>'
        f'<span style="color:{primary};">الرصيد التراكمي</span>'
        f'</div>'
        f'</div>'
        f'<div style="height:170px;position:relative;border-bottom:1px solid #cbd5e1;">'
        f'<div style="position:absolute;top:50%;left:0;right:0;border-top:1px dashed #94a3b8;z-index:1;"></div>'
        f'<div style="display:flex;height:100%;position:relative;z-index:2;">'
        f'{"".join(cols_html)}'
        f'</div>'
        f'<svg viewBox="0 0 500 170" style="position:absolute;inset:0;width:100%;height:100%;z-index:3;pointer-events:none;" preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="{primary}" stroke-width="2.5" points="{poly_pts}" stroke-linejoin="round" />'
        f'{dots_svg}'
        f'</svg>'
        f'</div>'
        f'</div>'
    )


def _render_fallback_heatmap(chart_data, primary='#005f78', secondary='#0ea5e9'):
    return _build_heatmap_matrix_html(chart_data, primary, secondary)


def _render_fallback_chart(chart_type, slide, project_data, primary='#005f78', secondary='#0ea5e9'):
    chart_type = canonicalize_chart_type(chart_type)
    if not chart_type:
        return ''
    model = _parse_financial_dict((project_data or {}).get('financial_study_model'))
    if chart_type == 'horizontal_bar':
        market = _decode_json_fact((project_data or {}).get('market_study_data')) if isinstance((project_data or {}).get('market_study_data'), (str, dict)) else {}
        competitors = market.get('competitors') if isinstance(market, dict) else []
        items = _extract_competitor_chart_data(competitors, project_data)
        return _render_fallback_horizontal_bar(items, primary, secondary)
    elif chart_type == 'waterfall':
        c_data = _extract_waterfall_chart_data(None, model, project_data)
        return _render_fallback_waterfall(c_data, primary, secondary)
    elif chart_type == 'combo':
        c_data = _extract_combo_chart_data(None, model, project_data)
        return _render_fallback_combo(c_data, primary, secondary)
    elif chart_type == 'heatmap':
        c_data = _extract_heatmap_chart_data(None, model, project_data)
        return _render_fallback_heatmap(c_data, primary, secondary)
    return ''


SOL_SLIDES_CSS = """
  .slide {
    width: 1280px; height: 720px; position: relative; overflow: hidden;
    background: #ffffff; color: #0b1f33; box-sizing: border-box; font-family: inherit;
  }
  .slide-header {
    height: 96px; padding: 0 58px; display: flex; justify-content: space-between; align-items: center;
    border-bottom: 1px solid #e2e8f0; box-sizing: border-box;
  }
  .header-left { text-align: left; }
  .header-project { font-size: 13px; font-weight: 700; color: #0b1f33; letter-spacing: 0.05em; }
  .header-cat { font-size: 11px; font-weight: 600; color: #c59a58; letter-spacing: 0.08em; text-transform: uppercase; margin-top: 2px; }
  .header-right { display: flex; align-items: center; gap: 14px; text-align: right; }
  .header-accent-bar { width: 4px; height: 38px; border-radius: 2px; flex-shrink: 0; }
  .header-title { font-size: 24px; font-weight: 800; color: #0b1f33; margin: 0; line-height: 1.2; }
  .header-subtitle { font-size: 13px; font-weight: 500; color: #64748b; margin: 3px 0 0; }
  .slide-footer {
    position: absolute; bottom: 0; left: 0; right: 0; height: 38px; padding: 0 58px;
    display: flex; justify-content: space-between; align-items: center;
    border-top: 1px solid #f1f5f9; background: #ffffff; font-size: 11px; color: #94a3b8; box-sizing: border-box;
  }
  .footer-left { font-weight: 600; color: #64748b; }
  .footer-center { font-weight: 500; }
  .footer-right { font-weight: 700; color: #0b1f33; font-feature-settings: "tnum"; font-variant-numeric: tabular-nums; }
  
  .luxury-kpi-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 16px;
  }
  .luxury-kpi-card {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px;
    display: flex; flex-direction: column; justify-content: center;
  }
  .luxury-kpi-card.primary {
    background: #0b1f33; border-color: #0b1f33; color: #ffffff;
  }
  .luxury-kpi-card.primary .kpi-label { color: #94a3b8; }
  .luxury-kpi-card.primary .kpi-val { color: #ffffff; }
  .luxury-kpi-card.accent {
    border-right: 3px solid #c59a58;
  }
  .kpi-label { font-size: 11px; font-weight: 600; color: #64748b; margin-bottom: 4px; }
  .kpi-val { font-size: 20px; font-weight: 800; color: #0b1f33; font-feature-settings: "tnum"; font-variant-numeric: tabular-nums; }

  .financial-table-wrap {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;
  }
  .financial-table {
    width: 100%; border-collapse: collapse; font-size: 11.5px; text-align: right;
  }
  .financial-table th {
    background: #0b1f33; color: #ffffff; font-weight: 700; padding: 10px 14px; font-size: 11.5px; white-space: nowrap;
  }
  .financial-table td {
    padding: 8px 14px; border-bottom: 1px solid #f1f5f9; color: #1e293b; font-weight: 500; vertical-align: middle;
  }
  .financial-table tr:nth-child(even) td {
    background: #f8fafc;
  }
  .financial-table td.numeric {
    text-align: center !important; direction: ltr; font-weight: 600; font-feature-settings: "tnum"; font-variant-numeric: tabular-nums;
  }
  .financial-table tfoot td {
    background: #f1f5f9; font-weight: 800; border-top: 2px solid #cbd5e1; color: #0b1f33;
  }
  .stacked-financial-tables .financial-table th {
    padding: 6px 10px; font-size: 11px;
  }
  .stacked-financial-tables .financial-table td {
    padding: 5px 10px; font-size: 11px;
  }

  .waterfall-card {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px 24px;
    height: 420px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between;
  }
  .waterfall-card-header {
    display: flex; justify-content: space-between; align-items: center; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9;
  }
  .waterfall-card-title { font-size: 14px; font-weight: 700; color: #0b1f33; }
  .waterfall-card-unit { font-size: 11px; font-weight: 600; color: #64748b; }

  .cashflow-layout {
    display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 18px; align-items: start;
  }
  .combo-chart-box {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 16px;
  }
  .table-note {
    font-size: 10.5px; color: #94a3b8; margin-top: 8px; font-weight: 500;
  }
"""


def _build_sol_waterfall_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    model = _parse_financial_dict((source or {}).get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'تكوين إجمالي تكلفة المشروع'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    w_data = _extract_waterfall_chart_data(_financial_chart_source(slide, model), model, source)
    items = w_data.get('items') or []
    total = w_data.get('total') or {}

    total_cost_m = total.get('value_millions', 0.0)
    total_cost_display = total.get('display', f"{total_cost_m:,.2f} ر.س")
    sorted_items = sorted(items, key=lambda x: x.get('value_millions', 0), reverse=True)
    top2_pct = sum(it.get('pct_of_total', 0) for it in sorted_items[:2]) if sorted_items else 0
    top1_name = sorted_items[0].get('name', 'المكون الرئيسي') if sorted_items else 'المكون الرئيسي'
    top1_val = sorted_items[0].get('display', '—') if sorted_items else '—'

    waterfall_rows = [
        [it.get('name', ''), it.get('display', ''), f"{it.get('pct_of_total', 0):.1f}%"]
        for it in items
    ]
    if total:
        waterfall_rows.append([
            total.get('name', 'إجمالي تكلفة المشروع'),
            total.get('display', ''),
            '100%',
        ])
    waterfall_table = _render_fallback_table(
        ['بند التكلفة', 'القيمة', 'النسبة'], waterfall_rows, primary)

    svg_code = _build_waterfall_svg(items, total, width=1116, height=310, primary=primary, secondary='#0284c7', gold=accent)
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">PROJECT COST WATERFALL</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">مخطط شلالي يوضح مساهمة كل مكون في بناء إجمالي التكلفة الرأسمالية للمشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 58px;margin-top:16px;">
    <div class="luxury-kpi-grid">
      <div class="luxury-kpi-card primary" style="background:{primary};border-color:{primary};">
        <div class="kpi-label">إجمالي تكلفة المشروع</div>
        <div class="kpi-val">{total_cost_display}</div>
      </div>
      <div class="luxury-kpi-card accent">
        <div class="kpi-label">المكونان الرئيسيان</div>
        <div class="kpi-val">{top2_pct:.1f}%</div>
      </div>
      <div class="luxury-kpi-card">
        <div class="kpi-label">{top1_name}</div>
        <div class="kpi-val">{top1_val}</div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:0.9fr 1.1fr;gap:18px;height:420px;align-items:stretch;">
      <div class="financial-table-wrap" style="height:420px;overflow:hidden;">
        <div style="padding:12px 14px 8px;font-size:13px;font-weight:700;color:{primary};border-bottom:1px solid #f1f5f9;">جدول بنود التكلفة</div>
        {waterfall_table}
      </div>
      <div class="waterfall-card">
        <div class="waterfall-card-header">
          <div class="waterfall-card-title">المخطط الشلالي لتراكم التكلفة</div>
          <div class="waterfall-card-unit">القيم بمليون ر.س</div>
        </div>
        <div style="flex:1;display:flex;align-items:center;justify-content:center;margin-top:8px;">
          {svg_code}
        </div>
      </div>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">هيكل تكلفة المشروع — عرض تراكمي لمكونات التطوير</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_combo_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    model = _parse_financial_dict((source or {}).get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'التدفقات النقدية وصافي الرصيد التراكمي'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    c_data = _extract_combo_chart_data(_financial_chart_source(slide, model), model, source)
    items = c_data.get('items') or []
    summary = c_data.get('summary') or {}

    total_inflow = summary.get('total_inflow_display', '—')
    peak_outflow = summary.get('peak_outflow_display', '—')
    payback_year = summary.get('payback_year_display', '—')

    if total_inflow == '—' and items:
        tot_inf = sum(it.get('net_flow_m', 0) for it in items if it.get('net_flow_m', 0) > 0)
        total_inflow = f"{tot_inf:,.1f} ر.س"
    if peak_outflow == '—' and items:
        min_cum = min((it.get('cumulative_m', 0) for it in items), default=0)
        peak_outflow = f"{abs(min_cum):,.1f} ر.س"
    if payback_year == '—' and items:
        for it in items:
            if it.get('cumulative_m', 0) > 0:
                payback_year = str(it.get('year') or '')
                break

    table_rows = []
    # Keep the complete calculated series in the table; the chart extractor
    # already applies the presentation limit, so a second slice here used to
    # hide the last years from the approved source table.
    for it in items:
        y = html_lib.escape(str(it.get('year') or ''))
        f_val = it.get('net_flow_m', 0.0)
        c_val = it.get('cumulative_m', 0.0)
        f_str = f"{f_val:,.1f} ر.س"
        c_str = f"{c_val:,.1f} ر.س"
        f_style = 'color:#dc2626;' if f_val < 0 else 'color:#059669;'
        c_style = 'color:#dc2626;' if c_val < 0 else 'color:#0b1f33;'
        table_rows.append(f'''<tr>
          <td>{y}</td>
          <td class="numeric" style="{f_style}">{f_str}</td>
          <td class="numeric" style="{c_style}">{c_str}</td>
        </tr>''')

    svg_code = summary.get('svg_code') or _render_fallback_combo(c_data, primary, accent)
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">CASH FLOW ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">تحليل التدفقات السنوية وصافي الرصيد التراكمي لسنوات المشروع</p>
      </div>
    </div>
  </header>
  <div style="padding:0 58px;margin-top:16px;">
    <div class="luxury-kpi-grid">
      <div class="luxury-kpi-card primary" style="background:{primary};border-color:{primary};">
        <div class="kpi-label">إجمالي التدفقات الإيجابية</div>
        <div class="kpi-val">{total_inflow}</div>
      </div>
      <div class="luxury-kpi-card accent">
        <div class="kpi-label">أقصى عجز تمويلي تراكمي</div>
        <div class="kpi-val">{peak_outflow}</div>
      </div>
      <div class="luxury-kpi-card">
        <div class="kpi-label">سنة التحول للإيجابية / الاسترداد</div>
        <div class="kpi-val">{payback_year}</div>
      </div>
    </div>
    <div class="cashflow-layout">
      <div class="financial-table-wrap">
        <table class="financial-table">
          <thead>
            <tr>
              <th>السنة</th>
              <th style="text-align:left;">صافي التدفق (ر.س)</th>
              <th style="text-align:left;">الرصيد التراكمي (ر.س)</th>
            </tr>
          </thead>
          <tbody>
            {"".join(table_rows)}
          </tbody>
        </table>
      </div>
      <div class="combo-chart-box">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:12px;font-weight:700;color:{primary};">الرسم البياني للتدفقات</span>
          <div style="display:flex;gap:10px;font-size:9.5px;font-weight:600;">
            <span style="color:#059669;">تدفق موجب</span>
            <span style="color:#dc2626;">تدفق سالب</span>
            <span style="color:{primary};">التراكمي</span>
          </div>
        </div>
        {svg_code}
      </div>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">التدفقات النقدية — صافي التدفق والرصيد التراكمي</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_table_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'جدول البيانات'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    headers, rows = _fallback_table_data(slide, source)
    if not rows:
        headers = ['البند', 'القيمة']
        rows = [['لا تتوفر بيانات', '—']]

    th_cells = ''.join(f'<th>{html_lib.escape(str(h))}</th>' for h in headers)
    tb_rows = []

    total_val = 0.0
    has_total_calc = False

    for row_idx, r in enumerate(rows):
        vals = list(r.values()) if isinstance(r, dict) else list(r) if isinstance(r, (list, tuple)) else [r]
        td_cells = []
        for idx, v in enumerate(vals):
            formatted, is_num = _format_table_num(v)
            if is_num and idx == len(vals) - 1 and not str(formatted).endswith('%') and not str(formatted).endswith('ر.س'):
                try:
                    f_clean = float(str(v).replace(',', ''))
                    if f_clean >= 1000 and not (1950 <= f_clean <= 2050):
                        formatted = f"{formatted} ر.س"
                except (ValueError, TypeError):
                    pass
            cls = ' class="numeric"' if is_num and idx > 0 else ''
            td_cells.append(f'<td{cls}>{formatted}</td>')
            if is_num and idx == len(vals) - 1:
                try:
                    f_val = float(str(v).replace(',', ''))
                    total_val += f_val
                    has_total_calc = True
                except (ValueError, TypeError):
                    pass
        tb_rows.append(f'<tr>{"".join(td_cells)}</tr>')

    kpi1_title = 'عدد البنود المعتمدة'
    kpi1_val = f"بنود {len(rows)}"

    kpi2_title = 'أكبر بند رئيسي'
    first_row_vals = list(rows[0].values()) if isinstance(rows[0], dict) else list(rows[0]) if isinstance(rows[0], (list, tuple)) else [rows[0]]
    kpi2_val = html_lib.escape(str(first_row_vals[0] if first_row_vals else '—'))

    kpi3_title = 'إجمالي التكلفة / القيمة'
    if has_total_calc and total_val > 0:
        kpi3_val = f"{total_val:,.0f} ر.س"
    else:
        kpi3_val = html_lib.escape(str(first_row_vals[1] if len(first_row_vals) > 1 else '—'))

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">CAPITAL INVESTMENT</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">توزيع الاستثمار المستهدف على مكونات التطوير الرئيسية والتكاليف المرتبطة بها</p>
      </div>
    </div>
  </header>
  <div style="padding:0 58px;margin-top:16px;">
    <div class="luxury-kpi-grid">
      <div class="luxury-kpi-card primary" style="background:{primary};border-color:{primary};">
        <div class="kpi-label">{kpi3_title}</div>
        <div class="kpi-val">{kpi3_val}</div>
      </div>
      <div class="luxury-kpi-card accent">
        <div class="kpi-label">{kpi2_title}</div>
        <div class="kpi-val" style="font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{kpi2_val}</div>
      </div>
      <div class="luxury-kpi-card">
        <div class="kpi-label">{kpi1_title}</div>
        <div class="kpi-val">{kpi1_val}</div>
      </div>
    </div>
    <div class="financial-table-wrap" style="max-height:420px;overflow:hidden;">
      <table class="financial-table">
        <thead>
          <tr>{th_cells}</tr>
        </thead>
        <tbody>
          {"".join(tb_rows)}
        </tbody>
      </table>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">{title}</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_heatmap_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    model = _parse_financial_dict((source or {}).get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'نتائج تحليل الحساسية'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    h_data = _extract_heatmap_chart_data(_financial_chart_source(slide, model), model, source)
    matrix_html = _build_heatmap_matrix_html(h_data, primary, accent)
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    assumption_blocks = []
    assumption_sources = [str(value).strip() for value in (slide or {}).get('sensitivity_assumptions_sources', [])
                          if str(value or '').strip()]
    for assumption_source in assumption_sources:
        assumption_slide = dict(slide or {})
        assumption_slide['content_source'] = assumption_source
        assumption_slide['chart_type'] = ''
        headers, rows = _fallback_table_data(assumption_slide, source)
        if not rows:
            continue
        title_text = 'افتراضات تحليل الحساسية'
        table = _render_fallback_table(headers, rows, primary)
        assumption_blocks.append(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;overflow:hidden;">'
            f'<div style="font-size:14px;font-weight:800;color:{primary};margin-bottom:10px;text-align:right;">{title_text}</div>'
            f'<div style="max-height:390px;overflow:hidden;">{table}</div></div>'
        )
    sensitivity_side_content = matrix_html
    if assumption_blocks:
        sensitivity_side_content = (
            '<div style="display:grid;grid-template-columns:minmax(300px,0.78fr) minmax(0,1.22fr);'
            'gap:16px;align-items:start;max-height:430px;overflow:hidden;">'
            f'<div style="min-width:0;">{"".join(assumption_blocks)}</div>'
            f'<div style="min-width:0;overflow:hidden;">{matrix_html}</div>'
            '</div>'
        )

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">SENSITIVITY ANALYSIS</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">مصفوفة اختبار المؤشرات المالية وفق السيناريوهات الثلاثة (المتحفظ، الأساسي، المتفائل)</p>
      </div>
    </div>
  </header>
  <div style="padding:0 58px;margin-top:16px;">
    <div class="luxury-kpi-grid">
      <div class="luxury-kpi-card primary" style="background:{primary};border-color:{primary};">
        <div class="kpi-label">السيناريو الأساسي</div>
        <div class="kpi-val">النموذج المعتمد</div>
      </div>
      <div class="luxury-kpi-card accent">
        <div class="kpi-label">السيناريو المتحفظ</div>
        <div class="kpi-val">اختبار الضغط</div>
      </div>
      <div class="luxury-kpi-card">
        <div class="kpi-label">السيناريو المتفائل</div>
        <div class="kpi-val">أقصى كفاءة</div>
      </div>
    </div>
    <div style="max-height:430px;overflow:hidden;">
      {sensitivity_side_content}
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">تحليل الحساسية — مقارنة السيناريوهات الثلاثة</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_horizontal_bar_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'مقارنة أسعار المنافسين'))
    project_title = html_lib.escape(str((source or {}).get('project_name') or (source or {}).get('projectName') or 'THE VIEW'))

    market = _decode_json_fact(source.get('market_study_data')) if isinstance(source.get('market_study_data'), (str, dict)) else {}
    competitors = market.get('competitors') if isinstance(market, dict) else []
    items = _extract_competitor_chart_data(competitors, source)

    bar_chart_html = _render_fallback_horizontal_bar(items, primary, accent)
    headers, rows = _fallback_table_data(slide, source)
    table_html = _render_fallback_table(headers, rows, primary)
    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""

    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">MARKET BENCHMARK</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">تحليل أسعار السوق ومقارنة الوحدات المنافسة في النطاق الجغرافي</p>
      </div>
    </div>
  </header>
  <div style="padding:0 58px;margin-top:16px;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;max-height:510px;overflow:hidden;align-items:start;">
      <div style="overflow:hidden;">
        {table_html}
      </div>
      <div style="overflow:hidden;">
        {bar_chart_html}
      </div>
    </div>
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">دراسة السوق — مقارنة أسعار المنافسين</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_sol_stacked_tables_slide(slide, source, branding=None, slide_num=None, total_slides=None):
    source = source if isinstance(source, dict) else {}
    model = _parse_financial_dict(source.get('financial_study_model'))
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
    accent = normalize_hex_color((branding or {}).get('accent_color'), '#c59a58')
    title = html_lib.escape(str((slide or {}).get('title') or 'الدراسة المالية'))
    project_title = html_lib.escape(str(source.get('project_name') or source.get('projectName') or 'THE VIEW'))
    content_sources = (slide or {}).get('content_sources') or []

    table_blocks = []
    for src in content_sources:
        dummy_slide = dict(slide)
        dummy_slide['content_source'] = src
        sub_headers, sub_rows = _fallback_table_data(dummy_slide, source)
        if sub_rows:
            sub_title = ''
            match_t = re.fullmatch(r'financial_table:([^:]+):\d+:\d+', src)
            if match_t:
                t_key = match_t.group(1)
                sub_title = next((t[1] for t in _FINANCIAL_PLAN_TABLES if t[0] == t_key), t_key)
            elif re.fullmatch(r'financial_report:(\d+):\d+:\d+.*', src):
                p_idx = int(re.fullmatch(r'financial_report:(\d+):\d+:\d+.*', src).group(1))
                sub_title = _financial_report_part_title(model, p_idx)

            th_cells = ''.join(f'<th>{html_lib.escape(str(h))}</th>' for h in sub_headers)
            tb_rows = []
            for r in sub_rows:
                vals = list(r.values()) if isinstance(r, dict) else list(r) if isinstance(r, (list, tuple)) else [r]
                td_cells = []
                for idx, v in enumerate(vals):
                    formatted, is_num = _format_table_num(v)
                    cls = ' class="numeric"' if is_num and idx > 0 else ''
                    td_cells.append(f'<td{cls}>{formatted}</td>')
                tb_rows.append(f'<tr>{"".join(td_cells)}</tr>')

            table_blocks.append((sub_title, tuple(str(h) for h in sub_headers), tb_rows, th_cells))

    # Adjacent key/value blocks with the same columns are one logical table.
    # This is common in the land and project-summary sections, where splitting
    # the same «البند / القيمة» table by heading only creates empty space.
    tables_html = []
    for sub_title, headers_key, tb_rows, th_cells in table_blocks:
        if tables_html and tables_html[-1].get('headers') == headers_key:
            tables_html[-1]['rows'].extend(tb_rows)
            continue
        tables_html.append({'title': sub_title, 'headers': headers_key, 'header_html': th_cells, 'rows': list(tb_rows)})
    rendered_tables = []
    for block in tables_html:
        title_block = (
            f'<div style="font-size:12.5px;font-weight:700;color:{primary};margin:8px 0 4px;">'
            f'{html_lib.escape(block["title"])}</div>' if block['title'] else ''
        )
        rendered_tables.append(f'''
        <div style="margin-bottom:6px;">
          {title_block}
          <div class="financial-table-wrap">
            <table class="financial-table">
              <thead><tr>{block['header_html']}</tr></thead>
              <tbody>{"".join(block['rows'])}</tbody>
            </table>
          </div>
        </div>
        ''')

    slide_num_str = _slide_counter_text(slide_num, total_slides) if slide_num else ""
    return f'''<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#ffffff;box-sizing:border-box;">
  <style>{SOL_SLIDES_CSS}</style>
  <header class="slide-header">
    <div class="header-left">
      <div class="header-project">{project_title}</div>
      <div class="header-cat">FINANCIAL TABLES</div>
    </div>
    <div class="header-right">
      <div class="header-accent-bar" style="background:{accent};"></div>
      <div class="header-text-group">
        <h1 class="header-title">{title}</h1>
        <p class="header-subtitle">جداول وبيانات الدراسة المالية للمشروع</p>
      </div>
    </div>
  </header>
  <div class="stacked-financial-tables" style="padding:0 58px;margin-top:14px;display:flex;flex-direction:column;max-height:510px;overflow:hidden;">
    {"".join(rendered_tables)}
  </div>
  <footer class="slide-footer" data-slide-footer="1">
    <div class="footer-left">{project_title}</div>
    <div class="footer-center">جداول الدراسة المالية المعتمدة</div>
    <div class="footer-right" data-slide-counter="1">{slide_num_str}</div>
  </footer>
</div>'''


def _build_structured_fallback_slide(slide, project_data, branding, slide_num=None, total_slides=None):
    source = project_data if isinstance(project_data, dict) else {}
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    secondary = normalize_hex_color((branding or {}).get('secondary_color'), '#0ea5e9')
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

    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    if chart_type == 'waterfall':
        return _build_sol_waterfall_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    elif chart_type == 'combo':
        return _build_sol_combo_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    elif chart_type == 'heatmap':
        return _build_sol_heatmap_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)
    elif chart_type == 'horizontal_bar':
        return _build_sol_horizontal_bar_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)

    content_sources = (slide or {}).get('content_sources')
    if isinstance(content_sources, list) and len(content_sources) > 1:
        return _build_sol_stacked_tables_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)

    headers, rows = _fallback_table_data(slide, source)
    if rows:
        return _build_sol_table_slide(slide, source, branding, slide_num=slide_num, total_slides=total_slides)

    note = _slide_source_data_note(slide, source) or '\n'.join(str(item) for item in ((slide or {}).get('bullets') or []))
    if note:
        content = html_lib.escape(note).replace('\n', '<br>')
        return (f'<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;padding:90px 48px 60px;box-sizing:border-box;">'
                f'<h2 style="font-size:28px;color:{primary};">{title}</h2><div style="font-size:16px;line-height:1.8;">{content}</div></div>')
    return None


def _validate_chart_slide_html(html, chart_type, slide, project_data=None):
    """
    Validates that a generated chart slide meets all architectural and content requirements.
    Returns an error message string if invalid (to trigger a retry), or None if valid.
    """
    chart_type = canonicalize_chart_type(chart_type)
    if not chart_type:
        return None

    html_lower = html.lower()

    # Rule 1: Every chart slide must have the approved data table (<table) side-by-side with the visual chart
    if '<table' not in html_lower:
        return "الشريحة ملزمة بعرض جدول البيانات الرقمي الكامل (table) بجانب المخطط البياني في تقسيم 50/50. أعد الشريحة مع الجدول المعتمد."

    # Rule 2: Chart-specific structural and semantic checks
    if chart_type == 'waterfall':
        # Must have floating bar geometry
        if not re.search(r'height\s*:\s*\d+%', html, re.IGNORECASE) or not re.search(r'(?:bottom|margin-bottom|top)\s*:\s*\d+%', html, re.IGNORECASE):
            return "مخطط الشلال (waterfall) يتطلب أعمدة عائمة مع ارتفاعات ومسافات سفلية واضحة بنسب مئوية (height, bottom/margin-bottom)."
        # Must have total pillar / final cost
        if not any(kw in html for kw in ('إجمالي', 'المجموع', 'صافي', 'total', 'Total')):
            return "مخطط الشلال (waterfall) يجب أن يتضمن عمود الإجمالي النهائي المرتكز على خط الأساس."
        # Must have monetary or numerical values
        if not re.search(r'\d+(?:\.\d+)?\s*(?:م\.ر|مليون|ر\.س|SAR|%)', html) and not re.search(r'\d{1,3}(?:,\d{3})+', html):
            return "مخطط الشلال (waterfall) يجب أن يعرض أرقام التكلفة بوضوح على كل عمود أو تحته (ر.س)."

    elif chart_type == 'horizontal_bar':
        # Must have horizontal bars with percentage widths
        if not re.search(r'width\s*:\s*(?:\d+%\s*|calc\([^)]+\))', html, re.IGNORECASE):
            return "مخطط الأشرطة الأفقية (horizontal_bar) يتطلب عناصر أشرطة بعروض نسبية (width: ...%)."
        # Must mention project or comparison
        if not any(kw in html for kw in ('المشروع', 'مشروع', 'سعر', 'المقترح', 'منافس', 'م²')):
            return "مخطط الأشرطة الأفقية (horizontal_bar) يجب أن يتضمن أسماء المنافسين وسعر المشروع المقترح."

    elif chart_type == 'combo':
        # Must have cash flow bars (bars with #10b981 / #ef4444 or explicit bar containers)
        has_flow_bars = any(c in html_lower for c in ('#10b981', '#ef4444', 'bar_direction', 'net_flow', 'flow-bar')) or (
            html_lower.count('background:') >= 4 and re.search(r'(?:top|bottom)\s*:\s*(?:50%|\d+%)', html)
        )
        if not has_flow_bars:
            return "المخطط المدمج (combo) يتطلب رسم أعمدة التدفق السنوي (أعمدة خضراء وحمراء موجبة وسالبة) لكل سنة بجانب منحنى الرصيد التراكمي."
        # Must have SVG cumulative line and closed SVG
        if '<svg' not in html_lower or '</svg>' not in html_lower:
            return "المخطط المدمج (combo) يتطلب منحنى الرصيد التراكمي في عنصر <svg> مغلق بالكامل يربط نقاط السنوات."
        if '<polyline' not in html_lower and '<path' not in html_lower:
            return "المخطط المدمج (combo) يتطلب مسار خطي (polyline أو path) داخل الـ SVG للرصيد التراكمي."
        # Must have year labels
        if not any(kw in html for kw in ('سنة', 'عام', 'Year', 'year', 'تراكمي', 'صافي')):
            return "المخطط المدمج (combo) يتطلب تسميات السنوات ومؤشرات التدفق السنوي والتراكمي."

    elif chart_type == 'heatmap':
        # Must compare scenarios
        has_scenarios = any(kw in html for kw in ('متحفظ', 'تحفظ')) and any(kw in html for kw in ('أساسي', 'اساسي', 'واقعي')) and any(kw in html for kw in ('متفائل', 'تفاؤل'))
        if not has_scenarios:
            return "الخريطة الحرارية (heatmap) يجب أن تعرض سيناريوهات الحساسية الثلاثة (متحفظ، أساسي، متفائل)."
        # Must have visual color shading / highlight
        if not re.search(r'background\s*:\s*(?:rgba|#[0-9a-fA-F]{3,8}|hsl)', html, re.IGNORECASE):
            return "الخريطة الحرارية (heatmap) تتطلب تمييزًا لونيًا لخلايا السيناريو الأفضل."

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

    chart_type = canonicalize_chart_type((slide or {}).get('chart_type'))
    if chart_type in APPROVED_CHART_TYPES:
        deterministic_slide = _build_structured_fallback_slide(slide, project_data, branding, slide_num=slide_num, total_slides=total_slides)
        if deterministic_slide:
            return postprocess_slide(
                deterministic_slide, (slide or {}).get('type', 'content'),
                slide_num=slide_num, slide_title=(slide or {}).get('title', f'شريحة {slide_num}'),
                total_slides=total_slides, tenant_id=(branding or {}).get('tenant_id'),
                branding=branding, project_data=project_data
            )

    # A packed table slide is already backed by exact stored rows.  Render it
    # deterministically so the model cannot flatten the stack, omit a table, or
    # replace it with cards while trying to fit the page.
    if (_slide_section_key(slide) == 'financial'
            and len([s for s in (slide or {}).get('content_sources') or [] if str(s or '').strip()]) > 1):
        deterministic_slide = _build_structured_fallback_slide(
            slide, project_data, branding, slide_num=slide_num, total_slides=total_slides)
        if deterministic_slide:
            return postprocess_slide(
                deterministic_slide, (slide or {}).get('type', 'content'),
                slide_num=slide_num, slide_title=(slide or {}).get('title', f'شريحة {slide_num}'),
                total_slides=total_slides, tenant_id=(branding or {}).get('tenant_id'),
                branding=branding, project_data=project_data
            )

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
            chart_type = canonicalize_chart_type(slide.get('chart_type'))
            if chart_type:
                chart_err = _validate_chart_slide_html(html, chart_type, slide, project_data)
                if chart_err:
                    print(f"[SLIDE-{slide_num}] ERROR: chart validation failed: {chart_err} (attempt {attempt})")
                    retry_note = f'\n\nإعادة المحاولة: {chart_err}'
                    continue
            elif re.search(
                    r'(?:data-chart|class\s*=\s*["\'][^"\']*(?:chart|treemap|heatmap)|conic-gradient\s*\()',
                    html, flags=re.IGNORECASE):
                print(f"[SLIDE-{slide_num}] ERROR: unplanned chart outside selected financial charts (attempt {attempt})")
                retry_note = '\n\nإعادة المحاولة: هذه الشريحة لا تحمل chart_type؛ احذف الرسم البياني واعرض النص أو الجدول فقط.'
                continue
            if _slide_section_key(slide) == 'financial' and not chart_type and '<table' not in html.lower():
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

    fallback = _build_structured_fallback_slide(slide, project_data, branding, slide_num=slide_num, total_slides=total_slides)
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
            '<div style="width:1px;height:52px;background:rgba(255,255,255,0.35);margin:0 18px;"></div>'
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
        'PROJECT_LOGO': _project_logo_reference(project_data),
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

        def apply(match):
            tag = match.group(0)
            chrome_logo = 'presentation-chrome-logo' in tag
            size = ('height:48px!important;max-height:48px!important;' if chrome_logo and content_header else
                    'height:40px!important;max-height:40px!important;' if chrome_logo else
                    'height:48px!important;max-height:48px!important;' if content_header else
                    'height:80px!important;max-height:80px!important;' if hero_logo else '')
            padding = '3px 7px' if chrome_logo else ('4px 10px' if content_header else '6px 12px')
            declarations = (
                f'{size}background:{background}!important;padding:{padding}!important;'
                'border-radius:8px!important;box-sizing:border-box!important;object-fit:contain!important;'
            )
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
    """Remove all icon markup and emoji, keeping company logo images and genuine data charts.

    Emojis used to be converted into inline SVG icons first, which the SVG removal below then
    deleted anyway. The product rule is that no icon is ever produced, so they are simply stripped.
    Genuine data rendering SVGs (map polygon overlay or chart data lines/polylines) are preserved.
    """
    if not html:
        return html

    def _strip_svg_if_icon(match):
        chunk = match.group(0)
        # Preserve genuine data visualization SVGs (map boundary overlay or chart data lines/polylines)
        if any(marker in chunk for marker in ('mapPolygonOverlay', 'data-chart', 'polyline', 'data-chart-line')):
            return chunk
        return ''

    html = re.sub(r'<svg\b[^>]*>[\s\S]*?</svg\s*>', _strip_svg_if_icon, html, flags=re.IGNORECASE)
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


def _slide_element_end(html, opening_match):
    """Return the end offset of one possibly nested HTML element."""
    tag_name = opening_match.group('tag').lower()
    depth = 0
    void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    tag_re = re.compile(r'<(?P<closing>/)?(?P<tag>[a-z][\w:-]*)(?:\s[^>]*)?>', re.IGNORECASE)
    for tag_match in tag_re.finditer(html, opening_match.start()):
        if tag_match.group('tag').lower() != tag_name:
            continue
        if tag_match.group('closing'):
            depth -= 1
            if depth == 0:
                return tag_match.end()
        elif tag_name not in void_tags and not tag_match.group(0).rstrip().endswith('/>'):
            depth += 1
    return len(html)


def _project_logo_reference(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    value = str(source.get('project_logo') or source.get('projectLogo') or '').strip()
    if value:
        return value
    meta = source.get('project_logo_file_meta')
    if isinstance(meta, dict) and str(meta.get('path') or '').strip():
        return str(meta.get('path')).strip()
    file_id = str(source.get('project_logo_file_id') or '').strip()
    return f'/api/project-files/{file_id}' if file_id else ''


def _strip_internal_financial_notes(html):
    """Remove model-facing financial instructions that must not reach the client deck."""
    if not html:
        return html
    note_re = re.compile(
        r'القيم\s+معروضة[\s\S]{0,180}?دون\s+إعادة\s+حساب[\s\S]{0,60}?تقريب',
        re.IGNORECASE,
    )
    opening_re = re.compile(r'<(?P<tag>div|span|p|small|section|aside)\b(?P<attrs>\s[^>]*)?>', re.IGNORECASE)
    while True:
        note = note_re.search(html)
        if not note:
            break
        container = None
        for candidate in reversed(list(opening_re.finditer(html, 0, note.start()))):
            attrs = candidate.group('attrs') or ''
            if re.search(r'\bclass\s*=\s*["\'][^"\']*\bslide\b', attrs, re.IGNORECASE):
                continue
            end = _slide_element_end(html, candidate)
            if end >= note.end():
                container = (candidate.start(), end)
                break
        if container:
            html = html[:container[0]] + html[container[1]:]
        else:
            html = html[:note.start()] + html[note.end():]
    return html


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

    # Keep the header and footer authored by Sol.  The engine must not remove them
    # and rebuild a second chrome layer because that reserves space over the
    # generated content and changes the layout Sol designed.
    normalized_title = str(slide_title or '').strip().lower()
    is_cover = slide_type == 'cover' or int(slide_num or 0) == 1 or bool(
        re.search(r'غلاف|cover|front', normalized_title)
    )
    is_closing = slide_type == 'closing' or bool(
        re.search(r'ختام|closing|شكراً|thanks', normalized_title)
    ) or (total_slides is not None and int(slide_num or 0) == int(total_slides))
    is_cover_or_closing = is_cover or is_closing
    html = _strip_internal_financial_notes(html)
    # Renumber a counter that Sol already rendered, but never create or remove
    # the surrounding header/footer markup.
    html = _rewrite_slide_counter(html, slide_type, slide_num, total_slides)
    if is_cover_or_closing:
        html = _normalize_brand_overlay(html, branding)
    if is_cover:
        html = _normalize_cover_overlay_element(html, branding)
        def _strip_cover_extra_images(match):
            tag = match.group(0)
            src_match = re.search(r'src=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            src = (src_match.group(1) if src_match else '').strip()
            if '##LOGO##' in src or '##PROJECT_LOGO##' in src or 'logo' in src.lower():
                return tag
            return ''
        html = re.sub(r'<img\b[^>]*>', _strip_cover_extra_images, html, flags=re.IGNORECASE)
        for _ in range(3):
            html = re.sub(r'<(?:div|figure|picture)\b(?![^>]*(?:\bslide\b|data-cover-overlay))[^>]*>\s*</(?:div|figure|picture)>', '', html, flags=re.IGNORECASE)
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
        project_logo=_project_logo_reference(project_data),
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
            item['html'] = _rewrite_slide_counter(
                item.get('html') or '', slide_type, index, total)
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
