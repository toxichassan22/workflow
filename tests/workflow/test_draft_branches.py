"""Branches of a project file — parallel work that merges like git.

Covers the branch store in db (the fork, the three-way merge, the conflicts
that need a human decision, the merge landing as a commit) and the routes in
app_parts/12_drafts/12d_draft_branches.py. Runs against a temporary SQLite
database and never calls an AI API.
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


class DraftBranchStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'draft-branches.db')
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
        db.save_project_draft('tenant-1', 'user-1',
                              {'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني'},
                              {'basic': 'draft'}, 'draft', draft_id='draft-1')

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def save_main(self, payload):
        return db.save_project_draft('tenant-1', 'user-1', payload, {'basic': 'draft'}, 'draft',
                                     draft_id='draft-1')

    def branch(self, **kwargs):
        created = db.create_draft_branch('tenant-1', 'draft-1', author_id='user-1',
                                         author_name='User One', **kwargs)
        self.assertNotIn('error', created)
        return created

    def save_branch(self, branch_draft_id, payload):
        return db.save_project_draft('tenant-1', 'user-2', payload, {'basic': 'draft'}, 'draft',
                                     draft_id=branch_draft_id)

    def test_a_branch_is_a_fork_that_leaves_the_main_line_alone(self):
        """The branch works on its own copy; the main file does not move."""
        created = self.branch(name='فرع الموقع')
        branch_draft_id = created['branchDraftId']

        main = db.get_project_draft_by_id('tenant-1', 'draft-1')
        branch = db.get_project_draft_by_id('tenant-1', branch_draft_id)
        self.assertEqual(main['draft_data']['project_name'], 'برج المشرق')
        self.assertEqual(branch['parent_draft_id'], 'draft-1')
        self.assertEqual(branch['branch_label'], 'فرع الموقع')
        self.assertEqual(branch['draft_data']['project_name'], 'برج المشرق')

    def test_a_branch_is_not_a_project_of_its_own(self):
        """The project list shows the file, not its forks."""
        self.branch(name='فرع الموقع')
        summaries = db.get_all_project_draft_summaries('tenant-1')
        self.assertEqual([item['id'] for item in summaries], ['draft-1'])
        self.assertEqual(db.get_project_draft('tenant-1', 'user-1')['id'], 'draft-1')

    def test_the_merge_takes_both_sides_when_they_do_not_collide(self):
        """Two people editing different fields merge into one file."""
        created = self.branch(name='فرع الموقع')
        branch_draft_id = created['branchDraftId']

        self.save_main({'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني',
                        'project_idea': 'فكرة جديدة'})
        self.save_branch(branch_draft_id, {'project_name': 'برج المشرق', 'city': 'الرياض',
                                           'project_type': 'سكني', 'city_code': 'RUH'})

        preview = db.draft_branch_merge_preview('tenant-1', 'draft-1', created['branch']['id'])
        self.assertNotIn('error', preview)
        self.assertEqual(preview['conflicts'], [])
        changed = {item['key'] for item in preview['changes']}
        self.assertEqual(changed, {'city_code'})

        merged, unresolved = db.apply_merge_resolutions(preview['merged'], preview['conflicts'], [])
        self.assertEqual(unresolved, [])
        self.assertEqual(merged['project_idea'], 'فكرة جديدة')
        self.assertEqual(merged['city_code'], 'RUH')

    def test_a_conflict_needs_a_decision_before_the_merge(self):
        """Both sides changing the same field is a conflict, not a silent win."""
        created = self.branch(name='فرع الموقع')
        branch_draft_id = created['branchDraftId']

        self.save_main({'project_name': 'اسم المشروع', 'city': 'الرياض', 'project_type': 'سكني'})
        self.save_branch(branch_draft_id, {'project_name': 'اسم الفرع', 'city': 'الرياض',
                                           'project_type': 'سكني'})

        preview = db.draft_branch_merge_preview('tenant-1', 'draft-1', created['branch']['id'])
        self.assertEqual([item['key'] for item in preview['conflicts']], ['project_name'])
        conflict = preview['conflicts'][0]
        self.assertEqual(conflict['ours'], 'اسم المشروع')
        self.assertEqual(conflict['theirs'], 'اسم الفرع')

        _merged, unresolved = db.apply_merge_resolutions(preview['merged'], preview['conflicts'], [])
        self.assertEqual([item['key'] for item in unresolved], ['project_name'])

        resolved, unresolved = db.apply_merge_resolutions(
            preview['merged'], preview['conflicts'],
            [{'key': 'project_name', 'choice': 'theirs'}])
        self.assertEqual(unresolved, [])
        self.assertEqual(resolved['project_name'], 'اسم الفرع')

    def test_a_branch_that_already_merged_cannot_merge_again(self):
        created = self.branch(name='فرع الموقع')
        branch_draft_id = created['branchDraftId']
        self.save_branch(branch_draft_id, {'project_name': 'برج المشرق', 'city': 'الرياض',
                                           'project_type': 'سكني', 'city_code': 'RUH'})
        preview = db.draft_branch_merge_preview('tenant-1', 'draft-1', created['branch']['id'])
        merged, _unresolved = db.apply_merge_resolutions(preview['merged'], preview['conflicts'], [])
        db.save_project_draft('tenant-1', 'user-1', merged, {'basic': 'draft'}, 'draft',
                              draft_id='draft-1', commit_kind='merge')
        db.finish_draft_branch_merge('tenant-1', 'draft-1', created['branch']['id'], None)

        again = db.draft_branch_merge_preview('tenant-1', 'draft-1', created['branch']['id'])
        self.assertEqual(again.get('error'), 'branch_already_merged')
        refused = db.discard_draft_branch('tenant-1', 'draft-1', created['branch']['id'])
        self.assertEqual(refused.get('error'), 'branch_already_merged')

    def test_discarding_a_branch_removes_the_fork(self):
        created = self.branch(name='فرع الموقع')
        branch_draft_id = created['branchDraftId']
        result = db.discard_draft_branch('tenant-1', 'draft-1', created['branch']['id'])
        self.assertTrue(result.get('discarded'))
        self.assertIsNone(db.get_project_draft_by_id('tenant-1', branch_draft_id))
        self.assertEqual(db.list_draft_branches('tenant-1', 'draft-1'), [])


class DraftBranchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'draft-branches-api.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.previous_uploads = application_module.UPLOADS_DIR
        cls.application_module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')

        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Company A', 'a@example.test', 'hash-a', 'company-a')
        cls.token = auth.create_token(
            cls.tenant, 'a@example.test', user_id=None, user_name='Company A', user_role='company_admin'
        )

    @classmethod
    def tearDownClass(cls):
        cls.application_module.UPLOADS_DIR = cls.previous_uploads
        cls.temp_dir.cleanup()

    def headers(self):
        return {'Authorization': f'Bearer {self.token}'}

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

    def test_a_branch_is_created_listed_and_merged(self):
        client = self.app.test_client()
        draft = self.draft(client)

        created = client.post(f"/api/project-draft/{draft['id']}/branches", headers=self.headers(),
                               json={'name': 'فرع الموقع'})
        self.assertEqual(created.status_code, 200, created.get_json())
        branch = created.get_json()['branch']
        branch_draft_id = created.get_json()['branchDraftId']

        listed = client.get(f"/api/project-draft/{draft['id']}/branches", headers=self.headers())
        self.assertEqual(len(listed.get_json()['branches']), 1)

        # The branch works on its own copy.
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': branch_draft_id,
            'draftData': {'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني',
                          'city_code': 'RUH'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft'})

        preview = client.get(f"/api/project-draft/{draft['id']}/branches/{branch['id']}/preview",
                             headers=self.headers())
        self.assertEqual(preview.status_code, 200, preview.get_json())
        self.assertEqual(preview.get_json()['conflicts'], [])

        merged = client.post(f"/api/project-draft/{draft['id']}/branches/{branch['id']}/merge",
                             headers=self.headers(), json={'resolutions': []})
        self.assertEqual(merged.status_code, 200, merged.get_json())
        self.assertTrue(merged.get_json()['merged'])

        stored = self.draft(client)
        self.assertEqual(stored['draft_data']['city_code'], 'RUH')

        commits = client.get(f"/api/project-draft/{draft['id']}/commits",
                             headers=self.headers()).get_json()['commits']
        self.assertEqual(commits[0]['kind'], 'merge')

    def test_a_conflicting_merge_is_refused_until_it_is_resolved(self):
        client = self.app.test_client()
        draft = self.draft(client)
        created = client.post(f"/api/project-draft/{draft['id']}/branches", headers=self.headers(),
                               json={'name': 'فرع الموقع'}).get_json()
        branch = created['branch']
        branch_draft_id = created['branchDraftId']

        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'],
            'draftData': {'project_name': 'اسم المشروع', 'city': 'الرياض', 'project_type': 'سكني'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft'})
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': branch_draft_id,
            'draftData': {'project_name': 'اسم الفرع', 'city': 'الرياض', 'project_type': 'سكني'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft'})

        refused = client.post(f"/api/project-draft/{draft['id']}/branches/{branch['id']}/merge",
                               headers=self.headers(), json={'resolutions': []})
        self.assertEqual(refused.status_code, 409, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'MERGE_CONFLICTS_UNRESOLVED')
        self.assertEqual([item['key'] for item in refused.get_json()['conflicts']], ['project_name'])

        resolved = client.post(f"/api/project-draft/{draft['id']}/branches/{branch['id']}/merge",
                                headers=self.headers(), json={
                                    'resolutions': [{'key': 'project_name', 'choice': 'theirs'}]})
        self.assertEqual(resolved.status_code, 200, resolved.get_json())
        self.assertEqual(self.draft(client)['draft_data']['project_name'], 'اسم الفرع')

    def test_a_branch_of_another_company_is_not_reachable(self):
        client = self.app.test_client()
        draft = self.draft(client)
        created = client.post(f"/api/project-draft/{draft['id']}/branches", headers=self.headers(),
                               json={'name': 'فرع الموقع'}).get_json()
        branch = created['branch']

        with self.app.app_context():
            other = db.create_tenant('Company B', 'b@example.test', 'hash-b', 'company-b')
        other_token = auth.create_token(
            other, 'b@example.test', user_id=None, user_name='Company B', user_role='company_admin'
        )
        refused = client.get(f"/api/project-draft/{draft['id']}/branches/{branch['id']}/preview",
                             headers={'Authorization': f'Bearer {other_token}'})
        self.assertEqual(refused.status_code, 404, refused.get_json())


if __name__ == '__main__':
    unittest.main()
