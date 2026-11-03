"""Tests for staging de-indexing protection, robots.txt, sitemap.xml, and site verification."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tests.conftest  # noqa: F401

import db
import app as landloom_app


class StagingIndexingProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, 'indexing_test.db')
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

    def test_staging_host_receives_noindex_header(self):
        resp = self.client.get('/', headers={'Host': 'lab.landloom.ai'})
        self.assertEqual(resp.status_code, 200)
        robots_tag = resp.headers.get('X-Robots-Tag', '')
        self.assertIn('noindex', robots_tag)
        self.assertIn('nofollow', robots_tag)
        self.assertIn('noarchive', robots_tag)

    def test_production_landing_does_not_force_noindex(self):
        resp = self.client.get('/', headers={'Host': 'landloom.ai'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('noindex', resp.headers.get('X-Robots-Tag', ''))

    def test_internal_app_shell_receives_noindex_on_all_domains(self):
        resp = self.client.get('/app', headers={'Host': 'landloom.ai'})
        self.assertEqual(resp.status_code, 200)
        robots_tag = resp.headers.get('X-Robots-Tag', '')
        self.assertIn('noindex', robots_tag)

    def test_robots_txt_staging(self):
        resp = self.client.get('/robots.txt', headers={'Host': 'lab.landloom.ai'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('User-agent: *', resp.get_data(as_text=True))
        self.assertIn('noindex', resp.headers.get('X-Robots-Tag', ''))

    def test_sitemap_xml_endpoint(self):
        resp = self.client.get('/sitemap.xml', headers={'Host': 'landloom.ai'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, 'application/xml')
        body = resp.get_data(as_text=True)
        self.assertIn('https://landloom.ai/', body)
        self.assertIn('<changefreq>weekly</changefreq>', body)

    def test_google_verification_file_endpoint(self):
        resp = self.client.get('/google3567ac5386460d70.html')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertEqual(body, 'google-site-verification: google3567ac5386460d70.html')

        bad_resp = self.client.get('/googleinvalid_token_too_short.html')
        self.assertEqual(bad_resp.status_code, 404)

    def test_html_files_carry_verification_and_meta_tags(self):
        with open(ROOT / 'index.html', 'r', encoding='utf-8') as f:
            index_content = f.read()
        self.assertIn('name="robots" content="noindex, nofollow, noarchive"', index_content)
        self.assertIn('name="google-site-verification"', index_content)
        self.assertIn('href="/assets/favicon.svg?v=2"', index_content)

        with open(ROOT / 'pages' / 'landing.html', 'r', encoding='utf-8') as f:
            landing_content = f.read()
        self.assertIn('name="google-site-verification"', landing_content)
        self.assertIn('href="/assets/favicon-48.png?v=2"', landing_content)
        self.assertIn('property="og:image"', landing_content)
        self.assertIn('SoftwareApplication', landing_content)

    def test_favicon_assets_exist_on_disk(self):
        assets_dir = ROOT / 'assets'
        self.assertTrue((assets_dir / 'favicon.svg').exists())
        self.assertTrue((assets_dir / 'favicon-48.png').exists())
        self.assertTrue((assets_dir / 'favicon-32.png').exists())
        self.assertTrue((assets_dir / 'favicon-16.png').exists())
        self.assertTrue((assets_dir / 'apple-touch-icon.png').exists())
        self.assertTrue((assets_dir / 'site.webmanifest').exists())
        self.assertTrue((assets_dir / 'og-image.png').exists())
