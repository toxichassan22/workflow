

# ─────────────────────────────────────────────────────────────────────────────
# Project Drafts
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Proposal Lifecycle: 11 official states (Landloom spec section 7 & 8)
#
#  1. draft: مسودة (المدخلات قابلة للتعديل ولم ترسل للاعتماد)
#  2. sections_in_progress: قيد إعداد الأقسام (يعمل المحررون على الأقسام بشكل متوازٍ)
#  3. section_approval_pending: بانتظار اعتماد قسم (القسم مقفل مؤقتًا على الإصدار المرسل)
#  4. rejected_for_revision: معاد للتعديل (رفض المعتمد القسم أو طلب تعديل مع ملاحظات)
#  5. sections_approved: الأقسام معتمدة (جميع الأقسام المطلوبة معتمدة على إصدارات محددة)
#  6. generation_approval_pending: بانتظار اعتماد التوليد (تم احتساب التكلفة التقديرية وتنتظر الموافقة)
#  7. generating: قيد التوليد (وظيفة التوليد تعمل في الخلفية)
#  8. generated_draft: مسودة ملف مولد (الملف قابل للتعديل بالشات أو النص وفق النطاق المنفذ)
#  9. final_approval_pending: بانتظار اعتماد الملف النهائي (نسخة محددة مرسلة للمعتمد النهائي)
# 10. approved: معتمد نهائيًا (نسخة رسمية مقفلة وقابلة للتنزيل)
# 11. archived: مؤرشف (غير نشط مع الاحتفاظ الكامل بالسجل)
# ─────────────────────────────────────────────────────────────────────────────

PROPOSAL_LIFECYCLE_STATES = {
    'draft': {
        'label': 'مسودة',
        'label_en': 'Draft',
        'phase': 'inputs',
        'description': 'المدخلات قابلة للتعديل ولم ترسل للاعتماد',
        'is_locked': False,
        'order': 1,
    },
    'sections_in_progress': {
        'label': 'قيد إعداد الأقسام',
        'label_en': 'Sections In Progress',
        'phase': 'inputs',
        'description': 'يعمل المحررون على الأقسام بشكل متوازٍ',
        'is_locked': False,
        'order': 2,
    },
    'section_approval_pending': {
        'label': 'بانتظار اعتماد قسم',
        'label_en': 'Section Approval Pending',
        'phase': 'inputs',
        'description': 'القسم مقفل مؤقتًا على الإصدار المرسل',
        'is_locked': False,
        'order': 3,
    },
    'rejected_for_revision': {
        'label': 'معاد للتعديل',
        'label_en': 'Returned For Revision',
        'phase': 'inputs',
        'description': 'رفض المعتمد القسم أو طلب تعديل مع ملاحظات',
        'is_locked': False,
        'order': 4,
    },
    'sections_approved': {
        'label': 'الأقسام معتمدة',
        'label_en': 'Sections Approved',
        'phase': 'inputs',
        'description': 'جميع الأقسام المطلوبة معتمدة على إصدارات محددة',
        'is_locked': False,
        'order': 5,
    },
    'generation_approval_pending': {
        'label': 'بانتظار اعتماد التوليد',
        'label_en': 'Generation Approval Pending',
        'phase': 'generation',
        'description': 'تم احتساب التكلفة التقديرية وتنتظر الموافقة',
        'is_locked': True,
        'order': 6,
    },
    'generating': {
        'label': 'قيد التوليد',
        'label_en': 'Generating',
        'phase': 'generation',
        'description': 'وظيفة التوليد تعمل في الخلفية',
        'is_locked': True,
        'order': 7,
    },
    'generated_draft': {
        'label': 'مسودة ملف مولد',
        'label_en': 'Generated Draft',
        'phase': 'output',
        'description': 'الملف قابل للتعديل بالشات أو النص وفق النطاق المنفذ',
        'is_locked': False,
        'order': 8,
    },
    'final_approval_pending': {
        'label': 'بانتظار اعتماد الملف النهائي',
        'label_en': 'Final Approval Pending',
        'phase': 'output',
        'description': 'نسخة محددة مرسلة للمعتمد النهائي',
        'is_locked': True,
        'order': 9,
    },
    'approved': {
        'label': 'معتمد نهائيًا',
        'label_en': 'Approved',
        'phase': 'output',
        'description': 'نسخة رسمية مقفلة وقابلة للتنزيل',
        'is_locked': True,
        'order': 10,
    },
    'archived': {
        'label': 'مؤرشف',
        'label_en': 'Archived',
        'phase': 'archived',
        'description': 'غير نشط مع الاحتفاظ الكامل بالسجل',
        'is_locked': True,
        'order': 11,
    },
}

PROPOSAL_ALLOWED_TRANSITIONS = {
    'draft': {'sections_in_progress', 'section_approval_pending', 'sections_approved', 'archived'},
    'sections_in_progress': {'section_approval_pending', 'sections_approved', 'rejected_for_revision', 'archived'},
    'section_approval_pending': {'sections_in_progress', 'rejected_for_revision', 'sections_approved', 'archived'},
    'rejected_for_revision': {'sections_in_progress', 'section_approval_pending', 'archived'},
    'sections_approved': {'generation_approval_pending', 'generating', 'sections_in_progress', 'rejected_for_revision', 'archived'},
    'generation_approval_pending': {'generating', 'generated_draft', 'sections_approved', 'sections_in_progress', 'archived'},
    'generating': {'generated_draft', 'sections_approved', 'archived'},
    'generated_draft': {'final_approval_pending', 'generation_approval_pending', 'generating', 'sections_in_progress', 'archived'},
    'final_approval_pending': {'approved', 'generated_draft', 'rejected_for_revision', 'archived'},
    'approved': {'archived', 'generated_draft', 'sections_in_progress'},
    'archived': {'draft', 'sections_in_progress'},
}

# The subset a user may pick through the manual transition endpoint. Gate states
# (generation_approval_pending, generating, generated_draft, final_approval_pending,
# approved) are entered only by their own backend workflows, never by hand.
PROPOSAL_MANUAL_TRANSITIONS = {
    'draft': {'sections_in_progress', 'section_approval_pending', 'archived'},
    'sections_in_progress': {'section_approval_pending', 'rejected_for_revision', 'archived'},
    'section_approval_pending': {'sections_in_progress', 'rejected_for_revision', 'sections_approved', 'archived'},
    'rejected_for_revision': {'sections_in_progress', 'section_approval_pending', 'archived'},
    'sections_approved': {'sections_in_progress', 'rejected_for_revision', 'archived'},
    'generation_approval_pending': {'sections_approved', 'sections_in_progress', 'archived'},
    'generating': {'archived'},
    'generated_draft': {'sections_in_progress', 'archived'},
    'final_approval_pending': {'generated_draft', 'archived'},
    'approved': {'generated_draft', 'sections_in_progress', 'archived'},
    'archived': {'draft', 'sections_in_progress'},
}

PROPOSAL_STATUS_ALIASES = {
    'pending_approval': 'section_approval_pending',
    'submitted': 'section_approval_pending',
    'edited': 'sections_in_progress',
}

PROJECT_DRAFT_STATUSES = set(PROPOSAL_LIFECYCLE_STATES.keys()) | {'pending_approval', 'submitted', 'edited'}
SECTION_DRAFT_STATUSES = {'draft', 'approved', 'pending'}


def normalize_proposal_status(status):
    """Normalize any historical or alias status to a canonical 11-state key."""
    if not status or not isinstance(status, str):
        return 'draft'
    clean = status.strip().lower()
    if clean in PROPOSAL_LIFECYCLE_STATES:
        return clean
    if clean in PROPOSAL_STATUS_ALIASES:
        return PROPOSAL_STATUS_ALIASES[clean]
    return 'draft'


def can_transition_proposal_status(current_status, next_status):
    """Check if a transition from current_status to next_status is valid."""
    curr = normalize_proposal_status(current_status)
    target = normalize_proposal_status(next_status)
    if curr == target:
        return True
    allowed = PROPOSAL_ALLOWED_TRANSITIONS.get(curr, set())
    return target in allowed


def proposal_status_is_locked(status):
    """True when the normalized lifecycle state freezes user edits."""
    return bool(PROPOSAL_LIFECYCLE_STATES.get(normalize_proposal_status(status), {}).get('is_locked'))


class DraftLocked(Exception):
    """Raised when a write targets a draft whose lifecycle state is locked."""

    def __init__(self, draft_id, status):
        super().__init__(f'Project draft {draft_id} is locked in state {status}')
        self.draft_id = draft_id
        self.status = status


class DraftRevisionConflict(Exception):
    """Raised when a save names a base revision the stored row already moved past."""

    def __init__(self, draft_id, expected_revision, current_revision):
        super().__init__(
            f'Project draft {draft_id} revision conflict: '
            f'expected {expected_revision}, current {current_revision}')
        self.draft_id = draft_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision

# Keys every save carries as bookkeeping: they say nothing about whether the payload still
# holds the project itself, so they are ignored when judging a destructive overwrite.
DRAFT_BOOKKEEPING_KEYS = {
    'draftId', 'draft_id', 'pageDrafts', 'sectionStatuses',
    'map_styles', 'map_type', 'calculate_landmark_driving', 'site_analysis_approved',
    'designerChat', 'presentation_scope',
}

