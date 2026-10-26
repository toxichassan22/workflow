"""Named hotel rows are completed from Booking's own cards, not an agent."""

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
            hotel_url: {'final_url': hotel_url, 'booking_rate': {
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
        row = {'name': 'فندق غير موجود', 'operation_type': 'تشغيل فندقي'}
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
            hotel_url: {'final_url': hotel_url, 'booking_rate': {
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
            hotel_url: {'final_url': hotel_url, 'booking_rate': {
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
            hotel_url: {'final_url': hotel_url, 'booking_rate': {
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
