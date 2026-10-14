"""EvidencePool — the shared per-job evidence store behind the market
search rework (docs/plans/مشكله البحث/plan.md, task A1).

One pool per job is shared by every browse call and fetch: folded queries
never run twice, pages dedupe under their final_url, failures are recorded
so nothing is retried blindly, and name matching folds Arabic variants the
same way _competitor_name_tokens does upstream. The module is pure stdlib
and standalone — it must never import market_study, Flask or the network.

Run like every other suite::

    python -m unittest tests.market.test_evidence_pool
"""

import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _p in (str(ROOT), str(_WEB_BROWSE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import evidence  # noqa: E402  modules/web_browse/evidence.py


class EvidencePoolContractTests(unittest.TestCase):

    def setUp(self):
        self.pool = evidence.EvidencePool()

    # ------------------------------------------------------------------
    # Standalone module contract
    # ------------------------------------------------------------------
    def test_module_is_standalone(self):
        source = (ROOT / 'modules' / 'web_browse' / 'evidence.py').read_text(
            encoding='utf-8')
        self.assertNotRegex(source, r'^\s*(import|from)\s+market_study')

        self.assertNotRegex(source, r'^\s*(import|from)\s+db\b')
        self.assertNotRegex(source.lower(), r'^\s*(import|from)\s+flask\b')
        self.assertEqual(evidence.EvidencePool.PAGE_TEXT_CAP, 8000)
        self.assertEqual(evidence.EvidencePool.MAX_PAGES, 250)

    def test_contract_surface(self):
        for name in ('add_query', 'query_results', 'add_page', 'mark_failed',
                     'get_page', 'page_failed', 'pages', 'pages_for_name',
                     'stats', 'to_dict', 'from_dict'):
            self.assertTrue(callable(getattr(self.pool, name, None)), name)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def test_add_query_stores_and_reports_count(self):
        results = [{'title': 'صفحة', 'url': 'https://a.example/1',
                    'snippet': 'مقتطف'}, {'title': 't2', 'url': 'u2',
                    'snippet': 's2'}]
        self.assertEqual(self.pool.add_query('منافسون جدة', results), 2)
        self.assertEqual(self.pool.stats()['queries'], 1)

    def test_add_query_dedupes_folded_query(self):
        first = [{'title': 't', 'url': 'u', 'snippet': 's'}]
        self.assertEqual(self.pool.add_query('دراسة السوق', first), 1)
        # Same query under folding: collapsed whitespace, casefold, alef fold.
        self.assertEqual(self.pool.add_query('  دراسة  السوق ', first), 0)
        self.assertEqual(self.pool.add_query('أداء السوق', first), 1)
        self.assertEqual(self.pool.add_query('اداء السوق', first), 0)
        self.assertEqual(self.pool.stats()['queries'], 2)

    def test_add_query_folds_ya_and_tatweel(self):
        first = [{'title': 't', 'url': 'u', 'snippet': 's'}]
        self.assertEqual(self.pool.add_query('مؤشر عقاري', first), 1)
        # ى→ي and tatweel are the same query — not stored again.
        self.assertEqual(self.pool.add_query('مؤشر عقارى', first), 0)
        self.assertEqual(self.pool.add_query('مـؤشر عقاري', first), 0)
        self.assertEqual(self.pool.stats()['queries'], 1)

    def test_query_results_none_empty_and_hit(self):
        self.assertIsNone(self.pool.query_results('لم تُنفَّذ'))
        self.pool.add_query('استعلام بلا نتائج', [])
        self.assertEqual(self.pool.query_results('استعلام بلا نتائج'), [])
        self.pool.add_query('استعلام', [{'title': 't', 'url': 'u',
                                         'snippet': 's'}])
        got = self.pool.query_results('استعلام')
        self.assertEqual(got, [{'title': 't', 'url': 'u', 'snippet': 's'}])
        # Returned copies — mutating them must not corrupt the pool.
        got[0]['title'] = 'مُعدَّل'
        self.assertEqual(self.pool.query_results('استعلام')[0]['title'], 't')

    def test_query_results_counts_pool_hits_only_on_hits(self):
        self.pool.add_query('q', [])
        self.pool.query_results('q')
        self.pool.query_results('q')
        self.pool.query_results('never ran')
        self.assertEqual(self.pool.stats()['pool_hits'], 2)

    def test_add_query_compacts_result_shape(self):
        stored = self.pool.add_query('q', [
            {'title': 't', 'url': 'u', 'snippet': 's', 'extra': 'dropped'},
            'not-a-dict',
            {'title': None, 'url': 5},
        ])
        self.assertEqual(stored, 2)
        got = self.pool.query_results('q')
        self.assertEqual(got, [{'title': 't', 'url': 'u', 'snippet': 's'},
                               {'title': '', 'url': '5', 'snippet': ''}])

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def test_add_page_dedupes_by_final_url(self):
        self.pool.add_page('https://a.example/short', title='صفحة',
                           content='نص', final_url='https://a.example/final')
        self.pool.add_page('https://a.example/other', title='أخرى',
                           content='أكثر', final_url='https://a.example/final')
        pages = self.pool.pages()
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]['url'], 'https://a.example/final')
        self.assertEqual(pages[0]['title'], 'صفحة')  # first non-empty wins
        self.assertIn('نص', pages[0]['content'])
        self.assertIn('أكثر', pages[0]['content'])

    def test_add_page_falls_back_to_requested_url(self):
        self.pool.add_page('https://a.example/x', content='c')
        self.assertEqual(self.pool.pages()[0]['url'], 'https://a.example/x')

    def test_get_page_resolves_requested_url_to_final(self):
        self.pool.add_page('https://a.example/requested', title='t',
                           content='c', final_url='https://a.example/final')
        self.assertIsNotNone(self.pool.get_page('https://a.example/requested'))
        self.assertIsNotNone(self.pool.get_page('https://a.example/final'))
        self.assertIsNone(self.pool.get_page('https://a.example/missing'))

    def test_pages_emit_citation_shape(self):
        self.pool.add_page('https://a.example/1', title='t', content='c',
                           via='http')
        self.pool.add_page('https://a.example/2', title='t2', content='c2')
        pages = self.pool.pages()
        self.assertEqual(len(pages), 2)
        for page in pages:
            self.assertEqual(set(page.keys()), {'url', 'title', 'content'})
        self.assertEqual([p['url'] for p in pages],
                         ['https://a.example/1', 'https://a.example/2'])

    def test_get_page_returns_public_shape(self):
        self.pool.add_page('https://a.example/1', title='t', content='c')
        self.assertEqual(set(self.pool.get_page('https://a.example/1').keys()),
                         {'url', 'title', 'content'})

    def test_page_content_capped(self):
        self.pool.add_page('https://a.example/1', content='x' * 9000)
        self.assertEqual(len(self.pool.get_page('https://a.example/1')['content']),
                         evidence.EvidencePool.PAGE_TEXT_CAP)

    def test_eviction_drops_oldest_page_and_its_aliases(self):
        class TinyPool(evidence.EvidencePool):
            MAX_PAGES = 3
        pool = TinyPool()
        pool.add_page('https://a.example/1-req', content='1',
                      final_url='https://a.example/1')
        pool.add_page('https://a.example/2', content='2')
        pool.add_page('https://a.example/3', content='3')
        pool.add_page('https://a.example/4', content='4')
        self.assertIsNone(pool.get_page('https://a.example/1'))
        self.assertIsNone(pool.get_page('https://a.example/1-req'))
        self.assertEqual([p['url'] for p in pool.pages()],
                         ['https://a.example/2', 'https://a.example/3',
                          'https://a.example/4'])

    # ------------------------------------------------------------------
    # Failures
    # ------------------------------------------------------------------
    def test_mark_failed_records_reason(self):
        self.pool.mark_failed('https://a.example/spa', 'needs_interaction')
        self.assertEqual(self.pool.page_failed('https://a.example/spa'),
                         'needs_interaction')
        self.assertIsNone(self.pool.page_failed('https://a.example/other'))

    def test_mark_failed_ignored_when_page_exists(self):
        self.pool.add_page('https://a.example/1', content='c')
        self.pool.mark_failed('https://a.example/1', 'timeout')
        self.assertIsNone(self.pool.page_failed('https://a.example/1'))

    def test_add_page_clears_prior_failure(self):
        self.pool.mark_failed('https://a.example/1', 'timeout')
        self.pool.add_page('https://a.example/1', content='c')
        self.assertIsNone(self.pool.page_failed('https://a.example/1'))

    # ------------------------------------------------------------------
    # Name matching
    # ------------------------------------------------------------------
    def test_pages_for_name_folds_arabic_variants(self):
        self.pool.add_page('https://aqar.fm/listings', title='مشروع النرجس',
                           content='مشروع النرجس في حي السلمانية—شقق للبيع')
        # Tokens arrive pre-folded like _competitor_name_tokens emits them:
        # السلمانية folds to السلمانيه (ة→ه), tatweel stripped.
        matched = self.pool.pages_for_name({'النرجس', 'السلمانيه'}, 2)
        self.assertEqual([p['url'] for p in matched],
                         ['https://aqar.fm/listings'])

    def test_pages_for_name_matches_page_with_tatweel_and_ya_variants(self):
        self.pool.add_page('https://a.example/1', title='مـوسـى هايتس',
                           content='تفاصيل مشروع موسى')
        matched = self.pool.pages_for_name({'موسي', 'هايتس'}, 2)
        self.assertEqual(len(matched), 1)

    def test_pages_for_name_requires_needed_distinct_tokens(self):
        self.pool.add_page('https://a.example/1', title='النرجس فقط')
        self.assertEqual(self.pool.pages_for_name({'النرجس', 'غائب'}, 2), [])
        self.assertEqual(len(self.pool.pages_for_name({'النرجس', 'غائب'}, 1)), 1)

    def test_pages_for_name_empty_tokens_returns_nothing(self):
        self.pool.add_page('https://a.example/1', content='x')
        self.assertEqual(self.pool.pages_for_name([], 1), [])
        self.assertEqual(self.pool.pages_for_name(None, 1), [])

    def test_pages_for_name_matches_url_and_content_not_just_title(self):
        self.pool.add_page('https://portal.example/النرجس-السلمانيه',
                           title='عنوان عام')
        matched = self.pool.pages_for_name({'النرجس', 'السلمانيه'}, 2)
        self.assertEqual(len(matched), 1)

    # ------------------------------------------------------------------
    # Stats + serialization
    # ------------------------------------------------------------------
    def test_stats_shape(self):
        self.pool.add_query('q', [{'title': 't', 'url': 'u', 'snippet': 's'}])
        self.pool.add_page('https://a.example/1', content='c')
        self.pool.query_results('q')
        self.assertEqual(self.pool.stats(),
                         {'queries': 1, 'pages': 1, 'pool_hits': 1})

    def test_to_dict_from_dict_round_trip(self):
        self.pool.add_query('دراسة السوق', [{'title': 't', 'url': 'u',
                                             'snippet': 's'}])
        self.pool.add_page('https://a.example/req', title='t', content='c',
                           final_url='https://a.example/final', via='http')
        self.pool.mark_failed('https://a.example/bad', 'timeout')
        self.pool.query_results('دراسة السوق')
        restored = evidence.EvidencePool.from_dict(self.pool.to_dict())
        self.assertEqual(restored.stats(), self.pool.stats())
        self.assertEqual(restored.pages(), self.pool.pages())
        self.assertIsNotNone(restored.get_page('https://a.example/req'))
        self.assertEqual(restored.page_failed('https://a.example/bad'),
                         'timeout')
        # Dedupe survives the round trip — the folded query still reads as ran.
        self.assertEqual(restored.add_query('دراسة السوق', []), 0)
        self.assertEqual(restored.query_results('دراسة السوق'),
                         [{'title': 't', 'url': 'u', 'snippet': 's'}])

    def test_from_dict_tolerates_garbage(self):
        pool = evidence.EvidencePool.from_dict(None)
        self.assertEqual(pool.stats(), {'queries': 0, 'pages': 0,
                                        'pool_hits': 0})
        pool = evidence.EvidencePool.from_dict({'pages': ['x', {}],
                                                'queries': {'k': 'bad'}})
        self.assertEqual(pool.stats()['pages'], 0)

    # ------------------------------------------------------------------
    # Thread safety — the ×4 verify pool shares one instance
    # ------------------------------------------------------------------
    def test_concurrent_writers_share_one_pool(self):
        def writer(worker):
            for i in range(25):
                self.pool.add_page(f'https://w{worker}.example/{i}',
                                   content=f'page {i}')
                self.pool.add_query(f'q{worker}-{i}', [])

        threads = [threading.Thread(target=writer, args=(w,))
                   for w in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.pool.stats()['pages'], 100)
        self.assertEqual(self.pool.stats()['queries'], 100)


if __name__ == '__main__':
    unittest.main()
