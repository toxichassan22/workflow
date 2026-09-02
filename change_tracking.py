"""Turn two versions of a presentation or a project draft into readable Arabic change lines.

The history used to record one generic sentence — «تعديل المحتوى» — so a reader could not tell what
had changed, who had changed it, or whether a slide had lost content. Nothing compared two versions
anywhere in the codebase, and AI edits were not recorded at all.

Everything here is pure: it takes the old and the new value and returns lines. That keeps it
testable without a database, a request context, or a model.
"""

import difflib
import json
import re

import db

# A slide carries markup, inline styles and placeholders. Only the parts a reader would call content
# are compared; a pure styling change is reported as such instead of as a text change.
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')
_STYLE_RE = re.compile(r'\sstyle\s*=\s*"[^"]*"', re.IGNORECASE)
_IMG_SRC_RE = re.compile(r'<img[^>]+src\s*=\s*"([^"]+)"', re.IGNORECASE)
_BG_URL_RE = re.compile(r'url\(\s*[\'"]?([^\'")]+)', re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r'##[A-Z0-9_]+##')

MAX_LINES = 60
MAX_TEXT_IN_LINE = 120


def _text_of(html):
    """The reading text of a slide, with markup and inline CSS removed."""
    text = _TAG_RE.sub(' ', str(html or ''))
    text = text.replace('&nbsp;', ' ')
    return _WS_RE.sub(' ', text).strip()


def _images_of(html):
    source = str(html or '')
    found = _IMG_SRC_RE.findall(source) + _BG_URL_RE.findall(source)
    return [item.strip() for item in found if item.strip()]


def _shorten(text, limit=MAX_TEXT_IN_LINE):
    text = _WS_RE.sub(' ', str(text or '')).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def _sentences(text):
    parts = re.split(r'(?<=[.!؟?])\s+|\n+|\s{2,}|\s*\|\s*', str(text or ''))
    return [part.strip() for part in parts if part.strip()]


def _text_difference_lines(old_text, new_text):
    """Which phrases left and which arrived, rather than a character-level diff."""
    old_parts = _sentences(old_text)
    new_parts = _sentences(new_text)
    if not old_parts and not new_parts:
        return []
    matcher = difflib.SequenceMatcher(None, old_parts, new_parts)
    removed, added = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'delete'):
            removed.extend(old_parts[i1:i2])
        if tag in ('replace', 'insert'):
            added.extend(new_parts[j1:j2])
    lines = []
    if removed:
        lines.append('حُذف نص: ' + _shorten(' | '.join(removed)))
    if added:
        lines.append('أُضيف نص: ' + _shorten(' | '.join(added)))
    return lines


def _slide_label(index, slide):
    title = ''
    if isinstance(slide, dict):
        title = str(slide.get('title') or '').strip()
    return f'الشريحة {index + 1}' + (f' ({_shorten(title, 40)})' if title else '')


def _slide_html(slide):
    return str(slide.get('html') or '') if isinstance(slide, dict) else str(slide or '')


def describe_slide_changes(old_slides, new_slides):
    """Readable lines for what changed between two decks."""
    old_list = old_slides if isinstance(old_slides, list) else []
    new_list = new_slides if isinstance(new_slides, list) else []
    lines = []

    def slide_identity(slide):
        item = slide if isinstance(slide, dict) else {}
        explicit = str(item.get('id') or item.get('slideId') or '').strip()
        if explicit:
            return 'id:' + explicit
        return '|'.join((
            str(item.get('title') or '').strip(),
            str(item.get('type') or '').strip(),
            str(item.get('content_source') or item.get('contentSource') or '').strip(),
        ))

    old_order = [slide_identity(slide) for slide in old_list]
    new_order = [slide_identity(slide) for slide in new_list]
    if (len(old_order) == len(new_order) and old_order != new_order
            and sorted(old_order) == sorted(new_order) and all(old_order)):
        lines.append('أُعيد ترتيب الشرائح')
        for new_index, identity in enumerate(new_order):
            old_index = old_order.index(identity)
            if old_index != new_index:
                lines.append(f'{_slide_label(new_index, new_list[new_index])}: نُقلت من الموضع {old_index + 1} إلى {new_index + 1}')

    if len(new_list) != len(old_list):
        lines.append(f'عدد الشرائح: من {len(old_list)} إلى {len(new_list)}')

    for index in range(min(len(old_list), len(new_list))):
        old_slide = old_list[index] if isinstance(old_list[index], dict) else {}
        new_slide = new_list[index] if isinstance(new_list[index], dict) else {}
        label = _slide_label(index, new_slide or old_slide)
        slide_lines = []

        old_title = str(old_slide.get('title') or '').strip()
        new_title = str(new_slide.get('title') or '').strip()
        if old_title != new_title:
            slide_lines.append(f'العنوان: من «{_shorten(old_title, 60) or "بدون"}» '
                               f'إلى «{_shorten(new_title, 60) or "بدون"}»')

        old_html = _slide_html(old_slide)
        new_html = _slide_html(new_slide)
        if old_html != new_html:
            old_text, new_text = _text_of(old_html), _text_of(new_html)
            if old_text != new_text:
                slide_lines.extend(_text_difference_lines(old_text, new_text))
            old_images, new_images = _images_of(old_html), _images_of(new_html)
            if old_images != new_images:
                if len(new_images) > len(old_images):
                    slide_lines.append(f'الصور: من {len(old_images)} إلى {len(new_images)}')
                elif len(new_images) < len(old_images):
                    slide_lines.append(f'الصور: من {len(old_images)} إلى {len(new_images)}')
                else:
                    slide_lines.append('استُبدلت صورة أو خريطة')
            old_marks = set(_PLACEHOLDER_RE.findall(old_html))
            new_marks = set(_PLACEHOLDER_RE.findall(new_html))
            if new_marks - old_marks:
                slide_lines.append('أُضيف عنصر: ' + '، '.join(sorted(new_marks - old_marks)))
            if old_marks - new_marks:
                slide_lines.append('أُزيل عنصر: ' + '، '.join(sorted(old_marks - new_marks)))
            if not slide_lines:
                # Same text, same images: only the styling moved.
                styled_old = _STYLE_RE.sub('', old_html)
                styled_new = _STYLE_RE.sub('', new_html)
                slide_lines.append('تغيّر التنسيق والألوان بدون تغيير النص'
                                   if styled_old == styled_new else 'تغيّر تخطيط الشريحة')

        old_style = str(old_slide.get('designStyle') or old_slide.get('design_style') or '')
        new_style = str(new_slide.get('designStyle') or new_slide.get('design_style') or '')
        if old_style != new_style and (old_style or new_style):
            slide_lines.append(f'نمط التصميم: من «{old_style or "غير محدد"}» إلى «{new_style or "غير محدد"}»')

        for line in slide_lines:
            lines.append(f'{label}: {line}')

    for index in range(len(old_list), len(new_list)):
        lines.append(f'أُضيفت {_slide_label(index, new_list[index])}')
    for index in range(len(new_list), len(old_list)):
        lines.append(f'حُذفت {_slide_label(index, old_list[index])}')

    if len(lines) > MAX_LINES:
        remaining = len(lines) - MAX_LINES
        lines = lines[:MAX_LINES] + [f'و{remaining} تغييرًا آخر']
    return lines


