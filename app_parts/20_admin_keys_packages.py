

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
        try:
            if data.get('creditBalanceSar') is not None:
                credit_balance = db.sar_to_usd(data.get('creditBalanceSar'))
            else:
                credit_balance = float(data.get('creditBalance') or 0)
        except (TypeError, ValueError):
            return jsonify({'error': 'Credit balance must be a valid number'}), 400

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
        if credit_balance < 0:
            return jsonify({'error': 'Credit balance cannot be negative'}), 400
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
        # dashboard-visible limit from day one. Never fails tenant creation.
        try:
            _ensure_tenant_openrouter_key(
                tenant_id, limit_usd=_tenant_provider_cap_usd(tenant_id))
        except Exception as exc:
            print(f"[OPENROUTER KEYS] auto-provision on create failed: {exc}")
        tenant = db.get_tenant_by_id(tenant_id)
        _notify_super_admins(
            'شركة جديدة انضمت إلى المنصة', company_name,
            entity_type='tenant', entity_id=tenant_id)
        return jsonify({
            'success': True,
            'tenant': _company_payload(tenant),
            'setupUrl': setup_url,
            'welcomeEmailSent': email_sent,
        }), 201

    tenants = db.get_all_tenants()
    result = [_company_payload(tenant) for tenant in tenants]
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
        'creditBalance': 'credit_balance',
        'isActive': 'is_active',
    }
    for input_key, db_key in key_map.items():
        if input_key in data:
            company_fields[db_key] = data[input_key]
    for db_key in ['company_name', 'account_manager_name', 'username', 'phone', 'email',
                   'plan', 'credit_balance', 'is_active']:
        if db_key in data:
            company_fields[db_key] = data[db_key]
    for input_key, db_key in _COMPANY_PROFILE_KEY_MAP.items():
        if input_key in data:
            company_fields[db_key] = str(data[input_key] or '').strip()
        elif db_key in data:
            company_fields[db_key] = str(data[db_key] or '').strip()
    if 'trialEndsAt' in data:
        company_fields['trial_ends_at'] = data['trialEndsAt']
    # The desk keys balances in riyals; the wallet stores dollars.
    if data.get('creditBalanceSar') is not None:
        try:
            company_fields['credit_balance'] = db.sar_to_usd(data.get('creditBalanceSar'))
        except (TypeError, ValueError):
            return jsonify({'error': 'Credit balance must be a valid number'}), 400

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
    if 'credit_balance' in company_fields:
        try:
            company_fields['credit_balance'] = float(company_fields['credit_balance'])
        except (TypeError, ValueError):
            return jsonify({'error': 'Credit balance must be a valid number'}), 400
        if company_fields['credit_balance'] < 0:
            return jsonify({'error': 'Credit balance cannot be negative'}), 400
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

    synced_credit_balance = company_fields.get('credit_balance')
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
                    tenant_id, target_active, actor_id=_omran_actor_id(),
                    actor_name=_omran_actor_name(), reason=data.get('deactivatedReason'),
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
        # credit_balance may have been written directly (no ledger entry, no
        # hook) — re-sync the provider cap from the freshest entitlement.
        _sync_tenant_credit_to_openrouter(tenant_id)
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Per-tenant OpenRouter keys (super admin only).
# Managed keys are provisioned through the OpenRouter Management API, so every
# key appears in the owner dashboard with its own spend limit. The raw secret
# is stored encrypted and is never returned by any endpoint below.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _admin_key_target(tenant_id):
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return None, (jsonify({'error': 'Tenant not found'}), 404)
    if tenant.get('is_admin'):
        return None, (jsonify({'error': 'Super admin accounts use the global key'}), 400)
    return tenant, None


@app.route('/api/admin/tenants/<tenant_id>/openrouter-key', methods=['GET'])
@require_admin
def api_admin_tenant_key_status(tenant_id):
    """Public key status for one company. Never includes the secret."""
    _tenant, error = _admin_key_target(tenant_id)
    if error is not None:
        return error
    return jsonify({
        'success': True,
        'key': db.get_tenant_openrouter_key_meta(tenant_id),
        'managedProvisioning': bool(_openrouter_management_key()),
        'defaults': {
            'limitUsd': TENANT_OPENROUTER_DEFAULT_LIMIT_USD,
            'limitReset': TENANT_OPENROUTER_DEFAULT_RESET,
        },
    })


