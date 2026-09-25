


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Super-admin tenant and tenant-user administration: company
# create/list/update/delete, tenant detail and user management, per-user
# permissions and field sections, reset-password, and the read panes over a
# tenant's drafts, presentations, exports, activity and agent — the reads
# run under _require_admin_content_access so client content is only served
# under an active grant.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@app.route('/api/admin/tenants', methods=['GET', 'POST'])
@require_admin
def api_admin_tenants():
    """List or create tenant companies."""
    if request.method == 'POST':
        data = request.json or {}
        company_name = (data.get('companyName') or '').strip()
        manager_name = (data.get('accountManagerName') or '').strip()
        email = (data.get('email') or '').strip().lower()
        username = (data.get('username') or '').strip().lower()
        phone = _normalize_phone(data.get('phone'))
        plan = (data.get('plan') or 'free').strip().lower()
        password_mode = data.get('passwordMode') or 'set_link'
        password = data.get('password') or ''
        is_active = bool(data.get('isActive', True))
        send_welcome = bool(data.get('sendWelcomeEmail', True))
        # Wallet funding is package-only — a new company always starts empty;
        # any creditBalance*/credit_balance field on the payload is ignored so
        # no unledgered money can be minted through this route.
        credit_balance = 0.0

        if not company_name or not manager_name or not email or not username or not phone:
            return jsonify({'error': 'All company and account fields are required'}), 400
        if len(company_name) > 120 or len(manager_name) > 120:
            return jsonify({'error': 'Company or account manager name is too long'}), 400
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            return jsonify({'error': 'Invalid email address'}), 400
        if not USERNAME_RE.fullmatch(username):
            return jsonify({'error': 'Invalid username'}), 400
        if not PHONE_RE.fullmatch(phone):
            return jsonify({'error': 'Invalid phone number'}), 400
        if plan not in ADMIN_COMPANY_PLANS:
            return jsonify({'error': 'Invalid plan'}), 400
        conflict = _identity_conflict(email, username)
        if conflict:
            return jsonify({'error': conflict}), 409
        slug = (data.get('slug') or '').strip().lower() or None
        if slug:
            verdict = db.validate_company_slug(slug)
            if 'error' in verdict:
                return jsonify({'error': 'slug_' + verdict['error']}), 409
            slug = verdict['slug']
        package_id = data.get('packageId') or None
        trial_days = data.get('trialDays')
        try:
            trial_days = int(trial_days) if trial_days not in (None, '') else None
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid trial days'}), 400
        profile = {}
        for input_key, db_key in _COMPANY_PROFILE_KEY_MAP.items():
            value = data.get(input_key)
            if value is None:
                value = data.get(db_key)
            if value is not None:
                profile[db_key] = str(value).strip()
        if password_mode == 'manual':
            password_error = _password_validation_error(password)
            if password_error:
                return jsonify({'error': password_error}), 400
            require_password_change = False
        elif password_mode == 'set_link':
            password = _generate_secure_password()
            require_password_change = True
        else:
            return jsonify({'error': 'Invalid password mode'}), 400

        try:
            tenant_id, user_id = db.create_company_with_admin(
                company_name, manager_name, email, username, phone,
                hash_password(password), plan=plan, credit_balance=credit_balance,
                is_active=is_active, require_password_change=require_password_change,
                profile=profile, slug=slug, package_id=package_id,
                trial_days=trial_days,
            )
        except db_driver.IntegrityError:
            return jsonify({'error': 'Email or username already registered'}), 409
        except ValueError:
            return jsonify({'error': 'slug_invalid'}), 400

        setup_token = db.create_password_setup_token(tenant_id, user_id)
        setup_url = _password_setup_url(setup_token)
        email_sent = False
        if send_welcome:
            email_sent = _send_company_welcome_email(
                email, company_name, manager_name, username, setup_url
            )
        # Best-effort managed OpenRouter key so the company spends on its own
        # dashboard-visible limit from day one. Never fails tenant creation —
        # the outcome rides the response so a silent miss is visible.
        key_provisioned = False
        try:
            provisioned = _ensure_tenant_openrouter_key(
                tenant_id, limit_usd=_tenant_provider_cap_usd(tenant_id))
            key_provisioned = bool(provisioned and provisioned.get('is_active'))
        except Exception as exc:
            print(f"[OPENROUTER KEYS] auto-provision on create failed: {exc}")
        tenant = db.get_tenant_by_id(tenant_id)
        # No «new company» notice: the desk created it — a notification would
        # only echo the admin's own click back at them.
        return jsonify({
            'success': True,
            'tenant': _company_payload(tenant),
            'setupUrl': setup_url,
            'welcomeEmailSent': email_sent,
            'keyProvisioned': key_provisioned,
        }), 201

    tenants = db.get_all_tenants()
    result = [_company_payload(tenant) for tenant in tenants]
    key_states = db.list_tenant_key_states()
    for payload in result:
        state = key_states.get(payload['id']) or {}
        payload['keyActive'] = bool(state.get('has_key') and state.get('is_active'))
    return jsonify({'success': True, 'tenants': result})


