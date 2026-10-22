"""Draft branches — parallel work on one project file, merged like git.

A branch is a FORKED COPY of the project file: its own draft row that starts
from the version the person opened. Work on the branch never touches the main
line, so two people can work on the same file at the same time and neither
loses the other's work. The main line keeps its own commits; the branch keeps
its own, because it is a draft row like any other.

Merging is a three-way merge over the payload keys, the way git merges
branches:

* a key only the branch changed is taken,
* a key only the main line changed stays,
* a key both sides changed differently is a CONFLICT, and the person picks
  the side that survives.

The merge itself is written through the ordinary save path, so the main line
gains a new commit (kind 'merge') and the history stays intact on both sides.
"""


class _Absent:
    """Marker for a key that does not exist in one of the three payloads."""

    def __repr__(self):  # pragma: no cover - debugging helper
        return '<absent>'


_ABSENT = _Absent()
DRAFT_BRANCH_MERGE_COMMIT_MESSAGE = 'دمج فرع'


def _branch_value(value):
    """A payload value as JSON: absent keys read as None with a flag."""
    return None if value is _ABSENT else value


def draft_three_way_merge(base, ours, theirs, prefer_theirs=(), base_digests=None):
    """Merge two payloads against their common ancestor.

    Returns ``(merged, changes, conflicts)``: the merged payload, the keys
    the branch changed that the merge took, and the keys both sides changed
    differently — those need a human decision.

    ``prefer_theirs`` names the keys the incoming side always wins on (the
    slides and the chat of a session are its own), so a merge never turns
    them into a conflict nobody can read.

    ``base_digests`` carries the hash of a base value the commit history did
    not keep (a value above the per-key cap). For those keys the rebuilt
    ``base`` value is only the current payload, so the hash is the only
    honest way to tell "untouched here" from "changed there".
    """
    base = base if isinstance(base, dict) else {}
    ours = ours if isinstance(ours, dict) else {}
    theirs = theirs if isinstance(theirs, dict) else {}
    merged = dict(ours)
    changes = []
    conflicts = []
    # Bookkeeping keys (the draft id, the derived mirrors) are not project
    # content: the two sides always differ on them and they never conflict.
    skip = set(DRAFT_BOOKKEEPING_KEYS or ())
    preferred = set(prefer_theirs or ())
    digests = base_digests if isinstance(base_digests, dict) else {}
    for key in sorted(set(base) | set(ours) | set(theirs)):
        if key in skip:
            continue
        base_value = base.get(key, _ABSENT)
        our_value = ours.get(key, _ABSENT)
        their_value = theirs.get(key, _ABSENT)
        if our_value == their_value:
            continue
        if key in preferred:
            # The incoming side owns this key outright.
            if their_value is _ABSENT:
                merged.pop(key, None)
            else:
                merged[key] = their_value
            changes.append({
                'key': key,
                'action': 'delete' if their_value is _ABSENT else 'set',
                'value': _branch_value(their_value),
            })
            continue
        base_digest = digests.get(key)
        if base_digest:
            our_digest = (DRAFT_COMMIT_ABSENT_DIGEST if our_value is _ABSENT
                          else _draft_commit_digest(our_value))
            their_digest = (DRAFT_COMMIT_ABSENT_DIGEST if their_value is _ABSENT
                            else _draft_commit_digest(their_value))
            if our_digest == base_digest:
                # Only the incoming side moved this key — the merge takes it.
                if their_value is _ABSENT:
                    merged.pop(key, None)
                else:
                    merged[key] = their_value
                changes.append({
                    'key': key,
                    'action': 'delete' if their_value is _ABSENT else 'set',
                    'value': _branch_value(their_value),
                })
                continue
            if their_digest == base_digest:
                # Only this side moved it — it stays.
                continue
            conflicts.append({
                'key': key,
                'base': None,
                'base_unverified': True,
                'ours': _branch_value(our_value),
                'theirs': _branch_value(their_value),
                'ours_absent': our_value is _ABSENT,
                'theirs_absent': their_value is _ABSENT,
            })
            continue
        if our_value == base_value:
            # Only the branch moved this key — the merge takes it.
            if their_value is _ABSENT:
                merged.pop(key, None)
            else:
                merged[key] = their_value
            changes.append({
                'key': key,
                'action': 'delete' if their_value is _ABSENT else 'set',
                'value': _branch_value(their_value),
            })
            continue
        if their_value == base_value:
            # Only the main line moved it — it stays.
            continue
        conflicts.append({
            'key': key,
            'base': _branch_value(base_value),
            'ours': _branch_value(our_value),
            'theirs': _branch_value(their_value),
            'ours_absent': our_value is _ABSENT,
            'theirs_absent': their_value is _ABSENT,
        })
    return merged, changes, conflicts