# Draft keys that carry machinery rather than a fact the reader entered. Their change is reported as
# one line naming the area, never as a value.
DRAFT_BLOB_LABELS = {
    'financial_study_model': 'الدراسة المالية',
    'financial_calc_data': 'حسابات الدراسة المالية',
    'market_study_data': 'دراسة السوق',
    'executive_content': 'المحتوى التنفيذي',
    'team_selection': 'فريق العمل',
    'visual_concept': 'التصور البصري',
    'land_documents_analysis': 'تحليل مستندات الأرض',
    'timeline_table_data': 'الجدول الزمني',
    'project_components_data': 'مكونات المشروع',
    'nearby_landmarks_data': 'المعالم القريبة',
    'coordinate_tables': 'جداول الإحداثيات',
    'survey_coordinates': 'إحداثيات المساحة',
    'directions_table': 'جدول الحدود والأطوال',
    'tenantCreativeImages': 'صور العرض',
    'tenantSlidesData': 'شرائح العرض',
    'tenantSlidePlan': 'هيكل العرض',
    'pageDrafts': 'حالة الصفحات',
    'map_styles': 'أنماط الخرائط',
    'landmarks_matrix': 'مسافات المعالم',
}

DRAFT_IGNORED_KEYS = {
    'draftId', 'draft_id', 'sectionStatuses', 'regen_seed', 'refresh_maps',
    'updated_at', 'created_at', 'revision',
}


def _draft_field_labels():
    labels = {}
    for field in getattr(db, 'PREBUILT_FIELDS', []) or []:
        key = field.get('key')
        if key:
            labels[key] = field.get('label') or key
    return labels


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


def describe_draft_changes(old_data, new_data, field_labels=None):
    """Readable lines for what changed between two saves of a project file."""
    old_data = old_data if isinstance(old_data, dict) else {}
    new_data = new_data if isinstance(new_data, dict) else {}
    labels = dict(field_labels or _draft_field_labels())
    labels.update(DRAFT_BLOB_LABELS)
    lines = []

    for key in sorted(set(old_data) | set(new_data)):
        if key in DRAFT_IGNORED_KEYS or key.startswith('_') or key.endswith(('_file_meta', '_file_ids')):
            continue
        old_value, new_value = old_data.get(key), new_data.get(key)
        if old_value == new_value:
            continue
        label = labels.get(key, key)
        if key in DRAFT_BLOB_LABELS or _is_blob(old_value) or _is_blob(new_value):
            had = bool(old_value) and old_value not in ({}, [], '')
            has = bool(new_value) and new_value not in ({}, [], '')
            if has and not had:
                lines.append(f'{label}: أُضيفت البيانات')
            elif had and not has:
                lines.append(f'{label}: أُزيلت البيانات')
            else:
                lines.append(f'{label}: تم تحديث البيانات')
            continue
        old_text, new_text = _readable_value(old_value), _readable_value(new_value)
        if not old_text and not new_text:
            continue
        if not old_text:
            lines.append(f'{label}: أُضيف «{new_text}»')
        elif not new_text:
            lines.append(f'{label}: أُفرغ (كان «{old_text}»)')
        else:
            lines.append(f'{label}: من «{old_text}» إلى «{new_text}»')

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