@app.route('/api/admin/tenants/<tenant_id>', methods=['PUT'])
@require_admin
def api_admin_update_tenant(tenant_id):
    """Update a tenant (admin only)."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    data = request.json or {}
    company_fields = {}
    account_fields = {}
    key_map = {
        'companyName': 'company_name',
        'accountManagerName': 'account_manager_name',
        'username': 'username',
        'phone': 'phone',
        'email': 'email',
        'plan': 'plan',
        'isActive': 'is_active',
    }
    for input_key, db_key in key_map.items():
        if input_key in data:
            company_fields[db_key] = data[input_key]
    for db_key in ['company_name', 'account_manager_name', 'username', 'phone', 'email',
                   'plan', 'is_active']:
        if db_key in data:
            company_fields[db_key] = data[db_key]
    for input_key, db_key in _COMPANY_PROFILE_KEY_MAP.items():
        if input_key in data:
            company_fields[db_key] = str(data[input_key] or '').strip()
        elif db_key in data:
            company_fields[db_key] = str(data[db_key] or '').strip()
    if 'trialEndsAt' in data:
        company_fields['trial_ends_at'] = data['trialEndsAt']
    # Wallet money moves only through the ledger — approved recharges or an
    # audited /api/admin/ledger/adjust movement. creditBalance* fields on this
    # route are ignored: a raw set would mint unledgered credit.

    if 'company_name' in company_fields:
        company_fields['company_name'] = str(company_fields['company_name'] or '').strip()
        if not company_fields['company_name'] or len(company_fields['company_name']) > 120:
            return jsonify({'error': 'Invalid company name'}), 400
    if 'account_manager_name' in company_fields:
        company_fields['account_manager_name'] = str(
            company_fields['account_manager_name'] or ''
        ).strip()
        if not company_fields['account_manager_name']:
            return jsonify({'error': 'Account manager name is required'}), 400
    if 'email' in company_fields:
        company_fields['email'] = str(company_fields['email'] or '').strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', company_fields['email']):
            return jsonify({'error': 'Invalid email address'}), 400
    if 'username' in company_fields:
        company_fields['username'] = str(company_fields['username'] or '').strip().lower()
        if not USERNAME_RE.fullmatch(company_fields['username']):
            return jsonify({'error': 'Invalid username'}), 400
    if 'phone' in company_fields:
        company_fields['phone'] = _normalize_phone(company_fields['phone'])
        if not PHONE_RE.fullmatch(company_fields['phone']):
            return jsonify({'error': 'Invalid phone number'}), 400
    if 'plan' in company_fields and company_fields['plan'] not in ADMIN_COMPANY_PLANS:
        return jsonify({'error': 'Invalid plan'}), 400
    if 'is_active' in company_fields:
        company_fields['is_active'] = 1 if company_fields['is_active'] else 0

    email = company_fields.get('email', tenant['email'])
    username = company_fields.get('username', tenant.get('username'))
    if email and username:
        conflict = _identity_conflict(
            email, username, tenant_id=tenant_id, user_id=tenant.get('primary_user_id')
        )
        if conflict:
            return jsonify({'error': conflict}), 409

    activation_request = company_fields.pop('is_active', None)
    for key in ['account_manager_name', 'username', 'phone', 'email']:
        if key in company_fields:
            account_fields[key] = company_fields.pop(key)
    try:
        if company_fields:
            db.update_tenant(tenant_id, **company_fields)
        if account_fields:
            db.sync_primary_company_admin(tenant_id, **account_fields)
        if activation_request is not None:
            target_active = bool(activation_request)
            if target_active != bool(tenant.get('is_active')):
                result = db.set_tenant_active(
                    tenant_id, target_active, actor_id=_landloom_actor_id(),
                    actor_name=_landloom_actor_name(), reason=data.get('deactivatedReason'),
                )
                if result.get('error') == 'activation_incomplete':
                    return jsonify({'error': 'activation_incomplete',
                                    'missing': result.get('missing') or []}), 409
                if result.get('error'):
                    return jsonify({'error': result['error']}), 400
            db.sync_primary_company_admin(tenant_id, is_active=1 if target_active else 0)
        if 'company_name' in company_fields:
            db.update_branding(tenant_id, company_name=company_fields['company_name'])
        primary_user_id = data.get('primaryUserId')
        if primary_user_id and primary_user_id != tenant.get('primary_user_id'):
            if not db.set_primary_company_admin(tenant_id, primary_user_id):
                return jsonify({'error': 'User not found'}), 404
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or username already registered'}), 409
    return jsonify({
        'success': True,
        'tenant': _company_payload(db.get_tenant_by_id(tenant_id)),
    })


@app.route('/api/admin/tenants/<tenant_id>', methods=['DELETE'])
@require_admin
def api_admin_delete_tenant(tenant_id):
    """Delete a tenant (admin only).

    The company's dashboard key is removed upstream first so no orphaned
    credential survives; the local key row then cascades with the tenant.
    """
    if tenant_id == g.tenant_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    try:
        meta = db.get_tenant_openrouter_key_meta(tenant_id)
    except Exception:
        meta = {'has_key': False}
    if meta.get('has_key') and meta.get('provenance') == 'auto' \
            and meta.get('openrouter_key_hash'):
        _openrouter_delete_managed_key(meta.get('openrouter_key_hash'))
    db.delete_tenant(tenant_id)
    return jsonify({'success': True})


@app.route('/api/admin/tenants/<tenant_id>/details', methods=['GET'])
@require_admin
def api_admin_tenant_details(tenant_id):
    """Get detailed info about a specific tenant (admin only)."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    if not tenant.get('is_admin') and _openrouter_management_key() and tenant.get('credit_balance') is not None:
        try:
            _sync_tenant_credit_to_openrouter(tenant_id)
        except Exception as exc:
            print(f"[OPENROUTER KEYS] tenant details auto-sync failed: {exc}")
    users = db.get_users_by_tenant(tenant_id)
    branding = db.get_branding(tenant_id)
    counts = db.get_tenant_profile_counts(tenant_id)
    return jsonify({
        'success': True,
        'tenant': _company_payload(tenant),
        'users': users,
        'branding': branding,
        'counts': counts,
    })


