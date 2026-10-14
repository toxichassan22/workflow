"""Competitors pipeline over the shared evidence pool (worker board task A4).

The competitors job now owns one EvidencePool, one deadline and one shared
browser session for everything it fetches: the known-source plan runs before
the main browse call, expansion rounds skip angles the pool already covers,
and competitor verification becomes three phases — match stored pages, a
deterministic «name city» search feeding the pool, and the browse agent only
for rows still without evidence.

The dependency modules land on their own board tasks (A1 pool, A2 agent
params, A3 retrieval planner), so the doubles here implement the documented
contract surface — ``pages_for_name`` folds exactly like the real pool — and
the app-side code degrades to the previous behavior when they are absent. No
test touches the network or Chromium: browser surfaces and
``run_browse_agent`` are faked per the flat-import contract
(``patch.object(agent, 'run_browse_agent')``).

Run like every other suite::

    python -m unittest tests.market.test_competitors_evidence_pipeline
"""

import json
import os
import sys
import tempfile
import time
import types
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
import browser  # noqa: E402  modules/web_browse/browser.py
import evidence  # noqa: E402  modules/web_browse/evidence.py — the real pool
import market_study


class FakeEvidencePool:
    """Contract double for modules/web_browse/evidence.py — kept for tests
    that need to control matching beyond the real semantics (the executor's
    angle-coverage probe) or assert pool identity. Behavioral tests use the
    real ``evidence.EvidencePool``.

    folded-query dedupe (None=never ran, []=ran empty), page store merged by
    url, failure records, ``pages_for_name`` token matching and stats.
    """

    def __init__(self, pages=None):
        self._pages = {}
        self._queries = {}
        self._failed = {}
        self.pool_hits = 0
        for page in pages or []:
            self.add_page(page.get('url'), title=page.get('title') or '',
                          content=page.get('content') or '')

    def add_query(self, query, results):
        key = market_study._fold_choice(query)
        if key in self._queries:
            return 0
        self._queries[key] = list(results or [])
        return len(self._queries[key])

    def query_results(self, query):
        return self._queries.get(market_study._fold_choice(query))

    def add_page(self, url, title='', content='', final_url='', via='browser'):
        url = str(final_url or url or '').strip()
        if not url:
            return None
        page = self._pages.setdefault(url, {'url': url, 'title': '', 'content': ''})
        if title and not page['title']:
            page['title'] = str(title)
        if content:
            page['content'] = (page['content'] + '\n' + str(content)).strip()[:8000]
        return page

    def mark_failed(self, url, reason):
        self._failed[str(url)] = str(reason)

    def get_page(self, url):
        return self._pages.get(str(url).strip())

    def page_failed(self, url):
        return self._failed.get(str(url).strip())

    def pages(self):
        return list(self._pages.values())

    def pages_for_name(self, tokens, needed):
        hits = []
        for page in self._pages.values():
            haystack = market_study._fold_choice(
                f"{page.get('title') or ''} {page.get('url') or ''} {page.get('content') or ''}")
            if sum(1 for token in tokens
                   if market_study._fold_choice(token) in haystack) >= needed:
                hits.append(page)
        return hits

    def stats(self):
        return {'queries': len(self._queries), 'pages': len(self._pages),
                'pool_hits': self.pool_hits}


class _FakeWorker:
    """Browser surface for the shared-session / thread-local contracts."""

    def __init__(self, web_search=None, open_url=None):
        self._web_search = web_search
        self._open_url = open_url
        self.closed = False

    def web_search(self, query, max_results=8, **_kw):
        return list(self._web_search(query) if self._web_search else [])

    def open_url(self, url, timeout=20, **_kw):
        if self._open_url is not None:
            return self._open_url(url)
        return {'url': url, 'final_url': url, 'title': '', 'text': '', 'error': None}

    def close(self):
        self.closed = True


