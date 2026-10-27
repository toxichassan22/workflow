"""Deterministic Booking room-rate extraction.

The owner compares the original pre-discount nightly price of the cheapest
base room. Booking's page also shows the current discounted price, a
breakfast-included sibling, other room categories and taxes; picking the wrong
one is the ~20% gap this suite guards.
"""

import contextlib
import io
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
        self.assertIn('price_before_discount: 350', block)
        self.assertIn('current_price_after_discount: 245', block)
        self.assertIn('price_range_before_discount: 350', block)
        self.assertIn('price_basis: original pre-discount room price', block)
        parsed = booking_rooms.parse_rate_block(block)
        self.assertEqual(parsed['price'], 350.0)
        self.assertEqual(parsed['current_price'], 245.0)
        self.assertEqual(parsed['area_sqm'], 35.0)
        self.assertEqual(parsed['taxes'], 44.0)
        self.assertEqual(parsed['price_from'], 350.0)
        self.assertEqual(parsed['price_to'], 350.0)

    def test_block_basis_states_that_taxes_are_excluded(self):
        rate = {
            'price': 340.0, 'current_price': 289.0, 'taxes': 52.0,
            'tax_included': True, 'currency': 'SAR',
            'price_from': 340.0, 'price_to': 900.0,
        }
        block = booking_rooms.format_rate_block(rate)
        self.assertIn('price_before_discount: 340', block)
        basis = next(line for line in block.splitlines()
                     if line.startswith('price_basis:'))
        self.assertIn('taxes', basis)
        self.assertNotIn('not divided back out', basis)

    def test_arabic_room_name_and_area_are_parsed(self):
        rate = booking_rooms.select_cheapest_rate(
            [_row('100_200_2_2_0', 245, 350, area='35 م²',
                  room='غرفة مزدوجة 35 م²')])
        self.assertEqual(rate['price'], 350.0)
        self.assertEqual(rate['area_sqm'], 35.0)
        self.assertEqual(rate['room_name'], 'غرفة مزدوجة')

    def test_room_ranges_span_every_base_room(self):
        rows = [
            _row('100_200_2_2_0', 245, 350, area='35 m²', room='Standard'),
            _row('101_201_2_2_0', 400, 500, area='42 m²', room='Suite'),
        ]
        ranges = booking_rooms.room_ranges(rows)
        self.assertEqual(ranges['price_from'], 350.0)
        self.assertEqual(ranges['price_to'], 500.0)
        self.assertEqual(ranges['area_from'], 35.0)
        self.assertEqual(ranges['area_to'], 42.0)
        self.assertEqual(ranges['room_count'], 2)
        self.assertEqual(ranges['currency'], 'SAR')

    def test_ranges_cover_every_room_row_not_only_base_rooms(self):
        rows = [
            _row('100_200_2_2_0', 245, 350, area='35 m²', room='Standard'),
            _row('101_201_2_2_0', 400, 500, area='42 m²', room='Suite'),
            _row('101_202_2_2_0', 450, 560, area='42 m²', room='Suite',
                 row_text='Guests: 2 adults Very good breakfast included'),
        ]
        ranges = booking_rooms.room_ranges(rows)
        self.assertEqual(ranges['price_from'], 350.0)
        self.assertEqual(ranges['price_to'], 560.0)
        self.assertEqual(ranges['area_from'], 35.0)
        self.assertEqual(ranges['area_to'], 42.0)
        self.assertEqual(ranges['room_count'], 2)

    def test_ranges_include_rooms_sold_for_other_occupancies(self):
        rows = [
            _row('100_200_2_2_0', 245, 350, area='35 m²', room='Standard'),
            _row('106_206_4_0_0', 1000, 1200, area='90 m²',
                 room='Family Suite', row_text='Guests: 4 adults'),
        ]
        ranges = booking_rooms.room_ranges(rows)
        self.assertEqual(ranges['price_to'], 1200.0)
        self.assertEqual(ranges['area_to'], 90.0)
        self.assertEqual(ranges['room_count'], 2)

    def test_range_area_is_borrowed_from_the_same_room(self):
        rows = [
            _row('100_200_2_2_0', 245, 350, area='35 m²', room='Standard'),
            _row('100_201_2_2_0', 301, 430, area='', room='',
                 row_text='Guests: 2 adults breakfast included'),
        ]
        ranges = booking_rooms.room_ranges(rows)
        self.assertEqual((ranges['area_from'], ranges['area_to']),
                         (35.0, 35.0))
        self.assertEqual(ranges['price_to'], 430.0)

    def test_block_round_trips_the_price_and_area_ranges(self):
        rows = [
            _row('100_200_2_2_0', 245, 350, area='35 m²', room='Standard'),
            _row('101_201_2_2_0', 400, 500, area='42 m²', room='Suite'),
        ]
        rate = booking_rooms.select_cheapest_rate(rows)
        rate.update(booking_rooms.room_ranges(rows))
        block = booking_rooms.format_rate_block(rate)
        self.assertIn('price_range_before_discount: 350 - 500', block)
        self.assertIn('area_range_sqm: 35 - 42', block)
        parsed = booking_rooms.parse_rate_block(block)
        self.assertEqual((parsed['price_from'], parsed['price_to']),
                         (350.0, 500.0))
        self.assertEqual((parsed['area_from'], parsed['area_to']),
                         (35.0, 42.0))

    def test_a_tax_inclusive_view_keeps_the_figure_the_page_prints(self):
        # A session outside Saudi Arabia is served the room table with the
        # property's taxes already folded into the figure it prints: the live
        # row read '89 €' beside a 375 SAR rounded attribute and a taxes line
        # that only said «شامل الضرائب والرسوم». Dividing that by a fixed
        # stack (1.2075) put 322 beside a page showing 325, so the owner ruled
        # the printed figure is the row's figure (2026-10-26): nothing is
        # divided back out, and the note says the figure includes the taxes.
        row = {
            'block_id': '1559334001_438176898_2_2_0',
            'price_attr': '375',
            'current_text': '89 €',
            'original_text': '148 €',
            'original_value': '147.883448314875',
            'taxes_text': 'شامل الضرائب والرسوم',
            'taxes_raw': '',
            'room_name': 'غرفة ديلوكس كينغ 30 م²',
            'area_text': '30 م²',
            'occupancy_text': 'Max. people: 2',
            'row_text': 'Guests: 2 adults',
        }
        rate = booking_rooms.select_cheapest_rate([row])
        self.assertTrue(rate['tax_included'])
        # 375 SAR printed as-is; nothing is divided back out.
        self.assertAlmostEqual(rate['current_price'], 375.0, delta=0.05)
        # 148 EUR x (375/89) = 623.6, kept as the pre-discount figure.
        self.assertAlmostEqual(rate['price'], 623.6, delta=0.1)
        self.assertAlmostEqual(rate['current_price_including_tax'], 375.0,
                               delta=0.05)
        ranges = booking_rooms.room_ranges([row])
        self.assertEqual(ranges['price_from'], 624)
        self.assertEqual(ranges['price_to'], 624)
        block = booking_rooms.format_rate_block(rate)
        self.assertIn('tax_included: true', block)
        self.assertNotIn('tax_factor_removed', block)
        self.assertIn('price_range_before_discount: 624', block)
        self.assertIn('شامل الضرائب والرسوم',
                      booking_rooms.note_basis_ar(True))
        self.assertIn('بدون الضريبة', booking_rooms.note_basis_ar(False))

    def test_no_table_rows_returns_none(self):
        self.assertIsNone(booking_rooms.select_cheapest_rate([]))

    def test_a_page_without_a_room_table_says_why_it_was_empty(self):
        # A property page that answers without a room table is either a night
        # with no availability or a page still in its challenge shell. The miss
        # must say which, otherwise it reads as a silent extraction failure.
        class _Page:
            def __init__(self):
                self.calls = 0

            def evaluate(self, _script):
                self.calls += 1
                if self.calls == 1:
                    return {'found': False, 'rows': []}
                return ('نوفوتيل جدة التحلية || flags=unavailable, || '
                        'لا تتوفر غرف لهذه التواريخ')

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rate = booking_rooms.extract_booking_rate(
                _Page(), 'https://www.booking.com/hotel/sa/x.html')
        self.assertIsNone(rate)
        printed = buffer.getvalue()
        self.assertIn('[BOOKING RATE MISS]', printed)
        self.assertIn('reason=no_table', printed)
        self.assertIn('unavailable', printed)

    def test_a_closed_tab_is_named_and_never_reread(self):
        # A tab that dies under the read and a page that has no rates print
        # the same «read_failed». Only the first can be answered, and only by
        # reopening the URL — re-reading the dead page just spends the stage's
        # window, so the miss has to say which one it was.
        class _Page:
            def __init__(self):
                self.reads = 0

            def evaluate(self, _script):
                self.reads += 1
                raise RuntimeError(
                    'Target page, context or browser has been closed')

            def is_closed(self):
                return True

            def wait_for_timeout(self, _ms):
                pass

            def wait_for_selector(self, *_args, **_kwargs):
                return None

        page = _Page()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rate = booking_rooms.wait_and_extract(
                page, 'https://www.booking.com/hotel/sa/x.html')
        self.assertIsNone(rate)
        self.assertEqual(page.reads, 1)
        printed = buffer.getvalue()
        self.assertIn('state=tab_closed', printed)
        self.assertIn('has been closed', printed)

    def test_a_destroyed_context_is_reread_instead_of_abandoned(self):
        # Booking reloads its own page to clear a WAF challenge, so the read
        # in flight loses the JS context it ran in — and the retry sleep fails
        # on that same document. That is what another look is for: ending the
        # read there cost the hotel its price after a single attempt.
        class _Page:
            def __init__(self):
                self.reads = 0

            def is_closed(self):
                return False

            def evaluate(self, script):
                if 'hprt-table' not in (script or ''):
                    return ''
                self.reads += 1
                if self.reads == 1:
                    raise RuntimeError('Execution context was destroyed')
                return {'found': True, 'rows': [_row('1', 578, 680)],
                        'title': 'فندق تجريبي'}

            def wait_for_timeout(self, _ms):
                raise RuntimeError('Execution context was destroyed')

            def wait_for_selector(self, *_args, **_kwargs):
                return None

        page = _Page()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rate = booking_rooms.wait_and_extract(
                page, 'https://www.booking.com/hotel/sa/x.html')
        self.assertEqual(page.reads, 2)
        self.assertIsNotNone(rate)
        self.assertEqual(rate['price'], 680.0)

    def test_the_room_table_price_is_kept_as_the_site_supplies_it(self):
        row = {
            'block_id': '1559334001_438176898_2_2_0',
            'price_attr': '578',
            'current_text': 'SAR 578',
            'original_value': '680',
            'original_text': 'SAR 680',
            'taxes_text': '+SAR 103 taxes and fees',
            'taxes_raw': '103',
            'room_name': 'Standard Double Room',
            'area_text': '35 m²',
            'occupancy_text': 'Max. people: 2',
            'row_text': 'Guests: 2 adults',
        }
        rate = booking_rooms.select_cheapest_rate([row])
        self.assertEqual(rate['price'], 680.0)
        self.assertEqual(rate['current_price'], 578.0)
        self.assertEqual(rate['taxes'], 103.0)
        self.assertEqual(rate['current_price_including_tax'], 681.0)
        block = booking_rooms.format_rate_block(rate)
        self.assertIn('price_before_discount: 680', block)
        self.assertIn('current_price_after_discount: 578', block)
        self.assertIn('price_range_before_discount: 680', block)

    def test_a_tax_inclusive_figure_loses_its_taxes_before_the_row_is_written(self):
        # The view folds the property's taxes into the printed original:
        # 680 printed with 103 stated as «included» is a 577 room price. The
        # row carries the pre-discount, pre-tax figure (owner decision
        # 2026-10-27), not the 680 stay total.
        row = {
            'block_id': '1559334001_438176898_2_2_0',
            'price_attr': '577',
            'current_text': 'SAR 577',
            'original_value': '680',
            'original_text': 'SAR 680',
            'taxes_text': 'SAR 103 taxes and fees included',
            'taxes_raw': '103',
            'room_name': 'Standard Double Room',
            'area_text': '35 m²',
            'occupancy_text': 'Max. people: 2',
            'row_text': 'Guests: 2 adults',
        }
        rate = booking_rooms.select_cheapest_rate([row])
        self.assertTrue(rate['tax_included'])
        self.assertEqual(rate['price'], 577.0)
        self.assertEqual(rate['taxes'], 103.0)
        self.assertEqual(booking_rooms.room_ranges([row])['price_from'], 577.0)
        self.assertIn('بعد استبعاد الضرائب',
                      booking_rooms.note_basis_ar(True, 103))

    def test_a_discount_never_inflates_the_original_room_price(self):
        # The live row displayed 340 as the original, 289 as the current
        # discounted price and +52 taxes. Applying 340/289 as a ratio
        # multiplied the original into 400; the table carries the 340
        # original alone, with no ratio and no added taxes.
        row = {
            'block_id': '1559334001_438176898_2_2_0',
            'price_attr': '340',
            'current_text': '289 SAR',
            'original_value': '340',
            'original_text': '340 SAR',
            'taxes_text': '+52 SAR taxes and fees',
            'taxes_raw': '51.6588',
            'room_name': 'Standard Double Room',
            'area_text': '35 m²',
            'occupancy_text': 'Max. people: 2',
            'row_text': 'Guests: 2 adults',
        }
        ranges = booking_rooms.room_ranges([row])
        self.assertEqual(ranges['price_from'], 340.0)
        self.assertEqual(ranges['price_to'], 340.0)
        block = booking_rooms.format_rate_block(
            booking_rooms.select_cheapest_rate([row]))
        self.assertIn('price_range_before_discount: 340', block)

    def test_a_local_currency_row_becomes_the_displayed_original_price(self):
        # One night in the browser's EGP display: the page shows 5,010 EGP
        # original, 4,258 EGP current and +761 EGP taxes beside the requested
        # 289 SAR current. 5,010 converts to 340, so the range must read 340,
        # not 400.
        row = {
            'block_id': '1559334001_438176898_2_2_0',
            'price_attr': '289',
            'current_text': '4,258 EGP',
            'original_value': '5010',
            'original_text': '5,010 EGP',
            'taxes_text': '+761 EGP taxes and fees',
            'taxes_raw': '761',
            'room_name': 'Standard Double Room',
            'area_text': '35 م²',
            'occupancy_text': 'Max. people: 2',
            'row_text': 'Guests: 2 adults',
        }
        ranges = booking_rooms.room_ranges([row])
        self.assertEqual(ranges['price_from'], 340.0)
        self.assertEqual(ranges['price_to'], 340.0)

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
        ranges = booking_rooms.room_ranges([row])
        self.assertAlmostEqual(ranges['price_from'], 630.0, delta=1.0)
        self.assertAlmostEqual(ranges['price_to'], 630.0, delta=1.0)


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


