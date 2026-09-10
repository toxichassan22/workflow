"""
PPTX Export Engine — Tenant-aware, fully editable.

Every slide becomes native PowerPoint objects (text boxes, tables, pictures,
shapes) built from the slide HTML, so the downloaded file keeps the site's
design (colors, order, images, tables) and every text stays editable.

Pure Python: no Playwright/Chromium dependency, works on hosting too.
Slide size is 13.333 x 7.5 in (16:9), i.e. 1280x720 px at 96 dpi.
"""

import base64
import os
import re
import time
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Emu, Inches, Pt
from pptx.dml.color import RGBColor

from design_templates import (
    dark_surface_color,
    normalize_hex_color,
    readable_text_color,
    sanitize_slide_html_for_export,
)
from generate_pdf_from_preview import _resolve_asset_urls, _resolve_project_file_urls
from slide_engine import resolve_logo_in_html

BASE_DIR = Path(__file__).resolve().parent.parent

# 96 dpi mapping: 1280px -> 13.333in, 720px -> 7.5in
EMU_PER_PX = 914400 / 96
SLIDE_W_PX, SLIDE_H_PX = 1280, 720

_ICON_RE = re.compile(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]')


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
    """Resolve an <img> src / background url to raw image bytes."""
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
        if src.startswith('file://'):
            path = Path(unquote(urlparse(src).path))
            # Windows file URIs look like file:///D:/... -> urlparse gives /D:/...
            if os.name == 'nt' and re.match(r'^/[A-Za-z]:', str(path)):
                path = Path(str(path)[1:])
            if path.is_file():
                return path.read_bytes()
            return None
        parsed = urlparse(src)
        if parsed.scheme in ('http', 'https'):
            import requests
            try:
                resp = requests.get(src, timeout=20, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            except Exception:
                return None
            if resp.ok and resp.content:
                ctype = str(resp.headers.get('Content-Type', '')).lower()
                if 'image' in ctype or src.lower().split('?')[0].endswith(
                        ('.png', '.jpg', '.jpeg', '.webp', '.gif')):
                    return resp.content
                # Accept it anyway when Pillow can open it
                try:
                    from PIL import Image
                    Image.open(BytesIO(resp.content)).verify()
                    return resp.content
                except Exception:
                    return None
            return None
        # Local repo paths: uploads/... assets/... /uploads/... /tenant-assets/...
        rel = src.split('?')[0].split('#')[0].lstrip('/')
        if rel.startswith('tenant-assets/'):
            rel = 'uploads/' + rel[len('tenant-assets/'):]
        candidate = (BASE_DIR / rel)
        if candidate.is_file():
            return candidate.read_bytes()
        # Tenant logo shorthand or bare filename under the tenant dir
        if tenant_id and '/' not in rel:
            for ext in ('', '.png', '.jpg', '.jpeg', '.webp'):
                cand = BASE_DIR / 'uploads' / str(tenant_id) / (rel + ext if ext else rel)
                if cand.is_file():
                    return cand.read_bytes()
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


def _add_paragraph(text_frame, runs, align=PP_ALIGN.RIGHT, space_after_pt=4.0,
                   line_spacing=1.15, first=False, bullet=None, level=0,
                   default_size_px=14.0, default_color=None, default_bold=False,
                   font_name='Arial', ordered=False, default_alpha=None):
    if first and len(text_frame.paragraphs) == 1 and not text_frame.paragraphs[0].runs:
        para = text_frame.paragraphs[0]
    else:
        para = text_frame.add_paragraph()
    para.alignment = align
    try:
        # Explicit base direction: without it PowerPoint guesses from the
        # first characters, so "72 / 01" flips to "01 / 72" and embedded
        # numbers jump inside Arabic sentences.
        from pptx.oxml.ns import qn  # noqa: F401 (ensures oxml available)
        direction = None
        for text, _fmt in runs:
            for ch in str(text):
                if 'A' <= ch <= 'Z' or 'a' <= ch <= 'z' or '0' <= ch <= '9':
                    direction = '0'
                    break
                if ('\u0590' <= ch <= '\u08FF' or '\uFB50' <= ch <= '\uFDFF'
                        or '\uFE70' <= ch <= '\uFEFF'):
                    direction = '1'
                    break
            if direction is not None:
                break
        if direction is None:
            direction = '1'
        para._p.get_or_add_pPr().set('rtl', direction)
    except Exception:
        pass
    try:
        para.level = min(int(level), 8)
    except Exception:
        pass
    try:
        para.space_after = Pt(space_after_pt)
        para.line_spacing = line_spacing
    except Exception:
        pass
    if bullet:
        if not _set_list_bullet(para, ordered=ordered, level=level):
            prefix = ('-  ' if level == 0 else '–  ')
            run = para.add_run()
            run.text = prefix
            run.font.size = _px_to_pt(default_size_px)
            run.font.name = font_name
            if default_color is not None:
                try:
                    run.font.color.rgb = default_color
                except Exception:
                    pass
    for text, fmt in runs:
        for chunk in text.split('\n'):
            run = para.add_run()
            run.text = chunk
            size_px = fmt.get('size_px') or default_size_px
            try:
                run.font.size = _px_to_pt(size_px)
            except Exception:
                pass
            try:
                run.font.name = font_name
            except Exception:
                pass
            color = fmt.get('color') or default_color
            if color is not None:
                try:
                    run.font.color.rgb = color
                except Exception:
                    pass
                _set_run_alpha(run, fmt.get('alpha') or default_alpha)
            try:
                run.font.bold = bool(fmt.get('bold') or default_bold)
                run.font.italic = bool(fmt.get('italic'))
            except Exception:
                pass
        # newlines inside a run become separate paragraphs for editability
    return para


# --------------------------------------------------------------------------
# Block model: convert HTML flow into measurable editable blocks
# --------------------------------------------------------------------------

class Ctx:
    def __init__(self, branding, tenant_id, font_name, primary, top_px=0.0):
        self.branding = branding or {}
        self.tenant_id = tenant_id
        self.font_name = font_name
        self.primary = primary
        self.counters = {'img': 0}


def _node_bg(node):
    bg = node.style.get('background', '') or node.style.get('background-color', '')
    # background shorthand may carry url(...) — only accept pure colors here
    if 'url(' in str(bg).lower():
        return None
    color = _parse_color(bg)
    if color is None and 'gradient' in str(bg).lower():
        color = _parse_gradient_color(bg)
    return color


def _node_bg_alpha(node):
    """(fill color, transparency pct) honouring rgba() tints."""
    bg = node.style.get('background', '') or node.style.get('background-color', '')
    if 'url(' in str(bg).lower():
        return None, None
    color = _parse_color(bg)
    if color is None and 'gradient' in str(bg).lower():
        color = _parse_gradient_color(bg)
    if color is None:
        return None, None
    return color, _parse_rgba_alpha(bg)


def _is_hidden(node):
    if not isinstance(node, Node):
        return False
    if node.tag in _SKIP_TAGS:
        return True
    if node.attrs.get('hidden') is not None:
        return True
    disp = node.style.get('display', '').strip().lower()
    if disp == 'none':
        return True
    if node.style.get('visibility', '').strip().lower() == 'hidden':
        return True
    return False


def _is_header_node(node):
    if node.tag == 'header':
        return True
    if node.attrs.get('data-slide-header') is not None:
        return True
    return 'slide-header' in node.classes()


def _is_footer_node(node):
    if node.tag == 'footer':
        return True
    if node.attrs.get('data-slide-footer') is not None:
        return True
    return 'slide-footer' in node.classes()


def _grid_columns(node):
    """Return column count for grid/flex row containers, else 1."""
    display = node.style.get('display', '').lower()
    if 'grid' in display:
        tpl = node.style.get('grid-template-columns', '')
        parts = [p for p in re.split(r'\s+', tpl.strip()) if p]
        if len(parts) >= 2:
            return len(parts)
        # repeat(n, ...)
        m = re.search(r'repeat\(\s*(\d+)', tpl)
        if m:
            return max(2, int(m.group(1)))
        visible = [c for c in node.children
                   if isinstance(c, Node) and not _is_hidden(c)]
        if len(visible) >= 2:
            return len(visible)
        return 1
    if 'flex' in display:
        direction = node.style.get('flex-direction', '').lower()
        if 'column' in direction:
            return 1
        visible = [c for c in node.children
                   if isinstance(c, Node) and not _is_hidden(c)]
        if len(visible) >= 2:
            return min(len(visible), 4)
        return 1
    return 1


def _estimate_text_height_px(runs, width_px, size_px):
    chars = sum(len(t) for t, _ in runs)
    if chars == 0:
        return 0.0
    avg_char_px = max(4.0, size_px * 0.55)
    per_line = max(8.0, width_px / avg_char_px)
    lines = max(1.0, chars / per_line)
    # account for explicit newlines
    lines += sum(t.count('\n') for t, _ in runs) * 0.9
    return lines * size_px * 1.35 + 8.0


class Block:
    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        """Render into the slide. Returns height used in px."""
        return 0.0

    def estimate(self, width_px, ctx):
        return 0.0


class TextBlock(Block):
    def __init__(self, node, size_px, bold=False, color=None, align=None,
                 space_after=6.0, bullet=False, level=0, anchor_top=False,
                 alpha=None):
        self.node = node
        self.size_px = size_px
        self.bold = bold
        self.color = color
        self.alpha = alpha
        self.align = align
        self.space_after = space_after
        self.bullet = bullet
        self.level = level

    def _runs(self):
        return _clean_runs(_inline_runs(self.node))

    def estimate(self, width_px, ctx):
        runs = self._runs()
        if not runs and not self.node.get_text().strip():
            return 0.0
        return _estimate_text_height_px(runs, width_px, self.size_px) + self.space_after

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        runs = self._runs()
        if not runs:
            return 0.0
        height_px = min(self.estimate(width_px, ctx), max(20.0, max_h_px))
        box = shapes.add_textbox(_px_to_emu(left_px), _px_to_emu(top_px),
                                 _px_to_emu(width_px), _px_to_emu(height_px))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        align = self.align if self.align is not None else _para_align(self.node)
        # split explicit newlines into separate paragraphs
        first = True
        for text, fmt in runs:
            for chunk in text.split('\n'):
                chunk = chunk.strip()
                if not chunk:
                    continue
                _add_paragraph(box.text_frame, [(chunk, fmt)], align=align,
                               space_after_pt=2.0, first=first,
                               bullet=self.bullet if first else False,
                               level=self.level, default_size_px=self.size_px,
                               default_color=self.color, default_bold=self.bold,
                               default_alpha=self.alpha,
                               font_name=ctx.font_name)
                first = False
        _no_line(box)
        return height_px


class ListBlock(Block):
    def __init__(self, node, size_px=14.0, color=None, alpha=None):
        self.node = node
        self.size_px = size_px
        self.color = color
        self.alpha = alpha

    def _items(self):
        items = []
        for child in self.node.children:
            if isinstance(child, Node) and child.tag == 'li' and not _is_hidden(child):
                items.append(child)
            elif isinstance(child, Node) and child.tag in ('ul', 'ol'):
                items.append(child)
        return items

    def estimate(self, width_px, ctx):
        total = 0.0
        for item in self._items():
            if isinstance(item, Node) and item.tag in ('ul', 'ol'):
                total += ListBlock(item, self.size_px, self.color).estimate(width_px - 24, ctx)
            else:
                runs = _clean_runs(_inline_runs(item))
                total += _estimate_text_height_px(runs, width_px - 24, self.size_px) + 4.0
        return total + 6.0

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        items = self._items()
        if not items:
            return 0.0
        height_px = min(self.estimate(width_px, ctx), max(20.0, max_h_px))
        box = shapes.add_textbox(_px_to_emu(left_px), _px_to_emu(top_px),
                                 _px_to_emu(width_px), _px_to_emu(height_px))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        align = _para_align(self.node)
        first = True
        ordered = self.node.tag == 'ol'
        for idx, item in enumerate(items, 1):
            if isinstance(item, Node) and item.tag in ('ul', 'ol'):
                sub = ListBlock(item, self.size_px, self.color, self.alpha)
                for sub_item in sub._items():
                    runs = _clean_runs(_inline_runs(sub_item))
                    if runs:
                        _add_paragraph(box.text_frame, runs, align=align, first=first,
                                       bullet=not ordered, level=1,
                                       default_size_px=self.size_px,
                                       default_color=self.color,
                                       default_alpha=self.alpha,
                                       font_name=ctx.font_name)
                        first = False
                continue
            runs = _clean_runs(_inline_runs(item))
            if not runs:
                continue
            _add_paragraph(box.text_frame, runs, align=align, first=first,
                           bullet=True, level=0, ordered=ordered,
                           default_size_px=self.size_px,
                           default_color=self.color, default_alpha=self.alpha,
                           font_name=ctx.font_name)
            first = False
        _no_line(box)
        return height_px


class ImageBlock(Block):
    def __init__(self, src, alt='', height_px=None, border_radius=False):
        self.src = src
        self.alt = alt
        self.fixed_h = height_px

    def _data(self, ctx):
        return _image_bytes(self.src, ctx.tenant_id)

    def estimate(self, width_px, ctx):
        data = self._data(ctx)
        if not data:
            return 0.0
        iw, ih = _image_size(data)
        if not iw or not ih:
            return width_px * 0.5
        h = width_px * ih / iw
        if self.fixed_h:
            h = min(h, self.fixed_h)
        return min(h, 460.0)

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        data = self._data(ctx)
        if not data:
            return 0.0
        iw, ih = _image_size(data)
        if iw and ih:
            height_px = width_px * ih / iw
        else:
            height_px = width_px * 0.5625
        if self.fixed_h:
            height_px = min(height_px, self.fixed_h)
        height_px = min(height_px, max(30.0, max_h_px))
        # re-fit width to the capped height to avoid distortion
        if iw and ih and height_px < width_px * ih / iw:
            width_px = height_px * iw / ih
            left_px = left_px  # keep right-aligned flow start
        try:
            shapes.add_picture(BytesIO(data), _px_to_emu(left_px), _px_to_emu(top_px),
                               _px_to_emu(width_px), _px_to_emu(height_px))
        except Exception:
            return 0.0
        return height_px


class TableBlock(Block):
    def __init__(self, node, rtl=True):
        self.node = node
        self.rtl = rtl

    def _grid(self):
        rows = []
        header = False
        for section in self.node.children:
            if not isinstance(section, Node):
                continue
            if section.tag in ('thead', 'tbody', 'tfoot'):
                if section.tag == 'thead':
                    header = True
                for tr in section.children:
                    if isinstance(tr, Node) and tr.tag == 'tr':
                        rows.append(tr)
            elif section.tag == 'tr':
                rows.append(section)
        grid = []
        for tr in rows:
            cells = []
            for cell in tr.children:
                if isinstance(cell, Node) and cell.tag in ('td', 'th'):
                    if cell.tag == 'th':
                        header = True
                    colspan = int(cell.attrs.get('colspan', '1') or 1)
                    cells.append((cell, min(max(colspan, 1), 4)))
            if cells:
                grid.append(cells)
        if not grid:
            return [], False
        ncols = max(sum(span for _, span in r) for r in grid)
        norm = []
        for row in grid:
            flat = []
            for cell, span in row:
                flat.append(cell)
                for _ in range(span - 1):
                    flat.append(cell)
            while len(flat) < ncols:
                flat.append(None)
            norm.append(flat[:ncols])
        return norm, header

    def estimate(self, width_px, ctx):
        grid, _ = self._grid()
        if not grid:
            return 0.0
        row_h = 34.0 if len(grid) <= 8 else 28.0
        return len(grid) * row_h + 8.0

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        grid, has_header = self._grid()
        if not grid:
            return 0.0
        nrows, ncols = len(grid), len(grid[0])
        est = self.estimate(width_px, ctx)
        avail = max(60.0, max_h_px)
        scale = min(1.0, avail / est) if est > 0 else 1.0
        font_px = max(8.0, (13.0 if ncols <= 5 else 11.0) * scale)
        header_px = max(9.0, (14.0 if ncols <= 5 else 12.0) * scale)
        row_h_px = (34.0 if nrows <= 8 else 28.0) * max(scale, 0.55)
        height_px = row_h_px * nrows
        try:
            graphic = shapes.add_table(nrows, ncols, _px_to_emu(left_px),
                                       _px_to_emu(top_px), _px_to_emu(width_px),
                                       _px_to_emu(height_px))
        except Exception:
            return 0.0
        table = graphic.table
        col_w = _px_to_emu(width_px / ncols)
        for i in range(ncols):
            try:
                table.columns[i].width = col_w
            except Exception:
                pass
        for r in range(nrows):
            try:
                table.rows[r].height = _px_to_emu(row_h_px)
            except Exception:
                pass
            for c in range(ncols):
                # PowerPoint tables lay out left-to-right while an RTL HTML
                # table starts at the right: mirror the column order.
                src_c = (ncols - 1 - c) if self.rtl else c
                node = grid[r][src_c]
                cell = table.cell(r, c)
                try:
                    cell.margin_top = _px_to_emu(3)
                    cell.margin_bottom = _px_to_emu(3)
                    cell.margin_left = _px_to_emu(6)
                    cell.margin_right = _px_to_emu(6)
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                except Exception:
                    pass
                is_header = has_header and r == 0
                fill = None
                if is_header:
                    fill = ctx.primary
                elif node is not None:
                    fill = _node_bg(node)
                    if fill is None:
                        # look at row node background
                        fill = None
                if fill is not None:
                    try:
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = fill
                    except Exception:
                        pass
                _cell_border(cell)
                tf = cell.text_frame
                try:
                    tf.word_wrap = True
                    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
                except Exception:
                    pass
                if node is None:
                    continue
                runs = _clean_runs(_inline_runs(node))
                if not runs:
                    text = _strip_icons(node.get_text()).strip()
                    runs = [(text, {'bold': False, 'italic': False, 'size_px': None,
                                    'color': None, 'link': None})] if text else []
                if not runs:
                    continue
                align = _para_align(node)
                size = header_px if is_header else font_px
                color = RGBColor(0xFF, 0xFF, 0xFF) if is_header else None
                _add_paragraph(tf, runs, align=align, space_after_pt=1.0,
                               first=True, default_size_px=size,
                               default_color=color, default_bold=is_header,
                               font_name=ctx.font_name)
        return height_px


class CardBlock(Block):
    """Colored/bordered container rendered as a filled shape with inner flow."""

    def __init__(self, node, inner, side_bar=None):
        self.node = node
        self.inner = inner
        self.side_bar = side_bar  # (side, width_px, RGBColor) e.g. gold side rule

    def estimate(self, width_px, ctx):
        pad = 24.0
        total = pad
        for b in self.inner:
            total += b.estimate(width_px - pad * 2, ctx) + 6.0
        return total + pad

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        height_px = min(self.estimate(width_px, ctx), max(40.0, max_h_px))
        fill, fill_alpha = _node_bg_alpha(self.node)
        shape = shapes.add_shape(_card_shape_type(self.node),
                                 _px_to_emu(left_px), _px_to_emu(top_px),
                                 _px_to_emu(width_px), _px_to_emu(height_px))
        if fill is not None:
            _set_shape_fill(shape, fill, alpha_pct=fill_alpha)
        else:
            try:
                shape.fill.background()
            except Exception:
                pass
        if not _apply_border(shape, self.node):
            _no_line(shape)
        try:
            shape.text_frame.word_wrap = True
        except Exception:
            pass
        if self.side_bar is not None:
            side, bar_w, bar_color = self.side_bar
            bw = min(bar_w, 12.0)
            if side == 'right':
                bx, by, bw_px, bh_px = left_px + width_px - bw, top_px + 8, bw, height_px - 16
            elif side == 'left':
                bx, by, bw_px, bh_px = left_px, top_px + 8, bw, height_px - 16
            elif side == 'top':
                bx, by, bw_px, bh_px = left_px + 8, top_px, width_px - 16, bw
            else:
                bx, by, bw_px, bh_px = left_px + 8, top_px + height_px - bw, width_px - 16, bw
            if bw_px > 0 and bh_px > 0:
                bar = shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                       _px_to_emu(bx), _px_to_emu(by),
                                       _px_to_emu(bw_px), _px_to_emu(bh_px))
                _set_shape_fill(bar, bar_color)
                _no_line(bar)
        # Render inner blocks as independent shapes stacked inside the card
        pad = 14.0
        inner_top = top_px + pad
        inner_w = width_px - pad * 2
        # draw inner content on top of the card shape
        for b in self.inner:
            used = b.render(slide, shapes, left_px + pad, inner_top, inner_w,
                            ctx, max(20.0, top_px + height_px - pad - inner_top))
            inner_top += used + 6.0
        return height_px


