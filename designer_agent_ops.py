"""Deterministic pieces of the designer agent: selectors, task normalization,
per-task instruction building and post-task verification.

Pure Python — no Flask, no network. The planner/runner live in
``app_parts/09a_designer_agent.py``; this module is deliberately standalone so
it can be unit-tested without the app context.
"""

import re
from collections import Counter

import designer_numbers
from designer_agent_plan import extract_visible_numbers, missing_numbers, slide_text, visible_text_nodes
from designer_chat_safety import StructureSafetyError, validate_single_slide


# ── Ops ─────────────────────────────────────────────────────────────────────

EDIT_OPS = ('edit', 'redesign', 'rewrite')
STRUCTURE_OPS = ('split', 'restructure', 'delete', 'move', 'create', 'duplicate')
CODE_OPS = ('table_edit', 'color_edit', 'watermark', 'insert_attached_image',
            'insert_map', 'update_image', 'generate_image', 'image_descriptions',
            'team_logo', 'company_logo_panel', 'renumber', 'duplicate',
            'find_replace', 'font_edit', 'financial_chart', 'ui')
ALL_OPS = EDIT_OPS + STRUCTURE_OPS + CODE_OPS

# Ops that change slide count or order — they must be confirmed by the user
# and they invalidate later positions, so the runner applies them last.
CONFIRM_OPS = {'split', 'restructure', 'delete', 'create', 'move', 'duplicate'}

OP_LABELS = {
    'edit': 'تعديل محتوى',
    'redesign': 'إعادة تصميم',
    'rewrite': 'إعادة صياغة النص',
    'split': 'تقسيم الشريحة',
    'restructure': 'إعادة هيكلة مجموعة شرائح',
    'delete': 'حذف شريحة',
    'move': 'نقل شريحة',
    'create': 'إنشاء شريحة جديدة',
    'table_edit': 'تعديل جدول',
    'color_edit': 'تعديل ألوان',
    'watermark': 'علامة مائية',
    'insert_attached_image': 'إدراج صورة مرفقة',
    'insert_map': 'إدراج خريطة',
    'update_image': 'استبدال صورة',
    'generate_image': 'توليد صورة',
    'image_descriptions': 'أوصاف الصور',
    'team_logo': 'شعار الفريق',
    'company_logo_panel': 'شعار الشركة',
    'renumber': 'ترقيم الشرائح',
    'duplicate': 'تكرار شريحة',
    'find_replace': 'استبدال نص في العرض',
    'font_edit': 'تغيير الخط',
    'financial_chart': 'إدراج مخطط مالي',
    'ui': 'إجراء في واجهة العرض',
}


# ── Selectors ───────────────────────────────────────────────────────────────

def slide_id_set(slides):
    return [s.get('id') for s in slides if isinstance(s, dict)]


def resolve_selector(select, slides, current_index=0):
    """Resolve a planner selector to sorted unique slide indexes.

    Returns ``(indexes, error)``. Selectors are id-based so they survive
    earlier mutations in the same run. Unknown ids are dropped; a selector that
    resolves to nothing returns an error instead of silently widening.
    """
    if not isinstance(select, dict):
        return [], 'missing_selector'
    id_to_index = {}
    for index, slide in enumerate(slides):
        if isinstance(slide, dict) and slide.get('id'):
            id_to_index[str(slide['id'])] = index

    def by_ids(raw_ids):
        out, missing = [], []
        for sid in raw_ids or []:
            idx = id_to_index.get(str(sid))
            if idx is None:
                missing.append(str(sid))
            else:
                out.append(idx)
        return sorted(set(out)), missing

    def except_indexes(raw):
        """«كل الشرائح ما عدا …» — the exclusion may be ids, positions or a
        nested selector dict."""
        if not raw:
            return []
        if isinstance(raw, dict):
            indexes, _ = resolve_selector(raw, slides, current_index)
            return indexes
        if not isinstance(raw, list):
            raw = [raw]
        indexes = [id_to_index[str(v)] for v in raw
                   if str(v) in id_to_index]
        indexes += [int(v) - 1 for v in raw
                    if isinstance(v, int) and 1 <= v <= len(slides)
                    and str(v) not in id_to_index]
        return sorted(set(indexes))

    if select.get('all'):
        excluded = set(except_indexes(select.get('except')))
        return [i for i in range(len(slides)) if i not in excluded], []
    if select.get('current'):
        idx = min(max(int(current_index or 0), 0), max(len(slides) - 1, 0))
        return ([idx] if slides else []), []
    if isinstance(select.get('range'), (list, tuple)) and len(select['range']) == 2:
        lo_id, hi_id = str(select['range'][0]), str(select['range'][1])
        lo, hi = id_to_index.get(lo_id), id_to_index.get(hi_id)
        if lo is None or hi is None:
            return [], 'range_endpoint_missing'
        if lo > hi:
            lo, hi = hi, lo
        return list(range(lo, hi + 1)), []
    if select.get('section'):
        wanted = str(select['section']).strip()
        indexes = []
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            section = str(slide.get('section') or slide.get('section_key')
                          or slide.get('type') or '').strip()
            if section and section == wanted:
                indexes.append(index)
        return indexes, ([] if indexes else ['section_not_found'])
    indexes, missing = by_ids(select.get('ids'))
    if not indexes:
        return [], 'selector_empty' if not missing else 'ids_not_found'
    return indexes, missing


