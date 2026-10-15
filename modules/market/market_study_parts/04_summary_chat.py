# ---------------------------------------------------------------------------
# Interactive summary chat — the contract module for the per-axis discuss /
# research session that sits on top of the one-shot summary generation.
#
# Pure functions only: no Flask, no db, no network. The endpoints in
# app_parts/17_market/18f_summary_chat.py call these builders and normalizers;
# everything here shares the market_study module namespace (SUMMARY_SECTIONS,
# SWOT_SECTIONS, DECISION_OPTIONS, _project_input_block, MISSING_VALUE_PHRASE,
# summary_has_content come from the loader / sibling parts — never redefine).
#
# Turn contract: phase A is a discuss call that may propose targeted ops
# ({reply, needs_research, queries, ops}); phase B re-asks through native
# Google search when needs_research fires and returns {reply, ops, sources_add}. Ops
# are proposals — the client shows them and the user applies them; nothing
# here mutates the live summary state except apply_summary_ops, which is a
# pure transform returning a new state plus the touched-field set.
# ---------------------------------------------------------------------------


SUMMARY_CHAT_AXIS_GENERAL = 'general'

# English display names for the summary axes — the same strings the UI's
# auto-EN dict (assets/i18n/07_dict_en_auto_market.js) already shows.
SUMMARY_CHAT_AXIS_LABELS_EN = {
    'market_definition': 'Market Definition',
    'city_position': 'City Mode / Overview',
    'sector_performance': 'Sector Performance',
    'supply': 'Supply',
    'demand': 'Demand',
    'competition': 'Competition',
    'market_gap': 'Market Gap',
    'project_evaluation': 'Project Evaluation',
    'recommendation': 'Recommendation',
    'risks': 'Risks',
}
_SUMMARY_CHAT_GENERAL_LABEL = 'عام'
_SUMMARY_CHAT_GENERAL_LABEL_EN = 'General'

# Display names for the decision enum when the offer is English — the stored
# value stays a DECISION_OPTIONS member; this map only lets the validator
# accept the English twin a model may emit and fold it back to the enum.
_SUMMARY_CHAT_DECISION_EN = {
    'فرصة قوية': 'Strong opportunity',
    'فرصة واعدة بشروط': 'Promising opportunity with conditions',
    'فرصة متوسطة': 'Medium opportunity',
    'فرصة مرتفعة المخاطر': 'High-risk opportunity',
    'البيانات غير كافية': 'Insufficient data',
}

_SUMMARY_CHAT_AXIS_KEYSET = frozenset(item['key'] for item in SUMMARY_SECTIONS)
_SUMMARY_CHAT_SWOT_KEYSET = frozenset(item['key'] for item in SWOT_SECTIONS)
_SUMMARY_CHAT_STALE_ORDER = ('one_block', 'decision', 'swot')

_SUMMARY_CHAT_OP_TEXT_MAX = 6000
_SUMMARY_CHAT_REPLY_MAX = 6000
_SUMMARY_CHAT_QUERY_MAX = 300
_SUMMARY_CHAT_QUERIES_MAX = 6
_SUMMARY_CHAT_SOURCE_ROWS_MAX = 8
_SUMMARY_CHAT_SOURCE_FIELD_MAX = 2000
_SUMMARY_CHAT_INDEX_LINE_MAX = 160
_SUMMARY_CHAT_SOURCES_SHOWN = 60


def summary_chat_axes(offer_lang=None):
    """[{key, label}] — the general thread first, then the ten summary axes
    in SUMMARY_SECTIONS order. Labels are the sections' existing display
    names; English variants ride the offer language."""
    en = offer_lang == 'en'
    axes = [{'key': SUMMARY_CHAT_AXIS_GENERAL,
             'label': _SUMMARY_CHAT_GENERAL_LABEL_EN if en else _SUMMARY_CHAT_GENERAL_LABEL}]
    for item in SUMMARY_SECTIONS:
        label = (SUMMARY_CHAT_AXIS_LABELS_EN.get(item['key']) or item['label']) if en else item['label']
        axes.append({'key': item['key'], 'label': label})
    return axes


def _summary_chat_axis_label(axis):
    """Prompt-facing axis name: the section label, or a whole-summary tag."""
    if axis == SUMMARY_CHAT_AXIS_GENERAL:
        return 'عام — الملخص كاملًا'
    item = next((item for item in SUMMARY_SECTIONS if item['key'] == axis), None)
    return f"{item['label']} ({axis})" if item else str(axis or SUMMARY_CHAT_AXIS_GENERAL)


