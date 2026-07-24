import os
import sys
import json
import time
import re
import base64
import requests
import uuid as _uuid

import db_driver
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
def call_openrouter_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None):
    if not OPENROUTER_KEY:
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    model_name = model or GLM_OPENROUTER_MODEL
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-Title": "Real Estate Proposal Generator"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=300)
        return response.json()
    except Exception as exc:
        return {"error": {"message": str(exc)}}


def call_zai_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000):
    """Call GLM (ZAI API) with automatic fallback to OpenRouter when ZAI fails or runs out of balance."""
    if not GLM_USE_OPENROUTER and ZAI_KEY:
        try:
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
            if 'error' not in data and 'choices' in data:
                return data
            print(f"[ZAI QUOTA/BALANCE ERROR] {json.dumps(data.get('error', {}), ensure_ascii=False)}. Falling back to OpenRouter...")
        except Exception as exc:
            print(f"[ZAI EXCEPTION] {exc}. Falling back to OpenRouter...")

    if OPENROUTER_KEY:
        res = call_openrouter_chat(system_prompt, user_content, temperature, max_tokens)
        if 'error' not in res and 'choices' in res:
            return res
        # Fallback to alternate OpenRouter model if specific model fails
        print(f"[OPENROUTER PRIMARY ERROR] {json.dumps(res.get('error', {}), ensure_ascii=False)}. Trying fallback model...")
        return call_openrouter_chat(system_prompt, user_content, temperature, max_tokens, model="google/gemini-2.5-flash")

    return {"error": {"message": "ZAI API has insufficient balance and OPENROUTER_KEY is not available."}}


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
    # AI4: Check if OpenRouter key is configured
    if not OPENROUTER_KEY:
        print("[IMAGE ERROR] OPENROUTER_KEY is not configured")
        return None
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
        # AI4: Detect specific error codes and return descriptive messages
        if response.status_code == 401:
            print("[IMAGE ERROR] OpenRouter API key is invalid or expired (401 Unauthorized)")
            return None
        if response.status_code == 402:
            print("[IMAGE ERROR] OpenRouter account has insufficient credits (402 Payment Required)")
            return None
        if response.status_code == 429:
            print("[IMAGE ERROR] OpenRouter rate limit exceeded (429 Too Many Requests)")
            return None
        if 'error' in data:
            err_msg = data['error'].get('message', '') if isinstance(data['error'], dict) else str(data['error'])
            print(f"[IMAGE ERROR] OpenRouter API error: {err_msg}")
            return None
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {})
            if "images" in msg and len(msg["images"]) > 0:
                img = msg["images"][0]
                if isinstance(img, dict) and "image_url" in img:
                    return img["image_url"].get("url")
    except requests.exceptions.Timeout:
        print("[IMAGE ERROR] OpenRouter API request timed out")
    except requests.exceptions.ConnectionError:
        print("[IMAGE ERROR] Cannot connect to OpenRouter API")
    except Exception as e:
        print("[IMAGE ERROR]", str(e))
    return None

def call_image_api_with_reference(reference_image_base64, prompt):
    # AI4: Check if OpenRouter key is configured
    if not OPENROUTER_KEY:
        print("[IMAGE ERROR] OPENROUTER_KEY is not configured")
        return None
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
        # AI4: Detect specific error codes
        if response.status_code == 401:
            print("[IMAGE ERROR] OpenRouter API key is invalid or expired (401 Unauthorized)")
            return None
        if response.status_code == 402:
            print("[IMAGE ERROR] OpenRouter account has insufficient credits (402 Payment Required)")
            return None
        if response.status_code == 429:
            print("[IMAGE ERROR] OpenRouter rate limit exceeded (429 Too Many Requests)")
            return None
        if 'error' in data:
            err_msg = data['error'].get('message', '') if isinstance(data['error'], dict) else str(data['error'])
            print(f"[IMAGE ERROR] OpenRouter API error: {err_msg}")
            return None
        if "choices" in data and len(data["choices"]) > 0:
            msg = data["choices"][0].get("message", {})
            if "images" in msg and len(msg["images"]) > 0:
                img = msg["images"][0]
                if isinstance(img, dict) and "image_url" in img:
                    return img["image_url"].get("url")
    except requests.exceptions.Timeout:
        print("[IMAGE ERROR] OpenRouter API request timed out")
    except requests.exceptions.ConnectionError:
        print("[IMAGE ERROR] Cannot connect to OpenRouter API")
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
    {'num': 4,  'title': 'الرؤية والفكرة',     'type': 'content',   'desc': 'content: نص تعريفي عن المشروع + بطاقات للمكونات الرئيسية بالنص والتخطيط فقط. يمكنك استخدام ##MOODBOARD_IMAGE_1## كخلفية شفافة opacity:0.15.'},
    {'num': 5,  'title': 'الموقع الاستراتيجي', 'type': 'content',   'desc': 'content: بطاقات مميزات الموقع (القرب من الخدمات، الوصول، المدينة) بعناوين ووصف نصي فقط. يمكنك استخدام ##MOODBOARD_IMAGE_2## كخلفية شفافة opacity:0.15.'},
    {'num': 6,  'title': 'مميزات المشروع',     'type': 'content',   'desc': 'content: Grid 2×3 من البطاقات الفاخرة: كل بطاقة فيها عنوان bold + وصف قصير. خلفية كل بطاقة بيضاء مع border بلون مميز رفيع. بدون صور أو أيقونات.'},
    {'num': 7,  'title': 'مكونات المشروع',     'type': 'content',   'desc': 'content: جدول احترافي: header باللون الرئيسي وأبيض، صفوف متبادلة بلون خلفية خفيف وأبيض، صف الإجمالي بارز. أسفل الجدول 3 بطاقات ملخص. بدون صور.'},
    {'num': 8,  'title': 'افتراضات الربح التشغيلي', 'type': 'content', 'desc': 'content: معادلة بصرية كبيرة: (إيرادات سنوية − مصاريف سنوية = صافي ربح). كل عنصر في بطاقة مع سهم يربطها. أرقام بخط كبير باللون الرئيسي. بدون صور.'},
    {'num': 9,  'title': 'افتراضات التكاليف',  'type': 'content',   'desc': 'content: 3 بطاقات كبيرة: بطاقة تكلفة الأرض (مع تفاصيل السعر/م²)، بطاقة تكلفة التطوير، بطاقة الإجمالي (الأكبر والأبرز). بدون صور.'},
    {'num': 10, 'title': 'الأرباح والتخارج',   'type': 'content',   'desc': 'content: Flow diagram أفقي: بطاقة ربح تشغيلي → علامة + → بطاقة قيمة التخارج → علامة = → بطاقة إجمالي الأرباح (الأكبر). يمكنك استخدام ##MOODBOARD_IMAGE_3## كخلفية شفافة opacity:0.1.'},
    {'num': 11, 'title': 'المؤشرات المالية',   'type': 'content',   'desc': 'content: أعلى الشريحة 3 بطاقات كبيرة: ROI % و NOI و مدة الاسترداد. أسفلها مقارنة بصرية: شريطين أفقيين (إجمالي التكلفة vs إجمالي الأرباح). بدون صور.'},
    {'num': 12, 'title': 'الجدول الزمني',      'type': 'content',   'desc': 'content: Timeline أفقي: خط رأسي في المنتصف، نقاط على الخط لكل مرحلة، أشرطة ملونة باللون الرئيسي واللون المميز. Years والأرباع Q1-Q4 في الأعلى. بدون صور.'},
    {'num': 13, 'title': 'فرص الاستثمار',      'type': 'content',   'desc': 'content: 3-4 بطاقات High-Impact: عنوان bold + وصف نصي واضح. يمكنك استخدام ##MOODBOARD_IMAGE_4## كخلفية شفافة opacity:0.1.'},
    {'num': 14, 'title': 'المخاطر والافتراضات', 'type': 'content',  'desc': 'content: بطاقات رمادية وبيج هادئة بالنص فقط. عنوان فرعي: نقاط يجب التحقق منها. بدون أي صور أو أيقونات.'},
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
لا تستخدم أيقونات أو رموز أو emoji؛ اعتمد على النص والمساحات والألوان فقط.

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

    info = f"- صورة الغلاف: {'متوفرة (استخدم ##IMAGE_COVER##)' if has_cover else 'لا توجد'}\n"
    if moodboard_count > 0:
        info += f"- صور المود بورد (استخدم الرموز ##MOODBOARD_IMAGE_1## حتى ##MOODBOARD_IMAGE_{moodboard_count}##): {moodboard_count} صور متوفرة\n"
    else:
        info += "- صور المود بورد: لا توجد\n"

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

_PRESENTATION_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')


def _strip_presentation_icons(html):
    """Remove generated icon markup and emoji while retaining company logo images."""
    if not html:
        return html
    html = re.sub(r'<svg\b[^>]*>[\s\S]*?</svg\s*>', '', html, flags=re.IGNORECASE)
    html = re.sub(
        r'<(?:i|span|div)\b[^>]*(?:class|id)=["\'][^"\']*(?:icon|emoji|lucide|fa-|material-icons)[^"\']*["\'][^>]*>[\s\S]*?</(?:i|span|div)\s*>',
        '', html, flags=re.IGNORECASE
    )
    return _PRESENTATION_ICON_RE.sub('', html)


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

            # Ensure proper styling so logo never collapses or breaks
            if 'style=' in img_tag.lower():
                img_tag = re.sub(
                    r'style=["\']([^"\']*)["\']',
                    r'style="\1;max-height:50px;width:auto;object-fit:contain;display:inline-block;"',
                    img_tag,
                    flags=re.IGNORECASE
                )
            else:
                img_tag = img_tag.replace('<img', f'<img style="max-height:50px;width:auto;object-fit:contain;display:inline-block;"')
        return img_tag

    html = re.sub(r'<img\s[^>]*>', _fix_logo_img, html, flags=re.IGNORECASE)
    return html


def postprocess_slide(html, slide_num, tenant_id=None, slide_title=None, total_slides=None):
    """Post-process a slide while keeping cover and closing free of header/footer."""
    html = _strip_presentation_icons(html)

    # Cover and closing must never receive the universal header/footer. Use
    # semantic data as well as position because some compatibility callers
    # historically pass a hard-coded content-slide number.
    normalized_title = str(slide_title or '').strip().lower()
    is_closing = bool(re.search(r'ختام|closing|شكراً|شكرًا|thanks', normalized_title))
    is_cover_or_closing = int(slide_num or 0) == 1 or is_closing or (
        total_slides is not None and int(slide_num or 0) == int(total_slides)
    )

    # Clean out empty/broken img tags across all slides
    html = re.sub(r'<img\b[^>]*(?:src=["\']\s*["\']|src=["\']#(?:["\']|$)|\bsrc=["\'](?:undefined|null|none)["\'])[^>]*>', '', html, flags=re.IGNORECASE)
    def _strip_srcless_img(match):
        tag = match.group(0)
        if 'src=' not in tag.lower():
            return ''
        return tag
    html = re.sub(r'<img\s[^>]*>', _strip_srcless_img, html, flags=re.IGNORECASE)

    # Slides where <img> tags are strictly forbidden EXCEPT logo images
    NO_IMAGE_SLIDES = {2, 3, 6, 7, 8, 9, 11, 12, 14}
    if slide_num in NO_IMAGE_SLIDES:
        def _strip_non_logo(match):
            tag = match.group(0)
            if 'logo' in tag.lower() or '##LOGO##' in tag or 'tenant-assets' in tag:
                return tag
            return ''
        html = re.sub(r'<img\s[^>]*>', _strip_non_logo, html, flags=re.IGNORECASE)

    # Content slides get a header/footer; cover and closing never do.
    HEADER_FOOTER_SLIDES = set(range(2, 16))
    if slide_num in HEADER_FOOTER_SLIDES and not is_cover_or_closing:
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

    html = resolve_logo_in_html(html, tenant_id)
    return _strip_presentation_icons(html)

