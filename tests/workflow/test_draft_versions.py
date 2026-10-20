"""The project version history — every save is a version, and an older one can
be restored (the GitHub-style workflow the owner asked for).

Covers the commit store in db (one commit per save, the chain of parents, the
rebuild of an older payload, the skip of a value too large to keep) and the
three routes in app_parts/12_drafts/12c_draft_commits.py (list, inspect,
restore). Runs against a temporary SQLite database and never calls an AI API.
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


class DraftCommitStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'draft-versions.db')
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

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def save(self, payload, draft_id='draft-1', **kwargs):
        return db.save_project_draft('tenant-1', 'user-1', payload, {}, 'draft',
                                     draft_id=draft_id, **kwargs)

    def test_every_save_leaves_a_commit_behind(self):
        """Two saves, two versions, and the second one points at the first."""
        self.save({'project_name': 'برج المشرق', 'city': 'الرياض'})
        self.save({'project_name': 'برج المشرق الثاني', 'city': 'الرياض'})

        commits = db.list_draft_commits('tenant-1', 'draft-1')
        self.assertEqual(len(commits), 2)
        newest, oldest = commits
        self.assertEqual(newest['parent_id'], oldest['id'])
        self.assertEqual(newest['changed_keys'], ['project_name'])
        self.assertEqual(newest['revision'], 2)

    def test_an_older_version_is_rebuilt_after_a_newer_save(self):
        """The work an overwrite replaced stays readable in the history."""
        self.save({'project_name': 'برج المشرق', 'city': 'الرياض'})
        first = db.list_draft_commits('tenant-1', 'draft-1')[0]
        self.save({'project_name': 'اسم أحدث', 'city': 'الرياض'})

        state, meta = db.draft_state_at_commit('tenant-1', 'draft-1', first['id'])
        self.assertEqual(state['project_name'], 'برج المشرق')
        self.assertEqual(state['city'], 'الرياض')
        self.assertNotIn('error', meta)

    def test_a_key_added_later_is_absent_from_the_older_version(self):
        """A field that did not exist yet cannot appear in an older version."""
        self.save({'project_name': 'برج المشرق'})
        first = db.list_draft_commits('tenant-1', 'draft-1')[0]
        self.save({'project_name': 'برج المشرق', 'city': 'الرياض'})

        state, _meta = db.draft_state_at_commit('tenant-1', 'draft-1', first['id'])
        self.assertNotIn('city', state)

    def test_a_refused_save_leaves_no_commit(self):
        """A write the database refuses never shows up in the history."""
        self.save({'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني'})
        before = len(db.list_draft_commits('tenant-1', 'draft-1'))

        with self.assertRaises(db.DraftOverwriteRefused):
            self.save({})
        with self.assertRaises(db.DraftRevisionConflict):
            self.save({'project_name': 'اسم آخر'}, expected_revision=99)

        self.assertEqual(len(db.list_draft_commits('tenant-1', 'draft-1')), before)

    def test_a_value_too_large_to_keep_is_named_not_stored(self):
        """An inline image is not copied into the history, and it is reported."""
        self.save({'project_name': 'برج المشرق'})
        first = db.list_draft_commits('tenant-1', 'draft-1')[0]
        huge = 'x' * (db.DRAFT_COMMIT_MAX_VALUE_BYTES + 10)
        self.save({'project_name': 'برج المشرق', 'tenantCreativeImages': huge})

        newest = db.list_draft_commits('tenant-1', 'draft-1')[0]
        self.assertIn('tenantCreativeImages', newest['skipped_keys'])
        self.assertNotIn('tenantCreativeImages', newest['changed_keys'])
        _state, meta = db.draft_state_at_commit('tenant-1', 'draft-1', first['id'])
        self.assertIn('tenantCreativeImages', meta['skipped_keys'])

    def test_the_table_arrives_on_an_existing_database(self):
        """A table added after the first install must exist on old databases."""
        conn = db.get_db()
        conn.execute('DROP TABLE IF EXISTS draft_commits')
        conn.commit()
        db.init_db()

        self.save({'project_name': 'برج المشرق'})
        self.assertEqual(len(db.list_draft_commits('tenant-1', 'draft-1')), 1)

    def test_another_tenant_reads_nothing(self):
        """The history is tenant-scoped like every other draft read."""
        self.save({'project_name': 'برج المشرق'})
        commit = db.list_draft_commits('tenant-1', 'draft-1')[0]
        self.assertEqual(db.list_draft_commits('tenant-2', 'draft-1'), [])
        self.assertIsNone(db.get_draft_commit('tenant-2', 'draft-1', commit['id']))
        state, meta = db.draft_state_at_commit('tenant-2', 'draft-1', commit['id'])
        self.assertIsNone(state)
        self.assertEqual(meta.get('error'), 'commit_not_found')


class DraftVersionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'draft-versions-api.db')

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
            db.get_db().commit()
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'project_name': 'برج المشرق', 'city': 'الرياض'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft',
        })

    def draft(self, client):
        return client.get('/api/project-draft', headers=self.headers()).get_json()['draft']

    def test_the_version_chain_is_listed_with_its_author(self):
        client = self.app.test_client()
        draft = self.draft(client)
        changed = dict(draft['draft_data'])
        changed['project_name'] = 'برج المشرق الثاني'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        listed = client.get(f"/api/project-draft/{draft['id']}/commits", headers=self.headers())
        self.assertEqual(listed.status_code, 200, listed.get_json())
        commits = listed.get_json()['commits']
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]['changed_keys'], ['project_name'])
        self.assertEqual(commits[0]['author_name'], 'Company A')
        self.assertTrue(commits[0]['created_at'])

    def test_restoring_an_older_version_keeps_the_whole_history(self):
        """The restore brings the old values back and adds a version of its own."""
        client = self.app.test_client()
        draft = self.draft(client)
        first = client.get(f"/api/project-draft/{draft['id']}/commits",
                            headers=self.headers()).get_json()['commits'][-1]

        changed = dict(draft['draft_data'])
        changed['project_name'] = 'اسم أحدث'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        restored = client.post(f"/api/project-draft/{draft['id']}/commits/{first['id']}/restore",
                               headers=self.headers(), json={})
        self.assertEqual(restored.status_code, 200, restored.get_json())
        self.assertTrue(restored.get_json()['restored'])

        stored = self.draft(client)
        self.assertEqual(stored['draft_data']['project_name'], 'برج المشرق')

        commits = client.get(f"/api/project-draft/{draft['id']}/commits",
                             headers=self.headers()).get_json()['commits']
        self.assertEqual(len(commits), 3)
        self.assertEqual(commits[0]['kind'], 'restore')
        self.assertEqual(commits[0]['changed_keys'], ['project_name'])

    def test_restoring_a_version_of_another_company_is_refused(self):
        client = self.app.test_client()
        draft = self.draft(client)
        commit = client.get(f"/api/project-draft/{draft['id']}/commits",
                            headers=self.headers()).get_json()['commits'][0]

        refused = client.post(f"/api/project-draft/{draft['id']}/commits/{commit['id']}/restore",
                               headers=self.headers(self.other_token), json={})
        self.assertEqual(refused.status_code, 404, refused.get_json())

    def test_the_commit_detail_names_what_changed(self):
        client = self.app.test_client()
        draft = self.draft(client)
        changed = dict(draft['draft_data'])
        changed['project_name'] = 'برج المشرق الثاني'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': changed,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        commits = client.get(f"/api/project-draft/{draft['id']}/commits",
                             headers=self.headers()).get_json()['commits']
        detail = client.get(f"/api/project-draft/{draft['id']}/commits/{commits[0]['id']}",
                            headers=self.headers())
        self.assertEqual(detail.status_code, 200, detail.get_json())
        changes = detail.get_json()['commit']['changes']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['key'], 'project_name')
        self.assertEqual(changes[0]['from'], 'برج المشرق')
        self.assertEqual(changes[0]['to'], 'برج المشرق الثاني')


if __name__ == '__main__':
    unittest.main()
