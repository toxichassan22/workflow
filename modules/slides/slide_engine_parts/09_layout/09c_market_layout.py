# Market layout frame and spacing normalizers.

def _inline_top_px(style, name):
    match = re.search(rf'\b{name}\s*:\s*(-?\d+(?:\.\d+)?)px', style or '', flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _strip_reserved_header_spacing(tag):
    """Drop the top margin/padding a stripped model header left behind."""
    style_match = re.search(r'\bstyle\s*=\s*(["\'])(.*?)\1', tag, flags=re.IGNORECASE)
    style = style_match.group(2) if style_match else ''
    margin_top = _inline_top_px(style, 'margin-top')
    if margin_top is None:
        margin_top = _inline_top_px(style, 'margin')
    padding_top = _inline_top_px(style, 'padding-top')
    if padding_top is None:
        padding_top = _inline_top_px(style, 'padding')
    if margin_top is not None and margin_top >= 24:
        tag = _set_tag_style(tag, ('margin-top',), 'margin-top:0!important;')
    if padding_top is not None and padding_top >= 48:
        tag = _set_tag_style(tag, ('padding-top',), 'padding-top:0!important;')
    return tag


def _align_market_auto_fit_frame(html):
    """Top-align an already-normalized market frame (old decks stored `safe center`)."""
    if not html or 'data-market-auto-fit-content' not in html:
        return html

    def align(match):
        tag = match.group(0)
        return re.sub(r'justify-content\s*:\s*safe\s+center', 'justify-content:flex-start',
                      tag, flags=re.IGNORECASE)

    frame_re = re.compile(
        r'<(?P<tag>div)\b[^>]*\bdata-market-auto-fit-content\s*=\s*["\']1["\'][^>]*>',
        re.IGNORECASE,
    )
    html = frame_re.sub(align, html, count=1)
    frame = frame_re.search(html)
    if not frame:
        return html
    frame_end = _slide_element_end(html, frame)
    inner = html[frame.end():frame_end]
    first_tag = re.search(r'<(?!/|!|\?)[a-z][^>]*>', inner, flags=re.IGNORECASE)
    if first_tag:
        cleaned = _strip_reserved_header_spacing(first_tag.group(0))
        inner = inner[:first_tag.start()] + cleaned + inner[first_tag.end():]
    return html[:frame.end()] + inner + html[frame_end:]


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
    ):
        return html
    if 'data-market-auto-fit="1"' in html:
        # Slides stored before the frame was top-aligned still say `safe center`,
        # which opened a gap taller than the header on every short page.
        return _align_market_auto_fit_frame(html)

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

    # A stripped model header leaves its reserved margin behind. The frame
    # already owns the 64px header lane, so a `margin-top:56px` on the first
    # block pushed the content another full header-height down the page.
    body[0] = re.sub(
        r'<(?!/|!|\?)[a-z][^>]*>', lambda match: _strip_reserved_header_spacing(match.group(0)),
        body[0], count=1, flags=re.IGNORECASE,
    )

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
        'display:flex;flex-direction:column;justify-content:flex-start;overflow:visible;">'
        + body_html + '</div>'
    )
    replacement = root_open + ''.join(preserved) + repair_css + frame + html[root_close_start:root_end]
    return html[:root_match.start()] + replacement + html[root_end:]


_FORCED_SECTION_BACKGROUND_RE = re.compile(
    r"background-image\s*:\s*url\([^)]*\)\s*!important\s*;\s*"
    r"background-size\s*:\s*cover\s*!important\s*;\s*"
    r"background-position\s*:\s*center\s+center\s*!important\s*;\s*"
    r"background-repeat\s*:\s*no-repeat\s*!important\s*;?",
    re.IGNORECASE,
)


def _strip_forced_section_background(html):
    """Remove the cover photo a misclassified divider forced onto a content page."""
    return _FORCED_SECTION_BACKGROUND_RE.sub('', str(html or ''))


def _restore_misclassified_section_divider(item, section_key):
    """A market/swot content page retyped as a divider because of its title."""
    if str(item.get('type') or '').strip().lower() != 'section_divider':
        return False
    if section_key not in _FIXED_DIVIDER_SECTION_KEYS:
        return False
    return _slide_visible_word_count(item.get('html')) > _SECTION_DIVIDER_MAX_WORDS


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


