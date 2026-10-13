import copy
import unittest

import best_use
import best_use_explore as explore
import best_use_workflow as workflow
import best_use_regulations as regulations
from best_use_contract import canonical_use
from tests.visual_plan.test_best_use import project_fixture


class ExplorationContractTests(unittest.TestCase):
    def setUp(self):
        self.project = project_fixture()
        self.project.update(plot_number_croquis='42', zoning_code='س ع')
        self.project['best_use_explore_data'] = {'mode': 'explore'}
        self.project['best_use_mode'] = 'explore'

    def artifact(self, name, payload):
        state = self.project['best_use_explore_data']
        state[name] = workflow.make_artifact(self.project, name, payload, name + '-1', state.get(name))
        return state[name]

    def populate(self):
        self.artifact('regulations', {'permittedUses': ['residential'], 'requiresApproval': False})
        self.artifact('priceScan', {'table': []})
        self.artifact('concepts', {'items': [{'id': 'c1'}, {'id': 'c2'}]})
        workflow.select_concept(self.project, 'c1')
        self.artifact('landDistribution', {'components': [{'footprintArea': 100}]})
        self.artifact('floorDistribution', {'components': [{'builtArea': 200}]})

    def test_exploration_snapshot_stays_independent_while_tracking_declared_regulations(self):
        original = workflow.source_hash(self.project)
        self.project.update(project_type='["فندقي"]', project_idea='فندق فقط',
                            market_study_data={'summary': 'سوق آخر'}, project_language='en',
                            land_documents_analysis={'project_type': 'فندقي', 'allowed_uses': 'فندقي'},
                            land_use_status='غير مسموح')
        self.assertEqual(workflow.source_hash(self.project), original)
        context = workflow.prompt_context(self.project)
        for key in workflow.EXPLORE_EXCLUDED:
            self.assertNotIn(key, context)
        # The AI site analysis is a tracked explore input: it steers the
        # distribution model, so it must be in the context and in the hash.
        self.assertIn('site_analysis', context)
        self.project.update(allowed_uses='سكني وتجاري', regulatory_constraints='قيود محدثة',
                            site_analysis='تحليل مبني على فكرة العميل')
        self.assertNotEqual(workflow.source_hash(self.project), original)
        context = workflow.prompt_context(self.project)
        self.assertEqual(context['allowed_uses'], 'سكني وتجاري')
        self.assertEqual(context['regulatory_constraints'], 'قيود محدثة')

    def test_exploration_needs_land_and_location_but_not_project_type_or_market(self):
        self.project.pop('project_type')
        self.project.pop('market_study_data')
        self.project.pop('land_documents_analysis')
        self.project['land_use_status'] = 'غير مسموح'
        self.assertEqual(workflow.missing_inputs(self.project, {'land_croquis': 'approved', 'location': 'approved'}), [])

    def test_missing_inputs_name_each_declared_regulation_field(self):
        self.project.update(allowed_uses='', land_and_building_summary='', regulatory_constraints='',
                            building_ratio_coverage='', directions_table=[], approved_typical_floor_coverage='')
        missing = workflow.missing_inputs(self.project, {'land_croquis': 'approved', 'location': 'approved'})
        for key in ('allowed_uses', 'land_and_building_summary', 'regulatory_constraints',
                    'building_ratio_coverage', 'directions_table', 'approved_typical_floor_coverage'):
            self.assertIn(key, missing)

    def test_typical_floor_coverage_is_optional_for_single_floor_land(self):
        self.project.update(approved_floor_count=1, approved_typical_floor_coverage='')
        self.assertEqual(workflow.missing_inputs(self.project, {'land_croquis': 'approved', 'location': 'approved'}), [])

    def test_declared_uses_are_parsed_without_documents_or_a_model(self):
        self.project['allowed_uses'] = 'سكني، تجاري'
        result = regulations.declared(self.project)
        self.assertEqual(set(result['permittedUses']), {'residential', 'retail', 'office', 'entertainment'})
        self.assertEqual(result['basis'], 'declared')
        self.assertTrue(result['requiresApproval'])
        self.assertTrue(result['evidence'])
        for item in result['evidence']:
            self.assertEqual(item['documentId'], 'declared-inputs')
            self.assertEqual(item['parcelScope'], '42')
            self.assertEqual(item['landClassification'], 'س ع')
            self.assertEqual(item['excerpt'], 'سكني، تجاري')

    def test_declared_uses_drop_negated_or_conditional_clauses(self):
        self.project['allowed_uses'] = 'سكني، تجاري بشرط موافقة الجهة، صناعي غير مسموح'
        result = regulations.declared(self.project)
        self.assertEqual(result['permittedUses'], ['residential'])
        self.project['allowed_uses'] = 'لا يسمح بأي استخدام'
        with self.assertRaises(best_use.ProposalError):
            regulations.declared(self.project)

    def test_missing_or_unparseable_declared_uses_fail_closed(self):
        for value in ('', 'غير محددة في المرجع المتاح', 'حسب المخطط المعتمد', 'سكني بشرط موافقة الجهة'):
            with self.subTest(value=value), self.assertRaises(best_use.ProposalError):
                regulations.declared(dict(self.project, allowed_uses=value))

    def test_a_documented_development_ban_in_the_summary_fields_still_blocks(self):
        for key in ('allowed_uses', 'regulatory_constraints', 'land_and_building_summary'):
            project = dict(self.project, **{key: self.project[key] + '\nيحظر تطوير الأرض'})
            with self.subTest(key=key), self.assertRaises(best_use.ProposalError):
                regulations.declared(project)

    def test_concept_uses_accept_arabic_labels_and_name_unpermitted_ones(self):
        self.assertEqual(canonical_use('سكني'), 'residential')
        self.assertEqual(canonical_use('مواقف'), 'parking')
        basis = {'use': 'residential', 'documentId': 'declared-inputs', 'page': 0,
                 'excerpt': 'سكني', 'parcelScope': '42', 'landClassification': 'س ع',
                 'conditions': [], 'status': 'permitted'}
        regs = {'permittedUses': ['residential'], 'evidence': [basis], 'constraints': []}
        row = {'name': 'شقق', 'useType': 'سكني', 'units': 1, 'unitArea': 500,
               'builtArea': 500, 'grossArea': 500, 'revenueArea': 450, 'nonRevenueArea': 50,
               'footprintArea': 500, 'investmentModel': 'sale',
               'reason': 'سبب', 'areaReason': 'سبب', 'revenueAreaBasis': 'افتراض',
               'allowedUseBasis': dict(basis)}
        scan = {'table': [], 'observations': [], 'status': 'partial'}
        raw = {'concepts': [{'name': 'مفهوم', 'summary': 's', 'siteFit': 's',
                             'revenueBasis': 's', 'uses': ['سكني'], 'components': [row]}]}
        result = explore.concepts(raw, self.project, regs, scan, 'art')
        self.assertEqual(result['items'][0]['uses'], ['residential'])
        self.assertEqual(result['items'][0]['components'][0]['useType'], 'residential')
        raw['concepts'][0]['uses'] = ['فندقي']
        with self.assertRaises(best_use.ProposalError) as ctx:
            explore.concepts(raw, self.project, regs, scan, 'art')
        self.assertIn('hospitality', str(ctx.exception))

    def test_a_shared_support_component_binds_to_a_permitted_use_its_label_names(self):
        basis = {'documentId': 'declared-inputs', 'page': 0, 'excerpt': 'سكني ومكاتب',
                 'parcelScope': '42', 'landClassification': 'س ع'}
        regs = {'permittedUses': ['office', 'residential'],
                'evidence': [dict(basis, use=use, conditions=[], status='permitted')
                             for use in ('residential', 'office')],
                'constraints': []}
        components = [
            {'name': 'مكاتب', 'useType': 'office', 'units': 1, 'unitArea': 500, 'builtArea': 500,
             'grossArea': 500, 'revenueArea': 450, 'nonRevenueArea': 50, 'footprintArea': 500,
             'investmentModel': 'annualRent', 'reason': 'سبب', 'areaReason': 'سبب',
             'revenueAreaBasis': 'افتراض', 'allowedUseBasis': dict(basis)},
            {'name': 'مواقف سيارات وخدمات ميكانيكية بالقبو', 'useType': 'parking', 'units': 1,
             'unitArea': 3000, 'builtArea': 3000, 'grossArea': 3000, 'revenueArea': 0,
             'nonRevenueArea': 3000, 'footprintArea': 0, 'investmentModel': 'nonRevenue',
             'parkingLocation': 'basement', 'reason': 'سبب', 'areaReason': 'سبب',
             'revenueAreaBasis': 'افتراض', 'supportUseOf': 'سكني ومكاتب',
             'allowedUseBasis': dict(basis)}]
        raw = {'title': 't', 'rationale': 'r', 'setbackExplanation': 'e', 'components': components}
        # canonical_use resolves «سكني ومكاتب» to residential — outside an
        # office-only concept — while the label still names the permitted
        # office use; the support component binds to it instead of rejecting.
        normalized = explore.distribution(raw, self.project, regs, 'art',
                                          stage='land', allowed_uses=['office'])
        parking = next(row for row in normalized['components'] if row['useType'] == 'parking')
        self.assertEqual(parking['supportUseOf'], 'office')
        normalized = explore.distribution(raw, self.project, regs, 'art',
                                          stage='land', allowed_uses=['office', 'residential'])
        parking = next(row for row in normalized['components'] if row['useType'] == 'parking')
        self.assertEqual(parking['supportUseOf'], 'residential')
        # An umbrella label binds to the concept's first permitted use — the
        # declared evidence entry is the same for every permitted use anyway.
        components[1]['supportUseOf'] = 'كل الاستخدامات المسموحة'
        normalized = explore.distribution(raw, self.project, regs, 'art',
                                          stage='land', allowed_uses=['office'])
        parking = next(row for row in normalized['components'] if row['useType'] == 'parking')
        self.assertEqual(parking['supportUseOf'], 'office')
        # A fabricated basis still fails: the binding only picks the use, the
        # declared evidence check still gates the component.
        components[1]['allowedUseBasis'] = dict(basis, excerpt='دليل مخترع')
        with self.assertRaises(best_use.ProposalError):
            explore.distribution(raw, self.project, regs, 'art',
                                 stage='land', allowed_uses=['office'])

    def test_selection_does_not_approve_or_gate_generation(self):
        self.populate()
        self.assertEqual(workflow.selected_concept(self.project)['id'], 'c1')
        self.assertFalse(workflow.approved(self.project, 'concepts'))
        self.assertTrue(workflow.current(self.project, 'landDistribution'))
        self.assertTrue(workflow.current(self.project, 'floorDistribution'))

    def test_selection_invalidates_only_downstream_artifacts(self):
        self.populate()
        workflow.select_concept(self.project, 'c2')
        self.assertTrue(workflow.current(self.project, 'concepts'))
        self.assertTrue(workflow.current(self.project, 'priceScan'))
        self.assertFalse(workflow.current(self.project, 'landDistribution'))
        self.assertFalse(workflow.current(self.project, 'floorDistribution'))

    def test_content_and_input_bound_approvals_are_required(self):
        self.populate()
        state = self.project['best_use_explore_data']
        for name in workflow.ARTIFACTS:
            artifact = state[name]
            artifact.update(approved=True, approvedContentHash=artifact['contentHash'],
                            approvedInputHash=artifact['inputHash'])
        self.assertIsNone(workflow.section_error(self.project))
        state['landDistribution']['components'][0]['footprintArea'] = 200
        self.assertEqual(workflow.section_error(self.project), 'BEST_USE_INPUTS_CHANGED')
        workflow.refresh(self.project)
        self.assertFalse(state['floorDistribution'].get('inputsChanged', False))
        self.assertTrue(self.project['best_use_explore_data']['floorDistribution']['inputsChanged'])

    def test_a_boolean_flag_alone_is_not_an_approval(self):
        self.populate()
        for artifact in self.project['best_use_explore_data'].values():
            if isinstance(artifact, dict):
                artifact['approved'] = True
        self.assertEqual(workflow.section_error(self.project), 'BEST_USE_APPROVAL_REQUIRED')

    def test_mode_switches_preserve_freshness_while_land_changes_invalidate(self):
        self.populate()
        previous = copy.deepcopy(self.project)
        self.project['approved_floor_count'] = 5
        self.assertFalse(workflow.current(self.project, 'regulations'))
        self.assertFalse(workflow.current(self.project, 'floorDistribution'))
        previous['best_use_mode'] = 'guided'
        self.assertTrue(workflow.current(previous, 'concepts'))
        workflow.refresh(previous)
        self.assertFalse(previous['best_use_explore_data']['concepts'].get('inputsChanged', False))


if __name__ == '__main__':
    unittest.main()
