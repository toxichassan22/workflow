

def _strip_icons(value):
    return _ICON_RE.sub('', str(value or '')).replace('•', '').strip()


# --------------------------------------------------------------------------
# CSS helpers
# --------------------------------------------------------------------------

_CSS_NAMED = {
    'white': 'ffffff', 'black': '000000', 'red': 'ff0000',
    'transparent': None,
}

_RGB_RE = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)')
_HEX_RE = re.compile(r'#([0-9a-fA-F]{3,8})')


def _split_declarations(style):
    """Split a style attribute on ';' ignoring semicolons inside url(...) or quotes
    (data-URI backgrounds contain ';base64,')."""
    parts, current, depth, quote = [], [], 0, None
    for ch in str(style or ''):
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            current.append(ch)
        elif ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == ';' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if ''.join(current).strip():
        parts.append(''.join(current))
    return parts


def _parse_style(style):
    """Parse an inline style attribute into a lowercase dict."""
    out = {}
    for part in _split_declarations(style):
        if ':' not in part:
            continue
        name, _, value = part.partition(':')
        name, value = name.strip().lower(), value.strip()
        if name and value:
            out[name] = value
    return out


# --------------------------------------------------------------------------
# CSS cascade resolver — generated slides style body components (KPI cards,
# financial tables, chart boxes) through <style> classes, not inline styles.
# Without resolving them every grid stacks vertically and every table loses
# its centering, sizes and zebra striping.
# --------------------------------------------------------------------------

_SIMPLE_SELECTOR_RE = re.compile(r'''
    ^(?P<tag>[a-zA-Z][a-zA-Z0-9_-]*)?
    (?P<rest>.*)$''', re.VERBOSE)
_SELECTOR_TOKEN_RE = re.compile(r'''
    \#(?P<id>[A-Za-z0-9_-]+)
    | \.(?P<class>[A-Za-z0-9_-]+)
    | \[(?P<attr>[A-Za-z0-9_-]+)(?:=(?P<q>["']?)(?P<val>.*?)(?P=q))?\]
    | :(?P<pseudo>[A-Za-z-]+(?:\([^)]*\))?)''', re.VERBOSE)


def _parse_simple_selector(part):
    """Parse one compound selector into tag/id/classes/attrs/pseudos."""
    part = part.strip()
    if not part:
        return None
    match = _SIMPLE_SELECTOR_RE.match(part)
    tag = (match.group('tag') or '').lower() or None
    rest = match.group('rest') or ''
    sel_id, classes, attrs, pseudos = None, [], [], []
    for tok in _SELECTOR_TOKEN_RE.finditer(rest):
        if tok.group('id'):
            sel_id = tok.group('id')
        elif tok.group('class'):
            classes.append(tok.group('class'))
        elif tok.group('attr'):
            attrs.append((tok.group('attr').lower(), tok.group('val')))
        elif tok.group('pseudo'):
            pseudos.append(tok.group('pseudo').lower())
    # Anything unparsed (combinators inside, universal *) -> treat carefully
    leftover = _SELECTOR_TOKEN_RE.sub('', rest).strip()
    if leftover not in ('', '*'):
        return None
    if tag == '*':
        tag = None
    return {'tag': tag, 'id': sel_id, 'classes': classes,
            'attrs': attrs, 'pseudos': pseudos}


def _parse_selector(selector):
    """Split a full selector into compound parts (descendant/child chains)."""
    selector = re.sub(r'\s*>\s*', ' ', selector.strip())
    selector = re.sub(r'\s+', ' ', selector)
    if not selector or '@' in selector:
        return None
    parts = []
    for chunk in selector.split(' '):
        parsed = _parse_simple_selector(chunk)
        if parsed is None:
            return None
        parts.append(parsed)
    return parts or None


def _selector_specificity(parts):
    ids = sum(1 for p in parts if p['id'])
    cls = sum(len(p['classes']) + len(p['attrs']) + len(p['pseudos']) for p in parts)
    tags = sum(1 for p in parts if p['tag'])
    return (ids, cls, tags)


