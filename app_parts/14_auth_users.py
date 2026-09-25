

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


def _is_public_base_url(url):
    if not url or 'sagdemos.store' in url:
        return False
    return not re.search(r'localhost|127\.0\.0\.1|0\.0\.0\.0', url)


def _current_base_url():
    """The public base URL links in outgoing mail should point at.

    Each server carries its own public URL in APP_BASE_URL (staging =
    lab host, production = main host), while gunicorn behind Apache only
    sees 127.0.0.1. Prefer the configured public URL, then the proxy
    headers, then the live request host. A loopback address is only a last
    resort: it is unreachable from any other machine. The legacy host is
    dead and is never emitted.
    """
    try:
        req_base = (request.host_url or '').strip().rstrip('/')
    except Exception:
        req_base = ''
    try:
        fwd_host = (request.headers.get('X-Forwarded-Host', '') or '').split(',')[0].strip()
        fwd_proto = (request.headers.get('X-Forwarded-Proto', '') or '').split(',')[0].strip()
    except Exception:
        fwd_host = ''
        fwd_proto = ''
    fwd_base = ''
    if fwd_host:
        scheme = fwd_proto if fwd_proto in ('http', 'https') else 'https'
        fwd_base = f'{scheme}://{fwd_host}'.rstrip('/')
    env_base = (os.environ.get('APP_BASE_URL') or '').strip().rstrip('/')
    base_url = ''
    for candidate in (env_base, fwd_base, req_base):
        if _is_public_base_url(candidate):
            base_url = candidate
            break
    if not base_url:
        base_url = fwd_base or req_base or env_base
    if base_url.startswith('http://') and _is_public_base_url(base_url):
        base_url = 'https://' + base_url[len('http://'):]
    return base_url


def _password_setup_url(raw_token):
    return f'{_current_base_url()}/set-password/{raw_token}'


def send_platform_email(recipient, subject, body):
    host = (os.environ.get('SMTP_HOST') or '').strip()
    if not host or not recipient:
        return False
    port = int(os.environ.get('SMTP_PORT') or 587)
    smtp_user = (os.environ.get('SMTP_USER') or '').strip()
    smtp_password = os.environ.get('SMTP_PASSWORD') or ''
    sender = (os.environ.get('SMTP_FROM') or smtp_user or 'noreply@landloom.ai').strip()
    if not sender:
        return False
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = sender
    message['To'] = recipient
    message.set_content(body)
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
        app.logger.exception('Platform email could not be sent')
        return False


# ── Housekeeping: periodic sweeps that used to wait for a human request ──────

_HOUSEKEEPING_LOCK = threading.Lock()
_HOUSEKEEPING_STARTED = False


def _drain_email_outbox(limit=20):
    """t41/t61: the outbox only matters if something sends it — claim due rows,
    push them through SMTP, and record the outcome on the message and on the
    notification's delivery row."""
    sent = failed = 0
    for row in db.claim_due_emails(limit=limit):
        ok = send_platform_email(row.get('to_email'), row.get('subject'),
                                 row.get('body_text') or '')
        if ok:
            db.mark_email_sent(row['id'])
            db.mark_email_delivery(row.get('notification_id'), 'sent')
            sent += 1
        else:
            db.mark_email_failed(row['id'], error='smtp_send_failed')
            db.mark_email_delivery(row.get('notification_id'), 'failed',
                                   error='smtp_send_failed')
            failed += 1
    return {'sent': sent, 'failed': failed}


def _bill_tenant_unbilled_usage(tenant_id):
    """Checkout one tenant's billable usage. Best-effort: an overdrawn scope
    just stays unbilled for the next sweep — it is already capped upstream
    by the provider key limit."""
    try:
        result = db.bill_unbilled_usage(tenant_id)
    except db.InsufficientBalance:
        return {'billed': False, 'reason': 'insufficient_balance'}
    except Exception as exc:
        return {'billed': False, 'reason': f'error:{exc}'}
    return {'billed': bool(result.get('billed')), 'reason': result.get('reason')}


