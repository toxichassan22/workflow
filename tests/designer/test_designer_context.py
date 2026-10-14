"""Designer project facts and current-deck context never silently lose fields."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import designer_chat_context as context


class DesignerContextTests(unittest.TestCase):
    def test_all_nested_fields_false_zero_and_long_values_survive(self):
        names = ['financial_study_model', 'timeline_table_data', 'market_study_data',
                 'executive_content', 'land_documents_analysis', 'nearby_landmarks_data',
                 'project_components_data', 'visual_concept', 'custom_file_meta', '_custom']
        source = {name: json.dumps({'custom': name + '_sentinel', 'zero': 0, 'off': False,
                                    'clear': None, 'rows': list(range(100))}) for name in names}
        source['long'] = 'x' * 130000 + 'END_SENTINEL'
        source['tenantSlidesData'] = [{'html': 'PREVIOUS_DECK'}]
        source['designerChat'] = {'messages': ['OLD_CHAT']}
        original = copy.deepcopy(source)
        result = json.loads(context.build_project_context(source))['project_data']
        for name in names:
            self.assertEqual(result[name]['custom'], name + '_sentinel')
            self.assertIs(result[name]['off'], False)
            self.assertEqual(result[name]['zero'], 0)
            self.assertIsNone(result[name]['clear'])
            self.assertEqual(result[name]['rows'][-1], 99)
        self.assertEqual(result['long'], source['long'])
        self.assertNotIn('tenantSlidesData', result)
        self.assertEqual(source, original)

    def test_binary_reference_keeps_path_and_durable_urls(self):
        source = {'image': 'data:image/png;base64,QUJD', 'logo': '/uploads/logo.png',
                  'custom': {'slides': ['nested fact']}}
        result = json.loads(context.build_project_context(source))['project_data']
        self.assertEqual(result['image']['asset_reference']['path'], '$.project_data.image')
        self.assertEqual(result['logo'], '/uploads/logo.png')
        self.assertEqual(result['custom']['slides'], ['nested fact'])
        self.assertNotIn('QUJD', json.dumps(result))

    def test_selected_team_extensions_and_role_clears_survive(self):
        database = Mock(PREBUILT_FIELDS=[])
        database.get_team_entities.return_value = [
            {'id': 'a', 'name': 'A', 'role': 'old', 'extra': 'extension'},
            {'id': 'b', 'name': 'B'}]
        database.get_fields.return_value = [{'key': 'custom', 'label': 'Custom label'}]
        source = {'custom': 'fact', 'team_selection': json.dumps({
            'excluded': ['b'], 'roles': {'a': ''}, 'local': [{'name': 'Local', 'extra': 12}]})}
        with patch.object(context.importlib, 'import_module', return_value=database):
            result = json.loads(context.build_project_context(source, tenant_id='tenant'))
        self.assertEqual(result['selected_team_entities'], [
            {'id': 'a', 'name': 'A', 'role': '', 'extra': 'extension'}, {'name': 'Local', 'extra': 12}])
        self.assertEqual(result['field_labels']['custom'], 'Custom label')
        database.get_team_entities.assert_called_once_with('tenant')

    def test_deck_carries_every_slide_content_style_and_metadata(self):
        slides = [{'html': '<div class="slide" style="color:#123456">' + 'a' * 160000 + 'LAST</div>',
                   'section_key': 'financial', 'content_source': 'report', 'custom': False},
                  {'html': '<div class="slide"><table><tr><td>SECOND_VALUE</td></tr></table></div>'}]
        result = json.loads(context.build_deck_context(slides))['slides']
        self.assertEqual(result[0]['slide']['html'], slides[0]['html'])
        self.assertEqual(result[1]['slide']['html'], slides[1]['html'])
        self.assertEqual(result[1]['slide_number'], 2)

    def test_cyclic_source_fails_instead_of_partial_context(self):
        source = {}; source['self'] = source
        with self.assertRaises(context.DesignerContextError):
            context.build_project_context(source)

    def test_internal_snapshot_copies_strip_at_every_depth(self):
        """Drift-check copies stored inside the payload must not sit beside the
        live values: a context carrying both reads them as conflicting facts
        («الأدوار 10 أم 12»)."""
        source = {
            'financial_study_model': json.dumps({
                'inputs': {'floorCount': 12, 'landArea': 5000},
                'parkingSnapshot': {'floorCount': 10, 'landArea': 5000},
                'parkingPlan': {'id': 'p1', 'approved': True,
                                'sourceSnapshot': {'floorCount': 10},
                                'sourceHash': 'hash-1',
                                'components': [{'name': 'مواقف'}]},
            }),
            'best_use_data': {
                'title': 'التوزيع', 'components': [{'name': 'شقق'}],
                'approved': True,
                'sourceSnapshot': {'approved_floor_count': 10},
                'sourceHash': 'h1', 'inputHash': 'h2', 'contentHash': 'h3'},
            'visual_concept': {'plansWorkflow': {
                'planContext': {'floor_count': '10'},
                'distribution': {'rows': [{'component': 'مول', 'units': 4}]}}},
            'market_study_data': {'competitors': [
                {'name': 'منافس', 'price': 9000,
                 'price_cache': {'price': 8000}, 'area_cache': {'area': 700},
                 'benchmarks': {'avg': 8500}}]},
        }
        result = json.loads(context.build_project_context(source))['project_data']
        model = result['financial_study_model']
        self.assertEqual(model['inputs']['floorCount'], 12)
        self.assertNotIn('parkingSnapshot', model)
        self.assertNotIn('sourceSnapshot', model['parkingPlan'])
        self.assertNotIn('sourceHash', model['parkingPlan'])
        self.assertEqual(model['parkingPlan']['components'], [{'name': 'مواقف'}])
        best_use = result['best_use_data']
        self.assertNotIn('sourceSnapshot', best_use)
        self.assertNotIn('sourceHash', best_use)
        self.assertNotIn('inputHash', best_use)
        self.assertNotIn('contentHash', best_use)
        self.assertEqual(best_use['components'], [{'name': 'شقق'}])
        workflow = result['visual_concept']['plansWorkflow']
        self.assertNotIn('planContext', workflow)
        self.assertEqual(workflow['distribution']['rows'][0]['units'], 4)
        competitor = result['market_study_data']['competitors'][0]
        self.assertNotIn('price_cache', competitor)
        self.assertNotIn('area_cache', competitor)
        self.assertNotIn('benchmarks', competitor)
        self.assertEqual(competitor['price'], 9000)

    def test_root_chat_and_run_state_keys_strip(self):
        """Stored conversations and run state are bookkeeping — the snapshot
        used to dump them beside the facts as if they were data."""
        source = {
            'project_name': 'مشروع',
            'best_use_chat': {'messages': ['OLD_TURN']},
            'designerChatSessions': {'s1': {'memory': 'OLD'}},
            'chatHistory': [{'content': 'OLD_TURN'}],
            'draftHistory': [{'change': 'OLD'}],
            'tenantArchiveCache': {'html': 'OLD'},
            'slide_generation_checkpoint': {'nextIndex': 1},
            'tenantSlidePlan': {'slides': []}, 'slidesData': [{'html': 'x'}],
            'presentation_scope': 'all', 'schema_version': 3,
            'draftId': 'd1', 'draft_id': 'd1',
        }
        result = json.loads(context.build_project_context(source))['project_data']
        self.assertEqual(result, {'project_name': 'مشروع'})

    def test_strip_internal_snapshots_decodes_string_blobs(self):
        blob = json.dumps({'inputs': {'floorCount': 12},
                           'parkingSnapshot': {'floorCount': 10}})
        self.assertEqual(context.strip_internal_snapshots(blob),
                         {'inputs': {'floorCount': 12}})
        self.assertEqual(context.strip_internal_snapshots('نص عادي'), 'نص عادي')
        self.assertEqual(
            context.strip_internal_snapshots({'a': [{'sourceHash': 'h', 'b': 1}]}),
            {'a': [{'b': 1}]})


if __name__ == '__main__':
    unittest.main()
