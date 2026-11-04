"""Tests for Unified Topbar Chrome: Brand Cluster, Breadcrumb Context, Points Pill, and User Chip."""
import unittest
from pathlib import Path
from tests.frontend_source import shell_text

ROOT = Path(__file__).resolve().parent.parent.parent


class TenantTopbarChromeTests(unittest.TestCase):
    def setUp(self):
        self.index_html = shell_text()
        self.topbar_css = (ROOT / 'assets' / 'css' / 'base' / '12_topbar_chrome.css').read_text(encoding='utf-8')
        self.responsive_css = (ROOT / 'assets' / 'css' / 'base' / '04_export_responsive.css').read_text(encoding='utf-8')
        self.auth_boot_js = (ROOT / 'assets' / 'js' / '02-settings-branding' / '02_auth_boot.js').read_text(encoding='utf-8')
        self.routing_js = (ROOT / 'assets' / 'js' / '02-settings-branding' / '01_routing.js').read_text(encoding='utf-8')
        self.i18n_js = (ROOT / 'assets' / 'i18n.js').read_text(encoding='utf-8')
        self.ar_dict = (ROOT / 'assets' / 'i18n' / '01_dict_ar.js').read_text(encoding='utf-8')
        self.en_dict = (ROOT / 'assets' / 'i18n' / '02_dict_en.js').read_text(encoding='utf-8')
        self.auth_users_py = (ROOT / 'app_parts' / '14_auth' / '14_auth_users.py').read_text(encoding='utf-8')

    def test_topbar_markup_elements(self):
        """Topbar markup contains breadcrumb context, points pill, and user chip elements."""
        for el_id in [
            'tenantCurrentPageContext',
            'tenantCurrentPageTitle',
            'tenantTopbarPointsPill',
            'tenantTopbarPointsVal',
            'tenantUserChip',
            'tenantUserAvatar',
            'tenantChipName',
            'tenantWorkspaceRole'
        ]:
            self.assertIn(f'id="{el_id}"', self.index_html, f"Missing #{el_id} in index.html")

    def test_user_chip_avatar_precedes_meta_in_rtl_flow(self):
        """In RTL header, the avatar appears before the text metadata in markup."""
        chip_start = self.index_html.find('id="tenantUserChip"')
        self.assertNotEqual(chip_start, -1)
        chip_end = self.index_html.find('</button>', chip_start)
        chip_snippet = self.index_html[chip_start:chip_end]
        avatar_pos = chip_snippet.find('tenant-userchip-avatar')
        meta_pos = chip_snippet.find('tenant-userchip-meta')
        caret_pos = chip_snippet.find('tenant-userchip-caret')
        self.assertTrue(avatar_pos != -1 and meta_pos != -1 and caret_pos != -1)
        self.assertLess(avatar_pos, meta_pos, "Avatar must precede metadata in RTL layout")
        self.assertLess(meta_pos, caret_pos, "Metadata must precede dropdown caret in RTL layout")

    def test_points_pill_triggers_recharge_navigation(self):
        """Clicking the points pill opens the wallet/recharge screen."""
        self.assertIn("openLandloomOpsPage('recharge')", self.index_html)

    def test_update_tenant_topbar_points_function(self):
        """JS helper updateTenantTopbarPoints formats points with 2 decimal places and updates DOM."""
        self.assertIn('function updateTenantTopbarPoints', self.auth_boot_js)
        self.assertIn('tenantTopbarPointsVal', self.auth_boot_js)
        self.assertIn('minimumFractionDigits: 2', self.auth_boot_js)

    def test_user_chip_name_does_not_duplicate_company_name(self):
        """Routing disentangles personal user title from the company name."""
        self.assertIn('tenantUser._userName', self.routing_js)
        self.assertIn('role.account_manager', self.routing_js)

    def test_api_me_returns_credit_balance(self):
        """Backend /api/auth/me returns creditBalance for topbar points hydration."""
        self.assertIn("'creditBalance': float(t.get('credit_balance')", self.auth_users_py)

    def test_topbar_css_classes_in_topbar_chrome(self):
        """CSS definitions for topbar, breadcrumb, points pill, and hover states exist."""
        self.assertIn('.tenant-topbar', self.topbar_css)
        self.assertIn('.tenant-topbar-crumb', self.topbar_css)
        self.assertIn('.tenant-topbar-points-pill', self.topbar_css)
        self.assertIn('.tenant-topbar-points-val', self.topbar_css)
        self.assertIn('.tenant-topbar-points-dot', self.topbar_css)

    def test_topbar_i18n_keys_exist_in_both_languages(self):
        """Topbar translation keys exist in both Arabic and English dictionaries."""
        keys = ['role.account_manager', 'wallet.points_balance', 'wallet.recharge_short']
        for key in keys:
            self.assertIn(f'"{key}"', self.ar_dict, f"Missing {key} in Arabic dictionary")
            self.assertIn(f'"{key}"', self.en_dict, f"Missing {key} in English dictionary")

    def test_logo_adaptive_tone_in_topbar(self):
        """Topbar logo chip respects data-logo-tone dark background for light company logos."""
        self.assertIn('.tenant-topbar-brand .tenant-brand-logo[data-logo-tone="dark"]', self.topbar_css)
        self.assertIn('background: #0a1f31', self.topbar_css)

    def test_points_cta_hover_contrast(self):
        """Hovering over points pill turns CTA turquoise with navy text for high visibility."""
        self.assertIn('.tenant-topbar-points-pill:hover .tenant-topbar-points-cta', self.topbar_css)
        self.assertIn('var(--teal-bright)', self.topbar_css)
        self.assertIn('#07182C', self.topbar_css)

    def test_usermenu_language_label_and_hydration(self):
        """User menu clearly displays current active language without confusing toggle button labels."""
        self.assertIn('id="tenantMenuLang"', self.index_html)
        self.assertIn("document.getElementById('tenantMenuLang')", self.i18n_js)

    def test_api_me_primary_admin_manager_name(self):
        """api_me fetches primary admin or account manager personal name instead of falling back to company name."""
        self.assertIn('db.get_primary_admin_name', self.auth_users_py)
        self.assertIn("'accountManagerName': primary_name", self.auth_users_py)

    def test_tenant_bell_modern_outline(self):
        """Bell notification icon is styled as a modern outline vector shape instead of solid chunky blocks."""
        self.assertIn('.tenant-bell-shape', self.responsive_css)
        self.assertIn('border: 1.6px solid currentColor', self.responsive_css)
        self.assertIn('background: transparent', self.responsive_css)


if __name__ == '__main__':
    unittest.main()
