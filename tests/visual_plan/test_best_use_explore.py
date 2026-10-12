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
        self.pages = [{'documentId': 'croquis-1', 'page': 1, 'kind': 'parcel',
                       'text': 'رقم القطعة: 42\nكود التنظيم: س ع\nالاستخدامات المسموحة: سكني، تجاري\n'}]

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

    def test_complete_scoped_use_list_is_parsed_without_a_model(self):
        result = regulations.extract(self.project, self.pages)
        self.assertEqual(set(result['permittedUses']), {'residential', 'retail', 'office', 'entertainment'})
        self.assertFalse(result['requiresApproval'])
        self.assertTrue(result['evidence'])
        for item in result['evidence']:
            self.assertEqual(item['documentId'], 'croquis-1')
            self.assertEqual(item['parcelScope'], '42')
            self.assertIn(item['excerpt'], self.pages[0]['text'])

    def test_negation_conditions_wrong_scope_and_partial_text_fail_closed(self):
        cases = ['رقم القطعة: 99\nالاستخدامات المسموحة: سكني',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: سكني بشرط موافقة الجهة',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: سكني، لا يسمح بتجاري',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: حسب المخطط المعتمد',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: سكني\nيحظر تطوير الأرض',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: سكني\nلا يسمح بالاستخدام السكني']
        for text in cases:
            with self.subTest(text=text), self.assertRaises(best_use.ProposalError):
                regulations.extract(self.project, [dict(self.pages[0], text=text + '\nكود التنظيم: س ع')])

    def test_a_croquis_without_parcel_identifiers_falls_back_to_declared_uses(self):
        pages = [{'documentId': 'croquis-1', 'page': 1, 'kind': 'parcel',
                  'text': 'كروكي قديم بلا رقم قطعة أو كود تنظيم'}]
        result = regulations.extract(self.project, pages)
        self.assertEqual(result['permittedUses'], ['residential'])
        self.assertEqual(result['basis'], 'declared')
        self.assertTrue(result['requiresApproval'])
        self.assertFalse(result['scope']['proven'])
        self.assertEqual(result['scope']['plotNumber'], '42')
        self.assertTrue(all(item['documentId'] == 'declared-inputs' for item in result['evidence']))
        # A document that does mark a different parcel still proves the wrong file.
        pages[0]['text'] = 'رقم القطعة: 99\nالاستخدامات المسموحة: سكني'
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, pages)

    def test_declared_uses_drop_negated_or_conditional_clauses(self):
        pages = [{'documentId': 'croquis-1', 'page': 1, 'kind': 'parcel', 'text': 'كروكي قديم'}]
        self.project['allowed_uses'] = 'سكني، تجاري بشرط موافقة الجهة، صناعي غير مسموح'
        result = regulations.extract(self.project, pages)
        self.assertEqual(result['permittedUses'], ['residential'])
        self.project['allowed_uses'] = 'لا يسمح بأي استخدام'
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, pages)

    def test_a_document_without_declarations_still_fails_without_declared_uses(self):
        pages = [dict(self.pages[0], text='رقم القطعة: 42\nكود التنظيم: س ع\nالمشروع السكني مسموح')]
        self.project['allowed_uses'] = ''
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, pages)

    def test_model_excerpt_must_be_a_full_verifiable_declaration_not_a_word(self):
        raw = {'declarations': [{'documentId': 'croquis-1', 'page': 1, 'excerpt': 'سكني'}]}
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, self.pages, raw)

    def test_interpreted_declarations_must_quote_the_scoped_page_verbatim(self):
        pages = [dict(self.pages[0], text='رقم القطعة: 42\nكود التنظيم: س ع\nيسمح بالاستعمالات الآتية على القطعة: سكني\n')]
        # No machine-readable declaration: the declared client inputs carry it.
        result = regulations.extract(self.project, pages)
        self.assertEqual(result['basis'], 'declared')
        self.assertEqual(result['permittedUses'], ['residential'])
        interpreted = {'declarations': [{'documentId': 'croquis-1', 'page': 1,
                                         'excerpt': 'الاستعمالات المسموحة: سكني'}]}
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, pages, interpreted)
        interpreted['declarations'][0].update(page=2)
        pages[0]['text'] += 'الاستعمالات المسموحة: سكني\n'
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, pages, interpreted)
        interpreted['declarations'][0].update(page=1)
        result = regulations.extract(self.project, pages, interpreted)
        self.assertEqual(result['permittedUses'], ['residential'])
        self.assertTrue(result['requiresApproval'])
        self.assertTrue(all(item['parcelScope'] == '42' for item in result['evidence']))

    def test_an_interpreted_negated_or_conditional_list_still_fails_closed(self):
        pages = [dict(self.pages[0], text='رقم القطعة: 42\nكود التنظيم: س ع\nالاستعمالات المسموحة: سكني بشرط موافقة الجهة\n')]
        interpreted = {'declarations': [{'documentId': 'croquis-1', 'page': 1,
                                         'excerpt': 'الاستعمالات المسموحة: سكني بشرط موافقة الجهة'}]}
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, pages, interpreted)

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
