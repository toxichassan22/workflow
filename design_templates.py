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


def extract_slide_elements(html):
    """Return only balanced root .slide elements, discarding AI chatter around them."""
    if not html:
        return []
    slide_open = re.compile(
        r'<div\b[^>]*\bclass\s*=\s*(["\'])[^"\']*\bslide\b[^"\']*\1[^>]*>',
        re.I,
    )
    div_token = re.compile(r'<div\b[^>]*>|</div\s*>', re.I)
    slides = []
    cursor = 0
    while True:
        match = slide_open.search(html, cursor)
        if not match:
            break
        depth = 1
        end = None
        for token in div_token.finditer(html, match.end()):
            if token.group(0).lower().startswith('</div'):
                depth -= 1
                if depth == 0:
                    end = token.end()
                    break
            else:
                depth += 1
        if end is None:
            break
        slides.append(html[match.start():end].strip())
        cursor = end
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
        import_line = (
            "@import url('https://fonts.googleapis.com/css2?family="
            + encoded
            + ":wght@400;700&display=swap');\n"
        )
        css = import_line + f".slide,.slide *{{font-family:{family_list} !important;}}"
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
    primary = branding.get('primary_color', '#0b1f33')
    secondary = branding.get('secondary_color', '#1e293b')
    accent = branding.get('accent_color', '#0ea5e9')
    bg = branding.get('background_color', '#f8fafc')
    text_color = branding.get('text_color', '#1e293b')
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

    rules = f"""أنت مصمم عروض تقديمية استثمارية فاخرة ورفيعة المستوى لشركة "{company_name}".
صمم كل شريحة كتحفة تصميمية تنفيذية راقية بأسلوب مسطح أنيق (Flat Crisp Luxury).

## أبعاد الشريحة وقواعد الاحتواء الصارمة (ممنوع التداخل أو التجاوز إطلاقاً)
- الأبعاد الكلية: {slide_w}px عرض × {slide_h}px ارتفاع.
- أقصى ارتفاع للمحتوى داخل الشريحة: {slide_h - header_h - footer_h - 20}px صافي بين الهيدر والفوتر.
- قانون عدم الخروج عن الحدود: يجب أن يتناسب كل محتوى الشريحة تماماً داخل هذا الارتفاع دون أن يقطع أي جزء منه.

## هوية الألوان المؤسسية الصارمة
- كحلي استثماري عميق (Primary / Navy): {primary} أو #0b1f33 (للعناوين الرئيسية، الكروت الداكنة الفاخرة، رؤوس الجداول الأساسية).
- أزرق سماوي راقي (Accent / Cyan): {accent} أو #0ea5e9 (للتمييز، النسب المئوية، الحدود النشطة، الرسوم البيانية).
- ذهبي / رملي هادئ (Warm Gold / Champagne): #c5a880 (للتفاصيل الفاخرة والإشارات التقديرية).
- خلفية فاتحة ناصعة ونظيفة: {bg} أو #f8fafc.
- لون النصوص: {text_color} أو #1e293b، والنصوص الفرعية بلون رمادي أردوازي #64748b.
- كروت بيضاء نقية: #ffffff (100% صلبة دائماً).
- ممنوع منعاً باتاً استخدام الألوان الفاقعة أو الوردية أو الفوشيا (Pink / Magenta / Neon) خارج لوحة الألوان المعتمدة.

## معالجة التدرجات والخلفيات لأجهزة Apple وWebKit
- قاعدة أمان متصفحات Apple (Safari و iOS): في أي CSS linear-gradient أو radial-gradient، لا تستخدم كلمة transparent إطلاقاً، لأن محرك WebKit يحولها إلى أسود شفاف مما يسبب هالات رمادية متسخة.
- استخدم دائماً اللون الأبيض الشفاف الصريح: rgba(255, 255, 255, 0) أو لون الخلفية بشفافية صفرية.
- تجنب الخلفيات شبه الشفافة الغائمة مثل rgba(255,255,255,0.7) على شاشات Retina لأنها تبدو رمادية باهتة؛ استخدم #ffffff صريح.

## الظلال والحدود (Flat Crisp Luxury - بدون ظلال ثقيلة)
- ممنوع استخدام الظلال السوداء الثقيلة أو المعتمة (Heavy Drop Shadows) إطلاقاً.
- اعتمد التصميم المسطح الراقي (Flat Luxury) باستخدام حدود ناعمة ودقيقة جداً: border: 1px solid #e2e8f0 أو border: 1px solid #edf2f7 مع border-radius: 10px إلى 14px.
- الظل الوحيد المسموح (إذا لزم الأمر) هو فائق النعومة والخفة: box-shadow: 0 1px 3px rgba(0,0,0,0.02) أو box-shadow: none.

## الخطوط والأحجام المحددة للتناسب
font-family: {font}
- العنوان الرئيسي للشريحة: 22px-26px font-weight:700 color:{primary} (أقصى حد 28px)
- عناوين البطاقات والأقسام: 14px-16px font-weight:600 color:{primary}
- النصوص العادية ونصوص البطاقات والجداول: 11px-13px font-weight:400 color:{text_color}
- الأرقام المالية الكبيرة: 22px-28px font-weight:700 color:{primary} مع تسميات واضحة بلون #64748b

## تصميم وعرض الدراسة المالية والجداول (Financial Study)
- اعتماد الجداول بدقة كاملة: اعتمد بيانات وأرقام الجداول المالية ومكونات المشروع المعتمدة كما هي دون تغيير أو اختصار يخل بالأرقام.
- قاعدة الرسوم البيانية والجداول المرافقة: إذا تضمنت الشريحة المالية رسماً بيانياً أو مخططاً دائرياً (Donut / Bar Chart / Matrix)، يجب إلزامياً وضع جدول البيانات الكامل بجانب الرسم البياني (جنباً إلى جنب في عمودين متناسقين مثل grid-template-columns: 1fr 1.2fr أو flex) لضمان الجمع بين الجاذبية البصرية والدقة الرقمية.
- تنسيق الجداول: صمم الجداول بأسلوب تنفيذي مسطح (Clean Hairline Table)، مع رأس جدول أنيق، وخطوط فاصلة دقيقة (border-bottom: 1px solid #e2e8f0)، وتباعد مريح، وأرقام واضحة ومحاذاة مناسبة.

## الشريحة الأساسية
<div class="slide" dir="rtl" style="width:{slide_w}px;height:{slide_h}px;position:relative;overflow:hidden;box-sizing:border-box;font-family:{font};background:{bg};">
CSS inline فقط. ممنوع box-shadow الثقيل أو filter أو backdrop-filter. استخدم box-sizing:border-box لكل العناصر.
"""

    if header_enabled:
        rules += f"""
## هيدر إلزامي — يجب أن يوجد في كل شريحة محتوى
position:absolute;top:0;right:0;left:0;height:{header_h}px;background:#ffffff;border-bottom:1px solid #e2e8f0;
المحتوى: شعار ##LOGO## height:36px يساراً + خط رأسي {accent} 3px + اسم الشريحة 16px font-weight:600 color:{primary}
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
top:{content_top}px إلى bottom:{content_bottom}px. padding: 16px 36px.
- إذا زاد عدد البطاقات أو العناصر عن 4، استخدم شبكة متعددة الأعمدة (grid 2x2 أو 3x2 مع gap:10px) أو توزيع أفقياً لضمان ملاءمة المحتوى كاملاً داخل الارتفاع المتاح.

## البطاقات (Cards)
كل بطاقة: background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; padding:12px 16px; box-sizing:border-box; box-shadow:none;
بدون أيقونات وبدون إيموجي نهائياً. اعتمد على التخطيط والخطوط والمساحات الأنيقة.
"""

    if template['use_gradients']:
        rules += f"تدرجات: استخدم linear-gradient(135deg,{primary},{secondary}) في الخلفيات والبطاقات المميزة مع استخدام rgba(255,255,255,0) للتلاشي الشفاف.\n"

    rules += f"""
## الصور Placeholder
- صورة الغلاف: ##IMAGE_COVER## (background-image فقط)
- صور المود بورد: ##MOODBOARD_IMAGE_1## إلى ##MOODBOARD_IMAGE_4##
- خريطة الموقع العام: ##MAP_OVERVIEW## (background-image)
- خريطة المعالم: ##MAP_LANDMARKS## (background-image)
- خريطة الوصول: ##MAP_ACCESS## (background-image)
- خريطة نطاق التأثير: ##MAP_CATCHMENT## (background-image)
- صور Street View: ##STREET_VIEW_1## إلى ##STREET_VIEW_4##
- شعار الشركة: ##LOGO## (height:36px في الهيدر، height:80px في الغلاف والختام)
- ممنوع رسم أي دوائر أو دبابيس أو مؤشرات موقع HTML فوق الخرائط (##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##) لأن هذه الصور تحتوي بالفعل على علامات موقع احترافية ومضلعات تحديد وبوصلة وخرائط مصغرة مرسومة مباشرة بدقة عالية.
- ممنوع base64 أو روابط صور خارجية — استخدم الـ placeholders فقط

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


def _managed_font_face(font_data, family, weight):
    if not font_data:
        return ''
    try:
        parsed = json.loads(font_data) if isinstance(font_data, str) and font_data.strip().startswith('{') else {'data': font_data, 'format': 'truetype'}
        data = parsed.get('data')
        fmt = parsed.get('format', 'truetype')
        if not data:
            return ''
        mime = {'truetype': 'font/ttf', 'opentype': 'font/otf', 'woff2': 'font/woff2', 'woff': 'font/woff'}.get(fmt, 'font/ttf')
        css_weight = '100 900' if weight == 'all' else {'light': 300, 'regular': 400, 'medium': 500, 'bold': 700, 'black': 900}.get(weight, 400)
        return f"@font-face{{font-family:'{family}';src:url(data:{mime};base64,{data}) format('{fmt}');font-weight:{css_weight};font-style:normal;font-display:swap;}}"
    except Exception:
        return ''


_MANAGED_FONT_WEIGHTS = {
    'light': 300,
    'regular': 400,
    'medium': 500,
    'bold': 700,
    'black': 900,
}
_SCRIPT_UNICODE_RANGES = {
    'arabic': 'U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+1EE00-1EEFF',
    'latin': 'U+0000-024F,U+1E00-1EFF,U+2000-206F',
}


def _managed_face_rule(font_data, family, weight, script):
    """Build one embedded face under a shared export family alias."""
    rule = _managed_font_face(font_data, family, weight)
    if not rule:
        return ''
    return rule[:-1] + f"unicode-range:{_SCRIPT_UNICODE_RANGES[script]};}}"


def _managed_face_rule_from_path(path, family, weight, script):
    abs_path = resolve_font_path(path)
    if not abs_path or _is_lfs_pointer(abs_path):
        return ''
    ext = os.path.splitext(abs_path)[1].lower()
    fmt = {'.ttf': 'truetype', '.otf': 'opentype', '.woff2': 'woff2', '.woff': 'woff'}.get(ext, 'truetype')
    with open(abs_path, 'rb') as font_file:
        payload = json.dumps({'data': base64.b64encode(font_file.read()).decode('ascii'), 'format': fmt})
    return _managed_face_rule(payload, family, weight, script)


def _managed_local_face_rule(local_family, family, weight, script):
    css_weight = '100 900' if weight == 'all' else _MANAGED_FONT_WEIGHTS.get(weight, 400)
    unicode_range = _SCRIPT_UNICODE_RANGES[script]
    return (
        f"@font-face{{font-family:'{family}';src:local('{local_family}');"
        f"font-weight:{css_weight};font-style:normal;unicode-range:{unicode_range};}}"
    )


def _managed_font_css(branding, tenant_id, fallback):
    try:
        from db import get_sag_font, get_sag_fonts, get_tenant_font_selections
    except Exception:
        return None

    def _path_payload(path):
        abs_path = resolve_font_path(path)
        if not abs_path or _is_lfs_pointer(abs_path):
            return None
        ext = os.path.splitext(abs_path)[1].lower()
        fmt = {'.ttf': 'truetype', '.otf': 'opentype', '.woff2': 'woff2', '.woff': 'woff'}.get(ext, 'truetype')
        with open(abs_path, 'rb') as font_file:
            return json.dumps({'data': base64.b64encode(font_file.read()).decode('ascii'), 'format': fmt})

    def _resolve_face(selection, font, script):
        if selection and selection.get('custom_font_data'):
            return 'data', selection['custom_font_data']
        if selection and selection.get('custom_font_path'):
            try:
                payload = _path_payload(selection['custom_font_path'])
            except OSError:
                payload = None
            return ('data', payload) if payload else None
        if not font:
            return None
        selected_family = font.get('font_family') or ('Arial' if script == 'latin' else 'The Sans Arabic')
        if font.get('file_data'):
            return 'data', font['file_data']
        source = _resolve_preset_font_source(font.get('source_data') or selected_family)
        if source and source.get('type') == 'bundled':
            payload = json.dumps({'data': source['data'], 'format': source.get('format', 'truetype')})
            return 'data', payload
        if source and source.get('type') in {'google', 'system'}:
            return source['type'], source
        if font.get('source_type') == 'system':
            return 'system', {'family': selected_family}
        return None

    def _build_rule(face, family, weight, script):
        if not face:
            return ''
        kind, source = face
        if kind == 'data':
            return _managed_face_rule(source, family, weight, script)
        if kind == 'system':
            return _managed_local_face_rule(source['family'], family, weight, script)
        if kind == 'google':
            return "@import url('https://fonts.googleapis.com/css2?family=" + source['encoded'] + ":wght@300;400;500;700;900&display=swap');"
        return ''

    rules = []
    import_rules = []
    imported_google_families = []
    tenant_selections = get_tenant_font_selections(tenant_id) if tenant_id else []
    legacy_family = branding.get('font_family') or ''
    if not tenant_selections and (branding.get('font_file_path') or branding.get('font_file_data')):
        return None
    if not tenant_selections and legacy_family and legacy_family not in {'The Sans Arabic'}:
        return None
    export_family = f"tenant-managed-{tenant_id or 'default'}"
    weights = tuple(_MANAGED_FONT_WEIGHTS)
    script_families = {
        'arabic': export_family,
        'latin': f'{export_family}-latin',
    }
    for script in ('arabic', 'latin'):
        script_selections = {item['weight']: item for item in tenant_selections if item.get('script') == script}
        # Once a company selects any face for a script, its available faces form
        # one family. Missing weights are synthesized from the nearest face.
        use_defaults = not script_selections
        available_faces = {}
        for weight in weights:
            selection = script_selections.get(weight)
            font = get_sag_font(selection.get('font_id')) if selection and selection.get('font_id') else None
            if use_defaults and not selection:
                font = next((item for item in get_sag_fonts(script=script, weight=weight) if item.get('is_default')), None)
            face = _resolve_face(selection, font, script)
            if face:
                available_faces[weight] = face
        if not available_faces:
            continue
        if len(available_faces) == 1:
            face = next(iter(available_faces.values()))
            generated_rules = [('all', face)]
        else:
            generated_rules = []
            for weight in weights:
                face = available_faces.get(weight)
                if face is None:
                    face = min(
                        available_faces.items(),
                        key=lambda item: abs(_MANAGED_FONT_WEIGHTS[item[0]] - _MANAGED_FONT_WEIGHTS[weight]),
                    )[1]
                generated_rules.append((weight, face))
        for weight, face in generated_rules:
            rule = _build_rule(face, script_families[script], weight, script)
            if not rule:
                continue
            if rule.startswith('@import'):
                if rule not in import_rules:
                    import_rules.append(rule)
                source = face[1]
                if source['family'] not in imported_google_families:
                    imported_google_families.append(source['family'])
            else:
                rules.append(rule)

    if not rules and not import_rules:
        return None
    families = [f"'{script_families['arabic']}'", f"'{script_families['latin']}'"]
    families.extend(f"'{family}'" for family in imported_google_families)
    family_list = ', '.join(families) + ', ' + fallback
    rules.append(f'.slide,.slide *{{font-family:{family_list} !important;}}')
    return '\n'.join(import_rules + rules), family_list


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

    # Managed per-weight selections take precedence over the legacy one-file setting.
    managed = _managed_font_css(branding, tenant_id, fallback)
    if managed:
        return managed

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
