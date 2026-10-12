"""Pure planner helpers for the designer agent: outline, density, expansion.

Everything here is deterministic and model-free so it is cheap to test. The
planner LLM receives :func:`outline_text` (positions + ids + titles, no HTML)
and answers with id-based selectors; :func:`expand_plan` resolves those
selectors into concrete per-slide tasks in deck order. Positions in a task are
the deck order at plan time — provenance for the checklist — while ``id`` is
the only field the runner trusts.
"""

import re
from collections import Counter
from html.parser import HTMLParser

import designer_agent_ids
import designer_numbers

# Per-slide op priority: the stronger operation absorbs weaker ones targeting
# the same slide (a redesign inside a restructure is part of the restructure).
_OP_PRIORITY = {
    'delete': 100, 'restructure': 90, 'split': 80, 'redesign': 70, 'edit': 60,
}
_WORKER_OPS = {'edit', 'redesign', 'split', 'restructure', 'create', 'generate_image',
               'financial_chart'}
_CODE_OPS = {'delete', 'move', 'table_edit', 'color_edit', 'watermark',
             'insert_map', 'update_image', 'insert_attached_image',
             'image_descriptions', 'team_logo', 'company_logo_panel', 'renumber',
             'duplicate', 'find_replace', 'font_edit', 'ui'}

_TAG_RE = re.compile(r'<[^>]+>', re.DOTALL)
_WS_RE = re.compile(r'\s+')


