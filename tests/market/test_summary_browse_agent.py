"""Parallel source researchers and evidence aggregation for market summaries."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / 'modules' / 'web_browse')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import db
import market_study


class SummaryBrowseAgentTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-browse.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def _opened_reply(url='https://rega.gov.sa/city-data'):
        return {'choices': [{'message': {
            'content': '{}',
            'annotations': [{'url_citation': {
                'url': url, 'title': 'صفحة بيانات', 'content': 'دليل'} }],
        }}]}

    def test_individual_researcher_uses_argon_playwright_and_only_searxng(self):
        module = self.module
        captured = {}

        def fake_browse(system, prompt, usage_ctx, **kwargs):
            captured.update({'system': system, 'prompt': prompt,
                             'usage_ctx': usage_ctx, **kwargs})
            return self._opened_reply()

        group = next(item for item in module._SUMMARY_RESEARCH_GROUPS
                     if item['key'] == 'transactions_and_rents')
        with patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_new_evidence_pool', return_value=None):
            outcome = module._run_summary_researcher(
                group, ['rei.rega.gov.sa'], {'city': 'جدة'}, 'جدة', 'الروضة',
                {'tenant_id': 't1'}, time.time() + 30)

        self.assertTrue(outcome['searched'])
        self.assertEqual(captured['model'], module.GEMINI_TEXT_MODEL)
        self.assertTrue(captured['local_tools'])
        self.assertEqual(captured['search_provider'], 'searxng')
        self.assertEqual(captured['max_steps'], 24)
        self.assertEqual(captured['search_budget'], 8)
        self.assertEqual(captured['max_tokens'], 8000)
        self.assertEqual(captured['usage_ctx']['tenant_id'], 't1')
        self.assertIn('site:rei.rega.gov.sa', captured['prompt'])
        self.assertIn('https://rei.rega.gov.sa/ar/advanced-search/deals', captured['prompt'])
        self.assertIn('فتح الموقع أو الرابط وحده لا يُعد بحثًا مكتملًا', captured['prompt'])
        self.assertIn('افحص كل التبويبات والجداول', captured['prompt'])
        self.assertIn('تستنفد البيانات المتاحة للنطاق', captured['prompt'])
        self.assertIn('الروضة', captured['prompt'])
        self.assertNotIn('server_tools', captured)

    def test_research_tasks_cover_each_source_and_scope_in_parallel(self):
        module = self.module
        first = module._SUMMARY_RESEARCH_GROUPS[0]
        second = module._SUMMARY_RESEARCH_GROUPS[2]
        source_map = {item['key']: [] for item in module._SUMMARY_RESEARCH_GROUPS}
        source_map[first['key']] = ['rega.gov.sa', 'rei.rega.gov.sa']
        source_map[second['key']] = ['mt.gov.sa']
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = 0
        maximum_active = 0
        captured = []

        def fake_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar'):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            barrier.wait(timeout=3)
            time.sleep(0.02)
            with lock:
                active -= 1
                captured.append((hosts[0], city, district))
            return {'key': group['key'], 'label': group['label'],
                    'city': city, 'district': district, 'hosts': hosts,
                    'result': self._opened_reply('https://' + hosts[0] + '/data'),
                    'parsed': {}, 'parse_error': '', 'pages': [], 'searched': True}

        payload = {'city': 'جدة', 'summaryScope': {'cities': [
            {'name': 'جدة', 'districts': ['الروضة']}]}}
        with patch.object(module, '_summary_research_sources_by_group',
                          return_value=source_map), \
                patch.object(module, '_run_summary_researcher',
                             side_effect=fake_researcher):
            research = module._run_market_summary_research(
                payload, {}, None, time.time() + 30)

        self.assertTrue(research['success'])
        self.assertEqual(len(captured), 6)
        self.assertGreaterEqual(maximum_active, 2)
        self.assertEqual({row[0] for row in captured},
                         {'rega.gov.sa', 'rei.rega.gov.sa', 'mt.gov.sa'})
        self.assertEqual({row[2] for row in captured}, {'', 'الروضة'})
        self.assertTrue(all(item.get('source_hosts') for item in research['reports']))
        self.assertTrue(all(item['coverage_status'] == 'partial'
                            for item in research['reports']))
        self.assertTrue(all(item.get('coverage_gap') for item in research['reports']))
        self.assertEqual(module._SUMMARY_RESEARCH_MAX_WORKERS, 100)

    def test_aggregator_calls_argon_and_preserves_only_received_citations(self):
        module = self.module
        response = {'choices': [{'message': {'content': '{}', 'annotations': []}}]}
        captured = {}

        def fake_chat(system, prompt, **kwargs):
            captured.update({'system': system, 'prompt': prompt, **kwargs})
            return response

        research = {'citation_urls': ['https://rega.gov.sa/city-data']}
        with patch.object(module, 'call_text_chat', side_effect=fake_chat):
            result = module._run_market_summary_aggregator(
                'system', 'evidence prompt', {'tenant_id': 't1'}, research,
                deadline=time.time() + 30)

        self.assertIs(result, response)
        self.assertEqual(captured['model'], module.GEMINI_TEXT_MODEL)
        self.assertEqual(captured['reasoning_effort'], 'medium')
        self.assertEqual(captured['usage_ctx']['tenant_id'], 't1')
        annotations = result['choices'][0]['message']['annotations']
        self.assertEqual(annotations[0]['url_citation']['url'],
                         'https://rega.gov.sa/city-data')
        self.assertTrue(result['browse_trace'])

    def test_fatal_research_error_is_reported_as_credit_failure(self):
        module = self.module
        fatal = {'error': {'fatal': True, 'message': 'رصيد غير كافٍ',
                           'error_code': 'INSUFFICIENT_CREDITS', 'http_status': 402}}
        research = {'success': False, 'error': 'no pages',
                    'outcomes': [{'result': fatal}]}
        with self.app.app_context(), \
                patch.object(module, '_run_market_summary_research', return_value=research):
            result = module._run_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'insufficient_credit')
        self.assertEqual(result['providerError'], 'رصيد غير كافٍ')

    def test_summary_prompt_assigns_research_to_playwright_workers(self):
        prompt = market_study.build_summary_user_prompt(
            {'city': 'جدة', 'summaryScope': {'cities': [
                {'name': 'جدة', 'districts': ['الروضة']}]}}, [], offer_lang='ar')
        self.assertIn('Playwright', prompt)
        self.assertIn('SearXNG', prompt)
        self.assertIn('أنت موديل تجميع الأدلة', prompt)
        self.assertIn('الروضة', prompt)
        self.assertNotIn('بحث جوجل الأصلي', prompt)
        self.assertNotIn('openrouter:web_search', prompt)

    def test_every_catalog_source_has_a_parallel_research_assignment(self):
        module = self.module
        assigned = {host for hosts in module._summary_research_sources_by_group().values()
                    for host in hosts}
        catalog_lines = [line for lines in market_study.SOURCE_PRIORITY.values()
                         for line in lines]
        catalog_lines.extend(line for lines in market_study.TYPE_SOURCE_PRIORITY.values()
                             for line in lines)
        required = {market_study._source_host(url)
                    for line in catalog_lines
                    for url in market_study._catalog_urls(line)
                    if market_study._source_host(url)}
        self.assertTrue(required)
        self.assertLessEqual(required, assigned)
        catalog_urls = module._summary_research_catalog_urls_by_host()
        required_urls = {url for line in catalog_lines
                         for url in market_study._catalog_urls(line)}
        assigned_urls = {url for urls in catalog_urls.values() for url in urls}
        self.assertLessEqual(required_urls, assigned_urls)
        for host, urls in module._SUMMARY_RESEARCH_REQUIRED_URLS.items():
            self.assertLessEqual(set(urls), set(catalog_urls.get(host, [])))
        group = module._SUMMARY_RESEARCH_GROUPS[0]
        for host in required:
            prompt = module._summary_research_prompt(
                {}, group, [host], 'جدة', 'الروضة')
            for url in catalog_urls.get(host, []):
                self.assertIn(url, prompt)


if __name__ == '__main__':
    unittest.main()
