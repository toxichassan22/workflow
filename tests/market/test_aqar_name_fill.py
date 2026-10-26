"""Named residential and commercial rows are completed from aqar's projects."""

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
import aqar_projects  # noqa: E402


_DIRECTORY_HTML = """
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
<a href="/المشاريع-العقارية/شركة-الواجهة-4/برج-الواجهة-77">
  <div>تحت الإنشاء</div><div>برج الواجهة</div>
  <div>حي الشاطئ ، جدة ، جدة</div>
</a>
</body></html>
"""

_DETAIL_RANGE = """
الوحدة
المساحات
من 178 م² إلى 220 م²
الأسعار
من 366,905 إلى 812,400 §
ريال
حي الأمير عبدالمجيد ، جدة ، جدة
"""

_DETAIL_WITHOUT_PRICE = """
المساحات
من 90 م² إلى 140 م²
حي الشاطئ ، جدة ، جدة
"""

_LINKS = aqar_projects.parse_project_links(_DIRECTORY_HTML)


def _link_url(word):
    return next(link['url'] for link in _LINKS if word in link['url'])


_ABYATNA_URL = _link_url('أبياتنا')
_TOWER_URL = _link_url('الواجهة')

_LISTING_URL = 'https://sa.aqar.fm/شقق-للبيع/جدة/12345'
_LISTING_HTML = """
<html><body>
<a href="/شقق-للبيع/جدة/12345">
  <div>شقة للبيع في مشروع مرقاة الشاطئ</div><div>حي الشاطئ ، جدة</div>
  <div>1,250,000 ريال</div>
</a>
<a href="/عقارات-للبيع/جدة/999">
  <div>أرض للبيع في حي النخبة</div>
</a>
</body></html>
"""
_LISTING_PAGE = {
    'final_url': _LISTING_URL,
    'title': 'شقة للبيع في مرقاة الشاطئ | عقار',
    'text': 'السعر المطلوب 1,250,000 ريال\nالمساحة 240 م²\nحي الشاطئ ، جدة',
}


class _Session:
    def __init__(self, details=None, html=_DIRECTORY_HTML, pages=None):
        self.html = html
        self.details = details or {}
        self.pages = pages or {}
        self.fetched = []
        self.opened = []
        self.closed = False

    def fetch_html(self, url, timeout=None):
        self.fetched.append(url)
        return {'html': self.pages.get(url, self.html), 'error': ''}

    def open_url(self, url):
        self.opened.append(url)
        value = self.details.get(url, '')
        if isinstance(value, dict):
            return value
        return {'text': value, 'error': ''}

    def close(self):
        self.closed = True


class AqarNameFillTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'aqar-name-fill.db')
        import app as application_module
        cls.module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        cls.module.UPLOADS_DIR = os.path.join(cls.temp_dir.name, 'uploads')
        os.makedirs(cls.module.UPLOADS_DIR, exist_ok=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _fill(self, rows, details, payload=None, pages=None):
        session = _Session(details, pages=pages)
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=session):
            filled = self.module._fill_project_rows_from_aqar(
                rows, payload or {'city': 'جدة'}, {}, tenant_id=None)
        return filled, session

    def _listing_pages(self):
        urls = [url for url, _label in self.module.market_study._listing_urls(
            ['سكني'], {'بيع'}, 'جدة')]
        return {url: _LISTING_HTML for url in urls}

    def test_a_single_listed_unit_gets_its_asking_price_and_area(self):
        row = {'name': 'مرقاة الشاطئ', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        filled, session = self._fill(
            [row], {_LISTING_URL: _LISTING_PAGE}, pages=self._listing_pages())
        self.assertEqual(filled, 1)
        self.assertEqual(row['price_type'], 'سعر الوحدة')
        self.assertEqual(row['price_value'], '1250000')
        self.assertEqual(row['area_sqm'], '240')
        self.assertEqual(row['source'], 'عقار')
        self.assertEqual(row['source_url'], _LISTING_URL)
        self.assertEqual(row['row_source'], 'aqar')
        self.assertEqual(row['verify_state'], 'verified')
        self.assertIn(_LISTING_URL, session.opened)

    def test_a_listing_that_does_not_name_the_row_is_rejected(self):
        row = {'name': 'مرقاة الشاطئ', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        other_page = dict(_LISTING_PAGE, title='شقة للبيع في حي السلامة | عقار',
                          text='السعر 900,000 ريال\nالمساحة 180 م²')
        filled, _session = self._fill(
            [row], {_LISTING_URL: other_page}, pages=self._listing_pages())
        self.assertEqual(filled, 0)
        self.assertIsNone(row.get('source_url'))
        self.assertFalse(row.get('price_value'))
        self.assertIn('إعلانات عقار', row.get('notes') or '')

    def test_a_chosen_property_kind_reads_only_its_own_listing_page(self):
        def listing_url(unit_types):
            return [url for url, _label in
                    self.module.market_study._listing_urls(
                        ['سكني'], {'بيع'}, 'جدة', unit_types)]

        villa = listing_url(['فيلا مستقلة'])[0]
        flats = listing_url(['شقة'])[0]
        # The villa page carries no advertisement of this project, so only
        # the flat page can satisfy the control pass below.
        pages = {villa: '<html><body></body></html>', flats: _LISTING_HTML}

        def row():
            return {'name': 'مرقاة الشاطئ', 'project_type': 'سكني',
                    'operation_type': 'بيع'}

        # No kind selected keeps the whole residential set.
        _filled, session = self._fill(
            [row()], {}, payload={'city': 'جدة'}, pages=pages)
        self.assertIn(flats, session.fetched)

        _filled, session = self._fill(
            [row()], {},
            payload={'city': 'جدة',
                     'competitorScope': {'mode': 'district',
                                         'unit_types': ['فيلا مستقلة']}},
            pages=pages)
        self.assertIn(villa, session.fetched)
        self.assertNotIn(flats, session.fetched)

    def test_a_blocked_directory_is_reported_not_treated_as_an_empty_one(self):
        class _Blocked:
            def fetch_html(self, url, timeout=None):
                return {'html': '', 'error': 'access_denied'}

            def open_url(self, url):
                return {'text': '', 'error': ''}

            def close(self):
                pass

        row = {'name': 'مرقاة الشاطئ', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=_Blocked()):
            self.module._fill_project_rows_from_aqar(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        note = row.get('notes') or ''
        self.assertIn('تعذر قراءة دليل المشاريع', note)
        self.assertIn('access_denied', note)
        self.assertNotIn('لم يُعثر', note)

    def test_a_blocked_listing_page_is_reported_not_read_as_an_empty_one(self):
        directory_url = self.module.aqar_projects.build_projects_url('جدة')

        class _ListingsBlocked:
            def fetch_html(self, url, timeout=None):
                if url == directory_url:
                    return {'html': _DIRECTORY_HTML, 'error': ''}
                return {'html': '', 'error': 'access_denied'}

            def open_url(self, url):
                return {'text': '', 'error': ''}

            def close(self):
                pass

        row = {'name': 'مرقاة الشاطئ', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        with self.app.app_context(), \
                patch.object(self.module, '_market_browser_session',
                             return_value=_ListingsBlocked()):
            self.module._fill_project_rows_from_aqar(
                [row], {'city': 'جدة'}, {}, tenant_id=None)
        note = row.get('notes') or ''
        self.assertIn('تعذر قراءة صفحات إعلانات عقار', note)
        self.assertIn('access_denied', note)

    def test_a_single_word_name_is_not_matched_to_an_ad(self):
        row = {'name': 'المرقاة', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        filled, session = self._fill(
            [row], {_LISTING_URL: _LISTING_PAGE}, pages=self._listing_pages())
        self.assertEqual(filled, 0)
        self.assertEqual(len(session.fetched), 1)
        self.assertEqual(session.opened, [])

    def test_a_named_residential_row_gets_its_project_page_figures(self):
        row = {'name': 'أبياتنا هيلز', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        filled, session = self._fill([row], {_ABYATNA_URL: _DETAIL_RANGE})
        self.assertEqual(filled, 1)
        self.assertEqual(row['price_type'], 'نطاق سعري')
        self.assertEqual((row['price_from'], row['price_to']),
                         ('366905', '812400'))
        self.assertEqual((row['area_from'], row['area_to']), ('178', '220'))
        self.assertEqual(row['source'], 'عقار')
        self.assertEqual(row['source_url'], _ABYATNA_URL)
        self.assertEqual(row['row_source'], 'aqar')
        self.assertEqual(row['verify_state'], 'verified')
        self.assertEqual(row['district'], 'الأمير عبدالمجيد')
        self.assertEqual(session.opened, [_ABYATNA_URL])

    def test_a_typed_name_with_the_city_word_still_finds_the_project(self):
        row = {'name': 'أبياتنا هيلز جدة', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        filled, _session = self._fill([row], {_ABYATNA_URL: _DETAIL_RANGE})
        self.assertEqual(filled, 1)
        self.assertEqual(row['source_url'], _ABYATNA_URL)

    def test_a_project_listed_without_a_price_is_still_read_by_name(self):
        row = {'name': 'برج الواجهة', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        filled, _session = self._fill([row], {_TOWER_URL: _DETAIL_WITHOUT_PRICE})
        self.assertEqual(filled, 1)
        self.assertEqual(row['source_url'], _TOWER_URL)
        self.assertEqual((row['area_from'], row['area_to']), ('90', '140'))
        self.assertFalse(row.get('price_type'))

    def test_the_row_keeps_the_price_its_owner_entered(self):
        own_url = 'https://example.sa/abyatna'
        row = {'name': 'أبياتنا هيلز', 'project_type': 'سكني',
               'operation_type': 'بيع', 'price_value': '500000',
               'source_url': own_url, 'source_urls': [own_url]}
        filled, _session = self._fill([row], {_ABYATNA_URL: _DETAIL_RANGE})
        self.assertEqual(filled, 1)
        self.assertEqual(row['price_value'], '500000')
        self.assertEqual(row['source_url'], own_url)
        self.assertIn(_ABYATNA_URL, row['source_urls'])
        self.assertEqual((row['area_from'], row['area_to']), ('178', '220'))
        warnings = row.get('conflict_warnings') or []
        price_warning = next((item for item in warnings
                              if item.get('field') == 'price_value'), None)
        self.assertIsNotNone(price_warning)
        self.assertEqual(price_warning['source_url'], _ABYATNA_URL)
        self.assertIn('366905', price_warning['incoming'])

    def test_a_complete_row_is_not_looked_up_at_all(self):
        row = {'name': 'أبياتنا هيلز', 'project_type': 'سكني',
               'operation_type': 'بيع', 'price_from': '850000',
               'area_from': '120', 'source_url': 'https://example.sa/own'}
        self.assertFalse(self.module._needs_aqar_fill(row))
        filled, session = self._fill([row], {_ABYATNA_URL: _DETAIL_RANGE})
        self.assertEqual(filled, 0)
        self.assertEqual(session.fetched, [])

    def test_a_name_outside_the_directory_stays_unfilled(self):
        row = {'name': 'برج المرقاة', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        filled, session = self._fill([row], {})
        self.assertEqual(filled, 0)
        self.assertEqual(row.get('source_url'), None)
        self.assertFalse(row.get('price_from'))
        self.assertIn('دليل المشاريع', row.get('notes') or '')
        self.assertEqual(session.opened, [])

    def test_a_hotel_row_is_left_to_booking(self):
        row = {'name': 'WA Hotel', 'project_type': 'فندقي',
               'operation_type': 'تشغيل فندقي'}
        self.assertFalse(self.module._needs_aqar_fill(row))
        filled, session = self._fill([row], {})
        self.assertEqual(filled, 0)
        self.assertEqual(session.fetched, [])

    def test_the_directory_and_each_page_are_read_once(self):
        rows = [{'name': 'أبياتنا هيلز', 'project_type': 'سكني',
                 'operation_type': 'بيع'},
                {'name': 'مكتب النخبة', 'project_type': 'تجاري',
                 'operation_type': 'بيع'}]
        office_url = _link_url('النخبة')
        filled, session = self._fill(
            rows, {_ABYATNA_URL: _DETAIL_RANGE, office_url: _DETAIL_RANGE})
        self.assertEqual(filled, 2)
        self.assertEqual(len(session.fetched), 1)
        self.assertEqual(len(session.opened), 2)
        self.assertTrue(session.closed)

    def test_fill_mode_completes_a_residential_row_before_the_agent(self):
        module = self.module
        row = {'name': 'أبياتنا هيلز', 'project_type': 'سكني',
               'operation_type': 'بيع'}
        calls = {'aqar': 0, 'verify': 0}

        def fake_aqar(rows, payload, data, **kwargs):
            calls['aqar'] += 1
            for item in rows:
                item.update({
                    'price_type': 'نطاق سعري', 'price_from': '366905',
                    'price_to': '812400', 'row_source': 'aqar',
                    'source_url': _ABYATNA_URL,
                })
            return 1

        def fake_verify(*_args, **_kwargs):
            calls['verify'] += 1

        self.app.config['TESTING'] = False
        try:
            with self.app.app_context(), \
                    patch.object(module, '_fill_project_rows_from_aqar',
                                 new=fake_aqar), \
                    patch.object(module, '_verify_competitor_rows',
                                 new=fake_verify):
                result = module._run_market_competitors({
                    'mode': 'fill',
                    'competitors': [row],
                    'comparisonTypes': [
                        {'type': 'residential', 'operation': 'sale'}],
                    'competitorScope': {'mode': 'district', 'radius': '10'},
                    'city': 'جدة',
                    'district': 'الأمير عبدالمجيد',
                    'projectType': 'سكني',
                })
        finally:
            self.app.config['TESTING'] = True
        self.assertTrue(result['success'], result)
        self.assertEqual(calls, {'aqar': 1, 'verify': 0})
        self.assertEqual(result['filledCount'], 1)
        self.assertEqual(result['competitors'][0]['price_from'], '366905')


if __name__ == '__main__':
    unittest.main()
