import copy
import unittest

import best_use
import best_use_workflow as workflow
import best_use_regulations as regulations
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

    def test_exploration_snapshot_is_independent_even_of_analysis_and_language(self):
        original = workflow.source_hash(self.project)
        self.project.update(project_type='["فندقي"]', project_idea='فندق فقط',
                            market_study_data={'summary': 'سوق آخر'}, project_language='en',
                            land_documents_analysis={'project_type': 'فندقي', 'allowed_uses': 'فندقي'},
                            allowed_uses='فندقي', land_use_status='غير مسموح',
                            regulatory_constraints='قيود تخص فكرة العميل')
        self.assertEqual(workflow.source_hash(self.project), original)
        context = workflow.prompt_context(self.project)
        for key in workflow.EXPLORE_EXCLUDED:
            self.assertNotIn(key, context)

    def test_exploration_needs_land_and_location_but_not_project_type_or_market(self):
        self.project.pop('project_type')
        self.project.pop('market_study_data')
        self.project.pop('land_documents_analysis')
        self.project['land_use_status'] = 'غير مسموح'
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
                 'رقم القطعة: 42\nالمشروع السكني مسموح',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: حسب المخطط المعتمد',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: سكني\nيحظر تطوير الأرض',
                 'رقم القطعة: 42\nالاستخدامات المسموحة: سكني\nلا يسمح بالاستخدام السكني']
        for text in cases:
            with self.subTest(text=text), self.assertRaises(best_use.ProposalError):
                regulations.extract(self.project, [dict(self.pages[0], text=text + '\nكود التنظيم: س ع')])

    def test_model_excerpt_must_be_a_full_verifiable_declaration_not_a_word(self):
        raw = {'declarations': [{'documentId': 'croquis-1', 'page': 1, 'excerpt': 'سكني'}]}
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, self.pages, raw)

    def test_interpreted_declarations_must_quote_the_scoped_page_verbatim(self):
        pages = [dict(self.pages[0], text='رقم القطعة: 42\nكود التنظيم: س ع\nيسمح بالاستعمالات الآتية على القطعة: سكني\n')]
        with self.assertRaises(best_use.ProposalError):
            regulations.extract(self.project, pages)
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
