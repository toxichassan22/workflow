import os
import sys
import json
import time
import math
from datetime import datetime
import re
import base64
import hashlib
import html as html_lib
import subprocess
import requests
import uuid as _uuid
import threading

import db_driver
import concurrent.futures
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, send_from_directory, g, current_app

load_dotenv()

import db
import auth
import maps_service
import population_service
import slide_engine
from auth import require_auth, require_admin, require_company_admin, require_permission, hash_password, verify_password, create_token, decode_token
from design_templates import get_all_templates, get_template, apply_template_colors, build_design_rules, extract_slide_elements, build_font_css

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.teardown_appcontext(db.close_db)


# Text responses go out uncompressed, and the SPA shell alone is ~740KB on every single load.
# Compressing here rather than adding a dependency keeps the deploy unchanged.
COMPRESSIBLE_TYPES = {
    'text/html', 'text/css', 'text/plain', 'text/javascript',
    'application/javascript', 'application/json', 'image/svg+xml',
}
COMPRESS_MIN_BYTES = 1024


@app.after_request
def compress_response(response):
    if response.status_code < 200 or response.status_code >= 300:
        return response
    if response.headers.get('Content-Encoding'):
        return response
    if (response.content_type or '').split(';')[0].strip() not in COMPRESSIBLE_TYPES:
        return response
    if 'gzip' not in (request.headers.get('Accept-Encoding') or '').lower():
        return response
    try:
        # File responses stream by default; reading them here is what allows compression.
        response.direct_passthrough = False
        body = response.get_data()
        if len(body) < COMPRESS_MIN_BYTES:
            return response
        import gzip as _gzip
        response.set_data(_gzip.compress(body, 6))
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Content-Length'] = str(len(response.get_data()))
        response.headers.add('Vary', 'Accept-Encoding')
    except Exception:
        app.logger.warning('Could not compress response', exc_info=True)
    return response


@app.before_request
def decompress_gzip_request_body():
    # The client gzips large JSON bodies because the hosting proxy corrupts
    # request bodies above ~35KB; restore the original body before routing.
    if request.headers.get('Content-Encoding', '').lower() != 'gzip':
        return
    try:
        import gzip as _gzip
        import io
        raw = request.get_data(cache=True)
        data = _gzip.decompress(raw)
        request._cached_data = data
        request.environ['wsgi.input'] = io.BytesIO(data)
        request.environ['CONTENT_LENGTH'] = str(len(data))
    except Exception:
        app.logger.warning('Could not decompress gzipped request body', exc_info=True)


@app.before_request
def reassemble_chunked_request_body():
    # The hosting edge corrupts request bodies above ~40KB: the app actually
    # receives and answers them, but the client gets a fabricated 404/502. The
    # client therefore uploads large bodies in small chunk envelopes
    # (POST /api/body-chunk) and finally sends a tiny {"__chunked_body": {...}}
    # reference; restore the original body here before routing.
    if request.method != 'POST' or request.path == '/api/body-chunk':
        return
    if 'application/json' not in (request.content_type or ''):
        return
    try:
        data = request.get_data(cache=True)
        if not data or b'__chunked_body' not in data:
            return
        meta = (json.loads(data) or {}).get('__chunked_body') or {}
    except Exception:
        return
    upload_id = str(meta.get('id', ''))
    total = meta.get('total')
    use_gzip = bool(meta.get('gzip'))
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', upload_id) or not isinstance(total, int) or not (1 <= total <= 1024):
        return jsonify({'error': 'Invalid chunked body reference'}), 400
    import gzip as _gzip
    import io
    import shutil as _shutil
    chunk_dir = os.path.join(UPLOADS_DIR, '.body_chunks', upload_id)
    parts = []
    try:
        for i in range(total):
            with open(os.path.join(chunk_dir, f'{i}.part'), 'rb') as fh:
                parts.append(fh.read())
    except OSError:
        return jsonify({'error': 'Missing uploaded body chunks'}), 400
    raw = b''.join(parts)
    if use_gzip:
        try:
            raw = _gzip.decompress(raw)
        except Exception:
            return jsonify({'error': 'Could not decompress chunked body'}), 400
    request._cached_data = raw
    request.environ['wsgi.input'] = io.BytesIO(raw)
    request.environ['CONTENT_LENGTH'] = str(len(raw))
    _shutil.rmtree(chunk_dir, ignore_errors=True)


@app.route('/api/body-chunk', methods=['POST'])
@require_auth
def api_body_chunk():
    """Receive one chunk of a large request body; reassembled by the before_request hook."""
    data = request.json or {}
    upload_id = str(data.get('id', ''))
    idx = data.get('idx')
    total = data.get('total')
    b64 = data.get('data') or ''
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', upload_id):
        return jsonify({'error': 'Invalid upload id'}), 400
    if not isinstance(idx, int) or not isinstance(total, int) or isinstance(idx, bool) or isinstance(total, bool) or not (0 <= idx < total <= 1024):
        return jsonify({'error': 'Invalid chunk index'}), 400
    if not isinstance(b64, str) or len(b64) > 24 * 1024:
        return jsonify({'error': 'Chunk too large'}), 400
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return jsonify({'error': 'Invalid chunk data'}), 400
    import shutil as _shutil
    chunk_root = os.path.join(UPLOADS_DIR, '.body_chunks')
    chunk_dir = os.path.join(chunk_root, upload_id)
    os.makedirs(chunk_dir, exist_ok=True)
    with open(os.path.join(chunk_dir, f'{idx}.part'), 'wb') as fh:
        fh.write(raw)
    # Best-effort sweep of stale chunk dirs (>15 min)
    try:
        now = time.time()
        for name in os.listdir(chunk_root):
            path = os.path.join(chunk_root, name)
            if os.path.isdir(path) and now - os.path.getmtime(path) > 900:
                _shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
    return jsonify({'success': True})


# Initialize database on startup
db.init_db()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Configuration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# strip(): a stray \r (CRLF endings) or spaces in .env would corrupt auth headers
ZAI_KEY = (os.environ.get("ZAI_KEY") or "").strip() or None
OPENROUTER_KEY = (os.environ.get("OPENROUTER_KEY") or "").strip() or None
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip() or None
ZAI_BASE = 'https://api.z.ai/api/paas/v4'
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
GEMINI_TEXT_MODEL = "google/gemini-3.7-flash"
LUNA_TEXT_MODEL = GEMINI_TEXT_MODEL
GLM_MODEL = GEMINI_TEXT_MODEL
GLM_OPENROUTER_MODEL = GEMINI_TEXT_MODEL
GLM_USE_OPENROUTER = True
print(f"[CONFIG] Primary text/design model: {GEMINI_TEXT_MODEL}")
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
FLOOR_DESIGN_IMAGE_MODEL = "openai/gpt-image-2"
FLOOR_DESIGN_TEXT_MODEL = GEMINI_TEXT_MODEL
FLOOR_DESIGN_REASONING_EFFORT = 'high'
FLOOR_DESIGN_REFERENCE_DIR = os.path.join(os.path.dirname(__file__), '2D reference')
FLOOR_DESIGN_REFERENCE_FILE = os.path.basename((os.environ.get('FLOOR_DESIGN_REFERENCE_FILE') or '1.png').strip() or '1.png')
FLOOR_DESIGN_REFERENCE_PATH = os.path.join(FLOOR_DESIGN_REFERENCE_DIR, FLOOR_DESIGN_REFERENCE_FILE)
_FLOOR_DESIGN_REFERENCE_CACHE = {'mtime': None, 'data_uri': None, 'path': None}
_FLOOR_DESIGN_REFERENCE_PACK_CACHE = {'fingerprint': None, 'references': None}
FLOOR_DESIGN_IMAGE_HARD_NEGATIVE = (
    'ABSOLUTE OUTPUT RULES: no watermark, no logo, no Acacia name, no copied project name, '
    'no copied dimensions, no copied room names, and no copied project content from the style reference. '
    'Do not omit, shorten, summarize, recalculate, estimate, or alter any supplied engineering value. '
    'Do not add decorative symbols, pictograms, three-dimensional perspective, photorealism, or unrelated UI.'
)
SITE_ANALYSIS_MAX_TOKENS = int(os.environ.get('SITE_ANALYSIS_MAX_TOKENS', '6000'))
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
DEPLOYMENT_MARKER_PATH = os.path.join(os.path.dirname(__file__), '.deployed_commit')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY')
print(f"[CONFIG] ZAI_KEY: {'SET' if ZAI_KEY else 'MISSING'}")
print(f"[CONFIG] OPENROUTER_KEY: {'SET' if OPENROUTER_KEY else 'MISSING'}")
print(f"[CONFIG] GEMINI_API_KEY: {'SET' if GEMINI_API_KEY else 'MISSING'}")
print(f"[CONFIG] GLM_USE_OPENROUTER: {GLM_USE_OPENROUTER}")
print(f"[CONFIG] GOOGLE_MAPS_API_KEY: {'SET' if GOOGLE_MAPS_API_KEY else 'MISSING'}")
print(f"[CONFIG] JWT_SECRET: {auth.JWT_SECRET_SOURCE.upper()}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Call GLM (ZAI API or OpenRouter fallback)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _has_chat_choices(response):
    return (
        isinstance(response, dict)
        and 'error' not in response
        and isinstance(response.get('choices'), list)
        and bool(response['choices'])
    )


def call_openrouter_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None):
    if not OPENROUTER_KEY:
        return {"error": {"message": "OPENROUTER_KEY is missing"}}
    model_name = model or GLM_OPENROUTER_MODEL
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-Title": "Real Estate Proposal Generator"
    }
    user_message_content = user_content
    if image_references:
        user_message_content = [{"type": "text", "text": str(user_content)}]
        for image_reference in image_references:
            if isinstance(image_reference, dict):
                image_url = image_reference.get('data_uri') or image_reference.get('url')
            else:
                image_url = image_reference
            if isinstance(image_url, str) and image_url.startswith('data:image/'):
                user_message_content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content}
        ],
        "max_tokens": max_tokens
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if response_format:
        payload["response_format"] = response_format
    if provider:
        payload["provider"] = provider
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=timeout)
        text = response.text or ''
        if not text.strip():
            print(f"[OPENROUTER EMPTY BODY] status={response.status_code} model={model_name} cap={max_tokens}")
            return {"error": {"message": f"مزوّد الذكاء الاصطناعي رد بجسم فارغ (HTTP {response.status_code})"}}
        try:
            data = response.json()
        except Exception as json_err:
            print(f"[OPENROUTER UNPARSEABLE] status={response.status_code} model={model_name} json_err={json_err} body={text[:200]!r}")
            return {"error": {"message": f"استجابة المزوّد ليست JSON صالحًا (HTTP {response.status_code})"}}
        if response.status_code >= 400:
            error = data.get('error', {}) if isinstance(data, dict) else data
            print(f"[OPENROUTER HTTP ERROR] status={response.status_code} model={model_name} error={error}")
            if isinstance(error, dict) and 'message' in error:
                error['message'] = f"[{response.status_code}] {error['message']}"
                return {"error": error}
            return {"error": error if isinstance(error, dict) else {"message": f"[{response.status_code}] {error}"}}
        return data
    except requests.exceptions.Timeout:
        print(f"[OPENROUTER TIMEOUT] model={model_name} cap={max_tokens} timeout={timeout}")
        return {"error": {"message": f"انتهت مهلة الاتصال بالمزوّد ({timeout} ثانية)"}}
    except requests.exceptions.ConnectionError as exc:
        print(f"[OPENROUTER CONNECTION] model={model_name} {exc}")
        return {"error": {"message": "انقطع الاتصال بالمزوّد قبل اكتمال الطلب"}}
    except Exception as exc:
        print(f"[OPENROUTER EXCEPTION] model={model_name} {exc}")
        return {"error": {"message": str(exc)}}


def call_zai_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000, timeout=300,
                  reasoning_effort=None):
    """Compatibility wrapper: all text/design work now uses Gemini through OpenRouter."""
    if not OPENROUTER_KEY:
        return {"error": {"message": "OPENROUTER_KEY is required for the Gemini text model"}}
    return call_openrouter_chat(
        system_prompt,
        user_content,
        temperature=None,
        max_tokens=max_tokens,
        model=LUNA_TEXT_MODEL,
        timeout=timeout,
        reasoning_effort=reasoning_effort,
    )


def call_zai_chat_parallel(system_prompt, user_content, temperature=0.7, max_tokens=8000, attempts=2, timeout=300):
    """
    Race multiple identical GLM calls in parallel and return the first valid response.
    Helps when a single model invocation is slow or returns malformed/empty content.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _attempt():
        try:
            resp = call_zai_chat(system_prompt, user_content, temperature, max_tokens, timeout=timeout)
            if not _has_chat_choices(resp):
                return None
            content = extract_chat_content(resp, 'GLM-PARALLEL')
            return resp if content.strip() else None
        except Exception as e:
            print(f"[GLM PARALLEL] attempt failed: {e}")
            return None

    executor = ThreadPoolExecutor(max_workers=max(1, attempts))
    futures = [executor.submit(_attempt) for _ in range(max(1, attempts))]
    try:
        for future in as_completed(futures):
            result = future.result()
            if result:
                for pending in futures:
                    pending.cancel()
                print(f"[GLM PARALLEL] Valid response received after racing {attempts} calls")
                return result
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    raise Exception(f"All {attempts} parallel GLM attempts failed")


def extract_chat_content(response, label="GLM"):
    """Safely extract text content from ZAI/GLM API response.
    Raises a descriptive exception if the response is malformed."""
    if not isinstance(response, dict):
        raise Exception(f"{label} returned an invalid response")
    if 'error' in response:
        err = response['error']
        if isinstance(err, dict):
            msg = err.get('message', json.dumps(err, ensure_ascii=False))
        else:
            msg = str(err)
        raise Exception(f"{label} API error: {msg}")
    if 'choices' not in response or not isinstance(response['choices'], list) or not response['choices']:
        raise Exception(f"{label} returned no choices. Response: {json.dumps(response, ensure_ascii=False)[:500]}")
    choice = response['choices'][0] if isinstance(response['choices'][0], dict) else {}
    message = choice.get('message') if isinstance(choice.get('message'), dict) else {}
    msg = message.get('content', '')
    if isinstance(msg, list):
        msg = ' '.join(
            part.get('text', '') if isinstance(part, dict) else str(part)
            for part in msg
        )
    if not msg:
        raise Exception(f"{label} returned empty content")
    return str(msg)

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
            text_part = msg.get("content")
            if isinstance(text_part, list):
                text_part = ' '.join(str(c.get('text', '')) if isinstance(c, dict) else str(c) for c in text_part)
            print(f"[IMAGE ERROR] API returned no image (status {response.status_code}). Text: {str(text_part)[:300]}")
        else:
            print(f"[IMAGE ERROR] Unexpected API response (status {response.status_code}): {str(data)[:300]}")
    except requests.exceptions.Timeout:
        print("[IMAGE ERROR] OpenRouter API request timed out")
    except requests.exceptions.ConnectionError:
        print("[IMAGE ERROR] Cannot connect to OpenRouter API")
    except Exception as e:
        print("[IMAGE ERROR]", str(e))
    return None

def _prepare_image_reference_for_model(reference):
    """Normalize a generated local image URL into a model-readable reference."""
    if not isinstance(reference, str) or not reference.strip():
        return None
    reference = reference.strip()
    if reference.startswith('data:image/') or re.match(r'^https?://', reference, re.IGNORECASE):
        return reference

    relative_path = reference.split('?', 1)[0].lstrip('/')
    if not relative_path.startswith('uploads/'):
        print(f'[IMAGE ERROR] Unsupported local reference path: {reference}')
        return None

    uploads_root = os.path.abspath(os.path.join(os.path.dirname(__file__), 'uploads'))
    image_path = os.path.abspath(os.path.join(os.path.dirname(__file__), relative_path.replace('/', os.sep)))
    try:
        if os.path.commonpath([uploads_root, image_path]) != uploads_root:
            return None
    except ValueError:
        return None
    if not os.path.isfile(image_path) or os.path.getsize(image_path) > 15 * 1024 * 1024:
        print(f'[IMAGE ERROR] Local reference image is unavailable: {reference}')
        return None

    mime_type = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
    }.get(os.path.splitext(image_path)[1].lower())
    if not mime_type:
        print(f'[IMAGE ERROR] Unsupported local reference format: {reference}')
        return None
    try:
        with open(image_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('ascii')
        return f'data:{mime_type};base64,{encoded}'
    except OSError as error:
        print(f'[IMAGE ERROR] Could not read local reference image: {error}')
        return None


def call_image_api_with_reference(reference_image_base64, prompt):
    # AI4: Check if OpenRouter key is configured
    if not OPENROUTER_KEY:
        print("[IMAGE ERROR] OPENROUTER_KEY is not configured")
        return None
    try:
        reference_for_model = _prepare_image_reference_for_model(reference_image_base64)
        if not reference_for_model:
            return None
        headers = {
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Real Estate Proposal Generator"
        }
        user_content = [
            {"type": "text", "text": prompt + " --aspect 16:9"},
            {"type": "image_url", "image_url": {"url": reference_for_model}}
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
            text_part = msg.get("content")
            if isinstance(text_part, list):
                text_part = ' '.join(str(c.get('text', '')) if isinstance(c, dict) else str(c) for c in text_part)
            print(f"[IMAGE ERROR] API returned no image (status {response.status_code}). Text: {str(text_part)[:300]}")
        else:
            print(f"[IMAGE ERROR] Unexpected API response (status {response.status_code}): {str(data)[:300]}")
    except requests.exceptions.Timeout:
        print("[IMAGE ERROR] OpenRouter API request timed out")
    except requests.exceptions.ConnectionError:
        print("[IMAGE ERROR] Cannot connect to OpenRouter API")
    except Exception as e:
        print("[IMAGE ERROR]", str(e))
    return None


def persist_generated_image(image, tenant_id):
    """Store generated data-URI images on disk and return a compact public URL."""
    if not isinstance(image, str) or not image.startswith('data:image/') or ';base64,' not in image:
        return image
    header, encoded = image.split(',', 1)
    mime = header[5:].split(';', 1)[0].lower()
    extension = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/webp': '.webp',
    }.get(mime)
    if not extension:
        return image
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        return image
    digest = hashlib.sha256(raw).hexdigest()[:24]
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(tenant_id or 'public')) or 'public'
    image_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'creative', safe_tenant)
    os.makedirs(image_dir, exist_ok=True)
    filename = digest + extension
    path = os.path.join(image_dir, filename)
    if not os.path.exists(path):
        with open(path, 'wb') as image_file:
            image_file.write(raw)
    return f'/uploads/creative/{safe_tenant}/{filename}'


def _floor_design_reference_data_uri(path):
    try:
        modified = os.path.getmtime(path)
        with open(path, 'rb') as reference_file:
            raw = reference_file.read()
        if len(raw) > 20 * 1024 * 1024 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            return None
        return modified, 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
    except (OSError, ValueError):
        return None


def _floor_design_reference_pack_data_uris():
    """Load the nine shared visual references for the prompt-writing vision model."""
    paths = [os.path.join(FLOOR_DESIGN_REFERENCE_DIR, f'{index}.png') for index in range(1, 10)]
    fingerprint = tuple((path, os.path.getmtime(path), os.path.getsize(path))
                        for path in paths if os.path.isfile(path))
    cached = _FLOOR_DESIGN_REFERENCE_PACK_CACHE
    if cached.get('fingerprint') == fingerprint and cached.get('references') is not None:
        return cached['references']
    references = []
    for index, path in enumerate(paths, 1):
        loaded = _floor_design_reference_data_uri(path)
        if not loaded:
            continue
        _modified, data_uri = loaded
        references.append({'name': f'{index}.png', 'data_uri': data_uri})
    cached.update({'fingerprint': fingerprint, 'references': references})
    return references


def _floor_design_default_reference_data_uri():
    """Return one selected style-only reference for the image-generation model."""
    selected_path = FLOOR_DESIGN_REFERENCE_PATH
    if not os.path.isfile(selected_path):
        pack = _floor_design_reference_pack_data_uris()
        selected_name = os.path.basename(selected_path)
        selected = next((item for item in pack if item['name'] == selected_name), None)
        if selected:
            return selected['data_uri']
        return None
    loaded = _floor_design_reference_data_uri(selected_path)
    if not loaded:
        return None
    modified, data_uri = loaded
    cached = _FLOOR_DESIGN_REFERENCE_CACHE
    if (cached.get('mtime') == modified and cached.get('path') == selected_path
            and cached.get('data_uri')):
        return cached['data_uri']
    cached.update({'mtime': modified, 'path': selected_path, 'data_uri': data_uri})
    return data_uri


def call_openrouter_image_generation(prompt, model, reference=None):
    """Generate one image through OpenRouter's dedicated Image API."""
    if not OPENROUTER_KEY:
        return None, 'NO_API_KEY'
    payload = {
        'model': model,
        'prompt': f'{prompt}\n\n{FLOOR_DESIGN_IMAGE_HARD_NEGATIVE}',
        'aspect_ratio': '16:9',
        'n': 1,
    }
    if model == 'openai/gpt-image-2':
        payload['quality'] = 'high'
    else:
        payload['resolution'] = '2K'
    if reference:
        reference_for_model = _prepare_image_reference_for_model(reference)
        if not reference_for_model:
            return None, 'REFERENCE_INVALID'
        payload['input_references'] = [{
            'type': 'image_url',
            'image_url': {'url': reference_for_model}
        }]
    headers = {
        'Authorization': f'Bearer {OPENROUTER_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://github.com/toxichassan22/workflow',
        'X-Title': 'Manafe Floor Design'
    }
    try:
        response = requests.post(f'{OPENROUTER_BASE}/images', headers=headers, json=payload, timeout=300)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code == 401:
            return None, 'PROVIDER_AUTH_FAILED'
        if response.status_code == 402:
            return None, 'INSUFFICIENT_CREDITS'
        if response.status_code == 429:
            return None, 'RATE_LIMITED'
        if response.status_code >= 400 or data.get('error'):
            print(f'[FLOOR IMAGE ERROR] model={model} status={response.status_code}')
            return None, 'IMAGE_PROVIDER_FAILED'
        item = (data.get('data') or [{}])[0]
        encoded = item.get('b64_json') if isinstance(item, dict) else None
        if encoded:
            return f'data:image/png;base64,{encoded}', None
        image_url = item.get('url') if isinstance(item, dict) else None
        if image_url:
            image_response = requests.get(image_url, timeout=120)
            image_response.raise_for_status()
            mime = image_response.headers.get('Content-Type', 'image/png').split(';', 1)[0]
            return f'data:{mime};base64,{base64.b64encode(image_response.content).decode("ascii")}', None
        return None, 'IMAGE_PROVIDER_EMPTY'
    except requests.exceptions.Timeout:
        return None, 'IMAGE_PROVIDER_TIMEOUT'
    except requests.exceptions.RequestException:
        return None, 'IMAGE_PROVIDER_FAILED'


def normalize_presentation_assets(value, tenant_id):
    """Replace embedded image data URIs with compact tenant-scoped file URLs."""
    if isinstance(value, dict):
        return {key: normalize_presentation_assets(item, tenant_id) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_presentation_assets(item, tenant_id) for item in value]
    if not isinstance(value, str) or 'data:image/' not in value:
        return value
    if value.startswith('data:image/'):
        return persist_generated_image(value, tenant_id)
    return re.sub(
        r'data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=]+',
        lambda match: persist_generated_image(match.group(0), tenant_id),
        value,
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Generate PDF with Playwright
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def generate_pdf_with_playwright(html, project_name, branding=None, output_dir=None, tenant_id=None):
    """Generate a PDF from slide HTML using the new generate_pdf export."""
    from exports.pdf_export import generate_pdf
    out_dir = output_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'presentation'
    out_path = os.path.join(out_dir, f"{safe_name}_{int(time.time())}.pdf")
    generate_pdf(html, branding, out_path, tenant_id)
    return out_path

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
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
    
    # Landmark driving times and distances
    if isinstance(images, dict) and images.get('map_landmarks'):
        landmarks = images['map_landmarks']
        if landmarks:
            info += "\n## أوقات القيادة والمسافات الفعلية من Google Maps\n"
            info += "استخدم هذه البيانات الحقيقية في شريحة المعالم (map_landmarks):\n"
            for lm in landmarks:
                name = lm.get('name', lm.get('description', 'معلم'))
                duration = lm.get('duration_minutes', '?')
                dist = lm.get('distance_text', '?')
                info += f"- {name}: {duration} دقيقة، {dist}\n"
    
    return info

def build_system_prompt(project_data, images_info, design_rules=None):
    """Build the shared system prompt ONCE for all slides (~3K chars)."""
    if design_rules is None:
        design_rules = build_design_rules({})
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)
    # Truncate project data if too long to keep system prompt compact
    if len(project_json) > 4000:
        project_json = project_json[:4000] + '\n... [تم اختصار البيانات]'
    return f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}"""

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


def postprocess_slide(html, slide_num=None, tenant_id=None, slide_title=None, total_slides=None, slide_type=None):
    """Compatibility wrapper around slide_engine.postprocess_slide.

    Existing callers in app.py pass (html, slide_num, tenant_id). The slide_engine
    implementation is semantic-type driven and no longer depends on SLIDE_DEFS.
    """
    if slide_type is None:
        n = int(slide_num or 0)
        t = int(total_slides or 0)
        normalized_title = str(slide_title or '').strip().lower()
        if n == 1 or re.search(r'غلاف|cover|front', normalized_title):
            slide_type = 'cover'
        elif (t and n == t) or re.search(r'ختام|closing|شكراً|شكرًا|thanks', normalized_title):
            slide_type = 'closing'
        else:
            slide_type = 'content'

    branding = db.get_branding(tenant_id) if tenant_id else None
    return slide_engine.postprocess_slide(
        html,
        slide_type,
        slide_num=slide_num,
        slide_title=slide_title,
        total_slides=total_slides,
        tenant_id=tenant_id,
        branding=branding,
    )

def generate_single_slide(system_prompt, slide_num, tenant_id=None, max_retries=2, total=None, title=None):
    """Generate one complete slide, retrying with a stricter prompt when needed."""
    slide_title = title or f'شريحة {slide_num}'
    style = _suggest_design_style(slide_title, slide_type='content')
    slide = {
        'title': slide_title,
        'type': 'content',
        'design_style': style,
        'content_density': 'medium',
        'requires_image': False,
        'bullets': []
    }
    branding = db.get_branding(tenant_id) if tenant_id else {}
    if total is None:
        _min_s, _max_s, total = resolve_slide_bounds(branding)
        total = max(_min_s, min(total, _max_s))
    total = int(total)
    base_user_msg = slide_engine.build_slide_user_msg(slide, slide_num, total, branding)

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
            html = postprocess_slide(html, slide_num, tenant_id=tenant_id, slide_title=slide_title, total_slides=total, slide_type='content')
            html = slide_engine.resolve_logo_in_html(html, tenant_id)
            count = html.count('class="slide"')
            if count >= 1:
                print(f"[SLIDE-{slide_num}] OK Done ({len(html)} chars)")
                return html
            print(f"[SLIDE-{slide_num}] WARN No slide found (attempt {attempt})")
        except Exception as e:
            print(f"[SLIDE-{slide_num}] EXCEPTION (attempt {attempt}): {e}")

    print(f"[SLIDE-{slide_num}] FAIL All attempts failed for {slide_title}")
    return ''

def build_glm_prompt(project_data, images, branding=None):
    """Legacy single-shot prompt builder (kept for /api/generate compatibility)."""
    project_data = clean_project_data(project_data)
    images_info = _get_images_info(images)

    # Resolve dynamic brand rules
    if branding is None:
        tenant_id = getattr(g, 'tenant_id', None)
        branding = db.get_branding(tenant_id) if tenant_id else {}
    dynamic_rules = build_design_rules(branding)
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    slide_count = max(min_s, min(default_count, max_s))
    fallback_plan = build_fallback_plan(branding)
    slides = fallback_plan.get('slides', [])
    generic_slide = {
        'title': 'تفاصيل إضافية',
        'type': 'content',
        'design_style': _suggest_design_style('تفاصيل إضافية', slide_type='content'),
        'content_density': 'medium',
        'requires_image': False,
        'bullets': []
    }

    sys_prompt = build_system_prompt(project_data, images_info, dynamic_rules)
    return sys_prompt + '\n\n'.join(
        slide_engine.build_slide_user_msg(slides[i] if i < len(slides) else generic_slide, i + 1, slide_count, branding)
        for i in range(slide_count)
    )

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
            slides = extract_slide_elements(html)
            if slides:
                return '\n'.join(slides)

    # Keep only complete slide roots; discard AI prose/punctuation around them.
    slides = extract_slide_elements(content)
    if slides:
        return '\n'.join(slides)

    # Fallback: regex match (may miss deeply nested slides)
    slides_regex = re.findall(r'<div\s+class="slide"[\s\S]*?</div>\s*</div>\s*</div>\s*</div>', content)
    if slides_regex:
        return '\n'.join(slides_regex)

    if '<div' in content and 'class="slide"' in content:
        return content

    return content

def validate_html(html, expected_count=None):
    slide_count = html.count('class="slide"')
    threshold = expected_count
    if threshold is None:
        tenant_id = getattr(g, 'tenant_id', None)
        branding = db.get_branding(tenant_id) if tenant_id else {}
        _min_s, _max_s, threshold = resolve_slide_bounds(branding)
        threshold = max(_min_s, min(threshold, _max_s))
    if slide_count < threshold:
        print(f"[WARN] Only {slide_count} slides found, expected {threshold}")
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
        images['cover'] = persist_generated_image(call_image_api(cover_prompt), getattr(g, 'tenant_id', None))
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
            img = persist_generated_image(call_image_api_with_reference(reference_image, prompt), getattr(g, 'tenant_id', None))
        else:
            img = persist_generated_image(call_image_api(prompt), getattr(g, 'tenant_id', None))
        images['moodboard'].append(img)
        print(f"[IMAGES] Moodboard {i+1}/{target_count}: {'OK' if img else 'FAILED'}")
        if i < len(moodboard_prompts) - 1:
            time.sleep(1)

    print(f"[IMAGES] Done. Cover: {'OK' if images['cover'] else 'FAIL'}, Moodboard: {sum(1 for x in images['moodboard'] if x)}/{target_count}")
    has_cover = bool(images['cover'])
    has_moodboard = any(images['moodboard'])
    requested_cover = include_cover
    # Only fail if nothing usable came back; otherwise preserve partial results with a warning.
    if requested_cover and not has_cover and not has_moodboard:
        if not OPENROUTER_KEY:
            return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'}), 400
        return jsonify({'success': False, 'error': 'تعذر توليد الصور — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'}), 400
    warning = None
    if requested_cover and not has_cover:
        warning = 'تعذر توليد صورة الغلاف — تم توليد المود بورد فقط'
    elif target_count and not has_moodboard:
        warning = 'تعذر توليد صور المود بورد — تم توليد الغلاف فقط'
    return jsonify({'success': True, 'images': images, 'warning': warning})

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
        output_path = generate_pdf_with_playwright(slides_html, project_name, tenant_id=g.tenant_id)
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
    """Compatibility: Generate outline/titles following tenant slide bounds."""
    project_data = clean_project_data(request.json.get('projectData', {}))
    print(f"\n[OUTLINE] Generating outline for: {project_data.get('projectName', 'Unknown')}")

    tenant_id = getattr(g, 'tenant_id', None)
    branding = db.get_branding(tenant_id) if tenant_id else {}
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    target_count = max(min_s, min(default_count, max_s))

    if target_count == 1:
        structure_lines = ['1. شريحة غلاف (type="cover")']
    elif target_count == 2:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة ختام (type="closing")']
    elif target_count == 3:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة فهرس (type="index")', '3. شريحة ختام (type="closing")']
    elif target_count == 4:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة فهرس (type="index")', '3. شريحة محتوى (type="content")', '4. شريحة ختام (type="closing")']
    else:
        structure_lines = ['1. شريحة غلاف (type="cover")', '2. شريحة فهرس (type="index")',
                           f'3-{target_count - 2}. شرائح محتوى (type="content")',
                           f'{target_count - 1}. شريحة مود بورد (type="mood_board")',
                           f'{target_count}. شريحة ختام (type="closing")']
    structure_text = '\n'.join(structure_lines)

    prompt = f"""أنت محلل مالي وعقاري ذكي. قم بإنشاء هيكل (outline) عرض تقديمي مخصص بالكامل لمشروع المستخدم.

المطلوب: {target_count} شرائح بالترتيب التالي:
{structure_text}

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

Return ONLY valid JSON: {{"titles": [{{"title": "عنوان الشريحة", "bullets": ["نقطة 1", "نقطة 2"], "type": "content"}}]}}
"""

    try:
        response = call_zai_chat(prompt, f"اكتب الهيكل المكون من {target_count} شريحة.", max_tokens=4000)
        raw = extract_chat_content(response, "OUTLINE")

        json_match = re.search(r'\{[\s\S]*"titles"[\s\S]*\}', raw)
        if not json_match:
            raise Exception("No JSON found in response")

        parsed = json.loads(json_match.group())
        titles = parsed.get('titles', [])

        if len(titles) < target_count:
            while len(titles) < target_count:
                titles.append({'title': f'شريحة {len(titles)+1}', 'bullets': [], 'type': 'content'})

        if len(titles) > target_count:
            titles = titles[:target_count]

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
            return jsonify({'success': True, 'image': persist_generated_image(image, getattr(g, 'tenant_id', None))})
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
            return jsonify({'success': True, 'image': persist_generated_image(image, getattr(g, 'tenant_id', None))})
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
            return jsonify({'success': True, 'image': persist_generated_image(image, getattr(g, 'tenant_id', None))})
        else:
            if not OPENROUTER_KEY:
                return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ — يرجى إضافته في ملف .env', 'error_code': 'NO_API_KEY'})
            return jsonify({'success': False, 'error': 'تعذر توليد الصورة — تحقق من مفتاح OpenRouter ورصيده', 'error_code': 'IMAGE_FAILED'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


FLOOR_DESIGN_PROMPT_VERSION = 3


FLOOR_DESIGN_LAND_KEYS = (
    'croquis_land_area', 'approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio',
    'max_floors_height', 'building_ratio_coverage', 'setbacks', 'allowed_uses', 'regulatory_constraints',
    'building_ratio_setbacks', 'allowed_uses_restrictions', 'land_and_building_summary',
    'boundary_lengths', 'surrounding_streets', 'facades_count', 'facades_directions',
    'land_documents_files_file_meta', 'directions_table', 'survey_coordinates',
)
FLOOR_DESIGN_PROJECT_KEYS = (
    'project_name', 'project_type', 'project_idea', 'project_goal', 'target_audience',
    'project_stage', 'location_address', 'location_detail', 'location_lat', 'location_lng',
)
FLOOR_DESIGN_FINANCIAL_KEYS = (
    'builtUpAreaAbove', 'basementArea', 'floorCount', 'totalBuiltUpArea', 'coverageRate',
    'landArea', 'coveredArea', 'openArea', 'project_components_data', 'financial_calc_data',
    'financial_study_model',
)


def _floor_design_parse_json(value, fallback=None):
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _floor_design_text(value, limit=5000):
    if value is None:
        return ''
    return str(value).strip()[:limit]


def _floor_design_read(source, key, *aliases):
    for candidate in (key, *aliases):
        value = source.get(candidate) if isinstance(source, dict) else None
        if value not in (None, '', [], {}):
            return value
    return ''


def _floor_design_financial_sources(source):
    model = _floor_design_parse_json(source.get('financial_study_model'), {}) or {}
    inputs = model.get('inputs') if isinstance(model, dict) and isinstance(model.get('inputs'), dict) else {}
    model_calc = model.get('financialCalcData') if isinstance(model, dict) and isinstance(model.get('financialCalcData'), dict) else {}
    legacy_calc = _floor_design_parse_json(source.get('financial_calc_data'), {}) or {}
    return inputs, model_calc, legacy_calc if isinstance(legacy_calc, dict) else {}


def _floor_design_financial_read(source, key, *aliases):
    candidates = (key, *aliases)
    inputs, model_calc, legacy_calc = _floor_design_financial_sources(source)
    for container in (inputs, source, model_calc, legacy_calc):
        value = _floor_design_read(container, candidates[0], *candidates[1:])
        if value not in (None, '', [], {}):
            return value
    return ''


def _floor_design_components(source):
    raw = _floor_design_parse_json(source.get('project_components_data'))
    if not isinstance(raw, list):
        financial_model = _floor_design_parse_json(source.get('financial_study_model'), {}) or {}
        dynamic = financial_model.get('dynamicRows') if isinstance(financial_model, dict) else {}
        raw = dynamic.get('components') if isinstance(dynamic, dict) else None
    if not isinstance(raw, list):
        _inputs, model_calc, legacy_calc = _floor_design_financial_sources(source)
        raw = model_calc.get('components') if isinstance(model_calc, dict) else None
        if not isinstance(raw, list):
            raw = legacy_calc.get('components') if isinstance(legacy_calc, dict) else None
    if not isinstance(raw, list):
        return []
    keys = (
        'id', 'name', 'useType', 'units', 'unitArea', 'builtArea', 'revenueArea', 'totalArea',
        'investmentModel', 'floorNumbers', 'floors', 'groupIds', 'floorAreas', 'areaPerFloor',
        'grossArea', 'netArea', 'color', 'unitsPerFloor', 'unitCountPerFloor', 'floorUnits',
        'unit_area', 'units_per_floor',
    )
    return [{key: item.get(key) for key in keys if item.get(key) not in (None, '')}
            for item in raw[:100] if isinstance(item, dict)]


def _floor_design_number(value):
    if value in (None, '') or isinstance(value, bool):
        return None
    text = str(value).strip().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789'))
    text = text.replace('\u066c', '').replace('\u066b', '.')
    match = re.search(r'[-+]?\d[\d\s,.]*', text)
    if not match:
        return None
    token = re.sub(r'\s+', '', match.group(0))
    if ',' in token and '.' not in token:
        parts = token.split(',')
        token = '.'.join(parts) if len(parts) == 2 and 0 < len(parts[1]) <= 2 else ''.join(parts)
    else:
        token = token.replace(',', '')
    try:
        number = float(token)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _floor_design_coverage_number(value):
    text = _floor_design_text(value, 12000)
    coverage_match = re.search(r'(?:نسبة\s*)?التغطية[^\d٠-٩۰-۹+-]{0,40}([-+]?\d[\d٠-٩۰-۹\s,.٬٫]*)', text)
    return _floor_design_number(coverage_match.group(1) if coverage_match else value)


def _floor_design_values_conflict(first, second, *, coverage=False):
    parser = _floor_design_coverage_number if coverage else _floor_design_number
    first_number, second_number = parser(first), parser(second)
    if first_number is None or second_number is None:
        return False, first_number, second_number
    tolerance = 0.01 if coverage else max(0.01, max(abs(first_number), abs(second_number)) * 0.001)
    return abs(first_number - second_number) > tolerance, first_number, second_number


def _floor_design_shared_values(land, financial):
    definitions = (
        ('approved_area', 'المساحة المعتمدة', land.get('approved_financial_area'), financial.get('landArea'), False),
        ('approved_floor_count', 'عدد الطوابق المعتمد', land.get('approved_floor_count'), financial.get('floorCount'), False),
        ('approved_coverage', 'نسبة التغطية المعتمدة', land.get('approved_coverage_ratio'), financial.get('coverageRate'), False),
    )
    shared, conflicts = {}, []
    for key, label, land_value, financial_value, is_coverage in definitions:
        differs, land_number, financial_number = _floor_design_values_conflict(
            land_value, financial_value, coverage=is_coverage)
        shared[key] = {
            'land_croquis_value': land_value,
            'financial_study_value': financial_value,
            'land_croquis_number': land_number,
            'financial_study_number': financial_number,
        }
        if differs:
            conflicts.append({
                'key': key,
                'label': label,
                'land_croquis_value': land_value,
                'financial_study_value': financial_value,
                'note': 'تعارض بين بيانات الأرض والكروكي والدراسة المالية. اعرض القيمتين ولا تختر قيمة أو تعدل بيانات المستخدم.',
            })
    return shared, conflicts


def _floor_design_state_conflicts(raw_state, groups, land, financial):
    state = _floor_design_parse_json(raw_state, {}) or {}
    state_floor_count = state.get('floorCount') if isinstance(state, dict) else None
    assigned_floors = sorted({floor for group in groups for floor in group.get('floorNumbers', [])})
    group_floor_count = len(assigned_floors)
    group_range = ''
    if assigned_floors:
        group_range = f'{assigned_floors[0]}-{assigned_floors[-1]} ({group_floor_count} طابق)'

    approved_sources = (
        ('بيانات الأرض والكروكي', land.get('approved_floor_count')),
        ('الدراسة المالية', financial.get('floorCount')),
    )
    design_sources = (
        ('floorDesignState.floorCount', state_floor_count, state_floor_count),
        ('المدى الفعلي لمجموعات الأدوار', group_range, group_floor_count if assigned_floors else None),
    )
    conflicts = []
    for design_source, display_value, numeric_value in design_sources:
        for approved_source, approved_value in approved_sources:
            differs, _design_number, _approved_number = _floor_design_values_conflict(numeric_value, approved_value)
            if not differs:
                continue
            conflicts.append({
                'key': 'floor_design_floor_count',
                'label': 'تعارض عدد طوابق المخطط المحفوظ',
                'source_a': design_source,
                'value_a': display_value,
                'source_b': approved_source,
                'value_b': approved_value,
                'note': 'بيانات المخطط المحفوظة لا تطابق عدد الطوابق المعتمد. اعرض القيمتين ولا تزامن المجموعات أو تعدل بيانات المستخدم.',
            })
    return conflicts


def _floor_design_groups(raw_state):
    state = _floor_design_parse_json(raw_state, {}) or {}
    groups = state.get('groups') if isinstance(state, dict) else []
    if not isinstance(groups, list):
        return []
    output = []
    for group in groups[:200]:
        if not isinstance(group, dict):
            continue
        floors = sorted({int(number) for number in (group.get('floorNumbers') or [])
                         if isinstance(number, (int, float)) and int(number) == number and 0 <= int(number) <= 500})
        if not floors:
            continue
        output.append({
            'id': _floor_design_text(group.get('id'), 120),
            'name': _floor_design_text(group.get('name'), 160),
            'floorNumbers': floors,
            'description': _floor_design_text(group.get('prompt'), 12000),
            'components': group.get('components') if isinstance(group.get('components'), list) else [],
            'unitsPerFloor': group.get('unitsPerFloor') or group.get('unitCountPerFloor'),
            'unitArea': group.get('unitArea'),
        })
    assigned = {floor for group in output for floor in group['floorNumbers']}
    try:
        floor_count = int(state.get('floorCount') or 0)
        first_floor = int(state.get('firstFloor') or 1)
    except (TypeError, ValueError):
        floor_count, first_floor = 0, 1
    for floor in range(first_floor, first_floor + max(0, min(floor_count, 500))):
        if floor not in assigned:
            output.append({'id': f'unassigned-{floor}', 'name': f'الدور {floor}', 'floorNumbers': [floor], 'description': '', 'components': []})
    return output


def _sanitize_floor_design_request(data):
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    state = data.get('floorDesignState') if isinstance(data.get('floorDesignState'), dict) else project_data.get('floor_visual_design', {})
    project = {key: _floor_design_text(_floor_design_read(project_data, key), 4000)
               for key in FLOOR_DESIGN_PROJECT_KEYS}
    land = {key: _floor_design_text(_floor_design_read(project_data, key), 12000)
            for key in FLOOR_DESIGN_LAND_KEYS}
    land['building_ratio_coverage'] = _floor_design_text(
        _floor_design_read(project_data, 'building_ratio_coverage', 'building_ratio_setbacks'), 12000)
    land['setbacks'] = _floor_design_text(
        _floor_design_read(project_data, 'setbacks', 'building_ratio_setbacks'), 12000)
    land['allowed_uses'] = _floor_design_text(
        _floor_design_read(project_data, 'allowed_uses', 'allowed_uses_restrictions'), 12000)
    land['regulatory_constraints'] = _floor_design_text(
        _floor_design_read(project_data, 'regulatory_constraints', 'allowed_uses_restrictions'), 12000)
    for key in ('directions_table', 'survey_coordinates', 'land_documents_files_file_meta'):
        parsed = _floor_design_parse_json(_floor_design_read(project_data, key), None)
        if parsed is not None:
            land[key] = parsed
    financial = {
        'approved_financial_area': _floor_design_read(project_data, 'approved_financial_area'),
        'approved_floor_count': _floor_design_read(project_data, 'approved_floor_count'),
        'landArea': _floor_design_financial_read(project_data, 'landArea', 'land_area'),
        'builtUpAreaAbove': _floor_design_financial_read(project_data, 'builtUpAreaAbove', 'built_up_area_above'),
        'floorCount': _floor_design_financial_read(project_data, 'floorCount', 'floor_count'),
        'basementArea': _floor_design_financial_read(project_data, 'basementArea', 'basement_area'),
        'totalBuiltUpArea': _floor_design_financial_read(project_data, 'totalBuiltUpArea', 'total_built_up_area'),
        'coverageRate': _floor_design_financial_read(project_data, 'coverageRate', 'coverage_rate'),
        'coveredArea': _floor_design_financial_read(project_data, 'coveredArea', 'covered_area'),
        'openArea': _floor_design_financial_read(project_data, 'openArea', 'open_area'),
        'components': _floor_design_components(project_data),
    }
    land_area_number = _floor_design_number(financial['landArea'])
    coverage_number = _floor_design_number(financial['coverageRate'])
    above_number = _floor_design_number(financial['builtUpAreaAbove'])
    basement_number = _floor_design_number(financial['basementArea'])
    if financial['totalBuiltUpArea'] in (None, '') and above_number is not None and basement_number is not None:
        financial['totalBuiltUpArea'] = above_number + basement_number
    if financial['coveredArea'] in (None, '') and land_area_number is not None and coverage_number is not None:
        financial['coveredArea'] = land_area_number * coverage_number / 100
    if financial['openArea'] in (None, '') and land_area_number is not None and coverage_number is not None:
        financial['openArea'] = land_area_number - (land_area_number * coverage_number / 100)
    shared_values, data_conflicts = _floor_design_shared_values(land, financial)
    groups = _floor_design_groups(state)
    data_conflicts.extend(_floor_design_state_conflicts(state, groups, land, financial))
    return {
        'project': project,
        'land': land,
        'financial': financial,
        'shared_values': shared_values,
        'data_conflicts': data_conflicts,
        'groups': groups,
    }


def _floor_design_coordinate_value(row, *keys):
    if not isinstance(row, dict):
        return None
    lowered = {str(key).strip().casefold(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(str(key).casefold())
        number = _floor_design_number(value)
        if number is not None:
            return number
    return None


def _floor_design_coordinate_rows(raw):
    if isinstance(raw, dict):
        raw = raw.get('rows') or raw.get('coordinates') or raw.get('survey_coordinates') or []
    if not isinstance(raw, list):
        return []
    rows = []
    for index, item in enumerate(raw[:500]):
        if not isinstance(item, dict):
            continue
        lowered_keys = {str(key).strip().casefold() for key in item}
        geographic_keys = {'lng', 'longitude', 'lon', 'lat', 'latitude'}
        local_keys = {'eastings', 'easting', 'x', 'coordinate_x', 'northings', 'northing', 'y',
                      'coordinate_y', 'الشرقيات', 'الشماليات'}
        has_geographic_keys = bool(lowered_keys & geographic_keys)
        has_local_keys = bool(lowered_keys & local_keys)
        coordinate_kind = 'mixed' if has_geographic_keys and has_local_keys else (
            'geographic' if has_geographic_keys else 'local' if has_local_keys else 'unknown')
        x = _floor_design_coordinate_value(
            item, 'eastings', 'easting', 'x', 'coordinate_x', 'lng', 'longitude', 'lon', 'الشرقيات')
        y = _floor_design_coordinate_value(
            item, 'northings', 'northing', 'y', 'coordinate_y', 'lat', 'latitude', 'الشماليات')
        if x is None or y is None:
            continue
        rows.append({'point': _floor_design_text(item.get('point') or item.get('point_number') or index + 1, 80),
                     'x': x, 'y': y, 'coordinateKind': coordinate_kind})
    if len(rows) > 2 and rows[0]['x'] == rows[-1]['x'] and rows[0]['y'] == rows[-1]['y']:
        rows.pop()
    return rows


def _floor_design_direction_rows(raw):
    if isinstance(raw, dict):
        raw = raw.get('rows') or [dict(value, direction=key) if isinstance(value, dict) else {'direction': key, 'value': value}
                                  for key, value in raw.items()]
    return [row for row in raw if isinstance(row, dict)][:500] if isinstance(raw, list) else []


def _floor_design_polygon_geometry(land):
    source_rows = _floor_design_coordinate_rows(land.get('survey_coordinates'))
    result = {
        'coordinateMode': 'unavailable', 'sourceVertices': source_rows, 'verticesMeters': [],
        'edges': [], 'areaSqm': None, 'rotation': None, 'calculationStatus': 'unavailable',
        'missingItems': [], 'sourceLengthConflicts': [],
    }
    if len(source_rows) < 3:
        result['missingItems'].append('polygon_coordinates_for_computed_angles_and_area')
        return result
    coordinate_kinds = {row.get('coordinateKind') for row in source_rows}
    if 'mixed' in coordinate_kinds or ('geographic' in coordinate_kinds and 'local' in coordinate_kinds):
        result['missingItems'].append('consistent_coordinate_system')
        result['calculationStatus'] = 'rejected_mixed_coordinate_system'
        return result
    geographic = coordinate_kinds == {'geographic'}
    if geographic and not all(abs(row['x']) <= 180 and abs(row['y']) <= 90 for row in source_rows):
        result['missingItems'].append('valid_geographic_coordinates')
        result['calculationStatus'] = 'rejected_invalid_geographic_coordinates'
        return result
    if 'unknown' in coordinate_kinds:
        result['missingItems'].append('declared_coordinate_system')
        result['calculationStatus'] = 'rejected_unknown_coordinate_system'
        return result
    if geographic:
        origin_lon = sum(row['x'] for row in source_rows) / len(source_rows)
        origin_lat = sum(row['y'] for row in source_rows) / len(source_rows)
        radius = 6378137.0
        points = [{
            'point': row['point'],
            'x': radius * math.radians(row['x'] - origin_lon) * math.cos(math.radians(origin_lat)),
            'y': radius * math.radians(row['y'] - origin_lat),
        } for row in source_rows]
        result['coordinateMode'] = 'geographic_converted_local_meters'
        result['localOrigin'] = {'latitude': round(origin_lat, 8), 'longitude': round(origin_lon, 8)}
    else:
        origin_x, origin_y = source_rows[0]['x'], source_rows[0]['y']
        points = [{'point': row['point'], 'x': row['x'] - origin_x, 'y': row['y'] - origin_y}
                  for row in source_rows]
        result['coordinateMode'] = 'local_or_projected_meters'
        result['localOrigin'] = {'x': origin_x, 'y': origin_y}
    twice_area = sum(
        points[index]['x'] * points[(index + 1) % len(points)]['y']
        - points[(index + 1) % len(points)]['x'] * points[index]['y']
        for index in range(len(points)))
    if abs(twice_area) < 0.001:
        result['missingItems'].append('non_degenerate_polygon')
        result['calculationStatus'] = 'rejected_degenerate_polygon'
        return result
    direction_rows = _floor_design_direction_rows(land.get('directions_table'))
    source_lengths = []
    for row in direction_rows:
        source_lengths.append(_floor_design_number(
            row.get('length') or row.get('boundary_length') or row.get('distance')))
    edges = []
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        dx, dy = following['x'] - point['x'], following['y'] - point['y']
        length = math.hypot(dx, dy)
        azimuth = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        compass = ('North' if azimuth < 22.5 or azimuth >= 337.5 else 'North East' if azimuth < 67.5
                   else 'East' if azimuth < 112.5 else 'South East' if azimuth < 157.5
                   else 'South' if azimuth < 202.5 else 'South West' if azimuth < 247.5
                   else 'West' if azimuth < 292.5 else 'North West')
        source_length = source_lengths[index] if index < len(source_lengths) else None
        edge = {'edge': index + 1, 'from': point['point'], 'to': following['point'],
                'deltaX': round(dx, 3), 'deltaY': round(dy, 3), 'computedLength': round(length, 3),
                'azimuthDegrees': round(azimuth, 3), 'direction': compass,
                'sourceLength': source_length}
        if source_length is not None and abs(source_length - length) > max(0.05, source_length * 0.005):
            conflict = {'edge': index + 1, 'sourceLength': source_length,
                        'computedLength': round(length, 3), 'status': 'unapproved_source_length_conflict'}
            result['sourceLengthConflicts'].append(conflict)
            edge['lengthConflict'] = conflict
        edges.append(edge)
    result.update({
        'verticesMeters': [{'point': point['point'], 'x': round(point['x'], 3), 'y': round(point['y'], 3)}
                           for point in points],
        'edges': edges, 'areaSqm': round(abs(twice_area) / 2, 3),
        'rotation': 'counterclockwise' if twice_area > 0 else 'clockwise', 'calculationStatus': 'computed',
    })
    return result


def _floor_design_setback_spec(land, geometry):
    rows = _floor_design_direction_rows(land.get('directions_table'))
    setbacks_text = _floor_design_text(land.get('setbacks'), 12000)
    mapped_setbacks = []
    for index, row in enumerate(rows):
        value = _floor_design_number(row.get('setback') or row.get('setback_meters') or row.get('ارتداد'))
        if value is not None:
            mapped_setbacks.append({'edge': index + 1, 'valueMeters': value})
    result = {'sourceText': setbacks_text, 'boundaryRows': rows, 'mappedSetbacks': mapped_setbacks,
              'buildableEnvelopeStatus': 'unavailable', 'buildableEnvelope': None, 'requirements': []}
    if geometry.get('calculationStatus') != 'computed':
        result['requirements'].append('buildable_envelope_requires_computable_polygon')
    elif len(geometry.get('edges', [])) != 4 or len(mapped_setbacks) != 4:
        result['requirements'].append('approved_edge_setback_mapping_required')
    else:
        vertices = geometry['verticesMeters']
        xs, ys = [item['x'] for item in vertices], [item['y'] for item in vertices]
        axis_aligned = all(abs(edge['deltaX']) < 0.02 or abs(edge['deltaY']) < 0.02 for edge in geometry['edges'])
        values = [item['valueMeters'] for item in mapped_setbacks]
        if axis_aligned:
            width, height = max(xs) - min(xs), max(ys) - min(ys)
            horizontal_edges = [index for index, edge in enumerate(geometry['edges']) if abs(edge['deltaY']) < 0.02]
            vertical_edges = [index for index, edge in enumerate(geometry['edges']) if abs(edge['deltaX']) < 0.02]
            horizontal_setbacks = sum(values[index] for index in horizontal_edges)
            vertical_setbacks = sum(values[index] for index in vertical_edges)
            envelope_width = width - vertical_setbacks
            envelope_height = height - horizontal_setbacks
            if envelope_width > 0 and envelope_height > 0:
                result['buildableEnvelopeStatus'] = 'computed_axis_aligned_rectangle'
                result['buildableEnvelope'] = {
                    'widthMeters': round(envelope_width, 3), 'heightMeters': round(envelope_height, 3),
                    'areaSqm': round(envelope_width * envelope_height, 3),
                    'setbacksByEdge': mapped_setbacks,
                }
            else:
                result['requirements'].append('setbacks_exceed_plot_dimensions')
        else:
            result['requirements'].append('irregular_polygon_offset_requires_approved_engineering_envelope')
    return result


def _floor_design_component_floor_numbers(component, group):
    explicit = component.get('floorNumbers') or component.get('floors') or []
    if isinstance(explicit, str):
        explicit = [_floor_design_number(item) for item in re.findall(r'\d+', explicit)]
    floors = sorted({int(item) for item in explicit if isinstance(item, (int, float)) and int(item) == item}) if isinstance(explicit, list) else []
    group_ids = component.get('groupIds') if isinstance(component.get('groupIds'), list) else []
    if group.get('id') in [str(item) for item in group_ids]:
        floors = group['floorNumbers']
    return [floor for floor in floors if floor in group['floorNumbers']]


def _floor_design_round_number(value):
    if value is None:
        return None
    number = round(float(value), 2)
    return int(number) if number.is_integer() else number


def _floor_design_group_units_per_floor(group):
    for key in ('unitsPerFloor', 'unitCountPerFloor', 'floorUnits', 'units_per_floor'):
        number = _floor_design_number(group.get(key))
        if number is not None and number > 0:
            return number, f'group.{key}'
    description = ' '.join(_floor_design_text(group.get(key), 12000) for key in ('name', 'description'))
    number_pattern = r'([-+]?\d[\d\s,٬٫.]*)'
    unit_pattern = r'(?:وحد(?:ة|ه|ات)|شقق?|units?|apartments?)'
    floor_pattern = r'(?:الطابق(?:\s+الواحد)?|الدور(?:\s+الواحد)?|floor)'
    patterns = (
        rf'(?:في|لكل|per)\s*{floor_pattern}[^0-9٠-٩۰-۹]{{0,80}}{number_pattern}\s*{unit_pattern}',
        rf'{number_pattern}\s*{unit_pattern}[^0-9٠-٩۰-۹]{{0,80}}(?:في|لكل|per)\s*{floor_pattern}',
    )
    for pattern in patterns:
        match = re.search(pattern, description, flags=re.IGNORECASE)
        if match:
            number = _floor_design_number(match.group(1))
            if number is not None and number > 0:
                return number, 'group.description'
    return None, ''


def _floor_design_component_unit_area(component, group):
    for source in (component, group):
        for key in ('unitArea', 'unit_area', 'areaPerUnit'):
            number = _floor_design_number(source.get(key))
            if number is not None and number > 0:
                return number, f'{key}'
    return None, ''


def _floor_design_component_units_per_floor(component, group, floors):
    for key in ('unitsPerFloor', 'unitCountPerFloor', 'floorUnits', 'units_per_floor'):
        number = _floor_design_number(component.get(key))
        if number is not None and number > 0:
            return number, f'component.{key}'
    group_number, group_source = _floor_design_group_units_per_floor(group)
    if group_number is not None:
        return group_number, group_source
    total_units = _floor_design_number(component.get('units'))
    if total_units is not None and total_units > 0 and floors:
        return total_units / len(floors), 'component.units_distributed_across_assigned_floors'
    return None, ''


def _floor_design_is_residential(component, group):
    text = ' '.join(_floor_design_text(source.get(key), 12000)
                    for source in (component, group)
                    for key in ('name', 'useType', 'description'))
    return bool(re.search(r'سكن|شقق|شقة|وحدات\s*سكن|residential|apartments?', text, flags=re.IGNORECASE))


def _floor_design_floor_range(numbers):
    sorted_numbers = sorted({int(number) for number in (numbers or []) if isinstance(number, (int, float)) and int(number) == number})
    if not sorted_numbers:
        return ''
    tokens, start, previous = [], sorted_numbers[0], sorted_numbers[0]
    for number in sorted_numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        tokens.append(str(start) if start == previous else f'{start}-{previous}')
        start = previous = number
    tokens.append(str(start) if start == previous else f'{start}-{previous}')
    return '/'.join(tokens)


def _floor_design_allocate_rounded(total, weights, digits=2):
    if not weights or any(float(weight) < 0 for weight in weights) or sum(float(weight) for weight in weights) <= 0:
        return []
    scale = 10 ** digits
    target = int(round(float(total) * scale))
    weight_total = sum(float(weight) for weight in weights)
    raw = [target * float(weight) / weight_total for weight in weights]
    base = [math.floor(value) for value in raw]
    residual = target - sum(base)
    order = sorted(range(len(raw)), key=lambda index: (-(raw[index] - base[index]), index))
    for index in order[:residual]:
        base[index] += 1
    return [value / scale for value in base]


def _floor_design_space_program(payload, group, floor_number):
    components, rows, missing = payload['financial']['components'], [], []
    for index, component in enumerate(components):
        component_id = _floor_design_text(component.get('id') or index + 1, 80)
        floors = _floor_design_component_floor_numbers(component, group)
        if not floors:
            # No explicit floor assignment: the component is assumed to span
            # every floor in the group, and its total area is split evenly.
            floors = group['floorNumbers']
        floor_areas = component.get('floorAreas') if isinstance(component.get('floorAreas'), dict) else {}
        explicit_area = _floor_design_number(floor_areas.get(str(floor_number), floor_areas.get(floor_number)))
        gross_total = _floor_design_number(component.get('grossArea') or component.get('builtArea') or component.get('totalArea'))
        net_total = _floor_design_number(component.get('netArea'))
        area_per_floor = _floor_design_number(component.get('areaPerFloor'))
        units_total = _floor_design_number(component.get('units'))
        unit_area, unit_area_source = _floor_design_component_unit_area(component, group)
        units_per_floor, units_source = _floor_design_component_units_per_floor(component, group, floors)
        if explicit_area is not None:
            gross_area = explicit_area
        elif floor_number in floors and area_per_floor is not None:
            gross_area = area_per_floor
        elif floor_number in floors and gross_total is not None:
            gross_area = _floor_design_allocate_rounded(gross_total, [1] * len(floors))[floors.index(floor_number)]
        elif floors and floor_number not in floors:
            continue
        else:
            missing.append(f'component_floor_allocation:{component_id}')
            continue
        if gross_area <= 0:
            continue
        net_area = None
        if net_total is not None and gross_total and gross_total > 0:
            net_area = round(gross_area * net_total / gross_total, 2)
        row = {'id': component_id,
               'name': _floor_design_text(component.get('name') or f'Component {index + 1}', 160),
               'useType': _floor_design_text(component.get('useType'), 80),
               'grossAreaSqm': round(gross_area, 2), 'netAreaSqm': net_area,
               'color': _floor_design_text(component.get('color'), 40) or ['#3B6E91', '#7AA6C2', '#C7A56A', '#8A9A5B', '#A97878'][index % 5]}
        if units_total is not None:
            row['unitCountTotal'] = _floor_design_round_number(units_total)
        if unit_area is not None:
            row['unitAreaSqm'] = _floor_design_round_number(unit_area)
            row['unitAreaSource'] = unit_area_source
        if units_per_floor is not None:
            row['unitsPerFloor'] = _floor_design_round_number(units_per_floor)
            row['unitsPerFloorSource'] = units_source
        if _floor_design_is_residential(component, group) and units_per_floor is not None:
            row['layoutType'] = 'repeated_residential_units'
            if unit_area is not None:
                required_unit_area = round(units_per_floor * unit_area, 2)
                row['requiredUnitLayoutAreaSqm'] = required_unit_area
                if abs(required_unit_area - gross_area) > max(0.01, max(required_unit_area, gross_area) * 0.001):
                    row['areaConsistency'] = 'conflict_between_unit_count_area_and_reported_floor_area'
                    row['reportedGrossAreaSqm'] = round(gross_area, 2)
            else:
                row['unitAreaStatus'] = 'unavailable'
        rows.append(row)
    total_area = round(sum(row['grossAreaSqm'] for row in rows), 2)
    percentages = _floor_design_allocate_rounded(100, [row['grossAreaSqm'] for row in rows]) if rows and total_area else []
    for row, percentage in zip(rows, percentages):
        row['percentage'] = percentage
    net_values = [row['netAreaSqm'] for row in rows]
    unit_rows = [row for row in rows if row.get('layoutType') == 'repeated_residential_units']
    unavailable = [] if not rows or all(value is not None for value in net_values) else ['net_area_without_approved_net_rule']
    if any(row.get('areaConsistency') for row in unit_rows):
        unavailable.append('residential_unit_area_conflict')
    if any(row.get('unitAreaStatus') == 'unavailable' for row in unit_rows):
        unavailable.append('residential_unit_area_missing')
    represented_floors = group.get('floorNumbers') or [floor_number]
    return {'floorNumber': floor_number, 'representedFloorRange': _floor_design_floor_range(represented_floors),
            'representedFloorCount': len(represented_floors), 'components': rows, 'grossAreaSqm': total_area,
            'netAreaSqm': round(sum(net_values), 2) if rows and all(value is not None for value in net_values) else None,
            'pieChartSeries': [{'label': row['name'], 'value': row['grossAreaSqm'],
                                'percentage': row['percentage'], 'color': row['color']} for row in rows],
            'residentialLayout': {
                'required': bool(unit_rows),
                'mode': 'repeated_residential_units' if unit_rows else 'component_areas',
                'components': [{key: row[key] for key in (
                    'id', 'name', 'useType', 'unitsPerFloor', 'unitAreaSqm', 'requiredUnitLayoutAreaSqm',
                    'reportedGrossAreaSqm', 'grossAreaSqm', 'areaConsistency', 'unitAreaStatus') if key in row}
                    for row in unit_rows],
            },
            'missingRequirements': sorted(set(missing)), 'unavailableCalculations': sorted(set(unavailable)),
            'rounding': 'largest_remainder_2_decimals'}


def _floor_design_prepare(payload, group):
    geometry = _floor_design_polygon_geometry(payload['land'])
    setbacks = _floor_design_setback_spec(payload['land'], geometry)
    floor_numbers = sorted(group.get('floorNumbers') or [])
    representative_floor = floor_numbers[0] if floor_numbers else None
    is_typical_group = len(floor_numbers) > 1
    floor_range = _floor_design_floor_range(floor_numbers)
    page_type = 'typical_floor' if is_typical_group else 'floor'
    title = f'FLOORS {floor_range} TYPICAL PLAN' if is_typical_group else f'FLOOR {representative_floor} PLAN'
    pages = [{'pageType': page_type, 'floorNumber': representative_floor, 'floorNumbers': floor_numbers,
              'floorRange': floor_range, 'title': title,
              'spaceProgram': _floor_design_space_program(payload, group, representative_floor)}] if representative_floor is not None else []
    return {
        'geometry': geometry, 'setbacks': setbacks,
        'siteContext': {key: payload['land'].get(key) for key in (
            'boundary_lengths', 'surrounding_streets', 'facades_count', 'facades_directions',
            'directions_table', 'max_floors_height', 'regulatory_constraints', 'allowed_uses')},
        'financial': payload['financial'], 'pages': pages,
    }


def _floor_design_preflight(payload, prepared, data):
    missing = _floor_design_missing_requirements(payload)
    blocked = []
    approvals = {str(item) for item in (data.get('approvedConflictKeys') or [])}
    for conflict in payload.get('data_conflicts', []):
        if str(conflict.get('key')) not in approvals:
            blocked.append({'type': 'data_conflict', 'item': conflict})
    for conflict in prepared['geometry'].get('sourceLengthConflicts', []):
        key = f'source_length_edge_{conflict["edge"]}'
        if key not in approvals:
            blocked.append({'type': 'source_length_conflict', 'item': conflict})
    unavailable = list(prepared['geometry'].get('missingItems', []))
    for page in prepared['pages']:
        program = page.get('spaceProgram', {})
        if page['pageType'] in ('floor', 'typical_floor'):
            missing.extend(program.get('missingRequirements', []))
            unavailable.extend(program.get('unavailableCalculations', []))
            if not program.get('components'):
                missing.append(f'space_program_floor_{page["floorNumber"]}')

    geometry_available = prepared['geometry'].get('calculationStatus') == 'computed'
    source_geometry_available = bool(payload['land'].get('boundary_lengths') or payload['land'].get('directions_table'))
    if not geometry_available and not source_geometry_available:
        missing.append('plot_boundary_geometry_or_source_lengths')
    return {'ok': not missing and not blocked, 'missingItems': sorted(set(missing)),
            'blockedItems': blocked, 'unavailableCalculations': sorted(set(unavailable)),
            'requirements': prepared['setbacks'].get('requirements', [])}


def _floor_design_missing_requirements(payload):
    project = payload['project']
    land = payload['land']
    financial = payload['financial']
    missing = []
    try:
        if float(financial['approved_financial_area']) <= 0:
            missing.append('approved_financial_area')
    except (TypeError, ValueError):
        missing.append('approved_financial_area')
    try:
        if int(financial['approved_floor_count']) <= 0 or int(financial['approved_floor_count']) != float(financial['approved_floor_count']):
            missing.append('approved_floor_count')
    except (TypeError, ValueError):
        missing.append('approved_floor_count')
    for key in ('building_ratio_coverage', 'setbacks', 'allowed_uses', 'regulatory_constraints', 'land_and_building_summary'):
        if not land.get(key):
            missing.append(key)
    if not financial['components']:
        missing.append('project_components_data')
    if not payload['groups']:
        missing.append('floor_groups')
    return missing


def _floor_design_compact_prompt_value(value, string_limit, list_limit, key=''):
    if isinstance(value, str):
        return value[:string_limit]
    if isinstance(value, dict):
        return {
            item_key: _floor_design_compact_prompt_value(
                item_value,
                4000 if item_key == 'data_conflicts' else string_limit,
                200 if item_key == 'data_conflicts' else list_limit,
                item_key,
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        effective_limit = 200 if key == 'data_conflicts' else list_limit
        return [_floor_design_compact_prompt_value(item, string_limit, list_limit, key)
                for item in value[:effective_limit]]
    return value


def _floor_design_json_prompt(payload):
    for string_limit, list_limit in ((12000, 200), (6000, 100), (3000, 50), (1500, 25), (800, 12), (400, 8)):
        compact = _floor_design_compact_prompt_value(payload, string_limit, list_limit)
        encoded = json.dumps(compact, ensure_ascii=False, separators=(',', ':'))
        if len(encoded) <= 90000:
            return encoded
    minimal = {
        'project': payload.get('project', {}) if isinstance(payload, dict) else {},
        'land': payload.get('land', {}) if isinstance(payload, dict) else {},
        'financial': payload.get('financial', {}) if isinstance(payload, dict) else {},
        'shared_values': payload.get('shared_values', {}) if isinstance(payload, dict) else {},
        'data_conflicts': payload.get('data_conflicts', []) if isinstance(payload, dict) else [],
        'groups': payload.get('groups', []) if isinstance(payload, dict) else [],
    }
    compact = _floor_design_compact_prompt_value(minimal, 200, 5)
    compact['data_conflicts'] = _floor_design_compact_prompt_value(minimal['data_conflicts'], 4000, 200, 'data_conflicts')
    return json.dumps(compact, ensure_ascii=False, separators=(',', ':'))


def _floor_design_conflicts_section(conflicts):
    if not isinstance(conflicts, list) or not conflicts:
        return ''
    lines = ['تعارضات البيانات الإلزامية']
    for index, conflict in enumerate(conflicts, 1):
        if not isinstance(conflict, dict):
            continue
        source_a = conflict.get('source_a') or 'بيانات الأرض والكروكي'
        value_a = conflict.get('value_a', conflict.get('land_croquis_value', ''))
        source_b = conflict.get('source_b') or 'الدراسة المالية'
        value_b = conflict.get('value_b', conflict.get('financial_study_value', ''))
        label = conflict.get('label') or conflict.get('key') or 'تعارض بيانات'
        lines.append(f'{index}. {label}: المصدر الأول: {source_a}، القيمة: {value_a}. المصدر الثاني: {source_b}، القيمة: {value_b}. لا تحسم التعارض ولا تعدل بيانات المستخدم.')
    return '\n'.join(lines) if len(lines) > 1 else ''


def _floor_design_append_conflicts(prompt, conflicts):
    section = _floor_design_conflicts_section(conflicts)
    if not section:
        return prompt
    conflict_lines = section.splitlines()[1:]
    if conflict_lines and all(line in prompt for line in conflict_lines):
        return prompt
    return prompt.rstrip() + '\n\n' + section


def _floor_design_page_specification(page, prepared, payload, group):
    """Build the authoritative appendix. The image model receives no numeric work to perform."""
    is_typical_group = page.get('pageType') == 'typical_floor'
    is_single_floor = page.get('pageType') == 'floor'
    represented_floors = page.get('floorNumbers') or group.get('floorNumbers') or []
    floor_range = _floor_design_floor_range(represented_floors)
    page_scope = {
        'scope': 'typical_group_floor' if is_typical_group else 'single_floor_only' if is_single_floor else 'group_overview',
        'representativeFloor': page.get('floorNumber'),
        'representedFloorRange': floor_range,
        'representedFloorCount': len(represented_floors),
        'renderOtherFloors': False,
        'typicalFloorRepeat': is_typical_group,
    }
    group_context = {
        'id': group.get('id'), 'name': group.get('name'),
        'description': group.get('description'),
        'floorRange': floor_range,
        'floorCount': len(represented_floors),
        'typicalFloorRepeat': is_typical_group,
        'scopeInstruction': 'This is one representative typical-floor plan for every floor in the supplied range. Do not generate a separate floor 2 plan.'
        if is_typical_group else 'This page represents one floor only.',
    }
    financial_keys = ('landArea', 'builtUpAreaAbove', 'basementArea', 'totalBuiltUpArea', 'coveredArea',
                      'openArea', 'coverageRate')
    if not is_single_floor and not is_typical_group:
        financial_keys += ('floorCount',)
    specification = {
        'contract': {
            'canvas': '16:9 landscape presentation page',
            'layout': {
                'leftColumn': '0 to 24 percent, Table of Contents',
                'centerColumn': '24 to 72 percent, numbered architectural plan',
                'rightColumn': '72 to 100 percent, Pie Charts and Space Program',
            },
            'style': {
                'referenceUse': 'layout, spacing, palette, line hierarchy, and typography only',
                'background': '#F5F1E8 warm ivory', 'primaryLines': '#243B53 at 1.6 px',
                'secondaryLines': '#7A8C99 at 0.8 px', 'accent': '#C7A56A',
                'typography': 'English geometric sans serif, dark navy, consistent table alignment',
            },
        },
        'page': {key: page.get(key) for key in ('pageType', 'floorNumber', 'floorRange', 'title')},
        'pageScope': page_scope,
        'plotGeometry': prepared['geometry'],
        'buildableEnvelope': prepared['setbacks'],
        'siteContext': prepared['siteContext'],
        'spaceProgram': page.get('spaceProgram'),
        'group': group_context,
        'project': payload['project'],
        'dataConflicts': payload.get('data_conflicts', []),
        'financialTotals': {key: payload['financial'].get(key) for key in financial_keys},
        'drawingRules': [
            'For pageScope.scope typical_group_floor, this is one representative plan for every floor in representedFloorRange. Label the range and do not generate or label a separate floor 2 plan. For single_floor_only, label only the current floor.',
            'Treat plotGeometry as the site boundary, not as the building floor plate. Do not shade the whole plot as if it were the building.',
            'Render every supplied plot edge, source length, computed length, azimuth, direction, street, facade, and setback exactly as listed.',
            'Render a conceptual building floor plate separately from the site boundary, using the supplied floor Space Program and never inventing an unavailable setback envelope.',
            'The active floor Space Program and group use govern the floor layout even if the general project type is different; preserve the raw project type as metadata but do not let it replace a residential unit program.',
            'Render the plan with entrances, cores, circulation, component boundaries, and numbered plan references.',
            'If spaceProgram.residentialLayout.required is true, divide the conceptual floor plate into repeated residential unit boundaries using the supplied unitsPerFloor and unitAreaSqm when available. If unitAreaSqm is unavailable, show the repeated unit boundaries and count without inventing dimensions. Show common circulation and cores, and never represent the entire residential floor as one component bubble.',
            'When residential unit area consistency is marked as a conflict, show the conflict clearly and do not silently change either source value.',
            'Match each numbered plan reference to one English Table of Contents row on the left.',
            'Render the complete Space Program table and pie series on the right with every supplied label, area, percentage, color, and residential unit count.',
            'Use unavailable exactly where a calculation status is unavailable. Do not fill an absent measurement.',
            'Do not alter source values when a computed value also exists.',
        ],
        'referenceSafety': [
            'Do not copy Acacia names, project titles, room names, dimensions, values, components, or project content.',
            'No logo and no watermark.',
        ],
    }
    return ('MANDATORY SERVER ENGINEERING SPECIFICATION\n'
            + json.dumps(specification, ensure_ascii=False, indent=2)
            + '\nEND MANDATORY SERVER ENGINEERING SPECIFICATION')


def _floor_design_provider_pages(result):
    pages = result.get('pages') if isinstance(result, dict) else None
    return pages if isinstance(pages, list) else []


def _floor_design_normalize_prompt_pages(result, prepared, payload, group):
    provider_pages = _floor_design_provider_pages(result)
    normalized = []
    for index, page_spec in enumerate(prepared['pages']):
        provider_page = next((item for item in provider_pages if isinstance(item, dict)
                              and item.get('pageType') == page_spec['pageType']
                              and item.get('floorNumber') == page_spec['floorNumber']), None)
        if provider_page is None and index < len(provider_pages) and isinstance(provider_pages[index], dict):
            provider_page = provider_pages[index]
        provider_page = provider_page or {}
        provider_prompt = _floor_design_text(provider_page.get('prompt'), 24000)
        if not provider_prompt and index == 0:
            provider_prompt = _floor_design_text(result.get('prompt'), 24000)
        if page_spec['pageType'] in ('floor', 'typical_floor'):
            if page_spec['pageType'] == 'typical_floor':
                base_prompt = (
                    f'Create one representative typical-floor architectural presentation page for FLOORS {page_spec.get("floorRange")} '
                    f'with FLOOR {page_spec["floorNumber"]} as the representative floor. '
                    'The same design represents every floor in the supplied group; do not create a separate plan for floor 2 only. '
                    'Follow the mandatory server engineering specification verbatim.')
            else:
                base_prompt = (
                    f'Create one single-floor architectural presentation page for FLOOR {page_spec["floorNumber"]} ONLY. '
                    'Do not show, list, compare, or mention any other floor number or the total number of project floors. '
                    'Follow the mandatory server engineering specification verbatim.')
        else:
            base_prompt = provider_prompt or (
                'Create the specified architectural presentation page. Follow the mandatory server engineering specification verbatim.')
        appendix = _floor_design_page_specification(page_spec, prepared, payload, group)
        normalized.append({
            'id': f'{group.get("id") or "group"}:{page_spec["pageType"]}:{page_spec.get("floorNumber") or "overview"}',
            'pageType': page_spec['pageType'], 'floorNumber': page_spec['floorNumber'],
            'floorNumbers': page_spec['floorNumbers'], 'title': page_spec['title'],
            'prompt': base_prompt.rstrip() + '\n\n' + appendix,
            'promptVersion': FLOOR_DESIGN_PROMPT_VERSION,
            'negative_prompt': _floor_design_text(
                provider_page.get('negative_prompt') or result.get('negative_prompt'), 6000)
                or FLOOR_DESIGN_IMAGE_HARD_NEGATIVE,
            'preparedSpecification': page_spec,
        })
    return normalized


@app.route('/api/floor-design/analyze', methods=['POST'])
@require_auth
def api_analyze_floor_design_data():
    data = request.get_json(silent=True) or {}
    payload = _sanitize_floor_design_request(data)
    missing = _floor_design_missing_requirements(payload)
    if missing:
        return jsonify({'success': False, 'error': 'بيانات تصميم الطوابق غير مكتملة', 'error_code': 'FLOOR_DESIGN_DATA_INCOMPLETE', 'missingFields': missing}), 400
    system_prompt = (
        'أنت مستشار معماري وتحليل بيانات عقارية دقيق. أخرج JSON فقط. '
        'حلل البيانات المعطاة فقط، ولا تخترع قياسات أو اشتراطات. '
        'فرّق بين القيود النظامية الصارمة وتعليمات العميل والافتراضات. '
        'لا تغيّر عدد الأدوار أو توزيع المجموعات أو مكونات المشروع. '
        'انقل كل عنصر في data_conflicts إلى warnings صراحة مع القيمتين ومصدريهما، ولا تحسم التعارض أو تعدل أي قيمة.'
    )
    user_prompt = (
        'حلل مدخلات مشروع لإنشاء مخططات 2D مفاهيمية. ركز على ما سيؤثر في الرسم: '
        'أطوال الأضلاع وحدود الأرض والشوارع المحيطة والواجهات واتجاهاتها وجدول الاتجاهات كاملًا، '
        'نسبة التغطية والارتدادات والارتفاع وعدد الأدوار والقيود التنظيمية، '
        'المساحة المعتمدة ومسطحات البناء فوق الأرض والبدرومات وإجمالي المسطحات والمساحة المغطاة والمفتوحة وجدول المكونات كاملًا، ومجموعات الأدوار. '
        'أعد الشكل التالي فقط: {"summary":"","hard_constraints":[],"project_inputs":[],"group_notes":[],"warnings":[],"assumptions":[]}.\n\n'
        + _floor_design_json_prompt(payload)
    )
    try:
        response = call_openrouter_chat(system_prompt, user_prompt, temperature=None, max_tokens=8000,
                                        model=FLOOR_DESIGN_TEXT_MODEL, reasoning_effort=FLOOR_DESIGN_REASONING_EFFORT)
        analysis = _designer_json_response(extract_chat_content(response, 'FLOOR-DESIGN-ANALYSIS'))
        if not analysis:
            return jsonify({'success': False, 'error': 'تعذر قراءة التحليل', 'error_code': 'TEXT_PROVIDER_INVALID'}), 503
        return jsonify({'success': True, 'analysis': analysis, 'model': FLOOR_DESIGN_TEXT_MODEL})
    except Exception:
        app.logger.exception('Floor design analysis failed')
        return jsonify({'success': False, 'error': 'تعذر تحليل بيانات تصميم الطوابق', 'error_code': 'TEXT_PROVIDER_FAILED'}), 503


FLOOR_DESIGN_ANALYSIS_PATCH_KEYS = ('hard_constraints', 'project_inputs', 'group_notes', 'warnings', 'assumptions')


def _sanitize_floor_design_analysis_patch(raw_patch):
    if not isinstance(raw_patch, dict):
        return {}
    patch = {}
    if isinstance(raw_patch.get('summary'), str):
        patch['summary'] = raw_patch['summary'].strip()[:16000]
    for key in FLOOR_DESIGN_ANALYSIS_PATCH_KEYS:
        values = raw_patch.get(key)
        if not isinstance(values, list):
            continue
        clean_values = []
        for item in values[:100]:
            if isinstance(item, str):
                clean_values.append(item.strip()[:4000])
            elif isinstance(item, dict):
                clean_item = {}
                for nested_key in ('classification', 'item', 'label', 'name', 'value', 'description',
                                   'drawing_impact', 'impact', 'warning', 'note', 'floorNumbers', 'floorCount', 'components', 'source'):
                    nested_value = item.get(nested_key)
                    if nested_value in (None, ''):
                        continue
                    if isinstance(nested_value, (str, int, float, bool)):
                        clean_item[nested_key] = _floor_design_text(nested_value, 4000)
                    elif isinstance(nested_value, list):
                        clean_item[nested_key] = nested_value[:50]
                if clean_item:
                    clean_values.append(clean_item)
        patch[key] = clean_values
    return patch


def _sanitize_floor_design_group_patch(raw_patch):
    raw_operations = raw_patch.get('operations') if isinstance(raw_patch, dict) else raw_patch
    if not isinstance(raw_operations, list):
        return {'operations': [], 'requires_confirmation': False}
    operations = []
    requires_confirmation = bool(raw_patch.get('requires_confirmation')) if isinstance(raw_patch, dict) else False
    for raw in raw_operations[:50]:
        if not isinstance(raw, dict):
            continue
        operation = _floor_design_text(raw.get('op') or raw.get('operation'), 40).lower()
        if operation == 'create':
            group = raw.get('group') if isinstance(raw.get('group'), dict) else raw
            floor_numbers = sorted({int(number) for number in (group.get('floorNumbers') or group.get('floor_numbers') or [])
                                    if isinstance(number, (int, float)) and int(number) == number and 0 <= int(number) <= 500})
            if not floor_numbers:
                continue
            operations.append({
                'op': 'create',
                'group': {
                    'id': _floor_design_text(group.get('id'), 120),
                    'name': _floor_design_text(group.get('name'), 160) or 'مجموعة جديدة',
                    'floorNumbers': floor_numbers,
                    'type': _floor_design_text(group.get('type'), 80) or 'غير محدد',
                    'prompt': _floor_design_text(group.get('prompt') or group.get('description'), 12000),
                }
            })
        elif operation in ('assign', 'unassign'):
            floor_numbers = sorted({int(number) for number in (raw.get('floorNumbers') or raw.get('floor_numbers') or [])
                                    if isinstance(number, (int, float)) and int(number) == number and 0 <= int(number) <= 500})
            group_id = _floor_design_text(raw.get('groupId') or raw.get('group_id'), 120)
            if group_id and floor_numbers:
                operations.append({'op': operation, 'groupId': group_id, 'floorNumbers': floor_numbers})
        elif operation in ('rename', 'describe'):
            group_id = _floor_design_text(raw.get('groupId') or raw.get('group_id'), 120)
            if not group_id:
                continue
            operation_data = {'op': operation, 'groupId': group_id}
            if operation == 'rename':
                operation_data['name'] = _floor_design_text(raw.get('name'), 160)
            else:
                operation_data['prompt'] = _floor_design_text(raw.get('prompt') or raw.get('description'), 12000)
            operations.append(operation_data)
        elif operation in ('remove', 'delete'):
            if raw.get('confirmed') is True:
                group_id = _floor_design_text(raw.get('groupId') or raw.get('group_id'), 120)
                if group_id:
                    operations.append({'op': 'remove', 'groupId': group_id, 'confirmed': True})
            else:
                requires_confirmation = True
    return {'operations': operations, 'requires_confirmation': requires_confirmation}


@app.route('/api/floor-design/analysis-chat', methods=['POST'])
@require_auth
def api_floor_design_analysis_chat():
    data = request.get_json(silent=True) or {}
    message = _floor_design_text(data.get('message'), 4000)
    analysis = data.get('analysis') if isinstance(data.get('analysis'), dict) else {}
    if not message:
        return jsonify({'success': False, 'error': 'اكتب التعديل المطلوب على التحليل أولًا', 'error_code': 'ANALYSIS_MESSAGE_REQUIRED'}), 400
    if not analysis:
        return jsonify({'success': False, 'error': 'لا يوجد تحليل حالي لمراجعته', 'error_code': 'ANALYSIS_NOT_FOUND'}), 400
    payload = _sanitize_floor_design_request(data)
    floor_state = data.get('floorDesignState') if isinstance(data.get('floorDesignState'), dict) else {}
    history = floor_state.get('analysisChat') if isinstance(floor_state.get('analysisChat'), list) else []
    history = [
        {'role': 'assistant' if item.get('role') == 'assistant' else 'user', 'text': _floor_design_text(item.get('text'), 6000)}
        for item in history[-20:] if isinstance(item, dict) and item.get('text')
    ]
    selected_section = _floor_design_text(data.get('selectedAnalysisSection'), 80)
    system_prompt = (
        'أنت مساعد ذكي لمراجعة تحليل تصميم معماري وتنظيم مجموعات الأدوار. أعد JSON فقط بالشكل '
        '{"reply":"","analysis_patch":{"summary":"","hard_constraints":[],"project_inputs":[],"group_notes":[],"warnings":[],"assumptions":[]},'
        '"groups_patch":{"requires_confirmation":false,"operations":[]}}. '
        'افهم السياق الكامل للمحادثة والحالة الحالية قبل الرد، ولا ترد بأنك نفذت شيئًا إلا إذا أرسلت العملية داخل patch. '
        'يمكنك تعديل أقسام التحليل المسموحة، ويمكنك إنشاء أو إعادة تسمية أو وصف أو إسناد أو إلغاء إسناد مجموعات الأدوار. '
        'عند طلب الأدوار غير المنظمة احسبها من الحالة الحالية، ولا تنشئ مجموعة فارغة. '
        'عمليات المجموعات المسموحة هي create مع group، assign، unassign، rename، describe، وremove. '
        'كل عملية assign أو unassign يجب أن تحتوي groupId وfloorNumbers. create يجب أن يحتوي name وfloorNumbers وprompt. '
        'لا تكرر الدور في مجموعتين؛ عند إسناد دور أزله من المجموعة القديمة. لا تغير عدد الأدوار أو المكونات أو البيانات المالية. '
        'لا تنفذ حذف مجموعة إلا بعد تأكيد صريح؛ عند غيابه أعد requires_confirmation=true واسأل المستخدم. '
        'إذا كان الطلب غامضًا أعد patch فارغًا واسأل سؤالًا واضحًا بدل اختراع مجموعة أو أدوار.'
    )
    user_prompt = (
        'بيانات المشروع المختصرة:\n' + _floor_design_json_prompt(payload) +
        '\n\nالتحليل الحالي:\n' + _floor_design_json_prompt(analysis) +
        '\n\nمجموعات الأدوار الحالية بما فيها الأدوار غير المنظمة:\n' + _floor_design_json_prompt(payload.get('groups', [])) +
        '\n\nقسم التحليل المفتوح حاليًا:\n' + selected_section +
        '\n\nذاكرة المحادثة الأخيرة:\n' + _floor_design_json_prompt(history) +
        '\n\nطلب المستخدم الجديد:\n' + message
    )
    try:
        response = call_openrouter_chat(
            system_prompt, user_prompt, temperature=None, max_tokens=5000,
            model=FLOOR_DESIGN_TEXT_MODEL, reasoning_effort=FLOOR_DESIGN_REASONING_EFFORT
        )
        result = _designer_json_response(extract_chat_content(response, 'FLOOR-DESIGN-ANALYSIS-CHAT'))
        reply = _floor_design_text(result.get('reply'), 6000)
        if not reply:
            return jsonify({'success': False, 'error': 'تعذر قراءة رد مراجعة التحليل', 'error_code': 'ANALYSIS_CHAT_INVALID'}), 503
        analysis_patch = _sanitize_floor_design_analysis_patch(result.get('analysis_patch') or result.get('analysisPatch'))
        groups_patch = _sanitize_floor_design_group_patch(result.get('groups_patch') or result.get('groupsPatch'))
        return jsonify({
            'success': True,
            'reply': reply,
            'analysisPatch': analysis_patch,
            'groupsPatch': groups_patch,
            'needsConfirmation': groups_patch.get('requires_confirmation', False),
            'model': FLOOR_DESIGN_TEXT_MODEL,
        })
    except Exception:
        app.logger.exception('Floor design analysis chat failed')
        return jsonify({'success': False, 'error': 'تعذر مراجعة تحليل البيانات', 'error_code': 'ANALYSIS_CHAT_FAILED'}), 503


@app.route('/api/floor-design/prompt', methods=['POST'])
@require_auth
def api_generate_floor_design_prompt():
    data = request.get_json(silent=True) or {}
    payload = _sanitize_floor_design_request(data)
    analysis = data.get('analysis') if isinstance(data.get('analysis'), dict) else {}
    group_id = _floor_design_text(data.get('groupId'), 120)
    group = next((item for item in payload['groups'] if item['id'] == group_id), None)
    if not group:
        return jsonify({'success': False, 'error': 'مجموعة الأدوار غير موجودة', 'error_code': 'GROUP_NOT_FOUND'}), 404
    prepared = _floor_design_prepare(payload, group)
    preflight = _floor_design_preflight(payload, prepared, data)
    if not preflight['ok']:
        error_code = 'FLOOR_DESIGN_CONFLICTS_BLOCKED' if preflight['blockedItems'] else 'FLOOR_DESIGN_DATA_INCOMPLETE'
        return jsonify({'success': False, 'error': 'بيانات المخطط الهندسية غير جاهزة للتوليد',
                        'error_code': error_code, 'missingFields': preflight['missingItems'],
                        'missingItems': preflight['missingItems'], 'blockedItems': preflight['blockedItems'],
                        'preflight': preflight}), 409 if preflight['blockedItems'] else 400
    system_prompt = (
        'You write strict English image prompts for complete landscape architectural presentation pages. '
        'Return JSON only as {"pages":[{"pageType":"typical_floor","floorNumber":1,"prompt":"","negative_prompt":""}]}. '
        'Return exactly one item for every supplied Page Spec in the same order. The image model designs only and performs no arithmetic. '
        'Use every prepared value verbatim. A typical_floor page represents the complete supplied group range with one representative plan; do not reduce a multi-floor group to a floor 2-only design. A floor page with one floor represents that floor only. '
        'Keep the site boundary separate from the conceptual building floor plate. Include the 16:9 canvas, three-column proportions, visual style, plot, envelope status, north orientation, '
        'all sides, available angles and lengths, setbacks, streets, facades, entrances, cores, circulation, numbered plan references, matching English '
        'Table of Contents rows, complete Space Program, and pie labels, values, percentages, colors, and unit counts. '
        'When residentialLayout.required is true, explicitly describe repeated residential unit boundaries, common circulation, and cores for the representative floor or typical group; never collapse the floor into one component bubble. '
        'Never use unresolved instructions such as calculate, determine, approximately, or as appropriate. Never invent missing values. '
        'The nine attached reference images, when supplied, show the same fixed design across different floor types. Extract only their invariant layout, spacing, palette, line hierarchy, and information architecture; do not copy any reference content. '
        'The supplied references are style and layout guidance only. Never copy Acacia names, project content, values, dimensions, room names, or components. '
        'Permit English titles, labels, numbers, dimensions, tables, legends, and north notation. No logo and no watermark.'
    )
    reference_pack = _floor_design_reference_pack_data_uris()
    reference_images = [item['data_uri'] for item in reference_pack]
    reference_instruction = (
        f'Nine official visual references are attached ({len(reference_images)} available). They are the same design language across different floor types. '
        'Use their common fixed division exactly; do not infer project data from them and do not copy their text or dimensions.'
        if reference_images else
        'The official visual reference pack is unavailable for this request. Follow the supplied engineering specification and do not invent visual reference details.'
    )
    user_prompt = reference_instruction + '\n\n' + _floor_design_json_prompt({
        'analysis': analysis, 'projectData': payload, 'group': group,
        'pageSpecs': prepared['pages'], 'preparedEngineeringSpecification': prepared,
        'preflight': preflight,
    })
    chat_kwargs = {
        'temperature': None, 'max_tokens': 10000,
        'model': FLOOR_DESIGN_TEXT_MODEL,
        'reasoning_effort': FLOOR_DESIGN_REASONING_EFFORT,
        'response_format': {'type': 'json_object'},
    }
    if reference_images:
        chat_kwargs['image_references'] = reference_images
    try:
        response = call_openrouter_chat(system_prompt, user_prompt, **chat_kwargs)
        result = _designer_json_response(extract_chat_content(response, 'FLOOR-DESIGN-PROMPT'))
        pages = _floor_design_normalize_prompt_pages(result, prepared, payload, group)
        first = pages[0]
        return jsonify({'success': True, 'pages': pages, 'prompt': first['prompt'],
                        'negativePrompt': first['negative_prompt'], 'preparedSpecification': prepared,
                        'preflight': preflight, 'model': FLOOR_DESIGN_TEXT_MODEL,
                        'referencePack': {'count': len(reference_pack),
                                         'files': [item['name'] for item in reference_pack],
                                         'imageGenerationReference': FLOOR_DESIGN_REFERENCE_FILE}})
    except Exception:
        app.logger.exception('Floor design prompt failed')
        return jsonify({'success': False, 'error': 'تعذر إنشاء Prompts لصفحات المجموعة', 'error_code': 'TEXT_PROVIDER_FAILED'}), 503


@app.route('/api/floor-design/generate', methods=['POST'])
@require_auth
def api_generate_floor_design_image():
    data = request.get_json(silent=True) or {}
    prompt = data.get('prompt')
    reference = data.get('referenceImage')
    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({'success': False, 'error': 'وصف التصميم مطلوب', 'error_code': 'PROMPT_REQUIRED'}), 400
    prompt = prompt.strip()
    if len(prompt) > 30000:
        return jsonify({'success': False, 'error': 'وصف التصميم يتجاوز الحد المسموح',
                        'error_code': 'PROMPT_TOO_LONG'}), 400
    approved_area = data.get('approvedFinancialArea')
    approved_floors = data.get('approvedFloorCount')
    try:
        valid_area = not isinstance(approved_area, bool) and float(approved_area) > 0
        valid_floors = not isinstance(approved_floors, bool) and int(approved_floors) == float(approved_floors) and int(approved_floors) > 0
    except (TypeError, ValueError):
        valid_area = False
        valid_floors = False
    if not valid_area or not valid_floors:
        return jsonify({
            'success': False,
            'error': 'المساحة المعتمدة والأدوار المعتمدة مطلوبان قبل توليد التصميم',
            'error_code': 'APPROVED_BUILD_INPUTS_REQUIRED',
            'missingFields': [key for key, valid in (('approved_financial_area', valid_area), ('approved_floor_count', valid_floors)) if not valid]
        }), 400
    if reference is not None:
        if not isinstance(reference, str) or len(reference) > 20 * 1024 * 1024:
            return jsonify({'success': False, 'error': 'الصورة المرجعية غير صالحة أو كبيرة جدًا', 'error_code': 'REFERENCE_INVALID'}), 400
        if not (reference.startswith('data:image/') or reference.startswith('/uploads/creative/')):
            return jsonify({'success': False, 'error': 'نوع الصورة المرجعية غير مسموح', 'error_code': 'REFERENCE_INVALID'}), 400
    system_reference = _floor_design_default_reference_data_uri()
    reference_for_generation = system_reference
    reference_mode = 'system_floor_plan_style' if system_reference else 'prompt_only_no_reference'
    if not system_reference:
        app.logger.warning('Floor design style reference is unavailable; continuing without the system reference')
    try:
        image, image_error = call_openrouter_image_generation(prompt, FLOOR_DESIGN_IMAGE_MODEL, reference_for_generation)
        if not image:
            messages = {
                'NO_API_KEY': 'مفتاح توليد الصور غير مُعدّ',
                'INSUFFICIENT_CREDITS': 'رصيد توليد الصور غير كافٍ',
                'RATE_LIMITED': 'تم تجاوز حد طلبات توليد الصور، أعد المحاولة لاحقًا',
                'IMAGE_PROVIDER_TIMEOUT': 'استغرق توليد الصورة وقتًا أطول من المتوقع',
            }
            return jsonify({'success': False, 'error': messages.get(image_error, 'تعذر توليد صورة التصميم'), 'error_code': image_error or 'IMAGE_FAILED'}), 503
        return jsonify({'success': True, 'image': persist_generated_image(image, g.tenant_id),
                        'model': FLOOR_DESIGN_IMAGE_MODEL, 'reference': reference_mode})
    except Exception:
        app.logger.exception('Floor design image generation failed')
        return jsonify({'success': False, 'error': 'حدث خطأ أثناء توليد صورة التصميم', 'error_code': 'IMAGE_FAILED'}), 503


@app.route('/api/get-image-prompts', methods=['POST'])
def api_get_image_prompts():
    """Use GLM 5.1 to generate hyper-realistic, project-tailored architectural prompts for cover and moodboard images."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    project_name = project_data.get('project_name') or project_data.get('projectName') or 'مشروع عقاري'
    project_type = project_data.get('project_type') or project_data.get('projectType') or 'سكني'
    location = project_data.get('location_address') or project_data.get('location') or 'المملكة العربية السعودية'
    try:
        count = max(1, min(20, int(data.get('count', 4))))
    except (TypeError, ValueError):
        count = 4

    formatted_inputs = []
    for k, v in project_data.items():
        if v and not str(k).startswith('_') and str(k) not in ('slides_data', 'plan'):
            formatted_inputs.append(f"- {k}: {v}")
    
    inputs_str = "\n".join(formatted_inputs) if formatted_inputs else f"- اسم المشروع: {project_name}\n- النوع: {project_type}\n- الموقع: {location}"

    sys_prompt = (
        "أنت خبير هندسي ومعماري ومصمم بصري محترف، متخصص في صياغة الأوصاف النصية (Image Prompts) "
        "فائقة الدقة والمطابقة لتصميم المشروع العقاري المدخل بنسبة 80% إلى 99%.\n"
        "المطلوب منك تحليل جميع بيانات ومعلومات المشروع المدخلة أدناه لإنشاء أوصاف عربية تفصيلية ومحترفة:\n"
        "1. cover_prompt: وصف تفصيلي للغلاف يصف الواجهة، المواد (مثل الحجر، الرخام، الزجاج)، الطوابق، الإضاءة، الشارع والمحيط الجغرافي الواقعي بدقة عالية.\n"
        "2. moodboard_prompts: قائمة بعدد المود بورد المطلوب تشمل لقطات واجهة رئيسية، منظور أيمن، منظور أيسر، لقطة جوية درون، وتفاصيل معمارية.\n"
        "يجب أن تعيد النتيجة بصيغة JSON حصرية فقط دون أي مقدمات أو شروحات:\n"
        '{\n  "cover_prompt": "...",\n  "moodboard_prompts": ["...", "..."]\n}'
    )

    user_msg = (
        f"بيانات ومواصفات المشروع الكاملة:\n"
        f"{inputs_str}\n"
        f"- عدد صور المود بورد المطلوبة: {count}\n\n"
        f"اكتب الأوصاف بدقة معمارية عالية جداً ومطابقة لواقع وتفاصيل هذا المشروع."
    )

    try:
        res = call_zai_chat(sys_prompt, user_msg, temperature=0.7, max_tokens=2500)
        if res and 'choices' in res and res['choices']:
            content = res['choices'][0]['message']['content'].strip()
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()
            
            parsed = json.loads(content)
            if 'cover_prompt' in parsed and 'moodboard_prompts' in parsed:
                moodboard_prompts = parsed['moodboard_prompts']
                while len(moodboard_prompts) < count:
                    moodboard_prompts.append(f"منظور معماري إضافي لمشروع {project_name} رقم {len(moodboard_prompts)+1}")
                return jsonify({
                    'success': True,
                    'cover_prompt': parsed['cover_prompt'],
                    'moodboard_prompts': moodboard_prompts[:count],
                    'engine': GLM_MODEL
                })
    except Exception as e:
        print(f"[IMAGE PROMPTS GLM ERROR] {e}. Falling back to rich template generator...")

    # Rich fallback generator incorporating all available fields
    arch_style = project_data.get('architectural_style') or project_data.get('style') or 'حديث وعصري'
    materials = project_data.get('materials') or project_data.get('finishes') or 'حجر فاخر، واجهات زجاجية، وألومنيوم'
    floors = project_data.get('floors_count') or project_data.get('floors') or ''
    floors_str = f"يتكون من {floors} أدوار، " if floors else ""
    desc = project_data.get('project_description') or project_data.get('description') or ''
    desc_str = f" التفاصيل: {desc}." if desc else ""

    cover_prompt = f"تصوير معماري احترافي فائق الواقعية لمشروع {project_name} ({project_type}) في {location}. المبنى {floors_str}بطراز {arch_style} واستخدام {materials}.{desc_str} إضاءة دافئة، سماء صافية، تصوير سينمائي عالي الجودة بدون نصوص."

    base_prompts = [
        f"لقطة رئيسية لواجهة مشروع {project_name} في {location}، مبنى {project_type} {floors_str}بطراز {arch_style} وإضاءة معماري مميزة",
        f"منظور جانبي أيمن لواجهة {project_name} يبرز التفاصيل المعمارية وخامات {materials}",
        f"منظور جانبي أيسر لمبنى {project_name} يوضح جماليات التصميم والفتحات المعمارية",
        f"لقطة جوية بارافيناميكية لمشروع {project_name} تظهر المبنى من الأعلى والمحيط العام في {location}",
        f"تفاصيل معمارية دقيقة للمدخل الرئيسي والبهو الخارجي لمشروع {project_name}",
        f"لقطة مسائية ليلية لمشروع {project_name} توضح إضاءة الواجهات الخارجية في وقت الغروب",
        f"تصميم داخلي فاخر لبهو الاستقبال والاستراحة في {project_name}",
        f"المساحات الخضراء والحدائق المحيطة بمبنى {project_name}"
    ]

    moodboard_prompts = base_prompts[:count]
    while len(moodboard_prompts) < count:
        moodboard_prompts.append(f"منظور معماري إضافي لمشروع {project_name} رقم {len(moodboard_prompts)+1}")

    return jsonify({
        'success': True,
        'cover_prompt': cover_prompt,
        'moodboard_prompts': moodboard_prompts,
        'engine': 'fallback'
    })


@app.route('/api/designer-generate', methods=['POST'])
@require_auth
def api_designer_generate():
    """Generate slides HTML: variable slide count in parallel (4 concurrent workers)."""
    project_data = clean_project_data(request.json.get('projectData', {}))
    outline = request.json.get('outline', [])
    images = request.json.get('images', {})
    images_info = _get_images_info(images)

    # Build system prompt ONCE — shared across all slides
    branding = db.get_branding(g.tenant_id) or {}
    dynamic_rules = build_design_rules(branding)
    system_prompt = build_system_prompt(project_data, images_info, dynamic_rules)
    min_s, max_s, default_count = resolve_slide_bounds(branding)
    if outline:
        slide_count = max(min_s, min(max_s, len(outline)))
    else:
        slide_count = max(min_s, min(default_count, max_s))
    print(f"\n[DESIGNER] Starting {slide_count}-slide parallel generation (4 workers)...")
    print(f"[DESIGNER] System prompt: {len(system_prompt)} chars (shared)")
    start_time = time.time()

    try:
        # Run slides in parallel with 4 concurrent workers
        results = [None] * slide_count
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_idx = {}
            for i in range(slide_count):
                slide_title = outline[i].get('title') if i < len(outline) else None
                future = executor.submit(generate_single_slide, system_prompt, i + 1, g.tenant_id, total=slide_count, title=slide_title)
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
                slide_title = outline[slide_num - 1].get('title') if slide_num - 1 < len(outline) else None
                results[slide_num - 1] = generate_single_slide(
                    system_prompt, slide_num, g.tenant_id, max_retries=1, total=slide_count, title=slide_title
                )

        elapsed = round(time.time() - start_time, 1)
        combined_html = '\n'.join(h for h in results if h).strip()
        combined_html = validate_html(combined_html, slide_count)
        total_slides = combined_html.count('class="slide"')
        print(f"[DESIGNER] Done in {elapsed}s — {total_slides} slides total")

        # Build dynamic fallback titles from the fallback plan, padded to slide_count
        fallback_slides = build_fallback_plan(branding).get('slides', [])
        DEFAULT_TITLES = [s.get('title', f'شريحة {i + 1}') for i, s in enumerate(fallback_slides)]
        if len(DEFAULT_TITLES) < slide_count:
            for i in range(len(DEFAULT_TITLES), slide_count):
                DEFAULT_TITLES.append(f'شريحة {i + 1}')

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
        
        return jsonify({'success': True, 'data': {'action': 'edit', 'html': html, 'response': 'تم تعديل الشريحة '}})
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
        # Bullet glyphs are stripped from the model's output; written as escapes so the source
        # itself stays free of icon characters.
        bullet_chars = '\u2022-\u25cf* '
        bullets = [line.strip().lstrip(bullet_chars) for line in content.split('\n') if line.strip() and len(line.strip()) > 3]
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
    
    draft_id = project_data.get('draft_id') or project_data.get('draftId') if isinstance(project_data, dict) else None
    db_maps = []
    if presentation_id:
        db_maps = db.get_map_images(tenant_id, presentation_id=presentation_id)
    elif draft_id:
        db_maps = db.get_map_images(tenant_id, draft_id=draft_id)
        
    for m in db_maps:
        placeholder = m.get('placeholder')
        path = m.get('file_path')
        if placeholder and path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            if placeholder not in map_placeholders:
                map_placeholders[placeholder] = f"/{rel_path}"
                
    # Missing maps remain placeholders. Map generation belongs to the explicit
    # map workflow, never to a chat/edit request.

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
    if not tenant_id:
        try:
            tenant_id = g.tenant_id
        except Exception:
            tenant_id = None

    rules = build_design_rules(branding)
    training_context = ''
    if tenant_id:
        try:
            training_context = db.get_training_context(tenant_id) or ''
        except Exception:
            training_context = ''
    training_note = (
        f"\n\n## قواعد الشركة الملزمة (من التدريب — التزم بها في التصميم)\n{training_context}"
        if training_context else ''
    )

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

    prompt = f"""{rules}{training_note}
أنت محرر شرائح. عدّل الشريحة التالية حسب الطلب، وأعد JSON فقط بالشكل:
{{"html":"<div class=\\"slide\\">...</div>","response":"رسالة عربية قصيرة"}}
حافظ على كل المحتوى المفيد والهوية البصرية. لا تستخدم روابط صور خارجية أو base64.
عنوان الشريحة: {title}
HTML الحالي:
{clean_html}
الطلب:
{instruction}"""

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
    training_context = db.get_training_context(g.tenant_id) or ''
    summary = [{'index': i + 1, 'title': s.get('title', '') if isinstance(s, dict) else ''} for i, s in enumerate(slides)]
    all_note = "\n تنبيه هام جداً: المستخدم طلب صراحة تعديل جميع الشرائح دون استثناء! يجب أن تعيد target='all' في الأداة edit_slides." if is_all_slides_request else ""
    training_note = f"\n\n## قواعد الشركة الملزمة (من التدريب — التزم بها في أي تصميم)\n{training_context}" if training_context else ""
    planner_prompt = f"""{build_design_rules(branding)}{training_note}
أنت وكيل تصميم عروض متميز ذكي يفهم كافة اللهجات العربية، المترادفات، الأرقام، وأوامر إضافة وتحديث الخرائط والتنسيقات.
حلل طلب المستخدم وخطط لتنفيذه على العرض.{all_note} أعد JSON فقط:
{{"response":"رسالة عربية تشرح ما ستفعله", "actions":[{{"tool":"edit_slides|generate_image|create_slide|chat_only", "params":{{}}}}]}}

الأدوات المتاحة:
- edit_slides: params={{"target":"current|all|indexes", "indexes":[1-based], "instruction":"التعديل المطلوبة"}}
- generate_image: params={{"prompt":"وصف الصورة", "slideIndex":1, "position":"background|right|left|inline"}}
- create_slide: params={{"title":"العنوان", "type":"content", "instruction":"محتوى الشريحة"}}
- regenerate_maps: params={{"maptype":"roadmap|satellite|hybrid|terrain"}} (استخدمها عند طلب التبديل إلى شوارع/مرور/قمر صناعي)

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
4. إذا طلب المستخدم تغيير نوع الخريطة (شوارع/مرور/قمر صناعي/roadmap/satellite) -> اختر tool="regenerate_maps".
5. إذا كان الطلب سؤالاً لا يتطلب تعديلاً -> اختر tool="chat_only".

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

            msg_lower = message.lower()
            if any(word in msg_lower for word in ('شوارع', 'مرور', 'roadmap', 'ملاحة', 'شوارع محيطة')):
                actions = [{'tool': 'regenerate_maps', 'params': {'maptype': 'roadmap'}}]
            elif any(word in msg_lower for word in ('قمر صناعي', 'satellite', 'فضائي')):
                actions = [{'tool': 'regenerate_maps', 'params': {'maptype': 'satellite'}}]
            elif any(word in msg_lower for word in ('صورة', 'صوره', 'image', 'توليد صورة')):
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
                image = persist_generated_image(call_image_api(prompt), tenant_id)
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
            elif tool in ('regenerate_maps', 'update_map_style', 'change_map_type'):
                maptype = params.get('maptype') or params.get('style') or 'roadmap'
                map_styles = {'overview': maptype, 'landmarks': maptype, 'access': maptype, 'catchment': maptype}
                project_data['map_styles'] = map_styles
                map_res = maps_service.generate_all_map_images(project_data, tenant_id, presentation_id=presentation_id, force=True, branding=branding)
                if map_res.get('placeholders'):
                    slides_json = json.dumps(slides, ensure_ascii=False)
                    for placeholder, ppath in map_res['placeholders'].items():
                        if ppath and os.path.exists(ppath):
                            rel_p = '/' + os.path.relpath(ppath, os.path.dirname(__file__)).replace('\\', '/')
                            ptype = placeholder.replace('##MAP_', '').replace('##STREET_VIEW_', 'streetview_').replace('##', '').lower()
                            pattern = r'/uploads/maps/[^/]+_[^/]+_' + ptype + r'_[^/]+\.png'
                            slides_json = re.sub(pattern, lambda m, rp=rel_p: rp, slides_json)
                    slides = json.loads(slides_json)
                executed.append({'tool': tool, 'status': 'success', 'maptype': maptype})
            else:
                executed.append({'tool': tool, 'status': 'skipped', 'message': 'أداة غير معروفة'})

        validation = _validate_workspace_data({'slidesData': slides})
        if not validation['valid']:
            return jsonify({'success': False, 'error': 'تم رفض التعديل لأن العرض يحتوي على شرائح غير صالحة', 'validation': validation}), 422
        if presentation_id:
            db.update_presentation(presentation_id, slides_data=slides, slide_count=len(slides), status='edited')
        response_text = plan.get('response') or 'تم تنفيذ طلبك على العرض بالكامل.'
        if assistant_messages:
            response_text += ' ' + ' '.join(dict.fromkeys(assistant_messages))
        return jsonify({'success': True, 'data': {'action': 'workspace_update', 'response': response_text, 'slidesData': slides, 'creativeImages': creative_images, 'actions': executed, 'validation': validation}})
    except Exception as exc:
        print(f'[DESIGNER-CHAT ERROR] {exc}')
        return jsonify({'success': False, 'error': str(exc)}), 500


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


@app.route('/api/branding/font.css', methods=['GET'])
@require_auth
def api_branding_font_css():
    """Return the tenant @font-face CSS so the preview matches the exported PDF.

    The rules are scoped to .slide only, so the site UI font is unaffected.
    """
    from design_templates import build_font_css
    branding = db.get_branding(g.tenant_id) or {}
    css, _family = build_font_css(branding, g.tenant_id, embed=False)
    response = app.response_class(css or '/* no tenant font */', mimetype='text/css')
    response.headers['Cache-Control'] = 'no-cache'
    return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INPUT FIELDS ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/fields', methods=['GET'])
@require_auth
def api_get_fields():
    """Get all input fields for the current tenant."""
    db.ensure_tenant_prebuilt_fields_active(g.tenant_id)
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

def _flatten_ai_fields(parsed):
    """Normalize an LLM response into a list of field/section dicts."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for k in ('fields', 'sections', 'suggestions', 'data', 'items'):
            if k in parsed:
                return parsed[k]
    return []


def _parse_ai_fields_json(text):
    """Extract the first JSON array (or object with fields/sections) from LLM text."""
    # Try code block first
    cb = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if cb:
        try:
            parsed = json.loads(cb.group(1).strip())
            flattened = _flatten_ai_fields(parsed)
            if flattened:
                return flattened
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
                            parsed = json.loads(text[start:i+1])
                            flattened = _flatten_ai_fields(parsed)
                            if flattened:
                                return flattened
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break
    # Fallback: whole text
    try:
        parsed = json.loads(text.strip())
        flattened = _flatten_ai_fields(parsed)
        if flattened:
            return flattened
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


@app.route('/api/ai-build-fields', methods=['POST'])
@require_permission('custom_fields')
def api_ai_build_fields():
    """
    AI suggests input fields and auto-creates them in DB (with sections).
    Input: { description: '...' }
    Output: { created: [...], errors: [] }
    """
    data = request.json or {}
    description = (data.get('description') or '').strip()
    if not description:
        return jsonify({'error': 'description is required'}), 400

    existing = db.get_fields(g.tenant_id, active_only=False)
    existing_keys = [f['field_key'] for f in existing]
    existing_labels = {f['field_label'].strip().lower() for f in existing}
    training_context = db.get_training_context(g.tenant_id) or ''
    section_keys = {s['key'] for s in db.get_all_sections(g.tenant_id)}

    system_prompt = """أنت مساعد ذكي لمنصة توليد عروض تقديمية عقارية. مهمتك اقتراح وبناء حقول إدخال (input fields) مناسبة لمشروع عقاري أو شركة معيّنة.

أعد الرد كـ JSON array فقط. كل عنصر يمثل قسماً أو حقل إدخال واحد."""

    user_prompt = f"""ابنِ حقول إدخال مناسبة للوصف التالي:

{description}

بيانات التدريب الخاصة بالشركة:
{training_context[:2000] if training_context else 'لا يوجد تدريب خاص بالشركة بعد.'}

الحقول الموجودة حالياً (لا تكررها): {', '.join(existing_keys) if existing_keys else 'لا يوجد حقول'}

الأنواع المسموح بها فقط: text, textarea, number, select, date, image.

المخرجات المطلوبة: JSON array فقط. كل عنصر بهذه المفاتيح:
- sectionKey: مفتاح القسم (snake_case). استخدم قسماً منطقيًا مثل: basic, location, financial, features, swot, marketing, timeline, compliance.
- sectionLabel: اسم القسم بالعربي (إذا كان القسم جديدًا).
- fieldKey: مفتاح إنجليزي صغير بدون مسافات (snake_case).
- fieldLabel: اسم الحقل بالعربي.
- fieldType: أحد الأنواع المسموح بها.
- fieldOptions: array من strings (إذا كان fieldType = select)، وإلا null.
- isRequired: true/false.
- placeholder: نص توضيحي داخل الحقل (اختياري).
- defaultValue: قيمة افتراضية (اختياري).
- aiHint: توجيه للـ AI عند توليد الشرائح (اختياري).

قواعد:
- لا تُرجع أكثر من 12 حقل (لضمان جودة الرد).
- اجعل الرد مدمجاً: لا تكرر الوصف الطويل، واستخدم قيم قصيرة.
- fieldKey يجب أن يكون فريداً وsnake_case.
- إذا كان القسم غير موجود في الأقسام المعروفة، سيتم إنشاؤه تلقائياً باستخدام sectionLabel.
"""

    try:
        response = call_zai_chat(system_prompt, user_prompt, temperature=0.7, max_tokens=4000)
        content = extract_chat_content(response, "AI-BUILD-FIELDS")
        suggestions = _parse_ai_fields_json(content)

        valid_types = {'text', 'textarea', 'number', 'select', 'date', 'image'}
        created = []
        errors = []
        for s in suggestions:
            if not isinstance(s, dict):
                continue
            # Expand a section that contains a nested 'fields' list.
            nested = s.get('fields') if isinstance(s.get('fields'), list) else None
            items = nested if nested else [s]
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = re.sub(r'[^a-z0-9_]', '_', (item.get('fieldKey') or item.get('field_key') or '').strip().lower()).strip('_')
                label = (item.get('fieldLabel') or item.get('field_label') or key).strip()
                if not key or not label or key in existing_keys or label.lower() in existing_labels:
                    continue
                ftype = item.get('fieldType') or item.get('field_type') or 'text'
                if ftype not in valid_types:
                    ftype = 'text'
                section = (item.get('sectionKey') or item.get('section_key') or 'general').strip().lower()
                section_label = (item.get('sectionLabel') or item.get('section_label') or section).strip()
                if section not in section_keys and section_label:
                    try:
                        db.add_custom_section(g.tenant_id, section, section_label)
                        section_keys.add(section)
                    except Exception as se:
                        print(f"[AI-BUILD-FIELDS] section creation failed: {se}")
                        section = 'general'
                opts = item.get('fieldOptions') if isinstance(item.get('fieldOptions'), list) else (item.get('field_options') if isinstance(item.get('field_options'), list) else None)
                try:
                    field_id = db.add_custom_field(
                        g.tenant_id, key, label, ftype,
                        field_options=opts,
                        is_required=bool(item.get('isRequired') or item.get('is_required')),
                        placeholder=str(item.get('placeholder') or '').strip() or None,
                        default_value=str(item.get('defaultValue') or item.get('default_value') or '').strip() or None,
                        ai_hint=str(item.get('aiHint') or item.get('ai_hint') or '').strip() or None,
                        section_key=section
                    )
                    created.append({'id': field_id, 'field_key': key, 'field_label': label, 'section_key': section})
                    existing_keys.append(key)
                    existing_labels.add(label.lower())
                except Exception as fe:
                    print(f"[AI-BUILD-FIELDS] field creation failed: {fe}")
                    errors.append(f"{label}: {fe}")

        return jsonify({'success': True, 'created': created, 'errors': errors, 'count': len(created)})
    except Exception as e:
        print(f"[AI-BUILD-FIELDS ERROR] {e}")
        return jsonify({'error': str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SLIDE PLAN & GENERATION ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from slide_engine import (
    build_slide_plan_prompt, parse_slide_plan, validate_slide_plan,
    generate_all_slides, extract_html_from_glm, CONTENT_DISTRIBUTION_RULES,
    resolve_slide_bounds, build_fallback_plan, _suggest_design_style
)


def _ensure_required_location_slides(plan, project_data):
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    slides = plan['slides']
    existing_types = {slide.get('type') for slide in slides if isinstance(slide, dict)}
    required = []
    if project_data.get('location_lat') and project_data.get('location_lng'):
        required.append({
            'title': 'الموقع الاستراتيجي والإحداثيات',
            'type': 'site_specs',
            'design_style': 'table',
            'requires_image': False,
            'content_density': 'medium',
            'bullets': [],
            'content_source': 'location_detail',
        })
        for slide_type, title, source in (
            ('map_overview', 'خريطة الأرض والموقع', 'location_polygon'),
            ('map_access', 'خريطة الطرق الرئيسية', 'main_roads'),
            ('map_catchment', 'خريطة المنطقة ونطاق التأثير', 'catchment_areas'),
            ('map_landmarks', 'خريطة المعالم القريبة', 'nearby_landmarks'),
        ):
            if project_data.get(source) or slide_type == 'map_overview':
                required.append({
                    'title': title,
                    'type': slide_type,
                    'design_style': 'map',
                    'requires_image': True,
                    'content_density': 'medium',
                    'bullets': [],
                    'content_source': source,
                })
        required.append({
            'title': 'تحليل AI للموقع',
            'type': 'content',
            'design_style': 'text',
            'requires_image': False,
            'content_density': 'medium',
            'bullets': ['طبيعة الموقع وموقعه الاستراتيجي', 'الاتصال بالطرق والمعالم المحيطة', 'المزايا المستندة إلى بيانات الموقع'],
            'content_source': 'site_analysis',
        })
    if not required:
        return plan
    insert_at = 2 if len(slides) >= 2 else len(slides)
    for item in required:
        if item['type'] in existing_types:
            continue
        slides.insert(insert_at, item)
        insert_at += 1
        existing_types.add(item['type'])
    plan['slides'] = slides
    plan['proposed_count'] = len(slides)
    return plan


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
    slide_count_locked = bool(branding.get('lock_slide_count'))
    configured_min, configured_max, locked_count = resolve_slide_bounds(branding)

    effective_max_slides = max(1, configured_max)
    effective_min_slides = min(configured_min, effective_max_slides)

    # A locked slide count outranks any hint found in the training context.
    if not slide_count_locked:
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
    if slide_count_locked:
        effective_branding['default_slide_count'] = locked_count
    elif effective_branding.get('default_slide_count', 0) > effective_max_slides:
        effective_branding['default_slide_count'] = effective_max_slides

    prompt = build_slide_plan_prompt(project_data, effective_branding)
    if training_context:
        prompt = f"## بيانات خاصة بالشركة والتزام بحد الشرائح\nتنبيه هام جداً: التزم بحد الشرائح لهذه الشركة ({effective_min_slides} إلى {effective_max_slides} شريحة كحد أقصى).\n{training_context}\n\n---\n\n{prompt}"

    plan = None
    last_error = None
    max_attempts = 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = call_zai_chat_parallel(
                "أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية.",
                prompt,
                max_tokens=4000,
                attempts=1,
                timeout=20
            )
            content = extract_chat_content(response, "SLIDE-PLAN")
            plan = parse_slide_plan(content, effective_branding, project_data)
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

    plan = _ensure_required_location_slides(plan, project_data)

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

    if not address and not maps_link:
        return jsonify({'error': 'رابط Google Maps مطلوب لتحديد موقع المشروع'}), 400

    query = maps_link or address
    if not query.startswith('http'):
        return jsonify({'error': 'موقع المشروع يجب أن يكون رابط Google Maps'}), 400

    if query.startswith('http'):
        coords = maps_service.extract_coords_from_maps_link(query)
        if coords:
            print(f"[MAPS LINK] Extracted coords from link: {coords}")
            return jsonify({
                'success': True,
                'lat': coords['lat'],
                'lng': coords['lng'],
                'formatted_address': address if (address and not address.startswith('http')) else 'تم الاستخراج من رابط خرائط جوجل',
                'source': 'maps_link'
            })

    return jsonify({'success': False, 'error': 'رابط Google Maps غير صالح أو لا يحتوي على إحداثيات'})


@app.route('/api/debug-osm-polygon', methods=['GET'])
@require_auth
def api_debug_osm_polygon():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat and lng are required'}), 400
    radius = int(request.args.get('radius', 400))
    maps_service._osm_polygon_cache.clear()
    coords = maps_service._fetch_osm_polygon(lat, lng, radius_m=radius)
    if not coords:
        return jsonify({'found': False, 'lat': lat, 'lng': lng, 'radius_m': radius})
    return jsonify({
        'found': True,
        'points': len(coords),
        'area_sqm': round(maps_service._approx_polygon_area_sqm(coords)),
        'coords': coords,
    })


@app.route('/api/nearby-landmarks', methods=['POST'])
@require_auth
def api_nearby_landmarks():
    """Get nearby landmarks for given coordinates."""
    data = request.json or {}
    lat = data.get('lat')
    lng = data.get('lng')
    radius = data.get('radius', 20000)
    if lat is None or lng is None:
        return jsonify({'error': 'lat and lng are required'}), 400
    result = maps_service.get_nearby_landmarks(float(lat), float(lng), int(radius), max_results=int(data.get('maxResults', 20)), include_all=True)
    status = 502 if result.get('error') and not result.get('success') else 200
    return jsonify(result), status


@app.route('/api/preview-map-data', methods=['POST'])
@require_auth
def api_preview_map_data():
    """Preview calculated landmarks, drive matrix times, distances, and catchment zones before generation."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))

    lat = maps_service._extract_coordinate(
        project_data.get('location_lat') or project_data.get('locationLat') or
        project_data.get('latitude') or project_data.get('lat')
    )
    lng = maps_service._extract_coordinate(
        project_data.get('location_lng') or project_data.get('locationLng') or
        project_data.get('longitude') or project_data.get('lng')
    )

    if lat is None or lng is None:
        address = project_data.get('location_address') or project_data.get('location', '')
        if address and not address.startswith('http'):
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id)
            if geo.get('success'):
                lat = geo['lat']
                lng = geo['lng']

    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'لم يتم العثور على إحداثيات للموقع'}), 400

    landmark_radius_m = 20000
    selected_landmarks = data.get('selectedLandmarks')
    custom_text = project_data.get('nearby_landmarks') or project_data.get('landmarks_text')
    landmarks = selected_landmarks if isinstance(selected_landmarks, list) else (
        maps_service._parse_landmarks_text(custom_text) if isinstance(custom_text, str) else (custom_text or [])
    )
    landmarks_error = None
    landmarks_warning = None

    if not landmarks:
        places = maps_service.get_nearby_landmarks(lat, lng, radius=landmark_radius_m, max_results=20, include_all=True)
        if places.get('success'):
            landmarks = places['landmarks']
            if not landmarks:
                landmarks_warning = 'لم تُرجع Google Places أي معالم ضمن نطاق 20 كم من الموقع'
        else:
            landmarks_error = places.get('error') or 'تعذر جلب المعالم من Google Places'

    location_context = project_data.get('location_detail') or project_data.get('location_address') or project_data.get('location', '')
    for lm in landmarks:
        if lm.get('lat') is None or lm.get('lng') is None:
            query = f"{lm['name']}, {location_context}" if location_context else lm['name']
            geo = maps_service.geocode_address(query, tenant_id=g.tenant_id)
            if geo.get('success'):
                lm['lat'] = geo['lat']
                lm['lng'] = geo['lng']

    filtered_landmarks = []
    for lm in landmarks:
        if lm.get('lat') is None or lm.get('lng') is None:
            lm['location_status'] = 'unresolved'
            filtered_landmarks.append(lm)
            continue
        dist_m = maps_service._distance_meters(lat, lng, lm['lat'], lm['lng'])
        if dist_m < 50 or dist_m > landmark_radius_m:
            continue
        lm['distance_meters'] = round(dist_m)
        filtered_landmarks.append(lm)

    landmarks = sorted(filtered_landmarks, key=lambda item: item.get('distance_meters', float('inf')))

    geocoded = [lm for lm in landmarks if lm.get('lat') is not None and lm.get('lng') is not None]
    matrix = []
    if data.get('calculateDriving') and geocoded:
        matrix = maps_service.get_drive_matrix((lat, lng), geocoded)
        for i, lm in enumerate(geocoded):
            if i < len(matrix) and matrix[i]:
                entry = matrix[i]
                lm['duration_minutes'] = entry.get('duration_min')
                lm['distance_km'] = entry.get('distance_km')
                lm['distance_text'] = f"{entry.get('distance_km')} كم" if entry.get('distance_km') else None

    catchment_text = project_data.get('catchment_areas') or project_data.get('catchment_zones')
    zones = maps_service._parse_catchment_zones(catchment_text) if isinstance(catchment_text, str) else catchment_text

    if landmarks_error:
        return jsonify({
            'success': False,
            'error': landmarks_error,
            'error_code': 'NEARBY_LANDMARKS_UNAVAILABLE',
            'lat': lat,
            'lng': lng,
            'landmarks': [],
        }), 503

    return jsonify({
        'success': True,
        'lat': lat,
        'lng': lng,
        'landmarks': landmarks,
        'landmarks_matrix': matrix or landmarks,
        'catchment_zones': zones,
        'warning': landmarks_warning,
    })


def _map_image_point_to_coords(x, y, width, height, center_lat, center_lng, zoom, scale=2):
    """Convert normalized image coordinates to WGS84 using Web Mercator."""
    world = 256 * (2 ** zoom) * scale
    center_x = (center_lng + 180.0) / 360.0 * world
    center_lat_rad = math.radians(center_lat)
    center_y = (1.0 - math.log(math.tan(math.pi / 4.0 + center_lat_rad / 2.0)) / math.pi) / 2.0 * world
    target_x = center_x + (float(x) - 0.5) * width
    target_y = center_y + (float(y) - 0.5) * height
    lng = target_x / world * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * target_y / world))))
    return lat, lng


def _estimate_site_polygon_from_satellite(image_path, center_lat, center_lng, zoom):
    """Ask the vision model for a conservative building-only polygon estimate."""
    if not OPENROUTER_KEY or not image_path or not os.path.isfile(image_path):
        return None
    try:
        from reference_analyzer import encode_image_to_base64
        from PIL import Image
        image_uri = encode_image_to_base64(image_path)
        prompt = (
            'Analyze this satellite map image. The target site is at the exact image center. '
            'Identify only the footprint of the building or compound directly at the center; '
            'do not select roads, highways, interchanges, districts, empty land, airport areas, '
            'or any nearby polygon. Return JSON only: '
            '{"confidence":0.0,"points":[{"x":0.0,"y":0.0}]} where x and y are normalized '
            'image coordinates between 0 and 1. Return an empty points array if no building footprint '
            'can be identified with confidence >= 0.65.'
        )
        response = requests.post(
            f'{OPENROUTER_BASE}/chat/completions',
            headers={
                'Authorization': f'Bearer {OPENROUTER_KEY}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://github.com',
                'X-Title': 'Real Estate Proposal Generator - Site Boundary',
            },
            json={
                'model': IMAGE_MODEL,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': image_uri}},
                ]}],
                'modalities': ['text'],
                'max_tokens': 1200,
            },
            timeout=90,
        )
        payload = response.json()
        content = payload.get('choices', [{}])[0].get('message', {}).get('content', '')
        if isinstance(content, list):
            content = ' '.join(str(part.get('text', '')) if isinstance(part, dict) else str(part) for part in content)
        match = re.search(r'\{[\s\S]*\}', content or '')
        if not match:
            return None
        result = json.loads(match.group())
        confidence = float(result.get('confidence', 0) or 0)
        raw_points = result.get('points') or []
        if confidence < 0.65 or len(raw_points) < 3 or len(raw_points) > 40:
            return None
        with Image.open(image_path) as image:
            width, height = image.size
        normalized = []
        for point in raw_points:
            if not isinstance(point, dict):
                return None
            x, y = float(point.get('x')), float(point.get('y'))
            if not (0 <= x <= 1 and 0 <= y <= 1):
                return None
            normalized.append(_map_image_point_to_coords(x, y, width, height, center_lat, center_lng, zoom))
        if not maps_service._point_in_polygon(center_lat, center_lng, normalized):
            return None
        area = maps_service._approx_polygon_area_sqm(normalized)
        if area < 20 or area > 100000:
            return None
        return normalized
    except Exception as error:
        print(f'[SITE BOUNDARY VISION] {error}')
        return None


def _collect_site_fields(project_data, tenant_id, lat, lng):
    """Gather site fields (landmarks, roads, population, polygon) from Google/BigQuery data.

    Does not generate map images.  Used by analyze-site and site-analysis so they
    share the same data sources.
    """

    def landmark_lines(items, matrix=None):
        matrix = matrix or []
        lines = []
        for index, item in enumerate(items or []):
            name = item.get('name') or item.get('displayName') or ''
            if not name:
                continue
            drive = matrix[index] if index < len(matrix) and isinstance(matrix[index], dict) else {}
            distance = drive.get('distance_text') or item.get('distance_text')
            duration = drive.get('duration_min') or item.get('duration_minutes')
            category = item.get('category')
            details = []
            if category:
                details.append(str(category))
            if distance:
                details.append(str(distance))
            if duration:
                details.append(f'{duration} دقيقة')
            lines.append(f"{name} - {' - '.join(details)}" if details else name)
        return '\n'.join(lines)

    def road_lines(items):
        lines = []
        for item in items or []:
            name = item.get('name') or 'طريق وصول'
            distance = item.get('distance_text')
            duration = item.get('duration_minutes') or item.get('duration_min')
            details = [value for value in (distance, f'{duration} دقيقة' if duration else None) if value]
            lines.append(f"{name} - {' - '.join(details)}" if details else name)
        return '\n'.join(lines)

    def enrich_road_metrics(items):
        if not items or all(item.get('distance_text') and item.get('duration_minutes') for item in items):
            return
        matrix = maps_service.get_drive_matrix((lat, lng), items)
        for index, item in enumerate(items):
            if index >= len(matrix) or not isinstance(matrix[index], dict):
                continue
            entry = matrix[index]
            item['distance_text'] = entry.get('distance_text') or item.get('distance_text')
            item['distance_km'] = entry.get('distance_km') or item.get('distance_km')
            item['duration_min'] = entry.get('duration_min') or item.get('duration_min')
            item['duration_minutes'] = entry.get('duration_min') or item.get('duration_minutes')

    nearby = maps_service.get_nearby_landmarks(lat, lng, radius=20000, max_results=20, include_all=True)
    nearby_items = nearby.get('landmarks', []) if nearby.get('success') else []
    nearby_error = nearby.get('error') if not nearby.get('success') else None
    nearby_warning = 'لم تُرجع Google Places أي معالم ضمن نطاق 20 كم من الموقع' if nearby.get('success') and not nearby_items else None
    nearby_matrix = maps_service.get_drive_matrix((lat, lng), nearby_items) if nearby_items else []
    for index, item in enumerate(nearby_items):
        if index >= len(nearby_matrix) or not isinstance(nearby_matrix[index], dict):
            continue
        entry = nearby_matrix[index]
        item['distance_km'] = entry.get('distance_km') or item.get('distance_km')
        item['distance_text'] = entry.get('distance_text') or item.get('distance_text')
        item['duration_min'] = entry.get('duration_min') or item.get('duration_min')
        item['duration_minutes'] = entry.get('duration_min') or item.get('duration_minutes')

    curated_city = maps_service.detect_curated_city(lat, lng, tenant_id=tenant_id)
    city_error = None
    city_warning = None
    if curated_city:
        city_items = maps_service.get_curated_city_landmarks(lat=lat, lng=lng, city=curated_city, tenant_id=tenant_id)
    else:
        city = maps_service.get_nearby_landmarks(lat, lng, radius=5000, max_results=20, include_all=True)
        city_items = city.get('landmarks', []) if city.get('success') else []
        city_error = city.get('error') if not city.get('success') else None
        existing_city_names = {item.get('name', '').casefold() for item in city_items}
        city_items.extend(
            item for item in maps_service.get_nearest_category_landmarks(lat, lng, radius=20000, tenant_id=tenant_id)
            if item.get('name', '').casefold() not in existing_city_names
        )
    if not city_items and not city_error:
        city_warning = 'لم تُرجع Google Places أي معالم للمدينة ضمن النطاق المحدد'
    roads = maps_service.discover_nearby_roads(lat, lng, tenant_id=tenant_id, max_results=6)
    enrich_road_metrics(roads)

    polygon = None
    raw_polygon = project_data.get('location_polygon')
    if isinstance(raw_polygon, str):
        try:
            polygon = [
                (float(lat_value.strip()), float(lng_value.strip()))
                for point in raw_polygon.split(';') if ',' in point
                for lat_value, lng_value in [point.split(',', 1)]
            ]
            if len(polygon) < 3:
                polygon = None
        except (TypeError, ValueError):
            polygon = None
    if not polygon:
        polygon = maps_service._fetch_osm_polygon(lat, lng, radius_m=180)

    population = population_service.get_population_density(lat, lng)
    location_details = maps_service.reverse_geocode_location(lat, lng, tenant_id=tenant_id, language='en')
    fields = {
        'location_lat': lat,
        'location_detail': location_details.get('formatted_address', ''),
        'location_lng': lng,
        'nearby_landmarks': landmark_lines(nearby_items, nearby_matrix),
        'city_landmarks': landmark_lines(city_items),
    }
    if population.get('available'):
        fields['population_density'] = f"{population['value']} {population.get('unit', 'نسمة/كم²')}"
        fields['population_density_source'] = population.get('source')
    road_names = []
    for road in roads:
        name = road.get('name')
        if name and name not in road_names:
            road_names.append(name)
    if road_names:
        fields['main_roads'] = '\n'.join(road_names)

    secondary_roads = maps_service.discover_nearby_roads(
        lat, lng, tenant_id=tenant_id, max_results=4, lat_step=0.0006, lng_step=0.0008
    )
    secondary_names = []
    filtered_secondary_roads = []
    for road in secondary_roads:
        name = road.get('name')
        if name and name not in road_names and name not in secondary_names:
            secondary_names.append(name)
            filtered_secondary_roads.append(road)
    if filtered_secondary_roads:
        enrich_road_metrics(filtered_secondary_roads)
        fields['main_roads'] = '\n'.join(road_names)
        fields['secondary_roads'] = road_lines(filtered_secondary_roads)

    city_matrix = maps_service.get_drive_matrix((lat, lng), city_items) if city_items else []
    for index, item in enumerate(city_items):
        if index < len(city_matrix) and isinstance(city_matrix[index], dict):
            if city_matrix[index].get('duration_min') is not None:
                item['duration_minutes'] = city_matrix[index].get('duration_min')
            if city_matrix[index].get('distance_text'):
                item['distance_text'] = city_matrix[index].get('distance_text')
    fields['city_landmarks'] = landmark_lines(city_items, city_matrix)
    catchment_lines = []
    for item in city_items:
        name = item.get('name')
        duration = item.get('duration_minutes')
        if not name:
            continue
        parts = [name]
        if item.get('category'):
            parts.append(str(item['category']))
        if item.get('distance_text'):
            parts.append(str(item['distance_text']))
        if duration is not None:
            parts.append(f'{duration} دقائق')
        catchment_lines.append(' — '.join(parts))
    if catchment_lines:
        fields['catchment_areas'] = '\n'.join(catchment_lines)

    if polygon:
        fields['location_polygon'] = ';'.join(f'{point[0]:.6f},{point[1]:.6f}' for point in polygon)

    diagnostics = {
        'nearby_landmarks_error': nearby_error,
        'nearby_landmarks_warning': nearby_warning,
        'city_landmarks_error': city_error,
        'city_landmarks_warning': city_warning,
    }
    return fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics


@app.route('/api/analyze-site', methods=['POST'])
@require_permission('create_presentation')
def api_analyze_site():
    """Resolve and enrich site data; map image generation is opt-in only."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    branding = db.get_branding(g.tenant_id) or {}

    address = project_data.get('location_address') or project_data.get('location') or ''
    link = address if isinstance(address, str) and address.startswith('http') else (
        project_data.get('location_maps_link') or project_data.get('maps_link')
    )
    if not isinstance(link, str) or not link.startswith('http'):
        return jsonify({'success': False, 'error': 'موقع المشروع يجب أن يكون رابط Google Maps'}), 400
    coords = maps_service.extract_coords_from_maps_link(link)
    if coords:
        lat, lng = coords['lat'], coords['lng']
        source = 'maps_link'
    elif link:
        return jsonify({'success': False, 'error': 'تعذر استخراج الإحداثيات من رابط Google Maps'}), 400
    else:
        lat = maps_service._extract_coordinate(
            project_data.get('location_lat') or project_data.get('locationLat') or
            project_data.get('latitude') or project_data.get('lat')
        )
        lng = maps_service._extract_coordinate(
            project_data.get('location_lng') or project_data.get('locationLng') or
            project_data.get('longitude') or project_data.get('lng')
        )
        source = 'existing_coordinates'
        if (lat is None or lng is None) and address and not str(address).startswith('http'):
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id)
            if geo.get('success'):
                lat, lng = geo['lat'], geo['lng']
                source = 'geocoding'

    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'أدخل رابط Google Maps أو عنوان الموقع أولاً'}), 400

    fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics = _collect_site_fields(
        project_data, g.tenant_id, lat, lng
    )
    fields['location_polygon_source'] = (
        'manual' if project_data.get('location_polygon_source') == 'manual'
        else 'auto' if fields.get('location_polygon')
        else 'none'
    )

    analyzed_project = {
        **project_data,
        **fields,
        'location_lat': lat,
        'location_lng': lng,
        'calculate_landmark_driving': False,
        'enabled_maps': ['overview', 'landmarks', 'access', 'catchment'],
    }
    generate_maps = data.get('generateMaps') is True
    estimate_boundary = data.get('estimateBoundary') is True
    map_result = {'placeholders': {}, 'zooms': {}, 'error': None}
    estimated_polygon = None
    if generate_maps:
        map_result = maps_service.generate_all_map_images(
            analyzed_project,
            g.tenant_id,
            presentation_id=data.get('presentationId'),
            force=data.get('force', True) is not False,
            branding=branding,
        )
        if estimate_boundary and not polygon:
            overview_path = (
                map_result.get('placeholders', {}).get('##MAP_OVERVIEW##')
                or map_result.get('placeholders', {}).get('##MAP_OVERVIEW_SATELLITE##')
                or map_result.get('placeholders', {}).get('##MAP_OVERVIEW_ROADMAP##')
            )
            estimated_polygon = _estimate_site_polygon_from_satellite(
                overview_path,
                lat,
                lng,
                int((map_result.get('zooms') or {}).get('overview') or 17),
            ) if overview_path else None
            if estimated_polygon:
                polygon = estimated_polygon
                fields['location_polygon'] = ';'.join(f'{point[0]:.6f},{point[1]:.6f}' for point in polygon)
                analyzed_project = {**analyzed_project, 'location_polygon': fields['location_polygon']}
                map_result = maps_service.generate_all_map_images(
                    analyzed_project,
                    g.tenant_id,
                    presentation_id=data.get('presentationId'),
                    force=True,
                    branding=branding,
                )
    placeholders = {}
    for placeholder, path in map_result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = f'/{rel_path}'

    return jsonify({
        'success': True,
        'fields': fields,
        'mapPlaceholders': placeholders,
        'mapsDeferred': not generate_maps,
        'landmarks': nearby_items,
        'landmarksMatrix': nearby_matrix,
        'cityLandmarks': city_items,
        'roads': roads,
        'zooms': map_result.get('zooms', {}),
        'lat': lat,
        'lng': lng,
        'source': source,
        'boundary': {
            'status': 'verified_building' if polygon and not estimated_polygon else ('estimated_building' if estimated_polygon else 'needs_review'),
            'estimated': bool(estimated_polygon),
            'manual_edit_available': True,
        },
        'warning': map_result.get('error'),
        'landmarksWarning': diagnostics.get('nearby_landmarks_error') or diagnostics.get('nearby_landmarks_warning'),
        'cityLandmarksWarning': diagnostics.get('city_landmarks_error') or diagnostics.get('city_landmarks_warning'),
    })


@app.route('/api/site-analysis', methods=['POST'])
@require_permission('create_presentation')
def api_site_analysis():
    data = request.json or {}
    raw_project_data = clean_project_data(data.get('projectData', {}))
    analysis_keys = (
        'project_name', 'project_type', 'project_idea', 'description', 'project_description',
        'project_goal', 'project_stage', 'initial_features', 'initial_strengths',
        'project_features', 'investment_opportunities', 'target_audience', 'location_address',
        'location_maps_link', 'maps_link', 'location_detail', 'location_lat', 'location_lng',
        'main_roads', 'secondary_roads', 'nearby_landmarks', 'nearby_landmarks_data',
        'city_landmarks', 'catchment_areas', 'population_density', 'population_density_source',
        'land_area', 'built_area', 'building_system', 'infrastructure', 'location_polygon'
    )
    project_data = {
        key: raw_project_data.get(key)
        for key in analysis_keys
        if raw_project_data.get(key) not in (None, '', [], {})
    }
    if not project_data.get('location_lat') or not project_data.get('location_lng'):
        return jsonify({'success': False, 'error': 'بيانات الموقع والإحداثيات مطلوبة أولًا'}), 400

    lat = maps_service._extract_coordinate(project_data.get('location_lat'))
    lng = maps_service._extract_coordinate(project_data.get('location_lng'))
    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'بيانات الموقع والإحداثيات مطلوبة أولًا'}), 400

    enriched_fields = {}
    enrichment_diagnostics = {}
    needs_enrichment = any(
        project_data.get(key) in (None, '', [], {})
        for key in (
            'location_detail', 'main_roads', 'secondary_roads', 'nearby_landmarks',
            'nearby_landmarks_data', 'city_landmarks', 'catchment_areas', 'population_density',
            'location_polygon',
        )
    )
    filled_fields = {}
    if needs_enrichment:
        try:
            enrichment_result = _collect_site_fields(raw_project_data, g.tenant_id, lat, lng)
            enriched_fields, nearby_items, *_rest, enrichment_diagnostics = enrichment_result
            enrichment_diagnostics = enrichment_diagnostics or {}
            if not project_data.get('nearby_landmarks_data') and nearby_items:
                enriched_fields['nearby_landmarks_data'] = nearby_items
        except Exception as error:
            print(f'[SITE DATA ENRICHMENT ERROR] {error}')
            enriched_fields = {}

    for key in analysis_keys:
        if enriched_fields.get(key) not in (None, '', [], {}) and project_data.get(key) in (None, '', [], {}):
            project_data[key] = enriched_fields[key]
            filled_fields[key] = enriched_fields[key]

    prompt = f"""اكتب تحليلًا عربيًا احترافيًا ومفصلًا لموقع مشروع عقاري اعتمادًا على البيانات التالية فقط.

المطلوب:
- اكتب تحليلًا عربيًا مسترسلًا في فقرات مترابطة، ولا تختصره إلى ملخص سريع أو عبارات عامة.
- غطِّ جميع الفئات التالية الموجودة في البيانات ولا تتخطى أي فئة فيها بيانات.
- يجب أن يتضمن التحليل إشارة مختصرة إلى كل ما يلي متاح منه، بالترتيب التالي قدر الإمكان:
  1. نوع المشروع وفكرته ووصفه والهدف منه ومرحلته الحالية والجمهور المستهدف.
  2. المميزات الأولية ونقاط القوة وفرص الاستثمار المناسبة للمشروع.
  3. طبيعة الموقع وموقعه الاستراتيجي والعنوان التفصيلي والإحداثيات.
  4. الكثافة السكانية ومصدرها إن وجدت.
  5. البنية التحتية والخدمات العامة المتاحة.
  6. الطرق الرئيسية والثانوية وطبيعة الوصول.
  7. المعالم القريبة ومعالم المدينة، مع ذكر المسافات وأوقات القيادة كدليل لا كموضوع رئيسي.
  8. نطاق التأثير ومناطق الالتقاط إن وجدت.
- اربط كل فئة بصلاحية الموقع لنوع المشروع وفكرته وهدفه ومرحلته والجمهور المستهدف ومميزات المشروع وفرصه.
- اشرح العلاقة والاستنتاجات بالتفصيل دون تكرار نفس المعلومة.
- لا تخترع أي معلومة غير موجودة في البيانات.
- إذا كانت معلومة غير متوفرة، لا تذكرها أبدًا بدلًا من اختلاقها.
- لا تستخدم عناوين أو نقاط تعداد في النص النهائي؛ أعد تحليلًا عربيًا سلسًا جاهزًا للعرض.

بيانات المشروع والموقع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}"""
    system_prompt = 'أنت محلل مواقع عقارية دقيق. أخرج تحليلًا عربيًا سلسًا يغطي كل فئة متاحة من البيانات دون تخطي أي منها، ودون اختلاق معلومات غير موجودة.'
    try:
        try:
            response = call_zai_chat(
                system_prompt, prompt, max_tokens=SITE_ANALYSIS_MAX_TOKENS,
                reasoning_effort='max')
            analysis = extract_chat_content(response, 'SITE-ANALYSIS').strip()
        except Exception as primary_error:
            if not OPENROUTER_KEY:
                raise
            print(f'[SITE ANALYSIS PRIMARY ERROR] {primary_error}. Trying direct OpenRouter fallback...')
            fallback = call_openrouter_chat(
                system_prompt,
                prompt,
                temperature=None,
                max_tokens=SITE_ANALYSIS_MAX_TOKENS,
                model=LUNA_TEXT_MODEL
            )
            analysis = extract_chat_content(fallback, 'SITE-ANALYSIS-FALLBACK').strip()
        warnings = [value for value in (
            enrichment_diagnostics.get('nearby_landmarks_error'),
            enrichment_diagnostics.get('nearby_landmarks_warning'),
            enrichment_diagnostics.get('city_landmarks_error'),
            enrichment_diagnostics.get('city_landmarks_warning'),
        ) if value]
        return jsonify({
            'success': True,
            'analysis': analysis,
            'fields': filled_fields,
            'warnings': warnings,
        })
    except Exception as error:
        print(f'[SITE ANALYSIS AI ERROR] {error}')
        return jsonify({
            'success': False,
            'error': 'تعذر تشغيل خدمة تحليل AI للموقع: ' + str(error),
            'error_code': 'SITE_ANALYSIS_AI_UNAVAILABLE'
        }), 503


@app.route('/api/generate-map-image', methods=['POST'])
@require_auth
def api_generate_single_map_image():
    data = request.json or {}
    map_type = str(data.get('mapType') or '').strip().lower()
    if map_type not in {'overview', 'landmarks', 'access', 'catchment'}:
        return jsonify({'success': False, 'error': 'نوع خريطة غير صالح'}), 400
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = data.get('presentationId')
    draft_id = project_data.get('draftId') or project_data.get('draft_id')
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return jsonify({'success': False, 'error': 'معرّف العرض أو المسودة مطلوب'}), 400
    for image_type in (map_type, f'{map_type}_satellite', f'{map_type}_roadmap'):
        db.delete_map_images(g.tenant_id, presentation_id=effective_id, image_type=image_type)
    project_data['enabled_maps'] = [map_type]
    branding = db.get_branding(g.tenant_id) or {}
    result = maps_service.generate_all_map_images(
        project_data,
        g.tenant_id,
        presentation_id=presentation_id,
        draft_id=draft_id,
        force=False,
        branding=branding,
        highlight_site=data.get('highlightSite', True) is not False,
    )
    if result.get('error'):
        return jsonify({'success': False, 'error': result['error']}), 400
    placeholders = {}
    for placeholder, path in result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = '/' + rel_path
    return jsonify({'success': True, 'mapType': map_type, 'placeholders': placeholders, 'zooms': result.get('zooms', {})})


@app.route('/api/generate-map-images', methods=['POST'])
@require_auth
def api_generate_map_images():
    """Generate all map images for a project and return placeholders."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    project_data['enabled_maps'] = ['overview', 'landmarks', 'access', 'catchment']
    presentation_id = data.get('presentationId')
    force = bool(data.get('force'))
    highlight_site = data.get('highlightSite', True) is not False
    branding = db.get_branding(g.tenant_id) or {}
    result = maps_service.generate_all_map_images(
        project_data,
        g.tenant_id,
        presentation_id=presentation_id,
        force=force,
        branding=branding,
        highlight_site=highlight_site,
    )
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
        'landmarks_matrix': result.get('landmarks_matrix', []),
        'zooms': result.get('zooms', {}),
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

    req_data = request.json or {}
    stored_project_data = json.loads(pres['project_data']) if pres.get('project_data') else {}
    submitted_project_data = req_data.get('projectData')
    if isinstance(submitted_project_data, dict):
        project_data = {**stored_project_data, **clean_project_data(submitted_project_data)}
        existing_creative = project_data.get('tenantCreativeImages')
        if isinstance(existing_creative, dict):
            project_data['tenantCreativeImages'] = {
                **existing_creative,
                'map_placeholders': {},
                'map_zooms': {},
                'map_landmarks': [],
                'map_lat': None,
                'map_lng': None,
                'map_approvals': {},
                'maps_persisted': False,
                'maps_signature': None,
            }
    else:
        project_data = stored_project_data
    project_data['enabled_maps'] = ['overview', 'landmarks', 'access', 'catchment']
    branding = db.get_branding(g.tenant_id) or {}
    if req_data.get('map_styles'):
        project_data['map_styles'] = req_data['map_styles']
    result = maps_service.generate_all_map_images(project_data, g.tenant_id, presentation_id=pres_id, force=True, branding=branding)
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
                slides_json = re.sub(pattern, lambda m, rp=rel_path: rp, slides_json)
                updated = True
        if updated:
            slides_data = json.loads(slides_json)
            db.update_presentation(pres_id, project_data=project_data, slides_data=slides_data)
        else:
            db.update_presentation(pres_id, project_data=project_data)
    else:
        db.update_presentation(pres_id, project_data=project_data)

    return jsonify({
        'success': True,
        'placeholders': placeholders,
        'landmarks': result.get('landmarks', []),
        'landmarks_matrix': result.get('landmarks_matrix', []),
        'zooms': result.get('zooms', {}),
        'lat': result.get('lat'),
        'lng': result.get('lng'),
    })


@app.route('/api/generate-slide-single', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slide_single():
    """Generate a single slide by index. Returns one slide HTML."""
    from slide_engine import generate_single_slide, build_design_rules, finalize_slide_html
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

    # Map generation is explicit. A single-slide request may reuse supplied
    # persisted assets, but it must never trigger a hidden Google/OSM call.
    map_placeholders = {}
    has_maps = isinstance(images, dict) and isinstance(images.get('map_placeholders'), dict) and bool(images.get('map_placeholders'))
    if has_maps:
        map_placeholders = {key: value for key, value in images.get('map_placeholders', {}).items() if value}
        resolved_location = project_data.get('_resolved_location')
        if not isinstance(resolved_location, dict):
            resolved_location = {}
        if project_data.get('location_lat') and project_data.get('location_lng'):
            project_data['_resolved_location'] = {
                'lat': resolved_location.get('lat') or project_data.get('location_lat'),
                'lng': resolved_location.get('lng') or project_data.get('location_lng'),
            }

    images_info = _get_images_info(images)
    training_context = db.get_training_context(g.tenant_id)

    design_rules = build_design_rules(branding)
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)
    if len(project_json) > 4000:
        project_json = project_json[:4000] + '\n... [تم اختصار البيانات]'

    landmarks_matrix = project_data.get('landmarks_matrix')
    landmarks_note = ''
    if landmarks_matrix:
        landmarks_note = (
            " إرشادات هامة لعرض المعالم:\n"
            "يجب عرض المسافة والوقت معاً لكل معلم بدون استثناء بالصيغة التاعية: (اسم المعلم - المسافة بالكم - الوقت بالدقائق)، مثل: 'ميدان السارية (1.5 كم - 5 دقائق)'.\n"
            "استخدم البيانات الموثقة التالية كما هي وممنوع تعديل الأرقام:\n" +
            json.dumps(landmarks_matrix, ensure_ascii=False, indent=2)
        )

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
-  ممنوع base64 أو روابط صور خارجية
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
        }), 503

    html = finalize_slide_html(
        html,
        slide.get('type', 'content'),
        project_data,
        branding,
        creative_images=images,
        map_placeholders=map_placeholders,
        tenant_id=g.tenant_id,
        slide_num=slide_index + 1,
        slide_title=slide.get('title', f'شريحة {slide_index + 1}'),
        total_slides=total,
    )

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

    # Map generation is explicit. Reuse only placeholders already supplied by the
    # caller or persisted by a previous, user-triggered map generation.
    map_placeholders = {}
    if isinstance(images, dict):
        supplied_placeholders = images.get('map_placeholders')
        if isinstance(supplied_placeholders, dict):
            map_placeholders = {key: value for key, value in supplied_placeholders.items() if value}
    elif isinstance(images, list):
        images = {'cover': images[0] if images else None, 'moodboard': []}

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


def _merge_persisted_map_assets(project_data, tenant_id, presentation_id=None, draft_id=None):
    if not isinstance(project_data, dict):
        return project_data or {}
    records = db.get_map_images(tenant_id, presentation_id=presentation_id, draft_id=draft_id)
    if not records:
        return project_data
    creative = project_data.get('tenantCreativeImages')
    if not isinstance(creative, dict):
        creative = {}
    placeholders = {}
    map_zooms = {}
    map_highlight_site = None
    seen_types = set()
    seen_placeholders = set()
    for record in records:
        path = record.get('file_path')
        placeholder = record.get('placeholder')
        image_type = record.get('image_type') or ''
        if not path or not placeholder or not os.path.exists(path):
            continue
        try:
            metadata = json.loads(record.get('metadata_json') or '{}')
        except (TypeError, ValueError):
            metadata = {}
        if metadata.get('map_highlight_version') != maps_service.MAP_HIGHLIGHT_RENDER_VERSION:
            continue
        if image_type in seen_types or placeholder in seen_placeholders:
            continue
        seen_types.add(image_type)
        seen_placeholders.add(placeholder)
        try:
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
        except ValueError:
            rel_path = 'uploads/maps/' + os.path.basename(path)
        placeholders[placeholder] = '/' + rel_path
        if creative.get('map_lat') is None and metadata.get('lat') is not None:
            creative['map_lat'] = metadata['lat']
        if creative.get('map_lng') is None and metadata.get('lng') is not None:
            creative['map_lng'] = metadata['lng']
        if metadata.get('zoom') is not None:
            base_type = image_type
            if base_type.endswith('_satellite') or base_type.endswith('_roadmap'):
                base_type = base_type.rsplit('_', 1)[0]
            map_zooms.setdefault(base_type, metadata['zoom'])
        if metadata.get('landmarks_matrix') and not creative.get('map_landmarks'):
            creative['map_landmarks'] = metadata['landmarks_matrix']
        if map_highlight_site is None and metadata.get('highlight_site') is not None:
            map_highlight_site = bool(metadata.get('highlight_site'))
    creative['map_placeholders'] = placeholders
    creative['maps_persisted'] = bool(placeholders)
    if map_highlight_site is not None:
        creative['map_highlight_site'] = map_highlight_site
    if map_zooms:
        creative['map_zooms'] = map_zooms
    project_data['tenantCreativeImages'] = creative
    return project_data


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
    project_data = normalize_presentation_assets(data.get('projectData', {}), g.tenant_id)
    slides_data = normalize_presentation_assets(data.get('slidesData', []), g.tenant_id)
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
    pres['projectData'] = _merge_persisted_map_assets(pres['projectData'], g.tenant_id, presentation_id=pres_id)
    slides = json.loads(pres['slides_data']) if pres.get('slides_data') else []
    branding = db.get_branding(g.tenant_id) or {}
    for s in slides:
        if isinstance(s, dict) and 'html' in s and isinstance(s['html'], str):
            s['html'] = resolve_logo_in_html(s['html'], g.tenant_id, _branding_cache=branding)
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
            updates[db_key] = normalize_presentation_assets(data[k], g.tenant_id) if k in {'projectData', 'slidesData'} else data[k]

    # Save version snapshot before update if slides_data is changing
    if 'slides_data' in updates:
        import json as _json
        current_slides = _json.loads(pres['slides_data']) if pres.get('slides_data') else []
        db.save_presentation_version(pres_id, g.user_id, g.user_name or 'System', current_slides, action='edit')
        # Build detailed log entry
        details_parts = []
        if 'title' in updates and updates['title'] != pres.get('title'):
            details_parts.append(f'العنوان: "{pres.get("title","")}" إلى "{updates["title"]}"')
        new_count = len(updates['slides_data']) if isinstance(updates['slides_data'], list) else 0
        old_count = len(current_slides) if isinstance(current_slides, list) else 0
        if new_count != old_count:
            details_parts.append(f'عدد الشرائح: {old_count} إلى {new_count}')
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
    draft['draft_data'] = _merge_persisted_map_assets(
        draft.get('draft_data') or {}, g.tenant_id, draft_id=draft.get('id')
    )
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
        g.tenant_id, _project_draft_actor_id(), draft_data, section_statuses, status,
        draft_id=draft_data.get('draftId') or draft_data.get('draft_id')
    )
    return jsonify({'success': True, 'draftId': draft_id})


@app.route('/api/project-drafts', methods=['GET'])
@require_auth
def api_get_all_project_drafts():
    """Get lightweight saved-project metadata for the tenant."""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit and offset must be integers'}), 400
    drafts = db.get_all_project_draft_summaries(g.tenant_id, limit=limit, offset=offset)
    return jsonify({'success': True, 'drafts': drafts, 'limit': max(1, min(limit, 200)), 'offset': max(0, offset)})


@app.route('/api/project-draft/<draft_id>', methods=['GET'])
@require_auth
def api_get_project_draft_by_id(draft_id):
    """Get a specific project draft by ID."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    draft['draft_data'] = _merge_persisted_map_assets(
        draft.get('draft_data') or {}, g.tenant_id, draft_id=draft_id
    )
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
        g.tenant_id, _project_draft_actor_id(), section_key, section_status, draft_id=data.get('draftId')
    )
    if not result:
        return jsonify({'error': 'Unable to update section status'}), 400
    return jsonify({'success': True})


@app.route('/api/project-draft/request-approval', methods=['POST'])
@require_auth
def api_request_project_draft_approval():
    """Request one overall approval after all tracked sections are approved."""
    data = request.json or {}
    draft = db.request_project_draft_approval(
        g.tenant_id, _project_draft_actor_id(), _project_draft_actor_id(), _project_draft_actor_name(),
        draft_id=data.get('draftId')
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



def _financial_inputs(model):
    if not isinstance(model, dict):
        return {}
    inputs = model.get('inputs')
    return inputs if isinstance(inputs, dict) else model


def _financial_has_value(value):
    return value is not None and not (isinstance(value, str) and not value.strip())


def validate_financial_model(model):
    """Validate only fields activated by the financial model switches."""
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    errors = []

    def required(key, label=None):
        if not _financial_has_value(inputs.get(key)):
            errors.append({'field': key, 'message': f'{label or key} مطلوب عند تفعيل هذا الخيار'})

    mode = inputs.get('unitRevenueMode') or 'mixed'
    sales_on = mode in {'sale', 'mixed'}
    rental_on = mode in {'rental', 'mixed'}
    if sales_on:
        required('salesStartYear', 'سنة بدء البيع')
        required('salesYears', 'عدد سنوات البيع')
    if rental_on:
        required('operationYears', 'عدد سنوات التشغيل')

    required('developmentYears', 'مدة التطوير')
    required('landArea', 'مساحة الأرض')
    required('builtUpAreaAbove', 'مسطحات البناء فوق الأرض')

    if inputs.get('financeEnabled') == 'yes':
        for key, label in (
            ('financeBase', 'أساس التمويل'), ('financingRate', 'نسبة التمويل'),
            ('financeArrangementFeeRate', 'رسوم ترتيب التمويل'),
            ('financeInterestMethod', 'طريقة احتساب الفائدة'), ('annualFinanceRate', 'معدل الفائدة'),
            ('financeDrawYears', 'سنوات سحب التمويل'),
            ('financeRepaymentStartYear', 'سنة بدء السداد'),
            ('financeRepaymentYears', 'سنوات السداد'),
        ):
            required(key, label)
        draw_rows = tables.get('financeDrawTable') or []
        repayment_rows = tables.get('financeRepaymentTable') or []
        if not draw_rows:
            errors.append({'field': 'financeDrawTable', 'message': 'خطة سحب التمويل مطلوبة عند تفعيل التمويل'})
        if not repayment_rows:
            errors.append({'field': 'financeRepaymentTable', 'message': 'خطة سداد التمويل مطلوبة عند تفعيل التمويل'})

    fund_on = inputs.get('fundEnabled') == 'yes'
    fees_on = fund_on and inputs.get('fundFeesEnabled') == 'yes'
    if fees_on:
        required('fundFeeBase', 'أساس أتعاب الصندوق')
        for key, label in (
            ('fundFeeStartYear', 'بداية احتساب أتعاب الصندوق'),
            ('fundFeeEndYear', 'نهاية احتساب أتعاب الصندوق'),
            ('fundFeeFrequency', 'دورية السداد'), ('fundFeeTiming', 'توقيت السداد'),
            ('fundFeeGrowthRate', 'نسبة نمو الأتعاب'),
        ):
            required(key, label)
        base = inputs.get('fundFeeBase')
        if base in {'fundCapital', 'investedCapital'}:
            required('fundCapitalInput', 'رأس مال الصندوق')
        elif base == 'nav':
            required('fundNavInput', 'صافي قيمة الأصول')
        elif base == 'fixed':
            required('fundFixedAnnualFee', 'الأتعاب السنوية الثابتة')

        if inputs.get('fundExitFeeEnabled') == 'yes':
            required('fundExitFeeBase', 'أساس أتعاب التخارج')
            if inputs.get('fundExitFeeBase') == 'fixed':
                required('fundExitFixedFee', 'مبلغ أتعاب التخارج')
            else:
                required('fundExitFeeRate', 'نسبة أتعاب التخارج')
        if inputs.get('performanceFeeEnabled') == 'yes':
            for key, label in (
                ('hurdleRate', 'الحد الأدنى للعائد'), ('hurdleMethod', 'طريقة الحد الأدنى'),
                ('performanceFeeRate', 'نسبة حافز الأداء'), ('performanceFeeBase', 'أساس حافز الأداء'),
                ('performanceCrystallizationYear', 'سنة احتساب حافز الأداء'),
            ):
                required(key, label)
            if inputs.get('catchupEnabled') == 'yes':
                required('catchupRate', 'نسبة Catch-up')
        additional_fees = tables.get('fundAdditionalFeesTable') or []
        for index, row in enumerate(additional_fees):
            if not isinstance(row, dict):
                continue
            if _financial_has_value(row.get('name')) and not _financial_has_value(row.get('value')):
                errors.append({'field': f'fundAdditionalFeesTable[{index}].value', 'message': 'قيمة الأتعاب الإضافية مطلوبة'})

    if rental_on and inputs.get('graceEnabled') == 'yes':
        for key, label in (
            ('graceMethod', 'طريقة فترة السماح'), ('graceScope', 'نطاق فترة السماح'),
            ('graceStartYear', 'سنة بداية السماح'), ('graceDurationMonths', 'مدة السماح'),
            ('graceDiscountRate', 'نسبة الخصم'),
        ):
            required(key, label)
        if inputs.get('graceScope') == 'selectedRevenue':
            required('graceRevenueId', 'الإيراد المشمول بالسماح')
        if inputs.get('graceMethod') == 'schedule' and not tables.get('graceScheduleTable'):
            errors.append({'field': 'graceScheduleTable', 'message': 'جدول خصومات فترة السماح مطلوب'})

    if inputs.get('externalEnabled') == 'yes' and not tables.get('externalTable'):
        errors.append({'field': 'externalTable', 'message': 'أضف بندًا خارجيًا واحدًا على الأقل'})

    if inputs.get('exitEnabled') == 'yes':
        if sales_on and inputs.get('saleExitMethod') not in (None, '', 'none'):
            required('saleExitYear', 'سنة التخارج البيعي')
        if rental_on and inputs.get('exitMethod') not in (None, '', 'none'):
            required('operatingExitYear', 'سنة التخارج التشغيلي')
            required('exitInput', 'مدخل التخارج التشغيلي')

    projection = model.get('projection') if isinstance(model, dict) else None
    if isinstance(projection, dict) and isinstance(projection.get('areaState'), dict) and projection['areaState'].get('valid') is False:
        errors.append({'field': 'componentsTable', 'message': 'مجموع مساحات مكونات المشروع يتجاوز مسطحات البناء فوق الأرض'})
    return errors


def _financial_report_escape(value):
    if value is None or value == '':
        return '—'
    if isinstance(value, (dict, list)):
        # A JSON dump used to be emitted here, which put raw [{"year":4,...}] into the client PDF.
        # Structured values belong in their own table, never in a label/value row.
        return '—'
    return html_lib.escape(str(value))


# Section 12 is a results summary, so it lists chosen metrics with Arabic labels instead of dumping
# the whole projection object, which also carried echoed inputs and raw schedule arrays.
FINANCIAL_RESULT_LABELS = (
    ('projectCost', 'إجمالي تكلفة المشروع'),
    ('projectCostWithFinance', 'التكلفة شاملة التمويل'),
    ('adjustedProjectCost', 'إجمالي تكلفة الاستثمار'),
    ('developerCost', 'أتعاب المطور'),
    ('landRent', 'إيجار الأرض السنوي'),
    ('saleRevenueTotal', 'إجمالي إيرادات البيع'),
    ('revenueY1', 'إيرادات السنة الأولى'),
    ('opexY1', 'مصروفات السنة الأولى'),
    ('noiY1', 'صافي الدخل التشغيلي — السنة الأولى'),
    ('fullOccupancyRevenue', 'الإيرادات عند الإشغال المستهدف'),
    ('fullOccupancyNOI', 'صافي الدخل التشغيلي عند الإشغال المستهدف'),
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
    ('roi', 'العائد على الاستثمار'),
    ('projectIrr', 'معدل العائد الداخلي للمشروع'),
    ('equityIrr', 'معدل العائد على حقوق الملكية'),
    ('payback', 'فترة استرداد رأس المال'),
    ('equityPayback', 'فترة استرداد حقوق الملكية'),
)


def _financial_report_rows(rows):
    # Structured values are dropped rather than stringified: they have their own tables.
    visible = [(label, value) for label, value in rows
               if value not in (None, '', [], {}) and not isinstance(value, (dict, list))]
    if not visible:
        return '<p class="empty">لا توجد قيم مطبقة في هذا القسم.</p>'
    return '<table class="summary-table"><tbody>' + ''.join(
        f'<tr><th>{_financial_report_escape(label)}</th><td>{_financial_report_escape(value)}</td></tr>'
        for label, value in visible
    ) + '</tbody></table>'


# Table columns arrive keyed by their internal name, which used to be printed as-is, so the client
# PDF showed headers like "costPct" and "saleRevenue". Unknown keys still fall back to the raw name
# so a new column shows up rather than silently vanishing.
FINANCIAL_COLUMN_LABELS = {
    'name': 'البند', 'useType': 'نوع الاستخدام', 'units': 'عدد الوحدات',
    'unitArea': 'مساحة الوحدة م²', 'builtArea': 'المساحة المبنية م²',
    'revenueArea': 'المساحة البيعية/التأجيرية م²', 'investmentModel': 'نموذج الاستفادة',
    'component': 'المكون المرتبط', 'qtySource': 'مصدر الكمية', 'method': 'طريقة الحساب',
    'qty': 'الكمية / المساحة', 'price': 'السعر / النسبة', 'period': 'الفترة',
    'occupancy': 'الإشغال المستهدف %', 'class': 'التصنيف', 'duration': 'المدة',
    'year': 'السنة', 'costPct': 'نسبة تكلفة التطوير %', 'devPct': 'نسبة دفعة المطور %',
    'drawPct': 'نسبة السحب %', 'repaymentPct': 'نسبة السداد %',
    'value': 'المبلغ / النسبة', 'startYear': 'سنة البداية', 'endYear': 'سنة النهاية',
    'recurrence': 'التكرار', 'type': 'نوع البند', 'base': 'القيمة الأساسية', 'growth': 'النمو %',
    'amount': 'القيمة', 'phase': 'المرحلة', 'occupancyReach': 'الوصول للإشغال %',
    'saleRevenue': 'المبيعات', 'operatingRevenue': 'إيرادات التأجير',
    'graceDiscount': 'خصم فترة السماح', 'developmentCost': 'تكلفة التطوير',
    'developerPayment': 'دفعة المطور', 'opex': 'المصروفات', 'landRent': 'إيجار الأرض',
    'fundFeesAnnual': 'أتعاب الصندوق', 'financeDraw': 'سحب التمويل',
    'financeInterest': 'فائدة التمويل', 'financeFee': 'رسوم التمويل',
    'financeRepayment': 'سداد أصل التمويل', 'final': 'صافي تدفق المشروع',
    'cumulative': 'الرصيد التراكمي', 'cashReserve': 'السيولة',
    'openingDebt': 'الرصيد الافتتاحي', 'closingDebt': 'الرصيد الختامي',
    'fundManagementFee': 'أتعاب الإدارة', 'additionalFundFees': 'الأتعاب الإضافية',
    'fundExitFee': 'أتعاب التخارج', 'performanceFee': 'حافز الأداء',
    'operationYear': 'سنة التشغيل', 'studyYear': 'السنة في الدراسة', 'reachPct': 'نسبة الوصول %',
    'terminal': 'قيمة التخارج',
}


def _financial_report_table(rows):
    if not isinstance(rows, list) or not rows:
        return '<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>'
    keys = []
    for row in rows:
        if isinstance(row, dict):
            for key in row:
                if key not in keys:
                    keys.append(key)
    if not keys:
        return '<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>'
    headers = ''.join(
        f'<th>{_financial_report_escape(FINANCIAL_COLUMN_LABELS.get(key, key))}</th>' for key in keys)
    body = ''.join('<tr>' + ''.join(f'<td>{_financial_report_escape(row.get(key))}</td>' for key in keys) + '</tr>'
                   for row in rows if isinstance(row, dict))
    return f'<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>'


def build_financial_report_html(project_name, model, branding, tenant_id):
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    projection = model.get('projection', {}) if isinstance(model, dict) and isinstance(model.get('projection'), dict) else {}
    primary = (branding or {}).get('primary_color') or '#123B6D'
    secondary = (branding or {}).get('secondary_color') or '#082646'
    accent = (branding or {}).get('accent_color') or '#C4A35A'
    font_css, font_family = build_font_css(branding or {}, tenant_id, embed=True)
    font_css = (font_css or '').replace('.slide', '.financial-report')
    rows = lambda keys: _financial_report_rows([(label, inputs.get(key)) for key, label in keys])
    sections = []
    sections.append(f'<section class="cover"><div class="eyebrow">دراسة مالية</div><h1>{_financial_report_escape(project_name)}</h1><h2>التقرير المالي المنظم</h2><p>تم إنشاء التقرير من النسخة المعتمدة للمدخلات والافتراضات.</p></section>')
    sections.append('<section><h2>1. ملخص المشروع</h2>' + rows([('unitRevenueMode', 'طبيعة الإيرادات'), ('developmentYears', 'مدة التطوير'), ('operationYears', 'سنوات التشغيل'), ('landArea', 'مساحة الأرض')]) + '</section>')
    sections.append('<section><h2>2. الأرض والمساحات</h2>' + rows([('landArea', 'مساحة الأرض'), ('coverageRate', 'نسبة التغطية'), ('floorCount', 'عدد الطوابق'), ('builtUpAreaAbove', 'مسطحات البناء فوق الأرض'), ('basementArea', 'مساحة البدرومات'), ('landValueMethod', 'طريقة احتساب قيمة الأرض'), ('landStatus', 'حالة الأرض')]) + '</section>')
    for number, title, table_key in (
        ('3', 'مكونات المشروع', 'componentsTable'), ('4', 'بنود الإيرادات', 'revenueTable'),
        ('5', 'تكاليف المشروع', 'costTable'), ('6', 'مراحل التطوير', 'scheduleTable'),
        ('7', 'المصروفات التشغيلية', 'opexTable'),
    ):
        sections.append(f'<section><h2>{number}. {title}</h2>{_financial_report_table(tables.get(table_key))}</section>')
    if inputs.get('financeEnabled') == 'yes':
        sections.append('<section><h2>8. التمويل</h2>' + rows([('financeBase', 'أساس التمويل'), ('financingRate', 'نسبة التمويل'), ('annualFinanceRate', 'معدل الفائدة'), ('financeInterestMethod', 'طريقة الفائدة'), ('financeDrawYears', 'سنوات السحب'), ('financeRepaymentYears', 'سنوات السداد')]) + _financial_report_table(tables.get('financeDrawTable')) + _financial_report_table(tables.get('financeRepaymentTable')) + '</section>')
    if inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes':
        sections.append('<section><h2>9. الصندوق وأتعابه</h2>' + rows([('fundFeeBase', 'أساس الأتعاب'), ('fundCapitalInput', 'رأس مال الصندوق'), ('fundManagementRate', 'نسبة الإدارة'), ('fundFeeStartYear', 'بداية الاحتساب'), ('fundFeeEndYear', 'نهاية الاحتساب')]) + _financial_report_table(tables.get('fundAdditionalFeesTable')) + '</section>')
    if inputs.get('externalEnabled') == 'yes':
        sections.append('<section><h2>10. البنود الخارجية</h2>' + _financial_report_table(tables.get('externalTable')) + '</section>')
    if inputs.get('exitEnabled') == 'yes':
        sections.append('<section><h2>11. التخارج</h2>' + rows([('saleExitMethod', 'التخارج البيعي'), ('saleExitYear', 'سنة التخارج البيعي'), ('exitMethod', 'التخارج التشغيلي'), ('operatingExitYear', 'سنة التخارج التشغيلي'), ('exitInput', 'مدخل التخارج')]) + '</section>')
    projection_rows = [(label, projection.get(key)) for key, label in FINANCIAL_RESULT_LABELS]
    sections.append('<section><h2>12. النتائج المالية</h2>' + _financial_report_rows(projection_rows) + _financial_report_table(tables.get('cashflowTable')) + '</section>')
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>
{font_css}
@page {{ size: A4 landscape; margin: 12mm; }}
* {{ box-sizing:border-box; }} body {{ margin:0; color:#252525; background:#fff; font-family:{font_family}; direction:rtl; line-height:1.5; }}
.financial-report {{ max-width:1120px; margin:0 auto; }} section {{ break-inside:avoid; margin:0 0 16px; }}
.cover {{ min-height:175mm; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; border:2px solid {primary}; padding:30px; page-break-after:always; }}
.eyebrow {{ color:{accent}; font-weight:700; }} h1 {{ color:{secondary}; font-size:32px; margin:18px 0 6px; }} h2 {{ color:{primary}; font-size:20px; border-bottom:2px solid {primary}; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; margin:8px 0 14px; font-size:10px; }} th,td {{ border:1px solid #d9d1cb; padding:6px; text-align:right; vertical-align:top; }} thead th {{ background:{primary}; color:#fff; }} .summary-table th {{ width:34%; background:#EAF2F8; color:{secondary}; }} .summary-table td {{ font-weight:700; }} .empty {{ color:#777; border:1px dashed #ccc; padding:10px; }}
</style></head><body><main class="financial-report">{''.join(sections)}</main></body></html>'''


def generate_financial_pdf(html, output_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])
        try:
            page = browser.new_page()
            page.set_content(html, wait_until='load')
            page.evaluate('() => document.fonts.ready')
            page.pdf(path=str(output_path), format='A4', landscape=True, print_background=True,
                     margin={'top': '12mm', 'right': '12mm', 'bottom': '12mm', 'left': '12mm'})
        finally:
            browser.close()


@app.route('/api/financial-study/validate', methods=['POST'])
@require_permission('create_presentation')
def api_validate_financial_study():
    data = request.json or {}
    errors = validate_financial_model(data.get('financialModel') or data.get('model') or {})
    return jsonify({'success': not errors, 'validation': errors})


@app.route('/api/financial-study/export', methods=['POST'])
@require_permission('export_files')
def api_export_financial_study():
    data = request.json or {}
    model = data.get('financialModel') or data.get('model') or {}
    errors = validate_financial_model(model)
    if errors:
        return jsonify({'success': False, 'error': 'لا يمكن تصدير الدراسة قبل استكمال المدخلات المطلوبة', 'validation': errors}), 400
    project_name = str(data.get('projectName') or 'الدراسة المالية').strip()[:120] or 'الدراسة المالية'
    tenant_output_dir = os.path.join(OUTPUT_DIR, g.tenant_id)
    os.makedirs(tenant_output_dir, exist_ok=True)
    safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'financial-study'
    output_path = os.path.join(tenant_output_dir, f'{safe_name}_{int(time.time())}_financial.pdf')
    try:
        branding = db.get_branding(g.tenant_id) or {}
        report_html = build_financial_report_html(project_name, model, branding, g.tenant_id)
        generate_financial_pdf(report_html, output_path)
        export_id = db.create_export(data.get('presentationId'), g.tenant_id, 'financial_pdf', output_path)
        return jsonify({'success': True, 'exportId': export_id, 'format': 'financial_pdf', 'url': f'/api/exports/{export_id}/download'})
    except Exception as error:
        print(f'[FINANCIAL PDF ERROR] {error}')
        if os.path.exists(output_path):
            os.unlink(output_path)
        return jsonify({'success': False, 'error': 'تعذر إنشاء ملف الدراسة المالية'}), 500


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
    print(f"[EXPORT] format={fmt} tenant={g.tenant_id} font_family={branding.get('font_family')!r} font_file_path={branding.get('font_file_path')!r}")

    # Tenant-specific output directory
    tenant_output_dir = os.path.join(OUTPUT_DIR, g.tenant_id)
    os.makedirs(tenant_output_dir, exist_ok=True)

    try:
        if fmt == 'pdf':
            from exports.pdf_export import generate_pdf
            slides_html = data.get('slidesHtml', '')
            slides_data = data.get('slidesData', [])
            presentation_id = data.get('presentationId')

            # Fallback: load latest saved slides from DB
            if not slides_html and not slides_data and presentation_id:
                pres = db.get_presentation(presentation_id, g.tenant_id)
                if pres and pres.get('slides_data'):
                    try:
                        loaded = pres['slides_data']
                        if isinstance(loaded, str):
                            loaded = json.loads(loaded)
                        slides_data = loaded if isinstance(loaded, list) else []
                    except Exception as e:
                        print(f"[EXPORT] failed to load slides_data: {e}")

            if not slides_html:
                if slides_data:
                    slides_html = '\n'.join(str(s.get('html', '')) for s in slides_data)
                if not slides_html:
                    return jsonify({'error': 'slidesHtml or slidesData is required for PDF export'}), 400

            safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'presentation'
            pdf_path = os.path.join(tenant_output_dir, f"{safe_name}_{int(time.time())}.pdf")
            generate_pdf(slides_html, branding, pdf_path, g.tenant_id)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pdf_path)}'

            # Record export
            export_id = db.create_export(presentation_id, g.tenant_id, 'pdf', pdf_path)
            if presentation_id:
                db.log_edit(presentation_id, g.user_id, g.user_name or 'System', 'export', f'Exported as PDF')
            return jsonify({'success': True, 'url': f'/api/exports/{export_id}/download', 'exportId': export_id, 'format': 'pdf'})

        elif fmt == 'pptx':
            from exports.pptx_export import generate_pptx
            slides_data = data.get('slidesData', [])
            presentation_id = data.get('presentationId')

            # Fallback: load latest saved slides from DB
            if not slides_data and presentation_id:
                pres = db.get_presentation(presentation_id, g.tenant_id)
                if pres and pres.get('slides_data'):
                    try:
                        loaded = pres['slides_data']
                        if isinstance(loaded, str):
                            loaded = json.loads(loaded)
                        slides_data = loaded if isinstance(loaded, list) else []
                    except Exception as e:
                        print(f"[EXPORT] failed to load slides_data for PPTX: {e}")

            if not slides_data:
                return jsonify({'error': 'slidesData is required for PPTX export'}), 400

            pptx_path = generate_pptx(slides_data, project_name, branding, tenant_output_dir, g.tenant_id)
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Project team library (فريق العمل)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _team_entity_payload(data):
    """Normalise a team-entity request body; returns (fields, error)."""
    name = str(data.get('name') or '').strip()
    if not name:
        return None, 'اسم الجهة مطلوب'
    logo_file_id = str(data.get('logoFileId') or '').strip()
    if logo_file_id and not db.get_project_file(g.tenant_id, logo_file_id):
        return None, 'شعار الجهة غير موجود'
    return {
        'name': name,
        'logo_file_id': logo_file_id,
        'brief': str(data.get('brief') or '').strip(),
        'experience_years': str(data.get('experienceYears') or '').strip(),
        'notable_projects': str(data.get('notableProjects') or '').strip(),
        'role': str(data.get('role') or '').strip(),
    }, None


@app.route('/api/team-entities', methods=['GET'])
@require_auth
def api_list_team_entities():
    """Company-wide team library; every project file starts from this list."""
    return jsonify({'success': True, 'entities': db.get_team_entities(g.tenant_id)})


@app.route('/api/team-entities', methods=['POST'])
@require_permission('company_settings')
def api_create_team_entity():
    fields, error = _team_entity_payload(request.json or {})
    if error:
        return jsonify({'success': False, 'error': error}), 400
    entity_id = db.create_team_entity(g.tenant_id, fields.pop('name'), **fields)
    return jsonify({'success': True, 'entity': db.get_team_entity(g.tenant_id, entity_id)}), 201


@app.route('/api/team-entities/<entity_id>', methods=['PUT'])
@require_permission('company_settings')
def api_update_team_entity(entity_id):
    if not db.get_team_entity(g.tenant_id, entity_id):
        return jsonify({'success': False, 'error': 'الجهة غير موجودة'}), 404
    fields, error = _team_entity_payload(request.json or {})
    if error:
        return jsonify({'success': False, 'error': error}), 400
    db.update_team_entity(g.tenant_id, entity_id, **fields)
    return jsonify({'success': True, 'entity': db.get_team_entity(g.tenant_id, entity_id)})


@app.route('/api/team-entities/<entity_id>', methods=['DELETE'])
@require_permission('company_settings')
def api_delete_team_entity(entity_id):
    if not db.delete_team_entity(g.tenant_id, entity_id):
        return jsonify({'success': False, 'error': 'الجهة غير موجودة'}), 404
    return jsonify({'success': True})


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


def _stringify_chat_part(value):
    """Flatten OpenRouter/OpenAI message fragments into a single string."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(_stringify_chat_part(item) for item in value)
    if isinstance(value, dict):
        for key in ('text', 'content', 'reasoning', 'output', 'summary'):
            fragment = value.get(key)
            if fragment not in (None, '', [], {}):
                return _stringify_chat_part(fragment)
        return ''
    return str(value)


def _get_chat_response_text(res):
    """Safely extract string content from OpenAI/GLM/OpenRouter chat response dict."""
    if not isinstance(res, dict):
        return str(res) if res else ""
    if 'choices' in res and isinstance(res['choices'], list) and res['choices']:
        choice = res['choices'][0]
        if isinstance(choice, dict):
            msg = choice.get('message', {})
            if isinstance(msg, dict):
                for key in ('content', 'reasoning', 'reasoning_content', 'reasoning_details'):
                    text = _stringify_chat_part(msg.get(key))
                    if text and str(text).strip():
                        return text
                parsed = msg.get('parsed')
                if isinstance(parsed, dict):
                    return json.dumps(parsed, ensure_ascii=False)
                return ''
            return str(choice.get('text', '') or '')
    return ""


def parse_json_object(text):
    """Extract and parse any JSON dict from text string."""
    if not text or not isinstance(text, str):
        return {}
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    cb = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if cb:
        try:
            parsed = json.loads(cb.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
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
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass
                        break
    return {}


PLACEHOLDER_VALUE_PHRASES = (
    'غير مدون', 'غير مذكور', 'غير موضح', 'غير متاح', 'غير محدد',
    'لا يوجد', 'n/a', 'none', 'null', 'غير مدونة',
)

# Cardinal/ordinal wording that belongs in the facade *directions* field, never in the count.
FACADE_DIRECTION_WORDS = ('شمال', 'جنوب', 'شرق', 'غرب', 'قبلي', 'بحري')

FACADE_COUNT_PATTERNS = (
    ('4', ('بلك كامل', 'بلك', 'أربع', 'اربع', '4 واجهات', 'أربعة شوارع', 'اربعة شوارع')),
    ('3', ('ثلاث', '3 واجهات', 'ثلاثة شوارع', '3 شوارع')),
    ('2', ('زاوية', 'زاوي', 'شارعين', 'واجهتين', 'واجهتان', '2 واجهة')),
    ('1', ('واجهة واحدة', 'شارع واحد', '1 واجهة')),
)


def is_placeholder_value(value):
    """True for short "not stated" answers that must not be stored as real data."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and len(text) < 20 and any(
        phrase in text.lower() for phrase in PLACEHOLDER_VALUE_PHRASES
    )


def normalize_facades_count(value, fallback_text=''):
    """Coerce the facade count to a bare 1-4.

    The form field is numeric, so a direction word ("جنوبية") is rejected outright instead
    of being written into the field; the caller keeps the wording in facades_directions.
    """
    text = '' if value is None else str(value).strip()
    digits = re.findall(r'[1-4]', text)
    if digits:
        return digits[0]
    for count, patterns in FACADE_COUNT_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return count
    if text and not any(word in text for word in FACADE_DIRECTION_WORDS):
        return ''
    for count, patterns in FACADE_COUNT_PATTERNS:
        if any(pattern in fallback_text for pattern in patterns):
            return count
    return ''


FACADE_SIDE_LABELS = (('north', 'شمالية'), ('south', 'جنوبية'), ('east', 'شرقية'), ('west', 'غربية'))

# A boundary that abuts another plot is not a facade, however the cell is worded.
FACADE_NEIGHBOUR_HINTS = ('جار', 'مجاور', 'قطعة', 'قطعه', 'ملك', 'أرض فضاء', 'حد القطعة')
FACADE_STREET_HINTS = ('شارع', 'طريق', 'ممر', 'كورنيش', 'ميدان', 'دوار', 'واجهة')


def facade_directions_from_streets(directions):
    """Return only the sides that actually front a street.

    A plot always has four boundaries, so listing all four compass points says nothing. What
    matters is which sides are facades — i.e. border a street rather than a neighbour.
    """
    found = []
    for side, label in FACADE_SIDE_LABELS:
        info = (directions or {}).get(side)
        if not isinstance(info, dict):
            continue
        text = ' '.join(
            str(info.get(key) or '') for key in ('street_name', 'uses', 'regulation_text')
        )
        width = info.get('street_width_m')
        has_width = width not in (None, '', 0, '0', '0.0')
        mentions_street = any(hint in text for hint in FACADE_STREET_HINTS)
        # "قطعة رقم 12" or "أرض مجاورة" means a neighbour, unless a street is named too.
        if any(hint in text for hint in FACADE_NEIGHBOUR_HINTS) and not mentions_street:
            continue
        if mentions_street or has_width:
            found.append(label)
    return '، '.join(found)


def normalize_facade_directions(*values):
    """Fallback for the legacy path: scan free text for cardinal directions."""
    haystack = ' '.join(str(value) for value in values if value)
    labels = (
        ('شمالية', ('شمالي', 'شمالية', 'الشمال', 'شمال')),
        ('جنوبية', ('جنوبي', 'جنوبية', 'الجنوب', 'جنوب')),
        ('شرقية', ('شرقي', 'شرقية', 'الشرق', 'شرق')),
        ('غربية', ('غربي', 'غربية', 'الغرب', 'غرب')),
    )
    found = [label for label, needles in labels if any(needle in haystack for needle in needles)]
    return '، '.join(found)


def normalize_north_direction(value):
    """Snap a free-text bearing onto one of the eight compass labels.

    Matches on the bare roots so wording like "الشمال الغربي" still resolves to a compound
    direction instead of collapsing to "شمال".
    """
    text = str(value or '').strip()
    if not text:
        return ''
    north, south = 'شمال' in text, 'جنوب' in text
    east, west = 'شرق' in text, 'غرب' in text
    for present, label in (
        (north and east, 'شمال شرقي'), (north and west, 'شمال غربي'),
        (south and east, 'جنوب شرقي'), (south and west, 'جنوب غربي'),
        (north, 'شمال'), (south, 'جنوب'), (east, 'شرق'), (west, 'غرب'),
    ):
        if present:
            return label
    return text


def strip_placeholder_values(payload):
    """Drop placeholder strings while leaving nested tables (dicts/lists) untouched."""
    cleaned = {}
    for key, value in (payload or {}).items():
        if isinstance(value, str):
            text = value.strip()
            if is_placeholder_value(text):
                continue
            cleaned[key] = text
        elif isinstance(value, (dict, list)):
            cleaned[key] = value
        elif value is not None:
            cleaned[key] = str(value)
    return cleaned


_LAND_USE_STATUS_LINE_RE = re.compile(
    r'(?:حالة\s*)?استخدام\s*(?:نوع\s*)?(?:المشروع|الأرض)\s*[:：]?\s*(مسموح|غير\s*مسموح|غير\s*محسوم|غير\s*محدد|ممنوع)',
    re.IGNORECASE,
)
_LAND_USE_STATUS_ONLY_RE = re.compile(
    r'^(حالة\s*استخدام\s*المشروع\s*[:：]\s*)?(مسموح|غير\s*مسموح|غير\s*محسوم|غير\s*محدد|ممنوع)\.?$',
    re.IGNORECASE,
)


def normalize_land_use_status(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if re.search(r'غير\s*مسموح|ممنوع', text):
        return 'غير مسموح'
    if re.search(r'غير\s*محسوم|غير\s*محدد', text):
        return 'غير محسوم'
    if text == 'مسموح' or re.search(r'(^|[^\u0621-\u064A])مسموح([^\u0621-\u064A]|$)', text):
        return 'مسموح'
    return ''


def split_land_use_status_text(text):
    raw = str(text or '')
    match = _LAND_USE_STATUS_LINE_RE.search(raw)
    only = _LAND_USE_STATUS_ONLY_RE.fullmatch(raw.strip())
    status = normalize_land_use_status(
        (match.group(1) if match else '') or (only.group(2) if only else '') or raw
    )
    cleaned = _LAND_USE_STATUS_LINE_RE.sub('', raw)
    cleaned = re.sub(r'ولم ي[ُو]حدد نوع المشروع[^\n.]*[.\n]?', '', cleaned)
    cleaned = re.sub(r'\n{2,}', '\n', cleaned).strip(' \n-–—:')
    if _LAND_USE_STATUS_ONLY_RE.fullmatch(cleaned):
        cleaned = ''
    return status, cleaned


PROJECT_TYPE_USE_ALIASES = {
    'سكني': ('سكني',),
    'تجاري': ('تجاري',),
    'إداري': ('إداري', 'مكتبي'),
    'فندقي': ('فندقي', 'فندق'),
    'ترفيهي': ('ترفيهي', 'سياحي', 'ترفيه'),
    'صناعي': ('صناعي',),
    'لوجستي': ('لوجستي', 'مستودع', 'تخزين'),
    'طبي': ('طبي', 'صحي'),
    'تعليمي': ('تعليمي', 'مدرسة', 'جامعة'),
    'سيارات وترفيه': ('سيارات', 'ترفيهي', 'ترفيه'),
    'مختلط': ('مختلط', 'متنوع', 'سكني', 'تجاري'),
}


def resolve_land_use_status(project_type, allowed_uses):
    """Compare the entered project type with extracted permitted uses.

    The model often leaves land_use_status unresolved even when the form sent
    "سكني" and the regulations already list residential use.
    """
    project = str(project_type or '').strip()
    uses = str(allowed_uses or '').strip()
    if not project or project.startswith('أخرى'):
        return 'غير محسوم'
    if not uses or uses.startswith('غير محدد'):
        return 'غير محسوم'
    aliases = PROJECT_TYPE_USE_ALIASES.get(project, (project,))
    if any(alias and alias in uses for alias in aliases):
        return 'مسموح'
    return 'غير مسموح'


def apply_entered_land_use_status(result, project_type=''):
    if not isinstance(result, dict):
        return result
    parcels = result.get('parcels') if isinstance(result.get('parcels'), list) else []
    first = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    uses = str(result.get('allowed_uses') or first.get('allowed_uses') or '').strip()
    _, uses = split_land_use_status_text(uses)
    status = resolve_land_use_status(project_type, uses)
    if uses:
        result['allowed_uses'] = uses
        if first:
            first['allowed_uses'] = uses
    result['land_use_status'] = status
    if first:
        first['land_use_status'] = status
    return result


def merge_regulatory_access_requirements(payload):
    if not isinstance(payload, dict):
        return payload
    uses = str(payload.get('allowed_uses') or '').strip()
    legacy_uses = str(payload.get('allowed_uses_restrictions') or '').strip()
    if not uses and legacy_uses:
        uses = legacy_uses
    constraints = str(payload.get('regulatory_constraints') or '').strip()
    additions = []
    for label, key in (
        ('اشتراطات المواقف', 'parking_requirements'),
        ('اشتراطات المداخل والمخارج', 'entrances_exits_requirements'),
    ):
        value = str(payload.get(key) or '').strip()
        if value and value not in additions and value not in constraints:
            additions.append(f'{label}: {value}')
    if uses:
        payload['allowed_uses'] = uses
    if additions:
        constraints = '\n'.join([item for item in (constraints, *additions) if item])
    if constraints:
        payload['regulatory_constraints'] = constraints
    legacy_parts = [item for item in (uses, constraints) if item]
    if legacy_parts:
        payload['allowed_uses_restrictions'] = '\n'.join(legacy_parts)
    return payload


def normalize_croquis_fields(resp_json, text_content=""):
    """Normalize extracted croquis fields, map select dropdown values, filter invalid placeholders, and apply text regex fallbacks."""
    if not isinstance(resp_json, dict):
        resp_json = {}

    resp_json = strip_placeholder_values(resp_json)

    full_text = text_content + " " + json.dumps(resp_json, ensure_ascii=False)

    # 1. Deed number fallback
    if not resp_json.get('deed_number'):
        deed_match = re.search(r'(?:صك|الصك|مرجع|المرجع|وثيقة)\s*(?:رقم)?\s*[:\s]*([0-9]{8,14})', full_text)
        if deed_match:
            resp_json['deed_number'] = deed_match.group(1)

    # 2. Plot / plan number fallback
    if not resp_json.get('plot_number_croquis'):
        plot_match = re.search(r'(?:قطعة|قطعه|مخطط)\s*(?:رقم)?\s*[:\s]*([0-9/\-\sA-Za-z]+)', full_text)
        if plot_match:
            resp_json['plot_number_croquis'] = plot_match.group(1).strip()

    # 3. Land area fallback (Targeting "بموجب التنظيم")
    if not resp_json.get('croquis_land_area'):
        area_match = re.search(r'(?:بموجب التنظيم|المساحة بموجب التنظيم|المساحة التنظيمية|مساحة الأرض|المساحة الإجمالية|مساحة المخطط)\s*[:\s]*([0-9,.]+)', full_text)
        if area_match:
            resp_json['croquis_land_area'] = area_match.group(1).replace(',', '')

    # These values are client decisions, so AI output is never allowed to populate or overwrite them.
    resp_json.pop('approved_financial_area', None)
    resp_json.pop('approved_financial_area_sqm', None)
    resp_json.pop('approved_floor_count', None)
    resp_json.pop('approved_floors', None)
    resp_json.pop('approved_coverage_ratio', None)

    # 4. Facades count normalization & fallback (Pure Number: 1, 2, 3, 4)
    raw_facades = resp_json.get('facades_count', '')
    resp_json['facades_count'] = normalize_facades_count(raw_facades, full_text)
    if not resp_json.get('facades_directions'):
        directions_text = normalize_facade_directions(raw_facades, resp_json.get('surrounding_streets'))
        if directions_text:
            resp_json['facades_directions'] = directions_text

    # 5. Floors / Max height fallback
    if not resp_json.get('max_floors_height'):
        floor_match = re.search(r'(?:أدوار|دور|ارتفاع|الأدوار)\s*[:\s]*([^\n,.]+)', full_text)
        if floor_match:
            resp_json['max_floors_height'] = floor_match.group(1).strip()

    # 6. North direction normalization
    resp_json['north_direction'] = normalize_north_direction(resp_json.get('north_direction'))

    # 7. Apply Aliases across all keys
    aliases = {
        'plot_number_croquis': ['plot_number', 'plot_and_plan_number'],
        'croquis_land_area': ['land_area'],
        'deed_number': ['deed_or_reference_number'],
        'deed_date': ['deed_issue_date', 'deed_date_hijri'],
        'plan_number': ['plan_no', 'subdivision_plan_number'],
        'subdivision_number': ['section_number', 'part_number'],
        'boundary_lengths': ['boundary_dimensions'],
        'surrounding_streets': ['surrounding_streets_widths'],
        'building_ratio_coverage': ['building_coverage', 'building_ratio'],
        'building_ratio_setbacks': ['building_coverage_setbacks'],
        'setbacks': ['setback_requirements'],
        'allowed_uses': ['permitted_uses', 'allowed_land_uses'],
        'regulatory_constraints': ['restrictions', 'regulatory_restrictions'],
        'max_floors_height': ['height_or_floors_allowed'],
    }
    # 8. Apply aliases and build a source-faithful summary. Missing values stay
    # explicitly unknown; never invent a city, regulation, area, or validity.
    for canonical, alternatives in aliases.items():
        if resp_json.get(canonical) in (None, ''):
            for alternative in alternatives:
                if resp_json.get(alternative) not in (None, ''):
                    resp_json[canonical] = resp_json[alternative]
                    break

    merge_regulatory_access_requirements(resp_json)
    if not resp_json.get('building_ratio_coverage'):
        resp_json['building_ratio_coverage'] = land_rule_text(resp_json)
    if not resp_json.get('building_ratio_setbacks'):
        resp_json['building_ratio_setbacks'] = land_rule_text(resp_json, include_setbacks=True)
    if not resp_json.get('allowed_uses') and resp_json.get('allowed_uses_restrictions'):
        resp_json['allowed_uses'] = resp_json['allowed_uses_restrictions']
    summary_text = str(resp_json.get('land_and_building_summary', '')).replace('{}', '').strip()
    if not summary_text:
        labels = (
            ('رقم القطعة', resp_json.get('plot_number_croquis')),
            ('رقم المخطط', resp_json.get('plan_number')),
            ('رقم القسم', resp_json.get('subdivision_number')),
            ('رقم الصك/المرجع', resp_json.get('deed_number')),
            ('تاريخ الصك', resp_json.get('deed_date')),
            ('المساحة التنظيمية م²', resp_json.get('croquis_land_area')),
            ('الحدود والأبعاد', resp_json.get('boundary_lengths')),
            ('الاتجاهات', resp_json.get('directions') or resp_json.get('north_direction')),
            ('الشوارع والواجهات', resp_json.get('surrounding_streets')),
            ('نسب البناء والارتدادات', resp_json.get('building_ratio_setbacks')),
            ('الارتفاع/الأدوار', resp_json.get('max_floors_height')),
            ('اشتراطات المواقف', resp_json.get('parking_requirements')),
            ('المداخل والمخارج', resp_json.get('entrances_exits_requirements')),
            ('الاستخدامات والقيود', resp_json.get('allowed_uses_restrictions')),
        )
        available = [f'{label}: {value}' for label, value in labels if value not in (None, '', [], {})]
        summary_text = ' | '.join(available) if available else 'لم يتم استخراج بيانات مؤكدة؛ تحتاج الوثائق إلى مراجعة يدوية.'

    resp_json['land_and_building_summary'] = summary_text.replace('{}', '').strip()
    strip_regulation_references_from_payload(resp_json)

    return resp_json


REGULATION_OUTPUT_KEYS = {
    'building_ratio', 'coverage_ratio', 'floor_area_ratio', 'table_floors',
    'building_ratio_coverage', 'building_ratio_setbacks', 'setbacks',
    'max_floors_height', 'allowed_uses', 'allowed_uses_restrictions',
    'regulatory_constraints', 'parking_requirements', 'entrances_exits_requirements',
    'land_and_building_summary', 'document_summary', 'summary',
}


def strip_regulation_references(value):
    if not isinstance(value, str):
        return value
    cleaned = re.sub(
        r'(?:اشتراطات\s*[12](?:\.pdf)?\s*(?:[-–—]\s*)?)?(?:صفحة|صفحات|ص)\s*[0-9٠-٩]+(?:\s*[-–—]\s*[0-9٠-٩]+)?',
        '', value, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned.replace('  ', ' ').strip(' \n-–—')


def strip_regulation_references_from_payload(payload):
    if not isinstance(payload, dict):
        return payload
    for key, value in list(payload.items()):
        if key in REGULATION_OUTPUT_KEYS and isinstance(value, str):
            payload[key] = strip_regulation_references(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    strip_regulation_references_from_payload(item)
        elif isinstance(value, dict) and key in {'parcels', 'site_facts'}:
            strip_regulation_references_from_payload(value)
    return payload


def land_rule_text(payload, include_setbacks=False):
    if not isinstance(payload, dict):
        return ''
    labels = (
        ('نسبة البناء', payload.get('building_ratio')),
        ('نسبة التغطية', payload.get('coverage_ratio')),
        ('معامل مسطح البناء (FAR)', payload.get('floor_area_ratio')),
        ('عدد الأدوار بموجب الجدول', payload.get('table_floors')),
    )
    if include_setbacks:
        labels += (('الارتدادات', payload.get('setbacks')),)
    return '\n'.join(
        f'{label}: {str(value).strip()}'
        for label, value in labels
        if value not in (None, '') and str(value).strip()
    )


REGULATION_PDF_NAMES = ('اشتراطات1.pdf', 'اشتراطات2.pdf')
REGULATION_SNIPPET_CHARS = int(os.environ.get('REGULATION_SNIPPET_CHARS', '2600'))
REGULATION_MAX_SNIPPETS = int(os.environ.get('REGULATION_MAX_SNIPPETS', '6'))
REGULATION_MAX_TABLE_PAGES = int(os.environ.get('REGULATION_MAX_TABLE_PAGES', '6'))
REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE = int(os.environ.get('REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', '0'))
REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE = int(os.environ.get('REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE', '0'))
REGULATION_EVIDENCE_MAX_CHARS_PER_FILE = int(os.environ.get('REGULATION_EVIDENCE_MAX_CHARS_PER_FILE', '0'))
REGULATION_EVIDENCE_TEXT_CHUNK_CHARS = int(os.environ.get('REGULATION_EVIDENCE_TEXT_CHUNK_CHARS', '50000'))
REGULATION_EVIDENCE_TABLE_BATCH_SIZE = int(os.environ.get(
    'REGULATION_EVIDENCE_TABLE_BATCH_SIZE',
    os.environ.get('REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE', '4')))
REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE = REGULATION_EVIDENCE_TABLE_BATCH_SIZE
REGULATION_EVIDENCE_TABLE_DPI = int(os.environ.get('REGULATION_EVIDENCE_TABLE_DPI', '180'))
LAND_FACTS_MAX_TOKENS = int(os.environ.get('LAND_FACTS_MAX_TOKENS', '2500'))
LAND_FACTS_MIN_TOKENS = int(os.environ.get('LAND_FACTS_MIN_TOKENS', '1200'))
REGULATION_EVIDENCE_MAX_TOKENS = int(os.environ.get('REGULATION_EVIDENCE_MAX_TOKENS', '4000'))
REGULATION_EVIDENCE_MIN_TOKENS = int(os.environ.get('REGULATION_EVIDENCE_MIN_TOKENS', '1500'))

_REGULATION_PAGE_INDEX = None
_REGULATION_PAGE_INDEX_SIGNATURE = None

# Terms that mark a page as carrying the conditions we need. Arabic extracted from these PDFs
# loses the lam-alef ligature and some letters, so the roots are matched without "ال".
REGULATION_TOPIC_TERMS = (
    ('نسبة البناء', 6), ('مسطح البناء', 4), ('معامل مسطح', 4),
    ('ارتداد', 6), ('تغطية', 4), ('عدد الطوابق', 5), ('الطوابق', 3),
    ('ارتفاع', 3), ('استعمال', 2), ('استخدام', 2),
    ('مواقف', 4), ('مدخل', 3), ('مخرج', 3), ('تحميل', 3), ('خدمات', 2),
    ('محاور التجارية', 3), ('سكني', 2), ('تجاري', 2),
)

# Repeated page furniture in these documents; it wastes the snippet budget.
_REGULATION_NOISE = re.compile(
    r'(المخطط المحلي لمحافظة\s*جدة\s*1447[^\n]*|أنظمة وضوابط البناء\s*1447[^\n]*|'
    r'الالئحة التنفيذية[^\n]*|م\s*ص\s*\d+\s*من\s*\d+|\.{6,})'
)


def _clean_regulation_text(text):
    """Strip repeated headers/footers and dotted index rows from an extracted page."""
    cleaned = _REGULATION_NOISE.sub(' ', text or '')
    return re.sub(r'[ \t]*\n[ \t]*', '\n', re.sub(r'[ \t]{2,}', ' ', cleaned)).strip()


def _is_regulation_index_page(text):
    """Index / list-of-figures pages match many keywords but contain no actual rules."""
    if not text:
        return True
    if len(re.findall(r'\.{6,}', text)) >= 3:
        return True
    return len(re.findall(r'\(\s*شكل رقم\s*\d+', text)) >= 3


def _score_regulation_page(text, query_tokens):
    score = sum(weight for term, weight in REGULATION_TOPIC_TERMS if term in text)
    for token in query_tokens:
        if token and token in text:
            score += 8
    if re.search(r'\d{2}\s*%', text):
        score += 5
    return score


def regulation_pdf_paths():
    """Absolute paths of the municipality regulation PDFs that exist on disk."""
    base = os.path.dirname(__file__)
    return [os.path.join(base, name) for name in REGULATION_PDF_NAMES
            if os.path.isfile(os.path.join(base, name))]


def search_official_regulations_pdf(query_text=""):
    """Return a bounded, source-separated regulation evidence packet for older callers."""
    package, warnings = search_official_regulations_evidence(query_text, {})
    return package.get('context', ''), package.get('table_pages', []), warnings


def _regulation_index_signature(paths):
    signature = []
    for path in paths:
        try:
            stat = os.stat(path)
            signature.append((path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((path, None, None))
    return tuple(signature)


def _build_regulation_page_index():
    global _REGULATION_PAGE_INDEX, _REGULATION_PAGE_INDEX_SIGNATURE
    paths = regulation_pdf_paths()
    signature = _regulation_index_signature(paths)
    if _REGULATION_PAGE_INDEX_SIGNATURE == signature and _REGULATION_PAGE_INDEX is not None:
        return _REGULATION_PAGE_INDEX
    try:
        import fitz
    except ImportError:
        _REGULATION_PAGE_INDEX = []
        _REGULATION_PAGE_INDEX_SIGNATURE = signature
        return []

    records = []
    for path in paths:
        name = os.path.basename(path)
        try:
            document = fitz.open(path)
        except Exception:
            continue
        try:
            for index in range(len(document)):
                page = document[index]
                raw = page.get_text()
                if _is_regulation_index_page(raw):
                    continue
                cleaned = _clean_regulation_text(raw)
                try:
                    has_table = bool(page.find_tables().tables)
                except Exception:
                    has_table = False
                if not cleaned and not has_table:
                    continue
                records.append({
                    'name': name,
                    'path': path,
                    'page': index + 1,
                    'text': cleaned,
                    'has_table': has_table,
                })
        finally:
            document.close()
    _REGULATION_PAGE_INDEX = records
    _REGULATION_PAGE_INDEX_SIGNATURE = signature
    return records


def _regulation_search_tokens(query_text='', site_facts=None):
    values = [str(query_text or '')]
    if isinstance(site_facts, dict):
        values.extend(str(site_facts.get(key) or '') for key in (
            'area_sqm', 'croquis_land_area', 'zoning_code', 'land_use', 'city',
            'project_type', 'axis_type', 'building_type', 'plot_number'
        ))
    blob = ' '.join(values)
    tokens = re.findall(r'[0-9A-Za-z\u0600-\u06FF/%.-]{3,}', blob)
    return list(dict.fromkeys(token.casefold() for token in tokens))[:24]


def search_official_regulations_evidence(query_text='', site_facts=None):
    records = _build_regulation_page_index()
    if not records:
        return {'context': '', 'documents': [], 'table_pages': []}, [
            'ملفات الاشتراطات غير موجودة أو لا تحتوي صفحات قابلة للبحث: '
            + '، '.join(REGULATION_PDF_NAMES)
        ]
    query_tokens = _regulation_search_tokens(query_text, site_facts)
    warnings = []
    documents = []
    table_pages = []
    for name in REGULATION_PDF_NAMES:
        file_records = [record for record in records if record['name'] == name]
        scored = sorted(
            (
                {
                    **record,
                    'score': _score_regulation_page(record['text'], query_tokens)
                }
                for record in file_records
            ),
            key=lambda record: (-record['score'], record['page'])
        )
        matched = [record for record in scored if record['score'] > 0]
        full_document = REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE <= 0
        text_records = file_records if full_document else matched[:REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE]
        table_pool = file_records if REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE <= 0 else matched
        table_records = [record for record in table_pool if record['has_table']]
        if REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE > 0:
            table_records = table_records[:REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE]
        if not text_records:
            warnings.append(f'لم يتم العثور على صفحات مطابقة في {name}')
        context_parts = []
        remaining = None if REGULATION_EVIDENCE_MAX_CHARS_PER_FILE <= 0 else REGULATION_EVIDENCE_MAX_CHARS_PER_FILE
        for record in text_records:
            if remaining is not None and remaining <= 0:
                break
            raw_text = record.get('text') or ''
            max_chars = len(raw_text) if remaining is None else min(REGULATION_SNIPPET_CHARS, remaining)
            snippet = raw_text[:max_chars]
            if not snippet and not record.get('has_table'):
                continue
            if not snippet:
                snippet = 'لا يوجد نص مستخرج من هذه الصفحة؛ اقرأ الجدول من الصورة المرفقة.'
            context_parts.append(
                f"--- {name} — صفحة {record['page']} — score={record.get('score', 0)} ---\n{snippet}"
            )
            if remaining is not None:
                remaining -= len(snippet)
        for record in table_records:
            table_pages.append({
                'path': record['path'],
                'name': name,
                'page': record['page'],
                'score': record.get('score', 0),
            })
        documents.append({
            'name': name,
            'context': '\n\n'.join(context_parts),
            'text_pages': [record['page'] for record in text_records],
            'table_pages': [record['page'] for record in table_records],
        })
    return {
        'context': '\n\n'.join(document['context'] for document in documents if document['context']),
        'documents': documents,
        'table_pages': table_pages,
    }, warnings


def split_regulation_context(context, max_chars=None):
    text = str(context or '').strip()
    limit = max_chars if max_chars is not None else REGULATION_EVIDENCE_TEXT_CHUNK_CHARS
    limit = max(1000, int(limit))
    if not text:
        return []
    units = [unit.strip() for unit in re.split(
        r'(?=---\s+[^\n]+—\s*صفحة\s+[0-9٠-٩]+\s+—)', text) if unit.strip()]
    if not units:
        units = [text]
    chunks = []
    current = ''
    for unit in units:
        if len(unit) > limit:
            if current:
                chunks.append(current)
                current = ''
            for start in range(0, len(unit), limit):
                chunks.append(unit[start:start + limit])
            continue
        candidate = unit if not current else current + '\n\n' + unit
        if current and len(candidate) > limit:
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def regulation_context_page_numbers(context):
    return {
        int(value.translate(_ARABIC_INDIC_DIGITS))
        for value in re.findall(r'---\s+[^\n]+—\s*صفحة\s+([0-9٠-٩]+)\s+—', str(context or ''))
    }


def split_regulation_table_batches(table_pages, batch_size=None):
    rows = list(table_pages or [])
    limit = int(batch_size if batch_size is not None else REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE)
    if limit <= 0:
        return [rows] if rows else []
    return [rows[start:start + limit] for start in range(0, len(rows), limit)]


def _extract_full_regulation_evidence(source, site_facts):
    source_name = source.get('name') or 'ملف اشتراطات'
    context = str(source.get('context') or '')
    table_pages = source.get('table_pages') if isinstance(source.get('table_pages'), list) else []
    chunks = split_regulation_context(context)
    if not chunks and table_pages:
        chunks = ['']
    evidence = []
    uncertainties = []
    warnings = []
    base_prompt = (
        "أنت مستخرج أدلة تنظيمية من ملف واحد كامل فقط. أعد JSON فقط بهذا الشكل: "
        '{"evidence":[{"field":"","value":"","page":0,"quote":""}],'
        '"uncertainties":[]} '
        f"المصدر الوحيد هو {source_name}. لا تستخدم أي معلومة من ملف آخر. "
        "اقرأ الجزء الحالي من المحتوى الكامل وصور الجداول المرفقة، واستخرج القواعد التي تنطبق على حقائق الموقع. "
        "يمكن حفظ رقم الصفحة داخليًا داخل evidence فقط لتتبع الدليل، ولا تضعه في أي قيمة اشتراط أو نص موجّه للمستخدم. "
        "أرقام الجداول تُقرأ من الصور المرفقة لأن النص قد يكون معكوسًا."
    )

    def run_stage(stage_name, context_chunk, table_batch, stage_note):
        nonlocal evidence, uncertainties
        parts, render_warnings = render_regulation_table_pages(
            table_batch, dpi=REGULATION_EVIDENCE_TABLE_DPI)
        warnings.extend(render_warnings)
        user_content = [{
            'type': 'text',
            'text': base_prompt + stage_note
                    + '\nحقائق الموقع المستخرجة من الكروكي:\n'
                    + json.dumps(site_facts, ensure_ascii=False)
                    + '\nجزء المحتوى الحالي:\n' + context_chunk
        }] + parts
        result, _cap, error = _run_land_json_stage(
            stage_name, base_prompt, user_content,
            REGULATION_EVIDENCE_MAX_TOKENS, REGULATION_EVIDENCE_MIN_TOKENS,
            REGULATION_EVIDENCE_MAX_TOKENS * 2
        )
        if error:
            warnings.append(f'تعذر استخراج جزء من أدلة {source_name}: {error}')
            return
        values = result.get('evidence') if isinstance(result, dict) else []
        if isinstance(values, list):
            evidence.extend(item for item in values if isinstance(item, dict))
        uncertainty_values = result.get('uncertainties') if isinstance(result, dict) else []
        if isinstance(uncertainty_values, list):
            uncertainties.extend(uncertainty_values)

    has_page_metadata = any(regulation_context_page_numbers(chunk) for chunk in chunks)
    if not has_page_metadata:
        if context.strip():
            for chunk_index, context_chunk in enumerate(chunks):
                run_stage(
                    f'{source_name}-text-{chunk_index + 1}', context_chunk, [],
                    f'\nهذا الجزء {chunk_index + 1} من {len(chunks)} من المحتوى الكامل للملف.')
        table_batch_size = REGULATION_EVIDENCE_TABLE_BATCH_SIZE
        if table_batch_size > 0:
            table_batches = [
                table_pages[start:start + table_batch_size]
                for start in range(0, len(table_pages), table_batch_size)
            ]
        else:
            table_batches = [table_pages]
        for batch_index, table_batch in enumerate(table_batches):
            run_stage(
                f'{source_name}-tables-{batch_index + 1}', '', table_batch,
                '\nهذه دفعة جداول من المحتوى الكامل للملف.')
        return {'evidence': evidence, 'uncertainties': uncertainties, 'warnings': warnings}

    for chunk_index, context_chunk in enumerate(chunks):
        chunk_pages = regulation_context_page_numbers(context_chunk)
        chunk_tables = [
            entry for entry in table_pages
            if not chunk_pages or entry.get('page') in chunk_pages
        ]
        table_batch_size = REGULATION_EVIDENCE_TABLE_BATCH_SIZE
        if table_batch_size > 0:
            table_batches = [
                chunk_tables[start:start + table_batch_size]
                for start in range(0, len(chunk_tables), table_batch_size)
            ]
        else:
            table_batches = [chunk_tables]
        if not table_batches:
            table_batches = [[]]
        for batch_index, table_batch in enumerate(table_batches):
            context_for_stage = context_chunk if batch_index == 0 else ''
            stage_note = f'\nهذا الجزء {chunk_index + 1} من {len(chunks)} من المحتوى الكامل للملف.'
            if batch_index:
                stage_note += '\nهذه دفعة جداول إضافية للجزء نفسه؛ استخرج منها ما لم يظهر في الدفعة السابقة.'
            run_stage(
                f'{source_name}-part-{chunk_index + 1}-tables-{batch_index + 1}',
                context_for_stage, table_batch, stage_note)
    return {'evidence': evidence, 'uncertainties': uncertainties, 'warnings': warnings}


def render_regulation_table_pages(table_pages, dpi=200):
    """Render the ranked regulation table pages to images for the vision model."""
    if not table_pages:
        return [], []
    try:
        import fitz
    except ImportError:
        return [], ['PyMuPDF غير متاح؛ تعذر تصوير جداول الاشتراطات']

    parts, warnings = [], []
    scale = max(1.0, float(dpi) / 72.0)
    matrix = fitz.Matrix(scale, scale)
    by_path = {}
    for entry in table_pages:
        by_path.setdefault(entry['path'], []).append(entry)
    for path, entries in by_path.items():
        try:
            document = fitz.open(path)
        except Exception as error:
            warnings.append(f"تعذر تصوير جداول {entries[0]['name']}: {error}")
            continue
        try:
            for entry in entries:
                index = entry['page'] - 1
                if index < 0 or index >= len(document):
                    continue
                pixmap = document[index].get_pixmap(matrix=matrix, alpha=False)
                encoded = base64.b64encode(pixmap.tobytes('png')).decode('ascii')
                parts.append({
                    'type': 'text',
                    'text': (f"جدول تنظيم من لائحة الأمانة: {entry['name']} — صفحة {entry['page']}. "
                             "اقرأ الأرقام من الصورة؛ نص هذا الجدول يُستخرج بترتيب معكوس فلا تعتمد عليه.")
                })
                parts.append({
                    'type': 'image_url',
                    'image_url': {'url': f'data:image/png;base64,{encoded}', 'detail': 'high'}
                })
        finally:
            document.close()
    return parts, warnings

PDF_VISION_DPI = int(os.environ.get('PDF_VISION_DPI', '300'))
PDF_VISION_MAX_PAGES = int(os.environ.get('PDF_VISION_MAX_PAGES', '40'))
PDF_VISION_MAX_EDGE = int(os.environ.get('PDF_VISION_MAX_EDGE', '3000'))
PDF_VISION_JPEG_QUALITY = int(os.environ.get('PDF_VISION_JPEG_QUALITY', '85'))
PDF_VISION_MAX_TOTAL_BYTES = int(os.environ.get('PDF_VISION_MAX_TOTAL_BYTES', str(12 * 1024 * 1024)))
PDF_VISION_TILE_COLUMNS = int(os.environ.get('PDF_VISION_TILE_COLUMNS', '2'))
PDF_VISION_TILE_ROWS = int(os.environ.get('PDF_VISION_TILE_ROWS', '3'))
PDF_VISION_TILE_MAX_PAGES = int(os.environ.get('PDF_VISION_TILE_MAX_PAGES', '6'))
PDF_VISION_TILE_MAX_EDGE = int(os.environ.get('PDF_VISION_TILE_MAX_EDGE', '2600'))
PDF_VISION_TILE_DPI = int(os.environ.get('PDF_VISION_TILE_DPI', '600'))
PDF_VISION_TILE_JPEG_QUALITY = int(os.environ.get('PDF_VISION_TILE_JPEG_QUALITY', '72'))
PDF_VISION_TILE_OVERLAP = float(os.environ.get('PDF_VISION_TILE_OVERLAP', '0.04'))
PDF_VISION_ALTERNATE_TILE_LIMIT = int(os.environ.get('PDF_VISION_ALTERNATE_TILE_LIMIT', '2'))
PDF_VISION_ROTATION_MIN_SCORE_GAP = float(os.environ.get('PDF_VISION_ROTATION_MIN_SCORE_GAP', '0.004'))
PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP = float(os.environ.get('PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP', '0.003'))
# The land prompt asks for a multi-paragraph Arabic narrative, sourced building rules and a full
# coordinates table. Arabic costs roughly 2-3 tokens per word, so a low cap truncates the JSON and
# the whole extraction is then rejected, which looks to the user like "nothing changed".
# The ceiling cannot simply be raised either: OpenRouter *reserves* max_tokens against the account
# balance, so an over-large cap is refused with 402 even when the real answer would be short.
# _call_land_analysis_model() walks the cap back down when that happens.
LAND_ANALYSIS_MAX_TOKENS = int(os.environ.get('LAND_ANALYSIS_MAX_TOKENS', '16000'))
LAND_ANALYSIS_MIN_TOKENS = int(os.environ.get('LAND_ANALYSIS_MIN_TOKENS', '6000'))
LAND_ANALYSIS_TRUNCATION_CEILING = int(os.environ.get('LAND_ANALYSIS_TRUNCATION_CEILING', '20000'))
# Gemini 3.6 Flash accepts text, images, and files and is the primary model
# for all text/analysis workflows, including land and croquis extraction.
LAND_ANALYSIS_MODEL = GEMINI_TEXT_MODEL

_AFFORDABLE_TOKENS_RE = re.compile(r'can only afford\s+(\d+)')
_TRANSIENT_PROVIDER_RE = re.compile(r'\(HTTP 5\d\d\)')
_EMPTY_PROVIDER_RE = re.compile(r'جسم فارغ \(HTTP \d+\)')
_JSON_MODE_BLOCK_RE = re.compile(
    r'output_format|content filtering|response_format|structured.?output',
    re.IGNORECASE,
)
LAND_ANALYSIS_PROVIDER = {'order': ['Google'], 'allow_fallbacks': False}


def _chat_error_message(res):
    """Human-readable provider error, so a failure is never reported as a mystery."""
    if not isinstance(res, dict):
        return str(res)[:400]
    error = res.get('error')
    if isinstance(error, dict):
        return str(error.get('message') or error)[:400]
    return str(error or 'unknown provider error')[:400]


def _call_land_analysis_model(system_prompt, user_content, max_tokens, min_tokens=None, truncation_ceiling=None):
    """Call the vision model, lowering the reserved cap when the provider cannot afford it.

    Gateway failures (HTTP 5xx) are usually transient, so they are retried with the same cap
    before being surfaced. A response truncated at the cap is retried once with a higher cap,
    bounded by ``LAND_ANALYSIS_TRUNCATION_CEILING``. Returns ``(response, used_cap, error_message)``.
    """
    minimum = LAND_ANALYSIS_MIN_TOKENS if min_tokens is None else max(1, int(min_tokens))
    ceiling = LAND_ANALYSIS_TRUNCATION_CEILING if truncation_ceiling is None else max(1, int(truncation_ceiling))
    cap = max(minimum, int(max_tokens))
    message = ''
    res = None
    use_json_mode = True
    for attempt in range(3):
        res = call_openrouter_chat(
            system_prompt, user_content, temperature=None,
            max_tokens=cap, model=LAND_ANALYSIS_MODEL,
            response_format={'type': 'json_object'} if use_json_mode else None,
            provider=LAND_ANALYSIS_PROVIDER,
        )
        if _has_chat_choices(res):
            choices = res.get('choices') or []
            finish_reason = choices[0].get('finish_reason') if choices and isinstance(choices[0], dict) else None
            higher_cap = min(ceiling, int(cap * 1.35))
            if finish_reason == 'length' and higher_cap > cap and attempt < 2:
                print(f'[LAND ANALYSIS] response truncated at cap={cap}; retrying with {higher_cap}')
                cap = higher_cap
                continue
            raw_text = _get_chat_response_text(res)
            if not str(raw_text).strip() and use_json_mode and attempt < 2:
                print('[LAND ANALYSIS] json_object returned empty content; retrying without response_format')
                use_json_mode = False
                continue
            return res, cap, ''
        message = _chat_error_message(res)
        affordable = _AFFORDABLE_TOKENS_RE.search(message)
        if affordable:
            # Leave a margin: the quoted allowance shrinks as the prompt itself consumes credit.
            retry_cap = max(minimum, int(int(affordable.group(1)) * 0.85))
            if retry_cap >= cap:
                break
            print(f'[LAND ANALYSIS] provider refused max_tokens={cap}; retrying with {retry_cap}')
            cap = retry_cap
            continue
        if use_json_mode and _JSON_MODE_BLOCK_RE.search(message) and attempt < 2:
            print(f'[LAND ANALYSIS] json_object blocked; retrying without response_format: {message}')
            use_json_mode = False
            continue
        if (_TRANSIENT_PROVIDER_RE.search(message) or _EMPTY_PROVIDER_RE.search(message)) and attempt < 2:
            print(f'[LAND ANALYSIS] transient provider response; retrying: {message}')
            time.sleep(2)
            continue
        break
    return res, cap, message


def _run_land_json_stage(stage_name, system_prompt, user_content, max_tokens, min_tokens, truncation_ceiling):
    response, used_cap, provider_error = _call_land_analysis_model(
        system_prompt,
        user_content,
        max_tokens,
        min_tokens=min_tokens,
        truncation_ceiling=truncation_ceiling,
    )
    if not _has_chat_choices(response):
        return {}, used_cap, provider_error
    raw = _get_chat_response_text(response)
    parsed = parse_json_object(raw)
    if not parsed:
        return {}, used_cap, 'المرحلة ' + stage_name + ' أعادت JSON فارغًا أو غير صالح'
    print(f'[LAND ANALYSIS STAGE] {stage_name} cap={used_cap} chars={len(raw)}')
    return parsed, used_cap, ''


def _extract_land_site_facts(parsed, request_data=None):
    source = parsed.get('site_facts') if isinstance(parsed, dict) else None
    source = source if isinstance(source, dict) else (parsed if isinstance(parsed, dict) else {})
    request_data = request_data if isinstance(request_data, dict) else {}
    facts = {}
    for key in ('area_sqm', 'croquis_land_area', 'zoning_code', 'land_use', 'city',
                'project_type', 'axis_type', 'building_type', 'plot_number',
                'location_address', 'location_lat', 'location_lng'):
        value = source.get(key)
        if value in (None, ''):
            value = request_data.get(key)
        if value not in (None, ''):
            facts[key] = value
    return facts


def _compact_regulation_evidence(source_name, parsed):
    if not isinstance(parsed, dict):
        return {'source_file': source_name, 'evidence': {}}
    evidence = parsed.get('evidence') or parsed.get('regulation_evidence') or parsed.get('rules')
    if evidence is None:
        evidence = parsed
    return {'source_file': source_name, 'evidence': evidence}


def _decode_data_uri(data_uri):
    if not isinstance(data_uri, str) or not data_uri.strip():
        return None
    payload = data_uri.split(',', 1)[1] if ',' in data_uri else data_uri
    try:
        return base64.b64decode(payload, validate=False)
    except (TypeError, ValueError):
        return None


PDF_PAGE_SELECTION_TERMS = (
    ('إحداثيات التنظيم', 160), ('جدول إحداثيات', 145), ('إحداثيات', 100),
    ('الشرقيات', 75), ('الشماليات', 75), ('نقاط الحدود', 60),
    ('بموجب التنظيم', 150), ('الاتجاهات', 90), ('حدود', 55), ('الشوارع', 45), ('واجهات', 45),
    ('ارتدادات', 35), ('مواقف', 35), ('مداخل', 35), ('مخارج', 35),
    ('coordinates', 70), ('easting', 60), ('northing', 60),
)


def _rank_pdf_page(raw_text):
    text = str(raw_text or '').lower().replace('ـ', '')
    score = 0
    for term, weight in PDF_PAGE_SELECTION_TERMS:
        normalized = term.lower()
        if normalized in text or normalized[::-1] in text:
            score += weight
    return score


def _pixmap_to_pil(pixmap):
    from PIL import Image
    mode = 'RGBA' if pixmap.alpha else 'RGB'
    return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples).convert('RGB')


def _encode_vision_image(image, quality, use_png=False):
    import io
    buffer = io.BytesIO()
    if use_png:
        image.save(buffer, format='PNG', optimize=True)
        mime = 'image/png'
    else:
        image.save(buffer, format='JPEG', quality=max(40, int(quality)), optimize=True)
        mime = 'image/jpeg'
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:{mime};base64,{encoded}', len(encoded)


def _detect_scan_rotation(image):
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return {
            'rotation': 0,
            'alternate_rotations': [],
            'method': 'default_no_numpy',
            'axis_gap': 0,
            'scores': {},
        }

    sample = image.convert('L')
    resampling = getattr(Image, 'Resampling', Image).LANCZOS
    sample.thumbnail((900, 900), resampling)
    gray = np.asarray(sample, dtype=np.uint8)
    if gray.ndim != 2 or min(gray.shape) < 16:
        return {
            'rotation': 0,
            'alternate_rotations': [],
            'method': 'default_small_image',
            'axis_gap': 0,
            'scores': {},
        }

    pad_y = max(1, int(gray.shape[0] * 0.02))
    pad_x = max(1, int(gray.shape[1] * 0.02))
    gray = gray[pad_y:-pad_y, pad_x:-pad_x]
    dark = gray < 200

    def projection_score(mask):
        height, width = mask.shape
        horizontal = 0.0
        vertical = 0.0
        for span, weight in ((2, 1.0), (3, 2.0), (4, 2.0), (5, 1.0), (7, 1.0)):
            if width >= span:
                run = np.ones((height, width - span + 1), dtype=bool)
                for offset in range(span):
                    run &= mask[:, offset:offset + width - span + 1]
                horizontal += weight * np.count_nonzero(run)
            if height >= span:
                run = np.ones((height - span + 1, width), dtype=bool)
                for offset in range(span):
                    run &= mask[offset:offset + height - span + 1, :]
                vertical += weight * np.count_nonzero(run)
        return float(horizontal - vertical) / max(1, mask.size)

    scores = {
        0: projection_score(dark),
        90: projection_score(np.rot90(dark, 1)),
        180: projection_score(np.rot90(dark, 2)),
        270: projection_score(np.rot90(dark, 3)),
    }
    base_score = (scores[0] + scores[180]) / 2
    sideways_score = (scores[90] + scores[270]) / 2
    axis_gap = sideways_score - base_score
    configured = os.environ.get('PDF_VISION_ROTATION', 'auto').strip().lower()
    if configured in {'0', '90', '180', '270'}:
        rotation = int(configured)
        alternate = []
        method = 'configured'
    elif axis_gap >= PDF_VISION_ROTATION_MIN_SCORE_GAP:
        rotation = 90 if scores[90] - scores[270] >= PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP else 270
        alternate = [270 if rotation == 90 else 90]
        method = 'projection_profile_sideways'
    elif axis_gap <= -PDF_VISION_ROTATION_MIN_SCORE_GAP:
        rotation = 180 if scores[180] - scores[0] >= PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP else 0
        alternate = []
        method = 'projection_profile_upright'
    else:
        rotation = 180 if scores[180] - scores[0] >= PDF_VISION_ROTATION_DIRECTION_MIN_SCORE_GAP else 0
        alternate = []
        method = 'projection_profile_ambiguous'

    return {
        'rotation': rotation,
        'alternate_rotations': alternate,
        'method': method,
        'axis_gap': round(axis_gap, 6),
        'scores': {str(key): round(value, 6) for key, value in scores.items()},
    }


def _render_pdf_clip_image(page, clip, scale, rotation):
    import fitz
    from PIL import Image
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    image = _pixmap_to_pil(pixmap)
    if rotation:
        resampling = getattr(Image, 'Resampling', Image).BICUBIC
        image = image.rotate(rotation, expand=True, resample=resampling)
    return image


def _pdf_tile_rects(rect):
    import fitz
    columns = max(1, PDF_VISION_TILE_COLUMNS)
    rows = max(1, PDF_VISION_TILE_ROWS)
    overlap = max(0.0, min(0.2, PDF_VISION_TILE_OVERLAP))
    result = []
    for row in range(rows):
        for column in range(columns):
            x0 = max(0.0, rect.width * column / columns - rect.width * overlap)
            y0 = max(0.0, rect.height * row / rows - rect.height * overlap)
            x1 = min(rect.width, rect.width * (column + 1) / columns + rect.width * overlap)
            y1 = min(rect.height, rect.height * (row + 1) / rows + rect.height * overlap)
            result.append((fitz.Rect(x0, y0, x1, y1), row, column))
    return result


def _alternate_tile_indexes(tile_count):
    columns = max(1, PDF_VISION_TILE_COLUMNS)
    priority = [index for index in range(tile_count) if index % columns == columns - 1]
    priority.extend(index for index in range(tile_count) if index not in priority)
    return priority


def _render_pdf_pages_for_vision(file_data, filename, dpi=PDF_VISION_DPI, max_pages=PDF_VISION_MAX_PAGES,
                                 budget=PDF_VISION_MAX_TOTAL_BYTES, diagnostics=None):
    """Render relevant PDF pages to image data URIs for vision models without OCR/text extraction.

    Raw 300 DPI PNG pages made multi-page deed books into a request so large that the
    provider's proxy dropped it with a bare non-JSON 502. Each page is therefore capped to
    ``PDF_VISION_MAX_EDGE`` pixels on its long side and encoded as JPEG, and when a document
    still exceeds its byte budget the whole document is re-rendered down a ladder of smaller
    edge caps and qualities until it fits.
    """
    pdf_bytes = _decode_data_uri(file_data)
    if not pdf_bytes:
        raise ValueError(f'Unable to decode PDF: {filename}')
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PyMuPDF is required for visual PDF analysis') from exc

    pages = []
    page_diagnostics = []
    truncated = False
    dpi_scale = max(1.0, float(dpi) / 72.0)
    ladder = (
        (PDF_VISION_MAX_EDGE, PDF_VISION_JPEG_QUALITY),
        (int(PDF_VISION_MAX_EDGE * 0.75), 80),
        (int(PDF_VISION_MAX_EDGE * 0.55), 72),
    )
    document = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        page_count = len(document)
        limit = min(page_count, max(1, int(max_pages)))
        if page_count <= limit:
            selected_pages = list(range(page_count))
        else:
            scored_pages = []
            for index, page in enumerate(document):
                score = _rank_pdf_page(page.get_text())
                try:
                    score += min(3, len(page.find_tables().tables)) * 55
                except Exception:
                    pass
                if score > 0:
                    scored_pages.append((score, index))
            ranked_pages = sorted(scored_pages, key=lambda item: (-item[0], item[1]))
            selected_pages = [index for _, index in ranked_pages[:limit]]
            for index in range(page_count):
                if len(selected_pages) >= limit:
                    break
                if index not in selected_pages:
                    selected_pages.append(index)
            selected_pages.sort()
        truncated = len(selected_pages) < page_count
        tile_limit = min(len(selected_pages), max(0, PDF_VISION_TILE_MAX_PAGES))
        selection_order = {index: position for position, index in enumerate(selected_pages)}
        tile_candidates = sorted(
            selected_pages,
            key=lambda index: (-_rank_pdf_page(document[index].get_text()), selection_order[index])
        )
        tile_page_indexes = set(tile_candidates[:tile_limit])
        for edge_cap, quality in ladder:
            pages = []
            page_diagnostics = []
            total = 0
            for page_index in selected_pages:
                page = document[page_index]
                rect = page.rect
                orientation_scale = min(dpi_scale, 900.0 / max(rect.width, rect.height, 1.0))
                orientation_image = _render_pdf_clip_image(page, None, orientation_scale, 0)
                orientation = _detect_scan_rotation(orientation_image)
                scale = min(dpi_scale, float(edge_cap) / max(rect.width, rect.height, 1.0))
                full_image = _render_pdf_clip_image(page, None, scale, orientation['rotation'])
                full_data, full_size = _encode_vision_image(full_image, quality)
                total += full_size
                pages.append({
                    'page_number': page_index + 1,
                    'image_data': full_data,
                    'kind': 'full',
                    'rotation': orientation['rotation'],
                    'orientation_variant': 'primary',
                    'orientation_method': orientation['method'],
                    'axis_gap': orientation['axis_gap'],
                })
                if orientation['alternate_rotations']:
                    alternate_scale = min(dpi_scale, float(edge_cap * 0.65) / max(rect.width, rect.height, 1.0))
                    alternate_image = _render_pdf_clip_image(
                        page, None, alternate_scale, orientation['alternate_rotations'][0]
                    )
                    alternate_data, alternate_size = _encode_vision_image(
                        alternate_image, min(quality, 65)
                    )
                    total += alternate_size
                    pages.append({
                        'page_number': page_index + 1,
                        'image_data': alternate_data,
                        'kind': 'full',
                        'rotation': orientation['alternate_rotations'][0],
                        'orientation_variant': 'alternate',
                    })
                page_diagnostics.append({
                    'page': page_index + 1,
                    'rotation': orientation['rotation'],
                    'alternate_rotations': orientation['alternate_rotations'],
                    'method': orientation['method'],
                    'axis_gap': orientation['axis_gap'],
                })
                if page_index not in tile_page_indexes:
                    continue
                tile_rects = _pdf_tile_rects(rect)
                tile_edge = min(PDF_VISION_TILE_MAX_EDGE, max(1200, int(edge_cap)))
                tile_quality = min(quality, PDF_VISION_TILE_JPEG_QUALITY)
                for tile_index, (clip, row, column) in enumerate(tile_rects):
                    tile_scale = min(float(PDF_VISION_TILE_DPI) / 72.0,
                                     tile_edge / max(clip.width, clip.height, 1.0))
                    tile_image = _render_pdf_clip_image(page, clip, tile_scale, orientation['rotation'])
                    tile_data, tile_size = _encode_vision_image(tile_image, tile_quality)
                    total += tile_size
                    pages.append({
                        'page_number': page_index + 1,
                        'image_data': tile_data,
                        'kind': 'tile',
                        'tile_index': tile_index,
                        'tile_row': row,
                        'tile_column': column,
                        'rotation': orientation['rotation'],
                        'orientation_variant': 'primary',
                    })
                if orientation['alternate_rotations']:
                    alternate_indexes = _alternate_tile_indexes(len(tile_rects))
                    if budget < 8 * 1024 * 1024:
                        alternate_indexes = alternate_indexes[:PDF_VISION_ALTERNATE_TILE_LIMIT]
                    for tile_index in alternate_indexes:
                        clip, row, column = tile_rects[tile_index]
                        alternate_rotation = orientation['alternate_rotations'][0]
                        tile_scale = min(float(PDF_VISION_TILE_DPI) / 72.0,
                                         tile_edge / max(clip.width, clip.height, 1.0))
                        tile_image = _render_pdf_clip_image(page, clip, tile_scale, alternate_rotation)
                        tile_data, tile_size = _encode_vision_image(tile_image, tile_quality)
                        total += tile_size
                        pages.append({
                            'page_number': page_index + 1,
                            'image_data': tile_data,
                            'kind': 'tile',
                            'tile_index': tile_index,
                            'tile_row': row,
                            'tile_column': column,
                            'rotation': alternate_rotation,
                            'orientation_variant': 'alternate',
                        })
            if total <= max(1, int(budget)):
                break
        while total > max(1, int(budget)):
            removable = next((index for index in range(len(pages) - 1, -1, -1)
                              if pages[index].get('kind') == 'tile'
                              and pages[index].get('orientation_variant') == 'alternate'), None)
            if removable is None:
                removable = next((index for index in range(len(pages) - 1, -1, -1)
                                  if pages[index].get('kind') == 'full'
                                  and pages[index].get('orientation_variant') == 'alternate'), None)
            if removable is None:
                removable = next((index for index in range(len(pages) - 1, -1, -1)
                                  if pages[index].get('kind') == 'tile'), None)
            if removable is None:
                break
            total -= len(pages[removable].get('image_data', '').split(',', 1)[-1])
            pages.pop(removable)
    finally:
        document.close()

    if diagnostics is not None:
        diagnostics.update({
            'page_rotations': page_diagnostics,
            'rotated_page_count': sum(1 for item in page_diagnostics if item.get('rotation')),
            'tile_count': sum(1 for item in pages if item.get('kind') == 'tile'),
            'image_count': len(pages),
            'encoded_base64_bytes': sum(len(item.get('image_data', '').split(',', 1)[-1]) for item in pages),
        })
    return pages, page_count, truncated


def _prepare_document_vision_parts(document, budget=PDF_VISION_MAX_TOTAL_BYTES, diagnostics=None):
    """Prepare image parts for a document while preserving source/page metadata."""
    file_data = document.get('fileData') or ''
    filename = document.get('filename') or 'document'
    mime_type = str(document.get('mimeType') or '').lower()
    is_pdf = (
        'application/pdf' in mime_type
        or file_data.startswith('data:application/pdf')
        or filename.lower().endswith('.pdf')
    )
    if not is_pdf:
        if diagnostics is not None:
            diagnostics.update({'image_count': 1, 'tile_count': 0, 'rotated_page_count': 0})
        return [{
            'type': 'image_url',
            'image_url': {'url': file_data, 'detail': 'high'}
        }], [], 1, 'image_direct'

    vision_diagnostics = {}
    pages, page_count, truncated = _render_pdf_pages_for_vision(
        file_data, filename, budget=budget, diagnostics=vision_diagnostics)
    warnings = []
    if truncated:
        selected_numbers = ', '.join(dict.fromkeys(
            str(page.get('page_number')) for page in pages if page.get('kind') == 'full'
        ))
        warnings.append(f'{filename}: تم تحليل الصفحات الأكثر ارتباطًا ({selected_numbers}) من أصل {page_count}')
    rotated_pages = [item for item in vision_diagnostics.get('page_rotations', []) if item.get('rotation')]
    if rotated_pages:
        rotations = '، '.join(f"صفحة {item['page']}: {item['rotation']} درجة" for item in rotated_pages)
        warnings.append(f'{filename}: تم تصحيح اتجاه {rotations}')
    if diagnostics is not None:
        diagnostics.update(vision_diagnostics)
    expanded = []
    for page in pages:
        if page.get('kind') == 'tile':
            variant = 'بديلة' if page.get('orientation_variant') == 'alternate' else 'مصَححة'
            label = (
                f"قصاصة مكبرة {variant} من الصفحة {page['page_number']}، "
                f"الموضع {page.get('tile_index', 0) + 1}، اتجاه {page.get('rotation', 0)} درجة. "
                "استخدمها لقراءة الأرقام والجداول، وتجاهل النسخة البديلة إذا كانت مقلوبة."
            )
        else:
            variant = ' بديلة' if page.get('orientation_variant') == 'alternate' else ''
            label = (
                f"الصورة الكاملة{variant} للمستند {filename}، الصفحة {page['page_number']} من {page_count}، "
                f"اتجاه العرض {page.get('rotation', 0)} درجة. "
                "استخدم الصورة البديلة فقط إذا كانت الكتابة فيها أفقية أوضح."
            )
        expanded.extend([
            {'type': 'text', 'text': label},
            {'type': 'image_url', 'image_url': {'url': page['image_data'], 'detail': 'high'}},
        ])
    return expanded, warnings, page_count, 'pdf_rendered'


PARCEL_PLACEHOLDER_KEYS = (
    'plot_number', 'plan_number', 'subdivision_number', 'deed_number', 'deed_date',
    'north_direction', 'setbacks', 'building_ratio', 'building_ratio_coverage',
    'coverage_ratio', 'floor_area_ratio', 'table_floors', 'max_floors_height',
    'parking_requirements', 'entrances_exits_requirements', 'allowed_uses',
    'allowed_uses_restrictions', 'regulatory_constraints', 'land_use_status', 'summary',
)


def _normalize_parcel_scalar_fields(parcel, text_content=''):
    """Apply the shared scalar normalizers to a single parcel.

    Historically these rules only ran when the model skipped the ``parcels`` array, so the
    regex fallbacks and the numeric facade coercion never executed on the real code path.
    """
    parcel.pop('approved_floor_count', None)
    parcel.pop('approved_floors', None)
    parcel.pop('approved_coverage_ratio', None)
    for key in PARCEL_PLACEHOLDER_KEYS:
        if is_placeholder_value(parcel.get(key)):
            parcel[key] = ''

    fallback_text = f"{text_content} {json.dumps(parcel, ensure_ascii=False, default=str)}"

    raw_facades = parcel.get('facades_count')
    parcel['facades_count'] = normalize_facades_count(raw_facades, fallback_text)
    # Derive the facades from the directions table: only sides bordering a street count.
    street_sides = facade_directions_from_streets(parcel.get('directions'))
    if street_sides:
        parcel['facades_directions'] = street_sides
        parcel['facades_count'] = str(len(street_sides.split('،')))
    elif not parcel.get('facades_directions'):
        parcel['facades_directions'] = ''

    parcel['north_direction'] = normalize_north_direction(parcel.get('north_direction'))

    if not parcel.get('deed_number'):
        deed_match = re.search(
            r'(?:صك|الصك|مرجع|المرجع|وثيقة)\s*(?:رقم)?\s*[:\s]*([0-9]{8,14})', fallback_text)
        if deed_match:
            parcel['deed_number'] = deed_match.group(1)

    if not parcel.get('deed_date'):
        parcel['deed_date'] = _find_document_date(fallback_text)

    if not parcel.get('plan_number'):
        plan_match = re.search(
            r'(?:رقم\s*)?(?:المخطط|مخطط)\s*(?:رقم)?\s*[:\s]*'
            r'([0-9\u0660-\u0669]{1,5}\s*/\s*[\u0621-\u064A0-9]{1,6}(?:\s*/\s*[\u0621-\u064A0-9]{1,6})?)',
            fallback_text)
        if plan_match:
            parcel['plan_number'] = re.sub(r'\s*', '', plan_match.group(1))

    merge_regulatory_access_requirements(parcel)
    if not parcel.get('building_ratio_coverage'):
        parcel['building_ratio_coverage'] = land_rule_text(parcel)
    if not parcel.get('building_ratio_setbacks'):
        parcel['building_ratio_setbacks'] = land_rule_text(parcel, include_setbacks=True)
    if not parcel.get('allowed_uses') and parcel.get('allowed_uses_restrictions'):
        parcel['allowed_uses'] = parcel['allowed_uses_restrictions']
    status, uses = split_land_use_status_text(parcel.get('allowed_uses'))
    if uses:
        parcel['allowed_uses'] = uses
    parcel['land_use_status'] = normalize_land_use_status(parcel.get('land_use_status')) or status
    strip_regulation_references_from_payload(parcel)
    return parcel


# Deed dates are usually Hijri and written in many shapes: "وتاريخ 1446/03/12هـ",
# "بتاريخ 12/03/1446", "تاريخ الصك 1446-03-12". Capture the date nearest a date keyword.
_DOCUMENT_DATE_PATTERNS = (
    r'(?:تاريخ\s*(?:الصك|صك|الإصدار|الاصدار|الاصدر))\s*[:\s]*([0-9\u0660-\u0669]{1,4}[/\-.][0-9\u0660-\u0669]{1,2}[/\-.][0-9\u0660-\u0669]{1,4})',
    r'(?:و?بتاريخ|و?تاريخ)\s*[:\s]*([0-9\u0660-\u0669]{1,4}[/\-.][0-9\u0660-\u0669]{1,2}[/\-.][0-9\u0660-\u0669]{1,4})',
    r'([0-9\u0660-\u0669]{1,4}[/\-.][0-9\u0660-\u0669]{1,2}[/\-.][0-9\u0660-\u0669]{1,4})\s*(?:هـ|هجري|هجرية)',
)

_ARABIC_INDIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def _find_document_date(text):
    """Return the first date that looks like an issue date, normalised to Y/M/D."""
    for pattern in _DOCUMENT_DATE_PATTERNS:
        match = re.search(pattern, text or '')
        if not match:
            continue
        raw = match.group(1).translate(_ARABIC_INDIC_DIGITS)
        parts = re.split(r'[/\-.]', raw)
        if len(parts) != 3:
            continue
        # Whichever end holds the 4-digit group is the year.
        if len(parts[0]) == 4:
            year, month, day = parts
        else:
            day, month, year = parts
        try:
            return f'{int(year)}/{int(month):02d}/{int(day):02d}'
        except ValueError:
            continue
    return ''


def _coordinate_table_rows(table):
    if not isinstance(table, dict):
        return []
    for key in ('rows', 'points', 'items', 'data'):
        rows = table.get(key)
        if isinstance(rows, list) and rows:
            return rows
    return []


def _coordinate_table_title(table):
    if not isinstance(table, dict):
        return ''
    return ' '.join(str(table.get(key) or '') for key in (
        'table_name', 'table_title', 'title', 'name', 'label', 'source', 'الجدول', 'اسم الجدول'
    )).strip()


def _coordinate_table_entries(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict) and _coordinate_table_rows(item)]
    if not isinstance(value, dict):
        return []
    if _coordinate_table_rows(value):
        return [value]
    entries = []
    for title, rows in value.items():
        if isinstance(rows, list) and rows:
            entries.append({'table_name': str(title), 'rows': rows})
    return entries


def _is_regulation_coordinate_table(table):
    title = _coordinate_table_title(table).casefold()
    return 'التنظيم' in title or 'regulation' in title


def _regulation_coordinate_rows_from_payload(payload):
    if not isinstance(payload, dict):
        return []
    for key in ('coordinate_tables', 'coordinates_tables', 'coordinate_table', 'coordinates_table', 'coordinatesTable'):
        for table in _coordinate_table_entries(payload.get(key)):
            if _is_regulation_coordinate_table(table):
                rows = _coordinate_table_rows(table)
                if rows:
                    return rows
    for key in ('regulation_coordinates', 'regulation_coordinates_table'):
        value = payload.get(key)
        if isinstance(value, dict):
            value = _coordinate_table_rows(value)
        if isinstance(value, list) and value:
            return value
    return []


def _coordinate_rows_from_payload(payload):
    if not isinstance(payload, dict):
        return []
    regulation_rows = _regulation_coordinate_rows_from_payload(payload)
    if regulation_rows:
        return regulation_rows
    for key in ('survey_coordinates', 'coordinates_table', 'coordinatesTable'):
        value = payload.get(key)
        if isinstance(value, dict):
            value = _coordinate_table_rows(value)
        if isinstance(value, list) and value:
            return value
    return []


def _coordinate_value(item, aliases):
    for key, value in item.items():
        normalized = str(key).strip().casefold()
        if normalized in aliases and value not in (None, ''):
            return str(value)
    return ''


def _normalize_survey_coordinate_rows(raw_coordinates, parcel_id):
    if isinstance(raw_coordinates, dict):
        raw_coordinates = raw_coordinates.get('rows') or raw_coordinates.get('points') or []
    if not isinstance(raw_coordinates, list):
        return []
    regulation_rows = []
    for item in raw_coordinates:
        if not isinstance(item, dict):
            continue
        metadata = ' '.join(str(item.get(key) or '') for key in (
            'source', 'table', 'table_name', 'coordinates_table_name', 'point', 'point_number', 'notes', 'الجدول'
        )).casefold()
        if 'التنظيم' in metadata or 'regulation' in metadata:
            regulation_rows.append(item)
    if regulation_rows:
        raw_coordinates = regulation_rows
    normalized = []
    for item in raw_coordinates:
        if not isinstance(item, dict):
            continue
        row_parcel_id = _coordinate_value(item, {'parcel_id', 'parcelid', 'plot_number', 'رقم القطعة'}) or str(parcel_id)
        point = _coordinate_value(item, {'point', 'point_number', 'pointnumber', 'رقم النقطة', 'النقطة'})
        if 'التنظيم' in point or 'regulation' in point.casefold():
            point_match = re.search(r'[0-9\u0660-\u0669]+', point)
            if point_match:
                point = point_match.group(0)
        eastings = _coordinate_value(item, {
            'eastings', 'easting', 'easting_coordinate', 'الشرقيات', 'الشرقي', 'شرقيات'
        })
        northings = _coordinate_value(item, {
            'northings', 'northing', 'northing_coordinate', 'الشماليات', 'الشمالي', 'شماليات'
        })
        source = _coordinate_value(item, {'source', 'المصدر'}) or 'regulation_table'
        if row_parcel_id or point or eastings or northings:
            normalized.append({
                'parcel_id': row_parcel_id,
                'point': point,
                'eastings': eastings,
                'northings': northings,
                'source': source,
            })
    return normalized


_DIRECTION_ALIASES = {
    'n': 'north', 'north': 'north', 'شمال': 'north', 'الشمال': 'north',
    's': 'south', 'south': 'south', 'جنوب': 'south', 'الجنوب': 'south',
    'e': 'east', 'east': 'east', 'شرق': 'east', 'الشرق': 'east',
    'w': 'west', 'west': 'west', 'غرب': 'west', 'الغرب': 'west',
}


def _normalize_direction_map(value):
    if isinstance(value, dict):
        entries = []
        for key, item in value.items():
            if isinstance(item, dict):
                entry = dict(item)
            else:
                entry = {'notes': str(item)}
            entry['direction'] = key
            entries.append(entry)
    elif isinstance(value, list):
        entries = [item for item in value if isinstance(item, dict)]
    else:
        entries = []
    directions = {}
    for entry in entries:
        direction_key = str(entry.get('direction') or entry.get('key') or '').strip().casefold()
        direction = _DIRECTION_ALIASES.get(direction_key)
        if direction:
            clean = dict(entry)
            clean.pop('direction', None)
            clean.pop('key', None)
            directions[direction] = clean
    for direction in ('north', 'south', 'east', 'west'):
        directions.setdefault(direction, {})
    return directions


def _directions_have_content(directions):
    if not isinstance(directions, dict):
        return False
    return any(
        any(str(value.get(key) or '').strip() for key in (
            'regulation_text', 'street_name', 'street_width_m', 'boundary_length_m', 'uses', 'notes'
        )) if isinstance(value, dict) else bool(str(value or '').strip())
        for value in directions.values()
    )


def _normalize_land_document_result(resp_json, text_content='', project_type=''):
    """Normalize multi-parcel document output while keeping legacy flat fields compatible."""
    if not isinstance(resp_json, dict):
        resp_json = {}
    raw_parcels = resp_json.get('parcels')
    if not isinstance(raw_parcels, list) or not raw_parcels:
        legacy = normalize_croquis_fields(resp_json, text_content)
        directions = _normalize_direction_map(
            legacy.get('directions') or resp_json.get('directions') or resp_json.get('directions_table')
        )
        survey_coordinates = _normalize_survey_coordinate_rows(
            _coordinate_rows_from_payload(resp_json), 'P-1'
        )
        parcel = {
            'parcel_id': 'P-1',
            'plot_number': legacy.get('plot_number_croquis', ''),
            'plan_number': legacy.get('plan_number', ''),
            'subdivision_number': legacy.get('subdivision_number', ''),
            'deed_number': legacy.get('deed_number', ''),
            'deed_date': legacy.get('deed_date', ''),
            'area_sqm': legacy.get('croquis_land_area'),
            'approved_financial_area_sqm': None,
            'facades_count': legacy.get('facades_count'),
            'facades_directions': legacy.get('facades_directions', ''),
            'directions': directions,
            'north_direction': legacy.get('north_direction', ''),
            'building_ratio_coverage': legacy.get('building_ratio_coverage', ''),
            'setbacks': legacy.get('setbacks', ''),
            'building_ratio': legacy.get('building_ratio', legacy.get('building_ratio_setbacks', '')),
            'coverage_ratio': legacy.get('coverage_ratio', ''),
            'floor_area_ratio': legacy.get('floor_area_ratio', ''),
            'table_floors': legacy.get('table_floors', ''),
            'building_ratio_setbacks': legacy.get('building_ratio_setbacks', ''),
            'max_floors_height': legacy.get('max_floors_height', ''),
            'allowed_uses': legacy.get('allowed_uses', legacy.get('allowed_uses_restrictions', '')),
            'regulatory_constraints': legacy.get('regulatory_constraints', ''),
            'land_use_status': legacy.get('land_use_status', ''),
            'allowed_uses_restrictions': legacy.get('allowed_uses_restrictions', ''),
                'coordinates': {'lat': None, 'lng': None, 'source': '', 'confidence': ''},
            'survey_coordinates': survey_coordinates,
            'confidence': {},
            'sources': [],
            'summary': legacy.get('land_and_building_summary', ''),
        }
        _normalize_parcel_scalar_fields(parcel, text_content)
        result = dict(legacy)
        result['parcels'] = [parcel]
        result['survey_coordinates'] = survey_coordinates
        result['source_priority'] = ['regulation_table', 'official_regulation', 'croquis', 'building_license']
        result['conflicts'] = resp_json.get('conflicts') if isinstance(resp_json.get('conflicts'), list) else []
        result['document_summary'] = result.get('land_and_building_summary', '')
        strip_regulation_references_from_payload(result)
        return apply_entered_land_use_status(result, project_type)

    normalized_parcels = []
    for index, raw in enumerate(raw_parcels):
        if not isinstance(raw, dict):
            continue
        directions = _normalize_direction_map(
            raw.get('directions') or raw.get('directions_table') or raw.get('regulation_directions')
        )
        if index == 0 and not _directions_have_content(directions):
            directions = _normalize_direction_map(
                resp_json.get('directions') or resp_json.get('directions_table')
            )
        parcel = dict(raw)
        parcel['parcel_id'] = str(raw.get('parcel_id') or raw.get('parcelId') or f'P-{index + 1}')
        parcel['survey_coordinates'] = _normalize_survey_coordinate_rows(
            _coordinate_rows_from_payload(raw), parcel['parcel_id']
        )
        parcel['directions'] = directions
        coords = raw.get('coordinates') if isinstance(raw.get('coordinates'), dict) else {}
        parcel['coordinates'] = {
            'lat': coords.get('lat'), 'lng': coords.get('lng'),
            'source': coords.get('source', ''), 'confidence': coords.get('confidence', '')
        }
        parcel['sources'] = raw.get('sources') if isinstance(raw.get('sources'), list) else []
        parcel['confidence'] = raw.get('confidence') if isinstance(raw.get('confidence'), dict) else {}
        _normalize_parcel_scalar_fields(parcel, text_content)
        normalized_parcels.append(parcel)

    if not normalized_parcels:
        return _normalize_land_document_result({}, text_content)
    result = dict(resp_json)
    result.pop('approved_floor_count', None)
    result.pop('approved_floors', None)
    result.pop('approved_coverage_ratio', None)
    result['parcels'] = normalized_parcels
    aggregate_coordinates = [row for parcel in normalized_parcels for row in parcel.get('survey_coordinates', [])]
    top_regulation_rows = _regulation_coordinate_rows_from_payload(resp_json)
    top_coordinates = _normalize_survey_coordinate_rows(
        top_regulation_rows or _coordinate_rows_from_payload(resp_json), normalized_parcels[0]['parcel_id']
    )
    if top_regulation_rows:
        aggregate_coordinates = top_coordinates
        normalized_parcels[0]['survey_coordinates'] = top_coordinates
    elif not aggregate_coordinates:
        aggregate_coordinates = top_coordinates
    result['survey_coordinates'] = aggregate_coordinates
    result['source_priority'] = ['regulation_table', 'official_regulation', 'croquis', 'building_license']
    result['conflicts'] = resp_json.get('conflicts') if isinstance(resp_json.get('conflicts'), list) else []
    # One canonical narrative: keep document_summary as a mirror for older stored drafts.
    summary = str(resp_json.get('land_and_building_summary') or resp_json.get('document_summary') or '').strip()
    if not summary:
        summary = str(normalized_parcels[0].get('summary') or '').strip()
    result['land_and_building_summary'] = summary
    result['document_summary'] = summary
    first = normalized_parcels[0]
    legacy_map = {
        'plot_number_croquis': first.get('plot_number', ''),
        'plan_number': first.get('plan_number', ''),
        'subdivision_number': first.get('subdivision_number', ''),
        'deed_number': first.get('deed_number', ''),
        'deed_date': first.get('deed_date', ''),
        'croquis_land_area': first.get('area_sqm'),
        'facades_count': first.get('facades_count'),
        'facades_directions': first.get('facades_directions', ''),
        'north_direction': first.get('north_direction', ''),
        'building_ratio_coverage': first.get('building_ratio_coverage') or land_rule_text(first),
        'setbacks': first.get('setbacks', ''),
        'building_ratio_setbacks': first.get('building_ratio_setbacks') or land_rule_text(first, include_setbacks=True),
        'max_floors_height': first.get('max_floors_height', ''),
        'allowed_uses': first.get('allowed_uses', ''),
        'regulatory_constraints': first.get('regulatory_constraints', ''),
        'land_use_status': first.get('land_use_status', ''),
        'allowed_uses_restrictions': first.get('allowed_uses_restrictions', ''),
    }
    for key, value in legacy_map.items():
        if value not in (None, ''):
            result.setdefault(key, value)
    strip_regulation_references_from_payload(result)
    return apply_entered_land_use_status(result, project_type)


def _build_land_extraction_diagnostics(result, document_processing=None):
    parcels = result.get('parcels') if isinstance(result, dict) else []
    parcels = parcels if isinstance(parcels, list) else []
    coordinate_rows = result.get('survey_coordinates') if isinstance(result, dict) else []
    if not isinstance(coordinate_rows, list):
        coordinate_rows = []
    first_parcel = parcels[0] if parcels and isinstance(parcels[0], dict) else {}
    if not coordinate_rows:
        coordinate_rows = first_parcel.get('survey_coordinates') if isinstance(first_parcel.get('survey_coordinates'), list) else []
    directions = first_parcel.get('directions') if isinstance(first_parcel.get('directions'), dict) else {}
    direction_values = 0
    for direction in ('north', 'south', 'east', 'west'):
        value = directions.get(direction)
        if isinstance(value, dict):
            has_value = any(str(value.get(key) or '').strip() for key in (
                'regulation_text', 'street_name', 'street_width_m', 'boundary_length_m', 'uses', 'notes'
            ))
        else:
            has_value = bool(str(value or '').strip())
        direction_values += int(has_value)
    complete_coordinates = sum(
        bool(str(row.get('eastings') or '').strip() and str(row.get('northings') or '').strip())
        for row in coordinate_rows if isinstance(row, dict)
    )
    conflicts = result.get('conflicts') if isinstance(result, dict) else []
    conflicts = conflicts if isinstance(conflicts, list) else []
    missing_tables = []
    if not coordinate_rows:
        missing_tables.append('إحداثيات التنظيم')
    if direction_values < 4:
        missing_tables.append('بموجب التنظيم')
    if not missing_tables:
        status = 'complete'
    elif coordinate_rows or direction_values:
        status = 'partial'
    else:
        status = 'empty'
    return {
        'status': status,
        'coordinates_rows': len(coordinate_rows),
        'coordinates_complete_rows': complete_coordinates,
        'directions_rows': 4,
        'directions_with_values': direction_values,
        'missing_tables': missing_tables,
        'conflict_count': len(conflicts),
        'coordinates_table_name': str(first_parcel.get('coordinates_table_name') or ''),
        'document_processing': document_processing if isinstance(document_processing, list) else [],
    }


LAND_ANALYSIS_SITE_CONTEXT_KEYS = (
    'location_address', 'location_detail', 'location_lat', 'location_lng', 'location_polygon',
    'city', 'main_roads', 'secondary_roads', 'nearby_landmarks', 'nearby_landmarks_data',
    'city_landmarks', 'catchment_areas', 'population_density', 'population_density_source',
    'land_area', 'built_area', 'building_system', 'infrastructure', 'zoning_code', 'land_use',
)


def build_land_analysis_site_context(data, tenant_id, lat, lng):
    source = data.get('siteContext') if isinstance(data.get('siteContext'), dict) else {}
    context = {}
    for key in LAND_ANALYSIS_SITE_CONTEXT_KEYS:
        value = source.get(key)
        if value in (None, '', [], {}):
            value = data.get(key)
        if value not in (None, '', [], {}):
            context[key] = value
    context['location_address'] = data.get('locationAddress') or data.get('location_address') or context.get('location_address') or ''
    context['location_lat'] = lat
    context['location_lng'] = lng
    warnings = []
    needs_enrichment = any(context.get(key) in (None, '', [], {}) for key in (
        'location_detail', 'main_roads', 'nearby_landmarks', 'city_landmarks'))
    if data.get('includeMapContext') is True and needs_enrichment:
        try:
            enriched, nearby_items, *_rest, diagnostics = _collect_site_fields(context, tenant_id, lat, lng)
            for key, value in (enriched or {}).items():
                if value not in (None, '', [], {}) and context.get(key) in (None, '', [], {}):
                    context[key] = value
            if nearby_items and not context.get('nearby_landmarks_data'):
                context['nearby_landmarks_data'] = nearby_items
            warnings.extend(value for value in (
                (diagnostics or {}).get('nearby_landmarks_error'),
                (diagnostics or {}).get('nearby_landmarks_warning'),
                (diagnostics or {}).get('city_landmarks_error'),
                (diagnostics or {}).get('city_landmarks_warning'),
            ) if value)
        except Exception as error:
            warnings.append('تعذر استكمال بعض بيانات الموقع والخرائط: ' + str(error))
    return context, warnings


_LAND_JOB_LOCK = threading.Lock()


def _land_job_dir(tenant_id):
    path = os.path.join(UPLOADS_DIR, '.land_jobs', str(tenant_id))
    os.makedirs(path, exist_ok=True)
    return path


def _land_job_path(tenant_id, job_id):
    return os.path.join(_land_job_dir(tenant_id), f'{job_id}.json')


def _write_land_job(tenant_id, job_id, payload):
    path = _land_job_path(tenant_id, job_id)
    payload = dict(payload)
    payload['updatedAt'] = time.time()
    body = json.dumps(payload, ensure_ascii=False)
    with _LAND_JOB_LOCK:
        last_error = None
        for _ in range(8):
            try:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(body)
                return
            except OSError as error:
                last_error = error
                time.sleep(0.03)
        if last_error:
            raise last_error


def _read_land_job(tenant_id, job_id):
    path = _land_job_path(tenant_id, job_id)
    if not os.path.isfile(path):
        return None
    with _LAND_JOB_LOCK:
        try:
            with open(path, encoding='utf-8') as fh:
                payload = json.load(fh)
        except Exception:
            return None
    return payload if isinstance(payload, dict) else None


def _land_job_worker(app, tenant_id, data, job_id):
    """Run the long land extraction off the HTTP request so the hosting proxy cannot 404 it."""
    with app.app_context():
        _write_land_job(tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري تحليل المستندات والاشتراطات...',
        })
        try:
            with app.test_request_context('/api/extract-croquis', method='POST', json=data):
                g.tenant_id = tenant_id
                response = _execute_extract_croquis()
            payload = response.get_json(silent=True) if response is not None else {}
            if not isinstance(payload, dict):
                payload = {}
            payload.pop('rawText', None)
            status = 'completed' if payload.get('success') else 'failed'
            _write_land_job(tenant_id, job_id, {
                **payload,
                'status': status,
                'httpStatus': getattr(response, 'status_code', 500),
                'message': payload.get('error') or 'اكتمل التحليل',
            })
        except Exception as exc:
            _write_land_job(tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'error': f'حدث خطأ في قراءة ملف الكروكي: {exc}',
                'failureReason': 'job_failed',
            })


@app.route('/api/extract-croquis', methods=['POST'])
@require_auth
def api_extract_croquis():
    """Accept a land-analysis request.

    The hosting proxy fabricates a 404 if this route stays open for the whole
    vision + regulation pipeline. Production therefore queues the work and
    returns immediately; the client polls GET /api/extract-croquis/<job_id>.
    Tests keep the original synchronous response unless they pass background=true.
    """
    data = request.json or {}
    use_background = (not current_app.config.get('TESTING')) or bool(data.get('background'))
    if not use_background:
        return _execute_extract_croquis()
    job_id = str(_uuid.uuid4())
    tenant_id = g.tenant_id
    _write_land_job(tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'message': 'تم استلام طلب التحليل',
    })
    threading.Thread(
        target=_land_job_worker,
        args=(current_app._get_current_object(), tenant_id, data, job_id),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'message': 'بدأ التحليل في الخلفية',
    }), 202


@app.route('/api/extract-croquis/<job_id>', methods=['GET'])
@require_auth
def api_extract_croquis_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_land_job(g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'error': 'مهمة التحليل غير موجودة',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(job)


def _execute_extract_croquis():
    """Extract one or more land documents together using vision AI."""
    import traceback
    try:
        data = request.json or {}
        location_address = str(
            data.get('locationAddress') or data.get('location_address') or ''
        ).strip()
        try:
            location_lat = float(data.get('locationLat') or data.get('location_lat'))
            location_lng = float(data.get('locationLng') or data.get('location_lng'))
        except (TypeError, ValueError):
            location_lat = location_lng = None
        if (
            not location_address.startswith('http')
            or location_lat is None or location_lng is None
            or not (-90 <= location_lat <= 90)
            or not (-180 <= location_lng <= 180)
        ):
            return jsonify({
                'success': False,
                'error': 'رابط Google Maps صالح وإحداثيات الموقع مطلوبان قبل بدء تحليل الأرض والكروكي',
                'failureReason': 'location_required',
            }), 400
        legacy_file_data = data.get('fileData') or data.get('croquis_file') or ''
        if not data.get('documents') and not legacy_file_data:
            return jsonify({'success': False, 'error': 'يرجى رفع صورة الأرض أو الكروكي أو الرخصة أولاً'}), 400

        site_context, site_context_warnings = build_land_analysis_site_context(
            data, g.tenant_id, location_lat, location_lng)
        regulation_query = ' '.join(str(data.get(key) or '') for key in (
            'zoningCode', 'zoning_code', 'projectType', 'city', 'landUse'
        )).strip()
        project_context_fields = (
            ('اسم المشروع', 'projectName'),
            ('نوع المشروع', 'projectType'),
            ('مرحلة المشروع الحالية', 'projectStage'),
            ('رابط Google Maps', 'locationAddress'),
            ('خط العرض', 'locationLat'),
            ('خط الطول', 'locationLng'),
        )
        project_context_block = '\n'.join(
            f'- {label}: {str(data.get(key) or "").strip() or "غير مدخل"}'
            for label, key in project_context_fields
        ) + '\nبيانات الموقع والخرائط المحللة:\n' + json.dumps(
            site_context, ensure_ascii=False, indent=2, default=str)

        documents = []
        raw_documents = data.get('documents')
        if isinstance(raw_documents, list) and len(raw_documents) > 10:
            return jsonify({'success': False, 'error': 'الحد الأقصى لتحليل الملفات معًا هو 10 ملفات'}), 400
        if isinstance(raw_documents, list):
            for index, item in enumerate(raw_documents):
                if not isinstance(item, dict):
                    continue
                file_data = item.get('fileData') or item.get('data') or ''
                file_id = item.get('fileId')
                if not file_data and file_id:
                    stored = db.get_project_file(g.tenant_id, str(file_id))
                    if stored and stored.get('storage_path') and os.path.isfile(stored['storage_path']):
                        with open(stored['storage_path'], 'rb') as source:
                            encoded = base64.b64encode(source.read()).decode('ascii')
                        file_data = f"data:{stored.get('mime_type') or 'application/octet-stream'};base64,{encoded}"
                if not file_data:
                    continue
                documents.append({
                    'key': str(item.get('key') or item.get('fileType') or f'document_{index + 1}'),
                    'filename': os.path.basename(str(item.get('filename') or item.get('originalName') or f'document_{index + 1}')),
                    'fileData': file_data,
                    'mimeType': item.get('mimeType') or ('application/pdf' if 'application/pdf' in file_data else 'image/*'),
                })
        if not documents:
            file_data = data.get('fileData') or data.get('croquis_file') or ''
            if file_data:
                documents = [{
                    'key': 'croquis',
                    'filename': 'croquis.pdf' if 'application/pdf' in file_data else 'croquis-image',
                    'fileData': file_data,
                    'mimeType': 'application/pdf' if 'application/pdf' in file_data else 'image/*',
                }]
        if not documents:
            return jsonify({'success': False, 'error': 'يرجى رفع صورة الأرض أو الكروكي أو الرخصة أولاً'}), 400

        system_prompt = (
            "أنت مهندس مساح وخبير عقاري ومدقق مستندات تنظيمية. حلل كل الملفات المرفقة معًا، مع الحفاظ على هوية كل ملف ومصدر كل معلومة.\n"
            "ملفا الاشتراطات الرسميان اشتراطات1 واشتراطات2 متاحان لك بمحتواهما الكامل؛ استخدمهما كاملين ولا تعتمد على جزء أو صفحات منتقاة فقط.\n"
            "أعد JSON فقط بدون Markdown. لا تخترع قيمة غير مقروءة؛ استخدم null أو نصًا فارغًا، وسجل التعارضات بدل اختيار قيمة من نفسك.\n"
            "أولوية المصادر إلزامية: جدول التنظيم الرسمي أولًا، ثم أي مرجع تنظيمي رسمي، ثم الكروكي، ثم رخصة البناء. إذا ظهرت جداول متعددة للإحداثيات أو الاتجاهات، استخدم جدول التنظيم واربط كل قيمة بـ source=regulation_table، وسجل البدائل والتعارضات في conflicts.\n"
            "ستجد في مستندات PDF صورة كاملة للصفحة وقصاصات مكبرة عالية الدقة، وقد توجد قصاصات بديلة باتجاه دوران آخر. استخدم النسخة التي يكون النص فيها أفقيًا واضحًا، ولا تعتبر النسخة المقلوبة مصدرًا مستقلًا.\n"
            "إذا وجدت أكثر من قطعة أرض، أعد كل قطعة داخل parcels منفصلة ولا تدمج مساحاتها أو حدودها.\n"
            "استخرج جدول الاتجاهات الأربعة بشكل مستقل من جدول الجهات أو الحدود الذي يوضح «بموجب التنظيم» أولًا، وليس من وصف عام في الرخصة أو الكروكي. اقرأ أسماء الشوارع وعروضها وأطوال الحدود والواجهات من صورة الجدول.\n"
            "بالنسبة للإحداثيات، إذا وجدت أكثر من جدول فافصل الجداول أولًا داخل coordinate_tables، وضع عنوان كل جدول في table_name وصفوفه في rows.\n"
            "الجدول المطلوب حصريًا هو الجدول الذي عنوانه «إحداثيات التنظيم» أو «جدول إحداثيات التنظيم» أو «احداثيات التنظيم». جدول «إحداثيات الموقع» أو «إحداثيات الصك» ليس بديلًا ولا يجوز أخذ أي صف منه.\n"
            "بعد فصل الجداول، انسخ صفوف جدول إحداثيات التنظيم وحده إلى regulation_coordinates ثم إلى survey_coordinates بنفس الترتيب. لا تخلط أو تنتقي صفوفًا من الجدولين.\n"
            "إذا لم تجد جدول إحداثيات التنظيم أو لم يكن عنوانه وصفوفه مقروءة بوضوح، أعد regulation_coordinates وsurvey_coordinates فارغين وسجل تعارضًا يوضح السبب، ولا تستنتج الإحداثيات من الحدود أو الاتجاهات.\n"
            "استخرج من جدول إحداثيات التنظيم كما هو: رقم القطعة، رقم النقطة، الشرقيات، الشماليات، بدون تحويل إلى latitude/longitude أو حساب أي نقطة.\n"
            "الصيغة المطلوبة:\n"
            "{\n"
            '  "parcels": [{\n'
            '    "parcel_id": "P-1", "plot_number": "", "plan_number": "", "subdivision_number": "",\n'
            '    "deed_number": "", "deed_date": "", "area_sqm": null,\n'
            '    "facades_count": null, "facades_directions": "",\n'
            '    "directions": {\n'
            '      "north": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "source": "regulation_table"},\n'
            '      "south": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "source": "regulation_table"},\n'
            '      "east": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "source": "regulation_table"},\n'
            '      "west": {"regulation_text": "", "street_name": "", "street_width_m": null, "boundary_length_m": null, "uses": "", "source": "regulation_table"}\n'
            '    },\n'
            '    "north_direction": "", "setbacks": "", "building_ratio": "", "coverage_ratio": "",\n'
            '    "building_ratio_coverage": "", "floor_area_ratio": "", "table_floors": "", "max_floors_height": "",\n'
            '    "parking_requirements": "", "entrances_exits_requirements": "",\n'
            '    "allowed_uses": "", "land_use_status": "", "regulatory_constraints": "",\n'
            '    "allowed_uses_restrictions": "", "zoning_code": "",\n'
            '    "coordinates": {"lat": null, "lng": null, "source": "", "confidence": ""},\n'
            '    "coordinates_table_name": "إحداثيات التنظيم", "coordinates_table_source_page": "",\n'
            '    "coordinate_tables": [{"table_name": "", "rows": [{"point": "", "eastings": "", "northings": "", "source": ""}]}],\n'
            '    "regulation_coordinates": [{"point": "", "eastings": "", "northings": "", "source": "regulation_table"}],\n'
            '    "survey_coordinates": [{"point": "", "eastings": "", "northings": "", "source": "regulation_table"}],\n'
            '    "confidence": {}, "sources": [], "summary": ""\n'
            '  }],\n'
            '  "coordinate_tables": [], "regulation_coordinates": [],\n'
            '  "survey_coordinates": [], "source_priority": ["regulation_table", "official_regulation", "croquis", "building_license"],\n'
            '  "conflicts": [{"field": "", "description": ""}],\n'
            '  "land_and_building_summary": ""\n'
            "}\n"
            "قواعد إلزامية لأرقام الهوية — لا تخلط بينها أبدًا:\n"
            "- plot_number: رقم قطعة الأرض وحده (مثل 9991). لا تضع فيه رقم المخطط ولا رقم القسم ولا كلمة (قطعة).\n"
            "- plan_number: رقم المخطط وحده (مثل 3/س/125).\n"
            "- subdivision_number: رقم القسم أو الجزء إن وُجد فقط، وإلا اتركه فارغًا. لا تضعه في plot_number.\n"
            "- إذا كان المستند يذكر رقمًا واحدًا فقط ولم يوضح نوعه، اتركه في الحقل المؤكد فقط وسجّل الغموض في conflicts.\n"
             "قواعد إلزامية للصك:\n"
             "- deed_number: رقم الصك رقميًا فقط.\n"
             "- deed_date: تاريخ إصدار الصك كما هو مكتوب (هجري أو ميلادي) بصيغة YYYY/MM/DD، وبيّن نوع التقويم في summary. لا تخلطه مع تاريخ الكروكي أو تاريخ الرخصة.\n"
             "قاعدة حاسمة لمساحة الأرض حسب الكروكي (area_sqm / croquis_land_area):\n"
             "- أخرج فقط المساحة المكتوبة في جدول التنظيم بجوار عبارة «بموجب التنظيم» لكل قطعة. هذه هي مساحة الأرض المعتمدة لهذا الحقل.\n"
             "- إذا وُجدت مساحات متعددة مثل مساحة الصك، أو المساحة المقاسة على الطبيعة، أو الرفع المساحي، أو مساحة حدود مختلفة، فلا تستخدم أيًا منها بدل مساحة «بموجب التنظيم».\n"
             "- استخدم مساحة «بموجب التنظيم» وحدها لاختيار شريحة جدول الاشتراطات، وسجّل أي مساحة أخرى في conflicts أو summary كمعلومة متعارضة فقط.\n"
             "- إذا لم تكن مساحة «بموجب التنظيم» مقروءة بوضوح، اترك area_sqm فارغًا وسجّل ذلك في conflicts، ولا تخمّن أو تحسب مساحة بديلة.\n"
             "قواعد إلزامية للواجهات — الواجهة هي الحد المطل على شارع فقط:\n"
            "- لكل قطعة أربعة حدود دائمًا، لكن الواجهات هي الحدود المطلة على شوارع وحدها. "
            "الحد المجاور لقطعة أو جار ليس واجهة.\n"
            "- facades_count: عدد الحدود المطلة على شوارع فقط، رقم صحيح (1 إلى 4). "
            "يُمنع منعًا تامًا كتابة أي كلمة اتجاه هنا.\n"
            "- facades_directions: اتجاهات تلك الواجهات فقط (مثل: شمالية، غربية). "
            "لا تكتب الاتجاهات الأربعة كلها إلا إذا كانت القطعة فعلًا مطلة على أربعة شوارع.\n"
            "- في directions املأ street_name و street_width_m للحدود المطلة على شوارع، "
            "واذكر في uses أن الحد يجاور قطعة/جار للحدود غير المطلة على شارع.\n"
            "قواعد منع التكرار:\n"
            "- لا تكرر نفس المعلومة في أكثر من حقل. building_ratio_coverage لنسب البناء والتغطية وFAR والأدوار، وsetbacks للارتدادات فقط.\n"
            "- allowed_uses للاستخدامات وحالة توافق نوع المشروع، وregulatory_constraints للقيود فقط.\n"
            "- أطوال الحدود وأسماء الشوارع تُكتب داخل directions فقط، ولا تُعاد في summary كقائمة.\n"
            "قواعد الاشتراطات — ممنوع إعادة رقم مجرد أو إحالة المستخدم إلى مكان داخل ملف:\n"
            "- zoning_code: كود التنظيم/الاستخدام كما هو في الرخصة أو جدول التنظيم إن وُجد.\n"
            "- building_ratio: اكتب النسبة بجملة كاملة توضّح مجال تطبيقها، ولا تكتب «60%» وحدها. لا تذكر اسم الملف أو رقم الصفحة في القيمة.\n"
            "- coverage_ratio: نسبة التغطية إن ذُكرت منفصلة عن نسبة البناء، وإلا اتركها فارغة ولا تكرر نسبة البناء فيها.\n"
            "- building_ratio_coverage: اجمع نسبة البناء والتغطية وFAR وعدد الأدوار المرتبط بشريحة مساحة الأرض في قيمة مفهومة، بدون إحالات إلى الصفحات.\n"
            "- floor_area_ratio: معامل مسطح البناء (FAR) رقمًا مع شرح نطاق تطبيقه إن وُجد.\n"
            "- table_floors: عدد الأدوار المقابل لمساحة هذه الأرض، مع ذكر شريحة المساحة أو المحور بالكلمات فقط.\n"
            "- setbacks: الارتدادات الأربعة كل واحد برقمه بالمتر (أمامي/خلفي/جانبي أيمن/جانبي أيسر). إن لم تجدها فاكتب «غير محددة في المرجع المتاح» ولا تخترع أرقامًا.\n"
            "- parking_requirements: استخرج اشتراطات المواقف كاملة: العدد أو النسبة، نوع الاستخدام، وأبعاد الموقف أو المسار إن ذُكرت، دون ذكر أرقام الصفحات. إذا لم توجد فاكتب «غير محددة في المرجع المتاح».\n"
            "- entrances_exits_requirements: استخرج اشتراطات مداخل ومخارج السيارات والمشاة والخدمات والتحميل والفصل بين المداخل إن ذُكرت، دون ذكر أرقام الصفحات. إذا لم توجد فاكتب «غير محددة في المرجع المتاح».\n"
            "- allowed_uses: اكتب قائمة الاستخدامات المسموحة تنظيميًا لهذه الأرض من جدول التنظيم وملفي الاشتراطات "
            "(مثل: سكني، تجاري، إداري، فندقي). لا تكتب حالة توافق نوع المشروع، ولا تكتب «حالة استخدام المشروع». "
            "إذا لم تُستخرج استخدامات واضحة فاكتب «غير محددة في المرجع المتاح».\n"
            "- land_use_status: أعد قيمة واحدة فقط بعد مقارنة نوع المشروع المدخل في بيانات العميل مع الاستخدامات المستخرجة: «مسموح» أو «غير مسموح» أو «غير محسوم». "
            "إذا كان نوع المشروع مكتوبًا في بيانات العميل فلا تقل إنه غير مدخل. لا تستخدم «مسموح» إذا لم يوجد دليل كافٍ.\n"
            "- regulatory_constraints: اذكر القيود التنظيمية المنطبقة على الموقع والمشروع، واجمع فيها المواقف والمداخل والمخارج والتحميل والخدمات عند وجودها، دون تكرار قائمة الاستخدامات.\n"
            "- allowed_uses_restrictions: اجمع allowed_uses وregulatory_constraints للتوافق مع البيانات القديمة فقط.\n"
            "- استخدم مساحة الأرض المستخرجة لاختيار الشريحة الصحيحة من جدول التنظيم؛ الجداول مفتاحها مساحة الأرض ونوع المحور/المنطقة.\n"
            "- لا تنسب اشتراطات إلى مدينة أو أمانة إلا إذا كانت المدينة ومصدر اللائحة واضحين في الملفات أو في المرجع المرفق.\n"
            "- لا تكتب في أي حقل عبارات مثل «صفحة كذا» أو «راجع الملف» أو اسم ملف كمصدر؛ اكتب الاشتراط نفسه مباشرة.\n"
            "قواعد التعارضات (conflicts) — لا تُعرض للمستخدم مباشرة:\n"
            "- عند اختلاف قيمة بين مستندين، سجّل التعارض هنا بجملة واحدة بدل اختيار قيمة من نفسك بصمت.\n"
            "- الشرح المفصّل للتعارض وأثره يُكتب داخل land_and_building_summary في فقرة المخاطر.\n"
            "- إذا لا توجد تعارضات أعد قائمة فارغة.\n"
            "قواعد الملخص (land_and_building_summary):\n"
            "- نص عربي مسترسل من ٣ إلى ٥ فقرات (١٨٠ كلمة على الأقل) وليس قائمة حقول مفصولة بشرطات.\n"
            "- لا تُعد سرد الأرقام التي وردت في الحقول؛ اربطها وحلّلها باختصار.\n"
            "- يغطي بالترتيب: (١) هوية القطعة وموقعها وصكها، (٢) المساحات والحدود والاتجاهات والواجهات، (٣) اشتراطات البناء، (٤) الاستخدامات المسموحة وحالة توافق نوع المشروع، (٥) القيود والمواقف والمداخل والمخارج، (٦) الفرص التطويرية المستنبطة من الاشتراطات، (٧) المخاطر والتعارضات وما يحتاج مراجعة.\n"
            "- يجب أن يذكر الملخص بوضوح الارتدادات والمواقف والمداخل والمخارج حتى لو وردت التفاصيل في الحقول الأخرى.\n"
            "- اربط ملاءمة الاشتراطات بنوع المشروع ومرحلته المدخلين، ولا تستبدلها بتحليل عام منفصل عن المشروع.\n"
            "- لا تذكر أرقام الصفحات أو أسماء الملفات أو مكان الاشتراط داخل الملخص؛ اذكر الاشتراط نفسه مباشرة.\n"
            "- اذكر صراحة أي معلومة غير متوفرة بدل تخطيها بصمت.\n"
            "ملاحظة: لا تُخرج حقل المساحة المعتمدة للدراسة المالية إطلاقًا؛ العميل هو من يحددها."
        )

        raw_resp = ""
        response_finish_reason = None
        model_error = ''
        vision_warnings = list(site_context_warnings)
        document_processing = []
        regulation_evidence_metadata = []
        if OPENROUTER_KEY:
            vision_parts = []
            document_descriptions = []
            per_document_budget = PDF_VISION_MAX_TOTAL_BYTES // max(1, len(documents))
            for doc in documents:
                try:
                    vision_diagnostics = {}
                    parts, warnings, page_count, mode = _prepare_document_vision_parts(
                        doc, budget=per_document_budget, diagnostics=vision_diagnostics)
                    vision_parts.extend(parts)
                    vision_warnings.extend(warnings)
                    processing = {
                        'filename': doc['filename'],
                        'mode': mode,
                        'page_count': page_count,
                        'dpi': PDF_VISION_DPI if mode == 'pdf_rendered' else None
                    }
                    processing.update({
                        key: vision_diagnostics[key]
                        for key in ('page_rotations', 'rotated_page_count', 'tile_count', 'image_count', 'encoded_base64_bytes')
                        if key in vision_diagnostics
                    })
                    document_processing.append(processing)
                    document_descriptions.append(f"- {doc['key']}: {doc['filename']} ({mode}, {page_count} صفحة/صورة)")
                except Exception as render_error:
                    print(f"[EXTRACT LAND DOCUMENTS RENDER ERROR] {doc['filename']}: {render_error}")
                    return jsonify({
                        'success': False,
                        'error': f'تعذر تجهيز المستند بصريًا: {doc["filename"]}. لم يتم إرسال PDF كملف عادي حتى لا ينتج AI بيانات غير دقيقة.',
                        'documentProcessing': document_processing,
                        'details': str(render_error)
                    }), 422

            request_facts = {
                'zoning_code': data.get('zoningCode') or data.get('zoning_code') or site_context.get('zoning_code') or '',
                'land_use': data.get('landUse') or data.get('land_use') or site_context.get('land_use') or '',
                'city': data.get('city') or site_context.get('city') or '',
                'project_type': data.get('projectType') or '',
                'location_address': data.get('locationAddress') or data.get('location_address') or '',
                'location_lat': data.get('locationLat') or data.get('location_lat') or location_lat,
                'location_lng': data.get('locationLng') or data.get('location_lng') or location_lng,
            }
            facts_prompt = (
                "أنت مستخرج حقائق أولي من صور مستندات الأرض والكروكي. أعد JSON فقط بهذا الشكل: "
                '{"site_facts":{"plot_number":"","area_sqm":null,"zoning_code":"",'
                '"land_use":"","city":"","project_type":"","axis_type":"","building_type":"",'
                '"location_address":"","location_lat":null,"location_lng":null},'
                '"uncertainties":[]} '
                "اقرأ الصور فقط ولا تستخدم أي لائحة أو تخمين. area_sqm يجب أن تكون مساحة «بموجب التنظيم» إن ظهرت، "
                "وإذا لم تكن واضحة اتركها null. هذا استخراج تمهيدي لا يكتب الملخص النهائي."
            )
            facts_payload = [{
                'type': 'text',
                'text': facts_prompt + '\nالمستندات المرفقة:\n' + '\n'.join(document_descriptions)
            }] + vision_parts
            facts_result, facts_cap, facts_error = _run_land_json_stage(
                'site_facts', facts_prompt, facts_payload,
                LAND_FACTS_MAX_TOKENS, LAND_FACTS_MIN_TOKENS, LAND_FACTS_MAX_TOKENS * 2
            )
            if facts_error:
                vision_warnings.append('تعذر استخراج حقائق الكروكي الأولية؛ تم استخدام بيانات المشروع المدخلة فقط.')
                print(f'[LAND ANALYSIS STAGE ERROR] site_facts cap={facts_cap} {facts_error}')
            site_facts = _extract_land_site_facts(facts_result, request_facts)
            regulation_query = ' '.join(str(value) for value in site_facts.values() if value not in (None, ''))
            try:
                evidence_package, evidence_warnings = search_official_regulations_evidence(
                    regulation_query, site_facts)
            except Exception as evidence_error:
                evidence_package = {'context': '', 'documents': [], 'table_pages': []}
                evidence_warnings = [f'تعذر تجهيز أدلة الاشتراطات: {evidence_error}']
            vision_warnings.extend(evidence_warnings)
            evidence_results = []
            for source in evidence_package.get('documents', []):
                source_name = source.get('name') or 'ملف اشتراطات'
                source_tables = [
                    entry for entry in evidence_package.get('table_pages', [])
                    if entry.get('name') == source_name
                ]
                source_for_evidence = {**source, 'table_pages': source_tables}
                extracted_evidence = _extract_full_regulation_evidence(source_for_evidence, site_facts)
                vision_warnings.extend(extracted_evidence.get('warnings', []))
                if not extracted_evidence.get('evidence') and not extracted_evidence.get('uncertainties'):
                    if not source.get('context') and not source_tables:
                        vision_warnings.append(f'لم يتوفر محتوى قابل للقراءة في {source_name}؛ لن يتم تخمين اشتراطاته.')
                    evidence_results.append({
                        'source_file': source_name,
                        'evidence': {},
                        'error': 'لا يوجد محتوى قابل للقراءة أو تعذر استخراج أدلة',
                    })
                    continue
                evidence_results.append({
                    'source_file': source_name,
                    'evidence': extracted_evidence.get('evidence', []),
                    'uncertainties': extracted_evidence.get('uncertainties', []),
                })
            regulation_evidence_metadata = [
                {
                    'name': source.get('name'),
                    'text_pages': source.get('text_pages', []),
                    'table_pages': source.get('table_pages', []),
                }
                for source in evidence_package.get('documents', [])
            ]
            print(
                f"[REGULATION EVIDENCE] documents={len(regulation_evidence_metadata)} "
                f"text_chars={sum(len(source.get('context') or '') for source in evidence_package.get('documents', []))} "
                f"table_pages={len(evidence_package.get('table_pages', []))}"
            )

            instructions = (
                "لديك نوعان من المدخلات، لا تخلط بينهما:\n"
                "١) مستندات العميل (الصك/الكروكي/الرخصة): مُرسلة صورًا عالية الدقة. اقرأها بصريًا فقط "
                "ولا تعتمد على OCR أو نص مستخرج، واقرأ جداولها من الصورة نفسها.\n"
                "٢) نتائج استخلاص مبنية على المحتوى الكامل لملفي اشتراطات1 واشتراطات2، بما في ذلك جداول كل ملف. "
                "استخدم القواعد التي تنطبق على حقائق الموقع فقط، ولا تخترع قاعدة غير موجودة في المحتوى الكامل.\n"
                "أولوية جدول التنظيم الرسمية مطلقة عند التعارض، وخاصة لجدول الإحداثيات وجدول الاتجاهات. "
                "لا تخلط بين شرقيات/شماليات المساحية وبين latitude/longitude. لا تذكر أرقام الصفحات أو أسماء الملفات في أي قيمة للمستخدم.\n"
            )
            regulation_block = (
                "نتائج استخلاص الاشتراطات من المحتوى الكامل للملفين:\n"
                + json.dumps(evidence_results, ensure_ascii=False)
                + "\n\n"
                if evidence_results else
                "تنبيه: لم تتوفر نتائج قابلة للاستخدام من الملفين كاملين. لا تخترع اشتراطات، وسجّل ذلك في conflicts.\n\n"
            )
            user_content = [{
                "type": "text",
                "text": instructions
                        + "بيانات المعلومات الأساسية ورؤية المشروع التي أدخلها العميل:\n"
                        + project_context_block + "\n\n"
                        + "حقائق الموقع الأولية المستخرجة من الكروكي:\n"
                        + json.dumps(site_facts, ensure_ascii=False) + "\n\n"
                        + "استخدم هذه البيانات كسياق فعلي لربط الملخص بالمشروع، ولا تنسبها إلى الصك أو الكروكي أو اللائحة إذا لم يذكر مصدرها.\n\n"
                        + regulation_block
                        + "مستندات العميل المرفقة:\n" + "\n".join(document_descriptions)
            }] + vision_parts

            try:
                res, used_cap, provider_error = _call_land_analysis_model(
                    system_prompt, user_content, LAND_ANALYSIS_MAX_TOKENS)
                if _has_chat_choices(res):
                    raw_resp = _get_chat_response_text(res)
                    choices = res.get('choices') if isinstance(res, dict) else []
                    response_finish_reason = choices[0].get('finish_reason') if choices and isinstance(choices[0], dict) else None
                    print(f"[EXTRACT LAND DOCUMENTS] analyzed {len(documents)} document(s), "
                          f"cap={used_cap}, finish_reason={response_finish_reason}, chars={len(raw_resp)}")
                else:
                    model_error = provider_error
                    print(f"[EXTRACT LAND DOCUMENTS ERROR] cap={used_cap} {provider_error}")
            except Exception as model_err:
                model_error = str(model_err)
                print(f"[EXTRACT LAND DOCUMENTS EXCEPTION] {model_err}")

        # Partial JSON is never accepted: half a parcel is worse than no parcel. But the failure
        # must say so plainly, otherwise a rejected re-analysis just looks like "nothing changed".
        if response_finish_reason == 'length':
            print(f"[EXTRACT LAND DOCUMENTS TRUNCATED] {len(raw_resp)} chars at cap {used_cap}")
            return jsonify({
                'success': False,
                'error': (f'انقطعت استجابة الذكاء الاصطناعي عند الحد الأقصى ({used_cap} رمز) '
                          'فلم يُعتمد أي حقل، ولهذا لم تتغير البيانات. أعد المحاولة، '
                          'أو ارفع LAND_ANALYSIS_MAX_TOKENS إن تكرر ذلك.'),
                'failureReason': 'truncated',
                'documentProcessing': document_processing
            }), 503
        if not raw_resp.strip():
            # Report what the provider actually said. "Check your API keys" was misleading when the
            # real cause was an insufficient credit balance for the reserved max_tokens.
            insufficient_credit = 'afford' in model_error or 'credit' in model_error.lower()
            blocked_format = bool(_JSON_MODE_BLOCK_RE.search(model_error or ''))
            if insufficient_credit:
                message = ('رصيد OpenRouter لا يكفي لهذا الطلب، فلم يُعتمد أي حقل ولم تتغير البيانات. '
                           'أضف رصيدًا أو قلّل LAND_ANALYSIS_MAX_TOKENS.')
                return jsonify({
                    'success': False,
                    'error': message,
                    'failureReason': 'insufficient_credit',
                    'providerError': model_error,
                    'documentProcessing': document_processing
                }), 503
            if blocked_format:
                message = ('مزوّد الذكاء الاصطناعي رفض صيغة JSON الإجبارية، فلم يُعتمد أي حقل ولم تتغير البيانات. '
                           f'سبب المزوّد: {model_error}')
                return jsonify({
                    'success': False,
                    'error': message,
                    'failureReason': 'provider_blocked',
                    'providerError': model_error,
                    'documentProcessing': document_processing
                }), 503
            if model_error:
                message = f'لم يرد الذكاء الاصطناعي بأي محتوى فلم تتغير البيانات. سبب المزوّد: {model_error}'
            else:
                message = ('لم يرد الذكاء الاصطناعي بأي محتوى، فلم تتغير البيانات. '
                           'تأكد من مفاتيح API ثم أعد المحاولة.')
            return jsonify({
                'success': False,
                'error': message,
                'failureReason': 'empty_response',
                'providerError': model_error,
                'documentProcessing': document_processing
            }), 503
        parsed_response = parse_json_object(raw_resp)
        if not parsed_response:
            print(f"[EXTRACT LAND DOCUMENTS UNPARSEABLE] first 400 chars: {raw_resp[:400]}")
            return jsonify({
                'success': False,
                'error': 'استجابة الذكاء الاصطناعي ليست JSON صالحًا، فلم يُعتمد أي حقل ولم تتغير البيانات.',
                'failureReason': 'invalid_json',
                'providerError': raw_resp[:400],
                'documentProcessing': document_processing
            }), 503
        resp_json = _normalize_land_document_result(
            parsed_response,
            raw_resp,
            project_type=str(data.get('projectType') or data.get('project_type') or '').strip(),
        )
        if vision_warnings:
            resp_json['warnings'] = vision_warnings
        resp_json['document_processing'] = document_processing
        resp_json['regulation_evidence'] = regulation_evidence_metadata
        extraction_diagnostics = _build_land_extraction_diagnostics(resp_json, document_processing)
        resp_json['extraction_diagnostics'] = extraction_diagnostics
        print(
            '[EXTRACT LAND DOCUMENTS TABLES] '
            f"coordinates={extraction_diagnostics['coordinates_rows']} "
            f"complete_coordinates={extraction_diagnostics['coordinates_complete_rows']} "
            f"directions={extraction_diagnostics['directions_with_values']}/4 "
            f"conflicts={extraction_diagnostics['conflict_count']}"
        )

        # Check if there are actual non-empty values extracted
        parcels = resp_json.get('parcels') if isinstance(resp_json, dict) else []
        has_scalar_values = bool(parcels) and any(
            any(value not in (None, '', [], {}) for key, value in parcel.items() if key not in {'parcel_id', 'directions', 'coordinates', 'confidence', 'sources'})
            for parcel in parcels if isinstance(parcel, dict)
        )
        has_table_values = bool(extraction_diagnostics['coordinates_rows'] or extraction_diagnostics['directions_with_values'])
        has_non_empty_values = bool(raw_resp.strip()) and bool(parcels) and (has_scalar_values or has_table_values)

        if not resp_json or not has_non_empty_values:
            print(f"[CROQUIS DEBUG RAW RESP]\n{raw_resp}")
            return jsonify({'success': False, 'error': f'لم يتم التوصل لبيانات مؤكدة في الصورة أو المستند المرفق. يرجى التأكد من وضوح الصورة.'})

        return jsonify({'success': True, 'extractedData': resp_json, 'rawText': raw_resp, 'documentProcessing': document_processing})
    except Exception as exc:
        err_msg = traceback.format_exc()
        print(f"[EXTRACT CROQUIS ERROR]\n{err_msg}")
        return jsonify({'success': False, 'error': f'حدث خطأ في قراءة ملف الكروكي: {str(exc)}'})


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


@app.route('/api/presentations/<pres_id>/log', methods=['POST'])
@require_permission('create_presentation')
def api_log_presentation_edit(pres_id):
    """Record a single edit log entry (used by inline text editing)."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404
    data = request.json or {}
    action = data.get('action', 'edit')
    details = data.get('details', '')
    db.log_edit(pres_id, g.user_id, g.user_name or 'System', action, details)
    return jsonify({'success': True})


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


PROJECT_FILE_EXTENSIONS = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.pdf': 'application/pdf'
}
PROJECT_FILE_TYPES = {'land_document', 'land_image', 'croquis', 'building_license',
                      'regulation_reference', 'team_logo'}
# Types that must be real images: they are rendered in <img> thumbnails, where a PDF shows nothing.
PROJECT_IMAGE_ONLY_TYPES = {'land_image', 'team_logo'}
PROJECT_FILE_MAX_BYTES = 30 * 1024 * 1024


def _store_project_upload(uploaded_file, file_type, draft_id=None, project_id=None):
    if file_type not in PROJECT_FILE_TYPES:
        raise ValueError('Invalid project file type')
    original_name = os.path.basename(uploaded_file.filename or '').strip() or 'document'
    extension = os.path.splitext(original_name)[1].lower()
    mime_type = PROJECT_FILE_EXTENSIONS.get(extension)
    if not mime_type:
        raise ValueError('Only PNG, JPG, JPEG, WEBP, and PDF files are supported')
    if file_type in PROJECT_IMAGE_ONLY_TYPES and not mime_type.startswith('image/'):
        raise ValueError('هذا الحقل يقبل الصور فقط (PNG أو JPG أو WEBP)')

    document_dir = os.path.join(UPLOADS_DIR, str(g.tenant_id), 'project-documents')
    os.makedirs(document_dir, exist_ok=True)
    temp_path = os.path.join(document_dir, f'.upload-{_uuid.uuid4().hex}.tmp')
    digest = hashlib.sha256()
    total = 0
    try:
        with open(temp_path, 'wb') as output:
            while True:
                chunk = uploaded_file.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > PROJECT_FILE_MAX_BYTES:
                    raise ValueError('Project files must be 30 MB or smaller')
                digest.update(chunk)
                output.write(chunk)

        with open(temp_path, 'rb') as source:
            signature = source.read(8)
        if mime_type == 'application/pdf' and not signature.startswith(b'%PDF'):
            raise ValueError('Invalid PDF file')
        if mime_type.startswith('image/'):
            try:
                from PIL import Image, UnidentifiedImageError
                with Image.open(temp_path) as image:
                    image.verify()
            except (UnidentifiedImageError, OSError):
                raise ValueError('Invalid image file')

        sha256 = digest.hexdigest()
        final_name = f'{sha256}{extension}'
        final_path = os.path.join(document_dir, final_name)
        if not os.path.exists(final_path):
            os.replace(temp_path, final_path)
        else:
            os.unlink(temp_path)
        try:
            relative_path = os.path.relpath(final_path, os.path.dirname(__file__)).replace('\\', '/')
        except ValueError:
            relative_path = f'uploads/{g.tenant_id}/project-documents/{final_name}'
        file_id = db.create_project_file(
            g.tenant_id, file_type, original_name, final_path, mime_type, total, sha256,
            draft_id=draft_id, project_id=project_id
        )
        return {
            'id': file_id,
            'fileType': file_type,
            'originalName': original_name,
            'mimeType': mime_type,
            'fileSize': total,
            'sha256': sha256,
            'path': relative_path,
        }
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


@app.route('/api/project-files', methods=['POST'])
@require_permission('create_presentation')
def api_upload_project_file():
    uploaded_file = request.files.get('file')
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({'success': False, 'error': 'No project file provided'}), 400
    file_type = (request.form.get('fileType') or '').strip().lower()
    draft_id = (request.form.get('draftId') or '').strip() or None
    project_id = (request.form.get('projectId') or '').strip() or None
    try:
        result = _store_project_upload(uploaded_file, file_type, draft_id=draft_id, project_id=project_id)
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    except OSError as error:
        return jsonify({'success': False, 'error': f'Could not store project file: {error}'}), 500
    return jsonify({'success': True, 'file': result}), 201


@app.route('/api/project-files/<file_id>', methods=['GET'])
@require_auth
def api_get_project_file(file_id):
    """Stream a previously uploaded project document back so the client can preview it.

    Uploads are only reachable through this route: the record is looked up inside the
    caller's tenant, and the stored path must resolve inside that tenant's upload folder.
    """
    stored = db.get_project_file(g.tenant_id, str(file_id))
    if not stored or not stored.get('storage_path'):
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404

    tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, str(g.tenant_id)))
    storage_path = os.path.realpath(stored['storage_path'])
    if os.path.commonpath([tenant_root, storage_path]) != tenant_root:
        print(f"[PROJECT FILE] rejected out-of-tenant path for {file_id}")
        return jsonify({'success': False, 'error': 'مسار الملف غير مسموح'}), 403
    if not os.path.isfile(storage_path):
        return jsonify({'success': False, 'error': 'الملف غير متاح على السيرفر'}), 404

    mime_type = stored.get('mime_type') or 'application/octet-stream'
    # PDFs and images render inline; anything else downloads instead of executing.
    inline = mime_type == 'application/pdf' or mime_type.startswith('image/')
    response = send_file(
        storage_path,
        mimetype=mime_type,
        as_attachment=not inline,
        download_name=stored.get('original_name') or os.path.basename(storage_path),
        conditional=True,
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'none'; object-src 'none'"
    response.headers['Cache-Control'] = 'private, max-age=300'
    return response


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


def _font_payload_from_file(file):
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in {'.ttf', '.otf', '.woff', '.woff2'}:
        return None, 'Only TTF, OTF, WOFF, and WOFF2 fonts are supported'
    raw = file.read()
    if not raw or len(raw) > 15 * 1024 * 1024:
        return None, 'Font file must be between 1 byte and 15 MB'
    fmt = {'.ttf': 'truetype', '.otf': 'opentype', '.woff': 'woff', '.woff2': 'woff2'}[ext]
    return json.dumps({'data': base64.b64encode(raw).decode('ascii'), 'format': fmt, 'ext': ext}), None


def _detect_font_metadata(raw, filename):
    stem = os.path.splitext(os.path.basename(filename or 'font'))[0]
    metadata_text = stem.replace('_', ' ').replace('-', ' ')
    scripts = set()
    family = metadata_text.strip() or 'Custom Font'
    weight = 'regular'
    try:
        from io import BytesIO
        from fontTools.ttLib import TTFont
        font = TTFont(BytesIO(raw), fontNumber=0)
        names = []
        for record in font['name'].names:
            if record.nameID in (1, 2, 4, 17):
                try:
                    names.append(record.toUnicode())
                except Exception:
                    pass
        if names:
            family = next((value for value in names if value.strip()), family).strip()
            metadata_text = ' '.join(names + [metadata_text])
        cmap = set()
        for table in font['cmap'].tables:
            cmap.update(table.cmap.keys())
        arabic_count = sum(1 for codepoint in cmap if 0x0600 <= codepoint <= 0x06FF or 0x0750 <= codepoint <= 0x077F or 0xFB50 <= codepoint <= 0xFEFF)
        latin_count = sum(1 for codepoint in cmap if 0x0041 <= codepoint <= 0x024F)
        if arabic_count:
            scripts.add('arabic')
        if latin_count:
            scripts.add('latin')
        weight_class = int(getattr(font.get('OS/2'), 'usWeightClass', 400) or 400)
        if weight_class <= 300:
            weight = 'light'
        elif weight_class <= 450:
            weight = 'regular'
        elif weight_class <= 550:
            weight = 'medium'
        elif weight_class <= 750:
            weight = 'bold'
        else:
            weight = 'black'
        font.close()
    except Exception:
        pass

    text = metadata_text.lower()
    if any(token in text for token in ('black', 'heavy', 'extrabold', 'extra bold')):
        weight = 'black'
    elif any(token in text for token in ('bold', 'semibold', 'semi bold', 'demi')):
        weight = 'bold'
    elif any(token in text for token in ('medium', 'medium')):
        weight = 'medium'
    elif any(token in text for token in ('light', 'thin', 'book')):
        weight = 'light'
    if not scripts:
        scripts.add('arabic' if re.search(r'arabic|arab|عربي|نسخ|رقعة', text) else 'latin')
    return {'family': family, 'weight': weight, 'scripts': sorted(scripts), 'source': 'font_metadata'}


@app.route('/api/admin/sag-fonts', methods=['GET'])
@require_permission('sag_admin_panel')
def api_get_sag_fonts():
    return jsonify({'success': True, 'fonts': db.get_sag_fonts(
        script=request.args.get('script'), weight=request.args.get('weight')
    )})


@app.route('/api/admin/sag-fonts', methods=['POST'])
@require_permission('sag_admin_panel')
def api_create_sag_font():
    data = request.form if request.form else (request.json or {})
    font_name = (data.get('font_name') or data.get('fontName') or '').strip()
    font_family = (data.get('font_family') or data.get('fontFamily') or '').strip()
    script = (data.get('script') or '').strip().lower()
    weight = (data.get('weight') or 'regular').strip().lower()
    if not font_name or not font_family or script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'font_name, font_family, script, and a valid weight are required'}), 400
    file_data = None
    if 'font' in request.files:
        file_data, error = _font_payload_from_file(request.files['font'])
        if error:
            return jsonify({'error': error}), 400
    font_id = db.create_sag_font(
        font_name, font_family, script, weight, data.get('style', 'normal'),
        'uploaded' if file_data else 'preset', data.get('source_data') or font_family, file_data
    )
    font = db.get_sag_font(font_id) or {}
    font.pop('file_data', None)
    return jsonify({'success': True, 'font': font}), 201


@app.route('/api/admin/sag-fonts/auto-upload', methods=['POST'])
@require_permission('sag_admin_panel')
def api_auto_upload_sag_font():
    file = request.files.get('font')
    if not file or not file.filename:
        return jsonify({'error': 'No font file provided'}), 400
    file_data, error = _font_payload_from_file(file)
    if error:
        return jsonify({'error': error}), 400
    raw = base64.b64decode(json.loads(file_data)['data'])
    detected = _detect_font_metadata(raw, file.filename)
    created = []
    for script in detected['scripts']:
        font_id = db.create_sag_font(
            detected['family'], detected['family'], script, detected['weight'],
            source_type='uploaded', source_data=detected['family'], file_data=file_data
        )
        created.append(font_id)
    return jsonify({'success': True, 'detected': detected, 'fontIds': created, 'fonts': db.get_sag_fonts()}), 201


@app.route('/api/admin/sag-fonts/<font_id>', methods=['PUT'])
@require_permission('sag_admin_panel')
def api_update_sag_font(font_id):
    data = request.json or {}
    if not db.update_sag_font(font_id, **data):
        return jsonify({'error': 'Font not found or no valid changes'}), 404
    return jsonify({'success': True, 'font': db.get_sag_font(font_id)})


@app.route('/api/admin/sag-fonts/<font_id>', methods=['DELETE'])
@require_permission('sag_admin_panel')
def api_delete_sag_font(font_id):
    if not db.get_sag_font(font_id):
        return jsonify({'error': 'Font not found'}), 404
    db.update_sag_font(font_id, is_active=0, is_default=0)
    return jsonify({'success': True})


def _get_tenant_uploaded_fonts(tenant_id):
    font_dir = os.path.join(UPLOADS_DIR, str(tenant_id), 'fonts')
    if not os.path.exists(font_dir):
        return []
    fonts = []
    seen = set()
    for fname in sorted(os.listdir(font_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in ('.ttf', '.otf', '.woff', '.woff2'):
            stem = os.path.splitext(fname)[0]
            family = re.sub(r'_(light|regular|medium|bold|black)$', '', stem, flags=re.I).replace('_', ' ').strip()
            if family and family.lower() not in seen:
                seen.add(family.lower())
                rel_path = os.path.relpath(os.path.join(font_dir, fname), os.path.dirname(__file__)).replace('\\', '/')
                fonts.append({
                    'id': f'custom_file_{len(fonts)+1}',
                    'font_family': family,
                    'font_name': family,
                    'script': 'arabic',
                    'weight': 'regular',
                    'is_custom': True,
                    'custom_font_path': rel_path
                })
    return fonts


def _public_font_selections(tenant_id):
    hidden = {'custom_font_data'}
    selections = db.get_tenant_font_selections(tenant_id)
    branding = db.get_branding(tenant_id) or {}
    tenant_family = branding.get('font_family')
    result = []
    for selection in selections:
        item = {key: value for key, value in selection.items() if key not in hidden}
        if item.get('font_id') and not item.get('font_family'):
            font = db.get_sag_font(item['font_id'])
            if font:
                item['font_family'] = font.get('font_family')
        elif item.get('custom_font_path') and not item.get('font_family'):
            if tenant_family:
                item['font_family'] = tenant_family
            else:
                path = item['custom_font_path']
                name = os.path.splitext(os.path.basename(path))[0]
                name = re.sub(r'_(light|regular|medium|bold|black)$', '', name, flags=re.I)
                item['font_family'] = name.replace('_', ' ').strip()
        result.append(item)
    return result


@app.route('/api/branding/fonts', methods=['GET'])
@require_auth
def api_get_branding_fonts():
    return jsonify({
        'success': True,
        'selections': _public_font_selections(g.tenant_id),
        'available': db.get_sag_fonts(),
        'custom_uploaded': _get_tenant_uploaded_fonts(g.tenant_id)
    })


@app.route('/api/branding/fonts', methods=['PUT'])
@require_permission('company_settings')
def api_set_branding_font():
    data = request.json or {}
    script = (data.get('script') or '').strip().lower()
    weight = (data.get('weight') or '').strip().lower()
    font_id = data.get('font_id') or data.get('fontId')
    custom_font_path = data.get('custom_font_path')
    if script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'Invalid script or weight'}), 400
    if font_id and not db.get_sag_font(font_id):
        return jsonify({'error': 'Font not found'}), 404
    if font_id:
        db.set_tenant_font_selection(g.tenant_id, script, weight, font_id=font_id)
    elif custom_font_path:
        db.set_tenant_font_selection(g.tenant_id, script, weight, custom_font_path=custom_font_path)
    else:
        db.delete_tenant_font_selection(g.tenant_id, script, weight)
    return jsonify({'success': True, 'selections': _public_font_selections(g.tenant_id)})


@app.route('/api/branding/fonts/upload', methods=['POST'])
@require_permission('company_settings')
def api_upload_branding_font_variant():
    script = (request.form.get('script') or '').strip().lower()
    weight = (request.form.get('weight') or 'regular').strip().lower()
    if script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'Invalid script or weight'}), 400
    file = request.files.get('font')
    if not file or not file.filename:
        return jsonify({'error': 'No font file provided'}), 400
    file_data, error = _font_payload_from_file(file)
    if error:
        return jsonify({'error': error}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', os.path.splitext(file.filename)[0])
    font_dir = os.path.join(UPLOADS_DIR, g.tenant_id, 'fonts')
    os.makedirs(font_dir, exist_ok=True)
    filename = f'{safe_name}_{script}_{weight}{ext}'
    filepath = os.path.join(font_dir, filename)
    with open(filepath, 'wb') as font_file:
        font_file.write(base64.b64decode(json.loads(file_data)['data']))
    stored_path = os.path.relpath(filepath, os.path.dirname(__file__)).replace('\\', '/')
    db.set_tenant_font_selection(g.tenant_id, script, weight, custom_font_path=stored_path, custom_font_data=file_data)
    return jsonify({'success': True, 'selections': _public_font_selections(g.tenant_id)})


@app.route('/api/branding/fonts/auto-upload', methods=['POST'])
@require_permission('company_settings')
def api_auto_upload_branding_font():
    file = request.files.get('font')
    if not file or not file.filename:
        return jsonify({'error': 'No font file provided'}), 400
    file_data, error = _font_payload_from_file(file)
    if error:
        return jsonify({'error': error}), 400
    parsed = json.loads(file_data)
    raw = base64.b64decode(parsed['data'])
    detected = _detect_font_metadata(raw, file.filename)
    ext = parsed['ext']
    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', os.path.splitext(file.filename)[0])
    font_dir = os.path.join(UPLOADS_DIR, g.tenant_id, 'fonts')
    os.makedirs(font_dir, exist_ok=True)
    filename = f'{safe_name}_{detected["weight"]}{ext}'
    filepath = os.path.join(font_dir, filename)
    with open(filepath, 'wb') as font_file:
        font_file.write(raw)
    stored_path = os.path.relpath(filepath, os.path.dirname(__file__)).replace('\\', '/')
    current_branding = db.get_branding(g.tenant_id) or {}
    current_family = (current_branding.get('font_family') or '').strip().lower()
    detected_family = (detected.get('family') or '').strip().lower()
    target_scripts = list(set(detected.get('scripts', []) + ['arabic', 'latin']))
    if not current_family or (detected_family and current_family != detected_family):
        for script in ('arabic', 'latin'):
            for old_weight in ('light', 'regular', 'medium', 'bold', 'black'):
                db.delete_tenant_font_selection(g.tenant_id, script, old_weight)
    for script in target_scripts:
        db.set_tenant_font_selection(
            g.tenant_id,
            script,
            detected['weight'],
            custom_font_path=stored_path,
            custom_font_data=file_data,
        )
    family_name = detected.get('family') or os.path.splitext(file.filename)[0].replace('_', ' ').strip()
    db.update_branding(g.tenant_id, font_family=family_name, font_arabic=family_name)
    return jsonify({
        'success': True,
        'detected': detected,
        'selections': _public_font_selections(g.tenant_id),
    })


@app.route('/api/branding/fonts/<script>/<weight>', methods=['DELETE'])
@require_permission('company_settings')
def api_delete_branding_font(script, weight):
    if script not in {'arabic', 'latin'} or weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
        return jsonify({'error': 'Invalid script or weight'}), 400
    db.delete_tenant_font_selection(g.tenant_id, script, weight)
    return jsonify({'success': True})


@app.route('/api/upload-font', methods=['POST'])
@app.route('/api/branding/font', methods=['POST'])
@require_permission('company_settings')
def api_upload_font():
    """Upload a custom font file (TTF/OTF/WOFF/WOFF2) to uploads/fonts/<tenant_id>/."""
    if 'font' not in request.files:
        return jsonify({'error': 'No font file provided'}), 400
    file = request.files['font']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.ttf', '.otf', '.woff', '.woff2'):
        return jsonify({'error': 'Only TTF, OTF, WOFF, WOFF2 are supported'}), 400

    font_dir = os.path.join('uploads', g.tenant_id, 'fonts')
    os.makedirs(font_dir, exist_ok=True)

    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(file.filename)[0])
    filename = f"{safe_name}{ext}"
    filepath = os.path.join(font_dir, filename)
    file.save(filepath)

    # Also persist the font bytes in the DB so exports still work if uploads/ is ephemeral
    try:
        with open(filepath, 'rb') as f:
            font_bytes = f.read()
        fmt = {'.ttf': 'truetype', '.otf': 'opentype', '.woff': 'woff', '.woff2': 'woff2'}.get(ext, 'truetype')
        font_file_data = json.dumps({
            'data': base64.b64encode(font_bytes).decode('ascii'),
            'format': fmt,
            'ext': ext
        })
    except Exception as e:
        print(f"[FONT UPLOAD] failed to read font bytes for persistence: {e}")
        font_file_data = None

    font_file_path = os.path.relpath(filepath, os.path.dirname(__file__)).replace('\\', '/')
    font_url = f"/tenant-assets/{g.tenant_id}/fonts/{filename}"
    font_name = safe_name.replace('_', ' ').title()
    updates = {'font_file_path': font_file_path, 'font_family': font_name}
    if font_file_data:
        updates['font_file_data'] = font_file_data
    db.update_branding(g.tenant_id, **updates)
    return jsonify({'success': True, 'font_url': font_url, 'font_file_path': font_file_path, 'font_name': font_name})


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
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return jsonify({'error': 'Logo not found'}), 404
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


@app.route('/tenant-assets/<tenant_id>/fonts/<filename>')
def serve_tenant_font(tenant_id, filename):
    """Serve uploaded tenant font files."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return jsonify({'error': 'Font not found'}), 404
    safe_name = os.path.basename(filename)
    if '..' in safe_name or safe_name.startswith('.') or not safe_name:
        return jsonify({'error': 'Invalid font filename'}), 400
    ext = os.path.splitext(safe_name)[1].lower()
    mime_map = {'.ttf': 'font/ttf', '.otf': 'font/otf', '.woff': 'font/woff', '.woff2': 'font/woff2'}
    mimetype = mime_map.get(ext)
    if not mimetype:
        return jsonify({'error': 'Invalid font filename'}), 400
    font_path = os.path.join(UPLOADS_DIR, str(tenant_id), 'fonts', safe_name)
    if not os.path.isfile(font_path):
        return jsonify({'error': 'Font not found'}), 404
    resp = send_file(font_path, mimetype=mimetype)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


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
                "model": LUNA_TEXT_MODEL,
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

### 23. ملء بيانات المشروع في مساحة العمل من كلام المستخدم:
```action
{{"tool": "update_workspace", "params": {{"projectData": {{"project_name": "...", "project_type": "...", "location_address": "...", "land_area": "...", "budget": "..."}}}}}}
```
استخدمها عندما يعطيك المستخدم بيانات مشروع في المحادثة ويريد إنشاء عرض منها. أرسل الحقول المتوفرة فقط.

### 24. توليد خطة الشرائح من بيانات المشروع:
```action
{{"tool": "generate_slide_plan"}}
```
تتطلب projectData في مساحة العمل (استخدم update_workspace أولاً إن لزم).

### 25. عرض الخطوط المتاحة والتخصيص الحالي:
```action
{{"tool": "list_fonts"}}
```

### 26. تخصيص خط الشركة أو الرجوع للخط الافتراضي:
```action
{{"tool": "set_font", "params": {{"font_query": "اسم الخط أو عائلته من قائمة الخطوط المتاحة أو default", "weight": "regular"}}}}
```
- عند اختيار خط يدعم العربية واللاتينية يُطبَّق على الاثنين تلقائياً.
- استخدم "default" في font_query للرجوع للخط الافتراضي.
- رفع ملف خط جديد يتم فقط من إعدادات الشركة (منطقة السحب والإفلات) — إذا طلب المستخدم خطاً غير موجود في القائمة، أخبره برفعه أولاً من الإعدادات.

## سير العمل الكامل لإنشاء عرض جديد من المحادثة:
1. اجمع بيانات المشروع من كلام المستخدم (اسم المشروع، النوع، الموقع، المساحات، الميزانية...) ونفّذ `update_workspace`
2. نفّذ `generate_slide_plan` لإنشاء خطة الشرائح
3. نفّذ `generate_workspace` لتوليد الشرائح فعلياً
4. أخبر المستخدم أن العرض جاهز في صفحة معاينة الشرائح
إذا كان مساحة العمل تحتوي بيانات وخطة مسبقاً، تجاوز الخطوتين 1-2 مباشرة إلى 3.
لا تنفذ التوليد أو التعديل أو التصدير إذا لم تتوفر مساحة عمل صالحة. نفذ الأدوات بالترتيب: inspect ثم التنفيذ ثم validate ثم save/export عند طلب المستخدم.

## قواعد مهمة وحاسمة:
1.  الفرق بين "الشرائح" (Slides) و "حقول الإدخال" (Input Fields):
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
                    reply = f"تم التعديل!  عدد صور المود بورد تم تغييره إلى **{num} صور**. الآن كل عرض تقديمي سيتم إنشاؤه سيضم {num} صور في شريحة المود بورد."
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
                        'params': {'default_slide_count': num, 'min_slides': max(1, num - 2), 'max_slides': min(50, num + 3)}
                    })
                    reply = f"تم التعديل!  عدد الشرائح الافتراضي تم تغييره إلى **{num} شرائح**. الحد الأدنى: {max(1, num - 2)}، الحد الأقصى: {min(50, num + 3)}."
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
                reply = f"تم التعديل!  تم تحديث ألوان الهوية البصرية للشركة: ({desc})."

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
            reply = "تم استرجاع الألوان القديمة والافتراضية للهوية البصرية بنجاح!  (Primary: #3B6E91, Secondary: #254B66)."

        # 5. Font intent ("غيّر الخط إلى X" / "استخدم خط X" / "رجّع الخط الافتراضي")
        font_words = {'خط', 'الخط', 'خطوط', 'الخطوط', 'بالخط', 'فونت', 'الفونت'}
        tokens = set(re.findall(r'[؀-ۿ]+|[A-Za-z]+', message))
        if not parsed_actions and (tokens & font_words or 'font' in message.lower()):
            msg_lower = message.lower()
            font_hit = None
            for f in db.get_sag_fonts():
                name = (f.get('font_name') or '').lower()
                family = (f.get('font_family') or '').lower()
                if (name and name in msg_lower) or (family and family in msg_lower):
                    font_hit = f
                    break
            if font_hit:
                parsed_actions.append({'tool': 'set_font', 'params': {'font_query': font_hit['font_name']}})
                reply = f"تم تخصيص خط الشركة إلى **{font_hit['font_name']}**. "
            elif any(kw in message for kw in ['الخط الافتراضي', 'رجع الخط', 'رجّع الخط', 'استرجاع الخط']):
                parsed_actions.append({'tool': 'set_font', 'params': {'font_query': 'default'}})
                reply = 'تم الرجوع للخط الافتراضي للشركة. '

    for action in parsed_actions:
        try:
            result = _execute_agent_action(g.tenant_id, action, reply_text=reply, workspace=workspace)
            actions_executed.append(result)
            # Chain workspace mutations so sequential tools in the same reply
            # (update_workspace إلى generate_slide_plan إلى generate_workspace) see updates.
            rdata = result.get('data') if isinstance(result, dict) else None
            if isinstance(rdata, dict):
                if isinstance(rdata.get('projectData'), dict):
                    workspace['projectData'] = rdata['projectData']
                if isinstance(rdata.get('slidePlan'), dict):
                    workspace['slidePlan'] = rdata['slidePlan']
                if isinstance(rdata.get('slidesData'), list):
                    workspace['slidesData'] = rdata['slidesData']
            print(f'[SUPER-AGENT] Executed: {action.get("tool")} إلى {result.get("status")}')
        except Exception as ex:
            print(f'[SUPER-AGENT] Action execution error: {ex}')
            actions_executed.append({'status': 'error', 'message': str(ex)})

    # ── Clean action blocks from the display reply ────────────────────────
    clean_reply = re.sub(r'```action\s*\n?[\s\S]*?```', '', reply).strip()
    # Remove leftover empty lines
    clean_reply = re.sub(r'\n{3,}', '\n\n', clean_reply).strip()

    if not clean_reply and actions_executed:
        clean_reply = ' تم تنفيذ الإجراء بنجاح.'

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
        req = ' إلزامي' if f.get('is_required') else 'اختياري'
        custom = ' (مخصص)' if f.get('is_custom') else ' (أساسي)'
        field_lines.append(f"  • {f['field_label']} [{f['field_key']}] — نوع: {f['field_type']}, قسم: {f.get('section_key', 'general')}, {req}{custom}")

    inactive_field_lines = []
    for f in inactive_fields[:15]:
        inactive_field_lines.append(f"  • {f['field_label']} [{f['field_key']}] — معطل")

    user_lines = []
    for u in users:
        status = ' نشط' if u.get('is_active') else ' معطل'
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

    font_selections = db.get_tenant_font_selections(tenant_id)
    current_font_lines = []
    for sel in font_selections:
        if sel.get('font_id'):
            src = db.get_sag_font(sel['font_id']) or {}
            font_label = src.get('font_name') or 'خط مركزي'
        else:
            font_label = os.path.basename(sel.get('custom_font_path') or 'خط مخصص')
        script_label = 'عربي' if sel.get('script') == 'arabic' else 'لاتيني'
        current_font_lines.append(f"  • {script_label} / {sel.get('weight', 'regular')}: {font_label}")

    available_fonts = db.get_sag_fonts()
    available_font_lines = []
    seen_families = set()
    for f in available_fonts:
        family_key = f.get('font_family') or f.get('font_name')
        if family_key in seen_families:
            continue
        seen_families.add(family_key)
        script_label = 'عربي' if f.get('script') == 'arabic' else 'لاتيني'
        default_tag = ' (افتراضي النظام)' if f.get('is_default') else ''
        available_font_lines.append(f"  • {f.get('font_name')} ({script_label}){default_tag}")

    return f"""###  معلومات الشركة:
- اسم الشركة: {branding.get('company_name', 'غير محدد')}
- الشعار النصي: {branding.get('tagline', 'غير محدد')}

###  الهوية البصرية:
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

###  الخطوط:
- التخصيص الحالي: {'الخط الافتراضي (لم يتم تخصيص خط)' if not current_font_lines else ''}
{chr(10).join(current_font_lines) if current_font_lines else ''}
- الخطوط المتاحة للتخصيص ({len(seen_families)} خط):
{chr(10).join(available_font_lines) if available_font_lines else '  لا توجد خطوط مركزية — يمكن للأدمن رفع خط مخصص من صفحة الإعدادات.'}

###  إعدادات الشرائح والصور:
- عدد الشرائح الافتراضي: {branding.get('default_slide_count', 16)}
- الحد الأدنى: {branding.get('min_slides', 8)}
- الحد الأقصى: {branding.get('max_slides', 30)}
- عدد صور المود بورد: {branding.get('moodboard_count', 4)}
- المود بورد: {'مفعل' if branding.get('moodboard_enabled') else 'معطل'}
- صورة الغلاف: {'مفعلة' if branding.get('cover_image_enabled') else 'معطلة'}

###  حقول الإدخال النشطة ({len(active_fields)} حقل):
{chr(10).join(field_lines) if field_lines else '  لا توجد حقول نشطة.'}

###  حقول معطلة ({len(inactive_fields)}):
{chr(10).join(inactive_field_lines) if inactive_field_lines else '  لا توجد حقول معطلة.'}

###  أقسام البيانات ({len(sections)} قسم):
{chr(10).join(section_lines) if section_lines else '  لا توجد أقسام.'}

###  الموظفين ({len(users)} موظف):
{chr(10).join(user_lines) if user_lines else '  لا يوجد موظفين.'}

###  العروض التقديمية:
{pres_summary}

###  سجلات التدريب ({len(active_training)} سجل نشط):
{chr(10).join(training_lines) if training_lines else '  لا توجد سجلات تدريب.'}

###  قوالب الشرائح المخصصة ({len(templates)} قالب):
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

        # ── Update workspace project data from chat ───────────────────
        elif tool == 'update_workspace':
            new_data = params.get('projectData')
            if not isinstance(new_data, dict) or not new_data:
                result['status'] = 'error'
                result['message'] = 'أرسل projectData ككائن يحتوي بيانات المشروع'
            else:
                merged = workspace.get('projectData') if isinstance(workspace.get('projectData'), dict) else {}
                merged = {**merged, **new_data}
                result['data'] = {'projectData': merged}
                result['message'] = f'تم تحديث بيانات المشروع ({len(new_data)} حقل)'

        # ── Generate slide plan from workspace project data ───────────
        elif tool == 'generate_slide_plan':
            project_data = clean_project_data(workspace.get('projectData') or {})
            if not project_data:
                result['status'] = 'error'
                result['message'] = 'لا توجد بيانات مشروع في مساحة العمل. استخدم update_workspace أولاً لملء بيانات المشروع من كلام المستخدم.'
            else:
                plan_branding = db.get_branding(tenant_id) or {}
                training_context = db.get_training_context(tenant_id) or ''
                plan_prompt = slide_engine.build_slide_plan_prompt(project_data, plan_branding)
                if training_context:
                    plan_prompt = f"## بيانات خاصة بالشركة\n{training_context}\n\n---\n\n{plan_prompt}"
                plan = None
                last_plan_err = None
                for _attempt in range(3):
                    try:
                        plan_resp = call_zai_chat_parallel(
                            "أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية.",
                            plan_prompt, max_tokens=4000, attempts=2)
                        plan = slide_engine.parse_slide_plan(extract_chat_content(plan_resp, "AGENT-SLIDE-PLAN"), plan_branding, project_data)
                        break
                    except Exception as plan_err:
                        last_plan_err = plan_err
                        time.sleep(1)
                if plan is None:
                    result['status'] = 'error'
                    result['message'] = f'فشل توليد خطة الشرائح: {last_plan_err}'
                else:
                    result['data'] = {'slidePlan': plan}
                    result['message'] = f'تم توليد خطة من {len(plan.get("slides", []))} شريحة — راجعها ثم نفّذ generate_workspace'

        # ── Generate workspace slides from the supplied plan ──────────
        elif tool == 'generate_workspace':
            project_data = clean_project_data(workspace.get('projectData') or {})
            slide_plan = workspace.get('slidePlan') or {}
            images = workspace.get('creativeImages') or workspace.get('images') or {}
            plan_slides = slide_plan.get('slides') if isinstance(slide_plan, dict) else None
            if not project_data or not isinstance(plan_slides, list) or not plan_slides:
                result['status'] = 'error'
                missing = []
                if not project_data:
                    missing.append('بيانات المشروع (projectData)')
                if not isinstance(plan_slides, list) or not plan_slides:
                    missing.append('خطة الشرائح (slidePlan)')
                result['message'] = (
                    'مساحة العمل تنقصها: ' + ' و '.join(missing) +
                    '. الخطوات: 1) اجمع بيانات المشروع من المستخدم ونفّذ update_workspace '
                    '2) نفّذ generate_slide_plan لإنشاء الخطة 3) أعد المحاولة.'
                )
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

        # ── List Fonts ────────────────────────────────────────────────
        elif tool == 'list_fonts':
            selections = db.get_tenant_font_selections(tenant_id)
            fonts = db.get_sag_fonts()
            result['data'] = {
                'current': [{
                    'script': s['script'], 'weight': s['weight'],
                    'font_id': s.get('font_id'),
                    'custom': bool(s.get('custom_font_path')),
                } for s in selections],
                'available': [{
                    'id': f['id'], 'font_name': f['font_name'], 'font_family': f['font_family'],
                    'script': f['script'], 'weight': f['weight'],
                } for f in fonts],
            }
            result['message'] = f'{len(fonts)} خط متاح، {len(selections)} تخصيص حالي'

        # ── Set Font ──────────────────────────────────────────────────
        elif tool == 'set_font':
            query = (params.get('font_query') or params.get('font_name') or params.get('font_family') or params.get('query') or '').strip()
            weight = (params.get('weight') or 'regular').strip().lower()
            if weight not in {'light', 'regular', 'medium', 'bold', 'black'}:
                weight = 'regular'
            script_filter = (params.get('script') or 'both').strip().lower()
            if not query:
                result['status'] = 'error'
                result['message'] = 'font_query مطلوب (اسم الخط أو default)'
            elif query.lower() in {'default', 'reset', 'الافتراضي', 'الخط الافتراضي'}:
                for script in ('arabic', 'latin'):
                    db.delete_tenant_font_selection(tenant_id, script, weight)
                db.log_ai_rule_change(tenant_id, 'agent_font', 'font_reset', query, 'default', risk_level='yellow')
                result['message'] = 'تم الرجوع للخط الافتراضي'
            else:
                fonts = db.get_sag_fonts()
                q = query.lower()
                matches = [
                    f for f in fonts
                    if q in (f.get('font_name') or '').lower()
                    or q in (f.get('font_family') or '').lower()
                    or ((f.get('font_name') or '').lower() and (f.get('font_name') or '').lower() in q)
                    or ((f.get('font_family') or '').lower() and (f.get('font_family') or '').lower() in q)
                ]
                if not matches:
                    result['status'] = 'error'
                    result['message'] = f'الخط "{query}" غير موجود ضمن الخطوط المتاحة'
                else:
                    exact = [f for f in matches if (f.get('font_family') or '').lower() == q or (f.get('font_name') or '').lower() == q]
                    pool = exact or matches
                    chosen = [f for f in pool if f.get('weight') == weight] or pool
                    applied = []
                    for f in chosen:
                        if script_filter in ('arabic', 'latin') and f['script'] != script_filter:
                            continue
                        db.set_tenant_font_selection(tenant_id, f['script'], weight, font_id=f['id'])
                        applied.append(f)
                    if not applied:
                        result['status'] = 'error'
                        result['message'] = f'الخط "{query}" لا يدعم السكربت المطلوب ({script_filter})'
                    else:
                        names = '، '.join(sorted({f['font_name'] for f in applied}))
                        scripts = ' و '.join('عربي' if s == 'arabic' else 'لاتيني' for s in sorted({f['script'] for f in applied}))
                        db.log_ai_rule_change(tenant_id, 'agent_font', 'set_font', query, names, risk_level='yellow')
                        result['changes']['font'] = {'query': query, 'applied': names}
                        result['message'] = f'تم تخصيص الخط "{names}" ({scripts}) بوزن {weight}'

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
    'lock_slide_count': 0,
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
    # "no-cache" means revalidate before use, which is what a SPA shell needs so a deploy is picked
    # up immediately. It was "no-store" as well, which forbids keeping a copy at all and forced the
    # full ~740KB down the wire on every single load. With the ETag that send_from_directory sets,
    # an unchanged shell now answers 304 with no body.
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers.pop('Pragma', None)
    resp.headers.pop('Expires', None)
    return resp


@app.route('/app', methods=['GET'])
@app.route('/app/<path:page>')
def tenant_app_page(page=''):
    """Serve the SPA shell for bookmarkable tenant workspace pages."""
    return index()


@app.route('/invite/<token>')
def invite_page(token):
    resp = send_from_directory(os.path.dirname(__file__), 'index.html')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


# Reserved prefixes must keep their own 404s; everything else is a client-side route and has to
# return the SPA shell, otherwise reloading or sharing a deep link drops the user on an error page.
SPA_RESERVED_PREFIXES = ('api/', 'uploads/', 'assets/', 'tenant-assets/', 'outputs/', 'static/')


@app.errorhandler(404)
def spa_fallback(error):
    path = (request.path or '/').lstrip('/')
    if request.method not in ('GET', 'HEAD') or path.startswith(SPA_RESERVED_PREFIXES):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    if 'text/html' not in (request.headers.get('Accept') or ''):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return index()

@app.route('/assets/<path:path>')
def static_assets(path):
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'assets'), path)

@app.route('/uploads/maps/<path:path>')
def static_map_uploads(path):
    """Serve persisted map assets; generation is available only via explicit APIs."""
    maps_dir = os.path.join(UPLOADS_DIR, 'maps')
    full_path = os.path.join(maps_dir, path)
    if os.path.isfile(full_path):
        return send_from_directory(maps_dir, path)
    return jsonify({'error': 'Map image not found', 'error_code': 'MAP_ASSET_MISSING'}), 404


@app.route('/uploads/creative/<tenant_id>/<path:filename>')
def static_creative_upload(tenant_id, filename):
    """Serve generated creative images without exposing arbitrary upload paths."""
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', tenant_id)
    safe_filename = os.path.basename(filename)
    if safe_tenant != tenant_id or safe_filename != filename:
        return jsonify({'error': 'Not found'}), 404
    creative_dir = os.path.join(UPLOADS_DIR, 'creative', safe_tenant)
    if not os.path.isfile(os.path.join(creative_dir, safe_filename)):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(creative_dir, safe_filename)


@app.route('/uploads/<path:path>')
def static_uploads(path):
    """Serve map images or static presentation assets."""
    maps_dir = os.path.join(UPLOADS_DIR, 'maps')
    filename = os.path.basename(path)
    possible_map = os.path.join(maps_dir, filename)
    if os.path.isfile(possible_map):
        return send_from_directory(maps_dir, filename)
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/deploy-webhook', methods=['GET', 'POST'])
def deploy_webhook():
    """Endpoint for GitHub or cPanel webhook to trigger automated deployment after commits."""
    env_secret = os.environ.get('DEPLOY_WEBHOOK_SECRET')
    if not env_secret:
        return jsonify({'error': 'DEPLOY_WEBHOOK_SECRET not configured in environment'}), 403

    secret = request.args.get('secret') or request.headers.get('X-Deploy-Secret') or (request.json.get('secret') if (request.is_json and request.json) else None)
    if not secret or secret != env_secret:
        return jsonify({'error': 'Unauthorized'}), 401

    requested_commit = request.args.get('commit') or (
        request.json.get('commit') if (request.is_json and request.json) else None
    )
    if requested_commit and not re.fullmatch(r'[0-9a-fA-F]{40}', str(requested_commit)):
        return jsonify({'error': 'Invalid deployment commit'}), 400
    
    deploy_script = '/home/sagdemo/proposal-generator/deploy.sh'
    if not os.path.exists(deploy_script):
        deploy_script = os.path.join(os.path.dirname(__file__), 'deploy.sh')

    if os.path.exists(deploy_script):
        try:
            import subprocess
            command = ['bash', deploy_script]
            if requested_commit:
                command.append(str(requested_commit))
            
            deploy_log_path = '/home/sagdemo/proposal-generator/deploy.log'
            if not os.path.exists(os.path.dirname(deploy_log_path)):
                deploy_log_path = os.path.join(os.path.dirname(__file__), 'deploy.log')
            
            log_fh = None
            try:
                log_fh = open(deploy_log_path, 'a', encoding='utf-8')
                log_fh.write(f"\n--- Deployment triggered at {datetime.now().isoformat()} for commit {requested_commit or 'latest'} ---\n")
                log_fh.flush()
            except OSError:
                log_fh = None
            
            popen_kwargs = {'start_new_session': True}
            if log_fh is not None:
                popen_kwargs['stdout'] = log_fh
                popen_kwargs['stderr'] = subprocess.STDOUT
            
            subprocess.Popen(command, **popen_kwargs)
            return jsonify({'status': 'Deployment triggered successfully',
                            'expected_commit': requested_commit,
                            'timestamp': datetime.now().isoformat()}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'deploy.sh not found'}), 404


@app.route('/favicon.ico')
def favicon():
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'favicon.ico')):
        return send_from_directory(os.path.dirname(__file__), 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    return ('', 204)


def _read_deployment_metadata():
    metadata = {'commit': 'unknown', 'deployed_commit': 'unknown', 'deployed_at': None, 'source': 'git'}
    try:
        with open(DEPLOYMENT_MARKER_PATH, 'r', encoding='utf-8') as marker:
            raw = marker.read().strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    metadata.update({key: value for key, value in parsed.items() if value is not None})
                else:
                    metadata['deployed_commit'] = raw
            except (TypeError, ValueError):
                metadata['deployed_commit'] = raw
            if metadata.get('source') == 'git':
                metadata['source'] = 'deployment_marker'
    except OSError:
        pass

    stored_deployed_commit = metadata.get('deployed_commit')
    if not stored_deployed_commit or stored_deployed_commit == 'unknown':
        stored_deployed_commit = metadata.get('commit')
    deployed_commit = str(stored_deployed_commit or 'unknown')
    metadata['deployed_commit'] = deployed_commit
    if deployed_commit != 'unknown':
        metadata['commit'] = deployed_commit[:7]
        return metadata
    try:
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if commit_hash:
            metadata['commit'] = commit_hash
            metadata['deployed_commit'] = commit_hash
    except Exception:
        pass
    return metadata


@app.route('/health')
def health():
    metadata = _read_deployment_metadata()
    return jsonify({
        'status': 'ok',
        'commit': metadata.get('commit', 'unknown'),
        'deployed_commit': metadata.get('deployed_commit', 'unknown'),
        'deployed_at': metadata.get('deployed_at'),
        'deployment_source': metadata.get('source'),
        'model': GLM_MODEL,
        'image_model': IMAGE_MODEL,
    })

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
