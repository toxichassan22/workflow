"""ISS-014/015/016/019/020 regression tests.

Tenant project-scope enforcement, hidden-section filtering, namespaced body
chunks, export resource policy and image-reference ownership. Temporary
database/media only; no provider calls.
"""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import auth
import db


class ScopeTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'scope.db')
        db.init_db()
        import app as application
        cls.module = application
        cls.app = application.app
        cls.app.config['TESTING'] = True
        cls.patches = [
            patch.object(application, 'UPLOADS_DIR', str(Path(cls.temp.name) / 'uploads')),
            patch.object(application.slide_engine, 'renumber_presentation_slides',
                         side_effect=lambda slides, **kw: slides),
            patch.object(application, '_prepare_generation_logo_context', return_value=None),
            patch.object(application, '_presentation_creative_images', return_value={}),
        ]
        for item in cls.patches:
            item.start()
        with cls.app.app_context():
            cls.tenant = db.create_tenant('Scope Tenant', 'scope@example.test', 'hash', 'scope-tenant')
            cls.other = db.create_tenant('Other Tenant', 'other-scope@example.test', 'hash', 'other-tenant')
            cls.admin_headers = {'Authorization': 'Bearer ' + auth.create_token(
                cls.tenant, 'scope@example.test', user_name='Admin', user_role='company_admin')}
            cls.other_headers = {'Authorization': 'Bearer ' + auth.create_token(
                cls.other, 'other-scope@example.test', user_name='Other', user_role='company_admin')}
            # One employee carrying every permission so routes reach the
            # scope checks instead of failing on the permission gate.
            cls.emp_id = db.create_user(cls.tenant, 'Scoped Employee', 'emp@scope.test',
                                        'hash', role='employee')
            for key in db.PERMISSION_KEYS:
                db.set_user_permission(cls.emp_id, key, True)
            cls.emp_headers = {'Authorization': 'Bearer ' + auth.create_token(
                cls.tenant, 'emp@scope.test', user_id=cls.emp_id,
                user_name='Scoped Employee', user_role='employee')}
            cls.draft_a = db.save_project_draft(
                cls.tenant, 'owner', {'project_name': 'مشروع مسموح'},
                {'basic': 'draft'}, 'draft', draft_id='draft-a')
            cls.draft_b = db.save_project_draft(
                cls.tenant, 'owner', {'project_name': 'مشروع ممنوع',
                                      'financial_study_model': {'capex': 10},
                                      'team_selection': {'lead': 'x'}},
                {'basic': 'draft'}, 'draft', draft_id='draft-b')
            cls.pres_b = db.create_presentation(
                cls.tenant, 'Pres B', project_data={'project_name': 'مشروع ممنوع',
                                                    'financial_study_model': {'capex': 10}},
                slides_data=[{'html': '<div class="slide">B</div>'}], draft_id=cls.draft_b)
            db.set_user_project_scope(cls.tenant, cls.emp_id, [cls.draft_a])

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.close_db()
        for item in reversed(cls.patches):
            item.stop()
        db.DB_PATH = cls.original_db_path
        cls.temp.cleanup()

    def setUp(self):
        self.client = self.app.test_client()


