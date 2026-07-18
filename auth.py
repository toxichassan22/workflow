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

    secret_path = os.path.join(os.path.dirname(__file__), '.jwt_secret')
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


def create_token(tenant_id, email, is_admin=False, user_id=None, user_name=None, user_role=None):
    """Create a JWT token for a tenant or user."""
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'sub': tenant_id,
        'email': email,
        'is_admin': is_admin,
        'user_id': user_id,
        'user_name': user_name,
        'user_role': user_role,
        'iat': int(time.time()),
        'exp': int(time.time()) + (JWT_EXPIRY_HOURS * 3600),
    }

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

        return payload
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Flask Middleware Decorators
# ─────────────────────────────────────────────────────────────────────────────

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

        g.tenant_id = payload['sub']
        g.tenant = tenant
        g.is_admin = bool(tenant.get('is_admin'))
        g.user_id = payload.get('user_id')
        g.user_name = payload.get('user_name')
        g.user_role = payload.get('user_role')
        g.user_permissions = {}
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

        is_super_admin = bool(tenant.get('is_admin'))
        user_role = payload.get('user_role')
        if not is_super_admin and user_role != 'company_admin':
            return jsonify({'error': 'Company admin access required'}), 403

        g.tenant_id = payload['sub']
        g.tenant = tenant
        g.is_admin = is_super_admin
        g.user_id = payload.get('user_id')
        g.user_name = payload.get('user_name')
        g.user_role = user_role
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
        if not tenant.get('is_admin'):
            return jsonify({'error': 'Admin access required'}), 403

        g.tenant_id = payload['sub']
        g.tenant = tenant
        g.is_admin = True
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

            g.tenant_id = payload['sub']
            g.tenant = tenant
            g.is_admin = bool(tenant.get('is_admin'))
            g.user_id = payload.get('user_id')
            g.user_name = payload.get('user_name')
            g.user_role = payload.get('user_role')
            g.user_permissions = {}

            is_super_admin = g.is_admin
            is_company_admin = g.user_role == 'company_admin'

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
