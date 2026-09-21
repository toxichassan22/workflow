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


class SectionStatusSaveTests(ScopeTestBase):
    """ISS-023: a plain save cannot mint approvals outside the gated route."""

    def test_save_cannot_approve_location_without_the_map_gate(self):
        with self.app.app_context():
            draft_id = db.save_project_draft(
                self.tenant, f'tenant-admin:{self.tenant}', {'project_name': 'حالة'},
                {'basic': 'draft'}, 'draft', draft_id='status-draft-1')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'حالة'},
            'sectionStatuses': {'location': 'approved', 'basic': 'approved'}})
        self.assertEqual(response.status_code, 200, response.get_json())
        with self.app.app_context():
            stored = db.get_project_draft_by_id(self.tenant, draft_id)['section_statuses']
        # No approved maps exist, so the workflow gate keeps location at draft —
        # while a section with no version snapshots may toggle exactly the way
        # the dedicated route already allows.
        self.assertNotEqual(stored.get('location'), 'approved')
        self.assertEqual(stored.get('basic'), 'approved')

    def test_dropped_and_demoted_statuses_behave(self):
        with self.app.app_context():
            draft_id = db.save_project_draft(
                self.tenant, f'tenant-admin:{self.tenant}', {'project_name': 'حالة'},
                {'basic': 'approved', 'contact': 'approved'}, 'draft', draft_id='status-draft-2')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'حالة'},
            'sectionStatuses': {'basic': 'draft'}})
        self.assertEqual(response.status_code, 200, response.get_json())
        with self.app.app_context():
            stored = db.get_project_draft_by_id(self.tenant, draft_id)['section_statuses']
        self.assertEqual(stored.get('basic'), 'draft')       # demotion allowed
        self.assertEqual(stored.get('contact'), 'approved')  # dropped key restored


class SharedDraftSaveTests(ScopeTestBase):
    """ISS-029: an in-scope shared draft saves instead of key-colliding."""

    def test_in_scope_employee_save_lands_on_the_owner_row(self):
        response = self.client.post('/api/project-draft', headers=self.emp_headers, json={
            'draftData': {'draftId': self.draft_a, 'project_name': 'تعديل تعاوني'}})
        self.assertEqual(response.status_code, 200, response.get_json())
        with self.app.app_context():
            stored = db.get_project_draft_by_id(self.tenant, self.draft_a)
        self.assertEqual(stored['draft_data']['project_name'], 'تعديل تعاوني')
        self.assertEqual(stored['user_id'], 'owner')


