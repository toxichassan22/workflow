import os
import sys
import json
import time
import re
import base64
import requests
import concurrent.futures
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory

load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZAI_KEY = os.environ.get("ZAI_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ZAI_BASE = 'https://api.z.ai/api/paas/v4'
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
GLM_MODEL = "glm-5.1"
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"[CONFIG] ZAI_KEY: {'SET' if ZAI_KEY else 'MISSING'}")
print(f"[CONFIG] OPENROUTER_KEY: {'SET' if OPENROUTER_KEY else 'MISSING'}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Call GLM (ZAI API)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def call_zai_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000):
    headers = {
        "Authorization": f"Bearer {ZAI_KEY}",
        "Content-Type": "application/json"
    }
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    payload = {
        "model": GLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"}
    }
    response = requests.post(f"{ZAI_BASE}/chat/completions", headers=headers, json=payload, timeout=300)
    data = response.json()
    if 'error' in data:
        print(f"[ZAI ERROR] Status {response.status_code}: {json.dumps(data['error'], ensure_ascii=False)}")
    return data

def extract_chat_content(response, label="GLM"):
    """Safely extract text content from ZAI/GLM API response.
    Raises a descriptive exception if the response is malformed."""
    if 'error' in response:
        err = response['error']
        if isinstance(err, dict):
            msg = err.get('message', json.dumps(err, ensure_ascii=False))
        else:
            msg = str(err)
        raise Exception(f"{label} API error: {msg}")
    if 'choices' not in response or not response['choices']:
        raise Exception(f"{label} returned no choices. Response: {json.dumps(response, ensure_ascii=False)[:500]}")
    msg = response['choices'][0].get('message', {}).get('content', '')
    if not msg:
        raise Exception(f"{label} returned empty content")
    return msg

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Call Image API (OpenRouter - Gemini)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def call_image_api(prompt):
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Real Estate Proposal Generator"
        }
        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt + " --aspect 16:9"}]}],
            "modalities": ["image", "text"]
        }
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=120)
        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {})
            if "images" in msg and len(msg["images"]) > 0:
                img = msg["images"][0]
                if isinstance(img, dict) and "image_url" in img:
                    return img["image_url"].get("url")
    except Exception as e:
        print("[IMAGE ERROR]", str(e))
    return None

