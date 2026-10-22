"""Competitor source links: one final page, no duplicates, no search hops."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _p in (str(ROOT), str(_WEB_BROWSE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_study  # noqa: E402


class SourceIdentityTests(unittest.TestCase):

    def test_canonical_key_ignores_www_slash_scheme_and_tracking(self):
        left = market_study.canonical_source_key(
            'https://www.Example.com/projects/tower/?utm_source=x&s=abc')
        right = market_study.canonical_source_key(
            'http://example.com/projects/tower')
        self.assertEqual(left, right)

    def test_unique_source_urls_keeps_first_printed_form(self):
        values = market_study.unique_source_urls([
            'https://www.example.com/project/?utm_campaign=a',
            'https://example.com/project',
            'https://example.com/project#gallery',
        ])
        self.assertEqual(values, ['https://www.example.com/project/?utm_campaign=a'])

    def test_search_pages_are_not_specific_sources(self):
        for url in (
                'https://www.booking.com/searchresults.ar.html?ss=jeddah',
                'https://www.google.com/search?q=hotel',
                'https://www.booking.com/',
                'https://example.com/'):
            self.assertTrue(market_study.is_search_or_index_source_url(url), url)
        self.assertFalse(market_study.is_search_or_index_source_url(
            'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.ar.html'))
        self.assertFalse(market_study.is_search_or_index_source_url(
            'https://developer.example/projects/tower-1'))


class CompetitorPrimarySourceTests(unittest.TestCase):

    def test_hotel_row_keeps_the_property_page_over_the_search_chain(self):
        row = {
            'name': 'فندق تجريبي',
            'operation_type': 'تشغيل فندقي',
            'source_url': 'https://www.booking.com/searchresults.ar.html?ss=jeddah',
            'source_urls': [
                'https://www.booking.com/searchresults.ar.html?ss=jeddah',
                'https://www.booking.com/district/sa/jiddah/alandalus.ar.html',
                'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.ar.html',
            ],
        }
        self.assertEqual(
            market_study.primary_competitor_source_url(row),
            'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.ar.html')

    def test_price_evidence_page_wins_over_the_stated_source(self):
        row = {
            'name': 'مجمع',
            'source_url': 'https://developer.example/projects/tower',
            'field_sources': {
                'price_value': ['https://sa.aqar.fm/listing/tower-price'],
            },
            'source_urls': ['https://developer.example/projects/tower'],
        }
        self.assertEqual(
            market_study.primary_competitor_source_url(row),
            'https://sa.aqar.fm/listing/tower-price')

    def test_source_urls_drop_search_pages_and_canonical_duplicates(self):
        row = {
            'source_urls': [
                'https://www.google.com/search?q=project',
                'https://developer.example/projects/tower?utm_source=x',
                'https://developer.example/projects/tower',
            ],
        }
        self.assertEqual(market_study.competitor_source_urls(row),
                         ['https://developer.example/projects/tower?utm_source=x'])

    def test_summary_sources_dedupe_by_page_identity(self):
        rows = [
            {'name': 'أ', 'url': 'https://www.example.com/report?utm_source=x'},
            {'name': 'ب', 'url': 'https://example.com/report'},
            {'name': 'ج', 'url': 'https://example.com/other'},
        ]
        deduped = market_study.dedupe_source_rows(rows)
        self.assertEqual([row['name'] for row in deduped], ['أ', 'ج'])


class HotelPriceRangeTests(unittest.TestCase):

    def test_hotel_room_range_is_the_default_and_a_range_type(self):
        self.assertEqual(
            market_study.PRICE_TYPE_BY_OPERATION['تشغيل فندقي'][0],
            'نطاق أسعار الغرف')
        self.assertIn('نطاق أسعار الغرف', market_study.RANGE_PRICE_TYPES)
        self.assertEqual(
            market_study.PRICE_TYPE_BY_OPERATION_EN['Hotel Operation'][0],
            'Room Price Range')

    def test_competitor_prompt_asks_for_hotel_range_and_pre_discount_price(self):
        prompt = market_study.build_competitors_user_prompt(
            {'city': 'جدة', 'district': 'النرجس', 'projectType': 'فندقي',
             'competitorScope': {'mode': 'district'},
             'comparisonTypes': [{'type': 'hotel', 'stars': 4}]}, [])
        self.assertIn('أقل سعر وأعلى سعر', prompt)
        self.assertIn('قبل الخصم', prompt)
        self.assertIn('الصفحة النهائية', prompt)
        self.assertIn('لا تضع روابط البحث أو النتائج', prompt)


if __name__ == '__main__':
    unittest.main()
