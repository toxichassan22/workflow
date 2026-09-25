"""Landloom platform subsystems (t14-t63).

Covers generation approvals with cost estimate and points reservation,
final-file approvals with stamping, downloads ledger, proposal copies,
archive/restore, notifications, approval tasks, role templates,
separation-of-duties matrix, recharge requests, support tickets,
the file-type registry and their HTTP endpoints. Runs against a temporary
SQLite database and never calls Google or an AI API.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class LandloomDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'landloom.db')
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

    # ── t31: atomic escrow holds on the real ledger ──────────────────────

    def test_estimate_is_priced_per_unit_not_history(self):
        """A tenant with no billing history still gets a real price (t14-4)."""
        conn = db.get_db()
        conn.execute('DELETE FROM tenant_ledger')
        conn.commit()
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        self.assertGreater(estimate['estimated_cost_usd'], 0)
        self.assertGreater(estimate['estimated_points'], 0)
        self.assertEqual(estimate['units']['slide'], 8)
        self.assertEqual(estimate['units']['plan'], 1)

    def test_two_holds_cannot_spend_the_same_balance(self):
        conn = db.get_db()
        conn.execute('UPDATE tenants SET credit_balance = 100 WHERE id = ?', ('tenant-1',))
        conn.commit()
        first = db.reserve_points('tenant-1', 80000, 80.0, draft_id=self.draft_id)
        self.assertEqual(first['status'], 'reserved')
        # $20 is still free — a second hold may spend only what is left.
        second = db.reserve_points('tenant-1', 80000, 80.0, draft_id=self.draft_id)
        self.assertEqual(second.get('error'), 'insufficient_balance')
        fits = db.reserve_points('tenant-1', 20000, 20.0, draft_id=self.draft_id)
        self.assertEqual(fits['status'], 'reserved')
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 0.0)

    def test_one_active_hold_per_approval(self):
        conn = db.get_db()
        conn.execute('UPDATE tenants SET credit_balance = 100 WHERE id = ?', ('tenant-1',))
        conn.commit()
        first = db.reserve_points('tenant-1', 5000, 5.0, generation_approval_id='appr-x')
        again = db.reserve_points('tenant-1', 5000, 5.0, generation_approval_id='appr-x')
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(len(db.list_point_reservations('tenant-1', status='reserved')), 1)

    def test_consume_writes_debit_and_claims_run_usage(self):
        conn = db.get_db()
        conn.execute('UPDATE tenants SET credit_balance = 100 WHERE id = ?', ('tenant-1',))
        reservation = db.reserve_points('tenant-1', 25000, 25.0, draft_id=self.draft_id)
        # ISS-035: the settlement claims only this run's usage — rows written
        # inside the hold window and already priced ('settled'). An unpriced
        # 'pending' row or one predating the hold stays unclaimed.
        conn.execute(
            "INSERT INTO ai_usage_events (id, tenant_id, draft_id, flow, model, cost_usd, attempt_status) "
            "VALUES ('ev-1', 'tenant-1', ?, 'slide_single', 'm', 1.25, 'settled')",
            (self.draft_id,))
        conn.commit()
        consumed = db.consume_points('tenant-1', reservation['id'], settled_by='user-2', note='job-1')
        self.assertEqual(consumed['status'], 'consumed')
        # The hold became the debit on the real ledger — amount is the agreed
        # price, raw_cost_usd records the provider cost it claimed.
        entry = conn.execute(
            "SELECT * FROM tenant_ledger WHERE idempotency_key = ?",
            (f'hold:{reservation["id"]}',)).fetchone()
        self.assertEqual(entry['kind'], 'debit')
        self.assertEqual(entry['amount_sar'], 25.0)
        self.assertEqual(entry['raw_cost_usd'], 1.25)
        claimed = conn.execute(
            'SELECT billed_ledger_id FROM ai_usage_events WHERE id = ?', ('ev-1',)).fetchone()
        self.assertEqual(claimed['billed_ledger_id'], entry['id'])
        # The escrow paid it — no second debit, and the usage stays billed.
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 75.0)
        again = db.consume_points('tenant-1', reservation['id'])
        self.assertEqual(again.get('error'), 'reservation_not_reserved')

    def test_release_refunds_wallet_and_marks_ledger(self):
        conn = db.get_db()
        conn.execute('UPDATE tenants SET credit_balance = 50 WHERE id = ?', ('tenant-1',))
        conn.commit()
        reservation = db.reserve_points('tenant-1', 30000, 30.0, draft_id=self.draft_id)
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 20.0)
        released = db.release_points('tenant-1', reservation['id'], note='فشل')
        self.assertEqual(released['status'], 'released')
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 50.0)
        entry = conn.execute(
            "SELECT * FROM tenant_ledger WHERE idempotency_key = ?",
            (f'hold:{reservation["id"]}',)).fetchone()
        self.assertEqual(entry['kind'], 'release')

    def test_stale_reservation_sweep_refunds_and_returns_draft(self):
        conn = db.get_db()
        conn.execute('UPDATE tenants SET credit_balance = 100 WHERE id = ?', ('tenant-1',))
        conn.commit()
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        estimate['estimated_points'] = 25000
        estimate['estimated_cost_usd'] = 25.0
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        decided = db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'user-2', 'المعتمد')
        self.assertEqual(decided.get('status'), 'approved')
        draft = db.get_project_draft_by_id('tenant-1', self.draft_id)
        self.assertEqual(draft['status'], 'generating')
        # The $25 estimate escrows its riyal equivalent (93.75 SAR).
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 6.25)
        # The run died with the browser: expire the hold and sweep it.
        conn.execute("UPDATE point_reservations SET expires_at = '2020-01-01' WHERE status = 'reserved'")
        conn.commit()
        self.assertEqual(db.release_stale_reservations('tenant-1'), 1)
        reservation = conn.execute(
            'SELECT * FROM point_reservations WHERE generation_approval_id = ?',
            (approval['id'],)).fetchone()
        self.assertEqual(reservation['status'], 'released')
        self.assertAlmostEqual(db.get_tenant_balance('tenant-1'), 100.0)
        refreshed = db.get_generation_approval('tenant-1', approval['id'])
        self.assertEqual(refreshed['status'], 'expired')
        draft = db.get_project_draft_by_id('tenant-1', self.draft_id)
        self.assertEqual(draft['status'], 'sections_approved')

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
        self.assertEqual(len(unread), 3)  # عام + خاص + نسخة الأدمن المرآة
        updated = db.mark_notifications_read('tenant-1', 'user-1')
        self.assertGreaterEqual(updated, 1)
        db.mark_notifications_read('tenant-1', 'tenant-admin:tenant-1')
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

    # ── project responsibility assignments ─────────────────────────────────

    def test_user_assignments_one_approver_per_draft(self):
        db.create_user('tenant-1', 'معتمد أ', 'a@x.test', 'hash', role='employee')
        db.create_user('tenant-1', 'معتمد ب', 'b@x.test', 'hash', role='employee')
        approver_a = db.get_user_by_email('a@x.test')
        approver_b = db.get_user_by_email('b@x.test')
        ok = db.set_user_assignments('tenant-1', approver_a['id'],
                                     [{'draft_id': self.draft_id, 'role': 'approver'}])
        self.assertEqual(len(ok['assignments']), 1)
        conflict = db.set_user_assignments('tenant-1', approver_b['id'],
                                           [{'draft_id': self.draft_id, 'role': 'approver'}])
        self.assertEqual(conflict.get('error'), 'approver_exists')
        self.assertEqual(conflict.get('holder'), 'معتمد أ')
        # Editors do not collide — two editors on one draft is fine.
        ok2 = db.set_user_assignments('tenant-1', approver_b['id'],
                                      [{'draft_id': self.draft_id, 'role': 'editor'}])
        self.assertEqual(len(ok2['assignments']), 1)
        self.assertEqual(db.assigned_approver('tenant-1', self.draft_id)['user_id'],
                         approver_a['id'])
        self.assertTrue(db.user_is_assigned_approver('tenant-1', approver_a['id'], self.draft_id))
        self.assertFalse(db.user_is_assigned_approver('tenant-1', approver_b['id'], self.draft_id))
        # List payloads carry the approver name for «بانتظار تعميد — الاسم».
        rows = db.attach_approver_names('tenant-1', [{'id': self.draft_id}])
        self.assertEqual(rows[0]['approver_name'], 'معتمد أ')
        # The assignment itself grants draft access — no separate scope row needed.
        draft = db.get_project_draft_by_id('tenant-1', self.draft_id)
        self.assertTrue(db.user_may_access_draft(approver_a['id'], draft))
        # Releasing the approver frees the slot for a colleague.
        db.set_user_assignments('tenant-1', approver_a['id'], [])
        ok3 = db.set_user_assignments('tenant-1', approver_b['id'],
                                      [{'draft_id': self.draft_id, 'role': 'approver'}])
        self.assertEqual(len(ok3['assignments']), 1)

    def test_wildcard_approver_covers_and_blocks_every_draft(self):
        db.create_user('tenant-1', 'معتمد عام', 'w@x.test', 'hash', role='employee')
        db.create_user('tenant-1', 'معتمد آخر', 'o@x.test', 'hash', role='employee')
        wildcard = db.get_user_by_email('w@x.test')
        other = db.get_user_by_email('o@x.test')
        db.set_user_assignments('tenant-1', wildcard['id'],
                                [{'draft_id': '*', 'role': 'approver'}])
        self.assertEqual(db.assigned_approver('tenant-1', self.draft_id)['user_id'],
                         wildcard['id'])
        conflict = db.set_user_assignments('tenant-1', other['id'],
                                           [{'draft_id': self.draft_id, 'role': 'approver'}])
        self.assertEqual(conflict.get('error'), 'approver_exists')
        rows = db.attach_approver_names('tenant-1', [{'id': self.draft_id}])
        self.assertEqual(rows[0]['approver_name'], 'معتمد عام')

    def test_editor_cap_is_five_per_draft(self):
        editors = []
        for i in range(5):
            db.create_user('tenant-1', f'محرر {i}', f'ed{i}@x.test', 'hash', role='employee')
            editors.append(db.get_user_by_email(f'ed{i}@x.test'))
        for user in editors:
            result = db.set_user_assignments('tenant-1', user['id'],
                                             [{'draft_id': self.draft_id, 'role': 'editor'}])
            self.assertEqual(len(result['assignments']), 1)
        db.create_user('tenant-1', 'محرر سادس', 'ed6@x.test', 'hash', role='employee')
        sixth = db.get_user_by_email('ed6@x.test')
        blocked = db.set_user_assignments('tenant-1', sixth['id'],
                                        [{'draft_id': self.draft_id, 'role': 'editor'}])
        self.assertEqual(blocked.get('error'), 'too_many_editors')
        # Editing an existing holder's rows re-checks against the others, not them.
        same = db.set_user_assignments('tenant-1', editors[0]['id'],
                                       [{'draft_id': self.draft_id, 'role': 'editor'}])
        self.assertEqual(len(same['assignments']), 1)
        # A different draft stays open for the sixth editor.
        other_draft = db.save_project_draft(
            'tenant-1', 'user-1', {'project_name': 'آخر'}, {}, 'draft', draft_id='draft-2')
        ok = db.set_user_assignments('tenant-1', sixth['id'],
                                     [{'draft_id': other_draft, 'role': 'editor'}])
        self.assertEqual(len(ok['assignments']), 1)

    def test_invite_responsibility_applies_on_acceptance(self):
        db.create_user('tenant-1', 'محرر مدعو', 'ed@x.test', 'hash', role='employee')
        editor = db.get_user_by_email('ed@x.test')
        invite = db.create_invite('tenant-1', 'ed@x.test',
                                  responsibility='editor', projects=[self.draft_id])
        db.apply_invite_scope(editor['id'], db.get_invite('tenant-1', invite['id']))
        rows = db.list_user_assignments('tenant-1', editor['id'])
        self.assertEqual([(r['draft_id'], r['role']) for r in rows],
                         [(self.draft_id, 'editor')])
        # An approver invite with no projects picked covers every draft.
        db.create_user('tenant-1', 'معتمد مدعو', 'ap@x.test', 'hash', role='employee')
        approver = db.get_user_by_email('ap@x.test')
        invite = db.create_invite('tenant-1', 'ap@x.test', responsibility='approver')
        db.apply_invite_scope(approver['id'], db.get_invite('tenant-1', invite['id']))
        self.assertTrue(db.user_is_assigned_approver('tenant-1', approver['id'], self.draft_id))
        # An admin invite grants every company permission instead of a scope.
        db.create_user('tenant-1', 'أدمن مدعو', 'ad@x.test', 'hash', role='employee')
        admin = db.get_user_by_email('ad@x.test')
        invite = db.create_invite('tenant-1', 'ad@x.test', responsibility='admin',
                                  projects=[self.draft_id])
        db.apply_invite_scope(admin['id'], db.get_invite('tenant-1', invite['id']))
        perms = db.get_user_permissions(admin['id'])
        self.assertTrue(all(v for k, v in perms.items()
                            if k not in ('sag_admin_panel', 'support_tickets')))
        self.assertEqual(db.list_user_assignments('tenant-1', admin['id']), [])
        self.assertTrue(db.user_may_access_draft(admin['id'],
                                                 db.get_project_draft_by_id('tenant-1', self.draft_id)))

    def test_delete_user_releases_assignment_rows(self):
        """A deleted approver frees the slot — its rows carried no FK."""
        db.create_user('tenant-1', 'معتمد محذوف', 'del@x.test', 'hash', role='employee')
        dead = db.get_user_by_email('del@x.test')
        db.set_user_assignments('tenant-1', dead['id'],
                                [{'draft_id': self.draft_id, 'role': 'approver'}])
        db.delete_user(dead['id'])
        self.assertIsNone(db.assigned_approver('tenant-1', self.draft_id))
        self.assertEqual(db.list_tenant_assignments('tenant-1'), [])
        db.create_user('tenant-1', 'معتمد جديد', 'new-ap@x.test', 'hash', role='employee')
        ok = db.set_user_assignments(
            'tenant-1', db.get_user_by_email('new-ap@x.test')['id'],
            [{'draft_id': self.draft_id, 'role': 'approver'}])
        self.assertEqual(len(ok['assignments']), 1)

    def test_orphaned_assignment_rows_are_ignored_and_swept(self):
        """Rows outliving a hard-deleted user hold no slot and get swept."""
        conn = db.get_db()
        conn.execute(
            "INSERT INTO user_assignments (id, tenant_id, user_id, draft_id, role) "
            "VALUES ('ghost-1', 'tenant-1', 'ghost-user', ?, 'approver')", (self.draft_id,))
        conn.commit()
        # The orphan does not resolve as the approver nor block the slot.
        self.assertIsNone(db.assigned_approver('tenant-1', self.draft_id))
        db.create_user('tenant-1', 'معتمد', 'm@x.test', 'hash', role='employee')
        ok = db.set_user_assignments(
            'tenant-1', db.get_user_by_email('m@x.test')['id'],
            [{'draft_id': self.draft_id, 'role': 'approver'}])
        self.assertEqual(len(ok['assignments']), 1)
        self.assertIsNone(conn.execute(
            "SELECT 1 FROM user_assignments WHERE user_id = 'ghost-user'").fetchone())

    def test_invite_approver_conflict_surfaces_error(self):
        """An invited approver on a taken slot is reported, not silently dropped."""
        db.create_user('tenant-1', 'معتمد أول', 'first-ap@x.test', 'hash', role='employee')
        first = db.get_user_by_email('first-ap@x.test')
        db.set_user_assignments('tenant-1', first['id'],
                                [{'draft_id': self.draft_id, 'role': 'approver'}])
        db.create_user('tenant-1', 'معتمد مدعو', 'inv-ap@x.test', 'hash', role='employee')
        invited = db.get_user_by_email('inv-ap@x.test')
        invite = db.create_invite('tenant-1', 'inv-ap@x.test',
                                  responsibility='approver', projects=[self.draft_id])
        err = db.apply_invite_scope(invited['id'], db.get_invite('tenant-1', invite['id']))
        self.assertEqual(err, 'approver_exists')
        self.assertFalse(db.user_is_assigned_approver('tenant-1', invited['id'], self.draft_id))

    def test_tenant_users_report_marks_admin_like_and_responsibilities(self):
        db.create_user('tenant-1', 'أدمن', 'adm@x.test', 'hash', role='employee')
        admin = db.get_user_by_email('adm@x.test')
        db.grant_company_admin_permissions(admin['id'])
        db.create_user('tenant-1', 'محرر', 'rep-ed@x.test', 'hash', role='employee')
        editor = db.get_user_by_email('rep-ed@x.test')
        db.set_user_assignments('tenant-1', editor['id'],
                                [{'draft_id': self.draft_id, 'role': 'editor'}])
        report = db.tenant_users_report('tenant-1')
        rows = {u['email']: u for u in report['users']}
        self.assertTrue(rows['adm@x.test']['admin_like'])
        self.assertEqual(rows['rep-ed@x.test']['responsibilities'], ['editor'])
        self.assertFalse(rows['rep-ed@x.test']['admin_like'])

    # ── t21/t22: SoD matrix, users report ─────────────────────

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
            requested_by_name='رئيس القسم', transfer_reference='TRX-LEDGER-1')
        self.assertEqual(row['status'], 'pending')
        decided = db.decide_recharge_request(
            'tenant-1', row['id'], 'approved', 'admin-1', 'المدير')
        self.assertEqual(decided['status'], 'approved')
        self.assertTrue(decided['reference_number'])
        balance = db.get_tenant_balance('tenant-1')
        self.assertGreaterEqual(balance, 200)
        rejected = db.create_recharge_request(
            'tenant-1', 'باقة ثانية', amount_usd=50, requested_by='user-1',
            requested_by_name='رئيس القسم', transfer_reference='TRX-LEDGER-2')
        decided = db.decide_recharge_request(
            'tenant-1', rejected['id'], 'rejected', 'admin-1', 'المدير')
        self.assertEqual(decided['status'], 'rejected')
        all_rows = db.list_recharge_requests('tenant-1')
        self.assertEqual(len(all_rows), 2)

    # ── t50: support tickets ─────────────────────────────────────────────

    def test_support_ticket_lifecycle(self):
        ticket = db.create_support_ticket(
            'tenant-1', 'مشكلة توليد', priority='urgent', body='العرض توقف',
            created_by='user-1', created_by_name='رئيس القسم')
        self.assertEqual(ticket['status'], 'open')
        self.assertEqual(ticket['priority'], 'urgent')
        db.add_support_message('tenant-1', ticket['id'], 'سنراجع الأمر',
                               author_name='الدعم', author_role='support')
        detail = db.get_support_ticket('tenant-1', ticket['id'])
        # The opening body itself lands as the first ticket message.
        self.assertEqual(len(detail['messages']), 2)
        updated = db.update_support_ticket_status('tenant-1', ticket['id'], 'resolved')
        self.assertEqual(updated['status'], 'resolved')
        tickets = db.list_support_tickets('tenant-1', status='resolved')
        self.assertEqual(len(tickets), 1)

    # ── t63: the file-type registry ──────────────────────────────────────

    def test_file_type_registry(self):
        row = db.upsert_file_type('deed_file', 'صك الملكية', max_size_mb=30)
        self.assertEqual(row['max_size_mb'], 30)
        self.assertEqual(row['version'], 2)
        missing = db.upsert_file_type('', 'بدون مفتاح')
        self.assertEqual(missing.get('error'), 'key_and_label_required')
        self.assertEqual(len(db.get_file_type_registry()), 10)

    def test_operational_overview_counts(self):
        overview = db.operational_overview()
        self.assertIn('tenants', overview)
        self.assertIn('workflows', overview)
        self.assertIn('open_support_tickets', overview['workflows'])

    # ── t33/d09: receipt, tax and dedup on package purchase ──────────────

    def test_recharge_approval_issues_receipt_with_tax_atomically(self):
        row = db.create_recharge_request(
            'tenant-1', 'باقة نمو', amount_usd=100, price_sar=375,
            transfer_reference='TRX-1', requested_by='user-1',
            requested_by_name='رئيس القسم')
        decided = db.decide_recharge_request(
            'tenant-1', row['id'], 'approved', 'admin-1', 'المدير')
        self.assertEqual(decided['status'], 'approved')
        receipts = db.list_topup_receipts('tenant-1')
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        self.assertTrue(receipt['invoice_number'].startswith('INV-'))
        self.assertAlmostEqual(receipt['tax_amount_sar'], round(375 * db.TAX_RATE_SAR, 2))
        self.assertAlmostEqual(receipt['total_sar'], round(375 * (1 + db.TAX_RATE_SAR), 2))
        self.assertEqual(receipt['recharge_request_id'], row['id'])
        # A second decision attempt cannot mint a second receipt.
        dup = db.decide_recharge_request('tenant-1', row['id'], 'approved', 'admin-1', 'المدير')
        self.assertEqual(dup.get('error'), 'request_not_pending')
        self.assertEqual(len(db.list_topup_receipts('tenant-1')), 1)

    def test_recharge_rejects_duplicate_transfer_reference(self):
        db.create_recharge_request(
            'tenant-1', 'باقة نمو', amount_usd=100, transfer_reference='TRX-DUP')
        dup = db.create_recharge_request(
            'tenant-1', 'باقة أخرى', amount_usd=50, transfer_reference='TRX-DUP')
        self.assertEqual(dup.get('error'), 'duplicate_transfer_reference')

    def test_recharge_resolves_price_from_package_id(self):
        package = db.create_billing_package('باقة اختبار', credit_sar=75, price_sar=281.25)
        row = db.create_recharge_request(
            'tenant-1', 'client-supplied-name', amount_usd=9999, price_sar=1,
            package_id=package['id'], requested_by='user-1',
            transfer_reference='TRX-PKG-1')
        self.assertEqual(row['amount_sar'], 75)
        self.assertEqual(row['price_sar'], 281.25)
        self.assertEqual(row['package_name'], 'باقة اختبار')

    def test_recharge_requires_transfer_reference_or_receipt(self):
        missing = db.create_recharge_request(
            'tenant-1', 'باقة نمو', amount_usd=100, requested_by='user-1')
        self.assertEqual(missing.get('error'), 'reference_or_receipt_required')
        by_receipt = db.create_recharge_request(
            'tenant-1', 'باقة نمو', amount_usd=100,
            receipt_file_id='file-1', requested_by='user-1')
        self.assertEqual(by_receipt['status'], 'pending')
        self.assertEqual(by_receipt['receipt_file_id'], 'file-1')
        by_ref = db.create_recharge_request(
            'tenant-1', 'باقة نمو', amount_usd=100,
            transfer_reference='TRX-NEW', requested_by='user-1')
        self.assertEqual(by_ref['status'], 'pending')

    # ── t30/t32: points overview and ledger adjustments ──────────────────

    def test_points_overview_buckets(self):
        overview = db.points_overview('tenant-1')
        self.assertEqual(overview['balance_sar'], 100.0)
        self.assertEqual(overview['balance_points'], int(100 * db.POINTS_PER_USD))
        estimate = db.estimate_generation_cost('tenant-1', draft_id=self.draft_id, slides_count=8)
        estimate['estimated_points'] = 500
        estimate['estimated_cost_usd'] = 25.0
        approval = db.create_generation_approval(
            'tenant-1', self.draft_id, estimate, 'user-1', 'رئيس القسم')
        db.decide_generation_approval(
            'tenant-1', approval['id'], 'approved', 'boss-1', 'المدير', allow_self=True)
        overview = db.points_overview('tenant-1')
        self.assertGreater(overview['reserved_sar'], 0)
        # The hold is escrow: spendable drops, total owned stays whole.
        self.assertLess(overview['available_sar'], 100.0)
        self.assertEqual(overview['balance_sar'], 100.0)
        self.assertEqual(overview['available_sar'] + overview['reserved_sar'],
                         overview['balance_sar'])

    def test_ledger_adjustment_kinds_and_reversal(self):
        credit = db.record_ledger_credit('tenant-1', 25, note='شحن', actor='platform_admin')
        entry_id = credit['entry']['id']
        refund = db.record_ledger_adjustment(
            'tenant-1', -10, 'refund', note='استرداد', actor='platform_admin',
            reversal_of=entry_id)
        self.assertTrue(refund['adjusted'])
        self.assertEqual(refund['entry']['kind'], 'refund')
        self.assertEqual(refund['entry']['reversal_of'], entry_id)
        correction = db.record_ledger_adjustment(
            'tenant-1', 5, 'correction', note='تصحيح', actor='platform_admin')
        self.assertEqual(correction['entry']['kind'], 'correction')
        bad = db.record_ledger_adjustment('tenant-1', 5, 'bogus')
        self.assertEqual(bad.get('error'), 'invalid_kind')
        overdraw = db.record_ledger_adjustment(
            'tenant-1', -99999, 'refund', actor='platform_admin')
        self.assertEqual(overdraw.get('error'), 'insufficient_balance')
        missing = db.record_ledger_adjustment(
            'tenant-1', -1, 'refund', reversal_of='nope')
        self.assertEqual(missing.get('error'), 'original_entry_not_found')

    def test_ledger_entries_filtered(self):
        db.record_ledger_credit('tenant-1', 10, note='أ', actor='platform_admin')
        db.record_ledger_adjustment('tenant-1', 5, 'correction', actor='platform_admin')
        all_rows = db.get_ledger_entries('tenant-1')
        credits = db.get_ledger_entries('tenant-1', kind='credit')
        corrections = db.get_ledger_entries('tenant-1', kind='correction')
        self.assertGreaterEqual(len(all_rows), 2)
        self.assertTrue(all(r['kind'] == 'credit' for r in credits))
        self.assertEqual(len(corrections), 1)
        future = db.get_ledger_entries('tenant-1', from_date='2999-01-01')
        self.assertEqual(len(future), 0)

    # ── t40: seven-state support board ───────────────────────────────────

    def test_support_reopen_counts_regression_and_categories(self):
        ticket = db.create_support_ticket(
            'tenant-1', 'مشكلة', category='billing', priority='high',
            created_by='user-1', created_by_name='رئيس القسم')
        self.assertEqual(ticket['category'], 'billing')
        bad = db.create_support_ticket('tenant-1', 'مشكلة', category='bogus')
        self.assertEqual(bad.get('error'), 'invalid_category')
        db.update_support_ticket_status('tenant-1', ticket['id'], 'resolved')
        reopened = db.update_support_ticket_status('tenant-1', ticket['id'], 'reopened')
        self.assertEqual(reopened['status'], 'reopened')
        self.assertEqual(reopened['reopened_count'], 1)
        self.assertIsNone(reopened['resolved_at'])
        early = db.update_support_ticket_status('tenant-1', ticket['id'], 'reopened')
        self.assertEqual(early.get('error'), 'invalid_transition')
        escalated = db.update_support_ticket_status('tenant-1', ticket['id'], 'escalated')
        self.assertEqual(escalated['status'], 'escalated')

    def test_support_assign_validates_member(self):
        ticket = db.create_support_ticket('tenant-1', 'مشكلة', created_by='user-1')
        missing = db.assign_support_ticket('tenant-1', ticket['id'], 'ghost-user')
        self.assertEqual(missing.get('error'), 'assignee_not_found')
        conn = db.get_db()
        conn.execute(
            "INSERT INTO users (id, tenant_id, name, email, password_hash, role) "
            "VALUES ('u-support', 'tenant-1', 'موظف الدعم', 's@x.test', 'h', 'support')")
        conn.commit()
        assigned = db.assign_support_ticket('tenant-1', ticket['id'], 'u-support')
        self.assertEqual(assigned['assigned_to'], 'u-support')

    # ── t41: email channel reaches the outbox ────────────────────────────

    def test_notification_email_enqueues_outbox(self):
        note = db.create_notification(
            'tenant-1', 'تنبيه بالبريد', body='نص', email_to='user@x.test')
        conn = db.get_db()
        outbox = conn.execute(
            'SELECT * FROM email_outbox WHERE notification_id = ?', (note['id'],)
        ).fetchall()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]['status'], 'queued')
        deliveries = conn.execute(
            'SELECT channel, status FROM notification_deliveries WHERE notification_id = ?',
            (note['id'],),
        ).fetchall()
        channels = {row['channel']: row['status'] for row in deliveries}
        self.assertEqual(channels.get('in_app'), 'delivered')
        self.assertEqual(channels.get('email'), 'queued')

    # ── t42: event tasks carry entity link and priority ──────────────────

    def test_event_task_entity_link_and_priority(self):
        task = db.create_event_task(
            'tenant-1', 'مراجعة ملف', entity_type='project_draft', entity_id='draft-1',
            priority='urgent', created_by='user-1')
        self.assertEqual(task['entity_type'], 'project_draft')
        self.assertEqual(task['entity_id'], 'draft-1')
        self.assertEqual(task['priority'], 'urgent')
        bad = db.create_event_task('tenant-1', 'مهمة', priority='bogus')
        self.assertEqual(bad['priority'], 'normal')

    # ── smart notifications: categories, prefs, reminders ────────────────

    def test_notification_new_categories(self):
        for category in ('billing', 'job', 'platform'):
            item = db.create_notification('tenant-1', f'ن {category}', category=category)
            self.assertEqual(item['category'], category)
        legacy = db.create_notification('tenant-1', 'ق', category='unknown-cat')
        self.assertEqual(legacy['category'], 'general')

    def test_notification_list_filters_and_counts(self):
        db.create_notification('tenant-1', 'مهمة', category='task', user_id='user-1')
        db.create_notification('tenant-1', 'رصيد', category='billing', user_id='user-1')
        db.create_notification('tenant-1', 'عام', user_id='user-2')
        listed = db.list_notifications('tenant-1', user_id='user-1', category='billing')
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['category'], 'billing')
        self.assertEqual(db.count_notifications('tenant-1', user_id='user-1', unread_only=True), 2)
        self.assertEqual(db.count_notifications('tenant-1', user_id='user-2', unread_only=True), 1)
        self.assertEqual(db.count_notifications('tenant-1', user_id='missing', unread_only=True), 0)
        db.mark_notifications_read('tenant-1', 'user-1')
        self.assertEqual(db.count_notifications('tenant-1', user_id='user-1', unread_only=True), 0)
        read = db.list_notifications('tenant-1', user_id='user-1', read_state='read')
        self.assertEqual(len(read), 2)
        unread = db.list_notifications('tenant-1', user_id='user-2', read_state='unread')
        self.assertEqual(len(unread), 1)

    def test_notification_preferences_roundtrip_and_mute(self):
        defaults = db.get_notification_preferences('tenant-1', 'user-1')
        self.assertEqual(set(defaults), set(db.NOTIFICATION_CATEGORIES))
        self.assertTrue(all(defaults.values()))
        self.assertEqual(db.set_notification_preference('tenant-1', 'user-1', 'billing', False),
                         {'ok': True})
        self.assertEqual(db.set_notification_preference('tenant-1', 'user-1', 'junk', True),
                         {'error': 'invalid_category'})
        prefs = db.get_notification_preferences('tenant-1', 'user-1')
        self.assertFalse(prefs['billing'])
        self.assertTrue(prefs['task'])
        self.assertTrue(db.get_notification_preferences('tenant-1', 'user-2')['billing'])
        db.create_notification('tenant-1', 'رصيد', category='billing', user_id='user-1')
        db.create_notification('tenant-1', 'مهمة', category='task', user_id='user-1')
        items = db.list_notifications('tenant-1', user_id='user-1', muted_categories=['billing'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['category'], 'task')
        self.assertEqual(
            db.count_notifications('tenant-1', user_id='user-1', muted_categories=['billing']), 1)

    def test_recent_notification_exists_dedup(self):
        db.create_notification('tenant-1', 'قاعدة', entity_type='wallet', entity_id='w1')
        self.assertTrue(db.recent_notification_exists('tenant-1', 'wallet', 'w1'))
        self.assertFalse(db.recent_notification_exists('tenant-1', 'wallet', 'w2'))
        self.assertFalse(db.recent_notification_exists('tenant-2', 'wallet', 'w1'))
        self.assertFalse(db.recent_notification_exists('tenant-1', 'wallet', 'w1', since_hours=0))

    def test_event_task_reminders_once(self):
        due = (db._utcnow() + timedelta(hours=6)).isoformat()
        db.create_event_task('tenant-1', 'قريبة', assignee_user_id='user-1', due_at=due)
        db.create_event_task('tenant-1', 'بدون إسناد', due_at=due)
        far = (db._utcnow() + timedelta(hours=30)).isoformat()
        db.create_event_task('tenant-1', 'بعيدة', assignee_user_id='user-1', due_at=far)
        done = db.create_event_task('tenant-1', 'منجزة', assignee_user_id='user-1', due_at=due)
        db.update_event_task_status('tenant-1', done['id'], 'completed')
        self.assertEqual(len(db.send_due_event_task_reminders()), 2)
        self.assertEqual(db.send_due_event_task_reminders(), [])
        items = db.list_notifications('tenant-1', user_id='user-1', category='task')
        self.assertEqual(len(items), 1)
        # The admin feed carries the unassigned task's own row plus the
        # mirrored copy of the assignee's reminder — the admin sees every
        # notice that lands between staff members.
        owner = db.list_notifications(
            'tenant-1', user_id='tenant-admin:tenant-1', category='task')
        self.assertEqual(len(owner), 2)

    def test_stale_generation_job_notifies_creator_once(self):
        job = db.create_generation_job('tenant-1', draft_id='draft-1', created_by='user-1')
        stale = (db._utcnow() - timedelta(hours=20)).isoformat()
        conn = db.get_db()
        conn.execute(
            "UPDATE generation_jobs SET status = 'running', heartbeat_at = ?, started_at = ? WHERE id = ?",
            (stale, stale, job['id']))
        conn.commit()
        self.assertEqual(db.sweep_stale_generation_jobs(), 1)
        self.assertEqual(db.sweep_stale_generation_jobs(), 0)
        self.assertEqual(db.get_generation_job(job['id'])['status'], 'failed')
        items = db.list_notifications('tenant-1', user_id='user-1', category='job')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['entity_id'], job['id'])

    def test_list_admin_tenant_ids(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active, is_admin) "
            "VALUES ('adm-live', 'المنصة', 'root@x.test', 'hash', 1, 1)")
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active, is_admin) "
            "VALUES ('adm-dead', 'المنصة القديمة', 'old@x.test', 'hash', 0, 1)")
        conn.commit()
        ids = db.list_admin_tenant_ids()
        self.assertIn('adm-live', ids)
        self.assertNotIn('adm-dead', ids)

class LandloomApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'landloom-api.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        application_module.OPENROUTER_MANAGEMENT_KEY = None
        self.context = self.app.app_context()
        self.context.push()
        self.tenant_id = db.create_tenant('شركة العمق', 'landloom@x.test', 'hash', 'landloom')
        self.other_tenant_id = db.create_tenant('شركة أخرى', 'other@x.test', 'hash', 'other')
        self.user_id = db.create_user(
            self.tenant_id, 'رئيس القسم', 'boss@x.test', 'hash', role='employee')
        # The primary link makes this user-bound token the company admin: the
        # session normalizes to the tenant-direct identity on every request.
        db.update_tenant(self.tenant_id, primary_user_id=self.user_id)
        db.grant_company_admin_permissions(self.user_id)
        self.token = auth.create_token(
            self.tenant_id, 'boss@x.test', user_id=self.user_id,
            user_name='رئيس القسم', user_role='company_admin')
        self.other_token = auth.create_token(
            self.other_tenant_id, 'other@x.test', user_id=None,
            user_name='مسؤول آخر', user_role='company_admin')
        self.client = self.app.test_client()

    def tearDown(self):
        # The settle/finish endpoints fire daemon `usage-bill-*` threads and
        # wallet moves fire `cap-sync-*` provider-cap threads — each opens its
        # own SQLite handle, and on Windows the temp file cannot be deleted
        # while that handle lives, so wait for them before cleanup.
        for thread in threading.enumerate():
            if thread.name.startswith(('usage-bill-', 'cap-sync-')):
                thread.join(timeout=10)
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, token):
        return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    def _user_token(self, name, email, role='employee'):
        """Create an employee holding the permission set the retired role
        preset used to imply, so each test exercises the same capability."""
        preset_perms = {
            'support': ['support_tickets'],
            'generation_approver': ['approve_generation'],
            'final_file_approver': ['approve_final_file', 'export_files'],
            'section_approver': ['approvals'],
            'section_editor': ['generate_images', 'generate_maps'],
        }
        user_id = db.create_user(self.tenant_id, name, email, 'hash', role='employee')
        for perm in preset_perms.get(role, []):
            db.set_user_permission(user_id, perm, 1)
        token = auth.create_token(
            self.tenant_id, email, user_id=user_id, user_name=name, user_role='employee')
        return user_id, token

    def _platform_admin_token(self):
        """A super-admin session: an is_admin tenant with a direct login."""
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active, is_admin) "
            "VALUES ('platform-adm', 'المنصة', 'root@x.test', 'hash', 1, 1) "
            "ON CONFLICT(id) DO NOTHING")
        conn.commit()
        return auth.create_token(
            'platform-adm', 'root@x.test', is_admin=True, user_name='مدير المنصة')

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
        # ISS-042: a settle claim is checked against the server-side run — the
        # named job must exist under this approval and be completed.
        with self.app.app_context():
            job = db.create_generation_job(
                self.tenant_id, approval_id=approval_id, draft_id=draft_id)
            db.update_generation_job(job['id'], status='completed')
        mismatched = self.client.post(
            f'/api/generation-approvals/{approval_id}/settle', headers=self.headers(emp_token),
            json={'jobId': 'job-x', 'consumed': True})
        self.assertEqual(mismatched.status_code, 409, mismatched.get_json())
        settled = self.client.post(
            f'/api/generation-approvals/{approval_id}/settle', headers=self.headers(emp_token),
            json={'jobId': job['id'], 'consumed': True})
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

    def test_support_ticket_creation_and_status_are_gated(self):
        emp_id, creator_token = self._user_token('عميل', 'cust@x.test', 'employee')
        _, support_token = self._user_token('دعم', 'sup@x.test', 'support')
        # Tickets are the company admin's channel to the platform — employees
        # cannot file or list them even when a stale support_tickets grant row
        # exists (the effective permission is force-denied for employees).
        db.set_user_permission(emp_id, 'support_tickets', 1)
        self.assertFalse(db.get_user_permissions(emp_id)['support_tickets'])
        for token in (creator_token, support_token):
            denied_create = self.client.post(
                '/api/support/tickets', headers=self.headers(token),
                json={'subject': 'مشكلة', 'body': 'تفاصيل'})
            self.assertEqual(denied_create.status_code, 403)
            denied_list = self.client.get(
                '/api/support/tickets', headers=self.headers(token))
            self.assertEqual(denied_list.status_code, 403)
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل'})
        self.assertEqual(created.status_code, 200, created.get_json())
        ticket_id = created.get_json()['ticket']['id']
        # Status moves belong to the platform desk alone — the company side
        # (permission holder, creator, even the company admin) has no route.
        legacy = db.create_support_ticket(
            self.tenant_id, 'مشكلة قديمة', created_by=emp_id, created_by_name='عميل')
        for token in (creator_token, support_token, self.token):
            for status in ('closed', 'in_progress', 'resolved'):
                denied = self.client.post(
                    f'/api/support/tickets/{legacy["id"]}/status',
                    headers=self.headers(token), json={'status': status})
                self.assertEqual(denied.status_code, 404)
        # The platform desk still owns the workflow.
        admin_move = self.client.post(
            f'/api/admin/support/tickets/{ticket_id}/status',
            headers=self.headers(self._platform_admin_token()),
            json={'status': 'in_progress'})
        self.assertEqual(admin_move.status_code, 200, admin_move.get_json())

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

    def test_disabled_or_deleted_user_token_is_rejected(self):
        user_id, token = self._user_token('موظف', 'gone@x.test', 'employee')
        ok = self.client.get('/api/notifications', headers=self.headers(token))
        self.assertEqual(ok.status_code, 200)
        db.update_user(user_id, is_active=0)
        denied = self.client.get('/api/notifications', headers=self.headers(token))
        self.assertEqual(denied.status_code, 403)
        db.update_user(user_id, is_active=1)
        restored = self.client.get('/api/notifications', headers=self.headers(token))
        self.assertEqual(restored.status_code, 200)
        db.delete_user(user_id)
        removed = self.client.get('/api/notifications', headers=self.headers(token))
        self.assertEqual(removed.status_code, 403)

    def test_permission_grant_applies_to_existing_token(self):
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
        db.set_user_permission(emp_id, 'approve_generation', 1)
        allowed = self.client.post(
            f'/api/generation-approvals/{approval_id}/decision', headers=self.headers(emp_token),
            json={'decision': 'approved'})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

    def test_assigned_editor_sends_and_cancels_version_on_shared_draft(self):
        draft_id = db.save_project_draft(
            self.tenant_id, self.user_id,
            {'project_name': 'برج مشترك', 'project_type': 'سكني', 'city': 'الرياض'},
            {'basic': 'draft'}, 'draft', draft_id='shared-draft')
        editor_id, editor_token = self._user_token('محرر معين', 'ed-assign@x.test', 'employee')
        db.set_user_assignments(self.tenant_id, editor_id,
                                [{'draft_id': draft_id, 'role': 'editor'}])
        sent = self.client.post(
            '/api/project-draft/section-version', headers=self.headers(editor_token),
            json={'draftId': draft_id, 'sectionKey': 'basic'})
        self.assertEqual(sent.status_code, 200, sent.get_json())
        # The sender may withdraw their own send on a draft they don't own.
        version_id = sent.get_json()['version']['id']
        cancelled = self.client.post(
            '/api/project-draft/section-version/cancel', headers=self.headers(editor_token),
            json={'versionId': version_id})
        self.assertEqual(cancelled.status_code, 200, cancelled.get_json())
        # A bare employee still cannot submit on somebody else's draft.
        _, outsider_token = self._user_token('غريب', 'out-assign@x.test', 'employee')
        denied = self.client.post(
            '/api/project-draft/section-version', headers=self.headers(outsider_token),
            json={'draftId': draft_id, 'sectionKey': 'basic'})
        self.assertEqual(denied.status_code, 404)

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
        package = db.create_billing_package('باقة نمو', credit_sar=375, price_sar=375)
        missing = self.client.post(
            '/api/recharge-requests', headers=self.headers(self.token),
            json={'packageName': 'باقة نمو', 'amountUsd': 100,
                  'referenceNumber': 'TRX-TENANT-0'})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.get_json()['error_code'], 'package_required')
        created = self.client.post(
            '/api/recharge-requests', headers=self.headers(self.token),
            json={'packageId': package['id'], 'packageName': 'اسم مزوّر',
                  'amountUsd': 9999, 'priceSar': 1,
                  'referenceNumber': 'TRX-TENANT-1'})
        self.assertEqual(created.status_code, 200)
        # The catalog row owns the numbers — client-supplied fields are ignored.
        self.assertEqual(created.get_json()['request']['amount_sar'], 375)
        self.assertEqual(created.get_json()['request']['package_name'], 'باقة نمو')
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

    # ── smart notifications: API surface ──────────────────────────────────

    def test_notification_unread_count_and_filters(self):
        created = self.client.post(
            '/api/notifications', headers=self.headers(self.token),
            json={'title': 'فاتورة', 'category': 'billing', 'userId': self.user_id})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.get_json()['notification']['category'], 'billing')
        count = self.client.get(
            '/api/notifications/unread-count', headers=self.headers(self.token))
        self.assertEqual(count.status_code, 200)
        self.assertGreaterEqual(count.get_json()['unread'], 1)
        listed = self.client.get(
            '/api/notifications?category=billing', headers=self.headers(self.token))
        payload = listed.get_json()
        self.assertTrue(payload['notifications'])
        self.assertTrue(all(n['category'] == 'billing' for n in payload['notifications']))
        self.assertIn('total', payload)
        self.assertIn('unreadCount', payload)
        self.assertIn('categories', payload)
        self.assertEqual(
            self.client.get('/api/notifications?status=read',
                            headers=self.headers(self.token)).get_json()['notifications'],
            [])
        read = self.client.post(
            '/api/notifications/read', headers=self.headers(self.token),
            json={'ids': [created.get_json()['notification']['id']]})
        self.assertEqual(read.get_json()['updated'], 1)
        unread_after = self.client.get(
            '/api/notifications?status=unread', headers=self.headers(self.token))
        self.assertFalse(any(n['category'] == 'billing'
                             for n in unread_after.get_json()['notifications']))

    def test_notification_preferences_endpoint(self):
        got = self.client.get(
            '/api/notifications/preferences', headers=self.headers(self.token))
        self.assertEqual(got.status_code, 200)
        prefs = got.get_json()['preferences']
        self.assertTrue(all(prefs.values()))
        updated = self.client.put(
            '/api/notifications/preferences', headers=self.headers(self.token),
            json={'categories': {'billing': False, 'junk': False}})
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.get_json()['preferences']['billing'])
        self.assertTrue(updated.get_json()['preferences']['task'])
        db.create_notification(self.tenant_id, 'فاتورة', category='billing',
                               user_id=self.user_id)
        db.create_notification(self.tenant_id, 'مهمة', category='task',
                               user_id=self.user_id)
        listed = self.client.get('/api/notifications', headers=self.headers(self.token))
        cats = {n['category'] for n in listed.get_json()['notifications']}
        self.assertNotIn('billing', cats)
        self.assertIn('task', cats)
        restored = self.client.put(
            '/api/notifications/preferences', headers=self.headers(self.token),
            json={'category': 'billing', 'enabled': True})
        self.assertTrue(restored.get_json()['preferences']['billing'])
        listed = self.client.get('/api/notifications', headers=self.headers(self.token))
        self.assertIn('billing', {n['category'] for n in listed.get_json()['notifications']})

    def test_notification_self_target_is_not_broadcast(self):
        emp_id, emp_token = self._user_token('موظف', 'emp-n@x.test', 'employee')
        created = self.client.post(
            '/api/notifications', headers=self.headers(emp_token),
            json={'title': 'خاص', 'userId': emp_id})
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.get_json()['notification']['user_id'], emp_id)
        _, emp2_token = self._user_token('موظفة', 'emp2-n@x.test', 'employee')
        colleague_feed = self.client.get('/api/notifications', headers=self.headers(emp2_token))
        self.assertFalse(any(n['title'] == 'خاص'
                             for n in colleague_feed.get_json()['notifications']))
        # A missing userId means broadcast, which needs manage_users.
        broadcast = self.client.post(
            '/api/notifications', headers=self.headers(emp2_token),
            json={'title': 'عام'})
        self.assertEqual(broadcast.status_code, 403)
        foreign = self.client.post(
            '/api/notifications', headers=self.headers(emp2_token),
            json={'title': 'لآخر', 'userId': emp_id})
        self.assertEqual(foreign.status_code, 403)

    def test_notification_delete_scopes_like_the_feed(self):
        emp_id, emp_token = self._user_token('موظف', 'emp-del@x.test', 'employee')
        own = db.create_notification(self.tenant_id, 'لي', user_id=emp_id)
        other = db.create_notification(self.tenant_id, 'لزميله', user_id='someone-else')
        empty = self.client.post(
            '/api/notifications/delete', headers=self.headers(emp_token), json={})
        self.assertEqual(empty.status_code, 400)
        gone = self.client.post(
            '/api/notifications/delete', headers=self.headers(emp_token),
            json={'ids': [own['id'], other['id']]})
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(gone.get_json()['deleted'], 1)
        feed = self.client.get('/api/notifications', headers=self.headers(emp_token))
        self.assertFalse(any(n['id'] == own['id']
                             for n in feed.get_json()['notifications']))
        row = db.get_db().execute(
            'SELECT 1 AS x FROM notifications WHERE id = ?', (other['id'],)).fetchone()
        self.assertIsNotNone(row)

    def test_super_admin_feed_and_tenant_isolation(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active, is_admin) "
            "VALUES ('platform-admin', 'المنصة', 'root@x.test', 'hash', 1, 1)")
        conn.commit()
        admin_token = auth.create_token(
            'platform-admin', 'root@x.test', is_admin=True, user_name='مدير المنصة')
        self.application_module._notify_super_admins(
            'شركة جديدة انضمت إلى المنصة', 'شركة الاختبار',
            entity_type='tenant', entity_id=self.tenant_id)
        listed = self.client.get('/api/notifications', headers=self.headers(admin_token))
        feed = listed.get_json()['notifications']
        self.assertTrue(feed)
        self.assertEqual(feed[0]['category'], 'platform')
        self.assertEqual(feed[0]['entity_id'], self.tenant_id)
        company_feed = self.client.get('/api/notifications', headers=self.headers(self.token))
        self.assertFalse(any(n['entity_id'] == self.tenant_id and n['category'] == 'platform'
                             for n in company_feed.get_json()['notifications']))


if __name__ == '__main__':
    unittest.main()
