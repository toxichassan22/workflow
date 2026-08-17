"""
Slide Engine: Dynamic slide count & content distribution.
AI analyzes project data and proposes a balanced slide plan.
"""

import json
import os
import re
import concurrent.futures
from design_templates import build_design_rules, extract_slide_elements
import db
# emoji_icons is intentionally not imported: it converted emojis into inline SVG icons, which the
# icon stripper then removed. The product rule is that no icon is ever generated.

_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')

# ─────────────────────────────────────────────────────────────────────────────
# Content Distribution Rules
# ─────────────────────────────────────────────────────────────────────────────

CONTENT_DISTRIBUTION_RULES = """
## قواعد توزيع المحتوى (إلزامية — اتبعها بدقة)
1. **التوازن البصري:** كل شريحة يجب أن تكون ممتلئة بصرياً بنسبة 60-85%
2. **الحد الأدنى للمحتوى:** كل شريحة محتوى يجب أن تحتوي على:
   - عنوان واضح
   - 3-6 نقاط أساسية (bullets) أو 2-4 بطاقات (cards) أو 3-5 أرقام (metrics)
   - ممنوع تماماً شريحة بكلمة أو كلمتين فقط (فارغة بصرياً)
3. **الحد الأقصى للمحتوى:** لا تزدحم شريحة بأكثر من:
   - 6 bullets
   - 4 بطاقات
   - 5 metrics
4. **التقسيم الذكي:** لو المحتوى كتير لشريحة واحدة، قسمه على شريحتين منفصلتين
5. **الدمج الذكي:** لو المحتوى قليل لشريحة، ادمجه مع شريحة مجاورة ذات صلة
6. **الأنواع الإلزامية:**
   - شريحة غلاف (1) — دائماً في البداية
   - شريحة فهرس (1) — بعد الغلاف
   - شريحة ختام (1) — دائماً في النهاية
   - شريحة مود بورد (0-1) — اختياري حسب توفر الصور
   - شرائح محتوى (N) — العدد يحدده المحتوى
7. **تنوع التصميم:** لا تجعل شريحتين متتاليتين بنفس نمط التصميم (مثلاً لا تجعل شريحتين متتاليتين كلتيهما bullets)
8. **الشرائح الثابتة:** الغلاف (1)، الفهرس (2)، المود بورد (قبل الأخيرة)، الختام (الأخيرة)
9. **شرائح تحليل الموقع:** إذا وُجدت بيانات موقع (location_lat/lng) أو (location_address)، أضف شرائح map_overview إلى map_landmarks إلى map_access إلى site_specs إلى site_photos إلى map_catchment متسلسلة بعد الفهرس
"""


def _suggest_design_style(title, bullets=None, slide_type='content'):
    """Pick a varied design style from the title, bullets, and slide type."""
    title = (title or '').lower()
    bullets_text = ' '.join(b or '' for b in (bullets or [])).lower()
    text = f"{title} {bullets_text}"

    fixed = {
        'cover': 'image',
        'index': 'flow',
        'moodboard': 'grid',
        'closing': 'minimal',
    }
    if slide_type in fixed:
        return fixed[slide_type]
    if slide_type.startswith('map_') or slide_type in ('site_specs', 'site_photos'):
        return 'map'

    if re.search(r'(?:مؤشر|أداء|قيمة مضافة|عائد|roi|noi|ربح|تكلفة|مالي|جدوى|إيراد|نسبة|رقم|إحصائية|تكلفة|دخل|استثمار|profit|cost|financial|revenue)', text):
        return 'dashboard'
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
    if re.search(r'(?:صورة|واجهة|تصميم معماري|انطباع|visual|image|facade|architectural|render)', text):
        return 'image'
    if re.search(r'(?:نظرة|نبذة|مقدمة|شرح|وصف|ملخص|تعريف|رؤية|رسالة|فلسفة|overview|introduction|description|summary|vision|mission)', text):
        return 'text'
    return 'cards'


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
    if re.search(r'(?:صور الموقع|street view)', t):
        return 'site_photos'
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
        "عمود الملاحظات جزء من الشريحة: إذا وُجدت ملاحظة فاعرضها تحت المرحلة أو بجانبها، ولا تحذفها ولا تختصرها.\n"
        + '\n'.join(f'- {format_timeline_phase_line(phase)}' for phase in phases)
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
    if project_data.get('street_view_images'):
        parts.append('صور Street View متاحة.')
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
        "- site_photos (يتطلب street_view_images)\n"
        "- map_catchment (يتطلب catchment_areas)\n"
        "استخدم placeholders ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##، ##STREET_VIEW_1##..."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Slide Plan Proposal