def _summary_chat_json_object(raw):
    """Tolerant JSON-object extraction with the same latitude as the app's
    parse_json_object (which lives in app_parts and is not importable here):
    a dict passes through, a string is tried verbatim, inside a fenced code
    block, embedded in prose via brace matching, then with truncation repair."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    text = raw.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', text)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    start = text.find('{')
    if start == -1:
        return {}
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == '\\' and in_str:
            esc = True
            continue
        if ch == '"' and not esc:
            in_str = not in_str
            continue
        if not in_str:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start:i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass
                    break
    if depth > 0 or in_str:
        partial = text[start:]
        partial = re.sub(r'\\u[0-9a-fA-F]{0,3}$', '', partial)
        partial = re.sub(r'\\$', '', partial)
        if in_str:
            partial += '"'
        for d in range(max(1, depth), 0, -1):
            try:
                parsed = json.loads(partial + ('}' * d))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def _chat_flag(value):
    """JSON booleans arrive as true/false, 'true'/'false', 1/0 — fold them."""
    if isinstance(value, str):
        return value.strip().casefold() in ('1', 'true', 'yes', 'on', 'نعم')
    return bool(value)


def _clean_summary_op_text(value, limit=_SUMMARY_CHAT_OP_TEXT_MAX):
    """Op text hygiene: trim whitespace, strip icon/emoji markup through the
    same slide-engine remover the pipeline uses, cap the length. slide_engine
    is imported lazily — market_study stays a leaf module."""
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        import slide_engine
        text = slide_engine._strip_presentation_icons(text)
    except Exception:
        pass
    return text.strip()[:limit].strip()


def _summary_chat_ops_list(data):
    """ops may arrive as a list, a single dict, or nested under proposal."""
    raw = data.get('ops')
    if not raw and isinstance(data.get('proposal'), dict):
        raw = data['proposal'].get('ops')
    if isinstance(raw, dict):
        raw = [raw]
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _summary_chat_source_row(row):
    """Shape one proposed source row; empty rows (no name and no url) drop."""
    if not isinstance(row, dict):
        return None
    name = _norm(row.get('name'))
    url = _norm(row.get('url') or row.get('source_url') or row.get('sourceUrl'))
    if not name and not url:
        return None
    return {
        'name': name[:_SUMMARY_CHAT_SOURCE_FIELD_MAX],
        'url': url[:_SUMMARY_CHAT_SOURCE_FIELD_MAX],
        'data_date': _norm(row.get('data_date') or row.get('dataDate')),
        'note': _clean_summary_op_text(row.get('note'), _SUMMARY_CHAT_SOURCE_FIELD_MAX),
        'reliability': _norm(row.get('reliability')),
    }


def _summary_chat_reply_axis(value):
    """The axis the model says the message is about — folded onto the known
    keyset so a hallucinated key can never steer the context block."""
    axis = _norm(value)
    if axis in _SUMMARY_CHAT_AXIS_KEYSET or axis == SUMMARY_CHAT_AXIS_GENERAL:
        return axis
    return SUMMARY_CHAT_AXIS_GENERAL


def normalize_summary_chat_reply(raw):
    """Phase-A (discuss) output → {reply, axis, needs_clarification,
    needs_research, queries, ops}.

    Accepts the parsed dict or the model's raw text (fenced blocks and
    surrounding prose tolerated). Malformed input raises ValueError with a
    short Arabic reason — the caller surfaces it as the turn's error."""
    data = _summary_chat_json_object(raw)
    if not data:
        raise ValueError('رد النموذج ليس JSON صالحًا.')
    reply = _clean_summary_op_text(data.get('reply'), _SUMMARY_CHAT_REPLY_MAX)
    if not reply:
        raise ValueError('رد النموذج بلا نص.')
    raw_queries = data.get('queries')
    if isinstance(raw_queries, str):
        raw_queries = [raw_queries]
    queries = [
        _norm(item)[:_SUMMARY_CHAT_QUERY_MAX]
        for item in (raw_queries if isinstance(raw_queries, list) else [])
        if _norm(item)
    ][:_SUMMARY_CHAT_QUERIES_MAX]
    return {
        'reply': reply,
        'axis': _summary_chat_reply_axis(data.get('axis')),
        'needs_clarification': _chat_flag(data.get('needs_clarification')),
        'needs_research': _chat_flag(data.get('needs_research')),
        'queries': queries,
        'ops': _summary_chat_ops_list(data),
    }


