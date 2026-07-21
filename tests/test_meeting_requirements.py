"""Regression checks for the meeting requirements implemented in this change.

The suite uses a temporary SQLite database and never calls Google or an AI API.
"""

import os
import sys
import tempfile
import unittest
import io
from pathlib import Path

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

    def test_fresh_database_has_meeting_columns(self):
        """Fresh initialization no longer executes multiple DDL statements incorrectly."""
        with self.app.app_context():
            conn = db.get_db()
            training_columns = {row['name'] for row in conn.execute('PRAGMA table_info(tenant_training_data)')}
            draft_columns = {row['name'] for row in conn.execute('PRAGMA table_info(project_drafts)')}
        self.assertTrue({'image_type', 'image_description'}.issubset(training_columns))
        self.assertTrue({'requested_by', 'reviewed_by', 'review_note', 'reviewed_at'}.issubset(draft_columns))

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
