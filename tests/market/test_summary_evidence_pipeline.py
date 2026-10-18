"""A5 — pooled-evidence seam tests for summary, summary-chat and best-use.

The board's search rework gives every market job one ``EvidencePool``, one
wall-clock deadline and one shared browser session; the summary executor, the
summary-chat research turn and the best-use price scan all ride it
(``docs/plans/مشكله البحث/plan.md``).

``test_summary_pool_wiring.py`` owns the end-to-end contract coverage
(plan-first ordering, call kwargs, sources union, shared scan pool). This
suite covers the seams it does not:

- ``_run_market_source_plan`` is invoked with the pipeline's pinned-HTTPS
  ``_market_source_fetch_http`` and the *same* session + deadline + pool the
  browse call gets — and the caller, not the agent, closes that session.
- A missing pool layer degrades honestly: the plan is skipped, the browse
  call still carries its deadline, and the result has no ``searchStats``.
- A clean reply with zero browsed pages and an empty pool is still an
  explicit ``search_not_run`` — the pool never softens the anti-memory guard.
- Discussion-only chat turns create no pool at all; the phase-B turn's
  ``citations`` union the pool's pages with the reply's annotations.
- ``_best_use_price_scan_use`` forwards ``evidence_pool``/``deadline``/
  ``session`` verbatim; the chunked scan closes each pool thread's browser
  exactly once.
- The job-budget constants drive the deadlines the executors pass.

Zero real network/Chromium — ``agent.run_browse_agent``, ``browser``.
``BrowserWorker``/``thread_local_browser``, the retrieval planner and the URL
probe are all faked at the seams.

Run like every other suite — one suite per process, PYTHONPATH=repo root::

    python -m unittest tests.market.test_summary_evidence_pipeline
"""

import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_MODULES = ROOT / 'modules'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if _MODULES.is_dir():
    for _dirpath, _dirnames, _filenames in os.walk(_MODULES):
        if any(_f.endswith('.py') for _f in _filenames) and _dirpath not in sys.path:
            sys.path.insert(0, _dirpath)
    del _dirpath, _dirnames, _filenames

import agent  # noqa: E402  modules/web_browse/agent.py — patched by name
import db  # noqa: E402
import evidence  # noqa: E402  modules/web_browse/evidence.py — real pool
import market_study  # noqa: E402


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
        'browse_trace': [{'url': url, 'title': 'صفحة', 'chars': 2} for url in urls],
    }


