

def extract_slide_elements(html):
    """Return every root .slide element, repairing one whose own tags do not balance.

    This walked the whole document looking for a balanced `</div>` per slide and **`break`ed** when
    it could not find one, so a single model-generated slide with a missing closing tag silently
    dropped every slide after it: 21 slides in, 10 out, and the exported PDF simply stopped in the
    middle of the deck with no error anywhere. Each slide is now bounded by the next slide's
    opening tag, so a broken slide can only damage itself.
    """
    if not html:
        return []
    div_token = re.compile(r'<div\b[^>]*>|</div\s*>', re.I)
    starts = [match.start() for match in _SLIDE_OPEN_RE.finditer(html)
              if 'slide' in (match.group(1) or match.group(2) or '').split()]
    slides = []
    for position, start in enumerate(starts):
        boundary = starts[position + 1] if position + 1 < len(starts) else len(html)
        fragment = html[start:boundary]
        depth = 0
        cut = None
        for token in div_token.finditer(fragment):
            if token.group(0).lower().startswith('</div'):
                depth -= 1
                if depth <= 0:
                    cut = token.end()
                    break
            else:
                depth += 1
        if cut is not None:
            slides.append(fragment[:cut].strip())
            continue
        # The slide never closes itself: keep it up to the next slide and close what it left open.
        depth = sum(-1 if token.group(0).lower().startswith('</div') else 1
                    for token in div_token.finditer(fragment))
        slides.append(fragment.strip() + ('</div>' * depth if depth > 0 else ''))
    return slides

# ─────────────────────────────────────────────────────────────────────────────
# Font source helpers for export (bundled / Google Fonts / uploaded / persisted)
# ─────────────────────────────────────────────────────────────────────────────

_BUNDLED_FONTS_CACHE = None


def _load_bundled_fonts():
    """Load base64 font data from fonts_bundle.json (guaranteed, not Git LFS)."""
    global _BUNDLED_FONTS_CACHE
    if _BUNDLED_FONTS_CACHE is not None:
        return _BUNDLED_FONTS_CACHE
    result = {}
    json_path = os.path.join(BASE_DIR, 'fonts_bundle.json')
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                bundle = json.load(f)
            for family, item in bundle.items():
                data = item.get('data')
                fmt = item.get('format', 'truetype')
                if data:
                    result[family] = (data, fmt)
        except Exception as e:
            print(f"[FONT] Failed to load fonts_bundle.json: {e}")
    _BUNDLED_FONTS_CACHE = result
    return result


def _is_lfs_pointer(path):
    """Detect Git LFS pointer stubs that should not be treated as real font files."""
    try:
        if os.path.getsize(path) < 500:
            return True
        with open(path, 'rb') as f:
            head = f.read(100)
            if b'version https://git-lfs' in head:
                return True
    except Exception:
        pass
    return False


def _font_family_list(chosen):
    if not chosen:
        chosen = 'IBM Plex Sans Arabic'
    if not (chosen.startswith("'") or chosen.startswith('"')):
        chosen = f"'{chosen}'"
    return f"{chosen}, {FALLBACK_FONTS}"


def _css_static_weight(value):
    weight = int(value or 400)
    if weight <= 300:
        return 300
    if weight <= 450:
        return 400
    if weight <= 550:
        return 500
    if weight <= 750:
        return 700
    return 900


def _resolved_static_weight(value, fallback):
    actual = _css_static_weight(value)
    requested = _css_static_weight(fallback)
    if requested >= 700 and actual < requested:
        return requested
    if requested <= 300 and actual > requested:
        return requested
    return actual


def _font_weight_descriptor(raw, fallback=400):
    try:
        table_count = int.from_bytes(raw[4:6], 'big')
        tables = {}
        for index in range(table_count):
            record = 12 + index * 16
            tag = raw[record:record + 4].decode('latin-1')
            tables[tag] = int.from_bytes(raw[record + 8:record + 12], 'big')
        if 'fvar' in tables:
            return '100 900'
        offset = tables.get('OS/2')
        if offset is not None and offset + 6 <= len(raw):
            weight = int.from_bytes(raw[offset + 4:offset + 6], 'big')
            return str(_resolved_static_weight(weight, fallback))
    except Exception:
        pass
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(io.BytesIO(raw), lazy=True)
        try:
            if 'fvar' in font:
                return '100 900'
            weight = int(font['OS/2'].usWeightClass) if 'OS/2' in font else int(fallback)
        finally:
            font.close()
        return str(_resolved_static_weight(weight, fallback))
    except Exception:
        return str(fallback)


