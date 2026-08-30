"""Regression checks for the meeting requirements implemented in this change.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import base64
import gzip
import math
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

        # The old cap of 17 left a 7,000 sqm plot as a dot on the slide. The croquis boundary
        # is exact, so the plot view may go to 19 while the context views stay wider.
        self.assertLessEqual(zooms['overview'], 19)
        self.assertEqual(zooms['landmarks'], max(14, min(17, zooms['overview'] - 2)))
        self.assertEqual(zooms['access'], max(15, min(17, zooms['overview'])))
        self.assertEqual(self.application_module.maps_service.access_map_zoom(21.63, 19), 16)
        self.assertLessEqual(zooms['catchment'], 14)

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

    FULL_PROJECT = {
        'project_name': 'THE VIEW',
        'project_type': ['سكني', 'فندقي'],
        'project_idea': 'برج على كورنيش جدة يجمع الشقق السكنية والغرف الفندقية.',
        'target_audience': {'audience::سكني': ['أصحاب الثروات'], 'audience::فندقي': ['سياح الأعمال']},
        'location_address': 'https://maps.google.com/?q=21.6,39.1',
        'location_lat': '21.6', 'location_lng': '39.1', 'city': 'جدة', 'district': 'الشاطئ',
        'main_roads': 'طريق الكورنيش — 1.6 كم',
        'secondary_roads': 'شارع غير نافذ 20م',
        'nearby_landmarks': 'ريد سي مول — 1.9 كم — 4 دقائق',
        'city_landmarks': 'جدة التاريخية — 21.9 كم',
        'catchment_areas': 'مطار الملك عبدالعزيز — 25.9 كم — 37 دقائق',
        'croquis_land_area': '7012',
        'approved_financial_area': '7012',
        'building_ratio_coverage': 'نسبة البناء 400% والتغطية 60%',
        'setbacks': 'ارتداد أمامي 6م',
        'allowed_uses': 'سكني وفندقي وتجاري',
        'regulatory_constraints': 'مواقف بمعدل موقف لكل وحدة',
        'land_and_building_summary': 'ملخص الأرض والمبنى المعتمد.',
        'timeline_table_data': json.dumps([{
            'name': 'التصميم', 'year': '2026', 'quarter': 'Q1', 'duration': '6',
            'endYear': '2026', 'endQuarter': 'Q3', 'notes': 'يشمل الاعتمادات',
        }], ensure_ascii=False),
        'financial_study_model': json.dumps({
            'inputs': {'projectCost': 480000000, 'roi': '18%'},
            'dynamicRows': {'components': [{'name': 'شقق سكنية', 'useType': 'سكني',
                                            'units': 120, 'builtArea': 24000}]},
        }, ensure_ascii=False),
        'market_study_data': json.dumps({
            'one_block_summary': 'تعريف السوق: قطاع الضيافة الفاخرة في جدة.',
            'competitors': [{
                'id': 'c1', 'name': 'فور سيزونز جدة', 'price_value': '9700000',
                'field_sources': {'name': ['https://example.test/a']},
                'source_urls': ['https://example.test/a'],
            }],
            'swot': {'strengths': 'موقع بحري مباشر'},
            'decision': 'فرصة جاذبة',
        }, ensure_ascii=False),
        'executive_content': json.dumps({
            'brief': 'نبذة المشروع المعتمدة.',
            'opportunity': 'الفرصة الاستثمارية المعتمدة.',
            'features': 'الميزات المعتمدة.',
            'risks': 'خطر التأخير ومعالجته بجدول ملزم.',
            'summary': 'الملخص التنفيذي المعتمد للمشروع.',
        }, ensure_ascii=False),
        'team_selection': json.dumps({
            'excluded': [], 'roles': {},
            'local': [{'localId': 'l1', 'name': 'مكتب تصميم محلي', 'role': 'التصميم المعماري'}],
        }, ensure_ascii=False),
        # Noise the model must never receive.
        'tenantSlidesData': [{'title': 'شريحة سابقة',
                              'html': '<div class="slide">ديك قديم</div>'}],
        'pageDrafts': {'slides': {'generated': True}},
        'visual_concept': {'slots': {'cover': {'prompt': 'Cinematic wide-angle shot'}}},
        'tenantCreativeImages': {'cover': '/uploads/creative/a.jpg'},
        'land_documents_files_file_meta': [{'id': 'f1', 'originalName': 'krooki.pdf'}],
        'survey_coordinates': json.dumps([{'eastings': '511085.849', 'northings': '2392264.840'}]),
    }

    def test_slide_prompt_carries_every_section_instead_of_a_truncated_dump(self):
        """A real project payload is ~230,000 characters and was cut at 4,000, so the market study,
        the executive content, the team and most of the location section never reached the model."""
        # The library is company-wide, so it is removed again: other cases assert it is empty.
        with self.app.app_context():
            entity_id = db.create_team_entity(self.tenant_a, 'شركة الاستشارات الهندسية',
                                              role='المستشار الهندسي',
                                              brief='خبرة في الأبراج الفاخرة')
            try:
                facts = self.application_module.slide_engine.build_project_facts(
                    self.FULL_PROJECT, tenant_id=self.tenant_a)
            finally:
                db.delete_team_entity(self.tenant_a, entity_id)

        for heading in ('معلومات أساسية', 'الموقع والخرائط', 'الأرض والكروكي',
                        'فريق العمل', 'دراسة السوق', 'المحتوى التنفيذي'):
            self.assertIn(heading, facts)
        for fact in ('THE VIEW', 'جدة', 'طريق الكورنيش', 'مطار الملك عبدالعزيز',
                     'ارتداد أمامي 6م', 'سكني وفندقي وتجاري', 'فور سيزونز جدة',
                     'الملخص التنفيذي المعتمد للمشروع.', 'خطر التأخير ومعالجته بجدول ملزم.',
                     'شركة الاستشارات الهندسية', 'مكتب تصميم محلي', 'فرصة جاذبة'):
            self.assertIn(fact, facts)
        # Multi-select groups are stored under internal keys; the model must not see them.
        self.assertIn('أصحاب الثروات', facts)
        self.assertNotIn('audience::', facts)
        # Noise: the previous deck, image prompts, per-field provenance, file metadata.
        for noise in ('class="slide"', 'ديك قديم', 'Cinematic wide-angle shot', 'field_sources',
                      'source_urls', 'krooki.pdf', '511085.849', 'tenantSlidesData'):
            self.assertNotIn(noise, facts)
        # A complete project fits without being cut at all.
        self.assertNotIn('[تم اختصار البيانات]', facts)

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        engine_source = (ROOT / 'slide_engine.py').read_text(encoding='utf-8')
        self.assertNotIn('project_json[:4000]', app_source)
        self.assertNotIn('project_json[:6000]', engine_source)
        self.assertIn('slide_engine.build_project_facts(project_data, g.tenant_id)', app_source)
        self.assertIn('project_json = build_project_facts(project_data, tenant_id)', engine_source)

    def test_generated_slide_request_sends_the_sections_and_not_the_previous_deck(self):
        """End to end: what the endpoint hands to the model for one slide."""
        captured = {}

        def fake_generate(system_prompt, slide, slide_num, total, branding, call_fn, **kwargs):
            captured['system_prompt'] = system_prompt
            return '<div class="slide" style="width:1280px;height:720px">ok</div>'

        client = self.app.test_client()
        with patch.object(self.application_module.slide_engine, 'generate_single_slide',
                          side_effect=fake_generate), \
                patch.object(self.application_module.maps_service, 'generate_all_map_images',
                             return_value={}):
            response = client.post('/api/generate-slide-single', headers=self._headers(self.token_a), json={
                'projectData': self.FULL_PROJECT,
                'slidePlan': {'slides': [{'title': 'دراسة السوق', 'type': 'content'}]},
                'slideIndex': 0,
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        prompt = captured['system_prompt']
        for fact in ('THE VIEW', 'دراسة السوق', 'المحتوى التنفيذي', 'فريق العمل',
                     'فور سيزونز جدة', 'التصميم', 'شقق سكنية'):
            self.assertIn(fact, prompt)
        self.assertNotIn('ديك قديم', prompt)

        # The client must not upload the previous deck or the image state with every slide either.
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function slimGenerationProjectData(data)', index_source)
        self.assertIn('projectData: slimGenerationProjectData(tenantProjectData)', index_source)
        for dropped in ('tenantSlidesData', 'pageDrafts', 'tenantCreativeImages', 'visual_concept'):
            self.assertIn(f"'{dropped}'", index_source.split('const GENERATION_PAYLOAD_DROPPED')[1][:900])

    def test_project_logo_is_used_next_to_the_company_logo(self):
        """An uploaded project logo was never used: the model was not told it exists, the fallback
        header carried the company logo alone, and resolve_logo_in_html() rewrote the project
        logo's src to the company logo whenever its path contained the word "logo"."""
        engine = self.application_module.slide_engine
        project_logo = '/api/project-files/proj-logo-1'
        project = {'project_name': 'THE VIEW', 'project_logo': project_logo}

        # 1. The prompt states whether a project logo exists, so "if it exists" is answerable.
        with_logo = self.application_module._get_images_info({}, project)
        self.assertIn('شعار المشروع: متوفر', with_logo)
        self.assertIn('##PROJECT_LOGO##', with_logo)
        without_logo = self.application_module._get_images_info({}, {'project_name': 'x'})
        self.assertIn('لا يوجد', without_logo)

        # 2. A content slide with no header of its own gets both logos.
        branding = {'primary_color': '#0b1f33', 'accent_color': '#0ea5e9', 'company_name': 'منافع'}
        finished = engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px"><p>محتوى</p></div>',
            'content', project, branding, slide_num=3, slide_title='الموقع', total_slides=8,
        )
        self.assertIn(project_logo, finished)
        self.assertIn('##LOGO##'.replace('##LOGO##', '/assets/logo.png'), finished)

        # 3. A project logo whose own path contains "logo" keeps its src.
        risky = '/uploads/project-files/tenant-a/logo.png'
        kept = engine.resolve_logo_in_html(
            f'<img src="{risky}" alt="project" />', None, project_logo=risky)
        self.assertIn(risky, kept)

        # 4. Cover and closing ask for both logos, and never get a header or footer.
        rules = self.application_module.build_design_rules(branding)
        self.assertIn('##PROJECT_LOGO##', rules)
        self.assertIn('الغلاف والختام', rules)
        cover = engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px"><h1>THE VIEW</h1></div>',
            'cover', project, branding, slide_num=1, slide_title='الغلاف', total_slides=8,
        )
        self.assertNotIn('height:56px', cover)
        self.assertNotIn('height:36px', cover)

    def test_palette_contrast_and_logo_backgrounds_are_resolved_before_rendering(self):
        from PIL import Image, ImageDraw
        from design_templates import build_design_rules, contrast_ratio

        tenant_dir = Path(self.application_module.UPLOADS_DIR) / self.tenant_a
        tenant_dir.mkdir(parents=True, exist_ok=True)
        company_path = tenant_dir / 'logo.png'
        company_logo = Image.new('RGBA', (160, 80), (0, 0, 0, 0))
        ImageDraw.Draw(company_logo).rectangle((12, 20, 148, 60), fill=(250, 250, 250, 255))
        company_logo.save(company_path)

        project_path = tenant_dir / 'project-documents' / 'dark-project.png'
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_logo = Image.new('RGBA', (160, 80), (0, 0, 0, 0))
        ImageDraw.Draw(project_logo).rectangle((12, 20, 148, 60), fill=(10, 30, 45, 255))
        project_logo.save(project_path)

        with self.app.app_context():
            file_id = db.create_project_file(
                self.tenant_a, 'project_logo', 'dark-project.png', str(project_path),
                'image/png', project_path.stat().st_size, 'dark-project-sha')
            db.update_branding(
                self.tenant_a, logo_path=f'/tenant-assets/{self.tenant_a}/logo',
                primary_color='#005f78', secondary_color='#003d50', accent_color='#d8c49a',
                background_color='#005f78', text_color='#111111')
            branding = db.get_branding(self.tenant_a)
            project = {
                'project_name': 'THE VIEW',
                'project_logo': f'/api/project-files/{file_id}',
                'project_logo_file_id': file_id,
            }
            self.application_module._prepare_generation_logo_context(project, branding, self.tenant_a)

        self.assertEqual(branding['_logo_tone'], 'light')
        self.assertEqual(project['_project_logo_tone'], 'dark')
        info = self.application_module._get_images_info({}, project)
        self.assertIn('شعار الشركة فاتح', info)
        self.assertIn('خلفية داكنة', info)
        self.assertIn('شعار المشروع داكن', info)
        self.assertIn('خلفية بيضاء', info)

        rules = build_design_rules(branding)
        self.assertIn('4.5:1', rules)
        self.assertIn('شعار الشركة فاتح', rules)
        index_html = self.application_module.slide_engine.build_index_slide({
            'index_entries': [{'title': 'نبذة عن المشروع', 'page': 3}],
        }, 2, 5, branding, project)
        self.assertIn('background:#005f78', index_html)
        self.assertIn('color:#ffffff', index_html)
        self.assertGreaterEqual(contrast_ratio('#ffffff', '#005f78'), 4.5)
        self.assertNotIn('color:#111111', index_html)

        finished = self.application_module.slide_engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px;background:#ffffff;color:#111111"><p>محتوى</p></div>',
            'content', project, branding, tenant_id=self.tenant_a,
            slide_num=3, slide_title='نبذة عن المشروع', total_slides=5)
        logo_tags = re.findall(r'<img\b[^>]*>', finished, re.IGNORECASE)
        company_tag = next(tag for tag in logo_tags if f'/tenant-assets/{self.tenant_a}/logo' in tag)
        project_tag = next(tag for tag in logo_tags if f'/api/project-files/{file_id}' in tag)
        self.assertIn('background:#005f78', company_tag)
        self.assertIn('background:#ffffff', project_tag)

    def test_single_slide_accepts_any_valid_slide_class_attribute(self):
        engine = self.application_module.slide_engine

        def generated(*_args, **_kwargs):
            return {'choices': [{'message': {'content': (
                "<div class='slide generated' style='width:1280px;height:720px;"
                "background:#ffffff;color:#111827'><p>محتوى</p></div>"
            )}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'نبذة', 'type': 'content'}, 3, 8,
            {'primary_color': '#0b1f33'}, generated, project_data={})
        self.assertEqual(len(self.application_module.extract_slide_elements(html)), 1)
        self.assertIn('class="slide"', html)
        self.assertIn('height:56px', html)

    def test_single_slide_retries_severely_unreadable_text(self):
        engine = self.application_module.slide_engine
        responses = iter([
            "<div class='slide' style='width:1280px;height:720px;background:#005f78;color:#111111'><p>نص غير مقروء</p></div>",
            "<div class='slide' style='width:1280px;height:720px;background:#005f78;color:#ffffff'><p>نص مقروء</p></div>",
        ])
        prompts = []

        def generated(_system, user_message, **_kwargs):
            prompts.append(user_message)
            return {'choices': [{'message': {'content': next(responses)}}]}

        html = engine.generate_single_slide(
            'system', {'title': 'نبذة', 'type': 'content'}, 3, 8,
            {'primary_color': '#005f78'}, generated, project_data={})
        self.assertIn('color:#ffffff', html)
        self.assertEqual(len(prompts), 2)
        self.assertIn('فشل التباين', prompts[1])
        self.assertTrue(engine.slide_contrast_issues(
            "<div class='slide' style='background:#005f78'><p>لون المتصفح الافتراضي</p></div>"))

    def test_section_dividers_are_built_from_one_fixed_layout(self):
        """Every divider is the same layout over the approved main image with only the text
        changing, so it is rendered in code: identical on every divider and no model call."""
        engine = self.application_module.slide_engine
        branding = {'primary_color': '#0b1f33', 'accent_color': '#22b6e8', 'company_name': 'منافع'}
        project = {'project_name': 'THE VIEW', 'project_logo': '/api/project-files/logo-1'}
        slide = {
            'title': 'فريق التطوير والتصميم', 'type': 'section_divider',
            'title_en': 'Development & Design Team',
            'subtitle': 'شراكة تجمع خبرة التطوير العقاري السعودي مع التصميم والهندسة العالمية.',
        }

        # No model call: call_glm_fn must not be touched for a divider.
        def fail_if_called(*args, **kwargs):
            raise AssertionError('a section divider must not call the model')

        html = engine.generate_single_slide(
            'system', slide, 6, 60, branding, fail_if_called, project_data=project)

        self.assertEqual(html.count('class="slide"'), 1)
        self.assertIn('فريق التطوير والتصميم', html)
        self.assertNotIn('DEVELOPMENT & DESIGN TEAM', html)
        self.assertNotIn('شراكة تجمع خبرة التطوير العقاري', html)
        self.assertIn('url(##IMAGE_COVER##)', html)               # the approved main image
        self.assertIn('06 — 60', html)                            # slide number, as in the reference
        self.assertIn('THE VIEW', html)
        self.assertIn('##PROJECT_LOGO##', html)                   # both logos
        self.assertIn('##LOGO##', html)
        self.assertIn('#22b6e8', html)                            # tenant accent, not a fixed colour

        # Finalizing must not add the content header/footer to it.
        finished = engine.finalize_slide_html(
            html, 'section_divider', project, branding,
            creative_images={'cover': '/uploads/creative/cover.jpg'},
            slide_num=6, slide_title=slide['title'], total_slides=60,
        )
        self.assertNotIn('height:56px', finished)
        self.assertNotIn('height:36px', finished)
        self.assertIn('/uploads/creative/cover.jpg', finished)
        self.assertIn('/api/project-files/logo-1', finished)

        # A divider with no English line or description still renders.
        bare = engine.generate_single_slide(
            'system', {'title': 'مكونات المشروع', 'type': 'section_divider'},
            15, 60, branding, fail_if_called, project_data=project)
        self.assertIn('مكونات المشروع', bare)
        self.assertIn('15 — 60', bare)

        # The planner knows the type, and the validator accepts it.
        prompt = engine.build_slide_plan_prompt({'project_name': 'THE VIEW'}, branding)
        self.assertIn('section_divider', prompt)
        self.assertIn('بلا وصف أو ترجمة', prompt)
        plan = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'مكونات المشروع', 'type': 'section_divider'},
            {'title': 'المكونات', 'type': 'content', 'bullets': ['1', '2', '3']},
            {'title': 'الختام', 'type': 'closing'},
        ]}
        _valid, issues = engine.validate_slide_plan(plan, {'min_slides': 1, 'max_slides': 60})
        self.assertFalse([issue for issue in issues if 'section_divider' in issue], issues)

    def test_final_deck_plan_has_canonical_sections_page_index_and_exact_media(self):
        engine = self.application_module.slide_engine
        financial = {
            'inputs': {'projectCost': 1200000},
            'dynamicRows': {'components': [{'name': 'فندق', 'units': 20}]},
            'tables': {
                'componentsTable': [{'المكون': 'فندق', 'الوحدات': '20'}],
                'revenueTable': [
                    {'السنة': '2027', 'الإيراد': '1,200,000'},
                    {'السنة': '2028', 'الإيراد': '1,500,000'},
                ],
            },
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': 'مكونات المشروع'},
                {'type': 'table', 'headers': ['المكون', 'الوحدات'], 'rows': [['فندق', '20']]},
                {'type': 'heading', 'level': 2, 'text': 'النتائج المالية'},
                {'type': 'fields', 'rows': [['ROI', '18%'], ['إجمالي التكلفة', '1,200,000']]},
                {'type': 'heading', 'level': 2, 'text': 'الإيرادات'},
                {'type': 'table', 'headers': ['السنة', 'الإيراد'],
                 'rows': [['2027', '1,200,000'], ['2028', '1,500,000']]},
            ]},
        }
        project = {
            'project_name': 'المشروع', 'project_idea': 'نبذة المشروع',
            'contact_email': 'info@example.test', 'contact_phone': '0110000000',
            'land_and_building_summary': 'ملخص الأرض النهائي',
            'site_analysis': 'ملخص الموقع النهائي',
            'timeline_table_data': json.dumps([
                {'name': 'التصميم', 'year': '2027', 'quarter': 'Q1', 'duration': '3', 'notes': ''},
                {'name': 'التنفيذ', 'year': '2027', 'quarter': 'Q2', 'duration': '9',
                 'notes': 'بعد الاعتماد'},
            ], ensure_ascii=False),
            'financial_study_model': financial,
            'market_study_data': json.dumps({
                'one_block_summary': 'ملخص السوق النهائي',
                'swot': {'strengths': 'موقع قوي', 'weaknesses': 'تكلفة مرتفعة'},
            }, ensure_ascii=False),
            'executive_content': json.dumps({
                'risks': 'خطر التأخير ومعالجته بجدول ملزم.',
                'summary': 'الملخص التنفيذي المعتمد.',
            }, ensure_ascii=False),
            'team_selection': json.dumps({'excluded': [], 'roles': {}, 'local': [{
                'localId': 'local-1', 'name': 'المكتب الهندسي', 'role': 'التصميم',
                'brief': 'خبرة متخصصة', 'logoFileId': 'team-logo-1',
            }]}, ensure_ascii=False),
        }
        images = {
            'moodboard': ['/uploads/creative/right.jpg', '/uploads/creative/left.jpg'],
            'moodboard_meta': [
                {'label': 'الواجهة اليمنى', 'caption': 'التكوين الحجري'},
                {'label': 'الواجهة الشمالية', 'caption': 'المدخل الرئيسي'},
            ],
            'land_photos': [{
                'url': '/uploads/creative/land.jpg', 'name': 'واجهة الأرض',
                'description': 'الحد الشمالي للأرض',
            }],
            'plans': ['/uploads/creative/plan.jpg'],
            'plan_meta': [{'title': 'مخطط الدور الأرضي', 'description': 'توزيع الدور الأرضي'}],
            'interior_components': [{
                'name': 'الفندق', 'images': [{
                    'url': '/uploads/creative/lobby.jpg', 'label': 'الاستقبال',
                    'caption': 'منطقة الاستقبال الرئيسية',
                }],
            }],
            'team_members': [{'name': 'المكتب الهندسي', 'role': 'التصميم',
                              'logo': '/uploads/creative/team.jpg'}],
        }
        raw = {'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'الفهرس', 'type': 'index'},
            {'title': 'تحليل السوق', 'type': 'content', 'section_key': 'market',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'المشروع والفكرة', 'type': 'content', 'section_key': 'overview',
             'bullets': ['أ', 'ب', 'ج']},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}
        plan = engine.normalize_presentation_plan(raw, project, images)
        dividers = [slide for slide in plan['slides'] if slide.get('type') == 'section_divider']
        self.assertEqual([slide['section_key'] for slide in dividers],
                         list(engine.PRESENTATION_SECTION_ORDER[:-1]))
        self.assertTrue(all('subtitle' not in slide and 'title_en' not in slide for slide in dividers))

        entries = plan['slides'][1]['index_entries']
        self.assertEqual([entry['section_key'] for entry in entries],
                         list(engine.PRESENTATION_SECTION_ORDER))
        for entry in entries:
            self.assertEqual(plan['slides'][entry['page'] - 1].get('section_key'), entry['section_key'])
        index_html = engine.build_index_slide(plan['slides'][1], 2, len(plan['slides']), {}, project)
        self.assertIn('محتويات العرض', index_html)
        self.assertIn('نبذة عن المشروع', index_html)
        self.assertIn('الخاتمة', index_html)
        self.assertNotIn('محور', index_html)

        divider_html = engine.build_section_divider_slide({
            'title': 'تحليل الأرض', 'subtitle': 'وصف يجب ألا يظهر', 'title_en': 'LAND',
        }, 3, len(plan['slides']), {}, project)
        self.assertNotIn('وصف يجب ألا يظهر', divider_html)
        self.assertNotIn('LAND', divider_html)

        overview = next(slide for slide in plan['slides'] if slide.get('content_source') == 'project_overview')
        self.assertEqual(overview['image_tokens'], ['##MOODBOARD_IMAGE_1##', '##MOODBOARD_IMAGE_2##'])
        land = [slide for slide in plan['slides'] if slide.get('section_key') == 'land'
                and slide.get('type') == 'content']
        self.assertEqual(land[0]['image_tokens'], ['##LAND_PHOTO_1##'])
        self.assertEqual(land[0]['bullets'], ['الحد الشمالي للأرض'])
        self.assertEqual(land[-1]['content_source'], 'land_and_building_summary')
        self.assertTrue(any(slide.get('image_tokens') == ['##PLAN_IMAGE_1##'] for slide in plan['slides']))
        self.assertTrue(any(slide.get('image_tokens') == ['##INTERIOR_COMP_1_IMG_1##']
                            for slide in plan['slides']))
        self.assertTrue(any(slide.get('image_tokens') == ['##TEAM_LOGO_1##'] for slide in plan['slides']))
        self.assertEqual(sum(slide.get('section_key') == 'components' and slide.get('type') == 'content'
                             for slide in plan['slides']), 1)
        component_slide = next(slide for slide in plan['slides']
                               if slide.get('section_key') == 'components' and slide.get('type') == 'content')
        self.assertTrue(component_slide['content_source'].startswith('financial_report:'))
        financial_slides = [slide for slide in plan['slides'] if slide.get('section_key') == 'financial'
                            and slide.get('type') == 'content']
        self.assertTrue(financial_slides)
        self.assertTrue(all(str(slide.get('content_source')).startswith('financial_report:')
                            for slide in financial_slides))
        self.assertTrue(any(slide.get('design_style') == 'chart' for slide in financial_slides))
        source_note = engine._slide_source_data_note(financial_slides[-1], project)
        self.assertIn('1,500,000', source_note)
        financial_note = engine._financial_data_note(project)
        self.assertIn('نفس محتوى تقرير PDF', financial_note)
        self.assertIn('ROI', financial_note)
        self.assertIn('1,500,000', financial_note)
        self.assertIn('فواصل الآلاف', financial_note)
        facts = engine.build_project_facts(project)
        self.assertIn('بيانات التواصل المعتمدة للخاتمة', facts)
        self.assertIn('info@example.test', facts)
        closing_message = engine.build_slide_user_msg(
            plan['slides'][-1], len(plan['slides']), len(plan['slides']), {}, project)
        self.assertIn('فرصة واعدة بشروط', closing_message)
        cleaned_closing = engine.postprocess_slide(
            '<div class="slide"><p>فرصة واعدة بشروط</p><p>شكراً لكم</p></div>',
            'closing', slide_num=len(plan['slides']), total_slides=len(plan['slides']),
            slide_title='الخاتمة',
        )
        self.assertNotIn('فرصة واعدة بشروط', cleaned_closing)
        self.assertIn('شكراً لكم', cleaned_closing)

        gated = engine.normalize_presentation_plan({'slides': [
            {'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'},
            {'title': 'المخططات', 'type': 'content', 'section_key': 'plans'},
            {'title': 'الدراسة المالية', 'type': 'content', 'section_key': 'financial'},
            {'title': 'الخاتمة', 'type': 'closing'},
        ]}, {'project_name': 'مشروع بلا وسائط'}, {})
        self.assertNotIn('plans', [slide.get('section_key') for slide in gated['slides']])
        self.assertNotIn('financial', [slide.get('section_key') for slide in gated['slides']])

    def test_media_manifest_carries_land_descriptions_and_keeps_team_logos(self):
        project = {
            'team_selection': json.dumps({'local': [{
                'name': 'المصمم', 'role': 'التصميم', 'logoFileId': 'team-file',
            }], 'excluded': [], 'roles': {}}, ensure_ascii=False),
            'land_photos_file_meta': [{
                'id': 'land-file', 'originalName': 'land.jpg', 'description': 'الشارع الشمالي',
            }],
        }
        with patch.object(self.application_module, '_generation_project_image_url',
                          side_effect=lambda _tenant, file_id: '/uploads/creative/' + file_id + '.jpg'):
            augmented = self.application_module._augment_generation_images({}, project, self.tenant_a)
        self.assertEqual(augmented['team_members'][0]['logo'], '/uploads/creative/team-file.jpg')
        self.assertEqual(augmented['land_photos'][0]['url'], '/uploads/creative/land-file.jpg')
        self.assertEqual(augmented['land_photos'][0]['description'], 'الشارع الشمالي')

        images = {
            'cover': '/uploads/creative/cover.jpg',
            'moodboard': ['/uploads/creative/right.jpg'],
            'moodboard_meta': [{'label': 'الواجهة اليمنى', 'caption': 'تفاصيل الواجهة'}],
            'land_photos': [{'url': '/uploads/creative/land.jpg',
                             'name': 'صورة الأرض', 'description': 'الشارع الشمالي'}],
            'plans': ['/uploads/creative/plan.jpg'],
            'plan_meta': [{'title': 'المخطط العام', 'description': 'توزيع المشروع'}],
            'team_members': [{'name': 'المصمم', 'role': 'التصميم',
                              'logo': '/uploads/creative/team.jpg'}],
        }
        info = self.application_module._get_images_info(images, {'project_name': 'المشروع'})
        for expected in ('##MOODBOARD_IMAGE_1##', 'تفاصيل الواجهة', '##LAND_PHOTO_1##',
                         'الشارع الشمالي', '##PLAN_IMAGE_1##', 'توزيع المشروع',
                         '##TEAM_LOGO_1##'):
            self.assertIn(expected, info)

        html = self.application_module.slide_engine.finalize_slide_html(
            '<div class="slide" style="width:1280px;height:720px">'
            '<img class="team-logo" src="##TEAM_LOGO_1##">'
            '<img src="##LAND_PHOTO_1##"></div>',
            'content', {'project_name': 'المشروع'},
            {'primary_color': '#123456', 'accent_color': '#abcdef'},
            creative_images=images, slide_num=3, slide_title='الوسائط', total_slides=5,
        )
        self.assertIn('/uploads/creative/team.jpg', html)
        self.assertIn('/uploads/creative/land.jpg', html)
        self.assertNotIn('##TEAM_LOGO_1##', html)
        self.assertNotIn('##LAND_PHOTO_1##', html)

    def test_slides_workspace_can_return_to_the_project_form_without_losing_it(self):
        """There was no way back from the slides page to بيانات المشروع: the only navigation was
        the dashboard, and from there "عرض جديد" calls startTenantProject(), which resets the
        state and shows a blank form as if the project were gone."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        toolbar = index_source.split('<section id="tenantSlidesPage"')[1].split('</div>\n\n      <!-- Live')[0]
        self.assertIn("navigateTenantWorkflow('tenantProjectPage')", toolbar)
        self.assertIn('بيانات المشروع', toolbar)

        # Going back only shows the page again: it must not rebuild or reload the form, because the
        # rendered form already holds the hydrated values.
        nav = index_source.split('async function navigateTenantWorkflow(pageId) {')[1]
        nav = nav.split('\n    function ')[0]
        self.assertIn("if (pageId === 'tenantProjectPage') {\n        showTenantPage(pageId);", nav)
        self.assertNotIn('startTenantProject', nav)
        self.assertNotIn('loadTenantProjectForm', nav)

    def test_an_emptied_draft_can_be_refilled_from_a_presentation_snapshot(self):
        """Every generated presentation stored the whole project data of its moment, so a draft
        that was emptied by a bad save is recoverable from it."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)
        full = {
            'draftId': 'draft-recover', 'project_name': 'برج المشرق', 'city': 'الرياض',
            'croquis_land_area': '7012', 'allowed_uses': 'سكني وتجاري',
        }
        self.assertEqual(client.post('/api/project-draft', headers=headers,
                                     json={'draftData': full}).status_code, 200)
        created = client.post('/api/presentations', headers=headers, json={
            'title': 'عرض برج المشرق', 'projectData': full,
            'slidesData': [{'html': '<div class="slide">1</div>'}], 'slideCount': 1,
        })
        self.assertEqual(created.status_code, 201, created.get_json())
        presentation_id = created.get_json()['presentationId']

        # Simulate the historic wipe directly in the database, past the new guard.
        with self.app.app_context():
            conn = db.get_db()
            conn.execute("UPDATE project_drafts SET draft_data = '{}', title = 'مسودة مشروع بدون عنوان' "
                         'WHERE id = ?', ('draft-recover',))
            conn.commit()

        report = client.get('/api/project-drafts/recovery', headers=headers).get_json()
        entry = next(item for item in report['drafts'] if item['draftId'] == 'draft-recover')
        self.assertTrue(entry['isEmpty'])
        self.assertEqual(entry['fieldCount'], 0)
        self.assertEqual(entry['snapshot']['presentationId'], presentation_id)
        self.assertTrue(entry['snapshot']['recoverable'])
        self.assertGreaterEqual(entry['snapshot']['fieldCount'], 4)

        restored = client.post('/api/project-draft/draft-recover/restore', headers=headers,
                               json={'presentationId': presentation_id})
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertGreaterEqual(restored.get_json()['restoredCount'], 4)

        draft = client.get('/api/project-draft/draft-recover', headers=headers).get_json()['draft']
        self.assertEqual(draft['draft_data']['project_name'], 'برج المشرق')
        self.assertEqual(draft['draft_data']['croquis_land_area'], '7012')
        self.assertEqual(draft['title'], 'برج المشرق')

        # Restoring never overwrites what the draft still holds.
        client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': 'draft-recover', 'project_name': 'اسم محدّث', 'city': 'الرياض',
            'croquis_land_area': '7012', 'allowed_uses': 'سكني وتجاري',
        }})
        again = client.post('/api/project-draft/draft-recover/restore', headers=headers,
                            json={'presentationId': presentation_id})
        self.assertEqual(again.get_json()['restoredCount'], 0)
        kept = client.get('/api/project-draft/draft-recover', headers=headers).get_json()['draft']
        self.assertEqual(kept['draft_data']['project_name'], 'اسم محدّث')

        # A snapshot from another tenant is never reachable.
        cross = client.post('/api/project-draft/draft-recover/restore',
                            headers=self._headers(self.token_b),
                            json={'presentationId': presentation_id})
        self.assertEqual(cross.status_code, 404)

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('/api/project-drafts/recovery', index_source)
        self.assertIn('async function restoreProjectDraft(draftId, presentationId)', index_source)
        self.assertIn('حقل ممتلئ', index_source)

    def test_slide_rules_forbid_invented_content_and_drawn_2d_plans(self):
        """Every number has to come from the project, and plans are uploaded images only."""
        rules = self.application_module.build_design_rules(
            {'primary_color': '#0b1f33', 'company_name': 'منافع'})
        self.assertIn('ممنوع اختراع أي معلومة', rules)
        self.assertIn('ممنوع منعًا باتًا رسم أو تركيب أي مخطط معماري', rules)
        self.assertIn('##PLAN_IMAGE_1##', rules)
        self.assertIn('الرسوم البيانية عند الحاجة', rules)
        self.assertIn('بحد أقصى 10% من لون التمييز', rules)
        self.assertIn('الوزن لخدمة التسلسل البصري', rules)
        self.assertIn('عنصرين أو ثلاثة مستقلين', rules)
        self.assertIn('صورة واحدة كبيرة أو صورتان', rules)
        self.assertIn('ممنوع إضافة ترجمة أو وصف', rules)
        # The batch path had its own copy of the 4,000-character cut.
        engine_source = (ROOT / 'slide_engine.py').read_text(encoding='utf-8')
        self.assertNotIn("project_json[:4000]", engine_source)
        self.assertEqual(engine_source.count('build_project_facts(project_data'), 3)

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

    def test_a_save_carrying_no_data_cannot_empty_a_stored_draft(self):
        """A draft is only ever emptied by DELETE.

        Saving used to store whatever arrived and answer success, and an absent ``draftData``
        became "{}". A payload with no ``draftId`` is applied to the row this actor updated most
        recently, so one mangled request emptied the project that was being worked on.
        """
        client = self.app.test_client()
        stored = {
            'draftId': 'draft-wipe-guard',
            'project_name': 'برج المشرق',
            'location_address': 'https://maps.google.com/?q=24,46',
            'approved_financial_area': '7012',
            'market_study_data': 'x' * 2000,
        }
        self.assertEqual(
            client.post('/api/project-draft', headers=self._headers(self.token_a),
                        json={'draftData': stored}).status_code, 200)

        def remaining():
            response = client.get('/api/project-draft/draft-wipe-guard',
                                  headers=self._headers(self.token_a))
            self.assertEqual(response.status_code, 200, response.get_json())
            return response.get_json()['draft']['draft_data']

        no_payload = client.post('/api/project-draft', headers=self._headers(self.token_a),
                                 json={'status': 'draft'})
        self.assertEqual(no_payload.status_code, 400, no_payload.get_json())
        empty_payload = client.post('/api/project-draft', headers=self._headers(self.token_a),
                                    json={'draftData': {}})
        self.assertEqual(empty_payload.status_code, 400, empty_payload.get_json())

        # A form that was rebuilt but never filled reports every field as an empty string.
        blanked = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {
                'draftId': 'draft-wipe-guard', 'project_name': '', 'location_address': '',
                'approved_financial_area': '', 'market_study_data': '',
                'pageDrafts': {'project': {'status': 'draft'}}, 'map_styles': {}, 'map_type': '',
            }
        })
        self.assertEqual(blanked.status_code, 409, blanked.get_json())
        self.assertEqual(blanked.get_json()['error_code'], 'DRAFT_EMPTY_OVERWRITE')

        self.assertEqual(remaining()['project_name'], 'برج المشرق')
        self.assertEqual(remaining()['approved_financial_area'], '7012')

        # A save that names no draft lands on the newest one, so it must be refused too.
        unnamed = client.post('/api/project-draft', headers=self._headers(self.token_a),
                              json={'draftData': {'project_name': '', 'city': ''}})
        self.assertEqual(unnamed.status_code, 409, unnamed.get_json())
        self.assertEqual(remaining()['project_name'], 'برج المشرق')

    def test_project_form_blanks_are_not_collected_before_it_is_filled(self):
        """The form is built empty and filled afterwards, so its blank inputs must not be
        reported as the project's values while hydration has not completed."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function tenantProjectFormIsFilled()', index_source)
        self.assertIn("form.dataset.projectFormFilled = ''", index_source)
        self.assertIn('markTenantProjectFormFilled();', index_source)
        self.assertIn('if (!tenantProjectFormIsFilled()) {', index_source)
        self.assertIn(
            'if (isBlankProjectValue(result[key]) && !isBlankProjectValue(tenantProjectData[key])) {',
            index_source)
        # The marker is written after hydration finishes, so a throw part-way leaves it unset.
        hydrate_body = index_source.split('function hydrateTenantProjectForm(data) {')[1]
        hydrate_body = hydrate_body.split('\n    function ')[0]
        self.assertLess(hydrate_body.index("form.querySelectorAll('[data-key]')"),
                        hydrate_body.index('markTenantProjectFormFilled();'))

    def test_an_unreassembled_chunked_reference_never_reaches_a_route(self):
        """The reassembly hook used to return silently when it could not read the reference, and
        the route then saw a request with no data at all."""
        client = self.app.test_client()
        refused = client.post('/api/project-draft', headers=self._headers(self.token_a),
                              json={'__chunked_body': {'id': 'a' * 12, 'total': 4, 'gzip': False}})
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertEqual(refused.get_json()['error'], 'Missing uploaded body chunks')

        # The marker appearing inside ordinary content is not a reference.
        saved = client.post('/api/project-draft', headers=self._headers(self.token_a), json={
            'draftData': {'draftId': 'draft-chunk-marker',
                          'project_idea': 'يشرح النص كيف يعمل __chunked_body في الحفظ'}
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())

        # Every large save goes through this path, so the round trip has to keep working.
        payload = {'draftData': {'draftId': 'draft-chunked-save',
                                 'project_name': 'برج مجمّع من أجزاء',
                                 'project_idea': 'وصف طويل ' * 400}}
        wire = gzip.compress(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        parts = [wire[start:start + 12 * 1024] for start in range(0, len(wire), 12 * 1024)]
        upload_id = 'chunked-save-1'
        for index, part in enumerate(parts):
            uploaded = client.post('/api/body-chunk', headers=self._headers(self.token_a), json={
                'id': upload_id, 'idx': index, 'total': len(parts),
                'data': base64.b64encode(part).decode('ascii'),
            })
            self.assertEqual(uploaded.status_code, 200, uploaded.get_json())
        assembled = client.post('/api/project-draft', headers=self._headers(self.token_a),
                                json={'__chunked_body': {'id': upload_id, 'total': len(parts),
                                                         'gzip': True}})
        self.assertEqual(assembled.status_code, 200, assembled.get_json())
        stored = client.get('/api/project-draft/draft-chunked-save',
                            headers=self._headers(self.token_a)).get_json()['draft']
        self.assertEqual(stored['draft_data']['project_name'], 'برج مجمّع من أجزاء')

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

    def test_uploaded_slot_images_are_published_to_a_durable_url(self):
        """A client upload was previewed from a blob: URL and that URL was saved into the file.

        A blob: URL only resolves inside the tab that created it, so every image the client
        had uploaded rendered broken once the file was reopened, and the export shipped a
        reference the server could never read.
        """
        client = self.app.test_client()
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        created = client.post('/api/project-files', headers=self._headers(self.token_a), data={
            'fileType': 'visual_reference',
            'file': (io.BytesIO(png_bytes), 'cover.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(created.status_code, 201, created.get_json())
        file_id = created.get_json()['file']['id']

        published = client.post(f'/api/project-files/{file_id}/publish-image',
                                headers=self._headers(self.token_a))
        self.assertEqual(published.status_code, 200, published.get_json())
        url = published.get_json()['url']
        self.assertTrue(url.startswith('/uploads/creative/'), url)
        # The published copy is served without an Authorization header, which is the whole
        # point: it can sit in a saved draft and in an exported deck.
        self.assertEqual(client.get(url).status_code, 200)

        # Another tenant cannot publish a file it does not own.
        self.assertEqual(
            client.post(f'/api/project-files/{file_id}/publish-image',
                        headers=self._headers(self.token_b)).status_code, 404)

        # A blob: cover reaching the server falls back to the stored file instead of being used.
        with self.application_module.app.test_request_context():
            self.application_module.g.tenant_id = self.tenant_a
            fallback = self.application_module._visual_concept_cover_image(
                {'coverImage': 'blob:https://example.test/abc', 'coverFileId': file_id})
        self.assertTrue(fallback.startswith('data:image/'), fallback[:32])

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("'/api/project-files/' + encodeURIComponent(fileId) + '/publish-image'", index_source)
        self.assertIn('liveSlot().imageUrl = await publishProjectFileImageUrl(fileId);', index_source)
        self.assertIn('imageUrl: await publishProjectFileImageUrl(file.id)', index_source)
        self.assertIn('viewSlot.imageUrl = await publishProjectFileImageUrl(file.id);', index_source)
        # A stored blob: URL is dropped on load and republished from the file id.
        self.assertIn('const approved = durableImageUrl(slot.approvedImageUrl);', index_source)
        self.assertIn('const imageUrl = durableImageUrl(slot.imageUrl);', index_source)
        self.assertIn('imageUrl: durableImageUrl(source.imageUrl || source.image_url)', index_source)
        self.assertIn('async function repairVisualConceptStoredImages()', index_source)
        self.assertIn('repairVisualConceptStoredImages();', index_source)
        self.assertNotIn('liveSlot().imageUrl = await getProjectFileObjectUrl(fileId)', index_source)

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

        # No internal identifier may be used as a visible header, allowing only accepted business acronyms (ROI, NOI).
        self.assertEqual(set(re.findall(r'<th>([A-Za-z]\w*)</th>', html)) - {'ROI', 'NOI'}, set())

        # Curated results with business domain acronyms, and the schedules still render as real tables in section 8.
        self.assertIn('12. النتائج المالية', html)
        self.assertIn('إجمالي تكلفة المشروع', html)
        self.assertIn('500,000,000', html)
        self.assertIn('42.00%', html)
        self.assertIn('18.00%', html)
        self.assertIn('Project IRR', html)
        self.assertIn('نسبة السحب %', html)
        self.assertIn('صافي تدفق المشروع', html)
        # Echoed inputs are no longer repeated in the results summary.
        self.assertNotIn('developerRate', html)

    def test_financial_pdf_prints_the_screen_verbatim_in_tables(self):
        """The export is the study as the screen shows it, only laid out as tables.

        The server used to rebuild the report from its own label map, so «هل وحدات المشروع بيعية
        أم تأجيرية؟» printed as «طبيعة الإيرادات» and its value printed as the raw option id
        «mixed», and a light branding colour painted the label column unreadable.
        """
        model = {
            'inputs': {'unitRevenueMode': 'mixed', 'developmentYears': 4, 'landArea': 70000,
                       'financeEnabled': 'no', 'fundEnabled': 'no', 'fundFeesEnabled': 'no',
                       'externalEnabled': 'no', 'exitEnabled': 'no', 'builtUpAreaAbove': 100000},
            'tables': {}, 'projection': {},
            'report': {'parts': [
                {'type': 'heading', 'level': 2, 'text': '1. طبيعة وحدات المشروع'},
                {'type': 'fields', 'rows': [['هل وحدات المشروع بيعية أم تأجيرية؟', 'مختلطة: بيعية وتأجيرية'],
                                            ['حالة الأرض', 'مستأجرة ولا تدخل ضمن تكلفة المشروع']]},
                {'type': 'heading', 'level': 2, 'text': '9. التمويل'},
                {'type': 'heading', 'level': 3, 'text': 'خطة سحب التمويل'},
                {'type': 'table', 'headers': ['سنة السحب', 'نسبة السحب من التسهيل %'], 'rows': [['1', '25%']]},
                {'type': 'fields', 'rows': [['صافي تدفق المشروع', '-13,125,000'], ['فترة الاسترداد', '4 سنة']]},
            ]},
        }
        branding = {'primary_color': '#EAF2F8', 'secondary_color': '#F0E9DF', 'accent_color': '#FFFFFF'}
        with self.app.app_context():
            html = self.application_module.build_financial_report_html('مشروع مالي', model, branding, self.tenant_a)

        # Screen wording, screen values — nothing renamed, nothing reformatted, nothing dropped.
        self.assertIn('هل وحدات المشروع بيعية أم تأجيرية؟', html)
        self.assertIn('مختلطة: بيعية وتأجيرية', html)
        self.assertIn('مستأجرة ولا تدخل ضمن تكلفة المشروع', html)
        self.assertIn('<th>نسبة السحب من التسهيل %</th>', html)
        self.assertIn('25%', html)
        self.assertNotIn('mixed', html)
        self.assertNotIn('leased', html)
        self.assertNotIn('طبيعة الإيرادات', html)

        # A sub-heading keeps its block title, and every value sits in a table cell.
        self.assertLess(html.index('9. التمويل'), html.index('خطة سحب التمويل'))
        self.assertNotIn('<p>مختلطة', html)

        # A figure is an LTR run: in an RTL cell the bidi algorithm moved the leading minus to the
        # right of the digits, so «-13,125,000» printed as «13,125,000-».
        self.assertIn('<td dir="ltr">-13,125,000</td>', html)
        self.assertIn('<td dir="ltr">25%</td>', html)
        # Text that happens to start with a figure stays in the cell's own direction.
        self.assertIn('<td>4 سنة</td>', html)
        self.assertIn('<td>مستأجرة ولا تدخل ضمن تكلفة المشروع</td>', html)
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('unicode-bidi: plaintext;', index_source)
        self.assertIn('td{unicode-bidi:plaintext}', index_source)

        # The branding palette no longer paints the report, so a light tenant colour cannot
        # print pale text on a pale tint.
        for colour in branding.values():
            self.assertNotIn(colour, html)

        # The fallback engine renders the same parts rather than the old label map.
        with tempfile.TemporaryDirectory() as folder:
            output = os.path.join(folder, 'screen.pdf')
            with self.app.app_context():
                self.application_module.generate_financial_pdf_from_model('مشروع مالي', model, output)
            self.assertTrue(self.application_module._financial_pdf_has_text(output, minimum=20))

        # The client is what supplies those parts, and only for the export.
        self.assertIn('function collectFinancialStudyReport()', index_source)
        self.assertIn('model.report = collectFinancialStudyReport();', index_source)
        self.assertNotIn('report: collectFinancialStudyReport()', index_source)
        # Selected option text, not the option id, and hidden inputs stay out.
        self.assertIn("if (control.tagName === 'SELECT') return financialReportText(control.selectedOptions?.[0])",
                      index_source)
        self.assertIn("FINANCIAL_REPORT_SKIP_COLUMNS = new Set(['ترتيب / حذف', 'ترتيب', 'حذف'])", index_source)

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

    def test_grouped_classification_dropdowns_fill_their_field(self):
        """`.project-choice-grid` is a flex row. The grouped fields wrap each dropdown in its own
        div, and a flex item shrinks to fit, so the dropdown's `width:100%` resolved against that
        shrunken box: «الأنواع الفرعية للمشروع» and «الفئة المستهدفة» rendered as a narrow box and
        their menus broke every option onto two lines."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('.project-choice-grid>div {\n      flex: 1 1 100%;', index_source)
        # Those are the wrappers that need it, and the dropdown still spans whatever holds it.
        self.assertIn("'<div style=\"margin-top:10px\"><label>' + (showSubtypeLabels", index_source)
        self.assertIn("return '<div style=\"margin-top:10px\"><label>' + label + subtypeText +",
                      index_source)
        self.assertIn('.project-multi-select {\n      position: relative;\n      width: 100%;',
                      index_source)

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

        # The project form keeps the requested order, with the timeline feeding the financial study and contact at the end.
        self.assertIn("const sectionOrder = ['basic', 'location', 'land_croquis'];", index_source)
        build_start = index_source.index('addTimelineTable(form);')
        build_end = index_source.index('const projectSections = Array.from', build_start)
        build_source = index_source[build_start:build_end]
        self.assertLess(build_source.index('addTimelineTable(form);'), build_source.index('addFinancialCalculations(form);'))
        self.assertLess(build_source.index('addFinancialCalculations(form);'), build_source.index('addTeamSection(form);'))
        self.assertLess(build_source.index('addTeamSection(form);'), build_source.index('addExecutiveContentSection(form)'))
        self.assertLess(build_source.index('addExecutiveContentSection(form)'), build_source.index("renderFormSection('contact')"))
        self.assertNotIn('addConceptualPlansSection(form)', build_source)

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
                     '/app/projects/visual-concept',
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
        self.assertIn('id="developmentYears" type="number" min="1" value="" readonly', index_source)
        self.assertNotIn('id="developmentYears" type="number" min="1" value="4" oninput', index_source)
        self.assertIn("مأخوذة من «عدد السنوات» في قسم الجدول الزمني", index_source)

        # The year count mirrors on its own: gating it on the stage list left «مدة تطوير المشروع»
        # showing 4 while the timeline said 5, in a box the user cannot edit.
        self.assertNotIn('if (namedStages.length && devYearsInput', index_source)
        self.assertIn("const nextDevYears = Number.isFinite(timelineYears) && timelineYears > 0 ? String(timelineYears) : '';",
                      index_source)
        self.assertIn('if (devYearsChanged) recalculate();', index_source)

    def test_mirrored_financial_inputs_never_show_a_figure_their_source_lacks(self):
        """These four boxes are read-only and say they come from another section, so a value the
        source does not have is invented data the user cannot correct. The study used to open on
        70,000 م², 35% تغطية, دور واحد and 4 سنوات that nobody entered, and clearing a source left
        the previous number behind because the mirror only wrote when the source was non-zero."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        for element in ('id="landArea" type="number" value=""',
                        'id="coverageRate" type="number" value=""',
                        'id="floorCount" type="number" min="1" value=""',
                        'id="developmentYears" type="number" min="1" value=""'):
            self.assertIn(element + ' readonly class="readonly-highlight"', index_source)
        self.assertNotIn('id="landArea" type="number" value="70000"', index_source)
        self.assertNotIn('id="coverageRate" type="number" value="35"', index_source)

        # An empty source clears the mirror instead of leaving the last value.
        self.assertIn("const next = raw !== '' && number > 0 ? String(number) : '';", index_source)
        self.assertIn("mirrorApproved(landAreaInput, 'approved_financial_area');", index_source)
        self.assertIn("mirrorApproved(floorInput, 'approved_floor_count');", index_source)
        self.assertIn("mirrorApproved(coverageInput, 'approved_coverage_ratio');", index_source)
        self.assertNotIn('if (landAreaInput && area > 0) landAreaInput.value', index_source)

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
        # The stage list still guards the schedule rebuild — but not the year count, which is the
        # timeline's own field and mirrors on its own.
        self.assertIn('if (!namedStages.length) {\n        if (devYearsChanged) recalculate();\n        return;\n      }',
                      index_source)

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

        # The three approved-build fields come from the land/croquis section and are locked. They
        # start empty: a read-only box must never show a figure its source does not have.
        self.assertIn('id="landArea" type="number" value="" readonly', index_source)
        self.assertIn('id="coverageRate" type="number" value="" readonly', index_source)
        self.assertIn('id="floorCount" type="number" min="1" value="" readonly', index_source)
        self.assertIn('مأخوذة من «المساحة المعتمدة للدراسة المالية» في قسم الأرض والكروكي', index_source)
        self.assertIn('مأخوذة من «التغطية المعتمدة» في قسم الأرض والكروكي', index_source)
        self.assertIn('مأخوذة من «الأدوار المعتمدة» في قسم الأرض والكروكي', index_source)

        # Changing those land fields re-mirrors them into the financial study.
        self.assertIn(
            "f.fieldKey === 'approved_financial_area' || f.fieldKey === 'approved_floor_count' || f.fieldKey === 'approved_coverage_ratio'",
            index_source)
        self.assertIn("mirrorApproved(coverageInput, 'approved_coverage_ratio');", index_source)
        self.assertIn('const raw = readLand(key);', index_source)
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
        # The owner asked for no how-to copy on screen; the notes column still feeds the slide.
        self.assertNotIn('الملاحظات تظهر مع المرحلة في شريحة الجدول الزمني', index_source)
        self.assertNotIn('الملاحظات داخلية في الملف فقط', index_source)
        self.assertIn('<th>إلى</th><th>الملاحظات</th>', index_source)

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
        self.assertIn('إذا كانت الملاحظة فارغة فلا تعرض', note)
        empty_note_line = self.application_module.slide_engine.format_timeline_phase_line({
            'name': 'التصميم', 'year': '2027', 'quarter': 'Q1',
            'endYear': '2027', 'endQuarter': 'Q2', 'duration': '3', 'notes': '',
        })
        self.assertNotIn(' — ', empty_note_line)

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
        self.assertIn('1,000', html)
        self.assertIn('90', html)
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

    def test_financial_schedules_state_their_own_totals_and_stop_at_their_own_period(self):
        """Five faults in the financial study, each of which showed a wrong figure as a right one.

        A percentage column that summed to less than 100% still looked complete; a schedule table
        printed one row per project year regardless of the period entered for it; a sale exit could
        be configured on a project that has no sellable units and stayed silently zero; and no
        screen stated how any derived figure had been arrived at.
        """
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        # 1. Both percentage columns of the stage table state their sum and what is unassigned.
        self.assertIn('id="scheduleCostPctTotal"', index_source)
        self.assertIn('id="scheduleDevPctTotal"', index_source)
        self.assertIn('id="scheduleCostTotalValue"', index_source)
        self.assertIn('id="scheduleDevTotalValue"', index_source)
        self.assertIn('function renderSchedulePercentTotals(rows, costValueTotal, devValueTotal)',
                      index_source)
        self.assertIn('غير موزَّع من نسبة تكلفة التطوير:', index_source)
        self.assertIn('غير موزَّع من نسبة دفعة المطور:', index_source)
        self.assertIn('renderSchedulePercentTotals(scheduleRows, scheduleCostValueTotal, scheduleDevValueTotal);',
                      index_source)
        # A tfoot row must reach the exported PDF, or the totals exist only on screen.
        self.assertIn("table.querySelectorAll('tbody tr,tfoot tr')", index_source)

        # 2. The sale exit belongs to a project that has sellable units, and its state is stated.
        self.assertIn('const saleModeOn = projectModeFlags().sales;', index_source)
        self.assertIn("const saleExitMethod = saleModeOn ? (val('saleExitMethod') || 'none') : 'none';",
                      index_source)
        self.assertIn("setWrapVisible('saleExitMethodWrap', exitOn && saleModeOn);", index_source)
        self.assertIn('id="saleExitAreaReference"', index_source)
        self.assertIn('function renderSaleExitStatus({', index_source)
        self.assertIn('لا يوجد تخارج بيعي: وحدات المشروع تأجيرية بالكامل.', index_source)
        self.assertIn('التخارج البيعي مطبق بقيمة صفر:', index_source)

        # 3. الإيضاحات states each derived figure as its own arithmetic, and reaches the report.
        self.assertIn('<h3>15. الإيضاحات</h3>', index_source)
        self.assertIn('id="clarificationsTable"', index_source)
        self.assertIn('function renderClarifications(facts)', index_source)
        self.assertIn("<th>طريقة الاحتساب بالأرقام المُدخلة</th>", index_source)
        self.assertIn("reportTableSnapshot('clarificationsTable', false)", index_source)
        self.assertIn("setConditionalVisibility('clarificationsBlock', rows.length > 0);", index_source)
        self.assertIn('updateDynamicFieldDetails(exitOn);\n    }\n\n    // Every readonly figure', index_source)
        self.assertLess(index_source.index('function renderClarifications(facts)'),
                        index_source.index('function updateDynamicFieldDetails(exitOn)'))

        # 4 and 5. A schedule stops where its own period stops, and a later year survives the trim
        # only when it still carries a figure — a computed amount must never be hidden by it.
        self.assertIn('function financeMovementRows(projected, financeOn, repaymentStartYear, repaymentYears)',
                      index_source)
        self.assertIn('function fundFeeScheduleRows(projected, fundFeesOn, feeEndYear)', index_source)
        self.assertIn('function lastYearCarryingValue(projected, fields)', index_source)
        self.assertIn('financeMovementRows(projected, financeOn, financeRepaymentStartYear, financeRepaymentYears)',
                      index_source)
        self.assertIn('fundFeeScheduleRows(projected, fundFeesOn, fundFeeEndYear)', index_source)
        # The tables must no longer render straight from the full projection.
        self.assertNotIn(
            "if (debtTb) debtTb.innerHTML = projected.map(r => `<tr><td>${r.year}</td>", index_source)
        self.assertNotIn(
            "if (fundTb) fundTb.innerHTML = projected.map(r => `<tr><td>${r.year}</td>", index_source)

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
                    'map_label_version': self.application_module.maps_service.MAP_LABEL_RENDER_VERSION,
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
        self.assertIn("ACCESS_ROADS_RENDER_VERSION = 'v12-context-zoom-road-names'", source)
        self.assertIn("def bundled_arabic_overlay_font_path():", source)
        self.assertIn("def _strip_arabic_diacritics(text):", source)
        self.assertIn("def _arabic_reshaper_without_ligatures():", source)
        self.assertIn("configuration['support_ligatures'] = False", source)
        self.assertIn('from bidi.algorithm import get_display', source)
        self.assertIn("'language': 'ar'", source)
        overlay_font = ROOT / 'fonts' / 'arabic-overlay.bin'
        self.assertGreater(overlay_font.stat().st_size, 10000)
        self.assertEqual(overlay_font.read_bytes()[:4], b'\x00\x01\x00\x00')
        self.assertIn("'feature:road|element:labels|visibility:off'", source)
        self.assertIn('pending_labels.append((route_segment, label_text))', source)
        self.assertIn('labels_overlay = Image.new', source)
        self.assertIn('distance=52', source)
        self.assertIn('candidates = preferred_candidates or visible_candidates', source)
        self.assertIn('ly1 = offset_point[1] - 30', source)
        self.assertLess(
            source.index('draw.line(segment, fill=gold_color, width=9)'),
            source.index('_draw_road_label(labels_draw')
        )
        self.assertIn('function withCacheBust(url)', index_source)
        self.assertIn('payload.refresh_maps = true', index_source)
        self.assertIn('selectMapPreviewView(mapType)', index_source)
        self.assertIn('selectMapPreviewView(tenantSelectedMapType)', index_source)
        self.assertIn('Regenerating a map is an explicit user action.', index_source)
        self.assertIn('await saveProjectAsDraftNow(true);', index_source)

    def test_map_section_has_no_regeneration_controls(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('data-map-action="regenerate"', index_source)
        self.assertNotIn(
            "closeTenantDropdown(); if(tenantPresentationId){ regeneratePresentationMaps(); } else { ensureProjectAssets({force:true, needImages:false})",
            index_source,
        )
        self.assertNotIn(
            "collectMapStylePanel(); if(tenantPresentationId){ regeneratePresentationMaps(); } else { ensureProjectAssets({force:true, needImages:false})",
            index_source,
        )

    def test_client_entered_land_fields_are_highlighted(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("TENANT_CLIENT_ENTERED_LAND_FIELDS = new Set(['approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio'])", index_source)
        self.assertIn('tenant-client-required-field', index_source)
        self.assertIn('tenant-client-complete-field', index_source)
        self.assertIn('tenant-client-required-badge', index_source)
        self.assertIn("badge.textContent = 'إدخال العميل';", index_source)
        self.assertIn('function updateClientEnteredLandFieldState(input)', index_source)
        self.assertIn("field.classList.toggle('tenant-client-complete-field', entered);", index_source)
        self.assertIn('input.addEventListener(\'input\', () => updateClientEnteredLandFieldState(input));', index_source)
        self.assertIn('refreshClientEnteredLandFieldStates();', index_source)
        self.assertIn("sectionKey === 'land_croquis' && TENANT_CLIENT_ENTERED_LAND_FIELDS.has(f.fieldKey)", index_source)

    def test_client_entered_land_fields_validation_and_placeholders(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        db_source = (ROOT / 'db.py').read_text(encoding='utf-8')

        # DB prebuilt field placeholders
        self.assertIn("'placeholder': 'يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.'", db_source)
        self.assertIn("'placeholder': 'يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.'", db_source)
        self.assertIn("'placeholder': 'يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.'", db_source)

        # Validation function in index.html
        self.assertIn('function validateLandCroquisClientFields()', index_source)
        self.assertIn("key === 'land_croquis'", index_source)
        self.assertIn("validateLandCroquisClientFields()", index_source)
        self.assertIn("يرجى إدخال عدد الأدوار المعتمدة للمشروع وفقًا للاشتراطات التنظيمية.", index_source)
        self.assertIn("يرجى إدخال نسبة التغطية المعتمدة للأرض وفقًا للاشتراطات التنظيمية.", index_source)
        self.assertIn("يرجى إدخال إجمالي المساحة البنائية المعتمدة التي ستُبنى عليها حسابات الدراسة المالية.", index_source)

        # toggleApproveCroquisData also validates before approving
        self.assertIn('function toggleApproveCroquisData()', index_source)
        self.assertIn('const errors = validateLandCroquisClientFields();', index_source)

    def test_financial_schedule_percentages_and_sales_exit_hiding(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        proto_source = (ROOT / 'THE-VIEW-Financial-Model-FINAL-v2.html').read_text(encoding='utf-8')

        # Schedule table percentage clamping
        self.assertIn('function enforceSchedulePctInput(input, fieldName)', index_source)
        self.assertIn('function enforceSchedulePctInput(input, fieldName)', proto_source)
        self.assertIn('const costPctTotal = Math.min(100, scheduleRows.reduce((s, r) => s + r.costPct, 0))', index_source)
        self.assertIn('const costPctTotal=Math.min(100,scheduleRows.reduce((s,r)=>s+r.costPct,0));', proto_source)
        self.assertIn('100 - existingCostSum', index_source)
        self.assertIn('100 - existingDevSum', index_source)

        # Section 13 sales exit dynamic hiding
        self.assertIn('id="saleExitYearWrap"', index_source)
        self.assertIn('id="saleExitCostRateWrap"', index_source)
        self.assertIn('id="resSaleExitGrossCard"', index_source)
        self.assertIn('id="resSaleExitCard"', index_source)
        self.assertIn("setWrapVisible('saleExitYearWrap', saleExitActive);", index_source)
        self.assertIn("setWrapVisible('saleExitCostRateWrap', saleExitActive);", index_source)
        self.assertIn("resSaleExitGrossCard.classList.toggle('dynamic-off', !saleExitActive);", index_source)
        self.assertIn("resSaleExitCard.classList.toggle('dynamic-off', !saleExitActive);", index_source)

    def test_financial_pdf_fallback_writes_real_arabic_text(self):
        import tempfile
        from pathlib import Path

        model = {
            'inputs': {
                'unitRevenueMode': 'nonRevenue', 'developmentYears': 2, 'operationYears': 5,
                'landArea': 70000, 'builtUpAreaAbove': 100000, 'coverageRate': 35,
                'financeEnabled': 'no', 'fundEnabled': 'no', 'fundFeesEnabled': 'no',
                'externalEnabled': 'no', 'exitEnabled': 'no',
            },
            'tables': {
                'cashflowTable': [{'year': 1, 'final': -10, 'cumulative': -10}],
                'sensitivityTable': [{'scenario': 'أساسي', 'roi': '12%'}],
            },
            'projection': {'projectCost': 1000},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'model.pdf'
            with self.app.app_context():
                self.application_module.generate_financial_pdf_from_model('مشروع مالي', model, output)
            self.assertTrue(self.application_module._financial_pdf_has_text(output))
            import fitz
            document = fitz.open(output)
            try:
                text = '\n'.join(page.get_text() for page in document)
            finally:
                document.close()
            # PyMuPDF applies no shaping, so the report must carry presentation forms.
            self.assertIn('\ufee3', text)
            self.assertIn('70,000', text)
            empty = Path(temp_dir) / 'empty.pdf'
            blank = fitz.open()
            blank.new_page()
            blank.save(empty)
            blank.close()
            self.assertFalse(self.application_module._financial_pdf_has_text(empty))

        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        # A textless PDF must never be accepted, and the font-embedding writer must be
        # tried before the MuPDF HTML engine, which needs system fonts we do not have.
        self.assertNotIn('os.path.getsize(output_path) > 0', source)
        self.assertLess(
            source.index('generate_financial_pdf_from_model(project_name, model, output_path)\n            if _financial_pdf_has_text'),
            source.index("fitz.open('html', candidate.encode('utf-8'))")
        )
        self.assertIn('def _financial_pdf_shape(text):', source)
        self.assertIn('def split_runs(value):', source)

    def test_parallel_section_approvals_are_not_lost(self):
        import threading

        client = self.app.test_client()
        headers = self._headers(self.token_a)
        sections = [
            'basic', 'location', 'land_croquis', 'section-timeline',
            'section-financial-calc', 'section-team', 'section-market-study',
            'section-executive-content',
        ]
        client.post('/api/project-draft', headers=headers, json={
            'draftData': {'project_name': 'ملف اعتماد'}, 'sectionStatuses': {}, 'status': 'draft'
        })

        # One merged call must store every section.
        response = client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionStatuses': {key: 'approved' for key in sections}
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        stored = client.get('/api/project-draft', headers=headers).get_json()['draft']['section_statuses']
        self.assertEqual(sorted(stored), sorted(sections))
        self.assertTrue(all(value == 'approved' for value in stored.values()), stored)

        # And a race between single-section calls must not drop any of them either.
        client.post('/api/project-draft/section-status', headers=headers, json={
            'sectionStatuses': {key: 'draft' for key in sections}
        })
        errors = []

        def approve(section_key):
            try:
                with self.app.test_client() as parallel:
                    parallel.post('/api/project-draft/section-status', headers=headers, json={
                        'sectionKey': section_key, 'sectionStatus': 'approved'
                    })
            except Exception as error:  # pragma: no cover - surfaced through the assertion below
                errors.append(error)

        threads = [threading.Thread(target=approve, args=(key,)) for key in sections]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        stored = client.get('/api/project-draft', headers=headers).get_json()['draft']['section_statuses']
        self.assertTrue(all(stored.get(key) == 'approved' for key in sections), stored)

        approval = client.post('/api/project-draft/request-approval', headers=headers, json={})
        self.assertEqual(approval.status_code, 200, approval.get_json())
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        # A section nobody opened had no stored status, and the approval gate walks the stored
        # map, so the file could be submitted with that section never approved.
        self.assertIn('applySectionStatuses(initialStatuses);', index_source)
        self.assertIn("sectionStatuses: statuses", index_source)
        self.assertIn('def update_draft_section_statuses(', (ROOT / 'db.py').read_text(encoding='utf-8'))

    def test_components_block_shows_the_regulated_uses(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        # The activities are chosen in the components table, so the regulated list belongs there.
        self.assertIn('id="componentsAllowedUsesNote"', index_source)
        self.assertIn('function renderComponentsAllowedUsesNote(allowedUses, status)', index_source)
        self.assertIn("'الاستخدامات المسموحة تنظيميًا: ' + uses", index_source)
        self.assertIn('renderComponentsAllowedUsesNote(allowedUses, status);', index_source)

    def test_access_road_names_do_not_change_between_regenerations(self):
        import maps_service

        site = (21.6324618, 39.1056571)
        # The probes decided which roads were found; seeding them meant a new set of street
        # names on every regeneration of the same site.
        self.assertEqual(maps_service.access_probe_points(*site), maps_service.access_probe_points(*site))
        self.assertEqual(len(maps_service.access_probe_points(*site)), 4)
        source = (ROOT / 'maps_service.py').read_text(encoding='utf-8')
        access_at = source.index('def _draw_access_roads(')
        body = source[access_at:source.index('def _get_cached_map_images(')]
        self.assertIn('probe_points = access_probe_points(route_origin_lat, route_origin_lng)', body)
        self.assertNotIn('seed_step', body)
        self.assertNotIn('rotate_by', body)
        self.assertNotIn("regen_seed = int(", body)

        # The names the user entered in the location section win over Google's wording.
        known = [
            'شارع الشاطئ وإسطنبول', 'الامير فيصل بن فهد والخليفة المهدي',
            'الامير فيصل بن فهد', 'شارع الشاطئ', 'طريق الكورنيش الفرعي',
        ]
        self.assertEqual(maps_service.match_known_road_name('شارع الشاطئ', known), 'شارع الشاطئ')
        self.assertEqual(maps_service.match_known_road_name('طريق الأمير فيصل بن فهد', known), 'الامير فيصل بن فهد')
        self.assertEqual(maps_service.match_known_road_name('الكورنيش', known), 'طريق الكورنيش الفرعي')
        self.assertEqual(maps_service.match_known_road_name('طريق مجهول تماما', known), '')
        self.assertEqual(maps_service.match_known_road_name('', known), '')
        # A compound row and its own street are one road; drawing both repeated the name.
        self.assertTrue(maps_service.is_same_road_name(
            'الامير فيصل بن فهد والخليفة المهدي', 'طريق الأمير فيصل بن فهد'
        ))
        self.assertTrue(maps_service.is_same_road_name('شارع الشاطئ', 'الشاطئ'))
        self.assertFalse(maps_service.is_same_road_name('شارع الشاطئ', 'طريق الكورنيش'))
        self.assertFalse(maps_service.is_same_road_name('', 'شارع الشاطئ'))
        self.assertIn('is_same_road_name(result[1], accepted)', source)
        self.assertEqual(
            maps_service._road_name_key('طريق الأمير فيصل بن فهد'),
            maps_service._road_name_key('الامير فيصل بن فهد'),
        )

    def test_croquis_coordinates_become_the_site_boundary(self):
        import maps_service

        # Jeddah, UTM zone 37N. The plot below is the real croquis table of a live project,
        # whose approved area is 7,012 sqm.
        site_lat, site_lng = 21.6324618, 39.1056571
        rows = [
            {'eastings': '511085.849', 'northings': '2392264.840', 'parcel_id': 'P-1'},
            {'eastings': '511189.416', 'northings': '2392298.825', 'parcel_id': 'P-1'},
            {'eastings': '511198.442', 'northings': '2392262.273', 'parcel_id': 'P-1'},
            {'eastings': '511208.664', 'northings': '2392220.822', 'parcel_id': 'P-1'},
            {'eastings': '511196.244', 'northings': '2392219.452', 'parcel_id': 'P-1'},
            {'eastings': '511111.135', 'northings': '2392211.397', 'parcel_id': 'P-1'},
            {'eastings': '511100.913', 'northings': '2392224.147', 'parcel_id': 'P-1'},
        ]
        self.assertEqual(maps_service.utm_zone_for_longitude(site_lng), 37)
        polygon = maps_service.survey_polygon_from_project(
            {'survey_coordinates': json.dumps(rows)}, site_lat, site_lng
        )
        self.assertIsNotNone(polygon)
        self.assertEqual(len(polygon), 7)
        mean_latitude = math.radians(site_lat)
        metres = [
            ((point[1] - site_lng) * 111320 * math.cos(mean_latitude), (point[0] - site_lat) * 110540)
            for point in polygon
        ]
        area = abs(sum(
            metres[index][0] * metres[(index + 1) % len(metres)][1]
            - metres[(index + 1) % len(metres)][0] * metres[index][1]
            for index in range(len(metres))
        )) / 2
        self.assertAlmostEqual(area, 7012.12, delta=400)

        # A local grid that lands in another region must be refused, not drawn.
        self.assertIsNone(maps_service.survey_polygon_from_project(
            {'survey_coordinates': json.dumps([
                {'eastings': '1000.0', 'northings': '2000.0', 'parcel_id': 'X'},
                {'eastings': '1100.0', 'northings': '2000.0', 'parcel_id': 'X'},
                {'eastings': '1100.0', 'northings': '2100.0', 'parcel_id': 'X'},
            ])}, site_lat, site_lng
        ))

        source = (ROOT / 'maps_service.py').read_text(encoding='utf-8')
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('def survey_polygon_from_project(', source)
        self.assertIn('Using croquis survey polygon with', source)
        self.assertIn('def _google_bounds_polygon(', source)
        # The client must send the croquis table and must not switch the highlight off just
        # because no boundary has been found yet.
        self.assertIn("'survey_coordinates', 'city'", index_source)
        self.assertIn("return source !== 'cleared';", index_source)
        self.assertIn("tenantProjectData.location_polygon_source = 'cleared';", index_source)

    def test_map_preview_uses_the_rendered_centre_and_fits_its_content(self):
        import maps_service

        source = (ROOT / 'maps_service.py').read_text(encoding='utf-8')
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        # Clicks were converted against the site pin while the image is centred on the plot,
        # which put every manually drawn boundary off by that distance.
        self.assertIn("result['centers'] = {", source)
        self.assertIn("'center_lat': map_center_lat", source)
        self.assertIn('const center = (tenantCreativeImages.map_centers || {})[mapType] || {};', index_source)
        self.assertIn('tenantCreativeImages.map_centers = data.centers || {};', index_source)

        # Nine destination rows became nine rings up to 31 km wide; keep three and frame them.
        rings = maps_service.catchment_rings([
            {'km': 1.6, 'minutes': 5}, {'km': 4.9, 'minutes': 11}, {'km': 13.6, 'minutes': 22},
            {'km': 28.6, 'minutes': 35}, {'km': 30.9, 'minutes': 38},
        ])
        self.assertEqual(len(rings), 3)
        self.assertEqual([ring['km'] for ring in rings], [1.6, 13.6, 30.9])
        self.assertEqual(rings[0]['label'], '5 دقائق')
        named_rings = maps_service.catchment_rings([{'km': 2.4, 'minutes': 7, 'label': 'حي النرجس'}])
        self.assertEqual(named_rings[0]['name'], 'حي النرجس')
        self.assertIn('حي النرجس', named_rings[0]['label'])
        markers = maps_service._build_markers(24.0, 46.0, [
            {'name': 'مجمع الراشد', 'lat': 24.01, 'lng': 46.01}
        ])
        self.assertEqual(markers[1]['label'], '1')
        self.assertEqual(markers[1]['name'], 'مجمع الراشد')
        self.assertIn('def _draw_marker_name_label(', source)
        self.assertIn("'map_label_version': MAP_LABEL_RENDER_VERSION", source)
        self.assertIn("'nearby_landmarks_data'", index_source)
        self.assertEqual(maps_service.catchment_rings([]), [])
        near = maps_service.zoom_for_radius_km(21.63, 1.6)
        far = maps_service.zoom_for_radius_km(21.63, 30.9)
        self.assertGreater(near, far)
        for radius, zoom in ((1.6, near), (30.9, far)):
            metres_per_pixel = 156543.03392 * math.cos(math.radians(21.63)) / (2 ** zoom) / 2
            self.assertLessEqual(radius * 1000 / metres_per_pixel, 720 * 0.8 + 1)
        self.assertIn('def zoom_for_radius_km(', source)
        self.assertIn('def access_map_zoom(', source)
        self.assertIn("access_zoom = access_map_zoom(lat, zooms['access'])", source)
        self.assertIn('shown_landmarks = [item for item in landmarks if item.get', source)
        self.assertIn('def find_place_near(', source)
        # Appending the project address made Google return the site itself for every landmark.
        self.assertNotIn("query = f\"{lm['name']}, {location_context}\"", source)
        self.assertIn('async function unapproveMapPreview(mapType)', index_source)
        self.assertIn("(approved ? 'unapprove' : 'approve')", index_source)

    def test_map_label_font_never_reapplies_bidi(self):
        from PIL import ImageFont
        import maps_service

        font = maps_service._get_arabic_font(24)
        self.assertEqual(font.layout_engine, ImageFont.Layout.BASIC)
        shaped = maps_service._reshape_arabic_text('طريق الشاطئ الشمالي')
        self.assertEqual(shaped[0], '\ufef2')
        self.assertEqual(shaped[-1], '\ufec3')

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
        # A failed planner ships the generic structure, and that is stated rather than passing as
        # the model's own proposal — every such file otherwise came out with identical titles.
        self.assertEqual(response.get_json()['plan']['source'], 'fallback')
        self.assertEqual(response.get_json()['planSource'], 'fallback')

    def test_slide_count_has_no_upper_limit(self):
        """The plan follows the amount of content: a stored max_slides used to trim the surplus."""
        engine = self.application_module.slide_engine
        # Only a locked count binds the plan; otherwise the ceiling is open.
        self.assertEqual(engine.resolve_slide_bounds({'min_slides': 8, 'max_slides': 30})[1],
                         engine.SLIDE_COUNT_OPEN)
        self.assertEqual(engine.resolve_slide_bounds(
            {'min_slides': 8, 'max_slides': 30, 'lock_slide_count': 1, 'default_slide_count': 12}),
            (12, 12, 12))
        # Every one of the 117 content slides survives; the canonical section divider is added.
        long_plan = {'slides': (
            [{'title': 'الغلاف', 'type': 'cover'}, {'title': 'الفهرس', 'type': 'index'}]
            + [{'title': f'محور {i}', 'type': 'content', 'bullets': ['1', '2', '3']} for i in range(117)]
            + [{'title': 'الختام', 'type': 'closing'}]
        )}
        with patch.object(self.application_module, 'call_zai_chat_parallel', return_value={}), \
                patch.object(self.application_module, 'extract_chat_content', return_value='{}'), \
                patch.object(self.application_module, 'parse_slide_plan', return_value=long_plan), \
                self.application_module.app.test_request_context():
            self.application_module.g.tenant_id = self.tenant_a
            result = self.application_module._execute_slide_plan(
                {'project_name': 'THE VIEW'}, self.tenant_a, {'min_slides': 8, 'max_slides': 30})
        self.assertEqual(len(result['plan']['slides']), 121)
        self.assertEqual(sum(slide.get('type') == 'content' for slide in result['plan']['slides']), 117)
        self.assertEqual(result['plan']['source'], 'model')
        self.assertNotIn('Too many slides', ' '.join(result['validation']['issues']))

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('max_tokens=40000', app_source)
        self.assertNotIn('شريحة كحد أقصى)', app_source)

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        # Regeneration always re-plans, and the previous deck is never displayed while it runs.
        self.assertIn("clearTenantSlidesStage('جاري إعداد خطة وهيكل العرض')", index_source)
        self.assertIn('const planResponse = await requestTenantSlidePlan(tenantProjectData', index_source)
        self.assertNotIn('if (!tenantSlidePlan) {', index_source)
        self.assertNotIn('settingsMaxSlides', index_source)

    def test_the_slide_structure_is_not_client_facing(self):
        """Owner rule: the client never operates the structure — no plan panel, no editable plan
        titles, and no button that builds or rebuilds it outside «توليد العرض»."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        for gone in (
            'تحديث الهيكل المقترح',
            'إعداد الهيكل المقترح',
            'generateSlidePlanOnly',
            'regenerateTenantSlidePlan',
            'renderTenantSlidePlan',
            'updatePlanSlideTitle',
            'tenantSlidePlanList',
            'slidePlanInfo',
            'tenant-slide-plan-card',
        ):
            self.assertNotIn(gone, index_source, gone)
        # The plan itself still exists — it is produced inside the generation flow.
        self.assertIn('const planResponse = await requestTenantSlidePlan(tenantProjectData', index_source)
        self.assertIn('slidePlan: tenantSlidePlan', index_source)

    def test_change_lines_name_the_difference_not_just_that_something_changed(self):
        import change_tracking as tracking
        old = [
            {'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1><img src="/uploads/a.png"></div>'},
            {'title': 'الموقع', 'html': '<div class="slide"><p>الرياض. حي الملقا.</p></div>'},
            {'title': 'المالية', 'html': '<div class="slide"><p>تكلفة 480 مليون</p></div>'},
        ]
        new = [
            {'title': 'الغلاف الرئيسي', 'html': '<div class="slide"><h1>THE VIEW</h1><img src="/uploads/b.png"></div>'},
            {'title': 'الموقع', 'html': '<div class="slide" style="color:red"><p>الرياض. حي الملقا.</p></div>'},
            {'title': 'المالية', 'html': '<div class="slide"><p>تكلفة 500 مليون</p></div>'},
            {'title': 'شكراً', 'html': '<div class="slide"><h2>شكراً</h2></div>'},
        ]
        lines = tracking.describe_slide_changes(old, new)
        joined = '\n'.join(lines)
        self.assertIn('عدد الشرائح: من 3 إلى 4', joined)
        self.assertIn('العنوان: من «الغلاف» إلى «الغلاف الرئيسي»', joined)
        self.assertIn('استُبدلت صورة أو خريطة', joined)
        self.assertIn('تغيّر التنسيق والألوان بدون تغيير النص', joined)
        self.assertIn('تكلفة 480 مليون', joined)
        self.assertIn('تكلفة 500 مليون', joined)
        self.assertIn('أُضيفت الشريحة 4', joined)
        self.assertNotIn('تعديل المحتوى', joined)

        draft_lines = '\n'.join(tracking.describe_draft_changes(
            {'project_name': 'the view', 'city': 'جدة', 'financial_study_model': {'inputs': {'a': 1}}},
            {'project_name': 'THE VIEW', 'district': 'الشاطئ', 'financial_study_model': {'inputs': {'a': 2}}},
        ))
        self.assertIn('من «the view» إلى «THE VIEW»', draft_lines)
        self.assertIn('أُفرغ (كان «جدة»)', draft_lines)
        self.assertIn('أُضيف «الشاطئ»', draft_lines)
        self.assertIn('الدراسة المالية: تم تحديث البيانات', draft_lines)
        # A blob is named, never dumped as a value.
        self.assertNotIn('inputs', draft_lines)

    def test_history_records_who_changed_what_for_drafts_and_ai_edits(self):
        client = self.app.test_client()
        headers = self._headers(self.token_a)

        saved = client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': 'history-draft', 'project_name': 'THE VIEW', 'city': 'جدة',
        }})
        self.assertTrue(saved.get_json()['success'], saved.get_json())
        client.post('/api/project-draft', headers=headers, json={'draftData': {
            'draftId': 'history-draft', 'project_name': 'THE VIEW 2', 'city': 'جدة', 'district': 'الشاطئ',
        }})
        client.post('/api/project-draft/section-status', headers=headers, json={
            'draftId': 'history-draft', 'sectionKey': 'basic', 'sectionStatus': 'approved',
        })

        draft_log = client.get('/api/project-draft/history-draft/edit-log', headers=headers).get_json()
        self.assertTrue(draft_log['success'], draft_log)
        actions = [entry['action'] for entry in draft_log['log']]
        self.assertIn('حفظ بيانات المشروع', actions)
        self.assertIn('اعتماد قسم', actions)
        details = '\n'.join(line for entry in draft_log['log'] for line in entry['details'])
        self.assertIn('من «THE VIEW» إلى «THE VIEW 2»', details)
        self.assertIn('أُضيف «الشاطئ»', details)
        self.assertIn('معتمد', details)
        self.assertTrue(all(entry['user_name'] for entry in draft_log['log']), draft_log['log'])

        created = client.post('/api/presentations', headers=headers, json={
            'title': 'THE VIEW', 'projectData': {'project_name': 'THE VIEW'},
            'slidesData': [{'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1></div>'}],
        })
        pres_id = created.get_json()['presentationId']

        # An AI edit used to leave no trace at all.
        edited = '<div class="slide"><h1>THE VIEW</h1><p>واجهة بحرية</p></div>'
        plan = json.dumps({'response': 'تم', 'actions': [
            {'tool': 'edit_slides', 'params': {'target': 'current', 'instruction': 'أضف سطر الواجهة'}}]},
            ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': plan}}]}), \
                patch.object(self.application_module, '_designer_edit_slide',
                             return_value=(edited, 'تم تحديث الشريحة')):
            chat = client.post('/api/designer-chat', headers=headers, json={
                'message': 'أضف سطر الواجهة البحرية', 'presentationId': pres_id, 'slideIndex': 0,
                'slidesData': [{'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1></div>'}],
            })
        self.assertTrue(chat.get_json()['success'], chat.get_json())

        log = client.get('/api/presentations/' + pres_id + '/edit-log', headers=headers).get_json()['log']
        ai_entries = [entry for entry in log if entry['source'] == 'ai']
        self.assertTrue(ai_entries, log)
        ai_details = '\n'.join(ai_entries[0]['details'])
        self.assertIn('الطلب: «أضف سطر الواجهة البحرية»', ai_details)
        self.assertIn('واجهة بحرية', ai_details)
        self.assertEqual(ai_entries[0]['action'], 'تعديل بالذكاء الاصطناعي')
        self.assertIn('إنشاء العرض', [entry['action'] for entry in log])

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('function renderChangeLogEntry(entry)', index_source)
        self.assertIn('async function showDraftEditLog(draftId)', index_source)
        self.assertIn('showDraftEditLog(', index_source)

    def test_designer_asks_instead_of_guessing_and_the_chat_is_one_line(self):
        client = self.app.test_client()
        slides = [{'html': '<div class="slide">شريحة</div>', 'title': 'الغلاف', 'type': 'cover'}]
        plan = json.dumps({
            'response': 'الطلب غير واضح',
            'actions': [{'tool': 'ask', 'params': {'question': 'أي شريحة تقصد؟'}}],
        }, ensure_ascii=False)
        with patch.object(self.application_module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': plan}}]}) as chat:
            response = client.post('/api/designer-chat', headers=self._headers(self.token_a), json={
                'message': 'حسّن الشريحة', 'slidesData': slides, 'slideIndex': 0,
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        reply = response.get_json()['data']
        self.assertEqual(reply['action'], 'ask')
        self.assertEqual(reply['response'], 'أي شريحة تقصد؟')
        # Nothing was edited: one model call for the plan, and no edit call after it.
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(reply['slidesData'], slides)

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        # One chat line: attach, write, send. The suggestions drawer is gone.
        self.assertNotIn('اقتراحات سريعة', index_source)
        self.assertNotIn('function setTenantChatExample', index_source)
        self.assertIn('id="tenantChatImageFile"', index_source)
        self.assertIn('function attachTenantChatImage(input)', index_source)
        self.assertIn("attachedImage: attachedImage ? attachedImage.dataUri : ''", index_source)
        self.assertIn("if (reply.action === 'ask') {", index_source)
        # The designer chat must not reuse the training page's file input.
        composer = index_source[index_source.index('id="tenantChatComposer"'):
                                index_source.index('id="tenantChatComposer"') + 1400]
        self.assertNotIn('trainingChatImageFile', composer)

    def test_refresh_on_the_slides_route_reopens_its_presentation(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        # The route carries no identity, and it used to be shown as-is: an empty workspace.
        self.assertIn('} else if (TENANT_NAVIGATION_CONTEXT_PAGES.has(requestedPage)) {', index_source)
        self.assertIn('if (!(await restoreTenantNavigation(requestedPage))) {', index_source)
        self.assertIn('async function restoreTenantNavigation(preferredPageId = null)', index_source)
        self.assertIn('if (preferredPageId && document.getElementById(preferredPageId)) state.pageId = preferredPageId;',
                      index_source)

    def test_designer_edit_keeps_the_presentation_images(self):
        """An edited slide used to come back with its image markers unresolved, so cards rendered empty."""
        module = self.application_module
        html = ('<div class="slide"><img src="##MOODBOARD_IMAGE_1##"><img src="##MOODBOARD_IMAGE_2##">'
                '<img src="##IMAGE_COVER##"><img src="##MAP_OVERVIEW##"></div>')
        creative = {
            'cover': '/uploads/creative/cover.png',
            'moodboard': ['/uploads/creative/mb1.png', '/uploads/creative/mb2.png'],
            'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/overview.png'},
        }
        # clean_project_data() strips creativeImages, so reading the images off project data
        # could never work; they arrive in their own key, or under tenantCreativeImages.
        self.assertNotIn('creativeImages', module.clean_project_data({'creativeImages': creative}))

        resolved = module.resolve_designer_chat_placeholders(html, {}, None, 'tenant-x', creative)
        self.assertIn('/uploads/creative/mb1.png', resolved)
        self.assertIn('/uploads/creative/mb2.png', resolved)
        self.assertIn('/uploads/creative/cover.png', resolved)
        self.assertIn('/uploads/maps/overview.png', resolved)
        self.assertNotIn('##MOODBOARD_IMAGE_1##', resolved)
        self.assertNotIn('##IMAGE_COVER##', resolved)

        from_draft = module.resolve_designer_chat_placeholders(
            html, {'tenantCreativeImages': creative}, None, 'tenant-x')
        self.assertIn('/uploads/creative/mb1.png', from_draft)
        self.assertNotIn('##IMAGE_COVER##', from_draft)

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        # Every edit path must carry the images, and a blind edit must say it was blind.
        self.assertIn('creative_images=creative_images', app_source)
        self.assertIn('التعديل جرى على الكود بدون معاينة بصرية للشريحة.', app_source)

    def test_no_slide_can_be_built_from_images_that_do_not_exist(self):
        """A slide came out as four empty frames: it used ##STREET_VIEW_1..4##, which nothing
        produces, and the unresolved tokens were blanked into src="" / url() — an empty card."""
        import slide_engine as engine
        self.assertIn('لا تكتب ##STREET_VIEW_1##', engine.NO_STREET_VIEW_RULE)
        for source in ('slide_engine.py', 'app.py', 'design_templates.py'):
            text = (ROOT / source).read_text(encoding='utf-8')
            # No line may still offer the token to the model.
            for line in text.splitlines():
                if 'STREET_VIEW' not in line:
                    continue
                self.assertNotIn('استخدم', line, f'{source}: {line.strip()}')
                self.assertNotIn('لصور الموقع', line, f'{source}: {line.strip()}')
        # The plan can no longer ask for such a slide, and one from an old draft is dropped.
        self.assertNotIn('site_photos', engine.SLIDE_PLAN_PROMPT)
        plan = engine.strip_street_view_slides({'slides': [
            {'title': 'الغلاف', 'type': 'cover'},
            {'title': 'قراءة بصرية للموقع', 'type': 'site_photos'},
            {'title': 'الختام', 'type': 'closing'},
        ]})
        self.assertEqual([s['type'] for s in plan['slides']], ['cover', 'closing'])
        self.assertNotIn('site_photos', engine.validate_slide_plan(
            {'slides': [{'title': 'x', 'type': 'site_photos'}]}, {})[1].__str__().replace(
                "unknown type 'site_photos'", ''))

        # An image token that reaches the end of the pipeline takes its carrier with it.
        html = ('<div class="slide">'
                '<div style="background-image:url(##STREET_VIEW_1##);width:200px"></div>'
                '<img src="##STREET_VIEW_2##" alt="">'
                '<div style="background-image:url();width:200px"></div>'
                '<img src="" alt="">'
                '<img src="/uploads/creative/cover.png" alt="">'
                '</div>')
        cleaned = engine._drop_unresolved_image_placeholders(html)
        self.assertNotIn('##STREET_VIEW', cleaned)
        self.assertNotIn('url()', cleaned)
        self.assertNotIn('src=""', cleaned)
        self.assertIn('/uploads/creative/cover.png', cleaned)
        # An unavailable map is stated as forbidden instead of being left unmentioned.
        with self.application_module.app.test_request_context():
            self.application_module.g.tenant_id = self.tenant_a
            info = self.application_module._get_images_info(
                {'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/overview.png'}}, {})
        self.assertIn('##MAP_OVERVIEW##', info)
        self.assertIn('ممنوع كتابة ##MAP_CATCHMENT##', info)
        self.assertIn('ممنوع كتابة ##PLAN_IMAGE_N##', info)
        self.assertIn('##STREET_VIEW_1##', info)

    def test_export_names_the_slide_it_could_not_print(self):
        """«25 صفحة مقابل 50 شريحة» is not actionable on its own: the deck is inspected per entry and
        the printed layout is measured, so the failure names the slides behind it."""
        import generate_pdf_from_preview as engine

        html, notes = self.application_module._export_html_from_slides([
            {'title': 'الغلاف', 'html': '<div class="slide"><h1>THE VIEW</h1></div>'},
            {'title': 'بلا إطار', 'html': '<h1>محتوى بلا إطار شريحة</h1>'},
            {'title': 'فارغة', 'html': ''},
            {'title': 'مدمجة', 'html': '<div class="slide">أ</div><div class="slide">ب</div>'},
        ])
        # The entry with no .slide root is wrapped so it still owns a page, and it is reported.
        # 1 cover + 1 wrapped + 2 from the merged entry; the empty entry contributes nothing.
        self.assertEqual(html.count('class="slide"'), 4)
        self.assertIn('محتوى بلا إطار شريحة', html)
        joined = ' | '.join(notes)
        self.assertIn('شرائح بلا محتوى: 3', joined)
        self.assertIn('شرائح بلا إطار شريحة', joined)
        self.assertIn('شرائح تحتوي أكثر من شريحة: 4', joined)

        faults = engine.describe_slide_layout_faults([
            {'index': 1, 'position': 'relative', 'display': 'block', 'cssFloat': 'none', 'height': 720},
            {'index': 2, 'position': 'absolute', 'display': 'block', 'cssFloat': 'none', 'height': 720},
            {'index': 3, 'position': 'static', 'display': 'none', 'cssFloat': 'none', 'height': 720},
            {'index': 4, 'position': 'static', 'display': 'block', 'cssFloat': 'left', 'height': 360},
        ])
        self.assertEqual(len(faults), 3)
        self.assertIn('الشريحة 2 (position:absolute)', faults)
        self.assertIn('display:none', faults[1])
        self.assertIn('height:360px', faults[2])

        # The build in use is reportable, so "is the fix deployed" has an answer.
        build = self.app.test_client().get('/api/build').get_json()
        self.assertTrue(build['commit'])
        self.assertTrue(build['startedAt'])

    def test_designer_chat_remembers_the_conversation_and_the_slide(self):
        """It used to receive the current message alone: it asked «أي شريحة؟», the answer arrived at
        a model that had never asked, and the next turn asked again."""
        module = self.application_module
        history = [
            {'role': 'user', 'content': 'الشريحة 8 فيها مشكلة', 'slides': [8]},
            {'role': 'assistant', 'content': 'ما هي المشكلة تحديدًا؟', 'slides': [8]},
        ]
        memory, recent = module._designer_chat_memory(history, '')
        self.assertEqual(memory, '')
        self.assertEqual(len(recent), 2)
        lines = module._designer_chat_history_lines(recent)
        self.assertIn('المستخدم [شرائح: 8]: الشريحة 8 فيها مشكلة', lines[0])

        # A long conversation is compressed once, not carried whole.
        long_history = [{'role': 'user', 'content': 'ك' * 900, 'slides': [3]} for _ in range(20)]
        with patch.object(module, 'call_zai_chat',
                          return_value={'choices': [{'message': {'content': 'ملخص: الحديث عن الشريحة 3.'}}]}) as chat:
            compressed, kept = module._designer_chat_memory(long_history, '')
        self.assertTrue(chat.called)
        self.assertIn('الشريحة 3', compressed)
        self.assertEqual(len(kept), module.DESIGNER_CHAT_VERBATIM_TURNS)

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('## ذاكرة المحادثة (ملخص ما سبق)', app_source)
        self.assertIn('## آخر رسائل المحادثة بالترتيب', app_source)
        self.assertIn('## الشرائح التي تدور عنها المحادثة الآن', app_source)
        self.assertIn("req_indexes = list(focus_indexes)", app_source)
        self.assertIn("'memory': chat_memory", app_source)

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('memory: tenantDesignerChatMemory,', index_source)
        self.assertIn('focusIndexes: tenantChatFocusIndexes,', index_source)
        self.assertIn('function applyDesignerChatMemory(reply)', index_source)
        self.assertIn('function restoreDesignerChat(source)', index_source)
        self.assertIn('data.designerChat = {', index_source)
        # The conversation is restored with the file instead of being wiped on open.
        self.assertNotIn('tenantDesignerMessages = [];\n      tenantChatSlideIndex', index_source)
        self.assertIn("'designerChat'", (ROOT / 'db.py').read_text(encoding='utf-8'))

    def test_untouched_financial_study_is_not_sent_as_approved_tables(self):
        """The section snapshots itself for every project, so defaults must not become facts."""
        import slide_engine as engine
        defaults_only = {
            'inputs': {'developmentYears': 4, 'developerRate': 10, 'annualFinanceRate': 6,
                       'projectCost': 0, 'landValue': 0, 'totalBuiltUpArea': 0},
            'projection': {'roi': 0, 'irr': 0},
            'dynamicRows': {'components': [], 'revenue': []},
            'tables': {'componentsTable': []},
        }
        self.assertFalse(engine.financial_study_has_real_input(defaults_only))
        # Silence is not neutral: the absence is stated so the model cannot fill the gap.
        absent_note = engine._financial_data_note({'financial_study_model': defaults_only})
        self.assertEqual(absent_note, engine.FINANCIAL_ABSENT_NOTE)
        self.assertNotIn('الجداول المالية المعتمدة أدناه', absent_note)

        entered = dict(defaults_only, inputs=dict(defaults_only['inputs'], projectCost=480000000))
        self.assertTrue(engine.financial_study_has_real_input(entered))
        entered_note = engine._financial_data_note({'financial_study_model': entered})
        self.assertIn('المؤشرات المالية بمسمياتها الأصلية', entered_note)
        # An entered study is copied, never recomputed or extended.
        self.assertIn('فواصل الآلاف', entered_note)
        self.assertIn('الرقم أو المؤشر غير الموجود لا يُكتب', entered_note)
        self.assertIn('لا تحذف صفاً أو عموداً أو سنة', entered_note)

        # A plan for a project with no figures carries no financial slide from any source.
        plan = {'slides': [
            {'title': 'الغلاف', 'type': 'cover', 'design_style': 'image'},
            {'title': 'التحليل المالي والجدوى', 'type': 'content', 'design_style': 'dashboard'},
            {'title': 'مؤشرات الأداء والقيمة المضافة', 'type': 'content', 'design_style': 'dashboard'},
            {'title': 'الموقع والمميزات', 'type': 'content', 'design_style': 'map'},
        ]}
        stripped = engine.strip_financial_slides(json.loads(json.dumps(plan)),
                                                 {'financial_study_model': defaults_only})
        self.assertEqual([slide['title'] for slide in stripped['slides']],
                         ['الغلاف', 'الموقع والمميزات'])
        self.assertEqual(stripped['proposed_count'], 2)
        kept = engine.strip_financial_slides(json.loads(json.dumps(plan)),
                                            {'financial_study_model': entered})
        self.assertEqual(len(kept['slides']), 4)

        by_components = dict(defaults_only,
                             dynamicRows={'components': [{'name': 'شقق سكنية', 'builtArea': 24000}]})
        self.assertTrue(engine.financial_study_has_real_input(by_components))

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("if (key === 'financial_study_model') {", index_source)
        self.assertIn('const report = tenantFinancialPresentationReport', index_source)
        self.assertIn("tenantFinancialPresentationReport = financialStudyHasRealInput", index_source)
        # Generating from a name alone can only produce invented content, so it is stated, not hidden.
        self.assertIn('const GENERATION_MIN_FACTS = 6;', index_source)
        self.assertIn('const factCount = countProjectFacts(tenantProjectData);', index_source)

    def test_slide_plan_runs_as_a_polled_job_so_the_proxy_cannot_drop_it(self):
        """A full project needs minutes to plan, and the live proxy kills a request held that long."""
        client = self.app.test_client()
        with patch.object(self.application_module, 'call_zai_chat_parallel', side_effect=RuntimeError('AI unavailable')):
            queued = client.post('/api/slide-plan', headers=self._headers(self.token_a), json={
                'projectData': {'project_name': 'مشروع تجريبي', 'project_type': 'سكني'},
                'background': True,
            })
            self.assertEqual(queued.status_code, 202, queued.get_json())
            job_id = queued.get_json()['jobId']

            job = {}
            for _ in range(80):
                time.sleep(0.05)
                polled = client.get('/api/slide-plan/jobs/' + job_id, headers=self._headers(self.token_a))
                self.assertEqual(polled.status_code, 200, polled.get_json())
                job = polled.get_json()
                if job.get('status') in ('completed', 'failed'):
                    break

        self.assertEqual(job.get('status'), 'completed', job)
        self.assertTrue(job['plan']['slides'])

        missing = client.get('/api/slide-plan/jobs/00000000-0000-0000-0000-000000000000',
                             headers=self._headers(self.token_a))
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()['failureReason'], 'job_not_found')

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
        self.assertIn('id="section-visual-concept"', index_source)
        self.assertIn("createProjectSectionHeader('section-visual-concept', 'التصور البصري')", index_source)
        self.assertIn('function addVisualConceptSection(form', index_source)
        self.assertIn("tenantVisualConceptPage: '/app/projects/visual-concept'", index_source)
        self.assertNotIn('اختاري كرت التصور الخارجي أو الداخلي', index_source)
        self.assertIn('data-visual-concept-target="external"', index_source)
        self.assertIn('data-visual-concept-target="internal"', index_source)
        self.assertIn('data-visual-caption', index_source)
        self.assertNotIn('data-conceptual-plan-caption', index_source)
        self.assertNotIn('function addConceptualPlansSection(form, before)', index_source)
        self.assertNotIn('function conceptualPlansNeedCaptions()', index_source)
        self.assertIn('<label>وصف الصورة</label>', index_source)
        self.assertNotIn('placeholder="وصف الصورة (اختياري)"', index_source)
        self.assertIn('visualConceptInteriorComponentSelect', index_source)
        self.assertIn('function uploadVisualConceptInteriorReferences', index_source)
        self.assertIn('function uploadVisualConceptSlotImage(slotId, input)', index_source)
        self.assertIn('VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 4', index_source)
        self.assertIn("data-visual-action=\"add-interior\"", index_source)
        self.assertIn('function showVisualConceptView(view)', index_source)
        self.assertIn('function persistVisualConceptDraftState()', index_source)
        self.assertIn("data-key=\"visual_concept\"", index_source)
        self.assertIn('function persistVisualConceptDraftState()', index_source)
        self.assertIn('saveProjectAsDraft', index_source)
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
        self.assertIn('data-visual-upload', index_source)
        self.assertIn('data-visual-title', index_source)
        self.assertIn('function visualConceptCanRenameSlot(slotId)', index_source)
        self.assertNotIn('visual-concept-grid', index_source)
        # The legacy floor-design page is gone: 2D plans and isometric are cards here now.
        self.assertNotIn('tenantFloorDesignPage', index_source)
        self.assertNotIn('floor_visual_design', index_source)
        self.assertNotIn('/api/floor-design/', index_source)
        self.assertNotIn('/api/floor-design/', (ROOT / 'app.py').read_text(encoding='utf-8'))
        self.assertIn('data-visual-concept-target="plans2d"', index_source)
        self.assertIn('data-visual-concept-target="isometric" disabled', index_source)
        self.assertIn('id="visualConceptPlansView"', index_source)
        self.assertIn('id="visualConceptIsometricView"', index_source)
        # 2D plans: unlimited client uploads, each with its own title and description,
        # and AI generation is not built yet.
        self.assertIn('VISUAL_CONCEPT_MAX_PLANS = 30', index_source)
        self.assertIn('function normalizeVisualConceptPlans(raw)', index_source)
        self.assertIn('function renderVisualConceptPlans()', index_source)
        self.assertIn('async function uploadVisualConceptPlanImages(input)', index_source)
        self.assertIn('function deleteVisualConceptPlan(planId)', index_source)
        self.assertIn('data-visual-plan-title', index_source)
        self.assertIn('data-visual-plan-description', index_source)
        self.assertIn('id="visualConceptPlansGenerateButton" disabled', index_source)
        self.assertIn("new Set(['home', 'external', 'internal', 'plans2d', 'isometric'])", index_source)
        self.assertIn('plans2d: plans', index_source)
        self.assertNotIn('نفس المبنى المعتمد', index_source)
        self.assertNotIn('tenantMainImagePage', index_source)
        self.assertNotIn('tenantMoodboardPage', index_source)
        self.assertNotIn('tenantMainImagePromptInput', index_source)
        self.assertNotIn('tenantMoodboardPreview', index_source)

    def test_ui_carries_no_static_how_to_hints(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        # Owner rule: the screen states what a thing is, never how to operate it.
        for instruction in (
            'ولّد الصورة الرئيسية أولًا من بيانات المشروع',
            'اختياري: ارفع حتى 5 صور لمبانٍ أو واجهات تعجبك',
            'اختر القسم من القائمة الجانبية',
            'عمود «إلى» يُحسب تلقائيًا من البداية والمدة',
            'النطاق يحدد دائرة البحث عن المنافسين',
            'المدينة والحي مرتبطان بقسم الموقع والخرائط',
            'توليد المنافسين يمسح الجدول ويضع النتيجة الجديدة',
            'اضغط على المخطط للتكبير الكامل',
            'حدد الأقسام التي يمكن للموظف الوصول إليها',
            'فعّل رسم حدود الموقع ثم أضف النقاط',
        ):
            self.assertNotIn(instruction, index_source, instruction)
        # Status and empty-state text stays: it reports state, it does not teach.
        for kept in (
            'لا توجد بنود مدخلة في هذا الجدول.',
            'زوايا التصور الخارجي مقفلة حتى اعتماد الصورة الرئيسية.',
            'الإحداثيات تحتاج مراجعة واعتماد',
            'لم تُرفع صور للأرض.',
        ):
            self.assertIn(kept, index_source, kept)

    def test_visual_concept_approval_is_one_toggle_per_image(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        start = index_source.index('function renderVisualConceptSlot(slotDef, locked)')
        body = index_source[start:index_source.index('function visualConceptImageUrl(url)')]
        # Same rule as a section: one button, status مسودة / معتمد, card frozen while approved.
        self.assertIn("(approved ? 'unapprove' : 'approve')", body)
        self.assertIn("(approved ? 'الغاء الاعتماد' : 'اعتماد')", body)
        self.assertIn("approved ? 'معتمد'", body)
        self.assertIn("(approved ? ' section-locked' : '')", body)
        self.assertIn('const frozen = approved;', body)
        self.assertNotIn('اعتماد الصورة<', body)
        self.assertIn('function unapproveVisualConceptImage(slotId)', index_source)
        self.assertIn("else if (action === 'unapprove') unapproveVisualConceptImage(slotId);", index_source)
        self.assertIn(".visual-concept-card.section-locked button:not([data-visual-action=\"unapprove\"])", index_source)
        # The legacy tenantCreativeImages mirrors hold previews, so they must not decide approval.
        self.assertIn('if (!stated.cover && tenantCreativeImages.cover) {', index_source)
        self.assertIn('if (!stated[item.id] && moodboardImages[index]) {', index_source)
        self.assertIn("if (slotId === 'cover' && tenantCreativeImages) tenantCreativeImages.cover = '';", index_source)

    def test_visual_concept_generation_writes_to_the_live_slot(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        start = index_source.index('async function generateVisualConceptImage(slotId)')
        body = index_source[start:index_source.index('function approveVisualConceptImage(slotId)')]
        # renderVisualConceptPage reassigns tenantVisualConceptState, so a slot captured
        # before a render is detached and the generated image is written to a dead object.
        self.assertIn('const liveSlot = () => tenantVisualConceptState.slots[slotId];', body)
        self.assertIn('liveSlot().imageUrl = visualConceptImageUrl(response.image);', body)
        self.assertNotIn('const slot = tenantVisualConceptState.slots[slotId];', body)
        self.assertNotIn('slot.imageUrl =', body)
        chat_start = index_source.index('async function sendVisualConceptChat(slotId)')
        chat_body = index_source[chat_start:chat_start + 2200]
        self.assertIn('liveSlot().prompt = response.prompt;', chat_body)
        self.assertNotIn('slot.chat.push({ role: \'assistant\'', chat_body)

    def test_visual_concept_requires_real_project_facts_and_cover_before_moodboard(self):
        client = self.app.test_client()
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("VISUAL_CONCEPT_MOODBOARD_SLOTS = ('right', 'left', 'top', 'back')", source)
        self.assertIn("VISUAL_CONCEPT_EXTERNAL_SLOTS = ('cover', 'right', 'left', 'top', 'back')", source)
        self.assertIn("'overview_map', 'خريطة الأرض / المبنى'", source)
        self.assertIn('style_reference_file_id', source)
        self.assertIn('style_reference_file_ids', source)
        self.assertIn('VISUAL_CONCEPT_MAX_REFERENCE_IMAGES = 5', source)
        self.assertIn('VISUAL_CONCEPT_MAX_INTERIOR_IMAGES = 4', source)
        self.assertIn('You are a smart editor of an existing English architectural image prompt.', source)
        self.assertIn('Current prompt (do not discard):', source)
        self.assertIn('def _visual_concept_slot_label(slot_id, facts=None):', source)
        self.assertEqual(self.application_module._visual_concept_slot_label('right', {'slot_label': 'الواجهة الشمالية'}), 'الواجهة الشمالية')
        self.assertEqual(self.application_module._visual_concept_slot_label('right', {}), 'يمين')
        self.assertIn("conceptual_plan", source)
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

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('visualConceptInteriorComponentSelect', index_source)
        self.assertIn('function visualConceptInteriorSlotId', index_source)
        self.assertNotIn("function addConceptualPlansSection(form, before)", index_source)
        self.assertNotIn('data-key="conceptual_plans"', index_source)
        self.assertEqual(self.application_module._visual_concept_interior_component_id('interior_comp-1::3'), 'comp-1')

    def test_executive_content_section_generates_each_block_from_existing_facts(self):
        import executive_content

        facts = {
            'projectName': 'ذا فيو',
            'projectType': ['سكني', 'فندقي'],
            'projectIdea': 'منتجع شاطئي',
            'targetAudience': ['عائلات', 'سياح وزوار'],
            'city': 'جدة',
            'allowedUses': 'سكني فندقي',
            'croquisLandArea': '7012',
            'timelineStartYear': '2026',
            'timelineStages': [{'name': 'التصميم', 'year': '2026', 'quarter': 'Q1'}],
            'financialIndicators': {'roi': '12%'},
            'marketSummary': {'decision': 'فرصة واعدة بشروط'},
            'marketSwot': {'strengths': 'موقع بحري'},
        }
        ready, missing = executive_content.block_ready('brief', facts)
        self.assertTrue(ready)
        self.assertEqual(missing, [])
        blocked, needed = executive_content.block_ready('opportunity', {'projectName': 'ذا فيو', 'projectType': 'سكني'})
        self.assertFalse(blocked)
        self.assertIn('financial', needed)
        self.assertIn('summary', [item['key'] for item in executive_content.BLOCKS])
        self.assertNotIn('swot', [item['key'] for item in executive_content.BLOCKS])
        parsed = executive_content.parse_generated_block('summary', {
            'sections': [
                {'heading': 'البيانات الأساسية', 'text': 'منتجع شاطئي في جدة'},
                {'heading': 'دراسة السوق', 'text': 'فرصة واعدة بشروط'},
            ]
        })
        self.assertIn('البيانات الأساسية', parsed)
        self.assertIn('منتجع شاطئي في جدة', parsed)
        self.assertIn('\n\n', parsed)
        compact = executive_content.compact_facts(facts)
        self.assertEqual(compact['allowedUses'], 'سكني فندقي')
        self.assertEqual(compact['timelineStages'][0]['name'], 'التصميم')
        self.assertEqual(compact['marketSwot']['strengths'], 'موقع بحري')
        summary_facts = {
            **facts,
            'generatedBlocks': {'brief': 'نص السكشن فقط', 'risks': 'خطر من السكشن'},
            'marketOneBlockSummary': 'ملخص سوق المشروع من الدراسة',
        }
        summary_compact = executive_content.compact_facts(summary_facts, for_block='summary')
        self.assertEqual(summary_compact['generatedBlocks'], {})
        self.assertEqual(summary_compact['marketOneBlockSummary'], 'ملخص سوق المشروع من الدراسة')
        other_compact = executive_content.compact_facts(summary_facts, for_block='brief')
        self.assertEqual(other_compact['generatedBlocks']['brief'], 'نص السكشن فقط')
        parsed_risks = executive_content.parse_generated_block('risks', {
            'items': [
                {'risk': 'ارتفاع تكلفة التنفيذ', 'mitigation': 'تثبيت عقود المقاولين'},
                {'risk': 'تأخر التصاريح', 'mitigation': ''},
            ]
        })
        self.assertIn('الخطر: ارتفاع تكلفة التنفيذ', parsed_risks)
        self.assertIn('المعالجة: تثبيت عقود المقاولين', parsed_risks)
        self.assertIn('الخطر: تأخر التصاريح', parsed_risks)
        summary_ready, summary_missing = executive_content.block_ready('summary', facts)
        self.assertTrue(summary_ready)
        self.assertEqual(summary_missing, [])

        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        module_source = (ROOT / 'executive_content.py').read_text(encoding='utf-8')
        self.assertIn("function addExecutiveContentSection(form, before)", index_source)
        self.assertIn("addExecutiveContentSection(form);", index_source)
        self.assertIn("id = 'section-executive-content'", index_source)
        self.assertIn('data-key="executive_content"', index_source)
        self.assertIn("function generateExecutiveContentBlock(key)", index_source)
        self.assertIn("api('POST', '/api/executive-content/generate'", index_source)
        self.assertIn("createProjectSectionHeader('section-executive-content', 'المحتوى التنفيذي')", index_source)
        self.assertIn("function collectExecutiveContentFacts()", index_source)
        self.assertIn("function collectExecutiveTeamFacts()", index_source)
        self.assertIn("function collectExecutiveTimelineFacts()", index_source)
        self.assertNotIn("بيانات مرتبطة من الأقسام السابقة", index_source)
        self.assertNotIn("underConstruction: true", index_source)
        self.assertNotIn('executiveSwot_', index_source)
        self.assertNotIn("{ key: 'swot', label: 'تحليل SWOT' }", index_source)
        self.assertIn("def api_generate_executive_content():", app_source)
        self.assertIn('EXECUTIVE_SUMMARY_MAX_TOKENS', app_source)
        self.assertIn('لا تخترع', module_source)
        self.assertIn('الملخص التنفيذي الشامل', module_source)
        self.assertIn('بيانات المشروع', module_source)
        self.assertIn('طريقة معالجته', module_source)
        self.assertIn("'output': 'document'", module_source)
        self.assertIn("'output': 'risks'", module_source)
        self.assertIn('for_block != \'summary\'', module_source)
        self.assertIn('marketOneBlockSummary', index_source)

        client = self.app.test_client()
        refused = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
            'block': 'opportunity',
            'facts': {'projectName': 'ذا فيو', 'projectType': 'سكني'},
        })
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertIn('استكمل', refused.get_json()['error'])

        with patch.object(self.application_module, 'call_zai_chat', return_value={'choices': [{'message': {'content': '{"text":"نبذة من الفكرة فقط"}'}}]}), \
             patch.object(self.application_module, 'extract_chat_content', return_value='{"text":"نبذة من الفكرة فقط"}'):
            generated = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
                'block': 'brief',
                'facts': facts,
            })
        self.assertEqual(generated.status_code, 200, generated.get_json())
        self.assertEqual(generated.get_json()['text'], 'نبذة من الفكرة فقط')

        summary_payload = '{"text":"البيانات الأساسية\\nمنتجع شاطئي\\n\\nالدراسة المالية\\nالعائد 12%"}'
        with patch.object(self.application_module, 'call_zai_chat', return_value={'choices': [{'message': {'content': summary_payload}}]}) as chat_call, \
             patch.object(self.application_module, 'extract_chat_content', return_value=summary_payload):
            summary = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
                'block': 'summary',
                'facts': facts,
            })
        self.assertEqual(summary.status_code, 200, summary.get_json())
        self.assertIn('البيانات الأساسية', summary.get_json()['text'])
        self.assertEqual(chat_call.call_args.kwargs.get('max_tokens'), self.application_module.EXECUTIVE_SUMMARY_MAX_TOKENS)

        parsed_dict = executive_content.parse_generated_block('summary', {'البيانات الأساسية': 'منتجع', 'الموقع': 'جدة'})
        self.assertIn('البيانات الأساسية\nمنتجع', parsed_dict)
        self.assertIn('الموقع\nجدة', parsed_dict)

        raw_md = 'البيانات الأساسية\nمشروع ذا فيو في جدة\n\nالدراسة المالية\nعائد استثماري متميز'
        with patch.object(self.application_module, 'call_zai_chat', return_value={'choices': [{'message': {'content': raw_md}}]}), \
             patch.object(self.application_module, 'extract_chat_content', return_value=raw_md):
            summary_raw = client.post('/api/executive-content/generate', headers=self._headers(self.token_a), json={
                'block': 'summary',
                'facts': {'projectName': 'ذا فيو', 'projectType': 'سكني'},
            })
        self.assertEqual(summary_raw.status_code, 200, summary_raw.get_json())
        self.assertIn('مشروع ذا فيو في جدة', summary_raw.get_json()['text'])

    def test_market_study_fields_and_section_are_wired(self):
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("function addMarketStudySection(form, before)", index_source)
        self.assertIn("addMarketStudySection(form);", index_source)
        self.assertIn("id = 'section-market-study'", index_source)
        self.assertIn("data-key=\"market_study_data\"", index_source)
        self.assertIn("function runMarketCompetitorsJob(mode)", index_source)
        self.assertIn("function runMarketSummaryJob()", index_source)
        self.assertIn('id="marketStudyOneBlockSummary"', index_source)
        self.assertIn('function buildMarketStudyOneBlockSummary(state = {})', index_source)
        self.assertIn('<th>القيمة (ر.س)</th>', index_source)
        self.assertIn('source_urls', index_source)
        self.assertNotIn('<textarea data-field="source_urls"', index_source)
        self.assertIn('id="marketSourcesTabs"', index_source)
        self.assertIn('id="marketSourcesPanels"', index_source)
        self.assertIn('function selectMarketSourceTab(key)', index_source)
        self.assertIn('class="market-sources-table"', index_source)
        self.assertNotIn('<table id="marketSourcesTable">', index_source)
        self.assertIn("tr.querySelectorAll('[data-source-links] a[href]')", index_source)
        self.assertIn('function mergeMarketSourceRows(existing, incoming)', index_source)
        self.assertIn('const visibleRows = Array.isArray(rows) && rows.length ? rows : [{}];', index_source)
        self.assertIn('function inferCompetitorPriceType(row = {})', index_source)
        self.assertIn('min-width: 1450px;', index_source)
        self.assertIn('width: max-content;', index_source)
        self.assertIn('min-width: 2200px;', index_source)
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
        self.assertIn("'type': 'openrouter:web_search',", app_source)
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
        self.assertEqual(updated_fill, 2)
        self.assertEqual([row['name'] for row in filled], ['مشروع العميل'])
        self.assertEqual(filled[0]['id'], 'keep-me')
        self.assertEqual(filled[0]['source'], 'العميل')
        self.assertEqual(filled[0]['price_type'], 'أخرى')
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
        normalized = market_study.normalize_summary({
            'one_block_summary': 'عنوان الملخص\\n\\nفقرة الملخص.',
            'summary': {},
        })
        self.assertEqual(normalized['one_block_summary'], 'عنوان الملخص\n\nفقرة الملخص.')
        summary_prompt = market_study.build_summary_user_prompt({}, [])
        self.assertIn('one_block_summary', summary_prompt)
        prompt = market_study.build_consultant_system_prompt()
        self.assertIn('رابط الصفحة بالضبط', prompt)

    def test_market_study_keeps_all_competitor_urls_and_builds_source_rows(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'برج الأعمال',
            'operation_type': 'بيع',
            'price_type': 'سعر المتر المربع',
            'price_value': '4500',
            'source_urls': [
                'https://developer.example/project',
                'https://listing.example/project-123',
            ],
            'field_sources': {
                'name': ['https://developer.example/project'],
                'area_sqm': ['https://listing.example/project-123'],
            },
            'source': 'المطور ومنصة الإعلانات',
        })
        self.assertEqual(row['source_url'], 'https://developer.example/project')
        self.assertEqual(row['source_urls'], [
            'https://developer.example/project',
            'https://listing.example/project-123',
        ])
        self.assertEqual(row['field_sources'], {
            'name': ['https://developer.example/project'],
            'area_sqm': ['https://listing.example/project-123'],
        })
        self.assertEqual(row['price_type'], 'سعر المتر المربع')
        self.assertEqual(row['price_value'], '4500')
        sources = market_study.competitor_source_rows([row])
        self.assertEqual([item['url'] for item in sources], row['source_urls'])
        self.assertEqual([item['competitor_name'] for item in sources], ['برج الأعمال', 'برج الأعمال'])
        self.assertEqual(sources[0]['source_fields'], ['اسم المشروع'])
        self.assertEqual(sources[1]['source_fields'], ['مساحة الوحدة'])

    def test_market_study_normalizes_price_object_and_operation_aliases(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'فندق الأعمال',
            'project_type': 'فندقي',
            'operation': 'sale',
            'price': {'type': 'سعر الوحدة', 'value': 1200000},
            'sources': [
                {'url': 'https://developer.example/hotel'},
                {'source_url': 'https://listing.example/hotel-1'},
            ],
        })
        self.assertEqual(row['operation_type'], 'بيع')
        self.assertEqual(row['price_type'], 'سعر الوحدة')
        self.assertEqual(row['price_value'], '1200000')
        self.assertEqual(row['source_urls'], [
            'https://developer.example/hotel',
            'https://listing.example/hotel-1',
        ])
        derived = market_study.normalize_competitor_row({
            'name': 'وحدة سكنية',
            'price_type': 'سعر الوحدة',
            'price_value': '900000',
        })
        self.assertEqual(derived['operation_type'], 'بيع')

    def test_market_study_accepts_arabic_price_aliases(self):
        import market_study
        row = market_study.normalize_competitor_row({
            'name': 'فندق جدة',
            'project_type': 'فندقي',
            'operation': 'تشغيل',
            'نوع السعر': 'سعر الليلة',
            'القيمة': '1548',
            'field_sources': {
                'price_type': ['https://example.com/price'],
                'price_value': ['https://example.com/price'],
            },
        })
        self.assertEqual(row['operation_type'], 'تشغيل فندقي')
        self.assertEqual(row['price_type'], 'سعر الليلة')
        self.assertEqual(row['price_value'], '1548')
        ranged = market_study.normalize_competitor_row({
            'name': 'فندق جدة بنطاق سعري',
            'operation': 'تشغيل',
            'نوع السعر': 'نطاق أسعار الغرف',
            'من': '900',
            'إلى': '1500',
        })
        self.assertEqual(ranged['price_type'], 'نطاق أسعار الغرف')
        self.assertEqual(ranged['price_from'], '900')
        self.assertEqual(ranged['price_to'], '1500')

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

    def test_market_study_searches_before_it_falls_back_to_json_mode(self):
        module = self.application_module
        responses = [
            {'error': {'message': 'web search response was empty'}},
            {'choices': [{'message': {'content': 'not valid json'}}]},
            {'choices': [{'message': {'content': 'still not json'}}]},
            {'choices': [{'message': {'content': '{"competitors": []}'}}]},
        ]
        calls = []

        def fake_call(system_prompt, user_content, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

        with patch.object(module, 'call_openrouter_chat', side_effect=fake_call) as call:
            response, error = module._call_market_study_model('system', 'user', max_tokens=6000)

        self.assertTrue(module._has_chat_choices(response))
        self.assertEqual(call.call_count, 4)
        # Gemini answers a tools + JSON-mode call with reasoning only, so searching with
        # JSON mode off must be the first attempt or no search ever runs.
        self.assertIsNotNone(calls[0]['tools'])
        self.assertIsNone(calls[0]['response_format'])
        self.assertIsNotNone(calls[1]['tools'])
        self.assertEqual(calls[1]['response_format'], {'type': 'json_object'})
        self.assertIsNone(calls[2]['tools'])
        self.assertEqual(calls[2]['response_format'], {'type': 'json_object'})
        self.assertIsNone(calls[3]['tools'])
        self.assertIsNone(calls[3]['response_format'])
        self.assertEqual(error, '')

    def test_market_study_uses_the_retrieved_page_for_homepage_links(self):
        import market_study
        module = self.application_module
        citations = [
            'https://sa.aqar.fm/',
            'https://sa.aqar.fm/%D8%B4%D9%82%D9%82-%D9%84%D9%84%D8%A8%D9%8A%D8%B9/12345',
            'https://www.stats.gov.sa/statistics/housing-2026',
        ]
        response = {'choices': [{'message': {'annotations': [
            {'type': 'url_citation', 'url_citation': {'url': url}} for url in citations
        ]}}]}
        self.assertEqual(module._market_citation_urls(response), citations)
        rows = [
            {'name': 'برج سكني', 'source_url': 'https://sa.aqar.fm/', 'row_source': 'ai'},
            {'name': 'برج العميل', 'source_url': 'https://sa.aqar.fm/', 'row_source': 'user'},
        ]
        market_study.apply_search_citations(rows, citations)
        self.assertEqual(rows[0]['source_url'], citations[1])
        self.assertEqual(rows[1]['source_url'], 'https://sa.aqar.fm/')
        sources = [{'name': 'الهيئة العامة للإحصاء', 'url': 'https://www.stats.gov.sa'}]
        market_study.apply_search_citations(sources, citations, url_key='url')
        self.assertEqual(sources[0]['url'], citations[2])
        multi = [{
            'name': 'برج متعدد المصادر',
            'source_urls': ['https://sa.aqar.fm/', 'https://www.stats.gov.sa/statistics/housing-2026'],
            'row_source': 'ai',
        }]
        market_study.apply_search_citations(multi, citations)
        self.assertEqual(multi[0]['source_urls'], [citations[1], citations[2]])
        self.assertEqual(multi[0]['source_url'], citations[1])
        prompt = market_study.build_competitors_user_prompt({'city': 'جدة'}, [], mode='generate')
        self.assertIn('رابط النطاق وحده أو الصفحة الرئيسية غير مقبول', prompt)
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("market_study.apply_search_citations(merged, _market_citation_urls(res))", app_source)

    def test_market_study_prices_require_a_dedicated_search(self):
        import market_study
        prompt = market_study.build_competitors_user_prompt({'city': 'جدة'}, [], mode='generate')
        # One market-wide search cannot price six competitors; every price used to come back
        # empty because the model searched once and answered the rest from memory.
        self.assertIn('بروتوكول البحث الإلزامي', prompt)
        self.assertIn('نفّذ بحثًا منفصلًا لكل منافس على حدة عن سعره الفعلي', prompt)
        self.assertIn('لا تكتب سعرًا من معرفتك السابقة', prompt)
        self.assertIn('source_urls', prompt)
        self.assertIn('field_sources', prompt)
        self.assertIn('مساحة الوحدة القابلة للبيع', prompt)
        self.assertIn('Tower GFA', prompt)
        self.assertIn('price_type والقيمة', prompt)
        self.assertIn(market_study.MISSING_VALUE_PHRASE, prompt)
        self.assertIn('سعر الليلة', prompt)
        self.assertIn('متوسط سعر الغرفة ADR', prompt)
        self.assertIn('إيجار المتر السنوي', prompt)
        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("'max_uses': 10", app_source)
        self.assertIn("'engine': 'exa'", app_source)

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
                {
                    'name': 'برج الشمال',
                    'project_type': 'سكني',
                    'classification': 'مباشر',
                    'status': 'قائم',
                    'operation_type': 'بيع',
                    'price_type': 'سعر الوحدة',
                    'price_value': '1200000',
                    'source': 'موقع المطور',
                    'source_urls': [
                        'https://developer.example/north-tower',
                        'https://listing.example/north-tower',
                    ],
                }
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
        generated_payload = generated.get_json()
        generated_names = [row['name'] for row in generated_payload['competitors']]
        self.assertEqual(generated_names, ['برج الشمال'])
        self.assertEqual(
            [row['url'] for row in generated_payload['sources']],
            ['https://developer.example/north-tower', 'https://listing.example/north-tower'],
        )
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

    def test_contact_section_and_fields_registered_and_piped(self):
        """Contact information section and its 7 fields are registered in schema and piped to slide engine."""
        import slide_engine

        # Section exists in FIELD_SECTIONS
        contact_sec = next((s for s in db.FIELD_SECTIONS if s['key'] == 'contact'), None)
        self.assertIsNotNone(contact_sec)
        self.assertEqual(contact_sec['label'], 'بيانات التواصل')

        # 7 prebuilt fields exist in PREBUILT_FIELDS
        prebuilt_by_key = {f['key']: f for f in db.PREBUILT_FIELDS}
        expected_keys = [
            'contact_name', 'contact_position', 'contact_email', 'contact_phone',
            'contact_website', 'contact_address', 'contact_social_media'
        ]
        for key in expected_keys:
            self.assertIn(key, prebuilt_by_key)
            self.assertEqual(prebuilt_by_key[key]['section_key'], 'contact')

        # slide_engine._contact_facts formats all 7 fields
        facts = slide_engine._contact_facts({
            'contact_name': 'سعد الأحمد',
            'contact_position': 'المدير التنفيذي',
            'contact_phone': '0500000000',
            'contact_email': 'info@project.sa',
            'contact_website': 'https://project.sa',
            'contact_address': 'الرياض - طريق الملك فهد',
            'contact_social_media': '@project_sa',
        })
        self.assertIn('سعد الأحمد', facts)
        self.assertIn('المدير التنفيذي', facts)
        self.assertIn('0500000000', facts)
        self.assertIn('info@project.sa', facts)
        self.assertIn('https://project.sa', facts)
        self.assertIn('الرياض - طريق الملك فهد', facts)
        self.assertIn('@project_sa', facts)

        # When no contact data is entered, _contact_facts returns empty string
        empty_facts = slide_engine._contact_facts({})
        self.assertEqual(empty_facts, '')

        # Closing slide prompt instructions
        closing_msg = slide_engine.build_slide_user_msg({'type': 'closing', 'title': 'الخاتمة'}, 10, 10, {}, {})
        self.assertIn('اقتصر على عبارة الشكر والختام فقط', closing_msg)
        self.assertIn('دون اختلاق أو كتابة أي أرقام أو بريد أو عناوين وهمية', closing_msg)

        # Form renders contact section at the end of the form and sidebar
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn("renderFormSection('contact')", index_source)
        exec_pos = index_source.index('addExecutiveContentSection(form);')
        contact_pos = index_source.index("renderFormSection('contact')", exec_pos)
        self.assertGreater(contact_pos, exec_pos)

    def test_empty_sections_are_completely_omitted_from_prompt_and_deck_plan(self):
        """Any section with no real data is completely excluded from prompt facts and deck plan."""
        import slide_engine

        basic_only_draft = {
            'project_name': 'مشروع تجريبي',
            'project_type': 'تجاري',
            'financial_study_model': '{}',
            'market_study_data': '{}',
            'team_selection': '{}',
            'executive_content': '{}',
            'timeline_table_data': '[]',
        }

        # 1. Facts omit all empty sections
        facts = slide_engine.build_project_facts(basic_only_draft)
        self.assertIn('### معلومات أساسية', facts)
        self.assertNotIn('### الدراسة المالية', facts)
        self.assertNotIn('### دراسة السوق', facts)
        self.assertNotIn('### فريق العمل', facts)
        self.assertNotIn('### المحتوى التنفيذي المعتمد', facts)
        self.assertNotIn('### بيانات التواصل المعتمدة للخاتمة', facts)

        # 2. Deck plan omits all empty sections and their dividers
        plan = slide_engine.normalize_presentation_plan({}, project_data=basic_only_draft, images={})
        emitted_sections = {s.get('section_key') for s in plan['slides']}
        self.assertNotIn('financial', emitted_sections)
        self.assertNotIn('team', emitted_sections)
        self.assertNotIn('market', emitted_sections)
        self.assertNotIn('timeline', emitted_sections)
        self.assertNotIn('swot_risks', emitted_sections)
        self.assertNotIn('plans', emitted_sections)
        self.assertNotIn('exterior', emitted_sections)
        self.assertNotIn('interior', emitted_sections)
        self.assertNotIn('executive_summary', emitted_sections)

        # 3. Index slide entries match only emitted sections
        index_slide = next(s for s in plan['slides'] if s.get('type') == 'index')
        index_titles = [e['title'] for e in index_slide.get('index_entries', [])]
        self.assertNotIn('الدراسة المالية', index_titles)
        self.assertNotIn('فريق العمل', index_titles)
        self.assertNotIn('تحليل السوق', index_titles)
        self.assertNotIn('الجدول الزمني', index_titles)
        self.assertIn('الخاتمة', index_titles)


if __name__ == '__main__':
    unittest.main()