# ─────────────────────────────────────────────────────────────────────────────

SLIDE_PLAN_PROMPT = """أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية الاستثمارية.

## بيانات المشروع
{project_json}

## المهمة
1. حلل كمية ونوع المحتوى المتاح في بيانات المشروع
2. اقترح عدد شرائح مناسب (بين {min_slides} و {max_slides})
3. وزع المحتوى بحيث:
   - لا توجد شريحة بكلمتين فقط (فارغة بصرياً)
   - لا توجد شريحة مزدحمة بالكلام
   - كل شريحة لها فكرة واحدة واضحة
   - المحتوى المالي/الرقمي في شرائح منفصلة (dashboard style)
   - المحتوى الوصفي في شرائح بطاقات (card style)

{distribution_rules}

## أنواع الشرائح المسموحة
- cover: شريحة الغلاف (1 فقط، في البداية)
- index: شريحة الفهرس (1 فقط، بعد الغلاف)
- content: شريحة محتوى (عدد متغير)
- moodboard: شريحة المود بورد (0 أو 1، قبل الختام)
- closing: شريحة الختام (1 فقط، في النهاية)
- map_overview: خريطة الموقع + المعالم المحيطة (يتطلب إحداثيات)
- map_landmarks: خريطة + جدول أوقات القيادة (يتطلب nearby_landmarks)
- map_access: خريطة الطرق + المداخل (يتطلب main_roads)
- map_catchment: خريطة نطاق التأثير + دوائر القيادة (يتطلب catchment_areas)
- site_specs: جدول خصائص الموقع (يتطلب location data)
- site_photos: صور Street View للموقع (يتطلب street view images)

## أنماط تصميم الشرائح (design_style)
- dashboard: بطاقات أرقام مالية كبيرة (metrics)
- cards: شبكة بطاقات 2×2 أو 2×3
- timeline: خط زمني أفقي
- table: جدول بيانات
- text: نص + نقاط (bullets)
- image: صورة + نص قصير
- flow: مخطط تدفق (flow diagram)
- swot: تحليل SWOT في grid 2×2
- map: خريطة كخلفية + طبقة نص شفافة

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
      "type": "cover|index|content|moodboard|closing|map_overview|map_landmarks|map_access|map_catchment|site_specs|site_photos",
      "content_density": "low|medium|high",
      "design_style": "dashboard|cards|timeline|table|text|image|flow|swot|map",
      "bullets": ["نقطة 1", "نقطة 2", "نقطة 3"],
      "requires_image": true أو false,
      "content_source": "<أي حقل من بيانات المشروع يغذي هذه الشريحة>"
    }}
  ]
}}

## قواعد إضافية:
- **الشرائح الثابتة في موضعها دائماً مهما تغيّر العدد:**
  * الشريحة 1 = type=cover (الغلاف)
  * الشريحة 2 = type=index (الفهرس)
  * الشريحة قبل الأخيرة = type=moodboard (المود بورد)
  * الشريحة الأخيرة = type=closing (الختام)
- **قواعد الشركة في بداية هذه الرسالة (إن وُجدت) إلزامية:** إذا حددت قواعد التدريب ترتيباً أو عدداً أو تصميماً معيناً للشرائح، اتبعه بدقة فوق أي افتراضات أخرى
- باقي الشرائح متغيرة العدد والترتيب حسب قواعد الشركة وكمية بيانات المشروع
- لو في صور مود بورد متوفرة، ضع شريحة moodboard قبل الختام
- لو في إحداثيات + بيانات موقع، يجب أن يتضمن العرض شرائح الموقع الأساسية: site_specs، map_overview، map_access، map_catchment، map_landmarks حسب توفر البيانات، بالإضافة إلى تحليل الموقع من الحقل site_analysis.
- لا تحذف نوع المعلم أو المسافة أو مدة القيادة من جداول المعالم عند توفرها.
- لو وُجد جدول زمني (`timeline_table_data`)، ضع شريحة خطة زمنية بنمط timeline واعرض كل مرحلة مع مدتها ونهايتها وملاحظتها. الملاحظات جزء من الشريحة وليست هامشًا داخليًا.
- كل شريحة content لازم يكون فيها 3-6 bullets على الأقل
- وزع المحتوى بحيث كل شريحة تكون ممتلئة بصرياً 60-85%
"""