def _resolve_preset_font_source(name):
    """Map a chosen font-family name to a real bundled or Google Fonts source."""
    if not name:
        return None
    norm = re.sub(r'[\s-]', '', name.lower())
    bundled = _load_bundled_fonts()

    # Bundled faces use the user-facing display name as the CSS family name.
    bundled_map = {
        'thesansarabic': ('The Sans Arabic', 'TheSansArabic-Light'),
        'thesansarabiclight': ('The Sans Arabic', 'TheSansArabic-Light'),
        'thesansarabicbold': ('The Sans Arabic', 'TheSansArabic-Bold'),
        'bahijthesansarabic': ('Bahij TheSansArabic', 'TheSansArabic-Bold'),
        'bahijthesansarabicbold': ('Bahij TheSansArabic', 'TheSansArabic-Bold'),
    }
    if norm in bundled_map:
        display, file_family = bundled_map[norm]
        data = bundled.get(file_family)
        if data:
            return {'type': 'bundled', 'family': display, 'data': data[0], 'format': data[1]}
        return None

    google_map = {
        'ibmplexsansarabic': 'IBM+Plex+Sans+Arabic',
        'cairo': 'Cairo',
        'notosansarabic': 'Noto+Sans+Arabic',
        'tajawal': 'Tajawal',
        'almarai': 'Almarai',
        'arefruqaa': 'Aref+Ruqaa',
        'readexpro': 'Readex+Pro',
    }
    if norm in google_map:
        encoded = google_map[norm]
        display = encoded.replace('+', ' ')
        return {'type': 'google', 'family': display, 'encoded': encoded}

    # Known system fonts that do not need a web font file
    system_map = {
        'arial': 'Arial',
        'tahoma': 'Tahoma',
    }
    if norm in system_map:
        return {'type': 'system', 'family': system_map[norm]}

    return None


def _build_font_face_from_file(abs_path, family, fallback, embed=True, tenant_id=None):
    ext = os.path.splitext(abs_path)[1].lower()
    fmt = {'.ttf': 'truetype', '.otf': 'opentype', '.woff2': 'woff2', '.woff': 'woff'}.get(ext, 'truetype')
    mime_map = {'truetype': 'font/ttf', 'opentype': 'font/otf', 'woff2': 'font/woff2', 'woff': 'font/woff'}
    mime = mime_map.get(fmt, 'font/ttf')
    with open(abs_path, 'rb') as font_file:
        raw = font_file.read()
    weight = _font_weight_descriptor(raw)
    served_url = None
    if not embed and tenant_id:
        served_url = f"/tenant-assets/{tenant_id}/fonts/{os.path.basename(abs_path)}"
    if served_url:
        src = f"url('{served_url}') format('{fmt}')"
    else:
        src = f"url(data:{mime};base64,{base64.b64encode(raw).decode()}) format('{fmt}')"
    css = f"@font-face{{font-family:'{family}';src:{src};font-weight:{weight};font-display:swap;}}\n.slide,.slide *{{font-family:'{family}',{fallback} !important;font-synthesis:weight;}}"
    return css, f"'{family}', {fallback}"


def _build_font_face_from_data(font_file_data, family, fallback):
    if isinstance(font_file_data, str) and font_file_data.strip().startswith('{'):
        parsed = json.loads(font_file_data)
        data = parsed['data']
        fmt = parsed.get('format', 'truetype')
    else:
        data = font_file_data
        fmt = 'truetype'
    mime_map = {'truetype': 'font/ttf', 'opentype': 'font/otf', 'woff2': 'font/woff2', 'woff': 'font/woff'}
    mime = mime_map.get(fmt, 'font/ttf')
    src = f"url(data:{mime};base64,{data}) format('{fmt}')"
    weight = _font_weight_descriptor(base64.b64decode(data))
    css = f"@font-face{{font-family:'{family}';src:{src};font-weight:{weight};font-display:swap;}}\n.slide,.slide *{{font-family:'{family}',{fallback} !important;font-synthesis:weight;}}"
    return css, f"'{family}', {fallback}"


def _build_preset_css(source, fallback):
    family = source['family']
    family_list = f"'{family}', {fallback}"
    if source['type'] == 'bundled':
        data, fmt = source['data'], source['format']
        mime = {'truetype':'font/ttf','opentype':'font/otf','woff2':'font/woff2','woff':'font/woff'}.get(fmt,'font/ttf')
        weight = _font_weight_descriptor(base64.b64decode(data))
        css = (
            f"@font-face{{font-family:'{family}';src:url(data:{mime};base64,{data}) format('{fmt}');font-weight:{weight};font-display:swap;}}\n"
            f".slide,.slide *{{font-family:{family_list} !important;font-synthesis:weight;}}"
        )
    elif source['type'] == 'google':
        encoded = source['encoded']
        import_line = (
            "@import url('https://fonts.googleapis.com/css2?family="
            + encoded
            + ":wght@400;700&display=swap');\n"
        )
        css = import_line + f".slide,.slide *{{font-family:{family_list} !important;font-synthesis:weight;}}"
    else:  # system
        css = f".slide,.slide *{{font-family:{family_list} !important;font-synthesis:weight;}}"
    return css, family_list


