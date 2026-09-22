


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tenant users and permissions: user CRUD, the primary
# company-admin role, per-user permission and field-section visibility, and
# the users report.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ─────────────────────────────────────────────────────────────────────────────
# Users CRUD (company employees/admins within a tenant)
# ─────────────────────────────────────────────────────────────────────────────

def create_user(tenant_id, name, email, password_hash, role='employee',
                username=None, phone=None, require_password_change=False):
    """Create a user within a tenant. Every row is an employee — the single
    company admin is the tenant-direct identity, never a role value."""
    conn = get_db()
    user_id = str(uuid.uuid4())
    clean_role = role if role in USER_ROLES else 'employee'
    conn.execute(
        '''INSERT INTO users
           (id, tenant_id, name, username, phone, email, password_hash, role,
            is_active, require_password_change)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)''',
        (user_id, tenant_id, name, username.lower() if username else None, phone,
         email.lower(), password_hash, clean_role, 1 if require_password_change else 0)
    )
    conn.commit()
    return user_id


def get_user_by_email(email):
    """Fetch a user by email (for login). Returns user dict with tenant info."""
    conn = get_db()
    row = conn.execute(
        'SELECT u.*, t.company_name, t.is_active as tenant_active, t.is_admin as tenant_is_admin '
        'FROM users u JOIN tenants t ON u.tenant_id = t.id '
        'WHERE u.email = ?', (email.lower(),)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_username(username):
    """Fetch a user by username with tenant account state."""
    conn = get_db()
    row = conn.execute(
        '''SELECT u.*, t.company_name, t.is_active AS tenant_active,
                  t.is_admin AS tenant_is_admin
           FROM users u JOIN tenants t ON u.tenant_id = t.id
           WHERE LOWER(u.username) = LOWER(?)''',
        (str(username or '').strip(),)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id):
    """Fetch a user by ID."""
    conn = get_db()
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def get_users_by_tenant(tenant_id):
    """Get all users for a tenant."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT id, name, username, phone, email, role, is_active,
                  require_password_change, last_login_at, created_at
           FROM users WHERE tenant_id = ? ORDER BY created_at''',
        (tenant_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def update_user(user_id, **fields):
    """Update a user."""
    conn = get_db()
    allowed = {
        'name', 'username', 'phone', 'email', 'password_hash', 'role',
        'is_active', 'require_password_change'
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    if 'email' in updates:
        updates['email'] = updates['email'].lower()
    if 'username' in updates and updates['username']:
        updates['username'] = updates['username'].lower()
    if 'role' in updates and updates['role'] not in USER_ROLES:
        updates['role'] = 'employee'
    set_parts = [f'{k} = ?' for k in updates]
    # A new password retires every session token issued under the old one.
    if 'password_hash' in updates:
        set_parts.append('session_version = COALESCE(session_version, 0) + 1')
    set_clause = ', '.join(set_parts)
    values = list(updates.values()) + [user_id]
    conn.execute(f'UPDATE users SET {set_clause} WHERE id = ?', values)
    link = conn.execute(
        'SELECT tenant_id FROM users WHERE id = ?', (user_id,)
    ).fetchone()
    # The primary company admin shares one login identity with the tenants row
    # (ISS-002): credential and profile edits must land on both records, or the
    # company login keeps authenticating with values the management record
    # already replaced. ``is_active``/``role`` stay person-level — the login
    # gate reads the primary row's live state itself.
    if link and conn.execute(
        'SELECT 1 FROM tenants WHERE id = ? AND primary_user_id = ?',
        (link['tenant_id'], user_id)
    ).fetchone():
        mirror_map = {
            'name': 'account_manager_name',
            'username': 'username',
            'phone': 'phone',
            'email': 'email',
            'password_hash': 'password_hash',
            'require_password_change': 'require_password_change',
        }
        mirrored = {mirror_map[key]: value for key, value in updates.items() if key in mirror_map}
        if mirrored:
            mirror_parts = [f'{key} = ?' for key in mirrored]
            if 'password_hash' in updates:
                mirror_parts.append('session_version = COALESCE(session_version, 0) + 1')
            conn.execute(
                f"UPDATE tenants SET {', '.join(mirror_parts)} WHERE id = ?",
                [*mirrored.values(), link['tenant_id']]
            )
    if 'is_active' in updates and not updates['is_active']:
        _revoke_password_setup_tokens(conn, user_id=user_id)
    conn.commit()
    return True


def set_primary_company_admin(tenant_id, user_id):
    """Assign an existing tenant user as the primary company administrator."""
    conn = get_db()
    user = conn.execute(
        'SELECT * FROM users WHERE id = ? AND tenant_id = ?',
        (user_id, tenant_id)
    ).fetchone()
    if not user:
        return False
    tenant = conn.execute(
        'SELECT primary_user_id FROM tenants WHERE id = ?', (tenant_id,)
    ).fetchone()
    previous_user_id = tenant['primary_user_id'] if tenant else None
    try:
        if previous_user_id and previous_user_id != user_id:
            # The outgoing admin becomes a plain employee row; its grants stay
            # for the company to trim as it sees fit.
            conn.execute(
                "UPDATE users SET role = 'employee' WHERE id = ? AND tenant_id = ?",
                (previous_user_id, tenant_id)
            )
        conn.execute(
            "UPDATE users SET role = 'employee', is_active = 1 WHERE id = ?",
            (user_id,)
        )
        _grant_all_permissions(conn, user_id)
        conn.execute(
            '''UPDATE tenants
               SET primary_user_id = ?, account_manager_name = ?, username = ?, phone = ?,
                   email = ?, password_hash = ?, require_password_change = ?,
                   session_version = COALESCE(session_version, 0) + 1
               WHERE id = ?''',
            (user_id, user['name'], user['username'], user['phone'], user['email'],
             user['password_hash'], user['require_password_change'], tenant_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def sync_primary_company_admin(tenant_id, **fields):
    """Update the tenant account and its primary company administrator together."""
    conn = get_db()
    tenant = conn.execute(
        'SELECT * FROM tenants WHERE id = ?', (tenant_id,)
    ).fetchone()
    if not tenant:
        return False
    user_id = tenant['primary_user_id']
    user_updates = {}
    tenant_updates = {}
    mapping = {
        'account_manager_name': 'name',
        'username': 'username',
        'phone': 'phone',
        'email': 'email',
        'password_hash': 'password_hash',
        'require_password_change': 'require_password_change',
        'is_active': 'is_active',
    }
    for key, value in fields.items():
        tenant_updates[key] = value
        if key in mapping:
            user_updates[mapping[key]] = value
    try:
        if tenant_updates:
            set_clause = ', '.join(f'{key} = ?' for key in tenant_updates)
            conn.execute(
                f'UPDATE tenants SET {set_clause} WHERE id = ?',
                [*tenant_updates.values(), tenant_id]
            )
        if user_id and user_updates:
            set_clause = ', '.join(f'{key} = ?' for key in user_updates)
            conn.execute(
                f'UPDATE users SET {set_clause} WHERE id = ? AND tenant_id = ?',
                [*user_updates.values(), user_id, tenant_id]
            )
        # A synced password rewrite retires sessions on both login identities.
        if 'password_hash' in fields:
            conn.execute(
                'UPDATE tenants SET session_version = COALESCE(session_version, 0) + 1 WHERE id = ?',
                (tenant_id,)
            )
            if user_id:
                conn.execute(
                    'UPDATE users SET session_version = COALESCE(session_version, 0) + 1 WHERE id = ?',
                    (user_id,)
                )
        if 'is_active' in fields and not fields['is_active']:
            _revoke_password_setup_tokens(conn, tenant_id=tenant_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def get_primary_admin_name(tenant_id):
    """Display name of the tenant's primary company admin — the person behind a
    tenant-level login, which otherwise only knows the company name."""
    conn = get_db()
    row = conn.execute(
        '''SELECT COALESCE(NULLIF(u.name, ''), NULLIF(t.account_manager_name, ''), '') AS name
           FROM tenants t LEFT JOIN users u ON u.id = t.primary_user_id
           WHERE t.id = ?''', (tenant_id,)).fetchone()
    return (row['name'] or '') if row else ''


def is_primary_company_admin(tenant_id, user_id):
    """True when this users row is the tenant's designated primary admin.

    The primary admin and the tenant row are one login identity (ISS-002), so
    auth code calls this wherever a user-bound credential might actually be the
    company owner."""
    if not user_id or not tenant_id:
        return False
    conn = get_db()
    row = conn.execute(
        'SELECT 1 FROM tenants WHERE id = ? AND primary_user_id = ?',
        (tenant_id, user_id)
    ).fetchone()
    return row is not None


def delete_user(user_id):
    """Delete a user."""
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()


# Available permissions per section
PERMISSION_KEYS = [
    'dashboard',
    'create_presentation',
    'view_presentations',
    'generate_images',
    'generate_maps',
    'company_settings',
    'custom_fields',
    'manage_users',
    'ai_rules',
    'training_data',
    'approvals',
    'approve_generation',
    'approve_final_file',
    'export_files',
    'support_tickets',
    'copy_presentation',
    'post_approval_edit',
    'billing',
    'audit_log',
    'sag_admin_panel',
]

# A company has exactly three authority levels: the platform super admin, the
# single company admin (the tenant-direct identity / primary user link), and
# employees — every row in ``users`` is an employee. Capability lives in the
# per-user permission grants below, so an employee can hold every company
# permission without ever leaving the employee role.
USER_ROLES = (
    'employee',
)

DEFAULT_PERMISSIONS = {
    'employee': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': True,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
}

# Presets of the retired roles — kept only so the role-collapse migration can
# convert each existing user's effective access into explicit grants before
# the role is rewritten to 'employee'.
_RETIRED_ROLE_PRESETS = {
    'company_admin': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'generate_images': True,
        'generate_maps': True,
        'company_settings': True,
        'custom_fields': True,
        'manage_users': True,
        'ai_rules': True,
        'training_data': True,
        'approvals': True,
        'approve_generation': True,
        'approve_final_file': True,
        'export_files': True,
        'support_tickets': True,
        'copy_presentation': True,
        'post_approval_edit': True,
        'billing': True,
        'audit_log': True,
        'sag_admin_panel': False,
    },
    'section_editor': {
        'dashboard': True,
        'create_presentation': True,
        'view_presentations': True,
        'generate_images': True,
        'generate_maps': True,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': True,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'section_approver': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': True,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'generation_approver': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': True,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'final_file_approver': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': True,
        'export_files': True,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'profile': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': False,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': True,
        'custom_fields': True,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': False,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': False,
        'audit_log': False,
        'sag_admin_panel': False,
    },
    'support': {
        'dashboard': True,
        'create_presentation': False,
        'view_presentations': True,
        'generate_images': False,
        'generate_maps': False,
        'company_settings': False,
        'custom_fields': False,
        'manage_users': False,
        'ai_rules': False,
        'training_data': False,
        'approvals': False,
        'approve_generation': False,
        'approve_final_file': False,
        'export_files': False,
        'support_tickets': True,
        'copy_presentation': False,
        'post_approval_edit': False,
        'billing': True,
        'audit_log': False,
        'sag_admin_panel': False,
    },
}


def get_user_permissions(user_id, default_role='employee'):
    """Get effective permissions for a user. Defaults apply when no override exists."""
    conn = get_db()
    defaults = DEFAULT_PERMISSIONS.get(default_role, DEFAULT_PERMISSIONS['employee']).copy()
    rows = conn.execute(
        'SELECT permission_key, granted FROM user_permissions WHERE user_id = ?',
        (user_id,)
    ).fetchall()
    for row in rows:
        defaults[row['permission_key']] = bool(row['granted'])
    return defaults


def set_user_permission(user_id, permission_key, granted):
    """Set or override a permission for a user."""
    if permission_key not in PERMISSION_KEYS:
        return False
    conn = get_db()
    perm_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO user_permissions (id, user_id, permission_key, granted, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, permission_key) DO UPDATE SET
           granted = excluded.granted, updated_at = excluded.updated_at''',
        (perm_id, user_id, permission_key, 1 if granted else 0, now, now)
    )
    conn.commit()
    return True


def has_permission(user_id, permission_key, default_role='employee'):
    """Check if a user has a specific permission."""
    perms = get_user_permissions(user_id, default_role)
    return perms.get(permission_key, False)


def _grant_all_permissions(conn, user_id):
    """Write every company permission as an explicit grant on this user row.

    sag_admin_panel stays platform-only — it is not a company permission and
    the auth layer hardwires it to super-admin sessions regardless of grants.
    """
    now = _utcnow().isoformat()
    for key in PERMISSION_KEYS:
        if key == 'sag_admin_panel':
            continue
        conn.execute(
            '''INSERT INTO user_permissions (id, user_id, permission_key, granted, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?)
               ON CONFLICT(user_id, permission_key) DO UPDATE SET
               granted = 1, updated_at = excluded.updated_at''',
            (str(uuid.uuid4()), user_id, key, now, now)
        )


def grant_company_admin_permissions(user_id):
    """Public wrapper for the primary admin row — full company access."""
    conn = get_db()
    _grant_all_permissions(conn, user_id)
    conn.commit()


def _collapse_legacy_user_roles(conn):
    """Fold the retired assignable roles into the single 'employee' role.

    The three-level model has no assignable company_admin: the company admin is
    the tenant-direct identity, and employees may hold any subset of company
    permissions. Before rewriting ``users.role`` each user's effective access —
    the old role preset adjusted by its permission overrides — is frozen into
    explicit user_permissions rows so nobody silently loses (or gains) access.
    Retired company_admin rows receive every company permission: their old
    bypass already behaved that way.
    """
    try:
        rows = conn.execute(
            "SELECT id, role FROM users WHERE role IS NOT NULL AND role != 'employee'"
        ).fetchall()
    except Exception:
        return
    for row in rows:
        overrides = conn.execute(
            'SELECT permission_key, granted FROM user_permissions WHERE user_id = ?',
            (row['id'],)
        ).fetchall()
        if row['role'] == 'company_admin':
            _grant_all_permissions(conn, row['id'])
        else:
            effective = dict(_RETIRED_ROLE_PRESETS.get(row['role'], DEFAULT_PERMISSIONS['employee']))
            for override in overrides:
                effective[override['permission_key']] = bool(override['granted'])
            now = _utcnow().isoformat()
            for key, granted in effective.items():
                if key not in PERMISSION_KEYS or key == 'sag_admin_panel':
                    continue
                conn.execute(
                    '''INSERT INTO user_permissions
                       (id, user_id, permission_key, granted, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(user_id, permission_key) DO UPDATE SET
                       granted = excluded.granted, updated_at = excluded.updated_at''',
                    (str(uuid.uuid4()), row['id'], key, 1 if granted else 0, now, now)
                )
        conn.execute("UPDATE users SET role = 'employee' WHERE id = ?", (row['id'],))
    if rows:
        print(f'[DB] Migration: collapsed {len(rows)} legacy user role(s) to employee')


def get_user_field_sections(user_id, tenant_id=None):
    """Get effective field section visibility for a user. Defaults to all granted."""
    conn = get_db()
    if tenant_id is None:
        # Try to get tenant_id from user
        user_row = conn.execute('SELECT tenant_id FROM users WHERE id = ?', (user_id,)).fetchone()
        tenant_id = user_row['tenant_id'] if user_row else None
    defaults = DEFAULT_FIELD_SECTIONS.copy()
    # Add custom sections as granted by default
    if tenant_id:
        custom = get_custom_sections(tenant_id)
        for s in custom:
            if s.get('is_active', 1):
                defaults[s['section_key']] = True
    rows = conn.execute(
        'SELECT section_key, granted FROM user_field_sections WHERE user_id = ?',
        (user_id,)
    ).fetchall()
    for row in rows:
        defaults[row['section_key']] = bool(row['granted'])
    return defaults


def set_user_field_section(user_id, section_key, granted):
    """Set or override visibility for a field section for a user."""
    conn = get_db()
    section_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    conn.execute(
        '''INSERT INTO user_field_sections (id, user_id, section_key, granted, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, section_key) DO UPDATE SET
           granted = excluded.granted, updated_at = excluded.updated_at''',
        (section_id, user_id, section_key, 1 if granted else 0, now, now)
    )
    conn.commit()
    return True


def has_field_section(user_id, section_key):
    """Check if a user can see a specific field section."""
    sections = get_user_field_sections(user_id)
    return sections.get(section_key, False)


def tenant_users_report(tenant_id):
    """t22: active, invited, disabled users plus the newest invite links."""
    conn = get_db()
    users = []
    for row in conn.execute(
        'SELECT id, name, email, username, role, is_active, require_password_change, '
        'last_login_at, created_at FROM users WHERE tenant_id = ? ORDER BY created_at DESC',
        (tenant_id,),
    ).fetchall():
        users.append(dict(row))
    invites = []
    try:
        for row in conn.execute(
            'SELECT id, email, token, expires_at, used_at, name, role, email_status, '
            'email_error, email_attempts, email_sent_at FROM invite_links '
            'WHERE tenant_id = ? ORDER BY expires_at DESC LIMIT 25',
            (tenant_id,),
        ).fetchall():
            invite = dict(row)
            try:
                invite['is_expired'] = bool(invite['expires_at']) and datetime.fromisoformat(invite['expires_at']) < _utcnow()
            except (TypeError, ValueError):
                invite['is_expired'] = False
            invite['is_used'] = bool(invite.get('used_at'))
            invites.append(invite)
    except Exception:
        invites = []
    active = [u for u in users if u['is_active']]
    return {
        'users': users,
        'invites': invites,
        'counts': {
            'total': len(users),
            'active': len(active),
            'disabled': len(users) - len(active),
            'pending_invites': len([i for i in invites if not i['is_used'] and not i['is_expired']]),
        },
    }
