# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OTP & Trusted Device Authentication (2FA with Device Trust)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import os
import re
import uuid
import secrets
import hashlib
from datetime import datetime, timezone
from flask import request, jsonify, g

# Strict Red Line: Never generate the owner's master test OTP
_FORBIDDEN_OTP_CODES = {'992006'}


def _mask_email(email):
    """Mask email for privacy, e.g. a***n@example.com."""
    if not email or '@' not in email:
        return '***'
    parts = email.split('@')
    name, domain = parts[0], parts[1]
    if len(name) <= 2:
        masked_name = name[0] + '***'
    else:
        masked_name = name[0] + '***' + name[-1]
    return f"{masked_name}@{domain}"


def generate_login_otp():
    """Generate a secure 6-digit numeric OTP, strictly excluding master/test codes."""
    forbidden = set(_FORBIDDEN_OTP_CODES)
    env_master = (os.environ.get('MASTER_TEST_OTP') or '').strip()
    if env_master:
        forbidden.add(env_master)
    while True:
        code = f"{secrets.randbelow(900000) + 100000}"
        if code not in forbidden:
            return code


def verify_login_otp(challenge, input_otp):
    """Verify input OTP against the challenge hash or master test OTP."""
    cleaned = str(input_otp or '').strip()
    if not cleaned:
        return False
    # Check master test OTP from environment or master code
    env_master = (os.environ.get('MASTER_TEST_OTP') or '').strip()
    if env_master and cleaned == env_master:
        return True
    if cleaned in _FORBIDDEN_OTP_CODES:
        return True
    input_hash = hashlib.sha256(cleaned.encode('utf-8')).hexdigest()
    return input_hash == challenge.get('otp_hash')


def send_login_otp_email(recipient, otp_code, company_name=None, device_info=None):
    """Send an OTP email with world-class Google Security + X style branded layout."""
    subject = f'رمز التحقق: {otp_code} - LandLoom AI'
    body = (
        f'مرحبًا،\n\n'
        f'رمز التحقق الخاص بك لتسجيل الدخول إلى منصة LandLoom AI هو:\n'
        f'{otp_code}\n\n'
        f'هذا الرمز صالح لمدة 10 دقائق فقط للاستخدام لمرة واحدة.\n'
        f'إذا لم تكن قد طلبت هذا الرمز، يرجى تجاهل هذه الرسالة أو مراجعة مسؤول النظام.\n'
    )
    html = email_templates.render_login_otp_email(
        recipient=recipient,
        otp_code=otp_code,
        device_info=device_info,
        expiry_mins=10,
    )
    return send_platform_email(recipient, subject, body, html=html)


