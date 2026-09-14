"""Client card: totals, current package with remaining, lifetime spend.

A package reads expired exactly when its remaining hits zero, and the
lifetime total keeps every package the company ever consumed. Temporary
SQLite database, no provider calls.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


class ClientOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'client-overview.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Client Co', 'client@example.test', 'hash', 'client-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'client@example.test', user_id=None, user_name='Client Admin',
            user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _headers(self, token=None):
        return {'Authorization': f'Bearer {token or self.token}'}

    def _fresh_client(self, name, email, slug):
        with self.app.app_context():
            tenant_id = db.create_tenant(name, email, 'hash', slug)
        token = auth.create_token(
            tenant_id, email, user_id=None, user_name=name, user_role='company_admin')
        return tenant_id, token

    def _overview(self, token=None):
        return self.app.test_client().get(
            '/api/client/overview', headers=self._headers(token)).get_json()

    # ── No package ─────────────────────────────────────────────────────

    def test_overview_without_package(self):
        _tenant_id, token = self._fresh_client('Fresh Co', 'fresh-ov@example.test', 'fresh-ov')
        body = self._overview(token)
        self.assertTrue(body['success'])
        self.assertEqual(body['totals']['projects'], 0)
        self.assertEqual(body['totals']['presentations'], 0)
        self.assertEqual(body['totals']['consumption_usd'], 0)
        self.assertIsNone(body['package'])
        self.assertEqual(body['lifetime']['consumed_usd'], 0)

    # ── Active then expired ────────────────────────────────────────────

    def test_package_active_then_expired(self):
        tenant_id, token = self._fresh_client('Expiry Co', 'expiry-ov@example.test', 'expiry-ov')
        with self.app.app_context():
            package = db.create_billing_package('باقة اختبار', credit_usd=1.0, price_sar=10.0)
            db.assign_tenant_package(tenant_id, package['id'])
            db.record_ai_usage_event(
                tenant_id, 'model-o', flow='slide', total_tokens=10,
                cost_usd=0.40, generation_id='gen-ov-1')
            db.record_maps_usage_event(
                tenant_id, 'geocode', 2, 0.005, flow='site')
        body = self._overview(token)
        self.assertEqual(body['package']['name'], 'باقة اختبار')
        self.assertAlmostEqual(body['package']['credit_usd'], 1.0)
        self.assertAlmostEqual(body['package']['consumed_usd'], 0.41)
        self.assertAlmostEqual(body['package']['remaining_usd'], 0.59)
        self.assertEqual(body['package']['status'], 'active')
        self.assertAlmostEqual(body['lifetime']['consumed_usd'], 0.41)

        with self.app.app_context():
            db.record_ai_usage_event(
                tenant_id, 'model-o', flow='slide', total_tokens=10,
                cost_usd=0.70, generation_id='gen-ov-2')
        body = self._overview(token)
        self.assertAlmostEqual(body['package']['consumed_usd'], 1.11)
        self.assertEqual(body['package']['remaining_usd'], 0)
        self.assertEqual(body['package']['status'], 'expired')
        self.assertAlmostEqual(body['lifetime']['consumed_usd'], 1.11)

    # ── Lifetime spans packages ────────────────────────────────────────

    def test_lifetime_covers_every_package(self):
        tenant_id, token = self._fresh_client('Life Co', 'life-ov@example.test', 'life-ov')
        with self.app.app_context():
            first = db.create_billing_package('الأولى', credit_usd=5.0)
            db.assign_tenant_package(tenant_id, first['id'])
            db.record_ai_usage_event(
                tenant_id, 'model-o', flow='slide', total_tokens=10,
                cost_usd=2.0, generation_id='gen-ov-3')
            second = db.create_billing_package('الثانية', credit_usd=5.0)
            db.assign_tenant_package(tenant_id, second['id'])
            db.record_ai_usage_event(
                tenant_id, 'model-o', flow='slide', total_tokens=10,
                cost_usd=1.0, generation_id='gen-ov-4')
        body = self._overview(token)
        self.assertEqual(body['package']['name'], 'الثانية')
        self.assertAlmostEqual(body['package']['consumed_usd'], 1.0)
        self.assertAlmostEqual(body['package']['remaining_usd'], 4.0)
        self.assertEqual(body['package']['status'], 'active')
        self.assertAlmostEqual(body['lifetime']['consumed_usd'], 3.0)

    # ── Totals count work ──────────────────────────────────────────────

    def test_totals_count_projects_and_presentations(self):
        tenant_id, token = self._fresh_client('Count Co', 'count-ov@example.test', 'count-ov')
        with self.app.app_context():
            db.get_db().execute(
                'INSERT INTO project_drafts (id, tenant_id, title) VALUES (?, ?, ?)',
                ('draft-ov-1', tenant_id, 'مشروع'))
            db.get_db().execute(
                'INSERT INTO presentations (id, tenant_id, title) VALUES (?, ?, ?)',
                ('pres-ov-1', tenant_id, 'عرض'))
            db.get_db().commit()
        body = self._overview(token)
        self.assertGreaterEqual(body['totals']['projects'], 1)
        self.assertGreaterEqual(body['totals']['presentations'], 1)


if __name__ == '__main__':
    unittest.main()
