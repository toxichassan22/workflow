"""Paint measured HTML tables as native PowerPoint tables."""

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt


_VERTICAL = {
    'top': MSO_ANCHOR.TOP,
    'middle': MSO_ANCHOR.MIDDLE,
    'bottom': MSO_ANCHOR.BOTTOM,
    'baseline': MSO_ANCHOR.BOTTOM,
}


def _column_boundaries(rows):
    xs = []
    for row in rows:
        for cell in row.get('cells') or []:
            xs.append(round(float(cell['x']), 1))
            xs.append(round(float(cell['x']) + float(cell['w']), 1))
    xs = sorted(set(xs))
    merged = []
    for value in xs:
        if not merged or value - merged[-1] > 1.0:
            merged.append(value)
    return merged


def _column_index(boundaries, x):
    if not boundaries:
        return 0
    best = 0
    best_distance = None
    for index, value in enumerate(boundaries):
        distance = abs(value - float(x))
        if best_distance is None or distance < best_distance:
            best, best_distance = index, distance
    return best


def _set_cell_border(cell, side, color, width_px, style='solid'):
    rgb, alpha = _css_color(color)
    if rgb is None or not width_px:
        return
    edge = {'top': 'a:lnT', 'bottom': 'a:lnB', 'left': 'a:lnL', 'right': 'a:lnR'}.get(side)
    if not edge:
        return
    try:
        tc_pr = cell._tc.get_or_add_tcPr()
        tag = qn(edge)
        line = tc_pr.find(tag)
        if line is None:
            line = tc_pr.makeelement(tag, {})
            # schema order: lnL, lnR, lnT, lnB before fill
            tc_pr.insert(0, line)
        line.set('w', str(int(max(0.25, float(width_px) * 0.75) * 12700)))
        line.set('cap', 'flat')
        line.set('cmpd', 'sng')
        line.set('algn', 'ctr')
        for child in list(line):
            line.remove(child)
        fill = line.makeelement(qn('a:solidFill'), {})
        clr = fill.makeelement(qn('a:srgbClr'), {'val': str(rgb)})
        if alpha:
            clr.append(clr.makeelement(
                qn('a:alpha'), {'val': str(int((100 - alpha) * 1000))}))
        fill.append(clr)
        line.append(fill)
        dash = 'solid'
        raw = str(style or '').lower()
        if 'dash' in raw:
            dash = 'dash'
        elif 'dot' in raw:
            dash = 'sysDot'
        line.append(line.makeelement(qn('a:prstDash'), {'val': dash}))
    except Exception:
        pass


def _fill_cell(cell, fill, opacity=1.0):
    rgb, alpha = _css_color(fill)
    if rgb is None:
        try:
            cell.fill.background()
        except Exception:
            pass
        return
    try:
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb
        combined = _combined_alpha(alpha, opacity)
        if combined:
            solid = cell.fill._xPr.find(qn('a:solidFill'))
            if solid is not None:
                clr = solid.find(qn('a:srgbClr'))
                if clr is not None:
                    clr.append(clr.makeelement(
                        qn('a:alpha'), {'val': str(int((100 - combined) * 1000))}))
    except Exception:
        pass


def _cell_paragraphs(runs):
    paragraphs = [[]]
    for run in runs or []:
        text = str(run.get('text') or '')
        pieces = text.split('\n')
        for index, piece in enumerate(pieces):
            if index:
                paragraphs.append([])
            if piece:
                paragraphs[-1].append({'text': piece, 'style': run.get('style') or {}})
    return [p for p in paragraphs if p]


def _write_cell(cell, payload, ctx):
    cell_info = payload['cell']
    if payload.get('rich'):
        # Rich cell (pills / chips): its text is painted from the measured line
        # boxes after the table, so the native cell must carry no text at all.
        try:
            cell.text_frame.clear()
        except Exception:
            pass
        return
    style = cell_info.get('style') or {}
    rtl = str(style.get('direction') or 'rtl').lower() != 'ltr'
    frame = cell.text_frame
    try:
        frame.word_wrap = True
        frame.auto_size = None
    except Exception:
        pass
    try:
        cell.vertical_anchor = _VERTICAL.get(
            str(cell_info.get('vertical') or 'middle').lower(), MSO_ANCHOR.MIDDLE)
    except Exception:
        pass
    padding = cell_info.get('padding') or [0, 0, 0, 0]
    try:
        cell.margin_top = _px_to_emu(padding[0])
        cell.margin_right = _px_to_emu(padding[1])
        cell.margin_bottom = _px_to_emu(padding[2])
        cell.margin_left = _px_to_emu(padding[3])
    except Exception:
        pass
    paragraphs = _cell_paragraphs(payload.get('runs'))
    fallback_style = style
    if not paragraphs:
        text = str(cell_info.get('text') or '').strip()
        if text:
            paragraphs = [[{'text': text, 'style': fallback_style}]]
    if not paragraphs:
        return
    # clear the default empty paragraph
    try:
        frame.clear()
    except Exception:
        pass
    first = True
    for runs in paragraphs:
        paragraph = frame.paragraphs[0] if first else frame.add_paragraph()
        first = False
        raw_align = str(style.get('align') or 'center').lower()
        paragraph.alignment = {
            'left': PP_ALIGN.LEFT, 'right': PP_ALIGN.RIGHT,
            'center': PP_ALIGN.CENTER, 'justify': PP_ALIGN.JUSTIFY,
            'start': PP_ALIGN.RIGHT if rtl else PP_ALIGN.LEFT,
            'end': PP_ALIGN.LEFT if rtl else PP_ALIGN.RIGHT,
        }.get(raw_align, PP_ALIGN.CENTER)
        _set_rtl(paragraph, rtl)
        try:
            paragraph.space_before = Pt(0)
            paragraph.space_after = Pt(0)
            line_height = float(style.get('line_height') or 0) or float(style.get('size') or 11) * 1.35
            paragraph.line_spacing = Pt(max(1.0, line_height * 0.75))
        except Exception:
            pass
        for run in runs:
            run_style = dict(fallback_style)
            run_style.update(run.get('style') or {})
            text = str(run.get('text') or '')
            if not text:
                continue
            text_run = paragraph.add_run()
            _paint_run(text_run, text, run_style, ctx)