def generate_single_slide(system_prompt, slide_num, tenant_id=None, max_retries=2):
    """Generate one complete slide, retrying with a stricter prompt when needed."""
    base_user_msg = build_slide_user_msg(slide_num)
    slide_title = SLIDE_DEFS[slide_num - 1]['title']

    for attempt in range(1, max_retries + 2):
        try:
            user_msg = base_user_msg
            if attempt > 1:
                user_msg += (
                    "\n\nإعادة المحاولة: أعد إنشاء الشريحة كاملة من البداية. "
                    "أخرج div class=\"slide\" واحداً مغلقاً بشكل صحيح، "
                    "ولا تتوقف قبل اكتماله. لا تكتب أي شرح أو markdown."
                )
            print(f"[SLIDE-{slide_num}] Attempt {attempt}: {slide_title}")
            response = call_zai_chat(system_prompt, user_msg, max_tokens=7000)
            if 'choices' not in response or not response.get('choices'):
                print(f"[SLIDE-{slide_num}] ERROR: no choices (attempt {attempt})")
                continue
            html = extract_html_from_glm(response)
            html = postprocess_slide(html, slide_num, tenant_id)
            count = html.count('class="slide"')
            if count >= 1:
                print(f"[SLIDE-{slide_num}] OK Done ({len(html)} chars)")
                return html
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
    reference_image = data.get('referenceImage') or project_data.get('cover') or project_data.get('mainImageData') or None

    project_name = project_data.get('project_name') or project_data.get('projectName') or 'مشروع'
    project_type = project_data.get('project_type') or project_data.get('projectType') or 'سكني'
    location = project_data.get('location_address') or project_data.get('location') or 'السعودية'

    branding = db.get_branding(g.tenant_id) if hasattr(g, 'tenant_id') and g.tenant_id else {}
    raw_count = data.get('count') or (branding.get('moodboard_count') if branding else 4) or 4
    try:
        target_count = max(1, min(20, int(raw_count)))
    except (ValueError, TypeError):
        target_count = 4

    print(f"\n[IMAGES] Generating {'1 cover + ' if include_cover else ''}{target_count} moodboard images for: {project_name}, ref: {'yes' if reference_image else 'no'}")

    images = {'cover': None, 'moodboard': []}

    # 1. Cover image. The wizard requests moodboard-only images at its next step.
    if include_cover:
        print("[IMAGES] Generating cover image...")
        cover_prompt = f"Modern luxury {project_type} building in {location}, professional architectural photography, elegant design, high quality, no text, no watermark"
        images['cover'] = call_image_api(cover_prompt)
        print(f"[IMAGES] Cover: {'OK' if images['cover'] else 'FAILED'}")

    # 2. Moodboard images — use reference image (main image) to maintain visual consistency
    ref_style = ', matching the architectural style, colors, and materials of the reference image provided' if reference_image else ''
    ref_note = 'CRITICAL: NO other buildings around the building — the building stands ALONE.'
    base_prompts = [
        f"Cover photo of {project_name} — a {project_type} building in {location}{ref_style}. {ref_note} Professional architectural photography, warm golden hour lighting, premium luxury facade, photorealistic.",
        f"Right-side facade view of {project_name} — the same building from the right angle. {ref_note} Clear sky background, professional architectural photography, showing the building's right side details, materials, and textures.{ref_style}",
        f"Left-side facade view of {project_name} — the same building from the left angle. {ref_note} Clear sky background, professional architectural photography, showing the building's left side details and design elements.{ref_style}",
        f"Aerial top-down view of {project_name} — bird's eye view of the building from above. {ref_note} Professional drone photography, showing the roof, overall building shape, and surrounding empty land.{ref_style}",
        f"Close-up architectural detail view of {project_name} — showing main entrance, glass balcony finishes, and premium stone cladding.{ref_style}",
        f"Night view of {project_name} — exterior building lighting and facade illumination at dusk.{ref_style}",
        f"Interior lobby and reception view of {project_name} — luxury indoor design and materials.{ref_style}",
        f"Landscape and garden surroundings of {project_name} — outdoor green areas, lighting, and pathways.{ref_style}",
        f"Sunset golden hour panoramic view of {project_name} with dramatic sky.{ref_style}",
        f"Architectural eye-level perspective of {project_name} facade and main gate.{ref_style}",
    ]
    moodboard_prompts = base_prompts[:target_count]
    while len(moodboard_prompts) < target_count:
        moodboard_prompts.append(f"Angle {len(moodboard_prompts)+1} view of {project_name} in {location}{ref_style}. Professional architectural photography.")

    for i, prompt in enumerate(moodboard_prompts):
        print(f"[IMAGES] Generating moodboard {i+1}/{target_count} (ref: {'yes' if reference_image else 'no'})...")
        if reference_image:
            img = call_image_api_with_reference(reference_image, prompt)
        else:
            img = call_image_api(prompt)
        images['moodboard'].append(img)
        print(f"[IMAGES] Moodboard {i+1}/{target_count}: {'OK' if img else 'FAILED'}")
        if i < len(moodboard_prompts) - 1:
            time.sleep(1)

    print(f"[IMAGES] Done. Cover: {'OK' if images['cover'] else 'FAIL'}, Moodboard: {sum(1 for x in images['moodboard'] if x)}/{target_count}")
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
            # AI4: Return descriptive Arabic error based on config state
            if not OPENROUTER_KEY:
                return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'})
            return jsonify({'success': False, 'error': 'تعذر توليد الصورة — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'})
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
            if not OPENROUTER_KEY:
                return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'})
            return jsonify({'success': False, 'error': 'تعذر توليد الصورة — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'})
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
            if not OPENROUTER_KEY:
                return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'})
            return jsonify({'success': False, 'error': 'تعذر توليد الصورة — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'})
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
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    print(f"[DESIGNER] Slide {idx + 1} worker failed: {exc}")
                    results[idx] = ''

        missing = [idx + 1 for idx, html in enumerate(results) if not html]
        if missing:
            print(f"[DESIGNER] Retrying missing slides after parallel run: {missing}")
            for slide_num in missing:
                results[slide_num - 1] = generate_single_slide(
                    system_prompt, slide_num, g.tenant_id, max_retries=1
                )

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
        # Preserve the actual slide semantics. In particular, a closing slide
        # must not be treated as content and receive a header/footer.
        slide_number = data.get('slideNumber') or data.get('slide_number')
        if slide_number is None:
            raw_index = data.get('slideIndex')
            slide_number = (int(raw_index) + 1) if raw_index is not None else 2
        html = postprocess_slide(
            html,
            int(slide_number),
            tenant_id,
            slide_title=data.get('slideTitle') or data.get('currentSlideTitle') or '',
            total_slides=data.get('totalSlides') or data.get('total_slides'),
        )
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


def _designer_json_response(text):
    """Parse the first JSON object returned by the designer model."""
    if not text:
        return {}
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except Exception:
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}


def normalize_arabic_digits_py(text):
    if not text:
        return ""
    eastern = "٠١٢٣٤٥٦٧٨٩"
    western = "0123456789"
    return text.translate(str.maketrans(eastern, western))


def detect_slide_indexes_from_message_py(text, slides):
    """Detect single or multiple slide indexes from prompt text using dynamic digits, words, or titles."""
    if not text or not slides:
        return []

    norm_text = normalize_arabic_digits_py(text.strip().lower())
    count = len(slides)
    found_indexes = []

    # 1. Check ordinal word phrases
    word_map = [
        ('الحادية عشر', 11), ('الحاديه عشر', 11),
        ('الثانية عشر', 12), ('الثانيه عشر', 12),
        ('الثالثة عشر', 13), ('الثالثه عشر', 13),
        ('الرابعة عشر', 14), ('الرابعه عشر', 14),
        ('الخامسة عشر', 15), ('الخامسه عشر', 15),
        ('السادسة عشر', 16), ('السادسه عشر', 16),
        ('السابعة عشر', 17), ('السابعه عشر', 17),
        ('الثامنة عشر', 18), ('الثامنه عشر', 18),
        ('التاسعة عشر', 19), ('التاسعه عشر', 19),
        ('الأولى', 1), ('الاولى', 1), ('الأول', 1), ('الاول', 1),
        ('الثانية', 2), ('الثانيه', 2), ('الثاني', 2),
        ('الثالثة', 3), ('الثالثه', 3), ('الثالث', 3),
        ('الرابعة', 4), ('الرابعه', 4), ('الرابع', 4),
        ('الخامسة', 5), ('الخامسه', 5), ('الخامس', 5),
        ('السادسة', 6), ('السادسه', 6), ('السادس', 6),
        ('السابعة', 7), ('السابعه', 7), ('السابع', 7),
        ('الثامنة', 8), ('الثامنه', 8), ('الثامن', 8),
        ('التاسعة', 9), ('التاسعه', 9), ('التاسع', 9),
        ('العاشرة', 10), ('العاشره', 10), ('العاشر', 10),
        ('العشرين', 20), ('العشرون', 20),
        ('الثلاثين', 30), ('الثلاثون', 30)
    ]

    for word, num in word_map:
        if word in norm_text:
            idx = num - 1
            if 0 <= idx < count and idx not in found_indexes:
                found_indexes.append(idx)

    # 2. Extract digits after trigger words (شريحة, شرايح, سلايد, رقم) or lists like "7 و 9 و 20"
    trigger_match = re.search(r'(?:الشريحة|شريحة|شريحه|شرايح|سلايد|سلايدات|رقم|الأرقام|ارقام)\s*([\d\s\,\،و]+)', norm_text)
    if trigger_match:
        digit_str = trigger_match.group(1)
        raw_numbers = re.findall(r'\b\d+\b', digit_str)
        for num_s in raw_numbers:
            try:
                num = int(num_s)
                idx = num - 1
                if 0 <= idx < count and idx not in found_indexes:
                    found_indexes.append(idx)
            except ValueError:
                continue

    # Fallback to any standalone numbers in the message if no trigger matched
    if not found_indexes:
        raw_numbers = re.findall(r'\b\d+\b', norm_text)
        for num_s in raw_numbers:
            try:
                num = int(num_s)
                idx = num - 1
                if 0 <= idx < count and idx not in found_indexes:
                    found_indexes.append(idx)
            except ValueError:
                continue

    # 3. Check slide title matches
    if not found_indexes:
        for idx, s in enumerate(slides):
            title = (s.get('title') or '').strip().lower() if isinstance(s, dict) else ''
            if len(title) >= 3 and title in norm_text:
                if idx not in found_indexes:
                    found_indexes.append(idx)

    return found_indexes


def detect_slide_from_message_py(text, slides):
    indexes = detect_slide_indexes_from_message_py(text, slides)
    return indexes[0] if indexes else -1


def _designer_target_indexes(action, count, current_index, force_all=False):
    """Resolve planner targets using 1-based slide numbers from the model."""
    if force_all:
        return list(range(count))
    params = action.get('params') if isinstance(action.get('params'), dict) else action
    target = params.get('target', params.get('scope', 'current'))
    raw_indexes = params.get('indexes', params.get('slideIndexes', []))
    if isinstance(raw_indexes, int):
        raw_indexes = [raw_indexes]
    indexes = []
    if isinstance(raw_indexes, list):
        for value in raw_indexes:
            try:
                number = int(value)
                idx = number - 1
                if 0 <= idx < count and idx not in indexes:
                    indexes.append(idx)
            except (TypeError, ValueError):
                continue
    if target in ('all', 'كل', 'all_slides', 'presentation'):
        return list(range(count))
    if indexes:
        return indexes
    if 'slideIndex' in params:
        try:
            idx = int(params.get('slideIndex')) - 1
        except (TypeError, ValueError):
            idx = current_index
    else:
        idx = current_index
    return [max(0, min(idx, count - 1))] if count else []


def _designer_edit_slide(html, title, instruction, slide_index, project_data, presentation_id, branding, tenant_id=None):
    """Ask GLM for one complete slide and retry malformed responses."""
    rules = build_design_rules(branding)

    # Store base64 data URIs to avoid inflating prompt with hundreds of thousands of tokens
    base64_map = {}
    def _preserve_base64(match):
        idx = len(base64_map)
        ph = f"##PRESERVED_BASE64_{idx}##"
        base64_map[ph] = match.group(0)
        return ph

    clean_html = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', _preserve_base64, html or '')
    if len(clean_html) > 30000:
        clean_html = clean_html[:30000]

    prompt = f"""{rules}
أنت محرر شرائح. عدّل الشريحة التالية حسب الطلب، وأعد JSON فقط بالشكل:
{{"html":"<div class=\\"slide\\">...</div>","response":"رسالة عربية قصيرة"}}
حافظ على كل المحتوى المفيد والهوية البصرية. لا تستخدم روابط صور خارجية أو base64.
عنوان الشريحة: {title}
HTML الحالي:
{clean_html}
الطلب:
{instruction}"""

    if not tenant_id:
        try:
            tenant_id = g.tenant_id
        except Exception:
            tenant_id = None

    for attempt in range(1, 4):
        try:
            raw = extract_chat_content(call_zai_chat(prompt, instruction, max_tokens=7000), 'DESIGNER-EDIT')
            parsed = _designer_json_response(raw)
            output = parsed.get('html') or parsed.get('content') or parsed.get('slide_html')
            if output and ('slide' in output and '<div' in output):
                if 'class="slide"' not in output and "class='slide'" not in output:
                    output = f'<div class="slide" style="width:1280px;height:720px;position:relative;box-sizing:border-box;overflow:hidden;">{output}</div>'
                
                # Restore any preserved base64 images
                for ph, b64_str in base64_map.items():
                    output = output.replace(ph, b64_str)

                output = postprocess_slide(output, slide_index + 1, tenant_id)
                output = resolve_designer_chat_placeholders(output, project_data, presentation_id, tenant_id)
                return output, parsed.get('response') or 'تم تحديث الشريحة بنجاح.'
            print(f'[DESIGNER-EDIT] invalid HTML on attempt {attempt}')
        except Exception as exc:
            print(f'[DESIGNER-EDIT] attempt {attempt} failed: {exc}')

    return html, f'تم الحفاظ على تصميم الشريحة {slide_index + 1} لتعذر التعديل التلقائي عليها.'


