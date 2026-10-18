# Tenant-managed OpenRouter key lifecycle.

def _tenant_key_secret():
    """Bytes used to obscure stored provider keys. Env-overridable."""
    configured = (os.environ.get('OPENROUTER_KEY_ENCRYPTION_SECRET') or '').strip()
    if configured:
        return configured.encode('utf-8')
    fallback = (os.environ.get('JWT_SECRET') or '').strip()
    if fallback:
        return fallback.encode('utf-8')
    try:
        base_dir = REPO_ROOT
        secret_path = os.path.abspath(os.path.join(base_dir, '.jwt_secret'))
        if os.path.commonpath([base_dir, secret_path]) == base_dir and os.path.exists(secret_path):
            with open(secret_path, 'r', encoding='utf-8') as secret_file:
                stored = secret_file.read().strip()
                if stored:
                    return stored.encode('utf-8')
    except Exception:
        pass
    return b'dev-only-tenant-key-secret'


def _tenant_key_stream(secret, nonce, length):
    """SHA256 counter stream for XOR obscuring without new dependencies."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(secret + nonce + counter.to_bytes(4, 'big')).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_tenant_openrouter_key(raw_key):
    """Obscure a provider key for storage with tamper detection."""
    import base64 as _b64
    import hmac as _hmac
    import secrets as _secrets
    secret = _tenant_key_secret()
    raw = (raw_key or '').strip().encode('utf-8')
    if not raw:
        raise ValueError('Empty provider key')
    nonce = _secrets.token_bytes(16)
    stream = _tenant_key_stream(secret, nonce, len(raw))
    cipher = bytes(a ^ b for a, b in zip(raw, stream))
    tag = _hmac.new(secret, nonce + cipher, hashlib.sha256).hexdigest()
    return 'v1.' + _b64.urlsafe_b64encode(nonce).decode('ascii') + '.' \
        + _b64.urlsafe_b64encode(cipher).decode('ascii') + '.' + tag


def decrypt_tenant_openrouter_key(enc_value):
    """Reverse encrypt_tenant_openrouter_key. Returns None when tampered."""
    import base64 as _b64
    import hmac as _hmac
    try:
        if not enc_value or not isinstance(enc_value, str):
            return None
        parts = enc_value.split('.')
        if len(parts) != 4 or parts[0] != 'v1':
            return None
        secret = _tenant_key_secret()
        nonce = _b64.urlsafe_b64decode(parts[1].encode('ascii'))
        cipher = _b64.urlsafe_b64decode(parts[2].encode('ascii'))
        tag = parts[3]
        expected = _hmac.new(secret, nonce + cipher, hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, tag):
            return None
        stream = _tenant_key_stream(secret, nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode('utf-8')
    except Exception:
        return None


def _tenant_key_public(row):
    """Public metadata for a key row. The raw secret never leaves the server."""
    if row is None:
        return {'has_key': False}
    try:
        data = dict(row)
    except Exception:
        return {'has_key': False}
    key_hash = str(data.get('key_hash') or '')
    return {
        'has_key': True,
        'key_hint': ('...' + key_hash[-4:]) if len(key_hash) >= 4 else '...',
        'key_label': data.get('key_label'),
        'openrouter_key_hash': data.get('openrouter_key_hash'),
        'limit_usd': data.get('limit_usd'),
        'limit_reset': data.get('limit_reset'),
        'provenance': data.get('provenance') or 'auto',
        'is_active': bool(data.get('is_active')),
        'last_limit_remaining': data.get('last_limit_remaining'),
        'last_usage': data.get('last_usage'),
        'last_checked_at': data.get('last_checked_at'),
        'cap_sync_pending': bool(data.get('cap_sync_pending')),
        'updated_at': data.get('updated_at'),
        'created_at': data.get('created_at'),
    }


def get_tenant_openrouter_key_meta(tenant_id):
    """Public key status for one tenant. Never includes the secret."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT * FROM tenant_openrouter_keys WHERE tenant_id = ?',
            (str(tenant_id),)
        ).fetchone()
    except Exception:
        return {'has_key': False}
    return _tenant_key_public(row)


def list_tenant_key_states():
    """tenant_id -> public key metadata for every stored row, in one query.

    The admin companies list calls this once instead of paying a lookup per
    row. A tenant with no row is simply absent from the map.
    """
    try:
        conn = get_db()
        rows = conn.execute('SELECT * FROM tenant_openrouter_keys').fetchall()
    except Exception:
        return {}
    return {row['tenant_id']: _tenant_key_public(row) for row in rows}


def get_tenant_openrouter_key_raw(tenant_id):
    """Decrypted provider key for server-side calls only. None when absent."""
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT key_enc FROM tenant_openrouter_keys WHERE tenant_id = ? AND is_active = 1',
            (str(tenant_id),)
        ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        enc = dict(row).get('key_enc')
    except Exception:
        return None
    raw = decrypt_tenant_openrouter_key(enc)
    return raw if raw else None


