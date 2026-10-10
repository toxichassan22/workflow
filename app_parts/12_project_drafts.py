

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROJECT DRAFTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _draft_locked_response(status):
    """423 answer naming the lifecycle state that froze the draft."""
    label = db.PROPOSAL_LIFECYCLE_STATES.get(status, {}).get('label', status)
    return jsonify({
        'error': f'المشروع مقفل في حالة «{label}» ولا يقبل التعديل حاليًا',
        'error_code': 'DRAFT_LOCKED',
        'status': status,
    }), 423


def _presentation_draft_lock(draft_id, data, presentation_id=None):
    """The lifecycle status freezing this presentation's draft, or None.

    A presentation write is draft editing: while the draft sits in a locked
    lifecycle state only the running generation job may write, and only through
    its own ``operation='generation'`` save — a flag the client cannot forge
    because it must be backed by a live approved generation approval, and an
    approval bound to a presentation unlocks only that file.
    """
    if not draft_id:
        return None
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return None
    status = db.normalize_proposal_status(draft.get('status'))
    if status == 'generating':
        # 'generating' only counts while a live run backs it; a dead client
        # leaves the state behind, and the write that notices frees the file.
        db.recover_dead_generating_drafts(g.tenant_id, draft_id=draft_id)
        draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
        if not draft:
            return None
        status = db.normalize_proposal_status(draft.get('status'))
    if not db.proposal_status_is_locked(status):
        return None
    if status == 'generating' and (data or {}).get('operation') == 'generation':
        approval = _active_generation_approval(draft_id)
        bound = (approval or {}).get('presentation_id')
        if approval and not bound:
            return None
        if approval and bound and presentation_id and bound == presentation_id:
            return None
    return status


