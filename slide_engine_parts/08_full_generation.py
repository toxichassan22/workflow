

# ─────────────────────────────────────────────────────────────────────────────
# Full Slide Generation (Parallel)
# ─────────────────────────────────────────────────────────────────────────────

def _replace_map_placeholders(html, map_placeholders):
    """Replace map image placeholders with actual URLs/paths."""
    if not html or not map_placeholders:
        return html
    for placeholder, path in map_placeholders.items():
        if path:
            html = html.replace(placeholder, path)

    # Fallback: if the model used the generic placeholder but only a satellite/roadmap
    # variant was generated, substitute the first available variant.
    base_variants = {
        '##MAP_OVERVIEW##': [
            '##MAP_OVERVIEW_SATELLITE##',
            '##MAP_OVERVIEW_ROADMAP##',
        ],
        '##MAP_LANDMARKS##': [
            '##MAP_LANDMARKS_SATELLITE##',
            '##MAP_LANDMARKS_ROADMAP##',
        ],
        '##MAP_ACCESS##': [
            '##MAP_ACCESS_SATELLITE##',
            '##MAP_ACCESS_ROADMAP##',
        ],
        '##MAP_CATCHMENT##': [
            '##MAP_CATCHMENT_SATELLITE##',
            '##MAP_CATCHMENT_ROADMAP##',
        ],
    }
    for base, variants in base_variants.items():
        if base in html:
            for variant in variants:
                path = map_placeholders.get(variant)
                if path:
                    html = html.replace(base, path)
                    break
    return html


def _creative_image_values(images):
    """Return the generated cover and moodboard image URLs in a safe shape with fallbacks."""
    if not isinstance(images, dict):
        return '', []
    cover = (
        images.get('cover')
        or images.get('coverImage')
        or images.get('cover_image')
        or images.get('mainImageData')
        or images.get('project_image_cover')
        or images.get('imageUrl')
        or images.get('url')
        or ''
    )
    if isinstance(cover, dict):
        cover = cover.get('url') or cover.get('imageUrl') or cover.get('approvedImageUrl') or ''
    moodboard = images.get('moodboard') or images.get('moodboardImages') or []
    if not isinstance(moodboard, list):
        moodboard = []
    return _creative_asset_url(cover), [_creative_asset_url(img) for img in moodboard]


def _moodboard_url(index, moodboard):
    """Pick the exact uploaded/generated image for a moodboard token."""
    if index < len(moodboard) and moodboard[index]:
        return moodboard[index]
    return ''


def _css_url(image_url):
    """Escape the small subset of characters that can break url('...') CSS."""
    return image_url.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '').replace('\r', '')


def _build_moodboard_fallback(images):
    """Build a deterministic moodboard layout matching the exact number of images."""
    images = [str(image) for image in (images or []) if image]
    count = len(images)

    # Dynamic CSS grid layout calculation based on image count
    if count <= 1:
        cols, rows = "1fr", "1fr"
    elif count == 2:
        cols, rows = "1fr 1fr", "1fr"
    elif count <= 4:
        cols, rows = "1fr 1fr", "1fr 1fr"
    elif count <= 6:
        cols, rows = "1fr 1fr 1fr", "1fr 1fr"
    elif count <= 8:
        cols, rows = "1fr 1fr 1fr 1fr", "1fr 1fr"
    else:
        cols, rows = f"repeat(auto-fill, minmax(220px, 1fr))", "auto"

    tiles = []
    for image in images:
        background = "background-image:url('" + _css_url(image) + "');"
        tiles.append(
            '<div style="min-width:0;min-height:0;background-size:cover;background-position:center;'
            + background + '"></div>'
        )
    return (
        '<div class="slide" dir="rtl" style="width:1280px;height:720px;position:relative;overflow:hidden;'
        'background:#171717;color:#fff;font-family:Arial,sans-serif;box-sizing:border-box;padding:42px;">'
        '<div style="display:flex;align-items:center;justify-content:space-between;height:52px;margin-bottom:20px;">'
        '<div style="font-size:30px;font-weight:700;">لوحة الإلهام (Moodboard)</div>'
        '<div style="width:170px;height:4px;background:#C2A176;"></div></div>'
        f'<div style="height:560px;display:grid;grid-template-columns:{cols};grid-template-rows:{rows};gap:8px;">'
        + ''.join(tiles) + '</div></div>'
    )


def _hex_to_rgba(color, alpha):
    """CSS rgba() from a #rgb/#rrggbb brand colour, so the veil follows the tenant's palette."""
    value = str(color or '').strip().lstrip('#')
    if len(value) == 3:
        value = ''.join(part * 2 for part in value)
    if len(value) != 6:
        value = '0b1f33'
    try:
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        red, green, blue = 11, 31, 51
    return f'rgba({red},{green},{blue},{alpha})'


def build_index_slide(slide, slide_num, total_slides, branding=None, project_data=None, offer_lang=None):
    branding = branding or {}
    slide = slide or {}
    lang = resolve_offer_lang(project_data, offer_lang)
    background = normalize_hex_color(branding.get('background_color'), '#f8fafc')
    if contrast_ratio('#1e293b', background) < 4.5:
        background = '#ffffff'
    text_color = readable_text_color(branding.get('text_color'), background)
    primary = readable_text_color(branding.get('primary_color'), background, (text_color,))
    accent = readable_text_color(branding.get('accent_color'), background, (primary, text_color))
    separator = _hex_to_rgba(text_color, '0.30')
    slide_ratio = branding.get('slide_ratio', '16:9')
    width, height = (1280, 960) if slide_ratio == '4:3' else (1280, 720)
    entries = [entry for entry in (slide.get('index_entries') or []) if isinstance(entry, dict)]
    midpoint = (len(entries) + 1) // 2

    def column(items):
        rows = []
        for entry in items:
            title = html_lib.escape(str(entry.get('title') or '').strip())
            section_key = html_lib.escape(str(entry.get('section_key') or '').strip(), quote=True)
            try:
                page = int(entry.get('page'))
            except (TypeError, ValueError):
                page = 0
            rows.append(
                f'<div data-index-section="{section_key}" style="min-height:48px;display:flex;align-items:center;gap:18px;'
                f'border-bottom:1px solid {separator};padding:9px 2px;box-sizing:border-box;">'
                f'<div style="font-size:16px;font-weight:600;color:{text_color};flex:1;">{title}</div>'
                f'<div data-index-page="{section_key}" dir="ltr" style="font-size:16px;font-weight:700;color:{accent};min-width:34px;'
                f'text-align:left;">{page:02d}</div></div>'
            )
        return ''.join(rows)

    columns = [entries[:midpoint], entries[midpoint:]]
    slide_dir = 'ltr' if lang == OFFER_LANG_ENGLISH else 'rtl'
    return (
        f'<div class="slide" dir="{slide_dir}" style="width:{width}px;height:{height}px;position:relative;'
        f'overflow:hidden;box-sizing:border-box;background:{background};color:{text_color};">'
        f'<div style="position:absolute;top:82px;right:52px;left:52px;bottom:58px;box-sizing:border-box;">'
        f'<div style="font-size:30px;font-weight:700;color:{primary};margin-bottom:24px;">{html_lib.escape(offer_chrome("index_heading", lang))}</div>'
        f'<div style="width:86px;height:3px;background:{accent};margin-bottom:24px;"></div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:26px 54px;align-items:start;">'
        f'<div>{column(columns[0])}</div><div>{column(columns[1])}</div>'
        '</div></div></div>'
    )


def _usable_slide_image_url(value):
    url = html_lib.unescape(str(value or '').strip()).strip().strip('"\'')
    lowered = url.lower()
    if not url or url.startswith('#') or '##' in url:
        return ''
    if lowered in {'none', 'undefined', 'null', 'about:blank'}:
        return ''
    if lowered.startswith(('blob:', 'javascript:')):
        return ''
    return url


def _slide_background_image_url(html):
    for match in re.finditer(
        r'background(?:-image)?\s*:\s*url\(\s*["\']?([^"\')]+)["\']?\s*\)',
        str(html or ''), flags=re.IGNORECASE,
    ):
        url = _usable_slide_image_url(match.group(1))
        if url:
            return url
    return ''


def _cover_image_url_from_html(html):
    """Find the actual cover image without mistaking an earlier logo for it."""
    source = str(html or '')
    for match in re.finditer(
        r'background(?:-image)?\s*:\s*url\(\s*["\']?([^"\')]+)["\']?\s*\)',
        source, flags=re.IGNORECASE,
    ):
        url = _usable_slide_image_url(match.group(1))
        if url and 'logo' not in url.lower():
            return url
    for match in re.finditer(
        r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', source, flags=re.IGNORECASE,
    ):
        url = _usable_slide_image_url(match.group(1))
        if url and 'logo' not in url.lower():
            return url
    return ''