@app.route('/api/admin/tenants/<tenant_id>/users', methods=['GET'])
@require_admin
def api_admin_tenant_users(tenant_id):
    """List users of a specific tenant (admin only)."""
    users = db.get_users_by_tenant(tenant_id)
    return jsonify({'success': True, 'users': users})


@app.route('/api/admin/tenants/<tenant_id>/users', methods=['POST'])
@require_admin
def api_admin_add_tenant_user(tenant_id):
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    data = request.json or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    username = (data.get('username') or '').strip().lower()
    phone = _normalize_phone(data.get('phone'))
    role = data.get('role') or 'employee'
    use_setup_link = bool(data.get('useSetupLink', True))
    password = data.get('password') or ''
    if not name or not email or not username or not phone:
        return jsonify({'error': 'All user fields are required'}), 400
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        return jsonify({'error': 'Invalid email address'}), 400
    if not USERNAME_RE.fullmatch(username):
        return jsonify({'error': 'Invalid username'}), 400
    if not PHONE_RE.fullmatch(phone):
        return jsonify({'error': 'Invalid phone number'}), 400
    if role not in db.USER_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    conflict = _identity_conflict(email, username)
    if conflict:
        return jsonify({'error': conflict}), 409
    if use_setup_link:
        password = _generate_secure_password()
    else:
        password_error = _password_validation_error(password)
        if password_error:
            return jsonify({'error': password_error}), 400
    try:
        user_id = db.create_user(
            tenant_id, name, email, hash_password(password), role=role,
            username=username, phone=phone, require_password_change=use_setup_link
        )
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or username already registered'}), 409
    setup_url = None
    if use_setup_link:
        setup_url = _password_setup_url(
            db.create_password_setup_token(tenant_id, user_id)
        )
    return jsonify({
        'success': True,
        'user': db.get_user_by_id(user_id),
        'setupUrl': setup_url,
    }), 201