def normalize_summary_chat_research(raw):
    """Phase-B (browse-agent) output → {reply, ops, sources_add}.

    Same parsing as the discuss reply plus the new-source rows. An empty reply
    is tolerated here — the endpoint falls back to the phase-A reply while the
    researched ops and sources still count; only a non-object raises."""
    data = _summary_chat_json_object(raw)
    if not data:
        raise ValueError('رد البحث ليس JSON صالحًا.')
    raw_sources = data.get('sources_add') or data.get('sourcesAdd') or data.get('sources')
    if not raw_sources and isinstance(data.get('proposal'), dict):
        raw_sources = data['proposal'].get('sources_add') or data['proposal'].get('sourcesAdd')
    if isinstance(raw_sources, dict):
        raw_sources = [raw_sources]
    sources_add = []
    for row in (raw_sources if isinstance(raw_sources, list) else []):
        shaped = _summary_chat_source_row(row)
        if shaped:
            sources_add.append(shaped)
    return {
        'reply': _clean_summary_op_text(data.get('reply'), _SUMMARY_CHAT_REPLY_MAX),
        'ops': _summary_chat_ops_list(data),
        'sources_add': sources_add,
    }


def _summary_chat_decision_value(value):
    """Fold a proposed decision onto a DECISION_OPTIONS member: exact member,
    a member the text contains (normalize_summary's tolerance), or an English
    display twin mapped back. '' when nothing matches."""
    text = _norm(value)
    if not text:
        return ''
    if text in DECISION_OPTIONS:
        return text
    matched = next((option for option in DECISION_OPTIONS if option in text), '')
    if matched:
        return matched
    folded = _fold_choice(text)
    for option, en in _SUMMARY_CHAT_DECISION_EN.items():
        if folded == _fold_choice(en) or _fold_choice(en) in folded:
            return option
    return ''


def validate_summary_ops(ops):
    """Whitelist the model's proposed ops → (kept, rejected).

    kept holds only the four contract shapes — set_axis/set_swot/set_decision/
    add_sources — with cleaned text; rejected collects every dropped entry as
    {'op': <raw entry>, 'reason': <short code>}. Bad ops never raise; a
    non-list ``ops`` does (a caller bug, not a model quirk)."""
    if not isinstance(ops, list):
        raise ValueError('ops يجب أن تكون قائمة.')
    kept = []
    rejected = []
    for entry in ops:
        if not isinstance(entry, dict):
            rejected.append({'op': entry, 'reason': 'not_object'})
            continue
        name = _norm(entry.get('op') or entry.get('type'))
        if name == 'set_axis':
            key = _norm(entry.get('key'))
            value = _clean_summary_op_text(entry.get('value'))
            if key not in _SUMMARY_CHAT_AXIS_KEYSET:
                rejected.append({'op': entry, 'reason': 'unknown_axis'})
            elif not value:
                rejected.append({'op': entry, 'reason': 'empty_value'})
            else:
                kept.append({'op': 'set_axis', 'key': key, 'value': value})
        elif name == 'set_swot':
            key = _norm(entry.get('key'))
            value = _clean_summary_op_text(entry.get('value'))
            if key not in _SUMMARY_CHAT_SWOT_KEYSET:
                rejected.append({'op': entry, 'reason': 'unknown_swot_key'})
            elif not value:
                rejected.append({'op': entry, 'reason': 'empty_value'})
            else:
                kept.append({'op': 'set_swot', 'key': key, 'value': value})
        elif name == 'set_decision':
            decision = _summary_chat_decision_value(entry.get('value'))
            if not decision:
                rejected.append({'op': entry, 'reason': 'unknown_decision'})
            else:
                kept.append({'op': 'set_decision', 'value': decision})
        elif name == 'add_sources':
            raw_rows = entry.get('rows')
            if isinstance(raw_rows, dict):
                raw_rows = [raw_rows]
            rows = []
            for row in (raw_rows if isinstance(raw_rows, list) else []):
                shaped = _summary_chat_source_row(row)
                if shaped:
                    rows.append(shaped)
            if not rows:
                rejected.append({'op': entry, 'reason': 'empty_rows'})
                continue
            kept.append({'op': 'add_sources', 'rows': rows[:_SUMMARY_CHAT_SOURCE_ROWS_MAX]})
            if len(rows) > _SUMMARY_CHAT_SOURCE_ROWS_MAX:
                rejected.append({'op': entry, 'reason': 'rows_over_limit',
                                 'dropped': rows[_SUMMARY_CHAT_SOURCE_ROWS_MAX:]})
        else:
            rejected.append({'op': entry, 'reason': 'unknown_op'})
    return kept, rejected


