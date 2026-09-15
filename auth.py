"""
Authentication layer for Multi-Tenant SaaS.
JWT-based with PBKDF2 password hashing (no external dependency).
"""

import os
import hashlib
import hmac
import time
import json
import base64
import secrets
from functools import wraps
from flask import request, jsonify, g
import db

def _load_jwt_secret():
    configured_secret = os.environ.get('JWT_SECRET', '').strip()
    if configured_secret:
        return configured_secret, 'environment'

    base_dir = os.path.abspath(os.path.dirname(__file__))
    secret_path = os.path.abspath(os.path.join(base_dir, '.jwt_secret'))
    if os.path.commonpath([base_dir, secret_path]) != base_dir:
        raise RuntimeError('Invalid secret file path')
    if os.path.exists(secret_path):
        with open(secret_path, 'r', encoding='utf-8') as secret_file:
            stored_secret = secret_file.read().strip()
            if stored_secret:
                return stored_secret, 'local_file'

    generated_secret = secrets.token_urlsafe(64)
    with open(secret_path, 'w', encoding='utf-8') as secret_file:
        secret_file.write(generated_secret)
    return generated_secret, 'local_file'


JWT_SECRET, JWT_SECRET_SOURCE = _load_jwt_secret()
JWT_EXPIRY_HOURS = 72  # 3 days


def create_signed_download_token(file_id, tenant_id, ttl_seconds=900):
    """t61: short-lived HMAC token carrying the file and its owning tenant."""
    exp = int(time.time()) + int(ttl_seconds)
    signing_input = f"dl.{file_id}.{tenant_id}.{exp}"
    sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).hexdigest()
    return f"{signing_input}.{sig}"


def verify_signed_download_token(token):
    """Return {'file_id', 'tenant_id'} for a valid unexpired token, else None."""
    parts = str(token or '').split('.')
    if len(parts) != 5 or parts[0] != 'dl':
        return None
    signing_input = '.'.join(parts[:4])
    expected = hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts[4]):
        return None
    try:
        exp = int(parts[3])
    except ValueError:
        return None
    if exp < int(time.time()):
        return None
    return {'file_id': parts[1], 'tenant_id': parts[2]}


# ─────────────────────────────────────────────────────────────────────────────
# Password Hashing (PBKDF2 + random salt — no external deps)
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(password):
    """Hash a password with a random salt using PBKDF2."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"pbkdf2$sha256${salt.hex()}${key.hex()}"


def verify_password(password, stored_hash):
    """Verify a password against a stored hash."""
    try:
        parts = stored_hash.split('$')
        if len(parts) != 4 or parts[0] != 'pbkdf2':
            return False
        salt = bytes.fromhex(parts[2])
        stored_key = bytes.fromhex(parts[3])
        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return hmac.compare_digest(key, stored_key)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# JWT Token Management (pure Python — no PyJWT dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _b64encode(data):
    """Base64 URL encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def _b64decode(data):
    """Base64 URL decode, adding padding back."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def _current_session_version(tenant_id, user_id):
    """Snapshot the identity's session epoch. Outside a request/app context the
    DB is unreachable, so the claim falls back to 0 — matching the column
    default of any account that never had its password rewritten."""
    try:
        return db.get_session_version('user' if user_id else 'tenant', user_id or tenant_id)
    except Exception:
        return 0


def create_token(tenant_id, email, is_admin=False, user_id=None, user_name=None,
                 user_role=None, mfa_pending=False):
    """Create a JWT token for a tenant or user.

    ``mfa_pending`` marks a session issued to a mandatory-MFA identity that has
    not enrolled a factor yet; the decorators confine it to the enrolment
    endpoints until ``mfa/enable`` hands back a clean token.
    """
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'sub': tenant_id,
        'email': email,
        'is_admin': is_admin,
        'user_id': user_id,
        'user_name': user_name,
        'user_role': user_role,
        'jti': secrets.token_urlsafe(16),
        'sv': _current_session_version(tenant_id, user_id),
        'iat': int(time.time()),
        'exp': int(time.time()) + (JWT_EXPIRY_HOURS * 3600),
    }
    if mfa_pending:
        payload['mfa_pending'] = True

    header_b64 = _b64encode(json.dumps(header, separators=(',', ':')).encode())
    payload_b64 = _b64encode(json.dumps(payload, separators=(',', ':')).encode())

    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_token(token):
    """Decode and verify a JWT token. Returns payload dict or None."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts
        header = json.loads(_b64decode(header_b64))
        if header.get('alg') != 'HS256' or header.get('typ') != 'JWT':
            return None

        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        expected_sig_b64 = _b64encode(expected_sig)

        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None

        payload = json.loads(_b64decode(payload_b64))

        if payload.get('exp', 0) < time.time():
            return None
        if not isinstance(payload.get('sub'), str) or not payload['sub']:
            return None
        # Purpose-scoped tokens (the MFA challenge) are not session tokens.
        if payload.get('purpose'):
            return None

        return payload
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# TOTP two-factor authentication (RFC 6238, pure stdlib — t21/t63)
# ─────────────────────────────────────────────────────────────────────────────

