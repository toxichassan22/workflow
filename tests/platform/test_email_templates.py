# -*- coding: utf-8 -*-
"""The email shell: one restrained design for every platform email.

The card is white on a light canvas, the emblem sits in the header and the
wordmark in the footer, headlines are centred, the only action is navy, and
turquoise stays a thin accent. No gradients, decorative shapes, pill badges,
emoji or icon glyphs may come back.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import email_templates as et

BRAND = et.brand_assets()


class EmailTemplateTests(unittest.TestCase):
    def _render_all(self):
        return {
            'otp': et.render_login_otp_email(
                'sara@example.test', '482915', device_info='Chrome على Windows',
                login_url='https://lab.landloom.ai/app', brand=BRAND),
            'welcome': et.render_company_welcome_email(
                'sara@example.test', 'بوابة الرؤية للتطوير', 'https://lab.landloom.ai/invite/x',
                account_name='سارة العتيبي',
                stats=[{'label': 'الفترة التجريبية', 'value': '14 يوم',
                        'color': et.BRAND_TEAL_DEEP}], brand=BRAND),
            'invite': et.render_user_invite_email(
                'khaled@example.test', 'سارة العتيبي', 'بوابة الرؤية', 'محرر',
                'https://lab.landloom.ai/invite/x', brand=BRAND),
            'user': et.render_user_welcome_email(
                'khaled@example.test', 'خالد', 'بوابة الرؤية',
                'https://lab.landloom.ai/app', brand=BRAND),
            'note': et.render_notification_email(
                'sara@example.test', 'تحديث', 'السطر الأول\nالسطر الثاني', brand=BRAND),
        }

    def test_every_email_uses_the_brand_shell(self):
        for name, html in self._render_all().items():
            self.assertIn('cid:landloom-emblem', html, name)
            self.assertIn('cid:landloom-logo', html, name)
            self.assertIn('height="64"', html, name)
            self.assertIn('background-color:#F5F7FA', html, name)
            self.assertIn('max-width:560px', html, name)
            self.assertIn('border-top:1px solid #EDF2F7', html, name)

    def test_headlines_are_centred_and_the_action_is_navy(self):
        welcome = self._render_all()['welcome']
        self.assertIn('مرحبًا سارة العتيبي،', welcome)
        self.assertIn('تم تفعيل حسابك المؤسسي في LandLoom AI بنجاح.', welcome)
        self.assertIn('align="center"', welcome)
        self.assertIn('background-color:#07182c', welcome)
        self.assertIn('أدوات مساحة العمل', welcome)
        self.assertNotIn('linear-gradient', welcome)

    def test_no_decorative_or_alarm_elements(self):
        pictographs = re.compile(
            '[\u2190-\u21ff\u2300-\u23ff\u25a0-\u27bf\u2b00-\u2bff\ufe0f'
            '\U0001f000-\U0001faff]')
        for name, html in self._render_all().items():
            self.assertEqual(sorted(set(pictographs.findall(html))), [], name)
            self.assertNotIn('<svg', html, name)
            self.assertNotIn('linear-gradient', html, name)
            self.assertNotIn('border-radius: 50%', html, name)
            self.assertNotIn('#ea580c', html, name)
            self.assertNotIn('#059669', html, name)

    def test_otp_carries_the_code_and_the_expiry(self):
        otp = self._render_all()['otp']
        self.assertIn('482915', otp)
        self.assertIn('صالح لمدة 10 دقائق', otp)
        self.assertIn('تأكيد تسجيل الدخول', otp)

    def test_inline_logo_assets_exist(self):
        assets = ROOT / 'assets'
        for name in ('landloom-emblem.png', 'landloom-logo.png', 'landloom-logo-white.png'):
            self.assertTrue((assets / name).is_file(), name)

    def test_emblem_asset_is_square(self):
        """The email header renders the emblem at equal width and height; a wide
        export (486x376 was shipped once) shows as a stretched pill."""
        try:
            from PIL import Image
        except Exception:  # pragma: no cover - Pillow ships with the app venv
            self.skipTest('Pillow is not available')
        image = Image.open(ROOT / 'assets' / 'landloom-emblem.png').convert('RGBA')
        bbox = image.split()[-1].getbbox()
        self.assertIsNotNone(bbox)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        self.assertLessEqual(
            abs(width - height) / max(width, height), 0.02,
            'the emblem mark must be square (measured %dx%d)' % (width, height))


if __name__ == '__main__':
    unittest.main()