def call_image_api_with_reference(reference_image_base64, prompt):
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Real Estate Proposal Generator"
        }
        user_content = [
            {"type": "text", "text": prompt + " --aspect 16:9"},
            {"type": "image_url", "image_url": {"url": reference_image_base64}}
        ]
        payload = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": user_content}],
            "modalities": ["image", "text"]
        }
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=120)
        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {})
            if "images" in msg and len(msg["images"]) > 0:
                img = msg["images"][0]
                if isinstance(img, dict) and "image_url" in img:
                    return img["image_url"].get("url")
    except Exception as e:
        print("[IMAGE ERROR]", str(e))
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Generate PDF with Playwright
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_pdf_with_playwright(html, project_name):
    from config.fonts_data import FONT_LIGHT_B64, FONT_BOLD_B64

    font_faces = ''
    for w in [300, 400, 500, 600]:
        font_faces += f"@font-face {{ font-family:'The Sans Arabic'; src:url('data:font/opentype;base64,{FONT_LIGHT_B64}') format('opentype'); font-weight:{w}; font-style:normal; font-display:swap; }}\n"
    for w in [700, 800, 900]:
        font_faces += f"@font-face {{ font-family:'The Sans Arabic'; src:url('data:font/truetype;base64,{FONT_BOLD_B64}') format('truetype'); font-weight:{w}; font-style:normal; font-display:swap; }}\n"

    full_html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <style>
    @page {{ size: 1280px 720px; margin: 0; }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    {font_faces}
    body {{ direction: rtl; font-family: 'The Sans Arabic', Tahoma, Arial, sans-serif; }}
    .slide {{ width: 1280px; height: 720px; direction: rtl; position: relative; overflow: hidden; page-break-after: always; page-break-inside: avoid; }}
    .slide:last-child {{ page-break-after: auto; }}
    img {{ max-width: 100%; max-height: 100%; object-fit: cover; }}
    .slide * {{ box-shadow: none !important; }}
  </style>
</head>
<body>
{html}
</body>
</html>"""

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
        page = browser.new_page()
        page.set_content(full_html, wait_until='load')
        page.wait_for_timeout(1000)
        page.evaluate('document.fonts.ready')

        output_path = os.path.join(OUTPUT_DIR, f"{project_name}_{int(time.time())}.pdf")
        page.pdf(
            path=output_path,
            width='1280px',
            height='720px',
            print_background=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
            prefer_css_page_size=True,
        )
        browser.close()

    return output_path

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Clean base64 and large image data from project data
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def clean_project_data(data):
    if not data:
        return data
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if k in ['mainImageData', 'moodboardImages', 'aiGeneratedImages', 'creativeImages', 'creativeSlots', 'image_b64', 'image', 'logo', 'referenceImage', 'slides']:
                continue
            cleaned[k] = clean_project_data(v)
        return cleaned
    elif isinstance(data, list):
        return [clean_project_data(item) for item in data]
    elif isinstance(data, str):
        if data.startswith('data:image/') or (len(data) > 1000 and ';base64,' in data) or len(data) > 10000:
            return "[IMAGE_DATA_OMITTED]"
        return data
    else:
        return data

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GLM Parallel Batch Prompt Builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Slide-by-slide generation (1 slide per API call for smaller prompts)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SLIDE_DEFS = [
    {'num': 1,  'title': 'شريحة الغلاف',     'type': 'cover',     'desc': 'cover: خلفية صورة الغلاف ##IMAGE_COVER## بكامل الشريحة. طبقة شفافة rgba(90,8,8,0.65). شعار ##LOGO## height:80px في المنتصف. اسم المشروع أبيض font-size:48px. وصف ذهبي font-size:20px. خطوط ذهبية هندسية زخرفية. بدون هيدر/فوتر.'},
    {'num': 2,  'title': 'الفهرس',            'type': 'index',     'desc': 'index: عناوين الشرائح 1-16 في جدول فهرس احترافي عمودين. رقم كل شريحة في دائرة عنابية. خلفية #FBFAF8. ⚠️ هيدر إلزامي في الأعلى (شعار ##LOGO## + خط ذهبي + عنوان الشريحة). ⚠️ فوتر إلزامي في الأسفل (اسم المشروع + رقم الشريحة في دائرة ذهبية). ⛔ ممنوع إطلاقاً: أي صور أو base64 أو روابط صور. النص فقط + أرقام الشرائح في دوائر.'},
    {'num': 3,  'title': 'الملخص التنفيذي',    'type': 'content',   'desc': 'content: Dashboard مالي — بطاقات كرتونية كبيرة: إجمالي التكلفة، الإيرادات السنوية، إجمالي الأرباح (الأكبر بصرياً)، ROI %، NOI، مدة الاسترداد. الأرقام بخط كبير 32-48px. بدون صور.'},
    {'num': 4,  'title': 'الرؤية والفكرة',     'type': 'content',   'desc': 'content: نص تعريفي عن المشروع + بطاقات للمكونات الرئيسية مع أيقونات Unicode. يمكنك استخدام ##MOODBOARD_IMAGE_1## كخلفية شفافة opacity:0.15.'},
    {'num': 5,  'title': 'الموقع الاستراتيجي', 'type': 'content',   'desc': 'content: بطاقات مميزات الموقع (القرب من الخدمات، الوصول، المدينة) مع أيقونات. يمكنك استخدام ##MOODBOARD_IMAGE_2## كخلفية شفافة opacity:0.15.'},
    {'num': 6,  'title': 'مميزات المشروع',     'type': 'content',   'desc': 'content: Grid 2×3 من البطاقات الفاخرة: كل بطاقة فيها أيقونة Unicode كبيرة + عنوان bold + وصف قصير. خلفية كل بطاقة بيضاء مع border ذهبي رفيع. بدون صور.'},
    {'num': 7,  'title': 'مكونات المشروع',     'type': 'content',   'desc': 'content: جدول احترافي: header عنابي #7A0C0C أبيض، صفوف متبادلة #FBFAF8 و #fff، صف الإجمالي بارز. أسفل الجدول 3 بطاقات ملخص. بدون صور.'},
    {'num': 8,  'title': 'افتراضات الربح التشغيلي', 'type': 'content', 'desc': 'content: معادلة بصرية كبيرة: (إيرادات سنوية − مصاريف سنوية = صافي ربح). كل عنصر في بطاقة مع سهم يربطها. أرقام بخط كبير. بدون صور.'},
    {'num': 9,  'title': 'افتراضات التكاليف',  'type': 'content',   'desc': 'content: 3 بطاقات كبيرة: بطاقة تكلفة الأرض (مع تفاصيل السعر/م²)، بطاقة تكلفة التطوير، بطاقة الإجمالي (الأكبر والأبرز). بدون صور.'},
    {'num': 10, 'title': 'الأرباح والتخارج',   'type': 'content',   'desc': 'content: Flow diagram أفقي: بطاقة ربح تشغيلي → علامة + → بطاقة قيمة التخارج → علامة = → بطاقة إجمالي الأرباح (الأكبر). يمكنك استخدام ##MOODBOARD_IMAGE_3## كخلفية شفافة opacity:0.1.'},
    {'num': 11, 'title': 'المؤشرات المالية',   'type': 'content',   'desc': 'content: أعلى الشريحة 3 بطاقات كبيرة: ROI % و NOI و مدة الاسترداد. أسفلها مقارنة بصرية: شريطين أفقيين (إجمالي التكلفة vs إجمالي الأرباح). بدون صور.'},
    {'num': 12, 'title': 'الجدول الزمني',      'type': 'content',   'desc': 'content: Timeline أفقي: خط رأسي في المنتصف، نقاط على الخط لكل مرحلة، أشرطة ملونة #7A0C0C و #C4A35A. Years والأرباع Q1-Q4 في الأعلى. بدون صور.'},
    {'num': 13, 'title': 'فرص الاستثمار',      'type': 'content',   'desc': 'content: 3-4 بطاقات High-Impact: عنوان bold + وصف + أيقونة Unicode كبيرة. يمكنك استخدام ##MOODBOARD_IMAGE_4## كخلفية شفافة opacity:0.1.'},
    {'num': 14, 'title': 'المخاطر والافتراضات', 'type': 'content',  'desc': 'content: بطاقات رمادية #f5f5f5 وبيج #f9f6f0 هادئة + أيقونة ⚠️ خطية. عنوان فرعي: نقاط يجب التحقق منها. بدون أي صور إطلاقاً.'},
    {'num': 15, 'title': 'المود بورد',         'type': 'moodboard', 'desc': 'moodboard: Grid 2×2 يشغل المساحة بين top:56px و bottom:36px. كل خلية فيها صورة واحدة: ##MOODBOARD_IMAGE_1## و ##MOODBOARD_IMAGE_2## و ##MOODBOARD_IMAGE_3## و ##MOODBOARD_IMAGE_4##. كل صورة بـ background-size:cover;background-position:center. فواصل رفيعة 4px بين الخلايا.'},
    {'num': 16, 'title': 'الختام',             'type': 'closing',   'desc': 'closing: خلفية عنابية gradient linear-gradient(135deg,#7A0C0C,#5A0808) تملأ الشريحة. شعار ##LOGO## height:80px في المنتصف. "شكراً لكم" أبيض 48px. اسم المشروع ذهبي #C4A35A. بيانات التواصل. بدون هيدر/فوتر.'},
]

# Design rules — sent ONCE in system prompt, not per-slide
DESIGN_RULES = """أنت مصمم عروض تقديمية عقارية فاخرة بالسعودية. صمم كل شريحة كلوحة فنية احترافية.

## الألوان
- عنابي: #7A0C0C (اللون الرئيسي للعناوين والأزرار)
- عنابي غامق: #5A0808 (التدرجات)
- ذهبي: #C4A35A (الزخارف والتفاصيل)
- خلفية: #FBFAF8
- نص: #333333
- أبيض: #FFFFFF

## الخط
font-family: 'The Sans Arabic', Arial, sans-serif
- عناوين الكبيرة: 36-48px font-weight:700 color:#7A0C0C
- عناوين فرعية: 24-28px font-weight:600 color:#7A0C0C
- نصوص عادية: 14-18px font-weight:400 color:#333
- أرقام مالية كبيرة: 32-48px font-weight:700 color:#7A0C0C

## الشريحة الأساسية
<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;font-family:'The Sans Arabic',Arial,sans-serif;">
CSS inline فقط. ممنوع box-shadow/filter/backdrop-filter.

## هيدر إلزامي — يجب أن يوجد في كل شريحة من 2 إلى 15
position:absolute;top:0;right:0;left:0;height:56px;background:#fff;border-bottom:2px solid #7A0C0C;
المحتوى: شعار ##LOGO## height:40px يساراً + خط رأسي ذهبي 4px + اسم الشريحة 16px font-weight:600 color:#7A0C0C
⚠️ شريحة 2 (الفهرس) لابد أن يكون فيها هذا الهيدر. شريحة الغلاف (1) والختام (16) فقط بدون هيدر.

## فوتر إلزامي — يجب أن يوجد في كل شريحة من 2 إلى 15
position:absolute;bottom:0;right:0;left:0;height:36px;background:#7A0C0C;display:flex;align-items:center;padding:0 16px;
المحتوى: اسم المشروع 13px أبيض + 'منافع الاقتصادية للعقار' opacity:0.7 + رقم الشريحة في دائرة ذهبية 24px
⚠️ شريحة 2 (الفهرس) لابد أن يكون فيها هذا الفوتر.

## منطقة المحتوى (شرائح 2-15)
top:56px → bottom:36px. padding: 20px 40px.

## البطاقات (Cards)
كل بطاقة: background:#fff border:1px solid rgba(196,163,90,0.2) border-radius:8px padding:16-24px.
أيقونات: استخدم Unicode emojis كبيرة (🏗️ 📊 💰 🏠 📍 ✅ ⚠️ 🔑 📈) بدل الصور.

## الصور Placeholder
- صورة الغلاف: ##IMAGE_COVER## (background-image فقط)
- صور المود بورد: ##MOODBOARD_IMAGE_1## إلى ##MOODBOARD_IMAGE_4##
- ⛔ ممنوع إطلاقاً: base64، روابط خارجية، أو أي صور `<img>` في شريحة الفهرس (شريحة 2) أو المخاطر (شريحة 14)
- شريحة 2 (الفهرس): نص + أرقام فقط. بدون أي `<img>` أو صور مطلقاً
- شريحة 14 (المخاطر): بطاقات نصية فقط. بدون أي `<img>` أو صور مطلقاً

## قواعد التصميم
- تجنب النص الطويل — استخدم بطاقات ونقاط مختصرة
- كل شريحة = تصور واحد واضح (dashboard, grid, timeline, etc.)
- الأرقام المالية يجب أن تكون بارزة بصرياً
- استخدم الألوان لتوضيح الهرمية: عنابي للعناوين، ذهبي للتفاصيل، رمادي للنصوص الفرعية"""

def _get_images_info(images):
    if isinstance(images, list):
        has_cover = bool(images[0]) if images else False
        moodboard_count = sum(1 for img in images[1:] if img) if len(images) > 1 else 0
    elif isinstance(images, dict):
        has_cover = bool(images.get('cover'))
        moodboard_count = sum(1 for img in images.get('moodboard', []) if img)
    else:
        has_cover = False
        moodboard_count = 0
    info = f"- صورة الغلاف: {'متوفرة' if has_cover else 'لا توجد'}\n"
    info += f"- صور المود بورد: {moodboard_count} صور متوفرة\n" if moodboard_count > 0 else "- صور المود بورد: لا توجد\n"
    return info

def build_system_prompt(project_data, images_info):
    """Build the shared system prompt ONCE for all slides (~3K chars)."""
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)
    # Truncate project data if too long to keep system prompt compact
    if len(project_json) > 4000:
        project_json = project_json[:4000] + '\n... [تم اختصار البيانات]'
    return f"""{DESIGN_RULES}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}"""

def build_slide_user_msg(slide_num):
    """Build the user message for a single slide (~500 chars)."""
    s = SLIDE_DEFS[slide_num - 1]
    return f"""أنشئ شريحة {s['num']}/16: {s['title']}
