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

    def test_sealed_scene_survives_a_draft_relabel(self):
        """The scene token used to bind the client-minted draftId — a draft
        reload or a lazy save between prepare and render re-labelled it, and
        every scene check then failed with 'تغيرت بيانات المشهد خارج مسار
        التعديل' even though the scene and its inputs were untouched. The
        binding now stops at the input signature: the same sealed scene
        verifies after a relabel, and the first-run draft-bound shape stays
        accepted for scenes sealed before the fix."""
        module = self.application_module
        project = self.project()
        client = self.app.test_client()
        layout = json.dumps({'buildings': [{'id': 'b1',
            'footprint': [[5, 3], [15, 3], [15, 15], [5, 15]]}],
            'entries': [], 'openAreas': []})
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': layout}}]
        }), patch.object(module, 'persist_generated_image', return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            prepared = client.post('/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': self.workflow(project)})
        self.assertEqual(prepared.status_code, 200, prepared.get_json())
        scene = prepared.get_json()['scene']
        workflow = {**self.workflow(project), 'scene': scene}

        # The signature covers every input the scene depends on — a relabeled
        # draftId changes nothing it should care about.
        relabeled = dict(project, draftId='reloaded-draft-id')
        with patch.object(module, 'call_images_api', return_value='data:image/png;base64,OUT'), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/out.png'):
            render = client.post('/api/visual-concept/generate',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_site', 'prompt': 'PROMPT',
                      'projectData': relabeled, 'plansWorkflow': workflow})
        self.assertEqual(render.status_code, 200, render.get_json())
        self.assertEqual(render.get_json()['image'], '/uploads/creative/out.png')

        # Scenes sealed by the first-run draft-bound formula still verify as
        # long as the current draftId matches the one they were sealed under.
        with module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            data = {'projectData': dict(project, draftId='draft-at-seal'),
                    'plansWorkflow': self.workflow(project)}
            signature = module._visual_plan_input_signature(data)
            posted = {key: value for key, value in scene.items() if key != 'token'}
            legacy_scene = dict(scene, token=module._visual_plan_token(
                'scene', data, signature, posted, legacy=True))
        with patch.object(module, 'call_images_api', return_value='data:image/png;base64,OUT'), \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/out.png'):
            render = client.post('/api/visual-concept/generate',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_site', 'prompt': 'PROMPT',
                      'projectData': dict(project, draftId='draft-at-seal'),
                      'plansWorkflow': {**self.workflow(project), 'scene': legacy_scene}})
        self.assertEqual(render.status_code, 200, render.get_json())

        # A tampered body fails both formulas — the relabel escape is not a bypass.
        tampered = json.loads(json.dumps(scene))
        tampered['buildings'][0]['footprint'][0] = [0, 0]
        refused = client.post('/api/visual-concept/generate',
            headers=self._headers(self.token_a),
            json={'slotId': 'plan_site', 'prompt': 'PROMPT',
                  'projectData': relabeled,
                  'plansWorkflow': {**self.workflow(project), 'scene': tampered}})
        self.assertEqual(refused.status_code, 400, refused.get_json())
        self.assertEqual(refused.get_json()['error_code'], 'PLANS_SCENE_INVALID')

    def test_sealed_scene_survives_the_browser_number_roundtrip(self):
        """The client stores the scene as JS numbers and posts it back through
        JSON.stringify — JS owns no float/int distinction, so every integral
        float arrives as an int (0.0 -> 0). Every sealed scene carries a
        literal 0.0 at the parcel origin, so the byte-exact body HMAC used to
        fail every repost with PLANS_SCENE_INVALID. The token now
        canonicalizes integral floats, so a browser-round-tripped scene
        verifies while a genuinely tampered one still refuses."""
        module = self.application_module
        project = self.project()
        layout = json.dumps({'buildings': [{'id': 'b1',
            'footprint': [[5, 3], [15, 3], [15, 15], [5, 15]]}],
            'entries': [], 'openAreas': []})
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': layout}}]
        }), patch.object(module, 'persist_generated_image', return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'), \
                module.app.test_request_context():
            module.g.tenant_id = self.tenant_a
            data = {'projectData': project, 'plansWorkflow': self.workflow(project)}
            scene, _context, _reference = module._visual_plan_create_scene(data)

            def browser_roundtrip(value):
                if isinstance(value, dict):
                    return {key: browser_roundtrip(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [browser_roundtrip(item) for item in value]
                if isinstance(value, float) and value.is_integer():
                    return int(value)
                return value

            # The origin subtraction guarantees the regression path — the
            # parcel polygon always holds the exact 0.0 the browser drops.
            self.assertIn(0.0, [coord for parcel in scene['geometry']['parcels']
                                for point in parcel['polygon'] for coord in point])
            posted_scene = browser_roundtrip(scene)
            self.assertNotEqual(json.dumps(scene), json.dumps(posted_scene))

            workflow = {**self.workflow(project), 'scene': posted_scene}
            verified, _contract, _ctx, _program = module._visual_plan_scene_from_request(
                {'projectData': project, 'plansWorkflow': workflow})
            self.assertEqual(verified['token'], scene['token'])

            workflow['scene'] = browser_roundtrip(scene)
            workflow['scene']['buildings'][0]['footprint'][0] = [0, 0]
            with self.assertRaises(module.visual_plan_geometry.PlanGeometryError) as raised:
                module._visual_plan_scene_from_request({'projectData': project, 'plansWorkflow': workflow})
            self.assertEqual(raised.exception.code, 'PLANS_SCENE_INVALID')

    def test_plan_render_illustrates_the_sealed_scene_with_the_image_model(self):
        """The shipped plan artwork comes from the image model drawing the
        validated scene spec in the prompt — the PIL scene renderer never
        runs, so its output can neither ship nor steer the illustration;
        the surveyed parcel outline is the only geometry reference."""
        module = self.application_module
        project = self.project()
        client = self.app.test_client()
        layout = json.dumps({'buildings': [{'id': 'b1',
            'footprint': [[5, 3], [15, 3], [15, 15], [5, 15]]}],
            'entries': [], 'openAreas': []})
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': layout}}]
        }), patch.object(module, 'persist_generated_image', return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            prepared = client.post('/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': self.workflow(project)})
        self.assertEqual(prepared.status_code, 200, prepared.get_json())
        scene = prepared.get_json()['scene']
        workflow = {**self.workflow(project), 'scene': scene,
                    'prompts': prepared.get_json()['prompts']}

        with patch.object(module, 'call_images_api', return_value='data:image/png;base64,OUT') as image_call, \
                patch.object(module.visual_plan_renderer, 'render_plan') as pil_render, \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/plan.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            render = client.post('/api/visual-concept/generate',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_uses', 'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(render.status_code, 200, render.get_json())
        body = render.get_json()
        self.assertEqual(body['image'], '/uploads/creative/plan.png')
        self.assertEqual(body['model'], module.VISUAL_CONCEPT_IMAGE_MODEL)
        image_call.assert_called_once()
        pil_render.assert_not_called()
        sent_prompt = image_call.call_args.args[0]
        self.assertIn('DRAWING REQUESTED', sent_prompt)
        self.assertIn('true surveyed parcel boundary', sent_prompt)
        self.assertNotIn('layout render', sent_prompt)
        self.assertEqual(image_call.call_args.kwargs.get('model'), module.VISUAL_CONCEPT_IMAGE_MODEL)
        references = image_call.call_args.args[1]
        # No scene render is attached — the surveyed parcel outline is the
        # only geometry reference the illustration may trace.
        self.assertEqual(references, ['ref:parcel'])

        with patch.object(module, 'call_images_api', return_value=None), \
                patch.object(module, 'last_images_api_error', return_value=None), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            failed = client.post('/api/visual-concept/generate',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_uses', 'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(failed.status_code, 503, failed.get_json())
        self.assertEqual(failed.get_json()['error_code'], 'PLANS_PROVIDER_FAILED')

    def test_plan_site_render_generates_svg_with_argon4(self):
        """Site plan generation uses argon4 (google/gemini-4-argon) and produces SVG output."""
        module = self.application_module
        project = self.project()
        context = module._visual_concept_plan_context(project)
        prompt = module._visual_concept_plan_drawing_prompt('site', context)
        self.assertIn('SVG', prompt)
        self.assertNotIn('png', prompt.lower())

        client = self.app.test_client()
        layout = json.dumps({'buildings': [{'id': 'b1',
            'footprint': [[5, 3], [15, 3], [15, 15], [5, 15]]}],
            'entries': [], 'openAreas': []})
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': layout}}]
        }), patch.object(module, 'persist_generated_image', return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            prepared = client.post('/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': self.workflow(project)})
        self.assertEqual(prepared.status_code, 200, prepared.get_json())
        scene = prepared.get_json()['scene']
        workflow = {**self.workflow(project), 'scene': scene,
                    'prompts': prepared.get_json()['prompts']}

        raw_svg = '<svg viewBox="0 0 1600 900" width="1600" height="900" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#fff"/></svg>'
        with patch.object(module, 'call_openrouter_chat', return_value={
            'choices': [{'message': {'content': raw_svg}}]
        }) as chat_call, \
                patch.object(module, 'persist_generated_image', return_value='/uploads/creative/plan.svg') as persist_mock, \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            render = client.post('/api/visual-concept/generate',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_site', 'projectData': project, 'plansWorkflow': workflow})
        self.assertEqual(render.status_code, 200, render.get_json())
        body = render.get_json()
        self.assertEqual(body['image'], '/uploads/creative/plan.svg')
        self.assertEqual(body['model'], 'google/gemini-4-argon')
        chat_call.assert_called_once()
        self.assertEqual(chat_call.call_args.kwargs.get('model'), 'google/gemini-4-argon')
        persisted_uri = persist_mock.call_args.args[0]
        self.assertTrue(persisted_uri.startswith('data:image/svg+xml;base64,'))

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