class _TextGrab(HTMLParser):
    """Visible text only: script/style/template/svg contents and managed
    chrome (footers, page counters) are not slide content — the renumber
    pipeline owns those digits, so they cannot count as preserved facts."""

    _SKIP = {'script', 'style', 'template', 'svg', 'canvas'}
    _MANAGED_ATTRS = ('data-slide-footer', 'data-slide-counter')
    _MANAGED_CLASSES = {'slide-footer', 'slide-counter'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0
        self._managed = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
            return
        attrs_d = dict(attrs)
        classes = set((attrs_d.get('class') or '').split())
        if (any(key in attrs_d for key in self._MANAGED_ATTRS)
                or classes & self._MANAGED_CLASSES):
            self._managed.append(tag)

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
            return
        if self._managed and self._managed[-1] == tag:
            self._managed.pop()

    def handle_data(self, data):
        if not self._skip and not self._managed:
            self.parts.append(data)


def slide_text(html):
    grab = _TextGrab()
    try:
        grab.feed(str(html or ''))
    except Exception:
        return _TAG_RE.sub(' ', str(html or ''))
    return _WS_RE.sub(' ', ' '.join(grab.parts)).strip()


def _slide_metrics(html):
    html = str(html or '')
    return {
        'chars': len(slide_text(html)),
        'rows': len(re.findall(r'<tr\b', html, re.I)),
        'cards': len(re.findall(r'class="[^"]*\b(?:card|kpi|metric)\b', html, re.I)),
        'tables': len(re.findall(r'<table\b', html, re.I)),
        'images': len(re.findall(r'<img\b', html, re.I)),
    }


def build_outline(slides):
    """One compact row per slide — what the planner sees instead of the HTML."""
    outline = []
    for index, slide in enumerate(slides if isinstance(slides, list) else []):
        slide = slide if isinstance(slide, dict) else {}
        metrics = _slide_metrics(slide.get('html'))
        outline.append({
            'n': index + 1,
            'id': slide.get('id') or '',
            'title': str(slide.get('title') or ''),
            'section': str(slide.get('section_key') or slide.get('sectionKey') or ''),
            'type': str(slide.get('type') or 'content'),
            'chars': metrics['chars'],
            'rows': metrics['rows'],
            'tables': metrics['tables'],
            'images': metrics['images'],
        })
    return outline


def outline_text(slides):
    """Tab-separated outline for the planner prompt (~one line per slide)."""
    lines = ['n\tid\ttype\tsection\tchars\trows\timgs\ttitle']
    for row in build_outline(slides):
        lines.append('\t'.join([
            str(row['n']), row['id'], row['type'], row['section'],
            str(row['chars']), str(row['rows']), str(row['images']),
            row['title'][:80],
        ]))
    return '\n'.join(lines)


def density(slides, ids=None):
    """Heuristic density per slide id; used by split/restructure decisions."""
    want = set(ids) if ids else None
    out = {}
    for index, slide in enumerate(slides if isinstance(slides, list) else []):
        slide = slide if isinstance(slide, dict) else {}
        sid = slide.get('id')
        if want is not None and sid not in want:
            continue
        metrics = _slide_metrics(slide.get('html'))
        metrics['score'] = (metrics['chars'] / 900.0 + metrics['rows'] * 0.4
                            + metrics['cards'] * 0.5 + metrics['images'] * 0.2)
        metrics['n'] = index + 1
        if sid:
            out[sid] = metrics
    return out


def _resolve_select(select, slides, current_index=None):
    """Expand a selector to ordered slide ids. Unknown ids land in ``missing``.

    Selector forms: {'all': true} | {'ids': [...]} | {'range': [from_id, to_id]}
    | {'section': key|[keys]} | {'positions': [1-based n,...]} | {'current': true}
    """
    select = select if isinstance(select, dict) else {}
    all_ids = [s.get('id') for s in slides if isinstance(s, dict) and s.get('id')]
    index_by_id = designer_agent_ids.index_by_id(slides)
    missing = []

    def except_ids(raw):
        """«كل الشرائح ما عدا الغلاف» — ids, positions, or a nested selector."""
        if not raw:
            return [], []
        if isinstance(raw, dict):
            return _resolve_select(raw, slides, current_index=current_index)
        raw = raw if isinstance(raw, list) else [raw]
        ids, miss = [], []
        for value in raw:
            sid = str(value or '')
            if sid in index_by_id:
                ids.append(sid)
                continue
            try:
                n = int(value)
            except (TypeError, ValueError):
                miss.append(sid)
                continue
            if 1 <= n <= len(all_ids):
                ids.append(all_ids[n - 1])
            else:
                miss.append(sid)
        return list(dict.fromkeys(ids)), miss

    if select.get('all') is True or select.get('target') == 'all':
        excluded, exc_missing = except_ids(select.get('except'))
        return [sid for sid in all_ids if sid not in set(excluded)], exc_missing
    if select.get('current') is True:
        if isinstance(current_index, int) and 0 <= current_index < len(all_ids):
            return [all_ids[current_index]], missing
        return [], all_ids[:0] or missing
    if 'positions' in select:
        raw = select.get('positions')
        raw = raw if isinstance(raw, list) else [raw]
        ids = []
        for value in raw:
            try:
                n = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= len(all_ids):
                ids.append(all_ids[n - 1])
            else:
                missing.append(str(value))
        return list(dict.fromkeys(ids)), missing
    if 'ids' in select:
        raw = select.get('ids')
        raw = raw if isinstance(raw, list) else [raw]
        ids = []
        for sid in raw:
            sid = str(sid or '')
            if sid in index_by_id:
                ids.append(sid)
            else:
                missing.append(sid)
        return list(dict.fromkeys(ids)), missing
    if 'range' in select:
        raw = select.get('range')
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            return [], [str(raw)]
        first = index_by_id.get(str(raw[0] or ''))
        last = index_by_id.get(str(raw[1] or ''))
        if first is None:
            missing.append(str(raw[0] or ''))
        if last is None:
            missing.append(str(raw[1] or ''))
        if first is None or last is None:
            return [], missing
        if first > last:
            first, last = last, first
        return list(all_ids[first:last + 1]), missing
    if 'section' in select:
        raw = select.get('section')
        keys = {str(k) for k in (raw if isinstance(raw, list) else [raw])}
        ids = [s.get('id') for s in slides
               if isinstance(s, dict)
               and str(s.get('section_key') or s.get('sectionKey') or '') in keys
               and s.get('id')]
        if not ids:
            missing.extend(sorted(keys))
        return ids, missing
    return [], []


def _op_priority(op):
    return _OP_PRIORITY.get(op, 50)  # unknown ops sort like a plain edit


def expand_plan(plan, slides, current_index=None):
    """Resolve a planner ``kind: 'plan'`` object into ordered runner tasks.

    Returns ``(tasks, errors)``. Every task carries the slide ids it touches;
    per-slide ops merge so a slide appears in at most one content op (the
    strongest one wins and absorbs the weaker instructions). Deterministic
    code ops keep their params verbatim.
    """
    ops = plan.get('ops') if isinstance(plan, dict) else None
    if not isinstance(ops, list):
        return [], [{'error': 'invalid_plan'}]
    style_brief = str(plan.get('style_brief') or '').strip()

    id_order = {sid: i for i, sid in enumerate(
        s.get('id') for s in slides if isinstance(s, dict) and s.get('id'))}
    titles_by_id = {s.get('id'): str(s.get('title') or '')
                    for s in slides if isinstance(s, dict)}

    per_slide = {}   # id -> strongest content op so far
    standalone = []  # ops not bound to a slide set (create/move) or code ops
    errors = []

    for seq, raw in enumerate(ops if isinstance(ops, list) else []):
        if not isinstance(raw, dict):
            errors.append({'error': 'invalid_op', 'op_index': seq})
            continue
        op = str(raw.get('op') or raw.get('tool') or '').strip()
        if not op:
            errors.append({'error': 'missing_op', 'op_index': seq})
            continue
        instruction = str(raw.get('instruction') or '').strip()
        select = raw.get('select') if isinstance(raw.get('select'), dict) else {}
        ids, missing = _resolve_select(select, slides, current_index=current_index)
        if missing:
            errors.append({'error': 'unknown_ids', 'op_index': seq,
                           'op': op, 'ids': missing})
        if op == 'create':
            after = raw.get('after')
            if isinstance(after, str) and after not in ('start', 'end') and after not in id_order:
                errors.append({'error': 'unknown_ids', 'op_index': seq,
                               'op': op, 'ids': [after]})
            standalone.append({'seq': seq, 'op': op, 'raw': raw, 'ids': [], 'instruction': instruction})
            continue
        if op == 'move':
            after = raw.get('after')
            if isinstance(after, str) and after not in ('start', 'end') and after not in id_order:
                errors.append({'error': 'unknown_ids', 'op_index': seq, 'op': op, 'ids': [after]})
            for sid in ids:
                standalone.append({'seq': seq, 'op': op, 'raw': raw, 'ids': [sid],
                                   'instruction': instruction})
            continue
        if op in _CODE_OPS and op not in _OP_PRIORITY:
            # Deterministic code ops stay grouped: one task, many slides.
            standalone.append({'seq': seq, 'op': op, 'raw': raw, 'ids': ids,
                               'instruction': instruction})
            continue
        if op not in _WORKER_OPS and op not in _OP_PRIORITY:
            # Admission, not approximation: an op outside the catalogue is
            # reported instead of being merged into a nearby task's intent.
            errors.append({'error': 'unsupported_op', 'op_index': seq, 'op': op})
            continue
        # Content ops (edit/redesign/split/restructure/delete): one winner per slide.
        for sid in ids:
            merged_instruction = instruction
            existing = per_slide.get(sid)
            if existing is None or _op_priority(op) > _op_priority(existing['op']):
                if existing is not None and existing['instruction']:
                    merged_instruction = (instruction + ' — ' + existing['instruction']).strip(' —')
                per_slide[sid] = {'seq': seq, 'op': op, 'raw': raw, 'ids': [sid],
                                  'instruction': merged_instruction}
            elif existing is not None and instruction:
                existing['instruction'] = (existing['instruction'] + ' — ' + instruction).strip(' —')

    # Regroup: restructure is a group op (one task over its whole id set);
    # everything else is per slide.
    groups = {}
    singles = []
    for sid, item in per_slide.items():
        if item['op'] == 'restructure':
            group = groups.get(item['seq'])
            if group is None:
                group = {'seq': item['seq'], 'op': 'restructure', 'raw': item['raw'],
                         'ids': [], 'instruction': ''}
                groups[item['seq']] = group
            if sid not in group['ids']:
                group['ids'].append(sid)
            if item['instruction'] and item['instruction'] not in group['instruction']:
                group['instruction'] = (group['instruction'] + ' — ' + item['instruction']).strip(' —')
        else:
            singles.append(item)

    tasks = []
    for item in sorted(standalone + singles + list(groups.values()),
                       key=lambda x: (x['seq'])):
        ids = item.get('ids') or []
        task = {
            'op': item['op'],
            'engine': 'worker' if item['op'] in _WORKER_OPS else 'code',
            'status': 'pending',
            'instruction': item.get('instruction') or '',
        }
        if style_brief and item['op'] in _WORKER_OPS:
            task['style_brief'] = style_brief
        if ids:
            task['slides'] = list(ids)
            task['positions_at_request'] = [id_order[sid] + 1 for sid in ids if sid in id_order]
            task['titles'] = [titles_by_id.get(sid, '') for sid in ids]
        raw = item.get('raw') if isinstance(item.get('raw'), dict) else {}
        params = raw.get('params') if isinstance(raw.get('params'), dict) else {}
        task['params'] = params
        for key in ('parts', 'target_count', 'exact_text', 'title', 'type', 'after'):
            if raw.get(key) is not None:
                task[key] = raw[key]
        tasks.append(task)

    for index, task in enumerate(tasks):
        task['n'] = index + 1
    return tasks, errors


# ── Verification helpers ────────────────────────────────────────────────────

def visible_text_nodes(html):
    """Visible text nodes in document order (the slide_text visibility rules).

    Numbers are read one node at a time: joining nodes — even with a space —
    lets two neighbouring cells read as one pseudo-number.
    """
    grab = _TextGrab()
    try:
        grab.feed(str(html or ''))
        grab.close()
    except Exception:
        return [part for part in _TAG_RE.split(str(html or '')) if part.strip()]
    return [part for part in grab.parts if part.strip()]


def extract_visible_numbers(html):
    """Multiset of numeric atoms in visible text (see designer_numbers).

    Eastern Arabic digits become western and grouping separators fold, so
    «1,234.56»، «1234.56» and «١٬٢٣٤٫٥٦» compare equal; «9/2027» is the atoms
    9 and 2027, and a cell never merges into the cell beside it.
    """
    return designer_numbers.count_atoms(visible_text_nodes(html))


def missing_numbers(source_htmls, result_htmls):
    """Numbers that appeared in the sources but vanished from the results."""
    before = Counter()
    for html in source_htmls or []:
        before |= extract_visible_numbers(html)
    after = Counter()
    for html in result_htmls or []:
        after |= extract_visible_numbers(html)
    return sorted((before - after).keys())