MFA_TOKEN_EXPIRY_SECONDS = 600  # the post-password challenge lives 10 minutes
MFA_ISSUER = 'LandLoom'


def generate_totp_secret():
    """A fresh base32 secret for an authenticator app."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _totp_secret_bytes(secret):
    padding = 8 - len(secret) % 8
    if padding != 8:
        secret = secret + '=' * padding
    return base64.b32decode(secret.upper())


def totp_code(secret, at_time=None, period=30, digits=6):
    """The current TOTP code for a base32 secret."""
    counter = int((at_time if at_time is not None else time.time()) // period)
    digest = hmac.new(
        _totp_secret_bytes(secret), counter.to_bytes(8, 'big'), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset:offset + 4], 'big') & 0x7FFFFFFF
    return str(value % (10 ** digits)).zfill(digits)


def verify_totp(secret, code, window=1):
    """Accept the current step and ``window`` neighbours for clock drift."""
    code = str(code or '').strip().replace(' ', '')
    if not secret or not code.isdigit():
        return False
    now = int(time.time())
    for step in range(-window, window + 1):
        if hmac.compare_digest(totp_code(secret, at_time=now + step * 30), code):
            return True
    return False


def create_mfa_token(tenant_id, email, user_id=None, user_name=None, user_role=None):
    """A short-lived JWT that only carries a login through the MFA challenge.

    The ``purpose`` claim makes ``decode_token`` reject it, so the challenge
    token can never be replayed as a session token.
    """
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'sub': tenant_id,
        'email': email,
        'user_id': user_id,
        'user_name': user_name,
        'user_role': user_role,
        'purpose': 'mfa',
        'iat': int(time.time()),
        'exp': int(time.time()) + MFA_TOKEN_EXPIRY_SECONDS,
    }
    header_b64 = _b64encode(json.dumps(header, separators=(',', ':')).encode())
    payload_b64 = _b64encode(json.dumps(payload, separators=(',', ':')).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64encode(signature)}"


def verify_mfa_token(token):
    """Decode a token only when it is the short-lived MFA challenge."""
    try:
        parts = str(token or '').split('.')
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        header = json.loads(_b64decode(header_b64))
        if header.get('alg') != 'HS256' or header.get('typ') != 'JWT':
            return None
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(sig_b64, _b64encode(expected_sig)):
            return None
        payload = json.loads(_b64decode(payload_b64))
        if payload.get('purpose') != 'mfa' or payload.get('exp', 0) < time.time():
            return None
        if not isinstance(payload.get('sub'), str) or not payload['sub']:
            return None
        return payload
    except Exception:
        return None


def generate_recovery_codes(count=8):
    """One-time recovery codes shown once at MFA setup."""
    return [f'{secrets.randbelow(10**8):08d}' for _ in range(count)]


def totp_otpauth_uri(secret, account_name):
    """otpauth:// URI for authenticator apps that accept pasted setup text."""
    from urllib.parse import quote
    label = f'{MFA_ISSUER}:{account_name}'
    return f'otpauth://totp/{quote(label)}?secret={secret}&issuer={quote(MFA_ISSUER)}'


