"""Regression checks for the meeting requirements implemented in this change.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import os
import re
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
        # The cap is negotiated in _call_land_analysis_model: too low truncates the JSON, too high
        # is refused outright because the provider reserves max_tokens against the balance.
        self.assertIn('_call_land_analysis_model(\n', app_source)
        self.assertIn('LAND_ANALYSIS_MAX_TOKENS)', app_source)

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

    def test_land_document_form_uses_one_multi_file_field(self):
        fields = self.app.test_client().get('/api/fields', headers=self._headers(self.token_a)).get_json()['fields']
        keys = {field['fieldKey'] for field in fields}
        self.assertIn('land_documents_files', keys)
        self.assertNotIn('land_image_file', keys)
        self.assertNotIn('regulation_reference_file', keys)
        self.assertNotIn('croquis_file', keys)
        self.assertNotIn('building_permit_file', keys)
        self.assertNotIn('north_direction', keys)

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
        for key in ('plan_number', 'subdivision_number', 'deed_date', 'facades_directions', 'land_photos'):
            self.assertIn(key, by_key)
            self.assertEqual(by_key[key]['sectionKey'], 'land_croquis')
        # The plot number is no longer a combined "plot + plan" box.
        self.assertEqual(by_key['plot_number_croquis']['fieldLabel'], 'رقم القطعة')
        self.assertEqual(by_key['deed_date']['fieldLabel'], 'تاريخ الصك')

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
        self.assertIn('const modeFlags=projectModeFlags();', index_source)
        self.assertIn('targetCarry=profit*carryRate', index_source)
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

    def test_team_settings_page_gates_entities_behind_categories(self):
        """The page used to show both forms at once, including eight fields for an entity form whose
        category picker was empty, so it could not be submitted."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        self.assertIn('id="teamEntityFormCard"', index_source)
        self.assertIn('id="teamEntityBlocked"', index_source)
        self.assertIn('if (card) card.hidden = !hasCategories;', index_source)
        self.assertIn('if (blocked) blocked.hidden = hasCategories;', index_source)

        # Numbered steps, and no placeholder option standing in for a real category.
        self.assertIn('١. الأقسام', index_source)
        self.assertIn('٢. الجهات', index_source)
        self.assertNotIn('أضف قسمًا أولاً</option>', index_source)

    def test_team_categories_are_company_defined_with_their_own_capacity(self):
        """Nothing about the categories is fixed in code: the company names each one and decides
        whether it holds a single entity or several."""
        client = self.app.test_client()
        headers = self._headers(self.token_a)

        # No presets ship with the app.
        listed = client.get('/api/team-entities', headers=headers)
        self.assertEqual(listed.status_code, 200, listed.get_json())
        self.assertEqual(listed.get_json()['entities'], [])
        self.assertEqual(listed.get_json()['categories'], [])
        for removed in ('TEAM_SINGLETON_CATEGORIES', 'TEAM_CATEGORY_LABELS'):
            self.assertFalse(hasattr(db, removed), f'{removed} must no longer exist')

        single = client.post('/api/team-categories', headers=headers, json={
            'label': 'المطور العقاري', 'allowMultiple': False})
        self.assertEqual(single.status_code, 201, single.get_json())
        single_id = single.get_json()['category']['id']
        self.assertFalse(single.get_json()['category']['allowMultiple'])

        many = client.post('/api/team-categories', headers=headers, json={'label': 'استشاريون'})
        self.assertEqual(many.status_code, 201, many.get_json())
        many_id = many.get_json()['category']['id']
        self.assertTrue(many.get_json()['category']['allowMultiple'])

        self.assertEqual(client.post('/api/team-categories', headers=headers,
                                     json={'label': 'استشاريون'}).status_code, 409)
        self.assertEqual(client.post('/api/team-categories', headers=headers,
                                     json={'label': '  '}).status_code, 400)

        created = client.post('/api/team-entities', headers=headers, json={
            'categoryId': single_id, 'name': 'منافع الاقتصادية للعقار',
            'experienceYears': '15', 'role': 'مطور المشروع'})
        self.assertEqual(created.status_code, 201, created.get_json())
        entity = created.get_json()['entity']
        self.assertEqual(entity['categoryLabel'], 'المطور العقاري')

        # A single-entity category refuses a second entity; a multi one accepts many.
        self.assertEqual(client.post('/api/team-entities', headers=headers, json={
            'categoryId': single_id, 'name': 'مطور آخر'}).status_code, 409)
        for name in ('مكتب المساحة', 'شركة الإشراف'):
            self.assertEqual(client.post('/api/team-entities', headers=headers, json={
                'categoryId': many_id, 'name': name}).status_code, 201)

        # An entity needs a real category, and a dangling logo id is refused.
        self.assertEqual(client.post('/api/team-entities', headers=headers, json={
            'name': 'بلا قسم'}).status_code, 400)
        self.assertEqual(client.post('/api/team-entities', headers=headers, json={
            'categoryId': 'nope', 'name': 'قسم وهمي'}).status_code, 400)
        self.assertEqual(client.post('/api/team-entities', headers=headers, json={
            'categoryId': many_id, 'name': 'شعار مفقود', 'logoFileId': 'nope'}).status_code, 400)

        # Narrowing a populated category would orphan entities, so it is refused.
        self.assertEqual(client.put('/api/team-categories/' + many_id, headers=headers,
                                    json={'allowMultiple': False}).status_code, 409)

        # Everything is tenant-scoped.
        other = client.get('/api/team-entities', headers=self._headers(self.token_b)).get_json()
        self.assertEqual(other['entities'], [])
        self.assertEqual(other['categories'], [])
        self.assertEqual(len(client.get('/api/team-entities', headers=headers).get_json()['entities']), 3)

        updated = client.put('/api/team-entities/' + entity['id'], headers=headers,
                             json={'categoryId': single_id, 'name': 'منافع', 'role': 'المطور والمشغل'})
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()['entity']['role'], 'المطور والمشغل')

        # Deleting a category detaches its entities instead of destroying them.
        self.assertEqual(client.delete('/api/team-categories/' + many_id, headers=headers).status_code, 200)
        remaining = client.get('/api/team-entities', headers=headers).get_json()['entities']
        self.assertEqual(len(remaining), 3)
        self.assertEqual([item['categoryLabel'] for item in remaining].count(''), 2)

        self.assertEqual(client.delete('/api/team-entities/' + entity['id'], headers=headers).status_code, 200)
        self.assertEqual(client.delete('/api/team-entities/' + entity['id'], headers=headers).status_code, 404)

    def test_project_team_section_scopes_choices_to_one_file(self):
        """A file may drop a library entity, override its role, or add an entity of its own —
        none of which may leak into other projects."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        self.assertIn("div.dataset.section = 'section-team'", index_source)
        self.assertIn("createProjectSectionHeader('section-team', 'فريق العمل')", index_source)
        self.assertIn('data-key="team_selection"', index_source)

        # Team is the second section, right after the basic information.
        self.assertIn('addTeamSection(form, form.querySelector(\'.tenant-form-section[data-section="basic"]\')?.nextSibling)',
                      index_source)

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

    def test_deep_links_serve_the_spa_instead_of_a_404(self):
        """Reloading or sharing a client-side route must not drop the user on an error page."""
        client = self.app.test_client()
        html_headers = {'Accept': 'text/html'}
        for path in ('/', '/app', '/app/dashboard', '/app/projects/new',
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

    def test_timeline_is_the_only_source_of_dev_duration_and_stages(self):
        """The financial study mirrors the timeline read-only so the two cannot disagree."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')

        self.assertIn('function syncFinancialFromTimeline()', index_source)

        # Development duration is taken from the timeline's year count and is not editable here.
        self.assertIn('id="developmentYears" type="number" min="1" value="4" readonly', index_source)
        self.assertNotIn('id="developmentYears" type="number" min="1" value="4" oninput', index_source)
        self.assertIn("مأخوذة من «عدد السنوات» في قسم الجدول الزمني", index_source)

        # Stage name and year are locked; only the two percentages remain editable.
        self.assertIn('<td data-field="name"><input value="${escapeHtml(d.name||\'\')}" readonly', index_source)
        self.assertIn('<td data-field="year"><input type="number" min="1" value="${d.year??1}" readonly', index_source)
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

        # Empty timeline warns rather than silently zeroing the cost distribution.
        self.assertIn('id="timelineStagesWarning"', index_source)
        self.assertIn('warning.hidden = namedStages.length > 0', index_source)

        # The stage table lost its actions column, so the report must stop dropping the last one.
        self.assertIn("reportTableSnapshot('scheduleTable',false)", index_source)

        # Sidebar order comes from append order: the timeline feeds the financial study, so it
        # must be filled first and therefore listed first.
        timeline_at = index_source.index('addTimelineTable(form);')
        financial_at = index_source.index('addFinancialCalculations(form);')
        self.assertLess(timeline_at, financial_at,
                        'the timeline section must be appended before the financial study')

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
        self.assertIn('function addComponent(d={})', index_source)
        self.assertIn('function getComponentRowsData()', index_source)
        self.assertIn('function validateComponentAreas()', index_source)
        self.assertIn("data-field=\"investmentModel\"", index_source)

        # Renamed section.
        self.assertIn("createProjectSectionHeader('section-financial-calc', 'الدراسة المالية والمؤشرات')",
                      index_source)
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
            'tables': {}, 'projection': {'projectCost': 10}
        }
        with self.app.app_context():
            html = self.application_module.build_financial_report_html('مشروع مالي', model, {}, self.tenant_a)
        self.assertNotIn('8. التمويل', html)
        self.assertNotIn('9. الصندوق وأتعابه', html)
        self.assertIn('12. النتائج المالية', html)
        client = self.app.test_client()
        with patch.object(self.application_module, 'generate_financial_pdf') as generate_pdf:
            response = client.post('/api/financial-study/export', headers=self._headers(self.token_a), json={
                'projectName': 'مشروع مالي', 'financialModel': model
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])
        generate_pdf.assert_called_once()

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

    def test_building_rules_keep_ratio_coverage_and_setbacks_together(self):
        """`building_ratio || setbacks` collapsed the field to a bare "60%"."""
        index_source = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('building_ratio_setbacks: parcel.building_ratio || parcel.setbacks', index_source)
        self.assertIn('building_ratio_setbacks: buildingRulesText', index_source)
        for label in ('نسبة البناء', 'نسبة التغطية', 'معامل مسطح البناء (FAR)', 'الارتدادات'):
            self.assertIn("['" + label + "'", index_source)

        app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('"coverage_ratio": ""', app_source)
        self.assertIn('"floor_area_ratio": ""', app_source)
        self.assertIn('لا تكتب «60%» وحدها', app_source)
        self.assertIn('غير محددة في المرجع المتاح', app_source)

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

        def fake_call(system_prompt, user_content, temperature=0.7, max_tokens=8000, model=None, timeout=300):
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
        self.assertIn('لم يتوفر مرجع لائحة الأمانة في هذا الطلب', source)

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
