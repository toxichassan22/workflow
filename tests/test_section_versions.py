"""Section snapshots with version numbers tied to approval (t10).

Covers db.section_versions (immutable snapshots, sequential numbers,
decisions naming the version) and the /api/project-draft/section-version*
endpoints plus the staleness gate on request-approval. Runs against a
temporary SQLite database and never calls Google or an AI API.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class SectionVersionDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'section-versions.db')
        db.init_db()
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('tenant-1', 'Tenant', 'tenant', 'tenant@example.test', 'hash', 'free'),
        )
        conn.commit()
        db.save_project_draft(
            'tenant-1', 'user-1',
            {'project_name': 'برج المشرق', 'city': 'الرياض'},
            {'basic': 'draft'}, 'draft', draft_id='draft-1',
        )

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_table_exists_after_schema_rerun_on_existing_database(self):
        """New tables must arrive on installs whose database already exists."""
        conn = db.get_db()
        conn.execute('DROP TABLE IF EXISTS section_versions')
        conn.commit()
        db._create_tables(conn)
        version = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'برج المشرق'},
            'user-1', 'User One',
        )
        self.assertNotIn('error', version)
        self.assertEqual(version['version_number'], 1)

    def test_sends_number_versions_sequentially_and_supersede_pending(self):
        first = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        second = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'B'}, 'user-1', 'User One')
        self.assertEqual(first['version_number'], 1)
        self.assertEqual(second['version_number'], 2)
        history = db.list_section_versions('tenant-1', 'draft-1', 'basic')
        self.assertEqual([item['status'] for item in history], ['pending', 'superseded'])
        self.assertEqual(history[1]['snapshot_hash'], db.section_snapshot_hash({'project_name': 'A'}))

    def test_snapshots_are_immutable(self):
        db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        stored = db.get_section_version(
            'tenant-1', db.list_section_versions('tenant-1', 'draft-1', 'basic')[0]['id'])
        self.assertEqual(stored['snapshot'], {'project_name': 'A'})

    def test_decision_names_the_version_and_needs_a_reason_to_return(self):
        version = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        refused = db.decide_section_version(
            'tenant-1', version['id'], 'returned', 'user-2', 'User Two')
        self.assertEqual(refused.get('error'), 'note_required')
        returned = db.decide_section_version(
            'tenant-1', version['id'], 'returned', 'user-2', 'User Two', 'وضح المصدر')
        self.assertEqual(returned['status'], 'returned')
        self.assertEqual(returned['decided_by_name'], 'User Two')
        again = db.decide_section_version(
            'tenant-1', version['id'], 'approved', 'user-2', 'User Two')
        self.assertEqual(again.get('error'), 'version_not_pending')

    def test_unknown_section_and_cross_tenant_access_are_refused(self):
        self.assertEqual(
            db.create_section_version(
                'tenant-1', 'draft-1', 'no-such-section', {}, 'user-1', 'User One').get('error'),
            'unknown_section',
        )
        version = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        self.assertIsNone(db.get_section_version('tenant-2', version['id']))
        self.assertEqual(
            db.decide_section_version('tenant-2', version['id'], 'approved', 'x', 'X').get('error'),
            'version_not_found',
        )

    def test_snapshot_hash_is_order_stable(self):
        self.assertEqual(
            db.section_snapshot_hash({'b': 1, 'a': 2}),
            db.section_snapshot_hash({'a': 2, 'b': 1}),
        )
        self.assertNotEqual(
            db.section_snapshot_hash({'a': 2}),
            db.section_snapshot_hash({'a': 3}),
        )

    def test_diff_against_predecessor_names_changed_fields(self):
        """The approver's comparison names every changed field between snapshots."""
        first = db.create_section_version(
            'tenant-1', 'draft-1', 'basic',
            {'project_name': 'برج المشرق', 'project_type': 'سكني'}, 'user-1', 'User One')
        second = db.create_section_version(
            'tenant-1', 'draft-1', 'basic',
            {'project_name': 'برج المشرق الثاني', 'project_type': 'سكني', 'city': 'الرياض'},
            'user-1', 'User One')

        diff = db.diff_section_versions('tenant-1', second['id'])
        self.assertNotIn('error', diff)
        self.assertEqual(diff['version_number'], 2)
        self.assertEqual(diff['base_version_number'], 1)
        by_key = {item['key']: item for item in diff['fields']}
        self.assertEqual(by_key['project_name']['status'], 'modified')
        self.assertEqual(by_key['project_name']['old_value'], 'برج المشرق')
        self.assertEqual(by_key['project_name']['new_value'], 'برج المشرق الثاني')
        self.assertEqual(by_key['city']['status'], 'added')
        self.assertEqual(diff['summary']['modified'], 1)
        self.assertEqual(diff['summary']['added'], 1)
        self.assertEqual(diff['summary']['unchanged'], 1)

    def test_diff_missing_required_fields_are_reported(self):
        """The comparison carries the completeness verdict of the sent snapshot."""
        version = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'city': 'الرياض'}, 'user-1', 'User One')
        diff = db.diff_section_versions('tenant-1', version['id'])
        self.assertFalse(diff['validation']['is_complete'])
        self.assertIn('اسم المشروع', diff['validation']['missing_fields'])

    def test_diff_refuses_a_base_version_from_another_section(self):
        """An explicit base must belong to the same section as the target."""
        basic = db.create_section_version(
            'tenant-1', 'draft-1', 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        land = db.create_section_version(
            'tenant-1', 'draft-1', 'land_croquis', {'croquis_land_area': 500}, 'user-1', 'User One')
        self.assertEqual(
            db.diff_section_versions(
                'tenant-1', basic['id'], base_version_id=land['id']).get('error'),
            'base_version_not_found',
        )


class SectionVersionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'section-versions-api.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')

        with cls.app.app_context():
            cls.tenant = db.create_tenant('Company A', 'a@example.test', 'hash-a', 'company-a')
        cls.token = auth.create_token(
            cls.tenant, 'a@example.test', user_id=None, user_name='Company A', user_role='company_admin'
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def setUp(self):
        client = self.app.test_client()
        with self.app.app_context():
            for row in db.get_db().execute('SELECT id FROM project_drafts').fetchall():
                db.get_db().execute('DELETE FROM section_versions WHERE draft_id = ?', (row['id'],))
                db.get_db().execute('DELETE FROM project_drafts WHERE id = ?', (row['id'],))
            db.get_db().commit()
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'project_name': 'برج المشرق', 'project_type': 'سكني', 'city': 'الرياض'},
            'sectionStatuses': {'basic': 'draft', 'land_croquis': 'draft'}, 'status': 'draft',
        })

    def test_send_decide_and_staleness_gate(self):
        client = self.app.test_client()

        sent = client.post('/api/project-draft/section-version',
                           headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(sent.status_code, 200, sent.get_json())
        version = sent.get_json()['version']
        self.assertEqual(version['version_number'], 1)
        self.assertEqual(version['status'], 'pending')

        # A direct toggle must wait for the pending version decision.
        blocked = client.post('/api/project-draft/section-status', headers=self.headers(), json={
            'sectionKey': 'basic', 'sectionStatus': 'approved'})
        self.assertEqual(blocked.status_code, 409, blocked.get_json())
        self.assertEqual(blocked.get_json()['error_code'], 'SECTION_VERSION_PENDING')

        # Returning without a reason is refused; with a reason it reopens the section.
        self.assertEqual(client.post('/api/project-draft/section-version/decision', headers=self.headers(),
                                     json={'versionId': version['id'], 'decision': 'returned'}).status_code, 400)
        sent2 = client.post('/api/project-draft/section-version',
                            headers=self.headers(), json={'sectionKey': 'basic'})
        version2 = sent2.get_json()['version']
        self.assertEqual(version2['version_number'], 2)

        decided = client.post('/api/project-draft/section-version/decision', headers=self.headers(), json={
            'versionId': version2['id'], 'decision': 'approved'})
        self.assertEqual(decided.status_code, 200, decided.get_json())
        self.assertEqual(decided.get_json()['version']['status'], 'approved')

        stored = client.get('/api/project-draft', headers=self.headers()).get_json()['draft']
        self.assertEqual(stored['section_statuses']['basic'], 'approved')

        client.post('/api/project-draft/section-status', headers=self.headers(), json={
            'sectionStatuses': {'land_croquis': 'approved'}})
        approval = client.post('/api/project-draft/request-approval', headers=self.headers(), json={})
        self.assertEqual(approval.status_code, 200, approval.get_json())

        # Editing the approved section after its approval voids overall readiness.
        draft = client.get('/api/project-draft', headers=self.headers()).get_json()['draft']
        changed = dict(draft['draft_data'])
        changed['project_name'] = 'برج المشرق المعدل'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})
        stale = client.post('/api/project-draft/request-approval', headers=self.headers(), json={})
        self.assertEqual(stale.status_code, 400, stale.get_json())
        self.assertEqual(stale.get_json()['error_code'], 'SECTION_VERSION_STALE')

        # Sending and approving the new content restores readiness.
        sent3 = client.post('/api/project-draft/section-version',
                            headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(sent3.get_json()['version']['version_number'], 3)
        client.post('/api/project-draft/section-version/decision', headers=self.headers(), json={
            'versionId': sent3.get_json()['version']['id'], 'decision': 'approved'})
        again = client.post('/api/project-draft/request-approval', headers=self.headers(), json={})
        self.assertEqual(again.status_code, 200, again.get_json())

    def test_history_and_restore_keep_earlier_versions(self):
        client = self.app.test_client()

        first = client.post('/api/project-draft/section-version',
                            headers=self.headers(), json={'sectionKey': 'basic'}).get_json()['version']
        client.post('/api/project-draft/section-version/decision', headers=self.headers(), json={
            'versionId': first['id'], 'decision': 'approved'})

        draft = client.get('/api/project-draft', headers=self.headers()).get_json()['draft']
        changed = dict(draft['draft_data'])
        changed['project_name'] = 'اسم أحدث'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})
        second = client.post('/api/project-draft/section-version',
                             headers=self.headers(), json={'sectionKey': 'basic'}).get_json()['version']

        restored = client.post('/api/project-draft/section-version/restore',
                               headers=self.headers(), json={'versionId': first['id']})
        self.assertEqual(restored.status_code, 200, restored.get_json())
        third = restored.get_json()['version']
        self.assertEqual(third['version_number'], 3)
        self.assertEqual(third['status'], 'pending')

        history = client.get('/api/project-draft/section-versions?sectionKey=basic',
                             headers=self.headers()).get_json()['versions']
        self.assertEqual([item['version_number'] for item in history], [3, 2, 1])
        by_number = {item['version_number']: item for item in history}
        self.assertEqual(by_number[1]['status'], 'approved')
        self.assertEqual(by_number[2]['status'], 'superseded')

        single = client.get(f"/api/project-draft/section-versions/{first['id']}",
                            headers=self.headers()).get_json()['version']
        self.assertEqual(single['snapshot'].get('project_name'), 'برج المشرق')
        live = client.get('/api/project-draft', headers=self.headers()).get_json()['draft']
        self.assertEqual(live['draft_data'].get('project_name'), 'برج المشرق')
        self.assertNotEqual(second['id'], third['id'])

    def test_legacy_toggle_still_works_without_versions(self):
        client = self.app.test_client()
        response = client.post('/api/project-draft/section-status', headers=self.headers(), json={
            'sectionKey': 'land_croquis', 'sectionStatus': 'approved'})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_unknown_section_send_is_rejected(self):
        client = self.app.test_client()
        response = client.post('/api/project-draft/section-version',
                               headers=self.headers(), json={'sectionKey': 'no-such-section'})
        self.assertEqual(response.status_code, 400, response.get_json())

    def test_send_requires_required_fields(self):
        client = self.app.test_client()
        draft = client.get('/api/project-draft', headers=self.headers()).get_json()['draft']
        changed = dict(draft['draft_data'])
        changed['project_type'] = ''
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})
        blocked = client.post('/api/project-draft/section-version',
                              headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(blocked.status_code, 400, blocked.get_json())
        self.assertEqual(blocked.get_json().get('error_code'), 'SECTION_VERSION_INCOMPLETE')
        changed['project_type'] = 'سكني'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})
        allowed = client.post('/api/project-draft/section-version',
                              headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

    def test_cancel_pending_version(self):
        client = self.app.test_client()
        sent = client.post('/api/project-draft/section-version',
                           headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(sent.status_code, 200, sent.get_json())
        version_id = sent.get_json()['version']['id']
        cancelled = client.post('/api/project-draft/section-version/cancel',
                                headers=self.headers(), json={'versionId': version_id})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        self.assertEqual(cancelled.get_json()['version']['status'], 'cancelled')
        decided = client.post('/api/project-draft/section-version/decision', headers=self.headers(), json={
            'versionId': version_id, 'decision': 'approved'})
        self.assertEqual(decided.status_code, 409, decided.get_json())
        again = client.post('/api/project-draft/section-version',
                            headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertEqual(again.get_json()['version']['version_number'], 2)

    def test_direct_toggle_blocked_for_versioned_section(self):
        client = self.app.test_client()
        sent = client.post('/api/project-draft/section-version',
                           headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(sent.status_code, 200, sent.get_json())
        decided = client.post('/api/project-draft/section-version/decision', headers=self.headers(), json={
            'versionId': sent.get_json()['version']['id'], 'decision': 'approved'})
        self.assertEqual(decided.status_code, 200, decided.get_json())
        draft = client.get('/api/project-draft', headers=self.headers()).get_json()['draft']
        changed = dict(draft['draft_data'])
        changed['project_name'] = 'اسم معدل بعد الاعتماد'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': {'basic': 'draft', 'land_croquis': 'draft'}, 'status': 'draft'})
        blocked = client.post('/api/project-draft/section-status', headers=self.headers(), json={
            'sectionKey': 'basic', 'sectionStatus': 'approved'})
        self.assertEqual(blocked.status_code, 409, blocked.get_json())
        self.assertIn(blocked.get_json().get('error_code'), {'SECTION_VERSION_STALE', 'SECTION_VERSION_REQUIRED'})

    def test_cross_user_approver_can_decide(self):
        client = self.app.test_client()
        sent = client.post('/api/project-draft/section-version',
                           headers=self.headers(), json={'sectionKey': 'basic'})
        self.assertEqual(sent.status_code, 200, sent.get_json())
        version_id = sent.get_json()['version']['id']
        with self.app.app_context():
            approver_id = db.create_user(
                self.tenant, 'Approver', 'approver@example.test', 'hash', role='employee')
            self.assertTrue(db.set_user_permission(approver_id, 'approvals', True))
            self.assertTrue(db.get_user_permissions(approver_id, 'employee').get('approvals'))
        approver_token = auth.create_token(
            self.tenant, 'approver@example.test', user_id=approver_id,
            user_name='Approver', user_role='employee')
        approver_headers = {'Authorization': f'Bearer {approver_token}'}
        decided = client.post('/api/project-draft/section-version/decision', headers=approver_headers, json={
            'versionId': version_id, 'decision': 'approved'})
        self.assertEqual(decided.status_code, 200, decided.get_json())
        self.assertEqual(decided.get_json()['version']['status'], 'approved')
        owner_draft_id = sent.get_json()['version']['draft_id']
        listed = client.get(
            f'/api/project-draft/section-versions?draftId={owner_draft_id}&sectionKey=basic',
            headers=approver_headers)
        self.assertEqual(listed.status_code, 200, listed.get_json())


class SectionVersionDiffApiTests(unittest.TestCase):
    """GET /api/project-draft/section-versions/<id>/diff (t13 comparison)."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'section-version-diff-api.db')
        # The app module is already imported by the first suite in this process,
        # so its one-time init will not run again: create the tables explicitly.
        db.init_db()

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')

        with cls.app.app_context():
            cls.tenant = db.create_tenant('Diff Co', 'diff@example.test', 'hash-diff', 'diff-co')
            cls.other_tenant = db.create_tenant('Other Co', 'other@example.test', 'hash-other', 'other-co')
        cls.token = auth.create_token(
            cls.tenant, 'diff@example.test', user_id=None, user_name='Diff Co', user_role='company_admin'
        )
        cls.other_token = auth.create_token(
            cls.other_tenant, 'other@example.test', user_id=None, user_name='Other Co', user_role='company_admin'
        )

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.close_db()
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def other_headers(self):
        return {'Authorization': f'Bearer {self.other_token}'}

    def setUp(self):
        client = self.app.test_client()
        with self.app.app_context():
            for row in db.get_db().execute('SELECT id FROM project_drafts').fetchall():
                db.get_db().execute('DELETE FROM section_versions WHERE draft_id = ?', (row['id'],))
                db.get_db().execute('DELETE FROM project_drafts WHERE id = ?', (row['id'],))
            db.get_db().commit()
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'project_name': 'برج المقارنة', 'project_type': 'سكني', 'city': 'الرياض'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft',
        })

    def _send_and_decide(self, client, decision='approved'):
        sent = client.post('/api/project-draft/section-version', headers=self.headers(),
                           json={'sectionKey': 'basic'})
        version = sent.get_json()['version']
        if decision:
            client.post('/api/project-draft/section-version/decision', headers=self.headers(),
                        json={'versionId': version['id'], 'decision': decision})
        return version

    def test_diff_lists_modified_fields_between_versions(self):
        client = self.app.test_client()
        self._send_and_decide(client)
        draft = client.get('/api/project-draft', headers=self.headers()).get_json()['draft']
        changed = dict(draft['draft_data'])
        changed['project_name'] = 'برج المقارنة الثاني'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})
        second = self._send_and_decide(client, decision=None)

        diff = client.get(f"/api/project-draft/section-versions/{second['id']}/diff",
                          headers=self.headers())
        self.assertEqual(diff.status_code, 200, diff.get_json())
        body = diff.get_json()['diff']
        self.assertEqual(body['version_number'], 2)
        self.assertEqual(body['base_version_number'], 1)
        self.assertEqual(body['summary']['modified'], 1)
        modified = [item for item in body['fields'] if item['status'] == 'modified']
        self.assertEqual(modified[0]['key'], 'project_name')
        self.assertEqual(modified[0]['old_value'], 'برج المقارنة')
        self.assertEqual(modified[0]['new_value'], 'برج المقارنة الثاني')
        self.assertTrue(body['validation']['is_complete'])

    def test_first_version_diffs_against_empty(self):
        client = self.app.test_client()
        version = self._send_and_decide(client)
        diff = client.get(f"/api/project-draft/section-versions/{version['id']}/diff",
                          headers=self.headers())
        self.assertEqual(diff.status_code, 200, diff.get_json())
        body = diff.get_json()['diff']
        self.assertIsNone(body['base_version_number'])
        self.assertEqual(body['summary']['added'], len(body['fields']) + len(body['attachments']))

    def test_explicit_base_is_accepted_and_unknown_base_is_refused(self):
        client = self.app.test_client()
        first = self._send_and_decide(client)
        second = self._send_and_decide(client)

        explicit = client.get(
            f"/api/project-draft/section-versions/{second['id']}/diff"
            f"?baseVersionId={first['id']}", headers=self.headers())
        self.assertEqual(explicit.status_code, 200, explicit.get_json())
        self.assertEqual(explicit.get_json()['diff']['base_version_number'], 1)

        unknown_base = client.get(
            f"/api/project-draft/section-versions/{second['id']}/diff"
            f"?baseVersionId=no-such-id", headers=self.headers())
        self.assertEqual(unknown_base.status_code, 404, unknown_base.get_json())

    def test_diff_is_scoped_to_the_tenant_and_unknown_versions_404(self):
        client = self.app.test_client()
        version = self._send_and_decide(client)
        missing = client.get('/api/project-draft/section-versions/no-such-id/diff',
                             headers=self.headers())
        self.assertEqual(missing.status_code, 404)
        cross = client.get(f"/api/project-draft/section-versions/{version['id']}/diff",
                           headers=self.other_headers())
        self.assertEqual(cross.status_code, 404, cross.get_json())


if __name__ == '__main__':
    unittest.main()
