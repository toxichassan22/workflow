"""The deterministic Booking rate block wins over a model-picked rate plan."""

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

import booking_rooms  # noqa: E402
import db  # noqa: E402

BOOKING_URL = 'https://www.booking.com/hotel/sa/sedra-global-jeddah.html'
FOLDED_URL = 'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.html'


def _rate():
    rate = booking_rooms.select_cheapest_rate([{
        'block_id': '1559334001_438176898_2_2_0',
        'price_attr': '245',
        'current_text': 'SAR 245',
        'original_value': '350',
        'original_text': 'SAR 350',
        'taxes_text': '+SAR 44 taxes and fees',
        'taxes_raw': '43.79',
        'room_name': 'Standard Double Room',
        'area_text': '35 m²',
        'occupancy_text': 'Max. people: 2',
        'row_text': ('Guests: 2 adults Very good breakfast SAR 50 '
                     'No prepayment needed'),
    }])
    rate['source_url'] = BOOKING_URL
    return rate


def _folded_rate():
    """The Novotel row: one printed figure, taxes folded in, no amount shown."""
    rate = booking_rooms.select_cheapest_rate([{
        'block_id': '193957202_398986150_2_42_0',
        'price_attr': '389',
        'current_text': '389 SAR',
        'original_text': '',
        'taxes_text': 'شامل الضرائب والرسوم',
        'room_name': 'غرفة سوبيرير مع سرير مزدوج',
        'area_text': '38 m²',
        'occupancy_text': 'Max. people: 2',
        'row_text': 'Guests: 2 adults',
    }])
    rate['source_url'] = FOLDED_URL
    return rate


class BookingRateApplyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'booking-rate.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _pages(self):
        return {BOOKING_URL: {
            'title': 'Sedra Al Alami',
            'content': 'property page\n' + booking_rooms.format_rate_block(_rate()),
        }}

    def test_ai_hotel_row_gets_the_original_pre_discount_rate_and_area(self):
        row = {
            'name': 'Sedra Al Alami',
            'operation_type': 'تشغيل فندقي',
            'row_source': 'ai',
            'price_value': '301',
            'price_type': 'نطاق أسعار الغرف',
            'price_from': '245',
            'price_to': '546',
            'area_sqm': '60',
        }
        with self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, self._pages(), offer_lang='ar')
        self.assertTrue(applied)
        self.assertEqual(row['price_from'], '350')
        self.assertEqual(row['price_to'], '350')
        self.assertEqual(row['price_type'], 'نطاق أسعار الغرف')
        self.assertEqual(row['area_sqm'], '35')
        self.assertNotIn('price_value', row)
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertEqual(row['price_cache']['booking_current_price'], 245.0)
        self.assertEqual(row['price_cache']['booking_taxes'], 44.0)
        self.assertEqual(row['price_cache']['booking_room_name'],
                         'Standard Double Room')
        self.assertEqual(row['source_url'], BOOKING_URL)
        self.assertIn(BOOKING_URL, row['field_sources']['price_from'])
        self.assertIn(BOOKING_URL, row['field_sources']['price_to'])
        self.assertIn(BOOKING_URL, row['field_sources']['area_sqm'])
        self.assertIn('الأصلي قبل الخصم بدون الضريبة', row['notes'])
        self.assertIn('350', row['notes'])

    def test_folded_view_figure_is_stored_as_the_page_prints_it(self):
        """The view that folds the taxes into its printed figure (Novotel read
        389 beside «شامل الضرائب والرسوم») stores 389 — dividing it by a fixed
        stack put 322 beside a page showing 325."""
        row = {'name': 'Novotel Jeddah Tahlia',
               'operation_type': 'تشغيل فندقي', 'row_source': 'ai'}
        pages = {FOLDED_URL: {
            'title': 'Novotel Jeddah Tahlia',
            'content': 'property page\n' + booking_rooms.format_rate_block(
                _folded_rate()),
        }}
        with self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, pages, offer_lang='ar')
        self.assertTrue(applied)
        self.assertEqual(row['price_from'], '389')
        self.assertEqual(row['price_to'], '389')
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertTrue(row['price_cache']['booking_tax_included'])
        self.assertIn('شامل الضرائب والرسوم', row['notes'])
        self.assertIn('389', row['notes'])
        self.assertNotIn('بدون الضريبة', row['notes'])

    def test_name_fill_keeps_the_folded_figure_and_says_so(self):
        """The completion pass applies the same basis: the printed figure and
        a note that names it as tax-inclusive."""
        row = {'name': 'Novotel Jeddah Tahlia'}
        with self.app.app_context():
            self.module._apply_rate(row, _folded_rate(), FOLDED_URL)
        self.assertEqual(row['price_from'], '389')
        self.assertEqual(row['price_to'], '389')
        self.assertEqual(row['price_type'], 'نطاق أسعار الغرف')
        self.assertIn('شامل الضرائب والرسوم', row['notes'])
        self.assertNotIn('بدون الضريبة', row['notes'])

    def test_manual_row_is_never_overwritten(self):
        row = {
            'name': 'Sedra Al Alami',
            'operation_type': 'تشغيل فندقي',
            'row_source': 'manual',
            'price_value': '301',
            'price_type': 'نطاق أسعار الغرف',
        }
        with self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, self._pages(), offer_lang='ar')
        self.assertFalse(applied)
        self.assertEqual(row['price_value'], '301')
        self.assertEqual(row['price_type'], 'نطاق أسعار الغرف')

    def test_non_hotel_row_is_untouched(self):
        row = {
            'name': 'Tower',
            'operation_type': 'بيع',
            'row_source': 'ai',
            'price_value': '900000',
        }
        with self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, self._pages(), offer_lang='ar')
        self.assertFalse(applied)
        self.assertEqual(row['price_value'], '900000')

    def test_foreign_currency_block_converts_the_original_price_range(self):
        rate = _rate()
        rate.update({'currency': 'EGP', 'price': 10000.0,
                     'current_price': 7017.0, 'taxes': 1254.0})
        block = booking_rooms.format_rate_block(rate)
        row = {
            'name': 'Sedra Al Alami',
            'operation_type': 'تشغيل فندقي',
            'row_source': 'ai',
        }
        with patch.object(self.module.market_study, 'price_fx_to_sar',
                          return_value=0.068), self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, {BOOKING_URL: {'content': block}}, offer_lang='ar')
        self.assertTrue(applied)
        self.assertEqual(row['price_from'], '680')
        self.assertEqual(row['price_to'], '680')
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertEqual(row['price_cache']['original_currency'], 'EGP')
        self.assertEqual(row['price_cache']['original_price_value'], '10000')

    def test_missing_block_returns_false(self):
        row = {
            'name': 'Sedra Al Alami',
            'operation_type': 'تشغيل فندقي',
            'row_source': 'ai',
            'price_value': '301',
        }
        with self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, {BOOKING_URL: {'content': 'no room table here'}},
                offer_lang='ar')
        self.assertFalse(applied)
        self.assertEqual(row['price_value'], '301')


if __name__ == '__main__':
    unittest.main()
