# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Platform mail: the single SMTP sender behind welcome, invite, OTP and outbox
# mail, plus a super-admin probe that reports exactly why delivery fails.
#
# The sender used to answer a bare False — an unset SMTP_HOST left no log line
# and the outbox stored only «smtp_send_failed» — so a broken server config was
# indistinguishable from a bad password or a firewall. The reason is now kept
# per thread (smtp_last_error()) and written to the logs and the outbox row.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SMTP_STATE = threading.local()


def _smtp_settings():
    smtp_user = (os.environ.get('SMTP_USER') or '').strip()
    try:
        port = int(os.environ.get('SMTP_PORT') or 587)
    except (TypeError, ValueError):
        port = 587
    return {
        'host': (os.environ.get('SMTP_HOST') or '').strip(),
        'port': port,
        'user': smtp_user,
        'password': os.environ.get('SMTP_PASSWORD') or '',
        'sender': (os.environ.get('SMTP_FROM') or smtp_user or 'noreply@landloom.ai').strip(),
        'ssl': str(os.environ.get('SMTP_SSL') or '').lower() in {'1', 'true', 'yes'},
        'starttls': str(os.environ.get('SMTP_TLS', 'true')).lower() not in {'0', 'false', 'no'},
    }


def _set_smtp_error(reason):
    _SMTP_STATE.last_error = reason
    return reason


def smtp_last_error():
    """Reason the last send_platform_email() on this thread failed, or None."""
    return getattr(_SMTP_STATE, 'last_error', None)


def _open_smtp_client(settings):
    if settings['ssl']:
        client = smtplib.SMTP_SSL(settings['host'], settings['port'],
                                  context=ssl.create_default_context(), timeout=20)
    else:
        client = smtplib.SMTP(settings['host'], settings['port'], timeout=20)
        if settings['starttls']:
            client.starttls(context=ssl.create_default_context())
    if settings['user']:
        client.login(settings['user'], settings['password'])
    return client


def send_platform_email(recipient, subject, body, html=None):
    _set_smtp_error(None)
    settings = _smtp_settings()
    if not recipient:
        _set_smtp_error('no_recipient')
        return False
    if not settings['host']:
        app.logger.error('Platform email skipped: SMTP_HOST is not set in the server environment')
        _set_smtp_error('smtp_not_configured: SMTP_HOST is empty')
        return False
    if not settings['sender']:
        _set_smtp_error('smtp_not_configured: SMTP_FROM is empty')
        return False
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = settings['sender']
    message['To'] = recipient
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype='html')
    try:
        client = _open_smtp_client(settings)
        try:
            client.send_message(message)
        finally:
            try:
                client.quit()
            except Exception:
                pass
        return True
    except Exception as exc:
        reason = f'{type(exc).__name__}: {exc}'[:500]
        _set_smtp_error(reason)
        app.logger.exception('Platform email could not be sent via %s:%s (%s)',
                             settings['host'], settings['port'], reason)
        return False


# ── Outbound senders ─────────────────────────────────────────────────────────
# Every send renders the designed HTML part from email_templates.py and keeps
# the plain body as the text/plain fallback — a render failure must never take
# the email down with it, so it degrades to text-only.


def _send_company_welcome_email(recipient, company_name, account_name, username, setup_url,
                                trial_days=None):
    subject = f'مرحبًا بك في LandLoom AI - {company_name}'
    body = (
        f'مرحبًا {account_name}\n\n'
        f'تم إنشاء حساب شركتك {company_name} في منصة LandLoom AI.\n'
        f'البريد الإلكتروني: {recipient}\n'
        f'رابط تعيين كلمة المرور: {setup_url}\n\n'
        'هذا الرابط صالح للاستخدام مرة واحدة.'
    )
    stats = []
    if trial_days:
        stats.append({'label': 'الفترة التجريبية', 'value': f'{trial_days} يوم',
                      'color': '#059669'})
    try:
        html = email_templates.render_company_welcome_email(
            recipient, company_name, setup_url,
            account_name=account_name, stats=stats,
            brand=email_templates.brand_assets(_current_base_url()))
    except Exception:
        html = None
    return send_platform_email(recipient, subject, body, html=html)