def resolve_slide_bounds(branding):
    """Resolve (min_slides, max_slides, default_count) from branding.

    When lock_slide_count is enabled the tenant's default_slide_count becomes an
    exact requirement, otherwise min/max act as the allowed range.
    """
    branding = branding or {}
    default_count = int(branding.get('default_slide_count') or 16)
    if branding.get('lock_slide_count'):
        return default_count, default_count, default_count
    min_slides = int(branding.get('min_slides') or 8)
    max_slides = int(branding.get('max_slides') or 30)
    if min_slides > max_slides:
        min_slides = max_slides
    return min_slides, max_slides, default_count


def build_fallback_plan(branding):
    """Build a default slide plan when AI slide planning fails.

    Uses the tenant's min/max/default slide count bounds.
    """
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    count = max(min_s, min(default_count, max_s))
    slides = [
        {'title': 'الغلاف', 'type': 'cover', 'design_style': 'image', 'requires_image': True, 'bullets': [], 'content_density': 'low'},
        {'title': 'الفهرس', 'type': 'index', 'design_style': 'flow', 'requires_image': False, 'bullets': [], 'content_density': 'low'},
    ]
    content_titles = [
        'نظرة عامة على المشروع',
        'الموقع والمميزات',
        'الوحدات والمساحات',
        'العائد الاستثماري',
        'الخدمات والمرافق',
        'لماذا هذا المشروع؟',
        'التحليل المالي والجدوى',
        'دراسة السوق والطلب',
        'الفرص والمزايا التنافسية',
        'خطة التنفيذ والجدول الزمني',
        'إدارة المخاطر والاستدامة',
        'المواصفات الفنية والهندسية',
    ]
    needed = max(0, count - 4)  # cover + index + moodboard + closing
    for i, title in enumerate(content_titles):
        if len(slides) - 1 >= needed:
            break
        style = _suggest_design_style(title, slide_type='content')
        # Avoid long runs of the same style
        if slides and slides[-1].get('design_style') == style and style == 'cards':
            style = 'text'
        slides.append({
            'title': title,
            'type': 'content',
            'design_style': style,
            'requires_image': False,
            'bullets': ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة'],
            'content_density': 'medium',
        })
    while len(slides) - 1 < needed:
        idx = len(slides) - 1
        title = f'تفاصيل محتوى فرعي {idx}'
        style = _suggest_design_style(title, slide_type='content')
        if slides and slides[-1].get('design_style') == style and style == 'cards':
            style = 'text'
        slides.append({
            'title': title,
            'type': 'content',
            'design_style': style,
            'requires_image': False,
            'bullets': ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة'],
            'content_density': 'medium',
        })
    slides.append({'title': 'مود بورد', 'type': 'moodboard', 'design_style': 'grid', 'requires_image': True, 'bullets': [], 'content_density': 'low'})
    slides.append({'title': 'شكراً لكم', 'type': 'closing', 'design_style': 'minimal', 'requires_image': False, 'bullets': [], 'content_density': 'low'})
    return {'proposed_count': len(slides), 'slides': slides}