@app.route('/api/project-draft', methods=['POST'])
@require_auth
def api_save_project_draft():
    """Save or update the current user's project draft."""
    data = request.json or {}
    draft_data = data.get('draftData', {})
    if not isinstance(draft_data, dict):
        return jsonify({'error': 'draftData must be an object'}), 400
    # A request that carries no payload used to store "{}" over the draft and answer success, so a
    # single mangled or half-initialised save emptied the project with nothing to show why.
    if not draft_data:
        app.logger.warning(
            '[DRAFT SAVE] Refused a save with no draftData: tenant=%s actor=%s keys=%s',
            g.tenant_id, _project_draft_actor_id(), sorted(data.keys())[:20]
        )
        return jsonify({'error': 'لم يتم الحفظ: لم تصل بيانات المشروع إلى الخادم'}), 400
    # Absence or {} means preserve already-reviewed sections (legacy clients send {}).
    section_statuses = data.get('sectionStatuses')
    if section_statuses is not None and not isinstance(section_statuses, dict):
        return jsonify({'error': 'sectionStatuses must be an object'}), 400
    status = data.get('status', 'draft')
    if status not in {'draft', 'submitted'}:
        status = 'draft'
    # Read the stored version before writing over it, so the history can name every field that
    # changed instead of only counting a revision.
    previous_id = draft_data.get('draftId') or draft_data.get('draft_id')
    previous = db.get_project_draft_by_id(g.tenant_id, previous_id) if previous_id else None
    # ISS-014: a project-scoped actor must not write a draft outside its scope
    # by naming its id — the same not-found answer the GET path gives.
    if previous and not db.user_may_access_draft(g.user_id, previous):
        return jsonify({'error': 'Draft not found'}), 404
    previous_data = (previous or {}).get('draft_data') if isinstance(previous, dict) else {}
    previous_statuses = (previous or {}).get('section_statuses') if isinstance(previous, dict) else {}
    # Approvers read, decide and annotate — they never write project content.
    # The permission gate, not the assignment, decides who may save: the
    # approver envelope denies create_presentation, and the company admin's
    # tenant-direct session (user_id None) bypasses altogether.
    if g.user_id is not None and not _landloom_can('create_presentation'):
        return _landloom_forbidden('تحرير المشاريع يخص المحررين')
    # A section the actor cannot open cannot be written through the save either.
    # The company admin (tenant-direct session) bypasses: require_permission
    # already grants it every permission, and section toggles govern employees.
    if g.user_id and not g.is_admin:
        forbidden_sections, restored_keys = _enforce_draft_field_sections(
            draft_data, previous_data, section_statuses, previous_statuses)
        if restored_keys:
            app.logger.warning(
                '[DRAFT SAVE] Restored %d blocked-section value(s) for tenant=%s actor=%s: %s',
                len(restored_keys), g.tenant_id, _project_draft_actor_id(), restored_keys[:12]
            )
        if forbidden_sections:
            app.logger.warning(
                '[DRAFT SAVE] Refused blocked-section write: tenant=%s actor=%s sections=%s',
                g.tenant_id, _project_draft_actor_id(), forbidden_sections
            )
            return jsonify({
                'error': 'لا تملك صلاحية حفظ بيانات قسم: ' + '، '.join(forbidden_sections),
                'error_code': 'SECTION_FORBIDDEN',
                'sections': forbidden_sections,
            }), 403
    # While the draft runs its generation job only the job's own checkpoint saves
    # may write; every other locked state refuses the save outright.
    prev_norm = db.normalize_proposal_status((previous or {}).get('status')) if previous else 'draft'
    save_draft_id = draft_data.get('draftId') or draft_data.get('draft_id') \
        or (previous or {}).get('id')
    # ISS-025: the client flag only claims the run exists — a live approved
    # approval is what proves it, so the flag alone cannot unlock the state.
    allow_generating = bool(data.get('slideCheckpoint')) and prev_norm == 'generating' \
        and _active_generation_approval(save_draft_id) is not None
    # ISS-023: statuses travel through the save only as mirrors, demotions, or
    # approvals that would also pass the dedicated route's gates.
    section_statuses = _sanitize_save_section_statuses(
        g.tenant_id, previous, section_statuses, previous_statuses)
    draft_data = _sanitize_save_workflow_claims(
        g.tenant_id, save_draft_id, draft_data, previous_data)
    # ISS-030: a save that names the revision it was made against cannot
    # silently overwrite a draft that moved meanwhile — the conflict surfaces
    # instead of the later save rewinding the earlier one's edits.
    expected_revision = data.get('expectedRevision')
    if expected_revision is not None:
        try:
            expected_revision = int(expected_revision)
            if expected_revision < 0:
                raise ValueError('negative')
        except (TypeError, ValueError):
            return jsonify({'error': 'expectedRevision must be a non-negative integer'}), 400
    try:
        draft_id = db.save_project_draft(
            g.tenant_id, _project_draft_actor_id(), draft_data, section_statuses, status,
            draft_id=draft_data.get('draftId') or draft_data.get('draft_id'),
            allow_generating=allow_generating,
            expected_revision=expected_revision,
            existing_row=previous,
        )
    except db.DraftRevisionConflict as conflict:
        return jsonify({
            'error': 'المسودة تغيّرت في نسخة أخرى منذ آخر قراءة — أعد تحميلها قبل الحفظ',
            'error_code': 'DRAFT_REVISION_CONFLICT',
            'expectedRevision': conflict.expected_revision,
            'currentRevision': conflict.current_revision,
        }), 409
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    except db.DraftOverwriteRefused as refused:
        app.logger.warning(
            '[DRAFT SAVE] Refused to empty draft %s: tenant=%s actor=%s stored=%d fields received=%s',
            refused.draft_id, g.tenant_id, _project_draft_actor_id(),
            len(refused.stored_keys), refused.incoming_keys[:20]
        )
        return jsonify({
            'error': 'لم يتم الحفظ: البيانات المرسلة فارغة والمسودة المحفوظة تحتوي بيانات المشروع',
            'error_code': 'DRAFT_EMPTY_OVERWRITE'
        }), 409

    details = change_tracking.describe_draft_changes(
        previous_data, draft_data, id_names=_draft_change_id_names())
    if isinstance(section_statuses, dict) and section_statuses:
        for status_line in change_tracking.describe_section_status_changes(
                previous_statuses, section_statuses):
            details.append({'group': 'حالة الأقسام', 'text': status_line, 'kind': 'info'})
    if not previous:
        _record_change('draft', draft_id, 'إنشاء ملف مشروع',
                       details, source='manual', summary='تم إنشاء ملف المشروع')
    else:
        # One entry per touched section: each names its section, its author and
        # its timestamp instead of one save dumping every accumulated
        # difference into a single row.
        grouped_details = {}
        for item in details:
            group_name = item.get('group') if isinstance(item, dict) else ''
            grouped_details.setdefault(str(group_name or ''), []).append(item)
        for group_name, group_items in grouped_details.items():
            if group_name == 'حالة الأقسام':
                entry_action = 'تحديث حالة الأقسام'
            elif group_name:
                entry_action = 'تعديل «%s»' % group_name
            else:
                entry_action = 'حفظ بيانات المشروع'
            _record_change('draft', draft_id, entry_action, group_items, source='manual')
    # t16: an edit that drifts an approved section from its snapshot voids the
    # approval — checkpoint saves of a running job never reach this.
    if not allow_generating:
        try:
            effective_statuses = (section_statuses if isinstance(section_statuses, dict) and section_statuses
                                  else previous_statuses)
            _void_stale_section_approvals(
                g.tenant_id, draft_id, draft_data, statuses=effective_statuses)
        except Exception:
            pass
    saved_revision = None
    saved_row = db.get_db().execute(
        'SELECT revision FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (draft_id, g.tenant_id)).fetchone()
    if saved_row:
        saved_revision = int(saved_row['revision'] or 0)
    return jsonify({'success': True, 'draftId': draft_id, 'revision': saved_revision})


@app.route('/api/project-drafts', methods=['GET'])
@require_auth
def api_get_all_project_drafts():
    """Get lightweight saved-project metadata for the tenant."""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit and offset must be integers'}), 400
    drafts = db.get_all_project_draft_summaries(
        g.tenant_id, limit=limit, offset=offset,
        search=(request.args.get('search') or '').strip(),
        status=(request.args.get('status') or '').strip(),
        date_from=(request.args.get('from') or '').strip(),
        date_to=(request.args.get('to') or '').strip(),
        accessible_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id),
    )
    return jsonify({'success': True, 'drafts': drafts, 'limit': max(1, min(limit, 200)), 'offset': max(0, offset)})


