"""Competitors-pipeline pool contract tests — search-rework board task A4.

``_execute_market_competitors`` stops letting every stage research alone: one
``EvidencePool``, one job deadline and one shared ``browser_session()`` are
created up front and flow through the deterministic ``run_source_plan`` pass
(known sources first) and into every ``_browse_agent_call`` (main, expansion,
verify last resort, logo discovery).

``_verify_competitor_rows`` becomes three phases — pool match (Python token
matching over already-retrieved pages, zero searches), deterministic search
(``web_search`` + top pages on the thread's browser for rows with no pool
evidence), and the browse-agent call as last resort only for rows still
evidence-free.

``_auto_import_competitor_logos`` pass 1.5 consumes ``pool.pages()``, and the
job result carries ``searchStats`` from ``pool.stats()``.

Contract and A0 rulings: docs/plans/مشكله البحث/plan.md. Zero network, zero
Chromium — ``agent.run_browse_agent`` (the flat-import seam), the browser
surface, the source plan, the URL probe and the logo store are all faked.

Run like every other suite — one suite per process, PYTHONPATH=repo root::

    python -m unittest tests.market.test_competitors_pipeline_pool
"""

import contextlib
import json
import os
import sys
import tempfile
import threading
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
import browser  # noqa: E402  modules/web_browse/browser.py
import db  # noqa: E402
import market_study  # noqa: E402

# ── fixtures ────────────────────────────────────────────────────────────────
# Four competitor rows, one per verification path:
#   روافد   — a pool page (fetched by run_source_plan) names it: verify from
#             evidence, zero searches.
#   الواجهة — nothing in the pool; the deterministic web_search+open round
#             retrieves a page naming it: verified without an agent call.
#   اللؤلؤ  — nothing in the pool or the deterministic search; the agent last
#             resort retrieves its page: verified through the old absorb path.
#   الواحة  — nothing anywhere; the last-resort answer retrieves a page that
#             does NOT name it: no_match, exactly like today.
ROAFED = 'مشروع روافد الياسمين'
WAJHA = 'برج الواجهة البحرية'
LU2 = 'مجمع اللؤلؤ السكني'
WAHA = 'مشروع الواحة النادر'

_ROAFED_PAGE = 'https://roafed.sa/projects/yasmeen'
_WAJHA_PAGE = 'https://sa.aqar.fm/projects/wajha-tower'
_LU2_PAGE = 'https://lu2.dev.sa/lu2-residence'

_MAIN_COMPETITORS = [
    {'name': ROAFED, 'city': 'جدة', 'project_type': 'سكني',
     'district': 'النرجس', 'operation_type': 'بيع',
     'distance_km': '2', 'benchmarks': ['سكني']},
    {'name': WAJHA, 'city': 'جدة', 'project_type': 'سكني',
     'district': 'النرجس', 'operation_type': 'إيجار',
     'distance_km': '5', 'benchmarks': ['سكني']},
    {'name': LU2, 'city': 'جدة', 'project_type': 'سكني',
     'district': 'النرجس', 'operation_type': 'بيع',
     'distance_km': '8', 'benchmarks': ['سكني']},
    {'name': WAHA, 'city': 'جدة', 'project_type': 'سكني',
     'district': 'النرجس', 'operation_type': 'بيع',
     'distance_km': '9', 'benchmarks': ['سكني']},
]


def _reply(payload, pages=()):
    """OpenRouter-shaped agent reply; ``pages`` are (url, title, content)."""
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
    """Shared/thread session stand-in: answers the deterministic search round
    for الواجهة and nothing else."""

    def __init__(self):
        self.searches = []
        self.opened = []
        self.closed = False
        self.is_open = True

    def web_search(self, query, max_results=8, **_kw):
        self.searches.append(str(query))
        if 'الواجهة' in str(query) or 'البحر' in str(query):
            return [{'title': 'برج الواجهة البحرية — تفاصيل المشروع',
                     'url': _WAJHA_PAGE, 'snippet': 'برج الواجهة البحرية في جدة'}]
        return []

    def open_url(self, url, timeout=20, **_kw):
        self.opened.append(str(url))
        if 'wajha' in str(url):
            return {'url': url, 'final_url': url,
                    'title': 'برج الواجهة البحرية — صفحة المشروع',
                    'text': ('برج الواجهة البحرية في جدة — شقق للإيجار، '
                             'الإيجار السنوي للوحدة 85000 ريال. ') * 20,
                    'error': None}
        return {'url': url, 'final_url': url, 'title': '', 'text': '',
                'error': 'not_found'}

    def close(self):
        self.closed = True
        self.is_open = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


