"""Deterministic Booking evidence inside the market summary."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / 'modules' / 'web_browse')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import db


class SummaryBookingEvidenceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-booking.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def _scan_reply():
        rows = [
            {
                'name': 'فندق الاختبار', 'hotel_stars': '4',
                'price_type': 'نطاق أسعار الغرف',
                'price_from': '392', 'price_to': '1048',
                'area_from': '42', 'area_to': '85',
                'source_url': 'https://www.booking.com/hotel/sa/test.html',
                'notes': 'نطاق أسعار الغرف مقابل ليلة على Booking '
                         '(الأصلي + الضرائب): 392–1048 ر.س',
            },
            {
                'name': 'فندق بلا سعر', 'hotel_stars': '4',
                'source_url': 'https://www.booking.com/hotel/sa/no-price.html',
                'notes': 'صفحة الفندق على Booking.com لم تُرجع بلوك سعر/مساحة',
            },
        ]
        annotations = [
            {'type': 'url_citation', 'url_citation': {
                'url': 'https://www.booking.com/searchresults.html?dest_id=1',
                'title': 'نتائج Booking', 'content': 'فنادق جدة'}},
            {'type': 'url_citation', 'url_citation': {
                'url': 'https://www.booking.com/hotel/sa/test.html',
                'title': 'فندق الاختبار', 'content': 'غرفة 42 م²'}},
        ]
        return {
            'parsed': {'competitors': rows, 'notes': 'تم جلب فندقين'},
            'reply': {'choices': [{'message': {
                'content': json.dumps({'competitors': rows}, ensure_ascii=False),
                'annotations': annotations,
            }}]},
        }

    def test_the_block_carries_prices_areas_and_the_stay_window(self):
        module = self.module
        payload = {'city': 'جدة', 'district': 'الحمراء'}
        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value={'kinds': {'hospitality'}}), \
                patch.object(module, '_booking_hotel_scan',
                             return_value=self._scan_reply()):
            result = module._summary_booking_evidence(
                payload, {'city': 'جدة'}, 'tenant-1',
                deadline=time.time() + 30)
        self.assertIsNotNone(result)
        self.assertEqual(result['rows'], 2)
        self.assertEqual(result['priced'], 1)
        self.assertIn('## BOOKING_HOTEL_SAMPLE ##', result['block'])
        self.assertIn('فندق الاختبار', result['block'])
        self.assertIn('392–1048', result['block'])
        self.assertIn('42–85 م²', result['block'])
        self.assertIn('https://www.booking.com/hotel/sa/test.html',
                      result['block'])
        self.assertIn('ليلة', result['block'])

    def test_a_scan_without_any_rate_does_not_claim_evidence(self):
        module = self.module
        reply = self._scan_reply()
        reply['parsed']['competitors'] = [reply['parsed']['competitors'][1]]
        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value={'kinds': {'hospitality'}}), \
                patch.object(module, '_booking_hotel_scan', return_value=reply):
            result = module._summary_booking_evidence(
                {'city': 'جدة'}, {}, 'tenant-1', deadline=time.time() + 30)
        self.assertIsNone(result)

    def test_evidence_lands_in_the_pool_and_suppresses_the_search_job(self):
        module = self.module
        payload = {'city': 'جدة', 'district': 'الحمراء'}
        added = []

        class Pool:
            def add_page(self, url, title='', content='', final_url='', via=''):
                added.append({'url': url, 'content': content, 'via': via})

        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value={'kinds': {'hospitality'}}), \
                patch.object(module, '_booking_hotel_scan',
                             return_value=self._scan_reply()):
            result = module._summary_booking_evidence_into(
                payload, {'city': 'جدة'}, 'tenant-1', Pool(),
                deadline=time.time() + 30)
        self.assertIsNotNone(result)
        self.assertTrue(added)
        self.assertEqual(added[0]['via'], 'booking_sample')
        self.assertIn('BOOKING_HOTEL_SAMPLE', added[0]['content'])
        self.assertEqual(payload['_summaryBookingSample'],
                         {'rows': 2, 'priced': 1})

        jobs = module.build_summary_research_jobs(
            payload,
            {'hospitality_and_tourism': ['booking.com', 'mt.gov.sa']},
            False, set(),
            {'cities': [{'name': 'جدة', 'districts': []}]},
            depth='full')
        hosts = [host for _group, job_hosts, _city, _district in jobs
                 for host in job_hosts]
        self.assertNotIn('booking.com', hosts)
        self.assertIn('mt.gov.sa', hosts)
        without = module.build_summary_research_jobs(
            {'city': 'جدة'},
            {'hospitality_and_tourism': ['booking.com']},
            False, set(),
            {'cities': [{'name': 'جدة', 'districts': []}]},
            depth='full')
        self.assertIn('booking.com',
                      [host for _g, hs, _c, _d in without for host in hs])

    def test_the_wrapper_runs_booking_before_the_research_fan_out(self):
        module = self.module
        calls = []
        with patch.object(module, '_summary_booking_stage_allowed',
                          return_value=True), \
                patch.object(module, '_summary_booking_selected',
                             return_value=True), \
                patch.object(module, '_summary_booking_evidence_into',
                             side_effect=lambda *a, **k: calls.append('booking')), \
                patch.object(module, '_run_market_summary_research',
                             side_effect=lambda *a, **k:
                             calls.append('research') or {'success': True}):
            result = module._run_market_summary_research_with_booking(
                {'city': 'جدة'}, {}, object(), time.time() + 30,
                data={}, tenant_id='t1')
        self.assertEqual(calls, ['booking', 'research'])
        self.assertTrue(result['success'])

    def test_the_wrapper_leaves_unittest_runs_offline(self):
        module = self.module
        calls = []
        with patch.object(module, '_summary_booking_stage_allowed',
                          return_value=False), \
                patch.object(module, '_summary_booking_evidence_into',
                             side_effect=lambda *a, **k: calls.append('booking')), \
                patch.object(module, '_run_market_summary_research',
                             side_effect=lambda *a, **k:
                             calls.append('research') or {'success': True}):
            module._run_market_summary_research_with_booking(
                {'city': 'جدة'}, {}, object(), time.time() + 30,
                data={}, tenant_id='t1')
        self.assertEqual(calls, ['research'])


if __name__ == '__main__':
    unittest.main()
