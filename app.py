import os
import sys
import json
import time
import math
import colorsys
from datetime import datetime, timezone
import re
import base64
import hashlib
import html as html_lib
from html.parser import HTMLParser
import subprocess
import requests
from urllib3 import HTTPSConnectionPool
from urllib3.util import Timeout
import uuid as _uuid
import threading
import ipaddress
import socket
import smtplib
import ssl
import secrets
from io import BytesIO
from email.message import EmailMessage
from urllib.parse import urljoin, urlsplit
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import db_driver
import concurrent.futures
import copy
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, send_from_directory, g, current_app

load_dotenv()

import db
import auth
import maps_service
import market_study
import executive_content
import population_service
import slide_engine
import change_tracking
import designer_chat_reliability
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
        request.__dict__.pop('_cached_json', None)
    except Exception:
        app.logger.warning('Could not decompress gzipped request body', exc_info=True)


@app.before_request
def reassemble_chunked_request_body():
    # The hosting edge corrupts request bodies above ~40KB: the app actually
    # receives and answers them, but the client gets a fabricated 404/502. The
    # client therefore uploads large bodies in small chunk envelopes
    # (POST /api/body-chunk) and finally sends a tiny {"__chunked_body": {...}}
    # reference; restore the original body here before routing.
    if request.method not in ('POST', 'PUT', 'PATCH') or request.path == '/api/body-chunk':
        return
    if 'application/json' not in (request.content_type or ''):
        return
    try:
        data = request.get_data(cache=True)
        if not data or b'__chunked_body' not in data:
            return
        payload = json.loads(data)
    except Exception:
        # An unreadable body is not a reassembly reference. Leave it alone so the route reports the
        # real parse failure instead of this hook turning it into a request that carries no data.
        return
    # The marker can also appear inside ordinary content, and treating that as a reference used to
    # reject the request; only a real top-level reference is reassembled.
    if not isinstance(payload, dict) or '__chunked_body' not in payload:
        return
    meta = payload.get('__chunked_body') or {}
    upload_id = str(meta.get('id', ''))
    total = meta.get('total')
    use_gzip = bool(meta.get('gzip'))
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', upload_id) or not isinstance(total, int) or not (1 <= total <= 1024):
        app.logger.warning(f"[CHUNK] Invalid chunked body reference: id={upload_id!r} total={total!r}")
        return jsonify({'error': 'Invalid chunked body reference'}), 400
    import gzip as _gzip
    import io
    import shutil as _shutil
    import time as _time
    chunk_dir = os.path.join(UPLOADS_DIR, '.body_chunks', upload_id)
    parts = []
    missing_index = None
    for _attempt in range(5):
        missing_index = None
        parts = []
        try:
            for i in range(total):
                part_file = os.path.join(chunk_dir, f'{i}.part')
                if not os.path.isfile(part_file):
                    missing_index = i
                    break
                with open(part_file, 'rb') as fh:
                    parts.append(fh.read())
            if missing_index is None and len(parts) == total:
                break
        except OSError:
            missing_index = i if 'i' in locals() else 0
        _time.sleep(0.05)

    if missing_index is not None or len(parts) != total:
        existing = os.listdir(chunk_dir) if os.path.isdir(chunk_dir) else 'none'
        app.logger.warning(f"[CHUNK] Missing uploaded body chunks for {upload_id}: missing={missing_index} total={total} existing={existing}")
        return jsonify({'error': 'Missing uploaded body chunks', 'missing': missing_index, 'total': total}), 400

    raw = b''.join(parts)
    if use_gzip:
        try:
            raw = _gzip.decompress(raw)
        except Exception as err:
            app.logger.warning(f"[CHUNK] Could not decompress chunked body for {upload_id} (len={len(raw)}): {err}")
            return jsonify({'error': 'Could not decompress chunked body'}), 400
    request._cached_data = raw
    request.environ['wsgi.input'] = io.BytesIO(raw)
    request.environ['CONTENT_LENGTH'] = str(len(raw))
    request.__dict__.pop('_cached_json', None)
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
    if not isinstance(b64, str) or len(b64) > 64 * 1024:
        return jsonify({'error': 'Chunk too large'}), 400
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return jsonify({'error': 'Invalid chunk data'}), 400
    import shutil as _shutil
    chunk_root = os.path.abspath(os.path.join(UPLOADS_DIR, '.body_chunks'))
    chunk_dir = os.path.abspath(os.path.join(chunk_root, upload_id))
    if os.path.commonpath([chunk_root, chunk_dir]) != chunk_root:
        return jsonify({'error': 'Invalid upload id'}), 400
    os.makedirs(chunk_dir, exist_ok=True)
    with open(os.path.join(chunk_dir, f'{int(idx)}.part'), 'wb') as fh:
        fh.write(raw)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
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
OPENROUTER_KEY = (os.environ.get("OPENROUTER_KEY") or "").strip() or None
OPENROUTER_BASE = 'https://openrouter.ai/api/v1'
GEMINI_TEXT_MODEL = "google/gemini-3.8-flash"
LUNA_TEXT_MODEL = GEMINI_TEXT_MODEL
GLM_MODEL = GEMINI_TEXT_MODEL
GLM_OPENROUTER_MODEL = GEMINI_TEXT_MODEL
SLIDE_TEXT_MODEL = os.environ.get('SLIDE_TEXT_MODEL', 'openai/gpt-5.6-sol')
print(f"[CONFIG] Primary text/design model: {GEMINI_TEXT_MODEL}")
print(f"[CONFIG] Slide generation model: {SLIDE_TEXT_MODEL}")
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"
SITE_ANALYSIS_MAX_TOKENS = int(os.environ.get('SITE_ANALYSIS_MAX_TOKENS', '6000'))
EXECUTIVE_CONTENT_MAX_TOKENS = int(os.environ.get('EXECUTIVE_CONTENT_MAX_TOKENS', '32000'))
EXECUTIVE_SUMMARY_MAX_TOKENS = int(os.environ.get('EXECUTIVE_SUMMARY_MAX_TOKENS', '65536'))
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
DEPLOYMENT_MARKER_PATH = os.path.join(os.path.dirname(__file__), '.deployed_commit')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY')
print(f"[CONFIG] OPENROUTER_KEY: {'SET' if OPENROUTER_KEY else 'MISSING'}")
print(f"[CONFIG] GOOGLE_MAPS_API_KEY: {'SET' if GOOGLE_MAPS_API_KEY else 'MISSING'}")
print(f"[CONFIG] JWT_SECRET: {auth.JWT_SECRET_SOURCE.upper()}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helper: Call the text/design model through OpenRouter
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _has_chat_choices(response):
    return (
        isinstance(response, dict)
        and 'error' not in response
        and isinstance(response.get('choices'), list)
        and bool(response['choices'])
    )


def call_openrouter_chat(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None, image_references=None, tools=None, plugins=None, usage_ctx=None):
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
    if tools:
        payload["tools"] = tools
    if plugins:
        payload["plugins"] = plugins
    try:
        response = requests.post(f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=payload, timeout=timeout)
        text = response.text or ''
        if not text.strip():
            print(f"[OPENROUTER EMPTY BODY] status={response.status_code} model={model_name} cap={max_tokens}")
            _record_ai_usage(usage_ctx, model_name, 'error')
            return {"error": {"message": f"مزوّد الذكاء الاصطناعي رد بجسم فارغ (HTTP {response.status_code})"}}
        try:
            data = response.json()
        except Exception as json_err:
            print(f"[OPENROUTER UNPARSEABLE] status={response.status_code} model={model_name} json_err={json_err} body={text[:200]!r}")
            _record_ai_usage(usage_ctx, model_name, 'error')
            return {"error": {"message": f"استجابة المزوّد ليست JSON صالحًا (HTTP {response.status_code})"}}
        if response.status_code >= 400:
            error = data.get('error', {}) if isinstance(data, dict) else data
            print(f"[OPENROUTER HTTP ERROR] status={response.status_code} model={model_name} error={error}")
            generation_id, error_usage = _extract_openrouter_usage(data)
            _record_ai_usage(usage_ctx, model_name, 'error', error_usage, generation_id)
            if isinstance(error, dict) and 'message' in error:
                error['message'] = f"[{response.status_code}] {error['message']}"
                return {"error": error}
            return {"error": error if isinstance(error, dict) else {"message": f"[{response.status_code}] {error}"}}
        generation_id, usage = _extract_openrouter_usage(data)
        _record_ai_usage(usage_ctx, model_name, 'ok', usage, generation_id)
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
                  reasoning_effort=None, response_format=None, model=None, image_references=None, usage_ctx=None):
    """Compatibility wrapper: text/design work uses configured models through OpenRouter."""
    if not OPENROUTER_KEY:
        return {"error": {"message": "OPENROUTER_KEY is required for the text model"}}
    return call_openrouter_chat(
        system_prompt,
        user_content,
        temperature=None,
        max_tokens=max_tokens,
        model=model or LUNA_TEXT_MODEL,
        timeout=timeout,
        reasoning_effort=reasoning_effort,
        response_format=response_format,
        image_references=image_references,
        usage_ctx=usage_ctx,
    )


def call_zai_chat_parallel(system_prompt, user_content, temperature=0.7, max_tokens=8000, attempts=2, timeout=300, model=None, image_references=None, usage_ctx=None):
    """
    Race multiple identical GLM calls in parallel and return the first valid response.
    Helps when a single model invocation is slow or returns malformed/empty content.
    Every attempt is metered separately: the provider bills each one.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _attempt():
        try:
            resp = call_zai_chat(system_prompt, user_content, temperature, max_tokens, timeout=timeout, model=model, image_references=image_references, usage_ctx=usage_ctx)
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI usage metering: per-call OpenRouter consumption, attributed per tenant,
# draft and presentation. Token figures are copied verbatim from the provider
# response. Dollar cost is resolved per generation id off the request path.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI_USAGE_FLOWS = (
    'slide', 'slide_plan', 'designer_chat', 'training_chat', 'land', 'site',
    'market', 'executive', 'project_data', 'image', 'other',
)


def _usage_ctx(flow, data=None, draft_id=None, presentation_id=None, tenant_id=None):
    """Build the metering context for one AI call. Unknown ids stay None."""
    if isinstance(data, dict):
        project_data = data.get('projectData')
        if draft_id is None:
            draft_id = data.get('draftId') or data.get('draft_id')
            if draft_id is None and isinstance(project_data, dict):
                draft_id = project_data.get('draftId') or project_data.get('draft_id')
        if presentation_id is None:
            presentation_id = data.get('presentationId') or data.get('presentation_id')
    if tenant_id is None:
        try:
            tenant_id = getattr(g, 'tenant_id', None)
        except Exception:
            tenant_id = None
    return {
        'tenant_id': tenant_id,
        'draft_id': draft_id,
        'presentation_id': presentation_id,
        'flow': flow if flow in AI_USAGE_FLOWS else 'other',
    }


def _extract_openrouter_usage(data):
    """Return (generation_id, usage_dict) copied from a provider response, never raising."""
    try:
        if not isinstance(data, dict):
            return None, {}
        generation_id = data.get('id')
        if not isinstance(generation_id, str) or not generation_id:
            generation_id = None
        usage = data.get('usage')
        if not isinstance(usage, dict):
            return generation_id, {}

        def _num(value):
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return generation_id, {
            'prompt_tokens': _num(usage.get('prompt_tokens')),
            'completion_tokens': _num(usage.get('completion_tokens')),
            'total_tokens': _num(usage.get('total_tokens')),
        }
    except Exception:
        return None, {}


def _record_ai_usage(usage_ctx, model, status='ok', usage=None, generation_id=None):
    """Persist one metered provider call. Never raises: metering must not break generation."""
    try:
        ctx = dict(usage_ctx or {})
        tenant_id = ctx.get('tenant_id')
        if tenant_id is None:
            try:
                tenant_id = getattr(g, 'tenant_id', None)
            except Exception:
                tenant_id = None
        usage = usage or {}
        flow = ctx.get('flow') or 'other'
        if flow not in AI_USAGE_FLOWS:
            flow = 'other'
        with app.app_context():
            event_id = db.record_ai_usage_event(
                tenant_id, model or 'unknown',
                flow=flow, status=status,
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0),
                total_tokens=usage.get('total_tokens', 0),
                draft_id=ctx.get('draft_id'),
                presentation_id=ctx.get('presentation_id'),
                generation_id=generation_id,
            )
        if generation_id and status == 'ok':
            _backfill_ai_usage_cost_async(event_id, generation_id)
        return event_id
    except Exception as exc:
        print(f"[AI-USAGE] record failed: {exc}")
        return None


def _fetch_openrouter_generation_cost(generation_id, timeout=15):
    """Ask OpenRouter what one generation actually cost. Returns dollars or None."""
    try:
        if not OPENROUTER_KEY or not generation_id:
            return None
        response = requests.get(
            f"{OPENROUTER_BASE}/generation?id={generation_id}",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            timeout=timeout,
        )
        payload = response.json()
        data = payload.get('data') if isinstance(payload, dict) else None
        cost = (data or {}).get('total_cost')
        return float(cost) if cost is not None else None
    except Exception as exc:
        print(f"[AI-USAGE] cost lookup failed for {generation_id}: {exc}")
        return None


def _backfill_ai_usage_cost(event_id, generation_id):
    """Resolve one event's dollar cost inside a worker thread."""
    try:
        with app.app_context():
            if app.config.get('TESTING'):
                return
            cost = _fetch_openrouter_generation_cost(generation_id)
            if cost is not None:
                db.update_ai_usage_cost(event_id, cost)
    except Exception as exc:
        print(f"[AI-USAGE] cost backfill failed: {exc}")


def _backfill_ai_usage_cost_async(event_id, generation_id):
    """Resolve the dollar cost off the request path."""
    try:
        thread = threading.Thread(
            target=_backfill_ai_usage_cost,
            args=(event_id, generation_id),
            daemon=True,
        )
        thread.start()
    except Exception as exc:
        print(f"[AI-USAGE] cost thread failed: {exc}")


def _ai_usage_event_age_hours(created_at):
    try:
        stamp = str(created_at or '').replace(' ', 'T')[:19]
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is not None:
            moment = moment.replace(tzinfo=None)
        return (datetime.utcnow() - moment).total_seconds() / 3600.0
    except Exception:
        return 0.0


def _backfill_missing_ai_costs(max_events=10, time_budget_seconds=8, max_age_hours=24):
    """Best-effort fill of costs the background threads missed. Bounded so reads stay fast."""
    try:
        pending = db.get_ai_usage_pending_costs(limit=max_events)
    except Exception as exc:
        print(f"[AI-USAGE] pending lookup failed: {exc}")
        return
    started = time.monotonic()
    for row in pending:
        if time.monotonic() - started > time_budget_seconds:
            break
        if _ai_usage_event_age_hours(row.get('created_at')) > max_age_hours:
            continue
        cost = _fetch_openrouter_generation_cost(row.get('generation_id'))
        if cost is not None:
            try:
                db.update_ai_usage_cost(row['id'], cost)
            except Exception as exc:
                print(f"[AI-USAGE] cost update failed: {exc}")


@app.route('/api/ai-usage', methods=['GET'])
@require_auth
def api_ai_usage():
    """Tenant-scoped consumption: OpenRouter totals plus Maps spend, with combined cost."""
    draft_id = (request.args.get('draftId') or request.args.get('draft_id') or '').strip() or None
    presentation_id = (request.args.get('presentationId') or request.args.get('presentation_id') or '').strip() or None
    try:
        _backfill_missing_ai_costs()
        ai_usage = db.get_ai_usage_summary(
            g.tenant_id, draft_id=draft_id, presentation_id=presentation_id)
        maps_usage = db.get_maps_usage_summary(
            g.tenant_id, draft_id=draft_id, presentation_id=presentation_id)
        ai_cost = float(ai_usage['totals'].get('cost_usd') or 0.0)
        maps_cost = float(maps_usage['totals'].get('cost_usd') or 0.0)
        return jsonify({
            'success': True,
            'usage': ai_usage,
            'maps': maps_usage,
            'combined': {
                'calls': int(ai_usage['totals'].get('calls') or 0) + int(maps_usage['totals'].get('calls') or 0),
                'cost_usd': ai_cost + maps_cost,
                'ai_cost_usd': ai_cost,
                'maps_cost_usd': maps_cost,
            },
        })
    except Exception as exc:
        print(f"[AI-USAGE] summary failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل الاستهلاك'}), 500


@app.route('/api/usage-totals', methods=['GET'])
@require_auth
def api_usage_totals():
    """Bulk spend for list screens: per-project totals plus per-presentation costs."""
    def _ids(value):
        return [part.strip() for part in (value or '').split(',') if part.strip()][:200]

    try:
        _backfill_missing_ai_costs()
        return jsonify({
            'success': True,
            **db.get_usage_totals(
                g.tenant_id,
                draft_ids=_ids(request.args.get('draftIds') or request.args.get('draft_ids')),
                presentation_ids=_ids(request.args.get('presentationIds') or request.args.get('presentation_ids')),
            ),
        })
    except Exception as exc:
        print(f"[AI-USAGE] totals failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل الإجماليات'}), 500


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
def _image_response_url(data):
    def candidate(value):
        if isinstance(value, str):
            value = value.strip()
            return value if value.startswith('data:image/') or value.startswith('http') else None
        if not isinstance(value, dict):
            return None
        encoded = value.get('b64_json') or value.get('base64')
        if encoded:
            return 'data:image/png;base64,' + str(encoded)
        for key in ('image_url', 'image', 'url', 'data_uri'):
            nested = value.get(key)
            if isinstance(nested, dict):
                nested = nested.get('url') or nested.get('data_uri')
            result = candidate(nested)
            if result:
                return result
        return None

    if not isinstance(data, dict):
        return None
    for choice in data.get('choices') or []:
        message = choice.get('message') if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            continue
        for key in ('images', 'content'):
            value = message.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                result = candidate(item)
                if result:
                    return result
    for item in data.get('data') or []:
        result = candidate(item)
        if result:
            return result
    return None


def call_image_api(prompt, usage_ctx=None):
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
        generation_id, img_usage = _extract_openrouter_usage(data)
        _record_ai_usage(usage_ctx or _usage_ctx('image'), IMAGE_MODEL,
                         'ok' if response.status_code < 400 and 'error' not in data else 'error',
                         img_usage, generation_id)
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
        image_url = _image_response_url(data)
        if image_url:
            return image_url
        print(f"[IMAGE ERROR] API returned no image (status {response.status_code}). Response: {str(data)[:300]}")
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


def call_image_api_with_reference(reference_image_base64, prompt, usage_ctx=None):
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
        generation_id, img_usage = _extract_openrouter_usage(data)
        _record_ai_usage(usage_ctx or _usage_ctx('image'), IMAGE_MODEL,
                         'ok' if response.status_code < 400 and 'error' not in data else 'error',
                         img_usage, generation_id)
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
        image_url = _image_response_url(data)
        if image_url:
            return image_url
        print(f"[IMAGE ERROR] API returned no image (status {response.status_code}). Response: {str(data)[:300]}")
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
    if not extension or not re.fullmatch(r'\.(png|jpg|webp)', extension):
        return image
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        return image
    digest = hashlib.sha256(raw).hexdigest()[:24]
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(tenant_id or 'public')) or 'public'
    image_dir = os.path.join(UPLOADS_DIR, 'creative', safe_tenant)
    os.makedirs(image_dir, exist_ok=True)
    filename = digest + extension
    path = os.path.join(image_dir, filename)
    if not os.path.exists(path):
        with open(path, 'wb') as image_file:
            image_file.write(raw)
    return f'/uploads/creative/{safe_tenant}/{filename}'


VISUAL_CONCEPT_MAX_REFERENCE_IMAGES = 5
VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 4
VISUAL_CONCEPT_SLOTS = ('cover', 'right', 'left', 'top', 'back', 'interior')
VISUAL_CONCEPT_EXTERNAL_SLOTS = ('cover', 'right', 'left', 'top', 'back')
VISUAL_CONCEPT_MOODBOARD_SLOTS = ('right', 'left', 'top', 'back')
VISUAL_CONCEPT_INTERNAL_PREFIX = 'interior'
VISUAL_CONCEPT_SLOT_LABELS = {
    'cover': 'الصورة الرئيسية',
    'right': 'يمين',
    'left': 'شمال',
    'top': 'فوق',
    'back': 'خلف',
    'interior': 'التصميم الداخلي',
}
VISUAL_CONCEPT_REQUIRED_FIELDS = (
    ('project_name', 'اسم المشروع'),
    ('project_idea', 'فكرة المشروع'),
    ('land_and_building_summary', 'وصف المشروع والأرض'),
    ('target_audience', 'الفئات المستهدفة'),
    ('approved_financial_area', 'المساحة المعتمدة للدراسة المالية'),
    ('approved_floor_count', 'عدد الأدوار المعتمدة'),
    ('approved_coverage_ratio', 'نسبة التغطية المعتمدة'),
    ('facades', 'عدد الواجهات على الشارع واتجاهاتها'),
    ('allowed_uses', 'الاستخدامات المسموحة'),
    ('directions_table', 'جدول الاتجاهات'),
    ('overview_map', 'خريطة الأرض / المبنى'),
)


def _visual_concept_text(value, limit=4000):
    if value is None:
        return ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        parts = [_visual_concept_text(item, 400) for item in value]
        return '، '.join(part for part in parts if part).strip()[:limit]
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value).strip()[:limit]


def _visual_concept_parse_json(value, fallback=None):
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, (dict, list)) else fallback


def _visual_concept_number(value):
    if isinstance(value, bool) or value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _visual_concept_read(project_data, *keys):
    source = project_data if isinstance(project_data, dict) else {}
    for key in keys:
        if key in source and source[key] not in (None, ''):
            return source[key]
    return ''


def _visual_concept_components(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    financial = source.get('financial_study_model') if isinstance(source.get('financial_study_model'), dict) else {}
    dynamic_rows = financial.get('dynamicRows') if isinstance(financial.get('dynamicRows'), dict) else {}
    rows = dynamic_rows.get('components')
    if not isinstance(rows, list):
        rows = _visual_concept_parse_json(_visual_concept_read(source, 'project_components_data'), [])
    output = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        name = _visual_concept_text(item.get('name') or item.get('component') or item.get('title'), 160)
        if not name:
            continue
        component_id = _visual_concept_text(item.get('id') or item.get('componentId') or item.get('component_id'), 80)
        output.append({
            'id': component_id or f'component_{len(output) + 1}',
            'name': name,
            'useType': _visual_concept_text(item.get('useType') or item.get('type'), 80),
            'units': _visual_concept_number(item.get('units')),
            'unitArea': _visual_concept_number(item.get('unitArea')),
            'builtArea': _visual_concept_number(item.get('builtArea') or item.get('totalArea')),
        })
        if len(output) >= 40:
            break
    return output


def _visual_concept_directions(project_data):
    raw = _visual_concept_parse_json(_visual_concept_read(project_data, 'directions_table'), None)
    if isinstance(raw, dict):
        raw = [{'direction': key, **(value if isinstance(value, dict) else {'regulation_text': value})}
               for key, value in raw.items()]
    if not isinstance(raw, list):
        return []
    labels = {'north': 'شمال', 'south': 'جنوب', 'east': 'شرق', 'west': 'غرب',
              'شمال': 'شمال', 'جنوب': 'جنوب', 'شرق': 'شرق', 'غرب': 'غرب'}
    rows = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        direction = _visual_concept_text(item.get('direction') or item.get('label'), 40)
        label = labels.get(direction.lower(), direction or labels.get(item.get('label'), ''))
        text = _visual_concept_text(
            item.get('regulation_text') or item.get('regulation') or item.get('text') or item.get('notes'),
            400,
        )
        if not text:
            continue
        rows.append({'direction': label or direction, 'regulation_text': text})
    return rows


def _visual_concept_list(value):
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        parsed = _visual_concept_parse_json(value, None)
        values = parsed if isinstance(parsed, list) else ([value] if value.strip() else [])
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def _visual_concept_style_reference_ids(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    visual = source.get('visual_concept')
    if isinstance(visual, str):
        visual = _visual_concept_parse_json(visual, {})
    visual = visual if isinstance(visual, dict) else {}
    candidates = []
    for key in ('styleReferenceFileIds', 'style_reference_file_ids'):
        candidates.extend(_visual_concept_list(visual.get(key)))
    candidates.extend(_visual_concept_list(visual.get('styleReferenceFileId') or visual.get('style_reference_file_id')))
    for key in ('visual_style_reference_file_ids',):
        candidates.extend(_visual_concept_list(source.get(key)))
    candidates.extend(_visual_concept_list(source.get('visual_style_reference_file_id')))
    unique = []
    for file_id in candidates:
        if file_id not in unique:
            unique.append(file_id)
        if len(unique) >= VISUAL_CONCEPT_MAX_REFERENCE_IMAGES:
            break
    return unique


def _visual_concept_style_reference_id(project_data):
    return next(iter(_visual_concept_style_reference_ids(project_data)), '')


def _visual_concept_overview_map_url(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
    placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    if not placeholders and isinstance(source.get('map_placeholders'), dict):
        placeholders = source.get('map_placeholders')
    for key in ('##MAP_OVERVIEW##', '##MAP_OVERVIEW_SATELLITE##', '##MAP_OVERVIEW_ROADMAP##'):
        url = placeholders.get(key)
        if isinstance(url, str) and url.strip():
            return url.strip()
    return ''


def _resolve_project_file_storage_path(stored, tenant_id=None):
    """Resolve and validate a project file's physical path within the tenant root.

    Handles absolute paths from migrated databases where the host prefix changed
    (e.g. from /home/demos/... to /home/landloom/...).
    """
    if not stored or not stored.get('storage_path'):
        return None
    tenant = str(tenant_id or stored.get('tenant_id') or getattr(g, 'tenant_id', '') or '')
    if not tenant:
        return None
    tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, tenant))
    raw_path = str(stored.get('storage_path') or '').replace('\\', '/')
    candidate = os.path.realpath(stored['storage_path'])
    try:
        if os.path.commonpath([tenant_root, candidate]) == tenant_root and os.path.isfile(candidate):
            return candidate
    except ValueError:
        pass
    # If migrated from another host, re-root relative to tenant_root
    if f'/{tenant}/' in raw_path:
        subpath = raw_path.split(f'/{tenant}/', 1)[1]
        re_rooted = os.path.realpath(os.path.join(tenant_root, subpath.replace('/', os.sep)))
        try:
            if os.path.commonpath([tenant_root, re_rooted]) == tenant_root and os.path.isfile(re_rooted):
                return re_rooted
        except ValueError:
            pass
    elif '/project-documents/' in raw_path:
        filename = os.path.basename(raw_path)
        re_rooted = os.path.realpath(os.path.join(tenant_root, 'project-documents', filename))
        try:
            if os.path.commonpath([tenant_root, re_rooted]) == tenant_root and os.path.isfile(re_rooted):
                return re_rooted
        except ValueError:
            pass
    return None


def _visual_concept_project_file_data_uri(file_id, tenant_id=None):
    tenant_id = tenant_id or getattr(g, 'tenant_id', None)
    if not tenant_id or not file_id:
        return None
    stored = db.get_project_file(tenant_id, str(file_id))
    if not stored or not stored.get('storage_path'):
        return None
    mime_type = stored.get('mime_type') or ''
    if not mime_type.startswith('image/'):
        return None
    storage_path = _resolve_project_file_storage_path(stored, tenant_id)
    if not storage_path or not os.path.isfile(storage_path) or os.path.getsize(storage_path) > 15 * 1024 * 1024:
        return None
    try:
        with open(storage_path, 'rb') as image_file:
            encoded = base64.b64encode(image_file.read()).decode('ascii')
    except OSError:
        return None
    return f'data:{mime_type};base64,{encoded}'


def _publish_project_file_as_creative_image(file_id, tenant_id=None):
    """Copy an uploaded image into the tenant's creative folder and return its public URL.

    An uploaded slot image used to be shown from a ``blob:`` URL, which exists only inside
    the tab that created it. That URL was saved into the draft, so after a reload every
    client-uploaded image rendered broken and every export shipped a dead reference.
    """
    tenant_id = tenant_id or getattr(g, 'tenant_id', None)
    data_uri = _visual_concept_project_file_data_uri(file_id, tenant_id)
    if not data_uri:
        return None
    url = persist_generated_image(data_uri, tenant_id)
    return url if isinstance(url, str) and url.startswith('/uploads/') else None


def _visual_concept_reference_uris(urls=None, file_ids=None, max_images=None, urls_first=False):
    limit = VISUAL_CONCEPT_MAX_REFERENCE_IMAGES if max_images is None else max(1, int(max_images))
    prepared_files = []
    for file_id in file_ids or []:
        prepared = _visual_concept_project_file_data_uri(file_id)
        if prepared:
            prepared_files.append(prepared)
    prepared_urls = []
    for url in urls or []:
        prepared = _prepare_image_reference_for_model(url)
        if prepared:
            prepared_urls.append(prepared)
    references = (prepared_urls + prepared_files) if urls_first else (prepared_files + prepared_urls)
    unique = []
    seen = set()
    for item in references:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _visual_concept_facts(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    directions = _visual_concept_directions(source)
    components = _visual_concept_components(source)
    style_reference_ids = _visual_concept_style_reference_ids(source)
    style_reference_id = style_reference_ids[0] if style_reference_ids else ''
    map_url = _visual_concept_overview_map_url(source)
    facades_count = _visual_concept_text(_visual_concept_read(source, 'facades_count'), 40)
    facades_directions = _visual_concept_text(_visual_concept_read(source, 'facades_directions'), 240)
    facts = {
        'project_name': _visual_concept_text(_visual_concept_read(source, 'project_name', 'projectName'), 200),
        'project_idea': _visual_concept_text(_visual_concept_read(source, 'project_idea'), 4000),
        'land_and_building_summary': _visual_concept_text(
            _visual_concept_read(source, 'land_and_building_summary', 'project_description', 'description'), 8000),
        'target_audience': _visual_concept_text(_visual_concept_read(source, 'target_audience'), 2000),
        'approved_financial_area': _visual_concept_text(_visual_concept_read(source, 'approved_financial_area'), 80),
        'approved_floor_count': _visual_concept_text(_visual_concept_read(source, 'approved_floor_count'), 40),
        'approved_coverage_ratio': _visual_concept_text(_visual_concept_read(source, 'approved_coverage_ratio'), 40),
        'facades_count': facades_count,
        'facades_directions': facades_directions,
        'allowed_uses': _visual_concept_text(_visual_concept_read(source, 'allowed_uses'), 4000),
        'city': _visual_concept_text(_visual_concept_read(source, 'city'), 80),
        'district': _visual_concept_text(_visual_concept_read(source, 'district'), 80),
        'directions': directions,
        'components': components,
        'style_reference_file_id': style_reference_id,
        'style_reference_file_ids': style_reference_ids,
        'overview_map_url': map_url,
    }
    return facts


def _visual_concept_missing_fields(facts, slot_id='cover'):
    missing = []
    if not facts.get('project_name'):
        missing.append({'key': 'project_name', 'label': 'اسم المشروع'})
    if not facts.get('project_idea'):
        missing.append({'key': 'project_idea', 'label': 'فكرة المشروع'})
    if not facts.get('land_and_building_summary'):
        missing.append({'key': 'land_and_building_summary', 'label': 'وصف المشروع والأرض'})
    if not facts.get('target_audience'):
        missing.append({'key': 'target_audience', 'label': 'الفئات المستهدفة'})
    if _visual_concept_number(facts.get('approved_financial_area')) in (None, 0):
        missing.append({'key': 'approved_financial_area', 'label': 'المساحة المعتمدة للدراسة المالية'})
    if _visual_concept_number(facts.get('approved_floor_count')) in (None, 0):
        missing.append({'key': 'approved_floor_count', 'label': 'عدد الأدوار المعتمدة'})
    if _visual_concept_number(facts.get('approved_coverage_ratio')) in (None, 0):
        missing.append({'key': 'approved_coverage_ratio', 'label': 'نسبة التغطية المعتمدة'})
    if not facts.get('facades_count') or not facts.get('facades_directions'):
        missing.append({'key': 'facades', 'label': 'عدد الواجهات على الشارع واتجاهاتها'})
    if not facts.get('allowed_uses'):
        missing.append({'key': 'allowed_uses', 'label': 'الاستخدامات المسموحة'})
    if not facts.get('directions'):
        missing.append({'key': 'directions_table', 'label': 'جدول الاتجاهات'})
    if not facts.get('overview_map_url'):
        missing.append({'key': 'overview_map', 'label': 'خريطة الأرض / المبنى'})
    if slot_id == 'interior' or str(slot_id or '').startswith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_'):
        if not facts.get('components'):
            missing.append({'key': 'project_components_data', 'label': 'مكونات المشروع في الدراسة المالية'})
    return missing


def _visual_concept_is_internal_slot(slot_id):
    value = str(slot_id or '')
    return value == VISUAL_CONCEPT_INTERNAL_PREFIX or value.startswith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_')


def _visual_concept_interior_component_id(slot_id):
    value = str(slot_id or '')
    prefix = VISUAL_CONCEPT_INTERNAL_PREFIX + '_'
    if not value.startswith(prefix):
        return ''
    rest = value[len(prefix):].strip()
    if '::' in rest:
        rest = rest.rsplit('::', 1)[0]
    return rest


def _visual_concept_normalize_slot(slot_id):
    value = str(slot_id or 'cover').strip()
    folded = value.lower()
    if folded in VISUAL_CONCEPT_SLOTS:
        return folded
    if folded.startswith(VISUAL_CONCEPT_INTERNAL_PREFIX + '_'):
        suffix = value.split('_', 1)[1].strip()
        return f'{VISUAL_CONCEPT_INTERNAL_PREFIX}_{suffix}' if suffix else None
    aliases = {
        'main': 'cover', 'cover_image': 'cover', 'hero': 'cover',
        'east': 'right', 'east_facade': 'right', 'يمين': 'right',
        'west': 'left', 'west_facade': 'left', 'شمال': 'left',
        'aerial': 'top', 'above': 'top', 'فوق': 'top',
        'rear': 'back', 'behind': 'back', 'خلف': 'back',
        'inside': 'interior', 'internal': 'interior',
    }
    return aliases.get(folded)


def _visual_concept_slot_label(slot_id, facts=None):
    custom = ''
    if isinstance(facts, dict):
        custom = _visual_concept_text(facts.get('slot_label'), 80)
    return custom or VISUAL_CONCEPT_SLOT_LABELS.get(slot_id, 'تصور داخلي للمكون')


def _visual_concept_slot_instruction(slot_id, facts):
    name = facts.get('project_name') or 'the project'
    if slot_id == 'cover':
        style_note = (
            'If a style-reference building image is attached, follow its architectural signature, materials, and design language. '
            if facts.get('style_reference_file_ids') else
            'No style-reference image was supplied; invent the architecture from the project facts only. '
        )
        return (
            f'Create the primary architectural hero photograph of {name}. '
            'Use the attached site/map image as the actual ground and plot background when it is included. Place the building on that plot. '
            + style_note +
            'The composition is a cinematic exterior establishing shot, 16:9.'
        )
    if slot_id in VISUAL_CONCEPT_MOODBOARD_SLOTS:
        view_name = _visual_concept_slot_label(slot_id, facts)
        return (
            f'Render the "{view_name}" view of the exact same building shown in the attached hero image of {name}. '
            'Keep the architecture, materials, height, and massing unchanged. Follow the named viewpoint.'
        )
    if _visual_concept_is_internal_slot(slot_id):
        selected = facts.get('selected_component') if isinstance(facts.get('selected_component'), dict) else {}
        component_name = selected.get('name') or 'the selected project component'
        use_type = selected.get('useType') or ''
        units = selected.get('units')
        area = selected.get('builtArea') or selected.get('unitArea')
        details = []
        if use_type:
            details.append(f'use type {use_type}')
        if units not in (None, ''):
            details.append(f'{units} units')
        if area not in (None, ''):
            details.append(f'area {area}')
        detail_text = ', '.join(details)
        return (
            f'Render one photorealistic INTERIOR of {name} for the actual project component named {component_name}. '
            f'This interior must belong to the same building shown in the attached approved hero image. '
            f'Use only this component: {component_name}'
            + (f' ({detail_text})' if detail_text else '')
            + '. Do not invent another program, mix other components, or change the exterior architecture. '
            'If component-specific interior references are attached, follow their materials and atmosphere. '
            'Composition is 16:9, no people, no text, no logos.'
        )
    component_names = '، '.join(item['name'] for item in (facts.get('components') or []) if item.get('name'))
    return (
        f'Render one photorealistic interior of {name} that belongs to the same project as the attached hero image. '
        f'Visible interior program must come from the financial components only: {component_names or "the listed project components"}. '
        'Do not invent unrelated interior uses.'
    )


def _visual_concept_facts_prompt(facts, slot_id):
    directions = '\n'.join(
        f"- {row['direction']}: {row['regulation_text']}" for row in facts.get('directions') or []
    ) or 'غير متوفر'
    components = '\n'.join(
        f"- {item['name']}"
        + (f" / {item['useType']}" if item.get('useType') else '')
        + (f" / وحدات {item['units']}" if item.get('units') not in (None, '') else '')
        + (f" / مساحة {item['builtArea'] or item['unitArea']}" if (item.get('builtArea') or item.get('unitArea')) else '')
        for item in facts.get('components') or []
    ) or 'غير متوفر'
    selected = facts.get('selected_component') if isinstance(facts.get('selected_component'), dict) else {}
    selected_component = selected.get('name') or 'غير محدد'
    location = '، '.join(part for part in (facts.get('city'), facts.get('district')) if part)
    return (
        f"اسم المشروع: {facts.get('project_name')}\n"
        f"فكرة المشروع: {facts.get('project_idea')}\n"
        f"وصف المشروع والأرض: {facts.get('land_and_building_summary')}\n"
        f"الفئات المستهدفة: {facts.get('target_audience')}\n"
        f"المساحة المعتمدة للدراسة المالية: {facts.get('approved_financial_area')}\n"
        f"عدد الأدوار المعتمدة: {facts.get('approved_floor_count')}\n"
        f"نسبة التغطية المعتمدة: {facts.get('approved_coverage_ratio')}\n"
        f"عدد الواجهات على الشارع: {facts.get('facades_count')}\n"
        f"اتجاهات الواجهات: {facts.get('facades_directions')}\n"
        f"الاستخدامات المسموحة: {facts.get('allowed_uses')}\n"
        f"المدينة والحي: {location or 'غير متوفر'}\n"
        f"جدول الاتجاهات:\n{directions}\n"
        f"مكونات الدراسة المالية:\n{components}\n"
        f"المكون الداخلي المختار: {selected_component}\n"
        f"صور مرجعية للتصميم: {'مرفقة' if facts.get('style_reference_file_ids') else 'غير مرفوعة — ولّد التصميم من البيانات فقط'}\n"
        f"صور مرجعية للمكون الداخلي: {'مرفقة' if facts.get('interior_reference_file_ids') else 'غير مرفوعة'}\n"
        f"خريطة الأرض / المبنى كخلفية الموقع: {'مرفقة' if facts.get('overview_map_url') else 'غير متوفرة'}\n"
        f"نوع الصورة المطلوبة: {_visual_concept_slot_label(slot_id, facts)}\n"
        f"تعليمات الكادر: {_visual_concept_slot_instruction(slot_id, facts)}"
    )


def _visual_concept_sanitize_prompt(prompt):
    return _visual_concept_text(prompt, 12000)


def call_image_api_with_references(prompt, references=None, usage_ctx=None):
    if not OPENROUTER_KEY:
        print('[IMAGE ERROR] OPENROUTER_KEY is not configured')
        return None
    ctx = usage_ctx or _usage_ctx('image')
    prepared = []
    for reference in references or []:
        item = _prepare_image_reference_for_model(reference) if isinstance(reference, str) and not str(reference).startswith('data:image/') else reference
        if isinstance(item, str) and item.startswith('data:image/'):
            prepared.append(item)
        elif isinstance(item, str) and item:
            resolved = _prepare_image_reference_for_model(item)
            if resolved:
                prepared.append(resolved)
    if not prepared:
        return call_image_api(prompt, usage_ctx=ctx)
    if len(prepared) == 1:
        return call_image_api_with_reference(prepared[0], prompt, usage_ctx=ctx)
    try:
        headers = {
            'Authorization': f'Bearer {OPENROUTER_KEY}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://github.com',
            'X-Title': 'Real Estate Proposal Generator'
        }
        user_content = [{'type': 'text', 'text': prompt + ' --aspect 16:9'}]
        for image_url in prepared[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]:
            user_content.append({'type': 'image_url', 'image_url': {'url': image_url}})
        payload = {
            'model': IMAGE_MODEL,
            'messages': [{'role': 'user', 'content': user_content}],
            'modalities': ['image', 'text']
        }
        response = requests.post(f'{OPENROUTER_BASE}/chat/completions', headers=headers, json=payload, timeout=120)
        data = response.json()
        generation_id, img_usage = _extract_openrouter_usage(data)
        _record_ai_usage(ctx, IMAGE_MODEL,
                         'ok' if response.status_code not in (401, 402, 429) and 'error' not in data else 'error',
                         img_usage, generation_id)
        if response.status_code in (401, 402, 429) or 'error' in data:
            print(f"[IMAGE ERROR] Visual concept multi-reference failed: {data.get('error') if isinstance(data, dict) else response.status_code}")
            return None
        image_url = _image_response_url(data)
        if image_url:
            return image_url
        print('[IMAGE ERROR] Multi-reference response contained no image; retrying with the first reference')
        return call_image_api_with_reference(prepared[0], prompt, usage_ctx=ctx)
    except Exception as error:
        print('[IMAGE ERROR]', error)
    return None


def _visual_concept_generate_prompt_text(facts, slot_id, current_prompt='', instruction='', image_references=None):
    current = _visual_concept_sanitize_prompt(current_prompt)
    request_text = _visual_concept_text(instruction, 4000)
    if current and request_text:
        system_prompt = (
            'You are a smart editor of an existing English architectural image prompt. '
            'The current prompt is the source of truth. Apply only the user request. '
            'Keep every other sentence, constraint, material, camera, and fact unless the user '
            'explicitly asks to rewrite, replace, or start over. '
            'If the user asks to add something, insert it into the existing prompt. '
            'If they ask to change one detail, change that detail only. '
            'Never invent a generic building style, never copy a previous project signature, '
            'and never add text, logos, people, or watermarks. '
            'Return JSON only: {"prompt":"...","reply":"..."}.'
        )
        user_prompt = (
            'Current prompt (do not discard):\n' + current
            + '\n\nUser request:\n' + request_text
        )
    else:
        system_prompt = (
            'You write one English architectural image prompt for a Saudi real-estate project. '
            'Use only the supplied project facts and attached references. '
            'Never invent a generic building style, never copy a previous project signature, '
            'and never add text, logos, people, or watermarks. '
            'Match the attached site/map footprint and any attached land photos. '
            'Return JSON only: {"prompt":"..."}.'
        )
        user_prompt = _visual_concept_facts_prompt(facts, slot_id)
        if current:
            user_prompt += '\n\nCurrent prompt to keep as the base:\n' + current
        if request_text:
            user_prompt += '\n\nUser request:\n' + request_text
    response = call_openrouter_chat(
        system_prompt,
        user_prompt,
        temperature=None,
        max_tokens=2500,
        model=GEMINI_TEXT_MODEL,
        response_format={'type': 'json_object'},
        image_references=image_references or None,
        usage_ctx=_usage_ctx('image'),
    )
    parsed = _designer_json_response(_get_chat_response_text(response) or extract_chat_content(response, 'VISUAL-CONCEPT-PROMPT'))
    prompt = _visual_concept_sanitize_prompt(parsed.get('prompt') or parsed.get('cover_prompt'))
    return prompt, parsed.get('reply') or ''


def _visual_concept_cover_image(data):
    cover = str(data.get('coverImage') or data.get('cover_image') or '').strip()
    # A blob: URL is meaningless outside the browser tab that made it, so an old draft
    # carrying one must fall back to the stored file instead of losing the cover reference.
    if cover and not cover.lower().startswith('blob:'):
        return cover
    file_id = _visual_concept_text(data.get('coverFileId') or data.get('cover_file_id'), 80)
    if file_id:
        return _visual_concept_project_file_data_uri(file_id) or ''
    return ''


def _visual_concept_collect_generation_references(facts, slot_id, cover_image=''):
    if slot_id == 'cover':
        file_ids = list(facts.get('style_reference_file_ids') or [])[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
        map_urls = []
        if len(file_ids) < VISUAL_CONCEPT_MAX_REFERENCE_IMAGES and facts.get('overview_map_url'):
            map_urls.append(facts['overview_map_url'])
        return _visual_concept_reference_uris(urls=map_urls, file_ids=file_ids)
    urls = [cover_image] if cover_image else []
    if _visual_concept_is_internal_slot(slot_id):
        file_ids = list(facts.get('interior_reference_file_ids') or [])[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
        return _visual_concept_reference_uris(
            urls=urls,
            file_ids=file_ids,
            max_images=VISUAL_CONCEPT_MAX_REFERENCE_IMAGES + 1,
            urls_first=True,
        )
    return _visual_concept_reference_uris(urls=urls, file_ids=[], urls_first=True)


def _visual_concept_request_bundle(data, slot_id):
    project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    creative = data.get('creativeImages') if isinstance(data.get('creativeImages'), dict) else {}
    if creative:
        existing = project_data.get('tenantCreativeImages') if isinstance(project_data.get('tenantCreativeImages'), dict) else {}
        project_data = {
            **project_data,
            'tenantCreativeImages': {**existing, **creative},
            'map_placeholders': creative.get('map_placeholders') or project_data.get('map_placeholders'),
        }
    facts = _visual_concept_facts(project_data)
    facts['slot_label'] = _visual_concept_text(data.get('slotLabel') or data.get('slot_label'), 80)
    requested_component_id = _visual_concept_text(data.get('componentId') or data.get('component_id'), 80)
    if _visual_concept_is_internal_slot(slot_id):
        if not requested_component_id:
            requested_component_id = _visual_concept_interior_component_id(slot_id)
        selected = next((item for item in (facts.get('components') or []) if item.get('id') == requested_component_id), None)
        if not selected and requested_component_id:
            selected = next((item for item in (facts.get('components') or []) if item.get('name') == requested_component_id), None)
        if not selected and (facts.get('components') or []):
            selected = facts['components'][0]
        facts['selected_component'] = selected or {}
        facts['interior_reference_file_ids'] = _visual_concept_list(
            data.get('referenceFileIds') or data.get('interiorReferenceFileIds')
        )[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]
    missing = _visual_concept_missing_fields(facts, slot_id)
    if _visual_concept_is_internal_slot(slot_id) and not (facts.get('selected_component') or {}).get('name'):
        missing.append({'key': 'project_components_data', 'label': 'اختر مكونًا فعليًا من الدراسة المالية'})
    return project_data, facts, missing


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
# Helper: record who changed what, on a presentation or a project file
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _record_change(target_type, target_id, action, details, source='manual', summary=''):
    """Write one history entry with its individual differences. Never fails a request."""
    try:
        lines = [line for line in (details or []) if str(line or '').strip()]
        if not lines and not summary:
            return None
        return db.log_change(
            g.tenant_id, target_type, target_id,
            getattr(g, 'user_id', None),
            getattr(g, 'user_name', None) or ('الذكاء الاصطناعي' if source == 'ai' else 'مستخدم غير معروف'),
            action, summary=summary, details=lines, source=source,
        )
    except Exception as exc:
        print(f'[CHANGE LOG] Could not record {action} on {target_type} {target_id}: {exc}')
        return None


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
        if data.startswith('data:image/') or (len(data) > 1000 and ';base64,' in data):
            return "[IMAGE_DATA_OMITTED]"
        return data
    else:
        return data

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GLM Parallel Batch Prompt Builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_GENERATION_PROJECT_IMAGE_CACHE = {}
_LOGO_APPEARANCE_CACHE = {}


TENANT_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')


def _tenant_image_storage_candidates(tenant_id, base_name):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return []
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(base_name or '')):
        return []
    tenant_dir = os.path.realpath(os.path.join(UPLOADS_DIR, str(tenant_id)))
    return [os.path.join(tenant_dir, f'{base_name}{extension}')
            for extension in TENANT_IMAGE_EXTENSIONS]


def _tenant_image_storage_path(tenant_id, base_name):
    candidates = [path for path in _tenant_image_storage_candidates(tenant_id, base_name)
                  if os.path.isfile(path)]
    return max(candidates, key=os.path.getmtime) if candidates else ''


def _tenant_logo_storage_path(tenant_id):
    stored = _tenant_image_storage_path(tenant_id, 'logo')
    if stored:
        return stored
    fallback = os.path.join(os.path.dirname(__file__), 'assets', 'logo.png')
    return fallback if os.path.isfile(fallback) else ''


def _tenant_watermark_storage_path(tenant_id):
    """Return only the tenant's uploaded watermark, with no logo fallback."""
    return _tenant_image_storage_path(tenant_id, 'watermark')


def _project_logo_storage_path(project_data, tenant_id):
    source = project_data if isinstance(project_data, dict) else {}
    meta = source.get('project_logo_file_meta') if isinstance(source.get('project_logo_file_meta'), dict) else {}
    file_id = source.get('project_logo_file_id') or meta.get('id')
    logo_value = str(source.get('project_logo') or '').strip()
    if not file_id and logo_value:
        match = re.search(r'/api/project-files/([^/?#]+)', logo_value)
        if match:
            file_id = match.group(1)
    if file_id:
        stored = db.get_project_file(tenant_id, str(file_id))
        if stored and stored.get('mime_type', '').startswith('image/'):
            path = _resolve_project_file_storage_path(stored, tenant_id)
            if path and os.path.isfile(path):
                return path
    relative = logo_value.split('?', 1)[0].lstrip('/')
    if relative.startswith('uploads/'):
        path = os.path.realpath(os.path.join(os.path.dirname(__file__), relative.replace('/', os.sep)))
        tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, str(tenant_id)))
        try:
            if os.path.commonpath([tenant_root, path]) == tenant_root and os.path.isfile(path):
                return path
        except ValueError:
            pass
    return ''


def _logo_pixel_luminance(red, green, blue):
    channels = [value / 255 for value in (red, green, blue)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _logo_appearance_from_path(path):
    if not path or not os.path.isfile(path):
        return 'unknown'
    stat = os.stat(path)
    key = (os.path.realpath(path), stat.st_mtime_ns, stat.st_size)
    cached = _LOGO_APPEARANCE_CACHE.get(key)
    if cached:
        return cached
    try:
        from PIL import Image
        with Image.open(path) as source:
            image = source.convert('RGBA')
            image.thumbnail((256, 256))
            width, height = image.size
            pixel_data = image.get_flattened_data() if hasattr(image, 'get_flattened_data') else image.getdata()
            pixels = list(pixel_data)
    except (OSError, ValueError):
        return 'unknown'
    visible = [pixel for pixel in pixels if pixel[3] >= 40]
    if not visible:
        return 'unknown'
    if len(visible) >= len(pixels) * 0.98 and width > 1 and height > 1:
        border = []
        for x in range(width):
            border.extend((image.getpixel((x, 0)), image.getpixel((x, height - 1))))
        for y in range(1, height - 1):
            border.extend((image.getpixel((0, y)), image.getpixel((width - 1, y))))
        background = tuple(sorted(pixel[channel] for pixel in border)[len(border) // 2]
                           for channel in range(3))
        foreground = [pixel for pixel in visible
                      if sum((pixel[channel] - background[channel]) ** 2 for channel in range(3)) >= 900]
        if len(foreground) >= max(12, len(visible) // 200):
            visible = foreground
    luminances = sorted(_logo_pixel_luminance(*pixel[:3]) for pixel in visible)
    median = luminances[len(luminances) // 2]
    light_share = sum(value >= 0.68 for value in luminances) / len(luminances)
    dark_share = sum(value <= 0.32 for value in luminances) / len(luminances)
    mean = sum(luminances) / len(luminances)
    tone = 'light' if median >= 0.58 or light_share >= 0.52 or (light_share >= 0.35 and dark_share < 0.25) else 'dark'
    if 0.48 < median < 0.58 and light_share < 0.35 and dark_share < 0.35:
        tone = 'light' if mean >= 0.55 else 'dark'
    _LOGO_APPEARANCE_CACHE[key] = tone
    return tone


def _prepare_generation_logo_context(project_data, branding, tenant_id):
    company_tone = _logo_appearance_from_path(_tenant_logo_storage_path(tenant_id))
    project_tone = _logo_appearance_from_path(_project_logo_storage_path(project_data, tenant_id))
    branding['_logo_tone'] = company_tone
    project_data['_company_logo_tone'] = company_tone
    project_data['_project_logo_tone'] = project_tone
    return company_tone, project_tone


def _generation_project_image_url(tenant_id, file_id):
    key = (str(tenant_id or ''), str(file_id or ''))
    if not all(key):
        return ''
    cached = _GENERATION_PROJECT_IMAGE_CACHE.get(key)
    if cached:
        return cached
    url = _publish_project_file_as_creative_image(file_id, tenant_id) or ''
    if url:
        _GENERATION_PROJECT_IMAGE_CACHE[key] = url
    return url


def _generation_asset_url(value, tenant_id=None):
    """Return a durable image URL from a visual-concept asset record."""
    source = value if isinstance(value, dict) else {'url': value}
    url = str(
        source.get('approvedImageUrl') or source.get('approved_image_url')
        or source.get('imageUrl') or source.get('image_url')
        or source.get('url') or source.get('path') or ''
    ).strip()
    # ``available`` is used by the compact planner payload and is not an image.
    if not url or url.lower() in {'available', 'blob:', 'undefined', 'null', 'none'} or url.lower().startswith('blob:'):
        url = ''
    if not url:
        file_id = source.get('fileId') or source.get('file_id') or source.get('sourceFileId') or source.get('source_file_id') or source.get('id')
        if file_id and str(file_id).strip() and not str(file_id).startswith('plan_'):
            url = _generation_project_image_url(tenant_id, file_id)
    if url and not url.startswith('/') and not url.startswith('http') and not url.startswith('data:'):
        url = '/' + url.lstrip('/')
    return url


def _visual_concept_generation_images(project_data, tenant_id):
    """Read every visual-concept image, including uploaded images still awaiting approval."""
    source = project_data if isinstance(project_data, dict) else {}
    visual = source.get('visual_concept')
    if isinstance(visual, str):
        visual = _visual_concept_parse_json(visual, {})
    visual = visual if isinstance(visual, dict) else {}
    slots = visual.get('slots') if isinstance(visual.get('slots'), dict) else {}
    creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}

    def slot_value(slot_id):
        aliases = {
            'right': ('right', 'east', 'east_facade'),
            'left': ('left', 'west', 'west_facade'),
            'top': ('top', 'aerial', 'above'),
            'back': ('back', 'rear', 'behind'),
        }
        for alias in aliases.get(slot_id, (slot_id,)):
            if isinstance(slots.get(alias), dict):
                return slots[alias]
        return {}

    moodboard = []
    moodboard_meta = []
    for slot_id in ('right', 'left', 'top', 'back'):
        item = slot_value(slot_id)
        url = _generation_asset_url(item, tenant_id)
        if not url:
            continue
        moodboard.append({
            'url': url,
            'label': str(item.get('label') or slot_id).strip(),
            'caption': str(item.get('caption') or '').strip(),
        })
        moodboard_meta.append({
            'label': str(item.get('label') or slot_id).strip(),
            'caption': str(item.get('caption') or '').strip(),
            'url': url,
        })
    if not moodboard:
        saved_moodboard = creative.get('moodboard')
        if isinstance(saved_moodboard, list):
            for index, item in enumerate(saved_moodboard, 1):
                url = _generation_asset_url(item, tenant_id)
                if not url:
                    continue
                source_item = item if isinstance(item, dict) else {}
                moodboard.append({
                    'url': url,
                    'label': str(source_item.get('label') or f'التصور الخارجي {index}').strip(),
                    'caption': str(source_item.get('caption') or '').strip(),
                })
                moodboard_meta.append({
                    'label': str(source_item.get('label') or f'التصور الخارجي {index}').strip(),
                    'caption': str(source_item.get('caption') or '').strip(),
                    'url': url,
                })

    component_rows = _visual_concept_components(source)
    component_by_id = {str(row.get('id')): row for row in component_rows}
    interior_groups = {}
    interior_order = []
    for slot_id, item in slots.items():
        slot_name = str(slot_id or '')
        if slot_name == 'interior':
            component_id, view_index = 'interior', 1
        elif slot_name.startswith('interior_'):
            remainder = slot_name[len('interior_'):]
            if '::' in remainder:
                component_id, raw_index = remainder.rsplit('::', 1)
                try:
                    view_index = int(raw_index)
                except (TypeError, ValueError):
                    view_index = 1
            else:
                component_id, view_index = remainder, 1
        else:
            continue
        url = _generation_asset_url(item, tenant_id)
        if not url:
            continue
        if component_id not in interior_groups:
            interior_groups[component_id] = []
            interior_order.append(component_id)
        interior_groups[component_id].append({
            'url': url,
            'label': str(item.get('label') or '').strip(),
            'caption': str(item.get('caption') or '').strip(),
            '_view_index': view_index,
        })

    interior_components = []
    ordered_component_ids = [str(row.get('id')) for row in component_rows if str(row.get('id')) in interior_groups]
    ordered_component_ids += [component_id for component_id in interior_order if component_id not in ordered_component_ids]
    for component_id in ordered_component_ids:
        items = sorted(interior_groups.get(component_id, []), key=lambda item: int(item.get('_view_index') or 1))
        row = component_by_id.get(component_id) or {}
        component_name = str(row.get('name') or ('التصميم الداخلي' if component_id == 'interior' else component_id)).strip()
        for item in items:
            item.pop('_view_index', None)
            if not item.get('label'):
                item['label'] = component_name
        if items:
            interior_components.append({'id': component_id, 'name': component_name, 'images': items})

    plans = []
    raw_plans = visual.get('plans2d') if isinstance(visual.get('plans2d'), list) else []
    for index, item in enumerate(raw_plans, 1):
        if not isinstance(item, dict):
            continue
        url = _generation_asset_url(item, tenant_id)
        if not url:
            continue
        plans.append({
            'url': url,
            'title': str(item.get('title') or item.get('fileName') or f'المخطط {index}').strip(),
            'description': str(item.get('description') or '').strip(),
            'name': str(item.get('fileName') or '').strip(),
        })

    cover_item = slot_value('cover') or slots.get('cover') or slots.get('main') or slots.get('primary') or {}
    cover_url = _generation_asset_url(cover_item, tenant_id)
    if not cover_url:
        cover_url = (
            _generation_asset_url(creative.get('cover'), tenant_id)
            or _generation_asset_url(creative.get('coverImage'), tenant_id)
            or _generation_asset_url(creative.get('mainImageData'), tenant_id)
            or _generation_asset_url(source.get('cover'), tenant_id)
            or _generation_asset_url(source.get('coverImage'), tenant_id)
            or _generation_asset_url(source.get('cover_image'), tenant_id)
            or _generation_asset_url(source.get('mainImageData'), tenant_id)
            or _generation_asset_url(source.get('project_image_cover'), tenant_id)
            or ''
        )

    return {
        'cover': cover_url,
        'moodboard': moodboard,
        'moodboard_meta': moodboard_meta,
        'interior_components': interior_components,
        'interior': [item['url'] for component in interior_components for item in component.get('images', []) if item.get('url')],
        'plans': plans,
        'plan_meta': [
            {'title': item.get('title') or '', 'description': item.get('description') or '', 'url': item.get('url') or ''}
            for item in plans
        ],
    }


def _augment_generation_images(images, project_data, tenant_id):
    result = dict(images) if isinstance(images, dict) else {}
    persisted_visual = _visual_concept_generation_images(project_data, tenant_id)

    def real_asset_count(values):
        if isinstance(values, list):
            return sum(bool(_generation_asset_url(item)) for item in values)
        return 0

    def real_component_asset_count(values):
        if not isinstance(values, list):
            return 0
        return sum(real_asset_count(component.get('images')) for component in values if isinstance(component, dict))

    if not result.get('cover'):
        result['cover'] = (
            persisted_visual.get('cover')
            or _generation_asset_url(result.get('cover'), tenant_id)
            or _generation_asset_url(result.get('coverImage'), tenant_id)
            or _generation_asset_url(result.get('mainImageData'), tenant_id)
            or _generation_asset_url((project_data or {}).get('cover'), tenant_id)
            or _generation_asset_url((project_data or {}).get('coverImage'), tenant_id)
            or _generation_asset_url((project_data or {}).get('cover_image'), tenant_id)
            or _generation_asset_url((project_data or {}).get('mainImageData'), tenant_id)
            or _generation_asset_url((project_data or {}).get('project_image_cover'), tenant_id)
            or ''
        )

    # A compact plan request carries the word ``available`` instead of URLs. If the client state
    # was stale, prefer the persisted visual-concept state when it contains more media so no
    # uploaded view disappears from the generated section.
    if real_asset_count(result.get('moodboard')) < real_asset_count(persisted_visual.get('moodboard')):
        result['moodboard'] = persisted_visual['moodboard']
        result['moodboard_meta'] = persisted_visual['moodboard_meta']
    if real_component_asset_count(result.get('interior_components')) < real_component_asset_count(persisted_visual.get('interior_components')):
        result['interior_components'] = persisted_visual['interior_components']
        result['interior'] = persisted_visual['interior']
    if real_asset_count(result.get('plans')) < real_asset_count(persisted_visual.get('plans')):
        result['plans'] = persisted_visual['plans']
        result['plan_meta'] = persisted_visual['plan_meta']
    team_members = []
    for entry in slide_engine._selected_team_entries(project_data or {}, tenant_id):
        file_id = entry.get('_logo_file_id') or ''
        team_members.append({
            'name': entry.get('الجهة') or '',
            'role': entry.get('الدور') or '',
            'logo': _generation_project_image_url(tenant_id, file_id) if file_id else '',
        })
    result['team_members'] = team_members
    market_state = (project_data or {}).get('market_study_data')
    if isinstance(market_state, str):
        try:
            market_state = json.loads(market_state)
        except (TypeError, ValueError):
            market_state = {}
    competitors = market_state.get('competitors') if isinstance(market_state, dict) else []
    competitor_logos = []
    for row in competitors if isinstance(competitors, list) else []:
        if not isinstance(row, dict):
            continue
        logo = str(row.get('logo_path') or row.get('logo_url') or '').strip()
        if not logo and row.get('logo_file_id'):
            logo = _generation_project_image_url(tenant_id, row['logo_file_id'])
        competitor_logos.append({'name': str(row.get('name') or '').strip(), 'logo': logo})
    result['competitor_logos'] = competitor_logos
    land_source = result.get('land_photos')
    if not isinstance(land_source, list):
        land_source = (project_data or {}).get('land_photos_file_meta')
    land_photos = []
    for item in land_source if isinstance(land_source, list) else []:
        source = item if isinstance(item, dict) else {}
        url = str(source.get('url') or source.get('imageUrl') or source.get('path') or '').strip()
        if url and not url.startswith('/') and not url.startswith('http'):
            url = '/' + url.lstrip('/')
        if not url and source.get('id'):
            url = _generation_project_image_url(tenant_id, source['id'])
        if url:
            land_photos.append({
                'url': url,
                'description': str(source.get('description') or source.get('caption') or '').strip(),
                'name': str(source.get('originalName') or source.get('name') or '').strip(),
            })
    result['land_photos'] = land_photos
    return result


def _presentation_creative_images(project_data, tenant_id):
    source = project_data if isinstance(project_data, dict) else {}
    saved = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
    return _augment_generation_images(saved, source, tenant_id)


def _get_images_info(images, project_data=None):
    interior_components = []
    moodboard_meta = []
    moodboard_items = []
    plan_meta = []
    land_photos = []
    team_members = []
    if isinstance(images, list):
        has_cover = bool(images[0]) if images else False
        moodboard_items = [(index, image) for index, image in enumerate(images[1:], 1) if image]
        moodboard_count = len(moodboard_items)
        interior_count = 0
        plans_count = 0
    elif isinstance(images, dict):
        has_cover = bool(images.get('cover'))
        moodboard_items = [(index, image) for index, image in enumerate(images.get('moodboard', []), 1) if image]
        moodboard_count = len(moodboard_items)
        moodboard_meta = images.get('moodboard_meta') if isinstance(images.get('moodboard_meta'), list) else []
        interior_components = images.get('interior_components', [])
        interior_count = sum(1 for img in images.get('interior', []) if img)
        plans_count = sum(1 for img in images.get('plans', []) if img)
        plan_meta = images.get('plan_meta') if isinstance(images.get('plan_meta'), list) else []
        land_photos = images.get('land_photos') if isinstance(images.get('land_photos'), list) else []
        team_members = images.get('team_members') if isinstance(images.get('team_members'), list) else []
    else:
        has_cover = False
        moodboard_count = 0
        interior_count = 0
        plans_count = 0

    # The design rules say to place ##PROJECT_LOGO## "if it exists", and the model had no way of
    # knowing whether it does, so an uploaded project logo was simply never used.
    project_source = project_data or {}
    company_tone = str(project_source.get('_company_logo_tone') or '').strip().lower()
    project_tone = str(project_source.get('_project_logo_tone') or '').strip().lower()
    tone_rules = {
        'light': 'فاتح — خلفية داكنة إلزامية، وممنوع وضعه مباشرة على الأبيض',
        'dark': 'داكن — خلفية بيضاء إلزامية، وممنوع وضعه مباشرة على الكحلي أو الأسود',
        'unknown': 'غير محسوم — لا تفترض لونًا مماثلًا لخلفيته',
    }
    info = f"- نتيجة تحليل شعار الشركة: شعار الشركة {tone_rules.get(company_tone, tone_rules['unknown'])}.\n"
    project_logo = str(project_source.get('project_logo') or '').strip()
    if project_logo:
        info += ("- شعار المشروع: متوفر ومرفوع من العميل. ضع ##PROJECT_LOGO## بجانب شعار الشركة "
                 "##LOGO## في هيدر كل شريحة محتوى، وفي الغلاف والختام معًا جنبًا إلى جنب بفاصل "
                 "رأسي رقيق بينهما. هذا إلزامي وليس اختياريًا. "
                 f"نتيجة التحليل: شعار المشروع {tone_rules.get(project_tone, tone_rules['unknown'])}.\n")
    else:
        info += "- شعار المشروع: لا يوجد — استخدم شعار الشركة ##LOGO## وحده ولا تكتب ##PROJECT_LOGO##.\n"
    info += f"- صورة الغلاف: {'متوفرة (استخدم ##IMAGE_COVER##)' if has_cover else 'لا توجد'}\n"
    if moodboard_count > 0:
        info += f"\n## التصورات الخارجية المتوفرة ({moodboard_count} صور)\n"
        info += "استخدم صورة واحدة كبيرة أو صورتين بحد أقصى في الصفحة، ويمكن استخدام أول صورتين غير رئيسيتين داخل نبذة عن المشروع. أنشئ صفحات إضافية حتى تظهر جميع الصور بوضوح:\n"
        for token_index, _image in moodboard_items:
            meta = moodboard_meta[token_index - 1] if token_index <= len(moodboard_meta) and isinstance(moodboard_meta[token_index - 1], dict) else {}
            label = str(meta.get('label') or f'التصور الخارجي {token_index}').strip()
            caption = str(meta.get('caption') or '').strip()
            info += f"- ##MOODBOARD_IMAGE_{token_index}## — {label}" + (f": {caption}" if caption else '') + "\n"
    else:
        info += "- صور التصورات الخارجية: لا توجد\n"

    if interior_components:
        info += f"\n## صور التصورات الداخلية موزعة حسب المكونات ({len(interior_components)} مكونات)\n"
        info += "اعرض صورة واحدة كبيرة أو صورتين بحد أقصى في الصفحة، ووزع بقية الصور على صفحات إضافية مع التسمية والوصف الصحيحين:\n"
        for c_idx, comp in enumerate(interior_components, 1):
            c_name = str(comp.get('name') or f'المكون {c_idx}').strip()
            c_imgs = comp.get('images', []) if isinstance(comp.get('images'), list) else []
            for image_index, image in enumerate(c_imgs, 1):
                source = image if isinstance(image, dict) else {}
                label = str(source.get('label') or c_name).strip()
                caption = str(source.get('caption') or '').strip()
                info += f"- ##INTERIOR_COMP_{c_idx}_IMG_{image_index}## — {c_name} — {label}" + (f": {caption}" if caption else '') + "\n"
    elif interior_count > 0:
        info += f"- صور التصورات الداخلية: ##INTERIOR_IMAGE_1## حتى ##INTERIOR_IMAGE_{interior_count}##، صورة واحدة كبيرة أو صورتان بحد أقصى في الصفحة.\n"

    if plans_count > 0:
        info += f"\n## المخططات المعمارية المرفوعة ({plans_count} مخططات)\n"
        for index in range(1, plans_count + 1):
            meta = plan_meta[index - 1] if index <= len(plan_meta) and isinstance(plan_meta[index - 1], dict) else {}
            title = str(meta.get('title') or meta.get('name') or f'المخطط {index}').strip()
            description = str(meta.get('description') or '').strip()
            info += f"- ##PLAN_IMAGE_{index}## — {title}" + (f": {description}" if description else '') + "\n"
        info += "كل مخطط له صفحة مستقلة أو مساحة كبيرة، ولا يجوز ضغط عدة مخططات في شبكة صغيرة.\n"

    if land_photos:
        info += f"\n## صور الأرض المرفوعة ({len(land_photos)} صور)\n"
        info += "اعرضها داخل قسم تحليل الأرض بصورة واحدة كبيرة أو صورتين بحد أقصى في الصفحة، ثم اعرض ملخص الأرض النهائي بعد صفحات الصور:\n"
        for index, photo in enumerate(land_photos, 1):
            source = photo if isinstance(photo, dict) else {}
            description = str(source.get('description') or '').strip()
            name = str(source.get('name') or f'صورة الأرض {index}').strip()
            info += f"- ##LAND_PHOTO_{index}## — {name}" + (f": {description}" if description else ': لا يوجد وصف محفوظ') + "\n"
    else:
        info += "- صور الأرض: لا توجد\n"

    if team_members:
        info += f"\n## شعارات فريق العمل ({len(team_members)} جهات مرتبة)\n"
        for index, member in enumerate(team_members, 1):
            source = member if isinstance(member, dict) else {}
            name = str(source.get('name') or f'الجهة {index}').strip()
            role = str(source.get('role') or '').strip()
            if source.get('logo'):
                info += f"- {name}" + (f" — {role}" if role else '') + f": الشعار متوفر ويجب استخدام ##TEAM_LOGO_{index}## عند ذكر الجهة.\n"
            else:
                info += f"- {name}" + (f" — {role}" if role else '') + ": لا يوجد شعار مرفوع؛ لا تنشئ بديلاً مصورًا.\n"

    # Map image placeholders (populated when project has location data). An absent map used to be
    # simply unmentioned, and the rules list every token, so the model wrote one anyway; the
    # unresolved token was then blanked and the slide shipped with an empty frame. Every map is
    # now named as available or as forbidden, exactly like ##PROJECT_LOGO##.
    map_placeholders = {
        '##MAP_OVERVIEW##': 'خريطة الموقع العامة',
        '##MAP_LANDMARKS##': 'خريطة المعالم المحيطة',
        '##MAP_ACCESS##': 'خريطة الوصول والطرق',
        '##MAP_CATCHMENT##': 'خريطة نطاق التأثير',
    }
    supplied_maps = images.get('map_placeholders') if isinstance(images, dict) else None
    available_maps = {placeholder for placeholder, path in (supplied_maps or {}).items() if path}
    for placeholder, label in map_placeholders.items():
        if placeholder in available_maps:
            info += f"- {label}: {placeholder}\n"
        else:
            info += f"- {label}: غير متوفرة — ممنوع كتابة {placeholder}\n"
    info += f"- {slide_engine.NO_STREET_VIEW_RULE}\n"
    if not has_cover:
        info += "- ممنوع كتابة ##IMAGE_COVER## أو ##MAIN_IMAGE## لعدم وجود صورة رئيسية معتمدة\n"
    if moodboard_count <= 0:
        info += "- ممنوع كتابة ##MOODBOARD_IMAGE_N## لعدم وجود صور للزوايا الخارجية\n"
    if not interior_components and interior_count <= 0:
        info += "- ممنوع كتابة ##INTERIOR_...## لعدم وجود صور تصور داخلي\n"
    if plans_count <= 0:
        info += "- ممنوع كتابة ##PLAN_IMAGE_N## أو ##2D_PLAN_N## لعدم وجود مخططات مرفوعة\n"
    if not land_photos:
        info += "- ممنوع كتابة ##LAND_PHOTO_N## لعدم وجود صور أرض مرفوعة\n"
    if not any(isinstance(member, dict) and member.get('logo') for member in team_members):
        info += "- ممنوع كتابة ##TEAM_LOGO_N## لعدم وجود شعارات فريق متاحة\n"
    
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
    """Build the shared system prompt ONCE for all slides."""
    if design_rules is None:
        design_rules = build_design_rules({})
    project_json = slide_engine.build_project_facts(project_data, getattr(g, 'tenant_id', None))
    timeline_note = slide_engine._timeline_data_note(project_data)
    financial_note = slide_engine._financial_data_note(project_data)
    return f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}
{timeline_note}
{financial_note}"""

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
        lowered = img_tag.lower()
        src_match = re.search(r'\bsrc\s*=\s*["\']([^"\']*)["\']', img_tag, flags=re.IGNORECASE)
        src_value = str(src_match.group(1) if src_match else '').strip()
        src_lower = src_value.lower()
        if src_lower.startswith('data:') or src_lower.startswith('blob:'):
            return img_tag
        if re.search(r'/tenant-assets/[^/]+/watermark(?:[?#]|$)', src_lower):
            return img_tag
        if '/uploads/creative/' in lowered or '/api/project-files/' in lowered or 'project-files' in lowered:
            return img_tag
        if 'project_logo' in lowered or '##project_logo##' in lowered or 'project-logo' in lowered:
            return img_tag
        # The managed chrome contains a company logo and, when available, a
        # project logo.  A resolved project-file URL does not contain the
        # semantic marker above, so the legacy compatibility pass used to
        # rewrite it back to the company logo.  Preserve resolved chrome URLs;
        # only placeholders and known company-logo fallbacks need replacement.
        if 'presentation-chrome-logo' in lowered:
            src = src_lower
            if src and not src.startswith('##') and not src.startswith('/assets/logo.png'):
                return img_tag
        tag_without_src = re.sub(r'src\s*=\s*["\'][^"\']*["\']', '', img_tag, flags=re.IGNORECASE).lower()
        if 'logo' in tag_without_src or '##LOGO##' in img_tag or 'tenant-assets' in img_tag:
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
    base_user_msg = slide_engine.build_slide_user_msg(slide, slide_num, total, branding, project_data=None)

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
            response = call_zai_chat(system_prompt, user_msg, max_tokens=7000, model=SLIDE_TEXT_MODEL, usage_ctx=_usage_ctx('slide'))
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
    images_info = _get_images_info(images, project_data)

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
        response = call_zai_chat(prompt, "قم بإنشاء العرض التقديمي الكامل.", max_tokens=16000, usage_ctx=_usage_ctx('slide'))

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
        response = call_zai_chat(prompt, f"اكتب الهيكل المكون من {target_count} شريحة.", max_tokens=4000, usage_ctx=_usage_ctx('slide_plan'))
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
        res = call_zai_chat(sys_prompt, user_msg, temperature=0.7, max_tokens=2500, usage_ctx=_usage_ctx('image'))
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


@app.route('/api/visual-concept/preflight', methods=['POST'])
@require_auth
def api_visual_concept_preflight():
    data = request.get_json(silent=True) or {}
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover') or 'cover'
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    return jsonify({
        'success': not missing,
        'slotId': slot_id,
        'missingFields': missing,
        'facts': {
            'project_name': facts.get('project_name'),
            'hasStyleReference': bool(facts.get('style_reference_file_ids')),
            'hasOverviewMap': bool(facts.get('overview_map_url')),
            'componentCount': len(facts.get('components') or []),
            'components': facts.get('components') or [],
        },
        'error': 'أكمل الحقول الناقصة قبل توليد التصور البصري' if missing else None,
        'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE' if missing else None,
    }), (400 if missing else 200)


@app.route('/api/visual-concept/prompt', methods=['POST'])
@require_auth
def api_visual_concept_prompt():
    data = request.get_json(silent=True) or {}
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return jsonify({
            'success': False,
            'error': 'أكمل الحقول الناقصة قبل إنشاء وصف التصور البصري',
            'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
            'missingFields': missing,
        }), 400
    cover_image = _visual_concept_cover_image(data)
    if slot_id != 'cover' and not cover_image:
        return jsonify({
            'success': False,
            'error': 'اعتمد الصورة الرئيسية قبل إنشاء وصف التصور البصري',
            'error_code': 'COVER_REQUIRED',
        }), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    current_prompt = _visual_concept_sanitize_prompt(data.get('currentPrompt') or data.get('prompt'))
    instruction = _visual_concept_text(data.get('instruction') or data.get('message'), 4000)
    try:
        prompt, reply = _visual_concept_generate_prompt_text(
            facts, slot_id, current_prompt=current_prompt, instruction=instruction, image_references=references
        )
        if not prompt:
            return jsonify({'success': False, 'error': 'تعذر إنشاء وصف التصور البصري', 'error_code': 'TEXT_PROVIDER_INVALID'}), 503
        return jsonify({
            'success': True,
            'slotId': slot_id,
            'prompt': prompt,
            'reply': reply,
            'referenceCount': len(references),
            'model': GEMINI_TEXT_MODEL,
        })
    except Exception:
        app.logger.exception('Visual concept prompt failed')
        return jsonify({'success': False, 'error': 'تعذر إنشاء وصف التصور البصري', 'error_code': 'TEXT_PROVIDER_FAILED'}), 503


@app.route('/api/visual-concept/generate', methods=['POST'])
@require_auth
def api_visual_concept_generate():
    data = request.get_json(silent=True) or {}
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return jsonify({
            'success': False,
            'error': 'أكمل الحقول الناقصة قبل توليد التصور البصري',
            'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
            'missingFields': missing,
        }), 400
    prompt = _visual_concept_sanitize_prompt(data.get('prompt'))
    if not prompt:
        return jsonify({'success': False, 'error': 'وصف التصور البصري مطلوب', 'error_code': 'PROMPT_REQUIRED'}), 400
    cover_image = _visual_concept_cover_image(data)
    if slot_id != 'cover' and not cover_image:
        return jsonify({
            'success': False,
            'error': 'اعتمد الصورة الرئيسية قبل توليد التصور البصري',
            'error_code': 'COVER_REQUIRED',
        }), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    image = call_image_api_with_references(prompt, references)
    if not image:
        if not OPENROUTER_KEY:
            return jsonify({'success': False, 'error': 'مفتاح OpenRouter غير مُعدّ', 'error_code': 'NO_API_KEY'}), 400
        return jsonify({'success': False, 'error': 'تعذر توليد صورة التصور البصري', 'error_code': 'IMAGE_FAILED'}), 503
    return jsonify({
        'success': True,
        'slotId': slot_id,
        'image': persist_generated_image(image, g.tenant_id),
        'prompt': prompt,
        'referenceCount': len(references),
        'model': IMAGE_MODEL,
    })


@app.route('/api/visual-concept/chat', methods=['POST'])
@require_auth
def api_visual_concept_chat():
    data = request.get_json(silent=True) or {}
    slot_id = _visual_concept_normalize_slot(data.get('slotId') or 'cover')
    if not slot_id:
        return jsonify({'success': False, 'error': 'نوع الصورة غير معروف', 'error_code': 'SLOT_INVALID'}), 400
    instruction = _visual_concept_text(data.get('message') or data.get('instruction'), 4000)
    if not instruction:
        return jsonify({'success': False, 'error': 'اكتب طلب التعديل أولاً', 'error_code': 'MESSAGE_REQUIRED'}), 400
    _project_data, facts, missing = _visual_concept_request_bundle(data, slot_id)
    if missing:
        return jsonify({
            'success': False,
            'error': 'أكمل الحقول الناقصة قبل تعديل التصور البصري',
            'error_code': 'VISUAL_CONCEPT_DATA_INCOMPLETE',
            'missingFields': missing,
        }), 400
    current_prompt = _visual_concept_sanitize_prompt(data.get('currentPrompt') or data.get('prompt'))
    cover_image = _visual_concept_cover_image(data)
    if slot_id != 'cover' and not cover_image:
        return jsonify({
            'success': False,
            'error': 'اعتمد الصورة الرئيسية قبل تعديل التصور البصري',
            'error_code': 'COVER_REQUIRED',
        }), 400
    references = _visual_concept_collect_generation_references(facts, slot_id, cover_image)
    try:
        prompt, reply = _visual_concept_generate_prompt_text(
            facts, slot_id, current_prompt=current_prompt, instruction=instruction, image_references=references
        )
        if not prompt:
            return jsonify({'success': False, 'error': 'تعذر تعديل وصف التصور البصري', 'error_code': 'TEXT_PROVIDER_INVALID'}), 503
        return jsonify({
            'success': True,
            'slotId': slot_id,
            'prompt': prompt,
            'reply': reply or 'تم تحديث وصف الصورة حسب طلبك.',
            'referenceCount': len(references),
        })
    except Exception:
        app.logger.exception('Visual concept chat failed')
        return jsonify({'success': False, 'error': 'تعذر تعديل وصف التصور البصري', 'error_code': 'TEXT_PROVIDER_FAILED'}), 503


@app.route('/api/designer-generate', methods=['POST'])
@require_auth
def api_designer_generate():
    """Generate slides HTML: variable slide count in parallel (4 concurrent workers)."""
    project_data = clean_project_data(request.json.get('projectData', {}))
    outline = request.json.get('outline', [])
    images = request.json.get('images', {})
    images_info = _get_images_info(images, project_data)

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
        response = call_zai_chat(prompt, "اكتب المحتوى.", max_tokens=2000, usage_ctx=_usage_ctx('slide'))
        content = extract_chat_content(response, "CONTENT")
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ai-edit-slide', methods=['POST'])
def api_ai_edit_slide():
    """Compatibility: AI edit a slide with Playwright Vision guidance"""
    data = request.json
    instruction = data.get('instruction', '') or data.get('editRequest', '') or data.get('message', '')
    slide_html = data.get('slideHtml', '') or data.get('slideContent', '') or data.get('currentSlideHtml', '')
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = data.get('presentationId')

    from auth import get_optional_tenant_id
    tenant_id = get_optional_tenant_id() or 'default'
    branding = db.get_branding(tenant_id) or {}
    requested_slide_type = data.get('slideType') or data.get('slide_type') or 'content'
    surface_note = '' if requested_slide_type in ('cover', 'closing', 'section_divider', 'moodboard') else (
        "\nهذه شريحة محتوى عادية: استخدم canvas أبيض أو فاتحاً موحداً، ولا تنشئ إطاراً داكناً حول صفحة بيضاء. "
        "الخلفية الداكنة الكاملة محجوزة للغلاف والخاتمة وفواصل الأقسام ذات الصورة. "
        "خلفية كل شعار مستقلة حسب لونه وتباينه، فلا تغيّر حاوية الشعار عند تغيير خلفية الشريحة."
    )

    vision_image_uri = None
    try:
        from generate_pdf_from_preview import render_slide_to_image_base64
        vision_image_uri = render_slide_to_image_base64(slide_html, branding=branding, tenant_id=tenant_id)
    except Exception as ve:
        print(f"[AI-EDIT VISION] Screenshot failed: {ve}")

    image_refs = [{"data_uri": vision_image_uri}] if vision_image_uri else None
    vision_note = (
        "\nتم تزويدك بلقطة شاشة مرئية فعلية للشريحة الحالية كما تظهر للمستخدم (1280x720). انظر للتنسيق ونفذ التعديل المطلوب بتناسق بصري."
        if vision_image_uri else ""
    )

    prompt = f"""عدّل الشريحة التالية حسب التعليمات:{vision_note}{surface_note}
التعليمات: {instruction}

الشريحة الحالية:
{slide_html}

بيانات المشروع:
{json.dumps(project_data, ensure_ascii=False, indent=2)}

أعد الشريحة بالـ HTML المعدّل."""

    try:
        response = call_zai_chat(prompt, "عدّل الشريحة.", max_tokens=4000, model=SLIDE_TEXT_MODEL, image_references=image_refs, usage_ctx=_usage_ctx('slide'))
        html = extract_chat_content(response, "EDIT")
        html = extract_html_from_glm({'choices': [{'message': {'content': html}}]})
        
        # Post-process and resolve placeholders
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
            slide_type=requested_slide_type,
        )
        html = resolve_designer_chat_placeholders(html, project_data, presentation_id, tenant_id,
                                                 data.get('creativeImages'))
        
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
        response = call_zai_chat(prompt, message, max_tokens=2000, usage_ctx=_usage_ctx('slide'))
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
        response = call_zai_chat(prompt, "اكتب النقاط.", max_tokens=1000, usage_ctx=_usage_ctx('slide'))
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
    """Render slide as image (returns base64 data URI via Playwright)"""
    data = request.json or {}
    slide_html = data.get('html', '')
    from auth import get_optional_tenant_id
    tenant_id = get_optional_tenant_id() or 'default'
    branding = db.get_branding(tenant_id) or {}
    try:
        from generate_pdf_from_preview import render_slide_to_image_base64
        uri = render_slide_to_image_base64(slide_html, branding=branding, tenant_id=tenant_id)
        if uri:
            return jsonify({'success': True, 'imageDataUri': uri, 'html': slide_html})
    except Exception as e:
        print(f"[RENDER-SLIDE-IMAGE ERROR] {e}")
    return jsonify({'success': True, 'html': slide_html})


# Last observed state of the slide renderer on this host, so /health can report whether the
# designer is editing with vision or blind instead of leaving it in a log file.
_SLIDE_VISION_STATE = {}


def _record_slide_vision_state(available, error='', source='edit'):
    _SLIDE_VISION_STATE.clear()
    _SLIDE_VISION_STATE.update({
        'available': bool(available),
        'error': str(error or '')[:300],
        'source': source,
        'checkedAt': datetime.now().isoformat(timespec='seconds'),
    })


def _designer_creative_images(project_data, creative_images=None):
    """The cover, moodboard and map images of the open presentation.

    `clean_project_data()` strips `creativeImages`, `mainImageData` and `moodboardImages` from
    project data, so reading them off `project_data` could never work: an edited slide kept its
    `##MOODBOARD_IMAGE_N##` markers and rendered as empty cards. The client sends the images in
    `creativeImages`, and a draft carries them under `tenantCreativeImages`.
    """
    if isinstance(creative_images, dict) and creative_images:
        return creative_images
    nested = project_data.get('tenantCreativeImages') if isinstance(project_data, dict) else None
    return nested if isinstance(nested, dict) else {}


def resolve_designer_chat_placeholders(html_out, project_data, presentation_id, tenant_id,
                                       creative_images=None):
    """Resolve map and creative image placeholders to their actual URLs."""
    if not html_out or '<div' not in html_out:
        return html_out

    creative = _designer_creative_images(project_data, creative_images)

    # 1. Gather all map placeholders
    map_placeholders = {}
    supplied_maps = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    for placeholder, url in supplied_maps.items():
        if placeholder and url:
            map_placeholders[placeholder] = url
    
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
    cover_url = (creative.get('cover') or creative.get('mainImageData')
                 or project_data.get('cover') or project_data.get('mainImageData') or '')
    moodboard = (creative.get('moodboard') or project_data.get('moodboard')
                 or project_data.get('moodboardImages') or [])
    
    if cover_url:
        html_out = html_out.replace('##IMAGE_COVER##', cover_url)
        html_out = html_out.replace('##COVER_IMAGE##', cover_url)
        html_out = html_out.replace('##MAIN_IMAGE##', cover_url)
        
    if isinstance(moodboard, list):
        for idx, mb_img in enumerate(moodboard):
            if mb_img:
                html_out = html_out.replace(f'##MOODBOARD_IMAGE_{idx + 1}##', mb_img)

    # An edited slide goes to the reader as it is, so a token with no image behind it must not
    # survive as an empty frame here either.
    return slide_engine._drop_unresolved_image_placeholders(html_out)


def _designer_json_response(text):
    """Parse the first JSON object returned by the designer model, with fallback extraction."""
    if not text:
        return {}
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    # Resilient fallback: extract "html" and "response" fields manually if JSON broken by quotes/newlines
    html_match = re.search(r'"(?:html|slide_html|content)"\s*:\s*"([\s\S]*?)(?<!\\)"\s*,\s*"(?:response|reply)"', cleaned)
    if not html_match:
        html_match = re.search(r'"(?:html|slide_html|content)"\s*:\s*"([\s\S]*?)(?<!\\)"\s*\}', cleaned)
    if html_match:
        extracted_html = html_match.group(1).replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
        resp_match = re.search(r'"(?:response|reply)"\s*:\s*"([\s\S]*?)(?<!\\)"', cleaned)
        resp_text = resp_match.group(1).replace('\\"', '"').replace('\\n', '\n') if resp_match else 'تم تحديث الشريحة بنجاح.'
        return {'html': extracted_html, 'response': resp_text}
    # Direct HTML slide block fallback
    div_match = re.search(r'<div\b[^>]*class=["\']slide["\'][\s\S]*?</div>\s*$', cleaned, flags=re.IGNORECASE)
    if div_match:
        return {'html': div_match.group(0), 'response': 'تم تحديث الشريحة بنجاح.'}
    return {}


def normalize_arabic_digits_py(text):
    if not text:
        return ""
    eastern = "٠١٢٣٤٥٦٧٨٩"
    western = "0123456789"
    return text.translate(str.maketrans(eastern, western))


def _slide_range_indexes(text, count):
    """Return zero-based indexes for numeric ranges such as «من 2 إلى 6»."""
    if not text or count <= 0:
        return []
    normalized = normalize_arabic_digits_py(text.lower())
    indexes = []
    for match in re.finditer(r'(?<!\d)(\d+)\s*(?:إلى|الى|حتى|لحد|[-–—])\s*(\d+)(?!\d)', normalized):
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            start, end = end, start
        for number in range(start, end + 1):
            index = number - 1
            if 0 <= index < count and index not in indexes:
                indexes.append(index)
    return indexes


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

    # 2. Expand numeric ranges before extracting individual numbers. The old parser stopped at
    # the first number in «من 2 إلى 6», so a request for a bounded group silently edited one slide.
    for idx in _slide_range_indexes(norm_text, count):
        if idx not in found_indexes:
            found_indexes.append(idx)

    # 3. Extract digits after trigger words (شريحة, شرايح, سلايد, رقم) or lists like "7 و 9 و 20"
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

    # 4. Check slide title and section matches
    if not found_indexes:
        norm_clean = re.sub(r'[^\w\s]', ' ', norm_text)
        sec_aliases = {
            'executive_summary': ['الملخص التنفيذي', 'ملخص تنفيذي', 'الملخص'],
            'financial': ['الدراسة المالية', 'التحليل المالي', 'الجانب المالي', 'دراسة مالية', 'المالية'],
            'location': ['تحليل الموقع', 'موقع المشروع', 'خريطة الموقع', 'الموقع'],
            'land': ['تحليل الأرض', 'كروكي الأرض', 'بيانات الأرض', 'الأرض', 'الارض'],
            'market': ['تحليل السوق', 'دراسة السوق', 'السوق'],
            'overview': ['نبذة عن المشروع', 'مقدمة المشروع', 'عن المشروع'],
            'components': ['مكونات المشروع', 'عناصر المشروع', 'المكونات'],
            'swot_risks': ['تحليل المخاطر', 'مصفوفة المخاطر', 'المخاطر', 'سوات', 'swot'],
            'timeline': ['الجدول الزمني', 'مراحل المشروع', 'الجدول'],
            'team': ['فريق العمل', 'فريق المشروع'],
            'visual_concept': ['التصور البصري', 'الهوية البصرية', 'الرؤية البصرية'],
            'cover': ['الغلاف', 'شريحة الغلاف'],
            'conclusion': ['الخاتمة', 'شريحة الختام'],
        }
        for idx, s in enumerate(slides):
            if not isinstance(s, dict):
                continue
            title = (s.get('title') or '').strip().lower()
            clean_title = re.sub(r'[^\w\s]', ' ', title).strip()
            if len(clean_title) >= 3 and (clean_title in norm_clean or any(part in norm_clean for part in clean_title.split(' - ') if len(part.strip()) >= 4)):
                if idx not in found_indexes:
                    found_indexes.append(idx)
                    break
            title_words = [w for w in clean_title.split() if len(w) >= 3 and w not in ('شريحة', 'صفحة', 'عرض', 'مشروع')]
            if len(title_words) >= 2:
                phrase = ' '.join(title_words[:2])
                if phrase in norm_clean and idx not in found_indexes:
                    found_indexes.append(idx)
                    break
            sec_key = (s.get('section_key') or s.get('sectionKey') or '').strip().lower()
            if sec_key and sec_key in sec_aliases:
                for alias in sec_aliases[sec_key]:
                    if alias in norm_clean:
                        if idx not in found_indexes:
                            found_indexes.append(idx)
                            break
                if found_indexes:
                    break

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


def _designer_actionable_edit_request(message):
    """Identify a concrete edit that should not be stalled by a needless clarification."""
    normalized = normalize_arabic_digits_py(str(message or '').lower())
    return bool(re.search(
        r'(?:لون|ألوان|الوان|خلفي|خط|عنوان|نص|هيدر|فوتر|بطاق|كارت|مساف|تباعد|حجم|عرض|ارتفاع|محاذاة|تنسيق|ترقيم|رقم|إزاحة|ازاحة|يمين|يسار|أعلى|اعلى|أسفل|اسفل|تصميم)',
        normalized,
    ))


_CANONICAL_MAP_TOKENS = {
    'overview': '##MAP_OVERVIEW##',
    'access': '##MAP_ACCESS##',
    'catchment': '##MAP_CATCHMENT##',
    'landmarks': '##MAP_LANDMARKS##',
}


def _canonical_map_type_for_slide(slide):
    """Infer the canonical map owned by a slide without asking the model."""
    item = slide if isinstance(slide, dict) else {}
    slide_type = str(item.get('type') or '').strip().lower()
    source = str(item.get('content_source') or item.get('contentSource') or '').strip().lower()
    title = normalize_arabic_digits_py(str(item.get('title') or '').strip().lower())
    raw_html = str(item.get('html') or '')
    html = raw_html.upper()

    explicit_map = re.search(
        r'data-canonical-map\s*=\s*["\'](overview|access|catchment|landmarks)["\']',
        raw_html, flags=re.IGNORECASE,
    )
    if explicit_map:
        return explicit_map.group(1).lower()

    for map_type in ('overview', 'access', 'catchment', 'landmarks'):
        if slide_type == f'map_{map_type}' or source in {
            map_type,
            f'{map_type}_areas',
            f'{map_type}_landmarks',
            f'{map_type}_roads',
        }:
            return map_type
        if _CANONICAL_MAP_TOKENS[map_type] in html:
            return map_type

    if any(term in title for term in ('النطاق الجغرافي', 'نطاق التأثير', 'استيعاب المنطقة', 'منطقة الخدمة')):
        return 'catchment'
    if any(term in title for term in ('الوصول', 'شبكة الطرق', 'الطرق الرئيسية', 'المحاور')):
        return 'access'
    if any(term in title for term in ('المعالم', 'الخدمات القريبة', 'أوقات القيادة')):
        return 'landmarks'
    if any(term in title for term in ('الموقع العام', 'خريطة الموقع', 'خريطة الأرض', 'النظرة العامة')):
        return 'overview'
    return ''


def _approved_canonical_map_url(map_type, project_data, creative_images=None):
    """Return only the already-persisted map; this helper never calls a map provider."""
    map_type = str(map_type or '').strip().lower()
    token = _CANONICAL_MAP_TOKENS.get(map_type)
    if not token:
        return ''
    creative = _designer_creative_images(project_data, creative_images)
    placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    approvals = creative.get('map_approvals') if isinstance(creative.get('map_approvals'), dict) else {}
    if map_type in approvals:
        approved = approvals.get(map_type)
        if not (approved is True or (isinstance(approved, str) and approved.strip().lower() in {'true', '1', 'yes'})):
            return ''
    base = token[:-2]
    for candidate in (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##'):
        value = placeholders.get(candidate)
        if value and not str(value).startswith('##'):
            return str(value)
    return ''


def _latest_canonical_map_url(map_type, project_data, creative_images=None,
                              tenant_id=None, presentation_id=None, preferred_images=None):
    """Return the newest saved final map for an explicit chat refresh.

    A map edit deliberately releases that map's approval until the user reviews
    it again. That is correct for the workflow, but it must not make an explicit
    "update the map in this slide" request keep the old raster image. This helper
    therefore ignores the approval flag, never calls Google, and prefers the
    current marked image from the project section over presentation snapshots.
    The sidecar is never a candidate here.
    """
    map_type = str(map_type or '').strip().lower()
    token = _CANONICAL_MAP_TOKENS.get(map_type)
    if not token:
        return ''

    canonical_types = {map_type, f'{map_type}_satellite', f'{map_type}_roadmap'}

    def usable_map_url(value):
        value = str(value or '').strip()
        if not value or value.startswith('##'):
            return False
        parsed = urlsplit(value)
        if parsed.path.startswith('/uploads/maps/'):
            relative = parsed.path.removeprefix('/uploads/maps/').replace('/', os.sep)
            maps_root = os.path.abspath(os.path.join(UPLOADS_DIR, 'maps'))
            candidate = os.path.abspath(os.path.join(maps_root, relative))
            if candidate != maps_root and not candidate.startswith(maps_root + os.sep):
                return False
            return os.path.isfile(candidate)
        # There is no live /api/map-images route.  Treating one as usable made
        # an old client URL win over the real persisted file and rendered a blank frame.
        if parsed.path.startswith('/api/map-images/'):
            return False
        # The browser must never receive a server filesystem path (for example
        # ``C:\\...`` or ``D:\\...``) as an image source.  It is not a URL and
        # silently renders as a missing image, while the persisted map row below
        # already has the public upload path we need.  Canonical maps are either
        # served from our map route or inline image data.  External map URLs are
        # deliberately excluded: an explicit refresh must copy the saved marked
        # raster, never a stale Google/CDN URL that can disappear or render a
        # different map after the response reaches the browser.
        if value.startswith('data:image/'):
            return True
        return False

    def public_map_url(file_path):
        """Convert a persisted map file to the only public route that serves it."""
        if not file_path or not os.path.isfile(file_path):
            return ''
        maps_root = os.path.realpath(os.path.join(UPLOADS_DIR, 'maps'))
        service_maps_root = os.path.realpath(getattr(maps_service, 'MAPS_DIR', maps_root))
        candidate = os.path.realpath(file_path)
        in_upload_maps = candidate == maps_root or candidate.startswith(maps_root + os.sep)
        in_service_maps = candidate == service_maps_root or candidate.startswith(service_maps_root + os.sep)
        if not (in_upload_maps or in_service_maps):
            return ''
        return '/uploads/maps/' + os.path.basename(candidate)

    # The location section is the source of truth for the image the user has just
    # approved or edited.  It is sent separately from project_data by the browser,
    # so prefer it before consulting map_images, whose rows can belong to an older
    # presentation snapshot.  This is only a file selection; it never generates a map.
    preferred_sources = list(preferred_images or [])
    preferred_sources.extend([creative_images, (project_data or {}).get('tenantCreativeImages')])
    for source in preferred_sources:
        if not isinstance(source, dict):
            continue
        placeholders = source.get('map_placeholders') if isinstance(source.get('map_placeholders'), dict) else {}
        base = token[:-2]
        for candidate in (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##'):
            value = placeholders.get(candidate)
            if usable_map_url(value):
                return str(value)

    draft_id = (project_data or {}).get('draftId') or (project_data or {}).get('draft_id')
    if tenant_id and (presentation_id or draft_id):
        try:
            rows = db.get_map_images(
                tenant_id,
                presentation_id=presentation_id,
                draft_id=draft_id if not presentation_id else None,
            )
        except Exception:
            rows = []
        for row in rows:
            if row.get('image_type') not in canonical_types:
                continue
            path = row.get('file_path')
            public_url = public_map_url(path)
            if public_url:
                return public_url

    # Compatibility fallback for an unsaved draft or a request carrying a map
    # that has not yet been written to map_images.
    sources = []
    nested = project_data.get('tenantCreativeImages') if isinstance(project_data, dict) else None
    if isinstance(nested, dict):
        sources.append(nested)
    if isinstance(creative_images, dict) and creative_images not in sources:
        sources.append(creative_images)
    base = token[:-2]
    candidates = (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##')
    for creative in sources:
        placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
        for candidate in candidates:
            value = placeholders.get(candidate)
            if usable_map_url(value):
                return str(value)
    return ''


def _replace_slide_with_approved_map(html, map_type, map_url):
    """Replace a slide's map media with one approved image and remove duplicate map tags."""
    if not html or not map_url:
        return html, False
    token = _CANONICAL_MAP_TOKENS.get(str(map_type or '').strip().lower())
    if not token:
        return html, False

    base = token[:-2]
    map_tokens = (token, f'{base}_SATELLITE##', f'{base}_ROADMAP##')
    output = str(html)
    for candidate in map_tokens:
        output = output.replace(candidate, map_url)

    map_ref = re.compile(r'(?:/uploads/maps/|/api/map-images/|maps/|##map_)', re.IGNORECASE)
    map_url_ref = str(map_url).lower()
    media_tags = []
    tag_pattern = re.compile(r'<[a-z][^>]*>', re.IGNORECASE)
    for match in tag_pattern.finditer(output):
        tag = match.group(0)
        lowered = tag.lower()
        is_image = lowered.startswith('<img')
        is_map_background = (
            'data-map-summary-background' in lowered
            or bool(re.search(r'background(?:-image)?\s*:', lowered) and map_ref.search(lowered))
        )
        if is_image and (map_ref.search(lowered) or map_url_ref in lowered):
            media_tags.append(('image', match))
        elif is_map_background:
            media_tags.append(('background', match))

    changed = False
    if media_tags:
        # A map slide can contain both a legacy background placeholder on the
        # root element and the real image slot inside its content grid.  The
        # root background is covered by the slide's white content surface, so
        # prefer an image element whenever one exists.  Selecting the first
        # tag blindly made the refresh appear successful while leaving the
        # visible image slot empty.
        image_media = [(kind, match) for kind, match in media_tags if kind == 'image']
        dedicated_backgrounds = [
            (kind, match) for kind, match in media_tags
            if kind == 'background' and re.search(
                r'data-canonical-map\s*=|data-map-summary-background\b',
                match.group(0),
                flags=re.IGNORECASE,
            )
        ]
        # Newer map slides use a dedicated background layer inside the map
        # panel.  It is more authoritative than the legacy root background,
        # which is normally covered by the slide content surface.
        first_kind, first = (
            image_media[0] if image_media else
            dedicated_backgrounds[0] if dedicated_backgrounds else
            media_tags[0]
        )
        first_tag = first.group(0)
        if first_kind == 'image':
            src_pattern = re.compile(r'(\bsrc\s*=\s*)(["\'])(.*?)(\2)', re.IGNORECASE | re.DOTALL)
            if src_pattern.search(first_tag):
                first_tag = src_pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}{map_url}{m.group(4)}', first_tag, count=1)
            else:
                first_tag = re.sub(r'\s*/>$', '>', first_tag)
                first_tag = first_tag[:-1] + f' src="{map_url}">'
        else:
            background_pattern = re.compile(
                r'(background(?:-image)?\s*:\s*url\(\s*["\']?)([^)"\']+)(["\']?\s*\))',
                re.IGNORECASE,
            )
            first_tag = background_pattern.sub(
                lambda m: f'{m.group(1)}{map_url}{m.group(3)}', first_tag, count=1
            )
        if 'data-canonical-map=' not in first_tag.lower():
            first_tag = re.sub(r'\s*/>$', '>', first_tag)
            first_tag = first_tag[:-1] + f' data-canonical-map="{map_type}">'
        replacements = [(first.start(), first.end(), first_tag)]
        for kind, match in media_tags:
            if match is first:
                continue
            if kind == 'image':
                # There must be one visible canonical image, not a stack of
                # old and new rasters in the same slide.
                replacements.append((match.start(), match.end(), ''))
            else:
                # Keep the element itself intact.  Removing only its opening
                # tag can unbalance the HTML, and a duplicate background is
                # unnecessary once the visible image slot is authoritative.
                background_tag = match.group(0)
                background_tag = re.sub(
                    r'(background(?:-image)?\s*):\s*url\([^)]*\)',
                    lambda m: f'{m.group(1)}:none',
                    background_tag,
                    count=1,
                    flags=re.IGNORECASE,
                )
                replacements.append((match.start(), match.end(), background_tag))
        # Sort by source position because the visible image is often after
        # the root background in the tag list.  Applying an earlier, shorter
        # replacement first would invalidate the later match offsets.
        for start, end, value in sorted(replacements, key=lambda item: item[0], reverse=True):
            output = output[:start] + value + output[end:]
        changed = True
    elif token in output or map_url in output:
        changed = map_url in output
    else:
        closing = re.search(r'</div>\s*$', output, re.IGNORECASE)
        if closing:
            map_markup = (
                f'<div data-canonical-map="{map_type}" style="position:absolute;left:40px;right:40px;'
                f'top:120px;bottom:70px;z-index:1;display:flex;align-items:center;justify-content:center;overflow:hidden;">'
                f'<img src="{map_url}" alt="" style="width:100%;height:100%;object-fit:contain;object-position:center center;"></div>'
            )
            output = output[:closing.start()] + map_markup + output[closing.start():]
            changed = True

    return output, changed


def is_watermark_request(message):
    """Detect requests to add or remove slide watermarks or subtle background logos."""
    if not message:
        return False
    normalized = normalize_arabic_digits_py(str(message).strip().lower())
    patterns = (
        r'watermark',
        r'(?:ال)?(?:وتر|ووتر)\s*مارك',
        r'(?:ال)?علام[ةه]\s*(?:ال)?مائي[ةه]',
        r'(?:ال)?(?:شعار|لوجو)\s*(?:ال)?مائي',
        r'(?:ال)?(?:شعار|لوجو)\s*كـ?علام[ةه]\s*مائي[ةه]',
        r'(?:ال)?(?:شعار|لوجو)\s*(?:في|كـ?|بـ?)?\s*(?:ال)?خلفي[ةه]',
        r'(?:ال)?(?:شعار|لوجو)\s*(?:خفيف|باهت)',
    )
    return any(re.search(pat, normalized) for pat in patterns)


# Named CSS colors used on slides. Any company brand color arrives as hex or as
# rgb()/hsl() and is measured by luminance below — detection never depends on
# a fixed brand palette, so a new company color cannot break it.
_CSS_NAMED_COLORS = {
    'black': '#000000', 'white': '#ffffff',
    'navy': '#000080', 'darkblue': '#00008b', 'mediumblue': '#0000cd', 'blue': '#0000ff',
    'royalblue': '#4169e1', 'steelblue': '#4682b4', 'skyblue': '#87ceeb',
    'lightskyblue': '#87cefa', 'lightblue': '#add8e6', 'powderblue': '#b0e0e6',
    'midnightblue': '#191970', 'slateblue': '#6a5acd', 'darkslateblue': '#483d8b',
    'indigo': '#4b0082', 'darkviolet': '#9400d3', 'blueviolet': '#8a2be2',
    'purple': '#800080', 'darkred': '#8b0000', 'red': '#ff0000', 'maroon': '#800000',
    'brown': '#a52a2a', 'chocolate': '#d2691e', 'sienna': '#a0522d',
    'orange': '#ffa500', 'darkorange': '#ff8c00', 'coral': '#ff7f50',
    'tomato': '#ff6347', 'orangered': '#ff4500', 'salmon': '#fa8072',
    'darksalmon': '#e9967a', 'lightsalmon': '#ffa07a',
    'pink': '#ffc0cb', 'lightpink': '#ffb6c1', 'hotpink': '#ff69b4',
    'gold': '#ffd700', 'goldenrod': '#daa520', 'darkgoldenrod': '#b8860b',
    'yellow': '#ffff00', 'lightyellow': '#ffffe0', 'lemonchiffon': '#fffacd',
    'lightgoldenrodyellow': '#fafad2', 'khaki': '#f0e68c', 'darkkhaki': '#bdb76b',
    'olive': '#808000', 'olivedrab': '#6b8e23', 'darkolivegreen': '#556b2f',
    'yellowgreen': '#9acd32', 'greenyellow': '#adff2f', 'chartreuse': '#7fff00',
    'lawngreen': '#7cfc00', 'lime': '#00ff00', 'limegreen': '#32cd32',
    'springgreen': '#00ff7f', 'mediumspringgreen': '#00fa9a',
    'forestgreen': '#228b22', 'green': '#008000', 'darkgreen': '#006400',
    'seagreen': '#2e8b57', 'mediumseagreen': '#3cb371', 'lightgreen': '#90ee90',
    'palegreen': '#98fb98', 'teal': '#008080', 'lightseagreen': '#20b2aa',
    'turquoise': '#40e0d0', 'mediumturquoise': '#48d1cc', 'darkturquoise': '#00ced1',
    'paleturquoise': '#afeeee', 'aqua': '#00ffff', 'cyan': '#00ffff',
    'gray': '#808080', 'grey': '#808080', 'darkgray': '#a9a9a9', 'darkgrey': '#a9a9a9',
    'dimgray': '#696969', 'dimgrey': '#696969', 'slategray': '#708090',
    'slategrey': '#708090', 'darkslategray': '#2f4f4f', 'darkslategrey': '#2f4f4f',
    'lightslategray': '#778899', 'lightslategrey': '#778899', 'silver': '#c0c0c0',
    'lightgray': '#d3d3d3', 'lightgrey': '#d3d3d3', 'gainsboro': '#dcdcdc',
    'whitesmoke': '#f5f5f5', 'ghostwhite': '#f8f8ff', 'aliceblue': '#f0f8ff',
    'azure': '#f0ffff', 'mintcream': '#f5fffa', 'honeydew': '#f0fff0',
    'beige': '#f5f5dc', 'ivory': '#fffff0', 'linen': '#faf0e6',
    'seashell': '#fff5ee', 'snow': '#fffafa', 'floralwhite': '#fffaf0',
    'oldlace': '#fdf5e6', 'cornsilk': '#fff8dc', 'papayawhip': '#ffefd5',
    'blanchedalmond': '#ffebcd', 'bisque': '#ffe4c4', 'moccasin': '#ffe4b5',
    'navajowhite': '#ffdead', 'wheat': '#f5deb3', 'tan': '#d2b48c',
}


def _parse_css_color_to_rgb(value):
    """Parse any CSS color (hex, rgb()/rgba(), hsl()/hsla(), named) into (r, g, b, alpha)."""
    text = str(value or '').strip().lower()
    if not text or text == 'transparent':
        return None
    short = re.fullmatch(r'#([0-9a-f]{3})', text)
    if short:
        digits = short.group(1)
        return (int(digits[0] * 2, 16), int(digits[1] * 2, 16), int(digits[2] * 2, 16), 1.0)
    full = re.fullmatch(r'#([0-9a-f]{6})', text)
    if full:
        digits = full.group(1)
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), 1.0)
    rgb = re.fullmatch(r'rgba?\(\s*([^)]+)\)', text)
    if rgb:
        parts = [part.strip() for part in rgb.group(1).split(',')]
        if len(parts) in (3, 4):
            try:
                channels = []
                for part in parts[:3]:
                    if part.endswith('%'):
                        channels.append(min(255.0, max(0.0, float(part[:-1]) * 2.55)))
                    else:
                        channels.append(min(255.0, max(0.0, float(part))))
                alpha = 1.0
                if len(parts) == 4:
                    alpha_text = parts[3]
                    alpha = float(alpha_text[:-1]) / 100.0 if alpha_text.endswith('%') else float(alpha_text)
                    alpha = min(1.0, max(0.0, alpha))
                return (channels[0], channels[1], channels[2], alpha)
            except (TypeError, ValueError):
                pass
    hsl = re.fullmatch(r'hsla?\(\s*([^)]+)\)', text)
    if hsl:
        parts = [part.strip() for part in hsl.group(1).split(',')]
        if len(parts) in (3, 4):
            try:
                hue = (float(parts[0].rstrip('deg')) % 360.0) / 360.0
                saturation = min(1.0, max(0.0, float(parts[1].rstrip('%')) / 100.0))
                lightness = min(1.0, max(0.0, float(parts[2].rstrip('%')) / 100.0))
                red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
                alpha = 1.0
                if len(parts) == 4:
                    alpha_text = parts[3]
                    alpha = float(alpha_text[:-1]) / 100.0 if alpha_text.endswith('%') else float(alpha_text)
                    alpha = min(1.0, max(0.0, alpha))
                return (red * 255.0, green * 255.0, blue * 255.0, alpha)
            except (TypeError, ValueError):
                pass
    named = _CSS_NAMED_COLORS.get(text)
    if named:
        return _parse_css_color_to_rgb(named)
    return None


def _css_color_luminance(value):
    """WCAG relative luminance (0-1) of any CSS color, composited over white when translucent."""
    parsed = _parse_css_color_to_rgb(value)
    if not parsed:
        return None
    red, green, blue, alpha = parsed
    red = alpha * red + (1.0 - alpha) * 255.0
    green = alpha * green + (1.0 - alpha) * 255.0
    blue = alpha * blue + (1.0 - alpha) * 255.0
    linear = []
    for channel in (red / 255.0, green / 255.0, blue / 255.0):
        channel = min(1.0, max(0.0, channel))
        linear.append(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _is_white_or_light_slide(slide, minimum_luminance=0.45):
    """Check whether a slide has a white or light background.

    Every background color in every shade is measured by luminance, so any
    company brand color is classified correctly without a fixed palette.
    """
    if not isinstance(slide, dict):
        return True
    stype = str(slide.get('type') or 'content').lower()
    if stype in ('cover', 'divider', 'back_cover', 'closing', 'section_divider', 'index'):
        return False
    html = str(slide.get('html') or '')
    if re.search(
        r'class=["\'][^"\']*\b(?:dark-slide|cover-slide|divider-slide|slide-dark|bg-dark|dark-mode)\b',
        html,
        flags=re.IGNORECASE,
    ):
        return False
    color_token = r'(?:#[0-9a-f]{3,6}\b|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-z]+)'
    # The root slide background decides: a white slide holding dark cards inside is
    # still a white slide, while a dark root stays dark even with light cards in it.
    # The class token must be exactly `slide` — `\bslide\b` also matches
    # `slide-inner` / `slide-footer`, which would read the wrong element.
    root_style = ''
    for root_candidate in re.finditer(r'<div\b[^>]*>', html, flags=re.IGNORECASE):
        tag_text = root_candidate.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if not class_match:
            continue
        if 'slide' not in class_match.group(1).split():
            continue
        style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if style_match:
            root_style = style_match.group(1)
        break
    if root_style:
        root_colors = []
        for background in re.findall(r'background(?:-color)?\s*:\s*([^;]+)', root_style, flags=re.IGNORECASE):
            root_colors.extend(re.findall(color_token, background, flags=re.IGNORECASE))
        measured = []
        for color in root_colors:
            luminance = _css_color_luminance(color)
            if luminance is not None:
                measured.append(luminance)
        if measured:
            return all(value >= minimum_luminance for value in measured)
    # Fallback when the root carries no explicit background: only a full-cover
    # background layer decides. Header/footer/table-header colors are dark by
    # design on white slides and must never flip a white slide to dark — that
    # is what silently skipped white slides from an only-white watermark run.
    for tag in re.finditer(r'<div\b[^>]*\bstyle\s*=\s*["\']([^"\']*)["\'][^>]*>', html, flags=re.IGNORECASE):
        style = tag.group(1) or ''
        lowered = style.lower()
        if 'absolute' not in lowered:
            continue
        compact = lowered.replace(' ', '')
        full_cover = (
            'inset:0' in compact
            or ('top:0' in compact and 'bottom:0' in compact and 'left:0' in compact and 'right:0' in compact)
            or ('width:1280' in compact and 'height:720' in compact)
        )
        if not full_cover:
            continue
        layer_colors = []
        for background in re.findall(r'background(?:-color)?\s*:\s*([^;]+)', style, flags=re.IGNORECASE):
            layer_colors.extend(re.findall(color_token, background, flags=re.IGNORECASE))
        for color in layer_colors:
            luminance = _css_color_luminance(color)
            if luminance is not None and luminance < minimum_luminance:
                return False
    return True


# The watermark always renders above slide content layers (opaque cards and
# images used to bury it at z-index 0). Its full-slide overlay stays
# click-through; in manual edit mode the client enables pointer events only on
# the visible logo so it can be selected without blocking the slide beneath it.
WATERMARK_Z_INDEX = 50


def _watermark_src_key(url):
    """Normalized watermark src for staleness checks (ignores cache-busters)."""
    return str(url or '').split('?', 1)[0].split('#', 1)[0].strip()


def _refresh_watermark_source(html, new_url):
    """Point an existing watermark layer at the current company file.

    Only the ``<img>`` src is swapped; position, size, opacity and hidden
    state are preserved. Returns the HTML unchanged when there is no layer
    or when it already points at the current file.
    """
    if not html or not new_url:
        return html
    spec = _watermark_spec_from_html(html)
    if not spec or not spec.get('markup'):
        return html
    if _watermark_src_key(spec.get('logo_url')) == _watermark_src_key(new_url):
        return html
    markup = spec['markup']
    refreshed, count = re.subn(
        r'(<img\b[^>]*\bsrc\s*=\s*["\'])[^"\']+(["\'])',
        lambda match: match.group(1) + new_url + match.group(2),
        markup, count=1, flags=re.IGNORECASE,
    )
    if not count:
        return html
    return html.replace(markup, refreshed, 1)


def _apply_slide_watermark(html, logo_url, opacity=0.045, width_px=480):
    """Inject an elegant watermark overlay on top of a slide's content layers.

    A single centered layer only. Re-applying never duplicates the layer and
    never resets a user move/resize/opacity: a visible watermark keeps its
    geometry and is only re-pointed at the current company file, a hidden
    one is unhidden with its saved geometry intact.
    """
    if not html:
        return html
    existing = _watermark_spec_from_html(html)
    if existing:
        refreshed = _refresh_watermark_source(html, logo_url)
        if existing.get('visible', True):
            return refreshed
        return _set_slide_watermark_visible(refreshed, True, logo_url)
    try:
        opacity_value = float(opacity)
    except (TypeError, ValueError):
        opacity_value = 0.045
    # Owner rule: an explicit user opacity is honored up to fully opaque (1.0).
    # The subtle default (0.045) stays at the call sites that omit it.
    opacity_value = min(1.0, max(0.01, opacity_value))
    try:
        width_value = int(width_px)
    except (TypeError, ValueError):
        width_value = 480
    width_value = min(900, max(200, width_value))
    cleaned = _remove_slide_watermark(html)
    watermark_markup = (
        '<div class="slide-watermark" data-slide-watermark="true" data-watermark-visible="true" aria-hidden="true" '
        'style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;'
        f'pointer-events:none;z-index:{WATERMARK_Z_INDEX};opacity:{opacity_value};overflow:hidden;">'
        f'<img src="{logo_url}" alt="" style="width:{width_value}px;max-width:50%;max-height:50%;object-fit:contain;filter:{slide_engine.WATERMARK_GRAY_FILTER};">'
        '</div>'
    )
    # The overlay is absolutely positioned, so the slide root must establish
    # positioning; most templates already carry position:relative.
    root_tag = re.search(r'<div\b[^>]*>', cleaned, flags=re.IGNORECASE)
    if root_tag:
        tag_text = root_tag.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if class_match and 'slide' in class_match.group(1).split():
            style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
            if style_match and 'position' not in style_match.group(1).lower():
                fixed_tag = tag_text.replace(
                    style_match.group(0),
                    'style="' + 'position:relative;' + style_match.group(1) + '"',
                    1,
                )
                cleaned = cleaned[:root_tag.start()] + fixed_tag + cleaned[root_tag.end():]
    closing = re.search(r'</div>\s*$', cleaned, flags=re.IGNORECASE)
    if not closing:
        return cleaned + watermark_markup
    return cleaned[:closing.start()] + watermark_markup + cleaned[closing.start():]


def _remove_slide_watermark(html):
    """Remove watermark overlay markup from a slide HTML."""
    if not html:
        return html
    cleaned = re.sub(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>[\s\S]*?</div>',
        '',
        html,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>[\s\S]*?</div>',
        '',
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _watermark_spec_from_html(html):
    """Read the watermark overlay spec (logo, opacity, width, visibility).

    Overlays saved before the visibility flag carry no
    ``data-watermark-visible`` attribute and count as visible, so opening an
    older presentation never flips them off.
    """
    if not html:
        return None
    match = re.search(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>([\s\S]*?)</div\s*>',
        str(html),
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>([\s\S]*?)</div\s*>',
            str(html),
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    full_markup = match.group(0)
    div_tag = full_markup[:full_markup.find('>') + 1]
    inner = match.group(1) or ''
    opacity = 0.045
    opacity_match = re.search(r'opacity\s*:\s*([0-9.]+)', div_tag, flags=re.IGNORECASE)
    if opacity_match:
        try:
            opacity = float(opacity_match.group(1))
        except (TypeError, ValueError):
            opacity = 0.045
    width = 480
    width_match = re.search(r'width\s*:\s*(\d+)\s*px', inner, flags=re.IGNORECASE)
    if width_match:
        try:
            width = int(width_match.group(1))
        except (TypeError, ValueError):
            width = 480
    logo_match = re.search(r'<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', inner, flags=re.IGNORECASE)
    logo_url = logo_match.group(1).strip() if logo_match else ''
    if not logo_url:
        return None
    visible_match = re.search(r'data-watermark-visible\s*=\s*["\']([^"\']*)["\']', div_tag, flags=re.IGNORECASE)
    if visible_match:
        visible = visible_match.group(1).strip().lower() != 'false'
    else:
        visible = True
    if re.search(r'display\s*:\s*none', div_tag, flags=re.IGNORECASE):
        visible = False
    return {'logo_url': logo_url, 'opacity': opacity, 'width_px': width,
            'visible': visible, 'markup': full_markup}


def _watermark_markup_from_html(html):
    """Return the raw watermark overlay markup, or an empty string."""
    spec = _watermark_spec_from_html(html)
    return spec.get('markup', '') if spec else ''


def _is_watermark_visible(html):
    """Whether the slide currently shows its watermark layer."""
    spec = _watermark_spec_from_html(html)
    return bool(spec and spec.get('visible', True))


def _set_slide_watermark_visible(html, visible, logo_url=None):
    """Show or hide the watermark layer while keeping its geometry.

    Hiding keeps position, size and opacity in the saved HTML so showing it
    again restores exactly what the user had. Showing a hidden layer never
    rebuilds it from defaults.
    """
    if not html:
        return html
    spec = _watermark_spec_from_html(html)
    if not spec:
        if not visible or not logo_url:
            return html
        return _apply_slide_watermark(html, logo_url)
    # Showing an existing layer also re-points it at the current company
    # file, so a replaced upload appears in place of the old mark without
    # losing the saved position/size/opacity.
    if visible and logo_url:
        html = _refresh_watermark_source(html, logo_url)
        spec = _watermark_spec_from_html(html) or spec
    if bool(spec.get('visible', True)) == bool(visible):
        # Already in the requested state, but the src refresh above (if any)
        # is still returned so a replaced file appears without another toggle.
        return html
    markup = spec.get('markup', '')
    if not markup:
        return html
    div_end = markup.find('>')
    if div_end == -1:
        return html
    div_tag = markup[:div_end + 1]
    rest = markup[div_end + 1:]
    if re.search(r'data-watermark-visible\s*=', div_tag, flags=re.IGNORECASE):
        div_tag = re.sub(
            r'data-watermark-visible\s*=\s*["\'][^"\']*["\']',
            'data-watermark-visible="%s"' % ('true' if visible else 'false'),
            div_tag, count=1, flags=re.IGNORECASE,
        )
    else:
        div_tag = div_tag[:-1] + ' data-watermark-visible="%s">' % ('true' if visible else 'false')
    if visible:
        div_tag = re.sub(r'display\s*:\s*none\s*;?', 'display:flex;', div_tag, flags=re.IGNORECASE)
        if 'display' not in div_tag.lower():
            div_tag = div_tag[:-1] + ' style="display:flex;">' if 'style=' not in div_tag.lower() else div_tag
    else:
        if re.search(r'display\s*:\s*flex', div_tag, flags=re.IGNORECASE):
            div_tag = re.sub(r'display\s*:\s*flex', 'display:none', div_tag, count=1, flags=re.IGNORECASE)
        elif re.search(r'display\s*:', div_tag, flags=re.IGNORECASE):
            div_tag = re.sub(r'display\s*:\s*[^;]+', 'display:none', div_tag, count=1, flags=re.IGNORECASE)
        else:
            style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', div_tag, flags=re.IGNORECASE)
            if style_match:
                div_tag = (div_tag[:style_match.start(2)] + 'display:none;'
                           + style_match.group(2) + div_tag[style_match.end(2):])
            else:
                div_tag = div_tag[:-1] + ' style="display:none;">'
    return html.replace(markup, div_tag + rest, 1)


def _carry_slide_watermark(source_html, output_html):
    """Keep a slide watermark across model regeneration that drops it.

    The model rebuilds the whole slide and almost never reproduces the overlay
    div, so without this any later AI edit silently deletes the watermark.
    The saved layer is copied verbatim — source, position, size, opacity and
    hidden state — so a user move is never lost and a hidden watermark is
    never reshown without a request.
    """
    if not output_html or _watermark_spec_from_html(output_html):
        return output_html
    spec = _watermark_spec_from_html(source_html)
    if not spec or not spec.get('markup'):
        return output_html
    markup = spec['markup']
    cleaned = _remove_slide_watermark(output_html)
    root_tag = re.search(r'<div\b[^>]*>', cleaned, flags=re.IGNORECASE)
    if root_tag:
        tag_text = root_tag.group(0)
        class_match = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
        if class_match and 'slide' in class_match.group(1).split():
            style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', tag_text, flags=re.IGNORECASE)
            if style_match and 'position' not in style_match.group(1).lower():
                fixed_tag = tag_text.replace(
                    style_match.group(0),
                    'style="' + 'position:relative;' + style_match.group(1) + '"',
                    1,
                )
                cleaned = cleaned[:root_tag.start()] + fixed_tag + cleaned[root_tag.end():]
    closing = re.search(r'</div>\s*$', cleaned, flags=re.IGNORECASE)
    if not closing:
        return cleaned + markup
    return cleaned[:closing.start()] + markup + cleaned[closing.start():]


def _is_watermark_removal_instruction(instruction):
    """Check whether an edit instruction asks to remove the watermark itself."""
    normalized = normalize_arabic_digits_py(str(instruction or '').strip().lower())
    if not re.search(r'(?:احذف|حذف|امسح|إزالة|ازالة|ازل|شيل|اخف|إخفاء|اخفاء|خف|عطل|عطّل|تعطيل|لغاء\s*(?:ال)?تفعيل|ايقاف|إيقاف)', normalized):
        return False
    return bool(re.search(r'(?:watermark|الوترمارك|الووترمارك|العلامة|علامة\s*مائي|لوجو|شعار)', normalized))


def _designer_deterministic_plan(message, slides, current_index, target_indexes):
    """Handle unambiguous structural commands without spending a planner turn first."""
    if not message or not slides:
        return None
    normalized = normalize_arabic_digits_py(str(message).strip().lower())
    numbers = [idx + 1 for idx in (target_indexes or [])]

    if is_watermark_request(message):
        is_remove = bool(re.search(r'(?:احذف|حذف|امسح|إزالة|ازالة|ازل|شيل|اخف|إخفاء|اخفاء|خف|عطّل|عطل|تعطيل|لغاء\s*(?:ال)?تفعيل|ايقاف|إيقاف)', normalized))
        only_white = bool(re.search(r'(?:البيضاء|البيضه|الابيض|الأبيض|white|الفاتحة|الفاتحه)', normalized))
        all_match = any(kw in normalized for kw in ('كل', 'جميع', 'كافة', 'العرض كامل', 'العرض كله', 'الشرائح كلها', 'الشرايح كلها'))
        # No scope named: the current slide only. "All" needs an explicit كل/جميع.
        target_mode = 'all' if all_match else ('indexes' if numbers else 'current')
        action_tool = 'remove_watermark' if is_remove else 'apply_watermark'
        # «إظهار» names visibility, never size: only an explicit bigger/clearer
        # request grows the mark.
        size_up = bool(re.search(r'(?:أكبر|اكبر|كبّر|كبر|واضح|واضحه|أوضح|اوضح|ظاهر|أجلى|اجلى|bigger|\bbig\b|\bclear\b|clearer)', normalized))
        size_down = bool(re.search(r'(?:أصغر|اصغر|صغّر|صغر|أخف|اخف|خفيف|خفيفه|شفاف|أفتح|افتح|smaller|\bsmall\b|\bfaint\b)', normalized))
        if size_up and not size_down:
            wm_opacity, wm_width = 0.10, 640
        elif size_down and not size_up:
            wm_opacity, wm_width = 0.03, 400
        else:
            wm_opacity, wm_width = 0.045, 480
        if is_remove:
            resp_text = 'سأنفذ حذف العلامة المائية مع الحفاظ على كامل محتوى الشرائح.'
        elif size_up and not size_down:
            resp_text = 'سأجعل العلامة المائية أكبر وأوضح في خلفية الشرائح مع الحفاظ التام على النصوص والتصميم.'
        elif only_white:
            resp_text = 'سأضيف العلامة المائية المعتمدة في خلفية الشرائح البيضاء مع الحفاظ التام على النصوص والتصميم.'
        else:
            resp_text = 'سأضيف العلامة المائية المعتمدة في خلفية الشرائح المحددة بأناقة وتناسق بصري تام.'
        return {
            'response': resp_text,
            'actions': [{
                'tool': action_tool,
                'params': {
                    'target': target_mode,
                    'indexes': numbers if target_mode == 'indexes' else [],
                    'only_white': only_white,
                    'opacity': wm_opacity,
                    'width_px': wm_width,
                },
            }],
        }

    is_map_reload = bool(
        re.search(r'(?:إعادة|اعادة|اعاده|أعد|اعد|عيد|رجع|رجّع|حدّث|حدث|تحديث|جدّد|جدد|استبدل|استبدال)', normalized)
        and re.search(r'(?:خريطة|الخريطة|الخريطه|map)', normalized)
    )
    if is_map_reload:
        number = numbers[0] if numbers else current_index + 1
        index = number - 1
        map_type = _canonical_map_type_for_slide(slides[index]) if 0 <= index < len(slides) else ''
        if map_type:
            return {
                'response': f'سأحدّث خريطة الشريحة رقم {number} من أحدث نسخة محفوظة، دون طلب خريطة جديدة من جوجل.',
                'actions': [{'tool': 'insert_canonical_map', 'params': {
                    'target': 'indexes', 'indexes': [number], 'map_type': map_type,
                    'refresh': True,
                }}],
            }

    # Creative, redesign, or multi-slide generative requests belong to the AI agent
    creative_patterns = (
        r'(?:اعد|أعد|اعادة|إعادة)\s*(?:توليد|تصميم|صياغة|بناء|ابتكار)',
        r'(?:صمم|ابتكر|طور|تطوير|حدث|تحديث)',
        r'(?:مصمم[ةه]|قوي[ةه]|بصري[ااً]|ابداع|فخم|فخم[ةه]|عصري|احترافي)',
        r'(?:اكثر|أكثر)\s*من\s*شريح[ةه]',
        r'علي\s*اكثر|على\s*أكثر|على\s*اكثر|علي\s*أكثر',
        r'شرايح\s*متعدد[ةه]|شرائح\s*متعدد[ةه]',
        r'(?:تحسين|تطوير|تجديد|ابتكار)\s*(?:التصميم|الشكل|المظهر)',
    )
    if any(re.search(pat, normalized) for pat in creative_patterns):
        return None

    if re.search(r'(?:احذف|حذف|امسح|إزالة|ازالة)\s*(?:الشريحة|شريحة|السلايد|سلايد)', normalized):
        targets = sorted(set(numbers or [current_index + 1]), reverse=True)
        return {
            'response': 'سأنفذ حذف الشرائح المحددة مع الحفاظ على ترتيب بقية العرض.',
            'actions': [{'tool': 'delete_slide', 'params': {'slide_number': number}} for number in targets],
        }

    if re.search(r'(?:كرر|تكرار|انسخ|استنسخ|استنساخ|دبلر)\s*(?:الشريحة|شريحة|السلايد|سلايد)', normalized):
        number = numbers[0] if numbers else current_index + 1
        return {
            'response': f'سأنشئ نسخة من الشريحة رقم {number} مع إبقاء النسخة الأصلية.',
            'actions': [{'tool': 'duplicate_slide', 'params': {'slide_number': number}}],
        }

    move_match = re.search(
        r'(?:انقل|حرك|غيّر\s*ترتيب|غير\s*ترتيب)\s*(?:الشريحة|شريحة|السلايد|سلايد)?\s*(\d+)\s*'
        r'(?:إلى|الى|لمكان|مكان|لتصبح|لتكون)\s*(?:الشريحة|شريحة|السلايد|سلايد)?\s*(\d+)',
        normalized,
    )
    if move_match:
        from_number, to_number = int(move_match.group(1)), int(move_match.group(2))
        return {
            'response': f'سأنقل الشريحة رقم {from_number} إلى الموضع رقم {to_number}.',
            'actions': [{'tool': 'reorder_slides', 'params': {
                'from_index': from_number, 'to_index': to_number,
            }}],
        }

    if designer_chat_reliability.is_split_request(message):
        detected = detect_slide_indexes_from_message_py(message, slides)
        number = numbers[0] if numbers else ((detected[0] + 1) if detected else current_index + 1)
        return {
            'response': f'سأقسم محتوى الشريحة رقم {number} إلى أجزاء متوازنة مع الحفاظ على كامل المحتوى دون فقد أي تفاصيل.',
            'actions': [{'tool': 'split_slide', 'params': {'slide_number': number, 'instruction': message}}],
        }
    return None


def _designer_team_logo_search_text(value):
    """Normalize a team name or chat text for explicit logo matching."""
    normalized = normalize_arabic_digits_py(str(value or '').casefold())
    normalized = re.sub(r'[^\w\u0600-\u06ff]+', ' ', normalized, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', normalized).strip()


def _designer_company_logo_requested(message):
    """Recognize an explicit company-brand request before consulting older team-logo context.

    Only the definite «الشركة» or the tenant's own proper nouns count as the company.
    A bare «شركة» also starts team entity names («شركة الأصالة») and must stay on the
    team-logo path when the message names that entity.
    """
    text = _designer_team_logo_search_text(message)
    has_logo_word = bool(re.search(r'(?:logo|لوجو|شعار|علامة\s*تجارية)', text, flags=re.IGNORECASE))
    has_company_word = bool(re.search(
        r'(?:الشركة|company|branding|بوابة\s*الرؤية|الرؤية\s*للتطوير)',
        text, flags=re.IGNORECASE,
    ))
    return has_logo_word and has_company_word


def _designer_team_logo_context(creative_images):
    """Describe the selected team logos to the designer without conflating them with branding."""
    members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
    lines = []
    for index, member in enumerate(members or [], 1):
        if not isinstance(member, dict):
            continue
        name = str(member.get('name') or f'الجهة {index}').strip()
        role = str(member.get('role') or '').strip()
        token = f'##TEAM_LOGO_{index}##'
        suffix = f' — {role}' if role else ''
        if member.get('logo'):
            lines.append(f'- {name}{suffix}: الشعار متوفر؛ استخدم {token} عند طلب شعار هذه الجهة.')
        else:
            lines.append(f'- {name}{suffix}: لا يوجد شعار مرفوع؛ لا تنشئ بديلاً.')
    if not lines:
        return 'لا توجد شعارات جهات فريق عمل متاحة في هذا المشروع.'
    return '\n'.join(lines)


def _find_designer_team_logo_request(message, history, creative_images):
    """Resolve a named team entity in a logo request to its exact TEAM_LOGO token.

    The current message alone must carry logo intent (شعار/لوجو/logo). Older turns
    only resolve *which* entity a follow-up means («لم تتم إضافة اللوجو حل المشكلة»),
    so a later «أضف وصفاً للصور» or «أعد تصميم الشريحة» never inherits a previous
    logo request. A description/caption request (وصف/شرح/تعليق) and a generic image
    request (صورة/تصميم/توليد) are not logo requests.
    """
    if _designer_company_logo_requested(message):
        return None
    members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
    if not isinstance(members, list) or not members:
        return None
    current_search = _designer_team_logo_search_text(message)
    if not re.search(r'(?:logo|لوجو|شعار|علامة\s*تجارية)', current_search, flags=re.IGNORECASE):
        return None
    with_logo = [
        (index, member)
        for index, member in enumerate(members, 1)
        if isinstance(member, dict) and member.get('logo')
    ]
    if not with_logo:
        return None
    for index, member in with_logo:
        name = str(member.get('name') or '').strip()
        name_key = _designer_team_logo_search_text(name)
        if name_key and len(name_key) >= 3 and name_key in current_search:
            return {
                'index': index,
                'name': name,
                'role': str(member.get('role') or '').strip(),
                'logo': str(member.get('logo') or '').strip(),
                'token': f'##TEAM_LOGO_{index}##',
            }
    # Follow-up without repeating the name («ضيف الشعار»، «لم تتم إضافة اللوجو حلها»):
    # resolve to the most recently named entity in earlier user turns.
    user_turns = [
        str(item.get('content') or '')
        for item in history if isinstance(item, dict) and item.get('role') == 'user'
    ]
    for past in reversed(user_turns):
        past_search = _designer_team_logo_search_text(past)
        if not past_search:
            continue
        for index, member in with_logo:
            name = str(member.get('name') or '').strip()
            name_key = _designer_team_logo_search_text(name)
            if name_key and len(name_key) >= 3 and name_key in past_search:
                return {
                    'index': index,
                    'name': name,
                    'role': str(member.get('role') or '').strip(),
                    'logo': str(member.get('logo') or '').strip(),
                    'token': f'##TEAM_LOGO_{index}##',
                }
    return None


def _inject_team_logo_fallback(html, team_logo, team_index):
    """Keep a named team logo visible if the model returned valid HTML without inserting it."""
    if not html or not team_logo or team_logo in html:
        return html
    safe_url = html_lib.escape(str(team_logo), quote=True)
    markup = (
        f'<div data-team-logo-placement="{int(team_index)}" '
        'style="position:absolute;left:44px;top:94px;width:188px;height:72px;'
        'display:flex;align-items:center;justify-content:center;z-index:4;overflow:hidden;'
        'padding:8px 12px;box-sizing:border-box;background:#0c2340;border-radius:8px;">'
        f'<img class="team-logo" src="{safe_url}" alt="" '
        'style="width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain;object-position:center center;">'
        '</div>'
    )
    closing = re.search(r'</div>\s*$', html, flags=re.IGNORECASE)
    if not closing:
        return html
    return html[:closing.start()] + markup + html[closing.start():]


def _inject_company_logo_panel_fallback(html, logo_url):
    """Put the company logo in the right content panel when the model omitted the requested move."""
    if not html:
        return html
    existing_logo_tags = [
        tag for tag in re.findall(r'<img\b[^>]*>', html, flags=re.IGNORECASE)
        if logo_url and logo_url in tag and 'presentation-chrome-logo' not in tag.lower()
    ]
    if existing_logo_tags or 'data-company-logo-placement="right-panel"' in html:
        return html
    source = html_lib.escape(str(logo_url or '##LOGO##'), quote=True)
    markup = (
        '<div data-company-logo-placement="right-panel" '
        'style="position:absolute;right:54px;top:92px;width:180px;height:62px;'
        'display:flex;align-items:center;justify-content:center;z-index:6;overflow:hidden;'
        'padding:6px 10px;box-sizing:border-box;background:#0c2340;border-radius:8px;">'
        f'<img class="company-content-logo" src="{source}" alt="" '
        'style="width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain;object-position:center center;">'
        '</div>'
    )
    closing = re.search(r'</div>\s*$', html, flags=re.IGNORECASE)
    if not closing:
        return html
    return html[:closing.start()] + markup + html[closing.start():]


def _find_component_reference_image(component_query, project_data, creative_images=None):
    """Search project and creative data for reference images belonging to a component or query."""
    if not component_query:
        return []
    query_str = str(component_query).strip().lower()
    creative = _designer_creative_images(project_data, creative_images) if isinstance(project_data, dict) else (creative_images or {})
    references = []

    # 1. Search interior components in creative_images and project_data
    int_comps = creative.get('interior_components') or (project_data.get('interior_components') if isinstance(project_data, dict) else []) or (project_data.get('interiorComponents') if isinstance(project_data, dict) else [])
    if isinstance(int_comps, list):
        for comp in int_comps:
            if not isinstance(comp, dict):
                continue
            name = str(comp.get('name') or '').strip().lower()
            if name and (name in query_str or query_str in name):
                for img in comp.get('images') or []:
                    uri = img.get('data_uri') or img.get('url') or img.get('file_path') or (img if isinstance(img, str) else '')
                    if uri and uri not in references:
                        references.append(uri)

    # 2. Search project components list
    proj_comps = (project_data.get('project_components') or project_data.get('components') or project_data.get('components_data')) if isinstance(project_data, dict) else []
    if isinstance(proj_comps, list):
        for comp in proj_comps:
            if not isinstance(comp, dict):
                continue
            name = str(comp.get('name') or comp.get('title') or '').strip().lower()
            if name and (name in query_str or query_str in name):
                for key in ('image', 'image_url', 'reference_image', 'data_uri'):
                    val = comp.get(key)
                    if val and val not in references:
                        references.append(val)

    # 3. Search moodboard / exterior
    moodboard = creative.get('moodboard') or (project_data.get('moodboard') if isinstance(project_data, dict) else [])
    moodboard_meta = creative.get('moodboard_meta') or (project_data.get('moodboard_meta') if isinstance(project_data, dict) else [])
    if isinstance(moodboard, list) and isinstance(moodboard_meta, list):
        for idx, img in enumerate(moodboard):
            meta = moodboard_meta[idx] if idx < len(moodboard_meta) and isinstance(moodboard_meta[idx], dict) else {}
            lbl = str(meta.get('label') or meta.get('caption') or '').strip().lower()
            if lbl and (lbl in query_str or query_str in lbl):
                if img and img not in references:
                    references.append(img)

    # 4. Search plans
    plans = creative.get('plans') or (project_data.get('plans') if isinstance(project_data, dict) else [])
    plan_meta = creative.get('plan_meta') or (project_data.get('plan_meta') if isinstance(project_data, dict) else [])
    if isinstance(plans, list) and isinstance(plan_meta, list):
        for idx, img in enumerate(plans):
            meta = plan_meta[idx] if idx < len(plan_meta) and isinstance(plan_meta[idx], dict) else {}
            lbl = str(meta.get('title') or meta.get('name') or meta.get('description') or '').strip().lower()
            if lbl and (lbl in query_str or query_str in lbl):
                if img and img not in references:
                    references.append(img)

    return references[:VISUAL_CONCEPT_MAX_REFERENCE_IMAGES]


def _build_designer_section_and_asset_context(slides, project_data, current_index, creative_images=None):
    """Build full situational and section asset audit context for Sol the designer."""
    slides_count = len(slides)
    cur_slide = slides[current_index] if 0 <= current_index < slides_count and isinstance(slides[current_index], dict) else {}
    cur_title = cur_slide.get('title', f'شريحة {current_index + 1}')

    # Audit map usage across slides
    map_usage = {
        '##MAP_OVERVIEW##': 0,
        '##MAP_ACCESS##': 0,
        '##MAP_CATCHMENT##': 0,
        '##MAP_LANDMARKS##': 0,
    }
    for s in slides:
        html = s.get('html', '') if isinstance(s, dict) else ''
        for k in map_usage:
            if k in html:
                map_usage[k] += 1

    audit_lines = [
        f"## الموقف التنفيذي وتدقيق الأصول المتاحة للعرض ({slides_count} شريحة):",
        f"- الشريحة الحالية المعروضة أمام المستخدم: [{current_index + 1}] '{cur_title}'",
        "- حالة الخرائط الأربع الرئيسية في العرض:",
        f"  1. خريطة النظرة العامة (##MAP_OVERVIEW##): مستخدمة {map_usage['##MAP_OVERVIEW##']} مرة",
        f"  2. خريطة شبكة الطرق والوصول (##MAP_ACCESS##): مستخدمة {map_usage['##MAP_ACCESS##']} مرة",
        f"  3. خريطة النطاق الجغرافي واستيعاب المنطقة (##MAP_CATCHMENT##): مستخدمة {map_usage['##MAP_CATCHMENT##']} مرة",
        f"  4. خريطة المعالم الحيوية القريبة (##MAP_LANDMARKS##): مستخدمة {map_usage['##MAP_LANDMARKS##']} مرة",
        "- تنبيه الخرائط: يمكنك استخدام أي من هذه الخرائط الأربع في أي شريحة من العرض بحرية تامة بتضمين الرمز المقابل.",
    ]

    audit_lines.extend([
        "- تمييز الشعارات: ##LOGO## للشركة فقط، ##PROJECT_LOGO## لشعار المشروع فقط، وشعارات جهات فريق العمل تستخدم ##TEAM_LOGO_N## حسب ترتيب القائمة التالية. ممنوع إدراج أي شعار إلا إذا طلب المستخدم ذلك صراحة بكلمة شعار أو لوجو أو علامة تجارية في رسالته الحالية؛ فالصورة والوصف والشعار ثلاثة أشياء مختلفة: الوصف نص يضاف لصور موجودة، والصورة توليد معماري جديد، والشعار رمز جهة مرفوع.",
        "## شعارات جهات فريق العمل المتاحة:",
        _designer_team_logo_context(creative_images),
    ])

    # Components list
    comps = (project_data.get('interior_components') or project_data.get('components') or []) if isinstance(project_data, dict) else []
    if isinstance(comps, list) and comps:
        comp_names = [str(c.get('name') or c.get('title') or '').strip() for c in comps if isinstance(c, dict) and (c.get('name') or c.get('title'))]
        if comp_names:
            audit_lines.append(f"- مكونات المشروع المسجلة: {', '.join(comp_names[:12])}")

    return "\n".join(audit_lines)


def _sanitize_designer_output(html):
    """Sanitize designer output strictly according to platform quality and compliance rules (Pillar 7).
    
    1. Zero emojis (stripped).
    2. Zero icon fonts, icon glyphs, or decorative SVGs.
    3. Replaces direction arrows with explicit Arabic words.
    4. Strips any how-to instructional hints.
    5. Ensures standard slide container bounds (1280x720, overflow:hidden).
    """
    if not html:
        return html

    # Replace arrow glyphs with explicit Arabic words
    arrow_replacements = {
        '\u2191': 'أعلى',
        '\u2193': 'أسفل',
        '\u2192': 'يمين',
        '\u2190': 'يسار',
        '\u25B2': 'أعلى',
        '\u25BC': 'أسفل',
        '\u25BA': 'يمين',
        '\u25C4': 'يسار',
        '\u27A4': 'يمين',
        '\u279C': 'يمين',
        '\u2B06': 'أعلى',
        '\u2B07': 'أسفل',
        '\u27A1': 'يمين',
        '\u2B05': 'يسار',
    }
    for arrow_char, ar_word in arrow_replacements.items():
        if arrow_char in html:
            html = html.replace(arrow_char, ar_word)

    # Strip emojis and decorative icon markup
    html = slide_engine._strip_presentation_icons(html)

    # Strip instructional how-to phrasing if any was generated
    how_to_patterns = [
        r'اضغط\s+على\s+[^<]+',
        r'اضغط\s+هنا\s+[^<]*',
        r'اختر\s+من\s+القائمة\s+[^<]*',
        r'راجع\s+أولاً\s+[^<]*',
        r'يرجى\s+مراجعة\s+[^<]*',
        r'قم\s+بالضغط\s+[^<]*',
    ]
    for pat in how_to_patterns:
        html = re.sub(pat, '', html, flags=re.IGNORECASE)

    return html


def _is_land_boundary_diagram_slide(title=None, content_source=None, html=None):
    """Detect the deterministic land-boundary diagram slide.

    It is the only slide the system rebuilds from documented land facts
    (content_source == 'land_boundary_diagram'), so the designer model must
    receive those facts explicitly — otherwise it claims success without any
    visible change.
    """
    if str(content_source or '').strip() == 'land_boundary_diagram':
        return True
    title_text = str(title or '')
    if 'مخطط اتجاهي' in title_text or 'حدود الأرض' in title_text:
        return True
    html_text = str(html or '')
    if 'data-boundary-diagram' in html_text or 'data-boundary-direction' in html_text:
        return True
    return False


def _designer_boundary_facts_note(project_data):
    """Render the documented boundary facts for the designer-chat prompt."""
    try:
        data = slide_engine._extract_land_boundary_diagram_data(
            project_data if isinstance(project_data, dict) else {}
        )
    except Exception:
        return ''
    if not isinstance(data, dict):
        return ''
    lines = []
    for key, label in (('north', 'الشمال'), ('south', 'الجنوب'),
                       ('east', 'الشرق'), ('west', 'الغرب')):
        raw_item = data.get(key)
        item = raw_item if isinstance(raw_item, dict) else {}
        length = str(item.get('length') or '').strip() or 'غير موثق'
        neighbour = str(item.get('street_name') or item.get('description') or '').strip() or 'غير موثق'
        width = str(item.get('street_width') or '').strip() or 'غير موثق'
        facade = 'واجهة على شارع' if item.get('is_facade') else 'جار'
        lines.append(f'- {label}: طول الحد {length}، البيان الموثق {neighbour}، عرض الشارع {width}، التصنيف {facade}')
    facades_summary = str(data.get('facades_summary') or '').strip() or 'غير موثق'
    key_view = str(data.get('key_view') or '').strip() or 'غير موثق'
    return (
        "\n\n## بيانات الحدود الموثقة لهذه الشريحة (المصدر الوحيد — ممنوع الاختراع)\n"
        + "\n".join(lines)
        + f"\n- ملخص الواجهات الموثق: {facades_summary}"
        + f"\n- الجهة المميزة الموثقة: {key_view}"
        + "\nقواعد ملزمة عند تعديل شريحة مخطط الحدود:"
        + "\n- المواضع الجغرافية ثابتة: الشمال أعلى، الجنوب أسفل، الشرق والغرب على الجانبين."
        + " لا تبدل الاتجاهات ولا تنقل بطاقة من موضعها."
        + "\n- حافظ على وسم data-boundary-direction لكل اتجاه كما هو."
        + "\n- اعرض طول كل حد ووصف الشارع أو الجار وعرض الشارع من البيانات أعلاه فقط."
        + " أي بيان مكتوب «غير موثق» اترك خانته كما هي ولا تخترع له نصاً."
        + "\n- إن طلب المستخدم إضافة بيان غير موجود في القائمة أعلاه، نفذ ما يمكن تنفيذه"
        + " من تنسيق، واذكر في الرد بوضوح أن البيان المطلوب غير موثق في بيانات المشروع"
        + " بدل ادعاء إضافته."
    )


def _designer_project_context(project_data, creative_images=None, tenant_id=None):
    """Give the planner and every slide edit the complete project source of truth."""
    source = project_data if isinstance(project_data, dict) else {}
    parts = [
        "## ملف بيانات المشروع الكامل — مصدر الحقيقة الملزم",
        "هذه أحدث بيانات متاحة لملف المشروع. استخدم كل حقل مطلوب كما هو، ولا تقل إن المعلومة غير موجودة قبل البحث في هذا الملف كاملًا. إذا ورد رابط Google Maps فهو رابط المشروع الفعلي ويمكن إدراجه نصيًا عند طلب المستخدم.",
        slide_engine.build_project_facts(source, tenant_id),
    ]
    for note in (
        _designer_boundary_facts_note(source),
        slide_engine._timeline_data_note(source),
        slide_engine._financial_data_note(source),
    ):
        if str(note or '').strip():
            parts.append(str(note).strip())
    asset_note = _get_images_info(creative_images or {}, source)
    if str(asset_note or '').strip():
        parts.append("## الأصول والخرائط والصور المتاحة فعليًا\n" + asset_note.strip())
    return '\n\n'.join(parts)


def _designer_project_data_for_request(request_project_data, presentation, tenant_id):
    """Merge the presentation snapshot with its latest saved draft and current request.

    The linked draft is loaded by id so opening an older presentation never sends Sol stale
    project facts, while an unrelated newer project owned by the same user is never mixed in.
    Current browser values win because they may contain edits made after the last explicit save.
    """
    cleaned_request = clean_project_data(request_project_data) if isinstance(request_project_data, dict) else {}
    request_data = cleaned_request if isinstance(cleaned_request, dict) else {}
    presentation_data = {}
    if isinstance(presentation, dict):
        raw = presentation.get('project_data')
        if isinstance(raw, dict):
            cleaned_presentation = clean_project_data(raw)
            presentation_data = cleaned_presentation if isinstance(cleaned_presentation, dict) else {}
        elif isinstance(raw, str) and raw.strip():
            try:
                decoded = json.loads(raw)
                cleaned_presentation = clean_project_data(decoded) if isinstance(decoded, dict) else {}
                presentation_data = cleaned_presentation if isinstance(cleaned_presentation, dict) else {}
            except (TypeError, ValueError):
                presentation_data = {}
    presentation_draft_id = presentation.get('draft_id') if isinstance(presentation, dict) else None
    draft_id = (
        presentation_draft_id
        or presentation_data.get('draftId') or presentation_data.get('draft_id')
        or request_data.get('draftId') or request_data.get('draft_id')
    )
    draft_data = {}
    if tenant_id and draft_id:
        try:
            draft = db.get_project_draft_by_id(tenant_id, str(draft_id))
            if isinstance(draft, dict) and isinstance(draft.get('draft_data'), dict):
                cleaned_draft = clean_project_data(draft['draft_data'])
                draft_data = cleaned_draft if isinstance(cleaned_draft, dict) else {}
        except Exception as exc:
            print(f'[DESIGNER-CHAT] Could not load linked draft {draft_id}: {exc}')
    merged = {**presentation_data, **draft_data, **request_data}
    if draft_id:
        merged['draftId'] = str(draft_id)
    cleaned_merged = clean_project_data(merged)
    return cleaned_merged if isinstance(cleaned_merged, dict) else {}


def _designer_requests_boundary_data(instruction):
    text = str(instruction or '').casefold()
    return any(word in text for word in (
        'حدود', 'شارع', 'شوارع', 'جار', 'جيران', 'اتجاه',
        'طول', 'واجهة',
    ))


def _designer_requests_google_maps_link(instruction):
    text = str(instruction or '').casefold()
    return 'رابط' in text and any(word in text for word in ('جوجل', 'google', 'خرائط', 'ماب'))


def _designer_project_maps_link(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    for key in ('location_address', 'location_maps_link', 'maps_link'):
        value = str(source.get(key) or '').strip()
        if re.match(r'^https?://', value, flags=re.IGNORECASE):
            return value
    return ''


def _inject_designer_project_maps_link(html, link):
    """Insert the exact stored map link when the user explicitly asks for it."""
    if not html or not link:
        return html, False
    safe_link = html_lib.escape(str(link), quote=True)
    markup = (
        '<a data-project-map-link="1" href="' + safe_link + '" target="_blank" rel="noopener" '
        'style="position:absolute;left:220px;right:220px;bottom:38px;z-index:8;'
        'font-size:11px;line-height:1.4;font-weight:700;text-align:center;color:#0c5670;'
        'text-decoration:underline;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">'
        'رابط موقع المشروع على Google Maps</a>'
    )
    existing = re.search(
        r'<a\b[^>]*\bdata-project-map-link=["\'][^"\']+["\'][^>]*>[\s\S]*?</a>',
        str(html), flags=re.IGNORECASE,
    )
    if existing:
        updated = str(html)[:existing.start()] + markup + str(html)[existing.end():]
        return updated, updated != html
    closing = re.search(r'</div>\s*$', str(html), flags=re.IGNORECASE)
    if not closing:
        return html, False
    return str(html)[:closing.start()] + markup + str(html)[closing.start():], True


def _designer_edit_failure_detail(reasons):
    unique = list(dict.fromkeys(str(reason or '') for reason in reasons if reason))
    if 'dropped_boundary_data' in unique:
        return 'نتيجة المصمم أسقطت أطوال حدود موثقة، فتم رفضها لحماية بيانات المشروع.'
    if unique and set(unique) == {'no_material_change'}:
        return 'أعاد المصمم الشريحة نفسها دون تغيير قابل للتحقق.'
    if 'invalid_html' in unique:
        return 'لم يُرجع المصمم شريحة HTML صالحة يمكن تطبيقها.'
    if 'provider_error' in unique:
        return 'تعذر الحصول على نتيجة صالحة من مزود التصميم بعد المحاولات المتاحة.'
    if 'maps_link_missing' in unique:
        return 'لا يوجد رابط Google Maps محفوظ في بيانات هذا المشروع.'
    if 'boundary_data_unchanged' in unique:
        return 'أحدث بيانات الحدود مطابقة لما هو ظاهر بالفعل في الشريحة.'
    return 'لم تنتج المحاولات تغييرًا فعليًا صالحًا للتطبيق.'


def _designer_edit_slide(html, title, instruction, slide_index, project_data, presentation_id, branding, tenant_id=None, creative_images=None, user_image_refs=None, slide_type='content', total_slides=None, content_source=None, skip_vision=False, progress_callback=None):
    """Ask GLM/Sol for one complete slide and retry malformed responses with Playwright Vision guidance."""
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
    team_logo_note = (
        "\n\n## شعارات فريق العمل في هذا المشروع\n"
        + _designer_team_logo_context(creative_images)
        + "\nلا تضع شعار جهة فريق العمل في هيدر الشركة، ولا تستبدله بـ ##LOGO## أو ##PROJECT_LOGO##. "
          "عند طلب شعار جهة محددة، أدرج الرمز المطابق داخل موضع محتوى مناسب في الشريحة. "
          "ممنوع إدراج أي شعار (شركة أو مشروع أو فريق عمل) إلا إذا طلب المستخدم ذلك صراحة بكلمة "
          "شعار أو لوجو أو علامة تجارية في رسالته الحالية. طلب وصف أو شرح أو تعليق على صور موجودة "
          "يعني إضافة نص وصفي فقط دون أي شعار ودون توليد صورة جديدة، وطلب صورة أو تصميم أو توليد "
          "يعني صورة معمارية جديدة وليس شعاراً."
    )

    # Capture Playwright vision screenshot of the current slide if available (skip in large bulk edits for speed)
    vision_image_uri = None
    vision_error = ''
    if not skip_vision:
        try:
            import generate_pdf_from_preview as renderer
            vision_image_uri = renderer.render_slide_to_image_base64(html, branding=branding, tenant_id=tenant_id)
            if not vision_image_uri:
                vision_error = getattr(renderer, 'LAST_VISION_ERROR', '') or 'no_snapshot'
        except Exception as ve:
            vision_error = str(ve)
            print(f"[DESIGNER-EDIT VISION] Screenshot failed: {ve}")
    else:
        vision_error = 'skipped_batch'
    _record_slide_vision_state(bool(vision_image_uri), vision_error)
    if vision_error:
        # Without the snapshot the model edits the markup blind, and it still claims success. The
        # user was left believing a layout was inspected and fixed when it was never seen.
        print(f"[DESIGNER-EDIT VISION] Editing slide {slide_index + 1} without a visual snapshot ({vision_error})")

    image_refs = None
    vision_note = ""
    if vision_image_uri:
        image_refs = [{"data_uri": vision_image_uri}]
        vision_note = (
            "\n\n## الرؤية البصرية للشريحة الحالية (Visual Vision Snapshot):\n"
            "لقد تم تزويدك بلقطة شاشة مرئية فعلية للشريحة الحالية بدقة 1280x720 كما تظهر للمستخدم تماماً.\n"
            "- انظر بدقة إلى اللقطة المرفقة لتفهم:\n"
            "  1. التوزيع البصري، الهوامش، والمسافات البينية (spacing / padding / margins).\n"
            "  2. أحجام الخطوط والتسلسل الهرمي للنصوص وعناوين البطاقات.\n"
            "  3. تموضع وحجم الصور والبطاقات والشعارات.\n"
            "  4. درجات الألوان وتناسق الخلفية مع النصوص والبطاقات.\n"
            "- نفّذ التعديل المطلوب بدقة جراحية مع الحفاظ على التناسق البصري والجمالي والتوازن وبدون تداخل نصوص."
        )

    if user_image_refs:
        # The user's own attachment comes after the snapshot, so the order matches the note below.
        image_refs = (image_refs or []) + list(user_image_refs)
        vision_note += (
            "\n\n## صورة أرفقها المستخدم مع طلبه\n"
            "الصورة الأخيرة المرفقة هي صورة المستخدم، لا لقطة الشريحة. استخدمها كما يوضح طلبه"
            " (مرجع تصميم أو محتوى مطلوب أو خلل يشير إليه)، ولا تنسخ نصوصها إلى الشريحة إلا إن طلب ذلك."
        )

    # Store base64 data URIs to avoid inflating prompt with hundreds of thousands of tokens
    base64_map = {}
    def _preserve_base64(match):
        idx = len(base64_map)
        ph = f"##PRESERVED_BASE64_{idx}##"
        base64_map[ph] = match.group(0)
        return ph

    clean_html = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', _preserve_base64, html or '')
    if len(clean_html) > 150000:
        clean_html = clean_html[:150000]

    surface_note = '' if slide_type in ('cover', 'closing', 'section_divider', 'moodboard') else (
        "\n\n## عقد سطح شريحة المحتوى\n"
        "هذه شريحة محتوى عادية ويجب أن تبقى على canvas أبيض أو فاتح موحد، لا على إطار داكن حول صفحة بيضاء. "
        "استخدم اللون الأساسي في العناوين ورؤوس الجداول والمساحات المحدودة فقط، واترك الخلفية الداكنة الكاملة للغلاف والخاتمة وفواصل الأقسام ذات الصورة. "
        "خلفية شعار الشركة وشعار المشروع مستقلة لكل شعار حسب لونه وتباينه؛ لا تغيّرها عند تغيير خلفية الشريحة."
    )

    is_boundary_slide = _is_land_boundary_diagram_slide(
        title=title, content_source=content_source, html=html)
    boundary_data_request = is_boundary_slide and _designer_requests_boundary_data(instruction)
    requested_maps_link = is_boundary_slide and _designer_requests_google_maps_link(instruction)
    project_maps_link = _designer_project_maps_link(project_data) if requested_maps_link else ''
    canonical_boundary_html = ''
    if boundary_data_request and slide_engine._has_land_boundary_data(project_data):
        try:
            canonical_boundary_html = slide_engine._build_land_boundary_diagram_slide(
                {
                    'title': title,
                    'type': slide_type or 'content',
                    'content_source': content_source or 'land_boundary_diagram',
                },
                project_data,
                branding,
                slide_num=slide_index + 1,
                total_slides=total_slides or (slide_index + 1),
            )
            canonical_boundary_html = resolve_designer_chat_placeholders(
                canonical_boundary_html, project_data, presentation_id, tenant_id, creative_images)
            canonical_boundary_html = slide_engine.finalize_slide_html(
                canonical_boundary_html, slide_type or 'content', project_data, branding,
                creative_images=creative_images, tenant_id=tenant_id,
                slide_num=slide_index + 1, slide_title=title,
                total_slides=total_slides or (slide_index + 1), content_source=content_source,
                allow_all_maps=True,
            )
            canonical_boundary_html = _sanitize_designer_output(canonical_boundary_html)
            if not _is_watermark_removal_instruction(instruction):
                canonical_boundary_html = _carry_slide_watermark(html, canonical_boundary_html)
        except Exception:
            canonical_boundary_html = ''
            app.logger.exception(
                '[DESIGNER-EDIT] deterministic boundary build failed for slide %s', slide_index + 1)
    project_context = _designer_project_context(project_data, creative_images, tenant_id)

    prompt = f"""{rules}{training_note}{team_logo_note}{vision_note}{surface_note}

{project_context}
أنت Sol، كبير المصممين ومهندس العرض وجرّاح كود وتصميم (Surgical Code & Design Master). عدّل الشريحة بدقة جراحية متناهية حسب الطلب:
1. قواعد الإزاحات والتخطيط الجراحي (Spatial & Layout Precision):
   - تحكّم دقيق بكسلي ونسبية في CSS: رفع أو تنزيل الهيدر، ضبط هوامش البطاقات الداخلية (padding) والخارجية (margins)، وتغيير حجم البطاقات والمسافات البينية (gap).
   - تحويل التخطيط بسلاسة بين عمودين أو ثلاثة أعمدة أو شبكة غير متماثلة (Asymmetric Grid) مع الحفاظ التام على انسيابية العناصر.
   - ضبط المحاذاة العمودية والأفقية والتوزيع المتوازن (align-items / justify-content).
2. النظم الجمالية والهوية المعتمدة (Design System & Tokens):
   - الخط الرسمي المعتمد هو The Sans Arabic حصراً لجميع العناصر (العناوين 700 والنصوص 400).
   - لوحة الألوان المعتمدة: الكحلي الملكي (#0c2340), الذهبي الاستثماري (#c5a059), الرمادي الداكن (#1a202c), والأبيض النقي (#ffffff).
   - تحقيق تباين لوني عالي (Contrast Ratio >= 4.5:1) لضمان سهولة القراءة الفائقة.
3. التعديل الجراحي الموضعي (Surgical Modifications):
   - إضافة أو حذف أو تعديل بطاقة أو نص أو مكون محدد دون مساس بباقي محتويات الشريحة، ودون إعادة بناء من الصفر، ودون تدمير التنسيق.
4. إدراج الخرائط والمكونات المعمارية:
   - يمكنك إدراج أو استبدال أي خريطة من الخرائط الأربع المعتمدة (##MAP_OVERVIEW##, ##MAP_ACCESS##, ##MAP_CATCHMENT##, ##MAP_LANDMARKS##) أو صور المكونات مع ضبط موضعها وأبعادها بدقة.
5. الصياغة العقارية والاستثمارية الرفيعة (Saudi Real Estate Phrasing):
   - نبرة رسمية استثمارية رفيعة المستوى تخاطب المستثمرين واللجان التمويلية.
   - استخدام المصطلحات العقارية السعودية الدقيقة (معامل البناء، الارتدادات، الصك الإلكتروني، كود البناء السعودي).
6. الامتثال الصارم (Strict Compliance):
   - ممنوع منعاً باتاً وضع أي أيقونات أو إيموجي أو رموز تعبيرية (No icons, no emojis).
   - ممنوع وضع أي رموز أسهم (استخدم كلمات: أعلى، أسفل، يمين، يسار).
   - خلو الشريحة تماماً من أي نص تعليمي (No How-To text).
   - الحفاظ على مقاس الشريحة القياسي 1280x720 و overflow:hidden دون أشرطة تمرير.
   - سطح الشريحة: شرائح المحتوى العادية فاتحة وموحدة، ولا تُبنى كواجهة داكنة أو كإطار داكن حول صفحة بيضاء. حافظ على خلفية كل شعار مستقلة حسب لونه.
7. حرية إبداعية وتصميمية مطلقة لجميع أنواع الشرائح (Full Creative Freedom):
   - تمتلك كامل الصلاحية والحرية المطلقة لتعديل أو إعادة ابتكار وتصميم أي شريحة يطلبها المستخدم بلا أي استثناء أو قيود نوعية:
     * شرائح الفصول والأقسام الرئيسية (Section Dividers / الفصول): لك مطلق الحرية في إعادة تصميمها بتخطيطات إبداعية كاملة (مثل: إضافة كروت ملخصة لمحاور القسم، خطوط زمنية، إبراز مؤشرات أو أرقام قياسية، تقسيم الشريحة أفقياً أو عمودياً Split View، دمج صورة معمارية مع بطاقة داكنة ملكية، تدرجات لونية، خطوط عريضة، إلخ).
     * شريحة الفهرس (Index Slide): لك الحرية في تصميمها بشبكات عصرية أو بطاقات مرقمة فاخرة، مع الحفاظ على وسم data-index-page="section_key" لكل قسم لربط أرقام الصفحات.
     * شرائح الغلاف والخاتمة (Cover & Closing): كامل الحرية في إعادة توزيع العناصر وتنسيق المقدمة والخاتمة.
     * شرائح المحتوى، الخرائط، والتحليلات.
   - لا ترفض ولا تعتذر عن تعديل أي شريحة مهما كان نوعها، ونفّذ أي فكرة تصميمية يطلبها المستخدم بحرية مطلقة وإتقان واحترافية.
أعد JSON فقط بالشكل:
{{"html":"<div class=\\"slide\\">...</div>","response":"شرح عربي موجز ودقيق لما قمت به جراحياً"}}
عنوان الشريحة: {title}
HTML الحالي:
{clean_html}
الطلب:
{instruction}"""

    failure_reasons = []
    for attempt in range(1, 4):
        if callable(progress_callback):
            try:
                progress_callback(attempt, 3)
            except Exception as progress_error:
                app.logger.warning('[DESIGNER-EDIT] progress callback failed: %s', progress_error)
        try:
            raw = extract_chat_content(call_zai_chat(prompt, instruction, max_tokens=16000, model=SLIDE_TEXT_MODEL, image_references=image_refs, timeout=300, usage_ctx=_usage_ctx('designer_chat', project_data, presentation_id=presentation_id)), 'DESIGNER-EDIT')
            parsed = _designer_json_response(raw)
            output = parsed.get('html') or parsed.get('content') or parsed.get('slide_html')
            if not output and raw and '<div' in raw and 'slide' in raw:
                div_m = re.search(r'<div\b[^>]*class=["\']slide["\'][\s\S]*?</div>', raw, flags=re.IGNORECASE)
                if div_m:
                    output = div_m.group(0)
            if output and ('slide' in output and '<div' in output):
                if 'class="slide"' not in output and "class='slide'" not in output:
                    output = f'<div class="slide" style="width:1280px;height:720px;position:relative;box-sizing:border-box;overflow:hidden;">{output}</div>'
                
                # Restore any preserved base64 images
                for ph, b64_str in base64_map.items():
                    output = output.replace(ph, b64_str)
                model_changed = designer_chat_reliability.materially_changed(
                    html, output, parsed.get('response'))
                if (not model_changed and not canonical_boundary_html
                        and not (requested_maps_link and project_maps_link)):
                    failure_reasons.append('no_material_change')
                    print(f'[DESIGNER-EDIT] model returned no change on attempt {attempt}')
                    continue

                output = resolve_designer_chat_placeholders(output, project_data, presentation_id,
                                                           tenant_id, creative_images)
                output = slide_engine.finalize_slide_html(
                    output, slide_type or 'content', project_data, branding,
                    creative_images=creative_images, tenant_id=tenant_id,
                    slide_num=slide_index + 1, slide_title=title,
                    total_slides=total_slides or (slide_index + 1), content_source=content_source,
                    allow_all_maps=True,
                )
                output = _sanitize_designer_output(output)
                # The model rebuilds the slide and drops the watermark overlay div.
                # Carry it over so any later AI edit cannot silently delete it.
                if not _is_watermark_removal_instruction(instruction):
                    output = _carry_slide_watermark(html, output)
                # Content requests on this system-owned slide always use the canonical builder.
                # Sol may choose the operation, but it cannot relocate directions, omit documented
                # neighbours or substitute stale data in the resulting boundary diagram.
                if canonical_boundary_html:
                    output = canonical_boundary_html
                if is_boundary_slide:
                    # The boundary diagram is rebuilt from documented facts: a model
                    # reply that drops a documented length corrupts the slide, and a
                    # data-add request with no visible text change is a false success.
                    # Retry instead of returning either.
                    try:
                        boundary_data = slide_engine._extract_land_boundary_diagram_data(
                            project_data if isinstance(project_data, dict) else {}
                        )
                    except Exception:
                        boundary_data = {}
                    if isinstance(boundary_data, dict):
                        dropped = []
                        for _dir_key in ('north', 'south', 'east', 'west'):
                            _raw_item = boundary_data.get(_dir_key)
                            _item = _raw_item if isinstance(_raw_item, dict) else {}
                            _length = str(_item.get('length') or '').strip()
                            _number = re.search(r'\d+(?:\.\d+)?', _length)
                            if _number and _number.group(0) not in str(output or ''):
                                dropped.append(_dir_key)
                        if dropped:
                            failure_reasons.append('dropped_boundary_data')
                            print(f'[DESIGNER-EDIT] boundary slide dropped lengths {dropped} on attempt {attempt}')
                            continue
                    if boundary_data_request:
                        _strip_tags = lambda value: re.sub(
                            r'\s+', ' ', re.sub(r'<[^>]+>', ' ', str(value or ''))).strip()
                        if _strip_tags(output) == _strip_tags(html) and not requested_maps_link:
                            failure_reasons.append('boundary_data_unchanged')
                            print(f'[DESIGNER-EDIT] boundary data already current on attempt {attempt}')
                            return output, (
                                f'تم الحفاظ على تصميم الشريحة {slide_index + 1}. '
                                'أحدث بيانات الحدود مطابقة لما هو ظاهر بالفعل في الشريحة.'
                            )
                inserted_requested_maps_link = False
                if requested_maps_link:
                    if not project_maps_link:
                        failure_reasons.append('maps_link_missing')
                        print(f'[DESIGNER-EDIT] no stored Google Maps link for slide {slide_index + 1}')
                        continue
                    output, inserted_requested_maps_link = _inject_designer_project_maps_link(
                        output, project_maps_link)
                    if 'data-project-map-link="1"' not in output:
                        failure_reasons.append('invalid_html')
                        print(f'[DESIGNER-EDIT] could not insert Google Maps link on attempt {attempt}')
                        continue
                response_text = (
                    'تم تحديث مخطط الحدود من أحدث بيانات المشروع الموثقة.'
                    if canonical_boundary_html
                    else (parsed.get('response') or 'تم تحديث الشريحة بنجاح.')
                )
                if inserted_requested_maps_link:
                    if not model_changed and not canonical_boundary_html:
                        response_text = 'تمت إضافة رابط Google Maps المحفوظ للمشروع.'
                    else:
                        response_text += ' تمت إضافة رابط Google Maps المحفوظ للمشروع.'
                if vision_error:
                    response_text += ' التعديل جرى على الكود بدون معاينة بصرية للشريحة.'
                return output, response_text
            failure_reasons.append('invalid_html')
            print(f'[DESIGNER-EDIT] invalid HTML on attempt {attempt}')
        except Exception:
            failure_reasons.append('provider_error')
            app.logger.exception('[DESIGNER-EDIT] attempt %s failed for slide %s', attempt, slide_index + 1)

    fallback = resolve_designer_chat_placeholders(
        html, project_data, presentation_id, tenant_id, creative_images)
    fallback = slide_engine.finalize_slide_html(
        fallback, slide_type or 'content', project_data, branding,
        creative_images=creative_images, tenant_id=tenant_id,
        slide_num=slide_index + 1, slide_title=title,
        total_slides=total_slides or (slide_index + 1), content_source=content_source,
        allow_all_maps=True,
    )
    fallback = _sanitize_designer_output(fallback)

    # The boundary diagram is a deterministic system slide. If Sol cannot safely edit it, rebuild
    # it from the newest linked-draft facts instead of returning the old snapshot. This gives new
    # streets, neighbours, widths and lengths a reliable path without weakening the no-op guard.
    deterministic = canonical_boundary_html or fallback
    rebuilt_boundary = bool(canonical_boundary_html) and designer_chat_reliability.materially_changed(
        html, deterministic, 'إعادة بناء شريحة الحدود من أحدث بيانات المشروع')
    if canonical_boundary_html and not rebuilt_boundary:
        failure_reasons.append('boundary_data_unchanged')

    inserted_maps_link = False
    if requested_maps_link:
        if project_maps_link:
            deterministic, inserted_maps_link = _inject_designer_project_maps_link(
                deterministic, project_maps_link)
        else:
            failure_reasons.append('maps_link_missing')

    if (rebuilt_boundary or inserted_maps_link) and designer_chat_reliability.materially_changed(
            html, deterministic, 'تحديث حتمي من بيانات المشروع'):
        completed = []
        if rebuilt_boundary:
            completed.append('تم تحديث مخطط الحدود من أحدث بيانات المشروع الموثقة')
        if inserted_maps_link:
            completed.append('تمت إضافة رابط Google Maps المحفوظ للمشروع')
        return deterministic, '، و'.join(completed) + '.'

    detail = _designer_edit_failure_detail(failure_reasons)
    print(f'[DESIGNER-EDIT] slide {slide_index + 1} rejected after 3 attempts: {failure_reasons}')
    return fallback, f'تم الحفاظ على تصميم الشريحة {slide_index + 1} لتعذر التعديل التلقائي عليها. {detail}'


DESIGNER_CHAT_VERBATIM_TURNS = 10
DESIGNER_CHAT_MEMORY_CHARS = 6000
DESIGNER_CHAT_MEMORY_MAX = 1800
DESIGNER_CHAT_STORED_TURNS = 40


def _normalize_designer_chat_messages(messages):
    """Keep chat entries in one comparable shape before merging browser and DB history."""
    normalized = []
    for entry in messages if isinstance(messages, list) else []:
        if not isinstance(entry, dict) or not str(entry.get('content') or '').strip():
            continue
        normalized.append({
            'role': 'user' if entry.get('role') == 'user' else 'assistant',
            'content': str(entry.get('content') or '')[:2000],
            'slides': entry.get('slides') if isinstance(entry.get('slides'), list) else [],
        })
    return normalized


def _merge_designer_chat_messages(stored_messages, incoming_messages):
    """Merge a browser snapshot into saved history without replacing older turns."""
    stored = _normalize_designer_chat_messages(stored_messages)
    incoming = _normalize_designer_chat_messages(incoming_messages)
    if not stored:
        return incoming
    if not incoming:
        return stored
    if incoming == stored or len(incoming) <= len(stored):
        for start in range(len(stored) - len(incoming) + 1):
            if stored[start:start + len(incoming)] == incoming:
                return stored
    if len(stored) <= len(incoming):
        for start in range(len(incoming) - len(stored) + 1):
            if incoming[start:start + len(stored)] == stored:
                return incoming
    max_overlap = min(len(stored), len(incoming))
    for overlap in range(max_overlap, 0, -1):
        if stored[-overlap:] == incoming[:overlap]:
            return stored + incoming[overlap:]
    return stored + incoming


def _designer_chat_history_lines(history):
    """The conversation as prompt lines, with each turn's slide numbers attached."""
    lines = []
    for entry in history if isinstance(history, list) else []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get('content') or '').strip()
        if not text:
            continue
        role = 'المستخدم' if entry.get('role') == 'user' else 'المصمم'
        slides = [str(int(n)) for n in (entry.get('slides') or []) if str(n).strip().isdigit()]
        scope = f" [شرائح: {'، '.join(slides)}]" if slides else ''
        lines.append(f"{role}{scope}: {text[:1500]}")
    return lines


def _designer_chat_memory(history, memory):
    """Keep the conversation whole: recent turns verbatim, older ones compressed into one memory.

    The chat used to receive nothing but the current message, so it asked «أي شريحة؟», the user
    answered «8», and the next turn had no idea what «8» referred to. History is now carried, and
    once it grows past DESIGNER_CHAT_MEMORY_CHARS the older half is folded into a short Arabic
    summary so a long session cannot push the actual request out of the context.
    """
    memory = str(memory or '').strip()
    entries = [e for e in (history if isinstance(history, list) else []) if isinstance(e, dict)]
    recent = entries[-DESIGNER_CHAT_VERBATIM_TURNS:]
    older = entries[:-DESIGNER_CHAT_VERBATIM_TURNS] if len(entries) > DESIGNER_CHAT_VERBATIM_TURNS else []
    older_lines = _designer_chat_history_lines(older)
    if not older_lines:
        return memory, recent

    older_text = '\n'.join(older_lines)
    if len(memory) + len(older_text) <= DESIGNER_CHAT_MEMORY_CHARS:
        merged = (memory + '\n' + older_text).strip() if memory else older_text
        return merged[-DESIGNER_CHAT_MEMORY_CHARS:], recent

    try:
        summary = extract_chat_content(call_zai_chat(
            "أنت تلخّص محادثة تصميم عرض تقديمي. أعد ملخصاً عربياً موجزاً يحفظ: أي شريحة كان الحديث "
            "عنها بأرقامها، والمشاكل التي ذُكرت، والتعديلات التي نُفّذت، والقرارات وتفضيلات المستخدم، "
            "وأي سؤال لم يُجب عليه بعد. بلا مقدمات وبلا تنسيق زائد.",
            f"الذاكرة السابقة:\n{memory or 'لا توجد'}\n\nالمحادثة الأقدم:\n{older_text}",
            max_tokens=700, model=SLIDE_TEXT_MODEL, usage_ctx=_usage_ctx('designer_chat')), 'DESIGNER-MEMORY')
        summary = str(summary or '').strip()
    except Exception as error:
        print(f"[DESIGNER MEMORY] compression failed: {error}")
        summary = ''
    if not summary:
        # Compression failed: keep the tail of the raw text rather than losing the conversation.
        summary = (memory + '\n' + older_text).strip()
    return summary[-DESIGNER_CHAT_MEMORY_MAX:], recent


def _report_designer_job_progress(job_id, tenant_id, progress_val, message_text, extra_data=None):
    """Update background designer job progress file thread-safely for client polling."""
    if not job_id or not tenant_id:
        return
    try:
        current_job = _read_job('.designer_chat_jobs', tenant_id, job_id) or {}
        updated_job = {
            **current_job,
            'status': 'running',
            'success': True,
            'progress': max(1, min(99, int(progress_val))),
            'message': str(message_text or 'جاري معالجة الطلب...'),
        }
        if extra_data and isinstance(extra_data, dict):
            updated_job.update(extra_data)
        _write_job('.designer_chat_jobs', tenant_id, job_id, updated_job)
    except Exception as err:
        print(f"[JOB PROGRESS ERROR] {err}")


@app.route('/api/designer-chat', methods=['POST'])
@require_auth
def api_designer_chat():
    """Agentic designer chat operating on one slide or the complete presentation."""
    data = request.json or {}
    job_id = request.headers.get('X-Designer-Job-Id') or data.get('_job_id')
    tenant_id = g.tenant_id

    def report_designer_progress(progress_val, message_text, extra_data=None):
        _report_designer_job_progress(job_id, tenant_id, progress_val, message_text, extra_data)

    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'الطلب فارغ'}), 400
    report_designer_progress(10, 'جاري تحليل الطلب وتحديد نطاق التعديل...')
    request_project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
    request_creative_images = copy.deepcopy(data.get('creativeImages')) if isinstance(data.get('creativeImages'), dict) else {}
    presentation_id = data.get('presentationId')
    presentation = None
    slides = data.get('slidesData') if isinstance(data.get('slidesData'), list) else []
    current_index = data.get('slideIndex', 0)
    try:
        current_index = int(current_index)
    except (TypeError, ValueError):
        current_index = 0

    if presentation_id:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not presentation:
            return jsonify({'success': False, 'error': 'العرض غير موجود أو لا يتبع هذه الشركة'}), 404
        if not slides and presentation.get('slides_data'):
            try:
                slides = json.loads(presentation['slides_data'])
            except Exception:
                slides = []

    project_data = _designer_project_data_for_request(
        request_project_data, presentation, tenant_id)
    project_creative_images = copy.deepcopy(project_data.get('tenantCreativeImages')) if isinstance(project_data.get('tenantCreativeImages'), dict) else {}
    project_data, creative_images = _hydrate_map_assets_for_request(
        project_data, data.get('creativeImages', {}), g.tenant_id,
        presentation_id=presentation_id,
    )
    # Designer-chat requests must have the same selected team-logo manifest as full
    # presentation generation. Without this merge, the model can see a team name but
    # has no real image behind ##TEAM_LOGO_N## and falls back to the company logo.
    creative_images = _augment_generation_images(creative_images, project_data, g.tenant_id)

    # Backward-compatible one-slide clients still work.
    if not slides and data.get('slideHtml'):
        slides = [{'html': data.get('slideHtml'), 'title': data.get('slideTitle', ''), 'type': 'content', 'designStyle': 'cards'}]
        current_index = 0
    if not slides:
        return jsonify({'success': False, 'error': 'لا توجد شرائح مفتوحة لتنفيذ الطلب'}), 400

    # Kept so the history can state what the AI actually changed. An AI edit used to leave no trace
    # at all: no log entry, no version, and no record of the instruction behind it.
    slides_before = copy.deepcopy(slides)

    # Only a scope explicitly selected in the UI is a constraint. The model
    # interprets natural language, including negation, corrections and numbers.
    is_all_slides_request = data.get('target') == 'all' or data.get('scope') == 'all'

    # The conversation so far. Merge the browser snapshot with the presentation copy so a stale
    # client cannot replace a complete saved conversation with only its last visible messages.
    stored_chat = project_data.get('designerChat') if isinstance(project_data.get('designerChat'), dict) else {}
    incoming_history = data.get('history') if isinstance(data.get('history'), list) else []
    history_for_turn = _merge_designer_chat_messages(stored_chat.get('messages'), incoming_history)
    memory_seed = data.get('memory') if isinstance(data.get('memory'), str) and data.get('memory') else stored_chat.get('memory')
    chat_memory, recent_history = _designer_chat_memory(history_for_turn, memory_seed)
    history_lines = _designer_chat_history_lines(recent_history)
    focus_indexes = []
    for value in (data.get('focusIndexes') if isinstance(data.get('focusIndexes'), list) else []):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= len(slides) and number not in focus_indexes:
            focus_indexes.append(number)

    # Focus is conversational context, not an instruction inferred from this turn.
    # In particular, a number may answer a value question rather than name a slide.
    preferred_indexes = list(focus_indexes)

    branding = db.get_branding(g.tenant_id) or {}
    _prepare_generation_logo_context(project_data, branding, g.tenant_id)
    training_context = db.get_training_context(g.tenant_id) or ''
    summary = [{
        'index': i + 1,
        'title': s.get('title', '') if isinstance(s, dict) else '',
        'section': s.get('section_key') or s.get('sectionKey') or '',
        'type': s.get('type', 'content') if isinstance(s, dict) else 'content'
    } for i, s in enumerate(slides)]
    all_note = "\n تنبيه هام جداً: المستخدم طلب صراحة تعديل جميع الشرائح دون استثناء! يجب أن تعيد target='all' في الأداة edit_slides." if is_all_slides_request else ""
    memory_note = f"\n\n## ذاكرة المحادثة (ملخص ما سبق)\n{chat_memory}" if chat_memory else ""
    history_note = ("\n\n## آخر رسائل المحادثة بالترتيب\n" + '\n'.join(history_lines)) if history_lines else ""
    focus_note = (
        f"\n\n## نطاق الحديث السابق: {'، '.join(str(n) for n in focus_indexes)}\n"
        "هذا سياق سابق وليس أمراً جديداً. اربط الإشارات والردود القصيرة بالسؤال السابق وبالطلب "
        "غير المنفذ، واسمح للرسالة الحالية بتغيير الموضوع أو تصحيح الطلب أو إلغائه."
    ) if focus_indexes else ""
    explicit_scope_note = (
        f"\n\n## الشريحة الظاهرة في المعاينة: {current_index + 1}\n"
        "موضع المعاينة سياق فقط، وليس دليلاً أن المستخدم طلب تعديل هذه الشريحة. "
        "حدّد النية والنطاق من المحادثة والرسالة الحالية معاً."
    )
    training_note = f"\n\n## قواعد الشركة الملزمة (من التدريب — التزم بها في أي تصميم)\n{training_context}" if training_context else ""
    audit_note = _build_designer_section_and_asset_context(slides, project_data, current_index, creative_images)
    project_context = _designer_project_context(project_data, creative_images, tenant_id)
    watermark_note = (
        'العلامة المائية المستقلة معتمدة ومتاحة لأداة apply_watermark.'
        if branding.get('watermark_path') else
        'لا توجد علامة مائية مرفوعة في إعدادات الشركة؛ لا تستبدلها بشعار الشركة.'
    )
    planner_prompt = f"""{build_design_rules(branding)}{training_note}

{watermark_note}

{project_context}
أنت Sol، كبير المصممين ومهندس العرض وجرّاح كود وتصميم (Surgical Code & Design Master).
أنت تمتلك كامل الصلاحية والحرية الإبداعية والمطلقة لتعديل أو إعادة تصميم أي شريحة في العرض دون استثناء:
- حرية مطلقة لتعديل وإعادة ابتكار شرائح الفصول والأقسام الرئيسية (Section Dividers / الفصول): لك كامل الحرية في إعادة تصميمها بتخطيطات إبداعية مبهرة (إضافة كروت ملخصة لمحاور القسم، خطوط زمنية، إبراز مؤشرات أو أرقام قياسية، تقسيم الشريحة أفقياً أو عمودياً Split View، دمج صور معمارية مع بطاقات داكنة ملكية، تدرجات لونية، خطوط عريضة).
- حرية مطلقة لتعديل وتطوير شريحة الفهرس ومحتويات العرض (Index): تصميمها بشبكات عصرية أو بطاقات مرقمة فاخرة مع الحفاظ على وسم data-index-page="section_key".
- حرية تعديل شرائح الغلاف والخاتمة وجميع شرائح المحتوى والخرائط والتحليلات.
- تعديل CSS والتخطيط (رفع/تنزيل الهيدر، تغيير الأحجام، إزاحة العناصر يميناً/يساراً، تعديل الألوان والخطوط).
- تعديل جراحي فوري لمحتوى أي شريحة (إضافة بطاقات، حذف عناصر، تعديل نصوص) دون مساس ببقية الشريحة.
- إدارة دورة حياة الشرائح كاملة: حذف شريحة (delete_slide)، تكرار شريحة (duplicate_slide)، إعادة ترتيب الشرائح (reorder_slides)، تقسيم شريحة كثيفة إلى شريحتين أو أكثر (split_slide)، دمج شريحتين (merge_slides)، أو إنشاء شريحة جديدة (create_slide).
- إدراج الخرائط الأربع المعتمدة بدقة (insert_canonical_map): خريطة الموقع العام، خريطة شبكة الطرق والوصول، خريطة النطاق الجغرافي، وخريطة المعالم الحيوية.
- إدراج وتعديل المخططات والرسوم المالية المعتمدة (insert_financial_chart): شلال التدفقات، تحليل الحساسية، التدفقات المركبة، وهيكل التمويل.
- توليد صور حصرية للمكونات المعمارية والداخلية والخارجية ودمجها جراحياً داخل الشرائح مع بطاقة شرح توضيحي.
- نفّذ الطلب الواضح، واسأل سؤالاً محدداً عندما يؤثر الغموض على الإجراء أو النطاق أو القيمة. لا تخمّن تعديلاً لم يطلبه المستخدم، ولا تعتبر مجرد ذكر رقم إذناً بالتعديل.
- الرد على سؤال سابق يكمل ذلك الطلب فقط. رسالة التصحيح أو الإلغاء تلغي الاستنتاج السابق. عند اختيار edit_slides اكتب instruction مكتملة تحمل التعديل والقيمة والقيود المفهومة من المحادثة، لا تنسخ الرد القصير وحده إلى المحرر.
{all_note} أعد JSON فقط:
{{"response":"رسالة عربية تشرح ما ستفعله جراحياً", "actions":[{{"tool":"edit_slides|apply_watermark|remove_watermark|generate_image|insert_canonical_map|insert_financial_chart|delete_slide|duplicate_slide|reorder_slides|split_slide|merge_slides|create_slide|ask|chat_only", "params":{{}}}}]}}

الأدوات المتاحة:
- edit_slides: params={{"target":"current|all|indexes", "indexes":[1-based], "instruction":"التعديل الجراحي المطلوب بدقة"}}
- apply_watermark: params={{"target":"current|all|indexes", "indexes":[1-based], "only_white":true, "opacity":0.045, "width_px":480}} لإظهار العلامة المائية المستقلة المعتمدة في إعدادات الشركة في خلفية الشرائح — صيغ فعّل/أظهر/إظهار/أضف تعني هذه الأداة، و«إظهار» تعني الرؤية فقط وليست تكبيرًا. النطاق الافتراضي current عند عدم تحديد أرقام؛ أرسل all فقط عند طلب كل الشرائح صراحة (كل/جميع/العرض كله)، وأرسل indexes مع الأرقام العربية أو الإنجليزية المذكورة. أرسل only_white=true فقط إذا ذكر المستخدم الشرائح البيضاء أو الفاتحة صراحة، والافتراضي opacity=0.045 وwidth_px=480. إذا ذكر المستخدم نسبة أو قيمة شفافية صريحة (مثل 50%) فأرسلها كما هي حتى 1.0 ونفّذها فورًا دون اقتراح بديل، وإذا رفض اقتراحًا سابقًا أو كرر قيمة صريحة فلا تعِد طرح نفس السؤال بأداة ask. أرسل width_px حتى 640 إذا طلب علامة أكبر
- remove_watermark: params={{"target":"current|all|indexes", "indexes":[1-based]}} لإخفاء العلامة المائية من الشرائح — صيغ اخف/إخفاء/عطّل/إلغاء التفعيل/احذف تعني هذه الأداة مع نفس قواعد النطاق أعلاه
- apply_image_descriptions: params={{"target":"current|all|indexes", "indexes":[1-based]}} لإضافة أوصاف الصور المحفوظة بالفعل دون توليد صور أو اختراع وصف
- insert_team_logo: params={{"target":"current|all|indexes", "indexes":[1-based], "team_index":1-based}} لإضافة شعار جهة فريق العمل المرفوع فعلياً
- insert_company_logo_panel: params={{"target":"current|all|indexes", "indexes":[1-based]}} لوضع شعار الشركة داخل المربع الكحلي فوق رقم سنوات الخبرة
- generate_image: params={{"prompt":"وصف دقيق للصورة المراد توليدها", "component_name":"اسم المكون إن وجد", "slideIndex":1, "position":"surgical|background|right|left|inline"}}
- insert_canonical_map: params={{"map_type":"overview|access|catchment|landmarks", "target":"current|indexes", "slideIndex":1, "refresh":true عند طلب تحديث خريطة موجودة}}
- insert_financial_chart: params={{"chart_type":"waterfall|sensitivity|compound_flows|financing_structure", "target":"current|indexes", "slideIndex":1}}
- delete_slide: params={{"slide_number":1-based, "slide_numbers":[1-based]}}
- duplicate_slide: params={{"slide_number":1-based}}
- reorder_slides: params={{"from_index":1-based, "to_index":1-based}}
- split_slide: params={{"slide_number":1-based, "parts":2, "instruction":"تفاصيل التقسيم والتنظيم"}}
- merge_slides: params={{"slide_numbers":[1-based, 1-based], "instruction":"تفاصيل الدمج"}}
- create_slide: params={{"title":"العنوان", "type":"content|cover|divider|table|kpi", "instruction":"محتوى الشريحة وتصميمها", "position":1-based}}
- regenerate_maps: params={{"maptype":"roadmap|satellite|hybrid|terrain"}}
- ask: params={{"question":"سؤال عربي واحد قصير يحسم الغموض"}} — ينهي الدور دون تنفيذ أي تعديل.
- chat_only: params={{}} للرد أو الشرح أو تأكيد الإلغاء دون تعديل العرض.

قواعد إضافة واستخدام الخرائط:
1. ##MAP_ACCESS## : لخريطة شبكة الطرق والمحاور والوصول.
2. ##MAP_OVERVIEW## : لخريطة النظرة العامة والموقع العام.
3. ##MAP_LANDMARKS## : لخريطة المعالم والخدمات والمواقع الحيوية القريبة.
4. ##MAP_CATCHMENT## : لخريطة النطاق الجغرافي واستيعاب المنطقة.

قواعد الفهم الذكي:
1. إذا كان الطلب يتضمن تعديل كل الشرائح -> اختر target="all".
2. حدّد معنى الأرقام من السياق: قد تكون قيمة أو حجم خط أو نسبة أو عدد عناصر أو رقم شريحة. لا تختَر indexes إلا عندما يشير الكلام أو جواب السؤال السابق إلى شرائح بالفعل. ذكر شريحة وحده ليس طلب تعديل؛ إذا غاب الإجراء المطلوب اسأل عنه. أرقام indexes تبدأ من 1.
3. إذا طلب حذف شريحة (مثل: "احذف الشريحة 5") -> اختر tool="delete_slide" مع slide_number.
4. إذا طلب تكرار شريحة (مثل: "كرر الشريحة 2") -> اختر tool="duplicate_slide" مع slide_number.
5. إذا طلب تغيير ترتيب (مثل: "انقل الشريحة 8 إلى 4") -> اختر tool="reorder_slides" مع from_index و to_index.
6. إذا طلب تقسيم أو تجزئة شريحة أو محتوى شريحة معينة (مثل: "اقسم محتوى الملخص التنفيذي" أو "جزئ الشريحة 4") -> اختر tool="split_slide" مع slide_number للشريحة المستهدفة.
7. إذا طلب دمج شريحتين (مثل: "ادمج الشريحة 3 مع 4") -> اختر tool="merge_slides" مع slide_numbers.
8. إذا طلب إنشاء أو إضافة شريحة جديدة -> اختر tool="create_slide" مع العنوان والمحتوى والموضع.
9. إذا طلب خريطة الموقع أو الوصول أو المعالم -> اختر tool="insert_canonical_map".
   وإذا طلب تحديث أو إعادة تحميل أو استبدال خريطة موجودة في شريحة، أرسل refresh=true حتى تُستخدم أحدث نسخة محفوظة للخريطة نفسها.
10. إذا طلب رسم أو مخطط مالي (شلال/حساسية/عوائد) -> اختر tool="insert_financial_chart".
11. إذا طلب تغيير نوع الخريطة (شوارع/مرور/قمر صناعي/roadmap/satellite) -> اختر tool="regenerate_maps".
12. إذا كان الطلب سؤالاً لا يتطلب تعديلاً -> اختر tool="chat_only".
13. إذا طلب المستخدم شعار جهة محددة من فريق العمل، ميّزها عن شعار الشركة واستخدم tool="insert_team_logo" مع team_index الصحيح. لا تستخدم هذه الأداة إلا إذا احتوت الرسالة الحالية نفسها على كلمة شعار أو لوجو أو علامة تجارية مع اسم الجهة؛ فطلب الصورة أو الوصف ليس طلب شعار.
14. إذا طلب المستخدم نقل أو وضع شعار الشركة داخل المربع الكحلي في يمين الشريحة، استخدم tool="insert_company_logo_panel" ولا تستخدم شعار فريق العمل.
15. في سائر طلبات التعديل والتنسيق والتصميم -> اختر tool="edit_slides".
16. فرّق بدقة بين الصورة والوصف والشعار: طلب وصف أو شرح أو تعليق أو كابشن لصور موجودة (مثل: «أضف وصفاً لصور التصور البصري») يعني تعديلاً نصياً فقط عبر tool="edit_slides" مع تعليمات إضافة نص وصفي تحت الصور الموجودة، دون توليد صورة جديدة ودون أي رمز شعار (ممنوع ##TEAM_LOGO_N## و##LOGO## و##PROJECT_LOGO##). وطلب صورة أو تصميم أو توليد صور جديدة يعني tool="generate_image" لصورة معمارية جديدة وليس شعاراً. ولا تستخدم أي رمز شعار إلا عند طلب شعار صريح في الرسالة الحالية.
17. إذا طلب المستخدم إعادة توليد أو تصميم قسم كامل أو توزيع محتوى شريحة على عدة شرائح (مثل: «أعد توليد قسم الملخص التنفيذي على أكثر من شريحة مصممة جيداً وقوية بصرياً»):
- أنت Agent كامل الصلاحية: اختر الشريحة أو الشرائح المناسبة من قائمة الشرائح، ونفذ التقسيم والتوزيع الفاخر عبر tool="split_slide" مع تحديد slide_number و parts وتضمين تعليمات التصميم الجمالي والتوزيع المتناسق في instruction، أو ادمج بين edit_slides و create_slide.
- احرص دائماً على الحفاظ التام على كامل الأرقام والبيانات والمؤشرات دون حذف أي تفصيل، وتوزيعها في كروت فاخرة وأقسام متوازنة مريحة بصرياً وخالية من أي إيموجي أو أيقونات.

{audit_note}

قائمة الشرائح الحالية في العرض ({len(slides)} شريحة):
{json.dumps(summary, ensure_ascii=False)}
{memory_note}{history_note}{focus_note}{explicit_scope_note}"""
    # An image the user attached in the chat: a design reference, something to insert, or the
    # problem they are pointing at. The attach button used to open the training page's file input,
    # so it never reached this endpoint at all.
    attached_image = str(data.get('attachedImage') or '').strip()
    user_image_refs = [{'data_uri': attached_image}] if attached_image.startswith('data:image/') else None
    if user_image_refs:
        planner_prompt += ("\n\nأرفق المستخدم صورة مع رسالته. انظر إليها قبل التخطيط، وإن لم يكن دورها"
                          " واضحًا فاسأل عنه بأداة ask.")
    try:
        planner_raw = extract_chat_content(
            call_zai_chat(planner_prompt, message, max_tokens=8000, model=SLIDE_TEXT_MODEL, image_references=user_image_refs, timeout=300, usage_ctx=_usage_ctx('designer_chat', data, presentation_id=presentation_id)),
            'DESIGNER-PLANNER')
        plan = _designer_json_response(planner_raw)
        actions = plan.get('actions', []) if isinstance(plan.get('actions'), list) else []

        # A question is an answer on its own: nothing is edited until the user replies.
        question = ''
        for action in actions if isinstance(actions, list) else []:
            if isinstance(action, dict) and action.get('tool') == 'ask':
                params = action.get('params') if isinstance(action.get('params'), dict) else {}
                question = str(params.get('question') or '').strip()
                if question:
                    break
        if question:
            ask_messages = list(history_for_turn)
            if not ask_messages or ask_messages[-1].get('content') != message or ask_messages[-1].get('role') != 'user':
                ask_messages.append({'role': 'user', 'content': message[:2000], 'slides': preferred_indexes[:]})
            ask_messages.append({'role': 'assistant', 'content': question[:2000], 'slides': preferred_indexes[:]})
            ask_chat = {
                'presentationId': presentation_id or None,
                'messages': ask_messages[-DESIGNER_CHAT_STORED_TURNS * 2:],
                'memory': chat_memory,
                'focusIndexes': preferred_indexes[:],
            }
            ask_project_data = dict(project_data)
            ask_project_data['designerChat'] = ask_chat
            return jsonify({'success': True, 'data': {
                'action': 'ask',
                'response': question,
                'slidesData': slides,
                'creativeImages': data.get('creativeImages') if isinstance(data.get('creativeImages'), dict) else {},
                'actions': [{'tool': 'ask', 'status': 'success'}],
                'memory': chat_memory,
                'focusIndexes': focus_indexes,
                'chatHistory': ask_chat['messages'],
                'saved': False,
            }})

        if not actions or any(not isinstance(action, dict) for action in actions):
            return jsonify({'success': False, 'error': 'لم تصل خطة تنفيذ صالحة؛ لم يتغير العرض.',
                            'error_code': 'DESIGNER_INVALID_PLAN'}), 502

        if all(action.get('tool') == 'chat_only' for action in actions):
            response_text = str(plan.get('response') or '').strip()
            chat_messages = list(history_for_turn)
            chat_messages.append({'role': 'user', 'content': message[:2000], 'slides': []})
            chat_messages.append({'role': 'assistant', 'content': response_text[:2000], 'slides': []})
            return jsonify({'success': True, 'data': {
                'action': 'chat_only', 'response': response_text, 'actions': [],
                'memory': chat_memory, 'focusIndexes': focus_indexes,
                'chatHistory': chat_messages[-DESIGNER_CHAT_STORED_TURNS * 2:], 'saved': False,
            }})

        executed = []
        assistant_messages = []
        tenant_id = g.tenant_id
        for action_number, action in enumerate(actions):
            tool = action.get('tool') if isinstance(action, dict) else ''
            params = action.get('params') if isinstance(action.get('params'), dict) else {}
            if tool in ('ask', 'chat_only', 'validate_design_workspace', 'save_design_workspace'):
                continue
            if tool == 'apply_image_descriptions':
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                descriptions = designer_chat_reliability.collect_image_descriptions(project_data, creative_images)
                changed = []
                for idx in indexes:
                    report_designer_progress(35, f'جاري تعديل الشريحة {idx + 1}...',
                                            {'phase': 'editing', 'activeSlideIndex': idx, 'actionNumber': action_number})
                    updated, count, _ = designer_chat_reliability.add_missing_image_descriptions(slides[idx].get('html', ''), descriptions)
                    if count:
                        slides[idx].update(html=updated, _designer_keep_html=True, is_custom=True)
                        changed.append(idx)
                executed.append({'tool': tool, 'status': 'success' if changed else 'noop', 'indexes': changed})
                assistant_messages.append(f'أضيفت الأوصاف المحفوظة إلى {len(changed)} شريحة.' if changed else 'لا توجد أوصاف محفوظة ناقصة ومطابقة للصور المستهدفة.')
            elif tool in ('apply_watermark', 'remove_watermark'):
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                # Default off: without an explicit white-only request every targeted
                # slide gets the watermark, otherwise dark slides were silently skipped.
                only_white = params.get('only_white', False)
                is_remove = (tool == 'remove_watermark')
                watermark_url = str(branding.get('watermark_path') or '').strip()
                if not is_remove and not watermark_url:
                    assistant_messages.append('لا توجد علامة مائية مرفوعة في إعدادات الشركة؛ لم تتغير أي شريحة.')
                    executed.append({
                        'tool': tool, 'status': 'failed', 'indexes': [],
                        'reason': 'watermark_missing',
                    })
                    continue
                affected_indexes = []
                skipped_dark_indexes = []
                total_target = max(1, len(indexes))
                report_designer_progress(20, 'جاري معالجة العلامة المائية للشرائح...')
                for i, idx in enumerate(indexes):
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    if only_white and not _is_white_or_light_slide(slide):
                        skipped_dark_indexes.append(idx)
                        continue
                    report_designer_progress(25, f'جاري تعديل الشريحة {idx + 1}...',
                                            {'phase': 'editing', 'activeSlideIndex': idx, 'actionNumber': action_number})
                    current_slide_html = slide.get('html', '')
                    if is_remove:
                        # Hiding keeps the saved position/size/opacity so a later
                        # show restores exactly what the user had.
                        new_html = _set_slide_watermark_visible(current_slide_html, False)
                    else:
                        try:
                            wm_opacity = float(params.get('opacity', 0.045))
                        except (TypeError, ValueError):
                            wm_opacity = 0.045
                        try:
                            wm_width = int(params.get('width_px', 480))
                        except (TypeError, ValueError):
                            wm_width = 480
                        new_html = _apply_slide_watermark(current_slide_html, watermark_url, opacity=wm_opacity, width_px=wm_width)
                    slide['html'] = new_html
                    slide['_designer_keep_html'] = True
                    slide['is_custom'] = True
                    slides[idx] = slide
                    affected_indexes.append(idx)
                    pct = int(20 + 75 * ((i + 1) / total_target))
                    report_designer_progress(pct, f"تمت معالجة الشريحة {i + 1} من {total_target}...")

                executed.append({
                    'tool': tool,
                    'status': 'success',
                    'indexes': affected_indexes,
                    'count': len(affected_indexes),
                    'skipped_indexes': [idx + 1 for idx in skipped_dark_indexes],
                    'skipped_count': len(skipped_dark_indexes),
                })
                action_desc = 'حذف' if is_remove else 'إضافة'
                if (not is_remove) and only_white:
                    skipped_dark = len(skipped_dark_indexes)
                    if skipped_dark > 0:
                        skipped_numbers = ', '.join(str(idx + 1) for idx in sorted(skipped_dark_indexes)[:20])
                        if skipped_dark > 20:
                            skipped_numbers += f' وغيرها ({skipped_dark} إجمالاً)'
                        assistant_messages.append(
                            f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة بيضاء "
                            f"وتخطي {skipped_dark} شريحة داكنة (أرقام: {skipped_numbers}) "
                            f"مع الحفاظ الكامل على النصوص والتصميم."
                        )
                    else:
                        assistant_messages.append(
                            f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة مع الحفاظ الكامل على النصوص والتصميم."
                        )
                else:
                    assistant_messages.append(
                        f"تم {action_desc} العلامة المائية بنجاح في خلفية {len(affected_indexes)} شريحة مع الحفاظ الكامل على النصوص والتصميم."
                    )
            elif tool in ('edit_slides', 'edit_design_slide', 'edit_design_slides'):
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                instruction = params.get('instruction') or message
                changed_indexes = []
                if indexes:
                    report_designer_progress(20, f'جاري تعديل الشريحة {indexes[0] + 1}...',
                                            {'phase': 'editing', 'activeSlideIndex': indexes[0], 'actionNumber': action_number})
                if len(indexes) > 1:
                    skip_vision = len(indexes) > 3
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
                                tenant_id=tenant_id,
                                creative_images=creative_images,
                                user_image_refs=user_image_refs,
                                slide_type=slide_item.get('type', 'content'),
                                total_slides=len(slides),
                                content_source=slide_item.get('content_source') or slide_item.get('contentSource'),
                                skip_vision=skip_vision,
                            )
                            return idx, h, r

                    max_workers = min(4, len(indexes))
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [executor.submit(_edit_worker, idx) for idx in indexes]
                        completed_count = 0
                        total_slides_count = len(indexes)
                        for future in concurrent.futures.as_completed(futures):
                            completed_count += 1
                            try:
                                idx_res, updated_html_res, resp_text_res = future.result()
                                original_html_res = slides[idx_res].get('html', '')
                                if designer_chat_reliability.materially_changed(
                                        original_html_res, updated_html_res, resp_text_res):
                                    slides[idx_res]['html'] = updated_html_res
                                    slides[idx_res]['_designer_keep_html'] = True
                                    slides[idx_res]['is_custom'] = True
                                    changed_indexes.append(idx_res)
                                    extracted_caps = slide_engine._extract_visual_concept_captions(updated_html_res)
                                    if extracted_caps:
                                        slides[idx_res]['captions'] = extracted_caps
                                if resp_text_res:
                                    assistant_messages.append(resp_text_res)
                            except Exception as exc:
                                print(f"[PARALLEL EDIT ERROR] Slide edit failed: {exc}")
                            pct = int(15 + 75 * (completed_count / total_slides_count))
                            report_designer_progress(pct, f"تمت معالجة الشريحة {completed_count} من {total_slides_count}...")
                else:
                    for idx in indexes:
                        slide = slides[idx] if isinstance(slides[idx], dict) else {}
                        original_html = slide.get('html', '')
                        report_designer_progress(40, f"جاري تعديل الشريحة {idx + 1}...")
                        html, response_text = _designer_edit_slide(
                            original_html, slide.get('title', f'شريحة {idx + 1}'),
                            instruction, idx, project_data, presentation_id, branding,
                            tenant_id=tenant_id, creative_images=creative_images,
                            user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                            total_slides=len(slides),
                            content_source=slide.get('content_source') or slide.get('contentSource'),
                            progress_callback=lambda attempt, total: report_designer_progress(
                                min(78, 35 + attempt * 12),
                                f"جاري تنفيذ محاولة تعديل الشريحة {attempt} من {total}...",
                            ),
                        )
                        if designer_chat_reliability.materially_changed(original_html, html, response_text):
                            slide['html'] = html
                            slide['_designer_keep_html'] = True
                            slide['is_custom'] = True
                            changed_indexes.append(idx)
                            extracted_caps = slide_engine._extract_visual_concept_captions(html)
                            if extracted_caps:
                                slide['captions'] = extracted_caps
                            slides[idx] = slide
                        if response_text:
                            assistant_messages.append(response_text)
                        report_designer_progress(85, f"تم الانتهاء من معالجة الشريحة {idx + 1}...")
                executed.append({
                    'tool': tool,
                    'status': 'success' if changed_indexes else 'noop',
                    'reason': None if changed_indexes else 'no_verified_change',
                    'indexes': sorted(changed_indexes),
                    'requested_indexes': indexes,
                })
            elif tool == 'insert_team_logo':
                raw_team_index = params.get('team_index') or params.get('teamIndex') or 0
                try:
                    team_index = int(raw_team_index)
                except (TypeError, ValueError):
                    team_index = 0
                team_members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
                team_member = (
                    team_members[team_index - 1]
                    if isinstance(team_members, list) and 0 < team_index <= len(team_members)
                    and isinstance(team_members[team_index - 1], dict)
                    else None
                )
                if not team_member or not team_member.get('logo'):
                    assistant_messages.append('لا يوجد شعار مرفوع للجهة المحددة في فريق العمل؛ لم يتم إنشاء شعار بديل.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'team_logo_missing'})
                    continue
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                team_name = str(team_member.get('name') or f'الجهة {team_index}').strip()
                team_token = f'##TEAM_LOGO_{team_index}##'
                team_instruction = (
                    f"أدرج شعار جهة فريق العمل «{team_name}» داخل موضع محتوى مناسب ومرئي في هذه الشريحة، "
                    f"باستخدام الرمز {team_token} فقط؛ يجب أن يتحول الرمز إلى الشعار المرفوع فعلياً. "
                    "لا تستخدم ##LOGO## ولا ##PROJECT_LOGO## لهذا الطلب، ولا تضع شعار الجهة في هيدر شعار الشركة، "
                    "وحافظ على شعار الشركة الموجود وبقية محتوى الشريحة وتوازنها البصري."
                )
                successful_indexes = []
                for i, idx in enumerate(indexes):
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    updated_html, response_text = _designer_edit_slide(
                        slide.get('html', ''), slide.get('title', f'شريحة {idx + 1}'),
                        team_instruction, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                    )
                    updated_html = _inject_team_logo_fallback(
                        updated_html, str(team_member.get('logo') or ''), team_index
                    )
                    slide['html'] = updated_html
                    slide['_designer_keep_html'] = True
                    slide['is_custom'] = True
                    slides[idx] = slide
                    successful_indexes.append(idx)
                    if response_text:
                        assistant_messages.append(response_text)
                    pct = int(15 + 75 * ((i + 1) / max(1, len(indexes))))
                    report_designer_progress(pct, f"تم إدراج الشعار في الشريحة {i + 1} من {len(indexes)}...")
                executed.append({'tool': tool, 'status': 'success' if successful_indexes else 'failed',
                                 'indexes': successful_indexes, 'team_index': team_index,
                                 'token': team_token})
            elif tool == 'insert_company_logo_panel':
                indexes = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                company_logo_url = str(
                    branding.get('logo_path') or branding.get('logo') or branding.get('logo_url') or '/assets/logo.png'
                ).strip()
                company_instruction = (
                    'انقل شعار الشركة المعتمد باستخدام الرمز ##LOGO## إلى داخل المربع الكحلي الموجود في يمين الشريحة، '
                    'واجعله فوق رقم سنوات الخبرة مباشرة داخل نفس المربع. لا تستخدم ##TEAM_LOGO_N## ولا شعار جهة من فريق العمل، '
                    'ولا تضع الشعار في أعلى يسار الشريحة. حافظ على الرقم 55 وبقية النصوص والتنسيق.'
                )
                successful_indexes = []
                for i, idx in enumerate(indexes):
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    updated_html, response_text = _designer_edit_slide(
                        slide.get('html', ''), slide.get('title', f'شريحة {idx + 1}'),
                        company_instruction, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                    )
                    updated_html = _inject_company_logo_panel_fallback(updated_html, company_logo_url)
                    slide['html'] = updated_html
                    slide['_designer_keep_html'] = True
                    slide['is_custom'] = True
                    slides[idx] = slide
                    successful_indexes.append(idx)
                    if response_text:
                        assistant_messages.append(response_text)
                    pct = int(15 + 75 * ((i + 1) / max(1, len(indexes))))
                    report_designer_progress(pct, f"تم وضع الشعار في الشريحة {i + 1} من {len(indexes)}...")
                executed.append({'tool': tool, 'status': 'success' if successful_indexes else 'failed',
                                 'indexes': successful_indexes, 'placement': 'right_panel_above_experience_years'})
            elif tool in ('generate_image', 'generate_design_image', 'insert_image_into_slide'):
                prompt = params.get('prompt') or message
                comp_name = params.get('component_name') or params.get('component') or ''
                if not comp_name and current_index < len(slides):
                    cur_title = slides[current_index].get('title', '')
                    comps = (project_data.get('interior_components') or project_data.get('components') or []) if isinstance(project_data, dict) else []
                    for c in comps:
                        c_title = (c.get('name') or c.get('title') or '') if isinstance(c, dict) else ''
                        if c_title and c_title in cur_title:
                            comp_name = c_title
                            break

                ref_images = _find_component_reference_image(comp_name or prompt or message, project_data, creative_images)
                if ref_images:
                    image_raw = call_image_api_with_references(prompt, references=ref_images)
                else:
                    image_raw = call_image_api(prompt)

                image = persist_generated_image(image_raw, tenant_id)
                if not image:
                    raise RuntimeError('تعذر توليد الصورة. تحقق من إعداد OpenRouter ورصيده.')
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                position = params.get('position', 'surgical')
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    orig_html = slide.get('html', '')
                    caption_text = comp_name or prompt[:60]
                    caption_markup = f'<div data-visual-media-caption="1" style="font-size:12px;color:#c5a059;margin-top:6px;font-weight:600;text-align:center;">{caption_text}</div>'
                    if position in ('surgical', 'inline') or not position:
                        instruction_img = (
                            f"أدرج الصورة الجديدة ({image}) في تصميم الشريحة كعنصر مرئي رئيسي متناسق وجميل مع بطاقة شرح توضيحي ({caption_markup}). "
                            f"حافظ على جميع النصوص والبطاقات واضبط مكان الصورة باحترافية وتوازن بدون أي إيموجي أو أيقونات."
                        )
                        updated_html, r_msg = _designer_edit_slide(
                            orig_html, slide.get('title', f'شريحة {idx + 1}'),
                            instruction_img, idx, project_data, presentation_id, branding,
                            tenant_id=tenant_id, creative_images=creative_images,
                            user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                            total_slides=len(slides),
                            content_source=slide.get('content_source') or slide.get('contentSource'),
                        )
                        slide['html'] = updated_html
                        slide['_designer_keep_html'] = True
                        if r_msg:
                            assistant_messages.append(r_msg)
                    elif position == 'background':
                        tag = f'<div aria-hidden="true" style="position:absolute;inset:0;background-image:url(\'{image}\');background-size:cover;background-position:center;z-index:0;"></div>'
                        slide['html'] = re.sub(r'(</div>\s*)$', tag + r'\1', orig_html or '', count=1)
                        slide['_designer_keep_html'] = True
                    else:
                        side = 'right:40px' if position != 'left' else 'left:40px'
                        tag = f'<div style="position:absolute;{side};top:120px;width:38%;z-index:2;"><img src="{image}" alt="" style="width:100%;max-height:460px;object-fit:cover;border-radius:8px;">{caption_markup}</div>'
                        slide['html'] = re.sub(r'(</div>\s*)$', tag + r'\1', orig_html or '', count=1)
                        slide['_designer_keep_html'] = True
                    slides[idx] = slide
                creative_images.setdefault('generated', []).append(image)
                executed.append({'tool': tool, 'status': 'success', 'indexes': targets, 'image': image})
            elif tool in ('insert_canonical_map', 'insert_map'):
                map_type = str(params.get('map_type') or 'overview').lower()
                refresh_requested = params.get('refresh') is True or params.get('use_latest') is True
                token_map = {
                    'overview': ('##MAP_OVERVIEW##', 'خريطة الموقع العام ونظرة جوية للأرض'),
                    'access': ('##MAP_ACCESS##', 'خريطة شبكة الطرق والمحاور الرئيسية للوصول'),
                    'catchment': ('##MAP_CATCHMENT##', 'خريطة النطاق الجغرافي واستيعاب المنطقة'),
                    'landmarks': ('##MAP_LANDMARKS##', 'خريطة المعالم الحيوية والخدمات وأوقات القيادة'),
                }
                token, label = token_map.get(map_type, ('##MAP_OVERVIEW##', 'خريطة الموقع العام'))
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                map_url = (_latest_canonical_map_url(
                    map_type, project_data, creative_images,
                    tenant_id=tenant_id, presentation_id=presentation_id,
                    preferred_images=[request_creative_images, project_creative_images],
                ) if refresh_requested else _approved_canonical_map_url(map_type, project_data, creative_images))
                if not map_url:
                    missing_text = (
                        f'لا توجد نسخة محفوظة حديثة من خريطة {label} لتحديثها.'
                        if refresh_requested else
                        f'لا توجد نسخة معتمدة محفوظة من خريطة {label} لإعادة إدراجها؛ لم يتم طلب خريطة جديدة من جوجل.'
                    )
                    assistant_messages.append(missing_text)
                    executed.append({'tool': tool, 'status': 'failed', 'indexes': targets,
                                     'map_type': map_type, 'reason': 'approved_map_missing'})
                    continue
                successful_targets = []
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    updated_html, replaced = _replace_slide_with_approved_map(
                        slide.get('html', ''), map_type, map_url
                    )
                    if not replaced:
                        assistant_messages.append(f'تعذر العثور على موضع خريطة {label} في الشريحة رقم {idx + 1}؛ لم يتم تغيير الشريحة.')
                        continue
                    updated_html = resolve_designer_chat_placeholders(
                        updated_html, project_data, presentation_id, tenant_id, creative_images
                    )
                    # A chat map refresh is a source swap, not a slide regeneration.
                    # Keep the existing HTML/layout and carry the exact marked image
                    # from the project section into the existing map slot.
                    slide['html'] = updated_html
                    slides[idx] = slide
                    successful_targets.append(idx)
                if successful_targets:
                    assistant_messages.append(
                        f"تم تحديث خريطة {label} في الشرائح المحددة من أحدث نسخة محفوظة دون توليد نسخة من جوجل."
                        if refresh_requested else
                        f'تمت إعادة إدراج خريطة {label} المعتمدة في الشرائح المحددة دون توليد نسخة من جوجل.'
                    )
                executed.append({'tool': tool, 'status': 'success' if successful_targets else 'failed',
                                 'indexes': successful_targets, 'map_type': map_type,
                                 'source': 'latest_persisted_map' if refresh_requested else 'approved_persisted_map'})
            elif tool in ('insert_financial_chart', 'update_financial_chart'):
                chart_type = str(params.get('chart_type') or 'waterfall').lower()
                targets = _designer_target_indexes(action, len(slides), current_index, force_all=is_all_slides_request)
                chart_desc = {
                    'waterfall': 'مخطط شلال التدفقات النقدية والأرباح الصافية',
                    'sensitivity': 'مخطط تحليل الحساسية للإيرادات ونسب الإشغال',
                    'compound_flows': 'مخطط التدفقات التراكمية وصافي القيمة الحالية (NPV)',
                    'financing_structure': 'مخطط توزيع هيكل التمويل والنفقات الرأسمالية والتشغيلية',
                }.get(chart_type, 'مخطط التحليل المالي والاستثماري')
                instruction_chart = (
                    f"أدرج رسم بياني مالي احترافي متناسق يوضح «{chart_desc}» معتمد على الأرقام والمؤشرات المالية للمشروع. "
                    f"حافظ على ألوان الهوية الرسمية (الكحلي الملكي والذهبي الاستثماري) والتباين العالي وخلو الشريحة من أي إيموجي أو أيقونات."
                )
                for idx in targets:
                    slide = slides[idx] if isinstance(slides[idx], dict) else {}
                    orig_html = slide.get('html', '')
                    updated_html, r_msg = _designer_edit_slide(
                        orig_html, slide.get('title', f'شريحة {idx + 1}'),
                        instruction_chart, idx, project_data, presentation_id, branding,
                        tenant_id=tenant_id, creative_images=creative_images,
                        user_image_refs=user_image_refs, slide_type=slide.get('type', 'content'),
                        total_slides=len(slides),
                        content_source=slide.get('content_source') or slide.get('contentSource'),
                    )
                    slide['html'] = updated_html
                    slide['_designer_keep_html'] = True
                    slides[idx] = slide
                    if r_msg:
                        assistant_messages.append(r_msg)
                executed.append({'tool': tool, 'status': 'success', 'indexes': targets, 'chart_type': chart_type})
            elif tool in ('delete_slide', 'remove_slide'):
                raw_nums = params.get('slide_numbers') or params.get('slide_number') or params.get('slide_index') or params.get('index')
                target_nums = []
                if isinstance(raw_nums, list):
                    for v in raw_nums:
                        try:
                            target_nums.append(int(v))
                        except (TypeError, ValueError):
                            pass
                else:
                    try:
                        target_nums.append(int(raw_nums))
                    except (TypeError, ValueError):
                        target_nums.append(current_index + 1)
                del_indexes = sorted(set(n - 1 for n in target_nums if 0 <= n - 1 < len(slides)), reverse=True)
                if del_indexes:
                    if len(slides) - len(del_indexes) >= 1:
                        removed_titles = []
                        for d_idx in del_indexes:
                            removed = slides.pop(d_idx)
                            removed_titles.append(f'«{removed.get("title", f"شريحة {d_idx + 1}")}»')
                        assistant_messages.append(f'تم حذف {len(del_indexes)} شريحة بنجاح ({", ".join(removed_titles)}).')
                        executed.append({'tool': tool, 'status': 'success', 'deleted_indexes': del_indexes})
                    else:
                        assistant_messages.append('لا يمكن حذف جميع الشرائح المتبقية في العرض.')
                        executed.append({'tool': tool, 'status': 'rejected', 'reason': 'single_slide'})
                else:
                    assistant_messages.append('أرقام الشرائح المحددة للحذف غير صحيحة.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'out_of_bounds'})
            elif tool in ('duplicate_slide', 'clone_slide'):
                raw_num = params.get('slide_number') or params.get('slide_index') or params.get('index')
                try:
                    target_num = int(raw_num)
                except (TypeError, ValueError):
                    target_num = current_index + 1
                dup_idx = target_num - 1
                if 0 <= dup_idx < len(slides):
                    cloned = copy.deepcopy(slides[dup_idx])
                    cur_title = cloned.get('title', '')
                    cloned['title'] = cur_title + ' (نسخة)' if not cur_title.endswith('(نسخة)') else cur_title
                    slides.insert(dup_idx + 1, cloned)
                    assistant_messages.append(f'تم تكرار الشريحة رقم {target_num} بنجاح.')
                    executed.append({'tool': tool, 'status': 'success', 'duplicated_index': dup_idx + 1})
                else:
                    assistant_messages.append(f'رقم الشريحة {target_num} غير موجود.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'out_of_bounds'})
            elif tool in ('reorder_slides', 'move_slide'):
                from_num = params.get('from_index') or params.get('from')
                to_num = params.get('to_index') or params.get('to')
                try:
                    f_idx = int(from_num) - 1
                    t_idx = int(to_num) - 1
                except (TypeError, ValueError):
                    f_idx, t_idx = -1, -1
                if 0 <= f_idx < len(slides) and 0 <= t_idx < len(slides) and f_idx != t_idx:
                    moved = slides.pop(f_idx)
                    slides.insert(t_idx, moved)
                    assistant_messages.append(f'تم نقل الشريحة من الترتيب {f_idx + 1} إلى الترتيب {t_idx + 1} بنجاح.')
                    executed.append({'tool': tool, 'status': 'success', 'from_index': f_idx, 'to_index': t_idx})
                else:
                    assistant_messages.append('تعذر تغيير ترتيب الشريحة؛ تحقق من أرقام الشرائح المحددة.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'invalid_indexes'})
            elif tool in ('split_slide', 'split_dense_slide'):
                raw_num = params.get('slide_number') or params.get('slide_index') or params.get('index')
                try:
                    target_num = int(raw_num)
                except (TypeError, ValueError):
                    target_num = current_index + 1
                sp_idx = target_num - 1
                if 0 <= sp_idx < len(slides):
                    base_slide = slides[sp_idx]
                    base_html = base_slide.get('html', '')
                    base_title = base_slide.get('title', f'شريحة {target_num}')

                    # 1. Check if slide contains a large table
                    table_parts = designer_chat_reliability.split_table_slide(base_html, base_title, 'auto')
                    if table_parts and len(table_parts) >= 2:
                        generated = []
                        for part in table_parts:
                            p_slide = copy.deepcopy(base_slide)
                            p_slide['title'] = part['title']
                            p_slide['html'] = _carry_slide_watermark(base_html, part['html'])
                            p_slide['_designer_keep_html'] = True
                            generated.append(p_slide)
                        slides[sp_idx:sp_idx + 1] = generated
                        assistant_messages.append(f'تم تقسيم جدول الشريحة رقم {target_num} إلى {len(generated)} شرائح متوازنة.')
                        executed.append({'tool': tool, 'status': 'success', 'split_index': sp_idx, 'parts': len(generated)})
                    else:
                        parts_param = params.get('parts')
                        req_parts = designer_chat_reliability.split_request_parts(params.get('instruction') or message)
                        if isinstance(parts_param, int) and parts_param >= 2:
                            parts_count = min(parts_param, 6)
                        elif isinstance(req_parts, int) and req_parts >= 2:
                            parts_count = min(req_parts, 6)
                        else:
                            parts_count = 2

                        clean_base_title = re.sub(r'\s*[-–—]\s*الجزء\s+\S+(?:\s+من\s+\S+)?\s*$', '', str(base_title or '')).strip() or f'شريحة {target_num}'
                        part_ordinals = ['الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس']
                        part_titles = [
                            f"{clean_base_title} - الجزء {part_ordinals[i] if i < len(part_ordinals) else (i + 1)}"
                            for i in range(parts_count)
                        ]

                        try:
                            flask_app = current_app._get_current_object()
                        except Exception:
                            flask_app = None

                        def _render_part_job(p_idx):
                            def _do():
                                p_title = part_titles[p_idx]
                                p_num = p_idx + 1
                                p_instr = (
                                    f"هذه عملية توزيع وإعادة تصميم محتوى الشريحة على {parts_count} شرائح بتصميم فاخر وقوي بصرياً. "
                                    f"أنشئ الشريحة ({p_title}): احتفظ فقط بالجزء {p_num} من أصل {parts_count} من عناصر وبيانات ومؤشرات الشريحة الأصلية. "
                                    f"تعليمات المستخدم الإضافية: {params.get('instruction') or message}. "
                                    "حافظ على فخامة التصميم، المساحات المريحة، والوضوح التام بدون أي إيموجي أو أيقونات."
                                )
                                out_html, r_text = _designer_edit_slide(
                                    base_html, p_title, p_instr, sp_idx + p_idx,
                                    project_data, presentation_id, branding,
                                    tenant_id=tenant_id, creative_images=creative_images,
                                    user_image_refs=user_image_refs,
                                    slide_type=base_slide.get('type', 'content'),
                                    total_slides=len(slides) + parts_count - 1,
                                    content_source=base_slide.get('content_source') or base_slide.get('contentSource'),
                                )
                                return p_idx, p_title, out_html, r_text

                            if flask_app:
                                with flask_app.app_context():
                                    from flask import g
                                    g.tenant_id = tenant_id
                                    return _do()
                            return _do()

                        part_results = []
                        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, parts_count)) as executor:
                            futures = [executor.submit(_render_part_job, i) for i in range(parts_count)]
                            for f in concurrent.futures.as_completed(futures):
                                try:
                                    part_results.append(f.result())
                                except Exception as err:
                                    print(f"[SPLIT SLIDE ERROR] {err}")
                        part_results.sort(key=lambda item: item[0])

                        if len(part_results) != parts_count or any(
                            not designer_chat_reliability.materially_changed(base_html, res[2], res[3])
                            for res in part_results
                        ):
                            card_parts = designer_chat_reliability.split_cards_or_blocks(base_html, clean_base_title, parts_count)
                            if card_parts and len(card_parts) >= 2:
                                generated = []
                                for cp in card_parts:
                                    p_slide = copy.deepcopy(base_slide)
                                    p_slide['title'] = cp['title']
                                    p_slide['html'] = _carry_slide_watermark(base_html, cp['html'])
                                    p_slide['_designer_keep_html'] = True
                                    generated.append(p_slide)
                                slides[sp_idx:sp_idx + 1] = generated
                                assistant_messages.append(f'تم توزيع محتوى وعناصر الشريحة رقم {target_num} إلى {len(generated)} شرائح متوازنة.')
                                executed.append({'tool': tool, 'status': 'success', 'split_index': sp_idx, 'parts': len(generated)})
                            else:
                                generated = []
                                for p_idx, p_title, p_html, _ in (part_results if part_results else [(0, part_titles[0], base_html, '')]):
                                    p_slide = copy.deepcopy(base_slide)
                                    p_slide['title'] = p_title
                                    p_slide['html'] = _carry_slide_watermark(base_html, p_html)
                                    p_slide['_designer_keep_html'] = True
                                    generated.append(p_slide)
                                slides[sp_idx:sp_idx + 1] = generated
                                assistant_messages.append(f'تم توزيع الشريحة رقم {target_num} على {len(generated)} شرائح.')
                                executed.append({'tool': tool, 'status': 'success', 'split_index': sp_idx, 'parts': len(generated)})
                        else:
                            generated = []
                            for p_idx, p_title, p_html, _ in part_results:
                                p_slide = copy.deepcopy(base_slide)
                                p_slide['title'] = p_title
                                p_slide['html'] = _carry_slide_watermark(base_html, p_html)
                                p_slide['_designer_keep_html'] = True
                                generated.append(p_slide)
                            slides[sp_idx:sp_idx + 1] = generated
                            assistant_messages.append(f'تم تقسيم الشريحة رقم {target_num} بنجاح إلى {len(generated)} شرائح متناسقة ومصممة بعناية.')
                            executed.append({'tool': tool, 'status': 'success', 'split_index': sp_idx, 'parts': len(generated)})
                else:
                    assistant_messages.append(f'رقم الشريحة {target_num} غير صحيح.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'out_of_bounds'})
            elif tool in ('merge_slides', 'combine_slides'):
                nums = params.get('slide_numbers') or [params.get('first_slide'), params.get('second_slide')]
                resolved_nums = []
                if isinstance(nums, list):
                    for n in nums:
                        try:
                            resolved_nums.append(int(n))
                        except (TypeError, ValueError):
                            pass
                if len(resolved_nums) >= 2:
                    idx1 = min(resolved_nums[0] - 1, resolved_nums[1] - 1)
                    idx2 = max(resolved_nums[0] - 1, resolved_nums[1] - 1)
                elif len(slides) >= 2:
                    idx1 = max(0, min(len(slides) - 2, current_index))
                    idx2 = idx1 + 1
                else:
                    idx1, idx2 = -1, -1
                if 0 <= idx1 < len(slides) and 0 <= idx2 < len(slides) and idx1 != idx2:
                    slide1 = slides[idx1]
                    slide2 = slides[idx2]
                    merged_title = params.get('title') or slide1.get('title', '')
                    merge_instruction = (
                        f"ادمج محتوى وبيانات هاتين الشريحتين في شريحة واحدة متكاملة ومنظمة بدون أي حشو. "
                        f"محتوى الشريحة الأولى: {slide1.get('title', '')}. "
                        f"محتوى الشريحة الثانية: {slide2.get('title', '')}. "
                        f"تعليمات الدمج: {params.get('instruction') or message}."
                    )
                    merged_html, r_msg = _designer_edit_slide(
                        slide1.get('html', ''), merged_title, merge_instruction, idx1,
                        project_data, presentation_id, branding, tenant_id=tenant_id,
                        creative_images=creative_images, user_image_refs=user_image_refs,
                        slide_type=slide1.get('type', 'content'), total_slides=len(slides) - 1,
                    )
                    slide1['html'] = merged_html
                    slide1['title'] = merged_title
                    slide1['_designer_keep_html'] = True
                    slides[idx1] = slide1
                    slides.pop(idx2)
                    assistant_messages.append(f'تم دمج الشريحتين {idx1 + 1} و {idx2 + 1} في شريحة واحدة بنجاح.')
                    executed.append({'tool': tool, 'status': 'success', 'merged_index': idx1, 'removed_index': idx2})
                else:
                    assistant_messages.append('تعذر دمج الشرائح المحددة؛ تحقق من أرقام الشرائح.')
                    executed.append({'tool': tool, 'status': 'failed', 'reason': 'invalid_indexes'})
            elif tool in ('create_slide', 'create_design_slide'):
                title = params.get('title') or 'شريحة جديدة'
                slide_type = params.get('type') or 'content'
                plan_slide = {'title': title, 'type': slide_type, 'design_style': params.get('designStyle', 'cards'), 'bullets': []}
                pos_raw = params.get('position') or params.get('after') or params.get('index')
                try:
                    pos = int(pos_raw) if pos_raw is not None else len(slides)
                except (TypeError, ValueError):
                    pos = len(slides)
                pos = max(0, min(len(slides), pos))
                html, _ = _designer_edit_slide(
                    '<div class="slide" style="width:1280px;height:720px;"><h1>' + title + '</h1></div>',
                    title, params.get('instruction') or message, pos, project_data,
                    presentation_id, branding, tenant_id=tenant_id, creative_images=creative_images,
                    user_image_refs=user_image_refs, slide_type=slide_type,
                    total_slides=len(slides) + 1,
                )
                new_slide = {'html': html, 'title': title, 'type': slide_type, 'designStyle': plan_slide['design_style'], 'bullets': [], 'metrics': [], '_designer_keep_html': True}
                slides.insert(pos, new_slide)
                executed.append({'tool': tool, 'status': 'success', 'index': pos})
                assistant_messages.append(f'تمت إضافة الشريحة الجديدة «{title}» في الموضع {pos + 1}.')
            elif tool in ('regenerate_maps', 'update_map_style', 'change_map_type'):
                maptype = params.get('maptype') or params.get('style') or 'roadmap'
                executed.append({'tool': tool, 'status': 'deferred', 'maptype': maptype})
                assistant_messages.append('لم تتغير خرائط الموقع المعتمدة؛ توليد الخرائط منفصل لكل خريطة.')
            else:
                executed.append({'tool': tool, 'status': 'skipped', 'message': 'أداة غير معروفة'})

        # Auto-heal any multi-slide containers or unpackable fragments into distinct slides
        try:
            slides = designer_chat_reliability._auto_heal_workspace_slides(slides, globals())
        except Exception:
            pass

        slides = slide_engine.renumber_presentation_slides(
            slides, branding=branding, project_data=project_data, tenant_id=tenant_id,
            allow_all_maps=True, creative_images=creative_images,
        )
        validation = _validate_workspace_data({'slidesData': slides})
        if not validation['valid']:
            try:
                healed_slides = designer_chat_reliability._auto_heal_workspace_slides(slides, globals())
                healed_val = _validate_workspace_data({'slidesData': healed_slides})
                if healed_val['valid']:
                    slides = healed_slides
                    validation = healed_val
            except Exception:
                pass
        if not validation['valid']:
            return jsonify({'success': False, 'error': 'تم رفض التعديل لأن العرض يحتوي على شرائح غير صالحة', 'validation': validation}), 422
        slide_changes = change_tracking.describe_slide_changes(slides_before, slides)
        touched = [item.get('index') + 1 for item in executed
                   if isinstance(item, dict) and isinstance(item.get('index'), int)]
        touched += [n + 1 for item in executed if isinstance(item, dict)
                    for n in (item.get('indexes') or []) if isinstance(n, int)]
        turn_focus = sorted(dict.fromkeys(touched)) or focus_indexes
        successful_execution = any(
            isinstance(item, dict) and item.get('status') == 'success'
            for item in executed
        )
        failure_reason = None
        if successful_execution:
            response_text = plan.get('response') or 'تم تنفيذ طلبك على العرض بالكامل.'
            if assistant_messages:
                response_text += ' ' + ' '.join(dict.fromkeys(assistant_messages))
        else:
            failure_reason = next((
                item.get('reason') for item in executed
                if isinstance(item, dict) and item.get('reason')
            ), 'no_verified_change')
            detail = ' '.join(dict.fromkeys(assistant_messages)).strip()
            response_text = 'لم يتم تنفيذ أي تعديل على العرض.' + (f' {detail}' if detail else '')
        # Return the updated conversation beside the edited workspace. The browser keeps both in
        # memory until the user explicitly presses save; writing here would make a failed edit
        # impossible to discard with a refresh.
        persisted_messages = _normalize_designer_chat_messages(history_for_turn)[-DESIGNER_CHAT_STORED_TURNS * 2:]
        if not persisted_messages or persisted_messages[-1].get('content') != message or persisted_messages[-1].get('role') != 'user':
            persisted_messages.append({'role': 'user', 'content': message[:2000], 'slides': preferred_indexes[:]})
        persisted_messages.append({'role': 'assistant', 'content': response_text[:2000], 'slides': preferred_indexes[:]})
        persisted_project_data = dict(project_data)
        persisted_project_data['tenantSlidesData'] = slides
        persisted_project_data['designerChat'] = {
            'messages': persisted_messages[-DESIGNER_CHAT_STORED_TURNS * 2:],
            'memory': chat_memory,
            'focusIndexes': turn_focus or preferred_indexes,
        }
        # The slides this turn actually touched become the conversation's focus, so the next
        # message («وطلعها أوضح») lands on them without asking again.
        # Both keys carry 0-based indexes; the chat speaks in 1-based slide numbers.
        persisted_project_data['designerChat']['focusIndexes'] = turn_focus
        # ``creative_images`` is the generation view and intentionally aliases
        # editable placeholders to the marked canonical image. Do not send that
        # alias back to the browser: the location editor needs the persisted
        # clean sidecar so its HTML labels are not drawn over raster labels.
        response_creative_images = copy.deepcopy(creative_images)
        source_creative_images = request_creative_images or project_creative_images
        if isinstance(source_creative_images, dict) and isinstance(source_creative_images.get('map_placeholders'), dict):
            returned_placeholders = response_creative_images.get('map_placeholders')
            returned_placeholders = dict(returned_placeholders) if isinstance(returned_placeholders, dict) else {}
            returned_placeholders.update(source_creative_images['map_placeholders'])
            response_creative_images['map_placeholders'] = returned_placeholders
        response_data = {
            'action': 'workspace_update', 'response': response_text,
            'slidesData': slides, 'creativeImages': response_creative_images,
            'actions': executed, 'validation': validation,
            'memory': chat_memory, 'focusIndexes': turn_focus,
            'chatHistory': persisted_project_data['designerChat']['messages'],
            'saved': False,
        }
        if failure_reason:
            response_data['failureReason'] = failure_reason
        return jsonify({'success': True, 'data': response_data})
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
        response = call_zai_chat(glm_prompt, "اكتب البرومبت.", max_tokens=500, usage_ctx=_usage_ctx('image', data))
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
    # The watermark file is set only through its upload endpoint; a
    # client-sent path must never choose the file on disk.
    data = {key: value for key, value in data.items()
            if key != 'watermark_path'}
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


@app.route('/api/branding/font-status', methods=['GET'])
@require_auth
def api_branding_font_status():
    """Say whether this company's font is really loadable, and from where.

    A font that silently falls back looks identical to a font that was never chosen, so this reports
    the resolved source instead of leaving it to guesswork: a real @font-face with an embedded or
    served file, a `src:local()` name that only works if the machine has that font installed, a
    Google import that needs the network, or nothing at all.
    """
    from design_templates import build_font_css, _load_bundled_fonts
    branding = db.get_branding(g.tenant_id) or {}
    selections = db.get_tenant_font_selections(g.tenant_id) or []
    result = build_font_css(branding, g.tenant_id, embed=False)
    css = (result[0] if result else '') or ''
    family = (result[1] if result else '') or ''
    faces = css.count('@font-face')
    embedded = css.count('base64,')
    served = len(re.findall(r"url\('/tenant-assets/", css))
    google_import = '@import' in css
    # How the glyphs actually arrive decides whether the font can be trusted: a file we ship or
    # serve always renders, a Google import needs the network, and a bare local() name renders only
    # on a machine that happens to have that font installed. The shipped Arabic safety net is not
    # counted as the company's own face, otherwise choosing Arial would report itself as embedded.
    shipped_fallback = 'platform-fallback-arabic' in css
    own_embedded = max(0, embedded - (1 if shipped_fallback else 0))
    if own_embedded:
        renders = 'embedded file'
    elif served:
        renders = 'served file'
    elif google_import:
        renders = 'google web font'
    elif 'src:local(' in css:
        renders = 'installed name only with shipped fallback' if shipped_fallback else 'installed name only'
    elif css:
        renders = 'embedded file' if embedded else 'installed name only'
    else:
        renders = 'nothing'
    local_only = renders == 'installed name only'
    if not css:
        source = 'none'
    elif selections:
        source = 'company selection'
    elif branding.get('font_file_path') or branding.get('font_file_data'):
        source = 'legacy upload'
    else:
        source = 'platform default'

    # Arabic and Latin resolve independently, and a script with no selection keeps the platform
    # default. Picking a Latin-only font therefore left every Arabic word unchanged, which read as
    # "the font does nothing" — so the resolved pair is reported.
    scripts = {}
    for script in ('arabic', 'latin'):
        chosen_faces = [item for item in selections if item.get('script') == script]
        if chosen_faces:
            names = []
            for item in chosen_faces:
                if item.get('custom_font_path') or item.get('custom_font_data'):
                    names.append(os.path.basename(str(item.get('custom_font_path') or 'خط مرفوع')))
                else:
                    font = db.get_sag_font(item.get('font_id')) or {}
                    names.append(font.get('font_name') or font.get('font_family') or 'خط مختار')
            scripts[script] = {'chosen': True, 'font': names[0],
                               'weights': sorted({item.get('weight') for item in chosen_faces if item.get('weight')})}
        else:
            defaults = [font for font in (db.get_sag_fonts(script=script) or []) if font.get('is_default')]
            default = next((font for font in defaults if font.get('weight') == 'regular'), None) or (defaults[0] if defaults else None)
            scripts[script] = {'chosen': False,
                               'font': (default or {}).get('font_name') or (default or {}).get('font_family') or 'الخط الافتراضي',
                               'weights': []}
    return jsonify({
        'success': True,
        'status': {
            'source': source,
            'familyList': family,
            'brandingFontFamily': branding.get('font_family'),
            'selections': [{'script': item.get('script'), 'weight': item.get('weight'),
                            'uploaded': bool(item.get('custom_font_path') or item.get('custom_font_data')),
                            'fontFamily': item.get('font_family')} for item in selections],
            'fontFaces': faces,
            'embeddedFiles': embedded,
            'servedFiles': served,
            'googleImport': google_import,
            'renders': renders,
            'scripts': scripts,
            'shippedArabicFallback': shipped_fallback,
            'localNameOnly': local_only,
            'cssBytes': len(css),
            'bundledFaces': sorted(_load_bundled_fonts().keys()),
            'willRenderRealFont': renders in ('embedded file', 'served file', 'google web font',
                                             'installed name only with shipped fallback'),
        },
    })


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
        response = call_zai_chat(system_prompt, user_prompt, temperature=0.7, max_tokens=4000, usage_ctx=_usage_ctx('project_data', data))
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
        response = call_zai_chat(system_prompt, user_prompt, temperature=0.7, max_tokens=4000, usage_ctx=_usage_ctx('project_data', data))
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
    resolve_slide_bounds, build_fallback_plan, _suggest_design_style,
    _timeline_data_note, _financial_data_note,
)


PROJECT_SECTION_PRESENTATION_TARGETS = {
    'basic': (('overview', 'components'), 'بيانات المشروع'),
    'location': (('location',), 'الموقع الجغرافي'),
    'land_croquis': (('land',), 'تحليل الأرض'),
    'section-timeline': (('timeline',), 'الجدول الزمني'),
    'section-financial-calc': (('financial',), 'الدراسة المالية والمؤشرات'),
    'section-team': (('team',), 'فريق العمل'),
    'section-market-study': (('market', 'swot_risks'), 'دراسة السوق'),
    'section-visual-concept': (('plans', 'exterior', 'interior'), 'التصور البصري'),
    'section-executive-content': (('executive_summary',), 'المحتوى التنفيذي'),
    'contact': (('closing',), 'بيانات التواصل'),
}


def _ensure_required_location_slides(plan, project_data):
    if not isinstance(plan, dict) or not isinstance(plan.get('slides'), list):
        return plan
    slides = plan['slides']
    existing_types = {slide.get('type') for slide in slides if isinstance(slide, dict)}
    required = []
    if project_data.get('location_lat') and project_data.get('location_lng'):
        required.append({
            'title': 'بيانات الموقع والإحداثيات',
            'type': 'site_specs',
            'section_key': 'location',
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
                    'section_key': 'location',
                    'design_style': 'map',
                    'requires_image': True,
                    'content_density': 'medium',
                    'bullets': [],
                    'content_source': source,
                    'image_tokens': [f'##{slide_type.upper()}##'],
                })
        required.append({
            'title': 'ملخص الموقع الجغرافي',
            'type': 'content',
            'section_key': 'location',
            'design_style': 'map',
            'requires_image': True,
            'content_density': 'medium',
            'bullets': ['طبيعة الموقع وموقعه الاستراتيجي', 'الاتصال بالطرق والمعالم المحيطة', 'المزايا المستندة إلى بيانات الموقع'],
            'content_source': 'site_analysis',
            'image_tokens': ['##MAP_OVERVIEW##'],
        })
    if not required:
        return plan
    insert_at = 2 if len(slides) >= 2 else len(slides)
    for item in required:
        if item['type'] in existing_types:
            existing_slides = [slide for slide in slides if isinstance(slide, dict) and slide.get('type') == item['type']]
            for existing in existing_slides:
                if item.get('image_tokens'):
                    existing['image_tokens'] = list(item['image_tokens'])
                    existing['requires_image'] = True
                    existing['design_style'] = item.get('design_style') or existing.get('design_style')
            continue
        slides.insert(insert_at, item)
        insert_at += 1
        existing_types.add(item['type'])
    plan['slides'] = slides
    plan['proposed_count'] = len(slides)
    return plan


def _execute_slide_plan(project_data, tenant_id, branding, images=None, target_section_keys=None):
    """Ask the planner for a slide plan, then enforce the company's slide bounds on it."""
    target_section_keys = tuple(
        key for key in (target_section_keys or ())
        if key in slide_engine.PRESENTATION_SECTION_ORDER
    )
    section_mode = bool(target_section_keys)
    training_context = db.get_training_context(tenant_id) or ''
    slide_count_locked = bool(branding.get('lock_slide_count')) and not section_mode
    bounds_branding = dict(branding)
    if section_mode:
        bounds_branding['lock_slide_count'] = False
    configured_min, configured_max, locked_count = resolve_slide_bounds(bounds_branding)

    effective_max_slides = max(1, configured_max)
    effective_min_slides = 1 if section_mode else min(configured_min, effective_max_slides)

    # A locked slide count outranks any hint found in the training context.
    if not slide_count_locked and not section_mode:
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
    if section_mode:
        effective_branding['lock_slide_count'] = False
    if slide_count_locked:
        effective_branding['default_slide_count'] = locked_count
    elif effective_branding.get('default_slide_count', 0) > effective_max_slides:
        effective_branding['default_slide_count'] = effective_max_slides

    prompt = build_slide_plan_prompt(project_data, effective_branding, tenant_id=tenant_id, images=images)
    if section_mode:
        target_titles = '، '.join(slide_engine.PRESENTATION_SECTION_TITLES[key] for key in target_section_keys)
        prompt = (
            "## نطاق العرض المستقل\n"
            f"أنشئ خطة للغلاف والفهرس والأقسام التالية فقط ثم الخاتمة: {target_titles}.\n"
            "لا تضف أي قسم آخر، ولا تطبق الحد الأدنى لعدد شرائح العرض الكامل.\n\n"
            + prompt
        )
    if training_context:
        # Only a locked count is a ceiling. Otherwise the count follows the content, and this
        # header used to contradict the prompt by naming a maximum the prompt calls open.
        count_rule = (
            "هذا عرض مستقل لقسم محدد، وعدد شرائحه يتبع محتوى القسم فقط."
            if section_mode else
            f"عدد الشرائح لهذه الشركة مقفل على {locked_count} شريحة بالضبط."
            if slide_count_locked else
            f"لا يقل عدد الشرائح عن {effective_min_slides} شريحة، ولا يوجد حد أعلى: "
            "وزّع كل المحتوى المتاح على ما يحتاجه من شرائح دون اختصار أو دمج، "
            "وابقِ كل شريحة بفكرة واحدة غير مزدحمة."
        )
        prompt = f"## بيانات خاصة بالشركة وقاعدة عدد الشرائح\nتنبيه هام جداً: {count_rule}\n{training_context}\n\n---\n\n{prompt}"

    plan = None
    last_error = None
    # The planner must finish before the web worker timeout so a slow provider can fall back cleanly.
    max_attempts = 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = call_zai_chat_parallel(
                "أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية الاستثمارية.",
                prompt,
                # The outline is compact; a bounded fast-model request avoids the five-minute
                # Gunicorn kill that previously left the background job stuck at 8 percent.
                max_tokens=12000,
                attempts=1,
                timeout=75,
                model=LUNA_TEXT_MODEL,
                usage_ctx=_usage_ctx('slide_plan', project_data, tenant_id=tenant_id)
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

    # A failed planner used to be invisible: the generic fallback structure shipped as if the model
    # had produced it, so every such file came out with the same titles and the same count and it
    # looked like a fixed slide count instead of a failure.
    plan_source = 'model'
    plan_error = ''
    if not plan:
        print(f"[SLIDE-PLAN FALLBACK] Using fallback plan after {max_attempts} attempts. Last error: {last_error}")
        plan = build_fallback_plan(effective_branding)
        plan_source = 'fallback'
        plan_error = str(last_error or '')

    plan = _ensure_required_location_slides(plan, project_data)
    # A project with no financial study gets no financial slides at all, from any source.
    plan = slide_engine.strip_financial_slides(plan, project_data)
    # There are no photographs of the site, so a slide built to hold them holds empty frames.
    plan = slide_engine.strip_street_view_slides(plan)
    plan = slide_engine.normalize_presentation_plan(plan, project_data, images, tenant_id=tenant_id)
    has_financial = slide_engine.project_has_financial_study(project_data)

    # Enforce min and max slide counts strictly on generated plan
    slides = plan.get('slides', [])

    if len(slides) < effective_min_slides:
        print(f"[SLIDE-PLAN ENFORCE] Plan returned {len(slides)} slides, auto-padding to effective_min_slides ({effective_min_slides})")
        needed_extra = effective_min_slides - len(slides)
        extra_topics = [
            {'title': 'المواصفات الفنية وجودة المواد', 'style': 'cards', 'bullets': ['جودة التشطيبات والمواد المستخدمة', 'أنظمة التكييف والعزل الحراري', 'الضمانات وخدمات ما بعد البيع']},
            {'title': 'التحليل البيئي والمحيط المباشر', 'style': 'text', 'bullets': ['سهولة الوصول والمحاور الرئيسية', 'قرب المشروع من المرافق والمراكز الحيوية', 'جودة البيئة العمرانية المحيطة']},
            {'title': 'الخطة الزمنية ومراحل التطوير', 'style': 'timeline', 'bullets': ['مرحلة التخطيط والدراسات الأولية', 'مرحلة التنفيذ والإنشاءات', 'مرحلة التسليم والتشغيل']},
        ]
        if has_financial:
            extra_topics.insert(0, {'title': 'مؤشرات الأداء والقيمة المضافة', 'style': 'dashboard', 'bullets': ['تحليل العائد الاستثماري المتوقع', 'معدل الإشغال والاستدامة', 'قيمة الأصول على المدى الطويل']})
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

    plan['slides'] = slides
    plan = slide_engine.normalize_presentation_plan(plan, project_data, images, tenant_id=tenant_id)
    slides = plan['slides']

    # Trimming only happens for a tenant who locked the count: without a lock the maximum is
    # SLIDE_COUNT_OPEN, so a long plan is kept exactly as the planner produced it.
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
    plan = slide_engine.refresh_index_entries(plan)
    if section_mode:
        filtered_plan = slide_engine.filter_presentation_plan_sections(plan, target_section_keys)
        if not filtered_plan:
            target_titles = '، '.join(slide_engine.PRESENTATION_SECTION_TITLES[key] for key in target_section_keys)
            return {
                'success': False,
                'error': f'لا توجد بيانات متاحة لتوليد عرض قسم {target_titles}',
                'failureReason': 'section_empty',
            }
        plan = filtered_plan
    plan['source'] = plan_source
    if plan_error:
        plan['source_error'] = plan_error[:400]

    is_valid, issues = validate_slide_plan(plan, effective_branding)
    if not is_valid:
        print(f"[SLIDE-PLAN] Validation issues: {issues}")

    return {
        'success': True,
        'plan': plan,
        'planSource': plan_source,
        'validation': {'isValid': is_valid, 'issues': issues},
    }


def _emergency_slide_plan(project_data, branding, images, tenant_id, target_section_keys=None):
    plan = build_fallback_plan(branding)
    plan = _ensure_required_location_slides(plan, project_data)
    plan = slide_engine.strip_financial_slides(plan, project_data)
    plan = slide_engine.strip_street_view_slides(plan)
    plan = slide_engine.normalize_presentation_plan(plan, project_data, images, tenant_id=tenant_id)
    if target_section_keys:
        filtered = slide_engine.filter_presentation_plan_sections(plan, target_section_keys)
        if filtered:
            plan = filtered
    plan = slide_engine.refresh_index_entries(plan)
    plan['source'] = 'fallback'
    return plan


def _slide_plan_job_worker(flask_app, tenant_id, project_data, branding, images, job_id, target_section_keys=None):
    with flask_app.app_context():
        fallback_plan = _emergency_slide_plan(
            project_data, branding, images, tenant_id, target_section_keys=target_section_keys)
        _write_job('.plan_jobs', tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري تحليل بيانات المشروع وإعداد هيكل العرض...',
            'fallbackPlan': fallback_plan,
        })
        try:
            payload = _execute_slide_plan(
                project_data, tenant_id, branding, images,
                target_section_keys=target_section_keys,
            )
            succeeded = bool(payload.get('success'))
            _write_job('.plan_jobs', tenant_id, job_id, {
                **payload,
                'status': 'completed' if succeeded else 'failed',
                'message': 'تم إعداد خطة الشرائح' if succeeded else payload.get('error', 'تعذر إعداد خطة الشرائح'),
            })
        except Exception as exc:
            print(f'[SLIDE-PLAN JOB FAILED] {exc}')
            _write_job('.plan_jobs', tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'error': f'تعذر إعداد خطة الشرائح: {exc}',
                'failureReason': 'job_failed',
            })


@app.route('/api/slide-plan', methods=['POST'])
@require_permission('create_presentation')
def api_slide_plan():
    """
    AI analyzes project data and proposes a slide plan.
    Input: {projectData: {...}}
    Output: {jobId} in production, or {proposed_count, reasoning, slides: [...]} in tests.

    The planner needs minutes on a full project, and the live hosting proxy drops a request that
    stays open that long — the browser then saw a timeout for work the server had completed. So the
    plan is queued and polled, the same way the croquis and market-study jobs are.
    """
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = str(data.get('presentationId') or '').strip()
    if presentation_id and not project_data:
        presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
        if not presentation:
            return jsonify({'success': False, 'error': 'العرض غير موجود أو لا يتبع هذه الشركة'}), 404
        try:
            project_data = clean_project_data(json.loads(presentation.get('project_data') or '{}'))
        except (TypeError, ValueError):
            project_data = {}
        project_data = _merge_persisted_map_assets(
            project_data, g.tenant_id, presentation_id=presentation_id)
    images = _augment_generation_images(data.get('images', {}), project_data, g.tenant_id)
    branding = db.get_branding(g.tenant_id)
    project_section_key = str(data.get('sectionKey') or '').strip()
    section_target = PROJECT_SECTION_PRESENTATION_TARGETS.get(project_section_key) if project_section_key else None

    if project_section_key and not section_target:
        return jsonify({'success': False, 'error': 'قسم المشروع غير صالح'}), 400
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400

    target_section_keys = section_target[0] if section_target else None
    use_background = (not current_app.config.get('TESTING')) or bool(data.get('background'))
    if not use_background:
        payload = _execute_slide_plan(
            project_data, g.tenant_id, branding, images,
            target_section_keys=target_section_keys,
        )
        return jsonify(payload), 200 if payload.get('success') else 400

    job_id = str(_uuid.uuid4())
    fallback_plan = _emergency_slide_plan(
        project_data, branding, images, g.tenant_id, target_section_keys=target_section_keys)
    _write_job('.plan_jobs', g.tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'message': 'تم استلام طلب إعداد هيكل العرض',
        'fallbackPlan': fallback_plan,
    })
    threading.Thread(
        target=_slide_plan_job_worker,
        args=(current_app._get_current_object(), g.tenant_id, project_data, dict(branding), images, job_id, target_section_keys),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'message': 'بدأ إعداد هيكل العرض في الخلفية',
        'fallbackPlan': fallback_plan,
    }), 202


@app.route('/api/slide-plan/jobs/<job_id>', methods=['GET'])
@require_permission('create_presentation')
def api_slide_plan_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_job('.plan_jobs', g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'status': 'not_found',
            'error': 'المهمة غير موجودة أو انتهت صلاحيتها',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(job)


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
            place = maps_service.reverse_geocode_location(
                coords['lat'], coords['lng'], tenant_id=g.tenant_id, language='ar',
                usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data)
            ) or {}
            names = market_study.extract_city_district(
                place.get('address_components') or [],
                place.get('formatted_address') or '',
            )
            return jsonify({
                'success': True,
                'lat': coords['lat'],
                'lng': coords['lng'],
                'formatted_address': place.get('formatted_address') or (
                    address if (address and not address.startswith('http')) else 'تم الاستخراج من رابط خرائط جوجل'
                ),
                'city': names.get('city') or '',
                'district': names.get('district') or '',
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
    result = maps_service.get_nearby_landmarks(float(lat), float(lng), int(radius), max_results=int(data.get('maxResults', 20)), include_all=True, usage_ctx=maps_service.maps_usage_ctx('places', g.tenant_id, data=data))
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
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data))
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
        places = maps_service.get_nearby_landmarks(lat, lng, radius=landmark_radius_m, max_results=20, include_all=True, usage_ctx=maps_service.maps_usage_ctx('places', g.tenant_id, data=data))
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
            geo = maps_service.geocode_address(query, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('geocode', g.tenant_id, data=data))
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
        matrix = maps_service.get_drive_matrix((lat, lng), geocoded, usage_ctx=maps_service.maps_usage_ctx('matrix', g.tenant_id, data=data))
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
        generation_id, vision_usage = _extract_openrouter_usage(payload)
        _record_ai_usage(_usage_ctx('site'), IMAGE_MODEL,
                         'ok' if response.status_code < 400 and 'error' not in payload else 'error',
                         vision_usage, generation_id)
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
    arabic_location = maps_service.reverse_geocode_location(lat, lng, tenant_id=tenant_id, language='ar') or {}
    place_names = market_study.extract_city_district(
        arabic_location.get('address_components') or location_details.get('address_components') or [],
        arabic_location.get('formatted_address') or location_details.get('formatted_address') or '',
    )
    fields = {
        'location_lat': lat,
        'location_detail': arabic_location.get('formatted_address') or location_details.get('formatted_address', ''),
        'location_lng': lng,
        'nearby_landmarks': landmark_lines(nearby_items, nearby_matrix),
        'city_landmarks': landmark_lines(city_items),
    }
    if place_names.get('city') and not str(project_data.get('city') or '').strip():
        fields['city'] = place_names['city']
    if place_names.get('district') and not str(project_data.get('district') or '').strip():
        fields['district'] = place_names['district']
    if population.get('available'):
        fields['population_density'] = f"{population['value']} {population.get('unit', 'نسمة/كم²')}"
        fields['population_density_source'] = population.get('source')
    road_names = []
    for road in roads:
        name = road.get('name')
        if name and name not in road_names:
            road_names.append(name)
    road_names = maps_service.normalize_access_road_names(road_names)
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
    """Resolve and enrich site data without generating map images."""
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    if data.get('generateMaps') is True:
        return jsonify({
            'success': False,
            'error': 'توليد الخرائط متاح لكل خريطة على حدة بعد اعتماد تحليل الموقع',
            'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
        }), 400

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
            geo = maps_service.geocode_address(address, tenant_id=g.tenant_id, usage_ctx=maps_service.maps_usage_ctx('site', g.tenant_id, data=data))
            if geo.get('success'):
                lat, lng = geo['lat'], geo['lng']
                source = 'geocoding'

    if lat is None or lng is None:
        return jsonify({'success': False, 'error': 'أدخل رابط Google Maps أو عنوان الموقع أولاً'}), 400

    site_maps_ctx = maps_service.maps_usage_ctx('site', g.tenant_id, data=data)
    with maps_service.maps_usage_scope(site_maps_ctx):
        fields, nearby_items, nearby_matrix, city_items, city_matrix, roads, polygon, diagnostics = _collect_site_fields(
            project_data, g.tenant_id, lat, lng
        )
    fields.pop('secondary_roads', None)
    fields['location_polygon_source'] = (
        'manual' if project_data.get('location_polygon_source') == 'manual'
        # 'cleared' is the user switching the highlight off; it must survive a re-analysis.
        else 'cleared' if project_data.get('location_polygon_source') == 'cleared'
        else 'auto' if fields.get('location_polygon')
        else 'none'
    )

    return jsonify({
        'success': True,
        'fields': fields,
        'mapPlaceholders': {},
        'mapsDeferred': True,
        'landmarks': nearby_items,
        'landmarksMatrix': nearby_matrix,
        'cityLandmarks': city_items,
        'roads': roads,
        'zooms': {},
        'lat': lat,
        'lng': lng,
        'source': source,
        'boundary': {
            'status': 'verified_building' if polygon else 'needs_review',
            'estimated': False,
            'manual_edit_available': True,
        },
        'warning': None,
        'landmarksWarning': diagnostics.get('nearby_landmarks_error') or diagnostics.get('nearby_landmarks_warning'),
        'cityLandmarksWarning': diagnostics.get('city_landmarks_error') or diagnostics.get('city_landmarks_warning'),
    })


@app.route('/api/site-analysis', methods=['POST'])
@require_permission('create_presentation')
def api_site_analysis():
    data = request.json or {}
    raw_project_data = clean_project_data(data.get('projectData', {}))
    analysis_keys = (
        'project_name', 'project_type', 'project_subtype', 'project_idea', 'description', 'project_description',
        'project_goal', 'project_stage', 'initial_features', 'initial_strengths',
        'project_features', 'investment_opportunities', 'target_audience', 'location_address',
        'location_maps_link', 'maps_link', 'location_detail', 'location_lat', 'location_lng',
        'city', 'district', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
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
            'location_detail', 'main_roads', 'nearby_landmarks', 'nearby_landmarks_data',
            'city_landmarks', 'catchment_areas', 'population_density',
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
  6. الطرق الرئيسية وطبيعة الوصول.
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
                reasoning_effort='max', usage_ctx=_usage_ctx('site', data))
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
                model=LUNA_TEXT_MODEL,
                usage_ctx=_usage_ctx('site', data)
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
    project_data = clean_project_data(data.get('projectData', {})) or {}
    overlay_only = data.get('overlayOnly') is True and map_type in {'overview', 'access', 'catchment', 'landmarks'}
    if not overlay_only and project_data.get('location_analysis_approved') is not True:
        return jsonify({
            'success': False,
            'error': 'يجب اعتماد تحليل الموقع قبل إنشاء الخريطة',
            'error_code': 'LOCATION_ANALYSIS_NOT_APPROVED',
        }), 400
    if not overlay_only and map_type in {'landmarks', 'access', 'catchment'} and data.get('overviewApproved') is not True:
        return jsonify({
            'success': False,
            'error': 'يجب اعتماد خريطة الموقع العامة قبل إنشاء هذه الخريطة',
            'error_code': 'OVERVIEW_MAP_NOT_APPROVED',
        }), 400
    if data.get('mapApproved') is True:
        return jsonify({
            'success': False,
            'error': 'يجب إلغاء اعتماد الخريطة قبل إعادة توليدها',
            'error_code': 'MAP_ALREADY_APPROVED',
        }), 400
    presentation_id = data.get('presentationId')
    draft_id = project_data.get('draftId') or project_data.get('draft_id')
    effective_id = presentation_id or (f'draft_{draft_id}' if draft_id else None)
    if not effective_id:
        return jsonify({'success': False, 'error': 'معرّف العرض أو المسودة مطلوب'}), 400
    highlight_site = data.get('highlightSite', True) is not False
    if data.get('overlayOnly') is True and map_type == 'overview':
        result = maps_service.recompose_overview_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
            highlight_site=highlight_site,
        )
    elif data.get('overlayOnly') is True and map_type == 'access':
        result = maps_service.recompose_access_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    elif data.get('overlayOnly') is True and map_type == 'catchment':
        result = maps_service.recompose_catchment_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    elif data.get('overlayOnly') is True and map_type == 'landmarks':
        result = maps_service.recompose_landmarks_map(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
        )
    else:
        image_types = [map_type, f'{map_type}_satellite', f'{map_type}_roadmap']
        if map_type in {'overview', 'access', 'catchment', 'landmarks'}:
            image_types.extend([
                f'{map_type}_editable', f'{map_type}_satellite_editable', f'{map_type}_roadmap_editable'
            ])
        for image_type in image_types:
            db.delete_map_images(g.tenant_id, presentation_id=effective_id, image_type=image_type)
        project_data['enabled_maps'] = [map_type]
        project_data['refresh_maps'] = True
        if data.get('regenSeed') is not None:
            project_data['regen_seed'] = data.get('regenSeed')
        branding = db.get_branding(g.tenant_id) or {}
        result = maps_service.generate_all_map_images(
            project_data,
            g.tenant_id,
            presentation_id=presentation_id,
            draft_id=draft_id,
            force=False,
            branding=branding,
            highlight_site=highlight_site,
            usage_flow=map_type,
        )
    if result.get('error'):
        return jsonify({'success': False, 'error': result['error']}), 400
    placeholders = {}
    for placeholder, path in result.get('placeholders', {}).items():
        if path and os.path.exists(path):
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            placeholders[placeholder] = '/' + rel_path
    map_labels = {'overview': 'الموقع العام', 'access': 'الوصول', 'catchment': 'نطاق الخدمة', 'landmarks': 'المعالم'}
    if presentation_id:
        _record_change('presentation', presentation_id, 'توليد خريطة',
                       [f'وُلّدت خريطة {map_labels.get(map_type, map_type)}'])
    elif draft_id:
        _record_change('draft', draft_id, 'توليد خريطة',
                       [f'وُلّدت خريطة {map_labels.get(map_type, map_type)}'])
    return jsonify({
        'success': True,
        'mapType': map_type,
        'placeholders': placeholders,
        'landmarks': result.get('landmarks', []),
        'landmarks_matrix': result.get('landmarks_matrix', []),
        'zooms': result.get('zooms', {}),
        'centers': result.get('centers', {}),
        'sitePolygon': result.get('site_polygon', []),
        'accessRoads': result.get('access_roads', []),
        'catchmentLandmarks': result.get('catchment_landmarks', []),
        'landmarkMapItems': result.get('landmark_map_items', []),
    })


@app.route('/api/generate-map-images', methods=['POST'])
@require_auth
def api_generate_map_images():
    """Reject the retired bulk path so maps can only be generated individually."""
    return jsonify({
        'success': False,
        'error': 'توليد الخرائط متاح لكل خريطة على حدة',
        'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
    }), 400


@app.route('/api/presentations/<pres_id>/regenerate-maps', methods=['POST'])
@require_permission('create_presentation')
def api_regenerate_presentation_maps(pres_id):
    """Reject the retired saved-presentation bulk regeneration path."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404

    return jsonify({
        'success': False,
        'error': 'إعادة توليد الخرائط متاحة لكل خريطة على حدة',
        'error_code': 'INDIVIDUAL_MAP_GENERATION_REQUIRED',
    }), 400


def _generation_map_marker_side(images, project_data, view='overview'):
    images = images if isinstance(images, dict) else {}
    project_data = project_data if isinstance(project_data, dict) else {}
    centers = images.get('map_centers') if isinstance(images.get('map_centers'), dict) else {}
    center = centers.get(view) if isinstance(centers.get(view), dict) else {}
    try:
        marker_lng = float(images.get('map_lng') or project_data.get('location_lng'))
        center_lng = float(center.get('lng'))
    except (TypeError, ValueError):
        return 'right'
    return 'left' if marker_lng < center_lng else 'right'


@app.route('/api/generate-slide-single', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slide_single():
    """Generate a single slide by index. Returns one slide HTML."""
    from slide_engine import generate_single_slide, build_design_rules, finalize_slide_html
    data = request.json or {}
    project_data = clean_project_data(data.get('projectData', {}))
    presentation_id = str(data.get('presentationId') or '').strip() or None
    project_data, request_images = _hydrate_map_assets_for_request(
        project_data, data.get('images', {}), g.tenant_id, presentation_id=presentation_id
    )
    slide_plan = data.get('slidePlan', {})
    images = _augment_generation_images(request_images, project_data, g.tenant_id)
    slide_index = int(data.get('slideIndex', 0))

    if not slide_plan or 'slides' not in slide_plan:
        return jsonify({'error': 'slidePlan with slides array is required'}), 400

    slides = slide_plan.get('slides', [])
    # The client may send just the single slide needed (slideIndex always 0)
    # together with a _totalSlides field for the real deck size and a _slideNum
    # field for this slide's real one-based position in that deck. Numbering,
    # cover/closing detection and header/footer all follow _slideNum: using the
    # snapshot index (always 1) mistook every slide for the cover and stripped
    # its chrome without re-adding it.
    _total_slides_override = data.get('_totalSlides')
    total_slides = int(_total_slides_override) if isinstance(_total_slides_override, (int, float)) and _total_slides_override > 0 else len(slides)
    if slide_index < 0 or slide_index >= len(slides):
        return jsonify({'error': 'Invalid slide index'}), 400
    try:
        slide_num = int(data.get('_slideNum') or 0)
    except (TypeError, ValueError):
        slide_num = 0
    if slide_num < 1 or slide_num > total_slides:
        slide_num = slide_index + 1

    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400
    _prepare_generation_logo_context(project_data, branding, g.tenant_id)
    project_data['_map_marker_side'] = _generation_map_marker_side(images, project_data)

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

    images_info = _get_images_info(images, project_data)
    training_context = db.get_training_context(g.tenant_id)

    design_rules = build_design_rules(branding)
    # Every collected fact, grouped by section. This used to be the raw draft cut at 4,000
    # characters, which silently dropped the market study, the executive content and the team.
    project_json = slide_engine.build_project_facts(project_data, g.tenant_id)

    landmarks_matrix = project_data.get('nearby_landmarks_data') or project_data.get('landmarks_matrix')
    landmarks_note = ''
    if landmarks_matrix:
        landmarks_note = (
            " إرشادات هامة لعرض المعالم:\n"
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
- للخرائط: ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT## — استخدمها في شرائح تحليل الموقع الجغرافي أو تحليل الأرض عند طلبها صراحة أو ملخص الموقع المحدد صراحة، وممنوع استخدامها في الجدول الزمني أو الدراسة المالية أو المخططات أو التصورات الخارجية أو الداخلية أو أي قسم آخر
-  ممنوع base64 أو روابط صور خارجية
- {slide_engine.NO_STREET_VIEW_RULE}
"""

    def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
        if training_context:
            sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
        return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2, model=SLIDE_TEXT_MODEL, usage_ctx=_usage_ctx('slide', data, presentation_id=presentation_id))

    # Apply the same ownership repair used by the full-plan normalizer before
    # rendering and before returning slide metadata. A single-slide retry can
    # arrive from an older saved plan that misclassified a map or financial
    # slide, so finalization must see the repaired type/source too.
    slide = slide_engine._normalize_legacy_single_slide(
        dict(slides[slide_index] or {}), project_data
    )
    total = total_slides
    html = generate_single_slide(system_prompt, slide, slide_num, total, branding, call_glm_fn, max_retries=3, project_data=project_data)

    # Never turn a failed generation into a fake successful slide. The client
    # can retry the request, but it must not save an incomplete presentation.
    if len(extract_slide_elements(html or '')) != 1:
        title = slide.get('title', f'شريحة {slide_num}')
        return jsonify({
            'success': False,
            'error': f'تعذر توليد الشريحة {slide_num}: {title}',
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
        slide_num=slide_num,
        slide_title=slide.get('title', f'شريحة {slide_num}'),
        total_slides=total,
        content_source=slide.get('content_source'),
    )

    return jsonify({
        'success': True,
        'slide': {
            'html': html,
            'title': slide.get('title', f'شريحة {slide_num}'),
            'type': slide.get('type', 'content'),
            'sectionKey': slide.get('section_key', ''),
            'contentSource': slide.get('content_source', ''),
            'sourceTable': slide.get('source_table', ''),
            'indexEntries': slide.get('index_entries', []),
            'designStyle': slide.get('design_style', 'cards'),
        },
        'slideIndex': slide_index,
        'totalSlides': total,
    })


def _run_slide_generation_job(flask_app, tenant_id, payload, job_id, authorization):
    """Run one slide request outside the hosting proxy's request lifetime."""
    with flask_app.test_request_context(
            '/api/generate-slide-single', method='POST', json=payload,
            headers={'Authorization': authorization}):
        try:
            result = api_generate_slide_single()
            response = result[0] if isinstance(result, tuple) else result
            status_code = result[1] if isinstance(result, tuple) and len(result) > 1 else response.status_code
            body = response.get_json(silent=True) or {}
            if 200 <= int(status_code) < 300 and body.get('success'):
                _write_job('.slide_jobs', tenant_id, job_id, {
                    **body, 'status': 'completed', 'success': True,
                })
            else:
                _write_job('.slide_jobs', tenant_id, job_id, {
                    **body,
                    'status': 'failed',
                    'success': False,
                    'error': body.get('error') or f'فشل توليد الشريحة (HTTP {status_code})',
                })
        except Exception as exc:
            print(f'[SLIDE GENERATION JOB FAILED] {exc}')
            _write_job('.slide_jobs', tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'error': f'تعذر توليد الشريحة: {exc}',
                'failureReason': 'job_failed',
            })


@app.route('/api/generate-slide-single-job', methods=['POST'])
@require_permission('create_presentation')
def api_generate_slide_single_job():
    """Queue one slide so a slow AI response cannot become a proxy 404."""
    data = request.json or {}
    slide_plan = data.get('slidePlan') or {}
    slides = slide_plan.get('slides') if isinstance(slide_plan, dict) else None
    if not isinstance(slides, list) or not slides:
        return jsonify({'success': False, 'error': 'slidePlan with slides array is required'}), 400
    job_id = str(_uuid.uuid4())
    tenant_id = g.tenant_id
    authorization = request.headers.get('Authorization', '')
    _write_job('.slide_jobs', tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'message': 'تم استلام طلب توليد الشريحة',
    })
    threading.Thread(
        target=_run_slide_generation_job,
        args=(current_app._get_current_object(), tenant_id, data, job_id, authorization),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'message': 'بدأ توليد الشريحة في الخلفية',
    }), 202


@app.route('/api/generate-slide-single/jobs/<job_id>', methods=['GET'])
@require_permission('create_presentation')
def api_generate_slide_single_job_status(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_job('.slide_jobs', g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'status': 'not_found',
            'error': 'المهمة غير موجودة أو انتهت صلاحيتها',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(job)


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
    presentation_id = str(data.get('presentationId') or '').strip() or None
    project_data, request_images = _hydrate_map_assets_for_request(
        project_data, data.get('images', {}), g.tenant_id, presentation_id=presentation_id
    )
    images = _augment_generation_images(request_images, project_data, g.tenant_id)

    branding = db.get_branding(g.tenant_id)
    if not branding:
        return jsonify({'error': 'Branding not configured'}), 400

    if not slide_plan or 'slides' not in slide_plan:
        return jsonify({'error': 'slidePlan with slides array is required'}), 400
    slide_plan = slide_engine.normalize_market_section_plan(slide_plan, project_data) or slide_plan
    _prepare_generation_logo_context(project_data, branding, g.tenant_id)
    project_data['_map_marker_side'] = _generation_map_marker_side(images, project_data)

    # Map generation is explicit. Reuse only placeholders already supplied by the
    # caller or persisted by a previous, user-triggered map generation.
    map_placeholders = {}
    if isinstance(images, dict):
        supplied_placeholders = images.get('map_placeholders')
        if isinstance(supplied_placeholders, dict):
            map_placeholders = {key: value for key, value in supplied_placeholders.items() if value}
    elif isinstance(images, list):
        images = {'cover': images[0] if images else None, 'moodboard': []}

    images_info = _get_images_info(images, project_data)

    training_context = db.get_training_context(g.tenant_id)

    # Define the GLM call function for the slide engine
    def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
        if training_context:
            sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
        return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2, model=SLIDE_TEXT_MODEL, usage_ctx=_usage_ctx('slide', data, presentation_id=presentation_id))

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
                'sectionKey': slide_info.get('section_key', ''),
                'contentSource': slide_info.get('content_source', ''),
                'sourceTable': slide_info.get('source_table', ''),
                'indexEntries': slide_info.get('index_entries', []),
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
    map_centers = {}
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
        if image_type in seen_types or placeholder in seen_placeholders:
            continue
        seen_types.add(image_type)
        seen_placeholders.add(placeholder)
        try:
            rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
        except ValueError:
            rel_path = 'uploads/maps/' + os.path.basename(path)
        placeholders[placeholder] = '/' + rel_path

        # The file itself remains a valid persisted map even when a later
        # renderer version changed its overlays or labels.  Keep importing that
        # image so slide generation never produces an empty map frame.  Only
        # trust the attached metadata for marker-aware layout when both versions
        # match the renderer that produced the current map implementation.
        current_map_metadata = (
            metadata.get('map_highlight_version') == maps_service.MAP_HIGHLIGHT_RENDER_VERSION
            and metadata.get('map_label_version') == maps_service.MAP_LABEL_RENDER_VERSION
        )
        if not current_map_metadata:
            continue
        # The map row is the source of truth for the image that was actually
        # approved.  Project JSON can lag behind it when a user edits a map and
        # immediately starts presentation generation, so do not let stale JSON
        # metadata survive a hydration pass.
        if metadata.get('lat') is not None:
            creative['map_lat'] = metadata['lat']
        if metadata.get('lng') is not None:
            creative['map_lng'] = metadata['lng']
        if metadata.get('zoom') is not None:
            base_type = image_type
            for suffix in ('_editable', '_satellite', '_roadmap'):
                if base_type.endswith(suffix):
                    base_type = base_type[:-len(suffix)]
            map_zooms.setdefault(base_type, metadata['zoom'])
        if metadata.get('center_lat') is not None and metadata.get('center_lng') is not None:
            base_type = image_type
            for suffix in ('_editable', '_satellite', '_roadmap'):
                if base_type.endswith(suffix):
                    base_type = base_type[:-len(suffix)]
            if base_type in {'overview', 'access', 'catchment', 'landmarks'}:
                map_centers.setdefault(base_type, {
                    'lat': metadata['center_lat'], 'lng': metadata['center_lng']
                })
        if 'landmarks_matrix' in metadata:
            creative['map_landmarks'] = metadata['landmarks_matrix']
        if 'access_roads' in metadata:
            project_data['access_roads_data'] = metadata['access_roads']
            creative['map_access_roads'] = metadata['access_roads']
        if 'catchment_landmarks' in metadata:
            project_data['catchment_map_landmarks'] = metadata['catchment_landmarks']
            creative['map_catchment_landmarks'] = metadata['catchment_landmarks']
        if 'landmark_map_items' in metadata:
            project_data['landmark_map_items'] = metadata['landmark_map_items']
            creative['map_landmark_items'] = metadata['landmark_map_items']
        if metadata.get('highlight_site') is not None:
            map_highlight_site = bool(metadata.get('highlight_site'))
    existing_placeholders = creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {}
    merged_placeholders = {key: value for key, value in existing_placeholders.items() if key and value}
    merged_placeholders.update(placeholders)
    creative['map_placeholders'] = merged_placeholders
    creative['maps_persisted'] = bool(merged_placeholders)
    if map_highlight_site is not None:
        creative['map_highlight_site'] = map_highlight_site
    if map_zooms:
        creative['map_zooms'] = map_zooms
    if map_centers:
        creative['map_centers'] = map_centers
    project_data['tenantCreativeImages'] = creative
    return project_data


def _hydrate_map_assets_for_request(project_data, images, tenant_id, presentation_id=None):
    """Restore saved map URLs before a slide, plan, or designer request runs.

    Map files are persisted separately from the presentation JSON.  A request may
    therefore have a perfectly valid presentation id but an incomplete client
    ``creativeImages`` object, especially after reopening an older draft.  Merge
    the DB-backed assets first, then use request values only as a fallback when
    no persisted map file exists for that placeholder.
    """
    source = project_data if isinstance(project_data, dict) else {}
    request_images = dict(images) if isinstance(images, dict) else {}
    draft_id = source.get('draftId') or source.get('draft_id')
    persisted_records = []
    if presentation_id or draft_id:
        source = _merge_persisted_map_assets(
            source, tenant_id, presentation_id=presentation_id, draft_id=draft_id
        )
        persisted_records = db.get_map_images(
            tenant_id, presentation_id=presentation_id, draft_id=draft_id
        )

    creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
    placeholder_sources = (
        creative.get('map_placeholders') if isinstance(creative.get('map_placeholders'), dict) else {},
        source.get('map_placeholders') if isinstance(source.get('map_placeholders'), dict) else {},
        request_images.get('map_placeholders') if isinstance(request_images.get('map_placeholders'), dict) else {},
    )
    # The persisted rows are the fallback for reopened presentations.  Keep only
    # the newest valid row for each image type/placeholder; without this guard an
    # older duplicate row could be visited later and overwrite the current map.
    placeholders = {}
    for values in placeholder_sources:
        placeholders.update({key: value for key, value in values.items() if key and value})
    persisted_file_records = []
    seen_persisted_types = set()
    seen_persisted_placeholders = set()
    for record in persisted_records:
        placeholder = record.get('placeholder')
        path = record.get('file_path')
        if placeholder and path and os.path.exists(path):
            image_type = record.get('image_type') or ''
            if image_type in seen_persisted_types or placeholder in seen_persisted_placeholders:
                continue
            try:
                rel_path = os.path.relpath(path, os.path.dirname(__file__)).replace('\\', '/')
            except ValueError:
                rel_path = 'uploads/maps/' + os.path.basename(path)
            seen_persisted_types.add(image_type)
            seen_persisted_placeholders.add(placeholder)
            persisted_file_records.append(record)
            placeholders[placeholder] = '/' + rel_path

    # During the same browser session, a map can be edited and approved after an
    # older Google row was stored.  The request carries that approved state and
    # its current URL, so it is authoritative for that map.  On a reopened
    # presentation maps_persisted/approvals come from the persisted project state
    # and agree with the DB row, preserving DB hydration as the fallback.
    requested_placeholders = request_images.get('map_placeholders')
    if isinstance(requested_placeholders, dict):
        for placeholder, path in requested_placeholders.items():
            if not path or not _request_map_is_approved(request_images, placeholder):
                continue
            # The browser may already have received the generation-only alias
            # below, where an editable sidecar points at the marked canonical
            # image.  Never let that alias overwrite the clean sidecar in the
            # project copy: the location editor renders its own labels over it.
            if placeholder.endswith('_EDITABLE##'):
                canonical = placeholder.replace('_EDITABLE##', '##')
                requested_canonical = requested_placeholders.get(canonical)
                if requested_canonical and str(path) == str(requested_canonical):
                    continue
            placeholders[placeholder] = path

    if placeholders and isinstance(source, dict):
        creative = source.get('tenantCreativeImages') if isinstance(source.get('tenantCreativeImages'), dict) else {}
        creative['map_placeholders'] = dict(placeholders)
        source['tenantCreativeImages'] = creative
    # Older plans or an over-helpful model may ask for the editable sidecar token.
    # A generated presentation must always receive the approved, marked image;
    # the sidecar is only for the interactive map editor. Keep this alias in the
    # request copy only; the project/browser copy above must retain the clean file.
    generation_placeholders = dict(placeholders)
    for placeholder, path in list(generation_placeholders.items()):
        if not placeholder.endswith('_EDITABLE##'):
            continue
        canonical = placeholder.replace('_EDITABLE##', '##')
        if generation_placeholders.get(canonical):
            generation_placeholders[placeholder] = generation_placeholders[canonical]
    if generation_placeholders:
        request_images['map_placeholders'] = generation_placeholders

    # These values keep marker-aware layout and location summaries consistent with
    # the exact map image that was persisted for the open presentation.
    for key in (
        'map_zooms', 'map_centers', 'map_landmarks', 'map_access_roads',
        'map_catchment_landmarks', 'map_landmark_items', 'map_highlight_site',
        'map_lat', 'map_lng', 'maps_persisted', 'map_approvals',
    ):
        if persisted_file_records and key in creative:
            request_images[key] = creative[key]
        elif key not in request_images and key in creative:
            request_images[key] = creative[key]
    return source, request_images


def _map_approval_key(value):
    """Return the logical map name for a canonical or editable placeholder."""
    key = str(value or '').strip()
    key = key.replace('##MAP_', '').replace('_EDITABLE##', '').replace('##', '')
    for suffix in ('_SATELLITE', '_ROADMAP'):
        if key.endswith(suffix):
            key = key[:-len(suffix)]
    return key.lower()


def _request_map_is_approved(request_images, placeholder):
    """Whether the caller is sending its current, user-approved map version."""
    if not isinstance(request_images, dict) or request_images.get('maps_persisted') is not True:
        return False
    approvals = request_images.get('map_approvals')
    if not isinstance(approvals, dict):
        return False
    value = approvals.get(_map_approval_key(placeholder))
    return value is True or (isinstance(value, str) and value.strip().lower() in {'true', '1', 'yes'})


@app.route('/api/presentations', methods=['GET'])
@require_permission('view_presentations')
def api_get_presentations():
    """List tenant presentations with optional project and archive filters."""
    try:
        limit = int(request.args.get('limit', 200))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit and offset must be integers'}), 400
    presentations = db.get_presentations(
        g.tenant_id,
        draft_id=(request.args.get('draftId') or '').strip() or None,
        search=(request.args.get('search') or '').strip(),
        status=(request.args.get('status') or '').strip(),
        date_from=(request.args.get('from') or '').strip(),
        date_to=(request.args.get('to') or '').strip(),
        limit=limit,
        offset=offset,
    )
    result = []
    for p in presentations:
        draft_id = p.get('draft_id')
        if not draft_id and p.get('project_data'):
            try:
                project_data = json.loads(p['project_data']) if isinstance(p['project_data'], str) else p['project_data']
            except (TypeError, ValueError):
                project_data = {}
            if isinstance(project_data, dict):
                draft_id = project_data.get('draftId') or project_data.get('draft_id')
        result.append({
            'id': p['id'],
            'title': p['title'],
            'draftId': draft_id,
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
    presentation = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not presentation:
        return jsonify({'error': 'Presentation not found'}), 404
    _record_change('presentation', pres_id, 'حذف العرض',
                   [f'حُذف العرض «{presentation.get("title") or "بدون عنوان"}»'])
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
    branding = db.get_branding(g.tenant_id) or {}
    render_project_data = copy.deepcopy(project_data)
    _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)
    slides_data = slide_engine.renumber_presentation_slides(
        slides_data, branding=branding, project_data=render_project_data,
        tenant_id=g.tenant_id,
        creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
    )
    slide_count = len(slides_data)

    pres_id = db.create_presentation(
        tenant_id=g.tenant_id,
        title=title,
        project_data=project_data,
        slides_data=slides_data,
        slide_count=slide_count,
        draft_id=project_data.get('draftId') or project_data.get('draft_id'),
    )
    _record_change('presentation', pres_id, 'إنشاء العرض',
                   [f'العنوان: «{title}»', f'عدد الشرائح: {slide_count}'])
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
    render_project_data = copy.deepcopy(pres['projectData'])
    _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)
    slides = slide_engine.renumber_presentation_slides(
        slides, branding=branding, project_data=render_project_data, tenant_id=g.tenant_id,
        creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
    )
    project_logo_ref = slide_engine._project_logo_reference(render_project_data)
    for s in slides:
        if isinstance(s, dict) and 'html' in s and isinstance(s['html'], str):
            # Resolve through the engine copy: it fixes ##LOGO## tokens and broken
            # logo paths exactly like the legacy pass, but never appends the 50px
            # logo sizing over an explicit height. The legacy pass matched the
            # watermark overlay img (its src carries tenant-assets) and appended
            # max-height:50px;width:auto, collapsing width:480px to a ~50px mark
            # on every open/refresh — and the next save persisted the shrink.
            s['html'] = slide_engine.resolve_logo_in_html(
                s['html'], g.tenant_id, _branding_cache=branding,
                project_logo=project_logo_ref,
            )
    pres['slide_count'] = len(slides)
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
    if isinstance(updates.get('project_data'), dict):
        updates['draft_id'] = (updates['project_data'].get('draftId')
                               or updates['project_data'].get('draft_id') or pres.get('draft_id'))

    if 'slides_data' in updates:
        project_data = updates.get('project_data')
        if not isinstance(project_data, dict):
            try:
                project_data = json.loads(pres.get('project_data') or '{}')
            except (TypeError, ValueError):
                project_data = {}
        update_branding = db.get_branding(g.tenant_id) or {}
        render_project_data = copy.deepcopy(project_data)
        _prepare_generation_logo_context(render_project_data, update_branding, g.tenant_id)
        updates['slides_data'] = slide_engine.renumber_presentation_slides(
            updates['slides_data'], branding=update_branding,
            project_data=render_project_data, tenant_id=g.tenant_id,
            creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
        )
        updates['slide_count'] = len(updates['slides_data'])

    details = []
    action = 'تعديل العرض'
    if 'title' in updates and updates['title'] != pres.get('title'):
        details.append(f'عنوان العرض: من «{pres.get("title") or "بدون"}» إلى «{updates["title"]}»')
    if 'project_data' in updates:
        try:
            old_project_data = json.loads(pres.get('project_data') or '{}')
        except (TypeError, ValueError):
            old_project_data = {}
        details.extend(change_tracking.describe_draft_changes(old_project_data, updates['project_data']))
    if 'slides_data' in updates:
        current_slides = change_tracking.parse_slides(pres.get('slides_data'))
        db.save_presentation_version(pres_id, g.user_id, g.user_name or 'System', current_slides, action='edit')
        details.extend(change_tracking.describe_slide_changes(current_slides, updates['slides_data']))
        action = 'تعديل الشرائح'
    if 'status' in updates and updates['status'] != pres.get('status'):
        details.append(f'حالة العرض: من «{pres.get("status") or "مسودة"}» إلى «{updates["status"]}»')
    if details:
        _record_change('presentation', pres_id, action, details, source='manual')

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


def _resolve_draft_id(explicit=None):
    """The draft a request acts on: the id it names, else this actor's current draft."""
    if explicit:
        return explicit
    draft = db.get_project_draft(g.tenant_id, _project_draft_actor_id())
    return (draft or {}).get('id')

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
    # A request that carries no payload used to store "{}" over the draft and answer success, so a
    # single mangled or half-initialised save emptied the project with nothing to show why.
    if not draft_data:
        app.logger.warning(
            '[DRAFT SAVE] Refused a save with no draftData: tenant=%s actor=%s keys=%s',
            g.tenant_id, _project_draft_actor_id(), sorted(data.keys())[:20]
        )
        return jsonify({'error': 'لم يتم الحفظ: لم تصل بيانات المشروع إلى الخادم'}), 400
    # Absence or {} means preserve already-reviewed sections (legacy clients send {}).
    section_statuses = data.get('sectionStatuses')
    if section_statuses is not None and not isinstance(section_statuses, dict):
        return jsonify({'error': 'sectionStatuses must be an object'}), 400
    status = data.get('status', 'draft')
    if status not in {'draft', 'submitted'}:
        status = 'draft'
    # Read the stored version before writing over it, so the history can name every field that
    # changed instead of only counting a revision.
    previous_id = draft_data.get('draftId') or draft_data.get('draft_id')
    previous = db.get_project_draft_by_id(g.tenant_id, previous_id) if previous_id else None
    previous_data = (previous or {}).get('draft_data') if isinstance(previous, dict) else {}
    previous_statuses = (previous or {}).get('section_statuses') if isinstance(previous, dict) else {}
    try:
        draft_id = db.save_project_draft(
            g.tenant_id, _project_draft_actor_id(), draft_data, section_statuses, status,
            draft_id=draft_data.get('draftId') or draft_data.get('draft_id')
        )
    except db.DraftOverwriteRefused as refused:
        app.logger.warning(
            '[DRAFT SAVE] Refused to empty draft %s: tenant=%s actor=%s stored=%d fields received=%s',
            refused.draft_id, g.tenant_id, _project_draft_actor_id(),
            len(refused.stored_keys), refused.incoming_keys[:20]
        )
        return jsonify({
            'error': 'لم يتم الحفظ: البيانات المرسلة فارغة والمسودة المحفوظة تحتوي بيانات المشروع',
            'error_code': 'DRAFT_EMPTY_OVERWRITE'
        }), 409

    details = change_tracking.describe_draft_changes(previous_data, draft_data)
    if isinstance(section_statuses, dict) and section_statuses:
        details.extend(change_tracking.describe_section_status_changes(previous_statuses, section_statuses))
    _record_change('draft', draft_id, 'حفظ بيانات المشروع' if previous else 'إنشاء ملف مشروع',
                   details, source='manual',
                   summary='' if previous else 'تم إنشاء ملف المشروع')
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
    drafts = db.get_all_project_draft_summaries(
        g.tenant_id, limit=limit, offset=offset,
        search=(request.args.get('search') or '').strip(),
        status=(request.args.get('status') or '').strip(),
        date_from=(request.args.get('from') or '').strip(),
        date_to=(request.args.get('to') or '').strip(),
    )
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


@app.route('/api/project-drafts/recovery', methods=['GET'])
@require_auth
def api_project_draft_recovery():
    """Report which drafts lost their fields and what can be read back into them.

    A save with no readable payload used to overwrite a draft with "{}" and answer success, so
    drafts were emptied silently. Every generated presentation kept a full snapshot of the project
    data of its moment, which is what makes those drafts recoverable.
    """
    snapshots = db.find_draft_snapshots(g.tenant_id)
    by_draft = {}
    for snapshot in snapshots:
        key = snapshot['draft_id']
        if key and (key not in by_draft or snapshot['field_count'] > by_draft[key]['field_count']):
            by_draft[key] = snapshot
    report = []
    for draft in db.get_all_project_draft_summaries(g.tenant_id, limit=200):
        stored = db.get_project_draft_by_id(g.tenant_id, draft['id'])
        field_count = len(db._draft_content_keys((stored or {}).get('draft_data') or {}))
        snapshot = by_draft.get(draft['id'])
        report.append({
            'draftId': draft['id'],
            'title': draft['title'],
            'updatedAt': draft.get('updated_at'),
            'dataBytes': draft.get('data_bytes') or 0,
            'revision': draft.get('revision') or 0,
            'fieldCount': field_count,
            'isEmpty': field_count == 0,
            'snapshot': {
                'presentationId': snapshot['presentation_id'],
                'title': snapshot['title'],
                'createdAt': snapshot['created_at'],
                'slideCount': snapshot['slide_count'],
                'fieldCount': snapshot['field_count'],
                'recoverable': snapshot['field_count'] > field_count,
            } if snapshot else None,
        })
    orphans = [
        {
            'presentationId': snapshot['presentation_id'],
            'title': snapshot['title'],
            'createdAt': snapshot['created_at'],
            'fieldCount': snapshot['field_count'],
        }
        for snapshot in snapshots
        if snapshot['field_count'] > 0 and snapshot['draft_id'] not in {item['draftId'] for item in report}
    ]
    return jsonify({'success': True, 'drafts': report, 'orphanSnapshots': orphans})


@app.route('/api/project-draft/<draft_id>/restore', methods=['POST'])
@require_auth
def api_restore_project_draft(draft_id):
    """Refill a draft's missing fields from a presentation snapshot. Never overwrites."""
    data = request.json or {}
    presentation_id = data.get('presentationId')
    if not isinstance(presentation_id, str) or not presentation_id:
        return jsonify({'error': 'presentationId is required'}), 400
    presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
    if not presentation:
        return jsonify({'error': 'Presentation not found'}), 404
    try:
        snapshot = json.loads(presentation.get('project_data') or '{}')
    except (TypeError, ValueError):
        snapshot = {}
    if not isinstance(snapshot, dict) or not snapshot:
        return jsonify({'error': 'لا توجد بيانات مشروع في هذا العرض'}), 400
    restored = db.restore_draft_from_snapshot(g.tenant_id, draft_id, snapshot)
    if restored is None:
        return jsonify({'error': 'Draft not found'}), 404
    _record_change('draft', draft_id, 'استرجاع بيانات المشروع',
                   [f'استُعيد الحقل «{field}» من العرض «{presentation.get("title") or "بدون عنوان"}»'
                    for field in restored])
    return jsonify({'success': True, 'restoredFields': restored, 'restoredCount': len(restored)})


@app.route('/api/project-draft/<draft_id>', methods=['DELETE'])
@require_auth
def api_delete_project_draft_by_id(draft_id):
    """Delete a specific project draft by ID."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    _record_change('draft', draft_id, 'حذف المشروع',
                   [f'حُذف المشروع «{draft.get("title") or "بدون عنوان"}»'])
    db.delete_project_draft_by_id(g.tenant_id, draft_id)
    return jsonify({'success': True})


def _location_workflow_complete(draft):
    project = (draft or {}).get('draft_data') if isinstance(draft, dict) else {}
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (TypeError, ValueError):
            project = {}
    if not isinstance(project, dict) or project.get('location_analysis_approved') not in (True, 'true', 1):
        return False
    creative = project.get('tenantCreativeImages') if isinstance(project.get('tenantCreativeImages'), dict) else {}
    approvals = creative.get('map_approvals') if isinstance(creative.get('map_approvals'), dict) else {}
    return all(approvals.get(key) is True for key in ('overview', 'access', 'catchment', 'landmarks'))


@app.route('/api/project-draft/section-status', methods=['POST'])
@require_auth
def api_update_section_status():
    """Update one section's status, or several in a single atomic merge."""
    data = request.json or {}
    bulk = data.get('sectionStatuses')
    if isinstance(bulk, dict) and bulk:
        # Approving every section used to fire one request per section in parallel, and the
        # concurrent read-modify-write on the shared JSON column lost half of them.
        if any(not isinstance(key, str) or not key or value not in {'draft', 'approved'} for key, value in bulk.items()):
            return jsonify({'error': 'A valid sectionStatuses map is required'}), 400
        draft_id = _resolve_draft_id(data.get('draftId'))
        before = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
        if bulk.get('location') == 'approved' and not _location_workflow_complete(before):
            return jsonify({'error': 'Location analysis and all four maps must be approved first',
                            'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
        result = db.update_draft_section_statuses(
            g.tenant_id, _project_draft_actor_id(), bulk, draft_id=data.get('draftId')
        )
        if not result:
            return jsonify({'error': 'Unable to update section status'}), 400
        _record_change('draft', draft_id or _resolve_draft_id(), 'اعتماد الأقسام',
                       change_tracking.describe_section_status_changes(
                           (before or {}).get('section_statuses') if isinstance(before, dict) else {}, bulk))
        return jsonify({'success': True})
    section_key = data.get('sectionKey')
    section_status = data.get('sectionStatus')
    if not isinstance(section_key, str) or not section_key or section_status not in {'draft', 'approved'}:
        return jsonify({'error': 'A valid sectionKey and sectionStatus are required'}), 400
    draft_id = _resolve_draft_id(data.get('draftId'))
    before = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
    if section_key == 'location' and section_status == 'approved' and not _location_workflow_complete(before):
        return jsonify({'error': 'Location analysis and all four maps must be approved first',
                        'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
    result = db.update_draft_section_status(
        g.tenant_id, _project_draft_actor_id(), section_key, section_status, draft_id=data.get('draftId')
    )
    if not result:
        return jsonify({'error': 'Unable to update section status'}), 400
    _record_change('draft', draft_id or _resolve_draft_id(), 'اعتماد قسم',
                   change_tracking.describe_section_status_changes(
                       (before or {}).get('section_statuses') if isinstance(before, dict) else {},
                       {section_key: section_status}))
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
    _record_change('draft', draft.get('id') or data.get('draftId'), 'طلب تعميد المشروع',
                   ['أُرسل المشروع للمراجعة'])
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
    action = 'اعتماد المشروع' if review_status == 'approved' else 'إعادة المشروع للتعديل'
    _record_change('draft', draft_id, action, [note] if note else [action])
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


_FINANCIAL_NUMERIC_CELL = re.compile(r'^[\s\-+()0-9.,%٠-٩٬٫]+$')


def _financial_report_cell(rendered, value=None):
    """A figure is an LTR run, so it needs an LTR cell.

    In an RTL cell the bidi algorithm has no strong direction to attach the leading sign to and
    gives it the paragraph direction, so `-13,125,000` printed as `13,125,000-`.
    """
    text = str(value if value is not None else rendered).strip()
    if text and any(char.isdigit() for char in text) and _FINANCIAL_NUMERIC_CELL.match(text):
        return f'<td dir="ltr">{rendered}</td>'
    return f'<td>{rendered}</td>'


_FINANCIAL_PERCENT_KEYS = {
    'coverageRate', 'occupancy', 'costPct', 'devPct', 'drawPct', 'repaymentPct',
    'growth', 'occupancyReach', 'reachPct', 'financingRate', 'annualFinanceRate',
    'developerRate', 'financeArrangementFeeRate', 'fundManagementRate',
    'operatingExitCostRate', 'developerUpliftShare', 'roi', 'projectIrr', 'equityIrr',
}
_FINANCIAL_YEAR_KEYS = {
    'year', 'startYear', 'endYear', 'studyYear', 'operationYear', 'developmentYears',
    'operationYears', 'salesStartYear', 'salesYears', 'landContributionYear',
    'financeDrawYears', 'financeRepaymentStartYear', 'financeRepaymentYears',
    'fundFeeStartYear', 'fundFeeEndYear', 'performanceCrystallizationYear',
    'saleExitYear', 'operatingExitYear',
}


def _financial_report_plain_number(value):
    if isinstance(value, bool) or value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text == '—':
        return None
    cleaned = text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٬،', '0123456789,,'))
    cleaned = cleaned.replace('%', '').replace('سنة', '').replace('م²', '').replace(' ', '')
    cleaned = cleaned.replace('(', '-').replace(')', '')
    cleaned = cleaned.replace('٫', '.')
    cleaned = cleaned.replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _financial_rounded_text(value, grouped=True):
    try:
        rounded = Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return ''
    if rounded == rounded.to_integral_value():
        return f'{int(rounded):,}' if grouped else str(int(rounded))
    return f'{rounded:,.1f}' if grouped else f'{rounded:.1f}'


def _financial_report_format_number(value, key=''):
    number = _financial_report_plain_number(value)
    if number is None:
        return _financial_report_escape(value)
    field = str(key or '')
    if field in _FINANCIAL_PERCENT_KEYS or (isinstance(value, str) and '%' in str(value)):
        if field in {'roi', 'projectIrr', 'equityIrr', 'irr'} and isinstance(value, (int, float)):
            display = number * 100
        elif field in {'occupancyReach'} and abs(number) <= 1:
            display = number * 100
        else:
            display = number
        return html_lib.escape(_financial_rounded_text(display, grouped=False) + '%')
    if field in {'payback', 'equityPayback'} or (isinstance(value, str) and 'سنة' in str(value)):
        return html_lib.escape(_financial_rounded_text(number, grouped=False) + ' سنة')
    if field in _FINANCIAL_YEAR_KEYS and float(number).is_integer() and abs(number) < 10000:
        return html_lib.escape(str(int(number)))
    return html_lib.escape(_financial_rounded_text(number))


_FINANCIAL_DISPLAY_VALUE_RE = re.compile(
    r'^\s*(?P<open>\()?\s*(?P<number>[-+]?(?:[0-9٠-٩]+(?:[٬،,][0-9٠-٩]{3})*|[0-9٠-٩]+)(?:[٫.][0-9٠-٩]+)?)'
    r'\s*(?P<close>\))?\s*(?P<suffix>%|٪|سنة|سنوات|م²|م2|ر\.?\s?س|ريال(?:\s+سعودي)?)?\s*$'
)
_FINANCIAL_PERCENT_CONTEXT_RE = re.compile(r'%|نسبة|معدل|إشغال|ROI|IRR', re.IGNORECASE)
_FINANCIAL_YEAR_CONTEXT_RE = re.compile(r'سنة|سنوات|عام|year', re.IGNORECASE)
_FINANCIAL_LITERAL_CONTEXT_RE = re.compile(
    r'تاريخ|هاتف|جوال|وثيقة|معرف|رقم|date|phone|mobile|document|identifier|\bid\b', re.IGNORECASE
)
_FINANCIAL_AMOUNT_CONTEXT_RE = re.compile(
    r'إجمالي|تكلفة|قيمة|مساحة|سعر|إيراد|مصروف|كمية|مبلغ|تدفق|رصيد|حقوق|أتعاب|'
    r'أصل|دين|سيولة|استثمار|دخل|NOI|total|amount|cost|price|revenue|area|cash|balance', re.IGNORECASE
)
_FINANCIAL_GROUP_CONTEXT_RE = re.compile(
    r'إجمالي|تكلفة|قيمة|مساحة|سعر|إيراد|مصروف|تمويل|كمية|مبلغ|تدفق|رصيد|حقوق|أتعاب|'
    r'أصل|دين|سيولة|استثمار|دخل|NOI|total|amount|cost|price|revenue|area|cash|balance', re.IGNORECASE
)
_FINANCIAL_NUMBER_TOKEN_RE = re.compile(
    r'(?<![0-9٠-٩])[-+]?(?:[0-9٠-٩]+(?:[٬،,][0-9٠-٩]{3})*)(?:[٫.][0-9٠-٩]+)?(?![0-9٠-٩])'
)


def _financial_report_format_display(value, context=''):
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return _financial_report_escape(value)
    text = str(value).strip()
    context_text = str(context or '')
    if _FINANCIAL_LITERAL_CONTEXT_RE.search(context_text):
        return _financial_report_escape(value)
    match = _FINANCIAL_DISPLAY_VALUE_RE.fullmatch(text)
    if match:
        number = _financial_report_plain_number(text)
        if number is None:
            return _financial_report_escape(value)
        suffix = match.group('suffix') or ''
        amount = bool(_FINANCIAL_AMOUNT_CONTEXT_RE.search(context_text))
        percent = bool(suffix in {'%', '٪'} or (not amount and _FINANCIAL_PERCENT_CONTEXT_RE.search(context_text)))
        year = bool(suffix in {'سنة', 'سنوات'} or (not amount and _FINANCIAL_YEAR_CONTEXT_RE.search(context_text)))
        formatted = _financial_rounded_text(number, grouped=not (percent or year))
        if match.group('open') and match.group('close'):
            formatted = f'({formatted.lstrip("-")})'
        if suffix:
            formatted += (' ' if suffix not in {'%', '٪'} else '') + suffix
        return html_lib.escape(formatted)
    if not (_FINANCIAL_GROUP_CONTEXT_RE.search(context_text)
            or re.search(r'م²|م2|ر\.?\s?س|ريال(?:\s+سعودي)?|SAR', text, re.IGNORECASE)):
        return _financial_report_escape(value)

    def format_token(token_match):
        raw = token_match.group(0)
        number = _financial_report_plain_number(raw)
        if number is None:
            return raw
        if 1900 <= abs(number) <= 2100 and _FINANCIAL_YEAR_CONTEXT_RE.search(context_text):
            return raw
        trailing = text[token_match.end():].lstrip()
        return _financial_rounded_text(number, grouped=not trailing.startswith(('%', '٪')))

    return html_lib.escape(_FINANCIAL_NUMBER_TOKEN_RE.sub(format_token, text))


# Section 12 is a results summary with curated metrics. English acronyms (ROI, Project IRR, Equity IRR, NOI)
# are preserved directly per business domain standards.
FINANCIAL_RESULT_LABELS = (
    ('projectCost', 'إجمالي تكلفة المشروع'),
    ('projectCostWithFinance', 'التكلفة شاملة التمويل'),
    ('adjustedProjectCost', 'إجمالي تكلفة الاستثمار'),
    ('developerCost', 'أتعاب المطور'),
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
)


def _filter_financial_results(inputs, projection):
    inputs = inputs if isinstance(inputs, dict) else {}
    projection = projection if isinstance(projection, dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    sales_on = mode in {'sale', 'mixed'}
    rental_on = mode in {'rental', 'mixed'}
    finance_on = inputs.get('financeEnabled') == 'yes'
    fund_on = inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes'
    grace_on = rental_on and inputs.get('graceEnabled') == 'yes'
    exit_on = inputs.get('exitEnabled') == 'yes'

    def has_nonzero(val):
        num = _financial_report_plain_number(val)
        return num is not None and abs(num) > 0.0001

    land_in_kind = inputs.get('landContributionType') == 'inKind' or has_nonzero(projection.get('landEquityContribution'))
    has_land_rent = inputs.get('landStatus') == 'leased' or has_nonzero(projection.get('landRent')) or has_nonzero(inputs.get('annualLandRent'))

    allowed_keys = {'projectCost', 'developerCost', 'totalEquityRequired', 'roi', 'projectIrr', 'payback'}

    if finance_on:
        allowed_keys.update({'projectCostWithFinance', 'facilityAmount', 'arrangementFee', 'totalFinanceInterest', 'totalFinanceCost', 'totalCashEquity', 'equityIrr', 'equityPayback'})
    if finance_on or fund_on:
        allowed_keys.add('adjustedProjectCost')
    if has_land_rent:
        allowed_keys.add('landRent')
    if sales_on:
        allowed_keys.add('saleRevenueTotal')
    if rental_on:
        allowed_keys.update({'revenueY1', 'opexY1', 'noiY1', 'fullOccupancyRevenue', 'fullOccupancyNOI'})
    if grace_on:
        allowed_keys.add('totalGraceDiscount')
    if fund_on:
        allowed_keys.add('totalFundFees')
    if exit_on:
        allowed_keys.add('terminal')
        if sales_on:
            allowed_keys.add('saleExitValue')
        if rental_on:
            allowed_keys.add('operatingExitValue')
    if land_in_kind:
        allowed_keys.add('landEquityContribution')
    if has_nonzero(projection.get('totalEquityDistributions')):
        allowed_keys.add('totalEquityDistributions')

    result = []
    for key, label in FINANCIAL_RESULT_LABELS:
        if key not in allowed_keys:
            continue
        val = projection.get(key)
        if val in (None, '', [], {}) and inputs.get(key) not in (None, ''):
            val = inputs.get(key)
        if val in (None, '', [], {}):
            continue
        result.append((label, val, key))
    return result


def _filter_cashflow_columns(rows, inputs):
    if not isinstance(rows, list) or not rows:
        return rows
    inputs = inputs if isinstance(inputs, dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    sales_on = mode in {'sale', 'mixed'}
    rental_on = mode in {'rental', 'mixed'}
    finance_on = inputs.get('financeEnabled') == 'yes'
    fund_on = inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes'
    grace_on = rental_on and inputs.get('graceEnabled') == 'yes'
    exit_on = inputs.get('exitEnabled') == 'yes'

    drop_columns = set(FINANCIAL_REPORT_DROP_COLUMNS)
    if not sales_on:
        drop_columns.update({'saleRevenue', 'المبيعات', 'saleExit', 'saleExitGross'})
    if not rental_on:
        drop_columns.update({'operatingRevenue', 'إيرادات التأجير', 'opex', 'المصروفات', 'noi', 'NOI', 'operatingExit', 'operatingExitGross', 'occupancyReach', 'الوصول للإشغال %'})
    if not grace_on:
        drop_columns.update({'graceDiscount', 'خصم فترة السماح'})
    if not fund_on:
        drop_columns.update({'fundFeesAnnual', 'أتعاب الصندوق', 'fundManagementFee', 'additionalFundFees', 'fundExitFee', 'performanceFee'})
    if not finance_on:
        drop_columns.update({'financeDraw', 'سحب التمويل', 'financeInterest', 'فائدة التمويل', 'financeFee', 'رسوم التمويل', 'financeRepayment', 'سداد أصل التمويل', 'openingDebt', 'closingDebt', 'فائدة ورسوم التمويل'})
    if not exit_on:
        drop_columns.update({'terminal', 'قيمة التخارج', 'saleExit', 'operatingExit'})

    filtered_rows = []
    for row in rows:
        if isinstance(row, dict):
            filtered_rows.append({k: v for k, v in row.items() if k not in drop_columns and FINANCIAL_COLUMN_LABELS.get(k, k) not in drop_columns})
        else:
            filtered_rows.append(row)
    return filtered_rows


def _financial_report_rows(rows):
    visible = []
    for item in rows:
        if len(item) == 3:
            label, value, key = item
        else:
            label, value = item
            key = ''
        if value in (None, '', [], {}) or isinstance(value, (dict, list)):
            continue
        visible.append((label, value, key))
    if not visible:
        return '<p class="empty">لا توجد قيم مطبقة في هذا القسم.</p>'
    return '<table class="summary-table"><tbody>' + ''.join(
        f'<tr><th>{_financial_report_escape(label)}</th>'
        + _financial_report_cell(_financial_report_format_number(value, key)) + '</tr>'
        for label, value, key in visible
    ) + '</tbody></table>'


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
    'noi': 'NOI',
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
    'key': 'المتغير', 'low': 'متحفظ', 'high': 'متفائل',
    'scenario': 'السيناريو', 'totalRevenue': 'إجمالي الإيرادات',
    'fullOccupancyNOI': 'NOI عند الإشغال المستهدف', 'investmentCost': 'إجمالي تكلفة الاستثمار',
    'netProfit': 'صافي الربح', 'exitValue': 'قيمة التخارج', 'roi': 'ROI',
    'projectIrr': 'Project IRR', 'equityIrr': 'Equity IRR', 'payback': 'فترة الاسترداد',
    'equityRequired': 'إجمالي حقوق الملكية',
    'cashEquityRequired': 'الضخ النقدي المطلوب',
}

FINANCIAL_REPORT_DROP_COLUMNS = {
    'ترتيب / حذف', 'حذف', 'ترتيب', 'مرتبط بمكون', 'المكون المرتبط',
    'idx', 'id', 'component', 'componentId', 'leasable', 'totalArea',
    'projected', 'cashflows', 'projectCashflows', 'financePlan', 'financeRepaymentPlan',
    'modeFlags', 'areaState',
}


def _financial_report_table(rows):
    if not isinstance(rows, list) or not rows:
        return '<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>'
    keys = []
    for row in rows:
        if isinstance(row, dict):
            for key in row:
                label = FINANCIAL_COLUMN_LABELS.get(key, key)
                if key in FINANCIAL_REPORT_DROP_COLUMNS or label in FINANCIAL_REPORT_DROP_COLUMNS:
                    continue
                if key not in keys:
                    keys.append(key)
    if not keys:
        return '<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>'
    headers = ''.join(
        f'<th>{_financial_report_escape(FINANCIAL_COLUMN_LABELS.get(key, key))}</th>' for key in keys)
    body = ''.join('<tr>' + ''.join(_financial_report_cell(_financial_report_format_number(row.get(key), key)) for key in keys) + '</tr>'
                   for row in rows if isinstance(row, dict))
    return f'<table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table>'


def _financial_screen_parts(model):
    """The study as the screen sent it, or None for a draft saved before that was captured."""
    report = model.get('report') if isinstance(model, dict) else None
    parts = report.get('parts') if isinstance(report, dict) else None
    if not isinstance(parts, list) or not parts:
        return None
    cleaned = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get('type') == 'fields':
            rows = [
                row for row in (part.get('rows') or [])
                if isinstance(row, (list, tuple)) and len(row) >= 2
                and str(row[1] if row[1] is not None else '').strip()
            ]
            if not rows:
                continue
            part = {**part, 'rows': rows}
        elif part.get('type') == 'table':
            headers = [str(header or '').strip() for header in (part.get('headers') or [])]
            kept_indexes = [index for index, header in enumerate(headers)
                            if header not in FINANCIAL_REPORT_DROP_COLUMNS]
            if not kept_indexes:
                continue
            rows = [
                [row[index] if index < len(row) else '' for index in kept_indexes]
                for row in (part.get('rows') or []) if isinstance(row, (list, tuple))
            ]
            part = {**part, 'headers': [headers[index] for index in kept_indexes], 'rows': rows}
        cleaned.append(part)
    result = []
    for index, part in enumerate(cleaned):
        if part.get('type') == 'heading':
            level = int(part.get('level') or 2)
            has_content = False
            for following in cleaned[index + 1:]:
                if following.get('type') == 'heading' and int(following.get('level') or 2) <= level:
                    break
                if following.get('type') != 'heading':
                    has_content = True
                    break
            if not has_content:
                continue
        result.append(part)
    return result or None


def _financial_screen_sections(parts):
    """Keep the screen's labels, values and order while normalizing numeric display."""
    sections = []
    body = []

    def flush():
        if body and any(not item.startswith(('<h2>', '<h3>')) for item in body):
            sections.append('<section>' + ''.join(body) + '</section>')
        body.clear()

    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get('type')
        if kind == 'heading':
            level = 3 if part.get('level') == 3 else 2
            if level == 2:
                flush()
            body.append(f'<h{level}>{_financial_report_escape(part.get("text"))}</h{level}>')
        elif kind == 'fields':
            rows = [
                row for row in (part.get('rows') or [])
                if isinstance(row, (list, tuple)) and len(row) >= 2
                and str(row[1] if row[1] is not None else '').strip()
            ]
            if not rows:
                continue
            regular_rows = [row for row in rows if str(row[0] or '').strip() != 'الإيضاحات']
            if regular_rows:
                body.append('<table class="summary-table"><tbody>' + ''.join(
                    f'<tr><th>{_financial_report_escape(row[0])}</th>'
                    + _financial_report_cell(_financial_report_format_display(row[1], row[0]), row[1]) + '</tr>'
                    for row in regular_rows) + '</tbody></table>')
            for row in rows:
                if str(row[0] or '').strip() == 'الإيضاحات':
                    body.append('<div class="financial-clarifications">'
                                + _financial_report_escape(row[1]) + '</div>')
        elif kind == 'table':
            headers = [header for header in (part.get('headers') or [])]
            if not headers:
                continue
            rows = [row for row in (part.get('rows') or []) if isinstance(row, (list, tuple))]
            if not rows:
                body.append('<p class="empty">لا توجد بنود مدخلة في هذا الجدول.</p>')
                continue
            head = ''.join(f'<th>{_financial_report_escape(header)}</th>' for header in headers)
            cells = ''.join(
                '<tr>' + ''.join(
                    _financial_report_cell(
                        _financial_report_format_display(cell, headers[index] if index < len(headers) else ''),
                        cell,
                    )
                    for index, cell in enumerate(row)
                ) + '</tr>'
                for row in rows)
            wide = ' wide' if len(headers) > 8 else ''
            body.append(f'<table class="data-table{wide}"><thead><tr>{head}</tr></thead><tbody>{cells}</tbody></table>')
    flush()
    return sections


def build_financial_report_html(project_name, model, branding, tenant_id):
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    projection = model.get('projection', {}) if isinstance(model, dict) and isinstance(model.get('projection'), dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    rental_on = mode in {'rental', 'mixed'}
    font_css, font_family = build_font_css(branding or {}, tenant_id, embed=True)
    font_css = (font_css or '').replace('.slide', '.financial-report')
    rows = lambda keys: _financial_report_rows([(label, inputs.get(key), key) for key, label in keys])
    sections = []
    sections.append(f'<section class="cover"><div class="eyebrow">دراسة مالية</div><h1>{_financial_report_escape(project_name)}</h1><h2>التقرير المالي المنظم</h2><p>تم إنشاء التقرير من النسخة المعتمدة للمدخلات والافتراضات.</p></section>')
    screen_parts = _financial_screen_parts(model)
    if screen_parts:
        sections.extend(_financial_screen_sections(screen_parts))
        return _financial_report_document(sections, font_css, font_family)
    sections.append('<section><h2>1. ملخص المشروع</h2>' + rows([('unitRevenueMode', 'طبيعة الإيرادات'), ('developmentYears', 'مدة التطوير'), ('operationYears', 'سنوات التشغيل'), ('landArea', 'مساحة الأرض')]) + '</section>')
    sections.append('<section><h2>2. الأرض والمساحات</h2>' + rows([('landArea', 'مساحة الأرض'), ('coverageRate', 'نسبة التغطية'), ('floorCount', 'عدد الطوابق'), ('builtUpAreaAbove', 'مسطحات البناء فوق الأرض'), ('basementArea', 'مساحة البدرومات'), ('landValueMethod', 'طريقة احتساب قيمة الأرض'), ('landStatus', 'حالة الأرض')]) + '</section>')
    for number, title, table_key in (
        ('3', 'مكونات المشروع', 'componentsTable'),
        ('4', 'بنود الإيرادات', 'revenueTable'),
        ('5', 'تكاليف المشروع', 'costTable'),
        ('7', 'المصروفات التشغيلية', 'opexTable'),
    ):
        sections.append(f'<section><h2>{number}. {title}</h2>{_financial_report_table(tables.get(table_key))}</section>')
    if inputs.get('developerPaymentsEnabled', 'yes') == 'yes':
        sections.insert(-1, f'<section><h2>6. مراحل التطوير ودفعات المطور</h2>{_financial_report_table(tables.get("scheduleTable"))}</section>')
    if rental_on and inputs.get('graceEnabled') == 'yes':
        grace_rows = [
            ('طريقة احتساب السماح', inputs.get('graceMethod'), 'graceMethod'),
            ('نطاق فترة السماح', inputs.get('graceScope'), 'graceScope'),
            ('سنة بداية السماح', inputs.get('graceStartYear'), 'graceStartYear'),
            ('مدة السماح (شهر)', inputs.get('graceDurationMonths'), 'graceDurationMonths'),
            ('نسبة الخصم %', inputs.get('graceDiscountRate'), 'graceDiscountRate'),
            ('إجمالي الخصم', inputs.get('graceTotalDiscount') or projection.get('totalGraceDiscount'), 'graceTotalDiscount'),
        ]
        grace_html = '<section><h2>فترة السماح للمستأجرين</h2>' + _financial_report_rows(grace_rows)
        if inputs.get('graceMethod') == 'schedule' and tables.get('graceScheduleTable'):
            grace_html += _financial_report_table(tables.get('graceScheduleTable'))
        grace_html += '</section>'
        sections.append(grace_html)
    if inputs.get('financeEnabled') == 'yes':
        sections.append('<section><h2>8. التمويل</h2>' + rows([('financeBase', 'أساس التمويل'), ('financingRate', 'نسبة التمويل'), ('annualFinanceRate', 'معدل الفائدة'), ('financeInterestMethod', 'طريقة الفائدة'), ('financeDrawYears', 'سنوات السحب'), ('financeRepaymentYears', 'سنوات السداد')]) + _financial_report_table(tables.get('financeDrawTable')) + _financial_report_table(tables.get('financeRepaymentTable')) + '</section>')
    if inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes':
        sections.append('<section><h2>9. الصندوق وأتعابه</h2>' + rows([('fundFeeBase', 'أساس الأتعاب'), ('fundCapitalInput', 'رأس مال الصندوق'), ('fundManagementRate', 'نسبة الإدارة'), ('fundFeeStartYear', 'بداية الاحتساب'), ('fundFeeEndYear', 'نهاية الاحتساب')]) + _financial_report_table(tables.get('fundAdditionalFeesTable')) + '</section>')
    if inputs.get('externalEnabled') == 'yes' and tables.get('externalTable'):
        sections.append('<section><h2>10. البنود الخارجية</h2>' + _financial_report_table(tables.get('externalTable')) + '</section>')
    if inputs.get('exitEnabled') == 'yes':
        sections.append('<section><h2>11. التخارج</h2>' + rows([('saleExitMethod', 'التخارج البيعي'), ('saleExitYear', 'سنة التخارج البيعي'), ('exitMethod', 'التخارج التشغيلي'), ('operatingExitYear', 'سنة التخارج التشغيلي'), ('exitInput', 'مدخل التخارج')]) + '</section>')
    filtered_results = _filter_financial_results(inputs, projection)
    sections.append('<section class="keep-together"><h2>12. النتائج المالية</h2>' + _financial_report_rows(filtered_results) + '</section>')
    cf_rows = _filter_cashflow_columns(tables.get('cashflowTable'), inputs)
    sections.append('<section class="wide-table"><h2>13. التدفقات النقدية السنوية</h2>' + _financial_report_table(cf_rows) + '</section>')
    sensitivity_assumptions = tables.get('sensitivityAssumptionsTable')
    if not isinstance(sensitivity_assumptions, list) or not sensitivity_assumptions:
        dynamic_rows = model.get('dynamicRows') if isinstance(model, dict) else {}
        if isinstance(dynamic_rows, dict) and isinstance(dynamic_rows.get('sensitivity'), list):
            sensitivity_assumptions = dynamic_rows.get('sensitivity')
    sections.append(
        '<section class="wide-table"><h2>14. تحليل الحساسية العام</h2>'
        + '<h3>افتراضات السيناريوهات</h3>' + _financial_report_table(sensitivity_assumptions)
        + '<h3>النتائج المقارنة</h3>' + _financial_report_table(tables.get('sensitivityTable'))
        + '</section>'
    )
    clarifications = str(inputs.get('financialClarifications') or '').strip()
    if clarifications:
        sections.append('<section><h2>15. الإيضاحات</h2><div class="financial-clarifications">'
                        + _financial_report_escape(clarifications) + '</div></section>')
    return _financial_report_document(sections, font_css, font_family)


def _financial_report_document(sections, font_css, font_family):
    """One readable monochrome sheet.

    Branding colours used to paint this: a light `secondary_color` printed the label column of
    every summary table as pale text on a pale tint, which is unreadable. A financial table is
    read for its figures, so the report is deliberately black on white with grey chrome.
    """
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>
{font_css}
@page {{ size: A4 landscape; margin: 10mm; }}
* {{ box-sizing:border-box; }} body {{ margin:0; color:#1a1a1a; background:#fff; font-family:{font_family}; direction:rtl; line-height:1.5; }}
.financial-report {{ max-width:none; margin:0; }} section {{ margin:0 0 16px; page-break-inside:auto; }}
.keep-together {{ break-inside:avoid; page-break-inside:avoid; }}
.wide-table table, table.wide {{ font-size:8px; }} .wide-table th,.wide-table td, table.wide th, table.wide td {{ padding:4px; white-space:normal; word-break:break-word; }}
.cover {{ min-height:175mm; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; border:2px solid #1a1a1a; padding:30px; page-break-after:always; }}
.eyebrow {{ color:#4a4a4a; font-weight:700; }} h1 {{ color:#1a1a1a; font-size:32px; margin:18px 0 6px; }} h2 {{ color:#1a1a1a; font-size:20px; border-bottom:2px solid #1a1a1a; padding-bottom:6px; }}
h3 {{ color:#1a1a1a; font-size:14px; margin:12px 0 6px; }}
table {{ width:100%; border-collapse:collapse; margin:8px 0 14px; font-size:10px; }} th,td {{ border:1px solid #b3b3b3; padding:6px; text-align:right; vertical-align:top; color:#1a1a1a; }} thead {{ display:table-header-group; }} tr {{ break-inside:avoid; page-break-inside:avoid; }} thead th {{ background:#e6e6e6; font-weight:700; }} .summary-table th {{ width:38%; background:#f2f2f2; font-weight:400; }} .summary-table td {{ font-weight:700; }} .empty {{ color:#555; border:1px dashed #b3b3b3; padding:10px; }}
.financial-clarifications {{ white-space:pre-wrap; border:1px solid #b3b3b3; padding:10px; font-size:10px; line-height:1.6; }}
</style></head><body><main class="financial-report">{''.join(sections)}</main></body></html>'''


def _financial_pdf_plain_html(html):
    """Drop huge embedded fonts so the PyMuPDF HTML parser can open the report."""
    text = str(html or '')
    text = re.sub(r'@font-face\s*\{.*?\}', '', text, flags=re.S)
    text = re.sub(r'src:\s*url\(data:font/[^)]+\);?', '', text, flags=re.I)
    text = re.sub(r'<style>.*?</style>', '<style>body{font-family:Tahoma,Arial,sans-serif;direction:rtl}table{width:100%;border-collapse:collapse;font-size:10px}th,td{border:1px solid #ccc;padding:4px;text-align:right}h1,h2,h3{color:#123B6D}</style>', text, flags=re.S)
    return text


def _financial_pdf_font():
    return maps_service.bundled_arabic_font_path()


def _financial_pdf_shape(text):
    """PyMuPDF places glyphs verbatim, so Arabic must be shaped and ordered first."""
    value = str(text or '')
    if not re.search(r'[\u0600-\u06ff]', value):
        return value
    return maps_service.shape_arabic_for_drawing(value)


def _financial_pdf_has_text(output_path, minimum=200):
    """A PDF of table borders with no glyphs is a failed render, not a report.

    The MuPDF HTML engine writes exactly that on hosts with no system Arabic font,
    and the old size-only check accepted it, so the client downloaded blank pages.
    """
    import fitz
    try:
        document = fitz.open(output_path)
    except Exception as error:
        print(f'[FINANCIAL PDF] cannot inspect the written file ({error})')
        return False
    try:
        return sum(len(page.get_text().strip()) for page in document) >= minimum
    finally:
        document.close()


def _financial_pdf_text(value, key=''):
    raw = _financial_report_format_number(value, key)
    return html_lib.unescape(raw).replace('\xa0', ' ')


def generate_financial_pdf_from_model(project_name, model, output_path):
    import fitz
    inputs = _financial_inputs(model)
    tables = model.get('tables', {}) if isinstance(model, dict) and isinstance(model.get('tables'), dict) else {}
    projection = model.get('projection', {}) if isinstance(model, dict) and isinstance(model.get('projection'), dict) else {}
    mode = inputs.get('unitRevenueMode') or 'mixed'
    rental_on = mode in {'rental', 'mixed'}
    font_path = _financial_pdf_font()
    document = fitz.open()
    page_size = fitz.paper_rect('a4-l')
    page = document.new_page(width=page_size.width, height=page_size.height)
    margin = 28
    y = margin
    font_name = 'helv'
    if font_path:
        try:
            page.insert_font(fontname='arabic', fontfile=font_path)
            font_name = 'arabic'
        except Exception as error:
            print(f'[FINANCIAL PDF] custom font skipped ({error})')
            font_path = None
    metrics = fitz.Font(fontfile=font_path) if font_path else fitz.Font('helv')
    latin_metrics = fitz.Font('helv')

    def ensure_space(needed=24):
        nonlocal page, y
        if y + needed < page_size.height - margin:
            return
        page = document.new_page(width=page_size.width, height=page_size.height)
        if font_path:
            try:
                page.insert_font(fontname='arabic', fontfile=font_path)
            except Exception:
                pass
        y = margin

    def split_runs(value):
        """Group a visual-order line by which embedded font actually owns each glyph.

        The bundled Arabic font carries no Latin or percent glyph, so a single-font
        line drops them to empty boxes.
        """
        runs = []
        for character in value:
            arabic = font_name == 'arabic' and metrics.has_glyph(ord(character))
            name, font = (font_name, metrics) if arabic else ('helv', latin_metrics)
            if runs and runs[-1][0] == name:
                runs[-1][2] += character
            else:
                runs.append([name, font, character])
        return runs

    def place(rect, text, size, color=(0.15, 0.15, 0.15)):
        """Right-align one line with insert_text.

        insert_textbox silently draws nothing when its line height does not fit the
        rectangle, which is why the whole report used to come out as empty borders.
        """
        value = _financial_pdf_shape(text)
        if not value.strip():
            return
        runs = split_runs(value)
        width = lambda items: sum(font.text_length(part, size) for _, font, part in items)
        while len(value) > 1 and width(runs) > rect.width:
            value = value[1:]
            runs = split_runs(value)
        baseline = min(rect.y0 + size, rect.y1 - 1) if rect.height > size else rect.y0 + size
        x = max(rect.x0, rect.x1 - width(runs))
        for name, font, part in runs:
            page.insert_text((x, baseline), part, fontname=name, fontsize=size, color=color)
            x += font.text_length(part, size)

    def place_wrapped(rect, text, size, color=(0.1, 0.1, 0.1), max_lines=2):
        """Header cells carry whole Arabic phrases, so a single truncated line loses the column."""
        words = str(text or '').split(' ')
        lines, current = [], ''
        for word in words:
            candidate = (current + ' ' + word).strip()
            if current and metrics.text_length(_financial_pdf_shape(candidate), size) > rect.width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for index, line in enumerate(lines[:max_lines]):
            top = rect.y0 + index * (size + 1)
            place(fitz.Rect(rect.x0, top, rect.x1, top + size + 1), line, size, color=color)

    def draw_text(text, size=11, indent=0):
        nonlocal y
        ensure_space(size + 8)
        box = fitz.Rect(margin + indent, y, page_size.width - margin, y + size + 6)
        place(box, text, size, color=(0.1, 0.1, 0.1))
        y += size + 8

    def draw_paragraph(text, size=9):
        nonlocal y
        width = page_size.width - margin * 2
        for paragraph in str(text or '').splitlines() or ['']:
            words = paragraph.split()
            if not words:
                y += size + 4
                continue
            line = ''
            for word in words:
                candidate = (line + ' ' + word).strip()
                shaped = _financial_pdf_shape(candidate)
                measured = sum(font.text_length(part, size) for _, font, part in split_runs(shaped))
                if line and measured > width:
                    draw_text(line, size)
                    line = word
                else:
                    line = candidate
            if line:
                draw_text(line, size)

    def draw_kv_table(rows, raw=False):
        nonlocal y
        visible = []
        for item in rows:
            label, value, key = (item + ('',))[:3] if len(item) < 3 else item
            if value in (None, '', [], {}) or isinstance(value, (dict, list)):
                continue
            visible.append((
                str(label),
                html_lib.unescape(_financial_report_format_display(value, label)) if raw
                else _financial_pdf_text(value, key),
            ))
        if not visible:
            draw_text('لا توجد قيم مطبقة في هذا القسم.', 9)
            return
        col_w = (page_size.width - margin * 2) / 2
        for label, value in visible:
            if label.strip() == 'الإيضاحات':
                draw_paragraph(value)
                y += 4
                continue
            ensure_space(16)
            rect = fitz.Rect(margin, y, page_size.width - margin, y + 15)
            page.draw_rect(rect, color=(0.85, 0.82, 0.8), width=0.4)
            place(fitz.Rect(rect.x0 + col_w + 4, rect.y0 + 2, rect.x1 - 4, rect.y1), label, 8)
            place(fitz.Rect(rect.x0 + 4, rect.y0 + 2, rect.x0 + col_w - 4, rect.y1), value, 8)
            y += 15

    def draw_data_table(rows, title):
        nonlocal y
        if not isinstance(rows, list) or not rows:
            draw_text(title, 12)
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        keys = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row:
                label = FINANCIAL_COLUMN_LABELS.get(key, key)
                if key in FINANCIAL_REPORT_DROP_COLUMNS or label in FINANCIAL_REPORT_DROP_COLUMNS:
                    continue
                if key not in keys:
                    keys.append(key)
        if not keys:
            draw_text(title, 12)
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        preferred = {
            'cashflowTable': ['year', 'phase', 'saleRevenue', 'operatingRevenue', 'developmentCost', 'developerPayment', 'opex', 'noi', 'financeDraw', 'financeInterest', 'final', 'cumulative'],
            'sensitivityAssumptionsTable': ['key', 'low', 'high'],
            'sensitivityTable': ['scenario', 'totalRevenue', 'investmentCost', 'netProfit', 'roi', 'projectIrr', 'equityRequired'],
        }
        wanted = preferred.get(title) or preferred.get(next((key for key in ('cashflowTable', 'sensitivityAssumptionsTable', 'sensitivityTable') if key in title), ''))
        if 'التدفقات' in title:
            wanted = preferred['cashflowTable']
        elif 'الافتراضات' in title:
            wanted = preferred['sensitivityAssumptionsTable']
        elif 'النتائج' in title and 'حساسية' in title:
            wanted = preferred['sensitivityTable']
        if wanted:
            keys = [key for key in wanted if key in keys] or keys[:8]
        elif len(keys) > 8:
            keys = keys[:8]
        draw_text(title, 12)
        usable = page_size.width - margin * 2
        col_w = usable / max(1, len(keys))
        row_h = 14
        def paint_row(values, header=False):
            nonlocal y
            ensure_space(row_h)
            x = margin
            for value in reversed(values):
                cell = fitz.Rect(x, y, x + col_w, y + row_h)
                fill = (0.07, 0.23, 0.43) if header else None
                page.draw_rect(cell, color=(0.85, 0.82, 0.8), fill=fill, width=0.4)
                color = (1, 1, 1) if header else (0.15, 0.15, 0.15)
                place(cell + (2, 1, -2, -1), value, 7, color=color)
                x += col_w
            y += row_h
        paint_row([FINANCIAL_COLUMN_LABELS.get(key, key) for key in keys], header=True)
        for row in rows:
            if isinstance(row, dict):
                paint_row([_financial_pdf_text(row.get(key), key) for key in keys])

    def draw_grid(headers, rows):
        """Draw a screen table verbatim. Columns beyond a readable page width continue in a
        second band that repeats the first column, so no entered figure is dropped."""
        nonlocal y
        if not headers:
            return
        if not rows:
            draw_text('لا توجد بنود مدخلة في هذا الجدول.', 9)
            return
        rows = [
            [
                html_lib.unescape(_financial_report_format_display(
                    value, headers[index] if index < len(headers) else ''
                ))
                for index, value in enumerate(row)
            ]
            for row in rows
        ]
        cell = lambda row, index: str(row[index]).strip() if index < len(row) else ''
        max_columns = 9
        bands = [(headers, rows)]
        if len(headers) > max_columns:
            bands = []
            for start in range(1, len(headers), max_columns - 1):
                picked = list(range(start, min(start + max_columns - 1, len(headers))))
                bands.append(([headers[0]] + [headers[index] for index in picked],
                              [[cell(row, 0)] + [cell(row, index) for index in picked] for row in rows]))
        for band_headers, band_rows in bands:
            col_w = (page_size.width - margin * 2) / len(band_headers)
            ensure_space(38)
            top = y
            x = margin
            for header in reversed(band_headers):
                box = fitz.Rect(x, top, x + col_w, top + 22)
                page.draw_rect(box, color=(0.7, 0.7, 0.7), fill=(0.9, 0.9, 0.9), width=0.4)
                place_wrapped(box + (2, 2, -2, -2), header, 7)
                x += col_w
            y = top + 22
            for row in band_rows:
                ensure_space(14)
                top = y
                x = margin
                for index in reversed(range(len(band_headers))):
                    box = fitz.Rect(x, top, x + col_w, top + 14)
                    page.draw_rect(box, color=(0.7, 0.7, 0.7), width=0.4)
                    place(box + (2, 1, -2, -1), cell(row, index), 7)
                    x += col_w
                y = top + 14
            y += 8

    screen_parts = _financial_screen_parts(model)
    if screen_parts:
        draw_text(project_name or 'الدراسة المالية', 18)
        for part in screen_parts:
            if not isinstance(part, dict):
                continue
            kind = part.get('type')
            if kind == 'heading':
                draw_text(str(part.get('text') or ''), 10 if part.get('level') == 3 else 12)
            elif kind == 'fields':
                draw_kv_table([(row[0], row[1], '') for row in (part.get('rows') or [])
                               if isinstance(row, (list, tuple)) and len(row) >= 2], raw=True)
            elif kind == 'table':
                draw_grid([str(header) for header in (part.get('headers') or [])],
                          [list(row) for row in (part.get('rows') or []) if isinstance(row, (list, tuple))])
        document.save(output_path)
        document.close()
        return output_path

    draw_text(project_name or 'الدراسة المالية', 18)
    draw_text('التقرير المالي المنظم', 13)
    draw_text('1. ملخص المشروع', 12)
    draw_kv_table([
        ('طبيعة الإيرادات', inputs.get('unitRevenueMode'), 'unitRevenueMode'),
        ('مدة التطوير', inputs.get('developmentYears'), 'developmentYears'),
        ('سنوات التشغيل', inputs.get('operationYears'), 'operationYears'),
        ('مساحة الأرض', inputs.get('landArea'), 'landArea'),
    ])
    draw_text('2. الأرض والمساحات', 12)
    draw_kv_table([
        ('مساحة الأرض', inputs.get('landArea'), 'landArea'),
        ('نسبة التغطية', inputs.get('coverageRate'), 'coverageRate'),
        ('عدد الطوابق', inputs.get('floorCount'), 'floorCount'),
        ('مسطحات البناء فوق الأرض', inputs.get('builtUpAreaAbove'), 'builtUpAreaAbove'),
        ('مساحة البدرومات', inputs.get('basementArea'), 'basementArea'),
        ('حالة الأرض', inputs.get('landStatus'), 'landStatus'),
    ])
    for number, title, table_key in (
        ('3', 'مكونات المشروع', 'componentsTable'),
        ('4', 'بنود الإيرادات', 'revenueTable'),
        ('5', 'تكاليف المشروع', 'costTable'),
    ):
        draw_data_table(tables.get(table_key), f'{number}. {title}')
    if inputs.get('developerPaymentsEnabled', 'yes') == 'yes':
        draw_data_table(tables.get('scheduleTable'), '6. مراحل التطوير ودفعات المطور')
    draw_data_table(tables.get('opexTable'), '7. المصروفات التشغيلية')
    if rental_on and inputs.get('graceEnabled') == 'yes':
        draw_text('فترة السماح للمستأجرين', 12)
        draw_kv_table([
            ('طريقة احتساب السماح', inputs.get('graceMethod'), 'graceMethod'),
            ('نطاق فترة السماح', inputs.get('graceScope'), 'graceScope'),
            ('سنة بداية السماح', inputs.get('graceStartYear'), 'graceStartYear'),
            ('مدة السماح (شهر)', inputs.get('graceDurationMonths'), 'graceDurationMonths'),
            ('نسبة الخصم %', inputs.get('graceDiscountRate'), 'graceDiscountRate'),
            ('إجمالي الخصم', inputs.get('graceTotalDiscount') or projection.get('totalGraceDiscount'), 'graceTotalDiscount'),
        ])
        if inputs.get('graceMethod') == 'schedule' and tables.get('graceScheduleTable'):
            draw_data_table(tables.get('graceScheduleTable'), 'جدول خصومات فترة السماح')
    if inputs.get('financeEnabled') == 'yes':
        draw_text('8. التمويل', 12)
        draw_kv_table([
            ('أساس التمويل', inputs.get('financeBase'), 'financeBase'),
            ('نسبة التمويل', inputs.get('financingRate'), 'financingRate'),
            ('معدل الفائدة', inputs.get('annualFinanceRate'), 'annualFinanceRate'),
            ('قيمة أساس التمويل', inputs.get('financeBaseAmount') or projection.get('financeBaseAmount'), 'financeBaseAmount'),
            ('قيمة التسهيل التمويلي', inputs.get('facilityAmount') or projection.get('facilityAmount'), 'facilityAmount'),
        ])
        draw_data_table(tables.get('financeDrawTable'), 'خطة السحب')
        draw_data_table(tables.get('financeRepaymentTable'), 'خطة السداد')
    if inputs.get('fundEnabled') == 'yes' and inputs.get('fundFeesEnabled') == 'yes':
        draw_text('9. الصندوق وأتعابه', 12)
        draw_kv_table([
            ('أساس الأتعاب', inputs.get('fundFeeBase'), 'fundFeeBase'),
            ('نسبة الإدارة', inputs.get('fundManagementRate'), 'fundManagementRate'),
        ])
        draw_data_table(tables.get('fundAdditionalFeesTable'), 'أتعاب إضافية')
    if inputs.get('externalEnabled') == 'yes' and tables.get('externalTable'):
        draw_text('10. البنود الخارجية', 12)
        draw_data_table(tables.get('externalTable'), 'البنود الخارجية')
    if inputs.get('exitEnabled') == 'yes':
        draw_text('11. التخارج', 12)
        draw_kv_table([
            ('التخارج البيعي', inputs.get('saleExitMethod'), 'saleExitMethod'),
            ('التخارج التشغيلي', inputs.get('exitMethod'), 'exitMethod'),
            ('سنة التخارج التشغيلي', inputs.get('operatingExitYear'), 'operatingExitYear'),
        ])
    draw_text('12. النتائج المالية', 12)
    filtered_results = _filter_financial_results(inputs, projection)
    draw_kv_table(filtered_results)
    cf_rows = _filter_cashflow_columns(tables.get('cashflowTable'), inputs)
    draw_data_table(cf_rows, '13. التدفقات النقدية السنوية')
    sensitivity_assumptions = tables.get('sensitivityAssumptionsTable')
    if not isinstance(sensitivity_assumptions, list) or not sensitivity_assumptions:
        dynamic_rows = model.get('dynamicRows') if isinstance(model, dict) else {}
        if isinstance(dynamic_rows, dict) and isinstance(dynamic_rows.get('sensitivity'), list):
            sensitivity_assumptions = dynamic_rows.get('sensitivity')
    draw_data_table(sensitivity_assumptions, '14. تحليل الحساسية العام - الافتراضات')
    draw_data_table(tables.get('sensitivityTable'), '14. تحليل الحساسية العام - النتائج')
    clarifications = str(inputs.get('financialClarifications') or '').strip()
    if clarifications:
        draw_text('15. الإيضاحات', 12)
        draw_paragraph(clarifications)
    document.save(output_path)
    document.close()
    return output_path


def generate_financial_pdf(html, output_path, model=None, project_name=''):
    last_error = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            try:
                page = browser.new_page()
                page.set_content(html, wait_until='load', timeout=45000)
                try:
                    page.evaluate('() => document.fonts && document.fonts.ready')
                except Exception:
                    pass
                page.pdf(
                    path=str(output_path),
                    format='A4',
                    landscape=True,
                    print_background=True,
                    margin={'top': '12mm', 'right': '12mm', 'bottom': '12mm', 'left': '12mm'},
                )
            finally:
                browser.close()
        if os.path.isfile(output_path) and _financial_pdf_has_text(output_path):
            return output_path
        last_error = RuntimeError('Playwright wrote an empty PDF')
    except Exception as error:
        last_error = error
        print(f'[FINANCIAL PDF] Playwright failed ({error}); falling back to PyMuPDF')
    # The model writer embeds the Arabic font itself, so it is the reliable engine on
    # hosts without Chromium. The MuPDF HTML engine relies on system fonts and writes
    # pages of empty table borders there, so it is only the last resort.
    if model is not None:
        try:
            generate_financial_pdf_from_model(project_name, model, output_path)
            if _financial_pdf_has_text(output_path):
                return output_path
            last_error = RuntimeError('Model renderer wrote a PDF with no text')
        except Exception as error:
            last_error = error
            print(f'[FINANCIAL PDF] model fallback failed ({error})')
    import fitz
    candidates = [_financial_pdf_plain_html(html), str(html or '')]
    for candidate in candidates:
        try:
            document = fitz.open('html', candidate.encode('utf-8'))
            try:
                document.save(output_path)
            finally:
                document.close()
            if os.path.isfile(output_path) and _financial_pdf_has_text(output_path):
                return output_path
        except Exception as error:
            last_error = error
            print(f'[FINANCIAL PDF] PyMuPDF html open failed ({error})')
    raise RuntimeError(str(last_error or 'Could not write financial PDF'))


@app.route('/api/financial-study/validate', methods=['POST'])
@require_permission('create_presentation')
def api_validate_financial_study():
    data = request.json or {}
    errors = validate_financial_model(data.get('financialModel') or data.get('model') or {})
    return jsonify({'success': not errors, 'validation': errors})


@app.route('/api/financial-study/export', methods=['POST'])
@require_auth
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
        generate_financial_pdf(report_html, output_path, model=model, project_name=project_name)
        export_id = db.create_export(data.get('presentationId') or None, g.tenant_id, 'financial_pdf', output_path)
        return jsonify({
            'success': True,
            'exportId': export_id,
            'format': 'financial_pdf',
            'fileName': os.path.basename(output_path),
            'url': f'/api/exports/{export_id}/download',
        })
    except Exception as error:
        print(f'[FINANCIAL PDF ERROR] {type(error).__name__}: {error!r}')
        if os.path.exists(output_path):
            os.unlink(output_path)
        detail = str(error).strip() or type(error).__name__
        return jsonify({'success': False, 'error': 'تعذر إنشاء ملف الدراسة المالية: ' + detail}), 500


def _export_html_from_slides(slides_data):
    """Join the deck for export, making sure every entry contributes exactly one page.

    Joining the stored html and hoping for the best is how a 50-slide deck exported as 25 pages
    with nothing to point at. Each entry is inspected on its own: an entry whose html carries no
    root `.slide` element is wrapped in one (it would otherwise print as loose content sharing a
    neighbour's page), and an entry carrying several is reported. The notes are logged and returned
    with the error, so the failure names the slide instead of only counting.
    """
    from design_templates import extract_slide_elements

    pieces = []
    empty = []
    wrapped = []
    multiple = []
    for index, item in enumerate(slides_data if isinstance(slides_data, list) else [], 1):
        html = str((item or {}).get('html') or '').strip() if isinstance(item, dict) else str(item or '').strip()
        title = str((item or {}).get('title') or '').strip() if isinstance(item, dict) else ''
        if not html:
            empty.append(index)
            continue
        roots = extract_slide_elements(html)
        if len(roots) == 1:
            pieces.append(roots[0])
        elif len(roots) > 1:
            multiple.append(index)
            pieces.extend(roots)
        else:
            wrapped.append(index)
            pieces.append(
                '<div class="slide" style="width:1280px;height:720px;position:relative;'
                'overflow:hidden;background:#fff;">' + html + '</div>'
            )
        if not html.strip():
            print(f'[EXPORT] slide {index} ({title}) has no html')

    notes = []
    if empty:
        notes.append('شرائح بلا محتوى: ' + '، '.join(str(n) for n in empty))
    if wrapped:
        notes.append('شرائح بلا إطار شريحة (أُضيف لها إطار): ' + '، '.join(str(n) for n in wrapped))
    if multiple:
        notes.append('شرائح تحتوي أكثر من شريحة: ' + '، '.join(str(n) for n in multiple))
    print(f'[EXPORT] entries={len(slides_data or [])} printable={len(pieces)}')
    return '\n'.join(pieces), notes


@app.route('/api/export', methods=['POST'])
@require_permission('export_files')
def api_export():
    """
    Export presentation to PDF or PPTX.
    Input: {format: 'pdf'|'pptx', slidesHtml: '...', slidesData: [...], projectName: '...'}
    """
    data = request.json or {}
    # Safety net: if __chunked_body reached route handler, perform inline reassembly
    if '__chunked_body' in data and isinstance(data.get('__chunked_body'), dict):
        meta = data['__chunked_body']
        fallback_id = str(meta.get('id', ''))
        fallback_total = meta.get('total')
        fallback_gzip = bool(meta.get('gzip'))
        chunk_dir = os.path.join(UPLOADS_DIR, '.body_chunks', fallback_id)
        if os.path.isdir(chunk_dir) and isinstance(fallback_total, int) and (1 <= fallback_total <= 1024):
            try:
                parts = [open(os.path.join(chunk_dir, f'{i}.part'), 'rb').read() for i in range(fallback_total)]
                raw = b''.join(parts)
                if fallback_gzip:
                    import gzip as _gzip
                    raw = _gzip.decompress(raw)
                data = json.loads(raw.decode('utf-8'))
                import shutil as _shutil
                _shutil.rmtree(chunk_dir, ignore_errors=True)
                print(f"[EXPORT] Inline chunked body reassembly succeeded for {fallback_id}")
            except Exception as _fb_err:
                print(f"[EXPORT] Inline chunked body reassembly failed: {_fb_err}")
    fmt = data.get('format', 'pdf').lower()
    project_name = data.get('projectName', 'presentation')
    export_notes = []
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
            project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
            pres = db.get_presentation(presentation_id, g.tenant_id) if presentation_id else None
            if pres and not project_data:
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}
            render_project_data = copy.deepcopy(project_data)
            _prepare_generation_logo_context(render_project_data, branding, g.tenant_id)

            # Fallback: load latest saved slides from DB
            if not slides_html and not slides_data and pres and pres.get('slides_data'):
                try:
                    loaded = pres['slides_data']
                    if isinstance(loaded, str):
                        loaded = json.loads(loaded)
                    slides_data = loaded if isinstance(loaded, list) else []
                except Exception as e:
                    print(f"[EXPORT] failed to load slides_data: {e}")

            if slides_data:
                slides_data = slide_engine.renumber_presentation_slides(
                    slides_data, branding=branding, project_data=render_project_data, tenant_id=g.tenant_id,
                    creative_images=_presentation_creative_images(render_project_data, g.tenant_id),
                )
                slides_html, export_notes = _export_html_from_slides(slides_data)
                if export_notes:
                    print('[EXPORT] ' + ' | '.join(export_notes))
            if not slides_html:
                return jsonify({'error': 'slidesHtml or slidesData is required for PDF export'}), 400

            safe_name = ''.join(c for c in project_name if c.isalnum() or c in '-_ ')[:50].strip() or 'presentation'
            pdf_path = os.path.join(tenant_output_dir, f"{safe_name}_{int(time.time())}.pdf")
            # The deck's own count, so a file that came out short is visible here too. This used to
            # log len(slides_html) — the character count — as the number of slides.
            slide_count = len(slides_data) if slides_data else slides_html.count('class="slide"')
            generate_pdf(slides_html, branding, pdf_path, g.tenant_id)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pdf_path)}'
            # Which renderer wrote the file: 'chromium' / 'chromium-isolated' is the
            # faithful export, 'fitz-fallback' keeps the page count but shifts the
            # layout (white strip left, clipped right) when no browser runs on host.
            try:
                import generate_pdf_from_preview as _deck_renderer
                pdf_engine = getattr(_deck_renderer, 'LAST_PDF_ENGINE', '') or 'unknown'
            except Exception:
                pdf_engine = 'unknown'
            print(f'[EXPORT] engine={pdf_engine} pages={slide_count} file={os.path.basename(pdf_path)}')

            # Record export
            export_id = db.create_export(presentation_id, g.tenant_id, 'pdf', pdf_path)
            if presentation_id:
                _record_change('presentation', presentation_id, 'تصدير',
                               [f'صُدّر العرض بصيغة PDF ({slide_count} شريحة)'])
            return jsonify({'success': True, 'url': f'/api/exports/{export_id}/download', 'exportId': export_id, 'format': 'pdf', 'engine': pdf_engine})

        elif fmt == 'pptx':
            from exports.pptx_export import generate_pptx
            slides_data = data.get('slidesData', [])
            presentation_id = data.get('presentationId')
            project_data = data.get('projectData') if isinstance(data.get('projectData'), dict) else {}
            pres = db.get_presentation(presentation_id, g.tenant_id) if presentation_id else None
            if pres and not project_data:
                try:
                    project_data = json.loads(pres.get('project_data') or '{}')
                except (TypeError, ValueError):
                    project_data = {}

            # Fallback: load latest saved slides from DB
            if not slides_data and pres and pres.get('slides_data'):
                try:
                    loaded = pres['slides_data']
                    if isinstance(loaded, str):
                        loaded = json.loads(loaded)
                    slides_data = loaded if isinstance(loaded, list) else []
                except Exception as e:
                    print(f"[EXPORT] failed to load slides_data for PPTX: {e}")

            if not slides_data:
                return jsonify({'error': 'slidesData is required for PPTX export'}), 400
            slides_data = slide_engine.renumber_presentation_slides(
                slides_data, branding=branding, project_data=project_data, tenant_id=g.tenant_id,
                creative_images=_presentation_creative_images(project_data, g.tenant_id),
            )

            pptx_path = generate_pptx(slides_data, project_name, branding, tenant_output_dir, g.tenant_id)
            relative_url = f'/outputs/{g.tenant_id}/{os.path.basename(pptx_path)}'
            # Native python-pptx build: no browser involved, and generate_pptx
            # already refused a short file. The count travels with the response
            # the same way the PDF engine does.
            pptx_count = len(slides_data)
            print(f'[EXPORT] engine=pptx-native slides={pptx_count} file={os.path.basename(pptx_path)}')

            export_id = db.create_export(data.get('presentationId'), g.tenant_id, 'pptx', pptx_path)
            if data.get('presentationId'):
                _record_change('presentation', data['presentationId'], 'تصدير',
                               [f'صُدّر العرض بصيغة PPTX ({len(slides_data)} شريحة)'])
            return jsonify({'success': True, 'url': f'/api/exports/{export_id}/download', 'exportId': export_id, 'format': 'pptx', 'engine': 'pptx-native', 'slideCount': pptx_count})

        else:
            return jsonify({'error': f'Unsupported format: {fmt}. Use pdf or pptx'}), 400

    except Exception as e:
        print(f"[EXPORT ERROR] {e}")
        # The notes name which slides the deck could not print, so the failure is actionable
        # instead of being a page count the user cannot act on.
        message = str(e)
        if export_notes:
            message += ' — ' + '؛ '.join(export_notes)
        return jsonify({'error': message, 'notes': export_notes}), 500


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

USERNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$')
PHONE_RE = re.compile(r'^\+?[0-9]{8,15}$')
ADMIN_COMPANY_PLANS = {'free', 'pro', 'enterprise'}


def _normalize_phone(value):
    translation = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
    return re.sub(r'[\s()-]+', '', str(value or '').translate(translation))


def _password_validation_error(password):
    if len(password or '') < 10:
        return 'Password must be at least 10 characters'
    if not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
        return 'Password must include letters and numbers'
    return None


def _generate_secure_password():
    while True:
        password = secrets.token_urlsafe(18)
        if not _password_validation_error(password):
            return password


def _identity_conflict(email, username, tenant_id=None, user_id=None):
    tenant_by_email = db.get_tenant_by_email(email)
    if tenant_by_email and tenant_by_email.get('id') != tenant_id:
        return 'Email already registered'
    user_by_email = db.get_user_by_email(email)
    if user_by_email and user_by_email.get('id') != user_id:
        if not tenant_id or user_by_email.get('tenant_id') != tenant_id:
            return 'Email already registered'
        tenant = db.get_tenant_by_id(tenant_id)
        if not tenant or tenant.get('primary_user_id') != user_by_email.get('id'):
            return 'Email already registered'
    tenant_by_username = db.get_tenant_by_username(username)
    if tenant_by_username and tenant_by_username.get('id') != tenant_id:
        return 'Username already registered'
    user_by_username = db.get_user_by_username(username)
    if user_by_username and user_by_username.get('id') != user_id:
        if not tenant_id or user_by_username.get('tenant_id') != tenant_id:
            return 'Username already registered'
        tenant = db.get_tenant_by_id(tenant_id)
        if not tenant or tenant.get('primary_user_id') != user_by_username.get('id'):
            return 'Username already registered'
    return None


def _password_setup_url(raw_token):
    base_url = (os.environ.get('APP_BASE_URL') or request.host_url).rstrip('/')
    return f'{base_url}/set-password/{raw_token}'


def _send_company_welcome_email(recipient, company_name, account_name, username, setup_url):
    host = (os.environ.get('SMTP_HOST') or '').strip()
    if not host:
        return False
    port = int(os.environ.get('SMTP_PORT') or 587)
    smtp_user = (os.environ.get('SMTP_USER') or '').strip()
    smtp_password = os.environ.get('SMTP_PASSWORD') or ''
    sender = (os.environ.get('SMTP_FROM') or smtp_user or '').strip()
    if not sender:
        return False
    message = EmailMessage()
    message['Subject'] = f'مرحبًا بك في LandLoom AI - {company_name}'
    message['From'] = sender
    message['To'] = recipient
    message.set_content(
        f'مرحبًا {account_name}\n\n'
        f'تم إنشاء حساب شركتك {company_name} في منصة LandLoom AI.\n'
        f'اسم المستخدم: {username}\n'
        f'رابط تعيين كلمة المرور: {setup_url}\n\n'
        'هذا الرابط صالح للاستخدام مرة واحدة.'
    )
    try:
        if str(os.environ.get('SMTP_SSL') or '').lower() in {'1', 'true', 'yes'}:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as client:
                if smtp_user:
                    client.login(smtp_user, smtp_password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as client:
                if str(os.environ.get('SMTP_TLS', 'true')).lower() not in {'0', 'false', 'no'}:
                    client.starttls(context=ssl.create_default_context())
                if smtp_user:
                    client.login(smtp_user, smtp_password)
                client.send_message(message)
        return True
    except Exception:
        app.logger.exception('Company welcome email could not be sent')
        return False


def _company_payload(tenant):
    return {
        'id': tenant['id'],
        'companyName': tenant['company_name'],
        'accountManagerName': tenant.get('account_manager_name'),
        'username': tenant.get('username'),
        'phone': tenant.get('phone'),
        'email': tenant['email'],
        'plan': tenant.get('plan', 'free'),
        'creditBalance': float(tenant.get('credit_balance') or 0),
        'isActive': bool(tenant.get('is_active')),
        'isAdmin': bool(tenant.get('is_admin')),
        'primaryUserId': tenant.get('primary_user_id'),
        'requirePasswordChange': bool(tenant.get('require_password_change')),
        'subdomain': tenant.get('subdomain'),
        'domain': tenant.get('domain'),
        'slug': db.tenant_slug(tenant),
        'createdAt': tenant.get('created_at'),
    }


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
        user_id = db.create_user(
            tenant_id, company_name, email, hash_password(password), role='company_admin'
        )
        db.update_tenant(
            tenant_id,
            primary_user_id=user_id,
            account_manager_name=company_name,
        )
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or subdomain already registered'}), 409
    token = create_token(tenant_id, email, is_admin=False, user_id=None, user_name=company_name, user_role='company_admin')
    return jsonify({
        'success': True,
        'token': token,
        'tenant': {'id': tenant_id, 'companyName': company_name, 'email': email, 'domain': domain,
                   'slug': db.tenant_slug({'id': tenant_id, 'subdomain': subdomain, 'username': None})}
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Login a company admin (tenant) or employee (user). Auto-detects by email domain."""
    data = request.json or {}
    identity = (data.get('email') or data.get('username') or '').strip().lower()
    password = data.get('password', '')

    if not identity or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    tenant = db.get_tenant_by_email(identity) or db.get_tenant_by_username(identity)
    if tenant and verify_password(password, tenant['password_hash']):
        if not tenant.get('is_active'):
            return jsonify({'error': 'Account is deactivated'}), 403
        if tenant.get('require_password_change'):
            return jsonify({
                'error': 'Password setup required',
                'code': 'PASSWORD_SETUP_REQUIRED',
            }), 403
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
                'username': tenant.get('username'),
                'slug': db.tenant_slug(tenant),
            },
            'user': {
                'name': tenant['company_name'],
                'role': 'company_admin',
            }
        })

    user = db.get_user_by_email(identity) or db.get_user_by_username(identity)
    if user and verify_password(password, user['password_hash']):
        if not user.get('is_active'):
            return jsonify({'error': 'Account is deactivated'}), 403
        if not user.get('tenant_active'):
            return jsonify({'error': 'Company account is deactivated'}), 403
        if user.get('require_password_change'):
            return jsonify({
                'error': 'Password setup required',
                'code': 'PASSWORD_SETUP_REQUIRED',
            }), 403
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
                'slug': db.tenant_slug(tenant),
            },
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email'],
                'role': user['role'],
                'username': user.get('username'),
            }
        })

    return jsonify({'error': 'Invalid email or password'}), 401


@app.route('/api/auth/password-setup/<raw_token>', methods=['GET'])
def api_password_setup_details(raw_token):
    token = db.get_password_setup_token(raw_token)
    if not token:
        return jsonify({'error': 'Password setup link is invalid or expired'}), 404
    return jsonify({
        'success': True,
        'companyName': token.get('company_name'),
        'username': token.get('username'),
        'email': token.get('email'),
        'expiresAt': token.get('expires_at'),
    })


@app.route('/api/auth/password-setup/<raw_token>', methods=['POST'])
def api_password_setup_complete(raw_token):
    data = request.json or {}
    password = data.get('password') or ''
    error = _password_validation_error(password)
    if error:
        return jsonify({'error': error}), 400
    completed = db.complete_password_setup(raw_token, hash_password(password))
    if not completed:
        return jsonify({'error': 'Password setup link is invalid or expired'}), 404
    tenant = db.get_tenant_by_id(completed['tenant_id'])
    user = db.get_user_by_id(completed['user_id'])
    token = create_token(
        tenant['id'], user['email'], is_admin=bool(tenant.get('is_admin')),
        user_id=user['id'], user_name=user['name'], user_role=user['role']
    )
    return jsonify({
        'success': True,
        'token': token,
        'tenant': _company_payload(tenant),
        'user': {
            'id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'username': user.get('username'),
            'role': user['role'],
        }
    })


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
            'slug': db.tenant_slug(t),
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
    """Extract and parse any JSON dict from text string, including auto-repairing truncated JSON."""
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
        # Auto-repair truncated unclosed JSON
        if depth > 0 or in_str:
            partial = text[start:]
            partial = re.sub(r'\\u[0-9a-fA-F]{0,3}$', '', partial)
            partial = re.sub(r'\\$', '', partial)
            if in_str:
                partial += '"'
            effective_depth = max(1, depth)
            for d in range(effective_depth, 0, -1):
                attempt = partial + ('}' * d)
                try:
                    parsed = json.loads(attempt)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
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
    'إداري': ('إداري', 'مكتبي', 'مكاتب'),
    'فندقي': ('فندقي', 'فندق'),
    'ترفيهي': ('ترفيهي', 'سياحي', 'ترفيه'),
    'صناعي': ('صناعي',),
    'لوجستي': ('لوجستي', 'مستودع', 'تخزين'),
    'صناعي ولوجستي': ('صناعي', 'لوجستي', 'مستودع', 'تخزين'),
    'متعدد الاستخدامات': ('متعدد', 'مختلط', 'متنوع', 'سكني', 'تجاري'),
    'طبي': ('طبي', 'صحي'),
    'تعليمي': ('تعليمي', 'مدرسة', 'جامعة'),
    'سيارات وترفيه': ('سيارات', 'ترفيهي', 'ترفيه'),
    'مختلط': ('مختلط', 'متنوع', 'سكني', 'تجاري', 'متعدد'),
}


def resolve_land_use_status(project_type, allowed_uses):
    """Compare the entered project type with extracted permitted uses.

    The model often leaves land_use_status unresolved even when the form sent
    "سكني" and the regulations already list residential use.
    """
    raw_project = project_type
    if isinstance(raw_project, str):
        try:
            parsed_project = json.loads(raw_project)
            raw_project = parsed_project
        except (TypeError, ValueError):
            raw_project = re.split(r'[,،\n;|]', raw_project)
    projects = raw_project if isinstance(raw_project, (list, tuple, set)) else [raw_project]
    projects = [str(item or '').strip() for item in projects if str(item or '').strip()]
    uses = str(allowed_uses or '').strip()
    if not projects:
        return 'غير محسوم'
    if not uses or uses.startswith('غير محدد'):
        return 'غير محسوم'
    aliases = [alias for project in projects for alias in PROJECT_TYPE_USE_ALIASES.get(project, (project,))]
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
            usage_ctx=_usage_ctx('land'),
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
    'city', 'district', 'main_roads', 'secondary_roads', 'nearby_landmarks', 'nearby_landmarks_data',
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


MARKET_STUDY_MAX_TOKENS = int(os.environ.get('MARKET_STUDY_MAX_TOKENS', '8000'))
MARKET_STUDY_MODEL = os.environ.get('MARKET_STUDY_MODEL') or GEMINI_TEXT_MODEL
_MARKET_JOB_LOCK = threading.Lock()


def _job_dir(namespace, tenant_id):
    path = os.path.join(UPLOADS_DIR, namespace, str(tenant_id))
    os.makedirs(path, exist_ok=True)
    return path


def _job_path(namespace, tenant_id, job_id):
    safe_job_id = str(job_id or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,80}', safe_job_id):
        raise ValueError('Invalid job id')
    return os.path.join(_job_dir(namespace, tenant_id), f'{safe_job_id}.json')


def _write_job(namespace, tenant_id, job_id, payload):
    path = _job_path(namespace, tenant_id, job_id)
    payload = dict(payload)
    payload['updatedAt'] = time.time()
    body = json.dumps(payload, ensure_ascii=False)
    # Polling can be served by another Gunicorn worker, so a process-local lock alone cannot
    # stop that worker from opening the file between truncate() and the final write. Publish a
    # fully flushed sibling file with os.replace(); readers then see either the old complete JSON
    # or the new complete JSON, never a partial document that looks like job_not_found.
    temp_path = f'{path}.tmp-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}'
    with _MARKET_JOB_LOCK:
        try:
            with open(temp_path, 'w', encoding='utf-8') as fh:
                fh.write(body)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            last_error = None
            for _ in range(8):
                try:
                    os.replace(temp_path, path)
                    return
                except OSError as error:
                    last_error = error
                    time.sleep(0.03)
            if last_error:
                raise last_error
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass


def _read_job(namespace, tenant_id, job_id):
    path = _job_path(namespace, tenant_id, job_id)
    if not os.path.isfile(path):
        return None
    with _MARKET_JOB_LOCK:
        try:
            with open(path, encoding='utf-8') as fh:
                payload = json.load(fh)
        except Exception:
            return None
    return payload if isinstance(payload, dict) else None


def _market_job_dir(tenant_id):
    return _job_dir('.market_jobs', tenant_id)


def _market_job_path(tenant_id, job_id):
    return _job_path('.market_jobs', tenant_id, job_id)


def _write_market_job(tenant_id, job_id, payload):
    _write_job('.market_jobs', tenant_id, job_id, payload)


def _read_market_job(tenant_id, job_id):
    return _read_job('.market_jobs', tenant_id, job_id)


def _call_market_study_model(system_prompt, user_content, max_tokens=None):
    """Search-backed market call with JSON, provider, and credit fallbacks."""
    cap = max(2000, int(max_tokens or MARKET_STUDY_MAX_TOKENS))
    # One search cannot price several competitors, so the model is allowed a search per
    # competitor plus the market-wide ones; without max_uses it settled for a single call
    # and left every price blank.
    tools = [{
        'type': 'openrouter:web_search',
        'parameters': {'engine': 'exa', 'max_results': 8, 'max_uses': 10, 'max_total_results': 60},
    }]
    provider = {'order': ['Google'], 'allow_fallbacks': True}
    # Gemini returns reasoning and no content when tools are combined with JSON mode, so
    # that pair silently dropped the search on every call and the model answered from
    # memory with homepage links. Search first, JSON mode only as a fallback.
    attempts = [
        (tools, None),
        (tools, {'type': 'json_object'}),
        (None, {'type': 'json_object'}),
        (None, None),
    ]
    last_response = {}
    last_error = ''
    for _cap_attempt in range(4):
        retry_cap = None
        for index, (attempt_tools, response_format) in enumerate(attempts):
            if index:
                print(
                    '[MARKET STUDY] retrying competitor/summary call with '
                    f'tools={bool(attempt_tools)} json_mode={bool(response_format)}: '
                    f'{_chat_error_message(last_response)}'
                )
            last_response = call_openrouter_chat(
                system_prompt,
                user_content,
                temperature=None,
                max_tokens=cap,
                model=MARKET_STUDY_MODEL,
                response_format=response_format,
                provider=provider,
                tools=attempt_tools,
                timeout=240,
                usage_ctx=_usage_ctx('market'),
            )
            last_error = _chat_error_message(last_response)
            text = _get_chat_response_text(last_response)
            if _has_chat_choices(last_response) and parse_json_object(text):
                return last_response, ''
            affordable = _AFFORDABLE_TOKENS_RE.search(last_error or '')
            if affordable:
                quoted = int(affordable.group(1))
                candidate = max(2000, int(quoted * 0.85))
                if candidate < cap:
                    retry_cap = candidate
                    break
        if retry_cap is None:
            break
        print(f'[MARKET STUDY] provider refused cap={cap}; retrying with cap={retry_cap}')
        cap = retry_cap
    return last_response, last_error


def _market_citation_urls(res):
    """Collect the url_citation pages the web search actually retrieved."""
    urls = []
    for choice in (res.get('choices') or []) if isinstance(res, dict) else []:
        message = (choice or {}).get('message') or {}
        for annotation in message.get('annotations') or []:
            if not isinstance(annotation, dict):
                continue
            citation = annotation.get('url_citation') if isinstance(annotation.get('url_citation'), dict) else {}
            url = str(citation.get('url') or annotation.get('url') or '').strip()
            if url and url not in urls:
                urls.append(url)
    return urls


def _parse_market_model_json(res):
    if not _has_chat_choices(res):
        return {}, _chat_error_message(res) or 'empty_response'
    text = _get_chat_response_text(res)
    parsed = parse_json_object(text)
    if not parsed:
        return {}, 'invalid_json'
    return parsed, ''


def _market_period_label(data):
    period = str(data.get('dataPeriod') or data.get('data_period') or '').strip()
    labels = {item['value']: item['label'] for item in market_study.DATA_PERIOD_OPTIONS}
    if period == 'custom':
        start = str(data.get('dataPeriodFrom') or data.get('data_period_from') or '').strip()
        end = str(data.get('dataPeriodTo') or data.get('data_period_to') or '').strip()
        if start or end:
            return f'فترة مخصصة من {start or "غير محدد"} إلى {end or "غير محدد"}'
    return labels.get(period, period or 'غير محدد')


def _market_radius_label(data, resolved_km):
    value = str(data.get('competitorRadius') or data.get('competitor_radius') or '10').strip()
    if value == 'auto':
        value = '10'
    labels = {item['value']: item['label'] for item in market_study.COMPETITOR_RADIUS_OPTIONS}
    if value == 'custom':
        custom = data.get('competitorRadiusCustomKm') or data.get('competitor_radius_custom_km') or resolved_km
        return f'نطاق مخصص {custom} كم'
    if resolved_km is None and value == 'city':
        return 'كامل المدينة'
    return labels.get(value, value)


def _prepare_market_payload(data):
    payload = dict(data or {})
    radius_value = payload.get('competitorRadius') or payload.get('competitor_radius') or '10'
    custom_km = payload.get('competitorRadiusCustomKm') or payload.get('competitor_radius_custom_km')
    resolved = market_study.resolve_competitor_radius_km(radius_value, custom_km)
    payload['resolvedRadiusKm'] = resolved
    payload['competitorRadiusLabel'] = _market_radius_label(payload, resolved)
    payload['dataPeriodLabel'] = _market_period_label(payload)
    mixed = payload.get('projectComponents') or payload.get('project_mixed_components') or payload.get('project_components')
    payload['projectComponents'] = mixed
    return payload


def _execute_market_competitors(data):
    payload = _prepare_market_payload(data)
    existing = data.get('competitors') if isinstance(data.get('competitors'), list) else []
    mode = 'fill' if str(data.get('mode') or '').strip() == 'fill' else 'generate'
    system_prompt = market_study.build_consultant_system_prompt()
    user_prompt = market_study.build_competitors_user_prompt(payload, existing, mode=mode)
    res, provider_error = _call_market_study_model(system_prompt, user_prompt, max_tokens=6000)
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        reason = 'insufficient_credit' if 'afford' in (provider_error or '').lower() else parse_error
        return {
            'success': False,
            'error': 'تعذر توليد المنافسين.',
            'failureReason': reason,
            'providerError': provider_error,
        }
    generated = parsed.get('competitors') if isinstance(parsed.get('competitors'), list) else []
    merged, added, updated = market_study.merge_generated_competitors(existing, generated, mode=mode)
    market_study.apply_search_citations(merged, _market_citation_urls(res))
    draft_id = payload.get('draftId') or payload.get('draft_id')
    for row in merged:
        if row.get('logo_file_id') or row.get('logo_path'):
            continue
        try:
            _store_imported_competitor_logo(row, draft_id=draft_id)
        except Exception as exc:
            row['logo_import_warning'] = str(exc)
    return {
        'success': True,
        'competitors': merged,
        'sources': market_study.competitor_source_rows(merged),
        'added': added,
        'updated': updated,
        'conflictWarnings': [warning for row in merged for warning in (row.get('conflict_warnings') or [])],
        'searchExpanded': bool(parsed.get('searchExpanded')),
        'expansionNote': parsed.get('expansionNote') or parsed.get('notes') or '',
        'notes': parsed.get('notes') or '',
    }


def _execute_market_summary(data):
    payload = _prepare_market_payload(data)
    competitors = data.get('competitors') if isinstance(data.get('competitors'), list) else []
    raw_current = data.get('currentSummary')
    current_summary = raw_current if isinstance(raw_current, (dict, str)) else None
    current_sources = data.get('currentSources') if isinstance(data.get('currentSources'), list) else None
    current_swot = data.get('currentSwot') if isinstance(data.get('currentSwot'), dict) else None
    system_prompt = market_study.build_consultant_system_prompt()
    user_prompt = market_study.build_summary_user_prompt(
        payload, competitors, current_summary, current_sources=current_sources, current_swot=current_swot
    )
    res, provider_error = _call_market_study_model(system_prompt, user_prompt, max_tokens=MARKET_STUDY_MAX_TOKENS)
    parsed, parse_error = _parse_market_model_json(res)
    if parse_error:
        reason = 'insufficient_credit' if 'afford' in (provider_error or '').lower() else parse_error
        return {
            'success': False,
            'error': 'تعذر توليد ملخص السوق. لم يُستبدل النص الحالي.',
            'failureReason': reason,
            'providerError': provider_error,
        }
    normalized = market_study.normalize_summary(parsed)
    if not market_study.summary_has_content(normalized.get('summary')):
        return {
            'success': False,
            'error': 'عاد النموذج ملخصًا فارغًا. لم يُستبدل النص الحالي.',
            'failureReason': 'empty_response',
            'providerError': provider_error,
        }
    market_study.apply_search_citations(normalized.get('sources'), _market_citation_urls(res), url_key='url')
    return {
        'success': True,
        **normalized,
    }


def _market_job_worker(app, tenant_id, kind, data, job_id):
    with app.app_context():
        _write_market_job(tenant_id, job_id, {
            'status': 'running',
            'success': True,
            'message': 'جاري البحث في المصادر الرسمية وإعداد النتائج...',
            'kind': kind,
        })
        try:
            if kind == 'competitors':
                payload = _execute_market_competitors(data)
            else:
                payload = _execute_market_summary(data)
            status = 'completed' if payload.get('success') else 'failed'
            _write_market_job(tenant_id, job_id, {
                **payload,
                'status': status,
                'kind': kind,
                'message': payload.get('error') or 'اكتملت دراسة السوق',
            })
        except Exception as exc:
            _write_market_job(tenant_id, job_id, {
                'status': 'failed',
                'success': False,
                'kind': kind,
                'error': f'حدث خطأ في دراسة السوق: {exc}',
                'failureReason': 'job_failed',
            })


def _start_market_job(kind, executor):
    data = request.json or {}
    use_background = (not current_app.config.get('TESTING')) or bool(data.get('background'))
    if not use_background:
        result = executor(data)
        status = 200 if result.get('success') else 422
        return jsonify(result), status
    job_id = str(_uuid.uuid4())
    tenant_id = g.tenant_id
    _write_market_job(tenant_id, job_id, {
        'status': 'queued',
        'success': True,
        'kind': kind,
        'message': 'تم استلام طلب دراسة السوق',
    })
    threading.Thread(
        target=_market_job_worker,
        args=(current_app._get_current_object(), tenant_id, kind, data, job_id),
        daemon=True,
    ).start()
    return jsonify({
        'success': True,
        'jobId': job_id,
        'status': 'queued',
        'kind': kind,
        'message': 'بدأت دراسة السوق في الخلفية',
    }), 202


@app.route('/api/executive-content/generate', methods=['POST'])
@require_auth
def api_generate_executive_content():
    """Rewrite one executive-content block from already collected project facts."""
    data = request.json or {}
    key = str(data.get('block') or '').strip()
    spec = executive_content.block_spec(key)
    if not spec:
        return jsonify({'success': False, 'error': 'عنصر محتوى غير صالح'}), 400
    facts = data.get('facts') if isinstance(data.get('facts'), dict) else {}
    ready, missing = executive_content.block_ready(key, facts)
    if not ready:
        labels = {
            'basic': 'البيانات الأساسية',
            'location': 'الموقع',
            'land': 'الأرض والكروكي',
            'timeline': 'الجدول الزمني',
            'financial': 'الدراسة المالية',
            'market': 'دراسة السوق',
        }
        needed = ' و'.join(labels.get(name, name) for name in missing) or 'المدخلات المطلوبة'
        return jsonify({
            'success': False,
            'error': 'استكمل ' + needed + ' قبل توليد هذا النص',
            'missing': missing,
        }), 400
    current = data.get('currentText')
    prompt = executive_content.build_user_prompt(key, facts, current)
    cap = EXECUTIVE_SUMMARY_MAX_TOKENS if key in ('summary', 'risks') else EXECUTIVE_CONTENT_MAX_TOKENS
    raw = None
    last_error = None
    try:
        for attempt in range(3):
            try:
                response = call_zai_chat(
                    executive_content.SYSTEM_PROMPT, prompt, temperature=0.2,
                    max_tokens=cap,
                    reasoning_effort='low',
                    response_format={'type': 'json_object'},
                    usage_ctx=_usage_ctx('executive', data),
                )
                if isinstance(response, dict) and 'error' in response:
                    msg = _chat_error_message(response)
                    affordable = _AFFORDABLE_TOKENS_RE.search(msg)
                    if affordable:
                        retry_cap = max(8000, int(int(affordable.group(1)) * 0.85))
                        if retry_cap < cap:
                            print(f'[EXECUTIVE CONTENT] provider cap refused={cap}; retrying with {retry_cap}')
                            cap = retry_cap
                            continue
                    raise RuntimeError(msg)
                raw = _get_chat_response_text(response) or extract_chat_content(response, 'EXECUTIVE-CONTENT')
                break
            except Exception as primary_error:
                last_error = primary_error
                if not OPENROUTER_KEY:
                    raise
                print(f'[EXECUTIVE CONTENT PRIMARY ERROR] {primary_error}. Trying OpenRouter fallback...')
                fallback = call_openrouter_chat(
                    executive_content.SYSTEM_PROMPT,
                    prompt,
                    temperature=0.2,
                    max_tokens=cap,
                    model=LUNA_TEXT_MODEL,
                    reasoning_effort='low',
                    usage_ctx=_usage_ctx('executive', data),
                    response_format={'type': 'json_object'},
                )
                if isinstance(fallback, dict) and 'error' in fallback:
                    msg = _chat_error_message(fallback)
                    affordable = _AFFORDABLE_TOKENS_RE.search(msg)
                    if affordable:
                        retry_cap = max(8000, int(int(affordable.group(1)) * 0.85))
                        if retry_cap < cap:
                            print(f'[EXECUTIVE CONTENT] fallback cap refused={cap}; retrying with {retry_cap}')
                            cap = retry_cap
                            continue
                raw = _get_chat_response_text(fallback) or extract_chat_content(fallback, 'EXECUTIVE-CONTENT-FALLBACK')
                if raw:
                    break
        if not raw and last_error:
            raise last_error
        parsed = parse_json_object(raw) or {}
        text = executive_content.parse_generated_block(key, parsed)
        if not text and raw and isinstance(raw, str):
            cleaned_raw = executive_content.clean_raw_json_string(raw)
            cleaned_raw = re.sub(r'^```(?:json)?\s*', '', str(cleaned_raw).strip(), flags=re.MULTILINE)
            cleaned_raw = re.sub(r'\s*```$', '', cleaned_raw.strip(), flags=re.MULTILINE)
            text = executive_content.normalize_document(cleaned_raw) if spec.get('output') in ('document', 'risks') else executive_content.normalize_text(cleaned_raw)
        empty = not str(text or '').strip()
        if empty:
            return jsonify({'success': False, 'error': 'عاد النموذج نصًا فارغًا. لم يُستبدل النص الحالي.'}), 422
        return jsonify({'success': True, 'block': key, 'text': text})
    except Exception as error:
        print(f'[EXECUTIVE CONTENT AI ERROR] {error}')
        return jsonify({
            'success': False,
            'error': 'تعذر توليد المحتوى التنفيذي: ' + str(error),
        }), 503


@app.route('/api/market-study/catalog', methods=['GET'])
@require_auth
def api_market_study_catalog():
    return jsonify({'success': True, 'catalog': market_study.catalog_payload()})


@app.route('/api/market-study/competitors', methods=['POST'])
@require_auth
def api_market_study_competitors():
    return _start_market_job('competitors', _execute_market_competitors)


@app.route('/api/market-study/summary', methods=['POST'])
@require_auth
def api_market_study_summary():
    return _start_market_job('summary', _execute_market_summary)


@app.route('/api/market-study/competitors/logo', methods=['POST'])
@require_permission('create_presentation')
def api_market_study_competitor_logo():
    data = request.json or {}
    competitor = market_study.normalize_competitor_row(data.get('competitor') or {}, fallback_source='manual')
    if not competitor:
        return jsonify({'success': False, 'error': 'بيانات المنافس غير صالحة'}), 400
    if competitor.get('logo_file_id') or competitor.get('logo_path'):
        return jsonify({'success': True, 'competitor': competitor})
    official_url = competitor.get('logo_source_url') or competitor.get('source_url')
    verified_official = bool(official_url and market_study.official_source_reliability(
        competitor.get('name'), competitor.get('source'), official_url))
    if not verified_official:
        discovery_prompt = (
            f'ابحث عن الموقع الرسمي وشعار «{competitor["name"]}». '
            'أعد JSON فقط بالمفاتيح official_url وlogo_url وlogo_source_url. '
            'official_url صفحة HTTPS من الموقع الرسمي للمشروع أو المطور، '
            'logo_url رابط HTTPS مباشر لصورة PNG أو JPG أو WEBP من الموقع الرسمي أو نطاق الصور التابع له، '
            'وlogo_source_url الصفحة الرسمية التي تثبت الشعار. إذا لم تجد دليلًا رسميًا أعد القيم فارغة.'
        )
        response, provider_error = _call_market_study_model(
            market_study.build_consultant_system_prompt(), discovery_prompt, max_tokens=1600)
        parsed, parse_error = _parse_market_model_json(response)
        discovered_official = str(parsed.get('official_url') or parsed.get('logo_source_url') or '').strip()
        citations = _market_citation_urls(response)
        cited_official = bool(discovered_official and any(
            _related_official_hosts(discovered_official, citation) for citation in citations))
        if parse_error or not cited_official:
            return jsonify({'success': False, 'error': provider_error or 'لم يُعثر على موقع رسمي موثق'}), 404
        official_url = discovered_official
        competitor['logo_url'] = str(parsed.get('logo_url') or '').strip()
        competitor['logo_source_url'] = str(parsed.get('logo_source_url') or official_url).strip()
        competitor['logo_official_verified'] = True
    else:
        competitor['logo_official_verified'] = True
    if not competitor.get('logo_url'):
        prompt = (
            f'ابحث داخل الموقع الرسمي فقط عن شعار «{competitor["name"]}»: {official_url}. '
            'أعد JSON فقط بالمفتاحين logo_url وlogo_source_url. '
            'logo_url رابط HTTPS مباشر لصورة PNG أو JPG أو WEBP على النطاق الرسمي أو نطاق الصور التابع له، '
            'وlogo_source_url صفحة الموقع الرسمي. إذا لم تجده أعد القيمتين فارغتين.'
        )
        response, provider_error = _call_market_study_model(
            market_study.build_consultant_system_prompt(), prompt, max_tokens=1200)
        parsed, parse_error = _parse_market_model_json(response)
        if parse_error:
            return jsonify({'success': False, 'error': provider_error or 'لم يُعثر على شعار رسمي'}), 404
        competitor['logo_url'] = str(parsed.get('logo_url') or '').strip()
        competitor['logo_source_url'] = str(parsed.get('logo_source_url') or official_url).strip()
    logo_source_url = competitor.get('logo_source_url') or official_url
    if logo_source_url:
        field_sources = market_study.competitor_field_sources(competitor)
        field_sources['logo_url'] = [logo_source_url]
        competitor['field_sources'] = field_sources
        competitor['source_urls'] = list(dict.fromkeys(
            market_study.competitor_source_urls(competitor) + [logo_source_url]))
    competitor = _store_imported_competitor_logo(
        competitor, draft_id=data.get('draftId') or data.get('draft_id'))
    if not competitor.get('logo_file_id'):
        return jsonify({'success': False, 'error': competitor.get('logo_import_warning') or 'لم يُعثر على شعار رسمي'}), 404
    draft_id = data.get('draftId') or data.get('draft_id')
    if draft_id:
        _record_change('draft', draft_id, 'استيراد شعار منافس',
                       [f'استُورد شعار «{competitor.get("name")}» من الموقع الرسمي'], source='ai')
    return jsonify({'success': True, 'competitor': competitor})


@app.route('/api/market-study/jobs/<job_id>', methods=['GET'])
@require_auth
def api_market_study_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{8,64}', str(job_id or '')):
        return jsonify({'success': False, 'error': 'معرف مهمة غير صالح'}), 400
    job = _read_market_job(g.tenant_id, job_id)
    if not job:
        return jsonify({
            'success': False,
            'error': 'مهمة دراسة السوق غير موجودة',
            'failureReason': 'job_not_found',
        }), 404
    return jsonify(job)


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
            '    "allowed_uses": "", "regulatory_constraints": "",\n'
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
            "- allowed_uses للاستخدامات، وregulatory_constraints للقيود فقط.\n"
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
            "(مثل: سكني، تجاري، فندقي، صناعي ولوجستي). لا تكتب حالة توافق نوع المشروع، ولا تكتب «حالة استخدام المشروع». "
            "إذا لم تُستخرج استخدامات واضحة فاكتب «غير محددة في المرجع المتاح».\n"
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
    try:
        project_data = _json.loads(pres.get('project_data') or '{}')
    except (TypeError, ValueError):
        project_data = {}
    old_slides = slide_engine.renumber_presentation_slides(
        old_slides, branding=db.get_branding(g.tenant_id), project_data=project_data,
        tenant_id=g.tenant_id,
        creative_images=_presentation_creative_images(project_data, g.tenant_id),
    )
    db.update_presentation(pres_id, slides_data=old_slides, slide_count=len(old_slides))
    _record_change('presentation', pres_id, 'استرجاع نسخة',
                   [f'رجع العرض إلى نسخة {version["created_at"]}']
                   + change_tracking.describe_slide_changes(current_slides, old_slides))

    return jsonify({'success': True, 'slidesData': old_slides})


@app.route('/api/presentations/<pres_id>/edit-log', methods=['GET'])
@require_auth
def api_get_edit_log(pres_id):
    """Get edit history for a presentation: who changed what, by hand or by the AI."""
    pres = db.get_presentation(pres_id, tenant_id=g.tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404
    return jsonify({'success': True, 'log': db.get_change_log(g.tenant_id, 'presentation', pres_id)})


@app.route('/api/project-draft/<draft_id>/edit-log', methods=['GET'])
@require_auth
def api_get_draft_edit_log(draft_id):
    """Edit history for one project file. Drafts had no history at all before."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    return jsonify({'success': True, 'log': db.get_change_log(g.tenant_id, 'draft', draft_id)})


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
    lines = details if isinstance(details, list) else [details]
    _record_change('presentation', pres_id, action, lines, source=data.get('source') or 'manual')
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FILE UPLOAD ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
# Watermark is a small branding silhouette, not a photo: cap bytes and pixels so a
# huge upload cannot exhaust disk or memory. The saved file keeps its own bytes,
# so a PNG alpha channel is preserved as uploaded.
TENANT_WATERMARK_MAX_BYTES = 5 * 1024 * 1024
TENANT_WATERMARK_MAX_DIMENSION = 4000


def _save_tenant_image(uploaded_file, base_name):
    from PIL import Image, UnidentifiedImageError

    # The stored filename is always <base_name><extension>; the client filename
    # only supplies the extension. A client-sent path can never choose where
    # the file lands, and SVG is rejected here by the extension allow-list.
    extension = os.path.splitext(uploaded_file.filename or '')[1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('Only PNG, JPG, JPEG, and WEBP images are supported')
    try:
        uploaded_file.stream.seek(0)
        raw_bytes = uploaded_file.stream.read()
        uploaded_file.stream.seek(0)
    except (OSError, ValueError):
        raise ValueError('Invalid image file')
    if base_name == 'watermark' and len(raw_bytes) > TENANT_WATERMARK_MAX_BYTES:
        raise ValueError('Image exceeds the 5MB watermark limit')
    try:
        image = Image.open(BytesIO(raw_bytes))
        actual_format = str(image.format or '').upper()
        image.load()
        width, height = image.size
    except (UnidentifiedImageError, OSError):
        raise ValueError('Invalid image file')
    if actual_format not in ('PNG', 'JPEG', 'JPG', 'WEBP'):
        raise ValueError('Invalid image file')
    if base_name == 'watermark' and max(width, height) > TENANT_WATERMARK_MAX_DIMENSION:
        raise ValueError('Image dimensions exceed the 4000px watermark limit')
    try:
        uploaded_file.stream.seek(0)
    except (OSError, ValueError):
        pass

    tenant_dir = os.path.join(UPLOADS_DIR, g.tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    normalized_extension = '.jpg' if extension == '.jpeg' else extension
    file_path = os.path.join(tenant_dir, f'{base_name}{normalized_extension}')
    uploaded_file.save(file_path)
    # The public branding URLs omit the extension. Keep exactly one current
    # source file so changing PNG to WEBP cannot serve an older sibling.
    target_path = os.path.realpath(file_path)
    for stale_path in _tenant_image_storage_candidates(g.tenant_id, base_name):
        if os.path.realpath(stale_path) == target_path or not os.path.isfile(stale_path):
            continue
        try:
            os.unlink(stale_path)
        except OSError as error:
            print(f'[TENANT IMAGE] could not remove stale {base_name} file: {error}')
    return file_path, normalized_extension


PROJECT_FILE_EXTENSIONS = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.pdf': 'application/pdf'
}
PROJECT_FILE_TYPES = {'land_document', 'land_image', 'croquis', 'building_license',
                      'regulation_reference', 'team_logo', 'competitor_logo', 'visual_reference',
                      'conceptual_plan', 'project_logo'}
# Types that must be real images: they are rendered in <img> thumbnails, where a PDF shows nothing.
PROJECT_IMAGE_ONLY_TYPES = {'land_image', 'team_logo', 'competitor_logo', 'visual_reference', 'project_logo'}
PROJECT_FILE_MAX_BYTES = 30 * 1024 * 1024
COMPETITOR_LOGO_MAX_BYTES = 2 * 1024 * 1024
COMPETITOR_LOGO_MIMES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
OFFICIAL_LOGO_PAGE_MAX_BYTES = 2 * 1024 * 1024


def _public_host_addresses(host):
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except (OSError, socket.gaierror):
        return ()
    verified = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return ()
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            return ()
        verified.append(address)
    return tuple(sorted(verified))


def _safe_public_host(host):
    return bool(_public_host_addresses(host))


def _open_pinned_https(parsed, addresses):
    host = str(parsed.hostname).encode('idna').decode('ascii')
    path = parsed.path or '/'
    if parsed.query:
        path += '?' + parsed.query
    pool = HTTPSConnectionPool(
        addresses[0], port=443, assert_hostname=host, server_hostname=host,
        cert_reqs='CERT_REQUIRED', ca_certs=requests.certs.where(),
    )
    response = pool.urlopen(
        'GET', path, headers={'Host': host, 'User-Agent': 'Mozilla/5.0'},
        redirect=False, preload_content=False, retries=False,
        timeout=Timeout(connect=7, read=20),
    )
    return pool, response


_OFFICIAL_CDN_PREFIXES = {'cdn', 'images', 'image', 'img', 'static', 'assets', 'media', 'files'}
_TWO_LEVEL_PUBLIC_SUFFIXES = {'co.uk', 'com.sa', 'net.sa', 'org.sa', 'com.ae', 'co.za', 'com.eg'}


def _normalized_web_host(url):
    return (urlsplit(str(url or '')).hostname or '').lower().removeprefix('www.')


def _registrable_host(host):
    parts = str(host or '').split('.')
    if len(parts) < 2:
        return str(host or '')
    suffix = '.'.join(parts[-2:])
    return '.'.join(parts[-3:]) if suffix in _TWO_LEVEL_PUBLIC_SUFFIXES and len(parts) >= 3 else suffix


def _related_official_hosts(first_url, second_url):
    first = _normalized_web_host(first_url)
    second = _normalized_web_host(second_url)
    return bool(first and second and (
        first == second or first.endswith('.' + second) or second.endswith('.' + first)
    ))


def _same_official_host(logo_url, official_url):
    logo_host = _normalized_web_host(logo_url)
    official_host = _normalized_web_host(official_url)
    if not logo_host or not official_host:
        return False
    if logo_host == official_host or logo_host.endswith('.' + official_host):
        return True
    logo_parts = logo_host.split('.')
    return bool(len(logo_parts) >= 3 and logo_parts[0] in _OFFICIAL_CDN_PREFIXES
                and _registrable_host(logo_host) == _registrable_host(official_host))


class _OfficialLogoHTMLParser(HTMLParser):
    """Collect logo hints exposed by a company's own page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.candidates = []
        self._json_ld_depth = 0
        self._json_ld_parts = []

    def _add(self, value, priority):
        value = html_lib.unescape(str(value or '')).strip()
        if value:
            self.candidates.append((priority, value))

    def handle_starttag(self, tag, attrs):
        attributes = {str(key).lower(): str(value or '').strip() for key, value in attrs}
        tag_name = str(tag or '').lower()
        if tag_name == 'meta':
            identity = (attributes.get('property') or attributes.get('name')
                        or attributes.get('itemprop') or '').lower()
            if identity in {'og:image', 'og:image:url', 'twitter:image', 'twitter:image:src'}:
                self._add(attributes.get('content'), 3)
            elif identity == 'logo':
                self._add(attributes.get('content'), 1)
        elif tag_name == 'link':
            rel = set(re.findall(r'[a-z0-9_-]+', attributes.get('rel', '').lower()))
            if rel.intersection({'icon', 'shortcut', 'apple-touch-icon', 'logo'}):
                self._add(attributes.get('href'), 1)
        elif tag_name == 'img':
            hint = ' '.join(attributes.get(key, '') for key in ('alt', 'class', 'id', 'src')).lower()
            if any(token in hint for token in ('logo', 'brand', 'شعار')):
                image_src = attributes.get('src') or attributes.get('data-src') or attributes.get('data-lazy-src')
                if image_src.lower().startswith('data:'):
                    image_src = attributes.get('data-src') or attributes.get('data-lazy-src')
                self._add(image_src, 1)
        elif tag_name == 'script' and attributes.get('type', '').lower() == 'application/ld+json':
            self._json_ld_depth = 1
            self._json_ld_parts = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._json_ld_depth:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag):
        if str(tag or '').lower() != 'script' or not self._json_ld_depth:
            return
        try:
            payload = json.loads(''.join(self._json_ld_parts))
        except (TypeError, ValueError):
            payload = None

        def collect(value):
            if isinstance(value, dict):
                logo = value.get('logo')
                if isinstance(logo, str):
                    self._add(logo, 0)
                elif isinstance(logo, dict):
                    self._add(logo.get('url') or logo.get('contentUrl'), 0)
                for key, item in value.items():
                    if key != 'logo' and isinstance(item, (dict, list)):
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        self._json_ld_depth = 0
        self._json_ld_parts = []


def _safe_read_official_logo_page(official_url):
    parsed = urlsplit(str(official_url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username or invalid_port):
        return '', 'صفحة الموقع الرسمي غير صالحة'
    addresses = _public_host_addresses(parsed.hostname)
    if not addresses:
        return '', 'عنوان الموقع الرسمي غير مسموح'
    try:
        pool, response = _open_pinned_https(parsed, addresses)
    except Exception as exc:
        return '', str(exc)
    try:
        if response.status != 200:
            return '', f'تعذر قراءة صفحة الموقع الرسمي: HTTP {response.status}'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > OFFICIAL_LOGO_PAGE_MAX_BYTES:
                return '', 'صفحة الموقع الرسمي أكبر من الحد المسموح'
        return bytes(content).decode('utf-8', errors='replace'), ''
    finally:
        response.release_conn()
        pool.close()


def _official_logo_candidates(official_url):
    page, _error = _safe_read_official_logo_page(official_url)
    if not page:
        return []
    parser = _OfficialLogoHTMLParser()
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        return []
    candidates = []
    seen = set()
    for _priority, raw_url in sorted(parser.candidates, key=lambda item: item[0]):
        candidate = urljoin(official_url, raw_url)
        parsed = urlsplit(candidate)
        if (parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username
                or not _same_official_host(candidate, official_url)):
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _safe_download_competitor_logo(logo_url, official_url):
    parsed = urlsplit(str(logo_url or '').strip())
    official = urlsplit(str(official_url or '').strip())
    try:
        invalid_port = parsed.port not in (None, 443) or official.port not in (None, 443)
    except ValueError:
        invalid_port = True
    if (parsed.scheme.lower() != 'https' or official.scheme.lower() != 'https'
            or not parsed.hostname or not official.hostname or parsed.username or official.username
            or invalid_port):
        return None, None, None, 'رابط الشعار الرسمي غير صالح'
    if not _same_official_host(logo_url, official_url):
        return None, None, None, 'شعار المنافس خارج الموقع الرسمي'
    addresses = _public_host_addresses(parsed.hostname)
    if not addresses or not _public_host_addresses(official.hostname):
        return None, None, None, 'عنوان موقع الشعار غير مسموح'
    try:
        pool, response = _open_pinned_https(parsed, addresses)
    except Exception as exc:
        return None, None, None, str(exc)
    try:
        if response.status != 200:
            return None, None, None, f'تعذر تنزيل الشعار: HTTP {response.status}'
        mime_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
        extension = COMPETITOR_LOGO_MIMES.get(mime_type)
        try:
            declared = int(response.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > COMPETITOR_LOGO_MAX_BYTES:
            return None, None, None, 'حجم شعار المنافس أكبر من الحد المسموح'
        content = bytearray()
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > COMPETITOR_LOGO_MAX_BYTES:
                return None, None, None, 'حجم شعار المنافس أكبر من الحد المسموح'
        try:
            from PIL import Image, UnidentifiedImageError
            with Image.open(BytesIO(content)) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > 16_000_000:
                    return None, None, None, 'أبعاد شعار المنافس غير صالحة'
                detected = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'), 'WEBP': ('image/webp', '.webp')}.get((image.format or '').upper())
                if not detected:
                    return None, None, None, 'نوع ملف الشعار غير مدعوم'
                mime_type, extension = detected
                image.verify()
        except (UnidentifiedImageError, OSError):
            return None, None, None, 'ملف شعار المنافس غير صالح'
        return bytes(content), mime_type, extension, ''
    finally:
        response.release_conn()
        pool.close()


def _store_imported_competitor_logo(row, draft_id=None):
    logo_url = str((row or {}).get('logo_url') or '').strip()
    official_url = str((row or {}).get('logo_source_url') or (row or {}).get('source_url') or '').strip()
    name = str((row or {}).get('name') or 'competitor').strip()
    if not official_url:
        return row
    if not (row or {}).get('logo_official_verified') and not market_study.official_source_reliability(
            name, (row or {}).get('source'), official_url):
        return row
    content = mime_type = extension = None
    error = ''
    candidates = [logo_url] if logo_url else []
    seen = set()
    for candidate in candidates:
        key = str(candidate or '').strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        content, mime_type, extension, error = _safe_download_competitor_logo(candidate, official_url)
        if content:
            logo_url = candidate
            row['logo_url'] = candidate
            break
    if not content:
        for candidate in _official_logo_candidates(official_url):
            key = str(candidate or '').strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            content, mime_type, extension, error = _safe_download_competitor_logo(candidate, official_url)
            if content:
                logo_url = candidate
                row['logo_url'] = candidate
                break
    if error or not content:
        row['logo_import_warning'] = error or 'تعذر استيراد شعار المنافس'
        return row
    from werkzeug.datastructures import FileStorage
    upload = FileStorage(
        stream=BytesIO(content), filename='competitor-logo' + extension, content_type=mime_type,
    )
    stored = _store_project_upload(
        upload, 'competitor_logo', draft_id=draft_id, project_id=str(row.get('id') or '') or None,
    )
    published = _publish_project_file_as_creative_image(stored['id'])
    row['logo_file_id'] = stored['id']
    row['logo_path'] = published or ('/api/project-files/' + stored['id'])
    row['logo_source_url'] = official_url
    row.pop('logo_import_warning', None)
    return row


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

    document_dir = os.path.join(UPLOADS_DIR, re.sub(r'[^A-Za-z0-9_-]', '', str(g.tenant_id)) or 'public', 'project-documents')
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
    if file_type == 'competitor_logo' and draft_id:
        _record_change('draft', draft_id, 'رفع شعار منافس',
                       [f'رُفع الملف «{result.get("originalName") or "شعار منافس"}»'])
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

    storage_path = _resolve_project_file_storage_path(stored, g.tenant_id)
    if not storage_path:
        tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, str(g.tenant_id)))
        raw_target = os.path.realpath(stored.get('storage_path') or '')
        try:
            inside = os.path.commonpath([tenant_root, raw_target]) == tenant_root
        except ValueError:
            inside = False
        if not inside:
            print(f"[PROJECT FILE] rejected out-of-tenant path for {file_id}")
            return jsonify({'success': False, 'error': 'مسار الملف غير مسموح'}), 403
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


@app.route('/api/project-files/<file_id>', methods=['DELETE'])
@require_permission('create_presentation')
def api_delete_project_file(file_id):
    stored = db.get_project_file(g.tenant_id, str(file_id))
    if not stored:
        return jsonify({'success': False, 'error': 'الملف غير موجود'}), 404
    if stored.get('file_type') != 'competitor_logo':
        return jsonify({'success': False, 'error': 'لا يمكن حذف هذا النوع من الملفات من هنا'}), 400

    storage_path = _resolve_project_file_storage_path(stored, g.tenant_id)
    if not storage_path:
        tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, str(g.tenant_id)))
        raw_target = os.path.realpath(stored.get('storage_path') or '')
        try:
            inside = os.path.commonpath([tenant_root, raw_target]) == tenant_root
        except ValueError:
            inside = False
        if not inside:
            print(f"[PROJECT FILE] rejected delete outside tenant path for {file_id}")
            return jsonify({'success': False, 'error': 'مسار الملف غير مسموح'}), 403
    try:
        if storage_path and os.path.isfile(storage_path):
            os.unlink(storage_path)
    except OSError as error:
        print(f"[PROJECT FILE] could not remove logo file {file_id}: {error}")
    deleted = db.delete_project_file(g.tenant_id, str(file_id))
    return jsonify({'success': bool(deleted), 'fileId': str(file_id)})


@app.route('/api/project-files/<file_id>/publish-image', methods=['POST'])
@require_permission('create_presentation')
def api_publish_project_file_image(file_id):
    """Return a durable URL for an uploaded image so a saved draft can point at it.

    The preview route needs an Authorization header, so the client had to read it into a
    ``blob:`` URL — which dies with the tab. This publishes the same bytes under
    ``/uploads/creative/<tenant>/`` exactly like a generated image.
    """
    url = _publish_project_file_as_creative_image(file_id)
    if not url:
        return jsonify({'success': False, 'error': 'الملف غير متاح أو ليس صورة'}), 404
    return jsonify({'success': True, 'url': url})


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


@app.route('/api/upload/watermark', methods=['POST'])
@require_permission('company_settings')
def api_upload_watermark():
    """Upload the company's watermark as a branding asset separate from its logo."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No filename'}), 400

    try:
        _save_tenant_image(file, 'watermark')
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    relative_path = f'/tenant-assets/{g.tenant_id}/watermark'
    db.update_branding(g.tenant_id, watermark_path=relative_path)
    return jsonify({
        'success': True,
        'watermarkPath': relative_path,
        'branding': db.get_branding(g.tenant_id),
    })


@app.route('/api/upload/watermark', methods=['DELETE'])
@require_permission('company_settings')
def api_delete_watermark():
    """Clear the configured watermark without changing the company logo."""
    for watermark_path in _tenant_image_storage_candidates(g.tenant_id, 'watermark'):
        if not os.path.isfile(watermark_path):
            continue
        try:
            os.unlink(watermark_path)
        except OSError as error:
            print(f'[TENANT IMAGE] could not remove watermark file: {error}')
    db.update_branding(g.tenant_id, watermark_path=None)
    return jsonify({'success': True, 'branding': db.get_branding(g.tenant_id)})


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
    if ext not in {'.ttf', '.otf', '.woff', '.woff2'}:
        return jsonify({'error': 'Invalid font file extension'}), 400
    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', os.path.splitext(file.filename)[0])
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(g.tenant_id)) or 'public'
    font_dir = os.path.join(UPLOADS_DIR, safe_tenant, 'fonts')
    os.makedirs(font_dir, exist_ok=True)
    filename = f'{safe_name}_{script}_{weight}{ext}'
    filepath = os.path.abspath(os.path.join(font_dir, filename))
    if os.path.commonpath([os.path.abspath(font_dir), filepath]) != os.path.abspath(font_dir):
        return jsonify({'error': 'Invalid font filename'}), 400
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
    if ext not in {'.ttf', '.otf', '.woff', '.woff2'}:
        return jsonify({'error': 'Invalid font file extension'}), 400
    safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', os.path.splitext(file.filename)[0])
    safe_tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(g.tenant_id)) or 'public'
    font_dir = os.path.join(UPLOADS_DIR, safe_tenant, 'fonts')
    os.makedirs(font_dir, exist_ok=True)
    filename = f'{safe_name}_{detected["weight"]}{ext}'
    filepath = os.path.abspath(os.path.join(font_dir, filename))
    if os.path.commonpath([os.path.abspath(font_dir), filepath]) != os.path.abspath(font_dir):
        return jsonify({'error': 'Invalid font filename'}), 400
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
    logo_path = _tenant_logo_storage_path(tenant_id)
    tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, tenant_id))
    if logo_path and os.path.commonpath([tenant_root, os.path.realpath(logo_path)]) == tenant_root:
        extension = os.path.splitext(logo_path)[1].lower()
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


@app.route('/tenant-assets/<tenant_id>/watermark')
def serve_tenant_watermark(tenant_id):
    """Serve only an explicitly uploaded watermark; never fall back to a logo."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', str(tenant_id or '')):
        return jsonify({'error': 'Watermark not found'}), 404
    branding = db.get_branding(tenant_id) or {}
    if not str(branding.get('watermark_path') or '').strip():
        return jsonify({'error': 'Watermark not found'}), 404
    watermark_path = _tenant_watermark_storage_path(tenant_id)
    tenant_root = os.path.realpath(os.path.join(UPLOADS_DIR, tenant_id))
    try:
        inside_tenant = bool(watermark_path) and os.path.commonpath(
            [tenant_root, os.path.realpath(watermark_path)]) == tenant_root
    except ValueError:
        inside_tenant = False
    if not inside_tenant:
        return jsonify({'error': 'Watermark not found'}), 404
    extension = os.path.splitext(watermark_path)[1].lower()
    mimetype = 'image/png' if extension == '.png' else 'image/jpeg' if extension in ('.jpg', '.jpeg') else 'image/webp'
    resp = send_file(watermark_path, mimetype=mimetype)
    resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return resp


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

@app.route('/api/admin/tenants', methods=['GET', 'POST'])
@require_admin
def api_admin_tenants():
    """List or create tenant companies."""
    if request.method == 'POST':
        data = request.json or {}
        company_name = (data.get('companyName') or '').strip()
        manager_name = (data.get('accountManagerName') or '').strip()
        email = (data.get('email') or '').strip().lower()
        username = (data.get('username') or '').strip().lower()
        phone = _normalize_phone(data.get('phone'))
        plan = (data.get('plan') or 'free').strip().lower()
        password_mode = data.get('passwordMode') or 'set_link'
        password = data.get('password') or ''
        is_active = bool(data.get('isActive', True))
        send_welcome = bool(data.get('sendWelcomeEmail', True))
        try:
            credit_balance = float(data.get('creditBalance') or 0)
        except (TypeError, ValueError):
            return jsonify({'error': 'Credit balance must be a valid number'}), 400

        if not company_name or not manager_name or not email or not username or not phone:
            return jsonify({'error': 'All company and account fields are required'}), 400
        if len(company_name) > 120 or len(manager_name) > 120:
            return jsonify({'error': 'Company or account manager name is too long'}), 400
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            return jsonify({'error': 'Invalid email address'}), 400
        if not USERNAME_RE.fullmatch(username):
            return jsonify({'error': 'Invalid username'}), 400
        if not PHONE_RE.fullmatch(phone):
            return jsonify({'error': 'Invalid phone number'}), 400
        if plan not in ADMIN_COMPANY_PLANS:
            return jsonify({'error': 'Invalid plan'}), 400
        if credit_balance < 0:
            return jsonify({'error': 'Credit balance cannot be negative'}), 400
        conflict = _identity_conflict(email, username)
        if conflict:
            return jsonify({'error': conflict}), 409
        if password_mode == 'manual':
            password_error = _password_validation_error(password)
            if password_error:
                return jsonify({'error': password_error}), 400
            require_password_change = False
        elif password_mode == 'set_link':
            password = _generate_secure_password()
            require_password_change = True
        else:
            return jsonify({'error': 'Invalid password mode'}), 400

        try:
            tenant_id, user_id = db.create_company_with_admin(
                company_name, manager_name, email, username, phone,
                hash_password(password), plan=plan, credit_balance=credit_balance,
                is_active=is_active, require_password_change=require_password_change
            )
        except db_driver.IntegrityError:
            return jsonify({'error': 'Email or username already registered'}), 409

        setup_token = db.create_password_setup_token(tenant_id, user_id)
        setup_url = _password_setup_url(setup_token)
        email_sent = False
        if send_welcome:
            email_sent = _send_company_welcome_email(
                email, company_name, manager_name, username, setup_url
            )
        tenant = db.get_tenant_by_id(tenant_id)
        return jsonify({
            'success': True,
            'tenant': _company_payload(tenant),
            'setupUrl': setup_url,
            'welcomeEmailSent': email_sent,
        }), 201

    tenants = db.get_all_tenants()
    result = [_company_payload(tenant) for tenant in tenants]
    return jsonify({'success': True, 'tenants': result})


@app.route('/api/admin/tenants/<tenant_id>', methods=['PUT'])
@require_admin
def api_admin_update_tenant(tenant_id):
    """Update a tenant (admin only)."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    data = request.json or {}
    company_fields = {}
    account_fields = {}
    key_map = {
        'companyName': 'company_name',
        'accountManagerName': 'account_manager_name',
        'username': 'username',
        'phone': 'phone',
        'email': 'email',
        'plan': 'plan',
        'creditBalance': 'credit_balance',
        'isActive': 'is_active',
    }
    for input_key, db_key in key_map.items():
        if input_key in data:
            company_fields[db_key] = data[input_key]
    for db_key in ['company_name', 'account_manager_name', 'username', 'phone', 'email',
                   'plan', 'credit_balance', 'is_active']:
        if db_key in data:
            company_fields[db_key] = data[db_key]

    if 'company_name' in company_fields:
        company_fields['company_name'] = str(company_fields['company_name'] or '').strip()
        if not company_fields['company_name'] or len(company_fields['company_name']) > 120:
            return jsonify({'error': 'Invalid company name'}), 400
    if 'account_manager_name' in company_fields:
        company_fields['account_manager_name'] = str(
            company_fields['account_manager_name'] or ''
        ).strip()
        if not company_fields['account_manager_name']:
            return jsonify({'error': 'Account manager name is required'}), 400
    if 'email' in company_fields:
        company_fields['email'] = str(company_fields['email'] or '').strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', company_fields['email']):
            return jsonify({'error': 'Invalid email address'}), 400
    if 'username' in company_fields:
        company_fields['username'] = str(company_fields['username'] or '').strip().lower()
        if not USERNAME_RE.fullmatch(company_fields['username']):
            return jsonify({'error': 'Invalid username'}), 400
    if 'phone' in company_fields:
        company_fields['phone'] = _normalize_phone(company_fields['phone'])
        if not PHONE_RE.fullmatch(company_fields['phone']):
            return jsonify({'error': 'Invalid phone number'}), 400
    if 'plan' in company_fields and company_fields['plan'] not in ADMIN_COMPANY_PLANS:
        return jsonify({'error': 'Invalid plan'}), 400
    if 'credit_balance' in company_fields:
        try:
            company_fields['credit_balance'] = float(company_fields['credit_balance'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Credit balance must be a valid number'}), 400
        if company_fields['credit_balance'] < 0:
            return jsonify({'error': 'Credit balance cannot be negative'}), 400
    if 'is_active' in company_fields:
        company_fields['is_active'] = 1 if company_fields['is_active'] else 0

    email = company_fields.get('email', tenant['email'])
    username = company_fields.get('username', tenant.get('username'))
    if email and username:
        conflict = _identity_conflict(
            email, username, tenant_id=tenant_id, user_id=tenant.get('primary_user_id')
        )
        if conflict:
            return jsonify({'error': conflict}), 409

    for key in ['account_manager_name', 'username', 'phone', 'email', 'is_active']:
        if key in company_fields:
            account_fields[key] = company_fields.pop(key)
    try:
        if company_fields:
            db.update_tenant(tenant_id, **company_fields)
        if account_fields:
            db.sync_primary_company_admin(tenant_id, **account_fields)
        if 'company_name' in company_fields:
            db.update_branding(tenant_id, company_name=company_fields['company_name'])
        primary_user_id = data.get('primaryUserId')
        if primary_user_id and primary_user_id != tenant.get('primary_user_id'):
            if not db.set_primary_company_admin(tenant_id, primary_user_id):
                return jsonify({'error': 'User not found'}), 404
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or username already registered'}), 409
    return jsonify({
        'success': True,
        'tenant': _company_payload(db.get_tenant_by_id(tenant_id)),
    })


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
    branding = db.get_branding(tenant_id)
    counts = db.get_tenant_profile_counts(tenant_id)
    return jsonify({
        'success': True,
        'tenant': _company_payload(tenant),
        'users': users,
        'branding': branding,
        'counts': counts,
    })


@app.route('/api/admin/tenants/<tenant_id>/users', methods=['GET'])
@require_admin
def api_admin_tenant_users(tenant_id):
    """List users of a specific tenant (admin only)."""
    users = db.get_users_by_tenant(tenant_id)
    return jsonify({'success': True, 'users': users})


@app.route('/api/admin/tenants/<tenant_id>/users', methods=['POST'])
@require_admin
def api_admin_add_tenant_user(tenant_id):
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    data = request.json or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    username = (data.get('username') or '').strip().lower()
    phone = _normalize_phone(data.get('phone'))
    role = data.get('role') or 'employee'
    use_setup_link = bool(data.get('useSetupLink', True))
    password = data.get('password') or ''
    if not name or not email or not username or not phone:
        return jsonify({'error': 'All user fields are required'}), 400
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Invalid email address'}), 400
    if not USERNAME_RE.fullmatch(username):
        return jsonify({'error': 'Invalid username'}), 400
    if not PHONE_RE.fullmatch(phone):
        return jsonify({'error': 'Invalid phone number'}), 400
    if role not in {'employee', 'company_admin'}:
        return jsonify({'error': 'Invalid role'}), 400
    conflict = _identity_conflict(email, username)
    if conflict:
        return jsonify({'error': conflict}), 409
    if use_setup_link:
        password = _generate_secure_password()
    else:
        password_error = _password_validation_error(password)
        if password_error:
            return jsonify({'error': password_error}), 400
    try:
        user_id = db.create_user(
            tenant_id, name, email, hash_password(password), role=role,
            username=username, phone=phone, require_password_change=use_setup_link
        )
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or username already registered'}), 409
    setup_url = None
    if use_setup_link:
        setup_url = _password_setup_url(
            db.create_password_setup_token(tenant_id, user_id)
        )
    return jsonify({
        'success': True,
        'user': db.get_user_by_id(user_id),
        'setupUrl': setup_url,
    }), 201


@app.route('/api/admin/tenants/<tenant_id>/users/<user_id>', methods=['PUT', 'DELETE'])
@require_admin
def api_admin_update_tenant_user(tenant_id, user_id):
    tenant = db.get_tenant_by_id(tenant_id)
    user = db.get_user_by_id(user_id)
    if not tenant or not user or user.get('tenant_id') != tenant_id:
        return jsonify({'error': 'User not found'}), 404
    if request.method == 'DELETE':
        if tenant.get('primary_user_id') == user_id:
            return jsonify({'error': 'Primary company admin cannot be deleted'}), 400
        db.delete_user(user_id)
        return jsonify({'success': True})
    data = request.json or {}
    updates = {}
    for key in ['name', 'role', 'is_active']:
        if key in data:
            updates[key] = data[key]
    if 'email' in data:
        updates['email'] = str(data.get('email') or '').strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', updates['email']):
            return jsonify({'error': 'Invalid email address'}), 400
    if 'username' in data:
        updates['username'] = str(data.get('username') or '').strip().lower()
        if not USERNAME_RE.fullmatch(updates['username']):
            return jsonify({'error': 'Invalid username'}), 400
    if 'phone' in data:
        updates['phone'] = _normalize_phone(data.get('phone'))
        if not PHONE_RE.fullmatch(updates['phone']):
            return jsonify({'error': 'Invalid phone number'}), 400
    if updates.get('role') not in {None, 'employee', 'company_admin'}:
        return jsonify({'error': 'Invalid role'}), 400
    email = updates.get('email', user['email'])
    username = updates.get('username', user.get('username'))
    conflict = _identity_conflict(email, username, tenant_id=tenant_id, user_id=user_id)
    if conflict:
        return jsonify({'error': conflict}), 409
    if data.get('password'):
        password_error = _password_validation_error(data['password'])
        if password_error:
            return jsonify({'error': password_error}), 400
        updates['password_hash'] = hash_password(data['password'])
        updates['require_password_change'] = 0
    try:
        db.update_user(user_id, **updates)
        if data.get('isPrimary'):
            db.set_primary_company_admin(tenant_id, user_id)
        elif tenant.get('primary_user_id') == user_id and updates:
            primary_fields = {}
            reverse_mapping = {
                'name': 'account_manager_name',
                'username': 'username',
                'phone': 'phone',
                'email': 'email',
                'password_hash': 'password_hash',
                'require_password_change': 'require_password_change',
                'is_active': 'is_active',
            }
            for key, value in updates.items():
                if key in reverse_mapping:
                    primary_fields[reverse_mapping[key]] = value
            if primary_fields:
                db.sync_primary_company_admin(tenant_id, **primary_fields)
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or username already registered'}), 409
    return jsonify({'success': True, 'user': db.get_user_by_id(user_id)})


@app.route('/api/admin/tenants/<tenant_id>/reset-password', methods=['POST'])
@require_admin
def api_admin_reset_tenant_password(tenant_id):
    """Reset a tenant's password (admin only)."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    data = request.json or {}
    new_password = data.get('password', '')
    if data.get('useSetupLink') or not new_password:
        user_id = tenant.get('primary_user_id')
        if not user_id:
            return jsonify({'error': 'Primary company admin is not configured'}), 400
        raw_token = db.create_password_setup_token(tenant_id, user_id)
        db.sync_primary_company_admin(tenant_id, require_password_change=1)
        return jsonify({
            'success': True,
            'setupUrl': _password_setup_url(raw_token),
        })
    password_error = _password_validation_error(new_password)
    if password_error:
        return jsonify({'error': password_error}), 400
    db.sync_primary_company_admin(
        tenant_id,
        password_hash=hash_password(new_password),
        require_password_change=0,
    )
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
            generation_id, training_vision_usage = _extract_openrouter_usage(vdata)
            _record_ai_usage(_usage_ctx('training_chat', tenant_id=g.tenant_id), LUNA_TEXT_MODEL,
                             'ok' if resp.status_code < 400 and 'error' not in vdata else 'error',
                             training_vision_usage, generation_id)
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


def _agent_attachment_context(data):
    """Read what the admin attached to a chat message: an image to look at, or a PDF to read.

    Returns a prompt note and the image references for the model. Reading the file is the point:
    the agent is asked to act on documents, and it cannot act on a file it never received.
    """
    notes = []
    images = []
    image_uri = str(data.get('attachedImage') or '').strip()
    if image_uri.startswith('data:image/'):
        images.append({'data_uri': image_uri})
        notes.append('أرفق المستخدم صورة مع رسالته. انظر إليها قبل الرد.')

    document = data.get('attachedFile') if isinstance(data.get('attachedFile'), dict) else {}
    name = str(document.get('name') or 'ملف').strip()
    document_uri = str(document.get('dataUri') or '').strip()
    if document_uri.startswith('data:application/pdf'):
        try:
            payload = base64.b64decode(document_uri.split(',', 1)[1])
            import fitz
            with fitz.open(stream=payload, filetype='pdf') as pdf:
                pages = [page.get_text() for page in pdf]
            text = '\n'.join(pages).strip()
            if text:
                notes.append(f'## محتوى الملف المرفق «{name}» ({len(pages)} صفحة)\n'
                             f'{text[:20000]}')
            else:
                notes.append(f'الملف المرفق «{name}» لا يحتوي نصًا قابلًا للقراءة (صور ممسوحة).')
        except Exception as exc:
            print(f'[SUPER-AGENT] Could not read the attached PDF: {exc}')
            notes.append(f'تعذر قراءة الملف المرفق «{name}».')
    elif document_uri.startswith('data:text/'):
        try:
            payload = base64.b64decode(document_uri.split(',', 1)[1]).decode('utf-8', 'replace')
            notes.append(f'## محتوى الملف المرفق «{name}»\n{payload[:20000]}')
        except Exception as exc:
            print(f'[SUPER-AGENT] Could not read the attached text file: {exc}')

    return ('\n\n'.join(notes), images)


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

    # A file the admin attached to this message. Images used to be analysed by a separate endpoint
    # and stored as training text, so the agent answering the message never saw them, and a PDF
    # could not be attached at all.
    attachment_note, attachment_images = _agent_attachment_context(data)

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
{{"tool": "update_branding", "params": {{"min_slides": N, "default_slide_count": N, "lock_slide_count": 0, "moodboard_count": N}}}}
```
ملاحظة: لا يوجد حد أعلى لعدد الشرائح؛ `min_slides` هو الحد الأدنى فقط والعدد النهائي يتبع حجم محتوى المشروع. لقفل العدد على رقم بالضبط استخدم `lock_slide_count: 1` مع `default_slide_count`.

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
عند طلب إضافة شعار الشركة أو شعار المشروع إلى شريحة، استخدم الشعار الموجود فعلياً في الهوية أو بيانات المشروع:
`##LOGO##` لشعار الشركة و`##PROJECT_LOGO##` لشعار المشروع. لا تكتب اسم الشعار كنص، ولا تستخدم رابطاً خارجياً أو صورة بديلة.
شعار جهة من فريق العمل ليس شعار الشركة: استخدم الرمز `##TEAM_LOGO_N##`، حيث يطابق `N` ترتيب الجهة في قائمة فريق العمل الحالية، ولا تستبدله بـ `##LOGO##`.
مكان شعار الشركة الافتراضي هو الهيدر المعتمد للشريحة، ويجب الحفاظ على الشعار الموجود إذا كان الهيدر يحتويه.

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

### 27. فريق العمل (مكتبة الشركة المشتركة):
```action
{{"tool": "list_team"}}
```
```action
{{"tool": "add_team_entity", "params": {{"name": "...", "role": "...", "brief": "...", "experience_years": "...", "notable_projects": "..."}}}}
```
```action
{{"tool": "update_team_entity", "params": {{"name": "الاسم الحالي أو معرفه", "updates": {{"role": "...", "brief": "...", "experience_years": "...", "notable_projects": "..."}}}}}}
```
```action
{{"tool": "delete_team_entity", "params": {{"name": "الاسم أو المعرف"}}}}
```
- المكتبة مشتركة بين كل ملفات المشاريع، فأي تعديل هنا يظهر في كل عرض جديد.
- الاستبعاد لملف واحد فقط يتم من صفحة فريق العمل داخل المشروع، لا من هنا.

### 28. قواعد التوليد الخاصة بالشركة (تُضاف إلى برومبت توليد الشرائح):
```action
{{"tool": "get_generation_rules"}}
```
```action
{{"tool": "set_generation_rules", "params": {{"rules": "نص القواعد الملزمة لتوليد الشرائح"}}}}
```
- هذه القواعد تُرسل حرفيًا مع كل توليد شريحة وكل تعديل تصميم، فوق قواعد التصميم الأساسية.
- اكتبها أوامر واضحة وقابلة للتنفيذ (ترتيب المحاور، ما يُعرض وما لا يُعرض، صيغة الأرقام، لغة العناوين).
- ممنوع أن تخالف قواعد المنصة الثابتة: ممنوع اختراع معلومة، وممنوع الأيقونات والإيموجي، والأرقام تُنقل كما هي.
- استخدم set_generation_rules لتعديل «برومبت التوليد»؛ لا توجد طريقة أخرى لتغييره.

### 29. سؤال المستخدم عند عدم الوضوح:
```action
{{"tool": "ask", "params": {{"question": "سؤال عربي واحد قصير"}}}}
```

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
8. **اسأل بدل أن تخمّن:** إذا كان الطلب غامضًا أو يقبل تنفيذين مختلفين، أو لم تعرف الحقل أو القسم أو
   الجهة أو الموظف المقصود، أو كان التنفيذ سيحذف أو يستبدل شيئًا قائمًا ولست متأكدًا أنه مقصود، أو
   أرفق المستخدم ملفًا دون أن يوضح المطلوب منه — أعد `ask` بسؤال واحد محدد ولا تنفّذ أي action آخر
   في نفس الرد. تنفيذ خاطئ على إعدادات الشركة أسوأ من سؤال واحد.
9. **الحقول الأصلية للنظام لا تُحذف.** `delete_field` تعمل على الحقول المضافة فقط؛ الحقل الأصلي
   يُعطَّل بـ `update_field` مع `is_active: 0` ويمكن إعادة تفعيله. لا تَعِد المستخدم بحذف حقل أصلي.
10. عند طلب تعديل «شكل العرض» أو «قواعد التوليد» أو «برومبت التوليد» استخدم `set_generation_rules`،
   وعند طلب تعديل الألوان والخطوط وأبعاد الشريحة استخدم `update_branding`. لا تخلط بينهما.
11. إذا أرفق المستخدم ملفًا أو صورة: اقرأها فعلًا واستخرج منها ما يخص الطلب، واذكر في ردك ما فهمته
   منها قبل التنفيذ. إن كان الملف غير مقروء فقل ذلك بصراحة ولا تخمّن محتواه.
"""

    if attachment_note:
        system_prompt += f'\n\n## ملف أرفقه المستخدم مع رسالته\n{attachment_note}'

    user_prompt = (context + '\n\nالمستخدم: ' + message + '\n\nوكيل الإدارة:') if context else ('المستخدم: ' + message + '\n\nوكيل الإدارة:')

    try:
        # This agent changes the company's settings, so it runs on the strong model with real
        # reasoning instead of the fast text model, and with room to plan several tool calls.
        response = call_zai_chat(system_prompt, user_prompt, max_tokens=6000,
                                 model=SLIDE_TEXT_MODEL, reasoning_effort='medium',
                                 image_references=attachment_images or None,
                                 usage_ctx=_usage_ctx('training_chat', data))
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
                    # Only the minimum binds the planner; the upper end is open, so a requested
                    # number is stored as the default and the floor, never as a ceiling.
                    parsed_actions.append({
                        'tool': 'update_branding',
                        'params': {'default_slide_count': num, 'min_slides': num}
                    })
                    reply = f"تم التعديل!  عدد الشرائح الافتراضي تم تغييره إلى **{num} شريحة**، وهو الحد الأدنى أيضًا. لا يوجد حد أعلى: العدد النهائي يتبع حجم محتوى المشروع، ولقفله على {num} بالضبط فعّل «قفل عدد الشرائح»."
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

    # A question is the whole answer: nothing else runs in that turn, so an ambiguous request cannot
    # half-apply while the agent is still asking what was meant.
    question = next((action for action in parsed_actions
                     if isinstance(action, dict) and action.get('tool') == 'ask'), None)
    if question:
        parsed_actions = [question]

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

    if question:
        asked = next((item.get('message') for item in actions_executed
                      if isinstance(item, dict) and item.get('status') == 'question'), '')
        if asked and asked not in clean_reply:
            clean_reply = (clean_reply + '\n\n' + asked).strip() if clean_reply else asked
    if not clean_reply and actions_executed:
        clean_reply = ' تم تنفيذ الإجراء بنجاح.'

    return jsonify({
        'success': True,
        'reply': clean_reply,
        'actions': actions_executed,
        'awaitingAnswer': bool(question),
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

    # The team library and the company generation rules are things the agent can change, so it has
    # to see their current state instead of guessing that they are empty.
    team_entities = db.get_team_entities(tenant_id) or []
    team_lines = [f"  • {item.get('name')} — {item.get('role') or 'بدون دور محدد'}"
                  f"{(' — خبرة ' + str(item.get('experienceYears'))) if item.get('experienceYears') else ''}"
                  for item in team_entities[:20]]
    generation_rules = str(branding.get('generation_rules') or '').strip()

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
- الحد الأقصى: {f"مقفل على {branding.get('default_slide_count', 16)} شريحة بالضبط" if branding.get('lock_slide_count') else 'لا يوجد حد أعلى — العدد يتبع حجم المحتوى'}
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

###  مكتبة فريق العمل ({len(team_entities)} جهة):
{chr(10).join(team_lines) if team_lines else '  لا توجد جهات في المكتبة.'}

###  إعدادات الخرائط:
- نوع الخريطة الافتراضي: {branding.get('default_map_type', 'satellite')}
- نظرة عامة/معالم/طرق/نطاق: {branding.get('map_style_overview', 'satellite')} / {branding.get('map_style_landmarks', 'satellite')} / {branding.get('map_style_access', 'satellite')} / {branding.get('map_style_catchment', 'satellite')}
- بوصلة: {'مفعلة' if branding.get('draw_compass') else 'معطلة'} — خريطة مصغّرة: {'مفعلة' if branding.get('draw_inset') else 'معطلة'}

###  قواعد التوليد الخاصة بالشركة (تُرسل مع كل توليد شريحة):
{generation_rules if generation_rules else '  لا توجد قواعد مخصصة — التوليد يتبع قواعد المنصة فقط.'}
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
    slide_div_re = re.compile(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\']', re.IGNORECASE)
    for index, slide in enumerate(slides):
        html = slide.get('html') if isinstance(slide, dict) else ''
        if not isinstance(html, str) or not html.strip():
            errors.append({'slide_index': index, 'message': 'محتوى الشريحة فارغ'})
            continue
        matches = slide_div_re.findall(html)
        if len(matches) != 1:
            if html.count('class="slide"') == 1 or html.count("class='slide'") == 1:
                continue
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
                # Map appearance is a company setting like any other; it was in the database and in
                # db.update_branding, but the agent could not reach it.
                'default_map_type', 'map_style_overview', 'map_style_landmarks',
                'map_style_access', 'map_style_catchment', 'draw_compass', 'draw_inset',
                'lock_slide_count',
            }
            updates = {}
            for k, v in params.items():
                if k in allowed_keys:
                    # Cast integers for boolean/numeric fields
                    if k in ('header_enabled', 'footer_enabled', 'moodboard_enabled',
                             'cover_image_enabled', 'draw_compass', 'draw_inset', 'lock_slide_count'):
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

        # ── Team library ──────────────────────────────────────────────
        # The company team is shared by every project file, and the agent had no way to touch it
        # although the database functions and the REST endpoints already existed.
        elif tool == 'list_team':
            entities = db.get_team_entities(tenant_id) or []
            result['data'] = [{
                'id': item.get('id'),
                'name': item.get('name'),
                'role': item.get('role'),
                'experienceYears': item.get('experienceYears'),
            } for item in entities]
            result['message'] = f'عدد جهات فريق العمل: {len(entities)}'

        elif tool == 'add_team_entity':
            name = str(params.get('name') or params.get('entity_name') or '').strip()
            if not name:
                result['status'] = 'error'
                result['message'] = 'اسم الجهة مطلوب'
            else:
                entity_id = db.create_team_entity(
                    tenant_id, name,
                    role=str(params.get('role') or '').strip() or None,
                    brief=str(params.get('brief') or '').strip(),
                    experience_years=params.get('experience_years') or params.get('experienceYears'),
                    notable_projects=params.get('notable_projects') or params.get('notableProjects'),
                )
                db.log_ai_rule_change(tenant_id, 'agent_team', 'add_team_entity', None, name, risk_level='yellow')
                result['data'] = {'id': entity_id, 'name': name}
                result['message'] = f'تمت إضافة «{name}» إلى مكتبة فريق العمل'

        elif tool in ('update_team_entity', 'delete_team_entity'):
            query = str(params.get('name') or params.get('entity_id') or params.get('id') or '').strip()
            entities = db.get_team_entities(tenant_id) or []
            target = next((item for item in entities if str(item.get('id')) == query), None)
            if not target:
                normalized = query.casefold()
                target = next((item for item in entities
                               if str(item.get('name') or '').strip().casefold() == normalized), None)
            if not target:
                result['status'] = 'error'
                result['message'] = f'الجهة «{query}» غير موجودة في مكتبة فريق العمل'
            elif tool == 'delete_team_entity':
                db.delete_team_entity(tenant_id, target['id'])
                db.log_ai_rule_change(tenant_id, 'agent_team', 'delete_team_entity', target.get('name'), None, risk_level='red')
                result['message'] = f'تم حذف «{target.get("name")}» من مكتبة فريق العمل'
            else:
                updates = params.get('updates') if isinstance(params.get('updates'), dict) else {}
                key_map = {
                    'role': 'role', 'brief': 'brief', 'sort_order': 'sort_order',
                    'experience_years': 'experience_years', 'experienceYears': 'experience_years',
                    'notable_projects': 'notable_projects', 'notableProjects': 'notable_projects',
                }
                fields = {key_map[key]: value for key, value in updates.items() if key in key_map}
                if not fields:
                    result['status'] = 'no_changes'
                    result['message'] = 'لم يتم تحديد بيانات صالحة للتعديل'
                else:
                    db.update_team_entity(tenant_id, target['id'], **fields)
                    db.log_ai_rule_change(tenant_id, 'agent_team', f'update_{target.get("name")}',
                                          str({k: target.get(k) for k in fields}), str(fields), risk_level='yellow')
                    result['changes'] = fields
                    result['message'] = f'تم تحديث بيانات «{target.get("name")}»'

        # ── Generation rules that ride with every slide prompt ────────
        elif tool == 'get_generation_rules':
            rules = (db.get_branding(tenant_id) or {}).get('generation_rules') or ''
            result['data'] = {'rules': rules}
            result['message'] = ('قواعد التوليد الحالية:\n' + rules) if rules else 'لا توجد قواعد توليد مخصصة بعد'

        elif tool == 'set_generation_rules':
            rules = str(params.get('rules') or params.get('text') or '').strip()
            old_rules = (db.get_branding(tenant_id) or {}).get('generation_rules') or ''
            db.update_branding(tenant_id, generation_rules=rules[:8000])
            db.log_ai_rule_change(tenant_id, 'agent_generation_rules', 'set_generation_rules',
                                  old_rules[:500] or None, rules[:500] or None, risk_level='yellow')
            result['changes'] = {'generation_rules': {'old': old_rules, 'new': rules}}
            result['message'] = 'تم تحديث قواعد التوليد الخاصة بالشركة' if rules else 'تم إلغاء قواعد التوليد المخصصة'

        # ── Ask instead of guessing ───────────────────────────────────
        elif tool == 'ask':
            result['status'] = 'question'
            result['message'] = str(params.get('question') or '').strip() or 'وضّح المطلوب.'

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
                # Workspace editing used to stop at the raw model HTML. That bypassed the
                # generation finalizer, so a requested company/project logo stayed as a token,
                # or the managed header was rebuilt without the project's logo. Use the same
                # project-aware finalization path as normal generation before returning the slide.
                project_data = workspace.get('projectData') if isinstance(workspace.get('projectData'), dict) else {}
                project_data = dict(project_data)
                creative_images = workspace.get('creativeImages') or workspace.get('images') or {}
                if not isinstance(creative_images, dict):
                    creative_images = {}
                _prepare_generation_logo_context(project_data, branding, tenant_id)
                creative_images = _augment_generation_images(creative_images, project_data, tenant_id)
                team_logo_lines = []
                for team_index, member in enumerate(creative_images.get('team_members') or [], 1):
                    if not isinstance(member, dict):
                        continue
                    name = str(member.get('name') or f'الجهة {team_index}').strip()
                    role = str(member.get('role') or '').strip()
                    token = f'##TEAM_LOGO_{team_index}##'
                    if member.get('logo'):
                        team_logo_lines.append(
                            f'- {name}' + (f' — {role}' if role else '')
                            + f': الشعار متوفر ويجب استخدام {token} عند طلب شعار هذه الجهة.'
                        )
                    else:
                        team_logo_lines.append(
                            f'- {name}' + (f' — {role}' if role else '')
                            + ': لا يوجد شعار مرفوع لهذه الجهة؛ لا تنشئ بديلاً.'
                        )
                team_logo_context = (
                    '\n'.join(team_logo_lines)
                    if team_logo_lines else 'لا توجد شعارات جهات فريق عمل متاحة في مساحة هذا المشروع.'
                )
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

قواعد الشعارات:
- شعار الشركة المعتمد يُستخدم بالرمز `##LOGO##` فقط، وتقوم المنظومة باستبداله تلقائياً بالشعار المرفوع للشركة.
- شعار المشروع يُستخدم بالرمز `##PROJECT_LOGO##` فقط عند توفره، ولا تستبدله بشعار الشركة.
- شعار جهة فريق العمل يُستخدم بالرمز `##TEAM_LOGO_N##` حسب ترتيب الجهة في القائمة التالية، ولا تستخدم `##LOGO##` له:
{team_logo_context}
- عند طلب إضافة شعار، ضعه في موضع الهوية المخصص داخل الهيدر أو الموضع الذي طلبه المستخدم، مع الحفاظ على أبعاده وتباينه.
- لا تكتب اسم الشعار كنص ولا تنشئ رابطاً خارجياً ولا تستخدم صورة بديلة.

عنوان الشريحة: {slide.get('title', '')}
الطلب: {instruction}
HTML الحالي:
{current_html}"""
                    response = call_zai_chat(edit_prompt, instruction, max_tokens=6000, usage_ctx=_usage_ctx('training_chat', workspace, tenant_id=tenant_id))
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
                    html = (parsed.get('html') or '') if isinstance(parsed, dict) else ''
                    if not html and isinstance(parsed, str):
                        html = parsed
                    if not html:
                        match_slide = re.search(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\'][\s\S]*?</div>\s*$', raw, re.IGNORECASE)
                        if match_slide:
                            html = match_slide.group(0)
                    matches = re.findall(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\']', html or '', re.IGNORECASE)
                    if not isinstance(html, str) or (len(matches) != 1 and html.count('class="slide"') != 1 and html.count("class='slide'") != 1):
                        result['status'] = 'error'
                        result['message'] = f'فشل التحقق من HTML للشريحة {index + 1}; لم يتم حفظ التعديل'
                        break
                    slide['html'] = slide_engine.finalize_slide_html(
                        html,
                        slide.get('type') or 'content',
                        project_data,
                        branding,
                        creative_images=creative_images,
                        tenant_id=tenant_id,
                        slide_num=index + 1,
                        slide_title=slide.get('title', ''),
                        total_slides=len(slides),
                        content_source=slide.get('content_source'),
                        allow_all_maps=True,
                    )
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
                plan_prompt = slide_engine.build_slide_plan_prompt(
                    project_data, plan_branding, tenant_id=tenant_id)
                if training_context:
                    plan_prompt = f"## بيانات خاصة بالشركة\n{training_context}\n\n---\n\n{plan_prompt}"
                plan = None
                last_plan_err = None
                for _attempt in range(3):
                    try:
                        plan_resp = call_zai_chat_parallel(
                            "أنت خبير في تحليل المحتوى وتوزيعه على شرائح العروض التقديمية الاستثمارية.",
                            plan_prompt,
                            max_tokens=6000,
                            attempts=2,
                            timeout=45,
                            model=SLIDE_TEXT_MODEL,
                            usage_ctx=_usage_ctx('training_chat', tenant_id=tenant_id)
                        )
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
            slide_plan = slide_engine.normalize_market_section_plan(slide_plan, project_data) or slide_plan
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
                _prepare_generation_logo_context(project_data, branding, tenant_id)
                training_context = db.get_training_context(tenant_id) or ''
                def call_glm_fn(sys_prompt, user_msg, max_tokens=6000):
                    if training_context:
                        sys_prompt = f"{sys_prompt}\n\n## بيانات خاصة بالشركة\n{training_context}"
                    return call_zai_chat_parallel(sys_prompt, user_msg, max_tokens=max_tokens, attempts=2, usage_ctx=_usage_ctx('training_chat', workspace, tenant_id=tenant_id))
                htmls = generate_all_slides(
                    slide_plan, project_data, branding, _get_images_info(images, project_data), call_glm_fn,
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
                project_data = workspace.get('projectData') if isinstance(workspace.get('projectData'), dict) else {}
                slides = slide_engine.renumber_presentation_slides(
                    slides, branding=db.get_branding(tenant_id), project_data=project_data,
                    tenant_id=tenant_id,
                    creative_images=_presentation_creative_images(project_data, tenant_id),
                )
                pres_id = workspace.get('presentationId')
                existing = db.get_presentation(pres_id, tenant_id=tenant_id) if pres_id else None
                if existing:
                    db.save_presentation_version(pres_id, None, 'Super Agent', slides, action='agent_save')
                    db.update_presentation(pres_id, title=title, project_data=project_data, slides_data=slides, slide_count=len(slides), status='edited')
                else:
                    pres_id = db.create_presentation(tenant_id, title, project_data, slides, len(slides))
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
    _record_change('presentation', pres_id, 'طلب تعميد العرض', ['أُرسل العرض للمراجعة'])
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
    approval = db.get_approval(approval_id, g.tenant_id)
    if not approval:
        return jsonify({'error': 'Approval not found'}), 404
    result = db.review_approval(approval_id, g.tenant_id, status, g.user_id, g.user_name or 'Admin', note)
    if not result:
        return jsonify({'error': 'Approval not found'}), 404
    action = 'اعتماد العرض' if status == 'approved' else 'إعادة العرض للتعديل'
    _record_change('presentation', approval['presentation_id'], action,
                   [str(note).strip()] if str(note or '').strip() else [action])
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
    """Serve the SPA shell for bookmarkable tenant workspace pages (legacy prefix)."""
    return index()


@app.route('/superadmin', methods=['GET'])
@app.route('/superadmin/<path:page>')
def superadmin_app_page(page=''):
    """Serve the SPA shell for the super-admin workspace (role guard runs client-side)."""
    return index()


@app.route('/c/<slug>', methods=['GET'])
@app.route('/c/<slug>/<path:page>')
def company_app_page(slug='', page=''):
    """Serve the SPA shell for a company workspace; slug mismatch redirects client-side."""
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
        return send_from_directory(maps_dir, path, max_age=3600)
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
    return send_from_directory(creative_dir, safe_filename, max_age=86400)


@app.route('/uploads/<path:path>')
def static_uploads(path):
    """Serve map images or static presentation assets."""
    maps_dir = os.path.join(UPLOADS_DIR, 'maps')
    filename = os.path.basename(path)
    possible_map = os.path.join(maps_dir, filename)
    if os.path.isfile(possible_map):
        return send_from_directory(maps_dir, filename, max_age=3600)
    return jsonify({'error': 'Not found'}), 404

APP_STARTED_AT = datetime.now(timezone.utc).isoformat()
_BUILD_COMMIT = None


def _build_commit():
    """The commit the running code came from, read once."""
    global _BUILD_COMMIT
    if _BUILD_COMMIT is None:
        try:
            _BUILD_COMMIT = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=os.path.dirname(os.path.abspath(__file__)),
                stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        except Exception:
            metadata = _read_deployment_metadata()
            deployed = metadata.get('deployed_commit') or metadata.get('commit')
            _BUILD_COMMIT = str(os.environ.get('DEPLOY_COMMIT') or deployed or 'unknown')[:7]
    return _BUILD_COMMIT


BUILD_FINGERPRINT_FILES = ('app.py', 'index.html', 'slide_engine.py', 'design_templates.py',
                           'generate_pdf_from_preview.py', 'db.py')


def _build_fingerprint():
    """A hash per source file, so the live code can be compared with a checkout.

    The commit alone is not enough: the deploy checks the tree out without a `.git` beside it, so
    `git rev-parse` on the server answers nothing and «هل نزل الإصلاح؟» stayed unanswered.
    """
    fingerprint = {}
    root = os.path.dirname(os.path.abspath(__file__))
    for name in BUILD_FINGERPRINT_FILES:
        path = os.path.join(root, name)
        try:
            with open(path, 'rb') as source:
                # Line endings are normalised: a Windows checkout is CRLF and the server is LF, so
                # the raw hash reported a difference where the code was identical.
                data = source.read().replace(b'\r\n', b'\n')
            fingerprint[name] = hashlib.sha256(data).hexdigest()[:12]
        except OSError:
            fingerprint[name] = 'missing'
    return fingerprint


@app.route('/api/build', methods=['GET'])
def api_build():
    """Which build is actually live.

    «هل نزل الإصلاح؟» had no answer but guessing: the frontend could be checked by fetching the
    page, and a server-side fix could not be checked at all.
    """
    return jsonify({'commit': _build_commit(), 'startedAt': APP_STARTED_AT,
                    'sources': _build_fingerprint()})


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
    
    deploy_script = '/home/demos/proposal-generator/deploy.sh'
    if not os.path.exists(deploy_script):
        deploy_script = os.path.join(os.path.dirname(__file__), 'deploy.sh')

    if os.path.exists(deploy_script):
        try:
            import subprocess
            command = ['bash', deploy_script]
            if requested_commit:
                command.append(str(requested_commit))
            
            deploy_log_path = '/home/demos/proposal-generator/deploy.log'
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


@app.route('/api/deploy-webhook-staging', methods=['GET', 'POST'])
def deploy_webhook_staging():
    """Staging counterpart of deploy_webhook: deploys origin/lab into the
    separate proposal-generator-staging directory. Production paths are never
    touched here, so lab experiments cannot overwrite client data."""
    env_secret = os.environ.get('DEPLOY_WEBHOOK_SECRET_STAGING') or os.environ.get('DEPLOY_WEBHOOK_SECRET')
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

    deploy_script = '/home/demos/proposal-generator-staging/deploy-staging.sh'
    if not os.path.exists(deploy_script):
        deploy_script = os.path.join(os.path.dirname(__file__), 'deploy-staging.sh')

    if os.path.exists(deploy_script):
        try:
            import subprocess
            command = ['bash', deploy_script]
            if requested_commit:
                command.append(str(requested_commit))

            deploy_log_path = '/home/demos/proposal-generator-staging/deploy.log'
            if not os.path.exists(os.path.dirname(deploy_log_path)):
                deploy_log_path = os.path.join(os.path.dirname(__file__), 'deploy-staging.log')

            log_fh = None
            try:
                log_fh = open(deploy_log_path, 'a', encoding='utf-8')
                log_fh.write(f"\n--- Staging deployment triggered at {datetime.now().isoformat()} for commit {requested_commit or 'latest'} ---\n")
                log_fh.flush()
            except OSError:
                log_fh = None

            popen_kwargs = {'start_new_session': True}
            if log_fh is not None:
                popen_kwargs['stdout'] = log_fh
                popen_kwargs['stderr'] = subprocess.STDOUT

            subprocess.Popen(command, **popen_kwargs)
            return jsonify({'status': 'Staging deployment triggered successfully',
                            'target': 'staging',
                            'expected_commit': requested_commit,
                            'timestamp': datetime.now().isoformat()}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'deploy-staging.sh not found'}), 404


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


def _deployed_vision_status():
    """What the deployment recorded about the slide renderer, including the install log tail."""
    for directory in ('/home/demos/proposal-generator', os.path.dirname(__file__)):
        path = os.path.join(directory, '.vision_status')
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8') as handle:
                status = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(status, dict):
            return {
                'available': bool(status.get('available')),
                'error': str(status.get('error') or '')[:400],
                'installLog': str(status.get('installLog') or '')[:600],
                'source': 'deploy',
            }
    return None


def _slide_vision_probe(force=False):
    """Whether this host can render a slide to an image at all.

    `deploy.sh` installs Chromium best-effort and logs a failure to /tmp, and a missing snapshot
    only ever reached the server log, so nobody could tell whether the designer was editing with
    vision or blind. The probe is cached, and every real edit records its outcome here.
    """
    if _SLIDE_VISION_STATE and not force:
        return dict(_SLIDE_VISION_STATE)
    state = {'available': False, 'error': '', 'source': 'probe'}
    try:
        import generate_pdf_from_preview as renderer
        state['available'] = bool(renderer.render_slide_to_image_base64(
            '<div class="slide" style="width:1280px;height:720px;">فحص</div>'))
        if not state['available']:
            state['error'] = getattr(renderer, 'LAST_VISION_ERROR', '') or 'renderer_returned_nothing'
    except Exception as exc:
        state['error'] = renderer.short_browser_error(exc)
    _record_slide_vision_state(state['available'], state['error'], source='probe')
    return dict(_SLIDE_VISION_STATE)


@app.route('/health')
def health():
    metadata = _read_deployment_metadata()
    if request.args.get('vision'):
        _slide_vision_probe(force=True)
    return jsonify({
        'status': 'ok',
        'slide_vision': dict(_SLIDE_VISION_STATE) or _deployed_vision_status(),
        'commit': metadata.get('commit', 'unknown'),
        'deployed_commit': metadata.get('deployed_commit', 'unknown'),
        'deployed_at': metadata.get('deployed_at'),
        'deployment_source': metadata.get('source'),
        'map_label_font': os.path.basename(maps_service.bundled_arabic_overlay_font_path() or ''),
        'model': GLM_MODEL,
        'image_model': IMAGE_MODEL,
    })

@app.route('/preview')
def preview():
    return send_from_directory(os.path.dirname(__file__), 'preview.html')

# Install queued designer-chat execution and deterministic reliability handlers.
designer_chat_reliability.install(app, globals())

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
