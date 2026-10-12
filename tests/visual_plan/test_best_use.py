import copy
import unittest

import best_use
import db


def project_fixture():
    return {
        'draftId': 'best-use-draft',
        'project_name': 'مشروع سكني',
        'project_type': '["سكني"]',
        'project_subtype': '{}',
        'project_language': 'ar',
        'land_documents_files_file_ids': ['croquis-1'],
        'land_documents_analysis': {'parcels': [{'land_area': 5000}]},
        'croquis_land_area': 5000,
        'approved_financial_area': 5000,
        'approved_coverage_ratio': 60,
        'approved_floor_count': 4,
        'approved_floor_area_ratio': 2,
        'building_ratio_coverage': 'التغطية المعتمدة 60% ومعامل مسطح البناء 2',
        'setbacks': 'الارتداد الأمامي 5 م، الخلفي 5 م، الجانبي 5 م',
        'allowed_uses': 'سكني وخدمات المشروع',
        'regulatory_constraints': 'المواقف والخدمات ضمن المساحة المتاحة',
        'survey_coordinates': [
            {'easting': 500000, 'northing': 2000000},
            {'easting': 500100, 'northing': 2000000},
            {'easting': 500100, 'northing': 2000050},
            {'easting': 500000, 'northing': 2000050},
        ],
        'directions_table': [{'direction': 'شمال', 'description': 'شارع', 'length': 100}],
        'location_address': 'https://maps.google.com/?q=21.5,39.2',
        'location_lat': '21.5',
        'location_lng': '39.2',
        'city': 'جدة',
        'district': 'حي الاختبار',
        'site_analysis': 'موقع سكني قريب من الخدمات',
        'site_analysis_approved': True,
        'tenantCreativeImages': {'map_placeholders': {'##MAP_OVERVIEW##': '/uploads/maps/site.png?s=old'}},
        'market_study_data': {
            'summary': {'market_definition': 'طلب موثق على الشقق السكنية',
                        'demand_analysis': 'الشقق المتوسطة ملائمة للفئة المستهدفة'},
            'one_block_summary': 'دراسة السوق تؤيد تطوير مشروع سكني متوسط.',
            'competitors': [{'name': 'منافس موثق', 'area_sqm': 100}],
        },
        'financial_study_model': {
            'inputs': {'builtUpAreaAbove': 6000, 'manualLandValue': 7000000,
                       'basementArea': 0, 'unitRevenueMode': 'sale'},
            'dynamicRows': {'components': [{'id': 'old', 'name': 'مكون حالي', 'builtArea': 6000}],
                            'revenue': [{'id': 'revenue-1', 'componentId': 'old', 'price': 5000}],
                            'cost': [{'id': 'cost-1', 'price': 900}]},
            'financialCalcData': {'components': [{'id': 'old', 'name': 'مكون حالي'}]},
        },
        'visual_concept': {'slots': {'cover': {'imageUrl': '/uploads/client-image.png',
                                             'approved': True}},
                           'plansWorkflow': {'ownerLocalWork': 'unchanged'}},
    }


def proposal_fixture():
    return {
        'title': 'توزيع سكني متوازن',
        'rationale': 'الطلب السوقي والحدود التنظيمية يدعمان توزيعًا سكنيًا مع خدمات ومساحات مفتوحة.',
        'setbackExplanation': 'التوزيع داخل حدود التغطية والارتدادات المسجلة في بيانات الأرض.',
        'components': [
            {'name': 'شقق سكنية', 'useType': 'residential', 'units': 80,
             'unitArea': 100, 'builtArea': 8000, 'revenueArea': 7200,
             'footprintArea': 2000, 'investmentModel': 'sale',
             'reason': 'مساحات الشقق تتفق مع الطلب المسجل في دراسة السوق.',
             'areaReason': 'ثمانون وحدة بمساحة 100 م² ضمن أربعة أدوار والمعامل المعتمد.'},
            {'name': 'خدمات السكان', 'useType': 'services', 'units': 1,
             'unitArea': 800, 'builtArea': 800, 'revenueArea': 0,
             'footprintArea': 200, 'investmentModel': 'nonRevenue',
             'reason': 'خدمات مساندة لنفس الاستخدام السكني.',
             'areaReason': 'حصة الخدمات ضمن إجمالي المسطحات المتاح.'},
            {'name': 'مساحات مفتوحة', 'useType': 'openArea', 'units': 1,
             'unitArea': 1800, 'builtArea': 1800, 'revenueArea': 0,
             'footprintArea': 1800, 'investmentModel': 'nonRevenue',
             'reason': 'مساحات مفتوحة للحركة والخدمات الخارجية.',
             'areaReason': 'ضمن الجزء غير المغطى من الأرض.'},
        ],
    }


