"""
Design templates for Multi-Tenant SaaS.
Pre-built design styles that companies can choose from.
"""

DESIGN_TEMPLATES = {
    'modern': {
        'name': 'مودرن',
        'name_en': 'modern',
        'description': 'تصميم عصري نظيف بحدود رفيعة ومساحات بيضاء',
        'card_style': 'bordered',
        'header_style': 'minimal',
        'use_gradients': False,
        'icon_style': 'unicode',
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
        'icon_style': 'unicode',
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
        'icon_style': 'unicode',
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
        'icon_style': 'unicode',
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
        'icon_style': 'unicode',
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
    font = branding.get('font_family', 'The Sans Arabic')
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

## الخط
font-family: '{font}', Arial, sans-serif
- عناوين كبيرة: 36-48px font-weight:700 color:{primary}
- عناوين فرعية: 24-28px font-weight:600 color:{primary}
- نصوص عادية: 14-18px font-weight:400 color:{text_color}
- أرقام مالية كبيرة: 32-48px font-weight:700 color:{primary}

## الشريحة الأساسية
<div class="slide" dir="rtl" style="width:{slide_w}px;height:{slide_h}px;position:relative;overflow:hidden;font-family:'{font}',Arial,sans-serif;">
CSS inline فقط. ممنوع box-shadow/filter/backdrop-filter.
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
## منطقة المحتوى
top:{content_top}px → bottom:{content_bottom}px. padding: 20px 40px.

## البطاقات (Cards) — نمط {card_style}
"""
    if card_style == 'bordered':
        accent_rgb = _hex_to_rgb(accent)
        rules += f"كل بطاقة: background:#fff border:1px solid rgba({accent_rgb},0.2) border-radius:8px padding:16-24px.\n"
    elif card_style == 'shadow':
        rules += f"كل بطاقة: background:#fff border-radius:12px padding:16-24px. ظل خفيف: box-shadow:0 2px 8px rgba(0,0,0,0.08).\n"
    elif card_style == 'flat':
        rules += f"كل بطاقة: background:{bg} border-radius:8px padding:16-24px. بدون حدود أو ظلال.\n"
    elif card_style == 'gradient':
        rules += f"كل بطاقة: background:linear-gradient(135deg,{primary},{secondary}) border-radius:12px padding:16-24px color:#fff.\n"

    if template['icon_style'] == 'unicode':
        rules += f"""
## الأيقونات — قواعد صارمة
⛔ ممنوع تماماً استخدام Unicode Emojis الملونة (🏗️ 📊 💰 🏠 📍 ✅ ⚠️ 🔑 📈) — هذا عرض عقاري احترافي وليس رسالة واتساب.
✅ استخدم أيقونات SVG inline أحادية اللون (monochrome) بحجم 20-28px.
- لون الأيقونات: {primary} أو {accent} أو #FFFFFF (حسب خلفية البطاقة)
- الأيقونات يجب أن تكون بسيطة وهندسية (geometric) — خطوط رفيعة بدون تعبئة
- مثال على SVG مقبول:
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{primary}" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
- أيقونات مقترحة حسب الموضوع:
  * موقع/عنوان: دائرة بداخلها نقطة (location pin بسيط)
  * مبنى/عقار: مستطيل بخطوط أفقية (building outline)
  * مالية/أرقام: مستطيلات بأعمدة (bar chart)
  * طرق/وصول: خطوط متقاطعة (road intersection)
  * مساحة: مربع بأبعاد (square with dimensions)
  * وقت: دائرة بعقارب (clock)
  * نقطة إيجابية: دائرة بعلامة صح (checkmark circle)
"""
    else:
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
