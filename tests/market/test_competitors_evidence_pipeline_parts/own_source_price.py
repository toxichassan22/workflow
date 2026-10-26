"""The client's own link is the price's home.

«إكمال المنافسين» read every retrieved page and wrote the median of them: a
row whose source cell opens a page showing 275,000 carried 268,000 — the
average of 275,000 and a 261,000 search hit — and even a gap that small reads
as a broken system to whoever opens the link. The fill now answers from the
row's own page alone, and reads that page before the per-row search result can
stamp a figure of its own.
"""

import json
from unittest.mock import patch

from tests.market import test_competitors_evidence_pipeline as pipeline

market_study = pipeline.market_study

OWN_URL = 'https://almemar.sa/marqaa-narjis'
OTHER_URL = 'https://sa.aqar.fm/listing/marqaa-other'
SEARCH_URLS = [f'https://sa.aqar.fm/listing/hit-{index}' for index in range(4)]

OWN_PAGE = ('<title>مشروع برج مرقاة النرجس — الموقع الرسمي</title>'
            '<div>سعر الوحدة 275,000 ريال</div>')
OWN_PAGE_WITHOUT_PRICE = ('<title>مشروع برج مرقاة النرجس — الموقع الرسمي</title>'
                          '<div>وحدات سكنية تحت الإنشاء</div>')
OTHER_PAGE = ('<title>إعلان برج مرقاة النرجس — عقار</title>'
              '<div>سعر الوحدة 261,000 ريال</div>')


def _reader(pages):
    def read(url, **_kwargs):
        key = str(url or '').strip()
        if key in pages:
            return pages[key], ''
        return '', 'not fetched in this test'
    return read


class OwnSourcePriceTests(pipeline._MarketTestBase):
    """The figure sits beside the link that proves it — never blended."""

    def test_fill_takes_the_figure_from_the_rows_own_link(self):
        module = self.module
        pages = {OWN_URL: OWN_PAGE, OTHER_URL: OTHER_PAGE}
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع',
               'source_url': OWN_URL, 'source_urls': [OWN_URL]}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=_reader(pages)):
            filled = module._fill_competitor_price_from_listings(
                row, [OTHER_URL, OWN_URL])
        self.assertTrue(filled)
        # 275,000 and 261,000 used to average to 268,000 — a number on no page.
        self.assertEqual(row['price_value'], '275000')
        self.assertEqual(row['price_type'], 'سعر الوحدة')
        self.assertEqual(row['field_sources']['price_value'], [OWN_URL])

    def test_own_link_is_read_before_the_search_hits(self):
        """The read budget used to be spent on search hits, so the client's
        own page was never opened and its figure never reached the cell."""
        module = self.module
        pages = {OWN_URL: OWN_PAGE}
        for url in SEARCH_URLS:
            pages[url] = OTHER_PAGE
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع',
               'source_url': OWN_URL, 'source_urls': [OWN_URL]}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=_reader(pages)):
            filled = module._fill_competitor_price_from_listings(
                row, SEARCH_URLS + [OWN_URL])
        self.assertTrue(filled)
        self.assertEqual(row['price_value'], '275000')
        self.assertEqual(row['field_sources']['price_value'], [OWN_URL])

    def test_a_page_without_a_figure_still_lets_the_search_answer(self):
        """Preference is not a lock: a source page that states no price leaves
        the row for the pages that do."""
        module = self.module
        pages = {OWN_URL: OWN_PAGE_WITHOUT_PRICE, OTHER_URL: OTHER_PAGE}
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع',
               'source_url': OWN_URL, 'source_urls': [OWN_URL]}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=_reader(pages)):
            filled = module._fill_competitor_price_from_listings(
                row, [OTHER_URL])
        self.assertTrue(filled)
        self.assertEqual(row['price_value'], '261000')
        self.assertEqual(row['field_sources']['price_value'], [OTHER_URL])

    def test_verification_keeps_the_own_link_figure_over_the_searched_one(self):
        module = self.module
        pages = {OWN_URL: OWN_PAGE, OTHER_URL: OTHER_PAGE}
        reply = {'choices': [{'message': {
            'content': json.dumps({
                'exists': True,
                'official_url': OWN_URL,
                'price': {'type': 'سعر الوحدة', 'value': '268000',
                          'url': OTHER_URL},
            }, ensure_ascii=False),
            'annotations': [
                {'url_citation': {'url': OTHER_URL,
                                  'title': 'إعلان برج مرقاة النرجس — عقار',
                                  'content': 'سعر الوحدة 261,000 ريال'}},
                {'url_citation': {
                    'url': OWN_URL,
                    'title': 'مشروع برج مرقاة النرجس — الموقع الرسمي',
                    'content': 'سعر الوحدة 275,000 ريال'}},
            ],
        }}]}
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع',
               'source_url': OWN_URL, 'source_urls': [OWN_URL]}
        with self.app.app_context(), \
                patch.object(module, '_browse_agent_call', return_value=reply), \
                patch.object(module, '_read_market_source_page',
                             side_effect=_reader(pages)):
            module._verify_competitor_row(row, {'city': 'الرياض'}, {})
        self.assertEqual(row.get('verify_state'), 'verified')
        self.assertEqual(row['price_value'], '275000')
        self.assertEqual(row['field_sources']['price_value'], [OWN_URL])

    def test_row_without_a_link_keeps_the_search_figure(self):
        """No source cell means nothing to contradict — the search still fills
        the row, so the completion job is unchanged for bare rows."""
        module = self.module
        pages = {OTHER_URL: OTHER_PAGE}
        row = {'name': 'برج مرقاة النرجس', 'operation_type': 'بيع'}
        with self.app.app_context(), \
                patch.object(module, '_read_market_source_page',
                             side_effect=_reader(pages)):
            self.assertFalse(module._fill_row_price_from_own_source(row))
            filled = module._fill_competitor_price_from_listings(
                row, [OTHER_URL])
        self.assertTrue(filled)
        self.assertEqual(row['price_value'], '261000')
