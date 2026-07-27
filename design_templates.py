"""
Design templates for Multi-Tenant SaaS.
Pre-built design styles that companies can choose from.
"""
import base64
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_FONTS = "'IBM Plex Sans Arabic', Tahoma, Arial, sans-serif"

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
    served_url = None
    if not embed and tenant_id:
        served_url = f"/tenant-assets/{tenant_id}/fonts/{os.path.basename(abs_path)}"
    if served_url:
        src = f"url('{served_url}') format('{fmt}')"
    else:
        with open(abs_path, 'rb') as f:
            src = f"url(data:{mime};base64,{base64.b64encode(f.read()).decode()}) format('{fmt}')"
    css = f"@font-face{{font-family:'{family}';src:{src};font-weight:100 900;font-display:swap;}}\n.slide,.slide *{{font-family:'{family}',{fallback} !important;}}"
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
    css = f"@font-face{{font-family:'{family}';src:{src};font-weight:100 900;font-display:swap;}}\n.slide,.slide *{{font-family:'{family}',{fallback} !important;}}"
    return css, f"'{family}', {fallback}"


def _build_preset_css(source, fallback):
    family = source['family']
    family_list = f"'{family}', {fallback}"
    if source['type'] == 'bundled':
        data, fmt = source['data'], source['format']
        mime = {'truetype':'font/ttf','opentype':'font/otf','woff2':'font/woff2','woff':'font/woff'}.get(fmt,'font/ttf')
        css = (
            f"@font-face{{font-family:'{family}';src:url(data:{mime};base64,{data}) format('{fmt}');font-weight:100 900;font-display:swap;}}\n"
            f".slide,.slide *{{font-family:{family_list} !important;}}"
        )
    elif source['type'] == 'google':
        encoded = source['encoded']
        css = (
            f"@import url('https://fonts.googleapis.com/css2?family={encoded}:wght@400;700&display=swap');\n"
            f".slide,.slide *{{font-family:{family_list} !important;}}"
        )
    else:  # system
        css = f".slide,.slide *{{font-family:{family_list} !important;}}"
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

