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

ROOT = Path(__file__).resolve().parents[2]
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

    def test_competitor_numeric_text_keeps_all_decimal_places(self):
        self.assertEqual(market_study._clean_numeric('1,234.56789'), '1234.56789')
        self.assertEqual(market_study._clean_numeric('١٢٣٫٤٥٦٧'), '123.4567')
        frontend = (ROOT / 'assets' / 'js' / '04-market.js').read_text(encoding='utf-8')
        self.assertIn("return sign + normalizedWhole + (fraction !== undefined ? '.' + fraction : '');", frontend)
        self.assertIn('return formatExactSystemNumber(clean, true);', frontend)

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

    def test_explicit_comparison_axes_use_only_client_selections(self):
        axes = market_study.project_competitor_axes({
            'comparisonTypes': [
                {'type': 'hotel'},
                {'type': 'residential', 'operation': 'sale'},
                {'type': 'commercial', 'operation': 'rent'},
                {'type': 'hotel'},
            ]})
        self.assertEqual([axis['key'] for axis in axes],
                         ['hotel', 'residential:sale', 'commercial:rent'])
        self.assertEqual(axes[0]['label'], 'فندقي')

    def test_multiple_values_expand_into_individual_comparison_axes(self):
        axes = market_study.normalize_comparison_types([
            {'type': 'hotel'},
            {'type': 'residential', 'operation': ['sale', 'rent']},
        ])
        self.assertEqual([axis['key'] for axis in axes], [
            'hotel', 'residential:sale', 'residential:rent',
        ])
        selected_rows = [
            {'project_type': 'فندقي', 'hotel_stars': 4},
            {'project_type': 'سكني', 'operation_type': 'بيع'},
            {'project_type': 'سكني', 'operation_type': 'إيجار'},
        ]
        self.assertEqual(
            [sum(market_study.competitor_matches_comparison_axis(row, axis)
                 for row in selected_rows) for axis in axes],
            [1, 1, 1],
        )

    def test_a_star_selection_is_ignored_and_never_becomes_an_axis(self):
        axes = market_study.normalize_comparison_types([
            {'type': 'hotel', 'stars': ['4', '5']},
        ])
        self.assertEqual([axis['key'] for axis in axes], ['hotel'])
        self.assertEqual(axes[0]['stars'], '')

    def test_prompt_enforces_selected_axes_location_booking_and_interaction(self):
        payload = {
            'city': 'جدة', 'district': 'الروضة',
            'competitorScope': {'mode': 'district'},
            'comparisonTypes': [
                {'type': 'hotel'},
                {'type': 'residential', 'operation': 'sale'}],
        }
        prompt = market_study.build_competitors_user_prompt(payload, [], mode='generate')
        self.assertIn('فندقي', prompt)
        self.assertNotIn('فندقي - 4 نجوم', prompt)
        self.assertIn('سكني - بيع', prompt)
        self.assertIn('لا تضف نوعًا أو عملية غير مختارة', prompt)
        # The project's district alone is the whole scope when the client added
        # none; the several-district case has its own test below.
        self.assertIn('حي الروضة في مدينة جدة', prompt)
        self.assertIn('Booking.com', prompt)
        self.assertIn('Booking.com فقط من مسار /hotel/', prompt)
        self.assertIn('/district/', prompt)
        self.assertIn('/city/', prompt)
        self.assertIn('النظام يحول كل الأسعار إلى الريال', prompt)
        self.assertIn('inspect_page', prompt)
        self.assertIn('type_text', prompt)
        self.assertIn('click_element', prompt)
        self.assertIn('انسخ المدينة كما وردت في بيانات المشروع دون ترجمة', prompt)
        self.assertIn('"benchmarks"', prompt)

    def test_distance_scope_normalizes_and_filters_competitors(self):
        scope = market_study.normalize_competitor_scope({
            'mode': 'distance', 'radius': 'custom', 'radius_custom_km': '3.5'})
        self.assertEqual(scope, {'mode': 'distance', 'radius_km': 3.5})
        self.assertIn('3.5 كم', market_study.competitor_scope_text({
            'competitorScope': scope, 'city': 'جدة', 'district': 'الروضة'}))

        axis = market_study.normalize_comparison_types(
            [{'type': 'residential', 'operation': 'sale'}])
        rows = [
            {'name': 'داخل المسافة', 'project_type': 'سكني', 'operation_type': 'بيع',
             'distance_km': '3.5'},
            {'name': 'خارج المسافة', 'project_type': 'سكني', 'operation_type': 'بيع',
             'distance_km': '3.6'},
            {'name': 'مسافة غير موثقة', 'project_type': 'سكني', 'operation_type': 'بيع'},
        ]
        accepted = market_study.filter_and_cap_competitors(
            rows, axis, scope=scope, city='جدة', district='الروضة')
        self.assertEqual([row['name'] for row in accepted], ['داخل المسافة'])

    def test_distance_scope_calculates_from_verified_coordinates(self):
        scope = {'mode': 'distance', 'radius_km': 5,
                 'origin_lat': 24.0, 'origin_lng': 46.0}
        nearby = {'lat': 24.03, 'lng': 46.0}
        distant = {'lat': 24.06, 'lng': 46.0}
        self.assertTrue(market_study.competitor_matches_location_scope(
            nearby, scope, city='الرياض', district='النرجس'))
        self.assertFalse(market_study.competitor_matches_location_scope(
            distant, scope, city='الرياض', district='النرجس'))

    def test_competitor_normalization_converts_foreign_prices_to_sar(self):
        with patch.object(market_study, '_live_fx_rates', return_value={}):
            row = market_study.normalize_competitor_row({
                'name': 'منافس أوروبي', 'operation_type': 'بيع', 'price_value': '1000',
                'price_currency': 'EUR'})
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertEqual(row['price_value'], '4050')
        self.assertEqual(row['price_cache']['original_price_value'], '1000')
        self.assertEqual(row['price_cache']['original_currency'], 'EUR')

    def test_competitor_normalization_hides_prices_without_an_fx_rate(self):
        with patch.object(market_study, '_live_fx_rates', return_value={}):
            row = market_study.normalize_competitor_row({
                'name': 'منافس بعملة غير مدعومة', 'operation_type': 'بيع',
                'price_value': '1000', 'price_currency': 'XYZ'})
        self.assertEqual(row['price_currency'], 'SAR')
        self.assertEqual(row['price_value'], '')
        self.assertEqual(row['price_conversion_error'], 'missing_fx_rate')

    def test_rent_operation_matches_arabic_and_english_values(self):
        axis = market_study.normalize_comparison_types([
            {'type': 'residential', 'operation': 'rent'}])[0]
        for operation in ('إيجار', 'تأجير', 'Rent', 'Rental'):
            self.assertTrue(market_study.competitor_matches_comparison_axis(
                {'project_type': 'سكني', 'operation_type': operation}, axis), operation)

    def test_explicit_filter_enforces_selection_location_and_five_row_cap(self):
        axes = market_study.normalize_comparison_types([
            {'type': 'hotel'},
            {'type': 'residential', 'operation': 'sale'},
        ])
        rows = [
            {'name': f'فندق جدة {n}', 'project_type': 'فندقي', 'hotel_stars': 4,
             'operation_type': 'تشغيل فندقي', 'city': 'جدة', 'district': 'الروضة'}
            for n in range(6)
        ] + [
            {'name': 'فندق خمس نجوم', 'project_type': 'فندقي', 'hotel_stars': 5,
             'operation_type': 'تشغيل فندقي', 'city': 'جدة', 'district': 'الروضة'},
            {'name': 'سكني إيجار', 'project_type': 'سكني', 'operation_type': 'إيجار',
             'city': 'جدة', 'district': 'الروضة'},
            {'name': 'سكني مدينة أخرى', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'الرياض', 'district': 'الروضة'},
            {'name': 'سكني حي آخر', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'جدة', 'district': 'السلامة'},
        ] + [
            {'name': f'فيلا جدة {n}', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'جدة', 'district': 'الروضة'}
            for n in range(6)
        ]
        accepted = market_study.filter_and_cap_competitors(
            rows, axes, scope={'mode': 'district'}, city='جدة', district='الروضة')
        self.assertEqual(len(accepted), 10)
        self.assertEqual(sum(row['comparison_type'] == 'hotel' for row in accepted), 5)
        self.assertEqual(sum(row['comparison_type'] == 'residential' for row in accepted), 5)
        self.assertFalse(any('إيجار' in row['name'] for row in accepted))
        self.assertFalse(any('مدينة أخرى' in row['name'] or 'حي آخر' in row['name']
                             for row in accepted))
        # Stars are not a dimension any more: the class column is cleared on
        # every hotel row instead of carrying a value nobody filters on.
        self.assertTrue(all(row['hotel_stars'] == ''
                            for row in accepted if row['comparison_type'] == 'hotel'))

    def test_every_hotel_matches_the_single_hotel_axis(self):
        """Owner decision 2026-10-27: hotel competitors are compared without a
        star class, so every hotel row belongs to the one hotel axis."""
        axis = market_study.normalize_comparison_types([
            {'type': 'hotel'}])[0]
        known = {'name': 'فندق معروف', 'project_type': 'فندقي',
                 'hotel_stars': '4', 'operation_type': 'تشغيل فندقي'}
        unknown = {'name': 'فندق بلا تصنيف', 'project_type': 'فندقي',
                   'operation_type': 'تشغيل فندقي'}
        other = {'name': 'فندق خمس نجوم', 'project_type': 'فندقي',
                 'hotel_stars': '5', 'operation_type': 'تشغيل فندقي'}
        for row in (known, unknown, other):
            self.assertTrue(market_study.competitor_matches_comparison_axis(
                row, axis), row['name'])

        accepted = market_study.filter_and_cap_competitors(
            [dict(unknown, city='جدة', district='الاندلس')], [axis],
            scope={'mode': 'district'}, city='جدة', district='الاندلس')
        self.assertEqual([row['name'] for row in accepted], ['فندق بلا تصنيف'])
        self.assertEqual(accepted[0]['hotel_stars'], '')

    def test_a_district_scope_may_cover_several_chosen_districts(self):
        axis = market_study.normalize_comparison_types(
            [{'type': 'residential', 'operation': 'sale'}])
        scope = market_study.normalize_competitor_scope({
            'mode': 'district',
            'districts': ['الروضة', 'السلامة'],
            'unit_types': ['فيلا مستقلة', 'شقة'],
        })
        self.assertEqual(scope['districts'], ['الروضة', 'السلامة'])
        self.assertEqual(scope['unit_types'], ['فيلا مستقلة', 'شقة'])
        self.assertIn('الروضة، السلامة', market_study.competitor_scope_text({
            'competitorScope': scope, 'city': 'جدة', 'district': 'الروضة'}))
        rows = [
            {'name': 'الروضة أول', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'جدة', 'district': 'الروضة'},
            {'name': 'السلامة ثان', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'جدة', 'district': 'السلامة'},
            {'name': 'حي آخر', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'جدة', 'district': 'الزهراء'},
        ]
        accepted = market_study.filter_and_cap_competitors(
            rows, axis, scope=scope, city='جدة', district='الروضة')
        self.assertEqual([row['name'] for row in accepted],
                         ['الروضة أول', 'السلامة ثان'])

    def test_competitor_prompt_names_every_selected_district(self):
        """A widened district scope must reach the binding search instruction.

        It used to appear only in the descriptive project block while rules 1
        and 7 named the project's own district, so the model searched one
        neighborhood and the added districts were never asked for.
        """
        payload = {
            'projectType': 'سكني', 'city': 'جدة', 'district': 'الروضة',
            'competitorScope': {'mode': 'district',
                                'districts': ['الروضة', 'السلامة']},
            'comparisonTypes': [{'type': 'residential', 'operation': 'sale'}],
        }
        prompt = market_study.build_competitors_user_prompt(
            payload, [], mode='generate')
        instruction = prompt.split('بيانات المشروع:')[0]
        self.assertIn('السلامة', instruction)
        self.assertIn('الأحياء المختارة', instruction)
        english = market_study.build_competitors_user_prompt(
            payload, [], mode='generate', offer_lang='en')
        english_instruction = english.split('بيانات المشروع:')[0]
        self.assertIn('districts', english_instruction)
        self.assertIn('السلامة', english_instruction)

    def test_unit_type_filter_drops_a_row_of_another_kind(self):
        """The client's unit-kind picks are a rule on model rows too, and a row
        that names no kind at all is kept."""
        axis = market_study.normalize_comparison_types(
            [{'type': 'residential', 'operation': 'sale'}])
        rows = [
            {'name': 'شقق الياسمين', 'project_type': 'سكني',
             'operation_type': 'بيع', 'city': 'جدة', 'district': 'الروضة'},
            {'name': 'فلل النخيل', 'project_type': 'سكني',
             'operation_type': 'بيع', 'city': 'جدة', 'district': 'الروضة'},
            {'name': 'مشروع الواحة', 'project_type': 'سكني',
             'operation_type': 'بيع', 'city': 'جدة', 'district': 'الروضة'},
        ]
        accepted = market_study.filter_and_cap_competitors(
            rows, axis, scope={'mode': 'district'}, city='جدة',
            district='الروضة', unit_types=['فيلا مستقلة'])
        self.assertEqual([row['name'] for row in accepted],
                         ['فلل النخيل', 'مشروع الواحة'])
        # No unit kind selected: the filter never touches the rows.
        unfiltered = market_study.filter_and_cap_competitors(
            rows, axis, scope={'mode': 'district'}, city='جدة',
            district='الروضة')
        self.assertEqual(len(unfiltered), 3)
        # A hotel is compared on its own axis and carries no unit kind, so a
        # residential pick never deletes it.
        self.assertTrue(market_study.competitor_matches_unit_types(
            {'name': 'شقق مخدومة مارينا', 'project_type': 'فندقي'},
            ['فيلا مستقلة']))

    def test_city_scope_allows_other_neighborhoods_in_selected_city_only(self):
        axis = market_study.normalize_comparison_types(
            [{'type': 'residential', 'operation': 'sale'}])
        rows = [
            {'name': 'حي أول', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'جدة', 'district': 'الروضة'},
            {'name': 'حي ثان', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'جدة', 'district': 'السلامة'},
            {'name': 'مدينة ثانية', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'الرياض', 'district': 'الروضة'},
        ]
        accepted = market_study.filter_and_cap_competitors(
            rows, axis, scope={'mode': 'city'}, city='جدة', district='الروضة')
        self.assertEqual([row['name'] for row in accepted], ['حي أول', 'حي ثان'])

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

    def test_uploaded_transactions_name_their_source_and_match_neighborhood(self):
        axis = market_study.normalize_comparison_types(
            [{'type': 'residential', 'operation': 'sale'}])[0]
        data = market_study.build_transaction_price_benchmarks({
            'city': 'جدة', 'district': 'الروضة',
            'competitorScope': {'mode': 'district'},
        }, [axis])
        self.assertTrue(data['available'])
        self.assertGreater(data['groups'][0]['deal_count'], 0)
        self.assertEqual({group['district'] for group in data['groups']}, {'الروضة'})
        self.assertNotIn('name', data['groups'][0])
        self.assertIn('وزارة العدل', data['source_label'])
        self.assertIn('وزارة العدل', data['note'])
        self.assertNotIn('مجهولة الهوية', data['note'])

    def test_uploaded_transactions_are_not_used_for_rental_comparisons(self):
        axis = market_study.normalize_comparison_types(
            [{'type': 'residential', 'operation': 'rent'}])[0]
        data = market_study.build_transaction_price_benchmarks({
            'city': 'جدة', 'district': 'الروضة',
            'competitorScope': {'mode': 'district'},
        }, [axis])
        self.assertFalse(data['available'])
        self.assertEqual(data['groups'], [])


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
        # Browse-agent shape: the retrieved pages ride as url_citation
        # annotations — _market_search_ran treats them as executed research.
        return {
            'choices': [{'message': {
                'content': json.dumps({'competitors': rows}, ensure_ascii=False),
                'annotations': [{'url_citation': {
                    'url': 'https://rei.rega.gov.sa/ar', 'title': 'المؤشرات'}}],
            }}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        }

    def test_hotel_axis_uses_booking_not_the_agent(self):
        module = self.application_module
        residential = [
            {'name': f'برج سكني {index}', 'project_type': 'سكني',
             'operation_type': 'بيع', 'city': 'الرياض', 'district': 'النرجس',
             'benchmarks': ['سكني - بيع']}
            for index in range(5)
        ]
        hotel = [
            {'name': f'فندق {index}', 'project_type': 'فندقي',
             'operation_type': 'تشغيل فندقي', 'city': 'الرياض', 'district': 'النرجس',
             'benchmarks': ['فندقي']}
            for index in range(5)
        ]
        calls = []

        def fake_call(system_prompt, user_prompt, *args, **kwargs):
            calls.append(user_prompt)
            return self._response(residential)

        def fake_hotel_scan(task, payload, data, tenant_id=None, offer_lang='ar',
                            deadline=None):
            return {
                'task': task, 'reply': None,
                'parsed': {'competitors': hotel}, 'parse_error': '',
                'provider_error': '', 'search_ran': True,
            }

        payload = {
            'projectType': 'متعدد الاستخدامات',
            'city': 'الرياض',
            'district': 'النرجس',
            'competitorScope': {'mode': 'district'},
            'comparisonTypes': [
                {'type': 'residential', 'operation': 'sale'},
                {'type': 'hotel'}],
            'mode': 'generate',
            'components': [
                {'name': 'الشقق', 'useType': 'residential', 'investmentModel': 'sale'},
                {'name': 'الفندق', 'useType': 'hospitality', 'investmentModel': 'dailyRent'},
            ],
            'competitors': [],
        }
        with self.app.app_context(), \
                patch.object(module, '_run_market_source_plan', return_value=None), \
                patch.object(module, '_browse_agent_call', side_effect=fake_call), \
                patch.object(module, '_booking_hotel_scan', side_effect=fake_hotel_scan), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(payload)

        self.assertTrue(result['success'], result)
        # Residential is the single agent search; the hotel axis is
        # deterministic Booking discovery and adds no model call.
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result['competitors']), 10)

    def test_full_axes_skip_expansion(self):
        module = self.application_module
        residential = [
            {'name': f'سكني {index}', 'project_type': 'سكني', 'operation_type': 'بيع',
             'city': 'الرياض', 'district': 'النرجس', 'benchmarks': ['سكني - بيع']}
            for index in range(5)
        ]
        hotel = [
            {'name': f'فندق {index}', 'project_type': 'فندقي',
             'operation_type': 'تشغيل فندقي', 'city': 'الرياض', 'district': 'النرجس',
             'benchmarks': ['فندقي']}
            for index in range(5)
        ]
        calls = []

        def fake_call(system_prompt, user_prompt, *args, **kwargs):
            calls.append(user_prompt)
            return self._response(residential)

        def fake_hotel_scan(task, payload, data, tenant_id=None, offer_lang='ar',
                            deadline=None):
            return {
                'task': task, 'reply': None,
                'parsed': {'competitors': hotel}, 'parse_error': '',
                'provider_error': '', 'search_ran': True,
            }

        payload = {
            'projectType': 'متعدد الاستخدامات',
            'city': 'الرياض',
            'district': 'النرجس',
            'competitorScope': {'mode': 'district'},
            'comparisonTypes': [
                {'type': 'residential', 'operation': 'sale'},
                {'type': 'hotel'}],
            'mode': 'generate',
            'components': [
                {'name': 'الشقق', 'useType': 'residential', 'investmentModel': 'sale'},
                {'name': 'الفندق', 'useType': 'hospitality', 'investmentModel': 'dailyRent'},
            ],
            'competitors': [],
        }
        with self.app.app_context(), \
                patch.object(module, '_run_market_source_plan', return_value=None), \
                patch.object(module, '_browse_agent_call', side_effect=fake_call), \
                patch.object(module, '_booking_hotel_scan', side_effect=fake_hotel_scan), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(payload)

        self.assertTrue(result['success'], result)
        # One agent search (residential) plus deterministic hotel discovery;
        # no sequential expansion call follows.
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result['competitors']), 10)

    def test_distance_scope_reaches_search_and_drops_out_of_radius_rows(self):
        module = self.application_module
        rows = [
            {'name': f'منافس داخل {index}', 'project_type': 'سكني',
             'operation_type': 'بيع', 'city': 'جدة', 'district': 'الروضة',
             'lat': '24.036', 'lng': '46.0', 'benchmarks': ['سكني - بيع'],
             'source_urls': [f'https://developer.example/project-{index}']}
            for index in range(4)
        ] + [{
            'name': 'منافس خارج المسافة', 'project_type': 'سكني',
            'operation_type': 'بيع', 'city': 'جدة', 'district': 'الروضة',
            'lat': '24.054', 'lng': '46.0', 'benchmarks': ['سكني - بيع'],
            'source_urls': ['https://developer.example/outside'],
        }]
        calls = []

        def fake_call(_system_prompt, user_prompt, *args, **kwargs):
            calls.append(user_prompt)
            return self._response(rows)

        payload = {
            'projectType': 'سكني', 'city': 'جدة', 'district': 'الروضة',
            'location_lat': '24.0', 'location_lng': '46.0',
            'competitorScope': {'mode': 'distance', 'radius': '5'},
            'comparisonTypes': [{'type': 'residential', 'operation': 'sale'}],
            'mode': 'generate', 'competitors': [],
        }
        with self.app.app_context(), \
                patch.object(module, '_run_market_source_plan', return_value=None), \
                patch.object(module, '_browse_agent_call', side_effect=fake_call), \
                patch.object(module, '_pool_covers_angle', return_value=True), \
                patch.object(module, '_verify_competitor_rows', return_value=None), \
                patch.object(module, '_verify_market_urls', return_value=set()), \
                patch.object(module, '_auto_import_competitor_logos', return_value=None):
            result = module._execute_market_competitors(payload)

        self.assertTrue(calls)
        self.assertIn('ضمن مسافة 5 كم', calls[0])
        self.assertEqual(len(result['competitors']), 4)
        self.assertFalse(any(row['name'] == 'منافس خارج المسافة'
                             for row in result['competitors']))


    def test_distance_scope_filters_even_without_a_comparison_selection(self):
        rows = [
            {'name': 'قريب', 'lat': 21.545, 'lng': 39.174},
            {'name': 'بعيد', 'lat': 21.60, 'lng': 39.20},
        ]
        scope = {'mode': 'distance', 'radius_km': 2,
                 'origin_lat': 21.5433, 'origin_lng': 39.1728}
        result = market_study.filter_and_cap_competitors(
            rows, [], scope=scope, city='جدة', district='الأندلس')
        self.assertEqual([row['name'] for row in result], ['قريب'])


if __name__ == '__main__':
    unittest.main()
