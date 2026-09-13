"""Response cost is provisional: /generation total_cost is the source of truth.

A row settled from the chat response (e.g. 1.40) must be verified once
against /generation (e.g. 1.50) and overwritten in place, while already
verified rows are never re-queried. The suite uses a temporary SQLite
database and never calls a provider: HTTP is always patched.
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


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class AiCostVerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'ai-cost-verify.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Verify Co', 'verify@example.test', 'hash', 'verify-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'verify@example.test', user_id=None, user_name='Verify Admin',
            user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _row(self, event_id):
        with self.app.app_context():
            return dict(db.get_db().execute(
                'SELECT cost_usd, cost_source, attempt_status, response_cost_usd, '
                'generation_cost_usd, reconcile_attempts, next_retry_at '
                'FROM ai_usage_events WHERE id = ?', (event_id,)).fetchone())

    # ── Scope ──────────────────────────────────────────────────────────

    def test_response_settled_row_needs_verify_but_verified_does_not(self):
        with self.app.app_context():
            provisional = db.record_ai_usage_event(
                self.tenant_id, 'model-v', flow='slide', total_tokens=10,
                cost_usd=1.40, cost_source='response', generation_id='gen-verify-1',
                draft_id='draft-verify-scope')
            verified = db.record_ai_usage_event(
                self.tenant_id, 'model-v', flow='slide', total_tokens=10,
                cost_usd=1.50, cost_source='generation', generation_cost_usd=1.50,
                generation_id='gen-verify-2', draft_id='draft-verify-scope')
            ids = [row['id'] for row in db.get_ai_events_needing_reconcile(
                limit=50, tenant_id=self.tenant_id, draft_id='draft-verify-scope')]
        self.assertIn(provisional, ids)
        self.assertNotIn(verified, ids)

    def test_scope_overwrites_provisional_with_generation_total(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-v', flow='slide', total_tokens=10,
                cost_usd=1.40, cost_source='response', generation_id='gen-verify-3',
                draft_id='draft-verify-overwrite')
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'data': {'id': 'gen-verify-3',
                                                                  'total_cost': 1.50}})):
                result = module._reconcile_ai_scope(
                    limit=10, time_budget_seconds=5, tenant_id=self.tenant_id,
                    draft_id='draft-verify-overwrite', force=True)
        self.assertEqual(result['reconciled'], 1)
        self.assertEqual(result['verified'], 1)
        row = self._row(event_id)
        self.assertAlmostEqual(row['cost_usd'], 1.50)
        self.assertEqual(row['cost_source'], 'generation')
        self.assertEqual(row['attempt_status'], 'settled')
        self.assertAlmostEqual(row['response_cost_usd'], 1.40)
        self.assertAlmostEqual(row['generation_cost_usd'], 1.50)

    def test_explicit_review_keeps_review_source(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-v', flow='slide', total_tokens=10,
                cost_usd=1.40, cost_source='response', generation_id='gen-verify-4',
                draft_id='draft-verify-review')
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'data': {'id': 'gen-verify-4',
                                                                  'total_cost': 1.50}})):
                result = module._reconcile_single_ai_event(
                    event_id, 'gen-verify-4', is_review=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['cost_source'], 'review')
        self.assertAlmostEqual(self._row(event_id)['cost_usd'], 1.50)

    def test_failed_verify_keeps_provisional_and_schedules_retry(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-v', flow='slide', total_tokens=10,
                cost_usd=1.40, cost_source='response', generation_id='gen-verify-5',
                draft_id='draft-verify-retry')
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'error': 'not ready'}, 404)):
                result = module._reconcile_single_ai_event(event_id, 'gen-verify-5')
        self.assertFalse(result['ok'])
        row = self._row(event_id)
        self.assertAlmostEqual(row['cost_usd'], 1.40)
        self.assertEqual(row['cost_source'], 'response')
        self.assertEqual(row['attempt_status'], 'settled')
        self.assertIsNotNone(row['next_retry_at'])

    def test_exhausted_verify_moves_to_needs_review(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-v', flow='slide', total_tokens=10,
                cost_usd=1.40, cost_source='response', generation_id='gen-verify-6',
                draft_id='draft-verify-exhaust')
            db.update_ai_usage_attempt(event_id, reconcile_attempts=5, clear_next_retry=True)
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'error': 'gone'}, 404)):
                result = module._reconcile_single_ai_event(event_id, 'gen-verify-6')
        self.assertFalse(result['ok'])
        self.assertTrue(result.get('needs_review'))
        row = self._row(event_id)
        self.assertEqual(row['attempt_status'], 'needs_review')
        self.assertAlmostEqual(row['cost_usd'], 1.40)

    def test_settled_response_row_is_scoped_for_verify(self):
        module = self.application_module
        with self.app.app_context():
            attempt_id = db.begin_ai_usage_attempt(
                self.tenant_id, 'model-v', flow='slide', draft_id='draft-verify-settle')
            module._settle_ai_attempt_record(
                attempt_id, 'ok',
                {'prompt_tokens': 5, 'completion_tokens': 5, 'total_tokens': 10,
                 'cost_usd': 1.40, 'cost_raw': '1.4'},
                'gen-verify-7')
            ids = [row['id'] for row in db.get_ai_events_needing_reconcile(
                limit=50, tenant_id=self.tenant_id, draft_id='draft-verify-settle')]
        self.assertIn(attempt_id, ids)

    def test_summary_reflects_verified_total(self):
        module = self.application_module
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_id, 'model-v', flow='slide', total_tokens=10,
                cost_usd=1.40, cost_source='response', generation_id='gen-verify-8',
                draft_id='draft-verify-totals')
            before = db.get_ai_usage_summary(
                self.tenant_id, draft_id='draft-verify-totals')['totals']['cost_usd']
            self.assertAlmostEqual(float(before), 1.40)
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'data': {'id': 'gen-verify-8',
                                                                  'total_cost': 1.50}})):
                module._reconcile_ai_scope(
                    limit=10, time_budget_seconds=5, tenant_id=self.tenant_id,
                    draft_id='draft-verify-totals', force=True)
            after = db.get_ai_usage_summary(
                self.tenant_id, draft_id='draft-verify-totals')['totals']['cost_usd']
        self.assertAlmostEqual(float(after), 1.50)


if __name__ == '__main__':
    unittest.main()
