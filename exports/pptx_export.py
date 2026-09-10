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

from design_templates import normalize_hex_color, sanitize_slide_html_for_export
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
    __slots__ = ('tag', 'attrs', 'style', 'children', 'text')

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.style = _parse_style(self.attrs.get('style', ''))
        self.children = []
        self.text = ''

    def classes(self):
        return set(str(self.attrs.get('class', '')).split())

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
            resp = requests.get(src, timeout=15)
            if resp.ok and resp.content:
                ctype = str(resp.headers.get('Content-Type', '')).lower()
                if 'image' in ctype or src.lower().split('?')[0].endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
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

    base = {'bold': False, 'italic': False, 'size_px': None, 'color': None, 'link': None}
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
                   font_name='Arial', ordered=False):
    if first and len(text_frame.paragraphs) == 1 and not text_frame.paragraphs[0].runs:
        para = text_frame.paragraphs[0]
    else:
        para = text_frame.add_paragraph()
    para.alignment = align
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
    return _parse_color(bg)


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
                 space_after=6.0, bullet=False, level=0, anchor_top=False):
        self.node = node
        self.size_px = size_px
        self.bold = bold
        self.color = color
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
                               font_name=ctx.font_name)
                first = False
        _no_line(box)
        return height_px


class ListBlock(Block):
    def __init__(self, node, size_px=14.0, color=None):
        self.node = node
        self.size_px = size_px
        self.color = color

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
                sub = ListBlock(item, self.size_px, self.color)
                for sub_item in sub._items():
                    runs = _clean_runs(_inline_runs(sub_item))
                    if runs:
                        _add_paragraph(box.text_frame, runs, align=align, first=first,
                                       bullet=not ordered, level=1,
                                       default_size_px=self.size_px,
                                       default_color=self.color,
                                       font_name=ctx.font_name)
                        first = False
                continue
            runs = _clean_runs(_inline_runs(item))
            if not runs:
                continue
            _add_paragraph(box.text_frame, runs, align=align, first=first,
                           bullet=True, level=0, ordered=ordered,
                           default_size_px=self.size_px,
                           default_color=self.color, font_name=ctx.font_name)
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
    def __init__(self, node):
        self.node = node

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
                node = grid[r][c]
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

    def __init__(self, node, inner):
        self.node = node
        self.inner = inner

    def estimate(self, width_px, ctx):
        pad = 24.0
        total = pad
        for b in self.inner:
            total += b.estimate(width_px - pad * 2, ctx) + 6.0
        return total + pad

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        height_px = min(self.estimate(width_px, ctx), max(40.0, max_h_px))
        fill = _node_bg(self.node)
        shape = shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 _px_to_emu(left_px), _px_to_emu(top_px),
                                 _px_to_emu(width_px), _px_to_emu(height_px))
        if fill is not None:
            _set_shape_fill(shape, fill)
        else:
            try:
                shape.fill.background()
            except Exception:
                pass
        _no_line(shape)
        try:
            shape.text_frame.word_wrap = True
        except Exception:
            pass
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


class ColumnsBlock(Block):
    def __init__(self, columns):
        # columns: list of list[Block]
        self.columns = columns

    def estimate(self, width_px, ctx):
        n = max(1, len(self.columns))
        gap = 20.0
        cw = (width_px - gap * (n - 1)) / n
        return max((sum(b.estimate(cw, ctx) + 6.0 for b in col) for col in self.columns),
                   default=0.0)

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        n = max(1, len(self.columns))
        gap = 20.0
        cw = (width_px - gap * (n - 1)) / n
        heights = []
        for i, col in enumerate(self.columns):
            y = top_px
            for b in col:
                used = b.render(slide, shapes, left_px + i * (cw + gap), y, cw,
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
    def __init__(self, color=None):
        self.color = color

    def estimate(self, width_px, ctx):
        return 10.0

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        bar = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(left_px),
                               _px_to_emu(top_px + 3), _px_to_emu(width_px),
                               _px_to_emu(3))
        _set_shape_fill(bar, self.color or RGBColor(0xCB, 0xD5, 0xE1))
        _no_line(bar)
        return 10.0


# --------------------------------------------------------------------------
# HTML -> blocks
# --------------------------------------------------------------------------

_HEADING_SIZES = {'h1': 26.0, 'h2': 23.0, 'h3': 19.0, 'h4': 16.0}


