# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Designer chat — project data resolution (split of 08 for the 1,000-line rule)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Three-way merge of the presentation snapshot, its live draft and the request
# payload, plus the planner's scoped get_project_data read tool. Opening an old
# presentation must never let the browser's snapshot echo shadow newer saved
# values, and the worker must never edit against facts the project moved past.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _designer_project_data_for_request(request_project_data, presentation, tenant_id,
                                       superseded_out=None):
    """Merge the presentation snapshot with its latest saved draft and current request.

    The linked draft is loaded by id so opening an older presentation never sends stale
    project facts, while an unrelated newer project owned by the same user is never
    mixed in. The browser copy only wins where it moved away from the snapshot it was
    opened from: a presentation workspace re-sends that snapshot verbatim on every
    chat turn, so letting it blanket-override the live draft kept feeding the designer
    values the project already replaced. A rendered-but-empty form field likewise
    cannot wipe data the draft holds — clears go through the draft save endpoint.

    ``superseded_out``, when given, collects the snapshot values that stopped
    surviving the merge — the slide may still display them, so verification reads
    their disappearance as an authorized replacement, not data loss.
    """
    def echo_of(value, base):
        # «Same value the snapshot carried» — including scalar type drift the
        # form can introduce («5000» vs 5000), which is an echo, not an edit.
        if _draft_values_equal(value, base):
            return True
        if isinstance(value, (str, int, float)) and isinstance(base, (str, int, float)):
            if str(value).strip() == str(base).strip():
                return True
            try:
                return float(str(value).strip()) == float(str(base).strip())
            except (TypeError, ValueError):
                return False
        return False

    cleaned_request = copy.deepcopy(request_project_data) if isinstance(request_project_data, dict) else {}
    request_data = cleaned_request if isinstance(cleaned_request, dict) else {}
    presentation_data = {}
    if isinstance(presentation, dict):
        raw = presentation.get('project_data')
        if isinstance(raw, dict):
            presentation_data = copy.deepcopy(raw)
        elif isinstance(raw, str) and raw.strip():
            try:
                decoded = json.loads(raw)
                presentation_data = decoded if isinstance(decoded, dict) else {}
            except (TypeError, ValueError):
                presentation_data = {}
    presentation_draft_id = presentation.get('draft_id') if isinstance(presentation, dict) else None
    draft_id = (
        presentation_draft_id
        or presentation_data.get('draftId') or presentation_data.get('draft_id')
        or request_data.get('draftId') or request_data.get('draft_id')
    )
    draft_data = {}
    if tenant_id and draft_id:
        try:
            draft = db.get_project_draft_by_id(tenant_id, str(draft_id))
            if isinstance(draft, dict) and isinstance(draft.get('draft_data'), dict):
                draft_data = copy.deepcopy(draft['draft_data'])
        except Exception as exc:
            print(f'[DESIGNER-CHAT] Could not load linked draft {draft_id}: {exc}')
    if not presentation_data:
        merged = {**draft_data, **request_data}
    else:
        merged = {**presentation_data, **draft_data}
        for key, value in request_data.items():
            if not _draft_value_has_content(value) and _draft_value_has_content(merged.get(key)):
                continue
            if key in presentation_data and echo_of(value, presentation_data.get(key)):
                continue
            merged[key] = value
        if superseded_out is not None:
            superseded_out.extend(
                base_value for key, base_value in presentation_data.items()
                if key in merged and not _draft_values_equal(merged[key], base_value)
                and _draft_value_has_content(base_value))
    if draft_id:
        merged['draftId'] = str(draft_id)
    return merged


def _superseded_number_tokens(values):
    """Numeric tokens inside values the merge retired.

    A path or URL is never a slide fact — its digit runs (dates, ids inside
    filenames) would over-authorize drops, so only plain text counts.
    """
    tokens = set()
    for value in values or []:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if re.match(r'^\s*(/|https?://|data:)', text, flags=re.IGNORECASE):
            continue
        try:
            tokens |= set(designer_agent_plan.extract_visible_numbers(text).keys())
        except Exception:
            pass
    return tokens


def _merge_superseded_numbers(ctx, values):
    tokens = _superseded_number_tokens(values)
    if tokens:
        ctx['superseded_numbers'] = set(ctx.get('superseded_numbers') or ()) | tokens


