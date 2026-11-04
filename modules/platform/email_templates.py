"""Email templates for LandLoom AI — one restrained brand shell.

The layout follows the product surfaces: a white card on a light canvas, the
brand emblem in the header and the wordmark in the footer, centred headlines,
one navy action, and turquoise only as a thin accent. No gradients, no
decorative shapes, no pill badges, no emoji or icon glyphs.

Every layout is table-based for Gmail/Outlook/Apple Mail consistency, and the
brand images travel inline (CID) so they render even when a client blocks
remote images.
"""

import html as _html_lib

BRAND_NAVY = '#07182c'
BRAND_TEAL = '#17c8e3'
BRAND_TEAL_DEEP = '#0a829b'

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans Arabic', Tahoma, Arial, sans-serif"
MONO_STACK = "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"


def brand_assets():
    """CID references for the platform emblem and wordmark. The sender attaches
    the PNGs as inline related parts, so the brand renders without any remote
    fetch — Gmail's image proxy and remote-image-blocked clients still show it."""
    return {
        'emblem_url': 'cid:landloom-emblem',
        'logo_url': 'cid:landloom-logo',
        'logo_url_light': 'cid:landloom-logo-white',
    }


def _escape(value):
    return _html_lib.escape(str(value or ''))


def _stats_rows(rows):
    """Label/value rows for the info panels (company details, invite role)."""
    html = []
    for index, row in enumerate(rows):
        border = 'border-bottom:1px solid #EDF2F7;' if index < len(rows) - 1 else ''
        color = row.get('color') or BRAND_NAVY
        html.append(
            '<tr>'
            f'<td style="padding:11px 0;font-size:12.5px;color:#64748B;{border}">'
            f'{_escape(row.get("label"))}</td>'
            f'<td style="padding:11px 0;font-size:13.5px;color:{color};font-weight:700;text-align:left;{border}">'
            f'{_escape(row.get("value"))}</td>'
            '</tr>'
        )
    return ''.join(html)