def _chat_result(payload, citations=()):
    message = {'role': 'assistant', 'content': json.dumps(payload, ensure_ascii=False)}
    if citations:
        message['annotations'] = [
            {'url_citation': {'url': url, 'title': 'صفحة مصدر', 'content': 'نص مسترجع'}}
            for url in citations]
    return {'choices': [{'finish_reason': 'stop', 'message': message}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}


class _FakeWorker:
    """A lazy, un-launched browser worker — ``_market_browser_session``
    hands the executor one of these; Chromium would launch only on a real
    tool call, which the faked agent never performs."""

    def __init__(self):
        self.closed = 0
        self.is_open = False

    def web_search(self, query, max_results=8, **_kw):
        return []

    def open_url(self, url, timeout=20, **_kw):
        return {'url': url, 'final_url': url, 'title': '', 'text': '',
                'error': 'not_found'}

    def close(self):
        self.closed += 1
        self.is_open = False


class SummaryEvidenceSeamTests(unittest.TestCase):
    """The summary executor's seams: the retrieval plan gets the pipeline's
    fetcher plus the job's pool/session/deadline, and the executor — not the
    agent — owns the session."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'evidence-seam.db')
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
        self.aggregate_prompts = []
        self._aggregator_patch = patch.object(
            self.application_module, '_run_market_summary_aggregator',
            side_effect=self._fake_aggregator)
        self._aggregator_patch.start()
        self.addCleanup(self._aggregator_patch.stop)

    def _fake_aggregator(self, _system, prompt, _usage_ctx, research,
                         deadline=None):
        self.aggregate_prompts.append(str(prompt))
        urls = tuple(research.get('citation_urls') or [])
        return _agent_reply(urls=urls)

    def test_plan_seam_and_session_ownership(self):
        module = self.application_module
        workers = []
        order = []
        plan_calls = {}
        agent_calls = []
        fake_plan = [{'purpose': 'deals',
                      'url': 'https://rei.rega.gov.sa/ar/advanced-search/deals',
                      'tier': 1, 'needs_browser': False, 'label': 'الصفقات'}]

        def fake_worker(search_provider=None):
            worker = _FakeWorker()
            workers.append(worker)
            return worker

        def fake_run_plan(plan, pool, fetch_http, session=None,
                          deadline=None, report=None):
            order.append('plan')
            plan_calls.update(plan=plan, pool=pool, fetch_http=fetch_http,
                              session=session, deadline=deadline)
            pool.add_page('https://rei.rega.gov.sa/deals/dataset', title='داتا',
                          content='نص الصفحة', via='http')
            return {'fetched': 1, 'skipped': 0, 'failed': 0}

        def fake_agent(task, usage_ctx=None, **kwargs):
            order.append('agent')
            agent_calls.append(kwargs)
            return _agent_reply()

        with self.app.app_context(), \
                patch.object(module, '_market_browser_session',
                             side_effect=fake_worker), \
                patch.object(market_study, 'build_source_plan',
                             return_value=fake_plan) as build_mock, \
                patch.object(market_study, 'run_source_plan',
                             side_effect=fake_run_plan), \
                patch.object(agent, 'run_browse_agent', side_effect=fake_agent), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(market_study, 'apply_search_citations',
                             wraps=market_study.apply_search_citations) as cite_spy:
            before = time.time()
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id='t1')

        self.assertTrue(result['success'], result)
        self.assertEqual(order[0], 'plan')
        self.assertTrue(agent_calls)
        self.assertTrue(all(event == 'agent' for event in order[1:]))
        build_mock.assert_called_once()
        # The plan executor gets the job pool, pinned-HTTPS fetcher, and its
        # sequential-stage browser. Parallel researchers get their own pools,
        # preloaded with the plan pages, plus the shared deadline.
        self.assertIs(plan_calls['fetch_http'], module._market_source_fetch_http)
        self.assertIsNotNone(plan_calls['pool'])
        self.assertIs(plan_calls['session'], workers[0])
        matching_calls = [
            call for call in agent_calls
            if any('rei.rega.gov.sa' in str(h) for h in (call.get('allowed_hosts') or []))
        ]
        self.assertTrue(matching_calls)
        for call in matching_calls:
            worker_pool = call.get('evidence_pool')
            self.assertIn('https://rei.rega.gov.sa/deals/dataset',
                          [page.get('url') for page in worker_pool.pages()])
        for call in agent_calls:
            worker_pool = call.get('evidence_pool')
            self.assertIsNotNone(worker_pool)
            self.assertIsNot(worker_pool, plan_calls['pool'])
            self.assertNotIn('session', call)
        # The plan stage runs under its own capped sub-deadline
        # (MARKET_SOURCE_PLAN_BUDGET), never the job's full budget — a chain
        # of dead catalog URLs must not eat the whole run.
        plan_deadline = plan_calls['deadline']
        self.assertIsNotNone(plan_deadline)
        job_deadline = agent_calls[0].get('deadline')
        self.assertIsNotNone(job_deadline)
        self.assertLessEqual(plan_deadline, job_deadline)
        self.assertLessEqual(
            plan_deadline, time.time() + module._SOURCE_PLAN_TIME_BUDGET + 5)
        budget = module._SUMMARY_JOB_TIME_BUDGET
        self.assertTrue(before + budget - 20 < job_deadline
                        < before + budget + 20)
        # One lazy session for the job — built un-launched, closed once by
        # the caller (the agent never owns it).
        self.assertEqual(len(workers), 1)
        self.assertFalse(workers[0].is_open)
        self.assertEqual(workers[0].closed, 1)
        # Citation collection unions the pool's fetched pages.
        citation_arg = cite_spy.call_args.args[1]
        self.assertIn('https://rei.rega.gov.sa/deals/dataset', citation_arg)
        self.assertIn('https://sakani.sa/reports-and-data/rent-index-q3',
                      citation_arg)
        stats = result.get('searchStats')
        self.assertEqual(set(stats or {}),
                         {'queries', 'pages', 'pool_hits'})
        self.assertEqual(stats['pages'], 1)

    def test_summary_prompt_carries_retrieved_evidence_from_pool(self):
        """User requirement: the summary prompt must directly receive the extracted
        evidence from primary sources in the EvidencePool, rather than writing
        from memory while attaching URLs post-hoc. Also guards that depth and
        advisory constraints are strictly ordered."""
        module = self.application_module
        fake_plan = [{'purpose': 'deals',
                      'url': 'https://rei.rega.gov.sa/ar/cities/jeddah',
                      'tier': 1, 'needs_browser': False, 'label': 'صفقات جدة'}]

        def fake_run_plan(plan, pool, fetch_http, session=None,
                          deadline=None, report=None):
            pool.add_page(
                'https://rei.rega.gov.sa/ar/cities/jeddah',
                title='مؤشرات جدة العقارية',
                content='إجمالي عدد الصفقات: 1,420 صفقة بقيمة 2.8 مليار ريال. متوسط سعر المتر السكني 4,100 ريال.',
                via='http',
            )
            pool.add_page(
                'https://sakani.sa/reports-and-data/rent-index',
                title='مؤشر إيجار',
                content='متوسط إيجار الشقة السكنية 3 غرف في شمال جدة: 38,000 ريال سنوياً.',
                via='http',
            )
            return {'fetched': 2, 'skipped': 0, 'failed': 0}

        def fake_agent(task, usage_ctx=None, **kwargs):
            return _agent_reply()

        with self.app.app_context(), \
                patch.object(market_study, 'build_source_plan', return_value=fake_plan), \
                patch.object(market_study, 'run_source_plan', side_effect=fake_run_plan), \
                patch.object(agent, 'run_browse_agent', side_effect=fake_agent), \
                patch.object(module, '_verify_market_urls', return_value=set()):
            result = module._execute_market_summary({'city': 'جدة', 'projectType': 'سكني'}, tenant_id='t1')

        self.assertTrue(result['success'], result)
        self.assertEqual(len(self.aggregate_prompts), 1)
        task_prompt = self.aggregate_prompts[0]
        # Primary source evidence must be present directly in prompt
        self.assertIn('بيانات وحقائق مستخلصة من المصادر الأساسية المعتمدة', task_prompt)
        self.assertIn('https://rei.rega.gov.sa/ar/cities/jeddah', task_prompt)
        self.assertIn('1,420 صفقة بقيمة 2.8 مليار ريال', task_prompt)
        self.assertIn('https://sakani.sa/reports-and-data/rent-index', task_prompt)
        self.assertIn('38,000 ريال سنوياً', task_prompt)
        # The synthesizer stays evidence-bound and preserves relevant details.
        self.assertIn('استخدم فقط الادعاءات التي يسندها الدليل المسترجع أدناه',
                      task_prompt)
        self.assertIn('لا تحوّل بيانات المملكة إلى بيانات مدينة', task_prompt)
        self.assertIn('لا تدمج فئات غرف النوم في متوسط واحد', task_prompt)

    def test_format_retrieved_evidence_block_contract(self):
        """Unit test for market_study.format_retrieved_evidence_block across
        Arabic, English, empty, and truncated states."""
        pool = evidence.EvidencePool()
        # Empty pool returns empty string
        self.assertEqual(market_study.format_retrieved_evidence_block(pool), '')
        self.assertEqual(market_study.format_retrieved_evidence_block(None), '')

        pool.add_page('https://example.com/data', title='Report', content='Metric 1: 500 units', via='http')
        # Arabic formatting
        ar_block = market_study.format_retrieved_evidence_block(pool, offer_lang='ar')
        self.assertIn('بيانات وحقائق مستخلصة من المصادر الأساسية المعتمدة', ar_block)
        self.assertIn('https://example.com/data', ar_block)
        self.assertIn('Metric 1: 500 units', ar_block)

        # English formatting
        en_block = market_study.format_retrieved_evidence_block(pool, offer_lang='en')
        self.assertIn('Retrieved Evidence from Primary Sources', en_block)
        self.assertIn('https://example.com/data', en_block)
        self.assertIn('Metric 1: 500 units', en_block)

    def test_no_pool_means_no_plan_but_call_still_carries_deadline(self):
        module = self.application_module
        captured = {}
        poolless = types.ModuleType('evidence')  # no EvidencePool inside

        def fake_agent(task, usage_ctx=None, **kwargs):
            captured.update(kwargs)
            return _agent_reply()

        with self.app.app_context(), \
                patch.dict(sys.modules, {'evidence': poolless}), \
                patch.object(market_study, 'run_source_plan') as run_mock, \
                patch.object(agent, 'run_browse_agent', side_effect=fake_agent), \
                patch.object(module, '_verify_market_urls', return_value=set()):
            result = module._execute_market_summary({'city': 'جدة'}, tenant_id=None)

        self.assertTrue(result['success'], result)
        run_mock.assert_not_called()
        self.assertIsNone(captured.get('evidence_pool'))
        self.assertIsInstance(captured.get('deadline'), float)
        self.assertIsNone(result.get('searchStats'))

    def test_zero_citations_and_empty_pool_still_search_not_run(self):
        """The pool does not soften the anti-memory guard: a clean reply with
        no browsed pages and an empty pool is still an explicit miss."""
        module = self.application_module
        with self.app.app_context(), \
                patch.object(module, '_run_market_source_plan',
                             return_value=None), \
                patch.object(agent, 'run_browse_agent',
                             return_value=_agent_reply(urls=())):
            result = module._execute_market_summary({'city': 'جدة'},
                                                    tenant_id=None)
        self.assertFalse(result['success'])
        self.assertEqual(result['failureReason'], 'search_not_run')


class SummaryChatEvidenceSeamTests(unittest.TestCase):
    """Phase B of the summary chat rides the same pool+deadline contract —
    and a discussion-only turn never builds a pool."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'evidence-seam-chat.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _chat_data(self):
        return {'axis': 'supply', 'message': 'حدّث أرقام العرض',
                'research': 'auto', 'history': [], 'city': 'جدة',
                'district': 'النرجس', 'projectType': 'سكني'}

    def test_phase_b_unions_pool_pages_into_turn_citations(self):
        module = self.application_module
        pools = []
        captured = {}
        cited_url = 'https://sakani.sa/reports-and-data/rent-index'
        pooled_url = 'https://ejar.sa/reports/market-quarterly'

        def counting_pool():
            pool = evidence.EvidencePool()
            pools.append(pool)
            return pool

        def fake_browse(*_args, **kwargs):
            captured.update(kwargs)
            # The run deposits a retrieved page in the job pool alongside the
            # annotations its reply cites.
            kwargs['evidence_pool'].add_page(
                pooled_url, title='تقرير إيجار', content='نص التقرير',
                via='browser')
            return _chat_result({'reply': 'بعد البحث', 'ops': []},
                                citations=[cited_url])

        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, '_new_evidence_pool',
                             side_effect=counting_pool), \
                patch.object(module, 'call_text_chat', return_value=_chat_result(
                    {'reply': 'سأبحث', 'needs_research': True,
                     'queries': ['إيجار النرجس'], 'ops': []})), \
                patch.object(module, '_browse_agent_call',
                             side_effect=fake_browse):
            before = time.time()
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id='t1')

        self.assertTrue(result['success'], result)
        self.assertEqual(len(pools), 1)
        self.assertIs(captured.get('evidence_pool'), pools[0])
        deadline = captured.get('deadline')
        self.assertIsInstance(deadline, float)
        budget = module._SUMMARY_CHAT_JOB_TIME_BUDGET
        self.assertTrue(before + budget - 20 < deadline < before + budget + 20)
        citations = result.get('citations') or []
        self.assertIn(cited_url, citations)
        self.assertIn(pooled_url, citations)

    def test_discuss_turn_creates_no_pool(self):
        module = self.application_module
        pools = []

        def counting_pool():
            pool = evidence.EvidencePool()
            pools.append(pool)
            return pool

        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, '_new_evidence_pool',
                             side_effect=counting_pool), \
                patch.object(module, 'call_text_chat', return_value=_chat_result(
                    {'reply': 'رد نقاشي', 'needs_research': False, 'ops': []})):
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id='t1')

        self.assertTrue(result['success'], result)
        self.assertEqual(pools, [])


