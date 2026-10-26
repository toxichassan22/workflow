"""Named hotel rows are completed from Booking's own cards, not an agent."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import db  # noqa: E402


class _Session:
    def __init__(self, replies, search_hits=None):
        self.replies = replies
        self.urls = []
        self.search_hits = search_hits or []
        self.queries = []

    def open_url(self, url):
        self.urls.append(url)
        return self.replies.get(url, {})

    def open_urls(self, urls, timeout=None):
        return [self.open_url(url) for url in urls]

    def fetch_html(self, url, timeout=None):
        raise RuntimeError('no destination page in the test session')

    def web_search(self, query, max_results=8):
        self.queries.append(query)
        return self.search_hits

    def close(self):
        pass


class _CatalogSession(_Session):
    def __init__(self, replies, catalog_html='', search_hits=None):
        super().__init__(replies, search_hits=search_hits)
        self.catalog_html = catalog_html

    def fetch_html(self, url, timeout=None):
        self.urls.append(url)
        return {'html': self.catalog_html, 'final_url': url}


class BookingNameFillTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'booking-name-fill.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')
        os.makedirs(cls.module.UPLOADS_DIR, exist_ok=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_named_hotel_row_gets_booking_price_and_source(self):
        name_url = self.module.booking_search.build_search_url('WA Hotel')
        hotel_url = 'https://www.booking.com/hotel/sa/wa-jeddah.html'
        session = _Session({
            name_url: {'final_url': name_url, 'booking_search': {'hotels': [
                {'name': 'WA Hotel Jeddah', 'url': hotel_url,
                 'location': 'الأندلس, جدة'}]}},
            hotel_url: {'final_url': hotel_url,
                        'title': 'WA Hotel Jeddah, Jeddah - Booking.com',
                        'booking_rate': {
                'price': 629.0, 'current_price': 535.0, 'currency': 'SAR',
                'price_from': 629.0, 'price_to': 1100.0,
                'area_from': 32.0, 'area_to': 63.0, 'taxes': 111.0}},
        })
        row = {'name': 'WA Hotel', 'operation_type': 'تشغيل فندقي',
               'project_type': 'فندقي'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة', 'district': 'حي الأندلس'}, {},
                tenant_id=None)
        self.assertEqual(filled, 1)
        self.assertEqual(row['price_from'], '629')
        self.assertEqual(row['price_to'], '1100')
        self.assertEqual(row['area_from'], '32')
        self.assertEqual(row['area_to'], '63')
        self.assertEqual(row['price_type'], 'نطاق أسعار الغرف')
        self.assertEqual(row['source_url'], hotel_url)
        self.assertEqual(row['row_source'], 'booking')

    def test_a_name_outside_the_name_cards_is_found_by_search(self):
        hotel_url = 'https://www.booking.com/hotel/sa/wa-jeddah.html'
        session = _Session({
            hotel_url: {'final_url': hotel_url,
                        'title': 'WA Hotel Jeddah, Jeddah – Booking.com',
                        'booking_rate': {
                'price': 629.0, 'currency': 'SAR',
                'price_from': 629.0, 'price_to': 1100.0,
                'area_from': 32.0, 'area_to': 63.0}},
        }, search_hits=[{'title': 'WA Hotel Jeddah, Jeddah – Booking.com',
                         'url': hotel_url}])
        row = {'name': 'WA Hotel', 'project_type': 'فندقي'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 1)
        self.assertEqual(row['source_url'], hotel_url)
        self.assertTrue(session.queries)
        self.assertIn('site:booking.com/hotel', session.queries[0])

    def test_a_name_that_is_not_in_booking_stays_explicitly_unfilled(self):
        session = _Session({})
        row = {'name': 'فندق غير موجود', 'operation_type': 'تشغيل فندقي',
               'notes': ''}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 0)
        self.assertIn('لم يُعثر', row['notes'])

    def test_name_fill_reports_progress_for_each_row(self):
        name_url = self.module.booking_search.build_search_url('WA Hotel')
        hotel_url = 'https://www.booking.com/hotel/sa/wa-jeddah.html'
        session = _Session({
            name_url: {'final_url': name_url, 'booking_search': {'hotels': [
                {'name': 'WA Hotel Jeddah', 'url': hotel_url}]}},
            hotel_url: {'final_url': hotel_url,
                        'title': 'WA Hotel Jeddah, Jeddah - Booking.com',
                        'booking_rate': {
                'price': 629.0, 'currency': 'SAR'}},
        })
        events = []
        row = {'name': 'WA Hotel', 'project_type': 'فندقي'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None,
                progress=lambda pct, message: events.append((pct, message)))
        self.assertEqual(filled, 1)
        self.assertTrue(any('WA Hotel' in message for _pct, message in events))
        self.assertEqual(events[-1][0], 48)

    def test_a_matching_page_without_rates_is_reported_as_unavailable(self):
        name = 'نوفوتيل جدة التحلية'
        novotel_url = 'https://www.booking.com/hotel/sa/' \
                      'novotel-jeddah-tahlia.ar.html'
        other_url = 'https://www.booking.com/hotel/sa/boudl-jeddah.ar.html'
        session = _Session({
            novotel_url: {'final_url': novotel_url,
                          'title': 'نوفوتيل جدة التحلية، جدة'},
            other_url: {'final_url': other_url,
                        'title': 'بودل التحلية، جدة',
                        'booking_rate': {'price': 680.0}},
        }, search_hits=[
            {'title': 'نوفوتيل جدة التحلية، جدة', 'url': novotel_url},
            {'title': 'بودل التحلية، جدة', 'url': other_url},
        ])
        row = {'name': name, 'project_type': 'فندقي'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 0)
        self.assertIn('لا تُظهر أسعارًا', row['notes'])
        self.assertIsNone(row.get('source_url'))

    def test_the_city_cards_fill_a_row_before_the_name_search(self):
        city_url = self.module.booking_search.build_search_url(
            'Jeddah', dest_id='-3096108')
        hotel_url = 'https://www.booking.com/hotel/sa/wa-jeddah.html'
        session = _Session({
            city_url: {'final_url': city_url, 'booking_search': {'hotels': [
                {'name': 'WA Hotel Jeddah', 'url': hotel_url}]}},
            hotel_url: {'final_url': hotel_url,
                        'title': 'WA Hotel Jeddah, Jeddah - Booking.com',
                        'booking_rate': {
                'price': 629.0, 'currency': 'SAR', 'hotel_stars': 5}},
        })
        row = {'name': 'WA Hotel', 'project_type': 'فندقي'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')), \
                patch.object(
                    self.module.booking_destination,
                    'resolve_city_destination',
                    return_value={'dest_id': '-3096108',
                                  'dest_type': 'city'}):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 1)
        self.assertEqual(row['source_url'], hotel_url)
        self.assertEqual(row['hotel_stars'], '5')
        self.assertEqual(row['status'], 'قائم')
        self.assertEqual(row['classification'], 'مباشر')
        name_url = self.module.booking_search.build_search_url('WA Hotel')
        self.assertNotIn(name_url, session.urls)

    def test_catalogue_finds_a_hotel_outside_the_city_cards(self):
        hotel_url = ('https://www.booking.com/hotel/sa/'
                     'assila-a-luxury-collection-hotel-jeddah.html')
        catalog_html = (
            '<html><body>'
            '<a href="/hotel/sa/assila-a-luxury-collection-hotel-jeddah.ar.html">'
            'Assila, a Luxury Collection Hotel, Jeddah</a>'
            '</body></html>')
        session = _CatalogSession({
            hotel_url: {'final_url': hotel_url,
                        'title': 'Assila, a Luxury Collection Hotel, Jeddah',
                        'booking_rate': {
                            'price': 2500.0, 'currency': 'SAR',
                            'price_from': 2500.0, 'price_to': 9000.0,
                            'area_from': 47.0, 'area_to': 230.0}},
        }, catalog_html=catalog_html)
        row = {'name': 'Assila, a Luxury Collection Hotel, Jeddah',
               'project_type': 'فندقي', 'notes': ''}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')), \
                patch.object(
                    self.module.booking_destination,
                    'resolve_city_destination',
                    return_value={'dest_id': '-3096108',
                                  'city_url':
                                  'https://www.booking.com/city/sa/jeddah.html',
                                  'dest_type': 'city'}):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 1)
        self.assertEqual(row['price_from'], '2500')
        self.assertEqual(row['source_url'], hotel_url)
        self.assertFalse(any('/searchresults.html' in url
                             for url in session.urls))

    def test_catalogue_aliases_match_an_arabic_name_without_a_hint(self):
        hotel_url = ('https://www.booking.com/hotel/sa/'
                     'best-western-plus-jeddah.html')
        catalog_html = (
            '<html><body>'
            '<a href="/hotel/sa/best-western-plus-jeddah.ar.html">'
            'فندق بيست ويسترن بلس جده طريق المدينه</a>'
            '<a href="/hotel/sa/best-western-plus-jeddah.html">'
            'Best Western Plus Jeddah Hotel Madinah Road</a>'
            '</body></html>')
        session = _CatalogSession({
            hotel_url: {'final_url': hotel_url,
                        'title': 'Best Western Plus Jeddah Hotel Madinah Road',
                        'booking_rate': {
                            'price': 1045.0, 'currency': 'SAR',
                            'price_from': 1045.0, 'price_to': 2470.0,
                            'area_from': 30.0, 'area_to': 70.0}},
        }, catalog_html=catalog_html)
        row = {'name': 'فندق بيست ويسترن بلس طريق المدينه',
               'project_type': 'فندقي', 'notes': ''}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')), \
                patch.object(
                    self.module.booking_destination,
                    'resolve_city_destination',
                    return_value={'dest_id': '-3096108',
                                  'city_url':
                                  'https://www.booking.com/city/sa/jeddah.html',
                                  'dest_type': 'city'}):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 1)
        self.assertEqual(row['price_from'], '1045')
        self.assertEqual(row['source_url'], hotel_url)

    def test_an_incomplete_catalogue_is_retried_before_filling(self):
        module = self.module
        one_url = 'https://www.booking.com/hotel/sa/one.html'
        two_url = 'https://www.booking.com/hotel/sa/two.html'
        first = []
        second = [
            {'name': 'One Hotel', 'url': one_url},
            {'name': 'Two Hotel', 'url': two_url},
        ]
        seen = {}
        rows = [
            {'name': 'One Hotel', 'project_type': 'فندقي'},
            {'name': 'Two Hotel', 'project_type': 'فندقي'},
        ]

        def fake_fill(items, *_args, **kwargs):
            seen['catalog'] = kwargs.get('catalog')
            return 0

        with self.app.app_context(), \
                patch.object(module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')), \
                patch.object(module, '_build_booking_catalog',
                             side_effect=[first, second]) as build, \
                patch.object(module, '_fill_rows', new=fake_fill):
            filled = module._fill_hotel_rows_from_booking(
                rows, {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 0)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(len(seen['catalog']), 2)

    def test_booking_fill_carries_stars_status_and_classification(self):
        row = {'name': 'فندق اختبار', 'project_type': 'فندقي'}
        rate = {'price': 600.0, 'price_from': 600.0, 'price_to': 900.0,
                'area_from': 4.0, 'area_to': 5.0, 'hotel_stars': 5,
                'current_price': 550.0}
        self.module._apply_rate(
            row, rate, 'https://www.booking.com/hotel/sa/x.html',
            target_stars={'4'})
        self.assertEqual(row['hotel_stars'], '5')
        self.assertEqual(row['status'], 'قائم')
        self.assertEqual(row['classification'], 'غير مباشر')
        self.assertEqual(row['area_from'], '')
        self.assertEqual(row['area_to'], '')
        self.assertIn('غير منطقية', row['notes'])
        self.assertEqual(row['price_from'], '600')
        self.assertEqual(row['price_to'], '900')
        self.assertIn('5 نجوم', row['notes'])

    def test_market_payload_backfills_project_location_from_the_draft(self):
        draft = {'draft_data': {
            'city': 'جدة', 'district': 'الأندلس',
            'location_lat': '21.544974', 'location_lng': '39.174685',
        }}
        with self.app.app_context(), \
                patch.object(self.module.db, 'get_project_draft_by_id',
                             return_value=draft), \
                patch.object(self.module, '_market_project_facts',
                             return_value=''):
            payload = self.module._prepare_market_payload({
                'draftId': 'draft-1',
                'city': '', 'district': '',
                'projectData': {},
            }, tenant_id='tenant-1')
        self.assertEqual(payload['city'], 'جدة')
        self.assertEqual(payload['district'], 'الأندلس')
        self.assertEqual(payload['location_lat'], '21.544974')
        self.assertEqual(payload['location_lng'], '39.174685')

    def test_fill_skips_booking_when_the_project_has_no_location(self):
        session = _Session({})
        rows = [{'name': 'Adagio Jeddah City Center', 'project_type': 'فندقي',
                 'notes': ''}]
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('', '', '')):
            filled = self.module._fill_hotel_rows_from_booking(
                rows, {'city': ''}, {}, tenant_id=None)
        self.assertEqual(filled, 0)
        self.assertIn('موقع المشروع', rows[0]['notes'])

    def test_booking_fill_says_when_booking_has_no_star_rating(self):
        row = {'name': 'فندق بلا تصنيف', 'project_type': 'فندقي'}
        rate = {'price': 600.0, 'price_from': 600.0, 'price_to': 900.0,
                'area_from': 30.0, 'area_to': 40.0}
        self.module._apply_rate(
            row, rate, 'https://www.booking.com/hotel/sa/no-stars.html')
        self.assertIn('لا يعرض Booking تصنيف نجوم', row['notes'])

    def test_booking_fill_classifies_a_matching_star_class_as_direct(self):
        row = {'name': 'فندق اختبار', 'project_type': 'فندقي'}
        rate = {'price': 600.0, 'price_from': 600.0, 'price_to': 600.0,
                'area_from': 30.0, 'area_to': 40.0, 'hotel_stars': 4}
        self.module._apply_rate(row, rate, 'https://x', target_stars={'4', '5'})
        self.assertEqual(row['classification'], 'مباشر')
        self.assertEqual(row['area_from'], '30')
        self.assertEqual(row['area_to'], '40')

    def test_english_name_matches_an_arabic_card_by_booking_slug(self):
        card = {'name': 'فندق موفنبيك جدة التحلية',
                'url': 'https://www.booking.com/hotel/sa/movenpick-tahlia.ar.html'}
        self.assertIs(
            self.module._card_for_name(
                [card], 'Mövenpick Hotel Tahlia Jeddah', 'جدة Jeddah'),
            card)

    def test_a_sibling_brand_in_the_same_city_does_not_match(self):
        wrong = {'name': 'Mövenpick Hotel City Star Jeddah',
                 'url': 'https://www.booking.com/hotel/sa/'
                        'movenpick-city-star-jeddah.html'}
        self.assertIsNone(self.module._card_for_name(
            [wrong], 'Mövenpick Hotel Tahlia Jeddah', 'جدة Jeddah'))

    def test_a_card_missing_a_road_word_still_matches_two_brand_tokens(self):
        card = {'name': 'بيست ويسترن بلاس جدة',
                'url': 'https://www.booking.com/hotel/sa/'
                       'best-western-plus-jeddah.ar.html'}
        self.assertIs(self.module._card_for_name(
            [card], 'فندق بيست ويسترن بلس طريق المدينه', 'جدة'), card)

    def test_arabic_title_matches_without_the_generic_hotel_word(self):
        self.assertTrue(self.module._title_matches(
            'جدة ماريوت، طريق المدينة',
            'فندق جدة ماريوت طريق المدينة', 'جدة'))
        self.assertFalse(self.module._title_matches(
            'ماريوت جدة', 'فندق جدة ماريوت طريق المدينة', 'جدة'))

    def test_a_row_missing_from_the_cards_is_filled_by_the_name_search(self):
        name = 'Adagio Jeddah City Center'
        name_url = self.module.booking_search.build_search_url(name)
        hotel_url = 'https://www.booking.com/hotel/sa/' \
                    'adagio-jeddah-city-center.html'
        session = _Session({
            name_url: {'final_url': name_url, 'booking_search': {'hotels': [
                {'name': 'شقق أداجيو الفندقية سيتي سنتر جدة',
                 'url': hotel_url}]}},
            hotel_url: {'final_url': hotel_url,
                        'title': 'Adagio Jeddah City Center - Booking.com',
                        'booking_rate': {
                'price': 471.0, 'currency': 'SAR',
                'price_from': 471.0, 'price_to': 900.0,
                'area_from': 30.0, 'area_to': 55.0}},
        })
        row = {'name': name, 'project_type': 'فندقي'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 1)
        self.assertEqual(row['price_from'], '471')
        self.assertEqual(row['source_url'], hotel_url)
        self.assertIn(name_url, session.urls)

    def test_the_name_resolver_maps_typed_names_to_booking_names(self):
        content = json.dumps({'hotels': [
            {'name': 'فندق جدة ماريوت طريق المدينة',
             'booking_name': 'Jeddah Marriott Hotel Madinah Road'},
            {'name': 'WA Hotel', 'booking_name': 'WA Hotel Jeddah'}]},
            ensure_ascii=False)
        reply = {'choices': [{'message': {'content': content}}]}
        with self.app.app_context(), \
                patch.object(self.module, 'call_text_chat',
                             return_value=reply) as call:
            hints = self.module._resolve_booking_names(
                [{'name': 'فندق جدة ماريوت طريق المدينة'},
                 {'name': 'WA Hotel'}],
                {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(hints['WA Hotel'], 'WA Hotel Jeddah')
        self.assertEqual(hints['فندق جدة ماريوت طريق المدينة'],
                         'Jeddah Marriott Hotel Madinah Road')
        self.assertEqual(call.call_args.kwargs.get('model'),
                         self.module.MARKET_STUDY_MODEL)
        self.assertIn('JSON', call.call_args.args[0])

    def test_a_booking_page_that_does_not_match_the_name_is_rejected(self):
        module = self.module
        self.assertTrue(module._page_identity(
            'WA Hotel Jeddah',
            'https://www.booking.com/hotel/sa/wa-jeddah.html',
            ['WA Hotel'], 'جدة'))
        self.assertFalse(module._page_identity(
            'Boudl Hotel Jeddah',
            'https://www.booking.com/hotel/sa/boudl-jeddah.html',
            ['WA Hotel'], 'جدة'))

    def test_the_ai_name_hint_finds_an_arabic_row(self):
        city_url = self.module.booking_search.build_search_url(
            'Jeddah', dest_id='-3096108')
        hotel_url = 'https://www.booking.com/hotel/sa/wa-jeddah.html'
        session = _Session({
            city_url: {'final_url': city_url, 'booking_search': {'hotels': [
                {'name': 'WA Hotel Jeddah', 'url': hotel_url}]}},
            hotel_url: {'final_url': hotel_url,
                        'title': 'WA Hotel Jeddah - Booking.com',
                        'booking_rate': {'price': 700.0, 'currency': 'SAR'}},
        })
        row = {'name': 'فندق دبليو', 'project_type': 'فندقي'}
        self.app.config['TESTING'] = False
        try:
            with self.app.app_context(), \
                    patch.object(self.module, '_market_browser_session',
                                 return_value=session), \
                    patch.object(self.module, '_english_booking_location',
                                 return_value=('Jeddah', 'Al Andalus', 'SA')), \
                    patch.object(self.module, '_resolve_booking_names',
                                 return_value={
                                     'فندق دبليو': 'WA Hotel Jeddah'}), \
                    patch.object(
                        self.module.booking_destination,
                        'resolve_city_destination',
                        return_value={'dest_id': '-3096108',
                                      'dest_type': 'city'}):
                filled = self.module._fill_hotel_rows_from_booking(
                    [row], {'city': 'جدة'}, {}, tenant_id=None)
        finally:
            self.app.config['TESTING'] = True
        self.assertEqual(filled, 1)
        self.assertEqual(row['name'], 'فندق دبليو')
        self.assertEqual(row['price_from'], '700')

    def test_a_wrong_card_page_is_not_written(self):
        name_url = self.module.booking_search.build_search_url('WA Hotel')
        hotel_url = 'https://www.booking.com/hotel/sa/other-hotel.html'
        session = _Session({
            name_url: {'final_url': name_url, 'booking_search': {'hotels': [
                {'name': 'WA Hotel Jeddah', 'url': hotel_url}]}},
            hotel_url: {'final_url': hotel_url,
                        'title': 'Other Hotel Jeddah - Booking.com',
                        'booking_rate': {'price': 700.0, 'currency': 'SAR'}},
        })
        row = {'name': 'WA Hotel', 'project_type': 'فندقي'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session), \
                patch.object(self.module, '_english_booking_location',
                             return_value=('Jeddah', 'Al Andalus', 'SA')):
            filled = self.module._fill_hotel_rows_from_booking(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        self.assertEqual(filled, 0)
        self.assertIsNone(row.get('price_from'))
        self.assertIn('لا تطابق', row.get('notes') or '')

    def test_fill_mode_skips_the_district_pipeline_and_completes_hotels(self):
        module = self.module
        booking_url = 'https://www.booking.com/hotel/sa/wa-jeddah.html'
        row = {'name': 'WA Hotel', 'project_type': 'فندقي',
               'operation_type': 'تشغيل فندقي'}
        calls = {'scan': 0, 'source': 0, 'verify': 0, 'logo': 0}

        def fake_fill(rows, payload, data, tenant_id=None, cache_path='',
                      budget_seconds=None, progress=None, band=None):
            for item in rows:
                if str(item.get('name') or '') != 'WA Hotel':
                    continue
                item.update({
                    'price_from': '629', 'price_to': '1100',
                    'price_type': 'نطاق أسعار الغرف', 'source': 'Booking.com',
                    'source_url': booking_url, 'source_urls': [booking_url],
                    'row_source': 'booking'})
            return 1

        def counted(key, value=None):
            def _inner(*_args, **_kwargs):
                calls[key] += 1
                return value
            return _inner

        self.app.config['TESTING'] = False
        try:
            with self.app.app_context(), \
                    patch.object(module, '_start_source_plan_async',
                                 new=counted('source')), \
                    patch.object(module, '_run_scan_tasks',
                                 new=counted('scan', [])), \
                    patch.object(module, '_fill_hotel_rows_from_booking',
                                 new=fake_fill), \
                    patch.object(module, '_verify_competitor_rows',
                                 new=counted('verify')), \
                    patch.object(module, '_auto_import_competitor_logos',
                                 new=counted('logo')):
                result = module._run_market_competitors({
                    'mode': 'fill',
                    'competitors': [row],
                    'comparisonTypes': [{'type': 'hotel', 'stars': '5'}],
                    'competitorScope': {'mode': 'district', 'radius': '10'},
                    'city': 'جدة',
                    'district': 'الأندلس',
                    'projectType': 'فندقي',
                })
        finally:
            self.app.config['TESTING'] = True
        self.assertTrue(result['success'], result)
        self.assertEqual(calls, {'scan': 0, 'source': 0, 'verify': 0, 'logo': 0})
        self.assertEqual(result['filledCount'], 1)
        self.assertFalse(result['partial'])
        self.assertEqual(result['competitors'][0]['price_from'], '629')
        self.assertEqual(result['competitors'][0]['source_url'], booking_url)

    def test_fill_mode_counts_only_rows_with_real_price_or_area(self):
        module = self.module
        rows = [{'name': f'فندق {number}', 'project_type': 'فندقي',
                 'notes': ''} for number in range(3)]

        def fake_fill(items, *_args, **_kwargs):
            for item in items:
                item['notes'] = 'لم يُعثر على هذا الفندق في Booking.'
            items[0].update({
                'price_from': '100',
                'source_url': 'https://www.booking.com/hotel/sa/one.html',
            })
            items[1]['source_url'] = 'https://example.com/no-price'
            return 1

        self.app.config['TESTING'] = False
        try:
            with self.app.app_context(), \
                    patch.object(module, '_fill_hotel_rows_from_booking',
                                 new=fake_fill):
                result = module._run_market_competitors({
                    'mode': 'fill',
                    'competitors': rows,
                    'comparisonTypes': [{'type': 'hotel', 'stars': '4'}],
                    'competitorScope': {'mode': 'district', 'radius': '10'},
                    'city': 'جدة',
                    'district': 'الأندلس',
                    'projectType': 'فندقي',
                })
        finally:
            self.app.config['TESTING'] = True
        self.assertEqual(result['filledCount'], 1)
        self.assertEqual(result['attemptedCount'], 3)
        self.assertEqual(result['unfilledCount'], 2)
        self.assertEqual(result['missingPriceCount'], 2)
        self.assertEqual(result['updated'], 1)
        self.assertIn('1 من 3', result['notes'])

    def test_fill_mode_leaves_a_complete_row_alone(self):
        module = self.module
        row = {'name': 'برج مكتمل', 'project_type': 'سكني',
               'operation_type': 'بيع',
               'source_url': 'https://example.sa/project',
               'price_from': '850000', 'area_from': '120'}
        calls = {'verify': 0}

        def fake_verify(*_args, **_kwargs):
            calls['verify'] += 1

        with self.app.app_context(), \
                patch.object(module, '_verify_competitor_rows',
                             new=fake_verify):
            result = module._run_market_competitors({
                'mode': 'fill',
                'competitors': [row],
                'comparisonTypes': [{'type': 'residential', 'operation': 'sale'}],
                'competitorScope': {'mode': 'district', 'radius': '10'},
                'city': 'الرياض',
                'district': 'النرجس',
            })
        self.assertTrue(result['success'], result)
        self.assertEqual(calls['verify'], 0)
        self.assertEqual(result['filledCount'], 0)
        self.assertIn('مكتملة بالفعل', result['notes'])

    def test_fill_mode_returns_success_when_a_name_search_finds_nothing(self):
        module = self.module
        row = {'name': 'برج مرقاة النرجس', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        seen = {}

        def fake_verify(rows, payload, data, tenant_id=None, progress=None,
                        **kwargs):
            seen['names'] = [item.get('name') for item in rows]
            seen['deadline'] = kwargs.get('deadline')
            for item in rows:
                item['verify_state'] = 'no_match'

        with self.app.app_context(), \
                patch.object(module, '_verify_competitor_rows',
                             new=fake_verify):
            result = module._run_market_competitors({
                'mode': 'fill',
                'competitors': [row],
                'comparisonTypes': [{'type': 'residential', 'operation': 'sale'}],
                'competitorScope': {'mode': 'district', 'radius': '10'},
                'city': 'الرياض',
                'district': 'النرجس',
            })
        self.assertTrue(result['success'], result)
        self.assertEqual(result['filledCount'], 0)
        self.assertTrue(result['partial'])
        self.assertEqual(result['missingPriceCount'], 1)
        self.assertEqual(seen['names'], ['برج مرقاة النرجس'])
        self.assertIsNotNone(seen['deadline'])


if __name__ == '__main__':
    unittest.main()