@app.route('/api/admin/tenants/<tenant_id>/users/<user_id>', methods=['PUT', 'DELETE'])
@require_admin
def api_admin_update_tenant_user(tenant_id, user_id):
    tenant = db.get_tenant_by_id(tenant_id)
    user = db.get_user_by_id(user_id)
    if not tenant or not user or user.get('tenant_id') != tenant_id:
        return jsonify({'error': 'User not found'}), 404
    if request.method == 'DELETE':
        if tenant.get('primary_user_id') == user_id:
            return jsonify({'error': 'Primary company admin cannot be deleted'}), 400
        db.delete_user(user_id)
        return jsonify({'success': True})
    data = request.json or {}
    updates = {}
    for key in ['name', 'role', 'is_active']:
        if key in data:
            updates[key] = data[key]
    # Disabling the primary row suspends the company's owner login — the
    # tenant row flips with it through sync_primary_company_admin, so this
    # stays a deliberate super-admin act.
    if 'email' in data:
        updates['email'] = str(data.get('email') or '').strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', updates['email']):
            return jsonify({'error': 'Invalid email address'}), 400
    if 'username' in data:
        updates['username'] = str(data.get('username') or '').strip().lower()
        if not USERNAME_RE.fullmatch(updates['username']):
            return jsonify({'error': 'Invalid username'}), 400
    if 'phone' in data:
        updates['phone'] = _normalize_phone(data.get('phone'))
        if not PHONE_RE.fullmatch(updates['phone']):
            return jsonify({'error': 'Invalid phone number'}), 400
    if updates.get('role') is not None and updates['role'] not in db.USER_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    email = updates.get('email', user['email'])
    username = updates.get('username', user.get('username'))
    conflict = _identity_conflict(email, username, tenant_id=tenant_id, user_id=user_id)
    if conflict:
        return jsonify({'error': conflict}), 409
    if data.get('password'):
        password_error = _password_validation_error(data['password'])
        if password_error:
            return jsonify({'error': password_error}), 400
        updates['password_hash'] = hash_password(data['password'])
        updates['require_password_change'] = 0
    try:
        db.update_user(user_id, **updates)
        if data.get('isPrimary'):
            db.set_primary_company_admin(tenant_id, user_id)
        elif tenant.get('primary_user_id') == user_id and updates:
            primary_fields = {}
            reverse_mapping = {
                'name': 'account_manager_name',
                'username': 'username',
                'phone': 'phone',
                'email': 'email',
                'password_hash': 'password_hash',
                'require_password_change': 'require_password_change',
                'is_active': 'is_active',
            }
            for key, value in updates.items():
                if key in reverse_mapping:
                    primary_fields[reverse_mapping[key]] = value
            if primary_fields:
                db.sync_primary_company_admin(tenant_id, **primary_fields)
    except db_driver.IntegrityError:
        return jsonify({'error': 'Email or username already registered'}), 409
    return jsonify({'success': True, 'user': db.get_user_by_id(user_id)})


