
# Keys that never say anything a reader cares about inside a blob.
BLOB_SKIP_KEYS = {
    'id', 'idx', 'version', 'signature', 'created_at', 'updated_at', 'localId',
    'extraction_diagnostics', 'document_processing', 'confidence',
    'slide_generation_checkpoint', 'area_cache', 'row_source',
    'sourceFileId', 'styleReferenceFileIds',
    # A nested approval-status mirror (pageDrafts.project.sectionStatuses):
    # the real column is already diffed line-per-section on the save itself.
    'sectionStatuses',
}

# Image/file slots: the stored URL is noise — a change reads as a replacement.
BLOB_IMAGE_KEYS = {
    'image', 'imageUrl', 'image_url', 'src', 'logo', 'fileId', 'file_id',
    'fileName', 'file_name', 'cover', 'plan_image', 'photo', 'thumbnail',
    'logo_path', 'image_path', 'photo_path', 'map_path', 'cover_path',
    'approvedImageUrl', 'logoFileId', 'logo_file_id',
}

_BLOB_FILE_KEY_RE = re.compile(r'(?:_path|_url|_uri|_image|_logo|_photo|_file|_src)$', re.I)
# Camel-case twins (referenceUrl, thumbnailUrl) — case-sensitive on purpose:
# «profile» must not read as a file key.
_BLOB_CAMEL_FILE_KEY_RE = re.compile(r'(?:Url|Uri|Path|Image|Logo|Photo|File|Src)$')

# Sibling keys that pin the stored file behind an image URL. When one stays
# equal, an URL rewrite is a re-publish/re-sign of the same file — not a swap.
_STABLE_FILE_ID_KEYS = ('sourceFileId', 'source_file_id', 'fileId', 'file_id',
                        'projectFileId', 'logoFileId', 'logo_file_id')


def _looks_like_file_ref(value):
    text = str(value or '').strip()
    return text.startswith(('/uploads/', 'http://', 'https://', 'data:image',
                            'data:', 'blob:'))


def _is_imageish_change(key, old_v, new_v):
    """File/image slot even when the key is not in BLOB_IMAGE_KEYS: a *_path /
    *_url / *Url style key whose stored value is a file path or URL."""
    if key in BLOB_IMAGE_KEYS:
        return True
    if not (_BLOB_FILE_KEY_RE.search(str(key)) or _BLOB_CAMEL_FILE_KEY_RE.search(str(key))):
        return False
    return _looks_like_file_ref(old_v) or _looks_like_file_ref(new_v)


def _same_file_repath(old_row, new_row, key, old_v, new_v):
    """The URL rotated but the file id next to it did not: a heal or re-sign,
    not a user-facing replacement. Empty sides stay real add/remove events."""
    if _is_empty_value(old_v) or _is_empty_value(new_v):
        return False
    if not (_looks_like_file_ref(old_v) and _looks_like_file_ref(new_v)):
        return False
    if not (isinstance(old_row, dict) and isinstance(new_row, dict)):
        return False
    for id_key in _STABLE_FILE_ID_KEYS:
        if id_key == key:
            continue
        old_id, new_id = old_row.get(id_key), new_row.get(id_key)
        if old_id and new_id and _values_equal(old_id, new_id):
            return True
    return False


def _image_change_text(key, old_v, new_v):
    """Name the transition rather than always «استُبدلت»: an approval stamp and
    an actual replacement are different clicks."""
    had, has = not _is_empty_value(old_v), not _is_empty_value(new_v)
    if key == 'approvedImageUrl':
        if has and not had:
            return 'اعتُمدت'
        if had and not has:
            return 'أُلغي الاعتماد'
        return 'استُبدلت'
    if has and not had:
        return 'أُضيفت'
    if had and not has:
        return 'حُذفت'
    return 'استُبدلت'

_INTERNAL_KEY_RE = re.compile(
    r'^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}|[a-z]+_\d{6,}|plan_[a-z0-9_]+)$')
