


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Identity tokens: invites with scope application, password-setup
# tokens, session-version bumps and revoked-token JTIs.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ─────────────────────────────────────────────────────────────────────────────
# Invite Links
# ─────────────────────────────────────────────────────────────────────────────

def create_invite(tenant_id, email, expiry_days=7, role='employee', name=None,
                  phone=None, sections=None, projects=None, responsibility=None):
    """Create an invite link carrying the pre-assigned role and scope (t21)."""
    import secrets as _secrets
    conn = get_db()
    invite_id = str(uuid.uuid4())
    token = _secrets.token_urlsafe(32)
    from datetime import timedelta
    expires = (_utcnow() + timedelta(days=expiry_days)).isoformat()
    clean_role = role if role in USER_ROLES else 'employee'
    clean_resp = responsibility if responsibility in ('editor', 'approver', 'admin') else None
    sections_json = json.dumps(list(sections), ensure_ascii=False) if sections is not None else None
    projects_json = json.dumps(list(projects), ensure_ascii=False) if projects is not None else None
    conn.execute(
        '''INSERT INTO invite_links
           (id, tenant_id, email, token, expires_at, name, phone, role, sections_json, projects_json, responsibility)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (invite_id, tenant_id, email.lower(), token, expires,
         str(name or '').strip() or None, str(phone or '').strip() or None, clean_role,
         sections_json, projects_json, clean_resp)
    )
    conn.commit()
    return {'id': invite_id, 'token': token, 'expires_at': expires}


def get_invite(tenant_id, invite_id):
    """One invite row for the tenant, whatever its state."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM invite_links WHERE id = ? AND tenant_id = ?', (invite_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


def mark_invite_email(invite_id, status, error=None):
    """Record the outcome of one invite-email send attempt (t21)."""
    conn = get_db()
    conn.execute(
        '''UPDATE invite_links SET email_status = ?, email_error = ?,
           email_attempts = COALESCE(email_attempts, 0) + 1, email_sent_at = ?
           WHERE id = ?''',
        (status, str(error or '')[:400] or None, _utcnow().isoformat(), invite_id),
    )
    conn.commit()


def apply_invite_scope(user_id, invite):
    """Give a newly registered user the scope and responsibility on the invite.

    An «admin» responsibility means every company permission and no project
    restriction; «editor»/«approver» become project assignments (the listed
    drafts, or every draft when the picker was left empty); anything else
    keeps the plain-employee scope semantics. Returns an assignment error
    code when the responsibility could not be applied — the same validations
    the direct add-user path reports — or ``None`` on success.
    """
    conn = get_db()
    tenant_id = invite.get('tenant_id')
    responsibility = invite.get('responsibility')
    if responsibility == 'admin':
        grant_company_admin_permissions(user_id)
        return None
    if responsibility in ASSIGNMENT_ROLES:
        apply_responsibility_preset(user_id, responsibility)
        valid = {
            row['id'] for row in conn.execute(
                'SELECT id FROM project_drafts WHERE tenant_id = ?', (tenant_id,)
            ).fetchall()
        }
        projects = _json_or(invite.get('projects_json'), None)
        wanted = [str(d) for d in projects if str(d) in valid] if isinstance(projects, list) else []
        targets = wanted or [ASSIGNMENT_ALL_DRAFTS]
        result = set_user_assignments(
            tenant_id, user_id,
            [{'draft_id': d, 'role': responsibility} for d in targets])
        return (result or {}).get('error')
    sections = _json_or(invite.get('sections_json'), None)
    if isinstance(sections, list) and sections:
        allowed = set(str(s) for s in sections)
        for key in get_user_field_sections(user_id, tenant_id):
            set_user_field_section(user_id, key, key in allowed)
    projects = _json_or(invite.get('projects_json'), None)
    if isinstance(projects, list) and projects:
        valid = {
            row['id'] for row in conn.execute(
                'SELECT id FROM project_drafts WHERE tenant_id = ?', (tenant_id,)
            ).fetchall()
        }
        for draft_id in projects:
            if draft_id in valid:
                conn.execute(
                    'INSERT OR IGNORE INTO user_project_scopes (id, tenant_id, user_id, draft_id) VALUES (?, ?, ?, ?)',
                    (str(uuid.uuid4()), tenant_id, user_id, draft_id),
                )
        conn.commit()
    return None


def create_password_setup_token(tenant_id, user_id, expiry_hours=24):
    """Create a one-time password setup token and return its raw value."""
    import hashlib as _hashlib
    import secrets as _secrets
    from datetime import timedelta
    conn = get_db()
    raw_token = _secrets.token_urlsafe(32)
    token_hash = _hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    token_id = str(uuid.uuid4())
    expires_at = (_utcnow() + timedelta(hours=expiry_hours)).isoformat()
    conn.execute(
        '''UPDATE password_setup_tokens
           SET used_at = ?
           WHERE tenant_id = ? AND user_id = ? AND used_at IS NULL''',
        (_utcnow().isoformat(), tenant_id, user_id)
    )
    conn.execute(
        '''INSERT INTO password_setup_tokens
           (id, tenant_id, user_id, token_hash, expires_at)
           VALUES (?, ?, ?, ?, ?)''',
        (token_id, tenant_id, user_id, token_hash, expires_at)
    )
    conn.commit()
    return raw_token


def get_password_setup_token(raw_token):
    """Return a valid one-time password setup token."""
    import hashlib as _hashlib
    conn = get_db()
    token_hash = _hashlib.sha256(str(raw_token or '').encode('utf-8')).hexdigest()
    row = conn.execute(
        '''SELECT pst.*, t.company_name, t.username, t.email
           FROM password_setup_tokens pst
           JOIN tenants t ON t.id = pst.tenant_id
           WHERE pst.token_hash = ? AND pst.used_at IS NULL AND pst.expires_at > ?''',
        (token_hash, _utcnow().isoformat())
    ).fetchone()
    return dict(row) if row else None


def _revoke_password_setup_tokens(conn, user_id=None, tenant_id=None):
    """Consume every unused password-setup link for a user or a whole company.

    Runs when the account is deactivated: a link issued before the
    deactivation must not be able to reactivate the user afterwards.
    """
    now = _utcnow().isoformat()
    if user_id:
        conn.execute(
            'UPDATE password_setup_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL',
            (now, user_id)
        )
    if tenant_id:
        conn.execute(
            'UPDATE password_setup_tokens SET used_at = ? WHERE tenant_id = ? AND used_at IS NULL',
            (now, tenant_id)
        )


def complete_password_setup(raw_token, password_hash):
    """Set the password for a valid setup token and consume it atomically."""
    import hashlib as _hashlib
    conn = get_db()
    token_hash = _hashlib.sha256(str(raw_token or '').encode('utf-8')).hexdigest()
    token = conn.execute(
        'SELECT * FROM password_setup_tokens WHERE token_hash = ?',
        (token_hash,)
    ).fetchone()
    if not token:
        return None
    used_at = _utcnow().isoformat()
    try:
        claimed = conn.execute(
            '''UPDATE password_setup_tokens SET used_at = ?
               WHERE id = ? AND used_at IS NULL AND expires_at > ?''',
            (used_at, token['id'], used_at)
        )
        if claimed.rowcount != 1:
            conn.rollback()
            return None
        conn.execute(
            '''UPDATE users
               SET password_hash = ?, require_password_change = 0, is_active = 1,
                   session_version = COALESCE(session_version, 0) + 1
               WHERE id = ? AND tenant_id = ?''',
            (password_hash, token['user_id'], token['tenant_id'])
        )
        conn.execute(
            '''UPDATE tenants
               SET password_hash = ?, require_password_change = 0,
                   session_version = COALESCE(session_version, 0) + 1
               WHERE id = ? AND primary_user_id = ?''',
            (password_hash, token['tenant_id'], token['user_id'])
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        'tenant_id': token['tenant_id'],
        'user_id': token['user_id'],
    }


# ── Session revocation ────────────────────────────────────────────────────────
# Session JWTs carry the identity's ``session_version`` (``sv``) plus a unique
# ``jti``. A password write bumps the version so every earlier token goes stale;
# logout records the jti in ``revoked_tokens`` until the token's natural exp.


def get_session_version(scope, row_id):
    """Current session epoch for an identity ('user' or 'tenant'); missing rows read 0."""
    if not row_id:
        return 0
    table = 'users' if scope == 'user' else 'tenants'
    conn = get_db()
    try:
        row = conn.execute(
            f'SELECT session_version FROM {table} WHERE id = ?', (row_id,)
        ).fetchone()
    except Exception:
        return 0
    if not row:
        return 0
    try:
        return int(row['session_version'] or 0)
    except (TypeError, ValueError):
        return 0


def bump_session_version(scope, row_id):
    """Invalidate every outstanding session token for this identity."""
    if not row_id:
        return
    table = 'users' if scope == 'user' else 'tenants'
    conn = get_db()
    conn.execute(
        f'UPDATE {table} SET session_version = COALESCE(session_version, 0) + 1 WHERE id = ?',
        (row_id,)
    )
    conn.commit()


def revoke_token_jti(jti, tenant_id, expires_at):
    """Denylist a single token id until its natural expiry (logout)."""
    if not jti:
        return
    conn = get_db()
    now = int(datetime.now(timezone.utc).timestamp())
    conn.execute('DELETE FROM revoked_tokens WHERE expires_at < ?', (now,))
    conn.execute(
        'INSERT OR IGNORE INTO revoked_tokens (jti, tenant_id, expires_at) VALUES (?, ?, ?)',
        (str(jti), str(tenant_id or ''), int(expires_at or now))
    )
    conn.commit()


def is_token_revoked(jti):
    """True when this token id was revoked before its exp."""
    if not jti:
        return False
    conn = get_db()
    row = conn.execute(
        'SELECT 1 FROM revoked_tokens WHERE jti = ?', (str(jti),)
    ).fetchone()
    return row is not None


def get_invite_by_token(token):
    """Get an invite by token. Returns None if expired or used."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM invite_links WHERE token = ? AND used_at IS NULL AND expires_at > ?",
        (token, _utcnow().isoformat())
    ).fetchone()
    return dict(row) if row else None


def mark_invite_used(token):
    """Mark an invite as used."""
    conn = get_db()
    conn.execute('UPDATE invite_links SET used_at = ? WHERE token = ?', (_utcnow().isoformat(), token))
    conn.commit()


def record_login(tenant_id, user_id=None):
    """Stamp last_login_at on the tenant row or the user row after a login."""
    conn = get_db()
    now = _utcnow().isoformat()
    if user_id:
        conn.execute('UPDATE users SET last_login_at = ? WHERE id = ?', (now, user_id))
    else:
        conn.execute('UPDATE tenants SET last_login_at = ? WHERE id = ?', (now, tenant_id))
    conn.commit()
    return now


def expire_stale_invites(tenant_id):
    """t21: invites past their expiry can no longer be accepted."""
    conn = get_db()
    now = _utcnow().isoformat()
    cursor = conn.execute(
        'UPDATE invite_links SET used_at = ? WHERE tenant_id = ? AND used_at IS NULL AND expires_at < ?',
        (now, tenant_id, now),
    )
    conn.commit()
    return cursor.rowcount


# ─────────────────────────────────────────────────────────────────────────────
# Auth OTP Challenges & Trusted Devices
# ─────────────────────────────────────────────────────────────────────────────

def create_otp_challenge(tenant_id, email, raw_otp, user_id=None, expiry_minutes=10):
    """Create a 6-digit OTP challenge with single-use token and expiration."""
    import hashlib as _hashlib
    import secrets as _secrets
    from datetime import timedelta
    conn = get_db()
    challenge_id = str(uuid.uuid4())
    challenge_token = _secrets.token_urlsafe(32)
    otp_hash = _hashlib.sha256(str(raw_otp).strip().encode('utf-8')).hexdigest()
    expires_at = (_utcnow() + timedelta(minutes=expiry_minutes)).isoformat()
    now = _utcnow().isoformat()

    # Invalidate previous unused challenges for this email
    conn.execute(
        '''UPDATE auth_otp_codes SET used_at = ?
           WHERE email = ? AND used_at IS NULL''',
        (now, str(email).lower().strip())
    )
    conn.execute(
        '''INSERT INTO auth_otp_codes
           (id, tenant_id, user_id, email, otp_hash, challenge_token, attempts, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)''',
        (challenge_id, tenant_id, user_id, str(email).lower().strip(), otp_hash, challenge_token, expires_at, now)
    )
    conn.commit()
    return {
        'id': challenge_id,
        'challenge_token': challenge_token,
        'expires_at': expires_at,
        'email': email,
    }


def get_otp_challenge(challenge_token):
    """Fetch an active, non-expired OTP challenge with remaining attempts."""
    conn = get_db()
    now = _utcnow().isoformat()
    row = conn.execute(
        '''SELECT * FROM auth_otp_codes
           WHERE challenge_token = ? AND used_at IS NULL AND expires_at > ? AND attempts < 5''',
        (challenge_token, now)
    ).fetchone()
    return dict(row) if row else None


def increment_otp_attempt(challenge_token):
    """Record an invalid OTP attempt. Returns the new attempt count."""
    conn = get_db()
    conn.execute(
        '''UPDATE auth_otp_codes SET attempts = attempts + 1
           WHERE challenge_token = ?''',
        (challenge_token,)
    )
    conn.commit()
    row = conn.execute(
        'SELECT attempts FROM auth_otp_codes WHERE challenge_token = ?',
        (challenge_token,)
    ).fetchone()
    return row['attempts'] if row else 5


def complete_otp_challenge(challenge_token):
    """Mark an OTP challenge as successfully verified and consumed."""
    conn = get_db()
    now = _utcnow().isoformat()
    conn.execute(
        'UPDATE auth_otp_codes SET used_at = ? WHERE challenge_token = ?',
        (now, challenge_token)
    )
    conn.commit()


def is_device_trusted(tenant_id, device_id, raw_token, user_id=None, fingerprint_hash=None):
    """Check if the given device and secret token represent a valid trusted device."""
    if not tenant_id or not device_id or not raw_token:
        return False
    import hashlib as _hashlib
    conn = get_db()
    token_hash = _hashlib.sha256(str(raw_token).strip().encode('utf-8')).hexdigest()
    now = _utcnow().isoformat()

    query = '''SELECT * FROM trusted_devices
               WHERE tenant_id = ? AND device_id = ? AND token_hash = ?
                 AND is_revoked = 0 AND expires_at > ?'''
    params = [tenant_id, str(device_id).strip(), token_hash, now]

    if user_id:
        query += ' AND (user_id = ? OR user_id IS NULL)'
        params.append(user_id)

    row = conn.execute(query, params).fetchone()
    if not row:
        return False

    # Bump last_used_at on successful check
    conn.execute(
        'UPDATE trusted_devices SET last_used_at = ? WHERE id = ?',
        (now, row['id'])
    )
    conn.commit()
    return True


def create_trusted_device(tenant_id, device_id, user_id=None, fingerprint_hash=None,
                          device_name=None, ip_address=None, expiry_days=90):
    """Register or refresh a trusted device and return a raw secret token."""
    import hashlib as _hashlib
    import secrets as _secrets
    from datetime import timedelta
    conn = get_db()
    device_row_id = str(uuid.uuid4())
    raw_token = _secrets.token_urlsafe(32)
    token_hash = _hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    now = _utcnow().isoformat()
    expires_at = (_utcnow() + timedelta(days=expiry_days)).isoformat()

    # Revoke any prior active tokens for this specific device on this tenant/user
    if user_id:
        conn.execute(
            '''UPDATE trusted_devices SET is_revoked = 1
               WHERE tenant_id = ? AND user_id = ? AND device_id = ? AND is_revoked = 0''',
            (tenant_id, user_id, str(device_id).strip())
        )
    else:
        conn.execute(
            '''UPDATE trusted_devices SET is_revoked = 1
               WHERE tenant_id = ? AND device_id = ? AND is_revoked = 0''',
            (tenant_id, str(device_id).strip())
        )

    conn.execute(
        '''INSERT INTO trusted_devices
           (id, tenant_id, user_id, device_id, token_hash, fingerprint_hash,
            device_name, ip_address, last_used_at, expires_at, is_revoked, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)''',
        (device_row_id, tenant_id, user_id, str(device_id).strip(), token_hash,
         str(fingerprint_hash or '')[:128] or None,
         str(device_name or '')[:120] or None,
         str(ip_address or '')[:64] or None,
         now, expires_at, now)
    )
    conn.commit()
    return raw_token
