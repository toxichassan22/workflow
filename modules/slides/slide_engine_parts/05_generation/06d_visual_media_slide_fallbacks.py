# Visual media slide fallbacks.

def _visual_media_content_source(slide):
    item = slide if isinstance(slide, dict) else {}
    return str(item.get('content_source') or item.get('contentSource') or '').strip().lower()


def _visual_media_image_tokens(slide):
    item = slide if isinstance(slide, dict) else {}
    values = item.get('image_tokens')
    if not isinstance(values, list):
        values = item.get('imageTokens')
    return [str(token or '').strip() for token in (values or []) if str(token or '').strip()]


def _visual_media_tokens_from_source(slide):
    source = _visual_media_content_source(slide)
    match = re.fullmatch(r'plan_image:(\d+)', source)
    if match and int(match.group(1)) > 0:
        return [f'##PLAN_IMAGE_{int(match.group(1))}##']
    match = re.fullmatch(r'exterior_image:(\d+)', source)
    if match and int(match.group(1)) > 0:
        return [f'##MOODBOARD_IMAGE_{int(match.group(1))}##']
    match = re.fullmatch(r'exterior_images_group:(\d+):(\d+)', source)
    if match:
        start, end = sorted((int(match.group(1)), int(match.group(2))))
        if start > 0:
            return [f'##MOODBOARD_IMAGE_{index}##' for index in range(start, min(end, start + 29) + 1)]
    match = re.fullmatch(r'interior_image:(\d+):(\d+)', source)
    if match and int(match.group(1)) > 0 and int(match.group(2)) > 0:
        return [f'##INTERIOR_COMP_{int(match.group(1))}_IMG_{int(match.group(2))}##']
    match = re.fullmatch(r'interior_images_group:(\d+):(\d+):(\d+)', source)
    if match:
        component = int(match.group(1))
        start, end = sorted((int(match.group(2)), int(match.group(3))))
        if component > 0 and start > 0:
            return [
                f'##INTERIOR_COMP_{component}_IMG_{index}##'
                for index in range(start, min(end, start + 29) + 1)
            ]
    return []


def _usable_legacy_visual_media_url(value, attrs_text=''):
    url = html_lib.unescape(str(value or '').strip()).strip('"\' ')
    if not url or '##' in url or url.lower().startswith(('blob:', 'javascript:', 'about:')):
        return ''
    if re.search(r'(?:logo|شعار|data-cover|cover-overlay)', attrs_text, flags=re.IGNORECASE):
        return ''
    if re.search(
        r'(?:tenant-assets|/api/branding/|(?:^|[/_.-])(?:project[-_])?logo(?:[/_.?&-]|$))',
        url, flags=re.IGNORECASE,
    ):
        return ''
    if re.search(
        r'(?:^|/)uploads/maps(?:/|$)|(?:^|/)api/map-images(?:/|$)|(?:^|/)map_[^/]*(?:\?|$)',
        url, flags=re.IGNORECASE,
    ):
        return ''
    if not (
        url.startswith(('/', 'http://', 'https://', 'data:image/'))
        or re.search(r'\.(?:avif|bmp|gif|jpe?g|png|webp)(?:\?.*)?$', url, flags=re.IGNORECASE)
    ):
        return ''
    return url


class _LegacyVisualMediaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def _append(self, value, attrs_text):
        url = _usable_legacy_visual_media_url(value, attrs_text)
        if url and url not in self.urls:
            self.urls.append(url)

    def handle_starttag(self, tag, attrs):
        values = {str(key or '').lower(): str(value or '') for key, value in attrs}
        attrs_text = ' '.join(
            f'{key}={value}' for key, value in values.items() if key not in {'src', 'style'}
        )
        if str(tag or '').lower() == 'img':
            self._append(values.get('src'), attrs_text)
        style = values.get('style') or ''
        for match in re.finditer(r'url\(\s*(["\']?)(.*?)\1\s*\)', style, flags=re.IGNORECASE):
            self._append(match.group(2), attrs_text)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def _legacy_visual_media_urls(slide):
    html = _strip_existing_slide_chrome(str((slide or {}).get('html') or ''))
    if not html:
        return []
    parser = _LegacyVisualMediaParser()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return []
    return parser.urls[:30]


def _legacy_visual_media_layout_marked(slide):
    item = slide if isinstance(slide, dict) else {}
    html = str(item.get('html') or '')
    if not _legacy_visual_media_urls(item):
        return False
    if item.get('media_only') or str(item.get('design_style') or item.get('designStyle') or '').strip().lower() == 'image':
        return True
    return bool(re.search(
        r'data-(?:visual-media-only|visual-media-grid|legacy-media-frame)',
        html, flags=re.IGNORECASE,
    ))


