"""Draft commit store — the version history of a project file.

A draft row keeps the live payload only, so two people editing the same file
could still overwrite each other. The commit store is the answer the owner
asked for: work like a git repository. Every save leaves a commit behind,
each commit points at its parent, and a commit stores the DIFFERENCE against
the state the save started from — not a full copy of a payload that can reach
several megabytes. An earlier version is rebuilt by replaying the chain, and
a restore is a new commit that carries the old values forward, exactly like a
git revert: nothing is ever thrown away.

Two rules keep the store honest:

* A value too large to store (an inline image, a slide deck) is skipped and
  named in ``skipped_keys``. Replaying keeps the current value for it, so a
  restore never invents content it could not read.
* The slides payload is never committed: slides carry their own revision
  history inside ``presentations`` and must not be resumed across engine
  versions.

The commit is written AFTER the save succeeded, so a refused write (locked
draft, empty overwrite, revision conflict) leaves no commit behind.
"""

# A single value above this size is not worth a history row: it is an inline
# image or a slide deck, and the file it belongs to is stored separately.
DRAFT_COMMIT_MAX_VALUE_BYTES = 32768
# The whole patch of one commit is capped as well, so one save cannot fill
# the database with megabytes of history.
DRAFT_COMMIT_MAX_PATCH_BYTES = 262144
# Payloads with their own version history stay out of the commit store.
DRAFT_COMMIT_EXCLUDED_KEYS = ('tenantSlidesData',)
# Marker stored instead of a value that did not exist in that version.
DRAFT_COMMIT_DELETED = '__draft_commit_deleted__'


def _draft_commit_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return ''


def _draft_commit_is_deleted(value):
    return isinstance(value, dict) and bool(value.get(DRAFT_COMMIT_DELETED))


def _draft_commit_apply(state, key, value):
    """Write one historic value into a rebuilt payload."""
    if _draft_commit_is_deleted(value):
        state.pop(key, None)
    else:
        state[key] = value


def _draft_commit_json_list(value):
    if isinstance(value, list):
        return list(value)
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []


def draft_commit_patch(old_data, new_data):
    """Difference between two draft payloads, as a mergeable patch.

    Returns ``(patch, skipped)``: the patch maps every changed top-level key
    to its previous and its new value, and ``skipped`` names the keys whose
    value was too large to keep.
    """
    before = old_data if isinstance(old_data, dict) else {}
    after = new_data if isinstance(new_data, dict) else {}
    patch = {}
    skipped = []
    total = 0
    for key in sorted(set(before) | set(after)):
        if key in DRAFT_COMMIT_EXCLUDED_KEYS:
            continue
        old_value = before.get(key)
        new_value = after.get(key)
        if old_value == new_value:
            continue
        encoded = _draft_commit_json(new_value)
        if len(encoded.encode('utf-8')) > DRAFT_COMMIT_MAX_VALUE_BYTES:
            skipped.append(key)
            continue
        total += len(encoded.encode('utf-8'))
        if total > DRAFT_COMMIT_MAX_PATCH_BYTES:
            skipped.append(key)
            continue
        patch[key] = {
            'from': old_value if key in before else {DRAFT_COMMIT_DELETED: True},
            'to': new_value if key in after else {DRAFT_COMMIT_DELETED: True},
        }
    return patch, skipped


