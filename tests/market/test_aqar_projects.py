"""The aqar projects directory is read deterministically, never by a model."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import aqar_projects  # noqa: E402


_CARDS_HTML = """
<html><body>
<a href="/المشاريع-العقارية/شركة-ابياتنا-التطويرية-255/أبياتنا-هيلز-790">
  <div>مميز</div><div>شقق للبيع</div><div>متاح</div>
  <div>أبياتنا هيلز</div><div>يبدأ من 366.9 ألف §</div><div>ريال</div>
  <div>حي الأمير عبدالمجيد ، جدة ، جدة</div>
</a>
<a href="/المشاريع-العقارية/شركة-دبيار-12/مكتب-النخبة-44">
  <div>مكاتب للبيع</div><div>مكتب النخبة</div>
  <div>يبدأ من 2 مليون §</div><div>حي الشاطئ ، جدة ، جدة</div>
</a>
<a href="/المشاريع-العقارية/شركة-الياقوت-9/شقق-الياقوت-51">
  <div>شقق للإيجار</div><div>شقق الياقوت</div>
  <div>يبدأ من 30 ألف §</div><div>حي الحمراء ، جدة ، جدة</div>
</a>
<a href="/المشاريع-العقارية/جدة">جدة</a>
</body></html>
"""

_DETAIL_TEXT = """
الوحدة
المساحات
من 178 م² إلى 220 م²
الأسعار
من 366,905 إلى 812,400 §
ريال
حي الأمير عبدالمجيد ، جدة ، جدة
"""

_NO_PRICE_CARD = """
<a href="/المشاريع-العقارية/شركة-الواجهة-4/برج-الواجهة-77">
  <div>تحت الإنشاء</div><div>برج الواجهة</div>
  <div>حي الشاطئ ، جدة ، جدة</div>