def build_slide_plan_prompt(project_data, branding):
    """Build the prompt for AI to propose a slide plan."""
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)
    if len(project_json) > 6000:
        project_json = project_json[:6000] + '\n... [تم اختصار البيانات]'

    min_slides, max_slides, _default_count = resolve_slide_bounds(branding)

    prompt = SLIDE_PLAN_PROMPT.format(
        project_json=project_json,
        min_slides=min_slides,
        max_slides=max_slides,
        distribution_rules=CONTENT_DISTRIBUTION_RULES,
    )
    location_note = _location_data_note(project_data)
    if location_note:
        prompt += location_note
    timeline_note = _timeline_data_note(project_data)
    if timeline_note:
        prompt += timeline_note
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

    The cover, index, moodboard and closing slides keep their reserved positions;
    only content slides are removed or appended.
    """
    if target_count < 1 or len(slides) == target_count:
        return slides

    reserved_tail_types = {'moodboard', 'closing'}

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
                slide_type in ('cover', 'moodboard')
                or slide_type.startswith('map_')
                or slide_type == 'site_photos'
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
    valid_types = {'cover', 'index', 'content', 'moodboard', 'closing',
                   'map_overview', 'map_landmarks', 'map_access', 'map_catchment',
                   'site_specs', 'site_photos'}

    if slides[0].get('type') != 'cover':
        issues.append("First slide must be 'cover'")
    if len(slides) > 1 and slides[1].get('type') != 'index':
        issues.append("Second slide must be 'index'")
    if slides[-1].get('type') != 'closing':
        issues.append("Last slide must be 'closing'")

    # If a moodboard slide exists, ensure it is placed immediately before the closing slide
    moodboard_indices = [i for i, slide in enumerate(slides) if slide.get('type') == 'moodboard']
    if moodboard_indices:
        if moodboard_indices[-1] != len(slides) - 2:
            issues.append("Moodboard slide must be second-to-last if present")

    # Check each slide type and content
    for i, slide in enumerate(slides):
        slide_type = slide.get('type', 'content')
        if slide_type not in valid_types:
            issues.append(f"Slide {i+1} has unknown type '{slide_type}'")

        if slide_type in ('content', 'site_specs', 'map_landmarks'):
            bullets = slide.get('bullets', [])
            if len(bullets) < 3:
                issues.append(f"Slide {i+1} '{slide.get('title', '?')}' has only {len(bullets)} bullets (min: 3)")
            if len(bullets) > 6:
                issues.append(f"Slide {i+1} '{slide.get('title', '?')}' has {len(bullets)} bullets (max: 6)")

    return len(issues) == 0, issues


# ─────────────────────────────────────────────────────────────────────────────
# Single Slide Generation
# ─────────────────────────────────────────────────────────────────────────────

def build_slide_user_msg(slide, slide_num, total_slides, branding, project_data=None):
    """Build the user message for generating a single slide."""
    title = slide.get('title', f'شريحة {slide_num}')
    slide_type = slide.get('type', 'content')
    design_style = slide.get('design_style', 'cards')
    bullets = slide.get('bullets', [])
    density = slide.get('content_density', 'medium')

    bullets_text = '\n'.join(f'- {b}' for b in bullets) if bullets else '(لا توجد نقاط محددة — استخرج من بيانات المشروع)'

    style_instructions = {
        'dashboard': 'بطاقات أرقام مالية كبيرة (metrics) — كل رقم في بطاقة كبيرة 32-48px',
        'cards': 'بطاقات متعددة (2-6 بطاقات) بتخطيط مرن يناسب المحتوى — لا تلجأ تلقائياً إلى 4 بطاقات متساوية',
        'timeline': 'خط زمني أفقي — نقاط لكل مرحلة مع أشرطة ملونة، واعرض الملاحظة تحت المرحلة إن وُجدت',
        'table': 'جدول احترافي — header ملون + صفوف متبادلة + صف إجمالي بارز',
        'text': 'نص + نقاط (bullets) في قائمة منظمة',
        'image': 'صورة رئيسية + نص قصير — استخدم placeholder الصورة المحدد',
        'flow': 'مخطط تدفق أفقي — بطاقات مع أسهم تربطها',
        'swot': 'تحليل SWOT في grid 2×2 — كل ربع بلون مميز: القوة (أخضر)، الضعف (أحمر)، الفرص (أزرق)، التحديات (برتقالي)',
        'map': 'خريطة كخلفية مع طبقة شفافة للنص — استخدم placeholder الخريطة المحدد',
        'grid': 'شبكة صور المود بورد — استخدم placeholders ##MOODBOARD_IMAGE_1## إلى ##MOODBOARD_IMAGE_4##',
        'minimal': 'شريحة ختام بسيطة — "شكراً لكم" + بيانات التواصل',
    }.get(design_style, 'بطاقات احترافية')

    density_instructions = {
        'low': 'محتوى خفيف — 3-4 عناصر بصرياً متوازنة',
        'medium': 'محتوى متوسط — 4-5 عناصر ممتلئة بصرياً',
        'high': 'محتوى كثيف — 5-6 عناصر بدون ازدحام',
    }.get(density, 'محتوى متوسط')

    # Explicit image/map placeholder for this slide
    placeholder_note = ''
    if slide_type == 'map_overview':
        placeholder_note = 'يجب استخدام ##MAP_OVERVIEW## كخلفية رئيسية لهذه الشريحة.'
    elif slide_type == 'map_landmarks':
        placeholder_note = 'يجب استخدام ##MAP_LANDMARKS## كخلفية مع جدول أوقات القيادة والمسافات من البيانات.'
    elif slide_type == 'map_access':
        placeholder_note = 'يجب استخدام ##MAP_ACCESS## لعرض خريطة الطرق والمداخل.'
    elif slide_type == 'map_catchment':
        placeholder_note = 'يجب استخدام ##MAP_CATCHMENT## لعرض دوائر نطاق التأثير.'
    elif slide_type == 'site_photos':
        placeholder_note = 'يجب استخدام ##STREET_VIEW_1## إلى ##STREET_VIEW_4## لعرض صور الموقع.'
    elif slide_type == 'site_specs':
        placeholder_note = 'استخدم جدول بيانات احترافي لخصائص الموقع.'
    elif slide_type == 'moodboard':
        placeholder_note = 'يجب استخدام ##MOODBOARD_IMAGE_1## إلى ##MOODBOARD_IMAGE_4## في شبكة صور المود بورد.'
    elif design_style == 'image':
        placeholder_note = 'يمكن استخدام ##IMAGE_COVER## أو ##MOODBOARD_IMAGE_1## إذا كانت مناسبة للموضوع.'

    notes = [
        f'أنشئ فقط الشريحة {slide_num} لا غير',
        'اكتب HTML في div class="slide" واحد فقط',
        'لا تكتب شرح أو markdown أو كود إضافي',
        'التصميم يجب أن يكون احترافي وفاخر',
        'املأ الشريحة بصرياً بنسبة 60-85% — لا تتركها فارغة ولا تزدحمها',
        'لا تلجأ تلقائياً إلى تقسيم 2×2 — اختر التخطيط الأنسب للمحتوى',
    ]
    if placeholder_note:
        notes.insert(0, placeholder_note)
    if design_style == 'timeline' or re.search(r'(?:خطة|زمن|جدول|مراحل)', title):
        notes.append('اعرض مراحل الجدول الزمني كما وردت، بما في ذلك عمود الملاحظات داخل الشريحة.')
        timeline_note = _timeline_data_note(project_data)
        if timeline_note:
            notes.append(timeline_note.strip())
    notes_text = '\n'.join(f'- {n}' for n in notes)

    return f"""أنشئ شريحة {slide_num}/{total_slides}: {title}
