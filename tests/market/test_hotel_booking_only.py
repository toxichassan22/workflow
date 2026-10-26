"""Booking-only hotel discovery and value enforcement.

Hotel competitors must be discovered from Booking's own search results and
priced only from the deterministic ``## BOOKING_RATE ##`` block. The native
web-search fallback, model-cited hotel prices/areas and generic listing fills
are intentionally disabled.
"""

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

import booking_rooms  # noqa: E402
import db  # noqa: E402
import market_study  # noqa: E402

BOOKING_URL = 'https://www.booking.com/hotel/sa/wa-jeddah.html'


def _hotel_row(**extra):
    row = {
        'name': 'WA Hotel Jeddah',
        'project_type': 'فندقي',
        'operation_type': 'تشغيل فندقي',
        'row_source': 'ai',
    }
    row.update(extra)
    return row


class BookingOnlyValueTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'hotel-booking-only.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_generic_hotel_price_and_area_fills_are_disabled(self):
        row = _hotel_row()
        page = {
            'url': BOOKING_URL,
            'title': 'WA Hotel Jeddah',
            'content': 'سعر الليلة 500 ريال — غرفة 40 م²',
        }
        with self.app.app_context():
            filled = self.module._fill_competitor_price_from_listings(
                row, [BOOKING_URL], pages=[page])
            self.module._apply_verified_competitor_price(
                row, {'price': {'value': '500', 'currency': 'SAR',
                                'url': BOOKING_URL}}, {BOOKING_URL})
            self.module._apply_verified_competitor_area(
                row, {'area_sqm': '40', 'area_url': BOOKING_URL}, {BOOKING_URL})
        self.assertFalse(filled)
        self.assertFalse(row.get('price_value'))
        self.assertFalse(row.get('area_sqm'))

    def test_clear_ai_hotel_values_leaves_manual_rows(self):
        row = _hotel_row(
            price_value='500', price_from='400', price_to='600',
            price_type='نطاق أسعار الغرف', price_currency='SAR',
            price_cache={'price_value': '500'}, price_listed=True,
            area_sqm='35', area_from='30', area_to='40', area_mode='range',
            area_cache={'area_sqm': '35'},
            fallback_source=True, fallback_source_name='x',
            fallback_source_urls=['https://example.com'],
            field_sources={'price_value': ['https://example.com'],
                           'area_sqm': ['https://example.com']})
        with self.app.app_context():
            self.module._clear_ai_hotel_value_fields(row)
        for key in ('price_value', 'price_from', 'price_to', 'price_type',
                    'price_currency', 'price_cache', 'price_listed',
                    'area_sqm', 'area_from', 'area_to', 'area_mode',
                    'area_cache', 'fallback_source'):
            self.assertNotIn(key, row)
        self.assertNotIn('price_value', row['field_sources'])
        self.assertNotIn('area_sqm', row['field_sources'])

        manual = _hotel_row(row_source='manual', price_value='500', area_sqm='35')
        with self.app.app_context():
            self.module._clear_ai_hotel_value_fields(manual)
        self.assertEqual(manual['price_value'], '500')
        self.assertEqual(manual['area_sqm'], '35')

    def test_fallback_label_does_not_keep_a_non_booking_hotel_source(self):
        row = _hotel_row(
            fallback_source=True,
            source_urls=['https://www.agoda.com/wa-hotel', BOOKING_URL],
            source_url='https://www.agoda.com/wa-hotel',
            price_value='100', price_cache={'price_value': '100'},
            field_sources={'price_value': ['https://www.agoda.com/wa-hotel']})
        with self.app.app_context():
            self.module._drop_banned_competitor_listing_urls(row)
        self.assertEqual(row.get('source_urls'), [BOOKING_URL])
        self.assertEqual(row.get('source_url'), BOOKING_URL)
        self.assertFalse(row.get('price_value'))
        self.assertFalse(row.get('field_sources'))

    def test_deterministic_block_is_the_hotel_writer(self):
        rate = booking_rooms.select_cheapest_rate([{
            'block_id': '100_200_2_2_0',
            'price_attr': '245',
            'current_text': 'SAR 245',
            'original_value': '350',
            'taxes_text': '+SAR 44 taxes and fees',
            'room_name': 'Standard Double Room',
            'area_text': '35 m²',
            'occupancy_text': 'Max. people: 2',
            'row_text': 'Guests: 2 adults',
        }])
        rate['source_url'] = BOOKING_URL
        row = _hotel_row(price_value='999', area_sqm='60')
        with self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, {BOOKING_URL: {
                    'content': booking_rooms.format_rate_block(rate),
                }}, offer_lang='ar')
        self.assertTrue(applied)
        self.assertEqual(row['price_from'], '394')
        self.assertEqual(row['price_to'], '394')
        self.assertEqual(row['price_type'], 'نطاق أسعار الغرف')
        self.assertEqual(row['area_sqm'], '35')
        self.assertEqual(row['price_cache']['booking_current_price'], 245.0)

    def test_native_fallback_is_removed(self):
        source = (ROOT / 'app_parts' / '17_market'
                  / '18_market_endpoints_invites.py').read_text(encoding='utf-8')
        self.assertNotIn('_fill_hotel_rows_with_native_search', source)
        self.assertFalse((ROOT / 'app_parts' / '17_market'
                          / '17d_competitor_hotel_fallback.py').exists())

    def test_hotel_prompt_uses_agent_search_and_booking_property_pages(self):
        prompt = market_study.build_competitors_user_prompt({
            'city': 'جدة', 'district': 'النرجس', 'projectType': 'فندقي',
            'competitorScope': {'mode': 'district'},
            'comparisonTypes': [{'type': 'hotel', 'stars': 4}],
        }, [])
        self.assertIn('SearXNG', prompt)
        self.assertIn('/hotel/', prompt)
        self.assertIn('Booking.com', prompt)
        self.assertNotIn('searchresults.html', prompt)

    def test_verification_prompt_uses_booking_property_pages(self):
        captured = {}

        def fake_call(_system, user, *_args, **_kwargs):
            captured['prompt'] = user
            return {'choices': [{'message': {
                'content': json.dumps({
                    'exists': True, 'official_url': BOOKING_URL}),
                'annotations': [{'url_citation': {
                    'url': BOOKING_URL,
                    'title': 'WA Hotel Jeddah',
                    'content': 'WA Hotel Jeddah property page',
                }}],
            }}]}

        row = _hotel_row(hotel_stars='4')
        with self.app.app_context(), \
                patch.object(self.module, '_browse_agent_call', side_effect=fake_call):
            self.module._verify_competitor_row(row, {'city': 'جدة'}, {})
        self.assertIn('WA Hotel Jeddah', captured['prompt'])
        self.assertIn('/hotel/', captured['prompt'])
        self.assertIn('Booking.com', captured['prompt'])
        self.assertNotIn('searchresults.html', captured['prompt'])


if __name__ == '__main__':
    unittest.main()
