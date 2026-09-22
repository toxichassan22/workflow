import os
import sys
import glob
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
import contextlib
import copy
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, send_from_directory, g, current_app, Response, has_request_context, has_app_context, redirect
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

import db
import auth
import maps_service
import market_study
import executive_content
import population_service
import slide_engine
import change_tracking
import presentation_assets
import designer_chat_reliability
import designer_chat_targets
import designer_chat_colors
import designer_chat_context
import regulation_digest
from auth import (require_auth, require_admin, require_company_admin, require_permission,
                  hash_password, verify_password, create_token, decode_token,
                  _load_token_user, _session_state_error, _is_platform_admin_session)
from design_templates import get_all_templates, get_template, apply_template_colors, build_design_rules, extract_slide_elements, build_font_css

app = Flask(__name__, static_folder=None)
# Apache proxies public traffic to gunicorn on 127.0.0.1, so without this the
# app sees the internal host (127.0.0.1:800x) instead of lab.landloom.ai.
# Trust the proxy headers for host/proto only; the proxy itself is local.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
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
        # Draft responses run to several MB of JSON; on the shared host the CPU
        # time of level 6 is the bottleneck, while level 1 keeps ~90% of the
        # compression ratio at a fraction of the cost.
        response.set_data(_gzip.compress(body, 1 if len(body) > 256 * 1024 else 6))
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
    chunk_dir = _body_chunk_dir(upload_id)
    if chunk_dir is None:
        # ISS-016: the reference only resolves inside the caller's own
        # tenant/user namespace — a foreign or anonymous upload id finds
        # nothing and cannot consume another caller's staged parts.
        return jsonify({'error': 'Invalid chunked body reference'}), 400
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


def _body_chunk_namespace():
    """ISS-016: ``(tenant_id, user_scope)`` naming the caller's chunk space.

    Works both inside a ``@require_auth`` view (``g`` populated) and inside the
    ``before_request`` reassembly hook (token decoded straight from the
    header). Primary-admin user tokens normalize to the tenant session
    (ISS-002), so their chunks share the tenant namespace — matching the
    identity the rest of the request will run under.
    """
    payload = getattr(g, 'token_payload', None)
    if payload is None:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None, None
        payload = decode_token(auth_header[7:])
    if not payload:
        return None, None
    tenant_id = payload.get('sub')
    user_id = payload.get('user_id')
    scope = 'tenant'
    if user_id:
        tenant = getattr(g, 'tenant', None) or db.get_tenant_by_id(tenant_id)
        if not (tenant and db.is_primary_company_admin(tenant['id'], user_id)):
            scope = 'u' + re.sub(r'[^A-Za-z0-9_-]', '', str(user_id))
    return tenant_id, scope


def _body_chunk_dir(upload_id):
    """ISS-016: the caller's own ``.body_chunks/<tenant>/<scope>/<id>`` dir."""
    tenant_id, scope = _body_chunk_namespace()
    if not tenant_id or not scope:
        return None
    tenant = re.sub(r'[^A-Za-z0-9_-]', '', str(tenant_id))
    if not tenant:
        return None
    return os.path.join(UPLOADS_DIR, '.body_chunks', tenant, scope, upload_id)


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
    chunk_dir = _body_chunk_dir(upload_id)
    if chunk_dir is None:
        return jsonify({'error': 'Invalid upload id'}), 400
    chunk_dir = os.path.abspath(chunk_dir)
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
    # Best-effort sweep of stale chunk dirs (>15 min), two levels down:
    # .body_chunks/<tenant>/<scope>/<upload_id>
    try:
        now = time.time()
        for tenant_dir in os.listdir(chunk_root):
            tenant_path = os.path.join(chunk_root, tenant_dir)
            if not os.path.isdir(tenant_path):
                continue
            for scope_dir in os.listdir(tenant_path):
                scope_path = os.path.join(tenant_path, scope_dir)
                if not os.path.isdir(scope_path):
                    continue
                for name in os.listdir(scope_path):
                    path = os.path.join(scope_path, name)
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
# Management key for per-tenant OpenRouter provisioning. It only manages other
# keys (create/list/update/delete) and can never make inference calls. When it
# is set, every company gets its own dashboard-visible key with a spend limit.
# When it is missing, all traffic falls back to OPENROUTER_KEY as before.
OPENROUTER_MANAGEMENT_KEY = (os.environ.get("OPENROUTER_MANAGEMENT_KEY") or "").strip() or None
try:
    TENANT_OPENROUTER_DEFAULT_LIMIT_USD = float(os.environ.get('TENANT_OPENROUTER_DEFAULT_LIMIT_USD') or 0.0)
except (TypeError, ValueError):
    TENANT_OPENROUTER_DEFAULT_LIMIT_USD = 0.0