@app.route('/api/admin/tenants/<tenant_id>/reset-password', methods=['POST'])
@require_admin
def api_admin_reset_tenant_password(tenant_id):
    """Reset a tenant's password (admin only)."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    data = request.json or {}
    new_password = data.get('password', '')
    if data.get('useSetupLink') or not new_password:
        user_id = tenant.get('primary_user_id')
        if not user_id:
            return jsonify({'error': 'Primary company admin is not configured'}), 400
        raw_token = db.create_password_setup_token(tenant_id, user_id)
        db.sync_primary_company_admin(tenant_id, require_password_change=1)
        # A forced credential reset retires every session the old password issued.
        db.bump_session_version('tenant', tenant_id)
        db.bump_session_version('user', user_id)
        return jsonify({
            'success': True,
            'setupUrl': _password_setup_url(raw_token),
        })
    password_error = _password_validation_error(new_password)
    if password_error:
        return jsonify({'error': password_error}), 400
    db.sync_primary_company_admin(
        tenant_id,
        password_hash=hash_password(new_password),
        require_password_change=0,
    )
    return jsonify({'success': True})


def _admin_tenant_or_404(tenant_id):
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return None, (jsonify({'error': 'Tenant not found'}), 404)
    return tenant, None


def _require_admin_content_access(tenant_id, scope, target_id=None):
    """d07: a platform admin may read client content only under an active grant.

    Returns the grant row when access is allowed, otherwise a ready
    (response, status) tuple explaining that a client-approved access request
    is required. Each allowed access is counted, audited in the *client's*
    audit log, and the first use notifies the client.
    """
    grant = db.active_admin_access_grant(tenant_id, scope=scope, target_id=target_id)
    if not grant:
        return (jsonify({
            'error': 'قراءة محتوى العميل تتطلب طلب وصول معتمدًا من مدير الشركة',
            'error_code': 'access_grant_required',
            'tenant_id': tenant_id,
        }), 403)
    db.mark_admin_access_used(grant['id'])
    try:
        db.record_audit_event(
            tenant_id=tenant_id,
            action='admin_content.access',
            entity_type=scope,
            entity_id=target_id or tenant_id,
            user_id=None,
            user_name=grant.get('requested_by_name') or 'مدير النظام',
            user_role='platform_admin',
            entity_name=None,
            new_value={'grant_id': grant['id'], 'scope': scope, 'target_id': target_id},
            metadata={'reason': grant.get('reason'), 'access_count': int(grant.get('access_count') or 0) + 1},
        )
    except Exception as exc:
        print(f'[ACCESS GRANT] audit write failed: {exc}')
    if not grant.get('first_accessed_at'):
        _notify_tenant_admins(
            tenant_id, 'وصول إداري إلى محتوى الشركة',
            'اطلع مدير النظام على محتوى شركتك بموجب طلب الوصول المعتمد: ' + (grant.get('reason') or ''),
            entity_type='admin_access_request', entity_id=grant['id'])
    return grant


def _admin_tenant_user_or_404(tenant_id, user_id):
    tenant, error = _admin_tenant_or_404(tenant_id)
    if error:
        return None, None, error
    user = db.get_user_by_id(user_id)
    if not user or user.get('tenant_id') != tenant_id:
        return tenant, None, (jsonify({'error': 'User not found'}), 404)
    return tenant, user, None


@app.route('/api/admin/tenants/<tenant_id>/users/<user_id>/permissions', methods=['GET'])
@require_admin
def api_admin_get_tenant_user_permissions(tenant_id, user_id):
    """Get effective permissions for any tenant's user (super admin only)."""
    _, user, error = _admin_tenant_user_or_404(tenant_id, user_id)
    if error:
        return error
    perms = db.get_user_permissions(user_id, user.get('role', 'employee'))
    keys = [k for k in db.PERMISSION_KEYS if k != 'sag_admin_panel']
    return jsonify({'success': True, 'permissions': perms, 'availableKeys': keys})


@app.route('/api/admin/tenants/<tenant_id>/users/<user_id>/permissions', methods=['PUT'])
@require_admin
def api_admin_set_tenant_user_permissions(tenant_id, user_id):
    """Set permissions for any tenant's user (super admin only)."""
    _, user, error = _admin_tenant_user_or_404(tenant_id, user_id)
    if error:
        return error
    data = request.json or {}
    permissions = data.get('permissions', {})
    for key, granted in permissions.items():
        if key not in db.PERMISSION_KEYS or key == 'sag_admin_panel':
            return jsonify({'error': f'Unknown permission key: {key}'}), 400
        db.set_user_permission(user_id, key, bool(granted))
    perms = db.get_user_permissions(user_id, user.get('role', 'employee'))
    return jsonify({'success': True, 'permissions': perms})


@app.route('/api/admin/tenants/<tenant_id>/users/<user_id>/field-sections', methods=['GET'])
@require_admin
def api_admin_get_tenant_user_field_sections(tenant_id, user_id):
    """Get field section visibility for any tenant's user (super admin only)."""
    _, user, error = _admin_tenant_user_or_404(tenant_id, user_id)
    if error:
        return error
    sections = db.get_user_field_sections(user_id, tenant_id)
    return jsonify({'success': True, 'sections': sections, 'available': db.get_all_sections(tenant_id)})


@app.route('/api/admin/tenants/<tenant_id>/users/<user_id>/field-sections', methods=['PUT'])
@require_admin
def api_admin_set_tenant_user_field_sections(tenant_id, user_id):
    """Set field section visibility for any tenant's user (super admin only)."""
    _, user, error = _admin_tenant_user_or_404(tenant_id, user_id)
    if error:
        return error
    data = request.json or {}
    sections = data.get('sections', {})
    all_keys = {s['key'] for s in db.get_all_sections(tenant_id)}
    for key, granted in sections.items():
        if key in all_keys:
            db.set_user_field_section(user_id, key, bool(granted))
    sections = db.get_user_field_sections(user_id)
    return jsonify({'success': True, 'sections': sections})


