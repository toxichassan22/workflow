"""The gzip request hook refuses bodies that expand past the decompressed cap."""

import gzip
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db
import app as landloom_app


class GzipBodyCapTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'gzip_cap.db')
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

    def test_gzip_bomb_past_the_cap_is_refused_with_413(self):
        # 26 MB of zeros gzips to roughly 26 KB: a small body that would
        # expand past MAX_DECOMPRESSED_BODY_BYTES (25 MB).
        expanded = landloom_app.MAX_DECOMPRESSED_BODY_BYTES + 1024 * 1024
        bomb = gzip.compress(b'\x00' * expanded)
        self.assertLess(len(bomb), 64 * 1024)
        response = self.client.post(
            '/api/analyze-site', data=bomb,
            headers={'Content-Encoding': 'gzip',
                     'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 413)

    def test_normal_gzipped_json_body_is_not_refused_by_the_cap(self):
        payload = json.dumps({'probe': 'x' * 2048}).encode('utf-8')
        response = self.client.post(
            '/api/analyze-site', data=gzip.compress(payload),
            headers={'Content-Encoding': 'gzip',
                     'Content-Type': 'application/json'})
        self.assertNotEqual(response.status_code, 413)


if __name__ == '__main__':
    unittest.main()