# ─────────────────────────────────────────────────────────────────────────────
# Flask Middleware Decorators
# ─────────────────────────────────────────────────────────────────────────────

def _load_token_user(payload):
    """Return the live users row for a user-bound token.

    A token without user_id is a tenant-direct login and returns (None, None).
    A user-bound token whose row was deleted, disabled or belongs to another
    tenant returns (None, error_response) — the JWT alone is never trusted,
    because claims like role stay frozen until expiry while the account may
    already be disabled or demoted.
    """
    user_id = payload.get('user_id')
    if not user_id:
        return None, None
    user = db.get_user_by_id(user_id)
    if not user or not user.get('is_active') or str(user.get('tenant_id')) != str(payload.get('sub')):
        return None, (jsonify({'error': 'User account inactive or not found'}), 403)
    return user, None


def _is_platform_admin_session(tenant, payload):
    """Only the admin tenant's own login carries platform rights."""
    return bool(tenant.get('is_admin')) and not payload.get('user_id')


def _session_state_error(payload, tenant, user_row):
    """Reject a token that was revoked at logout or issued before the
    identity's session version last moved (every password write bumps it).

    Pre-revocation tokens carry no ``jti``/``sv`` claims: the missing jti skips
    the denylist, and a missing ``sv`` reads as version 0 — the default for any
    account whose password was never rewritten — so old sessions survive until
    the first password change retires them.
    """
    jti = payload.get('jti')
    if jti and db.is_token_revoked(jti):
        return jsonify({'error': 'Session expired', 'error_code': 'session_revoked'}), 401
    identity = user_row if payload.get('user_id') else tenant
    try:
        current = int((identity or {}).get('session_version') or 0)
    except (TypeError, ValueError):
        current = 0
    try:
        token_version = int(payload.get('sv') or 0)
    except (TypeError, ValueError):
        token_version = -1
    if token_version != current:
        return jsonify({'error': 'Session expired', 'error_code': 'session_revoked'}), 401
    return None


# A session carrying ``mfa_pending`` may only reach the enrolment surface: who
# am I, the factor status, and the setup/enable calls themselves. Everything
# else answers 403 until enrolment completes and a clean token is issued.
MFA_SETUP_EXEMPT_ENDPOINTS = frozenset({
    'api_me', 'api_logout', 'api_mfa_status', 'api_mfa_setup', 'api_mfa_enable',
})


def _mfa_pending_gate(payload):
    """403 when the session still owes mandatory MFA enrolment (t21)."""
    if not payload.get('mfa_pending'):
        return None
    if request.endpoint in MFA_SETUP_EXEMPT_ENDPOINTS:
        return None
    return (jsonify({
        'error': 'يجب إكمال إعداد التحقق الثنائي قبل المتابعة',
        'error_code': 'mfa_setup_required',
        'mfaSetupRequired': True,
    }), 403)


