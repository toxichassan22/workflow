"""The autosave patch and its commit window.

A patch writes only the keys it carries, the rest of the file stays as it was,
and history waits for the window to close: one commit per window instead of one
per patch. Runs against a temporary SQLite database and never calls an AI API.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


class DraftAutosaveApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'draft-autosave.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Company Autosave', 'autosave@example.test',
                                          'hash-autosave', 'company-autosave')
        cls.token = auth.create_token(
            cls.tenant, 'autosave@example.test', user_id=None,
            user_name='Autosave Admin', user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def headers(self):
        return {'Authorization': 'Bearer ' + self.token}

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            conn = db.get_db()
            for table in ('draft_autosave_windows', 'draft_live_updates',
                          'draft_live_presence', 'draft_live_documents',
                          'draft_commits', 'project_drafts'):
                conn.execute('DELETE FROM ' + table)
            conn.commit()
        created = self.client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'project_name': 'برج المشرق', 'city': 'الرياض'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft',
        }).get_json()
        self.draft_id = created['draftId']
        self.revision = int(created['revision'] or 0)

    def autosave(self, patch, **kwargs):
        body = {'draftId': self.draft_id, 'baseRevision': self.revision,
                'patch': patch}
        body.update(kwargs)
        response = self.client.post('/api/project-draft/autosave',
                                    headers=self.headers(), json=body)
        data = response.get_json() or {}
        if data.get('success'):
            self.revision = int(data.get('revision') or self.revision)
        return response, data

    def stored_draft(self):
        response = self.client.get('/api/project-draft/' + self.draft_id,
                                   headers=self.headers())
        return response.get_json()['draft']

    def commits(self):
        with self.app.app_context():
            return db.list_draft_commits(self.tenant, self.draft_id)

    def test_a_patch_writes_only_the_keys_it_carries(self):
        """The rest of the file is not re-uploaded and is not touched."""
        response, data = self.autosave({'city': 'جدة'})
        self.assertEqual(response.status_code, 200, data)
        self.assertTrue(data['windowOpen'])
        stored = self.stored_draft()
        self.assertEqual(stored['draft_data']['city'], 'جدة')
        self.assertEqual(stored['draft_data']['project_name'], 'برج المشرق')
        self.assertEqual(stored['revision'], self.revision)

    def test_patches_do_not_mint_a_commit_each(self):
        """Two patches in one window leave the history untouched until it closes."""
        before = len(self.commits())
        self.autosave({'city': 'جدة'})
        self.autosave({'project_idea': 'فكرة جديدة'})
        self.assertEqual(len(self.commits()), before)

        _response, data = self.autosave({}, idle=True)
        self.assertTrue(data['committed'])
        self.assertFalse(data['windowOpen'])
        commits = self.commits()
        self.assertEqual(len(commits), before + 1)
        newest = commits[0]
        self.assertEqual(newest['kind'], 'autosave')
        self.assertEqual(sorted(newest['changed_keys']), ['city', 'project_idea'])

        with self.app.app_context():
            diff = db.draft_commit_diff(self.tenant, self.draft_id, newest['id'])
        changes = {item['key']: item for item in diff['changes']}
        self.assertEqual(changes['city']['from'], 'الرياض')
        self.assertEqual(changes['city']['to'], 'جدة')
        self.assertTrue(changes['project_idea']['deleted_from'])

    def test_an_autosave_commit_rebuilds_the_window_state(self):
        """The one commit of a window restores every key the window changed."""
        self.autosave({'city': 'جدة'})
        self.autosave({'project_idea': 'فكرة جديدة'})
        self.autosave({}, idle=True)
        commit_id = self.commits()[0]['id']
        with self.app.app_context():
            state, meta = db.draft_state_at_commit(self.tenant, self.draft_id, commit_id)
        self.assertNotIn('error', meta)
        self.assertEqual(state['city'], 'جدة')
        self.assertEqual(state['project_idea'], 'فكرة جديدة')
        self.assertEqual(state['project_name'], 'برج المشرق')

    def test_a_stale_base_revision_is_refused(self):
        """A patch built on an older revision cannot land on the newer file."""
        stale = self.revision
        self.autosave({'city': 'جدة'})
        response, data = self.autosave({'city': 'الدمام'}, baseRevision=stale)
        self.assertEqual(response.status_code, 409, data)
        self.assertEqual(data['error_code'], 'DRAFT_REVISION_CONFLICT')
        self.assertEqual(self.stored_draft()['draft_data']['city'], 'جدة')

    def test_ai_events_close_and_pin_the_window(self):
        """The states around an AI generation are kept forever."""
        response, data = self.autosave({'city': 'جدة'}, event='ai_before')
        self.assertEqual(response.status_code, 200, data)
        self.assertTrue(data['pinned'])
        self.assertTrue(data['committed'])
        commit = self.commits()[0]
        self.assertEqual(commit['kind'], 'ai_before')
        self.assertEqual(int(commit['pinned']), 1)

        self.autosave({'project_name': 'برج المشرق المحدّث'}, event='ai_after')
        commit = self.commits()[0]
        self.assertEqual(commit['kind'], 'ai_after')
        self.assertEqual(int(commit['pinned']), 1)

    def test_a_new_project_can_start_from_autosave(self):
        """A draft that does not exist yet is created by its first patch."""
        response = self.client.post('/api/project-draft/autosave',
                                    headers=self.headers(), json={
                                        'patch': {'project_name': 'مشروع جديد'},
                                        'baseRevision': 0,
                                    })
        data = response.get_json() or {}
        self.assertEqual(response.status_code, 200, data)
        self.assertTrue(data['draftId'])
        stored = self.client.get('/api/project-draft/' + data['draftId'],
                                 headers=self.headers()).get_json()['draft']
        self.assertEqual(stored['draft_data']['project_name'], 'مشروع جديد')

    def test_a_client_generated_id_creates_the_new_draft(self):
        """A new project already carries an id from the browser; it is not a 404."""
        response = self.client.post('/api/project-draft/autosave',
                                    headers=self.headers(), json={
                                        'draftId': 'new-draft-autosave-1',
                                        'baseRevision': 0,
                                        'patch': {'project_name': 'مشروع عميل'},
                                    })
        data = response.get_json() or {}
        self.assertEqual(response.status_code, 200, data)
        self.assertEqual(data['draftId'], 'new-draft-autosave-1')

    def test_an_empty_patch_is_refused(self):
        response, data = self.autosave({})
        self.assertEqual(response.status_code, 400, data)

    def test_an_expired_window_closes_before_a_new_one_opens(self):
        """A window left open by a closed tab still becomes one commit."""
        with self.app.app_context():
            db.autosave_window_begin(self.tenant, self.draft_id, self.revision,
                                     {'project_name': 'برج المشرق', 'city': 'الرياض'},
                                     ['city'])
            conn = db.get_db()
            conn.execute(
                "UPDATE draft_autosave_windows SET started_at = ?, last_save_at = ? "
                "WHERE draft_id = ?",
                ('2020-01-01T00:00:00', '2020-01-01T00:00:00', self.draft_id))
            conn.commit()
        response, data = self.autosave({'city': 'جدة'})
        self.assertEqual(response.status_code, 200, data)
        commits = self.commits()
        self.assertTrue(any(commit['kind'] == 'autosave' for commit in commits))


if __name__ == '__main__':
    unittest.main()
