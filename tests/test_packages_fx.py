"""Billing packages and the USD to SAR rate (super-admin part one).

Packages carry a dollar spend allowance plus a riyal selling price; the rate
refreshes on its own with a manual override auto-refresh never overwrites.
Temporary SQLite database, no provider calls: FX fetch is always patched.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


class PackagesFxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'packages-fx.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')
        cls.application_module.OPENROUTER_MANAGEMENT_KEY = None

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Pack Co', 'pack@example.test', 'hash', 'pack-co')
            cls.admin_tenant = db.create_tenant('SAG Admin', 'sag-fx@example.test', 'hash', 'sag-fx')
            db.get_db().execute(
                'UPDATE tenants SET is_admin = 1 WHERE id = ?', (cls.admin_tenant,))
            db.get_db().commit()

        cls.admin_token = auth.create_token(
            cls.admin_tenant, 'sag-fx@example.test', user_id=None,
            user_name='SAG', user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.application_module.OPENROUTER_MANAGEMENT_KEY = None
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _admin_headers(self):
        return {'Authorization': f'Bearer {self.admin_token}'}

    # ── Tables ─────────────────────────────────────────────────────────

    def test_billing_tables_exist_after_init(self):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn('billing_packages', names)
        self.assertIn('fx_rates', names)

    # ── Packages ───────────────────────────────────────────────────────

    def test_package_crud_and_assign(self):
        client = self.app.test_client()
        created = client.post(
            '/api/admin/packages', headers=self._admin_headers(),
            json={'name': 'باقة النمو', 'creditUsd': 25, 'priceSar': 100})
        self.assertEqual(created.status_code, 201, created.get_json())
        package = created.get_json()['package']
        self.assertEqual(package['credit_usd'], 25)
        self.assertEqual(package['price_sar'], 100)

        updated = client.put(
            f"/api/admin/packages/{package['id']}", headers=self._admin_headers(),
            json={'creditUsd': 30})
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()['package']['credit_usd'], 30)

        listed = client.get('/api/admin/packages', headers=self._admin_headers()).get_json()
        self.assertTrue(any(p['id'] == package['id'] for p in listed['packages']))

        assigned = client.post(
            f'/api/admin/tenants/{self.tenant_id}/package',
            headers=self._admin_headers(), json={'packageId': package['id']})
        self.assertEqual(assigned.status_code, 200, assigned.get_json())
        self.assertEqual(assigned.get_json()['package']['id'], package['id'])

        status = client.get(
            f'/api/admin/tenants/{self.tenant_id}/package',
            headers=self._admin_headers()).get_json()
        self.assertEqual(status['packageId'], package['id'])

        deleted = client.delete(
            f"/api/admin/packages/{package['id']}", headers=self._admin_headers())
        self.assertEqual(deleted.status_code, 200)
        with self.app.app_context():
            tenant = db.get_tenant_by_id(self.tenant_id)
        self.assertIsNone(tenant.get('package_id'))

    def test_package_endpoints_reject_bad_input(self):
        client = self.app.test_client()
        denied = client.get('/api/admin/packages')
        self.assertEqual(denied.status_code, 401)
        bad = client.post('/api/admin/packages', headers=self._admin_headers(),
                          json={'name': '', 'creditUsd': -5})
        self.assertEqual(bad.status_code, 400)
        missing = client.put('/api/admin/packages/nope', headers=self._admin_headers(),
                             json={'creditUsd': 5})
        self.assertEqual(missing.status_code, 404)

    # ── FX rate ────────────────────────────────────────────────────────

    def test_manual_override_beats_auto_and_sticks(self):
        module = self.application_module
        client = self.app.test_client()
        manual = client.put('/api/admin/fx-rate', headers=self._admin_headers(),
                            json={'mode': 'manual', 'rate': 3.4})
        self.assertEqual(manual.status_code, 200, manual.get_json())
        self.assertEqual(manual.get_json()['fx']['rate'], 3.4)
        self.assertEqual(manual.get_json()['fx']['source'], 'manual')

        # Auto refresh must never overwrite a manual override.
        with patch.object(module, '_fetch_fx_usd_sar', return_value=3.9) as fetch:
            refreshed = module._refresh_fx_rate()
            self.assertEqual(fetch.call_count, 0)
        self.assertEqual(refreshed['rate'], 3.4)
        self.assertEqual(refreshed['source'], 'manual')

        # Back to auto tracking stores the fetched rate.
        with patch.object(module, '_fetch_fx_usd_sar', return_value=3.9):
            auto = client.put('/api/admin/fx-rate', headers=self._admin_headers(),
                              json={'mode': 'auto'})
        self.assertEqual(auto.status_code, 200, auto.get_json())
        self.assertEqual(auto.get_json()['fx']['rate'], 3.9)
        self.assertEqual(auto.get_json()['fx']['source'], 'auto')

    def test_fx_fetch_failure_keeps_stored_rate(self):
        module = self.application_module
        client = self.app.test_client()
        with patch.object(module, '_fetch_fx_usd_sar', return_value=None):
            kept = module._refresh_fx_rate(force=True)
        with self.app.app_context():
            current = db.get_fx_rate()
        self.assertEqual(kept['rate'], current['rate'])

    def test_balances_display_in_sar(self):
        client = self.app.test_client()
        client.put('/api/admin/fx-rate', headers=self._admin_headers(),
                   json={'mode': 'manual', 'rate': 3.5})
        with self.app.app_context():
            db.update_tenant(self.tenant_id, credit_balance=10.0)
        company_token = auth.create_token(
            self.tenant_id, 'pack@example.test', user_id=None,
            user_name='Pack Admin', user_role='company_admin')
        body = client.get(
            '/api/ai-usage',
            headers={'Authorization': f'Bearer {company_token}'}).get_json()
        self.assertTrue(body['success'])
        self.assertAlmostEqual(body['billing']['balance_usd'], 10.0)
        self.assertAlmostEqual(body['billing']['balance_sar'], 35.0)
        self.assertEqual(body['billing']['fx']['rate'], 3.5)

    def test_usd_to_sar_rounding(self):
        with self.app.app_context():
            self.assertEqual(db.usd_to_sar(10.0, 3.5), 35.0)
            self.assertEqual(db.usd_to_sar(0.374, 3.75), 1.4)
            self.assertEqual(db.sar_to_usd(35.0, 3.5), 10.0)
            self.assertEqual(db.sar_to_usd(37.5, 3.75), 10.0)

    def test_package_credit_keyed_in_sar(self):
        client = self.app.test_client()
        client.put('/api/admin/fx-rate', headers=self._admin_headers(),
                   json={'mode': 'manual', 'rate': 2.5})
        created = client.post(
            '/api/admin/packages', headers=self._admin_headers(),
            json={'name': 'باقة ريال', 'creditSar': 100, 'priceSar': 100})
        self.assertEqual(created.status_code, 201, created.get_json())
        package = created.get_json()['package']
        self.assertAlmostEqual(package['credit_usd'], 40.0)

        updated = client.put(
            f"/api/admin/packages/{package['id']}", headers=self._admin_headers(),
            json={'creditSar': 200})
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertAlmostEqual(updated.get_json()['package']['credit_usd'], 80.0)

        listed = client.get('/api/admin/packages', headers=self._admin_headers()).get_json()
        row = next(p for p in listed['packages'] if p['id'] == package['id'])
        self.assertAlmostEqual(row['credit_sar'], 200.0)

        # The client catalog feed exposes the riyal figure as well.
        company_token = auth.create_token(
            self.tenant_id, 'pack@example.test', user_id=None,
            user_name='Pack Admin', user_role='company_admin')
        feed = client.get('/api/billing/packages',
                          headers={'Authorization': f'Bearer {company_token}'}).get_json()
        feed_row = next(p for p in feed['packages'] if p['id'] == package['id'])
        self.assertAlmostEqual(feed_row['credit_sar'], 200.0)

    def test_tenant_credit_balance_keyed_in_sar(self):
        client = self.app.test_client()
        client.put('/api/admin/fx-rate', headers=self._admin_headers(),
                   json={'mode': 'manual', 'rate': 2.5})
        saved = client.put(
            f'/api/admin/tenants/{self.tenant_id}', headers=self._admin_headers(),
            json={'creditBalanceSar': 250})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertAlmostEqual(saved.get_json()['tenant']['creditBalanceSar'], 250.0)
        with self.app.app_context():
            tenant = db.get_tenant_by_id(self.tenant_id)
        self.assertAlmostEqual(float(tenant['credit_balance']), 100.0)

    def test_usage_totals_carry_sar(self):
        client = self.app.test_client()
        client.put('/api/admin/fx-rate', headers=self._admin_headers(),
                   json={'mode': 'manual', 'rate': 4.0})
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_id, 'model-x', flow='slide', total_tokens=10,
                cost_usd=1.0, draft_id='draft-sar')
        company_token = auth.create_token(
            self.tenant_id, 'pack@example.test', user_id=None,
            user_name='Pack Admin', user_role='company_admin')
        body = client.get(
            '/api/usage-totals?draftIds=draft-sar',
            headers={'Authorization': f'Bearer {company_token}'}).get_json()
        project = body['projects']['draft-sar']
        self.assertAlmostEqual(project['cost_usd'], 1.0)
        self.assertAlmostEqual(project['cost_sar'], 4.0)

    def test_frontend_has_no_dollar_strings(self):
        parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
        for _css in sorted((ROOT / 'assets' / 'css').rglob('*.css')):
            parts.append(_css.read_text(encoding='utf-8'))
        for name in sorted((ROOT / 'assets' / 'js').rglob('*.js')):
            parts.append(name.read_text(encoding='utf-8'))
        frontend = '\n'.join(parts)
        self.assertNotIn('دولار', frontend)

    # ── Forced reset ───────────────────────────────────────────────────

    def test_reset_all_requires_confirm_and_spares_admins(self):
        client = self.app.test_client()
        with self.app.app_context():
            company = db.create_tenant('Reset Co', 'reset-fx@example.test', 'hash', 'reset-fx')
            db.update_tenant(company, credit_balance=5.0)
            package = db.create_billing_package('باقة تصفير', credit_usd=5.0)
            db.assign_tenant_package(company, package['id'])
            db.record_ai_usage_event(
                company, 'model-r', flow='slide', total_tokens=10,
                cost_usd=1.0, generation_id='gen-reset-1')
            db.record_ledger_credit(company, 5.0)
            admin_wallet_before = db.get_tenant_balance(self.admin_tenant)

        refused = client.post('/api/admin/billing/reset-all',
                              headers=self._admin_headers(), json={})
        self.assertEqual(refused.status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.get_tenant_balance(company), 10.0)

        company_token = auth.create_token(
            company, 'reset-fx@example.test', user_id=None,
            user_name='Reset Admin', user_role='company_admin')
        forbidden = client.post(
            '/api/admin/billing/reset-all',
            headers={'Authorization': f'Bearer {company_token}'},
            json={'confirm': True})
        self.assertEqual(forbidden.status_code, 403)

        done = client.post('/api/admin/billing/reset-all',
                           headers=self._admin_headers(),
                           json={'confirm': True})
        self.assertEqual(done.status_code, 200, done.get_json())
        body = done.get_json()
        self.assertTrue(body['success'])
        self.assertGreaterEqual(body['tenants_reset'], 1)
        self.assertGreaterEqual(body['ai_deleted'], 1)
        with self.app.app_context():
            self.assertEqual(db.get_tenant_balance(company), 0.0)
            self.assertIsNone(db.get_tenant_by_id(company).get('package_id'))
            self.assertEqual(db.get_tenant_balance(self.admin_tenant), admin_wallet_before)
            remaining = db.get_db().execute(
                'SELECT COUNT(*) AS n FROM ai_usage_events WHERE tenant_id = ?',
                (company,)).fetchone()['n']
        self.assertEqual(remaining, 0)


if __name__ == '__main__':
    unittest.main()