if TENANT_OPENROUTER_DEFAULT_LIMIT_USD < 0:
    TENANT_OPENROUTER_DEFAULT_LIMIT_USD = 0.0
# 'none' = a lifetime cap: the key's limit is the wallet, not a renewing
# monthly budget. Renewal is then always a deliberate super-admin act
# (recharge approval / manual limit), never an automatic provider reset.
TENANT_OPENROUTER_DEFAULT_RESET = (os.environ.get('TENANT_OPENROUTER_DEFAULT_RESET') or 'none').strip().lower()
if TENANT_OPENROUTER_DEFAULT_RESET not in ('daily', 'weekly', 'monthly', 'none'):
    TENANT_OPENROUTER_DEFAULT_RESET = 'none'
# Strict per-company spend: when 1, a company without an active key of its
# own is refused before any provider call instead of silently burning the
# shared global key. Super-admin operations always use the global key.
# Default 0 keeps the historical fallback until the owner enables it.
# The management key must also be configured; without it per-tenant keys cannot
# be provisioned, so enforcing strict mode would block every AI call.
REQUIRE_TENANT_OPENROUTER_KEY = (
    (os.environ.get('REQUIRE_TENANT_OPENROUTER_KEY') or '').strip() == '1'
    and bool(OPENROUTER_MANAGEMENT_KEY)
)
GEMINI_TEXT_MODEL = "google/gemini-3.8-flash"
LUNA_TEXT_MODEL = GEMINI_TEXT_MODEL
GLM_MODEL = GEMINI_TEXT_MODEL
GLM_OPENROUTER_MODEL = GEMINI_TEXT_MODEL
SLIDE_TEXT_MODEL = os.environ.get('SLIDE_TEXT_MODEL', 'openai/gpt-5.6-sol')
DESIGNER_PLANNER_MAX_TOKENS = int(os.environ.get('DESIGNER_PLANNER_MAX_TOKENS', '3000'))
DESIGNER_EDIT_MAX_TOKENS = int(os.environ.get('DESIGNER_EDIT_MAX_TOKENS', '16000'))
print(f"[CONFIG] Primary text/design model: {GEMINI_TEXT_MODEL}")
print(f"[CONFIG] Slide generation model: {SLIDE_TEXT_MODEL}")
# All image generation runs on OpenRouter's dedicated /images endpoint — the
# adopted model is image-only and rejects /chat/completions.
IMAGE_MODEL = os.environ.get('IMAGE_MODEL', 'openai/gpt-image-2.5-sunburst')
VISUAL_CONCEPT_IMAGE_MODEL = os.environ.get('VISUAL_CONCEPT_IMAGE_MODEL', IMAGE_MODEL)
SITE_ANALYSIS_MAX_TOKENS = int(os.environ.get('SITE_ANALYSIS_MAX_TOKENS', '6000'))
EXECUTIVE_CONTENT_MAX_TOKENS = int(os.environ.get('EXECUTIVE_CONTENT_MAX_TOKENS', '32000'))
EXECUTIVE_SUMMARY_MAX_TOKENS = int(os.environ.get('EXECUTIVE_SUMMARY_MAX_TOKENS', '65536'))
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'outputs')
DEPLOYMENT_MARKER_PATH = os.path.join(os.path.dirname(__file__), '.deployed_commit')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY')
print(f"[CONFIG] OPENROUTER_KEY: {'SET' if OPENROUTER_KEY else 'MISSING'}")
print(f"[CONFIG] OPENROUTER_MANAGEMENT_KEY: {'SET' if OPENROUTER_MANAGEMENT_KEY else 'MISSING'}")
print(f"[CONFIG] REQUIRE_TENANT_OPENROUTER_KEY: {'ON' if REQUIRE_TENANT_OPENROUTER_KEY else 'OFF'}")
print(f"[CONFIG] GOOGLE_MAPS_API_KEY: {'SET' if GOOGLE_MAPS_API_KEY else 'MISSING'}")
print(f"[CONFIG] JWT_SECRET: {auth.JWT_SECRET_SOURCE.upper()}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Split parts — this module grew past 30k lines, so its body lives in ordered
# files under app_parts/, exec'd into this module's own namespace. Globals,
# monkeypatching (patch.object(app, 'name')) and tracebacks are unchanged:
# part files are compiled with their real path so frames point at the part file.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_parts')
for _part_name in sorted(_n for _n in os.listdir(_PARTS_DIR) if _n.endswith('.py')):
    _part_path = os.path.join(_PARTS_DIR, _part_name)
    with open(_part_path, encoding='utf-8') as _part_fh:
        exec(compile(_part_fh.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_fh, _part_name
except NameError:
    pass
del _PARTS_DIR
