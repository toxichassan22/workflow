# ─────────────────────────────────────────────────────────────────────────────
# Project File Storage
# ─────────────────────────────────────────────────────────────────────────────

def create_project_file(tenant_id, file_type, original_name, storage_path, mime_type, file_size, sha256,
                        draft_id=None, project_id=None):
    conn = get_db()
    file_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO project_files
           (id, tenant_id, draft_id, project_id, file_type, original_name, storage_path,
            mime_type, file_size, sha256)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (file_id, tenant_id, draft_id, project_id, file_type, original_name, storage_path,
         mime_type, int(file_size or 0), sha256)
    )
    conn.commit()
    return file_id


def get_project_file(tenant_id, file_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_files WHERE id = ? AND tenant_id = ?',
        (file_id, tenant_id)
    ).fetchone()
    return dict(row) if row else None


def get_project_file_by_id(file_id):
    """Cross-tenant lookup, used only behind a super-admin check."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_files WHERE id = ?',
        (file_id,)
    ).fetchone()
    return dict(row) if row else None


def delete_project_file(tenant_id, file_id):
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_files WHERE id = ? AND tenant_id = ?',
        (file_id, tenant_id)
    ).fetchone()
    if not row:
        return None
    conn.execute(
        'DELETE FROM project_files WHERE id = ? AND tenant_id = ?',
        (file_id, tenant_id)
    )
    conn.commit()
    return dict(row)


def get_project_files(tenant_id, draft_id=None, project_id=None, file_type=None):
    conn = get_db()
    query = 'SELECT * FROM project_files WHERE tenant_id = ?'
    params = [tenant_id]
    if draft_id:
        query += ' AND draft_id = ?'
        params.append(draft_id)
    if project_id:
        query += ' AND project_id = ?'
        params.append(project_id)
    if file_type:
        query += ' AND file_type = ?'
        params.append(file_type)
    query += ' ORDER BY created_at DESC, rowid DESC'
    return [dict(row) for row in conn.execute(query, params).fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Map Images Storage
# ─────────────────────────────────────────────────────────────────────────────

def add_map_image(tenant_id, image_type, file_path, placeholder, presentation_id=None, metadata=None):
    """Store a reference to a generated map image."""
    conn = get_db()
    image_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO map_images
           (id, tenant_id, presentation_id, image_type, file_path, placeholder, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (image_id, tenant_id, presentation_id, image_type, file_path, placeholder,
         json.dumps(metadata, ensure_ascii=False) if metadata else None)
    )
    conn.commit()
    return image_id


def update_map_image(image_id, tenant_id, file_path, placeholder, metadata=None):
    conn = get_db()
    conn.execute(
        '''UPDATE map_images SET file_path = ?, placeholder = ?, metadata_json = ?
           WHERE id = ? AND tenant_id = ?''',
        (file_path, placeholder, json.dumps(metadata, ensure_ascii=False) if metadata else None,
         image_id, tenant_id)
    )
    conn.commit()


def get_map_images(tenant_id, presentation_id=None, draft_id=None, image_type=None):
    """Get map images for a tenant, optionally filtered by presentation, draft, and type."""
    conn = get_db()
    query = 'SELECT * FROM map_images WHERE tenant_id = ?'
    params = [tenant_id]
    if presentation_id:
        query += ' AND presentation_id = ?'
        params.append(presentation_id)
    elif draft_id:
        query += ' AND presentation_id = ?'
        params.append(f"draft_{draft_id}")
    if image_type:
        query += ' AND image_type = ?'
        params.append(image_type)
    query += ' ORDER BY created_at DESC, rowid DESC'
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def delete_map_images(tenant_id, presentation_id=None, image_type=None):
    """Delete map image records for a tenant (does not delete files)."""
    conn = get_db()
    query = 'DELETE FROM map_images WHERE tenant_id = ?'
    params = [tenant_id]
    if presentation_id:
        query += ' AND presentation_id = ?'
        params.append(presentation_id)
    if image_type:
        query += ' AND image_type = ?'
        params.append(image_type)
    conn.execute(query, params)
    conn.commit()