def build_design_rules(branding):
    """
    Build DESIGN_RULES string dynamically from tenant's branding settings.
    This replaces the hardcoded DESIGN_RULES in app.py.
    """
    template = DESIGN_TEMPLATES.get(branding.get('design_template', 'modern'), DESIGN_TEMPLATES['modern'])
    company_name = branding.get('company_name', '')
    primary = branding.get('primary_color', '#3B6E91')
    secondary = branding.get('secondary_color', '#254B66')
    accent = branding.get('accent_color', '#6DA3C3')
    bg = branding.get('background_color', '#F4F9FC')
    text_color = branding.get('text_color', '#333333')
    # Only the family name is needed here, so never read/base64 the font file
    # on every slide prompt build.
    _font_css, font = build_font_css(branding, branding.get('tenant_id'), family_only=True)
    header_enabled = branding.get('header_enabled', 1)
    footer_enabled = branding.get('footer_enabled', 1)
    header_h = branding.get('header_height', 56)
    footer_h = branding.get('footer_height', 36)
    card_style = branding.get('card_style', template['card_style'])
    logo_path = branding.get('logo_path', '')
    slide_ratio = branding.get('slide_ratio', '16:9')

    # Slide dimensions based on ratio
    if slide_ratio == '4:3':
        slide_w, slide_h = 1280, 960
    else:
        slide_w, slide_h = 1280, 720

    rules = f"""أنت مصمم عروض تقديمية احترافية لشركة "{company_name}". صمم كل شريحة كلوحة فنية احترافية.

## الألوان
- رئيسي: {primary} (العناوين والأزرار)
- ثانوي: {secondary} (التدرجات)
- مميز: {accent} (الزخارف والتفاصيل)
- خلفية: {bg}
- نص: {text_color}
- أبيض: #FFFFFF

## أبعاد الشريحة وقواعد الاحتواء الصارمة (ممنوع التداخل أو التجاوز إطلاقاً)
- الأبعاد الكلية: {slide_w}px عرض × {slide_h}px ارتفاع.
- أقصى ارتفاع للمحتوى داخل الشريحة: {slide_h - header_h - footer_h - 20}px صافي بين الهيدر والفوتر.
- ⚠️ قانون عدم الخروج عن الحدود: يجب أن يتناسب كل محتوى الشريحة تماماً داخل هذا الارتفاع دون أن يقطع أي جزء منه.

## الخطوط والأحجام المحددة للتناسب
font-family: {font}
- العنوان الرئيسي للشريحة: 24px-28px font-weight:700 color:{primary} (أقصى حد 30px)
- عناوين البطاقات والأقسام: 15px-17px font-weight:600 color:{primary}
- النصوص العادية ونصوص البطاقات والجداول: 12px-14px font-weight:400 color:{text_color}
- الأرقام المالية الكبيرة: 24px-30px font-weight:700 color:{primary} (أقصى حد 32px)

## الشريحة الأساسية
<div class="slide" dir="rtl" style="width:{slide_w}px;height:{slide_h}px;position:relative;overflow:hidden;box-sizing:border-box;font-family:{font};">
CSS inline فقط. ممنوع box-shadow/filter/backdrop-filter. استخدم box-sizing:border-box لكل العناصر.
"""

    if header_enabled:
        rules += f"""
## هيدر إلزامي — يجب أن يوجد في كل شريحة محتوى
position:absolute;top:0;right:0;left:0;height:{header_h}px;background:#fff;border-bottom:2px solid {primary};
المحتوى: شعار ##LOGO## height:40px يساراً + خط رأسي {accent} 4px + اسم الشريحة 16px font-weight:600 color:{primary}
"""

    if footer_enabled:
        rules += f"""
## فوتر إلزامي — يجب أن يوجد في كل شريحة محتوى
position:absolute;bottom:0;right:0;left:0;height:{footer_h}px;background:{primary};display:flex;align-items:center;padding:0 16px;
المحتوى: اسم المشروع 13px أبيض + '{company_name}' opacity:0.7 + رقم الشريحة في دائرة {accent} 24px
"""

    content_top = header_h if header_enabled else 0
    content_bottom = footer_h if footer_enabled else 0
    rules += f"""
## منطقة المحتوى والتخطيط
top:{content_top}px → bottom:{content_bottom}px. padding: 16px 36px.
- إذا زاد عدد البطاقات أو العناصر عن 4، استخدم شبكة متعددة الأعمدة (grid 2x2 أو 3x2 مع gap:10px) أو توزيع أفقياً لضمان ملاءمة المحتوى كاملاً داخل الارتفاع المتاح.

## البطاقات (Cards) — نمط {card_style}
"""
    if card_style == 'bordered':
        accent_rgb = _hex_to_rgb(accent)
        rules += f"كل بطاقة: background:#fff border:1px solid rgba({accent_rgb},0.2) border-radius:8px padding:10px 14px; box-sizing:border-box.\n"
    elif card_style == 'shadow':
        rules += f"كل بطاقة: background:#fff border-radius:10px padding:10px 14px; box-sizing:border-box. ظل خفيف: box-shadow:0 2px 6px rgba(0,0,0,0.06).\n"
    elif card_style == 'flat':
        rules += f"كل بطاقة: background:{bg} border-radius:8px padding:10px 14px; box-sizing:border-box. بدون حدود أو ظلال.\n"
    elif card_style == 'gradient':
        rules += f"كل بطاقة: background:linear-gradient(135deg,{primary},{secondary}) border-radius:10px padding:10px 14px color:#fff; box-sizing:border-box.\n"

    rules += "بدون أيقونات. اعتمد على التخطيط والمساحات.\n"

    if template['use_gradients']:
        rules += f"تدرجات: استخدم linear-gradient(135deg,{primary},{secondary}) في الخلفيات والبطاقات المميزة.\n"

    rules += f"""
## الصور Placeholder
- صورة الغلاف: ##IMAGE_COVER## (background-image فقط)
- صور المود بورد: ##MOODBOARD_IMAGE_1## إلى ##MOODBOARD_IMAGE_4##
- خريطة الموقع العام: ##MAP_OVERVIEW## (background-image)
- خريطة المعالم: ##MAP_LANDMARKS## (background-image)
- خريطة الوصول: ##MAP_ACCESS## (background-image)
- خريطة نطاق التأثير: ##MAP_CATCHMENT## (background-image)
- صور Street View: ##STREET_VIEW_1## إلى ##STREET_VIEW_4##
- شعار الشركة: ##LOGO## (height:40px في الهيدر، height:80px في الغلاف والختام)
- ⛔ ممنوع رسم أي دوائر أو دبابيس أو مؤشرات موقع HTML فوق الخرائط (##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##) لأن هذه الصور تحتوي بالفعل على علامات موقع احترافية ومضلعات تحديد وبوصلة وخرائط مصغرة مرسومة مباشرة بدقة عالية.
- ⛔ ممنوع base64 أو روابط صور خارجية — استخدم الـ placeholders فقط

## اسم الشركة في الفوتر
{company_name}
"""

    return rules