class SignedMediaUrlTests(ScopeTestBase):
    """ISS-022: uploads media serves only an expiring signature or the owner."""

    def _creative(self, tenant, name='pub.png', data=b'img-bytes'):
        folder = Path(self.module.UPLOADS_DIR) / 'creative' / tenant
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
        return f'/uploads/creative/{tenant}/{name}'

    def _map(self, tenant, name='map-x.png'):
        maps = Path(self.module.UPLOADS_DIR) / 'maps'
        maps.mkdir(parents=True, exist_ok=True)
        (maps / name).write_bytes(b'map-bytes')
        with self.app.app_context():
            db.add_map_image(tenant, 'overview', f'uploads/maps/{name}', 'ph')
        return f'/uploads/maps/{name}'

    def _sig(self, path):
        return self.module._media_url_serializer().dumps({'p': path})

    def test_unsigned_media_requests_are_refused(self):
        creative = self._creative(self.tenant)
        maps = self._map(self.tenant)
        for url in (creative, maps, '/uploads/maps/map-x.png'):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_valid_signature_serves_and_wrong_or_foreign_sig_fails(self):
        creative = self._creative(self.tenant)
        self.assertEqual(self.client.get(creative + '?s=' + self._sig(creative)).status_code, 200)
        self.assertEqual(self.client.get(creative + '?s=forged').status_code, 404)
        self.assertEqual(self.client.get(
            creative + '?s=' + self._sig('/uploads/creative/' + self.tenant + '/other.png')
        ).status_code, 404)

    def test_bearer_session_serves_only_owning_tenant(self):
        creative = self._creative(self.tenant)
        self.assertEqual(self.client.get(creative, headers=self.admin_headers).status_code, 200)
        self.assertEqual(self.client.get(creative, headers=self.other_headers).status_code, 404)

    def test_json_responses_sign_owned_urls_only(self):
        with self.app.app_context():
            draft_id = db.save_project_draft(
                self.tenant, 'owner',
                {'project_name': 'توقيع', 'cover': self._creative(self.tenant, 'signed.png'),
                 'foreign': self._creative(self.other, 'foreign.png'),
                 'map': self._map(self.tenant, 'owned-map.png'),
                 'unowned': self._map(self.other, 'foreign-map.png')},
                {'basic': 'draft'}, 'draft')
        response = self.client.get(f'/api/project-draft/{draft_id}', headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()['draft']['draft_data']
        self.assertIn('?s=', data['cover'])
        self.assertIn('?s=', data['map'])
        self.assertNotIn('?s=', data['foreign'])
        self.assertNotIn('?s=', data['unowned'])
        # The signed URL actually serves the file.
        self.assertEqual(self.client.get(data['cover']).status_code, 200)
        self.assertEqual(self.client.get(data['map']).status_code, 200)


class GenerationGateTests(ScopeTestBase):
    """ISS-024: draft-scoped generation requires a live approved gate whose
    snapshot matches both the stored draft and the inputs actually sent."""

    SLIDE_PLAN = {'slides': [{'title': 'غلاف', 'type': 'cover'}]}

    def _draft(self, draft_id, data=None, statuses=None):
        payload = {'project_name': 'مشروع البوابة'}
        payload.update(data or {})
        with self.app.app_context():
            return db.save_project_draft(
                self.tenant, 'owner', payload,
                statuses or {'basic': 'approved'}, 'draft', draft_id=draft_id)

    def _approve(self, draft_id):
        with self.app.app_context():
            draft = db.get_project_draft_by_id(self.tenant, draft_id)
            snapshot = {'draft_hash': db.draft_generation_input_hash(draft['draft_data'] or {})}
            approval = db.create_generation_approval(
                self.tenant, draft_id,
                {'estimated_points': 0, 'estimated_cost_usd': 0, 'slides_count': 1},
                'owner', 'Owner', input_snapshot=snapshot)
            self.assertNotIn('error', approval, approval)
            decided = db.decide_generation_approval(
                self.tenant, approval['id'], 'approved', 'owner', 'Owner', allow_self=True)
            self.assertNotIn('error', decided, decided)
            return approval['id']

    def _generate(self, project_data, headers=None):
        with patch.object(self.module.slide_engine, 'generate_single_slide',
                          return_value='<div class="slide">ok</div>'), \
                patch.object(db, 'get_branding', return_value={'company_name': 'x'}):
            return self.client.post('/api/generate-slide-single',
                                    headers=headers or self.admin_headers,
                                    json={'projectData': project_data,
                                          'slidePlan': self.SLIDE_PLAN,
                                          'slideIndex': 0})

    def test_declared_draft_without_approval_is_refused(self):
        draft_id = self._draft('gate-none')
        response = self._generate({'draftId': draft_id, 'project_name': 'مشروع البوابة'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json().get('error_code'), 'generation_not_approved')

    def test_draftless_generation_is_untouched(self):
        response = self._generate({'project_name': 'بلا مسودة'})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_approved_inputs_generate(self):
        draft_id = self._draft('gate-ok')
        self._approve(draft_id)
        response = self._generate({'draftId': draft_id, 'project_name': 'مشروع البوابة'})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_sent_inputs_must_match_the_approved_draft(self):
        draft_id = self._draft('gate-tamper', {'land_area': '500'})
        self._approve(draft_id)
        response = self._generate({'draftId': draft_id, 'project_name': 'مشروع البوابة',
                                   'land_area': '999'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json().get('error_code'), 'inputs_changed')
        response = self._generate({'draftId': draft_id, 'project_name': 'مشروع البوابة',
                                   'land_area': '500', 'injected': 'x'})
        self.assertEqual(response.status_code, 409)
        response = self._generate({'draftId': draft_id, 'project_name': 'مشروع البوابة',
                                   'land_area': '500'})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_draft_drift_after_approval_is_refused(self):
        draft_id = self._draft('gate-drift', {'land_area': '500'})
        self._approve(draft_id)
        with self.app.app_context():
            db.save_project_draft(
                self.tenant, 'owner',
                {'project_name': 'مشروع البوابة', 'land_area': '777'},
                {'basic': 'approved'}, 'generating', draft_id=draft_id,
                allow_generating=True)
        response = self._generate({'draftId': draft_id, 'project_name': 'مشروع البوابة',
                                   'land_area': '777'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json().get('error_code'), 'inputs_changed')

    def test_slimmed_financial_and_photos_still_match(self):
        model = {'inputs': {'projectCost': 1000}}
        photos = [{'id': 'p1', 'imageUrl': '/uploads/creative/t/1.png',
                   'originalName': 'a.png', 'description': 'd', 'extra': 'keep'}]
        draft_id = self._draft('gate-slim', {'financial_study_model': model,
                                             'land_photos_file_meta': photos})
        self._approve(draft_id)
        response = self._generate({
            'draftId': draft_id, 'project_name': 'مشروع البوابة',
            'financial_study_model': {'inputs': {'projectCost': 1000}, 'report': {'parts': []}},
            'land_photos_file_meta': [{'id': 'p1', 'imageUrl': '/uploads/creative/t/1.png',
                                       'originalName': 'a.png', 'description': 'd'}]})
        self.assertEqual(response.status_code, 200, response.get_json())

    def _queue_slide(self, project_data):
        with patch.object(self.module.threading.Thread, 'start'), \
                patch.object(self.module, '_write_job'):
            return self.client.post('/api/generate-slide-single-job', headers=self.admin_headers,
                                    json={'projectData': project_data,
                                          'slidePlan': self.SLIDE_PLAN, 'slideIndex': 0})

    def test_resigned_media_matches_on_both_generation_routes(self):
        url = f'/uploads/creative/{self.tenant}/cover.png'
        draft_id = self._draft('gate-resigned', {
            'cover': url,
            'visual_concept': {'slots': [{'approvedImageUrl': url}]},
            'land_photos_file_meta': [{'id': 'p1', 'imageUrl': url}]})
        self._approve(draft_id)
        response = self.client.get(f'/api/project-draft/{draft_id}', headers=self.admin_headers)
        live = response.get_json()['draft']['draft_data']
        self.assertIn('?s=', live['cover'])
        for generate, status in ((self._generate, 200), (self._queue_slide, 202)):
            with self.subTest(route=generate.__name__):
                response = generate(live)
                self.assertEqual(response.status_code, status, response.get_json())

    def test_checkpoint_with_rotated_media_preserves_approval(self):
        url = f'/uploads/creative/{self.tenant}/checkpoint.png'
        draft_id = self._draft('gate-checkpoint', {'cover': url + '?s=old&t=1'})
        self._approve(draft_id)
        live = {'draftId': draft_id, 'project_name': 'مشروع البوابة',
                'cover': url + '?cb=2&s=new&v=3',
                'tenantSlidesData': [{'html': '<div class="slide">ok</div>'}],
                'tenantSlidePlan': self.SLIDE_PLAN,
                'slide_generation_checkpoint': {'completed': [0]}}
        response = self.client.post('/api/project-draft', headers=self.admin_headers,
                                    json={'draftData': live, 'slideCheckpoint': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        response = self._queue_slide(live)
        self.assertEqual(response.status_code, 202, response.get_json())

    def test_media_identity_changes_are_still_refused(self):
        url = f'/uploads/creative/{self.tenant}/cover.png'
        draft_id = self._draft('gate-media-swap', {'cover': url + '?fileId=one&s=old'})
        self._approve(draft_id)
        for changed in (url.replace('cover.png', 'other.png') + '?fileId=one&s=new',
                        url + '?fileId=two&s=new',
                        url.replace(self.tenant, self.other) + '?fileId=one&s=new'):
            with self.subTest(url=changed):
                response = self._queue_slide({'draftId': draft_id, 'cover': changed})
                self.assertEqual(response.status_code, 409, response.get_json())
                self.assertEqual(response.get_json()['error_code'], 'inputs_changed')

    def test_generation_hash_normalizes_only_local_media_fetch_parameters(self):
        url = f'/uploads/creative/{self.tenant}/cover.png'
        original = {'nested': [{'url': url + '?fileId=one#crop'}],
                    'markup': '<img src="' + url + '?fileId=one">'}
        rotated = {'nested': [{'url': url + '?s=new&fileId=one&cb=2#crop'}],
                   'markup': '<img src="' + url + '?s=new&amp;fileId=one&amp;t=2">'}
        self.assertEqual(db.draft_generation_input_hash(original),
                         db.draft_generation_input_hash(rotated))
        for before, after in ((url + '?fileId=one', url + '?fileId=two'),
                              (url + '#one', url + '#two'),
                              ('https://example.test' + url + '?s=one',
                               'https://example.test' + url + '?s=two'),
                              ('https://example.test/?ref=' + url + '?s=one',
                               'https://example.test/?ref=' + url + '?s=two'),
                              ('//example.test/?ref=' + url + '?s=one',
                               '//example.test/?ref=' + url + '?s=two'),
                              ('budget?s=one', 'budget?s=two')):
            with self.subTest(before=before):
                self.assertNotEqual(db.draft_generation_input_hash({'value': before}),
                                    db.draft_generation_input_hash({'value': after}))

    def test_scoped_employee_cannot_generate_on_a_foreign_draft(self):
        draft_id = self._draft('gate-scope', {'project_name': 'مشروع ممنوع'})
        self._approve(draft_id)
        response = self._generate({'draftId': draft_id, 'project_name': 'مشروع ممنوع'},
                                  headers=self.emp_headers)
        self.assertEqual(response.status_code, 404)


class GenerationSettlementTests(ScopeTestBase):
    """ISS-042: settle/finish verify the run against server state — an
    unverified job label cannot consume or release the escrow, and a failed
    settlement can never be reported as success."""

    def _approved_run(self, draft_id, job_status='queued'):
        with self.app.app_context():
            db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع التسوية'},
                {'basic': 'approved'}, 'draft', draft_id=draft_id)
            approval = db.create_generation_approval(
                self.tenant, draft_id,
                {'estimated_points': 0, 'estimated_cost_usd': 0, 'slides_count': 1},
                'owner', 'Owner')
            self.assertNotIn('error', approval, approval)
            decided = db.decide_generation_approval(
                self.tenant, approval['id'], 'approved', 'owner', 'Owner', allow_self=True)
            self.assertNotIn('error', decided, decided)
            job = db.create_generation_job(
                self.tenant, approval_id=approval['id'], draft_id=draft_id)
            if job_status != 'queued':
                job = db.update_generation_job(job['id'], status=job_status)
            return approval['id'], job['id']

    def _settle(self, approval_id, payload):
        return self.client.post(
            f'/api/generation-approvals/{approval_id}/settle',
            headers=self.admin_headers, json=payload)

    def test_consume_claim_needs_a_completed_job(self):
        approval_id, job_id = self._approved_run('settle-live', job_status='running')
        response = self._settle(approval_id, {'jobId': job_id, 'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_not_completed')

    def test_release_claim_needs_a_finished_job(self):
        approval_id, job_id = self._approved_run('settle-rel', job_status='running')
        response = self._settle(approval_id, {'jobId': job_id, 'consumed': False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_still_running')

    def test_settle_rejects_a_job_from_another_approval(self):
        approval_id, _job = self._approved_run('settle-a')
        other_approval, other_job = self._approved_run('settle-b')
        response = self._settle(approval_id, {'jobId': other_job, 'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_mismatch')
        response = self._settle(approval_id, {'jobId': 'ghost-job', 'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_mismatch')

    def test_settle_without_job_id_is_refused_when_a_run_exists(self):
        approval_id, _job = self._approved_run('settle-noname')
        response = self._settle(approval_id, {'consumed': True})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'job_required')

    def test_settle_consumes_once_the_job_is_completed(self):
        approval_id, job_id = self._approved_run('settle-ok', job_status='completed')
        response = self._settle(approval_id, {'jobId': job_id, 'consumed': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['result']['status'], 'consumed')

    def test_finish_reports_settlement_failure_instead_of_success(self):
        approval_id, job_id = self._approved_run('finish-fail')
        with self.app.app_context():
            # Consume the approval first so the finish-time settle must fail.
            db.update_generation_job(job_id, status='running')
            settled = db.settle_generation_approval(
                self.tenant, approval_id, job_id, consumed=True)
            self.assertEqual(settled.get('status'), 'consumed')
        # The job is still 'running' server-side; finishing it now hits a
        # settle that can no longer pass — the route must surface that.
        response = self.client.post(
            f'/api/generation-jobs/{job_id}/finish',
            headers=self.admin_headers, json={'status': 'completed'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['error_code'], 'settlement_failed')
        self.assertFalse(response.get_json()['success'])


class WorkflowClaimTests(ScopeTestBase):
    """ISS-025: client-sent unlock booleans cannot mint workflow state — every
    approval the routes honor must exist as a stored server artifact."""

    def _draft(self, draft_id, data=None, status='draft', statuses=None):
        with self.app.app_context():
            saved = db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع الأعلام', **(data or {})},
                statuses or {'basic': 'draft'}, 'draft', draft_id=draft_id)
            if status != 'draft':
                db.get_db().execute(
                    'UPDATE project_drafts SET status = ? WHERE id = ?', (status, saved))
                db.get_db().commit()
            return saved

    def _stored_draft_data(self, draft_id):
        with self.app.app_context():
            return (db.get_project_draft_by_id(self.tenant, draft_id) or {}).get('draft_data') or {}

    def _approve_generation(self, draft_id):
        with self.app.app_context():
            draft = db.get_project_draft_by_id(self.tenant, draft_id)
            snapshot = {'draft_hash': db.draft_generation_input_hash(draft['draft_data'] or {})}
            approval = db.create_generation_approval(
                self.tenant, draft_id,
                {'estimated_points': 0, 'estimated_cost_usd': 0, 'slides_count': 1},
                'owner', 'Owner', input_snapshot=snapshot)
            self.assertNotIn('error', approval, approval)
            decided = db.decide_generation_approval(
                self.tenant, approval['id'], 'approved', 'owner', 'Owner', allow_self=True)
            self.assertNotIn('error', decided, decided)
            return approval['id']

    def _generate_map(self, draft_id, map_type='overview', project_extra=None):
        project = {'draftId': draft_id, 'project_name': 'مشروع الأعلام'}
        project.update(project_extra or {})
        with patch.object(self.module.maps_service, 'generate_all_map_images',
                          return_value={'placeholders': {}, 'landmarks': []}), \
                patch.object(db, 'get_branding', return_value={'company_name': 'x'}):
            return self.client.post('/api/generate-map-image', headers=self.admin_headers,
                                    json={'projectData': project, 'mapType': map_type})

    def test_map_gate_reads_approval_from_storage_not_payload(self):
        # The payload claims every approval under the sun; the stored draft has
        # none, so generation is refused at the first gate.
        draft_id = self._draft('wfc-map-claims')
        response = self._generate_map(draft_id, 'overview', {
            'location_analysis_approved': True,
            'locationAnalysisApproved': True,
            'tenantCreativeImages': {'map_approvals': {'overview': True}},
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'LOCATION_ANALYSIS_NOT_APPROVED')

    def test_dependent_maps_need_the_stored_overview_approval(self):
        draft_id = self._draft('wfc-map-overview', {'location_analysis_approved': True})
        for map_type in ('landmarks', 'access', 'catchment'):
            response = self._generate_map(draft_id, map_type)
            self.assertEqual(response.status_code, 400, map_type)
            self.assertEqual(response.get_json()['error_code'], 'OVERVIEW_MAP_NOT_APPROVED',
                             map_type)

    def test_approved_map_cannot_be_regenerated_by_flagging_it(self):
        draft_id = self._draft('wfc-map-done', {
            'location_analysis_approved': True,
            'tenantCreativeImages': {'map_approvals': {'overview': True}},
        })
        response = self._generate_map(draft_id, 'overview')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'MAP_ALREADY_APPROVED')

    def test_stored_approval_lets_generation_through(self):
        draft_id = self._draft('wfc-map-ok', {'location_analysis_approved': True})
        response = self._generate_map(draft_id, 'overview')
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])

    def test_checkpoint_flag_without_a_live_run_stays_locked(self):
        # The flag claims a running generation; parked at the approval gate the
        # draft has none, so the write is refused instead of unlocking.
        draft_id = self._draft('wfc-gen-locked', status='generation_approval_pending')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'مشروع الأعلام'},
            'slideCheckpoint': True})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_LOCKED')

    def test_checkpoint_flag_passes_with_a_live_approval(self):
        draft_id = self._draft('wfc-gen-live', statuses={'basic': 'approved'})
        self._approve_generation(draft_id)
        with self.app.app_context():
            stored = db.get_project_draft_by_id(self.tenant, draft_id)
            self.assertEqual(db.normalize_proposal_status(stored['status']), 'generating')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'مشروع الأعلام'},
            'slideCheckpoint': True})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_generation_operation_flag_cannot_unlock_a_presentation_save(self):
        # A live run bound to one file must not be used to write a different
        # one: the flag names the run's presentation or it stays locked.
        draft_id = self._draft('wfc-op-flag', status='generating')
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض مقفل', project_data={'project_name': 'مشروع الأعلام'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id=draft_id)
            db.get_db().execute(
                """INSERT INTO generation_approvals
                   (id, tenant_id, draft_id, presentation_id, status, requested_by,
                    decided_at, prior_status)
                   VALUES (?, ?, ?, ?, 'approved', 'owner', ?, 'sections_approved')""",
                ('appr-wfc-op-flag', self.tenant, draft_id, 'pres-other-file',
                 db._utcnow().isoformat()))
            db.get_db().commit()
        response = self.client.put(f'/api/presentations/{pres_id}',
                                   headers=self.admin_headers,
                                   json={'operation': 'generation',
                                         'projectData': {'project_name': 'مشروع الأعلام'},
                                         'expectedRevision': 0})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_LOCKED')

    def test_unbacked_approval_claims_are_stripped_on_save(self):
        draft_id = self._draft('wfc-strip')
        response = self.client.post('/api/project-draft', headers=self.admin_headers, json={
            'draftData': {'draftId': draft_id, 'project_name': 'مشروع الأعلام',
                          'location_analysis_approved': True,
                          'tenantCreativeImages': {'map_approvals': {'overview': True}}}})
        self.assertEqual(response.status_code, 200, response.get_json())
        stored = self._stored_draft_data(draft_id)
        self.assertNotIn(stored.get('location_analysis_approved'), (True, 'true', 1))
        approvals = (stored.get('tenantCreativeImages') or {}).get('map_approvals') or {}
        self.assertNotEqual(approvals.get('overview'), True)


class VersionRestoreGateTests(ScopeTestBase):
    """ISS-026: restoring a version rewrites the file, so every edit gate that
    guards a PUT guards the restore as well."""

    def _draft(self, draft_id, status='draft'):
        with self.app.app_context():
            saved = db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع الاستعادة'},
                {'basic': 'draft'}, 'draft', draft_id=draft_id)
            if status != 'draft':
                db.get_db().execute(
                    'UPDATE project_drafts SET status = ? WHERE id = ?', (status, saved))
                db.get_db().commit()
            return saved

    def _presentation(self, draft_id=None, status='draft'):
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض الاستعادة', project_data={'project_name': 'مشروع الاستعادة'},
                slides_data=[{'html': '<div class="slide">v1</div>'}], draft_id=draft_id)
            with self.app.test_request_context():
                from flask import g as flask_g
                flask_g.tenant_id = self.tenant
                version_id = self.module._commit_presentation_state(
                    self.tenant, pres_id, action='حالة ابتدائية', source='system')['version_id']
            if status != 'draft':
                db.get_db().execute('UPDATE presentations SET status = ? WHERE id = ?',
                                    (status, pres_id))
                db.get_db().commit()
            return pres_id, version_id

    def _restore(self, pres_id, version_id, payload=None, headers=None):
        return self.client.post(
            f'/api/presentations/{pres_id}/versions/{version_id}/restore',
            headers=headers or self.admin_headers, json=payload or {})

    def test_restore_inside_a_locked_draft_is_refused(self):
        draft_id = self._draft('rst-locked', status='generating')
        pres_id, version_id = self._presentation(draft_id=draft_id)
        with self.app.app_context():
            # A fresh approved approval makes the 'generating' state a live run
            # rather than a corpse the lock path would recover.
            db.get_db().execute(
                """INSERT INTO generation_approvals
                   (id, tenant_id, draft_id, status, requested_by, decided_at, prior_status)
                   VALUES (?, ?, ?, 'approved', 'owner', ?, 'sections_approved')""",
                ('appr-rst-locked', self.tenant, draft_id, db._utcnow().isoformat()))
            db.get_db().commit()
        response = self._restore(pres_id, version_id)
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_LOCKED')

    def test_restore_on_an_approved_file_needs_the_permission(self):
        pres_id, version_id = self._presentation(status='approved')
        with self.app.app_context():
            limited_id = db.create_user(self.tenant, 'محرر محدود', 'limited@scope.test',
                                        'hash', role='employee')
            for key in db.PERMISSION_KEYS:
                db.set_user_permission(limited_id, key, True)
            db.set_user_permission(limited_id, 'post_approval_edit', False)
            limited_headers = {'Authorization': 'Bearer ' + auth.create_token(
                self.tenant, 'limited@scope.test', user_id=limited_id,
                user_name='محرر محدود', user_role='employee')}
        response = self._restore(pres_id, version_id,
                                 payload={'editReason': 'سبب'}, headers=limited_headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['error_code'], 'post_approval_edit_required')

    def test_restore_on_an_approved_file_needs_a_reason(self):
        pres_id, version_id = self._presentation(status='approved')
        response = self._restore(pres_id, version_id, payload={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error_code'], 'reason_required')

    def test_restore_on_an_approved_file_with_reason_passes(self):
        pres_id, version_id = self._presentation(status='approved')
        response = self._restore(pres_id, version_id,
                                 payload={'editReason': 'تصحيح قيمة'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])

    def test_restore_on_an_open_file_still_works(self):
        pres_id, version_id = self._presentation()
        response = self._restore(pres_id, version_id)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['success'])


class LegacyApprovalGateTests(ScopeTestBase):
    """ISS-027: the legacy approval table cannot mint a final approval for a
    file inside the formal lifecycle, and where it still governs it enforces
    the gate's invariants — pending state, separation of duties, rejection
    reason and content binding."""

    def _draft(self, draft_id, status='draft'):
        with self.app.app_context():
            saved = db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع الاعتماد'},
                {'basic': 'draft'}, 'draft', draft_id=draft_id)
            if status != 'draft':
                db.get_db().execute(
                    'UPDATE project_drafts SET status = ? WHERE id = ?', (status, saved))
                db.get_db().commit()
            return saved

    def _presentation(self, draft_id=None):
        with self.app.app_context():
            return db.create_presentation(
                self.tenant, 'عرض الاعتماد', project_data={'project_name': 'مشروع الاعتماد'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id=draft_id)

    def _request(self, pres_id, headers=None):
        return self.client.post(f'/api/presentations/{pres_id}/request-approval',
                                headers=headers or self.admin_headers, json={})

    def _review(self, approval_id, status='approved', note=None, headers=None):
        payload = {'status': status}
        if note is not None:
            payload['note'] = note
        return self.client.post(f'/api/approvals/{approval_id}/review',
                                headers=headers or self.admin_headers, json=payload)

    def test_request_on_a_formal_gate_file_is_refused(self):
        draft_id = self._draft('lga-gated', status='generated_draft')
        pres_id = self._presentation(draft_id=draft_id)
        response = self._request(pres_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'use_final_approval_gate')

    def test_request_and_clean_decision_on_a_legacy_file(self):
        pres_id = self._presentation()
        requested = self._request(pres_id)
        self.assertEqual(requested.status_code, 200, requested.get_json())
        approval_id = requested.get_json()['approvalId']
        with self.app.app_context():
            row = db.get_approval(approval_id, self.tenant)
            self.assertEqual(row['status'], 'pending')
            self.assertTrue(row['request_hash'])
        decided = self._review(approval_id, 'approved')
        self.assertEqual(decided.status_code, 200, decided.get_json())
        with self.app.app_context():
            self.assertEqual(db.get_approval(approval_id, self.tenant)['status'], 'approved')
            pres = db.get_presentation(pres_id, tenant_id=self.tenant)
            self.assertEqual(pres['status'], 'approved')
        # A second decision on the settled row is refused, not re-applied.
        again = self._review(approval_id, 'approved')
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.get_json()['error_code'], 'approval_not_pending')

    def test_employee_cannot_self_decide(self):
        pres_id = self._presentation()
        requested = self._request(pres_id, headers=self.emp_headers)
        self.assertEqual(requested.status_code, 200, requested.get_json())
        approval_id = requested.get_json()['approvalId']
        decided = self._review(approval_id, 'approved', headers=self.emp_headers)
        self.assertEqual(decided.status_code, 403)
        self.assertEqual(decided.get_json()['error_code'], 'self_approval_not_allowed')

    def test_rejection_requires_a_written_reason(self):
        pres_id = self._presentation()
        approval_id = self._request(pres_id).get_json()['approvalId']
        decided = self._review(approval_id, 'rejected')
        self.assertEqual(decided.status_code, 400)
        self.assertEqual(decided.get_json()['error_code'], 'note_required')
        decided = self._review(approval_id, 'rejected', note='أعد العنوان')
        self.assertEqual(decided.status_code, 200, decided.get_json())
        with self.app.app_context():
            pres = db.get_presentation(pres_id, tenant_id=self.tenant)
            self.assertEqual(pres['status'], 'draft')

    def test_approval_fails_when_the_content_moved(self):
        pres_id = self._presentation()
        approval_id = self._request(pres_id).get_json()['approvalId']
        with self.app.app_context():
            db.get_db().execute(
                'UPDATE presentations SET project_data = ? WHERE id = ?',
                ('{"project_name": "محتوى مغيّر"}', pres_id))
            db.get_db().commit()
        decided = self._review(approval_id, 'approved')
        self.assertEqual(decided.status_code, 409)
        self.assertEqual(decided.get_json()['error_code'], 'content_changed')
        with self.app.app_context():
            self.assertEqual(db.get_approval(approval_id, self.tenant)['status'], 'pending')

    def test_a_file_that_enters_the_gate_mid_request_leaves_the_legacy_path(self):
        draft_id = self._draft('lga-mid', status='draft')
        pres_id = self._presentation(draft_id=draft_id)
        approval_id = self._request(pres_id).get_json()['approvalId']
        # The draft moved into the formal lifecycle after the request opened.
        self._draft(draft_id, status='generated_draft')
        decided = self._review(approval_id, 'approved')
        self.assertEqual(decided.status_code, 409)
        self.assertEqual(decided.get_json()['error_code'], 'use_final_approval_gate')


