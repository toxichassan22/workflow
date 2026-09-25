# -*- coding: utf-8 -*-
"""Operations-section coverage: super-admin announcements, the low-balance
warning, and support-ticket priority/attachment rules."""
import io
import os
import sys
import tempfile
import threading
import unittest

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


if __name__ == '__main__':
    unittest.main()
