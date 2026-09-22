


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Admin access requests (d07): a platform admin asks a company for
# temporary content access; the client lists, approves or revokes the grant
# from its own side.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
    failure = _landloom_error(row)
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
    if not _landloom_actor_is_admin() and not _landloom_can('manage_users'):
        return _landloom_forbidden('عرض طلبات الوصول يتطلب صلاحية إدارة المستخدمين')
    rows = db.list_admin_access_requests(tenant_id=g.tenant_id,
                                         status=request.args.get('status'))
    return jsonify({'success': True, 'requests': rows})


@app.route('/api/access-requests/<request_id>/decision', methods=['POST'])
@require_auth
def api_client_decide_access_request(request_id):
    """The client's company admin approves or denies the request (d07)."""
    if not _landloom_actor_is_admin():
        return _landloom_forbidden('قرار طلب الوصول لمدير الشركة فقط')
    data = request.json or {}
    row = db.decide_admin_access_request(
        request_id, g.tenant_id, data.get('decision'),
        _landloom_actor_id(), _landloom_actor_name(),
        note=data.get('note'), hours=data.get('hours'),
    )
    failure = _landloom_error(row)
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
    if not _landloom_actor_is_admin():
        return _landloom_forbidden('إلغاء الوصول لمدير الشركة فقط')
    row = db.revoke_admin_access_request(request_id, g.tenant_id, _landloom_actor_name())
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('admin_access.revoked', 'admin_access_request', request_id,
                        entity_name=row.get('reason'))
    return jsonify({'success': True, 'request': row})
