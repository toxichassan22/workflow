"""Proposal 11-State Lifecycle Suite (t12).

Tests the full 11-state state machine from Landloom AI System Analysis Section 7:
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
            user_name='Admin User', user_role='company_admin',
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
                {'project_name': 'مشروع الياسمين', 'city': 'جدة', 'project_type': 'سكني'},
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

    def test_manual_transition_cannot_enter_operational_states(self):
        """T12-05: the transition endpoint never hand-moves a draft into a gate state."""
        admin = {'Authorization': f'Bearer {self.admin_token}'}
        # Walk the draft to sections_approved through the internal machinery.
        with self.app.app_context():
            for target in ('sections_in_progress', 'section_approval_pending', 'sections_approved'):
                res = db.transition_project_draft_status(
                    'tenant-1', 'draft-api-1', target, actor_id='user-admin')
                self.assertTrue(res.get('success'), res)

        # Gate entries that are valid internally are refused for a manual caller.
        for target in ('generation_approval_pending', 'generating'):
            resp = self.client.post(
                '/api/project-draft/draft-api-1/transition-status',
                headers=admin, json={'targetStatus': target, 'reason': 'اختبار'},
            )
            self.assertEqual(resp.status_code, 403, target)
            self.assertEqual(resp.get_json()['error_code'], 'SYSTEM_TRANSITION_ONLY', target)

        # Move on to generated_draft internally, then the final gate stays manual-proof.
        with self.app.app_context():
            for target in ('generation_approval_pending', 'generating', 'generated_draft'):
                db.transition_project_draft_status(
                    'tenant-1', 'draft-api-1', target, actor_id='user-admin')
        resp = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers=admin, json={'targetStatus': 'final_approval_pending'},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()['error_code'], 'SYSTEM_TRANSITION_ONLY')

        with self.app.app_context():
            db.transition_project_draft_status(
                'tenant-1', 'draft-api-1', 'final_approval_pending', actor_id='user-admin')
        resp = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers=admin, json={'targetStatus': 'approved', 'reason': 'اختبار'},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()['error_code'], 'SYSTEM_TRANSITION_ONLY')

        # The draft itself never moved past where the internal calls put it.
        lifecycle = self.client.get(
            '/api/project-draft/draft-api-1/lifecycle',
            headers=admin,
        ).get_json()['lifecycle']
        self.assertEqual(lifecycle['current_status'], 'final_approval_pending')

    def test_manual_transition_cannot_bypass_section_gate(self):
        """T12-04: draft -> sections_approved by hand is refused even for an approver."""
        resp = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers={'Authorization': f'Bearer {self.admin_token}'},
            json={'targetStatus': 'sections_approved'},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()['error_code'], 'SYSTEM_TRANSITION_ONLY')

    def test_employee_cannot_self_approve_sections_via_transition(self):
        """A draft owner cannot move their own draft through the section gate."""
        self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers={'Authorization': f'Bearer {self.employee_token}'},
            json={'targetStatus': 'section_approval_pending'},
        )
        resp = self.client.post(
            '/api/project-draft/draft-api-1/transition-status',
            headers={'Authorization': f'Bearer {self.employee_token}'},
            json={'targetStatus': 'sections_approved'},
        )
        self.assertEqual(resp.status_code, 403)

    def test_locked_draft_refuses_save_and_section_writes(self):
        """T12-03: a draft in a locked lifecycle state refuses writes with 423."""
        with self.app.app_context():
            db.transition_project_draft_status(
                'tenant-1', 'draft-api-1', 'sections_in_progress', actor_id='user-employee')
            db.transition_project_draft_status(
                'tenant-1', 'draft-api-1', 'section_approval_pending', actor_id='user-employee')
            db.transition_project_draft_status(
                'tenant-1', 'draft-api-1', 'sections_approved', actor_id='user-admin')
            db.transition_project_draft_status(
                'tenant-1', 'draft-api-1', 'generation_approval_pending',
                actor_id='user-employee', reason='طلب اعتماد التوليد')

        headers = {'Authorization': f'Bearer {self.employee_token}'}
        save = self.client.post('/api/project-draft', headers=headers, json={
            'draftId': 'draft-api-1',
            'draftData': {'draftId': 'draft-api-1', 'project_name': 'تعديل مرفوض'},
            'sectionStatuses': {'basic': 'draft'},
        })
        self.assertEqual(save.status_code, 423)
        self.assertEqual(save.get_json()['error_code'], 'DRAFT_LOCKED')
        self.assertEqual(save.get_json()['status'], 'generation_approval_pending')

        section = self.client.post('/api/project-draft/section-status', headers=headers, json={
            'draftId': 'draft-api-1', 'sectionKey': 'basic', 'sectionStatus': 'approved',
        })
        self.assertEqual(section.status_code, 423)
        self.assertEqual(section.get_json()['error_code'], 'DRAFT_LOCKED')

        version = self.client.post('/api/project-draft/section-version', headers=headers, json={
            'draftId': 'draft-api-1', 'sectionKey': 'basic', 'snapshot': {'a': 1},
        })
        self.assertEqual(version.status_code, 423)


class ProposalLifecycleGateTests(unittest.TestCase):
    """The three approval gates drive the 11-state lifecycle end to end (t12)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir, 'proposal-gates.db')
        db.init_db()
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()

        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, "
            "is_active, credit_balance) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            ('tenant-1', 'Test Tenant', 'testtenant', 'tenant@example.test', 'hash', 'free', 1000.0),
        )
        conn.commit()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_draft(self, draft_id, status='draft', section_statuses=None):
        db.save_project_draft(
            'tenant-1', 'user-1',
            {'project_name': 'مشروع البوابات', 'city': 'الرياض'},
            section_statuses if section_statuses is not None else {'basic': 'approved'},
            'draft', draft_id=draft_id,
        )
        if status != 'draft':
            conn = db.get_db()
            conn.execute('UPDATE project_drafts SET status = ? WHERE id = ?', (status, draft_id))
            conn.commit()
        return draft_id

    def _draft_status(self, draft_id):
        return db.get_project_draft_by_id('tenant-1', draft_id).get('status')

    def _approval(self, draft_id):
        estimate = db.estimate_generation_cost('tenant-1', draft_id=draft_id, slides_count=5)
        approval = db.create_generation_approval(
            'tenant-1', draft_id, estimate, 'user-1', 'مقدم الطلب')
        self.assertNotIn('error', approval)
        return approval

    def test_new_draft_never_starts_in_a_gate_state(self):
        """A save payload may not create a draft already past the section gate."""
        db.save_project_draft(
            'tenant-1', 'user-1', {'project_name': 'مشروع', 'city': 'جدة'},
            {'basic': 'approved'}, 'approved', draft_id='draft-born-approved',
        )
        self.assertEqual(self._draft_status('draft-born-approved'), 'draft')
        db.save_project_draft(
            'tenant-1', 'user-1', {'project_name': 'مشروع ٢', 'city': 'جدة'},
            {'basic': 'draft'}, 'submitted', draft_id='draft-born-submitted',
        )
        self.assertEqual(self._draft_status('draft-born-submitted'), 'draft')

    def test_generation_request_moves_draft_to_approval_pending(self):
        """T12-01: opening a generation approval parks the draft in its gate state."""
        self._seed_draft('gate-1', status='sections_approved')
        approval = self._approval('gate-1')
        self.assertEqual(approval['status'], 'pending')
        self.assertEqual(approval['prior_status'], 'sections_approved')
        self.assertEqual(self._draft_status('gate-1'), 'generation_approval_pending')

    def test_generation_request_requires_approved_sections(self):
        """The request fails when a tracked section is not approved."""
        self._seed_draft('gate-2', status='sections_in_progress',
                         section_statuses={'basic': 'draft'})
        estimate = db.estimate_generation_cost('tenant-1', draft_id='gate-2', slides_count=5)
        res = db.create_generation_approval('tenant-1', 'gate-2', estimate, 'user-1', 'مقدم')
        self.assertEqual(res.get('error'), 'sections_not_approved')
        self.assertEqual(self._draft_status('gate-2'), 'sections_in_progress')

    def test_generation_request_on_locked_draft_refused(self):
        """A draft with a live run refuses a second generation request."""
        self._seed_draft('gate-3', status='sections_approved')
        approval = self._approval('gate-3')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'معتمد')
        self.assertEqual(decided.get('status'), 'approved', decided)
        self.assertEqual(self._draft_status('gate-3'), 'generating')
        estimate = db.estimate_generation_cost('tenant-1', draft_id='gate-3', slides_count=5)
        res = db.create_generation_approval('tenant-1', 'gate-3', estimate, 'user-1', 'مقدم')
        self.assertEqual(res.get('error'), 'draft_locked')

    def test_generation_approval_decision_moves_draft_to_generating(self):
        """Approving the request starts the run: the draft lands on 'generating'."""
        self._seed_draft('gate-4', status='sections_approved')
        approval = self._approval('gate-4')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'معتمد التوليد')
        self.assertEqual(decided.get('status'), 'approved')
        self.assertEqual(self._draft_status('gate-4'), 'generating')
        self.assertEqual(decided.get('draft_status'), 'generating')

    def test_generation_rejection_restores_prior_status(self):
        """A rejected request returns the draft to where it was requested from."""
        self._seed_draft('gate-5', status='sections_approved')
        approval = self._approval('gate-5')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'rejected', 'user-2', 'معتمد التوليد', note='السعر مرتفع')
        self.assertEqual(decided.get('status'), 'rejected')
        self.assertEqual(self._draft_status('gate-5'), 'sections_approved')

    def test_generation_cancel_restores_prior_status(self):
        """The requester cancelling their pending request frees the draft again."""
        self._seed_draft('gate-6', status='sections_approved')
        approval = self._approval('gate-6')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'cancelled', 'user-1', 'مقدم الطلب')
        self.assertEqual(decided.get('status'), 'cancelled')
        self.assertEqual(self._draft_status('gate-6'), 'sections_approved')

    def test_generation_settle_consumed_moves_to_generated_draft(self):
        """A finished run consumes the reservation and lands on 'generated_draft'."""
        self._seed_draft('gate-7', status='sections_approved')
        approval = self._approval('gate-7')
        db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'معتمد التوليد')
        settled = db.settle_generation_approval(
            'tenant-1', approval['id'], 'job-1', consumed=True, settled_by='user-1')
        self.assertEqual(settled.get('status'), 'consumed')
        self.assertEqual(self._draft_status('gate-7'), 'generated_draft')
        self.assertEqual(settled.get('draft_status'), 'generated_draft')

    def test_generation_settle_release_restores_prior(self):
        """A failed run releases the reservation and returns the draft to its prior state."""
        self._seed_draft('gate-8', status='sections_approved')
        approval = self._approval('gate-8')
        db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'معتمد التوليد')
        settled = db.settle_generation_approval(
            'tenant-1', approval['id'], 'job-1', consumed=False, settled_by='user-1',
            note='تعذر توليد الشرائح')
        self.assertEqual(settled.get('status'), 'rejected')
        self.assertEqual(self._draft_status('gate-8'), 'sections_approved')

    def test_regeneration_request_remembers_generated_prior(self):
        """A re-run on a generated draft returns to 'generated_draft' when rejected."""
        self._seed_draft('gate-9', status='generated_draft')
        approval = self._approval('gate-9')
        self.assertEqual(approval['prior_status'], 'generated_draft')
        db.decide_generation_approval(
            'tenant-1', approval['id'], 'rejected', 'user-2', 'معتمد', note='لا حاجة')
        self.assertEqual(self._draft_status('gate-9'), 'generated_draft')

    def test_leaving_gate_state_cancels_pending_approval(self):
        """Manual withdrawal from the gate voids the still-pending request."""
        self._seed_draft('gate-10', status='sections_approved')
        approval = self._approval('gate-10')
        res = db.transition_project_draft_status(
            'tenant-1', 'gate-10', 'sections_in_progress',
            actor_id='user-1', reason='سحب الطلب', manual=True)
        self.assertTrue(res.get('success'))
        refreshed = db.get_generation_approval('tenant-1', approval['id'])
        self.assertEqual(refreshed['status'], 'cancelled')

    def test_final_file_request_moves_draft_to_final_pending(self):
        """T12-02: requesting the final file parks the draft in final_approval_pending."""
        self._seed_draft('gate-11', status='generated_draft')
        pres_id = db.create_presentation(
            'tenant-1', 'عرض الملف', project_data={'draftId': 'gate-11'},
            slides_data=[{'title': 'غلاف'}], draft_id='gate-11')
        approval = db.request_final_file_approval('tenant-1', pres_id, 'user-1', 'مقدم')
        self.assertNotIn('error', approval)
        self.assertEqual(self._draft_status('gate-11'), 'final_approval_pending')
        self.assertEqual(approval['status'], 'pending')

    def test_final_file_approval_moves_draft_and_presentation_to_approved(self):
        """Approval lands both the presentation and the linked draft on 'approved'."""
        self._seed_draft('gate-12', status='generated_draft')
        pres_id = db.create_presentation(
            'tenant-1', 'عرض الملف', project_data={'draftId': 'gate-12'},
            slides_data=[{'title': 'غلاف'}], draft_id='gate-12')
        approval = db.request_final_file_approval('tenant-1', pres_id, 'user-1', 'مقدم')
        decided = db.decide_final_file_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'معتمد الملف')
        self.assertEqual(decided.get('status'), 'approved')
        self.assertEqual(self._draft_status('gate-12'), 'approved')
        pres = db.get_presentation(pres_id, tenant_id='tenant-1')
        self.assertEqual(pres.get('status'), 'approved')

    def test_final_file_rejection_returns_draft_to_generated(self):
        """A rejected final file sends the draft back to 'generated_draft' for rework."""
        self._seed_draft('gate-13', status='generated_draft')
        pres_id = db.create_presentation(
            'tenant-1', 'عرض الملف', project_data={'draftId': 'gate-13'},
            slides_data=[{'title': 'غلاف'}], draft_id='gate-13')
        approval = db.request_final_file_approval('tenant-1', pres_id, 'user-1', 'مقدم')
        decided = db.decide_final_file_approval(
            'tenant-1', approval['id'], 'rejected', 'user-2', 'معتمد الملف',
            note='الصفحة الأخيرة تحتاج إعادة تصميم')
        self.assertEqual(decided.get('status'), 'rejected')
        self.assertEqual(self._draft_status('gate-13'), 'generated_draft')

    def test_final_file_rejection_requires_note(self):
        """A rejection without a written reason is refused before any state moves."""
        self._seed_draft('gate-14', status='generated_draft')
        pres_id = db.create_presentation(
            'tenant-1', 'عرض الملف', project_data={'draftId': 'gate-14'},
            slides_data=[{'title': 'غلاف'}], draft_id='gate-14')
        approval = db.request_final_file_approval('tenant-1', pres_id, 'user-1', 'مقدم')
        res = db.decide_final_file_approval(
            'tenant-1', approval['id'], 'rejected', 'user-2', 'معتمد الملف')
        self.assertEqual(res.get('error'), 'note_required')
        self.assertEqual(self._draft_status('gate-14'), 'final_approval_pending')

    def test_save_and_section_writes_refuse_locked_draft(self):
        """T12-03: DraftLocked guards saves and section writes on a locked draft."""
        self._seed_draft('gate-15', status='generation_approval_pending')
        with self.assertRaises(db.DraftLocked):
            db.save_project_draft(
                'tenant-1', 'user-1', {'project_name': 'تعديل'}, {'basic': 'approved'},
                'draft', draft_id='gate-15')
        with self.assertRaises(db.DraftLocked):
            db.update_draft_section_statuses(
                'tenant-1', 'user-1', {'basic': 'draft'}, draft_id='gate-15')
        res = db.create_section_version(
            'tenant-1', 'gate-15', 'basic', {'a': 1}, 'user-1', 'مقدم')
        self.assertEqual(res.get('error'), 'draft_locked')

    def test_generating_draft_accepts_only_checkpoint_saves(self):
        """While a live run holds 'generating', ordinary saves refuse; the
        job's checkpoint save passes."""
        self._seed_draft('gate-16', status='sections_approved')
        approval = self._approval('gate-16')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'معتمد')
        self.assertEqual(decided.get('status'), 'approved', decided)
        self.assertEqual(self._draft_status('gate-16'), 'generating')
        with self.assertRaises(db.DraftLocked):
            db.save_project_draft(
                'tenant-1', 'user-1', {'project_name': 'تعديل'}, None,
                'draft', draft_id='gate-16')
        draft_id = db.save_project_draft(
            'tenant-1', 'user-1', {'project_name': 'نقطة تفتيش', 'city': 'الرياض'},
            {'basic': 'approved'}, 'draft', draft_id='gate-16', allow_generating=True)
        self.assertEqual(draft_id, 'gate-16')
        self.assertEqual(self._draft_status('gate-16'), 'generating')

    def test_full_lifecycle_walkthrough(self):
        """Every gate moves the draft forward through the canonical 11 states."""
        self._seed_draft('gate-17', status='draft')
        steps = [
            ('sections_in_progress', {}),
            ('section_approval_pending', {}),
            ('sections_approved', {}),
            ('generation_approval_pending', {}),
            ('generating', {}),
            ('generated_draft', {}),
            ('final_approval_pending', {}),
            ('approved', {}),
            ('archived', {}),
        ]
        for target, kwargs in steps:
            res = db.transition_project_draft_status(
                'tenant-1', 'gate-17', target, actor_id='user-1', **kwargs)
            self.assertTrue(res.get('success'), f'{target}: {res}')
            self.assertEqual(self._draft_status('gate-17'), target)


if __name__ == '__main__':
    unittest.main()
