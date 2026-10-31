# -*- coding: utf-8 -*-
"""Public presentation share links: token access, optional password, expiry,
revocation, read-only payloads and share-scoped media."""

import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import auth
import db

PNG_1PX = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
    b'+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


class PresentationShareTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'presentation-shares.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        self.previous_uploads = application_module.UPLOADS_DIR
        self.uploads_root = os.path.join(self.temp_dir.name, 'uploads')
        application_module.UPLOADS_DIR = self.uploads_root
        self.context = self.app.app_context()
        self.context.push()
        self.tenant_id = db.create_tenant('شركة المشاركة', 'shares@x.test', 'hash', 'shares-co')
        self.other_tenant_id = db.create_tenant('شركة أخرى', 'shares2@x.test', 'hash', 'shares-co-2')
        self.user_id = db.create_user(
            self.tenant_id, 'مدير الشركة', 'shares-admin@x.test', 'hash', role='employee')
        db.update_tenant(self.tenant_id, primary_user_id=self.user_id)
        db.grant_company_admin_permissions(self.user_id)
        self.token = auth.create_token(
            self.tenant_id, 'shares-admin@x.test', user_id=self.user_id,
            user_name='مدير الشركة', user_role='company_admin')
        self.other_token = auth.create_token(
            self.other_tenant_id, 'shares2@x.test', user_id=None,
            user_name='مدير آخر', user_role='company_admin')
        self.client = self.app.test_client()
        self.creative_dir = os.path.join(self.uploads_root, 'creative', self.tenant_id)
        os.makedirs(self.creative_dir, exist_ok=True)
        self.media_file = os.path.join(self.creative_dir, 'share.png')
        with open(self.media_file, 'wb') as handle:
            handle.write(PNG_1PX)
        self.media_url = '/uploads/creative/%s/share.png' % self.tenant_id
        slides = [{
            'id': 'slide-1',
            'type': 'content',
            'title': 'شريحة',
            'notes': 'ملاحظات المحاضر للشريحة',
            'html': '<div class="slide" style="width:1280px;height:720px">'
                    '<img src="%s"><span>محتوى العرض</span></div>' % self.media_url,
        }]
        self.presentation_id = db.create_presentation(
            self.tenant_id, 'عرض المشاركة', project_data={'project_name': 'سري'},
            slides_data=slides, slide_count=1)

    def tearDown(self):
        self.application_module.UPLOADS_DIR = self.previous_uploads
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def headers(self, token=None):
        return {'Authorization': 'Bearer ' + (token or self.token),
                'Content-Type': 'application/json'}

    def _create_share(self, **payload):
        body = {'expiresIn': '7d'}
        body.update(payload)
        return self.client.post(
            '/api/presentations/%s/shares' % self.presentation_id,
            headers=self.headers(), json=body)

    def _share_token(self, response):
        body = response.get_json()
        self.assertTrue(body.get('success'), body)
        return body['share']['token']

    # ── Creation and public read ─────────────────────────────────────────

    def test_share_reads_slides_without_project_data(self):
        created = self._create_share()
        self.assertEqual(created.status_code, 201, created.get_json())
        share = created.get_json()['share']
        self.assertEqual(share['status'], 'active')
        self.assertFalse(share['hasPassword'])
        self.assertIn('/s/' + share['token'], share['url'])

        public = self.client.get('/api/public/shares/' + share['token'])
        self.assertEqual(public.status_code, 200, public.get_json())
        body = public.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(len(body['slides']), 1)
        self.assertNotIn('projectData', body)
        self.assertNotIn('tenant', body)
        html = body['slides'][0]['html']
        self.assertIn('/s/' + share['token'] + '/media?src=', html)
        self.assertNotIn(self.media_url, html)
        # The owner wants slide notes readable by whoever opens the deck.
        self.assertEqual(body['slides'][0]['notes'], 'ملاحظات المحاضر للشريحة')
        self.assertNotIn('projectData', body['slides'][0])

        viewer = self.client.get('/s/' + share['token'])
        self.assertEqual(viewer.status_code, 200)
        self.assertIn('noindex', viewer.headers.get('X-Robots-Tag', ''))
        # CSP allows script-src 'self' only, so the viewer must not inline its JS.
        page = viewer.get_data(as_text=True)
        self.assertIn('<script src="/s/shared-viewer.js"></script>', page)
        self.assertIn('id="shareNotes"', page)
        self.assertNotIn('<script>', page)
        js = self.client.get('/s/shared-viewer.js')
        self.assertEqual(js.status_code, 200)
        self.assertIn('application/javascript', js.content_type)
        self.assertIn("location.pathname.split('/')[2]", js.get_data(as_text=True))
        self.assertIn('slides[index].notes', js.get_data(as_text=True))

    def test_media_is_scoped_to_the_deck(self):
        token = self._share_token(self._create_share())
        served = self.client.get('/s/%s/media?src=%s' % (token, self.media_url))
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.data, PNG_1PX)
        other = os.path.join(self.creative_dir, 'private.png')
        with open(other, 'wb') as handle:
            handle.write(PNG_1PX)
        refused = self.client.get(
            '/s/%s/media?src=%s' % (token, '/uploads/creative/%s/private.png' % self.tenant_id))
        self.assertEqual(refused.status_code, 404)

    def test_another_tenant_cannot_manage_the_share(self):
        token = self._share_token(self._create_share())
        listing = self.client.get(
            '/api/presentations/%s/shares' % self.presentation_id,
            headers=self.headers(self.other_token))
        self.assertEqual(listing.status_code, 404)
        created = self.client.post(
            '/api/presentations/%s/shares' % self.presentation_id,
            headers=self.headers(self.other_token), json={'expiresIn': '7d'})
        self.assertEqual(created.status_code, 404)
        share_id = self.client.get(
            '/api/presentations/%s/shares' % self.presentation_id,
            headers=self.headers()).get_json()['shares'][0]['id']
        revoked = self.client.post(
            '/api/presentations/%s/shares/%s/revoke' % (self.presentation_id, share_id),
            headers=self.headers(self.other_token))
        self.assertEqual(revoked.status_code, 404)
        still_live = self.client.get('/api/public/shares/' + token)
        self.assertEqual(still_live.status_code, 200)

    # ── Password ─────────────────────────────────────────────────────────

    def test_password_gate_unlocks_the_viewer(self):
        token = self._share_token(self._create_share(password='secret-pass'))
        locked = self.client.get('/api/public/shares/' + token)
        self.assertEqual(locked.status_code, 401)
        self.assertTrue(locked.get_json()['passwordRequired'])

        wrong = self.client.post('/api/public/shares/%s/unlock' % token,
                                 json={'password': 'wrong'})
        self.assertEqual(wrong.status_code, 403)

        unlocked = self.client.post('/api/public/shares/%s/unlock' % token,
                                    json={'password': 'secret-pass'})
        self.assertEqual(unlocked.status_code, 200, unlocked.get_json())
        opened = self.client.get('/api/public/shares/' + token)
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(len(opened.get_json()['slides']), 1)

    # ── Expiry and revocation ────────────────────────────────────────────

    def test_revoked_link_stops_working(self):
        token = self._share_token(self._create_share())
        share_id = self.client.get(
            '/api/presentations/%s/shares' % self.presentation_id,
            headers=self.headers()).get_json()['shares'][0]['id']
        revoked = self.client.post(
            '/api/presentations/%s/shares/%s/revoke' % (self.presentation_id, share_id),
            headers=self.headers())
        self.assertEqual(revoked.status_code, 200, revoked.get_json())
        self.assertEqual(self.client.get('/api/public/shares/' + token).status_code, 404)
        self.assertEqual(self.client.get('/s/' + token).status_code, 404)
        listing = self.client.get(
            '/api/presentations/%s/shares' % self.presentation_id,
            headers=self.headers()).get_json()['shares']
        self.assertEqual(listing[0]['status'], 'revoked')
        self.assertNotIn('password_hash', listing[0])

    def test_expired_link_stops_working(self):
        token = self._share_token(self._create_share(expiresIn='1d'))
        past = (db._utcnow() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        conn = db.get_db()
        conn.execute('UPDATE presentation_shares SET expires_at = ? WHERE token = ?', (past, token))
        conn.commit()
        self.assertEqual(self.client.get('/api/public/shares/' + token).status_code, 404)
        listing = self.client.get(
            '/api/presentations/%s/shares' % self.presentation_id,
            headers=self.headers()).get_json()['shares']
        self.assertEqual(listing[0]['status'], 'expired')

    def test_never_expires_by_default(self):
        created = self._create_share(expiresIn='never')
        self.assertIsNone(created.get_json()['share']['expiresAt'])


if __name__ == '__main__':
    unittest.main()