def _agent_reply(rows, urls, title='صفحة', content=''):
    """Browse-agent-shaped reply: JSON in content, opened pages as
    url_citation annotations (what _market_search_ran counts as executed
    research)."""
    return {
        'choices': [{'message': {
            'role': 'assistant',
            'content': json.dumps({'competitors': rows}, ensure_ascii=False),
            'annotations': [
                {'url_citation': {'url': url, 'title': title, 'content': content}}
                for url in urls],
        }}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        'browse_trace': [],
    }


# Name with two distinctive tokens (برج is generic filler) — the same folded
# tokens appear in the fixture page title/content, mirroring a real match.
_ROW = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع'}
_OFFICIAL_PAGE = {
    'url': 'https://almemar.sa/marqaa-narjis',
    'title': 'مشروع برج مرقاة النرجس — الموقع الرسمي',
    'content': 'تفاصيل مشروع برج مرقاة النرجس في الرياض — سعر الوحدة 850,000 ريال',
}
_LISTING_PAGE = {
    'url': 'https://wasalt.sa/listing/marqaa',
    'title': 'إعلان برج مرقاة النرجس',
    'content': 'وحدات مشروع مرقاة النرجس متاحة — السعر 850,000 ريال',
}


class _MarketTestBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, cls.__name__ + '.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()


class PoolVerifyPhaseTests(_MarketTestBase):
    """_verify_competitor_rows: pool match → deterministic search → agent."""

    def test_pool_evidence_verifies_row_without_agent(self):
        module = self.module
        pool = evidence.EvidencePool()
        pool.add_page(_OFFICIAL_PAGE['url'], title=_OFFICIAL_PAGE['title'],
                      content=_OFFICIAL_PAGE['content'])
        row = dict(_ROW)

        def forbidden(*_a, **_kw):
            raise AssertionError('no new search may run — the pool answered')

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call', side_effect=forbidden), \
                patch.object(agent, 'run_browse_agent', side_effect=forbidden), \
                patch.object(browser, 'web_search', side_effect=forbidden, create=True):
            module._verify_competitor_rows(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() + 300)

        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn(_OFFICIAL_PAGE['url'], row.get('source_urls') or [])
        # The page carries the whole name in its title on a non-aggregator
        # host — the row's official page, feeding the logo pass.
        self.assertEqual(row.get('logo_source_url'), _OFFICIAL_PAGE['url'])
        self.assertTrue(row.get('logo_official_verified'))
        # The price rides the retrieved page content, not the model's memory.
        self.assertEqual(str(row.get('price_value') or ''), '850000')

    def test_verify_price_keeps_its_source_currency(self):
        """A verify reply's EUR price lands with its currency — a Booking page
        priced in euros must not be dropped as «no price» nor relabeled SAR."""
        module = self.module
        row = {'name': 'فندق اختبار', 'operation_type': 'تشغيل فندقي'}
        module._apply_verified_competitor_price(
            row,
            {'price': {'type': 'سعر الليلة', 'value': '140', 'currency': 'يورو',
                       'url': 'https://booking.example/hotel'}},
            {'https://booking.example/hotel'})
        self.assertEqual(row['price_value'], '140')
        self.assertEqual(row['price_type'], 'سعر الليلة')
        self.assertEqual(row['price_currency'], 'EUR')
        self.assertIn('https://booking.example/hotel',
                      row['field_sources']['price_value'])

    def test_deterministic_search_fills_pool_then_verifies(self):
        module = self.module
        pool = evidence.EvidencePool()
        row = dict(_ROW)
        searches = []
        opened = []

        def fake_search(query, max_results=8, **_kw):
            searches.append(query)
            return [
                {'title': _LISTING_PAGE['title'], 'url': _LISTING_PAGE['url'],
                 'snippet': 'إعلان'},
                {'title': 'نتيجة أخرى', 'url': 'https://aqar.fm/x', 'snippet': ''},
            ]

        def fake_open(url, **_kw):
            opened.append(url)
            if url == _LISTING_PAGE['url']:
                return {'url': url, 'final_url': url,
                        'title': _LISTING_PAGE['title'],
                        'text': _LISTING_PAGE['content'], 'error': None}
            return {'url': url, 'final_url': url, 'title': '', 'text': '', 'error': 'timeout'}

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call',
                             side_effect=AssertionError('agent is the last resort, not the first')), \
                patch.object(browser, 'thread_local_browser',
                             lambda: _FakeWorker()), \
                patch.object(browser, 'web_search', side_effect=fake_search), \
                patch.object(browser, 'open_url', side_effect=fake_open):
            module._verify_competitor_rows(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() + 300)

        self.assertEqual(len(searches), 1)
        self.assertIn('مرقاة', searches[0])
        self.assertIn('الرياض', searches[0])
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn(_LISTING_PAGE['url'], row.get('source_urls') or [])
        # The fetched pages landed in the pool for every later stage.
        self.assertIsNotNone(pool.get_page(_LISTING_PAGE['url']))
        self.assertEqual(pool.page_failed('https://aqar.fm/x'), 'timeout')
        self.assertEqual(pool.stats()['queries'], 1)
        self.assertEqual(pool.stats()['pages'], 1)

    def test_agent_last_resort_for_evidence_free_row(self):
        module = self.module
        pool = evidence.EvidencePool()
        row = dict(_ROW)
        captured = {}
        worker = _FakeWorker(web_search=lambda _q: [])

        def fake_agent(task, **kwargs):
            captured.update(kwargs)
            return _agent_reply(
                [], [_LISTING_PAGE['url']],
                title=_LISTING_PAGE['title'], content=_LISTING_PAGE['content'])

        with self.app.app_context(), \
                patch.object(agent, 'run_browse_agent', new=fake_agent), \
                patch.object(browser, 'thread_local_browser',
                             lambda: worker), \
                patch.object(browser, 'close_thread_browser',
                             lambda: worker.close()), \
                patch.object(browser, 'web_search', return_value=[]):
            module._verify_competitor_rows(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() + 300)

        self.assertIn('evidence_pool', captured)
        self.assertIs(captured['evidence_pool'], pool)
        self.assertIn('deadline', captured)
        # The thread's own browser is the session — never a second launch.
        self.assertIs(captured.get('session'), worker)
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertIn(_LISTING_PAGE['url'], row.get('source_urls') or [])
        self.assertTrue(worker.closed)

    def test_deadline_exhausted_marks_search_not_run(self):
        module = self.module
        pool = evidence.EvidencePool()
        row = dict(_ROW)

        def forbidden(*_a, **_kw):
            raise AssertionError('deadline passed — nothing may launch')

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call', side_effect=forbidden), \
                patch.object(browser, 'web_search', side_effect=forbidden):
            module._verify_competitor_rows(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() - 1)

        self.assertEqual(row.get('verify_state'), 'search_not_run')
        self.assertEqual(row.get('verify_provider_error'), 'deadline_exceeded')

    def test_no_pool_keeps_the_agent_per_row_path(self):
        module = self.module
        row = dict(_ROW)
        captured = {}

        def fake_agent(task, **kwargs):
            captured.update(kwargs)
            return _agent_reply([], [_LISTING_PAGE['url']],
                                title=_LISTING_PAGE['title'],
                                content=_LISTING_PAGE['content'])

        worker = _FakeWorker()

        def no_search(*_a, **_kw):
            raise AssertionError('no deterministic phase without a pool')

        with self.app.app_context(), \
                patch.object(agent, 'run_browse_agent', new=fake_agent), \
                patch.object(browser, 'thread_local_browser', lambda: worker), \
                patch.object(browser, 'web_search', side_effect=no_search):
            module._verify_competitor_rows([row], {'city': 'الرياض'}, {})

        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertNotIn('evidence_pool', captured)
        # The thread's worker still reaches the agent as its session when the
        # signature accepts it — no pool does not mean no session reuse.
        self.assertIs(captured.get('session'), worker)


