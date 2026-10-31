"""A designer-edited index keeps its own layout on every save and export.

The canonical builder owns a generated index and still rebuilds it. Once the
client or the designer chat edited that page, the design is theirs: renumbering
only refreshes the page numbers of the rows that exist and repairs a collapsed
two-column split inside their own grid — it never replaces headings, styling or
extra content the edit added.
"""

_INDEX_GRID_OPEN_RE = re.compile(
    r'<(?P<tag>div)\b[^>]*\bstyle\s*=\s*["\'][^"\']*\bgrid-template-columns\b[^"\']*["\'][^>]*>',
    re.IGNORECASE)
_INDEX_PAGE_OPEN_RE = re.compile(
    r'<(?P<tag>[a-z][\w:-]*)\b[^>]*\bdata-index-page\s*=\s*["\'](?P<key>[^"\']*)["\'][^>]*>',
    re.IGNORECASE)
_INDEX_ROW_OPEN_RE = re.compile(
    r'<(?P<tag>[a-z][\w:-]*)\b[^>]*\bdata-index-section\s*=\s*["\'][^"\']*["\'][^>]*>',
    re.IGNORECASE)
_INDEX_TAG_RE = re.compile(
    r'<(?P<closing>/)?(?P<tag>[a-z][\w:-]*)(?:\s[^>]*)?>', re.IGNORECASE)
_INDEX_VOID_TAGS = frozenset(
    'area base br col embed hr img input link meta param source track wbr'.split())


def _index_page_numbers(html, entries):
    """Rewrite the page label of every row that is still on the page."""
    pages = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get('section_key') or '').strip()
        if key:
            pages[key] = entry.get('page')
    if not pages:
        return html
    for match in reversed(list(_INDEX_PAGE_OPEN_RE.finditer(html))):
        page = pages.get(str(match.group('key')).strip())
        if page in (None, ''):
            continue
        try:
            label = f'{int(page):02d}'
        except (TypeError, ValueError):
            label = str(page)
        end = _slide_element_end(html, match)
        close = re.search(r'</\s*' + re.escape(match.group('tag')) + r'\s*>\s*$',
                          html[match.end():end], re.IGNORECASE)
        inner_end = match.end() + close.start() if close else end
        inner = html[match.end():inner_end]
        if '<' in inner:
            new_inner = re.sub(r'(>\s*)\d+(\s*<)',
                               lambda m: m.group(1) + label + m.group(2), inner)
        else:
            new_inner = label
        html = html[:match.end()] + new_inner + html[inner_end:]
    return html


def _index_direct_div_children(html, start, end):
    """Balanced direct <div> children of the element spanning start..end."""
    children, stack, current = [], [], None
    for match in _INDEX_TAG_RE.finditer(html, start, end):
        tag = match.group('tag').lower()
        if match.group('closing'):
            if not stack:
                continue
            opened = stack.pop()
            if not stack and current is not None and opened == tag:
                current['inner_end'] = match.start()
                children.append(current)
                current = None
            continue
        if tag in _INDEX_VOID_TAGS or match.group(0).rstrip().endswith('/>'):
            continue
        if not stack and tag == 'div':
            current = {'inner_start': match.end(), 'inner_end': match.end()}
        stack.append(tag)
    return children


def _rebalance_collapsed_index_columns(html):
    """Split rows that all piled into the first column of an empty two-column grid.

    That layout is the damage the old row-patching pass left behind; it is not
    a design. The rows stay exactly as stored — they only move to the column
    they were meant to sit in.
    """
    for grid in list(_INDEX_GRID_OPEN_RE.finditer(html)):
        body_start = grid.end()
        body_end = _slide_element_end(html, grid)
        columns = _index_direct_div_children(html, body_start, body_end)
        if len(columns) < 2:
            continue
        first, second = columns[0], columns[1]
        rows = list(_INDEX_ROW_OPEN_RE.finditer(html, first['inner_start'], first['inner_end']))
        if not rows:
            continue
        if _INDEX_ROW_OPEN_RE.search(html, second['inner_start'], second['inner_end']):
            continue
        if re.sub(r'<[^>]+>', ' ', html[second['inner_start']:second['inner_end']]).strip():
            continue
        row_html = [html[m.start():_slide_element_end(html, m)] for m in rows]
        midpoint = (len(row_html) + 1) // 2
        body = html[body_start:body_end]
        first_start = first['inner_start'] - body_start
        first_end = first['inner_end'] - body_start
        second_start = second['inner_start'] - body_start
        second_end = second['inner_end'] - body_start
        body = (body[:first_start] + ''.join(row_html[:midpoint]) + body[first_end:second_start]
                + ''.join(row_html[midpoint:]) + body[second_end:])
        return html[:body_start] + body + html[body_end:]
    return html


def _patch_preserved_index_html(html, entries, slide_num, total_slides):
    """Renumber a designer-edited index without touching its design."""
    html = str(html or '')
    if not html:
        return html
    html = _index_page_numbers(html, entries)
    html = _rebalance_collapsed_index_columns(html)
    return _rewrite_preserved_counter(html, 'index', slide_num, total_slides)