def _match_simple(node, simple):
    if simple['tag'] and node.tag != simple['tag']:
        return False
    if simple['id'] and node.attrs.get('id') != simple['id']:
        return False
    classes = node.classes()
    for cls in simple['classes']:
        if cls not in classes:
            return False
    for name, val in simple['attrs']:
        actual = node.attrs.get(name)
        if actual is None:
            return False
        if val is not None and str(actual) != val:
            return False
    pos, is_last = node.sibling_position()
    for pseudo in simple['pseudos']:
        if pseudo.startswith('nth-child'):
            arg = pseudo[len('nth-child'):].strip('() ')
            if arg == 'even':
                if pos % 2:
                    return False
            elif arg == 'odd':
                if not pos % 2:
                    return False
            else:
                return False  # unsupported functional form: skip, do not over-match
        elif pseudo == 'first-child':
            if pos != 1:
                return False
        elif pseudo == 'last-child':
            if not is_last:
                return False
        elif pseudo.startswith(('before', 'after', 'first-line', 'first-letter',
                                'selection', 'marker', 'placeholder')):
            return False  # generated content is not in the DOM
        # other pseudos (:hover, :root ...) are ignored = treated as match
    return True


def _match_selector(node, parts):
    if not _match_simple(node, parts[-1]):
        return False
    ancestor = node.parent
    for part in reversed(parts[:-1]):
        found = False
        while ancestor is not None and ancestor.tag != 'root':
            if _match_simple(ancestor, part):
                found = True
                ancestor = ancestor.parent
                break
            ancestor = ancestor.parent
        if not found:
            return False
    return True


def _collect_css_rules(css_text):
    """Parse raw CSS into (parts, specificity, important_decls, normal_decls, order)."""
    rules = []
    order = 0
    css_text = re.sub(r'/\*.*?\*/', '', css_text or '', flags=re.S)
    for chunk in css_text.split('}'):
        if '{' not in chunk:
            continue
        selectors_raw, _, decls_raw = chunk.partition('{')
        if '@' in selectors_raw:
            continue  # @media / @font-face / @import
        decls = {}
        for part in _split_declarations(decls_raw):
            if ':' not in part:
                continue
            name, _, value = part.partition(':')
            name, value = name.strip().lower(), value.strip()
            if not name or not value or name.startswith('*'):
                continue
            important = bool(re.search(r'!important\s*$', value, re.I))
            value = re.sub(r'\s*!important\s*$', '', value, flags=re.I).strip()
            if value:
                decls[name] = (value, important)
        if not decls:
            continue
        for selector in selectors_raw.split(','):
            parts = _parse_selector(selector)
            if parts:
                rules.append((parts, _selector_specificity(parts), decls, order))
                order += 1
    return rules


def _apply_css_cascade(root):
    """Merge matching <style> rules into every node's style (inline wins)."""
    css_texts = []
    for style_node in root.find_all({'style'}):
        css_texts.append(style_node.get_text())
    if not css_texts:
        return
    rules = []
    for css in css_texts:
        rules.extend(_collect_css_rules(css))
    if not rules:
        return

    def _apply_to(node):
        merged, important = {}, {}
        for parts, spec, decls, order in rules:
            if _match_selector(node, parts):
                for name, (value, imp) in decls.items():
                    target = important if imp else merged
                    key = (spec, order)
                    if name not in target or key >= target[name][0]:
                        target[name] = (key, value)
        computed = {n: v for n, (_k, v) in merged.items()}
        computed.update({n: v for n, (_k, v) in important.items()})
        computed.update(node.style)  # inline style attribute wins
        node.style = computed

    # full-tree application via parent pointers (nth-child resolves its own
    # sibling position, so no ancestor bookkeeping is needed here)
    def apply_all(node):
        if not isinstance(node, Node):
            return
        _apply_to(node)
        for child in node.children:
            apply_all(child)

    apply_all(root)


def _parse_gradient_color(value):
    """First color stop of a linear-gradient (site uses gradients for rules)."""
    if not value or 'gradient' not in str(value).lower():
        return None
    inner = str(value)
    inner = inner[inner.lower().find('gradient'):]
    for regex in (_RGB_RE, _HEX_RE):
        match = regex.search(inner)
        if match:
            try:
                if regex is _RGB_RE:
                    return RGBColor(int(match.group(1)), int(match.group(2)),
                                    int(match.group(3)))
                return _hex_to_rgb('#' + match.group(1)[:6])
            except ValueError:
                continue
    return None


def _parse_rgba_alpha(value):
    """Transparency percentage (0-100) of an rgba() color, else None."""
    match = re.search(r'rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([\d.]+)\s*\)',
                      str(value or '').lower())
    if not match:
        return None
    try:
        alpha = max(0.0, min(1.0, float(match.group(1))))
    except ValueError:
        return None
    if alpha >= 1.0:
        return None
    return (1.0 - alpha) * 100.0