class ExecutorWiringTests(_MarketTestBase):
    """_execute_market_competitors threads pool/deadline/session everywhere."""

    def _payload(self):
        return {
            'projectType': 'متعدد الاستخدامات',
            'city': 'الرياض',
            'mode': 'generate',
            'components': [
                {'name': 'الشقق', 'useType': 'residential', 'investmentModel': 'sale'},
                {'name': 'الفندق', 'useType': 'hospitality', 'investmentModel': 'dailyRent'},
            ],
            'competitors': [],
        }

    def _residential_rows(self, count=5):
        return [{'name': f'برج سكني {index}', 'project_type': 'سكني',
                 'benchmarks': ['سكني']} for index in range(count)]

    def test_pool_deadline_session_reach_every_stage(self):
        module = self.module
        pool = FakeEvidencePool()
        worker = _FakeWorker()
        order = []
        calls = []
        verify_kwargs = {}
        logo_kwargs = {}
        fake_evidence = types.ModuleType('evidence')
        fake_evidence.EvidencePool = lambda: pool

        def fake_build(payload, offer_lang='ar'):
            order.append('build_plan')
            return [{'purpose': 'x', 'url': 'https://rei.rega.gov.sa/ar',
                     'tier': 1, 'needs_browser': False, 'label': 'مؤشرات'}]

        def fake_run(plan, the_pool, fetch_http, session=None, deadline=None,
                     report=None):
            order.append('run_plan')
            self.assertIs(the_pool, pool)
            self.assertIs(session, worker)
            self.assertIsNotNone(deadline)
            # The injected fetcher is the pinned-HTTPS reader, not raw HTTP.
            self.assertIs(fetch_http, module._market_source_fetch_http)
            return {'fetched': 1, 'skipped': 0, 'failed': 0}

        def fake_browse(system_prompt, user_prompt, usage_ctx=None, **kwargs):
            order.append('browse')
            calls.append(kwargs)
            return _agent_reply(self._residential_rows(5),
                                ['https://rei.rega.gov.sa/ar'])

        def fake_verify(rows, payload, data, tenant_id=None, progress=None, **kw):
            verify_kwargs.update(kw)

        def fake_logos(rows, payload, data, tenant_id=None, progress=None, **kw):
            logo_kwargs.update(kw)

        with self.app.app_context(), \
                patch.dict(sys.modules, {'evidence': fake_evidence}), \
                patch.object(browser, 'BrowserWorker', lambda: worker), \
                patch.object(market_study, 'build_source_plan', new=fake_build,
                             create=True), \
                patch.object(market_study, 'run_source_plan', new=fake_run,
                             create=True), \
                patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_verify_competitor_rows', side_effect=fake_verify), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', side_effect=fake_logos):
            result = module._execute_market_competitors(self._payload())

        self.assertTrue(result['success'], result)
        # The known-source plan executes strictly before the first browse call.
        self.assertEqual(order[:2], ['build_plan', 'run_plan'])
        self.assertEqual(order[2], 'browse')
        main_kwargs = calls[0]
        self.assertIs(main_kwargs.get('evidence_pool'), pool)
        self.assertIsInstance(main_kwargs.get('deadline'), float)
        self.assertIs(main_kwargs.get('session'), worker)
        self.assertIs(verify_kwargs.get('evidence_pool'), pool)
        self.assertIsNotNone(verify_kwargs.get('deadline'))
        self.assertIs(logo_kwargs.get('evidence_pool'), pool)
        self.assertIs(logo_kwargs.get('session'), worker)
        self.assertIsNotNone(logo_kwargs.get('deadline'))
        # Pool pages union into the citation trail the logo pass sees.
        self.assertIn('https://rei.rega.gov.sa/ar',
                      [p.get('url') for p in logo_kwargs.get('citation_pages') or []])
        self.assertEqual(result.get('searchStats'), pool.stats())

    def test_expansion_skips_angles_the_pool_covers(self):
        module = self.module
        # A pool whose pages already carry every angle's tokens — any new
        # browse call could only re-read stored pages.
        covering = FakeEvidencePool([{
            'url': 'https://aqar.fm/riyadh/all',
            'title': 'كل المشاريع',
            'content': ' '.join(['سكني', 'فندقي', 'فنادق', 'الرياض', 'مشاريع',
                                 'مطورين', 'مخطط', 'برج', 'مجمع', 'كمبوند',
                                 'احياء', 'المجاورة', 'كبار', 'قائمه', 'تحت',
                                 'الانشاء', 'افضل', 'اخبار', 'وجهه', 'قوائم']),
        }])
        # pages_for_name is contract-matched on tokens; broaden the double so
        # any angle reads as covered.
        covering.pages_for_name = lambda tokens, needed: covering.pages()
        covering.query_results = lambda query: None
        calls = []

        def fake_browse(system_prompt, user_prompt, usage_ctx=None, **kwargs):
            calls.append(kwargs)
            return _agent_reply(self._residential_rows(5),
                                ['https://rei.rega.gov.sa/ar'])

        fake_evidence = types.ModuleType('evidence')
        fake_evidence.EvidencePool = lambda: covering

        with self.app.app_context(), \
                patch.dict(sys.modules, {'evidence': fake_evidence}), \
                patch.object(browser, 'BrowserWorker', lambda: _FakeWorker()), \
                patch.object(module, '_run_market_source_plan', return_value=None), \
                patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(self._payload())

        self.assertTrue(result['success'], result)
        # The hotel axis is deficient but every angle is covered — no
        # expansion call fires.
        self.assertEqual(len(calls), 1)

    def test_expansion_stops_at_the_deadline_margin(self):
        module = self.module
        pool = FakeEvidencePool()
        calls = []
        fake_evidence = types.ModuleType('evidence')
        fake_evidence.EvidencePool = lambda: pool

        def fake_browse(system_prompt, user_prompt, usage_ctx=None, **kwargs):
            calls.append(kwargs)
            return _agent_reply(self._residential_rows(5),
                                ['https://rei.rega.gov.sa/ar'])

        with self.app.app_context(), \
                patch.dict(sys.modules, {'evidence': fake_evidence}), \
                patch.object(module, '_MARKET_JOB_TIME_BUDGET', -1), \
                patch.object(browser, 'BrowserWorker', lambda: _FakeWorker()), \
                patch.object(module, '_run_market_source_plan', return_value=None), \
                patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(self._payload())

        self.assertTrue(result['success'], result)
        self.assertEqual(len(calls), 1)

    def test_works_when_the_evidence_module_is_absent(self):
        """Pre-landing shape: no evidence module → no pool, calls behave as
        before, and the job result still carries the observability key."""
        module = self.module
        calls = []

        def fake_browse(system_prompt, user_prompt, usage_ctx=None, **kwargs):
            calls.append(kwargs)
            return _agent_reply(self._residential_rows(5),
                                ['https://rei.rega.gov.sa/ar'])

        with self.app.app_context(), \
                patch.dict(sys.modules, {'evidence': None}), \
                patch.object(browser, 'BrowserWorker', lambda: _FakeWorker()), \
                patch.object(module, '_browse_agent_call', side_effect=fake_browse), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(self._payload())

        self.assertTrue(result['success'], result)
        self.assertIsNone(result.get('searchStats'))
        self.assertIsNone(calls[0].get('evidence_pool'))


