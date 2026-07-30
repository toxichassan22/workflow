import os
import tempfile
import unittest

from flask import Flask

import db


class ProjectDraftIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'drafts.db')
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

    def test_new_draft_id_does_not_overwrite_previous_draft(self):
        db.save_project_draft(
            'tenant-1', 'user-1', {'name': 'old'}, {}, 'draft', draft_id='draft-old'
        )
        db.save_project_draft(
            'tenant-1', 'user-1', {'name': 'new'}, {}, 'draft', draft_id='draft-new'
        )

        old = db.get_project_draft_by_id('tenant-1', 'draft-old')
        new = db.get_project_draft_by_id('tenant-1', 'draft-new')

        self.assertEqual(old['draft_data']['name'], 'old')
        self.assertEqual(new['draft_data']['name'], 'new')

    def test_section_status_targets_requested_draft(self):
        db.save_project_draft(
            'tenant-1', 'user-1', {'name': 'old'}, {}, 'draft', draft_id='draft-old'
        )
        db.save_project_draft(
            'tenant-1', 'user-1', {'name': 'new'}, {}, 'draft', draft_id='draft-new'
        )

        updated = db.update_draft_section_status(
            'tenant-1', 'user-1', 'financial', 'approved', draft_id='draft-new'
        )

        self.assertTrue(updated)
        self.assertEqual(
            db.get_project_draft_by_id('tenant-1', 'draft-new')['section_statuses'],
            {'financial': 'approved'},
        )
        self.assertEqual(
            db.get_project_draft_by_id('tenant-1', 'draft-old')['section_statuses'],
            {},
        )


if __name__ == '__main__':
    unittest.main()
