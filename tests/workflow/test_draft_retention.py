"""Daily snapshots and the history retention window.

A snapshot is a full-state commit and a new replay base, so detailed deltas
older than the window can be dropped without breaking any version at or after
the snapshot. Pinned commits (approvals and the states around an AI run) are
never pruned. Runs against a temporary SQLite database.
"""

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import db


class DraftRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'draft-retention.db')
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

    def save(self, payload):
        return db.save_project_draft('tenant-1', 'user-1', payload, {}, 'draft',
                                     draft_id='draft-1')

    def age(self, commit_id, days):
        created = (db._utcnow() - timedelta(days=days)).isoformat()
        conn = db.get_db()
        conn.execute('UPDATE draft_commits SET created_at = ? WHERE id = ?',
                     (created, commit_id))
        conn.commit()

    def test_a_snapshot_rebuilds_the_full_payload(self):
        self.save({'project_name': 'برج المشرق', 'city': 'الرياض'})
        snapshot_id = db.write_draft_snapshot('tenant-1', 'draft-1')
        self.save({'project_name': 'برج المشرق الثاني', 'city': 'جدة'})

        state, meta = db.draft_state_at_commit('tenant-1', 'draft-1', snapshot_id)
        self.assertNotIn('error', meta)
        self.assertEqual(state['project_name'], 'برج المشرق')
        self.assertEqual(state['city'], 'الرياض')

    def test_old_deltas_are_pruned_around_the_snapshot_base(self):
        self.save({'project_name': 'النسخة الأولى', 'city': 'الرياض'})
        first = db.list_draft_commits('tenant-1', 'draft-1')[-1]
        snapshot_id = db.write_draft_snapshot('tenant-1', 'draft-1')
        self.save({'project_name': 'النسخة الثانية', 'city': 'جدة'})
        newest = db.list_draft_commits('tenant-1', 'draft-1')[0]
        self.age(first['id'], 10)
        self.age(snapshot_id, 8)

        deleted = db.prune_draft_history()
        self.assertGreaterEqual(deleted, 1)
        remaining = {commit['id'] for commit in db.list_draft_commits('tenant-1', 'draft-1')}
        self.assertNotIn(first['id'], remaining)
        self.assertIn(snapshot_id, remaining)
        self.assertIn(newest['id'], remaining)

        state, meta = db.draft_state_at_commit('tenant-1', 'draft-1', newest['id'])
        self.assertNotIn('error', meta)
        self.assertEqual(state['project_name'], 'النسخة الثانية')
        self.assertEqual(state['city'], 'جدة')

    def test_a_pinned_commit_is_never_removed(self):
        self.save({'project_name': 'نسخة معتمدة', 'city': 'الرياض'})
        pinned = db.list_draft_commits('tenant-1', 'draft-1')[-1]
        conn = db.get_db()
        conn.execute('UPDATE draft_commits SET pinned = 1 WHERE id = ?', (pinned['id'],))
        conn.commit()
        db.write_draft_snapshot('tenant-1', 'draft-1')
        self.save({'project_name': 'نسخة أحدث', 'city': 'جدة'})
        self.age(pinned['id'], 10)
        db.get_db().execute(
            'UPDATE draft_commits SET created_at = ? WHERE kind = ?',
            ((db._utcnow() - timedelta(days=8)).isoformat(), 'snapshot'))
        db.get_db().commit()

        db.prune_draft_history()
        remaining = {commit['id'] for commit in db.list_draft_commits('tenant-1', 'draft-1')}
        self.assertIn(pinned['id'], remaining)

    def test_an_old_snapshot_is_retired_but_the_base_stays(self):
        self.save({'project_name': 'البداية'})
        old_snapshot = db.write_draft_snapshot('tenant-1', 'draft-1')
        self.age(old_snapshot, 40)
        base_snapshot = db.write_draft_snapshot('tenant-1', 'draft-1')
        self.age(base_snapshot, 8)

        db.prune_draft_history()
        remaining = {commit['id'] for commit in db.list_draft_commits('tenant-1', 'draft-1')}
        self.assertNotIn(old_snapshot, remaining)
        self.assertIn(base_snapshot, remaining)


if __name__ == '__main__':
    unittest.main()
