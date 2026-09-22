

def _render_dashboard_content(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    sections = slide.get('sections', [])
    bullets = slide.get('bullets', [])

    header, footer = _header_footer_html(slide, d, num, total)

    title_html = f"""
<div style="position:absolute;top:42pt;right:30pt;left:30pt;z-index:5;display:flex;align-items:center;gap:8pt;">
    <div style="width:4pt;height:22pt;background:{primary};border-radius:2pt;"></div>
    <span style="font-size:16pt;font-weight:700;color:{primary};">{title}</span>
</div>"""

    right_cards = ''
    left_cards = ''

    if sections:
        for si, sec in enumerate(sections[:4]):
            sec_title = sec.get('title', '')
            items = sec.get('items', sec.get('bullets', []))
            sec_type = sec.get('type', 'list')
            tag = sec.get('tag', '')
            tag_color = sec.get('tag_color', accent)

            items_html = ''
            if sec_type == 'units':
                for item in items[:4]:
                    unit_name = item.get('name', item.get('label', ''))
                    area = item.get('area', '')
                    price = item.get('price', '')
                    area_html = f'<div style="font-size:8pt;color:#999;margin-top:2pt;">{area}</div>' if area else ''
                    price_html = f'<div style="font-size:9pt;color:{primary};font-weight:700;margin-top:2pt;">{price}</div>' if price else ''
                    items_html += f"""
<div style="background:#FBFAF8;border-radius:6pt;padding:8pt 10pt;margin-bottom:6pt;border:1px solid #F0ECE8;">
    <div style="font-size:9pt;font-weight:700;color:{text_c};">{unit_name}</div>
    {area_html}
    {price_html}
</div>"""
            elif sec_type == 'risk':
                for item in items[:3]:
                    risk_label = item.get('label', item) if isinstance(item, dict) else str(item)
                    risk_tag = item.get('tag', '') if isinstance(item, dict) else ''
                    risk_tag_color = item.get('tag_color', '#E8A838') if isinstance(item, dict) else tag_color
                    tag_html = f'<span style="font-size:7pt;color:{risk_tag_color};background:{_hex_to_rgba(risk_tag_color, 0.12)};padding:2pt 6pt;border-radius:3pt;margin-right:6pt;">{risk_tag}</span>' if risk_tag else ''
                    items_html += f"""
<div style="display:flex;align-items:center;justify-content:space-between;padding:5pt 0;border-bottom:1px solid #F0ECE8;">
    <div style="font-size:9pt;color:{text_c};">{tag_html}{risk_label}</div>
</div>"""
            else:
                for item in items[:6]:
                    item_text = item.get('label', item) if isinstance(item, dict) else str(item)
                    items_html += f"""
<div style="display:flex;align-items:center;margin-bottom:5pt;">
    <div style="width:5pt;height:5pt;border-radius:50%;background:{accent};margin-left:8pt;flex-shrink:0;"></div>
    <span style="font-size:9pt;color:{text_c};line-height:1.6;">{item_text}</span>
</div>"""

            tag_html = f'<span style="font-size:7pt;color:#FFF;background:{tag_color};padding:2pt 8pt;border-radius:3pt;margin-right:6pt;">{tag}</span>' if tag else ''

            section_html = f"""
<div style="background:#FFF;border-radius:8pt;padding:12pt;box-shadow:0 1pt 6pt rgba(0,0,0,0.04);margin-bottom:10pt;">
    <div style="display:flex;align-items:center;margin-bottom:8pt;">
        {tag_html}
        <span style="font-size:11pt;font-weight:700;color:{primary};">{sec_title}</span>
    </div>
    {items_html}
</div>"""

            if si < 2:
                right_cards += section_html
            else:
                left_cards += section_html

    if not sections and bullets:
        items_html = ''
        for b in bullets[:6]:
            items_html += f"""
<div style="display:flex;align-items:center;margin-bottom:5pt;">
    <div style="width:5pt;height:5pt;border-radius:50%;background:{accent};margin-left:8pt;flex-shrink:0;"></div>
    <span style="font-size:9pt;color:{text_c};line-height:1.6;">{b}</span>
</div>"""
        right_cards = f"""
<div style="background:#FFF;border-radius:8pt;padding:12pt;box-shadow:0 1pt 6pt rgba(0,0,0,0.04);">
    {items_html}
</div>"""

    col_w = (PAGE_W_PT - 60 - 16) / 2

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {title_html}
    <div style="position:absolute;top:78pt;right:30pt;width:{col_w}pt;bottom:28pt;z-index:5;overflow:hidden;">
        {right_cards}
    </div>
    <div style="position:absolute;top:78pt;left:30pt;width:{col_w}pt;bottom:28pt;z-index:5;overflow:hidden;">
        {left_cards}
    </div>
    {header}
    {footer}
</div>"""


def _render_metrics(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    metrics = slide.get('metrics', [])

    header, footer = _header_footer_html(slide, d, num, total)

    title_html = f"""
<div style="position:absolute;top:42pt;right:30pt;left:30pt;z-index:5;text-align:right;">
    <span style="font-size:16pt;font-weight:700;color:{primary};">{title}</span>
    <div style="width:60pt;height:2pt;background:{accent};margin-top:4pt;border-radius:1pt;"></div>
</div>"""

    cols = min(d.get('metrics_columns', 4), max(len(metrics), 1))
    gap = 16
    card_h = 95
    total_w = PAGE_W_PT - 60
    cw = (total_w - (cols - 1) * gap) / cols
    start_y = 70
    cards_html = ''

    for idx, m in enumerate(metrics):
        col = idx % cols
        x = PAGE_W_PT - 30 - (col + 1) * cw - col * gap
        y = start_y
        label = m.get('label', '')
        value = str(m.get('value', ''))
        subtitle = m.get('subtitle', '')
        subtitle_html = f'<div style="font-size:7pt;color:#999;margin-top:3pt;">{subtitle}</div>' if subtitle else ''

        cards_html += f"""
<div style="position:absolute;left:{x}pt;top:{y}pt;width:{cw}pt;height:{card_h}pt;background:#FFF;border-radius:10pt;box-shadow:0 2pt 12pt rgba(0,0,0,0.06);padding:16pt;display:flex;flex-direction:column;justify-content:space-between;">
    <div>
        <div style="font-size:8pt;color:#888;margin-bottom:2pt;">{label}</div>
        <div style="font-size:22pt;font-weight:700;color:{primary};line-height:1.2;">{value}</div>
        {subtitle_html}
    </div>
</div>"""

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {title_html}
    {cards_html}
    {header}
    {footer}
</div>"""


def _render_table(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    table_data = slide.get('table', [])

    header, footer = _header_footer_html(slide, d, num, total)

    title_bar = f"""
<div style="position:absolute;top:0;left:0;right:0;height:22pt;background:{primary};z-index:5;">
    <div style="position:absolute;bottom:0;left:0;right:0;height:1.2pt;background:{accent};"></div>
    <div style="position:absolute;top:6pt;right:20pt;left:40pt;">
        <span style="font-size:18pt;font-weight:700;color:#FFF;">{title}</span>
    </div>
</div>"""

    rows_html = ''
    if table_data:
        cols = max(len(row) for row in table_data)
        for r, row in enumerate(table_data):
            cells_html = ''
            for ci, cell in enumerate(row):
                tc = '#FFF' if r == 0 else text_c
                fw = '700' if r == 0 else '400'
                fs = '8pt'
                bg_style = ''
                if r == 0:
                    bg_style = f'background:{primary};'
                elif r % 2 == 0:
                    bg_style = f'background:#F5F0EE;'
                cells_html += f'<td style="padding:4pt 6pt;text-align:center;font-size:{fs};font-weight:{fw};color:{tc};{bg_style}border-bottom:1px solid #EEE;">{cell}</td>'
            rows_html += f'<tr>{cells_html}</tr>'

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {title_bar}
    <div style="position:absolute;top:34pt;left:20pt;right:20pt;bottom:24pt;z-index:5;">
        <table style="width:100%;border-collapse:collapse;background:#FFF;border-radius:4pt;overflow:hidden;box-shadow:0 1pt 3pt rgba(0,0,0,0.06);">
            {rows_html}
        </table>
    </div>
    {header}
    {footer}
</div>"""


def _render_section_divider(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#FFFFFF')
    title = slide.get('title', '')
    subtitle = slide.get('subtitle', '')

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    <div class="slide-content" style="justify-content:center;align-items:center;text-align:center;z-index:5;padding:40pt;">
        <h1 style="font-size:30pt;font-weight:700;color:{text_c};line-height:1.4;">{title}</h1>
        <div style="width:100pt;height:2pt;background:{accent};margin:12pt auto;"></div>
        {'<p style="font-size:13pt;color:' + _lighten(accent, 0.2) + ';">' + subtitle + '</p>' if subtitle else ''}
    </div>
</div>"""


def _render_quote(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    quote = slide.get('title', '')
    author = slide.get('subtitle', '')

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    <div class="slide-content" style="justify-content:center;align-items:center;text-align:center;z-index:5;padding:40pt;">
        <span style="font-size:80pt;font-weight:700;color:{accent};line-height:0.5;opacity:0.5;">"</span>
        <p style="font-size:16pt;color:{primary};line-height:1.8;max-width:85%;margin-top:10pt;">{quote}</p>
        <div style="width:100pt;height:1.5pt;background:{accent};margin:16pt auto;"></div>
        {'<p style="font-size:11pt;font-weight:700;color:#888;margin-top:6pt;">' + author + '</p>' if author else ''}
    </div>
</div>"""


def _render_comparison(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    lt = slide.get('subtitle', '')
    rt = str(slide.get('content', ''))[:100] if isinstance(slide.get('content'), str) else ''
    li = slide.get('bullets', [])
    ri = slide.get('metrics', [{'label': '', 'value': m} if isinstance(m, str) else m for m in (slide.get('right_bullets') or [])])

    cww = (PAGE_W_PT - 40 - 8) / 2 - 8
    left_items = ''.join(f'<li style="margin-bottom:6pt;font-size:10pt;color:{text_c};direction:rtl;">• {item if isinstance(item, str) else item.get("label", "")}</li>' for item in li[:8])
    right_items = ''.join(f'<li style="margin-bottom:6pt;font-size:10pt;color:{text_c};direction:rtl;">• {item if isinstance(item, str) else item.get("label", item.get("value", ""))}</li>' for item in ri[:8])

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    <div style="position:absolute;top:14pt;left:20pt;right:20pt;z-index:5;text-align:center;">
        <span style="font-size:18pt;font-weight:700;color:{primary};">{title}</span>
        <div style="width:80pt;height:1.5pt;background:{accent};margin:6pt auto;"></div>
    </div>
    <div style="position:absolute;top:48pt;left:20pt;width:{cww}pt;bottom:24pt;background:#FFF;border-radius:5pt;box-shadow:0 1pt 3pt rgba(0,0,0,0.06);overflow:hidden;z-index:5;">
        <div style="background:{primary};padding:6pt 10pt;border-radius:5pt 5pt 0 0;">
            <span style="font-size:12pt;font-weight:700;color:#FFF;">{lt}</span>
        </div>
        <ul style="list-style:none;padding:10pt;direction:rtl;">{left_items}</ul>
    </div>
    <div style="position:absolute;top:48pt;right:20pt;width:{cww}pt;bottom:24pt;background:#FFF;border-radius:5pt;box-shadow:0 1pt 3pt rgba(0,0,0,0.06);overflow:hidden;z-index:5;">
        <div style="background:{accent};padding:6pt 10pt;border-radius:5pt 5pt 0 0;">
            <span style="font-size:12pt;font-weight:700;color:#FFF;">{rt}</span>
        </div>
        <ul style="list-style:none;padding:10pt;direction:rtl;">{right_items}</ul>
    </div>
</div>"""


def _render_two_column(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    lc = slide.get('content', '')
    rb = slide.get('bullets', [])

    header, footer = _header_footer_html(slide, d, num, total)

    title_bar = f"""
<div style="position:absolute;top:0;left:0;right:0;height:22pt;background:{primary};z-index:5;">
    <div style="position:absolute;top:6pt;right:20pt;left:40pt;">
        <span style="font-size:17pt;font-weight:700;color:#FFF;">{title}</span>
    </div>
</div>"""

    col_w = (PAGE_W_PT - 40 - 8) / 2
    left_lines = ''
    right_lines = ''
    if lc:
        clean = re.sub(r'<[^>]+>', '\n', str(lc))
        lines = [l.strip() for l in clean.split('\n') if l.strip()]
        left_lines = '<br>'.join(f'<span style="font-size:10pt;color:{text_c};line-height:1.8;">{l}</span>' for l in lines[:10])
    if rb:
        right_lines = '<br>'.join(f'<span style="font-size:10pt;color:{text_c};line-height:1.8;">{b}</span>' for b in rb[:10])

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {title_bar}
    <div style="position:absolute;top:32pt;left:20pt;width:{col_w}pt;bottom:24pt;z-index:5;direction:rtl;unicode-bidi:normal;">{left_lines}</div>
    <div style="position:absolute;top:32pt;right:20pt;width:{col_w}pt;bottom:24pt;z-index:5;direction:rtl;unicode-bidi:normal;">{right_lines}</div>
    <div style="position:absolute;top:32pt;left:50%;width:1px;bottom:24pt;background:{accent};opacity:0.3;z-index:5;"></div>
    {header}
    {footer}
</div>"""


def _render_timeline(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', '')
    td = slide.get('table', []) or slide.get('bullets', [])

    header, footer = _header_footer_html(slide, d, num, total)

    title_bar = f"""
<div style="position:absolute;top:0;left:0;right:0;height:22pt;background:{primary};z-index:5;">
    <div style="position:absolute;top:6pt;right:20pt;left:40pt;">
        <span style="font-size:17pt;font-weight:700;color:#FFF;">{title}</span>
    </div>
</div>"""

    items_html = ''
    if td:
        mid_y = PAGE_H_PT / 2
        sp = (PAGE_W_PT - 80) / max(len(td), 1)
        for idx, item in enumerate(td):
            if isinstance(item, dict):
                label = item.get('label', item.get('value', ''))
            elif isinstance(item, list):
                label = item[0] if item else ''
            else:
                label = str(item)
            x = 40 + idx * sp + sp / 2
            items_html += f"""
<div style="position:absolute;left:{x - 10}pt;top:{mid_y - 10}pt;width:20pt;height:20pt;border-radius:50%;background:{primary};z-index:5;"></div>
<div style="position:absolute;left:{x - sp/2}pt;top:{mid_y + 14}pt;width:{sp}pt;text-align:center;z-index:5;">
    <span style="font-size:8pt;font-weight:700;color:{text_c};">{label}</span>
</div>"""

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {title_bar}
    <div style="position:absolute;top:{PAGE_H_PT/2}pt;left:40pt;right:40pt;height:2pt;background:#CCC;z-index:4;"></div>
    {items_html}
    {header}
    {footer}
</div>"""


def _render_image_focus(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    title = slide.get('title', '')
    caption = slide.get('subtitle', '')
    image_to_use = d.get('image_to_use') or slide.get('image_to_use')
    img = _resolve_image(slide, image_to_use)

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    <div style="position:absolute;top:18pt;left:20pt;right:20pt;bottom:40pt;z-index:5;display:flex;align-items:center;justify-content:center;background:#FFF;border-radius:4pt;box-shadow:0 2pt 6pt rgba(0,0,0,0.1);padding:6pt;">
        {_img_tag(img, "max-width:100%;max-height:100%;object-fit:contain;border-radius:3pt;") if img else '<span style="color:#AAA;font-size:14pt;">لا توجد صورة</span>'}
    </div>
    <div style="position:absolute;bottom:12pt;left:20pt;right:20pt;text-align:center;z-index:5;">
        {'<p style="font-size:12pt;color:' + primary + ';">' + caption + '</p>' if caption else ''}
        {'<p style="font-size:14pt;font-weight:700;color:' + primary + ';margin-top:4pt;">' + title + '</p>' if title else ''}
    </div>
</div>"""


def _render_mood_board(slide, d, num, total):
    primary = d.get('primary_color', '#7A0C0C')
    accent = d.get('accent_color', '#C4A35A')
    text_c = d.get('text_color', '#2D2D2D')
    title = slide.get('title', 'المود بورد')

    header, footer = _header_footer_html(slide, d, num, total)

    mb_list = d.get('moodboardImages') or slide.get('moodboardImages') or []
    
    img_cover = slide.get('cover_image_b64') or slide.get('image_b64') or ''
    img_right = slide.get('facade_right_b64') or ''
    img_left = slide.get('facade_left_b64') or ''
    img_aerial = slide.get('aerial_view_b64') or ''

    if not img_cover and len(mb_list) > 0: img_cover = mb_list[0]
    if not img_right and len(mb_list) > 1: img_right = mb_list[1]
    if not img_left and len(mb_list) > 2: img_left = mb_list[2]
    if not img_aerial and len(mb_list) > 3: img_aerial = mb_list[3]

    def _to_src(val):
        if not val:
            return ""
        if val.startswith('data:') or val.startswith('http'):
            return val
        return f"data:image/png;base64,{val}"

    srcs = [
        _to_src(img_cover),
        _to_src(img_right),
        _to_src(img_left),
        _to_src(img_aerial)
    ]
    mb_names = ['Exterior Hero', 'Right Facade', 'Left Facade', 'Aerial View']

    grid_items_html = ""
    for i in range(4):
        src = srcs[i]
        name = mb_names[i]
        if src:
            grid_items_html += f"""
            <div style="border-radius:14px;overflow:hidden;position:relative;box-shadow:0 6px 18px rgba(0,0,0,0.08);background:#f7f4ef;height:100%;">
                <img src="{src}" style="width:100%;height:100%;object-fit:cover;display:block;">
                <div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(0deg,rgba(103,13,12,0.88),rgba(103,13,12,0.6));padding:8px 12px;color:#fff;font-size:12px;font-weight:700;text-align:center;">{name}</div>
            </div>"""
        else:
            grid_items_html += f"""
            <div style="background:#f7f4ef;border:2px dashed #dcd8d0;border-radius:14px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:13px;height:100%;min-height:140px;">{name}</div>"""

    return f"""
<div class="slide" style="{_background_css(d)}">
    {_decorations_html(d)}
    {header}
    <div class="slide-content" style="justify-content:center;align-items:center;z-index:5;padding:20pt 40pt;box-sizing:border-box;display:flex;flex-direction:column;height:100%;">
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:14px;width:100%;flex:1;min-height:0;">
            {grid_items_html}
        </div>
        <div style="margin-top:10px;display:flex;gap:14px;justify-content:center;font-size:11px;color:{primary};font-weight:bold;">
            <span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:12px;background:#670D0C;border-radius:3px;display:inline-block;"></span> عنابي</span>
            <span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:12px;background:#C2A176;border-radius:3px;display:inline-block;"></span> ذهبي</span>
            <span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:12px;background:#F5F0EE;border-radius:3px;display:inline-block;border:1px solid #ccc;"></span> بيج فاخر</span>
        </div>
    </div>
    {footer}
</div>"""


# ════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════

RENDERERS = {
    'cover': _render_cover,
    'closing': _render_closing,
    'content': _render_content,
    'metrics': _render_metrics,
    'table': _render_table,
    'section_divider': _render_section_divider,
    'quote': _render_quote,
    'comparison': _render_comparison,
    'two_column': _render_two_column,
    'timeline': _render_timeline,
    'image_focus': _render_image_focus,
    'mood_board': _render_mood_board,
}


def _default_design(slide_type):
    defaults = {
        'cover': {'mood': 'dramatic', 'background_style': 'gradient_v', 'primary_color': '#7A0C0C',
                  'secondary_color': '#5A0808', 'accent_color': '#C4A35A', 'bg_color': '#7A0C0C',
                  'text_color': '#FFFFFF', 'layout': 'centered', 'title_style': 'large_centered'},
        'closing': {'mood': 'dramatic', 'background_style': 'gradient_v', 'primary_color': '#7A0C0C',
                    'secondary_color': '#5A0808', 'accent_color': '#C4A35A', 'bg_color': '#5A0808',
                    'text_color': '#FFFFFF', 'layout': 'centered', 'title_style': 'large_centered'},
        'content': {'mood': 'modern', 'background_style': 'solid', 'primary_color': '#7A0C0C',
                    'secondary_color': '#C4A35A', 'accent_color': '#F5F0EE', 'bg_color': '#FBFAF8',
                    'text_color': '#2D2D2D', 'layout': 'split_rl', 'title_style': 'top_bar',
                    'card_style': 'rounded_shadow', 'bullet_style': 'diamond'},
        'metrics': {'mood': 'modern', 'background_style': 'solid', 'primary_color': '#7A0C0C',
                    'secondary_color': '#C4A35A', 'accent_color': '#FBF6EE', 'bg_color': '#FBF6EE',
                    'text_color': '#2D2D2D', 'layout': 'cards', 'title_style': 'top_bar', 'metrics_columns': 4},
        'table': {'mood': 'minimal', 'background_style': 'solid', 'primary_color': '#7A0C0C',
                  'secondary_color': '#C4A35A', 'accent_color': '#FAF7F2', 'bg_color': '#FAF7F2',
                  'text_color': '#2D2D2D', 'layout': 'cards', 'title_style': 'top_bar'},
    }
    d = defaults.get(slide_type, defaults['content'])
    d['decorative_elements'] = []
    return d


def _resolve_glm_html(slide, html, num, total):
    if not html:
        return ""

    # Keep exported PDF output aligned with the icon-free presentation contract.
    html = re.sub(r'<svg\b[^>]*>[\s\S]*?</svg\s*>', '', html, flags=re.IGNORECASE)
    html = re.sub(
        r'<(?:i|span|div)\b[^>]*(?:class|id)=["\'][^"\']*(?:icon|emoji|lucide|fa-|material-icons)[^"\']*["\'][^>]*>[\s\S]*?</(?:i|span|div)\s*>',
        '', html, flags=re.IGNORECASE
    )
    html = _ICON_RE.sub('', html)
    
    logo_data_uri = _get_logo_data_uri()
    if logo_data_uri:
        html = html.replace('##LOGO##', logo_data_uri)
    
    img_cover = slide.get('cover_image_b64') or slide.get('image_b64') or ''
    img_right = slide.get('facade_right_b64') or slide.get('image_b64') or ''
    img_left = slide.get('facade_left_b64') or slide.get('image_b64') or ''
    img_aerial = slide.get('aerial_view_b64') or slide.get('image_b64') or ''
    
    def _to_src(val):
        if not val:
            return ""
        if val.startswith('data:') or val.startswith('http'):
            return val
        return f"data:image/png;base64,{val}"

    # Semantic project images mapping
    src_cover = _to_src(img_cover)
    src_right = _to_src(img_right)
    src_left = _to_src(img_left)
    src_aerial = _to_src(img_aerial)

    html = html.replace('##MOODBOARD_IMAGE_1##', src_cover)
    html = html.replace('##MAIN_IMAGE##', src_cover)
    html = html.replace('##IMAGE_COVER##', src_cover)
    html = html.replace('##PROJECT_IMAGE_COVER##', src_cover)
    
    html = html.replace('##MOODBOARD_IMAGE_2##', src_right)
    html = html.replace('##PROJECT_IMAGE_RIGHT##', src_right)
    html = html.replace('##FACADE_RIGHT##', src_right)
    html = html.replace('##IMAGE_FACADE_RIGHT##', src_right)
    
    html = html.replace('##MOODBOARD_IMAGE_3##', src_left)
    html = html.replace('##PROJECT_IMAGE_LEFT##', src_left)
    html = html.replace('##FACADE_LEFT##', src_left)
    html = html.replace('##IMAGE_FACADE_LEFT##', src_left)
    
    html = html.replace('##MOODBOARD_IMAGE_4##', src_aerial)
    html = html.replace('##PROJECT_IMAGE_AERIAL##', src_aerial)
    html = html.replace('##AERIAL_VIEW##', src_aerial)
    html = html.replace('##IMAGE_AERIAL##', src_aerial)
    
    if logo_data_uri:
        html = html.replace('##LOGO##', logo_data_uri)

    # ─── PARITY STRIPPING LOGIC (BeautifulSoup) ───
    title = slide.get('title', '') or ''
    is_cover = (num == 1) or any(w in title.lower() for w in ['غلاف', 'cover'])
    is_closing = (num == total) or any(w in title.lower() for w in ['ختام', 'closing', 'شكراً', 'thanks'])
    is_index = any(w in title.lower() for w in ['فهرس', 'محتويات', 'index', 'toc'])

    if not is_cover and not is_closing:
        try:
            from bs4 import BeautifulSoup
            import re
            
            project_images = [src_cover, src_right, src_left, src_aerial]
            project_images = [img for img in project_images if img]

            def is_project_image(src):
                if not src:
                    return False
                clean_src = src.strip().replace('"', '').replace("'", "")
                clean_src_base64 = re.sub(r'^data:image/[a-zA-Z+.-]+;base64,', '', clean_src)
                
                for p_img in project_images:
                    if not p_img:
                        continue
                    p_img_clean = p_img.strip().replace('"', '').replace("'", "")
                    p_img_clean_base64 = re.sub(r'^data:image/[a-zA-Z+.-]+;base64,', '', p_img_clean)
                    
                    if len(p_img_clean_base64) > 50 and p_img_clean_base64[:50] in clean_src_base64:
                        return True
                    if p_img_clean_base64 in clean_src_base64 or clean_src_base64 in p_img_clean_base64:
                        return True
                return False

            soup = BeautifulSoup(html, 'html.parser')
            is_moodboard = any(w in title.lower() for w in ['مود بورد', 'moodboard', 'لوحة أنماط', 'لوحة الأنماط'])

            # 1. Remove all <img> except logo and (for non-index slides) valid project images
            for img in soup.find_all('img'):
                src = img.get('src', '') or ''
                alt = img.get('alt', '') or ''
                src_lower = src.strip().lower()
                if src_lower.startswith('data:') or src_lower.startswith('blob:'):
                    is_logo = False
                    img_class = img.get('class', '') or ''
                    if isinstance(img_class, list):
                        img_class = ' '.join(img_class)
                    img_id = img.get('id', '') or ''
                    tag_hint = (str(img_class) + ' ' + str(img_id) + ' ' + str(alt)).lower()
                    if any(w in tag_hint for w in ['logo', 'landloom']):
                        is_logo = bool(logo_data_uri and logo_data_uri[:40] in src)
                else:
                    is_logo = (logo_data_uri and logo_data_uri[:40] in src) or any(w in (src + ' ' + alt).lower() for w in ['logo', 'landloom'])
                is_proj = not is_index and is_project_image(src)
                if not is_logo and not is_proj:
                    img.decompose()
                # On moodboard slides, remove project images from the header zone (top 80px)
                elif is_moodboard and is_proj:
                    parent = img.parent
                    is_in_header = False
                    while parent and parent.name:
                        parent_style = parent.get('style', '') or ''
                        if 'header' in (parent.get('class', '') or '').lower() if isinstance(parent.get('class'), list) else 'header' in str(parent.get('class', '')):
                            is_in_header = True
                            break
                        if re.search(r'position\s*:\s*absolute', parent_style, re.IGNORECASE):
                            top_match = re.search(r'top\s*:\s*(\d+)', parent_style, re.IGNORECASE)
                            if top_match and int(top_match.group(1)) < 80:
                                is_in_header = True
                                break
                            break
                        parent = parent.parent
                    if is_in_header:
                        img.decompose()
            
            # 2. Remove all <svg> except logo
            for svg in soup.find_all('svg'):
                svg_class = svg.get('class', '') or ''
                svg_id = svg.get('id', '') or ''
                if isinstance(svg_class, list):
                    svg_class = ' '.join(svg_class)
                svg_text = (svg_class + ' ' + svg_id + ' ' + str(svg)).lower()
                if not any(w in svg_text for w in ['logo', 'landloom']):
                    svg.decompose()
            
            # 3. Remove background/background-image containing url() (except logo and, for non-index slides, valid project images)
            for el in soup.find_all(style=True):
                style = el.get('style', '')
                if 'background' in style:
                    url_match = re.search(r'url\s*\(\s*([^)]+)\s*\)', style, re.IGNORECASE)
                    if url_match:
                        bg_url = url_match.group(1).replace('"', '').replace("'", "").strip()
                        if bg_url.lower().startswith('data:') or bg_url.lower().startswith('blob:'):
                            style_without_urls = re.sub(r'url\s*\([^)]*\)', '', style, flags=re.IGNORECASE).lower()
                            is_logo = any(w in style_without_urls for w in ['logo', 'landloom'])
                        else:
                            is_logo = any(w in style.lower() for w in ['logo', 'landloom'])
                        is_proj = not is_index and is_project_image(bg_url)
                        if not is_logo and not is_proj:
                            new_style = re.sub(r'background(-image)?\s*:\s*url\([^)]*\);?', '', style, flags=re.IGNORECASE)
                            el['style'] = new_style
            
            html = str(soup)
        except Exception as e:
            print(f"Error in backend element stripping: {e}")
        
    if "overflow" not in html[:500].lower():
        html = html.replace('width:1280px', 'width:1280px;overflow:hidden')
        html = html.replace('height:720px', 'height:720px;overflow:hidden')
        
    return html


def generate_pdf(slides, project_name='project', output_path='output.pdf'):
    total = len(slides)
    slides_html = []

    for i, slide in enumerate(slides):
        slide_html = slide.get('glm_html') or slide.get('html')
        if slide_html:
            slide_html = _resolve_glm_html(slide, slide_html, i + 1, total)
        else:
            design = slide.get('design', {})
            slide_type = slide.get('type', 'content')
            if not design or len(design) < 3:
                design = _default_design(slide_type)

            renderer = RENDERERS.get(slide_type, _render_content)
            slide_html = renderer(slide, design, i + 1, total)
        
        if slide_html:
            slides_html.append(slide_html)

    full_html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <style>{_base_css()}</style>
</head>
<body>
{''.join(slides_html)}
</body>
</html>"""

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--font-render-hinting=none'])
        page = browser.new_page()
        page.set_content(full_html, wait_until='networkidle')

        page.evaluate('''() => {
            document.querySelectorAll('.slide *').forEach(el => {
                const s = getComputedStyle(el);
                if (s.boxShadow && s.boxShadow !== 'none') el.style.boxShadow = 'none';
                if (s.filter && s.filter !== 'none') el.style.filter = 'none';
                if (s.backdropFilter && s.backdropFilter !== 'none') el.style.backdropFilter = 'none';
                if (s.opacity !== '1') el.style.opacity = '1';
                if (s.backgroundImage && s.backgroundImage.includes('gradient')) {
                    el.style.backgroundImage = 'none';
                    if (s.backgroundColor && s.backgroundColor !== 'rgba(0, 0, 0, 0)') el.style.background = s.backgroundColor;
                }
            });
        }''')

        page.pdf(
            path=output_path,
            width='1280px',
            height='720px',
            print_background=True,
            margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
        )
        browser.close()
    return output_path


if __name__ == '__main__':
    test_slides = [
        {'type': 'cover', 'title': 'مشروع الواحة السكنية الذكية', 'subtitle': 'دراسة جدوى | الرياض',
         'design': {'mood': 'dramatic', 'background_style': 'gradient_v', 'primary_color': '#7A0C0C',
                    'secondary_color': '#5A0808', 'accent_color': '#C4A35A', 'bg_color': '#7A0C0C',
                    'text_color': '#FFFFFF', 'layout': 'centered', 'title_style': 'large_centered',
                    'decorative_elements': [{'type': 'circle', 'x_pct': 0.9, 'y_pct': 0.15, 'r_mm': 70, 'color': '#C4A35A', 'alpha': 0.08}]}},
        {'type': 'metrics', 'title': 'ملخص المؤشرات الرئيسية',
         'metrics': [
             {'label': 'إجمالي التكلفة الاستثمارية', 'value': '146', 'subtitle': 'مليون ريال | التطوير: 110 مليون'},
             {'label': 'العائد الاستثماري المتوقع (ROI)', 'value': '24.2%', 'subtitle': 'فترة الاسترداد: 4.5 سنوات'},
             {'label': 'معدل الرسملة (Cap Rate)', 'value': '5.8%', 'subtitle': 'قيمة العقار: 220 مليون ريال'},
             {'label': 'إجمالي الربح الصافي المتوقع', 'value': '62', 'subtitle': 'مليون ريال | توقع الدخل الشهري المقدر'}
         ],
         'design': {'mood': 'modern', 'background_style': 'solid', 'primary_color': '#7A0C0C',
                    'secondary_color': '#C4A35A', 'accent_color': '#FBF6EE', 'bg_color': '#FBF6EE',
                    'text_color': '#2D2D2D', 'layout': 'cards', 'title_style': 'top_bar', 'metrics_columns': 4}},
        {'type': 'content', 'title': 'الأداء الشامل وتوزيع المساحات',
         'sections': [
             {'title': 'الإيرادات الشهية السنوية', 'type': 'units', 'items': [
                 {'name': 'دوبلكس (4 غرف نوم)', 'area': 'مساحة: 315 ر.س/م²', 'price': '10.5 مليون ريال'},
                 {'name': 'مايونت (3 غرف)', 'area': 'مساحة: 200 ر.س/م²', 'price': '2.625 مليون ريال'},
                 {'name': 'استوديو (ناشئة)', 'area': 'مساحة: 110 ر.س/م²', 'price': 'إجمالي المساحات الفعلية: 9,730 م²'}
             ]},
             {'title': 'المصروفات التشغيلية (OPEX)', 'type': 'units', 'items': [
                 {'name': 'تصنيف الاستثمارات المتنوعة', 'area': '', 'price': 'متوسط الإيجار: 150 ر.س/م²'}
             ]},
             {'title': 'تحليل المخاطر المحتملة', 'type': 'risk', 'tag': '!', 'tag_color': '#E8A838', 'items': [
                 {'label': 'تأخر أسعار المواد البنائية', 'tag': 'عالي', 'tag_color': '#C4382A'},
                 {'label': 'تأخر الترخيصات البلدية', 'tag': 'متوسطة', 'tag_color': '#E8A838'}
             ]},
             {'title': 'إجراءات الحدوث', 'type': 'list', 'items': [
                 'تفعيل عقود الأسعار الثابتة مع المقاولين',
                 'التخطيط المبكر لاستصدار التراخيص البلدية',
                 'تنويع المنتج السكني لتلبية متطلبات السوق'
             ]}
         ],
         'design': {'mood': 'modern', 'background_style': 'solid', 'primary_color': '#7A0C0C',
                    'secondary_color': '#C4A35A', 'accent_color': '#F5F0EE', 'bg_color': '#FBFAF8',
                    'text_color': '#2D2D2D', 'layout': 'dashboard', 'title_style': 'side_accent'}},
        {'type': 'closing', 'title': 'شكراً لثقتكم', 'subtitle': 'Landloom', 'contact': 'info@landloom.ai',
         'design': {'mood': 'dramatic', 'background_style': 'gradient_v', 'primary_color': '#7A0C0C',
                    'secondary_color': '#5A0808', 'accent_color': '#C4A35A', 'bg_color': '#5A0808',
                    'text_color': '#FFFFFF', 'layout': 'centered'}}
    ]
    generate_pdf(test_slides, 'test_design', 'test_output_html.pdf')
    print("Test PDF generated with Playwright!")
