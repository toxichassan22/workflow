import os
import sys
import json
import time
import re
import base64
import requests
import sqlite3
import uuid as _uuid
import concurrent.futures
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, send_from_directory, g

load_dotenv()

import db
import auth
import maps_service
from auth import require_auth, require_admin, require_company_admin, require_permission, hash_password, verify_password, create_token, decode_token
from design_templates import get_all_templates, get_template, apply_template_colors, build_design_rules

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
app.teardown_appcontext(db.close_db)

# Initialize database on startup
db.init_db()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZAI_KEY = os.environ.get("ZAI_KEY")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
ZAI_BASE = 'https://api.z.ai/api/paas/v4'
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
GLM_MODEL = "glm-5.1"
GLM_OPENROUTER_MODEL = "z-ai/glm-5.1"
GLM_USE_OPENROUTER = os.environ.get("GLM_USE_OPENROUTER", "false").lower() in ("1", "true", "yes")
# Prefer ZAI when its key is loaded; require explicit FORCE_OPENROUTER=1 to keep OpenRouter.
if ZAI_KEY and OPENROUTER_KEY and GLM_USE_OPENROUTER and os.environ.get("FORCE_OPENROUTER", "false").lower() not in ("1", "true", "yes"):
    GLM_USE_OPENROUTER = False
    print("[CONFIG] Both keys found; preferring ZAI for GLM calls. Set FORCE_OPENROUTER=1 to override.")
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY')
print(f"[CONFIG] ZAI_KEY: {'SET' if ZAI_KEY else 'MISSING'}")
print(f"[CONFIG] OPENROUTER_KEY: {'SET' if OPENROUTER_KEY else 'MISSING'}")
print(f"[CONFIG] GLM_USE_OPENROUTER: {GLM_USE_OPENROUTER}")
print(f"[CONFIG] GOOGLE_MAPS_API_KEY: {'SET' if GOOGLE_MAPS_API_KEY else 'MISSING'}")
print(f"[CONFIG] JWT_SECRET: {auth.JWT_SECRET_SOURCE.upper()}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Call GLM (ZAI API or OpenRouter fallback)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def call_zai_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000):
    if GLM_USE_OPENROUTER:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Real Estate Proposal Generator"
        }
        payload = {
            "model": GLM_OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=300)
    else:
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
        print(f"[GLM ERROR] Status {response.status_code}: {json.dumps(data['error'], ensure_ascii=False)}")
    return data


def call_zai_chat_parallel(system_prompt, user_content, temperature=0.7, max_tokens=8000, attempts=2):
    """
    Race multiple identical GLM calls in parallel and return the first valid response.
    Helps when a single model invocation is slow or returns malformed/empty content.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _attempt():
        try:
            resp = call_zai_chat(system_prompt, user_content, temperature, max_tokens)
            if 'error' in resp:
                return None
            choices = resp.get('choices')
            if not choices:
                return None
            content = choices[0].get('message', {}).get('content', '')
            if not content:
                return None
            return resp
        except Exception as e:
            print(f"[GLM PARALLEL] attempt failed: {e}")
            return None

    with ThreadPoolExecutor(max_workers=attempts) as executor:
        futures = [executor.submit(_attempt) for _ in range(attempts)]
        for future in as_completed(futures):
            result = future.result()
            if result:
                print(f"[GLM PARALLEL] Valid response received after racing {attempts} calls")
                return result

    raise Exception(f"All {attempts} parallel GLM attempts failed")


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
def generate_pdf_with_playwright(html, project_name, branding=None, output_dir=None):
    from exports.pdf_export import generate_pdf
    return generate_pdf(html, project_name, branding, output_dir or OUTPUT_DIR)

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
    {'num': 1,  'title': 'شريحة الغلاف',     'type': 'cover',     'desc': 'cover: خلفية صورة الغلاف ##IMAGE_COVER## بكامل الشريحة. طبقة شفافة بلون رئيسي داكن بنسبة opacity:0.65. شعار ##LOGO## height:80px في المنتصف. اسم المشروع أبيض font-size:48px. وصف بلون مميز (accent) font-size:20px. خطوط هندسية زخرفية بلون مميز. بدون هيدر/فوتر.'},
    {'num': 2,  'title': 'الفهرس',            'type': 'index',     'desc': 'index: عناوين الشرائح 1-16 في جدول فهرس احترافي عمودين. رقم كل شريحة في دائرة باللون الرئيسي. خلفية بلون الخلفية المعتمد. ⚠️ هيدر إلزامي في الأعلى (شعار ##LOGO## + خط رأسي مميز + عنوان الشريحة). ⚠️ فوتر إلزامي في الأسفل (اسم المشروع + رقم الشريحة في دائرة بلون مميز). ⛔ ممنوع إطلاقاً: أي صور أو base64 أو روابط صور. النص فقط + أرقام الشرائح في دوائر.'},
    {'num': 3,  'title': 'الملخص التنفيذي',    'type': 'content',   'desc': 'content: Dashboard مالي — بطاقات كرتونية كبيرة: إجمالي التكلفة، الإيرادات السنوية، إجمالي الأرباح (الأكبر بصرياً)، ROI %، NOI، مدة الاسترداد. الأرقام بخط كبير 32-48px باللون الرئيسي. بدون صور.'},
    {'num': 4,  'title': 'الرؤية والفكرة',     'type': 'content',   'desc': 'content: نص تعريفي عن المشروع + بطاقات للمكونات الرئيسية مع أيقونات Unicode. يمكنك استخدام ##MOODBOARD_IMAGE_1## كخلفية شفافة opacity:0.15.'},
    {'num': 5,  'title': 'الموقع الاستراتيجي', 'type': 'content',   'desc': 'content: بطاقات مميزات الموقع (القرب من الخدمات، الوصول، المدينة) مع أيقونات. يمكنك استخدام ##MOODBOARD_IMAGE_2## كخلفية شفافة opacity:0.15.'},
    {'num': 6,  'title': 'مميزات المشروع',     'type': 'content',   'desc': 'content: Grid 2×3 من البطاقات الفاخرة: كل بطاقة فيها أيقونة Unicode كبيرة + عنوان bold + وصف قصير. خلفية كل بطاقة بيضاء مع border بلون مميز رفيع. بدون صور.'},
    {'num': 7,  'title': 'مكونات المشروع',     'type': 'content',   'desc': 'content: جدول احترافي: header باللون الرئيسي وأبيض، صفوف متبادلة بلون خلفية خفيف وأبيض، صف الإجمالي بارز. أسفل الجدول 3 بطاقات ملخص. بدون صور.'},
    {'num': 8,  'title': 'افتراضات الربح التشغيلي', 'type': 'content', 'desc': 'content: معادلة بصرية كبيرة: (إيرادات سنوية − مصاريف سنوية = صافي ربح). كل عنصر في بطاقة مع سهم يربطها. أرقام بخط كبير باللون الرئيسي. بدون صور.'},
    {'num': 9,  'title': 'افتراضات التكاليف',  'type': 'content',   'desc': 'content: 3 بطاقات كبيرة: بطاقة تكلفة الأرض (مع تفاصيل السعر/م²)، بطاقة تكلفة التطوير، بطاقة الإجمالي (الأكبر والأبرز). بدون صور.'},
    {'num': 10, 'title': 'الأرباح والتخارج',   'type': 'content',   'desc': 'content: Flow diagram أفقي: بطاقة ربح تشغيلي → علامة + → بطاقة قيمة التخارج → علامة = → بطاقة إجمالي الأرباح (الأكبر). يمكنك استخدام ##MOODBOARD_IMAGE_3## كخلفية شفافة opacity:0.1.'},
    {'num': 11, 'title': 'المؤشرات المالية',   'type': 'content',   'desc': 'content: أعلى الشريحة 3 بطاقات كبيرة: ROI % و NOI و مدة الاسترداد. أسفلها مقارنة بصرية: شريطين أفقيين (إجمالي التكلفة vs إجمالي الأرباح). بدون صور.'},
    {'num': 12, 'title': 'الجدول الزمني',      'type': 'content',   'desc': 'content: Timeline أفقي: خط رأسي في المنتصف، نقاط على الخط لكل مرحلة، أشرطة ملونة باللون الرئيسي واللون المميز. Years والأرباع Q1-Q4 في الأعلى. بدون صور.'},
    {'num': 13, 'title': 'فرص الاستثمار',      'type': 'content',   'desc': 'content: 3-4 بطاقات High-Impact: عنوان bold + وصف + أيقونة Unicode كبيرة. يمكنك استخدام ##MOODBOARD_IMAGE_4## كخلفية شفافة opacity:0.1.'},
    {'num': 14, 'title': 'المخاطر والافتراضات', 'type': 'content',  'desc': 'content: بطاقات رمادية وبيج هادئة + أيقونة ⚠️ خطية باللون الرئيسي. عنوان فرعي: نقاط يجب التحقق منها. بدون أي صور إطلاقاً.'},
    {'num': 15, 'title': 'المود بورد',         'type': 'moodboard', 'desc': 'moodboard: Grid 2×2 يشغل المساحة بين top:56px و bottom:36px. كل خلية فيها صورة واحدة: ##MOODBOARD_IMAGE_1## و ##MOODBOARD_IMAGE_2## و ##MOODBOARD_IMAGE_3## و ##MOODBOARD_IMAGE_4##. كل صورة بـ background-size:cover;background-position:center. فواصل رفيعة 4px بين الخلايا.'},
    {'num': 16, 'title': 'الختام',             'type': 'closing',   'desc': 'closing: خلفية بلون رئيسي داكن gradient linear-gradient(135deg, [اللون الرئيسي], [اللون الرئيسي الداكن/الثانوي]) تملأ الشريحة. شعار ##LOGO## height:80px في المنتصف. "شكراً لكم" أبيض 48px. اسم المشروع باللون المميز. بيانات التواصل. بدون هيدر/فوتر.'},
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

    # Map image placeholders (populated when project has location data)
    map_placeholders = {
        '##MAP_OVERVIEW##': 'خريطة الموقع العامة',
        '##MAP_LANDMARKS##': 'خريطة المعالم المحيطة',
        '##MAP_ACCESS##': 'خريطة الوصول والطرق',
        '##MAP_CATCHMENT##': 'خريطة نطاق التأثير',
        '##STREET_VIEW_1##': 'صورة الموقع 1',
        '##STREET_VIEW_2##': 'صورة الموقع 2',
        '##STREET_VIEW_3##': 'صورة الموقع 3',
        '##STREET_VIEW_4##': 'صورة الموقع 4',
    }
    if isinstance(images, dict) and images.get('map_placeholders'):
        for placeholder, path in images['map_placeholders'].items():
            if path:
                label = map_placeholders.get(placeholder, placeholder)
                info += f"- {label}: {placeholder}\n"
    return info

def build_system_prompt(project_data, images_info, design_rules=None):
    """Build the shared system prompt ONCE for all slides (~3K chars)."""
    if design_rules is None:
        design_rules = DESIGN_RULES
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)
    # Truncate project data if too long to keep system prompt compact
    if len(project_json) > 4000:
        project_json = project_json[:4000] + '\n... [تم اختصار البيانات]'
    return f"""{design_rules}

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