class BookingStarsAndAreaTests(unittest.TestCase):

    def test_rating_stars_aria_is_read(self):
        class _Page:
            def __init__(self, aria):
                self.aria = aria

            def evaluate(self, _script):
                return self.aria

        self.assertEqual(
            booking_rooms.extract_hotel_stars(_Page('5 من أصل 5 نجوم')), 5)
        self.assertEqual(
            booking_rooms.extract_hotel_stars(_Page('4 out of 5 stars')), 4)
        self.assertEqual(booking_rooms.extract_hotel_stars(_Page('')), 0)
        self.assertEqual(booking_rooms.extract_hotel_stars(_Page('8.7')), 0)

    def test_a_star_class_is_read_from_the_header_when_the_widget_is_gone(self):
        # Booking drops the rating widget on some property pages while the
        # header still names the class, so the header and title are read too.
        # Every pattern needs the word that makes a digit a star class.
        class _Page:
            def __init__(self, raw):
                self.raw = raw

            def evaluate(self, _script):
                return self.raw

        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page("bui-rating | فندق جاليريا جدة، 4 نجوم | Galleria")), 4)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page("| | Mövenpick Hotel Tahlia Jeddah | جدة (4-star hotel)")), 4)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page("| | Assila, a Luxury Collection Hotel | جدة "
                  "(أسعار محدثة لعام 2027)")), 0)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page("8.7 رائع | فندق تجريبي | 2.8 كم من الأندلس")), 0)

    def test_a_starless_page_reports_the_text_it_was_read_from(self):
        class _Page:
            def __init__(self, raw):
                self.raw = raw

            def evaluate(self, _script):
                return self.raw

        stars, raw = booking_rooms._read_stars(
            _Page('| | فندق بلا تصنيف | جدة'))
        self.assertEqual(stars, 0)
        self.assertIn('فندق بلا تصنيف', raw)

    def test_an_implausible_room_area_is_rejected(self):
        self.assertIsNone(booking_rooms.parse_area('4 م²'))
        self.assertIsNone(booking_rooms.parse_area('5 m²'))
        self.assertEqual(booking_rooms.parse_area('42 م²'), 42.0)
    def test_a_one_star_badge_is_not_read_as_the_five_its_scale_names(self):
        # The live badge on a one-star property reads «نجمة واحدة من أصل 5
        # نجوم»: the class is spelled out in words while its scale is a digit,
        # so reading the denominator put five stars on every one-star hotel.
        class _Page:
            def __init__(self, raw):
                self.raw = raw

            def evaluate(self, _script):
                return self.raw

        live = ('نجمة واحدة من أصل 5 نجوم | b5ab46c480 ecac3a7c7a | '
                'نوفوتيل جدة التحلية | نجمة واحدة من أصل 5 نجوم | '
                'de576f5064 | شهادة الاستدامة نوفوتيل جدة التحلية | '
                'نوفوتيل جدة التحلية، جدة (أسعار محدثة لعام 2027)')
        self.assertEqual(booking_rooms.extract_hotel_stars(_Page(live)), 1)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page('نجمة واحدة من أصل 5 نجوم')), 1)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page('نجمتان من أصل 5 نجوم')), 2)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page('ثلاث نجوم من أصل 5')), 3)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page('خمسة نجوم | فندق خمسة نجوم')), 5)
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page('one-star hotel')), 1)
        # The scale on its own still is not a class.
        self.assertEqual(booking_rooms.extract_hotel_stars(
            _Page('من أصل 5 نجوم')), 0)


if __name__ == '__main__':
    unittest.main()