class PipelineFixture:
    """Every seam the reworked pipeline touches, faked and recorded."""

    def __init__(self):
        self.worker = _FakeWorker()
        self.agent_calls = []       # [{'task','kwargs'}]
        self.events = []            # ordered 'plan' / 'agent' markers
        self.plan_thread = ''
        self.scan_threads = set()
        self.main_scan_barrier = None
        self.stored_logos = []

    def fake_agent(self, task, usage_ctx=None, **kwargs):
        self.agent_calls.append({'task': str(task), 'kwargs': dict(kwargs)})
        task = str(task)
        if 'المشروع العقاري «' in task:
            # Per-competitor verify prompt — the last resort. The name follows
            # the marker: the system prompt's own «…» quoting would otherwise
            # win the first-guillemet split.
            name = task.split('المشروع العقاري «', 1)[1].split('»', 1)[0]
            if 'اللؤلؤ' in name:
                return _reply(
                    {'exists': True,
                     'official_url': _LU2_PAGE,
                     'summary': 'مشروع سكني',
                     'price': {'type': '', 'value': '', 'from': '',
                               'to': '', 'url': ''}},
                    pages=[(_LU2_PAGE, 'مجمع اللؤلؤ السكني — الموقع الرسمي',
                            'مجمع اللؤلؤ السكني في جدة — سعر المتر 3500 ريال')])
            return _reply(
                {'exists': False, 'official_url': '', 'summary': '',
                 'price': {}},
                pages=[('https://unrelated.sa/article', 'مقال عام عن السوق',
                        'لا يذكر اسم المشروع المطلوب')])
        if 'الموقع الرسمي والشعار' in task:
            return _reply({'results': []})
        if 'ابحث عبر SearXNG عن:' in task:
            # Expansion round — finds nothing new.
            return _reply({'competitors': []}, pages=[
                ('https://aqar.fm/market/jeddah', 'سوق جدة العقاري',
                 'قراءة عامة عن مشاريع جدة السكنية')])
        if self.main_scan_barrier is not None:
            # Both axis scans must be in flight at the same time for this to
            # pass; a sequential implementation times out here.
            self.main_scan_barrier.wait()
        self.events.append('agent')
        self.scan_threads.add(threading.current_thread().name)
        return _reply({'competitors': _MAIN_COMPETITORS, 'notes': ''}, pages=[
            ('https://sa.aqar.fm/market/jeddah-north', 'مشاريع شمال جدة',
             'قائمة مشاريع سكنية في شمال جدة')])

    def fake_build_plan(self, payload, offer_lang='ar', **_kwargs):
        self.events.append('build_plan')
        return [{'purpose': 'deals',
                 'url': 'https://rei.rega.gov.sa/ar/advanced-search/deals',
                 'tier': 1, 'needs_browser': False, 'label': 'مؤشر الصفقات'}]

    def fake_run_plan(self, plan, pool=None, fetch_http=None, **kwargs):
        self.events.append('plan')
        self.plan_thread = threading.current_thread().name
        # The deterministic pass fetches the known official page naming روافد.
        pool.add_page(_ROAFED_PAGE,
                      title='مشروع روافد الياسمين — الموقع الرسمي',
                      content=('مشروع روافد الياسمين في جدة — وحدات سكنية، '
                               'سعر المتر 5200 ريال. ') * 20,
                      via='http')
        return {'fetched': 1, 'skipped': 0, 'failed': 0}

    @contextlib.contextmanager
    def fake_browser_session(self, *a, **kw):
        yield self.worker

    def fake_store_logo(self, row, draft_id=None, **kw):
        row['logo_file_id'] = 'logo-fake'
        self.stored_logos.append(str(row.get('name') or ''))
        return row

    def patches(self, module, store_logo=False):
        """Every fake, stacked. ``store_logo`` swaps the auto-logo import for
        the real function with a faked store (pool-consumption test)."""
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
        # The shared job session + the thread-bound pool workers.
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
        stack.enter_context(patch.object(
            module, '_read_market_source_page', return_value=('', 'x'),
            create=True))
        if store_logo:
            stack.enter_context(patch.object(
                module, '_store_imported_competitor_logo',
                side_effect=self.fake_store_logo, create=True))
        else:
            stack.enter_context(patch.object(
                module, '_auto_import_competitor_logos',
                return_value=None))
        return stack

    # -- assertions shared by tests ------------------------------------------
    def tasks_containing(self, needle):
        return [call['task'] for call in self.agent_calls
                if needle in call['task']]

    def verify_tasks_for(self, name):
        out = []
        for task in self.tasks_containing('المشروع العقاري «'):
            extracted = task.split('المشروع العقاري «', 1)[1].split('»', 1)[0]
            if name in extracted:
                out.append(task)
        return out

    def expansion_calls(self):
        return self.tasks_containing('ابحث عبر SearXNG عن:')


