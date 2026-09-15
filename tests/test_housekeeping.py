"""Housekeeping passes (t24/t40/t41/d08).

Covers the automatic reminder/escalation sweeps and the email outbox
drain: each runs on a timer or an explicit admin call, reaches the assignee
and company admins in-app and by email, and stays idempotent so a repeated
tick never notifies twice. Runs against a temporary SQLite database and never
touches a real SMTP server.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class HousekeepingDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'housekeeping.db')
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
        self.admin_id = db.create_user(
            'tenant-1', 'مدير الشركة', 'admin@x.test', 'hash', role='company_admin')
        self.assignee_id = db.create_user(
            'tenant-1', 'المعتمد', 'approver@x.test', 'hash', role='generation_approver')

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _notifications(self, user_id):
        conn = db.get_db()
        return conn.execute(
            'SELECT * FROM notifications WHERE user_id = ?', (user_id,)
        ).fetchall()

    def _outbox_rows(self):
        conn = db.get_db()
        return conn.execute('SELECT * FROM email_outbox').fetchall()

    # ── t24: automatic reminders ─────────────────────────────────────────

    def test_due_reminder_notifies_assignee_once_per_cooldown(self):
        task = db.create_approval_task(
            'tenant-1', 'generation_approval', 'اعتماد توليد برج المشرق',
            assignee_id=self.assignee_id, assignee_name='المعتمد', due_hours=1)
        reminded = db.send_due_approval_reminders(due_window_hours=12)
        self.assertIn(task['id'], reminded)
        updated = db.get_db().execute(
            'SELECT reminded_at FROM approval_tasks WHERE id = ?', (task['id'],)
        ).fetchone()
        self.assertTrue(updated['reminded_at'])
        notes = self._notifications(self.assignee_id)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['category'], 'task')
        outbox = self._outbox_rows()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]['to_email'], 'approver@x.test')
        # A second pass inside the cooldown does not re-remind.
        self.assertEqual(db.send_due_approval_reminders(due_window_hours=12), [])
        self.assertEqual(len(self._outbox_rows()), 1)

    def test_manual_reminder_emails_the_assignee(self):
        task = db.create_approval_task(
            'tenant-1', 'section_approval', 'اعتماد قسم',
            assignee_id=self.assignee_id, assignee_name='المعتمد')
        result = db.remind_approval_task('tenant-1', task['id'])
        self.assertTrue(result['reminded_at'])
        outbox = self._outbox_rows()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]['to_email'], 'approver@x.test')

    # ── t24: escalation ──────────────────────────────────────────────────

    def test_overdue_task_escalates_to_assignee_and_admins(self):
        task = db.create_approval_task(
            'tenant-1', 'final_approval', 'اعتماد الملف النهائي',
            assignee_id=self.assignee_id, assignee_name='المعتمد', due_hours=1)
        db.get_db().execute(
            'UPDATE approval_tasks SET due_at = ? WHERE id = ?',
            ((db._utcnow() - timedelta(hours=30)).isoformat(), task['id']),
        )
        db.get_db().commit()
        escalated = db.escalate_overdue_approval_tasks()
        self.assertIn(task['id'], escalated)
        updated = db.get_db().execute(
            'SELECT escalated_at FROM approval_tasks WHERE id = ?', (task['id'],)
        ).fetchone()
        self.assertTrue(updated['escalated_at'])
        self.assertTrue(self._notifications(self.assignee_id))
        self.assertTrue(self._notifications(self.admin_id))
        self.assertEqual(db.escalate_overdue_approval_tasks(), [])

    def test_open_task_inside_due_window_does_not_escalate(self):
        db.create_approval_task(
            'tenant-1', 'section_approval', 'اعتماد قسم', due_hours=48)
        self.assertEqual(db.escalate_overdue_approval_tasks(), [])

    # ── t41/t61: the outbox drain ────────────────────────────────────────

    def test_claim_due_emails_claims_each_row_once(self):
        db.enqueue_email('a@x.test', 'أول')
        db.enqueue_email('b@x.test', 'ثانٍ')
        claimed = db.claim_due_emails()
        self.assertEqual(len(claimed), 2)
        # A second claim sees no queued rows — they are 'sending' now.
        self.assertEqual(db.claim_due_emails(), [])

    def test_failed_send_retries_then_dies(self):
        row = db.enqueue_email('x@x.test', 'موضوع')
        for _ in range(5):
            db.claim_due_emails()
            db.mark_email_failed(row['id'], error='smtp down')
        final = db.get_db().execute(
            'SELECT status FROM email_outbox WHERE id = ?', (row['id'],)
        ).fetchone()
        self.assertEqual(final['status'], 'dead')

    # ── t33: package catalog carries validity and terms ──────────────────

    def test_packages_expose_version_validity_and_features(self):
        pkg = db.create_billing_package('باقة اختبار', credit_usd=100, price_sar=375)
        db.create_package_version(
            pkg['id'], name='باقة اختبار', credit_usd=100,
            price_sar=375, duration_days=90, features=['دعم فني', 'خمسة مشاريع'])
        listed = {p['id']: p for p in db.list_billing_packages(active_only=True)}
        self.assertEqual(listed[pkg['id']]['duration_days'], 90)
        self.assertEqual(listed[pkg['id']]['features'], ['دعم فني', 'خمسة مشاريع'])

    def test_packages_without_version_report_no_validity(self):
        pkg = db.create_billing_package('باقة بلا إصدار', credit_usd=10)
        listed = {p['id']: p for p in db.list_billing_packages(active_only=True)}
        self.assertIsNone(listed[pkg['id']]['duration_days'])
        self.assertEqual(listed[pkg['id']]['features'], [])


class HousekeepingApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'housekeeping-api.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        self.context = self.app.app_context()
        self.context.push()
        self.tenant_id = db.create_tenant('شركة العمق', 'omran@x.test', 'hash', 'omran')
        self.user_id = db.create_user(
            self.tenant_id, 'مدير', 'boss@x.test', 'hash', role='company_admin')
        self.token = auth.create_token(
            self.tenant_id, 'boss@x.test', user_id=self.user_id,
            user_name='مدير', user_role='company_admin')
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active, is_admin) "
            "VALUES ('platform-admin', 'المنصة', 'root@x.test', 'hash', 1, 1)"
        )
        conn.commit()
        self.admin_token = auth.create_token(
            'platform-admin', 'root@x.test', is_admin=True, user_name='مدير المنصة')
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, token):
        return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    def test_housekeeping_run_requires_admin(self):
        denied = self.client.post(
            '/api/admin/housekeeping/run', headers=self.headers(self.token), json={})
        self.assertEqual(denied.status_code, 403)

    def test_housekeeping_run_returns_step_summary(self):
        response = self.client.post(
            '/api/admin/housekeeping/run',
            headers=self.headers(self.admin_token), json={})
        self.assertEqual(response.status_code, 200, response.get_json())
        summary = response.get_json()['summary']
        for step in ('email', 'reminders', 'escalations',
                     'stale_reservations', 'stale_generation_jobs'):
            self.assertIn(step, summary)

    def test_drain_marks_outbox_and_delivery_rows(self):
        note = db.create_notification(
            self.tenant_id, 'تنبيه', category='general',
            user_id=self.user_id, email_to='boss@x.test')
        module = self.application_module
        original = module.send_platform_email
        module.send_platform_email = lambda *args, **kwargs: True
        try:
            result = module._drain_email_outbox()
        finally:
            module.send_platform_email = original
        self.assertEqual(result, {'sent': 1, 'failed': 0})
        outbox = db.get_db().execute(
            'SELECT status, sent_at FROM email_outbox WHERE notification_id = ?',
            (note['id'],)
        ).fetchone()
        self.assertEqual(outbox['status'], 'sent')
        self.assertTrue(outbox['sent_at'])
        delivery = db.get_db().execute(
            "SELECT status, sent_at FROM notification_deliveries "
            "WHERE notification_id = ? AND channel = 'email'", (note['id'],)
        ).fetchone()
        self.assertEqual(delivery['status'], 'sent')
        self.assertTrue(delivery['sent_at'])


if __name__ == '__main__':
    unittest.main()