def apply_summary_ops(state, ops):
    """Apply validated ops to a summary state → (new_state, touched).

    Pure: the input state is never mutated; containers are copied on write.
    set_axis/set_swot write into state['summary'][key] / state['swot'][key],
    set_decision writes state['decision'], add_sources appends rows to
    state['sources'] deduped by url (name when the row has no url).
    ``touched`` is the set of fields that actually changed — summary axis
    keys, swot keys, 'decision', 'sources' — the same keys summary_ops_stale
    reads. A re-set of identical text does not count as touched."""
    kept, _rejected = validate_summary_ops(ops)
    base = state if isinstance(state, dict) else {}
    new_state = dict(base)
    summary_in = base.get('summary')
    swot_in = base.get('swot')
    sources_in = base.get('sources')
    summary = dict(summary_in) if isinstance(summary_in, dict) else {}
    swot = dict(swot_in) if isinstance(swot_in, dict) else {}
    sources = [dict(row) for row in sources_in if isinstance(row, dict)] \
        if isinstance(sources_in, list) else []
    touched = set()
    wrote_axis = wrote_swot = wrote_source = False
    for op in kept:
        name = op['op']
        if name == 'set_axis':
            if _norm(summary.get(op['key'])) != _norm(op['value']):
                summary[op['key']] = op['value']
                touched.add(op['key'])
            wrote_axis = True
        elif name == 'set_swot':
            if _norm(swot.get(op['key'])) != _norm(op['value']):
                swot[op['key']] = op['value']
                touched.add(op['key'])
            wrote_swot = True
        elif name == 'set_decision':
            if _norm(new_state.get('decision')) != op['value']:
                new_state['decision'] = op['value']
                touched.add('decision')
        elif name == 'add_sources':
            known_urls = {_norm(row.get('url')).casefold()
                          for row in sources if _norm(row.get('url'))}
            known_names = {_fold_choice(row.get('name'))
                           for row in sources if _norm(row.get('name'))}
            for row in op['rows']:
                url_key = _norm(row.get('url')).casefold()
                name_key = _fold_choice(row.get('name'))
                if url_key and url_key in known_urls:
                    continue
                if not url_key and name_key and name_key in known_names:
                    continue
                sources.append({
                    'id': str(uuid.uuid4()),
                    'name': row.get('name') or '',
                    'url': row.get('url') or '',
                    'data_date': row.get('data_date') or '',
                    'accessed_at': date.today().isoformat(),
                    'reliability': row.get('reliability') or '',
                    'note': row.get('note') or '',
                })
                if url_key:
                    known_urls.add(url_key)
                if name_key:
                    known_names.add(name_key)
                touched.add('sources')
                wrote_source = True
    if wrote_axis or isinstance(summary_in, dict):
        new_state['summary'] = summary
    if wrote_swot or isinstance(swot_in, dict):
        new_state['swot'] = swot
    if wrote_source or isinstance(sources_in, list):
        new_state['sources'] = sources
    return new_state, touched


def summary_ops_stale(touched):
    """Map a touched-field set onto the dependents that went stale.

    An axis rewrite stales the executive paragraph, the decision and SWOT;
    a swot or decision write stales the paragraph that quotes them; new
    sources alone stale nothing."""
    keys = {str(item) for item in touched} if touched else set()
    stale = {}
    if keys & _SUMMARY_CHAT_AXIS_KEYSET:
        stale.update({'one_block': True, 'decision': True, 'swot': True})
    if keys & _SUMMARY_CHAT_SWOT_KEYSET:
        stale['one_block'] = True
    if 'decision' in keys:
        stale['one_block'] = True
    return stale


def _summary_chat_first_line(value, limit=_SUMMARY_CHAT_INDEX_LINE_MAX):
    for line in str(value or '').splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ''


def _summary_chat_axis_index(summary, current_axis=None):
    """One first-line per axis — the index keeps the other axes in context
    without paying their full text."""
    if isinstance(summary, str):
        return ''
    if not isinstance(summary, dict):
        summary = {}
    lines = []
    for item in SUMMARY_SECTIONS:
        if item['key'] == current_axis:
            continue
        first = _summary_chat_first_line(summary.get(item['key']))
        lines.append(f"- {item['key']} ({item['label']}): {first or 'فارغ'}")
    return '\n'.join(lines)


