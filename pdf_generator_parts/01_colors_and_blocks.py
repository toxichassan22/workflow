
def hex_to_color(h):
    if not h:
        return HexColor('#333333')
    h = h.lstrip('#')
    try:
        return HexColor('#' + h)
    except:
        return HexColor('#333333')

def lerp_color(c1, c2, t):
    return Color(
        c1.red + (c2.red - c1.red) * t,
        c1.green + (c2.green - c1.green) * t,
        c1.blue + (c2.blue - c1.blue) * t)

def darken(hex_color, amount=0.2):
    c = hex_to_color(hex_color)
    return Color(max(0, c.red - amount), max(0, c.green - amount), max(0, c.blue - amount))

def lighten(hex_color, amount=0.2):
    c = hex_to_color(hex_color)
    return Color(min(1, c.red + amount), min(1, c.green + amount), min(1, c.blue + amount))

def _color_to_hex(c):
    try:
        return '#%02X%02X%02X' % (int(c.red * 255), int(c.green * 255), int(c.blue * 255))
    except:
        return '#333333'

# ─── FONT REGISTRATION ───────────────────────────────────────────────

ARABIC_FONT = 'Helvetica'  # Will be updated after registration
ARABIC_FONT_BOLD = 'Helvetica-Bold'  # Will be updated after registration

def register_fonts():
    global ARABIC_FONT, ARABIC_FONT_BOLD
    font_paths = [
        ('TheSansArabic-Light', str(PROJECT_ROOT / 'assets' / 'fonts' / 'TheSansArabic-Light.ttf')),
        ('TheSansArabic-Bold', str(PROJECT_ROOT / 'assets' / 'fonts' / 'BahijTheSansArabic-Bold.ttf')),
    ]
    for name, fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont(name, fp))
            except:
                pass

    # Always use The Sans Arabic
    try:
        pdfmetrics.getFont('TheSansArabic-Light')
        ARABIC_FONT = 'TheSansArabic-Light'
        try:
            pdfmetrics.getFont('TheSansArabic-Bold')
            ARABIC_FONT_BOLD = 'TheSansArabic-Bold'
        except:
            ARABIC_FONT_BOLD = 'TheSansArabic-Light'
    except:
        pass

    print(f"  [PDF] Using font: {ARABIC_FONT} (bold: {ARABIC_FONT_BOLD})")
    return True

def reshape_arabic(text):
    """Reshape Arabic text for correct ligatures.
    Does NOT apply bidi - drawString handles positioning natively."""
    if not text:
        return text
    try:
        return arabic_reshaper.reshape(text)
    except:
        return text


def reshape_arabic_for_rtl(text):
    """Reshape Arabic text for RTL rendering (e.g. drawRightString).
    Only reshapes characters for ligatures, does NOT apply bidi reversal,
    because drawRightString already handles RTL positioning."""
    if not text:
        return text
    try:
        return arabic_reshaper.reshape(text)
    except:
        return text

# ─── DRAWING PRIMITIVES ──────────────────────────────────────────────

def draw_gradient_vertical(c, y_bottom, height, color_top_hex, color_bottom_hex, steps=30):
    ct = hex_to_color(color_top_hex)
    cb = hex_to_color(color_bottom_hex)
    step_h = height / steps
    for i in range(steps):
        col = lerp_color(ct, cb, i / steps)
        c.setFillColor(col)
        c.rect(0, y_bottom + i * step_h, PAGE_W, step_h + 1, fill=1, stroke=0)

def draw_radial_glow(c, cx, cy, radius, color_hex, alpha=0.15):
    col = hex_to_color(color_hex)
    layers = 8
    for i in range(layers, 0, -1):
        r = radius * i / layers
        a = alpha * (1 - i / layers) * 2
        c.saveState()
        c.setFillColorRGB(col.red, col.green, col.blue, min(a, 0.4))
        c.circle(cx, cy, r, fill=1, stroke=0)
        c.restoreState()

def draw_circle(c, x, y, r, color_hex, alpha=1.0):
    col = hex_to_color(color_hex)
    c.saveState()
    if alpha < 1.0:
        c.setFillColorRGB(col.red, col.green, col.blue, alpha)
    else:
        c.setFillColor(col)
    c.circle(x, y, r, fill=1, stroke=0)
    c.restoreState()

def draw_rect(c, x, y, w, h, color_hex, radius=0, alpha=1.0):
    col = hex_to_color(color_hex)
    c.saveState()
    if alpha < 1.0:
        c.setFillColorRGB(col.red, col.green, col.blue, alpha)
    else:
        c.setFillColor(col)
    if radius > 0:
        c.roundRect(x, y, w, h, radius, fill=1, stroke=0)
    else:
        c.rect(x, y, w, h, fill=1, stroke=0)
    c.restoreState()

def draw_line(c, x1, y1, x2, y2, color_hex, width=1):
    c.setStrokeColor(hex_to_color(color_hex))
    c.setLineWidth(width)
    c.line(x1, y1, x2, y2)

def draw_diagonal_stripe(c, color_hex, position='top-right', width_mm=120, depth_mm=200):
    col = hex_to_color(color_hex)
    c.saveState()
    c.setFillColor(col)
    # Clamp stripe size to max 25% of page dimensions to prevent overwhelming the design
    max_w = PAGE_W * 0.25
    max_h = PAGE_H * 0.30
    w = min(width_mm, max_w)
    h = min(depth_mm, max_h)
    p = c.beginPath()
    if position == 'top-right':
        p.moveTo(PAGE_W, PAGE_H - h); p.lineTo(PAGE_W, PAGE_H)
        p.lineTo(PAGE_W - w, PAGE_H)
    elif position == 'bottom-left':
        p.moveTo(0, h); p.lineTo(0, 0); p.lineTo(w, 0)
    elif position == 'top-left':
        p.moveTo(0, PAGE_H - h); p.lineTo(0, PAGE_H); p.lineTo(w, PAGE_H)
    elif position == 'bottom-right':
        p.moveTo(PAGE_W, h); p.lineTo(PAGE_W, 0); p.lineTo(PAGE_W - w, 0)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    c.restoreState()

def draw_wave(c, y_base, amplitude, wavelength, color_hex, fill_down=True, alpha=1.0):
    col = hex_to_color(color_hex)
    c.saveState()
    if alpha < 1.0:
        c.setFillColorRGB(col.red, col.green, col.blue, alpha)
    else:
        c.setFillColor(col)
    p = c.beginPath()
    p.moveTo(0, y_base)
    x = 0
    while x <= PAGE_W:
        wy = y_base + amplitude * math.sin((x / wavelength) * 2 * math.pi)
        p.lineTo(x, wy)
        x += 3
    if fill_down:
        p.lineTo(PAGE_W, 0); p.lineTo(0, 0)
    else:
        p.lineTo(PAGE_W, PAGE_H); p.lineTo(0, PAGE_H)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    c.restoreState()

def draw_dot_grid(c, spacing, dot_radius, color_hex, alpha=0.12):
    col = hex_to_color(color_hex)
    c.saveState()
    c.setFillColorRGB(col.red, col.green, col.blue, alpha)
    x = MARGIN
    while x < PAGE_W - MARGIN:
        y = MARGIN
        while y < PAGE_H - MARGIN:
            c.circle(x, y, dot_radius, fill=1, stroke=0)
            y += spacing
        x += spacing
    c.restoreState()

def draw_geometric_lines(c, color_hex, count=5, alpha=0.08):
    import random
    random.seed(42)
    col = hex_to_color(color_hex)
    c.saveState()
    # Reduce alpha significantly so decorative lines are subtle background texture
    effective_alpha = min(alpha, 0.04)
    for _ in range(count):
        x1 = random.uniform(0, PAGE_W)
        y1 = random.uniform(0, PAGE_H)
        angle = random.uniform(0, math.pi * 2)
        length = random.uniform(40 * mm, 120 * mm)
        x2 = x1 + length * math.cos(angle)
        y2 = y1 + length * math.sin(angle)
        c.setStrokeColorRGB(col.red, col.green, col.blue, effective_alpha)
        c.setLineWidth(random.uniform(0.3, 1.0))
        c.line(x1, y1, x2, y2)
    c.restoreState()

def draw_image_safe(c, image_b64, x, y, w, h, border=False, border_color='#FFFFFF', border_width=2, corner_radius=0):
    try:
        import base64
        from io import BytesIO
        from reportlab.lib.utils import ImageReader
        if not image_b64:
            return False
        # Handle data URI prefix
        if image_b64.startswith('data:'):
            header, data = image_b64.split(',', 1)
            img_bytes = base64.b64decode(data)
        elif image_b64.startswith('http'):
            # Download remote image
            import requests as _req
            resp = _req.get(image_b64, timeout=15)
            img_bytes = resp.content
        else:
            # Raw base64
            # Strip any whitespace/newlines that might break decoding
            clean_b64 = image_b64.strip().replace('\n', '').replace('\r', '').replace(' ', '')
            img_bytes = base64.b64decode(clean_b64)
        img = ImageReader(BytesIO(img_bytes))
        if border:
            bc = hex_to_color(border_color)
            c.setFillColor(bc)
            if corner_radius > 0:
                c.roundRect(x - border_width, y - border_width, w + 2*border_width, h + 2*border_width, corner_radius, fill=1, stroke=0)
            else:
                c.rect(x - border_width, y - border_width, w + 2*border_width, h + 2*border_width, fill=1, stroke=0)
        c.drawImage(img, x, y, w, h, preserveAspectRatio=True, mask='auto')
        return True
    except Exception as e:
        print(f"  [WARN] Image render error: {e}")
        import traceback
        traceback.print_exc()
        return False

def draw_text(c, text, x, y, font_name=None, font_size=12, color_hex='#333333', align='right', max_width=None):
    """Draw a single line of text with optional auto-shrink to fit max_width.
    If text still overflows at the minimum font size (5pt), hand off to draw_text_wrapped."""
    if font_name is None:
        font_name = ARABIC_FONT
    c.setFillColor(hex_to_color(color_hex))
    shaped = reshape_arabic(text)
    if max_width and max_width > 0:
        while font_size > 5:
            w = pdfmetrics.stringWidth(shaped, font_name, font_size)
            if w <= max_width:
                break
            font_size -= 0.5
        if pdfmetrics.stringWidth(shaped, font_name, font_size) > max_width:
            return draw_text_wrapped(c, text, x, y, font_name, font_size, color_hex,
                                     align, max_width)
    c.setFont(font_name, font_size)
    if align == 'right':
        w = pdfmetrics.stringWidth(shaped, font_name, font_size)
        c.drawString(x - w, y, shaped)
    elif align == 'center':
        c.drawCentredString(x, y, shaped)
    else:
        c.drawString(x, y, shaped)


def draw_text_wrapped(c, text, x, y, font_name=None, font_size=12, color_hex='#333333',
                      align='right', max_width=None, line_height=None, max_lines=None,
                      max_height=None):
    """Draw text that wraps to multiple lines, with auto-shrink to never overflow.

    CRITICAL: Arabic text is reshaped AS A WHOLE first to preserve ligatures,
    then wrapped by measuring the shaped text width. Each line is drawn with
    reshape_arabic() (bidi) + drawString for correct RTL layout.

    Returns the y-coordinate below the last rendered line.
    """
    if font_name is None:
        font_name = ARABIC_FONT
    if max_width is None:
        max_width = PAGE_W - 2 * MARGIN
    c.setFillColor(hex_to_color(color_hex))
    if not text:
        return y

    # Step 1: Reshape the FULL text to preserve Arabic ligatures
    shaped_text = reshape_arabic_for_rtl(text)

    def _wrap_at_size(sz, lh):
        """Wrap shaped text into lines that fit within max_width."""
        # Split the SHAPED text by spaces — ligatures are already formed
        words = shaped_text.split()
        lines_out = []
        cur = ""
        for word in words:
            test = (cur + " " + word).strip() if cur else word
            if pdfmetrics.stringWidth(test, font_name, sz) <= max_width:
                cur = test
            else:
                if cur:
                    lines_out.append(cur)
                # If single word is too wide, force it on its own line
                cur = word
        if cur:
            lines_out.append(cur)
        if not lines_out:
            lines_out = [shaped_text]
        # Apply max_lines hard-cap
        if max_lines and len(lines_out) > max_lines:
            lines_out = lines_out[:max_lines]
        # Apply max_height: shrink lh if needed so all lines fit
        total_h = len(lines_out) * lh
        if max_height and total_h > max_height and len(lines_out) > 0:
            lh = max_height / len(lines_out)
        return lines_out, lh

    # Iteratively try shrinking font until everything fits
    current_size = font_size
    best_lines = None
    best_lh = None
    while current_size >= 5:
        lh = line_height if line_height else current_size * 1.45
        lines_out, final_lh = _wrap_at_size(current_size, lh)
        total_h = len(lines_out) * final_lh
        if max_height is None or total_h <= max_height:
            best_lines = lines_out
            best_lh = final_lh
            break
        current_size -= 0.5

    # Fallback: use whatever we got at 5pt
    if best_lines is None:
        lh = line_height if line_height else current_size * 1.45
        best_lines, best_lh = _wrap_at_size(current_size, lh)

    c.setFont(font_name, current_size if current_size >= 5 else 5)
    cur_y = y
    for line in best_lines:
        if align == 'right':
            w = pdfmetrics.stringWidth(line, font_name, current_size if current_size >= 5 else 5)
            c.drawString(x - w, cur_y, line)
        elif align == 'center':
            c.drawCentredString(x, cur_y, line)
        else:
            c.drawString(x, cur_y, line)
        cur_y -= best_lh
    return cur_y


# ─── IMAGE RESOLVER ──────────────────────────────────────────────────

def resolve_image(slide, image_key):
    """Get base64 image for a slide based on which of the 4 images to use."""
    if not image_key or image_key == 'null':
        return None
    mapping = {
        'cover_image': lambda s: s.get('cover_image_b64') or s.get('image_b64'),
        'facade_right': lambda s: s.get('facade_right_b64'),
        'facade_left': lambda s: s.get('facade_left_b64'),
        'aerial_view': lambda s: s.get('aerial_view_b64'),
        'client_image': lambda s: s.get('client_image_b64'),
    }
    getter = mapping.get(image_key)
    return getter(slide) if getter else None


# ─── DECORATIVE ELEMENT RENDERERS ─────────────────────────────────────

def _render_decorations(c, d):
    elements = d.get('decorative_elements', [])
    for el in elements:
        etype = el.get('type', '')
        if etype == 'circle':
            draw_circle(c, el.get('x_pct', 0.5)*PAGE_W, el.get('y_pct', 0.5)*PAGE_H,
                       el.get('r_mm', 40)*mm, el.get('color', '#C4A35A'), el.get('alpha', 0.1))
        elif etype == 'stripe':
            draw_diagonal_stripe(c, el.get('color', '#C4A35A'), el.get('position', 'top-right'),
                                  el.get('width_mm', 100), el.get('depth_mm', 180))
        elif etype == 'line':
            draw_line(c, el.get('x1_pct', 0)*PAGE_W, el.get('y1_pct', 0)*PAGE_H,
                     el.get('x2_pct', 1)*PAGE_W, el.get('y2_pct', 1)*PAGE_H,
                     el.get('color', '#C4A35A'), el.get('width', 1))
        elif etype == 'dot_grid':
            draw_dot_grid(c, el.get('spacing_mm', 15)*mm, el.get('dot_r_mm', 0.6)*mm,
                         el.get('color', '#7A0C0C'), el.get('alpha', 0.08))
        elif etype == 'glow':
            draw_radial_glow(c, el.get('x_pct', 0.5)*PAGE_W, el.get('y_pct', 0.5)*PAGE_H,
                             el.get('radius_mm', 80)*mm, el.get('color', '#C4A35A'), el.get('alpha', 0.12))
        elif etype == 'rect':
            draw_rect(c, el.get('x_pct', 0)*PAGE_W, el.get('y_pct', 0)*PAGE_H,
                     el.get('w_mm', 50)*mm, el.get('h_mm', 50)*mm,
                     el.get('color', '#C4A35A'), el.get('radius', 0), el.get('alpha', 0.1))
        elif etype == 'arch_pattern':
            _draw_arch_pattern(c, el)
        elif etype == 'corner_accent':
            _draw_corner_accent(c, el)
        elif etype == 'frame_lines':
            _draw_frame_lines(c, el)

def _draw_arch_pattern(c, el):
    style = el.get('style', 'building')
    color = el.get('color', '#7A0C0C')
    alpha = el.get('alpha', 0.05)
    col = hex_to_color(color)
    c.saveState()
    c.setFillColorRGB(col.red, col.green, col.blue, alpha)
    c.setStrokeColorRGB(col.red, col.green, col.blue, alpha)
    c.setLineWidth(0.3)
    if style == 'building':
        sp = 35*mm; x = 0
        while x < PAGE_W: c.line(x, 0, x, PAGE_H); x += sp
        y = 0
        while y < PAGE_H: c.line(0, y, PAGE_W, y); y += sp*0.6
    elif style == 'grid':
        sp = 18*mm; x = 0
        while x < PAGE_W: c.line(x, 0, x, PAGE_H); x += sp
        y = 0
        while y < PAGE_H: c.line(0, y, PAGE_W, y); y += sp
    elif style == 'circles':
        cx, cy = PAGE_W*0.7, PAGE_H*0.3; r = 30*mm
        for i in range(6): c.circle(cx, cy, r+i*25*mm, fill=0, stroke=1)
    elif style == 'diamonds':
        sp = 40*mm; x = 0
        while x < PAGE_W:
            y = 0
            while y < PAGE_H:
                s = 8*mm; c.saveState(); c.translate(x,y); c.rotate(45)
                c.rect(-s/2,-s/2,s,s,fill=0,stroke=1); c.restoreState()
                y += sp
            x += sp
    c.restoreState()
