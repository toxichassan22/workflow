"""Deterministic aqar advertising evidence inside the market summary."""

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
import market_study


_AQAR_TEXT = (
    'مميز 3,200 \u00a7 ريال شقة للإيجار في شارع الحنفي, حي الروضة, '
    'مدينة جدة, منطقة مكة المكرمة حي الروضة, جدة '
    'مميز 12,000 \u00a7 ريال شقة للإيجار في شارع آخر, حي الاندلس, '
    'مدينة جدة, منطقة مكة المكرمة حي الاندلس, جدة '
    'مميز 2,500,000 \u00a7 ريال فيلا للبيع في شارع الأمير, حي الاندلس, '
    'مدينة جدة, منطقة مكة المكرمة حي الاندلس, جدة '
    'مميز 8,500 \u00a7 ريال شقة للإيجار في شارع ثالث, حي الاندلس, '
    'مدينة جدة, منطقة مكة المكرمة حي الاندلس, جدة'
)


class SummaryAqarEvidenceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'summary-aqar.db')
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
    def _profile():
        return {'kinds': {'residential'}, 'source_kinds': ['سكني']}

    def test_text_cards_carry_price_description_and_district(self):
        module = self.module
        cards = module._aqar_cards_from_text(_AQAR_TEXT, 'https://sa.aqar.fm/x')
        self.assertEqual(len(cards), 4)
        self.assertEqual(module._aqar_price_text(cards[0]['price']), '3,200')
        self.assertIn('شقة للإيجار', cards[0]['desc'])
        self.assertIn('حي الروضة', cards[0]['loc'])
        self.assertEqual(module._aqar_price_text(cards[2]['price']), '2,500,000')

    def test_listing_pages_follow_the_project_activities(self):
        module = self.module
        listing = [
            ('https://sa.aqar.fm/villas-rent', 'aqar.fm — فلل إيجار — جدة'),
            ('https://sa.aqar.fm/villas-sale', 'aqar.fm — فلل بيع — جدة'),
            ('https://sa.aqar.fm/shops-rent', 'aqar.fm — محلات إيجار — جدة'),
            ('https://sa.aqar.fm/offices-rent', 'aqar.fm — مكاتب إيجار — جدة'),
        ]
        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value=self._profile()), \
                patch.object(module.market_study, '_payload_operations',
                             return_value={'إيجار', 'بيع'}), \
                patch.object(module.market_study, '_listing_urls',
                             return_value=iter(listing)):
            pages = module._summary_aqar_pages({'city': 'جدة'})
        self.assertEqual([page['label'] for page in pages],
                         ['aqar.fm — فلل إيجار — جدة',
                          'aqar.fm — فلل بيع — جدة'])
        self.assertNotIn('offices-rent', [page['url'] for page in pages])

    def test_evidence_keeps_the_district_cards_and_separates_sale_from_rent(self):
        module = self.module
        pages = [
            ('https://sa.aqar.fm/villas-sale', 'aqar.fm — فلل بيع — جدة'),
            ('https://sa.aqar.fm/villas-rent', 'aqar.fm — فلل إيجار — جدة'),
        ]

        class Session:
            def open_url(self, url):
                return {'text': _AQAR_TEXT, 'final_url': url, 'error': None}

        payload = {'city': 'جدة', 'district': 'حي الاندلس'}
        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value=self._profile()), \
                patch.object(module.market_study, '_payload_operations',
                             return_value={'إيجار', 'بيع'}), \
                patch.object(module.market_study, '_listing_urls',
                             return_value=iter(pages)):
            result = module._summary_aqar_evidence(
                payload, Session(), deadline=time.time() + 30)
        self.assertIsNotNone(result)
        self.assertIn('## AQAR_LISTINGS ##', result['block'])
        self.assertIn('2,500,000', result['block'])
        self.assertIn('حي الاندلس', result['block'])
        self.assertIn('[فلل بيع]', result['block'])
        self.assertIn('[فلل إيجار]', result['block'])
        self.assertNotIn('حي الروضة', result['block'])
        self.assertEqual(result['rows'], 6)

    def test_a_page_error_is_not_claimed_as_evidence(self):
        module = self.module

        class Session:
            def open_url(self, url):
                return {'error': 'timeout'}

        pages = [{'url': 'https://sa.aqar.fm/x',
                  'label': 'aqar.fm — فلل بيع — جدة'}]
        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value=self._profile()), \
                patch.object(module.market_study, '_payload_operations',
                             return_value={'بيع'}), \
                patch.object(module.market_study, '_listing_urls',
                             return_value=iter(pages)):
            result = module._summary_aqar_evidence(
                {'city': 'جدة'}, Session(), deadline=time.time() + 30)
        self.assertIsNone(result)

    def test_evidence_lands_in_the_pool_and_suppresses_the_search_job(self):
        module = self.module
        added = []

        class Pool:
            def add_page(self, url, title='', content='', final_url='', via=''):
                added.append({'url': url, 'content': content, 'via': via})

        class Session:
            def open_url(self, url):
                return {'text': _AQAR_TEXT, 'final_url': url, 'error': None}

        pages = [('https://sa.aqar.fm/villas-sale',
                  'aqar.fm — فلل بيع — جدة')]
        payload = {'city': 'جدة', 'district': 'الاندلس'}
        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value=self._profile()), \
                patch.object(module.market_study, '_payload_operations',
                             return_value={'بيع'}), \
                patch.object(module.market_study, '_listing_urls',
                             return_value=iter(pages)):
            result = module._summary_aqar_evidence_into(
                payload, Session(), Pool(), deadline=time.time() + 30)
        self.assertIsNotNone(result)
        self.assertTrue(added)
        self.assertEqual(added[0]['via'], 'aqar_sample')
        self.assertIn('AQAR_LISTINGS', added[0]['content'])
        self.assertEqual(payload['_summaryAqarSample']['rows'], result['rows'])

        jobs = module.build_summary_research_jobs(
            payload,
            {'transactions_and_rents': ['aqar.fm', 'red.rega.gov.sa']},
            False, set(),
            {'cities': [{'name': 'جدة', 'districts': []}]},
            depth='full')
        hosts = [host for _group, job_hosts, _city, _district in jobs
                 for host in job_hosts]
        self.assertNotIn('aqar.fm', hosts)
        self.assertIn('red.rega.gov.sa', hosts)


    def test_dom_cards_follow_the_price_paragraph_not_its_position(self):
        module = self.module

        class Page:
            def evaluate(self, script):
                return [
                    {'url': 'https://sa.aqar.fm/villa-1',
                     'price': '35,000 \u00a7 ريال /سنوي', 'basis': 'سنوي',
                     'desc': 'فيلا للإيجار في شارع الوفاء, حي الوفاء',
                     'loc': 'حي الرياض, جدة'},
                    {'url': 'https://sa.aqar.fm/villa-2',
                     'price': '80,000', 'basis': 'سنوي',
                     'desc': 'فيلا للإيجار في شارع أبو يوسف',
                     'loc': 'حي اللؤلؤ, جدة'},
                ]

        class Session:
            _page = Page()

            def open_url(self, url):
                return {'text': '', 'final_url': url, 'error': None}

        pages = [('https://sa.aqar.fm/villas-rent',
                  'aqar.fm — فلل إيجار — جدة')]
        with patch.object(module.market_study, 'summary_activity_profile',
                          return_value=self._profile()), \
                patch.object(module.market_study, '_payload_operations',
                             return_value={'إيجار'}), \
                patch.object(module.market_study, '_listing_urls',
                             return_value=iter(pages)):
            result = module._summary_aqar_evidence(
                {'city': 'جدة', 'district': 'الاندلس'}, Session(),
                deadline=time.time() + 30)
        self.assertIsNotNone(result)
        self.assertIn('35,000', result['block'])
        self.assertIn('price_basis: سنوي', result['block'])
        self.assertIn('https://sa.aqar.fm/villa-1', result['block'])
        self.assertIn('فيلا للإيجار', result['block'])
        self.assertEqual(result['rows'], 2)


if __name__ == '__main__':
    unittest.main()