@app.route('/api/project-draft/<draft_id>', methods=['GET'])
@require_auth
def api_get_project_draft_by_id(draft_id):
    """Get a specific project draft by ID."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft or not db.user_may_access_draft(g.user_id, draft):
        return jsonify({'error': 'Draft not found'}), 404
    draft['draft_data'] = _merge_persisted_map_assets(
        draft.get('draft_data') or {}, g.tenant_id, draft_id=draft_id
    )
    return jsonify({'success': True, 'draft': _draft_response_filtered(draft)})


@app.route('/api/project-drafts/recovery', methods=['GET'])
@require_auth
def api_project_draft_recovery():
    """Report which drafts lost their fields and what can be read back into them.

    A save with no readable payload used to overwrite a draft with "{}" and answer success, so
    drafts were emptied silently. Every generated presentation kept a full snapshot of the project
    data of its moment, which is what makes those drafts recoverable.

    Accepts an optional ?draftIds=a,b filter so a list screen showing one page
    does not pay for hydrating every draft payload and parsing every
    presentation payload of the tenant. Without the filter the full report is
    returned, as before.
    """
    _wanted = [part.strip() for part in (request.args.get('draftIds') or request.args.get('draft_ids') or '').split(',') if part.strip()][:200]
    _wanted_set = set(_wanted) or None
    accessible = db.user_accessible_draft_ids(g.user_id, g.tenant_id)
    if _wanted_set is not None and accessible is not None:
        _wanted_set &= accessible
    snapshots = [] if _wanted_set == set() else db.find_draft_snapshots(g.tenant_id, draft_ids=_wanted_set)
    if accessible is not None:
        snapshots = [s for s in snapshots if s.get('draft_id') in accessible]
    by_draft = {}
    for snapshot in snapshots:
        key = snapshot['draft_id']
        if key and (_wanted_set is None or key in _wanted_set) and (key not in by_draft or snapshot['field_count'] > by_draft[key]['field_count']):
            by_draft[key] = snapshot
    if _wanted_set is not None:
        summaries = [s for s in db.get_all_project_draft_summaries(g.tenant_id, limit=200, accessible_ids=accessible) if s['id'] in _wanted_set]
        # Preserve the requested order for a stable progressive patch on the client.
        summaries.sort(key=lambda s: _wanted.index(s['id']) if s['id'] in _wanted else 0)
        field_counts = db.get_draft_field_counts(g.tenant_id, [s['id'] for s in summaries])
    else:
        summaries = db.get_all_project_draft_summaries(g.tenant_id, limit=200, accessible_ids=accessible)
        field_counts = {}
    report = []
    for draft in summaries:
        if draft['id'] in field_counts:
            field_count = field_counts[draft['id']]
        else:
            stored = db.get_project_draft_by_id(g.tenant_id, draft['id'])
            field_count = len(db._draft_content_keys((stored or {}).get('draft_data') or {}))
        snapshot = by_draft.get(draft['id'])
        report.append({
            'draftId': draft['id'],
            'title': draft['title'],
            'updatedAt': draft.get('updated_at'),
            'dataBytes': draft.get('data_bytes') or 0,
            'revision': draft.get('revision') or 0,
            'fieldCount': field_count,
            'isEmpty': field_count == 0,
            'snapshot': {
                'presentationId': snapshot['presentation_id'],
                'title': snapshot['title'],
                'createdAt': snapshot['created_at'],
                'slideCount': snapshot['slide_count'],
                'fieldCount': snapshot['field_count'],
                'recoverable': snapshot['field_count'] > field_count,
            } if snapshot else None,
        })
    orphans = [
        {
            'presentationId': snapshot['presentation_id'],
            'title': snapshot['title'],
            'createdAt': snapshot['created_at'],
            'fieldCount': snapshot['field_count'],
        }
        for snapshot in snapshots
        if snapshot['field_count'] > 0 and snapshot['draft_id'] not in {item['draftId'] for item in report}
    ]
    return jsonify({'success': True, 'drafts': report, 'orphanSnapshots': orphans})


@app.route('/api/project-draft/<draft_id>/restore', methods=['POST'])
@require_auth
def api_restore_project_draft(draft_id):
    """Refill a draft's missing fields from a presentation snapshot. Never overwrites."""
    data = request.json or {}
    presentation_id = data.get('presentationId')
    if not isinstance(presentation_id, str) or not presentation_id:
        return jsonify({'error': 'presentationId is required'}), 400
    presentation = db.get_presentation(presentation_id, tenant_id=g.tenant_id)
    if not presentation or not _presentation_in_scope(presentation):
        return jsonify({'error': 'Presentation not found'}), 404
    # ISS-014: the restore target must be a draft the caller may touch —
    # restore_draft_from_snapshot is tenant-scoped only.
    target = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not target or not db.user_may_access_draft(g.user_id, target):
        return jsonify({'error': 'Draft not found'}), 404
    try:
        snapshot = json.loads(presentation.get('project_data') or '{}')
    except (TypeError, ValueError):
        snapshot = {}
    if not isinstance(snapshot, dict) or not snapshot:
        return jsonify({'error': 'لا توجد بيانات مشروع في هذا العرض'}), 400
    restored = db.restore_draft_from_snapshot(g.tenant_id, draft_id, snapshot)
    if restored is None:
        return jsonify({'error': 'Draft not found'}), 404
    _record_change('draft', draft_id, 'استرجاع بيانات المشروع',
                   [f'استُعيد الحقل «{field}» من العرض «{presentation.get("title") or "بدون عنوان"}»'
                    for field in restored])
    return jsonify({'success': True, 'restoredFields': restored, 'restoredCount': len(restored)})


