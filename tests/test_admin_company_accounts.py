import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


class AdminCompanyAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'admin-companies.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)

        with cls.app.app_context():
            cls.admin_id = db.create_tenant(
                'System Admin',
                'system-admin@example.test',
                auth.hash_password('AdminPass12345'),
                plan='enterprise',
            )
            db.get_db().execute(
                'UPDATE tenants SET is_admin = 1 WHERE id = ?',
                (cls.admin_id,),
            )
            db.get_db().commit()

        cls.admin_token = auth.create_token(
            cls.admin_id,
            'system-admin@example.test',
            is_admin=True,
            user_name='System Admin',
            user_role='company_admin',
        )
        cls.headers = {'Authorization': f'Bearer {cls.admin_token}'}

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = self.app.test_client()

    def _create_company(self, suffix):
        response = self.client.post(
            '/api/admin/tenants',
            headers=self.headers,
            json={
                'companyName': f'شركة الاختبار {suffix}',
                'accountManagerName': f'مدير الحساب {suffix}',
                'email': f'company-{suffix}@example.test',
                'phone': '+966500000001',
                'username': f'company_{suffix}',
                'plan': 'pro',
                'creditBalance': 1250.5,
                'isActive': True,
                'passwordMode': 'set_link',
                'sendWelcomeEmail': False,
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_admin_creates_company_primary_user_and_workspace(self):
        result = self._create_company('create')
        tenant_id = result['tenant']['id']

        with self.app.app_context():
            tenant = db.get_tenant_by_id(tenant_id)
            users = db.get_users_by_tenant(tenant_id)
            fields = db.get_fields(tenant_id)

        self.assertEqual(tenant['account_manager_name'], 'مدير الحساب create')
        self.assertEqual(tenant['username'], 'company_create')
        self.assertEqual(float(tenant['credit_balance']), 1250.5)
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['id'], tenant['primary_user_id'])
        self.assertEqual(users[0]['role'], 'company_admin')
        self.assertTrue(fields)
        self.assertTrue(result['setupUrl'].endswith(result['setupUrl'].rsplit('/', 1)[-1]))
        self.assertFalse(result['welcomeEmailSent'])

    def test_password_setup_link_is_one_time_and_supports_username_login(self):
        result = self._create_company('password')
        raw_token = result['setupUrl'].rsplit('/', 1)[-1]

        details = self.client.get(f'/api/auth/password-setup/{raw_token}')
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.get_json()['username'], 'company_password')

        completed = self.client.post(
            f'/api/auth/password-setup/{raw_token}',
            json={'password': 'SecurePass123'},
        )
        self.assertEqual(completed.status_code, 200, completed.get_json())
        self.assertTrue(completed.get_json()['token'])

        login = self.client.post(
            '/api/auth/login',
            json={'username': 'company_password', 'password': 'SecurePass123'},
        )
        self.assertEqual(login.status_code, 200, login.get_json())

        reused = self.client.post(
            f'/api/auth/password-setup/{raw_token}',
            json={'password': 'AnotherPass123'},
        )
        self.assertEqual(reused.status_code, 404)

    def test_duplicate_identity_and_invalid_account_data_are_rejected(self):
        self._create_company('unique')

        duplicate = self.client.post(
            '/api/admin/tenants',
            headers=self.headers,
            json={
                'companyName': 'شركة أخرى',
                'accountManagerName': 'مدير آخر',
                'email': 'other@example.test',
                'phone': '+966500000002',
                'username': 'company_unique',
                'passwordMode': 'set_link',
            },
        )
        self.assertEqual(duplicate.status_code, 409)

        invalid = self.client.post(
            '/api/admin/tenants',
            headers=self.headers,
            json={
                'companyName': 'شركة غير صالحة',
                'accountManagerName': 'مدير',
                'email': 'not-an-email',
                'phone': '12',
                'username': 'x',
                'passwordMode': 'manual',
                'password': 'short',
            },
        )
        self.assertEqual(invalid.status_code, 400)

    def test_company_profile_plan_credit_status_and_manager_are_editable(self):
        result = self._create_company('profile')
        tenant_id = result['tenant']['id']

        updated = self.client.put(
            f'/api/admin/tenants/{tenant_id}',
            headers=self.headers,
            json={
                'companyName': 'شركة الملف المحدثة',
                'accountManagerName': 'مدير الملف المحدث',
                'email': 'profile-updated@example.test',
                'phone': '+966500000010',
                'username': 'profile_updated',
                'plan': 'enterprise',
                'creditBalance': 9000,
                'isActive': True,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.get_json())
        tenant = updated.get_json()['tenant']
        self.assertEqual(tenant['companyName'], 'شركة الملف المحدثة')
        self.assertEqual(tenant['accountManagerName'], 'مدير الملف المحدث')
        self.assertEqual(tenant['plan'], 'enterprise')
        self.assertEqual(tenant['creditBalance'], 9000)

        with self.app.app_context():
            primary = db.get_user_by_id(tenant['primaryUserId'])
            branding = db.get_branding(tenant_id)
        self.assertEqual(primary['email'], 'profile-updated@example.test')
        self.assertEqual(primary['username'], 'profile_updated')
        self.assertEqual(branding['company_name'], 'شركة الملف المحدثة')

    def test_admin_adds_users_and_changes_primary_company_manager(self):
        result = self._create_company('users')
        tenant_id = result['tenant']['id']
        old_primary_id = result['tenant']['primaryUserId']

        added = self.client.post(
            f'/api/admin/tenants/{tenant_id}/users',
            headers=self.headers,
            json={
                'name': 'مدير الحساب الجديد',
                'email': 'new-manager@example.test',
                'username': 'new_manager',
                'phone': '+966500000020',
                'role': 'company_admin',
                'useSetupLink': True,
            },
        )
        self.assertEqual(added.status_code, 201, added.get_json())
        new_user_id = added.get_json()['user']['id']

        promoted = self.client.put(
            f'/api/admin/tenants/{tenant_id}/users/{new_user_id}',
            headers=self.headers,
            json={'isPrimary': True},
        )
        self.assertEqual(promoted.status_code, 200, promoted.get_json())

        with self.app.app_context():
            tenant = db.get_tenant_by_id(tenant_id)
            old_primary = db.get_user_by_id(old_primary_id)
            new_primary = db.get_user_by_id(new_user_id)
        self.assertEqual(tenant['primary_user_id'], new_user_id)
        self.assertEqual(tenant['account_manager_name'], 'مدير الحساب الجديد')
        self.assertEqual(old_primary['role'], 'employee')
        self.assertEqual(new_primary['role'], 'company_admin')

    def test_company_admin_cannot_access_super_admin_company_creation(self):
        company = self._create_company('permission')
        tenant_id = company['tenant']['id']
        with self.app.app_context():
            tenant = db.get_tenant_by_id(tenant_id)
        company_token = auth.create_token(
            tenant_id,
            tenant['email'],
            user_name=tenant['company_name'],
            user_role='company_admin',
        )
        response = self.client.post(
            '/api/admin/tenants',
            headers={'Authorization': f'Bearer {company_token}'},
            json={},
        )
        self.assertEqual(response.status_code, 403)

    def test_company_details_returns_counts_and_profile(self):
        result = self._create_company('details')
        tenant_id = result['tenant']['id']
        response = self.client.get(
            f'/api/admin/tenants/{tenant_id}/details',
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['tenant']['id'], tenant_id)
        self.assertEqual(payload['tenant']['companyName'], result['tenant']['companyName'])
        self.assertEqual(payload['tenant']['accountManagerName'], 'مدير الحساب details')
        self.assertIn('users', payload['counts'])
        self.assertIn('projects', payload['counts'])
        self.assertIn('presentations', payload['counts'])
        self.assertIn('exports', payload['counts'])
        self.assertEqual(payload['counts']['users'], 1)
        self.assertEqual(len(payload['users']), 1)
        self.assertEqual(payload['branding']['company_name'], result['tenant']['companyName'])
        self.assertNotIn('password_hash', payload['tenant'])

    def test_suspended_company_cannot_login_and_reactivation_restores_access(self):
        response = self.client.post(
            '/api/admin/tenants',
            headers=self.headers,
            json={
                'companyName': 'شركة الإيقاف',
                'accountManagerName': 'مدير الإيقاف',
                'email': 'suspend-company@example.test',
                'phone': '+966500000031',
                'username': 'suspend_company',
                'plan': 'pro',
                'creditBalance': 0,
                'isActive': True,
                'passwordMode': 'manual',
                'password': 'ManualPass123',
                'sendWelcomeEmail': False,
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        tenant_id = response.get_json()['tenant']['id']

        login = self.client.post(
            '/api/auth/login',
            json={'username': 'suspend_company', 'password': 'ManualPass123'},
        )
        self.assertEqual(login.status_code, 200, login.get_json())

        suspended = self.client.put(
            f'/api/admin/tenants/{tenant_id}',
            headers=self.headers,
            json={'isActive': False},
        )
        self.assertEqual(suspended.status_code, 200, suspended.get_json())
        self.assertFalse(suspended.get_json()['tenant']['isActive'])

        blocked = self.client.post(
            '/api/auth/login',
            json={'username': 'suspend_company', 'password': 'ManualPass123'},
        )
        self.assertEqual(blocked.status_code, 403)

        reactivated = self.client.put(
            f'/api/admin/tenants/{tenant_id}',
            headers=self.headers,
            json={'isActive': True},
        )
        self.assertEqual(reactivated.status_code, 200, reactivated.get_json())

        login_again = self.client.post(
            '/api/auth/login',
            json={'username': 'suspend_company', 'password': 'ManualPass123'},
        )
        self.assertEqual(login_again.status_code, 200, login_again.get_json())

    def test_admin_reset_password_via_setup_link_and_manual_password(self):
        result = self._create_company('resetflow')
        tenant_id = result['tenant']['id']
        first_token = result['setupUrl'].rsplit('/', 1)[-1]

        reset = self.client.post(
            f'/api/admin/tenants/{tenant_id}/reset-password',
            headers=self.headers,
            json={'useSetupLink': True},
        )
        self.assertEqual(reset.status_code, 200, reset.get_json())
        second_token = reset.get_json()['setupUrl'].rsplit('/', 1)[-1]
        self.assertNotEqual(first_token, second_token)

        stale = self.client.get(f'/api/auth/password-setup/{first_token}')
        self.assertEqual(stale.status_code, 404)

        completed = self.client.post(
            f'/api/auth/password-setup/{second_token}',
            json={'password': 'ResetPass1234'},
        )
        self.assertEqual(completed.status_code, 200, completed.get_json())

        manual = self.client.post(
            f'/api/admin/tenants/{tenant_id}/reset-password',
            headers=self.headers,
            json={'password': 'ManualReset123'},
        )
        self.assertEqual(manual.status_code, 200, manual.get_json())

        login = self.client.post(
            '/api/auth/login',
            json={'username': 'company_resetflow', 'password': 'ManualReset123'},
        )
        self.assertEqual(login.status_code, 200, login.get_json())

        weak = self.client.post(
            f'/api/admin/tenants/{tenant_id}/reset-password',
            headers=self.headers,
            json={'password': 'short'},
        )
        self.assertEqual(weak.status_code, 400)

    def test_admin_deletes_non_primary_user_but_primary_is_protected(self):
        result = self._create_company('deleteuser')
        tenant_id = result['tenant']['id']
        primary_id = result['tenant']['primaryUserId']

        added = self.client.post(
            f'/api/admin/tenants/{tenant_id}/users',
            headers=self.headers,
            json={
                'name': 'موظف للحذف',
                'email': 'delete-me@example.test',
                'username': 'delete_me_user',
                'phone': '+966500000032',
                'role': 'employee',
                'useSetupLink': True,
            },
        )
        self.assertEqual(added.status_code, 201, added.get_json())
        extra_id = added.get_json()['user']['id']

        protected = self.client.delete(
            f'/api/admin/tenants/{tenant_id}/users/{primary_id}',
            headers=self.headers,
        )
        self.assertEqual(protected.status_code, 400)

        removed = self.client.delete(
            f'/api/admin/tenants/{tenant_id}/users/{extra_id}',
            headers=self.headers,
        )
        self.assertEqual(removed.status_code, 200, removed.get_json())

        with self.app.app_context():
            self.assertIsNone(db.get_user_by_id(extra_id))
            self.assertIsNotNone(db.get_user_by_id(primary_id))

    def test_manual_password_creation_and_plan_credit_validation(self):
        created = self.client.post(
            '/api/admin/tenants',
            headers=self.headers,
            json={
                'companyName': 'شركة يدوية',
                'accountManagerName': 'مدير يدوي',
                'email': 'manual-company@example.test',
                'phone': '+966500000033',
                'username': 'manual_company',
                'plan': 'enterprise',
                'creditBalance': 500,
                'isActive': True,
                'passwordMode': 'manual',
                'password': 'ManualPass123',
                'sendWelcomeEmail': False,
            },
        )
        self.assertEqual(created.status_code, 201, created.get_json())

        login = self.client.post(
            '/api/auth/login',
            json={'username': 'manual_company', 'password': 'ManualPass123'},
        )
        self.assertEqual(login.status_code, 200, login.get_json())

        for payload, expected in (
            ({'plan': 'diamond'}, 400),
            ({'creditBalance': -10}, 400),
            ({'phone': '12'}, 400),
            ({'username': 'x'}, 400),
        ):
            base = {
                'companyName': f"شركة فحص {expected} {list(payload)[0]}",
                'accountManagerName': 'مدير فحص',
                'email': f"check-{list(payload)[0]}@example.test",
                'phone': '+966500000034',
                'username': f"check_{list(payload)[0]}",
                'passwordMode': 'set_link',
            }
            base.update(payload)
            rejected = self.client.post(
                '/api/admin/tenants',
                headers=self.headers,
                json=base,
            )
            self.assertEqual(rejected.status_code, expected, (payload, rejected.get_json()))

        existing = self._create_company('conflictbase')
        conflict_update = self.client.put(
            f"/api/admin/tenants/{existing['tenant']['id']}",
            headers=self.headers,
            json={'email': 'manual-company@example.test'},
        )
        self.assertEqual(conflict_update.status_code, 409)

    def test_tenant_data_isolation_between_companies(self):
        company_a = self._create_company('isoa')
        company_b = self._create_company('isob')
        id_a = company_a['tenant']['id']
        id_b = company_b['tenant']['id']
        self.assertNotEqual(id_a, id_b)

        with self.app.app_context():
            users_a = db.get_users_by_tenant(id_a)
            users_b = db.get_users_by_tenant(id_b)
        self.assertEqual(len(users_a), 1)
        self.assertEqual(len(users_b), 1)
        self.assertNotEqual(users_a[0]['id'], users_b[0]['id'])
        self.assertNotEqual(users_a[0]['email'], users_b[0]['email'])
        with self.app.app_context():
            full_a = db.get_user_by_id(users_a[0]['id'])
            full_b = db.get_user_by_id(users_b[0]['id'])
        self.assertEqual(full_a['tenant_id'], id_a)
        self.assertEqual(full_b['tenant_id'], id_b)

        token_a = company_a['setupUrl'].rsplit('/', 1)[-1]
        details_a = self.client.get(f'/api/auth/password-setup/{token_a}')
        self.assertEqual(details_a.status_code, 200)
        self.assertEqual(details_a.get_json()['username'], 'company_isoa')

        with self.app.app_context():
            db.save_project_draft(
                id_a, users_a[0]['id'], {'project_name': 'مشروع الشركة أ'},
                {}, 'draft', draft_id='draft-iso-a',
            )
            db.save_project_draft(
                id_b, users_b[0]['id'], {'project_name': 'مشروع الشركة ب'},
                {}, 'draft', draft_id='draft-iso-b',
            )
            cross = db.get_project_draft_by_id(id_a, 'draft-iso-b')
            own = db.get_project_draft_by_id(id_a, 'draft-iso-a')
            summaries_a = db.get_all_project_draft_summaries(id_a)
            summaries_b = db.get_all_project_draft_summaries(id_b)
        self.assertIsNone(cross)
        self.assertEqual(own['draft_data']['project_name'], 'مشروع الشركة أ')
        self.assertTrue(all(item['tenant_id'] == id_a for item in summaries_a))
        self.assertTrue(all(item['tenant_id'] == id_b for item in summaries_b))

        listed = self.client.get('/api/admin/tenants', headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        for item in listed.get_json()['tenants']:
            self.assertNotIn('password_hash', item)
            self.assertNotIn('passwordHash', item)

    def test_non_admin_permissions_are_denied_for_all_admin_routes(self):
        company = self._create_company('denied')
        tenant_id = company['tenant']['id']
        with self.app.app_context():
            tenant = db.get_tenant_by_id(tenant_id)
        company_headers = {'Authorization': 'Bearer ' + auth.create_token(
            tenant_id, tenant['email'],
            user_name=tenant['company_name'], user_role='company_admin',
        )}
        denied = [
            ('GET', '/api/admin/tenants', None),
            ('GET', f'/api/admin/tenants/{tenant_id}/details', None),
            ('GET', f'/api/admin/tenants/{tenant_id}/users', None),
            ('PUT', f'/api/admin/tenants/{tenant_id}', {'companyName': 'x'}),
            ('POST', f'/api/admin/tenants/{tenant_id}/users', {}),
            ('POST', f'/api/admin/tenants/{tenant_id}/reset-password', {}),
        ]
        for method, url, payload in denied:
            if method == 'GET':
                response = self.client.get(url, headers=company_headers)
            elif method == 'PUT':
                response = self.client.put(url, headers=company_headers, json=payload)
            else:
                response = self.client.post(url, headers=company_headers, json=payload)
            self.assertIn(response.status_code, (401, 403), (method, url))

        anonymous = self.client.get('/api/admin/tenants')
        self.assertEqual(anonymous.status_code, 401)


if __name__ == '__main__':
    unittest.main()