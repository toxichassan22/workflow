"""Deterministic retrieval planner for the market jobs (task A3).

build_source_plan() turns the source catalog (SOURCE_PRIORITY /
TYPE_SOURCE_PRIORITY / _PORTAL_DATASET_PAGES) plus the project's city into an
ordered list of concrete URLs the job reads before any free-form web search;
run_source_plan() executes it into the job's shared evidence pool — HTTP
first, the caller's browser session only for SPA/bot-walled targets or pages
whose fetched text is too thin to count as evidence. The module does no
network I/O: the fetcher and the browser session are injected fakes here.

Run like every other suite from the repo root::

    PYTHONPATH=. python -m unittest tests.market.test_retrieval_plan
"""

import sys
import time
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _p in (str(ROOT), str(_WEB_BROWSE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_study


class _FakePool:
    """The EvidencePool contract surface run_source_plan() consumes."""

    def __init__(self):
        self.pages_by_url = {}
        self.failures = {}
        self.added = []

    def add_page(self, url, title='', content='', final_url='', via='browser'):
        final = str(final_url or url).strip()
        page = self.pages_by_url.get(final) or {'url': final, 'title': '', 'content': ''}
        if title and not page['title']:
            page['title'] = title
        if content:
            page['content'] = content
        self.pages_by_url[final] = page
        if url != final:
            self.pages_by_url[url] = page
        self.added.append({'url': url, 'final_url': final, 'via': via,
                           'title': title, 'content': content})

    def get_page(self, url):
        return self.pages_by_url.get(url)

    def mark_failed(self, url, reason):
        self.failures[url] = reason

    def page_failed(self, url):
        return self.failures.get(url)

    def pages(self):
        return list({id(page): page for page in self.pages_by_url.values()}.values())


class _FakeBrowser:
    """BrowserWorker-shaped session stub — records opened URLs."""

    def __init__(self, results=None):
        self.results = results or {}
        self.opened = []

    def open_url(self, url, timeout=None):
        self.opened.append(url)
        result = self.results.get(url)
        if result is None:
            return {'url': url, 'final_url': url, 'title': '', 'text': '',
                    'error': None}
        return dict(result)


def _entry(url, purpose='catalog', tier=1, needs_browser=False, label=''):
    return {'purpose': purpose, 'url': url, 'tier': tier,
            'needs_browser': needs_browser, 'label': label}


def _big_html(marker='مؤشرات'):
    body = f'{marker} صفقة سعر متر إيجار ' * 90
    return f'<html><head><title>صفحة مصدر</title></head><body>{body}</body></html>'


def _big_text():
    return 'نص الصفحة الكامل ' * 120


class BuildSourcePlanTests(unittest.TestCase):

    def test_names_catalog_deep_links_for_the_project_type(self):
        plan = market_study.build_source_plan(
            {'projectType': 'سكني', 'city': 'الرياض'})
        urls = [entry['url'] for entry in plan]
        for expected in (
                'https://rei.rega.gov.sa/ar/cities/%D8%A7%D9%84%D8%B1%D9%8A%D8%A7%D8%B6',
                'https://sakani.sa/reports-and-data',
                'https://jll.com/en-sa'):
            self.assertIn(expected, urls)
        # Bare homepages are nav shells — a fetch on one burns a page
        # timeout for zero district evidence, so the plan never prefetches
        # them even though the catalog lines still steer the free search.
        for homepage in (
                'https://rei.rega.gov.sa', 'https://stats.gov.sa',
                'https://sama.gov.sa', 'https://ejar.sa', 'https://nhc.sa',
                'https://cbre.sa'):
            self.assertNotIn(homepage, urls)

    def test_plan_prefetches_no_bare_homepages(self):
        # Regression for the measured 47-failure plan stage: a catalog line
        # names a source family, but its domain's bare homepage is a nav
        # shell — only deep links may be prefetched.
        for payload in ({'projectType': 'فندقي', 'city': 'جدة'},
                        {'projectType': 'سكني', 'city': 'الرياض'},
                        {'projectType': 'صناعي ولوجستي', 'city': 'الدمام'}):
            plan = market_study.build_source_plan(payload)
            for entry in plan:
                self.assertFalse(
                    market_study.is_generic_source_homepage(entry['url']),
                    entry['url'])
            purposes = {entry['purpose'] for entry in plan}
            self.assertIn('dataset', purposes)
            self.assertIn('listing', purposes)

    def test_dataset_expansion_entries_are_browser_bound(self):
        plan = market_study.build_source_plan(
            {'projectType': 'سكني', 'city': 'الرياض'})
        city_page = next(entry for entry in plan if '/ar/cities/' in entry['url'])
        self.assertEqual(city_page['purpose'], 'dataset')
        self.assertEqual(city_page['tier'], 1)
        self.assertTrue(city_page['needs_browser'])

    def test_gated_advanced_search_pages_are_never_planned(self):
        # rei.rega.gov.sa/ar/advanced-search/* sits behind Nafath login — the
        # browser only ever reads a login shell there. The plan must carry the
        # public city page instead and never waste a fetch on the gated grids.
        plan = market_study.build_source_plan(
            {'projectType': 'سكني', 'city': 'جدة'})
        urls = [entry['url'] for entry in plan]
        self.assertFalse(any('/advanced-search' in url for url in urls))
        decoded = [unquote(url) for url in urls]
        self.assertTrue(any(
            u == 'https://rei.rega.gov.sa/ar/cities/جدة' for u in decoded))

    def test_listing_urls_scoped_to_the_city_and_browser_bound(self):
        plan = market_study.build_source_plan(
            {'projectType': 'سكني', 'city': 'جدة'})
        listings = [entry for entry in plan if entry['purpose'] == 'listing']
        self.assertTrue(listings)
        self.assertTrue(all(entry['needs_browser'] for entry in listings))
        decoded = [unquote(entry['url']) for entry in listings]
        self.assertTrue(any(u.startswith('https://sa.aqar.fm/')
                            and 'شقق-للبيع/جدة' in u for u in decoded))
        self.assertTrue(any(u.startswith('https://sa.aqar.fm/')
                            and 'شقق-للإيجار/جدة' in u for u in decoded))
        # Owner rule: aqar.fm is the only classifieds portal — no bayut,
        # wasalt or dealapp anywhere in the plan (catalog or generated).
        urls = [entry['url'] for entry in plan]
        self.assertFalse(any(host in url for url in urls
                             for host in ('bayut.sa', 'wasalt.sa', 'dealapp.sa')))

    def test_spa_gov_sa_is_never_planned(self):
        # spa.gov.sa's homepage reads as a shell and its non-/ar/ article
        # paths hang past the navigation timeout — measured, not guessed — so
        # the plan must not schedule a fetch on it.
        plan = market_study.build_source_plan(
            {'projectType': 'سكني', 'city': 'جدة'})
        urls = [entry['url'] for entry in plan]
        self.assertFalse(any('spa.gov.sa' in url for url in urls))

    def test_mixed_use_pulls_every_component_kind_sources(self):
        plan = market_study.build_source_plan(
            {'projectType': 'متعدد الاستخدامات',
             'projectComponents': 'سكني، مكاتب', 'city': 'الرياض'})
        # 'مكاتب' folds onto the commercial kind — its office listing
        # category exists only because that component's sources ran.
        decoded = [unquote(entry['url']) for entry in plan]
        self.assertTrue(any('مكاتب-' in u for u in decoded))

    def test_sale_only_project_skips_rent_listings(self):
        payload = {'projectType': 'سكني', 'city': 'الرياض',
                   'components': [{'useType': 'residential',
                                   'investmentModel': 'sale'}]}
        urls = [unquote(entry['url']) for entry in
                market_study.build_source_plan(payload)
                if entry['purpose'] == 'listing']
        self.assertTrue(urls)
        self.assertTrue(all('للإيجار' not in u and 'rent' not in u
                            for u in urls))

    def test_plan_entries_carry_the_contract_fields_sorted_by_tier(self):
        plan = market_study.build_source_plan(
            {'projectType': 'فندقي', 'city': 'مكة'})
        self.assertTrue(plan)
        for entry in plan:
            self.assertEqual(
                sorted(entry),
                ['label', 'needs_browser', 'purpose', 'tier', 'url'])
        tiers = [entry['tier'] for entry in plan]
        self.assertEqual(tiers, sorted(tiers))
        urls = [entry['url'] for entry in plan]
        self.assertEqual(len(urls), len(set(urls)))
        # Maps is a shell for text evidence — never planned.
        self.assertFalse(any('google.com' in u for u in urls))


class RunSourcePlanTests(unittest.TestCase):

    def test_http_fetch_stores_pages_in_the_pool(self):
        pool = _FakePool()
        calls = []
        counts = market_study.run_source_plan(
            [_entry('https://stats.gov.sa/x'), _entry('https://sama.gov.sa/y')],
            pool, lambda url: (calls.append(url) or (_big_html(), '')))
        self.assertEqual(counts, {'fetched': 2, 'skipped': 0, 'failed': 0})
        self.assertEqual(len(calls), 2)
        page = pool.get_page('https://stats.gov.sa/x')
        self.assertIsNotNone(page)
        self.assertIn('مؤشرات', page['content'])
        self.assertEqual(page['title'], 'صفحة مصدر')
        self.assertEqual(pool.added[0]['via'], 'http')

    def test_skips_urls_the_pool_already_holds(self):
        pool = _FakePool()
        pool.add_page('https://a.test/done', content='x' * 900)
        pool.mark_failed('https://b.test/dead', 'HTTP 403')
        calls = []
        counts = market_study.run_source_plan(
            [_entry('https://a.test/done'), _entry('https://b.test/dead'),
             _entry('https://c.test/new')],
            pool, lambda url: (calls.append(url) or (_big_html(), '')))
        self.assertEqual(counts, {'fetched': 1, 'skipped': 2, 'failed': 0})
        self.assertEqual(calls, ['https://c.test/new'])

    def test_needs_browser_never_touches_http_fetch(self):
        pool = _FakePool()
        calls = []
        session = _FakeBrowser({
            'https://aqar.fm/listings': {'url': 'https://aqar.fm/listings',
                                         'final_url': 'https://aqar.fm/listings',
                                         'title': 'aqar', 'text': _big_text(),
                                         'error': None}})
        counts = market_study.run_source_plan(
            [_entry('https://aqar.fm/listings', needs_browser=True)],
            pool, lambda url: (calls.append(url) or (_big_html(), '')),
            session=session)
        self.assertEqual(counts, {'fetched': 1, 'skipped': 0, 'failed': 0})
        self.assertEqual(calls, [])
        self.assertEqual(session.opened, ['https://aqar.fm/listings'])
        self.assertEqual(pool.added[0]['via'], 'browser')

    def test_thin_http_text_falls_back_to_the_browser(self):
        pool = _FakePool()
        session = _FakeBrowser({
            'https://p.test/spa': {'url': 'https://p.test/spa',
                                   'final_url': 'https://p.test/spa',
                                   'title': 't', 'text': _big_text(),
                                   'error': None}})
        counts = market_study.run_source_plan(
            [_entry('https://p.test/spa')], pool,
            lambda url: ('<html><body>nav only</body></html>', ''),
            session=session)
        self.assertEqual(counts, {'fetched': 1, 'skipped': 0, 'failed': 0})
        self.assertEqual(session.opened, ['https://p.test/spa'])
        self.assertEqual(pool.added[0]['via'], 'browser')

    def test_spa_shell_is_marked_needs_interaction_not_a_click_loop(self):
        pool = _FakePool()
        session = _FakeBrowser()   # every open returns an empty shell
        counts = market_study.run_source_plan(
            [_entry('https://rei.rega.gov.sa/ar/advanced-search/deals',
                    needs_browser=True)],
            pool, lambda url: ('', 'should not run'), session=session)
        self.assertEqual(counts, {'fetched': 0, 'skipped': 0, 'failed': 1})
        self.assertEqual(pool.page_failed(
            'https://rei.rega.gov.sa/ar/advanced-search/deals'),
            'needs_interaction')

    def test_http_error_marks_failed_without_browser_retry(self):
        pool = _FakePool()
        session = _FakeBrowser()
        counts = market_study.run_source_plan(
            [_entry('https://x.test/blocked')], pool,
            lambda url: ('', 'HTTP 403'), session=session)
        self.assertEqual(counts, {'fetched': 0, 'skipped': 0, 'failed': 1})
        self.assertEqual(pool.page_failed('https://x.test/blocked'), 'HTTP 403')
        self.assertEqual(session.opened, [])

    def test_needs_browser_without_a_session_is_browser_unavailable(self):
        pool = _FakePool()
        counts = market_study.run_source_plan(
            [_entry('https://aqar.fm/listings', needs_browser=True)],
            pool, lambda url: (_big_html(), ''))
        self.assertEqual(counts['failed'], 1)
        self.assertEqual(pool.page_failed('https://aqar.fm/listings'),
                         'browser_unavailable')

    def test_deadline_stops_the_run_before_any_fetch(self):
        pool = _FakePool()
        calls = []
        session = _FakeBrowser()
        counts = market_study.run_source_plan(
            [_entry('https://a.test/1'), _entry('https://b.test/2',
                                              needs_browser=True)],
            pool, lambda url: (calls.append(url) or (_big_html(), '')),
            session=session, deadline=time.time() - 1)
        self.assertEqual(counts, {'fetched': 0, 'skipped': 0, 'failed': 0})
        self.assertEqual(calls, [])
        self.assertEqual(session.opened, [])

    def test_report_receives_per_entry_events(self):
        pool = _FakePool()
        events = []
        market_study.run_source_plan(
            [_entry('https://a.test/ok')], pool,
            lambda url: (_big_html(), ''),
            report=events.append)
        self.assertEqual(events[0]['status'], 'fetched')
        self.assertEqual(events[0]['via'], 'http')
        self.assertEqual(events[0]['url'], 'https://a.test/ok')

    def test_entries_run_tier_first_regardless_of_input_order(self):
        pool = _FakePool()
        calls = []
        market_study.run_source_plan(
            [_entry('https://late.test/x', tier=4),
             _entry('https://early.test/y', tier=1)],
            pool, lambda url: (calls.append(url) or (_big_html(), '')))
        self.assertEqual(calls, ['https://early.test/y', 'https://late.test/x'])

    def test_report_falls_back_to_the_pct_msg_progress_shape(self):
        pool = _FakePool()
        progress = []
        market_study.run_source_plan(
            [_entry('https://a.test/ok', label='مؤشر')], pool,
            lambda url: (_big_html(), ''),
            report=lambda pct, msg: progress.append((pct, msg)))
        self.assertEqual(progress[0][0], 18)
        self.assertIn('مؤشر', progress[0][1])


class RealPoolIntegrationTests(unittest.TestCase):
    """run_source_plan against the real web_browse EvidencePool — the same
    object the job wires in, not a fake of the contract."""

    @classmethod
    def setUpClass(cls):
        try:
            import evidence
            cls.evidence = evidence
        except ImportError:
            raise unittest.SkipTest('modules/web_browse/evidence.py not landed')

    def test_fetches_into_and_dedupes_against_the_real_pool(self):
        pool = self.evidence.EvidencePool()
        plan = [_entry('https://stats.gov.sa/a'), _entry('https://sama.gov.sa/b')]
        counts = market_study.run_source_plan(
            plan, pool, lambda url: (_big_html(), ''))
        self.assertEqual(counts, {'fetched': 2, 'skipped': 0, 'failed': 0})
        self.assertEqual(pool.stats()['pages'], 2)
        # Second run: every URL is already evidence — nothing refetches.
        calls = []
        counts = market_study.run_source_plan(
            plan, pool, lambda url: (calls.append(url) or (_big_html(), '')))
        self.assertEqual(counts['skipped'], 2)
        self.assertEqual(calls, [])

    def test_recorded_failures_are_skipped_on_the_real_pool(self):
        pool = self.evidence.EvidencePool()
        pool.mark_failed('https://dead.test/x', 'HTTP 403')
        calls = []
        counts = market_study.run_source_plan(
            [_entry('https://dead.test/x')], pool,
            lambda url: (calls.append(url) or (_big_html(), '')))
        self.assertEqual(counts['skipped'], 1)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
