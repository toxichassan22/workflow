"""Per-tenant OpenRouter keys: storage, runtime selection and super-admin wiring.

The suite uses a temporary SQLite database and never calls a provider: HTTP
and the Management API client are always patched, so every assertion is about
this repository's own behaviour.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import db


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class TenantOpenRouterKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.uploads_temp = tempfile.TemporaryDirectory(dir=ROOT)
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'tenant-keys.db')

        import app as application_module

        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.application_module.UPLOADS_DIR = os.path.join(cls.uploads_temp.name, 'uploads')
        # Auto-provisioning must never touch the network in tests.
        cls.application_module.OPENROUTER_MANAGEMENT_KEY = None
        cls._orig_global_key = application_module.OPENROUTER_KEY
        cls.application_module.OPENROUTER_KEY = 'global-fallback-key'

        with cls.app.app_context():
            db.init_db()
            cls.tenant_id = db.create_tenant('Key Co', 'keys@example.test', 'hash', 'key-co')
            cls.admin_tenant = db.create_tenant('SAG Admin', 'sag-admin@example.test', 'hash', 'sag-admin')
            db.get_db().execute(
                'UPDATE tenants SET is_admin = 1 WHERE id = ?', (cls.admin_tenant,))
            db.get_db().commit()

        cls.token = auth.create_token(
            cls.tenant_id, 'keys@example.test', user_id=None, user_name='Key Admin',
            user_role='company_admin',
        )
        cls.admin_token = auth.create_token(
            cls.admin_tenant, 'sag-admin@example.test', user_id=None,
            user_name='SAG', user_role='company_admin',
        )

    @classmethod
    def tearDownClass(cls):
        cls.application_module.OPENROUTER_MANAGEMENT_KEY = None
        cls.application_module.OPENROUTER_KEY = cls._orig_global_key
        cls.temp_dir.cleanup()
        cls.uploads_temp.cleanup()

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}'}

    def _admin_headers(self):
        return {'Authorization': f'Bearer {self.admin_token}'}

    def _fresh_tenant(self, name, email, slug):
        with self.app.app_context():
            return db.create_tenant(name, email, 'hash', slug)

    # ── Storage ──────────────────────────────────────────────────────

    def test_key_table_exists_after_init(self):
        import sqlite3
        conn = sqlite3.connect(db.DB_PATH)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn('tenant_openrouter_keys', names)

    def test_encrypt_decrypt_roundtrip_and_tamper(self):
        with self.app.app_context():
            enc = db.encrypt_tenant_openrouter_key('sk-or-v1-secret-value')
            self.assertNotIn('sk-or-v1-secret-value', enc)
            self.assertEqual(db.decrypt_tenant_openrouter_key(enc), 'sk-or-v1-secret-value')
            self.assertIsNone(db.decrypt_tenant_openrouter_key(enc + 'x'))

    def test_set_and_read_key_meta_never_returns_secret(self):
        with self.app.app_context():
            meta = db.set_tenant_openrouter_key(
                self.tenant_id, 'sk-or-v1-tenant-secret-aaaaaaaaaaaaaaaa',
                key_label='Tenant Key', limit_usd=12.5, limit_reset='monthly',
                provenance='manual', openrouter_key_hash='abcd1234')
            self.assertTrue(meta['has_key'])
            self.assertEqual(meta['limit_usd'], 12.5)
            self.assertEqual(meta['provenance'], 'manual')
            dumped = json.dumps(meta, ensure_ascii=False)
            self.assertNotIn('sk-or-v1-tenant-secret', dumped)
            raw = db.get_tenant_openrouter_key_raw(self.tenant_id)
            self.assertEqual(raw, 'sk-or-v1-tenant-secret-aaaaaaaaaaaaaaaa')
            db.deactivate_tenant_openrouter_key(self.tenant_id)
            self.assertIsNone(db.get_tenant_openrouter_key_raw(self.tenant_id))
            refreshed = db.get_tenant_openrouter_key_meta(self.tenant_id)
            self.assertFalse(refreshed['is_active'])

    # ── Runtime selection ────────────────────────────────────────────

    def test_runtime_prefers_tenant_key_then_falls_back(self):
        module = self.application_module
        with self.app.app_context():
            db.set_tenant_openrouter_key(
                self.tenant_id, 'sk-or-v1-tenant-runtime-key-bbbbbbbbbbbbbbbb',
                provenance='manual')
            self.assertEqual(
                module._resolve_openrouter_key(tenant_id=self.tenant_id),
                'sk-or-v1-tenant-runtime-key-bbbbbbbbbbbbbbbb')
            self.assertEqual(
                module._resolve_openrouter_key(
                    {'tenant_id': '00000000-0000-0000-0000-000000000000'}),
                'global-fallback-key')
            db.deactivate_tenant_openrouter_key(self.tenant_id)

    def test_chat_uses_tenant_bearer_header(self):
        module = self.application_module
        seen = {}

        def _fake_post(url, headers=None, json=None, timeout=None):
            seen['auth'] = (headers or {}).get('Authorization')
            return _FakeResponse({
                'choices': [{'message': {'content': 'ok'}}],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5},
                'id': 'gen-tenant-header',
            })

        with self.app.app_context():
            db.set_tenant_openrouter_key(
                self.tenant_id, 'sk-or-v1-tenant-bearer-cccccccccccccccc',
                provenance='manual')
            with patch.object(module.requests, 'post', side_effect=_fake_post):
                resp = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.tenant_id, 'flow': 'other'})
            self.assertIn('choices', resp)
            self.assertEqual(seen.get('auth'), 'Bearer sk-or-v1-tenant-bearer-cccccccccccccccc')
            db.deactivate_tenant_openrouter_key(self.tenant_id)

    # ── Super-admin endpoints ────────────────────────────────────────

    def test_key_endpoints_require_super_admin(self):
        client = self.app.test_client()
        denied = client.get(
            f'/api/admin/tenants/{self.tenant_id}/openrouter-key', headers=self._headers())
        self.assertEqual(denied.status_code, 403)

    def test_manual_add_provision_update_refresh_delete(self):
        module = self.application_module
        client = self.app.test_client()
        tenant_id = self._fresh_tenant('Manual Co', 'manual-key@example.test', 'manual-key-co')
        status = client.get(
            f'/api/admin/tenants/{tenant_id}/openrouter-key',
            headers=self._admin_headers()).get_json()
        self.assertTrue(status['success'])
        self.assertFalse(status['key']['has_key'])

        live = {'label': 'Tenant Key', 'limit': 20.0, 'limit_reset': 'monthly',
                'limit_remaining': 19.5, 'usage': 0.5, 'hash': 'livehash99'}
        # The live validation is patched: no provider call happens in tests.
        with patch.object(module, '_openrouter_key_status', return_value=dict(live)):
            added = client.post(
                f'/api/admin/tenants/{tenant_id}/openrouter-key/manual',
                headers=self._admin_headers(),
                json={'apiKey': 'sk-or-v1-manual-admin-key-dddddddddddddddd',
                      'label': 'Tenant Key'})
        self.assertEqual(added.status_code, 201, added.get_json())
        body = added.get_json()
        self.assertTrue(body['key']['has_key'])
        self.assertEqual(body['key']['provenance'], 'manual')
        self.assertNotIn('sk-or-v1-manual', json.dumps(body, ensure_ascii=False))

        updated = client.put(
            f'/api/admin/tenants/{tenant_id}/openrouter-key',
            headers=self._admin_headers(), json={'limitUsd': 30})
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertEqual(updated.get_json()['key']['limit_usd'], 30)

        with patch.object(module, '_openrouter_key_status',
                          return_value=dict(live, limit_remaining=18.0, usage=2.0)):
            refreshed = client.post(
                f'/api/admin/tenants/{tenant_id}/openrouter-key/refresh',
                headers=self._admin_headers())
        self.assertEqual(refreshed.status_code, 200, refreshed.get_json())
        self.assertEqual(refreshed.get_json()['key']['last_limit_remaining'], 18.0)

        deleted = client.delete(
            f'/api/admin/tenants/{tenant_id}/openrouter-key',
            headers=self._admin_headers())
        self.assertEqual(deleted.status_code, 200, deleted.get_json())
        self.assertFalse(deleted.get_json()['key']['is_active'])

    def test_provision_needs_management_key_then_creates(self):
        module = self.application_module
        client = self.app.test_client()
        tenant_id = self._fresh_tenant('Provision Co', 'provision-key@example.test', 'provision-key-co')
        refused = client.post(
            f'/api/admin/tenants/{tenant_id}/openrouter-key/provision',
            headers=self._admin_headers(), json={'limitUsd': 15})
        self.assertEqual(refused.status_code, 503)

        created_body = {'key': 'sk-or-v1-managed-key-eeeeeeeeeeeeeeee',
                        'label': 'tenant-key-co', 'limit': 15.0,
                        'limit_reset': 'monthly', 'hash': 'managedhash11'}
        with patch.object(module, '_openrouter_management_key', return_value='mgmt-test'), \
                patch.object(module, '_openrouter_create_managed_key',
                             return_value=dict(created_body)):
            done = client.post(
                f'/api/admin/tenants/{tenant_id}/openrouter-key/provision',
                headers=self._admin_headers(), json={'limitUsd': 15})
        self.assertEqual(done.status_code, 201, done.get_json())
        payload = done.get_json()
        self.assertEqual(payload['key']['provenance'], 'auto')
        self.assertEqual(payload['key']['openrouter_key_hash'], 'managedhash11')
        self.assertNotIn('sk-or-v1-managed', json.dumps(payload, ensure_ascii=False))
        with self.app.app_context():
            self.assertEqual(
                db.get_tenant_openrouter_key_raw(tenant_id),
                'sk-or-v1-managed-key-eeeeeeeeeeeeeeee')

    def test_ensure_provisions_for_company_but_skips_admin(self):
        module = self.application_module
        tenant_id = self._fresh_tenant('Ensure Co', 'ensure-key@example.test', 'ensure-key-co')
        created_body = {'key': 'sk-or-v1-auto-key-ffffffffffffffff',
                        'label': 'tenant-key-co', 'limit': 0.0,
                        'limit_reset': 'monthly', 'hash': 'autohash22'}
        blocked_status = {'label': 'tenant-key-co', 'limit': 0.0, 'limit_reset': 'monthly',
                          'limit_remaining': 0.0, 'usage': 0.0, 'hash': 'autohash22'}
        with self.app.app_context():
            with patch.object(module, '_openrouter_management_key', return_value='mgmt-test'), \
                    patch.object(module, '_openrouter_create_managed_key',
                                 return_value=dict(created_body)), \
                    patch.object(module, '_openrouter_key_status',
                                 return_value=dict(blocked_status)):
                meta = module._ensure_tenant_openrouter_key(tenant_id)
                self.assertTrue(meta['has_key'])
                self.assertEqual(meta['provenance'], 'auto')
                self.assertEqual(meta['limit_usd'], 0.0)
                admin_meta = module._ensure_tenant_openrouter_key(self.admin_tenant)
                self.assertIsNone(admin_meta)

    def test_strict_mode_refuses_company_without_key(self):
        module = self.application_module
        tenant_id = self._fresh_tenant('Strict Co', 'strict-key@example.test', 'strict-key-co')
        with self.app.app_context():
            with patch.object(module, 'REQUIRE_TENANT_OPENROUTER_KEY', True), \
                    patch.object(module.requests, 'post') as fake_post:
                resp = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': tenant_id, 'flow': 'other'})
                self.assertIn('error', resp)
                self.assertEqual(resp['error'].get('error_code'), 'NO_TENANT_KEY')
                fake_post.assert_not_called()
                self.assertIsNone(module.call_image_api(
                    'a villa', usage_ctx={'tenant_id': tenant_id, 'flow': 'image'}))
                fake_post.assert_not_called()

    def test_strict_mode_passes_with_key_and_for_admins(self):
        module = self.application_module

        def _fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse({
                'choices': [{'message': {'content': 'ok'}}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                'id': 'gen-strict-1',
            })

        tenant_id = self._fresh_tenant('Strict Ok Co', 'strict-ok@example.test', 'strict-ok')
        with self.app.app_context():
            db.set_tenant_openrouter_key(
                tenant_id, 'sk-or-v1-strict-key-jjjjjjjjjjjjjjjj', provenance='manual')
            with patch.object(module, 'REQUIRE_TENANT_OPENROUTER_KEY', True), \
                    patch.object(module.requests, 'post', side_effect=_fake_post) as fake_post:
                resp = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': tenant_id, 'flow': 'other'})
                self.assertIn('choices', resp)
                self.assertEqual(fake_post.call_count, 1)
                admin_resp = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': self.admin_tenant, 'flow': 'other'})
                self.assertIn('choices', admin_resp)
                self.assertEqual(fake_post.call_count, 2)

    def test_fallback_stays_when_strict_is_off(self):
        module = self.application_module

        def _fake_post(url, headers=None, json=None, timeout=None):
            self.assertEqual((headers or {}).get('Authorization'),
                             'Bearer global-fallback-key')
            return _FakeResponse({
                'choices': [{'message': {'content': 'ok'}}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                'id': 'gen-fallback-1',
            })

        tenant_id = self._fresh_tenant('Fallback Co', 'fallback@example.test', 'fallback-co')
        with self.app.app_context():
            with patch.object(module, 'REQUIRE_TENANT_OPENROUTER_KEY', False), \
                    patch.object(module.requests, 'post', side_effect=_fake_post):
                resp = module.call_openrouter_chat(
                    'sys', 'hi', max_tokens=10,
                    usage_ctx={'tenant_id': tenant_id, 'flow': 'other'})
                self.assertIn('choices', resp)

    def test_deleting_tenant_removes_its_dashboard_key(self):
        module = self.application_module
        client = self.app.test_client()
        tenant_id = self._fresh_tenant('Gone Co', 'gone-key@example.test', 'gone-key-co')
        with self.app.app_context():
            db.set_tenant_openrouter_key(
                tenant_id, 'sk-or-v1-gone-key-kkkkkkkkkkkkkkkk', provenance='auto',
                openrouter_key_hash='gonehash55', limit_usd=5.0)
        with patch.object(module, '_openrouter_delete_managed_key',
                          return_value={'ok': True}) as deleted:
            resp = client.delete(f'/api/admin/tenants/{tenant_id}',
                                 headers=self._admin_headers())
        self.assertEqual(resp.status_code, 200, resp.get_json())
        deleted.assert_called_once_with('gonehash55')
        with self.app.app_context():
            self.assertIsNone(db.get_tenant_by_id(tenant_id))
            self.assertFalse(
                db.get_tenant_openrouter_key_meta(tenant_id).get('has_key'))

    def test_zero_provision_rolls_back_when_provider_ignores_limit(self):
        module = self.application_module
        client = self.app.test_client()
        tenant_id = self._fresh_tenant('Zero Co', 'zero-key@example.test', 'zero-key-co')
        created_body = {'key': 'sk-or-v1-zero-key-gggggggggggggggg',
                        'label': 'tenant-zero', 'limit': 0.0,
                        'limit_reset': 'monthly', 'hash': 'zerohash33'}
        unlimited_status = {'label': 'tenant-zero', 'limit': None,
                            'limit_reset': 'monthly', 'limit_remaining': None,
                            'usage': 0.0, 'hash': 'zerohash33'}
        with patch.object(module, '_openrouter_management_key', return_value='mgmt-test'), \
                patch.object(module, '_openrouter_create_managed_key',
                             return_value=dict(created_body)), \
                patch.object(module, '_openrouter_key_status',
                             return_value=dict(unlimited_status)), \
                patch.object(module, '_openrouter_delete_managed_key',
                             return_value={'ok': True}) as deleted:
            done = client.post(
                f'/api/admin/tenants/{tenant_id}/openrouter-key/provision',
                headers=self._admin_headers(), json={'limitUsd': 0})
        self.assertEqual(done.status_code, 503, done.get_json())
        deleted.assert_called_once()
        with self.app.app_context():
            meta = db.get_tenant_openrouter_key_meta(tenant_id)
        self.assertTrue(meta['has_key'])
        self.assertFalse(meta['is_active'])

    def test_ensure_all_issues_keys_to_keyless_companies_only(self):
        module = self.application_module
        client = self.app.test_client()
        keyed_id = self._fresh_tenant('Keyed Co', 'keyed-bulk@example.test', 'keyed-bulk')
        bare_id = self._fresh_tenant('Bare Co', 'bare-bulk@example.test', 'bare-bulk')
        with self.app.app_context():
            db.set_tenant_openrouter_key(
                keyed_id, 'sk-or-v1-existing-key-hhhhhhhhhhhhhhhh', provenance='manual')
        bodies = {'n': 0}

        def _fake_create(name, limit_usd, limit_reset='monthly'):
            bodies['n'] += 1
            tag = f"bulk{bodies['n']}"
            return {'key': f'sk-or-v1-bulk-key-{tag}-iiiiiiiiii',
                    'label': name, 'limit': 0.0,
                    'limit_reset': limit_reset, 'hash': f'bulkhash-{tag}'}

        def _fake_status(api_key, timeout=20):
            return {'label': 'bulk', 'limit': 0.0, 'limit_reset': 'monthly',
                    'limit_remaining': 0.0, 'usage': 0.0, 'hash': 'bulkhash'}
        # Without a management key the bulk run refuses before touching anyone.
        refused = client.post('/api/admin/openrouter-keys/ensure-all',
                              headers=self._admin_headers(), json={})
        self.assertEqual(refused.status_code, 503)
        with patch.object(module, '_openrouter_management_key', return_value='mgmt-test'), \
                patch.object(module, '_openrouter_create_managed_key',
                             side_effect=_fake_create), \
                patch.object(module, '_openrouter_key_status', side_effect=_fake_status):
            done = client.post('/api/admin/openrouter-keys/ensure-all',
                               headers=self._admin_headers(), json={'batch': 50})
        self.assertEqual(done.status_code, 200, done.get_json())
        body = done.get_json()
        by_tenant = {row['tenantId']: row for row in body['results']}
        self.assertNotIn(keyed_id, by_tenant)
        self.assertNotIn(self.admin_tenant, by_tenant)
        self.assertTrue(by_tenant[bare_id]['ok'])
        self.assertGreaterEqual(body['created'], 1)
        self.assertEqual(body['created'] + body['failed'], len(body['results']))
        with self.app.app_context():
            meta = db.get_tenant_openrouter_key_meta(bare_id)
        self.assertTrue(meta['has_key'])
        self.assertEqual(meta['limit_usd'], 0.0)


if __name__ == '__main__':
    unittest.main()
