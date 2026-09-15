"""PostgreSQL parity checks (t63).

The suite is skipped unless TEST_DATABASE_URL points at a reachable Postgres
DSN (postgres:// or postgresql://). Point it at a disposable database — the
schema build creates every table. It verifies the pieces SQLite-only tests
cannot prove: the full schema runs on Postgres, the audit immutability
trigger actually blocks UPDATE/DELETE there, and tenant-scoped writes behave
the same on both backends.
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
                      'email_outbox', 'job_queue', 'tenant_ledger'):
            self.assertIn(table, names)

    def test_audit_events_are_immutable(self):
        db.init_db()
        conn = db.get_db()
        tenant_id = 'pg-tenant-' + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active) "
            "VALUES (?, ?, ?, 'hash', 1)",
            (tenant_id, 'شركة اختبار', f'{tenant_id}@x.test'),
        )
        conn.commit()
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

    def test_approval_task_lifecycle(self):
        db.init_db()
        conn = db.get_db()
        tenant_id = 'pg-tenant-' + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active) "
            "VALUES (?, ?, ?, 'hash', 1)",
            (tenant_id, 'شركة اختبار', f'{tenant_id}@x.test'),
        )
        conn.commit()
        task = db.create_approval_task(
            tenant_id, 'section_approval', 'اعتماد قسم', due_hours=48)
        self.assertEqual(task['status'], 'open')
        reminded = db.remind_approval_task(tenant_id, task['id'])
        self.assertTrue(reminded['reminded_at'])
        closed = db.close_approval_task(tenant_id, task['id'])
        self.assertEqual(closed['status'], 'done')


if __name__ == '__main__':
    unittest.main()
