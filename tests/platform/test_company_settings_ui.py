import os
import re
import sys
import unittest
from pathlib import Path
from tests.frontend_source import shell_text

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
        return shell_text()

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

    def test_settings_tabs_wrap_instead_of_scrolling(self):
        """The tabs bar showed an unnecessary vertical scrollbar: overflow-x:auto makes
        overflow-y compute to auto, and the active tab's -2px underline margin overflowed
        by 2px. The tabs wrap instead, so the bar is never a scroll container."""
        css_path = ROOT / 'assets' / 'css' / 'base' / '14_company_settings.css'
        css_content = css_path.read_text(encoding='utf-8')
        nav_block = re.search(r'\.settings-tabs-nav\s*\{([^}]*)\}', css_content)
        self.assertIsNotNone(nav_block, '.settings-tabs-nav rule is missing')
        self.assertNotIn('overflow-x: auto', nav_block.group(1),
                         'the tabs bar must not be a scroll container')
        self.assertIn('flex-wrap: wrap', nav_block.group(1))

    def test_settings_profile_uses_a_live_company_card(self):
        """The profile tab stacked four full-width fields and left the page mostly empty.
        The fields now pair in two columns beside a live company card that mirrors them,
        the container uses the page width, and the save bar anchors the bottom."""
        page_html = self._extract_settings_page_html()
        self.assertIn('class="settings-profile-layout"', page_html)
        self.assertNotIn('class="tenant-field full"', page_html)
        for element_id in ('settingsCompanyPreviewNameAr', 'settingsCompanyPreviewNameEn',
                           'settingsCompanyPreviewTagAr', 'settingsCompanyPreviewTagEn',
                           'settingsCompanyPreviewLogo'):
            self.assertIn('id="%s"' % element_id, page_html,
                          'the live company card is missing %s' % element_id)

        css = (ROOT / 'assets' / 'css' / 'base' / '14_company_settings.css').read_text(encoding='utf-8')
        self.assertIn('.settings-profile-layout {', css)
        self.assertIn('grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);', css)
        self.assertIn('max-width: 1500px;', css)
        self.assertIn('min-height: calc(var(--ui-viewport, 100vh) - 120px);', css)
        self.assertRegex(css, r'\.settings-sticky-bar \{[^}]*margin-top: auto;')

        js = (ROOT / 'assets' / 'js' / '02-settings-branding' / '02_auth_boot.js').read_text(encoding='utf-8')
        self.assertIn('function renderSettingsCompanyPreview()', js)
        self.assertGreaterEqual(
            js.count('renderSettingsCompanyPreview()'), 5,
            'the card must render on open, on language change, and while typing')

    def test_settings_page_strings_are_i18n_bound(self):
        """The redesigned settings page shipped hardcoded Arabic, so the English UI kept
        showing Arabic. Every label, placeholder and status must resolve through the
        settings.* dictionary keys."""
        page_html = self._extract_settings_page_html()
        for key in (
                'settings.title', 'settings.subtitle',
                'settings.tab_profile', 'settings.tab_identity',
                'settings.tab_assets', 'settings.tab_fonts',
                'settings.profile_title', 'settings.profile_desc',
                'settings.name_ar_field', 'settings.tagline_ar_field',
                'settings.colors_title', 'settings.colors_desc',
                'settings.color_primary', 'settings.color_secondary',
                'settings.color_accent', 'settings.color_background',
                'settings.color_text', 'settings.preview_title',
                'settings.mockup_project', 'settings.mockup_badge',
                'settings.mockup_metric', 'settings.mockup_body',
                'settings.logo_title', 'settings.logo_light', 'settings.logo_dark',
                'settings.logo_upload', 'settings.watermark_title',
                'settings.watermark_upload', 'settings.watermark_delete',
                'settings.fonts_title', 'settings.fonts_desc',
                'settings.restore', 'settings.save'):
            self.assertIn('data-i18n="%s"' % key, page_html,
                          '%s is not bound in the settings page' % key)
        self.assertIn('data-i18n-ph="settings.name_ar_placeholder"', page_html)
        self.assertIn('data-i18n-ph="settings.tagline_ar_placeholder"', page_html)

        js_path = ROOT / 'assets' / 'js' / '02-settings-branding' / '02_auth_boot.js'
        js_content = js_path.read_text(encoding='utf-8')
        for key in ('settings.saved', 'settings.unsaved',
                    'settings.logo_placeholder', 'settings.logo_dark_placeholder'):
            self.assertIn("WFT('%s'" % key, js_content,
                          '%s must render through WFT in the settings script' % key)
        self.assertIn("addEventListener('wf:lang'", js_content)

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