def _summary_chat_sources_block(sources):
    rows = [row for row in (sources or []) if isinstance(row, dict)]
    lines = []
    for row in rows[:_SUMMARY_CHAT_SOURCES_SHOWN]:
        name = _norm(row.get('name')) or '—'
        url = _norm(row.get('url')) or '—'
        data_date = _norm(row.get('data_date') or row.get('dataDate')) or '—'
        lines.append(f'- {name} | {url} | {data_date}')
    if len(rows) > _SUMMARY_CHAT_SOURCES_SHOWN:
        lines.append(f'- … و{len(rows) - _SUMMARY_CHAT_SOURCES_SHOWN} مصدرًا إضافيًا')
    return '\n'.join(lines) if lines else '— لا مصادر بعد'


def _summary_chat_history_block(history):
    """Caller already capped the thread — render the turns as dialogue."""
    lines = []
    for item in (history or []):
        if not isinstance(item, dict):
            continue
        role = {'user': 'المستخدم', 'assistant': 'المساعد'}.get(
            str(item.get('role') or '').strip(), str(item.get('role') or '؟').strip() or '؟')
        content = str(item.get('content') or '').strip()
        if content:
            lines.append(f'{role}: {content}')
    return '\n'.join(lines) if lines else '— بداية النقاش'


def _summary_chat_flags_block(state):
    """Presence flags for the dependent outputs — the chat sees whether swot,
    decision and one_block_summary exist without paying their full text."""
    swot = state.get('swot')
    swot_present = isinstance(swot, dict) and any(
        _norm(value) and _norm(value) != MISSING_VALUE_PHRASE for value in swot.values())
    decision = _norm(state.get('decision'))
    one_block = _norm(state.get('one_block_summary') or state.get('oneBlockSummary'))
    return (
        f"- summary: {'موجود' if summary_has_content(state.get('summary')) else 'غير موجود'}\n"
        f"- swot: {'موجود' if swot_present else 'غير موجود'}\n"
        f"- decision: {decision if decision else 'غير موجود'}\n"
        f"- one_block_summary: {'موجود' if one_block else 'غير موجود'}"
    )


def _summary_chat_context_block(payload, axis, message, history, state):
    """The shared context both phases carry: project inputs plus the full
    project file, the reference axis with its current text, the other axes as
    a first-line index, dependent-output flags, sources, history, message."""
    summary = state.get('summary') if isinstance(state, dict) else {}
    if axis == SUMMARY_CHAT_AXIS_GENERAL:
        current_label = 'الملخص كاملًا — النقاش العام'
        one_block = _norm(state.get('one_block_summary') or state.get('oneBlockSummary'))
        current_text = one_block or '— لا يوجد ملخص تنفيذي بعد'
    else:
        current_label = _summary_chat_axis_label(axis)
        if isinstance(summary, dict):
            current_text = str(summary.get(axis) or '').strip() or '— لا يوجد نص لهذا المحور بعد'
        elif isinstance(summary, str) and summary.strip():
            current_text = '(ملخص قديم غير مقسّم لمحاور)\n' + summary.strip()
        else:
            current_text = '— لا يوجد نص لهذا المحور بعد'
    index = _summary_chat_axis_index(
        summary if isinstance(summary, dict) else {},
        None if axis == SUMMARY_CHAT_AXIS_GENERAL else axis)
    return (
        f'تاريخ اليوم / تاريخ الوصول للمصادر: {date.today().isoformat()}\n'
        'بيانات المشروع:\n'
        f'{_project_input_block(payload)}\n\n'
        f'محور السياق المعروض: {current_label} — key: {axis}\n'
        'النص الحالي للمحور:\n'
        f'{current_text}\n\n'
        'فهرس المحاور الأخرى (أول سطر من كل محور — للسياق فقط):\n'
        f'{index or "— المحور المعروض هو الوحيد"}\n\n'
        'حالة المخرجات التابعة:\n'
        f'{_summary_chat_flags_block(state)}\n\n'
        'جدول المصادر الحالي (الاسم | الرابط | تاريخ البيانات):\n'
        f'{_summary_chat_sources_block(state.get("sources"))}\n\n'
        'سجل هذا النقاش:\n'
        f'{_summary_chat_history_block(history)}\n\n'
        'رسالة المستخدم:\n'
        f'{str(message or "").strip()}\n'
    )


