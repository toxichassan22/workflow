"""Proposal 11-State Lifecycle Suite (t12).

Tests the full 11-state state machine from Omran AI System Analysis Section 7:
1. draft (مسودة)
2. sections_in_progress (قيد إعداد الأقسام)
3. section_approval_pending (بانتظار اعتماد قسم)
4. rejected_for_revision (معاد للتعديل)
5. sections_approved (الأقسام معتمدة)
6. generation_approval_pending (بانتظار اعتماد التوليد)
7. generating (قيد التوليد)
8. generated_draft (مسودة ملف مولد)
9. final_approval_pending (بانتظار اعتماد الملف النهائي)
10. approved (معتمد نهائيًا)
11. archived (مؤرشف)

Validates transitions, mandatory rejection/re-opening reasons, audit events,
backward compatibility with legacy statuses, DB functions, and Flask APIs.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class ProposalLifecycleDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir, 'proposal-lifecycle.db')
        db.init_db()
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()

        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('tenant-1', 'Test Tenant', 'testtenant', 'tenant@example.test', 'hash', 'free'),
        )
        conn.commit()

        # Seed sample project draft
        db.save_project_draft(
            'tenant-1', 'user-1',
            {'project_name': 'مشروع النرجس', 'city': 'الرياض'},
            {'basic': 'draft'}, 'draft', draft_id='draft-lifecycle-1',
        )

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_all_11_states_defined_with_metadata(self):
        """All 11 states must be defined with required attributes."""
        expected_states = [
            'draft',
            'sections_in_progress',
            'section_approval_pending',
            'rejected_for_revision',
            'sections_approved',
            'generation_approval_pending',
            'generating',
            'generated_draft',
            'final_approval_pending',
            'approved',
            'archived',
        ]
        self.assertEqual(len(db.PROPOSAL_LIFECYCLE_STATES), 11)
        for state in expected_states:
            self.assertIn(state, db.PROPOSAL_LIFECYCLE_STATES)
            meta = db.PROPOSAL_LIFECYCLE_STATES[state]
            self.assertIn('label', meta)
            self.assertIn('label_en', meta)
            self.assertIn('phase', meta)
            self.assertIn('description', meta)
            self.assertIn('is_locked', meta)
            self.assertIn('order', meta)

        # Locked states verify
        self.assertTrue(db.PROPOSAL_LIFECYCLE_STATES['approved']['is_locked'])
        self.assertTrue(db.PROPOSAL_LIFECYCLE_STATES['archived']['is_locked'])
        self.assertFalse(db.PROPOSAL_LIFECYCLE_STATES['draft']['is_locked'])

    def test_status_normalization_and_legacy_aliases(self):
        """Legacy status strings normalize gracefully."""
        self.assertEqual(db.normalize_proposal_status('draft'), 'draft')
        self.assertEqual(db.normalize_proposal_status('pending_approval'), 'section_approval_pending')
        self.assertEqual(db.normalize_proposal_status('submitted'), 'section_approval_pending')
        self.assertEqual(db.normalize_proposal_status('edited'), 'sections_in_progress')
        self.assertEqual(db.normalize_proposal_status(''), 'draft')
        self.assertEqual(db.normalize_proposal_status('unknown_status'), 'draft')

    def test_allowed_and_forbidden_transitions(self):
        """State machine allows valid transitions and rejects illegal jumps."""
        # Valid progressions
        self.assertTrue(db.can_transition_proposal_status('draft', 'sections_in_progress'))
        self.assertTrue(db.can_transition_proposal_status('sections_in_progress', 'section_approval_pending'))
        self.assertTrue(db.can_transition_proposal_status('section_approval_pending', 'sections_approved'))
        self.assertTrue(db.can_transition_proposal_status('section_approval_pending', 'rejected_for_revision'))
        self.assertTrue(db.can_transition_proposal_status('rejected_for_revision', 'sections_in_progress'))
        self.assertTrue(db.can_transition_proposal_status('sections_approved', 'generation_approval_pending'))
        self.assertTrue(db.can_transition_proposal_status('generation_approval_pending', 'generating'))
        self.assertTrue(db.can_transition_proposal_status('generating', 'generated_draft'))
        self.assertTrue(db.can_transition_proposal_status('generated_draft', 'final_approval_pending'))
        self.assertTrue(db.can_transition_proposal_status('final_approval_pending', 'approved'))
        self.assertTrue(db.can_transition_proposal_status('approved', 'archived'))
        self.assertTrue(db.can_transition_proposal_status('archived', 'sections_in_progress'))

        # Illegal jumps
        self.assertFalse(db.can_transition_proposal_status('draft', 'approved'))
        self.assertFalse(db.can_transition_proposal_status('draft', 'final_approval_pending'))
        self.assertFalse(db.can_transition_proposal_status('generating', 'approved'))
        self.assertFalse(db.can_transition_proposal_status('archived', 'approved'))

    def test_rejection_requires_mandatory_reason(self):
        """Moving to rejected_for_revision without reason must be rejected."""
        # draft -> sections_in_progress -> section_approval_pending
        db.transition_project_draft_status('tenant-1', 'draft-lifecycle-1', 'sections_in_progress')
        db.transition_project_draft_status('tenant-1', 'draft-lifecycle-1', 'section_approval_pending')

        # Rejection without reason fails
        res_no_reason = db.transition_project_draft_status(
            'tenant-1', 'draft-lifecycle-1', 'rejected_for_revision',
            actor_id='user-1', reason='',
        )
        self.assertEqual(res_no_reason.get('error'), 'reason_required')

        # Rejection with reason succeeds
        res_with_reason = db.transition_project_draft_status(
            'tenant-1', 'draft-lifecycle-1', 'rejected_for_revision',
            actor_id='user-1', reason='بيانات الصك تحتاج إلى مراجعة وتحديث مساحة الأرض',
        )
        self.assertTrue(res_with_reason.get('success'))
        self.assertEqual(res_with_reason.get('current_status'), 'rejected_for_revision')

    def test_reopening_approved_proposal_requires_mandatory_reason(self):
        """Moving from approved to generated_draft or sections_in_progress requires reason (Section 8.4)."""
        # Force draft to approved
        conn = db.get_db()
        conn.execute("UPDATE project_drafts SET status = 'approved' WHERE id = 'draft-lifecycle-1'")
        conn.commit()

        # Attempt to reopen without reason
        res_no_reason = db.transition_project_draft_status(
            'tenant-1', 'draft-lifecycle-1', 'generated_draft',
            actor_id='user-1', reason='',
        )
        self.assertEqual(res_no_reason.get('error'), 'reason_required')

        # Attempt to reopen with reason
        res_with_reason = db.transition_project_draft_status(
            'tenant-1', 'draft-lifecycle-1', 'generated_draft',
            actor_id='user-1', reason='طلب المالك تعديل نسبة البناء المعتمدة',
        )
        self.assertTrue(res_with_reason.get('success'))
        self.assertEqual(res_with_reason.get('current_status'), 'generated_draft')

    def test_transition_logs_immutable_audit_event(self):
        """Every status transition writes an audit_events row."""
        res = db.transition_project_draft_status(
            tenant_id='tenant-1',
            draft_id='draft-lifecycle-1',
            target_status='sections_in_progress',
            actor_id='user-1',
            actor_name='مطور المشاريع',
            actor_role='employee',
            reason='بدء إدخال بيانات الأقسام',
        )
        self.assertTrue(res.get('success'))

        # Check audit events table
        events = db.list_audit_events(
            tenant_id='tenant-1',
            entity_type='project_draft',
            entity_id='draft-lifecycle-1',
            action='proposal_status_transition',
        ).get('events', [])
        self.assertGreaterEqual(len(events), 1)
        latest = events[0]
        self.assertEqual(latest['user_name'], 'مطور المشاريع')
        self.assertEqual(latest['old_value'].get('status'), 'draft')
        self.assertEqual(latest['new_value'].get('status'), 'sections_in_progress')
        self.assertEqual(latest['metadata'].get('from_status'), 'draft')
        self.assertEqual(latest['metadata'].get('to_status'), 'sections_in_progress')
        self.assertEqual(latest['metadata'].get('reason'), 'بدء إدخال بيانات الأقسام')

    def test_get_proposal_lifecycle_info(self):
        """Lifecycle info provides state metadata, allowed next states, and history."""
        db.transition_project_draft_status(
            'tenant-1', 'draft-lifecycle-1', 'sections_in_progress',
            actor_id='user-1', actor_name='علي', reason='تجهيز',
        )
        info = db.get_proposal_lifecycle_info('tenant-1', 'draft-lifecycle-1')
        self.assertIsNotNone(info)
        self.assertEqual(info['current_status'], 'sections_in_progress')
        self.assertEqual(info['state_info']['phase'], 'inputs')
        self.assertIn('section_approval_pending', info['allowed_transitions'])
        self.assertGreaterEqual(len(info['history']), 1)
        self.assertEqual(info['history'][0]['to_status'], 'sections_in_progress')


class ProposalLifecycleApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir, 'proposal-lifecycle-api.db')
        db.init_db()

        # Import app after db redirection
        import app as flask_app
        cls.app = flask_app.app
        cls.app.config.update(TESTING=True)

        with cls.app.app_context():
            conn = db.get_db()
            conn.execute(
                "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                ('tenant-1', 'Test Tenant', 'testtenant', 'tenant@example.test', 'hash', 'free'),
            )
            conn.execute(
                "INSERT INTO users (id, tenant_id, email, password_hash, name, role, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                ('user-admin', 'tenant-1', 'admin@example.test', 'hash', 'Admin User', 'company_admin'),
            )
            conn.execute(
                "INSERT INTO users (id, tenant_id, email, password_hash, name, role, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, 1)",
                ('user-employee', 'tenant-1', 'emp@example.test', 'hash', 'Emp User', 'employee'),
            )
            conn.commit()

        cls.admin_token = auth.create_token(
            'tenant-1', 'admin@example.test', is_admin=True,
            user_id='user-admin', user_name='Admin User', user_role='company_admin',
        )
        cls.employee_token = auth.create_token(
            'tenant-1', 'emp@example.test', is_admin=False,
            user_id='user-employee', user_name='Emp User', user_role='employee',
        )

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.close_db()
        db.DB_PATH = cls.original_db_path
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            conn = db.get_db()
            conn.execute("DELETE FROM project_drafts WHERE tenant_id = 'tenant-1'")
            conn.commit()
            db.save_project_draft(
                'tenant-1', 'user-employee',
                {'project_name': 'مشروع الياسمين', 'city': 'جدة'},
                {'basic': 'draft'}, 'draft', draft_id='draft-api-1',
            )

    def test_get_lifecycle_states_endpoint(self):
        """GET /api/project-draft/lifecycle-states returns states and transitions."""
        resp = self.client.get(
            '/api/project-draft/lifecycle-states',
            headers={'Authorization': f'Bearer {self.admin_token}'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['states']), 11)
        self.assertIn('draft', data['transitions'])

    def test_get_draft_lifecycle_endpoint(self):
        """GET /api/project-draft/<id>/lifecycle returns draft state and transitions."""
        resp = self.client.get(
            '/api/project-draft/draft-api-1/lifecycle',
            headers={'Authorization': f'Bearer {self.admin_token}'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['lifecycle']['current_status'], 'draft')

    def test_transition_endpoint_validation_and_permissions(self):
        """POST /api/project-draft/<id>/transition-status validates transition and permissions."""
        # 1. Employee transitions own draft to sections_in_progress (valid)
        resp1 = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers={'Authorization': f'Bearer {self.employee_token}'},
            json={'targetStatus': 'sections_in_progress', 'reason': 'بدء العمل'},
        )
        self.assertEqual(resp1.status_code, 200, resp1.get_json())
        self.assertEqual(resp1.get_json()['lifecycle']['current_status'], 'sections_in_progress')

        # 2. Invalid transition (sections_in_progress -> approved) rejected
        resp2 = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={'targetStatus': 'approved'},
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(resp2.get_json()['error_code'], 'INVALID_STATUS_TRANSITION')

        # 3. Step forward to section_approval_pending
        resp3 = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers={'Authorization': f'Bearer {self.employee_token}'},
            json={'targetStatus': 'section_approval_pending'},
        )
        self.assertEqual(resp3.status_code, 200)

        # 4. Reject for revision without reason rejected with REASON_REQUIRED
        resp4 = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={'targetStatus': 'rejected_for_revision', 'reason': ''},
        )
        self.assertEqual(resp4.status_code, 400)
        self.assertEqual(resp4.get_json()['error_code'], 'REASON_REQUIRED')


if __name__ == '__main__':
    unittest.main()