def _node_to_blocks(node, ctx):
    """Convert a flow node into a list of Blocks."""
    if not isinstance(node, Node) or _is_hidden(node):
        return []
    if node.tag in _SKIP_TAGS:
        return []
    if _is_header_node(node) or _is_footer_node(node):
        return []

    tag = node.tag

    if tag in ('h1', 'h2', 'h3', 'h4'):
        size = _parse_font_size(node.style.get('font-size'), _HEADING_SIZES[tag])
        color = _parse_color(node.style.get('color'))
        bold = True
        if not node.get_text().strip():
            return []
        return [TextBlock(node, size, bold=bold, color=color, space_after=8.0)]

    if tag == 'p':
        if not node.get_text().strip():
            return []
        size = _parse_font_size(node.style.get('font-size'), 13.0)
        color = _parse_color(node.style.get('color'))
        return [TextBlock(node, size, color=color, space_after=6.0)]

    if tag in ('ul', 'ol'):
        if not node.get_text().strip():
            return []
        size = _parse_font_size(node.style.get('font-size'), 13.0)
        color = _parse_color(node.style.get('color'))
        return [ListBlock(node, size, color)]

    if tag == 'li':
        if not node.get_text().strip():
            return []
        return [ListBlock(Node('ul', {}), 13.0, None)]

    if tag == 'table':
        block = TableBlock(node)
        grid, _ = block._grid()
        if not grid:
            return []
        return [block]

    if tag == 'img':
        src = node.attrs.get('src', '')
        if not src or '##' in src:
            return []
        h = _parse_px(node.style.get('height'), None)
        return [ImageBlock(src, node.attrs.get('alt', ''), height_px=h)]

    if tag == 'hr':
        return [RuleBlock(_parse_color(node.style.get('background-color'))
                          or _parse_color(node.style.get('color')))]

    if tag == 'svg':
        texts = []
        for t in node.find_all({'text', 'tspan'}):
            val = _strip_icons(t.get_text()).strip()
            if val:
                texts.append(val)
        if not texts:
            return []
        ghost = Node('div', {})
        ghost.children = list(texts)
        size = 12.0
        blocks = []
        for val in texts[:12]:
            n = Node('p', {})
            n.children = [val]
            blocks.append(TextBlock(n, size, space_after=3.0))
        return blocks

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
        return [ImageBlock(bg_url)]

    children_blocks = []
    for child in node.children:
        if isinstance(child, Node):
            children_blocks.extend(_node_to_blocks(child, ctx))
        elif isinstance(child, str) and child.strip():
            ghost = Node('span', {})
            ghost.children = [child]
            size = _parse_font_size(node.style.get('font-size'), 13.0)
            color = _parse_color(node.style.get('color'))
            children_blocks.append(TextBlock(ghost, size, color=color))

    if not children_blocks:
        return []

    # Two-column grids/flex rows become side-by-side columns
    if tag == 'div' and _grid_columns(node) >= 2:
        kids = [c for c in node.children
                if isinstance(c, Node) and not _is_hidden(c) and c.tag not in _SKIP_TAGS]
        if len(kids) >= 2:
            cols = []
            for kid in kids:
                sub = _node_to_blocks(kid, ctx)
                if sub:
                    cols.append(sub)
            if len(cols) >= 2:
                return [ColumnsBlock(cols)]
        # fall through to stacked rendering

    # Cards: background color / border / radius -> grouped shape
    fill = _node_bg(node)
    has_border = 'border' in node.style or 'border-top' in node.style
    has_radius = 'radius' in ''.join(node.style.keys())
    if tag == 'div' and (fill is not None or (has_border and has_radius)) and children_blocks:
        # Only treat as a card when it actually wraps multiple/textual content
        # and is not the full-bleed slide root handled elsewhere.
        return [CardBlock(node, children_blocks)]

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
    return _strip_icons(header.get_text()).strip()[:120]


def _header_logos(header):
    if header is None:
        return []
    return [img.attrs.get('src', '') for img in header.find_all({'img'})
            if img.attrs.get('src') and '##' not in img.attrs.get('src', '')][:3]


def _render_header_band(slide, shapes, header, title, ctx, primary, top_px=0.0):
    height_px = 64.0
    band = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(0), _px_to_emu(top_px),
                            _px_to_emu(SLIDE_W_PX), _px_to_emu(height_px))
    _set_shape_fill(band, RGBColor(0xFF, 0xFF, 0xFF))
    _no_line(band)
    # Title (right side, RTL)
    text = _strip_icons(title).strip()
    if text:
        box = shapes.add_textbox(_px_to_emu(150), _px_to_emu(top_px + 10),
                                 _px_to_emu(SLIDE_W_PX - 200), _px_to_emu(46))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        ghost = Node('span', {})
        ghost.children = [text]
        _add_paragraph(box.text_frame, [(text, {'bold': True, 'italic': False,
                                                'size_px': None, 'color': None,
                                                'link': None})],
                       align=PP_ALIGN.RIGHT, first=True, default_size_px=20.0,
                       default_color=primary, default_bold=True,
                       font_name=ctx.font_name)
        _no_line(box)
    # Logos (left side)
    x = 28.0
    for src in _header_logos(header):
        data = _image_bytes(src, ctx.tenant_id)
        if not data:
            continue
        iw, ih = _image_size(data)
        h = 40.0
        w = h * iw / ih if iw and ih else 90.0
        try:
            shapes.add_picture(BytesIO(data), _px_to_emu(x), _px_to_emu(top_px + 12),
                               _px_to_emu(w), _px_to_emu(h))
        except Exception:
            continue
        x += w + 14.0
        if x > 300:
            break
    return height_px