def record_draft_commit(tenant_id, draft_id, revision, patch, skipped=None,
                        author_id=None, author_name=None, message=None,
                        kind='save', parent_id=None):
    """Store one commit of a draft and return its id."""
    conn = get_db()
    if parent_id is None:
        row = conn.execute(
            'SELECT id FROM draft_commits WHERE draft_id = ? '
            'ORDER BY revision DESC, created_at DESC, rowid DESC LIMIT 1',
            (draft_id,)
        ).fetchone()
        parent_id = row['id'] if row else None
    commit_id = str(uuid.uuid4())
    conn.execute(
        '''INSERT INTO draft_commits
           (id, tenant_id, draft_id, parent_id, revision, kind, message,
            author_id, author_name, changed_keys, skipped_keys, patch, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (commit_id, tenant_id, draft_id, parent_id, int(revision or 0), kind or 'save',
         (message or '').strip() or None, author_id or None, author_name or None,
         json.dumps(sorted(patch.keys()), ensure_ascii=False),
         json.dumps(sorted(skipped or []), ensure_ascii=False),
         json.dumps(patch, ensure_ascii=False), _utcnow().isoformat())
    )
    conn.commit()
    return commit_id


def list_draft_commits(tenant_id, draft_id, limit=100):
    """The commit chain of a draft, newest first (the patch is left out)."""
    rows = get_db().execute(
        '''SELECT id, parent_id, revision, kind, message, author_id, author_name,
                  changed_keys, skipped_keys, created_at
           FROM draft_commits WHERE tenant_id = ? AND draft_id = ?
           ORDER BY revision DESC, created_at DESC, rowid DESC LIMIT ?''',
        (tenant_id, draft_id, int(limit))
    ).fetchall()
    commits = []
    for row in rows:
        item = dict(row)
        item['changed_keys'] = _draft_commit_json_list(item.get('changed_keys'))
        item['skipped_keys'] = _draft_commit_json_list(item.get('skipped_keys'))
        item['changed_count'] = len(item['changed_keys'])
        commits.append(item)
    return commits


def get_draft_commit(tenant_id, draft_id, commit_id):
    """One commit with its patch, or None when it does not belong to the draft."""
    row = get_db().execute(
        'SELECT * FROM draft_commits WHERE id = ? AND tenant_id = ? AND draft_id = ?',
        (commit_id, tenant_id, draft_id)
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item['changed_keys'] = _draft_commit_json_list(item.get('changed_keys'))
    item['skipped_keys'] = _draft_commit_json_list(item.get('skipped_keys'))
    item['patch'] = _json_object(item.get('patch'))
    return item


def draft_commit_chain(tenant_id, draft_id):
    """Every commit of a draft, oldest first — the order a replay follows."""
    rows = get_db().execute(
        '''SELECT id, revision, patch, skipped_keys FROM draft_commits
           WHERE tenant_id = ? AND draft_id = ?
           ORDER BY revision ASC, created_at ASC, rowid ASC''',
        (tenant_id, draft_id)
    ).fetchall()
    chain = []
    for row in rows:
        item = dict(row)
        item['patch'] = _json_object(item.get('patch'))
        item['skipped_keys'] = _draft_commit_json_list(item.get('skipped_keys'))
        chain.append(item)
    return chain


def draft_state_at_commit(tenant_id, draft_id, commit_id):
    """The payload as it stood at that commit.

    The chain is replayed: every commit up to the target writes its new
    value, and the first commit after the target writes back the value the
    field had before it changed. Keys nobody ever committed keep the value
    they have today, and a key too large to keep is reported in
    ``skipped_keys`` so the caller can say so instead of pretending.
    """
    chain = draft_commit_chain(tenant_id, draft_id)
    if not chain:
        return None, {'error': 'commit_not_found'}
    ids = [item['id'] for item in chain]
    if commit_id not in ids:
        return None, {'error': 'commit_not_found'}
    target_index = ids.index(commit_id)
    draft = get_project_draft_by_id(tenant_id, draft_id)
    state = dict((draft or {}).get('draft_data') or {})
    touched = set()
    for item in chain[:target_index + 1]:
        for key, change in item['patch'].items():
            _draft_commit_apply(state, key, change.get('to'))
            touched.add(key)
    seen_after = set()
    for item in chain[target_index + 1:]:
        for key, change in item['patch'].items():
            if key in touched or key in seen_after:
                continue
            _draft_commit_apply(state, key, change.get('from'))
            seen_after.add(key)
    skipped = set()
    for item in chain:
        skipped.update(item.get('skipped_keys') or [])
    return state, {'skipped_keys': sorted(skipped), 'commit_index': target_index}


def draft_commit_diff(tenant_id, draft_id, commit_id):
    """What one commit changed, as ``before``/``after`` per key."""
    commit = get_draft_commit(tenant_id, draft_id, commit_id)
    if not commit:
        return None
    changes = []
    for key in sorted(commit.get('patch') or {}):
        change = commit['patch'][key] or {}
        changes.append({
            'key': key,
            'from': None if _draft_commit_is_deleted(change.get('from')) else change.get('from'),
            'to': None if _draft_commit_is_deleted(change.get('to')) else change.get('to'),
            'deleted_from': bool(_draft_commit_is_deleted(change.get('from'))),
            'deleted_to': bool(_draft_commit_is_deleted(change.get('to'))),
        })
    commit['changes'] = changes
    return commit


# ── The save hook ───────────────────────────────────────────────────────────
# Every save path — the editor, the generation checkpoint, the best-use
# pre-save — goes through db.save_project_draft, so the history is written
# once, here, instead of in every caller. The wrapper keeps the original
# function intact and adds the commit after a successful write.

_save_project_draft_impl = save_project_draft

_COMMIT_META_KEYS = ('commit_author_id', 'commit_author_name', 'commit_message', 'commit_kind')


def _draft_state_before_save(args, kwargs):
    """The payload a save is about to write over, and the row it targets."""
    existing_row = kwargs.get('existing_row')
    if isinstance(existing_row, dict) and existing_row.get('id'):
        return dict(existing_row.get('draft_data') or {}), existing_row.get('id')
    draft_id = kwargs.get('draft_id')
    if not draft_id and len(args) > 5:
        draft_id = args[5]
    if not draft_id:
        return None, None
    row = get_db().execute(
        'SELECT id, draft_data FROM project_drafts WHERE id = ?', (draft_id,)
    ).fetchone()
    if not row:
        return None, None
    return _json_object(row['draft_data']), row['id']


def _draft_commit_author(args, kwargs, meta):
    """Who made the save: the caller names itself, otherwise the actor id."""
    author_id = meta.get('commit_author_id')
    if not author_id and len(args) > 1:
        author_id = args[1]
    author_name = meta.get('commit_author_name')
    if not author_name and author_id:
        try:
            user = get_user_by_id(author_id)
            author_name = (user or {}).get('name')
        except Exception:
            author_name = None
    return author_id, author_name


def save_project_draft(*args, **kwargs):
    """Save a draft and leave a commit behind.

    The commit is written only after the save succeeded, so a refused write
    never shows up in the history. A failure to write the history never fails
    the save: the project file matters more than its log.
    """
    meta = {key: kwargs.pop(key) for key in _COMMIT_META_KEYS if key in kwargs}
    before_data, before_id = _draft_state_before_save(args, kwargs)
    result = _save_project_draft_impl(*args, **kwargs)
    try:
        _record_save_commit(args, kwargs, meta, before_data, before_id, result)
    except Exception as exc:  # history must never break a save
        print(f'[DRAFT COMMIT] could not record the commit for draft {before_id}: {exc}')
    return result


def _draft_commit_is_new_row(row):
    """A row created by the save we just made: revision 1, same timestamps."""
    return (int((row or {}).get('revision') or 0) == 1
            and str((row or {}).get('created_at') or '') == str((row or {}).get('updated_at') or ''))


def _record_save_commit(args, kwargs, meta, before_data, before_id, result):
    """Write the commit that describes what the save just changed."""
    tenant_id = kwargs.get('tenant_id') or (args[0] if args else None)
    new_data = kwargs.get('draft_data')
    if new_data is None and len(args) > 2:
        new_data = args[2]
    if not tenant_id or not isinstance(new_data, dict):
        return
    draft_id = before_id
    if not draft_id:
        # A save that named no row: the only safe history is the baseline of a
        # brand-new file. A save that landed on an existing row we could not
        # read before it wrote leaves no commit, because a wrong "created"
        # entry would be worse than none.
        row = get_db().execute(
            'SELECT id, revision, created_at, updated_at FROM project_drafts WHERE id = ?',
            (result,)
        ).fetchone()
        if not row or not _draft_commit_is_new_row(dict(row)):
            return
        draft_id = row['id']
        before_data = {}
    row = get_db().execute(
        'SELECT revision FROM project_drafts WHERE id = ?', (draft_id,)
    ).fetchone()
    if not row:
        return
    patch, skipped = draft_commit_patch(before_data, new_data)
    if not patch and not skipped:
        return
    author_id, author_name = _draft_commit_author(args, kwargs, meta)
    record_draft_commit(
        tenant_id, draft_id, int(row['revision'] or 0), patch, skipped,
        author_id=author_id, author_name=author_name,
        message=meta.get('commit_message'),
        kind=meta.get('commit_kind') or 'save'
    )