class ProjectScopeTests(ScopeTestBase):
    """ISS-014: scoped employees stay inside their drafts on every surface."""

    def test_out_of_scope_presentation_routes_answer_404(self):
        base = f'/api/presentations/{self.pres_b}'
        routes = [base, base + '/versions', base + '/edit-log', base + '/approval-status']
        for route in routes:
            self.assertEqual(self.client.get(route, headers=self.emp_headers).status_code, 404, route)
        self.assertEqual(self.client.put(base, headers=self.emp_headers,
                                         json={'title': 'x', 'expectedRevision': 0}).status_code, 404)
        for route in (base + '/archive', base + '/restore', base + '/request-approval'):
            self.assertEqual(self.client.post(route, headers=self.emp_headers, json={}).status_code, 404, route)
        # The in-scope admin is unaffected.
        self.assertEqual(self.client.get(base, headers=self.admin_headers).status_code, 200)

    def test_out_of_scope_draft_routes_answer_404(self):
        self.assertEqual(self.client.get(f'/api/project-draft/{self.draft_b}',
                                         headers=self.emp_headers).status_code, 404)
        self.assertEqual(self.client.post(f'/api/project-draft/{self.draft_b}/restore',
                                          headers=self.emp_headers, json={'presentationId': 'x'}).status_code, 404)
        self.assertEqual(self.client.get(f'/api/project-draft/{self.draft_b}/lifecycle',
                                         headers=self.emp_headers).status_code, 404)
        # Writing the other draft by naming its id is refused the same way.
        response = self.client.post('/api/project-draft', headers=self.emp_headers, json={
            'draftData': {'draftId': self.draft_b, 'project_name': 'تجاوز'}})
        self.assertEqual(response.status_code, 404)

    def test_project_file_and_lists_respect_scope(self):
        with self.app.app_context():
            file_id = db.create_project_file(self.tenant, 'brief', 'b.pdf', 'x.pdf',
                                             'application/pdf', 1, 'sha', draft_id=self.draft_b)
        self.assertEqual(self.client.get(f'/api/project-files/{file_id}',
                                         headers=self.emp_headers).status_code, 404)
        drafts = self.client.get('/api/project-drafts', headers=self.emp_headers).get_json()['drafts']
        self.assertEqual({d['id'] for d in drafts}, {self.draft_a})
        self.assertEqual(self.client.post('/api/downloads', headers=self.emp_headers,
                                          json={'draftId': self.draft_b, 'fileName': 'x.pdf'}).status_code, 404)