def _col_spec(kid):
    """Explicit column width hint: width, then min/max-width (icon boxes)."""
    for prop in ('width', 'min-width', 'max-width', 'flex-basis'):
        value = _parse_px(kid.style.get(prop, ''), None)
        if value:
            return value
    return None


def _split_widths(specs, total_w, gap=20.0):
    """Column widths: explicit px specs honoured, rest shared equally."""
    n = len(specs)
    if n == 0:
        return []
    fixed = [min(max(s or 0, 0), total_w) if s else 0 for s in specs]
    flex_count = sum(1 for f in fixed if not f)
    remaining = max(0.0, total_w - gap * (n - 1) - sum(fixed))
    per_flex = remaining / max(1, flex_count)
    return [f if f else per_flex for f in fixed]


class ColumnsBlock(Block):
    def __init__(self, columns, rtl=True, widths=None, align='fill'):
        # columns: list of list[Block] in DOM order; widths: px specs or None.
        # align fill spreads across the full width; start hugs the row start
        # (right in RTL) at natural widths — for inline-flex pills/badges.
        self.columns = columns
        self.rtl = rtl
        self.widths = widths
        self.align = align

    def _geometry(self, width_px, ctx=None):
        n = max(1, len(self.columns))
        gap = 20.0
        specs = list(self.widths or []) + [None] * n
        specs = specs[:n]
        if self.align != 'fill':
            # Caller supplies concrete widths (natural estimates); never stretch.
            widths = [min(s or 0, width_px) if s else width_px / n for s in specs]
            return widths, gap
        return _split_widths(specs, width_px, gap), gap

    def estimate(self, width_px, ctx):
        widths, gap = self._geometry(width_px, ctx)
        if self.align != 'fill':
            return sum(widths) + gap * (max(0, len(widths) - 1))
        return max((sum(b.estimate(cw, ctx) + 6.0 for b in col)
                    for col, cw in zip(self.columns, widths)),
                   default=0.0)

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        widths, gap = self._geometry(width_px, ctx)
        n = len(self.columns)
        total = sum(widths) + gap * max(0, n - 1)
        if self.align == 'fill' or total >= width_px:
            x0 = left_px
        elif self.align == 'center':
            x0 = left_px + (width_px - total) / 2
        elif (self.align == 'start') == (not self.rtl):
            x0 = left_px  # LTR start / RTL end
        else:
            x0 = left_px + width_px - total  # RTL start / LTR end
        # x offsets in visual order; RTL reverses DOM order
        order = list(range(n))
        if self.rtl:
            order = order[::-1]
        x_offsets, cursor = {}, 0.0
        for i in order:
            x_offsets[i] = cursor
            cursor += widths[i] + gap
        heights = []
        for i, col in enumerate(self.columns):
            x = x0 + x_offsets[i]
            cw = widths[i]
            y = top_px
            for b in col:
                used = b.render(slide, shapes, x, y, cw,
                                ctx, max(20.0, max_h_px - (y - top_px)))
                y += used + 6.0
            heights.append(y - top_px)
        return max(heights) if heights else 0.0


