# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Super-admin operations and tenant administration (t51, t63, Mission
# 5): operational overview, the file-type registry, company slug and
# activation/subscription, package versions, study-type and generator
# registries, the job queue, email outbox, housekeeping and backups.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── t51: operational overview; t63: file-type registry ─────────────────────

@app.route('/api/admin/operational-overview', methods=['GET'])
@require_admin
def api_operational_overview():
    return jsonify({'success': True, 'overview': db.operational_overview(
        months=request.args.get('months'),
        from_month=request.args.get('from'),
        to_month=request.args.get('to'))})


@app.route('/api/file-types', methods=['GET'])
@require_auth
def api_list_file_types():
    return jsonify({'success': True, 'fileTypes': db.get_file_type_registry()})


@app.route('/api/file-types/<key>', methods=['POST'])
@require_admin
def api_upsert_file_type(key):
    data = request.json or {}
    row = db.upsert_file_type(key, data.get('labelAr'), kind=data.get('kind') or 'document',
                              max_size_mb=data.get('maxSizeMb') or 25,
                              allowed_extensions=data.get('allowedExtensions'))
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('file_type.updated', 'file_type_registry', key, entity_name=row.get('label_ar'))
    return jsonify({'success': True, 'fileType': row})


# ── Mission 5: company file, slug, activation, subscriptions ────────────────

_COMPANY_PROFILE_KEY_MAP = {
    'legalName': 'legal_name', 'commercialName': 'commercial_name',
    'taxNumber': 'tax_number', 'crNumber': 'cr_number', 'country': 'country',
    'region': 'region', 'address': 'address', 'contactTitle': 'contact_title',
}


@app.route('/api/admin/tenants/<tenant_id>/slug', methods=['PUT'])
@require_admin
def api_admin_set_tenant_slug(tenant_id):
    """t51: set the company's URL slug; locked once the company is active."""
    tenant, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    data = request.json or {}
    allow_locked = bool(data.get('allowAfterActivation'))
    result = db.set_tenant_slug(
        tenant_id, data.get('slug'), actor_id=_landloom_actor_id(),
        actor_name=_landloom_actor_name(), allow_after_activation=allow_locked,
    )
    if result.get('error') == 'slug_locked':
        return jsonify({'error': 'slug_locked',
                        'message': 'الشركة نشطة — تغيير الرابط يتطلب تأكيدًا'}), 409
    if result.get('error') in ('invalid', 'reserved', 'taken'):
        return jsonify({'error': result['error']}), 409 if result['error'] == 'taken' else 400
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('tenant.slug_changed', 'tenant', tenant_id,
                        entity_name=tenant.get('company_name'),
                        old_value=result.get('previous'), new_value=result.get('slug'))
    return jsonify({'success': True, 'slug': result['slug'],
                    'redirectCreated': bool(result.get('redirect_created'))})


@app.route('/api/admin/tenants/<tenant_id>/activation', methods=['GET'])
@require_admin
def api_admin_tenant_activation_checklist(tenant_id):
    """t50: what is still missing before this company may go live."""
    tenant, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    checklist = db.tenant_activation_checklist(tenant)
    return jsonify({'success': True, 'isActive': bool(tenant.get('is_active')),
                    'activatedAt': tenant.get('activated_at'),
                    'activatedByName': tenant.get('activated_by_name'),
                    'checklist': checklist})


@app.route('/api/admin/tenants/<tenant_id>/activation', methods=['POST'])
@require_admin
def api_admin_set_tenant_activation(tenant_id):
    """t50: activate or suspend a company; activation passes through the gate."""
    tenant, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    data = request.json or {}
    is_active = bool(data.get('isActive', True))
    if is_active and tenant.get('is_active'):
        return jsonify({'success': True, 'tenant': _company_payload(tenant), 'unchanged': True})
    if not is_active and not tenant.get('is_active'):
        return jsonify({'success': True, 'tenant': _company_payload(tenant), 'unchanged': True})
    result = db.set_tenant_active(
        tenant_id, is_active, actor_id=_landloom_actor_id(),
        actor_name=_landloom_actor_name(), reason=data.get('reason'),
    )
    if result.get('error') == 'activation_incomplete':
        return jsonify({'error': 'activation_incomplete',
                        'missing': result.get('missing') or []}), 409
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('tenant.activated' if is_active else 'tenant.deactivated',
                        'tenant', tenant_id, entity_name=tenant.get('company_name'),
                        new_value={'reason': data.get('reason')} if not is_active else None)
    return jsonify({'success': True, 'tenant': _company_payload(result)})


