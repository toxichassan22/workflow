"""Booking.com hotel research must open a real stay, not an empty calendar.

The property page hides every price and room size until a check-in/check-out
is selected — the owner saw «Select dates to see this property's availability
and prices» and rows with no price and no area. Every hotel lookup now opens
the same two-week-out, two-night, one-room, two-adult, SAR window, and the
verification pass reads the room size from the retrieved page.
"""

import json
import os
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import agent  # noqa: E402
import booking_rooms  # noqa: E402
import browser  # noqa: E402
import db  # noqa: E402
import hotel_stay  # noqa: E402
import market_study  # noqa: E402

HOTEL_URL = 'https://www.booking.com/hotel/sa/assila.ar.html'
STAY_IN = date(2026, 1, 15)
STAY_OUT = date(2026, 1, 17)


class BookingStayWindowTests(unittest.TestCase):

    def test_window_is_two_weeks_out_for_two_nights(self):
        check_in, check_out = hotel_stay.booking_stay_window(date(2026, 1, 1))
        self.assertEqual(check_in, date(2026, 1, 15))
        self.assertEqual(check_out, date(2026, 1, 17))

    def test_hotel_url_carries_the_shared_stay(self):
        url = hotel_stay.with_booking_stay_params(HOTEL_URL, STAY_IN, STAY_OUT)
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, '/hotel/sa/assila.ar.html')
        self.assertEqual(query['checkin'], ['2026-01-15'])
        self.assertEqual(query['checkout'], ['2026-01-17'])
        self.assertEqual(query['group_adults'], ['2'])
        self.assertEqual(query['group_children'], ['0'])
        self.assertEqual(query['no_rooms'], ['1'])
        self.assertEqual(query['selected_currency'], ['SAR'])

    def test_existing_stay_is_replaced_and_other_params_survive(self):
        url = hotel_stay.with_booking_stay_params(
            HOTEL_URL + '?checkin=2020-01-01&checkout=2020-01-02&lang=ar',
            STAY_IN, STAY_OUT)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['checkin'], ['2026-01-15'])
        self.assertEqual(query['checkout'], ['2026-01-17'])
        self.assertEqual(query['lang'], ['ar'])

    def test_rewrite_is_idempotent(self):
        once = hotel_stay.with_booking_stay_params(HOTEL_URL, STAY_IN, STAY_OUT)
        twice = hotel_stay.with_booking_stay_params(once, STAY_IN, STAY_OUT)
        self.assertEqual(once, twice)

    def test_non_property_booking_pages_are_untouched(self):
        for url in (
            'https://www.booking.com/city/sa/jeddah.ar.html',
            'https://www.booking.com/district/sa/jeddah/alandalus.ar.html',
            'https://www.booking.com/searchresults.ar.html?ss=jeddah',
            'https://example.com/hotel/sa/assila.ar.html',
        ):
            self.assertEqual(hotel_stay.with_booking_stay_params(url), url)

    def test_agent_pool_lookup_uses_the_dated_url(self):
        seen = {}

        class Pool:
            def get_page(self, url):
                seen['url'] = url
                return {'url': url, 'title': 'Hotel', 'content': 'room'}

            def page_failed(self, _url):
                return None

        agent._run_open_url(None, {'url': HOTEL_URL}, [], {},
                            evidence_pool=Pool())
        query = parse_qs(urlsplit(seen['url']).query)
        self.assertIn('checkin', query)
        self.assertIn('selected_currency', query)

    def test_browser_opens_the_property_with_the_stay(self):
        worker = browser.BrowserWorker(headless=True)
        opened = {}
        worker._ensure_page = lambda: object()

        def fake_open(_page, url, _timeout):
            opened['url'] = url
            return {'url': url, 'title': 'Hotel', 'text': '', 'error': None}

        worker._open_url_once = fake_open
        worker.open_url(HOTEL_URL)
        query = parse_qs(urlsplit(opened['url']).query)
        check_in, check_out = hotel_stay.booking_stay_window()
        self.assertEqual(query['checkin'], [check_in.isoformat()])
        self.assertEqual(query['checkout'], [check_out.isoformat()])