class BrowseAgentCallContractTests(_MarketTestBase):
    """_browse_agent_call forwards the new params only when the agent's
    signature carries them — both sides of the agent-layer landing stay
    correct."""

    def test_forwards_pool_deadline_session_when_accepted(self):
        module = self.module
        pool = FakeEvidencePool()
        captured = {}

        def fake_agent(task, **kwargs):
            captured.update(kwargs)
            return {'ok': True}

        with patch.object(agent, 'run_browse_agent', new=fake_agent):
            module._browse_agent_call(
                'sys', 'usr', None, evidence_pool=pool, deadline=123.0,
                session='SESSION', search_budget=2)
        self.assertIs(captured.get('evidence_pool'), pool)
        self.assertEqual(captured.get('deadline'), 123.0)
        self.assertEqual(captured.get('session'), 'SESSION')
        self.assertEqual(captured.get('search_budget'), 2)

    def test_drops_params_for_an_agent_without_them(self):
        module = self.module
        captured = {}

        def old_agent(task, max_steps=None, usage_ctx=None, search_budget=None,
                      max_tokens=None, reasoning_effort=None, model=None):
            captured.update({'search_budget': search_budget, 'model': model})
            return {'ok': True}

        with patch.object(agent, 'run_browse_agent', new=old_agent):
            res = module._browse_agent_call(
                'sys', 'usr', None, evidence_pool=FakeEvidencePool(),
                deadline=123.0, session='SESSION', search_budget=2)
        self.assertEqual(res, {'ok': True})
        self.assertEqual(captured.get('search_budget'), 2)

    def test_unset_params_are_not_forwarded(self):
        module = self.module
        captured = {}

        def fake_agent(task, **kwargs):
            captured.update(kwargs)
            return {'ok': True}

        with patch.object(agent, 'run_browse_agent', new=fake_agent):
            module._browse_agent_call('sys', 'usr', None, search_budget=4)
        self.assertNotIn('evidence_pool', captured)
        self.assertNotIn('deadline', captured)
        self.assertNotIn('session', captured)