class BestUseTests(unittest.TestCase):
    def setUp(self):
        self.project = project_fixture()
        self.raw = proposal_fixture()
        self.statuses = {'land_croquis': 'approved', 'location': 'approved',
                         'section-market-study': 'approved'}

    def test_existing_far_coverage_and_floors_define_the_capacity(self):
        budget = best_use.capacity(self.project)
        self.assertEqual(budget['landArea'], 5000)
        self.assertEqual(budget['coverageFootprint'], 3000)
        self.assertEqual(budget['farLimit'], 10000)
        self.assertEqual(budget['maxBuiltArea'], 10000)
        self.assertTrue(budget['setbackVerified'])
        self.assertNotIn('isDistinguished', budget)
        self.project['approved_floor_area_ratio'] = 4
        self.assertEqual(best_use.capacity(self.project)['maxBuiltArea'], 12000)

    def test_setbacks_can_be_stricter_than_the_coverage_limit(self):
        self.project['approved_coverage_ratio'] = 90
        self.project['approved_floor_area_ratio'] = 4
        budget = best_use.capacity(self.project)
        self.assertAlmostEqual(budget['setbackFootprint'], 3600)
        self.assertEqual(budget['maxBuiltArea'], 14400)

    def test_missing_geometry_is_reported_not_claimed_as_a_verified_envelope(self):
        self.project['survey_coordinates'] = []
        budget = best_use.capacity(self.project)
        self.assertFalse(budget['setbackVerified'])
        self.assertIsNone(budget['setbackFootprint'])
        self.assertEqual(budget['setbackIssue']['code'], 'rows')
        self.assertTrue(budget['warnings'])

    def test_setback_issue_names_the_specific_failure(self):
        self.project['croquis_land_area'] = 6000
        budget = best_use.capacity(self.project)
        self.assertFalse(budget['setbackVerified'])
        self.assertEqual(budget['setbackIssue']['code'], 'mismatch')
        self.assertEqual(budget['setbackIssue']['cadastralArea'], 6000)
        self.assertAlmostEqual(budget['setbackIssue']['polygonArea'], 5000)
        self.project['croquis_land_area'] = 5000
        self.project['setbacks'] = ''
        budget = best_use.capacity(self.project)
        self.assertEqual(budget['setbackIssue']['code'], 'setbacks')

    def test_a_single_documented_setback_is_not_invented_for_other_boundaries(self):
        self.project['setbacks'] = 'الارتداد الأمامي 5 م'
        self.assertFalse(best_use.capacity(self.project)['setbackVerified'])

    def test_rounding_does_not_create_inconsistent_unit_and_built_areas(self):
        self.raw['components'][0].update(unitArea=100.06, builtArea=8004.8, footprintArea=2001.2)
        with self.assertRaises(best_use.ProposalError):
            best_use.normalize_proposal(self.raw, self.project, 'proposal-1')

    def test_prerequisites_require_documents_location_market_and_approvals(self):
        self.assertEqual(best_use.missing_inputs(self.project, self.statuses), [])
        for key in ('land_croquis', 'location', 'section-market-study'):
            statuses = dict(self.statuses, **{key: 'draft'})
            self.assertIn(key, best_use.missing_inputs(self.project, statuses))
        self.project['land_documents_files_file_ids'] = []
        self.assertIn('croquis', best_use.missing_inputs(self.project, self.statuses))
        self.project['market_study_data'] = {'competitors': [{'name': 'منافس'}]}
        self.assertIn('market', best_use.missing_inputs(self.project, self.statuses))

    def test_proposal_is_normalized_with_server_ids_and_per_component_reasons(self):
        proposal = best_use.normalize_proposal(self.raw, self.project, 'proposal-1')
        self.assertFalse(proposal['approved'])
        self.assertFalse(proposal['rejected'])
        self.assertEqual(proposal['totals']['builtArea'], 8800)
        self.assertEqual(proposal['totals']['openArea'], 1800)
        self.assertEqual(proposal['totals']['footprintArea'], 2200)
        self.assertTrue(all(row['id'].startswith('best_proposal-1_') for row in proposal['components']))
        self.assertTrue(all(row['reason'] and row['areaReason'] for row in proposal['components']))

    def test_a_different_project_type_is_not_accepted(self):
        self.raw['components'][0]['useType'] = 'hospitality'
        with self.assertRaises(best_use.ProposalError):
            best_use.normalize_proposal(self.raw, self.project, 'proposal-1')

    def test_invalid_or_excessive_areas_never_become_an_approvable_proposal(self):
        changes = [
            {'builtArea': 12000}, {'footprintArea': 4000}, {'revenueArea': 8100},
            {'units': 2.5}, {'units': True}, {'unitArea': float('nan')},
            {'builtArea': -1}, {'reason': ''}, {'areaReason': ''},
        ]
        for change in changes:
            with self.subTest(change=change):
                raw = copy.deepcopy(self.raw)
                raw['components'][0].update(change)
                with self.assertRaises(best_use.ProposalError):
                    best_use.normalize_proposal(raw, self.project, 'proposal-1')

    def test_approval_replaces_only_components_and_preserves_prices_and_visual_work(self):
        proposal = best_use.normalize_proposal(self.raw, self.project, 'proposal-1')
        before = copy.deepcopy(self.project)
        updated = best_use.apply_proposal(self.project, proposal)
        model = updated['financial_study_model']
        rows = model['dynamicRows']['components']
        self.assertEqual(len(rows), 3)
        self.assertNotIn('old', [row['id'] for row in rows])
        self.assertEqual(model['inputs']['builtUpAreaAbove'], 8800)
        self.assertEqual(model['inputs']['manualLandValue'], 7000000)
        self.assertEqual(model['dynamicRows']['cost'], before['financial_study_model']['dynamicRows']['cost'])
        self.assertEqual(model['dynamicRows']['revenue'][0]['price'], 5000)
        self.assertEqual(updated['visual_concept'], before['visual_concept'])
        for key in ('approved_financial_area', 'approved_floor_count', 'approved_coverage_ratio',
                    'approved_floor_area_ratio', 'setbacks'):
            self.assertEqual(updated[key], before[key])
        self.assertEqual(self.project, before)

    def test_financial_edits_do_not_stale_the_land_and_market_proposal(self):
        initial = best_use.source_hash(self.project)
        self.project['financial_study_model']['dynamicRows']['components'][0]['name'] = 'تعديل يدوي'
        self.project['financial_study_model']['inputs']['manualLandValue'] = 8000000
        self.assertEqual(best_use.source_hash(self.project), initial)
        self.project['approved_floor_area_ratio'] = 3
        self.assertNotEqual(best_use.source_hash(self.project), initial)

    def test_calculator_revenue_mode_and_basement_are_not_generation_inputs(self):
        initial = best_use.source_hash(self.project)
        budget = best_use.capacity(self.project)
        self.project['financial_study_model']['inputs'].update(basementArea=99999, unitRevenueMode='rental')
        self.assertEqual(best_use.source_hash(self.project), initial)
        self.assertEqual(best_use.capacity(self.project), budget)
        context = best_use.prompt_context(self.project)
        self.assertNotIn('basementArea', context)
        self.assertNotIn('unitRevenueMode', context)
        self.assertNotIn('financial_study_model', context)
        self.assertEqual(context['mode'], 'guided')
        self.assertEqual(best_use.normalize_proposal(self.raw, self.project, 'p1')['mode'], 'guided')

    def test_component_investment_models_are_independent_of_calculator_mode(self):
        for mode in ('sale', 'rental', 'nonRevenue'):
            with self.subTest(mode=mode):
                self.project['financial_study_model']['inputs']['unitRevenueMode'] = mode
                self.raw['components'][0]['investmentModel'] = 'annualRent'
                self.assertEqual(best_use.normalize_proposal(self.raw, self.project, 'p1')
                                 ['components'][0]['investmentModel'], 'annualRent')

    def test_mode_is_part_of_the_snapshot_and_unsupported_modes_are_not_ready(self):
        initial = best_use.source_hash(self.project)
        self.project['best_use_data'] = {'mode': 'guided'}
        self.assertEqual(best_use.source_hash(self.project), initial)
        self.project['best_use_data']['mode'] = 'explore'
        self.assertNotEqual(best_use.source_hash(self.project), initial)
        self.assertIn('best_use_mode', best_use.missing_inputs(self.project, self.statuses))

    def test_basement_capacity_is_a_planning_bound_not_calculator_input_or_permission(self):
        budget = best_use.capacity(self.project)
        self.assertEqual(budget['basementAreaLimit'], 5000)
        self.assertNotIn('basementVerified', budget)
        basement = {'name': 'بدروم تخطيطي', 'useType': 'basement', 'units': 1,
                    'unitArea': 1000, 'builtArea': 1000, 'revenueArea': 0,
                    'footprintArea': 0, 'investmentModel': 'nonRevenue',
                    'reason': 'اقتراح يحتاج تحقق السماح التنظيمي.', 'areaReason': 'طبقة ضمن مساحة الأرض.'}
        self.raw['components'].append(basement)
        proposal = best_use.normalize_proposal(self.raw, self.project, 'p1')
        self.assertEqual(proposal['totals']['basementArea'], 1000)
        updated = best_use.apply_proposal(self.project, proposal)
        self.assertEqual(updated['financial_study_model']['inputs']['basementArea'], 1000)
        basement.update(unitArea=5001, builtArea=5001)
        with self.assertRaises(best_use.ProposalError):
            best_use.normalize_proposal(self.raw, self.project, 'p2')

    def test_application_drops_stale_calculations_but_keeps_manual_input_tables(self):
        model = self.project['financial_study_model']
        model.update(projection={'roi': 99}, report={'parts': ['old']},
                     tables={'componentsTable': ['old'], 'costTable': ['manual']},
                     parkingPlan={'id': 'old'}, parkingSnapshot={'old': True})
        model['financialCalcData']['roi'] = 99
        self.project['financial_calc_data'] = {'roi': 99}
        self.project['financial_study_model']['inputs']['basementArea'] = 3000
        proposal = best_use.normalize_proposal(self.raw, self.project, 'p1')
        updated = best_use.apply_proposal(self.project, proposal)
        model = updated['financial_study_model']
        for key in ('projection', 'report', 'parkingPlan', 'parkingSnapshot'):
            self.assertNotIn(key, model)
        self.assertEqual(model['tables'], {'costTable': ['manual']})
        self.assertEqual(model['financialCalcData'], {'components': model['dynamicRows']['components']})
        self.assertEqual(best_use.read_object(updated['financial_calc_data']), model['financialCalcData'])
        self.assertEqual(model['inputs']['basementArea'], 0)
        self.assertEqual(model['dynamicRows']['cost'], [{'id': 'cost-1', 'price': 900}])

    def test_resigning_an_owned_map_does_not_invalidate_the_proposal(self):
        initial = best_use.source_hash(self.project)
        self.project['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##'] = '/uploads/maps/site.png?s=new&t=123'
        self.assertEqual(best_use.source_hash(self.project), initial)
        self.project['tenantCreativeImages']['map_placeholders']['##MAP_OVERVIEW##'] = '/uploads/maps/other.png?s=new'
        self.assertNotEqual(best_use.source_hash(self.project), initial)

    def test_proposal_and_chat_are_excluded_from_presentation_generation_hashes(self):
        initial = db.draft_generation_input_hash(self.project)
        self.project['best_use_data'] = {'id': 'proposal-1', 'rationale': 'توصية غير معتمدة'}
        self.project['best_use_chat'] = {'messages': [{'role': 'user', 'content': 'سؤال'}]}
        self.assertEqual(db.draft_generation_input_hash(self.project), initial)

    def test_unused_and_rejected_proposals_are_optional(self):
        self.assertFalse(best_use.section_required({}))
        self.assertFalse(best_use.section_required({'best_use_data': {'id': 'p1', 'rejected': True}}))
        self.assertTrue(best_use.section_required({'best_use_data': {'id': 'p1', 'approved': False}}))

    def test_arabic_numbers_and_precision_are_supported_without_boolean_coercion(self):
        self.assertEqual(best_use.number('٥٬٠٠٠'), 5000)
        self.assertEqual(best_use.number('٢٫٥'), 2.5)
        self.assertIsNone(best_use.number(True))
        self.assertIsNone(best_use.number('NaN'))


if __name__ == '__main__':
    unittest.main()