def apply_merge_resolutions(merged, conflicts, resolutions):
    """Apply the hand-picked side for every conflicting key.

    ``choice`` is ``ours`` (keep the main line), ``theirs`` (take the
    branch) or ``value`` (use the value the person typed). A conflict with no
    answer comes back unresolved, and the merge refuses to run without it.
    """
    payload = dict(merged or {})
    by_key = {}
    for item in conflicts or []:
        by_key[str(item.get('key'))] = item
    answered = {}
    for item in resolutions or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '')
        if key in by_key:
            answered[key] = item
    unresolved = []
    for key, item in by_key.items():
        pick = answered.get(key)
        if not pick:
            unresolved.append(item)
            continue
        choice = str(pick.get('choice') or '').strip()
        if choice == 'ours':
            continue
        if choice == 'theirs':
            if item.get('theirs_absent'):
                payload.pop(key, None)
            else:
                payload[key] = pick.get('value', item.get('theirs'))
            continue
        if choice == 'value':
            payload[key] = pick.get('value')
            continue
        unresolved.append(item)
    return payload, unresolved


def draft_commit_at_or_before_revision(tenant_id, draft_id, revision):
    """The commit of that revision, or the last one before it.

    The base of a merge is the state the other side started from, and the
    client only knows its revision number — the chain holds the states.
    """
    row = get_db().execute(
        'SELECT id FROM draft_commits WHERE draft_id = ? AND revision <= ? '
        'ORDER BY revision DESC LIMIT 1',
        (draft_id, int(revision or 0))
    ).fetchone()
    return row['id'] if row else None


def draft_merge_preview_for_save(tenant_id, draft_id, base_revision, incoming,
                                 prefer_theirs=()):
    """The three-way merge of a save that lost the race.

    The base is rebuilt from the commit chain, so the client does not have
    to send what it loaded: the revision it saved against is enough.
    """
    base_commit_id = draft_commit_at_or_before_revision(tenant_id, draft_id, base_revision)
    base = {}
    base_digests = {}
    if base_commit_id:
        state, meta = draft_state_at_commit(tenant_id, draft_id, base_commit_id)
        base = state if isinstance(state, dict) else {}
        base_digests = (meta or {}).get('digests') or {}
    current = get_project_draft_by_id(tenant_id, draft_id) or {}
    ours = dict(current.get('draft_data') or {})
    theirs = dict(incoming or {})
    merged, changes, conflicts = draft_three_way_merge(
        base, ours, theirs, prefer_theirs=prefer_theirs, base_digests=base_digests)
    return merged, changes, conflicts