@app.route('/api/admin/tenants/<tenant_id>/openrouter-key/provision', methods=['POST'])
@require_admin
def api_admin_tenant_key_provision(tenant_id):
    """Create a dashboard-visible managed key for one company.

    limitUsd may be zero: the key is then verified blocked before it is
    activated, so prepaid companies spend nothing until topped up.
    """
    tenant, error = _admin_key_target(tenant_id)
    if error is not None:
        return error
    data = request.json or {}
    if not _openrouter_management_key():
        return jsonify({'error': 'OPENROUTER_MANAGEMENT_KEY is not configured'}), 503
    raw_limit = data.get('limitUsd', data.get('limit_usd', TENANT_OPENROUTER_DEFAULT_LIMIT_USD))
    try:
        limit_usd = float(raw_limit if raw_limit is not None else TENANT_OPENROUTER_DEFAULT_LIMIT_USD)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid limitUsd'}), 400
    if limit_usd < 0:
        return jsonify({'error': 'Invalid limitUsd'}), 400
    limit_reset = str(data.get('limitReset') or data.get('limit_reset')
                      or TENANT_OPENROUTER_DEFAULT_RESET).strip().lower()
    if limit_reset not in ('daily', 'weekly', 'monthly', 'none'):
        return jsonify({'error': 'Invalid limitReset'}), 400
    force = bool(data.get('force') or data.get('rotate'))
    existing = db.get_tenant_openrouter_key_meta(tenant_id)
    if existing.get('has_key') and not force:
        return jsonify({'error': 'Company already has a key. Pass force=true to rotate it.',
                        'key': existing}), 409
    if existing.get('has_key') and force and existing.get('openrouter_key_hash'):
        _openrouter_delete_managed_key(existing.get('openrouter_key_hash'))
    meta, provision_error = _provision_one_tenant_key(tenant, limit_usd, limit_reset)
    if meta is None:
        return jsonify({'error': provision_error or 'Provisioning failed'}), 503
    return jsonify({'success': True, 'key': meta}), 201


