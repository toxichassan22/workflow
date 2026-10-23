"""Hotel price/area fallback through native web search.

Booking serves the agent a bot page, so hotel rows can stay empty even after
verification. The fallback accepts a cited price/area from a retrieved page
(Booking list page, booking engine, Agoda, official site), labels the row as
a fallback source, and keeps that labelled URL past the Booking-only filter.
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

import db  # noqa: E402

PRICE_URL = 'https://wa-hotel-jeddah.bookstaygo.com/de'
AREA_URL = 'https://www.agoda.com/wa-hotel/hotel/jeddah-sa.html'


def _hotel_row(**extra):
    row = {
        'name': 'WA Hotel Jeddah',
        'project_type': 'فندقي',
        'operation_type': 'تشغيل فندقي',
    }
    row.update(extra)
    return row


class HotelNativeFallbackTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'hotel-fallback.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _parsed(self):
        return {
            'name': 'WA Hotel Jeddah',
            'price_value': '140',
            'price_currency': 'USD',
            'price_type': 'يبدأ من',
            'area_from': '42',
            'area_to': '93',
            'area_sqm': '42-93',
            'price_source_url': PRICE_URL,
            'area_source_url': AREA_URL,
            'source_name': 'bookstaygo وAgoda',
        }

    def test_cited_price_and_area_are_applied_and_labelled(self):
        row = _hotel_row()
        with self.app.app_context():
            applied = self.module._apply_hotel_fallback_evidence(
                row, self._parsed(), {PRICE_URL, AREA_URL})
        self.assertTrue(applied)
        self.assertTrue(row.get('fallback_source'))
        self.assertEqual(row.get('price_type'), 'يبدأ من')
        self.assertEqual(row.get('price_currency'), 'SAR')
        self.assertTrue(str(row.get('price_value') or '').strip())
        self.assertEqual(row.get('price_cache', {}).get('original_currency'), 'USD')
        self.assertEqual(row.get('area_mode'), 'range')
        self.assertEqual((row.get('area_from'), row.get('area_to')), ('42', '93'))
        self.assertIn(PRICE_URL, row.get('source_urls') or [])
        self.assertIn(AREA_URL, row.get('source_urls') or [])
        self.assertIn(PRICE_URL, row['field_sources']['price_value'])
        self.assertIn(AREA_URL, row['field_sources']['area_from'])
        self.assertIn('مصدر بديل', row.get('source') or '')
        self.assertIn('مصدر بديل', row.get('notes') or '')
        self.assertEqual(row.get('verify_state'), 'verified')

    def test_uncited_sources_are_rejected(self):
        row = _hotel_row()
        with self.app.app_context():
            applied = self.module._apply_hotel_fallback_evidence(
                row, self._parsed(), set())
        self.assertFalse(applied)
        self.assertFalse(row.get('price_value'))
        self.assertFalse(row.get('area_sqm'))
        self.assertFalse(row.get('fallback_source'))

    def test_existing_price_is_not_overwritten(self):
        row = _hotel_row(price_value='999', price_currency='SAR')
        with self.app.app_context():
            applied = self.module._apply_hotel_fallback_evidence(
                row, self._parsed(), {PRICE_URL, AREA_URL})
        self.assertTrue(applied)
        self.assertEqual(row.get('price_value'), '999')
        self.assertEqual(row.get('area_mode'), 'range')

    def test_uncited_price_does_not_block_a_cited_area(self):
        row = _hotel_row()
        parsed = dict(self._parsed(), price_source_url='https://example.com/ghost')
        with self.app.app_context():
            applied = self.module._apply_hotel_fallback_evidence(
                row, parsed, {AREA_URL})
        self.assertTrue(applied)
        self.assertFalse(row.get('price_value'))
        self.assertEqual(row.get('area_mode'), 'range')

    def test_classifieds_are_not_accepted_as_fallback_sources(self):
        row = _hotel_row()
        parsed = dict(
            self._parsed(),
            price_source_url='https://www.bayut.sa/listing/wa-hotel',
            area_source_url='https://www.bayut.sa/listing/wa-hotel')
        with self.app.app_context():
            applied = self.module._apply_hotel_fallback_evidence(
                row, parsed, {'https://www.bayut.sa/listing/wa-hotel'})
        self.assertFalse(applied)
        self.assertFalse(row.get('price_value'))
        self.assertFalse(row.get('fallback_source'))

    def test_labelled_fallback_url_survives_the_booking_only_filter(self):
        url = 'https://www.agoda.com/wa-hotel/hotel/jeddah-sa.html'
        row = _hotel_row(source_url=url, source_urls=[url],
                         fallback_source=True)
        with self.app.app_context():
            self.module._drop_banned_competitor_listing_urls(row)
        self.assertIn(url, row.get('source_urls') or [])

    def test_unlabelled_non_booking_url_is_still_dropped(self):
        url = 'https://www.agoda.com/wa-hotel/hotel/jeddah-sa.html'
        row = _hotel_row(source_url=url, source_urls=[url])
        with self.app.app_context():
            self.module._drop_banned_competitor_listing_urls(row)
        self.assertNotIn(url, row.get('source_urls') or [])

    def test_native_search_call_uses_the_server_web_tool_and_applies_citations(self):
        captured = {}

        def fake_call(_system, _prompt, _usage_ctx, **kwargs):
            captured.update(kwargs)
            return {'choices': [{'message': {
                'content': json.dumps(self._parsed(), ensure_ascii=False),
                'annotations': [
                    {'url_citation': {'url': PRICE_URL, 'title': 'WA Hotel',
                                      'content': 'From 108 CAD per night'}},
                    {'url_citation': {'url': AREA_URL, 'title': 'WA Hotel Agoda',
                                      'content': '42 m²'}},
                ],
            }}]}

        row = _hotel_row()
        with self.app.app_context(), \
                patch.object(self.module, '_browse_agent_call', side_effect=fake_call):
            applied = self.module._hotel_native_fallback_search(
                row, {'city': 'جدة'}, {})
        self.assertTrue(applied)
        self.assertFalse(captured.get('local_tools'))
        self.assertEqual(captured.get('server_tools'),
                         [{'type': 'openrouter:web_search'}])
        self.assertEqual(captured.get('tool_choice'),
                         {'type': 'openrouter:web_search'})
        self.assertTrue(str(row.get('price_value') or '').strip())
        self.assertEqual(row.get('area_mode'), 'range')


if __name__ == '__main__':
    unittest.main()
