"""The SPA shell must stay a loader over ordered index_parts/ files.

index.html carries the document chrome and one placeholder; the body markup
lives in index_parts/*.html, spliced in by 22f_frontend_bundles.py in
INDEX_PARTS_ORDER. These guards prove the order authority matches the disk,
every part stays under the size limit and is balanced markup, and the served
/app shell really contains every part.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

from tests.frontend_source import PARTS_DIR, SHELL_PATH, parts_order, shell_text

ROOT = Path(__file__).resolve().parents[2]
MARKER = '<!--__INDEX_PARTS__-->'
PART_MARKER_RE = re.compile(r'(?m)^<!--__PART:[^>]+-->\n')
BUNDLE_VERSION_RE = re.compile(
    r'(/assets/(?:app\.bundle\.js|app\.bundle\.css|i18n\.bundle\.js))\?v=[0-9a-f]+')


class ShellPartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        import db
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'shell-parts.db')
        import app as application_module
        cls.application_module = application_module

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_index_html_is_a_loader_with_one_placeholder(self):
        skeleton = SHELL_PATH.read_text(encoding='utf-8')
        self.assertEqual(skeleton.count(MARKER), 1)
        self.assertLessEqual(len(skeleton.splitlines()), 1000)

    def test_parts_order_matches_disk_exactly(self):
        order = parts_order()
        self.assertTrue(order, 'INDEX_PARTS_ORDER must not be empty')
        self.assertEqual(len(order), len(set(order)), 'INDEX_PARTS_ORDER lists a part twice')
        on_disk = sorted(path.name for path in PARTS_DIR.glob('*.html'))
        self.assertEqual(sorted(order), on_disk, 'order and disk must name the same parts')
        self.assertEqual(list(order), on_disk, 'part names must sort into load order')

    def test_every_part_stays_under_the_line_limit(self):
        for path in sorted(PARTS_DIR.glob('*.html')):
            with self.subTest(part=path.name):
                self.assertLessEqual(len(path.read_text(encoding='utf-8').splitlines()), 1000)

    def test_parts_are_balanced_markup_without_inline_code(self):
        for name in parts_order():
            text = (PARTS_DIR / name).read_text(encoding='utf-8')
            with self.subTest(part=name):
                self.assertEqual(len(re.findall(r'<div(?=[\s>])', text)),
                                 len(re.findall(r'</div>', text)))
                self.assertEqual(len(re.findall(r'<section(?=[\s>])', text)),
                                 len(re.findall(r'</section>', text)))
                self.assertNotRegex(text, r'<style[\s>]')
                self.assertNotRegex(text, r'(?m)^\s*<script>\s*$')

    def test_served_app_shell_is_the_assembled_shell(self):
        with self.application_module.app.test_client() as client:
            response = client.get('/app')
        self.assertEqual(response.status_code, 200)
        served = response.get_data(as_text=True)
        self.assertNotIn(MARKER, served)
        served = PART_MARKER_RE.sub('', served)
        served = BUNDLE_VERSION_RE.sub(r'\1', served)
        self.assertEqual(served, shell_text())

    def test_every_part_reaches_the_served_shell(self):
        with self.application_module.app.test_client() as client:
            served = client.get('/app').get_data(as_text=True)
        for name in parts_order():
            part = (PARTS_DIR / name).read_text(encoding='utf-8')
            first_line = next(line for line in part.splitlines() if line.strip())
            with self.subTest(part=name):
                self.assertIn(first_line, served)


if __name__ == '__main__':
    unittest.main()
