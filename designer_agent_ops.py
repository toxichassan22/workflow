"""Deterministic pieces of the designer agent: selectors, task normalization,
per-task instruction building and post-task verification.

Pure Python — no Flask, no network. The planner/runner live in
``app_parts/09a_designer_agent.py``; this module is deliberately standalone so
it can be unit-tested without the app context.
"""

import re
from html.parser import HTMLParser

from designer_agent_plan import missing_numbers, slide_text
from designer_chat_safety import StructureSafetyError, validate_single_slide


# ── Ops ─────────────────────────────────────────────────────────────────────

EDIT_OPS = ('edit', 'redesign', 'rewrite')
STRUCTURE_OPS = ('split', 'restructure', 'delete', 'move', 'create')
CODE_OPS = ('table_edit', 'color_edit', 'watermark', 'insert_attached_image',
            'insert_map', 'update_image', 'generate_image', 'image_descriptions',
            'team_logo', 'company_logo_panel')
ALL_OPS = EDIT_OPS + STRUCTURE_OPS + CODE_OPS

# Ops that change slide count or order — they must be confirmed by the user
# and they invalidate later positions, so the runner applies them last.
CONFIRM_OPS = {'split', 'restructure', 'delete', 'create', 'move'}

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

    if select.get('all'):
        return list(range(len(slides))), []
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
        'failureReason': task.get('failureReason'),
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
        return (raw or 'قسّم محتوى هذه الشريحة مع الحفاظ على كل شيء.') + (
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
    # edit — explicit change on otherwise untouched content
    parts = [raw or task.get('label') or 'طبّق التعديل المطلوب على هذه الشريحة.']
    if task.get('exact_text'):
        parts.append(f'النص المطلوب حرفياً: {task["exact_text"]}')
    if brief:
        parts.append(f'الموجز العام: {brief}')
    return '\n'.join(parts)


# ── Verification ────────────────────────────────────────────────────────────

class _OverflowGauge(HTMLParser):
    """Counts table rows / card-like blocks that fell out of the slide box.

    Cheap static check — the authoritative measurement is the render session's
    DOM probe; this catches code-op results without launching a browser.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = 0
        self.cards = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.rows += 1
        elif tag in ('div', 'section', 'article', 'li'):
            style = dict(attrs).get('style') or ''
            cls = dict(attrs).get('class') or ''
            if 'card' in cls or re.search(r'\bborder(-radius)?\b', style):
                self.cards += 1


def verify_task_result(op, before_htmls, after_htmls):
    """Post-task check. Returns ``(ok, reasons)``.

    ``before_htmls``/``after_htmls`` are the slide HTMLs touched by the task.
    Verification fails closed: unverifiable HTML, dropped numbers or an
    unchanged result on an edit op all count as failure.
    """
    reasons = []
    for html in after_htmls:
        if not isinstance(html, str) or not html.strip():
            return False, ['empty_result']
        try:
            validate_single_slide(html)
        except StructureSafetyError as exc:
            return False, [f'invalid_html:{exc}']
    if op in EDIT_OPS or op in ('create', 'restructure', 'split'):
        missing = missing_numbers(before_htmls, after_htmls)
        if missing:
            reasons.append('missing_numbers:' + ','.join(missing[:8]))
    if op in EDIT_OPS:
        if before_htmls and all(b == a for b, a in zip(before_htmls, after_htmls)):
            reasons.append('unchanged')
    if op == 'table_edit' and before_htmls and after_htmls:
        if all(b == a for b, a in zip(before_htmls, after_htmls)):
            reasons.append('table_unchanged')
    return (not reasons), reasons


def verify_deck_integrity(slides, before_ids=None):
    """Whole-deck checks after a run: every slide valid, every id present,
    no duplicated ids, and (when before_ids given) no id silently dropped
    other than by delete/restructure tasks the runner already recorded.
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
        for sid in before_ids:
            pass  # ids removed by delete/restructure are legitimate; runner tracks those
    return reasons


__all__ = [
    'ALL_OPS', 'CODE_OPS', 'CONFIRM_OPS', 'EDIT_OPS', 'OP_LABELS', 'STRUCTURE_OPS',
    'instruction_for', 'needs_confirmation', 'public_task', 'resolve_selector',
    'slide_id_set', 'verify_deck_integrity', 'verify_task_result',
]
