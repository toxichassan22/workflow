"""Focused database-only tests: no app import, network, or real database access."""
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from flask import Flask

import db


class PresentationRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp.name, 'revisions.sqlite')
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        conn = db.get_db()
        db._create_tables(conn)
        for tenant in ('tenant-a', 'tenant-b'):
            conn.execute('INSERT INTO tenants (id, company_name, email, password_hash) VALUES (?, ?, ?, ?)',
                         (tenant, tenant, tenant + '@example.test', 'test-only'))
        conn.commit()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_path
        self.temp.cleanup()

    def create(self, **kwargs):
        fields = dict(title='Original', slides_data=[{'html': '<div>Before</div>'}],
                      project_data={'project_name': 'Project', 'city': 'Riyadh'},
                      user_id='author', user_name='Author')
        fields.update(kwargs)
        return db.commit_presentation_revision('tenant-a', **fields)

    def revision(self, result):
        return db.get_presentation_revision(result['presentation_id'], result['version_id'], 'tenant-a')

    def count(self, table):
        return db.get_db().execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n']

    def test_create_snapshots_full_state_and_links_readable_history(self):
        created = self.create()
        self.assertEqual(created['revision'], 1)
        self.assertTrue(created['created'])
        snapshot = self.revision(created)
        self.assertEqual(snapshot['title'], 'Original')
        self.assertEqual(json.loads(snapshot['project_data'])['city'], 'Riyadh')
        self.assertEqual(snapshot['slide_count'], 1)
        self.assertEqual(snapshot['user_id'], 'author')
        self.assertEqual(snapshot['snapshot_kind'], 'full')
        self.assertFalse(snapshot['legacy'])
        history = db.get_change_log('tenant-a', 'presentation', created['presentation_id'])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['id'], snapshot['change_log_id'])
        self.assertEqual(history[0]['revision_id'], created['version_id'])
        self.assertEqual(history[0]['revision'], 1)
        self.assertTrue(history[0]['summary'])

    def test_update_is_sequential_and_never_mutates_prior_snapshot(self):
        first = self.create()
        original = self.revision(first)
        second = db.commit_presentation_revision('tenant-a', first['presentation_id'],
            expected_revision=1, title='Renamed', project_data={'city': 'Jeddah'},
            slides_data=[], user_id='editor', user_name='Editor', source='ai')
        self.assertEqual(second['revision'], 2)
        self.assertEqual(self.revision(first), original)
        self.assertEqual(self.revision(second)['previous_revision_id'], first['version_id'])
        self.assertEqual(self.revision(second)['source'], 'ai')
        self.assertEqual(second['presentation']['slide_count'], 0)
        self.assertEqual([r['revision'] for r in db.get_presentation_revisions(first['presentation_id'], 'tenant-a')], [2, 1])

    def test_unchanged_json_and_bookkeeping_are_deduplicated(self):
        first = self.create()
        before = self.revision(first)
        result = db.commit_presentation_revision('tenant-a', first['presentation_id'], expected_revision=1,
            project_data='{"city":"Riyadh","project_name":"Project","designerChat":{"turns":["hi"]},"pageDrafts":{}}')
        self.assertFalse(result['changed'])
        self.assertEqual(result['version_id'], first['version_id'])
        self.assertEqual(result['revision'], 1)
        self.assertEqual(self.count('change_log'), 1)
        self.assertEqual(self.revision(first), before)
        self.assertIn('designerChat', json.loads(result['presentation']['project_data']))
        # Real project inputs and maps are not bookkeeping.
        changed = db.commit_presentation_revision('tenant-a', first['presentation_id'], expected_revision=1,
            project_data={'city': 'Riyadh', 'project_name': 'Project', 'map_type': 'terrain'})
        self.assertEqual(changed['revision'], 2)

    def test_stale_noop_conflicts_without_writes(self):
        first = self.create()
        with self.assertRaises(db.PresentationRevisionConflict) as raised:
            db.commit_presentation_revision('tenant-a', first['presentation_id'], title='Original', expected_revision=0)
        self.assertEqual(raised.exception.current_revision, 1)
        self.assertEqual(raised.exception.expected_revision, 0)
        self.assertEqual(self.count('presentation_revisions'), 1)
        self.assertEqual(self.count('change_log'), 1)

    def test_restore_full_state_as_new_revision_keeps_identity_and_current_draft(self):
        first = self.create(draft_id='old-project', status='approved')
        second = db.commit_presentation_revision('tenant-a', first['presentation_id'], expected_revision=1,
            title='New title', slides_data=[{'html': 'After'}], project_data={'city': 'New'},
            draft_id='current-project', status='approved')
        before = self.revision(first)
        restored = db.commit_presentation_revision('tenant-a', first['presentation_id'], expected_revision=2,
            restore_version_id=first['version_id'], user_id='restorer', source='manual')
        self.assertEqual(restored['revision'], 3)
        self.assertEqual(restored['presentation_id'], first['presentation_id'])
        self.assertEqual(restored['presentation']['title'], 'Original')
        self.assertEqual(restored['presentation']['draft_id'], 'current-project')
        self.assertEqual(restored['presentation']['status'], 'draft')
        self.assertEqual(restored['presentation']['project_data'], before['project_data'])
        snapshot = self.revision(restored)
        self.assertEqual(snapshot['previous_revision_id'], second['version_id'])
        self.assertEqual(snapshot['restored_from_revision_id'], first['version_id'])
        self.assertEqual(self.revision(first), before)
        # Explicit restore is meaningful history even when content is already identical.
        again = db.commit_presentation_revision('tenant-a', first['presentation_id'], expected_revision=3,
            restore_version_id=first['version_id'])
        self.assertEqual(again['revision'], 4)
        self.assertEqual(self.count('presentations'), 1)
        self.assertEqual(self.count('project_drafts'), 0)

    def test_content_edit_releases_approval_by_default(self):
        first = self.create(status='approved')
        result = db.commit_presentation_revision('tenant-a', first['presentation_id'], title='Changed', expected_revision=1)
        self.assertEqual(result['presentation']['status'], 'draft')
        self.assertEqual(self.revision(first)['status'], 'approved')

    def test_existing_current_baseline_has_unknown_actor_and_is_restorable(self):
        identity = db.create_presentation('tenant-a', 'Legacy current', {'city': 'Old'}, [{'html': 'Old'}], 1)
        updated = db.commit_presentation_revision('tenant-a', identity, title='Changed', expected_revision=0,
                                                   user_id='current-editor', user_name='Current editor')
        versions = db.get_presentation_revisions(identity, 'tenant-a')
        self.assertEqual([v['revision'] for v in versions], [1, 0])
        baseline = versions[1]
        self.assertEqual(baseline['action'], 'baseline')
        self.assertEqual(baseline['source'], 'system')
        self.assertIsNone(baseline['user_id'])
        self.assertIsNone(baseline['user_name'])
        restored = db.commit_presentation_revision('tenant-a', identity, expected_revision=updated['revision'],
                                                   restore_version_id=baseline['id'])
        self.assertEqual(restored['presentation']['title'], 'Legacy current')

    def test_legacy_slides_only_versions_remain_labeled_and_restorable(self):
        first = self.create()
        legacy_id = db.save_presentation_version(first['presentation_id'], 'old-editor', 'Old editor',
                                                  [{'html': 'Old legacy slide'}])
        old_helper = db.get_presentation_version(legacy_id)
        legacy = db.get_presentation_revision(first['presentation_id'], legacy_id, 'tenant-a')
        self.assertTrue(legacy['legacy'])
        self.assertEqual(legacy['snapshot_kind'], 'legacy-slides')
        self.assertIsNone(legacy['project_data'])
        self.assertIsNone(legacy['revision'])
        restored = db.commit_presentation_revision('tenant-a', first['presentation_id'],
            expected_revision=1, restore_version_id=legacy_id)
        self.assertEqual(restored['presentation']['title'], 'Original')
        self.assertEqual(json.loads(restored['presentation']['project_data'])['city'], 'Riyadh')
        self.assertEqual(json.loads(restored['presentation']['slides_data'])[0]['html'], 'Old legacy slide')
        self.assertEqual(db.get_presentation_version(legacy_id), old_helper)
        listed = db.get_presentation_revisions(first['presentation_id'], 'tenant-a')
        self.assertTrue(listed[-1]['legacy'])
        self.assertNotIn('slides_data', listed[-1])

    def test_tenant_scope_and_wrong_presentation_restore(self):
        first, other = self.create(), self.create(title='Other')
        legacy = db.save_presentation_version(first['presentation_id'], None, 'Old', [])
        for version in (first['version_id'], legacy):
            self.assertIsNone(db.get_presentation_revision(first['presentation_id'], version, 'tenant-b'))
            self.assertIsNone(db.get_presentation_revision(other['presentation_id'], version, 'tenant-a'))
            with self.assertRaises(LookupError):
                db.commit_presentation_revision('tenant-a', other['presentation_id'], restore_version_id=version)
        self.assertEqual(db.get_presentation_revisions(first['presentation_id'], 'tenant-b'), [])
        with self.assertRaises(LookupError):
            db.commit_presentation_revision('tenant-b', first['presentation_id'], title='Unauthorized')
        db.log_edit(first['presentation_id'], 'old', 'Old', 'edit', 'Old log')
        self.assertEqual(db.get_change_log('tenant-b', 'presentation', first['presentation_id']), [])

    def test_atomic_rollback_including_baseline_and_history(self):
        identity = db.create_presentation('tenant-a', 'Legacy', {}, [], 0)
        original = db._insert_presentation_revision
        def fail_after_insert(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('Injected transaction failure')
        with mock.patch.object(db, '_insert_presentation_revision', side_effect=fail_after_insert):
            with self.assertRaises(RuntimeError):
                db.commit_presentation_revision('tenant-a', identity, title='Lost', expected_revision=0)
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertEqual(self.count('presentations'), 1)
        self.assertEqual(self.count('presentation_revisions'), 0)
        self.assertEqual(self.count('change_log'), 0)
        self.assertEqual(db.get_presentation(identity, 'tenant-a')['title'], 'Legacy')

    def test_legacy_write_after_revision_is_preserved_before_next_change(self):
        first = self.create()
        db.update_presentation(first['presentation_id'], title='Legacy caller edit')
        result = db.commit_presentation_revision('tenant-a', first['presentation_id'], title='Next', expected_revision=1)
        versions = db.get_presentation_revisions(first['presentation_id'], 'tenant-a')
        self.assertEqual(result['revision'], 3)
        self.assertEqual(versions[1]['title'], 'Legacy caller edit')
        self.assertEqual(versions[1]['action'], 'baseline')
        self.assertIsNone(versions[1]['user_id'])

    def test_two_connections_same_base_exactly_one_commit(self):
        first = self.create()
        barrier = threading.Barrier(2)
        def writer(title):
            with self.app.app_context():
                try:
                    db.get_db()
                    barrier.wait(timeout=5)
                    return db.commit_presentation_revision('tenant-a', first['presentation_id'],
                                                           title=title, expected_revision=1)['revision']
                except db.PresentationRevisionConflict:
                    return 'conflict'
                finally:
                    db.close_db()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(writer, name) for name in ('First writer', 'Second writer')]
            results = [future.result(timeout=15) for future in futures]
        self.assertCountEqual(results, [2, 'conflict'])
        self.assertEqual(self.count('presentation_revisions'), 2)
        self.assertEqual(self.count('change_log'), 2)

    def test_migration_on_old_schema_is_idempotent_and_preserves_rows(self):
        conn = db.sqlite3.connect(os.path.join(self.temp.name, 'old.sqlite'))
        try:
            conn.execute('CREATE TABLE presentations (id TEXT PRIMARY KEY, tenant_id TEXT, title TEXT)')
            conn.execute('CREATE TABLE change_log (id TEXT PRIMARY KEY, details TEXT)')
            conn.execute("INSERT INTO presentations (id, tenant_id, title) VALUES ('old', 'tenant-a', 'Old')")
            conn.execute("INSERT INTO change_log (id, details) VALUES ('history', 'Old detail')")
            conn.commit()
            db._migrate_presentation_revision_schema(conn)
            db._migrate_presentation_revision_schema(conn)
            conn.commit()
            row = dict(conn.execute("SELECT * FROM presentations WHERE id = 'old'").fetchone())
            self.assertEqual(row['revision'], 0)
            self.assertIsNone(row['current_revision_id'])
            self.assertEqual(conn.execute("SELECT details FROM change_log WHERE id = 'history'").fetchone()['details'], 'Old detail')
        finally:
            conn.close()

    def test_snapshot_transform_freezes_legacy_baseline_and_restored_assets(self):
        identity = db.create_presentation('tenant-a', 'Legacy', {'image': '/mutable/old.png'},
                                          [{'html': '<img src="/mutable/old.png">'}], 1)
        calls = []
        def freeze(state):
            calls.append(state)
            state['project_data'] = json.loads((state['project_data'] or '{}').replace('/mutable/', '/frozen/'))
            state['slides_data'] = json.loads((state['slides_data'] or '[]').replace('/mutable/', '/frozen/'))
            # Identity/workflow fields cannot be redirected by the asset callback.
            state['draft_id'], state['status'], state['title'] = 'wrong', 'approved', 'wrong'
            return state
        result = db.commit_presentation_revision('tenant-a', identity, expected_revision=0,
            slides_data=[{'html': '<img src="/mutable/new.png">'}], snapshot_transform=freeze)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(isinstance(call['revision'], int) for call in calls))
        self.assertEqual(result['presentation']['title'], 'Legacy')
        self.assertEqual(result['presentation']['status'], 'draft')
        versions = db.get_presentation_revisions(identity, 'tenant-a')
        baseline = db.get_presentation_revision(identity, versions[-1]['id'], 'tenant-a')
        self.assertIn('/frozen/old.png', baseline['slides_data'])
        self.assertIn('/frozen/new.png', self.revision(result)['slides_data'])
        legacy_id = db.save_presentation_version(identity, None, 'Old', [{'html': '/mutable/legacy.png'}])
        restored = db.commit_presentation_revision('tenant-a', identity, expected_revision=1,
            restore_version_id=legacy_id, snapshot_transform=freeze)
        self.assertIn('/frozen/legacy.png', restored['presentation']['slides_data'])
        self.assertIn('/mutable/legacy.png', db.get_presentation_version(legacy_id)['slides_data'])
        repeated = db.commit_presentation_revision('tenant-a', identity, expected_revision=2,
            snapshot_transform=freeze)
        self.assertFalse(repeated['changed'])
        self.assertEqual(repeated['revision'], 2)

    def test_snapshot_transform_failure_rolls_back_and_stale_write_never_calls_it(self):
        first = self.create()
        with mock.patch.object(db, '_transform_presentation_snapshot', side_effect=RuntimeError('Copy failed')):
            with self.assertRaises(RuntimeError):
                db.commit_presentation_revision('tenant-a', first['presentation_id'], title='Not saved')
        self.assertEqual(db.get_presentation(first['presentation_id'])['title'], 'Original')
        transform = mock.Mock(side_effect=RuntimeError('Should not run'))
        with self.assertRaises(db.PresentationRevisionConflict):
            db.commit_presentation_revision('tenant-a', first['presentation_id'], expected_revision=0,
                                             snapshot_transform=transform)
        transform.assert_not_called()
        self.assertEqual(self.count('presentation_revisions'), 1)

    def test_legacy_noop_materializes_baseline_once_without_editor_attribution(self):
        identity = db.create_presentation('tenant-a', 'Legacy', {}, [], 0)
        first = db.commit_presentation_revision('tenant-a', identity, expected_revision=0,
                                                 user_id='editor', user_name='Editor')
        second = db.commit_presentation_revision('tenant-a', identity, expected_revision=0)
        self.assertFalse(first['changed'])
        self.assertFalse(second['changed'])
        self.assertEqual(first['version_id'], second['version_id'])
        self.assertEqual(second['revision'], 0)
        self.assertEqual(self.count('presentation_revisions'), 1)
        self.assertIsNone(self.revision(first)['user_id'])

    def test_create_relinks_draft_maps_without_editing_draft(self):
        conn = db.get_db()
        conn.execute('''INSERT INTO map_images (id, tenant_id, presentation_id, image_type, file_path, placeholder)
                        VALUES (?, ?, ?, ?, ?, ?)''', ('map-test', 'tenant-a', 'draft_project', 'overview', '/test.png', '##MAP_OVERVIEW##'))
        conn.commit()
        result = self.create(project_data={'draftId': 'project'})
        row = conn.execute("SELECT presentation_id FROM map_images WHERE id = 'map-test'").fetchone()
        self.assertEqual(row['presentation_id'], result['presentation_id'])
        self.assertEqual(result['presentation']['draft_id'], 'project')
        self.assertEqual(self.count('project_drafts'), 0)

    def test_noncontent_audit_links_current_revision_without_new_snapshot(self):
        first = self.create()
        for action in ('export', 'approve'):
            change_id = db.log_change('tenant-a', 'presentation', first['presentation_id'],
                'reviewer', 'Reviewer', action, summary='Event')
            event = next(row for row in db.get_change_log('tenant-a', 'presentation', first['presentation_id'])
                         if row['id'] == change_id)
            self.assertEqual(event['revision_id'], first['version_id'])
            self.assertEqual(event['revision'], 1)
        self.assertEqual(self.count('presentation_revisions'), 1)
        self.assertEqual(self.count('change_log'), 3)
        # Explicit event links can identify the older snapshot actually exported.
        second = db.commit_presentation_revision('tenant-a', first['presentation_id'], title='Changed')
        db.log_change('tenant-a', 'presentation', first['presentation_id'], None, None,
                      'export', summary='Old export', revision_id=first['version_id'])
        events = db.get_change_log('tenant-a', 'presentation', first['presentation_id'])
        self.assertEqual(events[0]['revision_id'], first['version_id'])
        self.assertEqual(db.get_presentation(first['presentation_id'])['revision'], second['revision'])

    def test_audit_rejects_foreign_revision_links_but_keeps_legacy_deleted_events(self):
        first, other = self.create(), self.create(title='Other')
        with self.assertRaises(ValueError):
            db.log_change('tenant-a', 'presentation', other['presentation_id'], None, None,
                          'export', summary='Invalid', revision_id=first['version_id'])
        with self.assertRaises(ValueError):
            db.log_change('tenant-b', 'presentation', first['presentation_id'], None, None,
                          'export', summary='Invalid', revision_id=first['version_id'])
        event = db.log_change('tenant-a', 'presentation', 'deleted-id', None, None, 'delete', summary='Deleted')
        self.assertIsNotNone(event)
        legacy = db.get_change_log('tenant-a', 'presentation', 'deleted-id')
        self.assertIsNone(legacy[0]['revision_id'])
        self.assertIsNotNone(db.log_change('tenant-a', 'draft', 'draft-id', None, None, 'save', summary='Draft'))

    def test_creation_key_retry_returns_identity_without_overwriting_later_edits(self):
        first = self.create(creation_key='one-intent')
        second = db.commit_presentation_revision('tenant-a', first['presentation_id'], title='Edited')
        retried = self.create(creation_key='one-intent')
        self.assertEqual(retried['presentation_id'], first['presentation_id'])
        self.assertEqual(retried['revision'], second['revision'])
        self.assertEqual(retried['presentation']['title'], 'Edited')
        self.assertFalse(retried['created'])
        self.assertFalse(retried['changed'])
        self.assertEqual(self.count('presentations'), 1)
        separate = db.commit_presentation_revision('tenant-b', title='Other tenant', creation_key='one-intent')
        self.assertNotEqual(separate['presentation_id'], first['presentation_id'])

    def test_concurrent_creation_key_commits_only_one_identity(self):
        barrier = threading.Barrier(2)
        def create_once():
            with self.app.app_context():
                try:
                    db.get_db()
                    barrier.wait(timeout=5)
                    return self.create(creation_key='concurrent-intent')
                finally:
                    db.close_db()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create_once) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results[0]['presentation_id'], results[1]['presentation_id'])
        self.assertCountEqual([r['created'] for r in results], [True, False])
        self.assertEqual(self.count('presentations'), 1)
        self.assertEqual(self.count('presentation_revisions'), 1)
        self.assertEqual(self.count('change_log'), 1)

    def test_invalid_payloads_rollback_new_identity(self):
        for payload in ({'slides_data': '{}'}, {'project_data': 'not json'}, {'slides_data': {'bad': 1}},
                        {'title': ''}, {'expected_revision': True}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.create(**payload)
        self.assertEqual(self.count('presentations'), 0)


if __name__ == '__main__':
    unittest.main()