def set_tenant_openrouter_key(tenant_id, raw_key, key_label=None, limit_usd=None,
                              limit_reset=None, provenance='manual',
                              openrouter_key_hash=None):
    """Create or replace one tenant key. Returns public metadata only."""
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        raise ValueError('tenant_id is required')
    raw = (raw_key or '').strip()
    if len(raw) < 16:
        raise ValueError('Invalid provider key')
    if provenance not in TENANT_KEY_PROVENANCES:
        provenance = 'manual'
    if limit_reset is not None and limit_reset not in TENANT_KEY_LIMIT_RESETS:
        raise ValueError('Invalid limit_reset')
    amount = None
    if limit_usd is not None:
        try:
            amount = float(limit_usd)
        except (TypeError, ValueError):
            raise ValueError('Invalid limit_usd')
        if amount < 0:
            raise ValueError('Invalid limit_usd')
    enc = encrypt_tenant_openrouter_key(raw)
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    conn = get_db()
    now = _utcnow().strftime('%Y-%m-%d %H:%M:%S')
    existing = conn.execute(
        'SELECT id FROM tenant_openrouter_keys WHERE tenant_id = ?', (tenant_id,)
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE tenant_openrouter_keys SET key_enc = ?, key_hash = ?, key_label = ?, '
            'openrouter_key_hash = ?, limit_usd = ?, limit_reset = ?, provenance = ?, '
            'is_active = 1, updated_at = ? WHERE tenant_id = ?',
            (enc, digest, (key_label or None), (openrouter_key_hash or None),
             amount, limit_reset, provenance, now, tenant_id)
        )
    else:
        conn.execute(
            'INSERT INTO tenant_openrouter_keys (id, tenant_id, key_enc, key_hash, key_label, '
            'openrouter_key_hash, limit_usd, limit_reset, provenance, is_active, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)',
            (str(uuid.uuid4()), tenant_id, enc, digest, (key_label or None),
             (openrouter_key_hash or None), amount, limit_reset, provenance, now)
        )
    conn.commit()
    return get_tenant_openrouter_key_meta(tenant_id)


def update_tenant_openrouter_key_meta(tenant_id, limit_usd=None, limit_reset=None,
                                      is_active=None, last_limit_remaining=None,
                                      last_usage=None, openrouter_key_hash=None,
                                      cap_sync_pending=None):
    """Update key metadata without touching the secret. Returns public metadata."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_openrouter_keys WHERE tenant_id = ?', (str(tenant_id),)
    ).fetchone()
    if row is None:
        return {'has_key': False}
    assignments = []
    params = []
    if limit_usd is not None:
        try:
            amount = float(limit_usd)
        except (TypeError, ValueError):
            raise ValueError('Invalid limit_usd')
        if amount < 0:
            raise ValueError('Invalid limit_usd')
        assignments.append('limit_usd = ?')
        params.append(amount)
    if limit_reset is not None:
        if limit_reset not in TENANT_KEY_LIMIT_RESETS:
            raise ValueError('Invalid limit_reset')
        assignments.append('limit_reset = ?')
        params.append(limit_reset)
    if is_active is not None:
        assignments.append('is_active = ?')
        params.append(1 if is_active else 0)
    if last_limit_remaining is not None:
        try:
            assignments.append('last_limit_remaining = ?')
            params.append(float(last_limit_remaining))
        except (TypeError, ValueError):
            pass
    if last_usage is not None:
        try:
            assignments.append('last_usage = ?')
            params.append(float(last_usage))
        except (TypeError, ValueError):
            pass
    if openrouter_key_hash is not None:
        assignments.append('openrouter_key_hash = ?')
        params.append(str(openrouter_key_hash or None))
    if cap_sync_pending is not None:
        assignments.append('cap_sync_pending = ?')
        params.append(1 if cap_sync_pending else 0)
    if last_limit_remaining is not None or last_usage is not None:
        assignments.append('last_checked_at = ?')
        params.append(_utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    if not assignments:
        return get_tenant_openrouter_key_meta(tenant_id)
    assignments.append('updated_at = ?')
    params.append(_utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(str(tenant_id))
    conn.execute(
        'UPDATE tenant_openrouter_keys SET ' + ', '.join(assignments) + ' WHERE tenant_id = ?',
        tuple(params)
    )
    conn.commit()
    return get_tenant_openrouter_key_meta(tenant_id)


def deactivate_tenant_openrouter_key(tenant_id):
    """Disable a tenant key locally. Returns public metadata."""
    return update_tenant_openrouter_key_meta(tenant_id, is_active=False)


def list_tenant_keys_pending_cap_sync(limit=25):
    """tenant_ids whose last provider-cap push never confirmed, oldest rows
    first. The housekeeping sweep retries them so one failed PATCH cannot
    leave the dashboard limit stale until the next wallet movement."""
    try:
        conn = get_db()
        rows = conn.execute(
            'SELECT tenant_id FROM tenant_openrouter_keys '
            'WHERE cap_sync_pending = 1 AND is_active = 1 '
            'ORDER BY updated_at LIMIT ?',
            (int(limit),)
        ).fetchall()
    except Exception:
        return []
    return [row['tenant_id'] for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Billing packages and the USD to SAR rate for riyal-denominated balances.
# ─────────────────────────────────────────────────────────────────────────────

FX_PAIR_USD_SAR = 'USD_SAR'
FX_DEFAULT_USD_SAR = 3.75
FX_REFRESH_SECONDS = 24 * 3600
