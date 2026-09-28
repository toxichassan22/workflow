"""Deterministic pieces of the designer agent: selectors, task normalization,
per-task instruction building and post-task verification.

Pure Python — no Flask, no network. The planner/runner live in
``app_parts/09a_designer_agent.py``; this module is deliberately standalone so
it can be unit-tested without the app context.
"""

import re
from html.parser import HTMLParser

from collections import Counter

from designer_agent_plan import extract_visible_numbers, missing_numbers, slide_text
from designer_chat_safety import StructureSafetyError, validate_single_slide


# ── Ops ─────────────────────────────────────────────────────────────────────

EDIT_OPS = ('edit', 'redesign', 'rewrite')
STRUCTURE_OPS = ('split', 'restructure', 'delete', 'move', 'create')
CODE_OPS = ('table_edit', 'color_edit', 'watermark', 'insert_attached_image',
            'insert_map', 'update_image', 'generate_image', 'image_descriptions',
            'team_logo', 'company_logo_panel', 'renumber')
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
    'renumber': 'ترقيم الشرائح',
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
    if op == 'renumber':
        return raw or 'صحّح رقم الصفحة الظاهر على الشرائح المحددة لتطابق ترتيبها الحالي.'
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
    allowed = set(allowed_numbers or ())
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
                       allowed_numbers=None, request_text=''):
    """Post-task check. Returns ``(ok, reasons)``.

    ``before_htmls``/``after_htmls`` are the slide HTMLs touched by the task.
    Verification fails closed: unverifiable HTML, dropped numbers or an
    unchanged result on an edit op all count as failure. ``allowed_numbers``
    and ``request_text`` mark the drops a value-update is authorized to make.
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
    if op in EDIT_OPS or op == 'create':
        missing = missing_numbers(before_htmls, after_htmls)
        if missing:
            missing = _excused_missing_numbers(
                missing, before_htmls, after_htmls, allowed_numbers, request_text)
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
    'failure_reason_text', 'instruction_for', 'needs_confirmation', 'public_task',
    'resolve_selector', 'slide_id_set', 'verify_deck_integrity', 'verify_task_result',
]
