

def _font_face_css():
    faces = []
    font_files = {
        'TheSansArabic-Light': ('TheSansArabic-Light', 'TheSansArabic-Light.otf'),
        'TheSansArabic-Bold': ('TheSansArabic-Bold', 'BahijTheSansArabic-Bold.ttf'),
    }
    for family, (name, filename) in font_files.items():
        fp = os.path.join(FONT_DIR, filename)
        if os.path.exists(fp):
            uri = Path(fp).as_uri()
            faces.append(f"""
@font-face {{
    font-family: '{name}';
    src: url('{uri}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}""")
    return '\n'.join(faces)


def _base_css():
    return f"""
@page {{
    size: 1280px 720px;
    margin: 0;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
{_font_face_css()}
.slide {{
    width: 1280px;
    height: 720px;
    direction: rtl;
    unicode-bidi: bidi-override;
    font-family: 'TheSansArabic-Light', 'TheSansArabic-Bold', Tahoma, Arial, sans-serif;
    position: relative;
    overflow: hidden;
    page-break-after: always;
    page-break-inside: avoid;
}}
.slide:last-child {{
    page-break-after: auto;
}}
.slide-content {{
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    display: flex;
    flex-direction: column;
}}
img {{
    max-width: 100%;
    max-height: 100%;
    object-fit: cover;
}}
"""


def _hex_to_rgba(hex_color, alpha=1.0):
    if not hex_color:
        return f'rgba(51,51,51,{alpha})'
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'rgba({r},{g},{b},{alpha})'
    except:
        return f'rgba(51,51,51,{alpha})'


def _lighten(hex_color, amount=0.2):
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    try:
        r = min(255, int(h[0:2], 16) + int(amount * 255))
        g = min(255, int(h[2:4], 16) + int(amount * 255))
        b = min(255, int(h[4:6], 16) + int(amount * 255))
        return f'#{r:02X}{g:02X}{b:02X}'
    except:
        return hex_color


def _resolve_image(slide, image_key):
    mapping = {
        'cover_image': lambda s: s.get('cover_image_b64') or s.get('image_b64'),
        'facade_right': lambda s: s.get('facade_right_b64'),
        'facade_left': lambda s: s.get('facade_left_b64'),
        'aerial_view': lambda s: s.get('aerial_view_b64'),
        'client_image': lambda s: s.get('client_image_b64'),
    }
    getter = mapping.get(image_key)
    return getter(slide) if getter else None


def _img_tag(img_b64, style=''):
    if not img_b64:
        return ''
    if img_b64.startswith('data:'):
        src = img_b64
    elif img_b64.startswith('http'):
        src = img_b64
    else:
        src = f'data:image/png;base64,{img_b64}'
    return f'<img src="{src}" style="{style}" />'


def _background_css(d):
    style = d.get('background_style', 'solid')
    bg = d.get('bg_color', '#FFFFFF')
    primary = d.get('primary_color', '#7A0C0C')
    secondary = d.get('secondary_color', '#C4A35A')

    if style == 'solid':
        return f'background-color: {bg};'
    elif style == 'gradient_v':
        top = d.get('gradient_top_color', primary)
        bot = d.get('gradient_bottom_color', secondary)
        return f'background: linear-gradient(180deg, {top} 0%, {bot} 100%);'
    elif style == 'gradient_h':
        left = d.get('gradient_left_color', secondary)
        right = d.get('gradient_right_color', primary)
        return f'background: linear-gradient(90deg, {left} 0%, {right} 100%);'
    elif style == 'radial_glow':
        gx = d.get('glow_x_pct', 0.5) * 100
        gy = d.get('glow_y_pct', 0.5) * 100
        gc = d.get('glow_color', primary)
        return f'background: radial-gradient(circle at {gx}% {gy}%, {_hex_to_rgba(gc, 0.25)} 0%, {bg} 70%);'
    elif style == 'split':
        sd = d.get('split_direction', 'horizontal')
        sp = d.get('split_position_pct', 0.35) * 100
        if sd == 'horizontal':
            return f'background: linear-gradient(180deg, {primary} {100-sp}%, {bg} {100-sp}%, {bg} 100%);'
        else:
            return f'background: linear-gradient(90deg, {primary} {sp}%, {bg} {sp}%, {bg} 100%);'
    elif style == 'wave':
        wc = d.get('wave_color', primary)
        return f'background: linear-gradient(180deg, {bg} 0%, {bg} 55%, {_hex_to_rgba(wc, 0.15)} 65%, {bg} 75%);'
    elif style == 'dark':
        return f'background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);'
    elif style == 'geometric':
        return f'background-color: {bg};'
    else:
        return f'background-color: {bg};'