# Below this many stored fields a draft is still being started, and blanking it can be a real
# edit. Above it, a payload that would leave nothing behind is a fault, not an instruction.
DRAFT_EMPTY_OVERWRITE_FLOOR = 3


class DraftOverwriteRefused(Exception):
    """Raised instead of blanking a stored draft that still holds project content."""

    def __init__(self, draft_id, stored_keys, incoming_keys):
        super().__init__(f'Refusing to empty project draft {draft_id}')
        self.draft_id = draft_id
        self.stored_keys = stored_keys
        self.incoming_keys = incoming_keys


def _has_content(value):
    """True when a stored value carries something a user would recognise as their data."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_content(item) for item in value)
    return True


def _draft_content_keys(payload):
    """Field names in a draft payload that actually carry project content."""
    if not isinstance(payload, dict):
        return set()
    return {
        key for key, value in payload.items()
        if key not in DRAFT_BOOKKEEPING_KEYS and _has_content(value)
    }


def _json_object(value):
    """Decode a JSON object safely; malformed historical data becomes empty."""
    if isinstance(value, dict):
        return value.copy()
    if not value:
        return {}
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _hydrate_project_draft(row):
    if not row:
        return None
    result = dict(row)
    result['draft_data'] = _json_object(result.get('draft_data'))
    result['section_statuses'] = _json_object(result.get('section_statuses'))
    if result.get('draft_data') and result.get('id'):
        result['draft_data']['draftId'] = result['id']
    return result


def _clear_draft_approval_fields(conn, draft_id):
    conn.execute(
        '''UPDATE project_drafts SET requested_by = NULL, requested_by_name = NULL,
           requested_at = NULL, reviewed_by = NULL, reviewed_by_name = NULL,
           review_note = NULL, reviewed_at = NULL WHERE id = ?''',
        (draft_id,)
    )


def save_project_draft(tenant_id, user_id, draft_data, section_statuses=None, status='draft',
                       draft_id=None, allow_generating=False, expected_revision=None):
    """Save one unified draft per tenant actor without losing section approvals.

    ``user_id`` is an actor identifier.  Company administrators use a stable
    tenant-admin identifier supplied by the API because their JWT has no user id.

    A save that does not name its draft still lands on the row this actor updated most recently,
    which is the single-draft contract older clients rely on.  That is also why an unnamed save
    reaching the wrong project is possible, so it is logged: a current client always sends an id.

    A locked lifecycle state refuses the write with ``DraftLocked``; the only exception is
    ``generating``, which a generation checkpoint may still update when the caller explicitly
    passes ``allow_generating``.  The ``status`` argument is a legacy hint, not a lifecycle
    command: a save never advances or regresses the stored state — only the approval-void
    reset below may move it, and new drafts always start as ``draft``.
    """
    conn = get_db()
    if draft_id:
        # ISS-029: a named draft identifies the tenant's row; the actor's scope
        # is enforced by the route before this call. Filtering by user_id here
        # made a shared draft look absent and the INSERT below die on a
        # duplicate primary key instead of accepting the authorized edit.
        existing = conn.execute(
            'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ?',
            (draft_id, tenant_id)
        ).fetchone()
    else:
        # The single-draft fallback targets the newest EDITABLE row: a locked
        # lifecycle state sealed that file, so work continues on the draft that
        # is still open instead of overwriting a sealed one.
        existing = conn.execute(
            '''SELECT * FROM project_drafts WHERE tenant_id = ? AND user_id = ?
               AND COALESCE(status, 'draft') NOT IN (
                   'generation_approval_pending', 'generating',
                   'final_approval_pending', 'approved', 'archived')
               ORDER BY updated_at DESC LIMIT 1''',
            (tenant_id, user_id)
        ).fetchone()
        if existing:
            print(f'[DRAFT SAVE] Save without a draft id applied to newest editable draft {existing["id"]} '
                  f'of actor {user_id}')

    # Determine the stable draft id before serializing
    draft_id = existing['id'] if existing else (draft_id or str(uuid.uuid4()))

    # ISS-030: a save that declares the revision it was made against cannot
    # land on a row that moved meanwhile — the conditional UPDATE below is the
    # atomic half of the same guarantee for the read-write window.
    if expected_revision is not None:
        if existing and int(existing['revision'] or 0) != int(expected_revision):
            raise DraftRevisionConflict(
                existing['id'], int(expected_revision), int(existing['revision'] or 0))
        if not existing and int(expected_revision) > 0:
            raise DraftRevisionConflict(draft_id, int(expected_revision), 0)

    now = _utcnow().isoformat()

    # Strip client-supplied draftId so it doesn't trigger false data_changed or bloat the row
    save_data = dict(draft_data) if isinstance(draft_data, dict) else {}
    save_data.pop('draftId', None)
    save_data.pop('draft_id', None)
    draft_json = json.dumps(save_data, ensure_ascii=False)
    title = str(save_data.get('project_name') or save_data.get('projectName') or save_data.get('name') or 'مسودة مشروع بدون عنوان').strip()[:200]
    creative = save_data.get('tenantCreativeImages') if isinstance(save_data.get('tenantCreativeImages'), dict) else {}
    has_slides = 1 if isinstance(save_data.get('tenantSlidesData'), list) and save_data.get('tenantSlidesData') else 0
    has_maps = 1 if isinstance(creative.get('map_placeholders'), dict) and any(creative.get('map_placeholders').values()) else 0
    data_bytes = len(draft_json.encode('utf-8'))

    if existing:
        norm_existing = normalize_proposal_status(existing['status'])
        if norm_existing == 'generating' and not allow_generating:
            # The 'generating' lock is only honest while a live run backs it —
            # a dead client leaves the state behind with nobody left to settle
            # it, so the save that notices the corpse is what frees the file.
            recover_dead_generating_drafts(tenant_id, draft_id=existing['id'])
            existing = conn.execute(
                'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ?',
                (existing['id'], tenant_id)).fetchone()
            norm_existing = normalize_proposal_status(existing['status'])
        if proposal_status_is_locked(norm_existing) \
                and not (allow_generating and norm_existing == 'generating'):
            raise DraftLocked(existing['id'], norm_existing)

        old_statuses = _json_object(existing['section_statuses'])
        # Older clients send {} whenever they autosave.  Treat that as "unchanged"
        # instead of silently erasing every section's review state.
        if isinstance(section_statuses, dict) and section_statuses:
            new_statuses = section_statuses
        elif section_statuses is None or section_statuses == {}:
            new_statuses = old_statuses
        else:
            new_statuses = _json_object(section_statuses)
        statuses_json = json.dumps(new_statuses, ensure_ascii=False)
        old_data = _json_object(existing['draft_data']) or {}
        old_data.pop('draftId', None)
        old_data.pop('draft_id', None)

        # A save that would leave the row with no project content at all is never a real edit:
        # emptying a project file is DELETE /api/project-draft/<id>.  Writing it used to answer
        # success, which is how a saved project could appear to empty itself with no error.
        stored_content = _draft_content_keys(old_data)
        incoming_content = _draft_content_keys(save_data)
        if len(stored_content) >= DRAFT_EMPTY_OVERWRITE_FLOOR and not incoming_content:
            raise DraftOverwriteRefused(existing['id'], sorted(stored_content), sorted(save_data))
        if stored_content and len(incoming_content) * 2 < len(stored_content):
            print(f'[DRAFT SAVE] Draft {existing["id"]} shrank from {len(stored_content)} to '
                  f'{len(incoming_content)} filled fields, '
                  f'{existing["data_bytes"] or 0} to {data_bytes} bytes. Dropped: '
                  f'{sorted(stored_content - incoming_content)[:12]}')

        data_changed = save_data != old_data
        statuses_changed = statuses_json != (existing['section_statuses'] or '{}')
        old_overall_status = existing['status'] or 'draft'

        norm_old_status = normalize_proposal_status(old_overall_status)
        if norm_old_status == 'section_approval_pending':
            if any(v == 'pending' for v in new_statuses.values()):
                # A live section-version review keeps the draft pending even when
                # unrelated fields change — the snapshot under review is immutable.
                next_status = old_overall_status
                clear_approval = False
            elif data_changed or statuses_changed:
                # Editing while a review request is open voids it; resubmit after fixing.
                next_status = 'draft'
                clear_approval = True
            else:
                next_status = old_overall_status
                clear_approval = False
        elif norm_old_status == 'approved' and (data_changed or statuses_changed):
            # Only reachable for a legacy raw 'approved' row: the canonical state is
            # locked above and a real reopen goes through transition with a reason.
            next_status = 'draft'
            clear_approval = True
        else:
            # The status hint ('draft'/'submitted') is never a lifecycle command: a save
            # neither regresses a reviewed draft nor submits it past the section gate.
            next_status = old_overall_status
            clear_approval = False

        update_sql = '''UPDATE project_drafts
               SET title = ?, draft_data = ?, section_statuses = ?, status = ?,
                   revision = COALESCE(revision, 0) + 1, data_bytes = ?,
                   has_slides = ?, has_maps = ?, updated_at = ?
               WHERE id = ?'''
        update_params = [title, draft_json, statuses_json, next_status, data_bytes,
                         has_slides, has_maps, now, existing['id']]
        if expected_revision is not None:
            update_sql += ' AND revision = ?'
            update_params.append(int(expected_revision))
        updated_row = conn.execute(update_sql, update_params)
        if expected_revision is not None and updated_row.rowcount != 1:
            current = conn.execute(
                'SELECT revision FROM project_drafts WHERE id = ?', (existing['id'],)
            ).fetchone()
            raise DraftRevisionConflict(
                existing['id'], int(expected_revision),
                int((current or {}).get('revision') or 0) if current else 0)
        if clear_approval:
            _clear_draft_approval_fields(conn, existing['id'])
        conn.commit()
        return draft_id

    statuses = section_statuses if isinstance(section_statuses, dict) else {}
    # A draft is born 'draft' — no save payload may create one already inside a
    # gate state; every state past it is earned through the lifecycle.
    conn.execute(
        '''INSERT INTO project_drafts
           (id, tenant_id, user_id, title, draft_data, section_statuses, status,
            revision, data_bytes, has_slides, has_maps, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (draft_id, tenant_id, user_id, title, draft_json, json.dumps(statuses, ensure_ascii=False),
         'draft', 1, data_bytes, has_slides, has_maps, now, now)
    )
    conn.commit()
    return draft_id


def find_draft_snapshots(tenant_id, draft_ids=None):
    """Snapshots of project data that survive an emptied draft, newest first.

    Every generated presentation stored the whole ``tenantProjectData`` of the moment, and it
    carries its own draft id, so a draft that lost its fields can be read back from here.

    When ``draft_ids`` is given, only presentations linked to those drafts are
    read and parsed, so a list screen showing a page of drafts does not pay for
    parsing every presentation payload of the tenant.
    """
    conn = get_db()
    wanted = None
    if draft_ids is not None:
        wanted = {str(d) for d in (draft_ids or []) if str(d or '').strip()}
        if not wanted:
            return []
        marks = ', '.join(['?'] * len(wanted))
        rows = conn.execute(
            '''SELECT id, title, draft_id, project_data, slide_count, created_at, updated_at
               FROM presentations WHERE tenant_id = ? AND draft_id IN (%s)
               ORDER BY created_at DESC''' % marks,
            [tenant_id] + sorted(wanted),
        ).fetchall()
        legacy = conn.execute(
            '''SELECT id, title, draft_id, project_data, slide_count, created_at, updated_at
               FROM presentations WHERE tenant_id = ? AND (draft_id IS NULL OR draft_id = '')
               ORDER BY created_at DESC''',
            (tenant_id,),
        ).fetchall()
        rows = list(rows) + [r for r in legacy if _snapshot_draft_id(r) in wanted]
        try:
            rows.sort(key=lambda r: str(r['created_at'] or ''), reverse=True)
        except Exception:
            pass
    else:
        rows = conn.execute(
            '''SELECT id, title, project_data, slide_count, created_at, updated_at
               FROM presentations WHERE tenant_id = ? ORDER BY created_at DESC''',
            (tenant_id,),
        ).fetchall()
    snapshots = []
    for row in rows:
        payload = _json_object(row['project_data'])
        if not payload:
            continue
        snapshots.append({
            'presentation_id': row['id'],
            'title': row['title'] or '',
            'draft_id': payload.get('draftId') or payload.get('draft_id') or '',
            'slide_count': row['slide_count'] or 0,
            'created_at': row['created_at'],
            'field_count': len(_draft_content_keys(payload)),
            'project_data': payload,
        })
    return snapshots


def _snapshot_draft_id(row):
    """Draft id carried by a presentation row, via column or legacy payload."""
    try:
        direct = (row['draft_id'] if 'draft_id' in row.keys() else '') or ''
    except Exception:
        direct = ''
    if direct:
        return str(direct)
    try:
        payload = _json_object(row['project_data'])
    except Exception:
        return ''
    return str(payload.get('draftId') or payload.get('draft_id') or '')


def get_draft_field_counts(tenant_id, draft_ids):
    """Filled-field counts for a page of drafts with one query and no hydration."""
    wanted = [str(d) for d in (draft_ids or []) if str(d or '').strip()][:200]
    if not wanted:
        return {}
    conn = get_db()
    marks = ', '.join(['?'] * len(wanted))
    counts = {}
    for row in conn.execute(
        'SELECT id, draft_data FROM project_drafts WHERE tenant_id = ? AND id IN (%s)' % marks,
        [tenant_id] + wanted,
    ).fetchall():
        try:
            payload = _json_object(row['draft_data'])
        except Exception:
            payload = {}
        counts[str(row['id'])] = len(_draft_content_keys(payload))
    return counts


def restore_draft_from_snapshot(tenant_id, draft_id, snapshot_data):
    """Fill a draft's missing fields from a snapshot without overwriting what it still holds."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ?', (draft_id, tenant_id)
    ).fetchone()
    if not row or not isinstance(snapshot_data, dict):
        return None
    current = _json_object(row['draft_data'])
    merged = dict(current)
    restored = []
    for key, value in snapshot_data.items():
        if key in ('draftId', 'draft_id'):
            continue
        if _has_content(current.get(key)) or not _has_content(value):
            continue
        merged[key] = value
        restored.append(key)
    if not restored:
        return []
    merged.pop('draftId', None)
    merged.pop('draft_id', None)
    draft_json = json.dumps(merged, ensure_ascii=False)
    title = str(merged.get('project_name') or merged.get('projectName')
                or row['title'] or 'مسودة مشروع بدون عنوان').strip()[:200]
    conn.execute(
        '''UPDATE project_drafts
           SET title = ?, draft_data = ?, data_bytes = ?,
               revision = COALESCE(revision, 0) + 1, updated_at = ?
           WHERE id = ?''',
        (title, draft_json, len(draft_json.encode('utf-8')), _utcnow().isoformat(), draft_id)
    )
    conn.commit()
    print(f'[DRAFT RESTORE] Draft {draft_id} regained {len(restored)} fields: {sorted(restored)[:12]}')
    return restored