def _draft_has_workflow_history(draft_id):
    """True when approval or output records exist for the draft.

    Delete stays a cleanup for never-processed drafts; anything the gates
    touched must be archived, not erased (t18). Fails closed: a lookup error
    counts as history.
    """
    conn = db.get_db()
    try:
        if conn.execute(
                'SELECT 1 FROM section_versions WHERE tenant_id = ? AND draft_id = ? LIMIT 1',
                (g.tenant_id, draft_id)).fetchone():
            return True
        if conn.execute(
                'SELECT 1 FROM generation_approvals WHERE tenant_id = ? AND draft_id = ? LIMIT 1',
                (g.tenant_id, draft_id)).fetchone():
            return True
        pres_ids = [row['id'] for row in conn.execute(
            'SELECT id FROM presentations WHERE tenant_id = ? AND draft_id = ?',
            (g.tenant_id, draft_id)).fetchall()]
        for pres_id in pres_ids:
            if conn.execute(
                    'SELECT 1 FROM final_file_approvals WHERE tenant_id = ? AND presentation_id = ? LIMIT 1',
                    (g.tenant_id, pres_id)).fetchone():
                return True
            if conn.execute(
                    'SELECT 1 FROM exports WHERE tenant_id = ? AND presentation_id = ? LIMIT 1',
                    (g.tenant_id, pres_id)).fetchone():
                return True
        return False
    except Exception:
        return True


