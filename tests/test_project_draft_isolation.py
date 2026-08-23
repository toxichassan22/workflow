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

    def test_unnamed_save_cannot_empty_the_draft_it_lands_on(self):
        """A save with no draft id still targets the newest draft of that actor, so the guard
        against emptying it is the only thing standing between a stray request and lost work."""
        db.save_project_draft(
            'tenant-1', 'user-1', {'project_name': 'برج المشرق', 'city': 'الرياض',
                                   'approved_financial_area': '7012'},
            {}, 'draft', draft_id='draft-old'
        )

        with self.assertRaises(db.DraftOverwriteRefused):
            db.save_project_draft('tenant-1', 'user-1', {})

        self.assertEqual(
            db.get_project_draft_by_id('tenant-1', 'draft-old')['draft_data']['project_name'],
            'برج المشرق',
        )

    def test_empty_payload_is_refused_instead_of_emptying_a_stored_draft(self):
        stored = {
            'project_name': 'برج المشرق',
            'city': 'الرياض',
            'approved_financial_area': '7012',
            'survey_coordinates': [{'point': '1', 'eastings': '510180.849'}],
        }
        db.save_project_draft('tenant-1', 'user-1', stored, {}, 'draft', draft_id='draft-1')

        with self.assertRaises(db.DraftOverwriteRefused):
            db.save_project_draft('tenant-1', 'user-1', {}, {}, 'draft', draft_id='draft-1')
        # Blank strings and empty containers carry no content either, whatever bookkeeping rides
        # along with them.
        with self.assertRaises(db.DraftOverwriteRefused):
            db.save_project_draft(
                'tenant-1', 'user-1',
                {'draftId': 'draft-1', 'project_name': '', 'city': '   ',
                 'approved_financial_area': '', 'survey_coordinates': [],
                 'tenantCreativeImages': {'cover': '', 'moodboard': []},
                 'pageDrafts': {'slides': {'status': 'empty'}}, 'map_styles': {}},
                {}, 'draft', draft_id='draft-1'
            )

        self.assertEqual(
            db.get_project_draft_by_id('tenant-1', 'draft-1')['draft_data']['project_name'],
            'برج المشرق',
        )

    def test_a_draft_that_is_still_being_started_can_still_be_cleared(self):
        db.save_project_draft(
            'tenant-1', 'user-1', {'project_name': 'اسم مؤقت'}, {}, 'draft', draft_id='draft-new'
        )

        db.save_project_draft(
            'tenant-1', 'user-1', {'draftId': 'draft-new', 'project_name': ''},
            {}, 'draft', draft_id='draft-new'
        )

        self.assertEqual(
            db.get_project_draft_by_id('tenant-1', 'draft-new')['draft_data']['project_name'], ''
        )

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
