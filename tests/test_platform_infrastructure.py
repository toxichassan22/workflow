"""Mission-5 platform infrastructure tests (t50/t51/t54/t55/t60/t61/t62/t63).

Covers the graph-model tables, company slugs and redirects, the activation
gate, package versions and subscriptions, generation
jobs, the durable job queue, email outbox, study-type and
generator registries, backup history, dashboards and PDF reports, and the
matching admin endpoints. Runs against a temporary SQLite database.
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


class Mission5DbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'mission5.db')
        db.init_db()
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            ('tenant-1', 'Tenant One', 't1@example.test', 'hash', 'free'),
        )
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, plan, is_active) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            ('tenant-2', 'Tenant Two', 't2@example.test', 'hash', 'free'),
        )
        conn.execute(
            "INSERT INTO billing_packages (id, name, price_sar, credit_usd) "
            "VALUES ('pkg-1', 'باقة احترافية', 500, 200)",
            (),
        )
        conn.commit()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    # ── t60: graph model tables and uniqueness ────────────────────────────

    def test_mission5_tables_exist_on_existing_database(self):
        conn = db.get_db()
        tables = {r['name'] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        for table in ('notification_deliveries', 'support_ticket_attachments',
                      'tenant_contract_versions',
                      'tenant_subscriptions', 'billing_package_versions',
                      'topup_receipts', 'generation_jobs', 'document_versions',
                      'tenant_slug_redirects', 'study_types', 'generator_registry',
                      'field_schema_versions', 'job_queue', 'email_outbox',
                      'backup_history'):
            self.assertIn(table, tables, table)

    def test_notification_creates_in_app_delivery(self):
        note = db.create_notification('tenant-1', 'اختبار', body='نص',
                                      email_to='ops@example.test')
        conn = db.get_db()
        rows = conn.execute(
            'SELECT * FROM notification_deliveries WHERE notification_id = ?',
            (note['id'],)).fetchall()
        channels = {r['channel']: r['status'] for r in rows}
        self.assertEqual(channels.get('in_app'), 'delivered')
        self.assertEqual(channels.get('email'), 'queued')

    def test_subscription_replaces_active_one(self):
        first = db.create_subscription('tenant-1', package_id='pkg-1')
        second = db.create_subscription('tenant-1', package_id='pkg-1',
                                        trial_ends_at='2030-01-01T00:00:00')
        current = db.current_subscription('tenant-1')
        self.assertEqual(current['id'], second['id'])
        history = db.list_subscriptions('tenant-1')
        self.assertEqual(len(history), 2)
        self.assertEqual(
            [h['status'] for h in history].count('expired'), 1)

    def test_package_versions_are_immutable_and_numbered(self):
        v1 = db.create_package_version('pkg-1')
        v2 = db.create_package_version('pkg-1', credit_usd=300)
        self.assertEqual(v1['version'], 1)
        self.assertEqual(v2['version'], 2)
        versions = db.list_package_versions('pkg-1')
        self.assertEqual([v['version'] for v in versions], [2, 1])
        self.assertEqual(versions[0]['credit_usd'], 300)

    def test_contract_versions_chain(self):
        contract = db.create_tenant_contract(
            'tenant-1', 'عقد خدمة', signature_status='signed',
            starts_at='2025-01-01', expires_at='2026-01-01')
        self.assertEqual(contract['version'], 1)
        updated = db.add_contract_version('tenant-1', contract['id'],
                                          signature_status='pending_signature')
        self.assertEqual(updated['version'], 2)
        self.assertEqual(updated['signature_status'], 'pending_signature')
        versions = db.list_contract_versions(contract['id'], tenant_id='tenant-1')
        self.assertEqual(len(versions), 2)

    def test_document_versions_number_per_document(self):
        a = db.create_document_version('tenant-1', 'presentation', 'pres-1')
        b = db.create_document_version('tenant-1', 'presentation', 'pres-1')
        other = db.create_document_version('tenant-1', 'presentation', 'pres-2')
        self.assertEqual((a['version'], b['version'], other['version']), (1, 2, 1))

    def test_generation_job_lifecycle(self):
        job = db.create_generation_job('tenant-1', draft_id='d1',
                                       slides_total=5, model='m')
        self.assertEqual(job['status'], 'queued')
        db.update_generation_job(job['id'], status='running')
        db.update_generation_job(job['id'], status='completed', progress=100,
                                 actual_cost_usd=1.5)
        fetched = db.get_generation_job(job['id'], tenant_id='tenant-1')
        self.assertEqual(fetched['status'], 'completed')
        self.assertEqual(fetched['actual_cost_usd'], 1.5)
        metrics = db.generation_job_metrics()
        self.assertEqual(metrics['by_status'].get('completed'), 1)

    # ── t51: slugs ────────────────────────────────────────────────────────

    def test_slug_validation_reserved_invalid_taken(self):
        self.assertEqual(db.validate_company_slug('admin'), {'error': 'reserved'})
        self.assertEqual(db.validate_company_slug('x'), {'error': 'invalid'})
        self.assertEqual(db.validate_company_slug('!!'), {'error': 'invalid'})
        db.get_db().execute(
            "UPDATE tenants SET slug = 'acme' WHERE id = 'tenant-1'")
        db.get_db().commit()
        self.assertEqual(db.validate_company_slug('ACME'), {'error': 'taken'})
        self.assertEqual(
            db.validate_company_slug('acme', exclude_tenant_id='tenant-1'),
            {'slug': 'acme'})

    def test_slug_lock_after_activation_and_redirect(self):
        conn = db.get_db()
        conn.execute("UPDATE tenants SET slug = 'old-co' WHERE id = 'tenant-1'")
        conn.commit()
        result = db.set_tenant_slug('tenant-1', 'new-co')
        self.assertEqual(result.get('error'), 'slug_locked')
        result = db.set_tenant_slug('tenant-1', 'new-co',
                                    allow_after_activation=True)
        self.assertEqual(result['slug'], 'new-co')
        self.assertTrue(result['redirect_created'])
        tenant, redirect = db.resolve_company_slug('old-co')
        self.assertIsNone(tenant)
        self.assertEqual(redirect, 'new-co')
        tenant, redirect = db.resolve_company_slug('new-co')
        self.assertEqual(tenant['id'], 'tenant-1')
        self.assertIsNone(redirect)

    def test_unique_slug_index_blocks_duplicates(self):
        conn = db.get_db()
        conn.execute("UPDATE tenants SET slug = 'dup-co' WHERE id = 'tenant-1'")
        conn.commit()
        with self.assertRaises(Exception):
            conn.execute("UPDATE tenants SET slug = 'dup-co' WHERE id = 'tenant-2'")
            conn.commit()

    # ── t50: activation gate and atomic company create ────────────────────

    def test_activation_gate_blocks_incomplete_company(self):
        result = db.set_tenant_active('tenant-2', True)
        self.assertEqual(result.get('error'), 'activation_incomplete')
        self.assertIn('legal_name', result['missing'])
        self.assertIn('doc:contract', result['missing'])

    def test_activation_stamps_actor_after_complete_file(self):
        conn = db.get_db()
        conn.execute(
            "UPDATE tenants SET legal_name = 'شركة', tax_number = '123', "
            "cr_number = '456', country = 'السعودية' WHERE id = 'tenant-2'")
        conn.commit()
        db.create_tenant_contract('tenant-2', 'عقد', signature_status='signed')
        result = db.set_tenant_active('tenant-2', True,
                                      actor_id='admin-1', actor_name='مدير المنصة')
        self.assertTrue(result['is_active'])
        self.assertEqual(result['activated_by'], 'admin-1')
        self.assertTrue(result['activated_at'])
        suspended = db.set_tenant_active('tenant-2', False, reason='عدم سداد')
        self.assertFalse(suspended['is_active'])
        self.assertEqual(suspended['deactivated_reason'], 'عدم سداد')

    def test_atomic_company_create_with_profile_slug_and_contract(self):
        tenant_id, user_id = db.create_company_with_admin(
            'شركة تجريبية', 'مدير', 'atomic@example.test', 'atomic_co',
            '+966500000009', 'hash', plan='pro',
            is_active=False,
            profile={'legal_name': 'شركة تجريبية ذ.م.م', 'tax_number': '300',
                     'cr_number': '1010', 'country': 'السعودية'},
            slug='Atomic Co', package_id='pkg-1', trial_days=30,
            contracts=[{'kind': 'contract', 'title': 'عقد الافتتاح',
                        'signature_status': 'signed'}],
        )
        tenant = db.get_tenant_by_id(tenant_id)
        self.assertEqual(tenant['slug'], 'atomic-co')
        self.assertEqual(tenant['legal_name'], 'شركة تجريبية ذ.م.م')
        self.assertEqual(tenant['package_id'], 'pkg-1')
        self.assertTrue(tenant['trial_ends_at'])
        sub = db.current_subscription(tenant_id)
        self.assertEqual(sub['package_id'], 'pkg-1')
        contracts = db.list_tenant_contracts(tenant_id)
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0]['signature_status'], 'signed')
        checklist = db.tenant_activation_checklist(tenant)
        self.assertTrue(checklist['complete'], checklist['missing'])

    def test_company_create_rolls_back_on_slug_conflict(self):
        db.create_company_with_admin(
            'شركة أولى', 'مدير', 'first@example.test', 'first_co',
            '+966500000011', 'hash', slug='rollback-co')
        with self.assertRaises(Exception):
            db.create_company_with_admin(
                'شركة ثانية', 'مدير', 'second@example.test', 'second_co',
                '+966500000012', 'hash', slug='rollback-co')
        self.assertIsNone(db.get_tenant_by_email('second@example.test'))

    # ── t62: registries, feature flags, schema versions ───────────────────

    def test_study_type_versions(self):
        v1 = db.register_study_type('feasibility', 'دراسة جدوى',
                                    definition={'sections': ['a']})
        v2 = db.register_study_type('feasibility', 'دراسة جدوى',
                                    definition={'sections': ['a', 'b']})
        self.assertEqual((v1['version'], v2['version']), (1, 2))
        latest = db.get_study_type('feasibility')
        self.assertEqual(latest['version'], 2)
        pinned = db.get_study_type('feasibility', version=1)
        self.assertEqual(pinned['definition']['sections'], ['a'])
        self.assertEqual(db.register_study_type('!!', 'x'), {'error': 'invalid_key'})

    def test_generator_registry_versions(self):
        v1 = db.register_generator('slide_template', 'classic',
                                   label_ar='كلاسيكي')
        v2 = db.register_generator('slide_template', 'classic',
                                   config={'density': 'compact'})
        self.assertEqual((v1['version'], v2['version']), (1, 2))
        latest = db.get_generator('slide_template', 'classic')
        self.assertEqual(latest['config'], {'density': 'compact'})
        self.assertEqual(
            db.register_generator('bogus', 'x'), {'error': 'invalid_kind'})

    def test_field_schema_snapshot_versions(self):
        snap1 = db.snapshot_field_schema('tenant-1')
        snap2 = db.snapshot_field_schema('tenant-1')
        self.assertEqual((snap1['version'], snap2['version']), (1, 2))
        self.assertIsInstance(snap1['schema'], list)
        self.assertEqual(db.latest_field_schema_version('tenant-1'), 2)

    def test_file_type_rule_from_registry(self):
        rule = db.get_file_type_rule('deed_file')
        self.assertIsNotNone(rule)
        self.assertIn('.pdf', rule['allowed_extensions'])
        self.assertIsNone(db.get_file_type_rule('not_registered'))

    # ── t61: durable queue and email outbox ───────────────────────────────

    def test_job_queue_claim_complete_fail_dead(self):
        job = db.enqueue_job('generate', payload={'x': 1}, tenant_id='tenant-1')
        claimed = db.claim_due_jobs('worker-1')
        self.assertEqual([j['id'] for j in claimed], [job['id']])
        self.assertEqual(claimed[0]['attempts'], 1)
        self.assertEqual(claimed[0]['payload'], {'x': 1})
        db.complete_job(job['id'], worker_id='worker-1')
        self.assertEqual(db.list_jobs(status='done')[0]['id'], job['id'])

        failing = db.enqueue_job('flaky', max_attempts=1)
        claimed = db.claim_due_jobs('worker-1')
        self.assertIn(failing['id'], [j['id'] for j in claimed])
        db.fail_job(failing['id'], error='boom')
        self.assertEqual(db.list_jobs(status='dead')[0]['id'], failing['id'])
        requeued = db.requeue_dead_jobs(job_type='flaky')
        self.assertEqual(requeued, 1)
        self.assertEqual(db.list_jobs(status='queued')[0]['id'], failing['id'])

    def test_email_outbox_lifecycle(self):
        row = db.enqueue_email('ops@example.test', 'موضوع',
                               body_text='نص', tenant_id='tenant-1')
        due = db.claim_due_emails()
        self.assertEqual([e['id'] for e in due], [row['id']])
        db.mark_email_sent(row['id'])
        stats = db.email_outbox_stats()
        self.assertEqual(stats.get('sent'), 1)

        failing = db.enqueue_email('x@example.test', 'x')
        db.claim_due_emails()
        for _ in range(6):
            db.mark_email_failed(failing['id'], error='smtp down')
            db.claim_due_emails()
        self.assertEqual(db.list_email_outbox(status='dead')[0]['id'],
                         failing['id'])

    # ── t54/t63: monitoring and backups ───────────────────────────────────

    def test_platform_alerts_returns_list(self):
        self.assertIsInstance(db.platform_alerts(), list)

    def test_backup_registry_cycle(self):
        row = db.record_backup(kind='full', path='/tmp/x.enc',
                               size_bytes=10, sha256='abc', encrypted=True)
        self.assertEqual(row['status'], 'done')
        self.assertEqual(db.latest_successful_backup()['id'], row['id'])
        tested = db.mark_backup_restore_tested(row['id'], note='ok')
        self.assertTrue(tested['restore_tested_at'])

    def test_storage_overview_counts_bytes(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO project_files (id, tenant_id, file_type, original_name, "
            "storage_path, mime_type, sha256, file_size) "
            "VALUES ('f1', 'tenant-1', 'deed_file', 'a.pdf', 'x', 'application/pdf', 'h1', 2048)")
        conn.commit()
        overview = db.storage_overview()
        self.assertEqual(overview['total_bytes'], 2048)
        self.assertEqual(overview['per_tenant'][0]['tenant_id'], 'tenant-1')

    # ── t55: dashboards and CSV reports ───────────────────────────────────

    def test_client_dashboard_shape(self):
        dash = db.client_dashboard('tenant-1')
        self.assertIn('lifecycle', dash)
        self.assertIn('open_approval_tasks', dash)
        self.assertIn('month_consumption_usd', dash)
        keys = {b['key'] for b in dash['lifecycle']}
        self.assertIn('draft', keys)

    def test_company_admin_dashboard_shape(self):
        dash = db.company_admin_dashboard('tenant-1')
        for key in ('overdue_sections', 'avg_approval_hours',
                    'spend_by_project', 'activity_by_user'):
            self.assertIn(key, dash)

    def test_report_rows_return_headers_and_data(self):
        db.record_ledger_credit('tenant-1', 50, note='شحن')
        for name, fn in (('ledger', db.ledger_report_rows),
                         ('tickets', db.tickets_report_rows)):
            headers, body = fn()
            self.assertTrue(headers, name)
            self.assertIsInstance(body, list, name)
        _, ledger_rows = db.ledger_report_rows(tenant_id='tenant-1')
        flat = [str(cell) for row in ledger_rows for cell in row]
        self.assertIn('شحن', flat)
        self.assertIn('Tenant One', flat)

    def test_ticket_carries_project_link(self):
        ticket = db.create_support_ticket(
            'tenant-1', 'مشكلة', priority='high', draft_id='draft-9')
        self.assertEqual(ticket['draft_id'], 'draft-9')


class Mission5ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'mission5-api.db')

        import app as application_module

        cls.app = application_module.app
        cls.app.config.update(TESTING=True)

        with cls.app.app_context():
            cls.admin_id = db.create_tenant(
                'System Admin', 'sysadmin@example.test',
                auth.hash_password('AdminPass12345'), plan='enterprise')
            db.get_db().execute(
                'UPDATE tenants SET is_admin = 1 WHERE id = ?', (cls.admin_id,))
            db.get_db().commit()
            cls.company_id, cls.admin_user_id = db.create_company_with_admin(
                'شركة الاختبار', 'مدير', 'company@example.test', 'm5_company',
                '+966500000020', auth.hash_password('CompanyPass123'),
                plan='pro', is_active=True)

        cls.admin_headers = {'Authorization': 'Bearer ' + auth.create_token(
            cls.admin_id, 'sysadmin@example.test', is_admin=True,
            user_name='System Admin', user_role='company_admin')}
        cls.company_headers = {'Authorization': 'Bearer ' + auth.create_token(
            cls.company_id, 'company@example.test', is_admin=False,
            user_id=cls.admin_user_id, user_name='مدير',
            user_role='company_admin')}

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = self.app.test_client()

    def test_slug_endpoint_validates_and_sets(self):
        res = self.client.put(
            f'/api/admin/tenants/{self.company_id}/slug',
            headers=self.admin_headers, json={'slug': 'admin'})
        self.assertEqual(res.status_code, 400)
        res = self.client.put(
            f'/api/admin/tenants/{self.company_id}/slug',
            headers=self.admin_headers, json={'slug': 'M5-Co'})
        self.assertEqual(res.status_code, 409, res.get_json())
        self.assertEqual(res.get_json()['error'], 'slug_locked')
        res = self.client.put(
            f'/api/admin/tenants/{self.company_id}/slug',
            headers=self.admin_headers,
            json={'slug': 'M5-Co', 'allowAfterActivation': True})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json()['slug'], 'm5-co')
        denied = self.client.put(
            f'/api/admin/tenants/{self.company_id}/slug',
            headers=self.company_headers, json={'slug': 'x-co'})
        self.assertEqual(denied.status_code, 403)

    def test_activation_gate_endpoint(self):
        with self.app.app_context():
            gate_tenant_id, _ = db.create_company_with_admin(
                'شركة البوابة', 'مدير', 'gate@example.test', 'gate_company',
                '+966500000030', 'hash', is_active=False)
        res = self.client.get(
            f'/api/admin/tenants/{gate_tenant_id}/activation',
            headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertFalse(body['checklist']['complete'])

        res = self.client.post(
            f'/api/admin/tenants/{gate_tenant_id}/activation',
            headers=self.admin_headers, json={'isActive': True})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()['error'], 'activation_incomplete')

        res = self.client.post(
            f'/api/admin/tenants/{gate_tenant_id}/contracts',
            headers=self.admin_headers,
            json={'title': 'عقد الافتتاح', 'kind': 'contract',
                  'signatureStatus': 'signed'})
        self.assertEqual(res.status_code, 201, res.get_json())
        self.client.put(
            f'/api/admin/tenants/{gate_tenant_id}',
            headers=self.admin_headers,
            json={'legalName': 'شركة البوابة ذ.م.م', 'taxNumber': '3001',
                  'crNumber': '101', 'country': 'السعودية'})
        res = self.client.post(
            f'/api/admin/tenants/{gate_tenant_id}/activation',
            headers=self.admin_headers, json={'isActive': True})
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertTrue(res.get_json()['tenant']['isActive'])

    def test_contract_versions_endpoint(self):
        created = self.client.post(
            f'/api/admin/tenants/{self.company_id}/contracts',
            headers=self.admin_headers, json={'title': 'اتفاقية'})
        contract_id = created.get_json()['contract']['id']
        res = self.client.post(
            f'/api/admin/tenants/{self.company_id}/contracts/{contract_id}/versions',
            headers=self.admin_headers, json={'signatureStatus': 'signed'})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()['contract']['version'], 2)
        res = self.client.get(
            f'/api/admin/tenants/{self.company_id}/contracts/{contract_id}/versions',
            headers=self.admin_headers)
        self.assertEqual(len(res.get_json()['versions']), 2)

    def test_reports_pdf_export(self):
        import unittest.mock as mock
        import app as app_module

        def fake_pdf(html, out_path, model=None, project_name='', min_text=200):
            with open(out_path, 'wb') as handle:
                handle.write(b'%PDF-1.4 test-report')
            return out_path

        with mock.patch.object(app_module, 'generate_financial_pdf', fake_pdf):
            res = self.client.get('/api/admin/reports/ledger',
                                  headers=self.admin_headers)
            self.assertEqual(res.status_code, 200)
            self.assertIn('application/pdf', res.headers['Content-Type'])
            self.assertTrue(res.data.startswith(b'%PDF'))
            res = self.client.get('/api/company/reports/tickets',
                                  headers=self.company_headers)
            self.assertEqual(res.status_code, 200)
        denied = self.client.get('/api/admin/reports/ledger',
                                 headers=self.company_headers)
        self.assertEqual(denied.status_code, 403)
        res = self.client.get('/api/admin/reports/nope',
                              headers=self.admin_headers)
        self.assertEqual(res.status_code, 404)

    def test_dashboards_endpoints(self):
        res = self.client.get('/api/dashboard', headers=self.company_headers)
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertIn('lifecycle', res.get_json()['dashboard'])
        res = self.client.get('/api/company/dashboard',
                              headers=self.company_headers)
        self.assertEqual(res.status_code, 200)
        res = self.client.get('/api/admin/operational-overview',
                              headers=self.admin_headers)
        overview = res.get_json()['overview']
        for key in ('alerts', 'storage', 'generation', 'queue', 'backup'):
            self.assertIn(key, overview)

    def test_jobs_and_backups_endpoints(self):
        res = self.client.get('/api/admin/jobs', headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        res = self.client.get('/api/admin/email-outbox',
                              headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        res = self.client.post('/api/admin/backups', headers=self.admin_headers,
                               json={'kind': 'manual', 'sizeBytes': 5,
                                     'sha256': 'x', 'encrypted': True})
        self.assertEqual(res.status_code, 201)
        backup_id = res.get_json()['backup']['id']
        res = self.client.post(
            f'/api/admin/backups/{backup_id}/restore-tested',
            headers=self.admin_headers, json={'note': 'ok'})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['backup']['restore_tested_at'])

    def test_study_types_and_generators_endpoints(self):
        res = self.client.post('/api/admin/study-types', headers=self.admin_headers,
                               json={'key': 'feasibility', 'nameAr': 'دراسة جدوى',
                                     'definition': {'sections': ['a']}})
        self.assertEqual(res.status_code, 201)
        res = self.client.get('/api/admin/study-types',
                              headers=self.admin_headers)
        self.assertEqual(res.get_json()['studyTypes'][0]['key'], 'feasibility')
        res = self.client.post('/api/admin/generators', headers=self.admin_headers,
                               json={'kind': 'slide_template', 'key': 'classic',
                                     'labelAr': 'كلاسيكي'})
        self.assertEqual(res.status_code, 201)
        res = self.client.get('/api/admin/generators?kind=slide_template',
                              headers=self.admin_headers)
        self.assertEqual(res.get_json()['generators'][0]['key'], 'classic')

    def test_slug_redirect_serves_301(self):
        with self.app.app_context():
            db.set_tenant_slug(self.company_id, 'm5-redirect',
                               allow_after_activation=True)
            db.set_tenant_slug(self.company_id, 'm5-final',
                               allow_after_activation=True)
        res = self.client.get('/c/m5-redirect',
                              headers={'Accept': 'text/html'})
        self.assertEqual(res.status_code, 301)
        self.assertIn('/c/m5-final', res.headers['Location'])

    def test_signed_download_url(self):
        import app as application_module
        tenant_dir = os.path.join(
            application_module.UPLOADS_DIR, self.company_id, 'project-documents')
        os.makedirs(tenant_dir, exist_ok=True)
        file_path = os.path.join(tenant_dir, 'signed-test.txt')
        with open(file_path, 'w', encoding='utf-8') as fh:
            fh.write('signed-payload')
        try:
            with self.app.app_context():
                conn = db.get_db()
                conn.execute(
                    "INSERT INTO project_files (id, tenant_id, file_type, "
                    "original_name, storage_path, mime_type, sha256, file_size) "
                    "VALUES ('signed-f1', ?, 'deed_file', 'doc.txt', ?, "
                    "'text/plain', 'sig', 14)", (self.company_id, file_path))
                conn.commit()
            res = self.client.post(
                '/api/project-files/signed-f1/signed-url',
                headers=self.company_headers)
            self.assertEqual(res.status_code, 200, res.get_json())
            url = res.get_json()['url']
            got = self.client.get(url)
            self.assertEqual(got.status_code, 200)
            self.assertEqual(got.data, b'signed-payload')
            bad = self.client.get(url[:-4] + 'dead')
            self.assertEqual(bad.status_code, 403)
        finally:
            try:
                os.remove(file_path)
            except OSError:
                pass


if __name__ == '__main__':
    unittest.main()
