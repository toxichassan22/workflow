"""Deterministic Booking room-rate extraction.

The owner compares the original pre-discount nightly price of the cheapest
base room. Booking's page also shows the current discounted price, a
breakfast-included sibling, other room categories and taxes; picking the wrong
one is the ~20% gap this suite guards.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import booking_rooms  # noqa: E402
import browser  # noqa: E402


def _row(block_id, price, original, area='35 m²', room='Standard Double Room',
         taxes='+SAR 44 taxes and fees', row_text='Guests: 2 adults'):
    return {
        'block_id': block_id,
        'price_attr': str(price),
        'current_text': f'SAR {price}',
        'original_value': str(original) if original else '',
        'original_text': f'SAR {original}' if original else '',
        'taxes_text': taxes,
        'taxes_raw': '43.79',
        'room_name': room,
        'area_text': area,
        'occupancy_text': 'Max. people: 2',
        'row_text': row_text,
    }


class BookingRateSelectionTests(unittest.TestCase):

    def test_base_room_original_rate_wins_over_current_breakfast_and_tax(self):
        rows = [
            _row('100_200_2_2_0', 245, 350,
                 row_text='Guests: 2 adults Very good breakfast SAR 50 No prepayment needed'),
            _row('100_200_2_1_0', 301, 430,
                 row_text='Guests: 2 adults Very good breakfast included'),
            _row('100_200_1_1_0', 273, 390, room='', area='',
                 row_text='Guests: 1 adult Very good breakfast included'),
        ]
        rate = booking_rooms.select_cheapest_rate(rows)
        self.assertEqual(rate['price'], 350.0)
        self.assertEqual(rate['current_price'], 245.0)
        self.assertEqual(rate['original_price'], 350.0)
        self.assertEqual(rate['area_sqm'], 35.0)
        self.assertEqual(rate['taxes'], 44.0)
        self.assertEqual(rate['currency'], 'SAR')
        self.assertEqual(rate['rate_policy'], 'room only; breakfast optional')
        self.assertEqual(rate['block_id'], '100_200_2_2_0')

    def test_no_original_price_falls_back_to_the_current_rate(self):
        rows = [_row('100_200_2_2_0', 245, 0)]
        rate = booking_rooms.select_cheapest_rate(rows)
        self.assertEqual(rate['price'], 245.0)
        self.assertEqual(rate['current_price'], 245.0)

    def test_later_rate_row_borrows_the_room_name_and_area(self):
        rows = [
            _row('100_200_2_2_0', 350, 500, area='42 m²', room='Deluxe Room'),
            _row('100_200_2_1_0', 330, 470, area='', room=''),
        ]
        rate = booking_rooms.select_cheapest_rate(rows)
        self.assertEqual(rate['price'], 470.0)
        self.assertEqual(rate['area_sqm'], 42.0)
        self.assertEqual(rate['room_name'], 'Deluxe Room')

    def test_block_round_trip_keeps_the_pre_discount_value(self):
        rate = booking_rooms.select_cheapest_rate(
            [_row('100_200_2_2_0', 245, 350)])
        block = booking_rooms.format_rate_block(rate)
        self.assertIn('nightly_price_before_discount: 350', block)
        self.assertIn('current_price_after_discount: 245', block)
        self.assertIn('price_basis: original pre-discount', block)
        parsed = booking_rooms.parse_rate_block(block)
        self.assertEqual(parsed['price'], 350.0)
        self.assertEqual(parsed['current_price'], 245.0)
        self.assertEqual(parsed['area_sqm'], 35.0)
        self.assertEqual(parsed['taxes'], 44.0)

    def test_arabic_room_name_and_area_are_parsed(self):
        rate = booking_rooms.select_cheapest_rate(
            [_row('100_200_2_2_0', 245, 350, area='35 م²',
                  room='غرفة مزدوجة 35 م²')])
        self.assertEqual(rate['price'], 350.0)
        self.assertEqual(rate['area_sqm'], 35.0)
        self.assertEqual(rate['room_name'], 'غرفة مزدوجة')

    def test_no_table_rows_returns_none(self):
        self.assertIsNone(booking_rooms.select_cheapest_rate([]))

    def test_local_currency_original_is_restated_in_the_page_currency(self):
        row = {
            'block_id': '100_200_2_2_0',
            'price_attr': '535',
            'current_text': '7,883 EGP',
            'original_value': '9273.64126820872',
            'original_text': '9,274 EGP',
            'taxes_text': '+1,636 EGP taxes and fees',
            'taxes_raw': '1636',
            'room_name': 'Deluxe Queen Room',
            'area_text': '32 m²',
            'occupancy_text': 'Max. people: 2',
            'row_text': 'Guests: 2 adults',
        }
        rate = booking_rooms.select_cheapest_rate([row])
        self.assertEqual(rate['currency'], 'SAR')
        self.assertEqual(rate['current_price'], 535.0)
        self.assertAlmostEqual(rate['price'], 629.5, delta=0.6)
        self.assertAlmostEqual(rate['taxes'], 111.0, places=1)
        self.assertEqual(rate['current_price_including_tax'], 646.0)


class BookingRoomTableWiringTests(unittest.TestCase):

    def test_rate_is_read_before_the_form_stripping_extractor(self):
        source = Path(browser.__file__).read_text(encoding='utf-8')
        start = source.index('def _open_url_once')
        body = source[start:source.index('    def open_url', start)]
        self.assertIn('booking_rooms.apply_user_agent(', body)
        self.assertIn('booking_rooms.wait_and_extract(page, url)', body)
        extract_at = body.index('booking_rooms.wait_and_extract(page, url)')
        evaluate_at = body.index('page.evaluate(_EXTRACT_JS)', extract_at)
        self.assertLess(extract_at, evaluate_at)
        self.assertIn('booking_rooms.wait_for_rate_rows', body)
        self.assertIn('BOOKING_TABLE_TIMEOUT_MS', body)

    def test_agent_result_carries_the_booking_rate(self):
        part = (ROOT / 'modules' / 'web_browse' / 'agent_parts'
                / '01_browser_interaction.py')
        text = part.read_text(encoding='utf-8')
        self.assertIn("payload['booking_rate'] = rate", text)


if __name__ == '__main__':
    unittest.main()
