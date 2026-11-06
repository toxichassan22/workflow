"""Regression guards for the security batch (report: docs/md/cyber security.md).

Each check targets one fixed finding and fails on the pre-fix behaviour.
"""
import gzip
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.slides.slide_html_sanitizer import sanitize_slide_html_for_share  # noqa: E402
from modules.web_browse.agent import _url_targets_public_host, _source_url_allowed  # noqa: E402


class ShareSlideSanitizerTests(unittest.TestCase):
    """XSS-01: public share payloads must not carry active content."""

    def test_script_tags_are_removed(self):
        cleaned = sanitize_slide_html_for_share('<p>عنوان</p><script>alert(1)</script>')
        self.assertNotIn('<script', cleaned.lower())
        self.assertNotIn('alert(1)', cleaned)
        self.assertIn('<p>عنوان</p>', cleaned)

    def test_event_handler_attributes_are_removed(self):
        cleaned = sanitize_slide_html_for_share('<img src="x.png" onerror="steal()">')
        self.assertNotIn('onerror', cleaned.lower())
        self.assertIn('x.png', cleaned)

    def test_javascript_urls_are_neutralised(self):
        cleaned = sanitize_slide_html_for_share('<a href="javascript:alert(1)">link</a>')
        self.assertNotIn('javascript:', cleaned.lower())

    def test_frames_and_objects_are_removed(self):
        cleaned = sanitize_slide_html_for_share(
            '<iframe src="https://evil.test"></iframe><object data="x"></object>ok')
        self.assertNotIn('<iframe', cleaned.lower())
        self.assertNotIn('<object', cleaned.lower())
        self.assertIn('ok', cleaned)

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(sanitize_slide_html_for_share(''), '')
        self.assertEqual(sanitize_slide_html_for_share(None), '')


class BrowseSsrfTests(unittest.TestCase):
    """SSRF-01: browse agent must never reach non-public targets."""

    def test_internal_targets_are_rejected(self):
        for url in ('file:///etc/passwd',
                    'http://127.0.0.1/admin',
                    'http://169.254.169.254/latest/meta-data/',
                    'http://localhost:8080/',
                    'http://10.0.0.5/',
                    'http://[::1]/'):
            self.assertFalse(_url_targets_public_host(url), url)

    def test_internal_targets_are_rejected_without_a_host_list(self):
        # The old behaviour allowed any host when allowed_hosts was None.
        self.assertFalse(_source_url_allowed('http://127.0.0.1/', None))
        self.assertFalse(_source_url_allowed('http://169.254.169.254/', None))
        self.assertFalse(_source_url_allowed('file:///etc/passwd', None))

    def test_page_action_refuses_an_internal_current_page(self):
        from modules.web_browse.agent import _run_page_action

        class _Session:
            called = False

            def __getattr__(self, name):
                self.called = True
                raise AssertionError('page action must not reach the browser')

        session = _Session()
        result = _run_page_action(session, 'click_element', {'index': 1}, [], {},
                                  current_url='http://169.254.169.254/latest/')
        self.assertEqual(result.get('error'), 'no_allowed_page_open')
        self.assertFalse(session.called)

    def test_public_host_is_allowed_without_a_host_list(self):
        self.assertTrue(_url_targets_public_host('https://8.8.8.8/'))
        self.assertTrue(_source_url_allowed('https://8.8.8.8/', None))


class BoundedGzipTests(unittest.TestCase):
    """BODY-01: a gzip bomb must not expand past the configured cap."""

    @classmethod
    def setUpClass(cls):
        # app.py is heavy to import; load only the helper from its source.
        import ast
        with open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as handle:
            tree = ast.parse(handle.read())
        func = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == '_bounded_gzip_decompress')
        namespace = {'gzip': gzip, 'MAX_DECOMPRESSED_BODY_BYTES': 25 * 1024 * 1024}
        exec(compile(ast.Module(body=[func], type_ignores=[]), 'app.py', 'exec'), namespace)
        cls.bounded = staticmethod(namespace['_bounded_gzip_decompress'])

    def test_small_payload_round_trips(self):
        raw = gzip.compress(b'hello world')
        self.assertEqual(self.bounded(raw, limit=1024), b'hello world')

    def test_bomb_is_refused_above_the_limit(self):
        raw = gzip.compress(b'\x00' * (5 * 1024 * 1024))
        with self.assertRaises(ValueError):
            self.bounded(raw, limit=1024 * 1024)


if __name__ == '__main__':
    unittest.main()