_SUMMARY_CHAT_OPS_SPEC = (
    'ops تبقى قائمة فارغة في النقاش العادي؛ استخدمها فقط عندما يطلب المستخدم '
    'تعديل نص الملخص فعلًا، واقتصر على المحور قيد النقاش ما لم يطلب المستخدم '
    'صراحةً تعديل محور آخر. الأشكال المسموحة فقط:\n'
    '- {"op":"set_axis","key":"<أحد مفاتيح المحاور أعلاه>","value":"<النص الجديد الكامل للمحور>"}\n'
    '- {"op":"set_swot","key":"strengths|weaknesses|opportunities|threats","value":"<النص الجديد للخانة>"}\n'
    '- {"op":"set_decision","value":"<إحدى قيم القرار أدناه حرفيًا — قيمة enum لا نص عرض>"}\n'
    '- {"op":"add_sources","rows":[{"name":"","url":"","data_date":"","note":"","reliability":""}]} — 8 صفوف كحد أقصى\n'
)


def build_summary_chat_system(offer_lang=None):
    """System prompt for the discuss phase: a market analyst in a scoped
    conversation about this project's summary — detects the addressed axis
    itself, asks a clarifying question when the message is ambiguous,
    proposes ops, never applies, never names sources inside reply."""
    en = offer_lang == 'en'
    prompt = (
        'أنت مستشار متخصص في دراسات السوق العقاري في المملكة العربية السعودية، '
        f'وتدير الآن نقاشًا تفاعليًا حول «{SUMMARY_TITLE}» المولّد مسبقًا لمشروع واحد.\n'
        'قواعد الجلسة:\n'
        '- أجب بلغة رسالة المستخدم — العربية للعربية والإنجليزية للإنجليزية.\n'
        '- أنت الوحيد المطّلع على ملف المشروع كاملًا — كل قسم معبّأ يصلك في السياق '
        '(الأرض والكروكي، الموقع، المكونات، المؤشرات المالية، أفضل استخدام، الفريق، '
        'المحتوى التنفيذي). استخدمه لتفهم قصد المستخدم وتحكم على سوق هذا المشروع '
        'تحديدًا، فدراسة السوق الصحيحة تقيّم المشروع الفعلي ولا تكتفي بمعلومات عامة.\n'
        '- حدّد بنفسك محور الملخص الذي تعالجه رسالة المستخدم واكتب مفتاحه في axis — '
        'المستخدم لا يختار المحور؛ استنتجه من صياغة الرسالة ومن ملف المشروع، '
        'واختر general فقط للنقاش الذي لا يخص محورًا بعينه.\n'
        '- إن كانت رسالة المستخدم غامضة أو مضللة أو يحتمل أنها تقصد أكثر من محور '
        'أو قسم معًا، فلا تخمّن: اضبط needs_clarification=true واجعل reply سؤال '
        'توضيح واحد قصير يحدد المقصود، واترك ops فارغة وneeds_research=false. '
        'وإن كانت الرسالة واضحة فلا تسأل سؤالًا توضيحيًا أصلًا.\n'
        '- النقاش محصور في ملخص سوق هذا المشروع: محاوره العشرة، تحليل SWOT، القرار، '
        'الملخص التنفيذي، وجدول المصادر. ما خرج عن هذا النطاق أجب عنه بإيجاز وبيّن أنه خارج الدراسة.\n'
        '- عند طلب تعديل فعلي في النص اقترحه عبر ops — الاقتراح يُعرض على المستخدم '
        'ولا يُطبق إلا بموافقته؛ لا تدّعِ أبدًا أن تعديلًا طُبّق أو حُفظ.\n'
        '- reply نص عادي فقط: بلا markdown ولا رموز تنسيق ولا أيقونات ولا نقاط مزخرفة.\n'
        '- ممنوع ذكر أسماء المصادر أو المواقع أو الجهات داخل reply — المصادر تُجمع '
        'في sources_add أو جدول المصادر فقط.\n'
        '- النطاق الجغرافي الملزم (حي المشروع ونطاق المنافسين المدخلان في البيانات) '
        'وفترة البيانات المحددة ملزمان لكل اقتراح ورقم: لا بيانات خارج النطاق إلا '
        'بديل الحي الأقرب الوحيد مع ذكره صراحةً، ولا مصادر خارج الفترة.\n'
        '- إن احتاج الرد بيانات ليست في الحالة المعروضة — رقم جديد، مصدر أحدث، تحقق '
        'من معلومة — اضبط needs_research=true واكتب queries دقيقة بدل التخمين، ولا '
        'تفبرك أرقامًا أبدًا.\n'
        f'- إن تعذرت المعلومة اكتب: {MISSING_VALUE_PHRASE}.\n'
        '- الدراسة أولية استرشادية وليست تقييمًا عقاريًا معتمدًا.\n'
    )
    if en:
        prompt += (
            'This project is English: write reply and every op text value in '
            'professional English. set_decision still takes one of the allowed '
            'enum values verbatim.\n'
        )
    return prompt


