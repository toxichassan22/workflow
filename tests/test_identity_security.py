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
                                      json={'password': 'secret123'})
        body = registered.get_json()
        self.assertEqual(registered.status_code, 201, body)
        self.assertEqual(body['user']['role'], 'section_editor')
        new_user = db.get_user_by_email('invited@x.test')
        self.assertEqual(new_user['role'], 'section_editor')
        self.assertEqual(db.get_user_project_scope_ids(new_user['id']), {draft_id})
        self.assertTrue(db.get_user_field_sections(new_user['id'], self.tenant_id).get('basic'))
        # The link is spent.
        again = self.client.post(f'/api/invite/{token}/register', json={'password': 'secret123'})
        self.assertEqual(again.status_code, 404)
        # Resend refuses a used invite.
        resend = self.client.post(
            f"/api/invites/{created.get_json()['inviteId']}/resend",
            headers=self.headers(self.admin_user_token), json={})
        self.assertEqual(resend.status_code, 409)

    def test_billing_permission_gates_recharge(self):
        uid = self._employee('nobill@x.test')
        emp_token = auth.create_token(self.tenant_id, 'nobill@x.test', user_id=uid,
                                      user_name='موظف', user_role='employee')
        denied = self.client.post('/api/recharge-requests', headers=self.headers(emp_token),
                                  json={'packageName': 'باقة', 'amountUsd': 10})
        self.assertEqual(denied.status_code, 403)
        db.set_user_permission(uid, 'billing', True)
        allowed = self.client.post('/api/recharge-requests', headers=self.headers(emp_token),
                                   json={'packageName': 'باقة نمو', 'amountUsd': 100,
                                         'priceSar': 375, 'referenceNumber': 'TRX-SEC-1'})
        self.assertEqual(allowed.status_code, 200, allowed.get_json())


if __name__ == '__main__':
    unittest.main()
