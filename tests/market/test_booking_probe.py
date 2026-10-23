"""Booking CDP probe verdicts.

The probe is the operator's pre-flight check before wiring a cloud VM or
residential CDP endpoint: it must distinguish a normal Booking page from the
WAF challenge and the b_bot page that silently hides prices and areas.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import probe_booking_cdp  # noqa: E402


class BookingProbeVerdictTests(unittest.TestCase):

    def test_waf_challenge_shell_is_its_own_verdict(self):
        verdict = probe_booking_cdp.classify_booking_page(
            '', '', '<div id="challenge-container"></div>')
        self.assertEqual(verdict, 'challenge')

    def test_bot_class_is_reported(self):
        verdict = probe_booking_cdp.classify_booking_page(
            'WA Hotel', 'some hotel text',
            '<html class="b_bot hasJS"></html>')
        self.assertEqual(verdict, 'bot_page')

    def test_bot_page_wins_over_a_leftover_challenge_script(self):
        verdict = probe_booking_cdp.classify_booking_page(
            'WA Hotel, Jeddah',
            "Availability\nSelect dates to see this property's availability and prices",
            '<html class="b_bot"><script src="/__challenge_x/challenge.js"></script></html>')
        self.assertEqual(verdict, 'bot_page')

    def test_select_dates_bot_alert_is_reported(self):
        verdict = probe_booking_cdp.classify_booking_page(
            'WA Hotel',
            "Availability\nSelect dates to see this property's availability and prices",
            '<html></html>')
        self.assertEqual(verdict, 'bot_page')

    def test_normal_page_with_price_or_area_is_ok(self):
        self.assertEqual(
            probe_booking_cdp.classify_booking_page(
                'WA Hotel', 'Deluxe Room 42 m² — SAR 430 per night',
                '<html class="hasJS"></html>'),
            'ok')
        self.assertEqual(
            probe_booking_cdp.classify_booking_page(
                'WA Hotel', 'Check-in date — Check-out date\nSAR 430',
                '<html></html>'),
            'ok')

    def test_transport_error_is_blocked(self):
        verdict = probe_booking_cdp.classify_booking_page(
            '', '', '', error='http_403')
        self.assertEqual(verdict, 'blocked')

    def test_empty_page_is_unknown(self):
        self.assertEqual(
            probe_booking_cdp.classify_booking_page('', '', '<html></html>'),
            'unknown')


if __name__ == '__main__':
    unittest.main()