class ApprovalRaceTests(ScopeTestBase):
    """ISS-028: the decide UPDATE is the atomic claim — a competing decision
    committed inside the read-write window turns the loser's write into a
    refusal instead of a silent overwrite."""

    def _draft(self, draft_id, statuses=None):
        with self.app.app_context():
            return db.save_project_draft(
                self.tenant, 'owner', {'project_name': 'مشروع السباق'},
                statuses or {'basic': 'approved'}, 'draft', draft_id=draft_id)

    def _generation_approval(self, draft_id):
        with self.app.app_context():
            draft = db.get_project_draft_by_id(self.tenant, draft_id)
            snapshot = {'draft_hash': db.draft_generation_input_hash(draft['draft_data'] or {})}
            approval = db.create_generation_approval(
                self.tenant, draft_id,
                {'estimated_points': 5, 'estimated_cost_usd': 1, 'slides_count': 1},
                'owner', 'Owner', input_snapshot=snapshot)
            self.assertNotIn('error', approval, approval)
            return approval['id']

    def _final_approval(self, draft_id):
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض السباق', project_data={'project_name': 'مشروع السباق'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id=draft_id)
            result = db.request_final_file_approval(
                self.tenant, pres_id, revision=1, requested_by='owner', requested_by_name='Owner')
            self.assertNotIn('error', result, result)
            return result['id']

    def test_generation_decision_loses_the_race_atomically(self):
        draft_id = self._draft('race-gen')
        approval_id = self._generation_approval(draft_id)
        real_release = db.release_stale_reservations

        def competitor_wins(tenant_id):
            # A competing reviewer decided inside this decision's read-write
            # window: the row is no longer pending by the time ours writes.
            conn = db.get_db()
            conn.execute(
                "UPDATE generation_approvals SET status = 'rejected', "
                "decided_by = 'rival', decided_at = datetime('now') WHERE id = ?",
                (approval_id,))
            conn.commit()
            return real_release(tenant_id)

        with self.app.app_context(), \
                patch.object(db, 'release_stale_reservations', side_effect=competitor_wins):
            result = db.decide_generation_approval(
                self.tenant, approval_id, 'approved', 'owner', 'Owner', allow_self=True)
        self.assertEqual(result.get('error'), 'approval_not_pending')
        with self.app.app_context():
            row = db.get_db().execute(
                'SELECT * FROM generation_approvals WHERE id = ?', (approval_id,)).fetchone()
            # The winning decision stands — no overwrite, no reservation.
            self.assertEqual(row['status'], 'rejected')
            self.assertEqual(row['decided_by'], 'rival')
            holds = db.get_db().execute(
                "SELECT COUNT(*) AS n FROM point_reservations WHERE generation_approval_id = ?",
                (approval_id,)).fetchone()
            self.assertEqual(holds['n'], 0)

    def test_final_file_decision_loses_the_race_atomically(self):
        draft_id = self._draft('race-final', statuses={'basic': 'approved'})
        with self.app.app_context():
            db.get_db().execute(
                "UPDATE project_drafts SET status = 'generated_draft' WHERE id = ?",
                (draft_id,))
            db.get_db().commit()
            approval_id = self._final_approval(draft_id)
        real_get = db.get_project_draft_by_id

        def competitor_wins(tenant_id, did):
            conn = db.get_db()
            conn.execute(
                "UPDATE final_file_approvals SET status = 'approved', "
                "decided_by = 'rival', decided_at = datetime('now') WHERE id = ?",
                (approval_id,))
            conn.commit()
            return real_get(tenant_id, did)

        with self.app.app_context(), \
                patch.object(db, 'get_project_draft_by_id', side_effect=competitor_wins):
            result = db.decide_final_file_approval(
                self.tenant, approval_id, 'rejected', 'owner', 'Owner',
                note='سبب', allow_self=True)
        self.assertEqual(result.get('error'), 'approval_not_pending')
        with self.app.app_context():
            row = db.get_db().execute(
                'SELECT * FROM final_file_approvals WHERE id = ?', (approval_id,)).fetchone()
            self.assertEqual(row['status'], 'approved')
            self.assertEqual(row['decided_by'], 'rival')

    def test_section_version_decision_loses_the_race_atomically(self):
        draft_id = self._draft('race-section', statuses={'basic': 'draft'})
        with self.app.app_context():
            version = db.create_section_version(
                self.tenant, draft_id, 'basic', {'project_name': 'x'},
                created_by='owner', created_by_name='Owner')
            self.assertNotIn('error', version, version)
            version_id = version['id']
        real_days = db.get_section_approval_validity_days

        def competitor_wins(tenant_id):
            conn = db.get_db()
            conn.execute(
                "UPDATE section_versions SET status = 'returned', "
                "decided_by = 'rival', decided_at = datetime('now') WHERE id = ?",
                (version_id,))
            conn.commit()
            return real_days(tenant_id)

        with self.app.app_context(), \
                patch.object(db, 'get_section_approval_validity_days', side_effect=competitor_wins):
            result = db.decide_section_version(
                self.tenant, version_id, 'approved', 'reviewer', 'Reviewer')
        self.assertEqual(result.get('error'), 'version_not_pending')
        with self.app.app_context():
            row = db.get_db().execute(
                'SELECT * FROM section_versions WHERE id = ?', (version_id,)).fetchone()
            self.assertEqual(row['status'], 'returned')
            self.assertEqual(row['decided_by'], 'rival')


