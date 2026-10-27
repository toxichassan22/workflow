"""The Booking tax probe prints what the pipeline would store.

The probe answers, from the server itself, why a hotel cell shows a number the
property page does not: it reads the room table exactly as the market job does
and reports whether the taxes line said «شامل» and which pre-tax figure the
pipeline would apply. These tests pin that reporting to the real rate readers,
so a probe run on the server can be trusted against the row it explains.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_WEB_BROWSE = ROOT / 'modules' / 'web_browse'
for _path in (str(ROOT), str(_WEB_BROWSE), str(ROOT / 'scripts')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_spec = importlib.util.spec_from_file_location(
    'booking_tax_probe', ROOT / 'scripts' / 'booking_tax_probe.py')
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

_FOLDED_ROW = {
    'index': 0,
    'block_id': '100_200_2_2_0',
    'price_attr': '389',
    'current_text': '389 SAR',
    'original_text': '',
    'taxes_text': 'شامل الضرائب والرسوم',
    'room_name': 'غرفة سوبيرير',
}

_PRE_TAX_ROW = {
    'index': 0,
    'block_id': '100_200_2_2_0',
    'price_attr': '325',
    'current_text': 'SAR 325',
    'original_text': '',
    'taxes_text': '+SAR 58 taxes and charges',
    'room_name': 'غرفة سوبيرير',
}


class BookingTaxProbeTests(unittest.TestCase):

    def test_summarize_reports_the_folded_figure_as_printed(self):
        """A folded view is reported as the page printed it: the property that
        showed 389 stores 389, and the probe flags that the taxes are folded."""
        summary = probe.summarize({'rows': [dict(_FOLDED_ROW)]})
        self.assertEqual(summary['rows'], 1)
        self.assertTrue(summary['tax_included'])
        self.assertEqual(summary['price'], 389)
        self.assertEqual(summary['applied_from'], 389)
        self.assertEqual(summary['applied_to'], 389)

    def test_summarize_reports_a_pre_tax_page_as_is(self):
        """The client's own view prints the price before tax beside the tax
        line; nothing is divided and the tax amount is reported."""
        summary = probe.summarize({'rows': [dict(_PRE_TAX_ROW)]})
        self.assertFalse(summary['tax_included'])
        self.assertEqual(summary['price'], 325)
        self.assertEqual(summary['applied_from'], 325)
        self.assertEqual(summary['taxes'], 58)

    def test_summarize_reports_zero_rows_for_an_empty_read(self):
        self.assertEqual(probe.summarize({'found': False, 'rows': []}),
                         {'rows': 0})

    def test_cookie_pairs_keep_values_whole(self):
        self.assertEqual(
            probe._cookie_pairs(['cc1=sa', 'x=a=b', 'broken', ' =v']),
            [('cc1', 'sa'), ('x', 'a=b'), ('broken', '')])


_spec = importlib.util.spec_from_file_location(
    'booking_page_dump', ROOT / 'scripts' / 'booking_page_dump.py')
dump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dump)

_PRE_TAX_HTML = (
    '<tr data-block-id="1"><td><div class="bui-price-display__value">'
    '303 SAR</div><div class="prd-taxes-and-fees-under-price" '
    'data-excl-charges-raw="54.2417">+54 SAR taxes and fees</div></td></tr>')
_FOLDED_HTML = (
    '<tr><td><div class="prd-taxes-and-fees-under-price" '
    'data-excl-charges-raw="">Includes taxes and fees</div></td></tr>')


class BookingPageDumpTests(unittest.TestCase):
    """The dump has to report what the page says, not what we expect.

    The whole point of dumping the page from the server is to settle whether a
    stored figure came from the markup or from our reading of it, so the
    evidence report must surface the stated tax amount when there is one and
    stay empty when the page folds the taxes in.
    """

    def test_evidence_reports_a_stated_tax_amount(self):
        report = dump.tax_evidence(_PRE_TAX_HTML)
        self.assertEqual(report['counts']['data-excl-charges-raw'], 1)
        self.assertEqual(report['counts']['data-hotel-rounded-price'], 0)
        self.assertTrue(report['snippets']['data-excl-charges-raw'])
        self.assertIn('54.2417', report['snippets']['data-excl-charges-raw'][0])

    def test_evidence_reports_a_folded_page_as_folded(self):
        report = dump.tax_evidence(_FOLDED_HTML)
        self.assertEqual(report['counts']['Includes taxes'], 1)
        self.assertIn('data-excl-charges-raw', report['snippets'])
        self.assertIn('data-excl-charges-raw=""', report['snippets'][
            'data-excl-charges-raw'][0])

    def test_evidence_is_empty_for_an_empty_page(self):
        report = dump.tax_evidence('')
        self.assertEqual(report['bytes'], 0)
        self.assertEqual(set(report['counts'].values()), {0})

    def test_default_dump_path_is_filed_under_sandbox(self):
        """A runtime dump never lands loose at the repo root."""
        self.assertTrue(dump.DEFAULT_OUT.startswith('sandbox/'))

    def test_a_page_stating_every_tax_proves_a_net_price(self):
        verdict = dump.net_basis_verdict([
            {'block_id': '1_2_2_0', 'price_attr': '298',
             'taxes_text': '+53 SAR taxes and fees', 'taxes_raw': '53.1781'},
            {'block_id': '1_2_2_1', 'price_attr': '350',
             'taxes_text': '+63 SAR taxes and fees', 'taxes_raw': '62.56'},
        ])
        self.assertEqual(verdict['rows'], 2)
        self.assertEqual(verdict['stated'], 2)
        self.assertEqual(verdict['folded'], 0)
        self.assertTrue(verdict['net'])

    def test_a_folded_page_cannot_prove_a_net_price(self):
        """The European view: one figure, «includes», nothing to remove."""
        verdict = dump.net_basis_verdict([
            {'block_id': '1_2_2_0', 'price_attr': '351',
             'taxes_text': 'شامل الضرائب والرسوم', 'taxes_raw': ''},
        ])
        self.assertEqual(verdict['folded'], 1)
        self.assertFalse(verdict['net'])

    def test_one_folded_row_fails_the_whole_view(self):
        """A single row without a stated tax must not pass as a net price."""
        verdict = dump.net_basis_verdict([
            {'block_id': '1_2_2_0', 'price_attr': '298',
             'taxes_text': '+53 SAR taxes and fees'},
            {'block_id': '1_2_2_1', 'price_attr': '351',
             'taxes_text': 'شامل الضرائب والرسوم'},
        ])
        self.assertEqual(verdict['stated'], 1)
        self.assertEqual(verdict['folded'], 1)
        self.assertFalse(verdict['net'])

    def test_an_empty_page_is_not_a_net_price(self):
        self.assertFalse(dump.net_basis_verdict([])['net'])


_spec = importlib.util.spec_from_file_location(
    'booking_pos_matrix', ROOT / 'scripts' / 'booking_pos_matrix.py')
matrix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(matrix)

_PROPERTY = 'https://www.booking.com/hotel/sa/novotel-jeddah-tahlia.html'


class BookingPosMatrixTests(unittest.TestCase):
    """The lever matrix must test the lever it says it tests.

    Every variant carries the shared stay window (so the property page keeps
    its room table) and the variant's own keys replace the stay's keys. A
    duplicate ``selected_currency`` measured the currency variants in riyals
    while their label claimed dollars, which made a negative result mean
    nothing.
    """

    def test_base_url_carries_the_shared_stay(self):
        url = matrix.variant_url(_PROPERTY, {})
        self.assertIn('checkin=', url)
        self.assertIn('checkout=', url)
        self.assertIn('selected_currency=SAR', url)

    def test_variant_keys_replace_the_stay_keys_instead_of_repeating_them(self):
        url = matrix.variant_url(
            _PROPERTY, {'lang': 'en-us', 'selected_currency': 'USD'})
        self.assertEqual(url.count('selected_currency='), 1)
        self.assertIn('selected_currency=USD', url)
        self.assertNotIn('selected_currency=SAR', url)
        self.assertIn('lang=en-us', url)
        self.assertIn('checkin=', url)

    def test_every_variant_label_is_unique(self):
        labels = list(matrix._PARAMS) + list(matrix._COOKIES)
        self.assertEqual(len(labels), len(set(labels)))

    def test_a_non_property_url_is_refused(self):
        self.assertFalse(
            matrix.hotel_stay.is_booking_hotel_url('https://www.booking.com/index.html'))


if __name__ == '__main__':
    unittest.main()
