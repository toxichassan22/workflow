"""The open workspace follows the file — the live state of a project file.

A merge by somebody else changes the file under the people who still have it
open, so the workspace asks for the state of the file it has open and acts on
it. The endpoint is a tiny read (the revision, who changed it last, the state
of the badges), and it is tenant-scoped like every other draft read.

Runs against a temporary SQLite database and never calls an AI API.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class DraftLiveStateApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'draft-live-state.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = application_module.UPLOADS_DIR
        cls.application_module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Company A', 'a@example.test', 'hash-a', 'company-a')
            cls.other_tenant = db.create_tenant('Company B', 'b@example.test', 'hash-b', 'company-b')
        cls.token = auth.create_token(
            cls.tenant, 'a@example.test', user_id=None, user_name='Company A', user_role='company_admin'
        )
        cls.other_token = auth.create_token(
            cls.other_tenant, 'b@example.test', user_id=None, user_name='Company B', user_role='company_admin'
        )
        # Two employees of the same company: the file belongs to the first one
        # and the second one works on it too.
        with cls.app.app_context():
            cls.employee_a = db.create_user(cls.tenant, 'موظف أول', 'employee-a@example.test', 'hash-a')
            cls.employee_b = db.create_user(cls.tenant, 'موظف ثاني', 'employee-b@example.test', 'hash-b')
        cls.employee_a_token = auth.create_token(
            cls.tenant, 'employee-a@example.test', user_id=cls.employee_a,
            user_name='موظف أول', user_role='employee'
        )
        cls.employee_b_token = auth.create_token(
            cls.tenant, 'employee-b@example.test', user_id=cls.employee_b,
            user_name='موظف ثاني', user_role='employee'
        )

    @classmethod
    def tearDownClass(cls):
        cls.application_module.UPLOADS_DIR = cls.previous_uploads
        cls.temp_dir.cleanup()

    def headers(self, token=None):
        return {'Authorization': f'Bearer {token or self.token}'}

    def setUp(self):
        client = self.app.test_client()
        with self.app.app_context():
            for row in db.get_db().execute('SELECT id FROM project_drafts').fetchall():
                db.get_db().execute('DELETE FROM draft_commits WHERE draft_id = ?', (row['id'],))
                db.get_db().execute('DELETE FROM project_drafts WHERE id = ?', (row['id'],))
            db.get_db().execute('DELETE FROM draft_branches')
            db.get_db().commit()
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft',
        })

    def draft(self, client):
        return client.get('/api/project-draft', headers=self.headers()).get_json()['draft']

    def test_the_state_reports_the_revision_and_the_last_change(self):
        client = self.app.test_client()
        draft = self.draft(client)
        state = client.get(f"/api/project-draft/{draft['id']}/state", headers=self.headers())
        self.assertEqual(state.status_code, 200, state.get_json())
        body = state.get_json()
        self.assertEqual(body['revision'], int(draft.get('revision') or 0))
        self.assertTrue(body['lastCommit'])
        self.assertEqual(body['lastCommit']['author'], 'Company A')
        self.assertEqual(body['openBranches'], 0)
        self.assertEqual(body['sectionStatuses'].get('basic'), 'draft')

    def test_a_change_is_reported_against_the_revision_the_caller_holds(self):
        client = self.app.test_client()
        draft = self.draft(client)
        revision = int(draft.get('revision') or 0)

        unchanged = client.get(f"/api/project-draft/{draft['id']}/state?since={revision}",
                               headers=self.headers()).get_json()
        self.assertFalse(unchanged['changed'])

        changed = dict(draft['draft_data'])
        changed['project_idea'] = 'فكرة'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        after = client.get(f"/api/project-draft/{draft['id']}/state?since={revision}",
                           headers=self.headers()).get_json()
        self.assertTrue(after['changed'])
        self.assertGreater(after['revision'], revision)

    def test_a_merge_is_reported_as_a_merge(self):
        client = self.app.test_client()
        draft = self.draft(client)
        revision = int(draft.get('revision') or 0)
        created = client.post(f"/api/project-draft/{draft['id']}/branches", headers=self.headers(),
                               json={'name': 'فرع الموقع'}).get_json()
        branch = created['branch']
        branch_draft_id = created['branchDraftId']
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': branch_draft_id,
            'draftData': {'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني',
                          'city_code': 'RUH'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft'})
        client.post(f"/api/project-draft/{draft['id']}/branches/{branch['id']}/merge",
                    headers=self.headers(), json={'resolutions': []})

        state = client.get(f"/api/project-draft/{draft['id']}/state?since={revision}",
                           headers=self.headers()).get_json()
        self.assertTrue(state['changed'])
        self.assertEqual(state['lastCommit']['kind'], 'merge')
        self.assertEqual(state['openBranches'], 0)

    def test_the_state_of_another_company_is_not_reachable(self):
        client = self.app.test_client()
        draft = self.draft(client)
        refused = client.get(f"/api/project-draft/{draft['id']}/state",
                             headers=self.headers(self.other_token))
        self.assertEqual(refused.status_code, 404, refused.get_json())

    def test_a_colleague_inside_the_company_can_follow_the_file(self):
        """The poll answers "did the file move under me", so whoever may open
        the file may follow it. The owner-only rule left every colleague on a
        manual refresh — and the poll failed silently while it did."""
        client = self.app.test_client()
        draft = self.draft(client)
        colleague = {'Authorization': f'Bearer {self.employee_b_token}'}

        opened = client.get(f"/api/project-draft/{draft['id']}", headers=colleague)
        self.assertEqual(opened.status_code, 200, opened.get_json())

        state = client.get(f"/api/project-draft/{draft['id']}/state?since=0", headers=colleague)
        self.assertEqual(state.status_code, 200, state.get_json())
        body = state.get_json()
        self.assertEqual(body['revision'], int(draft.get('revision') or 0))
        self.assertTrue(body['changed'])

    def test_a_colleague_sees_the_change_of_the_people_working_on_it(self):
        client = self.app.test_client()
        draft = self.draft(client)
        revision = int(draft.get('revision') or 0)
        colleague = {'Authorization': f'Bearer {self.employee_b_token}'}

        changed = dict(draft['draft_data'])
        changed['project_idea'] = 'فكرة'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        after = client.get(f"/api/project-draft/{draft['id']}/state?since={revision}",
                           headers=colleague)
        self.assertEqual(after.status_code, 200, after.get_json())
        self.assertTrue(after.get_json()['changed'])
        self.assertGreater(after.get_json()['revision'], revision)

    def test_the_state_read_does_not_carry_the_draft_payload(self):
        """The poll runs every few seconds per open workspace, so it must not
        parse a multi-megabyte draft payload to learn one revision number."""
        client = self.app.test_client()
        draft = self.draft(client)
        with self.app.app_context():
            light = db.get_project_draft_state(self.tenant, draft['id'])
        self.assertIsNotNone(light)
        self.assertNotIn('draft_data', light)
        self.assertIn('revision', light)
        state = client.get(f"/api/project-draft/{draft['id']}/state", headers=self.headers())
        self.assertNotIn('draft_data', state.get_json())

    def test_a_user_scoped_to_another_project_cannot_follow_this_file(self):
        client = self.app.test_client()
        draft = self.draft(client)
        # A save without a draft id lands on the actor's newest editable file,
        # so the second project is named explicitly.
        other = client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'draftId': 'scope-other-draft', 'project_name': 'مشروع آخر', 'city': 'جدة'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft',
        }).get_json()
        self.assertNotEqual(other.get('draftId'), draft['id'])
        with self.app.app_context():
            db.set_user_project_scope(self.tenant, self.employee_b, [other['draftId']])
        colleague = {'Authorization': f'Bearer {self.employee_b_token}'}
        refused = client.get(f"/api/project-draft/{draft['id']}/state", headers=colleague)
        self.assertEqual(refused.status_code, 404, refused.get_json())
        with self.app.app_context():
            db.set_user_project_scope(self.tenant, self.employee_b, [])


if __name__ == '__main__':
    unittest.main()