class SpacerBlock(Block):
    def __init__(self, height_px=12.0):
        self.height_px = height_px

    def estimate(self, width_px, ctx):
        return self.height_px

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        return self.height_px


class RuleBlock(Block):
    def __init__(self, color=None, width_px=None, height_px=3.0, centered=True,
                 oval=False):
        self.color = color
        self.width_px = width_px
        self.height_px = height_px
        self.centered = centered
        self.oval = oval

    def estimate(self, width_px, ctx):
        return self.height_px + 7.0

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        w = min(self.width_px or width_px, width_px)
        x = left_px + (width_px - w) / 2 if self.centered else left_px
        bar = shapes.add_shape(MSO_SHAPE.OVAL if self.oval else MSO_SHAPE.RECTANGLE,
                               _px_to_emu(x),
                               _px_to_emu(top_px + 3), _px_to_emu(w),
                               _px_to_emu(self.height_px))
        _set_shape_fill(bar, self.color or RGBColor(0xCB, 0xD5, 0xE1))
        _no_line(bar)
        return 10.0


# --------------------------------------------------------------------------
# HTML -> blocks
# --------------------------------------------------------------------------

_HEADING_SIZES = {'h1': 26.0, 'h2': 23.0, 'h3': 19.0, 'h4': 16.0}


def _node_dir(node, parent_rtl=True):
    """Effective base direction of a node (dir attr or CSS direction)."""
    direct = str(node.attrs.get('dir', '') or '').strip().lower()
    if direct == 'rtl':
        return True
    if direct == 'ltr':
        return False
    css = str(node.style.get('direction', '') or '').strip().lower()
    if css == 'rtl':
        return True
    if css == 'ltr':
        return False
    return parent_rtl


_ARABIC_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]')


def _serialize_svg(node):
    """Serialize an svg Node subtree back to an SVG document string."""
    import html as _html

    def esc_attr(value):
        return _html.escape(str(value), quote=True)

    def walk(n):
        if isinstance(n, str):
            return _html.escape(n)
        if not isinstance(n, Node):
            return ''
        attrs = ''.join(f' {k}="{esc_attr(v)}"' for k, v in n.attrs.items())
        inner = n.text + ''.join(walk(c) for c in n.children)
        if not inner and n.tag.lower() not in ('text', 'tspan', 'title', 'desc'):
            return f'<{n.tag}{attrs}/>'
        return f'<{n.tag}{attrs}>{inner}</{n.tag}>'

    svg = walk(node)
    if 'xmlns' not in svg[:200]:
        svg = svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg


def _rasterize_svg(node, scale=2.0):
    """Render an SVG node to PNG bytes. Returns None when the SVG carries
    Arabic text (MuPDF cannot shape it — those stay editable text instead)."""
    try:
        if _ARABIC_RE.search(node.get_text() or ''):
            return None
        svg = _serialize_svg(node)
        import fitz
        doc = fitz.open(stream=svg.encode('utf-8'), filetype='svg')
        if not len(doc):
            return None
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale))
        if not pix.width or not pix.height:
            return None
        return pix.tobytes('png')
    except Exception:
        return None


class RawImageBlock(Block):
    """Picture from already-loaded bytes (e.g. a rasterized chart)."""

    def __init__(self, data, width_px=None, height_px=None):
        self.data = data
        self.width_px = width_px
        self.height_px = height_px

    def estimate(self, width_px, ctx):
        if not self.data:
            return 0.0
        iw, ih = _image_size(self.data)
        w = self.width_px or width_px
        w = min(w, width_px)
        h = self.height_px or (w * ih / iw if iw and ih else w * 0.5625)
        return min(h, 460.0)

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        if not self.data:
            return 0.0
        iw, ih = _image_size(self.data)
        w = min(self.width_px or width_px, width_px)
        h = self.height_px or (w * ih / iw if iw and ih else w * 0.5625)
        h = min(h, max(30.0, max_h_px))
        if iw and ih and h < (w * ih / iw) - 1:
            w = h * iw / ih
        try:
            shapes.add_picture(BytesIO(self.data), _px_to_emu(left_px),
                               _px_to_emu(top_px), _px_to_emu(w), _px_to_emu(h))
        except Exception:
            return 0.0
        return h


