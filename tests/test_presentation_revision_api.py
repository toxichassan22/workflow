"""Revision API regressions. Temporary database/media only; no provider calls."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import auth
import db


class PresentationRevisionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp.name, 'revisions-api.db')
        import app as application
        import presentation_assets
        cls.module = application
        cls.app = application.app
        cls.app.config['TESTING'] = True
        cls.assets = presentation_assets
        cls.patches = [
            patch.object(application.slide_engine, 'renumber_presentation_slides', side_effect=lambda slides, **kw: copy.deepcopy(slides)),
            patch.object(application, '_prepare_generation_logo_context', return_value=None),
            patch.object(application, '_presentation_creative_images', return_value={}),
            patch.object(application, 'UPLOADS_DIR', str(Path(cls.temp.name) / 'uploads')),
            patch.object(presentation_assets, 'ROOT', Path(cls.temp.name)),
        ]
        for item in cls.patches:
            item.start()
        with cls.app.app_context():
            cls.tenant = db.create_tenant('Revision Tenant', 'revision@example.test', 'hash', 'revision-tenant')
            cls.other = db.create_tenant('Other Tenant', 'other-revision@example.test', 'hash', 'other-revision')
        cls.headers = {'Authorization': 'Bearer ' + auth.create_token(
            cls.tenant, 'revision@example.test', user_name='Authenticated Editor', user_role='company_admin')}
        cls.other_headers = {'Authorization': 'Bearer ' + auth.create_token(
            cls.other, 'other-revision@example.test', user_name='Other Editor', user_role='company_admin')}
        cls.denied_headers = {'Authorization': 'Bearer ' + auth.create_token(
            cls.tenant, 'employee@example.test', user_id='restricted-user', user_name='Restricted', user_role='employee')}

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

    def create(self, **updates):
        data = {'title': 'Original title', 'projectData': {'city': 'Original city'},
                'slidesData': [{'title': 'One', 'html': '<div class="slide">Original</div>'}],
                'expectedRevision': 0, **updates}
        response = self.client.post('/api/presentations', headers=self.headers, json=data)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def put(self, created, **updates):
        return self.client.put('/api/presentations/' + created['presentationId'], headers=self.headers,
                               json={'expectedRevision': created['revision'], **updates})

    def versions(self, created):
        response = self.client.get('/api/presentations/' + created['presentationId'] + '/versions', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['versions']

    def test_create_has_full_revision_and_actor_linked_history(self):
        created = self.create(userName='Spoofed Actor', userId='spoofed', changeSource='ai')
        self.assertEqual(created['revision'], 1)
        version = self.versions(created)[0]
        self.assertEqual(version['snapshotKind'], 'full')
        self.assertEqual(version['user_name'], 'Authenticated Editor')
        self.assertEqual(version['source'], 'manual')
        detail = self.client.get(f"/api/presentations/{created['presentationId']}/versions/{version['id']}", headers=self.headers).get_json()['version']
        self.assertEqual(detail['snapshot']['title'], 'Original title')
        self.assertEqual(detail['snapshot']['projectData']['city'], 'Original city')
        history = self.client.get(f"/api/presentations/{created['presentationId']}/edit-log", headers=self.headers).get_json()['log']
        self.assertEqual(history[0]['revision_id'], version['id'])

    def test_identical_save_is_not_a_duplicate_version_or_card(self):
        created = self.create()
        response = self.put(created, title='Original title', slidesData=created['presentation']['slidesData'])
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json()['changed'])
        self.assertEqual(response.get_json()['revision'], 1)
        self.assertEqual(len(self.versions(created)), 1)

    def test_stale_and_invalid_revision_do_not_write(self):
        created = self.create()
        edited = self.put(created, title='New title').get_json()
        response = self.put(created, title='Stale title')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error_code'], 'PRESENTATION_REVISION_CONFLICT')
        self.assertEqual(response.get_json()['currentRevision'], edited['revision'])
        self.assertEqual(len(self.versions(created)), 2)
        for expected in (None, True, -1, '2', 1.5):
            response = self.client.put(f"/api/presentations/{created['presentationId']}", headers=self.headers,
                                       json={'title': 'Bad title', 'expectedRevision': expected})
            self.assertEqual(response.status_code, 400, expected)

    def test_restore_restores_full_state_as_new_revision_without_rewinding_draft(self):
        with self.app.app_context():
            draft_id = db.save_project_draft(self.tenant, 'owner', {'project_name': 'Source project'}, draft_id='restore-source')
        created = self.create(projectData={'city': 'Original city', 'draftId': draft_id, 'presentation_scope': 'full'})
        original_version = created['versionId']
        edited = self.put(created, title='Edited title', projectData={'city': 'Edited city', 'draftId': draft_id},
                          slidesData=[{'html': '<div class="slide">Edited</div>'}]).get_json()
        with self.app.app_context():
            db.save_project_draft(self.tenant, 'owner', {'project_name': 'New draft facts'}, draft_id=draft_id)
            db.update_presentation(created['presentationId'], status='approved')
        response = self.client.post(f"/api/presentations/{created['presentationId']}/versions/{original_version}/restore",
                                    headers=self.headers, json={'expectedRevision': edited['revision']})
        self.assertEqual(response.status_code, 200, response.get_json())
        restored = response.get_json()
        self.assertEqual(restored['presentationId'], created['presentationId'])
        self.assertEqual(restored['revision'], 3)
        self.assertEqual(restored['presentation']['title'], 'Original title')
        self.assertEqual(restored['presentation']['projectData']['city'], 'Original city')
        self.assertEqual(restored['presentation']['status'], 'draft')
        self.assertEqual(restored['slidesData'], created['presentation']['slidesData'])
        self.assertEqual(self.versions(created)[0]['restored_from_revision_id'], original_version)
        with self.app.app_context():
            self.assertEqual(db.get_project_draft_by_id(self.tenant, draft_id)['draft_data']['project_name'], 'New draft facts')
            self.assertEqual(len(db.get_presentations(self.tenant, draft_id=draft_id)), 1)
        stale = self.client.post(f"/api/presentations/{created['presentationId']}/versions/{original_version}/restore",
                                 headers=self.headers, json={'expectedRevision': edited['revision']})
        self.assertEqual(stale.status_code, 409)

    def test_legacy_slides_only_restore_is_labelled_and_keeps_current_facts(self):
        created = self.create()
        with self.app.app_context():
            legacy = db.save_presentation_version(created['presentationId'], None, 'Historical user',
                                                  [{'html': '<div class="slide">Legacy</div>'}])
        versions = self.versions(created)
        item = next(v for v in versions if v['id'] == legacy)
        self.assertEqual(item['snapshotKind'], 'legacy-slides')
        self.assertIn('الشرائح فقط', item['label'])
        detail = self.client.get(f"/api/presentations/{created['presentationId']}/versions/{legacy}", headers=self.headers).get_json()['version']
        self.assertNotIn('projectData', detail['snapshot'])
        restored = self.client.post(f"/api/presentations/{created['presentationId']}/versions/{legacy}/restore",
                                    headers=self.headers, json={'expectedRevision': 1}).get_json()
        self.assertEqual(restored['presentation']['title'], 'Original title')
        self.assertEqual(restored['presentation']['projectData']['city'], 'Original city')
        self.assertIn('Legacy', restored['slidesData'][0]['html'])

    def test_permission_and_tenant_scope_for_history_detail_compare_restore(self):
        created = self.create()
        base = f"/api/presentations/{created['presentationId']}"
        routes = [base + '/versions', base + '/edit-log', base + '/versions/' + created['versionId'],
                  base + '/versions/compare?from=' + created['versionId']]
        for route in routes:
            self.assertEqual(self.client.get(route, headers=self.other_headers).status_code, 404)
            with patch.object(db, 'get_user_permissions', return_value={}):
                self.assertEqual(self.client.get(route, headers=self.denied_headers).status_code, 403)
        restore = base + '/versions/' + created['versionId'] + '/restore'
        self.assertEqual(self.client.post(restore, headers=self.other_headers, json={}).status_code, 404)
        with patch.object(db, 'get_user_permissions', return_value={}):
            self.assertEqual(self.client.post(restore, headers=self.denied_headers, json={}).status_code, 403)
        another = self.create()
        wrong = f"/api/presentations/{another['presentationId']}/versions/{created['versionId']}"
        self.assertEqual(self.client.get(wrong, headers=self.headers).status_code, 404)

    def test_compare_and_scope_list(self):
        created = self.create(projectData={'city': 'Original city', 'presentation_scope': 'section:financial'})
        self.put(created, title='Updated title', projectData={'city': 'Changed city'})
        response = self.client.get(f"/api/presentations/{created['presentationId']}/versions/compare?from={created['versionId']}&to=current", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['changes'])
        self.assertEqual(response.get_json()['from']['snapshot']['title'], 'Original title')
        self.assertEqual(response.get_json()['to']['snapshot']['title'], 'Updated title')
        rows = self.client.get('/api/presentations', headers=self.headers).get_json()['presentations']
        row = next(r for r in rows if r['id'] == created['presentationId'])
        self.assertEqual(row['presentationScope'], 'section:financial')
        self.assertEqual(row['revision'], 2)
        current = {**created, 'revision': 2}
        self.assertEqual(self.put(current, projectData={'presentation_scope': 'full'}).status_code, 409)

    def test_approved_content_change_resets_status_but_noop_does_not(self):
        created = self.create()
        with self.app.app_context():
            db.update_presentation(created['presentationId'], status='approved')
        unchanged = self.put(created, title='Original title').get_json()
        self.assertEqual(unchanged['presentation']['status'], 'approved')
        edited = self.put(created, title='Changed', status='approved').get_json()
        self.assertEqual(edited['presentation']['status'], 'draft')
        self.assertEqual(edited['revision'], 2)

    def test_verified_ai_receipt_records_real_authenticated_actor(self):
        created = self.create()
        slides = [{'html': '<div class="slide">AI change</div>'}]
        with self.app.test_request_context():
            from flask import g
            g.tenant_id, g.user_id = self.tenant, None
            provenance = self.module._issue_presentation_provenance(slides, created['presentationId'], 1,
                                                                    ['طلب التصميم: تعديل العنوان'])
        saved = self.put(created, slidesData=slides, changeSource='ai', provenance=provenance,
                         userName='Imaginary AI').get_json()
        self.assertEqual(saved['revision'], 2)
        version = self.versions(created)[0]
        self.assertEqual(version['source'], 'ai')
        self.assertEqual(version['user_name'], 'Authenticated Editor')
        self.assertIn('طلب التصميم: تعديل العنوان', version['details'])
        forged = self.put(saved, slidesData=[{'html': '<div class="slide">Other change</div>'}],
                          changeSource='ai', provenance=provenance)
        self.assertEqual(forged.status_code, 200, forged.get_json())
        self.assertEqual(self.versions(created)[0]['source'], 'manual')

    def test_local_asset_bytes_remain_immutable_after_source_overwrite(self):
        folder = Path(self.temp.name) / 'uploads' / 'creative' / self.tenant
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / 'mutable.png'
        source.write_bytes(b'original image bytes')
        url = f'/uploads/creative/{self.tenant}/mutable.png'
        created = self.create(slidesData=[{'html': f'<div class="slide"><img src="{url}"></div>'}],
                              projectData={'cover': url})
        snapshot_url = created['presentation']['projectData']['cover']
        self.assertIn('/revisions/', snapshot_url)
        source.write_bytes(b'replacement image bytes')
        self.assertEqual((Path(self.temp.name) / snapshot_url.lstrip('/')).read_bytes(), b'original image bytes')
        fetched = self.client.get(f"/api/presentations/{created['presentationId']}", headers=self.headers).get_json()
        self.assertEqual(fetched['presentation']['projectData']['cover'], snapshot_url)
        asset = self.client.get(snapshot_url)
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.data, b'original image bytes')
        asset.close()

    def test_super_agent_saves_same_identity_with_authenticated_actor(self):
        created = self.create()
        with self.app.test_request_context():
            from flask import g
            g.tenant_id, g.user_id, g.user_name = self.tenant, None, 'Authenticated Editor'
            workspace = {'presentationId': created['presentationId'], 'expectedRevision': 1,
                         'slidesData': [{'title': 'AI', 'html': '<div class="slide">Agent text</div>'}],
                         'projectData': {'city': 'Agent city'}}
            with patch.object(self.module, '_validate_workspace_data', return_value={'valid': True}):
                result = self.module._execute_agent_action(self.tenant, {'tool': 'save_workspace', 'params': {'title': 'Agent title'}}, workspace=workspace)
            self.assertEqual(result['data']['revision'], 2, result)
            self.assertEqual(workspace['expectedRevision'], 2)
            self.assertEqual(result['presentationId'], created['presentationId'])
        self.assertEqual(self.versions(created)[0]['user_name'], 'Authenticated Editor')
        self.assertEqual(self.versions(created)[0]['source'], 'ai')

    def test_scoped_creation_cannot_add_duplicate_card(self):
        with self.app.app_context():
            draft_id = db.save_project_draft(self.tenant, 'owner', {'project_name': 'Scoped'}, draft_id='scope-source')
        project = {'draftId': draft_id, 'presentation_scope': 'full'}
        created = self.create(projectData=project)
        response = self.client.post('/api/presentations', headers=self.headers, json={
            'title': 'Concurrent different content', 'projectData': project,
            'slidesData': [{'html': '<div class="slide">Concurrent</div>'}], 'expectedRevision': 0})
        self.assertEqual(response.status_code, 409, response.get_json())
        self.assertEqual(response.get_json()['presentationId'], created['presentationId'])
        self.assertEqual(response.get_json()['error_code'], 'PRESENTATION_SCOPE_EXISTS')
        with self.app.app_context():
            self.assertEqual(len(db.get_presentations(self.tenant, draft_id=draft_id)), 1)
        copy_result = self.create(projectData={**project, 'presentation_scope': 'copy:separate'})
        self.assertNotEqual(copy_result['presentationId'], created['presentationId'])

    def test_ai_assistance_survives_manual_fitting_before_save(self):
        created = self.create()
        slides = [{'html': '<div class="slide">AI wording</div>'}]
        with self.app.test_request_context():
            from flask import g
            g.tenant_id, g.user_id = self.tenant, None
            provenance = self.module._issue_presentation_provenance(slides, created['presentationId'], 1, ['طلب التصميم'])
        changed = self.put(created, slidesData=[{'html': '<div class="slide" style="font-size:20px">AI wording and manual edit</div>'}],
                           changeSource='ai', provenance=provenance)
        self.assertEqual(changed.status_code, 200, changed.get_json())
        version = self.versions(created)[0]
        self.assertEqual(version['source'], 'ai')
        self.assertIn('تعديلات يدوية', version['details'][-2])

    def test_map_tenant_and_revision_guard_precedes_provider(self):
        created = self.create()
        payload = {'presentationId': created['presentationId'], 'mapType': 'overview',
                   'projectData': {}, 'overlayOnly': True, 'expectedRevision': 0}
        with patch.object(self.module.maps_service, 'recompose_overview_map') as provider:
            response = self.client.post('/api/generate-map-image', headers=self.headers, json=payload)
            self.assertEqual(response.status_code, 409, response.get_json())
            response = self.client.post('/api/generate-map-image', headers=self.other_headers, json=payload)
            self.assertEqual(response.status_code, 404, response.get_json())
            provider.assert_not_called()

    def test_project_documents_image_in_metadata_allowed_without_authorization_error(self):
        project = {
            'project_name': 'Project With Croquis Image',
            'croquis_file': f'/uploads/{self.tenant}/project-documents/a99131413d33f94ab3fcca7bffb7c7fa6d61c1628e75d683c8aa5955dcda3f47.png',
            'land_photos': [f'uploads/{self.tenant}/project-documents/b1234567890abcdef.jpg'],
        }
        response = self.client.post('/api/presentations', headers=self.headers, json={
            'title': 'Project Image Test', 'projectData': project,
            'slidesData': [{'html': '<div class="slide">Slide Content</div>'}],
            'slideCount': 1,
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        self.assertTrue(data.get('success'))
        self.assertTrue(data.get('presentationId'))


if __name__ == '__main__':
    unittest.main()