</a>
"""


class _Session:
    def __init__(self, html=_CARDS_HTML, detail=_DETAIL_TEXT):
        self.html = html
        self.detail = detail
        self.opened = []

    def fetch_html(self, url, timeout=None):
        self.fetched = url
        return {'html': self.html, 'final_url': url, 'error': ''}

    def open_url(self, url):
        self.opened.append(url)
        return {'text': self.detail, 'error': ''}


class AqarCardTests(unittest.TestCase):

    def test_cards_carry_name_type_operation_price_and_district(self):
        cards = aqar_projects.parse_cards(_CARDS_HTML)
        self.assertEqual(len(cards), 3)
        first = cards[0]
        self.assertEqual(first['name'], 'أبياتنا هيلز')
        self.assertEqual(first['project_type'], 'سكني')
        self.assertEqual(first['operation'], 'بيع')
        self.assertEqual(first['price_from'], 366900)
        self.assertEqual(first['district'], 'الأمير عبدالمجيد')
        self.assertEqual(first['city'], 'جدة')
        self.assertEqual(first['developer'], 'شركة ابياتنا التطويرية')
        self.assertEqual(cards[1]['project_type'], 'تجاري')
        self.assertEqual(cards[1]['price_from'], 2000000)
        self.assertEqual(cards[2]['operation'], 'إيجار')

    def test_detail_carries_the_real_ranges(self):
        detail = aqar_projects.parse_detail(_DETAIL_TEXT)
        self.assertEqual((detail['area_from'], detail['area_to']), (178, 220))
        self.assertEqual((detail['price_from'], detail['price_to']),
                         (366905, 812400))
        self.assertEqual(detail['district'], 'الأمير عبدالمجيد')
        self.assertEqual(detail['city'], 'جدة')

    def test_a_starting_price_is_not_written_as_a_range(self):
        card = aqar_projects.parse_cards(_CARDS_HTML)[0]
        row = aqar_projects.project_row(card, {})
        self.assertEqual(row['price_type'], 'يبدأ من')
        self.assertEqual(row['price_value'], '366900')
        self.assertEqual(row['price_from'], '')
        self.assertEqual(row['price_to'], '')
        self.assertEqual(row['field_sources']['price_value'], [card['url']])

    def test_a_single_detail_price_is_also_a_starting_price(self):
        card = aqar_projects.parse_cards(_CARDS_HTML)[0]
        detail = {'price_from': 500000, 'price_to': 500000}
        row = aqar_projects.project_row(card, detail)
        self.assertEqual(row['price_type'], 'يبدأ من')
        self.assertEqual(row['price_value'], '500000')
        self.assertEqual(row['price_to'], '')


class AqarProjectLinkTests(unittest.TestCase):

    def test_every_named_project_is_a_link_even_without_a_price(self):
        links = aqar_projects.parse_project_links(_CARDS_HTML + _NO_PRICE_CARD)
        self.assertEqual(len(links), 4)
        names = [link['name'] for link in links]
        self.assertIn('أبياتنا هيلز', names)
        self.assertIn('برج الواجهة', names)
        self.assertTrue(links[0]['url'].startswith('https://sa.aqar.fm/'))

    def test_the_directory_returns_links_and_price_cards_together(self):
        catalog = aqar_projects.load_projects(_Session(), 'جدة')
        self.assertEqual(len(catalog['links']), 3)
        self.assertEqual(len(catalog['cards']), 3)
        self.assertEqual(catalog['error'], '')

    def test_a_typed_name_matches_the_projects_own_name(self):
        links = aqar_projects.parse_project_links(_CARDS_HTML + _NO_PRICE_CARD)
        for typed in ('أبياتنا هيلز', 'مشروع أبياتنا هيلز السكني',
                      'أبياتنا هيلز جدة'):
            match = aqar_projects.match_project_link(links, typed, city='جدة')
            self.assertIsNotNone(match, typed)
            self.assertIn('أبياتنا', match['url'])
        self.assertIsNotNone(
            aqar_projects.match_project_link(links, 'برج الواجهة', city='جدة'))

    def test_one_shared_word_does_not_claim_a_different_project(self):
        links = aqar_projects.parse_project_links(_CARDS_HTML + _NO_PRICE_CARD)
        self.assertIsNone(aqar_projects.match_project_link(
            links, 'برج الواجهة الذهبية', city='جدة'))
        self.assertIsNone(aqar_projects.match_project_link(
            links, 'مجمع النخيل', city='جدة'))

    def test_a_card_less_project_is_still_read_by_name(self):
        links = aqar_projects.parse_project_links(_NO_PRICE_CARD)
        session = _Session(html=_NO_PRICE_CARD)
        row = aqar_projects.project_for_link(session, links[0])
        self.assertEqual(row['name'], 'برج الواجهة')
        self.assertEqual(row['source_url'], links[0]['url'])
        self.assertEqual((row['price_from'], row['price_to']),
                         ('366905', '812400'))


class AqarScanTests(unittest.TestCase):

    def test_scan_filters_by_axis_and_reads_the_detail_page(self):
        session = _Session()
        result = aqar_projects.scan(
            session, 'جدة', pairs=[('سكني', 'بيع')], limit=4)
        self.assertEqual(result['cards'], 3)
        self.assertEqual(len(result['project_links']), 3)
        self.assertEqual(result['matched'], 1)
        self.assertEqual([row['name'] for row in result['rows']],
                         ['أبياتنا هيلز'])
        row = result['rows'][0]
        self.assertEqual(row['row_source'], 'aqar')
        self.assertEqual(row['source'], 'عقار')
        self.assertEqual(row['price_type'], 'نطاق سعري')
        self.assertEqual(row['price_from'], '366905')
        self.assertEqual(row['price_to'], '812400')
        self.assertEqual(row['area_from'], '178')
        self.assertEqual(row['area_to'], '220')
        self.assertEqual(row['district'], 'الأمير عبدالمجيد')
        self.assertEqual(row['verify_state'], 'verified')
        self.assertEqual(session.opened, [row['source_url']])
        self.assertIn('المشاريع-العقارية', session.fetched)

    def test_a_district_scope_keeps_only_that_district(self):
        session = _Session()
        result = aqar_projects.scan(
            session, 'جدة', district='حي الشاطئ',
            pairs=[('سكني', 'بيع'), ('تجاري', 'بيع')], limit=4)
        self.assertEqual([row['name'] for row in result['rows']],
                         ['مكتب النخبة'])
        # The client's own district text must travel on the row so the
        # downstream exact-match scope filter keeps it.
        self.assertEqual(result['rows'][0]['district'], 'حي الشاطئ')
        other = aqar_projects.scan(
            _Session(), 'جدة', district='حي الأندلس',
            pairs=[('سكني', 'بيع')], limit=4)
        self.assertEqual(other['rows'], [])
        self.assertEqual(other['matched'], 0)

    def test_the_limit_bounds_the_detail_reads(self):
        session = _Session()
        result = aqar_projects.scan(
            session, 'جدة', pairs=[('سكني', 'بيع'), ('تجاري', 'بيع'),
                                   ('سكني', 'إيجار')], limit=2)
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(len(session.opened), 2)

    def test_an_english_offer_gets_an_english_row_note(self):
        result = aqar_projects.scan(
            _Session(), 'جدة', pairs=[('سكني', 'بيع')], limit=1,
            offer_lang='en')
        self.assertIn('project page on aqar', result['rows'][0]['notes'])
        self.assertNotIn('صفحة المشروع', result['rows'][0]['notes'])


if __name__ == '__main__':
    unittest.main()
