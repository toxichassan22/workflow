

class PrimaryAdminIdentityTests(unittest.TestCase):
    """ISS-002: the primary company admin is one login identity — the tenants
    row owns the credential and the sessions; its users row is
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
            self.tenant_id, 'المالك', 'owner-user@x.test', pw_hash, role='employee')
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

    def test_non_primary_user_keeps_user_bound_session(self):
        # A legacy role claim in the row grants nothing — the session stays a
        # plain user-bound employee session.
        uid = db.create_user(
            self.tenant_id, 'مدير ثان', 'second@x.test',
            self.application_module.hash_password('secret123'), role='employee')
        res = self.client.post('/api/auth/login',
                               json={'email': 'second@x.test', 'password': 'secret123'})
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertEqual(auth.decode_token(body['token']).get('user_id'), uid)
        me = self.client.get('/api/auth/me', headers=self.headers(body['token']))
        self.assertEqual(me.get_json()['user']['id'], uid)

    def test_reassigned_primary_moves_the_owner_login(self):
        # Replacing the primary link moves the company login to the new row's
        # credentials; the old primary keeps its own employee session.
        second = db.create_user(
            self.tenant_id, 'المالك الجديد', 'owner2@x.test',
            self.application_module.hash_password('Second!234'), role='employee')
        db.set_primary_company_admin(self.tenant_id, second)
        # The tenant row now carries the new primary's credentials, so the old
        # company email no longer resolves; the new owner's user email issues
        # the tenant-direct session instead.
        stale = self._login('owner-co@x.test')
        self.assertEqual(stale.status_code, 401)
        moved = self._login('owner2@x.test', 'Second!234')
        self.assertEqual(moved.status_code, 200, moved.get_json())
        self.assertIsNone(auth.decode_token(moved.get_json()['token']).get('user_id'))
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