@app.route('/api/project-draft/<draft_id>', methods=['DELETE'])
@require_auth
def api_delete_project_draft_by_id(draft_id):
    """Delete is cleanup for never-processed drafts only — admin-gated, and
    refused entirely once the draft carries workflow history (t18)."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if not draft:
        return jsonify({'error': 'Draft not found'}), 404
    if not _landloom_actor_is_admin():
        return jsonify({'error': 'الحذف النهائي يتطلب صلاحية مدير الشركة — أو استخدم الأرشفة',
                        'error_code': 'admin_required'}), 403
    if _draft_has_workflow_history(draft_id):
        return jsonify({'error': 'لهذا المشروع مسار اعتماد محفوظ — استخدم الأرشفة بدل الحذف',
                        'error_code': 'archive_required'}), 409
    _record_change('draft', draft_id, 'حذف المشروع',
                   [f'حُذف المشروع «{draft.get("title") or "بدون عنوان"}»'])
    db.delete_project_draft_by_id(g.tenant_id, draft_id)
    return jsonify({'success': True})


def _location_workflow_complete(draft):
    """Location section approval needs the AI site analysis approved plus all
    four generated map rasters approved — each map approval certifies the baked
    raster the client framed, so a missing flag means the client never signed
    that map off."""
    project = (draft or {}).get('draft_data') if isinstance(draft, dict) else {}
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (TypeError, ValueError):
            project = {}
    if not isinstance(project, dict):
        return False
    if project.get('site_analysis_approved') not in (True, 'true', 1) \
            or not str(project.get('site_analysis') or '').strip():
        return False
    draft_id = (draft or {}).get('id')
    tenant_id = (draft or {}).get('tenant_id') or getattr(g, 'tenant_id', None)
    if not tenant_id:
        return False
    if not all(
        _map_image_artifact(tenant_id, map_type, draft_id=draft_id)
        for map_type in _LOCATION_MAP_TYPES):
        return False
    creative = project.get('tenantCreativeImages') or {}
    approvals = creative.get('map_approvals') if isinstance(creative, dict) else {}
    if not isinstance(approvals, dict):
        return False
    return all(
        approvals.get(map_type) in (True, 'true', 1)
        for map_type in _LOCATION_MAP_TYPES)


_LOCATION_MAP_TYPES = ('overview', 'access', 'catchment', 'landmarks')


def _map_image_artifact(tenant_id, map_type, draft_id=None, presentation_id=None):
    """The generated-map artifact a map approval must be backed by.

    The ledger keys generated maps to ``draft_<id>`` or a presentation id; an
    approval claim that names neither can never be honored.
    """
    scope = {presentation_id} if presentation_id else set()
    if draft_id:
        scope.add(f'draft_{draft_id}')
        try:
            scope.update(pres['id'] for pres in db.get_presentations(tenant_id, draft_id=draft_id))
        except Exception:
            pass
    scope.discard(None)
    if not scope:
        return False
    prefixes = (map_type, f'{map_type}_')
    try:
        return any(
            row.get('presentation_id') in scope
            and str(row.get('image_type') or '').startswith(prefixes)
            for row in db.get_map_images(tenant_id))
    except Exception:
        return False


def _sanitize_save_workflow_claims(tenant_id, draft_id, draft_data, stored_data):
    """ISS-025: workflow-lock claims must be backed by server artifacts.

    The only generated-content approval in the location section is the AI site
    analysis text, and an approval claim may only be set when that text exists.
    A bare claim written into draftData does not survive — the stored value
    stands.
    """
    if not isinstance(draft_data, dict):
        return draft_data
    stored = stored_data if isinstance(stored_data, dict) else {}
    truthy = lambda v: v in (True, 'true', 1)
    if truthy(draft_data.get('site_analysis_approved')) \
            and not truthy(stored.get('site_analysis_approved')) \
            and not str(draft_data.get('site_analysis') or '').strip():
        draft_data['site_analysis_approved'] = \
            stored.get('site_analysis_approved') or False
        app.logger.warning(
            '[DRAFT SAVE] Refused unbacked site analysis approval: tenant=%s draft=%s',
            tenant_id, draft_id)
    _sanitize_map_approval_claims(tenant_id, draft_id, draft_data, stored)
    _sanitize_financial_parking_claims(draft_data, stored)
    return draft_data


def _sanitize_map_approval_claims(tenant_id, draft_id, draft_data, stored_data):
    """A map_approvals=true claim only stands on a real raster artifact whose
    stored frame still matches — anything else reverts to the stored flag."""
    creative = draft_data.get('tenantCreativeImages')
    if not isinstance(creative, dict):
        return
    claims = creative.get('map_approvals')
    if not isinstance(claims, dict):
        return
    stored_creative = stored_data.get('tenantCreativeImages') if isinstance(stored_data, dict) else {}
    stored_claims = stored_creative.get('map_approvals') \
        if isinstance(stored_creative, dict) and isinstance(stored_creative.get('map_approvals'), dict) \
        else {}
    truthy = lambda v: v in (True, 'true', 1)
    for map_type, flag in list(claims.items()):
        if not truthy(flag) or truthy(stored_claims.get(map_type)):
            continue
        backed = _map_image_artifact(tenant_id, map_type, draft_id=draft_id) \
            and _frame_matches_baked(creative, map_type)
        if not backed:
            claims[map_type] = stored_claims.get(map_type) or False
            app.logger.warning(
                '[DRAFT SAVE] Refused unbacked map approval: tenant=%s draft=%s map=%s',
                tenant_id, draft_id, map_type)


def _active_generation_approval(draft_id):
    """The live approved generation approval for this draft, if one is running.

    Settlement moves the row to consumed/rejected, so its presence proves a
    real run — a client-sent ``slideCheckpoint`` or ``operation='generation'``
    flag is only a claim until this record backs it.
    """
    if not draft_id:
        return None
    try:
        row = db.get_db().execute(
            "SELECT * FROM generation_approvals WHERE tenant_id = ? AND draft_id = ? "
            "AND status = 'approved' ORDER BY decided_at DESC LIMIT 1",
            (g.tenant_id, draft_id)).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


@app.route('/api/project-draft/section-versions/<version_id>/diff', methods=['GET'])
@require_auth
def api_diff_section_version(version_id):
    """Compare one sent version against its predecessor for the approver's review."""
    version = db.get_section_version(g.tenant_id, version_id, include_snapshot=False)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    _draft, error = _versioned_draft_for_read(version.get('draft_id'))
    if error:
        return jsonify({'error': 'Section version not found'}), 404
    if _section_key_forbidden(version.get('section_key')):
        return jsonify({'error': 'Section version not found'}), 404
    base_id = (request.args.get('baseVersionId') or '').strip() or None
    diff = db.diff_section_versions(g.tenant_id, version_id, base_version_id=base_id)
    if diff.get('error') == 'version_not_found':
        return jsonify({'error': 'Section version not found'}), 404
    if diff.get('error') == 'base_version_not_found':
        return jsonify({'error': 'Base version not found for this section'}), 404
    if diff.get('error'):
        return jsonify({'error': 'Unable to compare the section versions'}), 400
    return jsonify({'success': True, 'diff': diff})