def _send_user_welcome_email(recipient, user_name, tenant):
    """Welcome mail for a directly-added employee: account exists, sign in with
    the email; the password itself is never sent — the admin hands it over."""
    company_name = (tenant or {}).get('company_name') or 'الشركة'
    base_url = _current_base_url().rstrip('/')
    subject = f'تم إنشاء حسابك في {company_name}'
    body = (
        f'مرحبًا {user_name}\n\n'
        f'تم إنشاء حسابك في {company_name} على منصة LandLoom AI.\n'
        f'سجّل الدخول ببريدك الإلكتروني وكلمة المرور التي استلمتها من مديرك:\n{base_url}\n'
    )
    try:
        html = email_templates.render_user_welcome_email(
            recipient, user_name, company_name, base_url,
            brand=email_templates.brand_assets(base_url))
    except Exception:
        html = None
    return send_platform_email(recipient, subject, body, html=html)


def _send_invite_email(invite, tenant, email=None, responsibility=None):
    """Deliver one invite email and record the outcome on the row (t21)."""
    recipient = email or invite.get('email')
    company_name = (tenant and tenant.get('company_name')) or 'الشركة'
    base_url = _current_base_url().rstrip('/')
    full_invite_url = f"{base_url}/invite/{invite['token']}"
    subject = f'دعوة للانضمام إلى {company_name}'
    body = (
        'مرحبًا،\n\n'
        f'تمت دعوتك للانضمام إلى فريق {company_name} في منصة LandLoom AI.\n'
        f'لإكمال التسجيل وتعيين كلمة المرور، يرجى زيارة الرابط التالي:\n{full_invite_url}\n\n'
        'هذا الرابط صالح للاستخدام لمدة 7 أيام.'
    )
    resp = responsibility if responsibility is not None else invite.get('responsibility')
    role_label = {'editor': 'محرر', 'approver': 'معتمد', 'admin': 'أدمن'}.get(resp) or 'موظف'
    try:
        inviter = getattr(g, 'user_name', None) or (tenant or {}).get('account_manager_name')
    except Exception:
        inviter = None
    try:
        html = email_templates.render_user_invite_email(
            recipient, inviter, company_name, role_label, full_invite_url,
            brand=email_templates.brand_assets(base_url))
    except Exception:
        html = None
    ok = send_platform_email(recipient, subject, body, html=html)
    db.mark_invite_email(invite['id'], 'sent' if ok else 'failed',
                         None if ok else (smtp_last_error() or 'smtp_send_failed'))
    return ok


@app.route('/api/admin/smtp-test', methods=['POST'])
@require_admin
def api_admin_smtp_test():
    """Super-admin probe: connect and log in with the server's SMTP settings and,
    when `to` is given, send one test message. Reports the exact failure stage."""
    data = request.json or {}
    settings = _smtp_settings()
    report = {
        'host': settings['host'] or None,
        'port': settings['port'],
        'ssl': settings['ssl'],
        'starttls': settings['starttls'] and not settings['ssl'],
        'user': settings['user'] or None,
        'passwordSet': bool(settings['password']),
        'sender': settings['sender'] or None,
    }
    if not settings['host']:
        return jsonify({'success': False, 'stage': 'config',
                        'error': 'SMTP_HOST is not set in the server environment',
                        'settings': report})
    stage = 'resolve'
    try:
        report['resolvedIp'] = socket.gethostbyname(settings['host'])
        stage = 'connect_login'
        client = _open_smtp_client(settings)
        try:
            to_email = (data.get('to') or '').strip()
            if to_email:
                stage = 'send'
                message = EmailMessage()
                message['Subject'] = 'LandLoom AI - SMTP test'
                message['From'] = settings['sender']
                message['To'] = to_email
                message.set_content('SMTP test message from LandLoom AI.')
                client.send_message(message)
                report['sentTo'] = to_email
        finally:
            try:
                client.quit()
            except Exception:
                pass
    except Exception as exc:
        return jsonify({'success': False, 'stage': stage,
                        'error': f'{type(exc).__name__}: {exc}'[:500],
                        'settings': report})
    return jsonify({'success': True, 'stage': 'done', 'settings': report})
