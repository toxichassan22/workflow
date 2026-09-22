

def _normalize_market_content_layout(html, slide_type='', slide_title='', content_source=''):
    """Center market content while leaving SOL's internal visual composition intact.

    The model owns the design inside the content frame. This wrapper only gives
    that design a stable vertical lane between the managed header and footer,
    and converts the occasional absolute-positioned text block into normal flow
    when it would otherwise overlap the rest of the market narrative.
    """
    if (
        not html
        or not _is_market_slide(slide_type, slide_title, content_source)
        or _is_fixed_competitor_comparison(content_source, slide_title)
        or 'data-market-auto-fit="1"' in html
    ):
        return html

    root_match = re.search(
        r'<(?P<tag>div)\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\2[^>]*>',
        html, flags=re.IGNORECASE,
    )
    if not root_match:
        return html
    root_end = _slide_element_end(html, root_match)
    root_close_start = html.rfind('</div>', root_match.end(), root_end)
    if root_close_start <= root_match.end():
        return html

    root_open = root_match.group(0)
    inner = html[root_match.end():root_close_start]
    parts = _split_top_level_html(inner)
    if not parts:
        return html

    preserved = []
    body = []
    for part in parts:
        lowered = part.lower()
        if (
            re.match(r'\s*<style\b', lowered)
            or 'data-slide-header' in lowered
            or 'data-slide-footer' in lowered
            or re.search(r'class\s*=\s*["\'][^"\']*slide-(?:header|footer)', lowered)
        ):
            preserved.append(part)
        else:
            body.append(part)
    body = [part for part in body if part.strip()]
    if not body:
        return html

    if 'data-market-auto-fit=' not in root_open:
        root_open = root_open[:-1] + ' data-market-auto-fit="1">'
    root_open = _set_tag_style(
        root_open,
        ('display', 'flex-direction', 'align-items', 'padding', 'margin', 'box-sizing'),
        'display:flex!important;flex-direction:column!important;align-items:stretch!important;'
        'padding:0!important;margin:0!important;box-sizing:border-box!important;',
    )
    body_html = ''.join(body)
    if 'data-market-work-summary' in body_html:
        # Older saved fallback slides used a grid with fixed height. Some PDF
        # engines interpret that grid differently from the browser and let the
        # decision card sit over the narrative. Convert only that emergency
        # marker to ordinary flow; SOL-authored market compositions remain
        # untouched.
        def repair_work_summary(match):
            return _set_tag_style(
                match.group(0),
                ('display', 'grid-template-columns', 'grid-template-areas', 'gap',
                 'min-height', 'max-height', 'overflow'),
                'display:block!important;min-height:0!important;max-height:none!important;overflow:visible!important;',
            )

        body_html = re.sub(
            r'<div\b[^>]*\bdata-market-work-summary\s*=\s*["\']1["\'][^>]*>',
            repair_work_summary,
            body_html,
            count=1,
            flags=re.IGNORECASE,
        )
        body_html = re.sub(
            r'grid-area\s*:\s*(?:aside|main)\s*;?',
            '',
            body_html,
            flags=re.IGNORECASE,
        )
    absolute_body = bool(re.search(r'position\s*:\s*(?:absolute|fixed)', body_html, flags=re.IGNORECASE))
    repair_css = ''
    if absolute_body:
        selector_scope = '[data-market-auto-fit="1"] [data-market-auto-fit-content="1"]'
        repair_css = (
            '<style data-market-auto-flow="1">'
            f'{selector_scope}[style*="position:absolute"],'
            f'{selector_scope}[style*="position: absolute"],'
            f'{selector_scope}[style*="position:fixed"],'
            f'{selector_scope}[style*="position: fixed"]{{'
            'position:relative!important;inset:auto!important;'
            'top:auto!important;right:auto!important;bottom:auto!important;left:auto!important;'
            'transform:none!important;height:auto!important;min-height:0!important;max-height:none!important;'
            '}'
            '</style>'
        )

        # An inline `!important` declaration wins over any injected stylesheet,
        # so repair absolute/fixed blocks in the HTML itself as well.  This is
        # intentionally limited to elements that SOL positioned absolutely;
        # normal-flow composition, widths, colors, and spacing remain SOL's.
        def repair_inline_absolute(match):
            tag = match.group(0)
            style_match = re.search(r'style\s*=\s*(["\'])(.*?)\1', tag, flags=re.IGNORECASE)
            if not style_match or not re.search(
                    r'position\s*:\s*(?:absolute|fixed)', style_match.group(2), flags=re.IGNORECASE):
                return tag
            return _set_tag_style(
                tag,
                ('position', 'inset', 'top', 'right', 'bottom', 'left', 'transform',
                 'height', 'min-height', 'max-height'),
                'position:relative!important;inset:auto!important;'
                'top:auto!important;right:auto!important;bottom:auto!important;left:auto!important;'
                'transform:none!important;height:auto!important;min-height:0!important;max-height:none!important;',
            )

        body_html = re.sub(
            r'<(?!/|!|\?)[a-z][^>]*>',
            repair_inline_absolute,
            body_html,
            flags=re.IGNORECASE,
        )
    frame = (
        '<div data-market-auto-fit-content="1" style="flex:1 1 auto;min-height:0;'
        'width:calc(100% - 72px);margin:0 auto;padding:64px 0 52px;box-sizing:border-box;'
        'display:flex;flex-direction:column;justify-content:safe center;overflow:visible;">'
        + body_html + '</div>'
    )
    replacement = root_open + ''.join(preserved) + repair_css + frame + html[root_close_start:root_end]
    return html[:root_match.start()] + replacement + html[root_end:]


