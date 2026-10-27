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

* A large value is stored compressed, so the study model, the market data and
  the visual concept remain fully restorable. Only a value that stays above
  the storage cap after compression is skipped and named in ``skipped_keys``;
  replaying keeps the current value for it, and the restore reports it instead
  of pretending it came back.
* The slides payload is never committed: slides carry their own revision
  history inside ``presentations`` and must not be resumed across engine
  versions.

The commit is written AFTER the save succeeded, so a refused write (locked
draft, empty overwrite, revision conflict) leaves no commit behind.
"""

import base64
import hashlib
import zlib

# A value above this size is compressed before it enters the history. The old
# rule skipped it outright, so the study model, the market data and the visual
# concept — the parts a client spends months filling — were never restorable.
DRAFT_COMMIT_MAX_VALUE_BYTES = 32 * 1024
# The size a stored value may reach after compression. Above it the value is
# skipped and reported, never silently pretended to have been kept.
DRAFT_COMMIT_MAX_STORED_BYTES = 4 * 1024 * 1024
# The whole patch of one commit is capped as well, so one save cannot fill
# the database with megabytes of history.
DRAFT_COMMIT_MAX_PATCH_BYTES = 16 * 1024 * 1024
# Payloads with their own version history stay out of the commit store.
DRAFT_COMMIT_EXCLUDED_KEYS = ('tenantSlidesData',)
# Marker stored instead of a value that did not exist in that version.
DRAFT_COMMIT_DELETED = '__draft_commit_deleted__'
# A skipped value has no stored content, so its hash stands in for it. The
# digest of a real value can never equal this marker.
DRAFT_COMMIT_ABSENT_DIGEST = '__absent__'
# Envelope of a compressed value. Commits written before compression hold the
# value itself, and decoding leaves those untouched.
DRAFT_COMMIT_ZIP_KEY = '__draft_commit_zip__'


def _draft_commit_digest(value):
    """The identity of a value whose full content the commit did not keep."""
    return hashlib.sha256(_draft_commit_json(value).encode('utf-8')).hexdigest()


def _draft_commit_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return ''


def _draft_commit_encode(value):
    """Store a large value compressed, so the history keeps ALL of it."""
    encoded = _draft_commit_json(value)
    if len(encoded.encode('utf-8')) <= DRAFT_COMMIT_MAX_VALUE_BYTES:
        return value
    packed = base64.b64encode(zlib.compress(encoded.encode('utf-8'), 6)).decode('ascii')
    return {DRAFT_COMMIT_ZIP_KEY: packed}


def _draft_commit_decode(value):
    """Read a stored value, compressed or plain."""
    if isinstance(value, dict) and set(value) == {DRAFT_COMMIT_ZIP_KEY}:
        try:
            raw = zlib.decompress(base64.b64decode(str(value[DRAFT_COMMIT_ZIP_KEY]).encode('ascii')))
            return json.loads(raw.decode('utf-8'))
        except (ValueError, zlib.error, KeyError, TypeError):
            return value
    return value


def _draft_commit_is_deleted(value):
    return isinstance(value, dict) and bool(value.get(DRAFT_COMMIT_DELETED))


def _draft_commit_apply(state, key, value):
    """Write one historic value into a rebuilt payload."""
    value = _draft_commit_decode(value)
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
    value could not be stored even compressed.
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
        stored_old = _draft_commit_encode(old_value) if key in before else {DRAFT_COMMIT_DELETED: True}
        stored_new = _draft_commit_encode(new_value) if key in after else {DRAFT_COMMIT_DELETED: True}
        size = (len(_draft_commit_json(stored_old).encode('utf-8'))
                + len(_draft_commit_json(stored_new).encode('utf-8')))
        if size > DRAFT_COMMIT_MAX_STORED_BYTES:
            skipped.append(key)
            continue
        total += size
        if total > DRAFT_COMMIT_MAX_PATCH_BYTES:
            skipped.append(key)
            continue
        patch[key] = {'from': stored_old, 'to': stored_new}
    return patch, skipped


def record_draft_commit(tenant_id, draft_id, revision, patch, skipped=None,
                        author_id=None, author_name=None, message=None,
                        kind='save', parent_id=None, skipped_digests=None):
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
            author_id, author_name, changed_keys, skipped_keys, skipped_digests,
            patch, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (commit_id, tenant_id, draft_id, parent_id, int(revision or 0), kind or 'save',
         (message or '').strip() or None, author_id or None, author_name or None,
         json.dumps(sorted(patch.keys()), ensure_ascii=False),
         json.dumps(sorted(skipped or []), ensure_ascii=False),
         json.dumps(skipped_digests or {}, ensure_ascii=False),
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
    item['skipped_digests'] = _json_object(item.get('skipped_digests'))
    patch = _json_object(item.get('patch'))
    item['patch'] = {
        key: {
            'from': _draft_commit_decode((change or {}).get('from')),
            'to': _draft_commit_decode((change or {}).get('to')),
        }
        for key, change in patch.items()
    }
    return item


def draft_commit_chain(tenant_id, draft_id):
    """Every commit of a draft, oldest first — the order a replay follows."""
    rows = get_db().execute(
        '''SELECT id, revision, patch, skipped_keys, skipped_digests FROM draft_commits
           WHERE tenant_id = ? AND draft_id = ?
           ORDER BY revision ASC, created_at ASC, rowid ASC''',
        (tenant_id, draft_id)
    ).fetchall()
    chain = []
    for row in rows:
        item = dict(row)
        item['patch'] = _json_object(item.get('patch'))
        item['skipped_keys'] = _draft_commit_json_list(item.get('skipped_keys'))
        item['skipped_digests'] = _json_object(item.get('skipped_digests'))
        chain.append(item)
    return chain


def draft_state_at_commit(tenant_id, draft_id, commit_id):
    """The payload as it stood at that commit.

    The chain is replayed: every commit up to the target writes its new
    value, and the first commit after the target writes back the value the
    field had before it changed. Keys nobody ever committed keep the value
    they have today, and a key too large to keep is reported in
    ``skipped_keys`` so the caller can say so instead of pretending.

    A skipped key's rebuilt VALUE is only a stand-in (the current payload).
    Its historical identity is still known from the digest the commit kept,
    so ``meta['digests']`` names the hash to compare against for every key
    in ``meta['unverified_keys']``; the merge must use that instead of the
    stand-in value.
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
    exact = {}
    digests = {}
    for item in chain[:target_index + 1]:
        for key, change in (item.get('patch') or {}).items():
            _draft_commit_apply(state, key, change.get('to'))
            exact[key] = True
            digests.pop(key, None)
        for key, hashes in (item.get('skipped_digests') or {}).items():
            exact[key] = False
            digests[key] = (hashes or {}).get('to') or DRAFT_COMMIT_ABSENT_DIGEST
    seen_after = set()
    for item in chain[target_index + 1:]:
        for key, change in (item.get('patch') or {}).items():
            if key in exact or key in seen_after:
                continue
            _draft_commit_apply(state, key, change.get('from'))
            seen_after.add(key)
            exact[key] = True
            digests.pop(key, None)
        for key, hashes in (item.get('skipped_digests') or {}).items():
            if key in exact or key in seen_after:
                continue
            seen_after.add(key)
            exact[key] = False
            digests[key] = (hashes or {}).get('from') or DRAFT_COMMIT_ABSENT_DIGEST
    skipped = set()
    for item in chain:
        skipped.update(item.get('skipped_keys') or [])
    return state, {
        'skipped_keys': sorted(skipped),
        'commit_index': target_index,
        'digests': digests,
        'unverified_keys': sorted(key for key, is_exact in exact.items() if not is_exact),
    }


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
    # A skipped value has no stored content, but its identity still belongs in
    # the history: the merge compares these digests to know which side moved.
    before = before_data if isinstance(before_data, dict) else {}
    skipped_digests = {}
    for key in skipped:
        skipped_digests[key] = {
            'from': _draft_commit_digest(before[key])
            if key in before else DRAFT_COMMIT_ABSENT_DIGEST,
            'to': _draft_commit_digest(new_data[key])
            if key in new_data else DRAFT_COMMIT_ABSENT_DIGEST,
        }
    author_id, author_name = _draft_commit_author(args, kwargs, meta)
    record_draft_commit(
        tenant_id, draft_id, int(row['revision'] or 0), patch, skipped,
        author_id=author_id, author_name=author_name,
        message=meta.get('commit_message'),
        kind=meta.get('commit_kind') or 'save',
        skipped_digests=skipped_digests,
    )
