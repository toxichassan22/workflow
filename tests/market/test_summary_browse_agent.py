"""The market executive summary researches through provider-native Google
search (an OpenRouter server tool, owner-ordered) with zero local page
opens — the model's own grounding plus its url_citation annotations are the
retrieved evidence that makes ``searchVerified`` true. A transport error, or
a clean reply with neither citations nor grounding proof, is an explicit
``search_not_run`` failure — never a memory study.

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

    def setUp(self):
        # The summary executor now runs the retrieval planner into the job's
        # evidence pool before the browse call — stub the seam so this suite
        # never fetches real pages whether or not that layer has landed.
        stub = patch.object(
            self.application_module, '_run_market_source_plan', return_value=None)
        stub.start()
        self.addCleanup(stub.stop)

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

    @staticmethod
    def _grounded_reply():
        """A native-search synthesis with zero opened pages: grounding proof
        on the message, no url_citation annotations at all."""
        text = json.dumps({
            'summary': {'market_definition': 'قراءة المحور من البحث الأصلي'},
            'decision': 'مجدٍ بشروط',
            'sources': [{'name': 'بحث جوجل الأصلي', 'url': ''}],
        }, ensure_ascii=False)
        return {
            'choices': [{'message': {
                'role': 'assistant',
                'content': text,
                'annotations': [],
                'groundingMetadata': {
                    'webSearchQueries': ['صفقات البيع جدة 2026'],
                },
            }}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 7},
            'browse_trace': [],
        }

    def test_summary_rides_native_server_search(self):
        """Owner-ordered: the summary researches through provider-native
        Google search (an OpenRouter server tool) with zero local page
        opens — the self-hosted Chromium agent stays the competitors and
        row-verification path only."""
        module = self.application_module
        captured = {}

        def fake_agent(task, usage_ctx=None, **kwargs):
            captured['task'] = task
            captured['kwargs'] = kwargs
            captured['usage_ctx'] = usage_ctx
            return self._agent_reply()

        with self.app.app_context(), \
                patch.object(agent, 'run_browse_agent', side_effect=fake_agent), \
                patch.object(module, '_verify_market_urls', return_value=set()):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id='t1')

        self.assertTrue(result['success'], result)
        self.assertTrue(result['searchVerified'])
        # The consultant brief and the summary brief ride in as one task.
        self.assertIn('المفاتيح الإلزامية لمحاور summary', captured['task'])
        server_tools = captured['kwargs'].get('server_tools')
        self.assertEqual(server_tools,
                         [{"type": "openrouter:web_search", "engine": "native"}])
        self.assertIs(captured['kwargs'].get('local_tools'), False)
        # The search is forced, not model-optional: tool_choice names the
        # server tool, so a memory answer without any search cannot happen.
        self.assertEqual(captured['kwargs'].get('tool_choice'),
                         {"type": "openrouter:web_search"})
        # No local search budget is consumed on the native path.
        self.assertNotIn('search_budget', captured['kwargs'])
        self.assertEqual(captured['kwargs'].get('max_tokens'),
                         module.MARKET_STUDY_MAX_TOKENS)
        # The agent mostly searches and opens pages — low effort keeps the
        # output budget for the answer itself instead of burning it on
        # reasoning tokens (the MAX_TOKENS failures).
        self.assertEqual(captured['kwargs'].get('reasoning_effort'), 'low')
        # The task's own model drives the loop — not a separate agent model.
        self.assertEqual(captured['kwargs'].get('model'),
                         module.MARKET_STUDY_MODEL)
        self.assertEqual(captured['usage_ctx'].get('tenant_id'), 't1')
        self.assertTrue(result['sources'])

    def test_grounding_proof_without_opened_pages_is_accepted(self):
        """AI-overview reliance: a grounded synthesis with zero opened pages
        (groundingMetadata proof, no annotations) still ships as a study —
        only a proof-less memory answer stays search_not_run."""
        module = self.application_module
        with self.app.app_context(), \
                patch.object(agent, 'run_browse_agent',
                             return_value=self._grounded_reply()), \
                patch.object(module, '_verify_market_urls', return_value=set()):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertTrue(result['success'], result)
        self.assertTrue(result['searchVerified'])

    def test_agent_error_is_explicit_search_not_run(self):
        module = self.application_module
        with self.app.app_context(), \
                patch.object(agent, 'run_browse_agent',
                             return_value={'error': {'message': 'browse_agent: launch_failed'}}):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'search_not_run')
        self.assertIn('launch_failed', result['providerError'])

    def test_clean_reply_with_zero_pages_is_search_not_run(self):
        # An agent that answered from memory — its annotations carry no opened
        # page — must not ship as a market study.
        module = self.application_module
        with self.app.app_context(), \
                patch.object(agent, 'run_browse_agent',
                             return_value=self._agent_reply(urls=())):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'search_not_run')
        self.assertEqual(result['providerError'], 'browse_agent: no browsed evidence')

    def test_fatal_refusal_reports_credit_not_search_not_run(self):
        """A wallet/key refusal stays a credit failure — the job must surface
        the deterministic refusal, not a generic search miss."""
        module = self.application_module
        fatal = {'error': {'fatal': True, 'message': 'استُنفد الرصيد',
                           'error_code': 'INSUFFICIENT_CREDITS',
                           'http_status': 402}}
        with self.app.app_context(), \
                patch.object(agent, 'run_browse_agent', return_value=dict(fatal)):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'insufficient_credit')

    def test_legacy_search_layer_is_gone(self):
        """Regression guard: the paid OpenRouter/Exa layer was deleted — the
        deprecated `web` plugin must never come back. The single sanctioned
        server-search usage is the summary's native tool
        (`_SUMMARY_NATIVE_SEARCH_TOOLS`); anything else is the old layer."""
        module = self.application_module
        self.assertFalse(hasattr(module, '_call_market_study_model'))
        self.assertFalse(hasattr(module, 'MARKET_SEARCH_ENGINE'))
        self.assertTrue(hasattr(module, '_SUMMARY_NATIVE_SEARCH_TOOLS'))

    def test_summary_prompt_carries_mandatory_search_protocol(self):
        """The summary failed as search_not_run with queries=0: the model
        answered from memory because its prompt — unlike the competitors
        prompt — carried no mandatory search protocol. The prompt must order
        per-axis native Google searches and source-table citations, and must
        not name local browser tools that do not exist on this path."""
        import market_study as market_study_module
        payload = {'city': 'جدة', 'district': 'الياسمين',
                   'projectType': 'سكني'}
        prompt = market_study_module.build_summary_user_prompt(
            payload, [], offer_lang='ar')
        self.assertIn('بروتوكول البحث الإلزامي', prompt)
        self.assertIn('بحث جوجل الأصلي', prompt)
        self.assertNotIn('open_url', prompt)
        prompt_en = market_study_module.build_summary_user_prompt(
            payload, [], offer_lang='en')
        self.assertIn('Mandatory search protocol', prompt_en)
        self.assertIn('native Google search', prompt_en)
        self.assertNotIn('open_url', prompt_en)


if __name__ == '__main__':
    unittest.main()