def postprocess_slide(html, slide_num, tenant_id=None):
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

        primary = '#7A0C0C'
        accent = '#C4A35A'
        company_name = 'منافع الاقتصادية للعقار'

        if tenant_id:
            branding = db.get_branding(tenant_id) or {}
            primary = branding.get('primary_color') or primary
            accent = branding.get('accent_color') or accent
            company_name = branding.get('company_name')
            if not company_name:
                tenant = db.get_tenant(tenant_id)
                company_name = tenant.get('company_name') if tenant else 'منافع الاقتصادية للعقار'
            if not company_name:
                company_name = 'منافع الاقتصادية للعقار'

        if not has_header:
            header_html = (
                f'<div style="position:absolute;top:0;right:0;left:0;height:56px;background:#fff;border-bottom:2px solid {primary};display:flex;align-items:center;padding:0 20px;z-index:10;">'
                '<img src="##LOGO##" style="height:40px;margin-right:12px;" />'
                f'<div style="width:3px;height:28px;background:{accent};margin:0 12px;"></div>'
                f'<span style="font-size:16px;font-weight:600;color:{primary};">{slide_title}</span>'
                '</div>'
            )
            html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1\n' + header_html, html, count=1)
            print(f"[POST] Injected header into slide {slide_num}")

        if not has_footer:
            footer_html = (
                f'<div style="position:absolute;bottom:0;right:0;left:0;height:36px;background:{primary};display:flex;align-items:center;padding:0 16px;z-index:10;">'
                f'<span style="font-size:13px;color:#fff;">{slide_title}</span>'
                f'<span style="font-size:13px;color:rgba(255,255,255,0.7);margin-right:auto;margin-left:8px;">{company_name}</span>'
                f'<div style="width:24px;height:24px;border-radius:50%;background:{accent};color:{primary};font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center;">{slide_num}</div>'
                '</div>'
            )
            html = re.sub(r'(</div>\s*)$', '\n' + footer_html + r'\1', html, count=1)
            print(f"[POST] Injected footer into slide {slide_num}")

    logo_url = '/assets/logo.png'
    if tenant_id:
        branding = db.get_branding(tenant_id) or {}
        if branding.get('logo_path'):
            logo_url = branding['logo_path']
    html = html.replace('##LOGO##', logo_url)
    return html

def generate_single_slide(system_prompt, slide_num, tenant_id=None, max_retries=2):
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
            html = postprocess_slide(html, slide_num, tenant_id)
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
    
    # Resolve dynamic brand rules if tenant context is available
    tenant_id = getattr(g, 'tenant_id', None)
    branding = db.get_branding(tenant_id) if tenant_id else {}
    dynamic_rules = build_design_rules(branding)
    
    sys_prompt = build_system_prompt(project_data, images_info, dynamic_rules)
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

        slide_count = html.count('class="slide"')
        print(f"[GENERATE] Final HTML: {len(html)} chars, {slide_count} slides")
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
    include_cover = data.get('includeCover', True) is not False

    project_name = project_data.get('project_name') or project_data.get('projectName') or 'مشروع'
    project_type = project_data.get('project_type') or project_data.get('projectType') or 'سكني'
    location = project_data.get('location_address') or project_data.get('location') or 'السعودية'

    print(f"\n[IMAGES] Generating {'5' if include_cover else '4'} images for: {project_name}")

    images = {'cover': None, 'moodboard': []}

    # 1. Cover image. The wizard requests moodboard-only images at its next step.
    if include_cover:
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
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    project_name = project_data.get('project_name') or project_data.get('projectName') or 'real-estate project'
    project_type = project_data.get('project_type') or project_data.get('projectType') or 'residential project'
    location = project_data.get('location_address') or project_data.get('location') or 'Saudi Arabia'
    description = project_data.get('project_description') or project_data.get('description') or ''
    prompt = data.get('prompt', '').strip()
    if not prompt:
        prompt = (
            f"Premium architectural hero image for {project_name}, a {project_type} in {location}. "
            f"{description} Modern luxury real-estate photography, elegant materials, cinematic natural light, "
            "no people, no text, no logos, no watermark, 16:9 composition."
        )
    reference = data.get('referenceImage')
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
@require_auth
def api_designer_generate():
    """Generate slides HTML: 16 individual slides in parallel (4 concurrent workers)."""
    project_data = clean_project_data(request.json.get('projectData', {}))
    outline = request.json.get('outline', [])
    images = request.json.get('images', {})
    images_info = _get_images_info(images)

    # Build system prompt ONCE — shared across all 16 slides
    branding = db.get_branding(g.tenant_id) or {}
    dynamic_rules = build_design_rules(branding)
    system_prompt = build_system_prompt(project_data, images_info, dynamic_rules)
    print(f"\n[DESIGNER] Starting 16-slide parallel generation (4 workers)...")
    print(f"[DESIGNER] System prompt: {len(system_prompt)} chars (shared)")
    start_time = time.time()

    try:
        # Run all 16 slides in parallel with 4 concurrent workers
        results = [None] * 16
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_idx = {}
            for i in range(16):
                future = executor.submit(generate_single_slide, system_prompt, i + 1, g.tenant_id)
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
    presentation_id = data.get('presentationId')

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
        
        # Post-process and resolve placeholders
        from auth import get_optional_tenant_id
        tenant_id = get_optional_tenant_id() or 'default'
        # Default to slide 2 postprocessing logic to inject header/footer if missing
        html = postprocess_slide(html, 2, tenant_id)
        html = resolve_designer_chat_placeholders(html, project_data, presentation_id, tenant_id)
        
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
def api_save_training_compat():
    """Compatibility: Save training data (no-op)"""
    return jsonify({'success': True})


@app.route('/api/get-training', methods=['GET'])
def api_get_training_compat():
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


def resolve_designer_chat_placeholders(html_out, project_data, presentation_id, tenant_id):
    """Resolve map and creative image placeholders to their actual URLs."""
    if not html_out or '<div' not in html_out:
        return html_out

    # 1. Gather all map placeholders
    map_placeholders = {}
    
    # Try to load existing map image records from db
    db_maps = []
    if presentation_id:
        db_maps = db.get_map_images(tenant_id, presentation_id=presentation_id)
    if not db_maps:
        db_maps = db.get_map_images(tenant_id)
        
    for m in db_maps:
        placeholder = m.get('placeholder')
        path = m.get('file_path')
        if placeholder and path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            if placeholder not in map_placeholders:
                map_placeholders[placeholder] = f"/{rel_path}"
                
    # If some maps are missing and we have coordinates, generate/ensure them
    def extract_coord(val):
        if val is None: return None
        try: return float(val)
        except: return None
        
    lat = extract_coord(project_data.get('location_lat'))
    lng = extract_coord(project_data.get('location_lng'))
    if lat is not None and lng is not None:
        needed = ['##MAP_OVERVIEW##', '##MAP_LANDMARKS##', '##MAP_ACCESS##', '##MAP_CATCHMENT##']
        if not map_placeholders or any(p not in map_placeholders for p in needed):
            try:
                map_result = maps_service.generate_all_map_images(project_data, tenant_id, presentation_id=presentation_id)
                if map_result.get('placeholders'):
                    for placeholder, path in map_result['placeholders'].items():
                        if path and os.path.exists(path):
                            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
                            map_placeholders[placeholder] = f"/{rel_path}"
            except Exception as ge:
                print(f"[DESIGNER-CHAT MAP GEN ERROR] {ge}")

    # 2. Replace map placeholders in HTML
    for placeholder, url in map_placeholders.items():
        if url:
            html_out = html_out.replace(placeholder, url)

    # 3. Replace creative image placeholders (cover & moodboard)
    cover_url = project_data.get('cover') or project_data.get('mainImageData') or ''
    moodboard = project_data.get('moodboard') or project_data.get('moodboardImages') or []
    
    if cover_url:
        html_out = html_out.replace('##IMAGE_COVER##', cover_url)
        html_out = html_out.replace('##COVER_IMAGE##', cover_url)
        html_out = html_out.replace('##MAIN_IMAGE##', cover_url)
        
    if isinstance(moodboard, list):
        for idx, mb_img in enumerate(moodboard):
            if mb_img:
                html_out = html_out.replace(f'##MOODBOARD_IMAGE_{idx + 1}##', mb_img)
                
    return html_out


