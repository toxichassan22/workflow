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


# The class attribute is read as a token list, never as a substring: `\bslide\b` also matches
# `slide-inner`, `slide-footer` and `slide-title`, because `-` is a word boundary. With the
# bounded reader below that chopped one real slide into three fragments — an empty
# `<div class="slide"></div>` plus its own inner blocks — so the export both miscounted the deck
# and printed it in pieces.
_SLIDE_OPEN_RE = re.compile(
    r'<div\b[^>]*\bclass\s*=\s*(?:"([^"]*)"|\'([^\']*)\')[^>]*>',
    re.I,
)


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
    # The prompt no longer states a font name: the slide used to be told to write
    # `font-family:'The Sans Arabic'` inline, while the face actually loaded is a per-tenant alias
    # (`tenant-managed-<id>`) that carries the uploaded file. The two never matched, and any surface
    # that renders a slide without the injected stylesheet showed the wrong font.
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
- اللون الأساسي: {primary} للعناوين ورؤوس الجداول والمساحات الداكنة المحدودة.
- اللون الثانوي: {secondary} للعناوين الفرعية أو خلفية واحدة مساندة عند الحاجة.
- لون التمييز: {accent} للنسب والعناصر المهمة وخطوط الرسوم البيانية فقط.
- الخلفية: {bg}، مع الأبيض #ffffff لمساحات القراءة والجداول.
- لون النص: {text_color}، والنص الفرعي #64748b.
- اجعل 70-80% من الصفحة خلفية فاتحة أو بيضاء، و15-20% من اللون الأساسي، وبحد أقصى 10% من لون التمييز. لا توزع الألوان بالتساوي ولا تجعل كل مربع بلون مختلف.
- الرسوم البيانية تستخدم درجات اللون الأساسي والثانوي ولون التمييز فقط، مع الرمادي المحايد عند الحاجة. لا تستخدم أخضر أو أحمر أو برتقالي تلقائياً.
- ممنوع إدخال أي لون خارج لوحة الهوية والمحايدات المذكورة، وممنوع الألوان الفاقعة أو النيون.

## معالجة التدرجات والخلفيات لأجهزة Apple وWebKit
- قاعدة أمان متصفحات Apple (Safari و iOS): في أي CSS linear-gradient أو radial-gradient، لا تستخدم كلمة transparent إطلاقاً، لأن محرك WebKit يحولها إلى أسود شفاف مما يسبب هالات رمادية متسخة.
- استخدم دائماً اللون الأبيض الشفاف الصريح: rgba(255, 255, 255, 0) أو لون الخلفية بشفافية صفرية.
- تجنب الخلفيات شبه الشفافة الغائمة مثل rgba(255,255,255,0.7) على شاشات Retina لأنها تبدو رمادية باهتة؛ استخدم #ffffff صريح.

## الظلال والحدود (Flat Crisp Luxury - بدون ظلال ثقيلة)
- ممنوع استخدام الظلال السوداء الثقيلة أو المعتمة (Heavy Drop Shadows) إطلاقاً.
- اعتمد التصميم المسطح الراقي (Flat Luxury) باستخدام حدود ناعمة ودقيقة جداً: border: 1px solid #e2e8f0 أو border: 1px solid #edf2f7 مع border-radius: 10px إلى 14px.
- الظل الوحيد المسموح (إذا لزم الأمر) هو فائق النعومة والخفة: box-shadow: 0 1px 3px rgba(0,0,0,0.02) أو box-shadow: none.

