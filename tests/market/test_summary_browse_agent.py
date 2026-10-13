"""BROWSER_AGENT=1 routes the market executive summary to the browse agent.

The summary used to reach the web only through the OpenRouter/Exa layer
(``_call_market_study_model``). With the flag on, one self-hosted browse
agent runs the searches and opens the pages itself; the pages it actually
read arrive as url_citation annotations — the retrieved evidence that makes
``searchVerified`` true. An agent error, or a clean reply that opened zero
pages, is an explicit ``search_not_run`` failure, never a silent paid
fallback and never a memory study.

Run like every other suite::

    python -m unittest tests.market.test_summary_browse_agent
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _p in (str(ROOT), str(_WEB_BROWSE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import db
import agent  # noqa: E402  modules/web_browse/agent.py — patched by name


class SummaryBrowseAgentTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-browse.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def _agent_reply(urls=('https://sakani.sa/reports-and-data/rent-index-q3',)):
        text = json.dumps({
            'summary': {'market_definition': 'قراءة المحور من الصفحات المفتوحة'},
            'decision': 'مجدٍ بشروط',
            'sources': [{'name': 'سكني', 'url': urls[0] if urls else ''}],
        }, ensure_ascii=False)
        return {
            'choices': [{'message': {
                'role': 'assistant',
                'content': text,
                'annotations': [
                    {'url_citation': {'url': url, 'title': 'صفحة', 'content': 'نص'}}
                    for url in urls],
            }}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 7},
            'browse_trace': [
                {'url': url, 'title': 'صفحة', 'chars': 2} for url in urls],
        }

    def test_summary_rides_the_browse_agent_when_flagged(self):
        module = self.application_module
        captured = {}

        def fake_agent(task, usage_ctx=None, **kwargs):
            captured['task'] = task
            captured['kwargs'] = kwargs
            captured['usage_ctx'] = usage_ctx
            return self._agent_reply()

        with patch.dict(os.environ, {'BROWSER_AGENT': '1'}), \
                self.app.app_context(), \
                patch.object(agent, 'run_browse_agent', side_effect=fake_agent), \
                patch.object(module, '_call_market_study_model',
                             side_effect=AssertionError('paid layer must not run')), \
                patch.object(module, '_verify_market_urls', return_value=set()):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id='t1')

        self.assertTrue(result['success'], result)
        self.assertTrue(result['searchVerified'])
        # The consultant brief and the summary brief ride in as one task.
        self.assertIn('المفاتيح الإلزامية لمحاور summary', captured['task'])
        self.assertEqual(captured['kwargs'].get('search_budget'),
                         module._SUMMARY_SEARCH_BUDGET)
        self.assertEqual(captured['kwargs'].get('max_steps'),
                         module._SUMMARY_MAX_STEPS)
        self.assertEqual(captured['kwargs'].get('max_tokens'),
                         module.MARKET_STUDY_MAX_TOKENS)
        self.assertEqual(captured['kwargs'].get('thinking'), 'max')
        self.assertEqual(captured['usage_ctx'].get('tenant_id'), 't1')
        self.assertTrue(result['sources'])

    def test_agent_error_is_explicit_search_not_run(self):
        module = self.application_module
        with patch.dict(os.environ, {'BROWSER_AGENT': '1'}), \
                self.app.app_context(), \
                patch.object(agent, 'run_browse_agent',
                             return_value={'error': {'message': 'browse_agent: launch_failed'}}), \
                patch.object(module, '_call_market_study_model',
                             side_effect=AssertionError('paid layer must not run')):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'search_not_run')
        self.assertIn('launch_failed', result['providerError'])

    def test_clean_reply_with_zero_pages_is_search_not_run(self):
        # An agent that answered from memory — its annotations carry no opened
        # page — must not ship as a market study.
        module = self.application_module
        with patch.dict(os.environ, {'BROWSER_AGENT': '1'}), \
                self.app.app_context(), \
                patch.object(agent, 'run_browse_agent',
                             return_value=self._agent_reply(urls=())), \
                patch.object(module, '_call_market_study_model',
                             side_effect=AssertionError('paid layer must not run')):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'search_not_run')
        self.assertEqual(result['providerError'], 'browse_agent: no browsed evidence')

    def test_flag_off_keeps_the_openrouter_layer(self):
        module = self.application_module
        response = {
            'choices': [{'message': {'content': json.dumps({
                'summary': {'market_definition': 'تحليل'},
                'sources': [{'name': 's', 'url': 'https://sakani.sa/x'}],
            }, ensure_ascii=False)}}],
            'usage': {'server_tool_use': {'web_search_requests': 1}},
        }
        with patch.dict(os.environ, {'BROWSER_AGENT': '0'}), \
                self.app.app_context(), \
                patch.object(agent, 'run_browse_agent',
                             side_effect=AssertionError('agent must not run')), \
                patch.object(module, '_call_market_study_model',
                             return_value=(response, '')), \
                patch.object(module, '_verify_market_urls', return_value=set()):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertTrue(result['success'], result)
        self.assertTrue(result['searchVerified'])


if __name__ == '__main__':
    unittest.main()
