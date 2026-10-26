"""Booking's city catalogue parser and its category pages."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import booking_catalog  # noqa: E402


class _CatalogSession:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def fetch_html(self, url, timeout=None):
        self.urls.append(url)
        return self.pages.get(url, {'error': 'not_found'})


class BookingCatalogTests(unittest.TestCase):

    def test_canonical_hotel_url_drops_language_and_query(self):
        self.assertEqual(
            booking_catalog.canonical_hotel_url(
                'https://www.booking.com/hotel/sa/foo.ar.html?aid=1'),
            'https://www.booking.com/hotel/sa/foo.html')
        self.assertEqual(
            booking_catalog.canonical_hotel_url('/hotel/sa/foo.html'),
            'https://www.booking.com/hotel/sa/foo.html')
        self.assertEqual(
            booking_catalog.canonical_hotel_url(
                'https://example.com/hotel/sa/foo.html'), '')

    def test_hotel_entries_dedupe_language_variants_and_keep_the_longest_name(self):
        html = ('<html><body>'
                '<a href="/hotel/sa/foo.ar.html">فندق فو</a>'
                '<a href="/hotel/sa/foo.html">Foo Hotel Jeddah</a>'
                '<a href="https://example.com/hotel/sa/bar.html">Bar</a>'
                '</body></html>')
        entries = booking_catalog.hotel_entries_from_html(html)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['url'],
                         'https://www.booking.com/hotel/sa/foo.html')
        self.assertEqual(entries[0]['name'],
                         'فندق فو | Foo Hotel Jeddah')

    def test_category_pages_are_derived_from_the_city_url(self):
        urls = booking_catalog.category_page_urls(
            'https://www.booking.com/city/sa/jiddah.html?aid=1')
        self.assertEqual(len(urls), len(booking_catalog.CATEGORY_PAGES))
        self.assertIn(
            'https://www.booking.com/budget/city/sa/jiddah.html', urls)
        self.assertIn(
            'https://www.booking.com/resorts/city/sa/jiddah.html', urls)
        self.assertNotIn('aid=1', ' '.join(urls))

    def test_fetch_city_catalog_aggregates_pages_and_skips_failures(self):
        city_url = 'https://www.booking.com/city/sa/jeddah.html'
        budget_url = booking_catalog.category_page_urls(city_url)[1]
        session = _CatalogSession({
            city_url: {'html': '<a href="/hotel/sa/one.ar.html">One</a>'},
            budget_url: {'html': '<a href="/hotel/sa/two.html">Two</a>'},
        })
        entries = booking_catalog.fetch_city_catalog(session, city_url)
        self.assertEqual(
            [entry['name'] for entry in entries], ['One', 'Two'])
        self.assertIn(city_url, session.urls)
        self.assertIn(budget_url, session.urls)

    def test_category_page_redirected_to_the_city_page_is_skipped(self):
        city_url = 'https://www.booking.com/city/sa/jeddah.html'
        budget_url = booking_catalog.category_page_urls(city_url)[1]
        session = _CatalogSession({
            city_url: {'html': '<a href="/hotel/sa/one.html">One</a>',
                       'final_url': city_url},
            budget_url: {'html': '<a href="/hotel/sa/two.html">Two</a>',
                         'final_url': city_url},
        })
        entries = booking_catalog.fetch_city_catalog(session, city_url)
        self.assertEqual([entry['name'] for entry in entries], ['One'])

    def test_merge_entries_keeps_the_union_and_longest_label(self):
        first = [{'name': 'One', 'url': 'https://www.booking.com/hotel/sa/one.html'}]
        second = [{'name': 'One Jeddah', 'url': 'https://www.booking.com/hotel/sa/one.html'},
                  {'name': 'Two', 'url': 'https://www.booking.com/hotel/sa/two.html'}]
        merged = booking_catalog.merge_entries(first, second)
        self.assertEqual([entry['name'] for entry in merged],
                         ['One Jeddah', 'Two'])

    def test_deadline_prevents_further_page_loads(self):
        city_url = 'https://www.booking.com/city/sa/jeddah.html'
        session = _CatalogSession({
            city_url: {'html': '<a href="/hotel/sa/one.html">One</a>'},
        })
        with patch('booking_catalog.time.time', return_value=200.0):
            entries = booking_catalog.fetch_city_catalog(
                session, city_url, deadline=100.0)
        self.assertEqual(entries, [])
        self.assertEqual(session.urls, [])


if __name__ == '__main__':
    unittest.main()