def _extract_cover_image_url(project_data, creative_images=None):
    """Safely extract cover image URL from project_data, creative_images, or visual_concept.

    Handles JSON strings, nested dicts, and malformed facts without raising
    AttributeError or TypeError.
    """
    p_data = project_data if isinstance(project_data, dict) else {}
    if not isinstance(creative_images, dict):
        tci_raw = p_data.get('tenantCreativeImages')
        if isinstance(tci_raw, str):
            tci_raw = _decode_json_fact(tci_raw)
        creative_images = tci_raw if isinstance(tci_raw, dict) else {}

    def _resolve(val):
        if not val:
            return ''
        if isinstance(val, str):
            val_str = val.strip()
            if val_str.startswith('{') and val_str.endswith('}'):
                decoded = _decode_json_fact(val_str)
                if isinstance(decoded, dict):
                    return _resolve(decoded)
            return _usable_slide_image_url(val_str)
        if isinstance(val, dict):
            for k in ('url', 'imageUrl', 'approvedImageUrl', 'dataUrl'):
                res = _resolve(val.get(k))
                if res:
                    return res
        return ''

    if isinstance(creative_images, dict):
        for k in ('cover', 'coverImage', 'cover_image', 'mainImageData', 'project_image_cover', 'imageUrl', 'url'):
            url = _resolve(creative_images.get(k))
            if url:
                return url

    for k in ('cover', 'coverImage', 'cover_image', 'mainImageData', 'project_image_cover'):
        url = _resolve(p_data.get(k))
        if url:
            return url

    tci = p_data.get('tenantCreativeImages')
    if isinstance(tci, str):
        tci = _decode_json_fact(tci)
    if isinstance(tci, dict):
        for k in ('cover', 'coverImage', 'mainImageData', 'project_image_cover', 'imageUrl', 'url'):
            url = _resolve(tci.get(k))
            if url:
                return url

    vc = p_data.get('visual_concept')
    if isinstance(vc, str):
        vc = _decode_json_fact(vc)
    if isinstance(vc, dict):
        slots = vc.get('slots')
        if isinstance(slots, str):
            slots = _decode_json_fact(slots)
        if isinstance(slots, dict):
            url = _resolve(slots.get('cover'))
            if url:
                return url
        for k in ('cover', 'coverImage', 'mainImageData', 'approvedImageUrl', 'imageUrl', 'url'):
            url = _resolve(vc.get(k))
            if url:
                return url

    return ''


def _force_section_divider_background(html, cover_url):
    """Make a divider use the deck's real cover even when its saved CSS is empty or stale."""
    cover = _usable_slide_image_url(cover_url)
    if not html or not cover:
        return html
    declaration = (
        "background-image:url('" + _css_url(cover) + "')!important;"
        'background-size:cover!important;background-position:center center!important;'
        'background-repeat:no-repeat!important;'
    )
    source = str(html)
    source, count = re.subn(
        r'background(?:-image)?\s*:\s*(?:url\([^)]*\)|none)\s*;?',
        declaration, source, count=1, flags=re.IGNORECASE,
    )
    if count:
        return source
    background = (
        '<div data-section-divider-background="1" aria-hidden="true" '
        'style="position:absolute;top:0;right:0;left:0;bottom:0;'
        + declaration + '"></div>'
    )
    return re.sub(
        r'(<div\b[^>]*\bclass=["\'][^"\']*\bslide\b[^"\']*["\'][^>]*>)',
        lambda match: match.group(1) + background,
        source, count=1, flags=re.IGNORECASE,
    )


def build_section_divider_slide(slide, slide_num, total_slides, branding=None, project_data=None, offer_lang=None):
    """Render a section divider: the main image, darkened, with the section name over it.

    The layout is identical on every divider and only the text changes, so it is built here
    instead of being asked from the model on every deck: that keeps all dividers pixel-identical,
    costs no tokens, and cannot drift between slides.
    """
    branding = branding or {}
    project_data = project_data or {}
    slide = slide or {}
    lang = resolve_offer_lang(project_data, offer_lang)
    ltr = lang == OFFER_LANG_ENGLISH
    slide_dir = 'ltr' if ltr else 'rtl'
    align = 'left' if ltr else 'right'
    fore, aft = ('left', 'right') if ltr else ('right', 'left')
    primary = normalize_hex_color(branding.get('primary_color'), '#0b1f33')
    divider_background = dark_surface_color(primary, branding.get('secondary_color'))
    accent = readable_text_color(branding.get('accent_color'), divider_background, ('#ffffff',))
    slide_ratio = branding.get('slide_ratio', '16:9')
    width, height = (1280, 960) if slide_ratio == '4:3' else (1280, 720)

    title = html_lib.escape(str(slide.get('title') or ('Section' if ltr else 'القسم')).strip())
    project_name = html_lib.escape(str(project_data.get('project_name') or project_data.get('projectName') or '').strip())
    project_logo = str(project_data.get('project_logo') or '').strip()

    logos = '<img src="##LOGO##" alt="" style="height:80px;width:auto;object-fit:contain;" />'
    if project_logo:
        logos += (
            '<div style="width:1px;height:52px;background:rgba(255,255,255,0.35);margin:0 18px;"></div>'
            '<img src="##PROJECT_LOGO##" alt="" style="height:80px;width:auto;object-fit:contain;" />'
        )

    rule = f'<div style="width:200px;height:3px;background:{accent};margin:18px {"auto 0 0" if ltr else "0 0 auto"};"></div>'
    footer_number = f'{slide_num:02d} — {int(total_slides or slide_num):02d}' if slide_num else ''

    return (
        f'<div class="slide" dir="{slide_dir}" style="width:{width}px;height:{height}px;position:relative;'
        f'overflow:hidden;box-sizing:border-box;background:{divider_background};">'
        # The approved main image, full bleed.
        '<div data-section-divider-background="1" style="position:absolute;top:0;right:0;left:0;bottom:0;'
        'background-image:url(##IMAGE_COVER##);background-size:cover;background-position:center center;"></div>'
        # Navy veil: dark enough for white text on any photo, light enough that the photo shows.
        f'<div style="position:absolute;top:0;right:0;left:0;bottom:0;background:linear-gradient(160deg,'
        f'{_hex_to_rgba(divider_background, "0.94")} 0%,{_hex_to_rgba(divider_background, "0.82")} 45%,'
        f'{_hex_to_rgba(divider_background, "0.62")} 100%);"></div>'
        f'<div style="position:absolute;top:0;bottom:0;{aft}:0;width:10px;background:{accent};"></div>'
        f'<div style="position:absolute;top:44px;{aft}:48px;display:flex;align-items:center;">{logos}</div>'
        # padding-bottom biases the block slightly above the optical centre, as in the reference.
        f'<div style="position:absolute;top:0;bottom:0;{fore}:64px;width:58%;display:flex;flex-direction:column;'
        f'justify-content:center;text-align:{align};padding-bottom:56px;box-sizing:border-box;">'
        f'<div style="font-size:58px;line-height:1.15;font-weight:700;color:#ffffff;">{title}</div>'
        f'{rule}'
        '</div>'
        f'<div data-slide-counter="1" dir="ltr" style="position:absolute;bottom:34px;{aft}:48px;font-size:13px;letter-spacing:1px;'
        f'color:rgba(255,255,255,0.55);">{footer_number}</div>'
        f'<div style="position:absolute;bottom:34px;{fore}:48px;font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;color:{accent};">{project_name}</div>'
        '</div>'
    )


