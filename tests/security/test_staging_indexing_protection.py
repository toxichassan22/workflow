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
        self.assertIn('https://landloom.ai/llms.txt', body)
        self.assertIn('<changefreq>weekly</changefreq>', body)

    def test_root_favicon_ico_serves_icon_file(self):
        resp = self.client.get('/favicon.ico')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, 'image/x-icon')

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

    def test_brand_logo_and_emblem_geometry(self):
        assets_dir = ROOT / 'assets'
        svg_text = (assets_dir / 'favicon.svg').read_text(encoding='utf-8')
        # Emblem must carry the primary white L and the top-aligned turquoise L (LL twin monogram)
        self.assertIn('fill="#FFFFFF"', svg_text)
        self.assertIn('stroke="#17C8E3"', svg_text)
        self.assertIn('stroke-width="46"', svg_text)
        # Disconnected square dot is replaced
        self.assertNotIn('<rect x="305" y="110"', svg_text)
        # Verify brand logos exist on disk and have valid payload
        for name in ('logo.png', 'landloom-logo.png', 'landloom-logo-white.png', 'favicon-512.png', 'favicon-192.png', 'favicon.ico'):
            p = assets_dir / name
            self.assertTrue(p.exists(), f"{name} must exist")
            self.assertGreater(p.stat().st_size, 500, f"{name} must not be empty")

    def test_all_public_pages_use_unified_favicon_suite(self):
        pages_to_check = [
            ROOT / 'index.html',
            ROOT / 'pages' / 'landing.html',
            ROOT / 'pages' / 'about.html',
            ROOT / 'pages' / 'privacy.html',
            ROOT / 'pages' / 'terms.html',
        ]
        for page_path in pages_to_check:
            self.assertTrue(page_path.exists(), f"File {page_path} must exist")
            with open(page_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertIn('/assets/favicon.svg?v=2', content, f"{page_path.name} must reference new favicon.svg?v=2")
            self.assertIn('/assets/favicon-48.png?v=2', content, f"{page_path.name} must reference favicon-48.png?v=2")
            self.assertNotIn('href="/assets/landloom-logo.png" type="image/png"', content,
                             f"{page_path.name} must not use wide logo as favicon")

    def test_llms_txt_and_full_endpoints(self):
        resp = self.client.get('/llms.txt')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn('# LandLoom', body)
        self.assertIn('Two-Tier Approval Architecture', body)
        self.assertIn('Deterministic Financial Feasibility', body)

        resp_full = self.client.get('/llms-full.txt')
        self.assertEqual(resp_full.status_code, 200)
        body_full = resp_full.get_data(as_text=True)
        self.assertIn('# LandLoom Full System Specification', body_full)
        self.assertIn('Two-Tier Approval Protocol', body_full)

    def test_geo_structured_data_and_discovery_links(self):
        with open(ROOT / 'pages' / 'landing.html', 'r', encoding='utf-8') as f:
            landing_content = f.read()
        self.assertIn('FAQPage', landing_content)
        self.assertIn('Two-Tier Approval System', landing_content)
        self.assertIn('Deterministic Financial Modeling', landing_content)
        self.assertIn('rel="alternate" type="text/plain" href="https://landloom.ai/llms.txt"', landing_content)

        with open(ROOT / 'pages' / 'about.html', 'r', encoding='utf-8') as f:
            about_content = f.read()
        self.assertIn('AboutPage', about_content)
        self.assertIn('rel="alternate" type="text/plain" href="https://landloom.ai/llms.txt"', about_content)

    def test_robots_txt_disallows_leaked_staging_path(self):
        resp = self.client.get('/robots.txt', headers={'Host': 'landloom.ai'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Disallow: /lab.landloom.ai/', resp.get_data(as_text=True))

    def test_leaked_staging_directory_returns_410_gone(self):
        resp = self.client.get('/lab.landloom.ai/', headers={'Host': 'www.landloom.ai'})
        self.assertEqual(resp.status_code, 410)
        self.assertIn('noindex', resp.headers.get('X-Robots-Tag', ''))

        resp_sub = self.client.get('/lab.landloom.ai/about', headers={'Host': 'landloom.ai'})
        self.assertEqual(resp_sub.status_code, 410)
        self.assertIn('noindex', resp_sub.headers.get('X-Robots-Tag', ''))

        resp_env = self.client.get('/', environ_overrides={'REQUEST_URI': '/lab.landloom.ai/'})
        self.assertEqual(resp_env.status_code, 410)

    def test_htaccess_prod_carries_410_protection(self):
        with open(ROOT / '.htaccess_prod', 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('RewriteCond %{HTTP_HOST} ^(www\\.)?landloom\\.ai', content)
        self.assertIn('RewriteRule ^ - [G,L]', content)
