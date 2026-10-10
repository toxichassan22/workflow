import copy
import os
import tempfile
import unittest
from unittest.mock import patch

import db
import financial_parking
import test_financial_parking as parking_fixtures


class FinancialParkingPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(cls.directory.name, 'parking-plans.db')
        import app
        cls.module = app
        with app.app.app_context():
            db.init_db()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls.original_db_path
        cls.directory.cleanup()

    def setUp(self):
        fixture = parking_fixtures.FinancialParkingTests()
        fixture.setUp()
        self.project, rules = fixture.project, fixture.rules
        self.project.update(project_name='مشروع المواقف', approved_floor_count=10)
        self.project['financial_study_model']['inputs']['floorCount'] = 10
        plan = financial_parking.build_parking_plan(self.project, rules, 'plan-1')
        plan['approved'] = True
        self.project['financial_study_model'] = financial_parking.apply_parking_plan(
            self.project['financial_study_model'], plan)
        self.plan = plan
        self.regulations = patch.object(self.module, '_visual_concept_plan_regulation_facts', return_value={})
        self.regulations.start()
        self.addCleanup(self.regulations.stop)

    def context(self):
        return self.module._visual_concept_plan_context(self.project)

    def test_context_reads_json_financial_models_and_refreshes_a_cached_program(self):
        import json
        project = dict(self.project, financial_study_model=json.dumps(self.project['financial_study_model']))
        context = self.module._visual_concept_plan_context(project)
        self.assertTrue(context['parking']['approved'])
        self.assertEqual(context['parking']['requiredSpaces'], 130)
        _, _, _, _, cached = self.module._visual_concept_plans_context_from_request({
            'projectData': project, 'plansWorkflow': {'planContext': {'components': []}}})
        self.assertEqual(len(cached['components']), len(context['components']))
        self.assertEqual(cached['parking']['requiredSpaces'], 130)

    def test_surface_parking_is_not_a_basement_or_an_extra_building(self):
        context = self.context()
        rows = self.module._financial_parking_merge_distribution_rows([], context)
        distribution = self.module._visual_concept_plan_normalize_distribution({'rows': rows}, context, {})
        model = self.module._visual_concept_plan_model_from_distribution(distribution, context, {})
        self.assertEqual(len(model['open_uses']), 1)
        self.assertEqual(model['open_uses'][0]['items'][0]['units'], 66)
        self.assertEqual(len(model['blocks']), 0)
        self.assertFalse(any(band['items'][0]['name'].endswith('سطحية') for band in model['below']))

    def test_single_basement_floor_is_not_multiplied_by_its_floor_number(self):
        for label in ('B3', 'بدروم 3'):
            with self.subTest(label=label):
                self.assertEqual(self.module._visual_concept_plan_floor_range(label)['count'], 1)
        parsed = self.module._visual_concept_plan_floor_range('بدروم 2-4')
        self.assertEqual(parsed, {'kind': 'basement', 'lo': -4, 'hi': -2, 'count': 3})

    def test_generating_distribution_keeps_the_exact_parking_totals(self):
        context = self.context()
        rows = self.module._financial_parking_merge_distribution_rows([
            {'component': self.plan['components'][0]['name'], 'floor_range': 'أرضي',
             'units_per_floor': 999, 'floor_area_sqm': 9999},
            {'component': 'شقق سكنية', 'floor_range': '1-10', 'units_per_floor': 10, 'floor_area_sqm': 1500},
        ], context)
        distribution = self.module._visual_concept_plan_normalize_distribution({'rows': rows}, context, {})
        parking_totals = [item for item in distribution['totals'] if 'مواقف' in item['component']]
        self.assertEqual(sum(item['units'] for item in parking_totals), 130)
        self.assertEqual(sum(item['area'] for item in parking_totals), 3900)
        self.assertFalse(any(check.get('fixedFact') for check in distribution['checks']))

    def test_modified_parking_counts_cannot_be_softened_by_the_model(self):
        context = self.context()
        rows = self.module._financial_parking_merge_distribution_rows([], context)
        rows[0]['units_per_floor'] -= 1
        distribution = self.module._visual_concept_plan_normalize_distribution({'rows': rows}, context, {})
        checks = distribution['checks']
        hard_indices = [index for index, check in enumerate(checks) if check.get('fixedFact')]
        self.assertTrue(hard_indices)
        reviewed = self.module._visual_concept_plan_adjudicate_checks(
            checks, [{'index': index, 'result': 'مطابق'} for index in hard_indices])
        self.assertTrue(any(check.get('fixedFact') and check['result'] == 'متعارض' for check in reviewed))

    def test_all_drawing_prompts_and_exterior_context_carry_the_financial_capacity(self):
        context = self.context()
        for kind in ('site', 'uses', 'massing'):
            with self.subTest(kind=kind):
                prompt = self.module._visual_concept_plan_drawing_prompt(kind, context)
                self.assertIn('Regulatory demand=130 spaces', prompt)
                self.assertIn('Surface Parking: 66', prompt)
                self.assertIn('including circulation', prompt)
        text = self.module._visual_concept_plan_context_text(context, diagram_rules=False)
        self.assertIn('Regulatory demand=130 spaces', text)
        self.assertNotIn('All image labels', text)

    def test_site_parking_does_not_consume_far_or_coverage_floor_space(self):
        context = self.context()
        context.update(land_area='5000', coverage_ratio='10', floor_area_ratio='0.1')
        surface = next(row for row in self.plan['components'] if row['parkingLocation'] == 'surface')
        rows = [{'component': surface['name'], 'floor_range': 'مساحة مفتوحة',
                 'units_per_floor': surface['units'], 'floor_area_sqm': surface['builtArea']}]
        normalized = self.module._visual_concept_plan_normalize_distribution({'rows': rows}, context, {})
        self.assertFalse(any(check['item'] in ('إجمالي المسطحات يتجاوز معامل البناء', 'مساحة الدور تتجاوز حد التغطية')
                             for check in normalized['checks']))

    def test_inferred_distribution_does_not_loop_when_uses_exceed_floor_count(self):
        context = self.context()
        context['floor_count'] = 1
        context['components'].append({'name': 'مواقف فوق الأرض', 'useType': 'parking',
                                      'parkingLocation': 'aboveGround', 'units': 10, 'builtArea': 300})
        self.assertIsNotNone(self.module._visual_concept_plan_model(context, {}))


if __name__ == '__main__':
    unittest.main()