def create_draft_branch(tenant_id, base_draft_id, author_id=None, author_name=None,
                        name=None, base_commit_id=None):
    """Fork a project file into a branch the person can work on.

    The branch starts from the version the caller opened — the given commit,
    or the current state of the main line — so nothing the main line did
    afterwards is carried into it.
    """
    base = get_project_draft_by_id(tenant_id, base_draft_id)
    if not base:
        return {'error': 'draft_not_found'}
    status = normalize_proposal_status(base.get('status'))
    if proposal_status_is_locked(status):
        return {'error': 'draft_locked', 'status': status}
    if base_commit_id:
        state, meta = draft_state_at_commit(tenant_id, base_draft_id, base_commit_id)
        if state is None:
            return {'error': 'commit_not_found'}
    else:
        state = dict(base.get('draft_data') or {})
        # The fork remembers where it started, so the merge can tell the
        # branch's changes apart from the main line's later ones.
        head = list_draft_commits(tenant_id, base_draft_id, limit=1)
        if head:
            base_commit_id = head[0]['id']
    payload = dict(state)
    payload.pop('draftId', None)
    payload.pop('draft_id', None)
    label = str(name or '').strip() or 'فرع'
    branch_draft_id = str(uuid.uuid4())
    try:
        save_project_draft(
            tenant_id, author_id or base.get('user_id'), payload,
            dict(base.get('section_statuses') or {}), 'draft',
            draft_id=branch_draft_id,
            commit_author_id=author_id,
            commit_author_name=author_name,
            commit_message='إنشاء فرع',
            commit_kind='branch',
        )
    except Exception as exc:
        return {'error': 'branch_create_failed', 'detail': str(exc)}
    conn = get_db()
    conn.execute(
        'UPDATE project_drafts SET parent_draft_id = ?, branch_label = ? WHERE id = ?',
        (base_draft_id, label, branch_draft_id)
    )
    branch_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO draft_branches
           (id, tenant_id, base_draft_id, branch_draft_id, base_commit_id, name,
            status, created_by, created_by_name, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)''',
        (branch_id, tenant_id, base_draft_id, branch_draft_id, base_commit_id, label,
         author_id, author_name, _utcnow().isoformat())
    )
    conn.commit()
    return {
        'success': True,
        'branch': get_draft_branch(tenant_id, base_draft_id, branch_id),
        'branchDraftId': branch_draft_id,
    }


def count_open_draft_branches(tenant_id, draft_id):
    """How many branches of a project file are still open."""
    row = get_db().execute(
        "SELECT COUNT(*) AS n FROM draft_branches WHERE tenant_id = ? AND base_draft_id = ? "
        "AND status = 'open'",
        (tenant_id, draft_id)
    ).fetchone()
    return int(row['n'] or 0) if row else 0


def get_draft_branch(tenant_id, draft_id, branch_id):
    """One branch of a project file, with the state of its forked copy."""
    row = get_db().execute(
        'SELECT * FROM draft_branches WHERE id = ? AND tenant_id = ? AND base_draft_id = ?',
        (branch_id, tenant_id, draft_id)
    ).fetchone()
    if not row:
        return None
    branch = dict(row)
    branch_draft = get_project_draft_by_id(tenant_id, branch.get('branch_draft_id'))
    branch['branch_draft_id'] = branch.get('branch_draft_id')
    branch['branch_revision'] = int((branch_draft or {}).get('revision') or 0)
    branch['branch_title'] = (branch_draft or {}).get('title') or ''
    branch['branch_label'] = (branch_draft or {}).get('branch_label') or branch.get('name') or ''
    branch['branch_data_bytes'] = int((branch_draft or {}).get('data_bytes') or 0)
    return branch


def list_draft_branches(tenant_id, draft_id, include_merged=True):
    """The branches of a project file, newest first."""
    clauses = ['base_draft_id = ?', 'tenant_id = ?']
    params = [draft_id, tenant_id]
    if not include_merged:
        clauses.append("status = 'open'")
    rows = get_db().execute(
        'SELECT * FROM draft_branches WHERE ' + ' AND '.join(clauses) +
        ' ORDER BY created_at DESC, rowid DESC',
        params
    ).fetchall()
    branches = []
    for row in rows:
        branch = get_draft_branch(tenant_id, draft_id, row['id'])
        if branch:
            branches.append(branch)
    return branches


def draft_branch_merge_preview(tenant_id, draft_id, branch_id):
    """What merging a branch would do, and where it would conflict."""
    branch = get_draft_branch(tenant_id, draft_id, branch_id)
    if not branch:
        return {'error': 'branch_not_found'}
    if branch.get('status') == 'merged':
        return {'error': 'branch_already_merged'}
    base_draft = get_project_draft_by_id(tenant_id, draft_id)
    branch_draft = get_project_draft_by_id(tenant_id, branch.get('branch_draft_id'))
    if not base_draft or not branch_draft:
        return {'error': 'draft_not_found'}
    base_commit_id = branch.get('base_commit_id')
    base_digests = {}
    if base_commit_id:
        base_state, _meta = draft_state_at_commit(tenant_id, draft_id, base_commit_id)
        if base_state is None:
            return {'error': 'commit_not_found'}
        base_digests = (_meta or {}).get('digests') or {}
    else:
        base_state = dict(base_draft.get('draft_data') or {})
    ours = dict(base_draft.get('draft_data') or {})
    theirs = dict(branch_draft.get('draft_data') or {})
    merged, changes, conflicts = draft_three_way_merge(
        base_state, ours, theirs, base_digests=base_digests)
    return {
        'success': True,
        'branch': branch,
        'merged': merged,
        'changes': changes,
        'conflicts': conflicts,
        'baseRevision': int(base_draft.get('revision') or 0),
        'branchRevision': int(branch_draft.get('revision') or 0),
    }


def finish_draft_branch_merge(tenant_id, draft_id, branch_id, merged_commit_id=None):
    """Mark a branch as merged and point at the commit that carried it in."""
    conn = get_db()
    conn.execute(
        "UPDATE draft_branches SET status = 'merged', merged_at = ?, merged_commit_id = ? "
        "WHERE id = ? AND tenant_id = ? AND base_draft_id = ?",
        (_utcnow().isoformat(), merged_commit_id, branch_id, tenant_id, draft_id)
    )
    conn.commit()
    return get_draft_branch(tenant_id, draft_id, branch_id)


def discard_draft_branch(tenant_id, draft_id, branch_id):
    """Drop a branch and the forked copy that carried it."""
    branch = get_draft_branch(tenant_id, draft_id, branch_id)
    if not branch:
        return {'error': 'branch_not_found'}
    if branch.get('status') == 'merged':
        return {'error': 'branch_already_merged'}
    conn = get_db()
    conn.execute('DELETE FROM draft_commits WHERE draft_id = ?', (branch.get('branch_draft_id'),))
    conn.execute('DELETE FROM project_drafts WHERE id = ? AND tenant_id = ?',
                 (branch.get('branch_draft_id'), tenant_id))
    conn.execute('DELETE FROM draft_branches WHERE id = ? AND tenant_id = ?', (branch_id, tenant_id))
    conn.commit()
    return {'success': True, 'discarded': True}
