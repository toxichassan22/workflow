"""PostgreSQL parity checks (t63).

The suite is skipped unless TEST_DATABASE_URL points at a reachable Postgres
DSN (postgres:// or postgresql://). Point it at a disposable database — the
schema build creates every table. It verifies the pieces SQLite-only tests
cannot prove: the full schema runs on Postgres, the audit immutability
trigger actually blocks UPDATE/DELETE there, unique constraints hold under
the escrow model, and tenant-scoped reads never leak across companies.
"""

import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import db
import db_driver

DSN = os.environ.get('TEST_DATABASE_URL') or ''


def _postgres_ready():
    if not db_driver._is_postgres_dsn(DSN):
        return False
    try:
        conn = db_driver.connect(DSN)
        conn.execute('SELECT 1')
        conn.close()
        return True
    except Exception:
        return False


def _make_tenant(prefix='pg'):
    tenant_id = f'{prefix}-tenant-' + uuid.uuid4().hex[:8]
    conn = db.get_db()
    conn.execute(
        "INSERT INTO tenants (id, company_name, email, password_hash, is_active, credit_balance) "
        "VALUES (?, ?, ?, 'hash', 1, 500)",
        (tenant_id, 'شركة اختبار', f'{tenant_id}@x.test'),
    )
    conn.commit()
    return tenant_id


@unittest.skipUnless(_postgres_ready(),
                     'TEST_DATABASE_URL is not a reachable Postgres DSN')
class PostgresParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_db_path = db.DB_PATH
        db.DB_PATH = DSN

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._original_db_path

    def setUp(self):
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        db.close_db()
        self.context.pop()

    def test_full_schema_builds(self):
        db.init_db()
        conn = db.get_db()
        names = {
            row['name'] if isinstance(row, dict) or hasattr(row, 'keys') else row[0]
            for row in conn.execute(
                "SELECT table_name AS name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            ).fetchall()
        }
        for table in ('tenants', 'users', 'audit_events', 'approval_tasks',
                      'email_outbox', 'job_queue', 'tenant_ledger',
                      'point_reservations', 'support_tickets', 'recharge_requests'):
            self.assertIn(table, names)

    def test_audit_events_are_immutable(self):
        db.init_db()
        conn = db.get_db()
        tenant_id = _make_tenant()
        db.record_audit_event(tenant_id, 'test.event', 'tenant', tenant_id)
        event = conn.execute(
            'SELECT id FROM audit_events WHERE tenant_id = ?', (tenant_id,)
        ).fetchone()
        with self.assertRaises(Exception):
            conn.execute(
                "UPDATE audit_events SET action = 'tampered' WHERE id = ?",
                (event['id'],),
            )
        conn.rollback()
        with self.assertRaises(Exception):
            conn.execute('DELETE FROM audit_events WHERE id = ?', (event['id'],))
        conn.rollback()

    def test_approval_task_lifecycle(self):
        db.init_db()
        tenant_id = _make_tenant()
        task = db.create_approval_task(
            tenant_id, 'section_approval', 'اعتماد قسم', due_hours=48)
        self.assertEqual(task['status'], 'open')
        reminded = db.remind_approval_task(tenant_id, task['id'])
        self.assertTrue(reminded['reminded_at'])
        closed = db.close_approval_task(tenant_id, task['id'])
        self.assertEqual(closed['status'], 'done')

    def test_approval_tasks_are_tenant_scoped(self):
        db.init_db()
        first = _make_tenant('pg-a')
        second = _make_tenant('pg-b')
        task = db.create_approval_task(first, 'support', 'تذكرة', due_hours=24)
        feed = db.list_approval_tasks(second, status='all')
        self.assertNotIn(task['id'], [t['id'] for t in feed])
        self.assertTrue(db.list_approval_tasks(first, status='all'))

    def test_close_tasks_for_entity(self):
        db.init_db()
        tenant_id = _make_tenant()
        for _ in range(2):
            db.create_approval_task(
                tenant_id, 'section_approval', 'اعتماد',
                entity_type='section_version', entity_id='v-1', due_hours=12)
        closed = db.close_approval_tasks_for_entity(tenant_id, 'section_version', 'v-1')
        self.assertEqual(closed, 2)

    def test_point_reservation_escrow_and_single_consume(self):
        db.init_db()
        tenant_id = _make_tenant()
        held = db.reserve_points(
            tenant_id, 50, cost_usd=10, generation_approval_id='ga-1')
        self.assertNotIn('error', held)
        # a retried hold on the same operation returns the live row
        again = db.reserve_points(
            tenant_id, 50, cost_usd=10, generation_approval_id='ga-1')
        self.assertEqual(held['id'], again['id'])
        settled = db.consume_points(tenant_id, held['id'])
        self.assertNotIn('error', settled)
        self.assertEqual(
            db.consume_points(tenant_id, held['id']).get('error'),
            'reservation_not_reserved')

    def test_support_ticket_isolation(self):
        db.init_db()
        first = _make_tenant('pg-a')
        second = _make_tenant('pg-b')
        ticket = db.create_support_ticket(first, 'مشكلة', priority='high')
        self.assertEqual(ticket['priority'], 'high')
        other_feed = db.list_support_tickets(second)
        self.assertNotIn(ticket['id'], [t['id'] for t in other_feed])

    def test_recharge_reference_dedupe(self):
        db.init_db()
        tenant_id = _make_tenant()
        ref = 'TRX-' + uuid.uuid4().hex[:10]
        first = db.create_recharge_request(tenant_id, 'باقة', transfer_reference=ref)
        self.assertNotIn('error', first)
        second = db.create_recharge_request(tenant_id, 'باقة', transfer_reference=ref)
        self.assertEqual(second.get('error'), 'duplicate_transfer_reference')

    def test_email_outbox_lifecycle(self):
        db.init_db()
        row = db.enqueue_email('pg@x.test', 'موضوع', tenant_id=_make_tenant())
        claimed = db.claim_due_emails()
        self.assertIn(row['id'], [c['id'] for c in claimed])
        db.mark_email_sent(row['id'])
        final = db.get_db().execute(
            'SELECT status FROM email_outbox WHERE id = ?', (row['id'],)
        ).fetchone()
        self.assertEqual(final['status'], 'sent')


if __name__ == '__main__':
    unittest.main()
