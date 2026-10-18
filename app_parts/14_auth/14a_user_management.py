# Tenant user, assignment and invitation routes.

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
    assignment_error = _apply_user_responsibility_payload(user_id, data)
    if data.get('responsibility') != 'admin':
        _apply_user_scope_payload(user_id, data)
    try:
        email_sent = _send_user_welcome_email(email, name, db.get_tenant_by_id(g.tenant_id))
    except Exception:
        email_sent = False
    _record_audit_event('user.created', 'user', user_id, entity_name=name,
                        metadata={'email': email, 'email_sent': email_sent})
    return jsonify({'success': True, 'userId': user_id, 'emailSent': email_sent,
                    'assignmentError': assignment_error}), 201


def _apply_user_responsibility_payload(user_id, data):
    """Apply the responsibility picked on the add form («editor»/«approver»
    become project assignments, «admin» grants every company permission).
    Returns a conflict message when an assignment could not be set."""
    responsibility = data.get('responsibility') or None
    if responsibility == 'admin':
        db.grant_company_admin_permissions(user_id)
        return None
    if responsibility in db.ASSIGNMENT_ROLES:
        db.apply_responsibility_preset(user_id, responsibility)
        projects = data.get('projects')
        draft_ids = [str(p) for p in projects] if isinstance(projects, list) and projects else [db.ASSIGNMENT_ALL_DRAFTS]
        result = db.set_user_assignments(
            g.tenant_id, user_id, [{'draft_id': d, 'role': responsibility} for d in draft_ids])
        if result.get('error'):
            return result['error']
    elif responsibility is not None:
        return 'invalid_responsibility'
    return None


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
    # support_tickets and billing are pinned off for employees — offering them
    # as toggles would flip and revert; sag_admin_panel is platform-session only.
    keys = [k for k in db.PERMISSION_KEYS
            if k not in ('sag_admin_panel', 'support_tickets', 'billing')]
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


@app.route('/api/users/<user_id>/assignments', methods=['GET'])
@require_permission('manage_users')
def api_get_user_assignments(user_id):
    """A user's responsibility assignments (editor/approver per project)."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'success': True,
                    'assignments': db.list_user_assignments(g.tenant_id, user_id)})


@app.route('/api/users/<user_id>/assignments', methods=['PUT'])
@require_permission('manage_users')
def api_set_user_assignments(user_id):
    """Replace a user's assignments. Refused when a requested approver slot is
    already held by someone else — one approver per project."""
    user = db.get_user_by_id(user_id)
    if not user or user['tenant_id'] != g.tenant_id:
        return jsonify({'error': 'User not found'}), 404
    data = request.json or {}
    result = db.set_user_assignments(
        g.tenant_id, user_id, data.get('assignments') or [])
    if result.get('error') == 'user_not_found':
        return jsonify({'error': 'User not found'}), 404
    if result.get('error') == 'approver_exists':
        return jsonify({
            'error': f'المشروع له معتمد بالفعل: {result.get("holder") or "مستخدم آخر"}',
            'error_code': 'approver_exists',
            'holder': result.get('holder'),
        }), 409
    if result.get('error') == 'too_many_editors':
        return jsonify({
            'error': 'المشروع يقبل خمسة محررين كحد أقصى',
            'error_code': 'too_many_editors',
        }), 409
    _record_audit_event('user.assignments_changed', 'user', user_id,
                        new_value=result.get('assignments'))
    return jsonify({'success': True, 'assignments': result.get('assignments')})


@app.route('/api/assignments', methods=['GET'])
@require_permission('manage_users')
def api_list_tenant_assignments():
    """Every assignment in the company — the admin needs the tenant-wide view
    to see which projects already have an approver."""
    return jsonify({'success': True,
                    'assignments': db.list_tenant_assignments(g.tenant_id)})


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
    responsibility = data.get('responsibility') or None
    if responsibility is not None and responsibility not in db.RESPONSIBILITY_ROLES:
        return jsonify({'error': 'Invalid responsibility'}), 400
    invite = db.create_invite(
        g.tenant_id, email,
        role=role,
        name=data.get('name'), phone=data.get('phone'),
        sections=data.get('sections') if isinstance(data.get('sections'), list) else None,
        projects=data.get('projects') if isinstance(data.get('projects'), list) else None,
        responsibility=responsibility,
    )
    tenant = db.get_tenant_by_id(g.tenant_id)
    email_sent = _send_invite_email(invite, tenant, email, responsibility=responsibility)
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
    invite_assignment_error = None
    try:
        invite_assignment_error = db.apply_invite_scope(user_id, invite)
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
        'user': {'id': user_id, 'name': name, 'email': invite['email'], 'role': invite_role},
        'assignmentError': invite_assignment_error,
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