# ── Task shaping ─────────────────────────────────────────────────────────────

def public_task(task):
    """Checklist row — display fields plus the execution fields the client
    echoes back on retry/continue. Never carries HTML."""
    return {
        'n': task.get('n'),
        'op': task.get('op'),
        'label': task.get('label') or OP_LABELS.get(task.get('op'), task.get('op') or ''),
        'slides': list(task.get('slides') or []),
        'titles': list(task.get('titles') or []),
        'status': task.get('status', 'pending'),
        'failureReason': (failure_reason_text(task.get('failureReason'))
                          if task.get('failureReason') else None),
        'instruction': task.get('instruction') or '',
        'style_brief': task.get('style_brief') or '',
        'params': dict(task.get('params') or {}),
        'parts': task.get('parts'),
        'target_count': task.get('target_count'),
        'after': task.get('after'),
        'title': task.get('title'),
        'type': task.get('type'),
        'exact_text': task.get('exact_text'),
    }


def needs_confirmation(task):
    if task.get('op') in CONFIRM_OPS:
        return True
    params = task.get('params') or {}
    return bool(params.get('confirm'))


def instruction_for(task, style_brief=''):
    """The worker instruction for one task — one slide, one job."""
    op = task.get('op')
    params = task.get('params') or {}
    raw = task.get('instruction') or params.get('instruction') or ''
    brief = (style_brief or '').strip()

    if op == 'redesign':
        base = f'أعد تصميم هذه الشريحة بالكامل وفق الموجز التالي، مع الحفاظ على كل الحقائق والأرقام والنصوص الجوهرية: {brief or raw or "حسّن التصميم"}'
        if raw and raw != brief:
            base += f'\nملاحظات إضافية: {raw}'
        return base
    if op == 'rewrite':
        return (raw or 'أعد صياغة نص هذه الشريحة بشكل أوضح.') + (
            f'\nالموجز العام: {brief}' if brief else '')
    if op == 'split':
        return (raw or 'قسّم محتوى هذه الشريحة إلى أجزاء بتوزيع عناصرها عليها — لا تنسخها.') + (
            f'\nالموجز العام: {brief}' if brief else '')
    if op == 'create':
        title = task.get('title') or params.get('title') or ''
        return (raw or f'أنشئ شريحة جديدة بعنوان «{title}».' if title else raw or 'أنشئ شريحة جديدة.') + (
            f'\nالموجز العام: {brief}' if brief else '')
    if op == 'table_edit':
        column = params.get('column') or params.get('column_title') or ''
        row = params.get('row') or params.get('row_index')
        bits = []
        if column:
            bits.append(f'احذف عمود «{column}»')
        if row is not None:
            bits.append(f'احذف الصف رقم {row}')
        return '، '.join(bits) or raw or 'عدّل الجدول كما طلب المستخدم.'
    if op == 'color_edit':
        frm, to = params.get('from'), params.get('to')
        if frm and to:
            return f'استبدل اللون {frm} باللون {to}'
        return raw or 'عدّل الألوان كما طلب المستخدم.'
    if op == 'watermark':
        return params.get('action') or raw or ''
    if op in ('insert_map', 'update_image', 'generate_image', 'team_logo',
              'company_logo_panel', 'insert_attached_image', 'image_descriptions'):
        return raw or task.get('label') or OP_LABELS.get(op, op)
    if op == 'renumber':
        return raw or 'صحّح رقم الصفحة الظاهر على الشرائح المحددة لتطابق ترتيبها الحالي.'
    if op == 'financial_chart':
        chart_type = params.get('chart_type') or params.get('chart') or 'waterfall'
        kind_label = ('شلالي (waterfall)' if str(chart_type).lower() in ('waterfall', 'شلالي')
                      else f'مالي من نوع {chart_type}')
        return (raw or f'أنشئ في هذه الشريحة مخططًا {kind_label} من بيانات المشروع المالية '
                       'مع الحفاظ على كل محتوى الشريحة.') + (
            f'\nالموجز العام: {brief}' if brief else '')
    if op == 'find_replace':
        return f'استبدل «{params.get("from") or params.get("find") or ""}» بـ «{params.get("to") or params.get("replace") or ""}»'
    if op == 'font_edit':
        return f'غيّر خط الشريحة إلى {params.get("font") or "الخط المطلوب"}'
    if op == 'ui':
        return raw or params.get('action') or ''
    if op == 'duplicate':
        return raw or 'كرر الشريحة.'
    # edit — explicit change on otherwise untouched content
    parts = [raw or task.get('label') or 'طبّق التعديل المطلوب على هذه الشريحة.']
    if task.get('exact_text'):
        parts.append(f'النص المطلوب حرفياً: {task["exact_text"]}')
    if brief:
        parts.append(f'الموجز العام: {brief}')
    return '\n'.join(parts)