النوع: {s['type']}
{s['desc']}

ملاحظات:
- أنشئ فقط الشريحة {s['num']} لا غير
- اكتب HTML في div class=\"slide\" واحد فقط
- لا تكتب شرح أو markdown أو كود إضافي
- التصميم يجب أن يكون احترافي وفاخر"""

def postprocess_slide(html, slide_num):
    """Post-process: strip forbidden images and ensure header/footer exist."""
    # Slides where <img> tags are strictly forbidden (desc says 'بدون صور')
    NO_IMAGE_SLIDES = {2, 3, 6, 7, 8, 9, 11, 12, 14}
    if slide_num in NO_IMAGE_SLIDES:
        html = re.sub(r'<img\s[^>]*>', '', html, flags=re.IGNORECASE)

    # Slides 2-15 MUST have a header and footer; inject if missing
    HEADER_FOOTER_SLIDES = set(range(2, 16))
    if slide_num in HEADER_FOOTER_SLIDES:
        has_header = bool(re.search(r'height:\s*56px', html))
        has_footer = bool(re.search(r'height:\s*36px', html))
        slide_title = SLIDE_DEFS[slide_num - 1]['title']

        if not has_header:
            header_html = (
                '<div style="position:absolute;top:0;right:0;left:0;height:56px;background:#fff;border-bottom:2px solid #7A0C0C;display:flex;align-items:center;padding:0 20px;z-index:10;">'
                '<img src="##LOGO##" style="height:40px;margin-right:12px;" />'
                '<div style="width:3px;height:28px;background:#C4A35A;margin:0 12px;"></div>'
                f'<span style="font-size:16px;font-weight:600;color:#7A0C0C;">{slide_title}</span>'
                '</div>'
            )
            html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1\n' + header_html, html, count=1)
            print(f"[POST] Injected header into slide {slide_num}")

        if not has_footer:
            footer_html = (
                '<div style="position:absolute;bottom:0;right:0;left:0;height:36px;background:#7A0C0C;display:flex;align-items:center;padding:0 16px;z-index:10;">'
                f'<span style="font-size:13px;color:#fff;">{slide_title}</span>'
                '<span style="font-size:13px;color:rgba(255,255,255,0.7);margin-right:auto;margin-left:8px;">منافع الاقتصادية للعقار</span>'
                f'<div style="width:24px;height:24px;border-radius:50%;background:#C4A35A;color:#7A0C0C;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;">{slide_num}</div>'
                '</div>'
            )
            html = re.sub(r'(</div>\s*)$', '\n' + footer_html + r'\1', html, count=1)
            print(f"[POST] Injected footer into slide {slide_num}")

    return html

def generate_single_slide(system_prompt, slide_num, max_retries=2):
    """Generate a single slide. system_prompt is pre-built and shared."""
    user_msg = build_slide_user_msg(slide_num)
    slide_title = SLIDE_DEFS[slide_num - 1]['title']

    for attempt in range(1, max_retries + 2):
        try:
            print(f"[SLIDE-{slide_num}] Attempt {attempt}: {slide_title}")
            response = call_zai_chat(system_prompt, user_msg, max_tokens=6000)
            if 'choices' not in response:
                print(f"[SLIDE-{slide_num}] ERROR: no choices (attempt {attempt})")
                continue
            html = extract_html_from_glm(response)
            html = postprocess_slide(html, slide_num)
            count = html.count('class="slide"')
            if count >= 1:
                print(f"[SLIDE-{slide_num}] OK Done ({len(html)} chars)")
                return html
            else:
                print(f"[SLIDE-{slide_num}] WARN No slide found (attempt {attempt})")
        except Exception as e:
            print(f"[SLIDE-{slide_num}] EXCEPTION (attempt {attempt}): {e}")

    print(f"[SLIDE-{slide_num}] FAIL All attempts failed for {slide_title}")
    return ''

def build_glm_prompt(project_data, images):
    """Legacy single-shot prompt builder (kept for /api/generate compatibility)"""
    project_data = clean_project_data(project_data)
    images_info = _get_images_info(images)
    sys_prompt = build_system_prompt(project_data, images_info)
    return sys_prompt + '\n\n'.join(build_slide_user_msg(i) for i in range(1, 17))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Extract HTML from GLM response
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def extract_html_from_glm(raw_response):
    content = raw_response.get('choices', [{}])[0].get('message', {}).get('content', '')

    # Try to extract from code block first
    code_match = re.search(r'```(?:html)?\s*\n?([\s\S]*?)```', content)
    if code_match:
        html = code_match.group(1).strip()
        if 'class="slide"' in html:
            return html

    # Try balanced extraction: find each <div class="slide" and match its closing tags
    slides = []
    for m in re.finditer(r'<div[^>]*class=["\']slide["\'][^>]*>', content):
        start = m.start()
        # Find the matching closing by counting nested divs
        depth = 0
        pos = start
        while pos < len(content) and pos != -1:
            next_open = content.find('<div', pos)
            next_close = content.find('</div>', pos)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + 4
            else:
                if depth == 0:
                    end = next_close + 6
                    slides.append(content[start:end].strip())
                    break
                depth -= 1
                pos = next_close + 6

    if slides:
        return '\n'.join(slides)

    # Fallback: regex match (may miss deeply nested slides)
    slides_regex = re.findall(r'<div\s+class="slide"[\s\S]*?</div>\s*</div>\s*</div>\s*</div>', content)
    if slides_regex:
        return '\n'.join(slides_regex)

    if '<div' in content and 'class="slide"' in content:
        return content

    return content

def validate_html(html):
    slide_count = html.count('class="slide"')
    if slide_count < 16:
        print(f"[WARN] Only {slide_count} slides found, expected 16")
    if 'dir="rtl"' not in html:
        html = html.replace('<div class="slide"', '<div class="slide" dir="rtl"')
    return html

def _extract_json_from_text(text):
    """Try to find a valid JSON object with 'action' key in text.
    Returns a dict or None."""
    # 1) Try parsing the entire response as JSON
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, dict) and 'action' in parsed:
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    # 2) Try extracting from markdown code block
    cb = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if cb:
        try:
            parsed = json.loads(cb.group(1).strip())
            if isinstance(parsed, dict) and 'action' in parsed:
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    # 3) Balanced-brace scan for the first complete JSON object
    start = text.find('{')
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == '\\' and in_str:
                esc = True
                continue
            if c == '"' and not esc:
                in_str = not in_str
                continue
            if not in_str:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[start:i+1])
                            if isinstance(parsed, dict) and 'action' in parsed:
                                return parsed
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 1: Generate all slides HTML with GLM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json
    project_data = clean_project_data(data.get('projectData', {}))
    images = data.get('images', {})

    print(f"\n[GENERATE] Starting generation for: {project_data.get('projectName', 'Unknown')}")

    prompt = build_glm_prompt(project_data, images)
    print(f"[GENERATE] Prompt length: {len(prompt)} chars (4 batches)")

    try:
        response = call_zai_chat(prompt, "قم بإنشاء العرض التقديمي الكامل.", max_tokens=16000)

        raw = extract_chat_content(response, "GENERATE")
        print(f"[GENERATE] GLM response: {len(raw)} chars")

        html = extract_html_from_glm(response)
        html = validate_html(html)

        print(f"[GENERATE] Final HTML: {len(html)} chars, {html.count('class=\"slide\"')} slides")
        return jsonify({'success': True, 'html': html})

    except Exception as e:
        print(f"[GENERATE ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 2: Generate images (1 cover + 4 moodboard)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/generate-images', methods=['POST'])
def api_generate_images():
    data = request.json
    project_data = clean_project_data(data.get('projectData', {}))

    project_name = project_data.get('projectName', 'مشروع')
    project_type = project_data.get('projectType', 'سكني')
    location = project_data.get('location', 'السعودية')

    print(f"\n[IMAGES] Generating 5 images for: {project_name}")

    images = {'cover': None, 'moodboard': []}

    # 1. Cover image
    print("[IMAGES] Generating cover image...")
    cover_prompt = f"Modern luxury {project_type} building in {location}, professional architectural photography, elegant design, high quality, no text, no watermark"
    images['cover'] = call_image_api(cover_prompt)
    print(f"[IMAGES] Cover: {'OK' if images['cover'] else 'FAILED'}")

    # 2. Four moodboard images
    moodboard_prompts = [
        f"Interior design of luxury {project_type}, modern elegant living space, warm lighting, premium finishes, architectural photography",
        f"Aerial view of {project_type} complex in {location}, modern architecture, landscaped gardens, professional photography",
        f"Living room interior of premium {project_type}, contemporary furniture, large windows, natural light, interior design photography",
        f"Architectural details of luxury {project_type}, facade close-up, premium materials, marble and glass, professional photography"
    ]

    for i, prompt in enumerate(moodboard_prompts):
        print(f"[IMAGES] Generating moodboard {i+1}/4...")
        img = call_image_api(prompt)
        images['moodboard'].append(img)
        print(f"[IMAGES] Moodboard {i+1}: {'OK' if img else 'FAILED'}")
        if i < len(moodboard_prompts) - 1:
            time.sleep(1)

    print(f"[IMAGES] Done. Cover: {'OK' if images['cover'] else 'FAIL'}, Moodboard: {sum(1 for x in images['moodboard'] if x)}/4")
    return jsonify({'success': True, 'images': images})

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENDPOINT 3: Export PDF
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/export-pdf', methods=['POST'])
def api_export_pdf():
    data = request.json
    # Accept both 'slidesHtml' (from designer) and 'html' (legacy)
    slides_html = data.get('slidesHtml', '') or data.get('html', '')
    project_name = data.get('projectName', 'project')

    print(f"\n[PDF] Exporting PDF for: {project_name}")

    if not slides_html:
        return jsonify({'success': False, 'error': 'No HTML provided'}), 400

    try:
        output_path = generate_pdf_with_playwright(slides_html, project_name)
        filename = os.path.basename(output_path)
        print(f"[PDF] Generated: {filename}")
        return jsonify({'success': True, 'url': f'/outputs/{filename}', 'filename': filename})
    except Exception as e:
        print(f"[PDF ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMPATIBILITY ENDPOINTS (Old frontend expects these)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/official-outline', methods=['POST'])
def api_official_outline():
    """Compatibility: Generate outline/titles for 16 slides"""
    project_data = clean_project_data(request.json.get('projectData', {}))
    print(f"\n[OUTLINE] Generating outline for: {project_data.get('projectName', 'Unknown')}")

    prompt = f"""أنت محلل مالي وعقاري ذكي. قم بإنشاء هيكل (outline) عرض تقديمي مخصص بالكامل لمشروع المستخدم.