def _bill_all_unbilled_usage():
    """Housekeeping step: convert every tenant's settled spend into a wallet
    debit, so usage outside the reservation flow is collected automatically
    instead of accumulating unbilled forever."""
    billed = skipped = 0
    for tenant_id in db.list_tenants_with_billable_usage():
        outcome = _bill_tenant_unbilled_usage(tenant_id)
        if outcome.get('billed'):
            billed += 1
        else:
            skipped += 1
    return {'tenants_billed': billed, 'tenants_skipped': skipped}


def _bill_tenant_unbilled_usage_async(tenant_id):
    """Post-settlement convenience: bill right after a run's escrow resolves
    instead of waiting for the sweep tick."""
    if not tenant_id:
        return

    def _run():
        try:
            with app.app_context():
                _bill_tenant_unbilled_usage(tenant_id)
        except Exception as exc:
            print(f"[BILLING] post-settle billing failed for {tenant_id}: {exc}")

    try:
        threading.Thread(target=_run, daemon=True,
                         name=f'usage-bill-{str(tenant_id)[:8]}').start()
    except Exception as exc:
        print(f"[BILLING] usage billing spawn failed: {exc}")


def _run_housekeeping_tick():
    """One bounded pass over every standing sweep: outbound mail, approval-task
    reminders and escalations, stale point holds and silent generation jobs.
    Each step is isolated so one failure never stops the rest."""
    summary = {}
    steps = (
        ('email', _drain_email_outbox),
        ('reminders', db.send_due_approval_reminders),
        ('escalations', db.escalate_overdue_approval_tasks),
        ('event_task_reminders', db.send_due_event_task_reminders),
        ('stale_reservations', db.release_stale_reservations),
        ('stale_generation_jobs', db.sweep_stale_generation_jobs),
        ('dead_generating_drafts', db.recover_dead_generating_drafts),
        ('rate_limits', db.rate_limit_cleanup),
        ('usage_billing', _bill_all_unbilled_usage),
        ('cap_resync', _resync_pending_tenant_caps),
    )
    for name, fn in steps:
        try:
            summary[name] = fn()
        except Exception as exc:
            summary[name] = {'error': str(exc)}
    return summary


def _housekeeping_loop():
    interval = max(60, int(os.environ.get('HOUSEKEEPING_INTERVAL_SECONDS') or 300))
    try:
        with app.app_context():
            resumed = _resume_interrupted_jobs()
            if resumed:
                print(f'[HOUSEKEEPING] resumed {resumed} interrupted job(s)')
    except Exception as exc:
        print(f'[HOUSEKEEPING] job resume sweep failed: {exc}')
    while True:
        try:
            with app.app_context():
                _run_housekeeping_tick()
        except Exception as exc:
            print(f'[HOUSEKEEPING] tick failed: {exc}')
        try:
            time.sleep(interval)
        except Exception:
            pass


def _ensure_housekeeping_started():
    """Start the single sweeper thread once, on the first request — works under
    app.run and any WSGI runner, and stays off for tests and CLI imports."""
    global _HOUSEKEEPING_STARTED
    if _HOUSEKEEPING_STARTED:
        return
    try:
        if app.config.get('TESTING'):
            return
    except Exception:
        pass
    if str(os.environ.get('HOUSEKEEPING_DISABLED') or '').lower() in {'1', 'true', 'yes'}:
        return
    with _HOUSEKEEPING_LOCK:
        if _HOUSEKEEPING_STARTED:
            return
        _HOUSEKEEPING_STARTED = True
        threading.Thread(target=_housekeeping_loop, daemon=True, name='housekeeping').start()


@app.before_request
def start_housekeeping_once():
    _ensure_housekeeping_started()