def build_summary_chat_turn_prompt(payload, axis, message, history, state):
    """Phase-A user prompt: the context block plus the discuss output shape —
    {reply, needs_research, queries, ops}."""
    axis = _norm(axis) or SUMMARY_CHAT_AXIS_GENERAL
    if axis not in _SUMMARY_CHAT_AXIS_KEYSET and axis != SUMMARY_CHAT_AXIS_GENERAL:
        axis = SUMMARY_CHAT_AXIS_GENERAL
    return (
        _summary_chat_context_block(payload, axis, str(message or ''), history,
                                    state if isinstance(state, dict) else {})
        + '\nأرجع JSON فقط بهذا الشكل — بلا أي نص خارج JSON:\n'
        '{\n'
        '  "reply": "ردك على المستخدم — نص عادي",\n'
        '  "axis": "مفتاح محور الملخص الذي تعالجه الرسالة — من المحاور المذكورة أعلاه أو general للعموم",\n'
        '  "needs_clarification": false,\n'
        '  "needs_research": false,\n'
        '  "queries": ["استعلام بحث دقيق عند ضبط needs_research=true"],\n'
        '  "ops": []\n'
        '}\n'
        'استنتج axis من موضوع الرسالة — من مفاتيح محاور الملخص المذكورة في الفهرس '
        'أو general. وعندما تكون الرسالة ملتبسة أو تحتمل أكثر من معنى اضبط '
        'needs_clarification=true واكتب في reply سؤال توضيح واحد قصير بدل '
        'التخمين — عندها يجب أن تبقى ops فارغة وneeds_research=false.\n'
        'اضبط needs_research=true فقط عندما يتطلب الرد بيانات حية من الويب '
        '(رقم جديد أو مصدر أو تحقق)، واكتب عندها queries دقيقة محصورة في نطاق '
        'المشروع وفترة بياناته.\n'
        + _SUMMARY_CHAT_OPS_SPEC
        + 'قيم set_decision المسموحة حصرًا: ' + '، '.join(DECISION_OPTIONS) + '.\n'
    )


def build_summary_chat_research_prompt(payload, axis, message, history, state, queries,
                                     offer_lang=None):
    """Phase-B user prompt for native Google search: the same context plus the
    queries phase A asked for, native-search instructions inside the binding
    scope/period, and the research output shape {reply, ops, sources_add}."""
    axis = _norm(axis) or SUMMARY_CHAT_AXIS_GENERAL
    if axis not in _SUMMARY_CHAT_AXIS_KEYSET and axis != SUMMARY_CHAT_AXIS_GENERAL:
        axis = SUMMARY_CHAT_AXIS_GENERAL
    query_lines = '\n'.join(
        f'- {_norm(query)}' for query in (queries or []) if _norm(query)) or '— نفس رسالة المستخدم'
    return (
        _summary_chat_context_block(payload, axis, str(message or ''), history,
                                    state if isinstance(state, dict) else {})
        + '\nاستعلامات البحث التي حددتها مرحلة النقاش:\n'
        f'{query_lines}\n\n'
        'تعليمات البحث (بحث جوجل الأصلي — بلا فتح صفحات):\n'
        '- ابحث عبر بحث جوجل الأصلي أولًا — لا تجب من الذاكرة؛ '
        'كل رقم في reply أو في ops يجب أن يستند إلى نتائج البحث.\n'
        '- التزم بفترة البيانات المحددة — أي مصدر خارج الفترة مرفوض ولا يُدرج.\n'
        + _summary_scope_block(payload, offer_lang)
        + '- كل مصدر في sources_add يحمل رابط الصفحة المحددة التي ظهرت فيها المعلومة '
        '(لا الصفحة الرئيسية للموقع) وتاريخ بياناتها كما ورد فيها.\n\n'
        'أرجع JSON فقط بهذا الشكل — بلا أي نص خارج JSON:\n'
        '{\n'
        '  "reply": "ردك على المستخدم بعد البحث — نص عادي",\n'
        '  "ops": [],\n'
        '  "sources_add": [{"name":"","url":"","data_date":"","note":"","reliability":""}]\n'
        '}\n'
        + _SUMMARY_CHAT_OPS_SPEC
        + 'قيم set_decision المسموحة حصرًا: ' + '، '.join(DECISION_OPTIONS) + '.\n'
    )


