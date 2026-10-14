"""Summary / chat / best-use pool wiring tests — search-rework board task A5.

The same ``EvidencePool`` + job deadline discipline that A4 gives the
competitors table reaches the three other browse paths:

- ``_execute_market_summary`` runs the deterministic ``run_source_plan`` pass
  first, then the main browse call with ``evidence_pool``/``deadline``/
  ``session``, and the sources table unions ``pool.pages()`` into the
  citation set ``apply_search_citations`` resolves against — a pool-fetched
  page counts as retrieved evidence even when the agent never cited it.
- ``_execute_market_summary_chat`` phase B (the optional research turn) rides
  the same params.
- ``_best_use_scan_prices`` shares one pool across every per-use browse call
  and gives each its thread's browser session.

Contract: docs/plans/مشكله البحث/plan.md — A5. Zero network, zero Chromium —
``agent.run_browse_agent`` (flat import), the browser surface, the source
plan, ``call_text_chat`` and the URL probe are all faked.

Run like every other suite — one suite per process, PYTHONPATH=repo root::

    python -m unittest tests.market.test_summary_pool_wiring
"""

import contextlib
import json
import os
import sys
import tempfile
import time
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

import agent  # noqa: E402  modules/web_browse/agent.py
import browser  # noqa: E402
import db  # noqa: E402
import market_study  # noqa: E402

# Non-generic sakani dataset path (a 'data' path token would be filtered as
# generic by resolve_source_url_from_citations).
_POOL_PAGE = 'https://sakani.sa/ar/knowledge-center/market-insight'
_CITED_PAGE = 'https://ejar.sa/reports/q3'


def _reply(payload, pages=()):
    return {
        'choices': [{'message': {
            'role': 'assistant',
            'content': json.dumps(payload, ensure_ascii=False),
            'annotations': [
                {'url_citation': {'url': url, 'title': title, 'content': text}}
                for url, title, text in pages],
        }}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        'browse_trace': [
            {'url': url, 'title': title, 'chars': len(text)}
            for url, title, text in pages],
    }


class _FakeWorker:
    def __init__(self):
        self.searches = []
        self.opened = []
        self.closed = False
        self.is_open = True

    def web_search(self, query, max_results=8, **_kw):
        self.searches.append(str(query))
        return []

    def open_url(self, url, timeout=20, **_kw):
        self.opened.append(str(url))
        return {'url': url, 'final_url': url, 'title': '',
                'text': '', 'error': 'not_found'}

    def close(self):
        self.closed = True
        self.is_open = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


class _Fixture:
    """Fakes for every seam the summary-side wiring touches."""

    def __init__(self, pool_pages=()):
        self.worker = _FakeWorker()
        self.agent_calls = []
        self.events = []
        self.plan_kwargs = {}
        self._pool_pages = list(pool_pages)

    def fake_agent(self, task, usage_ctx=None, **kwargs):
        self.agent_calls.append({'task': str(task), 'kwargs': dict(kwargs)})
        self.events.append('agent')
        return _reply(self.payload, pages=self.citation_pages)

    payload = {'summary': {'market_definition': 'قراءة السوق'},
               'decision': 'فرصة قوية',
               'sources': [{'name': 'سكني', 'url': 'https://sakani.sa'}]}
    citation_pages = [(_CITED_PAGE, 'تقرير إيجار',
                       'مؤشر سوق الإيجار للربع الثالث')]

    def fake_build_plan(self, payload, offer_lang='ar'):
        self.events.append('build_plan')
        return [{'purpose': 'rent-index', 'url': _POOL_PAGE, 'tier': 1,
                 'needs_browser': False, 'label': 'مؤشر الإيجار'}]

    def fake_run_plan(self, plan, pool=None, fetch_http=None, **kwargs):
        self.events.append('plan')
        self.plan_kwargs = kwargs
        for url, title, text in self._pool_pages:
            pool.add_page(url, title=title, content=text, via='http')
        return {'fetched': len(self._pool_pages), 'skipped': 0, 'failed': 0}

    @contextlib.contextmanager
    def fake_browser_session(self, *a, **kw):
        yield self.worker

    def patches(self, module):
        worker = self.worker
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(
            agent, 'run_browse_agent', side_effect=self.fake_agent))
        stack.enter_context(patch.object(
            market_study, 'build_source_plan', side_effect=self.fake_build_plan,
            create=True))
        stack.enter_context(patch.object(
            market_study, 'run_source_plan', side_effect=self.fake_run_plan,
            create=True))
        for mod, name in ((browser, 'browser_session'),
                          (module, 'browser_session')):
            stack.enter_context(patch.object(
                mod, name, self.fake_browser_session, create=True))
        for mod, name in ((browser, 'thread_local_browser'),
                          (module, 'thread_local_browser')):
            stack.enter_context(patch.object(
                mod, name, lambda *a, **kw: worker, create=True))
        for mod, name in ((browser, 'web_search'), (module, 'web_search')):
            stack.enter_context(patch.object(
                mod, name, worker.web_search, create=True))
        for mod, name in ((browser, 'open_url'), (module, 'open_url')):
            stack.enter_context(patch.object(
                mod, name, worker.open_url, create=True))
        stack.enter_context(patch.object(
            module, '_verify_market_urls', return_value=set()))
        return stack


