"""
Slide Engine: Dynamic slide count & content distribution.
AI analyzes project data and proposes a balanced slide plan.
"""

import json
import re
import concurrent.futures
from design_templates import build_design_rules


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


def build_slide_plan_prompt(project_data, branding):
    """Build the prompt for AI to propose a slide plan."""
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)
    if len(project_json) > 6000:
        project_json = project_json[:6000] + '\n... [تم اختصار البيانات]'

    min_slides = branding.get('min_slides', 8)
    max_slides = branding.get('max_slides', 30)

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


def parse_slide_plan(response_text):
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

    if 'proposed_count' not in plan:
        plan['proposed_count'] = len(plan['slides'])

    # Ensure first slide is cover and last is closing
    if plan['slides']:
        plan['slides'][0]['type'] = 'cover'
        plan['slides'][-1]['type'] = 'closing'

    # Ensure second slide is index (if more than 2 slides)
    if len(plan['slides']) > 2:
        plan['slides'][1]['type'] = 'index'

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
    min_s = branding.get('min_slides', 8)
    max_s = branding.get('max_slides', 30)
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
    if len(slides) > 2 and slides[-2].get('type') != 'moodboard':
        issues.append("Second-to-last slide must be 'moodboard'")

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

            html = postprocess_slide(html, slide_type)
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
    """Return the generated cover and moodboard image URLs in a safe shape."""
    if not isinstance(images, dict):
        return '', []
    cover = images.get('cover') or images.get('mainImageData') or ''
    moodboard = images.get('moodboard') or images.get('moodboardImages') or []
    if not isinstance(moodboard, list):
        moodboard = []
    return str(cover or ''), [str(image or '') for image in moodboard]


def _css_url(image_url):
    """Escape the small subset of characters that can break url('...') CSS."""
    return image_url.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '').replace('\r', '')


def _build_moodboard_fallback(images):
    """Build a deterministic moodboard when the model omits its image tokens."""
    tiles = []
    for index in range(4):
        image = images[index] if index < len(images) else ''
        if image:
            background = "background-image:url('" + _css_url(image) + "');"
        else:
            background = 'background:linear-gradient(135deg,#6B1C23,#C2A176);'
        tiles.append(
            '<div style="min-width:0;min-height:0;background-size:cover;background-position:center;'
            + background + '"></div>'
        )
    return (
        '<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;'
        'background:#171717;color:#fff;font-family:Arial,sans-serif;box-sizing:border-box;padding:42px;">'
        '<div style="display:flex;align-items:center;justify-content:space-between;height:52px;margin-bottom:20px;">'
        '<div style="font-size:30px;font-weight:700;">لوحة الإلهام</div>'
        '<div style="width:170px;height:4px;background:#C2A176;"></div></div>'
        '<div style="height:560px;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;gap:8px;">'
        + ''.join(tiles) + '</div></div>'
    )


def _replace_creative_image_placeholders(html, creative_images, slide_type):
    """Resolve image tokens after generation so browser previews always have real sources."""
    if not html:
        return html
    cover, moodboard = _creative_image_values(creative_images)
    replacements = {
        '##IMAGE_COVER##': cover,
        '##COVER_IMAGE##': cover,
        '##MAIN_IMAGE##': cover,
    }
    for index in range(4):
        replacements[f'##MOODBOARD_IMAGE_{index + 1}##'] = moodboard[index] if index < len(moodboard) else ''
    for token, image in replacements.items():
        html = html.replace(token, image)

    # Do not leave the cover blank simply because the model forgot its token.
    if slide_type == 'cover' and cover and cover not in html:
        background = (
            '<div aria-hidden="true" style="position:absolute;inset:0;z-index:0;'
            "background-image:url('" + _css_url(cover) + "');background-size:cover;background-position:center;\"></div>"
        )
        html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1' + background, html, count=1)

    # A moodboard has a fixed job: show the four approved images. Make that
    # reliable even when a model response forgets one or more placeholders.
    if slide_type == 'moodboard' and moodboard:
        image_count = sum(1 for image in moodboard if image and image in html)
        if image_count < min(4, len([image for image in moodboard if image])):
            html = _build_moodboard_fallback(moodboard)
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

    system_prompt = f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}

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
            if map_placeholders:
                html = _replace_map_placeholders(html, map_placeholders)
            html = _replace_creative_image_placeholders(html, creative_images, slide.get('type', 'content'))
            results[idx] = html

    return results
