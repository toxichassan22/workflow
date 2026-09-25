# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Access-control surface (t20-t22): tenant role templates cloned onto
# users, the users report, the separation-of-duties matrix, and tenant
# policies.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
