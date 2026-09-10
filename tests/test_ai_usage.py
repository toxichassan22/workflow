"""OpenRouter consumption metering per tenant, draft and presentation.

The suite uses a temporary SQLite database and never calls a provider: HTTP is
always patched, so every assertion is about this repository's own behaviour.
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
import maps_service
import reference_analyzer


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)


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