class DraftRevisionConflictTests(ScopeTestBase):
    """ISS-030: a save that names its base revision cannot silently overwrite
    a draft that moved meanwhile — the conflict surfaces instead."""

    def _save(self, draft_id, data, expected='omit', statuses=None):
        payload = {'draftData': {'draftId': draft_id, **data}}
        if statuses is not None:
            payload['sectionStatuses'] = statuses
        if expected != 'omit':
            payload['expectedRevision'] = expected
        return self.client.post('/api/project-draft', headers=self.admin_headers, json=payload)

    def _stored(self, draft_id):
        with self.app.app_context():
            return db.get_project_draft_by_id(self.tenant, draft_id)

    def test_save_chain_tracks_the_returned_revision(self):
        response = self._save('rev-draft', {'project_name': 'أول'}, expected=0)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['revision'], 1)
        response = self._save('rev-draft', {'project_name': 'ثان'}, expected=1)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['revision'], 2)
        self.assertEqual(self._stored('rev-draft')['draft_data']['project_name'], 'ثان')

    def test_stale_revision_is_refused_not_overwritten(self):
        self._save('rev-stale', {'project_name': 'أول', 'field_a': 'A'})
        # A second tab moved the row meanwhile.
        self._save('rev-stale', {'project_name': 'أول', 'field_a': 'A2'}, expected=1)
        stale = self._save('rev-stale', {'project_name': 'أول', 'field_b': 'B'}, expected=1)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()['error_code'], 'DRAFT_REVISION_CONFLICT')
        self.assertEqual(stale.get_json()['currentRevision'], 2)
        stored = self._stored('rev-stale')['draft_data']
        self.assertEqual(stored.get('field_a'), 'A2')
        self.assertNotIn('field_b', stored)

    def test_unknown_future_revision_is_refused(self):
        self._save('rev-future', {'project_name': 'أول'})
        response = self._save('rev-future', {'project_name': 'أول'}, expected=9)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'DRAFT_REVISION_CONFLICT')

    def test_legacy_save_without_revision_still_works(self):
        response = self._save('rev-legacy', {'project_name': 'أول'})
        self.assertEqual(response.status_code, 200, response.get_json())
        response = self._save('rev-legacy', {'project_name': 'ثان', 'more': 'x'})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_invalid_expected_revision_is_a_client_error(self):
        response = self._save('rev-bad', {'project_name': 'أول'}, expected='abc')
        self.assertEqual(response.status_code, 400)

    def test_presentation_get_reports_the_linked_draft_revision(self):
        """Opening a presentation must hand the workspace its draft revision —
        otherwise the next expectedRevision save conflicts against a counter
        the client never saw."""
        self._save('rev-linked', {'project_name': 'أول'}, expected=0)
        with self.app.app_context():
            pres_id = db.create_presentation(
                self.tenant, 'عرض مرتبط', project_data={'project_name': 'أول'},
                slides_data=[{'html': '<div class="slide">x</div>'}], draft_id='rev-linked')
        response = self.client.get(f'/api/presentations/{pres_id}', headers=self.admin_headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['presentation'].get('draftRevision'), 1)
        # A second save moves the draft — the next open sees the new counter.
        self._save('rev-linked', {'project_name': 'ثان'}, expected=1)
        response = self.client.get(f'/api/presentations/{pres_id}', headers=self.admin_headers)
        self.assertEqual(response.get_json()['presentation'].get('draftRevision'), 2)

    def test_section_version_restore_returns_the_new_draft_revision(self):
        self._save('rev-restore', {'project_name': 'أول'}, expected=0,
                   statuses={'basic': 'draft'})
        with self.app.app_context():
            version = db.create_section_version(
                self.tenant, 'rev-restore', 'basic', {'project_name': 'أول'},
                created_by='owner', created_by_name='Owner')
            self.assertNotIn('error', version, version)
        response = self.client.post(
            '/api/project-draft/section-version/restore',
            headers=self.admin_headers, json={'versionId': version['id']})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn('revision', response.get_json())
        self.assertEqual(
            response.get_json()['revision'],
            self._stored('rev-restore')['revision'])


