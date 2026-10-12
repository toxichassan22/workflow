


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Team entities: the named people/companies a proposal can list
# on its team slide.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _team_entity_payload(data):
    """Normalise a team-entity request body; returns (fields, error)."""
    name = str(data.get('name') or '').strip()
    if not name:
        return None, 'اسم الجهة مطلوب'
    logo_file_id = str(data.get('logoFileId') or '').strip()
    if logo_file_id and not db.get_project_file(g.tenant_id, logo_file_id):
        return None, 'شعار الجهة غير موجود'
    return {
        'name': name,
        'logo_file_id': logo_file_id,
        'brief': str(data.get('brief') or '').strip(),
        'experience_years': str(data.get('experienceYears') or '').strip(),
        'notable_projects': str(data.get('notableProjects') or '').strip(),
        'role': str(data.get('role') or '').strip(),
    }, None


@app.route('/api/team-entities', methods=['GET'])
@require_auth
def api_list_team_entities():
    """Company-wide team library; every project file starts from this list."""
    return jsonify({'success': True, 'entities': db.get_team_entities(g.tenant_id)})


@app.route('/api/team-entities', methods=['POST'])
@require_permission('company_settings')
def api_create_team_entity():
    fields, error = _team_entity_payload(request.json or {})
    if error:
        return jsonify({'success': False, 'error': error}), 400
    entity_id = db.create_team_entity(g.tenant_id, fields.pop('name'), **fields)
    return jsonify({'success': True, 'entity': db.get_team_entity(g.tenant_id, entity_id)}), 201


@app.route('/api/team-entities/<entity_id>', methods=['PUT'])
@require_permission('company_settings')
def api_update_team_entity(entity_id):
    if not db.get_team_entity(g.tenant_id, entity_id):
        return jsonify({'success': False, 'error': 'الجهة غير موجودة'}), 404
    fields, error = _team_entity_payload(request.json or {})
    if error:
        return jsonify({'success': False, 'error': error}), 400
    db.update_team_entity(g.tenant_id, entity_id, **fields)
    return jsonify({'success': True, 'entity': db.get_team_entity(g.tenant_id, entity_id)})


@app.route('/api/team-entities/<entity_id>', methods=['DELETE'])
@require_permission('company_settings')
def api_delete_team_entity(entity_id):
    if not db.delete_team_entity(g.tenant_id, entity_id):
        return jsonify({'success': False, 'error': 'الجهة غير موجودة'}), 404
    return jsonify({'success': True})
