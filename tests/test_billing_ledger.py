"""Tenant billing ledger: idempotent checkout on unbilled usage plus top-ups.

The suite uses a temporary SQLite database and never calls a provider, so
every assertion is about this repository's own behaviour.
"""

import os
import sys
import tempfile
import threading
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
        cls.application_module.OPENROUTER_MANAGEMENT_KEY = None

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
        # Wallet moves fire `cap-sync-*` provider-cap threads that open their
        # own SQLite handle — on Windows the temp file cannot be deleted while
        # that handle lives, so wait for them before cleanup.
        for thread in threading.enumerate():
            if thread.name.startswith(('usage-bill-', 'cap-sync-')):
                thread.join(timeout=10)
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
        # Wallet money is riyals: raw USD x rate (3.75) x multiplier.
        self.assertAlmostEqual(entry['amount_usd'], round(1.02 * 2.0, 2))
        self.assertAlmostEqual(entry['amount_sar'], round(1.02 * 3.75 * 2.0, 2))
        self.assertAlmostEqual(result['balance_sar'], 10.0 - round(1.02 * 3.75 * 2.0, 2))
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
            self.assertEqual(db.get_active_hold_total_sar(tenant_id), 0.0)
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
        self.assertAlmostEqual(result['entry']['amount_sar'], 5.0)
        self.assertAlmostEqual(result['balance_sar'], 6.0)

    # ── Sub-cent carry (ISS-038) ───────────────────────────────────────

    def test_subcent_claim_carries_instead_of_closing_at_zero(self):
        """ISS-038: a claim whose billed total rounds to 0.00 SAR must leave
        the rows unbilled so the cents accumulate into the next invoice."""
        tenant_id = self._fresh_tenant('subcent', balance=10.0)
        with self.app.app_context():
            # 0.0001 raw x 3.75 x 1.6 = 0.0006 SAR — below a single halala.
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=3,
                cost_usd=0.0001, draft_id='draft-subcent')
            result = db.bill_unbilled_usage(tenant_id, draft_id='draft-subcent')
        self.assertFalse(result['billed'])
        self.assertEqual(result['reason'], 'below_minimum_charge')
        with self.app.app_context():
            conn = db.get_db()
            row = conn.execute(
                'SELECT billed_ledger_id FROM ai_usage_events WHERE draft_id = ?',
                ('draft-subcent',)).fetchone()
            self.assertIsNone(row['billed_ledger_id'])
            count = conn.execute(
                'SELECT COUNT(*) AS c FROM tenant_ledger WHERE tenant_id = ? AND kind = ?',
                (tenant_id, 'debit')).fetchone()['c']
            self.assertEqual(count, 0)
            self.assertAlmostEqual(db.get_tenant_balance(tenant_id), 10.0)

    def test_carried_subcent_claim_bills_once_threshold_is_crossed(self):
        """ISS-038: after the carried cents push the aggregate past a halala,
        the next checkout claims the earlier rows under the new debit."""
        tenant_id = self._fresh_tenant('subcent-carry', balance=10.0)
        with self.app.app_context():
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=3,
                cost_usd=0.0001, draft_id='draft-carry')
            first = db.bill_unbilled_usage(tenant_id, draft_id='draft-carry')
            self.assertFalse(first['billed'])
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=900,
                cost_usd=0.002, draft_id='draft-carry')
            second = db.bill_unbilled_usage(tenant_id, draft_id='draft-carry')
        self.assertTrue(second['billed'])
        entry = second['entry']
        # 0.0021 raw x 3.75 x 1.6 = 0.0126 -> 0.01 SAR collected once.
        self.assertAlmostEqual(entry['amount_sar'], 0.01, places=2)
        self.assertEqual(entry['ai_events_count'], 2)
        with self.app.app_context():
            conn = db.get_db()
            unbilled = conn.execute(
                'SELECT COUNT(*) AS c FROM ai_usage_events '
                'WHERE draft_id = ? AND billed_ledger_id IS NULL',
                ('draft-carry',)).fetchone()['c']
            self.assertEqual(unbilled, 0)

    def test_zero_cost_rows_still_close_instead_of_looping(self):
        """ISS-038: genuinely free rows have no cents to carry — marking them
        billed at $0 keeps them out of every later claim scope."""
        tenant_id = self._fresh_tenant('free-rows', balance=10.0)
        with self.app.app_context():
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=0,
                cost_usd=0.0, draft_id='draft-free')
            result = db.bill_unbilled_usage(tenant_id, draft_id='draft-free')
        self.assertTrue(result['billed'])
        self.assertAlmostEqual(result['entry']['amount_sar'], 0.0)

    # ── Package fallback (ISS-039) ─────────────────────────────────────

    def test_exhausted_package_stops_owning_new_usage(self):
        """ISS-039: once the assigned package's credit is burned, new usage
        must fall back to the wallet instead of staying package-tagged and
        unbillable forever."""
        tenant_id = self._fresh_tenant('pkg-exhaust', balance=10.0)
        with self.app.app_context():
            # 0.01 SAR of entitlement burns after 0.0027 USD of raw spend.
            package = db.create_billing_package('pkg-mini', credit_sar=0.01)
            db.assign_tenant_package(tenant_id, package['id'])
            # First event burns the package credit exactly under it
            # (0.01 USD raw = 0.0375 SAR > the 0.01 SAR grant).
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=10,
                cost_usd=0.01, draft_id='draft-pkg')
            # Second event lands after the credit is gone — it must be a
            # wallet row, not another package row the billing sweep ignores.
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=10,
                cost_usd=0.02, draft_id='draft-pkg')
            conn = db.get_db()
            rows = conn.execute(
                'SELECT cost_usd, package_id FROM ai_usage_events '
                'WHERE tenant_id = ? ORDER BY created_at ASC, rowid ASC',
                (tenant_id,)).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['package_id'], package['id'])
            self.assertIsNone(rows[1]['package_id'])
            # And the wallet actually bills the overflow row.
            result = db.bill_unbilled_usage(tenant_id, draft_id='draft-pkg')
            self.assertTrue(result['billed'])
            self.assertAlmostEqual(result['entry']['amount_sar'], 0.12, places=2)

    def test_deactivated_package_stops_owning_new_usage(self):
        """ISS-039: an is_active=0 package is not a valid spend owner either."""
        tenant_id = self._fresh_tenant('pkg-off', balance=10.0)
        with self.app.app_context():
            package = db.create_billing_package('pkg-off', credit_sar=5.0)
            db.assign_tenant_package(tenant_id, package['id'])
            conn = db.get_db()
            conn.execute('UPDATE billing_packages SET is_active = 0 WHERE id = ?',
                         (package['id'],))
            conn.commit()
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=10,
                cost_usd=0.02, draft_id='draft-off')
            row = conn.execute(
                'SELECT package_id FROM ai_usage_events WHERE tenant_id = ?',
                (tenant_id,)).fetchone()
            self.assertIsNone(row['package_id'])

    def test_reassignment_starts_a_fresh_package_cycle(self):
        """ISS-040: re-assigning a consumed package must open a new credit
        window — the old cycle's burn must not eat the new grant."""
        tenant_id = self._fresh_tenant('pkg-cycle', balance=10.0)
        with self.app.app_context():
            # 3.75 SAR of entitlement = 1.00 USD of raw provider spend.
            package = db.create_billing_package('pkg-renew', credit_sar=3.75)
            db.assign_tenant_package(tenant_id, package['id'])
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=10,
                cost_usd=1.0, draft_id='draft-cycle')
            self.assertAlmostEqual(db.get_package_remaining_sar(tenant_id), 0.0)
            import time
            time.sleep(1.1)  # cycle bound is second-precision
            db.assign_tenant_package(tenant_id, package['id'])
            # New cycle: full snapshot credit again, old usage out of scope.
            self.assertAlmostEqual(db.get_package_remaining_sar(tenant_id), 3.75)
            db.record_ai_usage_event(
                tenant_id, 'model-x', flow='slide', total_tokens=10,
                cost_usd=0.5, draft_id='draft-cycle')
            row = db.get_db().execute(
                'SELECT package_id FROM ai_usage_events WHERE tenant_id = ? '
                'ORDER BY created_at DESC, rowid DESC LIMIT 1',
                (tenant_id,)).fetchone()
            self.assertEqual(row['package_id'], package['id'])
            self.assertAlmostEqual(db.get_package_remaining_sar(tenant_id), 1.87)

    def test_catalog_edit_does_not_rewrite_existing_entitlement(self):
        """ISS-040: changing the catalog credit must not change what an
        already-assigned company was granted."""
        tenant_id = self._fresh_tenant('pkg-snapshot', balance=10.0)
        with self.app.app_context():
            package = db.create_billing_package('pkg-snap', credit_sar=0.5)
            db.assign_tenant_package(tenant_id, package['id'])
            db.update_billing_package(package['id'], credit_sar=0.1)
            # The assignment snapshot keeps the original 0.5 SAR grant.
            self.assertAlmostEqual(db.get_package_remaining_sar(tenant_id), 0.5)

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

    def test_preflight_fails_closed_when_balance_lookup_errors(self):
        """ISS-037: an unreadable wallet is not a funded wallet — a DB error
        must refuse the paid call instead of silently letting it through."""
        os.environ['BILLING_ENFORCE'] = '1'
        original = db.get_tenant_balance
        db.get_tenant_balance = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('db down'))
        try:
            with self.app.app_context():
                from flask import g
                g.tenant_id = self.tenant_id
                resp, status = self.application_module._require_billing_balance('analyze_site')
        finally:
            db.get_tenant_balance = original
        self.assertEqual(status, 503)
        self.assertEqual(resp.get_json()['error_code'], 'BILLING_CHECK_UNAVAILABLE')

    def test_preflight_guard_covers_paid_ai_routes(self):
        """ISS-037: image, visual-concept, executive-content and legacy paid
        routes all run the wallet preflight before any provider call."""
        os.environ['BILLING_ENFORCE'] = '1'
        tenant_id = self._fresh_tenant('preflight-coverage', balance=0.0)
        token = auth.create_token(
            tenant_id, 'preflight-coverage@example.test', user_id=None,
            user_name='Coverage Admin', user_role='company_admin')
        headers = {'Authorization': f'Bearer {token}'}
        client = self.app.test_client()
        paid_posts = [
            ('/api/visual-concept/generate', {'slotId': 'cover'}),
            ('/api/visual-concept/chat', {'slotId': 'cover'}),
            ('/api/visual-concept/plans-verify', {}),
            ('/api/visual-concept/plans-boundary', {
                'mode': 'ai',
                'plansWorkflow': {'verification': {'approved': True}},
            }),
            ('/api/visual-concept/prompt', {
                'slotId': 'plan_site',
                'instruction': 'x',
                'projectData': {'project_name': 'x'},
                'plansWorkflow': {
                    'verification': {'approved': True},
                    'boundary': {'approved': True},
                    'distribution': {'approved': True},
                },
            }),
            ('/api/generate-images', {'projectData': {}}),
            ('/api/generate-main-image', {'projectData': {}}),
            ('/api/generate-slide-image', {'prompt': 'x'}),
            ('/api/generate-image', {'prompt': 'x'}),
            ('/api/generate', {'projectData': {}}),
            ('/api/generate-content', {'projectData': {}}),
            ('/api/ai-edit-slide', {'instruction': 'x'}),
            ('/api/ai-chat', {'message': 'x'}),
            ('/api/generate-bullets', {'title': 'x'}),
            ('/api/designer-generate', {'projectData': {}}),
            ('/api/designer-chat', {'message': 'x'}),
            ('/api/generate-cover-prompt', {'projectData': {}}),
            ('/api/get-image-prompts', {'projectData': {}}),
            ('/api/executive-content/generate', {'block': 'x'}),
            ('/api/ai-input-builder', {'description': 'x'}),
            ('/api/ai-build-fields', {'description': 'x'}),
            ('/api/training-chat', {'message': 'x'}),
            ('/api/market-study/competitors/logo', {'competitor': {'name': 'x'}}),
        ]
        for path, payload in paid_posts:
            response = client.post(path, json=payload, headers=headers)
            body = response.get_json() or {}
            self.assertEqual(
                response.status_code, 402,
                f'{path} should refuse an empty wallet first, got '
                f'{response.status_code}: {body}')
            self.assertEqual(body.get('error_code'), 'INSUFFICIENT_BALANCE', path)

    def test_preflight_refusal_precedes_payload_validation(self):
        """ISS-037: the wallet check fires before request validation, so a
        paid route can never be probed for free with malformed payloads."""
        os.environ['BILLING_ENFORCE'] = '1'
        tenant_id = self._fresh_tenant('preflight-order', balance=0.0)
        token = auth.create_token(
            tenant_id, 'preflight-order@example.test', user_id=None,
            user_name='Order Admin', user_role='company_admin')
        client = self.app.test_client()
        response = client.post(
            '/api/executive-content/generate', json={},
            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 402)
        self.assertEqual(
            response.get_json()['error_code'], 'INSUFFICIENT_BALANCE')

    def test_tenant_key_gate_fails_closed_on_lookup_error(self):
        """ISS-037: strict tenant-key mode must refuse when the key lookup
        itself fails — a storage error cannot become a free pass."""
        module = self.application_module
        original_flag = module.REQUIRE_TENANT_OPENROUTER_KEY
        original_raw = db.get_tenant_openrouter_key_raw
        original_tenant = db.get_tenant_by_id
        module.REQUIRE_TENANT_OPENROUTER_KEY = True
        db.get_tenant_by_id = lambda tid: {'id': tid, 'is_admin': 0}
        db.get_tenant_openrouter_key_raw = (
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('db down')))
        try:
            verdict = module._tenant_key_gate(tenant_id=self.tenant_id)
        finally:
            module.REQUIRE_TENANT_OPENROUTER_KEY = original_flag
            db.get_tenant_openrouter_key_raw = original_raw
            db.get_tenant_by_id = original_tenant
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict['error_code'], 'TENANT_KEY_CHECK_FAILED')

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
        tenant_id = self._fresh_tenant('ledger-http', balance=10.0)
        token = auth.create_token(
            tenant_id, 'ledger-http@example.test', user_id=None,
            user_name='Ledger Admin', user_role='company_admin')
        self._seed_usage(tenant_id, draft_id='draft-ledger')
        client = self.app.test_client()
        headers = {'Authorization': f'Bearer {token}'}
        before = client.get('/api/billing/ledger', headers=headers).get_json()
        self.assertTrue(before['success'])
        self.assertAlmostEqual(before['balance_sar'], 10.0)
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

    def test_topup_endpoint_is_retired_package_only_funding(self):
        """Manual wallet credit is gone: funding is package-only, so even a
        platform admin gets a clear refusal instead of a minted balance."""
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
        response = client.post(
            '/api/billing/topup', json={'tenantId': tenant_id, 'amount_usd': 7.5},
            headers={'Authorization': f'Bearer {admin_token}'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_code'], 'package_only_funding')
        with self.app.app_context():
            self.assertAlmostEqual(db.get_tenant_balance(tenant_id), 1.0)


if __name__ == '__main__':
    unittest.main()