def _is_visual_concept_media_slide(slide):
    source = _visual_media_content_source(slide)
    section = _slide_section_key(slide or {})
    token_names = [token.strip('#').upper() for token in _visual_media_image_tokens(slide)]
    has_visual_token = any(token.startswith((
        'PLAN_IMAGE_', '2D_PLAN_', 'MOODBOARD_IMAGE_', 'PROJECT_IMAGE_',
        'INTERIOR_COMP_', 'INTERIOR_C', 'INTERIOR_IMAGE_', 'INTERIOR_',
    )) for token in token_names)
    has_visual_source = source.startswith((
        'plan_image:', 'exterior_image:', 'exterior_images_group:',
        'interior_image:', 'interior_images_group:',
    ))
    return section in {'plans', 'exterior', 'interior'} and (
        has_visual_token or has_visual_source or _legacy_visual_media_layout_marked(slide)
    )


def _creative_asset_url(value):
    source = value if isinstance(value, dict) else {'url': value}
    url = str(
        source.get('approvedImageUrl') or source.get('approved_image_url')
        or source.get('imageUrl') or source.get('image_url')
        or source.get('url') or source.get('path') or ''
    ).strip()
    if url.lower() in {'', 'available', 'blob:', 'undefined', 'null', 'none'} or url.lower().startswith('blob:'):
        return ''
    return url


def _visual_media_token_url(token, creative_images):
    images = creative_images if isinstance(creative_images, dict) else {}
    name = str(token or '').strip().strip('#').upper()

    match = re.fullmatch(r'(?:MOODBOARD_IMAGE|PROJECT_IMAGE)_(\d+)', name)
    if match:
        values = images.get('moodboard') or images.get('moodboardImages') or []
        index = int(match.group(1)) - 1
        return _creative_asset_url(values[index]) if isinstance(values, list) and 0 <= index < len(values) else ''

    match = re.fullmatch(r'(?:PLAN_IMAGE|2D_PLAN)_(\d+)', name)
    if match:
        values = images.get('plans') or images.get('plans2d') or []
        index = int(match.group(1)) - 1
        return _creative_asset_url(values[index]) if isinstance(values, list) and 0 <= index < len(values) else ''

    match = re.fullmatch(r'INTERIOR_(?:COMP_)?(\d+)_(?:IMG|IMAGE)_(\d+)', name)
    if not match:
        match = re.fullmatch(r'INTERIOR_C(\d+)_(?:IMG|IMAGE)_(\d+)', name)
    if not match:
        match = re.fullmatch(r'INTERIOR_(\d+)_(\d+)', name)
    if match:
        components = images.get('interior_components') or []
        component_index = int(match.group(1)) - 1
        image_index = int(match.group(2)) - 1
        if isinstance(components, list) and 0 <= component_index < len(components):
            component = components[component_index]
            values = component.get('images') if isinstance(component, dict) else []
            if isinstance(values, list) and 0 <= image_index < len(values):
                return _creative_asset_url(values[image_index])
        return ''

    match = re.fullmatch(r'INTERIOR_(?:IMAGE_)?(\d+)', name)
    if match:
        values = images.get('interior') or images.get('interior_images') or []
        index = int(match.group(1)) - 1
        return _creative_asset_url(values[index]) if isinstance(values, list) and 0 <= index < len(values) else ''
    return ''


def _visual_media_rebuild_sources(slide, creative_images):
    inferred_tokens = _visual_media_tokens_from_source(slide)
    if inferred_tokens and all(_visual_media_token_url(token, creative_images) for token in inferred_tokens):
        return inferred_tokens, inferred_tokens

    tokens = _visual_media_image_tokens(slide)
    if tokens and all(_visual_media_token_url(token, creative_images) for token in tokens):
        return tokens, tokens

    direct_sources = [
        _usable_legacy_visual_media_url(token)
        for token in tokens
    ]
    if tokens and all(direct_sources):
        return direct_sources, []

    return _legacy_visual_media_urls(slide), []