def get_project_draft(tenant_id, user_id):
    """Get the latest unified draft for one tenant actor."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_drafts WHERE tenant_id = ? AND user_id = ? ORDER BY updated_at DESC LIMIT 1',
        (tenant_id, user_id)
    ).fetchone()
    return _hydrate_project_draft(row)


def get_all_project_draft_summaries(tenant_id, limit=50, offset=0, search='', status='', date_from='', date_to='', accessible_ids=None):
    """Return lightweight draft metadata without hydrating project payloads.

    ``accessible_ids`` scopes the list to the drafts a project-scoped user may
    see (t20); ``None`` keeps the tenant-wide listing."""
    conn = get_db()
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    clauses = ['tenant_id = ?']
    params = [tenant_id]
    if accessible_ids is not None:
        ids = [str(i) for i in accessible_ids]
        if not ids:
            return []
        clauses.append('id IN (' + ','.join('?' * len(ids)) + ')')
        params.extend(ids)
    if str(search or '').strip():
        clauses.append('LOWER(title) LIKE ?')
        params.append('%' + str(search).strip().lower() + '%')
    if status == 'draft':
        clauses.append("COALESCE(status, 'draft') NOT IN ('pending_approval', 'approved', 'sections_approved', 'final_approval_pending')")
    elif status in {'pending_approval', 'pending'}:
        clauses.append("status IN ('pending_approval', 'section_approval_pending', 'generation_approval_pending', 'final_approval_pending')")
    elif status == 'approved':
        clauses.append("status IN ('approved', 'sections_approved')")
    elif status in PROPOSAL_LIFECYCLE_STATES:
        clauses.append('status = ?')
        params.append(status)
    elif status:
        clauses.append('status = ?')
        params.append(status)
    if date_from:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) >= ?')
        params.append(str(date_from)[:10])
    if date_to:
        clauses.append('substr(COALESCE(updated_at, created_at), 1, 10) <= ?')
        params.append(str(date_to)[:10])
    params.extend([limit, offset])
    rows = conn.execute(
        '''SELECT id, tenant_id, user_id, title, section_statuses, status, revision,
                  data_bytes, has_slides, has_maps, requested_by, requested_by_name,
                  requested_at, reviewed_by, reviewed_by_name, review_note, reviewed_at,
                  created_at, updated_at
           FROM project_drafts
           WHERE ''' + ' AND '.join(clauses) + '''
           ORDER BY updated_at DESC
           LIMIT ? OFFSET ?''',
        params
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['section_statuses'] = _json_object(item.get('section_statuses'))
        item['title'] = item.get('title') or 'مسودة مشروع بدون عنوان'
        item['has_slides'] = bool(item.get('has_slides'))
        item['has_maps'] = bool(item.get('has_maps'))
        result.append(item)
    return result


def get_all_project_drafts(tenant_id):
    """Get all saved project drafts for a tenant, including full payloads."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM project_drafts WHERE tenant_id = ? ORDER BY updated_at DESC',
        (tenant_id,)
    ).fetchall()
    return [_hydrate_project_draft(row) for row in rows]