class BgImageBlock(Block):
    """Panel with a background image and editable content on top."""

    def __init__(self, src, inner, tenant_id=None):
        self.src = src
        self.inner = inner
        self.tenant_id = tenant_id

    def estimate(self, width_px, ctx):
        if not self.inner:
            data = _image_bytes(self.src, self.tenant_id)
            if data:
                iw, ih = _image_size(data)
                if iw and ih:
                    return min(width_px * ih / iw, 460.0)
            return 200.0
        total = sum(b.estimate(width_px, ctx) + 6.0 for b in self.inner)
        return max(total, 120.0)

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        height_px = min(self.estimate(width_px, ctx), max(60.0, max_h_px))
        data = _image_bytes(self.src, self.tenant_id)
        if data:
            iw, ih = _image_size(data)
            ih_px = width_px * ih / iw if iw and ih else height_px
            try:
                # cover-fit the panel so no gaps show behind the content
                shapes.add_picture(BytesIO(data), _px_to_emu(left_px),
                                   _px_to_emu(top_px), _px_to_emu(width_px),
                                   _px_to_emu(max(height_px, min(ih_px, max_h_px))))
            except Exception:
                pass
        y = top_px + 10.0
        for b in self.inner:
            used = b.render(slide, shapes, left_px + 10.0, y, width_px - 20.0,
                            ctx, max(20.0, top_px + height_px - 10.0 - y))
            y += used + 6.0
        return height_px


def _svg_text_fallback(node):
    texts = []
    for t in node.find_all({'text', 'tspan'}):
        val = _strip_icons(t.get_text()).strip()
        if val:
            texts.append(val)
    blocks = []
    for val in texts[:12]:
        n = Node('p', {})
        n.children = [val]
        blocks.append(TextBlock(n, 12.0, space_after=3.0))
    return blocks


def _text_color_alpha(node):
    raw = node.style.get('color', '')
    return _parse_color(raw), _parse_rgba_alpha(raw)


def _node_to_blocks(node, ctx, rtl=True):
    """Convert a flow node into a list of Blocks."""
    if not isinstance(node, Node) or _is_hidden(node):
        return []
    if node.tag in _SKIP_TAGS:
        return []
    if _is_header_node(node) or _is_footer_node(node):
        return []

    tag = node.tag
    rtl = _node_dir(node, rtl)

    if tag in ('h1', 'h2', 'h3', 'h4'):
        size = _parse_font_size(node.style.get('font-size'), _HEADING_SIZES[tag])
        color, alpha = _text_color_alpha(node)
        bold = True
        if not node.get_text().strip():
            return []
        return [TextBlock(node, size, bold=bold, color=color, alpha=alpha,
                          space_after=8.0)]

    if tag == 'p':
        if not node.get_text().strip():
            return []
        size = _parse_font_size(node.style.get('font-size'), 13.0)
        color, alpha = _text_color_alpha(node)
        return [TextBlock(node, size, color=color, alpha=alpha, space_after=6.0)]

    if tag in ('ul', 'ol'):
        if not node.get_text().strip():
            return []
        size = _parse_font_size(node.style.get('font-size'), 13.0)
        color, alpha = _text_color_alpha(node)
        return [ListBlock(node, size, color, alpha)]

    if tag == 'li':
        if not node.get_text().strip():
            return []
        return [ListBlock(Node('ul', {}), 13.0, None)]

    if tag == 'table':
        block = TableBlock(node, rtl=rtl)
        grid, _ = block._grid()
        if not grid:
            return []
        return [block]

    if tag == 'img':
        src = node.attrs.get('src', '')
        if not src or '##' in src:
            # Fall back to the first srcset candidate when src is missing.
            srcset = str(node.attrs.get('srcset', '') or '')
            first = srcset.split(',')[0].strip().split()[0] if srcset.strip() else ''
            if first and '##' not in first:
                src = first
        if not src or '##' in src:
            return []
        h = _parse_px(node.style.get('height'), None)
        return [ImageBlock(src, node.attrs.get('alt', ''), height_px=h)]

    if tag == 'hr':
        return [RuleBlock(_parse_color(node.style.get('background-color'))
                          or _parse_color(node.style.get('color')))]

    if tag in ('div', 'span') and not node.get_text().strip() and not node.find_all({'img', 'table', 'svg', 'ul', 'ol'}):
        # Thin decorative bar (gold rules under titles etc.) or dot.
        w = _parse_px(node.style.get('width'), None)
        h = _parse_px(node.style.get('height'), None)
        fill = _node_bg(node)
        if fill is not None and w is not None and h is not None:
            if w <= 18 and h <= 18:
                return [RuleBlock(fill, width_px=w, height_px=h)]
            if w >= 20 and h <= 12:
                return [RuleBlock(fill, width_px=w, height_px=h)]
            if h >= 20 and w <= 12:
                return [RuleBlock(fill, width_px=w, height_px=h, centered=False)]
        if not node.children:
            return []

    if tag == 'svg':
        png = _rasterize_svg(node)
        if png:
            w = _parse_px(node.attrs.get('width'), 0) or _parse_px(node.style.get('width'), 0)
            h = _parse_px(node.attrs.get('height'), 0) or _parse_px(node.style.get('height'), 0)
            return [RawImageBlock(png, width_px=w or None, height_px=h or None)]
        return _svg_text_fallback(node)

    if tag == 'br':
        return [SpacerBlock(6.0)]

    # Generic container
    bg_url = _extract_bg_url(node.style.get('background-image', '')
                             or node.style.get('background', ''))
    if bg_url and tag == 'div':
        # decorative/cover-like panel -> picture block (skip tiny trackers)
        w = _parse_px(node.style.get('width'), 0)
        h = _parse_px(node.style.get('height'), 0)
        if (w and w < 40) or (h and h < 40):
            return []
        kids = [c for c in node.children
                if isinstance(c, Node) and not _is_hidden(c) and c.tag not in _SKIP_TAGS]
        if kids:
            # Panel keeps its picture AND its content (overlays, captions).
            inner = []
            for kid in kids:
                inner.extend(_node_to_blocks(kid, ctx, rtl))
            if inner:
                return [BgImageBlock(bg_url, inner, ctx.tenant_id)]
        return [ImageBlock(bg_url)]

    children_blocks = []
    for child in node.children:
        if isinstance(child, Node):
            children_blocks.extend(_node_to_blocks(child, ctx, rtl))
        elif isinstance(child, str) and child.strip():
            ghost = Node('span', {})
            ghost.children = [child]
            size = _parse_font_size(node.style.get('font-size'), 13.0)
            color, alpha = _text_color_alpha(node)
            children_blocks.append(TextBlock(ghost, size, color=color, alpha=alpha))

    if not children_blocks:
        return []

    # Two-column grids/flex rows become side-by-side columns
    if tag == 'div' and _grid_columns(node) >= 2:
        kids = [c for c in node.children
                if isinstance(c, Node) and not _is_hidden(c) and c.tag not in _SKIP_TAGS]
        if len(kids) >= 2:
            pairs = []
            for kid in kids:
                sub = _node_to_blocks(kid, ctx, rtl)
                if sub:
                    pairs.append((kid, sub))
            if len(pairs) >= 2:
                display = str(node.style.get('display', '')).lower()
                if 'inline-flex' in display \
                        and not _parse_px(node.style.get('width'), None):
                    # Pills/badges hug their content instead of filling the row.
                    widths = [min(_col_spec(k) or _estimate_node_width(k, ctx, 500.0),
                                  600.0) for k, _s in pairs]
                    return [ColumnsBlock([s for _k, s in pairs], rtl=rtl,
                                         widths=widths, align='start')]
                widths = [_col_spec(k) for k, _s in pairs]
                return [ColumnsBlock([s for _k, s in pairs], rtl=rtl, widths=widths)]
        # fall through to stacked rendering

    # Cards: background color / border / radius -> grouped shape.
    # A thick single-side border (gold side rules) also groups its text.
    fill = _node_bg(node)
    has_border = 'border' in node.style or 'border-top' in node.style
    has_radius = 'radius' in ''.join(node.style.keys())
    side_bar = _parse_side_bar(node)
    if tag == 'div' and (fill is not None or (has_border and has_radius)
                         or side_bar is not None) and children_blocks:
        # Only treat as a card when it actually wraps multiple/textual content
        # and is not the full-bleed slide root handled elsewhere.
        return [CardBlock(node, children_blocks, side_bar=side_bar)]

    return children_blocks


def _li_to_list_fallback(li_node):
    ghost = Node('ul', {})
    ghost.children = [li_node]
    return [ListBlock(ghost, 13.0, None)]


# --------------------------------------------------------------------------
# Slide chrome: header / footer / cover
# --------------------------------------------------------------------------

def _extract_chrome(root):
    """Split header/footer nodes out of the slide root. Returns (header, footer, body_kids)."""
    header = footer = None
    body = []
    for child in root.children:
        if isinstance(child, Node) and not _is_hidden(child):
            if header is None and _is_header_node(child):
                header = child
                continue
            if footer is None and _is_footer_node(child):
                footer = child
                continue
        body.append(child)
    return header, footer, body


