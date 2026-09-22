


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Managed per-tenant OpenRouter keys, billing packages and the USD-to-SAR
# rate (super admin only). Managed keys are provisioned through the
# OpenRouter Management API so every company key carries its own spend
# limit in the owner dashboard; the raw secret is stored encrypted and is
# never returned by any endpoint below.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
