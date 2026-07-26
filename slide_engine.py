"""
Slide Engine: Dynamic slide count & content distribution.
AI analyzes project data and proposes a balanced slide plan.
"""

import json
import os
import re
import math
import shutil
import hashlib
import concurrent.futures
from design_templates import build_design_rules
import db

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
   - ⛔ ممنوع تماماً شريحة بكلمة أو كلمتين فقط (فارغة بصرياً)
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
9. **شرائح تحليل الموقع:** إذا وُجدت بيانات موقع (location_lat/lng) أو (location_address)، أضف شرائح map_overview → map_landmarks → map_access → site_specs → site_photos → map_catchment متسلسلة بعد الفهرس
"""

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
- باقي الشرائح متغيرة العدد والترتيب حسب قالب الشركة وكمية بيانات المشروع
- لو في صور مود بورد متوفرة، ضع شريحة moodboard قبل الختام
- لو في إحداثيات + معالم، أضف شرائح تحليل الموقع (map_*) متسلسلة بعد الفهرس
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
        slides.append({
            'title': title,
            'type': 'content',
            'design_style': 'cards',
            'requires_image': False,
            'bullets': ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة'],
            'content_density': 'medium',
        })
    while len(slides) - 1 < needed:
        idx = len(slides) - 1
        slides.append({
            'title': f'تفاصيل محتوى فرعي {idx}',
            'type': 'content',
            'design_style': 'cards',
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

    return SLIDE_PLAN_PROMPT.format(
        project_json=project_json,
        min_slides=min_slides,
        max_slides=max_slides,
        distribution_rules=CONTENT_DISTRIBUTION_RULES,
    )


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
        body.append({
            'title': f'تفاصيل إضافية {len(body)}',
            'type': 'content',
            'design_style': 'cards',
            'content_density': 'medium',
            'requires_image': False,
            'bullets': ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة'],
        })
    return body + tail


def parse_slide_plan(response_text, branding=None):
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

    # Fill defaults for any missing slide metadata
    for slide in plan['slides']:
        if 'design_style' not in slide:
            slide['design_style'] = 'cards'
        if 'content_density' not in slide:
            slide['content_density'] = 'medium'
        if 'requires_image' not in slide:
            slide['requires_image'] = False

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

def build_slide_user_msg(slide, slide_num, total_slides, branding):
    """Build the user message for generating a single slide."""
    title = slide.get('title', f'شريحة {slide_num}')
    slide_type = slide.get('type', 'content')
    design_style = slide.get('design_style', 'cards')
    bullets = slide.get('bullets', [])
    density = slide.get('content_density', 'medium')

    bullets_text = '\n'.join(f'- {b}' for b in bullets) if bullets else '(لا توجد نقاط محددة — استخرج من بيانات المشروع)'

    style_instructions = {
        'dashboard': 'بطاقات أرقام مالية كبيرة (metrics) — كل رقم في بطاقة كبيرة 32-48px',
        'cards': 'شبكة بطاقات 2×2 أو 2×3 — كل بطاقة فيها عنوان bold + وصف قصير + أيقونة',
        'timeline': 'خط زمني أفقي — نقاط لكل مرحلة مع أشرطة ملونة',
        'table': 'جدول احترافي — header ملون + صفوف متبادلة + صف إجمالي بارز',
        'text': 'نص + نقاط (bullets) في قائمة منظمة',
        'image': 'صورة + نص قصير جانبي',
        'flow': 'مخطط تدفق أفقي — بطاقات مع أسهم تربطها',
        'swot': 'تحليل SWOT في grid 2×2 — كل ربع بلون مميز: القوة (أخضر)، الضعف (أحمر)، الفرص (أزرق)، التحديات (برتقالي)',
        'map': 'خريطة كخلفية مع طبقة شفافة للنص — استخدم placeholder الخريطة المحدد',
    }.get(design_style, 'بطاقات احترافية')

    density_instructions = {
        'low': 'محتوى خفيف — 3-4 عناصر بصرياً متوازنة',
        'medium': 'محتوى متوسط — 4-5 عناصر ممتلئة بصرياً',
        'high': 'محتوى كثيف — 5-6 عناصر بدون ازدحام',
    }.get(density, 'محتوى متوسط')

    return f"""أنشئ شريحة {slide_num}/{total_slides}: {title}
النوع: {slide_type}
نمط التصميم: {design_style} — {style_instructions}
كثافة المحتوى: {density} — {density_instructions}

النقاط الأساسية:
{bullets_text}

