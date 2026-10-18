

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


# send_platform_email() lives in 14c_platform_mail.py.


# ── Housekeeping: periodic sweeps that used to wait for a human request ──────

_HOUSEKEEPING_LOCK = threading.Lock()
_HOUSEKEEPING_STARTED = False


def _drain_email_outbox(limit=20):
    """t41/t61: the outbox only matters if something sends it — claim due rows,
    push them through SMTP, and record the outcome on the message and on the
    notification's delivery row."""
    sent = failed = 0
    brand = email_templates.brand_assets()
    logos = _platform_logo_images()
    for row in db.claim_due_emails(limit=limit):
        # The outbox stores an optional HTML part; when a row only carries
        # plain text it still leaves inside the branded shell so every email
        # the platform sends arrives in the designed layout.
        html = row.get('body_html')
        if not html and row.get('body_text'):
            try:
                html = email_templates.render_notification_email(
                    row.get('to_email'), row.get('subject'), row.get('body_text'),
                    brand=brand)
            except Exception:
                html = None
        ok = send_platform_email(row.get('to_email'), row.get('subject'),
                                 row.get('body_text') or '', html=html,
                                 inline_images=logos)
        if ok:
            db.mark_email_sent(row['id'])
            db.mark_email_delivery(row.get('notification_id'), 'sent')
            sent += 1
        else:
            reason = smtp_last_error() or 'smtp_send_failed'
            db.mark_email_failed(row['id'], error=reason)
            db.mark_email_delivery(row.get('notification_id'), 'failed',
                                   error=reason)
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


def _trial_watch_sweep():
    """Warn a company once when its trial enters the final days, and once when
    it lapses. Both notices are keyed to the trial end date, so an admin who
    extends the window re-arms the warnings automatically."""
    warned = expired = 0
    with _worker_app_context():
        for tenant in db.get_all_tenants() or []:
            if tenant.get('is_admin') or not tenant.get('is_active'):
                continue
            try:
                state = db.tenant_trial_state(tenant)
            except Exception:
                continue
            kind = {'expiring': 'trial_expiring', 'expired': 'trial_expired'} \
                .get(state.get('state'))
            if not kind:
                continue
            ends = str(state.get('ends_at') or '')
            if db.recent_notification_exists(
                    tenant['id'], kind, ends, since_hours=24 * 3650):
                continue
            if kind == 'trial_expiring':
                title = 'الفترة التجريبية تنتهي قريبًا'
                body = (f'تنتهي تجربة الشركة خلال {state.get("days_left")} يوم '
                        '— راجع الاشتراك لتفادي توقف التوليد.')
            else:
                title = 'انتهت الفترة التجريبية'
                body = ('انتهت تجربة الشركة وتوقف التوليد — '
                        'تواصل مع الإدارة للاشتراك والاستئناف.')
            db.create_notification(
                tenant['id'], title, body=body, category='billing',
                user_id='tenant-admin:' + str(tenant['id']),
                entity_type=kind, entity_id=ends,
                email_to=tenant.get('email'))
            if kind == 'trial_expiring':
                warned += 1
            else:
                expired += 1
    return {'warned': warned, 'expired': expired}