def _send_company_welcome_email(recipient, company_name, account_name, username, setup_url):
    subject = f'مرحبًا بك في LandLoom AI - {company_name}'
    body = (
        f'مرحبًا {account_name}\n\n'
        f'تم إنشاء حساب شركتك {company_name} في منصة LandLoom AI.\n'
        f'اسم المستخدم: {username}\n'
        f'رابط تعيين كلمة المرور: {setup_url}\n\n'
        'هذا الرابط صالح للاستخدام مرة واحدة.'
    )
    return send_platform_email(recipient, subject, body)


def _company_payload(tenant):
    return {
        'id': tenant['id'],
        'companyName': tenant['company_name'],
        'accountManagerName': tenant.get('account_manager_name'),
        'username': tenant.get('username'),
        'phone': tenant.get('phone'),
        'email': tenant['email'],
        'plan': tenant.get('plan', 'free'),
        'creditBalance': db.sar_to_usd(tenant.get('credit_balance')),
        'creditBalanceSar': float(tenant.get('credit_balance') or 0),
        'isActive': bool(tenant.get('is_active')),
        'isAdmin': bool(tenant.get('is_admin')),
        'primaryUserId': tenant.get('primary_user_id'),
        'requirePasswordChange': bool(tenant.get('require_password_change')),
        'subdomain': tenant.get('subdomain'),
        'domain': tenant.get('domain'),
        'slug': db.tenant_slug(tenant),
        'createdAt': tenant.get('created_at'),
        'legalName': tenant.get('legal_name'),
        'commercialName': tenant.get('commercial_name'),
        'taxNumber': tenant.get('tax_number'),
        'crNumber': tenant.get('cr_number'),
        'country': tenant.get('country'),
        'region': tenant.get('region'),
        'address': tenant.get('address'),
        'contactTitle': tenant.get('contact_title'),
        'activatedAt': tenant.get('activated_at'),
        'activatedByName': tenant.get('activated_by_name'),
        'trialEndsAt': tenant.get('trial_ends_at'),
        'deactivatedReason': tenant.get('deactivated_reason'),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ISS-005: in-app attempt limits for the credential-bearing endpoints. The app
# used to rely entirely on whatever the hosting layer did; these buckets bound
# password guessing, registration spam and setup-link
# probing inside the app itself. Counters live in ``rate_limit_buckets`` so every
# gunicorn worker shares them. A limiter that errors fails open — a broken
# counter must never turn into a site-wide lockout.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# name -> (max_attempts, window_seconds, lock_seconds)
AUTH_RATE_LIMITS = {
    'login:ip': (60, 600, 900),        # login requests per source IP
    'login:id': (5, 600, 900),         # failed passwords per account
    'register:ip': (10, 3600, 3600),   # public sign-ups per source IP
    'invite:ip': (30, 600, 900),       # invite lookups/registrations per IP
    'pwsetup:ip': (20, 600, 900),      # password-setup token probes per IP
}


def _rate_limit_client_ip():
    return (request.remote_addr or 'unknown').strip() or 'unknown'


def _rate_limited(retry_seconds):
    retry = max(1, int(math.ceil(retry_seconds or 0)))
    response = jsonify({
        'error': 'عدد المحاولات كبير، أعد المحاولة لاحقًا',
        'error_code': 'rate_limited',
        'retryAfter': retry,
    })
    response.status_code = 429
    response.headers['Retry-After'] = str(retry)
    return response


def _rate_limit_check(name, subject):
    """A 429 response when the bucket is locked, else None. Never raises."""
    try:
        retry = db.rate_limit_status(f'{name}:{subject}')
    except Exception as exc:
        print(f'[RATE-LIMIT] status check failed for {name}: {exc}')
        return None
    return _rate_limited(retry) if retry > 0 else None


def _rate_limit_attempt(name, subject):
    """Record one attempt; a 429 response when it trips the limit. Never raises."""
    max_attempts, window_seconds, lock_seconds = AUTH_RATE_LIMITS[name]
    try:
        retry = db.rate_limit_hit(
            f'{name}:{subject}', max_attempts, window_seconds, lock_seconds)
    except Exception as exc:
        print(f'[RATE-LIMIT] hit failed for {name}: {exc}')
        return None
    return _rate_limited(retry) if retry > 0 else None


def _rate_limit_clear(name, subject):
    """Wipe the bucket after a success so earlier typos stop counting."""
    try:
        db.rate_limit_reset(f'{name}:{subject}')
    except Exception as exc:
        print(f'[RATE-LIMIT] reset failed for {name}: {exc}')


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """Register a new company (tenant). Creates company admin user automatically."""
    limited = _rate_limit_attempt('register:ip', _rate_limit_client_ip())
    if limited:
        return limited
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
    password_error = _password_validation_error(password)
    if password_error:
        return jsonify({'error': password_error}), 400
    if subdomain and not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', subdomain):
        return jsonify({'error': 'Invalid subdomain'}), 400
    if domain and not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,}', domain):
        return jsonify({'error': 'Invalid domain (e.g. landloom.ai)'}), 400

    if db.get_tenant_by_email(email):
        return jsonify({'error': 'Email already registered'}), 409
    if subdomain and db.get_tenant_by_subdomain(subdomain):
        return jsonify({'error': 'Subdomain already taken'}), 409
    if domain and db.get_tenant_by_domain(domain):
        return jsonify({'error': 'Domain already registered'}), 409

    try:
        # One hash feeds both rows — the primary admin is a single login
        # identity, so its two records start with identical credentials (ISS-002).
        password_hash = hash_password(password)
        tenant_id = db.create_tenant(company_name, email, password_hash, subdomain=subdomain)
        if domain:
            db.update_tenant(tenant_id, **{'settings_json': json.dumps({'domain': domain})})
            conn = db.get_db()
            conn.execute('UPDATE tenants SET domain = ? WHERE id = ?', (domain, tenant_id))
            conn.commit()
        user_id = db.create_user(
            tenant_id, company_name, email, password_hash, role='employee'
        )
        db.grant_company_admin_permissions(user_id)
        db.update_tenant(
            tenant_id,
            primary_user_id=user_id,
            account_manager_name=company_name,
        )
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or subdomain already registered'}), 409
    token = create_token(tenant_id, email, is_admin=False, user_id=None, user_name=company_name,
                         user_role='company_admin')
    return jsonify({
        'success': True,
        'token': token,
        'tenant': {'id': tenant_id, 'companyName': company_name, 'email': email, 'domain': domain,
                   'slug': db.tenant_slug({'id': tenant_id, 'subdomain': subdomain, 'username': None})}
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Login a company admin (tenant) or employee (user). Auto-detects by email domain."""
    limited = _rate_limit_attempt('login:ip', _rate_limit_client_ip())
    if limited:
        return limited
    data = request.json or {}
    identity = (data.get('email') or data.get('username') or '').strip().lower()
    password = data.get('password', '')

    if not identity or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    # ISS-005: the per-account lock is checked before any password work, so a
    # locked identity costs almost nothing to refuse and the counter cannot be
    # reset by guessing on a fresh connection.
    limited = _rate_limit_check('login:id', identity)
    if limited:
        return limited

    tenant = db.get_tenant_by_email(identity) or db.get_tenant_by_username(identity)
    user = db.get_user_by_email(identity) or db.get_user_by_username(identity)

    # ISS-002: the primary company admin is a single login identity owned by
    # the tenants row; its users row is the management record whose live state
    # still gates whether the owner login may run at all.
    primary = None
    if tenant and tenant.get('primary_user_id'):
        candidate = db.get_user_by_id(tenant['primary_user_id'])
        if candidate and str(candidate.get('tenant_id')) == str(tenant['id']):
            primary = candidate
    elif not tenant and user and user.get('is_active'):
        owning = db.get_tenant_by_id(user['tenant_id'])
        if owning and owning.get('primary_user_id') == user['id']:
            tenant, primary, user = owning, user, None

    owner_login_open = bool(
        tenant and (
            not tenant.get('primary_user_id')
            or (primary is not None and primary.get('is_active'))
        )
    )
    credential_ok = False
    if owner_login_open:
        if primary is not None:
            # The primary's users row is the live credential record: a tenant
            # hash that drifted from it is stale and must not authenticate
            # (ISS-002). A verified password whose tenant copy lagged adopts
            # the user hash, converging the pair.
            credential_ok = verify_password(password, primary.get('password_hash') or '')
            if credential_ok and not verify_password(password, tenant['password_hash'] or ''):
                db.update_tenant(tenant['id'], password_hash=primary['password_hash'])
        else:
            credential_ok = verify_password(password, tenant['password_hash'])
    if credential_ok:
        _rate_limit_clear('login:id', identity)
        if not tenant.get('is_active'):
            return jsonify({'error': 'Account is deactivated'}), 403
        if tenant.get('require_password_change'):
            return jsonify({
                'error': 'Password setup required',
                'code': 'PASSWORD_SETUP_REQUIRED',
            }), 403
        token = create_token(tenant['id'], tenant['email'], is_admin=bool(tenant.get('is_admin')),
                             user_name=tenant['company_name'], user_role='company_admin')
        db.record_login(tenant['id'])
        if primary is not None:
            db.record_login(tenant['id'], primary['id'])
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

    if user and verify_password(password, user['password_hash']):
        _rate_limit_clear('login:id', identity)
        if not user.get('is_active'):
            return jsonify({'error': 'Account is deactivated'}), 403
        if not user.get('tenant_active'):
            return jsonify({'error': 'Company account is deactivated'}), 403
        if user.get('require_password_change'):
            return jsonify({
                'error': 'Password setup required',
                'code': 'PASSWORD_SETUP_REQUIRED',
            }), 403
        token = create_token(user['tenant_id'], user['email'], is_admin=False,
                             user_id=user['id'], user_name=user['name'], user_role=user['role'])
        db.record_login(user['tenant_id'], user['id'])
        tenant = db.get_tenant_by_id(user['tenant_id'])
        return jsonify({
            'success': True,
            'token': token,
            'tenant': {
                'id': tenant['id'],
                'companyName': tenant['company_name'],
                'email': tenant['email'],
                'isAdmin': False,
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

    limited = _rate_limit_attempt('login:id', identity)
    if limited:
        return limited
    return jsonify({'error': 'Invalid email or password'}), 401


@app.route('/api/auth/password-setup/<raw_token>', methods=['GET'])
def api_password_setup_details(raw_token):
    limited = _rate_limit_attempt('pwsetup:ip', _rate_limit_client_ip())
    if limited:
        return limited
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
    limited = _rate_limit_attempt('pwsetup:ip', _rate_limit_client_ip())
    if limited:
        return limited
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
    if not tenant or not user:
        return jsonify({'error': 'Password setup link is invalid or expired'}), 404
    db.record_login(tenant['id'], user['id'])
    token = create_token(
        tenant['id'], user['email'], is_admin=False,
        user_id=user['id'], user_name=user['name'], user_role=user['role'],
    )
    tenant_payload = _company_payload(tenant)
    tenant_payload['isAdmin'] = False
    return jsonify({
        'success': True,
        'token': token,
        'tenant': tenant_payload,
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
            'isAdmin': bool(g.is_admin),
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
    token = create_token(t['id'], t['email'], is_admin=bool(g.is_admin),
                         user_id=g.user_id, user_name=g.user_name, user_role=g.user_role)
    return jsonify({'success': True, 'token': token})


@app.route('/api/auth/logout', methods=['POST'])
@require_auth
def api_logout():
    """Revoke the presented session token server-side; the client also drops it."""
    payload = getattr(g, 'token_payload', None) or {}
    if payload.get('jti'):
        db.revoke_token_jti(payload['jti'], g.tenant_id, payload.get('exp'))
    return jsonify({'success': True})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# USER MANAGEMENT ENDPOINTS (company admin only)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/users', methods=['GET'])
@require_permission('manage_users')
def api_list_users():
    """List all users in the tenant; the primary row is flagged as the admin."""
    users = db.get_users_by_tenant(g.tenant_id)
    primary_id = str((g.tenant or {}).get('primary_user_id') or '')
    for u in users:
        u['is_primary'] = str(u.get('id')) == primary_id
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
    password_error = _password_validation_error(password)
    if password_error:
        return jsonify({'error': password_error}), 400
    if role not in db.USER_ROLES:
        return jsonify({'error': 'Invalid role'}), 400

    existing = db.get_user_by_email(email)
    if existing:
        return jsonify({'error': 'Email already in use'}), 409

    try:
        user_id = db.create_user(g.tenant_id, name, email, hash_password(password), role=role,
                                 phone=(data.get('phone') or '').strip() or None,
                                 username=(data.get('username') or '').strip() or None)
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email already in use'}), 409
    _apply_user_scope_payload(user_id, data)
    return jsonify({'success': True, 'userId': user_id}), 201


def _apply_user_scope_payload(user_id, data):
    """Optional sections/projects restrictions on create or update (t20/t21).

    ``sections`` names the field sections the user may see — everything else is
    switched off. ``projects`` names the drafts they may act on; an empty list
    lifts the restriction entirely.
    """
    sections = data.get('sections')
    if isinstance(sections, list) and sections:
        allowed = set(str(s) for s in sections)
        for key in db.get_user_field_sections(user_id, g.tenant_id):
            db.set_user_field_section(user_id, key, key in allowed)
    projects = data.get('projects')
    if isinstance(projects, list):
        db.set_user_project_scope(g.tenant_id, user_id, [str(p) for p in projects])


@app.route('/api/users/<user_id>', methods=['PUT'])
@require_permission('manage_users')
def api_update_user(user_id):
    """Update a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404

    # t21-03: the primary row IS the company's admin identity — every editable
    # field on it (password, email, username, name, phone) mirrors onto the
    # tenants login row. Only the tenant-direct session or the super admin may
    # touch it; an employee holding manage_users must not rewrite the company's
    # own credentials.
    if db.is_primary_company_admin(g.tenant_id, user_id) and g.user_id is not None:
        return jsonify({'error': 'لا يمكن تعديل مدير الشركة الأساسي',
                        'error_code': 'primary_company_admin'}), 403

    data = request.json or {}
    updates = {}
    for k in ['name', 'email', 'role', 'is_active']:
        if k in data:
            updates[k] = data[k]
    if updates.get('role') is not None and updates['role'] not in db.USER_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    if 'password' in data and data['password']:
        password_error = _password_validation_error(data['password'])
        if password_error:
            return jsonify({'error': password_error}), 400
        updates['password_hash'] = hash_password(data['password'])
        updates['require_password_change'] = 0

    # Even the tenant-direct session must not disable the primary row through
    # user management — it would lock the company's owner login out.
    if db.is_primary_company_admin(g.tenant_id, user_id) \
            and 'is_active' in updates and not updates['is_active']:
        return jsonify({'error': 'لا يمكن تعطيل مدير الشركة الأساسي',
                        'error_code': 'primary_company_admin'}), 400

    db.update_user(user_id, **updates)
    _apply_user_scope_payload(user_id, data)
    return jsonify({'success': True})


@app.route('/api/users/<user_id>', methods=['DELETE'])
@require_permission('manage_users')
def api_delete_user(user_id):
    """Delete a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    if db.is_primary_company_admin(g.tenant_id, user_id):
        return jsonify({'error': 'لا يمكن حذف مدير الشركة الأساسي',
                        'error_code': 'primary_company_admin'}), 400
    db.delete_user(user_id)
    return jsonify({'success': True})


@app.route('/api/users/<user_id>/project-scope', methods=['GET'])
@require_permission('manage_users')
def api_get_user_project_scope(user_id):
    """The drafts a scoped user may act on, plus every draft for the picker."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    scope = sorted(db.get_user_project_scope_ids(user_id))
    drafts = [
        {'id': item['id'], 'title': item.get('title'), 'status': item.get('status')}
        for item in db.get_all_project_draft_summaries(g.tenant_id, limit=200)
    ]
    return jsonify({'success': True, 'scope': scope, 'limited': bool(scope), 'drafts': drafts})


@app.route('/api/users/<user_id>/project-scope', methods=['PUT'])
@require_permission('manage_users')
def api_set_user_project_scope(user_id):
    """Replace the user's draft scope; an empty list lifts the restriction."""
    data = request.json or {}
    draft_ids = data.get('draftIds', data.get('projects'))
    if not isinstance(draft_ids, list):
        return jsonify({'error': 'draftIds must be a list'}), 400
    result = db.set_user_project_scope(g.tenant_id, user_id, [str(d) for d in draft_ids])
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('user.project_scope_set', 'user', user_id,
                        new_value=result.get('scope'))
    return jsonify({'success': True, **result})


@app.route('/api/users/<user_id>/permissions', methods=['GET'])
@require_permission('manage_users')
def api_get_user_permissions(user_id):
    """Get effective permissions for a user."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    perms = db.get_user_permissions(user_id, user.get('role', 'employee'))
    keys = [k for k in db.PERMISSION_KEYS if k != 'sag_admin_panel']
    return jsonify({'success': True, 'permissions': perms, 'availableKeys': keys})


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
        if key not in db.PERMISSION_KEYS or key == 'sag_admin_panel':
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
        # The tenant-direct session holds every company permission; the
        # platform panel key stays super-admin only.
        perms = {k: True for k in db.PERMISSION_KEYS if k != 'sag_admin_panel' or g.is_admin}
    return jsonify({'success': True, 'permissions': perms, 'role': g.user_role})


@app.route('/api/field-sections', methods=['GET'])
@require_auth
def api_get_field_sections():
    """Get available field sections (built-in + custom) and current user's allowed sections."""
    available = db.get_all_sections(g.tenant_id)
    allowed = db.get_user_field_sections(g.user_id, g.tenant_id) if g.user_id else {s['key']: True for s in available}
    return jsonify({'success': True, 'available': available, 'allowed': allowed})


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


def _send_invite_email(invite, tenant, email=None):
    """Deliver one invite email and record the outcome on the row (t21)."""
    recipient = email or invite.get('email')
    company_name = (tenant and tenant.get('company_name')) or 'الشركة'
    base_url = _current_base_url().rstrip('/')
    full_invite_url = f"{base_url}/invite/{invite['token']}"
    ok = send_platform_email(
        recipient,
        f'دعوة للانضمام إلى {company_name}',
        f'مرحبًا،\n\nتمت دعوتك للانضمام إلى فريق {company_name} في منصة LandLoom AI.\n'
        f'لإكمال التسجيل وتعيين كلمة المرور، يرجى زيارة الرابط التالي:\n{full_invite_url}\n\n'
        'هذا الرابط صالح للاستخدام لمدة 7 أيام.'
    )
    db.mark_invite_email(invite['id'], 'sent' if ok else 'failed',
                         None if ok else 'smtp_send_failed')
    return ok


@app.route('/api/invites', methods=['POST'])
@require_permission('manage_users')
def api_create_invite():
    """Create an invite carrying the pre-assigned role and scope (t21)."""
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    if not email or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Valid email required'}), 400
    role = data.get('role') or 'employee'
    if role not in db.USER_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    invite = db.create_invite(
        g.tenant_id, email,
        role=role,
        name=data.get('name'), phone=data.get('phone'),
        sections=data.get('sections') if isinstance(data.get('sections'), list) else None,
        projects=data.get('projects') if isinstance(data.get('projects'), list) else None,
    )
    tenant = db.get_tenant_by_id(g.tenant_id)
    email_sent = _send_invite_email(invite, tenant, email)
    invite_url = f"/invite/{invite['token']}"
    _record_audit_event('invite.created', 'invite_link', invite['id'], entity_name=email,
                        metadata={'role': role, 'email_sent': email_sent})
    return jsonify({'success': True, 'inviteUrl': invite_url, 'token': invite['token'],
                    'inviteId': invite['id'], 'emailSent': email_sent})


@app.route('/api/invite/<token>', methods=['GET'])
def api_get_invite(token):
    """Get invite info (public, no auth needed)."""
    limited = _rate_limit_attempt('invite:ip', _rate_limit_client_ip())
    if limited:
        return limited
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
    limited = _rate_limit_attempt('invite:ip', _rate_limit_client_ip())
    if limited:
        return limited
    invite = db.get_invite_by_token(token)
    if not invite:
        return jsonify({'error': 'Invalid or expired invite'}), 404

    data = request.json or {}
    name = (data.get('name') or invite.get('name') or '').strip()
    password = data.get('password', '')
    if not password:
        return jsonify({'error': 'password is required'}), 400
    password_error = _password_validation_error(password)
    if password_error:
        return jsonify({'error': password_error}), 400

    existing = db.get_user_by_email(invite['email'])
    if existing:
        return jsonify({'error': 'Email already registered'}), 409

    # The invite fixes the role and scope; the registrant only picks a name and
    # password (t21). The name defaults to the one the admin typed on the invite.
    invite_role = invite.get('role') if invite.get('role') in db.USER_ROLES else 'employee'
    if not name:
        return jsonify({'error': 'name is required'}), 400
    user_id = db.create_user(
        invite['tenant_id'], name, invite['email'], hash_password(password),
        role=invite_role, phone=invite.get('phone'),
    )
    try:
        db.apply_invite_scope(user_id, invite)
    except Exception:
        pass
    db.mark_invite_used(token)
    db.record_login(invite['tenant_id'], user_id)

    tenant = db.get_tenant_by_id(invite['tenant_id'])
    jwt_token = create_token(tenant['id'], invite['email'], is_admin=False,
                             user_id=user_id, user_name=name, user_role=invite_role)
    return jsonify({
        'success': True,
        'token': jwt_token,
        'tenant': {
            'id': tenant['id'],
            'companyName': tenant['company_name'],
            'email': tenant['email'],
        },
        'user': {'id': user_id, 'name': name, 'email': invite['email'], 'role': invite_role}
    }), 201


@app.route('/api/invites/<invite_id>/resend', methods=['POST'])
@require_permission('manage_users')
def api_resend_invite(invite_id):
    """Retry the invite email for a still-pending invite (t21)."""
    invite = db.get_invite(g.tenant_id, invite_id)
    if not invite:
        return jsonify({'error': 'Invite not found'}), 404
    if invite.get('used_at'):
        return jsonify({'error': 'Invite already used'}), 409
    try:
        expired = invite.get('expires_at') and datetime.fromisoformat(invite['expires_at']) < datetime.now(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        expired = False
    if expired:
        return jsonify({'error': 'Invite already expired'}), 409
    tenant = db.get_tenant_by_id(g.tenant_id)
    sent = _send_invite_email(invite, tenant)
    _record_audit_event('invite.resent', 'invite_link', invite_id,
                        entity_name=invite.get('email'), metadata={'email_sent': sent})
    return jsonify({'success': True, 'emailSent': sent,
                    'emailAttempts': int(invite.get('email_attempts') or 0) + 1})
