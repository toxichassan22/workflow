

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
                          or _parse_color(node.style.get('color')),
                          align=_css_rule_align(node))]

    if tag in ('div', 'span') and not node.get_text().strip() and not node.find_all({'img', 'table', 'svg', 'ul', 'ol'}):
        # Thin decorative bar (gold rules under titles etc.) or dot.
        w = _parse_px(node.style.get('width'), None)
        h = _parse_px(node.style.get('height'), None)
        fill = _node_bg(node)
        rule_align = _css_rule_align(node)
        if fill is not None and w is not None and h is not None:
            if w <= 18 and h <= 18:
                return [RuleBlock(fill, width_px=w, height_px=h, align=rule_align)]
            if w >= 20 and h <= 12:
                return [RuleBlock(fill, width_px=w, height_px=h, align=rule_align)]
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


def _css_auto_margin(node, side):
    """Whether CSS margin on `left`/`right` is auto (shorthand-aware)."""
    if str(node.style.get(f'margin-{side}', '')).strip().lower() == 'auto':
        return True
    margin = str(node.style.get('margin', '')).strip().lower()
    if 'auto' not in margin:
        return False
    parts = [p for p in re.split(r'\s+', margin) if p]
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] == 'auto'
    if len(parts) == 2:
        return parts[1] == 'auto'
    if len(parts) == 3:
        return parts[1] == 'auto'
    return parts[3 if side == 'left' else 1] == 'auto'


def _css_rule_align(node):
    """RuleBlock align from margin auto: left:auto -> end, right:auto -> start."""
    if _css_auto_margin(node, 'left'):
        return 'end'
    if _css_auto_margin(node, 'right'):
        return 'start'
    return None


def _is_full_bleed_bg_layer(node, cw=1280.0, ch=720.0):
    """A child that only carries a full-slide background image (no content)."""
    if not isinstance(node, Node) or _is_hidden(node):
        return False
    if node.tag in _SKIP_TAGS:
        return False
    if (node.get_text() or '').strip():
        return False
    if node.find_all({'img', 'table', 'svg', 'ul', 'ol', 'p', 'h1', 'h2', 'h3', 'h4'}):
        return False
    for child in node.children:
        if isinstance(child, Node) and not _is_hidden(child) and (child.get_text() or '').strip():
            return False
    url = _extract_bg_url(node.style.get('background-image', '')
                         or node.style.get('background', ''))
    if not url:
        return False
    rect = _abs_rect(node, cw, ch)
    if rect is None:
        return False
    _x, _y, w, h = rect
    return w >= cw * 0.9 and h >= ch * 0.9


def _anchored_rect(node, cw, ch, ctx):
    """Absolute rect with shrink-to-fit fallback for open/bottom-anchored boxes.

    CSS absolute boxes without explicit height size to their content; stretching
    them to the slide edge misplaces bottom-anchored strips and stretches side
    rules. Estimate the content height when the markup leaves it open. Boxes
    with only left/right (no width) also shrink-to-fit so a bottom counter
    does not become a full-width strip, and bottom anchoring still applies
    after that shrink (project name at bottom-right, counter at bottom-left).
    """
    rect = _abs_rect(node, cw, ch)
    if rect is None:
        return None
    x, y, w, h = rect
    width_given = _parse_len(node.style.get('width'), cw)
    if width_given is None:
        left = _parse_len(node.style.get('left'), cw)
        right = _parse_len(node.style.get('right'), cw)
        if left is not None and right is None:
            est_w = _estimate_node_width(node, ctx, max(20.0, cw - left))
            w = min(max(est_w, 20.0), max(20.0, cw - left))
            x = left
        elif left is None and right is not None:
            # Right-anchored open box (flex rows, labels): shrink-to-fit and
            # hug the right edge like the browser instead of filling the row.
            est_w = _estimate_node_width(node, ctx, max(20.0, cw - right))
            w = min(max(est_w, 20.0), max(20.0, cw - right))
            x = cw - right - w
    explicit_h = _parse_len(node.style.get('height'), ch)
    top = _parse_len(node.style.get('top'), ch)
    if top is None and node.style.get('inset', '').strip():
        it, _ir, _ib, _il = _parse_insets(node.style.get('inset'), cw, ch)
        top = it
    bottom = _parse_len(node.style.get('bottom'), ch)
    if explicit_h is not None:
        if top is None and bottom is not None:
            return (x, ch - bottom - h, w, h)
        if top is not None and bottom is None:
            return (x, top, w, h)
        if top is not None and bottom is not None:
            return (x, top, w, max(h, ch - top - bottom) if h < (ch - top - bottom) else h)
        return (x, y, w, h)
    if top is not None and bottom is None:
        # Open-ended: shrink to content instead of filling to the slide edge.
        est = _estimate_node_height(node, ctx, w)
        return (x, y, w, min(est, ch - y))
    if top is None and bottom is not None:
        est = _estimate_node_height(node, ctx, w)
        est = min(est, max(20.0, ch - bottom))
        return (x, ch - bottom - est, w, est)
    return (x, y, w, h)


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

def _strip_hidden_watermark_overlays(html):
    """Drop hidden watermark layers so they stay invisible in every export.

    A hidden layer keeps its geometry in the saved slide for a later show;
    the export must not draw it. Visible layers pass through untouched with
    their source, position, size and opacity intact.
    """
    if not html or 'watermark' not in str(html).lower():
        return html
    source = str(html)

    def _drop_if_hidden(match):
        overlay = match.group(0)
        tag_end = overlay.find('>')
        tag = overlay[:tag_end + 1] if tag_end != -1 else overlay
        hidden_attr = re.search(
            r'data-watermark-visible\s*=\s*["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        if hidden_attr and hidden_attr.group(1).strip().lower() == 'false':
            return ''
        if re.search(r'display\s*:\s*none', tag, flags=re.IGNORECASE):
            return ''
        return overlay

    source = re.sub(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>[\s\S]*?</div\s*>',
        _drop_if_hidden, source, flags=re.IGNORECASE,
    )
    return re.sub(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>[\s\S]*?</div\s*>',
        _drop_if_hidden, source, flags=re.IGNORECASE,
    )


def _prepare_slide_html(html, tenant_id):
    try:
        html = resolve_logo_in_html(html, tenant_id)
    except Exception:
        pass
    html = _strip_hidden_watermark_overlays(html)
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
