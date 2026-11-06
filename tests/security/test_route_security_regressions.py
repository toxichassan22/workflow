"""Route-level regression guards for the security batch (docs/md/cyber security.md).

DEPLOY-01: the deploy secret travels only in the X-Deploy-Secret header and the
webhooks accept POST only. DIAG-01: /api/build hides per-file fingerprints from
anonymous callers.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db
import app as landloom_app

SECRET = 'test-deploy-secret-0123456789'


class DeployWebhookRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'route_security.db')
        db.init_db()
        self.app = landloom_app.app
        self.app.config['TESTING'] = True
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()
        self.env = mock.patch.dict(os.environ, {'DEPLOY_WEBHOOK_SECRET': SECRET})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_secret_in_query_string_is_not_accepted(self):
        response = self.client.post(f'/api/deploy-webhook?secret={SECRET}')
        self.assertEqual(response.status_code, 401)

    def test_wrong_header_secret_is_refused(self):
        response = self.client.post('/api/deploy-webhook', headers={'X-Deploy-Secret': 'nope'})
        self.assertEqual(response.status_code, 401)

    def test_get_is_not_allowed(self):
        response = self.client.get('/api/deploy-webhook', headers={'X-Deploy-Secret': SECRET})
        self.assertEqual(response.status_code, 405)

    def test_staging_webhook_rejects_query_secret_and_get(self):
        response = self.client.post(f'/api/deploy-webhook-staging?secret={SECRET}')
        self.assertEqual(response.status_code, 401)
        response = self.client.get('/api/deploy-webhook-staging', headers={'X-Deploy-Secret': SECRET})
        self.assertEqual(response.status_code, 405)

    def test_staging_webhook_refuses_wrong_header_secret(self):
        response = self.client.post('/api/deploy-webhook-staging',
                                    headers={'X-Deploy-Secret': 'nope'})
        self.assertEqual(response.status_code, 401)


class BuildDiagnosticsRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'route_diag.db')
        db.init_db()
        self.app = landloom_app.app
        self.app.config['TESTING'] = True
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_anonymous_build_request_has_no_source_fingerprint(self):
        response = self.client.get('/api/build')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('sources', response.get_json())

    def test_forged_bearer_token_gets_no_source_fingerprint(self):
        response = self.client.get('/api/build', headers={'Authorization': 'Bearer forged.token.value'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('sources', response.get_json())


if __name__ == '__main__':
    unittest.main()