class HiddenSectionTests(ScopeTestBase):
    """ISS-015: hidden sections never reach the client and cannot be written."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.app.app_context():
            db.set_user_field_section(cls.emp_id, 'section-financial-calc', False)
            db.set_user_field_section(cls.emp_id, 'section-team', False)

    def test_draft_response_drops_hidden_blobs(self):
        # The employee's own draft, with hidden-section content planted by admin.
        with self.app.app_context():
            draft_id = db.save_project_draft(
                self.tenant, self.emp_id,
                {'project_name': 'ملفي', 'financial_study_model': {'capex': 5},
                 'team_selection': {'a': 1}, 'timeline_table_data': {'rows': []}},
                {'basic': 'draft'}, 'draft')
        response = self.client.get(f'/api/project-draft/{draft_id}', headers=self.emp_headers)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()['draft']['draft_data']
        self.assertNotIn('financial_study_model', data)
        self.assertNotIn('team_selection', data)
        self.assertIn('timeline_table_data', data)  # still allowed
        self.assertEqual(data['project_name'], 'ملفي')

    def test_hidden_write_rejected_and_omission_preserves(self):
        with self.app.app_context():
            draft_id = db.save_project_draft(
                self.tenant, self.emp_id,
                {'project_name': 'ملفي', 'financial_study_model': {'capex': 5}},
                {'basic': 'draft'}, 'draft')
        # Writing hidden content is refused.
        response = self.client.post('/api/project-draft', headers=self.emp_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'ملفي',
                          'financial_study_model': {'capex': 999}}})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_code'], 'SECTION_FORBIDDEN')
        # Omitting the hidden key restores the stored value instead of wiping it.
        response = self.client.post('/api/project-draft', headers=self.emp_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'تعديل مسموح'}})
        self.assertEqual(response.status_code, 200, response.get_json())
        with self.app.app_context():
            stored = db.get_project_draft_by_id(self.tenant, draft_id)['draft_data']
        self.assertEqual(stored['financial_study_model'], {'capex': 5})
        self.assertEqual(stored['project_name'], 'تعديل مسموح')

    def test_hidden_section_status_and_version_routes(self):
        with self.app.app_context():
            draft_id = db.save_project_draft(
                self.tenant, self.emp_id, {'project_name': 'ملفي'}, {'basic': 'draft'}, 'draft')
        response = self.client.post('/api/project-draft/section-status', headers=self.emp_headers,
                                    json={'draftId': draft_id, 'sectionKey': 'section-financial-calc',
                                          'sectionStatus': 'approved'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/project-draft/section-version', headers=self.emp_headers,
                                    json={'draftId': draft_id, 'sectionKey': 'section-financial-calc'})
        self.assertEqual(response.status_code, 403)

    def test_presentation_project_data_drops_hidden_keys(self):
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'Scoped Pres',
                project_data={'project_name': 'مسموح', 'financial_study_model': {'capex': 1},
                              'draftId': self.draft_a},
                slides_data=[{'html': '<div class="slide">A</div>'}], draft_id=self.draft_a)
        response = self.client.get(f'/api/presentations/{pres_id}', headers=self.emp_headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('financial_study_model', response.get_json()['presentation']['projectData'])


class BodyChunkTests(ScopeTestBase):
    """ISS-016: chunks live in the caller's own tenant/user namespace."""

    def _upload_chunk(self, headers, upload_id, payload=b'{"x":1}', idx=0, total=1):
        return self.client.post('/api/body-chunk', headers=headers, json={
            'id': upload_id, 'idx': idx, 'total': total,
            'data': base64.b64encode(payload).decode()})

    def test_chunk_dir_is_namespaced_per_tenant_and_user(self):
        upload_id = 'test-upload-1'
        response = self._upload_chunk(self.emp_headers, upload_id)
        self.assertEqual(response.status_code, 200)
        root = Path(self.module.UPLOADS_DIR) / '.body_chunks'
        self.assertTrue((root / self.tenant / f'u{self.emp_id}' / upload_id / '0.part').is_file())

    def test_other_tenant_cannot_consume_the_chunks(self):
        upload_id = 'test-upload-2'
        payload = json.dumps({'draftData': {'project_name': 'مشروع الأجزاء'}}).encode()
        self.assertEqual(self._upload_chunk(self.emp_headers, upload_id, payload).status_code, 200)
        # Same upload id, different tenant session: the reference resolves in
        # the other tenant's namespace and finds nothing.
        response = self.client.post('/api/project-draft', headers=self.other_headers, json={
            '__chunked_body': {'id': upload_id, 'total': 1}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'Missing uploaded body chunks')
        # The original tenant consumes it and the draft save succeeds.
        response = self.client.post('/api/project-draft', headers=self.emp_headers, json={
            '__chunked_body': {'id': upload_id, 'total': 1}})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])

    def test_anonymous_reference_is_refused(self):
        response = self.client.post('/api/project-draft', json={
            '__chunked_body': {'id': 'test-upload-3', 'total': 1}})
        self.assertEqual(response.status_code, 400)