class MarketJobIdentityTests(ScopeTestBase):
    """ISS-033: the background market worker must run under the job's tenant
    identity — upload dirs, logo publishing, audit rows and key selection all
    read it from g, and an app context starts empty."""

    def test_worker_stamps_tenant_and_actor_inside_its_context(self):
        from flask import g as flask_g
        captured = {}

        def fake_execute(data, tenant_id=None, progress=None):
            captured['g_tenant'] = getattr(flask_g, 'tenant_id', None)
            captured['g_user'] = getattr(flask_g, 'user_id', None)
            captured['arg_tenant'] = tenant_id
            return {'success': True, 'summary': {}}

        with patch.object(self.module, '_execute_market_summary', side_effect=fake_execute):
            self.module._market_job_worker(
                self.app, self.tenant, 'summary', {'projectData': {}}, 'job0001',
                actor={'user_id': 'u-1', 'user_name': 'Employee', 'user_role': 'employee'})

        self.assertEqual(captured['g_tenant'], self.tenant)
        self.assertEqual(captured['g_user'], 'u-1')
        self.assertEqual(captured['arg_tenant'], self.tenant)


class BillingHoldExclusionTests(ScopeTestBase):
    """ISS-034: usage under a live generation hold is prepaid by the escrow —
    the periodic sweep must not bill it separately and charge the run twice."""

    def _wallet_tenant(self, slug, credit=100.0):
        tenant = db.create_tenant('Wallet ' + slug, slug + '@example.test', 'hash', slug)
        db.record_ledger_credit(tenant, credit, note='topup')
        return tenant

    def test_unbilled_usage_under_a_live_hold_is_not_billed(self):
        with self.app.app_context():
            tenant = self._wallet_tenant('hold-tenant')
            draft_id = db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='hold-draft')
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-1', draft_id=draft_id)
            self.assertNotIn('error', hold, hold)
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 90.0)
            db.record_ai_usage_event(
                tenant, 'model-x', flow='slide', cost_usd=1.0, draft_id=draft_id)
            # The sweep must skip usage the live hold already prepays.
            result = db.bill_unbilled_usage(tenant)
            self.assertFalse(result.get('billed'), result)
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 90.0)
            # Settlement claims the run's usage under its own entry — one
            # debit total, and the usage lands on that entry, not a second.
            settle = db.consume_points(tenant, hold['id'])
            self.assertNotIn('error', settle, settle)
            billed = db.get_db().execute(
                'SELECT billed_ledger_id FROM ai_usage_events WHERE tenant_id = ?',
                (tenant,)).fetchone()
            self.assertIsNotNone(billed['billed_ledger_id'])
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 90.0)

    def test_usage_outside_the_hold_scope_still_bills(self):
        with self.app.app_context():
            tenant = self._wallet_tenant('hold-scope')
            db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='held-draft')
            db.save_project_draft(
                tenant, 'owner', {'project_name': 'حر'}, {'basic': 'draft'},
                'draft', draft_id='free-draft')
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-2', draft_id='held-draft')
            self.assertNotIn('error', hold, hold)
            db.record_ai_usage_event(
                tenant, 'model-x', flow='slide', cost_usd=1.0, draft_id='held-draft')
            db.record_ai_usage_event(
                tenant, 'model-x', flow='market', cost_usd=2.0, draft_id='free-draft')
            # Only the unrelated usage bills; the held draft's spend stays
            # prepaid until settlement.
            result = db.bill_unbilled_usage(tenant)
            self.assertTrue(result.get('billed'), result)
            entry = result.get('entry') or {}
            self.assertAlmostEqual(float(entry.get('ai_cost_usd') or 0), 2.0)
            held = db.get_db().execute(
                'SELECT billed_ledger_id FROM ai_usage_events WHERE draft_id = ?',
                ('held-draft',)).fetchone()
            self.assertIsNone(held['billed_ledger_id'])

    def test_released_hold_returns_its_usage_to_billable(self):
        with self.app.app_context():
            tenant = self._wallet_tenant('hold-release')
            db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='rel-draft')
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-3', draft_id='rel-draft')
            self.assertNotIn('error', hold, hold)
            db.record_ai_usage_event(
                tenant, 'model-x', flow='slide', cost_usd=1.0, draft_id='rel-draft')
            released = db.release_points(tenant, hold['id'])
            self.assertNotIn('error', released, released)
            # After release the escrow is refunded and the usage bills normally.
            self.assertAlmostEqual(db.get_tenant_balance(tenant), 100.0)
            result = db.bill_unbilled_usage(tenant)
            self.assertTrue(result.get('billed'), result)