def paint_table(slide, item, ctx):
    rows = item.get('rows') or []
    if not rows:
        return 0
    boundaries = _column_boundaries(rows)
    ncols = max(1, len(boundaries) - 1)
    nrows = len(rows)
    widths = [max(1.0, boundaries[i + 1] - boundaries[i]) for i in range(ncols)]
    table_x = float(item.get('x') or boundaries[0])
    table_y = float(item.get('y') or rows[0].get('y') or 0)
    table_w = sum(widths)
    heights = [max(1.0, float(row.get('h') or 0)) for row in rows]
    table_h = sum(heights)
    opacity = item.get('opacity') or 1.0
    # Nested decorated spans (status pills, highlighted chips) live inside a
    # cell, which a native table cannot express. Draw their boxes BEFORE the
    # table so the transparent cell lets them show through, then the table text
    # is painted on top of them.
    for row in rows:
        for cell in row.get('cells') or []:
            overlays = cell.get('overlays') or []
            if not overlays:
                continue
            rgb, _alpha = _css_color(cell.get('fill'))
            if rgb is not None:
                paint_box(slide, {
                    'type': 'box', 'x': cell['x'], 'y': cell['y'],
                    'w': cell['w'], 'h': cell['h'], 'fill': cell.get('fill'),
                    'radius': '0px', 'borders': [], 'shadow': None,
                    'opacity': opacity}, ctx)
            for overlay in overlays:
                paint_box(slide, overlay, ctx)
    try:
        graphic = slide.shapes.add_table(
            nrows, ncols, _px_to_emu(table_x), _px_to_emu(table_y),
            _px_to_emu(max(1.0, table_w)), _px_to_emu(max(1.0, table_h)))
    except Exception:
        ctx.missing.append(('table', 'add_table failed'))
        return 0
    table = graphic.table
    try:
        table.first_row = False
        table.first_col = False
        table.last_row = False
        table.last_col = False
        table.horz_banding = False
        table.vert_banding = False
    except Exception:
        pass
    for index, width in enumerate(widths):
        try:
            table.columns[index].width = _px_to_emu(width)
        except Exception:
            pass
    for index, height in enumerate(heights):
        try:
            table.rows[index].height = _px_to_emu(height)
        except Exception:
            pass
    consumed = set()
    rich_lines = []
    for row_index, row in enumerate(rows):
        for cell in row.get('cells') or []:
            col_index = _column_index(boundaries, cell.get('x'))
            if col_index >= ncols:
                col_index = ncols - 1
            span_cols = max(1, int(cell.get('colspan') or 1))
            span_cols = min(span_cols, ncols - col_index)
            span_rows = max(1, int(cell.get('rowspan') or 1))
            span_rows = min(span_rows, nrows - row_index)
            if (row_index, col_index) in consumed:
                continue
            for rr in range(row_index, row_index + span_rows):
                for cc in range(col_index, col_index + span_cols):
                    consumed.add((rr, cc))
            target = table.cell(row_index, col_index)
            if span_rows > 1 or span_cols > 1:
                try:
                    target.merge(table.cell(row_index + span_rows - 1,
                                            col_index + span_cols - 1))
                except Exception:
                    pass
            _fill_cell(target, None if cell.get('overlays') else cell.get('fill'),
                       opacity)
            for border in cell.get('borders') or []:
                _set_cell_border(target, border.get('side'), border.get('color'),
                                 border.get('width'), border.get('style'))
            rich = bool(cell.get('overlays'))
            _write_cell(target, {'cell': cell, 'runs': cell.get('runs') or [],
                                 'rich': rich}, ctx)
            if rich:
                rich_lines.extend(cell.get('lines') or [])
            text = str(cell.get('text') or '').strip()
            if text:
                ctx.texts.append(text)
    for line in rich_lines:
        paint_text(slide, line, ctx)
    return 1