def _strip_market_slide_media(html):
    """Keep competitor logos while removing maps and unrelated images from market slides."""
    protected_images = []

    def protect_competitor_region(match):
        region = match.group(0)

        def stash_image(image_match):
            marker = f'__MARKET_COMPETITOR_IMAGE_{len(protected_images)}__'
            protected_images.append((marker, image_match.group(0)))
            return marker

        return re.sub(r'<img\b[^>]*>', stash_image, region, flags=re.IGNORECASE)

    # Resolved logos no longer contain the token name (for example they may be
    # /uploads/creative/.../logo.png), so protect the semantic competitor
    # containers before the generic market-image cleanup runs. This also keeps
    # already-saved presentations exportable when they are re-numbered.
    html = re.sub(
        r'<(?P<tag>table|div)\b[^>]*\bdata-competitor-(?:table|logos)\b[^>]*>.*?</(?P=tag)>',
        protect_competitor_region, html, flags=re.IGNORECASE | re.DOTALL,
    )

    # A requested watermark is presentation decoration, not market content.
    # Protect its image by its containing element: the resolved URL need not
    # contain the word logo and the image itself may carry no class.
    html = re.sub(
        r'<div\b(?=[^>]*(?:\bdata-slide-watermark\s*=\s*["\']true["\']|'
        r'\bclass\s*=\s*["\'][^"\']*\bslide-watermark\b))[^>]*>.*?</div\s*>',
        protect_competitor_region, html, flags=re.IGNORECASE | re.DOTALL,
    )

    def keep_image(match):
        tag = match.group(0)
        lowered_tag = tag.lower()
        src_match = re.search(r'\bsrc\s*=\s*["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        src = str(src_match.group(1) if src_match else '').lower()
        # The managed company/project logos are part of the fixed chrome, not
        # market content. They must survive the market media scrub, including
        # the second pass after the chrome has been injected.
        if (
            'presentation-chrome-logo' in lowered_tag
            or '##logo##' in src
            or '##project_logo##' in src
        ):
            return tag
        if 'competitor_logo' in src:
            return tag
        return ''

    html = re.sub(
        r'background-image\s*:\s*url\s*\([^)]*(?:map_|/uploads/maps|image_cover|moodboard|land_photo|plan_image|interior)[^)]*\)',
        'background-image:none', html, flags=re.IGNORECASE,
    )
    html = re.sub(r'<img\b[^>]*>', keep_image, html, flags=re.IGNORECASE)
    html = re.sub(r'#*MAP_(?:OVERVIEW|LANDMARKS|ACCESS|CATCHMENT)#*', '', html, flags=re.IGNORECASE)
    for marker, image in protected_images:
        html = html.replace(marker, image)
    return html


def postprocess_slide(html, slide_type, slide_num=None, slide_title=None, total_slides=None,
                       tenant_id=None, branding=None, project_data=None, content_source=None):
    """Post-process a slide while keeping cover and closing free of header/footer.

    slide_type is the semantic type (cover, index, content, closing, ...).
    slide_num / total_slides are used for page numbers and cover/closing detection.
    """
    # No icons are ever produced: strip any SVG, icon markup and emoji the model emitted.
    html = _strip_presentation_icons(html)

    is_market = _is_market_slide(slide_type, slide_title, content_source)
    is_market_content = is_market and slide_type != 'section_divider'

    # Enforce image/placeholder rules. Market slides are text/table-only and
    # must not receive a map placeholder merely because an old slide type was
    # map_*.
    html = _block_external_images(html)
    if not is_market_content:
        html = _ensure_map_placeholder(html, slide_type)
    else:
        html = _strip_market_slide_media(html)

    normalized_title = str(slide_title or '').strip().lower()
    is_cover = slide_type == 'cover' or (
        slide_type not in ('section_divider', 'closing', 'index', 'content', 'overview', 'site_specs')
        and int(slide_num or 0) == 1
    ) or (
        slide_type not in ('section_divider', 'closing', 'index')
        and bool(re.search(r'غلاف|cover|front', normalized_title))
    )
    is_closing = slide_type == 'closing' or (
        slide_type not in ('cover', 'section_divider', 'index')
        and (
            bool(re.search(r'ختام|closing|شكراً|thanks', normalized_title))
            or (total_slides is not None and int(slide_num or 0) == int(total_slides) and int(slide_num or 0) > 1)
        )
    )
    is_cover_or_closing = is_cover or is_closing
    # Ordinary content slides use the light report canvas. Covers, closings, dividers,
    # and moodboards keep their image-led contracts.
    if not is_cover_or_closing and slide_type not in ('moodboard', 'section_divider'):
        html = _normalize_light_content_surface(html, slide_type=slide_type)
    # Sol and the deterministic financial renderer use different chrome. Remove
    # both forms first so preview and export always receive the same one.
    if slide_type not in ('cover', 'closing', 'moodboard', 'section_divider') and not is_cover_or_closing:
        html = _strip_existing_slide_chrome(html)
    html = _strip_internal_financial_notes(html)
    if is_cover_or_closing:
        html = _normalize_brand_overlay(html, branding)
    if is_cover:
        html = _normalize_cover_overlay_element(html, branding)
        def _strip_cover_extra_images(match):
            tag = match.group(0)
            src_match = re.search(r'src=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            src = (src_match.group(1) if src_match else '').strip()
            if src.lower().startswith('data:') or src.lower().startswith('blob:'):
                return tag
            tag_without_src = re.sub(r'src=["\'][^"\']*["\']', '', tag, flags=re.IGNORECASE)
            if '##LOGO##' in src or '##PROJECT_LOGO##' in src or 'logo' in tag_without_src.lower():
                return tag
            return ''
        html = re.sub(r'<img\b[^>]*>', _strip_cover_extra_images, html, flags=re.IGNORECASE)
        for _ in range(3):
            html = re.sub(r'<(?:div|figure|picture)\b(?![^>]*(?:\bslide\b|data-cover-overlay|background|##IMAGE_COVER##|cover-bg))[^>]*>\s*</(?:div|figure|picture)>', '', html, flags=re.IGNORECASE)
    if is_closing:
        html = re.sub(
            r'<(p|h[1-6]|span)\b[^>]*>[^<]*(?:فرصة\s+(?:واعدة|مشروطة)|واعدة\s+بشروط|بشروط)[^<]*</\1\s*>',
            '', html, flags=re.IGNORECASE,
        )
        html = _remove_unapproved_contact_elements(html, project_data)

    # Strip repetitive badges like "* مشروع متعدد الاستخدامات *" or floating project type chips from content slides
    if not is_cover and slide_type not in ('cover', 'overview'):
        html = re.sub(
            r'<(?:div|span|p|small)\b[^>]*>\s*(?:[*•-]?\s*(?:مشروع\s+)?متعدد\s+الاستخدامات\s*[*•-]?)\s*</(?:div|span|p|small)>',
            '', html, flags=re.IGNORECASE
        )
        html = re.sub(
            r'<(?:div|span|p|small|button|a)\b[^>]*class=["\']?[^"\'>]*(?:badge|tag|chip|pill|meta-pill|type-tag)[^"\'>]*[^>]*>[\s\S]*?(?:مشروع\s+متعدد\s+الاستخدامات|متعدد\s+الاستخدامات)[\s\S]*?</(?:div|span|p|small|button|a)>',
            '', html, flags=re.IGNORECASE
        )

    # Ensure map containers are centered without awkward crop shifts
    if 'MAP_' in html or (isinstance(slide_type, str) and slide_type.startswith('map_')):
        html = _map_media_contain(html)

    if '<table' in html.lower():
        html = _normalize_table_readability(html)

    # Clean out empty/broken img tags across all slides
    html = re.sub(
        r'<img\b[^>]*(?:src=["\']\s*["\']|src=["\']#(?:["\']|$)|\bsrc=["\'](?:undefined|null|none)["\'])[^>]*>',
        '',
        html,
        flags=re.IGNORECASE
    )

    def _strip_srcless_img(match):
        tag = match.group(0)
        if 'src=' not in tag.lower():
            return ''
        return tag
    html = re.sub(r'<img\s[^>]*>', _strip_srcless_img, html, flags=re.IGNORECASE)

    # Content/map/site slides get one canonical header/footer; cover, dividers,
    # moodboards and closing keep their own image-led layouts.
    if slide_type not in ('cover', 'closing', 'moodboard', 'section_divider') and not is_cover_or_closing:
        html = _ensure_managed_chrome(
            html, slide_title=slide_title, slide_num=slide_num, total_slides=total_slides,
            branding=branding, project_data=project_data, tenant_id=tenant_id,
        )

    if is_market_content:
        html = _normalize_market_content_layout(
            html, slide_type=slide_type, slide_title=slide_title,
            content_source=content_source,
        )

    # The market and SWOT section dividers use the same approved full-bleed
    # cover treatment as the other dividers.  The market-media scrub applies to
    # content slides only; applying it to a divider removes ##IMAGE_COVER## and
    # leaves the divider as a blank solid panel.
    if is_market_content:
        html = _strip_market_slide_media(html)

    # Repair any remaining unreadable text on the light canvas in place — including
    # colors coming from <style>-block rules — instead of paying for a model retry.
    # Covers, closings, dividers and moodboards keep their image-led light-on-dark
    # text untouched.
    if slide_type not in ('cover', 'closing', 'moodboard', 'section_divider') and not is_cover_or_closing:
        html = _repair_slide_text_contrast(html)

    return html


def _designer_preserves_html(item):
    html = str(item.get('html') or '')
    return bool(
        item.get('_designer_keep_html') or item.get('is_custom')
        or item.get('keep_html') or item.get('custom_html')
        or 'data-visual-media-caption="1"' in html
    )


def _rewrite_preserved_counter(html, slide_type, slide_num, total_slides):
    """Change numeric text only, retaining nested counter markup and its styles."""
    counter = _slide_counter_text(slide_num, total_slides)
    if not counter or not html:
        return html
    opening = re.compile(r'<(?P<tag>[a-z][\w:-]*)\b[^>]*\bdata-slide-counter\s*=\s*["\'][^"\']*["\'][^>]*>', re.IGNORECASE)
    matches = list(opening.finditer(html))
    if not matches:
        # Upgrade only an existing legacy footer/divider, never create chrome.
        return _rewrite_slide_counter(html, slide_type, slide_num, total_slides)
    for match in reversed(matches):
        end = _slide_element_end(html, match)
        close = html.rfind('</', match.end(), end)
        if close < match.end():
            continue
        body = html[match.end():close]
        text = re.sub(r'<[^>]*>', '', body).strip()
        if not re.fullmatch(r'\d+(?:\s*[—–/\-]\s*\d+)?', text):
            continue
        values = iter(counter.split(' — ') if re.search(r'[—–/\-]', text) else [counter])
        parts = re.split(r'(<[^>]*>)', body)
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r'\d+', lambda m: next(values, m.group(0)), parts[i])
        html = html[:match.end()] + ''.join(parts) + html[close:]
    return html


def _refresh_preserved_index(html, entries, branding=None, project_data=None):
    """Synchronize managed rows, not the index canvas or surrounding custom content."""
    row_re = re.compile(r'<(?P<tag>[a-z][\w:-]*)\b[^>]*\bdata-index-section\s*=\s*["\'](?P<key>[^"\']+)["\'][^>]*>', re.IGNORECASE)
    rows = [(m, _slide_element_end(html, m)) for m in row_re.finditer(html)]
    entries = [e for e in (entries or []) if isinstance(e, dict)]
    if not entries:
        return html
    if not rows:
        return build_index_slide({'index_entries': entries}, 2, 2, branding, project_data)
    by_key = {m.group('key'): html[m.start():end] for m, end in rows}
    canonical = build_index_slide({'index_entries': entries}, 1, 1, branding, project_data)
    fallback = {m.group('key'): canonical[m.start():_slide_element_end(canonical, m)]
                for m in row_re.finditer(canonical)}
    ordered = [by_key.get(e['section_key'], fallback.get(e['section_key'], '')) for e in entries]
    for i in range(len(rows) - 1, -1, -1):
        match, end = rows[i]
        replacement = (''.join(ordered[i:]) if i == len(rows) - 1
                       else ordered[i] if i < len(ordered) else '')
        html = html[:match.start()] + replacement + html[end:]
    pages = {str(e.get('section_key')): e.get('page') for e in entries}
    page_re = re.compile(r'(<(?P<tag>[a-z][\w:-]*)\b[^>]*\bdata-index-page\s*=\s*["\'](?P<key>[^"\']+)["\'][^>]*>)(?P<body>[^<]*)(</(?P=tag)\s*>)', re.IGNORECASE)

    def update_page(match):
        page = pages.get(match.group('key'))
        if page is None:
            return match.group(0)
        body = re.sub(r'\d+', f'{int(page):02d}', match.group('body'), count=1)
        return match.group(1) + body + match.group(5)

    return page_re.sub(update_page, html)


def finalize_designer_slide_html(html, slide_type, project_data, branding, creative_images=None,
                                 map_placeholders=None, tenant_id=None, slide_num=None, slide_title=None,
                                 total_slides=None, content_source=None, allow_all_maps=False):
    """Finalize a designer edit without regenerating its content or visual design.

    Safety and company/project logo compliance remain mandatory. Only logo
    images may receive policy backing/sizing; user surfaces, tables, numbers,
    media ownership and existing chrome are never normalized here. Save/export
    numbering must use the preservation branch, not call this helper again.
    """
    if not html:
        return html
    project_data = project_data or {}
    branding = branding or {}
    html = _strip_presentation_icons(_block_external_images(html))
    if map_placeholders:
        html = _replace_map_placeholders(html, map_placeholders)
    # Resolve only tokens already present. The generation resolver can otherwise
    # insert a cover, a moodboard or competitor logos that the user removed.
    html = IMAGE_TOKEN_RE.sub(
        lambda m: m.group(0) if 'LOGO' in m.group(0).upper() and m.group(0).upper() in ('##LOGO##', '##PROJECT_LOGO##')
        else _replace_creative_image_placeholders(m.group(0), creative_images or {}, 'content'), html)
    project_logo = _project_logo_reference(project_data)
    company_logo = resolve_logo_in_html('##LOGO##', tenant_id, _branding_cache=branding)
    company_sources = {company_logo, branding.get('logo_path'), branding.get('logo'), branding.get('logo_url'), '/assets/logo.png'}
    found = set()
    hero = slide_type in ('cover', 'closing', 'section_divider')
    size = 80 if hero else 40 if slide_type == 'moodboard' else 48
    dark = dark_surface_color(branding.get('primary_color'), branding.get('secondary_color'))

    def compliant_logo(match):
        tag = match.group(0)
        src_match = re.search(r'\bsrc\s*=\s*(["\'])(.*?)\1', tag, re.IGNORECASE)
        if not src_match:
            return tag
        src = html_lib.unescape(src_match.group(2))
        if src == '##PROJECT_LOGO##' or (project_logo and src == project_logo):
            role, url, tone = 'project', project_logo, project_data.get('_project_logo_tone')
        elif src == '##LOGO##' or src in company_sources:
            role, url, tone = 'company', company_logo, project_data.get('_company_logo_tone') or branding.get('_logo_tone')
        else:
            return tag
        if not url:
            return ''
        found.add(role)
        tag = tag[:src_match.start(2)] + html_lib.escape(url, quote=True) + tag[src_match.end(2):]
        background = dark if str(tone).lower() == 'light' else '#ffffff'
        return _set_tag_style(tag, ('height', 'max-height', 'background', 'background-color', 'padding', 'border-radius', 'box-sizing', 'object-fit'),
                              f'height:{size}px!important;max-height:{size}px!important;background:{background}!important;'
                              'padding:4px 10px!important;border-radius:8px!important;box-sizing:border-box!important;object-fit:contain!important;')

    html = re.sub(r'<img\b[^>]*>', compliant_logo, html, flags=re.IGNORECASE)
    missing = ''.join(f'<img src="{token}" alt="">' for role, token in
                      [('company', '##LOGO##'), ('project', '##PROJECT_LOGO##')]
                      if role not in found and (role == 'company' or project_logo))
    if missing:
        missing = re.sub(r'<img\b[^>]*>', compliant_logo, missing)
        overlay = ('<div data-designer-managed-logos="1" style="position:absolute;top:8px;left:24px;'
                   'display:flex;gap:10px;z-index:10;">' + missing + '</div>')
        html = re.sub(r'(<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bslide\b[^"\']*["\'][^>]*>)',
                      lambda m: m.group(0) + overlay, html, count=1, flags=re.IGNORECASE)
    html = _rewrite_preserved_counter(html, slide_type, slide_num, total_slides)
    # Existing header/footer markup is authoritative. Mark it without repainting.
    for tag, marker in [('header', 'data-slide-header'), ('footer', 'data-slide-footer')]:
        html = re.sub(rf'<{tag}\b[^>]*>', lambda m: _with_data_attribute(m.group(0), marker), html, flags=re.IGNORECASE)
    if slide_type not in ('cover', 'closing', 'moodboard') and not re.search(r'\bdata-slide-counter\s*=', html, re.IGNORECASE):
        counter = _slide_counter_text(slide_num, total_slides)
        if counter:
            counter_html = '<span data-slide-counter="1" dir="ltr">' + counter + '</span>'
            if re.search(r'</footer\s*>', html, re.IGNORECASE):
                html = re.sub(r'</footer\s*>', lambda m: counter_html + m.group(0), html, count=1, flags=re.IGNORECASE)
            else:
                footer = ('<footer data-slide-footer="1" style="position:absolute;bottom:8px;left:24px;">'
                          + counter_html + '</footer>')
                html = re.sub(r'(</div>\s*)$', lambda m: footer + m.group(0), html, count=1, flags=re.IGNORECASE)
    return _drop_unresolved_image_placeholders(html)


def finalize_slide_html(html, slide_type, project_data, branding, creative_images=None,
                        map_placeholders=None, tenant_id=None, slide_num=None, slide_title=None,
                        total_slides=None, content_source=None, allow_all_maps=False):
    """Unified post-processing pipeline for every generated slide."""
    if _is_fixed_competitor_comparison(content_source, slide_title):
        market = _market_state(project_data)
        competitors = market.get('competitors') if isinstance(market, dict) else []
        competitors = competitors if isinstance(competitors, list) else []
        has_named_competitors = any(_competitor_name(item) for item in competitors if isinstance(item, dict))
        # A stale/AI-authored competitor slide must never ship without the
        # agreed table. Keep the original HTML only for legacy logo-only calls
        # that carry no market rows to rebuild from.
        if 'data-competitor-table' not in str(html or '').lower() and (has_named_competitors or not creative_images):
            html = _build_sol_horizontal_bar_slide(
                {
                    'title': slide_title or ('Competitor Comparison' if resolve_offer_lang(project_data if isinstance(project_data, dict) else None) == OFFER_LANG_ENGLISH else 'مقارنة المنافسين'),
                    'type': 'content',
                    'section_key': 'market',
                    'design_style': 'chart',
                    'chart_type': 'horizontal_bar',
                    'content_source': content_source or 'market_study_data.competitors',
                    'source_table': 'competitors',
                },
                project_data if isinstance(project_data, dict) else {},
                branding,
                slide_num=slide_num,
                total_slides=total_slides,
            )
    html = _canonicalize_slide_root_class(html)
    is_map_summary = (
        (isinstance(content_source, str) and (content_source.startswith('site_analysis') or content_source.startswith('executive_content.summary')))
        and (
            'data-map-summary-background' in str(html or '')
            or 'data-map-summary-card' in str(html or '')
            or ('##MAP_' in str(html or '') and 'grid-template-columns' not in str(html or ''))
            or (bool(re.search(r'/uploads/maps/|/api/map-images/', str(html or ''))) and 'grid-template-columns' not in str(html or ''))
        )
    )
    if is_map_summary:
        html = _ensure_map_summary_structure(html)
    html = postprocess_slide(
        html, slide_type, slide_num=slide_num, slide_title=slide_title,
        total_slides=total_slides, tenant_id=tenant_id, branding=branding,
        project_data=project_data, content_source=content_source
    )
    if (not _is_market_slide(slide_type, slide_title, content_source)
            and isinstance(slide_type, str) and (slide_type.startswith('map_') or slide_type == 'site_specs')
            or (isinstance(content_source, str) and (content_source.startswith('site_analysis') or content_source == 'location_detail'))
            or (isinstance(content_source, str) and content_source.startswith('executive_content.summary') and is_map_summary)):
        html = _inject_location_data_timestamp(html, project_data)
    html = _strip_unplanned_map_media(
        html, slide_type, content_source=content_source, slide_title=slide_title,
        allow_all_maps=allow_all_maps)
    if map_placeholders:
        html = _replace_map_placeholders(html, map_placeholders)
    if (not _is_market_slide(slide_type, slide_title, content_source)
            and isinstance(slide_type, str) and slide_type.startswith('map_')) or is_map_summary:
        html = _map_media_contain(html)
    if is_map_summary:
        html = _normalize_map_summary_layout(
            html,
            str((project_data or {}).get('_map_marker_side') or 'right'),
            full_width=False,
        )
    html = _apply_logo_contrast_styles(html, branding, project_data, slide_type)
    creative_images = dict(creative_images) if isinstance(creative_images, dict) else {}
    if not creative_images.get('cover'):
        p_cover = _extract_cover_image_url(project_data, creative_images)
        if p_cover:
            creative_images['cover'] = p_cover
    html = _replace_creative_image_placeholders(html, creative_images, slide_type, content_source)
    html = _replace_data_placeholders(html, project_data, branding)
    html = resolve_logo_in_html(
        html, tenant_id, _branding_cache=branding,
        project_logo=_project_logo_reference(project_data),
    )
    html = _format_presentation_numeric_text(html)
    html = _drop_unresolved_image_placeholders(html)
    return _unwrap_spurious_map_summary_cards(html)


# Fixed watermark gray shared with app._apply_slide_watermark: any logo renders
# as a flat #888888 silhouette (alpha preserved), so light logos stay visible.
WATERMARK_GRAY_FILTER = 'grayscale(100%) brightness(0) invert(53.3%)'


def _normalize_watermark_ink(html):
    """Upgrade saved watermark overlays to the fixed readable gray.

    Marks stored before the gray rule carry older filters; rewriting the filter
    declaration inside the overlay (and only there) heals them on the next
    open/save/export without re-applying the watermark.
    """
    if not html or 'watermark' not in str(html).lower():
        return html
    source = str(html)

    def heal_overlay(match):
        overlay = match.group(0)
        healed, count = re.subn(
            r'filter\s*:\s*[^;]+',
            'filter:' + WATERMARK_GRAY_FILTER,
            overlay,
            count=1,
            flags=re.IGNORECASE,
        )
        return healed if count else overlay

    source = re.sub(
        r'<div\b[^>]*\bdata-slide-watermark=["\']true["\'][^>]*>[\s\S]*?</div\s*>',
        heal_overlay, source, flags=re.IGNORECASE,
    )
    return re.sub(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bslide-watermark\b[^"\']*["\'][^>]*>[\s\S]*?</div\s*>',
        heal_overlay, source, flags=re.IGNORECASE,
    )


def _slides_carry_arabic(slides, limit=20000):
    """True when the deck's own text holds real Arabic content.

    Backstop for mutation paths that arrive with thin project data: a deck
    carrying Arabic prose keeps Arabic chrome even if detection on the
    accompanying data is inconclusive.
    """
    budget = [limit]
    arabic = 0
    strip_tags = re.compile(r'<[^>]*>')
    for slide in slides if isinstance(slides, list) else []:
        if budget[0] <= 0 or arabic >= 40:
            break
        item = slide if isinstance(slide, dict) else {}
        for key in ('title', 'html'):
            text = strip_tags.sub(' ', str(item.get(key) or ''))
            chunk = text[:budget[0]]
            budget[0] -= len(chunk)
            arabic += len(_ARABIC_SCRIPT_RE.findall(chunk))
            if arabic >= 40 or budget[0] <= 0:
                break
    return arabic >= 40


def renumber_presentation_slides(slides, branding=None, project_data=None, tenant_id=None,
                                 allow_all_maps=False, creative_images=None, preserve_html=False,
                                 offer_lang=None):
    """Renumber a deck; designer/structural edits retain HTML across later saves.

    ``preserve_html`` marks every source slide, not just the edited selection.
    Generation's legacy migrations remain the default for unmarked slides.
    Divider titles already canonical in either deck language are preserved;
    only missing or non-canonical ones are reset in the resolved language.
    """
    source = slides if isinstance(slides, list) else []
    total = len(source)
    if not total:
        return []
    lang = resolve_offer_lang(project_data, offer_lang)
    if lang == OFFER_LANG_ENGLISH and _slides_carry_arabic(source):
        lang = OFFER_LANG_ARABIC
    branding = dict(branding or (db.get_branding(tenant_id) if tenant_id else {}) or {})
    project_data = dict(project_data or {})
    if not isinstance(creative_images, dict):
        creative_images = project_data.get('tenantCreativeImages')
        if isinstance(creative_images, str):
            creative_images = _decode_json_fact(creative_images)
    creative_images = dict(creative_images) if isinstance(creative_images, dict) else {}
    if not creative_images.get('cover'):
        discovered_cover = _extract_cover_image_url(project_data, creative_images)
        if not discovered_cover:
            for s in source:
                s_dict = s if isinstance(s, dict) else {}
                s_type = str(s_dict.get('type') or '').lower()
                s_html = str(s_dict.get('html') or '')
                if s_type == 'cover' or 'cover' in s_html:
                    discovered_cover = _cover_image_url_from_html(s_html)
                    if discovered_cover:
                        break
        if discovered_cover:
            creative_images['cover'] = discovered_cover
    normalized = []
    current_section = ''
    for index, raw in enumerate(source):
        item = dict(raw) if isinstance(raw, dict) else {'html': str(raw or '')}
        slide_type = str(item.get('type') or '').strip().lower()
        title = str(item.get('title') or '').strip()
        html = str(item.get('html') or '')
        if not slide_type:
            if index == 0:
                slide_type = 'cover'
            elif re.search(r'محتويات\s+العرض|فهرس|index', title + ' ' + html, flags=re.IGNORECASE):
                slide_type = 'index'
            elif index == total - 1:
                slide_type = 'closing'
            else:
                slide_type = 'content'
            item['type'] = slide_type
        if slide_type == 'cover':
            item['section_key'] = 'cover'
        elif slide_type == 'index':
            item['section_key'] = 'index'
        else:
            section_key = _slide_section_key(item, current_section)
            if _is_fixed_section_divider(item, section_key):
                slide_type = 'section_divider'
                current_title = str(item.get('title') or '').strip()
                keep_title = (lang == OFFER_LANG_ENGLISH
                              and current_title == PRESENTATION_SECTION_TITLES_EN.get(section_key, ''))
                item.update({
                    'type': slide_type,
                    'title': (current_title if keep_title
                              else section_title(section_key, lang)),
                    'design_style': 'divider',
                    'section_key': section_key,
                    'bullets': [],
                })
            item['section_key'] = section_key
            if slide_type == 'section_divider' and section_key in PRESENTATION_SECTION_ORDER:
                current_section = section_key
        if preserve_html or _designer_preserves_html(item):
            item['_designer_keep_html'] = True
            item['is_custom'] = True
            item['html'] = _normalize_watermark_ink(str(item.get('html') or ''))
            normalized.append(item)
            continue
        if item.get('html'):
            item['html'] = _normalize_watermark_ink(item['html'])
        normalized.append(item)

    refresh_index_entries({'slides': normalized}, offer_lang=lang)
    for index, item in enumerate(normalized, 1):
        slide_type = str(item.get('type') or 'content')
        if _designer_preserves_html(item):
            html = _rewrite_preserved_counter(item.get('html') or '', slide_type, index, total)
            if slide_type == 'index':
                if not re.search(r'data-index-(?:section|page)', html, re.IGNORECASE):
                    html = build_index_slide(item, index, total, branding, project_data, offer_lang=lang)
                else:
                    html = _refresh_preserved_index(html, item.get('index_entries'), branding, project_data)
            item['html'] = _strip_presentation_icons(html)
            continue
        # A designer-chat edit, user edit, or custom slide produced this HTML
        # (for example description bars added to visual slides, custom cards, or layouts).
        # Rebuilding from the canonical template would discard those edits.
        # Keep the edited HTML and only refresh chrome and counters.
        # This flag persists across presentation saves, draft reloads, and exports.
        has_caption_in_html = bool(
            'data-visual-media-caption="1"' in str(item.get('html') or '')
        )
        keep_edited_html = bool(
            item.get('_designer_keep_html') or
            item.get('is_custom') or
            item.get('keep_html') or
            item.get('custom_html') or
            has_caption_in_html or
            re.search(r'\bdata-slide-watermark\s*=\s*["\']true["\']', str(item.get('html') or ''), re.IGNORECASE)
        )
        if keep_edited_html:
            item['_designer_keep_html'] = True
            item['is_custom'] = True
        if slide_type == 'index':
            existing_html = item.get('html') or ''
            if existing_html and re.search(r'data-index-(?:section|page)', existing_html, re.IGNORECASE):
                index_html = _refresh_preserved_index(existing_html, item.get('index_entries'), branding, project_data)
            else:
                index_html = build_index_slide(item, index, total, branding, project_data, offer_lang=lang)
            item['html'] = finalize_slide_html(
                index_html, slide_type, project_data, branding, tenant_id=tenant_id,
                slide_num=index, slide_title=item.get('title') or offer_chrome('index_heading', lang),
                total_slides=total, content_source=item.get('content_source'),
                allow_all_maps=allow_all_maps,
            )
        elif slide_type in ('cover', 'closing', 'moodboard', 'section_divider'):
            if (slide_type == 'section_divider' or _is_fixed_section_divider(item, item.get('section_key'))):
                divider_images = dict(creative_images)
                if not divider_images.get('cover'):
                    fallback_cover = project_data.get('cover') or project_data.get('mainImageData')
                    if fallback_cover:
                        divider_images['cover'] = fallback_cover
                cover_target = _creative_asset_url(divider_images.get('cover'))
                if not keep_edited_html:
                    rebuilt = build_section_divider_slide(
                        item, index, total, branding, project_data
                    )
                    item['html'] = finalize_slide_html(
                        rebuilt, 'section_divider', project_data, branding,
                        creative_images=divider_images, tenant_id=tenant_id,
                        slide_num=index, slide_title=item.get('title'),
                        total_slides=total, content_source=None,
                        allow_all_maps=allow_all_maps,
                    )
                else:
                    curr_html = _rewrite_slide_counter(
                        item.get('html') or '', slide_type, index, total)
                    if cover_target:
                        for cover_pat in [r'#*IMAGE_COVER#*', r'#*COVER_IMAGE#*', r'#*MAIN_IMAGE#*', r'#*PROJECT_IMAGE_COVER#*']:
                            curr_html = re.sub(cover_pat, cover_target, curr_html, flags=re.IGNORECASE)
                    item['html'] = curr_html
                if cover_target:
                    item['html'] = _force_section_divider_background(item.get('html') or '', cover_target)
            else:
                curr_html = _rewrite_slide_counter(
                    item.get('html') or '', slide_type, index, total)
                cover_target = creative_images.get('cover') or project_data.get('cover') or project_data.get('mainImageData') or ''
                if cover_target:
                    for cover_pat in [r'#*IMAGE_COVER#*', r'#*COVER_IMAGE#*', r'#*MAIN_IMAGE#*', r'#*PROJECT_IMAGE_COVER#*']:
                        curr_html = re.sub(cover_pat, cover_target, curr_html, flags=re.IGNORECASE)
                item['html'] = curr_html
            if slide_type != 'section_divider' and (item.get('section_key') == 'market' or _is_market_slide(slide_type, title, item.get('content_source'))):
                item['html'] = _strip_market_slide_media(item['html'])
        else:
            media_sources = []
            canonical_tokens = []
            if _is_visual_concept_media_slide(item):
                media_sources, canonical_tokens = _visual_media_rebuild_sources(item, creative_images)
            if media_sources and not keep_edited_html:
                # Stored presentations can predate both image_tokens and the bounded visual-media
                # template. Prefer current assets inferred from content_source, then recover the
                # resolved media URL already present in the old slide HTML.
                rebuild_item = dict(item)
                rebuild_item['image_tokens'] = media_sources
                if canonical_tokens:
                    item['image_tokens'] = canonical_tokens
                if not rebuild_item.get('captions'):
                    extracted_caps = _extract_visual_concept_captions(item.get('html'))
                    if extracted_caps:
                        rebuild_item['captions'] = extracted_caps
                        item['captions'] = extracted_caps
                rebuilt = _build_visual_concept_media_slide(rebuild_item, branding=branding)
                item['html'] = finalize_slide_html(
                    rebuilt, slide_type, project_data, branding,
                    creative_images=creative_images, tenant_id=tenant_id,
                    slide_num=index, slide_title=item.get('title'), total_slides=total,
                    content_source=_visual_media_content_source(item), allow_all_maps=allow_all_maps,
                )
            else:
                html = item.get('html') or ''
                # Rebuild the managed chrome on every content slide. Older saved slides
                # may already have the previous white header, so checking only for the
                # marker would preserve the color conflict after the new adaptive rule.
                html = _strip_existing_slide_chrome(html)
                html = _normalize_light_content_surface(html, slide_type=slide_type)
                html = _ensure_managed_chrome(
                    html, slide_title=item.get('title'), slide_num=index,
                    total_slides=total, branding=branding,
                    project_data=project_data, tenant_id=tenant_id,
                )
                html = _apply_logo_contrast_styles(html, branding, project_data, slide_type)
                html = _replace_data_placeholders(html, project_data, branding)
                html = resolve_logo_in_html(
                    html, tenant_id, _branding_cache=branding,
                    project_logo=_project_logo_reference(project_data),
                )
                item['html'] = _rewrite_slide_counter(html, slide_type, index, total)
                # Generation already applies the strict media ownership boundary in
                # finalize_slide_html().  Re-numbering is also used when an existing
                # presentation is opened, so it must not delete a map URL that was
                # deliberately saved in a slide (for example after a designer-chat
                # insertion).  Unresolved map tokens are still removed here because
                # they cannot render an image on their own.
                item['html'] = _strip_unplanned_map_media(
                    item['html'], slide_type, content_source=item.get('content_source'),
                    slide_title=title, strip_resolved=False, allow_all_maps=allow_all_maps)
                if item.get('section_key') == 'market' or _is_market_slide(slide_type, title, item.get('content_source')):
                    item['html'] = _strip_market_slide_media(item['html'])
    return normalized


def generate_all_slides(slide_plan, project_data, branding, images_info, call_glm_fn, map_placeholders=None,
                        creative_images=None):
    """
    Generate all slides in parallel.
    Returns list of HTML strings.
    """
    # Requests can carry a plan saved before the market-section rules existed.
    # Repair that plan at the last boundary before rendering as well, so old
    # clients and the workspace agent receive the same deterministic output.
    slide_plan = normalize_market_section_plan(slide_plan, project_data) or slide_plan
    # This route is still used by workspace/legacy callers that can submit an
    # older plan without passing through the tenant plan endpoint. Apply the
    # same per-slide ownership repair here so those callers cannot reintroduce
    # maps into visual, timeline or financial sections.
    slides = [
        _normalize_legacy_single_slide(dict(slide), project_data)
        for slide in (slide_plan.get('slides', []) if isinstance(slide_plan, dict) else [])
        if isinstance(slide, dict)
    ]
    total = len(slides)

    # Build system prompt with tenant's design rules
    design_rules = build_design_rules(branding)
    project_json = build_project_facts(project_data, branding.get('tenant_id'))

    landmarks_matrix = project_data.get('nearby_landmarks_data') or project_data.get('landmarks_matrix')
    landmarks_note = ''
    if landmarks_matrix:
        landmarks_note = (
            "إرشادات هامة لعرض المعالم:\n"
            "يجب عرض المسافة والوقت معاً لكل معلم بدون استثناء بالصيغة التاعية: (اسم المعلم - المسافة بالكم - الوقت بالدقائق)، مثل: 'ميدان السارية (1.5 كم - 5 دقائق)'.\n"
            "استخدم البيانات الموثقة التالية كما هي وممنوع تعديل الأرقام:\n" +
            json.dumps(landmarks_matrix, ensure_ascii=False, indent=2)
        )
    timeline_note = _timeline_data_note(project_data)
    financial_note = _financial_data_note(project_data)

    system_prompt = f"""{design_rules}

## بيانات المشروع
{project_json}

## الصور المتوفرة
{images_info}

## بيانات المسافات والأوقات (ممنوع تعديل الأرقام)
{landmarks_note}
{timeline_note}
{financial_note}

## قواعد عامة
- كل شريحة 1280x720px (أو حسب نسبة العرض المحددة)
- CSS inline فقط
- ممنوع box-shadow/filter/backdrop-filter
- استخدم ##LOGO## للشعار، ##IMAGE_COVER## لصورة الغلاف، ##MOODBOARD_IMAGE_N## لصور المود بورد
- للخرائط: ##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT## — استخدمها في شرائح تحليل الموقع الجغرافي أو تحليل الأرض عند طلبها صراحة أو ملخص الموقع المحدد صراحة، وممنوع استخدامها في الجدول الزمني أو الدراسة المالية أو المخططات أو التصورات الخارجية أو الداخلية أو أي قسم آخر
- ممنوع base64 أو روابط صور خارجية
- """ + NO_STREET_VIEW_RULE + """
"""

    results = [None] * total

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_idx = {}
        for i, slide in enumerate(slides):
            future = executor.submit(
                generate_single_slide,
                system_prompt, slide, i + 1, total, branding, call_glm_fn,
                project_data=project_data
            )
            future_to_idx[future] = i

        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            slide = slides[idx]
            html = future.result()
            if not html:
                # Fallback HTML so the rest of the pipeline keeps working
                title = slide.get('title', f'شريحة {idx + 1}')
                html = f'<div class="slide" style="width:1280px;height:720px;direction:rtl;font-family:sans-serif;display:flex;align-items:center;justify-content:center;text-align:center;background:#fff;"><h1>{title}</h1></div>'
                print(f"[SLIDE-{idx + 1}] Using fallback HTML")
            html = finalize_slide_html(
                html,
                slide.get('type', 'content'),
                project_data,
                branding,
                creative_images=creative_images,
                map_placeholders=map_placeholders,
                tenant_id=branding.get('tenant_id'),
                slide_num=idx + 1,
                slide_title=slide.get('title', f'شريحة {idx + 1}'),
                total_slides=total,
                content_source=slide.get('content_source'),
            )
            results[idx] = html

    return results
