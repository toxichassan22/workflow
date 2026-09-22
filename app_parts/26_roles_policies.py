# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Access-control surface (t20-t22): tenant role templates cloned onto
# users, the users report, the separation-of-duties matrix, and tenant
# policies.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── t20: role templates cloned onto users; built-ins stay code-defined ───────

@app.route('/api/roles/template', methods=['GET'])
@require_permission('manage_users')
def api_role_template():
    return jsonify({'success': True, **db.list_tenant_role_templates(g.tenant_id)})


@app.route('/api/roles', methods=['POST'])
@require_permission('manage_users')
def api_create_tenant_role():
    data = request.json or {}
    row = db.create_tenant_role(g.tenant_id, data.get('name'), data.get('baseRole') or 'employee',
                                data.get('permissions'))
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('role.created', 'tenant_role', row['id'], entity_name=row['name'],
                        new_value=json.dumps(row.get('permissions') or {}, ensure_ascii=False))
    return jsonify({'success': True, 'role': row})


@app.route('/api/roles/<role_id>/update', methods=['POST'])
@require_permission('manage_users')
def api_update_tenant_role(role_id):
    data = request.json or {}
    row = db.update_tenant_role(g.tenant_id, role_id, name=data.get('name'),
                                permissions=data.get('permissions'))
    if not row:
        return jsonify({'error': 'Role not found', 'error_code': 'task_not_found'}), 404
    failure = _landloom_error(row)
    if failure:
        return failure
    _record_audit_event('role.updated', 'tenant_role', role_id, entity_name=row.get('name'),
                        new_value=json.dumps(row.get('permissions') or {}, ensure_ascii=False))
    return jsonify({'success': True, 'role': row})


@app.route('/api/roles/<role_id>/delete', methods=['POST'])
@require_permission('manage_users')
def api_delete_tenant_role(role_id):
    if not db.delete_tenant_role(g.tenant_id, role_id):
        return jsonify({'error': 'Role not found', 'error_code': 'task_not_found'}), 404
    _record_audit_event('role.deleted', 'tenant_role', role_id)
    return jsonify({'success': True})


@app.route('/api/roles/<role_id>/assign', methods=['POST'])
@require_permission('manage_users')
def api_assign_tenant_role(role_id):
    data = request.json or {}
    user_id = data.get('userId')
    user = db.get_user_by_id(user_id) if user_id else None
    if not user or user.get('tenant_id') != g.tenant_id:
        return jsonify({'error': 'User not found in this company', 'error_code': 'task_not_found'}), 404
    permissions = db.assign_tenant_role_to_user(g.tenant_id, user_id, role_id)
    if not permissions:
        return jsonify({'error': 'Role not found', 'error_code': 'task_not_found'}), 404
    _record_audit_event('role.assigned', 'user', user_id,
                        metadata={'role_id': role_id, 'role_name': (db.get_tenant_role(g.tenant_id, role_id) or {}).get('name')})
    return jsonify({'success': True, 'permissions': permissions})


# ── t22: users report; t21: separation-of-duties matrix ─────────────────────

@app.route('/api/users/report', methods=['GET'])
@require_permission('manage_users')
def api_tenant_users_report():
    return jsonify({'success': True, 'report': db.tenant_users_report(g.tenant_id)})


@app.route('/api/approvals/sod-matrix', methods=['GET'])
@require_auth
def api_sod_matrix():
    if not (_landloom_can('approvals') or _landloom_can('manage_users')):
        return _landloom_forbidden('عرض مصفوفة فصل المهام يتطلب صلاحية الاعتمادات أو إدارة المستخدمين')
    return jsonify({'success': True, 'matrix': db.separation_of_duties_matrix(g.tenant_id)})


@app.route('/api/policies', methods=['GET'])
@require_auth
def api_get_policies():
    """Tenant policy settings (d01 and siblings); read by approver tooling."""
    if not (_landloom_can('approvals') or _landloom_can('manage_users') or _landloom_can('company_settings')):
        return _landloom_forbidden('عرض سياسات الشركة يتطلب صلاحية مناسبة')
    return jsonify({'success': True, 'policies': db.get_tenant_policies(g.tenant_id)})


@app.route('/api/policies', methods=['PUT'])
@require_permission('company_settings')
def api_update_policies():
    """Update tenant policies; only known keys with allowed values apply."""
    result = db.set_tenant_policies(g.tenant_id, request.json or {})
    failure = _landloom_error(result)
    if failure:
        return failure
    _record_audit_event('policies.updated', 'tenant', g.tenant_id, new_value=result)
    return jsonify({'success': True, 'policies': result})