## الخطوط والأحجام المحددة للتناسب (Bold Executive Hierarchy)
**ممنوع كتابة font-family في أي عنصر أو في أي style.** خط الشركة يُطبَّق تلقائيًا على الشريحة كلها من
إعدادات الشركة (قد يكون خطًا مرفوعًا لا يعرفه أي جهاز)، فأي font-family تكتبه يخالف الخط المعتمد.
حدّد الأحجام والوزن لخدمة التسلسل البصري الواضح مع استخدام خط عريض وبارز للعناوين والمؤشرات:
- عنوان الشريحة الرئيسي: 24px-28px وfont-weight:800 (Bold قوي وبارز) باللون {primary}.
- عنوان القسم أو الجدول: 16px-18px وfont-weight:700 باللون {primary}.
- تسمية الحقل أو المؤشر: 12px-14px وfont-weight:600 باللون {text_color}.
- الفقرات والقيم والوصف وخلايا الجدول: 11px-13px وfont-weight:400 باللون {text_color}، مع تمييز الكلمات المفتاحية بوزن 700.
- الأرقام المالية الرئيسية والمؤشرات الكبرى: 24px-30px وfont-weight:800 باللون {primary} أو {accent}.
- ممنوع خلط أكثر من عائلة خط واحدة.

## شريحة الغلاف (Cover Slide - Full Bleed Background)
- صورة الغلاف (##IMAGE_COVER##) يجب أن تمتد كخلفية كاملة على كامل الشريحة (Full Bleed Background):
  `position:absolute; inset:0; background-image:url('##IMAGE_COVER##'); background-size:cover; background-position:center; z-index:0;`
- وضع طبقة تدرج لوني داكن فخم فوق الصورة لضمان وضوح النصوص والشعارات:
  `position:absolute; inset:0; background:linear-gradient(135deg, rgba(11,31,51,0.85) 0%, rgba(11,31,51,0.55) 50%, rgba(11,31,51,0.9) 100%); z-index:1;`
- وضع المحتوى النصي والعناوين والشعارات فوق التدرج (`z-index:2`) بلون أبيض ناصع وتباين فخم.

## معالجة تباين وخلفيات الشعارات الذكية (Adaptive Independent Logo Containers)
- **مبدأ تباين الشعارات المستقل:** يجب أن يظهر كل شعار (سواء شعار الشركة ##LOGO## أو شعار المشروع ##PROJECT_LOGO##) بوضوح تام وتباين عالٍ ومقروء 100%، ويتم تقييم كل شعار باستقلالية تامة حسب ألوانه والخلفية الموضوع عليها:
  - **في هيدر شرائح المحتوى (الخلفية فاتحة/بيضاء #ffffff):**
    - **الشعار الداكن أو الملون** (مثل الأخضر، الكحلي، الأسود، الذهبي الداكن): يوضع مباشرة وبشكل طبيعي على الهيدر الأبيض دون أي حاوية أو شارة داكنة إطلاقاً (خلفية شفافة `background: transparent;`).
    - **الشعار ذو النصوص أو العناصر البيضاء/الفاتحة جداً** (التي لا تُقرأ على الأبيض): يُوضع **هذا الشعار الفاتح فقط** داخل شارة داكنة أنيقة ناعمة (`background:{primary}; padding:4px 10px; border-radius:6px; display:inline-flex; align-items:center;`).
    - **ممنوع منعاً باتاً وضع الشعار الداكن داخل شارة داكنة**، وممنوع دمج الشعارين معاً في شارة واحدة عشوائية إذا اختلف لونهما.
  - **في الشرائح الداكنة (الغلاف، الختام، فواصل الأقسام الداكنة):**
    - **الشعار الأبيض أو الفاتح:** يوضع مباشرة على الخلفية الداكنة بأناقة وتباين كامل.
    - **الشعار الداكن** (الذي لا يظهر على الخلفية الداكنة): يُوضع **هذا الشعار الداكن فقط** داخل حاوية بيضاء أو فاتحة ناعمة (`background:#ffffff; padding:6px 14px; border-radius:8px; display:inline-flex; align-items:center;`).

## توسيط صور الخرائط والموقع (Centered Maps - No Crop Shift)
- صور الخرائط (##MAP_OVERVIEW##, ##MAP_LANDMARKS##, ##MAP_ACCESS##, ##MAP_CATCHMENT##) يجب أن تُضبط دائماً في المنتصف تماماً:
  `background-position: center center !important; background-size: cover !important;` أو عند استخدام وسم img: `object-fit: cover !important; object-position: center center !important;`
- ممنوع إزاحة أو اقتطاع أطراف الخريطة بشكل غير متوازن.

## منظومة الرسوم البيانية الشاملة وتنوع أنماط العرض (Pure HTML/CSS Executive Charts)
يجب التنويع الذكي في استخدام أنواع الرسوم البيانية حسب طبيعة البيانات المعروضة، مع تنفيذها بـ HTML و CSS نقي فائق الجودة والنعومة ومتوافق بالكامل:
1. **المخططات الدائرية والدائرية المجوفة (Pie & Donut Charts):**
   - **الاستخدام الأنسب:** توزيع مساحات مكونات المشروع، الحصص النسبية للاستخدامات (سكني/تجاري/فندقي)، توزيع مصادر التمويل (حقوق ملكية vs تمويل بنكي)، وتوزيع الإيرادات حسب النشاط.
   - **طريقة التنفيذ:** عنصر دائري بـ `border-radius: 50%` مع `conic-gradient(var(--accent) 0% 40%, var(--primary) 40% 70%, var(--secondary) 70% 100%)`، وللمخطط المجوف (Donut) يوضع مركز أبيض دائري داخله (`border-radius: 50%; background: #fff;`) يعرض الرقم الإجمالي أو النسبة الأكبر في وسطه، بجانب دليل بياني (Legend) منظم يوضح اسم كل بند ونسبته ولونه.
2. **مخططات الانتشار والنقاط (Scatter Plots):**
   - **الاستخدام الأنسب:** تحليل أسعار المتر مقابل المساحات في السوق، مقارنة العائد بحجم الاستثمار للمكونات، ومصفوفة المخاطر مقابل العائد.
   - **طريقة التنفيذ:** شبكة إحداثيات ثنائية أنيقة بخطوط شبكة رمادية خفيفة ومحوري X و Y واضحين، مع نقاط بيانات متموضعة بـ `position: absolute; left: X%; bottom: Y%;` مع خلفية بارزة وتأثير نقطي ناعم وتسمية لكل نقطة.
3. **مخططات التوزيع التكراري (Histogram & Range Distribution):**
   - **الاستخدام الأنسب:** توزيع فئات مساحات الوحدات السكنية/المكتبية، فئات الأسعار الإيجارية في المنطقة، وتوزيع آجال التدفقات.
   - **طريقة التنفيذ:** أعمدة متلاصقة أو متتالية رأسية متدرجة الارتفاع بألوان الهوية مع تسمية الفئات السفلية بدقة (مثل: «100-150 م²»، «151-200 م²»).
4. **مخطط الشموع ونطاقات السيناريوهات (Candlestick & Scenario Range Charts):**
   - **الاستخدام الأنسب:** تحليل الحساسية وتعدد السيناريوهات المالية (السيناريو المتفائل / الأساسي / المتحفظ)، ونطاقات أسعار المتر المتوقعة (الأعلى / المتوسط / الأدنى).
   - **طريقة التنفيذ:** خط عمودي رفيع يمثل النطاق الكلي (المدى الأعلى والأدنى) يتوسطه مستطيل مالي ملون عريض يمثل النطاق المرجح (Base Range) مع وسم واضح لقيمة السيناريو الأساسي.
5. **مخططات التدفق والشبكات والمسارات (Networkgram / Pipeline / Sankey Flow):**
   - **الاستخدام الأنسب:** مسارات تدفق التمويل والأرباح، هيكل الصندوق الاستثماري والجهات المرتبطة، ومراحل التطوير التنفيذية وسحب وسداد التمويل.
   - **طريقة التنفيذ:** كتل وبطاقات متسلسلة مرتبطة بخطوط وصل ومسارات تدفق وشارات أسهم بالألوان المؤسسية مع إبراز المبالغ لكل مرحلة.
6. **المنحنيات والخطوط والمساحات التراكمية (Line & Stepped Area Charts):**
   - **الاستخدام الأنسب:** التدفقات النقدية السنوية والتراكمية، منحنى الوصول للإشغال الكامل، ومنحنى استرداد رأس المال.
   - **طريقة التنفيذ:** مخطط مسار بأعمدة أو مساحات متدرجة الارتفاع أو خطوط مؤشرات تربط السنوات بالأرقام والقيم الدقيقة.
7. **الأعمدة والأشرطة والمقارنات (Bar & Column / Stacked Charts):**
   - **الاستخدام الأنسب:** مقارنة الإيرادات بالتكاليف، ومقارنة التكاليف الرأسمالية للمكونات.
   - **طريقة التنفيذ:** أشرطة أفقية أو أعمدة رأسية بنسب دقيقة وألوان الهوية مع جدول البيانات الأصلي الكامل بجانبها.

- اعرض جميع أقسام وجداول ومؤشرات الدراسة الموجودة في البيانات، بالترتيب والمسميات نفسها المستخدمة في تقرير الدراسة المالية، ولا تختصرها في لوحة مؤشرات واحدة.
- انقل كل قيمة ووحدة وعدد خانات عشرية كما هو. أضف فواصل الآلاف بصرياً فقط، من دون تقريب أو تحويل إلى آلاف أو ملايين أو إعادة حساب.
- عند وجود قيم فعلية قابلة للمقارنة، أضف رسماً بيانياً واضحاً بألوان الهوية، مع جدول البيانات الأصلي الكامل بجانبه. لا ترسم مخططاً من قيم وصفية أو ناقصة.
- لا تغيّر أسماء المؤشرات: تبقى ROI وProject IRR وEquity IRR وNOI وبقية المسميات كما وردت في الدراسة.
- الجداول تستخدم رأسًا واضحًا وفواصل دقيقة وتباعدًا مريحًا، ويمكن أن تمتد على صفحات إضافية؛ ممنوع حذف صف أو عمود لتناسب صفحة واحدة.

## تجنب التقطيع المفرط والشارات المكررة
- عدم اختصار الكلام أو تفتيت المحتوى إلى شبكة مربعات وبطاقات صغيرة كثيرة مفتعلة؛ اجعل المحتوى متماسكاً وفقرات متكاملة وجداول منسقة.
- ممنوع وضع شارات أو كبسولات مكررة مثل «* مشروع متعدد الاستخدامات *» أو شارات تصنيف عامة أعلى شرائح المحتوى العادية.

## الشريحة الأساسية
<div class="slide" dir="rtl" style="width:{slide_w}px;height:{slide_h}px;position:relative;overflow:hidden;box-sizing:border-box;background:{bg};">
CSS inline فقط، وبدون font-family. ممنوع box-shadow الثقيل أو filter أو backdrop-filter. استخدم box-sizing:border-box لكل العناصر.
"""

    if header_enabled:
        rules += f"""
## هيدر إلزامي — يجب أن يوجد في كل شريحة محتوى
position:absolute;top:0;right:0;left:0;height:{header_h}px;background:#ffffff;border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between;padding:0 24px;box-sizing:border-box;
المحتوى:
- في أحد الجانبين: شعار الشركة ##LOGO## (height:32px-36px) مع شعار المشروع ##PROJECT_LOGO## إن وُجد كصورة متناسقة بجانبه (أو شارة نصية باسم المشروع).
- في الجانب المقابل: خط رأسي {accent} 3px + اسم الشريحة 16px font-weight:700 color:{primary}.
- **قاعدة وضوح وتباين الشعارات في الهيدر:**
  - إذا كان الشعار داكناً أو ملوناً: يوضع مباشرة على الهيدر الأبيض دون أي خلفية داكنة.
  - إذا كان الشعار أبيض أو فاتح جداً: يوضع هذا الشعار الفاتح فقط داخل شارة داكنة (`background:{primary}; padding:4px 10px; border-radius:6px; display:inline-flex; align-items:center;`).
"""

    if footer_enabled:
        rules += f"""
## فوتر إلزامي — يجب أن يوجد في كل شريحة محتوى
position:absolute;bottom:0;right:0;left:0;height:{footer_h}px;background:{primary};display:flex;align-items:center;padding:0 16px;
المحتوى: اسم المشروع 13px أبيض + '{company_name}' opacity:0.7 + رقم الصفحة كنص واضح بلون {accent} من دون دائرة أو شارة
"""

    content_top = header_h if header_enabled else 0
    content_bottom = footer_h if footer_enabled else 0
    rules += f"""
## منطقة المحتوى والتخطيط
top:{content_top}px إلى bottom:{content_bottom}px. padding: 16px 36px.
- النبذة والملخص: فقرة أو عمود نصي واضح مع صورة كبيرة عند توفرها.
- البيانات المنظمة: جدول واحد واضح، ويمكن تقسيمه على صفحات إضافية.
- الأرقام القابلة للمقارنة: رسم بياني مناسب (Pie / Donut, Scatter, Histogram, Candlestick, Line, Bar, Flow) مع جدول المصدر بجانبه.
- الصور والمخططات: صورة واحدة كبيرة أو صورتان بحد أقصى، مع عنوان ووصف كل صورة دون تكرار.
- لا تستخدم شبكة مربعات لمجرد ملء الصفحة، ولا تكرر العنصر نفسه كنص وبطاقة ومؤشر.

## البطاقات (Cards)
تستخدم فقط لعنصرين أو ثلاثة مستقلين وقصيرين. كل بطاقة: background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; padding:12px 16px; box-sizing:border-box; box-shadow:none;
بدون أيقونات وبدون إيموجي نهائياً. إذا تجاوز المحتوى ثلاثة عناصر أو احتوى فقرات مترابطة فاستخدم نصاً أو جدولاً بدلاً من البطاقات.
"""

    if template['use_gradients']:
        rules += f"تدرجات: استخدم linear-gradient(135deg,{primary},{secondary}) في الخلفيات والبطاقات المميزة مع استخدام rgba(255,255,255,0) للتلاشي الشفاف.\n"

    rules += f"""
## الصور Placeholder
- صورة الغلاف: ##IMAGE_COVER## (background-image فقط كخلفية كاملة Full Bleed مع تدرج داكن)
- التصورات الخارجية: ##MOODBOARD_IMAGE_1## إلى ##MOODBOARD_IMAGE_N##. استخدم صورة واحدة كبيرة أو صورتين بحد أقصى لكل صفحة مع التسمية والوصف الصحيحين، وضعها في قسم التصورات الخارجية لا قبل الخاتمة.
- نبذة عن المشروع يمكن أن تستخدم صورة أو صورتين من هذه الصور الخارجية غير صورة الغلاف، مع بقاء النص هو المحتوى الرئيسي.
- صور الأرض: ##LAND_PHOTO_1## إلى ##LAND_PHOTO_N##، كل صورة بحجم واضح مع وصفها المحفوظ داخل قسم تحليل الأرض، ثم الملخص النهائي للأرض.
- التصورات الداخلية: ##INTERIOR_COMP_1_IMG_1## وما يماثلها. استخدم صورة واحدة كبيرة أو صورتين بحد أقصى في الصفحة، ووزع صور المكون على صفحات إضافية عند الحاجة.
- المخططات المعمارية 2D: ##PLAN_IMAGE_1## إلى ##PLAN_IMAGE_N## (أو ##2D_PLAN_N##)، وكل مخطط في صفحة مستقلة أو مساحة كبيرة مع عنوانه ووصفه الصحيحين.
- شعارات فريق العمل: ##TEAM_LOGO_1## إلى ##TEAM_LOGO_N##. عند ذكر جهة لها شعار متوفر يجب أن يظهر شعارها بوضوح بجانب اسمها، ولا يُستبدل بشعار الشركة.
- خريطة الموقع العام: ##MAP_OVERVIEW## (background-image مضبوطة في المنتصف center center)
- خريطة المعالم: ##MAP_LANDMARKS## (background-image مضبوطة في المنتصف center center)
- خريطة الوصول: ##MAP_ACCESS## (background-image مضبوطة في المنتصف center center)
- خريطة نطاق التأثير: ##MAP_CATCHMENT## (background-image مضبوطة في المنتصف center center)
- لا توجد صور فوتوغرافية للشوارع أو لمحيط الموقع، ولا تُولَّد من الخرائط ولا من التصور البصري: ممنوع كتابة ##STREET_VIEW_1## أو أي رمز مشابه، وممنوع إنشاء شريحة صور موقع أو بطاقات صور للمحيط. الموقع يُعرض بالخرائط والبيانات.
- شعار الشركة: ##LOGO## (height:36px في الهيدر، height:80px في الغلاف والختام؛ يوضع مباشرة على الخلفية الفاتحة إذا كان داكناً، أو داخل شارة داكنة إذا كانت نصوصه بيضاء)
- شعار المشروع ##PROJECT_LOGO##: إذا ذُكر في «الصور المتوفرة» أنه متوفر فوضعه **إلزامي** — في هيدر كل شريحة محتوى بجانب شعار الشركة، وفي الغلاف والختام كذلك. الشعاران جنبًا إلى جنب بفاصل رأسي رقيق (1px solid #e2e8f0) وبارتفاع واحد متساوٍ (36px في الهيدر، 72px-80px في الغلاف والختام). يُعامل كل شعار باستقلالية تامة حسب تباين ألوانه (الشعار الفاتح على الأبيض يُوضع في شارة داكنة، والشعار الداكن على الداكن يُوضع في شارة بيضاء، والشعار المتناسق مع الخلفية يوضع مباشرة بدون شارة). إذا ذُكر أنه غير متوفر فلا تكتب ##PROJECT_LOGO## إطلاقًا.
- ممنوع رسم أي دوائر أو دبابيس أو مؤشرات موقع HTML فوق الخرائط (##MAP_OVERVIEW##، ##MAP_LANDMARKS##، ##MAP_ACCESS##، ##MAP_CATCHMENT##) لأن هذه الصور تحتوي بالفعل على علامات موقع احترافية ومضلعات تحديد وبوصلة وخرائط مصغرة مرسومة مباشرة بدقة عالية.
- ممنوع base64 أو روابط صور خارجية — استخدم الـ placeholders فقط

## صفحات بداية الأقسام (section_divider)
- قبل كل قسم موجود صفحة تحمل اسم القسم العربي المعتمد وحده، وخلفيتها الصورة الرئيسية المعتمدة مع حجاب من اللون الأساسي.
- التخطيط ثابت ويُبنى تلقائيًا: الشعار أعلى اليسار، اسم القسم كبيرًا على اليمين، خط تمييز قصير، رقم الصفحة واسم المشروع فقط.
- ممنوع إضافة ترجمة أو وصف أو سطر فرعي أو نقاط أو بطاقات أو جداول إلى صفحة بداية القسم.

## الالتزام بمحتوى المشروع (قاعدة قاطعة)
- كل رقم واسم وتاريخ ونسبة ومساحة في الشرائح يجب أن يكون موجودًا في «بيانات المشروع» أو في جداول الدراسة المالية والجدول الزمني المرفقة. ممنوع اختراع أي معلومة أو استكمالها بتقدير أو بمعرفة عامة عن السوق.
- إذا كانت معلومة غير متوفرة فلا تذكرها ولا تضع مكانها قيمة تقريبية أو نصًا إنشائيًا يوحي بوجودها؛ اكتفِ بالمتاح أو اجعل الشريحة أصغر.
- إعادة الصياغة والترتيب والتصميم مسموحة. تغيير المعنى أو الأرقام غير مسموح.

## المخططات المعمارية 2D (ممنوع الرسم)
- ممنوع منعًا باتًا رسم أو تركيب أي مخطط معماري أو مسقط أفقي بنفسك — لا بـ HTML/CSS ولا بجداول ولا بمربعات divs ولا بـ SVG.
- المخططات تُعرض **فقط** كصور مرفوعة من العميل عبر ##PLAN_IMAGE_1## إلى ##PLAN_IMAGE_N##، ووجودها إلزامي في الشرائح إن كانت متوفرة في «الصور المتوفرة».
- إذا لم تكن هناك مخططات مرفوعة فلا تُنشئ شريحة مخططات إطلاقًا.

## المخطط الاتجاهي لحدود الأرض والواجهات (Directional Boundary Diagram)
- عند وجود شريحة «مخطط اتجاهي لحدود الأرض» بنمط `diagram`: صمّم مخططاً اتجاهياً هندسياً متناسقاً وراقياً بـ HTML و CSS النقي بألوان الهوية فقط ودون أيقونات أو إيموجي.
- الهيكل المعتمد للشريحة:
  1. عنوان الشريحة «مخطط اتجاهي لحدود الأرض» مع عبارة «الأبعاد بالمتر» في الزاوية العلوية المقابلة.
  2. صندوق مركزي عريض وأنيق يمثل «أرض المشروع» بألوان الهوية وخلفية مميزة، يكتب في وسطه اسم «أرض المشروع» مع خط تمييز وملخص الواجهات (مثل «واجهتان شرقية وغربية»)، وتوضع على حوافه الأربع أطوال الأضلاع للحدود الأربعة بوضوح («حد شمالي ... م»، «حد جنوبي ... م»، «حد شرقي ... م»، «حد غربي ... م»).
  3. بطاقات خارجية للجهات الأربع المحيطة (شمال، جنوب، شرق، غرب) مبيناً في كل منها تفاصيل الشارع أو الجار وطول الضلع وعرض الشارع، مع تمييز الشوارع والواجهات بلون التمييز (مثل الذهبي).
  4. بطاقة بارزة ومميزة بألوان الهوية لجهة الإطلالة أو الطريق الرئيسي إن وجدت (مثل «جهة الإطلالة البحرية» أو «طريق الكورنيش»).
  5. ملاحظة توضيحية أسفل الشريحة بخط ناعم: «تمثل القراءة اتجاهات الحدود وعلاقتها بالشوارع دون محاكاة مساحية للنسب.»

## الرسوم البيانية عند الحاجة ومخططات التدفق
- استخدم رسمًا بيانيًا أو مخطط تدفق (Flowchart) في الدراسة المالية ومقارنة المنافسين والمراحل عندما توجد قيم رقمية أو خطوات فعلية قابلة للعرض المرئي.
- ارسمه بـ HTML/CSS فقط بألوان الهوية، وبدون مكتبة رسم أو أيقونات.
- كل رسم مبني على القيم الموجودة حرفيًا، ويعرض جدول المصدر الكامل بجانبه. لا تكرر الرسم نفسه أو تحول القيم المنفردة إلى رسم غير مفيد.

## الملخصات ومنع التكرار
- أقسام الأرض والموقع والسوق والدراسة المالية تنتهي بملخصها المعتمد بعد الجداول، مرة واحدة فقط.
- لا تعيد مكونات المشروع أو بيانات الموقع في أكثر من قسم. عند الحاجة استخدم إحالة نصية قصيرة بلا إعادة القائمة أو الجدول.
- التحسينات التحريرية قصيرة ومبنية على قيمة واضحة في البيانات؛ ممنوع الحشو والاسترسال أو إضافة استنتاج غير مسند.

## الخاتمة
- تعرض اسم المشروع والشركة وبيانات التواصل المتاحة فقط مع عبارة شكر موجزة.
- ممنوع كتابة «فرصة واعدة بشروط» أو «فرصة مشروطة» أو أي تقييم أو توصية استثمارية عامة في الخاتمة.

## اسم الشركة في الفوتر
{company_name}
"""

    # Rules the company wrote for itself through the admin agent. They ride with every slide prompt
    # and every design edit, because that is the only way to change the generation prompt without a
    # code change. They add to the rules above; they never license inventing a fact, an icon or an
    # emoji, nor rewriting a stated number.
    company_rules = str(branding.get('generation_rules') or '').strip()
    if company_rules:
        rules += (
            "\n\n## قواعد التوليد الملزمة لهذه الشركة (كتبها الأدمن — التزم بها فوق ما سبق)\n"
            f"{company_rules[:8000]}\n"
            "إن تعارضت هذه القواعد مع منع اختراع المعلومات أو منع الأيقونات والإيموجي أو نقل الأرقام"
            " كما هي، فالقواعد الأساسية أعلاه هي التي تُطبَّق.\n"
        )

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

    def kind_of_face(face):
        return face[0] if face else ''

    rules = []
    import_rules = []
    imported_google_families = []
    # Which scripts got a face whose file travels with the deck, rather than a name the reading
    # machine must already have.
    shipped_scripts = set()
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
                if kind_of_face(face) == 'data':
                    shipped_scripts.add(script)

    if not rules and not import_rules:
        return None
    families = [f"'{script_families['arabic']}'", f"'{script_families['latin']}'"]
    families.extend(f"'{family}'" for family in imported_google_families)
    # A company can legitimately choose a system font such as Arial for the whole deck. It renders
    # wherever it is installed, but the PDF is rendered on the server, which has no Arial and no
    # Tahoma — Arabic then landed on whatever Chromium had, usually DejaVu. So a shipped Arabic face
    # is appended last: the choice still wins where it exists, and the export stays readable.
    if 'arabic' not in shipped_scripts:
        bundled = _load_bundled_fonts().get('TheSansArabic-Light') or _load_bundled_fonts().get('TheSansArabic-Bold')
        if bundled:
            data, fmt = bundled
            mime = {'truetype': 'font/ttf', 'opentype': 'font/otf', 'woff2': 'font/woff2', 'woff': 'font/woff'}.get(fmt, 'font/ttf')
            rules.append(
                f"@font-face{{font-family:'platform-fallback-arabic';src:url(data:{mime};base64,{data})"
                f" format('{fmt}');font-weight:100 900;font-display:swap;}}"
            )
            families.append("'platform-fallback-arabic'")
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

    # 4) The stored name has no loadable source anywhere. Emitting the bare name meant the slide fell
    # back to whatever the reading machine happened to have — usually Tahoma — with nothing to show
    # why. This is not a rare corner: any name saved without a matching file or selection lands here,
    # including one the admin agent typed. Ship the bundled platform face behind the requested name
    # so the slides and the PDF always carry a real Arabic font.
    print(f"[FONT] no bundled or Google source for '{chosen}'; falling back to the bundled platform face")
    bundled = _load_bundled_fonts().get('TheSansArabic-Light') or _load_bundled_fonts().get('TheSansArabic-Bold')
    if bundled:
        data, fmt = bundled
        mime = {'truetype': 'font/ttf', 'opentype': 'font/otf', 'woff2': 'font/woff2', 'woff': 'font/woff'}.get(fmt, 'font/ttf')
        family = 'platform-fallback-arabic'
        family_list = f"{_font_family_list(chosen).rsplit(', ' + FALLBACK_FONTS, 1)[0]}, '{family}', {fallback}"
        css = (
            f"@font-face{{font-family:'{family}';src:url(data:{mime};base64,{data}) format('{fmt}');"
            f"font-weight:100 900;font-display:swap;}}\n"
            f".slide,.slide *{{font-family:{family_list} !important;}}"
        )
        return css, family_list
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