ملاحظات:
- أنشئ فقط الشريحة {slide_num} لا غير
- اكتب HTML في div class="slide" واحد فقط
- لا تكتب شرح أو markdown أو كود إضافي
- التصميم يجب أن يكون احترافي وفاخر
- املأ الشريحة بصرياً بنسبة 60-85% — لا تتركها فارغة ولا تزدحمها"""


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


def postprocess_slide(html, slide_type):
    """Post-process generated HTML to enforce image and placeholder rules."""
    # The product design deliberately has no icon language.  Models sometimes
    # reintroduce SVGs, icon-font markup, or emoji despite the prompt, so enforce
    # that contract at the output boundary used by HTML/PDF/PPTX generation.
    html = re.sub(r'<svg\b[^>]*>[\s\S]*?</svg\s*>', '', html, flags=re.IGNORECASE)
    html = re.sub(
        r'<(?:i|span|div)\b[^>]*(?:class|id)=["\'][^"\']*(?:icon|emoji|lucide|fa-|material-icons)[^"\']*["\'][^>]*>[\s\S]*?</(?:i|span|div)\s*>',
        '', html, flags=re.IGNORECASE
    )
    html = _ICON_RE.sub('', html)
    html = _block_external_images(html)
    html = _ensure_map_placeholder(html, slide_type)
    return html


def generate_single_slide(system_prompt, slide, slide_num, total_slides, branding, call_glm_fn, max_retries=2):
    """
    Generate a single slide's HTML.
    call_glm_fn: function(system_prompt, user_msg, max_tokens) -> response_dict
    """
    user_msg = build_slide_user_msg(slide, slide_num, total_slides, branding)
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

    # Find the slide div
    slide_match = re.search(r'(<div[^>]*class=["\']slide["\'][\s\S]*$)', html)
    if slide_match:
        html = slide_match.group(1)

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
    return html


def _creative_image_values(images):
    """Return the generated cover and moodboard image URLs in a safe shape with fallbacks."""
    default_cover = '/uploads/luxury_skyscraper_cover.png'
    default_moodboard = [
        '/uploads/moodboard_exterior.png',
        '/uploads/moodboard_materials.png',
        '/uploads/moodboard_interior.png',
        '/uploads/moodboard_urban_lifestyle.png'
    ]
    if not isinstance(images, dict):
        return default_cover, default_moodboard
    cover = images.get('cover') or images.get('mainImageData') or default_cover
    moodboard = images.get('moodboard') or images.get('moodboardImages') or []
    if not isinstance(moodboard, list) or not any(moodboard):
        moodboard = default_moodboard
    else:
        moodboard = [moodboard[i] if i < len(moodboard) and moodboard[i] else default_moodboard[i % 4] for i in range(4)]
    return str(cover), [str(img) for img in moodboard]


def _css_url(image_url):
    """Escape the small subset of characters that can break url('...') CSS."""
    return image_url.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '').replace('\r', '')


def _build_moodboard_fallback(images):
    """Build a deterministic moodboard layout matching the exact number of images."""
    default_moodboard = [
        '/uploads/moodboard_exterior.png',
        '/uploads/moodboard_materials.png',
        '/uploads/moodboard_interior.png',
        '/uploads/moodboard_urban_lifestyle.png'
    ]
    if not images or not any(images):
        images = default_moodboard
    images = [img or default_moodboard[i % 4] for i, img in enumerate(images)]
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
    for index in range(16):
        img_url = moodboard[index] if index < len(moodboard) else moodboard[index % len(moodboard)]
        num = index + 1
        html = re.sub(rf'#*MOODBOARD_IMAGE_{num}#*', img_url, html, flags=re.IGNORECASE)
        html = re.sub(rf'#*PROJECT_IMAGE_{num}#*', img_url, html, flags=re.IGNORECASE)

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


def resolve_logo_in_html(html, tenant_id=None):
    """Replace all logo placeholders and broken logo paths with tenant's logo URL."""
    if not html:
        return html
    logo_url = '/assets/logo.png'
    if tenant_id:
        branding = db.get_branding(tenant_id) or {}
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
    """Remove generated icon markup and emoji while retaining company logo images."""
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
    # Strip SVGs, icon fonts and emojis first.
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
        landmarks_note = "استخدم الأرقام التالية كما هي وممنوع تعديلها:\n" + json.dumps(landmarks_matrix, ensure_ascii=False, indent=2)

    system_prompt = f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}

## بيانات المسافات والأوقات (ممنوع تعديل الأرقام)
{landmarks_note}

## قواعد عامة
- كل شريحة 1280x720px (أو حسب نسبة العرض المحددة)
- CSS inline فقط
- ممنوع box-shadow/filter/backdrop-filter
- استخدم ##LOGO## للشعار، ##IMAGE_COVER## لصورة الغلاف، ##MOODBOARD_IMAGE_N## لصور المود بورد
- للخرائط: ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##
- لصور الموقع: ##STREET_VIEW_1## إلى ##STREET_VIEW_4##
- ⛔ ممنوع base64 أو روابط صور خارجية
"""

    results = [None] * total

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_idx = {}
        for i, slide in enumerate(slides):
            future = executor.submit(
                generate_single_slide,
                system_prompt, slide, i + 1, total, branding, call_glm_fn
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
