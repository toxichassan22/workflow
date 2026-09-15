"""Omran platform subsystems (t14-t63).

Covers generation approvals with cost estimate and points reservation,
final-file approvals with stamping, downloads ledger, proposal copies,
archive/restore, notifications, approval tasks, event tasks, role templates,
separation-of-duties matrix, recharge requests, support tickets, contracts,
the file-type registry and their HTTP endpoints. Runs against a temporary
SQLite database and never calls Google or an AI API.
"""

import json
import os
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


class OmranDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'omran.db')
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
        self.draft_id = db.save_project_draft(
            'tenant-1', 'user-1',
            {'project_name': 'برج المشرق', 'city': 'الرياض'},
            {'basic': 'approved'}, 'draft', draft_id='draft-1',
        )
        db.record_ledger_credit('tenant-1', 100, note='شحن تجريبي')

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    # ── t14: generation approvals and points ─────────────────────────────

    def test_generation_estimate_and_zero_cost_approval(self):
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        self.assertIn('estimated_points', estimate)
        self.assertIn('estimated_cost_usd', estimate)
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        self.assertEqual(approval['status'], 'pending')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'المعتمد')
        self.assertEqual(decided.get('status'), 'approved')

    def test_approve_reserves_and_settle_consumes_exactly_once(self):
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        estimate['estimated_points'] = 500
        estimate['estimated_cost_usd'] = 25.0
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'المعتمد')
        self.assertEqual(decided.get('status'), 'approved')
        self.assertTrue(decided.get('reservation_id'))
        settled = db.settle_generation_approval(
            'tenant-1', approval['id'], 'job-1', consumed=True, settled_by='user-1')
        self.assertEqual(settled['status'], 'consumed')
        again = db.settle_generation_approval(
            'tenant-1', approval['id'], 'job-1', consumed=True, settled_by='user-1')
        self.assertEqual(again.get('error'), 'approval_not_approved')
        reservations = db.list_point_reservations('tenant-1')
        self.assertEqual(len(reservations), 1)
        self.assertEqual(reservations[0]['status'], 'consumed')

    def test_release_after_failure_frees_reservation(self):
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        estimate['estimated_points'] = 500
        estimate['estimated_cost_usd'] = 25.0
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'المعتمد')
        settled = db.settle_generation_approval(
            'tenant-1', approval['id'], 'job-2', consumed=False, settled_by='user-1',
            note='فشل التوليد')
        self.assertEqual(settled['status'], 'rejected')
        reservations = db.list_point_reservations('tenant-1', status='released')
        self.assertEqual(len(reservations), 1)

    def test_approval_with_insufficient_balance_stays_pending(self):
        conn = db.get_db()
        conn.execute('UPDATE tenants SET credit_balance = 0 WHERE id = ?', ('tenant-1',))
        conn.commit()
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        estimate['estimated_points'] = 500
        estimate['estimated_cost_usd'] = 25.0
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'المعتمد')
        self.assertEqual(decided.get('error'), 'insufficient_balance')
        refreshed = db.get_generation_approval('tenant-1', approval['id'])
        self.assertEqual(refreshed['status'], 'pending')

    def test_cancel_is_requester_only(self):
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        result = db.decide_generation_approval(
            'tenant-1', approval['id'], 'cancelled', 'other-user', 'مستخدم آخر')
        self.assertEqual(result.get('error'), 'cancel_not_allowed')
        result = db.decide_generation_approval(
            'tenant-1', approval['id'], 'cancelled', 'user-1', 'رئيس القسم')
        self.assertEqual(result.get('status'), 'cancelled')

    def test_self_approval_blocked_unless_admin_allows(self):
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        blocked = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-1', 'رئيس القسم')
        self.assertEqual(blocked.get('error'), 'self_approval_not_allowed')
        blocked_reject = db.decide_generation_approval(
            'tenant-1', approval['id'], 'rejected', 'user-1', 'رئيس القسم')
        self.assertEqual(blocked_reject.get('error'), 'self_approval_not_allowed')
        allowed = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-1', 'رئيس القسم', allow_self=True)
        self.assertEqual(allowed.get('status'), 'approved')

    def test_generation_approval_requires_approved_sections(self):
        conn = db.get_db()
        # The request itself refuses while a tracked section is not approved.
        conn.execute(
            'UPDATE project_drafts SET section_statuses = ? WHERE id = ?',
            (json.dumps({'basic': 'draft'}), self.draft_id))
        conn.commit()
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        refused = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        self.assertEqual(refused.get('error'), 'sections_not_approved')

        conn.execute(
            'UPDATE project_drafts SET section_statuses = ? WHERE id = ?',
            (json.dumps({'basic': 'approved'}), self.draft_id))
        conn.commit()
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        self.assertEqual(approval.get('status'), 'pending')

        # The decision re-checks too: a section revoked after the request still
        # blocks approval.
        conn.execute(
            'UPDATE project_drafts SET section_statuses = ? WHERE id = ?',
            (json.dumps({'basic': 'draft'}), self.draft_id))
        conn.commit()
        blocked = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'المعتمد')
        self.assertEqual(blocked.get('error'), 'sections_not_approved')
        conn.execute(
            'UPDATE project_drafts SET section_statuses = ? WHERE id = ?',
            (json.dumps({'basic': 'approved'}), self.draft_id))
        conn.commit()
        allowed = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'المعتمد')
        self.assertEqual(allowed.get('status'), 'approved')

    # ── t15: final file approvals, downloads ─────────────────────────────

    def test_final_file_approval_requires_presentation_and_blocks_double(self):
        missing = db.request_final_file_approval('tenant-1', 'nope', 'user-1', 'رئيس القسم')
        self.assertEqual(missing.get('error'), 'presentation_not_found')
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status) VALUES (?, ?, ?, 'approved')",
            ('pres-1', 'tenant-1', 'عرض تجريبي'))
        conn.commit()
        first = db.request_final_file_approval('tenant-1', 'pres-1', 'user-1', 'رئيس القسم')
        self.assertEqual(first['status'], 'pending')
        second = db.request_final_file_approval('tenant-1', 'pres-1', 'user-1', 'رئيس القسم')
        self.assertEqual(second.get('error'), 'approval_already_pending')
        decided = db.decide_final_file_approval(
            'tenant-1', first['id'], 'approved', 'user-2', 'المعتمد')
        self.assertEqual(decided['status'], 'approved')

    def test_final_file_self_approval_blocked_unless_admin_allows(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status) VALUES (?, ?, ?, 'approved')",
            ('pres-self', 'tenant-1', 'عرض ذاتي'))
        conn.commit()
        request = db.request_final_file_approval('tenant-1', 'pres-self', 'user-1', 'رئيس القسم')
        blocked = db.decide_final_file_approval(
            'tenant-1', request['id'], 'approved', 'user-1', 'رئيس القسم')
        self.assertEqual(blocked.get('error'), 'self_approval_not_allowed')
        allowed = db.decide_final_file_approval(
            'tenant-1', request['id'], 'approved', 'user-1', 'رئيس القسم', allow_self=True)
        self.assertEqual(allowed.get('status'), 'approved')

    def test_downloads_ledger_lifecycle(self):
        row = db.record_download('tenant-1', 'proposal.pdf', draft_id=self.draft_id)
        self.assertEqual(row['approval_status'], 'pending')
        self.assertIsNone(row['downloaded_at'])
        delivered = db.mark_download_downloaded('tenant-1', row['id'], downloaded_by_name='المستلم')
        self.assertTrue(delivered['downloaded_at'])
        self.assertEqual(len(db.list_downloads('tenant-1')), 1)
        self.assertIsNone(db.mark_download_downloaded('tenant-1', row['id']))

    # ── t17/t18: copy, archive, restore ──────────────────────────────────

    def test_copy_keeps_inputs_drops_history_and_blocks_duplicate_names(self):
        copy = db.copy_project_draft(
            'tenant-1', self.draft_id, 'نسخة المطعم', 'user-1', 'رئيس القسم')
        self.assertEqual(copy['title'], 'نسخة المطعم')
        self.assertEqual(copy['source_draft_id'], self.draft_id)
        source = db.get_project_draft_by_id('tenant-1', copy['draft_id'])
        self.assertEqual(source.get('section_statuses'), {})
        duplicate = db.copy_project_draft(
            'tenant-1', self.draft_id, 'نسخة المطعم', 'user-1', 'رئيس القسم')
        self.assertEqual(duplicate.get('error'), 'title_exists')
        self.assertEqual(len(db.list_proposal_copies('tenant-1')), 1)

    def test_archive_then_restore(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status) VALUES (?, ?, ?, 'draft')",
            ('pres-2', 'tenant-1', 'عرض للأرشفة'))
        conn.commit()
        archived = db.archive_presentation('tenant-1', 'pres-2', 'user-1', 'رئيس القسم')
        self.assertEqual(archived['status'], 'archived')
        restored = db.restore_presentation('tenant-1', 'pres-2')
        self.assertEqual(restored['status'], 'draft')
        again = db.restore_presentation('tenant-1', 'pres-2')
        self.assertEqual(again.get('error'), 'presentation_not_archived')

    # ── t40: notifications, approval tasks, event tasks ──────────────────

    def test_notifications_mark_read_scopes(self):
        db.create_notification('tenant-1', 'تنبيه عام', body='نص')
        db.create_notification('tenant-1', 'تنبيه خاص', body='نص', user_id='user-1')
        unread = db.list_notifications('tenant-1', unread_only=True)
        self.assertEqual(len(unread), 2)
        updated = db.mark_notifications_read('tenant-1', 'user-1')
        self.assertGreaterEqual(updated, 1)
        conn = db.get_db()
        rows = conn.execute('SELECT title, read_at FROM notifications').fetchall()
        read_map = {row['title']: row['read_at'] for row in rows}
        self.assertTrue(all(read_map.values()))

    def test_approval_task_lifecycle(self):
        task = db.create_approval_task(
            'tenant-1', 'section_approval', 'اعتماد قسم الأساسيات',
            entity_type='section_version', entity_id='v1')
        self.assertEqual(task['status'], 'open')
        reminded = db.remind_approval_task('tenant-1', task['id'])
        self.assertTrue(reminded['reminded_at'])
        closed = db.close_approval_task('tenant-1', task['id'], closed_by_name='المعتمد')
        self.assertEqual(closed['status'], 'done')
        again = db.close_approval_task('tenant-1', task['id'], closed_by_name='المعتمد')
        self.assertEqual(again.get('error'), 'task_not_open')

    def test_event_task_recurrence_reopens(self):
        task = db.create_event_task(
            'tenant-1', 'اجتماع أسبوعي', recurrence='weekly', due_at='2026-09-20T10:00',
            created_by='user-1', created_by_name='رئيس القسم')
        self.assertEqual(task['status'], 'open')
        done = db.update_event_task_status('tenant-1', task['id'], 'completed', actor_name='رئيس القسم')
        self.assertEqual(done['status'], 'completed')
        tasks = db.list_event_tasks('tenant-1', status='open')
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0]['due_at'] > '2026-09-20')
        invalid = db.update_event_task_status('tenant-1', task['id'], 'bogus')
        self.assertEqual(invalid.get('error'), 'invalid_status')

    # ── t20/t21/t22: roles, SoD matrix, users report ─────────────────────

    def test_role_template_clone_and_duplicate_block(self):
        template = db.list_tenant_role_templates('tenant-1')
        self.assertIn({'key': 'approvals', 'default_granted': False}, template['permission_keys'])
        role = db.create_tenant_role('tenant-1', 'مراجع', 'employee',
                                     {'approvals': True, 'not_a_key': True})
        self.assertEqual(role['permissions'], {'approvals': True})
        duplicate = db.create_tenant_role('tenant-1', 'مراجع', 'employee', {'dashboard': True})
        self.assertEqual(duplicate.get('error'), 'role_name_exists')
        db.create_user('tenant-1', 'موظف', 'emp@x.test', 'hash', role='employee')
        user = db.get_user_by_email('emp@x.test')
        permissions = db.assign_tenant_role_to_user('tenant-1', user['id'], role['id'])
        self.assertTrue(permissions['approvals'])
        updated = db.update_tenant_role('tenant-1', role['id'], permissions={'approvals': False})
        self.assertEqual(updated['permissions'], {'approvals': False})
        self.assertTrue(db.delete_tenant_role('tenant-1', role['id']))

    def test_sod_matrix_flags_self_approval_and_missing_reason(self):
        conn = db.get_db()
        conn.execute(
            '''INSERT INTO section_versions
               (id, tenant_id, draft_id, section_key, version_number, snapshot_data,
                snapshot_hash, status, created_by, created_by_name, decided_by,
                decided_by_name, decided_at)
               VALUES ('sv-1', 'tenant-1', 'draft-1', 'basic', 1, '{}', 'h',
                       'approved', 'user-1', 'رئيس القسم', 'user-1', 'رئيس القسم',
                       '2026-09-14T10:00:00')''')
        conn.commit()
        matrix = db.separation_of_duties_matrix('tenant-1')
        self.assertEqual(matrix['self_approvals_count'], 1)
        self.assertEqual(matrix['self_approvals'][0]['section_key'], 'basic')
        self.assertEqual(matrix['missing_reason_count'], 0)

    def test_users_report_counts(self):
        db.create_user('tenant-1', 'موظف', 'emp2@x.test', 'hash', role='employee')
        report = db.tenant_users_report('tenant-1')
        self.assertEqual(report['counts']['active'], 1)
        self.assertGreaterEqual(len(report['users']), 1)

    # ── t30: recharge requests ───────────────────────────────────────────

    def test_recharge_request_decision_credits_ledger_once(self):
        row = db.create_recharge_request(
            'tenant-1', 'باقة نمو', amount_usd=100, requested_by='user-1',
            requested_by_name='رئيس القسم')
        self.assertEqual(row['status'], 'pending')
        decided = db.decide_recharge_request(
            'tenant-1', row['id'], 'approved', 'admin-1', 'المدير')
        self.assertEqual(decided['status'], 'approved')
        self.assertTrue(decided['reference_number'])
        balance = db.get_tenant_balance('tenant-1')
        self.assertGreaterEqual(balance, 200)
        rejected = db.create_recharge_request(
            'tenant-1', 'باقة ثانية', amount_usd=50, requested_by='user-1',
            requested_by_name='رئيس القسم')
        decided = db.decide_recharge_request(
            'tenant-1', rejected['id'], 'rejected', 'admin-1', 'المدير')
        self.assertEqual(decided['status'], 'rejected')
        all_rows = db.list_recharge_requests('tenant-1')
        self.assertEqual(len(all_rows), 2)

    # ── t50: support tickets ─────────────────────────────────────────────

    def test_support_ticket_lifecycle_and_sla(self):
        ticket = db.create_support_ticket(
            'tenant-1', 'مشكلة توليد', priority='urgent', body='العرض توقف',
            created_by='user-1', created_by_name='رئيس القسم')
        self.assertEqual(ticket['status'], 'open')
        self.assertTrue(ticket['sla_due_at'])
        db.add_support_message('tenant-1', ticket['id'], 'سنراجع الأمر',
                               author_name='الدعم', author_role='support')
        detail = db.get_support_ticket('tenant-1', ticket['id'])
        # The opening body itself lands as the first ticket message.
        self.assertEqual(len(detail['messages']), 2)
        updated = db.update_support_ticket_status('tenant-1', ticket['id'], 'resolved')
        self.assertEqual(updated['status'], 'resolved')
        tickets = db.list_support_tickets('tenant-1', status='resolved')
        self.assertEqual(len(tickets), 1)

    # ── t53/t63: contracts and the file-type registry ────────────────────

    def test_contracts_and_file_type_registry(self):
        contract = db.create_tenant_contract(
            'tenant-1', 'عقد الرئيسي', kind='nda', expires_at='2027-01-01',
            created_by='user-1', created_by_name='رئيس القسم')
        self.assertEqual(contract['status'], 'active')
        contracts = db.list_tenant_contracts('tenant-1')
        self.assertEqual(len(contracts), 1)
        row = db.upsert_file_type('deed_file', 'صك الملكية', max_size_mb=30)
        self.assertEqual(row['max_size_mb'], 30)
        self.assertEqual(row['version'], 2)
        missing = db.upsert_file_type('', 'بدون مفتاح')
        self.assertEqual(missing.get('error'), 'key_and_label_required')
        self.assertEqual(len(db.get_file_type_registry()), 9)

    def test_operational_overview_counts(self):
        overview = db.operational_overview()
        self.assertIn('tenants', overview)
        self.assertIn('workflows', overview)
        self.assertIn('open_support_tickets', overview['workflows'])


class OmranApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'omran-api.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        self.context = self.app.app_context()
        self.context.push()
        self.tenant_id = db.create_tenant('شركة العمق', 'omran@x.test', 'hash', 'omran')
        self.other_tenant_id = db.create_tenant('شركة أخرى', 'other@x.test', 'hash', 'other')
        self.user_id = db.create_user(
            self.tenant_id, 'رئيس القسم', 'boss@x.test', 'hash', role='company_admin')
        self.token = auth.create_token(
            self.tenant_id, 'boss@x.test', user_id=self.user_id,
            user_name='رئيس القسم', user_role='company_admin')
        self.other_token = auth.create_token(
            self.other_tenant_id, 'other@x.test', user_id=None,
            user_name='مسؤول آخر', user_role='company_admin')
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, token):
        return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    def _user_token(self, name, email, role='employee'):
        user_id = db.create_user(self.tenant_id, name, email, 'hash', role=role)
        token = auth.create_token(
            self.tenant_id, email, user_id=user_id, user_name=name, user_role=role)
        return user_id, token

    def _approved_draft(self, draft_id):
        return db.save_project_draft(
            self.tenant_id, self.user_id, {'project_name': 'مشروع معتمد'},
            {'basic': 'approved'}, 'draft', draft_id=draft_id)

    # ── Gate coverage: dedicated permissions + separation of duties ───────

    def test_generation_decision_requires_approve_generation(self):
        draft_id = self._approved_draft('draft-gen-gate')
        db.record_ledger_credit(self.tenant_id, 500, note='شحن تجريبي')
        _, emp_token = self._user_token('موظف', 'emp-gen@x.test', 'employee')
        _, approver_token = self._user_token('معتمد توليد', 'gen-appr@x.test', 'generation_approver')
        created = self.client.post(
            '/api/generation-approvals', headers=self.headers(emp_token),
            json={'draftId': draft_id, 'slidesCount': 4})
        self.assertEqual(created.status_code, 200, created.get_json())
        approval_id = created.get_json()['approval']['id']
        denied = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(emp_token),
            json={'decision': 'approved'})
        self.assertEqual(denied.status_code, 403)
        decided = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(approver_token),
            json={'decision': 'approved'})
        self.assertEqual(decided.status_code, 200, decided.get_json())

    def test_generation_self_approval_blocked_for_requester(self):
        draft_id = self._approved_draft('draft-gen-self')
        db.record_ledger_credit(self.tenant_id, 500, note='شحن تجريبي')
        emp_id, emp_token = self._user_token('محرر', 'ed-self@x.test', 'employee')
        db.set_user_permission(emp_id, 'approve_generation', True)
        created = self.client.post(
            '/api/generation-approvals', headers=self.headers(emp_token),
            json={'draftId': draft_id, 'slidesCount': 4})
        self.assertEqual(created.status_code, 200, created.get_json())
        approval_id = created.get_json()['approval']['id']
        own = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(emp_token),
            json={'decision': 'approved'})
        self.assertEqual(own.status_code, 403)
        self.assertEqual(own.get_json().get('error_code'), 'self_approval_not_allowed')
        by_admin = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(self.token),
            json={'decision': 'approved'})
        self.assertEqual(by_admin.status_code, 200, by_admin.get_json())

    def test_generation_settle_limited_to_requester_or_approver(self):
        draft_id = self._approved_draft('draft-gen-settle')
        db.record_ledger_credit(self.tenant_id, 500, note='شحن تجريبي')
        _, emp_token = self._user_token('مقدم', 'req@x.test', 'employee')
        _, third_token = self._user_token('غريب', 'third@x.test', 'employee')
        created = self.client.post(
            '/api/generation-approvals', headers=self.headers(emp_token),
            json={'draftId': draft_id, 'slidesCount': 4})
        approval_id = created.get_json()['approval']['id']
        decided = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(self.token),
            json={'decision': 'approved'})
        self.assertEqual(decided.status_code, 200, decided.get_json())
        denied = self.client.post(
            f'/api/generation-approvals/{approval_id}/settle', headers=self.headers(third_token),
            json={'jobId': 'job-x', 'consumed': True})
        self.assertEqual(denied.status_code, 403)
        settled = self.client.post(
            f'/api/generation-approvals/{approval_id}/settle', headers=self.headers(emp_token),
            json={'jobId': 'job-x', 'consumed': True})
        self.assertEqual(settled.status_code, 200, settled.get_json())

    def test_final_file_decision_requires_permission_and_separation(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status) VALUES (?, ?, ?, 'approved')",
            ('pres-gate-1', self.tenant_id, 'عرض للملف'))
        conn.commit()
        emp_id, emp_token = self._user_token('مقدم الملف', 'file-req@x.test', 'employee')
        _, fin_token = self._user_token('معتمد الملف', 'fin-appr@x.test', 'final_file_approver')
        requested = self.client.post(
            '/api/presentations/pres-gate-1/final-approval/request', headers=self.headers(emp_token),
            json={'revision': 1})
        self.assertEqual(requested.status_code, 200, requested.get_json())
        approval_id = requested.get_json()['approval']['id']
        denied = self.client.post(
            f'/api/final-file-approvals/{approval_id}/decision', headers=self.headers(emp_token),
            json={'decision': 'approved'})
        self.assertEqual(denied.status_code, 403)
        decided = self.client.post(
            f'/api/final-file-approvals/{approval_id}/decision', headers=self.headers(fin_token),
            json={'decision': 'approved'})
        self.assertEqual(decided.status_code, 200, decided.get_json())

    def test_final_file_self_approval_blocked_over_http(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status) VALUES (?, ?, ?, 'approved')",
            ('pres-gate-2', self.tenant_id, 'عرض ذاتي'))
        conn.commit()
        emp_id, emp_token = self._user_token('مقدم معتمد', 'both@x.test', 'employee')
        db.set_user_permission(emp_id, 'approve_final_file', True)
        requested = self.client.post(
            '/api/presentations/pres-gate-2/final-approval/request', headers=self.headers(emp_token),
            json={'revision': 1})
        self.assertEqual(requested.status_code, 200, requested.get_json())
        approval_id = requested.get_json()['approval']['id']
        own = self.client.post(
            f'/api/final-file-approvals/{approval_id}/decision', headers=self.headers(emp_token),
            json={'decision': 'approved'})
        self.assertEqual(own.status_code, 403)
        self.assertEqual(own.get_json().get('error_code'), 'self_approval_not_allowed')

    def test_support_status_needs_support_permission_or_creator_close(self):
        _, creator_token = self._user_token('عميل', 'cust@x.test', 'employee')
        _, other_token = self._user_token('آخر', 'other-emp@x.test', 'employee')
        _, support_token = self._user_token('دعم', 'sup@x.test', 'support')
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(creator_token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل'})
        self.assertEqual(created.status_code, 200, created.get_json())
        ticket_id = created.get_json()['ticket']['id']
        denied = self.client.post(
            f'/api/support/tickets/{ticket_id}/status', headers=self.headers(other_token),
            json={'status': 'in_progress'})
        self.assertEqual(denied.status_code, 403)
        creator_close = self.client.post(
            f'/api/support/tickets/{ticket_id}/status', headers=self.headers(creator_token),
            json={'status': 'closed'})
        self.assertEqual(creator_close.status_code, 200, creator_close.get_json())
        support_move = self.client.post(
            f'/api/support/tickets/{ticket_id}/status', headers=self.headers(support_token),
            json={'status': 'in_progress'})
        self.assertEqual(support_move.status_code, 200, support_move.get_json())

    def test_approval_task_close_and_remind_are_gated(self):
        _, emp_token = self._user_token('موظف', 'emp-task@x.test', 'employee')
        approver_id, approver_token = self._user_token('معتمد', 'task-appr@x.test', 'generation_approver')
        task = db.create_approval_task(
            self.tenant_id, 'generation_approval', 'مهمة اعتماد', assignee_id=approver_id,
            assignee_name='معتمد')
        denied_close = self.client.post(
            f'/api/approval-tasks/{task["id"]}/close', headers=self.headers(emp_token), json={})
        self.assertEqual(denied_close.status_code, 403)
        denied_remind = self.client.post(
            f'/api/approval-tasks/{task["id"]}/remind', headers=self.headers(emp_token), json={})
        self.assertEqual(denied_remind.status_code, 403)
        reminded = self.client.post(
            f'/api/approval-tasks/{task["id"]}/remind', headers=self.headers(approver_token), json={})
        self.assertEqual(reminded.status_code, 200, reminded.get_json())
        closed = self.client.post(
            f'/api/approval-tasks/{task["id"]}/close', headers=self.headers(approver_token), json={})
        self.assertEqual(closed.status_code, 200, closed.get_json())

    def test_event_task_status_limited_to_assignee_creator_or_manager(self):
        _, creator_token = self._user_token('منشئ', 'creator@x.test', 'employee')
        assignee_id, assignee_token = self._user_token('مكلف', 'assignee@x.test', 'employee')
        _, third_token = self._user_token('غريب', 'third-ev@x.test', 'employee')
        created = self.client.post(
            '/api/event-tasks', headers=self.headers(creator_token),
            json={'title': 'مهمة تسليم', 'assigneeId': assignee_id})
        self.assertEqual(created.status_code, 200, created.get_json())
        task_id = created.get_json()['task']['id']
        denied = self.client.post(
            f'/api/event-tasks/{task_id}/status', headers=self.headers(third_token),
            json={'status': 'completed'})
        self.assertEqual(denied.status_code, 403)
        done = self.client.post(
            f'/api/event-tasks/{task_id}/status', headers=self.headers(assignee_token),
            json={'status': 'completed'})
        self.assertEqual(done.status_code, 200, done.get_json())

    def test_disabled_or_deleted_user_token_is_rejected(self):
        user_id, token = self._user_token('موظف', 'gone@x.test', 'employee')
        ok = self.client.get('/api/event-tasks', headers=self.headers(token))
        self.assertEqual(ok.status_code, 200)
        db.update_user(user_id, is_active=0)
        denied = self.client.get('/api/event-tasks', headers=self.headers(token))
        self.assertEqual(denied.status_code, 403)
        db.update_user(user_id, is_active=1)
        restored = self.client.get('/api/event-tasks', headers=self.headers(token))
        self.assertEqual(restored.status_code, 200)
        db.delete_user(user_id)
        removed = self.client.get('/api/event-tasks', headers=self.headers(token))
        self.assertEqual(removed.status_code, 403)

    def test_role_change_applies_to_existing_token(self):
        draft_id = self._approved_draft('draft-role-change')
        db.record_ledger_credit(self.tenant_id, 500, note='شحن تجريبي')
        created = self.client.post(
            '/api/generation-approvals', headers=self.headers(self.token),
            json={'draftId': draft_id, 'slidesCount': 4})
        self.assertEqual(created.status_code, 200, created.get_json())
        approval_id = created.get_json()['approval']['id']
        emp_id, emp_token = self._user_token('موظف', 'promoted@x.test', 'employee')
        denied = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(emp_token),
            json={'decision': 'approved'})
        self.assertEqual(denied.status_code, 403)
        db.update_user(emp_id, role='generation_approver')
        allowed = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(emp_token),
            json={'decision': 'approved'})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

    def test_event_tasks_roundtrip_and_auth(self):
        no_auth = self.client.get('/api/event-tasks')
        self.assertEqual(no_auth.status_code, 401)
        created = self.client.post(
            '/api/event-tasks', headers=self.headers(self.token),
            json={'title': 'اجتماع تسليم', 'recurrence': 'weekly'})
        self.assertEqual(created.status_code, 200)
        task_id = created.get_json()['task']['id']
        completed = self.client.post(
            f'/api/event-tasks/{task_id}/status', headers=self.headers(self.token),
            json={'status': 'completed'})
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.get_json()['task']['status'], 'completed')
        listed = self.client.get('/api/event-tasks', headers=self.headers(self.token))
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(listed.get_json()['tasks'])

    def test_roles_require_manage_users_and_tenant_scope(self):
        role = self.client.post(
            '/api/roles', headers=self.headers(self.token),
            json={'name': 'مراجع', 'permissions': {'approvals': True}})
        self.assertEqual(role.status_code, 200)
        role_id = role.get_json()['role']['id']
        # A second company must not see the first company's role.
        foreign = self.client.post(
            f'/api/roles/{role_id}/update', headers=self.headers(self.other_token),
            json={'permissions': {'approvals': False}})
        self.assertEqual(foreign.status_code, 404)

    def test_support_ticket_and_messages(self):
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل'})
        self.assertEqual(created.status_code, 200)
        ticket_id = created.get_json()['ticket']['id']
        detail = self.client.get(f'/api/support/tickets/{ticket_id}', headers=self.headers(self.token))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.get_json()['ticket']['messages']), 1)
        missing = self.client.get('/api/support/tickets/nope', headers=self.headers(self.token))
        self.assertEqual(missing.status_code, 404)

    def test_notifications_roundtrip(self):
        created = self.client.post(
            '/api/notifications', headers=self.headers(self.token),
            json={'title': 'تنبيه', 'category': 'tasks'})
        self.assertEqual(created.status_code, 200)
        listed = self.client.get('/api/notifications', headers=self.headers(self.token))
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(listed.get_json()['notifications'])
        read = self.client.post('/api/notifications/read', headers=self.headers(self.token), json={})
        self.assertEqual(read.status_code, 200)
        self.assertGreaterEqual(read.get_json()['updated'], 1)

    def test_recharge_request_tenant_scoped(self):
        created = self.client.post(
            '/api/recharge-requests', headers=self.headers(self.token),
            json={'packageName': 'باقة نمو', 'amountUsd': 100})
        self.assertEqual(created.status_code, 200)
        listed = self.client.get('/api/recharge-requests', headers=self.headers(self.token))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.get_json()['requests']), 1)
        foreign = self.client.get('/api/recharge-requests', headers=self.headers(self.other_token))
        self.assertEqual(foreign.status_code, 200)
        self.assertEqual(len(foreign.get_json()['requests']), 0)

    def test_copy_endpoint_needs_draft(self):
        response = self.client.post(
            '/api/project-draft/copy', headers=self.headers(self.token),
            json={'newTitle': 'نسخة'})
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