def _replace_creative_image_placeholders(html, creative_images, slide_type, content_source=None):
    """Resolve image tokens after generation so browser previews always have real sources."""
    if not html:
        return html
    cover, moodboard = _creative_image_values(creative_images)

    # Replace cover tokens
    for cover_pat in [r'#*IMAGE_COVER#*', r'#*COVER_IMAGE#*', r'#*MAIN_IMAGE#*', r'#*PROJECT_IMAGE_COVER#*']:
        html = re.sub(cover_pat, cover, html, flags=re.IGNORECASE)

    # Replace moodboard & project image tokens (including malformed variations)
    def _replace_moodboard_token(match):
        index = int(match.group(1)) - 1
        return _moodboard_url(index, moodboard)

    html = re.sub(r'#*MOODBOARD_IMAGE_(\d+)#*', _replace_moodboard_token, html, flags=re.IGNORECASE)
    html = re.sub(r'#*PROJECT_IMAGE_(\d+)#*', _replace_moodboard_token, html, flags=re.IGNORECASE)

    land_photos = creative_images.get('land_photos') if isinstance(creative_images, dict) else []
    for index, item in enumerate(land_photos if isinstance(land_photos, list) else [], 1):
        source = item if isinstance(item, dict) else {'url': item}
        url = str(source.get('url') or source.get('imageUrl') or '').strip()
        if url:
            html = re.sub(rf'#*LAND_(?:PHOTO|IMAGE)_{index}#*', _css_url(url), html, flags=re.IGNORECASE)

    team_members = creative_images.get('team_members') if isinstance(creative_images, dict) else []
    for index, item in enumerate(team_members if isinstance(team_members, list) else [], 1):
        source = item if isinstance(item, dict) else {'logo': item}
        url = str(source.get('logo') or source.get('url') or '').strip()
        if url:
            html = re.sub(rf'#*TEAM_LOGO_{index}#*', _css_url(url), html, flags=re.IGNORECASE)

    competitor_logos = creative_images.get('competitor_logos') if isinstance(creative_images, dict) else []
    for index, item in enumerate(competitor_logos if isinstance(competitor_logos, list) else [], 1):
        source = item if isinstance(item, dict) else {'logo': item}
        url = str(source.get('logo') or source.get('url') or '').strip()
        if url:
            html = re.sub(rf'#*COMPETITOR_LOGO_{index}#*', _css_url(url), html, flags=re.IGNORECASE)
    html = re.sub(r'(?<![A-Za-z0-9_])#*COMPETITOR_LOGO_\d+#*', '', html, flags=re.IGNORECASE)

    # Replace component-specific interior tokens
    interior_comps = []
    if isinstance(creative_images, dict):
        interior_comps = creative_images.get('interior_components') or []
    for c_idx, comp in enumerate(interior_comps, 1):
        c_imgs = comp.get('images', []) if isinstance(comp, dict) else []
        for j_idx, img_item in enumerate(c_imgs, 1):
            url = img_item.get('url', '') if isinstance(img_item, dict) else str(img_item or '')
            if url:
                css_u = _css_url(url)
                html = re.sub(rf'#*INTERIOR_COMP_{c_idx}_(?:IMG|IMAGE)_{j_idx}#*', css_u, html, flags=re.IGNORECASE)
                html = re.sub(rf'#*INTERIOR_C{c_idx}_(?:IMG|IMAGE)_{j_idx}#*', css_u, html, flags=re.IGNORECASE)
                html = re.sub(rf'#*INTERIOR_{c_idx}_{j_idx}#*', css_u, html, flags=re.IGNORECASE)

    # Replace flat interior tokens
    interiors = []
    if isinstance(creative_images, dict):
        interiors = creative_images.get('interior') or creative_images.get('interior_images') or []
        if not isinstance(interiors, list):
            interiors = [interiors]
    for idx, url in enumerate(interiors):
        num = idx + 1
        if url:
            html = re.sub(rf'#*INTERIOR_IMAGE_{num}#*', _css_url(str(url)), html, flags=re.IGNORECASE)
    html = re.sub(r'(?<![A-Za-z0-9_])#*INTERIOR_(?:COMP_\d+_(?:IMG|IMAGE)_\d+|C\d+_(?:IMG|IMAGE)_\d+|\d+_\d+|IMAGE_\d+|\d+)#*', '', html, flags=re.IGNORECASE)

    # Replace 2D plan tokens
    plans = []
    if isinstance(creative_images, dict):
        plans = creative_images.get('plans') or creative_images.get('plans2d') or []
        if not isinstance(plans, list):
            plans = [plans]
    for idx, url in enumerate(plans):
        num = idx + 1
        if isinstance(url, dict):
            url = url.get('url') or url.get('imageUrl') or url.get('image_url') or url.get('path') or ''
        if url:
            html = re.sub(rf'#*PLAN_IMAGE_{num}#*', _css_url(str(url)), html, flags=re.IGNORECASE)
            html = re.sub(rf'#*2D_PLAN_{num}#*', _css_url(str(url)), html, flags=re.IGNORECASE)
    html = re.sub(r'(?<![A-Za-z0-9_])#*(?:PLAN_IMAGE|2D_PLAN)_\d+#*', '', html, flags=re.IGNORECASE)

    # Do not leave the cover blank simply because the model forgot its token.
    if slide_type == 'cover' and cover and cover not in html:
        background = (
            '<div aria-hidden="true" style="position:absolute;inset:0;z-index:0;'
            "background-image:url('" + _css_url(cover) + "');background-size:cover;background-position:center;\"></div>"
        )
        html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1' + background, html, count=1)

    # A moodboard slide should show the exact moodboard images
    if slide_type == 'moodboard' or 'moodboard' in str(slide_type).lower() or 'مودبورد' in html:
        if any(moodboard) and not re.search(r'<img|background-image', html, re.IGNORECASE):
            html = _build_moodboard_fallback(moodboard)
    logo_items = []
    for item in competitor_logos if isinstance(competitor_logos, list) else []:
        source = item if isinstance(item, dict) else {'logo': item}
        url = str(source.get('logo') or source.get('url') or '').strip()
        if url:
            logo_items.append((str(source.get('name') or '').strip(), url))
    missing_logo_items = [(name, url) for name, url in logo_items if url not in html]
    # Competitor logos belong in the fixed competitor table. Do not append a
    # decorative logo strip to summary, scope, or source slides.
    if str(content_source or '') == 'market_study_data.competitors' and missing_logo_items:
        logos = ''.join(
            '<img src="' + html_lib.escape(url, quote=True) + '" alt="' + html_lib.escape(name, quote=True)
            + '" style="width:64px;height:40px;object-fit:contain;background:#fff;border-radius:7px;padding:4px;box-sizing:border-box;">'
            for name, url in missing_logo_items[:6]
        )
        strip = ('<div data-competitor-logos="1" style="position:absolute;left:50px;bottom:58px;z-index:20;'
                 'display:flex;gap:8px;align-items:center;">' + logos + '</div>')
        html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1' + strip, html, count=1)

    # Rescue image-source tokens the model invented (##AERIAL_IMAGE_3##,
    # ##LOBBY_INTERIOR_1##): the family keyword plus the trailing index pick a
    # real project image, so the frame is not left for the placeholder dropper.
    # Scoped to src=/url() contexts so a field token like ##VIEW_NAME## in text
    # is never rewritten into an image URL.
    def _loose_image_token_url(token_text):
        body = token_text.strip('#').upper().replace('-', '_').replace(' ', '_')
        index_match = re.search(r'_(\d+)$', body)
        index = int(index_match.group(1)) - 1 if index_match else 0
        if 'INTERIOR' in body or 'INDOOR' in body:
            family = 'interior'
        elif 'PLAN' in body or 'LAYOUT' in body or 'BLUEPRINT' in body:
            family = 'plan'
        elif 'LAND' in body or 'PLOT' in body or 'SITE_PHOTO' in body:
            family = 'land'
        elif 'COVER' in body or 'HERO' in body or body.startswith('MAIN'):
            family = 'cover'
        else:
            family = 'moodboard'
        src = creative_images if isinstance(creative_images, dict) else {}
        urls = []
        if family == 'cover':
            urls = [cover] if cover else []
        elif family == 'moodboard':
            urls = [u for u in moodboard if u]
        elif family == 'interior':
            raw = src.get('interior') or src.get('interior_images') or []
            urls = [str(u) for u in (raw if isinstance(raw, list) else [raw]) if u]
            for comp in src.get('interior_components') or []:
                comp_images = comp.get('images', []) if isinstance(comp, dict) else []
                for img_item in comp_images:
                    u = img_item.get('url', '') if isinstance(img_item, dict) else str(img_item or '')
                    if u:
                        urls.append(u)
        elif family == 'plan':
            raw = src.get('plans') or src.get('plans2d') or []
            for item in (raw if isinstance(raw, list) else [raw]):
                u = (item.get('url') or item.get('imageUrl') or item.get('image_url')
                     or item.get('path') or '') if isinstance(item, dict) else str(item or '')
                if u:
                    urls.append(str(u))
        elif family == 'land':
            for item in src.get('land_photos') or []:
                source = item if isinstance(item, dict) else {'url': item}
                u = str(source.get('url') or source.get('imageUrl') or '').strip()
                if u:
                    urls.append(u)
        if 0 <= index < len(urls):
            return _css_url(urls[index])
        return token_text

    loose_token = (r'#+[A-Za-z0-9_\s-]*(?:IMAGE|IMG|PHOTO|VIEW|RENDER|AERIAL|EXTERIOR|MOODBOARD|'
                   r'INTERIOR|PLAN|LAND|COVER|SCENE|FACADE|PERSPECTIVE|VISUAL)[A-Za-z0-9_\s-]*#+')
    # A token prefix glued to an already-resolved URL (##AERIAL_/uploads/x.png)
    # is an invented wrapper around a real token — drop the wrapper, keep the URL.
    html = re.sub(r'(\bsrc\s*=\s*["\'])#+[A-Za-z0-9_]+_(?=(?:/|data:|https?:))',
                  r'\1', html, flags=re.IGNORECASE)
    html = re.sub(r'(url\(\s*["\']?)#+[A-Za-z0-9_]+_(?=(?:/|data:|https?:))',
                  r'\1', html, flags=re.IGNORECASE)
    html = re.sub(
        r'(\bsrc\s*=\s*["\'])(' + loose_token + r')(["\'])',
        lambda m: m.group(1) + _loose_image_token_url(m.group(2)) + m.group(3),
        html, flags=re.IGNORECASE)
    html = re.sub(
        r'(url\(\s*["\']?)(' + loose_token + r')(["\']?\s*\))',
        lambda m: m.group(1) + _loose_image_token_url(m.group(2)) + m.group(3),
        html, flags=re.IGNORECASE)
    return html


