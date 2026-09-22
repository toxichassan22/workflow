
def _draw_corner_accent(c, el):
    pos = el.get('position', 'bottom-left')
    size = el.get('size_mm', 40)*mm
    color = el.get('color', '#C4A35A')
    width = el.get('width', 1.5)
    col = hex_to_color(color)
    c.setStrokeColor(col); c.setLineWidth(width)
    if pos == 'bottom-left':
        c.line(0,0,size,0); c.line(0,0,0,size)
        c.setLineWidth(width*0.4)
        c.line(5*mm,5*mm,size-12*mm,5*mm); c.line(5*mm,5*mm,5*mm,size-12*mm)
    elif pos == 'top-right':
        c.line(PAGE_W,PAGE_H,PAGE_W-size,PAGE_H); c.line(PAGE_W,PAGE_H,PAGE_W,PAGE_H-size)
    elif pos == 'top-left':
        c.line(0,PAGE_H,size,PAGE_H); c.line(0,PAGE_H,0,PAGE_H-size)
    elif pos == 'bottom-right':
        c.line(PAGE_W,0,PAGE_W-size,0); c.line(PAGE_W,0,PAGE_W,size)

def _draw_frame_lines(c, el):
    inset = el.get('inset_mm', 10)*mm
    color = el.get('color', '#C4A35A')
    width = el.get('width', 0.5)
    alpha = el.get('alpha', 0.15)
    col = hex_to_color(color)
    c.saveState()
    c.setStrokeColorRGB(col.red, col.green, col.blue, alpha)
    c.setLineWidth(width)
    c.rect(inset, inset, PAGE_W-2*inset, PAGE_H-2*inset, fill=0, stroke=1)
    c.restoreState()


# ─── ICON DRAWER ─────────────────────────────────────────────────────

def draw_icon(c, icon_name, x, y, size, color_hex='#7A0C0C'):
    pass


# ─── UNIVERSAL HEADER & FOOTER ───────────────────────────────────────

def _draw_universal_header(c, slide, d):
    primary = d.get('primary_color', '#7A0C0C')
    title = slide.get('title', '')
    c.setFillColor(hex_to_color(primary)); c.setFont(ARABIC_FONT, 8)
    shaped = reshape_arabic("Landloom")
    w = pdfmetrics.stringWidth(shaped, ARABIC_FONT, 8)
    c.drawString(PAGE_W - MARGIN - w, PAGE_H - 8*mm, shaped)
    if title:
        c.setFillColor(hex_to_color('#777777')); c.setFont(ARABIC_FONT, 7)
        shaped_title = reshape_arabic(title)
        wt = pdfmetrics.stringWidth(shaped_title, ARABIC_FONT, 7)
        c.drawString(PAGE_W - MARGIN - 45*mm - wt, PAGE_H - 8*mm, shaped_title)
    c.setStrokeColor(hex_to_color(primary)); c.setLineWidth(0.4)
    c.line(MARGIN, PAGE_H-11*mm, PAGE_W-MARGIN, PAGE_H-11*mm)

