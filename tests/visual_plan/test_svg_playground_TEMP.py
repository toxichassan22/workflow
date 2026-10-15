# TEMPORARY — tests for the SVG model playground (revert with its commit).
#
# Everything AI is mocked: no provider call leaves the test process. The suite
# proves the playground fans out to exactly the 4 approved models, measures
# per-model time, sanitizes active SVG content, scores fidelity against the
# sealed scene, never touches the image model, and refuses unsealed inputs.

import copy
import unittest
from unittest.mock import patch

from tests.workflow.test_meeting_requirements import MeetingRequirementsTests


def _project():
    points = [
        {'point': '1', 'eastings': 500000, 'northings': 2000000},
        {'point': '2', 'eastings': 500040, 'northings': 2000000},
        {'point': '3', 'eastings': 500040, 'northings': 2000030},
        {'point': '4', 'eastings': 500000, 'northings': 2000030},
    ]
    return {
        'project_name': 'Playground Parcel', 'city': 'الرياض',
        'project_idea': 'A residential building with separate service access.',
        'croquis_land_area': 1200, 'approved_financial_area': 1200,
        'approved_floor_count': 3, 'approved_coverage_ratio': 40,
        'approved_floor_area_ratio': 1.5, 'survey_coordinates': points,
        'land_and_building_summary': 'The main facade faces west.',
        'regulatory_constraints': 'No vehicle entry from the east.',
        'setbacks': '5 m west; 3 m east; 3 m north; 3 m south',
        'directions_table': [
            {'direction': 'west', 'regulation_text': 'Public street 20 m wide', 'setback': 5},
            {'direction': 'east', 'regulation_text': 'Neighboring plot', 'setback': 3},
            {'direction': 'north', 'regulation_text': 'Neighboring plot', 'setback': 3},
            {'direction': 'south', 'regulation_text': 'Neighboring plot', 'setback': 3},
        ],
        'project_components_data': [
            {'name': 'Residential', 'useType': 'residential', 'units': 12, 'builtArea': 360},
        ],
    }


def _workflow(project):
    return {
        'verification': {'approved': True},
        'boundary': {'approved': True, 'points': project['survey_coordinates'],
                     'referenceUrl': '/uploads/creative/parcel.png'},
        'distribution': {'approved': True, 'rows': [{
            'id': 'row_1', 'building': 'Main Building', 'floor_range': '1-3',
            'component': 'Residential', 'units_per_floor': 4, 'floor_area_sqm': 120,
            'circulation': 'Separate service access',
        }]},
    }


def _scene():
    return {
        'version': 1,
        'geometry': {'parcels': [{'id': 'p1', 'polygon': [[0, 0], [40, 0], [40, 30], [0, 30]]}]},
        'setbacks': {'west': 5, 'east': 3, 'north': 3, 'south': 3},
        'primaryFrontage': {'direction': 'west'},
        'buildings': [{'id': 'b1', 'label': 'Tower',
                       'footprint': [[5, 5], [20, 5], [20, 25], [5, 25]],
                       'footprintArea': 300,
                       'bands': [{'kind': 'range', 'category': 'residential'}],
                       'facades': {}, 'levels': 3}],
        'openAreas': [],
        'entries': [{'id': 'main_entry', 'kind': 'main', 'buildingId': 'b1',
                     'side': 'west', 'position': 0.5}],
        'directions': [{'direction': 'west', 'street': True, 'streetWidth': 20}],
    }