def _replace_data_placeholders(html, project_data, branding=None):
    """Replace all field & data tokens (like ##PROJECT_NAME##, ##land_area##, ##noi##, ##LOGO##) with real values."""
    if not html:
        return html

    project_data = project_data or {}
    branding = branding or {}

    replacements = {}

    # 1. Logo replacement
    logo_url = branding.get('logo_path') or branding.get('logo') or branding.get('logo_url')
    if not logo_url:
        print('[REPLACE] WARNING: no logo_path in branding; falling back to /assets/logo.png')
        logo_url = '/assets/logo.png'
    elif not logo_url.startswith('/') and not logo_url.startswith('http'):
        logo_url = f"/{logo_url.lstrip('/')}"
    replacements['##LOGO##'] = logo_url

    # 2. Add all dynamic key-value pairs from project_data
    for k, v in project_data.items():
        if v is None or isinstance(v, (dict, list)):
            continue
        val_str = str(v)
        replacements[f'##{k}##'] = val_str
        replacements[f'##{k.lower()}##'] = val_str
        replacements[f'##{k.upper()}##'] = val_str

    # 3. Known key aliases & fallback mappings for template placeholders
    aliases = {
        'PROJECT_NAME': project_data.get('project_name') or project_data.get('projectName') or project_data.get('name') or 'المشروع الاستثماري',
        'PROJECT_TYPE': project_data.get('project_type') or project_data.get('projectType') or 'مشروع عقاري',
        'PROJECT_DESCRIPTION': project_data.get('project_description') or project_data.get('description') or '',
        'land_area': project_data.get('land_area') or project_data.get('total_area_sqm') or project_data.get('landArea') or '—',
        'built_area': project_data.get('built_area') or project_data.get('total_built_area') or project_data.get('builtArea') or '—',
        'location_address': project_data.get('location_address') or project_data.get('location') or project_data.get('address') or 'المملكة العربية السعودية',
        'location_lat': str(project_data.get('location_lat') or project_data.get('lat') or ''),
        'location_lng': str(project_data.get('location_lng') or project_data.get('lng') or ''),
        'altsnyf_altkhtyty': project_data.get('altsnyf_altkhtyty') or project_data.get('zoning') or project_data.get('planning_classification') or '—',
        'building_system': project_data.get('building_system') or project_data.get('buildingSystem') or '—',
        'nsba_albna__far': project_data.get('nsba_albna__far') or project_data.get('far') or project_data.get('building_ratio') or '—',
        'plot_number': project_data.get('plot_number') or project_data.get('plotNumber') or project_data.get('plan_number') or '—',
        'infrastructure': project_data.get('infrastructure') or project_data.get('utilities') or 'مكتملة الخدمات',
        'budget': project_data.get('budget') or project_data.get('total_cost') or project_data.get('totalCost') or '—',
        'noi': project_data.get('noi') or project_data.get('annual_profit') or project_data.get('net_operating_income') or '—',
        'roi': project_data.get('roi') or project_data.get('return_on_investment') or '—',
        'alqrma_almdafa_almtwqaa__cap_rate': project_data.get('cap_rate') or project_data.get('capRate') or project_data.get('alqrma_almdafa_almtwqaa__cap_rate') or '—',
        'nsba_alashgal_almtwqaa': project_data.get('occupancy_rate') or project_data.get('occupancy') or '—',
        'PROJECT_LOGO': _project_logo_reference(project_data),
    }

    for a_key, a_val in aliases.items():
        if a_val is not None:
            val_s = str(a_val)
            replacements[f'##{a_key}##'] = val_s
            replacements[f'##{a_key.lower()}##'] = val_s
            replacements[f'##{a_key.upper()}##'] = val_s

    # Perform replacements
    for token, value in replacements.items():
        if token in html:
            html = html.replace(token, value)

    # Regex search for any custom tokens generated by LLM (e.g. ##custom_key##)
    def token_replacer(match):
        token_str = match.group(0)
        # An image token is left standing for _drop_unresolved_image_placeholders to deal with.
        # Blanking it here is what produced empty framed boxes: src="" / url() render as a card
        # with nothing in it, and the reader saw it as part of the design.
        if IMAGE_TOKEN_RE.fullmatch(token_str):
            return token_str
        raw_key = token_str.replace('##', '').strip()
        for k, v in project_data.items():
            if k.lower() == raw_key.lower() and v is not None:
                return str(v)
        return ''

    html = re.sub(r'##[a-zA-Z0-9_]+##', token_replacer, html)

    return html


# A token naming an image. Anything matching this that survives the whole pipeline has no image
# behind it, so its carrier is removed rather than emptied.
IMAGE_TOKEN_RE = re.compile(
    r'##[A-Za-z0-9_]*(?:IMAGE|IMG|PHOTO|STREET_VIEW|MAP_|PLAN|INTERIOR|MOODBOARD|COVER|LOGO)[A-Za-z0-9_]*##',
    re.IGNORECASE,
)


def _drop_unresolved_image_placeholders(html):
    """Remove image carriers that ended up with no image, instead of leaving an empty frame.

    A slide came out with four empty cards because it used ##STREET_VIEW_1..4##, which no workflow
    produces: the tokens were blanked into `src=""` / `url()` and the frames stayed. An image that
    does not exist must leave nothing behind, not a hole.
    """
    if not html:
        return html
    html = re.sub(r'<img\b[^>]*>',
                  lambda m: '' if IMAGE_TOKEN_RE.search(m.group(0)) else m.group(0),
                  html, flags=re.IGNORECASE)
    # background / background-image declarations pointing at a leftover token or at nothing.
    html = re.sub(r'background(?:-image)?\s*:\s*url\(\s*["\']?[^)"\']*##[^)"\']*["\']?\s*\)\s*;?',
                  '', html, flags=re.IGNORECASE)
    html = re.sub(r'background(?:-image)?\s*:\s*url\(\s*["\']?\s*["\']?\s*\)\s*;?',
                  '', html, flags=re.IGNORECASE)
    html = re.sub(r'<img\b[^>]*src=["\']\s*["\'][^>]*>', '', html, flags=re.IGNORECASE)
    # Whatever token text is left is not an image reference the reader should see.
    return IMAGE_TOKEN_RE.sub('', html)