def get_project_draft_by_id(tenant_id, draft_id):
    """Fetch a draft for review while enforcing tenant isolation."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (draft_id, tenant_id)
    ).fetchone()
    return _hydrate_project_draft(row)


def delete_project_draft_by_id(tenant_id, draft_id):
    """Delete a specific project draft by ID."""
    conn = get_db()
    conn.execute('DELETE FROM project_drafts WHERE id = ? AND tenant_id = ?', (draft_id, tenant_id))
    conn.commit()
    return True


def get_pending_project_drafts(tenant_id, accessible_draft_ids=None):
    """Return only this tenant's drafts awaiting overall approval.

    ``accessible_draft_ids`` (ISS-014) keeps a project-scoped member's list
    inside their assigned drafts plus drafts they own."""
    conn = get_db()
    query = ("SELECT * FROM project_drafts WHERE tenant_id = ? AND status IN ('pending_approval', "
             "'section_approval_pending', 'generation_approval_pending', 'final_approval_pending')")
    params = [tenant_id]
    if accessible_draft_ids is not None:
        ids = [str(i) for i in accessible_draft_ids]
        if ids:
            query += ' AND id IN (' + ','.join('?' * len(ids)) + ')'
            params.extend(ids)
        else:
            query += ' AND 0'
    query += ' ORDER BY requested_at DESC'
    rows = conn.execute(query, params).fetchall()
    return [_hydrate_project_draft(row) for row in rows]


def delete_project_draft(tenant_id, user_id):
    """Delete a user's own draft from the current tenant."""
    conn = get_db()
    cursor = conn.execute(
        'DELETE FROM project_drafts WHERE tenant_id = ? AND user_id = ?',
        (tenant_id, user_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def update_draft_section_status(tenant_id, user_id, section_key, section_status, draft_id=None):
    """Update one section in a unified draft, resetting overall approval if needed."""
    return update_draft_section_statuses(tenant_id, user_id, {section_key: section_status}, draft_id=draft_id)


def update_draft_section_statuses(tenant_id, user_id, updates, draft_id=None):
    """Merge section statuses into a draft without losing a concurrent update.

    The whole statuses map lives in one JSON column, so eight parallel 'approve' calls each
    read the same snapshot and the last write won: the screen showed every section approved
    while the database had kept only some. The write is therefore conditional on the value
    that was read, and retried when another request got there first.
    """
    if not isinstance(updates, dict) or not updates:
        return False
    if any(status not in SECTION_DRAFT_STATUSES for status in updates.values()):
        return False
    conn = get_db()
    for attempt in range(6):
        draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
        # A named shared draft stays writable: the route already proved the
        # actor's scope, and vetoing by owner here turned a legal status
        # change into a phantom create that collided on the primary key.
        if not draft:
            # A status click can occur before the first explicit Save action.
            save_project_draft(tenant_id, user_id, {}, {}, 'draft', draft_id=draft_id)
            draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
            if not draft:
                return False
        norm_status = normalize_proposal_status(draft.get('status'))
        if proposal_status_is_locked(norm_status):
            raise DraftLocked(draft['id'], norm_status)
        statuses = dict(draft.get('section_statuses') or {})
        expected = json.dumps(statuses, ensure_ascii=False)
        changed = any(statuses.get(key) != value for key, value in updates.items())
        statuses.update(updates)
        # Toggling a section after the draft entered review or passed the section
        # gate voids that state; the draft goes back to sections being worked on.
        resets_approval = changed and norm_status in {
            'section_approval_pending', 'sections_approved', 'generated_draft'}
        next_status = 'sections_in_progress' if resets_approval else (draft.get('status') or 'draft')
        cursor = conn.execute(
            '''UPDATE project_drafts SET section_statuses = ?, status = ?, updated_at = ?
               WHERE id = ? AND COALESCE(section_statuses, '') IN (?, ?)''',
            (json.dumps(statuses, ensure_ascii=False), next_status, _utcnow().isoformat(),
             draft['id'], expected, '' if expected == '{}' else expected)
        )
        if getattr(cursor, 'rowcount', 1) == 0:
            conn.commit()
            continue
        if resets_approval:
            _clear_draft_approval_fields(conn, draft['id'])
        conn.commit()
        if resets_approval:
            try:
                record_audit_event(
                    tenant_id=tenant_id,
                    action='proposal_status_transition',
                    entity_type='project_draft',
                    entity_id=draft['id'],
                    user_id=user_id,
                    entity_name=draft.get('title') or 'مشروع',
                    old_value={'status': norm_status},
                    new_value={'status': 'sections_in_progress'},
                    metadata={
                        'from_status': norm_status,
                        'to_status': 'sections_in_progress',
                        'reason': 'تعديل حالة قسم أبطل حالة الاعتماد القائمة',
                    },
                    created_at=_utcnow().isoformat(),
                )
            except Exception:
                pass
        return True
    print(f'[DRAFT SECTIONS] gave up merging {list(updates)} after repeated concurrent writes')
    return False


def update_draft_section_status_by_id(tenant_id, draft_id, updates):
    """Merge section statuses into one draft by id without an owner check.

    Version decisions are recorded by an approver who may not own the draft,
    so the mirror write cannot require the actor to match the draft owner.
    Tenant isolation still applies. The concurrent-merge guard matches
    update_draft_section_statuses.
    """
    if not isinstance(updates, dict) or not updates:
        return False
    if any(status not in SECTION_DRAFT_STATUSES for status in updates.values()):
        return False
    if not draft_id:
        return False
    conn = get_db()
    for _attempt in range(6):
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if not draft:
            return False
        norm_status = normalize_proposal_status(draft.get('status'))
        if proposal_status_is_locked(norm_status):
            raise DraftLocked(draft['id'], norm_status)
        statuses = dict(draft.get('section_statuses') or {})
        expected = json.dumps(statuses, ensure_ascii=False)
        changed = any(statuses.get(key) != value for key, value in updates.items())
        statuses.update(updates)
        resets_approval = changed and norm_status in {
            'section_approval_pending', 'sections_approved', 'generated_draft'}
        next_status = 'sections_in_progress' if resets_approval else (draft.get('status') or 'draft')
        cursor = conn.execute(
            '''UPDATE project_drafts SET section_statuses = ?, status = ?, updated_at = ?
               WHERE id = ? AND tenant_id = ? AND COALESCE(section_statuses, '') IN (?, ?)''',
            (json.dumps(statuses, ensure_ascii=False), next_status, _utcnow().isoformat(),
             draft['id'], tenant_id, expected, '' if expected == '{}' else expected)
        )
        if getattr(cursor, 'rowcount', 1) == 0:
            conn.commit()
            continue
        if resets_approval:
            _clear_draft_approval_fields(conn, draft['id'])
        conn.commit()
        return True
    print(f'[DRAFT SECTIONS] gave up merging {list(updates)} by id after repeated concurrent writes')
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Section versions: immutable per-section snapshots tied to approval.
#
# Spec (Landloom analysis sections 6, 8.1, 19): every send for approval stores an
# independent copy of that section inputs under the next version number, and
# the approval decision names that number instead of the live values. Sections
# without any version keep the legacy toggle path, while a section that has a
# version must be approved through its snapshot.
# ─────────────────────────────────────────────────────────────────────────────

SECTION_VERSION_STATUSES = {'pending', 'approved', 'returned', 'rejected', 'superseded', 'cancelled'}
SECTION_VERSION_DECISIONS = {'approved', 'returned', 'rejected'}

BASE_SECTION_KEYS = {
    'basic', 'location', 'land_croquis', 'contact',
    'section-timeline', 'section-financial-calc', 'section-team',
    'section-market-study', 'section-visual-concept', 'section-executive-content',
}


def section_snapshot_hash(snapshot):
    """Stable sha256 over the canonical JSON of a section snapshot."""
    try:
        canonical = json.dumps(snapshot if isinstance(snapshot, dict) else {}, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        canonical = '{}'
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _known_section_keys(conn, tenant_id, draft_statuses=None):
    """Section keys a version may be opened for: base, custom and already stored."""
    keys = set(BASE_SECTION_KEYS)
    try:
        for row in conn.execute(
            'SELECT section_key FROM tenant_custom_sections WHERE tenant_id = ? AND is_active = 1',
            (tenant_id,),
        ).fetchall():
            if row['section_key']:
                keys.add(row['section_key'])
    except Exception:
        pass
    for key in (draft_statuses or {}):
        if key:
            keys.add(key)
    return keys


def _section_version_public(row, include_snapshot=False):
    item = dict(row)
    raw = item.pop('snapshot_data', None)
    if include_snapshot:
        try:
            item['snapshot'] = json.loads(raw or '{}')
        except (TypeError, ValueError):
            item['snapshot'] = {}
        if not isinstance(item.get('snapshot'), dict):
            item['snapshot'] = {}
    # d05: an approved version past its validity window is no longer a gate
    # the project can rely on — it must be sent and approved again.
    item['is_expired'] = False
    if item.get('status') == 'approved' and item.get('expires_at'):
        try:
            item['is_expired'] = datetime.fromisoformat(str(item['expires_at'])) < _utcnow()
        except (TypeError, ValueError):
            item['is_expired'] = False
    return item


def create_section_version(tenant_id, draft_id, section_key, snapshot, created_by, created_by_name,
                           allow_supersede=False):
    """Store an immutable snapshot as the next version of a draft section.

    A live pending version blocks a new send (t13-04) unless the caller
    explicitly supersedes it, so a request under review is never dropped
    silently. Returns the stored row metadata, or a dict with an error key
    when the draft or section is unknown.
    """
    if not isinstance(section_key, str) or not section_key.strip() or len(section_key) > 64:
        return {'error': 'unknown_section'}
    if not isinstance(snapshot, dict):
        return {'error': 'invalid_snapshot'}
    section_key = section_key.strip()
    conn = get_db()
    draft = conn.execute(
        'SELECT id, status, section_statuses FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (draft_id, tenant_id),
    ).fetchone()
    if not draft:
        return {'error': 'draft_not_found'}
    if proposal_status_is_locked(draft['status']):
        return {'error': 'draft_locked', 'status': normalize_proposal_status(draft['status'])}
    if section_key not in _known_section_keys(conn, tenant_id, _json_object(draft['section_statuses'])):
        return {'error': 'unknown_section'}
    pending = conn.execute(
        "SELECT id, version_number FROM section_versions "
        "WHERE draft_id = ? AND section_key = ? AND status = 'pending'",
        (draft_id, section_key),
    ).fetchone()
    if pending and not allow_supersede:
        return {'error': 'version_pending_exists', 'version_id': pending['id'],
                'version_number': pending['version_number']}
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    digest = section_snapshot_hash(snapshot)
    version_id = str(uuid.uuid4())
    now = _utcnow().isoformat()
    for _attempt in range(3):
        current = conn.execute(
            'SELECT COALESCE(MAX(version_number), 0) AS top FROM section_versions WHERE draft_id = ? AND section_key = ?',
            (draft_id, section_key),
        ).fetchone()
        next_number = int((current['top'] if current else 0) or 0) + 1
        try:
            conn.execute(
                'UPDATE section_versions SET status = ? WHERE draft_id = ? AND section_key = ? AND status = ?',
                ('superseded', draft_id, section_key, 'pending'),
            )
            conn.execute(
                '''INSERT INTO section_versions
                   (id, tenant_id, draft_id, section_key, version_number, snapshot_data,
                    snapshot_hash, status, created_by, created_by_name, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (version_id, tenant_id, draft_id, section_key, next_number, snapshot_json,
                 digest, 'pending', created_by, created_by_name, now),
            )
            conn.commit()
            break
        except Exception:
            conn.rollback()
    else:
        return {'error': 'version_conflict'}
    row = conn.execute('SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()
    if not row:
        return {'error': 'version_conflict'}
    try:
        update_draft_section_status_by_id(tenant_id, draft_id, {section_key: 'pending'})
    except Exception:
        pass
    try:
        draft_row = get_project_draft_by_id(tenant_id, draft_id)
        if draft_row:
            curr_status = normalize_proposal_status(draft_row.get('status'))
            if curr_status in {'draft', 'sections_in_progress', 'rejected_for_revision'}:
                transition_project_draft_status(
                    tenant_id, draft_id, 'section_approval_pending',
                    actor_id=created_by, actor_name=created_by_name,
                    reason=f'إرسال قسم {section_key} للاعتماد',
                )
    except Exception:
        pass
    return _section_version_public(row)


def list_section_versions(tenant_id, draft_id, section_key=None):
    """Newest-first version metadata for a draft, without snapshot payloads."""
    conn = get_db()
    if section_key:
        rows = conn.execute(
            '''SELECT * FROM section_versions WHERE tenant_id = ? AND draft_id = ? AND section_key = ?
               ORDER BY version_number DESC''',
            (tenant_id, draft_id, section_key),
        ).fetchall()
    else:
        rows = conn.execute(
            '''SELECT * FROM section_versions WHERE tenant_id = ? AND draft_id = ?
               ORDER BY section_key ASC, version_number DESC''',
            (tenant_id, draft_id),
        ).fetchall()
    return [_section_version_public(row) for row in rows]


def get_section_version(tenant_id, version_id, include_snapshot=True):
    """One tenant-scoped version, with its immutable snapshot on request."""
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM section_versions WHERE id = ? AND tenant_id = ?', (version_id, tenant_id)
    ).fetchone()
    return _section_version_public(row, include_snapshot=include_snapshot) if row else None


def section_versions_overview(tenant_id, draft_id):
    """Latest version per section: number, status and hash for gates and locks."""
    overview = {}
    for item in list_section_versions(tenant_id, draft_id):
        if item['section_key'] not in overview:
            overview[item['section_key']] = item
    return overview


def pending_section_versions(tenant_id, draft_id, section_keys):
    """Subset of the given sections that currently await a version decision."""
    wanted = [key for key in (section_keys or []) if isinstance(key, str) and key]
    if not wanted:
        return []
    overview = section_versions_overview(tenant_id, draft_id)
    return [key for key in wanted if (overview.get(key) or {}).get('status') == 'pending']


SECTION_APPROVAL_DEFAULT_DAYS = int(os.environ.get('SECTION_APPROVAL_DAYS', '30'))


def get_section_approval_validity_days(tenant_id):
    """d05: how long a decided section approval stays valid before re-review.

    The tenant sets the window through ``section_approval_days`` in branding;
    missing or non-positive values fall back to the platform default so the
    expiry rule can never be switched off by accident.
    """
    try:
        branding = get_branding(tenant_id) or {}
        raw = branding.get('section_approval_days')
        days = int(raw) if raw not in (None, '') else SECTION_APPROVAL_DEFAULT_DAYS
        return days if days > 0 else SECTION_APPROVAL_DEFAULT_DAYS
    except Exception:
        return SECTION_APPROVAL_DEFAULT_DAYS


def expired_approved_sections(tenant_id, draft_id):
    """Sections whose latest approved version passed its validity window."""
    overview = section_versions_overview(tenant_id, draft_id)
    return [key for key, meta in overview.items()
            if meta.get('status') == 'approved' and meta.get('is_expired')]


GENERATION_INPUT_EXCLUDED_KEYS = {
    # Generation outputs and run state — never part of the priced inputs.
    'tenantSlidesData', 'tenantSlidePlan', 'slide_generation_checkpoint',
    'tenantCreativeImages', 'pageDrafts', 'landmarks_matrix',
    'landmark_map_items', 'landmark_label_positions', 'access_road_label_positions',
    'access_road_label_sizes', 'catchment_label_positions',
    # Working/chat state that does not feed the generation prompts.
    'designerChat', 'designerChatSessions', 'chatHistory', 'draftHistory',
    'tenantArchiveCache',
    # Identity/bookkeeping fields the client round-trips.
    'draftId', 'draft_id', 'schema_version', 'sectionStatuses',
    # Transient UI state, view parameters and client-side mirrors.
    'projectName', 'map_styles', 'map_type', 'main_roads_data',
    'city_landmarks_data', 'nearby_landmarks_data',
    'visual_style_reference_file_ids', 'visual_style_reference_file_id',
    'site_analysis_approved', 'location_analysis_approved', 'croquis_approved',
    'location_coordinates_confirmed', 'land_use_status',
    'land_documents_analysis_status', 'calculate_landmark_driving',
    'presentation_scope', 'presentationId', 'presentationTitle',
    'location_coordinates_source', 'financial_calc_data',
}


_GENERATION_MEDIA_URL_RE = re.compile(
    r"(?:[a-zA-Z][a-zA-Z0-9+.-]*://|//|(?<![\w/.:])/uploads/)[^\s<>'\"`\\),\]\[]+")
_GENERATION_MEDIA_FETCH_KEYS = {'s', 't', 'v', 'cb'}


def normalize_generation_input(value):
    if isinstance(value, dict):
        return {key: normalize_generation_input(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_generation_input(item) for item in value]
    if not isinstance(value, str) or '/uploads/' not in value:
        return value

    def normalize_url(match):
        if not match.group(0).startswith('/uploads/'):
            return match.group(0)
        url = re.sub(r'&(?:amp|#0*38|#x0*26);', '&', match.group(0), flags=re.IGNORECASE)
        base, fragment_sep, fragment = url.partition('#')
        path, query_sep, query = base.partition('?')
        if not query_sep:
            return match.group(0)
        kept = [part for part in re.split(r'&|;(?=s=)', query)
                if part and part.split('=', 1)[0] not in _GENERATION_MEDIA_FETCH_KEYS]
        return path + ('?' + '&'.join(kept) if kept else '') + fragment_sep + fragment

    return _GENERATION_MEDIA_URL_RE.sub(normalize_url, value)


def draft_generation_input_hash(draft_data):
    """Stable hash over a draft's generation inputs — outputs excluded.

    Slide data, the plan and checkpoints are written by the run itself, so
    hashing them in would make the approved snapshot drift mid-run while the
    real inputs stay untouched.
    """
    data = draft_data if isinstance(draft_data, dict) else {}
    inputs = {key: value for key, value in data.items()
              if key not in GENERATION_INPUT_EXCLUDED_KEYS}
    return section_snapshot_hash(normalize_generation_input(inputs))


def _presentation_review_hash(presentation):
    """Semantic hash of what the final approver reviews: slides + project data."""
    slides = presentation.get('slides_data')
    if isinstance(slides, str):
        try:
            slides = json.loads(slides)
        except (TypeError, ValueError):
            slides = None
    project = presentation.get('project_data')
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (TypeError, ValueError):
            project = None
    try:
        canonical = json.dumps({'slides': slides, 'project': project},
                               sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        canonical = '{}'
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def decide_section_version(tenant_id, version_id, decision, decided_by, decided_by_name, note=None):
    """Record an approval decision against one immutable version.

    Only a pending version can be decided. A return or rejection needs a reason,
    because the editor must know what to fix before the next send.
    """
    if decision not in SECTION_VERSION_DECISIONS:
        return {'error': 'invalid_decision'}
    clean_note = str(note or '').strip()
    if decision in {'returned', 'rejected'} and not clean_note:
        return {'error': 'note_required'}
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM section_versions WHERE id = ? AND tenant_id = ?', (version_id, tenant_id)
    ).fetchone()
    if not row:
        return {'error': 'version_not_found'}
    if row['status'] != 'pending':
        return {'error': 'version_not_pending'}
    draft_row = conn.execute(
        'SELECT status FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (row['draft_id'], tenant_id),
    ).fetchone()
    if draft_row and proposal_status_is_locked(draft_row['status']):
        return {'error': 'draft_locked', 'status': normalize_proposal_status(draft_row['status'])}

    is_self_approval = bool(row['created_by'] and decided_by and str(row['created_by']) == str(decided_by))
    if is_self_approval:
        # d01: self-approval of one's own section is a tenant policy — the
        # default 'allow' records it with an audit note; 'block' refuses it.
        policy = get_tenant_policy(tenant_id, 'section_self_approval', 'allow')
        if policy == 'block':
            return {'error': 'self_approval_blocked_by_policy'}

    expires_at = None
    if decision == 'approved':
        # d05: an approval is valid for a bounded window; after it the section
        # has to be sent and decided again before the file can move forward.
        expires_at = (_utcnow() + timedelta(
            days=get_section_approval_validity_days(tenant_id))).isoformat()
    # ISS-028: the decide itself is the atomic claim — a competing decision
    # committed between the read above and this write turns it into a no-op
    # instead of silently overwriting the first decision.
    updated_row = conn.execute(
        '''UPDATE section_versions SET status = ?, decided_by = ?, decided_by_name = ?,
           decision_note = ?, decided_at = ?, expires_at = ?
           WHERE id = ? AND status = 'pending' ''',
        (decision, decided_by, decided_by_name, clean_note or None,
         _utcnow().isoformat(), expires_at, version_id),
    )
    if updated_row.rowcount != 1:
        return {'error': 'version_not_pending'}
    conn.commit()
    updated = conn.execute('SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()
    res = _section_version_public(updated)
    if is_self_approval:
        res['is_self_approval'] = True

    draft_id = row['draft_id']
    section_key = row['section_key']
    try:
        mirror = 'approved' if decision == 'approved' else 'draft'
        update_draft_section_status_by_id(tenant_id, draft_id, {section_key: mirror})
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if draft:
            if decision == 'approved':
                statuses = draft.get('section_statuses') or {}
                if statuses and all(v == 'approved' for v in statuses.values()):
                    transition_project_draft_status(
                        tenant_id, draft_id, 'sections_approved',
                        actor_id=decided_by, actor_name=decided_by_name,
                        reason='اعتماد جميع أقسام العرض',
                    )
            elif decision in {'returned', 'rejected'}:
                transition_project_draft_status(
                    tenant_id, draft_id, 'rejected_for_revision',
                    actor_id=decided_by, actor_name=decided_by_name,
                    reason=clean_note or f'إعادة قسم {section_key} للتعديل',
                )
    except Exception:
        pass

    return res


def cancel_section_version(tenant_id, version_id, cancelled_by, cancelled_by_name):
    """Withdraw a pending send so the editor can keep working on a later draft.

    Only a pending version can be cancelled. The row stays in history with
    status cancelled and the actor who withdrew it, so the request does not
    vanish without a trace.
    """
    conn = get_db()
    row = conn.execute(
        'SELECT * FROM section_versions WHERE id = ? AND tenant_id = ?', (version_id, tenant_id)
    ).fetchone()
    if not row:
        return {'error': 'version_not_found'}
    if row['status'] != 'pending':
        return {'error': 'version_not_pending'}
    draft_row = conn.execute(
        'SELECT status FROM project_drafts WHERE id = ? AND tenant_id = ?',
        (row['draft_id'], tenant_id),
    ).fetchone()
    if draft_row and proposal_status_is_locked(draft_row['status']):
        return {'error': 'draft_locked', 'status': normalize_proposal_status(draft_row['status'])}
    conn.execute(
        '''UPDATE section_versions SET status = ?, decided_by = ?, decided_by_name = ?,
           decided_at = ? WHERE id = ?''',
        ('cancelled', cancelled_by, cancelled_by_name,
         _utcnow().isoformat(), version_id),
    )
    conn.commit()
    updated = conn.execute('SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()

    draft_id = row['draft_id']
    section_key = row['section_key']
    try:
        update_draft_section_status_by_id(tenant_id, draft_id, {section_key: 'draft'})
        draft = get_project_draft_by_id(tenant_id, draft_id)
        if draft:
            curr = normalize_proposal_status(draft.get('status'))
            if curr == 'section_approval_pending':
                overview = section_versions_overview(tenant_id, draft_id)
                has_pending = any(v.get('status') == 'pending' for v in overview.values())
                if not has_pending:
                    transition_project_draft_status(
                        tenant_id, draft_id, 'sections_in_progress',
                        actor_id=cancelled_by, actor_name=cancelled_by_name,
                        reason=f'إلغاء طلب اعتماد قسم {section_key}',
                    )
    except Exception:
        pass

    return _section_version_public(updated)


def diff_section_versions(tenant_id, version_id, base_version_id=None):
    """Structured comparison between a target section version and a base version.

    If base_version_id is not specified, compares against the immediately preceding
    version number for the same section. If no previous version exists, compares against empty.
    Returns categorized fields, attachments, validation readiness, and change counters.
    """
    target = get_section_version(tenant_id, version_id, include_snapshot=True)
    if not target:
        return {'error': 'version_not_found'}

    conn = get_db()
    draft_id = target['draft_id']
    section_key = target['section_key']

    if base_version_id:
        base = get_section_version(tenant_id, base_version_id, include_snapshot=True)
        if not base or base.get('draft_id') != draft_id or base.get('section_key') != section_key:
            return {'error': 'base_version_not_found'}
        base_snapshot = base.get('snapshot') or {}
        base_version_number = base.get('version_number')
        base_created_at = base.get('created_at')
    else:
        prev_row = conn.execute(
            '''SELECT * FROM section_versions
               WHERE tenant_id = ? AND draft_id = ? AND section_key = ? AND version_number < ?
               ORDER BY version_number DESC LIMIT 1''',
            (tenant_id, draft_id, section_key, target['version_number']),
        ).fetchone()
        if prev_row:
            prev = _section_version_public(prev_row, include_snapshot=True)
            base_version_id = prev['id']
            base_version_number = prev['version_number']
            base_created_at = prev.get('created_at')
            base_snapshot = prev.get('snapshot') or {}
        else:
            base_version_id = None
            base_version_number = None
            base_created_at = None
            base_snapshot = {}

    target_snapshot = target.get('snapshot') or {}

    field_labels = {}
    for f in PREBUILT_FIELDS:
        field_labels[f['key']] = f.get('label') or f['key']
    try:
        for f in get_fields(tenant_id):
            if f.get('field_key'):
                field_labels[f['field_key']] = f.get('field_label') or f['field_key']
    except Exception:
        pass

    known_labels = {
        'timeline_table_data': 'الجدول الزمني ومراحل المشروع',
        'timeline_start_date': 'تاريخ بداية المشروع',
        'timeline_start_year': 'سنة بداية المشروع',
        'timeline_years': 'عدد سنوات المشروع',
        'financial_study_model': 'الدراسة المالية والمؤشرات',
        'team_selection': 'فريق العمل والجهات المشاركة',
        'market_study_data': 'دراسة السوق وتحليل المنافسين',
        'visual_concept': 'التصور البصري والمخططات',
        'executive_content': 'المحتوى التنفيذي والملخص',
        'location_analysis_approved': 'اعتماد تحليل الموقع',
        'location_data_fetched_at': 'تاريخ جلب بيانات الموقع',
        'location_polygon_source': 'مصدر مضلع الموقع',
        'map_approvals': 'اعتمادات الخرائط',
        'land_documents_files': 'وثائق ومستندات الأرض',
        'land_photos': 'صور الأرض والموقع',
        'project_logo': 'شعار المشروع',
    }
    field_labels.update(known_labels)

    def _val_eq(v1, v2):
        if v1 == v2:
            return True
        try:
            return json.dumps(v1, ensure_ascii=False, sort_keys=True) == json.dumps(v2, ensure_ascii=False, sort_keys=True)
        except Exception:
            return False

    def _val_has_content(v):
        if v is None or v is False:
            return False
        if isinstance(v, str):
            return bool(v.strip())
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, dict):
            return any(_val_has_content(item) for item in v.values())
        if isinstance(v, (list, tuple, set)):
            return any(_val_has_content(item) for item in v)
        return True

    all_keys = sorted(set(target_snapshot.keys()) | set(base_snapshot.keys()))
    attachment_keys = {'land_documents_files', 'land_photos', 'project_logo', 'deed_file', 'croquis_file'}

    fields = []
    attachments = []
    modified_count = 0
    added_count = 0
    removed_count = 0
    unchanged_count = 0

    for key in all_keys:
        old_val = base_snapshot.get(key)
        new_val = target_snapshot.get(key)
        in_base = key in base_snapshot
        in_target = key in target_snapshot

        if not in_base and in_target:
            c_status = 'added'
            added_count += 1
        elif in_base and not in_target:
            c_status = 'removed'
            removed_count += 1
        elif _val_eq(old_val, new_val):
            c_status = 'unchanged'
            unchanged_count += 1
        else:
            c_status = 'modified'
            modified_count += 1

        label = field_labels.get(key) or key
        item = {
            'key': key,
            'label': label,
            'old_value': old_val,
            'new_value': new_val,
            'status': c_status,
        }
        if key in attachment_keys or 'file' in key or 'photo' in key:
            attachments.append(item)
        else:
            fields.append(item)

    missing_required = []
    for f in PREBUILT_FIELDS:
        if f.get('section_key') == section_key and f.get('required'):
            if not _val_has_content(target_snapshot.get(f['key'])):
                missing_required.append(f.get('label') or f['key'])
    try:
        for f in get_fields(tenant_id):
            if (f.get('section_key') or '') == section_key and f.get('is_required') and f.get('is_active', 1):
                fk = f.get('field_key')
                if fk and not _val_has_content(target_snapshot.get(fk)):
                    lbl = f.get('field_label') or fk
                    if lbl not in missing_required:
                        missing_required.append(lbl)
    except Exception:
        pass

    return {
        'version_id': target['id'],
        'draft_id': draft_id,
        'section_key': section_key,
        'version_number': target['version_number'],
        'status': target['status'],
        'created_at': target['created_at'],
        'created_by': target['created_by'],
        'created_by_name': target['created_by_name'],
        'decided_at': target.get('decided_at'),
        'decided_by': target.get('decided_by'),
        'decided_by_name': target.get('decided_by_name'),
        'decision_note': target.get('decision_note'),
        'is_self_approval': bool(target.get('created_by') and target.get('decided_by') and str(target['created_by']) == str(target['decided_by'])),
        'base_version_id': base_version_id,
        'base_version_number': base_version_number,
        'base_created_at': base_created_at,
        'summary': {
            'total_changes': modified_count + added_count + removed_count,
            'modified': modified_count,
            'added': added_count,
            'removed': removed_count,
            'unchanged': unchanged_count,
        },
        'fields': fields,
        'attachments': attachments,
        'validation': {
            'is_complete': len(missing_required) == 0,
            'missing_fields': missing_required,
        },
    }


def request_project_draft_approval(tenant_id, user_id, requested_by, requested_by_name, draft_id=None):
    """Submit a draft only after every tracked section is approved."""
    draft = get_project_draft_by_id(tenant_id, draft_id) if draft_id else get_project_draft(tenant_id, user_id)
    if draft and draft.get('user_id') != user_id:
        draft = None
    if not draft:
        return {'error': 'draft_not_found'}
    norm = normalize_proposal_status(draft.get('status'))
    if proposal_status_is_locked(norm):
        return {'error': 'draft_locked', 'status': norm}
    if norm == 'sections_approved':
        # Already past the section gate — asking again is a no-op success so a
        # client that re-submits after fixing staleness still lands cleanly.
        return get_project_draft_by_id(tenant_id, draft['id'])
    if norm not in {'draft', 'sections_in_progress', 'rejected_for_revision', 'section_approval_pending'}:
        # A draft already past the section gate cannot be re-submitted through it.
        return {'error': 'invalid_transition', 'current_status': norm}
    statuses = draft.get('section_statuses', {})
    if not statuses or any(value != 'approved' for value in statuses.values()):
        return {'error': 'sections_not_approved', 'section_statuses': statuses}
    expired = expired_approved_sections(tenant_id, draft['id'])
    if expired:
        return {'error': 'section_version_expired', 'sections': expired}
    conn = get_db()
    conn.execute(
        '''UPDATE project_drafts SET requested_by = ?, requested_by_name = ?,
           requested_at = ?, reviewed_by = NULL,
           reviewed_by_name = NULL, review_note = NULL, reviewed_at = NULL, updated_at = ?
           WHERE id = ? AND tenant_id = ?''',
        (requested_by, requested_by_name, _utcnow().isoformat(), _utcnow().isoformat(),
         draft['id'], tenant_id)
    )
    conn.commit()
    if norm != 'section_approval_pending':
        # Canonical state + audit event + presentation sync all come from the
        # transition authority; 'pending_approval' remains a readable alias.
        res = transition_project_draft_status(
            tenant_id, draft['id'], 'section_approval_pending',
            actor_id=requested_by, actor_name=requested_by_name,
            reason='طلب اعتماد المشروع',
        )
        if res.get('error'):
            return res
    return get_project_draft_by_id(tenant_id, draft['id'])


def review_project_draft(tenant_id, draft_id, review_status, reviewed_by, reviewed_by_name, note=None):
    """Record a tenant-scoped approval or return a draft for correction.

    Approval lands on the canonical ``sections_approved`` state — the draft passed
    the section gate and may now request generation. Returning for correction only
    makes sense for a pending request and requires a reason, matching the
    lifecycle rule for ``rejected_for_revision``.
    """
    if review_status not in {'approved', 'rejected'}:
        return {'error': 'invalid_status'}
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return {'error': 'draft_not_found'}
    norm = normalize_proposal_status(draft.get('status'))
    if review_status == 'approved':
        if norm not in {'draft', 'sections_in_progress', 'section_approval_pending'}:
            return {'error': 'draft_not_reviewable', 'status': norm}
        # The project-level approve cannot stand in for missing section
        # approvals — every tracked section must hold a valid approval first.
        statuses = draft.get('section_statuses') or {}
        if statuses and any(value != 'approved' for value in statuses.values()):
            return {'error': 'sections_not_approved', 'section_statuses': statuses}
        expired = expired_approved_sections(tenant_id, draft_id)
        if expired:
            return {'error': 'section_version_expired', 'sections': expired}
        target = 'sections_approved'
    else:
        if norm != 'section_approval_pending':
            return {'error': 'draft_not_pending', 'status': norm}
        if not str(note or '').strip():
            return {'error': 'reason_required'}
        target = 'rejected_for_revision'
    res = transition_project_draft_status(
        tenant_id, draft_id, target,
        actor_id=reviewed_by, actor_name=reviewed_by_name,
        reason=str(note or '').strip() or ('اعتماد المشروع' if review_status == 'approved' else None),
    )
    if res.get('error'):
        return res
    conn = get_db()
    conn.execute(
        '''UPDATE project_drafts SET reviewed_by = ?, reviewed_by_name = ?,
           review_note = ?, reviewed_at = ?, updated_at = ? WHERE id = ?''',
        (reviewed_by, reviewed_by_name, note, _utcnow().isoformat(),
         _utcnow().isoformat(), draft_id)
    )
    conn.commit()
    return {'success': True, 'draft': res.get('draft')}


def transition_project_draft_status(tenant_id, draft_id, target_status,
                                    actor_id=None, actor_name=None,
                                    actor_role=None, reason=None, metadata=None,
                                    manual=False):
    """Transition a project draft through the 11-state lifecycle with validation and immutable audit logging."""
    if not tenant_id or not draft_id or not target_status:
        return {'error': 'missing_arguments'}
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return {'error': 'draft_not_found'}

    current_status = draft.get('status') or 'draft'
    norm_current = normalize_proposal_status(current_status)
    norm_target = normalize_proposal_status(target_status)

    if not can_transition_proposal_status(norm_current, norm_target):
        return {
            'error': 'invalid_transition',
            'current_status': norm_current,
            'target_status': norm_target,
            'allowed_transitions': sorted(list(PROPOSAL_ALLOWED_TRANSITIONS.get(norm_current, []))),
        }

    if manual and norm_target not in PROPOSAL_MANUAL_TRANSITIONS.get(norm_current, set()):
        # A user may never hand-move a draft into a gate state; those belong to
        # the approval workflows that guard them.
        return {
            'error': 'manual_transition_not_allowed',
            'current_status': norm_current,
            'target_status': norm_target,
        }

    # Spec Section 8.4: Reopening an approved proposal requires a mandatory reason
    if norm_current == 'approved' and norm_target != 'archived':
        if not reason or not str(reason).strip():
            return {'error': 'reason_required', 'message': 'سبب التعديل بعد التعميد إلزامي'}

    # Spec Section 8.1 & 7: Rejection/Returning for revision requires a mandatory reason
    if norm_target == 'rejected_for_revision':
        if not reason or not str(reason).strip():
            return {'error': 'reason_required', 'message': 'سبب إعادة العرض للتعديل إلزامي'}

    now_iso = _utcnow().isoformat()
    conn = get_db()
    conn.execute(
        '''UPDATE project_drafts SET status = ?, updated_at = ? WHERE id = ? AND tenant_id = ?''',
        (norm_target, now_iso, draft_id, tenant_id)
    )
    # Also sync associated presentation status if any
    try:
        conn.execute(
            '''UPDATE presentations SET status = ?, updated_at = ?
               WHERE tenant_id = ? AND (draft_id = ? OR json_extract(project_data, '$.draftId') = ?)''',
            (norm_target, now_iso, tenant_id, draft_id, draft_id)
        )
    except Exception:
        pass
    # t18: archiving stamps the retention clock; restoring clears it.
    try:
        if norm_target == 'archived':
            conn.execute('UPDATE project_drafts SET archived_at = ? WHERE id = ?', (now_iso, draft_id))
            conn.execute(
                '''UPDATE presentations SET archived_at = ?
                   WHERE tenant_id = ? AND (draft_id = ? OR json_extract(project_data, '$.draftId') = ?)''',
                (now_iso, tenant_id, draft_id, draft_id)
            )
        elif norm_current == 'archived':
            conn.execute('UPDATE project_drafts SET archived_at = NULL WHERE id = ?', (draft_id,))
            conn.execute(
                '''UPDATE presentations SET archived_at = NULL
                   WHERE tenant_id = ? AND (draft_id = ? OR json_extract(project_data, '$.draftId') = ?)''',
                (tenant_id, draft_id, draft_id)
            )
    except Exception:
        pass
    # Leaving a gate state voids the request that put the draft there: a still-pending
    # approval would otherwise stay open and could later decide on a stale state.
    try:
        if norm_current == 'generation_approval_pending' and norm_target != 'generating':
            conn.execute(
                '''UPDATE generation_approvals SET status = 'cancelled', decision_note = ?
                   WHERE tenant_id = ? AND draft_id = ? AND status = 'pending' ''',
                ('أُلغي تلقائيًا عند مغادرة حالة انتظار اعتماد التوليد', tenant_id, draft_id),
            )
        if norm_current == 'final_approval_pending' and norm_target != 'approved':
            conn.execute(
                '''UPDATE final_file_approvals SET status = 'cancelled', decision_note = ?
                   WHERE tenant_id = ? AND status = 'pending' AND presentation_id IN (
                       SELECT id FROM presentations WHERE tenant_id = ? AND draft_id = ?)''',
                ('أُلغي تلقائيًا عند مغادرة حالة انتظار اعتماد الملف النهائي', tenant_id, tenant_id, draft_id),
            )
        if norm_current == 'generating' and norm_target != 'generated_draft':
            # Abandoning a run refunds its escrowed hold and closes the
            # approval it belonged to — never a bare status flip.
            stale = conn.execute(
                """SELECT * FROM point_reservations
                   WHERE tenant_id = ? AND status = 'reserved' AND draft_id = ?""",
                (tenant_id, draft_id),
            ).fetchall()
            for stale_row in stale:
                _settle_reservation_tx(
                    conn, tenant_id, stale_row, 'released', settled_by=actor_id,
                    note='تحرير تلقائي عند مغادرة حالة التوليد')
                if stale_row['generation_approval_id']:
                    conn.execute(
                        """UPDATE generation_approvals SET status = 'rejected', decision_note = ?
                           WHERE id = ? AND status = 'approved'""",
                        ('أُلغي عند مغادرة المسودة حالة التوليد', stale_row['generation_approval_id']),
                    )
    except Exception:
        pass
    conn.commit()

    # Record immutable audit event (T11 integration)
    event_meta = dict(metadata or {})
    if reason:
        event_meta['reason'] = str(reason).strip()
    event_meta['from_status'] = norm_current
    event_meta['to_status'] = norm_target

    try:
        record_audit_event(
            tenant_id=tenant_id,
            action='proposal_status_transition',
            entity_type='project_draft',
            entity_id=draft_id,
            user_id=actor_id,
            user_name=actor_name,
            user_role=actor_role,
            entity_name=draft.get('title') or 'مشروع',
            old_value={'status': norm_current},
            new_value={'status': norm_target, 'reason': reason},
            metadata=event_meta,
            created_at=now_iso,
        )
    except Exception as e:
        print(f'[AUDIT LOG] Warning: failed to log status transition: {e}')

    updated_draft = get_project_draft_by_id(tenant_id, draft_id)
    return {
        'success': True,
        'draft': updated_draft,
        'previous_status': norm_current,
        'current_status': norm_target,
        'state_info': PROPOSAL_LIFECYCLE_STATES.get(norm_target),
    }


def get_proposal_lifecycle_info(tenant_id, draft_id):
    """Return current state metadata, allowed next transitions, and transition history for a draft."""
    draft = get_project_draft_by_id(tenant_id, draft_id)
    if not draft:
        return None
    raw_status = draft.get('status') or 'draft'
    norm_status = normalize_proposal_status(raw_status)
    state_info = PROPOSAL_LIFECYCLE_STATES.get(norm_status, PROPOSAL_LIFECYCLE_STATES['draft'])
    allowed_keys = sorted(list(PROPOSAL_ALLOWED_TRANSITIONS.get(norm_status, set())))
    next_states = [
        {
            'status': k,
            'label': PROPOSAL_LIFECYCLE_STATES[k]['label'],
            'label_en': PROPOSAL_LIFECYCLE_STATES[k]['label_en'],
            'phase': PROPOSAL_LIFECYCLE_STATES[k]['phase'],
            'description': PROPOSAL_LIFECYCLE_STATES[k]['description'],
            'is_locked': PROPOSAL_LIFECYCLE_STATES[k]['is_locked'],
        }
        for k in allowed_keys if k in PROPOSAL_LIFECYCLE_STATES
    ]

    # Retrieve recent transitions from audit_events
    history = []
    try:
        audit_res = list_audit_events(
            tenant_id=tenant_id,
            entity_type='project_draft',
            entity_id=draft_id,
            action='proposal_status_transition',
            limit=20,
        )
        for ev in audit_res.get('events', []):
            history.append({
                'id': ev.get('id'),
                'created_at': ev.get('created_at'),
                'user_id': ev.get('user_id'),
                'user_name': ev.get('user_name'),
                'user_role': ev.get('user_role'),
                'from_status': (ev.get('old_value') or {}).get('status') if isinstance(ev.get('old_value'), dict) else None,
                'to_status': (ev.get('new_value') or {}).get('status') if isinstance(ev.get('new_value'), dict) else None,
                'reason': (ev.get('metadata') or {}).get('reason'),
            })
    except Exception:
        history = []

    return {
        'draft_id': draft_id,
        'title': draft.get('title') or 'مشروع بدون عنوان',
        'current_status': norm_status,
        'state_info': state_info,
        'is_locked': state_info.get('is_locked', False),
        'allowed_transitions': allowed_keys,
        'next_states': next_states,
        'history': history,
    }



def log_ai_rule_change(tenant_id, rule_category, rule_key, old_value, new_value,
                       risk_level='green', user_id=None, user_name=None):
    """Log a change to AI rules for audit and rollback."""
    conn = get_db()
    log_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO ai_rules_log
           (id, tenant_id, user_id, user_name, rule_category, rule_key, old_value, new_value, risk_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (log_id, tenant_id, user_id, user_name, rule_category, rule_key,
         str(old_value) if old_value is not None else None,
         str(new_value) if new_value is not None else None, risk_level)
    )
    conn.commit()
    return log_id


def get_ai_rules_log(tenant_id, limit=50):
    """Get recent AI rule changes for a tenant."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM ai_rules_log WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?',
        (tenant_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def log_agent_chat(tenant_id, user_id, user_name, message, reply, actions):
    """Persist one training-chat turn so the super admin can review what a
    company asked the agent and what the agent answered/did."""
    conn = get_db()
    log_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO agent_chat_log
           (id, tenant_id, user_id, user_name, message, reply, actions_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (log_id, tenant_id, user_id, user_name,
         str(message or '')[:4000], str(reply or '')[:4000],
         json.dumps(actions or [], ensure_ascii=False)[:8000])
    )
    conn.commit()
    return log_id


def get_agent_chat_log(tenant_id, limit=100):
    """Recent stored training-chat turns for a tenant, newest first."""
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM agent_chat_log WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?',
        (tenant_id, max(1, min(int(limit or 100), 500)))
    ).fetchall()
    return [dict(r) for r in rows]
