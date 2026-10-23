

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
                 oval=False, align=None):
        self.color = color
        self.width_px = width_px
        self.height_px = height_px
        self.centered = centered
        self.oval = oval
        # align overrides centered: 'start' | 'center' | 'end'
        self.align = align

    def estimate(self, width_px, ctx):
        return self.height_px + 7.0

    def render(self, slide, shapes, left_px, top_px, width_px, ctx, max_h_px):
        w = min(self.width_px or width_px, width_px)
        mode = self.align or ('center' if self.centered else 'start')
        if mode == 'center':
            x = left_px + (width_px - w) / 2
        elif mode == 'end':
            x = left_px + width_px - w
        else:
            x = left_px
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
