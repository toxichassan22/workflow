"""Regression checks for the meeting requirements implemented in this change.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import os
import sys
import tempfile
import json
import unittest
import io
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class MeetingRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'meeting-requirements.db')

        # Import only after redirecting DB_PATH: app.py initializes its database at import time.
        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        # Training-image bytes written by this suite stay in the temporary folder.
        cls.application_module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')

        with cls.app.app_context():
            cls.tenant_a = db.create_tenant('Company A', 'a@example.test', 'hash-a', 'company-a')
            cls.tenant_b = db.create_tenant('Company B', 'b@example.test', 'hash-b', 'company-b')

        cls.token_a = auth.create_token(
            cls.tenant_a, 'a@example.test', user_id=None, user_name='Company A', user_role='company_admin'
        )
        cls.token_b = auth.create_token(
            cls.tenant_b, 'b@example.test', user_id=None, user_name='Company B', user_role='company_admin'
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def _headers(token):
        return {'Authorization': f'Bearer {token}'}

    def test_map_zoom_caps_overview_and_preserves_context(self):
        zooms = self.application_module.maps_service._calculate_map_zooms([
            (21.63200, 39.10500),
            (21.63201, 39.10501),
            (21.63200, 39.10501),
        ])

        self.assertLessEqual(zooms['overview'], 17)
        self.assertEqual(zooms['landmarks'], max(14, zooms['overview'] - 1))
        self.assertEqual(zooms['access'], max(15, zooms['overview'] + 1))

    def test_google_places_errors_are_explicit_instead_of_empty_success(self):
        response = Mock(status_code=403)
        response.json.return_value = {
            'error': {'status': 'PERMISSION_DENIED', 'message': 'Places API (New) is not enabled'}
        }
        with patch.object(self.application_module.maps_service.requests, 'post', return_value=response):
            result = self.application_module.maps_service.get_nearby_landmarks(24.0, 46.0)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'GOOGLE_PLACES_HTTP_ERROR')
        self.assertIn('Places API (New) is not enabled', result['error'])

    def test_preview_map_data_surfaces_google_places_errors(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'get_nearby_landmarks', return_value={
            'success': False,
            'error': 'Google Places API HTTP 403: Places API (New) is not enabled',
            'error_code': 'GOOGLE_PLACES_HTTP_ERROR',
        }):
            response = client.post('/api/preview-map-data', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0}
            })

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['error_code'], 'NEARBY_LANDMARKS_UNAVAILABLE')
        self.assertIn('Places API (New) is not enabled', response.get_json()['error'])

    def test_nearest_category_landmarks_return_real_names(self):
        places = [
            {'name': 'مول حقيقي', 'types': ['shopping_mall'], 'lat': 24.01, 'lng': 46.01, 'distance_meters': 1000},
            {'name': 'جامعة حقيقية', 'types': ['university'], 'lat': 24.02, 'lng': 46.02, 'distance_meters': 2000},
            {'name': 'مستشفى حقيقي', 'types': ['hospital'], 'lat': 24.03, 'lng': 46.03, 'distance_meters': 3000},
        ]
        with patch.object(self.application_module.maps_service, 'get_nearby_landmarks', return_value={
            'success': True, 'landmarks': places
        }), patch.object(self.application_module.maps_service, 'get_drive_matrix', return_value=[
            {'distance_km': 1.0, 'distance_text': '1 كم', 'duration_min': 3},
            {'distance_km': 2.0, 'distance_text': '2 كم', 'duration_min': 5},
            {'distance_km': 3.0, 'distance_text': '3 كم', 'duration_min': 7},
        ]):
            result = self.application_module.maps_service.get_nearest_category_landmarks(24.0, 46.0)

        self.assertEqual([item['name'] for item in result], ['مول حقيقي', 'جامعة حقيقية', 'مستشفى حقيقي'])
        self.assertEqual([item['category'] for item in result], ['التسوق', 'التعليم', 'الصحة'])
        self.assertEqual(result[1]['duration_minutes'], 5)

    def test_fresh_database_has_meeting_columns(self):
        """Fresh initialization no longer executes multiple DDL statements incorrectly."""
        with self.app.app_context():
            conn = db.get_db()
            training_columns = {row['name'] for row in conn.execute('PRAGMA table_info(tenant_training_data)')}
            draft_columns = {row['name'] for row in conn.execute('PRAGMA table_info(project_drafts)')}
        self.assertTrue({'image_type', 'image_description'}.issubset(training_columns))
        self.assertTrue({'requested_by', 'reviewed_by', 'review_note', 'reviewed_at'}.issubset(draft_columns))

    def test_single_slide_generation_uses_tenant_logo_immediately(self):
        """A freshly generated slide must not be finalized with the system logo."""
        logo_path = f'/tenant-assets/{self.tenant_a}/logo'
        with self.app.app_context():
            db.update_branding(self.tenant_a, logo_path=logo_path)

        generated_html = (
            '<div class="slide" style="width:1280px;height:720px;position:relative;">'
            '<img src="##LOGO##">'
            '</div>'
        )
        client = self.app.test_client()
        with patch.object(self.application_module.slide_engine, 'generate_single_slide', return_value=generated_html), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={}):
            response = client.post('/api/generate-slide-single', headers=self._headers(self.token_a), json={
                'projectData': {},
                'slidePlan': {'slides': [{'title': 'غلاف', 'type': 'cover'}]},
                'slideIndex': 0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        html = response.get_json()['slide']['html']
        self.assertIn(logo_path + '?t=1', html)
        self.assertNotIn('/assets/logo.png', html)

    def test_local_generated_image_reference_is_embedded_for_moodboard_generation(self):
        """Generated cover URLs must be converted before the vision request uses them."""
        response = Mock(status_code=200)
        response.json.return_value = {
            'choices': [{'message': {'images': [{'image_url': {'url': 'data:image/png;base64,result'}}]}}]
        }
        with patch.object(self.application_module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(self.application_module.requests, 'post', return_value=response) as request_post, \
                patch.object(self.application_module.os.path, 'isfile', return_value=True), \
                patch.object(self.application_module.os.path, 'getsize', return_value=3), \
                patch('builtins.open', mock_open(read_data=b'abc')):
            result = self.application_module.call_image_api_with_reference(
                '/uploads/creative/tenant-a/cover.png?t=1', 'moodboard prompt'
            )

        self.assertEqual(result, 'data:image/png;base64,result')
        request_payload = request_post.call_args.kwargs['json']
        reference_url = request_payload['messages'][0]['content'][1]['image_url']['url']
        self.assertEqual(reference_url, 'data:image/png;base64,YWJj')

    def test_osm_boundary_ignores_landuse_and_selects_containing_building(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'elements': [
                {
                    'type': 'way',
                    'tags': {'landuse': 'industrial'},
                    'geometry': [
                        {'lat': 24.0, 'lon': 46.0},
                        {'lat': 24.0, 'lon': 46.01},
                        {'lat': 24.01, 'lon': 46.01},
                        {'lat': 24.01, 'lon': 46.0},
                    ],
                },
                {
                    'type': 'way',
                    'tags': {'building': 'commercial'},
                    'geometry': [
                        {'lat': 23.9998, 'lon': 45.9998},
                        {'lat': 23.9998, 'lon': 46.0002},
                        {'lat': 24.0002, 'lon': 46.0002},
                        {'lat': 24.0002, 'lon': 45.9998},
                    ],
                },
            ]
        }
        with patch.object(self.application_module.maps_service.requests, 'post', return_value=response):
            coords = self.application_module.maps_service._fetch_osm_polygon(24.0, 46.0)

        self.assertEqual(len(coords), 4)
        self.assertLess(self.application_module.maps_service._approx_polygon_area_sqm(coords), 100000)

    def test_osm_boundary_returns_none_without_building_footprint(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            'elements': [{
                'type': 'way',
                'tags': {'landuse': 'commercial'},
                'geometry': [
                    {'lat': 24.0, 'lon': 46.0},
                    {'lat': 24.0, 'lon': 46.01},
                    {'lat': 24.01, 'lon': 46.01},
                ],
            }]
        }
        with patch.object(self.application_module.maps_service.requests, 'post', return_value=response):
            coords = self.application_module.maps_service._fetch_osm_polygon(24.0, 46.0)

        self.assertIsNone(coords)

    def test_site_analysis_can_defer_map_generation(self):
        client = self.app.test_client()
        fields = {'location_lat': 25.1, 'location_lng': 47.6, 'nearby_landmarks': 'معلم'}
        with patch.object(self.application_module.maps_service, 'extract_coords_from_maps_link', return_value={'lat': 25.1, 'lng': 47.6}), \
                patch.object(self.application_module, '_collect_site_fields', return_value=(fields, [], [], [], [], [], None, {})), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post('/api/analyze-site', headers=self._headers(self.token_a), json={
                'projectData': {'location_address': 'https://www.google.com/maps/@25.1,47.6,17z'},
                'generateMaps': False,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['mapsDeferred'])
        generate_maps.assert_not_called()

    def test_site_analysis_prefers_google_link_over_stale_coordinates(self):
        client = self.app.test_client()
        map_result = {'placeholders': {}, 'zooms': {'overview': 17}}
        with patch.object(self.application_module.maps_service, 'extract_coords_from_maps_link', return_value={'lat': 25.123456, 'lng': 47.654321}), \
                patch.object(self.application_module.maps_service, 'get_nearby_landmarks', return_value={'success': True, 'landmarks': []}), \
                patch.object(self.application_module.maps_service, 'get_drive_matrix', return_value=[]), \
                patch.object(self.application_module.maps_service, 'discover_nearby_roads', return_value=[]), \
                patch.object(self.application_module.maps_service, '_fetch_osm_polygon', return_value=None), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value=map_result) as generate_maps:
            response = client.post('/api/analyze-site', headers=self._headers(self.token_a), json={
                'projectData': {
                    'location_lat': '24.000000',
                    'location_lng': '46.000000',
                    'location_address': 'https://www.google.com/maps/@25.123456,47.654321,17z'
                },
                'generateMaps': True,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload['fields']['location_lat'], 25.123456)
        self.assertEqual(payload['fields']['location_lng'], 47.654321)
        generated_project = generate_maps.call_args.args[0]
        self.assertEqual(generated_project['location_lat'], 25.123456)
        self.assertEqual(generated_project['location_lng'], 47.654321)

    def test_saved_map_assets_hydrate_by_draft_id(self):
        map_file = tempfile.NamedTemporaryFile(dir=ROOT, suffix='.png', delete=False)
        map_path = map_file.name
        self.addCleanup(lambda: os.path.exists(map_path) and os.unlink(map_path))
        map_file.write(b'png')
        map_file.close()
        with self.app.app_context():
            db.add_map_image(
                self.tenant_a,
                'overview',
                map_path,
                '##MAP_OVERVIEW##',
                presentation_id='draft_draft-map',
                metadata={
                    'lat': 24.1,
                    'lng': 46.2,
                    'zoom': 17,
                    'map_highlight_version': self.application_module.maps_service.MAP_HIGHLIGHT_RENDER_VERSION,
                }
            )
            hydrated = self.application_module._merge_persisted_map_assets(
                {'project_name': 'Saved'}, self.tenant_a, draft_id='draft-map'
            )
        self.assertEqual(os.path.basename(hydrated['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##']), os.path.basename(map_path))
        self.assertEqual(hydrated['tenantCreativeImages']['map_lat'], 24.1)
        self.assertEqual(hydrated['tenantCreativeImages']['map_lng'], 46.2)

    def test_full_map_generation_always_requests_all_four_views(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={
            'placeholders': {}, 'landmarks': [], 'landmarks_matrix': [], 'zooms': {}
        }) as generate_maps:
            response = client.post('/api/generate-map-images', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'maps-draft'}
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        generated_project = generate_maps.call_args.args[0]
        self.assertEqual(generated_project['enabled_maps'], ['overview', 'landmarks', 'access', 'catchment'])

    def test_presentation_map_regeneration_uses_current_project_data(self):
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant_a,
                'Old location',
                project_data={
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'tenantCreativeImages': {
                        'map_placeholders': {'##MAP_OVERVIEW##': '/old-map.png'},
                        'map_zooms': {'overview': 17},
                        'maps_persisted': True,
                    },
                },
                slides_data=[],
            )
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={
            'placeholders': {}, 'landmarks': [], 'landmarks_matrix': [], 'zooms': {}, 'lat': 25.0, 'lng': 47.0
        }) as generate_maps:
            response = client.post(
                f'/api/presentations/{pres_id}/regenerate-maps',
                headers=self._headers(self.token_a),
                json={'projectData': {'location_lat': 25.0, 'location_lng': 47.0}}
            )

        self.assertEqual(response.status_code, 200, response.get_json())
        generated_project = generate_maps.call_args.args[0]
        self.assertEqual(generated_project['location_lat'], 25.0)
        self.assertEqual(generated_project['location_lng'], 47.0)
        with self.app.app_context():
            stored = db.get_presentation(pres_id, tenant_id=self.tenant_a)
        stored_data = json.loads(stored['project_data'])
        self.assertEqual(stored_data['location_lat'], 25.0)
        self.assertEqual(stored_data['tenantCreativeImages']['map_placeholders'], {})

    def test_site_analysis_fills_google_site_fields_without_touching_unknown_fields(self):
        client = self.app.test_client()
        nearby = [{'name': 'معلم قريب', 'lat': 24.001, 'lng': 46.001, 'distance_text': '1 كم'}]
        city = [{'name': 'معلم المدينة', 'lat': 24.02, 'lng': 46.02}]
        with patch.object(self.application_module.maps_service, 'get_nearby_landmarks', side_effect=lambda *args, **kwargs: {'success': True, 'landmarks': nearby if kwargs.get('radius') == 20000 else city}), \
                patch.object(self.application_module.maps_service, 'get_drive_matrix', return_value=[{'distance_text': '1.2 كم', 'duration_min': 5}]), \
                patch.object(self.application_module.maps_service, 'discover_nearby_roads', return_value=[{'name': 'طريق تجريبي', 'lat': 24.0, 'lng': 46.0}]), \
                patch.object(self.application_module.maps_service, '_fetch_osm_polygon', return_value=[(23.999, 45.999), (23.999, 46.001), (24.001, 46.001), (24.001, 45.999)]), \
                patch.object(self.application_module.maps_service, 'detect_curated_city', return_value=None), \
                patch.object(self.application_module.maps_service, 'get_curated_city_landmarks', return_value=[]), \
                patch.object(self.application_module.maps_service, 'get_nearest_category_landmarks', return_value=[]), \
                patch.object(self.application_module.maps_service, 'reverse_geocode_location', return_value={'formatted_address': 'Riyadh, Saudi Arabia'}), \
                patch.object(self.application_module.population_service, 'get_population_density', return_value={'available': False}), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={'placeholders': {}, 'zooms': {'overview': 17}}):
            response = client.post('/api/analyze-site', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': '24.0', 'location_lng': '46.0', 'location_address': 'https://www.google.com/maps/@24.0,46.0,17z'}
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        fields = response.get_json()['fields']
        self.assertEqual(fields['main_roads'], 'طريق تجريبي')
        self.assertIn('معلم قريب', fields['nearby_landmarks'])
        self.assertIn('1.2 كم', fields['nearby_landmarks'])
        self.assertIn('5 دقيقة', fields['nearby_landmarks'])
        self.assertIn('معلم المدينة', fields['city_landmarks'])
        self.assertIn('location_polygon', fields)
        self.assertEqual(fields['location_polygon_source'], 'auto')
        self.assertNotIn('land_area', fields)

    def test_slide_plan_falls_back_when_ai_provider_is_unavailable(self):
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat_parallel', side_effect=RuntimeError('AI unavailable')):
            response = client.post('/api/slide-plan', headers=self._headers(self.token_a), json={
                'projectData': {'project_name': 'مشروع تجريبي', 'project_type': 'سكني'}
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])
        self.assertTrue(response.get_json()['plan']['slides'])

    def test_site_analysis_endpoint_returns_ai_text_without_large_creative_payload(self):
        client = self.app.test_client()
        enriched = {
            'location_detail': 'Riyadh, Saudi Arabia',
            'main_roads': 'شارع تجريبي رئيسي',
            'secondary_roads': 'شارع فرعي قريب - 1 كم',
            'nearby_landmarks': 'معلم قريب — تعليمي — 5 كم — 8 دقائق',
            'city_landmarks': 'معالم مدينة جدة',
            'population_density': '4500 نسمة/كم²',
        }
        with patch.object(self.application_module, '_collect_site_fields', return_value=(enriched, [], [], [], [], [], None)), \
                patch.object(self.application_module, 'call_zai_chat', return_value={
            'choices': [{'message': {'content': 'تحليل عربي مختصر للموقع'}}]
        }) as call_ai:
            response = client.post('/api/site-analysis', headers=self._headers(self.token_a), json={
                'projectData': {
                    'location_lat': 24.0,
                    'location_lng': 46.0,
                    'project_idea': 'فندق بوتيك لرجال الأعمال والسياح',
                    'nearby_landmarks': 'معلم قريب — تعليمي — 5 كم — 8 دقائق',
                    'tenantCreativeImages': {'cover': 'data:image/png;base64,' + ('A' * 20000)},
                }
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['analysis'], 'تحليل عربي مختصر للموقع')
        self.assertEqual(response.get_json()['fields']['population_density'], '4500 نسمة/كم²')
        self.assertEqual(response.get_json()['fields']['main_roads'], 'شارع تجريبي رئيسي')
        prompt = call_ai.call_args.args[1]
        self.assertNotIn('tenantCreativeImages', prompt)
        self.assertIn('معلم قريب', prompt)
        self.assertIn('فندق بوتيك', prompt)
        self.assertIn('4500 نسمة/كم²', prompt)
        self.assertIn('شارع تجريبي رئيسي', prompt)
        self.assertIn('الكثافة السكانية', prompt)
        self.assertIn('البنية التحتية', prompt)
        self.assertIn('فرص الاستثمار', prompt)
        self.assertIn('المعالم القريبة ومعالم المدينة', prompt)

    def test_site_analysis_falls_back_to_openrouter_when_primary_ai_response_fails(self):
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat', side_effect=RuntimeError('primary AI unavailable')), \
                patch.object(self.application_module, 'OPENROUTER_KEY', 'test-openrouter-key'), \
                patch.object(self.application_module, 'call_openrouter_chat', return_value={
                    'choices': [{'message': {'content': 'تحليل من النموذج الاحتياطي'}}]
                }) as fallback:
            response = client.post('/api/site-analysis', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0}
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['analysis'], 'تحليل من النموذج الاحتياطي')
        self.assertEqual(fallback.call_args.kwargs['model'], 'google/gemini-2.5-flash')

    def test_project_draft_preserves_selected_landmark_details(self):
        client = self.app.test_client()
        details = [{
            'name': 'معلم مختار', 'category': 'تعليمي', 'lat': 24.01, 'lng': 46.01,
            'distance_km': 4.2, 'duration_minutes': 7,
        }]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {
                'nearby_landmarks': 'معلم مختار — تعليمي — 4.2 كم — 7 دقائق',
                'nearby_landmarks_data': details,
            }
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        loaded = client.get('/api/project-draft', headers=self._headers(self.token_a))
        self.assertEqual(loaded.status_code, 200, loaded.get_json())
        self.assertEqual(loaded.get_json()['draft']['draft_data']['nearby_landmarks_data'], details)

    def test_custom_sections_can_be_renamed_and_fields_require_a_tenant_section(self):
        client = self.app.test_client()
        headers_a = self._headers(self.token_a)

        created = client.post('/api/field-sections/custom', headers=headers_a, json={
            'key': 'brand_references', 'label': 'Brand references'
        })
        self.assertEqual(created.status_code, 201)

        renamed = client.put('/api/field-sections/custom/brand_references', headers=headers_a, json={
            'label': 'Brand standards'
        })
        self.assertEqual(renamed.status_code, 200)
        available = client.get('/api/field-sections', headers=headers_a).get_json()['available']
        custom_section = next(section for section in available if section['key'] == 'brand_references')
        self.assertEqual(custom_section['label'], 'Brand standards')

        invalid_create = client.post('/api/fields', headers=headers_a, json={
            'fieldKey': 'invalid_section_field', 'fieldLabel': 'Invalid section field',
            'sectionKey': 'not_a_company_section'
        })
        self.assertEqual(invalid_create.status_code, 400)

        valid_create = client.post('/api/fields', headers=headers_a, json={
            'fieldKey': 'brand_standard_note', 'fieldLabel': 'Brand standard note',
            'sectionKey': 'brand_references'
        })
        self.assertEqual(valid_create.status_code, 201)
        field_id = valid_create.get_json()['fieldId']

        # A section from Company A cannot be used by Company B or assigned to
        # an existing field as an arbitrary key.
        cross_tenant = client.post('/api/fields', headers=self._headers(self.token_b), json={
            'fieldKey': 'cross_tenant_section_field', 'fieldLabel': 'Cross-tenant section field',
            'sectionKey': 'brand_references'
        })
        self.assertEqual(cross_tenant.status_code, 400)
        invalid_update = client.put('/api/fields/' + field_id, headers=headers_a, json={
            'sectionKey': 'not_a_company_section'
        })
        self.assertEqual(invalid_update.status_code, 400)

        missing_rename = client.put('/api/field-sections/custom/not_real', headers=headers_a, json={
            'label': 'No section'
        })
        self.assertEqual(missing_rename.status_code, 404)

    def test_company_admin_draft_preserves_sections_and_approval_state(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)

        saved = client.post('/api/project-draft', headers=headers, json={
            'draftData': {'project_name': 'Test project'}, 'sectionStatuses': {}, 'status': 'draft'
        })
        self.assertEqual(saved.status_code, 200)

        section = client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionKey': 'basic', 'sectionStatus': 'approved'
        })
        self.assertEqual(section.status_code, 200)

        # Legacy autosaves send {}; this must not erase the per-section decision.
        resaved = client.post('/api/project-draft', headers=headers, json={
            'draftData': {'project_name': 'Test project updated'}, 'sectionStatuses': {}, 'status': 'draft'
        })
        self.assertEqual(resaved.status_code, 200)
        draft = client.get('/api/project-draft', headers=headers).get_json()['draft']
        self.assertEqual(draft['section_statuses'], {'basic': 'approved'})

        request_approval = client.post('/api/project-draft/request-approval', headers=headers, json={})
        self.assertEqual(request_approval.status_code, 200)
        draft_id = request_approval.get_json()['draft']['id']

        review = client.post('/api/project-draft/review', headers=headers, json={
            'draftId': draft_id, 'status': 'approved', 'note': 'Reviewed in test'
        })
        self.assertEqual(review.status_code, 200)
        approved = client.get('/api/project-draft/approval-status', headers=headers).get_json()['approval']
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['review_note'], 'Reviewed in test')

        # Editing a previously approved section returns the unified draft to draft state.
        returned = client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionKey': 'basic', 'sectionStatus': 'draft'
        })
        self.assertEqual(returned.status_code, 200)
        current = client.get('/api/project-draft', headers=headers).get_json()['draft']
        self.assertEqual(current['status'], 'draft')

    def test_training_entries_are_tenant_isolated_and_not_public_uploads(self):
        client = self.app.test_client()
        created = client.post('/api/training', headers=self._headers(self.token_a), json={
            'title': 'Tenant A reference', 'content': 'Private design instruction', 'category': 'reference'
        })
        self.assertEqual(created.status_code, 201)
        entry_id = created.get_json()['entryId']

        other_update = client.put('/api/training/' + entry_id, headers=self._headers(self.token_b), json={'is_active': False})
        other_delete = client.delete('/api/training/' + entry_id, headers=self._headers(self.token_b))
        self.assertEqual(other_update.status_code, 404)
        self.assertEqual(other_delete.status_code, 404)

        own_entry = client.get('/api/training', headers=self._headers(self.token_a)).get_json()['entries'][0]
        self.assertEqual(own_entry['is_active'], 1)
        self.assertNotIn('image_path', own_entry)
        self.assertEqual(client.get('/uploads/training/unknown.png').status_code, 404)

    def test_uploaded_training_image_requires_consent_and_tenant_authentication(self):
        client = self.app.test_client()
        # Valid 1x1 PNG, kept inline so the test does not need network or fixtures.
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        original_key = self.application_module.OPENROUTER_KEY
        self.application_module.OPENROUTER_KEY = None
        try:
            denied = client.post('/api/training/upload-image', headers=self._headers(self.token_a), data={
                'image': (io.BytesIO(png_bytes), 'reference.png'), 'imageType': 'reference'
            }, content_type='multipart/form-data')
            self.assertEqual(denied.status_code, 400)

            uploaded = client.post('/api/training/upload-image', headers=self._headers(self.token_a), data={
                'image': (io.BytesIO(png_bytes), 'reference.png'),
                'imageType': 'reference',
                'description': 'Private tenant reference',
                'companyDataConsent': 'true',
            }, content_type='multipart/form-data')
        finally:
            self.application_module.OPENROUTER_KEY = original_key

        self.assertEqual(uploaded.status_code, 200)
        image_url = uploaded.get_json()['imagePath']
        own_image = client.get(image_url, headers=self._headers(self.token_a))
        self.assertEqual(own_image.status_code, 200)
        own_image.close()
        self.assertEqual(client.get(image_url, headers=self._headers(self.token_b)).status_code, 404)

    def test_icons_and_non_google_router_are_absent_from_output_paths(self):
        from slide_engine import postprocess_slide

        html = '<div class="slide"><svg><path /></svg><span class="icon">x</span>🏗️ محتوى</div>'
        rendered = postprocess_slide(html, 'content')
        self.assertNotIn('<svg', rendered.lower())
        self.assertNotIn('class="icon"', rendered.lower())
        self.assertNotIn('🏗', rendered)

        maps_source = Path('maps_service.py').read_text(encoding='utf-8')
        self.assertNotIn('router.project-osrm.org', maps_source)
        self.assertIn('maps.googleapis.com/maps/api/directions/json', maps_source)


if __name__ == '__main__':
    unittest.main()