النوع: {slide_type}
نمط التصميم: {design_style} — {style_instructions}
كثافة المحتوى: {density} — {density_instructions}

النقاط الأساسية:
{bullets_text}

ملاحظات:
{notes_text}"""


def _block_external_images(html):
    """Block external image URLs (http/https) except allowed placeholders."""
    if not html:
        return html
    allowed = {'##MAP_OVERVIEW##', '##MAP_LANDMARKS##', '##MAP_ACCESS##', '##MAP_CATCHMENT##',
               '##STREET_VIEW_1##', '##STREET_VIEW_2##', '##STREET_VIEW_3##', '##STREET_VIEW_4##',
               '##IMAGE_COVER##', '##LOGO##', '##MOODBOARD_IMAGE_1##', '##MOODBOARD_IMAGE_2##',
               '##MOODBOARD_IMAGE_3##', '##MOODBOARD_IMAGE_4##'}

    def _replace_src(match):
        url = match.group(1)
        if any(url.startswith(p) for p in allowed) or url.startswith('/uploads/') or url.startswith('/assets/'):
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
        'site_photos': '##STREET_VIEW',
    }
    if slide_type not in expected:
        return html
    marker = expected[slide_type]
    if marker in html:
        return html
    # Inject a background-image fallback if placeholder is missing
    if marker == '##STREET_VIEW':
        marker = '##STREET_VIEW_1##'
    fallback = f'<div style="position:absolute;top:0;left:0;right:0;bottom:0;z-index:-1;background-image:url({marker});background-size:cover;background-position:center;"></div>'
    html = html.replace('class="slide"', 'class="slide"')
    # Insert fallback before closing of slide div
    html = re.sub(r'(</div>\s*)$', fallback + r'\1', html, count=1)
    print(f"[POST] Injected fallback placeholder {marker} into slide")
    return html


def generate_single_slide(system_prompt, slide, slide_num, total_slides, branding, call_glm_fn, max_retries=2, project_data=None):
    """
    Generate a single slide's HTML.
    call_glm_fn: function(system_prompt, user_msg, max_tokens) -> response_dict
    """
    user_msg = build_slide_user_msg(slide, slide_num, total_slides, branding, project_data=project_data)
    slide_title = slide.get('title', f'شريحة {slide_num}')
    slide_type = slide.get('type', 'content')

    for attempt in range(1, max_retries + 2):
        try:
            print(f"[SLIDE-{slide_num}] Attempt {attempt}: {slide_title}")
            response = call_glm_fn(system_prompt, user_msg, max_tokens=6000)
            if 'choices' not in response or not response['choices']:
                print(f"[SLIDE-{slide_num}] ERROR: no choices (attempt {attempt})")
                continue

            content = response['choices'][0].get('message', {}).get('content', '')
            html = extract_html_from_glm(content)
            if not html:
                print(f"[SLIDE-{slide_num}] ERROR: no HTML extracted (attempt {attempt})")
                continue

            html = postprocess_slide(html, slide_type, slide_num=slide_num, slide_title=slide_title, total_slides=total_slides, tenant_id=branding.get('tenant_id'), branding=branding)
            count = html.count('class="slide"')
            if count >= 1:
                print(f"[SLIDE-{slide_num}] OK: {len(html)} chars")
                return html
            else:
                print(f"[SLIDE-{slide_num}] ERROR: no slide div found (attempt {attempt})")
        except Exception as e:
            print(f"[SLIDE-{slide_num}] Exception: {e}")

    print(f"[SLIDE-{slide_num}] FAILED after {max_retries + 1} attempts")
    return None


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
        return '\n'.join(slides)

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


DEFAULT_MOODBOARD_IMAGES = [
    '/uploads/moodboard_exterior.png',
    '/uploads/moodboard_materials.png',
    '/uploads/moodboard_interior.png',
    '/uploads/moodboard_urban_lifestyle.png'
]


def _creative_image_values(images):
    """Return the generated cover and moodboard image URLs in a safe shape with fallbacks."""
    default_cover = '/uploads/luxury_skyscraper_cover.png'
    if not isinstance(images, dict):
        return default_cover, DEFAULT_MOODBOARD_IMAGES[:]
    cover = images.get('cover') or images.get('mainImageData') or default_cover
    moodboard = images.get('moodboard') or images.get('moodboardImages') or []
    if not isinstance(moodboard, list) or not any(moodboard):
        moodboard = DEFAULT_MOODBOARD_IMAGES[:]
    return str(cover), [str(img) if img else '' for img in moodboard]


def _moodboard_url(index, moodboard):
    """Pick an image for a moodboard token, falling back to the default set if needed."""
    if index < len(moodboard) and moodboard[index]:
        return moodboard[index]
    if index < len(DEFAULT_MOODBOARD_IMAGES):
        return DEFAULT_MOODBOARD_IMAGES[index]
    return DEFAULT_MOODBOARD_IMAGES[0] if DEFAULT_MOODBOARD_IMAGES else ''


def _css_url(image_url):
    """Escape the small subset of characters that can break url('...') CSS."""
    return image_url.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '').replace('\r', '')


def _build_moodboard_fallback(images):
    """Build a deterministic moodboard layout matching the exact number of images."""
    if not images or not any(images):
        images = DEFAULT_MOODBOARD_IMAGES[:]
    # Prefer generated images; for missing slots use the first default image instead of
    # cycling 4 assets, which produced 4 images repeated many times for large counts.
    fallback_img = DEFAULT_MOODBOARD_IMAGES[0] if DEFAULT_MOODBOARD_IMAGES else ''
    images = [img if img else (DEFAULT_MOODBOARD_IMAGES[i] if i < len(DEFAULT_MOODBOARD_IMAGES) else fallback_img) for i, img in enumerate(images)]
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


def _replace_creative_image_placeholders(html, creative_images, slide_type):
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

    # Do not leave the cover blank simply because the model forgot its token.
    if slide_type == 'cover' and cover and cover not in html:
        background = (
            '<div aria-hidden="true" style="position:absolute;inset:0;z-index:0;'
            "background-image:url('" + _css_url(cover) + "');background-size:cover;background-position:center;\"></div>"
        )
        html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1' + background, html, count=1)

    # A moodboard slide should show the exact moodboard images
    if slide_type == 'moodboard' or 'moodboard' in str(slide_type).lower() or 'مودبورد' in html:
        if not re.search(r'<img|background-image', html, re.IGNORECASE):
            html = _build_moodboard_fallback(moodboard)
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
        raw_key = token_str.replace('##', '').strip()
        for k, v in project_data.items():
            if k.lower() == raw_key.lower() and v is not None:
                return str(v)
        return ''

    html = re.sub(r'##[a-zA-Z0-9_]+##', token_replacer, html)

    return html


def resolve_logo_in_html(html, tenant_id=None, _branding_cache=None):
    """Replace all logo placeholders and broken logo paths with tenant's logo URL."""
    if not html:
        return html
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
        if 'logo' in img_tag.lower() or '##LOGO##' in img_tag or 'tenant-assets' in img_tag:
            if 'src=' in img_tag.lower():
                img_tag = re.sub(r'src=["\'][^"\']*["\']', f'src="{logo_url}"', img_tag, flags=re.IGNORECASE)
            else:
                img_tag = img_tag.replace('<img', f'<img src="{logo_url}"')

            # Only add the logo sizing style once
            _LOGO_STYLE = 'max-height:50px;width:auto;object-fit:contain;display:inline-block;'
            if _LOGO_STYLE not in img_tag:
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