@app.route('/api/admin/tenants/<tenant_id>/drafts', methods=['GET'])
@require_admin
def api_admin_tenant_drafts(tenant_id):
    """List project files of any tenant (super admin only, summaries)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    drafts = db.get_all_project_draft_summaries(tenant_id, limit=200)
    return jsonify({'success': True, 'drafts': drafts})


@app.route('/api/admin/tenants/<tenant_id>/presentations', methods=['GET'])
@require_admin
def api_admin_tenant_presentations(tenant_id):
    """List presentations of any tenant (super admin only)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    presentations = db.get_presentations(tenant_id, limit=200)
    result = []
    for p in presentations:
        result.append({
            'id': p['id'],
            'title': p['title'],
            'draftId': p.get('draft_id'),
            'slideCount': p.get('slide_count', 0),
            'status': p.get('status', 'draft'),
            'createdAt': p.get('created_at'),
            'updatedAt': p.get('updated_at'),
        })
    return jsonify({'success': True, 'presentations': result})


@app.route('/api/admin/tenants/<tenant_id>/exports', methods=['GET'])
@require_admin
def api_admin_tenant_exports(tenant_id):
    """List exports of any tenant (super admin only, metadata without download)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    result = [
        {'id': e['id'], 'format': e['format'], 'createdAt': e.get('created_at')}
        for e in db.get_exports(tenant_id)
    ]
    return jsonify({'success': True, 'exports': result})


@app.route('/api/admin/tenants/<tenant_id>/activity', methods=['GET'])
@require_admin
def api_admin_tenant_activity(tenant_id):
    """Recent change history across any tenant — its diff details carry real
    content, so an active client-approved access grant is required (d07)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    grant = _require_admin_content_access(tenant_id, scope='tenant')
    if isinstance(grant, tuple):
        return grant
    return jsonify({'success': True, 'activity': db.get_tenant_recent_activity(tenant_id)})


@app.route('/api/admin/tenants/<tenant_id>/agent', methods=['GET'])
@require_admin
def api_admin_tenant_agent(tenant_id):
    """Read-only review of a tenant's AI training, agent change log and stored
    agent conversations. Always available to the super admin — when a company
    reports a problem, support sees what it taught the AI and what the agent
    answered and executed, without needing a client access grant."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    return jsonify({
        'success': True,
        'training': db.get_training_data(tenant_id),
        'rulesLog': db.get_ai_rules_log(tenant_id, limit=100),
        'chatLog': db.get_agent_chat_log(tenant_id, limit=100),
    })


@app.route('/api/admin/tenants/<tenant_id>/presentations/<pres_id>', methods=['GET'])
@require_admin
def api_admin_tenant_presentation(tenant_id, pres_id):
    """Full read-only presentation of any tenant — requires an active,
    client-approved access grant (d07)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    grant = _require_admin_content_access(tenant_id, scope='presentation', target_id=pres_id)
    if isinstance(grant, tuple):
        return grant
    pres = db.get_presentation(pres_id, tenant_id=tenant_id)
    if not pres:
        return jsonify({'error': 'Presentation not found'}), 404
    pres['projectData'] = json.loads(pres['project_data']) if pres.get('project_data') else {}
    pres['projectData'] = _merge_persisted_map_assets(pres['projectData'], tenant_id, presentation_id=pres_id)
    slides = json.loads(pres['slides_data']) if pres.get('slides_data') else []
    branding = db.get_branding(tenant_id) or {}
    render_project_data = copy.deepcopy(pres['projectData'])
    _prepare_generation_logo_context(render_project_data, branding, tenant_id)
    slides = slide_engine.renumber_presentation_slides(
        slides, branding=branding, project_data=render_project_data, tenant_id=tenant_id,
        creative_images=_presentation_creative_images(render_project_data, tenant_id),
    )
    project_logo_ref = slide_engine._project_logo_reference(render_project_data)
    for s in slides:
        if isinstance(s, dict) and 'html' in s and isinstance(s['html'], str):
            s['html'] = slide_engine.resolve_logo_in_html(
                s['html'], tenant_id, _branding_cache=branding,
                project_logo=project_logo_ref,
            )
    pres['slide_count'] = len(slides)
    pres['slidesData'] = slides
    return jsonify({'success': True, 'presentation': pres})
