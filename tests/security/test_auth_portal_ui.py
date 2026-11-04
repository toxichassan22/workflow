# -*- coding: utf-8 -*-
"""The login portal design: a split identity panel, one title per auth state,
and the navy primary action instead of the oversized turquoise fill."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.frontend_source import shell_text


class AuthPortalUiTests(unittest.TestCase):
    def setUp(self):
        self.shell = shell_text()
        self.css = (ROOT / 'assets' / 'css' / 'base' / '05_dashboard_viz.css').read_text(encoding='utf-8')

    def test_auth_card_is_a_split_brand_and_form_layout(self):
        """The portal is one card split into a navy identity panel and the white form."""
        auth_block = self.shell[self.shell.index('id="tenantAuthPage"'):]
        auth_block = auth_block[:auth_block.index('class="auth-body"')]
        self.assertIn('class="auth-brand"', auth_block)
        self.assertIn('class="auth-brand-rule"', auth_block)
        self.assertIn('landloom-wordmark-white.svg', auth_block)
        self.assertNotIn('/assets/landloom-logo.png', auth_block,
                         'the navy panel needs the white wordmark')
        self.assertIn('class="auth-body"', self.shell)

        card = re.search(r'\.auth-card \{(.*?)\n    \}', self.css, re.S)
        self.assertIsNotNone(card, '.auth-card rule is missing')
        self.assertIn('display: grid;', card.group(1))
        self.assertIn('grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);', card.group(1))
        self.assertNotIn('linear-gradient(90deg, #17C8E3, #07182C)', self.css,
                         'the old top gradient bar must not come back')

        brand = re.search(r'\.auth-brand \{(.*?)\n    \}', self.css, re.S)
        self.assertIsNotNone(brand)
        self.assertIn('background: #07182C;', brand.group(1))
        self.assertIn('color: #ffffff;', brand.group(1))

    def test_each_auth_state_carries_its_own_title(self):
        """The shared «تسجيل الدخول» title used to stay above the OTP form."""
        login_form = self.shell[self.shell.index('id="loginForm"'):self.shell.index('id="loginOtpForm"')]
        otp_form = self.shell[self.shell.index('id="loginOtpForm"'):]
        otp_form = otp_form[:otp_form.index('</form>')]
        self.assertIn('data-i18n="auth.sign_in"', login_form)
        self.assertIn('data-i18n="auth.otp_title"', otp_form)
        self.assertNotIn('data-i18n="auth.sign_in"', otp_form)

    def test_auth_primary_button_uses_navy_not_a_turquoise_fill(self):
        """Turquoise is a 5% accent: the primary action is navy with white text."""
        button = re.search(r'\.auth-btn \{(.*?)\n    \}', self.css, re.S)
        self.assertIsNotNone(button, '.auth-btn rule is missing')
        self.assertIn('background: #07182C;', button.group(1))
        self.assertIn('color: #ffffff;', button.group(1))
        self.assertNotIn('linear-gradient', button.group(1))

    def test_mobile_keeps_the_language_toggle_readable_on_the_navy_strip(self):
        """Below 880px the brand panel becomes a navy strip; the toggle sits on it."""
        self.assertIn('@media (max-width: 880px)', self.css)
        mobile = self.css[self.css.index('@media (max-width: 880px)'):]
        self.assertIn('grid-template-columns: 1fr;', mobile)
        toggle = re.search(r'\.auth-lang-toggle \{(.*?)\n      \}', mobile, re.S)
        self.assertIsNotNone(toggle, 'the mobile language toggle rule is missing')
        self.assertIn('color: #ffffff;', toggle.group(1))


if __name__ == '__main__':
    unittest.main()
