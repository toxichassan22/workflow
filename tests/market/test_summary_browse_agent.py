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
import evidence
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

    def test_individual_researcher_uses_haiku_with_native_openrouter_search(self):
        module = self.module
        captured = {}

        def fake_browse(system, prompt, usage_ctx, **kwargs):
            captured.update({'system': system, 'prompt': prompt,
                             'usage_ctx': usage_ctx, **kwargs})
            return self._opened_reply()

        group = next(item for item in module._SUMMARY_RESEARCH_GROUPS
                     if item['key'] == 'transactions_and_rents')
        with patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_new_evidence_pool', return_value=None), \
                patch.dict(os.environ, {}, clear=False):
            os.environ.pop('BROWSER_USE_LOCAL_TOOLS', None)
            on_event = lambda _event: None
            outcome = module._run_summary_researcher(
                group, ['rei.rega.gov.sa'], {
                    'city': 'جدة', 'projectType': 'سكني',
                    'dataPeriodLabel': 'فترة مخصصة من 2025-10-17 إلى 2026-10-17',
                    'dataPeriodBounds': {'from': '2025-10-17', 'to': '2026-10-17'},
                }, 'جدة', 'الروضة',
                {'tenant_id': 't1'}, time.time() + 30, on_event=on_event)

        self.assertTrue(outcome['searched'])
        self.assertEqual(captured['model'], module._SUMMARY_RESEARCHER_MODEL)
        self.assertEqual(captured['model'], 'anthropic/claude-haiku-5.5')
        self.assertFalse(captured['local_tools'])
        self.assertEqual(captured['plugins'], [{'id': 'web', 'max_results': 5}])
        self.assertEqual(captured['max_steps'], 1000)
        self.assertEqual(captured['search_budget'], 1000)
        self.assertTrue(captured['research_mode'])
        self.assertEqual(captured['allowed_hosts'], ['rei.rega.gov.sa'])
        self.assertEqual(captured['max_tokens'], 66000)
        self.assertEqual(captured['usage_ctx']['tenant_id'], 't1')
        self.assertIs(captured['on_event'], on_event)
        self.assertIn('site:rei.rega.gov.sa', captured['prompt'])
        self.assertIn('https://rei.rega.gov.sa/ar/advanced-search/deals', captured['prompt'])
        self.assertIn('ابحث في المصادر الموكلة إليك', captured['prompt'])
        self.assertIn('الروضة', captured['prompt'])
        self.assertIn('فترة البيانات المطلوبة إلزاميًا: من 2025-10-17 إلى 2026-10-17',
                      captured['prompt'])
        self.assertIn('عدد غرف نوم الشقة', captured['prompt'])
        self.assertIn('أعلى سعر مرصود', captured['prompt'])
        self.assertNotIn('server_tools', captured)

    def test_individual_researcher_falls_back_to_local_tools_when_env_set(self):
        module = self.module
        captured = {}

        def fake_browse(system, prompt, usage_ctx, **kwargs):
            captured.update({'system': system, 'prompt': prompt,
                             'usage_ctx': usage_ctx, **kwargs})
            return self._opened_reply()

        group = next(item for item in module._SUMMARY_RESEARCH_GROUPS
                     if item['key'] == 'transactions_and_rents')
        with patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_new_evidence_pool', return_value=None), \
                patch.dict(os.environ, {'BROWSER_USE_LOCAL_TOOLS': '1'}):
            outcome = module._run_summary_researcher(
                group, ['rei.rega.gov.sa'], {
                    'city': 'جدة', 'projectType': 'سكني',
                }, 'جدة', 'الروضة',
                {'tenant_id': 't1'}, time.time() + 30)

        self.assertTrue(outcome['searched'])
        self.assertTrue(captured['local_tools'])
        self.assertEqual(captured['search_provider'], 'searxng')
        self.assertNotIn('plugins', captured)

    def test_individual_researcher_populates_evidence_pool_from_native_citations(self):
        module = self.module
        pool = evidence.EvidencePool()

        def fake_chat(messages, **kwargs):
            return {'choices': [{'message': {
                'role': 'assistant',
                'content': json.dumps({
                    'group': 'transactions_and_rents',
                    'findings': [{
                        'metric': 'متوسط سعر المتر', 'value': 4500, 'unit': 'SAR/m2',
                        'city': 'جدة', 'district': 'الروضة', 'source_url': 'https://rei.rega.gov.sa/deals/1',
                    }],
                    'sources': [{'name': 'الهيئة العامة للعقار', 'url': 'https://rei.rega.gov.sa/deals/1'}],
                }),
                'annotations': [{'url_citation': {
                    'url': 'https://rei.rega.gov.sa/deals/1',
                    'title': 'صفقة الروضة',
                    'content': 'تفاصيل الصفقة السكنية 4500 ريال للمتر',
                }}],
            }}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}

        group = next(item for item in module._SUMMARY_RESEARCH_GROUPS
                     if item['key'] == 'transactions_and_rents')
        import agent
        with patch.object(agent, 'openrouter_chat', side_effect=fake_chat), \
                patch.object(module, '_new_evidence_pool', return_value=pool):
            outcome = module._run_summary_researcher(
                group, ['rei.rega.gov.sa'], {
                    'city': 'جدة', 'projectType': 'سكني',
                }, 'جدة', 'الروضة',
                {'tenant_id': 't1'}, time.time() + 30)

        self.assertTrue(outcome['searched'])
        self.assertEqual(len(outcome['pages']), 1)
        self.assertEqual(outcome['pages'][0]['url'], 'https://rei.rega.gov.sa/deals/1')
        self.assertEqual(len(pool.pages()), 1)
        self.assertEqual(pool.pages()[0]['url'], 'https://rei.rega.gov.sa/deals/1')

    def test_final_summary_preserves_available_residential_transaction_breakdown(self):
        prompt = market_study.build_summary_user_prompt(
            {'city': 'جدة', 'projectType': 'سكني'}, [],
            retrieved_evidence='صفقات الشقق ذات الغرفتين: العدد 12، المتوسط 900000، الأعلى 1200000.')
        self.assertIn('أبقِ كل فئة متاحة في sector_performance', prompt)
        self.assertIn('لا تدمج فئات غرف النوم في متوسط واحد', prompt)
        self.assertIn('ولا تستبدلها بأسعار الإعلانات', prompt)

    def test_final_summary_prompt_uses_sar_formal_lines_and_omits_missing_details(self):
        prompt = market_study.build_summary_user_prompt(
            {'city': 'جدة', 'projectType': 'سكني'}, [],
            retrieved_evidence='صفقات الشقق ذات الغرفتين: 12 صفقة، متوسط 900000 ريال.')
        self.assertIn('كل القيم المالية في الدراسة وملاحظات المصادر بالريال السعودي', prompt)
        self.assertIn('احذف الفئات الفرعية غير المتاحة', prompt)
        self.assertIn('وفورمال ومسترسلة', prompt)
        self.assertIn('لا تذكر تاريخ الوصول', prompt)
        self.assertIn('لا تكتب كلمة «وسيط»', prompt)
        self.assertNotIn('في حدود 350 كلمة', prompt)

    def test_summary_normalization_converts_foreign_money_and_preserves_lines(self):
        with patch.object(market_study, 'price_fx_to_sar',
                          side_effect=lambda code: {'USD': 3.75, 'EUR': 4.0, 'SAR': 1.0}.get(code)):
            normalized = market_study.normalize_summary({
                'summary': {
                    'sector_performance': 'الفنادق:\nسعر الليلة 100 USD\nالشقق:\nغرفتان: 5 صفقات',
                    'city_position': 'غير متوفر من مصدر موثوق',
                },
                'one_block_summary': 'الفندق بسعر 100 دولارًا.',
                'sources': [{'name': 'مرجع الأسعار', 'note': 'EUR 50–75'}],
            })
        self.assertEqual(normalized['summary']['city_position'], '')
        self.assertIn('الفنادق:\nسعر الليلة 375 ريال سعودي\nالشقق:',
                      normalized['summary']['sector_performance'])
        self.assertNotIn('USD', normalized['summary']['sector_performance'])
        self.assertIn('375 ريال سعودي', normalized['one_block_summary'])
        self.assertIn('200 SAR to 300 SAR', normalized['sources'][0]['note'])

    def test_source_plan_pages_remain_usable_when_browser_research_fails(self):
        module = self.module
        group = module._SUMMARY_RESEARCH_GROUPS[0]
        source_map = {item['key']: [] for item in module._SUMMARY_RESEARCH_GROUPS}
        source_map[group['key']] = ['rei.rega.gov.sa']
        pool = evidence.EvidencePool()
        source_url = 'https://rei.rega.gov.sa/ar/cities/jeddah'
        pool.add_page(source_url, title='مؤشرات جدة العقارية',
                      content='عدد الصفقات 120 والقيمة 90 مليون ريال', via='http')

        def failed_researcher(group, hosts, payload, city, district,
                              usage_ctx, deadline, offer_lang='ar',
                              cancel_event=None, on_event=None):
            return {'key': group['key'], 'label': group['label'],
                    'city': city, 'district': district, 'hosts': hosts,
                    'result': {'error': {'message': 'browser search unavailable'}},
                    'parsed': {}, 'parse_error': 'worker_error',
                    'pages': [], 'searched': False}

        with patch.object(module, '_summary_research_sources_by_group',
                          return_value=source_map), \
                patch.object(module, '_run_summary_researcher',
                             side_effect=failed_researcher):
            result = module._run_market_summary_research(
                {'city': 'جدة', 'projectType': 'سكني'}, {}, pool,
                time.time() + 30)

        self.assertTrue(result['success'], result)
        self.assertIn(source_url, result['citation_urls'])
        self.assertEqual(result['reports'][0]['coverage_status'], 'partial')

    def test_completed_researcher_is_reused_when_resuming(self):
        module = self.module
        group = module._SUMMARY_RESEARCH_GROUPS[0]
        source_map = {item['key']: [] for item in module._SUMMARY_RESEARCH_GROUPS}
        source_map[group['key']] = ['rega.gov.sa']
        parsed = {'findings': [{'metric': 'عدد الصفقات', 'value': '12'}],
                  'coverage': []}
        reply = {'choices': [{'message': {
            'content': json.dumps(parsed, ensure_ascii=False),
            'annotations': [{'url_citation': {
                'url': 'https://rega.gov.sa/city-data',
                'title': 'بيانات المدينة', 'content': 'دليل'} }],
        }}]}
        researcher_calls = []
        checkpoints = []

        def fake_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar',
                            cancel_event=None, on_event=None):
            researcher_calls.append(hosts[0])
            return {'key': group['key'], 'label': group['label'],
                    'city': city, 'district': district, 'hosts': hosts,
                    'result': reply, 'parsed': parsed, 'parse_error': '',
                    'pages': [], 'searched': True}

        payload = {'city': 'جدة'}
        with patch.object(module, '_summary_research_sources_by_group',
                          return_value=source_map), \
                patch.object(module, '_run_summary_researcher',
                             side_effect=fake_researcher):
            first = module._run_market_summary_research(
                payload, {}, None, time.time() + 30,
                checkpoint=checkpoints.append)
            second = module._run_market_summary_research(
                payload, {}, None, time.time() + 30,
                resume_state=checkpoints[-1])

        self.assertTrue(first['success'])
        self.assertTrue(second['success'])
        self.assertEqual(researcher_calls, ['rega.gov.sa'])
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(len(checkpoints[0]['researchers']), 1)
        self.assertIn('https://rega.gov.sa/city-data', second['citation_urls'])

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
        observed_workers = []
        real_executor = module.ThreadPoolExecutor

        class RecordingExecutor(real_executor):
            def __init__(self, max_workers=None, *args, **kwargs):
                observed_workers.append(max_workers)
                super().__init__(max_workers=max_workers, *args, **kwargs)

        def fake_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar',
                            cancel_event=None, on_event=None):
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
                             side_effect=fake_researcher), \
                patch.object(module, 'ThreadPoolExecutor', RecordingExecutor):
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
        self.assertEqual(observed_workers, [3])

    def test_live_browser_events_advance_research_job_progress(self):
        module = self.module
        group = module._SUMMARY_RESEARCH_GROUPS[0]
        source_map = {item['key']: [] for item in module._SUMMARY_RESEARCH_GROUPS}
        source_map[group['key']] = ['rega.gov.sa']
        progress = []

        def fake_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar',
                            cancel_event=None, on_event=None):
            on_event({'phase': 'round', 'step': 1, 'max_steps': 100,
                      'searches': 0, 'pages': 0})
            on_event({'phase': 'tool', 'step': 1, 'tool': 'web_search',
                      'hint': 'site:rega.gov.sa جدة'})
            on_event({'phase': 'tool_done', 'step': 1, 'tool': 'web_search',
                      'hint': 'site:rega.gov.sa جدة', 'searches': 1,
                      'pages': 0, 'ok': True})
            on_event({'phase': 'tool', 'step': 2, 'tool': 'open_url',
                      'hint': 'https://rega.gov.sa/city-data'})
            on_event({'phase': 'tool_done', 'step': 2, 'tool': 'open_url',
                      'hint': 'https://rega.gov.sa/city-data', 'searches': 1,
                      'pages': 1, 'ok': True})
            return {'key': group['key'], 'label': group['label'],
                    'city': city, 'district': district, 'hosts': hosts,
                    'result': self._opened_reply(), 'parsed': {},
                    'parse_error': '', 'pages': [], 'searched': True}

        with patch.object(module, '_summary_research_sources_by_group',
                          return_value=source_map), \
                patch.object(module, '_run_summary_researcher',
                             side_effect=fake_researcher):
            research = module._run_market_summary_research(
                {'city': 'جدة'}, {}, None, time.time() + 30,
                report=lambda pct, message: progress.append((pct, message)))

        self.assertTrue(research['success'])
        self.assertTrue(any('1 عملية بحث و1 صفحة' in message for _pct, message in progress))
        self.assertTrue(any(pct > 12 for pct, _message in progress))
        self.assertTrue(any('اكتمل فتح الصفحة' in message for _pct, message in progress))

    def test_fatal_research_credit_error_stops_parallel_research(self):
        module = self.module
        group = module._SUMMARY_RESEARCH_GROUPS[0]
        fatal = {'error': {
            'fatal': True, 'message': 'رصيد غير كافٍ',
            'error_code': 'INSUFFICIENT_CREDITS', 'http_status': 402,
        }}
        started = []

        def fake_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar',
                            cancel_event=None, on_event=None):
            started.append(hosts[0])
            if hosts[0] == 'fatal.example':
                return {'key': group['key'], 'label': group['label'],
                        'city': city, 'district': district, 'hosts': hosts,
                        'result': fatal, 'parsed': {}, 'parse_error': '',
                        'pages': [], 'searched': False}
            cancel_event.wait(timeout=5)
            return {'key': group['key'], 'label': group['label'],
                    'city': city, 'district': district, 'hosts': hosts,
                    'result': {'error': {'message': 'cancelled'}},
                    'parsed': {}, 'parse_error': '', 'pages': [],
                    'searched': False}

        source_map = {item['key']: [] for item in module._SUMMARY_RESEARCH_GROUPS}
        source_map[group['key']] = ['fatal.example', 'other.example']
        with patch.object(module, '_summary_research_sources_by_group',
                          return_value=source_map), \
                patch.object(module, '_run_summary_researcher',
                             side_effect=fake_researcher):
            research = module._run_market_summary_research(
                {'city': 'جدة'}, {}, None, time.time() + 30)

        self.assertFalse(research['success'])
        self.assertEqual(research['error'], 'رصيد غير كافٍ')
        self.assertIn('fatal.example', started)

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
        self.assertEqual(captured['model'], 'google/gemini-4-argon')
        self.assertEqual(captured['reasoning_effort'], 'medium')
        self.assertEqual(captured['max_tokens'], 66000)
        self.assertEqual(captured['usage_ctx']['tenant_id'], 't1')
        annotations = result['choices'][0]['message']['annotations']
        self.assertEqual(annotations[0]['url_citation']['url'],
                         'https://rega.gov.sa/city-data')
        self.assertTrue(result['browse_trace'])

    def test_aggregator_retries_using_the_provider_affordable_token_cap(self):
        module = self.module
        responses = [
            {'error': {
                'provider_message': 'can only afford 24000 tokens',
                'message': 'the requested output cap exceeds the current allowance',
            }},
            {'choices': [{'message': {'content': '{}', 'annotations': []}}]},
        ]
        caps = []

        def fake_chat(_system, _prompt, **kwargs):
            caps.append(kwargs['max_tokens'])
            return responses.pop(0)

        with patch.object(module, 'call_text_chat', side_effect=fake_chat):
            result = module._run_market_summary_aggregator(
                'system', 'evidence prompt', {}, {'citation_urls': []},
                deadline=time.time() + 30)

        self.assertIn('choices', result)
        self.assertEqual(caps, [66000, 21600])

    def test_aggregator_stops_immediately_on_fatal_balance_error(self):
        module = self.module
        fatal = {'error': {
            'fatal': True,
            'provider_message': 'can only afford 24000 tokens',
            'message': 'رصيد غير كافٍ',
            'error_code': 'INSUFFICIENT_CREDITS',
            'http_status': 402,
        }}
        calls = []

        def fake_chat(_system, _prompt, **kwargs):
            calls.append(kwargs['max_tokens'])
            return fatal

        with patch.object(module, 'call_text_chat', side_effect=fake_chat):
            result = module._run_market_summary_aggregator(
                'system', 'evidence prompt', {}, {'citation_urls': []},
                deadline=time.time() + 30)

        self.assertIs(result, fatal)
        self.assertEqual(calls, [66000])

    def test_fatal_research_error_is_reported_as_credit_failure(self):
        module = self.module
        fatal = {'error': {'fatal': True, 'message': 'رصيد غير كافٍ',
                           'error_code': 'INSUFFICIENT_CREDITS', 'http_status': 402}}
        research = {'success': False, 'error': 'no pages',
                    'outcomes': [{'result': fatal}]}
        with self.app.app_context(), \
                patch.object(module, '_run_market_summary_research',
                             return_value=research) as research_mock:
            result = module._run_market_summary({'city': 'جدة'}, tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'insufficient_credit')
        self.assertEqual(result['providerError'], 'رصيد غير كافٍ')
        usage_ctx = research_mock.call_args.args[1]
        self.assertEqual(usage_ctx.get('billing_flow'), 'market_summary')

    def test_aggregator_failure_shows_safe_provider_reason_and_is_resumable(self):
        module = self.module
        provider_result = {'error': {'message': 'temporary upstream timeout'}}
        research = {'success': True, 'reports': [], 'citation_urls': []}
        data = {'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]}}
        with patch.object(module, '_prepare_market_payload',
                          return_value=data), \
                patch.object(module, '_usage_ctx', return_value={}), \
                patch.object(module, '_run_market_summary_research',
                             return_value=research), \
                patch.object(module.market_study,
                             'format_retrieved_evidence_block', return_value=''), \
                patch.object(module, '_run_market_summary_aggregator',
                             return_value=provider_result):
            result = module._run_market_summary(data, tenant_id=None)

        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'aggregator_failed')
        self.assertIn('تعذر تجميع نتائج بحث الويب', result['error'])
        self.assertIn('temporary upstream timeout', result['error'])
        self.assertEqual(result['providerError'], 'temporary upstream timeout')
        resumable_job = {
            'kind': 'summary', 'status': 'failed',
            'failureReason': result['failureReason'],
            'resumeState': {'researchers': {'task-1': {'searched': True}}},
        }
        self.assertTrue(module._market_job_can_resume(resumable_job))
        resumable_job['resumeState']['researchers'] = {}
        self.assertFalse(module._market_job_can_resume(resumable_job))

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

    def test_research_result_keeps_only_findings_from_assigned_sources(self):
        module = self.module
        parsed, removed = module._summary_restrict_research_result({
            'group': 'transactions_and_rents',
            'coverage': [
                {'url': 'https://sakani.sa/reports-and-data',
                 'completeness': 'complete'},
                {'url': 'https://unknown.example/report',
                 'completeness': 'complete'},
            ],
            'findings': [
                {'metric': 'متوسط الإيجار', 'value': '1000',
                 'source_url': 'https://www.sakani.sa/reports-and-data'},
                {'metric': 'صفقة', 'value': '999',
                 'source_url': 'https://unknown.example/report'},
            ],
            'sources': [
                {'url': 'https://sakani.sa/reports-and-data'},
                {'url': 'https://unknown.example/report'},
            ],
            'coverage_gaps': [],
        }, ['sakani.sa'])
        self.assertEqual(removed, 3)
        self.assertEqual(len(parsed['coverage']), 1)
        self.assertEqual(len(parsed['findings']), 1)
        self.assertEqual(len(parsed['sources']), 1)
        self.assertEqual(parsed['filtered_outside_source_rows'], 3)

    def test_market_research_trace_persists_sanitized_browser_events(self):
        module = self.module
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(module, 'UPLOADS_DIR', temp_dir):
            writer = module._market_research_trace_writer('tenant-a', 'jobtrace123')
            writer({
                'event': 'browser_step', 'tool': 'type_text',
                'purpose': 'تحديد المدينة والفترة',
                'arguments': {
                    'text': 'جدة 2025-10-17 إلى 2026-10-17',
                    'password': 'private-password',
                    'email': 'owner@example.test',
                    'phone': '0551234567',
                },
                'result': {'url': 'https://sakani.sa/reports-and-data',
                           'text': 'ظهرت بيانات السوق'},
            })
            path = module._market_research_trace_path('tenant-a', 'jobtrace123')
            with open(path, encoding='utf-8') as handle:
                record = json.loads(handle.readline())

        self.assertEqual(record['purpose'], 'تحديد المدينة والفترة')
        self.assertIn('ظهرت بيانات السوق', record['result']['text'])
        self.assertEqual(record['arguments']['password'], '[redacted]')
        self.assertEqual(record['arguments']['email'], '[redacted]')
        self.assertEqual(record['arguments']['phone'], '[redacted]')
        self.assertIn('2025-10-17', record['arguments']['text'])
        self.assertNotIn('owner@example.test', json.dumps(record))

    def test_market_research_trace_marks_its_size_limit(self):
        module = self.module
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(module, 'UPLOADS_DIR', temp_dir), \
                patch.object(module, '_MARKET_TRACE_MAX_BYTES', 1):
            writer = module._market_research_trace_writer('tenant-a', 'jobtrace124')
            writer({'event': 'browser_step', 'tool': 'open_url'})
            path = module._market_research_trace_path('tenant-a', 'jobtrace124')
            with open(path, encoding='utf-8') as handle:
                record = json.loads(handle.readline())
        self.assertEqual(record['event'], 'trace_limit_reached')

    def test_official_census_and_air_traffic_research_is_city_scoped_and_resumable(self):
        module = self.module
        census_group = next(item for item in module._SUMMARY_RESEARCH_GROUPS
                            if item['key'] == 'economy_commercial_industrial')
        aviation_group = next(item for item in module._SUMMARY_RESEARCH_GROUPS
                              if item['key'] == 'hospitality_and_tourism')
        payload = {'city': 'جدة', 'summaryScope': {'cities': [
            {'name': 'جدة', 'districts': ['الروضة']} ]}}

        census_prompt = module._summary_research_prompt(
            payload, census_group, ['geo.stats.gov.sa'], 'جدة')
        self.assertIn('https://geo.stats.gov.sa/portal/apps/experiencebuilder/experience/?id=64be425670be40c5881b37ee7ee5cf17&page=Population', census_prompt)
        self.assertIn('https://geo.stats.gov.sa/portal/apps/experiencebuilder/experience/?id=814450be664242f0be3d6da1f906024f&page=Household', census_prompt)
        self.assertIn('تعداد السعودية 2022', census_prompt)
        self.assertIn('الروضة', census_prompt)
        self.assertIn('الدقة الجغرافية الفعلية', census_prompt)

        residential_payload = {'city': 'جدة', 'projectType': 'سكني'}
        demographics_prompt = module._summary_research_prompt(
            residential_payload, census_group, ['stats.gov.sa'], 'جدة')
        self.assertIn('نمو سكان المدينة والأسر', demographics_prompt)
        self.assertIn('الوحدات السكنية أو الرخص', demographics_prompt)
        sakani_prompt = module._summary_research_prompt(
            {'city': 'جدة', 'projectType': 'تجاري'},
            module._SUMMARY_RESEARCH_GROUPS[0], ['sakani.sa'], 'جدة')
        self.assertIn('منصة سكني مصدر أساسي إلزامي', sakani_prompt)
        self.assertIn('جداول إيجار الوحدات التجارية', sakani_prompt)

        aviation_prompt = module._summary_research_prompt(
            payload, aviation_group, ['gaca.gov.sa'], 'جدة')
        self.assertIn('https://www.gaca.gov.sa/ar/Open-Data/OpenDataLibrary', aviation_prompt)
        self.assertIn('https://gaca.gov.sa/en/Reports-Categories/Air-Traffic-Reports?pageIndex=0', aviation_prompt)
        self.assertIn('أعداد المسافرين وحركات الرحلات', aviation_prompt)
        self.assertIn('لا تستنتجها من المسافرين', aviation_prompt)

        booking_prompt = module._summary_research_prompt(
            payload, aviation_group, ['booking.com'], 'جدة')
        check_in = market_study.date.fromordinal(
            market_study.date.today().toordinal() + 14)
        check_out = market_study.date.fromordinal(check_in.toordinal() + 2)
        self.assertIn('https://www.booking.com/', booking_prompt)
        self.assertIn(check_in.isoformat(), booking_prompt)
        self.assertIn(check_out.isoformat(), booking_prompt)
        self.assertIn('غرفة واحدة، بالغان، دون أطفال', booking_prompt)
        self.assertIn('ثلاث منشآت متاحة قابلة للمقارنة على الأقل', booking_prompt)
        self.assertIn('لا تسمّه ADR أو متوسطًا سنويًا', booking_prompt)
        self.assertIn('إلزامي عند اختيار نشاط فندقي أو سكني', booking_prompt)
        self.assertNotIn('كبديل فقط', booking_prompt)

        for group, host in ((census_group, 'geo.stats.gov.sa'),
                            (aviation_group, 'gaca.gov.sa'),
                            (aviation_group, 'booking.com')):
            task_id = json.loads(module._summary_research_task_id(
                group, [host], 'جدة', ''))
            self.assertEqual(task_id[-1], 'prompt-v4')
        ordinary_group = module._SUMMARY_RESEARCH_GROUPS[0]
        ordinary_task_id = json.loads(module._summary_research_task_id(
            ordinary_group, ['rega.gov.sa'], 'جدة', ''))
        self.assertEqual(ordinary_task_id[-1], 'prompt-v3')
        self.assertEqual(len(ordinary_task_id), 5)

        source_map = {item['key']: [] for item in module._SUMMARY_RESEARCH_GROUPS}
        source_map[census_group['key']] = ['geo.stats.gov.sa']
        source_map[aviation_group['key']] = ['gaca.gov.sa', 'booking.com']
        calls = []

        def fake_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar',
                            cancel_event=None, on_event=None):
            calls.append((hosts[0], city, district))
            return {'key': group['key'], 'label': group['label'],
                    'city': city, 'district': district, 'hosts': hosts,
                    'result': self._opened_reply('https://' + hosts[0] + '/data'),
                    'parsed': {}, 'parse_error': '', 'pages': [], 'searched': True}

        with patch.object(module, '_summary_research_sources_by_group',
                          return_value=source_map), \
                patch.object(module, '_run_summary_researcher',
                             side_effect=fake_researcher):
            research = module._run_market_summary_research(
                payload, {}, None, time.time() + 30)
        self.assertTrue(research['success'])
        self.assertEqual(set(calls), {
            ('geo.stats.gov.sa', 'جدة', ''),
            ('gaca.gov.sa', 'جدة', ''),
            ('booking.com', 'جدة', ''),
            ('booking.com', 'جدة', 'الروضة'),
        })

    def test_researcher_jobs_follow_selected_project_activity_sources(self):
        module = self.module
        groups = {item['key']: item for item in module._SUMMARY_RESEARCH_GROUPS}
        source_map = {key: [] for key in groups}
        source_map['transactions_and_rents'] = [
            'rei.rega.gov.sa', 'aqar.fm', 'sakani.sa']
        source_map['hospitality_and_tourism'] = [
            'mt.gov.sa', 'gaca.gov.sa', 'booking.com']
        source_map['economy_commercial_industrial'] = [
            'geo.stats.gov.sa', 'modon.gov.sa']
        calls = []

        def fake_researcher(group, hosts, payload, city, district,
                            usage_ctx, deadline, offer_lang='ar',
                            cancel_event=None, on_event=None):
            host = hosts[0]
            calls.append(host)
            return {'key': group['key'], 'label': group['label'],
                    'city': city, 'district': district, 'hosts': hosts,
                    'result': self._opened_reply('https://' + host + '/data'),
                    'parsed': {}, 'parse_error': '', 'pages': [], 'searched': True}

        payload = {'city': 'جدة', 'projectType': 'سكني',
                   'summaryScope': {'cities': [{'name': 'جدة', 'districts': []}]}}
        with patch.object(module, '_summary_research_sources_by_group',
                          return_value=source_map), \
                patch.object(module, '_run_summary_researcher',
                             side_effect=fake_researcher):
            result = module._run_market_summary_research(
                payload, {}, None, time.time() + 30)

        self.assertTrue(result['success'])
        self.assertIn('rei.rega.gov.sa', calls)
        self.assertIn('aqar.fm', calls)
        self.assertIn('geo.stats.gov.sa', calls)
        self.assertIn('booking.com', calls)
        self.assertNotIn('gaca.gov.sa', calls)
        self.assertNotIn('modon.gov.sa', calls)

    def test_hospitality_and_residential_always_include_booking_source(self):
        for project_type in ('فندقي', 'سكني'):
            with self.subTest(project_type=project_type):
                hosts = self.module._summary_research_activity_hosts(
                    {'projectType': project_type})
                self.assertIn('booking.com', hosts)

    def test_resumed_research_identity_includes_selected_project_activity(self):
        module = self.module
        group = module._SUMMARY_RESEARCH_GROUPS[0]
        residential_signature = module._summary_research_activity_signature(
            {'projectType': 'سكني'})
        hotel_signature = module._summary_research_activity_signature(
            {'projectType': 'فندقي'})
        self.assertNotEqual(residential_signature, hotel_signature)
        self.assertNotEqual(
            module._summary_research_task_id(
                group, ['stats.gov.sa'], 'جدة', '', residential_signature),
            module._summary_research_task_id(
                group, ['stats.gov.sa'], 'جدة', '', hotel_signature))

    def test_aqar_listing_urls_use_selected_project_activity_only(self):
        module = self.module
        group = module._SUMMARY_RESEARCH_GROUPS[0]
        prompt = module._summary_research_prompt(
            {'projectType': 'سكني'}, group, ['aqar.fm'], 'جدة')
        expected_urls = [url for url, _label in market_study._listing_urls(
            ['سكني'], {'بيع', 'إيجار'}, 'جدة')]
        self.assertEqual(len(expected_urls), 6)
        for url in expected_urls:
            self.assertIn(url, prompt)
        for unrelated_kind in ('تجاري', 'فندقي', 'صناعي ولوجستي'):
            unrelated_urls = [url for url, _label in market_study._listing_urls(
                [unrelated_kind], {'بيع', 'إيجار'}, 'جدة')]
            for url in unrelated_urls:
                self.assertNotIn(url, prompt)
        self.assertEqual(list(market_study._listing_urls(
            ['فندقي'], {'بيع', 'إيجار'}, 'جدة')), [])

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