# ── Verification ────────────────────────────────────────────────────────────

_MANAGED_DATA_ATTRS = re.compile(
    r'^data-(slide-|landloom-|agent-|designer-|footer|counter)', re.IGNORECASE)
_MEDIA_SRC_RE = re.compile(
    r'<(?:img|source|video|iframe)\b[^>]*?\b(?:src|poster)\s*=\s*["\']([^"\']+)',
    re.IGNORECASE | re.DOTALL)
_MEDIA_CSS_RE = re.compile(r'url\(\s*["\']?([^)"\']+)["\']?\s*\)', re.IGNORECASE)
_DATA_ATTR_RE = re.compile(r'\b(data-[\w:-]+)\s*=', re.IGNORECASE)
_TR_RE = re.compile(r'<tr\b', re.IGNORECASE)
_TOKEN_RE = re.compile(r'##[A-Z][A-Z0-9_-]{2,}##')
# Requests that explicitly authorize losing content — «احذف الصورة» may drop an
# image, «استبدل النص» may drop sentences. Numbers stay checked regardless.
_TEXT_CHANGE_INTENT_RE = re.compile(
    r'استبدل|بدّل|بدل|غيّر\s+(?:النص|العنوان|الكلام)|أعد\s+صياغ|لخّص|اختصر|قصّر|'
    r'احذف|امسح|شيل|أزل|ترجمة|ترجم|replace|rewrite|summari[sz]e|translate|rephrase',
    re.IGNORECASE)
_MEDIA_REMOVE_INTENT_RE = re.compile(
    r'احذف|امسح|شيل|أزل|إزالة|حذف|remove|delete', re.IGNORECASE)
_MEDIA_KIND_WORDS_RE = re.compile(
    r'صور|صورة|الصور|خريطة|خرائط|الخريطة|خلفي|أيقون|شعار|فيديو|'
    r'image|images|picture|map|maps|background|logo|video|icon', re.IGNORECASE)


def _media_key(url):
    url = str(url or '').strip()
    if not url or url.startswith('#') or url.startswith('javascript:'):
        return ''
    if url.startswith('data:'):
        # A base64 payload cannot be diffed literally — fingerprint it so a
        # byte-identical carry-over matches while a swapped asset does not.
        head, _, payload = url.partition(',')
        mime = head[5:].split(';')[0] or 'bin'
        return f'data:{mime}:{len(payload)}'
    return url.split('#')[0].split('?')[0]


def _media_profile(html):
    """Multiset of visible media references (images, css urls, video, iframe)."""
    profile = Counter()
    for url in _MEDIA_SRC_RE.findall(html or ''):
        key = _media_key(url)
        if key:
            profile[key] += 1
    for url in _MEDIA_CSS_RE.findall(html or ''):
        key = _media_key(url)
        if key and not key.startswith('data:'):
            profile[key] += 1
        elif key:
            profile[key] += 1
    return profile


def _token_profile(html):
    """##MAP_1## / ##TEAM_LOGO_2## / ##PRESERVED_BASE64_3## style placeholders."""
    return Counter(_TOKEN_RE.findall(html or ''))


def _data_attr_profile(html):
    return Counter(
        name.lower() for name in _DATA_ATTR_RE.findall(html or '')
        if not _MANAGED_DATA_ATTRS.match(name))


def _text_items(html):
    """Logical text units — block-level items, not raw parser nodes."""
    try:
        from designer_chat_safety import _Inventory
        inventory = _Inventory(html)
        return [item for item in inventory.text_items if str(item).strip()]
    except Exception:
        return [part for part in re.split(r'\s{2,}|\n+', slide_text(html) or '')
                if part.strip()]


