

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROJECT DRAFTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _project_draft_actor_id():
    """Return a non-NULL, tenant-scoped owner for the unified project draft."""
    return g.user_id or f'tenant-admin:{g.tenant_id}'


def _project_draft_actor_name():
    return g.user_name or 'Company administrator'


def _resolve_draft_id(explicit=None):
    """The draft a request acts on: the id it names, else this actor's current draft."""
    if explicit:
        return explicit
    draft = db.get_project_draft(g.tenant_id, _project_draft_actor_id())
    return (draft or {}).get('id')


def _presentation_in_scope(pres):
    """ISS-014: True when this presentation stays inside the caller's project scope.

    A presentation with no linked draft stays visible to scoped users, matching
    the list route; one linked to a draft outside their scope answers not-found
    so its existence is not disclosed.
    """
    if not pres:
        return False
    draft_id = pres.get('draft_id')
    if not draft_id:
        return True
    accessible = db.user_accessible_draft_ids(g.user_id, g.tenant_id)
    return accessible is None or str(draft_id) in accessible


def _hidden_field_sections():
    """ISS-015: section keys the current caller may not see at all.

    Tenant-direct (company admin) and super-admin sessions see everything; an
    employee's ``user_field_sections`` rows decide. Fails open for a caller with
    no user id only because that identity already bypasses section toggles.
    """
    try:
        if not getattr(g, 'user_id', None) or getattr(g, 'is_admin', False):
            return set()
        allowed = db.get_user_field_sections(g.user_id, g.tenant_id) or {}
    except Exception:
        return set()
    return {key for key, granted in allowed.items() if not granted} - {'general'}


def _draft_data_for_response(data):
    """ISS-015: copy of a draft/project payload without hidden-section keys.

    Mirrors ``_enforce_draft_field_sections``: the UI never renders a denied
    section, so its stored values must not reach the client through any
    response — not the draft GET, a presentation's projectData, or a version
    snapshot.
    """
    denied = _hidden_field_sections()
    if not denied or not isinstance(data, dict):
        return data
    section_map = _draft_field_section_map(g.tenant_id)
    return {key: value for key, value in data.items()
            if _draft_section_of_key(section_map, key) not in denied}


def _draft_response_filtered(draft):
    """ISS-015: draft row minus hidden-section content and section statuses."""
    if not isinstance(draft, dict):
        return draft
    draft = dict(draft)
    data = draft.get('draft_data')
    if isinstance(data, dict):
        # Older saves embedded a second copy of the whole deck under
        # pageDrafts.slides.data; nothing reads it, so returning it doubled the
        # payload of every draft open. The stored row keeps it; the response
        # drops it.
        page_drafts = data.get('pageDrafts')
        if isinstance(page_drafts, dict) and isinstance(page_drafts.get('slides'), dict) \
                and 'data' in page_drafts['slides']:
            data = dict(data)
            page_drafts = dict(page_drafts)
            page_drafts['slides'] = {
                key: value for key, value in page_drafts['slides'].items() if key != 'data'}
            data['pageDrafts'] = page_drafts
            draft['draft_data'] = data
    denied = _hidden_field_sections()
    if denied:
        if isinstance(draft.get('draft_data'), dict):
            draft['draft_data'] = _draft_data_for_response(draft['draft_data'])
        if isinstance(draft.get('section_statuses'), dict):
            draft['section_statuses'] = {
                key: value for key, value in draft['section_statuses'].items()
                if key not in denied}
    return draft


def _section_key_forbidden(section_key):
    """ISS-015: True when this section is hidden from the current caller."""
    return bool(section_key) and section_key in _hidden_field_sections()


@app.route('/api/project-draft', methods=['GET'])
@require_auth
def api_get_project_draft():
    """Get the current user's project draft."""
    draft = db.get_project_draft(g.tenant_id, _project_draft_actor_id())
    if not draft:
        return jsonify({'success': True, 'draft': None})
    draft['draft_data'] = _merge_persisted_map_assets(
        draft.get('draft_data') or {}, g.tenant_id, draft_id=draft.get('id')
    )
    return jsonify({'success': True, 'draft': _draft_response_filtered(draft)})


# Draft keys that are not tenant_input_fields rows but still belong to a governed
# field section. ISS-015 also mapped the widget-section payloads: timeline,
# financial study, team, market study, visual concept and executive content are
# governable sections now, so a denied widget section refuses writes and never
# reaches the client.
DRAFT_FIELD_SECTION_BLOBS = {
    'land_documents_analysis': 'land_croquis',
    'survey_coordinates': 'land_croquis',
    'directions_table': 'land_croquis',
    'site_analysis': 'location',
    'timeline_table_data': 'section-timeline',
    'timeline_start_date': 'section-timeline',
    'timeline_start_year': 'section-timeline',
    'timeline_years': 'section-timeline',
    'financial_study_model': 'section-financial-calc',
    'team_selection': 'section-team',
    'market_study_data': 'section-market-study',
    'visual_concept': 'section-visual-concept',
    'executive_content': 'section-executive-content',
}