@app.route('/api/project-draft/section-version/restore', methods=['POST'])
@require_auth
def api_restore_section_version():
    """Bring back an older version as a brand-new pending version, keeping history."""
    data = request.json or {}
    if not data.get('versionId'):
        return jsonify({'error': 'A valid versionId is required'}), 400
    version = db.get_section_version(g.tenant_id, data['versionId'], include_snapshot=True)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    draft, error = _versioned_draft_or_404(version.get('draft_id'))
    if error:
        return jsonify(error), 404
    # ISS-015: restoring writes hidden-section content into the draft — the
    # caller must be able to see that section.
    if _section_key_forbidden(version.get('section_key')):
        return jsonify({'error': 'Section version not found'}), 404
    live = dict(draft.get('draft_data') or {})
    section_map = _draft_field_section_map(g.tenant_id)
    for key in _section_snapshot_slice(live, version['section_key'], section_map):
        live.pop(key, None)
    snapshot = dict(version.get('snapshot') or {})
    snapshot.pop('map_approvals', None)
    live.update(snapshot)
    try:
        db.save_project_draft(
            g.tenant_id, _project_draft_actor_id(), live,
            None, draft.get('status') or 'draft', draft_id=draft['id'],
        )
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    except db.DraftOverwriteRefused:
        return jsonify({'error': 'Restoring this version would empty the draft'}), 400
    except Exception:
        return jsonify({'error': 'Unable to restore the section version'}), 400
    restored = db.create_section_version(
        g.tenant_id, draft['id'], version['section_key'], snapshot,
        _project_draft_actor_id(), _project_draft_actor_name(),
        allow_supersede=True,
    )
    if restored.get('error') == 'draft_locked':
        return _draft_locked_response(restored.get('status'))
    if restored.get('error') == 'version_pending_exists':
        return jsonify({'error': 'يوجد إصدار قيد المراجعة لهذا القسم بالفعل',
                        'error_code': 'SECTION_VERSION_PENDING_EXISTS'}), 409
    if restored.get('error'):
        return jsonify({'error': 'Unable to store the restored section snapshot'}), 400
    _record_change('draft', draft['id'], 'الرجوع لنسخة قسم سابقة',
                   [f'القسم {_section_version_label(version["section_key"])}: '
                    f'لقطة رقم {version["version_number"]} عادت كلقطة رقم {restored["version_number"]} بانتظار القرار'])
    _record_audit_event(
        action='section_version_restored',
        entity_type='section_version',
        entity_id=restored['id'],
        entity_name=f'القسم {_section_version_label(version["section_key"])} (إصدار {restored["version_number"]})',
        old_value={'restored_from_version_id': data['versionId'], 'restored_from_version_number': version['version_number']},
        new_value=snapshot,
        metadata={'draft_id': draft['id'], 'section_key': version['section_key']},
    )
    # The restore already moved the draft revision — hand it back so an open
    # workspace does not conflict against a counter it never saw.
    restored_draft = db.get_project_draft_by_id(g.tenant_id, draft['id'])
    return jsonify({'success': True, 'version': restored,
                    'revision': int((restored_draft or {}).get('revision') or 0)})