class LogoPassPoolTests(_MarketTestBase):
    """_auto_import_competitor_logos consumes pool.pages() and the deadline."""

    def test_pool_page_satisfies_pass_15_without_a_search(self):
        module = self.module
        pool = evidence.EvidencePool()
        pool.add_page(_OFFICIAL_PAGE['url'], title=_OFFICIAL_PAGE['title'],
                      content=_OFFICIAL_PAGE['content'])
        row = dict(_ROW)

        def fake_store(row, draft_id=None):
            row['logo_file_id'] = 'f-logo'
            return row

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call',
                             side_effect=AssertionError('pool must answer first')), \
                patch.object(module, '_store_imported_competitor_logo',
                             side_effect=fake_store):
            module._auto_import_competitor_logos(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() + 300)

        self.assertEqual(row.get('logo_source_url'), _OFFICIAL_PAGE['url'])
        self.assertTrue(row.get('logo_official_verified'))
        self.assertEqual(row.get('logo_file_id'), 'f-logo')

    def test_batch_discovery_stops_at_the_deadline(self):
        module = self.module
        pool = evidence.EvidencePool()
        row = dict(_ROW)

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call',
                             side_effect=AssertionError('deadline passed')):
            module._auto_import_competitor_logos(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() - 1)

        self.assertIn('ميزانية', str(row.get('logo_import_warning') or ''))

    def test_batch_discovery_carries_pool_deadline_session(self):
        module = self.module
        pool = evidence.EvidencePool()
        row = dict(_ROW)
        captured = {}
        worker = _FakeWorker()

        def fake_browse(system_prompt, user_prompt, usage_ctx=None, **kwargs):
            captured.update(kwargs)
            return {'error': {'message': 'stop after capture'}}

        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call', side_effect=fake_browse):
            module._auto_import_competitor_logos(
                [row], {'city': 'الرياض'}, {}, evidence_pool=pool,
                deadline=time.time() + 300, session=worker)

        self.assertIs(captured.get('evidence_pool'), pool)
        self.assertIsNotNone(captured.get('deadline'))
        self.assertIs(captured.get('session'), worker)
        self.assertTrue(row.get('logo_import_warning'))