def _assert_pool_deadline_session(testcase, kwargs, session=True):
    pool = kwargs.get('evidence_pool')
    testcase.assertIsNotNone(pool, kwargs)
    testcase.assertTrue(callable(getattr(pool, 'pages', None)))
    deadline = kwargs.get('deadline')
    testcase.assertIsInstance(deadline, (int, float), kwargs)
    testcase.assertGreater(deadline, time.time() - 60)
    if session:
        testcase.assertIsNotNone(kwargs.get('session'), kwargs)


class SummaryPoolWiringTests(unittest.TestCase):
    PAYLOAD = {'city': 'جدة', 'district': 'النرجس', 'projectType': 'سكني'}

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-pool.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_summary_runs_the_source_plan_then_browses(self):
        fx = _Fixture(pool_pages=[
            (_POOL_PAGE, 'مؤشر الإيجار التفصيلي',
             'جداول إيجار الوحدات حسب المدينة والحي')])
        module = self.application_module
        with self.app.app_context(), fx.patches(module):
            result = module._execute_market_summary(
                dict(self.PAYLOAD), tenant_id=None)
        self.assertTrue(result['success'], result)
        self.assertIn('plan', fx.events)
        self.assertIn('agent', fx.events)
        self.assertLess(fx.events.index('plan'), fx.events.index('agent'))

    def test_source_plan_runs_on_its_own_stage_budget(self):
        # The serial plan stage must not eat the browse agent's share of the
        # job budget — measured runs died at deadline after ~50 catalog
        # fetches stalled one timeout each. The plan gets a capped
        # sub-deadline, never the job's own.
        fx = _Fixture()
        module = self.application_module
        with self.app.app_context(), fx.patches(module):
            result = module._execute_market_summary(
                dict(self.PAYLOAD), tenant_id=None)
        self.assertTrue(result['success'], result)
        deadline = fx.plan_kwargs.get('deadline')
        self.assertIsInstance(deadline, (int, float), fx.plan_kwargs)
        self.assertGreater(deadline, time.time())
        self.assertLessEqual(
            deadline, time.time() + module._SOURCE_PLAN_TIME_BUDGET + 5)

    def test_summary_main_call_carries_pool_deadline_session(self):
        fx = _Fixture()
        module = self.application_module
        with self.app.app_context(), fx.patches(module):
            result = module._execute_market_summary(
                dict(self.PAYLOAD), tenant_id=None)
        self.assertTrue(result['success'], result)
        self.assertTrue(fx.agent_calls)
        for call in fx.agent_calls:
            _assert_pool_deadline_session(self, call['kwargs'])

    def test_summary_sources_union_pool_pages(self):
        fx = _Fixture(pool_pages=[
            (_POOL_PAGE, 'مؤشر الإيجار التفصيلي',
             'جداول إيجار الوحدات حسب المدينة والحي')])
        module = self.application_module
        with self.app.app_context(), fx.patches(module):
            result = module._execute_market_summary(
                dict(self.PAYLOAD), tenant_id=None)
        self.assertTrue(result['success'], result)
        urls = [str(row.get('url') or '') for row in result.get('sources') or []]
        # The bare sakani.sa homepage resolves to the pool's fetched dataset
        # page — proof the citation set unioned pool.pages(), not only the
        # agent's own annotations.
        self.assertIn(_POOL_PAGE, urls)


class SummaryChatPhaseBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-chat-pool.db')
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
        return {
            'axis': 'supply',
            'message': 'حدّث أرقام العرض بالربع الأخير',
            'research': 'auto',
            'history': [],
            'currentSummary': {'supply': 'نص العرض الحالي'},
            'currentSources': [],
            'currentSwot': {},
            'decision': '',
            'oneBlockSummary': '',
            'city': 'جدة',
            'district': 'النرجس',
            'projectType': 'سكني',
        }

    def test_phase_b_research_call_carries_pool_deadline_session(self):
        module = self.application_module
        fx = _Fixture()
        fx.payload = {'reply': 'وجدت أرقامًا', 'ops': []}

        def fake_chat(system, prompt, **kwargs):
            return _reply({'reply': 'أحتاج بحثًا', 'needs_research': True,
                           'queries': ['إيجار المتر حي النرجس'], 'ops': []})

        with self.app.app_context(), \
                patch.dict(os.environ, {'MARKET_CHAT_MODEL': 'm/chat'}), \
                patch.object(module, 'call_text_chat', side_effect=fake_chat), \
                fx.patches(module):
            result = module._execute_market_summary_chat(
                self._chat_data(), tenant_id=None)
        self.assertTrue(result['success'], result)
        self.assertTrue(fx.agent_calls, 'phase B never browsed')
        for call in fx.agent_calls:
            # Phase B is one call — the contract carries pool + deadline, no
            # shared session.
            _assert_pool_deadline_session(self, call['kwargs'], session=False)


class BestUseScanPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'best-use-pool.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_per_use_calls_share_one_pool(self):
        module = self.application_module
        fx = _Fixture()
        fx.payload = {'observations': []}
        fx.citation_pages = [('https://aqar.fm/p/scan', 'مسح أسعار',
                              'أسعار معروضة للحي')]
        draft = {'id': 'draft-scan',
                 'draft_data': {'city': 'جدة', 'district': 'النرجس'}}
        regulation = {'permittedUses': ['سكني', 'مكاتب']}
        with self.app.app_context(), fx.patches(module):
            module._best_use_scan_prices(draft, regulation, {})
        self.assertTrue(fx.agent_calls, 'the price scan never browsed')
        pools = {id(call['kwargs'].get('evidence_pool'))
                 for call in fx.agent_calls}
        # Every per-use call shares the job's one pool.
        self.assertNotIn(None, {call['kwargs'].get('evidence_pool')
                                for call in fx.agent_calls})
        self.assertEqual(len(pools), 1, fx.agent_calls)
        for call in fx.agent_calls:
            self.assertIsInstance(call['kwargs'].get('deadline'),
                                  (int, float), call['kwargs'])
            self.assertIsNotNone(call['kwargs'].get('session'),
                                 call['kwargs'])


_RESUMED_PAGE = 'https://ejar.sa/reports/previous-run'