def _parse_color(value):
    """Return an RGBColor or None for a CSS color value."""
    if not value:
        return None
    value = str(value).strip().lower()
    if value in ('transparent', 'none', 'inherit', 'initial'):
        return None
    if value in _CSS_NAMED:
        value = _CSS_NAMED[value]
        if value is None:
            return None
    match = _RGB_RE.search(value)
    if match:
        try:
            return RGBColor(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = _HEX_RE.search(value)
    if match:
        try:
            return _hex_to_rgb('#' + match.group(1)[:6])
        except ValueError:
            return None
    try:
        return _hex_to_rgb(normalize_hex_color(value, '#000000'))
    except Exception:
        return None


def _hex_to_rgb(hex_color):
    """Convert hex color string to RGBColor."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)
    return RGBColor(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def _parse_px(value, default=0.0):
    if value is None:
        return default
    match = re.search(r'(-?[\d.]+)\s*(px|pt|in|cm|mm|%)?', str(value).strip().lower())
    if not match:
        return default
    number, unit = float(match.group(1)), (match.group(2) or 'px')
    if unit == 'px':
        return number
    if unit == 'pt':
        return number * 96.0 / 72.0
    if unit == 'in':
        return number * 96.0
    if unit == 'cm':
        return number * 96.0 / 2.54
    if unit == 'mm':
        return number * 96.0 / 25.4
    return default


def _parse_font_size(value, default_px=14.0):
    px = _parse_px(value, None)
    if px:
        return px
    named = {'small': 11.0, 'medium': 14.0, 'large': 18.0, 'x-large': 24.0, 'xx-large': 32.0}
    return named.get(str(value or '').strip().lower(), default_px)


def _px_to_emu(px):
    return Emu(int(float(px) * EMU_PER_PX))


def _px_to_pt(px):
    return Pt(max(6.0, float(px) * 0.75))


_URL_RE = re.compile(r'url\(\s*["\']?(.*?)["\']?\s*\)', re.IGNORECASE)


def _extract_bg_url(style_value):
    if not style_value:
        return ''
    match = _URL_RE.search(str(style_value))
    if not match:
        return ''
    url = match.group(1).strip()
    if url.lower().startswith('data:'):
        return url
    if '##' in url:
        return ''
    return url


# --------------------------------------------------------------------------
# Minimal HTML tree (stdlib only — no bs4 on the server)
# --------------------------------------------------------------------------

_SKIP_TAGS = {'style', 'script', 'noscript', 'head', 'meta', 'link', 'title'}


class Node:
    __slots__ = ('tag', 'attrs', 'style', 'children', 'text', 'parent')

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.style = _parse_style(self.attrs.get('style', ''))
        self.children = []
        self.text = ''
        self.parent = None

    def classes(self):
        return set(str(self.attrs.get('class', '')).split())

    def sibling_position(self):
        """1-based element index among siblings + whether it is the last one."""
        parent = self.parent
        if parent is None:
            return 1, True
        idx, total = 0, 0
        for child in parent.children:
            if isinstance(child, Node):
                total += 1
                if child is self:
                    idx = total
        return idx or 1, (idx == total)

    def get_text(self):
        parts = [self.text]
        for child in self.children:
            if isinstance(child, Node):
                parts.append(child.get_text())
            else:
                parts.append(str(child))
        return ''.join(parts)

    def find_all(self, tags):
        found = []
        if self.tag in tags:
            found.append(self)
        for child in self.children:
            if isinstance(child, Node):
                found.extend(child.find_all(tags))
        return found

    def __repr__(self):  # pragma: no cover - debugging helper
        return f'Node({self.tag}, {len(self.children)} children)'


class _TreeBuilder(HTMLParser):
    VOID = {'img', 'br', 'hr', 'input', 'meta', 'link', 'source'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('root')
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        node = Node(tag, attrs)
        node.parent = self._stack[-1]
        self._stack[-1].children.append(node)
        if tag not in self.VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        tag = tag.lower()
        if tag not in self.VOID and self._stack and self._stack[-1].tag == tag:
            self._stack.pop()

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if data:
            self._stack[-1].children.append(data)


def _parse_html(html):
    builder = _TreeBuilder()
    try:
        builder.feed(str(html or ''))
    except Exception:
        pass
    try:
        _apply_css_cascade(builder.root)
    except Exception:
        pass
    return builder.root


def _find_slide_root(root):
    for node in root.find_all({'div'}):
        if 'slide' in node.classes():
            return node
    return root


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------

def _image_bytes(src, tenant_id=None):
    """Resolve an <img> src / background url, fitted to display size.

    The stored originals are never touched; fitting only shrinks what the
    deck embeds (a 2.5MB source photo becomes ~200KB) and python-pptx still
    deduplicates identical results into one media part.
    """
    data = _resolve_image_bytes(src, tenant_id)
    if not data:
        return None
    try:
        return fit_image_bytes(data)
    except Exception:
        return data


def _resolve_image_bytes(src, tenant_id=None):
    """Resolve an <img> src / background url to raw image bytes.

    ISS-019: the export never follows a remote URL and never reads a local
    path outside the caller's allowed roots — a stored slide can carry
    ``file://``, ``http(s)://`` or ``..`` traversal references that would
    otherwise make the server read or fetch them.
    """
    if not src:
        return None
    src = str(src).strip().strip('"\'')
    if not src or '##' in src:
        return None
    try:
        if src.lower().startswith('data:image'):
            header, _, data = src.partition(',')
            if ';base64' in header and data:
                return base64.b64decode(data)
            return None
        parsed = urlparse(src)
        if parsed.scheme in ('http', 'https') or src.startswith('//'):
            # Remote image fetches are an SSRF surface; the export only embeds
            # what the tenant already stored locally.
            return None
        if parsed.scheme and parsed.scheme != 'file':
            return None

        candidates = []
        if parsed.scheme == 'file':
            candidates.append(_export_url_to_local_path(src))
        else:
            # Site paths: uploads/... assets/... /uploads/... /tenant-assets/...
            rel = src.split('?')[0].split('#')[0].lstrip('/')
            is_tenant_asset = rel.startswith('tenant-assets/')
            if is_tenant_asset:
                rel = 'uploads/' + rel[len('tenant-assets/'):]
            candidates.append(BASE_DIR / rel)
            if is_tenant_asset and not Path(rel).suffix:
                candidates += [
                    Path(str(BASE_DIR / rel) + ext)
                    for ext in ('.png', '.jpg', '.jpeg', '.webp')
                ]
            # Tenant logo shorthand or bare filename under the tenant dir
            if tenant_id and '/' not in rel:
                candidates += [
                    BASE_DIR / 'uploads' / str(tenant_id) / (rel + ext if ext else rel)
                    for ext in ('', '.png', '.jpg', '.jpeg', '.webp')
                ]
        for candidate in candidates:
            try:
                if candidate.is_file() \
                        and _export_allowed_local_path(candidate, tenant_id, base_dir=BASE_DIR):
                    return candidate.read_bytes()
            except OSError:
                continue
        return None
    except Exception:
        return None


def _image_size(data):
    try:
        from PIL import Image
        with Image.open(BytesIO(data)) as im:
            return im.size
    except Exception:
        return (1280, 720)


# --------------------------------------------------------------------------
# pptx primitives
# --------------------------------------------------------------------------

def _resolve_font_name(branding):
    raw = str((branding or {}).get('font_family') or '').strip()
    if raw:
        first = raw.split(',')[0].strip().strip('"\'')
        low = first.lower()
        if first and 'tenant-managed' not in low and 'platform-fallback' not in low:
            return first
    return 'IBM Plex Sans Arabic'


def _set_slide_background(slide, color):
    if color is None:
        return
    try:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = color
    except Exception:
        pass


def _set_shape_fill(shape, color, alpha_pct=None):
    """Solid fill with optional transparency percentage (0-100)."""
    try:
        shape.fill.solid()
        shape.fill.fore_color.rgb = color
        if alpha_pct:
            # python-pptx has no public transparency API: add a:alpha under srgbClr
            solid = shape.fill._xPr.find(
                '{http://schemas.openxmlformats.org/drawingml/2006/main}solidFill')
            if solid is not None:
                clr = solid.find(
                    '{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr')
                if clr is not None:
                    alpha = clr.makeelement(
                        '{http://schemas.openxmlformats.org/drawingml/2006/main}alpha',
                        {'val': str(int((100 - alpha_pct) * 1000))})
                    clr.append(alpha)
    except Exception:
        pass


def _no_line(shape):
    try:
        shape.line.fill.background()
    except Exception:
        pass


def _cell_border(cell, color_hex='BFC9D4', width_pt=0.75):
    try:
        from pptx.oxml.ns import qn
        tcPr = cell._tc.get_or_add_tcPr()
        for edge in ('lnL', 'lnR', 'lnT', 'lnB'):
            ln = tcPr.find(qn(f'a:{edge}'))
            if ln is None:
                ln = tcPr.makeelement(qn(f'a:{edge}'), {})
                tcPr.append(ln)
            ln.set('w', str(int(width_pt * 12700)))
            fill = ln.find(qn('a:solidFill'))
            if fill is None:
                fill = ln.makeelement(qn('a:solidFill'), {})
                ln.append(fill)
            clr = fill.find(qn('a:srgbClr'))
            if clr is None:
                clr = fill.makeelement(qn('a:srgbClr'), {'val': color_hex})
                fill.append(clr)
            else:
                clr.set('val', color_hex)
    except Exception:
        pass


def _inline_runs(node):
    """Flatten inline content of a node into (text, fmt) runs.

    fmt keys: bold, italic, size_px, color (RGBColor|None), link.
    """
    runs = []

    def walk(n, fmt):
        if isinstance(n, str):
            text = _strip_icons(n).replace('\xa0', ' ')
            text = re.sub(r'[ \t]+', ' ', text)
            if text.strip():
                runs.append((text, dict(fmt)))
            return
        if not isinstance(n, Node):
            return
        if n.tag in _SKIP_TAGS:
            return
        if n.tag == 'br':
            runs.append(('\n', dict(fmt)))
            return
        child_fmt = dict(fmt)
        if n.tag in ('b', 'strong'):
            child_fmt['bold'] = True
        if n.tag in ('i', 'em'):
            child_fmt['italic'] = True
        if n.tag == 'a':
            child_fmt['link'] = n.attrs.get('href', '')
        color = _parse_color(n.style.get('color'))
        if color is not None:
            child_fmt['color'] = color
            child_fmt['alpha'] = _parse_rgba_alpha(n.style.get('color'))
        size = _parse_font_size(n.style.get('font-size'), None)
        if size:
            child_fmt['size_px'] = size
        weight = str(n.style.get('font-weight', '')).lower()
        if weight in ('bold', '700', '800', '900') or (weight.isdigit() and int(weight) >= 700):
            child_fmt['bold'] = True
        if n.text and n.text.strip():
            text = _strip_icons(n.text).replace('\xa0', ' ')
            text = re.sub(r'[ \t]+', ' ', text)
            if text.strip():
                runs.append((text, dict(child_fmt)))
        for child in n.children:
            walk(child, child_fmt)

    base = {'bold': False, 'italic': False, 'size_px': None, 'color': None,
            'alpha': None, 'link': None}
    if node.text and node.text.strip():
        text = _strip_icons(node.text).replace('\xa0', ' ')
        if text.strip():
            runs.append((re.sub(r'[ \t]+', ' ', text), dict(base)))
    for child in node.children:
        walk(child, base)
    return runs


def _clean_runs(runs):
    cleaned = []
    for text, fmt in runs:
        text = text.replace('\n ', '\n').strip(' \t')
        if text:
            cleaned.append((text, fmt))
    return cleaned


def _para_align(node, default=PP_ALIGN.RIGHT):
    align = str(node.style.get('text-align', '')).lower()
    return {'left': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER,
            'right': PP_ALIGN.RIGHT, 'justify': PP_ALIGN.JUSTIFY}.get(align, default)


def _set_run_alpha(run, alpha_pct):
    """Transparency on a text run (for rgba() tints and watermarks)."""
    if not alpha_pct:
        return
    try:
        from pptx.oxml.ns import qn
        rPr = run._r.get_or_add_rPr()
        solid = rPr.find(qn('a:solidFill'))
        if solid is None:
            return
        clr = solid.find(qn('a:srgbClr'))
        if clr is None:
            return
        if clr.find(qn('a:alpha')) is not None:
            return
        alpha = clr.makeelement(qn('a:alpha'),
                                {'val': str(int((100 - alpha_pct) * 1000))})
        clr.append(alpha)
    except Exception:
        pass


def _set_list_bullet(para, ordered=False, level=0):
    """Real PowerPoint bullets (no glyph characters inside the editable text)."""
    try:
        from pptx.oxml.ns import qn
        pPr = para._p.get_or_add_pPr()
        for tag in ('a:buChar', 'a:buAutoNum', 'a:buBlip', 'a:buNone'):
            el = pPr.find(qn(tag))
            if el is not None:
                pPr.remove(el)
        if ordered:
            pPr.append(pPr.makeelement(qn('a:buAutoNum'), {'type': 'arabicPeriod'}))
        else:
            pPr.append(pPr.makeelement(qn('a:buChar'), {'char': '–' if level else '•'}))
        marL = int((0.25 + level * 0.3) * 914400)
        pPr.set('marL', str(marL))
        pPr.set('indent', str(-int(0.25 * 914400)))
        return True
    except Exception:
        return False
