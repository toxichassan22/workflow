"""Identity, roles and security subsystems (t20-t23, d01, d07, t63-MFA).

Covers TOTP two-factor login (RFC 6238) with one-time recovery codes, the
purpose-scoped MFA challenge token, per-user project scopes, last-company-admin
protection, the d01 section self-approval policy, the d07 client-approved admin
access grant, the expanded separation-of-duties matrix and extended invites.
Runs against a temporary SQLite database and never calls Google or an AI API.
"""

import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask

import auth
import db


class IdentityDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'identity.db')
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
        conn.execute(
            "INSERT INTO tenants (id, company_name, subdomain, email, password_hash, plan, is_active, is_admin) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, 1)",
            ('admin-t', 'Platform', 'platform', 'admin@example.test', 'hash', 'enterprise'),
        )
        conn.commit()
        self.draft_id = db.save_project_draft(
            'tenant-1', 'user-1',
            {'project_name': 'برج المشرق', 'city': 'الرياض'},
            {'basic': 'draft'}, 'draft', draft_id='draft-1',
        )

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    # ── t21/t63: TOTP + recovery codes ───────────────────────────────────

    def test_totp_round_trip_and_rejects_bad_code(self):
        secret = auth.generate_totp_secret()
        code = auth.totp_code(secret)
        self.assertTrue(auth.verify_totp(secret, code))
        self.assertFalse(auth.verify_totp(secret, '000000'))
        self.assertFalse(auth.verify_totp(secret, 'not-a-code'))
        self.assertFalse(auth.verify_totp('', code))
        uri = auth.totp_otpauth_uri(secret, 'user@x.test')
        self.assertIn(secret, uri)
        self.assertIn('otpauth://totp/', uri)

    def test_mfa_challenge_token_cannot_act_as_session(self):
        token = auth.create_mfa_token('tenant-1', 'u@x.test', user_id='user-1',
                                      user_name='U', user_role='employee')
        payload = auth.verify_mfa_token(token)
        self.assertEqual(payload['sub'], 'tenant-1')
        self.assertEqual(payload['user_id'], 'user-1')
        # The purpose claim bars the challenge token from session use.
        self.assertIsNone(auth.decode_token(token))
        self.assertIsNone(auth.verify_mfa_token('garbage'))

    def test_mfa_state_lifecycle(self):
        uid = db.create_user('tenant-1', 'U1', 'u1@x.test', 'hash', role='employee')
        self.assertFalse(db.get_mfa_state('user', uid)['enabled'])
        secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('user', uid, secret)
        state = db.get_mfa_state('user', uid)
        self.assertFalse(state['enabled'])
        self.assertTrue(state['pending'])
        db.activate_mfa('user', uid)
        state = db.get_mfa_state('user', uid)
        self.assertTrue(state['enabled'])
        self.assertFalse(state['pending'])
        db.clear_mfa('user', uid)
        self.assertFalse(db.get_mfa_state('user', uid)['enabled'])

    def test_recovery_codes_are_hashed_and_one_time(self):
        uid = db.create_user('tenant-1', 'RC', 'rc@x.test', 'hash', role='employee')
        codes = auth.generate_recovery_codes(3)
        db.store_recovery_codes('tenant-1', uid, codes)
        self.assertEqual(db.count_unused_recovery_codes('tenant-1', uid), 3)
        self.assertTrue(db.consume_recovery_code('tenant-1', uid, codes[0]))
        # One-time: the same code cannot be spent twice.
        self.assertFalse(db.consume_recovery_code('tenant-1', uid, codes[0]))
        self.assertEqual(db.count_unused_recovery_codes('tenant-1', uid), 2)
        self.assertFalse(db.consume_recovery_code('tenant-1', uid, '99999999'))
        # Codes live hashed, never in clear.
        row = db.get_db().execute(
            'SELECT code_hash FROM mfa_recovery_codes WHERE user_id = ?', (uid,)
        ).fetchone()
        self.assertNotEqual(row['code_hash'], codes[1])

    # ── t20: project scope ───────────────────────────────────────────────

    def test_project_scope_limits_and_owner_bypass(self):
        uid = db.create_user('tenant-1', 'Scoped', 'scoped@x.test', 'hash', role='employee')
        other_draft = db.save_project_draft(
            'tenant-1', 'user-1', {'project_name': 'آخر'},
            {'basic': 'draft'}, 'draft', draft_id='draft-2')
        # No scope rows: unrestricted.
        self.assertTrue(db.user_may_access_draft(uid, {'id': 'draft-2'}))
        res = db.set_user_project_scope('tenant-1', uid, [self.draft_id])
        self.assertTrue(res['limited'])
        self.assertEqual(res['scope'], [self.draft_id])
        self.assertTrue(db.user_project_scope_limited(uid))
        self.assertTrue(db.user_may_access_draft(uid, {'id': self.draft_id}))
        self.assertFalse(db.user_may_access_draft(uid, {'id': 'draft-2'}))
        # The owner always reaches their own file.
        self.assertTrue(db.user_may_access_draft(uid, {'id': 'draft-2', 'user_id': uid}))
        # Empty list lifts the restriction.
        res = db.set_user_project_scope('tenant-1', uid, [])
        self.assertFalse(res['limited'])
        self.assertTrue(db.user_may_access_draft(uid, {'id': 'draft-2'}))
        # Unknown users and drafts from another tenant are refused.
        self.assertEqual(
            db.set_user_project_scope('tenant-2', uid, []).get('error'), 'user_not_found')

    # ── t21-03: last company admin protection ────────────────────────────

    def test_last_active_company_admin_guard(self):
        admin1 = db.create_user('tenant-1', 'A1', 'a1@x.test', 'hash', role='company_admin')
        admin2 = db.create_user('tenant-1', 'A2', 'a2@x.test', 'hash', role='company_admin')
        self.assertFalse(db.is_last_active_company_admin('tenant-1', admin1))
        db.update_user(admin2, is_active=0)
        self.assertTrue(db.is_last_active_company_admin('tenant-1', admin1))
        emp = db.create_user('tenant-1', 'E', 'e@x.test', 'hash', role='employee')
        self.assertFalse(db.is_last_active_company_admin('tenant-1', emp))
        # A disabled last admin is still "last" — enabling a second admin lifts it.
        db.update_user(admin1, is_active=0)
        self.assertTrue(db.is_last_active_company_admin('tenant-1', admin1))

    # ── d01: section self-approval policy ────────────────────────────────

    def test_d01_policy_block_warn_allow(self):
        version = db.create_section_version(
            'tenant-1', self.draft_id, 'basic', {'project_name': 'A'}, 'user-1', 'User One')
        # Default 'allow': recorded and flagged as a self-approval.
        decided = db.decide_section_version(
            'tenant-1', version['id'], 'approved', 'user-1', 'User One')
        self.assertEqual(decided.get('status'), 'approved')
        self.assertTrue(decided.get('is_self_approval'))

        db.set_tenant_policies('tenant-1', {'section_self_approval': 'block'})
        version2 = db.create_section_version(
            'tenant-1', self.draft_id, 'basic', {'project_name': 'B'},
            'user-1', 'User One', allow_supersede=True)
        blocked = db.decide_section_version(
            'tenant-1', version2['id'], 'approved', 'user-1', 'User One')
        self.assertEqual(blocked.get('error'), 'self_approval_blocked_by_policy')
        # Another approver still decides normally under 'block'.
        ok = db.decide_section_version(
            'tenant-1', version2['id'], 'approved', 'user-2', 'User Two')
        self.assertEqual(ok.get('status'), 'approved')

        db.set_tenant_policies('tenant-1', {'section_self_approval': 'warn'})
        version3 = db.create_section_version(
            'tenant-1', self.draft_id, 'basic', {'project_name': 'C'},
            'user-1', 'User One', allow_supersede=True)
        warned = db.decide_section_version(
            'tenant-1', version3['id'], 'approved', 'user-1', 'User One')
        self.assertEqual(warned.get('status'), 'approved')
        self.assertTrue(warned.get('is_self_approval'))

    # ── d07: admin access requests and grants ────────────────────────────

    def test_admin_access_request_lifecycle(self):
        self.assertEqual(
            db.create_admin_access_request('admin-t', 'tenant-1', 'bogus', None, 'سبب', 24, 'مشرف').get('error'),
            'invalid_scope')
        self.assertEqual(
            db.create_admin_access_request('admin-t', 'tenant-1', 'tenant', None, ' ', 24, 'مشرف').get('error'),
            'reason_required')
        req = db.create_admin_access_request(
            'admin-t', 'tenant-1', 'tenant', None, 'دعم عميل', 24, 'مشرف المنصة')
        self.assertEqual(req['status'], 'pending')
        # No grant yet.
        self.assertIsNone(db.active_admin_access_grant('tenant-1', scope='presentation', target_id='p1'))
        # Only the target tenant may decide.
        self.assertEqual(
            db.decide_admin_access_request(req['id'], 'tenant-2', 'approved', 'x', 'X').get('error'),
            'request_not_found')
        approved = db.decide_admin_access_request(
            req['id'], 'tenant-1', 'approved', 'user-1', 'مدير الشركة', hours=4)
        self.assertEqual(approved['status'], 'approved')
        self.assertTrue(approved['expires_at'])
        grant = db.active_admin_access_grant('tenant-1', scope='presentation', target_id='p1')
        self.assertEqual(grant['id'], req['id'])
        db.mark_admin_access_used(grant['id'])
        used = db.get_admin_access_request(req['id'])
        self.assertEqual(used['access_count'], 1)
        self.assertTrue(used['first_accessed_at'])
        revoked = db.revoke_admin_access_request(req['id'], 'tenant-1', 'مدير الشركة')
        self.assertEqual(revoked['status'], 'revoked')
        self.assertIsNone(db.active_admin_access_grant('tenant-1'))

    def test_admin_access_scoped_grant_and_expiry(self):
        req = db.create_admin_access_request(
            'admin-t', 'tenant-1', 'presentation', 'pres-1', 'مراجعة', 1, 'مشرف')
        db.decide_admin_access_request(req['id'], 'tenant-1', 'approved', 'u', 'U')
        # A presentation-scoped grant covers only its target.
        self.assertTrue(db.active_admin_access_grant('tenant-1', 'presentation', 'pres-1'))
        self.assertIsNone(db.active_admin_access_grant('tenant-1', 'presentation', 'pres-2'))
        self.assertIsNone(db.active_admin_access_grant('tenant-1', 'draft', 'draft-1'))
        # Expiry: force the grant into the past and re-check.
        conn = db.get_db()
        conn.execute("UPDATE admin_access_requests SET expires_at = '2000-01-01' WHERE id = ?",
                     (req['id'],))
        conn.commit()
        self.assertIsNone(db.active_admin_access_grant('tenant-1', 'presentation', 'pres-1'))
        self.assertEqual(db.get_admin_access_request(req['id'])['status'], 'expired')
        # Denied requests never grant.
        req2 = db.create_admin_access_request(
            'admin-t', 'tenant-1', 'tenant', None, 'سبب', 24, 'مشرف')
        denied = db.decide_admin_access_request(req2['id'], 'tenant-1', 'denied', 'u', 'U', note='لا')
        self.assertEqual(denied['status'], 'denied')
        self.assertIsNone(db.active_admin_access_grant('tenant-1'))

    # ── t23: expanded SoD matrix ─────────────────────────────────────────

    def test_sod_matrix_flags_cross_gate_and_post_approval_edit(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, draft_id, title, status) "
            "VALUES ('pres-1', 'tenant-1', ?, 'عرض', 'approved')", (self.draft_id,))
        conn.execute(
            '''INSERT INTO generation_approvals
               (id, tenant_id, draft_id, presentation_id, requested_by, requested_by_name,
                decided_by, decided_by_name, decided_at, status)
               VALUES ('ga-1', 'tenant-1', ?, 'pres-1', 'user-2', 'طالب',
                       'user-9', 'المعتمد المشترك', '2026-01-01T00:00:00', 'approved')''',
            (self.draft_id,))
        conn.execute(
            '''INSERT INTO final_file_approvals
               (id, tenant_id, presentation_id, requested_by, requested_by_name,
                decided_by, decided_by_name, decided_at, status)
               VALUES ('fa-1', 'tenant-1', 'pres-1', 'user-2', 'طالب',
                       'user-9', 'المعتمد المشترك', '2026-01-02T00:00:00', 'approved')''')
        conn.execute(
            '''INSERT INTO change_log (id, tenant_id, target_type, target_id, user_id, user_name,
                action, created_at)
               VALUES ('cl-1', 'tenant-1', 'presentation', 'pres-1', 'user-9',
                       'المعتمد المشترك', 'edit', '2026-01-04T00:00:00')''')
        conn.execute(
            '''INSERT INTO change_log (id, tenant_id, target_type, target_id, user_id, user_name,
                action, created_at)
               VALUES ('cl-2', 'tenant-1', 'presentation', 'pres-1', 'user-7',
                       'محرر بلا صلاحية', 'edit', '2026-01-03T00:00:00')''')
        conn.execute(
            "INSERT INTO users (id, tenant_id, name, email, password_hash, role, is_active) "
            "VALUES ('user-7', 'tenant-1', 'محرر', 'u7@x.test', 'h', 'employee', 1)")
        conn.execute(
            "INSERT INTO users (id, tenant_id, name, email, password_hash, role, is_active) "
            "VALUES ('user-9', 'tenant-1', 'معتمد', 'u9@x.test', 'h', 'employee', 1)")
        conn.commit()
        # user-9 may legitimately edit after approval, but must not also be the
        # approver of the file they last touched.
        db.set_user_permission('user-9', 'post_approval_edit', True)
        conn.execute(
            "INSERT INTO tenant_ledger (id, tenant_id, kind, amount_usd, note, actor, created_at) "
            "VALUES ('led-1', 'tenant-1', 'credit', 10, 'شحن يدوي', 'user-7', '2026-01-04T00:00:00')")
        conn.commit()

        matrix = db.separation_of_duties_matrix('tenant-1')
        self.assertEqual(matrix['cross_gate_count'], 1)
        self.assertEqual(matrix['last_editor_conflicts_count'], 1)
        self.assertEqual(matrix['post_approval_edits_count'], 1)
        self.assertEqual(matrix['client_side_topups_count'], 1)
        self.assertEqual(matrix['policies']['section_self_approval'], 'allow')

    # ── t21: extended invites ────────────────────────────────────────────

    def test_invite_carries_role_scope_and_email_status(self):
        invite = db.create_invite(
            'tenant-1', 'new@x.test', role='section_editor', name='موظف جديد',
            phone='0500', sections=['basic'], projects=[self.draft_id])
        stored = db.get_invite('tenant-1', invite['id'])
        self.assertEqual(stored['role'], 'section_editor')
        self.assertEqual(stored['name'], 'موظف جديد')
        db.mark_invite_email(invite['id'], 'failed', 'SMTP down')
        stored = db.get_invite('tenant-1', invite['id'])
        self.assertEqual(stored['email_status'], 'failed')
        self.assertEqual(stored['email_attempts'], 1)
        report = db.tenant_users_report('tenant-1')
        invite_row = next(i for i in report['invites'] if i['id'] == invite['id'])
        self.assertEqual(invite_row['email_status'], 'failed')
        self.assertFalse(invite_row['is_used'])

    # ── ISS-005: rate-limit buckets ──────────────────────────────────────

    def test_rate_limit_bucket_lifecycle(self):
        key = 'test:unit-bucket'
        # First N attempts inside the window pass freely.
        for _ in range(3):
            self.assertEqual(db.rate_limit_hit(key, 3, 60, 120), 0.0)
        # The attempt that crosses the limit locks the bucket.
        self.assertGreater(db.rate_limit_hit(key, 3, 60, 120), 0.0)
        self.assertGreater(db.rate_limit_status(key), 0.0)
        # Hitting a locked bucket reports the lock without extending it.
        locked = db.rate_limit_status(key)
        self.assertGreater(db.rate_limit_hit(key, 3, 60, 120), 0.0)
        self.assertAlmostEqual(db.rate_limit_status(key), locked, delta=2)
        # A successful clear restarts from zero.
        db.rate_limit_reset(key)
        self.assertEqual(db.rate_limit_status(key), 0.0)
        self.assertEqual(db.rate_limit_hit(key, 3, 60, 120), 0.0)

    def test_rate_limit_window_expiry_and_cleanup(self):
        key = 'test:expiring-bucket'
        now = db._utcnow()
        self.assertEqual(db.rate_limit_hit(key, 1, 60, 60, now=now), 0.0)
        self.assertGreater(db.rate_limit_hit(key, 1, 60, 60, now=now), 0.0)
        # Once the lock and the window both pass, the bucket is forgotten.
        later = now + timedelta(seconds=180)
        self.assertEqual(db.rate_limit_hit(key, 1, 60, 60, now=later), 0.0)
        db.rate_limit_cleanup(now=now)          # active bucket survives
        row = db.get_db().execute(
            'SELECT bucket_key FROM rate_limit_buckets WHERE bucket_key = ?', (key,)
        ).fetchone()
        self.assertIsNotNone(row)
        db.rate_limit_cleanup(now=now + timedelta(seconds=400))
        row = db.get_db().execute(
            'SELECT bucket_key FROM rate_limit_buckets WHERE bucket_key = ?', (key,)
        ).fetchone()
        self.assertIsNone(row)


class IdentityApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'identity-api.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        self.context = self.app.app_context()
        self.context.push()
        self.tenant_id = db.create_tenant('شركة', 'co@x.test', 'hash', 'co')
        self.admin_tenant_id = db.create_tenant('المنصة', 'sag@x.test', 'hash', 'sag')
        conn = db.get_db()
        conn.execute('UPDATE tenants SET is_admin = 1 WHERE id = ?', (self.admin_tenant_id,))
        conn.commit()
        self.admin_token = auth.create_token(
            self.admin_tenant_id, 'sag@x.test', is_admin=True,
            user_name='مدير النظام', user_role='company_admin')
        self.admin_user_id = db.create_user(
            self.tenant_id, 'مدير الشركة', 'boss@x.test',
            application_module.hash_password('secret123'), role='company_admin')
        self.admin_user_token = auth.create_token(
            self.tenant_id, 'boss@x.test', user_id=self.admin_user_id,
            user_name='مدير الشركة', user_role='company_admin')
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, token):
        return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    def test_platform_admin_is_only_the_tenant_account(self):
        user_id = db.create_user(
            self.admin_tenant_id, 'موظف المنصة', 'platform-employee@x.test',
            'hash', role='employee')
        token = auth.create_token(
            self.admin_tenant_id, 'platform-employee@x.test', is_admin=True,
            user_id=user_id, user_name='موظف المنصة', user_role='employee')
        headers = self.headers(token)

        me = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(me.status_code, 200, me.get_json())
        self.assertFalse(me.get_json()['tenant']['isAdmin'])
        denied_by_role = self.client.get('/api/admin/tenants', headers=headers)
        self.assertEqual(denied_by_role.status_code, 403)
        denied_panel = self.client.get('/api/admin/sag-fonts', headers=headers)
        self.assertEqual(denied_panel.status_code, 403)

        db.update_user(user_id, role='company_admin')
        still_denied = self.client.get('/api/admin/tenants', headers=headers)
        self.assertEqual(still_denied.status_code, 403)
        panel_still_denied = self.client.get('/api/admin/sag-fonts', headers=headers)
        self.assertEqual(panel_still_denied.status_code, 403)

        db.update_user(user_id, is_active=0)
        denied_when_disabled = self.client.get('/api/admin/tenants', headers=headers)
        self.assertEqual(denied_when_disabled.status_code, 403)

        db.update_user(user_id, is_active=1)
        db.delete_user(user_id)
        denied_when_deleted = self.client.get('/api/admin/tenants', headers=headers)
        self.assertEqual(denied_when_deleted.status_code, 403)

        direct_headers = self.headers(self.admin_token)
        direct_admin = self.client.get('/api/admin/tenants', headers=direct_headers)
        self.assertEqual(direct_admin.status_code, 200, direct_admin.get_json())
        direct_panel = self.client.get('/api/admin/sag-fonts', headers=direct_headers)
        self.assertEqual(direct_panel.status_code, 200, direct_panel.get_json())
        direct_me = self.client.get('/api/auth/me', headers=direct_headers)
        self.assertTrue(direct_me.get_json()['tenant']['isAdmin'])

    # ── Session revocation (logout + password change) ────────────────────

    def test_logout_revokes_only_the_presented_token(self):
        uid = self._employee('sess@x.test')
        first = auth.create_token(
            self.tenant_id, 'sess@x.test', user_id=uid,
            user_name='موظف', user_role='employee')
        second = auth.create_token(
            self.tenant_id, 'sess@x.test', user_id=uid,
            user_name='موظف', user_role='employee')
        self.assertNotEqual(first, second)

        ok = self.client.get('/api/auth/me', headers=self.headers(first))
        self.assertEqual(ok.status_code, 200)

        out = self.client.post('/api/auth/logout', headers=self.headers(first))
        self.assertEqual(out.status_code, 200, out.get_json())

        dead = self.client.get('/api/auth/me', headers=self.headers(first))
        self.assertEqual(dead.status_code, 401)
        # The session cannot be refreshed once revoked.
        dead_refresh = self.client.post('/api/auth/refresh', headers=self.headers(first))
        self.assertEqual(dead_refresh.status_code, 401)
        # A second session of the same account survives the first one's logout.
        alive = self.client.get('/api/auth/me', headers=self.headers(second))
        self.assertEqual(alive.status_code, 200)

    def test_password_change_kills_user_sessions_and_refresh(self):
        uid = self._employee('pw@x.test')
        token = auth.create_token(
            self.tenant_id, 'pw@x.test', user_id=uid,
            user_name='موظف', user_role='employee')
        self.assertEqual(
            self.client.get('/api/auth/me', headers=self.headers(token)).status_code, 200)

        db.update_user(uid, password_hash=auth.hash_password('NewPass12345'))

        self.assertEqual(
            self.client.get('/api/auth/me', headers=self.headers(token)).status_code, 401)
        self.assertEqual(
            self.client.post('/api/auth/refresh', headers=self.headers(token)).status_code, 401)
        # A session minted after the change works.
        fresh = auth.create_token(
            self.tenant_id, 'pw@x.test', user_id=uid,
            user_name='موظف', user_role='employee')
        self.assertEqual(
            self.client.get('/api/auth/me', headers=self.headers(fresh)).status_code, 200)

    def test_tenant_password_change_kills_tenant_direct_sessions(self):
        token = auth.create_token(
            self.tenant_id, 'co@x.test', user_name='شركة', user_role='company_admin')
        self.assertEqual(
            self.client.get('/api/auth/me', headers=self.headers(token)).status_code, 200)

        db.update_tenant(self.tenant_id, password_hash=auth.hash_password('Changed12345'))

        self.assertEqual(
            self.client.get('/api/auth/me', headers=self.headers(token)).status_code, 401)

    def test_non_password_user_update_keeps_sessions_alive(self):
        uid = self._employee('keep@x.test')
        token = auth.create_token(
            self.tenant_id, 'keep@x.test', user_id=uid,
            user_name='موظف', user_role='employee')
        db.update_user(uid, name='موظف معدل')
        self.assertEqual(
            self.client.get('/api/auth/me', headers=self.headers(token)).status_code, 200)

    def _employee(self, email='emp@x.test', role='employee'):
        uid = db.create_user(
            self.tenant_id, 'موظف', email, self.application_module.hash_password('secret123'),
            role=role)
        return uid

    # ── MFA login flow over HTTP ─────────────────────────────────────────

    def test_login_challenges_mfa_then_issues_session(self):
        uid = self._employee()
        secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('user', uid, secret)
        db.activate_mfa('user', uid)
        res = self.client.post('/api/auth/login', json={'email': 'emp@x.test', 'password': 'secret123'})
        body = res.get_json()
        self.assertTrue(body['mfaRequired'])
        self.assertNotIn('token', body)
        # The challenge token cannot authenticate API calls.
        denied = self.client.get('/api/auth/me', headers=self.headers(body['mfaToken']))
        self.assertEqual(denied.status_code, 401)
        bad = self.client.post('/api/auth/mfa/verify',
                               json={'mfaToken': body['mfaToken'], 'code': '000000'})
        self.assertEqual(bad.status_code, 401)
        good = self.client.post('/api/auth/mfa/verify',
                                json={'mfaToken': body['mfaToken'], 'code': auth.totp_code(secret)})
        self.assertEqual(good.status_code, 200, good.get_json())
        session = good.get_json()
        self.assertEqual(session['mfaMethod'], 'totp')
        me = self.client.get('/api/auth/me', headers=self.headers(session['token']))
        self.assertEqual(me.status_code, 200)

    def test_login_with_recovery_code_counts_down(self):
        uid = self._employee('emp2@x.test')
        secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('user', uid, secret)
        db.activate_mfa('user', uid)
        codes = auth.generate_recovery_codes(3)
        db.store_recovery_codes(self.tenant_id, uid, codes)
        res = self.client.post('/api/auth/login', json={'email': 'emp2@x.test', 'password': 'secret123'})
        verified = self.client.post('/api/auth/mfa/verify',
                                    json={'mfaToken': res.get_json()['mfaToken'], 'code': codes[0]})
        body = verified.get_json()
        self.assertEqual(verified.status_code, 200, body)
        self.assertEqual(body['mfaMethod'], 'recovery')
        self.assertEqual(body['recoveryCodesRemaining'], 2)
        # The spent code cannot open a second session.
        res2 = self.client.post('/api/auth/login', json={'email': 'emp2@x.test', 'password': 'secret123'})
        again = self.client.post('/api/auth/mfa/verify',
                                 json={'mfaToken': res2.get_json()['mfaToken'], 'code': codes[0]})
        self.assertEqual(again.status_code, 401)

    def test_company_admin_login_flags_missing_mfa_setup(self):
        res = self.client.post('/api/auth/login', json={'email': 'boss@x.test', 'password': 'secret123'})
        body = res.get_json()
        self.assertTrue(body.get('token'))
        self.assertTrue(body.get('mfaSetupRequired'))

    def test_mfa_setup_enable_and_status_over_http(self):
        setup = self.client.post('/api/auth/mfa/setup', headers=self.headers(self.admin_user_token), json={})
        self.assertEqual(setup.status_code, 200, setup.get_json())
        secret = setup.get_json()['secret']
        bad = self.client.post('/api/auth/mfa/enable', headers=self.headers(self.admin_user_token),
                               json={'code': '000000'})
        self.assertEqual(bad.status_code, 400)
        enabled = self.client.post('/api/auth/mfa/enable', headers=self.headers(self.admin_user_token),
                                   json={'code': auth.totp_code(secret)})
        body = enabled.get_json()
        self.assertTrue(body['enabled'])
        self.assertEqual(len(body['recoveryCodes']), 8)
        status = self.client.get('/api/auth/mfa/status', headers=self.headers(self.admin_user_token))
        self.assertTrue(status.get_json()['mfa']['enabled'])
        # Disabling is refused while the role mandates MFA.
        refused = self.client.post('/api/auth/mfa/disable', headers=self.headers(self.admin_user_token),
                                   json={'password': 'secret123', 'code': auth.totp_code(secret)})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.get_json()['error_code'], 'mfa_required_role')

    def test_mfa_resetup_requires_password_and_current_code(self):
        uid = self._employee()
        emp_token = auth.create_token(self.tenant_id, 'emp@x.test', user_id=uid,
                                      user_name='موظف', user_role='employee')
        headers = self.headers(emp_token)
        first = self.client.post('/api/auth/mfa/setup', headers=headers, json={})
        self.assertEqual(first.status_code, 200, first.get_json())
        old_secret = first.get_json()['secret']
        enabled = self.client.post('/api/auth/mfa/enable', headers=headers,
                                   json={'code': auth.totp_code(old_secret)})
        self.assertTrue(enabled.get_json()['enabled'])

        # A session alone cannot replace the factor: re-enrolment demands the
        # same proof as disabling — the password plus a current TOTP code.
        naked = self.client.post('/api/auth/mfa/setup', headers=headers, json={})
        self.assertEqual(naked.status_code, 400)
        self.assertEqual(naked.get_json()['error_code'], 'password_invalid')
        wrong_pw = self.client.post('/api/auth/mfa/setup', headers=headers,
                                    json={'password': 'nope',
                                          'code': auth.totp_code(old_secret)})
        self.assertEqual(wrong_pw.status_code, 400)
        self.assertEqual(wrong_pw.get_json()['error_code'], 'password_invalid')
        wrong_code = self.client.post('/api/auth/mfa/setup', headers=headers,
                                      json={'password': 'secret123', 'code': '000000'})
        self.assertEqual(wrong_code.status_code, 400)
        self.assertEqual(wrong_code.get_json()['error_code'], 'mfa_code_invalid')
        # Refused calls never planted a pending secret nor touched the live one.
        secrets_row = db.get_mfa_secrets('user', uid)
        self.assertEqual(secrets_row['mfa_secret'], old_secret)
        self.assertFalse(secrets_row['mfa_pending_secret'])

        # The right proof rotates the factor end to end.
        again = self.client.post('/api/auth/mfa/setup', headers=headers,
                                 json={'password': 'secret123',
                                       'code': auth.totp_code(old_secret)})
        self.assertEqual(again.status_code, 200, again.get_json())
        new_secret = again.get_json()['secret']
        self.assertNotEqual(new_secret, old_secret)
        rotated = self.client.post('/api/auth/mfa/enable', headers=headers,
                                   json={'code': auth.totp_code(new_secret)})
        self.assertTrue(rotated.get_json()['enabled'])
        self.assertEqual(db.get_mfa_secrets('user', uid)['mfa_secret'], new_secret)

    # ── Last-admin protection over HTTP ──────────────────────────────────

    def test_last_company_admin_cannot_be_deleted_or_demoted(self):
        res = self.client.delete(f'/api/users/{self.admin_user_id}',
                                 headers=self.headers(self.admin_user_token))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error_code'], 'last_company_admin')
        demote = self.client.put(f'/api/users/{self.admin_user_id}',
                                 headers=self.headers(self.admin_user_token),
                                 json={'role': 'employee'})
        self.assertEqual(demote.status_code, 400)
        self.assertEqual(demote.get_json()['error_code'], 'last_company_admin')
        disable = self.client.put(f'/api/users/{self.admin_user_id}',
                                  headers=self.headers(self.admin_user_token),
                                  json={'is_active': 0})
        self.assertEqual(disable.status_code, 400)
        # A second admin restores normal management.
        db.create_user(self.tenant_id, 'ثاني', 'second@x.test', 'hash', role='company_admin')
        demote2 = self.client.put(f'/api/users/{self.admin_user_id}',
                                  headers=self.headers(self.admin_user_token),
                                  json={'role': 'employee'})
        self.assertEqual(demote2.status_code, 200)

    # ── Project scope over HTTP ──────────────────────────────────────────

    def test_project_scope_endpoints(self):
        draft_id = db.save_project_draft(
            self.tenant_id, self.admin_user_id, {'project_name': 'ملف'},
            {'basic': 'draft'}, 'draft', draft_id='scoped-draft')
        uid = self._employee('scoped@x.test')
        put = self.client.put(f'/api/users/{uid}/project-scope',
                              headers=self.headers(self.admin_user_token),
                              json={'draftIds': [draft_id]})
        self.assertEqual(put.status_code, 200, put.get_json())
        self.assertTrue(put.get_json()['limited'])
        got = self.client.get(f'/api/users/{uid}/project-scope',
                              headers=self.headers(self.admin_user_token))
        body = got.get_json()
        self.assertEqual(body['scope'], [draft_id])
        self.assertTrue(any(d['id'] == draft_id for d in body['drafts']))
        # Employees without manage_users cannot touch the scope.
        emp_token = auth.create_token(self.tenant_id, 'scoped@x.test', user_id=uid,
                                      user_name='موظف', user_role='employee')
        denied = self.client.get(f'/api/users/{uid}/project-scope',
                                 headers=self.headers(emp_token))
        self.assertEqual(denied.status_code, 403)

    # ── d07 over HTTP ────────────────────────────────────────────────────

    def test_admin_content_requires_client_grant(self):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, title, status) "
            "VALUES ('pres-c', ?, 'عرض سري', 'approved')", (self.tenant_id,))
        conn.commit()
        denied = self.client.get(
            f'/api/admin/tenants/{self.tenant_id}/presentations/pres-c',
            headers=self.headers(self.admin_token))
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.get_json()['error_code'], 'access_grant_required')
        # Activity carries client field values, so it is gated the same way.
        denied_act = self.client.get(
            f'/api/admin/tenants/{self.tenant_id}/activity',
            headers=self.headers(self.admin_token))
        self.assertEqual(denied_act.status_code, 403)

        created = self.client.post(
            f'/api/admin/tenants/{self.tenant_id}/access-requests',
            headers=self.headers(self.admin_token),
            json={'scope': 'tenant', 'reason': 'تشخيص مشكلة', 'hours': 24})
        self.assertEqual(created.status_code, 201, created.get_json())
        request_id = created.get_json()['request']['id']

        # The client sees it and approves.
        listed = self.client.get('/api/access-requests', headers=self.headers(self.admin_user_token))
        self.assertTrue(any(r['id'] == request_id for r in listed.get_json()['requests']))
        decided = self.client.post(
            f'/api/access-requests/{request_id}/decision',
            headers=self.headers(self.admin_user_token),
            json={'decision': 'approved'})
        self.assertEqual(decided.status_code, 200, decided.get_json())

        allowed = self.client.get(
            f'/api/admin/tenants/{self.tenant_id}/presentations/pres-c',
            headers=self.headers(self.admin_token))
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

        # Revoking the grant closes access again.
        revoked = self.client.post(
            f'/api/access-requests/{request_id}/revoke',
            headers=self.headers(self.admin_user_token), json={})
        self.assertEqual(revoked.status_code, 200)
        denied2 = self.client.get(
            f'/api/admin/tenants/{self.tenant_id}/presentations/pres-c',
            headers=self.headers(self.admin_token))
        self.assertEqual(denied2.status_code, 403)

    def test_client_deny_leaves_content_closed(self):
        created = self.client.post(
            f'/api/admin/tenants/{self.tenant_id}/access-requests',
            headers=self.headers(self.admin_token),
            json={'scope': 'tenant', 'reason': 'دعم', 'hours': 24})
        request_id = created.get_json()['request']['id']
        decided = self.client.post(
            f'/api/access-requests/{request_id}/decision',
            headers=self.headers(self.admin_user_token),
            json={'decision': 'denied', 'note': 'غير مسموح'})
        self.assertEqual(decided.get_json()['request']['status'], 'denied')
        self.assertIsNone(db.active_admin_access_grant(self.tenant_id))
        # A plain employee cannot decide access requests.
        uid = self._employee('emp3@x.test')
        emp_token = auth.create_token(self.tenant_id, 'emp3@x.test', user_id=uid,
                                      user_name='موظف', user_role='employee')
        forbidden = self.client.post(
            f'/api/access-requests/{request_id}/decision',
            headers=self.headers(emp_token), json={'decision': 'approved'})
        self.assertEqual(forbidden.status_code, 403)

    # ── Policies over HTTP ───────────────────────────────────────────────

    def test_policies_get_and_update(self):
        got = self.client.get('/api/policies', headers=self.headers(self.admin_user_token))
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()['policies']['section_self_approval'], 'allow')
        uid = self._employee('emp4@x.test')
        emp_token = auth.create_token(self.tenant_id, 'emp4@x.test', user_id=uid,
                                      user_name='موظف', user_role='employee')
        forbidden = self.client.put('/api/policies', headers=self.headers(emp_token),
                                    json={'section_self_approval': 'block'})
        self.assertEqual(forbidden.status_code, 403)
        updated = self.client.put('/api/policies', headers=self.headers(self.admin_user_token),
                                  json={'section_self_approval': 'block'})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(
            db.get_tenant_policies(self.tenant_id)['section_self_approval'], 'block')

    # ── Invites over HTTP ────────────────────────────────────────────────

    def test_invite_assigns_role_and_scope_on_acceptance(self):
        draft_id = db.save_project_draft(
            self.tenant_id, self.admin_user_id, {'project_name': 'ملف'},
            {'basic': 'draft'}, 'draft', draft_id='invite-draft')
        created = self.client.post('/api/invites', headers=self.headers(self.admin_user_token),
                                   json={'email': 'invited@x.test', 'name': 'مدعو',
                                         'role': 'section_editor',
                                         'sections': ['basic'], 'projects': [draft_id]})
        self.assertEqual(created.status_code, 200, created.get_json())
        token = created.get_json()['token']
        info = self.client.get(f'/api/invite/{token}')
        self.assertEqual(info.status_code, 200)
        registered = self.client.post(f'/api/invite/{token}/register',
                                      json={'password': 'Secret1234'})
        body = registered.get_json()
        self.assertEqual(registered.status_code, 201, body)
        self.assertEqual(body['user']['role'], 'section_editor')
        new_user = db.get_user_by_email('invited@x.test')
        self.assertEqual(new_user['role'], 'section_editor')
        self.assertEqual(db.get_user_project_scope_ids(new_user['id']), {draft_id})
        self.assertTrue(db.get_user_field_sections(new_user['id'], self.tenant_id).get('basic'))
        # The link is spent.
        again = self.client.post(f'/api/invite/{token}/register', json={'password': 'Secret1234'})
        self.assertEqual(again.status_code, 404)
        # Resend refuses a used invite.
        resend = self.client.post(
            f"/api/invites/{created.get_json()['inviteId']}/resend",
            headers=self.headers(self.admin_user_token), json={})
        self.assertEqual(resend.status_code, 409)

    # ── One password policy across every endpoint ────────────────────────

    def test_password_policy_is_identical_on_every_path(self):
        """ISS-008: employee add, employee edit, invite acceptance and company
        registration used to each carry a different rule (6 chars, any
        non-empty value, 10 chars without the letters/digits requirement).
        All of them now share _password_validation_error."""
        # Add employee: short or digit-less passwords are refused before insert.
        for weak in ('abc123', 'onlyletters', '1234567890'):
            res = self.client.post('/api/users', headers=self.headers(self.admin_user_token),
                                   json={'name': 'موظف', 'email': 'w1@x.test',
                                         'password': weak})
            self.assertEqual(res.status_code, 400, (weak, res.get_json()))
        self.assertIsNone(db.get_user_by_email('w1@x.test'))
        ok = self.client.post('/api/users', headers=self.headers(self.admin_user_token),
                              json={'name': 'موظف', 'email': 'w1@x.test',
                                    'password': 'Employee123'})
        self.assertEqual(ok.status_code, 201, ok.get_json())
        uid = ok.get_json()['userId']

        # Editing the same employee's password applies the same policy, and a
        # manual set clears any pending first-login flag.
        weak_edit = self.client.put(f'/api/users/{uid}',
                                    headers=self.headers(self.admin_user_token),
                                    json={'password': 'short'})
        self.assertEqual(weak_edit.status_code, 400)
        strong_edit = self.client.put(f'/api/users/{uid}',
                                      headers=self.headers(self.admin_user_token),
                                      json={'password': 'NewEmployee123'})
        self.assertEqual(strong_edit.status_code, 200, strong_edit.get_json())
        self.assertEqual(db.get_user_by_id(uid)['require_password_change'], 0)

        # Invite acceptance no longer settles for 6 characters.
        created = self.client.post('/api/invites', headers=self.headers(self.admin_user_token),
                                   json={'email': 'weak-invite@x.test', 'name': 'مدعو'})
        token = created.get_json()['token']
        weak_invite = self.client.post(f'/api/invite/{token}/register',
                                       json={'password': 'abc123'})
        self.assertEqual(weak_invite.status_code, 400)
        self.assertIsNone(db.get_user_by_email('weak-invite@x.test'))
        strong_invite = self.client.post(f'/api/invite/{token}/register',
                                         json={'password': 'InvitePass12'})
        self.assertEqual(strong_invite.status_code, 201, strong_invite.get_json())

        # Registration demands letters and digits, not just ten characters.
        weak_register = self.client.post('/api/auth/register', json={
            'companyName': 'شركة ضعيفة', 'email': 'weakco@x.test',
            'password': 'onlylettersxx'})
        self.assertEqual(weak_register.status_code, 400)
        self.assertIsNone(db.get_tenant_by_email('weakco@x.test'))

    # ── Cross-tenant reads ───────────────────────────────────────────────

    def test_presentation_approval_status_is_tenant_and_scope_guarded(self):
        draft_id = db.save_project_draft(
            self.tenant_id, self.admin_user_id, {'project_name': 'ملف'},
            {'basic': 'draft'}, 'draft', draft_id='appr-draft')
        other_draft = db.save_project_draft(
            self.tenant_id, self.admin_user_id, {'project_name': 'آخر'},
            {'basic': 'draft'}, 'draft', draft_id='appr-draft-2')
        conn = db.get_db()
        conn.execute(
            "INSERT INTO presentations (id, tenant_id, draft_id, title, status) "
            "VALUES ('pres-appr', ?, ?, 'عرض', 'pending_approval')",
            (self.tenant_id, draft_id))
        conn.commit()
        approval_id = db.create_approval(
            'pres-appr', self.tenant_id, self.admin_user_id, 'مدير الشركة')

        own = self.client.get('/api/presentations/pres-appr/approval-status',
                              headers=self.headers(self.admin_user_token))
        self.assertEqual(own.status_code, 200, own.get_json())
        self.assertEqual(own.get_json()['approval']['id'], approval_id)

        # A session from another company must not read this approval record.
        other_tenant = db.create_tenant('شركة أخرى', 'other@x.test', 'hash', 'other')
        other_uid = db.create_user(other_tenant, 'مدير', 'other-admin@x.test',
                                   'hash', role='company_admin')
        other_token = auth.create_token(other_tenant, 'other-admin@x.test', user_id=other_uid,
                                        user_name='مدير', user_role='company_admin')
        denied = self.client.get('/api/presentations/pres-appr/approval-status',
                                 headers=self.headers(other_token))
        self.assertEqual(denied.status_code, 404)
        self.assertIsNone(denied.get_json().get('approval'))

        # A project-scoped member of the same tenant is refused for a file
        # outside their scope, exactly like the presentation GET route.
        scoped_uid = self._employee('scoped-appr@x.test')
        db.set_user_project_scope(self.tenant_id, scoped_uid, [other_draft])
        scoped_token = auth.create_token(self.tenant_id, 'scoped-appr@x.test', user_id=scoped_uid,
                                         user_name='موظف', user_role='employee')
        scoped = self.client.get('/api/presentations/pres-appr/approval-status',
                                 headers=self.headers(scoped_token))
        self.assertEqual(scoped.status_code, 404)

    def test_billing_permission_gates_recharge(self):
        uid = self._employee('nobill@x.test')
        emp_token = auth.create_token(self.tenant_id, 'nobill@x.test', user_id=uid,
                                      user_name='موظف', user_role='employee')
        denied = self.client.post('/api/recharge-requests', headers=self.headers(emp_token),
                                  json={'packageName': 'باقة', 'amountUsd': 10})
        self.assertEqual(denied.status_code, 403)
        db.set_user_permission(uid, 'billing', True)
        package = db.create_billing_package('باقة نمو', credit_usd=100, price_sar=375)
        allowed = self.client.post('/api/recharge-requests', headers=self.headers(emp_token),
                                   json={'packageId': package['id'],
                                         'referenceNumber': 'TRX-SEC-1'})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())

    # ── ISS-005: login and MFA attempt limits over HTTP ──────────────────

    def test_login_locks_account_after_repeated_failures(self):
        self._employee('locked@x.test')
        for _ in range(5):
            res = self.client.post('/api/auth/login',
                                   json={'email': 'locked@x.test', 'password': 'wrong'})
            self.assertEqual(res.status_code, 401)
        res = self.client.post('/api/auth/login',
                               json={'email': 'locked@x.test', 'password': 'wrong'})
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.get_json()['error_code'], 'rate_limited')
        self.assertIn('Retry-After', res.headers)
        # Even the right password is refused while the lock stands.
        res = self.client.post('/api/auth/login',
                               json={'email': 'locked@x.test', 'password': 'secret123'})
        self.assertEqual(res.status_code, 429)
        # Other accounts on the same IP are not affected.
        res = self.client.post('/api/auth/login',
                               json={'email': 'boss@x.test', 'password': 'secret123'})
        self.assertEqual(res.status_code, 200)
        # Once the lock lapses the correct password works again.
        conn = db.get_db()
        conn.execute(
            "UPDATE rate_limit_buckets SET locked_until = '2000-01-01T00:00:00'"
            " WHERE bucket_key = 'login:id:locked@x.test'")
        conn.commit()
        res = self.client.post('/api/auth/login',
                               json={'email': 'locked@x.test', 'password': 'secret123'})
        self.assertEqual(res.status_code, 200, res.get_json())

    def test_login_success_clears_failure_counter(self):
        self._employee('reset@x.test')
        for _ in range(4):
            res = self.client.post('/api/auth/login',
                                   json={'email': 'reset@x.test', 'password': 'nope'})
            self.assertEqual(res.status_code, 401)
        ok = self.client.post('/api/auth/login',
                              json={'email': 'reset@x.test', 'password': 'secret123'})
        self.assertEqual(ok.status_code, 200, ok.get_json())
        # The counter restarted at zero: four more failures are still 401s.
        for _ in range(4):
            res = self.client.post('/api/auth/login',
                                   json={'email': 'reset@x.test', 'password': 'nope'})
            self.assertEqual(res.status_code, 401)

    def test_mfa_verify_attempts_are_bounded_per_account(self):
        uid = self._employee('mfa-lock@x.test')
        secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('user', uid, secret)
        db.activate_mfa('user', uid)
        res = self.client.post('/api/auth/login',
                               json={'email': 'mfa-lock@x.test', 'password': 'secret123'})
        mfa_token = res.get_json()['mfaToken']
        wrong = '000000' if auth.totp_code(secret) != '000000' else '111111'
        for _ in range(5):
            bad = self.client.post('/api/auth/mfa/verify',
                                   json={'mfaToken': mfa_token, 'code': wrong})
            self.assertEqual(bad.status_code, 401)
        blocked = self.client.post('/api/auth/mfa/verify',
                                   json={'mfaToken': mfa_token, 'code': wrong})
        self.assertEqual(blocked.status_code, 429)
        # Minting a fresh challenge does not reset the account's counter.
        res2 = self.client.post('/api/auth/login',
                                json={'email': 'mfa-lock@x.test', 'password': 'secret123'})
        still = self.client.post('/api/auth/mfa/verify',
                                 json={'mfaToken': res2.get_json()['mfaToken'],
                                       'code': auth.totp_code(secret)})
        self.assertEqual(still.status_code, 429)

    def test_mfa_enable_attempts_are_bounded(self):
        # A dedicated user keeps the mfa:op bucket away from the shared admin.
        uid = self._employee('mfa-enable@x.test')
        token = auth.create_token(self.tenant_id, 'mfa-enable@x.test', user_id=uid,
                                  user_name='موظف', user_role='employee')
        headers = self.headers(token)
        setup = self.client.post('/api/auth/mfa/setup', headers=headers, json={})
        self.assertEqual(setup.status_code, 200, setup.get_json())
        for _ in range(5):
            bad = self.client.post('/api/auth/mfa/enable', headers=headers,
                                   json={'code': '000000'})
            self.assertEqual(bad.status_code, 400)
        blocked = self.client.post('/api/auth/mfa/enable', headers=headers,
                                   json={'code': '000000'})
        self.assertEqual(blocked.status_code, 429)

    def test_register_is_bounded_per_ip(self):
        for i in range(10):
            res = self.client.post('/api/auth/register', json={
                'companyName': f'شركة {i}', 'email': f'c{i}@x.test',
                'password': 'password12345'})
            self.assertEqual(res.status_code, 201, res.get_json())
        res = self.client.post('/api/auth/register', json={
            'companyName': 'شركة زائدة', 'email': 'extra@x.test',
            'password': 'password12345'})
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.get_json()['error_code'], 'rate_limited')

    # ── ISS-003: a session that still owes MFA enrolment is confined ─────

    def test_pending_mfa_session_only_reaches_enrolment_endpoints(self):
        login = self.client.post('/api/auth/login',
                                 json={'email': 'boss@x.test', 'password': 'secret123'})
        body = login.get_json()
        self.assertTrue(body.get('mfaSetupRequired'))
        pending = self.headers(body['token'])

        gated = self.client.get('/api/users', headers=pending)
        self.assertEqual(gated.status_code, 403)
        self.assertEqual(gated.get_json()['error_code'], 'mfa_setup_required')
        # The enrolment surface stays reachable under the same token.
        me = self.client.get('/api/auth/me', headers=pending)
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.get_json()['mfa']['setupRequired'])
        self.assertEqual(self.client.get('/api/auth/mfa/status', headers=pending).status_code, 200)
        setup = self.client.post('/api/auth/mfa/setup', headers=pending, json={})
        self.assertEqual(setup.status_code, 200, setup.get_json())
        enabled = self.client.post('/api/auth/mfa/enable', headers=pending,
                                   json={'code': auth.totp_code(setup.get_json()['secret'])})
        self.assertEqual(enabled.status_code, 200, enabled.get_json())
        fresh = enabled.get_json().get('token')
        self.assertTrue(fresh)
        self.assertEqual(self.client.get('/api/users', headers=self.headers(fresh)).status_code, 200)
        # The restricted token never upgrades itself and cannot renew.
        still = self.client.get('/api/users', headers=pending)
        self.assertEqual(still.status_code, 403)
        self.assertEqual(still.get_json()['error_code'], 'mfa_setup_required')
        self.assertEqual(self.client.post('/api/auth/refresh', headers=pending).status_code, 403)

    def test_tenant_direct_login_flags_and_gates_mfa_setup(self):
        conn = db.get_db()
        conn.execute('UPDATE tenants SET password_hash = ? WHERE id = ?',
                     (self.application_module.hash_password('secret123'), self.tenant_id))
        conn.commit()
        login = self.client.post('/api/auth/login',
                                 json={'email': 'co@x.test', 'password': 'secret123'})
        body = login.get_json()
        # A tenant-direct login is the company-admin identity: the flag applies
        # to every company, not only the platform tenant.
        self.assertTrue(body.get('mfaSetupRequired'))
        gated = self.client.get('/api/users', headers=self.headers(body['token']))
        self.assertEqual(gated.status_code, 403)
        self.assertEqual(gated.get_json()['error_code'], 'mfa_setup_required')

    def test_employee_session_is_not_mfa_gated(self):
        self._employee('plain@x.test')
        login = self.client.post('/api/auth/login',
                                 json={'email': 'plain@x.test', 'password': 'secret123'})
        body = login.get_json()
        self.assertTrue(body.get('token'))
        self.assertFalse(body.get('mfaSetupRequired'))
        denied = self.client.get('/api/users', headers=self.headers(body['token']))
        self.assertEqual(denied.status_code, 403)
        self.assertNotEqual(denied.get_json().get('error_code'), 'mfa_setup_required')