@app.route('/api/admin/tenants/<tenant_id>/subscription', methods=['GET', 'POST'])
@require_admin
def api_admin_tenant_subscription(tenant_id):
    """t60: subscription window per company (one active at a time)."""
    _, error = _admin_tenant_or_404(tenant_id)
    if error:
        return error
    if request.method == 'GET':
        return jsonify({'success': True,
                        'current': db.current_subscription(tenant_id),
                        'history': db.list_subscriptions(tenant_id)})
    data = request.json or {}
    row = db.create_subscription(
        tenant_id, package_id=data.get('packageId'),
        package_version_id=data.get('packageVersionId'),
        starts_at=data.get('startsAt'), ends_at=data.get('endsAt'),
        trial_ends_at=data.get('trialEndsAt'),
        status=data.get('status') or 'active',
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
    )
    _record_audit_event('tenant.subscription_changed', 'tenant', tenant_id,
                        new_value=row.get('package_id'))
    return jsonify({'success': True, 'subscription': row}), 201


# ── Subscription watch: the desk hears once when a company's window nears its
# end and once when it lapses — the renewal nudge itself stays a human send ──

SUBSCRIPTION_WATCH_WARN_DAYS = int(os.environ.get('SUBSCRIPTION_WATCH_WARN_DAYS') or 7)


def _subscription_watch_sweep():
    """Ping every super admin when a company's paid subscription (or bare
    trial) approaches or passes its end date. One notice per state per end
    date: editing the window re-arms it, so a renewed plan never goes stale.
    The follow-up — messaging the company — stays a deliberate desk act via
    the announcement composer."""
    warned = expired = 0
    admin_ids = db.list_admin_tenant_ids()
    if not admin_ids:
        return {'warned': 0, 'expired': 0}
    now = db._utcnow()
    with _worker_app_context():
        for tenant in db.get_all_tenants() or []:
            if tenant.get('is_admin') or not tenant.get('is_active'):
                continue
            try:
                sub = db.current_subscription(tenant['id'])
            except Exception:
                sub = None
            ends_raw = str((sub or {}).get('ends_at') or '').strip()
            label = (sub or {}).get('package_name') or 'الباقة'
            if not ends_raw:
                ends_raw = str(tenant.get('trial_ends_at') or '').strip()
                label = 'الفترة التجريبية'
            if not ends_raw:
                continue
            try:
                ends_dt = datetime.fromisoformat(
                    ends_raw[:10] + 'T23:59:59' if len(ends_raw) == 10 else ends_raw)
            except (TypeError, ValueError):
                continue
            if ends_dt.tzinfo is not None:
                ends_dt = ends_dt.replace(tzinfo=None)
            state = 'expired' if ends_dt <= now else (
                'expiring' if (ends_dt - now).days <= SUBSCRIPTION_WATCH_WARN_DAYS else None)
            if not state:
                continue
            company = tenant.get('company_name') or 'شركة'
            if state == 'expiring':
                title = 'باقة شركة تقترب من الانتهاء'
                body = f'«{company}» — {label} تنتهي خلال {max(0, (ends_dt - now).days)} يوم'
            else:
                title = 'انتهت صلاحية باقة شركة'
                body = f'«{company}» — انتهت {label} في {ends_raw[:10]}'
            # tenant_id:state:ends re-arms the dedup key whenever the window moves.
            entity_id = f"{tenant['id']}:{state}:{ends_raw[:10]}"
            sent = 0
            for admin_id in admin_ids:
                if db.recent_notification_exists(
                        admin_id, 'subscription', entity_id, since_hours=24 * 3650):
                    continue
                db.create_notification(
                    admin_id, title, body, category='platform', user_id=None,
                    entity_type='subscription', entity_id=entity_id)
                sent += 1
            if not sent:
                continue
            if state == 'expiring':
                warned += 1
            else:
                expired += 1
    return {'warned': warned, 'expired': expired}