def _header_title(header):
    if header is None:
        return ''
    h = header.find_all({'h1', 'h2', 'h3'})
    if h:
        return _strip_icons(h[0].get_text()).strip()
    # Canonical chrome carries the title in a bold 16px span, not a heading.
    for node in header.find_all({'span', 'div', 'p'}):
        if _is_hidden(node):
            continue
        try:
            weight = str(node.style.get('font-weight', '')).lower()
            bold = weight in ('bold', '700', '800', '900') or (
                weight.isdigit() and int(weight) >= 700)
        except Exception:
            bold = False
        size = _parse_font_size(node.style.get('font-size'), 0)
        text = _strip_icons(node.get_text()).strip()
        if bold and size >= 14 and text and len(text) <= 160:
            return text
    return _strip_icons(header.get_text()).strip()[:120]


def _header_logos(header):
    if header is None:
        return []
    return [img.attrs.get('src', '') for img in header.find_all({'img'})
            if img.attrs.get('src') and '##' not in img.attrs.get('src', '')][:3]


def _header_accent(header, branding):
    """Accent-bar color used in the header (defaults to branding accent)."""
    if header is not None:
        for node in header.find_all({'span', 'div'}):
            w = _parse_px(node.style.get('width'), 0)
            h = _parse_px(node.style.get('height'), 0)
            if 1 <= w <= 8 and h >= 16:
                color = _parse_color(node.style.get('background-color', '')
                                     or node.style.get('background', ''))
                if color is not None:
                    return color
    try:
        return _hex_to_rgb(normalize_hex_color(
            (branding or {}).get('accent_color'), '#c4a35a'))
    except Exception:
        return RGBColor(0xC4, 0xA3, 0x5A)


def _footer_parts(footer, project_name, counter):
    """Extract (project, middle, counter) texts from a footer node."""
    project, middle = project_name, ''
    if footer is not None:
        spans = [n for n in footer.find_all({'span', 'div'})
                 if not _is_hidden(n) and _strip_icons(n.get_text()).strip()]
        counter_node = None
        for n in footer.find_all({'span', 'div'}):
            if n.attrs.get('data-slide-counter') is not None:
                counter_node = n
                break
        texts = []
        for n in spans:
            if n is counter_node:
                continue
            # skip wrappers that merely contain the other spans
            t = _strip_icons(n.get_text()).strip()
            if t and all(t != _strip_icons(o.get_text()).strip() for o in spans if o is not n):
                texts.append(t)
            elif t and n.tag == 'span':
                texts.append(t)
        # de-duplicate while keeping order, drop counter-looking strings
        seen = []
        for t in texts:
            if t == counter or re.fullmatch(r'[\d\s—\-–/]+', t):
                continue
            if t not in seen:
                seen.append(t)
        if seen:
            project = seen[0]
        if len(seen) > 1:
            middle = seen[1][:140]
        if counter_node is not None:
            found = _strip_icons(counter_node.get_text()).strip()
            if found:
                counter = found
    return project, middle, counter


def _footer_colors(branding, primary):
    try:
        primary_hex = normalize_hex_color((branding or {}).get('primary_color'), '#0b1f33')
        secondary = (branding or {}).get('secondary_color')
        bg_hex = dark_surface_color(primary_hex, secondary)
        bg = _hex_to_rgb(bg_hex)
    except Exception:
        bg = RGBColor(0x1F, 0x2A, 0x37)
        bg_hex = '#1f2a37'
    try:
        fg = _hex_to_rgb(readable_text_color('#ffffff', bg_hex, ('#0f172a',)))
    except Exception:
        fg = RGBColor(0xFF, 0xFF, 0xFF)
    try:
        accent_hex = normalize_hex_color((branding or {}).get('accent_color'), '#c4a35a')
        accent = _hex_to_rgb(readable_text_color(accent_hex, bg_hex, ('#ffffff',)))
    except Exception:
        accent = fg
    return bg, fg, accent


def _render_header_band(slide, shapes, header, title, ctx, primary, top_px=0.0):
    height_px = 56.0
    band = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(0), _px_to_emu(top_px),
                            _px_to_emu(SLIDE_W_PX), _px_to_emu(height_px))
    _set_shape_fill(band, RGBColor(0xFF, 0xFF, 0xFF))
    _no_line(band)
    # 2px primary rule under the header, like the site chrome.
    rule = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(0),
                            _px_to_emu(top_px + height_px - 2),
                            _px_to_emu(SLIDE_W_PX), _px_to_emu(2))
    _set_shape_fill(rule, primary)
    _no_line(rule)
    # Logos (left side, LTR order like the site header)
    x = 24.0
    for src in _header_logos(header):
        data = _image_bytes(src, ctx.tenant_id)
        if not data:
            continue
        iw, ih = _image_size(data)
        h = 40.0
        w = h * iw / ih if iw and ih else 90.0
        w = min(w, 122.0)
        try:
            shapes.add_picture(BytesIO(data), _px_to_emu(x), _px_to_emu(top_px + 8),
                               _px_to_emu(w), _px_to_emu(h))
        except Exception:
            continue
        x += w + 10.0
        if x > 320:
            break
    # Accent bar + title
    text = _strip_icons(title).strip()
    if _header_logos(header):
        bar = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(x),
                               _px_to_emu(top_px + 14), _px_to_emu(3), _px_to_emu(28))
        _set_shape_fill(bar, _header_accent(header, ctx.branding))
        _no_line(bar)
        x += 12.0
    if text:
        box = shapes.add_textbox(_px_to_emu(x), _px_to_emu(top_px + 8),
                                 _px_to_emu(max(200.0, SLIDE_W_PX - x - 24)),
                                 _px_to_emu(42))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        _add_paragraph(box.text_frame, [(text, {'bold': True, 'italic': False,
                                                'size_px': None, 'color': None,
                                                'link': None})],
                       align=PP_ALIGN.RIGHT, first=True, default_size_px=16.0,
                       default_color=primary, default_bold=True,
                       font_name=ctx.font_name)
        _no_line(box)
    return height_px


def _render_footer_band(slide, shapes, footer, project_name, counter, ctx, bottom_px=720.0):
    height_px = 36.0
    top_px = bottom_px - height_px
    bg, fg, accent = _footer_colors(ctx.branding, ctx.primary)
    project, middle, counter = _footer_parts(footer, project_name, counter)
    band = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(0), _px_to_emu(top_px),
                            _px_to_emu(SLIDE_W_PX), _px_to_emu(height_px))
    _set_shape_fill(band, bg)
    _no_line(band)
    # Project name (right)
    if project:
        box = shapes.add_textbox(_px_to_emu(640), _px_to_emu(top_px + 5),
                                 _px_to_emu(SLIDE_W_PX - 664), _px_to_emu(26))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        _add_paragraph(box.text_frame, [(project, {'bold': True, 'italic': False,
                                                   'size_px': None, 'color': None,
                                                   'link': None})],
                       align=PP_ALIGN.RIGHT, first=True, default_size_px=12.0,
                       default_color=fg, default_bold=True,
                       font_name=ctx.font_name)
        _no_line(box)
    # Middle description (center)
    if middle:
        box = shapes.add_textbox(_px_to_emu(300), _px_to_emu(top_px + 7),
                                 _px_to_emu(330), _px_to_emu(22))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        _add_paragraph(box.text_frame, [(middle, {'bold': False, 'italic': False,
                                                  'size_px': None, 'color': None,
                                                  'link': None})],
                       align=PP_ALIGN.CENTER, first=True, default_size_px=10.0,
                       default_color=fg, font_name=ctx.font_name)
        _no_line(box)
    # Counter (left, LTR)
    if counter:
        box = shapes.add_textbox(_px_to_emu(24), _px_to_emu(top_px + 5),
                                 _px_to_emu(180), _px_to_emu(26))
        try:
            box.text_frame.word_wrap = True
        except Exception:
            pass
        _add_paragraph(box.text_frame, [(counter, {'bold': True, 'italic': False,
                                                   'size_px': None, 'color': None,
                                                   'link': None})],
                       align=PP_ALIGN.LEFT, first=True, default_size_px=12.0,
                       default_color=accent, default_bold=True,
                       font_name=ctx.font_name)
        _no_line(box)
    return height_px


def _slide_bg_image(root):
    """Full-bleed background image url for cover-style slides."""
    for child in root.children:
        if not isinstance(child, Node) or _is_hidden(child):
            continue
        url = _extract_bg_url(child.style.get('background-image', '')
                              or child.style.get('background', ''))
        if url:
            return url
    url = _extract_bg_url(root.style.get('background-image', '')
                          or root.style.get('background', ''))
    return url or ''


# --------------------------------------------------------------------------
# Absolute positioning — designed slides (covers, dividers, designer
# overlays) place elements at explicit coordinates. Honouring those rects is
# what makes the export match the site instead of re-flowing everything.
# --------------------------------------------------------------------------