# Widget-section blobs that belong to a section snapshot even though no input
# field carries them. Binary image bytes are deliberately excluded: rendered
# map and creative images stay referenced by file, while the snapshot keeps the
# structured inputs plus the small approval flags that prove what was reviewed.
SECTION_SNAPSHOT_BLOBS = {
    'section-timeline': ['timeline_table_data'],
    'section-financial-calc': ['financial_study_model'],
    'section-team': ['team_selection'],
    'section-market-study': ['market_study_data'],
    'section-visual-concept': ['visual_concept'],
    'section-executive-content': ['executive_content'],
}
SECTION_SNAPSHOT_LOCATION_EXTRAS = [
    'location_analysis_approved',
    'location_data_fetched_at',
    'location_polygon_source',
]
SECTION_SNAPSHOT_EXCLUDED_KEYS = {
    'tenantCreativeImages', 'tenantSlidesData', 'pageDrafts', 'designerChat', 'map_styles',
}

SECTION_VERSION_AR_LABELS = {
    'basic': 'المعلومات الأساسية',
    'location': 'الموقع والخرائط',
    'land_croquis': 'الأرض والكروكي',
    'contact': 'بيانات التواصل',
    'section-timeline': 'الجدول الزمني',
    'section-financial-calc': 'الدراسة المالية والمؤشرات',
    'section-team': 'فريق العمل',
    'section-market-study': 'دراسة السوق',
    'section-visual-concept': 'التصور البصري',
    'section-executive-content': 'المحتوى التنفيذي',
}


def _section_snapshot_slice(draft_data, section_key, section_map=None):
    """Copy the inputs one section owns at this moment for an approval snapshot."""
    data = draft_data if isinstance(draft_data, dict) else {}
    section_map = section_map or {}
    selected = {}
    for key, value in data.items():
        if key in SECTION_SNAPSHOT_EXCLUDED_KEYS:
            continue
        if _draft_section_of_key(section_map, key) == section_key:
            selected[key] = change_tracking.strip_url_fetch_params(value)
    for key in SECTION_SNAPSHOT_BLOBS.get(section_key, []):
        if key in data:
            selected[key] = change_tracking.strip_url_fetch_params(data[key])
    if section_key == 'location':
        for key in SECTION_SNAPSHOT_LOCATION_EXTRAS:
            if key in data:
                selected[key] = change_tracking.strip_url_fetch_params(data[key])
        creative = data.get('tenantCreativeImages')
        if isinstance(creative, dict) and isinstance(creative.get('map_approvals'), dict):
            selected['map_approvals'] = change_tracking.strip_url_fetch_params(
                dict(creative.get('map_approvals')))
    return selected


def _section_version_label(section_key):
    return SECTION_VERSION_AR_LABELS.get(section_key, section_key)


def _versioned_draft_or_404(draft_id):
    """The draft version flows act on — the owner's, or one the caller is
    assigned to edit — or a not-found error dict."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
    if not draft:
        return None, {'error': 'No project draft found'}
    if draft.get('user_id') != _project_draft_actor_id() \
            and not db.user_is_assigned_editor(g.tenant_id, g.user_id, draft.get('id')):
        return None, {'error': 'No project draft found'}
    if not db.user_may_access_draft(g.user_id, draft):
        return None, {'error': 'No project draft found'}
    return draft, None


def _has_approvals_permission():
    """True when the caller may decide on another actor's section version."""
    try:
        if getattr(g, 'is_admin', False):
            return True
    except Exception:
        pass
    if getattr(g, 'user_id', None) is None:
        return True
    try:
        perms = getattr(g, 'user_permissions', None) or db.get_user_permissions(
            g.user_id, getattr(g, 'user_role', None) or 'employee')
    except Exception:
        perms = {}
    return bool((perms or {}).get('approvals'))


def _versioned_draft_for_read(draft_id):
    """Draft visible to its owner or to a caller with the approvals permission.

    Project-scoped users stay inside their scope either way (t20): a granted
    approvals permission never widens the project list an invite fixed."""
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
    if not draft:
        return None, {'error': 'No project draft found'}
    if not db.user_may_access_draft(g.user_id, draft):
        return None, {'error': 'No project draft found'}
    if draft.get('user_id') == _project_draft_actor_id():
        return draft, None
    if _has_approvals_permission():
        return draft, None
    # The draft's assigned approver reviews it even without the global
    # approvals permission — the assignment IS the approver role. Its
    # assigned editor reads the version history they work against.
    try:
        if db.user_is_assigned_approver(g.tenant_id, g.user_id, draft.get('id')) \
                or db.user_is_assigned_editor(g.tenant_id, g.user_id, draft.get('id')):
            return draft, None
    except Exception:
        pass
    return None, {'error': 'No project draft found'}


def _versioned_draft_for_decide(draft_id):
    """Draft whose pending version the caller may approve, return or reject.

    One approver per project: a draft with an assigned approver is decided by
    that approver alone (company admins keep their override); only a draft
    with no assignment falls back to the legacy approvals pool.
    """
    draft = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
    if not draft or not db.user_may_access_draft(g.user_id, draft):
        return None, {'error': 'No project draft found'}
    try:
        assigned = db.assigned_approver(g.tenant_id, draft.get('id'))
    except Exception:
        assigned = None
    if assigned:
        if _landloom_actor_is_admin() \
                or str(assigned.get('user_id') or '') == str(g.user_id or ''):
            return draft, None
        return None, {'error': 'No project draft found'}
    if _has_approvals_permission():
        return draft, None
    return None, {'error': 'No project draft found'}


