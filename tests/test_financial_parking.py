import copy
import unittest

import financial_parking


class FinancialParkingTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            'approved_financial_area': 5000,
            'croquis_land_area': 5000,
            'approved_coverage_ratio': 60,
            'regulatory_constraints': (
                'السكني: موقف واحد لكل وحدة. '
                'التجاري: موقف واحد لكل 50 م² من المساحة المبنية.'),
            'financial_study_model': {
                'inputs': {'landArea': 5000, 'coverageRate': 60,
                           'builtUpAreaAbove': 16500, 'basementArea': 600},
                'dynamicRows': {'components': [
                    {'id': 'housing', 'name': 'شقق سكنية', 'useType': 'residential',
                     'units': 100, 'unitArea': 150, 'builtArea': 15000,
                     'revenueArea': 13000, 'investmentModel': 'sale'},
                    {'id': 'retail', 'name': 'محلات تجارية', 'useType': 'retail',
                     'units': 10, 'unitArea': 150, 'builtArea': 1500,
                     'revenueArea': 1200, 'investmentModel': 'annualRent'},
                ]},
            },
        }
        self.rules = {'rules': [
            {'componentId': 'housing', 'basis': 'units', 'spaces': 1, 'per': 1,
             'sourceQuote': 'السكني: موقف واحد لكل وحدة.'},
            {'componentId': 'retail', 'basis': 'builtArea', 'spaces': 1, 'per': 50,
             'sourceQuote': 'التجاري: موقف واحد لكل 50 م² من المساحة المبنية.'},
        ]}

    def build(self):
        return financial_parking.build_parking_plan(self.project, self.rules, 'plan-1')

    def test_counts_follow_each_use_and_not_the_whole_plot(self):
        plan = self.build()
        self.assertTrue(plan['canApply'], plan)
        self.assertEqual(plan['requiredSpaces'], 130)
        self.assertEqual([row['spaces'] for row in plan['requirements']], [100, 30])
        self.assertEqual(plan['parkingArea'], 3900)
        self.assertTrue(plan['areaIsEstimate'])
        self.assertFalse(plan['approved'])

    def test_rounds_each_requirement_up_and_handles_arabic_digits(self):
        self.project['financial_study_model']['dynamicRows']['components'][1]['builtArea'] = '١٬٥٠١'
        plan = self.build()
        self.assertEqual(plan['requiredSpaces'], 131)
        self.assertEqual(plan['requirements'][1]['quantity'], 1501)

    def test_missing_or_invented_regulations_never_become_a_zero_requirement(self):
        self.rules['rules'][1]['sourceQuote'] = 'التجاري: موقف لكل 25 م².'
        self.rules['rules'][1]['per'] = 25
        plan = self.build()
        self.assertFalse(plan['canApply'])
        self.assertTrue(plan['missing'])
        self.assertEqual(plan['requirements'][1]['spaces'], None)

    def test_copied_quote_cannot_back_a_different_numeric_rate(self):
        self.rules['rules'][1]['per'] = 25
        plan = self.build()
        self.assertFalse(plan['canApply'])
        self.assertIsNone(plan['requirements'][1]['spaces'])

    def test_units_cannot_be_substituted_for_an_area_based_requirement(self):
        self.rules['rules'][1].update(basis='units', per=50)
        self.assertFalse(self.build()['canApply'])

    def test_existing_manual_parking_is_preserved_without_double_counting(self):
        manual = {'id': 'manual-parking', 'name': 'مواقف قائمة', 'useType': 'parking',
                  'parkingLocation': 'basement', 'units': 10, 'unitArea': 30,
                  'builtArea': 300, 'revenueArea': 0, 'investmentModel': 'nonRevenue'}
        self.project['financial_study_model']['dynamicRows']['components'].append(manual)
        plan = self.build()
        self.assertEqual(plan['existingSpaces'], 10)
        self.assertEqual(plan['additionalSpaces'], 120)
        applied = financial_parking.apply_parking_plan(self.project['financial_study_model'], plan)
        rows = applied['dynamicRows']['components']
        self.assertIn(manual, rows)
        self.assertEqual(sum(row['units'] for row in rows if row['useType'] == 'parking'), 130)

    def test_basement_extension_is_an_explicit_proposal_not_a_regulatory_fact(self):
        self.project['approved_coverage_ratio'] = 100
        self.project['financial_study_model']['inputs'].update(coverageRate=100, basementArea=0)
        plan = self.build()
        self.assertTrue(plan['canApply'])
        self.assertEqual(plan['basementAreaTarget'], 3900)
        self.assertTrue(plan['warnings'])
        self.assertFalse(plan['approved'])
        self.assertEqual(self.project['financial_study_model']['inputs']['basementArea'], 0)

    def test_documented_basement_prohibition_does_not_get_overridden(self):
        self.project['approved_coverage_ratio'] = 100
        self.project['financial_study_model']['inputs'].update(coverageRate=100, basementArea=0)
        self.project['regulatory_constraints'] += ' لا يسمح بإنشاء بدرومات.'
        self.rules.update(basementAllowed=False, basementSourceQuote='لا يسمح بإنشاء بدرومات.')
        plan = self.build()
        self.assertFalse(plan['canApply'])
        self.assertGreater(plan['unallocatedSpaces'], 0)

    def test_reapplying_and_regenerating_do_not_duplicate_generated_rows(self):
        plan = self.build()
        model = financial_parking.apply_parking_plan(self.project['financial_study_model'], plan)
        again = financial_parking.apply_parking_plan(model, plan)
        self.assertEqual(model, again)
        project = dict(self.project, financial_study_model=again)
        next_plan = financial_parking.build_parking_plan(project, self.rules, 'plan-2')
        self.assertEqual(next_plan['requiredSpaces'], plan['requiredSpaces'])
        self.assertEqual(next_plan['additionalSpaces'], plan['additionalSpaces'])
        self.assertEqual(next_plan['basementAreaTarget'], plan['basementAreaTarget'])

    def test_changed_program_or_regulation_invalidates_an_approved_proposal(self):
        plan = self.build()
        plan['approved'] = True
        project = copy.deepcopy(self.project)
        project['financial_study_model'] = financial_parking.apply_parking_plan(
            project['financial_study_model'], plan)
        self.assertIsNone(financial_parking.parking_plan_error(project))
        project['financial_study_model']['dynamicRows']['components'][0]['units'] = 120
        self.assertIsNotNone(financial_parking.parking_plan_error(project))

    def test_basement_distribution_has_integer_spaces_and_exact_totals(self):
        self.project['approved_coverage_ratio'] = 100
        self.project['financial_study_model']['inputs'].update(coverageRate=100, basementArea=0)
        self.project['approved_financial_area'] = 1000
        self.project['croquis_land_area'] = 1000
        self.project['financial_study_model']['inputs']['landArea'] = 1000
        plan = self.build()
        rows = financial_parking.parking_distribution_rows(plan['components'], plan['footprintArea'])
        self.assertEqual(sum(row['units_per_floor'] for row in rows), 130)
        self.assertEqual(sum(row['floor_area_sqm'] for row in rows), 3900)
        self.assertTrue(all(isinstance(row['units_per_floor'], int) for row in rows))
        self.assertEqual(len(rows), 4)

    def test_square_meter_symbol_does_not_authorize_two_spaces(self):
        self.rules['rules'][1]['spaces'] = 2
        self.assertFalse(self.build()['canApply'])

    def test_a_retail_name_mentioning_parking_is_not_counted_as_parking_supply(self):
        self.project['financial_study_model']['dynamicRows']['components'][1]['name'] = 'محلات تجارية بجوار المواقف'
        plan = self.build()
        self.assertEqual(plan['requiredSpaces'], 130)
        self.assertEqual(plan['existingSpaces'], 0)

    def test_documented_basement_ban_stands_even_if_the_model_omits_it(self):
        self.project['approved_coverage_ratio'] = 100
        self.project['financial_study_model']['inputs'].update(coverageRate=100, basementArea=0)
        self.project['regulatory_constraints'] += ' لا يسمح بإنشاء بدرومات.'
        self.assertFalse(self.build()['canApply'])

    def test_regeneration_keeps_component_ids_for_revenue_links(self):
        plan = self.build()
        model = financial_parking.apply_parking_plan(self.project['financial_study_model'], plan)
        next_plan = financial_parking.build_parking_plan(dict(self.project, financial_study_model=model), self.rules, 'plan-2')
        self.assertEqual([row['id'] for row in plan['components']], [row['id'] for row in next_plan['components']])

    def test_boolean_and_nonfinite_numbers_are_not_parking_quantities(self):
        for value in (True, float('nan'), float('inf'), -4):
            with self.subTest(value=value):
                self.project['financial_study_model']['dynamicRows']['components'][0]['units'] = value
                self.assertFalse(self.build()['canApply'])

    def _apartments_clause(self, quote):
        self.project['regulatory_constraints'] = (
            'موقف لكل 25 م² من مسطحات المحلات والمعارض والمكاتب والمطاعم، ' + quote + '.')
        self.rules = {'rules': [
            {'componentId': 'housing', 'basis': 'units', 'spaces': 1, 'per': 1,
             'combination': 'max', 'sourceQuote': quote},
            {'componentId': 'housing', 'basis': 'builtArea', 'spaces': 1, 'per': 150,
             'combination': 'max', 'sourceQuote': quote},
            {'componentId': 'retail', 'basis': 'builtArea', 'spaces': 1, 'per': 25,
             'sourceQuote': 'موقف لكل 25 م² من مسطحات المحلات والمعارض والمكاتب والمطاعم'},
        ]}

    def test_one_clause_quote_documents_both_whichever_is_greater_alternatives(self):
        self._apartments_clause('وموقف لكل وحدة سكنية أو لكل 150 م² شقق سكنية أيهما أكثر')
        plan = self.build()
        self.assertTrue(plan['canApply'], plan)
        self.assertEqual(plan['requirements'][0]['spaces'], 100)
        self.assertEqual(plan['requirements'][0]['basis'], 'units')
        self.assertEqual(plan['requiredSpaces'], 160)
        self.assertEqual(plan['requirements'][0]['summary'],
                         'الأكبر من: موقف لكل وحدة، أو موقف لكل 150 م² مبنية')
        self.assertEqual(plan['requirements'][1]['summary'], 'موقف لكل 25 م² مبنية')
        self.assertNotIn('\n', plan['requirements'][0]['sourceQuote'])

    def test_a_verified_alternative_missing_its_quantity_warns_not_blocks(self):
        self._apartments_clause('وموقف لكل وحدة سكنية أو لكل 150 م² شقق سكنية أيهما أكثر')
        self.project['financial_study_model']['dynamicRows']['components'][0]['units'] = ''
        plan = self.build()
        self.assertTrue(plan['canApply'], plan)
        self.assertEqual(plan['requirements'][0]['spaces'], 100)
        self.assertEqual(plan['requirements'][0]['basis'], 'builtArea')
        self.assertEqual(plan['requirements'][0]['summary'], 'موقف لكل 150 م² مبنية')
        self.assertTrue(any('البديل المتاح' in warning for warning in plan['warnings']))

    def test_an_unverifiable_alternative_still_blocks_the_component(self):
        self._apartments_clause('وموقف لكل وحدة سكنية أو لكل 150 م² شقق سكنية أيهما أكثر')
        self.rules['rules'][0]['spaces'] = 5
        plan = self.build()
        self.assertFalse(plan['canApply'])
        self.assertIsNone(plan['requirements'][0]['spaces'])

    def test_summed_rules_still_require_every_quantity(self):
        self._apartments_clause('وموقف لكل وحدة سكنية وموقف لكل 150 م² للصالات')
        self.project['financial_study_model']['dynamicRows']['components'][0]['units'] = ''
        for rule in self.rules['rules']:
            rule['combination'] = 'sum'
        plan = self.build()
        self.assertFalse(plan['canApply'])
        self.assertIsNone(plan['requirements'][0]['spaces'])


if __name__ == '__main__':
    unittest.main()
