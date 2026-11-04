import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application_module
import auth
import db


class TestCompanySettingsUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application_module.app
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.init_db()
            existing = db.get_tenant_by_email('settings-co@example.test')
            if existing:
                cls.tenant_id = existing['id']
            else:
                cls.tenant_id = db.create_tenant(
                    'Settings Co', 'settings-co@example.test', auth.hash_password('TestPass123!'), 'settings-co'
                )
        cls.token = auth.create_token(
            cls.tenant_id,
            'settings-co@example.test',
            user_id=None,
            user_name='Settings Admin',
            user_role='company_admin',
        )
        cls.auth_headers = {'Authorization': f'Bearer {cls.token}'}

    def _read_index_html(self):
        index_path = ROOT / 'index.html'
        return index_path.read_text(encoding='utf-8')

    def _extract_settings_page_html(self):
        content = self._read_index_html()
        start = content.find('id="tenantSettingsPage"')
        self.assertNotEqual(start, -1, 'tenantSettingsPage element must exist in index.html')
        # Find closing tag of page section
        end = content.find('</section>', start)
        self.assertNotEqual(end, -1, 'tenantSettingsPage section closing tag must exist')
        return content[start:end]

    def test_settings_page_structure(self):
        """Verify segmented tabs, preview mockup, dual logo preview, and sticky bar exist."""
        page_html = self._extract_settings_page_html()

        # Tabs nav
        self.assertIn('settings-tabs-nav', page_html)
        self.assertIn('id="settingsTabProfile"', page_html)
        self.assertIn('id="settingsTabIdentity"', page_html)
        self.assertIn('id="settingsTabAssets"', page_html)
        self.assertIn('id="settingsTabFonts"', page_html)

        # 4 Tab panes
        self.assertIn('id="settingsPaneProfile"', page_html)
        self.assertIn('id="settingsPaneIdentity"', page_html)
        self.assertIn('id="settingsPaneAssets"', page_html)
        self.assertIn('id="settingsPaneFonts"', page_html)

        # Profile fields
        self.assertIn('id="settingsCompanyName"', page_html)
        self.assertIn('id="settingsCompanyNameEn"', page_html)
        self.assertIn('id="settingsTagline"', page_html)
        self.assertIn('id="settingsTaglineEn"', page_html)

        # Identity & Colors
        self.assertIn('id="settingsPrimaryColor"', page_html)
        self.assertIn('id="settingsSecondaryColor"', page_html)
        self.assertIn('id="settingsAccentColor"', page_html)
        self.assertIn('id="settingsBackgroundColor"', page_html)
        self.assertIn('id="settingsTextColor"', page_html)

        # Interactive palette mockup card
        self.assertIn('id="mockupSlide"', page_html)
        self.assertIn('id="mockupHeader"', page_html)
        self.assertIn('id="mockupBadge"', page_html)
        self.assertIn('id="mockupCard"', page_html)

        # Assets: dual logo preview (light and dark/navy)
        self.assertIn('id="settingsLogoPreview"', page_html)
        self.assertIn('id="settingsLogoPreviewDarkBox"', page_html)
        self.assertIn('id="logoFileInput"', page_html)

        # Assets: Watermark
        self.assertIn('id="settingsWatermarkPreview"', page_html)
        self.assertIn('id="settingsWatermarkUploadButton"', page_html)
        self.assertIn('id="settingsWatermarkDeleteButton"', page_html)
        self.assertIn('id="watermarkFileInput"', page_html)

        # Fonts container
        self.assertIn('id="tenantFontSelections"', page_html)

        # Sticky action bar with dirty indicator
        self.assertIn('settings-sticky-bar', page_html)
        self.assertIn('id="settingsStickyDot"', page_html)
        self.assertIn('id="settingsSaveStatus"', page_html)
        self.assertIn('saveTenantSettings()', page_html)

    def test_settings_page_contains_no_emojis_or_icon_glyphs(self):
        """Strict adherence to zero emojis and zero icon glyphs."""
        page_html = self._extract_settings_page_html()
        emoji_pattern = re.compile(
            r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\ufe00-\ufe0f]'
        )
        emojis_found = emoji_pattern.findall(page_html)
        self.assertEqual(emojis_found, [], f"Settings page contains forbidden emoji: {emojis_found}")

        forbidden_arrows = ['↑', '↓', '→', '←', '▶', '◀', '▲', '▼']
        for arrow in forbidden_arrows:
            self.assertNotIn(arrow, page_html, f"Settings page contains forbidden arrow glyph: {arrow}")

    def test_settings_page_contains_no_how_to_instructions(self):
        """Owner rule: screens state what something is, never how to operate it."""
        page_html = self._extract_settings_page_html()
        forbidden_phrases = [
            'اضغط',
            'راجع أولاً',
            'راجع اولا',
            'اختر ثم',
            'اختياري: ارفع',
            'يرجى الضغط',
            'انقر هنا'
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, page_html, f"Settings page contains instructional how-to copy: {phrase}")

    def test_settings_css_registered_and_clean(self):
        """CSS file exists, is in FRONTEND_CSS_ORDER, and carries no emojis."""
        css_path = ROOT / 'assets' / 'css' / 'base' / '14_company_settings.css'
        self.assertTrue(css_path.is_file(), '14_company_settings.css must exist')

        css_content = css_path.read_text(encoding='utf-8')
        self.assertIn('.settings-tabs-nav', css_content)
        self.assertIn('.settings-tab-btn', css_content)
        self.assertIn('.settings-tab-pane', css_content)
        self.assertIn('.settings-palette-preview', css_content)
        self.assertIn('.settings-slide-mockup', css_content)
        self.assertIn('.settings-logo-preview-box', css_content)
        self.assertIn('.settings-sticky-bar', css_content)

        # Brand palette colors should be respected
        self.assertIn('#07182C', css_content)
        self.assertIn('#17C8E3', css_content)

        # Check bundled list
        bundles_file = ROOT / 'app_parts' / '22_rules_pages' / '22f_frontend_bundles.py'
        bundles_code = bundles_file.read_text(encoding='utf-8')
        self.assertIn("'base/14_company_settings.css'", bundles_code)

    def test_branding_api_get_and_update(self):
        """API endpoints GET and PUT /api/branding work cleanly."""
        # GET branding
        res = self.client.get('/api/branding', headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('branding', data)

        # PUT branding
        payload = {
            'company_name_en': 'Settings Co Global',
            'primary_color': '#07182C',
            'secondary_color': '#254B66',
            'accent_color': '#17C8E3',
            'tagline': 'هوية معتمدة',
            'tagline_en': 'Verified Identity'
        }
        update_res = self.client.put('/api/branding', json=payload, headers=self.auth_headers)
        self.assertEqual(update_res.status_code, 200)
        update_data = update_res.get_json()
        self.assertTrue(update_data.get('success'))
        branding = update_data.get('branding', {})
        self.assertEqual(branding.get('primary_color'), '#07182C')
        self.assertEqual(branding.get('secondary_color'), '#254B66')
        self.assertEqual(branding.get('accent_color'), '#17C8E3')
        self.assertEqual(branding.get('tagline'), 'هوية معتمدة')
        self.assertEqual(branding.get('tagline_en'), 'Verified Identity')


if __name__ == '__main__':
    unittest.main()