class PrimaryAdminIdentityTests(unittest.TestCase):
    """ISS-002: the primary company admin is one login identity — the tenants
    row owns the credential, the MFA factor and the sessions; its users row is
    the management record whose live state still gates the owner login."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'primary-admin.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        self.context = self.app.app_context()
        self.context.push()
        self.password = 'OwnerPass123'
        pw_hash = application_module.hash_password(self.password)
        self.tenant_id = db.create_tenant('شركة المالك', 'owner-co@x.test', pw_hash, 'ownerco')
        self.primary_id = db.create_user(
            self.tenant_id, 'المالك', 'owner-user@x.test', pw_hash, role='company_admin')
        db.update_tenant(self.tenant_id, primary_user_id=self.primary_id)
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, token):
        return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    def _login(self, identity, password=None):
        return self.client.post('/api/auth/login', json={
            'email': identity, 'password': password or self.password})

    def test_owner_login_via_user_email_issues_tenant_session(self):
        res = self._login('owner-user@x.test')
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertTrue(body.get('mfaSetupRequired'))
        self.assertIsNone(auth.decode_token(body['token']).get('user_id'))
        me = self.client.get('/api/auth/me', headers=self.headers(body['token']))
        self.assertEqual(me.status_code, 200, me.get_json())
        self.assertNotIn('id', me.get_json()['user'])
        self.assertEqual(me.get_json()['tenant']['id'], self.tenant_id)

    def test_owner_login_via_tenant_email_issues_tenant_session(self):
        res = self._login('owner-co@x.test')
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertIsNone(auth.decode_token(body['token']).get('user_id'))
        me = self.client.get('/api/auth/me', headers=self.headers(body['token']))
        self.assertNotIn('id', me.get_json()['user'])

    def test_disabled_primary_row_blocks_both_login_paths(self):
        db.update_user(self.primary_id, is_active=0)
        via_company = self._login('owner-co@x.test')
        self.assertIn(via_company.status_code, (401, 403))
        via_user = self._login('owner-user@x.test')
        self.assertEqual(via_user.status_code, 403)
        self.assertEqual(via_user.get_json().get('error'), 'Account is deactivated')

    def test_user_side_password_change_moves_the_owner_login(self):
        db.update_user(
            self.primary_id,
            password_hash=self.application_module.hash_password('BrandNew!234'))
        stale = self._login('owner-co@x.test')
        self.assertEqual(stale.status_code, 401)
        fresh = self._login('owner-co@x.test', 'BrandNew!234')
        self.assertEqual(fresh.status_code, 200, fresh.get_json())
        via_user = self._login('owner-user@x.test', 'BrandNew!234')
        self.assertEqual(via_user.status_code, 200, via_user.get_json())
        tenant_row = db.get_tenant_by_id(self.tenant_id)
        self.assertTrue(auth.verify_password('BrandNew!234', tenant_row['password_hash']))

    def test_legacy_drifted_password_heals_on_first_login(self):
        # Rows written before the mirror can hold diverging hashes; the user
        # record's live credential wins and is adopted onto the tenant row.
        conn = db.get_db()
        conn.execute(
            'UPDATE users SET password_hash = ? WHERE id = ?',
            (self.application_module.hash_password('Drifted!234'), self.primary_id))
        conn.commit()
        self.assertEqual(self._login('owner-co@x.test').status_code, 401)
        healed = self._login('owner-co@x.test', 'Drifted!234')
        self.assertEqual(healed.status_code, 200, healed.get_json())
        tenant_row = db.get_tenant_by_id(self.tenant_id)
        self.assertTrue(auth.verify_password('Drifted!234', tenant_row['password_hash']))

    def test_primary_password_change_retires_tenant_direct_sessions(self):
        token = auth.create_token(self.tenant_id, 'owner-co@x.test',
                                  user_name='المالك', user_role='company_admin')
        ok = self.client.get('/api/auth/me', headers=self.headers(token))
        self.assertEqual(ok.status_code, 200)
        db.update_user(
            self.primary_id,
            password_hash=self.application_module.hash_password('Retired!234'))
        dead = self.client.get('/api/auth/me', headers=self.headers(token))
        self.assertEqual(dead.status_code, 401)

    def test_user_bound_primary_token_normalizes_to_tenant_session(self):
        # The password-setup flow still mints a user-bound token for the owner;
        # the session must run as the tenant identity, not a second account.
        token = auth.create_token(self.tenant_id, 'owner-user@x.test',
                                  user_id=self.primary_id, user_name='المالك',
                                  user_role='company_admin')
        me = self.client.get('/api/auth/me', headers=self.headers(token))
        self.assertEqual(me.status_code, 200, me.get_json())
        self.assertNotIn('id', me.get_json()['user'])
        self.assertFalse(me.get_json()['mfa']['enabled'])
        # The factor the session manages is the tenant-scope one.
        secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('tenant', self.tenant_id, secret)
        db.activate_mfa('tenant', self.tenant_id)
        again = self.client.get('/api/auth/me', headers=self.headers(token))
        self.assertTrue(again.get_json()['mfa']['enabled'])
        self.assertFalse(again.get_json()['mfa']['setupRequired'])

    def test_setup_token_session_enrols_tenant_mfa_end_to_end(self):
        pending = auth.create_token(self.tenant_id, 'owner-user@x.test',
                                    user_id=self.primary_id, user_name='المالك',
                                    user_role='company_admin', mfa_pending=True)
        headers = self.headers(pending)
        setup = self.client.post('/api/auth/mfa/setup', headers=headers, json={})
        self.assertEqual(setup.status_code, 200, setup.get_json())
        enabled = self.client.post('/api/auth/mfa/enable', headers=headers,
                                   json={'code': auth.totp_code(setup.get_json()['secret'])})
        self.assertEqual(enabled.status_code, 200, enabled.get_json())
        # The factor landed on the tenant identity; the user row stays clean.
        self.assertTrue(db.get_mfa_state('tenant', self.tenant_id)['enabled'])
        self.assertFalse(db.get_mfa_state('user', self.primary_id)['enabled'])
        # The clean token handed back after enrolment is tenant-direct.
        fresh = enabled.get_json().get('token')
        self.assertIsNone(auth.decode_token(fresh).get('user_id'))
        # The next login — by either identity — gets the same challenge.
        res = self._login('owner-user@x.test')
        self.assertTrue(res.get_json().get('mfaRequired'))

    def test_tenant_mfa_enrolment_challenges_both_login_identities(self):
        secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('tenant', self.tenant_id, secret)
        db.activate_mfa('tenant', self.tenant_id)
        for identity in ('owner-co@x.test', 'owner-user@x.test'):
            res = self._login(identity)
            body = res.get_json()
            self.assertTrue(body.get('mfaRequired'), body)
            self.assertNotIn('token', body)
            challenge = auth.verify_mfa_token(body['mfaToken'])
            self.assertIsNone(challenge.get('user_id'))
            verified = self.client.post('/api/auth/mfa/verify', json={
                'mfaToken': body['mfaToken'], 'code': auth.totp_code(secret)})
            self.assertEqual(verified.status_code, 200, verified.get_json())
            self.assertIsNone(
                auth.decode_token(verified.get_json()['token']).get('user_id'))

    def test_migration_moves_stray_user_factor_onto_tenant(self):
        secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('user', self.primary_id, secret)
        db.activate_mfa('user', self.primary_id)
        codes = auth.generate_recovery_codes(3)
        db.store_recovery_codes(self.tenant_id, self.primary_id, codes)
        conn = db.get_db()
        db._migrate_primary_admin_identity(conn)
        conn.commit()
        self.assertFalse(db.get_mfa_state('user', self.primary_id)['enabled'])
        tenant_secrets = db.get_mfa_secrets('tenant', self.tenant_id)
        self.assertEqual(tenant_secrets['mfa_secret'], secret)
        self.assertTrue(tenant_secrets['mfa_enabled'])
        # The recovery set moved with the factor to the tenant scope.
        self.assertTrue(db.consume_recovery_code(self.tenant_id, None, codes[0]))
        res = self._login('owner-user@x.test')
        self.assertTrue(res.get_json().get('mfaRequired'))

    def test_migration_drops_user_factor_when_tenant_already_has_one(self):
        tenant_secret = auth.generate_totp_secret()
        db.set_mfa_pending_secret('tenant', self.tenant_id, tenant_secret)
        db.activate_mfa('tenant', self.tenant_id)
        db.set_mfa_pending_secret('user', self.primary_id, auth.generate_totp_secret())
        db.activate_mfa('user', self.primary_id)
        conn = db.get_db()
        db._migrate_primary_admin_identity(conn)
        conn.commit()
        self.assertEqual(
            db.get_mfa_secrets('tenant', self.tenant_id)['mfa_secret'], tenant_secret)
        self.assertFalse(db.get_mfa_state('user', self.primary_id)['enabled'])

    def test_non_primary_company_admin_keeps_user_bound_session(self):
        uid = db.create_user(
            self.tenant_id, 'مدير ثان', 'second@x.test',
            self.application_module.hash_password('secret123'), role='company_admin')
        res = self.client.post('/api/auth/login',
                               json={'email': 'second@x.test', 'password': 'secret123'})
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertEqual(auth.decode_token(body['token']).get('user_id'), uid)
        me = self.client.get('/api/auth/me', headers=self.headers(body['token']))
        self.assertEqual(me.get_json()['user']['id'], uid)

    def test_demoted_primary_loses_owner_login_but_keeps_own(self):
        db.update_user(self.primary_id, role='employee')
        owner = self._login('owner-co@x.test')
        self.assertEqual(owner.status_code, 401)
        own = self._login('owner-user@x.test')
        body = own.get_json()
        self.assertEqual(own.status_code, 200, body)
        self.assertEqual(auth.decode_token(body['token']).get('user_role'), 'employee')
        me = self.client.get('/api/auth/me', headers=self.headers(body['token']))
        self.assertEqual(me.get_json()['user']['role'], 'employee')

    def test_deleted_primary_row_fails_closed(self):
        # A dangling primary_user_id must not silently reopen the un-gated
        # tenant credential; the platform admin repoints a new primary.
        db.delete_user(self.primary_id)
        self.assertEqual(self._login('owner-co@x.test').status_code, 401)
        self.assertEqual(self._login('owner-user@x.test').status_code, 401)


if __name__ == '__main__':
    unittest.main()
