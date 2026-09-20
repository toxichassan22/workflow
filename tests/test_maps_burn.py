"""Maps burn-down: discovery runs once per site and repeats are served from cache.

One /api/analyze-site used to fire two full 8-probe road discoveries plus
uncached landmarks, geocodes and matrix calls on every run. The suite uses a
temporary SQLite database and never calls a provider: HTTP is always patched.
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


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _ten_roads():
    names = ['طريق الملك فهد', 'طريق الأمير سلطان', 'شارع التحلية', 'طريق المدينة',
             'شارع فلسطين', 'طريق الحرمين', 'شارع الروضة', 'طريق الكورنيش',
             'شارع الأمير محمد', 'طريق مكة القديم']
    return [{'name': name, 'lat': 24.0 + i * 0.001, 'lng': 46.0 + i * 0.001,
             'distance_text': f'{i + 1} كم', 'duration_minutes': i + 1}
            for i, name in enumerate(names)]


class MapsBurnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'maps-burn.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Burn Co', 'burn@example.test', 'hash', 'burn-co')

        cls.token = auth.create_token(
            cls.tenant_id, 'burn@example.test', user_id=None, user_name='Burn Admin',
            user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def _maps_calls(self, sku=None, flow=None):
        with self.app.app_context():
            rows = db.get_db().execute(
                'SELECT sku, flow, units FROM map_usage_events WHERE tenant_id = ?',
                (self.tenant_id,)).fetchall()
        return [dict(r) for r in rows
                if (sku is None or dict(r)['sku'] == sku)
                and (flow is None or dict(r)['flow'] == flow)]

    # ── Cache ──────────────────────────────────────────────────────────

    def test_discovery_cache_table_exists_after_init(self):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn('maps_discovery_cache', names)

    def test_roads_discovery_hits_google_once_for_repeats(self):
        snaps = []
        routes = []

        def _fake_snap(lat, lng, tenant_id=None, usage_ctx=None):
            snaps.append((lat, lng))
            return {'lat': lat, 'lng': lng, 'placeId': f'p-{len(snaps)}'}

        def _fake_route(o_lat, o_lng, d_lat, d_lng, tenant_id=None, usage_ctx=None):
            routes.append((d_lat, d_lng))
            return {'coords': [(o_lat, o_lng), (d_lat, d_lng)], 'summary': 'طريق الملك فهد',
                    'distance_meters': 500, 'distance_km': 0.5, 'duration_min': 2}

        with self.app.app_context():
            with patch.object(maps_service, '_snap_to_roads', side_effect=_fake_snap), \
                    patch.object(maps_service, '_google_directions_route', side_effect=_fake_route):
                first = maps_service.discover_nearby_roads(
                    24.0, 46.0, tenant_id=self.tenant_id, max_results=6)
                snaps_after_first = len(snaps)
                second = maps_service.discover_nearby_roads(
                    24.0, 46.0, tenant_id=self.tenant_id, max_results=6)
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertEqual(snaps_after_first, 8)
        self.assertEqual(len(routes), 8)
        # Second run served from cache: no new provider calls at all.
        self.assertEqual(len(snaps), 8)

    def test_matrix_repeats_are_cached(self):
        element = {'status': 'OK', 'distance': {'value': 1000}, 'duration': {'value': 60}}
        payload = {'status': 'OK', 'rows': [{'elements': [element, element]}]}
        dests = [{'lat': 24.1, 'lng': 46.1}, {'lat': 24.2, 'lng': 46.2}]
        with self.app.app_context():
            ctx = maps_service.maps_usage_ctx(
                'matrix', tenant_id=self.tenant_id, draft_id='draft-matrix-cache')
            with patch.object(maps_service, '_has_api_key', return_value=True), \
                    patch.object(maps_service.requests, 'get',
                                 return_value=_FakeResponse(payload)) as fake_get:
                first = maps_service.get_drive_matrix((24.0, 46.0), dests, usage_ctx=ctx)
                second = maps_service.get_drive_matrix((24.0, 46.0), dests, usage_ctx=ctx)
            self.assertEqual(first, second)
            self.assertEqual(fake_get.call_count, 1)
            summary = db.get_maps_usage_summary(self.tenant_id, draft_id='draft-matrix-cache')
        self.assertEqual(summary['totals']['units'], 2)

    # ── Prices match the list ──────────────────────────────────────────

    def test_sku_prices_match_the_public_list(self):
        self.assertAlmostEqual(maps_service.MAPS_SKU_UNIT_PRICES['staticmap'], 0.002)
        self.assertAlmostEqual(maps_service.MAPS_SKU_UNIT_PRICES['distance_matrix'], 0.010)
        self.assertAlmostEqual(maps_service.MAPS_SKU_UNIT_PRICES['directions'], 0.005)
        self.assertAlmostEqual(maps_service.MAPS_SKU_UNIT_PRICES['geocode'], 0.005)
        self.assertAlmostEqual(maps_service.MAPS_SKU_UNIT_PRICES['roads'], 0.01)

    # ── One discovery per analysis ─────────────────────────────────────

    def test_analyze_site_runs_a_single_road_discovery(self):
        module = self.application_module
        client = self.app.test_client()
        with patch.object(module.maps_service, 'get_nearby_landmarks',
                          return_value={'success': True, 'landmarks': []}), \
                patch.object(module.maps_service, 'get_drive_matrix', return_value=[]), \
                patch.object(module.maps_service, 'discover_nearby_roads',
                             return_value=_ten_roads()) as discover, \
                patch.object(module.maps_service, '_fetch_osm_polygon', return_value=None), \
                patch.object(module.maps_service, 'detect_curated_city', return_value=None), \
                patch.object(module.maps_service, 'get_curated_city_landmarks', return_value=[]), \
                patch.object(module.maps_service, 'get_nearest_category_landmarks', return_value=[]), \
                patch.object(module.maps_service, 'reverse_geocode_location', return_value={}), \
                patch.object(module.population_service, 'get_population_density',
                             return_value={'available': False}):
            response = client.post('/api/analyze-site', headers=self._headers(), json={
                'projectData': {'location_lat': '24.0', 'location_lng': '46.0',
                                'location_address': 'https://www.google.com/maps/@24.0,46.0,17z'}
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(discover.call_count, 1)
        fields = response.get_json()['fields']
        self.assertIn('طريق الملك فهد', fields['main_roads'])
        self.assertNotIn('secondary_roads', fields)

    def test_usage_response_carries_sku_prices(self):
        client = self.app.test_client()
        body = client.get('/api/ai-usage', headers=self._headers()).get_json()
        self.assertTrue(body['success'])
        self.assertAlmostEqual(body['mapsSkuPrices']['staticmap'], 0.002)

    # ── Every enrichment caller must open a usage scope ────────────────
    # Without maps_usage_scope the Places/Matrix calls inside
    # _collect_site_fields record tenant_id=NULL rows that
    # bill_unbilled_usage can never claim — provider spend nobody pays for.

    def test_site_analysis_enrichment_is_metered(self):
        module = self.application_module
        client = self.app.test_client()
        captured = {}

        def fake_collect(project_data, tenant_id, lat, lng):
            captured['ctx'] = maps_service._current_maps_ctx()
            return ({'location_detail': 'عنوان الموقع'}, [], [], [], [], [], None, {})

        with patch.object(module, '_collect_site_fields', side_effect=fake_collect), \
                patch.object(module, 'call_zai_chat', return_value={
                    'choices': [{'message': {'content': 'تحليل'}}]
                }):
            response = client.post('/api/site-analysis', headers=self._headers(), json={
                'projectData': {'location_lat': '24.0', 'location_lng': '46.0'},
                'draftId': 'draft-metered',
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(captured['ctx'].get('tenant_id'), self.tenant_id)
        self.assertEqual(captured['ctx'].get('draft_id'), 'draft-metered')
        self.assertEqual(captured['ctx'].get('flow'), 'site')

    def test_land_analysis_map_context_is_metered(self):
        module = self.application_module
        captured = {}

        def fake_collect(context, tenant_id, lat, lng):
            captured['ctx'] = maps_service._current_maps_ctx()
            return ({'location_detail': 'عنوان الموقع'}, [], [], [], [], [], None, {})

        with self.app.app_context(), \
                patch.object(module, '_collect_site_fields', side_effect=fake_collect):
            module.build_land_analysis_site_context(
                {'includeMapContext': True, 'draftId': 'draft-croquis',
                 'locationAddress': 'https://www.google.com/maps/@24,46,17z'},
                self.tenant_id, 24, 46)
        self.assertEqual(captured['ctx'].get('tenant_id'), self.tenant_id)
        self.assertEqual(captured['ctx'].get('draft_id'), 'draft-croquis')
        self.assertEqual(captured['ctx'].get('flow'), 'site')


if __name__ == '__main__':
    unittest.main()