class CompetitorsPipelinePoolTests(unittest.TestCase):
    PAYLOAD = {'city': 'جدة', 'district': 'النرجس', 'projectType': 'سكني',
               'competitorScope': {'mode': 'district'},
               'comparisonTypes': [
                   {'type': 'residential', 'operation': 'sale'},
                   {'type': 'residential', 'operation': 'rent'}]}

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'pipeline-pool.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _run(self, fx, **extra):
        store_logo = extra.pop('_store_logo', False)
        data = dict(self.PAYLOAD)
        data.update(extra)
        with self.app.app_context(), fx.patches(
                self.application_module, store_logo=store_logo):
            return self.application_module._execute_market_competitors(
                data, tenant_id=None)

    def test_job_budget_defaults_to_one_hour_and_caps_at_two(self):
        budget = self.application_module._market_job_time_budget
        self.assertEqual(budget(None), 60 * 60)
        self.assertEqual(budget('900'), 900)
        self.assertEqual(budget('2400'), 2400)
        self.assertEqual(budget('999999'), 2 * 60 * 60)
        self.assertEqual(budget('invalid'), 60 * 60)

    # -- phase 1: pool match ---------------------------------------------------

    def test_pool_evidence_verifies_without_any_search_or_agent(self):
        fx = PipelineFixture()
        result = self._run(fx)
        self.assertTrue(result['success'], result)
        rows = {row['name']: row for row in result['competitors']}
        self.assertEqual(rows[ROAFED].get('verify_state'), 'verified')
        # The pool page never saw a search for this name.
        self.assertFalse(any('روافد' in q or 'الياسمين' in q
                             for q in fx.worker.searches),
                         fx.worker.searches)
        self.assertEqual(fx.verify_tasks_for('روافد'), [])

    # -- phase 2: deterministic search ----------------------------------------

    def test_deterministic_search_verifies_the_gap_row(self):
        fx = PipelineFixture()
        result = self._run(fx)
        rows = {row['name']: row for row in result['competitors']}
        self.assertEqual(rows[WAJHA].get('verify_state'), 'verified')
        # The deterministic round searched for the row's name + city and
        # opened the top hit — on the thread's browser, not a new agent call.
        self.assertTrue(any('الواجهة' in q or 'البحرية' in q
                            for q in fx.worker.searches),
                        fx.worker.searches)
        self.assertIn(_WAJHA_PAGE, fx.worker.opened)
        self.assertEqual(fx.verify_tasks_for('الواجهة'), [])

    # -- phase 3: agent last resort -------------------------------------------

    def test_agent_last_resort_only_for_evidence_free_rows(self):
        fx = PipelineFixture()
        result = self._run(fx)
        rows = {row['name']: row for row in result['competitors']}
        self.assertEqual(rows[LU2].get('verify_state'), 'verified')
        self.assertEqual(rows[WAHA].get('verify_state'), 'no_match')
        self.assertTrue(rows[WAHA].get('no_search_evidence'))
        # Exactly the two evidence-free rows paid an agent call.
        verify_names = [
            task.split('المشروع العقاري «', 1)[1].split('»', 1)[0]
            for task in fx.tasks_containing('المشروع العقاري «')]
        self.assertEqual(len(verify_names), 2, verify_names)
        self.assertTrue(any('اللؤلؤ' in name for name in verify_names))
        self.assertTrue(any('الواحة' in name for name in verify_names))

    # -- executor wiring -------------------------------------------------------

    def test_source_plan_runs_beside_the_parallel_axis_scans(self):
        fx = PipelineFixture()
        fx.main_scan_barrier = threading.Barrier(2, timeout=10)
        result = self._run(fx)
        self.assertTrue(result['success'], result)
        # The known-sources plan still runs, but no longer blocks the scans:
        # two comparison axes are in flight together (the barrier would time
        # out on a sequential run).
        self.assertIn('plan', fx.events)
        self.assertEqual(fx.events.count('agent'), 2, fx.events)
        self.assertTrue(fx.plan_thread.startswith('market-source-plan'),
                        fx.plan_thread)

    def test_single_axis_still_scans_twice_in_parallel(self):
        fx = PipelineFixture()
        fx.main_scan_barrier = threading.Barrier(2, timeout=10)
        result = self._run(fx, comparisonTypes=[
            {'type': 'residential', 'operation': 'sale'}])
        self.assertTrue(result['success'], result)
        # One comparison axis -> the axis scan plus its portal twin, both in
        # flight at once (the barrier fails a sequential implementation).
        self.assertEqual(fx.events.count('agent'), 2, fx.events)

    def test_pool_deadline_and_session_reach_every_agent_call(self):
        fx = PipelineFixture()
        result = self._run(fx)
        self.assertTrue(result['success'], result)
        self.assertTrue(fx.agent_calls)
        import time
        for call in fx.agent_calls:
            kwargs = call['kwargs']
            pool = kwargs.get('evidence_pool')
            self.assertIsNotNone(pool, kwargs)
            self.assertTrue(callable(getattr(pool, 'pages', None)))
            deadline = kwargs.get('deadline')
            self.assertIsInstance(deadline, (int, float), kwargs)
            self.assertGreater(deadline, time.time() - 60)
            self.assertIsNotNone(kwargs.get('session'), kwargs)

    def test_expansion_calls_carry_the_deadline(self):
        fx = PipelineFixture()
        with patch.object(self.application_module, '_pool_covers_angle',
                          return_value=False):
            result = self._run(fx)
        self.assertTrue(result['success'], result)
        # Four rows leave the selected sale axis short of five — an
        # expansion round fires and must carry the job deadline.
        self.assertTrue(fx.expansion_calls())
        import time
        for call in fx.agent_calls:
            if 'ابحث عبر SearXNG عن:' in call['task']:
                self.assertIsInstance(call['kwargs'].get('deadline'),
                                      (int, float), call['kwargs'])
                self.assertGreater(call['kwargs']['deadline'],
                                   time.time() - 60)

    def test_result_carries_search_stats(self):
        fx = PipelineFixture()
        result = self._run(fx)
        stats = result.get('searchStats')
        self.assertIsInstance(stats, dict, result)
        for key in ('queries', 'pages', 'pool_hits'):
            self.assertIn(key, stats)

    def test_pool_page_feeds_logo_import_without_a_new_search(self):
        fx = PipelineFixture()
        result = self._run(fx, _store_logo=True)
        rows = {row['name']: row for row in result['competitors']}
        # روافد's official page came from run_source_plan — it is the row's
        # logo source and its logo went through the store without any logo
        # discovery search for it.
        row = rows[ROAFED]
        self.assertEqual(str(row.get('logo_source_url') or ''), _ROAFED_PAGE)
        self.assertTrue(row.get('logo_official_verified'))
        self.assertIn(ROAFED, fx.stored_logos)

    def test_expired_deadline_stops_the_expansion_round(self):
        fx = PipelineFixture()
        # The env knob clamps to >=60s — drive the budget constant itself.
        with patch.object(
                self.application_module, '_MARKET_JOB_TIME_BUDGET', -1):
            result = self._run(fx)
        # Whatever the first call managed, no expansion round may fire when
        # the job deadline is already behind us.
        self.assertEqual(fx.expansion_calls(), [])
        self.assertIsInstance(result, dict)