class SvgPlaygroundTempTests(MeetingRequirementsTests):
    def _mock_chat(self, module):
        def fake_chat(system_prompt, user_content, **kwargs):
            model = kwargs.get('model')
            if model == 'anthropic/claude-sonnet-5.5':
                body = ('<svg viewBox="0 0 1600 900"><title>CONCEPTUAL SITE PLAN</title>'
                        '<polygon points="1,2 3,4"/><text>Tower</text>'
                        '<script>alert(1)</script></svg>')
            elif model == 'openai/gpt-6.1-sol':
                body = ('Done.\n```svg\n<svg viewBox="0 0 1600 900">'
                        '<text>CONCEPTUAL SITE PLAN</text></svg>\n```')
            elif model == 'google/gemini-4-argon':
                body = '<svg viewBox="0 0 1600 900"><rect width="10" height="10"/></svg>'
            else:
                raise RuntimeError('provider broke')
            return {'choices': [{'message': {'content': body}}]}
        return patch.object(module, 'call_openrouter_chat', side_effect=fake_chat)

    def _run(self, module, project, workflow):
        with patch.object(module, '_visual_plan_scene_from_request',
                          return_value=(_scene(), {}, {}, {})), \
                self._mock_chat(module), \
                patch.object(module, 'call_images_api') as image_call:
            response = self.app.test_client().post(
                '/api/visual-concept/plans-svg-playground',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})
        return response, image_call

    def test_playground_compares_exactly_the_four_approved_models(self):
        module = self.application_module
        self.assertEqual(tuple(module.SVG_PLAYGROUND_MODELS), (
            'anthropic/claude-sonnet-5.5', 'anthropic/claude-haiku-5.5',
            'openai/gpt-6.1-sol', 'google/gemini-4-argon'))
        project = _project()
        workflow = _workflow(project)
        response, image_call = self._run(module, project, workflow)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertTrue(body['success'])
        results = body['results']
        self.assertEqual([item['model'] for item in results], list(module.SVG_PLAYGROUND_MODELS))
        for item in results:
            with self.subTest(model=item['model']):
                for key in ('model', 'ok', 'ms', 'chars', 'score', 'svg', 'error'):
                    self.assertIn(key, item)
                self.assertIsInstance(item['ms'], int)
                self.assertGreaterEqual(item['ms'], 0)
        image_call.assert_not_called()

    def test_playground_records_success_failure_and_sanitizes_svg(self):
        module = self.application_module
        project = _project()
        response, _image_call = self._run(module, project, _workflow(project))
        by_model = {item['model']: item for item in response.get_json()['results']}
        sonnet = by_model['anthropic/claude-sonnet-5.5']
        self.assertTrue(sonnet['ok'])
        self.assertIn('Tower', sonnet['svg'])
        self.assertNotIn('<script', sonnet['svg'])
        self.assertNotIn('alert', sonnet['svg'])
        self.assertGreater(sonnet['score'], 0)
        haiku = by_model['anthropic/claude-haiku-5.5']
        self.assertFalse(haiku['ok'])
        self.assertEqual(haiku['svg'], '')
        self.assertTrue(haiku['error'])
        argon = by_model['google/gemini-4-argon']
        self.assertTrue(argon['ok'])
        self.assertLess(argon['score'], sonnet['score'])

    def test_playground_refuses_unsealed_inputs_like_render(self):
        module = self.application_module
        project = _project()
        workflow = _workflow(project)
        workflow['boundary']['approved'] = False
        with self._mock_chat(module):
            response = self.app.test_client().post(
                '/api/visual-concept/plans-svg-playground',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 400, response.get_json())

    def test_playground_page_shell_lists_no_models_and_needs_no_auth(self):
        response = self.app.test_client().get('/playground-plans-svg')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.content_type)
        self.assertIn('مقارنة موديلات SVG', response.get_data(as_text=True))

    def test_svg_helpers_extract_fences_and_strip_active_content(self):
        module = self.application_module
        raw = 'note\n```svg\n<svg><text onload="x()">hi</text></svg>\n```'
        clean = module._svg_playground_sanitize_svg(module._svg_playground_extract_svg(raw))
        self.assertIn('<svg>', clean)
        self.assertNotIn('onload', clean)
        self.assertEqual(module._svg_playground_extract_svg('no markup here'), '')
        dirty = '<svg><script>alert(1)</script><foreignObject><p>x</p></foreignObject></svg>'
        self.assertNotIn('script', module._svg_playground_sanitize_svg(dirty))
        self.assertNotIn('foreignObject', module._svg_playground_sanitize_svg(dirty))


if __name__ == '__main__':
    unittest.main()