class ManagedChromeTests(unittest.TestCase):

    def test_explicit_chrome_path_is_used(self):
        handle = tempfile.NamedTemporaryFile(suffix='.exe', delete=False)
        handle.close()
        try:
            with patch.dict(os.environ,
                            {'BROWSER_EXECUTABLE_PATH': handle.name}, clear=False):
                self.assertEqual(
                    browser._managed_chrome_executable(), handle.name)
        finally:
            os.unlink(handle.name)

    def test_missing_explicit_path_does_not_fall_back_silently(self):
        with patch.dict(os.environ, {
                'BROWSER_EXECUTABLE_PATH': '/missing/chrome',
                'BROWSER_MANAGED_CHROME': ''}, clear=False):
            self.assertEqual(browser._managed_chrome_executable(), '')

    def test_managed_chrome_disabled_returns_empty(self):
        with patch.dict(os.environ, {
                'BROWSER_EXECUTABLE_PATH': '',
                'BROWSER_MANAGED_CHROME': '0'}, clear=False), \
                patch.object(browser.shutil, 'which', return_value='C:/Chrome/chrome.exe'), \
                patch.object(browser.os.path, 'isfile', return_value=True):
            self.assertEqual(browser._managed_chrome_executable(), '')

    def test_installed_chrome_is_found(self):
        with patch.dict(os.environ, {
                'BROWSER_EXECUTABLE_PATH': '',
                'BROWSER_MANAGED_CHROME': ''}, clear=False), \
                patch.object(browser.shutil, 'which',
                             side_effect=lambda name: (
                                 'C:/Chrome/chrome.exe'
                                 if name == 'google-chrome' else None)), \
                patch.object(browser.os.path, 'isfile',
                             side_effect=lambda path: (
                                 path == 'C:/Chrome/chrome.exe')):
            self.assertEqual(
                browser._managed_chrome_executable(), 'C:/Chrome/chrome.exe')

    def test_playwright_chromium_is_found_in_cache(self):
        cache = '/tmp/chromium-1243/chrome-linux64/chrome'
        with patch.dict(os.environ, {
                'BROWSER_EXECUTABLE_PATH': '',
                'BROWSER_MANAGED_CHROME': '1'}, clear=False), \
                patch.object(browser.glob, 'glob', return_value=[cache]), \
                patch.object(browser.os.path, 'isfile',
                             side_effect=lambda path: path == cache):
            self.assertEqual(browser._managed_chrome_executable(), cache)


class ChallengeShellTests(unittest.TestCase):

    class _Page:
        def __init__(self, html, text=''):
            self._html = html
            self._text = text
            self.url = HOTEL_URL

        def set_extra_http_headers(self, _headers):
            pass

        def goto(self, _url, **_kwargs):
            return types.SimpleNamespace(status=200)

        def wait_for_timeout(self, _ms):
            pass

        def title(self):
            return ''

        def evaluate(self, _script):
            return self._text

        def content(self):
            return self._html

    def _open(self, html, text=''):
        worker = browser.BrowserWorker(headless=True)
        page = self._Page(html, text)
        worker._ensure_page = lambda: page
        return worker.open_url(HOTEL_URL)

    def test_aws_waf_challenge_shell_is_reported_as_blocked(self):
        with patch.object(browser, '_CHALLENGE_WAIT_SECONDS', 0):
            result = self._open(
                '<html><body><div id="challenge-container"></div>'
                '<script>window.awsWafCookieDomainList = ["booking.com"]</script>'
                '</body></html>')
        self.assertEqual(result.get('error'), 'blocked')

    def test_a_short_real_page_is_not_blocked(self):
        result = self._open(
            '<html><body><p>Select dates to see prices</p></body></html>',
            'Select dates to see prices')
        self.assertIsNone(result.get('error'))


class CompetitorPromptStayTests(unittest.TestCase):

    def _payload(self):
        return {
            'city': 'جدة',
            'district': 'الروضة',
            'competitorScope': {'mode': 'district'},
            'comparisonTypes': [{'type': 'hotel', 'stars': '4'}],
        }

    def test_hotel_prompt_stops_on_a_blocked_page_and_keeps_listing_names(self):
        prompt = market_study.build_competitors_user_prompt(
            self._payload(), [], mode='generate')
        self.assertIn('تحديًا أمنيًا', prompt)
        self.assertIn('لا تُعد المحاولة', prompt)
        self.assertIn('صفحة قوائم أو صفحة حي', prompt)
        self.assertIn('source فارغ', prompt)


class VerifiedAreaTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'hotel-booking-stay.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _hotel_row(self):
        return {
            'name': 'فندق أسيال',
            'project_type': 'فندقي',
            'operation_type': 'تشغيل فندقي',
        }

    def test_cited_room_area_is_ignored_for_a_hotel_row(self):
        row = self._hotel_row()
        with self.app.app_context():
            self.module._apply_verified_competitor_area(
                row, {'area_sqm': '42', 'area_url': HOTEL_URL}, {HOTEL_URL})
        self.assertFalse(row.get('area_sqm'))
        self.assertFalse(row.get('area_from'))

    def test_property_area_is_rejected_for_a_hotel(self):
        row = self._hotel_row()
        with self.app.app_context():
            self.module._apply_verified_competitor_area(
                row, {'area_sqm': '5000', 'area_url': HOTEL_URL}, {HOTEL_URL})
        self.assertFalse(row.get('area_sqm'))

    def test_uncited_area_is_not_applied(self):
        row = self._hotel_row()
        with self.app.app_context():
            self.module._apply_verified_competitor_area(
                row, {'area_sqm': '42', 'area_url': HOTEL_URL}, set())
        self.assertFalse(row.get('area_sqm'))

    def test_non_room_areas_are_ignored(self):
        with self.app.app_context():
            areas = self.module._extract_room_areas(
                'قاعة اجتماعات 300 م² وغرفة ديلوكس 40 م²')
        self.assertEqual(areas, [40.0])

    def test_pool_hotel_without_area_stays_verified_from_stored_evidence(self):
        page = {
            'url': HOTEL_URL,
            'title': 'فندق أسيال',
            'content': 'غرفة ديلوكس — 500 ريال',
        }

        class Pool:
            def pages_for_name(self, _tokens, _needed):
                return [page]

        row = self._hotel_row()
        with self.app.app_context():
            verified = self.module._verify_row_from_pool(
                row, {'city': 'جدة'}, {}, Pool())
        self.assertTrue(verified)
        self.assertEqual(row.get('verify_state'), 'verified')

    def test_hotel_area_and_price_come_from_the_booking_block_only(self):
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
        rate['source_url'] = HOTEL_URL
        row = self._hotel_row()
        with self.app.app_context():
            applied = self.module._apply_booking_rate_block(
                row, {HOTEL_URL: {
                    'content': booking_rooms.format_rate_block(rate),
                }}, offer_lang='ar')
        self.assertTrue(applied)
        self.assertEqual(row['price_value'], '350')
        self.assertEqual(row['area_sqm'], '35')

    def test_hotel_expansion_is_deterministic_not_a_new_agent_search(self):
        axes = market_study.project_competitor_axes({
            'comparisonTypes': [{'type': 'hotel', 'stars': 4}],
        })
        with self.app.app_context():
            tasks = self.module._expansion_scan_tasks(
                {'city': 'جدة', 'district': 'الروضة',
                 'competitorScope': {'mode': 'district'},
                 'projectType': 'فندقي'},
                axes, axes, [], offer_lang='ar')
        self.assertEqual(tasks, [])

    def test_verification_prompt_uses_booking_property_pages(self):
        captured = {}

        def fake_call(_system, user, *_args, **_kwargs):
            captured['prompt'] = user
            return {'choices': [{'message': {
                'content': json.dumps({'exists': True, 'official_url': HOTEL_URL}),
                'annotations': [{'url_citation': {
                    'url': HOTEL_URL,
                    'title': 'فندق أسيال',
                    'content': 'غرفة ديلوكس 40 م²',
                }}],
            }}]}

        row = self._hotel_row()
        with self.app.app_context(), \
                patch.object(self.module, '_browse_agent_call', side_effect=fake_call):
            self.module._verify_competitor_row(row, {'city': 'جدة'}, {})
        self.assertIn('area_sqm', captured['prompt'])
        self.assertIn('تحديًا أمنيًا', captured['prompt'])
        self.assertFalse(row.get('area_sqm'))


if __name__ == '__main__':
    unittest.main()
