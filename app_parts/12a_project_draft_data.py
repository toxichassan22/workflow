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
    'timeline_end_date': 'section-timeline',
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
    'site_analysis_approved',
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
    return selected


def _section_snapshot_slices(draft_data, section_map):
    """All sections' snapshot slices in a single walk of the payload.

    Checking several approved sections used to rescan every draft key once per
    section; the slices are identical to calling _section_snapshot_slice per key.
    """
    data = draft_data if isinstance(draft_data, dict) else {}
    section_map = section_map or {}
    slices = {}
    for key, value in data.items():
        if key in SECTION_SNAPSHOT_EXCLUDED_KEYS:
            continue
        section_key = _draft_section_of_key(section_map, key)
        if section_key:
            slices.setdefault(section_key, {})[key] = change_tracking.strip_url_fetch_params(value)
    for section_key, keys in SECTION_SNAPSHOT_BLOBS.items():
        for key in keys:
            if key in data:
                slices.setdefault(section_key, {})[key] = change_tracking.strip_url_fetch_params(data[key])
    for key in SECTION_SNAPSHOT_LOCATION_EXTRAS:
        if key in data:
            slices.setdefault('location', {})[key] = change_tracking.strip_url_fetch_params(data[key])
    return slices


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


def _section_version_readiness(draft, section_key, section_map=None, overview=None, slices=None):
    """Readiness of one section against its latest snapshot.

    Returns (state, meta) where state is ok, not_approved, stale or expired.
    Sections without any version return (legacy, None) so the old toggle
    keeps working. ``overview``/``slices`` let a caller that checks several
    sections pass a single fetched overview and a single-pass slice set.
    """
    if overview is None:
        try:
            overview = db.section_versions_overview(g.tenant_id, (draft or {}).get('id'))
        except Exception:
            overview = {}
    meta = (overview or {}).get(section_key)
    if _financial_parking_section_error(draft, section_key):
        return 'not_approved', meta
    if not meta:
        return 'legacy', None
    if (meta.get('status') or '') != 'approved':
        return 'not_approved', meta
    if meta.get('is_expired'):
        return 'expired', meta
    try:
        live_hash = db.section_snapshot_hash(
            slices.get(section_key, {}) if slices is not None else
            _section_snapshot_slice((draft or {}).get('draft_data') or {}, section_key,
                                    section_map if section_map is not None else _draft_field_section_map(g.tenant_id)))
    except Exception:
        return 'stale', meta
    if live_hash != meta.get('snapshot_hash'):
        return 'stale', meta
    return 'ok', meta


def _void_stale_section_approvals(tenant_id, draft_id, draft_data, statuses=None):
    """Drop section statuses whose live content no longer matches the approved
    snapshot (t16): an edit on an approved section voids that approval and the
    section falls back to 'draft' until it is sent and decided again. Expired
    approvals void the same way (d05). The caller may pass the effective
    ``statuses`` map so the just-saved row is not re-read and re-parsed."""
    if statuses is None:
        draft = db.get_project_draft_by_id(tenant_id, draft_id)
        if not draft:
            return
        statuses = draft.get('section_statuses') or {}
    if not statuses:
        return
    overview = db.section_versions_overview(tenant_id, draft_id)
    section_map = _draft_field_section_map(tenant_id)
    slices = None
    stale = {}
    if statuses.get('section-financial-calc') == 'approved' and _financial_parking_section_error(
            {'draft_data': draft_data}, 'section-financial-calc'):
        stale['section-financial-calc'] = 'draft'
    model = financial_parking.parking_object((draft_data or {}).get('financial_study_model'))
    if model.get('parkingPlan', {}).get('inputsChanged') and statuses.get('section-visual-concept') == 'approved':
        stale['section-visual-concept'] = 'draft'
    for key, value in statuses.items():
        if value != 'approved':
            continue
        meta = overview.get(key)
        if not meta or meta.get('status') != 'approved':
            continue
        if slices is None:
            slices = _section_snapshot_slices(draft_data, section_map)
        live_hash = db.section_snapshot_hash(slices.get(key, {}))
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
    overview = None
    slices = None
    draft_id = (draft or {}).get('id')
    for key, value in incoming.items():
        if not isinstance(key, str) or not key or value not in {'draft', 'approved'}:
            continue
        if value == 'approved' and _financial_parking_section_error(draft, key):
            sanitized[key] = 'draft'
            blocked.append(key)
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
        if overview is None:
            try:
                overview = db.section_versions_overview(tenant_id, draft_id)
            except Exception:
                overview = {}
        if slices is None:
            slices = _section_snapshot_slices((draft or {}).get('draft_data') or {}, section_map)
        state, _meta = _section_version_readiness(
            draft, key, section_map, overview=overview, slices=slices)
        if state in {'not_approved', 'stale', 'expired'}:
            blocked.append(key)
            continue
        sanitized[key] = 'approved'
    if blocked:
        app.logger.warning(
            '[DRAFT SAVE] Restored %d ungated approval(s): tenant=%s draft=%s sections=%s',
            len(blocked), tenant_id, draft_id, blocked[:12])
    return sanitized
