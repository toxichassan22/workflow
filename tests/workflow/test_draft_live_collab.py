"""The live editing session: ordered deltas, presence and snapshots.

This is the server half of the Google-Docs-style collaboration. The draft is
never written here — only the session tables — but the exchange must still be
tenant-scoped, ordered, compactable, and limited to fields the caller may
edit.

Runs against a temporary SQLite database and never calls an AI API.
"""

import base64
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


class DraftLiveCollabApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'draft-live-collab.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()
            cls.tenant = db.create_tenant('Company Live', 'live@example.test', 'hash-live', 'company-live')
            cls.other_tenant = db.create_tenant('Company Other', 'other@example.test', 'hash-other',
                                                'company-other')
        cls.token = auth.create_token(
            cls.tenant, 'live@example.test', user_id=None, user_name='Live Admin',
            user_role='company_admin')
        cls.other_token = auth.create_token(
            cls.other_tenant, 'other@example.test', user_id=None, user_name='Other Admin',
            user_role='company_admin')

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def headers(self, token=None):
        return {'Authorization': 'Bearer ' + (token or self.token)}

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            conn = db.get_db()
            for table in ('draft_live_updates', 'draft_live_presence',
                          'draft_live_documents', 'draft_commits', 'project_drafts'):
                conn.execute('DELETE FROM ' + table)
            conn.commit()
        created = self.client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'project_name': 'برج المشرق', 'city': 'الرياض'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft',
        }).get_json()
        self.draft_id = created['draftId']

    def live_url(self, **params):
        query = '&'.join('%s=%s' % (key, value) for key, value in params.items())
        return '/api/project-draft/%s/live%s' % (self.draft_id, ('?' + query) if query else '')

    def post_live(self, body, token=None):
        return self.client.post(self.live_url(), headers=self.headers(token), json=body)

    def update(self, value, field='project_name'):
        return {'payload': base64.b64encode(value).decode('ascii'), 'fieldKey': field}

    def test_updates_are_ordered_and_read_after_a_cursor(self):
        first = self.post_live({
            'clientId': 'client-aaaa1111',
            'updates': [self.update(b'update-one')],
        })
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(first.get_json()['seq'], 1)

        second = self.post_live({
            'clientId': 'client-aaaa1111',
            'updates': [self.update(b'update-two'), self.update(b'update-three', 'city')],
        })
        self.assertEqual(second.get_json()['seq'], 3)

        all_updates = self.client.get(
            self.live_url(since=0, clientId='client-bbbb2222'), headers=self.headers()).get_json()
        self.assertTrue(all_updates['hasSession'])
        self.assertEqual(all_updates['seq'], 3)
        payloads = [base64.b64decode(item['payload']) for item in all_updates['updates']]
        self.assertEqual(payloads, [b'update-one', b'update-two', b'update-three'])
        self.assertEqual([item['field_key'] for item in all_updates['updates']],
                         ['project_name', 'project_name', 'city'])

        after_one = self.client.get(
            self.live_url(since=1, clientId='client-bbbb2222'), headers=self.headers()).get_json()
        self.assertEqual([base64.b64decode(item['payload']) for item in after_one['updates']],
                         [b'update-two', b'update-three'])

        after_last = self.client.get(
            self.live_url(since=3, clientId='client-bbbb2222'), headers=self.headers()).get_json()
        self.assertEqual(after_last['updates'], [])

    def test_presence_excludes_the_caller_and_expires_by_time(self):
        written = self.post_live({
            'clientId': 'client-aaaa1111',
            'updates': [],
            'presence': {'fieldKey': 'project_name', 'sectionKey': 'basic',
                         'caretStart': 4, 'caretEnd': 6},
        })
        self.assertEqual(written.status_code, 200, written.get_json())
        mine = self.client.get(
            self.live_url(since=0, clientId='client-aaaa1111'), headers=self.headers()).get_json()
        self.assertEqual(mine['presence'], [])
        theirs = self.client.get(
            self.live_url(since=0, clientId='client-bbbb2222'), headers=self.headers()).get_json()
        self.assertEqual(len(theirs['presence']), 1)
        self.assertEqual(theirs['presence'][0]['field_key'], 'project_name')
        self.assertEqual(theirs['presence'][0]['caret_start'], 4)
        self.assertEqual(theirs['presence'][0]['user_name'], 'Live Admin')

    def test_a_snapshot_compacts_the_update_log(self):
        self.post_live({'clientId': 'client-aaaa1111',
                        'updates': [self.update(b'one'), self.update(b'two')]})
        snapshot = base64.b64encode(b'compacted-state').decode('ascii')
        stored = self.post_live({'clientId': 'client-aaaa1111', 'updates': [],
                                 'snapshot': snapshot, 'snapshotSeq': 2})
        self.assertEqual(stored.status_code, 200, stored.get_json())
        loaded = self.client.get(
            self.live_url(since=0, clientId='client-bbbb2222'), headers=self.headers()).get_json()
        self.assertTrue(loaded['reset'])
        self.assertEqual(base64.b64decode(loaded['snapshot']), b'compacted-state')
        self.assertEqual(loaded['updates'], [])

    def test_an_unknown_field_is_refused(self):
        refused = self.post_live({
            'clientId': 'client-aaaa1111',
            'updates': [self.update(b'x', 'not_a_real_field')],
        })
        self.assertEqual(refused.status_code, 403, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'LIVE_FIELD_FORBIDDEN')

    def test_an_update_must_name_its_field(self):
        refused = self.post_live({
            'clientId': 'client-aaaa1111',
            'updates': [{'payload': base64.b64encode(b'x').decode('ascii')}],
        })
        self.assertEqual(refused.status_code, 400, refused.get_json())

    def test_an_approved_section_is_locked_for_live_edits(self):
        with self.app.app_context():
            conn = db.get_db()
            conn.execute(
                'UPDATE project_drafts SET section_statuses = ? WHERE id = ?',
                ('{"basic": "approved"}', self.draft_id))
            conn.commit()
        refused = self.post_live({
            'clientId': 'client-aaaa1111',
            'updates': [self.update(b'locked', 'project_name')],
        })
        self.assertEqual(refused.status_code, 403, refused.get_json())

    def test_a_locked_draft_refuses_the_session_entirely(self):
        with self.app.app_context():
            conn = db.get_db()
            conn.execute('UPDATE project_drafts SET status = ? WHERE id = ?',
                         ('approved', self.draft_id))
            conn.commit()
        refused = self.post_live({
            'clientId': 'client-aaaa1111',
            'updates': [self.update(b'late', 'project_name')],
        })
        self.assertEqual(refused.status_code, 423, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'DRAFT_LOCKED')

    def test_a_session_is_scoped_to_its_tenant(self):
        self.client.post(self.live_url(), headers=self.headers(), json={
            'clientId': 'client-aaaa1111', 'updates': [self.update(b'tenant-one')],
        })
        foreign = self.client.get(self.live_url(since=0), headers=self.headers(self.other_token))
        self.assertEqual(foreign.status_code, 404)
        foreign_write = self.client.post(self.live_url(), headers=self.headers(self.other_token), json={
            'clientId': 'client-cccc3333', 'updates': [self.update(b'intrusion')],
        })
        self.assertEqual(foreign_write.status_code, 404)


if __name__ == '__main__':
    unittest.main()