المطلوب: بالضبط 16 شريحة بالترتيب التالي:
1. شريحة غلاف (type="cover")
2. شريحة فهرس (type="index")
3-14. 12 شريحة محتوى (type="content")
15. شريحة مود بورد (type="mood_board")
16. شريحة ختام (type="closing")

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

Return ONLY valid JSON: {{"titles": [{{"title": "عنوان الشريحة", "bullets": ["نقطة 1", "نقطة 2"], "type": "content"}}]}}
"""

    try:
        response = call_zai_chat(prompt, "اكتب الهيكل المكون من 16 شريحة.", max_tokens=4000)
        raw = extract_chat_content(response, "OUTLINE")

        json_match = re.search(r'\{[\s\S]*"titles"[\s\S]*\}', raw)
        if not json_match:
            raise Exception("No JSON found in response")

        parsed = json.loads(json_match.group())
        titles = parsed.get('titles', [])

        if len(titles) < 16:
            while len(titles) < 16:
                titles.append({'title': f'شريحة {len(titles)+1}', 'bullets': [], 'type': 'content'})

        print(f"[OUTLINE] Generated {len(titles)} slides")
        return jsonify({'success': True, 'titles': titles})

    except Exception as e:
        print(f"[OUTLINE ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-titles', methods=['POST'])
def api_generate_titles():
    """Compatibility: Same as official-outline"""
    return api_official_outline()


@app.route('/api/generate-main-image', methods=['POST'])
def api_generate_main_image():
    """Compatibility: Generate main cover image"""
    prompt = request.json.get('prompt', '')
    reference = request.json.get('referenceImage')
    print(f"\n[MAIN IMAGE] Generating cover image...")

    try:
        if reference:
            image = call_image_api_with_reference(reference, prompt)
        else:
            image = call_image_api(prompt)

        if image:
            return jsonify({'success': True, 'image': image})
        else:
            return jsonify({'success': False, 'error': 'No image generated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/api/generate-slide-image', methods=['POST'])
def api_generate_slide_image():
    """Compatibility: Generate image for a specific slide"""
    prompt = request.json.get('prompt', '')
    reference = request.json.get('referenceImage')
    print(f"\n[SLIDE IMAGE] Generating...")

    try:
        if reference:
            image = call_image_api_with_reference(reference, prompt)
        else:
            image = call_image_api(prompt)

        if image:
            return jsonify({'success': True, 'image': image})
        else:
            return jsonify({'success': False, 'error': 'No image generated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-image', methods=['POST'])
def api_generate_image_single():
    """Compatibility: Generate single image (singular)"""
    prompt = request.json.get('prompt', '')
    reference = request.json.get('referenceImage')
    print(f"\n[IMAGE] Generating single image...")

    try:
        if reference:
            image = call_image_api_with_reference(reference, prompt)
        else:
            image = call_image_api(prompt)

        if image:
            return jsonify({'success': True, 'image': image})
        else:
            return jsonify({'success': False, 'error': 'No image generated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/designer-generate', methods=['POST'])
def api_designer_generate():
    """Generate slides HTML: 16 individual slides in parallel (4 concurrent workers)."""
    project_data = clean_project_data(request.json.get('projectData', {}))
    outline = request.json.get('outline', [])
    images = request.json.get('images', {})
    images_info = _get_images_info(images)

    # Build system prompt ONCE — shared across all 16 slides
    system_prompt = build_system_prompt(project_data, images_info)
    print(f"\n[DESIGNER] Starting 16-slide parallel generation (4 workers)...")
    print(f"[DESIGNER] System prompt: {len(system_prompt)} chars (shared)")
    start_time = time.time()

    try:
        # Run all 16 slides in parallel with 4 concurrent workers
        results = [None] * 16
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_idx = {}
            for i in range(16):
                future = executor.submit(generate_single_slide, system_prompt, i + 1)
                future_to_idx[future] = i

            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                results[idx] = future.result()

        elapsed = round(time.time() - start_time, 1)
        combined_html = '\n'.join(h for h in results if h).strip()
        combined_html = validate_html(combined_html)
        total_slides = combined_html.count('class="slide"')
        print(f"[DESIGNER] Done in {elapsed}s — {total_slides} slides total")

        DEFAULT_TITLES = [
            'الغلاف', 'الفهرس', 'الملخص التنفيذي', 'الرؤية والفكرة',
            'الموقع الاستراتيجي', 'مميزات المشروع', 'مكونات المشروع',
            'افتراضات الإيرادات', 'افتراضات التكاليف', 'الأرباح والتخارج',
            'المؤشرات المالية', 'الجدول الزمني', 'فرص الاستثمار',
            'المخاطر', 'المود بورد', 'الختام'
        ]

        def extract_slide_title(s_html, def_title):
            for pattern in [r'<h[1-6][^>]*>([\s\S]*?)</h[1-6]>',
                            r'class="[^"]*(?:slide-title|title)[^"]*"[^>]*>([\s\S]*?)</']:
                m = re.search(pattern, s_html)
                if m:
                    t = re.sub(r'<[^>]*>', '', m.group(1)).strip()
                    if t and len(t) < 80:
                        return t
            return def_title

        slide_starts = [m.start() for m in re.finditer(r'<div[^>]*class=["\']slide["\']', combined_html)]
        slides_list = []
        for idx, start_pos in enumerate(slide_starts):
            end_pos = slide_starts[idx + 1] if idx + 1 < len(slide_starts) else len(combined_html)
            slide_html = combined_html[start_pos:end_pos].strip()
            if not slide_html:
                continue
            if idx < len(outline) and outline[idx].get('title'):
                def_title = outline[idx]['title']
            elif idx < len(DEFAULT_TITLES):
                def_title = DEFAULT_TITLES[idx]
            else:
                def_title = f'شريحة {idx + 1}'
            title = extract_slide_title(slide_html, def_title)
            slides_list.append({'title': title, 'html': slide_html})

        if not slides_list and combined_html:
            slides_list.append({'title': 'شريحة 1', 'html': combined_html})

        print(f"[DESIGNER] Returning {len(slides_list)} slides to frontend")
        return jsonify({'success': True, 'slides': slides_list})

    except Exception as e:
        print(f"[DESIGNER ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-outline', methods=['POST'])
def api_generate_outline():
    """Compatibility: Generate outline"""
    return api_official_outline()


@app.route('/api/generate-content', methods=['POST'])
def api_generate_content():
    """Compatibility: Generate content for a slide"""
    slide_data = request.json.get('slide', {})
    project_data = clean_project_data(request.json.get('projectData', {}))

    prompt = f"اكتب محتوى للشريحة: {slide_data.get('title', '')}\n\nبيانات المشروع:\n{json.dumps(project_data, ensure_ascii=False, indent=2)}"

    try:
        response = call_zai_chat(prompt, "اكتب المحتوى.", max_tokens=2000)
        content = extract_chat_content(response, "CONTENT")
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-edit-slide', methods=['POST'])
def api_ai_edit_slide():
    """Compatibility: AI edit a slide"""
    data = request.json
    instruction = data.get('instruction', '') or data.get('editRequest', '') or data.get('message', '')
    slide_html = data.get('slideHtml', '') or data.get('slideContent', '') or data.get('currentSlideHtml', '')
    project_data = clean_project_data(data.get('projectData', {}))

    prompt = f"""عدّل الشريحة التالية حسب التعليمات:
التعليمات: {instruction}

الشريحة الحالية:
{slide_html}

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

أعد الشريحة بالـ HTML المعدّل."""

    try:
        response = call_zai_chat(prompt, "عدّل الشريحة.", max_tokens=4000)
        html = extract_chat_content(response, "EDIT")
        html = extract_html_from_glm({'choices': [{'message': {'content': html}}]})
        return jsonify({'success': True, 'data': {'action': 'edit', 'html': html, 'response': 'تم تعديل الشريحة ✓'}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-chat', methods=['POST'])
def api_ai_chat():
    """Compatibility: AI chat — returns data.data format expected by frontend"""
    data = request.json
    message = data.get('message', '')
    project_data = clean_project_data(data.get('projectData', {}))
    current_slide_idx = data.get('currentSlideIdx', 0)

    prompt = f"""أنت مساعد ذكي متخصص في العروض العقارية.

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

مهمتك: تعدّل شريحة العرض بناءً على طلبات المستخدم.
أعد الرد بصيغة JSON فقط:
{{"action": "edit", "slideIdx": {current_slide_idx}, "changes": {{"content": "النص الجديد للشريحة", "title": "عنوان جديد (إذا طُلب)"}}}}
إذا كان الطلب استفساراً فقط بدون تعديل، أعد:
{{"action": "reply", "response": "نص الرد"}}"""

    try:
        response = call_zai_chat(prompt, message, max_tokens=2000)
        reply = extract_chat_content(response, "CHAT")

        parsed = _extract_json_from_text(reply)
        if parsed:
            if parsed.get('action') == 'edit' and 'changes' in parsed:
                parsed.setdefault('slideIdx', current_slide_idx)
            return jsonify({'success': True, 'data': parsed})

        # Fallback: plain text reply wrapped in data format with response field
        return jsonify({'success': True, 'data': {'action': 'reply', 'response': reply}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/save-training', methods=['POST'])
def api_save_training():
    """Compatibility: Save training data (no-op)"""
    return jsonify({'success': True})


@app.route('/api/get-training', methods=['GET'])
def api_get_training():
    """Compatibility: Get training data (empty)"""
    return jsonify({'success': True, 'history': []})


@app.route('/api/edit-deck-data', methods=['POST'])
def api_edit_deck_data():
    """Compatibility: Edit deck data (pass-through)"""
    return jsonify({'success': True})


@app.route('/api/generate-bullets', methods=['POST'])
def api_generate_bullets():
    """Compatibility: Generate bullets for a slide"""
    title = request.json.get('title', '')
    project_data = clean_project_data(request.json.get('projectData', {}))

    prompt = f"اكتب 3-5 نقاط مختصرة للشريحة: {title}\n\nبيانات المشروع:\n{json.dumps(project_data, ensure_ascii=False, indent=2)}"

    try:
        response = call_zai_chat(prompt, "اكتب النقاط.", max_tokens=1000)
        content = extract_chat_content(response, "BULLETS")
        bullets = [line.strip().lstrip('•-●* ') for line in content.split('\n') if line.strip() and len(line.strip()) > 3]
        return jsonify({'success': True, 'bullets': bullets[:5]})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/organize-text', methods=['POST'])
def api_organize_text():
    """Compatibility: Organize text"""
    text = request.json.get('text', '')
    return jsonify({'success': True, 'organized': text})


@app.route('/api/generate-design', methods=['POST'])
def api_generate_design():
    """Compatibility: Generate design (use designer-generate)"""
    return api_designer_generate()


@app.route('/api/generate-design-batch', methods=['POST'])
def api_generate_design_batch():
    """Compatibility: Generate design batch"""
    return api_designer_generate()


@app.route('/api/redesign-slide', methods=['POST'])
def api_redesign_slide():
    """Compatibility: Redesign a slide"""
    return api_ai_edit_slide()


@app.route('/api/pdf-design', methods=['POST'])
def api_pdf_design():
    """Compatibility: PDF design (use export-pdf)"""
    return api_export_pdf()


@app.route('/api/pdf-design-stream', methods=['POST'])
def api_pdf_design_stream():
    """Compatibility: PDF design stream"""
    return api_export_pdf()


@app.route('/api/generate-pdf', methods=['POST'])
def api_generate_pdf():
    """Compatibility: Generate PDF"""
    return api_export_pdf()


@app.route('/api/pdf-chat', methods=['POST'])
def api_pdf_chat():
    """Compatibility: PDF chat (no-op)"""
    return jsonify({'success': True, 'reply': 'تم'})

@app.route('/api/pdf-chat/upload', methods=['POST'])
def api_pdf_chat_upload():
    """Compatibility: PDF chat upload (no-op)"""
    return jsonify({'success': True})


@app.route('/api/render-slide-image', methods=['POST'])
def api_render_slide_image():
    """Compatibility: Render slide as image (return HTML)"""
    slide_html = request.json.get('html', '')
    return jsonify({'success': True, 'html': slide_html})


@app.route('/api/designer-chat', methods=['POST'])
def api_designer_chat():
    """Designer chat: edit a specific slide via AI"""
    data = request.json
    message = data.get('message', '')
    slide_html = data.get('slideHtml', '') or data.get('currentSlideHtml', '') or ''
    slide_title = data.get('slideTitle', '') or data.get('currentSlideTitle', '') or ''

    # Build system prompt with design rules for consistency
    system_prompt = f"""{DESIGN_RULES}

