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

    def test_summarize_reports_the_pre_tax_division(self):
        """A folded view is reported as divided, not as a read figure — the
        property that showed 389 and stored 322."""
        summary = probe.summarize({'rows': [dict(_FOLDED_ROW)]})
        self.assertEqual(summary['rows'], 1)
        self.assertTrue(summary['tax_included'])
        self.assertAlmostEqual(summary['price'], 322.15, places=2)
        self.assertEqual(summary['applied_from'], 322)
        self.assertEqual(summary['applied_to'], 322)

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


if __name__ == '__main__':
    unittest.main()
