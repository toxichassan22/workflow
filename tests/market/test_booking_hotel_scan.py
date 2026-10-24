"""Deterministic Booking hotel discovery for the competitor scan.

The project's English district (from its coordinates) is searched on Booking,
the hotel cards become rows, and each property page's rate block supplies the
original pre-discount price and room area. No model chooses a hotel page.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import booking_destination  # noqa: E402
import booking_search  # noqa: E402
import db  # noqa: E402

PROPERTY_URL = ('https://www.booking.com/hotel/sa/eden.html'
                '?checkin=2026-11-07&checkout=2026-11-09')
COUNTRY_PAGE = booking_destination.country_page_url('sa', 'en-us')
CITY_PAGE = 'https://www.booking.com/city/sa/jiddah.html?aid=304142'
COUNTRY_HTML = ('<html><body><a href="/city/sa/riyadh.html">Riyadh</a>'
                '<a href="/city/sa/jiddah.html?aid=304142">Jeddah</a>'
                '</body></html>')
CITY_HTML = ('<html><body><form>'
             '<input type="hidden" name="ss" value="Jeddah">'
             '<input type="hidden" name="dest_id" value="-3096108">'
             '<input type="hidden" name="dest_type" value="city">'
             '</form></body></html>')


class _Session:
    def __init__(self, replies, pages=None):
        self.replies = replies
        self.pages = pages or {}
        self.urls = []
        self.page_urls = []

    def open_url(self, url):
        self.urls.append(url)
        return self.replies.get(url, {})

    def fetch_html(self, url, timeout=None):
        self.page_urls.append(url)
        return self.pages.get(url, {'error': 'not_found'})

    def close(self):
        pass


class BookingHotelScanTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'booking-hotel-scan.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        booking_destination._RESOLVED.clear()

    def _payload(self):
        return {
            'city': 'جدة',
            'district': 'حي الأندلس',
            'projectType': 'فندقي',
            'location_lat': 21.5433,
            'location_lng': 39.1728,
            'comparisonTypes': [{'type': 'hotel', 'stars': 4}],
        }

    def _task(self):
        return {
            'kind': 'axis',
            'axis': {'type': 'hotel', 'stars': '4', 'explicit': True},
            'label': 'البحث عن فندقي - 4 نجوم',
        }

    def _geocode(self):
        return {
            'formatted_address': 'Al Andalus, Jeddah',
            'address_components': [
                {'long_name': 'Al Andalus', 'types': [
                    'political', 'sublocality', 'sublocality_level_1']},
                {'long_name': 'Jeddah', 'types': ['locality', 'political']},
                {'long_name': 'Saudi Arabia', 'short_name': 'SA',
                 'types': ['country', 'political']},
            ],
        }

    def _search_url(self):
        return booking_search.build_search_url('Jeddah', stars='4')

    def test_english_location_uses_coordinates(self):
        with self.app.app_context(), \
                patch.object(self.module.maps_service,
                             'reverse_geocode_location',
                             return_value=self._geocode()):
            city, district, country = self.module._english_booking_location(
                self._payload(), {}, tenant_id=None)
        self.assertEqual((city, district, country),
                         ('Jeddah', 'Al Andalus', 'SA'))

    def test_english_location_uses_address_geocode_without_coordinates(self):
        payload = self._payload()
        payload.pop('location_lat', None)
        payload.pop('location_lng', None)
        with self.app.app_context(), \
                patch.object(self.module.maps_service, 'geocode_address',
                             return_value={'success': True,
                                           'lat': 21.5433, 'lng': 39.1728}), \
                patch.object(self.module.maps_service,
                             'reverse_geocode_location',
                             return_value=self._geocode()):
            city, district, country = self.module._english_booking_location(
                payload, {}, tenant_id=None)
        self.assertEqual((city, district, country),
                         ('Jeddah', 'Al Andalus', 'SA'))

    def test_english_location_falls_back_to_the_project_text(self):
        payload = self._payload()
        payload.pop('location_lat', None)
        payload.pop('location_lng', None)
        with self.app.app_context(), \
                patch.object(self.module.maps_service, 'geocode_address',
                             return_value={}):
            city, district, country = self.module._english_booking_location(
                payload, {}, tenant_id=None)
        self.assertEqual((city, district, country), ('جدة', 'الأندلس', ''))

    def test_search_url_carries_dest_id_and_the_district_filter(self):
        url = booking_search.build_search_url(
            'Jeddah', stars='4', dest_id='-3096108', district_id='5654')
        params = dict(parse_qsl(urlsplit(url).query))
        self.assertEqual(params['ss'], 'Jeddah')
        self.assertEqual(params['dest_id'], '-3096108')
        self.assertEqual(params['dest_type'], 'city')
        self.assertEqual(params['nflt'], 'class=4;di=5654')

    def test_district_facet_matches_the_arabic_project_district(self):
        facets = [{'id': '5656', 'label': 'الشاطئ 9'},
                  {'id': '5654', 'label': 'الأندلس 3'}]
        matched = booking_search.match_district_facet(
            facets, 'حي الأندلس', 'Al Andalus District')
        self.assertEqual(matched['id'], '5654')
        self.assertEqual(booking_search.facet_label(matched), 'الأندلس')

    def test_district_facet_matches_the_english_district(self):
        facets = [{'id': '5653', 'label': 'Al Hamra 2'},
                  {'id': '5654', 'label': 'Al Andalus 3'}]
        matched = booking_search.match_district_facet(
            facets, '', 'Al Andalus District')
        self.assertEqual(matched['id'], '5654')

    def test_booking_search_refusal_code_is_read_from_the_final_url(self):
        final_url = ('https://www.booking.com/index.ar.html?label=gen173'
                     '&errorc_searchstring_not_found=ss')
        self.assertEqual(booking_search.search_error_code(final_url),
                         'searchstring_not_found')
        self.assertEqual(
            booking_search.search_error_code('https://www.booking.com/x'), '')

    def test_hotel_scan_builds_rows_from_booking_search_and_rate_block(self):
        search_url = self._search_url()
        session = _Session({
            search_url: {
                'final_url': search_url,
                'title': 'Booking.com: Search results: Al Andalus, Jeddah',
                'text': '## BOOKING_SEARCH ##',
                'booking_search': {'hotels': [{
                    'name': 'Eden Residence',
                    'url': PROPERTY_URL,
                }]},
            },
            PROPERTY_URL: {
                'final_url': PROPERTY_URL,
                'title': 'Eden Residence',
                'text': '## BOOKING_RATE ##',
                'booking_rate': {
                    'price': 680.0, 'currency': 'SAR', 'area_sqm': 59.0,
                    'current_price': 476.0, 'taxes': 85.0,
                    'room_name': 'One-Bedroom Apartment',
                },
            },
        })
        with self.app.app_context(), \
                patch.object(self.module.maps_service,
                             'reverse_geocode_location',
                             return_value=self._geocode()), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session):
            result = self.module._booking_hotel_scan(
                self._task(), self._payload(), {}, tenant_id=None,
                offer_lang='ar', deadline=None)
        rows = result['parsed']['competitors']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['name'], 'Eden Residence')
        self.assertEqual(row['price_value'], '680')
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertEqual(row['price_type'], 'سعر الليلة')
        self.assertEqual(row['area_sqm'], '59')
        self.assertEqual(row['hotel_stars'], '4')
        self.assertEqual(row['source_url'], PROPERTY_URL)
        self.assertEqual(row['source_urls'], [PROPERTY_URL])
        self.assertEqual(row['row_source'], 'booking')
        self.assertIn('قبل الخصم', row['notes'])
        self.assertTrue(result['search_ran'])
        self.assertIn(self._search_url(), session.urls)
        self.assertIn(PROPERTY_URL, session.urls)
        annotations = result['reply']['choices'][0]['message']['annotations']
        annotation_urls = [item['url_citation']['url'] for item in annotations]
        self.assertIn(self._search_url(), annotation_urls)
        self.assertIn(PROPERTY_URL, annotation_urls)

    def test_unpriced_booking_card_is_still_a_sourced_row(self):
        search_url = self._search_url()
        second_url = 'https://www.booking.com/hotel/sa/garden-city-furnished-apartments.html'
        session = _Session({
            search_url: {
                'final_url': search_url,
                'title': 'Booking.com: Search results: Al Andalus, Jeddah',
                'text': '',
                'booking_search': {'hotels': [
                    {'name': 'Eden Residence', 'url': PROPERTY_URL},
                    {'name': 'Garden City', 'url': second_url},
                ]},
            },
            PROPERTY_URL: {
                'final_url': PROPERTY_URL,
                'title': 'Eden Residence',
                'text': '',
                'booking_rate': {
                    'price': 680.0, 'currency': 'SAR', 'area_sqm': 59.0,
                    'current_price': 476.0, 'taxes': 85.0,
                    'room_name': 'One-Bedroom Apartment',
                },
            },
            second_url: {
                'final_url': second_url,
                'title': 'Garden City',
                'text': '',
            },
        })
        with self.app.app_context(), \
                patch.object(self.module.maps_service,
                             'reverse_geocode_location',
                             return_value=self._geocode()), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session):
            result = self.module._booking_hotel_scan(
                self._task(), self._payload(), {}, tenant_id=None,
                offer_lang='ar', deadline=None)
        rows = result['parsed']['competitors']
        self.assertEqual(len(rows), 2)
        unpriced = next(row for row in rows if not row.get('price_value'))
        self.assertEqual(unpriced['name'], 'Garden City')
        self.assertEqual(unpriced['source_url'], second_url)
        self.assertEqual(unpriced['source_urls'], [second_url])
        self.assertIn('لم تُرجع بلوك سعر/مساحة', unpriced['notes'])

    def test_no_cards_returns_an_explicit_booking_note(self):
        search_url = self._search_url()
        session = _Session({
            search_url: {
                'final_url': search_url,
                'title': 'Booking.com',
                'text': '',
                'booking_search': {'hotels': []},
            },
        })
        with self.app.app_context(), \
                patch.object(self.module.maps_service,
                             'reverse_geocode_location',
                             return_value=self._geocode()), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session):
            result = self.module._booking_hotel_scan(
                self._task(), self._payload(), {}, tenant_id=None,
                offer_lang='ar', deadline=None)
        self.assertEqual(result['parsed']['competitors'], [])
        self.assertIn('تعذّر تحديد وجهة المدينة', result['parsed']['notes'])
        self.assertTrue(result['search_ran'])

    def test_hotel_scan_searches_by_dest_id_and_filters_the_district(self):
        booking_destination._RESOLVED.clear()
        city_url = booking_search.build_search_url(
            'Jeddah', stars='4', dest_id='-3096108')
        district_url = booking_search.build_search_url(
            'Jeddah', stars='4', dest_id='-3096108', district_id='5654')
        session = _Session({
            city_url: {
                'final_url': city_url,
                'title': 'Booking.com search',
                'text': '',
                'booking_districts': [
                    {'id': '5656', 'label': 'الشاطئ 9'},
                    {'id': '5654', 'label': 'الأندلس 3'},
                ],
                'booking_search': {'hotels': [
                    {'name': 'City Hotel', 'url': PROPERTY_URL},
                ]},
            },
            district_url: {
                'final_url': district_url,
                'title': 'Booking.com search',
                'text': '',
                'booking_districts': [],
                'booking_search': {'hotels': [
                    {'name': 'Eden Residence', 'url': PROPERTY_URL},
                ]},
            },
            PROPERTY_URL: {
                'final_url': PROPERTY_URL,
                'title': 'Eden Residence',
                'text': '',
                'booking_rate': {
                    'price': 680.0, 'currency': 'SAR', 'area_sqm': 59.0,
                    'current_price': 476.0, 'taxes': 85.0,
                    'room_name': 'One-Bedroom Apartment',
                },
            },
        }, pages={COUNTRY_PAGE: {'html': COUNTRY_HTML},
                  CITY_PAGE: {'html': CITY_HTML}})
        with self.app.app_context(), \
                patch.object(self.module.maps_service,
                             'reverse_geocode_location',
                             return_value=self._geocode()), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session):
            result = self.module._booking_hotel_scan(
                self._task(), self._payload(), {}, tenant_id=None,
                offer_lang='ar', deadline=None)
        rows = result['parsed']['competitors']
        self.assertEqual([row['name'] for row in rows], ['Eden Residence'])
        self.assertIn(city_url, session.urls)
        self.assertIn(district_url, session.urls)
        params = dict(parse_qsl(urlsplit(district_url).query))
        self.assertIn('di=5654', params['nflt'])
        self.assertIn('فلتر حي', result['parsed']['notes'])

    def test_hotel_scan_names_booking_search_only_refusal(self):
        booking_destination._RESOLVED.clear()
        search_url = self._search_url()
        bounced = ('https://www.booking.com/index.ar.html?label=gen173'
                   '&errorc_searchstring_not_found=ss')
        session = _Session({
            search_url: {'final_url': bounced, 'title': 'Booking.com',
                         'text': 'صفحة رئيسية'},
        })
        with self.app.app_context(), \
                patch.object(self.module.maps_service,
                             'reverse_geocode_location',
                             return_value=self._geocode()), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session):
            result = self.module._booking_hotel_scan(
                self._task(), self._payload(), {}, tenant_id=None,
                offer_lang='ar', deadline=None)
        self.assertEqual(result['parsed']['competitors'], [])
        self.assertIn('searchstring_not_found', result['parsed']['notes'])
        self.assertIn('رفض Booking', result['parsed']['notes'])

    def test_hotel_axis_skips_the_agent_and_the_portal_twin(self):
        axes = self.module.market_study.project_competitor_axes({
            'comparisonTypes': [{'type': 'hotel', 'stars': 4}],
        })
        tasks = self.module._competitor_scan_tasks(axes, 'ar', 'generate')
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['axis'].get('type'), 'hotel')
        with self.app.app_context(), \
                patch.object(self.module, '_booking_hotel_scan',
                             return_value={'sentinel': True}), \
                patch.object(self.module, '_browse_agent_call',
                             side_effect=AssertionError('no agent for hotels')):
            result = self.module._run_single_competitor_scan(
                tasks[0], self._payload(), [], 'generate', 'ar', None, {},
                None, None, '', lambda *_a: None, (0, 1), 4, 8)
        self.assertEqual(result, {'sentinel': True})

    def test_hotel_expansion_is_not_a_new_agent_search(self):
        axes = self.module.market_study.project_competitor_axes({
            'comparisonTypes': [{'type': 'hotel', 'stars': 4}],
        })
        tasks = self.module._expansion_scan_tasks(
            self._payload(), axes, axes, [], offer_lang='ar')
        self.assertEqual(tasks, [])

    def test_verification_skips_booking_discovered_rows(self):
        row = {
            'name': 'Eden Residence',
            'operation_type': 'تشغيل فندقي',
            'row_source': 'booking',
            'price_value': '680',
            'area_sqm': '59',
            'verify_state': 'verified',
        }
        with self.app.app_context(), \
                patch.object(self.module, '_browse_agent_call',
                             side_effect=AssertionError('no agent for booking rows')):
            self.module._verify_competitor_rows(
                [row], {'city': 'جدة'}, {}, evidence_pool=None,
                deadline=None)
        self.assertEqual(row['price_value'], '680')
        self.assertEqual(row['area_sqm'], '59')
        self.assertEqual(row['verify_state'], 'verified')


if __name__ == '__main__':
    unittest.main()