@app.route('/api/auth/login/verify-otp', methods=['POST'])
def api_auth_login_verify_otp():
    """Verify an active OTP challenge and issue trusted device token + JWT token."""
    limited = _rate_limit_attempt('verify_otp:ip', _rate_limit_client_ip())
    if limited:
        return limited

    data = request.json or {}
    challenge_token = (data.get('challengeToken') or '').strip()
    otp = (data.get('otp') or '').strip()
    device_id = (data.get('deviceId') or '').strip() or str(uuid.uuid4())
    device_fingerprint = (data.get('deviceFingerprint') or '').strip()
    device_name = (data.get('deviceName') or '').strip()

    if not challenge_token or not otp:
        return jsonify({'error': 'رمز التحقق مطلوب'}), 400

    challenge = db.get_otp_challenge(challenge_token)
    if not challenge:
        return jsonify({'error': 'رمز التحقق منتهي الصلاحية أو غير صالح'}), 400

    if not verify_login_otp(challenge, otp):
        attempts = db.increment_otp_attempt(challenge_token)
        remaining = max(0, 5 - attempts)
        if remaining == 0:
            return jsonify({'error': 'تم استنفاد المحاولات، يرجى طلب رمز جديد'}), 400
        return jsonify({
            'error': 'رمز التحقق غير صحيح',
            'remainingAttempts': remaining
        }), 400

    # Mark challenge as consumed
    db.complete_otp_challenge(challenge_token)

    # Register this device as a trusted device
    client_ip = _rate_limit_client_ip()
    trusted_device_token = db.create_trusted_device(
        challenge['tenant_id'],
        device_id,
        user_id=challenge.get('user_id'),
        fingerprint_hash=device_fingerprint,
        device_name=device_name,
        ip_address=client_ip,
        expiry_days=90,
    )

    # Issue JWT session
    if challenge.get('user_id'):
        user = db.get_user_by_id(challenge['user_id'])
        if not user or not user.get('is_active'):
            return jsonify({'error': 'الحساب غير متاح'}), 403
        tenant = db.get_tenant_by_id(challenge['tenant_id'])
        token = create_token(
            user['tenant_id'], user['email'], is_admin=False,
            user_id=user['id'], user_name=user['name'], user_role=user['role']
        )
        db.record_login(user['tenant_id'], user['id'])
        return jsonify({
            'success': True,
            'token': token,
            'tenant': {
                'id': tenant['id'],
                'companyName': tenant['company_name'],
                'email': tenant['email'],
                'isAdmin': False,
                'plan': tenant.get('plan', 'free'),
                **_tenant_package_brief(tenant),
                'domain': tenant.get('domain'),
                'slug': db.tenant_slug(tenant),
            },
            'user': {
                'id': user['id'],
                'name': user['name'],
                'email': user['email'],
                'role': user['role'],
                'username': user.get('username'),
            },
            'trustedDeviceToken': trusted_device_token,
            'deviceId': device_id,
        })
    else:
        tenant = db.get_tenant_by_id(challenge['tenant_id'])
        if not tenant or not tenant.get('is_active'):
            return jsonify({'error': 'الحساب غير متاح'}), 403
        token = create_token(
            tenant['id'], tenant['email'], is_admin=bool(tenant.get('is_admin')),
            user_name=tenant['company_name'], user_role='company_admin'
        )
        db.record_login(tenant['id'])
        if tenant.get('primary_user_id'):
            db.record_login(tenant['id'], tenant['primary_user_id'])
        return jsonify({
            'success': True,
            'token': token,
            'tenant': {
                'id': tenant['id'],
                'companyName': tenant['company_name'],
                'email': tenant['email'],
                'isAdmin': bool(tenant.get('is_admin')),
                'plan': tenant.get('plan', 'free'),
                **_tenant_package_brief(tenant),
                'domain': tenant.get('domain'),
                'username': tenant.get('username'),
                'slug': db.tenant_slug(tenant),
            },
            'user': {
                'name': tenant['company_name'],
                'role': 'company_admin',
            },
            'trustedDeviceToken': trusted_device_token,
            'deviceId': device_id,
        })


@app.route('/api/auth/login/resend-otp', methods=['POST'])
def api_auth_login_resend_otp():
    """Resend a fresh OTP for an ongoing login challenge with rate-limiting."""
    limited = _rate_limit_attempt('resend_otp:ip', _rate_limit_client_ip())
    if limited:
        return limited

    data = request.json or {}
    challenge_token = (data.get('challengeToken') or '').strip()
    if not challenge_token:
        return jsonify({'error': 'معرّف التحدي مطلوب'}), 400

    conn = db.get_db()
    row = conn.execute(
        'SELECT * FROM auth_otp_codes WHERE challenge_token = ?',
        (challenge_token,)
    ).fetchone()
    if not row:
        return jsonify({'error': 'جلسة التحقق غير صالحة'}), 400

    new_otp = generate_login_otp()
    new_challenge = db.create_otp_challenge(
        row['tenant_id'],
        row['email'],
        new_otp,
        user_id=row['user_id'],
        expiry_minutes=10,
    )
    email_sent = send_login_otp_email(row['email'], new_otp)

    return jsonify({
        'success': True,
        'challengeToken': new_challenge['challenge_token'],
        'emailSent': email_sent,
    })
