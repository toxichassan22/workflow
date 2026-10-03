"""
Email Templates & HTML Layout Engine for LandLoom AI.

World-class, high-conversion, responsive email templates inspired by top-tier tech brands:
- Google Security: Minimalist white cards, user identity pills, bold headlines, blue pill buttons.
- Cloudflare: Vibrant high-impact gradient hero banners with clean white content sections.
- X (Twitter): Modular feature tiles with dark gradient monogram badges and clean action links.
- Chess.com: High-energy contrast, punchy orange CTAs, prominent metrics and status callouts.

Strict repository compliance (AGENTS.md):
- Zero emojis and zero icon fonts (pure CSS/HTML typography and geometric badges).
- No how-to instructional copy (purely states what items are).
- Rock-solid client rendering (Gmail, Apple Mail, Outlook, iOS, Android).
"""

import html as _html_lib


def build_base_email(
    title,
    content_html,
    badge=None,
    preheader=None,
    hero_banner=None,       # Optional dict: {'title': str, 'subtitle': str, 'gradient': str, 'tag': str}
    user_pill=None,          # Optional dict: {'name': str, 'email': str}
    cta_text=None,
    cta_url=None,
    cta_style='primary',     # 'primary' (blue), 'orange' (chess.com), 'obsidian' (dark), 'outline' (linkedin)
    secondary_tiles=None,    # Optional list: [{'title': str, 'desc': str, 'link_text': str, 'link_url': str, 'badge': str, 'monogram': str}]
    secondary_note=None,
    footer_text=None,
    theme='light',           # 'light' (clean white/slate card) or 'dark' (obsidian tech card)
):
    """
    Universal responsive email engine for LandLoom AI.
    Renders pixel-perfect, high-impact HTML layouts across all major email clients.
    """
    safe_title = _html_lib.escape(title or '')
    preview_snippet = _html_lib.escape(preheader or title or '')

    is_dark = (theme == 'dark')
    body_bg = '#090d16' if is_dark else '#f4f6f9'
    card_bg = '#111827' if is_dark else '#ffffff'
    card_border = '#1f293d' if is_dark else '#e2e8f0'
    text_primary = '#f8fafc' if is_dark else '#07182c'
    text_secondary = '#94a3b8' if is_dark else '#475569'
    tile_bg = '#1e293b' if is_dark else '#f8fafc'
    tile_border = '#334155' if is_dark else '#e2e8f0'

    # ── 1. Hero Header Banner (Cloudflare / Chess.com style) ───────────────────
    hero_html = ''
    if hero_banner:
        h_title = _html_lib.escape(hero_banner.get('title', ''))
        h_sub = _html_lib.escape(hero_banner.get('subtitle', ''))
        h_tag = _html_lib.escape(hero_banner.get('tag') or 'LANDLOOM AI')
        gradient = hero_banner.get('gradient') or 'linear-gradient(135deg, #07182c 0%, #1e3a8a 55%, #0369a1 100%)'
        hero_html = f'''
        <tr>
          <td style="background: {gradient}; padding: 48px 36px 42px 36px; border-radius: 20px 20px 0 0; text-align: center; direction: rtl;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin: 0 auto 16px auto;">
              <tr>
                <td align="center" style="background: rgba(255, 255, 255, 0.16); border: 1px solid rgba(255, 255, 255, 0.28); border-radius: 24px; padding: 4px 16px; font-size: 11px; font-weight: 800; color: #ffffff; letter-spacing: 1.2px; text-transform: uppercase;">
                  {h_tag}
                </td>
              </tr>
            </table>
            <h1 style="margin: 0; font-size: 30px; font-weight: 900; color: #ffffff; line-height: 1.3; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Tahoma, sans-serif; letter-spacing: -0.5px;">
              {h_title}
            </h1>
            {f'<div style="margin-top: 12px; font-size: 15px; color: rgba(255, 255, 255, 0.92); font-weight: 500; line-height: 1.6; max-width: 480px; margin-left: auto; margin-right: auto;">{h_sub}</div>' if h_sub else ''}
          </td>
        </tr>'''

    # ── 2. User Identity Pill (Google Security style) ──────────────────────────
    user_pill_html = ''
    if user_pill:
        p_email = _html_lib.escape(user_pill.get('email') or '')
        p_name = _html_lib.escape(user_pill.get('name') or p_email or 'المستخدم')
        initial = p_name[0].upper() if p_name else 'L'
        user_pill_html = f'''
        <tr>
          <td align="center" style="padding-bottom: 24px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" dir="ltr" style="margin: 0 auto; background-color: {tile_bg}; border: 1px solid {tile_border}; border-radius: 28px; padding: 4px 16px 4px 6px;">
              <tr>
                <td align="center" style="width: 26px; height: 26px; background-color: #07182c; color: #38bdf8; border-radius: 50%; font-size: 13px; font-weight: 800; line-height: 26px;">
                  {initial}
                </td>
                <td style="font-size: 13px; font-weight: 700; color: {text_secondary}; padding-left: 10px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                  {p_email}
                </td>
              </tr>
            </table>
          </td>
        </tr>'''

    # ── 3. Category / Security Badge ─────────────────────────────────────────
    badge_html = ''
    if badge:
        safe_badge = _html_lib.escape(str(badge))
        badge_html = f'''
        <tr>
          <td align="center" style="padding-bottom: 14px;">
            <span style="display: inline-block; background-color: {'#1e293b' if is_dark else '#eef2ff'}; color: {'#93c5fd' if is_dark else '#3730a3'}; border: 1px solid {'#334155' if is_dark else '#c7d2fe'}; font-size: 11px; font-weight: 800; padding: 4px 14px; border-radius: 20px; letter-spacing: 0.5px;">
              {safe_badge}
            </span>
          </td>
        </tr>'''

    # ── 4. Call-to-Action Buttons (Google Blue / Chess Orange / Outline) ──────
    cta_html = ''
    if cta_text and cta_url:
        safe_cta_text = _html_lib.escape(str(cta_text))
        safe_cta_url = _html_lib.escape(str(cta_url))

        # Default: Google Blue
        btn_bg = '#1a73e8'
        btn_color = '#ffffff'
        btn_border = '#1a73e8'
        btn_radius = '28px'

        if cta_style == 'orange':  # Chess.com style
            btn_bg = '#ea580c'
            btn_border = '#ea580c'
            btn_radius = '14px'
        elif cta_style == 'emerald':
            btn_bg = '#059669'
            btn_border = '#059669'
        elif cta_style == 'obsidian':
            btn_bg = '#07182c'
            btn_border = '#07182c'
        elif cta_style == 'outline':  # LinkedIn style
            btn_bg = 'transparent'
            btn_color = '#1a73e8' if not is_dark else '#38bdf8'
            btn_border = '#1a73e8' if not is_dark else '#38bdf8'

        cta_html = f'''
        <tr>
          <td align="center" style="padding: 28px 0 12px 0;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td align="center" style="background-color: {btn_bg}; border: 2px solid {btn_border}; border-radius: {btn_radius}; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);">
                  <a href="{safe_cta_url}" target="_blank" style="display: inline-block; padding: 14px 40px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Tahoma, sans-serif; font-size: 16px; font-weight: 800; color: {btn_color}; text-decoration: none; border-radius: {btn_radius}; text-align: center; letter-spacing: 0.3px;">
                    {safe_cta_text}
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>'''

    # ── 5. Modular Feature Tiles (X / Twitter style) ──────────────────────────
    tiles_html = ''
    if secondary_tiles and isinstance(secondary_tiles, list):
        tile_rows = []
        for t in secondary_tiles:
            t_title = _html_lib.escape(t.get('title') or '')
            t_desc = _html_lib.escape(t.get('desc') or '')
            t_link = _html_lib.escape(t.get('link_text') or '')
            t_url = _html_lib.escape(t.get('link_url') or '#')
            t_mono = _html_lib.escape(t.get('monogram') or 'AI')

            tile_rows.append(f'''
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: {tile_bg}; border: 1px solid {tile_border}; border-radius: 14px; margin-bottom: 12px; padding: 18px 20px; direction: rtl; text-align: right;">
              <tr>
                <td valign="top" style="width: 54px; padding-left: 16px;">
                  <div style="width: 48px; height: 48px; background: linear-gradient(135deg, #07182c 0%, #1e3a8a 100%); border-radius: 12px; text-align: center; line-height: 48px; font-weight: 900; font-size: 14px; color: #38bdf8; font-family: 'SFMono-Regular', Consolas, monospace; box-shadow: 0 4px 10px rgba(7, 24, 44, 0.2);">
                    {t_mono}
                  </div>
                </td>
                <td valign="top" style="text-align: right;">
                  <div style="font-size: 15px; font-weight: 800; color: {text_primary}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                    {t_title}
                  </div>
                  <div style="font-size: 13px; color: {text_secondary}; line-height: 1.6; margin-top: 6px;">
                    {t_desc}
                  </div>
                  {f'<div style="margin-top: 10px;"><a href="{t_url}" target="_blank" style="font-size: 13px; font-weight: 800; color: #2563eb; text-decoration: none;">{t_link}</a></div>' if t_link else ''}
                </td>
              </tr>
            </table>''')

        tiles_html = f'''
        <tr>
          <td style="padding-top: 22px;">
            {''.join(tile_rows)}
          </td>
        </tr>'''

    # ── 6. Secondary Note / Callout ───────────────────────────────────────────
    note_html = ''
    if secondary_note:
        note_html = f'''
        <tr>
          <td style="padding-top: 20px;">
            <div style="background-color: {'#1e293b' if is_dark else '#f8fafc'}; border: 1px solid {tile_border}; border-right: 4px solid #07182c; border-radius: 10px; padding: 14px 18px; font-size: 13px; color: {text_secondary}; line-height: 1.65;">
              {secondary_note}
            </div>
          </td>
        </tr>'''

    card_radius = '0 0 20px 20px' if hero_banner else '20px'

    return f'''<!DOCTYPE html>
<html lang="ar" dir="rtl" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="x-apple-disable-message-reformatting">
  <title>{safe_title}</title>
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <![endif]-->
  <style>
    html, body {{
      margin: 0 !important;
      padding: 0 !important;
      height: 100% !important;
      width: 100% !important;
      background-color: {body_bg};
      direction: rtl;
      text-align: right;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Arabic", Tahoma, Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    table {{ border-collapse: separate !important; }}
    a {{ color: #2563eb; text-decoration: none; }}
    @media only screen and (max-width: 620px) {{
      .email-container {{
        width: 100% !important;
        margin: auto !important;
        padding: 8px !important;
      }}
      .card-body {{
        padding: 28px 20px !important;
      }}
      .email-title {{
        font-size: 22px !important;
      }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: {body_bg}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans Arabic', Tahoma, Arial, sans-serif; direction: rtl; text-align: right;">

  <!-- Preheader text (visible in inbox preview list, hidden in body) -->
  <div style="display: none; font-size: 1px; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden; mso-hide: all;">
    {preview_snippet} &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
  </div>

  <!-- Outer canvas -->
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: {body_bg}; margin: 0; padding: 36px 0 44px 0;">
    <tr>
      <td align="center" style="padding: 0 12px;">

        <!-- Main centered container (max-width: 580px) -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" class="email-container" style="max-width: 580px; margin: 0 auto; text-align: right; direction: rtl;">

          <!-- Top Brand Bar (Google / X style when no hero banner) -->
          {'' if hero_banner else f'''
          <tr>
            <td align="center" style="padding: 0 0 24px 0;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 0 auto; text-align: center;">
                <tr>
                  <td align="center">
                    <div style="display: inline-block; background-color: #07182c; border-radius: 12px; padding: 10px 24px; color: #ffffff; font-size: 16px; font-weight: 900; letter-spacing: 2px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; box-shadow: 0 4px 12px rgba(7, 24, 44, 0.25);">
                      LANDLOOM <span style="color: #38bdf8; font-weight: 700; font-size: 14px;">AI</span>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>'''}

          <!-- Main Tech Card -->
          <tr>
            <td style="background-color: {card_bg}; border-radius: {card_radius}; border: 1px solid {card_border}; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08); overflow: hidden;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                {hero_html}
                <tr>
                  <td class="card-body" style="padding: 40px 36px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="direction: rtl; text-align: right;">

                      {user_pill_html}
                      {badge_html}

                      <!-- Main Headline (Google / Cloudflare style) -->
                      <tr>
                        <td align="center" style="padding-bottom: 20px;">
                          <h2 class="email-title" style="margin: 0; font-size: 25px; font-weight: 900; color: {text_primary}; line-height: 1.35; text-align: center; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans Arabic', Tahoma, Arial, sans-serif;">
                            {safe_title}
                          </h2>
                        </td>
                      </tr>

                      <!-- Dynamic Body Content -->
                      <tr>
                        <td align="right" style="font-size: 15px; line-height: 1.8; color: {text_secondary}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans Arabic', Tahoma, Arial, sans-serif;">
                          {content_html}
                        </td>
                      </tr>

                      <!-- Call to action button -->
                      {cta_html}

                      <!-- Feature tiles (X style) -->
                      {tiles_html}

                      <!-- Secondary Note / Alert -->
                      {note_html}

                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Modern Tech Footer (Google / Apple / X style) -->
          <tr>
            <td align="center" style="padding: 32px 16px 0 16px; font-size: 12px; color: #94a3b8; line-height: 1.7; text-align: center;">
              <div style="font-weight: 700; color: #64748b; margin-bottom: 6px;">
                منصة LandLoom AI لتوليد العروض والدراسات العقارية الاستثمارية
              </div>
              <div>
                وصلتك هذه الرسالة بصفتك مسجلاً في منصة LandLoom AI.
              </div>
              <div style="margin-top: 10px; font-size: 11px; color: #cbd5e1;">
                جميع الحقوق محفوظة للمنصة &copy; 2026
              </div>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>'''


