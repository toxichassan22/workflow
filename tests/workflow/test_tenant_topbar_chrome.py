"""Tests for Unified Topbar Chrome: Brand Cluster, Breadcrumb Context, Points Pill, and User Chip."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class TenantTopbarChromeTests(unittest.TestCase):
    def setUp(self):
        self.index_html = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.topbar_css = (ROOT / 'assets' / 'css' / 'base' / '12_topbar_chrome.css').read_text(encoding='utf-8')
        self.auth_boot_js = (ROOT / 'assets' / 'js' / '02-settings-branding' / '02_auth_boot.js').read_text(encoding='utf-8')
        self.routing_js = (ROOT / 'assets' / 'js' / '02-settings-branding' / '01_routing.js').read_text(encoding='utf-8')
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


if __name__ == '__main__':
    unittest.main()
