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
            'search_ran': True, 'provider_error': 'captcha', 'parsed': {'competitors': []}}))

    def test_fallback_failure_returns_none(self):
        with patch.object(self.module, '_browse_agent_call',
                          return_value={'error': {'message': 'blocked'}}):
            self.assertIsNone(self.module._native_search_fallback(
                'system', 'prompt', {}, None, None))


if __name__ == '__main__':
    unittest.main()