def build_summary_consolidate_prompt(state, stale_keys, offer_lang=None):
    """Consolidate pass: regenerate only the flagged dependents
    (one_block_summary / decision / swot) from the final axes and existing
    sources. A rewrite call — no browsing, no new figures; same output keys
    as the one-shot summary shape."""
    state = state if isinstance(state, dict) else {}
    if isinstance(stale_keys, dict):
        wanted = [key for key in _SUMMARY_CHAT_STALE_ORDER if stale_keys.get(key)]
    else:
        wanted = [key for key in _SUMMARY_CHAT_STALE_ORDER
                  if key in set(str(item) for item in (stale_keys or []))]
    en = offer_lang == 'en'
    summary = state.get('summary')
    summary_block = (
        json.dumps(summary, ensure_ascii=False, indent=2)
        if isinstance(summary, dict) else str(summary or '— لا يوجد')
    )
    tasks = []
    shape_lines = []
    if 'one_block' in wanted:
        tasks.append(
            f'- one_block_summary: أعد كتابة {SUMMARY_TITLE} فقرةً واحدة متماسكة '
            f'في حدود {SUMMARY_WORD_TARGET} كلمة (لا تقل عن {SUMMARY_MIN_WORDS} ولا '
            'تتجاوز 400)، تغطي المحاور النهائية بلا عناوين ولا ترقيم ولا نقاط، '
            'وبلا ذكر مصادر ولا SWOT.')
        shape_lines.append('"one_block_summary": "الفقرة المعاد توليدها"')
    if 'decision' in wanted:
        tasks.append(
            '- decision: أعد تصنيف الفرصة من المحاور النهائية إلى إحدى القيم حرفيًا: '
            + '، '.join(DECISION_OPTIONS))
        shape_lines.append('"decision": "قيمة من القائمة"')
    if 'swot' in wanted:
        tasks.append(
            '- swot: أعد كتابة خانات SWOT الأربع نقاطًا قصيرة خاصة بهذا المشروع '
            'مستندةً إلى المحاور النهائية: ' +
            '، '.join(f'{item["key"]} ({item["label"]})' for item in SWOT_SECTIONS))
        shape_lines.append('"swot": {' + ', '.join(
            f'"{item["key"]}": "..."' for item in SWOT_SECTIONS) + '}')
    current = []
    if 'one_block' in wanted:
        current.append('one_block_summary الحالي:\n'
                       + (_norm(state.get('one_block_summary')) or '— غير موجود'))
    if 'decision' in wanted:
        current.append('decision الحالي: ' + (_norm(state.get('decision')) or 'غير موجود'))
    if 'swot' in wanted:
        swot = state.get('swot') if isinstance(state.get('swot'), dict) else {}
        current.append('swot الحالي:\n' + (json.dumps(swot, ensure_ascii=False)
                                           if swot else '— غير موجود'))
    return (
        f'تاريخ اليوم: {date.today().isoformat()}\n'
        'هذه خطوة إعادة توليد للمخرجات المعلّمة فقط — بلا بحث وبلا أرقام جديدة؛ '
        'استخدم المحاور النهائية وجدول المصادر الموجودين كما هما.\n\n'
        'محاور الملخص النهائية (المعتمدة — لا تعدّلها):\n'
        f'{summary_block}\n\n'
        'جدول المصادر الحالي (للسياق فقط):\n'
        f'{_summary_chat_sources_block(state.get("sources"))}\n\n'
        + ('القيم الحالية للمخرجات المطلوب تحديثها (أعد كتابتها):\n'
           + '\n\n'.join(current) + '\n\n' if current else '')
        + 'المطلوب إعادة توليده:\n' + '\n'.join(tasks) + '\n\n'
        'قواعد النص نفسها ملزمة: بلا أيقونات أو رموز، وممنوع ذكر أسماء المصادر '
        'أو المواقع داخل القيم المعاد توليدها.\n'
        + ('Write every regenerated value in professional English.\n' if en else '')
        + '\nأرجع JSON فقط بالمفاتيح المطلوبة وحدها:\n{\n  '
        + ',\n  '.join(shape_lines)
        + '\n}\n'
    )