@app.route('/api/project-draft/request-approval', methods=['POST'])
@require_auth
def api_request_project_draft_approval():
    """Request one overall approval after all tracked sections are approved."""
    data = request.json or {}
    draft_id = _resolve_draft_id(data.get('draftId'))
    current = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
    # ISS-014: an explicit draftId outside the caller's scope answers not-found.
    if current and not db.user_may_access_draft(g.user_id, current):
        return jsonify({'error': 'No project draft found'}), 404
    if current and current.get('user_id') == _project_draft_actor_id():
        # Rule 19.2: an approval names one version, so a later edit voids that
        # section's readiness until it is sent and approved again. Sections
        # without any version keep the legacy toggle behaviour.
        overview = db.section_versions_overview(g.tenant_id, current['id'])
        if overview:
            section_map = _draft_field_section_map(g.tenant_id)
            stored_data = current.get('draft_data') or {}
            stored_statuses = current.get('section_statuses') or {}
            for section_key, meta in overview.items():
                if stored_statuses.get(section_key) != 'approved':
                    continue
                if meta.get('status') != 'approved':
                    return jsonify({
                        'error': f'Section {section_key} has a newer version awaiting a decision',
                        'error_code': 'SECTION_VERSION_NOT_APPROVED',
                        'section': section_key, 'version': meta.get('version_number'),
                    }), 400
                live_hash = db.section_snapshot_hash(
                    _section_snapshot_slice(stored_data, section_key, section_map))
                if live_hash != meta.get('snapshot_hash'):
                    return jsonify({
                        'error': f'Section {section_key} changed after its approval',
                        'error_code': 'SECTION_VERSION_STALE',
                        'section': section_key, 'version': meta.get('version_number'),
                    }), 400
    draft = db.request_project_draft_approval(
        g.tenant_id, _project_draft_actor_id(), _project_draft_actor_id(), _project_draft_actor_name(),
        draft_id=data.get('draftId')
    )
    if draft.get('error') == 'draft_not_found':
        return jsonify({'error': 'No project draft found'}), 404
    if draft.get('error') == 'sections_not_approved':
        return jsonify({
            'error': 'All project sections must be approved before requesting approval',
            'error_code': 'SECTIONS_NOT_APPROVED',
            'sectionStatuses': draft.get('section_statuses', {})
        }), 400
    if draft.get('error') == 'section_version_expired':
        return jsonify({'error': 'انتهت صلاحية اعتماد بعض الأقسام — أعد إرسالها للاعتماد',
                        'error_code': 'SECTION_VERSION_EXPIRED',
                        'sections': draft.get('sections', [])}), 409
    if draft.get('error') == 'draft_locked':
        return _draft_locked_response(draft.get('status'))
    if draft.get('error') == 'invalid_transition':
        return jsonify({'error': 'This draft cannot be sent for approval from its current state',
                        'error_code': 'INVALID_TRANSITION',
                        'status': draft.get('current_status')}), 409
    if draft.get('error'):
        return jsonify({'error': 'Unable to request approval'}), 400
    try:
        if draft.get('status') == 'section_approval_pending':
            resolved_id = draft.get('id') or data.get('draftId')
            assigned = db.assigned_approver(g.tenant_id, resolved_id)
            db.create_approval_task(
                g.tenant_id, 'section_approval',
                f'اعتماد مشروع «{draft.get("title") or "مشروع"}»',
                entity_type='project_draft', entity_id=resolved_id, due_hours=48,
                assignee_id=(assigned or {}).get('user_id'),
                assignee_name=(assigned or {}).get('user_name'),
                draft_id=resolved_id)
            recipients = ([{'id': assigned['user_id']}] if assigned
                          else db.get_users_with_permission(g.tenant_id, 'approvals'))
            for approver in recipients:
                db.create_notification(
                    g.tenant_id, 'مشروع بانتظار الاعتماد',
                    f'«{draft.get("title") or "مشروع"}» أُرسل للاعتماد',
                    category='section_approval', user_id=approver['id'],
                    entity_type='project_draft', entity_id=resolved_id,
                    mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_change('draft', draft.get('id') or data.get('draftId'), 'طلب تعميد المشروع',
                   ['أُرسل المشروع للمراجعة'])
    return jsonify({'success': True, 'draft': _draft_response_filtered(draft)})


@app.route('/api/project-draft/approval-status', methods=['GET'])
@require_auth
def api_project_draft_approval_status():
    """Return the current actor's overall draft-review state."""
    draft = db.get_project_draft(g.tenant_id, _project_draft_actor_id())
    return jsonify({'success': True, 'approval': _draft_response_filtered(draft)})


@app.route('/api/project-draft/pending-approvals', methods=['GET'])
@require_auth
def api_pending_project_draft_approvals():
    """List tenant-only draft approval requests for authorized reviewers —
    permission holders, or users holding an approver assignment."""
    if not _has_approvals_permission() and not _landloom_has_approver_assignment():
        return _landloom_forbidden()
    drafts = db.get_pending_project_drafts(
        g.tenant_id, accessible_draft_ids=db.user_accessible_draft_ids(g.user_id, g.tenant_id))
    return jsonify({'success': True, 'drafts': drafts})


@app.route('/api/project-draft/review', methods=['POST'])
@require_auth
def api_review_project_draft():
    """Approve or return a tenant-scoped project draft for correction."""
    data = request.json or {}
    draft_id = data.get('draftId')
    review_status = data.get('status')
    note = (data.get('note') or '').strip()[:3000]
    if not isinstance(draft_id, str) or not draft_id or review_status not in {'approved', 'rejected'}:
        return jsonify({'error': 'draftId and status (approved or rejected) are required'}), 400
    # The decision needs the approvals permission or the approver assignment
    # for this exact draft — a bare user can never review somebody's draft.
    if not _has_approvals_permission() \
            and not db.user_is_assigned_approver(g.tenant_id, g.user_id, draft_id):
        return _landloom_forbidden()
    # ISS-014: a scoped reviewer cannot decide a draft outside their scope.
    target = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if target and not db.user_may_access_draft(g.user_id, target):
        return jsonify({'error': 'Pending draft approval not found'}), 404
    reviewed = db.review_project_draft(
        g.tenant_id, draft_id, review_status, _project_draft_actor_id(), _project_draft_actor_name(), note
    )
    if reviewed.get('error') in {'draft_not_found', 'draft_not_pending', 'draft_not_reviewable'}:
        return jsonify({'error': 'Pending draft approval not found'}), 404
    if reviewed.get('error') == 'reason_required':
        return jsonify({'error': 'A reason is required when returning the draft for revision',
                        'error_code': 'REASON_REQUIRED'}), 400
    if reviewed.get('error') == 'sections_not_approved':
        return jsonify({'error': 'All project sections must be approved before this decision',
                        'error_code': 'SECTIONS_NOT_APPROVED',
                        'sectionStatuses': reviewed.get('section_statuses', {})}), 400
    if reviewed.get('error') == 'section_version_expired':
        return jsonify({'error': 'انتهت صلاحية اعتماد بعض الأقسام — أعد إرسالها للاعتماد',
                        'error_code': 'SECTION_VERSION_EXPIRED',
                        'sections': reviewed.get('sections', [])}), 409
    if reviewed.get('error') == 'draft_locked':
        return _draft_locked_response(reviewed.get('status'))
    if reviewed.get('error') == 'invalid_transition':
        return jsonify({'error': 'This draft cannot be reviewed from its current state',
                        'error_code': 'INVALID_TRANSITION',
                        'status': reviewed.get('current_status')}), 409
    if reviewed.get('error'):
        return jsonify({'error': 'Unable to review the draft'}), 400
    try:
        db.close_approval_tasks_for_entity(
            g.tenant_id, 'project_draft', draft_id,
            closed_by_name=_project_draft_actor_name())
        reviewed_draft = reviewed.get('draft') or {}
        requester = str(reviewed_draft.get('requested_by') or '')
        if not _recipient_is_actor(g.tenant_id, requester, _project_draft_actor_id(),
                                   _landloom_actor_is_admin()) \
                and not _recipient_is_tenant_admin(g.tenant_id, requester):
            message = 'اعتُمد مشروعك' if review_status == 'approved' else 'أُعيد مشروعك للتعديل'
            db.create_notification(
                g.tenant_id, message, note or None,
                category='section_approval',
                user_id=requester,
                entity_type='project_draft', entity_id=draft_id,
                mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    action = 'اعتماد المشروع' if review_status == 'approved' else 'إعادة المشروع للتعديل'
    _record_change('draft', draft_id, action, [note] if note else [action])
    return jsonify({'success': True, 'draft': _draft_response_filtered(reviewed)})


@app.route('/api/project-draft/lifecycle-states', methods=['GET'])
@require_auth
def api_get_proposal_lifecycle_states():
    """Return all 11 official proposal lifecycle states, phases, and allowed transitions."""
    states_list = [
        {
            'status': key,
            'label': meta['label'],
            'label_en': meta['label_en'],
            'phase': meta['phase'],
            'description': meta['description'],
            'is_locked': meta['is_locked'],
            'order': meta['order'],
        }
        for key, meta in sorted(db.PROPOSAL_LIFECYCLE_STATES.items(), key=lambda x: x[1]['order'])
    ]
    transitions = {k: sorted(list(v)) for k, v in db.PROPOSAL_ALLOWED_TRANSITIONS.items()}
    return jsonify({
        'success': True,
        'states': states_list,
        'statesMap': db.PROPOSAL_LIFECYCLE_STATES,
        'transitions': transitions,
    })


@app.route('/api/project-draft/<draft_id>/lifecycle', methods=['GET'])
@require_auth
def api_get_proposal_lifecycle(draft_id):
    """Return the current lifecycle state, metadata, and transition history for a proposal."""
    resolved_id = _resolve_draft_id(draft_id)
    draft = db.get_project_draft_by_id(g.tenant_id, resolved_id)
    if not draft or not db.user_may_access_draft(g.user_id, draft):
        return jsonify({'error': 'Project draft not found'}), 404
    info = db.get_proposal_lifecycle_info(g.tenant_id, resolved_id)
    if not info:
        return jsonify({'error': 'Project draft not found'}), 404
    return jsonify({'success': True, 'lifecycle': info})


@app.route('/api/project-draft/<draft_id>/transition-status', methods=['POST'])
@require_auth
def api_transition_proposal_status(draft_id):
    """Execute a validated state transition for a proposal in accordance with the 11-state lifecycle."""
    resolved_id = _resolve_draft_id(draft_id)
    draft = db.get_project_draft_by_id(g.tenant_id, resolved_id)
    if not draft or not db.user_may_access_draft(g.user_id, draft):
        return jsonify({'error': 'Project draft not found'}), 404

    data = request.json or {}
    target_status = data.get('targetStatus') or data.get('status')
    reason = (data.get('reason') or data.get('note') or '').strip()
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}

    if not target_status or target_status not in db.PROPOSAL_LIFECYCLE_STATES:
        return jsonify({
            'error': 'Valid targetStatus is required',
            'valid_statuses': list(db.PROPOSAL_LIFECYCLE_STATES.keys())
        }), 400

    # Permission check: regular employees can only modify their own draft unless they have approvals permission
    actor_id = _project_draft_actor_id()
    can_review = _has_approvals_permission()
    if draft.get('user_id') != actor_id and not can_review:
        return jsonify({'error': 'Not authorized to transition this project draft'}), 403

    current_status = db.normalize_proposal_status(draft.get('status') or 'draft')
    norm_target = db.normalize_proposal_status(target_status)

    # Permission check for administrative transitions:
    # 1. Gate outcomes (sections approved, returned for revision, final approval)
    #    belong to approvers — the owner cannot pass their own draft through.
    if norm_target in {'approved', 'sections_approved', 'rejected_for_revision'} and not can_review:
        return jsonify({'error': 'Approvals permission required for this decision'}), 403

    # 2. Reopening an approved proposal (post-approval edit, Section 8.4) requires approvals permission + reason
    if current_status == 'approved' and norm_target != 'archived' and not can_review:
        return jsonify({'error': 'Approvals permission required to modify an approved proposal'}), 403

    res = db.transition_project_draft_status(
        tenant_id=g.tenant_id,
        draft_id=resolved_id,
        target_status=norm_target,
        actor_id=actor_id,
        actor_name=_project_draft_actor_name(),
        actor_role=getattr(g, 'user_role', 'employee'),
        reason=reason,
        metadata=metadata,
        manual=True,
    )

    if res.get('error') == 'manual_transition_not_allowed':
        return jsonify({
            'error': 'This state is reached by its approval workflow, not by a manual transition',
            'error_code': 'SYSTEM_TRANSITION_ONLY',
            'current_status': res.get('current_status'),
            'target_status': res.get('target_status'),
        }), 403

    if res.get('error') == 'invalid_transition':
        return jsonify({
            'error': f'Invalid transition from {res.get("current_status")} to {res.get("target_status")}',
            'error_code': 'INVALID_STATUS_TRANSITION',
            'current_status': res.get('current_status'),
            'target_status': res.get('target_status'),
            'allowed_transitions': res.get('allowed_transitions', []),
        }), 400

    if res.get('error') == 'reason_required':
        return jsonify({
            'error': res.get('message') or 'Reason is required for this transition',
            'error_code': 'REASON_REQUIRED',
        }), 400

    if not res.get('success'):
        return jsonify({'error': 'Failed to transition proposal status'}), 400

    # Record human-readable change log entry
    state_label = res.get('state_info', {}).get('label', norm_target)
    prev_label = db.PROPOSAL_LIFECYCLE_STATES.get(res.get('previous_status'), {}).get('label', res.get('previous_status'))
    details = [f'تغيرت حالة العرض من «{prev_label}» إلى «{state_label}»']
    if reason:
        details.append(f'السبب: {reason}')
    _record_change('draft', resolved_id, f'تغيير حالة العرض: {state_label}', details)

    return jsonify({'success': True, 'lifecycle': res})