def _render_footer_band(slide, shapes, footer, project_name, counter, ctx, bottom_px=720.0):
    height_px = 40.0
    top_px = bottom_px - height_px
    band = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(0), _px_to_emu(top_px),
                            _px_to_emu(SLIDE_W_PX), _px_to_emu(height_px))
    _set_shape_fill(band, RGBColor(0x1F, 0x2A, 0x37))
    _no_line(band)
    # Project name (right)
    if project_name:
        box = shapes.add_textbox(_px_to_emu(620), _px_to_emu(top_px + 6),
                                 _px_to_emu(SLIDE_W_PX - 660), _px_to_emu(28))
        try:
            box.text_frame.word_wrap = True
        except Exception:
            pass
        _add_paragraph(box.text_frame, [(project_name, {'bold': False, 'italic': False,
                                                        'size_px': None, 'color': None,
                                                        'link': None})],
                       align=PP_ALIGN.RIGHT, first=True, default_size_px=12.0,
                       default_color=RGBColor(0xFF, 0xFF, 0xFF),
                       font_name=ctx.font_name)
        _no_line(box)
    # Counter (left, LTR)
    if counter:
        box = shapes.add_textbox(_px_to_emu(40), _px_to_emu(top_px + 6),
                                 _px_to_emu(220), _px_to_emu(28))
        try:
            box.text_frame.word_wrap = True
        except Exception:
            pass
        _add_paragraph(box.text_frame, [(counter, {'bold': False, 'italic': False,
                                                   'size_px': None, 'color': None,
                                                   'link': None})],
                       align=PP_ALIGN.LEFT, first=True, default_size_px=11.0,
                       default_color=RGBColor(0xFF, 0xFF, 0xFF),
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


def _render_cover_slide(slide, shapes, root, body_blocks, title, subtitle, ctx,
                        primary, logos, veil=True):
    bg_url = _slide_bg_image(root)
    if bg_url:
        data = _image_bytes(bg_url, ctx.tenant_id)
        if data:
            try:
                shapes.add_picture(BytesIO(data), _px_to_emu(0), _px_to_emu(0),
                                   _px_to_emu(SLIDE_W_PX), _px_to_emu(SLIDE_H_PX))
            except Exception:
                pass
            if veil:
                overlay = shapes.add_shape(MSO_SHAPE.RECTANGLE, _px_to_emu(0),
                                           _px_to_emu(0), _px_to_emu(SLIDE_W_PX),
                                           _px_to_emu(SLIDE_H_PX))
                _set_shape_fill(overlay, RGBColor(0x0B, 0x1F, 0x33), alpha_pct=45)
                _no_line(overlay)
    # Logos row
    y = 150.0
    picts = []
    for src in logos[:2]:
        data = _image_bytes(src, ctx.tenant_id)
        if data:
            picts.append(data)
    if picts:
        widths = []
        for data in picts:
            iw, ih = _image_size(data)
            widths.append(110.0 * iw / ih if iw and ih else 110.0)
        total_w = sum(widths) + 20.0 * (len(widths) - 1)
        x = (SLIDE_W_PX - total_w) / 2
        for data, w in zip(picts, widths):
            try:
                shapes.add_picture(BytesIO(data), _px_to_emu(x), _px_to_emu(y),
                                   _px_to_emu(w), _px_to_emu(80))
            except Exception:
                pass
            x += w + 20.0
        y += 104.0
    # Title
    if title:
        box = shapes.add_textbox(_px_to_emu(120), _px_to_emu(y),
                                 _px_to_emu(SLIDE_W_PX - 240), _px_to_emu(130))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        _add_paragraph(box.text_frame, [(title, {'bold': True, 'italic': False,
                                                 'size_px': None, 'color': None,
                                                 'link': None})],
                       align=PP_ALIGN.CENTER, first=True, default_size_px=40.0,
                       default_color=RGBColor(0xFF, 0xFF, 0xFF),
                       default_bold=True, font_name=ctx.font_name)
        _no_line(box)
        y += 140.0
    if subtitle:
        box = shapes.add_textbox(_px_to_emu(180), _px_to_emu(y),
                                 _px_to_emu(SLIDE_W_PX - 360), _px_to_emu(90))
        try:
            box.text_frame.word_wrap = True
            box.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
        lines = [ln.strip() for ln in str(subtitle).split('\n') if ln.strip()]
        for i, line in enumerate(lines[:6]):
            _add_paragraph(box.text_frame, [(line, {'bold': False, 'italic': False,
                                                    'size_px': None, 'color': None,
                                                    'link': None})],
                           align=PP_ALIGN.CENTER, first=(i == 0), default_size_px=18.0,
                           default_color=RGBColor(0xFF, 0xFF, 0xFF),
                           font_name=ctx.font_name)
        _no_line(box)


def _render_flow(slide, shapes, blocks, ctx, left_px, top_px, width_px, max_h_px):
    y = top_px
    remaining = max_h_px
    for block in blocks:
        if remaining <= 24.0:
            break
        used = block.render(slide, shapes, left_px, y, width_px, ctx, remaining)
        y += used + 8.0
        remaining = max_h_px - (y - top_px)
    return y - top_px


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


def generate_pptx(slides_data, project_name, branding=None, output_dir=None, tenant_id=None):
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

    for index, raw in enumerate(slides_data or []):
        slide_data = dict(raw) if isinstance(raw, dict) else {'html': str(raw or '')}
        html = _prepare_slide_html(slide_data.get('html', ''), tenant_id)
        title = _strip_icons(str(slide_data.get('title') or '')).strip()
        slide_type = str(slide_data.get('type') or '').strip().lower()

        slide = prs.slides.add_slide(blank)
        shapes = slide.shapes

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

        # ---- cover / closing / section divider: full-bleed centered layout
        if slide_type in ('cover', 'closing', 'section_divider'):
            logos = _header_logos(header)
            # also pick logos that sit in the body top row
            for img in root.find_all({'img'}):
                src = img.attrs.get('src', '')
                if src and '##' not in src and src not in logos and len(logos) < 2:
                    logos.append(src)
            subtitle = ''
            if slide_type == 'closing':
                contact_bits = []
                for leaf in root.find_all({'h1', 'h2', 'h3', 'h4', 'p', 'li', 'div', 'span'}):
                    if leaf.tag in ('div', 'span') and any(
                            isinstance(c, Node) for c in leaf.children):
                        continue  # containers handled via their own leaf children
                    if _is_header_node(leaf) or _is_footer_node(leaf):
                        continue
                    text = _strip_icons(leaf.get_text()).strip()
                    if text and text != title and text not in contact_bits \
                            and len(contact_bits) < 5:
                        contact_bits.append(text)
                if not contact_bits:
                    for kid in body_kids:
                        text = _strip_icons(kid.get_text() if isinstance(kid, Node)
                                            else str(kid)).strip()
                        if text and text != title and len(contact_bits) < 4:
                            contact_bits.append(text)
                subtitle = '\n'.join(contact_bits)[:600]
            elif not title:
                title = project_label
                subtitle = ''
            _render_cover_slide(slide, shapes, root, [], title, subtitle, ctx,
                                primary, logos, veil=True)
            if slide_type == 'section_divider':
                bar = shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                       _px_to_emu((SLIDE_W_PX - 220) / 2),
                                       _px_to_emu(430), _px_to_emu(220), _px_to_emu(6))
                try:
                    accent = _hex_to_rgb(normalize_hex_color(
                        branding.get('accent_color'), '#d4af37'))
                except Exception:
                    accent = RGBColor(0xD4, 0xAF, 0x37)
                _set_shape_fill(bar, accent)
                _no_line(bar)
            continue

        # ---- regular content slide
        header_title = _header_title(header) or title
        _render_header_band(slide, shapes, header, header_title, ctx, primary)
        counter = _slide_counter_text(slide_data, index, total)
        _render_footer_band(slide, shapes, footer, project_label, counter, ctx,
                            bottom_px=SLIDE_H_PX)

        content_top = 84.0
        content_bottom = SLIDE_H_PX - 58.0
        content_left = 48.0
        content_w = SLIDE_W_PX - 96.0

        blocks = []
        for kid in body_kids:
            if isinstance(kid, Node):
                blocks.extend(_node_to_blocks(kid, ctx))
            elif isinstance(kid, str) and kid.strip():
                ghost = Node('p', {})
                ghost.children = [kid]
                blocks.extend(_node_to_blocks(ghost, ctx))

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