def resolve_font_path(path):
    """Resolve a stored font path to an absolute path.

    font_file_path is stored relative to the project root, so relying on the
    process CWD (which differs under gunicorn) would silently fail.
    """
    if not path:
        return None
    if os.path.isabs(path):
        return path if os.path.exists(path) else None
    candidate = os.path.join(BASE_DIR, path.lstrip('/\\'))
    return candidate if os.path.exists(candidate) else None


def build_font_css(branding, tenant_id=None, embed=True, family_only=False):
    """@font-face isolated inside .slide only — does not affect site UI.

    family_only=True skips all disk I/O and returns just the font-family value,
    for callers that only need the name (e.g. prompt building).
    """
    branding = branding or {}
    chosen = branding.get('font_family') or 'IBM Plex Sans Arabic'
    fallback = FALLBACK_FONTS

    if family_only:
        family_list = _font_family_list(chosen)
        return f".slide,.slide *{{font-family:{family_list} !important;}}", family_list

    # 1) Custom font file on disk (uploaded by tenant)
    path = branding.get('font_file_path')
    abs_path = resolve_font_path(path)
    if abs_path and not _is_lfs_pointer(abs_path):
        family = f"tenant-font-{tenant_id or branding.get('tenant_id', 'x')}"
        return _build_font_face_from_file(abs_path, family, fallback, embed, tenant_id)
    if path:
        print(f"[FONT] ERROR: uploaded font file missing or LFS pointer: {path}")

    # 2) Persisted base64 font data in DB (fallback when uploads/ is ephemeral)
    font_file_data = branding.get('font_file_data')
    if font_file_data:
        try:
            family = f"tenant-font-{tenant_id or branding.get('tenant_id', 'x')}"
            return _build_font_face_from_data(font_file_data, family, fallback)
        except Exception as e:
            print(f"[FONT] ERROR: failed to use font_file_data: {e}")

    # 3) Built-in presets: bundled faces or Google Fonts
    source = _resolve_preset_font_source(chosen)
    if source:
        css, family_list = _build_preset_css(source, fallback)
        print(f"[FONT DEBUG] preset source for '{chosen}': {source['type']}, family={source['family']}")
        return css, family_list

    # 4) No source available: keep the name and warn loudly
    print(f"[FONT] ERROR: no bundled or Google font source for '{chosen}'; PDF may fall back to system fonts")
    family_list = _font_family_list(chosen)
    return f".slide,.slide *{{font-family:{family_list} !important;}}", family_list


def _hex_to_rgb(hex_color):
    """Convert hex color to 'r,g,b' string for rgba()."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"{r},{g},{b}"
    except Exception:
        return "196,163,90"
