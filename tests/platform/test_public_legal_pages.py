import re
import unittest
from app import app
import auth
import db


class TestPublicLegalPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        with cls.app.app_context():
            cls.admin_id = db.create_tenant(
                'Legal Admin Company',
                'legal-superadmin@landloom.test',
                auth.hash_password('AdminLegalPass123!'),
                plan='enterprise'
            )
            db.get_db().execute(
                'UPDATE tenants SET is_admin = 1, is_active = 1 WHERE id = ?',
                (cls.admin_id,)
            )
            db.get_db().commit()

            cls.admin_token = auth.create_token(
                cls.admin_id,
                'legal-superadmin@landloom.test',
                is_admin=True,
                user_name='Platform Admin',
                user_role='company_admin'
            )
            cls.admin_headers = {'Authorization': f'Bearer {cls.admin_token}'}

    def test_public_pages_render_and_include_site_legal_css(self):
        pages = ['/about', '/terms', '/privacy']
        for page in pages:
            resp = self.client.get(page)
            self.assertEqual(resp.status_code, 200, f"{page} must return 200")
            html = resp.get_data(as_text=True)
            self.assertIn('/pages/site-legal.css', html, f"{page} must include site-legal.css")
            self.assertIn('legal-page-header', html, f"{page} must include legal-page-header")
            self.assertIn('legal-nav-tabs', html, f"{page} must include legal-nav-tabs")
            self.assertIn('legal-card-shell', html, f"{page} must include legal-card-shell")
            self.assertIn(f'href="{page}"', html, f"{page} must link to itself in tabs")

    def test_public_pages_contain_no_emojis_or_icon_glyphs(self):
        emoji_pattern = re.compile(
            r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\ufe00-\ufe0f]'
        )
        for page in ['/about', '/terms', '/privacy']:
            resp = self.client.get(page)
            html = resp.get_data(as_text=True)
            emojis_found = emoji_pattern.findall(html)
            self.assertEqual(
                emojis_found, [],
                f"Page {page} must contain NO emojis or icon glyphs, but found: {emojis_found}"
            )

    def test_about_page_editable_by_super_admin(self):
        custom_ar = '<h2>رؤيتنا العقارية المحدثة</h2><p>محتوى تعريفي مخصص تم تحديثه بواسطة السوبر أدمن عبر اللوحة.</p>'
        custom_en = '<h2>Our Updated PropTech Vision</h2><p>Custom about content updated by Super Admin via the dashboard.</p>'

        put_resp = self.client.put(
            '/api/admin/legal/about',
            headers=self.admin_headers,
            json={'ar': custom_ar, 'en': custom_en}
        )
        self.assertEqual(put_resp.status_code, 200, put_resp.get_data(as_text=True))
        self.assertTrue(put_resp.get_json().get('success'))

        get_resp = self.client.get('/about')
        self.assertEqual(get_resp.status_code, 200)
        body = get_resp.get_data(as_text=True)
        self.assertIn('رؤيتنا العقارية المحدثة', body)
        self.assertIn('محتوى تعريفي مخصص تم تحديثه بواسطة السوبر أدمن عبر اللوحة', body)
        self.assertIn('Our Updated PropTech Vision', body)
        self.assertIn('Custom about content updated by Super Admin via the dashboard', body)

    def test_terms_and_privacy_editable_by_super_admin(self):
        # Update Terms
        terms_ar = '<h2>شروط محدثة</h2><p>بنود تعاقدية جديدة تم حفظها وتعديلها بنجاح.</p>'
        terms_en = '<h2>Updated Terms</h2><p>New contractual terms saved and updated successfully.</p>'
        put_terms = self.client.put(
            '/api/admin/legal/terms',
            headers=self.admin_headers,
            json={'ar': terms_ar, 'en': terms_en}
        )
        self.assertEqual(put_terms.status_code, 200)
        self.assertTrue(put_terms.get_json().get('success'))
        get_terms = self.client.get('/terms')
        self.assertIn('شروط محدثة', get_terms.get_data(as_text=True))

        # Update Privacy
        privacy_ar = '<h2>سياسة خصوصية محدثة</h2><p>إجراءات أمان وسرية مطورة وفق الأنظمة.</p>'
        privacy_en = '<h2>Updated Privacy Policy</h2><p>Advanced security practices updated.</p>'
        put_privacy = self.client.put(
            '/api/admin/legal/privacy',
            headers=self.admin_headers,
            json={'ar': privacy_ar, 'en': privacy_en}
        )
        self.assertEqual(put_privacy.status_code, 200)
        self.assertTrue(put_privacy.get_json().get('success'))
        get_privacy = self.client.get('/privacy')
        self.assertIn('سياسة خصوصية محدثة', get_privacy.get_data(as_text=True))

    def test_unauthorized_user_cannot_edit_legal_pages(self):
        resp = self.client.put(
            '/api/admin/legal/about',
            json={'ar': 'اختراق', 'en': 'hack'}
        )
        self.assertIn(resp.status_code, [401, 403])

    def test_reject_unknown_document(self):
        resp = self.client.put(
            '/api/admin/legal/invalid_page_name',
            headers=self.admin_headers,
            json={'ar': 'محتوى', 'en': 'content'}
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == '__main__':
    unittest.main()