def _decorations_css(d):
    elements = d.get('decorative_elements', [])
    css_parts = []
    for i, el in enumerate(elements):
        etype = el.get('type', '')
        if etype == 'circle':
            x = el.get('x_pct', 0.5) * 100
            y = el.get('y_pct', 0.5) * 100
            r = el.get('r_mm', 40) * 3.78
            color = el.get('color', '#C4A35A')
            alpha = el.get('alpha', 0.1)
            css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    left: {x}%; top: {y}%;
    width: {r*2}pt; height: {r*2}pt;
    border-radius: 50%;
    background: {_hex_to_rgba(color, alpha)};
    transform: translate(-50%, -50%);
    pointer-events: none;
}}""")
        elif etype == 'stripe':
            pos = el.get('position', 'top-right')
            w = el.get('width_mm', 100) * 3.78
            h = el.get('depth_mm', 180) * 3.78
            color = el.get('color', '#C4A35A')
            alpha = el.get('alpha', 0.1)
            bg = _hex_to_rgba(color, alpha)
            if pos == 'top-right':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    right: 0; top: 0;
    width: {w}pt; height: {h}pt;
    background: {bg};
    clip-path: polygon(100% 0, 100% 100%, calc(100% - {w}pt) 0);
    pointer-events: none;
}}""")
            elif pos == 'bottom-left':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    left: 0; bottom: 0;
    width: {w}pt; height: {h}pt;
    background: {bg};
    clip-path: polygon(0 100%, 0 0, {w}pt 100%);
    pointer-events: none;
}}""")
            elif pos == 'top-left':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    left: 0; top: 0;
    width: {w}pt; height: {h}pt;
    background: {bg};
    clip-path: polygon(0 0, 0 {h}pt, {w}pt 0);
    pointer-events: none;
}}""")
            elif pos == 'bottom-right':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    right: 0; bottom: 0;
    width: {w}pt; height: {h}pt;
    background: {bg};
    clip-path: polygon(100% 100%, 100% calc(100% - {h}pt), calc(100% - {w}pt) 100%);
    pointer-events: none;
}}""")
        elif etype == 'glow':
            x = el.get('x_pct', 0.5) * 100
            y = el.get('y_pct', 0.5) * 100
            r = el.get('radius_mm', 80) * 3.78
            color = el.get('color', '#C4A35A')
            alpha = el.get('alpha', 0.12)
            css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    left: {x}%; top: {y}%;
    width: {r*2}pt; height: {r*2}pt;
    border-radius: 50%;
    background: radial-gradient(circle, {_hex_to_rgba(color, alpha)} 0%, transparent 70%);
    transform: translate(-50%, -50%);
    pointer-events: none;
}}""")
        elif etype == 'frame_lines':
            inset = el.get('inset_mm', 10) * 3.78
            color = el.get('color', '#C4A35A')
            alpha = el.get('alpha', 0.15)
            w = el.get('width', 0.5)
            css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    left: {inset}pt; top: {inset}pt;
    right: {inset}pt; bottom: {inset}pt;
    border: {w}px solid {_hex_to_rgba(color, alpha)};
    pointer-events: none;
}}""")
        elif etype == 'corner_accent':
            pos = el.get('position', 'bottom-left')
            size = el.get('size_mm', 40) * 3.78
            color = el.get('color', '#C4A35A')
            w = el.get('width', 1.5)
            border_style = f'{w}px solid {color}'
            if pos == 'bottom-left':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    left: 0; bottom: 0;
    width: {size}pt; height: {size}pt;
    border-left: {border_style};
    border-bottom: {border_style};
    pointer-events: none;
}}""")
            elif pos == 'top-right':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    right: 0; top: 0;
    width: {size}pt; height: {size}pt;
    border-right: {border_style};
    border-top: {border_style};
    pointer-events: none;
}}""")
            elif pos == 'top-left':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    left: 0; top: 0;
    width: {size}pt; height: {size}pt;
    border-left: {border_style};
    border-top: {border_style};
    pointer-events: none;
}}""")
            elif pos == 'bottom-right':
                css_parts.append(f"""
.deco-{i} {{
    position: absolute;
    right: 0; bottom: 0;
    width: {size}pt; height: {size}pt;
    border-right: {border_style};
    border-bottom: {border_style};
    pointer-events: none;
}}""")
    return '\n'.join(css_parts)