class ExportPolicyTests(ScopeTestBase):
    """ISS-019: export resources stay data-URIs or tenant-owned local files."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pdfmod = __import__('generate_pdf_from_preview')
        import exports.pptx_export as pptx_module
        cls.base_patch = patch.object(cls.pdfmod, 'BASE_DIR', Path(cls.temp.name))
        cls.pptx_patch = patch.object(pptx_module, 'BASE_DIR', Path(cls.temp.name))
        cls.base_patch.start()
        cls.pptx_patch.start()
        cls.tenant_dir = Path(cls.temp.name) / 'uploads' / cls.tenant
        cls.tenant_dir.mkdir(parents=True, exist_ok=True)
        (cls.tenant_dir / 'ok.png').write_bytes(b'png-bytes')
        cls.other_dir = Path(cls.temp.name) / 'uploads' / cls.other
        cls.other_dir.mkdir(parents=True, exist_ok=True)
        (cls.other_dir / 'secret.png').write_bytes(b'secret')
        (cls.other_dir / 'logo.png').write_bytes(b'secret-logo')

    @classmethod
    def tearDownClass(cls):
        cls.base_patch.stop()
        cls.pptx_patch.stop()
        super().tearDownClass()

    def _p(self, path):
        return self.pdfmod._export_url_to_local_path(path)

    def test_url_policy(self):
        ok = self.pdfmod._export_url_allowed
        self.assertTrue(ok(f'/uploads/{self.tenant}/ok.png', self.tenant))
        self.assertTrue(ok('data:image/png;base64,AAA=', self.tenant))
        self.assertTrue(ok('https://fonts.googleapis.com/css2?family=X', self.tenant))
        self.assertFalse(ok(f'/uploads/{self.other}/secret.png', self.tenant))
        self.assertFalse(ok('file:///etc/passwd', self.tenant))
        self.assertFalse(ok('https://example.com/x.png', self.tenant))
        self.assertFalse(ok('http://169.254.169.254/latest', self.tenant))
        self.assertFalse(ok('//internal.host/x.png', self.tenant))
        self.assertFalse(ok('javascript:alert(1)', self.tenant))
        self.assertFalse(ok('../outside.png', self.tenant))

    def test_html_sanitizer_strips_hostile_urls(self):
        html = (
            '<div class="slide">'
            f'<img src="/uploads/{self.tenant}/ok.png">'
            '<img src="file:///etc/passwd">'
            '<img src="https://evil.internal/x.png">'
            '<style>@import "https://fonts.googleapis.com/css2?family=X";'
            'a{background:url(file:///etc/shadow)}</style></div>')
        out = self.pdfmod._sanitize_export_resource_urls(html, self.tenant)
        self.assertIn(f'/uploads/{self.tenant}/ok.png', out)
        self.assertIn('fonts.googleapis.com', out)
        self.assertNotIn('file:///etc/passwd', out)
        self.assertNotIn('evil.internal', out)
        self.assertNotIn('file:///etc/shadow', out)

    def test_pptx_image_bytes_policy(self):
        from exports.pptx_export import _resolve_image_bytes
        self.assertEqual(_resolve_image_bytes(f'/uploads/{self.tenant}/ok.png', self.tenant), b'png-bytes')
        self.assertEqual(_resolve_image_bytes('data:image/png;base64,' + base64.b64encode(b'x').decode()), b'x')
        self.assertIsNone(_resolve_image_bytes(f'/uploads/{self.other}/secret.png', self.tenant))
        self.assertIsNone(_resolve_image_bytes('file:///etc/passwd', self.tenant))
        self.assertIsNone(_resolve_image_bytes('https://example.com/x.png', self.tenant))
        self.assertIsNone(_resolve_image_bytes(f'tenant-assets/{self.other}/logo', self.tenant))


class ImageReferenceTests(ScopeTestBase):
    """ISS-020: a generation reference must be the caller's own upload."""

    def test_tenant_owned_upload_and_data_uri(self):
        folder = Path(self.module.UPLOADS_DIR) / self.tenant
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'ref.png').write_bytes(b'\x89PNG')
        ref = f'/uploads/{self.tenant}/ref.png'
        prepared = self.module._prepare_image_reference_for_model(ref, self.tenant)
        self.assertTrue(prepared.startswith('data:image/png;base64,'))
        data_uri = 'data:image/png;base64,' + base64.b64encode(b'x').decode()
        self.assertEqual(self.module._prepare_image_reference_for_model(data_uri, self.tenant), data_uri)

    def test_cross_tenant_and_remote_references_refused(self):
        folder = Path(self.module.UPLOADS_DIR) / self.other
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'secret.png').write_bytes(b'\x89PNG')
        for ref in (f'/uploads/{self.other}/secret.png',
                    'https://example.com/x.png',
                    'file:///etc/passwd',
                    'uploads/../secret.png',
                    'not-a-path'):
            self.assertIsNone(
                self.module._prepare_image_reference_for_model(ref, self.tenant), ref)

    def test_project_file_reference_requires_owning_tenant(self):
        with self.app.app_context():
            file_id = db.create_project_file(self.other, 'brief', 'b.png', 'x.png',
                                             'image/png', 1, 'sha')
            self.assertIsNone(self.module._visual_concept_project_file_data_uri(file_id, self.tenant))


if __name__ == '__main__':
    unittest.main()