def _norm_text(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


# Ops where the markup structure itself must survive: edit ops and the
# deterministic insert/annotate ops all promise «change nothing else». A
# redesign/restructure/split owns the markup and is exempt from the row count —
# the text/number/media checks above still cover real content loss.
_ROW_STRICT_OPS = {
    'edit', 'generate_image', 'update_image', 'watermark', 'insert_map',
    'insert_attached_image', 'image_descriptions', 'team_logo',
    'company_logo_panel', 'font_edit', 'renumber', 'rewrite',
}


def _edit_preservation_reasons(op, before_html, after_html, request_text,
                               excused_numbers=None):
    """Content a worker rewrite must keep: media, table rows, data-* hooks,
    reserved tokens and (unless the request retires it) every text item."""
    reasons = []
    request_text = str(request_text or '')
    text_may_change = op == 'rewrite' or bool(_TEXT_CHANGE_INTENT_RE.search(request_text))
    media_may_drop = bool(
        _MEDIA_REMOVE_INTENT_RE.search(request_text)
        and _MEDIA_KIND_WORDS_RE.search(request_text))

    before_media, after_media = _media_profile(before_html), _media_profile(after_html)
    dropped_media = before_media - after_media
    if dropped_media and not media_may_drop:
        sample = next(iter(dropped_media))
        if sample.startswith('data:'):
            sample = sample[:60]
        reasons.append(f'dropped_media:{sample[:80]}')

    before_tokens, after_tokens = _token_profile(before_html), _token_profile(after_html)
    dropped_tokens = before_tokens - after_tokens
    if dropped_tokens:
        # A resolved token is fine — the placeholder may have turned into a
        # real asset — as long as new media appeared to take its place.
        new_media = after_media - before_media
        if len(dropped_tokens) > sum(new_media.values()):
            reasons.append('dropped_tokens:' + ','.join(list(dropped_tokens)[:5]))

    before_rows = len(_TR_RE.findall(before_html or ''))
    after_rows = len(_TR_RE.findall(after_html or ''))
    # Row strictness applies to surgical ops only — a «redesign» may legitimately
    # turn a table into cards, and a deterministic table_edit decides rows itself.
    if op in _ROW_STRICT_OPS and before_rows > after_rows and not media_may_drop:
        reasons.append(f'dropped_rows:{before_rows - after_rows}')

    dropped_attrs = _data_attr_profile(before_html) - _data_attr_profile(after_html)
    if dropped_attrs:
        reasons.append('dropped_data_attrs:' + ','.join(list(dropped_attrs)[:5]))

    if not text_may_change:
        after_text = _norm_text(slide_text(after_html))
        # Compare digit-normalized so a reformatted «120,000»→«120000» is not a drop.
        after_flat = re.sub(r'[,\s]', '', after_text)
        # A number the missing-numbers check already excused — or one the
        # request itself named — may retire with the words carrying it.
        allowed_flat = {re.sub(r'[,\s]', '', str(n)) for n in (excused_numbers or set())}
        allowed_flat.update(re.sub(r'[,\s]', '', w)
                            for w in re.findall(r'\d[\d,.]*', request_text))
        dropped = []
        for item in _text_items(before_html):
            item = _norm_text(item)
            if len(item) < 12:
                continue
            if item in after_text or re.sub(r'[,\s]', '', item) in after_flat:
                continue
            words = item.split()
            missing_idx = [i for i, w in enumerate(words)
                           if re.sub(r',', '', w) not in after_flat]
            if not missing_idx:
                continue
            # An excused number and the label words next to it retire together —
            # «الهاتف 0111»→«الهاتف 0222» is a sanctioned update, not a lost
            # sentence. Anything else missing flags the item as dropped.
            excused = set()
            for i in missing_idx:
                if re.sub(r'[,\s]', '', words[i]) in allowed_flat:
                    excused.update({i - 1, i, i + 1})
            if [words[i] for i in missing_idx if i not in excused]:
                dropped.append(item[:60])
                if len(dropped) >= 3:
                    break
        if dropped:
            reasons.append('dropped_text:' + '،'.join(dropped))
    return reasons


def _excused_missing_numbers(missing, before_htmls, after_htmls,
                             allowed_numbers, request_text):
    """Filter out numbers the request itself retired.

    ``allowed_numbers`` carries tokens of project values a fresher draft
    superseded — the slide can still display the old figure, so its removal is
    an authorized replacement. Numbers the user or planner wrote into the
    message, instruction or exact_text are authorized the same way. Finally, a
    number the request never named may still drop when the task mandated a
    brand-new value that landed in the result: «غيّر الهاتف إلى X» retires the
    old phone — but only as many drops as values introduced, so an unrelated
    figure can never slip through.
    """
    # Callers may hand raw values («1,200», «٠١١١»); compare them as atoms.
    allowed = set()
    for value in allowed_numbers or ():
        allowed.update(designer_numbers.number_atoms(value) or [str(value)])
    if request_text and str(request_text).strip():
        allowed |= set(extract_visible_numbers(request_text).keys())
    residual = [n for n in missing if n not in allowed]
    if not residual or not request_text or not str(request_text).strip():
        return residual
    before, after = Counter(), Counter()
    for html in before_htmls or []:
        before |= extract_visible_numbers(html)
    for html in after_htmls or []:
        after |= extract_visible_numbers(html)
    mandated = {tok for tok in extract_visible_numbers(request_text)
                if after.get(tok) and not before.get(tok)}
    return [] if len(residual) <= len(mandated) else residual


def verify_task_result(op, before_htmls, after_htmls,
                       allowed_numbers=None, request_text='', exact_text=None):
    """Post-task check. Returns ``(ok, reasons)``.

    ``before_htmls``/``after_htmls`` are the slide HTMLs touched by the task.
    Verification fails closed: unverifiable HTML, dropped numbers or an
    unchanged result on an edit op all count as failure. ``allowed_numbers``
    and ``request_text`` mark the drops a value-update is authorized to make.
    ``exact_text`` is content the user demanded verbatim — its absence from
    the result is a failure no excuse lifts.
    """
    reasons = []
    for html in after_htmls:
        if not isinstance(html, str) or not html.strip():
            return False, ['empty_result']
        try:
            validate_single_slide(html)
        except StructureSafetyError as exc:
            return False, [f'invalid_html:{exc}']
    # Restructure/split already ran their own preservation gate inside the
    # executor (require_facts_preserved/require_preserved). Recounting
    # occurrences here would reject a legitimate merge that deduplicates
    # repeated figures — the executor check is the authority for those ops.
    excused_numbers = set()
    if op in EDIT_OPS or op in ('create', 'financial_chart'):
        raw_missing = missing_numbers(before_htmls, after_htmls)
        missing = _excused_missing_numbers(
            raw_missing, before_htmls, after_htmls, allowed_numbers, request_text) \
            if raw_missing else []
        excused_numbers = set(raw_missing or []) - set(missing or [])
        if missing:
            reasons.append('missing_numbers:' + ','.join(missing[:8]))
    if op in EDIT_OPS:
        if before_htmls and all(b == a for b, a in zip(before_htmls, after_htmls)):
            reasons.append('unchanged')
    if op == 'table_edit' and before_htmls and after_htmls:
        if all(b == a for b, a in zip(before_htmls, after_htmls)):
            reasons.append('table_unchanged')
    # An edit must not silently lose pictures, table rows, data-* hooks or
    # sentences — the runner used to check numbers only, so a rewrite that
    # dropped «الصورة والجدول» reported success.
    if op in EDIT_OPS or op == 'financial_chart':
        for before, after in zip(before_htmls or [], after_htmls or []):
            if isinstance(before, str) and before.strip() and isinstance(after, str):
                reasons.extend(_edit_preservation_reasons(
                    op, before, after, request_text, excused_numbers=excused_numbers))
    if exact_text and str(exact_text).strip():
        wanted = _norm_text(exact_text)
        joined = ' '.join(_norm_text(slide_text(html)) for html in after_htmls or [])
        if wanted and wanted not in joined:
            reasons.append('exact_text_missing')
    return (not reasons), reasons


# ── Retry policy ────────────────────────────────────────────────────────────
# A failed attempt is worth another model call only when the model can do
# something different: a verification rejection it can repair from the
# feedback below, or a transient provider/parse failure. Deterministic code
# ops, missing assets and selector errors fail identically on every attempt,
# and billing errors must stop the run (the runner checks those separately).

_WORKER_TASK_OPS = frozenset(EDIT_OPS + ('split', 'restructure', 'create',
                                         'team_logo', 'company_logo_panel',
                                         'financial_chart'))
_RETRYABLE_CODES = frozenset({
    'missing_numbers', 'facts_not_preserved', 'content_not_preserved',
    'split_not_partitioned', 'incomplete_result', 'invalid_slide_html',
    'invalid_html', 'empty_result', 'empty_worker_result', 'unchanged',
    'no_material_change', 'measured_overflow', 'clipped', 'verification_failed',
    'provider_error', 'exception', 'finalize_failed', 'generation_failed',
    'worker_failed', 'dropped_text', 'dropped_media', 'dropped_rows',
    'dropped_data_attrs', 'dropped_tokens', 'exact_text_missing',
    'image_not_placed',
})


def reason_codes(reason):
    """``'missing_numbers:5;clipped:div:40px'`` gives ``['missing_numbers', 'clipped']``."""
    return [part.strip().partition(':')[0].strip()
            for part in str(reason or '').split(';') if part.strip()]


def is_retryable_failure(op, reason, rejected_by_check=False):
    """True when another worker attempt could plausibly succeed.

    ``rejected_by_check`` marks a result the executor produced and the
    verification or layout measurement rejected — the model can always try
    to repair that. An executor failure retries only on the known transient
    or repairable codes.
    """
    if op not in _WORKER_TASK_OPS:
        return False
    if rejected_by_check:
        return True
    codes = reason_codes(reason)
    return bool(codes) and set(codes) <= _RETRYABLE_CODES


_FACT_KIND_TEXT = {'row': 'صفوف جداول', 'media': 'صور أو خرائط', 'data': 'روابط فهرس',
                   'entities': 'أسماء جهات أو مشاريع'}


def _missing_numbers_note(atoms, before_htmls):
    nodes = [node for html in before_htmls or [] for node in visible_text_nodes(html)]
    pairs = designer_numbers.atom_contexts(nodes, atoms)
    listed = '، '.join(f'«{atom}» (في: «{context}»)' if context else f'«{atom}»'
                       for atom, context in pairs[:10])
    return ('المحاولة السابقة أسقطت قيمًا رقمية موجودة في الشريحة الأصلية: ' + listed
            + ' — أعد كل قيمة منها كما وردت حرفيًا وبنفس صيغتها، ولا تحذف أي رقم آخر.')


def retry_feedback(reason, before_htmls=None, measure_report=None):
    """Arabic correction note for the next attempt.

    The old note was «النتيجة رُفضت تحققاً: missing_numbers:9/20275» — a code
    the worker cannot act on. This names what was wrong in terms the worker
    can fix: each dropped value with the source text it lived in, the element
    that left the frame with its text, the structural contract it broke.
    Transient provider failures add nothing — the retry itself is the fix.
    """
    notes = []
    for part in str(reason or '').split(';'):
        code, _, detail = part.strip().partition(':')
        code = code.strip()
        if not code:
            continue
        if code == 'missing_numbers':
            atoms = [atom for atom in detail.split(',') if atom.strip()]
            if atoms:
                notes.append(_missing_numbers_note(atoms, before_htmls))
        elif code == 'facts_not_preserved':
            kinds, _, sample = detail.partition(':')
            if kinds.strip() == 'numbers':
                atoms = [atom for atom in sample.split(',') if atom.strip()]
                notes.append(_missing_numbers_note(atoms, before_htmls))
            else:
                label = '، '.join(_FACT_KIND_TEXT.get(k, k) for k in kinds.split('+') if k)
                notes.append(f'المحاولة السابقة أسقطت عناصر من المصدر ({label}): {sample[:300]}'
                             ' — أعد كل عنصر منها كما ورد.')
        elif code == 'split_not_partitioned':
            notes.append('المحاولة السابقة أعادت الشريحة نفسها (أو معظمها) في أكثر من جزء — '
                         'التقسيم يعني توزيع العناصر على الأجزاء لا تكرارها: كل جزء يحمل حصته '
                         'وحدها ولا يعيد الشريحة كاملة.')
        elif code == 'content_not_preserved':
            notes.append('المحاولة السابقة لم تنقل كل نصوص المصدر وصفوفه وصوره مرة واحدة دون تكرار'
                         ' — انقل كل عنصر حرفيًا إلى موضع واحد فقط.')
        elif code in ('unchanged', 'no_material_change'):
            notes.append('المحاولة السابقة أعادت الشريحة دون تغيير ظاهر — طبّق التعديل المطلوب فعليًا'
                         ' مع الحفاظ على كل المحتوى.')
        elif code == 'incomplete_result':
            notes.append('المحاولة السابقة لم تُرجع العدد المطلوب من الشرائح بمحتوى مكتمل — أعد العدد'
                         ' المطلوب بالضبط.')
        elif code in ('clipped', 'measured_overflow'):
            clipped = (measure_report or {}).get('clipped') if isinstance(measure_report, dict) else None
            first = clipped[0] if isinstance(clipped, list) and clipped and isinstance(clipped[0], dict) else {}
            where = f' وهو يحمل النص «{str(first.get("text") or "")[:60]}»' if first.get('text') else ''
            amount = f' بمقدار {first.get("overPx")}px' if first.get('overPx') else ''
            notes.append(f'في المحاولة السابقة خرج محتوى عن إطار الشريحة 1280x720{amount}{where}'
                         ' — صغّر الخطوط والمسافات أو أعد توزيع العناصر حتى يبقى كل شيء داخل الإطار'
                         ' دون حذف أي نص أو رقم.')
        elif code in ('invalid_html', 'invalid_slide_html', 'empty_result', 'empty_worker_result'):
            notes.append('المحاولة السابقة لم تُرجع شريحة HTML صالحة — أعد JSON صحيحًا فيه شريحة واحدة'
                         ' بجذر <div class="slide"> وكل الوسوم مغلقة ومتوازنة.')
        elif code == 'dropped_text':
            notes.append(f'المحاولة السابقة أسقطت نصوصًا كانت موجودة في الشريحة الأصلية: «{detail[:180]}»'
                         ' — أعد كل نص ورد في الأصل ما لم يطلب المستخدم تغييره صراحة.')
        elif code == 'dropped_media':
            notes.append('المحاولة السابقة أزالت صورة أو وسيطًا كان موجودًا في الشريحة الأصلية'
                         ' — أبقِ كل الصور والخرائط والوسائط كما هي وأدرجها في الناتج.')
        elif code == 'dropped_rows':
            notes.append(f'المحاولة السابقة حذفت {detail} من صفوف الجدول الأصلية'
                         ' — أبقِ كل الصفوف كما وردت ما لم يطلب المستخدم حذفها صراحة.')
        elif code == 'dropped_data_attrs':
            notes.append(f'المحاولة السابقة أسقطت خصائص data-* كانت في الشريحة ({detail[:120]})'
                         ' — أعدها على العناصر نفسها في الناتج.')
        elif code == 'dropped_tokens':
            notes.append(f'المحاولة السابقة حذفت عناصر محجوزة في الشريحة ({detail[:120]})'
                         ' — أبقِ الرموز ##…## كما هي في مواضعها دون تغيير.')
        elif code == 'exact_text_missing':
            notes.append('النص الذي طلبه المستخدم حرفيًا غير موجود في النتيجة — أدرجه بنصه كما طلب.')
        elif code == 'image_not_placed':
            notes.append('الصورة المولّدة لم تدخل في HTML الشريحة — أدرج رابط الصورة المرفق في عنصر '
                         '<img> أو خلفية داخل الشريحة.')
        elif code in ('provider_error', 'exception', 'finalize_failed', 'generation_failed',
                      'worker_failed', 'verification_failed'):
            continue
        else:
            text = failure_reason_text(part)
            if text != _FAILURE_REASON_FALLBACK:
                notes.append(text)
    return ' '.join(dict.fromkeys(note for note in notes if note))


def verify_deck_integrity(slides, before_ids=None, removed_ok=None):
    """Whole-deck checks after a run: every slide valid, every id present,
    no duplicated ids, and (when before_ids given) no id silently dropped
    other than the ones delete/restructure tasks legitimately consumed —
    the runner passes those in ``removed_ok``.
    """
    reasons = []
    seen = set()
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            reasons.append(f'slide_{index}_not_dict')
            continue
        sid = slide.get('id')
        if not sid:
            reasons.append(f'slide_{index}_missing_id')
        elif sid in seen:
            reasons.append(f'duplicate_id:{sid}')
        else:
            seen.add(sid)
        try:
            validate_single_slide(slide.get('html'))
        except StructureSafetyError as exc:
            reasons.append(f'slide_{index}_invalid:{exc}')
    if before_ids:
        removed_ok = set(removed_ok or ())
        for sid in before_ids:
            if sid and sid not in seen and sid not in removed_ok:
                reasons.append(f'dropped_id:{sid}')
    return reasons


# ── Failure-reason display text ─────────────────────────────────────────────
# Internal reason codes (missing_numbers:…, ids_not_found, clipped:…) are for
# logs, checkpoints and the machine-readable ``failureReason`` field — never
# for the chat bubble or the checklist row, where only Arabic display text
# belongs. Reasons the runner joins with «;» are split and each part mapped;
# worker notes already written in Arabic pass through untouched.

_FAILURE_REASON_TEXT = {
    'missing_selector': 'لم يحدد الطلب شريحة قابلة للتنفيذ.',
    'selector_empty': 'لم يحدد الطلب شريحة قابلة للتنفيذ.',
    'ids_not_found': 'لم يُعثر على الشرائح المطلوبة في العرض الحالي.',
    'missing_slide': 'لم يُعثر على الشريحة المطلوبة في العرض الحالي.',
    'range_endpoint_missing': 'تعذر تحديد نطاق الشرائح المطلوب.',
    'section_not_found': 'لم يُعثر على القسم المطلوب في العرض.',
    'non_contiguous_sources': 'الشرائح المحددة غير متجاورة فتعذرت إعادة هيكلتها معًا.',
    'unknown_after_id': 'موضع الإدراج المحدد غير موجود في العرض.',
    'no_target_slide': 'لم يُعثر على شريحة مستهدفة صالحة.',
    'invalid_indexes': 'رقم الشريحة المحدد خارج العرض أو غير واضح.',
    'invalid_position': 'موضع الإدراج المحدد غير صالح.',
    'invalid_parts': 'عدد الأجزاء المطلوب غير صالح.',
    'invalid_target_count': 'عدد الشرائح الهدف غير صالح.',
    'invalid_slide_html': 'بنية الشريحة لا تسمح بالتحقق الآمن من المحتوى.',
    'invalid_html': 'لم يُرجع المصمم شريحة HTML صالحة.',
    'incomplete_result': 'النتيجة غير مكتملة أو لم تتغير.',
    'content_not_preserved': 'النتيجة لم تحتفظ بكامل محتوى الشرائح الأصلية فرُفضت.',
    'split_not_partitioned': 'الأجزاء الناتجة مكررة أو غير منفصلة.',
    'empty_result': 'لم تُرجع المحاولة شريحة صالحة.',
    'empty_worker_result': 'لم يُرجع المصمم نتيجة صالحة.',
    'unknown_structure_tool': 'العملية المطلوبة غير معروفة.',
    'unknown_code_op': 'العملية المطلوبة غير معروفة.',
    'unchanged': 'أعاد المصمم الشريحة نفسها دون تغيير قابل للتحقق.',
    'no_material_change': 'أعاد المصمم الشريحة نفسها دون تغيير قابل للتحقق.',
    'table_unchanged': 'لم يتغير الجدول.',
    'color_unchanged': 'لم يتغير لون الشريحة.',
    'watermark_unchanged': 'لم تتغير العلامة المائية.',
    'image_unchanged': 'لم تتغير الصورة في الشريحة.',
    'map_unchanged': 'لم تتغير الخريطة في الشريحة.',
    'renumber_unchanged': 'ترقيم الشرائح الظاهر صحيح بالفعل.',
    'watermark_missing': 'لا توجد علامة مائية مرفوعة في إعدادات الشركة.',
    'map_missing': 'لا توجد خريطة معتمدة من هذا النوع.',
    'asset_missing': 'الأصل البصري المطلوب غير موجود في المشروع.',
    'attached_image_missing': 'لا توجد صورة مرفقة بهذه الرسالة بالترتيب المطلوب.',
    'no_missing_descriptions': 'لا توجد أوصاف ناقصة لإضافتها.',
    'cannot_delete_all': 'لا يمكن حذف كل شرائح العرض.',
    'cancelled': 'أُلغيت المهمة.',
    'billing_stopped': 'توقفت المهمة لاستنفاد رصيد الشركة.',
    'measured_overflow': 'النتيجة تجاوزت حدود إطار الشريحة فرُفضت.',
    'clipped': 'عناصر في النتيجة خرجت عن إطار الشريحة فرُفضت.',
    'worker_failed': 'تعذر تنفيذ المهمة على الشريحة.',
    'verification_failed': 'رُفضت النتيجة في التحقق.',
    'dropped_boundary_data': 'النتيجة أسقطت أطوال حدود موثقة فرُفضت.',
    'boundary_data_unchanged': 'أحدث بيانات الحدود مطابقة لما هو ظاهر بالفعل في الشريحة.',
    'maps_link_missing': 'لا يوجد رابط خرائط محفوظ في بيانات هذا المشروع.',
    'generation_failed': 'تعذر توليد النتيجة.',
    'finalize_failed': 'تعذر تجهيز نتيجة الشريحة.',
    'provider_error': 'تعذر الحصول على نتيجة صالحة من المصمم.',
    'image_generation_failed': 'تعذر توليد الصورة حاليًا.',
    'exception': 'حدث خطأ أثناء تنفيذ المهمة.',
    'unknown': 'تعذر تنفيذ المهمة.',
    'dropped_text': 'النتيجة أسقطت جزءًا من نص الشريحة الأصلي فرُفضت.',
    'dropped_media': 'النتيجة أزالت صورة أو وسيطًا كان في الشريحة فرُفضت.',
    'dropped_rows': 'النتيجة حذفت صفوفًا من الجدول دون طلب فرُفضت.',
    'dropped_data_attrs': 'النتيجة أسقطت خصائص data- المطلوبة في الشريحة فرُفضت.',
    'dropped_tokens': 'النتيجة فقدت عناصر محجوزة كانت في الشريحة فرُفضت.',
    'exact_text_missing': 'النص المطلوب حرفيًا غير موجود في النتيجة.',
    'image_not_placed': 'الصورة المولّدة لم تُدرج في الشريحة.',
    'find_replace_not_found': 'النص المطلوب استبداله غير موجود في الشرائح المحددة.',
    'font_unchanged': 'لم يتغير خط الشريحة.',
    'missing_replace_target': 'لم يُحدد الطلب النص المطلوب استبداله.',
    'unsupported_op': 'هذه العملية غير مدعومة حاليًا في المصمم.',
}

_FAILURE_REASON_FALLBACK = 'تعذر تنفيذ المهمة — أعد المحاولة بعد قليل.'
_ARABIC_TEXT_RE = re.compile(r'[؀-ۿ]')


def _failure_reason_part_text(part):
    code, _, detail = part.partition(':')
    code = code.strip()
    if code == 'missing_numbers':
        numbers = '، '.join(n for n in detail.split(',') if n.strip())[:120]
        return ('النتيجة أسقطت أرقامًا من المحتوى الأصلي'
                + (f' ({numbers})' if numbers else '')
                + ' فرُفضت حفاظًا على بيانات العرض.')
    if code == 'facts_not_preserved':
        kinds, _, sample = detail.partition(':')
        if kinds.strip() == 'numbers' and sample.strip():
            numbers = '، '.join(n for n in sample.split(',') if n.strip())[:120]
            return f'النتيجة لم تحتفظ بكل أرقام المحتوى الأصلي ({numbers}) فرُفضت.'
        return 'النتيجة لم تحتفظ بكل حقائق المحتوى الأصلي فرُفضت.'
    if code == 'table_precheck':
        return detail.strip() or _FAILURE_REASON_FALLBACK
    if code in _FAILURE_REASON_TEXT:
        return _FAILURE_REASON_TEXT[code]
    if _ARABIC_TEXT_RE.search(part):
        return part
    return _FAILURE_REASON_FALLBACK


def failure_reason_text(reason):
    """Arabic display text for an internal failure-reason string."""
    out = []
    for chunk in str(reason or '').split(';'):
        text = _failure_reason_part_text(chunk.strip())
        if text and text not in out:
            out.append(text)
    return ' '.join(out) or _FAILURE_REASON_FALLBACK


__all__ = [
    'ALL_OPS', 'CODE_OPS', 'CONFIRM_OPS', 'EDIT_OPS', 'OP_LABELS', 'STRUCTURE_OPS',
    'failure_reason_text', 'instruction_for', 'is_retryable_failure', 'needs_confirmation',
    'public_task', 'reason_codes', 'resolve_selector', 'retry_feedback', 'slide_id_set',
    'verify_deck_integrity', 'verify_task_result',
]