def _run_housekeeping_tick():
    """One bounded pass over every standing sweep: outbound mail, approval-task
    reminders and escalations, stale point holds and silent generation jobs.
    Each step is isolated so one failure never stops the rest."""
    summary = {}
    steps = (
        ('email', _drain_email_outbox),
        ('escalations', db.escalate_overdue_approval_tasks),
        ('subscription_watch', _subscription_watch_sweep),
        ('stale_reservations', db.release_stale_reservations),
        ('stale_generation_jobs', db.sweep_stale_generation_jobs),
        ('dead_generating_drafts', db.recover_dead_generating_drafts),
        ('rate_limits', db.rate_limit_cleanup),
        ('usage_billing', _bill_all_unbilled_usage),
        ('cap_resync', _resync_pending_tenant_caps),
        ('trial_watch', _trial_watch_sweep),
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
                # Single-flight across workers: N gunicorn workers must not run
                # the billing claim and the outbox drain on one SQLite file at
                # the same minute — the losers hold the write lock while draft
                # reads queue behind them and the whole site stalls.
                with _housekeeping_tick_singleflight() as _may_run:
                    if _may_run:
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


# The mail senders (_send_company_welcome_email, _send_user_welcome_email,
# _send_invite_email) live in 14c_platform_mail.py next to the SMTP layer.


def _tenant_package_brief(tenant):
    """Assigned billing-package summary for tenant payloads. Never raises."""
    package_id = (tenant or {}).get('package_id')
    name = None
    name_en = None
    if package_id:
        package = db.get_billing_package(package_id)
        if package:
            name = package.get('name')
            name_en = package.get('name_en')
    return {'packageId': package_id, 'packageName': name,
            'packageNameEn': name_en}


def _company_payload(tenant):
    trial = db.tenant_trial_state(tenant)
    package_remaining = db.get_package_remaining_sar(tenant['id'])
    wallet_sar = float(tenant.get('credit_balance') or 0)
    return {
        'id': tenant['id'],
        'companyName': tenant['company_name'],
        'companyNameEn': tenant.get('company_name_en'),
        'accountManagerName': tenant.get('account_manager_name'),
        'username': tenant.get('username'),
        'phone': tenant.get('phone'),
        'email': tenant['email'],
        'plan': tenant.get('plan', 'free'),
        **_tenant_package_brief(tenant),
        'creditBalance': db.sar_to_usd(tenant.get('credit_balance')),
        'creditBalanceSar': wallet_sar,
        # What the company can actually burn: wallet riyals plus the
        # unburned credit of its assigned package (packages spend first).
        'packageRemainingSar': package_remaining,
        'effectiveBalanceSar': wallet_sar + package_remaining,
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
        'trialState': trial.get('state'),
        'trialDaysLeft': trial.get('days_left'),
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
    'verify_otp:ip': (30, 600, 900),   # otp verification attempts per IP
    'resend_otp:ip': (5, 300, 600),    # otp resend requests per IP
    'join:ip': (5, 3600, 3600),        # landing-page access requests per IP
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
    # A self-serve signup is the one «new company» event the desk did not
    # author — admin-created companies notify nobody.
    _notify_super_admins(
        'شركة جديدة انضمت إلى المنصة', f'«{company_name}» — {email}',
        entity_type='tenant', entity_id=tenant_id)
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
    identity = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    if not identity or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    # ISS-005: the per-account lock is checked before any password work, so a
    # locked identity costs almost nothing to refuse and the counter cannot be
    # reset by guessing on a fresh connection.
    limited = _rate_limit_check('login:id', identity)
    if limited:
        return limited

    tenant = db.get_tenant_by_email(identity)
    user = db.get_user_by_email(identity)

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

        device_id = (data.get('deviceId') or '').strip()
        trusted_token = (data.get('trustedDeviceToken') or '').strip()
        is_testing = app.config.get('TESTING') and not data.get('enforce_otp') and not request.headers.get('X-Enforce-OTP')

        if not is_testing and not db.is_device_trusted(tenant['id'], device_id, trusted_token):
            otp_code = generate_login_otp()
            challenge = db.create_otp_challenge(tenant['id'], tenant['email'], otp_code)
            send_login_otp_email(tenant['email'], otp_code, company_name=tenant.get('company_name'))
            return jsonify({
                'success': False,
                'otpRequired': True,
                'challengeToken': challenge['challenge_token'],
                'maskedEmail': _mask_email(tenant['email']),
            }), 200

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
                'companyNameEn': tenant.get('company_name_en'),
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

        device_id = (data.get('deviceId') or '').strip()
        trusted_token = (data.get('trustedDeviceToken') or '').strip()
        is_testing = app.config.get('TESTING') and not data.get('enforce_otp') and not request.headers.get('X-Enforce-OTP')

        if not is_testing and not db.is_device_trusted(user['tenant_id'], device_id, trusted_token, user_id=user['id']):
            otp_code = generate_login_otp()
            challenge = db.create_otp_challenge(user['tenant_id'], user['email'], otp_code, user_id=user['id'])
            send_login_otp_email(user['email'], otp_code)
            return jsonify({
                'success': False,
                'otpRequired': True,
                'challengeToken': challenge['challenge_token'],
                'maskedEmail': _mask_email(user['email']),
            }), 200

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
                'companyNameEn': tenant.get('company_name_en'),
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
    trial = db.tenant_trial_state(t)
    result = {
        'success': True,
        'tenant': {
            'id': t['id'],
            'companyName': t['company_name'],
            'companyNameEn': t.get('company_name_en'),
            'email': t['email'],
            'isAdmin': bool(g.is_admin),
            'plan': t.get('plan', 'free'),
            **_tenant_package_brief(t),
            'subdomain': t.get('subdomain'),
            'domain': t.get('domain'),
            'slug': db.tenant_slug(t),
            'trialEndsAt': t.get('trial_ends_at'),
            'trialState': trial.get('state'),
            'trialDaysLeft': trial.get('days_left'),
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