def _parse_len(value, total):
    """CSS length (px or %) into px float, or None for auto/unparseable."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == 'auto':
        return None
    if text.endswith('%'):
        try:
            return float(text[:-1]) * total / 100.0
        except ValueError:
            return None
    return _parse_px(text, None)


def _parse_insets(value, total_w, total_h):
    """Parse CSS inset shorthand into (top, right, bottom, left) px or Nones."""
    parts = [p for p in str(value or '').strip().split() if p]
    if not parts:
        return None, None, None, None
    vals = []
    for i, part in enumerate(parts):
        vals.append(_parse_len(part, total_h if i % 2 == 0 else total_w))
    if len(vals) == 1:
        vals *= 4
    elif len(vals) == 2:
        vals = [vals[0], vals[1], vals[0], vals[1]]
    elif len(vals) == 3:
        vals = [vals[0], vals[1], vals[2], vals[1]]
    else:
        vals = vals[:4]
    return vals[0], vals[1], vals[2], vals[3]


def _abs_rect(node, cw=1280.0, ch=720.0):
    """Absolute rect (x, y, w, h) for a positioned node, else None."""
    if node.style.get('position', '').strip().lower() not in ('absolute', 'fixed'):
        return None
    inset = node.style.get('inset', '').strip()
    top = _parse_len(node.style.get('top'), ch)
    left = _parse_len(node.style.get('left'), cw)
    bottom = _parse_len(node.style.get('bottom'), ch)
    right = _parse_len(node.style.get('right'), cw)
    if inset:
        it, ir, ib, il = _parse_insets(inset, cw, ch)
        top = top if top is not None else it
        right = right if right is not None else ir
        bottom = bottom if bottom is not None else ib
        left = left if left is not None else il
    width = _parse_len(node.style.get('width'), cw)
    height = _parse_len(node.style.get('height'), ch)
    if left is None and right is not None and width is not None:
        left = cw - right - width
    if top is None and bottom is not None and height is not None:
        top = ch - bottom - height
    if left is None:
        left = 0.0
    if top is None:
        top = 0.0
    if width is None:
        width = cw - left - (right or 0.0)
    if height is None:
        height = ch - top - (bottom or 0.0)
    if width <= 0 or height <= 0:
        return None
    return (left, top, width, height)


def _estimate_node_height(node, ctx, width_px):
    """Shrink-to-fit height estimate for an abs-positioned node without height."""
    try:
        if node.tag == 'img':
            src = node.attrs.get('src', '')
            data = _image_bytes(src, ctx.tenant_id) if src else None
            if data:
                iw, ih = _image_size(data)
                if iw and ih:
                    return min(width_px * ih / iw, 500.0)
            return 120.0
        if node.tag == 'table':
            return TableBlock(node).estimate(width_px, ctx)
        if node.tag == 'svg':
            h = _parse_px(node.attrs.get('height'), 0) or _parse_px(node.style.get('height'), 0)
            return min(h or 300.0, 500.0)
        if node.tag in ('h1', 'h2', 'h3', 'h4', 'p', 'li', 'span'):
            runs = _clean_runs(_inline_runs(node))
            size = _parse_font_size(node.style.get('font-size'),
                                    _HEADING_SIZES.get(node.tag, 14.0))
            return _estimate_text_height_px(runs, width_px, size) + 8.0
        blocks = _node_to_blocks(node, ctx)
        total = sum(b.estimate(width_px, ctx) + 8.0 for b in blocks)
        return min(max(total, 20.0), 600.0)
    except Exception:
        return 60.0


def _estimate_node_width(node, ctx, cap=1280.0):
    """Shrink-to-fit width estimate for right-anchored open boxes."""
    try:
        if node.tag == 'img':
            w = _parse_px(node.style.get('width'), 0)
            if w:
                return min(w, cap)
            src = node.attrs.get('src', '')
            data = _image_bytes(src, ctx.tenant_id) if src else None
            if data:
                iw, ih = _image_size(data)
                h = _parse_px(node.style.get('height'), 0) or 100.0
                if iw and ih:
                    return min(h * iw / ih, cap)
            return 120.0
        text_only = not any(isinstance(c, Node) for c in node.children)
        if text_only or node.tag in ('span', 'a', 'h1', 'h2', 'h3', 'h4', 'p', 'li'):
            size = _parse_font_size(node.style.get('font-size'), 14.0)
            chars = len(_strip_icons(node.get_text()).strip())
            return min(max(chars * size * 0.58 + 8.0, 20.0), cap)
        display = str(node.style.get('display', '')).lower()
        kids = [c for c in node.children
                if isinstance(c, Node) and not _is_hidden(c) and c.tag not in _SKIP_TAGS]
        if not kids:
            return min(200.0, cap)
        if 'flex' in display or 'grid' in display:
            gap = _parse_px(node.style.get('gap'), 16.0) or 16.0
            total = sum(_estimate_node_width(k, ctx, cap) for k in kids)
            return min(total + gap * max(0, len(kids) - 1), cap)
        return min(max((_estimate_node_width(k, ctx, cap) for k in kids), default=60.0), cap)
    except Exception:
        return min(200.0, cap)


def _anchored_rect(node, cw, ch, ctx):
    """Absolute rect with shrink-to-fit fallback for open/bottom-anchored boxes.

    CSS absolute boxes without explicit height size to their content; stretching
    them to the slide edge misplaces bottom-anchored strips and stretches side
    rules. Estimate the content height when the markup leaves it open.
    """
    rect = _abs_rect(node, cw, ch)
    if rect is None:
        return None
    x, y, w, h = rect
    width_given = _parse_len(node.style.get('width'), cw)
    if width_given is None:
        left = _parse_len(node.style.get('left'), cw)
        right = _parse_len(node.style.get('right'), cw)
        if left is None and right is not None:
            # Right-anchored open box (flex rows, labels): shrink-to-fit and
            # hug the right edge like the browser instead of filling the row.
            est_w = _estimate_node_width(node, ctx, cw - right)
            est_w = min(max(est_w, 20.0), cw - right)
            return (cw - right - est_w, y, est_w, h)
    explicit_h = _parse_len(node.style.get('height'), ch)
    if explicit_h is not None:
        return rect
    top = _parse_len(node.style.get('top'), ch)
    if top is None and node.style.get('inset', '').strip():
        it, _ir, _ib, _il = _parse_insets(node.style.get('inset'), cw, ch)
        top = it
    bottom = _parse_len(node.style.get('bottom'), ch)
    if top is not None and bottom is None:
        # Open-ended: shrink to content instead of filling to the slide edge.
        est = _estimate_node_height(node, ctx, w)
        return (x, y, w, min(est, ch - y))
    if top is None and bottom is not None:
        est = _estimate_node_height(node, ctx, w)
        est = min(est, ch - bottom)
        return (x, ch - bottom - est, w, est)
    return rect


def _is_veil(node, cw=1280.0, ch=720.0):
    """A full-slide darkening layer (marker attr or gradient veil)."""
    if node.attrs.get('data-cover-overlay') is not None:
        return True
    bg = str(node.style.get('background-image', '')
             or node.style.get('background', '')).lower()
    if 'gradient' not in bg:
        return False
    rect = _abs_rect(node, cw, ch)
    if rect is None:
        return False
    x, y, w, h = rect
    return w >= cw * 0.9 and h >= ch * 0.9


def _parse_side_bar(node):
    """Thick single-side border (gold side rules) -> (side, width_px, color)."""
    for side in ('right', 'left', 'top', 'bottom'):
        raw = str(node.style.get(f'border-{side}', '') or '').strip()
        width, color = None, None
        if raw:
            width = _parse_px(raw, None)
            color = _parse_color(raw)
        else:
            w_raw = node.style.get(f'border-{side}-width')
            if w_raw:
                width = _parse_px(w_raw, None)
                color = _parse_color(node.style.get(f'border-{side}-color', ''))
        if width is not None and width >= 2 and color is not None:
            return (side, width, color)
    return None


def _parse_border(value):
    """Full border shorthand (2px solid #color) -> (width_pt, RGBColor)."""
    if not value:
        return None
    text = str(value).strip().lower()
    if 'none' in text or 'hidden' in text:
        return None
    width = _parse_px(text, None)
    color = _parse_color(text)
    if width is not None and width >= 0.75 and color is not None:
        return (width * 0.75, color)
    return None


def _card_shape_type(node):
    if '50%' in str(node.style.get('border-radius', '')):
        return MSO_SHAPE.OVAL
    return MSO_SHAPE.ROUNDED_RECTANGLE


def _apply_border(shape, node):
    """Apply a full border (circles, outlined cards) to a shape."""
    for prop in ('border', 'border-top', 'border-right', 'border-bottom', 'border-left'):
        parsed = _parse_border(node.style.get(prop, ''))
        if parsed is not None:
            width_pt, color = parsed
            try:
                shape.line.fill.solid()
                shape.line.fill.fore_color.rgb = color
                shape.line.width = Pt(width_pt)
            except Exception:
                pass
            return True
    return False


def _render_designed_slide(slide, shapes, root, body_kids, title, project_label,
                           ctx, branding, primary, slide_type='cover'):
    """Render a designed slide (cover / closing / divider) from its own body.

    Absolutely-positioned elements keep their explicit rects; the remaining
    flow content is laid out inside the slide with the root's own gravity.
    Only when the body yields nothing do we fall back to a plain title.
    """
    cw, ch = SLIDE_W_PX, SLIDE_H_PX
    veil_drawn = False
    bg_url = _slide_bg_image(root)
    if bg_url:
        data = _image_bytes(bg_url, ctx.tenant_id)
        if data:
            try:
                shapes.add_picture(BytesIO(data), _px_to_emu(0), _px_to_emu(0),
                                   _px_to_emu(cw), _px_to_emu(ch))
            except Exception:
                pass
            # Veil when the design carries an overlay marker or gradient veil
            needs_veil = any(
                isinstance(k, Node) and not _is_hidden(k) and _is_veil(k, cw, ch)
                for k in root.children)
            if needs_veil:
                overlay = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(0),
                                           _px_to_emu(0), _px_to_emu(cw),
                                           _px_to_emu(ch))
                _set_shape_fill(overlay, RGBColor(0x0B, 0x1F, 0x33), alpha_pct=45)
                _no_line(overlay)
                veil_drawn = True
    rendered = 0
    for kid in body_kids:
        if not isinstance(kid, Node) or _is_hidden(kid):
            continue
        if _is_veil(kid, cw, ch):
            continue  # already painted as the overlay above
        rect = _anchored_rect(kid, cw, ch, ctx)
        if rect is not None:
            _render_abs_node(slide, shapes, kid, ctx, rect)
            rendered += 1
    flow_blocks = _flow_blocks([k for k in body_kids
                                if not (isinstance(k, Node)
                                        and (_abs_rect(k, cw, ch) is not None
                                             or _is_veil(k, cw, ch)))], ctx)
    if flow_blocks:
        halign, valign = _container_gravity(root)
        _render_flow(slide, shapes, flow_blocks, ctx, 64.0, 40.0,
                     cw - 128.0, ch - 80.0, halign=halign or 'center',
                     valign=valign)
        rendered += len(flow_blocks)
    if not rendered:
        fallback = title or project_label or ''
        if fallback:
            box = shapes.add_textbox(_px_to_emu(120), _px_to_emu(290),
                                     _px_to_emu(cw - 240), _px_to_emu(140))
            try:
                box.text_frame.word_wrap = True
                box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
            except Exception:
                pass
            _add_paragraph(box.text_frame, [(fallback, {'bold': True, 'italic': False,
                                                        'size_px': None, 'color': None,
                                                        'link': None})],
                           align=PP_ALIGN.CENTER, first=True, default_size_px=40.0,
                           default_color=RGBColor(0xFF, 0xFF, 0xFF),
                           default_bold=True, font_name=ctx.font_name)
            _no_line(box)
    if slide_type == 'section_divider' and not any(
            isinstance(k, Node) and 'gold' in (k.get_text() or '').lower()
            for k in body_kids):
        # Deterministic dividers always carry their own bar; this only guards
        # legacy divider bodies that lost it.
        pass