def require_auth(f):
    """Decorator: require a valid JWT token. Sets g.tenant_id, g.tenant, g.is_admin, g.user_id, g.user_name, g.user_role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        tenant = db.get_tenant_by_id(payload['sub'])
        if not tenant or not tenant.get('is_active'):
            return jsonify({'error': 'Account inactive or not found'}), 403

        user_row, user_error = _load_token_user(payload)
        if user_error:
            return user_error

        session_error = _session_state_error(payload, tenant, user_row)
        if session_error:
            return session_error

        mfa_block = _mfa_pending_gate(payload)
        if mfa_block:
            return mfa_block

        g.tenant_id = payload['sub']
        g.tenant = tenant
        g.is_admin = _is_platform_admin_session(tenant, payload)
        g.user_id = payload.get('user_id')
        g.user_name = (user_row or {}).get('name') or payload.get('user_name')
        g.user_role = (user_row or {}).get('role') or payload.get('user_role')
        g.user_permissions = {}
        g.token_payload = payload
        if g.user_id:
            g.user_permissions = db.get_user_permissions(g.user_id, g.user_role or 'employee')
        return f(*args, **kwargs)
    return decorated


def require_company_admin(f):
    """Decorator: require a valid JWT token AND company_admin role (or super admin)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing Authorization header'}), 401

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        tenant = db.get_tenant_by_id(payload['sub'])
        if not tenant or not tenant.get('is_active'):
            return jsonify({'error': 'Account inactive'}), 403

        user_row, user_error = _load_token_user(payload)
        if user_error:
            return user_error

        session_error = _session_state_error(payload, tenant, user_row)
        if session_error:
            return session_error

        mfa_block = _mfa_pending_gate(payload)
        if mfa_block:
            return mfa_block

        user_role = (user_row or {}).get('role') or payload.get('user_role')
        user_id = payload.get('user_id')
        is_super_admin = _is_platform_admin_session(tenant, payload)
        if not is_super_admin and user_role != 'company_admin' and user_id is not None:
            return jsonify({'error': 'Company admin access required'}), 403

        g.tenant_id = payload['sub']
        g.tenant = tenant
        g.is_admin = is_super_admin
        g.user_id = payload.get('user_id')
        g.user_name = (user_row or {}).get('name') or payload.get('user_name')
        g.user_role = user_role
        g.token_payload = payload
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Decorator: require a valid JWT token AND admin privileges."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing Authorization header'}), 401

        token = auth_header[7:]
        payload = decode_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401

        tenant = db.get_tenant_by_id(payload['sub'])
        if not tenant or not tenant.get('is_active'):
            return jsonify({'error': 'Account inactive'}), 403

        if not _is_platform_admin_session(tenant, payload):
            return jsonify({'error': 'Admin access required'}), 403

        session_error = _session_state_error(payload, tenant, None)
        if session_error:
            return session_error

        mfa_block = _mfa_pending_gate(payload)
        if mfa_block:
            return mfa_block

        g.tenant_id = payload['sub']
        g.tenant = tenant
        g.is_admin = True
        g.user_id = None
        g.user_name = payload.get('user_name')
        g.user_role = payload.get('user_role')
        g.user_permissions = {}
        g.token_payload = payload
        return f(*args, **kwargs)
    return decorated


def require_permission(permission_key):
    """Decorator factory: require a specific permission. Super admins and company admins bypass."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return jsonify({'error': 'Missing Authorization header'}), 401

            token = auth_header[7:]
            payload = decode_token(token)
            if not payload:
                return jsonify({'error': 'Invalid or expired token'}), 401

            tenant = db.get_tenant_by_id(payload['sub'])
            if not tenant or not tenant.get('is_active'):
                return jsonify({'error': 'Account inactive'}), 403

            user_row, user_error = _load_token_user(payload)
            if user_error:
                return user_error

            session_error = _session_state_error(payload, tenant, user_row)
            if session_error:
                return session_error

            mfa_block = _mfa_pending_gate(payload)
            if mfa_block:
                return mfa_block

            g.tenant_id = payload['sub']
            g.tenant = tenant
            g.is_admin = _is_platform_admin_session(tenant, payload)
            g.user_id = payload.get('user_id')
            g.user_name = (user_row or {}).get('name') or payload.get('user_name')
            g.user_role = (user_row or {}).get('role') or payload.get('user_role')
            g.user_permissions = {}
            g.token_payload = payload

            is_super_admin = g.is_admin
            is_company_admin = g.user_role == 'company_admin' or g.user_id is None

            if permission_key == 'sag_admin_panel' and not is_super_admin:
                return jsonify({'error': 'Super admin access required'}), 403

            if not is_super_admin and not is_company_admin:
                if g.user_id:
                    g.user_permissions = db.get_user_permissions(g.user_id, g.user_role or 'employee')
                if not g.user_permissions.get(permission_key, False):
                    return jsonify({'error': f'Permission required: {permission_key}'}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


def get_optional_tenant_id():
    """Extract tenant_id from request if token present (optional auth)."""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        payload = decode_token(token)
        if payload:
            return payload.get('sub')
    return None
