import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db
import maps_service
from test_ai_usage import _FakeResponse


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

            def _fake_get(*args, **kwargs):
                calls.append(args)
                params = kwargs['params']
                width, height = map(int, params['size'].split('x'))
                content = io.BytesIO()
                Image.new('RGB', (width * params['scale'], height * params['scale'])).save(content, 'PNG')
                response = _ImageResponse()
                response.content = content.getvalue()
                return response

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

    def test_openrouter_stream_decodes_arabic_utf8_without_mojibake(self):
        module = self.application_module

        class _FakeStreamResponse:
            def __init__(self, sse_lines):
                self.status_code = 200
                self.headers = {'content-type': 'text/event-stream'}
                self.encoding = 'ISO-8859-1'
                self._lines = sse_lines

            def iter_lines(self, decode_unicode=False):
                if decode_unicode:
                    enc = getattr(self, 'encoding', 'utf-8') or 'utf-8'
                    for line in self._lines:
                        yield line.decode(enc)
                else:
                    yield from self._lines

            def close(self):
                pass

        arabic_text = 'عرض السعر نبذة عن المشروع'
        chunk = json.dumps({'id': 'gen-stream-ar-1', 'choices': [{'delta': {'content': arabic_text}}], 'usage': {'total_tokens': 10}})
        raw_sse = f'data: {chunk}\n\n'.encode('utf-8')

        with self.app.app_context():
            with patch.object(module.requests, 'post', return_value=_FakeStreamResponse([raw_sse])):
                result = module.call_openrouter_chat_stream(
                    'sys', 'user',
                    usage_ctx={'tenant_id': self.tenant_id, 'draft_id': 'draft-stream-ar'}
                )
        content = result['choices'][0]['message']['content']
        self.assertEqual(content, arabic_text)
        self.assertNotIn('Ø¹Ø±Ø¶', content)


if __name__ == '__main__':
    unittest.main()