class VerifyProgressBandTests(_MarketTestBase):
    """The verify stage reports real movement: one tick per finished row and
    a narrated tool event while a row's own agent run is still browsing —
    the bar never sits frozen for the minutes a row search can take."""

    def test_verify_band_ticks_per_row_and_narrates_tool_events(self):
        module = self.module
        rows = [{'name': 'منافس أول'}, {'name': 'منافس ثاني'}]
        progress = []

        def fake_pooled(row, payload, data, tenant_id=None, evidence_pool=None,
                        deadline=None, on_event=None):
            if callable(on_event):
                on_event({'phase': 'tool', 'tool': 'web_search',
                          'hint': 'استعلام تجريبي', 'step': 1,
                          'max_steps': 8})

        with self.app.app_context(), \
                patch.object(module, '_verify_competitor_row_pooled',
                             side_effect=fake_pooled):
            module._verify_competitor_rows(
                rows, {}, {}, progress=lambda p, m: progress.append((p, m)),
                evidence_pool=None, deadline=None, band=(52, 70))

        pcts = [pct for pct, _msg in progress]
        self.assertTrue(pcts)
        self.assertTrue(all(52 <= pct <= 70 for pct in pcts), pcts)
        # Two finished rows land the band's end; tool events narrate between.
        self.assertEqual(pcts[-1], 70)
        tool_msgs = [msg for _pct, msg in progress if 'يبحث عن' in msg]
        self.assertTrue(tool_msgs)
        self.assertIn('استعلام تجريبي', tool_msgs[0])
        tick_msgs = [msg for _pct, msg in progress if 'من 2' in msg]
        self.assertEqual(len(tick_msgs), 2)

    def test_agent_progress_maps_events_onto_the_stage_band(self):
        module = self.module
        progress = []
        report = lambda p, m: progress.append((p, m))
        on_event = module._market_agent_progress(report, 22, 40, 'البحث الرئيسي')

        on_event({'phase': 'round', 'step': 1, 'max_steps': 20})
        on_event({'phase': 'tool', 'step': 10, 'max_steps': 20,
                  'tool': 'web_search', 'hint': 'فنادق الأندلس'})
        on_event({'phase': 'tool_done', 'step': 10, 'max_steps': 20,
                  'tool': 'open_url', 'hint': 'https://x.sa', 'ok': False})
        on_event({'phase': 'done', 'ok': True})

        pcts = [pct for pct, _msg in progress]
        self.assertEqual(pcts, sorted(pcts))
        self.assertTrue(all(22 <= pct <= 40 for pct in pcts), pcts)
        self.assertIn('يبحث في الويب عن «فنادق الأندلس»', progress[1][1])
        self.assertIn('تعذّر', progress[2][1])


if __name__ == '__main__':
    unittest.main()