@app.route('/api/designer-chat', methods=['POST'])
@require_auth
def api_designer_chat():
    """Agentic designer chat operating on one slide or the complete presentation."""
    data = request.json or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'الطلب فارغ'}), 400
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = data.get('presentationId')
    slides = data.get('slidesData') if isinstance(data.get('slidesData'), list) else []
    current_index = data.get('slideIndex', 0)
    try:
        current_index = int(current_index)
    except (TypeError, ValueError):
        current_index = 0

    if presentation_id:
        pres = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not pres:
            return jsonify({'success': False, 'error': 'العرض غير موجود أو لا يتبع هذه الشركة'}), 404
        if not project_data and pres.get('project_data'):
            try:
                project_data = clean_project_data(json.loads(pres['project_data']))
            except Exception:
                project_data = {}
        if not slides and pres.get('slides_data'):
            try:
                slides = json.loads(pres['slides_data'])
            except Exception:
                slides = []

    # Backward-compatible one-slide clients still work.
    if not slides and data.get('slideHtml'):
        slides = [{'html': data.get('slideHtml'), 'title': data.get('slideTitle', ''), 'type': 'content', 'designStyle': 'cards'}]
        current_index = 0
    if not slides:
        return jsonify({'success': False, 'error': 'لا توجد شرائح مفتوحة لتنفيذ الطلب'}), 400

    # Automatic map type change detection (satellite, roadmap, hybrid, terrain)
    msg_lowered = message.lower()
    requested_map_type = None
    if any(k in msg_lowered for k in ('مروري', 'مرورية', 'عادي', 'عادية', 'جرافيك', 'roadmap')):
        requested_map_type = 'roadmap'
    elif any(k in msg_lowered for k in ('قمر صناعي', 'ساتلايت', 'satellite')):
        requested_map_type = 'satellite'
    elif any(k in msg_lowered for k in ('هجين', 'هايبريد', 'hybrid')):
        requested_map_type = 'hybrid'
    elif any(k in msg_lowered for k in ('تضاريس', 'terrain')):
        requested_map_type = 'terrain'

    if requested_map_type and any(k in msg_lowered for k in ('خريطة', 'خريطه', 'خرائط', 'خرايط', 'map')):
        project_data['map_type'] = requested_map_type
        try:
            maps_service.generate_all_map_images(project_data, g.tenant_id, presentation_id=presentation_id, force=True)
        except Exception as me:
            print(f"[MAP TYPE REGEN ERROR] {me}")

    ALL_SLIDES_KEYWORDS = (
        'كل الشرائح', 'كل الشرايح', 'جميع الشرائح', 'كافة الشرائح', 
        'كل شريحة', 'كل السلايدات', 'الشرائح كلها', 'الشرايح كلها',
        'في الكل', 'على الكل', 'كل الرايح', 'العرض كامل', 'العرض كله',
        'كل السلايدز', 'شرايح كلها', 'عدل في كل', 'تعديل كل'
    )
    is_all_slides_request = (
        data.get('target') == 'all' or 
        data.get('scope') == 'all' or 
        any(kw in message.lower() for kw in ALL_SLIDES_KEYWORDS)
    )

    branding = db.get_branding(g.tenant_id) or {}
    summary = [{'index': i + 1, 'title': s.get('title', '') if isinstance(s, dict) else ''} for i, s in enumerate(slides)]
    all_note = "\n⚠️ تنبيه هام جداً: المستخدم طلب صراحة تعديل جميع الشرائح دون استثناء! يجب أن تعيد target='all' في الأداة edit_slides." if is_all_slides_request else ""
    planner_prompt = f"""{build_design_rules(branding)}
أنت وكيل تصميم عروض متميز ذكي يفهم كافة اللهجات العربية، المترادفات، الأرقام، وأوامر إضافة وتحديث الخرائط والتنسيقات.
حلل طلب المستخدم وخطط لتنفيذه على العرض.{all_note} أعد JSON فقط:
{{"response":"رسالة عربية تشرح ما ستفعله", "actions":[{{"tool":"edit_slides|generate_image|create_slide|chat_only", "params":{{}}}}]}}

الأدوات المتاحة:
- edit_slides: params={{"target":"current|all|indexes", "indexes":[1-based], "instruction":"التعديل المطلوبة"}}
- generate_image: params={{"prompt":"وصف الصورة", "slideIndex":1, "position":"background|right|left|inline"}}
- create_slide: params={{"title":"العنوان", "type":"content", "instruction":"محتوى الشريحة"}}

قواعد إضافة الخرائط عند طلب المستخدم (خريطة شوارع، خريطة منطقة، معالم، نطاق):
إذا طلب المستخدم إضافة خريطة أو تعديل خريطة الشريحة، يرجى توجيه edit_slides بتضمين أحد الرموز التالية داخل كود HTML للشريحة:
1. ##MAP_ACCESS## : لخريطة الشوارع المحيطة وشبكة الطرق والوصول.
2. ##MAP_OVERVIEW## : لخريطة نظرة عامة شاملة للمنطقة بالكامل.
3. ##MAP_LANDMARKS## : لخريطة المعالم والخدمات والمواقع الحيوية القريبة.
4. ##MAP_CATCHMENT## : لخريطة النطاق الجغرافي واستيعاب المنطقة.

قواعد الفهم الذكي:
1. إذا كان الطلب يتضمن تعديل كل الشرائح -> اختر target="all".
2. إذا حدد المستخدم شرائح بأرقامها أو بأسماءها (مثل: "30", "تلاتين", "7 و 9", "شريحة الموقع") -> ضع أرقام تلك الشرائح في indexes كأرقام (1-based).
3. إذا كان التعديل عاماً أو يخص الشريحة الحالية فقط -> اختر target="current".
4. إذا كان الطلب سؤالاً لا يتطلب تعديلاً -> اختر tool="chat_only".

قائمة الشرائح الحالية في العرض ({len(slides)} شريحة):
{json.dumps(summary, ensure_ascii=False)}"""
    try:
        planner_raw = extract_chat_content(call_zai_chat(planner_prompt, message, max_tokens=2500), 'DESIGNER-PLANNER')
        plan = _designer_json_response(planner_raw)
        actions = plan.get('actions', []) if isinstance(plan.get('actions'), list) else []
        if not actions:
            if is_all_slides_request:
                target = 'all'
                target_indexes = []
            else:
                req_indexes = data.get('indexes') if isinstance(data.get('indexes'), list) else []
                if not req_indexes:
                    req_indexes = [idx + 1 for idx in detect_slide_indexes_from_message_py(message, slides)]
                if req_indexes:
                    target = 'indexes'
                    target_indexes = req_indexes
                else:
                    target = 'current'
                    target_indexes = [current_index + 1]

            if any(word in message.lower() for word in ('صورة', 'صوره', 'image', 'توليد صورة')):
                actions = [{'tool': 'generate_image', 'params': {'prompt': message, 'target': target, 'indexes': target_indexes, 'slideIndex': current_index + 1}}]
            else:
                actions = [{'tool': 'edit_slides', 'params': {'target': target, 'indexes': target_indexes, 'slideIndex': current_index + 1, 'instruction': message}}]

        executed = []
        assistant_messages = []
        creative_images = data.get('creativeImages') if isinstance(data.get('creativeImages'), dict) else {}
        tenant_id = g.tenant_id
        for action in actions:
            tool = action.get('tool') if isinstance(action, dict) else ''
            params = action.get('params') if isinstance(action.get('params'), dict) else {}
            if tool in ('chat_only', 'validate_design_workspace', 'save_design_workspace'):
                continue
            if tool in ('edit_slides', 'edit_design_slide', 'edit_design_slides'):
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                instruction = params.get('instruction') or message
                if len(indexes) > 1:
                    def _edit_worker(idx):
                        with app.app_context():
                            slide_item = slides[idx] if isinstance(slides[idx], dict) else {}
                            h, r = _designer_edit_slide(
                                slide_item.get('html', ''),
                                slide_item.get('title', f'شريحة {idx + 1}'),
                                instruction,
                                idx,
                                project_data,
                                presentation_id,
                                branding,
                                tenant_id=tenant_id
                            )
                            return idx, h, r

                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(indexes))) as executor:
                        futures = [executor.submit(_edit_worker, idx) for idx in indexes]
                        results = []
                        for future in concurrent.futures.as_completed(futures):
                            try:
                                results.append(future.result())
                            except Exception as exc:
                                print(f"[PARALLEL EDIT ERROR] Slide edit failed: {exc}")

                    results.sort(key=lambda x: x[0])
                    for idx, updated_html, response_text in results:
                        slides[idx]['html'] = updated_html
                        if response_text:
                            assistant_messages.append(response_text)
                else:
                    for idx in indexes:
                        slide = slides[idx] if isinstance(slides[idx], dict) else {}
                        html, response_text = _designer_edit_slide(slide.get('html', ''), slide.get('title', f'شريحة {idx + 1}'), instruction, idx, project_data, presentation_id, branding, tenant_id=tenant_id)
                        slide['html'] = html
                        slides[idx] = slide
                        if response_text:
                            assistant_messages.append(response_text)
                executed.append({'tool': tool, 'status': 'success', 'indexes': indexes})
            elif tool in ('generate_image', 'generate_design_image', 'insert_image_into_slide'):
                prompt = params.get('prompt') or message
                image = call_image_api(prompt)
                if not image:
                    raise RuntimeError('تعذر توليد الصورة. تحقق من إعداد OpenRouter ورصيده.')
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                position = params.get('position', 'right')
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    html = slide.get('html', '')
                    if position == 'background':
                        tag = f'<div aria-hidden="true" style="position:absolute;inset:0;background-image:url(\'{image}\');background-size:cover;background-position:center;z-index:0;"></div>'
                    else:
                        side = 'right:40px' if position != 'left' else 'left:40px'
                        tag = f'<img src="{image}" alt="" style="position:absolute;{side};top:120px;width:38%;max-height:480px;object-fit:cover;z-index:2;">'
                    html = re.sub(r'(</div>\s*)$', tag + r'\1', html or '', count=1)
                    slide['html'] = html
                    slides[idx] = slide
                creative_images.setdefault('generated', []).append(image)
                executed.append({'tool': tool, 'status': 'success', 'indexes': targets, 'image': image})
            elif tool in ('create_slide', 'create_design_slide'):
                title = params.get('title') or 'شريحة جديدة'
                slide_type = params.get('type') or 'content'
                plan_slide = {'title': title, 'type': slide_type, 'design_style': params.get('designStyle', 'cards'), 'bullets': []}
                html, _ = _designer_edit_slide('<div class="slide" style="width:1280px;height:720px;"><h1>' + title + '</h1></div>', title, params.get('instruction') or message, len(slides), project_data, presentation_id, branding)
                slides.append({'html': html, 'title': title, 'type': slide_type, 'designStyle': plan_slide['design_style'], 'bullets': [], 'metrics': []})
                executed.append({'tool': tool, 'status': 'success', 'index': len(slides) - 1})
            else:
                executed.append({'tool': tool, 'status': 'skipped', 'message': 'أداة غير معروفة'})

        validation = _validate_workspace_data({'slidesData': slides})
        if not validation['valid']:
            return jsonify({'success': False, 'error': 'تم رفض التعديل لأن العرض يحتوي على شرائح غير صالحة', 'validation': validation}), 502
        if presentation_id:
            db.update_presentation(presentation_id, slides_data=slides, slide_count=len(slides), status='edited')
        response_text = plan.get('response') or 'تم تنفيذ طلبك على العرض بالكامل.'
        if assistant_messages:
            response_text += ' ' + ' '.join(dict.fromkeys(assistant_messages))
        return jsonify({'success': True, 'data': {'action': 'workspace_update', 'response': response_text, 'slidesData': slides, 'creativeImages': creative_images, 'actions': executed, 'validation': validation}})
    except Exception as exc:
        print(f'[DESIGNER-CHAT ERROR] {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 502


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
        options = None
        if f.get('field_options'):
            try:
                options = json.loads(f['field_options'])
                if isinstance(options, str):
                    options = [x.strip() for x in options.split(',') if x.strip()]
            except Exception:
                options = [x.strip() for x in str(f['field_options']).split(',') if x.strip()]

        result.append({
            'id': f['id'],
            'fieldKey': f['field_key'],
            'fieldLabel': f['field_label'],
            'fieldType': f['field_type'],
            'fieldOptions': options,
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
            field_key = f'field_{_uuid.uuid4().hex[:6]}'

    valid_types = ['text', 'number', 'textarea', 'select', 'date', 'image']
    if field_type not in valid_types:
        return jsonify({'error': f'Invalid fieldType. Must be one of: {valid_types}'}), 400

    # A field must belong to one of this tenant's visible sections.  Keep
    # ``general`` as a backwards-compatible fallback for older custom fields
    # and for fields whose custom section was deleted.
    section_key = data.get('sectionKey', 'general')
    if not isinstance(section_key, str):
        return jsonify({'error': 'sectionKey must be a string'}), 400
    section_key = section_key.strip()
    valid_section_keys = {'general'} | {section['key'] for section in db.get_all_sections(g.tenant_id)}
    if section_key not in valid_section_keys:
        # If the user or AI suggests a new custom section, create it automatically.
        if section_key and section_key not in {s['key'] for s in db.FIELD_SECTIONS}:
            db.add_custom_section(g.tenant_id, section_key, section_key.replace('_', ' ').title())
            valid_section_keys.add(section_key)
    if section_key not in valid_section_keys:
        return jsonify({'error': 'Invalid sectionKey for this company'}), 400

    raw_opts = (
        data.get('fieldOptions') or data.get('field_options') or 
        data.get('options') or data.get('choices')
    )
    field_options = db._normalize_options_list(raw_opts)
    if field_options and field_type != 'select':
        field_type = 'select'

    field_id = db.add_custom_field(
        tenant_id=g.tenant_id,
        field_key=field_key,
        field_label=field_label,
        field_type=field_type,
        field_options=field_options,
        is_required=data.get('isRequired', False),
        placeholder=data.get('placeholder'),
        default_value=data.get('defaultValue'),
        ai_hint=data.get('aiHint'),
        sort_order=data.get('sortOrder', 100),
        section_key=section_key,
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
    if 'sectionKey' in data:
        section_key = data['sectionKey']
        if not isinstance(section_key, str):
            return jsonify({'error': 'sectionKey must be a string'}), 400
        section_key = section_key.strip()
        valid_section_keys = {'general'} | {section['key'] for section in db.get_all_sections(g.tenant_id)}
        if section_key not in valid_section_keys:
            return jsonify({'error': 'Invalid sectionKey for this company'}), 400
        # Persist the normalized key rather than the untrimmed request value.
        data['sectionKey'] = section_key

    updates = {}
    for k in ['fieldKey', 'field_key', 'fieldLabel', 'field_label', 'fieldType', 'field_type',
              'fieldOptions', 'field_options', 'options', 'choices', 'sectionKey', 'section_key',
              'isRequired', 'is_required', 'isActive', 'is_active', 'sortOrder', 'sort_order',
              'placeholder', 'defaultValue', 'default_value', 'aiHint', 'ai_hint']:
        if k in data:
            db_key = {
                'fieldKey': 'field_key', 'field_key': 'field_key',
                'fieldLabel': 'field_label', 'field_label': 'field_label',
                'fieldType': 'field_type', 'field_type': 'field_type',
                'fieldOptions': 'field_options', 'field_options': 'field_options',
                'options': 'field_options', 'choices': 'field_options',
                'sectionKey': 'section_key', 'section_key': 'section_key',
                'isRequired': 'is_required', 'is_required': 'is_required',
                'isActive': 'is_active', 'is_active': 'is_active',
                'sortOrder': 'sort_order', 'sort_order': 'sort_order',
                'defaultValue': 'default_value', 'default_value': 'default_value',
                'aiHint': 'ai_hint', 'ai_hint': 'ai_hint',
            }.get(k, k)
            updates[db_key] = data[k]

    if 'field_options' in updates:
        updates['field_options'] = db._normalize_options_list(updates['field_options'])
        if updates['field_options']:
            updates['field_type'] = 'select'

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
    section_keys = [s['key'] for s in db.get_all_sections(g.tenant_id)]

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

    training_context = db.get_training_context(g.tenant_id) or ''
    configured_min = branding.get('min_slides', 5)
    configured_max = branding.get('max_slides', 30)

    effective_max_slides = max(1, configured_max)
    effective_min_slides = min(configured_min, effective_max_slides)

    # Search training context only for explicit min slide constraints
    matches = re.findall(r'(?:أقل|لا يقل عن|بدون أن يقل عن|الحد الأدنى|من|حوالي|أقل عدد|عدد الشرائح.*?لا يقل عن|الالتزام بـ).*?(\d+)', training_context)
    if matches:
        try:
            nums = [int(m) for m in matches if 1 <= int(m) <= 50]
            if nums:
                detected_min = max(nums)
                effective_min_slides = min(max(effective_min_slides, detected_min), effective_max_slides)
        except ValueError:
            pass

    effective_branding = dict(branding)
    effective_branding['min_slides'] = effective_min_slides
    effective_branding['max_slides'] = effective_max_slides
    if effective_branding.get('default_slide_count', 0) > effective_max_slides:
        effective_branding['default_slide_count'] = effective_max_slides

    prompt = build_slide_plan_prompt(project_data, effective_branding)
    if training_context:
        prompt = f"## بيانات خاصة بالشركة والتزام بحد الشرائح\nتنبيه هام جداً: التزم بحد الشرائح لهذه الشركة ({effective_min_slides} إلى {effective_max_slides} شريحة كحد أقصى).\n{training_context}\n\n---\n\n{prompt}"

    def build_fallback_plan(b):
        count = max(effective_min_slides, min(b.get('max_slides', 35), b.get('default_slide_count', effective_min_slides)))
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
        plan = build_fallback_plan(effective_branding)

    # Enforce min and max slide counts strictly on generated plan
    slides = plan.get('slides', [])

    if len(slides) < effective_min_slides:
        print(f"[SLIDE-PLAN ENFORCE] Plan returned {len(slides)} slides, auto-padding to effective_min_slides ({effective_min_slides})")
        needed_extra = effective_min_slides - len(slides)
        extra_topics = [
            {'title': 'مؤشرات الأداء والقيمة المضافة', 'style': 'dashboard', 'bullets': ['تحليل العائد الاستثماري المتوقع', 'معدل الإشغال والاستدامة', 'قيمة الأصول على المدى الطويل']},
            {'title': 'المواصفات الفنية وجودة المواد', 'style': 'cards', 'bullets': ['جودة التشطيبات والمواد المستخدمة', 'أنظمة التكييف والعزل الحراري', 'الضمانات وخدمات ما بعد البيع']},
            {'title': 'التحليل البيئي والمحيط المباشر', 'style': 'text', 'bullets': ['سهولة الوصول والمحاور الرئيسية', 'قرب المشروع من المرافق والمراكز الحيوية', 'جودة البيئة العمرانية المحيطة']},
            {'title': 'الخطة الزمنية ومراحل التطوير', 'style': 'timeline', 'bullets': ['مرحلة التخطيط والدراسات الأولية', 'مرحلة التنفيذ والإنشاءات', 'مرحلة التسليم والتشغيل']},
        ]
        insert_idx = max(1, len(slides) - 1)
        if len(slides) >= 2 and slides[-2].get('type') == 'moodboard':
            insert_idx = max(1, len(slides) - 2)

        for i in range(needed_extra):
            topic = extra_topics[i % len(extra_topics)]
            new_slide = {
                'title': topic['title'] + (f" ({i+1})" if i >= len(extra_topics) else ""),
                'type': 'content',
                'design_style': topic['style'],
                'requires_image': False,
                'bullets': topic['bullets'],
                'content_density': 'medium',
            }
            slides.insert(insert_idx, new_slide)
            insert_idx += 1

    # Strictly trim slides if LLM generated more slides than max_slides
    if len(slides) > effective_max_slides:
        print(f"[SLIDE-PLAN TRIM] Plan returned {len(slides)} slides, trimming strictly to effective_max_slides ({effective_max_slides})")
        if effective_max_slides == 1:
            slides = slides[:1]
        else:
            first_slides = slides[:1]
            last_slides = slides[-1:]
            middle_count = max(0, effective_max_slides - 2)
            middle_slides = slides[1:1+middle_count]
            slides = first_slides + middle_slides + last_slides

    plan['proposed_count'] = len(slides)
    plan['slides'] = slides

    is_valid, issues = validate_slide_plan(plan, effective_branding)
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
    """Geocode an address or Google Maps link to lat/lng."""
    data = request.json or {}
    address = data.get('address', '').strip()
    maps_link = data.get('maps_link', '').strip()

    # If address itself is a Google Maps URL, treat it as maps_link
    if address.startswith('http') and not maps_link:
        maps_link = address

    if maps_link:
        coords = maps_service.extract_coords_from_maps_link(maps_link)
        if coords:
            print(f"[MAPS LINK] Extracted coords from link: {coords}")
            return jsonify({
                'success': True,
                'lat': coords['lat'],
                'lng': coords['lng'],
                'formatted_address': address if not address.startswith('http') else 'تم الاستخراج من رابط خرائط جوجل',
                'source': 'maps_link'
            })
        elif address and not address.startswith('http'):
            result = maps_service.geocode_address(address)
            if result.get('success'):
                result['source'] = 'geocode_fallback'
                return jsonify(result)
            return jsonify({'success': False, 'error': 'ما قدرنا نحدد الموقع من هذا الرابط — جربي لصق رابط قوقل ماب مباشر أو كتابة العنوان النصي'})

    if not address:
        return jsonify({'error': 'address or maps_link is required'}), 400

    if address.startswith('http'):
        coords = maps_service.extract_coords_from_maps_link(address)
        if coords:
            return jsonify({
                'success': True,
                'lat': coords['lat'],
                'lng': coords['lng'],
                'formatted_address': 'تم الاستخراج من رابط خرائط جوجل',
                'source': 'maps_link'
            })
        return jsonify({'success': False, 'error': 'تعذر استخراج الإحداثيات من هذا الرابط'}), 400

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
        return jsonify({'success': False, 'error': result['error']}), 200
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


@app.route('/api/generate-slide-single', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slide_single():
    """Generate a single slide by index. Returns one slide HTML."""
    from slide_engine import generate_single_slide, build_design_rules, _replace_map_placeholders, _replace_creative_image_placeholders, _replace_data_placeholders
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    slide_plan = data.get('slidePlan', {})
    images = data.get('images', {})
    slide_index = int(data.get('slideIndex', 0))

    if not slide_plan or 'slides' not in slide_plan:
        return jsonify({'error': 'slidePlan with slides array is required'}), 400

    slides = slide_plan.get('slides', [])
    if slide_index < 0 or slide_index >= len(slides):
        return jsonify({'error': 'Invalid slide index'}), 400

    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400

    # Build map placeholders if needed
    map_placeholders = {}
    need_maps = (slide_index == 0 or 'map' in slides[slide_index].get('type', ''))
    has_maps = isinstance(images, dict) and isinstance(images.get('map_placeholders'), dict) and bool(images.get('map_placeholders'))
    if need_maps and not has_maps:
        map_result = maps_service.generate_all_map_images(project_data, g.tenant_id, presentation_id=data.get('presentationId'), force=True)
        if map_result.get('placeholders'):
            if not isinstance(images, dict):
                images = {'cover': None, 'moodboard': []}
            for placeholder, path in map_result['placeholders'].items():
                if path and os.path.exists(path):
                    rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
                    map_placeholders[placeholder] = f"/{rel_path}"
                else:
                    map_placeholders[placeholder] = None
            images['map_placeholders'] = map_placeholders
            images['map_landmarks'] = map_result.get('landmarks', [])
            project_data['_resolved_location'] = {'lat': map_result['lat'], 'lng': map_result['lng']}
    elif has_maps:
        map_placeholders = images.get('map_placeholders', {})
        project_data['_resolved_location'] = {'lat': project_data.get('_resolved_location', {}).get('lat'), 'lng': project_data.get('_resolved_location', {}).get('lng')}

    images_info = _get_images_info(images)
    training_context = db.get_training_context(g.tenant_id)

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

    def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
        if training_context:
            sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
        return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2)

    slide = slides[slide_index]
    total = len(slides)
    html = generate_single_slide(system_prompt, slide, slide_index + 1, total, branding, call_glm_fn, max_retries=3)

    # Never turn a failed generation into a fake successful slide. The client
    # can retry the request, but it must not save an incomplete presentation.
    if not html or html.count('class="slide"') != 1:
        title = slide.get('title', f'شريحة {slide_index + 1}')
        return jsonify({
            'success': False,
            'error': f'تعذر توليد الشريحة {slide_index + 1}: {title}',
            'slideIndex': slide_index,
            'totalSlides': total,
        }), 502

    if map_placeholders:
        html = _replace_map_placeholders(html, map_placeholders)
    html = _replace_creative_image_placeholders(html, images, slide.get('type', 'content'))
    html = _replace_data_placeholders(html, project_data, branding)

    return jsonify({
        'success': True,
        'slide': {
            'html': html,
            'title': slide.get('title', f'شريحة {slide_index + 1}'),
            'type': slide.get('type', 'content'),
            'designStyle': slide.get('design_style', 'cards'),
        },
        'slideIndex': slide_index,
        'totalSlides': total,
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
                'html': postprocess_slide(html or '', i + 1, g.tenant_id),
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


@app.route('/api/presentations/<pres_id>', methods=['DELETE'])
@require_permission('create_presentation')
def api_delete_presentation(pres_id):
    """Delete a presentation for the current tenant."""
    if not db.delete_presentation(pres_id, g.tenant_id):
        return jsonify({'error': 'Presentation not found'}), 404
    return jsonify({'success': True})


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
    for s in slides:
        if isinstance(s, dict) and 'html' in s and isinstance(s['html'], str):
            s['html'] = resolve_logo_in_html(s['html'], g.tenant_id)
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
# PROJECT DRAFTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _project_draft_actor_id():
    """Return a non-NULL, tenant-scoped owner for the unified project draft."""
    return g.user_id or f'tenant-admin:{g.tenant_id}'


def _project_draft_actor_name():
    return g.user_name or 'Company administrator'

@app.route('/api/project-draft', methods=['GET'])
@require_auth
def api_get_project_draft():
    """Get the current user's project draft."""
    draft = db.get_project_draft(g.tenant_id, _project_draft_actor_id())
    if not draft:
        return jsonify({'success': True, 'draft': None})
    return jsonify({'success': True, 'draft': draft})


@app.route('/api/project-draft', methods=['POST'])
@require_auth
def api_save_project_draft():
    """Save or update the current user's project draft."""
    data = request.json or {}
    draft_data = data.get('draftData', {})
    if not isinstance(draft_data, dict):
        return jsonify({'error': 'draftData must be an object'}), 400
    # Absence or {} means preserve already-reviewed sections (legacy clients send {}).
    section_statuses = data.get('sectionStatuses')
    if section_statuses is not None and not isinstance(section_statuses, dict):
        return jsonify({'error': 'sectionStatuses must be an object'}), 400
    status = data.get('status', 'draft')
    if status not in {'draft', 'submitted'}:
        status = 'draft'
    draft_id = db.save_project_draft(
        g.tenant_id, _project_draft_actor_id(), draft_data, section_statuses, status
    )
    return jsonify({'success': True, 'draftId': draft_id})


@app.route('/api/project-drafts', methods=['GET'])
@require_auth
def api_get_all_project_drafts():
    """Get all saved project drafts for the tenant."""
    drafts = db.get_all_project_drafts(g.tenant_id)
    return jsonify({'success': True, 'drafts': drafts})


@app.route('/api/project-draft/<draft_id>', methods=['GET'])
@require_auth
def api_get_project_draft_by_id(draft_id):
    """Get a specific project draft by ID."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    return jsonify({'success': True, 'draft': draft})


@app.route('/api/project-draft/<draft_id>', methods=['DELETE'])
@require_auth
def api_delete_project_draft_by_id(draft_id):
    """Delete a specific project draft by ID."""
    db.delete_project_draft_by_id(g.tenant_id, draft_id)
    return jsonify({'success': True})


@app.route('/api/project-draft/section-status', methods=['POST'])
@require_auth
def api_update_section_status():
    """Update a single section's status in the draft."""
    data = request.json or {}
    section_key = data.get('sectionKey')
    section_status = data.get('sectionStatus')
    if not isinstance(section_key, str) or not section_key or section_status not in {'draft', 'approved'}:
        return jsonify({'error': 'A valid sectionKey and sectionStatus are required'}), 400
    result = db.update_draft_section_status(
        g.tenant_id, _project_draft_actor_id(), section_key, section_status
    )
    if not result:
        return jsonify({'error': 'Unable to update section status'}), 400
    return jsonify({'success': True})


@app.route('/api/project-draft/request-approval', methods=['POST'])
@require_auth
def api_request_project_draft_approval():
    """Request one overall approval after all tracked sections are approved."""
    draft = db.request_project_draft_approval(
        g.tenant_id, _project_draft_actor_id(), _project_draft_actor_id(), _project_draft_actor_name()
    )
    if draft.get('error') == 'draft_not_found':
        return jsonify({'error': 'No project draft found'}), 404
    if draft.get('error') == 'sections_not_approved':
        return jsonify({
            'error': 'All project sections must be approved before requesting approval',
            'sectionStatuses': draft.get('section_statuses', {})
        }), 400
    return jsonify({'success': True, 'draft': draft})


@app.route('/api/project-draft/approval-status', methods=['GET'])
@require_auth
def api_project_draft_approval_status():
    """Return the current actor's overall draft-review state."""
    draft = db.get_project_draft(g.tenant_id, _project_draft_actor_id())
    return jsonify({'success': True, 'approval': draft})


@app.route('/api/project-draft/pending-approvals', methods=['GET'])
@require_permission('approvals')
def api_pending_project_draft_approvals():
    """List tenant-only draft approval requests for authorized reviewers."""
    drafts = db.get_pending_project_drafts(g.tenant_id)
    return jsonify({'success': True, 'drafts': drafts})


@app.route('/api/project-draft/review', methods=['POST'])
@require_permission('approvals')
def api_review_project_draft():
    """Approve or return a tenant-scoped project draft for correction."""
    data = request.json or {}
    draft_id = data.get('draftId')
    review_status = data.get('status')
    note = (data.get('note') or '').strip()[:3000]
    if not isinstance(draft_id, str) or not draft_id or review_status not in {'approved', 'rejected'}:
        return jsonify({'error': 'draftId and status (approved or rejected) are required'}), 400
    if not db.review_project_draft(
        g.tenant_id, draft_id, review_status, _project_draft_actor_id(), _project_draft_actor_name(), note
    ):
        return jsonify({'error': 'Pending draft approval not found'}), 404
    return jsonify({'success': True})



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
    except db_driver.IntegrityError:
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
    except db_driver.IntegrityError:
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
    """Get available field sections (built-in + custom) and current user's allowed sections."""
    available = db.get_all_sections(g.tenant_id)
    allowed = db.get_user_field_sections(g.user_id, g.tenant_id) if g.user_id else {s['key']: True for s in available}
    return jsonify({'success': True, 'available': available, 'allowed': allowed})


@app.route('/api/field-sections/custom', methods=['POST'])
@require_permission('custom_fields')
def api_add_custom_section():
    """Create a custom field section."""
    data = request.json or {}
    label = (data.get('label') or '').strip()
    if not label:
        return jsonify({'error': 'اسم القسم مطلوب'}), 400
    # Generate key from label if not provided
    key = (data.get('key') or '').strip().lower().replace(' ', '_').replace('-', '_')
    if not key:
        import re as _re
        # Transliterate Arabic to approximate key
        ar_map = {'أ': 'a', 'إ': 'a', 'آ': 'a', 'ا': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th', 'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'th', 'ر': 'r', 'ز': 'z', 'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n', 'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ة': 'a', 'ء': '', 'ئ': 'y', 'ؤ': 'w'}
        key = ''.join(ar_map.get(c, c) for c in label)
        key = _re.sub(r'[^a-zA-Z0-9_]', '', key)
        if not key:
            key = 'section_' + str(_uuid.uuid4())[:8]
    # Prevent collision with built-in keys
    builtin_keys = {s['key'] for s in db.FIELD_SECTIONS}
    if key in builtin_keys:
        return jsonify({'error': 'لا يمكن استخدام اسم قسم موجود مسبقاً'}), 400
    sort_order = int(data.get('sortOrder', 100))
    section_id = db.add_custom_section(g.tenant_id, key, label, sort_order)
    if not section_id:
        return jsonify({'error': 'قسم بهذا الاسم موجود مسبقاً'}), 409
    return jsonify({'success': True, 'sectionId': section_id, 'key': key}), 201


@app.route('/api/field-sections/custom/<section_key>', methods=['PUT'])
@require_permission('custom_fields')
def api_update_custom_section(section_key):
    """Update a custom field section."""
    # The route is deliberately custom-only: built-in section labels and
    # structure stay stable, while each company can rename its own additions.
    if not db.get_custom_section(g.tenant_id, section_key):
        return jsonify({'error': 'Custom section not found'}), 404

    data = request.json or {}
    updates = {}
    if 'label' in data:
        label = (data.get('label') or '').strip()
        if not label:
            return jsonify({'error': 'اسم القسم لا يمكن أن يكون فارغاً'}), 400
        updates['section_label'] = label
    if 'sortOrder' in data:
        updates['sort_order'] = int(data.get('sortOrder', 100))
    if 'isActive' in data:
        updates['is_active'] = 1 if data.get('isActive') else 0
    if not updates:
        return jsonify({'error': 'لا توجد تغييرات'}), 400
    db.update_custom_section(g.tenant_id, section_key, **updates)
    return jsonify({'success': True})


@app.route('/api/field-sections/custom/<section_key>', methods=['DELETE'])
@require_permission('custom_fields')
def api_delete_custom_section(section_key):
    """Delete a custom field section. Fields move to 'general'."""
    # Prevent deleting built-in sections
    builtin_keys = {s['key'] for s in db.FIELD_SECTIONS}
    if section_key in builtin_keys:
        return jsonify({'error': 'لا يمكن حذف قسم أساسي'}), 400
    if not db.get_custom_section(g.tenant_id, section_key):
        return jsonify({'error': 'Custom section not found'}), 404
    db.delete_custom_section(g.tenant_id, section_key)
    return jsonify({'success': True})


@app.route('/api/users/<user_id>/field-sections', methods=['GET'])
@require_permission('manage_users')
def api_get_user_field_sections(user_id):
    """Get effective field section visibility for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    sections = db.get_user_field_sections(user_id, g.tenant_id)
    return jsonify({'success': True, 'sections': sections, 'available': db.get_all_sections(g.tenant_id)})


@app.route('/api/users/<user_id>/field-sections', methods=['PUT'])
@require_permission('manage_users')
def api_set_user_field_sections(user_id):
    """Set field section visibility for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404

    data = request.json or {}
    sections = data.get('sections', {})
    all_keys = {s['key'] for s in db.get_all_sections(g.tenant_id)}
    for key, granted in sections.items():
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
    tenant_dir = os.path.join(UPLOADS_DIR, tenant_id)
    if os.path.isdir(tenant_dir):
        for extension in ALLOWED_IMAGE_EXTENSIONS:
            logo_path = os.path.join(tenant_dir, f'logo{extension}')
            if os.path.isfile(logo_path):
                mimetype = 'image/png' if extension == '.png' else 'image/jpeg' if extension in ('.jpg', '.jpeg') else 'image/webp'
                resp = send_file(logo_path, mimetype=mimetype)
                resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
                return resp
    # Fallback to default system logo if no tenant logo was uploaded yet
    default_logo = os.path.join(os.path.dirname(__file__), 'assets', 'logo.png')
    if os.path.isfile(default_logo):
        resp = send_file(default_logo, mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
        return resp
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
    for entry in entries:
        if entry.get('image_path'):
            entry['imageUrl'] = f"/api/training/{entry['id']}/image"
        # Never expose the on-disk, tenant-specific storage path to the browser.
        entry.pop('image_path', None)
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
    updated = db.update_training_entry(
        g.tenant_id, entry_id,
        **{k: data[k] for k in ['title', 'content', 'category', 'is_active', 'image_description'] if k in data}
    )
    if not updated:
        return jsonify({'error': 'Training entry not found'}), 404
    return jsonify({'success': True})


@app.route('/api/training/<entry_id>', methods=['DELETE'])
@require_permission('training_data')
def api_delete_training(entry_id):
    """Delete a training data entry."""
    if not db.delete_training_entry(g.tenant_id, entry_id):
        return jsonify({'error': 'Training entry not found'}), 404
    return jsonify({'success': True})


@app.route('/api/training/upload-image', methods=['POST'])
@require_permission('training_data')
def api_upload_training_image():
    """Upload an image for training and analyze it with AI Vision.
    Accepts multipart form data with 'image' file and optional 'title' and 'category'.
    Returns the AI-generated analysis as training content."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400
    
    title = (request.form.get('title') or '').strip() or 'Training image'
    category = (request.form.get('category') or 'image_reference').strip()[:80]
    image_type = (request.form.get('imageType') or 'reference').strip().lower()
    image_description = (request.form.get('description') or '').strip()[:4000]
    consent = (request.form.get('companyDataConsent') or '').strip().lower()
    valid_image_types = {'logo', 'watermark', 'reference', 'design_sample'}
    if image_type not in valid_image_types:
        return jsonify({'error': 'imageType must be logo, watermark, reference, or design_sample'}), 400
    if consent not in {'1', 'true', 'yes', 'on'}:
        return jsonify({'error': 'Company data consent is required before uploading a training image'}), 400

    # Validate bytes with Pillow instead of trusting the extension or browser MIME type.
    try:
        from PIL import Image, UnidentifiedImageError
        image = Image.open(file.stream)
        if image.width * image.height > 30_000_000:
            return jsonify({'error': 'Image dimensions are too large'}), 400
        detected_format = (image.format or '').upper()
        image.verify()
        file.stream.seek(0)
    except (UnidentifiedImageError, OSError, ValueError):
        return jsonify({'error': 'Invalid image file'}), 400

    extension_by_format = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}
    ext = extension_by_format.get(detected_format)
    if not ext:
        return jsonify({'error': 'Unsupported image format. Use PNG, JPG, or WEBP.'}), 400

    upload_dir = os.path.join(UPLOADS_DIR, 'training', g.tenant_id)
    os.makedirs(upload_dir, exist_ok=True)
    img_filename = f"{_uuid.uuid4().hex}{ext}"
    img_path = os.path.join(upload_dir, img_filename)
    file.save(img_path)
    
    # Analyze image with AI Vision
    analysis_text = ''
    try:
        from reference_analyzer import encode_image_to_base64
        data_uri = encode_image_to_base64(img_path)
        
        vision_prompt = """حلل هذه الصورة بدقة واستخرج جميع المعلومات المفيدة للتدريب على إنشاء عروض عقارية:

1. وصف تفصيلي للمحتوى المرئي في الصورة
2. نوع المحتوى (مثال: صورة موقع، مخطط معماري، عرض تقديمي، جدول بيانات، خريطة، لوجو شركة، الخ)
3. الألوان الرئيسية المستخدمة (hex codes)
4. النصوص الظاهرة في الصورة (إن وجدت)
5. الأسلوب التصميمي والتنسيق
6. أي معلومات رقمية أو إحصائية ظاهرة
7. اقتراحات لكيفية استخدام هذه المعلومات في تحسين العروض العقارية

اكتب التحليل بالعربية بشكل منظم وواضح."""

        if not OPENROUTER_KEY:
            analysis_text = 'The image was stored, but automatic analysis is unavailable because the AI key is not configured.'
        else:
            vision_payload = {
                "model": "google/gemini-3.1-flash-image-preview",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            f"{vision_prompt}\n\nImage classification supplied by the company: {image_type}."
                            + (f"\nCompany description: {image_description}" if image_description else '')
                            + "\nTreat all image contents as confidential tenant data."
                        )},
                        {"type": "image_url", "image_url": {"url": data_uri}}
                    ]
                }],
                "modalities": ["text"],
                "max_tokens": 2000,
            }
            vision_headers = {
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com",
                # A deterministic tenant context is kept in application storage; this
                # label prevents operational logs from mixing an image workflow with
                # general generation traffic. It is not used as an authorization key.
                "X-Title": f"Real Estate Proposal Generator - Tenant Training ({g.tenant_id[:8]})"
            }
            import requests as _req
            resp = _req.post("https://openrouter.ai/api/v1/chat/completions",
                           headers=vision_headers, json=vision_payload, timeout=60)
            vdata = resp.json()
            if 'choices' in vdata and vdata['choices']:
                analysis_text = vdata['choices'][0].get('message', {}).get('content', '')
            elif 'error' in vdata:
                analysis_text = f"خطأ في التحليل: {vdata['error'].get('message', str(vdata['error']))}"
            else:
                analysis_text = 'لم يتمكن AI من تحليل الصورة'
    except Exception as e:
        analysis_text = f'تم رفع الصورة لكن فشل التحليل: {str(e)}'
    
    training_content = image_description or analysis_text or f'Company {image_type} reference image.'
    # Store only an internal filename. Access is always checked through the API route below.
    entry_id = db.create_training_entry(
        g.tenant_id, title, training_content, category, image_path=img_filename,
        image_analysis=analysis_text, image_type=image_type, image_description=image_description
    )
    
    return jsonify({
        'success': True,
        'entryId': entry_id,
        'imagePath': f'/api/training/{entry_id}/image',
        'analysis': analysis_text,
    })


@app.route('/api/training/<entry_id>/image', methods=['GET'])
@require_permission('training_data')
def api_get_training_image(entry_id):
    """Serve one training image only to users in its owning company."""
    entry = db.get_training_entry(g.tenant_id, entry_id)
    if not entry or not entry.get('image_path'):
        return jsonify({'error': 'Training image not found'}), 404

    filename = os.path.basename(str(entry['image_path']))
    if not filename or filename != entry['image_path']:
        # Legacy entries may contain a former URL; accept its filename but never its path.
        filename = os.path.basename(str(entry['image_path']).replace('\\', '/'))
    tenant_dir = os.path.abspath(os.path.join(UPLOADS_DIR, 'training', g.tenant_id))
    image_path = os.path.abspath(os.path.join(tenant_dir, filename))
    if os.path.commonpath([tenant_dir, image_path]) != tenant_dir or not os.path.isfile(image_path):
        return jsonify({'error': 'Training image not found'}), 404

    mimetype = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(
        os.path.splitext(filename)[1].lower(), 'application/octet-stream'
    )
    response = send_file(image_path, mimetype=mimetype, conditional=True)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@app.route('/api/training-chat', methods=['POST'])
@require_permission('training_data')
def api_training_chat():
    """Super Agent — full server-aware AI assistant for company admin.
    Understands and can modify: branding, fields, slides, moodboard, users,
    permissions, sections, presentations, and training data."""
    data = request.json or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'message is required'}), 400

    history = data.get('history') or []
    workspace = data.get('workspace') or {}
    history_lines = []
    for turn in history[-12:]:
        role = 'المستخدم' if turn.get('role') == 'user' else 'المساعد'
        history_lines.append(f"{role}: {turn.get('text', '')}")
    context = '\n'.join(history_lines)

    # ── Build real-time system state ──────────────────────────────────────
    system_state = _build_agent_system_state(g.tenant_id)
    workspace_state = _summarize_agent_workspace(workspace, g.tenant_id)

    # ── System prompt ─────────────────────────────────────────────────────
    system_prompt = f"""أنت "وكيل الإدارة الذكي" (Super Agent) — المساعد التنفيذي الكامل لأدمن الشركة في منصة العروض التقديمية العقارية.
أنت لست مجرد chatbot — أنت وكيل تنفيذي يمتلك صلاحيات كاملة لقراءة وتعديل جميع إعدادات النظام مباشرة.

## حالة النظام الحالية:
{system_state}

## مساحة العمل المفتوحة حالياً:
{workspace_state}

## الأدوات المتاحة لك (Tools):
يمكنك تنفيذ أي من الإجراءات التالية بإرجاع JSON action ضمن ردك.
ضع الـ action داخل بلوك ```action ... ``` في ردك.

### 1. تعديل الهوية البصرية:
```action
{{"tool": "update_branding", "params": {{"primary_color": "#HEX", "secondary_color": "#HEX", "accent_color": "#HEX", "background_color": "#HEX", "text_color": "#HEX", "font_family": "...", "font_arabic": "...", "design_template": "modern|classic|dark|corporate|luxury", "card_style": "bordered|shadow|flat|glass", "slide_ratio": "16:9|4:3", "header_enabled": 1, "footer_enabled": 1, "header_height": 56, "footer_height": 36, "moodboard_enabled": 1, "cover_image_enabled": 1, "tagline": "..."}}}}
```
ملاحظة: أرسل فقط الحقول التي يريد المستخدم تعديلها، ليس كلها.

### 2. تعديل إعدادات الشرائح:
```action
{{"tool": "update_branding", "params": {{"min_slides": N, "max_slides": N, "default_slide_count": N, "moodboard_count": N}}}}
```

### 3. عرض الحقول:
```action
{{"tool": "list_fields"}}
```

### 4. إضافة حقل جديد:
```action
{{"tool": "add_field", "params": {{"field_label": "...", "field_type": "text|number|textarea|select|date", "field_options": ["اختيار 1", "اختيار 2"], "section_key": "basic|location|financial|project|swot|...", "is_required": false, "ai_hint": "...", "placeholder": "..."}}}}
```

### 5. تعديل حقل (تفعيل/تعطيل/تغيير الخيارات):
```action
{{"tool": "update_field", "params": {{"field_key": "...", "updates": {{"is_active": 1, "field_label": "...", "field_type": "select", "field_options": ["اختيار 1", "اختيار 2"], "ai_hint": "..."}}}}}}
```
ملاحظة: عند إضافة أو تحديث خيارات قائمة مسدلة (dropdown)، تأكد دائماً من تمرير "field_type": "select" و تمرير مصفوفة JSON تحتوي الخيارات بالشكل: "field_options": ["خيار 1", "خيار 2"].

### 6. حذف حقل مخصص:
```action
{{"tool": "delete_field", "params": {{"field_key": "..."}}}}
```

### 7. عرض المستخدمين:
```action
{{"tool": "list_users"}}
```

### 8. تعديل صلاحيات موظف:
```action
{{"tool": "set_permission", "params": {{"user_email": "...", "permission": "dashboard|create_presentation|view_presentations|company_settings|custom_fields|manage_users|ai_rules|training_data|approvals|export_files", "granted": true}}}}
```

### 9. تفعيل/تعطيل موظف:
```action
{{"tool": "toggle_user", "params": {{"user_email": "...", "is_active": true}}}}
```

### 10. عرض الأقسام:
```action
{{"tool": "list_sections"}}
```

### 11. إضافة قسم جديد:
```action
{{"tool": "add_section", "params": {{"section_key": "...", "section_label": "..."}}}}
```

### 12. حذف قسم:
```action
{{"tool": "delete_section", "params": {{"section_key": "..."}}}}
```

### 13. عرض العروض التقديمية:
```action
{{"tool": "list_presentations"}}
```

### 14. حذف عرض تقديمي:
```action
{{"tool": "delete_presentation", "params": {{"presentation_id": "..."}}}}
```

### 15. إضافة قاعدة تدريب:
```action
{{"tool": "add_training", "params": {{"title": "...", "content": "...", "category": "general|design|content|style"}}}}
```

### 16. حذف سجل تدريب:
```action
{{"tool": "delete_training", "params": {{"entry_id": "..."}}}}
```

### 17. عرض سجلات التدريب:
```action
{{"tool": "list_training"}}
```

### 18. قراءة مساحة العرض المفتوح والتحقق منه:
```action
{{"tool": "inspect_workspace"}}
```
```action
{{"tool": "validate_workspace"}}
```

### 19. تعديل شريحة أو أكثر في العرض المفتوح:
```action
{{"tool": "edit_workspace_slide", "params": {{"slide_index": 0, "instruction": "..."}}}}
```
يمكن تمرير `slide_indices` كمصفوفة لتعديل أكثر من شريحة، وتنفذ الأداة التعديل لكل شريحة مع تحقق بعد كل تعديل.

### 20. حفظ مساحة العمل:
```action
{{"tool": "save_workspace", "params": {{"title": "..."}}}}
```

### 21. تصدير العرض المفتوح:
```action
{{"tool": "export_workspace", "params": {{"format": "pdf|pptx"}}}}
```

### 22. توليد الشرائح من الخطة المفتوحة:
```action
{{"tool": "generate_workspace", "params": {{"regenerate": true}}}}
```
لا تنفذ التوليد أو التعديل أو التصدير إذا لم تتوفر مساحة عمل صالحة. نفذ الأدوات بالترتيب: inspect ثم التنفيذ ثم validate ثم save/export عند طلب المستخدم.

## قواعد مهمة وحاسمة:
1. ⚠️ الفرق بين "الشرائح" (Slides) و "حقول الإدخال" (Input Fields):
   - عندما يطلب المستخدم إضافة أو وصف أو تعديل **شريحة** (مثل: "شريحة للجداول"، "شريحة للدراسات"، "شريحة الخريطة"، "أضف شريحة كذا")، فهذا يخص **العرض التقديمي والشرائح** فقط. **يُمنع منعاً باتاً** استخدام أدوات إنشاء أو تعديل الحقول (`add_field` / `update_field`)!
   - تُنشأ وتعدل الحقول (`add_field`/`update_field`) **فقط وفقط** إذا طلب المستخدم صراحة كلمة "حقل" أو "حقل إدخال جديد" أو "تعديل حقل" في استمارة البيانات!
2. عند الاستفسار: أجب بدقة بناءً على حالة النظام الفعلية أعلاه.
3. عند التعديل: نفّذ التعديل بإرجاع بلوك ```action``` ثم اشرح ما تم.
4. يمكنك تنفيذ عدة actions في رد واحد (كل واحدة في بلوك ```action``` منفصل).
5. كن مباشراً، ودياً، وذكياً. لا تتظاهر بعدم معرفة النظام.
6. بعد تنفيذ أي action اذكر القيمة القديمة والجديدة.
7. إذا طلب المستخدم شيء خطير (حذف عروض، تعطيل موظفين)، نفذه مباشرة لكن حذّره بوضوح.
"""

    user_prompt = (context + '\n\nالمستخدم: ' + message + '\n\nوكيل الإدارة:') if context else ('المستخدم: ' + message + '\n\nوكيل الإدارة:')

    try:
        response = call_zai_chat(system_prompt, user_prompt, max_tokens=2000)
        reply = extract_chat_content(response, 'SUPER-AGENT')
    except Exception as e:
        print(f'[SUPER-AGENT] AI reply failed: {e}')
        reply = 'أهلاً! أنا وكيل الإدارة الذكي الخاص بشركتك. أقدر أساعدك في أي إعداد — من الألوان والحقول حتى الموظفين والصلاحيات.'

    # ── Execute any actions embedded in the reply ─────────────────────────
    actions_executed = []
    parsed_actions = _extract_json_actions_from_text(reply)

    # ── Fallback intent extraction if LLM didn't format an action block ──
    if not parsed_actions and message:
        # 1. Moodboard count intent
        mb_match = re.search(r'(?:مود\s*بورد|مودبورد|صور|عدد الصور).+?(\d+)', message) or re.search(r'(\d+).+?(?:مود\s*بورد|مودبورد|صور)', message)
        if mb_match:
            try:
                num = int(mb_match.group(1))
                if 1 <= num <= 20:
                    parsed_actions.append({
                        'tool': 'update_branding',
                        'params': {'moodboard_count': num}
                    })
                    reply = f"تم التعديل! 🎨 عدد صور المود بورد تم تغييره إلى **{num} صور**. الآن كل عرض تقديمي سيتم إنشاؤه سيضم {num} صور في شريحة المود بورد."
            except ValueError:
                pass

        # 2. Slide count intent
        slide_match = re.search(r'(?:شرائح|شريحة|عدد الشرائح).+?(\d+)', message) or re.search(r'(\d+).+?(?:شرائح|شريحة)', message)
        if not parsed_actions and slide_match:
            try:
                num = int(slide_match.group(1))
                if 1 <= num <= 50:
                    parsed_actions.append({
                        'tool': 'update_branding',
                        'params': {'default_slide_count': num, 'min_slides': num, 'max_slides': num}
                    })
                    reply = f"تم التعديل! 📊 عدد الشرائح الافتراضي تم تغييره إلى **{num} شرائح**."
            except ValueError:
                pass

        # 3. Color intent (hex codes like #7a6938, #a8a851, etc.)
        hex_matches = re.findall(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', message)
        if not parsed_actions and hex_matches:
            full_hexes = [f"#{h}" for h in hex_matches]
            color_params = {}

            lines = message.split('\n')
            for line in lines:
                line_hexes = re.findall(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', line)
                if not line_hexes:
                    continue
                hex_val = f"#{line_hexes[0]}"
                line_lower = line.lower()
                if 'primary' in line_lower or 'أساسي' in line_lower or 'الأساسي' in line_lower or 'الرئيسي' in line_lower:
                    color_params['primary_color'] = hex_val
                elif 'secondary' in line_lower or 'ثانوي' in line_lower or 'الثانوي' in line_lower or 'فرعي' in line_lower:
                    color_params['secondary_color'] = hex_val
                elif 'accent' in line_lower or 'أكسنت' in line_lower or 'تمييز' in line_lower:
                    color_params['accent_color'] = hex_val
                elif 'background' in line_lower or 'خلفية' in line_lower or 'الخلفية' in line_lower:
                    color_params['background_color'] = hex_val
                elif 'text' in line_lower or 'نص' in line_lower or 'النص' in line_lower:
                    color_params['text_color'] = hex_val

            if not color_params and len(full_hexes) >= 1:
                color_params['primary_color'] = full_hexes[0]
                if len(full_hexes) >= 2:
                    color_params['secondary_color'] = full_hexes[1]
                if len(full_hexes) >= 3:
                    color_params['accent_color'] = full_hexes[2]

            if color_params:
                parsed_actions.append({
                    'tool': 'update_branding',
                    'params': color_params
                })
                desc = ', '.join([f"{k}: {v}" for k, v in color_params.items()])
                reply = f"تم التعديل! 🎨 تم تحديث ألوان الهوية البصرية للشركة: ({desc})."

        # 4. Revert / Reset colors intent ("رجع الألوان", "استرجع الألوان", "الألوان القديمة", "الألوان الافتراضية")
        if not parsed_actions and any(kw in message for kw in ['رجع الالوان', 'رجع الألوان', 'الالوان القديمه', 'الألوان القديمة', 'الالوان السابقة', 'الألوان السابقة', 'استرجاع الالوان', 'استرجاع الألوان', 'الالوان الافتراضية', 'الألوان الافتراضية', 'القديمة', 'القديمه']):
            default_colors = {
                'primary_color': '#3B6E91',
                'secondary_color': '#254B66',
                'accent_color': '#D97706',
                'background_color': '#F8FAFC',
                'text_color': '#1E293B'
            }
            parsed_actions.append({
                'tool': 'update_branding',
                'params': default_colors
            })
            reply = "تم استرجاع الألوان القديمة والافتراضية للهوية البصرية بنجاح! 🎨 (Primary: #3B6E91, Secondary: #254B66)."

    for action in parsed_actions:
        try:
            result = _execute_agent_action(g.tenant_id, action, reply_text=reply, workspace=workspace)
            actions_executed.append(result)
            print(f'[SUPER-AGENT] Executed: {action.get("tool")} → {result.get("status")}')
        except Exception as ex:
            print(f'[SUPER-AGENT] Action execution error: {ex}')
            actions_executed.append({'status': 'error', 'message': str(ex)})

    # ── Clean action blocks from the display reply ────────────────────────
    clean_reply = re.sub(r'```action\s*\n?[\s\S]*?```', '', reply).strip()
    # Remove leftover empty lines
    clean_reply = re.sub(r'\n{3,}', '\n\n', clean_reply).strip()

    if not clean_reply and actions_executed:
        clean_reply = '✅ تم تنفيذ الإجراء بنجاح.'

    return jsonify({
        'success': True,
        'reply': clean_reply,
        'actions': actions_executed,
    })


def _build_agent_system_state(tenant_id):
    """Build comprehensive real-time system state for the Super Agent."""
    branding = db.get_branding(tenant_id) or {}
    fields = db.get_fields(tenant_id, active_only=False)
    active_fields = [f for f in fields if f.get('is_active')]
    inactive_fields = [f for f in fields if not f.get('is_active')]
    users = db.get_users_by_tenant(tenant_id)
    sections = db.get_all_sections(tenant_id)
    custom_sections = db.get_custom_sections(tenant_id)
    presentations = db.get_presentations(tenant_id)
    training_data = db.get_training_data(tenant_id)
    active_training = [t for t in training_data if t.get('is_active')]
    templates = db.get_slide_templates(tenant_id)

    field_lines = []
    for f in active_fields[:40]:
        req = '✅ إلزامي' if f.get('is_required') else '⬜ اختياري'
        custom = ' (مخصص)' if f.get('is_custom') else ' (أساسي)'
        field_lines.append(f"  • {f['field_label']} [{f['field_key']}] — نوع: {f['field_type']}, قسم: {f.get('section_key', 'general')}, {req}{custom}")

    inactive_field_lines = []
    for f in inactive_fields[:15]:
        inactive_field_lines.append(f"  • {f['field_label']} [{f['field_key']}] — معطل")

    user_lines = []
    for u in users:
        status = '🟢 نشط' if u.get('is_active') else '🔴 معطل'
        user_lines.append(f"  • {u['name']} ({u['email']}) — دور: {u['role']}, {status}")

    section_lines = []
    for s in sections:
        custom_tag = ' (مخصص)' if s.get('custom') else ' (أساسي)'
        section_lines.append(f"  • {s.get('label', s['key'])} [{s['key']}]{custom_tag}")

    pres_summary = f"{len(presentations)} عرض"
    if presentations:
        recent = presentations[:5]
        pres_lines = [f"  • {p.get('title', 'بدون عنوان')} — {p.get('slide_count', '?')} شريحة — {p.get('status', 'draft')} — {p.get('created_at', '')[:10]}" for p in recent]
        pres_summary += '\n' + '\n'.join(pres_lines)

    training_lines = []
    for t in active_training[:10]:
        training_lines.append(f"  • [{t['id'][:8]}] {t.get('title', 'بدون عنوان')} — فئة: {t.get('category', 'general')} — {t.get('created_at', '')[:10]}")

    return f"""### 🏢 معلومات الشركة:
- اسم الشركة: {branding.get('company_name', 'غير محدد')}
- الشعار النصي: {branding.get('tagline', 'غير محدد')}

### 🎨 الهوية البصرية:
- اللون الرئيسي: {branding.get('primary_color', '#3B6E91')}
- اللون الثانوي: {branding.get('secondary_color', '#254B66')}
- لون التمييز: {branding.get('accent_color', '#6DA3C3')}
- لون الخلفية: {branding.get('background_color', '#F4F9FC')}
- لون النص: {branding.get('text_color', '#333333')}
- الخط: {branding.get('font_family', 'The Sans Arabic')}
- الخط العربي: {branding.get('font_arabic', 'The Sans Arabic')}
- قالب التصميم: {branding.get('design_template', 'modern')}
- نمط البطاقات: {branding.get('card_style', 'bordered')}
- نسبة العرض: {branding.get('slide_ratio', '16:9')}
- الهيدر: {'مفعل' if branding.get('header_enabled') else 'معطل'} (ارتفاع {branding.get('header_height', 56)}px)
- الفوتر: {'مفعل' if branding.get('footer_enabled') else 'معطل'} (ارتفاع {branding.get('footer_height', 36)}px)
- اللوجو: {'موجود' if branding.get('logo_path') else 'غير مرفوع'}

### 📊 إعدادات الشرائح والصور:
- عدد الشرائح الافتراضي: {branding.get('default_slide_count', 16)}
- الحد الأدنى: {branding.get('min_slides', 8)}
- الحد الأقصى: {branding.get('max_slides', 30)}
- عدد صور المود بورد: {branding.get('moodboard_count', 4)}
- المود بورد: {'مفعل' if branding.get('moodboard_enabled') else 'معطل'}
- صورة الغلاف: {'مفعلة' if branding.get('cover_image_enabled') else 'معطلة'}

### 📋 حقول الإدخال النشطة ({len(active_fields)} حقل):
{chr(10).join(field_lines) if field_lines else '  لا توجد حقول نشطة.'}

### 🚫 حقول معطلة ({len(inactive_fields)}):
{chr(10).join(inactive_field_lines) if inactive_field_lines else '  لا توجد حقول معطلة.'}

### 📁 أقسام البيانات ({len(sections)} قسم):
{chr(10).join(section_lines) if section_lines else '  لا توجد أقسام.'}

### 👥 الموظفين ({len(users)} موظف):
{chr(10).join(user_lines) if user_lines else '  لا يوجد موظفين.'}

### 📄 العروض التقديمية:
{pres_summary}

### 🧠 سجلات التدريب ({len(active_training)} سجل نشط):
{chr(10).join(training_lines) if training_lines else '  لا توجد سجلات تدريب.'}

### 📐 قوالب الشرائح المخصصة ({len(templates)} قالب):
{chr(10).join([f"  • {t.get('slide_name', t.get('slide_type', '?'))}" for t in templates[:10]]) if templates else '  لا توجد قوالب مخصصة.'}
"""


def _extract_json_actions_from_text(raw_text):
    """Extract all valid JSON objects containing a 'tool' key from text,
    handling code blocks, multi-JSON blocks, trailing text, and formatting quirks."""
    actions = []
    if not raw_text:
        return actions

    # 1. Find blocks inside ```action ... ``` or ```json ... ``` or use full text
    blocks = re.findall(r'```(?:action|json)?\s*\n?([\s\S]*?)```', raw_text)
    if not blocks:
        blocks = [raw_text]

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Try direct parse first
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict) and 'tool' in parsed:
                actions.append(parsed)
                continue
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and 'tool' in item:
                        actions.append(item)
                continue
        except (json.JSONDecodeError, ValueError):
            pass

        # Balanced brace scanner for concatenated or noisy JSONs
        idx = 0
        while idx < len(block):
            start = block.find('{', idx)
            if start == -1:
                break
            depth = 0
            in_str = False
            esc = False
            end = -1
            for i in range(start, len(block)):
                c = block[i]
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
                            end = i + 1
                            break
            if end != -1:
                candidate = block[start:end]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and 'tool' in parsed:
                        actions.append(parsed)
                except (json.JSONDecodeError, ValueError):
                    pass
                idx = end
            else:
                idx = start + 1

    return actions


def _find_target_field(fields, search_str):
    """Smart field matcher by key, label, transliteration, or partial substring."""
    if not search_str or not fields:
        return None
    search_clean = str(search_str).strip().lower()
    search_key = re.sub(r'[^a-zA-Z0-9_]', '_', search_clean).strip('_')

    # 1. Exact key match
    for f in fields:
        if f['field_key'].lower() == search_clean or (search_key and f['field_key'].lower() == search_key):
            return f

    # 2. Exact label match
    for f in fields:
        if f['field_label'].strip().lower() == search_clean:
            return f

    # 3. Transliterated label match
    ar_map = {
        'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
        'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
        'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
        'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
        'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
        ' ': '_', 'ـ': '',
    }
    for f in fields:
        label_trans = ''.join(ar_map.get(ch, ch) for ch in f['field_label'].lower())
        label_trans_clean = re.sub(r'[^a-zA-Z0-9_]', '_', label_trans).strip('_')
        if search_key and (search_key == label_trans_clean or label_trans_clean in search_key or search_key in label_trans_clean):
            return f

    # 4. Partial substring match in key or label
    for f in fields:
        if search_clean and (search_clean in f['field_key'].lower() or search_clean in f['field_label'].lower()):
            return f

    return None


def _summarize_agent_workspace(workspace, tenant_id):
    """Return a bounded, non-HTML workspace summary for the agent prompt."""
    if not isinstance(workspace, dict):
        return 'لا توجد مساحة عمل مرسلة من الواجهة.'
    slides = workspace.get('slidesData') if isinstance(workspace.get('slidesData'), list) else []
    plan = workspace.get('slidePlan') if isinstance(workspace.get('slidePlan'), dict) else {}
    presentation_id = workspace.get('presentationId')
    owned = db.get_presentation(presentation_id, tenant_id=tenant_id) if presentation_id else None
    slide_lines = []
    for i, slide in enumerate(slides[:40]):
        if isinstance(slide, dict):
            html = slide.get('html') or ''
            slide_lines.append(f"  • {i + 1}: {slide.get('title', 'بدون عنوان')} — {'HTML موجود' if html else 'HTML مفقود'}")
    return '\n'.join([
        f"- presentationId: {presentation_id or 'غير محفوظ'}",
        f"- العرض يخص الشركة الحالية: {'نعم' if owned else 'لا/غير محفوظ'}",
        f"- عدد الشرائح: {len(slides)}",
        f"- عدد شرائح الخطة: {len(plan.get('slides', [])) if isinstance(plan.get('slides'), list) else 0}",
        '\n'.join(slide_lines) if slide_lines else '  لا توجد شرائح مفتوحة.',
    ])


def _workspace_slides(workspace):
    slides = workspace.get('slidesData') if isinstance(workspace, dict) else None
    return slides if isinstance(slides, list) else []


def _validate_workspace_data(workspace):
    slides = _workspace_slides(workspace)
    errors = []
    for index, slide in enumerate(slides):
        html = slide.get('html') if isinstance(slide, dict) else ''
        if not isinstance(html, str) or html.count('class="slide"') != 1:
            errors.append({'slide_index': index, 'message': 'يجب أن تحتوي الشريحة على div class="slide" واحد فقط'})
    return {'valid': bool(slides) and not errors, 'slide_count': len(slides), 'errors': errors}


def _execute_agent_action(tenant_id, action, reply_text=None, workspace=None):
    """Execute a single agent action and return the result."""
    tool = action.get('tool', '')
    params = action.get('params', {})
    workspace = workspace if isinstance(workspace, dict) else {}
    result = {'tool': tool, 'status': 'success', 'changes': {}}

    try:
        # ── Branding ──────────────────────────────────────────────────
        if tool == 'update_branding':
            old_branding = db.get_branding(tenant_id) or {}
            # Filter to allowed branding fields only
            allowed_keys = {
                'primary_color', 'secondary_color', 'accent_color', 'background_color',
                'text_color', 'font_family', 'font_arabic', 'design_template', 'card_style',
                'slide_ratio', 'header_enabled', 'footer_enabled', 'header_height',
                'footer_height', 'moodboard_enabled', 'cover_image_enabled', 'moodboard_count',
                'default_slide_count', 'min_slides', 'max_slides', 'tagline', 'company_name',
            }
            updates = {}
            for k, v in params.items():
                if k in allowed_keys:
                    # Cast integers for boolean/numeric fields
                    if k in ('header_enabled', 'footer_enabled', 'moodboard_enabled', 'cover_image_enabled'):
                        v = 1 if v in (True, 1, '1', 'true', 'نعم') else 0
                    elif k in ('header_height', 'footer_height', 'moodboard_count', 'default_slide_count', 'min_slides', 'max_slides'):
                        try:
                            v = int(v)
                        except (ValueError, TypeError):
                            continue
                    updates[k] = v

            if updates:
                db.update_branding(tenant_id, **updates)
                # Log each change
                for k, new_val in updates.items():
                    old_val = old_branding.get(k)
                    if str(old_val) != str(new_val):
                        db.log_ai_rule_change(tenant_id, 'agent_branding', k, old_val, new_val, risk_level='yellow')
                        result['changes'][k] = {'old': old_val, 'new': new_val}
                result['message'] = f'تم تحديث {len(updates)} إعداد في الهوية البصرية'
            else:
                result['status'] = 'no_changes'
                result['message'] = 'لم يتم تحديد حقول صالحة للتعديل'

        # ── List Fields ───────────────────────────────────────────────
        elif tool == 'list_fields':
            fields = db.get_fields(tenant_id, active_only=False)
            result['data'] = [{
                'field_key': f['field_key'], 'field_label': f['field_label'],
                'field_type': f['field_type'], 'section_key': f.get('section_key', 'general'),
                'is_active': bool(f['is_active']), 'is_custom': bool(f['is_custom']),
                'is_required': bool(f['is_required']),
            } for f in fields]
            result['message'] = f'{len(fields)} حقل في النظام'

        # ── Add Field ─────────────────────────────────────────────────
        elif tool == 'add_field':
            label = (params.get('field_label') or params.get('fieldLabel') or '').strip()
            if not label:
                result['status'] = 'error'
                result['message'] = 'field_label مطلوب'
            else:
                fields = db.get_fields(tenant_id, active_only=False)
                existing = _find_target_field(fields, label) or (
                    _find_target_field(fields, params.get('field_key') or params.get('fieldKey'))
                )
                if existing:
                    key = existing['field_key']
                else:
                    ar_map = {
                        'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
                        'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
                        'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
                        'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
                        'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
                        ' ': '_', 'ـ': '',
                    }
                    key = params.get('field_key') or params.get('fieldKey') or ''.join(ar_map.get(ch, ch) for ch in label)
                    key = re.sub(r'[^a-zA-Z0-9_]', '_', key.lower()).strip('_')
                    if not key:
                        key = f'field_{_uuid.uuid4().hex[:6]}'

                section_key = params.get('section_key') or params.get('sectionKey') or (existing.get('section_key') if existing else 'general')
                valid_keys = {'general'} | {s['key'] for s in db.get_all_sections(tenant_id)}
                if section_key not in valid_keys and section_key not in {s['key'] for s in db.FIELD_SECTIONS}:
                    db.add_custom_section(tenant_id, section_key, section_key.replace('_', ' ').title())

                raw_opts = (
                    params.get('field_options') or params.get('fieldOptions') or
                    params.get('options') or params.get('choices') or params.get('values')
                )
                options = db._normalize_options_list(raw_opts)
                if not options and reply_text:
                    extracted = re.findall(r'^\s*[\d\-\*\•][\.\)\:]?\s*(.+)$', reply_text, re.MULTILINE)
                    if extracted and len(extracted) >= 2:
                        options = db._normalize_options_list([x for x in extracted if len(x.strip()) < 100])
                    else:
                        match = re.search(r'(?:خيارات|الخيارات|القيمة الجديدة|القيم)[:\s]*([^\n]+)', reply_text)
                        if match:
                            options = db._normalize_options_list(match.group(1))

                field_type = params.get('field_type') or params.get('fieldType') or ('select' if options else 'text')
                if options:
                    field_type = 'select'

                field_id = db.add_custom_field(
                    tenant_id=tenant_id, field_key=key, field_label=label,
                    field_type=field_type,
                    field_options=options,
                    is_required=params.get('is_required') or params.get('isRequired') or False,
                    ai_hint=params.get('ai_hint') or params.get('aiHint') or '',
                    placeholder=params.get('placeholder') or '',
                    section_key=section_key,
                )
                db.log_ai_rule_change(tenant_id, 'agent_field', 'add_field', None, f'{label} [{key}]', risk_level='yellow')
                result['message'] = f'تم تحديث/إضافة حقل "{label}" (المفتاح: {key}) في قسم {section_key}'
                result['field_id'] = field_id

        # ── Update Field ──────────────────────────────────────────────
        elif tool == 'update_field':
            field_key = params.get('field_key') or params.get('fieldKey') or ''
            field_label = params.get('field_label') or params.get('fieldLabel') or ''
            query = field_key or field_label or ''

            raw_updates = params.get('updates', {})
            updates = raw_updates.copy() if isinstance(raw_updates, dict) else {}

            for k, v in params.items():
                if k != 'updates' and k not in updates:
                    updates[k] = v

            fields = db.get_fields(tenant_id, active_only=False)
            target = _find_target_field(fields, query) or _find_target_field(fields, updates.get('field_label') or updates.get('fieldLabel'))

            raw_opts = (
                updates.get('field_options') or updates.get('fieldOptions') or 
                updates.get('options') or updates.get('choices') or updates.get('values') or
                params.get('field_options') or params.get('fieldOptions') or 
                params.get('options') or params.get('choices') or params.get('values')
            )
            options = db._normalize_options_list(raw_opts)

            if not options and reply_text and (not target or target.get('field_type') == 'select' or 'select' in str(updates.get('field_type') or updates.get('fieldType')).lower()):
                extracted = re.findall(r'^\s*[\d\-\*\•][\.\)\:]?\s*(.+)$', reply_text, re.MULTILINE)
                if extracted and len(extracted) >= 2:
                    options = db._normalize_options_list([x for x in extracted if len(x.strip()) < 100])
                else:
                    match = re.search(r'(?:خيارات|الخيارات|القيمة الجديدة|القيم)[:\s]*([^\n]+)', reply_text)
                    if match:
                        options = db._normalize_options_list(match.group(1))

            if not target:
                label = updates.get('field_label') or updates.get('fieldLabel') or params.get('field_label') or field_key.replace('_', ' ').title()
                field_type = updates.get('field_type') or updates.get('fieldType') or ('select' if options else 'select')
                section_key = updates.get('section_key') or updates.get('sectionKey') or 'compliance'
                ai_hint = updates.get('ai_hint') or updates.get('aiHint') or ''

                ar_map = {
                    'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'a', 'ب': 'b', 'ت': 't', 'ث': 'th',
                    'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'dh', 'ر': 'r', 'ز': 'z',
                    'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
                    'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
                    'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ئ': 'y', 'ة': 'a', 'ء': '',
                    ' ': '_', 'ـ': '',
                }
                new_key = ''.join(ar_map.get(ch, ch) for ch in label)
                new_key = re.sub(r'[^a-zA-Z0-9_]', '_', new_key.lower()).strip('_')
                if not new_key:
                    new_key = field_key if field_key else f'field_{_uuid.uuid4().hex[:6]}'

                field_id = db.add_custom_field(
                    tenant_id=tenant_id, field_key=new_key, field_label=label,
                    field_type='select' if options else field_type, field_options=options,
                    is_required=updates.get('is_required') or updates.get('isRequired') or False,
                    ai_hint=ai_hint, section_key=section_key
                )
                target = db.get_field_by_id(field_id)

            if target:
                db_updates = {}
                key_map = {
                    'field_label': 'field_label', 'fieldLabel': 'field_label',
                    'is_active': 'is_active', 'isActive': 'is_active',
                    'is_required': 'is_required', 'isRequired': 'is_required',
                    'ai_hint': 'ai_hint', 'aiHint': 'ai_hint',
                    'placeholder': 'placeholder', 'default_value': 'default_value', 'defaultValue': 'default_value',
                    'section_key': 'section_key', 'sectionKey': 'section_key',
                    'field_type': 'field_type', 'fieldType': 'field_type',
                }
                for k, v in updates.items():
                    if k in key_map:
                        if key_map[k] in ('is_active', 'is_required'):
                            v = 1 if v in (True, 1, '1', 'true') else 0
                        db_updates[key_map[k]] = v

                if options:
                    db_updates['field_options'] = options
                    db_updates['field_type'] = 'select'

                if db_updates:
                    db.update_field(target['id'], **db_updates)
                    db.log_ai_rule_change(tenant_id, 'agent_field', f'update_{target["field_key"]}', str(target), str(db_updates), risk_level='yellow')
                    result['message'] = f'تم تحديث حقل "{target["field_label"]}" بنجاح'
                    result['changes'] = db_updates
                else:
                    result['message'] = f'حقل "{target["field_label"]}" تم إعداده بنجاح'

        # ── Delete Field ──────────────────────────────────────────────
        elif tool == 'delete_field':
            query = (
                params.get('field_key') or params.get('field_label') or 
                params.get('fieldKey') or params.get('fieldLabel') or ''
            )
            fields = db.get_fields(tenant_id, active_only=False)
            target = _find_target_field(fields, query)
            if not target:
                result['status'] = 'error'
                result['message'] = f'الحقل "{query}" غير موجود'
            elif not target.get('is_custom'):
                result['status'] = 'error'
                result['message'] = f'لا يمكن حذف الحقل الأساسي "{target["field_label"]}". يمكنك تعطيله فقط.'
            else:
                db.delete_field(target['id'])
                db.log_ai_rule_change(tenant_id, 'agent_field', 'delete_field', target['field_label'], None, risk_level='red')
                result['message'] = f'تم حذف الحقل "{target["field_label"]}" ({target["field_key"]}) نهائياً'

        # ── List Users ────────────────────────────────────────────────
        elif tool == 'list_users':
            users = db.get_users_by_tenant(tenant_id)
            result['data'] = [{
                'name': u['name'], 'email': u['email'], 'role': u['role'],
                'is_active': bool(u['is_active']),
            } for u in users]
            result['message'] = f'{len(users)} موظف في الشركة'

        # ── Add User ──────────────────────────────────────────────────
        elif tool == 'add_user':
            name = (params.get('name') or params.get('user_name') or '').strip()
            email = (params.get('email') or params.get('user_email') or '').strip().lower()
            password = (params.get('password') or '123456').strip()
            role = (params.get('role') or 'employee').strip()
            if not name or not email:
                result['status'] = 'error'
                result['message'] = 'name و email مطلوبان لإضافة الموظف'
            else:
                existing = db.get_user_by_email(email)
                if existing:
                    result['status'] = 'error'
                    result['message'] = f'الموظف بالإيميل "{email}" موجود بالفعل'
                else:
                    pw_hash = auth.hash_password(password)
                    user_id = db.create_user(tenant_id, name, email, pw_hash, role=role)
                    db.log_ai_rule_change(tenant_id, 'agent_user', 'add_user', None, f'{name} ({email})', risk_level='yellow')
                    result['message'] = f'تم إضافة الموظف "{name}" ({email}) بكلمة مرور مؤقتة ({password}) بنجاح.'
                    result['user_id'] = user_id

        # ── Set Permission ────────────────────────────────────────────
        elif tool == 'set_permission':
            email = (params.get('user_email') or '').lower()
            perm = params.get('permission', '')
            granted = params.get('granted', True)
            users = db.get_users_by_tenant(tenant_id)
            target_user = next((u for u in users if u['email'] == email), None)
            if not target_user:
                result['status'] = 'error'
                result['message'] = f'الموظف "{email}" غير موجود'
            elif perm not in db.PERMISSION_KEYS:
                result['status'] = 'error'
                result['message'] = f'الصلاحية "{perm}" غير صالحة. الصلاحيات المتاحة: {", ".join(db.PERMISSION_KEYS)}'
            else:
                db.set_user_permission(target_user['id'], perm, granted)
                db.log_ai_rule_change(tenant_id, 'agent_permission', f'{email}:{perm}', 'unknown', str(granted), risk_level='red')
                target_label = 'للموظف' if granted else 'من الموظف'
                target_name = target_user["name"]
                result['message'] = f'تم {status_text} صلاحية "{perm}" {target_label} {target_name}'

        # ── Toggle User ───────────────────────────────────────────────
        elif tool == 'toggle_user':
            email = (params.get('user_email') or '').lower()
            is_active = params.get('is_active', True)
            users = db.get_users_by_tenant(tenant_id)
            target_user = next((u for u in users if u['email'] == email), None)
            if not target_user:
                result['status'] = 'error'
                result['message'] = f'الموظف "{email}" غير موجود'
            else:
                active_val = 1 if is_active in (True, 1, '1', 'true') else 0
                db.update_user(target_user['id'], is_active=active_val)
                db.log_ai_rule_change(tenant_id, 'agent_user', f'toggle_{email}', target_user.get('is_active'), active_val, risk_level='red')
                status_text = 'تفعيل' if active_val else 'تعطيل'
                result['message'] = f'تم {status_text} حساب الموظف {target_user["name"]}'

        # ── List Sections ─────────────────────────────────────────────
        elif tool == 'list_sections':
            sections = db.get_all_sections(tenant_id)
            result['data'] = sections
            result['message'] = f'{len(sections)} قسم في النظام'

        # ── Add Section ───────────────────────────────────────────────
        elif tool == 'add_section':
            key = params.get('section_key', '').strip()
            label = params.get('section_label', '').strip()
            if not key or not label:
                result['status'] = 'error'
                result['message'] = 'section_key و section_label مطلوبان'
            else:
                section_id = db.add_custom_section(tenant_id, key, label)
                if section_id:
                    db.log_ai_rule_change(tenant_id, 'agent_section', 'add_section', None, f'{label} [{key}]', risk_level='yellow')
                    result['message'] = f'تم إضافة قسم "{label}" بنجاح'
                else:
                    result['status'] = 'error'
                    result['message'] = f'القسم "{key}" موجود بالفعل'

        # ── Delete Section ────────────────────────────────────────────
        elif tool == 'delete_section':
            key = params.get('section_key', '').strip()
            deleted = db.delete_custom_section(tenant_id, key)
            if deleted:
                db.log_ai_rule_change(tenant_id, 'agent_section', 'delete_section', key, None, risk_level='red')
                result['message'] = f'تم حذف القسم "{key}" وتم نقل حقوله لقسم "عام"'
            else:
                result['status'] = 'error'
                result['message'] = f'القسم "{key}" غير موجود أو لا يمكن حذفه'

        # ── Edit one or more workspace slides ─────────────────────────
        elif tool == 'edit_workspace_slide':
            slides = _workspace_slides(workspace)
            instruction = (params.get('instruction') or params.get('message') or '').strip()
            raw_indices = params.get('slide_indices')
            if raw_indices is None:
                raw_indices = [params.get('slide_index', 0)]
            if not isinstance(raw_indices, list):
                raw_indices = [raw_indices]
            try:
                indices = sorted(set(int(i) for i in raw_indices))
            except (TypeError, ValueError):
                indices = []
            if not instruction or not indices:
                result['status'] = 'error'
                result['message'] = 'instruction و slide_index أو slide_indices مطلوبان'
            elif any(i < 0 or i >= len(slides) for i in indices):
                result['status'] = 'error'
                result['message'] = 'رقم شريحة خارج نطاق مساحة العمل'
            else:
                branding = db.get_branding(tenant_id) or {}
                dynamic_rules = build_design_rules(branding)
                edited = []
                for index in indices:
                    slide = slides[index]
                    current_html = slide.get('html', '') if isinstance(slide, dict) else ''
                    if not current_html:
                        result['status'] = 'error'
                        result['message'] = f'الشريحة {index + 1} لا تحتوي HTML صالحاً للتعديل'
                        break
                    edit_prompt = f"""{dynamic_rules}

مهمتك تعديل شريحة HTML واحدة فقط.
أعد JSON صالحاً فقط بالمفتاحين html و response.
html يجب أن يكون div class=\"slide\" واحداً كاملاً، بلا markdown أو شرح خارجه.
حافظ على المحتوى غير المطلوب تغييره، ولا تستخدم صوراً خارجية.

عنوان الشريحة: {slide.get('title', '')}
الطلب: {instruction}
HTML الحالي:
{current_html}"""
                    response = call_zai_chat(edit_prompt, instruction, max_tokens=6000)
                    raw = extract_chat_content(response, 'SUPER-AGENT-SLIDE-EDIT').strip()
                    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw).strip()
                    parsed = None
                    try:
                        parsed = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        match = re.search(r'\{[\s\S]*\}', raw)
                        if match:
                            try:
                                parsed = json.loads(match.group(0))
                            except (json.JSONDecodeError, TypeError):
                                parsed = None
                    html = parsed.get('html') if isinstance(parsed, dict) else None
                    if not isinstance(html, str) or html.count('class="slide"') != 1:
                        result['status'] = 'error'
                        result['message'] = f'فشل التحقق من HTML للشريحة {index + 1}; لم يتم حفظ التعديل'
                        break
                    slide['html'] = postprocess_slide(html, index + 1, tenant_id)
                    if isinstance(parsed, dict) and parsed.get('response'):
                        slide['agentResponse'] = parsed['response']
                    edited.append(index)
                if edited and result['status'] == 'success':
                    result['changes'] = {'slide_indices': edited}
                    result['data'] = {'slidesData': slides, 'slideCount': len(slides)}
                    result['message'] = f'تم تعديل الشرائح: {", ".join(str(i + 1) for i in edited)}'

        # ── Generate workspace slides from the supplied plan ──────────
        elif tool == 'generate_workspace':
            project_data = clean_project_data(workspace.get('projectData') or {})
            slide_plan = workspace.get('slidePlan') or {}
            images = workspace.get('creativeImages') or workspace.get('images') or {}
            plan_slides = slide_plan.get('slides') if isinstance(slide_plan, dict) else None
            if not project_data or not isinstance(plan_slides, list) or not plan_slides:
                result['status'] = 'error'
                result['message'] = 'تحتاج مساحة العمل إلى projectData و slidePlan.slides قبل التوليد'
            else:
                branding = db.get_branding(tenant_id) or {}
                training_context = db.get_training_context(tenant_id) or ''
                def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
                    if training_context:
                        sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
                    return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2)
                htmls = generate_all_slides(
                    slide_plan, project_data, branding, _get_images_info(images), call_glm_fn,
                    map_placeholders=(images.get('map_placeholders', {}) if isinstance(images, dict) else {}),
                    creative_images=images,
                )
                generated = []
                for i, html in enumerate(htmls):
                    info = plan_slides[i] if i < len(plan_slides) else {}
                    generated.append({
                        'html': postprocess_slide(html or '', i + 1, tenant_id),
                        'title': info.get('title', f'شريحة {i + 1}'),
                        'type': info.get('type', 'content'),
                        'designStyle': info.get('design_style', 'cards'),
                    })
                validation = _validate_workspace_data({'slidesData': generated})
                if not validation['valid'] or len(generated) != len(plan_slides):
                    result['status'] = 'error'
                    result['data'] = {'slidesData': generated, 'validation': validation}
                    result['message'] = 'فشل التحقق من التوليد؛ لم يتم اعتماد عرض ناقص'
                else:
                    result['data'] = {'slidesData': generated, 'slideCount': len(generated)}
                    result['changes'] = {'slide_count': len(generated)}
                    result['message'] = f'تم توليد والتحقق من {len(generated)} شريحة'

        # ── Workspace inspection and validation ───────────────────────
        elif tool == 'inspect_workspace':
            slides = _workspace_slides(workspace)
            result['data'] = {
                'presentation_id': workspace.get('presentationId'),
                'title': workspace.get('projectData', {}).get('project_name', 'عرض بدون عنوان') if isinstance(workspace.get('projectData'), dict) else 'عرض بدون عنوان',
                'slide_count': len(slides),
                'slides': [{'index': i, 'title': s.get('title', ''), 'has_html': bool(s.get('html'))} for i, s in enumerate(slides) if isinstance(s, dict)],
            }
            result['message'] = f'تم فحص مساحة العمل: {len(slides)} شريحة'
        elif tool == 'validate_workspace':
            validation = _validate_workspace_data(workspace)
            result['data'] = validation
            if not validation['valid']:
                result['status'] = 'error'
                result['message'] = f"فشل التحقق: {len(validation['errors'])} مشكلة" if validation['errors'] else 'لا توجد شرائح للتحقق'
            else:
                result['message'] = f"التحقق ناجح: {validation['slide_count']} شريحة مكتملة"

        # ── List Presentations ────────────────────────────────────────
        elif tool == 'list_presentations':
            presentations = db.get_presentations(tenant_id)
            result['data'] = [{
                'id': p['id'], 'title': p.get('title', 'بدون عنوان'),
                'slide_count': p.get('slide_count', 0), 'status': p.get('status', 'draft'),
                'created_at': p.get('created_at', ''),
            } for p in presentations[:20]]
            result['message'] = f'{len(presentations)} عرض تقديمي في النظام'

        # ── Save workspace ────────────────────────────────────────────
        elif tool == 'save_workspace':
            validation = _validate_workspace_data(workspace)
            if not validation['valid']:
                result['status'] = 'error'
                result['message'] = 'تم منع الحفظ لأن مساحة العمل غير مكتملة أو تحتوي شرائح غير صالحة'
            else:
                title = (params.get('title') or workspace.get('title') or
                         (workspace.get('projectData') or {}).get('project_name') or 'عرض بدون عنوان').strip()
                slides = _workspace_slides(workspace)
                pres_id = workspace.get('presentationId')
                existing = db.get_presentation(pres_id, tenant_id=tenant_id) if pres_id else None
                if existing:
                    db.save_presentation_version(pres_id, None, 'Super Agent', slides, action='agent_save')
                    db.update_presentation(pres_id, title=title, project_data=workspace.get('projectData', {}), slides_data=slides, slide_count=len(slides), status='edited')
                else:
                    pres_id = db.create_presentation(tenant_id, title, workspace.get('projectData', {}), slides, len(slides))
                result['presentationId'] = pres_id
                result['data'] = {
                    'presentationId': pres_id,
                    'slidesData': slides,
                    'slideCount': len(slides),
                }
                result['message'] = f'تم حفظ العرض "{title}" وعدد شرائحه {len(slides)}'

        # ── Delete Presentation ───────────────────────────────────────
        elif tool == 'delete_presentation':
            pres_id = params.get('presentation_id', '')
            deleted = db.delete_presentation(pres_id, tenant_id=tenant_id)
            if deleted:
                db.log_ai_rule_change(tenant_id, 'agent_presentation', 'delete', pres_id, None, risk_level='red')
                result['message'] = 'تم حذف العرض التقديمي'
            else:
                result['status'] = 'error'
                result['message'] = 'العرض غير موجود أو لا ينتمي لشركتك'

        # ── Export workspace ──────────────────────────────────────────
        elif tool == 'export_workspace':
            validation = _validate_workspace_data(workspace)
            if not validation['valid']:
                result['status'] = 'error'
                result['message'] = 'تم منع التصدير لأن العرض غير مكتمل أو غير صالح'
            else:
                fmt = (params.get('format') or 'pdf').lower()
                if fmt not in {'pdf', 'pptx'}:
                    result['status'] = 'error'
                    result['message'] = 'صيغة التصدير يجب أن تكون pdf أو pptx'
                else:
                    presentation_id = workspace.get('presentationId')
                    if not presentation_id or not db.get_presentation(presentation_id, tenant_id=tenant_id):
                        result['status'] = 'error'
                        result['message'] = 'يجب حفظ العرض أولاً قبل تصديره، ومعرّف العرض غير صالح لهذه الشركة'
                    else:
                        branding = db.get_branding(tenant_id) or {}
                        output_dir = os.path.join(OUTPUT_DIR, tenant_id)
                        os.makedirs(output_dir, exist_ok=True)
                        title = (workspace.get('projectData') or {}).get('project_name', 'presentation')
                        if fmt == 'pdf':
                            from exports.pdf_export import generate_pdf
                            path = generate_pdf(
                                '\n'.join(s.get('html', '') for s in _workspace_slides(workspace)),
                                title, branding, output_dir
                            )
                        else:
                            from exports.pptx_export import generate_pptx
                            path = generate_pptx(_workspace_slides(workspace), title, branding, output_dir)
                        export_id = db.create_export(presentation_id, tenant_id, fmt, path)
                        result['data'] = {
                            'exportId': export_id,
                            'url': f'/api/exports/{export_id}/download',
                            'format': fmt,
                            'presentationId': presentation_id,
                        }
                        result['message'] = f'تم تصدير العرض بصيغة {fmt.upper()}'

        # ── Add Training ──────────────────────────────────────────────
        elif tool == 'add_training':
            title = params.get('title', '').strip()
            content = params.get('content', '').strip()
            if not title or not content:
                result['status'] = 'error'
                result['message'] = 'title و content مطلوبان'
            else:
                entry_id = db.create_training_entry(
                    tenant_id, title, content,
                    category=params.get('category', 'general')
                )
                result['message'] = f'تم إضافة قاعدة تدريب "{title}"'
                result['entry_id'] = entry_id

        # ── Delete Training ───────────────────────────────────────────
        elif tool == 'delete_training':
            entry_id = params.get('entry_id', '')
            deleted = db.delete_training_entry(tenant_id, entry_id)
            if deleted:
                result['message'] = 'تم حذف سجل التدريب'
            else:
                result['status'] = 'error'
                result['message'] = 'سجل التدريب غير موجود'

        # ── List Training ─────────────────────────────────────────────
        elif tool == 'list_training':
            entries = db.get_training_data(tenant_id)
            result['data'] = [{
                'id': t['id'], 'title': t.get('title', ''), 'category': t.get('category', 'general'),
                'is_active': bool(t.get('is_active', 1)), 'created_at': t.get('created_at', ''),
                'has_image': bool(t.get('image_path')),
            } for t in entries]
            result['message'] = f'{len(entries)} سجل تدريب'

        # ── Unknown tool ──────────────────────────────────────────────
        else:
            result['status'] = 'error'
            result['message'] = f'أداة غير معروفة: {tool}'

    except Exception as e:
        result['status'] = 'error'
        result['message'] = str(e)
        print(f'[SUPER-AGENT] Action error ({tool}): {e}')

    return result


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
    resp = send_from_directory(os.path.dirname(__file__), 'index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/invite/<token>')
def invite_page(token):
    resp = send_from_directory(os.path.dirname(__file__), 'index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/assets/<path:path>')
def static_assets(path):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'assets'), path)

@app.route('/uploads/maps/<path:path>')
def static_map_uploads(path):
    """Map renderings are presentation assets and may be served publicly."""
    return send_from_directory(os.path.join(UPLOADS_DIR, 'maps'), path)


@app.route('/uploads/<path:path>')
def static_uploads(path):
    """Serve map images or static presentation assets."""
    maps_dir = os.path.join(UPLOADS_DIR, 'maps')
    filename = os.path.basename(path)
    possible_map = os.path.join(maps_dir, filename)
    if os.path.isfile(possible_map):
        return send_from_directory(maps_dir, filename)
    return jsonify({'error': 'Not found'}), 404

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'model': GLM_MODEL, 'image_model': IMAGE_MODEL})

@app.route('/preview')
def preview():
    return send_from_directory(os.path.dirname(__file__), 'preview.html')

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
