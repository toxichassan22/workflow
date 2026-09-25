# -*- coding: utf-8 -*-
"""Operations-section coverage: super-admin announcements, the low-balance
warning, and support-ticket priority/attachment rules."""
import io
import os
import sys
import tempfile
import threading
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
import db


class OpsSectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'ops-section.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        application_module.OPENROUTER_MANAGEMENT_KEY = None
        self.context = self.app.app_context()
        self.context.push()
        self.tenant_id = db.create_tenant('شركة العمق', 'ops@x.test', 'hash', 'ops-co')
        self.other_tenant_id = db.create_tenant('شركة أخرى', 'ops2@x.test', 'hash', 'ops-co-2')
        self.user_id = db.create_user(
            self.tenant_id, 'مدير الشركة', 'ops-admin@x.test', 'hash', role='employee')
        db.update_tenant(self.tenant_id, primary_user_id=self.user_id)
        db.grant_company_admin_permissions(self.user_id)
        self.token = auth.create_token(
            self.tenant_id, 'ops-admin@x.test', user_id=self.user_id,
            user_name='مدير الشركة', user_role='company_admin')
        self.other_token = auth.create_token(
            self.other_tenant_id, 'ops2@x.test', user_id=None,
            user_name='مدير آخر', user_role='company_admin')
        self.client = self.app.test_client()

    def tearDown(self):
        for thread in threading.enumerate():
            if thread.name.startswith(('usage-bill-', 'cap-sync-')):
                thread.join(timeout=10)
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, token):
        return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    def _admin_token(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO tenants (id, company_name, email, password_hash, is_active, is_admin) "
            "VALUES ('platform-adm', 'المنصة', 'root@x.test', 'hash', 1, 1) "
            "ON CONFLICT(id) DO NOTHING")
        conn.commit()
        return auth.create_token(
            'platform-adm', 'root@x.test', is_admin=True, user_name='مدير المنصة')

    def _approve_recharge(self, tenant_id, credit_sar, reference):
        package = db.create_billing_package(
            'باقة ' + reference, credit_sar=credit_sar, price_sar=credit_sar)
        request_row = db.create_recharge_request(
            tenant_id, package['name'], package_id=package['id'],
            transfer_reference=reference)
        self.assertNotIn('error', request_row)
        decided = db.decide_recharge_request(
            None, request_row['id'], 'approved', 'admin-1', 'مدير المنصة')
        self.assertEqual(decided.get('status'), 'approved', decided)
        return decided

    def _feed(self, token, **params):
        query = '&'.join(f'{k}={v}' for k, v in params.items())
        response = self.client.get('/api/notifications' + ('?' + query if query else ''),
                                   headers=self.headers(token))
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json().get('notifications', [])

    # ── Super-admin announcements ─────────────────────────────────────────

    def test_admin_broadcast_reaches_every_company(self):
        admin = self._admin_token()
        response = self.client.post(
            '/api/admin/notifications', headers=self.headers(admin),
            json={'tenantId': 'all', 'title': 'صيانة مجدولة', 'body': 'المنصة تحت الصيانة'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json().get('sent'), 2)
        for token in (self.token, self.other_token):
            titles = [n['title'] for n in self._feed(token)]
            self.assertIn('صيانة مجدولة', titles)
            row = next(n for n in self._feed(token) if n['title'] == 'صيانة مجدولة')
            self.assertEqual(row['category'], 'platform')
            self.assertIsNone(row['user_id'])

    def test_admin_announcement_targets_one_company(self):
        admin = self._admin_token()
        response = self.client.post(
            '/api/admin/notifications', headers=self.headers(admin),
            json={'tenantId': self.tenant_id, 'title': 'رسالة خاصة'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json().get('sent'), 1)
        self.assertIn('رسالة خاصة', [n['title'] for n in self._feed(self.token)])
        self.assertNotIn('رسالة خاصة', [n['title'] for n in self._feed(self.other_token)])

    def test_admin_announcement_validation_and_auth(self):
        admin = self._admin_token()
        missing_title = self.client.post(
            '/api/admin/notifications', headers=self.headers(admin),
            json={'tenantId': 'all'})
        self.assertEqual(missing_title.status_code, 400)
        bad_target = self.client.post(
            '/api/admin/notifications', headers=self.headers(admin),
            json={'tenantId': 'no-such-tenant', 'title': 'x'})
        self.assertEqual(bad_target.status_code, 404)
        # The platform tenant itself is not a broadcast target.
        platform_target = self.client.post(
            '/api/admin/notifications', headers=self.headers(admin),
            json={'tenantId': 'platform-adm', 'title': 'x'})
        self.assertEqual(platform_target.status_code, 404)
        denied = self.client.post(
            '/api/admin/notifications', headers=self.headers(self.token),
            json={'tenantId': 'all', 'title': 'x'})
        self.assertEqual(denied.status_code, 403)

    # ── Low-balance warning ───────────────────────────────────────────────

    def test_low_balance_warns_once_per_cycle(self):
        self._approve_recharge(self.tenant_id, 100.0, 'TRX-LOW-1')
        # Above the 20% line: no warning yet.
        db.record_ledger_adjustment(self.tenant_id, -70.0, 'correction', note='use')
        self.assertEqual(
            [n for n in self._feed(self.token) if n['entity_type'] == 'low_balance'], [])
        # Under 20% of the 100 SAR cycle (balance 10 < 20): one warning.
        db.record_ledger_adjustment(self.tenant_id, -20.0, 'correction', note='use')
        warnings = [n for n in self._feed(self.token) if n['entity_type'] == 'low_balance']
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]['category'], 'billing')
        self.assertEqual(warnings[0]['user_id'], 'tenant-admin:' + self.tenant_id)
        # Further drains inside the same cycle do not re-warn.
        db.record_ledger_adjustment(self.tenant_id, -5.0, 'correction', note='use')
        warnings = [n for n in self._feed(self.token) if n['entity_type'] == 'low_balance']
        self.assertEqual(len(warnings), 1)
        # An email delivery is queued for the company address.
        conn = db.get_db()
        mail = conn.execute(
            "SELECT * FROM email_outbox WHERE tenant_id = ? AND subject LIKE '%رصيد%'",
            (self.tenant_id,)).fetchall()
        self.assertEqual(len(mail), 1)
        self.assertEqual(dict(mail[0])['to_email'], 'ops@x.test')

    def test_low_balance_rearms_on_new_recharge(self):
        self._approve_recharge(self.tenant_id, 100.0, 'TRX-REARM-1')
        db.record_ledger_adjustment(self.tenant_id, -90.0, 'correction', note='use')
        self.assertEqual(
            len([n for n in self._feed(self.token) if n['entity_type'] == 'low_balance']), 1)
        # A new approved recharge starts a new cycle — the warning re-arms.
        self._approve_recharge(self.tenant_id, 500.0, 'TRX-REARM-2')
        db.record_ledger_adjustment(self.tenant_id, -450.0, 'correction', note='use')
        warnings = [n for n in self._feed(self.token) if n['entity_type'] == 'low_balance']
        self.assertEqual(len(warnings), 2)
        self.assertNotEqual(warnings[0]['entity_id'], warnings[1]['entity_id'])

    def test_low_balance_ignored_without_credit_base(self):
        # No approved recharge and zero lifetime credit: nothing to warn about.
        db.record_ledger_adjustment(self.tenant_id, -1.0, 'correction', note='use')
        self.assertEqual(
            [n for n in self._feed(self.token) if n['entity_type'] == 'low_balance'], [])

    # ── Ticket priority ownership ─────────────────────────────────────────

    def test_client_cannot_set_ticket_priority(self):
        response = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل', 'priority': 'urgent'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['ticket']['priority'], 'normal')
        # No client-side status/priority route exists at all.
        denied = self.client.post(
            '/api/support/tickets/x/status', headers=self.headers(self.token),
            json={'priority': 'urgent'})
        self.assertEqual(denied.status_code, 404)

    def test_admin_priority_update_returns_fresh_ticket_without_status_notice(self):
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل'})
        ticket_id = created.get_json()['ticket']['id']
        admin = self._admin_token()
        response = self.client.post(
            f'/api/admin/support/tickets/{ticket_id}/status',
            headers=self.headers(admin), json={'priority': 'urgent'})
        self.assertEqual(response.status_code, 200, response.get_json())
        ticket = response.get_json()['ticket']
        self.assertEqual(ticket['priority'], 'urgent')
        self.assertEqual(ticket['status'], 'open')
        # Priority-only moves do not emit a status notification.
        notices = [n for n in self._feed(self.token)
                   if n['entity_type'] == 'support_ticket' and 'حالة' in (n['title'] or '')]
        self.assertEqual(notices, [])
        # A bad priority value is refused.
        bad = self.client.post(
            f'/api/admin/support/tickets/{ticket_id}/status',
            headers=self.headers(admin), json={'priority': 'bogus'})
        self.assertEqual(bad.status_code, 400)

    def test_admin_same_status_update_is_a_noop(self):
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل'})
        ticket_id = created.get_json()['ticket']['id']
        admin = self._admin_token()
        first = self.client.post(
            f'/api/admin/support/tickets/{ticket_id}/status',
            headers=self.headers(admin), json={'status': 'in_progress'})
        self.assertEqual(first.status_code, 200)
        notices = [n for n in self._feed(self.token)
                   if n['entity_type'] == 'support_ticket' and 'حالة' in (n['title'] or '')]
        self.assertEqual(len(notices), 1)
        # Re-clicking the current status changes nothing and re-notifies nobody.
        again = self.client.post(
            f'/api/admin/support/tickets/{ticket_id}/status',
            headers=self.headers(admin), json={'status': 'in_progress'})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()['ticket']['status'], 'in_progress')
        notices = [n for n in self._feed(self.token)
                   if n['entity_type'] == 'support_ticket' and 'حالة' in (n['title'] or '')]
        self.assertEqual(len(notices), 1)

    def test_admin_resolve_closes_the_ticket(self):
        """«تم الحل» is terminal: the ticket lands in 'closed' directly."""
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل'})
        ticket_id = created.get_json()['ticket']['id']
        admin = self._admin_token()
        response = self.client.post(
            f'/api/admin/support/tickets/{ticket_id}/status',
            headers=self.headers(admin), json={'status': 'closed'})
        self.assertEqual(response.status_code, 200, response.get_json())
        ticket = response.get_json()['ticket']
        self.assertEqual(ticket['status'], 'closed')
        self.assertTrue(ticket.get('closed_at'))
        notices = [n for n in self._feed(self.token)
                   if n['entity_type'] == 'support_ticket' and 'حالة' in (n['title'] or '')]
        self.assertEqual(len(notices), 1)
        self.assertIn('مغلقة', notices[0]['body'])

    # ── Company-admin visibility: every staff notice mirrors to the admin ──

    def test_employee_notifications_mirror_to_the_company_admin(self):
        emp_id = db.create_user(
            self.tenant_id, 'محرر', 'mirror-ed@x.test', 'hash', role='employee')
        db.create_notification(
            self.tenant_id, 'اعتُمد قسمك', category='section_approval',
            user_id=emp_id)
        employee_feed = db.list_notifications(self.tenant_id, user_id=emp_id)
        self.assertEqual(
            [n['title'] for n in employee_feed if n['title'] == 'اعتُمد قسمك'],
            ['اعتُمد قسمك'])
        admin_feed = [n['title'] for n in self._feed(self.token)]
        self.assertIn('اعتُمد قسمك', admin_feed)

    def test_admin_feed_rows_do_not_mirror_twice(self):
        db.create_notification(self.tenant_id, 'بثّ عام')
        db.create_notification(
            self.tenant_id, 'للأدمن', user_id='tenant-admin:' + self.tenant_id)
        db.create_notification(
            self.tenant_id, 'محفظة', category='billing', user_id='someone',
            mirror_admin=False)
        titles = [n['title'] for n in self._feed(self.token)]
        self.assertEqual(titles.count('بثّ عام'), 1)
        self.assertEqual(titles.count('للأدمن'), 1)
        self.assertNotIn('محفظة', titles)

    def test_employees_cannot_read_the_admin_only_rows(self):
        emp_id = db.create_user(
            self.tenant_id, 'موظف', 'emp-feed@x.test', 'hash', role='employee')
        emp_token = auth.create_token(
            self.tenant_id, 'emp-feed@x.test', user_id=emp_id,
            user_name='موظف', user_role='employee')
        db.create_notification(
            self.tenant_id, 'أمر إداري', user_id='tenant-admin:' + self.tenant_id)
        db.create_notification(self.tenant_id, 'عام للجميع')
        titles = [n['title'] for n in self._feed(emp_token)]
        self.assertIn('عام للجميع', titles)
        self.assertNotIn('أمر إداري', titles)

    # ── Admin self-echo: own acts never ping the admin feed ─────────────

    def test_admin_initiated_notice_does_not_echo_back(self):
        emp_id = db.create_user(
            self.tenant_id, 'محرر', 'echo-ed@x.test', 'hash', role='employee')
        response = self.client.post(
            '/api/notifications', headers=self.headers(self.token),
            json={'title': 'ملاحظة للمحرر', 'userId': emp_id})
        self.assertEqual(response.status_code, 200, response.get_json())
        employee_feed = db.list_notifications(self.tenant_id, user_id=emp_id)
        self.assertIn('ملاحظة للمحرر', [n['title'] for n in employee_feed])
        # The admin authored it — his own feed must not carry a copy.
        self.assertNotIn('ملاحظة للمحرر', [n['title'] for n in self._feed(self.token)])

    def test_employee_initiated_notice_mirrors_to_admin(self):
        sender_id = db.create_user(
            self.tenant_id, 'معتمد', 'echo-ap@x.test', 'hash', role='employee')
        db.set_user_permission(sender_id, 'manage_users', True)
        target_id = db.create_user(
            self.tenant_id, 'محرر', 'echo-tg@x.test', 'hash', role='employee')
        emp_token = auth.create_token(
            self.tenant_id, 'echo-ap@x.test', user_id=sender_id,
            user_name='معتمد', user_role='employee')
        response = self.client.post(
            '/api/notifications', headers=self.headers(emp_token),
            json={'title': 'راجع القسم', 'userId': target_id})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn('راجع القسم', [n['title'] for n in self._feed(self.token)])

    def test_decision_on_admin_own_submission_notifies_nobody_admin_side(self):
        """A decision on a version the company admin sent stays in the audit
        trail only — the tenant-admin address never receives «اعتُمد قسمك»."""
        draft_id = db.save_project_draft(
            self.tenant_id, self.user_id,
            {'project_name': 'برج المشرق'}, {'basic': 'draft'}, 'draft',
            draft_id='draft-admin-sec')
        version = db.create_section_version(
            self.tenant_id, draft_id, 'basic', {'project_name': 'برج المشرق'},
            'tenant-admin:' + self.tenant_id, 'مدير الشركة')
        self.assertNotIn('error', version)
        approver_id = db.create_user(
            self.tenant_id, 'معتمد', 'dec-ap@x.test', 'hash', role='employee')
        db.set_user_permission(approver_id, 'approvals', True)
        approver_token = auth.create_token(
            self.tenant_id, 'dec-ap@x.test', user_id=approver_id,
            user_name='معتمد', user_role='employee')
        response = self.client.post(
            '/api/project-draft/section-version/decision',
            headers=self.headers(approver_token),
            json={'versionId': version['id'], 'decision': 'approved'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn('اعتُمد قسمك', [n['title'] for n in self._feed(self.token)])

    # ── Wallet surfaces stay with the company admin ─────────────────────

    def _employee_token(self, email):
        emp_id = db.create_user(self.tenant_id, 'موظف', email, 'hash', role='employee')
        return auth.create_token(
            self.tenant_id, email, user_id=emp_id, user_name='موظف', user_role='employee')

    def test_employee_wallet_reads_are_forbidden(self):
        emp_token = self._employee_token('wallet-ed@x.test')
        for url in ('/api/recharge-requests', '/api/billing/packages',
                    '/api/points/overview', '/api/points/reservations'):
            response = self.client.get(url, headers=self.headers(emp_token))
            self.assertEqual(response.status_code, 403, url)

    def test_client_overview_hides_wallet_figures_from_employees(self):
        emp_token = self._employee_token('ov-ed@x.test')
        body = self.client.get(
            '/api/client/overview', headers=self.headers(emp_token)).get_json()
        self.assertTrue(body['success'], body)
        self.assertTrue(body.get('wallet_restricted'))
        self.assertIn('funds_available', body)
        for key in ('balance_sar', 'balance_usd', 'reserved_sar',
                    'package', 'lifetime', 'fx'):
            self.assertNotIn(key, body)
        self.assertNotIn('consumption_sar', body['totals'])
        full = self.client.get(
            '/api/client/overview', headers=self.headers(self.token)).get_json()
        self.assertIn('balance_sar', full)
        self.assertIn('package', full)

    def test_employee_feed_lists_no_wallet_support_or_task_categories(self):
        emp_token = self._employee_token('cats-ed@x.test')
        body = self.client.get(
            '/api/notifications', headers=self.headers(emp_token)).get_json()
        for hidden in ('billing', 'recharge', 'support', 'task'):
            self.assertNotIn(hidden, body['categories'])
        full = self.client.get(
            '/api/notifications', headers=self.headers(self.token)).get_json()
        for cat in ('billing', 'recharge', 'support'):
            self.assertIn(cat, full['categories'])

    # ── Overdue approvals escalate as plain notices, not «tasks» ─────────

    def test_overdue_approval_escalates_under_its_own_category(self):
        task = db.create_approval_task(
            self.tenant_id, 'section_approval', 'اعتماد قسم «الأساسيات»',
            due_hours=-25)
        escalated = db.escalate_overdue_approval_tasks(self.tenant_id)
        self.assertIn(task['id'], escalated)
        note = next(
            n for n in self._feed(self.token) if n['entity_type'] == 'approval_task')
        self.assertEqual(note['category'], 'section_approval')
        self.assertNotIn('مهمة', note['title'])
        self.assertIn('متأخر', note['title'])

    # ── Responsibility presets ────────────────────────────────────────────

    def test_responsibility_presets_on_add_user(self):
        created = self.client.post('/api/users', headers=self.headers(self.token), json={
            'name': 'معتمد', 'email': 'preset-ap@x.test', 'password': 'Secret12345',
            'responsibility': 'approver'})
        self.assertIn(created.status_code, (200, 201), created.get_json())
        approver = db.get_user_by_email('preset-ap@x.test')
        perms = db.get_user_permissions(approver['id'])
        self.assertTrue(perms['approvals'])
        self.assertTrue(perms['approve_generation'])
        self.assertTrue(perms['approve_final_file'])
        for denied in ('create_presentation', 'billing', 'support_tickets',
                       'company_settings', 'manage_users', 'ai_rules'):
            self.assertFalse(perms[denied], denied)

        created = self.client.post('/api/users', headers=self.headers(self.token), json={
            'name': 'محرر', 'email': 'preset-ed@x.test', 'password': 'Secret12345',
            'responsibility': 'editor'})
        self.assertIn(created.status_code, (200, 201), created.get_json())
        editor = db.get_user_by_email('preset-ed@x.test')
        perms = db.get_user_permissions(editor['id'])
        self.assertTrue(perms['create_presentation'])
        self.assertTrue(perms['export_files'])
        for denied in ('approvals', 'approve_generation', 'approve_final_file',
                       'billing', 'support_tickets', 'company_settings',
                       'manage_users', 'ai_rules'):
            self.assertFalse(perms[denied], denied)

    def test_support_tickets_are_company_admin_only(self):
        emp_id = db.create_user(
            self.tenant_id, 'موظف', 'emp-ticket@x.test', 'hash', role='employee')
        emp_token = auth.create_token(
            self.tenant_id, 'emp-ticket@x.test', user_id=emp_id,
            user_name='موظف', user_role='employee')
        for method, url in (
                ('POST', '/api/support/tickets'),
                ('GET', '/api/support/tickets')):
            response = (self.client.post if method == 'POST' else self.client.get)(
                url, headers=self.headers(emp_token),
                json={'subject': 'عطل', 'body': 'مساعدة'} if method == 'POST' else None)
            self.assertEqual(response.status_code, 403, (method, url, response.get_json()))
        # A stale grant row can never reopen the desk for an employee.
        db.set_user_permission(emp_id, 'support_tickets', True)
        self.assertFalse(db.get_user_permissions(emp_id)['support_tickets'])
        denied = self.client.post(
            '/api/support/tickets', headers=self.headers(emp_token),
            json={'subject': 'عطل', 'body': 'مساعدة'})
        self.assertEqual(denied.status_code, 403)

    # ── Subscription watch: the desk hears before a package lapses ────────

    def test_subscription_watch_warns_the_platform_desk(self):
        admin = self._admin_token()
        package = db.create_billing_package('باقة سنوية', credit_sar=1000, price_sar=1000)
        ends = (db._utcnow() + timedelta(days=5)).isoformat()
        db.create_subscription(
            self.tenant_id, package_id=package['id'], ends_at=ends)
        result = self.application_module._subscription_watch_sweep()
        self.assertEqual(result['warned'], 1)
        feed = self._feed(admin)
        note = next((n for n in feed if n['entity_type'] == 'subscription'), None)
        self.assertIsNotNone(note)
        self.assertEqual(note['title'], 'باقة شركة تقترب من الانتهاء')
        self.assertTrue(note['entity_id'].startswith(self.tenant_id))
        # The same window never notifies twice.
        self.assertEqual(self.application_module._subscription_watch_sweep()['warned'], 0)

    def test_subscription_watch_reports_an_elapsed_package(self):
        admin = self._admin_token()
        package = db.create_billing_package('باقة', credit_sar=10, price_sar=10)
        db.create_subscription(
            self.tenant_id, package_id=package['id'],
            ends_at=(db._utcnow() - timedelta(days=1)).isoformat())
        result = self.application_module._subscription_watch_sweep()
        self.assertEqual(result['expired'], 1)
        titles = [n['title'] for n in self._feed(admin)]
        self.assertIn('انتهت صلاحية باقة شركة', titles)

    # ── Ticket attachments ────────────────────────────────────────────────

    def _upload_attachment(self, token, name='notes.txt', content=b'attachment-body'):
        return self.client.post(
            '/api/project-files', headers={'Authorization': 'Bearer ' + token},
            data={'file': (io.BytesIO(content), name), 'fileType': 'ticket_attachment'},
            content_type='multipart/form-data')

    def test_ticket_attachment_upload_download_and_isolation(self):
        upload = self._upload_attachment(self.token)
        self.assertEqual(upload.status_code, 201, upload.get_json())
        file_id = upload.get_json()['file']['id']
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'body': 'تفاصيل', 'attachmentFileId': file_id})
        self.assertEqual(created.status_code, 200, created.get_json())
        ticket_id = created.get_json()['ticket']['id']
        # The list row reports an attachment; the detail carries its metadata.
        listing = self.client.get('/api/support/tickets', headers=self.headers(self.token))
        row = next(t for t in listing.get_json()['tickets'] if t['id'] == ticket_id)
        self.assertEqual(row['attachment_count'], 1)
        detail = self.client.get(
            f'/api/support/tickets/{ticket_id}', headers=self.headers(self.token))
        attachments = detail.get_json()['ticket']['attachments']
        self.assertEqual(attachments[0]['file_id'], file_id)
        self.assertEqual(attachments[0]['original_name'], 'notes.txt')
        # Owner downloads through the tenant-scoped route.
        download = self.client.get(
            f'/api/support/tickets/{ticket_id}/attachments/{file_id}',
            headers=self.headers(self.token))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b'attachment-body')
        self.assertEqual(download.headers.get('X-Content-Type-Options'), 'nosniff')
        # The platform desk downloads through the admin route.
        admin = self._admin_token()
        admin_download = self.client.get(
            f'/api/admin/support/tickets/{ticket_id}/attachments/{file_id}',
            headers=self.headers(admin))
        self.assertEqual(admin_download.status_code, 200)
        self.assertEqual(admin_download.data, b'attachment-body')
        # Another company cannot reach the file through either route.
        foreign = self.client.get(
            f'/api/support/tickets/{ticket_id}/attachments/{file_id}',
            headers=self.headers(self.other_token))
        self.assertEqual(foreign.status_code, 404)
        # A file not attached to this ticket is refused even for the owner.
        other_upload = self._upload_attachment(self.token, name='other.bin')
        other_file = other_upload.get_json()['file']['id']
        swap = self.client.get(
            f'/api/support/tickets/{ticket_id}/attachments/{other_file}',
            headers=self.headers(self.token))
        self.assertEqual(swap.status_code, 404)

    def test_ticket_attachment_file_id_must_belong_to_tenant(self):
        foreign_upload = self._upload_attachment(self.other_token, name='foreign.txt')
        self.assertEqual(foreign_upload.status_code, 201, foreign_upload.get_json())
        foreign_file = foreign_upload.get_json()['file']['id']
        created = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'مشكلة', 'attachmentFileId': foreign_file})
        self.assertEqual(created.status_code, 400)
        # Ticket creation works fine without any attachment at all.
        plain = self.client.post(
            '/api/support/tickets', headers=self.headers(self.token),
            json={'subject': 'بدون مرفق'})
        self.assertEqual(plain.status_code, 200, plain.get_json())

    def test_sag_admin_panel_grant_never_survives(self):
        """A stale sag_admin_panel grant row must not resurrect the platform
        flag for a company session — it made the ops page call admin routes.
        Only non-primary employee sessions keep user_id, so the grant must be
        pinned on one of those, not the primary admin row."""
        emp_id = db.create_user(
            self.tenant_id, 'موظف', 'emp@x.test', 'hash', role='employee')
        conn = db.get_db()
        conn.execute(
            "INSERT INTO user_permissions (id, user_id, permission_key, granted) "
            "VALUES ('stale-1', ?, 'sag_admin_panel', 1) "
            "ON CONFLICT(user_id, permission_key) DO UPDATE SET granted = 1",
            (emp_id,))
        conn.commit()
        emp_token = auth.create_token(
            self.tenant_id, 'emp@x.test', user_id=emp_id,
            user_name='موظف', user_role='employee')

        # The merge can never flip it on, and the setter refuses to write it.
        perms = db.get_user_permissions(emp_id)
        self.assertFalse(perms['sag_admin_panel'])
        self.assertFalse(db.set_user_permission(emp_id, 'sag_admin_panel', True))

        # /api/my-permissions feeds hasPermission() — it must stay clean.
        mine = self.client.get('/api/my-permissions', headers=self.headers(emp_token))
        self.assertEqual(mine.status_code, 200)
        self.assertFalse(mine.get_json()['permissions']['sag_admin_panel'])

        # init_db wipes the stale grant itself.
        db.init_db()
        row = db.get_db().execute(
            "SELECT granted FROM user_permissions WHERE user_id = ? AND permission_key = 'sag_admin_panel'",
            (emp_id,)).fetchone()
        self.assertIsNone(row)


if __name__ == '__main__':
    unittest.main()