def _decorations_html(d):
    elements = d.get('decorative_elements', [])
    parts = []
    for i, el in enumerate(elements):
        parts.append(f'<div class="deco-{i}"></div>')
    return '\n'.join(parts)


def _get_logo_data_uri():
    try:
        from pathlib import Path
        project_root = Path(__file__).resolve().parent
        logo_path = os.path.join(str(project_root), 'assets', 'logo.png')
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
            return f"data:image/png;base64,{encoded}"
    except Exception as e:
        print(f"[PDF Logo Load Error] {e}")
    return ""


def _header_footer_html(slide, d, num, total, show_header=True):
    if not show_header:
        return '', ''
    primary = d.get('primary_color', '#7A0C0C')
    title = slide.get('title', '')
    project_name = slide.get('projectName', '')

    header = f"""
<div style="position:absolute;top:0;left:0;right:0;height:32pt;padding:8pt 30pt;display:flex;justify-content:space-between;align-items:center;z-index:10;">
    <span style="font-size:9pt;font-weight:700;color:{primary};">Landloom</span>
    <span style="font-size:8pt;color:#888;">دراسة جدوى |Brainscape| اقتصادية العقار</span>
</div>
<div style="position:absolute;top:32pt;left:30pt;right:30pt;height:1px;background:{primary};opacity:0.15;z-index:10;"></div>
"""
    footer = f"""
<div style="position:absolute;bottom:0;left:0;right:0;height:22pt;padding:0 30pt;display:flex;justify-content:space-between;align-items:center;border-top:1px solid #EEE;z-index:10;">
    <span style="font-size:7pt;color:#AAA;">{project_name}</span>
    <span style="font-size:7pt;color:#AAA;">Landloom | مشاريع الأقتصادية العقار</span>
    <span style="display:inline-flex;align-items:center;justify-content:center;width:16pt;height:16pt;border-radius:50%;background:{primary};color:#FFF;font-size:8pt;font-weight:700;">{num}</span>
</div>
"""
    return header, footer


# ════════════════════════════════════════════════════════════════════
# SLIDE TYPE RENDERERS
# ════════════════════════════════════════════════════════════════════

