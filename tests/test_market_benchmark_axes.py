"""Per-axis competitor coverage for mixed-use projects.

The competitors table used to enforce COMPETITOR_MIN_DIRECT on the whole
table, so a residential + hotel + retail project could come back with five
residential rows and no hotel or retail competitor at all. The minimum is now
per benchmark axis — each revenue-bearing project component is an axis, every
row carries a benchmarks tag naming the axis it measures, and the expansion
passes target whichever axis is still short.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db
import market_study


def _mixed_payload():
    return {
        'projectType': 'متعدد الاستخدامات',
        'city': 'الرياض',
        'components': [
            {'name': 'الشقق', 'useType': 'residential', 'investmentModel': 'sale'},
            {'name': 'الفندق', 'useType': 'hospitality', 'investmentModel': 'dailyRent'},
            {'name': 'المحلات', 'useType': 'retail', 'investmentModel': 'annualRent'},
            {'name': 'المواقف', 'useType': 'parking', 'investmentModel': 'nonRevenue'},
        ],
    }


class BenchmarkAxesTests(unittest.TestCase):

    def test_axes_derived_from_revenue_components(self):
        axes = market_study.project_competitor_axes(_mixed_payload())
        self.assertEqual([axis['key'] for axis in axes],
                         ['residential', 'hospitality', 'retail'])

    def test_axes_skip_support_uses_and_non_revenue_components(self):
        payload = {'components': [
            {'name': 'المواقف', 'useType': 'parking', 'investmentModel': 'operating'},
            {'name': 'الخدمات', 'useType': 'services', 'investmentModel': 'operating'},
            {'name': 'محلات', 'useType': 'retail', 'investmentModel': 'nonRevenue'},
        ]}
        self.assertEqual([axis['key'] for axis in market_study.project_competitor_axes(payload)],
                         ['general'])

    def test_axes_fall_back_to_subtypes_then_mains(self):
        subtyped = {'projectType': 'متعدد الاستخدامات', 'projectComponents': 'سكني، فندق'}
        self.assertEqual([axis['key'] for axis in market_study.project_competitor_axes(subtyped)],
                         ['residential', 'hospitality'])
        mains = {'projectType': 'سكني، فندقي'}
        self.assertEqual([axis['key'] for axis in market_study.project_competitor_axes(mains)],
                         ['residential', 'hospitality'])

    def test_axes_general_when_nothing_is_known(self):
        axes = market_study.project_competitor_axes({})
        self.assertEqual([axis['key'] for axis in axes], ['general'])

    def test_row_axis_keys_from_benchmarks(self):
        axes = market_study.project_competitor_axes(_mixed_payload())
        row = {'name': 'برج', 'benchmarks': ['سكني', 'فندقي']}
        self.assertEqual(market_study.competitor_row_axis_keys(row, axes),
                         {'residential', 'hospitality'})

    def test_row_axis_keys_accept_strings_and_english_values(self):
        axes = market_study.project_competitor_axes(_mixed_payload())
        row = {'name': 'برج', 'benchmarks': 'سكني، Retail'}
        self.assertEqual(market_study.competitor_row_axis_keys(row, axes),
                         {'residential', 'retail'})

    def test_row_axis_keys_fall_back_to_project_type(self):
        axes = market_study.project_competitor_axes(_mixed_payload())
        self.assertEqual(
            market_study.competitor_row_axis_keys({'name': 'مول', 'project_type': 'تجاري'}, axes),
            {'retail'})
        mixed = {'name': 'برج مختلط', 'project_type': 'متعدد الاستخدامات'}
        self.assertEqual(market_study.competitor_row_axis_keys(mixed, axes),
                         {'residential', 'hospitality', 'retail'})

    def test_general_axis_counts_every_named_row(self):
        axes = market_study.project_competitor_axes({'projectType': 'أخرى'})
        self.assertEqual(axes[0]['key'], 'general')
        self.assertEqual(market_study.competitor_row_axis_keys({'name': 'x'}, axes), {'general'})

    def test_multi_axis_prompt_demands_the_minimum_per_axis(self):
        prompt = market_study.build_competitors_user_prompt(_mixed_payload(), [], mode='generate')
        self.assertIn('متعدد المحاور', prompt)
        self.assertIn('سكني: 5', prompt)
        self.assertIn('فندقي: 5', prompt)
        self.assertIn('تجزئة ومحلات: 5', prompt)
        self.assertIn('"benchmarks"', prompt)
        self.assertIn('سكني', prompt.split('benchmarks')[0] or 'سكني')

    def test_single_axis_prompt_keeps_the_flat_minimum(self):
        payload = {'components': [
            {'name': 'شقق', 'useType': 'residential', 'investmentModel': 'sale'}]}
        prompt = market_study.build_competitors_user_prompt(payload, [], mode='generate')
        self.assertNotIn('متعدد المحاور', prompt)
        self.assertIn('منافسين مباشرين على الأقل', prompt)
        self.assertIn('"benchmarks"', prompt)

    def test_fill_mode_asks_to_tag_missing_benchmarks(self):
        payload = _mixed_payload()
        existing = [{'name': 'منافس موجود'}]
        prompt = market_study.build_competitors_user_prompt(payload, existing, mode='fill')
        self.assertIn('benchmarks', prompt)
        # The untagged row counts as incomplete so the model sees it listed.
        self.assertIn('منافس موجود', prompt)

    def test_normalize_row_keeps_benchmarks(self):
        row = market_study.normalize_competitor_row(
            {'name': 'منافس', 'benchmarks': 'سكني، فندقي'})
        self.assertEqual(row['benchmarks'], ['سكني', 'فندقي'])


class BenchmarkExpansionTests(unittest.TestCase):
    """_execute_market_competitors runs a targeted search per deficient axis."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        db.DB_PATH = os.path.join(cls.temp_dir.name, 'benchmark-axes.db')
        import app as application_module
        cls.application_module = application_module
        cls.app = application_module.app
        cls.app.config.update(TESTING=True)
        with cls.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    @staticmethod
    def _response(rows):
        return (
            {'choices': [{'message': {'content': json.dumps(
                {'competitors': rows}, ensure_ascii=False)}}],
             'usage': {'server_tool_use': {'web_search_requests': 4}}},
            '',
        )

    def test_deficient_axis_gets_its_own_search_round(self):
        module = self.application_module
        residential = [
            {'name': f'برج سكني {index}', 'project_type': 'سكني', 'benchmarks': ['سكني']}
            for index in range(5)
        ]
        hotel = [{'name': 'فندق المدينة', 'project_type': 'فندقي', 'benchmarks': ['فندقي']}]
        calls = []

        def fake_call(system_prompt, user_prompt, **kwargs):
            calls.append(user_prompt)
            if len(calls) == 1:
                return self._response(residential + hotel)
            return self._response([
                {'name': f'فندق {index}', 'project_type': 'فندقي', 'benchmarks': ['فندقي']}
                for index in range(5)])

        payload = {
            'projectType': 'متعدد الاستخدامات',
            'city': 'الرياض',
            'mode': 'generate',
            'components': [
                {'name': 'الشقق', 'useType': 'residential', 'investmentModel': 'sale'},
                {'name': 'الفندق', 'useType': 'hospitality', 'investmentModel': 'dailyRent'},
            ],
            'competitors': [],
        }
        with self.app.app_context(), \
                patch.object(module, '_call_market_study_model', side_effect=fake_call), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(payload)

        self.assertTrue(result['success'], result)
        # First call is the main generation; the second must target the
        # hospitality axis specifically, not another generic angle.
        self.assertEqual(len(calls), 2)
        self.assertIn('فنادق', calls[1])
        self.assertIn('benchmarks', calls[1])
        self.assertEqual(len(result['competitors']), 11)

    def test_full_axes_skip_expansion(self):
        module = self.application_module
        rows = [
            {'name': f'سكني {index}', 'project_type': 'سكني', 'benchmarks': ['سكني']}
            for index in range(5)
        ] + [
            {'name': f'فندق {index}', 'project_type': 'فندقي', 'benchmarks': ['فندقي']}
            for index in range(5)
        ]
        calls = []

        def fake_call(system_prompt, user_prompt, **kwargs):
            calls.append(user_prompt)
            return self._response(rows)

        payload = {
            'projectType': 'متعدد الاستخدامات',
            'city': 'الرياض',
            'mode': 'generate',
            'components': [
                {'name': 'الشقق', 'useType': 'residential', 'investmentModel': 'sale'},
                {'name': 'الفندق', 'useType': 'hospitality', 'investmentModel': 'dailyRent'},
            ],
            'competitors': [],
        }
        with self.app.app_context(), \
                patch.object(module, '_call_market_study_model', side_effect=fake_call), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(payload)

        self.assertTrue(result['success'], result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result['competitors']), 10)


if __name__ == '__main__':
    unittest.main()
