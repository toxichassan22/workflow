"""Regression checks for the meeting requirements implemented in this change.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import os
import re
import sys
import tempfile
import json
import time
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

        # 503, not 502: the edge fabricates its own 502s, so the app must stay out of that status.
        self.assertEqual(response.status_code, 503)
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

    def test_pdf_documents_are_rendered_to_vision_images_without_text_extraction(self):
        import fitz
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), 'Visual table sample')
        pdf_data = document.tobytes()
        document.close()
        data_uri = 'data:application/pdf;base64,' + __import__('base64').b64encode(pdf_data).decode('ascii')
        parts, warnings, page_count, mode = self.application_module._prepare_document_vision_parts({
            'filename': 'scan.pdf', 'mimeType': 'application/pdf', 'fileData': data_uri
        })
        self.assertEqual(page_count, 1)
        self.assertEqual(warnings, [])
        self.assertEqual(mode, 'pdf_rendered')
        self.assertTrue(any(part.get('type') == 'image_url' for part in parts))
        self.assertFalse(any(part.get('type') == 'file' for part in parts))
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn('أُرسل الملف الأصلي كحل احتياطي', app_source)
        self.assertIn('finish_reason == \'length\'', app_source)
        self.assertIn('_detect_scan_rotation', app_source)
        self.assertIn('PDF_VISION_TILE_MAX_EDGE', app_source)
        self.assertIn('extraction_diagnostics', app_source)
        # The cap is negotiated in _call_land_analysis_model: too low truncates the JSON, too high
        # is refused outright because the provider reserves max_tokens against the balance.
        self.assertIn('_call_land_analysis_model(\n', app_source)
        self.assertIn('LAND_ANALYSIS_MAX_TOKENS)', app_source)

    def test_pdf_scan_orientation_adds_high_resolution_table_tiles(self):
        import base64
        import fitz
        from PIL import Image, ImageDraw

        source = Image.new('RGB', (800, 1000), 'white')
        painter = ImageDraw.Draw(source)
        for y in range(80, 900, 70):
            painter.line((40, y, 760, y), fill='black', width=2)
            painter.line((40, y + 28, 760, y + 28), fill='black', width=1)
        sideways = source.rotate(90, expand=True)
        image_buffer = io.BytesIO()
        sideways.save(image_buffer, format='PNG')
        document = fitz.open()
        page = document.new_page(width=sideways.width, height=sideways.height)
        page.insert_image(page.rect, stream=image_buffer.getvalue())
        pdf_data = document.tobytes()
        document.close()
        data_uri = 'data:application/pdf;base64,' + base64.b64encode(pdf_data).decode('ascii')

        diagnostics = {}
        parts, warnings, page_count, mode = self.application_module._prepare_document_vision_parts(
            {'filename': 'rotated-scan.pdf', 'mimeType': 'application/pdf', 'fileData': data_uri},
            budget=8 * 1024 * 1024,
            diagnostics=diagnostics,
        )

        self.assertEqual((page_count, mode), (1, 'pdf_rendered'))
        self.assertEqual(diagnostics['rotated_page_count'], 1)
        self.assertGreater(diagnostics['tile_count'], 0)
        self.assertTrue(any('تم تصحيح اتجاه' in warning for warning in warnings))
        self.assertTrue(any('قصاصة مكبرة' in part.get('text', '') for part in parts if part.get('type') == 'text'))

    def test_land_normalizer_accepts_regulation_coordinate_and_direction_aliases(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-2',
                'directions': [{'direction': 'الشمال', 'regulation_text': 'بطول 80 م يحده شارع'}],
                'regulation_coordinates': [{
                    'point_number': 1,
                    'الشرقيات': '511085,849',
                    'الشماليات': '2392264,840',
                }],
            }],
        })

        parcel = result['parcels'][0]
        self.assertEqual(parcel['directions']['north']['regulation_text'], 'بطول 80 م يحده شارع')
        self.assertEqual(result['survey_coordinates'][0]['eastings'], '511085,849')
        self.assertEqual(result['survey_coordinates'][0]['northings'], '2392264,840')
        self.assertEqual(result['survey_coordinates'][0]['source'], 'regulation_table')

        mixed = self.application_module._normalize_land_document_result({
            'survey_coordinates': [
                {'point': '1 (إحداثيات الموقع)', 'eastings': '511072.703', 'northings': '2392261.792'},
                {'point': '1 (إحداثيات التنظيم)', 'eastings': '511085.849', 'northings': '2392264.840'},
            ]
        })
        self.assertEqual(len(mixed['survey_coordinates']), 1)
        self.assertEqual(mixed['survey_coordinates'][0]['point'], '1')
        self.assertEqual(mixed['survey_coordinates'][0]['eastings'], '511085.849')

    def test_land_normalizer_selects_rows_under_regulation_coordinate_table(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'regulation_coordinates': [
                    {'point': '1', 'eastings': '511073.703', 'northings': '2392261.792'},
                ],
                'coordinate_tables': [
                    {
                        'table_name': 'إحداثيات الموقع',
                        'rows': [{'point': '1', 'eastings': '511073.703', 'northings': '2392261.792'}],
                    },
                    {
                        'table_name': 'إحداثيات التنظيم',
                        'rows': [{'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'}],
                    },
                ],
            }],
        })

        self.assertEqual(len(result['survey_coordinates']), 1)
        self.assertEqual(result['survey_coordinates'][0]['eastings'], '511085.849')
        self.assertEqual(result['survey_coordinates'][0]['northings'], '2392264.840')

        top_level_regulation = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'survey_coordinates': [{'point': '1', 'eastings': '511073.703', 'northings': '2392261.792'}],
            }],
            'regulation_coordinates': [{
                'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'
            }],
        })
        self.assertEqual(top_level_regulation['survey_coordinates'][0]['eastings'], '511085.849')

    def test_land_extraction_diagnostics_identifies_empty_tables(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'directions': {'north': {'regulation_text': 'بطول 10 م يحده جار'}},
                'survey_coordinates': [],
            }],
            'conflicts': [{'field': 'survey_coordinates', 'description': 'الجدول غير مقروء'}],
        })
        diagnostics = self.application_module._build_land_extraction_diagnostics(result, [])

        self.assertEqual(diagnostics['status'], 'partial')
        self.assertEqual(diagnostics['coordinates_rows'], 0)
        self.assertEqual(diagnostics['directions_with_values'], 1)
        self.assertIn('إحداثيات التنظيم', diagnostics['missing_tables'])
        self.assertEqual(diagnostics['conflict_count'], 1)

    def test_extract_croquis_response_exposes_table_diagnostics(self):
        model_payload = {
            'parcels': [{
                'parcel_id': 'P-1',
                'survey_coordinates': [{
                    'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'
                }],
                'directions': {
                    'north': {'regulation_text': 'بطول 10 م'},
                    'south': {'regulation_text': 'بطول 11 م'},
                    'east': {'regulation_text': 'بطول 12 م'},
                    'west': {'regulation_text': 'بطول 13 م'},
                },
            }],
            'conflicts': [],
        }
        provider_response = {
            'choices': [{
                'finish_reason': 'stop',
                'message': {'content': json.dumps(model_payload, ensure_ascii=False)},
            }]
        }
        with patch.object(self.application_module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(self.application_module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(self.application_module, 'search_official_regulations_evidence', return_value=(
                    {'context': '', 'documents': [], 'table_pages': []}, []
                )), \
                patch.object(self.application_module, '_call_land_analysis_model', return_value=(provider_response, 9000, '')):
            response = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        diagnostics = response.get_json()['extractedData']['extraction_diagnostics']
        self.assertEqual(diagnostics['coordinates_rows'], 1)
        self.assertEqual(diagnostics['directions_with_values'], 4)
        self.assertEqual(diagnostics['status'], 'complete')

    def test_extract_croquis_requires_resolved_google_location(self):
        response = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
            'fileData': 'data:image/png;base64,test',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['failureReason'], 'location_required')

    def test_land_analysis_pipeline_reads_both_regulation_sources_before_final_merge(self):
        final_payload = {
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9',
                'area_sqm': 3000,
                'survey_coordinates': [{
                    'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'
                }],
                'directions': {},
            }],
            'conflicts': [],
        }
        stage_responses = [
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'site_facts': {'area_sqm': 3000, 'land_use': 'سكني', 'zoning_code': 'ت ر1'}
            }, ensure_ascii=False)}}]},
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'evidence': [{'field': 'allowed_uses_restrictions', 'value': 'سكني', 'page': 12}]
            }, ensure_ascii=False)}}]},
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'evidence': [{'field': 'building_ratio', 'value': '60%', 'page': 44}]
            }, ensure_ascii=False)}}]},
            {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(final_payload, ensure_ascii=False)}}]},
        ]
        stage_responses = [(response, 9000, '') for response in stage_responses]
        evidence_package = {
            'context': 'لا يُستخدم هذا الحقل في الدمج النهائي',
            'documents': [
                {'name': 'اشتراطات1.pdf', 'context': 'دليل الملف الأول', 'text_pages': [12], 'table_pages': []},
                {'name': 'اشتراطات2.pdf', 'context': 'دليل الملف الثاني', 'text_pages': [44], 'table_pages': []},
            ],
            'table_pages': [],
        }
        with patch.object(self.application_module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(self.application_module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(self.application_module, 'search_official_regulations_evidence', return_value=(
                    evidence_package, []
                )), \
                patch.object(self.application_module, '_call_land_analysis_model', side_effect=stage_responses) as calls:
            response = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(calls.call_count, 4)
        final_user_content = json.dumps(calls.call_args_list[-1].args[1], ensure_ascii=False)
        self.assertIn('اشتراطات1.pdf', final_user_content)
        self.assertIn('اشتراطات2.pdf', final_user_content)
        self.assertNotIn('لا يُستخدم هذا الحقل في الدمج النهائي', final_user_content)

    def test_health_reports_deployment_marker(self):
        marker = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        marker.write(json.dumps({'commit': '492d856c7fa', 'deployed_at': '2026-08-06T22:45:00Z', 'source': 'github'}))
        marker.close()
        self.addCleanup(lambda: os.path.exists(marker.name) and os.unlink(marker.name))
        with patch.object(self.application_module, 'DEPLOYMENT_MARKER_PATH', marker.name):
            payload = self.app.test_client().get('/health').get_json()
        self.assertEqual(payload['commit'], '492d856')
        self.assertEqual(payload['deployed_commit'], '492d856c7fa')
        self.assertEqual(payload['deployment_source'], 'github')
        self.assertIn('map_label_font', payload)

    def test_deploy_webhook_forwards_and_validates_the_expected_commit(self):
        module = self.application_module
        commit = 'a' * 40
        with patch.dict(os.environ, {'DEPLOY_WEBHOOK_SECRET': 'deploy-secret'}), \
                patch('subprocess.Popen') as popen:
            response = self.app.test_client().post(
                f'/api/deploy-webhook?secret=deploy-secret&commit={commit}')
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['expected_commit'], commit)
        self.assertEqual(popen.call_args.args[0][-1], commit)

        with patch.dict(os.environ, {'DEPLOY_WEBHOOK_SECRET': 'deploy-secret'}):
            invalid = self.app.test_client().post(
                '/api/deploy-webhook?secret=deploy-secret&commit=not-a-commit')
        self.assertEqual(invalid.status_code, 400, invalid.get_json())

        workflow = (ROOT / '.github/workflows/deploy.yml').read_text(encoding='utf-8')
        deploy_script = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
        self.assertIn('&commit=${{ github.sha }}', workflow)
        self.assertIn('https://sagdemos.store/api/deploy-webhook', workflow)
        self.assertNotIn('sagdemo.site', workflow)
        self.assertIn('TARGET_COMMIT="${1:-}"', deploy_script)
        self.assertIn('git reset --hard "$TARGET_COMMIT"', deploy_script)
        self.assertIn('REPO_DIR="/home/demos/workflow.git"', deploy_script)
        self.assertIn('APP_DIR="/home/demos/proposal-generator"', deploy_script)
        start_script = (ROOT / 'start_server.sh').read_text(encoding='utf-8')
        self.assertIn('WEB_ROOT="/home/demos/public_html"', start_script)
        self.assertIn("deploy_script = '/home/demos/proposal-generator/deploy.sh'", (ROOT / 'app.py').read_text(encoding='utf-8'))

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

    def test_visual_concept_image_response_accepts_content_image_parts(self):
        module = self.application_module
        response = Mock(status_code=200)
        response.json.return_value = {
            'choices': [{'message': {'content': [
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,from-content'}}
            ]}}]
        }
        with patch.object(module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(module.requests, 'post', return_value=response):
            result = module.call_image_api_with_references(
                'prompt', ['data:image/png;base64,AAAA', 'data:image/png;base64,BBBB']
            )
        self.assertEqual(result, 'data:image/png;base64,from-content')

    def test_visual_concept_keeps_five_reference_file_ids(self):
        module = self.application_module
        ids = [f'file-{index}' for index in range(7)]
        result = module._visual_concept_style_reference_ids({
            'visual_concept': {'styleReferenceFileIds': ids}
        })
        self.assertEqual(result, ids[:5])

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

    def test_land_document_form_uses_one_multi_file_field(self):
        fields = self.app.test_client().get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        keys = {field['fieldKey'] for field in fields}
        self.assertIn('land_documents_files', keys)
        self.assertNotIn('land_image_file', keys)
        self.assertNotIn('regulation_reference_file', keys)
        self.assertNotIn('croquis_file', keys)
        self.assertNotIn('building_permit_file', keys)
        self.assertNotIn('north_direction', keys)

    def test_approved_floor_count_is_client_entered_and_distinct_from_allowed_floors(self):
        fields = self.app.test_client().get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        field = next(item for item in fields if item['fieldKey'] == 'approved_floor_count')
        self.assertEqual(field['fieldLabel'], 'الأدوار المعتمدة')
        self.assertEqual(field['fieldType'], 'number')
        self.assertTrue(field['isRequired'])
        coverage = next(item for item in fields if item['fieldKey'] == 'approved_coverage_ratio')
        self.assertEqual(coverage['fieldLabel'], 'التغطية المعتمدة (%)')
        self.assertEqual(coverage['fieldType'], 'number')
        self.assertTrue(coverage['isRequired'])
        land_fields = {item['fieldKey']: item for item in fields}
        for key in ('building_ratio_coverage', 'setbacks', 'allowed_uses', 'regulatory_constraints', 'land_and_building_summary'):
            self.assertTrue(land_fields[key]['isRequired'])

        result = self.application_module._normalize_land_document_result({
            'parcels': [{'parcel_id': 'P-1', 'approved_floor_count': 7, 'max_floors_height': '12 دور'}]
        })
        self.assertNotIn('approved_floor_count', result)
        self.assertNotIn('approved_floor_count', result['parcels'][0])
        self.assertEqual(result['parcels'][0]['max_floors_height'], '12 دور')

        coverage_result = self.application_module._normalize_land_document_result({
            'parcels': [{'parcel_id': 'P-1', 'approved_coverage_ratio': 55, 'setbacks': 'أمامي 6م'}]
        })
        self.assertNotIn('approved_coverage_ratio', coverage_result)
        self.assertNotIn('approved_coverage_ratio', coverage_result['parcels'][0])

        regulatory = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'allowed_uses_restrictions': 'استخدام سكني',
                'parking_requirements': 'موقف لكل وحدة',
                'entrances_exits_requirements': 'مدخل سيارات منفصل',
            }]
        })
        restrictions = regulatory['parcels'][0]['allowed_uses_restrictions']
        self.assertIn('اشتراطات المواقف', restrictions)
        self.assertIn('اشتراطات المداخل والمخارج', restrictions)

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("resp_json.pop('approved_floor_count', None)", app_source)
        self.assertIn("resp_json.pop('approved_coverage_ratio', None)", app_source)
        self.assertIn('parking_requirements', app_source)
        self.assertIn('entrances_exits_requirements', app_source)
        self.assertIn("delete fields.approved_floor_count", index_source)
        self.assertIn("delete fields.approved_coverage_ratio", index_source)
        self.assertIn("'approved_floor_count'", index_source)

    def test_direction_and_coordinate_tables_are_separate_ai_outputs(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('surveyCoordinatesPanel', index_source)
        self.assertIn('surveyDirectionsPanel', index_source)
        self.assertNotIn('addSurveyCoordinateButton', index_source)
        self.assertIn('data-key="survey_coordinates"', index_source)
        self.assertIn('data-key="directions_table"', index_source)
        self.assertIn("f.fieldKey === 'land_documents_files'", index_source)
        self.assertIn("analyzeButton.textContent = 'تحليل الرخصة والكروكي معًا'", index_source)
        self.assertNotIn('analyzeLandDocumentsButton', index_source)
        self.assertIn('regulation_text', index_source)
        self.assertIn('landAnalysisDiagnostics', index_source)
        self.assertIn('showLandAnalysisDiagnostics', index_source)
        self.assertIn('uncertaintyMarkers', index_source)
        self.assertNotIn('تمت قراءة جدولي التنظيم', index_source)

    def test_land_tables_survive_draft_round_trip_without_being_wiped(self):
        """The coordinate/direction tables live in hidden inputs as JSON strings, so the
        renderers must parse them back instead of replacing stored rows with empty ones."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function parseStoredLandTable(value)', index_source)
        self.assertIn('const parsed = parseStoredLandTable(rows);', index_source)
        self.assertIn('if (hadValue && parsed === null) return;', index_source)
        self.assertIn('if (hadValue && parseStoredLandTable(value) === null) return;', index_source)
        # The destructive forms that silently dropped JSON strings must be gone.
        self.assertNotIn('const normalized = Array.isArray(rows) ? rows : [];', index_source)
        self.assertNotIn('Object.entries(value || {}).map(([direction, data])', index_source)

        client = self.app.test_client()
        coordinates = json.dumps(
            [{'parcel_id': 'P-1', 'point': '1', 'eastings': '510180.849',
              'northings': '2939234.840', 'source': 'regulation_table'}],
            ensure_ascii=False)
        directions = json.dumps(
            [{'direction': 'north', 'regulation_text': 'بطول 80.32م يحده شارع',
              'source': 'regulation_table'}],
            ensure_ascii=False)
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'survey_coordinates': coordinates, 'directions_table': directions}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        loaded = client.get('/api/project-draft', headers=self._headers(self.token_a))
        draft_data = loaded.get_json()['draft']['draft_data']
        self.assertEqual(json.loads(draft_data['survey_coordinates'])[0]['eastings'], '510180.849')
        self.assertEqual(json.loads(draft_data['directions_table'])[0]['direction'], 'north')

    def test_land_analysis_is_persisted_but_not_shown_as_a_review_panel(self):
        """The conflicts/parcels panels were removed; the payload must still be saved because
        the directions table falls back to parcels[0].directions on reload."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function storeLandDocumentAnalysis(', index_source)
        self.assertIn('landDocumentsAnalysisData', index_source)
        self.assertIn('parseStoredLandTable(source.land_documents_analysis)', index_source)
        # No visible review UI, and no raw JSON dumped at the user.
        self.assertNotIn('renderExtractedParcels', index_source)
        self.assertNotIn('renderLandDocumentConflicts', index_source)
        self.assertNotIn('القطع المكتشفة', index_source)
        self.assertNotIn('تعارضات تحتاج مراجعتك', index_source)
        self.assertNotIn('typeof item === \'string\' ? item : JSON.stringify(item)', index_source)
        self.assertNotIn('escapeHtml(JSON.stringify(parcel.confidence', index_source)
        # Conflicts are still requested so the model records disagreements instead of
        # silently picking a value, and they surface through the narrative summary.
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('"conflicts": [{"field": "", "description": ""}]', app_source)
        self.assertIn('_build_land_extraction_diagnostics', app_source)
        self.assertIn('إحداثيات التنظيم', app_source)
        self.assertIn('بموجب التنظيم', app_source)
        self.assertIn('"coordinate_tables"', app_source)
        self.assertIn('"regulation_coordinates"', app_source)
        self.assertNotIn('"severity": "high|medium|low"', app_source)

    def test_project_draft_list_returns_metadata_without_payload(self):
        client = self.app.test_client()
        response = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {
                'project_name': 'مسودة خفيفة',
                'tenantSlidesData': [{'html': 'x' * 5000}],
                'tenantCreativeImages': {'map_placeholders': {'##MAP_OVERVIEW##': '/map.png'}},
            }
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        listed = client.get('/api/project-drafts', headers=self._headers(self.token_a))
        self.assertEqual(listed.status_code, 200, listed.get_json())
        draft = next(item for item in listed.get_json()['drafts'] if item['title'] == 'مسودة خفيفة')
        self.assertNotIn('draft_data', draft)
        self.assertTrue(draft['has_slides'])
        self.assertTrue(draft['has_maps'])
        self.assertGreater(draft['data_bytes'], 5000)

    def test_missing_map_asset_does_not_regenerate_on_static_request(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.get('/uploads/maps/missing-map.png')
        self.assertEqual(response.status_code, 404)
        generate_maps.assert_not_called()

    def test_generate_slides_does_not_generate_maps_implicitly(self):
        client = self.app.test_client()
        generated = ['<div class="slide" style="width:1280px;height:720px">ok</div>']
        with patch.object(self.application_module, 'generate_all_slides', return_value=generated), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images') as generate_maps:
            response = client.post('/api/generate-slides', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0},
                'slidePlan': {'slides': [{'title': 'خريطة', 'type': 'map_overview'}]},
                'images': {},
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        generate_maps.assert_not_called()

    def test_project_file_upload_is_tenant_scoped_and_stored_by_hash(self):
        client = self.app.test_client()
        response = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'croquis',
            'draftId': 'draft-file-test',
            'file': (io.BytesIO(b'%PDF-1.4 test document'), 'parcel.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 201, response.get_json())
        file_id = response.get_json()['file']['id']
        with self.app.app_context():
            stored = db.get_project_file(self.tenant_a, file_id)
            other = db.get_project_file(self.tenant_b, file_id)
        self.assertIsNotNone(stored)
        self.assertIsNone(other)
        self.assertEqual(stored['file_type'], 'croquis')
        self.assertTrue(os.path.basename(stored['storage_path']).startswith(stored['sha256']))

    def test_project_file_preview_is_tenant_scoped_and_served_inline(self):
        """Uploaded deeds/site plans must be viewable in the app, but only by their tenant."""
        client = self.app.test_client()
        created = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'land_document',
            'file': (io.BytesIO(b'%PDF-1.4 preview me'), 'krooki.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(created.status_code, 201, created.get_json())
        file_id = created.get_json()['file']['id']

        served = client.get(f'/api/project-files/{file_id}', headers=self._headers(self.token_a))
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, 'application/pdf')
        self.assertIn(b'%PDF', served.data)
        # Inline so it can render in an iframe, and never sniffed into another type.
        self.assertNotIn('attachment', served.headers.get('Content-Disposition', ''))
        self.assertEqual(served.headers.get('X-Content-Type-Options'), 'nosniff')

        self.assertEqual(
            client.get(f'/api/project-files/{file_id}', headers=self._headers(self.token_b)).status_code,
            404)
        self.assertIn(client.get(f'/api/project-files/{file_id}').status_code, (401, 403))

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('async function openProjectFilePreview(', index_source)
        self.assertIn("'/api/project-files/' + encodeURIComponent(fileId)", index_source)
        self.assertIn('onclick="openProjectFilePreview(', index_source)

    def test_land_photos_are_optional_images_with_per_photo_descriptions(self):
        client = self.app.test_client()
        fields = client.get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        photo_field = next(field for field in fields if field['fieldKey'] == 'land_photos')
        self.assertFalse(photo_field['isRequired'])
        self.assertEqual(photo_field['sectionKey'], 'land_croquis')

        # PDFs are rejected for this slot because the UI renders them as thumbnails.
        rejected = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'land_image',
            'file': (io.BytesIO(b'%PDF-1.4 not a photo'), 'plan.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(rejected.status_code, 400, rejected.get_json())

        descriptions = [
            {'id': 'photo-1', 'originalName': 'front.jpg', 'description': 'الواجهة الشمالية'},
            {'id': 'photo-2', 'originalName': 'street.jpg', 'description': 'الشارع الغربي'},
        ]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'land_photos_file_ids': ['photo-1', 'photo-2'],
                          'land_photos_file_meta': descriptions}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        draft_data = client.get('/api/project-draft', headers=self._headers(self.token_a)).get_json()['draft']['draft_data']
        self.assertEqual(draft_data['land_photos_file_meta'][0]['description'], 'الواجهة الشمالية')

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('const LAND_PHOTOS_MAX = 4;', index_source)
        self.assertIn('function renderLandPhotos(', index_source)
        self.assertIn("input.dataset.projectFileType = 'land_image'", index_source)
        self.assertIn('function removeLandPhoto(', index_source)
        # Autosave re-uploads must not clear captions the client already typed.
        self.assertIn('previous?.description ? { ...file, description: previous.description } : file', index_source)

    def test_new_land_fields_split_identifiers_and_add_deed_date(self):
        fields = self.app.test_client().get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        by_key = {field['fieldKey']: field for field in fields}
        for key in ('plan_number', 'deed_date', 'facades_directions', 'land_photos'):
            self.assertIn(key, by_key)
            self.assertEqual(by_key[key]['sectionKey'], 'land_croquis')
        self.assertNotIn('subdivision_number', by_key)
        self.assertEqual(by_key['location_address']['sectionKey'], 'location')
        self.assertTrue(by_key['location_address']['isRequired'])
        for key in ('project_name', 'project_type', 'project_mixed_components', 'project_subtype', 'project_stage', 'project_logo',
                    'project_idea', 'project_level', 'target_audience', 'activity_class'):
            self.assertEqual(by_key[key]['sectionKey'], 'basic')
        self.assertEqual(by_key['project_mixed_components']['fieldLabel'], 'أنواع المشروع متعدد الاستخدامات')
        for key in ('project_goal', 'initial_features', 'initial_strengths'):
            self.assertNotIn(key, by_key)
        self.assertEqual(by_key['project_type']['fieldOptions'], [
            'سكني', 'تجاري', 'فندقي', 'صناعي ولوجستي'
        ])
        self.assertEqual(by_key['city']['sectionKey'], 'location')
        self.assertEqual(by_key['district']['sectionKey'], 'location')
        self.assertEqual(by_key['plot_number_croquis']['fieldLabel'], 'رقم القطعة')
        self.assertEqual(by_key['deed_date']['fieldLabel'], 'تاريخ الصك')
        self.assertEqual(by_key['building_ratio_coverage']['fieldLabel'], 'نسبة البناء والتغطية')
        self.assertEqual(by_key['setbacks']['fieldLabel'], 'الارتدادات')
        self.assertEqual(by_key['max_floors_height']['fieldType'], 'textarea')
        self.assertEqual(by_key['allowed_uses']['fieldLabel'], 'الاستخدامات المسموحة')
        self.assertEqual(by_key['regulatory_constraints']['fieldLabel'], 'القيود التنظيمية')
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('locationAddressMirror', index_source)
        self.assertNotIn('syncLocationAddressMirror', index_source)
        self.assertIn('geocodeTenantLocationLink', index_source)
        self.assertIn("if (f.fieldKey === 'city' || f.fieldKey === 'district')", index_source)
        self.assertIn("input.title = 'تُملأ تلقائيًا من الموقع والخرائط';", index_source)
        self.assertIn('applyCityDistrictToForm(data.city, data.district, true)', index_source)
        self.assertIn('includeMapContext: true', index_source)
        self.assertIn('function renderAllowedUsesStatusNote(status)', index_source)
        self.assertIn("id = 'allowedUsesStatusNote'", index_source)
        self.assertIn("استخدام نوع المشروع غير مسموح حسب الاشتراطات", index_source)
        self.assertIn('function resolveLandUseStatus(projectType, allowedUses)', index_source)
        self.assertIn('function refreshAllowedUsesStatusNote()', index_source)
        self.assertIn("قائمة الاستخدامات المسموحة تنظيميًا", (ROOT / 'db.py').read_text(encoding='utf-8'))
        self.assertIn('function slimLandAnalysisSiteContext(context)', index_source)
        self.assertIn('siteContext: slimLandAnalysisSiteContext(projectContext)', index_source)
        self.assertNotIn('siteContext: projectContext', index_source)
        self.assertIn("sectionKey === 'location'", index_source)
        self.assertIn('locationLat: projectContext.location_lat', index_source)
        self.assertIn("f.fieldType === 'textarea' || f.fieldKey === 'location_address' || f.fieldKey === 'project_type' ? ' full'", index_source)

    def test_uploaded_land_documents_are_restored_as_server_metadata_after_refresh(self):
        client = self.app.test_client()
        metadata = [{'id': 'file-a', 'originalName': 'permit.pdf', 'fileSize': 1024}]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'land_documents_files_file_ids': ['file-a'], 'land_documents_files_file_meta': metadata}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        loaded = client.get('/api/project-draft', headers=self._headers(self.token_a))
        self.assertEqual(loaded.status_code, 200, loaded.get_json())
        draft_data = loaded.get_json()['draft']['draft_data']
        self.assertEqual(draft_data['land_documents_files_file_ids'], ['file-a'])
        self.assertEqual(draft_data['land_documents_files_file_meta'], metadata)

    def test_browser_history_tracks_pages_sections_and_internal_tabs(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function syncTenantBrowserHistory', index_source)
        self.assertIn('function showSection(sectionKey, fromHistory = false)', index_source)
        self.assertIn('function setGlobalRailTab(tab, fromHistory = false)', index_source)
        self.assertIn("syncTenantBrowserHistory('tenantProjectPage', { activeSection: sectionKey }, fromHistory)", index_source)
        self.assertIn("window.history[method](state, '', url)", index_source)

    def test_location_analysis_runs_only_from_explicit_button(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("btn.onclick = () => analyzeTenantSite();", index_source)
        self.assertNotIn("addressInput.addEventListener('paste'", index_source)
        self.assertNotIn("addressInput.addEventListener('blur'", index_source)

    def test_financial_visibility_has_native_hidden_guard_for_optional_sections(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('element.hidden = !visible', index_source)
        self.assertIn("setConditionalVisibility('graceDetails', graceOn)", index_source)
        self.assertIn("setConditionalVisibility('graceScheduleWrap', scheduledGrace)", index_source)
        self.assertIn('const modeFlags = projectModeFlags();', index_source)
        self.assertIn('const targetCarry = profit * carryRate', index_source)
        self.assertIn("setConditionalVisibility('fundExitPerformanceGrid', feesOn)", index_source)

    def test_croquis_expiry_date_field_is_retired(self):
        """Retiring a prebuilt field means REMOVED_PREBUILT_FIELDS, so existing tenants lose it too,
        and the model must stop being asked for a value nothing will display."""
        self.assertIn('croquis_expiry_date', db.REMOVED_PREBUILT_FIELDS)
        self.assertNotIn('croquis_expiry_date', {field['key'] for field in db.PREBUILT_FIELDS})

        # Gone from the tenant's active field list, not just from the defaults.
        client = self.app.test_client()
        fields = client.get('/api/fields', headers=self._headers(self.token_a)).get_json()
        keys = {item['fieldKey'] for item in (fields.get('fields') or [])}
        self.assertNotIn('croquis_expiry_date', keys)

        # The extraction prompt, the alias map, the summary row and the parcel mapping are clean,
        # so no tokens are spent on it and no orphan value is stored.
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn('croquis_expiry_date', app_source)
        self.assertNotIn('expiry_date', app_source)
        self.assertNotIn("'croquis_validity_dates'", app_source)

        # The validity badge and its date parsing went with the field.
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('croquis_expiry_date', index_source)
        self.assertNotIn('croquisExpiryBadge', index_source)

    def test_land_documents_upload_on_selection_not_on_save(self):
        """The upload used to run inside collectTenantFormData, which only executed from the
        autosave. Once autosave was removed the files sat on "saving" forever and the analyse
        button saw no file ids to send."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        # Choosing a file must upload it, the way land photos already did.
        self.assertIn('uploadLandDocuments(input);', index_source)
        self.assertIn('async function uploadLandDocuments(input)', index_source)
        self.assertIn("uploadTenantProjectFileInput(input, 'land_documents_files')", index_source)

        # The old change handler only drew placeholders and waited for a save that never came.
        self.assertNotIn(
            "renderLandDocumentsUploadState(Array.from(input.files).map(file => ({ originalName: file.name, fileSize: file.size, status: 'pending' })));\n                triggerAutoSaveDraft();",
            index_source)

        # And the card must not claim an autosave that no longer exists.
        self.assertNotIn('جاري الحفظ تلقائيًا', index_source)
        self.assertIn("'جاري الرفع...'", index_source)

    def test_uploaded_land_documents_can_be_removed(self):
        """A wrongly uploaded deed or croquis had no way out: the card offered preview only."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        self.assertIn('function removeLandDocument(fileId)', index_source)
        self.assertIn("onclick=\"removeLandDocument(\\'", index_source)

        # Both the metadata list and the id list must be updated, because the analysis reads the
        # metadata list to decide which files to send to the model.
        self.assertIn('tenantProjectData.land_documents_files_file_meta = meta;', index_source)
        self.assertIn('tenantProjectData.land_documents_files_file_ids = meta.map(item => item.id);',
                      index_source)

        # Clearing the cached signatures lets the same file be re-selected after a mistake.
        self.assertIn("document.querySelector('#tenantProjectForm [data-key=\"land_documents_files\"]')",
                      index_source)
        self.assertIn('delete input.dataset.uploadSignatures;', index_source)

        # Removing a file must re-render, and persist the change.
        self.assertIn('renderLandDocumentsUploadState(meta);', index_source)

    def test_empty_places_result_is_not_reported_as_a_provider_error(self):
        """Places API (New) answers a valid search that matches nothing with HTTP 200 and "{}".
        Calling that an error turned a quiet area into "invalid response" and hid the caller's own
        "no landmarks found" message, which is only reachable on success."""
        import maps_service

        class _Response:
            status_code = 200
            def json(self):
                return {}

        with patch.object(maps_service, '_has_api_key', return_value=True), \
             patch.object(maps_service, '_get_api_key', return_value='k'), \
             patch.object(maps_service.requests, 'post', return_value=_Response()):
            result = maps_service.get_nearby_landmarks(21.5, 39.2, radius=20000)
        self.assertTrue(result['success'], result)
        self.assertEqual(result['landmarks'], [])
        self.assertIsNone(result.get('error_code'))

        # A genuinely malformed 200 body is still an error.
        class _Garbage(_Response):
            def json(self):
                return {'unexpected': 'shape'}

        with patch.object(maps_service, '_has_api_key', return_value=True), \
             patch.object(maps_service, '_get_api_key', return_value='k'), \
             patch.object(maps_service.requests, 'post', return_value=_Garbage()):
            broken = maps_service.get_nearby_landmarks(21.5, 39.2, radius=20000)
        self.assertFalse(broken['success'])
        self.assertEqual(broken['error_code'], 'GOOGLE_PLACES_INVALID_RESPONSE')

        # The reason must survive on screen, not only in a toast that disappears.
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="siteAnalysisWarnings"', index_source)
        self.assertIn('const reasons = [data.landmarksWarning, data.cityLandmarksWarning].filter(Boolean);',
                      index_source)
        self.assertIn('تعذر جلب المعالم — التفصيل أسفل الخريطة', index_source)

    def test_financial_pdf_has_no_raw_identifiers_or_json(self):
        """Section 12 used to dump the whole projection object, so schedule arrays landed in the
        client PDF as raw JSON under English keys, and table headers printed internal names."""
        model = {
            'inputs': {'unitRevenueMode': 'mixed', 'developmentYears': 4, 'landArea': 7000,
                       'builtUpAreaAbove': 60000, 'financeEnabled': 'yes', 'fundEnabled': 'no',
                       'fundFeesEnabled': 'no', 'externalEnabled': 'no', 'exitEnabled': 'no'},
            'tables': {
                'financeDrawTable': [{'year': 1, 'drawPct': 25}],
                'financeRepaymentTable': [{'year': 5, 'repaymentPct': 10}],
                'scheduleTable': [{'name': 'الأساسات', 'year': 1, 'costPct': 30, 'devPct': 30}],
                'cashflowTable': [{'year': 1, 'phase': 'تطوير', 'saleRevenue': 0, 'opex': 100,
                                   'final': -500, 'cumulative': -500}],
            },
            'projection': {
                'projectCost': 500000000, 'roi': 0.42, 'projectIrr': 0.18, 'equityIrr': 0.22,
                # These two are what leaked as JSON; they belong to section 8 as tables.
                'financePlan': [{'year': 4, 'drawPct': 25}],
                'financeRepaymentPlan': [{'year': 8, 'repaymentPct': 10}],
                'projected': [1, 2], 'cashflows': [4, 5], 'modeFlags': {'sales': True},
                'areaState': {'valid': True},
                # Echoed inputs already shown in sections 1 and 2.
                'landArea': 7000, 'developerRate': 10,
            },
        }
        with self.app.app_context():
            html = self.application_module.build_financial_report_html('مشروع', model, {}, self.tenant_a)

        # No structured value may be stringified into a row.
        self.assertNotIn('financePlan', html)
        self.assertNotIn('financeRepaymentPlan', html)
        self.assertNotIn('"drawPct"', html)
        self.assertNotIn('[{', html)

        # No internal identifier may be used as a visible header.
        self.assertEqual(sorted(set(re.findall(r'<th>([A-Za-z]\w*)</th>', html))), [])

        # Curated Arabic results, and the schedules still render as real tables in section 8.
        self.assertIn('12. النتائج المالية', html)
        self.assertIn('إجمالي تكلفة المشروع', html)
        self.assertIn('500,000,000.00', html)
        self.assertIn('42.00%', html)
        self.assertIn('18.00%', html)
        self.assertIn('معدل العائد الداخلي للمشروع', html)
        self.assertIn('نسبة السحب %', html)
        self.assertIn('صافي تدفق المشروع', html)
        # Echoed inputs are no longer repeated in the results summary.
        self.assertNotIn('developerRate', html)

    def test_cashflow_column_tints_do_not_override_the_table_header(self):
        """The cf-* classes also sit on the <th> so whole columns can be hidden by project mode.
        An unscoped class rule outranks "#section-financial-calc th" on specificity, which left
        those headers tinted with white text on them."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        for group in ('sales', 'rental', 'grace', 'fund', 'finance'):
            self.assertNotIn(f'#section-financial-calc .cf-{group} {{', index_source,
                             f'.cf-{group} must be scoped to td')
            self.assertIn(f'#section-financial-calc td.cf-{group} {{', index_source)
        # The classes must stay on the headers: column visibility depends on them.
        self.assertIn('<th class="cf-sales">', index_source)
        self.assertIn("setConditionalSelector('.cf-sales', flags.sales)", index_source)
        # Any other class placed on a th must be scoped for both th and td, as lt-* already is.
        header_classes = set(re.findall(r'<th[^>]*class="([^"]+)"', index_source))
        self.assertEqual(header_classes,
                         {'cf-sales', 'cf-rental', 'cf-grace', 'cf-fund', 'cf-finance',
                          'lt-dist', 'lt-dur', 'lt-actions'},
                         'a new class on a <th> needs its background rule scoped to td')

    def test_ui_contains_no_emojis_or_icon_glyphs(self):
        """Product rule: the app ships no emojis and no icon glyphs, including arrows used as
        button labels. Generated slides are covered separately by the icon stripper."""
        pictographs = re.compile(
            '[\u2190-\u21ff\u2300-\u23ff\u25a0-\u27bf\u2b00-\u2bff\ufe0f'
            '\U0001f000-\U0001faff]'
        )
        # index.html is the whole UI; the prompt files tell the model what to produce, so an emoji
        # there teaches it to emit one.
        for name in ('index.html', 'slide_engine.py', 'design_templates.py', 'app.py'):
            source = (ROOT / name).read_text(encoding='utf-8')
            found = sorted({match.group() for match in pictographs.finditer(source)})
            self.assertEqual(found, [], f'{name} still contains icon glyphs: {found}')

        # No icon libraries, and the only inline SVG is the map polygon overlay.
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        for library in ('font-awesome', 'fontawesome', 'material-icons', 'bootstrap-icons', 'lucide'):
            self.assertNotIn(library, index_source.lower(), f'{library} must not be used')
        self.assertEqual(index_source.count('<svg'), 2, 'only the favicon and the map overlay may use SVG')
        self.assertIn('id="mapPolygonOverlay"', index_source)

        # Missing logos fall back to a text monogram rather than a building glyph.
        self.assertIn('function teamMonogramHtml(name, size)', index_source)

        # The emoji-to-SVG converter is gone: it created icons the next line deleted.
        slide_source = (ROOT / 'slide_engine.py').read_text(encoding='utf-8')
        self.assertNotIn('_replace_emojis_with_svg', slide_source)
        self.assertNotIn('import emoji_icons', slide_source)
        self.assertIn('def _strip_presentation_icons(html)', slide_source)

    def test_team_library_is_a_flat_list_of_entities(self):
        """Categories were removed: each entity already states what it does in its role field, so
        the extra layer only added a step and a way to fail."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)

        listed = client.get('/api/team-entities', headers=headers)
        self.assertEqual(listed.status_code, 200, listed.get_json())
        self.assertEqual(listed.get_json()['entities'], [])
        self.assertNotIn('categories', listed.get_json())

        for removed in ('TEAM_SINGLETON_CATEGORIES', 'TEAM_CATEGORY_LABELS', 'TEAM_CATEGORY_FIELDS',
                        'get_team_categories', 'create_team_category', 'team_category_is_full'):
            self.assertFalse(hasattr(db, removed), f'{removed} must no longer exist')
        # The category endpoints are gone with them.
        self.assertEqual(client.post('/api/team-categories', headers=headers,
                                     json={'label': 'x'}).status_code, 404)

        created = client.post('/api/team-entities', headers=headers, json={
            'name': 'منافع الاقتصادية للعقار', 'experienceYears': '15',
            'role': 'مطور المشروع', 'brief': 'مطور عقاري سعودي',
            'notableProjects': 'برج الأمير\nمجمع الواحة'})
        self.assertEqual(created.status_code, 201, created.get_json())
        entity = created.get_json()['entity']
        self.assertEqual(entity['role'], 'مطور المشروع')
        self.assertEqual(entity['experienceYears'], '15')
        self.assertNotIn('categoryId', entity)

        # A name is required; a dangling logo id is refused rather than stored.
        self.assertEqual(client.post('/api/team-entities', headers=headers,
                                     json={'name': '  '}).status_code, 400)
        self.assertEqual(client.post('/api/team-entities', headers=headers, json={
            'name': 'شعار مفقود', 'logoFileId': 'nope'}).status_code, 400)

        # No cap on how many entities exist.
        for name in ('مكتب هندسي', 'مقاول', 'استشاري'):
            self.assertEqual(client.post('/api/team-entities', headers=headers,
                                         json={'name': name}).status_code, 201)
        self.assertEqual(len(client.get('/api/team-entities', headers=headers).get_json()['entities']), 4)

        # Tenant-scoped.
        self.assertEqual(client.get('/api/team-entities', headers=self._headers(self.token_b)).get_json()['entities'], [])

        updated = client.put('/api/team-entities/' + entity['id'], headers=headers,
                             json={'name': 'منافع', 'role': 'المطور والمشغل'})
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()['entity']['role'], 'المطور والمشغل')

        self.assertEqual(client.delete('/api/team-entities/' + entity['id'], headers=headers).status_code, 200)
        self.assertEqual(client.delete('/api/team-entities/' + entity['id'], headers=headers).status_code, 404)

        # No category UI survives in the settings page.
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        for gone in ('teamCategoryLabel', 'teamEntityCategory', 'tenantTeamCategories',
                     'submitTeamCategory', 'teamEntityBlocked', 'team-categories'):
            self.assertNotIn(gone, index_source, f'{gone} should have been removed')

    def test_openrouter_empty_body_is_reported_not_parsed(self):
        """An empty or unparseable response body must not leak a raw JSONDecodeError to the user.
        The previous flow exposed 'Expecting value: line 1 column 1 (char 0)' as the providerError."""
        from unittest.mock import patch, Mock

        def make_response(status, text, json_side_effect=None):
            r = Mock()
            r.status_code = status
            r.text = text
            if json_side_effect:
                r.json.side_effect = json_side_effect
            else:
                r.json.return_value = {'error': {'message': 'some provider error'}}
            return r

        empty = make_response(200, '')
        bad_json = make_response(200, 'not json', json_side_effect=ValueError('Expecting value: line 1 column 1 (char 0)'))
        http_error = make_response(503, '{"error":{"message":"Service Unavailable"}}')

        with patch('app.requests.post', side_effect=[empty, bad_json, http_error]):
            for response, expected in ((empty, '200'), (bad_json, '200'), (http_error, '503')):
                result = self.application_module.call_openrouter_chat(
                    'system', 'user', max_tokens=100, timeout=5)
                self.assertIn('error', result, f'status {response.status_code}')
                self.assertNotIn('Expecting value', result['error'].get('message', ''),
                                 f'raw JSONDecodeError leaked for status {response.status_code}')
                self.assertNotIn('line 1 column 1', result['error'].get('message', ''))
                self.assertIn(expected, result['error'].get('message', ''),
                              f'status code not in message for status {response.status_code}')

    def test_openrouter_chat_attaches_visual_references_as_multimodal_content(self):
        module = self.application_module
        response = Mock()
        response.status_code = 200
        response.text = '{"choices":[{"message":{"content":"ok"}}]}'
        response.json.return_value = {'choices': [{'message': {'content': 'ok'}}]}
        with patch('app.requests.post', return_value=response) as post:
            result = module.call_openrouter_chat(
                'system', 'instructions', model='google/gemini-3.7-flash',
                reasoning_effort='high', image_references=['data:image/png;base64,AAAA'])
        self.assertIn('choices', result)
        request_payload = post.call_args.kwargs['json']
        user_content = request_payload['messages'][1]['content']
        self.assertEqual(user_content[0], {'type': 'text', 'text': 'instructions'})
        self.assertEqual(user_content[1]['type'], 'image_url')
        self.assertEqual(user_content[1]['image_url']['url'], 'data:image/png;base64,AAAA')
        self.assertEqual(request_payload['reasoning_effort'], 'high')

    def test_app_never_answers_502(self):
        """The hosting edge fabricates 502s of its own for large bodies, so an app that also answers
        502 makes "the proxy broke" and "the AI failed" impossible to tell apart."""
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn('), 502', app_source,
                         '502 must be left to the proxy; use 503 for an upstream dependency')
        # The handled cases keep saying what happened, just under their own status.
        self.assertIn("'failureReason': 'truncated',", app_source)
        self.assertIn("'failureReason': 'invalid_json',", app_source)
        self.assertIn('), 503', app_source)

        # The land-analysis reason must survive on screen, not only in a toast.
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function showLandAnalysisFailure(reason, providerError)', index_source)
        self.assertIn('showLandAnalysisFailure(reason, res.providerError);', index_source)
        self.assertIn('clearLandAnalysisFailure();', index_source)
        self.assertIn('لم يتم تحديث أي حقل — التفصيل أسفل خانة الملفات', index_source)

    def test_shell_is_compressed_and_revalidates_instead_of_redownloading(self):
        """The SPA shell is ~740KB and was sent with no-store and no compression, so every load
        pulled all of it down again."""
        client = self.app.test_client()
        plain = client.get('/', headers={'Accept': 'text/html'})
        gzipped = client.get('/', headers={'Accept': 'text/html', 'Accept-Encoding': 'gzip'})

        self.assertEqual(gzipped.headers.get('Content-Encoding'), 'gzip')
        self.assertLess(len(gzipped.data), len(plain.data) / 2, 'compression should at least halve it')
        self.assertIn('Accept-Encoding', gzipped.headers.get('Vary', ''))

        # no-store forbids keeping a copy at all; no-cache keeps one and revalidates.
        self.assertEqual(plain.headers.get('Cache-Control'), 'no-cache')
        self.assertNotIn('no-store', plain.headers.get('Cache-Control', ''))
        etag = plain.headers.get('ETag')
        self.assertTrue(etag)
        revalidated = client.get('/', headers={'Accept': 'text/html', 'If-None-Match': etag})
        self.assertEqual(revalidated.status_code, 304)
        self.assertEqual(len(revalidated.data), 0)

        # JSON is compressed too, and a short body is left alone.
        listed = client.get('/api/team-entities', headers={
            **self._headers(self.token_a), 'Accept-Encoding': 'gzip'})
        self.assertEqual(listed.status_code, 200)
        self.assertIsNone(listed.headers.get('Content-Encoding'),
                          'a tiny payload is not worth compressing')

    def test_prebuilt_field_sync_writes_only_on_change(self):
        """It ran one UPDATE per prebuilt field on every /api/fields call — 39 writes and a commit
        per project-form load, none of which changed anything in the normal case."""
        source = (ROOT / 'db.py').read_text(encoding='utf-8')
        self.assertIn('if unchanged:', source)
        self.assertIn('if dirty:', source)

        client = self.app.test_client()
        first = client.get('/api/fields', headers=self._headers(self.token_a))
        self.assertEqual(first.status_code, 200)

        # Second identical call must not write anything.
        writes = []
        real_execute = db.get_db

        with self.app.app_context():
            conn = db.get_db()
            original = conn.execute

            def spy(sql, *args):
                if not sql.lstrip().upper().startswith('SELECT'):
                    writes.append(sql.split()[0].upper())
                return original(sql, *args)

            conn.execute = spy
            try:
                db.ensure_tenant_prebuilt_fields_active(self.tenant_a)
            finally:
                conn.execute = original
        self.assertEqual(writes, [], f'steady-state sync must not write, got {writes}')

    def test_new_tables_are_created_on_an_existing_database(self):
        """_create_tables used to return early when `tenants` existed, so every table added after
        the first deploy was missing forever on existing installs, surfacing as a 500 from
        whichever endpoint touched it."""
        import sqlite3
        import tempfile

        source = (ROOT / 'db.py').read_text(encoding='utf-8')
        self.assertNotIn("if cur and cur.fetchone():\n            return", source)

        path = os.path.join(tempfile.mkdtemp(), 'existing.db')
        original = db.DB_PATH
        try:
            db.DB_PATH = path
            db.init_db()
            conn = sqlite3.connect(path)
            conn.execute('DROP TABLE IF EXISTS tenant_team_entities')
            conn.commit()
            conn.close()

            db.init_db()  # what a deploy does
            conn = sqlite3.connect(path)
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            self.assertIn('tenant_team_entities', names,
                          'a missing table must be recreated on an existing database')
        finally:
            db.DB_PATH = original

    def test_project_team_section_scopes_choices_to_one_file(self):
        """A file may drop a library entity, override its role, or add an entity of its own —
        none of which may leak into other projects."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        self.assertIn("div.dataset.section = 'section-team'", index_source)
        self.assertIn("createProjectSectionHeader('section-team', 'فريق العمل')", index_source)
        self.assertIn('data-key="team_selection"', index_source)

        # The project form keeps the requested order, with the timeline feeding the financial study.
        self.assertIn("const sectionOrder = ['basic', 'location', 'land_croquis'];", index_source)
        build_start = index_source.index('addTimelineTable(form);')
        build_end = index_source.index('const projectSections = Array.from', build_start)
        build_source = index_source[build_start:build_end]
        self.assertLess(build_source.index('addTimelineTable(form);'), build_source.index('addFinancialCalculations(form);'))
        self.assertLess(build_source.index('addFinancialCalculations(form);'), build_source.index('addTeamSection(form);'))
        self.assertLess(build_source.index('addTeamSection(form);'), build_source.index('const conceptual2dSection'))

        # The three per-file behaviours.
        self.assertIn('function toggleTeamEntityInFile(entityId)', index_source)
        self.assertIn('function setProjectTeamRole(entityId, role)', index_source)
        self.assertIn('function addLocalTeamEntity()', index_source)
        self.assertIn('function removeLocalTeamEntity(localId)', index_source)
        # Project-only entities get the full field set, including a logo upload.
        self.assertIn('function updateLocalTeamEntity(localId, key, value)', index_source)
        self.assertIn('function uploadLocalTeamLogo(localId, input)', index_source)
        self.assertNotIn("prompt('اسم الجهة')", index_source)

        # The whole per-file choice set round-trips through the draft.
        client = self.app.test_client()
        selection = {
            'excluded': ['library-entity-1'],
            'roles': {'library-entity-2': 'المشرف على التنفيذ'},
            'local': [{'localId': 'local-1', 'categoryLabel': 'مقاول',
                       'name': 'شركة التنفيذ', 'role': 'المقاول الرئيسي'}],
        }
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'team_selection': json.dumps(selection, ensure_ascii=False)}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        draft_data = client.get('/api/project-draft', headers=self._headers(self.token_a)).get_json()['draft']['draft_data']
        restored = json.loads(draft_data['team_selection'])
        self.assertEqual(restored['excluded'], ['library-entity-1'])
        self.assertEqual(restored['roles']['library-entity-2'], 'المشرف على التنفيذ')
        self.assertEqual(restored['local'][0]['name'], 'شركة التنفيذ')

    def test_team_logos_must_be_images(self):
        client = self.app.test_client()
        rejected = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'team_logo',
            'file': (io.BytesIO(b'%PDF-1.4 not a logo'), 'logo.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(rejected.status_code, 400, rejected.get_json())
        self.assertIn('team_logo', self.application_module.PROJECT_FILE_TYPES)
        self.assertIn('team_logo', self.application_module.PROJECT_IMAGE_ONLY_TYPES)

    def test_drafts_are_saved_only_on_request(self):
        """Autosave fired on any input and from several render helpers, so merely opening a new
        project wrote a row to the server."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        # The debounced background save is gone; the old name only flags unsaved work now.
        # (Explicit checkpoint saves before slide/presentation generation stay: the backend needs
        # the draft to exist, and they only run on a deliberate user action.)
        self.assertNotIn('autoSaveDraftTimer', index_source)
        self.assertNotIn('جاري الحفظ تلقائياً', index_source)
        self.assertIn('function triggerAutoSaveDraft() {\n      setDraftDirty(true);\n    }', index_source)
        self.assertIn('function setDraftDirty(dirty)', index_source)
        self.assertIn('تغييرات غير محفوظة', index_source)

        # Losing unsaved work silently is worse than a prompt.
        self.assertIn("window.addEventListener('beforeunload'", index_source)
        self.assertIn('if (!tenantDraftDirty) return;', index_source)

        # A successful save clears the flag.
        self.assertIn('tenantDraftDirty = false;', index_source)

        # Deleting a draft addressed a route that does not exist, so it silently failed.
        self.assertNotIn("api('DELETE', '/api/project-draft');", index_source)
        self.assertIn("api('DELETE', '/api/project-draft/' + encodeURIComponent(draftId))", index_source)
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn("@app.route('/api/project-draft', methods=['DELETE'])", app_source)

    def test_project_form_action_bar_stays_visible_while_scrolling_every_section(self):
        """Save/back stay on screen while the user is inside a long section, then settle at the
        natural page end. The bar is shared by every project-form section, including floor design."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('.tenant-form-actions {', index_source)
        actions_start = index_source.index('.tenant-form-actions {')
        actions_end = index_source.index('}', actions_start)
        actions_css = index_source[actions_start:actions_end]
        self.assertIn('position: sticky', actions_css)
        self.assertIn('bottom: 10px', actions_css)
        self.assertNotIn('#tenantProjectPage.tenant-floor-design-project-mode>.tenant-form-actions', index_source)
        self.assertIn('<div class="tenant-form-actions">', index_source)
        self.assertIn('onclick="saveProjectAsDraft()"', index_source)

    def test_deep_links_serve_the_spa_instead_of_a_404(self):
        """Reloading or sharing a client-side route must not drop the user on an error page."""
        client = self.app.test_client()
        html_headers = {'Accept': 'text/html'}
        for path in ('/', '/app', '/app/dashboard', '/app/projects/new',
                     '/app/projects/floor-design', '/app/projects/visual-concept',
                     '/app/settings/users', '/projects/123/financial'):
            response = client.get(path, headers=html_headers)
            self.assertEqual(response.status_code, 200, f'{path} should serve the SPA shell')

        # Reserved prefixes must keep real 404s rather than returning HTML.
        for path in ('/api/does-not-exist', '/uploads/missing.png', '/assets/missing.js'):
            self.assertEqual(client.get(path, headers=html_headers).status_code, 404, path)
        # Non-GET and non-HTML requests must not be answered with the shell either.
        self.assertEqual(client.post('/definitely-not-a-route').status_code, 404)
        self.assertEqual(client.get('/definitely-not-a-route').status_code, 404)

    def test_back_navigation_never_leaves_the_app(self):
        """"/" and unmapped paths fell through popstate, so the view and the URL disagreed and the
        next Back exited the site."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn(
            "else if (tenantToken && window.location.pathname.startsWith('/app/')) showTenantPage('tenantDashboardPage', true);",
            index_source)
        self.assertIn("showTenantPage('tenantDashboardPage', true);\n      syncTenantBrowserHistory('tenantDashboardPage', {}, true);",
                      index_source)
        # A requested path wins over the remembered page, and "/" is rewritten to a real route.
        self.assertIn('const requestedPage = TENANT_ROUTE_PAGES[window.location.pathname];', index_source)
        self.assertIn("if (window.location.pathname === '/') {", index_source)
        self.assertIn('if (current && TENANT_PAGE_ROUTES[current]) syncTenantBrowserHistory(current, {}, true);',
                      index_source)

    def test_project_refresh_reopens_the_saved_draft(self):
        """Refreshing the project form must reopen the remembered draft, not a blank project."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('const savedDraftId = navigation && navigation.draftId &&', index_source)
        self.assertIn('if (!(savedDraftId && await openProjectDraftById(savedDraftId)))', index_source)
        self.assertIn('await startTenantProject()', index_source)

    def test_timeline_is_the_only_source_of_dev_duration_and_stages(self):
        """The financial study mirrors the timeline read-only so the two cannot disagree."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        self.assertIn('function syncFinancialFromTimeline()', index_source)

        # Development duration is taken from the timeline's year count and is not editable here.
        self.assertIn('id="developmentYears" type="number" min="1" value="4" readonly', index_source)
        self.assertNotIn('id="developmentYears" type="number" min="1" value="4" oninput', index_source)
        self.assertIn("مأخوذة من «عدد السنوات» في قسم الجدول الزمني", index_source)

        # Stage name and year are locked; only the two percentages remain editable.
        self.assertIn('<td data-field="name"><input value="${escapeHtml(d.name || \'\')}" readonly', index_source)
        self.assertIn('tr.dataset.stageYear = String(d.year ?? 1)', index_source)
        self.assertIn("tr.querySelectorAll('input:not([readonly])')", index_source)

        # No way to add or delete a stage from the financial study.
        self.assertNotIn('onclick="addScheduleStage()"', index_source)
        self.assertIn('المراحل وسنواتها تُعدّل من قسم الجدول الزمني', index_source)

        # Seeded stages are gone; the timeline drives the list.
        self.assertNotIn('التصميم والتراخيص والأعمال المبكرة', index_source)
        self.assertNotIn('الأساسات والهيكل الإنشائي', index_source)

        # Calendar year -> relative cashflow year, and the percentages survive a rebuild.
        self.assertIn('calendarYear - startYear + 1', index_source)
        self.assertIn('previous.get(name) || {}', index_source)
        self.assertIn('tr.dataset.stageEndYear = String(d.endYear ?? d.year ?? 1)', index_source)
        self.assertIn('year >= r.year && year <= r.endYear', index_source)
        self.assertIn('developerPayment += devPctTotal ? developerCost * (r.devPct / devPctTotal) / span : 0', index_source)

        # Empty timeline warns rather than silently zeroing the cost distribution.
        self.assertIn('id="timelineStagesWarning"', index_source)
        self.assertIn('warning.hidden = namedStages.length > 0', index_source)
        self.assertIn('if (!namedStages.length) return;', index_source)
        self.assertIn("if (namedStages.length && devYearsInput && Number.isFinite(timelineYears) && timelineYears > 0)", index_source)

        # The stage table lost its actions column, so the report must stop dropping the last one.
        self.assertIn("reportTableSnapshot('scheduleTable', false)", index_source)

        # Sidebar order comes from append order: the timeline feeds the financial study, so it
        # must be filled first and therefore listed first.
        timeline_at = index_source.index('addTimelineTable(form);')
        financial_at = index_source.index('addFinancialCalculations(form);')
        self.assertLess(timeline_at, financial_at,
                        'the timeline section must be appended before the financial study')

    def test_financial_study_mirrors_approved_build_inputs_from_land(self):
        """Approved area, floor count and coverage are owned by land/croquis and read-only here."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        self.assertIn('function syncFinancialFromLand()', index_source)

        # The three approved-build fields come from the land/croquis section and are locked.
        self.assertIn('id="landArea" type="number" value="70000" readonly', index_source)
        self.assertIn('id="coverageRate" type="number" value="35" readonly', index_source)
        self.assertIn('id="floorCount" type="number" min="1" value="1" readonly', index_source)
        self.assertIn('مأخوذة من «المساحة المعتمدة للدراسة المالية» في قسم الأرض والكروكي', index_source)
        self.assertIn('مأخوذة من «التغطية المعتمدة» في قسم الأرض والكروكي', index_source)
        self.assertIn('مأخوذة من «الأدوار المعتمدة» في قسم الأرض والكروكي', index_source)

        # Changing those land fields re-mirrors them into the financial study.
        self.assertIn(
            "f.fieldKey === 'approved_financial_area' || f.fieldKey === 'approved_floor_count' || f.fieldKey === 'approved_coverage_ratio'",
            index_source)
        self.assertIn("readLand('approved_coverage_ratio')", index_source)
        self.assertNotIn('parseCoverageFromLandText', index_source)

    def test_timeline_starts_blank_with_a_quarter_picker_and_row_delete(self):
        """Phases are client data, so the table must not seed invented stages."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        # The seeding table and its quarter-advancing loop are gone. (The unrelated `timeline`
        # sample *text* field may still mention phase names; only the table must not seed rows.)
        self.assertNotIn("{ name: 'الحصول على التراخيص', q: 'Q1', dur: 3 }", index_source)
        self.assertNotIn('currentQ += Math.ceil', index_source)
        self.assertNotIn("value=\"Q${currentQ}\"", index_source)

        # The quarter is a picker, not a free-text box.
        self.assertIn("const TIMELINE_QUARTERS = ['Q1', 'Q2', 'Q3', 'Q4'];", index_source)
        self.assertIn('<select class="tl-quarter"', index_source)
        self.assertNotIn('class="tl-quarter" value=', index_source)
        self.assertIn('function computeTimelineEnd(year, quarter, duration)', index_source)
        self.assertIn('class="tl-end"', index_source)
        self.assertIn('endYear: end ? String(end.year) : \'\'', index_source)
        self.assertIn('الملاحظات تظهر مع المرحلة في شريحة الجدول الزمني', index_source)
        self.assertNotIn('الملاحظات داخلية في الملف فقط', index_source)

        # Rows can be deleted, and one editable row always survives.
        self.assertIn('function removeTimelineRow(button)', index_source)
        self.assertIn('onclick="removeTimelineRow(this)"', index_source)
        self.assertIn('if (!tbody.rows.length) addTimelineRow();', index_source)

        # The slide title/subtitle fields are gone: nothing consumed them, so they invited the user
        # to fill in a heading that reached neither the slides nor the PDF.
        self.assertNotIn('timeline_slide_title', index_source)
        self.assertNotIn('timeline_slide_subtitle', index_source)

        # A missing start year used to collapse every stage into year 1 with no visible cause.
        self.assertIn('id="timelineStartYearWarning"', index_source)
        self.assertIn('startYearWarning.hidden = Number.isFinite(startYear) || !namedStages.length;',
                      index_source)

        # A single shared builder feeds the blank row, the add button and draft hydration.
        self.assertIn('function timelineRowHtml(data = {})', index_source)
        self.assertIn('timelineRows.forEach(row => addTimelineRow(row));', index_source)

        # Saved phases still round-trip through the draft.
        client = self.app.test_client()
        rows = [{'name': 'التراخيص', 'year': '2027', 'quarter': 'Q3',
                 'duration': '5', 'notes': 'بانتظار الأمانة'}]
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'timeline_table_data': json.dumps(rows, ensure_ascii=False)}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        draft_data = client.get('/api/project-draft', headers=self._headers(self.token_a)).get_json()['draft']['draft_data']
        restored = json.loads(draft_data['timeline_table_data'])[0]
        self.assertEqual(restored['quarter'], 'Q3')
        self.assertEqual(restored['notes'], 'بانتظار الأمانة')

        note = self.application_module.slide_engine._timeline_data_note({
            'timeline_table_data': json.dumps(rows, ensure_ascii=False)
        })
        self.assertIn('التراخيص', note)
        self.assertIn('بانتظار الأمانة', note)
        self.assertIn('2027 Q4', note)

    def test_components_live_only_inside_the_financial_study(self):
        """The standalone components section duplicated id="componentsTable", and duplicate ids
        make querySelector return only the first — so the financial readers were bound to the
        wizard table and its mismatched columns."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        # Exactly one element may own the id.
        self.assertEqual(len(re.findall(r'id="componentsTable"', index_source)), 1)

        # The standalone section and its helpers are gone.
        for gone in ('addComponentsTable', 'addComponentRow', 'recalcComponents',
                     'componentsTableBody', 'components_table_data', 'section-components'):
            self.assertNotIn(gone, index_source, f'{gone} should have been removed')

        # The financial study still owns the richer table and its readers.
        self.assertIn('<table id="componentsTable">', index_source)
        self.assertIn('function addComponent(d = {})', index_source)
        self.assertIn('function getComponentRowsData()', index_source)
        self.assertIn('function validateComponentAreas()', index_source)
        self.assertIn("data-field=\"investmentModel\"", index_source)

        # Renamed section.
        self.assertIn("createProjectSectionHeader('section-financial-calc', 'الدراسة المالية والمؤشرات')",
                      index_source)
        self.assertIn('onclick="saveProjectAsDraft()">حفظ كمسودة</button>', index_source)
        self.assertIn('function applySectionLockState(sectionKey, status)', index_source)
        self.assertIn("toggleButton.textContent = status === 'approved' ? 'الغاء الاعتماد' : 'اعتماد';", index_source)
        self.assertNotIn("resetButton.textContent = 'إلغاء الاعتماد';", index_source)
        self.assertIn('function updateVisualConceptHomeCards()', index_source)
        self.assertIn('id="visualConceptHomeCoverPreview"', index_source)
        self.assertNotIn('الدراسة المالية المبسطة', index_source)

        # The backend still reports on the financial components table.
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("('3', 'مكونات المشروع', 'componentsTable')", app_source)

    def test_financial_validation_requires_only_enabled_optional_inputs(self):
        errors = self.application_module.validate_financial_model({
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 1,
                'landArea': 1000, 'builtUpAreaAbove': 500,
                'financeEnabled': 'no', 'fundEnabled': 'no', 'externalEnabled': 'no',
                'exitEnabled': 'no',
            },
            'tables': {},
        })
        self.assertEqual(errors, [])
        errors = self.application_module.validate_financial_model({
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 1,
                'landArea': 1000, 'builtUpAreaAbove': 500,
                'financeEnabled': 'yes', 'fundEnabled': 'no', 'externalEnabled': 'no',
                'exitEnabled': 'no',
            },
            'tables': {},
        })
        self.assertTrue(any(item['field'] == 'annualFinanceRate' for item in errors))
        self.assertTrue(any(item['field'] == 'financeDrawTable' for item in errors))

    def test_financial_export_uses_server_validator_and_skips_disabled_sections(self):
        model = {
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 1,
                'landArea': 1000, 'builtUpAreaAbove': 500,
                'financeEnabled': 'no', 'fundEnabled': 'no',
                'fundFeesEnabled': 'no', 'externalEnabled': 'no',
                'exitEnabled': 'no',
            },
            'tables': {
                'sensitivityAssumptionsTable': [{'key': 'executionCost', 'low': 90, 'high': 110, 'ترتيب / حذف': 'أعلى'}],
                'sensitivityTable': [{'scenario': 'أساسي', 'roi': '12%'}],
                'cashflowTable': [{'year': 1, 'final': -10, 'cumulative': -10}],
            },
            'projection': {'projectCost': 10},
            'dynamicRows': {'sensitivity': [{'key': 'executionCost', 'low': 90, 'high': 110}]},
        }
        with self.app.app_context():
            html = self.application_module.build_financial_report_html('مشروع مالي', model, {}, self.tenant_a)
        self.assertNotIn('8. التمويل', html)
        self.assertNotIn('9. الصندوق وأتعابه', html)
        self.assertIn('12. النتائج المالية', html)
        self.assertIn('13. التدفقات النقدية السنوية', html)
        self.assertIn('14. تحليل الحساسية العام', html)
        self.assertIn('wide-table', html)
        self.assertIn('1,000.00', html)
        self.assertIn('90.00', html)
        self.assertIn('12.00%', html)
        self.assertNotIn('ترتيب / حذف', html)
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function persistFinancialStudyDraftState()', index_source)
        self.assertIn("data-key=\"financial_study_model\"", index_source)
        self.assertIn('sensitivity: collectSensitivityVariables()', index_source)
        self.assertIn("existing = Array.isArray(plan) ? plan : [...tb.querySelectorAll('tr')]", index_source)
        self.assertIn('if (source !== \'manual\') updateAutoQtyPreview(tr);', index_source)
        # Comma-formatted snapshot values used to be written back into type=number inputs,
        # which blank them, so the finance base and every derived field stayed at zero.
        self.assertIn("cleaned = cleaned.replace(/[٠-٩]/g, ch => String('٠١٢٣٤٥٦٧٨٩'.indexOf(ch)));", index_source)
        self.assertIn('function financialInputNumber(value, fallback = 0)', index_source)
        self.assertIn('if (isFinancialNumericControl(input)) {', index_source)
        self.assertIn('inputs[el.id] = isFinancialNumericControl(el) ? parseNumber(el.value) : (el.value ?? \'\');', index_source)
        self.assertIn('value="${financialInputNumber(d.qty, 0)}"', index_source)
        client = self.app.test_client()
        with patch.object(self.application_module, 'generate_financial_pdf') as generate_pdf:
            response = client.post('/api/financial-study/export', headers=self._headers(self.token_a), json={
                'projectName': 'مشروع مالي', 'financialModel': model
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])
        generate_pdf.assert_called_once()
        export_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        export_at = export_source.index('def api_export_financial_study()')
        self.assertIn('@require_auth', export_source[export_at - 80:export_at])
        self.assertNotIn('@require_permission(\'export_files\')', export_source[export_at - 80:export_at])
        self.assertIn("Playwright failed ({error}); falling back to PyMuPDF", export_source)
        self.assertIn("str(error).strip() or type(error).__name__", export_source)
        self.assertIn('def _financial_pdf_plain_html(html):', export_source)
        self.assertIn('def generate_financial_pdf_from_model(project_name, model, output_path):', export_source)
        self.assertIn("generate_financial_pdf(report_html, output_path, model=model, project_name=project_name)", export_source)
        maps_source = (ROOT / 'maps_service.py').read_text(encoding='utf-8')
        self.assertIn('def bundled_arabic_font_path():', maps_source)
        self.assertIn("os.path.join(FONTS_DIR, 'arabic-text.bin')", maps_source)
        font_path = ROOT / 'fonts' / 'arabic-text.bin'
        self.assertGreater(font_path.stat().st_size, 10000)
        self.assertEqual(font_path.read_bytes()[:4], b'\x00\x01\x00\x00')
        import tempfile
        from pathlib import Path
        with self.app.app_context():
            with tempfile.TemporaryDirectory() as temp_dir:
                out = Path(temp_dir) / 'model.pdf'
                self.application_module.generate_financial_pdf_from_model('مشروع مالي', model, out)
                self.assertTrue(out.exists())
                self.assertGreater(out.stat().st_size, 1000)
        with self.app.app_context():
            report = self.application_module.build_financial_report_html('مشروع مالي', model, {}, self.tenant_a)
            with tempfile.TemporaryDirectory() as temp_dir:
                out = Path(temp_dir) / 'study.pdf'
                with patch.dict('sys.modules', {'playwright': None, 'playwright.sync_api': None}):
                    self.application_module.generate_financial_pdf(report, out)
                self.assertTrue(out.exists())
                self.assertGreater(out.stat().st_size, 100)

    def test_land_document_normalizer_keeps_each_parcel_and_four_directions(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-7',
                'plot_number': '7',
                'directions': {'north': {'street_name': 'طريق شمالي', 'source': 'regulation_table'}},
                'survey_coordinates': [{'point': '1', 'eastings': '510180.849', 'northings': '2939234.840'}]
            }, {
                'parcel_id': 'P-8',
                'plot_number': '8',
                'directions': {'غرب': {'street_name': 'شارع غربي'}}
            }]
        })
        self.assertEqual([item['parcel_id'] for item in result['parcels']], ['P-7', 'P-8'])
        self.assertEqual(result['parcels'][0]['directions']['north']['street_name'], 'طريق شمالي')
        self.assertIn('west', result['parcels'][1]['directions'])
        self.assertIn('east', result['parcels'][0]['directions'])
        self.assertEqual(result['survey_coordinates'][0]['source'], 'regulation_table')
        self.assertEqual(result['survey_coordinates'][0]['eastings'], '510180.849')

    def test_parcel_path_normalizes_facades_deed_and_blocks_approved_area(self):
        """The scalar normalizers must run on the ``parcels`` path, not only on the legacy one."""
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9991',
                'plan_number': '3/س/125',
                # A direction word must never survive in the numeric facade field.
                'facades_count': 'جنوبية',
                'north_direction': 'يميل قليلًا نحو الشمال الغربي',
                'deed_number': 'غير مذكور',
                'approved_financial_area_sqm': 4321,
                'directions': {'south': {'street_name': 'شارع جنوبي'}},
            }],
            'land_and_building_summary': 'ملخص تفصيلي مسترسل عن الأرض والاشتراطات.',
        }, 'صك رقم 260629004505 وتاريخ الصك 1446/03/12 لقطعة رقم 9991')
        parcel = result['parcels'][0]

        # "جنوبية" is rejected as a count, then the count is rebuilt from the one street side.
        self.assertEqual(parcel['facades_count'], '1')
        self.assertEqual(parcel['facades_directions'], 'جنوبية')
        self.assertEqual(parcel['north_direction'], 'شمال غربي')
        # Placeholder wording is dropped, then the regex fallback fills the real values.
        self.assertEqual(parcel['deed_number'], '260629004505')
        self.assertEqual(parcel['deed_date'], '1446/03/12')
        self.assertEqual(result['plan_number'], '3/س/125')
        # The approved financial-study area is the client's input and must never be returned.
        self.assertNotIn('approved_financial_area', result)
        self.assertEqual(result['land_and_building_summary'], 'ملخص تفصيلي مسترسل عن الأرض والاشتراطات.')

    def test_hijri_dates_are_extracted_and_never_fed_to_a_date_input(self):
        """Saudi deeds are dated in Hijri; <input type="date"> silently drops those values."""
        find = self.application_module._find_document_date
        self.assertEqual(find('صك رقم 260629004505 وتاريخ 1446/03/12هـ'), '1446/03/12')
        self.assertEqual(find('تاريخ الصك 1446-03-12'), '1446/03/12')
        self.assertEqual(find('بتاريخ 12/03/1446 قطعة رقم أ'), '1446/03/12')
        self.assertEqual(find('وتاريخ ١٤٤٦/٠٣/١٢ هـ'), '1446/03/12')
        self.assertEqual(find('صادر بتاريخ 2025/09/30'), '2025/09/30')
        self.assertEqual(find('لا يوجد تاريخ هنا'), '')

        # deed_date must stay text so Hijri values survive; <input type="date"> would drop them.
        # (croquis_expiry_date was retired, and the client-side date parser went with its badge.)
        self.assertEqual(next(f for f in db.PREBUILT_FIELDS if f['key'] == 'deed_date')['type'], 'text')

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('const expDate = new Date(input.value);', index_source)
        self.assertNotIn('parseDocumentDate', index_source)

    def test_plan_number_falls_back_to_the_document_text(self):
        module = self.application_module
        for text, expected in (
            ('المخطط رقم 3/س/125', '3/س/125'),
            ('رقم المخطط: 1406/ب', '1406/ب'),
            ('مخطط خاص بدون رقم', ''),
        ):
            parcel = {'plan_number': ''}
            module._normalize_parcel_scalar_fields(parcel, text)
            self.assertEqual(parcel['plan_number'], expected, text)

    def test_building_rules_are_split_into_ratio_and_setbacks_fields(self):
        """The visible form separates ratios from setbacks without losing legacy payload support."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('building_ratio_setbacks: parcel.building_ratio || parcel.setbacks', index_source)
        self.assertIn('building_ratio_coverage: parcel.building_ratio_coverage || buildingRatioCoverageText', index_source)
        self.assertIn('setbacks: parcel.setbacks || setbacksText', index_source)
        self.assertIn('building_ratio_setbacks: parcel.building_ratio_setbacks || buildingRulesText', index_source)
        for label in ('نسبة البناء', 'نسبة التغطية', 'معامل مسطح البناء (FAR)'):
            self.assertIn("['" + label + "'", index_source)
        self.assertIn("const setbacksText = String(parcel.setbacks || '').trim();", index_source)

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('"coverage_ratio": ""', app_source)
        self.assertIn('"floor_area_ratio": ""', app_source)
        self.assertIn('لا تكتب «60%» وحدها', app_source)
        self.assertIn('غير محددة في المرجع المتاح', app_source)
        self.assertIn('REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', app_source)
        self.assertIn("os.environ.get('REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', '0')", app_source)
        self.assertIn('لا تكتب في أي حقل عبارات مثل «صفحة كذا»', app_source)

    def test_land_use_status_is_split_out_of_allowed_uses_text(self):
        module = self.application_module
        self.assertEqual(module.normalize_land_use_status('غير مسموح في هذه المنطقة'), 'غير مسموح')
        self.assertEqual(module.normalize_land_use_status('غير محسوم'), 'غير محسوم')
        status, text = module.split_land_use_status_text('حالة استخدام المشروع: غير مسموح\nسكني وتجاري')
        self.assertEqual(status, 'غير مسموح')
        self.assertEqual(text, 'سكني وتجاري')
        status_only, empty_text = module.split_land_use_status_text('استخدام الأرض: مسموح')
        self.assertEqual(status_only, 'مسموح')
        self.assertEqual(empty_text, '')
        self.assertEqual(
            module.resolve_land_use_status(
                'سكني',
                'الاستخدام المسموح للموقع هو سكني ترفيهي سياحي متنوع للجزء المطل على طريق الكورنيش، وسكني عمائر للجزء المتبقي.'
            ),
            'مسموح',
        )
        ignored = module.apply_entered_land_use_status({
            'allowed_uses': 'سكني ترفيهي سياحي',
            'land_use_status': 'غير محسوم',
            'parcels': [{'allowed_uses': 'سكني ترفيهي سياحي', 'land_use_status': 'غير محسوم'}],
        }, 'سكني')
        self.assertEqual(ignored['land_use_status'], 'مسموح')
        self.assertEqual(ignored['parcels'][0]['land_use_status'], 'مسموح')

    def test_land_result_exposes_split_usage_fields_without_page_references(self):
        result = self.application_module._normalize_land_document_result({
            'parcels': [{
                'parcel_id': 'P-1',
                'building_ratio': '60% من مساحة الأرض',
                'coverage_ratio': '50%',
                'floor_area_ratio': '2.5',
                'setbacks': 'أمامي 6م؛ خلفي 3م',
                'allowed_uses': 'حالة استخدام المشروع: غير محسوم\nسكني ترفيهي سياحي',
                'land_use_status': 'غير محسوم',
                'regulatory_constraints': 'اشتراطات المواقف: موقف لكل وحدة وفق اشتراطات1 صفحة 12',
                'summary': 'الاشتراطات وفق اشتراطات2 صفحة 44 واضحة.',
            }]
        }, project_type='سكني')
        parcel = result['parcels'][0]
        self.assertIn('نسبة البناء', parcel['building_ratio_coverage'])
        self.assertEqual(parcel['setbacks'], 'أمامي 6م؛ خلفي 3م')
        self.assertEqual(parcel['land_use_status'], 'مسموح')
        self.assertIn('موقف لكل وحدة', parcel['regulatory_constraints'])
        self.assertNotIn('صفحة 12', parcel['regulatory_constraints'])
        self.assertNotIn('صفحة 44', parcel['summary'])
        self.assertEqual(parcel['allowed_uses'], 'سكني ترفيهي سياحي')
        self.assertEqual(result['allowed_uses'], 'سكني ترفيهي سياحي')

    def test_full_regulation_evidence_includes_unmatched_pages_and_tables(self):
        module = self.application_module
        records = [
            {'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 1, 'text': 'قاعدة نسبة البناء', 'has_table': False},
            {'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 2, 'text': 'قاعدة غير مطابقة للكلمات المدخلة', 'has_table': True},
            {'name': 'اشتراطات2.pdf', 'path': 'two.pdf', 'page': 1, 'text': 'قاعدة الارتداد', 'has_table': False},
        ]
        with patch.object(module, '_build_regulation_page_index', return_value=records):
            package, warnings = module.search_official_regulations_evidence('كلمة لا تطابق', {})
        self.assertEqual(warnings, [])
        first = next(item for item in package['documents'] if item['name'] == 'اشتراطات1.pdf')
        self.assertIn('قاعدة غير مطابقة للكلمات المدخلة', first['context'])
        self.assertIn(2, first['text_pages'])
        self.assertEqual(package['table_pages'][0]['page'], 2)
        self.assertEqual({item['name'] for item in package['documents']}, {'اشتراطات1.pdf', 'اشتراطات2.pdf'})

    def test_full_regulation_table_pages_are_not_dropped_when_batched(self):
        module = self.application_module
        pages = [
            {'path': 'one.pdf', 'name': 'اشتراطات1.pdf', 'page': page}
            for page in (7, 8, 9, 10, 11)
        ]
        with patch.object(module, 'REGULATION_EVIDENCE_TABLE_PAGES_PER_STAGE', 2):
            batches = module.split_regulation_table_batches(pages)
        self.assertEqual([[item['page'] for item in batch] for batch in batches], [[7, 8], [9, 10], [11]])
        self.assertEqual(
            [item['page'] for batch in batches for item in batch],
            [item['page'] for item in pages],
        )

    def test_land_analysis_site_context_uses_map_fields(self):
        module = self.application_module
        with patch.object(module, '_collect_site_fields', return_value=(
            {'location_detail': 'عنوان الموقع', 'main_roads': 'طريق رئيسي'},
            [{'name': 'معلم قريب'}], [], [], [], [], None, {}
        )):
            context, warnings = module.build_land_analysis_site_context({
                'locationAddress': 'https://www.google.com/maps/@24,46,17z',
                'locationLat': 24,
                'locationLng': 46,
                'includeMapContext': True,
                'siteContext': {'project_type': 'سكني'},
            }, self.tenant_a, 24, 46)
        self.assertEqual(warnings, [])
        self.assertEqual(context['location_detail'], 'عنوان الموقع')
        self.assertEqual(context['main_roads'], 'طريق رئيسي')
        self.assertEqual(context['nearby_landmarks_data'][0]['name'], 'معلم قريب')

    def test_facade_count_accepts_real_counts_and_rejects_directions(self):
        normalize = self.application_module.normalize_facades_count
        self.assertEqual(normalize(4), '4')
        self.assertEqual(normalize('واجهتين'), '2')
        self.assertEqual(normalize('بلك كامل'), '4')
        self.assertEqual(normalize('شمالية وغربية'), '')
        self.assertEqual(normalize('', 'الأرض زاوية على شارعين'), '2')

    def test_facades_are_only_the_sides_that_front_a_street(self):
        """All plots have four boundaries, so naming four directions says nothing. Only the
        boundaries that border a street are facades."""
        module = self.application_module
        directions = {
            'north': {'street_name': 'شارع الأمير ماجد', 'street_width_m': 30},
            'south': {'street_name': 'قطعة رقم 12', 'uses': 'جار'},
            'east': {'street_name': '', 'street_width_m': 15},
            'west': {'street_name': 'أرض مجاورة'},
        }
        self.assertEqual(module.facade_directions_from_streets(directions), 'شمالية، شرقية')
        self.assertEqual(module.facade_directions_from_streets({}), '')

        # The count is derived from those sides when the model leaves it blank.
        parcel = {'facades_count': '', 'directions': directions}
        module._normalize_parcel_scalar_fields(parcel, '')
        self.assertEqual(parcel['facades_directions'], 'شمالية، شرقية')
        self.assertEqual(parcel['facades_count'], '2')

        wrong_count = {'facades_count': '4', 'directions': directions}
        module._normalize_parcel_scalar_fields(wrong_count, '')
        self.assertEqual(wrong_count['facades_count'], '2')

    def test_truncated_analysis_is_rejected_with_an_explicit_reason(self):
        """A rejected extraction changes no field, so it must not look like a silent no-op."""
        module = self.application_module
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('_call_land_analysis_model(', source)
        for reason in ('truncated', 'invalid_json', 'insufficient_credit'):
            self.assertIn(f"'failureReason': '{reason}'", source)
        self.assertIn('ولهذا لم تتغير البيانات', source)

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("'لم يتم تحديث أي حقل: ' + reason", index_source)
        self.assertIn('res.failureReason', index_source)
        self.assertIn("' حقلًا. راجع النتائج قبل الاعتماد.'", index_source)

    def test_land_analysis_lowers_the_cap_when_the_provider_cannot_afford_it(self):
        """OpenRouter reserves max_tokens against the balance, so an over-large cap is refused
        with 402 even when the real answer would be short."""
        module = self.application_module
        # A default the account can actually pay for; the retry only ever walks the cap down.
        self.assertLessEqual(module.LAND_ANALYSIS_MAX_TOKENS, 16000)

        refusal = {'error': {'code': 402, 'message': (
            'This request requires more credits, or fewer max_tokens. '
            'You requested up to 60000 tokens, but can only afford 25898')}}
        success = {'choices': [{'message': {'content': '{"ok":1}'}, 'finish_reason': 'stop'}]}
        caps = []

        def fake_call(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300, reasoning_effort=None, response_format=None, provider=None):
            caps.append(max_tokens)
            return refusal if max_tokens > 25898 else success

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call):
            res, cap, error = module._call_land_analysis_model('s', 'u', 60000)
        self.assertTrue(module._has_chat_choices(res))
        self.assertEqual(error, '')
        self.assertEqual(caps[0], 60000)
        self.assertLessEqual(caps[1], 25898)
        self.assertLess(cap, 60000)

        # A failure that is not about credit must be reported, not retried in a loop.
        with patch.object(module, 'call_openrouter_chat',
                          return_value={'error': {'message': 'model not found'}}) as once:
            _, _, error = module._call_land_analysis_model('s', 'u', 12000)
        self.assertEqual(once.call_count, 1)
        self.assertIn('model not found', error)

        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('رصيد OpenRouter لا يكفي', source)
        self.assertIn("'providerError': model_error", source)

    def test_land_analysis_retries_an_empty_provider_response(self):
        module = self.application_module
        empty = {'error': {'message': 'مزوّد الذكاء الاصطناعي رد بجسم فارغ (HTTP 200)'}}
        success = {'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]}
        with patch.object(module, 'call_openrouter_chat', side_effect=[empty, success]) as call, \
                patch.object(module.time, 'sleep'):
            res, cap, error = module._call_land_analysis_model('s', 'u', 16000)
        self.assertTrue(module._has_chat_choices(res))
        self.assertEqual(cap, 16000)
        self.assertEqual(error, '')
        self.assertEqual(call.call_count, 2)

    def test_land_analysis_retries_without_json_mode_after_output_format_block(self):
        """Anthropic and some OpenRouter fallbacks reject json_object with output_format
        content filtering, which used to abort the whole croquis analysis."""
        module = self.application_module
        blocked = {'error': {'message': (
            '[400] Provider returned error '
            '{"type":"error","error":{"type":"invalid_request_error",'
            '"message":"Output blocked by content filtering policy","code":"output_format"}}'
        )}}
        success = {'choices': [{'message': {'content': '{"plot_number":"9991"}'}, 'finish_reason': 'stop'}]}
        formats = []

        def fake_call(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None,
                      timeout=300, reasoning_effort=None, response_format=None, provider=None):
            formats.append(response_format)
            return blocked if response_format else success

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call) as call:
            res, cap, error = module._call_land_analysis_model('s', 'u', 16000)
        self.assertTrue(module._has_chat_choices(res))
        self.assertEqual(error, '')
        self.assertEqual(cap, 16000)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(formats[0], {'type': 'json_object'})
        self.assertIsNone(formats[1])
        self.assertEqual(module._get_chat_response_text(res), '{"plot_number":"9991"}')

    def test_land_analysis_reads_json_from_reasoning_when_content_is_empty(self):
        """Reasoning models often spend the reply on reasoning and leave message.content empty."""
        module = self.application_module
        payload = json.dumps({
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9991',
                'area_sqm': 3000,
                'survey_coordinates': [{'point': '1', 'eastings': '511085.849', 'northings': '2392264.840'}],
                'directions': {
                    'north': {'regulation_text': 'بطول 10 م'},
                    'south': {'regulation_text': 'بطول 11 م'},
                    'east': {'regulation_text': 'بطول 12 م'},
                    'west': {'regulation_text': 'بطول 13 م'},
                },
            }],
            'conflicts': [],
        }, ensure_ascii=False)
        response = {
            'choices': [{
                'finish_reason': 'stop',
                'message': {
                    'content': '',
                    'reasoning': 'thinking first then answer\n' + payload,
                },
            }]
        }
        self.assertEqual(module.parse_json_object(module._get_chat_response_text(response))['parcels'][0]['plot_number'], '9991')

        with patch.object(module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(module, 'search_official_regulations_evidence', return_value=(
                    {'context': '', 'documents': [], 'table_pages': []}, []
                )), \
                patch.object(module, '_call_land_analysis_model', return_value=(response, 9000, '')):
            result = self.app.test_client().post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(result.get_json()['extractedData']['plot_number_croquis'], '9991')

    def test_live_land_analysis_returns_a_job_and_is_polled(self):
        """The hosting proxy fabricates a 404 if extract-croquis stays open for minutes."""
        module = self.application_module
        model_payload = {
            'parcels': [{
                'parcel_id': 'P-1',
                'plot_number': '9991',
                'survey_coordinates': [{'point': '1', 'eastings': '1', 'northings': '2'}],
                'directions': {
                    'north': {'regulation_text': 'بطول 10 م'},
                    'south': {'regulation_text': 'بطول 11 م'},
                    'east': {'regulation_text': 'بطول 12 م'},
                    'west': {'regulation_text': 'بطول 13 م'},
                },
            }],
            'conflicts': [],
        }
        provider_response = {
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(model_payload, ensure_ascii=False)}}]
        }
        client = self.app.test_client()
        with patch.object(module, 'OPENROUTER_KEY', 'test-key'), \
                patch.object(module, '_prepare_document_vision_parts', return_value=(
                    [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test', 'detail': 'high'}}],
                    [], 1, 'image_direct'
                )), \
                patch.object(module, 'search_official_regulations_evidence', return_value=(
                    {'context': '', 'documents': [], 'table_pages': []}, []
                )), \
                patch.object(module, '_call_land_analysis_model', return_value=(provider_response, 9000, '')):
            started = client.post('/api/extract-croquis', headers=self._headers(self.token_a), json={
                'background': True,
                'fileData': 'data:image/png;base64,test',
                'locationAddress': 'https://www.google.com/maps/@24.0,46.0,17z',
                'locationLat': 24.0,
                'locationLng': 46.0,
            })
            self.assertEqual(started.status_code, 202, started.get_json())
            job_id = started.get_json()['jobId']
            self.assertTrue(job_id)
            job = None
            for _ in range(80):
                polled = client.get('/api/extract-croquis/' + job_id, headers=self._headers(self.token_a))
                self.assertEqual(polled.status_code, 200, polled.get_json())
                job = polled.get_json()
                if job.get('status') in ('completed', 'failed'):
                    break
                time.sleep(0.05)
        self.assertEqual(job['status'], 'completed', job)
        self.assertTrue(job['success'])
        self.assertEqual(job['extractedData']['plot_number_croquis'], '9991')
        self.assertNotIn('rawText', job)

        foreign = client.get('/api/extract-croquis/' + job_id, headers=self._headers(self.token_b))
        self.assertEqual(foreign.status_code, 404)

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("api('GET', '/api/extract-croquis/' + encodeURIComponent(jobId))", index_source)
        self.assertIn('res.jobId', index_source)

    def test_land_prompt_forbids_ai_written_approved_area_and_demands_narrative(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn('"approved_financial_area_sqm": null', source)
        self.assertIn('"subdivision_number": ""', source)
        self.assertIn('"deed_date": ""', source)
        self.assertIn('"facades_directions": ""', source)
        self.assertIn('عدد الحدود المطلة على شوارع فقط', source)
        # Trimmed from 250 words: the longer narrative pushed the JSON past the token cap, and a
        # truncated response is discarded whole.
        self.assertIn('١٨٠ كلمة على الأقل', source)
        self.assertIn('وليس قائمة حقول مفصولة بشرطات', source)
        self.assertIn('قائمة الاستخدامات المسموحة تنظيميًا', source)

    def test_regulation_lookup_skips_index_pages_and_strips_page_furniture(self):
        module = self.application_module
        index_page = 'نسبة البناء ' + ('.' * 30) + ' 36\nالارتدادات ' + ('.' * 30) + ' 37\nالتغطية ' + ('.' * 30) + ' 38'
        self.assertTrue(module._is_regulation_index_page(index_page))
        self.assertTrue(module._is_regulation_index_page(''))
        self.assertFalse(module._is_regulation_index_page('نسبة البناء هي النسبة المئوية لمساحة الحد الأقصى'))

        noisy = 'المخطط المحلي لمحافظة جدة1447 هـ\nم ص 25 من197\nنسبة البناء 60%'
        cleaned = module._clean_regulation_text(noisy)
        self.assertIn('نسبة البناء 60%', cleaned)
        self.assertNotIn('من197', cleaned)

        # Pages carrying the conditions must outrank generic prose.
        self.assertGreater(
            module._score_regulation_page('نسبة البناء 60% وعدد الطوابق 5 وارتداد أمامي', []),
            module._score_regulation_page('مقدمة عامة عن الوثيقة', []))

    def test_regulation_lookup_reports_missing_files_instead_of_failing_silently(self):
        module = self.application_module
        with patch.object(module, 'regulation_pdf_paths', return_value=[]):
            context, table_pages, warnings = module.search_official_regulations_pdf('ت ر1')
        self.assertEqual(context, '')
        self.assertEqual(table_pages, [])
        self.assertTrue(warnings, 'a missing regulation file must surface a warning')
        self.assertIn('اشتراطات1.pdf', warnings[0])

        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        # The stale hardcoded filenames are gone, along with the first-two-pages-then-break scan.
        self.assertNotIn('Document_LocalPlan_1447.pdf', source)
        self.assertNotIn('ExecutiveRegulations-1447-2025-2.pdf', source)
        self.assertNotIn('search_jeddah_official_regulations_pdf', source)
        # Client documents stay vision-only; the regulation arrives as trusted text + table images.
        self.assertIn('لديك نوعان من المدخلات', source)
        self.assertIn('نص هذا الجدول يُستخرج بترتيب معكوس', source)
        self.assertIn('نتائج استخلاص الاشتراطات من المحتوى الكامل للملفين', source)

    @unittest.skipUnless((ROOT / 'اشتراطات1.pdf').exists(), 'regulation PDFs not present')
    def test_regulation_lookup_returns_real_condition_pages(self):
        context, table_pages, warnings = self.application_module.search_official_regulations_pdf('ت ر1 تجاري سكني')
        self.assertEqual(warnings, [])
        # Far more usable text than the old 4 KB of index pages, and none of the furniture.
        self.assertGreater(len(context), 6000)
        self.assertNotIn('من197', context)
        self.assertNotIn('......', context)
        self.assertIn('نسبة البناء', context)
        # Zoning tables extract in reversed order, so they must ride along as images.
        self.assertTrue(table_pages)
        parts, render_warnings = self.application_module.render_regulation_table_pages(table_pages[:2])
        self.assertEqual(render_warnings, [])
        self.assertEqual(len(parts), 4)
        self.assertTrue(parts[1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_regulation_evidence_can_be_limited_per_file_when_configured(self):
        module = self.application_module
        records = [
            {
                'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 12,
                'text': 'نسبة البناء والاستخدامات والمواقف سكني', 'has_table': True,
            },
            {
                'name': 'اشتراطات2.pdf', 'path': 'two.pdf', 'page': 44,
                'text': 'ارتداد وتغطية وعدد الطوابق وارتفاع مسطح البناء', 'has_table': True,
            },
            {
                'name': 'اشتراطات1.pdf', 'path': 'one.pdf', 'page': 13,
                'text': 'مقدمة عامة عن الوثيقة', 'has_table': False,
            },
        ]
        with patch.object(module, '_build_regulation_page_index', return_value=records), \
                patch.object(module, 'REGULATION_EVIDENCE_TEXT_PAGES_PER_FILE', 1), \
                patch.object(module, 'REGULATION_EVIDENCE_TABLE_PAGES_PER_FILE', 1):
            package, warnings = module.search_official_regulations_evidence(
                'سكني', {'area_sqm': 3000, 'land_use': 'سكني'}
            )

        self.assertEqual(warnings, [])
        self.assertEqual([item['name'] for item in package['documents']], ['اشتراطات1.pdf', 'اشتراطات2.pdf'])
        self.assertEqual([item['table_pages'] for item in package['documents']], [[12], [44]])
        self.assertEqual({item['name'] for item in package['table_pages']}, {'اشتراطات1.pdf', 'اشتراطات2.pdf'})
        self.assertIn('نسبة البناء والاستخدامات والمواقف', package['context'])
        self.assertIn('ارتداد وتغطية وعدد الطوابق', package['context'])
        self.assertNotIn('مقدمة عامة عن الوثيقة', package['context'])

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

    def test_single_map_regeneration_bypasses_cached_assets(self):
        client = self.app.test_client()
        with patch.object(self.application_module.maps_service, 'generate_all_map_images', return_value={
            'placeholders': {'##MAP_ACCESS##': '/uploads/maps/access.png'},
            'landmarks': [],
            'landmarks_matrix': [],
            'zooms': {'access': 16},
        }) as generate_maps:
            response = client.post('/api/generate-map-image', headers=self._headers(self.token_a), json={
                'projectData': {'location_lat': 24.0, 'location_lng': 46.0, 'draftId': 'one-map'},
                'mapType': 'access',
                'regenSeed': 17,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        generated_project = generate_maps.call_args.args[0]
        self.assertEqual(generated_project['enabled_maps'], ['access'])
        self.assertTrue(generated_project['refresh_maps'])
        self.assertEqual(generated_project['regen_seed'], 17)
        self.assertFalse(generate_maps.call_args.kwargs.get('force'))

    def test_access_road_names_are_drawn_above_highlights(self):
        source = (ROOT / 'maps_service.py').read_text(encoding='utf-8')
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("ACCESS_ROADS_RENDER_VERSION = 'v9-arabic-no-ligatures'", source)
        self.assertIn("def bundled_arabic_overlay_font_path():", source)
        self.assertIn("def _strip_arabic_diacritics(text):", source)
        self.assertIn("def _arabic_reshaper_without_ligatures():", source)
        self.assertIn("configuration['support_ligatures'] = False", source)
        self.assertIn('from bidi.algorithm import get_display', source)
        self.assertIn("'language': 'ar'", source)
        overlay_font = ROOT / 'fonts' / 'cairo-overlay.bin'
        self.assertGreater(overlay_font.stat().st_size, 10000)
        self.assertEqual(overlay_font.read_bytes()[:4], b'\x00\x01\x00\x00')
        self.assertIn("'feature:road|element:labels|visibility:off'", source)
        self.assertIn('pending_labels.append((route_segment, label_text))', source)
        self.assertIn('labels_overlay = Image.new', source)
        self.assertIn('distance=52', source)
        self.assertIn('ly1 = offset_point[1] - 30', source)
        self.assertLess(
            source.index('draw.line(segment, fill=gold_color, width=9)'),
            source.index('_draw_road_label(labels_draw')
        )
        self.assertIn('function withCacheBust(url)', index_source)
        self.assertIn('payload.refresh_maps = true', index_source)
        self.assertIn('selectMapPreviewView(mapType)', index_source)

    def test_progress_bars_never_jump_backward(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('const value = allowDecrease ? requested : Math.max(loaderProgressValue, requested);', index_source)
        self.assertIn('const continueExisting = alreadyVisible && loaderSessionActive && options.reset !== true;', index_source)
        self.assertIn('const value = Math.max(genProgressValue, requested);', index_source)
        self.assertIn('let genProgressValue = 0;', index_source)

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
                    'project_goal': 'إنشاء وجهة ضيافة عملية للمسافرين من رجال الأعمال',
                    'project_stage': 'دراسة جدوى',
                    'initial_features': 'ردهة أعمال ومرافق اجتماعات',
                    'initial_strengths': 'قرب الموقع من المطار ومحور تجاري رئيسي',
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
        self.assertIn('إنشاء وجهة ضيافة عملية', prompt)
        self.assertIn('دراسة جدوى', prompt)
        self.assertIn('ردهة أعمال ومرافق اجتماعات', prompt)
        self.assertIn('قرب الموقع من المطار', prompt)
        self.assertIn('الكثافة السكانية', prompt)
        self.assertIn('البنية التحتية', prompt)
        self.assertIn('فرص الاستثمار', prompt)
        self.assertIn('المعالم القريبة ومعالم المدينة', prompt)
        self.assertEqual(call_ai.call_args.kwargs['reasoning_effort'], 'max')
        self.assertEqual(call_ai.call_args.kwargs['max_tokens'], self.application_module.SITE_ANALYSIS_MAX_TOKENS)

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
        self.assertEqual(fallback.call_args.kwargs['model'], 'google/gemini-3.7-flash')

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

    def test_visual_concept_replaces_legacy_image_workflow_pages(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<section id="tenantVisualConceptPage" class="tenant-page">', index_source)
        self.assertIn("tenantVisualConceptPage: '/app/projects/visual-concept'", index_source)
        self.assertIn("{ pageId: 'tenantVisualConceptPage', label: 'التصور البصري' }", index_source)
        self.assertIn('اختاري كرت التصور الخارجي أو الداخلي', index_source)
        self.assertIn('data-visual-concept-target="external"', index_source)
        self.assertIn('data-visual-concept-target="internal"', index_source)
        self.assertIn('visualConceptInteriorComponentSelect', index_source)
        self.assertIn('function uploadVisualConceptInteriorReferences', index_source)
        self.assertIn('عدد الصور الداخلية يساوي عدد مكونات المشروع', index_source)
        self.assertIn('function showVisualConceptView(view)', index_source)
        self.assertIn('function persistVisualConceptDraftState()', index_source)
        self.assertIn("data-key=\"visual_concept\"", index_source)
        self.assertIn('function persistVisualConceptDraftState()', index_source)
        visual_page = index_source[index_source.index('id="tenantVisualConceptPage"'):index_source.index('id="tenantSlidesPage"')]
        self.assertIn('onclick="saveProjectAsDraft()"', visual_page)
        self.assertIn('حفظ كمسودة', visual_page)
        self.assertIn("api('POST', '/api/visual-concept/prompt'", index_source)
        self.assertIn("apiWithTimeout('POST', '/api/visual-concept/generate'", index_source)
        self.assertIn('visual-concept-stack', index_source)
        self.assertIn('.visual-concept-preview img {', index_source)
        self.assertIn('object-fit: contain', index_source)
        self.assertRegex(index_source, r'\.visual-concept-stack \{\s*display: grid;\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);')
        self.assertIn('visualConceptStyleReferenceInput', index_source)
        self.assertIn("input.dataset.projectFileType = 'visual_reference'", index_source)
        self.assertIn('multiple accept="image/png,image/jpeg,image/jpg,image/webp"', index_source)
        self.assertIn('styleReferenceFileIds', index_source)
        self.assertIn('visualConceptImageUrl(response.image)', index_source)
        self.assertNotIn('visual-concept-grid', index_source)
        self.assertNotIn('نفس المبنى المعتمد', index_source)
        self.assertNotIn('tenantMainImagePage', index_source)
        self.assertNotIn('tenantMoodboardPage', index_source)
        self.assertNotIn('tenantMainImagePromptInput', index_source)
        self.assertNotIn('tenantMoodboardPreview', index_source)

    def test_visual_concept_requires_real_project_facts_and_cover_before_moodboard(self):
        client = self.app.test_client()
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("VISUAL_CONCEPT_MOODBOARD_SLOTS = ('right', 'left', 'top', 'back')", source)
        self.assertIn("VISUAL_CONCEPT_EXTERNAL_SLOTS = ('cover', 'right', 'left', 'top', 'back')", source)
        self.assertIn("'overview_map', 'خريطة الأرض / المبنى'", source)
        self.assertIn('style_reference_file_id', source)
        self.assertIn('style_reference_file_ids', source)
        self.assertIn('VISUAL_CONCEPT_MAX_REFERENCE_IMAGES = 5', source)
        self.assertNotIn("facts.get('land_photo_ids')", source)
        self.assertIn('visual_reference', self.application_module.PROJECT_FILE_TYPES)
        self.assertIn('visual_reference', self.application_module.PROJECT_IMAGE_ONLY_TYPES)
        self.assertIn('approved_financial_area', source)

        incomplete = client.post('/api/visual-concept/preflight', headers=self._headers(self.token_a), json={
            'projectData': {'project_name': 'برج الاختبار'}
        })
        self.assertEqual(incomplete.status_code, 400, incomplete.get_json())
        self.assertEqual(incomplete.get_json()['error_code'], 'VISUAL_CONCEPT_DATA_INCOMPLETE')
        missing_keys = {item['key'] for item in incomplete.get_json()['missingFields']}
        self.assertIn('approved_financial_area', missing_keys)
        self.assertIn('overview_map', missing_keys)

        facts = {
            'project_name': 'برج الاختبار',
            'project_idea': 'أبراج مكتبية على أرض تجارية',
            'land_and_building_summary': 'أرض تجارية بواجهة شرقية وغربية',
            'target_audience': 'شركات ومكاتب',
            'approved_financial_area': 8500,
            'approved_floor_count': 12,
            'approved_coverage_ratio': 60,
            'facades_count': 2,
            'facades_directions': 'شرق وغرب',
            'allowed_uses': 'تجاري مكتبي',
            'directions_table': [
                {'direction': 'east', 'regulation_text': 'شارع تجاري 30م'},
                {'direction': 'west', 'regulation_text': 'شارع فرعي 15م'},
            ],
            'project_components_data': [{'name': 'مكاتب', 'useType': 'office', 'units': 20, 'builtArea': 4000}],
            'tenantCreativeImages': {'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/overview.png'}},
        }
        ready = client.post('/api/visual-concept/preflight', headers=self._headers(self.token_a), json={'projectData': facts})
        self.assertEqual(ready.status_code, 200, ready.get_json())
        self.assertTrue(ready.get_json()['success'])

        moodboard_blocked = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
            'slotId': 'right',
            'prompt': 'Right elevation',
            'projectData': facts,
        })
        self.assertEqual(moodboard_blocked.status_code, 400, moodboard_blocked.get_json())
        self.assertEqual(moodboard_blocked.get_json()['error_code'], 'COVER_REQUIRED')

        generated = 'data:image/png;base64,AAAA'
        with patch.object(self.application_module, 'call_image_api_with_references', return_value=generated) as image_call, \
                patch.object(self.application_module, 'persist_generated_image', return_value='/uploads/creative/cover.png'):
            cover = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'cover',
                'prompt': 'Hero image from the project facts',
                'projectData': facts,
            })
        self.assertEqual(cover.status_code, 200, cover.get_json())
        self.assertEqual(cover.get_json()['image'], '/uploads/creative/cover.png')
        self.assertTrue(image_call.called)
        self.assertEqual(image_call.call_args.args[0], 'Hero image from the project facts')

        with patch.object(self.application_module, '_visual_concept_generate_prompt_text', return_value=('Revised right prompt', 'تم')):
            east_prompt = client.post('/api/visual-concept/prompt', headers=self._headers(self.token_a), json={
                'slotId': 'east',
                'coverImage': '/uploads/creative/cover.png',
                'projectData': facts,
            })
        self.assertEqual(east_prompt.status_code, 200, east_prompt.get_json())
        self.assertEqual(east_prompt.get_json()['slotId'], 'right')
        self.assertEqual(east_prompt.get_json()['prompt'], 'Revised right prompt')

        interior_blocked = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
            'slotId': 'interior_comp-1',
            'prompt': 'Apartment interior',
            'componentId': 'comp-1',
            'projectData': {
                **facts,
                'project_components_data': [{'id': 'comp-1', 'name': 'شقق', 'useType': 'residential', 'units': 12}],
            },
        })
        self.assertEqual(interior_blocked.status_code, 400, interior_blocked.get_json())
        self.assertEqual(interior_blocked.get_json()['error_code'], 'COVER_REQUIRED')

        with patch.object(self.application_module, 'call_image_api_with_references', return_value='data:image/png;base64,BBBB') as interior_call, \
                patch.object(self.application_module, 'persist_generated_image', return_value='/uploads/creative/interior.png'), \
                patch.object(self.application_module, '_prepare_image_reference_for_model', side_effect=lambda url: f'data:image/png;base64,{str(url).rsplit("/", 1)[-1]}'), \
                patch.object(self.application_module, '_visual_concept_project_file_data_uri', side_effect=lambda file_id: f'data:image/png;base64,{file_id}'):
            interior = client.post('/api/visual-concept/generate', headers=self._headers(self.token_a), json={
                'slotId': 'interior_comp-1',
                'prompt': 'Apartment interior',
                'componentId': 'comp-1',
                'coverImage': '/uploads/creative/cover.png',
                'referenceFileIds': ['ref-a', 'ref-b', 'ref-c', 'ref-d', 'ref-e'],
                'projectData': {
                    **facts,
                    'project_components_data': [{'id': 'comp-1', 'name': 'شقق', 'useType': 'residential', 'units': 12}],
                },
            })
        self.assertEqual(interior.status_code, 200, interior.get_json())
        self.assertEqual(interior.get_json()['slotId'], 'interior_comp-1')
        self.assertTrue(interior_call.called)
        self.assertEqual(interior_call.call_args.args[0], 'Apartment interior')
        self.assertEqual(interior.get_json()['referenceCount'], 6)
        references = interior_call.call_args.args[1]
        self.assertEqual(len(references), 6)
        self.assertIn('cover.png', str(references[0]))
        self.assertTrue(any('ref-a' in str(item) for item in references))

        self.assertIn('visualConceptInteriorComponentSelect', (ROOT / 'index.html').read_text(encoding='utf-8'))
        self.assertIn('function visualConceptInteriorSlotId', (ROOT / 'index.html').read_text(encoding='utf-8'))

    def test_floor_design_state_is_saved_as_tenant_draft_data(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("tenantFloorDesignPage: '/app/projects/floor-design'", index_source)
        self.assertIn("floor_visual_design", index_source)
        self.assertIn("formatTenantFloorDesignNumbers", index_source)
        self.assertIn('const formData = await collectTenantFormData();', index_source)
        self.assertIn('const data = { ...tenantProjectData, ...formData };', index_source)
        self.assertIn('function persistClassificationDraftState()', index_source)
        self.assertIn('if (typeof persistClassificationDraftState === \'function\') persistClassificationDraftState();', index_source)
        self.assertIn("if (f.fieldKey === 'project_type' || f.fieldKey === 'project_mixed_components' || f.fieldKey === 'project_subtype' || f.fieldKey === 'target_audience' || f.fieldKey === 'activity_class') {", index_source)
        self.assertIn('tenantVisualConceptState = normalizeVisualConceptState(tenantProjectData.visual_concept || tenantVisualConceptState);', index_source)
        self.assertIn('const moodboardImages = Array.isArray(tenantCreativeImages.moodboard) ? tenantCreativeImages.moodboard : [];', index_source)
        self.assertIn('if (!data.target_audience && tenantProjectData.target_audience) data.target_audience = tenantProjectData.target_audience;', index_source)
        self.assertIn('return slot.approvedImageUrl || slot.imageUrl || previousMoodboard[index] || \'\';', index_source)
        self.assertIn('collectFinancialDynamicRows', index_source)
        self.assertIn('hydrateFinancialStudyModel', index_source)
        self.assertIn('requireTenantApprovedBuildInputs', index_source)
        self.assertIn("APPROVED_BUILD_INPUTS_REQUIRED", (ROOT / 'app.py').read_text(encoding='utf-8'))

        state = {
            'version': 1,
            'floorCount': 5,
            'firstFloor': 1,
            'groups': [{
                'id': 'group-1',
                'name': 'مجموعة اختبار',
                'floorNumbers': [1, 3, 5],
                'status': 'pending',
                'imageUrl': '',
                'approvedImageUrl': '',
            }],
        }
        client = self.app.test_client()
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'project_name': 'اختبار التصميم المصور', 'floor_visual_design': state}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        loaded = client.get('/api/project-draft', headers=self._headers(self.token_a))
        self.assertEqual(loaded.status_code, 200, loaded.get_json())
        self.assertEqual(loaded.get_json()['draft']['draft_data']['floor_visual_design']['groups'][0]['floorNumbers'], [1, 3, 5])

    def test_floor_design_ai_endpoints_use_luna_and_validate_project_payload(self):
        client = self.app.test_client()
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('GEMINI_TEXT_MODEL = "google/gemini-3.7-flash"', source)
        self.assertIn('FLOOR_DESIGN_IMAGE_MODEL = "openai/gpt-image-2"', source)
        self.assertIn('FLOOR_DESIGN_IMAGE_HARD_NEGATIVE', source)
        self.assertIn("response_format={'type': 'json_object'}", source)
        self.assertIn('Permit English titles, labels, numbers, dimensions, tables, legends, and north notation.', source)
        self.assertIn('MANDATORY SERVER ENGINEERING SPECIFICATION', source)
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('tenantFloorDesignAnalysisChatThread', index_source)
        self.assertIn('sendTenantFloorDesignAnalysisChat', index_source)
        self.assertIn('/api/floor-design/analysis-chat', source)
        self.assertIn("apiWithTimeout('POST', '/api/floor-design/generate'", index_source)
        self.assertIn('for (let index = 0; index < group.pages.length; index += 1)', index_source)
        self.assertIn('hideLoader', index_source)
        self.assertIn("image.removeAttribute('src')", index_source)
        self.assertEqual(self.application_module._get_chat_response_text({'choices': [{'message': {'content': [{'type': 'text', 'text': '{"ok":true}'}]}}]}), '{"ok":true}')
        payload = {
            'projectData': {
                'project_name': 'اختبار مخطط 2D',
                'project_type': 'سكني',
                'project_idea': 'مشروع سكني',
                'project_goal': 'تطوير وحدات سكنية',
                'building_ratio_setbacks': 'ارتداد أمامي 6م وخلفي 3م',
                'boundary_lengths': 'حدود معتمدة من الكروكي',
                'allowed_uses_restrictions': 'سكني؛ موقف لكل وحدة؛ مدخل سيارات مستقل',
                'land_and_building_summary': 'ملخص موثق من ملفات الأمانة',
                'approved_financial_area': 7000,
                'approved_floor_count': 5,
                'project_components_data': json.dumps([{
                    'id': 'c1', 'name': 'وحدات سكنية', 'builtArea': 3000,
                    'floorNumbers': [1, 2, 3, 4, 5], 'netArea': 2500,
                }], ensure_ascii=False),
                'basementArea': 0,
            },
            'floorDesignState': {
                'floorCount': 5,
                'groups': [{'id': 'g1', 'name': 'الأدوار المتكررة', 'floorNumbers': [1, 2, 3, 4, 5], 'prompt': 'وحدات متكررة'}]
            }
        }
        missing = client.post('/api/floor-design/analyze', headers=self._headers(self.token_a), json={'projectData': {}})
        self.assertEqual(missing.status_code, 400, missing.get_json())
        self.assertEqual(missing.get_json()['error_code'], 'FLOOR_DESIGN_DATA_INCOMPLETE')
        fake_analysis = {'summary': 'تحليل تجريبي', 'hard_constraints': ['لا تغيّر الارتدادات'], 'project_inputs': [], 'group_notes': [], 'warnings': [], 'assumptions': []}
        with patch.object(self.application_module, 'call_openrouter_chat', return_value={'choices': [{'message': {'content': json.dumps(fake_analysis, ensure_ascii=False)}}]}) as call:
            analyzed = client.post('/api/floor-design/analyze', headers=self._headers(self.token_a), json=payload)
        self.assertEqual(analyzed.status_code, 200, analyzed.get_json())
        self.assertEqual(analyzed.get_json()['analysis']['summary'], 'تحليل تجريبي')
        self.assertEqual(call.call_args.kwargs['model'], 'google/gemini-3.7-flash')
        prompt_response = {'pages': [
            {'pageType': 'typical_floor', 'floorNumber': 1, 'prompt': 'Typical group design', 'negative_prompt': 'No furniture'}
        ]}
        with patch.object(self.application_module, 'call_openrouter_chat', return_value={'choices': [{'message': {'content': json.dumps(prompt_response, ensure_ascii=False)}}]}) as call:
            prompted = client.post('/api/floor-design/prompt', headers=self._headers(self.token_a), json={**payload, 'groupId': 'g1', 'analysis': fake_analysis})
        self.assertEqual(prompted.status_code, 200, prompted.get_json())
        self.assertEqual(len(prompted.get_json()['pages']), 1)
        self.assertEqual(prompted.get_json()['pages'][0]['pageType'], 'typical_floor')
        self.assertEqual(prompted.get_json()['pages'][0]['promptVersion'], 3)
        self.assertTrue(prompted.get_json()['prompt'].startswith('Create one representative typical-floor architectural presentation page for FLOORS 1-5'))
        self.assertIn('MANDATORY SERVER ENGINEERING SPECIFICATION', prompted.get_json()['prompt'])
        self.assertEqual(call.call_args.kwargs['model'], 'google/gemini-3.7-flash')
        self.assertEqual(call.call_args.kwargs['reasoning_effort'], 'high')
        self.assertEqual(len(call.call_args.kwargs['image_references']), 9)
        self.assertEqual(prompted.get_json()['referencePack']['count'], 9)
        self.assertEqual(prompted.get_json()['referencePack']['imageGenerationReference'], '1.png')
        prompt_system, prompt_user = call.call_args.args[:2]
        self.assertIn('Table of Contents', prompt_system)
        self.assertIn('data_conflicts', prompt_user)
        self.assertIn('directions_table', prompt_user)
        self.assertIn('components', prompt_user)

        chat_response = {
            'reply': 'تم تعديل التحذير وإنشاء المجموعة.',
            'analysis_patch': {'warnings': ['تحذير معدل']},
            'groups_patch': {'operations': [{
                'op': 'create',
                'group': {'id': 'g2', 'name': 'مجموعة جديدة', 'floorNumbers': [1, 2], 'prompt': 'وصف المجموعة'}
            }]}
        }
        with patch.object(self.application_module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': json.dumps(chat_response, ensure_ascii=False)}}]
        }) as call:
            chat = client.post('/api/floor-design/analysis-chat', headers=self._headers(self.token_a), json={
                **payload, 'analysis': fake_analysis, 'message': 'عدّل التحذير'
            })
        self.assertEqual(chat.status_code, 200, chat.get_json())
        self.assertEqual(chat.get_json()['reply'], 'تم تعديل التحذير وإنشاء المجموعة.')
        self.assertEqual(chat.get_json()['analysisPatch']['warnings'], ['تحذير معدل'])
        self.assertEqual(chat.get_json()['groupsPatch']['operations'][0]['op'], 'create')
        self.assertEqual(call.call_args.kwargs['model'], 'google/gemini-3.7-flash')

    def test_floor_design_payload_includes_financial_areas_tables_and_explicit_conflicts(self):
        project_data = {
            'approved_financial_area': '٧٬٠٠٠ م²',
            'approved_floor_count': '٥ أدوار',
            'approved_coverage_ratio': '35.5',
            'building_ratio_coverage': 'نسبة البناء 60%، نسبة التغطية ٣٥٫٥٪',
            'setbacks': 'أمامي 6م وخلفي 3م',
            'allowed_uses': 'سكني',
            'regulatory_constraints': 'موقف لكل وحدة',
            'land_and_building_summary': 'ملخص الأرض',
            'boundary_lengths': 'الشمال 100م والجنوب 100م',
            'surrounding_streets': 'شارع شمالي عرض 20م',
            'facades_count': 1,
            'facades_directions': 'شمالية',
            'directions_table': json.dumps({'rows': [
                {'direction': 'شمال', 'boundary': 'شارع', 'length': '100م'},
                {'direction': 'جنوب', 'boundary': 'قطعة مجاورة', 'length': '100م'},
            ]}, ensure_ascii=False),
            'financial_study_model': {
                'inputs': {
                    'landArea': '7,100.00 م2',
                    'coverageRate': '36 %',
                    'floorCount': '6',
                    'builtUpAreaAbove': '12,000',
                    'basementArea': '2,000',
                    'totalBuiltUpArea': '14,000',
                    'coveredArea': '2,556',
                    'openArea': '4,544',
                },
                'dynamicRows': {'components': [
                    {'id': 'c1', 'name': 'سكني', 'builtArea': 9000},
                    {'id': 'c2', 'name': 'تجاري', 'builtArea': 3000},
                ]},
            },
        }
        state = {'floorCount': 6, 'groups': [
            {'id': 'g1', 'name': 'الأدوار', 'floorNumbers': [1, 2, 3, 4, 5, 6]}
        ]}
        payload = self.application_module._sanitize_floor_design_request({
            'projectData': project_data, 'floorDesignState': state
        })

        self.assertEqual(payload['financial']['builtUpAreaAbove'], '12,000')
        self.assertEqual(payload['financial']['totalBuiltUpArea'], '14,000')
        self.assertEqual(payload['financial']['coveredArea'], '2,556')
        self.assertEqual(payload['financial']['openArea'], '4,544')
        self.assertEqual(len(payload['financial']['components']), 2)
        self.assertEqual(len(payload['land']['directions_table']['rows']), 2)
        self.assertEqual(
            {item['key'] for item in payload['data_conflicts']},
            {'approved_area', 'approved_floor_count', 'approved_coverage', 'floor_design_floor_count'},
        )
        for conflict in payload['data_conflicts']:
            self.assertRegex(conflict['note'], 'لا تختر قيمة|لا تزامن المجموعات')

        legacy = self.application_module._sanitize_floor_design_request({
            'projectData': {
                **{key: value for key, value in project_data.items() if key != 'financial_study_model'},
                'financial_calc_data': json.dumps({
                    'landArea': 7000, 'coverageRate': 35.5, 'floorCount': 5,
                    'builtUpAreaAbove': 12000, 'basementArea': 2000,
                    'components': [{'id': 'legacy', 'name': 'قديم', 'builtArea': 12000}],
                }, ensure_ascii=False),
            },
            'floorDesignState': {'floorCount': 5, 'groups': [
                {'id': 'legacy-group', 'name': 'قديم', 'floorNumbers': [1, 2, 3, 4, 5]}
            ]},
        })
        self.assertEqual(legacy['data_conflicts'], [])
        self.assertEqual(legacy['financial']['totalBuiltUpArea'], 14000.0)
        self.assertEqual(legacy['financial']['coveredArea'], 2485.0)
        self.assertEqual(legacy['financial']['openArea'], 4515.0)
        self.assertEqual(legacy['financial']['components'][0]['id'], 'legacy')

    def test_floor_design_saved_groups_conflict_after_approved_floor_count_changes(self):
        state = {'floorCount': 5, 'groups': [
            {'id': 'saved', 'name': 'مجموعات محفوظة', 'floorNumbers': [1, 2, 3, 4, 5], 'prompt': 'وصف محفوظ'}
        ]}
        payload = self.application_module._sanitize_floor_design_request({
            'projectData': {
                'approved_floor_count': 7,
                'financial_study_model': {'inputs': {'floorCount': 7}},
            },
            'floorDesignState': state,
        })

        self.assertEqual(payload['groups'][0]['floorNumbers'], [1, 2, 3, 4, 5])
        conflicts = [item for item in payload['data_conflicts'] if item['key'] == 'floor_design_floor_count']
        self.assertEqual(len(conflicts), 4)
        self.assertEqual(
            {(item['source_a'], item['source_b']) for item in conflicts},
            {
                ('floorDesignState.floorCount', 'بيانات الأرض والكروكي'),
                ('floorDesignState.floorCount', 'الدراسة المالية'),
                ('المدى الفعلي لمجموعات الأدوار', 'بيانات الأرض والكروكي'),
                ('المدى الفعلي لمجموعات الأدوار', 'الدراسة المالية'),
            },
        )
        self.assertTrue(all(float(item['value_b']) == 7 for item in conflicts))

    def test_approved_coverage_conflict_uses_the_dedicated_field(self):
        """Coverage conflicts compare the client-approved ratio, not the regulation prose."""
        module = self.application_module
        # Regulation text alone must not fabricate a coverage conflict.
        _, conflicts = module._floor_design_shared_values(
            {'building_ratio_coverage': 'نسبة التغطية 30%'},
            {'coverageRate': '35'},
        )
        self.assertEqual([item['key'] for item in conflicts], [])
        # The dedicated approved-coverage field is what drives the comparison.
        _, conflicts = module._floor_design_shared_values(
            {'approved_coverage_ratio': '30'},
            {'coverageRate': '35'},
        )
        self.assertEqual([item['key'] for item in conflicts], ['approved_coverage'])

    def test_floor_design_prompt_endpoint_appends_provider_omitted_conflicts(self):
        client = self.app.test_client()
        payload = {
            'projectData': {
                'approved_financial_area': 7000,
                'approved_floor_count': 5,
                'approved_coverage_ratio': 33,
                'building_ratio_coverage': 'نسبة التغطية 35%',
                'setbacks': 'أمامي 6م',
                'allowed_uses': 'سكني',
                'regulatory_constraints': 'موقف لكل وحدة',
                'land_and_building_summary': 'ملخص',
                'boundary_lengths': 'حدود معتمدة',
                'financial_study_model': {
                    'inputs': {'landArea': 7100, 'floorCount': 6, 'coverageRate': 36},
                    'dynamicRows': {'components': [{
                        'id': 'c1', 'name': 'سكني', 'builtArea': 3000,
                        'floorNumbers': [1, 2, 3, 4, 5], 'netArea': 2500,
                    }]},
                },
            },
            'floorDesignState': {'floorCount': 5, 'groups': [
                {'id': 'g1', 'name': 'محفوظ', 'floorNumbers': [1, 2, 3, 4, 5]}
            ]},
            'groupId': 'g1',
            'analysis': {'summary': 'تحليل'},
            'approvedConflictKeys': [
                'approved_area', 'approved_floor_count', 'approved_coverage', 'floor_design_floor_count'
            ],
        }
        provider_result = {'prompt': 'مخطط مقدم من المزود بلا تعارضات', 'negative_prompt': 'بدون نص'}
        with patch.object(self.application_module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': json.dumps(provider_result, ensure_ascii=False)}}]
        }):
            response = client.post('/api/floor-design/prompt', headers=self._headers(self.token_a), json=payload)

        self.assertEqual(response.status_code, 200, response.get_json())
        final_prompt = response.get_json()['prompt']
        self.assertIn('"dataConflicts"', final_prompt)
        self.assertIn('"land_croquis_value": "7000"', final_prompt)
        self.assertIn('"financial_study_value": 7100', final_prompt)
        self.assertIn('floorDesignState.floorCount', final_prompt)
        self.assertIn('لا تختر قيمة أو تعدل بيانات المستخدم', final_prompt)

    def test_floor_design_json_prompt_large_payload_stays_valid_and_keeps_conflicts(self):
        conflict = {
            'key': 'floor_design_floor_count',
            'label': 'تعارض عدد الطوابق',
            'source_a': 'floorDesignState.floorCount',
            'value_a': 5,
            'source_b': 'الدراسة المالية',
            'value_b': 7,
            'note': 'لا تعدل بيانات المستخدم',
        }
        payload = {
            'project': {'project_idea': 'وصف طويل ' * 20000},
            'land': {'land_and_building_summary': 'اشتراط ' * 20000},
            'financial': {'components': [
                {'id': f'c{index}', 'name': 'مكون ' + ('تفصيل ' * 2000), 'builtArea': index}
                for index in range(100)
            ]},
            'shared_values': {'approved_floor_count': {'financial_study_value': 7}},
            'data_conflicts': [conflict],
            'groups': [
                {'id': f'g{index}', 'name': f'مجموعة {index}', 'floorNumbers': [index + 1],
                 'description': 'وصف مجموعة ' * 3000, 'components': list(range(100))}
                for index in range(200)
            ],
        }

        encoded = self.application_module._floor_design_json_prompt(payload)
        decoded = json.loads(encoded)
        self.assertLessEqual(len(encoded), 90000)
        self.assertEqual(decoded['data_conflicts'], [conflict])
        self.assertIn('project', decoded)
        self.assertIn('land', decoded)
        self.assertIn('financial', decoded)
        self.assertIn('groups', decoded)

    def test_floor_design_geometry_space_program_and_page_preparation_are_deterministic(self):
        module = self.application_module
        land = {
            'survey_coordinates': [
                {'point': 'A', 'x': 1000, 'y': 2000},
                {'point': 'B', 'x': 1040, 'y': 2000},
                {'point': 'C', 'x': 1040, 'y': 2030},
                {'point': 'D', 'x': 1000, 'y': 2030},
            ],
            'directions_table': {'rows': [
                {'direction': 'south', 'setback': 2},
                {'direction': 'east', 'setback': 3},
                {'direction': 'north', 'setback': 4},
                {'direction': 'west', 'setback': 5},
            ]},
            'setbacks': 'Approved edge setbacks',
        }
        geometry = module._floor_design_polygon_geometry(land)
        self.assertEqual(geometry['coordinateMode'], 'local_or_projected_meters')
        self.assertEqual(geometry['areaSqm'], 1200.0)
        self.assertEqual([edge['computedLength'] for edge in geometry['edges']], [40.0, 30.0, 40.0, 30.0])
        setbacks = module._floor_design_setback_spec(land, geometry)
        self.assertEqual(setbacks['buildableEnvelopeStatus'], 'computed_axis_aligned_rectangle')
        self.assertEqual(setbacks['buildableEnvelope']['areaSqm'], 768.0)
        self.assertEqual(module._floor_design_allocate_rounded(100, [1, 1, 1]), [33.34, 33.33, 33.33])
        self.assertEqual(module._floor_design_allocate_rounded(100, []), [])

        group = {'id': 'g1', 'name': 'Typical', 'floorNumbers': [1, 2], 'description': '', 'components': []}
        payload = {
            'project': {}, 'land': land, 'data_conflicts': [], 'groups': [group],
            'financial': {'components': [
                {'id': 'c1', 'name': 'Residential', 'builtArea': 100, 'netArea': 80, 'floorNumbers': [1, 2]},
                {'id': 'c2', 'name': 'Retail', 'floorAreas': {'1': 25, '2': 35}},
            ]},
        }
        prepared = module._floor_design_prepare(payload, group)
        self.assertEqual(len(prepared['pages']), 1)
        self.assertEqual([page['pageType'] for page in prepared['pages']], ['typical_floor'])
        self.assertEqual(prepared['pages'][0]['floorNumbers'], [1, 2])
        self.assertEqual(prepared['pages'][0]['title'], 'FLOORS 1-2 TYPICAL PLAN')
        first_program = prepared['pages'][0]['spaceProgram']
        self.assertEqual(first_program['grossAreaSqm'], 75.0)
        self.assertEqual(sum(item['percentage'] for item in first_program['components']), 100.0)
        self.assertIsNone(first_program['netAreaSqm'])
        self.assertIn('net_area_without_approved_net_rule', first_program['unavailableCalculations'])

    def test_floor_design_components_without_floor_assignment_span_the_group_evenly(self):
        module = self.application_module
        group = {'id': 'g1', 'name': 'Typical', 'floorNumbers': [1, 2, 3, 4], 'description': '', 'components': []}
        payload = {'financial': {'components': [
            {'id': 'c1', 'name': 'Residential', 'builtArea': 400},
        ]}}
        for floor_number in (1, 2, 3, 4):
            program = module._floor_design_space_program(payload, group, floor_number)
            self.assertEqual(program['missingRequirements'], [])
            self.assertEqual(len(program['components']), 1)
            self.assertEqual(program['components'][0]['grossAreaSqm'], 100.0)
            self.assertEqual(program['grossAreaSqm'], 100.0)

    def test_floor_design_residential_units_are_explicit_and_page_scope_excludes_group_range(self):
        module = self.application_module
        group = {
            'id': 'g1', 'name': 'شقق سكنية', 'description': 'يوجد في الطابق الواحد تقريبا 1000 وحدة سكنية',
            'floorNumbers': [2, 3, 4],
        }
        payload = {
            'financial': {'components': [{
                'id': 'apt', 'name': 'شقة', 'useType': 'residential', 'units': 1000,
                'unitArea': 18.37, 'builtArea': 18.37,
            }]},
            'land': {}, 'project': {}, 'data_conflicts': [],
        }
        program = module._floor_design_space_program(payload, group, 2)
        row = program['components'][0]
        self.assertEqual(row['unitsPerFloor'], 1000)
        self.assertEqual(row['unitAreaSqm'], 18.37)
        self.assertEqual(row['layoutType'], 'repeated_residential_units')
        self.assertEqual(row['requiredUnitLayoutAreaSqm'], 18370.0)
        self.assertIn('residential_unit_area_conflict', program['unavailableCalculations'])
        self.assertTrue(program['residentialLayout']['required'])

        prepared = {'geometry': {}, 'setbacks': {}, 'siteContext': {}, 'pages': []}
        page = {'pageType': 'floor', 'floorNumber': 2, 'floorNumbers': [2], 'title': 'FLOOR 2 PLAN', 'spaceProgram': program}
        spec_text = module._floor_design_page_specification(page, prepared, payload, group)
        spec_json = spec_text.split('\n', 1)[1].rsplit('\nEND MANDATORY SERVER ENGINEERING SPECIFICATION', 1)[0]
        spec = json.loads(spec_json)
        self.assertNotIn('floorNumbers', spec['group'])
        self.assertNotIn('floorCount', spec['financialTotals'])
        self.assertEqual(spec['pageScope']['representativeFloor'], 2)
        self.assertFalse(spec['pageScope']['renderOtherFloors'])
        self.assertIn('residentialLayout.required', '\n'.join(spec['drawingRules']))

    def test_floor_design_geographic_conversion_and_preflight_require_explicit_approvals(self):
        module = self.application_module
        geometry = module._floor_design_polygon_geometry({'survey_coordinates': [
            {'longitude': 31.0000, 'latitude': 30.0000},
            {'longitude': 31.0010, 'latitude': 30.0000},
            {'longitude': 31.0010, 'latitude': 30.0010},
        ]})
        self.assertEqual(geometry['coordinateMode'], 'geographic_converted_local_meters')
        self.assertGreater(geometry['areaSqm'], 5000)
        rejected = module._floor_design_polygon_geometry({'survey_coordinates': [
            {'point': 'A', 'first': 1, 'second': 2},
            {'point': 'B', 'first': 2, 'second': 2},
            {'point': 'C', 'first': 2, 'second': 3},
        ]})
        self.assertEqual(rejected['calculationStatus'], 'unavailable')

        prepared = {
            'geometry': {'calculationStatus': 'computed', 'missingItems': [], 'sourceLengthConflicts': [
                {'edge': 1, 'sourceLength': 10, 'computedLength': 11}
            ]},
            'setbacks': {'requirements': []},
            'pages': [{'pageType': 'floor', 'floorNumber': 1, 'spaceProgram': {
                'components': [{'id': 'c1'}], 'missingRequirements': [], 'unavailableCalculations': []
            }}],
        }
        payload = {
            'project': {'project_name': 'Test', 'project_type': 'Residential', 'project_idea': 'Idea', 'project_goal': 'Goal'},
            'land': {'building_ratio_coverage': '35%', 'setbacks': '6 m', 'allowed_uses': 'Residential',
                     'regulatory_constraints': 'Parking', 'land_and_building_summary': 'Summary'},
            'financial': {'approved_financial_area': 1000, 'approved_floor_count': 1, 'components': [{'id': 'c1'}]},
            'groups': [{'id': 'g1'}],
            'data_conflicts': [{'key': 'approved_area'}],
        }
        blocked = module._floor_design_preflight(payload, prepared, {'analysisApproved': True})
        self.assertFalse(blocked['ok'])
        self.assertEqual(len(blocked['blockedItems']), 2)
        approved = module._floor_design_preflight(payload, prepared, {
            'approvedConflictKeys': ['approved_area', 'source_length_edge_1']
        })
        self.assertTrue(approved['ok'])

    def test_floor_design_prompt_normalization_and_frontend_keep_independent_pages(self):
        module = self.application_module
        group = {'id': 'g1', 'name': 'Typical', 'description': '', 'floorNumbers': [1, 2]}
        payload = {'project': {}, 'land': {}, 'financial': {}, 'data_conflicts': [], 'groups': [group]}
        prepared = {'geometry': {}, 'setbacks': {}, 'siteContext': {}, 'pages': [
            {'pageType': 'typical_floor', 'floorNumber': 1, 'floorNumbers': [1, 2], 'floorRange': '1-2', 'title': 'FLOORS 1-2 TYPICAL PLAN', 'spaceProgram': {}},
        ]}
        pages = module._floor_design_normalize_prompt_pages(
            {'pages': [{'pageType': 'typical_floor', 'floorNumber': 1, 'prompt': 'Provider group plan'}]},
            prepared, payload, group,
        )
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0]['prompt'].startswith('Create one representative typical-floor architectural presentation page for FLOORS 1-2'))
        self.assertTrue(all('MANDATORY SERVER ENGINEERING SPECIFICATION' in page['prompt'] for page in pages))
        self.assertNotIn('Provider group plan', pages[0]['prompt'])

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('const legacyPage = group?.generatedPrompt || group?.imageUrl || group?.approvedImageUrl', index_source)
        self.assertIn('group.pages = response.pages.map((item, index)', index_source)
        self.assertIn('for (let index = 0; index < group.pages.length; index += 1)', index_source)
        self.assertIn('page.approvedImageUrl = page.imageUrl', index_source)
        self.assertIn('tenantFloorDesignActivePageIndex', index_source)
        self.assertIn('const TENANT_FLOOR_DESIGN_PROMPT_VERSION = 3', index_source)
        self.assertIn('dir="ltr"', index_source)
        self.assertIn('unicode-bidi: plaintext', index_source)
        self.assertIn('const pagesAreCurrent =', index_source)

    def test_floor_design_single_floor_and_range_parsing(self):
        module = self.application_module
        # Range parsing
        self.assertEqual(module._parse_floor_numbers_range('2-50'), list(range(2, 51)))
        self.assertEqual(module._parse_floor_numbers_range('1, 3-5, 10'), [1, 3, 4, 5, 10])
        self.assertEqual(module._parse_floor_numbers_range('الأدوار 2-10'), list(range(2, 11)))
        self.assertEqual(module._parse_floor_numbers_range('1'), [1])

        # Single floor vs multi-floor prompt generation
        client = self.app.test_client()
        single_group = {'id': 'g_single', 'name': 'الدور 1', 'floorNumbers': [1]}
        multi_group = {'id': 'g_multi', 'name': 'الأدوار 2-50 (شقق سكنية)', 'floorNumbers': list(range(2, 51))}
        project_data = {
            'project_name': 'برج سكني', 'project_type': 'سكني', 'project_idea': 'فكرة', 'project_goal': 'هدف',
            'building_ratio_coverage': '35%', 'setbacks': '6 م', 'allowed_uses': 'سكني مسموح',
            'regulatory_constraints': 'مواقف سيارات', 'land_and_building_summary': 'ملخص الأرض',
            'boundary_lengths': '100م, 100م, 100م, 100م', 'surrounding_streets': 'شارع 30م',
            'facades_count': 1, 'facades_directions': 'شمال', 'max_floors_height': '50 دور',
            'approved_financial_area': 50000, 'approved_floor_count': 50,
            'project_components_data': json.dumps([
                {'id': 'c_res', 'name': 'شقق سكنية', 'area': 49000, 'useType': 'residential', 'units': 200, 'unitArea': 245, 'floors': '2-50'},
            ], ensure_ascii=False)
        }
        floor_design_state = {
            'floorCount': 50,
            'groups': [single_group, multi_group],
        }

        # Single floor prompt generation (Floor 1 has no explicit residential component, should use fallback services and not crash)
        single_payload = {'projectData': project_data, 'floorDesignState': floor_design_state, 'groupId': single_group['id']}
        res_single = client.post('/api/floor-design/prompt', headers=self._headers(self.token_a), json=single_payload)
        self.assertEqual(res_single.status_code, 200, res_single.get_json())
        single_data = res_single.get_json()
        self.assertTrue(single_data['success'])
        self.assertEqual(len(single_data['pages']), 1)
        self.assertEqual(single_data['pages'][0]['pageType'], 'floor')
        self.assertEqual(single_data['pages'][0]['floorNumber'], 1)

        # Multi-floor prompt generation
        multi_payload = {'projectData': project_data, 'floorDesignState': floor_design_state, 'groupId': multi_group['id']}
        res_multi = client.post('/api/floor-design/prompt', headers=self._headers(self.token_a), json=multi_payload)
        self.assertEqual(res_multi.status_code, 200, res_multi.get_json())
        multi_data = res_multi.get_json()
        self.assertTrue(multi_data['success'])
        self.assertEqual(len(multi_data['pages']), 1)
        self.assertEqual(multi_data['pages'][0]['pageType'], 'typical_floor')
        self.assertEqual(multi_data['pages'][0]['floorNumbers'], list(range(2, 51)))

    def test_floor_design_image_generation_forces_cached_system_reference(self):
        client = self.app.test_client()
        generated = 'data:image/png;base64,AAAA'
        with patch.object(self.application_module, '_floor_design_default_reference_data_uri', return_value='data:image/png;base64,SYSTEM'), \
                patch.object(self.application_module, 'call_openrouter_image_generation', return_value=(generated, None)) as call, \
                patch.object(self.application_module, 'persist_generated_image', return_value='/uploads/creative/generated.png'):
            response = client.post('/api/floor-design/generate', headers=self._headers(self.token_a), json={
                'prompt': 'Complete presentation page', 'referenceImage': 'data:image/png;base64,USER',
                'approvedFinancialArea': 1000, 'approvedFloorCount': 2,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(call.call_args.args[2], 'data:image/png;base64,SYSTEM')
        self.assertEqual(response.get_json()['reference'], 'system_floor_plan_style')

        with patch.object(self.application_module, '_floor_design_default_reference_data_uri', return_value=None), \
                patch.object(self.application_module, 'call_openrouter_image_generation', return_value=(generated, None)) as fallback_call, \
                patch.object(self.application_module, 'persist_generated_image', return_value='/uploads/creative/generated.png'):
            fallback = client.post('/api/floor-design/generate', headers=self._headers(self.token_a), json={
                'prompt': 'Complete presentation page without local reference',
                'approvedFinancialArea': 1000, 'approvedFloorCount': 2,
                'referenceImage': 'data:image/png;base64,USER_REFERENCE_MUST_BE_IGNORED',
            })
        self.assertEqual(fallback.status_code, 200, fallback.get_json())
        self.assertIsNone(fallback_call.call_args.args[2])
        self.assertEqual(fallback.get_json()['reference'], 'prompt_only_no_reference')

        too_long = client.post('/api/floor-design/generate', headers=self._headers(self.token_a), json={
            'prompt': 'x' * 30001, 'approvedFinancialArea': 1000, 'approvedFloorCount': 2,
        })
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(too_long.get_json()['error_code'], 'PROMPT_TOO_LONG')

    def test_floor_design_numeric_conflicts_handle_arabic_units_percentages_and_empty_values(self):
        check = self.application_module._floor_design_values_conflict
        self.assertEqual(check('٧٬٠٠٠ م²', '7,000.00 متر')[0], False)
        self.assertEqual(check('نسبة التغطية ٣٥٫٥٪', '35.50 %', coverage=True)[0], False)
        self.assertEqual(check('نسبة البناء 60% ونسبة التغطية 35%', '36%', coverage=True)[0], True)
        self.assertEqual(check('5 أدوار', '٦ طوابق')[0], True)
        self.assertEqual(check('', '35%', coverage=True)[0], False)
        self.assertEqual(check('غير محدد', None)[0], False)
        self.assertEqual(check('7000.0 م2', '7005 م2')[0], False)
        self.assertEqual(check('7000 م2', '7010 م2')[0], True)

    def test_floor_design_generation_requires_auth_and_valid_prompt(self):
        client = self.app.test_client()
        unauthenticated = client.post('/api/floor-design/generate', json={'prompt': 'تصميم'})
        self.assertEqual(unauthenticated.status_code, 401)

        missing_prompt = client.post('/api/floor-design/generate', headers=self._headers(self.token_a), json={})
        self.assertEqual(missing_prompt.status_code, 400, missing_prompt.get_json())
        self.assertEqual(missing_prompt.get_json()['error_code'], 'PROMPT_REQUIRED')

        missing_build_inputs = client.post('/api/floor-design/generate', headers=self._headers(self.token_a), json={
            'prompt': 'تصميم دور نموذجي'
        })
        self.assertEqual(missing_build_inputs.status_code, 400, missing_build_inputs.get_json())
        self.assertEqual(missing_build_inputs.get_json()['error_code'], 'APPROVED_BUILD_INPUTS_REQUIRED')
        self.assertEqual(set(missing_build_inputs.get_json()['missingFields']), {'approved_financial_area', 'approved_floor_count'})

        invalid_reference = client.post('/api/floor-design/generate', headers=self._headers(self.token_a), json={
            'prompt': 'تصميم دور نموذجي',
            'approvedFinancialArea': 1000,
            'approvedFloorCount': 5,
            'referenceImage': 'https://example.com/image.png'
        })
        self.assertEqual(invalid_reference.status_code, 400, invalid_reference.get_json())
        self.assertEqual(invalid_reference.get_json()['error_code'], 'REFERENCE_INVALID')

    def test_market_study_fields_and_section_are_wired(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("function addMarketStudySection(form, before)", index_source)
        self.assertIn("addMarketStudySection(form);", index_source)
        self.assertIn("id = 'section-market-study'", index_source)
        self.assertIn("data-key=\"market_study_data\"", index_source)
        self.assertIn("function runMarketCompetitorsJob(mode)", index_source)
        self.assertIn("function runMarketSummaryJob()", index_source)
        self.assertIn('<th>القيمة (ر.س)</th>', index_source)
        self.assertIn('const visibleRows = Array.isArray(rows) && rows.length ? rows : [{}];', index_source)
        self.assertIn('function inferCompetitorPriceType(row = {})', index_source)
        self.assertIn('min-width: 1450px;', index_source)
        self.assertIn('<textarea data-field="name" rows="2">', index_source)
        self.assertIn('<textarea data-field="note" rows="2">', index_source)
        self.assertIn("tr.querySelectorAll('input,select,textarea')", index_source)
        self.assertNotIn('<select data-field="classification">', index_source)
        self.assertIn('data-currency="SAR"', index_source)
        self.assertIn('placeholder="من (ر.س)"', index_source)
        self.assertIn('#section-market-study th {', index_source)
        self.assertIn('color: var(--ink);', index_source)
        self.assertIn("function renderMarketSummaryCompare(current, incoming, currentSwot, incomingSwot)", index_source)
        self.assertIn('/api/market-study/competitors', index_source)
        self.assertIn('/api/market-study/summary', index_source)
        self.assertIn('/api/market-study/jobs/', index_source)
        self.assertIn('function enhanceProjectClassificationFields()', index_source)
        self.assertIn("id = 'projectAudienceGrid'", index_source)
        self.assertIn('id="marketCityMirror"', index_source)
        self.assertIn('const MARKET_GENERAL_AUDIENCE', index_source)
        self.assertIn('if (audienceWrap) audienceWrap.style.display = \'none\';', index_source)
        self.assertIn('function audienceOptionsForMain(main, subtype)', index_source)
        self.assertIn("const MARKET_GENERAL_AUDIENCE = ['أفراد', 'عائلات', 'مستثمرون', 'شركات', 'جهات حكومية', 'سياح وزوار', 'مشغلون ومستأجرون'];", index_source)
        self.assertIn('const MARKET_STUDY_SWOT_SECTIONS', index_source)
        self.assertIn("id=\"marketSwotFields\"", index_source)
        self.assertIn('تحليل SWOT', index_source)
        self.assertNotIn('const MARKET_OTHER_TYPE_OPTIONS', index_source)
        self.assertNotIn("id = 'projectOtherTypesGrid'", index_source)
        self.assertIn("id = 'projectTypeGrid'", index_source)
        self.assertIn("keepProjectMultiSelectOpen('projectTypeGrid')", index_source)
        self.assertIn('function persistProjectTypes(values)', index_source)
        self.assertIn("id = 'projectSubtypeGrid'", index_source)
        self.assertIn("id = 'projectActivityClassFields'", index_source)
        self.assertIn('function renderMultiSelectDropdown(host, options, selected, placeholder, onChange, closeAfterSelection = false)', index_source)
        self.assertIn('function keepProjectMultiSelectOpen(hostId)', index_source)
        self.assertIn('function closeOtherProjectMultiSelects(current)', index_source)
        self.assertIn('function refreshClassificationDependents()', index_source)
        self.assertNotIn("keepProjectMultiSelectOpen('projectSubtypeGrid')", index_source)
        self.assertIn('class="project-multi-select-option', index_source)
        self.assertIn("host.querySelectorAll('.project-multi-select-option')", index_source)
        self.assertNotIn('function reopenProjectMultiSelect', index_source)
        self.assertIn('function normalizeProjectTypeValue(raw)', index_source)
        self.assertIn('function applyProjectTypeSelect(input, raw)', index_source)
        self.assertIn('function selectedProjectTypeMains()', index_source)
        self.assertIn('function selectedProjectSubtypesByMain()', index_source)
        self.assertIn('function renderGroupedAudienceFields(mains, hidden, host)', index_source)
        self.assertIn('function audienceGroupInfo(main, subtype)', index_source)
        self.assertIn('function audienceValuesForGroup(current, group)', index_source)
        self.assertIn("groups.find(item => item.kind === info.kind)", index_source)
        self.assertIn('const MARKET_PROJECT_LEVELS', index_source)
        self.assertIn('function classificationGroupsForProject(mains, isOther, kinds)', index_source)
        self.assertNotIn('      kinds.forEach(addGroup);', index_source)
        self.assertIn("if (f.fieldKey === 'project_type') {", index_source)
        self.assertNotIn('otherHost.hidden = !isOther;', index_source)
        self.assertNotIn('🎯', index_source)

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("import market_study", app_source)
        self.assertIn("@app.route('/api/market-study/competitors'", app_source)
        self.assertIn("{'type': 'openrouter:web_search'", app_source)
        self.assertIn('def _start_market_job(kind, executor):', app_source)

        self.assertIn('project_idea', {field['key'] for field in db.PREBUILT_FIELDS})
        self.assertNotIn('project_idea', db.REMOVED_PREBUILT_FIELDS)

    def test_market_study_merge_keeps_client_rows(self):
        import market_study
        existing = [{
            'id': 'keep-me',
            'name': 'مشروع العميل',
            'project_type': 'سكني',
            'status': 'قائم',
            'source': 'العميل',
            'row_source': 'manual',
        }]
        generated = [
            {'name': 'مشروع العميل', 'price_value': '1200000', 'source': 'منصة عقار'},
            {'name': 'منافس جديد', 'classification': 'مباشر', 'status': 'تحت الإنشاء'},
        ]
        merged, added, updated = market_study.merge_generated_competitors(existing, generated, mode='generate')
        self.assertEqual(added, 2)
        self.assertEqual(updated, 0)
        self.assertEqual([row['name'] for row in merged], ['مشروع العميل', 'منافس جديد'])
        self.assertEqual(merged[0]['source'], 'منصة عقار')
        self.assertEqual(len(merged), 2)

        filled, added_fill, updated_fill = market_study.merge_generated_competitors(
            existing, [
                {'name': 'مشروع العميل', 'price_value': '1200000', 'source': 'منصة عقار'},
                {'name': 'اسم غير موجود', 'status': 'قائم'},
            ], mode='fill'
        )
        self.assertEqual(added_fill, 0)
        self.assertEqual(updated_fill, 1)
        self.assertEqual([row['name'] for row in filled], ['مشروع العميل'])
        self.assertEqual(filled[0]['id'], 'keep-me')
        self.assertEqual(filled[0]['source'], 'العميل')
        self.assertEqual(filled[0]['price_value'], '1200000')

    def test_market_study_prefers_exact_page_urls_over_homepages(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'برج تجاري',
            'source': 'منصة عقار',
            'source_url': 'https://sa.aqar.fm/',
            'url': 'https://sa.aqar.fm/apartment-for-sale/12345',
        })
        self.assertEqual(row['source_url'], 'https://sa.aqar.fm/apartment-for-sale/12345')
        summary = market_study.normalize_summary({
            'decision': 'البيانات غير كافية',
            'sources': [{
                'name': 'الهيئة العامة للإحصاء',
                'url': 'https://www.stats.gov.sa/',
                'source_url': 'https://www.stats.gov.sa/statistics/housing-2024',
            }],
        })
        self.assertEqual(summary['sources'][0]['url'], 'https://www.stats.gov.sa/statistics/housing-2024')
        prompt = market_study.build_consultant_system_prompt()
        self.assertIn('رابط الصفحة بالضبط', prompt)

    def test_market_study_radius_auto_is_ten_km(self):
        import market_study
        self.assertNotIn('auto', [item['value'] for item in market_study.COMPETITOR_RADIUS_OPTIONS])
        self.assertEqual(market_study.resolve_competitor_radius_km(None), 10)
        self.assertEqual(market_study.resolve_competitor_radius_km('auto'), 10)
        self.assertEqual(market_study.resolve_competitor_radius_km('custom', 7), 7)
        self.assertIsNone(market_study.resolve_competitor_radius_km('city'))
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('تلقائي حسب نوع المشروع', index_source)
        self.assertIn('<option value="10" selected>10 كم</option>', index_source)

    def test_market_study_retries_without_tools_and_json_mode(self):
        module = self.application_module
        responses = [
            {'error': {'message': 'web search response was empty'}},
            {'choices': [{'message': {'content': 'not valid json'}}]},
            {'choices': [{'message': {'content': '{"competitors": []}'}}]},
        ]
        calls = []

        def fake_call(system_prompt, user_content, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call) as call:
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)

        self.assertTrue(module._has_chat_choices(response))
        self.assertEqual(call.call_count, 3)
        self.assertIsNotNone(calls[0]['tools'])
        self.assertEqual(calls[0]['response_format'], {'type': 'json_object'})
        self.assertIsNone(calls[1]['tools'])
        self.assertEqual(calls[1]['response_format'], {'type': 'json_object'})
        self.assertIsNone(calls[2]['tools'])
        self.assertIsNone(calls[2]['response_format'])
        self.assertEqual(error, '')

    def test_market_study_lowers_token_cap_when_credit_is_limited(self):
        module = self.application_module
        refusal = {'error': {'message': 'You requested up to 6000 tokens, but can only afford 3000'}}
        success = {'choices': [{'message': {'content': '{"competitors": []}'}}]}
        caps = []

        def fake_call(system_prompt, user_content, **kwargs):
            caps.append(kwargs['max_tokens'])
            return refusal if len(caps) == 1 else success

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call):
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)

        self.assertTrue(module._has_chat_choices(response))
        self.assertEqual(error, '')
        self.assertEqual(caps, [6000, 2550])

    def test_market_study_endpoints_queue_or_run_without_deleting_rows(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        fake = {
            'competitors': [
                {'name': 'برج الشمال', 'project_type': 'سكني', 'classification': 'مباشر', 'status': 'قائم', 'source': 'موقع المطور'}
            ]
        }
        with patch.object(self.application_module, '_call_market_study_model', return_value=(
            {'choices': [{'message': {'content': json.dumps(fake, ensure_ascii=False)}}]},
            '',
        )):
            generated = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني',
                'city': 'الرياض',
                'mode': 'generate',
                'competitors': [{'id': 'c1', 'name': 'منافس العميل', 'row_source': 'manual'}],
            })
            filled = client.post('/api/market-study/competitors', headers=headers, json={
                'projectType': 'سكني',
                'city': 'الرياض',
                'mode': 'fill',
                'competitors': [{'id': 'c1', 'name': 'منافس العميل', 'row_source': 'manual'}],
            })
        self.assertEqual(generated.status_code, 200, generated.get_json())
        generated_names = [row['name'] for row in generated.get_json()['competitors']]
        self.assertEqual(generated_names, ['برج الشمال'])
        self.assertEqual(filled.status_code, 200, filled.get_json())
        filled_names = [row['name'] for row in filled.get_json()['competitors']]
        self.assertEqual(filled_names, ['منافس العميل'])

        catalog = client.get('/api/market-study/catalog', headers=headers)
        self.assertEqual(catalog.status_code, 200)
        self.assertIn('سكني', catalog.get_json()['catalog']['projectTypes'])
        self.assertEqual(
            [item['key'] for item in catalog.get_json()['catalog']['swotSections']],
            ['strengths', 'weaknesses', 'opportunities', 'threats']
        )

        missing = client.get('/api/market-study/jobs/not-a-job-id-xxx', headers=headers)
        self.assertEqual(missing.status_code, 404)

    def test_market_source_priority_matches_owner_order(self):
        import market_study
        expected = {
            1: [
                'الهيئة العامة للعقار', 'منصة المؤشرات العقارية',
                'السجل العقاري وبيانات وزارة العدل المتاحة', 'شبكة إيجار',
                'الهيئة العامة للإحصاء', 'منصة البيانات المفتوحة السعودية',
                'وزارة البلديات والإسكان', 'منصة بلدي', 'الأمانة التابعة للمدينة',
                'كود البناء السعودي', 'البنك المركزي السعودي', 'برنامج وافي',
                'منصة سكني', 'الشركة الوطنية للإسكان NHC',
            ],
            2: [
                'موقع المشروع الرسمي', 'موقع المطور الرسمي', 'موقع المشغل الرسمي',
                'موقع العلامة الفندقية', 'كتيب المشروع الرسمي', 'بيانات البيع الرسمية',
                'بيانات تداول للشركات والصناديق العقارية', 'الإعلانات الرسمية للمطور',
            ],
            3: ['CBRE', 'JLL', 'Knight Frank', 'Colliers', 'Savills', 'ValuStrat',
                'Deloitte', 'PwC', 'KPMG', 'EY', 'STR', 'CoStar'],
            4: ['منصة عقار', 'بيوت السعودية', 'وصلت', 'تطبيق ديل',
                'منصات المسوقين العقاريين المرخصين'],
            5: ['Google Maps', 'Google Places', 'المواقع الإخبارية الموثوقة',
                'وكالة الأنباء السعودية', 'البيانات الصحفية الرسمية'],
        }
        self.assertEqual(market_study.SOURCE_PRIORITY, expected)
        expected_type_sources = {
            'سكني': [
                'منصة المؤشرات العقارية وبيانات الصفقات الفعلية', 'الهيئة العامة للإحصاء',
                'البنك المركزي السعودي', 'وافي', 'سكني وNHC', 'الأمانة وبلدي',
                'المواقع الرسمية للمطورين', 'تقارير CBRE وJLL وKnight Frank وColliers',
                'منصات الإعلانات العقارية', 'Google Maps للموقع والخدمات فقط',
            ],
            'تجاري': [
                'منصة المؤشرات العقارية وشبكة إيجار', 'الهيئة العامة للإحصاء', 'وزارة التجارة',
                'الأمانة وبلدي', 'البنك المركزي السعودي',
                'المواقع الرسمية للمراكز والمشروعات التجارية', 'تداول وتقارير الصناديق العقارية',
                'CBRE وJLL وKnight Frank وColliers وSavills', 'منصات التأجير والإعلانات',
                'Google Maps وGoogle Places للخدمات والتقييمات',
            ],
            'فندقي': [
                'وزارة السياحة', 'الهيئة العامة للإحصاء وإحصاءات المنشآت السياحية',
                'الهيئة العامة للطيران المدني', 'الجهات الرسمية للفعاليات والسياحة في المدينة',
                'المواقع الرسمية للفنادق والمشغلين', 'STR أو CoStar',
                'CBRE وJLL وKnight Frank وColliers', 'مواقع الحجز لمقارنة السعر في تاريخ محدد فقط',
                'Google Maps للتقييمات والموقع والخدمات',
            ],
            'صناعي ولوجستي': [
                'وزارة الصناعة والثروة المعدنية',
                'الهيئة السعودية للمدن الصناعية ومناطق التقنية مدن', 'خرائط مدن GIS',
                'هيئة المدن والمناطق الاقتصادية الخاصة', 'الهيئة العامة للإحصاء',
                'الهيئة العامة للموانئ', 'الهيئة العامة للطيران المدني للشحن الجوي',
                'وزارة النقل والخدمات اللوجستية', 'الأمانة وبلدي',
                'المواقع الرسمية للمدن الصناعية والمشروعات',
                'تقارير CBRE وJLL وKnight Frank وColliers', 'منصات المستودعات والعقارات الصناعية',
            ],
        }
        self.assertEqual(market_study.TYPE_SOURCE_PRIORITY, expected_type_sources)
        self.assertEqual(market_study.catalog_payload()['sourcePriority'], expected)
        self.assertEqual(market_study.catalog_payload()['typeSourcePriority'], expected_type_sources)
        prompt = market_study.build_consultant_system_prompt()
        self.assertIn('ابدأ بالمستوى الأول، ولا تنتقل إلى مستوى أدنى', prompt)
        self.assertIn('تعامل مع أسعار منصات الإعلانات باعتبارها أسعار طلب وليست صفقات منفذة.', prompt)

    def test_target_audience_options_do_not_include_other(self):
        import market_study
        self.assertNotIn('أخرى', market_study.GENERAL_TARGET_AUDIENCE)
        self.assertNotIn('أخرى', market_study.target_audience_options('سكني'))
        self.assertNotIn('أخرى', market_study.target_audience_options('تجاري', 'مكاتب'))
        self.assertEqual(
            market_study.activity_class_options('سكني'),
            [item['label'] for item in market_study.PROJECT_LEVELS]
        )

    def test_mixed_use_unlocks_selected_subtypes(self):
        import market_study
        self.assertEqual(
            market_study.analysis_kind_for_project('متعدد الاستخدامات', '', ['مكاتب', 'فندق']),
            ['مكاتب', 'فندقي']
        )
        self.assertEqual(
            market_study.activity_class_options('متعدد الاستخدامات', '', ['مكاتب', 'فندق']),
            market_study.ACTIVITY_CLASS_BY_TYPE['مكاتب'] + [
                option for option in market_study.ACTIVITY_CLASS_BY_TYPE['فندقي']
                if option not in market_study.ACTIVITY_CLASS_BY_TYPE['مكاتب']
            ]
        )

    def test_market_study_normalizes_swot_independently_of_summary(self):
        import market_study
        parsed = market_study.normalize_summary({
            'summary': {'market_definition': 'سوق سكني في الرياض', 'decision': 'فرصة واعدة بشروط'},
            'swot': {
                'strengths': 'موقع على طريق رئيسي',
                'weaknesses': 'مساحة الأرض محدودة',
                'opportunities': 'نقص المعروض المناسب',
                'threats': 'مشروعات جديدة قريبة',
            },
            'decision': 'فرصة واعدة بشروط',
            'sources': [{'name': 'الهيئة العامة للإحصاء', 'url': 'https://www.stats.gov.sa'}],
        })
        self.assertEqual(parsed['title'], 'الملخص التنفيذي لسوق المشروع')
        self.assertEqual(parsed['swot']['strengths'], 'موقع على طريق رئيسي')
        self.assertEqual(parsed['swot']['threats'], 'مشروعات جديدة قريبة')
        self.assertEqual(parsed['summary']['market_definition'], 'سوق سكني في الرياض')
        self.assertEqual(parsed['summary']['city_position'], market_study.MISSING_VALUE_PHRASE)
        self.assertEqual(parsed['decision'], 'فرصة واعدة بشروط')
        self.assertIn('ابدأ المخرجات بعنوان: الملخص التنفيذي لسوق المشروع.', market_study.build_summary_user_prompt({}, []))
        self.assertIn('في حدود 500 كلمة', market_study.build_summary_user_prompt({}, []))
        self.assertIn('مصادر حالية إن وُجدت', market_study.build_summary_user_prompt({}, []))


if __name__ == '__main__':
    unittest.main()