def postprocess_slide(html, slide_type, slide_num=None, slide_title=None, total_slides=None,
                       tenant_id=None, branding=None):
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

    # Content/map/site slides get a header/footer; cover, moodboard and closing never do.
    if slide_type not in ('cover', 'closing', 'moodboard') and not is_cover_or_closing:
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

        if not has_header:
            header_html = (
                f'<div style="position:absolute;top:0;right:0;left:0;height:56px;background:#fff;border-bottom:2px solid {primary};display:flex;align-items:center;padding:0 20px;z-index:10;">'
                '<img src="##LOGO##" style="height:40px;margin-right:12px;" />'
                f'<div style="width:3px;height:28px;background:{accent};margin:0 12px;"></div>'
                f'<span style="font-size:16px;font-weight:600;color:{primary};">{title}</span>'
                '</div>'
            )
            html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1\n' + header_html, html, count=1)

        if not has_footer:
            footer_html = (
                f'<div style="position:absolute;bottom:0;right:0;left:0;height:36px;background:{primary};display:flex;align-items:center;padding:0 16px;z-index:10;">'
                f'<span style="font-size:13px;color:#fff;">{title}</span>'
                f'<span style="font-size:13px;color:rgba(255,255,255,0.7);margin-right:auto;margin-left:8px;">{company_name}</span>'
                f'<div style="width:24px;height:24px;border-radius:50%;background:{accent};color:{primary};font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;">{slide_num}</div>'
                '</div>'
            )
            html = re.sub(r'(</div>\s*)$', '\n' + footer_html + r'\1', html, count=1)

    return html