def _container_gravity(node):
    """(halign, valign) from flex alignment props: center/None, center/top."""
    justify = str(node.style.get('justify-content', '')).lower()
    align = str(node.style.get('align-items', '')).lower()
    halign = 'center' if 'center' in align else None
    valign = 'center' if 'center' in justify else 'top'
    return halign, valign


def _render_flow(slide, shapes, blocks, ctx, left_px, top_px, width_px, max_h_px,
                 halign=None, valign='top'):
    total = sum(b.estimate(width_px, ctx) + 8.0 for b in blocks)
    y = top_px
    if valign == 'center' and total < max_h_px:
        y += (max_h_px - total) / 2
    remaining = max_h_px - (y - top_px)
    for block in blocks:
        if remaining <= 24.0:
            break
        if halign == 'center' and isinstance(block, (RuleBlock,)):
            pass  # RuleBlock centers itself
        used = block.render(slide, shapes, left_px, y, width_px, ctx, remaining)
        y += used + 8.0
        remaining = max_h_px - (y - top_px)
    return y - top_px


def _inherited_text_style(parent):
    """Text style a bare-text ghost inherits from its container."""
    if parent is None or not isinstance(parent, Node):
        return {}
    return {prop: parent.style[prop] for prop in
            ('color', 'font-size', 'font-weight', 'font-style',
             'text-align', 'direction', 'line-height')
            if prop in parent.style}


def _flow_blocks(kids, ctx, rtl=True, inherit_from=None):
    blocks = []
    inherited = _inherited_text_style(inherit_from)
    for kid in kids:
        if isinstance(kid, Node):
            blocks.extend(_node_to_blocks(kid, ctx, rtl))
        elif isinstance(kid, str) and kid.strip():
            ghost = Node('p', {})
            ghost.children = [kid]
            if inherited:
                ghost.style = dict(inherited)
            blocks.extend(_node_to_blocks(ghost, ctx, rtl))
    return blocks


def _render_abs_node(slide, shapes, node, ctx, rect, depth=0):
    """Render one absolutely-positioned node inside its explicit rect."""
    if depth > 4:
        return 0.0
    x, y, w, h = rect
    rtl = _node_dir(node, True)
    tag = node.tag
    if tag == 'img':
        src = node.attrs.get('src', '')
        if src and '##' not in src:
            return ImageBlock(src, node.attrs.get('alt', '')).render(
                slide, shapes, x, y, w, ctx, h)
        return 0.0
    if tag == 'table':
        block = TableBlock(node, rtl=rtl)
        grid, _ = block._grid()
        if grid:
            return block.render(slide, shapes, x, y, w, ctx, h)
        return 0.0
    if tag == 'svg':
        png = _rasterize_svg(node)
        if png:
            sw = _parse_px(node.attrs.get('width'), 0) or _parse_px(node.style.get('width'), 0)
            sh = _parse_px(node.attrs.get('height'), 0) or _parse_px(node.style.get('height'), 0)
            return RawImageBlock(png, width_px=min(sw or w, w),
                                 height_px=min(sh or h, h)).render(
                                     slide, shapes, x, y, w, ctx, h)
        for b in _svg_text_fallback(node):
            b.render(slide, shapes, x, y, w, ctx, h)
        return h
    if tag in ('h1', 'h2', 'h3', 'h4', 'p', 'li', 'span'):
        if not node.get_text().strip():
            return 0.0
        size = _parse_font_size(node.style.get('font-size'),
                                _HEADING_SIZES.get(tag, 14.0))
        color = _parse_color(node.style.get('color'))
        box = shapes.add_textbox(_px_to_emu(x), _px_to_emu(y),
                                 _px_to_emu(w), _px_to_emu(h))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        runs = _clean_runs(_inline_runs(node))
        if runs:
            _add_paragraph(box.text_frame, runs, align=_para_align(node),
                           first=True, default_size_px=size, default_color=color,
                           default_bold=(tag in _HEADING_SIZES),
                           font_name=ctx.font_name)
        _no_line(box)
        return h
    # Generic container: background shape, then children (absolute at offsets,
    # flow remainder inside with the container's own gravity).
    fill, fill_alpha = _node_bg_alpha(node)
    bg_url = _extract_bg_url(node.style.get('background-image', '')
                             or node.style.get('background', ''))
    if bg_url:
        try:
            data = _image_bytes(bg_url, ctx.tenant_id)
            if data:
                shapes.add_picture(BytesIO(data), _px_to_emu(x), _px_to_emu(y),
                                   _px_to_emu(w), _px_to_emu(h))
        except Exception:
            pass
    has_full_border = _parse_border(node.style.get('border', '')) is not None
    if fill is not None or has_full_border:
        shape = shapes.add_shape(_card_shape_type(node),
                                 _px_to_emu(x), _px_to_emu(y),
                                 _px_to_emu(w), _px_to_emu(h))
        if fill is not None:
            _set_shape_fill(shape, fill, alpha_pct=fill_alpha)
        else:
            try:
                shape.fill.background()
            except Exception:
                pass
        if not _apply_border(shape, node):
            _no_line(shape)
    side_bar = _parse_side_bar(node)
    if side_bar is not None:
        side, bar_w, bar_color = side_bar
        bw = min(bar_w, 12.0)
        if side == 'right':
            bx, by, bw_px, bh_px = x + w - bw, y + 6, bw, h - 12
        elif side == 'left':
            bx, by, bw_px, bh_px = x, y + 6, bw, h - 12
        elif side == 'top':
            bx, by, bw_px, bh_px = x + 6, y, w - 12, bw
        else:
            bx, by, bw_px, bh_px = x + 6, y + h - bw, w - 12, bw
        if bw_px > 0 and bh_px > 0:
            bar = shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                   _px_to_emu(bx), _px_to_emu(by),
                                   _px_to_emu(bw_px), _px_to_emu(bh_px))
            _set_shape_fill(bar, bar_color)
            _no_line(bar)
    pad = _parse_px(node.style.get('padding', ''), 10.0) or 10.0
    pad = min(max(pad, 0.0), 60.0)
    if h < 64.0:
        pad = 0.0  # small labels/badges: padding would swallow the whole rect
    abs_kids = [c for c in node.children
                if isinstance(c, Node) and not _is_hidden(c)
                and c.tag not in _SKIP_TAGS
                and _abs_rect(c, w, h) is not None]
    flow_kids = [c for c in node.children
                 if not (isinstance(c, Node) and (c.tag in _SKIP_TAGS or _is_hidden(c)
                                                 or _abs_rect(c, w, h) is not None))]
    for kid in abs_kids:
        if _is_veil(kid, w, h):
            # Nested gradient overlay (image panels): darken the panel.
            overlay = shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                       _px_to_emu(x), _px_to_emu(y),
                                       _px_to_emu(w), _px_to_emu(h))
            _set_shape_fill(overlay, RGBColor(0x0B, 0x1F, 0x33), alpha_pct=35)
            _no_line(overlay)
            continue
        sub = _anchored_rect(kid, w, h, ctx) or _abs_rect(kid, w, h)
        _render_abs_node(slide, shapes, kid, ctx,
                         (x + sub[0], y + sub[1], sub[2], sub[3]), depth + 1)
    # Flex/grid rows keep their side-by-side columns inside the rect.
    grid_handled = False
    if _grid_columns(node) >= 2:
        kids = [c for c in flow_kids
                if isinstance(c, Node) and not _is_hidden(c) and c.tag not in _SKIP_TAGS]
        if len(kids) >= 2:
            pairs = []
            for kid in kids:
                sub = _node_to_blocks(kid, ctx, rtl)
                if sub:
                    pairs.append((kid, sub))
            if len(pairs) >= 2:
                pad = _parse_px(node.style.get('padding', ''), 0.0) or 0.0
                widths = [_col_spec(k) for k, _s in pairs]
                ColumnsBlock([s for _k, s in pairs], rtl=rtl,
                             widths=widths).render(
                    slide, shapes, x + pad, y + pad, w - pad * 2, ctx, h - pad * 2)
                grid_handled = True
    if grid_handled:
        return h
    flow_blocks = _flow_blocks(flow_kids, ctx, rtl, inherit_from=node)
    if flow_blocks:
        halign, valign = _container_gravity(node)
        _render_flow(slide, shapes, flow_blocks, ctx, x + pad, y + pad,
                     w - pad * 2, h - pad * 2, halign=halign, valign=valign)
    return h


# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------

def _prepare_slide_html(html, tenant_id):
    try:
        html = resolve_logo_in_html(html, tenant_id)
    except Exception:
        pass
    try:
        html = _resolve_project_file_urls(html, tenant_id)
    except Exception:
        pass
    try:
        html = _resolve_asset_urls(html)
    except Exception:
        pass
    try:
        from slide_engine import _drop_unresolved_image_placeholders
        html = _drop_unresolved_image_placeholders(html)
    except Exception:
        html = re.sub(r'<img[^>]*##[^>]*>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'##[A-Z0-9_]+##', '', html)
    html = sanitize_slide_html_for_export(html)
    return html


def _slide_counter_text(slide, index, total):
    for key in ('counter', 'slideCounter'):
        if slide.get(key):
            return str(slide.get(key))
    return f'{index + 1:02d} — {total:02d}'


def _verify_pptx_slide_count(output_path, expected):
    """Refuse to hand back a PPTX with fewer slides than the deck holds.

    Same rule as the PDF side: a short file is a failed export, not a smaller
    export. The file is reopened and counted so a silently dropped slide (or
    a worker killed mid-save leaving a truncated zip) surfaces as an error
    instead of a finished download.
    """
    try:
        written = len(Presentation(output_path).slides)
    except Exception as exc:
        raise RuntimeError(f'تعذر التحقق من ملف PPTX: {exc}')
    print(f"[PPTX] slides={written} expected={expected}")
    try:
        print(f"[PPTX] file={os.path.basename(str(output_path))}")
    except UnicodeEncodeError:
        print(os.path.basename(str(output_path)).encode('ascii', errors='backslashreplace').decode('ascii'))
    if written < expected:
        raise RuntimeError(
            f'تعذر تصدير العرض كاملاً: الملف يحتوي {written} شريحة مقابل {expected} شريحة.')
    return written


def generate_pptx(slides_data, project_name, branding=None, output_dir=None,
                  tenant_id=None):
    """
    Generate an editable PPTX from slide HTML.

    Every slide becomes native PowerPoint objects (text boxes, tables,
    pictures, shapes) following the slide's own design: background, header,
    footer, headings, lists, tables and images — all editable in PowerPoint.

    Args:
        slides_data: list of slide dicts with 'html', 'title', 'type' keys
        project_name: name for the output file
        branding: tenant branding dict
        output_dir: directory to save the PPTX
        tenant_id: tenant identifier (falls back to branding.get('tenant_id'))

    Returns:
        str: path to the generated PPTX file
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'outputs')
    os.makedirs(output_dir, exist_ok=True)

    branding = dict(branding or {})
    if not tenant_id:
        tenant_id = branding.get('tenant_id')

    slide_ratio = branding.get('slide_ratio', '16:9')
    if slide_ratio == '4:3':
        global SLIDE_W_PX, SLIDE_H_PX
        SLIDE_W_PX, SLIDE_H_PX = 1280, 960
        slide_w, slide_h = Inches(13.333), Inches(10)
    else:
        SLIDE_W_PX, SLIDE_H_PX = 1280, 720
        slide_w, slide_h = Inches(13.333), Inches(7.5)

    font_name = _resolve_font_name(branding)
    try:
        primary = _hex_to_rgb(normalize_hex_color(branding.get('primary_color'), '#0b1f33'))
    except Exception:
        primary = RGBColor(0x0B, 0x1F, 0x33)

    ctx = Ctx(branding, tenant_id, font_name, primary)
    project_label = _strip_icons(str(project_name or '')).strip()

    prs = Presentation()
    prs.slide_width = slide_w
    prs.slide_height = slide_h
    blank = prs.slide_layouts[6]
    total = len(slides_data or [])
    if not total:
        raise ValueError('slides_data is required for PPTX export')
    print(f"[PPTX] Building {total} editable slides...")

    for index, raw in enumerate(slides_data or []):
        slide_data = dict(raw) if isinstance(raw, dict) else {'html': str(raw or '')}
        html = _prepare_slide_html(slide_data.get('html', ''), tenant_id)
        title = _strip_icons(str(slide_data.get('title') or '')).strip()
        slide_type = str(slide_data.get('type') or '').strip().lower()

        slide = prs.slides.add_slide(blank)
        shapes = slide.shapes
        if (index + 1) % 10 == 0 or (index + 1) == total:
            print(f"[PPTX] slide {index + 1}/{total}...")

        root = _find_slide_root(_parse_html(html))
        bg = _parse_color(root.style.get('background-color', '')
                          or root.style.get('background', ''))
        # background shorthand may include url(...) — then there is no plain color
        if bg is None:
            plain = str(root.style.get('background', '') or root.style.get('background-color', ''))
            if plain and 'url(' not in plain.lower():
                bg = _parse_color(plain)
        _set_slide_background(slide, bg or RGBColor(0xFF, 0xFF, 0xFF))

        header, footer, body_kids = _extract_chrome(root)

        # ---- cover / closing / section divider: render the slide's own
        # designed body (absolute positions honoured), not a rebuilt template
        if slide_type in ('cover', 'closing', 'section_divider'):
            _render_designed_slide(slide, shapes, root, body_kids, title,
                                   project_label, ctx, branding, primary,
                                   slide_type=slide_type)
            continue

        # ---- regular content slide
        header_title = _header_title(header) or title
        _render_header_band(slide, shapes, header, header_title, ctx, primary)
        counter = _slide_counter_text(slide_data, index, total)
        _render_footer_band(slide, shapes, footer, project_label, counter, ctx,
                            bottom_px=SLIDE_H_PX)

        content_top = 80.0
        content_bottom = SLIDE_H_PX - 50.0
        content_left = 36.0
        content_w = SLIDE_W_PX - 72.0

        # Absolutely-positioned overlays (badges, logo strips) keep their rects.
        # Positions are slide-relative, so anchor against the full slide.
        for kid in body_kids:
            if isinstance(kid, Node) and not _is_hidden(kid):
                rect = _anchored_rect(kid, SLIDE_W_PX, SLIDE_H_PX, ctx)
                if rect is not None and not _is_veil(kid):
                    _render_abs_node(slide, shapes, kid, ctx, rect)
        blocks = _flow_blocks([k for k in body_kids
                               if not (isinstance(k, Node)
                                       and _abs_rect(k, SLIDE_W_PX, SLIDE_H_PX) is not None)],
                              ctx)

        if not blocks and title and not header_title:
            ghost = Node('h2', {})
            ghost.children = [title]
            blocks = [TextBlock(ghost, 24.0, bold=True, color=primary)]

        _render_flow(slide, shapes, blocks, ctx, content_left, content_top,
                     content_w, content_bottom - content_top)

    safe_name = ''.join(c for c in str(project_name or '')
                        if c.isalnum() or c in '-_ ')[:50].strip() or 'presentation'
    output_path = os.path.join(output_dir, f"{safe_name}_{int(time.time())}.pptx")
    prs.save(output_path)
    _verify_pptx_slide_count(output_path, total)
    return output_path


def _add_textbox(slide, left, top, width, height, text, font_size=18, color=None,
                 bold=False, alignment=PP_ALIGN.RIGHT, font_name='IBM Plex Sans Arabic'):
    """Add a text box to a slide (kept for backward compatibility)."""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    try:
        tf.word_wrap = True
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.text = _strip_icons(text)
    try:
        p.font.size = Pt(font_size)
        p.font.bold = bold
        p.font.name = font_name
        p.alignment = alignment
    except Exception:
        pass
    if color:
        try:
            p.font.color.rgb = color
        except Exception:
            pass
    return txBox
