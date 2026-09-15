"""Tenant billing ledger: idempotent checkout on unbilled usage plus top-ups.

The suite uses a temporary SQLite database and never calls a provider, so
every assertion is about this repository's own behaviour.
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


class BillingLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'billing-ledger.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant(
                'Billing Co', 'billing@example.test', 'hash', 'billing-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'billing@example.test', user_id=None,
            user_name='Billing Admin', user_role='company_admin',
        )
        cls._saved_env = {
            key: os.environ.get(key)
            for key in ('BILLING_ENFORCE', 'BILLING_MULTIPLIER',
                        'BILLING_PREFLIGHT_ESTIMATES')
        }

    @classmethod
    def tearDownClass(cls):
        for key, value in cls._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls.temp_dir.cleanup()

    def setUp(self):
        for key in ('BILLING_ENFORCE', 'BILLING_MULTIPLIER',
                    'BILLING_PREFLIGHT_ESTIMATES'):
            os.environ.pop(key, None)

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def _fresh_tenant(self, name, balance=0.0):
        with self.app.app_context():
            tenant_id = db.create_tenant(
                name, f'{name}@example.test', 'hash', name,
                credit_balance=balance)
        return tenant_id

    def _seed_usage(self, tenant_id, draft_id='draft-bill'):
        with self.app.app_context():
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=100,
                cost_usd=1.0, draft_id=draft_id)
            db.record_maps_usage_event(
                tenant_id, 'distance_matrix', 2, 0.01, flow='matrix',
                draft_id=draft_id)

    # ── Schema ─────────────────────────────────────────────────────────

    def test_ledger_table_and_links_exist_after_init(self):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        try:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn('tenant_ledger', names)
            for table in ('ai_usage_events', 'map_usage_events'):
                cols = {row[1] for row in conn.execute(
                    f'PRAGMA table_info({table})')}
                self.assertIn('billed_ledger_id', cols)
        finally:
            conn.close()

    # ── Checkout ───────────────────────────────────────────────────────

    def test_checkout_bills_unbilled_scope_once(self):
        tenant_id = self._fresh_tenant('checkout-once', balance=10.0)
        self._seed_usage(tenant_id)
        with self.app.app_context():
            result = db.bill_unbilled_usage(
                tenant_id, draft_id='draft-bill', multiplier=2.0)
        self.assertTrue(result['billed'])
        entry = result['entry']
        self.assertEqual(entry['kind'], 'debit')
        self.assertEqual(entry['ai_events_count'], 1)
        self.assertEqual(entry['maps_events_count'], 1)
        self.assertAlmostEqual(entry['ai_cost_usd'], 1.0)
        self.assertAlmostEqual(entry['maps_cost_usd'], 0.02)
        self.assertAlmostEqual(entry['amount_usd'], round(1.02 * 2.0, 2))
        self.assertAlmostEqual(result['balance_usd'], 10.0 - round(1.02 * 2.0, 2))
        with self.app.app_context():
            unbilled = db.get_unbilled_usage(tenant_id, draft_id='draft-bill')
        self.assertEqual(unbilled['ai_calls'], 0)
        self.assertEqual(unbilled['maps_calls'], 0)

    def test_checkout_is_idempotent_on_repeat(self):
        tenant_id = self._fresh_tenant('checkout-repeat', balance=10.0)
        self._seed_usage(tenant_id)
        with self.app.app_context():
            first = db.bill_unbilled_usage(tenant_id, draft_id='draft-bill')
            balance_after_first = db.get_tenant_balance(tenant_id)
            second = db.bill_unbilled_usage(tenant_id, draft_id='draft-bill')
            balance_after_second = db.get_tenant_balance(tenant_id)
        self.assertTrue(first['billed'])
        self.assertFalse(second['billed'])
        self.assertEqual(second['reason'], 'no_unbilled_events')
        self.assertAlmostEqual(balance_after_first, balance_after_second)

    def test_idempotency_key_replay_returns_original_entry(self):
        tenant_id = self._fresh_tenant('checkout-key', balance=10.0)
        self._seed_usage(tenant_id)
        with self.app.app_context():
            first = db.bill_unbilled_usage(
                tenant_id, draft_id='draft-bill', idempotency_key='key-1')
            self._seed_usage(tenant_id, draft_id='draft-new')
            replay = db.bill_unbilled_usage(
                tenant_id, draft_id='draft-new', idempotency_key='key-1')
            unbilled = db.get_unbilled_usage(tenant_id, draft_id='draft-new')
        self.assertTrue(first['billed'])
        self.assertFalse(replay['billed'])
        self.assertEqual(replay['reason'], 'idempotency_key_replayed')
        self.assertEqual(replay['entry']['id'], first['entry']['id'])
        self.assertEqual(unbilled['ai_calls'], 1)

    def test_insufficient_balance_rolls_back_claim(self):
        tenant_id = self._fresh_tenant('checkout-poor', balance=0.0)
        self._seed_usage(tenant_id)
        with self.app.app_context():
            with self.assertRaises(db.InsufficientBalance):
                db.bill_unbilled_usage(tenant_id, draft_id='draft-bill')
            unbilled = db.get_unbilled_usage(tenant_id, draft_id='draft-bill')
            entries = db.get_ledger_entries(tenant_id)
        self.assertEqual(unbilled['ai_calls'], 1)
        self.assertEqual(unbilled['maps_calls'], 1)
        self.assertEqual(entries, [])

    def test_scoped_checkout_leaves_other_scopes_unbilled(self):
        tenant_id = self._fresh_tenant('checkout-scope', balance=10.0)
        self._seed_usage(tenant_id, draft_id='draft-a')
        self._seed_usage(tenant_id, draft_id='draft-b')
        with self.app.app_context():
            result = db.bill_unbilled_usage(tenant_id, draft_id='draft-a')
            unbilled_b = db.get_unbilled_usage(tenant_id, draft_id='draft-b')
        self.assertTrue(result['billed'])
        self.assertEqual(result['entry']['draft_id'], 'draft-a')
        self.assertEqual(unbilled_b['ai_calls'], 1)

    def test_checkout_skips_unpriced_attempts(self):
        """In-flight/pending rows must not be claimed at $0: they stay
        unbilled until the reconcile loop prices them."""
        tenant_id = self._fresh_tenant('checkout-pending', balance=10.0)
        self._seed_usage(tenant_id)  # one settled AI row ($1.00) + one maps row
        with self.app.app_context():
            pending_id = db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=50,
                generation_id='gen-pending', draft_id='draft-bill')
            inflight_id = db.begin_ai_usage_attempt(
                tenant_id, 'model-x', flow='slide', draft_id='draft-bill')
            result = db.bill_unbilled_usage(
                tenant_id, draft_id='draft-bill', multiplier=2.0)
            conn = db.get_db()
            cols = {row['name'] for row in conn.execute(
                'PRAGMA table_info(ai_usage_events)').fetchall()}
            rows = {
                dict(r)['id']: dict(r)
                for r in conn.execute(
                    'SELECT id, billed_ledger_id, attempt_status FROM ai_usage_events '
                    'WHERE tenant_id = ?', (tenant_id,)).fetchall()
            } if 'billed_ledger_id' in cols else {}
        self.assertTrue(result['billed'])
        self.assertEqual(result['entry']['ai_events_count'], 1)
        self.assertAlmostEqual(result['entry']['ai_cost_usd'], 1.0)
        if rows:
            self.assertIsNone(rows[pending_id]['billed_ledger_id'])
            self.assertIsNone(rows[inflight_id]['billed_ledger_id'])

    def test_checkout_never_bills_package_consumed_usage(self):
        """A row burned under an assigned package is consumed against that
        package — the wallet must not charge it a second time."""
        tenant_id = self._fresh_tenant('checkout-pkg', balance=10.0)
        with self.app.app_context():
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=100,
                cost_usd=1.0, draft_id='draft-bill', package_id='pkg-1')
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=100,
                cost_usd=2.0, draft_id='draft-bill')
            result = db.bill_unbilled_usage(
                tenant_id, draft_id='draft-bill', multiplier=1.0)
            unbilled = db.get_unbilled_usage(tenant_id, draft_id='draft-bill')
        self.assertTrue(result['billed'])
        self.assertEqual(result['entry']['ai_events_count'], 1)
        self.assertAlmostEqual(result['entry']['ai_cost_usd'], 2.0)
        self.assertEqual(unbilled['ai_calls'], 0)

    def test_balance_change_hook_fires_on_credit_and_debit(self):
        tenant_id = self._fresh_tenant('hook-tenant', balance=10.0)
        fired = []
        previous = db.BALANCE_CHANGE_HOOK
        db.BALANCE_CHANGE_HOOK = fired.append
        try:
            with self.app.app_context():
                db.record_ledger_credit(tenant_id, 5.0, note='شحن')
                db.record_ai_usage_event(
                    tenant_id, 'model-x', flow='slide', total_tokens=10,
                    cost_usd=1.0, draft_id='draft-bill')
                db.bill_unbilled_usage(tenant_id, draft_id='draft-bill')
        finally:
            db.BALANCE_CHANGE_HOOK = previous
        self.assertEqual(fired, [tenant_id, tenant_id])

    def test_hold_total_and_billable_tenant_feed(self):
        tenant_id = self._fresh_tenant('sweep-feed', balance=10.0)
        with self.app.app_context():
            self.assertEqual(db.get_active_hold_total_usd(tenant_id), 0.0)
            self.assertNotIn(tenant_id, db.list_tenants_with_billable_usage())
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=10,
                cost_usd=1.0, draft_id='draft-bill')
            self.assertIn(tenant_id, db.list_tenants_with_billable_usage())

    # ── Credits ────────────────────────────────────────────────────────

    def test_topup_records_credit_and_adds_balance(self):
        tenant_id = self._fresh_tenant('topup', balance=1.0)
        with self.app.app_context():
            result = db.record_ledger_credit(tenant_id, 5.0, note='manual top-up')
        self.assertTrue(result['credited'])
        self.assertEqual(result['entry']['kind'], 'credit')
        self.assertAlmostEqual(result['balance_usd'], 6.0)

    # ── Pre-flight guard ───────────────────────────────────────────────

    def test_preflight_passes_when_enforcement_off(self):
        os.environ.pop('BILLING_ENFORCE', None)
        with self.app.app_context():
            from flask import g
            g.tenant_id = self.tenant_id
            self.assertIsNone(
                self.application_module._require_billing_balance('analyze_site'))

    def test_preflight_blocks_expensive_call_when_enforced(self):
        os.environ['BILLING_ENFORCE'] = '1'
        client = self.app.test_client()
        response = client.post(
            '/api/analyze-site',
            json={'projectData': {'location_address': 'https://maps.google.com/?q=24.0,46.0'}},
            headers=self._headers())
        self.assertEqual(response.status_code, 402)
        body = response.get_json()
        self.assertFalse(body['success'])
        self.assertEqual(body['error_code'], 'INSUFFICIENT_BALANCE')

    # ── HTTP surface ───────────────────────────────────────────────────

    def test_checkout_endpoint_returns_402_without_balance(self):
        tenant_id = self._fresh_tenant('checkout-http', balance=0.0)
        token = auth.create_token(
            tenant_id, 'checkout-http@example.test', user_id=None,
            user_name='Checkout Admin', user_role='company_admin')
        self._seed_usage(tenant_id, draft_id='draft-http')
        client = self.app.test_client()
        response = client.post(
            '/api/billing/checkout', json={'draftId': 'draft-http'},
            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.get_json()['error_code'], 'INSUFFICIENT_BALANCE')

    def test_ledger_endpoint_reports_balance_and_history(self):
        tenant_id = self._fresh_tenant('ledger-http', balance=3.0)
        token = auth.create_token(
            tenant_id, 'ledger-http@example.test', user_id=None,
            user_name='Ledger Admin', user_role='company_admin')
        self._seed_usage(tenant_id, draft_id='draft-ledger')
        client = self.app.test_client()
        headers = {'Authorization': f'Bearer {token}'}
        before = client.get('/api/billing/ledger', headers=headers).get_json()
        self.assertTrue(before['success'])
        self.assertAlmostEqual(before['balance_usd'], 3.0)
        self.assertEqual(before['unbilled']['ai_calls'], 1)
        checkout = client.post(
            '/api/billing/checkout', json={'draftId': 'draft-ledger'},
            headers=headers).get_json()
        self.assertTrue(checkout['success'])
        self.assertTrue(checkout['billed'])
        after = client.get('/api/billing/ledger', headers=headers).get_json()
        self.assertEqual(len(after['entries']), 1)
        self.assertEqual(after['entries'][0]['kind'], 'debit')
        self.assertEqual(after['unbilled']['ai_calls'], 0)

    def test_topup_endpoint_requires_platform_admin(self):
        client = self.app.test_client()
        denied = client.post('/api/billing/topup', json={'amount_usd': 5.0})
        self.assertEqual(denied.status_code, 401)
        # A company admin can never mint wallet credit — funding flows through
        # package purchases approved by the platform desk.
        denied_client = client.post(
            '/api/billing/topup', json={'amount_usd': 5.0},
            headers=self._headers())
        self.assertEqual(denied_client.status_code, 403)

    def test_topup_endpoint_credits_named_tenant_as_admin(self):
        tenant_id = self._fresh_tenant('topup-target', balance=1.0)
        with self.app.app_context():
            conn = db.get_db()
            conn.execute(
                "INSERT INTO tenants (id, company_name, email, password_hash, is_active, is_admin) "
                "VALUES ('platform-admin', 'المنصة', 'root@x.test', 'hash', 1, 1)")
            conn.commit()
        admin_token = auth.create_token(
            'platform-admin', 'root@x.test', is_admin=True, user_name='مدير المنصة')
        client = self.app.test_client()
        missing_target = client.post(
            '/api/billing/topup', json={'amount_usd': 5.0},
            headers={'Authorization': f'Bearer {admin_token}'})
        self.assertEqual(missing_target.status_code, 400)
        response = client.post(
            '/api/billing/topup', json={'tenantId': tenant_id, 'amount_usd': 7.5},
            headers={'Authorization': f'Bearer {admin_token}'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['credited'])
        with self.app.app_context():
            self.assertAlmostEqual(db.get_tenant_balance(tenant_id), 8.5)


if __name__ == '__main__':
    unittest.main()