@app.route('/api/admin/packages/<package_id>/versions', methods=['GET', 'POST'])
@require_admin
def api_admin_package_versions(package_id):
    """t60: immutable package versions — pricing changes never rewrite history."""
    if request.method == 'GET':
        return jsonify({'success': True,
                        'versions': db.list_package_versions(package_id)})
    data = request.json or {}
    row = db.create_package_version(
        package_id, name=data.get('name'), credit_sar=data.get('creditSar', data.get('credit_sar')),
        price_sar=data.get('priceSar'), duration_days=data.get('durationDays'),
        limits=data.get('limits'), features=data.get('features'),
        actor_id=_landloom_actor_id(), actor_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('package.version_created', 'billing_package', package_id,
                        new_value=row.get('version'))
    return jsonify({'success': True, 'version': row}), 201


# ── Mission 5: registries, flags, queue, outbox, backups ────────────────────

@app.route('/api/admin/study-types', methods=['GET', 'POST'])
@require_admin
def api_admin_study_types():
    """t62: versioned study-type registry."""
    if request.method == 'GET':
        active_only = request.args.get('all') != '1'
        return jsonify({'success': True,
                        'studyTypes': db.list_study_types(active_only=active_only)})
    data = request.json or {}
    row = db.register_study_type(
        data.get('key'), data.get('nameAr'), name_en=data.get('nameEn'),
        definition=data.get('definition'),
        supersedes_version=data.get('supersedesVersion'),
        created_by=_landloom_actor_id(), created_by_name=_landloom_actor_name(),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('study_type.registered', 'study_type', row['key'],
                        new_value=row.get('version'))
    return jsonify({'success': True, 'studyType': row}), 201


@app.route('/api/admin/generators', methods=['GET', 'POST'])
@require_admin
def api_admin_generators():
    """t62: versioned generator registry (templates, models, processors)."""
    if request.method == 'GET':
        return jsonify({'success': True,
                        'generators': db.list_generators(kind=request.args.get('kind'))})
    data = request.json or {}
    row = db.register_generator(
        data.get('kind'), data.get('key'), config=data.get('config'),
        label_ar=data.get('labelAr'), label_en=data.get('labelEn'),
        supersedes_version=data.get('supersedesVersion'),
    )
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('generator.registered', 'generator_registry',
                        f"{row['kind']}:{row['key']}", new_value=row.get('version'))
    return jsonify({'success': True, 'generator': row}), 201


@app.route('/api/admin/jobs', methods=['GET'])
@require_admin
def api_admin_jobs():
    """t61: inspect the persistent background queue."""
    return jsonify({'success': True,
                    'jobs': db.list_jobs(status=request.args.get('status'),
                                         job_type=request.args.get('type')),
                    'stats': db.job_queue_stats()})


@app.route('/api/admin/jobs/requeue', methods=['POST'])
@require_admin
def api_admin_jobs_requeue():
    data = request.json or {}
    count = db.requeue_dead_jobs(job_type=data.get('type'))
    _record_audit_event('job_queue.requeue', 'job_queue', data.get('type'),
                        new_value=count)
    return jsonify({'success': True, 'requeued': count})


@app.route('/api/admin/email-outbox', methods=['GET'])
@require_admin
def api_admin_email_outbox():
    """t61/t41: outbound mail queue state."""
    return jsonify({'success': True,
                    'emails': db.list_email_outbox(status=request.args.get('status')),
                    'stats': db.email_outbox_stats()})


@app.route('/api/admin/housekeeping/run', methods=['POST'])
@require_admin
def api_admin_housekeeping_run():
    """t24/t41: run one housekeeping pass on demand — the same tick the
    background thread performs, so an operator or a cron can force it."""
    summary = _run_housekeeping_tick()
    _record_audit_event('housekeeping.run', 'housekeeping', 'manual',
                        metadata={'summary': summary})
    return jsonify({'success': True, 'summary': summary})


@app.route('/api/admin/backups', methods=['GET', 'POST'])
@require_admin
def api_admin_backups():
    """t63: backup registry — the run script POSTs each completed backup."""
    if request.method == 'GET':
        return jsonify({'success': True, 'backups': db.list_backups(),
                        'latest': db.latest_successful_backup(),
                        'rpoHours': db.RPO_TARGET_HOURS, 'rtoHours': db.RTO_TARGET_HOURS})
    data = request.json or {}
    row = db.record_backup(
        kind=data.get('kind') or 'full', path=data.get('path'),
        size_bytes=data.get('sizeBytes'), sha256=data.get('sha256'),
        encrypted=bool(data.get('encrypted')), note=data.get('note'),
    )
    _record_audit_event('backup.recorded', 'backup', row['id'],
                        new_value={'kind': row['kind'], 'size_bytes': row.get('size_bytes')})
    return jsonify({'success': True, 'backup': row}), 201


@app.route('/api/admin/backups/<backup_id>/restore-tested', methods=['POST'])
@require_admin
def api_admin_backup_restore_tested(backup_id):
    row = db.mark_backup_restore_tested(backup_id, note=(request.json or {}).get('note'))
    if not row:
        return jsonify({'error': 'Backup not found'}), 404
    _record_audit_event('backup.restore_tested', 'backup', backup_id)
    return jsonify({'success': True, 'backup': row})


@app.route('/api/admin/stats', methods=['GET'])
@require_admin
def api_admin_stats():
    """Get global stats (admin only)."""
    return jsonify({'success': True, 'stats': db.get_stats()})