def _apply_logo_contrast_styles(html, branding, project_data, slide_type='content'):
    if not html:
        return html
    branding = branding or {}
    project_data = project_data or {}
    dark_background = dark_surface_color(
        branding.get('primary_color'), branding.get('secondary_color'))
    profiles = {
        '##LOGO##': str(project_data.get('_company_logo_tone') or branding.get('_logo_tone') or 'unknown').lower(),
        '##PROJECT_LOGO##': str(project_data.get('_project_logo_tone') or 'unknown').lower(),
    }

    content_header = slide_type not in ('cover', 'closing', 'moodboard', 'section_divider')
    hero_logo = slide_type in ('cover', 'closing', 'section_divider')

    def style_token(source, token, tone):
        background = dark_background if tone == 'light' else '#ffffff'

        def apply(match):
            tag = match.group(0)
            chrome_logo = 'presentation-chrome-logo' in tag
            size = ('height:48px!important;max-height:48px!important;' if chrome_logo and content_header else
                    'height:40px!important;max-height:40px!important;' if chrome_logo else
                    'height:48px!important;max-height:48px!important;' if content_header else
                    'height:80px!important;max-height:80px!important;' if hero_logo else '')
            padding = '3px 7px' if chrome_logo else ('4px 10px' if content_header else '6px 12px')
            declarations = (
                f'{size}background:{background}!important;padding:{padding}!important;'
                'border-radius:8px!important;box-sizing:border-box!important;object-fit:contain!important;'
            )
            style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', tag, re.IGNORECASE)
            if style_match:
                style = style_match.group(2).rstrip(';') + ';' + declarations
                return tag[:style_match.start(2)] + style + tag[style_match.end(2):]
            return tag.replace('<img', f'<img style="{declarations}"', 1)

        pattern = rf'<img\b(?=[^>]*\bsrc\s*=\s*["\'][^"\']*{re.escape(token)}[^"\']*["\'])[^>]*>'
        return re.sub(pattern, apply, source, flags=re.IGNORECASE)

    for token, tone in profiles.items():
        html = style_token(html, token, tone)

    # Stored presentations may already contain resolved logo URLs instead of
    # placeholders.  In that case the token pass above cannot apply the tone,
    # so restyle the managed chrome by position/source as well.  The project
    # URL is the only reliable discriminator for the optional second logo.
    project_logo = _project_logo_reference(project_data)

    def style_resolved_chrome(match):
        tag = match.group(0)
        src_match = re.search(r'\bsrc\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
        src = str(src_match.group(1) if src_match else '')
        if '##LOGO##' in src or '##PROJECT_LOGO##' in src:
            return tag
        if project_logo and project_logo in src:
            tone = profiles['##PROJECT_LOGO##']
        else:
            tone = profiles['##LOGO##']
        return _apply_logo_tag_style(tag, tone, dark_background, content_header, hero_logo)

    def _apply_logo_tag_style(tag, tone, background, is_content_header, is_hero_logo):
        chrome_logo = 'presentation-chrome-logo' in tag
        if chrome_logo:
            size = ('height:48px!important;max-height:48px!important;' if is_content_header else
                    'height:80px!important;max-height:80px!important;' if is_hero_logo else
                    'height:40px!important;max-height:40px!important;')
            padding = '3px 7px'
        else:
            size = ('height:48px!important;max-height:48px!important;' if is_content_header else
                    'height:80px!important;max-height:80px!important;' if is_hero_logo else '')
            padding = '4px 10px' if is_content_header else '6px 12px'
        declarations = (
            f'{size}background:{background if tone == "light" else "#ffffff"}!important;'
            f'padding:{padding}!important;border-radius:8px!important;box-sizing:border-box!important;'
            'object-fit:contain!important;'
        )
        style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', tag, re.IGNORECASE)
        if style_match:
            style = style_match.group(2).rstrip(';') + ';' + declarations
            return tag[:style_match.start(2)] + style + tag[style_match.end(2):]
        return tag.replace('<img', f'<img style="{declarations}"', 1)

    # Only resolve tags that are part of the managed chrome.  Content images
    # must never inherit the logo background rule.
    html = re.sub(r'<img\b[^>]*\bclass\s*=\s*["\'][^"\']*presentation-chrome-logo[^"\']*["\'][^>]*>',
                  style_resolved_chrome, html, flags=re.IGNORECASE)
    return html


def _strip_unplanned_creative_tokens(html, slide):
    """Prevent a model from spreading uploaded images into unrelated slides."""
    if not html or not isinstance(slide, dict):
        return html
    allowed = {
        _canonical_image_token(token)
        for token in (slide.get('image_tokens') or [])
        if _canonical_image_token(token)
    }
    token_re = re.compile(
        r'#*(?:PROJECT_IMAGE|MOODBOARD_IMAGE|LAND_IMAGE|LAND_PHOTO|2D_PLAN|PLAN_IMAGE)_\d+#*|'
        r'#*INTERIOR(?:_COMP)?_\d+_(?:IMG|IMAGE)_\d+#*|'
        r'#*INTERIOR_C\d+_(?:IMG|IMAGE)_\d+#*|'
        r'#*INTERIOR_\d+_\d+#*|'
        r'#*TEAM_LOGO_\d+#*',
        re.IGNORECASE,
    )

    def replace(match):
        raw = match.group(0)
        canonical = _canonical_image_token(raw)
        return raw if canonical in allowed else ''

    return token_re.sub(replace, html)


def resolve_logo_in_html(html, tenant_id=None, _branding_cache=None, project_logo=None):
    """Replace all logo placeholders and broken logo paths with tenant's logo URL.

    ``project_logo`` is the already-resolved path of the project's own logo. It has to be known
    here: this function rewrites the ``src`` of every ``<img>`` whose tag mentions "logo", and by
    the time it runs ``##PROJECT_LOGO##`` has already been replaced with a real path. A project
    logo stored at a path containing the word "logo" was therefore replaced by the company logo.
    """
    if not html:
        return html
    project_logo = str(project_logo or '').strip()
    logo_url = '/assets/logo.png'
    if tenant_id:
        branding = _branding_cache if _branding_cache is not None else (db.get_branding(tenant_id) or {})
        if branding.get('logo_path'):
            logo_url = branding['logo_path']
            if not logo_url.startswith('http') and '?t=' not in logo_url:
                logo_url = f"{logo_url}?t=1"
        else:
            logo_url = f"/tenant-assets/{tenant_id}/logo?t=1"
    else:
        logo_url = '/assets/logo.png'

    if not logo_url.startswith('/') and not logo_url.startswith('http'):
        logo_url = f"/{logo_url}"

    html = html.replace('##LOGO##', logo_url)
    html = re.sub(
        r'src=["\'](?:/?assets/logo\.png|logo\.png|/logo\.png|undefined|null|none)["\']',
        f'src="{logo_url}"',
        html,
        flags=re.IGNORECASE
    )

    def _fix_logo_img(match):
        img_tag = match.group(0)
        lowered = img_tag.lower()
        # Never touch embedded uploads: data/blob URLs are user content, and a base64
        # payload can easily contain the substring "logo" by chance. Checking the whole
        # tag for "logo" used to rewrite such uploads to the company logo.
        src_match = re.search(r'src\s*=\s*["\']([^"\']*)["\']', img_tag, flags=re.IGNORECASE)
        src_value = (src_match.group(1) if src_match else '').strip()
        src_lower = src_value.lower()
        if src_lower.startswith('data:image/') or src_lower.startswith('data:') or src_lower.startswith('blob:'):
            return img_tag
        # A company watermark is a separate branding asset. Its tenant-assets URL
        # must never be rewritten to the company logo by this compatibility pass.
        if re.search(r'/tenant-assets/[^/]+/watermark(?:[?#]|$)', src_lower):
            return img_tag
        if 'project_logo' in lowered or '##project_logo##' in lowered or 'project-logo' in lowered:
            return img_tag
        if project_logo and project_logo in img_tag:
            return img_tag
        if '/uploads/creative/' in lowered or '/api/project-files/' in lowered or 'project-files' in lowered:
            return img_tag
        # Check logo hints outside the src value only, so base64 payloads never match.
        tag_without_src = re.sub(r'src\s*=\s*["\'][^"\']*["\']', '', img_tag, flags=re.IGNORECASE).lower()
        if 'logo' in tag_without_src or '##logo##' in lowered or 'tenant-assets' in lowered:
            if 'src=' in img_tag.lower():
                img_tag = re.sub(r'src=["\'][^"\']*["\']', f'src="{logo_url}"', img_tag, flags=re.IGNORECASE)
            else:
                img_tag = img_tag.replace('<img', f'<img src="{logo_url}"')

            # Only add the logo sizing style once, and never over an explicit height: the cover,
            # closing and section dividers set a much larger logo on purpose.
            _LOGO_STYLE = 'max-height:50px;width:auto;object-fit:contain;display:inline-block;'
            has_explicit_height = re.search(r'(?:max-)?height\s*:', img_tag, flags=re.IGNORECASE)
            if _LOGO_STYLE not in img_tag and not has_explicit_height:
                if 'style=' in img_tag.lower():
                    img_tag = re.sub(
                        r'style=["\']([^"\']*)["\']',
                        lambda m: f'style="{m.group(1).rstrip(";")};{_LOGO_STYLE}"',
                        img_tag,
                        flags=re.IGNORECASE
                    )
                else:
                    img_tag = img_tag.replace('<img', f'<img style="{_LOGO_STYLE}"')
        return img_tag

    html = re.sub(r'<img\s[^>]*>', _fix_logo_img, html, flags=re.IGNORECASE)
    return html


def _remove_unapproved_contact_elements(html, project_data):
    source = project_data if isinstance(project_data, dict) else {}
    allowed = [str(source.get(key) or '').strip() for key in (
        'contact_name', 'contact_position', 'contact_phone', 'contact_email',
        'contact_website', 'contact_address', 'contact_social_media') if str(source.get(key) or '').strip()]
    contact_pattern = re.compile(r'(?:هاتف|جوال|بريد|إيميل|email|موقع إلكتروني|عنوان|سوشل|تواصل)', re.IGNORECASE)

    def remove_if_unapproved(match):
        text = html_lib.unescape(re.sub(r'<[^>]+>', ' ', match.group(0)))
        if not contact_pattern.search(text):
            return match.group(0)
        approved = any(re.search(rf'(?<![\w@.]){re.escape(value)}(?![\w@.])', text)
                       for value in allowed)
        return match.group(0) if approved else ''

    return re.sub(r'<(?:p|li|span|small|div)\b[^>]*>[^<>]*</(?:p|li|span|small|div)\s*>',
                  remove_if_unapproved, html, flags=re.IGNORECASE)


def _strip_presentation_icons(html):
    """Remove all icon markup and emoji, keeping company logo images and genuine data charts.

    Emojis used to be converted into inline SVG icons first, which the SVG removal below then
    deleted anyway. The product rule is that no icon is ever produced, so they are simply stripped.
    Genuine data rendering SVGs (map polygon overlay or chart data lines/polylines) are preserved.
    """
    if not html:
        return html

    def _strip_svg_if_icon(match):
        chunk = match.group(0)
        # Preserve genuine data visualization SVGs (map boundary overlay or chart data lines/polylines)
        if any(marker in chunk for marker in ('mapPolygonOverlay', 'data-chart', 'polyline', 'data-chart-line')):
            return chunk
        return ''

    html = re.sub(r'<svg\b[^>]*>[\s\S]*?</svg\s*>', _strip_svg_if_icon, html, flags=re.IGNORECASE)
    html = re.sub(
        r'<(?:i|span|div)\b[^>]*(?:class|id)=["\'][^"\']*(?:icon|emoji|lucide|fa-|material-icons)[^"\']*["\'][^>]*>[\s\S]*?</(?:i|span|div)\s*>',
        '', html, flags=re.IGNORECASE
    )
    return _ICON_RE.sub('', html)


def _slide_counter_text(slide_num, total_slides=None):
    try:
        number = int(slide_num)
    except (TypeError, ValueError):
        return ''
    try:
        total = int(total_slides)
    except (TypeError, ValueError):
        total = number
    return f'{number:02d} — {max(number, total):02d}'


def _with_data_attribute(open_tag, name):
    if re.search(rf'\b{re.escape(name)}\s*=', open_tag, flags=re.IGNORECASE):
        return open_tag
    return open_tag[:-1] + f' {name}="1">'


def _rewrite_slide_counter(html, slide_type, slide_num, total_slides=None):
    if not html:
        return html
    counter = _slide_counter_text(slide_num, total_slides)
    if not counter:
        return html
    marker = re.compile(
        r'(<(?P<tag>span|div)\b[^>]*\bdata-slide-counter=["\'][^"\']*["\'][^>]*>)'
        r'[\s\S]*?(</(?P=tag)\s*>)', re.IGNORECASE,
    )
    html, replaced = marker.subn(lambda match: match.group(1) + counter + match.group(3), html)
    if replaced:
        return html
    if slide_type == 'section_divider':
        legacy = re.compile(
            r'(<div\b(?=[^>]*bottom:\s*34px)(?=[^>]*left:\s*48px)[^>]*)>'
            r'\s*\d{1,3}\s*[—–-]\s*\d{1,3}\s*</div\s*>', re.IGNORECASE,
        )
        return legacy.sub(lambda match: _with_data_attribute(match.group(1) + '>', 'data-slide-counter')
                          + counter + '</div>', html, count=1)

    footer = re.compile(
        r'(?P<open><(?P<ftag>div|footer)\b[^>]*height:\s*36px[^>]*>)(?P<body>[\s\S]*?)</(?P=ftag)\s*>', re.IGNORECASE,
    )

    def replace_footer(match):
        spans = list(re.finditer(
            r'(?P<open><span\b[^>]*>)(?P<value>\s*\d{1,3}(?:\s*[—–/-]\s*\d{1,3})?\s*)</span\s*>',
            match.group('body'), flags=re.IGNORECASE,
        ))
        if not spans:
            return match.group(0)
        target = spans[-1]
        span_open = _with_data_attribute(target.group('open'), 'data-slide-counter')
        body = (match.group('body')[:target.start()] + span_open + counter + '</span>'
                + match.group('body')[target.end():])
        return _with_data_attribute(match.group('open'), 'data-slide-footer') + body + f"</{match.group('ftag')}>"

    return footer.sub(replace_footer, html, count=1)


def _remove_managed_slide_footer(html):
    return re.sub(
        r'<(?:div|footer)\b[^>]*\bdata-slide-footer=["\'][^"\']*["\'][^>]*>[\s\S]*?</(?:div|footer)\s*>',
        '', html or '', count=1, flags=re.IGNORECASE,
    )


def _slide_element_end(html, opening_match):
    """Return the end offset of one possibly nested HTML element."""
    tag_name = opening_match.group('tag').lower()
    depth = 0
    void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    tag_re = re.compile(r'<(?P<closing>/)?(?P<tag>[a-z][\w:-]*)(?:\s[^>]*)?>', re.IGNORECASE)
    for tag_match in tag_re.finditer(html, opening_match.start()):
        if tag_match.group('tag').lower() != tag_name:
            continue
        if tag_match.group('closing'):
            depth -= 1
            if depth == 0:
                return tag_match.end()
        elif tag_name not in void_tags and not tag_match.group(0).rstrip().endswith('/>'):
            depth += 1
    return len(html)


def _strip_existing_slide_chrome(html):
    """Remove model-authored or stale header/footer elements before rebuilding them."""
    if not html:
        return html
    opening_re = re.compile(r'<(?P<tag>[a-z][\w:-]*)(?P<attrs>\s[^>]*)?>', re.IGNORECASE)
    ranges = []
    for match in opening_re.finditer(html):
        tag = match.group('tag').lower()
        attrs = match.group('attrs') or ''
        classes = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        class_text = (classes.group(1) if classes else '').lower()
        style_match = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        style = (style_match.group(1) if style_match else '').lower().replace(' ', '')
        is_header = (
            tag == 'header'
            or 'slide-header' in class_text
            or re.search(r'\bdata-slide-header\s*=', attrs, re.IGNORECASE)
            or (re.search(r'position:(?:absolute|fixed)', style)
                and re.search(r'top:0(?:px)?', style)
                and re.search(r'height:(?:36|40|48|56|60|64|72|96)px', style))
        )
        is_footer = (
            tag == 'footer'
            or 'slide-footer' in class_text
            or re.search(r'\bdata-slide-footer\s*=', attrs, re.IGNORECASE)
            or (re.search(r'position:(?:absolute|fixed)', style)
                and re.search(r'bottom:0(?:px)?', style)
                and re.search(r'height:(?:30|32|34|36|38|40|42)px', style))
        )
        if is_header or is_footer:
            ranges.append((match.start(), _slide_element_end(html, match)))
    for start, end in reversed(ranges):
        while start > 0 and html[start - 1] in ' \t\r\n':
            start -= 1
        while end < len(html) and html[end] in ' \t\r\n':
            end += 1
        html = html[:start] + html[end:]
    return re.sub(r'\n[ \t]*(?:\n[ \t]*)+', '\n', html)


def _slide_root_surface(html):
    """Read a solid background from the generated slide root for chrome contrast."""
    root = re.search(
        r'<div\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\1[^>]*>',
        str(html or ''), flags=re.IGNORECASE,
    )
    if not root:
        return None
    style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', root.group(0), flags=re.IGNORECASE)
    if not style_match:
        return None
    styles = _inline_style_properties(style_match.group(2))
    return _css_solid_color(styles.get('background-color') or styles.get('background'))


def _is_dark_slide_surface(surface):
    """Return whether a solid surface is dark enough to have carried light text."""
    color = normalize_hex_color(surface, '')
    return bool(color and contrast_ratio('#ffffff', color) >= 4.5)


def _normalize_dark_slide_surface(html, slide_type='content'):
    # Kept as a compatibility shim for older callers; ordinary content is now light.
    return _normalize_light_content_surface(html, slide_type=slide_type)

    """Keep edited/generated dark slides dark instead of wrapping them in white pages.

    This is deliberately limited to content-like slides. Covers, closing slides, section
    dividers, and moodboards have their own image-led contracts and may legitimately use
    white logo backing or other contrast surfaces.
    """
    if not html or slide_type in ('cover', 'closing', 'moodboard', 'section_divider'):
        return html
    surface = _slide_root_surface(html)
    if not _is_dark_slide_surface(surface):
        return html

    root_match = re.search(
        r'<(?P<tag>div)\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\2[^>]*>',
        html, flags=re.IGNORECASE,
    )
    if not root_match:
        return html
    root_tag = root_match.group(0)
    if 'data-slide-surface="dark"' not in root_tag and "data-slide-surface='dark'" not in root_tag:
        root_tag = root_tag[:-1] + ' data-slide-surface="dark">'
        html = html[:root_match.start()] + root_tag + html[root_match.end():]
        root_match = re.search(
            r'<(?P<tag>div)\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\2[^>]*>',
            html, flags=re.IGNORECASE,
        )
    if not root_match:
        return html

    root_end = _slide_element_end(html, root_match)
    inner_start = root_match.end()
    inner_end = max(inner_start, root_end - len('</div>'))
    inner = html[inner_start:inner_end]
    tag_re = re.compile(r'<(?P<closing>/)?(?P<tag>[a-z][\w:-]*)(?P<attrs>\s[^>]*)?>', re.IGNORECASE)
    void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    pieces = []
    cursor = 0
    depth = 0
    for match in tag_re.finditer(inner):
        pieces.append(inner[cursor:match.start()])
        tag = match.group('tag').lower()
        closing = bool(match.group('closing'))
        if closing:
            depth = max(0, depth - 1)
            pieces.append(match.group(0))
            cursor = match.end()
            continue
        attrs = match.group('attrs') or ''
        class_match = re.search(r'\bclass\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE | re.DOTALL)
        class_text = (class_match.group(2) if class_match else '').lower()
        exempt = (
            tag in ('header', 'footer')
            or 'presentation-chrome-logo' in class_text
            or 'logo' in class_text
            or re.search(r'\bdata-slide-(?:header|footer)\s*=', attrs, flags=re.IGNORECASE)
            or re.search(r'\bdata-cover-overlay\s*=', attrs, flags=re.IGNORECASE)
        )
        style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE | re.DOTALL)
        rewritten = match.group(0)
        if style_match and not exempt:
            new_style = _dark_slide_style(style_match.group(2), surface, depth=depth + 1)
            new_attrs = attrs[:style_match.start(2)] + new_style + attrs[style_match.end(2):]
            attrs_start = match.start('attrs') - match.start()
            attrs_end = match.end('attrs') - match.start()
            rewritten = match.group(0)[:attrs_start] + new_attrs + match.group(0)[attrs_end:]
        pieces.append(rewritten)
        if tag not in void_tags and not match.group(0).rstrip().endswith('/>'):
            depth += 1
        cursor = match.end()
    pieces.append(inner[cursor:])
    return html[:inner_start] + ''.join(pieces) + html[inner_end:]


def _light_content_style(style, inherited_surface='#ffffff', depth=1, exempt=False):
    """Repair legacy dark-surface edits while keeping intentional brand blocks intact."""
    if exempt:
        return style, inherited_surface

    def replace_legacy_background(match):
        declaration = match.group(0)
        value_match = re.search(r':\s*([^;]+)', declaration)
        raw_value = value_match.group(1).strip() if value_match else ''
        normalized = raw_value.lower().replace(' ', '')
        if normalized in (
            'transparent', 'rgba(255,255,255,0.08)', 'rgba(255,255,255,.08)',
            'rgba(255,255,255,0.22)', 'rgba(255,255,255,.22)',
        ):
            replacement = '#f8fafc' if depth > 1 else '#ffffff'
            return re.sub(r':\s*[^;]+', ':' + replacement, declaration, count=1)
        return declaration

    style = re.sub(
        r'\bbackground(?:-color)?\s*:\s*[^;]+',
        replace_legacy_background,
        style,
        flags=re.IGNORECASE,
    )
    style = re.sub(
        r'(\bborder(?:-(?:top|right|bottom|left))?\s*:\s*[^;]*?)'
        r'(?:white|#fff(?:fff)?|rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.22\s*\))',
        r'\1#e2e8f0',
        style,
        flags=re.IGNORECASE,
    )

    properties = _inline_style_properties(style)
    surface = _css_solid_color(properties.get('background-color') or properties.get('background')) or inherited_surface
    color_value = properties.get('color')
    color = _css_solid_color(color_value)
    if color and surface and contrast_ratio(color, surface) < 4.5:
        readable = readable_text_color('#1e293b', surface, ('#0f172a', '#334155'))
        style = re.sub(
            r'(\bcolor\s*:)\s*[^;]+', r'\1' + readable, style,
            count=1, flags=re.IGNORECASE,
        )
    return style, surface


def _normalize_light_content_surface(html, slide_type='content'):
    """Make ordinary content slides light; image-led slides keep their own contracts.

    Some stored slides were previously treated as intentionally dark and received a
    transparent/light-text content layer. Rebuild those slides on the normal white
    content canvas, but leave logo contrast containers and image-led slide types alone.
    """
    if not html or slide_type in ('cover', 'closing', 'moodboard', 'section_divider'):
        return html
    root_match = re.search(
        r'<(?P<tag>div)\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\2[^>]*>',
        html, flags=re.IGNORECASE,
    )
    if not root_match:
        return html

    root_tag = root_match.group(0)
    style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', root_tag, flags=re.IGNORECASE | re.DOTALL)
    root_style = style_match.group(2) if style_match else ''
    root_properties = _inline_style_properties(root_style)
    root_surface = _css_solid_color(root_properties.get('background-color') or root_properties.get('background'))
    map_root_background = re.search(
        r'\bbackground(?:-image)?\s*:\s*[^;]*(?:/uploads/maps/|/api/map-images/|##MAP_)[^;]*',
        root_style, flags=re.IGNORECASE,
    )
    preserve_root_background = bool(
        map_root_background and str(slide_type or '').strip().lower().startswith('map_')
    )
    preserved_background = map_root_background.group(0).strip().rstrip(';') if preserve_root_background else ''
    legacy_dark = (
        _is_dark_slide_surface(root_surface)
        or bool(re.search(r'data-slide-surface\s*=\s*["\']dark["\']', root_tag, flags=re.IGNORECASE))
        or bool(re.search(r'\bcolor\s*:\s*(?:#fff(?:fff)?|white)\b', root_style, flags=re.IGNORECASE))
    )
    root_tag = re.sub(r'\sdata-slide-surface\s*=\s*["\']dark["\']', '', root_tag, flags=re.IGNORECASE)
    root_surface_declarations = 'background:#ffffff;'
    if preserved_background:
        root_surface_declarations += preserved_background + ';'
    else:
        root_surface_declarations += 'background-image:none;'
    root_surface_declarations += 'color:#1e293b;'
    root_tag = _set_tag_style(
        root_tag,
        ('background', 'background-color', 'background-image', 'color'),
        root_surface_declarations,
    )
    html = html[:root_match.start()] + root_tag + html[root_match.end():]
    if not legacy_dark:
        return html

    root_match = re.search(
        r'<(?P<tag>div)\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\2[^>]*>',
        html, flags=re.IGNORECASE,
    )
    if not root_match:
        return html
    root_end = _slide_element_end(html, root_match)
    inner_start = root_match.end()
    inner_end = max(inner_start, root_end - len('</div>'))
    inner = html[inner_start:inner_end]
    tag_re = re.compile(r'<(?P<closing>/)?(?P<tag>[a-z][\w:-]*)(?P<attrs>\s[^>]*)?>', re.IGNORECASE)
    void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    pieces = []
    cursor = 0
    surface_stack = ['#ffffff']
    for match in tag_re.finditer(inner):
        pieces.append(inner[cursor:match.start()])
        tag = match.group('tag').lower()
        if match.group('closing'):
            if len(surface_stack) > 1:
                surface_stack.pop()
            pieces.append(match.group(0))
            cursor = match.end()
            continue
        attrs = match.group('attrs') or ''
        class_match = re.search(r'\bclass\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE | re.DOTALL)
        class_text = (class_match.group(2) if class_match else '').lower()
        exempt = (
            tag in ('header', 'footer', 'style', 'script')
            or 'presentation-chrome-logo' in class_text
            or re.search(r'\blogo\b', class_text)
            or re.search(r'\bdata-slide-(?:header|footer)\s*=', attrs, flags=re.IGNORECASE)
            or re.search(r'\bdata-cover-overlay\s*=', attrs, flags=re.IGNORECASE)
        )
        style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE | re.DOTALL)
        rewritten = match.group(0)
        current_surface = surface_stack[-1]
        if style_match and not exempt:
            new_style, current_surface = _light_content_style(
                style_match.group(2), current_surface, depth=len(surface_stack), exempt=False)
            new_attrs = attrs[:style_match.start(2)] + new_style + attrs[style_match.end(2):]
            attrs_start = match.start('attrs') - match.start()
            attrs_end = match.end('attrs') - match.start()
            rewritten = match.group(0)[:attrs_start] + new_attrs + match.group(0)[attrs_end:]
        pieces.append(rewritten)
        if tag not in void_tags and not match.group(0).rstrip().endswith('/>'):
            surface_stack.append(current_surface)
        cursor = match.end()
    pieces.append(inner[cursor:])
    return html[:inner_start] + ''.join(pieces) + html[inner_end:]


def _presentation_chrome_html(title, project_title, company_name, primary, accent,
                              footer_background, footer_text, footer_accent, counter,
                              project_logo=False, slide_surface=None, offer_lang=None):
    """Return the single canonical light header and footer for content slides."""
    # Content chrome stays light regardless of any stale/model-authored root fill.
    # Logo backing is applied independently later by _apply_logo_contrast_styles.
    lang = OFFER_LANG_ENGLISH if offer_lang == OFFER_LANG_ENGLISH else OFFER_LANG_ARABIC
    chrome_dir = 'ltr' if lang == OFFER_LANG_ENGLISH else 'rtl'
    chrome_text = primary
    chrome_accent = accent
    header_style = f'position:absolute;top:0;right:0;left:0;height:56px;background:#ffffff;border-bottom:2px solid {primary};'
    footer_style = f'background:{footer_background};border-top:1px solid #e2e8f0;'
    footer_surface_text = footer_text
    footer_surface_accent = footer_accent

    logo_style = (
        'height:40px;width:auto;max-width:122px;object-fit:contain;display:inline-block;'
        'background:#ffffff;border-radius:6px;padding:3px 7px;box-sizing:border-box;'
    )
    project_logo_html = (
        '<img class="presentation-chrome-logo" src="##PROJECT_LOGO##" alt="" '
        f'style="{logo_style}" />'
    ) if project_logo else ''
    header = (
        f'<header class="slide-header" data-slide-header="1" dir="{chrome_dir}" '
        f'style="{header_style}'
        'display:flex;align-items:center;justify-content:space-between;padding:0 24px;'
        'box-sizing:border-box;z-index:10;overflow:hidden;">'
        '<div style="display:flex;align-items:center;gap:10px;min-width:0;direction:ltr;">'
        f'<img class="presentation-chrome-logo" src="##LOGO##" alt="" style="{logo_style}" />'
        f'{project_logo_html}'
        f'<span style="width:3px;height:28px;background:{chrome_accent};display:inline-block;flex:0 0 auto;"></span>'
        f'<span style="font-size:16px;font-weight:700;color:{chrome_text};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;direction:{chrome_dir};">{title}</span>'
        '</div></header>'
    )
    footer = (
        f'<footer class="slide-footer" data-slide-footer="1" dir="{chrome_dir}" '
        f'style="position:absolute;bottom:0;right:0;left:0;height:36px;{footer_style}'
        f'display:flex;align-items:center;justify-content:space-between;padding:0 24px;'
        'box-sizing:border-box;z-index:10;overflow:hidden;">'
        f'<span style="font-size:12px;font-weight:700;color:{footer_surface_text};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:62%;">{project_title}</span>'
        f'<span data-slide-counter="1" dir="ltr" style="display:inline-flex;align-items:center;justify-content:center;min-width:72px;font-size:12px;font-weight:700;color:{footer_surface_accent};text-align:center;">{counter}</span>'
        '</footer>'
    )
    return header, footer


def _ensure_managed_chrome(html, slide_title=None, slide_num=None, total_slides=None,
                           branding=None, project_data=None, tenant_id=None):
    """Inject the single canonical header/footer for a content slide.

    The one chrome authority: postprocess_slide() calls this for every new
    slide, and renumber_presentation_slides() calls it for stored slides that
    predate it, so old and new decks converge on one header and footer.
    Callers must strip any stale chrome first via _strip_existing_slide_chrome.
    """
    lang = resolve_offer_lang(project_data if isinstance(project_data, dict) else None)
    if slide_title:
        title = html_lib.escape(str(slide_title))
    elif lang == OFFER_LANG_ENGLISH:
        title = html_lib.escape(f'Slide {slide_num}' if slide_num else 'Title')
    else:
        title = html_lib.escape(f'شريحة {slide_num}' if slide_num else 'العنوان')
    primary = '#7A0C0C'
    accent = '#C4A35A'
    company_name = 'منافع الاقتصادية للعقار'

    if branding is None and tenant_id:
        branding = db.get_branding(tenant_id) or {}
    if branding:
        primary = branding.get('primary_color') or primary
        accent = branding.get('accent_color') or accent
        company_name = branding.get('company_name') or company_name
        if not company_name:
            tenant = db.get_tenant(tenant_id) if tenant_id else None
            company_name = tenant.get('company_name') if tenant else 'منافع الاقتصادية للعقار'

    primary = normalize_hex_color(primary, '#7a0c0c')
    accent = normalize_hex_color(accent, '#c4a35a')
    footer_background = dark_surface_color(primary, branding.get('secondary_color') if branding else None)
    footer_text = readable_text_color('#ffffff', footer_background, ('#0f172a',))
    footer_accent = readable_text_color(accent, footer_background, (footer_text,))
    footer_number = _slide_counter_text(slide_num, total_slides)
    project_source = project_data if isinstance(project_data, dict) else {}
    project_title = html_lib.escape(str(
        project_source.get('project_name') or project_source.get('projectName') or 'THE VIEW'
    ))
    header_html, footer_html = _presentation_chrome_html(
        title, project_title, html_lib.escape(str(company_name)), primary, accent,
        footer_background, footer_text, footer_accent, footer_number,
        project_logo=bool(_project_logo_reference(project_source)),
        slide_surface=_slide_root_surface(html),
        offer_lang=lang,
    )
    html = re.sub(r'(<div[^>]*class=["\']slide["\'][^>]*>)', r'\1\n' + header_html, html, count=1)
    html = re.sub(r'(</div>\s*)$', '\n' + footer_html + r'\1', html, count=1)
    return html


def _project_logo_reference(project_data):
    source = project_data if isinstance(project_data, dict) else {}
    value = str(source.get('project_logo') or source.get('projectLogo') or '').strip()
    if value:
        return value
    meta = source.get('project_logo_file_meta')
    if isinstance(meta, dict) and str(meta.get('path') or '').strip():
        return str(meta.get('path')).strip()
    file_id = str(source.get('project_logo_file_id') or '').strip()
    return f'/api/project-files/{file_id}' if file_id else ''


def _strip_internal_financial_notes(html):
    """Remove model-facing financial instructions that must not reach the client deck."""
    if not html:
        return html
    note_re = re.compile(
        r'القيم\s+معروضة[\s\S]{0,180}?دون\s+إعادة\s+حساب[\s\S]{0,60}?تقريب',
        re.IGNORECASE,
    )
    opening_re = re.compile(r'<(?P<tag>div|span|p|small|section|aside)\b(?P<attrs>\s[^>]*)?>', re.IGNORECASE)
    while True:
        note = note_re.search(html)
        if not note:
            break
        container = None
        for candidate in reversed(list(opening_re.finditer(html, 0, note.start()))):
            attrs = candidate.group('attrs') or ''
            if re.search(r'\bclass\s*=\s*["\'][^"\']*\bslide\b', attrs, re.IGNORECASE):
                continue
            end = _slide_element_end(html, candidate)
            if end >= note.end():
                container = (candidate.start(), end)
                break
        if container:
            html = html[:container[0]] + html[container[1]:]
        else:
            html = html[:note.start()] + html[note.end():]
    return html


def _is_market_slide(slide_type='', slide_title='', content_source=''):
    text = ' '.join(str(value or '') for value in (slide_type, slide_title, content_source)).lower()
    return bool(re.search(
        r'(?:تحليل السوق|دراسة السوق|مقارنة المنافسين|المنافسين|الفجوة السوقية|السوقية|market|competitor)',
        text, flags=re.IGNORECASE,
    ))


def _is_fixed_competitor_comparison(content_source='', slide_title=''):
    """Identify the one market slide whose visual contract is fixed."""
    text = ' '.join(str(value or '') for value in (content_source, slide_title)).lower()
    return bool(
        str(content_source or '').strip() == 'market_study_data.competitors'
        or bool(re.fullmatch(r'market_study_data\.competitors(?::\d+:\d+)?', str(content_source or '').strip()))
        or re.search(r'(?:مقارنة\s+المنافسين|المنافسين|competitor)', text, flags=re.IGNORECASE)
    )


def _split_top_level_html(html):
    """Split an HTML fragment into direct-child elements without reformatting it."""
    if not html:
        return []
    tag_re = re.compile(r'<(?P<closing>/)?(?P<tag>[a-z][\w:-]*)(?:\s[^>]*)?>', re.IGNORECASE)
    void_tags = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'param', 'source', 'track', 'wbr',
    }
    parts = []
    depth = 0
    start = None
    for match in tag_re.finditer(html):
        tag = match.group('tag').lower()
        is_closing = bool(match.group('closing'))
        if is_closing:
            if depth:
                depth -= 1
                if depth == 0 and start is not None:
                    parts.append(html[start:match.end()])
                    start = None
            continue
        if depth == 0:
            start = match.start()
            if tag in void_tags or match.group(0).rstrip().endswith('/>'):
                parts.append(html[start:match.end()])
                start = None
                continue
        if tag not in void_tags and not match.group(0).rstrip().endswith('/>'):
            depth += 1
    if start is not None:
        parts.append(html[start:])
    return parts