def _draw_universal_footer(c, slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    project_name = slide.get('projectName', '')
    c.setStrokeColor(hex_to_color('#DDDDDD')); c.setLineWidth(0.3)
    c.line(MARGIN, 10*mm, PAGE_W-MARGIN, 10*mm)
    draw_text(c, project_name or '', MARGIN+2*mm, 6*mm, ARABIC_FONT, 6, '#999999', 'left',
              max_width=PAGE_W*0.4)
    draw_text(c, 'Landloom', PAGE_W-MARGIN-2*mm, 6*mm, ARABIC_FONT, 6, '#999999', 'right')
    c.setFillColor(hex_to_color(primary))
    c.circle(PAGE_W-14*mm, 6*mm, 4*mm, fill=1, stroke=0)
    c.setFillColor(white); c.setFont(ARABIC_FONT, 7)
    c.drawCentredString(PAGE_W-14*mm, 4.5*mm, str(num))


# ════════════════════════════════════════════════════════════════════
# SLIDE RENDERERS
# ════════════════════════════════════════════════════════════════════

def render_slide(c, slide, slide_num, total_slides):
    design = slide.get('design', {})
    slide_type = slide.get('type', 'content')
    if not design:
        design = _default_design(slide_type)

    image_to_use = design.get('image_to_use') or slide.get('image_to_use')
    resolved_image = resolve_image(slide, image_to_use)

    _render_background(c, design)
    _render_decorations(c, design)

    renderers = {
        'cover': _render_cover, 'closing': _render_closing, 'content': _render_content,
        'metrics': _render_metrics, 'table': _render_table, 'section_divider': _render_section_divider,
        'quote': _render_quote, 'comparison': _render_comparison, 'two_column': _render_two_column,
        'timeline': _render_timeline, 'image_focus': _render_image_focus,
    }
    renderer = renderers.get(slide_type, _render_content)
    renderer(c, slide, design, slide_num, total_slides, resolved_image)

    if slide_type not in ('cover', 'closing'):
        _draw_universal_header(c, slide, design)
        _draw_universal_footer(c, slide, design, slide_num, total_slides)


def _default_design(slide_type):
    defaults = {
        'cover': {'mood':'dramatic','background_style':'gradient_v','primary_color':'#7A0C0C',
                  'secondary_color':'#5A0808','accent_color':'#C4A35A','bg_color':'#7A0C0C',
                  'text_color':'#FFFFFF','layout':'centered','title_style':'large_centered'},
        'closing': {'mood':'dramatic','background_style':'gradient_v','primary_color':'#7A0C0C',
                    'secondary_color':'#5A0808','accent_color':'#C4A35A','bg_color':'#5A0808',
                    'text_color':'#FFFFFF','layout':'centered','title_style':'large_centered'},
        'content': {'mood':'modern','background_style':'solid','primary_color':'#7A0C0C',
                   'secondary_color':'#C4A35A','accent_color':'#F5F0EE','bg_color':'#FBFAF8',
                   'text_color':'#2D2D2D','layout':'split_rl','title_style':'top_bar','card_style':'rounded_shadow'},
        'metrics': {'mood':'modern','background_style':'solid','primary_color':'#7A0C0C',
                    'secondary_color':'#C4A35A','accent_color':'#FBF6EE','bg_color':'#FBF6EE',
                    'text_color':'#2D2D2D','layout':'cards','title_style':'top_bar','card_style':'rounded_shadow'},
        'table': {'mood':'minimal','background_style':'solid','primary_color':'#7A0C0C',
                  'secondary_color':'#C4A35A','accent_color':'#FAF7F2','bg_color':'#FAF7F2',
                  'text_color':'#2D2D2D','layout':'cards','title_style':'top_bar'},
    }
    d = defaults.get(slide_type, defaults['content'])
    d['decorative_elements'] = []
    return d


# ─── BACKGROUND RENDERERS ────────────────────────────────────────────

def _render_background(c, d):
    style = d.get('background_style', 'solid')
    bg = d.get('bg_color', '#FFFFFF')
    primary = d.get('primary_color', '#7A0C0C')
    secondary = d.get('secondary_color', '#C4A35A')

    if style == 'solid':
        draw_rect(c, 0, 0, PAGE_W, PAGE_H, bg)
    elif style == 'gradient_v':
        draw_gradient_vertical(c, 0, PAGE_H, d.get('gradient_top_color', primary),
                              d.get('gradient_bottom_color', secondary))
    elif style == 'gradient_h':
        ct = hex_to_color(d.get('gradient_left_color', secondary))
        cb = hex_to_color(d.get('gradient_right_color', primary))
        sw = PAGE_W/30
        for i in range(30):
            col = lerp_color(ct, cb, i/30); c.setFillColor(col)
            c.rect(i*sw, 0, sw+1, PAGE_H, fill=1, stroke=0)
    elif style == 'radial_glow':
        draw_rect(c, 0, 0, PAGE_W, PAGE_H, bg)
        draw_radial_glow(c, d.get('glow_x_pct',0.5)*PAGE_W, d.get('glow_y_pct',0.5)*PAGE_H,
                        d.get('glow_radius_mm',120)*mm, d.get('glow_color', primary), 0.18)
    elif style == 'split':
        sd = d.get('split_direction', 'horizontal')
        sp = d.get('split_position_pct', 0.35)
        if sd == 'horizontal':
            draw_rect(c, 0, 0, PAGE_W, PAGE_H*(1-sp), primary)
            draw_rect(c, 0, PAGE_H*(1-sp), PAGE_W, PAGE_H*sp, bg)
        else:
            draw_rect(c, 0, 0, PAGE_W*sp, PAGE_H, primary)
            draw_rect(c, PAGE_W*sp, 0, PAGE_W*(1-sp), PAGE_H, bg)
    elif style == 'geometric':
        draw_rect(c, 0, 0, PAGE_W, PAGE_H, bg)
        draw_dot_grid(c, 20*mm, 0.6*mm, primary, 0.06)
        draw_geometric_lines(c, primary, 4, 0.05)
    elif style == 'wave':
        draw_rect(c, 0, 0, PAGE_W, PAGE_H, bg)
        draw_wave(c, d.get('wave_y_pct',0.65)*PAGE_H, d.get('wave_amplitude_mm',15)*mm,
                 d.get('wave_wavelength_mm',80)*mm, d.get('wave_color', primary), True, 0.12)
    elif style == 'dark':
        draw_rect(c, 0, 0, PAGE_W, PAGE_H, '#1a1a2e')
        draw_radial_glow(c, PAGE_W*0.8, PAGE_H*0.2, 100*mm, primary, 0.1)


# ─── CONTENT RENDERERS BY TYPE ───────────────────────────────────────

def _render_cover(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#FFFFFF')
    layout = d.get('layout', 'centered')
    title = slide.get('title', '')
    subtitle = slide.get('subtitle', '')
    img = resolved_image
    max_tw = PAGE_W - 2 * MARGIN  # max text width for cover

    if layout in ('centered', 'full_bleed'):
        if img:
            draw_image_safe(c, img, 0, 0, PAGE_W, PAGE_H)
            c.saveState(); c.setFillColor(hex_to_color(primary))
            c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
            c.setFillColorRGB(0, 0, 0, 0.55)
            c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0); c.restoreState()
        draw_text(c, title, PAGE_W/2, PAGE_H/2+15*mm, ARABIC_FONT_BOLD, 30, text_c, 'center',
                  max_width=max_tw)
        lw = min(80*mm, len(title)*3*mm)
        draw_line(c, PAGE_W/2-lw/2, PAGE_H/2+8*mm, PAGE_W/2+lw/2, PAGE_H/2+8*mm, accent, 2.5)
        if subtitle:
            draw_text(c, subtitle, PAGE_W/2, PAGE_H/2-5*mm, ARABIC_FONT, 14,
                      _color_to_hex(lighten(text_c,0.2)), 'center', max_width=max_tw)
    elif layout == 'split_rl':
        draw_rect(c, PAGE_W*0.45, 0, PAGE_W*0.55, PAGE_H, primary)
        if img:
            draw_image_safe(c, img, MARGIN, PAGE_H*0.15, PAGE_W*0.38, PAGE_H*0.7, True, '#FFFFFF', 3, 5)
        title_max_w = PAGE_W * 0.55 - MARGIN - 10*mm
        draw_text(c, title, PAGE_W-MARGIN, PAGE_H*0.55, ARABIC_FONT_BOLD, 26, text_c, 'right',
                  max_width=title_max_w)
        if subtitle:
            draw_text(c, subtitle, PAGE_W-MARGIN, PAGE_H*0.43, ARABIC_FONT, 13,
                      _color_to_hex(lighten(accent,0.3)), 'right', max_width=title_max_w)
        draw_line(c, PAGE_W*0.45+10*mm, PAGE_H*0.48, PAGE_W-MARGIN, PAGE_H*0.48, accent, 2)

def _render_closing(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#FFFFFF')
    title = slide.get('title', 'شكراً لكم')
    subtitle = slide.get('subtitle', '')
    contact = slide.get('contact', '')
    img = resolved_image
    max_tw = PAGE_W - 2 * MARGIN

    if img:
        draw_image_safe(c, img, 0, 0, PAGE_W, PAGE_H)
        c.saveState(); c.setFillColor(hex_to_color(primary))
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0, 0.6); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0); c.restoreState()
    draw_text(c, title, PAGE_W/2, PAGE_H/2+12*mm, ARABIC_FONT_BOLD, 36, text_c, 'center',
              max_width=max_tw)
    lw = 70*mm
    draw_line(c, PAGE_W/2-lw/2, PAGE_H/2+5*mm, PAGE_W/2+lw/2, PAGE_H/2+5*mm, accent, 1.5)
    draw_line(c, PAGE_W/2-lw/2, PAGE_H/2-20*mm, PAGE_W/2+lw/2, PAGE_H/2-20*mm, accent, 1.5)
    if subtitle:
        draw_text(c, subtitle, PAGE_W/2, PAGE_H/2-8*mm, ARABIC_FONT, 15,
                  _color_to_hex(lighten(text_c,0.3)), 'center', max_width=max_tw)
    if contact:
        draw_text(c, contact, PAGE_W/2, PAGE_H/2-35*mm, ARABIC_FONT, 12, accent, 'center',
                  max_width=max_tw)
    draw_text(c, 'Landloom', PAGE_W/2, 18*mm, ARABIC_FONT, 9,
              _color_to_hex(lighten(text_c,0.5)), 'center')