def sanitize_slide_html_for_export(html):
    """Remove any previously-injected font-family declarations before re-applying the tenant font."""
    def _clean_style_attr(m):
        quote = m.group(1)
        value = m.group(2)
        cleaned = re.sub(r'\s*font-family\s*:\s*[^;]+;?\s*', '', value, flags=re.I)
        cleaned = re.sub(r';\s*;', ';', cleaned)
        cleaned = cleaned.strip().strip(';')
        if cleaned:
            return f' style={quote}{cleaned}{quote}'
        return ''

    html = re.sub(r'\sstyle\s*=\s*(["\'])(.*?)\1', _clean_style_attr, html, flags=re.I | re.S)

    def _clean_style_block(m):
        block = m.group(1)
        if '@font-face' in block:
            return m.group(0)
        cleaned = re.sub(r'\s*font-family\s*:\s*[^;]+;?\s*', '', block, flags=re.I)
        cleaned = re.sub(r';\s*;', ';', cleaned)
        return f'<style>{cleaned}</style>'

    html = re.sub(r'<style[^>]*>(.*?)</style>', _clean_style_block, html, flags=re.I | re.S)
    return html


DESIGN_TEMPLATES = {
    'modern': {
        'name': 'مودرن',
        'name_en': 'modern',
        'description': 'تصميم عصري نظيف بحدود رفيعة ومساحات بيضاء',
        'card_style': 'bordered',
        'header_style': 'minimal',
        'use_gradients': False,
        'icon_style': 'none',
        'default_colors': {
            'primary': '#3B6E91',
            'secondary': '#254B66',
            'accent': '#6DA3C3',
            'background': '#F4F9FC',
            'text': '#333333',
        },
    },
    'classic': {
        'name': 'كلاسيك',
        'name_en': 'classic',
        'description': 'تصميم كلاسيكي أنيق بظلال وتدرجات',
        'card_style': 'shadow',
        'header_style': 'ornate',
        'use_gradients': True,
        'icon_style': 'none',
        'default_colors': {
            'primary': '#3B6E91',
            'secondary': '#254B66',
            'accent': '#6DA3C3',
            'background': '#F4F9FC',
            'text': '#333333',
        },
    },
    'minimal': {
        'name': 'مينيمال',
        'name_en': 'minimal',
        'description': 'تصميم بسيط بمساحات بيضاء كبيرة وبدون زخارف',
        'card_style': 'flat',
        'header_style': 'none',
        'use_gradients': False,
        'icon_style': 'none',
        'default_colors': {
            'primary': '#1A1A1A',
            'secondary': '#333333',
            'accent': '#666666',
            'background': '#FAFAFA',
            'text': '#1A1A1A',
        },
    },
    'luxury': {
        'name': 'فاخر',
        'name_en': 'luxury',
        'description': 'تصميم فاخر بتدرجات ذهبية وزخارف',
        'card_style': 'gradient',
        'header_style': 'ornate',
        'use_gradients': True,
        'icon_style': 'none',
        'default_colors': {
            'primary': '#1B1B1B',
            'secondary': '#0D0D0D',
            'accent': '#D4AF37',
            'background': '#F5F5F5',
            'text': '#1B1B1B',
        },
    },
    'corporate': {
        'name': 'كوربوريت',
        'name_en': 'corporate',
        'description': 'تصميم مؤسسي احترافي بألوان هادئة',
        'card_style': 'bordered',
        'header_style': 'minimal',
        'use_gradients': False,
        'icon_style': 'none',
        'default_colors': {
            'primary': '#003366',
            'secondary': '#002244',
            'accent': '#0066CC',
            'background': '#F0F4F8',
            'text': '#1A2B3C',
        },
    },
    'nature': {
        'name': 'طبيعي',
        'name_en': 'nature',
        'description': 'تصميم بألوان طبيعية خضراء وترابية',
        'card_style': 'flat',
        'header_style': 'minimal',
        'use_gradients': False,
        'icon_style': 'none',
        'default_colors': {
            'primary': '#2D5016',
            'secondary': '#1A3009',
            'accent': '#8B7355',
            'background': '#F5F2E9',
            'text': '#2D5016',
        },
    },
}


def get_template(template_key):
    """Get a template by key, returns None if not found."""
    return DESIGN_TEMPLATES.get(template_key)


def get_all_templates():
    """Get all available templates (for frontend selection)."""
    result = []
    for key, t in DESIGN_TEMPLATES.items():
        result.append({
            'key': key,
            'name': t['name'],
            'name_en': t['name_en'],
            'description': t['description'],
            'card_style': t['card_style'],
            'header_style': t['header_style'],
            'default_colors': t['default_colors'],
        })
    return result


def apply_template_colors(template_key):
    """
    Get the default color palette for a template, mapped to DB column names.
    Used when a company selects a template to auto-fill colors.
    """
    template = DESIGN_TEMPLATES.get(template_key)
    if not template:
        return None
    dc = template['default_colors']
    return {
        'primary_color': dc['primary'],
        'secondary_color': dc['secondary'],
        'accent_color': dc['accent'],
        'background_color': dc['background'],
        'text_color': dc['text'],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Design Rules Builder
# ─────────────────────────────────────────────────────────────────────────────

def normalize_hex_color(value, fallback='#000000'):
    text = str(value or '').strip().lower()
    if re.fullmatch(r'#[0-9a-f]{3}', text):
        text = '#' + ''.join(character * 2 for character in text[1:])
    if re.fullmatch(r'#[0-9a-f]{6}', text):
        return text
    return fallback