class BestUseScanEvidenceSeamTests(unittest.TestCase):
    """The price scan fans uses over pool threads sharing one job pool, a
    thread-bound browser each — closed once when the chunk finishes — and one
    deadline."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'evidence-seam-scan.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_threads_share_one_pool_and_close_once(self):
        module = self.application_module
        pools = []
        uses = ['residential', 'retail', 'office', 'hotel', 'warehouse']
        draft = {'id': 'd1',
                 'draft_data': {'city': 'جدة', 'district': 'النرجس'}}
        calls = []
        bound = {}       # thread ident -> its currently-bound worker
        created = []     # every worker the factory hands out
        closes = []      # one entry per close_thread_browser call
        lock = threading.Lock()

        def counting_pool():
            pool = evidence.EvidencePool()
            pools.append(pool)
            return pool

        def fake_thread_browser():
            ident = threading.get_ident()
            with lock:
                worker = bound.get(ident)
                if worker is None:
                    worker = _FakeWorker()
                    bound[ident] = worker
                    created.append(worker)
                return worker

        def fake_close_thread_browser():
            # Real close_thread_browser drops the thread's binding — the next
            # chunk on a reused pool thread binds a fresh worker.
            ident = threading.get_ident()
            closes.append(ident)
            bound.pop(ident, None)

        def fake_use(use, prompt, city, draft_, data, usage_ctx, **kwargs):
            calls.append((use, kwargs))
            return [], None

        with self.app.app_context(), \
                patch.object(module, '_new_evidence_pool',
                             side_effect=counting_pool), \
                patch.object(module, '_verify_thread_browser',
                             side_effect=fake_thread_browser), \
                patch.object(module, '_close_verify_thread_browser',
                             side_effect=fake_close_thread_browser), \
                patch.object(module, '_best_use_price_scan_use',
                             side_effect=fake_use), \
                patch.object(module, '_best_use_price_page', return_value=None):
            before = time.time()
            result = module._best_use_scan_prices(
                draft, {'permittedUses': uses}, {}, progress=None)

        self.assertEqual(sorted(use for use, _ in calls), sorted(uses))
        self.assertEqual(len(pools), 1)
        for _use, kwargs in calls:
            self.assertIs(kwargs.get('evidence_pool'), pools[0])
            self.assertTrue(before - 1 < kwargs.get('deadline')
                            < before + module._BEST_USE_SCAN_TIME_BUDGET + 1)
            self.assertIn(kwargs.get('session'), created)
        # 5 uses over ≤4 chunk tasks: every browser created for a chunk is
        # closed once, regardless of how many executor threads the scheduler
        # needed to run those chunks.
        self.assertEqual(len(closes), len(created))
        self.assertLessEqual(len(created), 4)
        self.assertLess(len(created), len(calls))
        from collections import Counter
        self.assertGreaterEqual(
            max(Counter(id(kwargs['session']) for _use, kwargs in calls)
                .values()), 2)
        self.assertIn('table', result)

    def test_scan_use_forwards_pool_deadline_session(self):
        module = self.application_module
        captured = {}
        pool = evidence.EvidencePool()
        session = object()

        def fake_call(*args, **kwargs):
            captured.update(kwargs)
            return {'choices': [{'message': {
                'role': 'assistant', 'content': '{"observations": []}',
                'annotations': [{'url_citation': {
                    'url': 'https://x.sa/1', 'title': 't', 'content': 'c'}}]}}],
                'usage': {}}

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call',
                             side_effect=fake_call), \
                patch.object(module, '_best_use_explore_provider',
                             return_value={'observations': []}):
            rows, _response = module._best_use_price_scan_use(
                'residential', '{"use":"residential"}', 'جدة',
                {'id': 'd1'}, {}, {},
                evidence_pool=pool, deadline=123.5, session=session)

        self.assertEqual(rows, [])
        self.assertIs(captured.get('evidence_pool'), pool)
        self.assertEqual(captured.get('deadline'), 123.5)
        self.assertIs(captured.get('session'), session)
        self.assertEqual(captured.get('search_budget'), 3)


class JobBudgetConstantTests(unittest.TestCase):
    """The three job-budget knobs: positive int constants (env parsing is the
    same vetted try/except shape as _MARKET_JOB_TIME_BUDGET) that the
    executors actually spend as deadlines."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'evidence-budget.db')
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
        self._aggregator_patch = patch.object(
            self.application_module, '_run_market_summary_aggregator',
            side_effect=lambda _system, _prompt, _usage_ctx, research,
            deadline=None: _agent_reply(
                urls=tuple(research.get('citation_urls') or [])))
        self._aggregator_patch.start()
        self.addCleanup(self._aggregator_patch.stop)

    def test_budget_constants_exist_and_floor(self):
        module = self.application_module
        for name, floor in (('_SUMMARY_JOB_TIME_BUDGET', 60),
                            ('_SUMMARY_CHAT_JOB_TIME_BUDGET', 30),
                            ('_BEST_USE_SCAN_TIME_BUDGET', 60)):
            value = getattr(module, name, None)
            self.assertIsInstance(value, int, name)
            self.assertGreaterEqual(value, floor, name)

    def test_summary_deadline_tracks_the_budget_constant(self):
        module = self.application_module
        captured = {}

        def fake_agent(task, usage_ctx=None, **kwargs):
            captured.update(kwargs)
            return _agent_reply()

        with self.app.app_context(), \
                patch.object(module, '_SUMMARY_JOB_TIME_BUDGET', 95), \
                patch.object(module, '_run_market_source_plan',
                             return_value=None), \
                patch.object(agent, 'run_browse_agent',
                             side_effect=fake_agent), \
                patch.object(module, '_verify_market_urls', return_value=set()):
            before = time.time()
            result = module._execute_market_summary({'city': 'جدة'},
                                                    tenant_id=None)

        self.assertTrue(result['success'], result)
        self.assertTrue(before + 80 < captured.get('deadline') < before + 110)


if __name__ == '__main__':
    unittest.main()