@app.route('/api/designer-chat', methods=['POST'])
@require_auth
def api_designer_chat():
    """Designer chat: edit a specific slide via AI"""
    data = request.json
    message = data.get('message', '')
    slide_html = data.get('slideHtml', '') or data.get('currentSlideHtml', '') or ''
    slide_title = data.get('slideTitle', '') or data.get('currentSlideTitle', '') or ''
    slide_index = data.get('slideIndex')
    
    # Extract project_data and presentation_id
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = data.get('presentationId')
    
    # If project_data is empty but presentation_id is provided, try loading from db
    if not project_data and presentation_id:
        pres = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if pres and pres.get('project_data'):
            try:
                project_data = clean_project_data(json.loads(pres['project_data']))
            except Exception:
                pass

    # Build system prompt with design rules for consistency
    branding = db.get_branding(g.tenant_id) or {}
    dynamic_rules = build_design_rules(branding)
    print(f"\n[DEBUG DESIGNER CHAT] tenant_id: {g.tenant_id}")
    print(f"[DEBUG DESIGNER CHAT] branding: {branding}")
    print(f"[DEBUG DESIGNER CHAT] dynamic_rules:\n{dynamic_rules}\n")
    system_prompt = f"""{dynamic_rules}

مهمتك: تعديل شريحة HTML واحدة فقط بناءً على طلب المستخدم، أو الرد على استفساراته.

قواعد الاستجابة:
يجب أن تكون إجابتك بصيغة JSON صالحة تحتوي على حقلين:
1. "html": كود HTML الكامل للشريحة المعدلة داخل div class="slide" (أو قيمة null إذا لم يكن هناك تعديل أو تغيير في الشريحة).
2. "response": رسالة ودية وذكية باللغة العربية تشرح فيها ما قمت بتعديله بالتفصيل، أو تسأل المستخدم لتوضيح طلبه إذا كان غامضاً، أو تجيب على سؤاله.

مثال للاستجابة:
{{
  "html": "<div class=\"slide\">...</div>",
  "response": "لقد قمت بتغيير ألوان الشريحة لتطابق هوية الشركة، وتكبير حجم الخط للعناوين الرئيسية لتسهيل القراءة."
}}

⚠️ قواعد صارمة:
- لا تضف أي نص خارج كتلة الـ JSON.
- يجب أن يبدأ ردك بـ {{ وينتهي بـ }}.
- حافظ دائماً على هوية وألوان الشركة والخطوط المحددة في قواعد التصميم.
- لا تضف أي صور خارجية إلا إذا كانت من الصور المتاحة للمشروع.
"""

    # Build current user message with full slide HTML
    user_msg = f"الشريحة الحالية ({slide_title}):\n\n"
    if slide_html:
        user_msg += f"{slide_html}\n\n"
    user_msg += f"الطلب: {message}"
    print(f"[DEBUG DESIGNER CHAT] user_msg:\n{user_msg}\n")

    try:
        response = call_zai_chat(system_prompt, user_msg, max_tokens=6000)
        print(f"[DEBUG DESIGNER CHAT] raw response:\n{response}\n")
        reply = extract_chat_content(response, "DESIGNER-CHAT").strip()
        print(f"[DEBUG DESIGNER CHAT] reply content:\n{reply}\n")

        # Try to parse as JSON
        html_out = None
        assistant_response = ""
        
        # Clean potential markdown JSON wrappers
        json_clean = reply
        if json_clean.startswith("```json"):
            json_clean = json_clean[7:]
        elif json_clean.startswith("```"):
            json_clean = json_clean[3:]
        if json_clean.endswith("```"):
            json_clean = json_clean[:-3]
        json_clean = json_clean.strip()
        
        try:
            parsed = json.loads(json_clean)
            html_out = parsed.get('html')
            assistant_response = parsed.get('response', '')
        except Exception:
            # Fallback if LLM didn't return valid JSON
            # Let's search for JSON-like block
            match = re.search(r'\{[\s\S]*\}', reply)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                    html_out = parsed.get('html')
                    assistant_response = parsed.get('response', '')
                except Exception:
                    pass
            
            if not assistant_response:
                # If everything fails, treat the whole response as plain text response
                # unless we detect HTML, in which case extract HTML
                if '<div' in reply:
                    code_match = re.search(r'```(?:html)?\s*\n?([\s\S]*?)```', reply)
                    html_out = code_match.group(1).strip() if code_match else reply
                    assistant_response = "✅ تم تحديث الشريحة بنجاح"
                else:
                    html_out = None
                    assistant_response = reply

        # Post-process HTML if present
        if html_out and '<div' in html_out:
            if slide_index is not None:
                try:
                    slide_num = int(slide_index) + 1
                    html_out = postprocess_slide(html_out, slide_num, g.tenant_id)
                    # Resolve placeholders (maps, cover, moodboard)
                    html_out = resolve_designer_chat_placeholders(html_out, project_data, presentation_id, g.tenant_id)
                except Exception as pe:
                    print(f"[DESIGNER-CHAT POSTPROCESS ERROR] {str(pe)}")
            
            return jsonify({
                'success': True,
                'data': {
                    'action': 'update_slide',
                    'html': html_out,
                    'response': assistant_response or '✅ تم تحديث الشريحة بنجاح'
                }
            })
        else:
            return jsonify({
                'success': True,
                'data': {
                    'action': 'chat_only',
                    'response': assistant_response or reply
                }
            })
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
# BRANDING ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/branding', methods=['GET'])
@require_auth
def api_get_branding():
    """Get branding settings for the current tenant."""
    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not found'}), 404
    return jsonify({'success': True, 'branding': branding})


@app.route('/api/branding', methods=['PUT'])
@require_permission('company_settings')
def api_update_branding():
    """Update branding settings for the current tenant."""
    data = request.json or {}
    db.update_branding(g.tenant_id, **data)
    branding = db.get_branding(g.tenant_id)
    return jsonify({'success': True, 'branding': branding})


@app.route('/api/branding/template', methods=['POST'])
@require_permission('company_settings')
def api_apply_template():
    """Apply a design template — auto-fills colors and settings."""
    data = request.json or {}
    template_key = data.get('template')
    template = get_template(template_key)
    if not template:
        return jsonify({'error': 'Invalid template'}), 400

    colors = apply_template_colors(template_key)
    updates = {
        'design_template': template_key,
        'card_style': template['card_style'],
    }
    if colors:
        updates.update(colors)

    db.update_branding(g.tenant_id, **updates)
    branding = db.get_branding(g.tenant_id)
    return jsonify({'success': True, 'branding': branding})


@app.route('/api/design-templates', methods=['GET'])
def api_design_templates():
    """List all available design templates (public, no auth needed)."""
    return jsonify({'success': True, 'templates': get_all_templates()})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INPUT FIELDS ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/fields', methods=['GET'])
@require_auth
def api_get_fields():
    """Get all input fields for the current tenant."""
    active_only = request.args.get('all') != '1'
    fields = db.get_fields(g.tenant_id, active_only=active_only)
    result = []
    for f in fields:
        result.append({
            'id': f['id'],
            'fieldKey': f['field_key'],
            'fieldLabel': f['field_label'],
            'fieldType': f['field_type'],
            'fieldOptions': json.loads(f['field_options']) if f.get('field_options') else None,
            'sectionKey': f.get('section_key', 'general'),
            'isRequired': bool(f['is_required']),
            'isActive': bool(f['is_active']),
            'isCustom': bool(f['is_custom']),
            'sortOrder': f['sort_order'],
            'placeholder': f.get('placeholder'),
            'defaultValue': f.get('default_value'),
            'aiHint': f.get('ai_hint'),
        })
    return jsonify({'success': True, 'fields': result})


@app.route('/api/fields', methods=['POST'])
@require_permission('custom_fields')
def api_add_field():
    """Add a custom input field."""
    data = request.json or {}
    field_label = (data.get('fieldLabel') or '').strip()
    field_type = data.get('fieldType', 'text')

    if not field_label:
        return jsonify({'error': 'fieldLabel is required'}), 400

    # Auto-generate field_key from label if not provided
    field_key = (data.get('fieldKey') or '').strip()
    if not field_key:
        import re as _re
        # Try transliteration of common Arabic patterns, fallback to field_N
        # Map common Arabic letters to approximate English
        ar_map = {
            'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
            'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
            'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
            'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
            'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
            ' ': '_', 'ـ': '',
        }
        transliterated = ''
        for ch in field_label:
            transliterated += ar_map.get(ch, ch)
        # Clean: lowercase, replace non-alphanumeric with _, strip leading/trailing _
        field_key = _re.sub(r'[^a-zA-Z0-9_]', '_', transliterated.lower()).strip('_')
        if not field_key:
            field_key = f'field_{uuid.uuid4().hex[:6]}'

    valid_types = ['text', 'number', 'textarea', 'select', 'date', 'image']
    if field_type not in valid_types:
        return jsonify({'error': f'Invalid fieldType. Must be one of: {valid_types}'}), 400

    field_id = db.add_custom_field(
        tenant_id=g.tenant_id,
        field_key=field_key,
        field_label=field_label,
        field_type=field_type,
        field_options=data.get('fieldOptions'),
        is_required=data.get('isRequired', False),
        placeholder=data.get('placeholder'),
        default_value=data.get('defaultValue'),
        ai_hint=data.get('aiHint'),
        sort_order=data.get('sortOrder', 100),
        section_key=data.get('sectionKey', 'general'),
    )
    return jsonify({'success': True, 'fieldId': field_id}), 201