def _render_cover(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#FFFFFF')
    layout = d.get('layout', 'centered')
    title = slide.get('title', '')
    subtitle = slide.get('subtitle', '')
    image_to_use = d.get('image_to_use') or slide.get('image_to_use')
    img = _resolve_image(slide, image_to_use)

    overlay = ''
    img_style = 'position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;'
    if img:
        overlay = f'<div style="position:absolute;top:0;left:0;right:0;bottom:0;">{_img_tag(img, img_style)}<div style="position:absolute;top:0;left:0;right:0;bottom:0;background:{_hex_to_rgba(primary, 0.55)};"></div></div>'

    if layout in ('centered', 'full_bleed'):
        return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {overlay}
    <div class="slide-content" style="justify-content:center;align-items:center;text-align:center;z-index:5;padding:40pt;">
        <h1 style="font-size:30pt;font-weight:700;color:{text_c};line-height:1.4;max-width:80%;">{title}</h1>
        <div style="width:80pt;height:2.5pt;background:{accent};margin:12pt auto;"></div>
        {'<p style="font-size:14pt;color:' + _lighten(text_c, 0.2) + ';margin-top:8pt;">' + subtitle + '</p>' if subtitle else ''}
    </div>
</div>"""
    elif layout == 'split_rl':
        return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    <div style="position:absolute;top:0;left:0;width:45%;height:100%;{_background_css(d)}">
        {_img_tag(img, 'width:100%;height:100%;object-fit:cover;') if img else ''}
    </div>
    <div style="position:absolute;top:0;right:0;width:55%;height:100%;background:{primary};display:flex;flex-direction:column;justify-content:center;padding:20pt 30pt;">
        <h1 style="font-size:26pt;font-weight:700;color:{text_c};line-height:1.4;">{title}</h1>
        <div style="width:60pt;height:2pt;background:{accent};margin:10pt 0;"></div>
        {'<p style="font-size:13pt;color:' + _lighten(accent, 0.3) + ';">' + subtitle + '</p>' if subtitle else ''}
    </div>
</div>"""
    return ''


def _render_closing(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#FFFFFF')
    title = slide.get('title', 'شكراً لكم')
    subtitle = slide.get('subtitle', '')
    contact = slide.get('contact', '')
    image_to_use = d.get('image_to_use') or slide.get('image_to_use')
    img = _resolve_image(slide, image_to_use)

    overlay = ''
    if img:
        overlay = f'<div style="position:absolute;top:0;left:0;right:0;bottom:0;">{_img_tag(img, "width:100%;height:100%;object-fit:cover;")}<div style="position:absolute;top:0;left:0;right:0;bottom:0;background:{_hex_to_rgba(primary, 0.6)};"></div></div>'

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {overlay}
    <div class="slide-content" style="justify-content:center;align-items:center;text-align:center;z-index:5;padding:40pt;">
        <h1 style="font-size:36pt;font-weight:700;color:{text_c};line-height:1.4;">{title}</h1>
        <div style="width:70pt;height:1.5pt;background:{accent};margin:12pt auto;"></div>
        {'<p style="font-size:15pt;color:' + _lighten(text_c, 0.3) + ';margin-top:8pt;">' + subtitle + '</p>' if subtitle else ''}
        {'<p style="font-size:12pt;color:' + accent + ';margin-top:30pt;">' + contact + '</p>' if contact else ''}
        <p style="font-size:9pt;color:' + _lighten(text_c, 0.5) + ';margin-top:30pt;">Landloom</p>
    </div>
</div>"""


def _render_content(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    layout = d.get('layout', 'split_rl')
    title_style = d.get('title_style', 'top_bar')
    card_style = d.get('card_style', 'rounded_shadow')
    bullet_style = d.get('bullet_style', 'diamond')
    title = slide.get('title', '')
    subtitle = slide.get('subtitle', '')
    bullets = slide.get('bullets', [])
    content_html = slide.get('content', '')
    image_to_use = d.get('image_to_use') or slide.get('image_to_use')
    img = _resolve_image(slide, image_to_use)

    header, footer = _header_footer_html(slide, d, num, total)

    if layout == 'dashboard':
        return _render_dashboard_content(slide, d, num, total)

    title_html = ''
    content_top = '34pt'
    if title_style == 'top_bar':
        title_html = f"""
<div style="position:absolute;top:0;left:0;right:0;height:22pt;background:{primary};z-index:5;">
    <div style="position:absolute;bottom:0;left:0;right:0;height:1.2pt;background:{accent};"></div>
    <div style="position:absolute;top:6pt;right:20pt;left:40pt;">
        <span style="font-size:18pt;font-weight:700;color:#FFF;">{title}</span>
    </div>
</div>"""
        content_top = '30pt'
    elif title_style == 'side_accent':
        title_html = f"""
<div style="position:absolute;top:0;right:0;width:5pt;height:100%;background:{primary};z-index:5;"></div>
<div style="position:absolute;top:14pt;right:12pt;left:20pt;z-index:5;">
    <span style="font-size:20pt;font-weight:700;color:{primary};">{title}</span>
    <div style="width:100%;height:1.5pt;background:{accent};margin-top:4pt;"></div>
</div>"""
        content_top = '34pt'
    elif title_style == 'floating_card':
        title_html = f"""
<div style="position:absolute;top:14pt;left:20pt;right:20pt;height:22pt;background:#FFF;border-radius:4pt;z-index:5;display:flex;align-items:center;padding:0 10pt;box-shadow:0 2pt 4pt rgba(0,0,0,0.1);">
    <div style="width:4pt;height:100%;background:{primary};border-radius:4pt 0 0 4pt;position:absolute;right:0;top:0;"></div>
    <span style="font-size:18pt;font-weight:700;color:{primary};margin-right:8pt;">{title}</span>
</div>"""
        content_top = '42pt'

    subtitle_html = ''
    if subtitle:
        subtitle_html = f'<div style="position:absolute;top:{content_top};right:20pt;left:20pt;z-index:5;"><span style="font-size:10pt;color:#888;">{subtitle}</span></div>'
        content_top = str(int(content_top.replace('pt', '')) + 10) + 'pt'

    img_html = ''
    text_area_style = 'position:absolute;top:' + content_top + ';left:20pt;right:20pt;bottom:24pt;z-index:5;'
    if layout == 'split_rl' and img:
        iw = 200
        img_html = f'<div style="position:absolute;top:{content_top};left:20pt;width:{iw}pt;bottom:24pt;z-index:5;display:flex;align-items:center;justify-content:center;background:#FFF;border-radius:3pt;box-shadow:0 1pt 3pt rgba(0,0,0,0.08);padding:6pt;">{_img_tag(img, "max-width:100%;max-height:100%;object-fit:contain;border-radius:2pt;")}</div>'
        text_area_style = f'position:absolute;top:{content_top};left:230pt;right:20pt;bottom:24pt;z-index:5;'
    elif layout == 'split_lr' and img:
        iw = 200
        img_html = f'<div style="position:absolute;top:{content_top};right:20pt;width:{iw}pt;bottom:24pt;z-index:5;display:flex;align-items:center;justify-content:center;background:#FFF;border-radius:3pt;box-shadow:0 1pt 3pt rgba(0,0,0,0.08);padding:6pt;">{_img_tag(img, "max-width:100%;max-height:100%;object-fit:contain;border-radius:2pt;")}</div>'
        text_area_style = f'position:absolute;top:{content_top};left:20pt;right:230pt;bottom:24pt;z-index:5;'

    card_bg = ''
    if card_style == 'rounded_shadow':
        card_bg = f'background:#FFF;border-radius:4pt;box-shadow:0 2pt 6pt rgba(0,0,0,0.08);padding:16pt;'
    elif card_style == 'glass':
        card_bg = f'background:rgba(255,255,255,0.85);border-radius:4pt;backdrop-filter:blur(8pt);padding:16pt;'
    elif card_style == 'flat_border':
        card_bg = f'border:1pt solid {accent};border-radius:3pt;padding:16pt;'

    bullets_html = ''
    if bullets:
        bullet_markers = {
            'diamond': f'<span style="display:inline-block;width:6pt;height:6pt;background:{accent};transform:rotate(45deg);margin-left:6pt;flex-shrink:0;"></span>',
            'circle': f'<span style="display:inline-block;width:6pt;height:6pt;border-radius:50%;background:{accent};margin-left:6pt;flex-shrink:0;"></span>',
            'bar': f'<span style="display:inline-block;width:10pt;height:4pt;background:{accent};border-radius:2pt;margin-left:6pt;flex-shrink:0;"></span>',
        }
        marker = bullet_markers.get(bullet_style, bullet_markers['diamond'])
        items = ''.join(f'<li style="display:flex;align-items:flex-start;margin-bottom:6pt;font-size:11pt;color:{text_c};line-height:1.6;">{marker}<span>{b}</span></li>' for b in bullets[:12])
        bullets_html = f'<ul style="list-style:none;padding:0;direction:rtl;unicode-bidi:normal;">{items}</ul>'
    elif content_html:
        clean = re.sub(r'<[^>]+>', '\n', str(content_html))
        lines = [l.strip() for l in clean.split('\n') if l.strip()]
        bullets_html = '<br>'.join(f'<span style="font-size:10pt;color:{text_c};line-height:1.8;">{l}</span>' for l in lines[:14])

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {title_html}
    {subtitle_html}
    <div style="{text_area_style}">
        <div style="{card_bg}">
            {bullets_html}
        </div>
    </div>
    {img_html}
    {header}
    {footer}
</div>"""