class FailedJobResumeTests(unittest.TestCase):
    """A failed market job keeps the pages it already paid for, and the next
    same-draft run of the same kind starts with them in the pool instead of
    re-fetching — continuation after a deadline, not a restart."""

    PAYLOAD = {'city': 'جدة', 'district': 'النرجس', 'projectType': 'سكني'}

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'resume-pool.db')
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
        self.uploads = tempfile.TemporaryDirectory()
        self.addCleanup(self.uploads.cleanup)

    def _write_failed_job(self, tenant, job_id, draft_id, pages):
        module = self.application_module
        with patch.object(module, 'UPLOADS_DIR', self.uploads.name):
            module._write_market_job(tenant, job_id, {
                'status': 'failed',
                'success': False,
                'kind': 'summary',
                'payload': {'kind': 'summary', 'data': {'draftId': draft_id}},
                'evidencePages': list(pages),
            })

    def _capture_agent(self, fx, pools):
        def fake_agent(task, usage_ctx=None, **kwargs):
            pools.append(kwargs.get('evidence_pool'))
            return _reply(fx.payload, pages=fx.citation_pages)
        fx.fake_agent = fake_agent

    def test_failed_job_file_keeps_the_runs_evidence_pages(self):
        module = self.application_module
        fx = _Fixture()

        def failing_agent(task, usage_ctx=None, **kwargs):
            # The deadline case: the agent dies mid-run but the pages it
            # already fetched sit in the job's pool — they must survive.
            pool = kwargs.get('evidence_pool')
            if pool is not None:
                pool.add_page(_RESUMED_PAGE, title='تقرير إيجار قديم',
                              content='نص الصفحة المقروء')
            return {'error': {'message': 'deadline_exceeded'}}
        fx.fake_agent = failing_agent

        with patch.object(module, 'UPLOADS_DIR', self.uploads.name), \
                fx.patches(module):
            module._market_job_worker(
                self.app, 't-resume', 'summary',
                dict(self.PAYLOAD, draftId='d-1'), 'jobfail001')
            job = module._read_market_job('t-resume', 'jobfail001')

        self.assertIsNotNone(job)
        self.assertEqual(job.get('status'), 'failed')
        kept = [page.get('url') for page in job.get('evidencePages') or []]
        self.assertIn(_RESUMED_PAGE, kept)

    def test_next_same_draft_run_preloads_failed_evidence(self):
        module = self.application_module
        self._write_failed_job('t-resume', 'jobfail002', 'd-9', [{
            'url': _RESUMED_PAGE,
            'title': 'تقرير إيجار قديم',
            'content': 'نص الصفحة المقروء من المحاولة السابقة',
        }])
        fx = _Fixture()
        pools = []
        self._capture_agent(fx, pools)

        with self.app.app_context(), \
                patch.object(module, 'UPLOADS_DIR', self.uploads.name), \
                fx.patches(module):
            result = module._execute_market_summary(
                dict(self.PAYLOAD, draftId='d-9'), tenant_id='t-resume')

        self.assertTrue(result['success'], result)
        self.assertIsNone(result.get('evidencePages'))
        self.assertTrue(pools, 'the browse call never ran')
        urls = [page.get('url') for page in pools[0].pages()]
        self.assertIn(_RESUMED_PAGE, urls)

    def test_resume_never_crosses_into_another_draft(self):
        module = self.application_module
        self._write_failed_job('t-resume', 'jobfail003', 'd-9', [{
            'url': _RESUMED_PAGE, 'title': 'x', 'content': 'y',
        }])
        fx = _Fixture()
        pools = []
        self._capture_agent(fx, pools)

        with self.app.app_context(), \
                patch.object(module, 'UPLOADS_DIR', self.uploads.name), \
                fx.patches(module):
            result = module._execute_market_summary(
                dict(self.PAYLOAD, draftId='d-10'), tenant_id='t-resume')

        self.assertTrue(result['success'], result)
        self.assertTrue(pools)
        urls = [page.get('url') for page in pools[0].pages()]
        self.assertNotIn(_RESUMED_PAGE, urls)

    def test_stale_failed_jobs_are_not_resumed(self):
        module = self.application_module
        # Written by hand so `updatedAt` can sit beyond the resume window —
        # evidence from a day-old failure must not steer a fresh run.
        job_dir = os.path.join(self.uploads.name, '.market_jobs', 't-resume')
        os.makedirs(job_dir)
        with open(os.path.join(job_dir, 'jobstale01.json'), 'w',
                  encoding='utf-8') as fh:
            json.dump({
                'status': 'failed', 'success': False, 'kind': 'summary',
                'updatedAt': time.time() - 90000,
                'payload': {'kind': 'summary', 'data': {'draftId': 'd-9'}},
                'evidencePages': [{'url': _RESUMED_PAGE,
                                   'title': 'x', 'content': 'y'}],
            }, fh)
        fx = _Fixture()
        pools = []
        self._capture_agent(fx, pools)

        with self.app.app_context(), \
                patch.object(module, 'UPLOADS_DIR', self.uploads.name), \
                fx.patches(module):
            result = module._execute_market_summary(
                dict(self.PAYLOAD, draftId='d-9'), tenant_id='t-resume')

        self.assertTrue(result['success'], result)
        self.assertTrue(pools)
        urls = [page.get('url') for page in pools[0].pages()]
        self.assertNotIn(_RESUMED_PAGE, urls)


if __name__ == '__main__':
    unittest.main()
