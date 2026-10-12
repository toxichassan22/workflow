


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fonts: the SAG font catalog and each tenant's per-script,
# per-weight font selections.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_sag_fonts(script=None, weight=None, active_only=True):
    conn = get_db()
    query = 'SELECT id, font_name, font_family, script, weight, style, source_type, source_data, is_active, is_default, created_at, updated_at FROM sag_fonts WHERE 1=1'
    params = []
    if active_only:
        query += ' AND is_active = 1'
    if script:
        query += ' AND script = ?'
        params.append(script)
    if weight:
        query += ' AND weight = ?'
        params.append(weight)
    query += ' ORDER BY script, weight, is_default DESC, font_name'
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_sag_font(font_id):
    row = get_db().execute('SELECT * FROM sag_fonts WHERE id = ?', (font_id,)).fetchone()
    return dict(row) if row else None


def create_sag_font(font_name, font_family, script, weight, style='normal', source_type='uploaded', source_data=None, file_data=None):
    font_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        '''INSERT INTO sag_fonts
           (id, font_name, font_family, script, weight, style, source_type, source_data, file_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (font_id, font_name, font_family, script, weight, style, source_type, source_data, file_data),
    )
    conn.commit()
    return font_id


def update_sag_font(font_id, **fields):
    allowed = {'font_name', 'font_family', 'is_active', 'is_default'}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return False
    if updates.get('is_default'):
        current = get_sag_font(font_id)
        if current:
            get_db().execute(
                'UPDATE sag_fonts SET is_default = 0 WHERE script = ? AND weight = ?',
                (current['script'], current['weight']),
            )
    updates['updated_at'] = _utcnow().isoformat()
    clause = ', '.join(f'{key} = ?' for key in updates)
    get_db().execute(f'UPDATE sag_fonts SET {clause} WHERE id = ?', list(updates.values()) + [font_id])
    get_db().commit()
    return True


def get_tenant_font_selections(tenant_id):
    rows = get_db().execute(
        'SELECT * FROM tenant_font_selections WHERE tenant_id = ? ORDER BY script, weight',
        (tenant_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_tenant_font_selection(tenant_id, script, weight):
    row = get_db().execute(
        'SELECT * FROM tenant_font_selections WHERE tenant_id = ? AND script = ? AND weight = ?',
        (tenant_id, script, weight),
    ).fetchone()
    return dict(row) if row else None


def set_tenant_font_selection(tenant_id, script, weight, font_id=None, custom_font_path=None, custom_font_data=None):
    selection_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    get_db().execute(
        '''INSERT INTO tenant_font_selections
           (id, tenant_id, script, weight, font_id, custom_font_path, custom_font_data, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(tenant_id, script, weight) DO UPDATE SET
           font_id = excluded.font_id,
           custom_font_path = excluded.custom_font_path,
           custom_font_data = excluded.custom_font_data,
           updated_at = excluded.updated_at''',
        (selection_id, tenant_id, script, weight, font_id, custom_font_path, custom_font_data, now, now),
    )
    get_db().commit()
    return selection_id


def delete_tenant_font_selection(tenant_id, script, weight):
    get_db().execute(
        'DELETE FROM tenant_font_selections WHERE tenant_id = ? AND script = ? AND weight = ?',
        (tenant_id, script, weight),
    )
    get_db().commit()
