


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Project team library (فريق العمل) plus the tenant-by-domain lookup used
# at invite time.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEAM_ENTITY_FIELDS = ('name', 'logo_file_id', 'brief',
                      'experience_years', 'notable_projects', 'role', 'sort_order')


def _row_to_team_entity(row):
    if not row:
        return None
    return {
        'id': row['id'],
        'name': row['name'] or '',
        'logoFileId': row['logo_file_id'] or '',
        'brief': row['brief'] or '',
        'experienceYears': row['experience_years'] or '',
        'notableProjects': row['notable_projects'] or '',
        'role': row['role'] or '',
        'sortOrder': row['sort_order'] if row['sort_order'] is not None else 100,
    }


def get_team_entities(tenant_id):
    """Company-wide team entities as a flat list, in the order they were added."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM tenant_team_entities WHERE tenant_id = ? ORDER BY sort_order, created_at',
        (tenant_id,)
    ).fetchall()
    return [_row_to_team_entity(row) for row in rows]


def get_team_entity(tenant_id, entity_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM tenant_team_entities WHERE tenant_id = ? AND id = ?',
        (tenant_id, entity_id)
    ).fetchone()
    return _row_to_team_entity(row)


def create_team_entity(tenant_id, name, **fields):
    conn = get_db()
    entity_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO tenant_team_entities
           (id, tenant_id, name, logo_file_id, brief,
            experience_years, notable_projects, role, sort_order)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (entity_id, tenant_id, name,
         fields.get('logo_file_id') or None, fields.get('brief') or '',
         str(fields.get('experience_years') or ''), fields.get('notable_projects') or '',
         fields.get('role') or '', fields.get('sort_order') or 100)
    )
    conn.commit()
    return entity_id


def update_team_entity(tenant_id, entity_id, **updates):
    allowed = {key: value for key, value in updates.items() if key in TEAM_ENTITY_FIELDS}
    if not allowed:
        return False
    conn = get_db()
    assignments = ', '.join(f'{key} = ?' for key in allowed)
    cursor = conn.execute(
        f'UPDATE tenant_team_entities SET {assignments}, updated_at = ? WHERE tenant_id = ? AND id = ?',
        (*allowed.values(), _utcnow().isoformat(), tenant_id, entity_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_team_entity(tenant_id, entity_id):
    conn = get_db()
    cursor = conn.execute(
        'DELETE FROM tenant_team_entities WHERE tenant_id = ? AND id = ?',
        (tenant_id, entity_id)
    )
    conn.commit()
    return cursor.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Tenant domain support
# ─────────────────────────────────────────────────────────────────────────────

def get_tenant_by_domain(domain):
    """Fetch a tenant by email domain."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM tenants WHERE domain = ? AND is_active = 1 AND is_admin = 0",
        (domain.lower(),)
    ).fetchone()
    return dict(row) if row else None