class VerifyRowsDirectTests(unittest.TestCase):
    """``_verify_competitor_rows`` on its own — phases 2 and 3 still work when
    no shared pool is threaded in (the signature stays additive)."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'verify-direct.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_row_without_evidence_takes_the_agent_last_resort(self):
        module = self.application_module
        fx = PipelineFixture()
        rows = [{'name': LU2, 'operation_type': 'بيع', 'row_source': 'ai'}]
        with self.app.app_context(), fx.patches(module):
            module._verify_competitor_rows(
                rows, {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(rows[0].get('verify_state'), 'verified')
        self.assertTrue(fx.verify_tasks_for('اللؤلؤ'))

    def test_agent_failure_marks_search_not_run(self):
        module = self.application_module
        fx = PipelineFixture()
        rows = [{'name': WAHA, 'operation_type': 'بيع', 'row_source': 'ai'}]
        with self.app.app_context(), fx.patches(module), \
                patch.object(agent, 'run_browse_agent', return_value={
                    'error': {'message': 'browse_agent: launch_failed'},
                    'usage': {}, 'browse_trace': []}):
            module._verify_competitor_rows(
                rows, {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(rows[0].get('verify_state'), 'search_not_run')
        self.assertTrue(rows[0].get('verify_provider_error'))


if __name__ == '__main__':
    unittest.main()