مهمتك: تعدّل شريحة HTML واحدة فقط بناءً على طلبات المستخدم.

⚠️ قواعد صارمة:
- تعدّل ONLY الشريحة المقدمة في الرسالة. لا تعدّل أي شريحة أخرى.
- أعد HTML الشريحة المعدّلة كاملة في div class=\"slide\" واحد فقط.
- لا تكتب شرح أو markdown. فقط HTML.
- حافظ على الهيكل العام للشريحة (الهيدر والفوتر والموقع).
- إذا الطلب غير واضح، اسأل المستخدم بدل ما تعدّل بشكل عشوائي."""

    # Build current user message with full slide HTML
    user_msg = f"الشريحة الحالية ({slide_title}):\n\n"
    if slide_html:
        user_msg += f"{slide_html}\n\n"
    user_msg += f"الطلب: {message}"

    try:
        response = call_zai_chat(system_prompt, user_msg, max_tokens=6000)
        reply = extract_chat_content(response, "DESIGNER-CHAT")

        # Extract HTML if present
        code_match = re.search(r'```(?:html)?\s*\n?([\s\S]*?)```', reply)
        html_out = code_match.group(1).strip() if code_match else reply

        # Check if reply is HTML or plain text response
        if '<div' in html_out and 'class="slide"' in html_out:
            return jsonify({'success': True, 'data': {'action': 'update_slide', 'html': html_out, 'response': '✅ تم تحديث الشريحة بنجاح'}})
        elif '<div' in html_out:
            return jsonify({'success': True, 'data': {'action': 'update_slide', 'html': html_out, 'response': '✅ تم تحديث الشريحة بنجاح'}})
        else:
            # Plain text reply (clarification or question)
            return jsonify({'success': True, 'data': {'response': reply}})
    except Exception as e:
        print(f"[DESIGNER-CHAT ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/files', methods=['GET'])
def api_files():
    """Compatibility: List files"""
    return jsonify({'success': True, 'files': []})


@app.route('/api/project-data', methods=['GET'])
def api_project_data():
    """Compatibility: Get project data"""
    return jsonify({'success': True, 'data': {}})


@app.route('/api/generate-cover-prompt', methods=['POST'])
def api_generate_cover_prompt():
    """Compatibility: Generate detailed cover image prompt using GLM"""
    data = request.json
    project_data = clean_project_data(data.get('projectData', {}))

    project_name = project_data.get('projectName', '')
    project_type = project_data.get('projectType', 'سكني')
    location = project_data.get('location', 'السعودية')
    description = project_data.get('idea', '') or project_data.get('description', '')
    features = project_data.get('projectFeatures', [])
    features_text = ', '.join(features) if isinstance(features, list) else str(features)

    glm_prompt = f"""أنت متخصص في كتابة prompts لتصوير معماري احترافي.