def _section_required_missing_labels(tenant_id, section_key, snapshot):
    """Required field labels of one section that carry no content right now."""
    wanted = []
    try:
        for prebuilt in db.PREBUILT_FIELDS:
            if prebuilt.get('section_key') == section_key and prebuilt.get('required'):
                wanted.append((prebuilt['key'], prebuilt.get('label') or prebuilt['key']))
    except Exception:
        pass
    try:
        for field in db.get_fields(tenant_id):
            if (field.get('section_key') or '') != section_key:
                continue
            if not field.get('is_required') or not field.get('is_active', 1):
                continue
            key = field.get('field_key')
            if key:
                wanted.append((key, field.get('field_label') or key))
    except Exception:
        pass
    missing = []
    data = snapshot if isinstance(snapshot, dict) else {}
    for key, label in wanted:
        if not _draft_value_has_content(data.get(key)):
            if label not in missing:
                missing.append(label)
    return missing


def _section_version_readiness(draft, section_key, section_map=None):
    """Readiness of one section against its latest snapshot.

    Returns (state, meta) where state is ok, not_approved, stale or expired.
    Sections without any version return (legacy, None) so the old toggle
    keeps working.
    """
    try:
        overview = db.section_versions_overview(g.tenant_id, (draft or {}).get('id'))
    except Exception:
        overview = {}
    meta = (overview or {}).get(section_key)
    if not meta:
        return 'legacy', None
    if (meta.get('status') or '') != 'approved':
        return 'not_approved', meta
    if meta.get('is_expired'):
        return 'expired', meta
    try:
        live_hash = db.section_snapshot_hash(
            _section_snapshot_slice((draft or {}).get('draft_data') or {}, section_key,
                                    section_map if section_map is not None else _draft_field_section_map(g.tenant_id)))
    except Exception:
        return 'stale', meta
    if live_hash != meta.get('snapshot_hash'):
        return 'stale', meta
    return 'ok', meta


def _void_stale_section_approvals(tenant_id, draft_id, draft_data):
    """Drop section statuses whose live content no longer matches the approved
    snapshot (t16): an edit on an approved section voids that approval and the
    section falls back to 'draft' until it is sent and decided again. Expired
    approvals void the same way (d05)."""
    draft = db.get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return
    statuses = draft.get('section_statuses') or {}
    if not statuses:
        return
    overview = db.section_versions_overview(tenant_id, draft_id)
    section_map = _draft_field_section_map(tenant_id)
    stale = {}
    for key, value in statuses.items():
        if value != 'approved':
            continue
        meta = overview.get(key)
        if not meta or meta.get('status') != 'approved':
            continue
        live_hash = db.section_snapshot_hash(
            _section_snapshot_slice(draft_data, key, section_map))
        if live_hash != meta.get('snapshot_hash') or meta.get('is_expired'):
            stale[key] = 'draft'
    if stale:
        db.update_draft_section_status_by_id(tenant_id, draft_id, stale)


def _draft_field_section_map(tenant_id):
    """Map every draft key the section UI governs to its section key."""
    section_map = {}
    try:
        for field in db.get_fields(tenant_id):
            field_key = field.get('field_key')
            if field_key:
                section_map[field_key] = field.get('section_key') or 'general'
    except Exception:
        pass
    for prebuilt in db.PREBUILT_FIELDS:
        section_map.setdefault(prebuilt['key'], prebuilt.get('section_key', 'general'))
    section_map.update(DRAFT_FIELD_SECTION_BLOBS)
    return section_map


def _draft_section_of_key(section_map, key):
    """Resolve a draft key (including *_file_id/_file_meta companions) to a section."""
    section = section_map.get(key)
    if section:
        return section
    for suffix in ('_file_ids', '_file_meta', '_file_id'):
        if key.endswith(suffix):
            return section_map.get(key[:-len(suffix)])
    return None


