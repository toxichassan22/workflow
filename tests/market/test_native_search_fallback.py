"""Provider-native search is a fallback for a blocked local search layer."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db


class NativeSearchFallbackTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'native-fallback.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _response(self):
        return {
            'choices': [{'message': {
                'content': json.dumps({'competitors': [{
                    'name': 'منافس من البحث البديل',
                    'project_type': 'سكني',
                    'operation_type': 'بيع',
                }]}, ensure_ascii=False),
                'annotations': [{'url_citation': {
                    'url': 'https://sa.aqar.fm/x',
                    'title': 'إعلان',
                    'content': 'منافس من البحث البديل',
                }}],
            }}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
        }

    def test_fallback_runs_native_search_without_local_tools(self):
        captured = {}

        def fake_call(system_prompt, prompt, usage_ctx=None, **kwargs):
            captured.update(kwargs)
            return self._response()

        with patch.object(self.module, '_browse_agent_call',
                          side_effect=fake_call):
            result = self.module._native_search_fallback(
                'system', 'prompt', {}, None, None,
                search_budget=3, max_steps=6)

        self.assertFalse(captured.get('local_tools'))
        self.assertEqual(captured.get('plugins'),
                         [{'id': 'web', 'max_results': 5}])
        self.assertNotIn('model', captured)
        self.assertEqual(result['parsed']['competitors'][0]['name'],
                         'منافس من البحث البديل')
        self.assertTrue(result['search_ran'])

    def test_fallback_is_only_for_a_search_that_never_ran(self):
        module = self.module
        self.assertTrue(module._native_fallback_needed({}))
        self.assertTrue(module._native_fallback_needed({
            'search_ran': False, 'parsed': {'competitors': []}}))
        self.assertFalse(module._native_fallback_needed({
            'search_ran': True, 'parsed': {'competitors': []}}))
        self.assertFalse(module._native_fallback_needed({
            'search_ran': True, 'parsed': {'competitors': [{'name': 'x'}]}}))
        self.assertTrue(module._native_fallback_needed({
            'search_ran': True, 'search_blocked': True, 'parsed': {'competitors': []}}))
        self.assertTrue(module._native_fallback_needed({
            'search_ran': True, 'pages_blocked': True, 'parsed': {'competitors': []}}))
        self.assertTrue(module._native_fallback_needed({
            'search_ran': True, 'provider_error': 'captcha', 'parsed': {'competitors': []}}))

    def test_fallback_failure_returns_none(self):
        with patch.object(self.module, '_browse_agent_call',
                          return_value={'error': {'message': 'blocked'}}):
            self.assertIsNone(self.module._native_search_fallback(
                'system', 'prompt', {}, None, None))

    def test_sanitize_search_query_strips_conversational_prefixes(self):
        import browser
        sanitizer = getattr(browser, 'sanitize_search_query', None)
        self.assertTrue(callable(sanitizer))
        cases = [
            ('التحقق من وجود مشاريع فلل للبيع مسماة في حي الأندلس بجدة',
             'مشاريع فلل للبيع في حي الأندلس بجدة'),
            ('حصر مشاريع الفلل السكنية المسماة للبيع داخل حي الحمراء في جدة',
             'الفلل السكنية للبيع حي الحمراء في جدة'),
            ('البحث عن مجمع تجاري حي الخالدية جدة',
             'مجمع تجاري حي الخالدية جدة'),
            ('مشروع فلل الروضة جدة',
             'مشروع فلل الروضة جدة'),
        ]
        for raw, expected in cases:
            self.assertEqual(sanitizer(raw), expected)

    def test_run_single_competitor_scan_triggers_fallback_when_axis_competitors_sparse(self):
        task = {'kind': 'axis', 'label': 'فلل للبيع', 'axis': {'key': 'villas'}}
        fake_response = {
            'choices': [{'message': {
                'content': json.dumps({'competitors': []}, ensure_ascii=False),
            }}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
        }
        fallback_res = {
            'task': None,
            'reply': self._response(),
            'parsed': {'competitors': [{'name': 'مشروع فلل الروضة الموثق'}]},
            'parse_error': '',
            'provider_error': '',
            'search_ran': True,
        }
        with patch.object(self.module, '_browse_agent_call', return_value=fake_response), \
             patch.object(self.module, '_market_browser_session', return_value=None), \
             patch.object(self.module, '_native_search_fallback', return_value=fallback_res) as mock_fallback:
            result = self.module._run_single_competitor_scan(
                task, {'city': 'جدة'}, [], 'generate', 'ar', None, {}, None, None,
                'system', None, (0, 10), 3, 5)

        self.assertTrue(mock_fallback.called)
        self.assertEqual(len(result['parsed']['competitors']), 1)
        self.assertEqual(result['parsed']['competitors'][0]['name'], 'مشروع فلل الروضة الموثق')

    def test_dead_url_shape_blocks_nft_and_crypto(self):
        import agent
        dead_fn = getattr(agent, '_dead_url_shape', None)
        self.assertTrue(callable(dead_fn))
        self.assertEqual(
            dead_fn('https://blog.esprezzo.io/11-of-the-most-interesting-membership-nfts-in-2023'),
            'dead_source')
        self.assertEqual(
            dead_fn('https://nftnow.com/features/nft-tickets-are-the-future-of-live-music/'),
            'dead_source')
        self.assertEqual(
            dead_fn('https://walmart.com/stores'),
            'dead_source')


if __name__ == '__main__':
    unittest.main()