بيانات المشروع:
- الاسم: {project_name}
- النوع: {project_type}
- الموقع: {location}
- الوصف: {description}
- المميزات: {features_text}

اكتب prompt واحد بالإنجليزي لتصوير غلاف هذا العرض التقديمي.
المطلوب:
- وصف دقيق للمبنى بناءً على نوعه وموقعه
- أسلوب تصوير معماري احترافي
- إضاءة طبيعية أو مسائية جذابة
- زاوية تصوير تُبرز فخامة المشروع
- بدون أي نصوص أو علامات مائية
- بدون أشخاص
- جودة عالية جداً

اكتب فقط البرومبت بدون أي شرح."""

    try:
        response = call_zai_chat(glm_prompt, "اكتب البرومبت.", max_tokens=500)
        prompt = extract_chat_content(response, "COVER-PROMPT").strip()

        # Clean up the prompt
        prompt = prompt.strip('"').strip("'")
        if prompt.startswith('Prompt:') or prompt.startswith('prompt:'):
            prompt = prompt.split(':', 1)[1].strip()

        print(f"[COVER PROMPT] Generated: {prompt[:100]}...")
        return jsonify({'success': True, 'prompt': prompt})

    except Exception as e:
        # Fallback to basic prompt
        fallback = f"Professional architectural photography of a modern luxury {project_type} building in {location}, {project_name}. Elegant contemporary design with premium finishes, glass facade, warm golden hour lighting, landscaped surroundings. Shot from a low angle to emphasize grandeur. High resolution, no text, no watermarks, no people."
        print(f"[COVER PROMPT] GLM failed, using fallback: {str(e)}")
        return jsonify({'success': True, 'prompt': fallback})





# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Static Files + Health
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

@app.route('/outputs/<path:path>')
def serve_output(path):
    return send_from_directory('outputs', path)

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'model': GLM_MODEL, 'image_model': IMAGE_MODEL})

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == '__main__':
    print("=" * 60)
    print("  Real Estate Proposal Generator - GLM-First Architecture")
    print("=" * 60)
    print(f"  GLM Model: {GLM_MODEL}")
    print(f"  Image Model: {IMAGE_MODEL}")
    print(f"  Output Dir: {OUTPUT_DIR}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
