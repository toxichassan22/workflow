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
            existing = db.get_tenant_by_email('legal-superadmin@landloom.test')
            if existing:
                cls.admin_id = existing['id']
            else:
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

    def test_admin_get_legal_endpoint(self):
        for doc in ['about', 'terms', 'privacy']:
            resp = self.client.get(f'/api/admin/legal/{doc}', headers=self.admin_headers)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get('success'))
            document = data.get('document', {})
            self.assertIn('ar', document)
            self.assertIn('en', document)
            self.assertIn('date_ar', document)
            self.assertIn('date_en', document)
            self.assertIn('notice_ar', document)
            self.assertIn('notice_en', document)
            self.assertTrue(len(document['date_ar']) > 0, f"Default date_ar for {doc} must not be empty")

    def test_about_page_editable_dates_notices_and_content(self):
        custom_ar = '<h2>رؤيتنا العقارية المحدثة</h2><p>محتوى تعريفي مخصص تم تحديثه بواسطة السوبر أدمن عبر اللوحة.</p>'
        custom_en = '<h2>Our Updated PropTech Vision</h2><p>Custom about content updated by Super Admin via the dashboard.</p>'
        custom_date_ar = 'تحديث: نوفمبر 2026'
        custom_date_en = 'Updated: November 2026'
        custom_notice_ar = 'تنبيه حصري: نص معتمد للإصدار الرسمي'
        custom_notice_en = 'Notice: Official release approved text'

        put_resp = self.client.put(
            '/api/admin/legal/about',
            headers=self.admin_headers,
            json={
                'ar': custom_ar,
                'en': custom_en,
                'date_ar': custom_date_ar,
                'date_en': custom_date_en,
                'notice_ar': custom_notice_ar,
                'notice_en': custom_notice_en,
            }
        )
        self.assertEqual(put_resp.status_code, 200, put_resp.get_data(as_text=True))
        self.assertTrue(put_resp.get_json().get('success'))

        get_resp = self.client.get('/about')
        self.assertEqual(get_resp.status_code, 200)
        body = get_resp.get_data(as_text=True)
        self.assertIn('رؤيتنا العقارية المحدثة', body)
        self.assertIn('Our Updated PropTech Vision', body)
        self.assertIn(custom_date_ar, body)
        self.assertIn(custom_date_en, body)
        self.assertIn(custom_notice_ar, body)
        self.assertIn(custom_notice_en, body)

    def test_terms_and_privacy_editable_dates_notices_and_content(self):
        # Update Terms with custom dates and notices
        terms_ar = '<h2>شروط محدثة</h2><p>بنود تعاقدية جديدة تم حفظها وتعديلها بنجاح.</p>'
        terms_en = '<h2>Updated Terms</h2><p>New contractual terms saved and updated successfully.</p>'
        terms_date_ar = 'تحديث: 04/Nov/2026'
        terms_date_en = 'Updated: 04/Nov/2026'
        terms_notice_ar = 'تنبيه الشروط: النسخة الرسمية رقم 2'
        terms_notice_en = 'Notice: Official version 2'

        put_terms = self.client.put(
            '/api/admin/legal/terms',
            headers=self.admin_headers,
            json={
                'ar': terms_ar,
                'en': terms_en,
                'date_ar': terms_date_ar,
                'date_en': terms_date_en,
                'notice_ar': terms_notice_ar,
                'notice_en': terms_notice_en,
            }
        )
        self.assertEqual(put_terms.status_code, 200)
        self.assertTrue(put_terms.get_json().get('success'))

        get_terms = self.client.get('/terms')
        terms_body = get_terms.get_data(as_text=True)
        self.assertIn('شروط محدثة', terms_body)
        self.assertIn(terms_date_ar, terms_body)
        self.assertIn(terms_date_en, terms_body)
        self.assertIn(terms_notice_ar, terms_body)
        self.assertIn(terms_notice_en, terms_body)

        # Update Privacy with custom dates and notices
        privacy_ar = '<h2>سياسة خصوصية محدثة</h2><p>إجراءات أمان وسرية مطورة وفق الأنظمة.</p>'
        privacy_en = '<h2>Updated Privacy Policy</h2><p>Advanced security practices updated.</p>'
        privacy_date_ar = 'تحديث: ديسمبر 2026'
        privacy_date_en = 'Updated: Dec 2026'
        privacy_notice_ar = 'تنبيه الخصوصية: سارية المفعول فورًا'
        privacy_notice_en = 'Privacy notice: effective immediately'

        put_privacy = self.client.put(
            '/api/admin/legal/privacy',
            headers=self.admin_headers,
            json={
                'ar': privacy_ar,
                'en': privacy_en,
                'date_ar': privacy_date_ar,
                'date_en': privacy_date_en,
                'notice_ar': privacy_notice_ar,
                'notice_en': privacy_notice_en,
            }
        )
        self.assertEqual(put_privacy.status_code, 200)
        self.assertTrue(put_privacy.get_json().get('success'))

        get_privacy = self.client.get('/privacy')
        privacy_body = get_privacy.get_data(as_text=True)
        self.assertIn('سياسة خصوصية محدثة', privacy_body)
        self.assertIn(privacy_date_ar, privacy_body)
        self.assertIn(privacy_date_en, privacy_body)
        self.assertIn(privacy_notice_ar, privacy_body)
        self.assertIn(privacy_notice_en, privacy_body)

    def test_clearing_notice_removes_it_from_rendered_page(self):
        # Admin clears notice (empty string)
        put_resp = self.client.put(
            '/api/admin/legal/about',
            headers=self.admin_headers,
            json={
                'ar': '<h1>من نحن</h1><p>محتوى بدون أي تنبيه تجريبي.</p>',
                'en': '<h1>About Us</h1><p>Content without any draft notice.</p>',
                'notice_ar': '',
                'notice_en': '',
            }
        )
        self.assertEqual(put_resp.status_code, 200)
        get_resp = self.client.get('/about')
        body = get_resp.get_data(as_text=True)
        self.assertNotIn('نص مبدئي قابل للتحديث', body)
        self.assertNotIn('Draft text subject to update', body)
        self.assertNotIn('تنبيه حصري', body)

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
