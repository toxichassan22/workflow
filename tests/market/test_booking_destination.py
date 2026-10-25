"""Booking's own destination resolution (country page -> city page -> dest_id).

A free-text Booking search is refused with ``errorc_searchstring_not_found``,
so the hotel scan needs the destination id up front. These cases pin the
resolution chain and its failure modes.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import booking_destination  # noqa: E402

COUNTRY_PAGE = booking_destination.country_page_url('sa', 'en-us')
CITY_PAGE = 'https://www.booking.com/city/sa/jiddah.html?aid=304142'
COUNTRY_HTML = ('<html><body><nav>'
                '<a href="/city/sa/riyadh.html">Riyadh</a>'
                '<a href="/city/sa/jiddah.html?aid=304142">Jeddah</a>'
                '</nav></body></html>')
CITY_HTML = ('<html><body><form>'
             '<input type="hidden" name="dest_id" value="-3096108">'
             '<input type="hidden" name="dest_type" value="city">'
             '</form></body></html>')
ARABIC_COUNTRY_HTML = ('<html><body>'
                       '<a href="/city/sa/jiddah.html">جدة</a>'
                       '</body></html>')


class _FakeSession:
    def __init__(self, pages):
        self.pages = {
            url: (value if isinstance(value, list) else [value])
            for url, value in (pages or {}).items()
        }
        self.urls = []

    def fetch_html(self, url, timeout=None):
        self.urls.append(url)
        replies = self.pages.get(url)
        if not replies:
            return {'error': 'not_found'}
        return replies.pop(0) if len(replies) > 1 else replies[0]


class BookingDestinationTests(unittest.TestCase):

    def setUp(self):
        booking_destination._RESOLVED.clear()
        booking_destination.CONTENT_PAGE_RETRY_DELAY = 0
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = str(Path(self.temp_dir.name) / 'destinations.json')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_district_id_is_remembered_and_read_back(self):
        booking_destination.remember_district_id(
            self.cache_path, 'SA', 'Jeddah', 'الأندلس', '5654')
        self.assertEqual(
            booking_destination.cached_district_id(
                self.cache_path, 'sa', 'jeddah', 'الأندلس'), '5654')
        self.assertEqual(
            booking_destination.cached_district_id(
                self.cache_path, 'SA', 'jeddah', 'الشاطئ'), '')

    def test_resolved_city_is_reused_from_the_disk_cache(self):
        first = _FakeSession({COUNTRY_PAGE: {'html': COUNTRY_HTML},
                              CITY_PAGE: {'html': CITY_HTML}})
        booking_destination.resolve_city_destination(
            first, 'SA', 'Jeddah', cache_path=self.cache_path)
        booking_destination._RESOLVED.clear()
        second = _FakeSession({})
        result = booking_destination.resolve_city_destination(
            second, 'SA', 'Jeddah', cache_path=self.cache_path)
        self.assertEqual(result['dest_id'], '-3096108')
        self.assertEqual(second.urls, [])

    def test_stale_cache_entry_is_ignored(self):
        booking_destination._cache_write(self.cache_path, {'sa|jeddah': {
            'dest_id': '-111', 'dest_type': 'city',
            'saved_at': int(time.time()) - booking_destination.CACHE_TTL_SECONDS - 10,
        }})
        session = _FakeSession({COUNTRY_PAGE: {'html': COUNTRY_HTML},
                                CITY_PAGE: {'html': CITY_HTML}})
        result = booking_destination.resolve_city_destination(
            session, 'SA', 'Jeddah', cache_path=self.cache_path)
        self.assertEqual(result['dest_id'], '-3096108')
        self.assertTrue(session.urls)

    def test_country_page_without_links_is_fetched_again(self):
        session = _FakeSession({
            COUNTRY_PAGE: [{'html': '<html>still loading</html>'},
                           {'html': COUNTRY_HTML}],
            CITY_PAGE: {'html': CITY_HTML},
        })
        result = booking_destination.resolve_city_destination(
            session, 'SA', 'Jeddah')
        self.assertEqual(result['dest_id'], '-3096108')
        self.assertEqual(session.urls.count(COUNTRY_PAGE), 2)

    def test_resolves_the_city_dest_id_through_the_country_page(self):
        session = _FakeSession({COUNTRY_PAGE: {'html': COUNTRY_HTML},
                                CITY_PAGE: {'html': CITY_HTML}})
        result = booking_destination.resolve_city_destination(
            session, 'SA', 'Jeddah')
        self.assertEqual(result['dest_id'], '-3096108')
        self.assertEqual(result['dest_type'], 'city')
        self.assertEqual(result['country'], 'sa')
        self.assertEqual(result['city_url'], CITY_PAGE)
        self.assertEqual(session.urls[0], COUNTRY_PAGE)

    def test_resolved_city_is_reused_for_the_second_star_class(self):
        session = _FakeSession({COUNTRY_PAGE: {'html': COUNTRY_HTML},
                                CITY_PAGE: {'html': CITY_HTML}})
        booking_destination.resolve_city_destination(session, 'SA', 'Jeddah')
        booking_destination.resolve_city_destination(session, 'SA', 'Jeddah')
        self.assertEqual(session.urls.count(COUNTRY_PAGE), 1)

    def test_arabic_country_page_is_the_fallback(self):
        session = _FakeSession({
            booking_destination.country_page_url('sa', 'ar'):
                {'html': ARABIC_COUNTRY_HTML},
            CITY_PAGE.replace('?aid=304142', ''): {'html': CITY_HTML},
        })
        session.pages[COUNTRY_PAGE] = [{'error': 'not_found'}]
        result = booking_destination.resolve_city_destination(
            session, 'sa', 'Jeddah', 'جدة')
        self.assertEqual(result['dest_id'], '-3096108')

    def test_unknown_city_returns_empty(self):
        session = _FakeSession({COUNTRY_PAGE: {'html': COUNTRY_HTML}})
        self.assertEqual(booking_destination.resolve_city_destination(
            session, 'SA', 'Atlantis'), {})

    def test_city_page_without_a_dest_id_returns_empty(self):
        session = _FakeSession({COUNTRY_PAGE: {'html': COUNTRY_HTML},
                                CITY_PAGE: {'html': '<html>no id</html>'}})
        self.assertEqual(booking_destination.resolve_city_destination(
            session, 'SA', 'Jeddah'), {})

    def test_missing_country_or_city_needs_no_navigation(self):
        session = _FakeSession({})
        self.assertEqual(booking_destination.resolve_city_destination(
            session, '', 'Jeddah'), {})
        self.assertEqual(booking_destination.resolve_city_destination(
            session, 'SA'), {})
        self.assertEqual(session.urls, [])

    def test_country_page_anchors_are_parsed(self):
        links = booking_destination.city_links(COUNTRY_HTML)
        self.assertEqual([link['text'] for link in links], ['Riyadh', 'Jeddah'])
        self.assertEqual(links[1]['url'], CITY_PAGE)

    def test_dest_id_is_read_from_the_hidden_input(self):
        self.assertEqual(booking_destination.parse_destination(CITY_HTML),
                         {'dest_id': '-3096108', 'dest_type': 'city'})


if __name__ == '__main__':
    unittest.main()
