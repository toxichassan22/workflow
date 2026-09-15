"""Immutable unified audit log tests (t11).

Covers db.audit_events (immutable ledger, append-only triggers,
filtering, pagination, CSV export with UTF-8 BOM) and the /api/audit-log*
endpoints. Runs against a temporary SQLite database and never calls external APIs.
"""

import csv
import io
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


class AuditLogDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'audit-log.db')
        db.init_db()
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()

        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('tenant-1', 'Tenant One', 'tenant1', 'tenant1@example.test', 'hash', 'free'),
        )
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('tenant-2', 'Tenant Two', 'tenant2', 'tenant2@example.test', 'hash', 'free'),
        )
        conn.commit()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_audit_events_table_and_triggers_exist(self):
        """Table, indices, and triggers must exist and recreate cleanly."""
        conn = db.get_db()
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()
        self.assertIsNotNone(table)

        triggers = [r['name'] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_audit_events%'"
        ).fetchall()]
        self.assertIn('trg_audit_events_no_update', triggers)
        self.assertIn('trg_audit_events_no_delete', triggers)

    def test_audit_events_immutability_triggers(self):
        """Direct SQL UPDATE or DELETE on audit_events must be rejected by SQLite triggers."""
        event = db.record_audit_event(
            tenant_id='tenant-1',
            action='create',
            entity_type='project_draft',
            entity_id='draft-100',
            user_id='user-1',
            user_name='User One',
            new_value={'name': 'مشروع أ'},
        )
        self.assertIsNotNone(event['id'])

        conn = db.get_db()
        with self.assertRaises(Exception):
            conn.execute("UPDATE audit_events SET action = 'modified' WHERE id = ?", (event['id'],))

        with self.assertRaises(Exception):
            conn.execute("DELETE FROM audit_events WHERE id = ?", (event['id'],))

    def test_record_and_get_audit_event(self):
        """Audit events record and deserialize JSON structures, strings, and metadata."""
        old_data = {'status': 'draft', 'area': 1000}
        new_data = {'status': 'submitted', 'area': 1200}
        meta = {'ip': '127.0.0.1', 'browser': 'Chrome'}

        created = db.record_audit_event(
            tenant_id='tenant-1',
            action='section_submit',
            entity_type='section_version',
            entity_id='ver-1',
            entity_name='البيانات الأساسية',
            user_id='user-1',
            user_name='User One',
            user_role='editor',
            old_value=old_data,
            new_value=new_data,
            metadata=meta,
        )

        fetched = db.get_audit_event('tenant-1', created['id'])
        self.assertEqual(fetched['action'], 'section_submit')
        self.assertEqual(fetched['entity_type'], 'section_version')
        self.assertEqual(fetched['entity_id'], 'ver-1')
        self.assertEqual(fetched['entity_name'], 'البيانات الأساسية')
        self.assertEqual(fetched['user_name'], 'User One')
        self.assertEqual(fetched['user_role'], 'editor')
        self.assertEqual(fetched['old_value'], old_data)
        self.assertEqual(fetched['new_value'], new_data)
        self.assertEqual(fetched['metadata'], meta)

    def test_list_audit_events_filters_and_pagination(self):
        """Filtering by entity_type, entity_id, action, user_id, dates, and pagination works."""
        base_time = datetime(2026, 9, 1, 10, 0, 0)
        for i in range(10):
            ts = (base_time + timedelta(hours=i)).isoformat()
            action = 'draft_save' if i % 2 == 0 else 'section_approve'
            etype = 'project_draft' if i < 5 else 'section_version'
            eid = f'entity-{i}'
            uid = 'user-1' if i < 7 else 'user-2'
            db.record_audit_event(
                tenant_id='tenant-1',
                action=action,
                entity_type=etype,
                entity_id=eid,
                user_id=uid,
                created_at=ts,
            )

        all_events = db.list_audit_events('tenant-1', limit=20)
        self.assertEqual(all_events['total'], 10)
        self.assertEqual(len(all_events['events']), 10)
        # Should be sorted newest first
        self.assertGreater(all_events['events'][0]['created_at'], all_events['events'][9]['created_at'])

        paged = db.list_audit_events('tenant-1', limit=3, offset=0)
        self.assertEqual(len(paged['events']), 3)
        self.assertEqual(paged['total'], 10)
        self.assertEqual(paged['limit'], 3)
        self.assertEqual(paged['offset'], 0)

        by_type = db.list_audit_events('tenant-1', entity_type='project_draft')
        self.assertEqual(by_type['total'], 5)

        by_action = db.list_audit_events('tenant-1', action='section_approve')
        self.assertEqual(by_action['total'], 5)

        by_user = db.list_audit_events('tenant-1', user_id='user-2')
        self.assertEqual(by_user['total'], 3)

        date_filtered = db.list_audit_events(
            'tenant-1',
            from_date=(base_time + timedelta(hours=2)).isoformat(),
            to_date=(base_time + timedelta(hours=4)).isoformat(),
        )
        self.assertEqual(date_filtered['total'], 3)

    def test_tenant_isolation(self):
        """Events created by tenant-1 cannot be read or retrieved by tenant-2."""
        ev1 = db.record_audit_event(
            tenant_id='tenant-1',
            action='create',
            entity_type='project_draft',
            entity_id='draft-1',
        )
        ev2 = db.record_audit_event(
            tenant_id='tenant-2',
            action='create',
            entity_type='project_draft',
            entity_id='draft-2',
        )

        self.assertIsNone(db.get_audit_event('tenant-2', ev1['id']))
        self.assertIsNone(db.get_audit_event('tenant-1', ev2['id']))

        t1_events = db.list_audit_events('tenant-1')
        self.assertEqual(t1_events['total'], 1)
        self.assertEqual(t1_events['events'][0]['id'], ev1['id'])

        t2_events = db.list_audit_events('tenant-2')
        self.assertEqual(t2_events['total'], 1)
        self.assertEqual(t2_events['events'][0]['id'], ev2['id'])

    def test_export_audit_events_csv(self):
        """CSV export must include UTF-8 BOM, Arabic headers, and correct values."""
        db.record_audit_event(
            tenant_id='tenant-1',
            action='section_approve',
            entity_type='section_version',
            entity_id='ver-12',
            entity_name='القسم المالي',
            user_id='u-99',
            user_name='أحمد',
            user_role='admin',
            old_value={'cost': 5000},
            new_value={'cost': 4500},
        )
        csv_text = db.export_audit_events_csv('tenant-1')
        self.assertTrue(csv_text.startswith('\ufeff'), "CSV must start with UTF-8 BOM")

        # Parse CSV lines
        reader = csv.reader(io.StringIO(csv_text[1:]))
        rows = list(reader)
        self.assertGreaterEqual(len(rows), 2)
        headers = rows[0]
        self.assertIn('معرف الحدث', headers)
        self.assertIn('التاريخ والوقت', headers)
        self.assertIn('اسم المستخدم', headers)
        self.assertIn('نوع العملية', headers)

        data_row = rows[1]
        self.assertEqual(data_row[3], 'أحمد')
        self.assertEqual(data_row[5], 'section_approve')
        self.assertEqual(data_row[8], 'القسم المالي')

    def test_project_copy_does_not_inherit_audit_events(self):
        """Section 19 Rule 6: Copying a project must not copy old audit events to the new entity."""
        db.record_audit_event(
            tenant_id='tenant-1',
            action='draft_create',
            entity_type='project_draft',
            entity_id='draft-source',
            new_value={'name': 'أصل'},
        )
        db.record_audit_event(
            tenant_id='tenant-1',
            action='draft_update',
            entity_type='project_draft',
            entity_id='draft-source',
            new_value={'name': 'تعديل'},
        )
        source_events = db.list_audit_events('tenant-1', entity_type='project_draft', entity_id='draft-source')
        self.assertEqual(source_events['total'], 2)

        copied_events = db.list_audit_events('tenant-1', entity_type='project_draft', entity_id='draft-copied')
        self.assertEqual(copied_events['total'], 0)


class AuditLogApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_module
        cls.flask_app = app_module.app
        cls.flask_app.config.update(TESTING=True)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'audit-api.db')
        db.init_db()
        self.context = self.flask_app.app_context()
        self.context.push()

        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('tenant-1', 'Audit Test Co', 'audit-test', 'audit@example.test', 'hash', 'free'),
        )
        conn.execute(
            "INSERT INTO users (id, tenant_id, email, password_hash, name, role, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            ('admin-1', 'tenant-1', 'audit@example.test', 'hash', 'مدير الاختبار', 'company_admin'),
        )
        conn.commit()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, tenant_id='tenant-1', user_id='admin-1', role='company_admin'):
        token = auth.create_token(
            tenant_id, 'audit@example.test', is_admin=True,
            user_id=user_id, user_name='مدير الاختبار', user_role=role
        )
        return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def test_api_endpoints_list_and_get(self):
        client = self.flask_app.test_client()
        ev = db.record_audit_event(
            tenant_id='tenant-1',
            action='login',
            entity_type='user_session',
            entity_id='sess-1',
            user_id='admin-1',
            user_name='مدير الاختبار',
            user_role='company_admin',
        )

        resp = client.get('/api/audit-log', headers=self.headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['events'][0]['id'], ev['id'])

        single_resp = client.get(f'/api/audit-log/{ev["id"]}', headers=self.headers())
        self.assertEqual(single_resp.status_code, 200)
        self.assertEqual(single_resp.get_json()['event']['id'], ev['id'])

        not_found = client.get('/api/audit-log/non-existent-id', headers=self.headers())
        self.assertEqual(not_found.status_code, 404)

    def test_api_export_endpoint(self):
        client = self.flask_app.test_client()
        db.record_audit_event(
            tenant_id='tenant-1',
            action='settings_update',
            entity_type='tenant_branding',
            entity_id='tenant-1',
            user_id='admin-1',
            user_name='مدير الاختبار',
        )
        resp = client.get('/api/audit-log/export', headers=self.headers())
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.content_type)
        self.assertIn('attachment; filename=audit-log.csv', resp.headers.get('Content-Disposition', ''))
        content = resp.data.decode('utf-8')
        self.assertTrue(content.startswith('\ufeff'))
        self.assertIn('settings_update', content)

    def test_api_immutability_endpoints(self):
        client = self.flask_app.test_client()
        for method in ['post', 'put', 'patch', 'delete']:
            fn = getattr(client, method)
            resp = fn('/api/audit-log', headers=self.headers(), json={'action': 'test'})
            self.assertEqual(resp.status_code, 405)
            self.assertEqual(resp.get_json().get('error_code'), 'AUDIT_LOG_IMMUTABLE')

            resp_sub = fn('/api/audit-log/some-event-id', headers=self.headers(), json={'action': 'test'})
            self.assertEqual(resp_sub.status_code, 405)
            self.assertEqual(resp_sub.get_json().get('error_code'), 'AUDIT_LOG_IMMUTABLE')


if __name__ == '__main__':
    unittest.main()