class RunClaimScopeTests(ScopeTestBase):
    """ISS-035: settlement claims only this run's wallet-billable usage —
    package rows, still-unpriced attempts and usage older than the hold stay
    out of the settling entry."""

    def _settle_with_events(self, slug, events):
        with self.app.app_context():
            tenant = db.create_tenant('Claim ' + slug, slug + '@example.test', 'hash', slug)
            db.record_ledger_credit(tenant, 100.0, note='topup')
            draft_id = db.save_project_draft(
                tenant, 'owner', {'project_name': 'تشغيل'}, {'basic': 'approved'},
                'draft', draft_id='claim-draft-' + slug)
            ids = {}
            conn = db.get_db()
            for name, kwargs in events.items():
                kwargs = dict(kwargs)
                older = kwargs.pop('older_than_hold', False)
                kwargs.setdefault('tenant_id', tenant)
                kwargs.setdefault('draft_id', draft_id)
                ids[name] = db.record_ai_usage_event(model='model-x', **kwargs)
                if older:
                    conn.execute(
                        "UPDATE ai_usage_events SET created_at = '2020-01-01 00:00:00' WHERE id = ?",
                        (ids[name],))
                    conn.commit()
            hold = db.reserve_points(
                tenant, 10, cost_usd=10.0,
                generation_approval_id='appr-' + slug, draft_id=draft_id)
            self.assertNotIn('error', hold, hold)
            settle = db.consume_points(tenant, hold['id'])
            self.assertNotIn('error', settle, settle)
            rows = {
                row['id']: row['billed_ledger_id']
                for row in conn.execute(
                    'SELECT id, billed_ledger_id FROM ai_usage_events WHERE tenant_id = ?',
                    (tenant,)).fetchall()
            }
            return ids, rows

    def test_settled_usage_in_the_run_window_is_claimed(self):
        ids, rows = self._settle_with_events('inwin', {
            'settled': {'flow': 'slide', 'cost_usd': 1.0},
        })
        self.assertIsNotNone(rows[ids['settled']])

    def test_pending_and_package_rows_stay_unclaimed(self):
        ids, rows = self._settle_with_events('pend', {
            'pending': {'flow': 'slide', 'attempt_status': 'in_flight'},
            'packaged': {'flow': 'slide', 'cost_usd': 1.0, 'package_id': 'pkg-1'},
        })
        self.assertIsNone(rows[ids['pending']])
        self.assertIsNone(rows[ids['packaged']])

    def test_usage_older_than_the_hold_is_not_claimed(self):
        ids, rows = self._settle_with_events('older', {
            'prior': {'flow': 'slide', 'cost_usd': 1.0, 'older_than_hold': True},
            'current': {'flow': 'slide', 'cost_usd': 1.0},
        })
        self.assertIsNone(rows[ids['prior']])
        self.assertIsNotNone(rows[ids['current']])