def _draft_value_has_content(value):
    """True when a value carries something worth refusing to write blindly."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, dict):
        return any(_draft_value_has_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_draft_value_has_content(item) for item in value)
    return True


def _draft_values_equal(first, second):
    """Compare draft values so an untouched hidden section never looks edited."""
    if first == second:
        return True
    try:
        return json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
            second, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return False


def _enforce_draft_field_sections(draft_data, stored_data, section_statuses, stored_statuses):
    """Refuse a blocked section write while keeping the allowed work saveable.

    Hidden sections are not rendered, so a legitimate save carries their stored
    values unchanged (or omits them). Only incoming content that differs from
    storage is a real write to a section the actor cannot reach, and that is
    refused with 403. Anything else is restored from storage so a stale or
    partial client can neither edit nor wipe what it cannot see.
    Returns (forbidden_sections, restored_sections).
    """
    allowed = db.get_user_field_sections(g.user_id, g.tenant_id)
    denied = {key for key, granted in allowed.items() if not granted} - {'general'}
    if not denied:
        return [], []
    section_map = _draft_field_section_map(g.tenant_id)
    stored = stored_data if isinstance(stored_data, dict) else {}
    forbidden = []
    restored = []

    section_labels = {s['key']: s.get('label') or s['key'] for s in db.get_all_sections(g.tenant_id)}
    for key in list(draft_data.keys()):
        section = _draft_section_of_key(section_map, key)
        if section not in denied:
            continue
        incoming_value = draft_data.get(key)
        stored_value = stored.get(key)
        if _draft_values_equal(incoming_value, stored_value):
            continue
        if _draft_value_has_content(incoming_value):
            label = section_labels.get(section, section)
            if label not in forbidden:
                forbidden.append(label)
            continue
        if key in stored:
            draft_data[key] = stored_value
            restored.append(key)
        else:
            draft_data.pop(key, None)

    # A key the client omitted must not wipe storage either: the save overwrites
    # the whole row, and a hidden section is absent precisely because it was not
    # rendered.
    inverted = {}
    for field_key, section in section_map.items():
        if section in denied:
            inverted.setdefault(section, []).append(field_key)
    for section, field_keys in inverted.items():
        for field_key in field_keys:
            if field_key not in draft_data and field_key in stored:
                draft_data[field_key] = stored[field_key]
                restored.append(field_key)

    if isinstance(section_statuses, dict) and section_statuses:
        previous = stored_statuses if isinstance(stored_statuses, dict) else {}
        for section in denied:
            if section in section_statuses and section_statuses[section] != previous.get(section, 'draft'):
                section_statuses[section] = previous.get(section, 'draft')
                restored.append('status:' + section)
    return forbidden, restored


def _sanitize_save_section_statuses(tenant_id, draft, incoming, stored_statuses):
    """ISS-023: a plain save may not mint approvals outside the gated route.

    Mirroring the stored value and demoting to 'draft' are always safe — a stale
    client must still be able to save its edit. A NEW 'approved' has to pass the
    same gates the section-status route enforces (location workflow, no pending
    version, version readiness); otherwise the stored value stands. Keys the
    payload dropped are restored from storage so the map cannot be pruned.
    """
    if incoming is None:
        return None
    stored = stored_statuses if isinstance(stored_statuses, dict) else {}
    sanitized = dict(stored)
    blocked = []
    section_map = None
    draft_id = (draft or {}).get('id')
    for key, value in incoming.items():
        if not isinstance(key, str) or not key or value not in {'draft', 'approved'}:
            continue
        if value == 'draft' or stored.get(key) == 'approved':
            sanitized[key] = value
            continue
        if key == 'location' and not _location_workflow_complete(draft):
            blocked.append(key)
            continue
        if draft_id and db.pending_section_versions(tenant_id, draft_id, [key]):
            blocked.append(key)
            continue
        if section_map is None:
            section_map = _draft_field_section_map(tenant_id)
        state, _meta = _section_version_readiness(draft, key, section_map)
        if state in {'not_approved', 'stale', 'expired'}:
            blocked.append(key)
            continue
        sanitized[key] = 'approved'
    if blocked:
        app.logger.warning(
            '[DRAFT SAVE] Restored %d ungated approval(s): tenant=%s draft=%s sections=%s',
            len(blocked), tenant_id, draft_id, blocked[:12])
    return sanitized


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
            _void_stale_section_approvals(g.tenant_id, draft_id, draft_data)
        except Exception:
            pass
    saved_revision = None
    saved_draft = db.get_project_draft_by_id(g.tenant_id, draft_id)
    if saved_draft:
        saved_revision = int(saved_draft.get('revision') or 0)
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
    project = (draft or {}).get('draft_data') if isinstance(draft, dict) else {}
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (TypeError, ValueError):
            project = {}
    if not isinstance(project, dict) or project.get('location_analysis_approved') not in (True, 'true', 1):
        return False
    creative = project.get('tenantCreativeImages') if isinstance(project.get('tenantCreativeImages'), dict) else {}
    approvals = creative.get('map_approvals') if isinstance(creative.get('map_approvals'), dict) else {}
    return all(approvals.get(key) is True for key in ('overview', 'access', 'catchment', 'landmarks'))


# Mirrors LOCATION_ANALYSIS_KEYS on the client: the analysis approval exists to
# confirm a complete location input set, so the server requires the same set.
_LOCATION_ANALYSIS_REQUIRED_KEYS = (
    'location_address', 'location_lat', 'location_lng', 'city', 'district',
    'main_roads', 'nearby_landmarks', 'city_landmarks', 'location_detail')
_MAP_APPROVAL_TYPES = ('overview', 'access', 'catchment', 'landmarks')


def _location_analysis_approvable(project_data):
    """Whether the location analysis approval may stand: full inputs present."""
    if not isinstance(project_data, dict):
        return False
    for key in _LOCATION_ANALYSIS_REQUIRED_KEYS:
        value = project_data.get(key)
        if value is None or value == [] or value == {} \
                or (isinstance(value, str) and not value.strip()):
            return False
    return True


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

    Approval flags can always be cleared, and may only be set when the artifact
    they claim exists: analysis approval needs the complete location input set;
    a map approval needs a generated map recorded under this project. A bare
    claim written into draftData does not survive — the stored value stands.
    """
    if not isinstance(draft_data, dict):
        return draft_data
    stored = stored_data if isinstance(stored_data, dict) else {}
    truthy = lambda v: v in (True, 'true', 1)
    if truthy(draft_data.get('location_analysis_approved')) \
            and not truthy(stored.get('location_analysis_approved')) \
            and not _location_analysis_approvable(draft_data):
        draft_data['location_analysis_approved'] = \
            stored.get('location_analysis_approved') or False
        app.logger.warning(
            '[DRAFT SAVE] Refused unbacked location analysis approval: tenant=%s draft=%s',
            tenant_id, draft_id)
    creative = draft_data.get('tenantCreativeImages')
    stored_creative = stored.get('tenantCreativeImages')
    if isinstance(creative, dict) and isinstance(creative.get('map_approvals'), dict):
        incoming = creative['map_approvals']
        stored_approvals = (stored_creative.get('map_approvals')
                            if isinstance(stored_creative, dict) else {}) or {}
        for key, value in list(incoming.items()):
            if truthy(value) and not truthy(stored_approvals.get(key)) \
                    and key in _MAP_APPROVAL_TYPES \
                    and not _map_image_artifact(tenant_id, key, draft_id=draft_id):
                incoming[key] = False
                app.logger.warning(
                    '[DRAFT SAVE] Refused map approval without a generated map: '
                    'tenant=%s draft=%s map=%s', tenant_id, draft_id, key)
    return draft_data


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