# ─────────────────────────────────────────────────────────────────────────────
# 1. Login OTP Email (Google Security + X Style)
# ─────────────────────────────────────────────────────────────────────────────

def render_login_otp_email(recipient, otp_code, device_info=None, expiry_mins=10):
    """
    Precision Google Security & X style template for Login OTP.
    Features: User identity pill, glowing monospace code box, session metadata, Google Blue pill CTA.
    """
    dev_str = device_info or 'متصفح Chrome على نظام Windows • الرياض، المملكة العربية السعودية'

    content = f'''
    <p style="margin: 0 0 18px 0; text-align: center; font-size: 15px; color: #475569;">
      استخدم رمز التحقق التالي لإتمام تسجيل دخولك بأمان إلى مساحة عمل شركتك:
    </p>

    <!-- High-Tech Monospace OTP Code Display -->
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background: linear-gradient(180deg, #07182c 0%, #0f172a 100%); border-radius: 16px; margin: 24px 0 20px 0; text-align: center; box-shadow: 0 8px 24px rgba(7, 24, 44, 0.25); border: 1px solid #1e293b;">
      <tr>
        <td style="padding: 30px 16px;">
          <div style="font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace; font-size: 42px; font-weight: 900; letter-spacing: 14px; color: #38bdf8; text-align: center; user-select: all; -webkit-user-select: all;">
            {otp_code}
          </div>
          <div style="margin-top: 12px;">
            <span style="display: inline-block; background-color: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 20px; padding: 4px 14px; font-size: 12px; font-weight: 700; color: #38bdf8;">
              صلاحية الرمز: {expiry_mins} دقائق
            </span>
          </div>
        </td>
      </tr>
    </table>

    <!-- Session Metadata Card -->
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 18px; margin-top: 16px;">
      <tr>
        <td style="font-size: 13px; color: #475569; line-height: 1.6;">
          <strong style="color: #07182c;">بيانات جلسة الدخول:</strong> {dev_str}
        </td>
      </tr>
    </table>
    '''

    return build_base_email(
        title='رمز التحقق لتسجيل الدخول',
        content_html=content,
        user_pill={'email': recipient},
        badge='أمان الحساب',
        preheader=f'رمز التحقق لتسجيل الدخول إلى حسابك: {otp_code}',
        cta_text='تأكيد تسجيل الدخول عبر المنصة',
        cta_url='https://lab.landloom.ai',
        cta_style='primary',
        secondary_note='هذا الرمز مخصص لاستخدامك الشخصي فقط. لن يطلب منك فريق دعم LandLoom AI هذا الرمز بأي وسيلة.',
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Company Welcome & Onboarding (Cloudflare Hero + X Tiles Style)
# ─────────────────────────────────────────────────────────────────────────────

def render_company_welcome_email(recipient, company_name, activation_url, initial_points=5000):
    """
    Cloudflare Hero + X style onboarding email for new company onboarding.
    Features: Vibrant gradient hero, account parameter metrics, and modular feature tiles.
    """
    safe_company = _html_lib.escape(company_name or 'شركتك')

    content = f'''
    <p style="margin: 0 0 18px 0; font-size: 15px; color: #334155; line-height: 1.8;">
      أهلاً بك في منصة <strong>LandLoom AI</strong> المتخصصة في إعداد الدراسات التحليلية وتوليد العروض الاستثمارية العقارية المعتمدة. تم تجهيز مساحة عمل <strong>{safe_company}</strong> بالكامل وتفعيل محركات الذكاء الاصطناعي الخاصة بالسوق العقاري السعودي.
    </p>

    <!-- Company Stats Matrix -->
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 14px; padding: 18px; margin: 20px 0;">
      <tr>
        <td style="padding: 8px 12px; font-size: 13px; color: #64748b; font-weight: 600;">المنشأة:</td>
        <td style="padding: 8px 12px; font-size: 14px; color: #07182c; font-weight: 800;">{safe_company}</td>
      </tr>
      <tr>
        <td style="padding: 8px 12px; font-size: 13px; color: #64748b; font-weight: 600; border-top: 1px solid #edf2f7;">الباقة المفعلة:</td>
        <td style="padding: 8px 12px; font-size: 14px; color: #059669; font-weight: 800; border-top: 1px solid #edf2f7;">باقة الشركات المتقدمة (Pro Enterprise)</td>
      </tr>
      <tr>
        <td style="padding: 8px 12px; font-size: 13px; color: #64748b; font-weight: 600; border-top: 1px solid #edf2f7;">الرصيد الافتتاحي:</td>
        <td style="padding: 8px 12px; font-size: 14px; color: #07182c; font-weight: 800; border-top: 1px solid #edf2f7;">{initial_points:,} نقطة توليد فورية</td>
      </tr>
    </table>
    '''

    tiles = [
        {
            'title': 'تحليل الأراضي والكروكيات الجغرافية',
            'desc': 'رفع الصكوك والمخططات لتوليد اشتراطات البناء ودراسة الموقع الجغرافي وحساب الارتدادات بدقة.',
            'link_text': 'استكشاف الأداة',
            'link_url': 'https://lab.landloom.ai',
            'monogram': 'GEO',
        },
        {
            'title': 'صياغة العروض الاستثمارية التفاعلية',
            'desc': 'تصدير عروض تقديمية وملفات PDF تنفيذية مطابقة للهوية المعتمدة لشركتك خلال دقائق.',
            'link_text': 'إنشاء أول مسودة',
            'link_url': 'https://lab.landloom.ai',
            'monogram': 'PPT',
        },
    ]

    return build_base_email(
        title='تم تفعيل حسابك المؤسسي بنجاح',
        content_html=content,
        hero_banner={
            'title': 'مرحبًا بك في LandLoom AI',
            'subtitle': 'المنصة الذكية الأولى لدراسات التطوير والاستثمار العقاري في المملكة',
            'tag': 'منصة الجيل الجديد',
            'gradient': 'linear-gradient(135deg, #07182c 0%, #1e3a8a 55%, #0284c7 100%)',
        },
        user_pill={'email': recipient},
        badge='انضمام جديد',
        preheader=f'مرحبًا بك في LandLoom AI - حساب {safe_company} جاهز للعمل',
        cta_text='تعيين كلمة المرور والبدء',
        cta_url=activation_url,
        cta_style='primary',
        secondary_tiles=tiles,
        secondary_note='صلاحية رابط التفعيل 7 أيام. للاستفسار أو الدعم الفني، تواصل مع فريق الحسابات عبر المنصة.',
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Low Balance Warning & Billing Alert (Chess.com Style)
# ─────────────────────────────────────────────────────────────────────────────

def render_billing_low_balance_email(recipient, company_name, remaining_points, recharge_url):
    """
    High-contrast Chess.com style alert email for low balance.
    Features: Amber badge, large metric display box, and vibrant punchy orange CTA.
    """
    safe_company = _html_lib.escape(company_name or 'شركتك')

    content = f'''
    <p style="margin: 0 0 18px 0; font-size: 15px; color: #334155; line-height: 1.8;">
      تنبيه بخصوص استهلاك الرصيد في حساب <strong>{safe_company}</strong>. لقد أوشك رصيد نقاط التوليد المتاح لشركتك على النفاد.
    </p>

    <!-- Prominent Chess.com-style Metric Callout -->
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #fff7ed; border: 2px solid #fed7aa; border-radius: 16px; margin: 20px 0; text-align: center; padding: 24px;">
      <tr>
        <td>
          <div style="font-size: 13px; font-weight: 800; color: #c2410c; text-transform: uppercase; letter-spacing: 1px;">
            الرصيد المتبقي الحالي
          </div>
          <div style="font-size: 44px; font-weight: 900; color: #ea580c; margin: 8px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            {remaining_points:,}
          </div>
          <div style="font-size: 14px; font-weight: 700; color: #9a3412;">
            نقطة توليد فقط
          </div>
        </td>
      </tr>
    </table>

    <p style="margin: 0 0 16px 0; font-size: 14px; color: #475569; line-height: 1.7;">
      لتفادي توقف عمليات توليد العروض، والتحليلات الجغرافية، ودراسات الجدوى لفريق عملك، يرجى تقديم طلب شحن باقة جديدة عبر لوحة الإدارة.
    </p>
    '''

    return build_base_email(
        title='رصيد النقاط قارب على النفاد',
        content_html=content,
        user_pill={'email': recipient},
        badge='تنبيه استهلاك',
        preheader=f'تنبيه رصيد: متبقي {remaining_points} نقطة فقط في حساب {safe_company}',
        cta_text='شحن الرصيد الآن',
        cta_url=recharge_url,
        cta_style='orange',
        secondary_note='يتم معالجة وتفعيل طلبات التحويل البنكي وشحن الباقات آلياً عبر لوحة الإدارة.',
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. User Invitation Email (LinkedIn / X Style)
# ─────────────────────────────────────────────────────────────────────────────

def render_user_invite_email(recipient, inviter_name, company_name, role_name, invite_url):
    """
    LinkedIn / X style invitation email for new team members.
    """
    safe_inviter = _html_lib.escape(inviter_name or 'مدير الحساب')
    safe_company = _html_lib.escape(company_name or 'فريق العمل')
    safe_role = _html_lib.escape(role_name or 'عضو فريق')

    content = f'''
    <p style="margin: 0 0 18px 0; font-size: 15px; color: #334155; line-height: 1.8;">
      قام <strong>{safe_inviter}</strong> بدعوتك للانضمام إلى مساحة عمل <strong>{safe_company}</strong> على منصة <strong>LandLoom AI</strong>.
    </p>

    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 14px; padding: 18px; margin: 18px 0;">
      <tr>
        <td style="padding: 8px 12px; font-size: 13px; color: #64748b; font-weight: 600;">الجهة:</td>
        <td style="padding: 8px 12px; font-size: 14px; color: #07182c; font-weight: 800;">{safe_company}</td>
      </tr>
      <tr>
        <td style="padding: 8px 12px; font-size: 13px; color: #64748b; font-weight: 600; border-top: 1px solid #edf2f7;">الدور الوظيفي:</td>
        <td style="padding: 8px 12px; font-size: 14px; color: #1d4ed8; font-weight: 800; border-top: 1px solid #edf2f7;">{safe_role}</td>
      </tr>
    </table>

    <p style="margin: 0; font-size: 14px; color: #64748b; line-height: 1.7;">
      يمكنك الانضمام مباشرة وبدء العمل على مسودات العروض والمخططات فور قبول الدعوة وتعيين كلمة المرور الخاصة بك.
    </p>
    '''

    return build_base_email(
        title='دعوة للانضمام إلى مساحة العمل',
        content_html=content,
        user_pill={'email': recipient},
        badge='دعوة فريق',
        preheader=f'دعوة من {safe_inviter} للانضمام إلى {safe_company} على LandLoom AI',
        cta_text='قبول الدعوة وتفعيل الحساب',
        cta_url=invite_url,
        cta_style='primary',
        secondary_note='هذه الدعوة صالحة لمدة 7 أيام مخصصة لعنوان البريد الإلكتروني المدعو فقط.',
    )