class ProviderCapSyncTests(ScopeTestBase):
    """ISS-036: the provider's limit is a cumulative cap on usage — the PATCH
    must send usage + remaining entitlement or every re-sync silently shrinks
    the real allowance by what the key already burned."""

    def _sync(self, tenant, status, intended=80.0):
        captured = {}
        meta = {'has_key': True, 'openrouter_key_hash': 'hash-1',
                'is_active': 1, 'provenance': 'manual'}
        with self.app.app_context(), \
                patch.object(db, 'get_tenant_openrouter_key_meta', return_value=meta), \
                patch.object(db, 'update_tenant_openrouter_key_meta', return_value=meta), \
                patch.object(db, 'get_tenant_openrouter_key_raw', return_value='sk-or-fake'), \
                patch.object(self.module, '_openrouter_key_status', return_value=status), \
                patch.object(self.module, '_openrouter_update_managed_key',
                           side_effect=lambda h, **kw: captured.update(kw) or {'ok': True}):
            self.module._sync_tenant_credit_to_openrouter(tenant, new_limit_usd=intended)
        return captured

    def test_cap_patch_adds_recorded_usage_to_the_remaining_budget(self):
        with self.app.app_context():
            tenant = db.create_tenant('Cap T', 'cap@example.test', 'hash', 'cap-tenant')
        captured = self._sync(tenant, {'usage': 20.0, 'limit': 100.0}, intended=80.0)
        self.assertAlmostEqual(captured['limit_usd'], 100.0)

    def test_unreadable_usage_falls_back_to_the_conservative_cap(self):
        with self.app.app_context():
            tenant = db.create_tenant('Cap F', 'capf@example.test', 'hash', 'capf-tenant')
        captured = self._sync(tenant, {'error': 'network'}, intended=80.0)
        # Under-capping is the safe failure — the next successful sync corrects it.
        self.assertAlmostEqual(captured['limit_usd'], 80.0)


if __name__ == '__main__':
    unittest.main()
