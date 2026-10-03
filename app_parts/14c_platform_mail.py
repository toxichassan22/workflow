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