def _designer_project_data_tool_result(args, ctx):
    """Serve the planner the project's CURRENT saved data, scoped to what it asked for.

    The deck being edited can come from a presentation snapshot older than the live
    draft, so this re-runs the request merge instead of trusting ctx: a section
    approved seconds ago lands in the same turn that asks about it. Keys it returns
    are also written back into ``ctx['project_data']`` — and the values they replace
    into the superseded pool — so the worker's fact block and the
    number-preservation check agree with what the planner just read. Hidden-section
    keys (ISS-015) are stripped before the model sees anything.
    """
    args = args if isinstance(args, dict) else {}
    tenant_id = ctx.get('tenant_id')
    try:
        merged = _designer_project_data_for_request(
            ctx.get('request_project_data') or {},
            ctx.get('presentation'), tenant_id)
    except Exception:
        merged = dict(ctx.get('project_data') or {})
    try:
        merged = _draft_data_for_response(merged)
    except Exception:
        pass
    merged = merged if isinstance(merged, dict) else {}

    labels = {}
    try:
        labels = dict(slide_engine._field_label_map())
    except Exception:
        labels = {}
    try:
        for field in db.get_fields(tenant_id) or []:
            fkey = field.get('field_key')
            if fkey:
                labels.setdefault(fkey, (field.get('field_label') or fkey,
                                         field.get('section_key') or 'general', 0))
    except Exception:
        pass
    extra_labels = getattr(slide_engine, 'EXTRA_FIELD_LABELS', {}) or {}

    def label_of(key):
        entry = labels.get(key)
        return entry[0] if entry else extra_labels.get(key, key)

    sections = {str(s.get('key') or ''): str(s.get('label') or s.get('key') or '')
                for s in (getattr(db, 'FIELD_SECTIONS', []) or []) if s.get('key')}
    try:
        hidden = _hidden_field_sections()
    except Exception:
        hidden = set()

    section_arg = str(args.get('section') or '').strip()
    section_key = ''
    if section_arg:
        folded = section_arg.casefold()
        for key, label in sections.items():
            if folded == key.casefold() or folded == label.casefold():
                section_key = key
                break
        if not section_key:
            for key, label in sections.items():
                if folded in key.casefold() or key.casefold() in folded \
                        or folded in label.casefold() or label.casefold() in folded:
                    section_key = key
                    break
        if not section_key:
            section_key = section_arg
    if section_key and section_key in hidden:
        return json.dumps({'error': 'section_unavailable'}, ensure_ascii=False)
    want_keys = [str(k).strip() for k in (args.get('keys') or []) if str(k or '').strip()]

    if not section_key and not want_keys:
        catalog = [{'key': k, 'label': v} for k, v in sections.items() if k not in hidden]
        return json.dumps(
            {'sections': catalog,
             'note': 'حدّد قسماً أو مفاتيح حقول لقراءة أحدث قيمها المحفوظة'},
            ensure_ascii=False)

    try:
        section_map = _draft_field_section_map(tenant_id)
    except Exception:
        section_map = {}

    # Keys surfaced by a whole-section read must carry content; keys asked for by
    # name are listed even when empty so the planner learns the field is unset.
    selected, seen, missing_keys = [], set(), []
    if section_key:
        keys_in_section = [k for k, s in section_map.items() if s == section_key]
        keys_in_section += [k for k in SECTION_SNAPSHOT_BLOBS.get(section_key, [])
                            if k not in keys_in_section]
        for key in keys_in_section:
            seen.add(key)
            if _draft_value_has_content(merged.get(key)):
                selected.append(key)
    for key in want_keys:
        if key in seen:
            continue
        seen.add(key)
        known = key in labels or key in extra_labels \
            or _draft_section_of_key(section_map, key) is not None
        if not known or key not in merged:
            missing_keys.append(key)
            continue
        selected.append(key)

    fields, total, truncated = [], 0, False
    for key in selected[:60]:
        try:
            text = slide_engine._readable_fact(merged.get(key)) or ''
        except Exception:
            text = str(merged.get(key) or '')
        if len(text) > 4000:
            text = text[:4000] + '…'
        if total + len(text) > 24000:
            truncated = True
            break
        total += len(text)
        fields.append({'key': key, 'label': label_of(key), 'value': text})

    if isinstance(ctx.get('project_data'), dict):
        for key in selected:
            if key not in merged:
                continue
            old = ctx['project_data'].get(key)
            if not _draft_values_equal(old, merged[key]):
                ctx['project_data'][key] = merged[key]
                _merge_superseded_numbers(ctx, [old])

    payload = {'section': section_key or None,
               'section_label': sections.get(section_key, ''),
               'fields': fields}
    if missing_keys:
        payload['missing_keys'] = missing_keys
    if truncated:
        payload['truncated'] = True
        payload['note'] = 'النتيجة طويلة — اطلب مفاتيح أدق إن احتجت الباقي'
    elif not fields:
        payload['note'] = ('لا توجد بيانات محفوظة تطابق الطلب — لا تخترع قيماً '
                           'وأخبر المستخدم أن القسم فارغ')
    return json.dumps(payload, ensure_ascii=False)
