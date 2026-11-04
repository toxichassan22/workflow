"""Tests for the tenant wallet, operations, package catalog, and financial ledger UI."""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as application_module
import auth
import db


class TenantWalletRechargeUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'test-wallet.db')

        cls.app = application_module.app
        cls.FRONTEND_JS_ORDER = application_module.FRONTEND_JS_ORDER
        cls.app.config.update(TESTING=True)

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant(
                'Wallet Test Co', 'wallet@test.com', 'hash123', 'wallet-test'
            )
            db.update_tenant(cls.tenant_id, is_active=1)

        cls.token = auth.create_token(
            cls.tenant_id,
            'wallet@test.com',
        )

        cls.index_html = (ROOT / 'index.html').read_text(encoding='utf-8')
        cls.wallet_js = (ROOT / 'assets' / 'js' / '18-landloom-ops' / '04_wallet_ledger.js').read_text(encoding='utf-8')
        cls.slider_css = (ROOT / 'assets' / 'css' / 'base' / '07_package_slider.css').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_wallet_dom_elements_exist_in_shell(self):
        """Shell must include the complete structure for Tab 2: Recharge & Wallet."""
        self.assertIn('id="llTabPane_recharge"', self.index_html)
        self.assertIn('id="llWalletHero"', self.index_html)
        self.assertIn('id="llWalletBalance"', self.index_html)
        self.assertIn('id="llWalletPackageName"', self.index_html)
        self.assertIn('id="llWalletMeta"', self.index_html)
        self.assertIn('id="llWalletReserved"', self.index_html)
        self.assertIn('id="llWalletExpired"', self.index_html)
        self.assertIn('id="llWalletConsumed"', self.index_html)
        self.assertIn('id="llWalletIban"', self.index_html)
        self.assertIn('id="llWalletStatsStrip"', self.index_html)
        self.assertIn('id="llWalletStatTotal"', self.index_html)
        self.assertIn('id="llWalletStatPending"', self.index_html)
        self.assertIn('id="llWalletStatApproved"', self.index_html)
        self.assertIn('id="llWalletStatRejected"', self.index_html)
        self.assertIn('id="llWalletCatalog"', self.index_html)
        self.assertIn('id="llWalletIbanMain"', self.index_html)
        self.assertIn('id="llRechargeStatusFilter"', self.index_html)
        self.assertIn('id="llRechargeList"', self.index_html)
        self.assertIn('id="llLedgerTable"', self.index_html)
        self.assertIn('id="llLedgerBody"', self.index_html)

        # Hero card must NOT contain the IBAN copy box (role separation)
        hero_match = re.search(r'id="llWalletHero"[\s\S]*?id="llWalletStatsStrip"', self.index_html)
        self.assertIsNotNone(hero_match)
        self.assertNotIn('tenant-wallet-iban-box', hero_match.group(0))

        # Ops tabs must be hidden so they don't pollute the top of the wallet page
        self.assertIn('id="landloomOpsTabs"', self.index_html)
        self.assertIn('style="display:none"', self.index_html)

    def test_refresh_buttons_use_workspace_icons_and_no_bare_refresh_text(self):
        """Refresh buttons in the wallet pane must use data-ws-icon and carry no bare text."""
        # Find llTabPane_recharge block
        pane_match = re.search(r'<div id="llTabPane_recharge"[^>]*>([\s\S]*?)<!-- Tab 3:', self.index_html)
        self.assertIsNotNone(pane_match)
        pane_html = pane_match.group(1)

        # Must have wallet-refresh-btn with refresh data-ws-icon
        self.assertIn('class="btn small ghost wallet-refresh-btn"', pane_html)
        self.assertIn('data-ws-icon="refresh"', pane_html)

        # Must NOT have button with literal Arabic refresh text
        self.assertNotIn('>تحديث</button>', pane_html)

    def test_wallet_js_bundle_and_functions(self):
        """04_wallet_ledger.js must be in FRONTEND_JS_ORDER and expose key functions."""
        self.assertIn('18-landloom-ops/04_wallet_ledger.js', self.FRONTEND_JS_ORDER)
        for fn in (
            'llCopyIban',
            'llFormatPoints',
            'setWalletCategory',
            'llOnRechargeFilterChange',
            'llUpdateWalletStats',
            'llRenderWalletCatalog',
            'llRefreshWallet',
        ):
            self.assertIn(f'function {fn}', self.wallet_js)

    def test_wallet_css_styles_defined(self):
        """07_package_slider.css must define required styling classes for wallet."""
        for selector in (
            '.tenant-wallet-wrap',
            '.tenant-wallet-hero',
            '.tenant-wallet-stats-strip',
            '.tenant-wallet-stat-chip',
            '.tenant-wallet-packages-grid',
            '.tenant-wallet-bank-card',
            '.tenant-wallet-type-badge',
            '.wallet-refresh-btn',
        ):
            self.assertIn(selector, self.slider_css)

    def test_wallet_i18n_keys_registered(self):
        """All wallet i18n keys must be present in both Arabic and English dictionaries."""
        dict_ar = (ROOT / 'assets' / 'i18n' / '01_dict_ar.js').read_text(encoding='utf-8')
        dict_en = (ROOT / 'assets' / 'i18n' / '02_dict_en.js').read_text(encoding='utf-8')

        required_keys = (
            'wallet.kicker',
            'wallet.title',
            'wallet.balance_available',
            'wallet.reserved',
            'wallet.expired',
            'wallet.consumed',
            'wallet.copy_iban',
            'wallet.iban_copied',
            'wallet.stat_total',
            'wallet.stat_pending',
            'wallet.stat_approved',
            'wallet.stat_rejected',
            'wallet.packages_title',
            'wallet.bank_title',
            'wallet.bank_name',
            'wallet.bank_note',
            'wallet.requests_title',
            'wallet.cat_all',
            'wallet.cat_pending',
            'wallet.cat_approved',
            'wallet.cat_rejected',
            'wallet.ledger_title',
            'wallet.ledger_sub',
            'wallet.col_date',
            'wallet.col_type',
            'wallet.col_amount',
            'wallet.col_package',
            'wallet.col_status',
            'wallet.col_invoice',
            'wallet.sar_unit',
            'wallet.points_unit',
        )

        for k in required_keys:
            self.assertIn(f'"{k}":', dict_ar, f"Missing {k} in 01_dict_ar.js")
            self.assertIn(f'"{k}":', dict_en, f"Missing {k} in 02_dict_en.js")

    def test_billing_ledger_endpoint(self):
        """GET /api/billing/ledger returns balance, multiplier, points, and entries."""
        with self.app.test_client() as client:
            res = client.get(
                '/api/billing/ledger',
                headers={'Authorization': f'Bearer {self.token}'},
            )
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get('success'))
            self.assertIn('balance_sar', data)
            self.assertIn('multiplier', data)
            self.assertIn('points', data)
            self.assertIn('entries', data)
            self.assertIsInstance(data['entries'], list)


if __name__ == '__main__':
    unittest.main()
