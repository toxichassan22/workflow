# -*- coding: utf-8 -*-
"""Slide images upload as durable project files.

The deck editor used to inline uploaded images as base64 data URIs inside the
slide HTML, which bloated every save and export. The replacement stores the file
under the project-files pipeline and publishes a durable URL, so the upload type
must exist and stay image-only.
"""

import base64
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import auth
import db

PNG_1PX = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
    b'+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


class SlideImageUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'slide-image-upload.db')
        db.init_db()
        import app as application_module
        self.application_module = application_module
        self.app = application_module.app
        self.app.config.update(TESTING=True)
        self.context = self.app.app_context()
        self.context.push()
        self.tenant_id = db.create_tenant('شركة الصور', 'slide-img@x.test', 'hash', 'slide-img-co')
        self.user_id = db.create_user(
            self.tenant_id, 'مدير الشركة', 'slide-img-admin@x.test', 'hash', role='employee')
        db.update_tenant(self.tenant_id, primary_user_id=self.user_id)
        db.grant_company_admin_permissions(self.user_id)
        self.token = auth.create_token(
            self.tenant_id, 'slide-img-admin@x.test', user_id=self.user_id,
            user_name='مدير الشركة', user_role='company_admin')
        self.client = self.app.test_client()

    def tearDown(self):
        db.close_db()
        self.context.pop()
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def _upload(self, name, content, file_type='slide_image'):
        return self.client.post(
            '/api/project-files',
            headers={'Authorization': 'Bearer ' + self.token},
            data={'file': (io.BytesIO(content), name), 'fileType': file_type},
            content_type='multipart/form-data')

    def test_slide_image_accepts_a_real_image(self):
        upload = self._upload('photo.png', PNG_1PX)
        self.assertEqual(upload.status_code, 201, upload.get_json())
        body = upload.get_json()
        self.assertEqual(body['file']['fileType'], 'slide_image')
        self.assertEqual(body['file']['originalName'], 'photo.png')

    def test_slide_image_refuses_a_pdf(self):
        upload = self._upload('document.pdf', b'%PDF-1.4 fake')
        self.assertEqual(upload.status_code, 400, upload.get_json())
        self.assertIn('صور فقط', upload.get_json()['error'])

    def test_slide_image_is_a_known_project_type(self):
        self.assertIn('slide_image', self.application_module.PROJECT_FILE_TYPES)
        self.assertIn('slide_image', self.application_module.PROJECT_IMAGE_ONLY_TYPES)


if __name__ == '__main__':
    unittest.main()
