"""OpenRouter consumption metering per tenant, draft and presentation.

The suite uses a temporary SQLite database and never calls a provider: HTTP is
always patched, so every assertion is about this repository's own behaviour.
"""

import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db
import maps_service
import reference_analyzer


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class AiUsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'ai-usage.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Usage Co', 'usage@example.test', 'hash', 'usage-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'usage@example.test', user_id=None, user_name='Usage Admin',
            user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    # ── Storage ──────────────────────────────────────────────────────────

    def test_usage_table_exists_after_init(self):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn('ai_usage_events', names)

    def test_record_and_summarize_usage(self):
        module = self.application_module
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_id, 'google/gemini-3.8-flash', flow='slide',
                prompt_tokens=100, completion_tokens=50, total_tokens=150,
                draft_id='draft-1', presentation_id='pres-1', generation_id='gen-1')
            db.record_ai_usage_event(
                self.tenant_id, 'openai/gpt-5.6-sol', flow='designer_chat',
                prompt_tokens=200, completion_tokens=100, total_tokens=300,
                draft_id='draft-1', presentation_id='pres-1', generation_id='gen-2')
            db.record_ai_usage_event(
                self.tenant_id, 'google/gemini-3.8-flash', flow='slide',
                prompt_tokens=10, completion_tokens=5, total_tokens=15,
                draft_id='draft-other', generation_id='gen-3')
            summary = db.get_ai_usage_summary(
                self.tenant_id, draft_id='draft-1', presentation_id='pres-1')
        self.assertEqual(summary['totals']['calls'], 2)
        self.assertEqual(summary['totals']['prompt_tokens'], 300)
        self.assertEqual(summary['totals']['completion_tokens'], 150)
        self.assertEqual(summary['totals']['total_tokens'], 450)
        flows = {row['flow']: row for row in summary['by_flow']}
        self.assertEqual(flows['slide']['calls'], 1)
        self.assertEqual(flows['designer_chat']['total_tokens'], 300)
        models = {row['model'] for row in summary['by_model']}
        self.assertIn('google/gemini-3.8-flash', models)
        self.assertEqual(len(summary['recent']), 2)

    def test_cost_update_fills_pending_event(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-x', flow='market', total_tokens=42,
                generation_id='gen-cost-1')
            pending = db.get_ai_usage_pending_costs(limit=5)
            self.assertIn(event_id, [row['id'] for row in pending])
            db.update_ai_usage_cost(event_id, 0.00123)
            pending = db.get_ai_usage_pending_costs(limit=50)
            self.assertNotIn(event_id, [row['id'] for row in pending])
            summary = db.get_ai_usage_summary(self.tenant_id)
            self.assertGreaterEqual(summary['totals']['cost_usd'], 0.00123)

    # ── Capture ──────────────────────────────────────────────────────────

    def test_openrouter_chat_records_usage_from_response(self):
        module = self.application_module
        payload = {
            'id': 'gen-chat-1',
            'choices': [{'message': {'content': 'hello'}}],
            'usage': {'prompt_tokens': 11, 'completion_tokens': 22, 'total_tokens': 33},
        }
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)):
                data = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-chat',
                               'presentation_id': None, 'flow': 'slide'})
            self.assertIn('choices', data)
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-chat')
        self.assertEqual(summary['totals']['calls'], 1)
        self.assertEqual(summary['totals']['total_tokens'], 33)
        self.assertEqual(summary['recent'][0]['generation_id'], 'gen-chat-1')
        self.assertIsNone(summary['recent'][0]['cost_usd'])

    def test_openrouter_error_attempt_is_recorded_without_tokens(self):
        module = self.application_module
        with self.app.app_context():
            with patch.object(module.requests, 'post',
                              return_value=_FakeResponse({'error': {'message': 'nope'}}, 402)):
                data = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'flow': 'market'})
            self.assertIn('error', data)
            rows = db.get_ai_usage_summary(self.tenant_id)['recent']
        error_rows = [row for row in rows if row['status'] == 'error']
        self.assertTrue(error_rows)
        self.assertEqual(error_rows[0]['total_tokens'], 0)

    def test_usage_extraction_never_raises(self):
        module = self.application_module
        self.assertEqual(module._extract_openrouter_usage(None), (None, {}))
        self.assertEqual(module._extract_openrouter_usage({'id': 123}), (None, {}))
        generation_id, usage = module._extract_openrouter_usage(
            {'id': 'gen-x', 'usage': {'prompt_tokens': '7', 'completion_tokens': None}})
        self.assertEqual(generation_id, 'gen-x')
        self.assertEqual(usage['prompt_tokens'], 7)
        self.assertEqual(usage['completion_tokens'], 0)

    def test_generation_cost_parsing(self):
        module = self.application_module
        with patch.object(module.requests, 'get',
                          return_value=_FakeResponse({'data': {'total_cost': 0.0045}})):
            self.assertEqual(module._fetch_openrouter_generation_cost('gen-x'), 0.0045)
        with patch.object(module.requests, 'get',
                          return_value=_FakeResponse({'data': {}})):
            self.assertIsNone(module._fetch_openrouter_generation_cost('gen-x'))

    def test_cost_backfill_is_skipped_under_testing(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-y', total_tokens=5, generation_id='gen-skip')
            with patch.object(module, '_fetch_openrouter_generation_cost') as fetched:
                module._backfill_ai_usage_cost(event_id, 'gen-skip')
                fetched.assert_not_called()

    def test_recording_never_breaks_generation(self):
        module = self.application_module
        # Garbage in must never raise; unattributed rows are still stored as 'other'.
        self.assertIsInstance(module._record_ai_usage(None, None), str)
        self.assertIsInstance(module._record_ai_usage({'flow': 'bogus-flow!!!'}, 'm'), str)
        with self.app.app_context():
            rows = db.get_db().execute(
                'SELECT flow FROM ai_usage_events WHERE tenant_id IS NULL').fetchall()
        self.assertEqual({row['flow'] for row in rows}, {'other'})

    # ── Summary endpoint ─────────────────────────────────────────────────

    def test_reference_image_analysis_exposes_metering(self):
        module = self.application_module
        payload = {
            'id': 'gen-ref-1',
            'choices': [{'message': {'content': (
                '{"colors": {}, "design_style": "modern", "layout_type": "grid", '
                '"card_style": "flat", "header_style": "minimal", "notes": "x"}')}}],
            'usage': {'prompt_tokens': 500, 'completion_tokens': 60, 'total_tokens': 560},
        }
        image_path = os.path.join(self.temp_dir.name, 'ref.png')
        with open(image_path, 'wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\nfakepng')
        with patch.object(reference_analyzer.requests, 'post',
                          return_value=_FakeResponse(payload)):
            result, metering = reference_analyzer.analyze_reference_image(image_path, 'key')
        self.assertEqual(result['design_style'], 'modern')
        self.assertEqual(metering['generation_id'], 'gen-ref-1')
        self.assertEqual(metering['usage']['total_tokens'], 560)
        with self.app.app_context():
            module._record_ai_usage(
                {'tenant_id': self.tenant_id, 'flow': 'image', 'draft_id': 'draft-ref-meter'},
                metering['model'], 'ok', metering['usage'], metering['generation_id'])
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-ref-meter')
        self.assertEqual(summary['totals']['total_tokens'], 560)

    def test_usage_summary_endpoint_is_tenant_scoped(self):
        module = self.application_module
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_id, 'model-z', flow='slide', total_tokens=99,
                draft_id='draft-endpoint')
        client = self.app.test_client()
        with patch.object(module, '_fetch_openrouter_generation_cost', return_value=0.002):
            response = client.get('/api/ai-usage?draftId=draft-endpoint', headers=self._headers())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['usage']['totals']['calls'], 1)
        self.assertEqual(body['usage']['totals']['total_tokens'], 99)

        forbidden = client.get('/api/ai-usage?draftId=draft-endpoint')
        self.assertEqual(forbidden.status_code, 401)

    # ── Response cost first ────────────────────────────────────────────

    def test_direct_response_cost_is_saved_immediately(self):
        module = self.application_module
        payload = {
            'id': 'gen-direct-1',
            'choices': [{'message': {'content': 'hello'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
                      'cost': 0.0123},
        }
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)), \
                 patch.object(module, '_backfill_ai_usage_cost_async') as backfill:
                data = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-direct',
                               'flow': 'slide'})
            self.assertIn('choices', data)
            backfill.assert_not_called()
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-direct')
        self.assertEqual(summary['totals']['calls'], 1)
        self.assertAlmostEqual(summary['totals']['cost_usd'], 0.0123)
        row = summary['recent'][0]
        self.assertEqual(row['generation_id'], 'gen-direct-1')
        self.assertEqual(row['cost_source'], 'response')
        self.assertEqual(row['attempt_status'], 'settled')

    def test_zero_response_cost_is_valid_and_settled(self):
        module = self.application_module
        payload = {
            'id': 'gen-zero-1',
            'choices': [{'message': {'content': 'hello'}}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 5, 'total_tokens': 10, 'cost': 0},
        }
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)), \
                 patch.object(module, '_backfill_ai_usage_cost_async') as backfill:
                module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-zero', 'flow': 'slide'})
            backfill.assert_not_called()
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-zero')
        self.assertEqual(summary['recent'][0]['cost_usd'], 0)
        self.assertEqual(summary['recent'][0]['cost_source'], 'response')
        self.assertEqual(summary['recent'][0]['attempt_status'], 'settled')

    def test_missing_cost_stays_pending_not_zero(self):
        module = self.application_module
        payload = {
            'id': 'gen-missing-1',
            'choices': [{'message': {'content': 'hello'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
        }
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)):
                module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-missing', 'flow': 'slide'})
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-missing')
        self.assertIsNone(summary['recent'][0]['cost_usd'])
        self.assertEqual(summary['recent'][0]['attempt_status'], 'pending')
        self.assertEqual(summary['totals']['cost_usd'], 0)
        with self.app.app_context():
            pending = db.get_ai_usage_pending_costs(limit=50, tenant_id=self.tenant_id)
        self.assertIn(summary['recent'][0]['id'], [row['id'] for row in pending])

    def test_corrupt_cost_values_stay_unknown(self):
        module = self.application_module
        for bad in ('abc', -1, float('inf'), float('nan'), True, ''):
            cost, raw = module._parse_openrouter_cost(bad)
            self.assertIsNone(cost, bad)
            self.assertIsNone(raw, bad)
        payload = {
            'id': 'gen-bad-1',
            'choices': [{'message': {'content': 'hello'}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2, 'cost': 'abc'},
        }
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)):
                module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-bad', 'flow': 'slide'})
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-bad')
        self.assertIsNone(summary['recent'][0]['cost_usd'])
        self.assertEqual(summary['recent'][0]['attempt_status'], 'pending')

    def test_cost_is_never_estimated_from_tokens(self):
        module = self.application_module
        _id, usage = module._extract_openrouter_usage(
            {'id': 'gen-noest', 'usage': {'prompt_tokens': 1000, 'completion_tokens': 500,
                                         'total_tokens': 1500}})
        self.assertNotIn('cost_usd', usage)
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-e', flow='slide', prompt_tokens=1000,
                completion_tokens=500, total_tokens=1500, draft_id='draft-noest')
            row = db.get_db().execute(
                'SELECT cost_usd FROM ai_usage_events WHERE id = ?', (event_id,)).fetchone()
        self.assertIsNone(dict(row)['cost_usd'])

    def test_sub_detail_costs_are_not_summed(self):
        module = self.application_module
        _id, usage = module._extract_openrouter_usage(
            {'id': 'gen-sub', 'usage': {'prompt_tokens': 10, 'completion_tokens': 5,
                                       'total_tokens': 15, 'cost': 0.005,
                                       'prompt_cost': 0.003, 'completion_cost': 0.004}})
        self.assertAlmostEqual(usage['cost_usd'], 0.005)

    def test_paid_error_attempt_keeps_cost(self):
        module = self.application_module
        payload = {'error': {'message': 'billing hit'},
                   'id': 'gen-paid-err',
                   'usage': {'prompt_tokens': 20, 'completion_tokens': 0,
                             'total_tokens': 20, 'cost': 0.004}}
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload, 402)), \
                 patch.object(module, '_backfill_ai_usage_cost_async') as backfill:
                data = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-paid-err',
                               'flow': 'market'})
            self.assertIn('error', data)
            backfill.assert_not_called()
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-paid-err')
        self.assertEqual(summary['recent'][0]['status'], 'error')
        self.assertAlmostEqual(summary['recent'][0]['cost_usd'], 0.004)
        self.assertEqual(summary['recent'][0]['cost_source'], 'response')

    def test_single_row_per_attempt_for_all_outcomes(self):
        module = self.application_module
        import requests as _requests

        def _count(draft):
            with self.app.app_context():
                return int(dict(db.get_db().execute(
                    'SELECT COUNT(*) AS n FROM ai_usage_events WHERE draft_id = ?',
                    (draft,)).fetchone())['n'])

        payload = {'id': 'gen-once-1', 'choices': [{'message': {'content': 'ok'}}],
                   'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)):
                module.call_openrouter_chat('s', 'u', usage_ctx={'tenant_id': self.tenant_id,
                                                                'draft_id': 'draft-once-ok', 'flow': 'slide'})
        self.assertEqual(_count('draft-once-ok'), 1)
        with self.app.app_context():
            with patch.object(module.requests, 'post', side_effect=_requests.exceptions.Timeout()):
                module.call_openrouter_chat('s', 'u', usage_ctx={'tenant_id': self.tenant_id,
                                                                'draft_id': 'draft-once-to', 'flow': 'slide'})
        self.assertEqual(_count('draft-once-to'), 1)
        with self.app.app_context():
            row = dict(db.get_db().execute(
                'SELECT cost_usd, generation_id, attempt_status FROM ai_usage_events WHERE draft_id = ?',
                ('draft-once-to',)).fetchone())
        self.assertIsNone(row['cost_usd'])
        self.assertIsNone(row['generation_id'])
        self.assertEqual(row['attempt_status'], 'unresolved')

    def test_timeout_and_connection_record_unresolved(self):
        module = self.application_module
        import requests as _requests
        for exc in (_requests.exceptions.Timeout(), _requests.exceptions.ConnectionError('down')):
            draft = f"draft-unres-{type(exc).__name__}"
            with self.app.app_context():
                with patch.object(module.requests, 'post', side_effect=exc):
                    data = module.call_openrouter_chat(
                        's', 'u', usage_ctx={'tenant_id': self.tenant_id, 'draft_id': draft,
                                            'flow': 'slide'})
                self.assertIn('error', data)
                summary = db.get_ai_usage_summary(self.tenant_id, draft_id=draft)
            self.assertIsNone(summary['recent'][0]['cost_usd'])
            self.assertEqual(summary['recent'][0]['attempt_status'], 'unresolved')

    def test_reference_callback_records_cost_before_invalid_content(self):
        seen = {}

        def _cb(metering):
            seen.update(metering)

        payload = {'id': 'gen-refbad-1',
                   'choices': [{'message': {'content': 'not json at all'}}],
                   'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110,
                             'cost': 0.007}}
        image_path = os.path.join(self.temp_dir.name, 'ref-bad.png')
        with open(image_path, 'wb') as handle:
            handle.write(b'\x89PNG\r\n\x1a\nfakepng')
        with patch.object(reference_analyzer.requests, 'post', return_value=_FakeResponse(payload)):
            with self.assertRaises(Exception):
                reference_analyzer.analyze_reference_image(image_path, 'key', on_metering=_cb)
        self.assertEqual(seen['generation_id'], 'gen-refbad-1')
        self.assertAlmostEqual(seen['cost_usd'], 0.007)
        module = self.application_module
        with self.app.app_context():
            module._record_ai_usage(
                {'tenant_id': self.tenant_id, 'flow': 'image', 'draft_id': 'draft-refbad'},
                seen['model'], 'ok', seen['usage'], seen['generation_id'])
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-refbad')
        self.assertAlmostEqual(summary['totals']['cost_usd'], 0.007)

    def test_parallel_attempts_each_leave_one_row(self):
        module = self.application_module
        first = {'id': 'gen-par-1', 'choices': [{'message': {'content': 'first'}}],
                 'usage': {'prompt_tokens': 5, 'completion_tokens': 5, 'total_tokens': 10}}
        second = {'id': 'gen-par-2', 'choices': [{'message': {'content': 'second'}}],
                  'usage': {'prompt_tokens': 6, 'completion_tokens': 6, 'total_tokens': 12}}
        calls = [first, second]

        def _fake_post(*args, **kwargs):
            import time as _time
            payload = calls.pop(0) if calls else second
            if payload['id'] == 'gen-par-1':
                _time.sleep(0.05)
            return _FakeResponse(payload)

        with self.app.app_context():
            with patch.object(module.requests, 'post', side_effect=_fake_post):
                result = module.call_zai_chat_parallel(
                    'sys', 'hello', max_tokens=10, attempts=2,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-parallel',
                               'flow': 'slide'})
            self.assertTrue(module._has_chat_choices(result))
            import time as _time
            _time.sleep(0.3)
            rows = db.get_db().execute(
                'SELECT generation_id FROM ai_usage_events WHERE draft_id = ?',
                ('draft-parallel',)).fetchall()
        ids = {dict(r)['generation_id'] for r in rows}
        self.assertIn('gen-par-1', ids)
        self.assertIn('gen-par-2', ids)

    def test_generation_404_then_success(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-r', flow='slide', total_tokens=10,
                generation_id='gen-retry-404', draft_id='draft-retry-404')
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'error': 'not ready'}, 404)):
                result = module._reconcile_single_ai_event(event_id, 'gen-retry-404')
            self.assertFalse(result['ok'])
            self.assertEqual(result['outcome'], 'not_found')
            row = dict(db.get_db().execute(
                'SELECT cost_usd, attempt_status, reconcile_attempts FROM ai_usage_events WHERE id = ?',
                (event_id,)).fetchone())
            self.assertIsNone(row['cost_usd'])
            self.assertNotEqual(row['attempt_status'], 'settled')
            db.update_ai_usage_attempt(event_id, clear_next_retry=True)
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'data': {'id': 'gen-retry-404',
                                                                  'total_cost': 0.009}})):
                result = module._reconcile_single_ai_event(event_id, 'gen-retry-404')
            self.assertTrue(result['ok'])
            row = dict(db.get_db().execute(
                'SELECT cost_usd, cost_source, attempt_status FROM ai_usage_events WHERE id = ?',
                (event_id,)).fetchone())
            self.assertAlmostEqual(row['cost_usd'], 0.009)
            self.assertEqual(row['cost_source'], 'generation')

    def test_generation_429_keeps_pending_with_backoff(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-r', flow='slide', generation_id='gen-retry-429',
                draft_id='draft-retry-429')
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'error': 'slow down'}, 429)):
                result = module._reconcile_single_ai_event(event_id, 'gen-retry-429')
            self.assertFalse(result['ok'])
            self.assertEqual(result['outcome'], 'rate_limited')
            row = dict(db.get_db().execute(
                'SELECT cost_usd, attempt_status, next_retry_at FROM ai_usage_events WHERE id = ?',
                (event_id,)).fetchone())
            self.assertIsNone(row['cost_usd'])
            self.assertIsNotNone(row['next_retry_at'])

    def test_records_older_than_24h_stay_eligible(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-old', flow='slide', generation_id='gen-old-1',
                draft_id='draft-old')
            db.get_db().execute(
                "UPDATE ai_usage_events SET created_at = datetime('now', '-30 hours') WHERE id = ?",
                (event_id,))
            db.get_db().commit()
            pending = db.get_ai_events_needing_reconcile(limit=50, tenant_id=self.tenant_id,
                                                         draft_id='draft-old')
            self.assertIn(event_id, [row['id'] for row in pending])
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'data': {'id': 'gen-old-1',
                                                                  'total_cost': 0.003}})):
                result = module._reconcile_ai_scope(
                    limit=10, time_budget_seconds=5, tenant_id=self.tenant_id,
                    draft_id='draft-old', force=True)
            self.assertEqual(result['reconciled'], 1)

    def test_concurrent_reconcile_claim_prevents_double_work(self):
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-c', flow='slide', generation_id='gen-claim-1',
                draft_id='draft-claim')
            first = db.claim_ai_usage_reconcile_row(event_id, delay_seconds=600)
            second = db.claim_ai_usage_reconcile_row(event_id, delay_seconds=600)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_review_updates_row_without_appending_cost(self):
        module = self.application_module
        with self.app.app_context():
            event_id = db.record_ai_usage_event(
                self.tenant_id, 'model-h', flow='slide', total_tokens=20, cost_usd=0.01,
                cost_source='response', response_cost_usd=0.01, generation_id='gen-hist-1',
                draft_id='draft-hist')
            before = int(dict(db.get_db().execute(
                'SELECT COUNT(*) AS n FROM ai_usage_events WHERE draft_id = ?',
                ('draft-hist',)).fetchone())['n'])
            with patch.object(module.requests, 'get',
                              return_value=_FakeResponse({'data': {'id': 'gen-hist-1',
                                                                  'total_cost': 0.015}})):
                result = module._reconcile_single_ai_event(event_id, 'gen-hist-1', is_review=True)
            self.assertTrue(result['ok'])
            after = int(dict(db.get_db().execute(
                'SELECT COUNT(*) AS n FROM ai_usage_events WHERE draft_id = ?',
                ('draft-hist',)).fetchone())['n'])
            self.assertEqual(before, after)
            row = dict(db.get_db().execute(
                'SELECT cost_usd, cost_source, response_cost_usd, generation_cost_usd '
                'FROM ai_usage_events WHERE id = ?', (event_id,)).fetchone())
            self.assertAlmostEqual(row['cost_usd'], 0.015)
            self.assertEqual(row['cost_source'], 'review')
            self.assertAlmostEqual(row['response_cost_usd'], 0.01)
            self.assertAlmostEqual(row['generation_cost_usd'], 0.015)

    def test_truckplex_decimal_difference_is_not_float_noise(self):
        provider_total = Decimal('0.76317')
        system_total = Decimal('0.75577005')
        self.assertEqual(provider_total - system_total, Decimal('0.00739995'))
        summed = db.decimal_cost_total(['0.75577005', 0.0, None, 'invalid'])
        self.assertEqual(summed, Decimal('0.75577005'))

    def test_generation_id_mismatch_is_rejected(self):
        module = self.application_module
        with patch.object(module.requests, 'get',
                          return_value=_FakeResponse({'data': {'id': 'other-id',
                                                              'total_cost': 0.5}})):
            self.assertIsNone(module._fetch_openrouter_generation_cost('gen-expect-1'))

    def test_image_timeout_records_unresolved_attempt(self):
        module = self.application_module
        import requests as _requests
        with self.app.app_context():
            with patch.object(module.requests, 'post', side_effect=_requests.exceptions.Timeout()):
                self.assertIsNone(module.call_image_api(
                    'a villa', usage_ctx={'tenant_id': self.tenant_id,
                                          'draft_id': 'draft-img-to', 'flow': 'image'}))
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-img-to')
        self.assertEqual(summary['totals']['calls'], 1)
        self.assertIsNone(summary['recent'][0]['cost_usd'])
        self.assertEqual(summary['recent'][0]['attempt_status'], 'unresolved')

    def test_events_page_and_status_counts(self):
        with self.app.app_context():
            for index in range(5):
                db.record_ai_usage_event(
                    self.tenant_id, 'model-p', flow='slide', total_tokens=index,
                    draft_id='draft-page')
            page = db.get_ai_usage_events_page(self.tenant_id, draft_id='draft-page',
                                               page=1, page_size=2)
            self.assertEqual(page['total'], 5)
            self.assertEqual(page['pages'], 3)
            self.assertEqual(len(page['items']), 2)
            self.assertIn('generation_id', page['items'][0])
            self.assertIn('cost_source', page['items'][0])
            status = db.get_ai_usage_status_counts(self.tenant_id, draft_id='draft-page')
            self.assertEqual(status['total'], 5)
            self.assertIn(status['state'], ('pending', 'needs_review', 'settled'))
            self.assertIn(status['state_label'], ('قيد الاستكمال', 'تحتاج مطابقة', 'التكلفة المسجلة'))

    def test_reconcile_endpoint_is_scoped_and_company_protected(self):
        module = self.application_module
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_id, 'model-e2', flow='slide', generation_id='gen-ep-1',
                draft_id='draft-ep')
        client = self.app.test_client()
        denied = client.post('/api/ai-usage/reconcile', json={'draftId': 'draft-ep'})
        self.assertEqual(denied.status_code, 401)
        employee_token = auth.create_token(
            self.tenant_id, 'emp@example.test', user_id='emp-1', user_name='Emp',
            user_role='employee')
        forbidden = client.post(
            '/api/ai-usage/reconcile', json={'draftId': 'draft-ep'},
            headers={'Authorization': f'Bearer {employee_token}'})
        self.assertIn(forbidden.status_code, (403, 401))
        with patch.object(module.requests, 'get',
                          return_value=_FakeResponse({'data': {'id': 'gen-ep-1',
                                                              'total_cost': 0.011}})):
            response = client.post('/api/ai-usage/reconcile', json={'draftId': 'draft-ep'},
                                   headers=self._headers())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['checked'], 1)
        self.assertEqual(body['reconciled'], 1)

    def test_usage_events_endpoint_supports_pagination(self):
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_id, 'model-pg', flow='slide', draft_id='draft-pg-page')
        client = self.app.test_client()
        response = client.get('/api/ai-usage?draftId=draft-pg-page&page=1&pageSize=10',
                              headers=self._headers())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertIn('reconcile', body)
        self.assertIn('events', body)
        self.assertEqual(body['events']['total'], 1)
        self.assertEqual(body['events']['items'][0]['model'], 'model-pg')

    # ── Project attribution ──────────────────────────────────────────

    def test_image_generation_carries_draft_attribution(self):
        module = self.application_module
        payload = {
            'id': 'gen-img-attr-1',
            'choices': [{'message': {'content': 'ok'}}],
            'usage': {'prompt_tokens': 50, 'completion_tokens': 8000, 'total_tokens': 8050,
                      'cost': 0.028},
        }
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)):
                url = module.call_image_api(
                    'a villa', usage_ctx={'tenant_id': self.tenant_id,
                                          'draft_id': 'draft-img-attr', 'flow': 'image'})
            self.assertIsNone(url)
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-img-attr')
        self.assertEqual(summary['totals']['calls'], 1)
        self.assertAlmostEqual(summary['totals']['cost_usd'], 0.028)
        self.assertEqual(summary['recent'][0]['generation_id'], 'gen-img-attr-1')

    def test_generate_images_endpoint_attributes_project(self):
        import base64 as _b64
        module = self.application_module
        tiny_png = 'data:image/png;base64,' + _b64.b64encode(b'fakepngbytes').decode('ascii')
        payload = {
            'id': 'gen-imgs-ep-1',
            'choices': [{'message': {'images': [tiny_png]}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 2000, 'total_tokens': 2100,
                      'cost': 0.02},
        }
        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeResponse(payload)):
                client = self.app.test_client()
                response = client.post(
                    '/api/generate-images',
                    json={'draftId': 'draft-imgs-ep', 'projectData': {'draftId': 'draft-imgs-ep'},
                          'includeCover': True, 'count': 1},
                    headers=self._headers())
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()['success'])
            summary = db.get_ai_usage_summary(self.tenant_id, draft_id='draft-imgs-ep')
        self.assertGreaterEqual(summary['totals']['calls'], 1)
        self.assertGreaterEqual(summary['totals']['cost_usd'], 0.02)

    def test_market_model_call_forwards_project_scope(self):
        module = self.application_module
        seen = []
        fake = {'choices': [{'message': {'content': '{"competitors": []}'}}],
                'usage': {'prompt_tokens': 5, 'completion_tokens': 5, 'total_tokens': 10},
                'id': 'gen-mkt-attr'}

        def _fake_chat(*args, **kwargs):
            seen.append(kwargs.get('usage_ctx'))
            return dict(fake)

        with self.app.app_context():
            with patch.object(module, 'call_openrouter_chat', side_effect=_fake_chat):
                module._call_market_study_model(
                    'sys', 'user', max_tokens=2000,
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-mkt-attr',
                               'flow': 'market'})
        self.assertTrue(seen)
        self.assertEqual(seen[0].get('draft_id'), 'draft-mkt-attr')
        self.assertEqual(seen[0].get('flow'), 'market')

    def test_usage_ctx_reads_outer_and_inner_draft_ids(self):
        module = self.application_module
        ctx = module._usage_ctx('slide', {'draftId': 'd-outer',
                                          'projectData': {'draftId': 'd-inner'}})
        self.assertEqual(ctx['draft_id'], 'd-outer')
        ctx = module._usage_ctx('slide', {'projectData': {'draft_id': 'd-inner'}})
        self.assertEqual(ctx['draft_id'], 'd-inner')
        ctx = module._usage_ctx('slide', {'draftId': 'd-outer'}, presentation_id='p-1')
        self.assertEqual(ctx['presentation_id'], 'p-1')
        ctx = module._usage_ctx('slide', {'draftId': 'd-outer'}, draft_id='d-explicit')
        self.assertEqual(ctx['draft_id'], 'd-explicit')

    def test_designer_chat_attributes_draft_via_linked_presentation(self):
        module = self.application_module
        client = self.app.test_client()
        created = client.post(
            '/api/presentations',
            json={'title': 'Designer Draft Link',
                  'projectData': {'draftId': 'draft-designer-link'},
                  'slidesData': [{'title': 'Cover', 'type': 'cover',
                                  'html': '<div class="slide">Cover</div>'}],
                  'slideCount': 1},
            headers=self._headers())
        self.assertEqual(created.status_code, 201)
        presentation_id = created.get_json()['presentationId']
        seen = []

        def _fake_chat(*args, **kwargs):
            seen.append(kwargs.get('usage_ctx'))
            return {'choices': [{'message': {'content':
                '{"actions": [{"tool": "ask", "params": {"question": "أي شريحة؟"}}]}'}}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5,
                              'total_tokens': 15},
                    'id': 'gen-designer-attr'}

        with self.app.app_context():
            with patch.object(module, 'call_zai_chat', side_effect=_fake_chat):
                response = client.post(
                    '/api/designer-chat',
                    json={'message': 'غير اللون',
                          'presentationId': presentation_id,
                          'slidesData': [{'title': 'Cover', 'type': 'cover',
                                          'html': '<div class="slide">Cover</div>'}]},
                    headers=self._headers())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body.get('success'))
        self.assertTrue(seen)
        for ctx in seen:
            self.assertEqual(ctx.get('draft_id'), 'draft-designer-link')
            self.assertEqual(ctx.get('presentation_id'), presentation_id)


class MapsUsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'maps-usage.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Maps Co', 'maps@example.test', 'hash', 'maps-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'maps@example.test', user_id=None, user_name='Maps Admin',
            user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def test_maps_table_exists_after_init(self):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn('map_usage_events', names)

    def test_record_stores_units_times_price(self):
        with self.app.app_context():
            event_id = db.record_maps_usage_event(
                self.tenant_id, 'distance_matrix', 7, 0.005, flow='matrix',
                draft_id='draft-maps', presentation_id='pres-maps')
            summary = db.get_maps_usage_summary(
                self.tenant_id, draft_id='draft-maps', presentation_id='pres-maps')
        self.assertEqual(summary['totals']['calls'], 1)
        self.assertEqual(summary['totals']['units'], 7)
        self.assertAlmostEqual(summary['totals']['cost_usd'], 0.035)
        self.assertEqual(summary['by_sku'][0]['sku'], 'distance_matrix')
        self.assertEqual(summary['by_flow'][0]['flow'], 'matrix')
        self.assertEqual(summary['recent'][0]['id'], event_id)
        self.assertEqual(summary['recent'][0]['unit_price_usd'], 0.005)

    def test_scope_attributes_nested_calls(self):
        ctx = maps_service.maps_usage_ctx(
            'overview', tenant_id=self.tenant_id, draft_id='draft-scope',
            presentation_id='pres-scope')
        with self.app.app_context():
            with maps_service.maps_usage_scope(ctx):
                maps_service._record_maps_usage(None, 'staticmap', 1)
                maps_service._record_maps_usage(None, 'staticmap', 1)
            summary = db.get_maps_usage_summary(
                self.tenant_id, draft_id='draft-scope', presentation_id='pres-scope')
        self.assertEqual(summary['totals']['calls'], 2)
        self.assertEqual(summary['by_flow'][0]['flow'], 'overview')

    def test_recording_never_breaks_mapping(self):
        self.assertIsNone(maps_service._record_maps_usage(None, 'staticmap', 0))
        self.assertIsNone(maps_service._record_maps_usage(None, 'no-such-sku', -3))
        event_id = maps_service._record_maps_usage({'flow': 'bogus!!!'}, 'geocode', 1)
        self.assertIsInstance(event_id, str)

    def test_static_map_cache_hit_records_nothing(self):
        import shutil
        maps_dir = tempfile.mkdtemp()
        try:
            calls = []

            class _ImageResponse:
                status_code = 200
                content = b'fake-png-bytes'

            def _fake_get(*args, **kwargs):
                calls.append(args)
                return _ImageResponse()

            ctx = maps_service.maps_usage_ctx(
                'landmarks', tenant_id=self.tenant_id, draft_id='draft-cache')
            with self.app.app_context():
                with patch.object(maps_service, 'MAPS_DIR', maps_dir), \
                     patch.object(maps_service, '_has_api_key', return_value=True), \
                     patch.object(maps_service.requests, 'get', side_effect=_fake_get):
                    first = maps_service.get_static_map(
                        24.0, 46.0, output_path=os.path.join(maps_dir, 'o1.png'),
                        usage_ctx=ctx)
                    second = maps_service.get_static_map(
                        24.0, 46.0, output_path=os.path.join(maps_dir, 'o2.png'),
                        usage_ctx=ctx)
            self.assertTrue(first.get('success'))
            self.assertTrue(second.get('cached'))
            self.assertEqual(len(calls), 1)
            with self.app.app_context():
                summary = db.get_maps_usage_summary(self.tenant_id, draft_id='draft-cache')
            self.assertEqual(summary['totals']['calls'], 1)
            self.assertEqual(summary['recent'][0]['sku'], 'staticmap')
            self.assertEqual(
                summary['recent'][0]['unit_price_usd'],
                maps_service.MAPS_SKU_UNIT_PRICES['staticmap'])
        finally:
            shutil.rmtree(maps_dir, ignore_errors=True)

    def test_matrix_counts_elements_as_units(self):
        element = {'status': 'OK', 'distance': {'value': 1000}, 'duration': {'value': 60}}
        payload = {'status': 'OK', 'rows': [{'elements': [element, element, element]}]}
        ctx = maps_service.maps_usage_ctx(
            'matrix', tenant_id=self.tenant_id, draft_id='draft-matrix')
        with self.app.app_context():
            with patch.object(maps_service, '_has_api_key', return_value=True), \
                 patch.object(maps_service.requests, 'get',
                              return_value=_FakeResponse(payload)):
                rows = maps_service.get_drive_matrix(
                    (24.0, 46.0),
                    [{'lat': 24.1, 'lng': 46.1}, {'lat': 24.2, 'lng': 46.2},
                     {'lat': 24.3, 'lng': 46.3}],
                    usage_ctx=ctx)
            self.assertEqual(len(rows), 3)
            summary = db.get_maps_usage_summary(self.tenant_id, draft_id='draft-matrix')
        self.assertEqual(summary['totals']['units'], 3)

    def test_usage_endpoint_combines_ai_and_maps(self):
        module = self.application_module
        with self.app.app_context():
            db.record_ai_usage_event(
                self.tenant_id, 'model-z', flow='slide', total_tokens=100,
                cost_usd=0.01, draft_id='draft-combined')
            db.record_maps_usage_event(
                self.tenant_id, 'geocode', 2, 0.005, flow='site',
                draft_id='draft-combined')
        client = self.app.test_client()
        response = client.get('/api/ai-usage?draftId=draft-combined', headers=self._headers())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['success'])
        self.assertAlmostEqual(body['maps']['totals']['cost_usd'], 0.01)
        self.assertAlmostEqual(body['combined']['ai_cost_usd'], 0.01)
        self.assertAlmostEqual(body['combined']['maps_cost_usd'], 0.01)
        self.assertAlmostEqual(body['combined']['cost_usd'], 0.02)
        self.assertEqual(body['combined']['calls'], 2)


if __name__ == '__main__':
    unittest.main()
