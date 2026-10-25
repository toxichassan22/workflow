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
    def __init__(self, replies):
        self.replies = replies
        self.urls = []

    def open_url(self, url):
        self.urls.append(url)
        return self.replies.get(url, {})

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
        city_url = self.module.booking_search.build_search_url(
            'Jeddah', dest_id='-3096108')
        hotel_url = 'https://www.booking.com/hotel/sa/wa-jeddah.html'
        session = _Session({
            city_url: {'final_url': city_url, 'booking_search': {'hotels': [
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
                             return_value=('Jeddah', 'Al Andalus', 'SA')), \
                patch.object(
                    self.module.booking_destination,
                    'resolve_city_destination',
                    return_value={'dest_id': '-3096108',
                                  'dest_type': 'city'}):
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

    def test_a_name_that_is_not_in_booking_stays_explicitly_unfilled(self):
        city_url = self.module.booking_search.build_search_url(
            'Jeddah', dest_id='-3096108')
        session = _Session({city_url: {
            'final_url': city_url,
            'booking_search': {'hotels': [
                {'name': 'Other Hotel', 'url': 'https://x/hotel.html'}]},
        }})
        row = {'name': 'فندق غير موجود', 'operation_type': 'تشغيل فندقي'}
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
        self.assertEqual(filled, 0)
        self.assertIn('لم يُعثر', row['notes'])


if __name__ == '__main__':
    unittest.main()