def _render_content(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    layout = d.get('layout', 'split_rl')
    title_style = d.get('title_style', 'top_bar')
    card_style = d.get('card_style', 'rounded_shadow')
    title = slide.get('title', '')
    subtitle = slide.get('subtitle', '')
    bullets = slide.get('bullets', [])
    content_html = slide.get('content', '')
    img = resolved_image

    # Title area
    title_max_w = PAGE_W - 2 * MARGIN - 10*mm
    if title_style == 'top_bar':
        bh = 22*mm; draw_rect(c, 0, PAGE_H-bh, PAGE_W, bh, primary)
        draw_rect(c, 0, PAGE_H-bh-1.2*mm, PAGE_W, 1.2*mm, accent)
        draw_text(c, title, PAGE_W-MARGIN, PAGE_H-14*mm, ARABIC_FONT_BOLD, 18, '#FFFFFF', 'right',
                  max_width=title_max_w)
        content_top = PAGE_H - 30*mm
    elif title_style == 'side_accent':
        draw_rect(c, PAGE_W-5*mm, 0, 5*mm, PAGE_H, primary)
        draw_text(c, title, PAGE_W-12*mm, PAGE_H-18*mm, ARABIC_FONT_BOLD, 20, primary, 'right',
                  max_width=title_max_w)
        draw_line(c, MARGIN, PAGE_H-22*mm, PAGE_W-16*mm, PAGE_H-22*mm, accent, 1.5)
        content_top = PAGE_H - 28*mm
    elif title_style == 'floating_card':
        cw = PAGE_W - 2*MARGIN
        draw_rect(c, MARGIN, PAGE_H-28*mm, cw, 22*mm, '#FFFFFF', 4)
        draw_rect(c, MARGIN, PAGE_H-28*mm, 4*mm, 22*mm, primary, 4)
        draw_rect(c, MARGIN+1.5*mm, PAGE_H-27*mm, 2.5*mm, 20*mm, primary, 0)
        draw_text(c, title, PAGE_W-MARGIN-10*mm, PAGE_H-17*mm, ARABIC_FONT_BOLD, 18, primary, 'right',
                  max_width=title_max_w)
        content_top = PAGE_H - 36*mm
    else:
        draw_text(c, title, PAGE_W/2, PAGE_H-20*mm, ARABIC_FONT_BOLD, 22, primary, 'center',
                  max_width=title_max_w)
        draw_line(c, PAGE_W/3, PAGE_H-25*mm, PAGE_W*2/3, PAGE_H-25*mm, accent, 1.5)
        content_top = PAGE_H - 32*mm

    if subtitle:
        draw_text(c, subtitle, PAGE_W-MARGIN, content_top-5*mm, ARABIC_FONT, 10, '#888888', 'right',
                  max_width=title_max_w)
        content_top -= 10*mm

    content_area_h = content_top - 18*mm

    # Image placement
    if layout == 'split_rl' and img:
        iw = min(55*mm, PAGE_W*0.28); ih = min(content_area_h-12*mm, 42*mm)
        ix = MARGIN+5*mm; iy = content_top-ih-6*mm
        if card_style != 'none':
            draw_rect(c, ix-3*mm, iy-3*mm, iw+6*mm, ih+6*mm, '#FFFFFF', 3)
        draw_image_safe(c, img, ix, iy, iw, ih)
        text_x_start = ix+iw+8*mm; text_w = PAGE_W-text_x_start-MARGIN-6*mm
    elif layout == 'split_lr' and img:
        iw = min(55*mm, PAGE_W*0.28); ih = min(content_area_h-12*mm, 42*mm)
        ix = PAGE_W-MARGIN-iw-5*mm; iy = content_top-ih-6*mm
        if card_style != 'none':
            draw_rect(c, ix-3*mm, iy-3*mm, iw+6*mm, ih+6*mm, '#FFFFFF', 3)
        draw_image_safe(c, img, ix, iy, iw, ih)
        text_x_start = MARGIN+5*mm; text_w = ix-16*mm
    else:
        text_x_start = MARGIN+8*mm; text_w = PAGE_W-2*MARGIN-12*mm

    # Content card background
    if card_style == 'rounded_shadow':
        draw_rect(c, text_x_start-5*mm, 16*mm, text_w+10*mm, content_area_h-3*mm, '#FFFFFF', 4)
        draw_rect(c, text_x_start-3*mm, 14*mm, text_w+6*mm, 2.5*mm, '#EDE8E3', 3)
    elif card_style == 'glass':
        draw_rect(c, text_x_start-5*mm, 16*mm, text_w+10*mm, content_area_h-3*mm, '#FFFFFF', 4, 0.85)
    elif card_style == 'flat_border':
        c.setStrokeColor(accent); c.setLineWidth(1)
        c.roundRect(text_x_start-5*mm, 16*mm, text_w+10*mm, content_area_h-3*mm, 3, fill=0, stroke=1)

    # Bullets — anchor and width derived from the computed text column
    if bullets:
        y = content_top - 12*mm
        bstyle = d.get('bullet_style', 'diamond')
        # Right edge of text column (for RTL, text ends at text_x_start + text_w)
        bx = text_x_start + text_w
        bullet_avail_w = text_w - 8*mm  # leave room for the marker
        for idx, bullet in enumerate(bullets[:12]):
            if y < 24*mm: break
            if bstyle == 'diamond':
                c.saveState(); c.setFillColor(hex_to_color(accent))
                c.translate(bx, y+2*mm); c.rotate(45)
                c.rect(-1.8*mm,-1.8*mm,3.6*mm,3.6*mm,fill=1,stroke=0); c.restoreState()
            elif bstyle == 'circle':
                draw_circle(c, bx, y+2*mm, 2*mm, accent)
            elif bstyle == 'bar':
                draw_rect(c, bx-3.5*mm, y+0.5*mm, 7*mm, 2.5*mm, accent, 1)
            draw_text(c, bullet, bx-7*mm, y, ARABIC_FONT, 11, text_c, 'right',
                      max_width=bullet_avail_w)
            y -= 8*mm
    elif content_html:
        clean = re.sub(r'<[^>]+>', '\n', str(content_html))
        lines = [l.strip() for l in clean.split('\n') if l.strip()]
        y = content_top - 12*mm
        html_avail_w = text_w - 6*mm
        for line in lines[:14]:
            if y < 24*mm: break
            draw_text(c, line, text_x_start + text_w, y, ARABIC_FONT, 10, text_c, 'right',
                      max_width=html_avail_w)
            y -= 7*mm

def _render_metrics(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    metrics = slide.get('metrics', [])

    draw_rect(c, 0, PAGE_H-22*mm, PAGE_W, 22*mm, primary)
    draw_rect(c, 0, PAGE_H-23.2*mm, PAGE_W, 1.2*mm, accent)
    draw_text(c, title, PAGE_W-MARGIN, PAGE_H-14*mm, ARABIC_FONT_BOLD, 18, '#FFFFFF', 'right',
              max_width=PAGE_W-2*MARGIN)

    if not metrics: return
    cols = min(d.get('metrics_columns', 3), len(metrics))
    rows = (len(metrics)+cols-1)//cols
    pad = 8*mm; avail_w = PAGE_W-2*MARGIN-10*mm; gap = 6*mm
    cw = (avail_w-(cols-1)*gap)/cols; ch = d.get('metric_card_height_mm', 26)*mm
    sx = PAGE_W-MARGIN-6*mm; sy = PAGE_H-34*mm

    for idx, metric in enumerate(metrics):
        col = idx%cols; row = idx//cols
        x = sx-(col+1)*cw-col*gap; y = sy-row*(ch+gap)
        label = metric.get('label', '')
        value = str(metric.get('value', ''))
        draw_rect(c, x+2*mm, y-2*mm, cw-4*mm, ch-4*mm, '#E8E0D6', 4)
        draw_rect(c, x, y, cw, ch, '#FFFFFF', 5)
        draw_rect(c, x+2, y+ch-4*mm, cw-4, 4*mm, primary, 3)
        draw_text(c, label, x+cw-5*mm, y+ch-12*mm, ARABIC_FONT_BOLD, 8, '#888888', 'right',
                  max_width=cw-10*mm)
        draw_text(c, value, x+cw-5*mm, y+6*mm, ARABIC_FONT_BOLD, 15, primary, 'right',
                  max_width=cw-10*mm)

def _render_table(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    table_data = slide.get('table', [])

    draw_rect(c, 0, PAGE_H-22*mm, PAGE_W, 22*mm, primary)
    draw_rect(c, 0, PAGE_H-23.2*mm, PAGE_W, 1.2*mm, accent)
    draw_text(c, title, PAGE_W-MARGIN, PAGE_H-14*mm, ARABIC_FONT_BOLD, 18, '#FFFFFF', 'right',
              max_width=PAGE_W-2*MARGIN)

    if not table_data: return
    rows = len(table_data); cols = max(len(row) for row in table_data)
    tw = PAGE_W-2*MARGIN-10*mm; col_w = tw/cols; rh = 10*mm; sy = PAGE_H-30*mm
    draw_rect(c, MARGIN+2*mm, 18*mm, tw+4*mm, rows*rh+6*mm, '#FFFFFF', 4)

    for r, row in enumerate(table_data):
        y = sy - r*rh
        if y < 22*mm: break
        if r == 0:
            draw_rect(c, MARGIN+4*mm, y-rh+1.2*mm, tw-2*mm, rh-1.5*mm, primary, 3)
            tc = '#FFFFFF'; font = (ARABIC_FONT_BOLD, 8)
        else:
            if r%2==0: draw_rect(c, MARGIN+4*mm, y-rh+1.2*mm, tw-2*mm, rh-1.5*mm, '#F5F0EE', 2)
            tc = text_c; font = (ARABIC_FONT, 8)
        for ci, cell in enumerate(row):
            cx = PAGE_W-MARGIN-8*mm-(ci+1)*col_w
            draw_text(c, str(cell), cx+col_w/2, y-rh+3*mm, font[0], font[1], tc, 'center',
                      max_width=col_w-4*mm)

def _render_section_divider(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#FFFFFF')
    title = slide.get('title', '')
    subtitle = slide.get('subtitle', '')
    max_tw = PAGE_W - 2 * MARGIN
    draw_text(c, title, PAGE_W/2, PAGE_H/2+8*mm, ARABIC_FONT_BOLD, 30, text_c, 'center',
              max_width=max_tw)
    draw_line(c, PAGE_W/3, PAGE_H/2-3*mm, PAGE_W*2/3, PAGE_H/2-3*mm, accent, 2)
    if subtitle:
        draw_text(c, subtitle, PAGE_W/2, PAGE_H/2-14*mm, ARABIC_FONT, 13,
                  _color_to_hex(lighten(accent,0.2)), 'center', max_width=max_tw)

def _render_quote(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    quote = slide.get('title', '')
    author = slide.get('subtitle', '')
    max_tw = PAGE_W - 2 * MARGIN
    draw_text(c, '"', MARGIN+5*mm, PAGE_H-38*mm, ARABIC_FONT_BOLD, 80, accent, 'left')
    # Allow up to ~6 lines between the quote mark and the divider line
    quote_max_h = (PAGE_H/2 + 5*mm) - (PAGE_H/2 - 18*mm) + 4*mm
    draw_text_wrapped(c, quote, PAGE_W/2, PAGE_H/2+5*mm, ARABIC_FONT, 16, primary, 'center',
                      max_width=max_tw*0.85, max_height=quote_max_h)
    draw_line(c, PAGE_W/3, PAGE_H/2-18*mm, PAGE_W*2/3, PAGE_H/2-18*mm, accent, 1.5)
    if author:
        draw_text(c, author, PAGE_W/2, PAGE_H/2-28*mm, ARABIC_FONT_BOLD, 11, '#888888', 'center',
                  max_width=max_tw*0.6)

def _render_comparison(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    lt = slide.get('subtitle', '')
    rt = str(slide.get('content', ''))[:100] if isinstance(slide.get('content'), str) else ''
    li = slide.get('bullets', [])
    ri = slide.get('metrics', [{'label':'','value':m} if isinstance(m,str) else m for m in (slide.get('right_bullets') or [])])
    max_tw = PAGE_W - 2 * MARGIN

    draw_text(c, title, PAGE_W/2, PAGE_H-18*mm, ARABIC_FONT_BOLD, 18, primary, 'center',
              max_width=max_tw)
    draw_line(c, PAGE_W/3, PAGE_H-22*mm, PAGE_W*2/3, PAGE_H-22*mm, accent, 1.5)
    mid = PAGE_W/2; ch = PAGE_H-48*mm; cww = (PAGE_W-3*MARGIN)/2-8*mm

    draw_rect(c, MARGIN, 20*mm, cww, ch, '#FFFFFF', 5)
    draw_rect(c, MARGIN, 20*mm, cww, 5*mm, primary, 5)
    draw_rect(c, MARGIN+1*mm, 21*mm, cww-2*mm, 3*mm, primary, 0)
    draw_text(c, lt, MARGIN+cww/2, 20*mm+ch-12*mm, ARABIC_FONT_BOLD, 12, '#FFFFFF', 'center',
              max_width=cww-8*mm)
    y = 20*mm+ch-24*mm
    for item in li[:8]:
        if y<26*mm: break
        it=item if isinstance(item,str) else item.get('label','')
        draw_text(c, f"• {it}", MARGIN+12*mm, y, ARABIC_FONT, 10, text_c, 'right',
                  max_width=cww-16*mm); y-=8*mm

    rx = mid+4*mm
    draw_rect(c, rx, 20*mm, cww, ch, '#FFFFFF', 5)
    draw_rect(c, rx, 20*mm, cww, 5*mm, accent, 5)
    draw_rect(c, rx+1*mm, 21*mm, cww-2*mm, 3*mm, accent, 0)
    draw_text(c, rt, rx+cww/2, 20*mm+ch-12*mm, ARABIC_FONT_BOLD, 12, '#FFFFFF', 'center',
              max_width=cww-8*mm)
    y = 20*mm+ch-24*mm
    for item in ri[:8]:
        if y<26*mm: break
        it=item if isinstance(item,str) else item.get('label',item.get('value',''))
        draw_text(c, f"• {it}", rx+12*mm, y, ARABIC_FONT, 10, text_c, 'right',
                  max_width=cww-16*mm); y-=8*mm

def _render_two_column(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    draw_rect(c, 0, PAGE_H-22*mm, PAGE_W, 22*mm, primary)
    draw_text(c, title, PAGE_W-MARGIN, PAGE_H-14*mm, ARABIC_FONT_BOLD, 17, '#FFFFFF', 'right',
              max_width=PAGE_W-2*MARGIN)
    mid = PAGE_W/2; col_w = (PAGE_W-2*MARGIN-8*mm)/2

    lc = slide.get('content', '')
    if lc:
        clean = re.sub(r'<[^>]+>', '\n', str(lc))
        lines = [l.strip() for l in clean.split('\n') if l.strip()]
        y = PAGE_H-32*mm
        for line in lines[:10]:
            if y<22*mm: break
            draw_text(c, line, mid-6*mm, y, ARABIC_FONT, 10, text_c, 'right',
                      max_width=col_w-6*mm); y-=7*mm

    rb = slide.get('bullets', [])
    if rb:
        y = PAGE_H-32*mm
        for b in rb[:10]:
            if y<22*mm: break
            draw_text(c, b, PAGE_W-MARGIN-6*mm, y, ARABIC_FONT, 10, text_c, 'right',
                      max_width=col_w-6*mm); y-=7*mm
    draw_line(c, mid, PAGE_H-29*mm, mid, 22*mm, accent, 0.5)

def _render_timeline(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    td = slide.get('table', []) or slide.get('bullets', [])
    draw_rect(c, 0, PAGE_H-22*mm, PAGE_W, 22*mm, primary)
    draw_text(c, title, PAGE_W-MARGIN, PAGE_H-14*mm, ARABIC_FONT_BOLD, 17, '#FFFFFF', 'right',
              max_width=PAGE_W-2*MARGIN)
    ly = PAGE_H/2; draw_line(c, MARGIN+15*mm, ly, PAGE_W-MARGIN-15*mm, ly, '#CCCCCC', 2)
    if not td: return
    sp = (PAGE_W-2*MARGIN-30*mm)/max(len(td),1)
    for idx, item in enumerate(td):
        if isinstance(item, dict): label = item.get('label',item.get('value',''))
        elif isinstance(item, list): label = item[0] if item else ''
        else: label = str(item)
        x = MARGIN+15*mm+idx*sp+sp/2
        draw_circle(c, x, ly, 3*mm, primary)
        draw_text(c, label, x, ly+8*mm, ARABIC_FONT_BOLD, 8, text_c, 'center',
                  max_width=sp-4*mm)
        draw_line(c, x, ly+3*mm, x, ly+6*mm, primary, 1)

def _render_image_focus(c, slide, d, num, total, resolved_image=None):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    img = resolved_image or slide.get('image_b64', '')
    title = slide.get('title', '')
    caption = slide.get('subtitle', '')
    max_tw = PAGE_W - 2 * MARGIN
    if img:
        draw_image_safe(c, img, MARGIN, 18*mm, PAGE_W-2*MARGIN, PAGE_H-40*mm, True, '#FFFFFF', 3, 4)
    if caption:
        draw_text(c, caption, PAGE_W/2, 28*mm, ARABIC_FONT, 12, primary, 'center',
                  max_width=max_tw)
    if title:
        draw_text(c, title, PAGE_W/2, PAGE_H-12*mm, ARABIC_FONT_BOLD, 14, primary, 'center',
                  max_width=max_tw)


# ════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════

def generate_pdf(slides, project_name='project', output_path='output.pdf'):
    register_fonts()
    c = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(project_name); c.setAuthor('Landloom')
    total = len(slides)
    for i, slide in enumerate(slides):
        render_slide(c, slide, i+1, total)
        if i < total-1: c.showPage()
    c.save()
    return output_path

if __name__ == '__main__':
    test_slides = [
        {'type':'cover','title':'مشروع الواحة السكنية','subtitle':'دراسة جدوى | الرياض',
         'design':{'mood':'dramatic','background_style':'gradient_v','primary_color':'#1a3a52',
                   'secondary_color':'#0d1f2d','accent_color':'#d4a84b','bg_color':'#1a3a52',
                   'text_color':'#FFFFFF','layout':'centered','title_style':'large_centered',
                   'decorative_elements':[{'type':'circle','x_pct':0.9,'y_pct':0.15,'r_mm':70,'color':'#d4a84b','alpha':0.08},
                                         {'type':'stripe','position':'top-right','width_mm':140,'depth_mm':220}]}},
        {'type':'content','title':'الملخص التنفيذي','bullets':['مشروع سكني على 15000م²','120 وحدة','عائد 18%'],
         'design':{'mood':'modern','background_style':'radial_glow','primary_color':'#2d5a4a',
                   'secondary_color':'#1a3a30','accent_color':'#c9a227','bg_color':'#f8faf6',
                   'text_color':'#1a2e24','layout':'split_rl','title_style':'side_accent',
                   'card_style':'rounded_shadow','bullet_style':'diamond',
                   'glow_x_pct':0.85,'glow_y_pct':0.2,'glow_radius_mm':100,'glow_color':'#2d5a4a'}},
        {'type':'metrics','title':'المؤشرات المالية','metrics':[{'label':'إجمالي الاستثمار','value':'45M ر.س'},{'label':'العائد السنوي','value':'18.5%'},{'label':'فترة الاسترداد','value':'5.4 سنة'}],
         'design':{'mood':'minimal','background_style':'geometric','primary_color':'#6b2d5b',
                   'secondary_color':'#4a1d3e','accent_color':'#e8c547','bg_color':'#faf6f8',
                   'text_color':'#2d1f2a','layout':'cards','title_style':'top_bar','metrics_columns':3}},
        {'type':'comparison','title':'مقارنة الخيارات','subtitle':'الخيار التقليدي','content':'شراء أرض وبناء',
         'bullets':['تكلفة عالية','مدة طويلة'],'right_bullets':['تكلفة محدودة','عائد فوري'],
         'design':{'mood':'modern','background_style':'solid','primary_color':'#1a3a5c',
                   'secondary_color':'#c4a35a','accent_color':'#c4a35a','bg_color':'#f0f4f8',
                   'text_color':'#1a2a3a','layout':'cards','title_style':'large_centered'}},
        {'type':'quote','title':'الاستثمار في العقار هو استثمار في المستقبل','subtitle':'رؤية 2030',
         'design':{'mood':'dramatic','background_style':'wave','primary_color':'#4a3080',
                   'accent_color':'#d4a84b','bg_color':'#f5f3fa',
                   'wave_y_pct':0.6,'wave_amplitude_mm':12,'wave_wavelength_mm':70,'wave_color':'#4a3080'}},
        {'type':'section_divider','title':'التحليل المالي','subtitle':'الجزء الثاني',
         'design':{'mood':'bold','background_style':'split','primary_color':'#c4382a',
                   'secondary_color':'#f5f0ee','accent_color':'#e8a838','bg_color':'#c4382a',
                   'text_color':'#FFFFFF','split_direction':'horizontal','split_position_pct':0.5}},
        {'type':'closing','title':'شكراً لثقتكم','subtitle':'Landloom','contact':'info@landloom.ai',
         'design':{'mood':'dramatic','background_style':'gradient_v','primary_color':'#1a3a52',
                   'secondary_color':'#0d1f2d','accent_color':'#d4a84b','bg_color':'#1a3a52',
                   'text_color':'#FFFFFF','layout':'centered',
                   'decorative_elements':[{'type':'circle','x_pct':0.15,'y_pct':0.2,'r_mm':100,'color':'#d4a84b','alpha':0.06},
                                         {'type':'stripe','position':'top-left','width_mm':160,'depth_mm':200}]}}
    ]
    generate_pdf(test_slides, 'test_design', 'test_output.pdf')
    print("Test PDF generated with GLM-driven designs!")