@app.route('/api/fields/<field_id>', methods=['PUT'])
@require_permission('custom_fields')
def api_update_field(field_id):
    """Update an input field."""
    field = db.get_field_by_id(field_id)
    if not field or field['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'Field not found'}), 404

    data = request.json or {}
    updates = {}
    for k in ['fieldKey', 'fieldLabel', 'fieldType', 'fieldOptions', 'sectionKey', 'isRequired', 'isActive', 'sortOrder', 'placeholder', 'defaultValue', 'aiHint']:
        if k in data:
            db_key = {
                'fieldKey': 'field_key', 'fieldLabel': 'field_label', 'fieldType': 'field_type',
                'fieldOptions': 'field_options', 'sectionKey': 'section_key', 'isRequired': 'is_required',
                'isActive': 'is_active', 'sortOrder': 'sort_order', 'defaultValue': 'default_value',
                'aiHint': 'ai_hint',
            }.get(k, k)
            updates[db_key] = data[k]

    db.update_field(field_id, **updates)
    return jsonify({'success': True})


@app.route('/api/fields/<field_id>', methods=['DELETE'])
@require_permission('custom_fields')
def api_delete_field(field_id):
    """Delete an input field."""
    field = db.get_field_by_id(field_id)
    if not field or field['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'Field not found'}), 404
    db.delete_field(field_id)
    return jsonify({'success': True})


@app.route('/api/fields/<field_id>/toggle', methods=['POST'])
@require_permission('custom_fields')
def api_toggle_field(field_id):
    """Toggle active/inactive state of a field."""
    field = db.get_field_by_id(field_id)
    if not field or field['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'Field not found'}), 404
    new_state = 0 if field['is_active'] else 1
    db.update_field(field_id, is_active=new_state)
    return jsonify({'success': True, 'isActive': bool(new_state)})


@app.route('/api/fields/reorder', methods=['PUT'])
@require_permission('custom_fields')
def api_reorder_fields():
    """Reorder fields. Expects: {fieldIds: ['id1', 'id2', ...]}"""
    data = request.json or {}
    field_ids = data.get('fieldIds', [])
    if not isinstance(field_ids, list):
        return jsonify({'error': 'fieldIds must be a list'}), 400

    if not db.reorder_fields(g.tenant_id, field_ids):
        return jsonify({'error': 'One or more fields do not belong to this company'}), 403
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI INPUT BUILDER
# يقترح AI حقول الإدخال المناسبة للشركة بناءً على وصف المشروع + بيانات التدريب
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_ai_fields_json(text):
    """Extract the first JSON array from LLM text."""
    # Try code block first
    cb = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if cb:
        try:
            parsed = json.loads(cb.group(1).strip())
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    # Try balanced bracket scan for array
    start = text.find('[')
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
                if c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i+1])
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
    # Fallback: whole text
    try:
        parsed = json.loads(text.strip())
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return []


@app.route('/api/ai-input-builder', methods=['POST'])
@require_permission('custom_fields')
def api_ai_input_builder():
    """
    AI suggests input fields for a project based on tenant training context.
    Input: { description: 'مشروع سكني في الرياض...', existingKeys: ['project_name'] }
    Output: { suggestions: [{ fieldKey, fieldLabel, fieldType, sectionKey, fieldOptions, isRequired, placeholder, defaultValue, aiHint, reason }] }
    """
    data = request.json or {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'description is required'}), 400

    existing = db.get_fields(g.tenant_id, active_only=False)
    existing_keys = [f['field_key'] for f in existing] + (data.get('existingKeys') or [])
    training_context = db.get_training_context(g.tenant_id) or ''
    section_keys = [s['key'] for s in db.FIELD_SECTIONS]

    system_prompt = """أنت مساعد ذكي لمنصة توليد عروض تقديمية عقارية. مهمتك اقتراح حقول إدخال (input fields) مناسبة لمشروع عقاري معيّن بناءً على:
- وصف المشروع.
- نوع الشركة وطبيعة أعمالها (من بيانات التدريب).
- أفضل الممارسات لعروض الاستثمار العقاري.

أعد الرد كـ JSON array فقط، بدون أي شرح إضافي. كل عنصر يمثل حقل إدخال واحد."""

    user_prompt = f"""اقترح حقول إدخال للمشروع التالي:

{description}

البيانات التدريبية الخاصة بالشركة:
{training_context[:2000] if training_context else 'لا يوجد تدريب خاص بالشركة بعد.'}

الحقول الموجودة حالياً (لا تكررها): {', '.join(existing_keys) if existing_keys else 'لا يوجد حقول'}

الأنواع المسموح بها فقط: text, textarea, number, select, date, image.
الأقسام المسموح بها فقط: {', '.join(section_keys)} (أو general إذا لم ينطبق).

المخرجات المطلوبة: JSON array فقط. كل عنصر به هذه المفاتيح:
- fieldKey: مفتاح إنجليزي صغير بدون مسافات (snake_case).
- fieldLabel: اسم الحقل بالعربي.
- fieldType: أحد الأنواع المسموح بها.
- sectionKey: أحد الأقسام المسموح بها.
- fieldOptions: array من strings (إذا كان fieldType = select)، وإلا null.
- isRequired: true/false.
- placeholder: نص توضيحي داخل الحقل (اختياري).
- defaultValue: قيمة افتراضية (اختياري).
- aiHint: توجيه للـ AI عند توليد الشرائح (اختياري).
- reason: جملة قصيرة تبرر لماذا هذا الحقل مهم.

قواعد:
- لا تُرجع أكثر من 8 حقول (لضمان جودة الرد بدون قطع).
- اجعل الرد مدمجاً: لا تكرر الوصف الطويل، واستخدم قيم قصيرة.
- ركّز على حقول تؤثر في العرض التقديمي المالي والتسويقي.
- تجنب الحقول العامة مثل "اسم المشروع" إذا كان موجوداً بالفعل.
- fieldKey يجب أن يكون فريداً وsnake_case.
"""

    try:
        response = call_zai_chat(system_prompt, user_prompt, temperature=0.7, max_tokens=4000)
        content = extract_chat_content(response, "AI-INPUT-BUILDER")
        suggestions = _parse_ai_fields_json(content)

        valid_types = {'text', 'textarea', 'number', 'select', 'date', 'image'}
        valid_sections = set(section_keys) | {'general'}
        cleaned = []
        seen_keys = set()
        for s in suggestions:
            if not isinstance(s, dict):
                continue
            key = re.sub(r'[^a-z0-9_]', '_', (s.get('fieldKey') or '').strip().lower()).strip('_')
            if not key or key in seen_keys or key in existing_keys:
                continue
            seen_keys.add(key)
            ftype = s.get('fieldType', 'text')
            if ftype not in valid_types:
                ftype = 'text'
            section = s.get('sectionKey', 'general')
            if section not in valid_sections:
                section = 'general'
            opts = s.get('fieldOptions') if isinstance(s.get('fieldOptions'), list) else None
            cleaned.append({
                'fieldKey': key,
                'fieldLabel': (s.get('fieldLabel') or key).strip(),
                'fieldType': ftype,
                'sectionKey': section,
                'fieldOptions': opts,
                'isRequired': bool(s.get('isRequired')),
                'placeholder': str(s.get('placeholder') or '').strip(),
                'defaultValue': str(s.get('defaultValue') or '').strip(),
                'aiHint': str(s.get('aiHint') or s.get('reason') or '').strip(),
                'reason': str(s.get('reason') or '').strip(),
            })

        return jsonify({'success': True, 'suggestions': cleaned})
    except Exception as e:
        print(f"[AI-INPUT-BUILDER ERROR] {e}")
        return jsonify({'error': str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SLIDE PLAN & GENERATION ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from slide_engine import (
    build_slide_plan_prompt, parse_slide_plan, validate_slide_plan,
    generate_all_slides, extract_html_from_glm, CONTENT_DISTRIBUTION_RULES
)


@app.route('/api/slide-plan', methods=['POST'])
@require_permission('create_presentation')
def api_slide_plan():
    """
    AI analyzes project data and proposes a slide plan.
    Input: {projectData: {...}}
    Output: {proposed_count, reasoning, slides: [...]}
    """
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    branding = db.get_branding(g.tenant_id)

    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400

    training_context = db.get_training_context(g.tenant_id)
    prompt = build_slide_plan_prompt(project_data, branding)
    if training_context:
        prompt = f"## بيانات خاصة بالشركة\n{training_context}\n\n---\n\n{prompt}"

    def build_fallback_plan(b):
        count = max(b.get('min_slides', 8), min(b.get('max_slides', 30), b.get('default_slide_count', 12)))
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
        ]
        needed = max(0, count - 4)  # cover + index + moodboard + closing
        for i, title in enumerate(content_titles):
            if len(slides) - 1 >= needed:
                break
            slides.append({
                'title': title,
                'type': 'content',
                'design_style': 'cards' if i % 2 == 0 else 'split',
                'requires_image': False,
                'bullets': ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة'],
                'content_density': 'medium',
            })
        while len(slides) - 1 < needed:
            idx = len(slides) - 1
            slides.append({
                'title': f'شريحة محتوى {idx}',
                'type': 'content',
                'design_style': 'cards',
                'requires_image': False,
                'bullets': ['نقطة رئيسية أولى', 'نقطة رئيسية ثانية', 'نقطة رئيسية ثالثة'],
                'content_density': 'medium',
            })
        slides.append({'title': 'مود بورد', 'type': 'moodboard', 'design_style': 'grid', 'requires_image': True, 'bullets': [], 'content_density': 'low'})
        slides.append({'title': 'شكراً لكم', 'type': 'closing', 'design_style': 'minimal', 'requires_image': False, 'bullets': [], 'content_density': 'low'})
        return {'proposed_count': len(slides), 'slides': slides}

    plan = None
    last_error = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            response = call_zai_chat_parallel(
                "أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية.",
                prompt,
                max_tokens=4000,
                attempts=2
            )
            content = extract_chat_content(response, "SLIDE-PLAN")
            plan = parse_slide_plan(content)
            print(f"[SLIDE-PLAN] Parsed on attempt {attempt}")
            break
        except Exception as e:
            last_error = e
            print(f"[SLIDE-PLAN ATTEMPT {attempt} FAILED] {e}")
            if attempt < max_attempts:
                time.sleep(1)

    if not plan:
        print(f"[SLIDE-PLAN FALLBACK] Using fallback plan after {max_attempts} attempts. Last error: {last_error}")
        plan = build_fallback_plan(branding)

    is_valid, issues = validate_slide_plan(plan, branding)
    if not is_valid:
        print(f"[SLIDE-PLAN] Validation issues: {issues}")

    return jsonify({
        'success': True,
        'plan': plan,
        'validation': {'isValid': is_valid, 'issues': issues},
    })


@app.route('/api/geocode', methods=['POST'])
@require_auth
def api_geocode():
    """Geocode an address to lat/lng."""
    data = request.json or {}
    address = data.get('address', '').strip()
    if not address:
        return jsonify({'error': 'address is required'}), 400
    result = maps_service.geocode_address(address)
    return jsonify(result)


@app.route('/api/nearby-landmarks', methods=['POST'])
@require_auth
def api_nearby_landmarks():
    """Get nearby landmarks for given coordinates."""
    data = request.json or {}
    lat = data.get('lat')
    lng = data.get('lng')
    radius = data.get('radius', 1500)
    if lat is None or lng is None:
        return jsonify({'error': 'lat and lng are required'}), 400
    result = maps_service.get_nearby_landmarks(float(lat), float(lng), int(radius))
    return jsonify(result)


@app.route('/api/generate-map-images', methods=['POST'])
@require_auth
def api_generate_map_images():
    """Generate all map images for a project and return placeholders."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = data.get('presentationId')
    force = bool(data.get('force'))
    result = maps_service.generate_all_map_images(project_data, g.tenant_id, presentation_id=presentation_id, force=force)
    if result.get('error'):
        return jsonify({'success': False, 'error': result['error']}), 400
    # Convert absolute paths to public URLs
    placeholders = {}
    for placeholder, path in result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = f"/{rel_path}"
        else:
            placeholders[placeholder] = None
    return jsonify({
        'success': True,
        'placeholders': placeholders,
        'landmarks': result.get('landmarks', []),
        'lat': result.get('lat'),
        'lng': result.get('lng'),
    })


@app.route('/api/presentations/<pres_id>/regenerate-maps', methods=['POST'])
@require_permission('create_presentation')
def api_regenerate_presentation_maps(pres_id):
    """Regenerate map images for a saved presentation."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404

    project_data = json.loads(pres['project_data']) if pres.get('project_data') else {}
    # Accept per-map style overrides from request body
    req_data = request.json or {}
    if req_data.get('map_styles'):
        project_data['map_styles'] = req_data['map_styles']
    result = maps_service.generate_all_map_images(project_data, g.tenant_id, presentation_id=pres_id, force=True)
    if result.get('error'):
        return jsonify({'success': False, 'error': result['error']}), 400

    placeholders = {}
    for placeholder, path in result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = f"/{rel_path}"
        else:
            placeholders[placeholder] = None

    # Update slide HTML in database with new map paths
    slides_data = json.loads(pres['slides_data']) if pres.get('slides_data') else []
    if slides_data:
        slides_json = json.dumps(slides_data, ensure_ascii=False)
        updated = False
        for placeholder, rel_path in placeholders.items():
            if not rel_path:
                continue
            # Derive the map type name from the placeholder
            # ##MAP_OVERVIEW## -> overview, ##STREET_VIEW_1## -> streetview_1
            ptype = placeholder.replace('##MAP_', '').replace('##STREET_VIEW_', 'streetview_').replace('##', '').lower()
            pattern = r'/uploads/maps/[^/]+_[^/]+_' + ptype + r'_[^/]+\.png'
            if re.search(pattern, slides_json):
                slides_json = re.sub(pattern, rel_path, slides_json)
                updated = True
        if updated:
            slides_data = json.loads(slides_json)
            db.update_presentation(pres_id, slides_data=slides_data)

    return jsonify({
        'success': True,
        'placeholders': placeholders,
        'landmarks': result.get('landmarks', []),
        'lat': result.get('lat'),
        'lng': result.get('lng'),
    })


@app.route('/api/generate-slides', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slides():
    """
    Generate all slides HTML based on a slide plan.
    Input: {projectData: {...}, slidePlan: {...}, images: {...}}
    Output: {slides: [{html, title, type}], slideCount}
    """
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    slide_plan = data.get('slidePlan', {})
    images = data.get('images', {})
    presentation_id = data.get('presentationId')

    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400

    if not slide_plan or 'slides' not in slide_plan:
        return jsonify({'error': 'slidePlan with slides array is required'}), 400

    # Generate map images if project has location data
    map_result = maps_service.generate_all_map_images(project_data, g.tenant_id, presentation_id=presentation_id, force=True)
    map_placeholders = {}
    if map_result.get('placeholders'):
        if not isinstance(images, dict):
            images = {'cover': images[0] if isinstance(images, list) and images else None, 'moodboard': []}
        # Convert absolute file paths to public URLs for HTML replacement
        for placeholder, path in map_result['placeholders'].items():
            if path and os.path.exists(path):
                rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
                map_placeholders[placeholder] = f"/{rel_path}"
            else:
                map_placeholders[placeholder] = None
        images['map_placeholders'] = map_placeholders
        images['map_landmarks'] = map_result.get('landmarks', [])
        # Add coordinates back into project data for the AI
        project_data['_resolved_location'] = {
            'lat': map_result['lat'],
            'lng': map_result['lng'],
        }

    images_info = _get_images_info(images)

    training_context = db.get_training_context(g.tenant_id)

    # Define the GLM call function for the slide engine
    def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
        if training_context:
            sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
        return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2)

    try:
        htmls = generate_all_slides(
            slide_plan, project_data, branding, images_info, call_glm_fn,
            map_placeholders=map_placeholders, creative_images=images
        )

        slides_out = []
        plan_slides = slide_plan.get('slides', [])
        for i, html in enumerate(htmls):
            slide_info = plan_slides[i] if i < len(plan_slides) else {}
            slides_out.append({
                'html': html or '',
                'title': slide_info.get('title', f'شريحة {i+1}'),
                'type': slide_info.get('type', 'content'),
                'designStyle': slide_info.get('design_style', 'cards'),
            })

        return jsonify({
            'success': True,
            'slides': slides_out,
            'slideCount': len(slides_out),
        })
    except Exception as e:
        print(f"[GENERATE-SLIDES ERROR] {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/presentations', methods=['GET'])
@require_permission('view_presentations')
def api_get_presentations():
    """List all presentations for the current tenant."""
    presentations = db.get_presentations(g.tenant_id)
    result = []
    for p in presentations:
        result.append({
            'id': p['id'],
            'title': p['title'],
            'slideCount': p.get('slide_count', 0),
            'status': p.get('status', 'draft'),
            'createdAt': p.get('created_at'),
            'updatedAt': p.get('updated_at'),
        })
    return jsonify({'success': True, 'presentations': result})


@app.route('/api/presentations', methods=['POST'])
@require_permission('create_presentation')
def api_save_presentation():
    """Save a new presentation."""
    data = request.json or {}
    title = (data.get('title') or 'عرض بدون عنوان').strip()
    project_data = data.get('projectData', {})
    slides_data = data.get('slidesData', [])
    slide_count = data.get('slideCount', len(slides_data))

    pres_id = db.create_presentation(
        tenant_id=g.tenant_id,
        title=title,
        project_data=project_data,
        slides_data=slides_data,
        slide_count=slide_count,
    )
    return jsonify({'success': True, 'presentationId': pres_id}), 201


@app.route('/api/presentations/<pres_id>', methods=['GET'])
@require_permission('view_presentations')
def api_get_presentation(pres_id):
    """Get a specific presentation."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404

    pres['projectData'] = json.loads(pres['project_data']) if pres.get('project_data') else {}
    slides = json.loads(pres['slides_data']) if pres.get('slides_data') else []
    logo_url = '/assets/logo.png'
    branding = db.get_branding(g.tenant_id) or {}
    if branding.get('logo_path'):
        logo_url = branding['logo_path']
    for s in slides:
        if isinstance(s, dict) and 'html' in s and isinstance(s['html'], str):
            s['html'] = s['html'].replace('##LOGO##', logo_url)
    pres['slidesData'] = slides
    return jsonify({'success': True, 'presentation': pres})


@app.route('/api/presentations/<pres_id>', methods=['PUT'])
@require_permission('create_presentation')
def api_update_presentation(pres_id):
    """Update a presentation. Saves a version snapshot and logs the edit."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404

    data = request.json or {}
    updates = {}
    for k in ['title', 'projectData', 'slidesData', 'slideCount', 'status']:
        if k in data:
            db_key = {'projectData': 'project_data', 'slidesData': 'slides_data', 'slideCount': 'slide_count'}.get(k, k)
            updates[db_key] = data[k]

    # Save version snapshot before update if slides_data is changing
    if 'slides_data' in updates:
        import json as _json
        current_slides = _json.loads(pres['slides_data']) if pres.get('slides_data') else []
        db.save_presentation_version(pres_id, g.user_id, g.user_name or 'System', current_slides, action='edit')
        # Build detailed log entry
        details_parts = []
        if 'title' in updates and updates['title'] != pres.get('title'):
            details_parts.append(f'العنوان: "{pres.get("title","")}" → "{updates["title"]}"')
        new_count = len(updates['slides_data']) if isinstance(updates['slides_data'], list) else 0
        old_count = len(current_slides) if isinstance(current_slides, list) else 0
        if new_count != old_count:
            details_parts.append(f'عدد الشرائح: {old_count} → {new_count}')
        if not details_parts:
            details_parts.append('تعديل المحتوى')
        db.log_edit(pres_id, g.user_id, g.user_name or 'System', 'edit', ' | '.join(details_parts))

    db.update_presentation(pres_id, **updates)
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EXPORT ENDPOINTS (Tenant-Aware)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/export', methods=['POST'])
@require_permission('export_files')
def api_export():
    """
    Export presentation to PDF or PPTX.
    Input: {format: 'pdf'|'pptx', slidesHtml: '...', slidesData: [...], projectName: '...'}
    """
    data = request.json or {}
    fmt = data.get('format', 'pdf').lower()
    project_name = data.get('projectName', 'presentation')
    branding = db.get_branding(g.tenant_id)

    # Tenant-specific output directory
    tenant_output_dir = os.path.join(OUTPUT_DIR, g.tenant_id)
    os.makedirs(tenant_output_dir, exist_ok=True)

    try:
        if fmt == 'pdf':
            from exports.pdf_export import generate_pdf
            slides_html = data.get('slidesHtml', '')
            if not slides_html:
                return jsonify({'error': 'slidesHtml is required for PDF export'}), 400

            pdf_path = generate_pdf(slides_html, project_name, branding, tenant_output_dir)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pdf_path)}'

            # Record export
            export_id = db.create_export(data.get('presentationId'), g.tenant_id, 'pdf', pdf_path)
            if data.get('presentationId'):
                db.log_edit(data['presentationId'], g.user_id, g.user_name or 'System', 'export', f'Exported as PDF')
            return jsonify({'success': True, 'url': f'/api/exports/{export_id}/download', 'exportId': export_id, 'format': 'pdf'})

        elif fmt == 'pptx':
            from exports.pptx_export import generate_pptx
            slides_data = data.get('slidesData', [])
            if not slides_data:
                return jsonify({'error': 'slidesData is required for PPTX export'}), 400

            pptx_path = generate_pptx(slides_data, project_name, branding, tenant_output_dir)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pptx_path)}'

            export_id = db.create_export(data.get('presentationId'), g.tenant_id, 'pptx', pptx_path)
            if data.get('presentationId'):
                db.log_edit(data['presentationId'], g.user_id, g.user_name or 'System', 'export', f'Exported as PPTX')
            return jsonify({'success': True, 'url': f'/api/exports/{export_id}/download', 'exportId': export_id, 'format': 'pptx'})

        else:
            return jsonify({'error': f'Unsupported format: {fmt}. Use pdf or pptx'}), 400

    except Exception as e:
        print(f"[EXPORT ERROR] {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/exports', methods=['GET'])
@require_auth
def api_get_exports():
    """List all exports for the current tenant."""
    exports = db.get_exports(g.tenant_id)
    result = []
    for e in exports:
        result.append({
            'id': e['id'],
            'format': e['format'],
            'downloadUrl': f"/api/exports/{e['id']}/download",
            'createdAt': e.get('created_at'),
        })
    return jsonify({'success': True, 'exports': result})


@app.route('/api/exports/<export_id>/download', methods=['GET'])
@require_auth
def api_download_export(export_id):
    exported_file = db.get_export(export_id, g.tenant_id)
    if not exported_file:
        return jsonify({'error': 'Export not found'}), 404
    file_path = os.path.abspath(exported_file['file_path'])
    tenant_output_dir = os.path.abspath(os.path.join(OUTPUT_DIR, g.tenant_id))
    if os.path.commonpath([file_path, tenant_output_dir]) != tenant_output_dir or not os.path.isfile(file_path):
        return jsonify({'error': 'Export file unavailable'}), 404
    return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUTH ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """Register a new company (tenant). Creates company admin user automatically."""
    data = request.json or {}
    company_name = (data.get('companyName') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')
    subdomain = (data.get('subdomain') or '').strip().lower() or None
    domain = (data.get('domain') or '').strip().lower() or None

    if not company_name or not email or not password:
        return jsonify({'error': 'companyName, email, and password are required'}), 400
    if len(company_name) > 120:
        return jsonify({'error': 'Company name is too long'}), 400
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Invalid email address'}), 400
    if len(password) < 10:
        return jsonify({'error': 'Password must be at least 10 characters'}), 400
    if subdomain and not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', subdomain):
        return jsonify({'error': 'Invalid subdomain'}), 400
    if domain and not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,}', domain):
        return jsonify({'error': 'Invalid domain (e.g. manafe.com)'}), 400

    if db.get_tenant_by_email(email):
        return jsonify({'error': 'Email already registered'}), 409
    if subdomain and db.get_tenant_by_subdomain(subdomain):
        return jsonify({'error': 'Subdomain already taken'}), 409
    if domain and db.get_tenant_by_domain(domain):
        return jsonify({'error': 'Domain already registered'}), 409

    try:
        tenant_id = db.create_tenant(company_name, email, hash_password(password), subdomain=subdomain)
        if domain:
            db.update_tenant(tenant_id, **{'settings_json': json.dumps({'domain': domain})})
            conn = db.get_db()
            conn.execute('UPDATE tenants SET domain = ? WHERE id = ?', (domain, tenant_id))
            conn.commit()
        # Create company admin user
        db.create_user(tenant_id, company_name, email, hash_password(password), role='company_admin')
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email or subdomain already registered'}), 409
    token = create_token(tenant_id, email, is_admin=False, user_id=None, user_name=company_name, user_role='company_admin')
    return jsonify({
        'success': True,
        'token': token,
        'tenant': {'id': tenant_id, 'companyName': company_name, 'email': email, 'domain': domain}
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Login a company admin (tenant) or employee (user). Auto-detects by email domain."""
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    # Try tenant (company admin) login first
    tenant = db.get_tenant_by_email(email)
    if tenant and verify_password(password, tenant['password_hash']):
        if not tenant.get('is_active'):
            return jsonify({'error': 'Account is deactivated'}), 403
        token = create_token(tenant['id'], tenant['email'], is_admin=bool(tenant.get('is_admin')),
                             user_name=tenant['company_name'], user_role='company_admin')
        return jsonify({
            'success': True,
            'token': token,
            'tenant': {
                'id': tenant['id'],
                'companyName': tenant['company_name'],
                'email': tenant['email'],
                'isAdmin': bool(tenant.get('is_admin')),
                'plan': tenant.get('plan', 'free'),
                'domain': tenant.get('domain'),
            },
            'user': {
                'name': tenant['company_name'],
                'role': 'company_admin',
            }
        })

    # Try user (employee) login - find by email
    user = db.get_user_by_email(email)
    if user and verify_password(password, user['password_hash']):
        if not user.get('is_active'):
            return jsonify({'error': 'Account is deactivated'}), 403
        if not user.get('tenant_active'):
            return jsonify({'error': 'Company account is deactivated'}), 403
        token = create_token(user['tenant_id'], user['email'], is_admin=bool(user.get('tenant_is_admin')),
                             user_id=user['id'], user_name=user['name'], user_role=user['role'])
        tenant = db.get_tenant_by_id(user['tenant_id'])
        return jsonify({
            'success': True,
            'token': token,
            'tenant': {
                'id': tenant['id'],
                'companyName': tenant['company_name'],
                'email': tenant['email'],
                'isAdmin': bool(tenant.get('is_admin')),
                'plan': tenant.get('plan', 'free'),
                'domain': tenant.get('domain'),
            },
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email'],
                'role': user['role'],
            }
        })

    return jsonify({'error': 'Invalid email or password'}), 401


@app.route('/api/auth/me', methods=['GET'])
@require_auth
def api_me():
    """Get current tenant/user info."""
    t = g.tenant
    result = {
        'success': True,
        'tenant': {
            'id': t['id'],
            'companyName': t['company_name'],
            'email': t['email'],
            'isAdmin': bool(t.get('is_admin')),
            'plan': t.get('plan', 'free'),
            'subdomain': t.get('subdomain'),
            'domain': t.get('domain'),
        }
    }
    if g.user_id:
        result['user'] = {
            'id': g.user_id,
            'name': g.user_name,
            'role': g.user_role,
            'permissions': g.user_permissions,
        }
    else:
        result['user'] = {
            'name': t['company_name'],
            'role': 'company_admin',
            'permissions': {k: True for k in db.PERMISSION_KEYS},
        }
    return jsonify(result)


@app.route('/api/auth/refresh', methods=['POST'])
@require_auth
def api_refresh():
    """Refresh the JWT token."""
    t = g.tenant
    token = create_token(t['id'], t['email'], is_admin=bool(t.get('is_admin')),
                         user_id=g.user_id, user_name=g.user_name, user_role=g.user_role)
    return jsonify({'success': True, 'token': token})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# USER MANAGEMENT ENDPOINTS (company admin only)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/users', methods=['GET'])
@require_permission('manage_users')
def api_list_users():
    """List all users in the tenant."""
    users = db.get_users_by_tenant(g.tenant_id)
    return jsonify({'success': True, 'users': users})


@app.route('/api/users', methods=['POST'])
@require_permission('manage_users')
def api_add_user():
    """Add a user (employee) to the tenant."""
    data = request.json or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')
    role = data.get('role', 'employee')

    if not name or not email or not password:
        return jsonify({'error': 'name, email, and password are required'}), 400
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Invalid email'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if role not in ('employee', 'company_admin'):
        return jsonify({'error': 'Invalid role'}), 400

    existing = db.get_user_by_email(email)
    if existing:
        return jsonify({'error': 'Email already in use'}), 409

    try:
        user_id = db.create_user(g.tenant_id, name, email, hash_password(password), role=role)
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already in use'}), 409
    return jsonify({'success': True, 'userId': user_id}), 201


@app.route('/api/users/<user_id>', methods=['PUT'])
@require_permission('manage_users')
def api_update_user(user_id):
    """Update a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404

    data = request.json or {}
    updates = {}
    for k in ['name', 'email', 'role', 'is_active']:
        if k in data:
            updates[k] = data[k]
    if 'password' in data and data['password']:
        updates['password_hash'] = hash_password(data['password'])

    db.update_user(user_id, **updates)
    return jsonify({'success': True})


@app.route('/api/users/<user_id>', methods=['DELETE'])
@require_permission('manage_users')
def api_delete_user(user_id):
    """Delete a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    db.delete_user(user_id)
    return jsonify({'success': True})


@app.route('/api/users/<user_id>/permissions', methods=['GET'])
@require_permission('manage_users')
def api_get_user_permissions(user_id):
    """Get effective permissions for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    perms = db.get_user_permissions(user_id, user.get('role', 'employee'))
    return jsonify({'success': True, 'permissions': perms, 'availableKeys': db.PERMISSION_KEYS})


@app.route('/api/users/<user_id>/permissions', methods=['PUT'])
@require_permission('manage_users')
def api_set_user_permissions(user_id):
    """Set permissions for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404

    data = request.json or {}
    permissions = data.get('permissions', {})
    for key, granted in permissions.items():
        if key not in db.PERMISSION_KEYS:
            return jsonify({'error': f'Unknown permission key: {key}'}), 400
        db.set_user_permission(user_id, key, bool(granted))

    perms = db.get_user_permissions(user_id, user.get('role', 'employee'))
    return jsonify({'success': True, 'permissions': perms})


@app.route('/api/my-permissions', methods=['GET'])
@require_auth
def api_get_my_permissions():
    """Get current user's effective permissions."""
    if g.user_id:
        perms = db.get_user_permissions(g.user_id, g.user_role or 'employee')
    else:
        perms = {k: True for k in db.PERMISSION_KEYS}
    return jsonify({'success': True, 'permissions': perms, 'role': g.user_role})


@app.route('/api/field-sections', methods=['GET'])
@require_auth
def api_get_field_sections():
    """Get available field sections and current user's allowed sections."""
    available = db.FIELD_SECTIONS
    allowed = db.get_user_field_sections(g.user_id) if g.user_id else db.DEFAULT_FIELD_SECTIONS.copy()
    return jsonify({'success': True, 'available': available, 'allowed': allowed})


@app.route('/api/users/<user_id>/field-sections', methods=['GET'])
@require_permission('manage_users')
def api_get_user_field_sections(user_id):
    """Get effective field section visibility for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    sections = db.get_user_field_sections(user_id)
    return jsonify({'success': True, 'sections': sections, 'available': db.FIELD_SECTIONS})


@app.route('/api/users/<user_id>/field-sections', methods=['PUT'])
@require_permission('manage_users')
def api_set_user_field_sections(user_id):
    """Set field section visibility for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404

    data = request.json or {}
    sections = data.get('sections', {})
    for key, granted in sections.items():
        if key not in db.DEFAULT_FIELD_SECTIONS:
            return jsonify({'error': f'Unknown section key: {key}'}), 400
        db.set_user_field_section(user_id, key, bool(granted))

    sections = db.get_user_field_sections(user_id)
    return jsonify({'success': True, 'sections': sections})


@app.route('/api/invites', methods=['POST'])
@require_permission('manage_users')
def api_create_invite():
    """Create an invite link for an employee."""
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    if not email or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Valid email required'}), 400

    token = db.create_invite(g.tenant_id, email)
    # In production, send email here. For now, return the link.
    invite_url = f"/invite/{token}"
    return jsonify({'success': True, 'inviteUrl': invite_url, 'token': token})


@app.route('/api/invite/<token>', methods=['GET'])
def api_get_invite(token):
    """Get invite info (public, no auth needed)."""
    invite = db.get_invite_by_token(token)
    if not invite:
        return jsonify({'error': 'Invalid or expired invite'}), 404
    tenant = db.get_tenant_by_id(invite['tenant_id'])
    return jsonify({
        'success': True,
        'email': invite['email'],
        'companyName': tenant['company_name'] if tenant else '',
    })


@app.route('/api/invite/<token>/register', methods=['POST'])
def api_accept_invite(token):
    """Register a user via invite link."""
    invite = db.get_invite_by_token(token)
    if not invite:
        return jsonify({'error': 'Invalid or expired invite'}), 404

    data = request.json or {}
    name = (data.get('name') or '').strip()
    password = data.get('password', '')
    if not name or not password:
        return jsonify({'error': 'name and password are required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    existing = db.get_user_by_email(invite['email'])
    if existing:
        return jsonify({'error': 'Email already registered'}), 409

    user_id = db.create_user(invite['tenant_id'], name, invite['email'], hash_password(password), role='employee')
    db.mark_invite_used(token)

    tenant = db.get_tenant_by_id(invite['tenant_id'])
    jwt_token = create_token(tenant['id'], invite['email'], is_admin=False,
                             user_id=user_id, user_name=name, user_role='employee')
    return jsonify({
        'success': True,
        'token': jwt_token,
        'tenant': {
            'id': tenant['id'],
            'companyName': tenant['company_name'],
            'email': tenant['email'],
        },
        'user': {'id': user_id, 'name': name, 'email': invite['email'], 'role': 'employee'}
    }), 201


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PRESENTATION VERSIONS & EDIT LOG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/presentations/<pres_id>/versions', methods=['GET'])
@require_auth
def api_get_versions(pres_id):
    """Get all versions of a presentation."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404
    versions = db.get_presentation_versions(pres_id)
    return jsonify({'success': True, 'versions': versions})


@app.route('/api/presentations/<pres_id>/versions/<version_id>/restore', methods=['POST'])
@require_auth
def api_restore_version(pres_id, version_id):
    """Restore a presentation to a previous version."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404

    version = db.get_presentation_version(version_id)
    if not version or version['presentation_id'] != pres_id:
        return jsonify({'error': 'Version not found'}), 404

    # Save current state as a new version before restoring
    import json as _json
    current_slides = _json.loads(pres['slides_data']) if pres.get('slides_data') else []
    db.save_presentation_version(pres_id, g.user_id, g.user_name or 'System', current_slides, action='pre-restore')

    # Restore the old version
    old_slides = _json.loads(version['slides_data']) if version.get('slides_data') else []
    db.update_presentation(pres_id, slides_data=old_slides)
    db.log_edit(pres_id, g.user_id, g.user_name or 'System', 'restore', f'Restored version from {version["created_at"]}')

    return jsonify({'success': True, 'slidesData': old_slides})


@app.route('/api/presentations/<pres_id>/edit-log', methods=['GET'])
@require_auth
def api_get_edit_log(pres_id):
    """Get edit history for a presentation."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404
    log = db.get_edit_log(pres_id)
    return jsonify({'success': True, 'log': log})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FILE UPLOAD ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


def _save_tenant_image(uploaded_file, base_name):
    from PIL import Image, UnidentifiedImageError

    extension = os.path.splitext(uploaded_file.filename or '')[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('Only PNG, JPG, JPEG, and WEBP images are supported')
    try:
        image = Image.open(uploaded_file.stream)
        image.verify()
        uploaded_file.stream.seek(0)
    except (UnidentifiedImageError, OSError):
        raise ValueError('Invalid image file')

    tenant_dir = os.path.join(UPLOADS_DIR, g.tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    normalized_extension = '.jpg' if extension == '.jpeg' else extension
    file_path = os.path.join(tenant_dir, f'{base_name}{normalized_extension}')
    uploaded_file.save(file_path)
    return file_path, normalized_extension


@app.route('/api/upload/logo', methods=['POST'])
@require_permission('company_settings')
def api_upload_logo():
    """Upload company logo."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    try:
        logo_path, extension = _save_tenant_image(file, 'logo')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    relative_path = f'/tenant-assets/{g.tenant_id}/logo'
    db.update_branding(g.tenant_id, logo_path=relative_path)
    return jsonify({'success': True, 'logoPath': relative_path})


@app.route('/api/upload/reference-image', methods=['POST'])
@require_permission('company_settings')
def api_upload_reference():
    """Upload a reference design image."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    try:
        ref_path, extension = _save_tenant_image(file, 'reference')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    stored_path = os.path.relpath(ref_path, os.path.dirname(__file__)).replace('\\', '/')
    db.update_branding(g.tenant_id, reference_image_path=stored_path)
    return jsonify({'success': True, 'referenceImageUploaded': True})


@app.route('/api/branding/analyze-reference', methods=['POST'])
@require_permission('company_settings')
def api_analyze_reference():
    """
    Analyze the uploaded reference image using Gemini Vision.
    Extracts colors, design style, and layout — then auto-applies to branding.
    """
    from reference_analyzer import analyze_reference_image

    branding = db.get_branding(g.tenant_id)
    ref_path = branding.get('reference_image_path') if branding else None

    if not ref_path:
        return jsonify({'error': 'No reference image uploaded. Upload one first via /api/upload/reference-image'}), 400

    # Convert relative path to absolute
    abs_path = os.path.join(os.path.dirname(__file__), ref_path.lstrip('/'))
    if not os.path.exists(abs_path):
        return jsonify({'error': 'Reference image file not found on disk'}), 404

    try:
        analysis = analyze_reference_image(abs_path, OPENROUTER_KEY)

        # Auto-apply extracted colors and style to branding
        updates = {}
        colors = analysis.get('colors', {})
        if colors:
            for k in ['primary', 'secondary', 'accent', 'background', 'text']:
                if colors.get(k):
                    updates[f'{k}_color'] = colors[k]

        if analysis.get('design_style'):
            updates['design_template'] = analysis['design_style']
        if analysis.get('card_style'):
            updates['card_style'] = analysis['card_style']

        if updates:
            db.update_branding(g.tenant_id, **updates)

        updated_branding = db.get_branding(g.tenant_id)
        return jsonify({
            'success': True,
            'analysis': analysis,
            'branding': updated_branding,
        })
    except Exception as e:
        print(f"[ANALYZE-REFERENCE ERROR] {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/tenant-assets/<tenant_id>/logo')
def serve_tenant_logo(tenant_id):
    branding = db.get_branding(tenant_id)
    if not branding or not branding.get('logo_path'):
        return jsonify({'error': 'Logo not found'}), 404
    tenant_dir = os.path.join(UPLOADS_DIR, tenant_id)
    for extension in ALLOWED_IMAGE_EXTENSIONS:
        logo_path = os.path.join(tenant_dir, f'logo{extension}')
        if os.path.isfile(logo_path):
            return send_file(logo_path)
    return jsonify({'error': 'Logo not found'}), 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/admin/tenants', methods=['GET'])
@require_admin
def api_admin_tenants():
    """List all tenants (admin only)."""
    tenants = db.get_all_tenants()
    result = []
    for t in tenants:
        result.append({
            'id': t['id'],
            'companyName': t['company_name'],
            'email': t['email'],
            'plan': t.get('plan', 'free'),
            'isActive': bool(t.get('is_active')),
            'isAdmin': bool(t.get('is_admin')),
            'subdomain': t.get('subdomain'),
            'domain': t.get('domain'),
            'createdAt': t.get('created_at'),
        })
    return jsonify({'success': True, 'tenants': result})


@app.route('/api/admin/tenants/<tenant_id>', methods=['PUT'])
@require_admin
def api_admin_update_tenant(tenant_id):
    """Update a tenant (admin only)."""
    data = request.json or {}
    fields = {}
    for k in ['company_name', 'subdomain', 'plan', 'is_active']:
        if k in data:
            fields[k] = data[k]
    db.update_tenant(tenant_id, **fields)
    return jsonify({'success': True})


@app.route('/api/admin/tenants/<tenant_id>', methods=['DELETE'])
@require_admin
def api_admin_delete_tenant(tenant_id):
    """Delete a tenant (admin only)."""
    if tenant_id == g.tenant_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    db.delete_tenant(tenant_id)
    return jsonify({'success': True})


@app.route('/api/admin/stats', methods=['GET'])
@require_admin
def api_admin_stats():
    """Get global stats (admin only)."""
    return jsonify({'success': True, 'stats': db.get_stats()})


@app.route('/api/admin/tenants/<tenant_id>/details', methods=['GET'])
@require_admin
def api_admin_tenant_details(tenant_id):
    """Get detailed info about a specific tenant (admin only)."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    users = db.get_users_by_tenant(tenant_id)
    presentations = db.get_presentations(tenant_id)
    branding = db.get_branding(tenant_id)
    exports = db.get_exports(tenant_id)
    return jsonify({
        'success': True,
        'tenant': {
            'id': tenant['id'],
            'companyName': tenant['company_name'],
            'email': tenant['email'],
            'plan': tenant.get('plan', 'free'),
            'isActive': bool(tenant.get('is_active')),
            'isAdmin': bool(tenant.get('is_admin')),
            'subdomain': tenant.get('subdomain'),
            'domain': tenant.get('domain'),
            'createdAt': tenant.get('created_at'),
            'settingsJson': tenant.get('settings_json'),
        },
        'users': users,
        'presentations': presentations,
        'exports': exports,
        'branding': branding,
        'counts': {
            'users': len(users),
            'presentations': len(presentations),
            'exports': len(exports),
        }
    })


@app.route('/api/admin/tenants/<tenant_id>/users', methods=['GET'])
@require_admin
def api_admin_tenant_users(tenant_id):
    """List users of a specific tenant (admin only)."""
    users = db.get_users_by_tenant(tenant_id)
    return jsonify({'success': True, 'users': users})


@app.route('/api/admin/tenants/<tenant_id>/reset-password', methods=['POST'])
@require_admin
def api_admin_reset_tenant_password(tenant_id):
    """Reset a tenant's password (admin only)."""
    data = request.json or {}
    new_password = data.get('password', '')
    if len(new_password) < 10:
        return jsonify({'error': 'Password must be at least 10 characters'}), 400
    db.update_tenant(tenant_id, password_hash=hash_password(new_password))
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Training Data (per-tenant GLM training)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/training', methods=['GET'])
@require_permission('training_data')
def api_get_training():
    """Get all training data entries for the current tenant."""
    entries = db.get_training_data(g.tenant_id)
    return jsonify({'success': True, 'entries': entries})


@app.route('/api/training', methods=['POST'])
@require_permission('training_data')
def api_add_training():
    """Add a training data entry."""
    data = request.json or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    category = data.get('category', 'general')
    if not title or not content:
        return jsonify({'error': 'title and content are required'}), 400
    entry_id = db.create_training_entry(g.tenant_id, title, content, category)
    return jsonify({'success': True, 'entryId': entry_id}), 201


@app.route('/api/training/<entry_id>', methods=['PUT'])
@require_permission('training_data')
def api_update_training(entry_id):
    """Update a training data entry."""
    data = request.json or {}
    db.update_training_entry(entry_id, **{k: data[k] for k in ['title', 'content', 'category', 'is_active'] if k in data})
    return jsonify({'success': True})


@app.route('/api/training/<entry_id>', methods=['DELETE'])
@require_permission('training_data')
def api_delete_training(entry_id):
    """Delete a training data entry."""
    db.delete_training_entry(entry_id)
    return jsonify({'success': True})


@app.route('/api/training-chat', methods=['POST'])
@require_permission('training_data')
def api_training_chat():
    """Discussion-only chat for training the AI. Does not save anything.
    Accepts a user message and an optional history of previous turns."""
    data = request.json or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'message is required'}), 400

    history = data.get('history') or []
    history_lines = []
    for turn in history[-10:]:
        role = 'المستخدم' if turn.get('role') == 'user' else 'المساعد'
        history_lines.append(f"{role}: {turn.get('text', '')}")
    context = '\n'.join(history_lines)

    system_prompt = (
        "أنت مساعد ذكي لتدريب نموذج AI على توليد العروض التقديمية العقارية. "
        "المستخدم سيشاركك معلومات عن شركته، أسلوب الكتابة، المصطلحات، أو أي تفاصيل يريد أن يستخدمها AI. "
        "مهمتك: مناقشة المستخدم، طلب التوضيح عند الحاجة، تلخيص ما يقوله، واقتراح حفظ المعلومات عندما تصبح كافية. "
        "لا تحفظ أي شيء بنفسك؛ مجرد رد ودي ومفيد."
    )
    user_prompt = (context + '\n\nالمستخدم: ' + message + '\n\nالمساعد:') if context else ('المستخدم: ' + message + '\n\nالمساعد:')

    try:
        response = call_zai_chat(system_prompt, user_prompt, max_tokens=800)
        reply = extract_chat_content(response, 'TRAINING-CHAT')
    except Exception as e:
        print(f'[TRAINING-CHAT] AI reply failed: {e}')
        reply = 'أهلاً! شاركني المعلومات التي تريد تدريب AI عليها.'

    return jsonify({'success': True, 'reply': reply})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI Rules Management
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AI_RULE_FIELDS = {
    # Design rules (editable branding fields)
    'primary_color': {'label': 'اللون الرئيسي', 'category': 'design', 'risk': 'green'},
    'secondary_color': {'label': 'اللون الثانوي', 'category': 'design', 'risk': 'green'},
    'accent_color': {'label': 'لون التمييز', 'category': 'design', 'risk': 'green'},
    'background_color': {'label': 'لون الخلفية', 'category': 'design', 'risk': 'green'},
    'text_color': {'label': 'لون النص', 'category': 'design', 'risk': 'green'},
    'font_family': {'label': 'الخط', 'category': 'design', 'risk': 'green'},
    'font_arabic': {'label': 'الخط العربي', 'category': 'design', 'risk': 'green'},
    'design_template': {'label': 'قالب التصميم', 'category': 'design', 'risk': 'yellow'},
    'card_style': {'label': 'نمط البطاقات', 'category': 'design', 'risk': 'green'},
    'slide_ratio': {'label': 'نسبة العرض', 'category': 'design', 'risk': 'yellow'},
    'header_enabled': {'label': 'تفعيل الهيدر', 'category': 'design', 'risk': 'red'},
    'footer_enabled': {'label': 'تفعيل الفوتر', 'category': 'design', 'risk': 'red'},
    'header_height': {'label': 'ارتفاع الهيدر', 'category': 'design', 'risk': 'yellow'},
    'footer_height': {'label': 'ارتفاع الفوتر', 'category': 'design', 'risk': 'yellow'},
    'moodboard_enabled': {'label': 'تفعيل المود بورد', 'category': 'design', 'risk': 'yellow'},
    'cover_image_enabled': {'label': 'تفعيل صورة الغلاف', 'category': 'design', 'risk': 'green'},
    'default_slide_count': {'label': 'عدد الشرائح الافتراضي', 'category': 'content', 'risk': 'yellow'},
    'min_slides': {'label': 'الحد الأدنى للشرائح', 'category': 'content', 'risk': 'red'},
    'max_slides': {'label': 'الحد الأقصى للشرائح', 'category': 'content', 'risk': 'red'},
}

DEFAULT_BRANDING_VALUES = {
    'primary_color': '#3B6E91',
    'secondary_color': '#254B66',
    'accent_color': '#6DA3C3',
    'background_color': '#F4F9FC',
    'text_color': '#333333',
    'font_family': 'The Sans Arabic',
    'font_arabic': 'The Sans Arabic',
    'design_template': 'modern',
    'card_style': 'bordered',
    'slide_ratio': '16:9',
    'header_enabled': 1,
    'footer_enabled': 1,
    'header_height': 56,
    'footer_height': 36,
    'moodboard_enabled': 1,
    'cover_image_enabled': 1,
    'default_slide_count': 16,
    'min_slides': 8,
    'max_slides': 30,
}


@app.route('/api/ai-rules', methods=['GET'])
@require_permission('ai_rules')
def api_get_ai_rules():
    """Get all AI rules for the tenant: design, content, training, log."""
    branding = db.get_branding(g.tenant_id) or {}
    design_rules = []
    for key, meta in AI_RULE_FIELDS.items():
        value = branding.get(key, DEFAULT_BRANDING_VALUES.get(key, ''))
        design_rules.append({
            'key': key,
            'label': meta['label'],
            'category': meta['category'],
            'risk': meta['risk'],
            'value': value,
            'defaultValue': DEFAULT_BRANDING_VALUES.get(key),
        })

    return jsonify({
        'success': True,
        'designRules': design_rules,
        'contentRules': CONTENT_DISTRIBUTION_RULES,
        'training': db.get_training_data(g.tenant_id),
        'log': db.get_ai_rules_log(g.tenant_id, limit=20),
    })


@app.route('/api/ai-rules', methods=['POST'])
@require_permission('ai_rules')
def api_update_ai_rule():
    """Update a single AI rule and log the change."""
    data = request.json or {}
    key = data.get('key')
    value = data.get('value')

    if not key or key not in AI_RULE_FIELDS:
        return jsonify({'error': 'Invalid rule key'}), 400

    meta = AI_RULE_FIELDS[key]
    if meta['category'] == 'design':
        # Get current value for audit log
        branding = db.get_branding(g.tenant_id) or {}
        old_value = branding.get(key)
        db.update_branding(g.tenant_id, **{key: value})
        db.log_ai_rule_change(
            tenant_id=g.tenant_id,
            rule_category='design',
            rule_key=key,
            old_value=old_value,
            new_value=value,
            risk_level=meta['risk'],
            user_id=g.user_id,
            user_name=g.user_name or 'Admin'
        )
    else:
        return jsonify({'error': 'Content rules are read-only in this endpoint'}), 400

    return jsonify({'success': True})


@app.route('/api/ai-rules/reset', methods=['POST'])
@require_permission('ai_rules')
def api_reset_ai_rules():
    """Reset all design rules to default values and log the reset."""
    keys = list(DEFAULT_BRANDING_VALUES.keys())
    branding = db.get_branding(g.tenant_id) or {}

    # Log old values for changed keys
    for key in keys:
        old_value = branding.get(key)
        new_value = DEFAULT_BRANDING_VALUES[key]
        if old_value != new_value:
            db.log_ai_rule_change(
                tenant_id=g.tenant_id,
                rule_category='design',
                rule_key=key,
                old_value=old_value,
                new_value=new_value,
                risk_level='red',
                user_id=g.user_id,
                user_name=g.user_name or 'Admin'
            )

    db.update_branding(g.tenant_id, **DEFAULT_BRANDING_VALUES)
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Presentation Approvals
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/presentations/<pres_id>/request-approval', methods=['POST'])
@require_auth
def api_request_approval(pres_id):
    """Request approval for a presentation (employee submits for review)."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404
    existing = db.get_approval_status(pres_id)
    if existing and existing['status'] == 'pending':
        return jsonify({'error': 'Approval already requested'}), 400
    approval_id = db.create_approval(pres_id, g.tenant_id, g.user_id, g.user_name or 'Unknown')
    return jsonify({'success': True, 'approvalId': approval_id})


@app.route('/api/approvals', methods=['GET'])
@require_permission('approvals')
def api_get_approvals():
    """Get all pending approvals for the current tenant."""
    approvals = db.get_pending_approvals(g.tenant_id)
    return jsonify({'success': True, 'approvals': approvals})


@app.route('/api/approvals/<approval_id>/review', methods=['POST'])
@require_permission('approvals')
def api_review_approval(approval_id):
    """Approve or reject a presentation."""
    data = request.json or {}
    status = data.get('status')
    if status not in ('approved', 'rejected'):
        return jsonify({'error': 'status must be approved or rejected'}), 400
    note = data.get('note')
    result = db.review_approval(approval_id, g.tenant_id, status, g.user_id, g.user_name or 'Admin', note)
    if not result:
        return jsonify({'error': 'Approval not found'}), 404
    return jsonify({'success': True})


@app.route('/api/presentations/<pres_id>/approval-status', methods=['GET'])
@require_auth
def api_approval_status(pres_id):
    """Get approval status for a presentation."""
    approval = db.get_approval_status(pres_id)
    return jsonify({'success': True, 'approval': approval})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Static Files + Health
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/invite/<token>')
def invite_page(token):
    return send_from_directory('.', 'index.html')

@app.route('/assets/<path:path>')
def static_assets(path):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'assets'), path)

@app.route('/uploads/<path:path>')
def static_uploads(path):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'uploads'), path)

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'model': GLM_MODEL, 'image_model': IMAGE_MODEL})

@app.route('/preview')
def preview():
    return send_from_directory('.', 'preview.html')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == '__main__':
    print("=" * 60)
    print("  Real Estate Proposal Generator - GLM-First Architecture")
    print("=" * 60)
    print(f"  GLM Model: {GLM_MODEL}")
    print(f"  Image Model: {IMAGE_MODEL}")
    print(f"  Output Dir: {OUTPUT_DIR}")
    print("=" * 60)
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True)