def finalize_slide_html(html, slide_type, project_data, branding, creative_images=None,
                        map_placeholders=None, tenant_id=None, slide_num=None, slide_title=None,
                        total_slides=None):
    """Unified post-processing pipeline for every generated slide."""
    html = postprocess_slide(
        html, slide_type, slide_num=slide_num, slide_title=slide_title,
        total_slides=total_slides, tenant_id=tenant_id, branding=branding
    )
    if map_placeholders:
        html = _replace_map_placeholders(html, map_placeholders)
    html = _replace_creative_image_placeholders(html, creative_images, slide_type)
    html = _replace_data_placeholders(html, project_data, branding)
    html = resolve_logo_in_html(html, tenant_id)
    return html



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
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)
    if len(project_json) > 4000:
        project_json = project_json[:4000] + '\n... [تم اختصار البيانات]'

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

    system_prompt = f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}

## بيانات المسافات والأوقات (ممنوع تعديل الأرقام)
{landmarks_note}
{timeline_note}

## قواعد عامة
- كل شريحة 1280x720px (أو حسب نسبة العرض المحددة)
- CSS inline فقط
- ممنوع box-shadow/filter/backdrop-filter
- استخدم ##LOGO## للشعار، ##IMAGE_COVER## لصورة الغلاف، ##MOODBOARD_IMAGE_N## لصور المود بورد
- للخرائط: ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##
- لصور الموقع: ##STREET_VIEW_1## إلى ##STREET_VIEW_4##
- ممنوع base64 أو روابط صور خارجية
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
            )
            results[idx] = html

    return results