def build_base_email(
    title,
    content_html,
    subtitle=None,
    preheader=None,
    cta_text=None,
    cta_url=None,
    tiles=None,
    tiles_title=None,
    note=None,
    brand=None,
):
    """The single brand shell every email leaves in."""
    brand = brand or {}
    emblem_url = _escape(brand.get('emblem_url') or '')
    logo_url = _escape(brand.get('logo_url') or '')
    safe_title = _escape(title or '')
    preview_snippet = _escape(preheader or title or '')

    emblem_html = (
        f'<img src="{emblem_url}" alt="LandLoom" height="64" '
        'style="display:block;height:64px;width:auto;margin:0 auto;">'
        if emblem_url else ''
    )
    footer_logo_html = (
        f'<img src="{logo_url}" alt="LandLoom" height="18" '
        'style="display:block;height:18px;width:auto;margin:0 auto 10px auto;opacity:.55;">'
        if logo_url else ''
    )

    subtitle_html = (
        f'<tr><td align="center" style="padding:0 0 24px 0;font-size:14px;color:#64748B;line-height:1.8;">'
        f'{_escape(subtitle)}</td></tr>'
        if subtitle else
        '<tr><td style="height:20px;line-height:20px;font-size:0;">&nbsp;</td></tr>'
    )

    cta_html = ''
    if cta_text and cta_url:
        cta_html = f'''
        <tr>
          <td align="center" style="padding:26px 0 0 0;">
            <a href="{_escape(cta_url)}" target="_blank" style="display:inline-block;background-color:{BRAND_NAVY};color:#ffffff;font-size:14px;font-weight:700;text-decoration:none;padding:13px 34px;border-radius:10px;">{_escape(cta_text)}</a>
          </td>
        </tr>'''

    tiles_html = ''
    if tiles:
        rows = []
        if tiles_title:
            rows.append(
                '<tr><td style="padding:30px 0 12px 0;border-top:1px solid #EDF2F7;'
                'font-size:12px;font-weight:800;color:#94A3B8;letter-spacing:.4px;">'
                f'{_escape(tiles_title)}</td></tr>'
            )
        for index, tile in enumerate(tiles):
            first = index == 0 and not tiles_title
            border = '' if first else 'border-top:1px solid #EDF2F7;'
            padding = '2px' if first else '14px'
            rows.append(
                f'<tr><td style="padding:{padding} 0 0 0;{border}">'
                f'<div style="font-size:13.5px;font-weight:800;color:{BRAND_NAVY};padding:{"0" if first else "6px"} 0 5px 0;">'
                f'{_escape(tile.get("title"))}</div>'
                f'<div style="font-size:12.5px;color:#64748B;line-height:1.8;">{_escape(tile.get("desc"))}</div>'
                + (
                    f'<div style="padding:7px 0 0 0;font-size:12.5px;font-weight:700;">'
                    f'<a href="{_escape(tile.get("link_url"))}" target="_blank" style="color:{BRAND_TEAL_DEEP};text-decoration:none;">'
                    f'{_escape(tile.get("link_text"))}</a></div>'
                    if tile.get('link_text') else ''
                )
                + '</td></tr>'
            )
        tiles_html = ''.join(rows)

    note_html = (
        f'<tr><td style="padding:24px 0 0 0;">'
        f'<div style="padding:13px 16px;background-color:#F8FAFC;border:1px solid #EDF2F7;border-radius:10px;'
        f'font-size:12.5px;color:#64748B;line-height:1.8;text-align:right;">{note}</div></td></tr>'
        if note else ''
    )

    return f'''<!DOCTYPE html>
<html lang="ar" dir="rtl" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="x-apple-disable-message-reformatting">
  <title>{safe_title}</title>
  <!--[if mso]>
  <noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#F5F7FA;direction:rtl;text-align:right;font-family:{FONT_STACK};">
  <div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">
    {preview_snippet} &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
  </div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:#F5F7FA;">
    <tr>
      <td align="center" style="padding:36px 12px 40px 12px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;margin:0 auto;background-color:#ffffff;border:1px solid #E4E9F0;border-radius:18px;overflow:hidden;direction:rtl;">
          <tr><td style="height:3px;background-color:{BRAND_TEAL};line-height:3px;font-size:0;">&nbsp;</td></tr>
          <tr>
            <td align="center" style="padding:30px 32px 22px 32px;">{emblem_html}</td>
          </tr>
          <tr>
            <td style="padding:0 40px 30px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="direction:rtl;">
                <tr>
                  <td align="center" style="padding:0 0 10px 0;font-size:23px;font-weight:800;color:{BRAND_NAVY};line-height:1.45;">{safe_title}</td>
                </tr>
                {subtitle_html}
                {content_html}
                {cta_html}
                {tiles_html}
                {note_html}
              </table>
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:20px 32px 26px 32px;border-top:1px solid #EDF2F7;background-color:#FBFCFD;">
              {footer_logo_html}
              <div style="font-size:11.5px;color:#94A3B8;line-height:1.9;">منصة توليد العروض والدراسات العقارية الاستثمارية<br>وصلتك هذه الرسالة بصفتك مسجلاً في منصة LandLoom AI.</div>
              <div style="padding:8px 0 0 0;font-size:11px;color:#B6C2D1;">جميع الحقوق محفوظة للمنصة &copy; 2026</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def render_login_otp_email(recipient, otp_code, device_info=None, expiry_mins=10,
                           login_url=None, brand=None):
    """Login OTP: a calm code panel, the session line, one navy action."""
    dev_str = _escape(
        device_info or 'متصفح Chrome على نظام Windows • الرياض، المملكة العربية السعودية')
    content = f'''
        <tr>
          <td align="center" style="padding:0 0 26px 0;font-size:14px;color:#64748B;line-height:1.8;">
            أدخل الرمز التالي لإكمال الدخول إلى مساحة عمل شركتك.
          </td>
        </tr>
        <tr>
          <td style="padding:26px 18px 18px 18px;background-color:#F0FBFD;border:1px solid #B9EEF7;border-radius:14px;text-align:center;">
            <div style="font-family:{MONO_STACK};font-size:36px;font-weight:800;letter-spacing:12px;color:{BRAND_NAVY};direction:ltr;">{_escape(otp_code)}</div>
            <div style="padding:12px 0 0 0;font-size:12px;color:{BRAND_TEAL_DEEP};">صالح لمدة {int(expiry_mins)} دقائق</div>
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:18px 0 0 0;font-size:12px;color:#94A3B8;line-height:1.8;">
            بيانات جلسة الدخول: {dev_str}
          </td>
        </tr>'''

    return build_base_email(
        title='رمز التحقق لتسجيل الدخول',
        content_html=content,
        preheader=f'رمز التحقق لتسجيل الدخول إلى حسابك: {otp_code}',
        cta_text='تأكيد تسجيل الدخول',
        cta_url=login_url,
        note='هذا الرمز مخصص لاستخدامك الشخصي فقط. لن يطلب منك فريق دعم LandLoom AI هذا الرمز بأي وسيلة.',
        brand=brand,
    )


def render_company_welcome_email(recipient, company_name, activation_url,
                                 account_name=None, stats=None, brand=None):
    """New company onboarding: a personal greeting, the account matrix, and the
    workspace tools as quiet labelled rows."""
    company = company_name or 'شركتك'
    rows = [{'label': 'المنشأة', 'value': company, 'color': BRAND_NAVY}]
    if account_name:
        rows.append({'label': 'مدير الحساب', 'value': account_name, 'color': BRAND_NAVY})
    for extra in stats or []:
        if extra and extra.get('value') not in (None, ''):
            rows.append(extra)

    content = f'''
        <tr>
          <td style="padding:0 0 22px 0;font-size:14px;color:#475569;line-height:1.9;text-align:right;">
            تم تجهيز مساحة عمل <strong style="color:{BRAND_NAVY};">{_escape(company)}</strong> وتفعيل محركات الذكاء الاصطناعي الخاصة بالسوق العقاري السعودي، لتبدأ بإعداد الدراسات التحليلية وتوليد العروض الاستثمارية المعتمدة.
          </td>
        </tr>
        <tr>
          <td style="padding:2px 18px;background-color:#F8FAFC;border:1px solid #EDF2F7;border-radius:12px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="direction:rtl;">
              {_stats_rows(rows)}
            </table>
          </td>
        </tr>'''

    tiles = [
        {
            'title': 'تحليل الأراضي والكروكيات',
            'desc': 'رفع الصكوك والمخططات لتوليد اشتراطات البناء ودراسة الموقع الجغرافي وحساب الارتدادات.',
            'link_text': 'استكشاف الأداة',
            'link_url': 'https://lab.landloom.ai',
        },
        {
            'title': 'العروض الاستثمارية والتصدير',
            'desc': 'عروض تقديمية وملفات PDF تنفيذية مطابقة لهوية شركتك، جاهزة خلال دقائق.',
            'link_text': 'إنشاء أول مسودة',
            'link_url': 'https://lab.landloom.ai',
        },
    ]

    greeting = f'مرحبًا {account_name}،' if account_name else 'مرحبًا بك في LandLoom AI'
    return build_base_email(
        title=greeting,
        subtitle='تم تفعيل حسابك المؤسسي في LandLoom AI بنجاح.',
        content_html=content,
        preheader=f'حساب {_escape(company)} جاهز للعمل على LandLoom AI',
        cta_text='تعيين كلمة المرور والبدء',
        cta_url=activation_url,
        tiles=tiles,
        tiles_title='أدوات مساحة العمل',
        note='صلاحية رابط التفعيل 7 أيام. للاستفسار أو الدعم الفني، تواصل مع فريق الحسابات عبر المنصة.',
        brand=brand,
    )


def render_billing_low_balance_email(recipient, company_name, remaining_points,
                                     recharge_url, brand=None):
    """Low-balance notice: the figure on a neutral panel, no alarm colours."""
    content = f'''
        <tr>
          <td style="padding:0 0 20px 0;font-size:14px;color:#475569;line-height:1.9;text-align:right;">
            رصيد نقاط التوليد في حساب <strong style="color:{BRAND_NAVY};">{_escape(company_name or 'شركتك')}</strong> قارب على النفاد.
          </td>
        </tr>
        <tr>
          <td style="padding:24px 16px;background-color:#F8FAFC;border:1px solid #EDF2F7;border-radius:14px;text-align:center;">
            <div style="font-size:12px;font-weight:700;color:#64748B;">الرصيد المتبقي</div>
            <div style="padding:8px 0 4px 0;font-size:40px;font-weight:800;color:{BRAND_NAVY};">{remaining_points:,}</div>
            <div style="font-size:13px;color:#64748B;">نقطة توليد</div>
          </td>
        </tr>'''

    return build_base_email(
        title='رصيد النقاط قارب على النفاد',
        content_html=content,
        preheader=f'متبقي {remaining_points} نقطة فقط في حساب {company_name}',
        cta_text='شحن الرصيد',
        cta_url=recharge_url,
        note='يتم معالجة وتفعيل طلبات التحويل البنكي وشحن الباقات عبر لوحة الإدارة.',
        brand=brand,
    )


def render_user_invite_email(recipient, inviter_name, company_name, role_name,
                             invite_url, brand=None):
    """Team invitation: who invited whom, the role, one action."""
    rows = [
        {'label': 'الجهة', 'value': company_name or 'فريق العمل', 'color': BRAND_NAVY},
        {'label': 'الدور الوظيفي', 'value': role_name or 'عضو فريق', 'color': BRAND_TEAL_DEEP},
    ]
    content = f'''
        <tr>
          <td style="padding:0 0 20px 0;font-size:14px;color:#475569;line-height:1.9;text-align:right;">
            قام <strong style="color:{BRAND_NAVY};">{_escape(inviter_name or 'مدير الحساب')}</strong> بدعوتك للانضمام إلى مساحة عمل <strong style="color:{BRAND_NAVY};">{_escape(company_name or 'فريق العمل')}</strong> على منصة LandLoom AI.
          </td>
        </tr>
        <tr>
          <td style="padding:2px 18px;background-color:#F8FAFC;border:1px solid #EDF2F7;border-radius:12px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="direction:rtl;">
              {_stats_rows(rows)}
            </table>
          </td>
        </tr>'''

    return build_base_email(
        title='دعوة للانضمام إلى مساحة العمل',
        content_html=content,
        preheader=f'دعوة من {_escape(inviter_name or "مدير الحساب")} للانضمام إلى {_escape(company_name or "فريق العمل")}',
        cta_text='قبول الدعوة وتفعيل الحساب',
        cta_url=invite_url,
        note='هذه الدعوة صالحة لمدة 7 أيام مخصصة لعنوان البريد الإلكتروني المدعو فقط.',
        brand=brand,
    )


def render_user_welcome_email(recipient, user_name, company_name, login_url, brand=None):
    """Directly-added employee: the account exists, the password arrives from
    the admin — never inside the email itself."""
    company = company_name or 'الشركة'
    rows = [
        {'label': 'البريد الإلكتروني', 'value': recipient, 'color': BRAND_NAVY},
        {'label': 'كلمة المرور', 'value': 'تصلك من مدير حسابك', 'color': BRAND_NAVY},
    ]
    content = f'''
        <tr>
          <td style="padding:0 0 20px 0;font-size:14px;color:#475569;line-height:1.9;text-align:right;">
            تم إنشاء حسابك في <strong style="color:{BRAND_NAVY};">{_escape(company)}</strong> على منصة LandLoom AI.
          </td>
        </tr>
        <tr>
          <td style="padding:2px 18px;background-color:#F8FAFC;border:1px solid #EDF2F7;border-radius:12px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="direction:rtl;">
              {_stats_rows(rows)}
            </table>
          </td>
        </tr>'''

    greeting = f'مرحبًا {user_name}،' if user_name else 'مرحبًا بك'
    return build_base_email(
        title=greeting,
        subtitle=f'تم إنشاء حسابك في {company}',
        content_html=content,
        preheader=f'حسابك في {_escape(company)} على منصة LandLoom AI جاهز',
        cta_text='تسجيل الدخول',
        cta_url=login_url,
        brand=brand,
    )


def render_notification_email(recipient, title, body, brand=None):
    """Generic branded shell for outbox rows that carry only plain text."""
    paragraphs = ''.join(
        f'<tr><td style="padding:0 0 12px 0;font-size:14px;color:#475569;line-height:1.9;text-align:right;">'
        f'{_escape(line)}</td></tr>'
        for line in (body or '').split('\n') if line.strip()
    ) or '<tr><td style="font-size:14px;color:#475569;">&nbsp;</td></tr>'

    return build_base_email(
        title=title or 'إشعار',
        content_html=paragraphs,
        preheader=title,
        brand=brand,
    )