# A stored row reference such as «p_1789906384606_497620a2685448» or a uuid —
# never readable on screen; resolve it to the referenced row's name instead.
_INTERNAL_ID_VALUE_RE = re.compile(
    r'^(?:[a-z]+_\d{6,}(?:_[0-9a-z]{4,})?|'
    r'(?=[a-z0-9_]*\d{4,})[a-z]+(?:_[a-z0-9]+)+|'
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$', re.I)
# URL params that identify a fetch, not a file: the media signature (?s=) is
# re-issued on every response and the cache-busters (?t=/?v=/?cb=) rotate with
# each render — the same stored image would otherwise diff as a replacement on
# every save. The whole parameter is stripped so a signed and an unsigned form
# of one URL compare equal.
_URL_BUSTER_RE = re.compile(r'(?:[?&]|&amp;)(?:t|v|cb|s)=[^&\s"\'<>]*')
_MISSING = object()


def strip_url_fetch_params(value):
    """Remove rotating fetch params (?s=, ?t=, ?v=, ?cb=) from every string in a
    nested structure — a re-signed upload URL is the same content."""
    if isinstance(value, dict):
        return {key: strip_url_fetch_params(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [strip_url_fetch_params(item) for item in value]
    if isinstance(value, str):
        return _URL_BUSTER_RE.sub('', value)
    return value


def _parse_jsonish(value):
    """A stored JSON string behaves like the object it encodes."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) < 2 or text[0] not in '{[':
        return value
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


def _norm_scalar(value):
    """Numbers compare by value; text compares normalized (cache-busters and spacing out)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = _WS_RE.sub(' ', _URL_BUSTER_RE.sub('', value)).strip()
        try:
            return float(text.replace(',', ''))
        except ValueError:
            return text
    return _MISSING


def _values_equal(old, new):
    if old == new:
        return True
    old_n, new_n = _norm_scalar(old), _norm_scalar(new)
    if old_n is not _MISSING and new_n is not _MISSING:
        return old_n == new_n
    old_p, new_p = _parse_jsonish(old), _parse_jsonish(new)
    if (old_p, new_p) != (old, new):
        return _values_equal(old_p, new_p)
    return False


def _is_empty_value(value):
    return value is None or value == '' or value == {} or value == []


# Dict keys that are generated ids rather than names — search form so ids
# nested inside a longer key («interior_p_1789906…_1») are caught too.
_MACHINE_KEY_RE = re.compile(r'[a-z]+_\d{6,}|[0-9a-f]{8}-[0-9a-f]{4}|[a-z]+_[0-9a-f]{10,}', re.I)


def _child_row_name(child):
    """Display name carried inside a dict child (slots keep it in «label»)."""
    if not isinstance(child, dict):
        return ''
    for name_key in ('name', 'title', 'label', 'direction', 'point', 'street_name',
                     'milestone', 'task', 'company', 'role', 'year'):
        text = _blob_text(child.get(name_key))
        if text:
            return text
    return ''


def _blob_label(key, child=None):
    if key in BLOB_KEY_LABELS:
        return BLOB_KEY_LABELS[key]
    key_text = str(key)
    parsed = _parse_jsonish(child)
    # A machine-generated dict key («plan_site», a uuid, or a slot id like
    # «interior_p_1789906…_1») — or a key that is simply the child's own id
    # («right» → {id: 'right'}): the key is a row identifier, so name the row
    # instead — «الخانات › «الصورة الرئيسية»» rather than «أحد العناصر».
    if isinstance(parsed, dict):
        child_id = str(parsed.get('id') or parsed.get('key') or '').strip()
        if (_INTERNAL_KEY_RE.match(key_text) or _MACHINE_KEY_RE.search(key_text)
                or (child_id and child_id == key_text)):
            name = _child_row_name(parsed)
            return f'«{name}»' if name else 'أحد العناصر'
    if _INTERNAL_KEY_RE.match(key_text) or _MACHINE_KEY_RE.search(key_text):
        return 'أحد العناصر'
    return key_text


def _blob_text(value):
    """Readable text for one leaf value; '' for empty or unprintable values."""
    if _is_empty_value(value):
        return ''
    if isinstance(value, bool):
        return 'نعم' if value else 'لا'
    if isinstance(value, (int, float)):
        number = float(value)
        return str(int(number)) if number.is_integer() else str(value)
    if isinstance(value, (dict, list)):
        return ''
    text = str(value).strip()
    if not text or text.startswith('data:') or text.startswith('/uploads/'):
        return ''
    if _parse_jsonish(text) is not text:
        return ''
    return BLOB_VALUE_LABELS.get(text, _shorten(text))


def _collect_id_names(*roots):
    """id/key → display name for every row dict in the structures, so a stored
    reference («الإيراد المشمول: من «p_…» إلى «p_…»») reads as the row it points
    at. Both snapshots are scanned so a deleted row still resolves."""
    id_map = {}
    stack = [root for root in roots if isinstance(root, (dict, list))]
    while stack and len(id_map) < 1000:
        node = stack.pop()
        if isinstance(node, dict):
            row_id = str(node.get('id') or node.get('key')
                         or node.get('localId') or '').strip()
            if row_id and row_id not in id_map:
                for name_key in ('name', 'title', 'label', 'direction', 'point',
                                 'street_name', 'milestone', 'task', 'company',
                                 'role', 'year'):
                    text = _blob_text(node.get(name_key))
                    if text:
                        id_map[row_id] = text
                        break
            parsed_items = [(child_key, _parse_jsonish(child))
                            for child_key, child in node.items()]
            for child_key, child in parsed_items:
                # Slot-style dicts are keyed by the row id itself
                # («slots: {interior_p_…: {label: …}}») — map the key too, so a
                # bare id in a list («الخانات المحذوفة») still resolves.
                if isinstance(child, dict) and child_key not in id_map:
                    name = _child_row_name(child)
                    if name:
                        id_map[child_key] = name
            stack.extend(v for _, v in parsed_items if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(v for v in node if isinstance(v, (dict, list)))
    return id_map


def _ref_text(value, id_map, deleted=False, fallback=None):
    """Readable text for a leaf value, resolving stored row references to the
    referenced row's name. An unresolvable internal id reads as a removed/added
    item rather than dumping «p_1789906…» on screen."""
    raw = str(value or '').strip()
    if raw:
        if raw in id_map:
            return id_map[raw]
        if _INTERNAL_ID_VALUE_RE.match(raw):
            return 'عنصر محذوف' if deleted else 'عنصر مضاف'
    return (fallback or _blob_text)(value)


def _row_key(item):
    """Stable identity for a table row: its stored id, else its display name."""
    if isinstance(item, dict):
        explicit = str(item.get('id') or item.get('key')
                       or item.get('localId') or '').strip()
        if explicit:
            return 'id:' + explicit
        for key in ('name', 'title', 'label', 'direction', 'point', 'street_name',
                    'milestone', 'task', 'company', 'role', 'year'):
            value = str(item.get(key) or '').strip()
            if value:
                return 'name:' + value
    return None


def _row_label(item, index):
    if isinstance(item, dict):
        for key in ('name', 'title', 'label', 'direction', 'point', 'street_name',
                    'milestone', 'task', 'company', 'role', 'year'):
            text = _blob_text(item.get(key))
            if text:
                return f'«{text}»'
    return f'صف {index + 1}'


def _has_row_id(item):
    """A stored id/key is strong identity: an unmatched one means another row."""
    return isinstance(item, dict) and bool(
        str(item.get('id') or item.get('key')
            or item.get('localId') or '').strip())


def _match_rows(old_items, new_items):
    """Pair rows by id, then by name, then by order; report the leftovers."""
    pairs, remaining_new = [], set(range(len(new_items)))
    buckets = {}
    for index, item in enumerate(new_items):
        key = _row_key(item)
        if key:
            buckets.setdefault(key, []).append(index)
    unmatched_old = []
    for index, item in enumerate(old_items):
        key = _row_key(item)
        candidates = buckets.get(key) if key else None
        while candidates and candidates[0] not in remaining_new:
            candidates.pop(0)
        if candidates:
            match = candidates.pop(0)
            remaining_new.discard(match)
            pairs.append((index, match))
        else:
            unmatched_old.append(index)
    # Leftovers pair only at the same position (an in-place row edit); a row
    # removed mid-table or appended elsewhere reports as removed/added instead
    # of a fake rename between unrelated rows. Two leftover rows that both
    # carry ids are never the same row — a delete plus an insert at the same
    # position stays a removal and an addition, not a rename.
    if len(old_items) == len(new_items):
        for index in unmatched_old:
            if (index in remaining_new
                    and not (_has_row_id(old_items[index]) and _has_row_id(new_items[index]))):
                remaining_new.discard(index)
                pairs.append((index, index))
    matched_old = {index for index, _ in pairs}
    removed = [index for index in range(len(old_items)) if index not in matched_old]
    return sorted(pairs, key=lambda pair: pair[1]), removed, sorted(remaining_new)


def _path_head(path):
    return path[0] if path else ''


def _path_tail(path):
    return ' › '.join(part for part in path[1:] if part)


def _emit(out, path, text=None, field=None, old=None, new=None, kind='info'):
    if len(out) >= MAX_LINES:
        return
    item = {'group': _path_head(path), 'path': _path_tail(path), 'kind': kind}
    if field:
        item['field'] = field
        item['old'] = old or ''
        item['new'] = new or ''
        item['kind'] = 'change'
    if text:
        item['text'] = text
    out.append(item)


def _diff_blob(old, new, path, out, depth=0, extra_skip=(), state=None,
               list_verbs=None, verbs=None):
    """Walk two structured values and emit one detail item per real change."""
    if len(out) >= MAX_LINES or depth > 7:
        return
    old, new = _parse_jsonish(old), _parse_jsonish(new)
    if _values_equal(old, new):
        return
    id_map = state.get('id_map') if state else {}
    if isinstance(old, dict) and isinstance(new, dict):
        skip = set(BLOB_SKIP_KEYS) | set(extra_skip)
        for key in sorted(set(old) | set(new)):
            if (key in skip or str(key).startswith('_')
                    or str(key).endswith(('_file_meta', '_file_ids', '_file_id', '_signature'))):
                continue
            old_v, new_v = old.get(key), new.get(key)
            if _values_equal(old_v, new_v):
                continue
            # A difference at a describable key: even if no line survives below,
            # the caller's fallback knows this was a real change, not churn.
            if state is not None:
                state['saw'] = True
            # A key that is itself a stored row id («roles: {entity-uuid: role}»)
            # names the row it points at instead of printing the raw id.
            ref_name = id_map.get(str(key))
            label = (f'«{ref_name}»' if ref_name else
                     _blob_label(key, new_v if not _is_empty_value(_parse_jsonish(new_v)) else old_v))
            child_path = path + ([label] if label else [])
            if isinstance(_parse_jsonish(old_v), (dict, list)) or isinstance(_parse_jsonish(new_v), (dict, list)):
                _diff_blob(old_v, new_v, child_path, out, depth + 1,
                           extra_skip=extra_skip, state=state,
                           list_verbs=list_verbs,
                           verbs=(list_verbs or {}).get(key))
            elif _is_imageish_change(key, old_v, new_v):
                if not _same_file_repath(old, new, key, old_v, new_v):
                    _emit(out, child_path, text=_image_change_text(key, old_v, new_v),
                          kind='info')
            else:
                old_raw, new_raw = str(old_v or '').strip(), str(new_v or '').strip()
                if (old_raw and new_raw
                        and _INTERNAL_ID_VALUE_RE.match(old_raw)
                        and _INTERNAL_ID_VALUE_RE.match(new_raw)
                        and old_raw not in id_map and new_raw not in id_map):
                    # A row reference retargeted between ids that resolve in
                    # neither snapshot — machinery churn with nothing to name.
                    continue
                old_t = _ref_text(old_v, id_map, deleted=True)
                new_t = _ref_text(new_v, id_map)
                if not old_t and not new_t:
                    _emit(out, child_path, text='تغيّرت قيمة', kind='info')
                    continue
                if max(len(str(old_v or '')), len(str(new_v or ''))) > 160:
                    for text_line in _text_difference_lines(str(old_v or ''), str(new_v or '')):
                        _emit(out, child_path, text=text_line, kind='info')
                else:
                    _emit(out, path, field=label or 'القيمة', old=old_t, new=new_t,
                          kind='change')
        return
    if isinstance(old, list) and isinstance(new, list):
        if state is not None:
            state['saw'] = True
        _diff_list(old, new, path, out, depth, state=state, verbs=verbs)
        return
    had, has = not _is_empty_value(old), not _is_empty_value(new)
    if has and not had:
        text = 'أُضيفت البيانات'
    elif had and not has:
        text = 'أُزيلت البيانات'
    else:
        text = 'تغيّرت البيانات'
    if state is not None:
        state['saw'] = True
    _emit(out, path, text=text, kind='info')


def _diff_list(old_items, new_items, path, out, depth, state=None, verbs=None):
    if len(out) >= MAX_LINES:
        return
    if (old_items or new_items) and all(isinstance(item, dict)
                                        for item in list(old_items) + list(new_items)):
        pairs, removed, added = _match_rows(old_items, new_items)
        for old_index, new_index in pairs:
            _diff_blob(old_items[old_index], new_items[new_index],
                       path + [_row_label(new_items[new_index], new_index)],
                       out, depth + 1, state=state)
        for index in removed:
            _emit(out, path, text='حُذف ' + _row_label(old_items[index], index),
                  kind='removed')
        for index in added:
            _emit(out, path, text='أُضيف ' + _row_label(new_items[index], index),
                  kind='added')
        if pairs and not removed and not added:
            order = [old_index for old_index, _ in pairs]
            if order != sorted(order):
                _emit(out, path, text='أُعيد ترتيب الصفوف', kind='info')
        return
    from collections import Counter
    id_map = state.get('id_map') if state else {}
    old_counter = Counter(text for text in
                          (_ref_text(item, id_map, deleted=True) for item in old_items) if text)
    new_counter = Counter(text for text in
                          (_ref_text(item, id_map) for item in new_items) if text)
    removed = list((old_counter - new_counter).elements())
    added = list((new_counter - old_counter).elements())
    removed_verb, added_verb = verbs or ('حُذف', 'أُضيف')
    if removed:
        _emit(out, path, text=removed_verb + ': ' + '، '.join(removed[:6])
              + (f' و{len(removed) - 6} أخرى' if len(removed) > 6 else ''),
              kind='removed')
    if added:
        _emit(out, path, text=added_verb + ': ' + '، '.join(added[:6])
              + (f' و{len(added) - 6} أخرى' if len(added) > 6 else ''),
              kind='added')
    if not removed and not added and old_items != new_items:
        _emit(out, path, text='تغيّرت القائمة', kind='info')


def detail_text(item):
    """One readable line out of a stored detail item, dict or plain string."""
    if not isinstance(item, dict):
        return str(item)
    head = ' › '.join(part for part in (item.get('group'), item.get('path')) if part)
    if item.get('field'):
        old, new = str(item.get('old') or ''), str(item.get('new') or '')
        if old and new:
            phrase = f'من «{old}» إلى «{new}»'
        elif new:
            phrase = f'أُضيف «{new}»'
        else:
            phrase = f'أُفرغ (كان «{old}»)'
        return f'{head}: {item["field"]}: {phrase}' if head else f'{item["field"]}: {phrase}'
    text = str(item.get('text') or '')
    return f'{head}: {text}' if head else text


def _draft_field_labels():
    labels = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            labels[key] = field.get('label') or key
    return labels


def _draft_field_groups():
    """Section label per known draft field, so scalar edits group under their form section."""
    section_labels = {section['key']: section['label']
                      for section in (getattr(db, 'FIELD_SECTIONS', []) or [])}
    groups = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            groups[key] = section_labels.get(field.get('section_key'), '')
    return groups


def _readable_value(value):
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return 'نعم' if value else 'لا'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return ''
    text = str(value).strip()
    if text.startswith('data:'):
        return ''
    return _shorten(text)


def _is_blob(value):
    if isinstance(value, (dict, list)):
        return True
    text = str(value or '').strip()
    return text.startswith('{') or text.startswith('[')


def describe_draft_changes(old_data, new_data, field_labels=None, id_names=None):
    """Readable detail items for what changed between two saves of a project file.

    Each item is either a plain string (legacy wording, slide lines) or a dict
    {group, path, field, old, new, kind} — the log page groups dicts under their
    section and renders a before/after, while detail_text() flattens any item
    back into one sentence for plain-text consumers.
    """
    old_data = old_data if isinstance(old_data, dict) else {}
    new_data = new_data if isinstance(new_data, dict) else {}
    labels = dict(field_labels or _draft_field_labels())
    labels.update(DRAFT_SCALAR_LABELS)
    labels.update(DRAFT_BLOB_LABELS)
    groups = _draft_field_groups()
    state = {'id_map': _collect_id_names(old_data, new_data)}
    # Rows that live outside draft_data (the company team library): the caller
    # hands their id-to-name map so references inside the draft still resolve.
    if id_names:
        state['id_map'].update({str(k): str(v) for k, v in id_names.items() if v})
    lines = []

    for key in sorted(set(old_data) | set(new_data)):
        if (key in DRAFT_IGNORED_KEYS or str(key).startswith('_')
                or str(key).endswith(DRAFT_IGNORED_SUFFIXES)):
            continue
        old_value, new_value = old_data.get(key), new_data.get(key)
        if _values_equal(old_value, new_value):
            continue
        label = labels.get(key, key)
        old_blob, new_blob = _parse_jsonish(old_value), _parse_jsonish(new_value)
        if key in DRAFT_BLOB_QUIET:
            _emit(lines, [label], text=DRAFT_BLOB_QUIET[key], kind='info')
            continue
        if key in DRAFT_BLOB_LABELS or isinstance(old_blob, (dict, list)) or isinstance(new_blob, (dict, list)):
            if key == 'tenantSlidesData':
                slide_lines = describe_slide_changes(
                    old_blob if isinstance(old_blob, list) else [],
                    new_blob if isinstance(new_blob, list) else [])
                for slide_line in slide_lines:
                    _emit(lines, [label], text=slide_line, kind='info')
                continue
            _diff_blob(old_blob, new_blob, [label], lines,
                       extra_skip=DRAFT_BLOB_INNER_SKIP.get(key, ()), state=state,
                       list_verbs=DRAFT_BLOB_LIST_VERBS.get(key))
            continue
        old_text = _ref_text(old_value, state['id_map'], deleted=True, fallback=_readable_value)
        new_text = _ref_text(new_value, state['id_map'], fallback=_readable_value)
        if not old_text and not new_text:
            continue
        _emit(lines, [groups.get(key) or 'بيانات المشروع'],
              field=label, old=old_text, new=new_text, kind='change')

    if len(lines) > MAX_LINES:
        remaining = len(lines) - MAX_LINES
        lines = lines[:MAX_LINES] + [f'و{remaining} تغييرًا آخر']
    return lines


def describe_section_status_changes(old_statuses, new_statuses, section_labels=None):
    """Readable lines for approvals of the project sections."""
    old_statuses = old_statuses if isinstance(old_statuses, dict) else {}
    new_statuses = new_statuses if isinstance(new_statuses, dict) else {}
    labels = dict(section_labels or {item['key']: item['label']
                                     for item in (getattr(db, 'FIELD_SECTIONS', []) or [])})
    words = {'approved': 'معتمد', 'draft': 'مسودة', 'pending': 'قيد المراجعة'}
    lines = []
    for key in sorted(set(old_statuses) | set(new_statuses)):
        before, after = old_statuses.get(key), new_statuses.get(key)
        if before == after:
            continue
        label = labels.get(key, key)
        lines.append(f'{label}: من «{words.get(before, before or "غير محدد")}» '
                     f'إلى «{words.get(after, after or "غير محدد")}»')
    return lines


def parse_slides(raw):
    """Slides as a list, whether they arrive as JSON text or already decoded."""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []
