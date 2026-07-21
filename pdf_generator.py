"""
PDF Design Engine — GLM decides the design, this code renders it.
4 project images only, universal header/footer, decorative elements, icons.
"""

import os
import re
import math
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import mm, cm, inch
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus import Paragraph, Frame, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from config.settings import PROJECT_ROOT

PAGE_W, PAGE_H = 13.333 * inch, 7.5 * inch  # 960×540 pt (16:9)
MARGIN = 20 * mm

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
    shaped = reshape_arabic("منافع الاقتصادية")
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
    draw_text(c, 'منافع الاقتصادية للعقار', PAGE_W-MARGIN-2*mm, 6*mm, ARABIC_FONT, 6, '#999999', 'right')
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
    draw_text(c, 'شركة منافع الاقتصادية', PAGE_W/2, 18*mm, ARABIC_FONT, 9,
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
    c.setTitle(project_name); c.setAuthor('منافع الاقتصادية')
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
        {'type':'closing','title':'شكراً لثقتكم','subtitle':'منافع الاقتصادية','contact':'info@manafe.com',
         'design':{'mood':'dramatic','background_style':'gradient_v','primary_color':'#1a3a52',
                   'secondary_color':'#0d1f2d','accent_color':'#d4a84b','bg_color':'#1a3a52',
                   'text_color':'#FFFFFF','layout':'centered',
                   'decorative_elements':[{'type':'circle','x_pct':0.15,'y_pct':0.2,'r_mm':100,'color':'#d4a84b','alpha':0.06},
                                         {'type':'stripe','position':'top-left','width_mm':160,'depth_mm':200}]}}
    ]
    generate_pdf(test_slides, 'test_design', 'test_output.pdf')
    print("Test PDF generated with GLM-driven designs!")
