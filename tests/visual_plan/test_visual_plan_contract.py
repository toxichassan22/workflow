import copy
import json
import unittest
from unittest.mock import patch

from tests.workflow.test_meeting_requirements import MeetingRequirementsTests


class VisualPlanContractTests(MeetingRequirementsTests):
    def project(self):
        points = [
            {'point': '1', 'eastings': 500000, 'northings': 2000000},
            {'point': '2', 'eastings': 500040, 'northings': 2000000},
            {'point': '3', 'eastings': 500040, 'northings': 2000030},
            {'point': '4', 'eastings': 500000, 'northings': 2000030},
        ]
        return {
            'project_name': 'Fixed Parcel', 'city': 'الرياض',
            'project_idea': 'A residential building with separate service access.',
            'croquis_land_area': 1200, 'approved_financial_area': 1200,
            'approved_floor_count': 3, 'approved_coverage_ratio': 40,
            'approved_floor_area_ratio': 1.5, 'survey_coordinates': points,
            'land_and_building_summary': 'The main facade faces west. SUMMARY_CONTEXT_MARKER.',
            'regulatory_constraints': 'FULL_CONSTRAINT_MARKER: no vehicle entry from the east.',
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
            'land_documents_analysis': {'parcels': [{
                'regulatory_constraints': 'FULL_CONSTRAINT_MARKER: no vehicle entry from the east.',
                'setbacks': '5 m west; 3 m east; 3 m north; 3 m south',
                'table_floors': 3, 'coverage_ratio': 40,
            }]},
        }

    def workflow(self, project):
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

    def test_every_plan_prompt_keeps_the_full_croquis_brief_and_constraints(self):
        module = self.application_module
        context = module._visual_concept_plan_context(self.project())
        for kind in ('site', 'uses', 'massing'):
            with self.subTest(kind=kind):
                prompt = module._visual_concept_plan_drawing_prompt(kind, context)
                self.assertIn('SUMMARY_CONTEXT_MARKER', prompt)
                self.assertIn('FULL_CONSTRAINT_MARKER', prompt)
                self.assertIn('500040', prompt)

    def test_notes_cannot_bypass_server_review_with_posted_boolean_flags(self):
        module = self.application_module
        project = self.project()
        workflow = self.workflow(project)
        workflow.update(clientNotes='Build directly on the west parcel boundary.',
                        notesReview={'verified': True, 'canProceed': True})
        with patch.object(module, 'call_images_api', return_value='data:image/png;base64,AAAA') as image_call, \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/out.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            response = self.app.test_client().post('/api/visual-concept/generate',
                headers=self._headers(self.token_a), json={
                    'slotId': 'plan_site', 'prompt': 'Render the site',
                    'projectData': project, 'plansWorkflow': workflow,
                })
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'PLANS_NOTES_CHECK_REQUIRED')
        image_call.assert_not_called()

    def test_notes_acknowledgement_token_clears_the_notes_gate(self):
        """Unchecked or conflicting notes used to hard-block generation. The
        responsibility acknowledgement mints a server token bound to the exact
        input signature — it clears the gate, and a forged token still refuses."""
        module = self.application_module
        project = self.project()
        workflow = self.workflow(project)
        workflow['clientNotes'] = 'Build directly on the west parcel boundary.'
        client = self.app.test_client()

        def gate(wf):
            return module._visual_concept_plan_workflow_error(
                {'projectData': project, 'plansWorkflow': copy.deepcopy(wf)},
                'plan_site', require_boundary=True, require_distribution=True)

        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            self.assertEqual(gate(workflow)['error_code'], 'PLANS_NOTES_CHECK_REQUIRED')

        response = client.post('/api/visual-concept/plans-notes-acknowledge',
                               headers=self._headers(self.token_a),
                               json={'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 200, response.get_json())
        ack = response.get_json()['notesAck']
        self.assertTrue(ack['acknowledged'])

        workflow['notesReview'] = {'acknowledged': True,
                                   'ackSignature': ack['inputSignature'],
                                   'ackToken': ack['token']}
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            self.assertIsNone(gate(workflow))
            # The ack rides even a conflicting review — the client signed for it.
            workflow['notesReview'].update(
                verified=True, canProceed=False,
                checks=[{'index': 0, 'note': 'x', 'result': 'متعارض', 'detail': ''}])
            self.assertIsNone(gate(workflow))
            workflow['notesReview']['ackToken'] = 'forged'
            self.assertEqual(gate(workflow)['error_code'], 'PLANS_NOTES_CHECK_REQUIRED')

    def test_notes_acknowledge_requires_written_notes_and_approved_verification(self):
        project = self.project()
        client = self.app.test_client()
        missing_verification = client.post('/api/visual-concept/plans-notes-acknowledge',
            headers=self._headers(self.token_a),
            json={'projectData': project, 'plansWorkflow': {'clientNotes': 'x'}})
        self.assertEqual(missing_verification.status_code, 400)
        self.assertEqual(missing_verification.get_json()['error_code'], 'PLANS_VERIFICATION_REQUIRED')
        missing_notes = client.post('/api/visual-concept/plans-notes-acknowledge',
            headers=self._headers(self.token_a),
            json={'projectData': project, 'plansWorkflow': self.workflow(project)})
        self.assertEqual(missing_notes.status_code, 400)
        self.assertEqual(missing_notes.get_json()['error_code'], 'PLANS_NOTES_INVALID')

    def test_prepare_seals_a_deterministic_scene_when_the_model_breaks_setbacks(self):
        """The layout model answered twice with a footprint parked on the west
        boundary — inside the recorded 5 m setback — which used to surface as
        'PLANS_SETBACK_CONFLICT' after both retries. Prepare now falls back to
        deterministic placement inside the setback envelope and still seals a
        valid scene."""
        module = self.application_module
        project = self.project()
        bad_layout = json.dumps({'buildings': [{'id': 'b1',
            'footprint': [[0, 0], [10, 0], [10, 10], [0, 10]]}],
            'entries': [], 'openAreas': []})
        response_body = {'choices': [{'message': {'content': bad_layout}}]}
        with patch.object(module, 'call_openrouter_chat', return_value=response_body) as chat, \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            response = self.app.test_client().post('/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': self.workflow(project)})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(chat.call_count, 2)
        scene = response.get_json()['scene']
        self.assertEqual(len(scene['buildings']), 1)
        footprint = scene['buildings'][0]['footprint']
        self.assertAlmostEqual(abs(sum(a[0] * b[1] - b[0] * a[1]
                                       for a, b in zip(footprint, footprint[1:] + footprint[:1])) / 2),
                               120, places=4)
        self.assertGreaterEqual(min(point[0] for point in footprint), 5)
        self.assertGreaterEqual(min(point[1] for point in footprint), 3)

    def test_prepare_still_refuses_when_nothing_can_fit_the_setbacks(self):
        """A program whose footprints cannot fit inside the setback envelope
        fails with the capacity explanation instead of the model's rejection."""
        module = self.application_module
        project = self.project()
        project['approved_coverage_ratio'] = 90
        workflow = self.workflow(project)
        workflow['distribution']['rows'][0]['floor_area_sqm'] = 900
        bad_layout = json.dumps({'buildings': [{'id': 'b1',
            'footprint': [[0, 0], [10, 0], [10, 10], [0, 10]]}]})
        response_body = {'choices': [{'message': {'content': bad_layout}}]}
        with patch.object(module, 'call_openrouter_chat', return_value=response_body), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            response = self.app.test_client().post('/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(response.get_json()['error_code'], 'PLANS_SETBACK_CONFLICT')
        self.assertIn('لا تتسع', response.get_json()['error'])

    def test_fixed_geometry_plans_do_not_chain_image_approvals(self):
        module = self.application_module
        project = self.project()
        data = {'projectData': project, 'plansWorkflow': self.workflow(project)}
        for kind in ('uses', 'massing'):
            with self.subTest(kind=kind):
                error = module._visual_concept_plan_workflow_error(
                    copy.deepcopy(data), 'plan_' + kind, require_boundary=True,
                    require_distribution=True)
                self.assertIsNone(error)


if __name__ == '__main__':
    unittest.main()