@app.route('/api/project-draft/section-status', methods=['POST'])
@require_auth
def api_update_section_status():
    """Update one section's status, or several in a single atomic merge."""
    data = request.json or {}
    bulk = data.get('sectionStatuses')
    if isinstance(bulk, dict) and bulk:
        # Approving every section used to fire one request per section in parallel, and the
        # concurrent read-modify-write on the shared JSON column lost half of them.
        if any(not isinstance(key, str) or not key or value not in {'draft', 'approved'} for key, value in bulk.items()):
            return jsonify({'error': 'A valid sectionStatuses map is required'}), 400
        draft_id = _resolve_draft_id(data.get('draftId'))
        before = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
        # ISS-014/ISS-015: the draft must be in scope and a hidden section's
        # status is never the caller's to change.
        if before and not db.user_may_access_draft(g.user_id, before):
            return jsonify({'error': 'Draft not found'}), 404
        denied_sections = _hidden_field_sections()
        if denied_sections and any(key in denied_sections for key in bulk):
            return jsonify({'error': 'قسم غير متاح لهذا المستخدم',
                            'error_code': 'SECTION_FORBIDDEN'}), 403
        if bulk.get('location') == 'approved' and not _location_workflow_complete(before):
            return jsonify({'error': 'Location analysis and all four maps must be approved first',
                            'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
        if draft_id:
            blocked = db.pending_section_versions(g.tenant_id, draft_id, list(bulk))
            if blocked:
                return jsonify({'error': 'These sections await a version decision; decide on the sent version first',
                                'error_code': 'SECTION_VERSION_PENDING', 'sections': blocked}), 409
            versioned_blocked = []
            if before:
                section_map = _draft_field_section_map(g.tenant_id)
                for key, value in bulk.items():
                    if value != 'approved':
                        continue
                    state, _meta = _section_version_readiness(before, key, section_map)
                    if state in {'not_approved', 'stale', 'expired'}:
                        versioned_blocked.append(key)
            if versioned_blocked:
                return jsonify({'error': 'These sections have version snapshots; send and approve the version instead of toggling directly',
                                'error_code': 'SECTION_VERSION_REQUIRED', 'sections': versioned_blocked}), 409
        try:
            result = db.update_draft_section_statuses(
                g.tenant_id, _project_draft_actor_id(), bulk, draft_id=data.get('draftId')
            )
        except db.DraftLocked as locked:
            return _draft_locked_response(locked.status)
        if not result:
            return jsonify({'error': 'Unable to update section status'}), 400
        _record_change('draft', draft_id or _resolve_draft_id(), 'اعتماد الأقسام',
                       change_tracking.describe_section_status_changes(
                           (before or {}).get('section_statuses') if isinstance(before, dict) else {}, bulk))
        return jsonify({'success': True})
    section_key = data.get('sectionKey')
    section_status = data.get('sectionStatus')
    if not isinstance(section_key, str) or not section_key or section_status not in {'draft', 'approved'}:
        return jsonify({'error': 'A valid sectionKey and sectionStatus are required'}), 400
    draft_id = _resolve_draft_id(data.get('draftId'))
    before = db.get_project_draft_by_id(g.tenant_id, draft_id) if draft_id else None
    if before and not db.user_may_access_draft(g.user_id, before):
        return jsonify({'error': 'Draft not found'}), 404
    if _section_key_forbidden(section_key):
        return jsonify({'error': 'قسم غير متاح لهذا المستخدم',
                        'error_code': 'SECTION_FORBIDDEN'}), 403
    if section_key == 'location' and section_status == 'approved' and not _location_workflow_complete(before):
        return jsonify({'error': 'Location analysis and all four maps must be approved first',
                        'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
    if draft_id and db.pending_section_versions(g.tenant_id, draft_id, [section_key]):
        return jsonify({'error': 'This section awaits a version decision; decide on the sent version first',
                        'error_code': 'SECTION_VERSION_PENDING', 'sections': [section_key]}), 409
    if section_status == 'approved' and before:
        state, meta = _section_version_readiness(
            before, section_key, _draft_field_section_map(g.tenant_id))
        if state in {'not_approved', 'stale', 'expired'}:
            code = {'not_approved': 'SECTION_VERSION_PENDING',
                    'stale': 'SECTION_VERSION_STALE',
                    'expired': 'SECTION_VERSION_EXPIRED'}[state]
            return jsonify({'error': 'This section has version snapshots; send and approve the version instead of toggling directly',
                            'error_code': code, 'sections': [section_key],
                            'version': (meta or {}).get('version_number')}), 409
    try:
        result = db.update_draft_section_status(
            g.tenant_id, _project_draft_actor_id(), section_key, section_status, draft_id=data.get('draftId')
        )
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    if not result:
        return jsonify({'error': 'Unable to update section status'}), 400
    _record_change('draft', draft_id or _resolve_draft_id(), 'اعتماد قسم',
                   change_tracking.describe_section_status_changes(
                       (before or {}).get('section_statuses') if isinstance(before, dict) else {},
                       {section_key: section_status}))
    return jsonify({'success': True})


@app.route('/api/project-draft/section-version', methods=['POST'])
@require_auth
def api_send_section_for_approval():
    """Freeze this moment's section inputs as a new pending version for approval."""
    data = request.json or {}
    section_key = data.get('sectionKey')
    if not isinstance(section_key, str) or not section_key.strip():
        return jsonify({'error': 'A valid sectionKey is required'}), 400
    section_key = section_key.strip()
    draft, error = _versioned_draft_or_404(_resolve_draft_id(data.get('draftId')))
    if error:
        return jsonify(error), 404
    # ISS-015: a section hidden from the caller cannot be sent for approval.
    if _section_key_forbidden(section_key):
        return jsonify({'error': 'قسم غير متاح لهذا المستخدم',
                        'error_code': 'SECTION_FORBIDDEN'}), 403
    if section_key == 'location' and not _location_workflow_complete(draft):
        return jsonify({'error': 'Location analysis and all four maps must be approved first',
                        'error_code': 'LOCATION_WORKFLOW_NOT_APPROVED'}), 400
    stored = draft.get('draft_data') or {}
    section_map = _draft_field_section_map(g.tenant_id)
    snapshot = _section_snapshot_slice(stored, section_key, section_map)
    missing = _section_required_missing_labels(g.tenant_id, section_key, snapshot)
    if missing:
        return jsonify({'error': 'Required section fields are missing',
                        'error_code': 'SECTION_VERSION_INCOMPLETE', 'missing': missing}), 400
    version = db.create_section_version(
        g.tenant_id, draft['id'], section_key, snapshot,
        _project_draft_actor_id(), _project_draft_actor_name(),
        allow_supersede=bool(data.get('supersede')),
    )
    if version.get('error') == 'draft_not_found':
        return jsonify({'error': 'No project draft found'}), 404
    if version.get('error') == 'unknown_section':
        return jsonify({'error': 'Unknown project section'}), 400
    if version.get('error') == 'draft_locked':
        return _draft_locked_response(version.get('status'))
    if version.get('error') == 'version_pending_exists':
        # t13-04: a send already under review is never dropped silently; the
        # client either cancels it or resubmits with supersede=true.
        return jsonify({'error': 'يوجد إصدار قيد المراجعة لهذا القسم بالفعل',
                        'error_code': 'SECTION_VERSION_PENDING_EXISTS',
                        'version_id': version.get('version_id'),
                        'version_number': version.get('version_number')}), 409
    if version.get('error'):
        return jsonify({'error': 'Unable to store the section snapshot'}), 400
    try:
        # t13-01: every send opens an approver task and notifies the approvers
        # whose section scope covers this key. When the draft carries an
        # assigned approver the request goes to them alone — responsibility
        # assignments outrank the permission broadcast.
        assigned = db.assigned_approver(g.tenant_id, draft['id'])
        db.create_approval_task(
            g.tenant_id, 'section_approval',
            f'اعتماد قسم «{_section_version_label(section_key)}»',
            entity_type='section_version', entity_id=version['id'],
            section_key=section_key,
            assignee_id=(assigned or {}).get('user_id'),
            assignee_name=(assigned or {}).get('user_name'),
            payload={'draft_id': draft['id'], 'version_number': version['version_number']},
            due_hours=48, draft_id=draft['id'])
        if assigned:
            db.create_notification(
                g.tenant_id, 'إصدار قسم بانتظار الاعتماد',
                f'«{draft.get("title") or "مشروع"}» — القسم {_section_version_label(section_key)} بانتظار قرارك',
                category='section_approval', user_id=assigned['user_id'],
                entity_type='section_version', entity_id=version['id'],
                mirror_admin=not _landloom_actor_is_admin(), email_to=None)
        else:
            for approver in db.get_users_with_permission(g.tenant_id, 'approvals'):
                try:
                    if not db.get_user_field_sections(approver['id'], g.tenant_id).get(section_key, True):
                        continue
                except Exception:
                    continue
                db.create_notification(
                    g.tenant_id, 'إصدار قسم بانتظار الاعتماد',
                    f'«{draft.get("title") or "مشروع"}» — القسم {_section_version_label(section_key)} بانتظار قرارك',
                    category='section_approval', user_id=approver['id'],
                    entity_type='section_version', entity_id=version['id'],
                    mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_change('draft', draft['id'], 'إرسال قسم للاعتماد',
                   [f'القسم {_section_version_label(section_key)}: لقطة رقم {version["version_number"]} بانتظار القرار'])
    _record_audit_event(
        action='section_version_submitted',
        entity_type='section_version',
        entity_id=version['id'],
        entity_name=f'القسم {_section_version_label(section_key)} (إصدار {version["version_number"]})',
        new_value=version.get('snapshot'),
        metadata={'draft_id': draft['id'], 'section_key': section_key, 'version_number': version['version_number']},
    )
    return jsonify({'success': True, 'version': version})


@app.route('/api/project-draft/section-versions', methods=['GET'])
@require_auth
def api_list_section_versions():
    """Newest-first version history of a draft, metadata only."""
    draft, error = _versioned_draft_for_read(_resolve_draft_id(request.args.get('draftId')))
    if error:
        return jsonify(error), 404
    section_key = request.args.get('sectionKey') or None
    versions = db.list_section_versions(g.tenant_id, draft['id'], section_key)
    # ISS-015: versions of hidden sections are not the caller's to see.
    denied = _hidden_field_sections()
    if denied:
        versions = [v for v in versions if v.get('section_key') not in denied]
    return jsonify({'success': True, 'versions': versions})


@app.route('/api/project-draft/section-versions/<version_id>', methods=['GET'])
@require_auth
def api_get_section_version(version_id):
    """One version with its immutable snapshot, for history and comparison."""
    version = db.get_section_version(g.tenant_id, version_id, include_snapshot=True)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    _draft, error = _versioned_draft_for_read(version.get('draft_id'))
    if error:
        return jsonify({'error': 'Section version not found'}), 404
    # ISS-015: a hidden section's snapshot never leaves the server.
    if _section_key_forbidden(version.get('section_key')):
        return jsonify({'error': 'Section version not found'}), 404
    return jsonify({'success': True, 'version': version})


@app.route('/api/project-draft/section-version/decision', methods=['POST'])
@require_auth
def api_decide_section_version():
    """Approve, return or reject one sent version; the decision names its number."""
    data = request.json or {}
    version_id = data.get('versionId')
    decision = data.get('decision')
    if not version_id or decision not in {'approved', 'returned', 'rejected'}:
        return jsonify({'error': 'A valid versionId and decision are required'}), 400
    version = db.get_section_version(g.tenant_id, version_id, include_snapshot=False)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    draft, error = _versioned_draft_for_decide(version.get('draft_id'))
    if error:
        return jsonify(error), 404
    actor_id = _project_draft_actor_id()
    # t13-02: a non-admin approver decides only inside their granted field
    # sections; keys outside the field map stay governed by the approvals
    # permission that already let this caller reach the decision. The draft's
    # assigned approver is responsible for every section in it.
    assigned_approver = False
    try:
        assigned_approver = db.user_is_assigned_approver(
            g.tenant_id, g.user_id, draft.get('id'))
    except Exception:
        pass
    if not _landloom_actor_is_admin() and str(draft.get('user_id')) != str(actor_id) \
            and not assigned_approver:
        section_key = version['section_key']
        if section_key in db.DEFAULT_FIELD_SECTIONS:
            try:
                granted = db.get_user_field_sections(g.user_id, g.tenant_id)
            except Exception:
                granted = {}
            if not granted.get(section_key):
                return jsonify({'error': 'هذا القسم خارج نطاق اعتمادك',
                                'error_code': 'section_scope_forbidden'}), 403
    decided = db.decide_section_version(
        g.tenant_id, version_id, decision,
        actor_id, _project_draft_actor_name(), data.get('note'),
    )
    if decided.get('error') == 'version_not_found':
        return jsonify({'error': 'Section version not found'}), 404
    if decided.get('error') == 'version_not_pending':
        return jsonify({'error': 'This version was already decided',
                        'error_code': 'SECTION_VERSION_DECIDED'}), 409
    if decided.get('error') == 'draft_locked':
        return _draft_locked_response(decided.get('status'))
    if decided.get('error') == 'note_required':
        return jsonify({'error': 'A reason is required to return or reject a version'}), 400
    if decided.get('error') == 'self_approval_blocked_by_policy':
        return jsonify({'error': 'سياسة الشركة تمنع المحرر من اعتماد قسمه بنفسه',
                        'error_code': 'self_approval_blocked_by_policy'}), 403
    if decided.get('error'):
        return jsonify({'error': 'Unable to record the version decision'}), 400
    mirror = 'approved' if decision == 'approved' else 'draft'
    try:
        db.update_draft_section_status_by_id(
            g.tenant_id, draft['id'], {version['section_key']: mirror}
        )
    except db.DraftLocked as locked:
        return _draft_locked_response(locked.status)
    action = {'approved': 'اعتماد نسخة قسم', 'returned': 'إعادة نسخة قسم للتعديل', 'rejected': 'رفض نسخة قسم'}[decision]
    detail = f'القسم {_section_version_label(version["section_key"])}: لقطة رقم {version["version_number"]} — {action}'
    if decided.get('decision_note'):
        detail += f' (السبب: {decided["decision_note"]})'
    if (version.get('created_by') or '') == actor_id:
        detail += ' (اعتماد ذاتي)'
    try:
        # t13-03: the decision closes the approver task; a return opens an
        # editor task for the version's sender and notifies them.
        db.close_approval_tasks_for_entity(
            g.tenant_id, 'section_version', version_id,
            closed_by_name=_project_draft_actor_name())
        sender = str(version.get('created_by') or '')
        if decision in {'returned', 'rejected'}:
            db.create_approval_task(
                g.tenant_id, 'revision',
                f'إعادة قسم «{_section_version_label(version["section_key"])}» للتعديل',
                entity_type='project_draft', entity_id=draft['id'],
                section_key=version['section_key'],
                assignee_id=None if sender.startswith('tenant-admin:') else sender or None,
                payload={'version_id': version_id, 'note': decided.get('decision_note')},
                draft_id=draft['id'])
        # The admin sees every staff exchange — including a verdict on work
        # he submitted himself. Only a self-decision stays notification-free;
        # the audit trail is where admin-caused decisions live regardless.
        if not _recipient_is_actor(g.tenant_id, sender, actor_id, _landloom_actor_is_admin()):
            message = {'approved': 'اعتُمد قسمك',
                       'returned': 'أُعيد قسمك للتعديل',
                       'rejected': 'رُفض قسمك'}[decision]
            db.create_notification(
                g.tenant_id, message,
                f'«{draft.get("title") or "مشروع"}» — القسم {_section_version_label(version["section_key"])}',
                category='section_approval',
                user_id=sender,
                entity_type='section_version', entity_id=version_id,
                mirror_admin=not _landloom_actor_is_admin())
    except Exception:
        pass
    _record_change('draft', draft['id'], action, [detail])
    _record_audit_event(
        action=f'section_version_{decision}',
        entity_type='section_version',
        entity_id=version_id,
        entity_name=f'القسم {_section_version_label(version["section_key"])} (إصدار {version["version_number"]})',
        old_value={'status': 'pending'},
        new_value={'status': decided.get('status'), 'decision_note': data.get('note')},
        metadata={'draft_id': draft['id'], 'section_key': version['section_key'], 'version_number': version['version_number']},
    )
    return jsonify({'success': True, 'version': decided})


@app.route('/api/project-draft/section-version/cancel', methods=['POST'])
@require_auth
def api_cancel_section_version():
    """Withdraw a pending send so the editor keeps working on a later draft."""
    data = request.json or {}
    version_id = data.get('versionId')
    if not version_id:
        section_key = (data.get('sectionKey') or '').strip() if isinstance(data.get('sectionKey'), str) else ''
        draft, error = _versioned_draft_or_404(_resolve_draft_id(data.get('draftId')))
        if error:
            return jsonify(error), 404
        if not section_key:
            return jsonify({'error': 'A valid versionId is required'}), 400
        pending = [item for item in db.list_section_versions(g.tenant_id, draft['id'], section_key)
                   if (item.get('status') or '') == 'pending']
        if not pending:
            return jsonify({'error': 'No pending version to cancel'}), 404
        version_id = pending[0]['id']
    version = db.get_section_version(g.tenant_id, version_id, include_snapshot=False)
    if not version:
        return jsonify({'error': 'Section version not found'}), 404
    draft, error = _versioned_draft_for_read(version.get('draft_id'))
    if error:
        return jsonify(error), 404
    if _section_key_forbidden(version.get('section_key')):
        return jsonify({'error': 'Section version not found'}), 404
    if draft.get('user_id') != _project_draft_actor_id() and not _has_approvals_permission() \
            and str(version.get('created_by') or '') != str(_project_draft_actor_id()):
        return jsonify({'error': 'Section version not found'}), 404
    cancelled = db.cancel_section_version(
        g.tenant_id, version_id,
        _project_draft_actor_id(), _project_draft_actor_name(),
    )
    if cancelled.get('error') == 'version_not_found':
        return jsonify({'error': 'Section version not found'}), 404
    if cancelled.get('error') == 'version_not_pending':
        return jsonify({'error': 'This version was already decided',
                        'error_code': 'SECTION_VERSION_DECIDED'}), 409
    if cancelled.get('error') == 'draft_locked':
        return _draft_locked_response(cancelled.get('status'))
    if cancelled.get('error'):
        return jsonify({'error': 'Unable to cancel the section version'}), 400
    try:
        db.close_approval_tasks_for_entity(
            g.tenant_id, 'section_version', version_id,
            closed_by_name=_project_draft_actor_name(), cancel_reason='سحب طلب الاعتماد')
    except Exception:
        pass
    _record_change('draft', draft['id'], 'إلغاء طلب اعتماد قسم',
                   [f'القسم {_section_version_label(version["section_key"])}: لقطة رقم {version["version_number"]} أُلغيت'])
    _record_audit_event(
        action='section_version_cancelled',
        entity_type='section_version',
        entity_id=version_id,
        entity_name=f'القسم {_section_version_label(version["section_key"])} (إصدار {version["version_number"]})',
        old_value={'status': 'pending'},
        new_value={'status': 'cancelled'},
        metadata={'draft_id': draft['id'], 'section_key': version['section_key']},
    )
    return jsonify({'success': True, 'version': cancelled})


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
    map_approvals = snapshot.pop('map_approvals', None)
    live.update(snapshot)
    if version['section_key'] == 'location' and isinstance(map_approvals, dict):
        raw_creative = live.get('tenantCreativeImages')
        if isinstance(raw_creative, str):
            try:
                raw_creative = json.loads(raw_creative)
            except Exception:
                raw_creative = {}
        creative = dict(raw_creative) if isinstance(raw_creative, dict) else {}
        creative['map_approvals'] = map_approvals
        live['tenantCreativeImages'] = creative
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
                                   _landloom_actor_is_admin()):
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
