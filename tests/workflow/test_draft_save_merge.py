"""A save that lost the race merges instead of overwriting the newer work.

Covers the server side of the last gap in the version workflow: two people
save the same project file at the same time, and the second save must not
throw the first one's work away. The base is rebuilt from the commit chain
(the client only sends the revision it saved against), the fields only the
incoming side changed come over, and the fields both sides changed are a
conflict the caller decides on.

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


class DraftSaveMergeDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'draft-save-merge.db')
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

    def test_the_base_is_rebuilt_from_the_commit_chain(self):
        """The client only knows its revision; the chain holds the states."""
        db.save_project_draft('tenant-1', 'user-1',
                              {'project_name': 'برج المشرق', 'city': 'الرياض',
                               'project_type': 'سكني', 'project_idea': 'فكرة'},
                              {'basic': 'draft'}, 'draft', draft_id='draft-1')
        base_commit = db.draft_commit_at_or_before_revision('tenant-1', 'draft-1', 1)
        self.assertIsNotNone(base_commit)
        state, _meta = db.draft_state_at_commit('tenant-1', 'draft-1', base_commit)
        self.assertEqual(state['project_name'], 'برج المشرق')
        self.assertNotIn('project_idea', state)

    def test_a_lost_save_merges_with_the_newer_work(self):
        """The other side's field survives the save that lost the race."""
        base_revision = int((db.get_project_draft_by_id('tenant-1', 'draft-1') or {}).get('revision') or 0)
        # The other side saved first.
        db.save_project_draft('tenant-1', 'user-2',
                              {'project_name': 'برج المشرق', 'city': 'الرياض',
                               'project_type': 'سكني', 'project_idea': 'فكرة الزميل'},
                              {'basic': 'draft'}, 'draft', draft_id='draft-1')
        # This side saved against the revision it loaded.
        incoming = {'project_name': 'برج المشرق', 'city': 'جدة',
                    'project_type': 'سكني', 'project_idea': 'فكرة الزميل'}

        merged, changes, conflicts = db.draft_merge_preview_for_save(
            'tenant-1', 'draft-1', base_revision, incoming)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged['project_idea'], 'فكرة الزميل')
        self.assertEqual(merged['city'], 'جدة')
        self.assertEqual({item['key'] for item in changes}, {'city'})

    def test_a_field_both_sides_changed_is_a_conflict(self):
        """The same field changed twice needs a decision, not a silent winner."""
        base_revision = int((db.get_project_draft_by_id('tenant-1', 'draft-1') or {}).get('revision') or 0)
        db.save_project_draft('tenant-1', 'user-2',
                              {'project_name': 'اسم الزميل', 'city': 'الرياض', 'project_type': 'سكني'},
                              {'basic': 'draft'}, 'draft', draft_id='draft-1')
        incoming = {'project_name': 'اسمي', 'city': 'الرياض', 'project_type': 'سكني'}

        merged, _changes, conflicts = db.draft_merge_preview_for_save(
            'tenant-1', 'draft-1', base_revision, incoming)
        self.assertEqual([item['key'] for item in conflicts], ['project_name'])
        _resolved, unresolved = db.apply_merge_resolutions(merged, conflicts, [])
        self.assertEqual([item['key'] for item in unresolved], ['project_name'])

        resolved, unresolved = db.apply_merge_resolutions(
            merged, conflicts, [{'key': 'project_name', 'choice': 'ours'}])
        self.assertEqual(unresolved, [])
        self.assertEqual(resolved['project_name'], 'اسم الزميل')

    def test_the_slides_belong_to_the_incoming_session(self):
        """The slide deck and the chat are the session's own, never a conflict."""
        base_revision = int((db.get_project_draft_by_id('tenant-1', 'draft-1') or {}).get('revision') or 0)
        db.save_project_draft('tenant-1', 'user-2',
                              {'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني',
                               'tenantSlidesData': [{'html': '<div>شريحة الزميل</div>'}]},
                              {'basic': 'draft'}, 'draft', draft_id='draft-1')
        incoming = {'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني',
                    'tenantSlidesData': [{'html': '<div>شريحتي</div>'}]}

        merged, _changes, conflicts = db.draft_merge_preview_for_save(
            'tenant-1', 'draft-1', base_revision, incoming,
            prefer_theirs=('tenantSlidesData',))
        self.assertEqual(conflicts, [])
        self.assertEqual(merged['tenantSlidesData'], [{'html': '<div>شريحتي</div>'}])

    def _save_large_value(self, value, extra=None):
        payload = {'project_name': 'برج المشرق', 'city': 'الرياض',
                   'project_type': 'سكني', 'financial_study_model': value}
        payload.update(extra or {})
        db.save_project_draft('tenant-1', 'user-1', payload, {'basic': 'draft'},
                              'draft', draft_id='draft-1')
        return int((db.get_project_draft_by_id('tenant-1', 'draft-1') or {}).get('revision') or 0)

    def test_a_value_over_the_commit_cap_is_never_rewound_by_a_merge(self):
        """A 40KB section blob is skipped from the commit, but its digest still
        tells the merge that this side did not touch it."""
        large_old = {'blob': 'x' * 40000}
        large_new = {'blob': 'y' * 40000}
        base_revision = self._save_large_value(large_old)
        # The other side saves a newer financial study.
        db.save_project_draft('tenant-1', 'user-2',
                              {'project_name': 'برج المشرق', 'city': 'الرياض',
                               'project_type': 'سكني', 'financial_study_model': large_new},
                              {'basic': 'draft'}, 'draft', draft_id='draft-1')
        # This side only changed the city; its financial model is the older one.
        incoming = {'project_name': 'برج المشرق', 'city': 'جدة',
                    'project_type': 'سكني', 'financial_study_model': large_old}

        merged, changes, conflicts = db.draft_merge_preview_for_save(
            'tenant-1', 'draft-1', base_revision, incoming)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged['financial_study_model'], large_new,
                         'the newer financial study must survive the merge')
        self.assertEqual(merged['city'], 'جدة')
        self.assertEqual({item['key'] for item in changes}, {'city'})

    def test_two_sides_changing_a_value_over_the_cap_is_a_real_conflict(self):
        large_old = {'blob': 'x' * 40000}
        large_other = {'blob': 'y' * 40000}
        large_mine = {'blob': 'z' * 40000}
        base_revision = self._save_large_value(large_old)
        db.save_project_draft('tenant-1', 'user-2',
                              {'project_name': 'برج المشرق', 'city': 'الرياض',
                               'project_type': 'سكني', 'financial_study_model': large_other},
                              {'basic': 'draft'}, 'draft', draft_id='draft-1')
        incoming = {'project_name': 'برج المشرق', 'city': 'الرياض',
                    'project_type': 'سكني', 'financial_study_model': large_mine}

        _merged, _changes, conflicts = db.draft_merge_preview_for_save(
            'tenant-1', 'draft-1', base_revision, incoming)
        self.assertEqual([item['key'] for item in conflicts], ['financial_study_model'])
        self.assertTrue(conflicts[0].get('base_unverified'))

    def test_the_rebuilt_base_reports_the_digest_of_a_skipped_value(self):
        large_old = {'blob': 'x' * 40000}
        base_revision = self._save_large_value(large_old)
        commit = db.draft_commit_at_or_before_revision('tenant-1', 'draft-1', base_revision)
        _state, meta = db.draft_state_at_commit('tenant-1', 'draft-1', commit)
        self.assertIn('financial_study_model', meta['unverified_keys'])
        self.assertEqual(meta['digests']['financial_study_model'],
                         db._draft_commit_digest(large_old))


class DraftSaveMergeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'draft-save-merge-api.db')

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
            db.get_db().commit()
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftData': {'project_name': 'برج المشرق', 'city': 'الرياض', 'project_type': 'سكني'},
            'sectionStatuses': {'basic': 'draft'}, 'status': 'draft',
        })

    def draft(self, client):
        return client.get('/api/project-draft', headers=self.headers()).get_json()['draft']

    def test_a_stale_save_is_refused_until_it_asks_for_a_merge(self):
        client = self.app.test_client()
        draft = self.draft(client)
        stale_revision = int(draft.get('revision') or 0)

        # The other side saves first.
        other = dict(draft['draft_data'])
        other['project_idea'] = 'فكرة الزميل'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': other,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        mine = dict(draft['draft_data'])
        mine['city'] = 'جدة'
        refused = client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': mine,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft',
            'expectedRevision': stale_revision})
        self.assertEqual(refused.status_code, 409, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'DRAFT_REVISION_CONFLICT')

        merged = client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': mine,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft',
            'expectedRevision': stale_revision, 'mergeOnConflict': True})
        self.assertEqual(merged.status_code, 200, merged.get_json())
        self.assertTrue(merged.get_json()['merged'])

        stored = self.draft(client)['draft_data']
        self.assertEqual(stored['city'], 'جدة')
        self.assertEqual(stored['project_idea'], 'فكرة الزميل')

    def test_a_conflicting_save_asks_for_a_decision_and_then_merges(self):
        client = self.app.test_client()
        draft = self.draft(client)
        stale_revision = int(draft.get('revision') or 0)

        other = dict(draft['draft_data'])
        other['project_name'] = 'اسم الزميل'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': other,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        mine = dict(draft['draft_data'])
        mine['project_name'] = 'اسمي'
        asked = client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': mine,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft',
            'expectedRevision': stale_revision, 'mergeOnConflict': True})
        self.assertEqual(asked.status_code, 409, asked.get_json())
        self.assertEqual(asked.get_json()['error_code'], 'DRAFT_MERGE_CONFLICTS')
        self.assertEqual([item['key'] for item in asked.get_json()['conflicts']], ['project_name'])

        decided = client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': mine,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft',
            'expectedRevision': stale_revision, 'mergeOnConflict': True,
            'mergeResolutions': [{'key': 'project_name', 'choice': 'ours'}]})
        self.assertEqual(decided.status_code, 200, decided.get_json())
        self.assertTrue(decided.get_json()['merged'])
        self.assertEqual(self.draft(client)['draft_data']['project_name'], 'اسم الزميل')

    def test_a_merge_lands_as_a_commit_of_its_own(self):
        client = self.app.test_client()
        draft = self.draft(client)
        stale_revision = int(draft.get('revision') or 0)

        other = dict(draft['draft_data'])
        other['project_idea'] = 'فكرة الزميل'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': other,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft'})

        mine = dict(draft['draft_data'])
        mine['city'] = 'جدة'
        client.post('/api/project-draft', headers=self.headers(), json={
            'draftId': draft['id'], 'draftData': mine,
            'sectionStatuses': draft['section_statuses'], 'status': 'draft',
            'expectedRevision': stale_revision, 'mergeOnConflict': True})

        commits = client.get(f"/api/project-draft/{draft['id']}/commits",
                             headers=self.headers()).get_json()['commits']
        self.assertEqual(commits[0]['kind'], 'merge')
        self.assertEqual(commits[0]['changed_keys'], ['city'])

        # The merge is a save: it shows up in the project change log.
        log = client.get(f"/api/project-draft/{draft['id']}/edit-log",
                         headers=self.headers()).get_json()
        actions = [str(entry.get('action') or '') for entry in (log.get('log') or [])]
        self.assertTrue(actions, 'the merge wrote no change log entry')


class DraftMergeClientWiringTests(unittest.TestCase):
    """The browser side of the same contract: dirty edits gate the merge apply."""

    @classmethod
    def setUpClass(cls):
        import app as application_module
        parts = [(ROOT / 'index.html').read_text(encoding='utf-8')]
        for name in application_module.FRONTEND_JS_ORDER:
            parts.append((ROOT / 'assets' / 'js' / name).read_text(encoding='utf-8'))
        cls.source = '\n'.join(parts)

    def test_a_merge_clears_the_dirty_flag_and_applies_the_merged_state(self):
        start = self.source.index('if (resp && resp.success && resp.merged)')
        snippet = self.source[start:start + 1200]
        self.assertIn('applyLiveDraftSync(', snippet)
        self.assertIn('{ force: true }', snippet)
        self.assertIn('setDraftDirty(false)', snippet)

    def test_live_sync_never_applies_over_unsaved_edits(self):
        live = (ROOT / 'assets' / 'js' / '07-project-form' / '07_draft_live_sync.js').read_text(
            encoding='utf-8')
        self.assertIn('if (editing && !options.force)', live)
        self.assertIn('hydrateTenantProjectForm(draftData)', live)


if __name__ == '__main__':
    unittest.main()