def _extract_visual_concept_captions(html):
    """Extract existing captions or description texts from visual slide HTML."""
    if not html or not isinstance(html, str):
        return []
    explicit = re.findall(
        r'<div[^>]*data-visual-media-caption="1"[^>]*>(.*?)</div>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if explicit:
        results = [re.sub(r'<[^>]+>', '', cap).strip() for cap in explicit]
        results = [cap for cap in results if cap]
        if results:
            return results
    generic = re.findall(
        r'<(?:div|p|span)[^>]*(?:class|data-role)=["\'][^"\']*(?:caption|description|desc)[^"\']*["\'][^>]*>(.*?)</(?:div|p|span)>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if generic:
        results = [re.sub(r'<[^>]+>', '', cap).strip() for cap in generic]
        results = [cap for cap in results if cap]
        if results:
            return results
    return []


def _build_visual_concept_media_slide(slide, branding=None):
    """Build a media visual-concept slide with prominent component/title header and captions."""
    tokens = [str(token).strip() for token in ((slide or {}).get('image_tokens') or []) if str(token).strip()]
    if not tokens:
        return None
    primary = normalize_hex_color((branding or {}).get('primary_color'), '#005f78')
    secondary = normalize_hex_color((branding or {}).get('secondary_color'), '#0ea5e9')
    title = html_lib.escape(str((slide or {}).get('title') or '').strip())
    component_name = html_lib.escape(str((slide or {}).get('component_name') or '').strip())

    captions = (slide or {}).get('captions')
    if not isinstance(captions, list) or not any(str(c or '').strip() for c in captions):
        captions = (slide or {}).get('bullets')
    if not isinstance(captions, list) or not any(str(c or '').strip() for c in captions):
        extracted = _extract_visual_concept_captions((slide or {}).get('html'))
        if extracted:
            captions = extracted
            if isinstance(slide, dict):
                slide['captions'] = list(extracted)
    if not isinstance(captions, list):
        captions = []
    description = str((slide or {}).get('description') or '').strip()
    if not description and captions:
        description = str(captions[0] or '').strip()

    columns = 1 if len(tokens) == 1 else 2

    header_html = ''
    if title or component_name:
        badge = f'<span style="font-size:14px;font-weight:700;color:{secondary};background:#f0f9ff;padding:4px 12px;border-radius:6px;border:1px solid #bae6fd;">{component_name}</span>' if (component_name and component_name not in title) else ''
        header_html = (
            f'<div data-visual-media-title="1" style="position:absolute;top:72px;right:34px;left:34px;height:40px;'
            f'display:flex;align-items:center;justify-content:space-between;padding-bottom:10px;'
            f'border-bottom:2px solid #eef2f6;box-sizing:border-box;">'
            f'<div style="font-size:24px;font-weight:800;color:{primary};letter-spacing:-0.3px;">{title}</div>'
            f'{badge}'
            f'</div>'
        )

    cards = []
    for i, token in enumerate(tokens):
        cap = ''
        if i < len(captions) and str(captions[i] or '').strip():
            cap = str(captions[i]).strip()
        elif description:
            cap = description

        cap_html = ''
        if cap:
            escaped_cap = html_lib.escape(cap)
            cap_html = (
                f'<div data-visual-media-caption="1" style="margin-top:10px;padding:10px 14px;background:#f8fafc;'
                f'border:1px solid #e2e8f0;border-radius:8px;font-size:14px;font-weight:600;color:#334155;'
                f'line-height:1.5;text-align:center;box-sizing:border-box;width:100%;">'
                f'{escaped_cap}</div>'
            )

        card = (
            '<div style="min-width:0;min-height:0;display:flex;flex-direction:column;'
            'overflow:hidden;height:100%;box-sizing:border-box;">'
            '<div data-visual-media-frame="1" style="position:relative;flex:1;min-height:0;overflow:hidden;'
            'border:1px solid #d9e1ea;border-radius:12px;background:#fff;box-sizing:border-box;">'
            f'<img data-visual-media-image="1" src="{html_lib.escape(token, quote=True)}" alt="" '
            'style="position:absolute!important;inset:0!important;display:block!important;'
            'width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important;'
            'object-fit:contain!important;object-position:center center!important;">'
            '</div>'
            f'{cap_html}'
            '</div>'
        )
        cards.append(card)

    images_grid = ''.join(cards)
    grid_top = 126 if header_html else 72

    return (
        '<div class="slide" dir="rtl" data-visual-media-only="1" '
        'style="width:1280px;height:720px;position:relative;overflow:hidden;background:#fff;color:#172033;'
        'padding:72px 34px 48px;box-sizing:border-box;">'
        f'{header_html}'
        f'<div data-visual-media-grid="1" style="position:absolute;top:{grid_top}px;right:34px;bottom:48px;left:34px;'
        f'display:grid;grid-template-columns:repeat({columns},minmax(0,1fr));'
        'gap:16px;min-width:0;min-height:0;overflow:hidden;align-items:stretch;">'
        f'{images_grid}</div></div>'
    )