@app.route('/api/admin/openrouter-keys/ensure-all', methods=['POST'])
@require_admin
def api_admin_tenant_keys_ensure_all():
    """Issue managed keys to every company that has none. Bulk, best-effort.

    Body: {limitUsd (default 0, blocked until top-up), limitReset, batch
    (default 25, max 50), offset (default 0)}. Super admins and companies
    with an active key are skipped. Key creation is rate-limited upstream,
    so one batch paces itself and the caller pages with offset.
    """
    data = request.json or {}
    if not _openrouter_management_key():
        return jsonify({'error': 'OPENROUTER_MANAGEMENT_KEY is not configured'}), 503
    raw_limit = data.get('limitUsd', data.get('limit_usd', TENANT_OPENROUTER_DEFAULT_LIMIT_USD))
    try:
        limit_usd = float(raw_limit if raw_limit is not None else TENANT_OPENROUTER_DEFAULT_LIMIT_USD)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid limitUsd'}), 400
    if limit_usd < 0:
        return jsonify({'error': 'Invalid limitUsd'}), 400
    limit_reset = str(data.get('limitReset') or data.get('limit_reset')
                      or TENANT_OPENROUTER_DEFAULT_RESET).strip().lower()
    if limit_reset not in ('daily', 'weekly', 'monthly', 'none'):
        return jsonify({'error': 'Invalid limitReset'}), 400
    try:
        batch = max(1, min(50, int(data.get('batch') or 25)))
    except (TypeError, ValueError):
        batch = 25
    try:
        offset = max(0, int(data.get('offset') or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        tenants = db.get_all_tenants()
    except Exception as exc:
        return jsonify({'error': f'Tenant list failed: {exc}'}), 500
    targets = []
    already_keyed = 0
    total_companies = 0
    for tenant in tenants:
        try:
            if tenant.get('is_admin'):
                continue
            total_companies += 1
            meta = db.get_tenant_openrouter_key_meta(tenant.get('id'))
        except Exception:
            continue
        if meta.get('has_key') and meta.get('is_active'):
            already_keyed += 1
            continue
        old_hash = meta.get('openrouter_key_hash') if meta.get('has_key') else None
        targets.append((tenant, old_hash))
    import time as _time
    page = targets[offset:offset + batch]
    results = []
    created = 0
    for tenant, old_hash in page:
        if old_hash:
            _openrouter_delete_managed_key(old_hash)
        meta, provision_error = _provision_one_tenant_key(tenant, limit_usd, limit_reset)
        if meta is not None:
            provision_error = None
        elif not isinstance(provision_error, str) or not provision_error.strip() \
                or provision_error.strip().lower() in ('none', 'null'):
            provision_error = 'Provisioning failed'
        results.append({
            'tenantId': tenant.get('id'),
            'companyName': tenant.get('company_name'),
            'ok': bool(meta is not None and meta.get('is_active', True)),
            'error': provision_error,
        })
        if meta is not None and meta.get('is_active', True):
            created += 1
        _time.sleep(1)
    # Post-provision count from the same snapshot: every ok row just turned
    # active, every failed row is still keyless. The caller stops when this
    # reaches zero instead of paying for a confirmatory round per press.
    remaining_keyless = len(targets) - created
    return jsonify({'success': True, 'total_keyless': len(targets),
                    'remaining_keyless': remaining_keyless,
                    'total_companies': total_companies,
                    'already_keyed': already_keyed,
                    'offset': offset, 'batch': batch, 'created': created,
                    'failed': len(results) - created, 'results': results})


@app.route('/api/admin/openrouter-keys/orphans', methods=['GET'])
@require_admin
def api_admin_tenant_keys_orphans():
    """Dashboard keys no company row references (e.g. after a failed run).

    These can never be recovered (the secret shows only at creation), only
    listed here and deleted below.
    """
    orphans, error = _managed_orphan_keys()
    if error is not None:
        return jsonify({'success': False, 'error': error}), 503
    return jsonify({'success': True, 'count': len(orphans), 'orphans': orphans})


@app.route('/api/admin/openrouter-keys/orphans', methods=['DELETE'])
@require_admin
def api_admin_tenant_keys_orphans_delete():
    """Delete orphaned dashboard keys. Requires {"confirm": true}."""
    data = request.json or {}
    if data.get('confirm') is not True:
        return jsonify({'success': False,
                        'error': 'أرسل confirm=true لحذف المفاتيح اليتيمة',
                        'error_code': 'CONFIRM_REQUIRED'}), 400
    orphans, error = _managed_orphan_keys()
    if error is not None:
        return jsonify({'success': False, 'error': error}), 503
    deleted = []
    failed = []
    for item in orphans:
        result = _openrouter_delete_managed_key(item.get('hash'))
        if isinstance(result, dict) and (result.get('ok') or result.get('skipped')):
            deleted.append(item.get('name'))
        else:
            failed.append({'name': item.get('name'), 'result': result})
    return jsonify({'success': True, 'deleted': deleted, 'failed': failed,
                    'deleted_count': len(deleted)})


@app.route('/api/admin/openrouter-keys/debug', methods=['GET'])
@require_admin
def api_admin_tenant_keys_debug():
    """Diagnose bulk-issuance repeats: key state per company plus backend facts.

    Presence/state metadata only. Never includes secrets or key hashes.
    """
    try:
        tenants = db.get_all_tenants()
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Tenant list failed: {exc}'}), 500
    rows = []
    for tenant in tenants:
        try:
            if tenant.get('is_admin'):
                continue
            meta = db.get_tenant_openrouter_key_meta(tenant.get('id'))
        except Exception:
            continue
        rows.append({
            'tenantId': tenant.get('id'),
            'companyName': tenant.get('company_name'),
            'has_key': bool(meta.get('has_key')),
            'is_active': bool(meta.get('is_active')),
            'provenance': meta.get('provenance'),
            'limit_usd': meta.get('limit_usd'),
            'updated_at': meta.get('updated_at'),
        })
    db_path = str(db.DB_PATH)
    return jsonify({
        'success': True,
        'db_path': db_path,
        'db_backend': 'postgres' if db_path.startswith(('postgres://', 'postgresql://')) else 'sqlite',
        'default_limit_usd': TENANT_OPENROUTER_DEFAULT_LIMIT_USD,
        'management_key_configured': bool(_openrouter_management_key()),
        'total_companies': len(rows),
        'keyed_active': sum(1 for row in rows if row['has_key'] and row['is_active']),
        'tenants': rows,
    })


@app.route('/api/admin/tenants/<tenant_id>/openrouter-key/manual', methods=['POST'])
@require_admin
def api_admin_tenant_key_manual(tenant_id):
    """Attach a super-admin-supplied key (created in the dashboard by hand)."""
    _tenant, error = _admin_key_target(tenant_id)
    if error is not None:
        return error
    data = request.json or {}
    raw_key = str(data.get('apiKey') or data.get('key') or '').strip()
    if len(raw_key) < 16:
        return jsonify({'error': 'Invalid apiKey'}), 400
    label = str(data.get('label') or data.get('key_label') or '').strip() or None
    limit_reset = data.get('limitReset') or data.get('limit_reset')
    if limit_reset is not None:
        limit_reset = str(limit_reset).strip().lower()
        if limit_reset not in ('daily', 'weekly', 'monthly', 'none'):
            return jsonify({'error': 'Invalid limitReset'}), 400
    limit_usd = data.get('limitUsd', data.get('limit_usd'))
    if limit_usd is not None:
        try:
            limit_usd = float(limit_usd)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid limitUsd'}), 400
        if limit_usd < 0:
            return jsonify({'error': 'Invalid limitUsd'}), 400
    status = _openrouter_key_status(raw_key)
    if isinstance(status, dict) and status.get('error'):
        return jsonify({'error': 'The key was rejected by OpenRouter: ' + str(status.get('error'))}), 400
    live_hash = status.get('hash') if isinstance(status, dict) else None
    try:
        meta = db.set_tenant_openrouter_key(
            tenant_id, raw_key, key_label=label,
            limit_usd=limit_usd if limit_usd is not None
            else (status.get('limit') if isinstance(status, dict) else None),
            limit_reset=limit_reset or (status.get('limit_reset') if isinstance(status, dict) else None),
            provenance='manual',
            openrouter_key_hash=live_hash,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    try:
        db.update_tenant_openrouter_key_meta(
            tenant_id,
            last_limit_remaining=(status.get('limit_remaining') if isinstance(status, dict) else None),
            last_usage=(status.get('usage') if isinstance(status, dict) else None),
        )
        meta = db.get_tenant_openrouter_key_meta(tenant_id)
    except Exception:
        pass
    return jsonify({'success': True, 'key': meta}), 201


@app.route('/api/admin/tenants/<tenant_id>/openrouter-key', methods=['PUT'])
@require_admin
def api_admin_tenant_key_update(tenant_id):
    """Update limit/reset/active flag. Syncs the dashboard limit best-effort.

    Setting limitUsd to zero blocks the company until the next top-up.
    """
    _tenant, error = _admin_key_target(tenant_id)
    if error is not None:
        return error
    data = request.json or {}
    existing = db.get_tenant_openrouter_key_meta(tenant_id)
    if not existing.get('has_key'):
        return jsonify({'error': 'Company has no key yet'}), 404
    limit_usd = data.get('limitUsd', data.get('limit_usd'))
    if limit_usd is not None:
        try:
            limit_usd = float(limit_usd)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid limitUsd'}), 400
        if limit_usd < 0:
            return jsonify({'error': 'Invalid limitUsd'}), 400
    limit_reset = data.get('limitReset', data.get('limit_reset'))
    if limit_reset is not None:
        limit_reset = str(limit_reset).strip().lower()
        if limit_reset not in ('daily', 'weekly', 'monthly', 'none'):
            return jsonify({'error': 'Invalid limitReset'}), 400
    is_active = data.get('isActive', data.get('is_active'))
    if is_active is not None:
        is_active = bool(is_active)
    try:
        meta = db.update_tenant_openrouter_key_meta(
            tenant_id, limit_usd=limit_usd, limit_reset=limit_reset,
            is_active=is_active)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    key_hash = existing.get('openrouter_key_hash')
    if not key_hash and existing.get('provenance') == 'auto':
        key_hash = _find_managed_key_hash_for_tenant(tenant_id)
    if key_hash:
        if limit_usd is not None:
            # ISS-036: the dashboard field means the same thing here as in the
            # wallet sync — how much more the key may burn — so the PATCH adds
            # the usage the provider already recorded against the key.
            provider_usage = _openrouter_key_usage_usd(tenant_id)
            _openrouter_update_managed_key(
                key_hash,
                limit_usd=(provider_usage + limit_usd) if provider_usage is not None else limit_usd,
                limit_reset=limit_reset)
        if is_active is False:
            _openrouter_update_managed_key(key_hash, disabled=True)
        elif is_active is True:
            _openrouter_update_managed_key(key_hash, disabled=False)
    return jsonify({'success': True, 'key': meta})


@app.route('/api/admin/tenants/<tenant_id>/openrouter-key', methods=['DELETE'])
@require_admin
def api_admin_tenant_key_delete(tenant_id):
    """Disable a company key locally and remove it from the dashboard best-effort."""
    _tenant, error = _admin_key_target(tenant_id)
    if error is not None:
        return error
    existing = db.get_tenant_openrouter_key_meta(tenant_id)
    if not existing.get('has_key'):
        return jsonify({'error': 'Company has no key yet'}), 404
    if existing.get('provenance') == 'auto' and existing.get('openrouter_key_hash'):
        _openrouter_delete_managed_key(existing.get('openrouter_key_hash'))
    meta = db.deactivate_tenant_openrouter_key(tenant_id)
    return jsonify({'success': True, 'key': meta})


@app.route('/api/admin/tenants/<tenant_id>/openrouter-key/refresh', methods=['POST'])
@require_admin
def api_admin_tenant_key_refresh(tenant_id):
    """Read live limit/usage from OpenRouter and cache it on the key row."""
    _tenant, error = _admin_key_target(tenant_id)
    if error is not None:
        return error
    raw = db.get_tenant_openrouter_key_raw(tenant_id)
    if not raw:
        return jsonify({'error': 'Company has no active key'}), 404
    status = _openrouter_key_status(raw)
    if isinstance(status, dict) and status.get('error'):
        return jsonify({'error': 'OpenRouter refused the key: ' + str(status.get('error'))}), 503
    meta = db.update_tenant_openrouter_key_meta(
        tenant_id,
        last_limit_remaining=status.get('limit_remaining'),
        last_usage=status.get('usage'),
        openrouter_key_hash=status.get('hash') or None,
    )
    live = {'limit': status.get('limit'), 'limitRemaining': status.get('limit_remaining'),
            'limitReset': status.get('limit_reset'), 'usage': status.get('usage'),
            'usageDaily': status.get('usage_daily'), 'usageWeekly': status.get('usage_weekly'),
            'usageMonthly': status.get('usage_monthly'), 'label': status.get('label')}
    return jsonify({'success': True, 'key': meta, 'live': live})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Billing packages and the USD to SAR rate (super admin only).
# Packages are the bundles companies subscribe to: credit_usd is the spend
# allowance the provider key follows, price_sar is the selling price.
# Balances display in riyals at a rate that refreshes daily on its own, with
# a manual override that auto-refresh never overwrites.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FX_RATE_URL = 'https://open.er-api.com/v6/latest/USD'


def _fetch_fx_usd_sar(timeout=10):
    """Live dollars-to-riyals rate, or None. Never raises."""
    try:
        response = requests.get(FX_RATE_URL, timeout=timeout)
        data = response.json() if response.status_code < 400 else {}
        rate = float(((data or {}).get('rates') or {}).get('SAR') or 0)
        return rate if rate > 0 else None
    except Exception as exc:
        print(f"[FX] fetch failed: {exc}")
        return None


def _fx_rate_age_seconds(fx):
    try:
        stamp = str((fx or {}).get('updated_at') or '').replace(' ', 'T')[:19]
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is not None:
            moment = moment.replace(tzinfo=None)
        return (datetime.now(timezone.utc).replace(tzinfo=None) - moment).total_seconds()
    except Exception:
        return float('inf')


def _refresh_fx_rate(force=False):
    """Fetch and store the auto rate unless a manual override or fresh value stands."""
    try:
        with app.app_context():
            current = db.get_fx_rate()
            if current.get('source') == 'manual' and not force:
                return current
            if not force and _fx_rate_age_seconds(current) < db.FX_REFRESH_SECONDS:
                return current
            rate = _fetch_fx_usd_sar()
            if rate:
                return db.set_fx_rate(db.FX_PAIR_USD_SAR, rate, source='auto')
            return current
    except Exception as exc:
        print(f"[FX] refresh failed: {exc}")
        try:
            return db.get_fx_rate()
        except Exception:
            return {'pair': db.FX_PAIR_USD_SAR, 'rate': db.FX_DEFAULT_USD_SAR,
                    'source': 'default', 'updated_at': None}


def _refresh_fx_rate_async(force=False):
    """Refresh the rate off the request path. Testing stays fully offline."""
    try:
        if app.config.get('TESTING') and not force:
            return
        thread = threading.Thread(target=_refresh_fx_rate, args=(force,), daemon=True)
        thread.start()
    except Exception as exc:
        print(f"[FX] refresh thread failed: {exc}")


@app.route('/api/admin/packages', methods=['GET'])
@require_admin
def api_admin_packages():
    """List all billing packages with the margin figures the catalog owner
    tunes against — admin-only, never exposed on the client purchase feed.

    A purchased package lands as wallet credit (billed dollars): the holder
    burns it at raw provider cost x BILLING_MULTIPLIER, so the provider-side
    cost of a fully consumed package is credit_usd / multiplier. The margin
    is the SAR price converted to USD minus that estimate.
    """
    packages = db.list_billing_packages()
    try:
        multiplier = float(db.get_billing_multiplier() or 0.0)
    except (TypeError, ValueError):
        multiplier = 0.0
    if multiplier <= 0:
        multiplier = 1.0
    try:
        fx_rate = float((db.get_fx_rate() or {}).get('rate') or 0.0)
    except (TypeError, ValueError):
        fx_rate = 0.0
    for package in packages:
        try:
            credit = float(package.get('credit_usd') or 0.0)
        except (TypeError, ValueError):
            credit = 0.0
        cost = credit / multiplier
        package['est_cost_usd'] = round(cost, 2)
        package['credit_sar'] = db.usd_to_sar(credit, fx_rate or None)
        package['est_cost_sar'] = db.usd_to_sar(cost, fx_rate or None)
        price_sar = package.get('price_sar')
        if price_sar is not None and fx_rate > 0:
            margin_usd = float(price_sar) / fx_rate - cost
            package['est_margin_usd'] = round(margin_usd, 2)
            package['est_margin_sar'] = round(margin_usd * fx_rate, 2)
    return jsonify({'success': True, 'packages': packages,
                    'billingMultiplier': multiplier,
                    'fxRate': fx_rate or None})


@app.route('/api/admin/packages', methods=['POST'])
@require_admin
def api_admin_packages_create():
    """Create a package (custom by default). credit_usd may be zero.

    The desk keys the wallet credit in riyals (``creditSar``); it is converted
    to the internal USD figure at the active rate. ``creditUsd`` stays accepted
    for old callers.
    """
    data = request.json or {}
    credit_usd = data.get('creditUsd', data.get('credit_usd'))
    credit_sar = data.get('creditSar', data.get('credit_sar'))
    if credit_sar is not None:
        try:
            credit_usd = db.sar_to_usd(credit_sar)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid credit_sar'}), 400
    try:
        package = db.create_billing_package(
            data.get('name'),
            credit_usd if credit_usd is not None else 0,
            data.get('priceSar', data.get('price_sar')),
            is_custom=bool(data.get('isCustom', data.get('is_custom', True))),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'success': True, 'package': package}), 201


@app.route('/api/admin/packages/<package_id>', methods=['PUT'])
@require_admin
def api_admin_package_update(package_id):
    """Edit a package name, credit, price or active flag."""
    data = request.json or {}
    kwargs = {}
    if 'name' in data:
        kwargs['name'] = data.get('name')
    if 'creditSar' in data or 'credit_sar' in data:
        try:
            kwargs['credit_usd'] = db.sar_to_usd(data.get('creditSar', data.get('credit_sar')))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid credit_sar'}), 400
    elif 'creditUsd' in data or 'credit_usd' in data:
        kwargs['credit_usd'] = data.get('creditUsd', data.get('credit_usd'))
    if 'priceSar' in data or 'price_sar' in data:
        kwargs['price_sar'] = data.get('priceSar', data.get('price_sar'))
    if 'isActive' in data or 'is_active' in data:
        kwargs['is_active'] = data.get('isActive', data.get('is_active'))
    try:
        package = db.update_billing_package(package_id, **kwargs)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if package is None:
        return jsonify({'error': 'Package not found'}), 404
    return jsonify({'success': True, 'package': package})


@app.route('/api/admin/packages/<package_id>', methods=['DELETE'])
@require_admin
def api_admin_package_delete(package_id):
    """Delete a package. Companies on it keep their key limit, package unset."""
    if not db.delete_billing_package(package_id):
        return jsonify({'error': 'Package not found'}), 404
    return jsonify({'success': True})


@app.route('/api/admin/tenants/<tenant_id>/package', methods=['GET'])
@require_admin
def api_admin_tenant_package_status(tenant_id):
    """Which package a company is on, if any."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    package = db.get_billing_package(tenant.get('package_id')) if tenant.get('package_id') else None
    return jsonify({'success': True, 'tenantId': tenant_id,
                    'packageId': tenant.get('package_id'), 'package': package})


@app.route('/api/admin/tenants/<tenant_id>/package', methods=['POST'])
@require_admin
def api_admin_tenant_package_assign(tenant_id):
    """Attach a company to a package and sync its provider key limit to it."""
    tenant = db.get_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    if tenant.get('is_admin'):
        return jsonify({'error': 'Super admin accounts use the global key'}), 400
    data = request.json or {}
    package_id = data.get('packageId', data.get('package_id'))
    try:
        _tenant, package = db.assign_tenant_package(tenant_id, package_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    key = db.get_tenant_openrouter_key_meta(tenant_id)
    if package is not None:
        # The new package credit joins the provider-cap entitlement; the
        # sync recomputes wallet + holds + package remaining itself.
        key = _sync_tenant_credit_to_openrouter(tenant_id) or key
    return jsonify({'success': True, 'tenantId': tenant_id,
                    'package': package, 'key': key})


@app.route('/api/admin/fx-rate', methods=['GET'])
@require_admin
def api_admin_fx_rate():
    """Current USD to SAR rate with source. Triggers a background refresh."""
    _refresh_fx_rate_async()
    return jsonify({'success': True, 'fx': db.get_fx_rate()})


@app.route('/api/admin/fx-rate', methods=['PUT'])
@require_admin
def api_admin_fx_rate_update():
    """Manual override (mode manual + rate) or back to auto tracking."""
    data = request.json or {}
    mode = str(data.get('mode') or 'manual').strip().lower()
    if mode == 'manual':
        try:
            fx = db.set_fx_rate(db.FX_PAIR_USD_SAR, data.get('rate'), source='manual')
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        return jsonify({'success': True, 'fx': fx})
    if mode == 'auto':
        fx = _refresh_fx_rate(force=True)
        if fx.get('source') == 'auto':
            return jsonify({'success': True, 'fx': fx})
        return jsonify({'error': 'Rate provider unreachable, kept stored rate',
                        'fx': fx}), 503
    return jsonify({'error': 'Invalid mode'}), 400


@app.route('/api/client/overview', methods=['GET'])
@require_auth
def api_client_overview():
    """Client card: totals, current package with remaining, lifetime spend.

    Money travels in raw USD with a riyal rendering beside it at the live
    rate. A package reads expired exactly when its remaining hits zero.
    """
    try:
        _refresh_fx_rate_async()
        view = db.get_client_overview(g.tenant_id)
        fx = db.get_fx_rate()
        package = view.get('package')
        balance_usd = db.get_tenant_balance(g.tenant_id)
        if package is not None:
            package = dict(package)
            package['credit_sar'] = db.usd_to_sar(package.get('credit_usd'), fx.get('rate'))
            package['consumed_sar'] = db.usd_to_sar(package.get('consumed_usd'), fx.get('rate'))
            package['remaining_sar'] = db.usd_to_sar(package.get('remaining_usd'), fx.get('rate'))
        else:
            # A bare wallet has no package cap; its limit is everything the
            # platform ever credited, and what left since is the consumed share.
            credited_usd = db.get_tenant_wallet_credited(g.tenant_id)
            if balance_usd > 0 or credited_usd > 0:
                consumed_usd = max(0.0, round(credited_usd - balance_usd, 2))
                package = {
                    'id': 'wallet',
                    'name': 'رصيد المحفظة',
                    'credit_usd': credited_usd,
                    'consumed_usd': consumed_usd,
                    'remaining_usd': balance_usd,
                    'status': 'active',
                    'assigned_at': None,
                    'credit_sar': db.usd_to_sar(credited_usd, fx.get('rate')),
                    'consumed_sar': db.usd_to_sar(consumed_usd, fx.get('rate')),
                    'remaining_sar': db.usd_to_sar(balance_usd, fx.get('rate')),
                }
        return jsonify({
            'success': True,
            'totals': {
                'projects': view.get('projects'),
                'presentations': view.get('presentations'),
                'consumption_usd': view.get('consumption_usd'),
                'consumption_sar': db.usd_to_sar(view.get('consumption_usd'), fx.get('rate')),
            },
            'package': package,
            'balance_usd': balance_usd,
            'balance_sar': db.usd_to_sar(balance_usd, fx.get('rate')),
            'lifetime': {
                'consumed_usd': view.get('lifetime_consumed_usd'),
                'consumed_sar': db.usd_to_sar(view.get('lifetime_consumed_usd'), fx.get('rate')),
            },
            'fx': {'rate': fx.get('rate'), 'source': fx.get('source'),
                   'updatedAt': fx.get('updated_at')},
        })
    except Exception as exc:
        print(f"[CLIENT] overview failed: {exc}")
        return jsonify({'success': False, 'error': 'تعذر تحميل بطاقة العميل'}), 500


@app.route('/api/admin/stats', methods=['GET'])
@require_admin
def api_admin_stats():
    """Get global stats (admin only)."""
    return jsonify({'success': True, 'stats': db.get_stats()})


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


def _notify_tenant_admins(tenant_id, title, body, entity_type=None, entity_id=None):
    """In-app + email notification to every active company admin of the tenant."""
    try:
        # The company admin reads its feed under the tenant-admin address —
        # employees must not see platform-access escalations in theirs.
        tenant = db.get_tenant_by_id(tenant_id)
        db.create_notification(
            tenant_id, title, body, category='general',
            user_id='tenant-admin:' + str(tenant_id),
            entity_type=entity_type, entity_id=entity_id,
            email_to=(tenant or {}).get('email'))
    except Exception as exc:
        print(f'[ACCESS REQUEST] client notification failed: {exc}')


def _notify_super_admins(title, body, entity_type=None, entity_id=None, category='platform'):
    """A platform event lands in every active super admin's feed — the admin
    tenant's own notification stream, visible to all of its logins."""
    try:
        for admin_tenant_id in db.list_admin_tenant_ids():
            db.create_notification(
                admin_tenant_id, title, body, category=category,
                user_id=None, entity_type=entity_type, entity_id=entity_id)
    except Exception as exc:
        print(f'[NOTIFY] super-admin notification failed: {exc}')


def _notify_tenant_billing(tenant_id, title, body, entity_type=None, entity_id=None):
    """Wallet movements reach the users holding the billing permission plus
    the company-owner login (addressed as 'tenant-admin:<id>', which employee
    accounts never match)."""
    try:
        notified = set()
        for user in db.get_users_with_permission(tenant_id, 'billing'):
            if user['id'] in notified:
                continue
            notified.add(user['id'])
            db.create_notification(
                tenant_id, title, body, category='billing', user_id=user['id'],
                entity_type=entity_type, entity_id=entity_id)
        db.create_notification(
            tenant_id, title, body, category='billing',
            user_id='tenant-admin:' + str(tenant_id),
            entity_type=entity_type, entity_id=entity_id)
    except Exception as exc:
        print(f'[NOTIFY] billing notification failed: {exc}')


def _notification_recipient_key():
    """The actor's notification address: their user id for staff logins, or
    the tenant-admin address for the direct company login."""
    return getattr(g, 'user_id', None) or 'tenant-admin:' + str(g.tenant_id)


def _notification_muted_categories():
    try:
        prefs = db.get_notification_preferences(g.tenant_id, _notification_recipient_key())
    except Exception:
        return []
    return [category for category, enabled in prefs.items() if not enabled]


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


@app.route('/api/admin/tenants/<tenant_id>/access-requests', methods=['POST'])
@require_admin
def api_admin_create_access_request(tenant_id):
    """Ask the client for time-boxed read access to its content (d07)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    data = request.json or {}
    row = db.create_admin_access_request(
        g.tenant_id, tenant_id, data.get('scope') or 'tenant',
        data.get('targetId') or data.get('target_id'),
        data.get('reason'), int(data.get('hours') or 24),
        g.tenant.get('company_name') or 'مدير النظام',
    )
    failure = _omran_error(row)
    if failure:
        return failure
    tenant = db.get_tenant_by_id(tenant_id)
    _notify_tenant_admins(
        tenant_id, 'طلب وصول إلى محتوى الشركة',
        f'طلب مدير النظام وصولًا مؤقتًا إلى محتوى {(tenant or {}).get("company_name") or "شركتك"}'
        f' — السبب: {row.get("reason")}',
        entity_type='admin_access_request', entity_id=row['id'])
    return jsonify({'success': True, 'request': row}), 201


@app.route('/api/admin/access-requests', methods=['GET'])
@require_admin
def api_admin_list_access_requests():
    rows = db.list_admin_access_requests(admin_tenant_id=g.tenant_id,
                                         status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/access-requests', methods=['GET'])
@require_auth
def api_client_list_access_requests():
    """The client sees every platform-admin access request targeting it (d07)."""
    if not _omran_actor_is_admin() and not _omran_can('manage_users'):
        return _omran_forbidden('عرض طلبات الوصول يتطلب صلاحية إدارة المستخدمين')
    rows = db.list_admin_access_requests(tenant_id=g.tenant_id,
                                         status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/access-requests/<request_id>/decision', methods=['POST'])
@require_auth
def api_client_decide_access_request(request_id):
    """The client's company admin approves or denies the request (d07)."""
    if not _omran_actor_is_admin():
        return _omran_forbidden('قرار طلب الوصول لمدير الشركة فقط')
    data = request.json or {}
    row = db.decide_admin_access_request(
        request_id, g.tenant_id, data.get('decision'),
        _omran_actor_id(), _omran_actor_name(),
        note=data.get('note'), hours=data.get('hours'),
    )
    failure = _omran_error(row)
    if failure:
        return failure
    _record_audit_event('admin_access.' + str(data.get('decision')),
                        'admin_access_request', request_id,
                        entity_name=row.get('reason'),
                        new_value={'status': row.get('status'), 'expires_at': row.get('expires_at')})
    return jsonify({'success': True, 'request': row})


@app.route('/api/access-requests/<request_id>/revoke', methods=['POST'])
@require_auth
def api_client_revoke_access_request(request_id):
    """The client closes an active grant before its expiry."""
    if not _omran_actor_is_admin():
        return _omran_forbidden('إلغاء الوصول لمدير الشركة فقط')
    row = db.revoke_admin_access_request(request_id, g.tenant_id, _omran_actor_name())
    failure = _omran_error(row)
    if failure:
        return failure
    _record_audit_event('admin_access.revoked', 'admin_access_request', request_id,
                        entity_name=row.get('reason'))
    return jsonify({'success': True, 'request': row})


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
