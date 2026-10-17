import copy
import base64
import json
import math
import os
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest.mock import patch

from tests.workflow.test_meeting_requirements import MeetingRequirementsTests


class VisualPlanContractBase(MeetingRequirementsTests):
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
            'boundary': {'approved': False, 'points': project['survey_coordinates']},
            'distribution': {'approved': True, 'rows': [{
                'id': 'row_1', 'building': 'Main Building', 'floor_range': '1-3',
                'component': 'Residential', 'units_per_floor': 4, 'floor_area_sqm': 120,
                'circulation': 'Separate service access',
            }]},
        }


class VisualPlanContractTests(VisualPlanContractBase):
    def test_every_plan_prompt_keeps_the_full_croquis_brief_and_constraints(self):
        module = self.application_module
        context = module._visual_concept_plan_context(self.project())
        for kind in ('site', 'uses', 'massing'):
            with self.subTest(kind=kind):
                prompt = module._visual_concept_plan_drawing_prompt(kind, context)
                self.assertIn('SUMMARY_CONTEXT_MARKER', prompt)
                self.assertIn('FULL_CONSTRAINT_MARKER', prompt)
                self.assertIn('500040', prompt)

    def test_main_facade_is_a_gated_external_slot_with_a_front_view_prompt(self):
        module = self.application_module
        self.assertIn('main_facade', module.VISUAL_CONCEPT_SLOTS)
        self.assertIn('main_facade', module.VISUAL_CONCEPT_EXTERNAL_SLOTS)
        self.assertEqual(module._visual_concept_section_requirement('main_facade'), 'plans2d')
        instruction = module._visual_concept_slot_instruction('main_facade', {
            'project_name': 'Fixed Parcel', 'slot_label': 'الواجهة الرئيسية',
            'plan_image_urls': ['/site.svg', '/uses.svg', '/massing.svg'],
        })
        self.assertIn('straight-on primary street-facing', instruction)
        self.assertIn('approved planning diagrams', instruction)
        self.assertIn('Do not make an aerial', instruction)

    def test_site_plan_interview_keeps_choices_answers_and_compacts_at_input_threshold(self):
        module = self.application_module
        first_data = {'message': 'Review the site plan.', 'plansWorkflow': {
            'siteAssistant': {'inputSignature': 'same-input'}
        }}
        first_reply = {'ready': False, 'question': 'Which side is the main vehicle entry?',
                       'choices': ['West street', 'South street'], 'memory': 'Entries remain on recorded streets.'}
        next_reply = {'ready': True, 'reply': 'The requirements are clear.',
                      'memory': 'The main vehicle entry is on the west street.'}
        with patch.object(module, '_visual_plan_site_packet',
                          return_value=({}, {}, {}, 'same-input')), \
                patch.object(module, '_visual_plan_site_call',
                             side_effect=[(first_reply, 900000), (next_reply, 10)]) as model_call:
            question = module._visual_plan_site_interview(first_data)
            self.assertEqual(question['choices'], ['West street', 'South street'])
            self.assertEqual(question['assistantState']['compactionCount'], 1)
            self.assertEqual(question['assistantState']['turns'][-1]['choices'], question['choices'])
            answer_data = {'message': 'West street', 'plansWorkflow': {
                'siteAssistant': question['assistantState']
            }}
            ready = module._visual_plan_site_interview(answer_data)
        self.assertTrue(ready['readyForGeneration'])
        self.assertEqual(ready['assistantState']['answers'], [{
            'question': first_reply['question'], 'answer': 'West street'
        }])
        self.assertEqual(ready['assistantState']['compactionCount'], 1)
        second_packet = json.loads(model_call.call_args_list[1].args[1])
        first_packet = json.loads(model_call.call_args_list[0].args[1])
        self.assertIsNotNone(first_packet['validatedProjectData'])
        self.assertTrue(second_packet['continuation'])
        self.assertIsNone(second_packet['validatedProjectData'])
        self.assertTrue(second_packet['sessionMemory'])
        self.assertEqual(second_packet['resolvedAnswers'][0]['answer'], 'West street')
        self.assertEqual(model_call.call_args_list[0].kwargs['max_tokens'], 12000)
        self.assertEqual(model_call.call_args_list[0].kwargs['reasoning_effort'], 'high')
        self.assertEqual(model_call.call_args_list[1].kwargs['max_tokens'], 6000)
        self.assertEqual(model_call.call_args_list[1].kwargs['reasoning_effort'], 'medium')

    def test_starting_site_plan_chat_analyzes_inputs_without_fabricating_a_user_message(self):
        module = self.application_module
        data = {'plansWorkflow': {'siteAssistant': {}}}
        reply = {'ready': False, 'question': 'ما جهة المدخل الرئيسي؟',
                 'choices': ['الغرب', 'الجنوب'], 'memory': 'لم يحدد المدخل الرئيسي.'}
        with patch.object(module, '_visual_plan_site_packet',
                          return_value=({'project': {'name': 'Fixed Parcel'}}, {}, {}, 'same-input')), \
                patch.object(module, '_visual_plan_site_call', return_value=(reply, 1200)) as model_call:
            result = module._visual_plan_site_interview(data)

        packet = json.loads(model_call.call_args.args[1])
        self.assertEqual(packet['latestClientMessage'], '')
        self.assertIn('begin the client interview', packet['task'])
        self.assertEqual(packet['recentTurns'], [])
        self.assertEqual(result['assistantState']['turns'], [{
            'role': 'assistant', 'text': 'ما جهة المدخل الرئيسي؟', 'choices': ['الغرب', 'الجنوب']
        }])

    def test_changed_site_plan_inputs_restart_with_the_full_project_packet(self):
        module = self.application_module
        data = {'message': 'West street', 'plansWorkflow': {'siteAssistant': {
            'inputSignature': 'old-input', 'summary': 'Old approved-context memory.',
            'pendingQuestion': 'Which side is the entry?', 'turns': [
                {'role': 'assistant', 'text': 'Which side is the entry?', 'choices': ['West', 'South']}
            ],
        }}}
        reply = {'ready': False, 'question': 'Which street is the main frontage?',
                 'choices': ['West', 'South'], 'memory': 'Use the updated approved inputs.'}
        packet = {'project': {'name': 'Updated Parcel'}, 'landAndRegulations': {'landArea': 1200}}
        with patch.object(module, '_visual_plan_site_packet',
                          return_value=(packet, {}, {}, 'new-input')), \
                patch.object(module, '_visual_plan_site_call', return_value=(reply, 100)) as model_call:
            module._visual_plan_site_interview(data)
        sent = json.loads(model_call.call_args.args[1])
        self.assertFalse(sent['continuation'])
        self.assertEqual(sent['validatedProjectData'], packet)
        self.assertEqual(sent['sessionMemory'], '')

    def test_generate_request_waits_for_answer_then_generates_without_a_second_request(self):
        module = self.application_module
        first_data = {'message': 'Generate the plan.', 'plansWorkflow': {'siteAssistant': {}}}
        followup = {'ready': False, 'generateRequested': True,
                    'question': 'Which side should be the main entrance?',
                    'choices': ['West', 'South'], 'memory': 'The client requested generation.'}
        resolved = {'ready': True, 'generateRequested': False,
                    'reply': 'The requirements are clear.',
                    'memory': 'The main entrance is on the west.'}
        generated = {'success': True, 'image': '/plan.svg', 'svgCode': '<svg/>'}
        with patch.object(module, '_visual_plan_site_packet', return_value=({}, {}, {}, 'same-input')), \
                patch.object(module, '_visual_plan_site_call', side_effect=[(followup, 10), (resolved, 10)]), \
                patch.object(module, '_visual_plan_site_generate', return_value=generated) as generate:
            first, first_status = module._visual_plan_site_assistant_execute(first_data, 'chat')
            self.assertEqual(first_status, 200)
            self.assertTrue(first['needsClarification'])
            self.assertTrue(first['generateRequested'])
            generate.assert_not_called()

            second_data = {'message': 'West', 'plansWorkflow': {'siteAssistant': first['assistantState']}}
            second, second_status = module._visual_plan_site_assistant_execute(second_data, 'chat')

        self.assertEqual(second_status, 200)
        self.assertEqual(second, generated)
        generate.assert_called_once()
        self.assertTrue(generate.call_args.args[1]['assistantState']['generateRequested'])

    def test_site_plan_context_compaction_keeps_recent_answers_and_repeats_at_each_threshold(self):
        module = self.application_module
        state = {'promptTokens': 899990, 'compactedAtTokens': 0, 'compactionCount': 0,
                 'turns': [{'text': str(index)} for index in range(10)],
                 'answers': [{'question': str(index), 'answer': str(index)} for index in range(20)]}
        module._visual_plan_site_record_tokens(state, 10)
        self.assertEqual(state['compactionCount'], 1)
        self.assertEqual(len(state['turns']), 4)
        self.assertEqual([item['question'] for item in state['answers']],
                         [str(index) for index in range(8, 20)])
        module._visual_plan_site_record_tokens(state, 900000)
        self.assertEqual(state['compactionCount'], 2)
        self.assertEqual(state['compactedAtTokens'], 1800000)

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
                'plan_site', require_distribution=True)

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
        }) as prepare_call, patch.object(module, 'persist_generated_image', return_value='/uploads/creative/ref.png'), \
                patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
            prepared = client.post('/api/visual-concept/plans-prompts',
                headers=self._headers(self.token_a),
                json={'projectData': project, 'plansWorkflow': self.workflow(project)})
        self.assertEqual(prepared.status_code, 200, prepared.get_json())
        self.assertEqual(prepare_call.call_args.kwargs.get('model'), 'google/gemini-4-argon')
        self.assertEqual(prepare_call.call_args.kwargs.get('reasoning_effort'), 'medium')
        scene = prepared.get_json()['scene']
        workflow = {**self.workflow(project), 'scene': scene}

        # The signature covers every input the scene depends on — a relabeled
        # draftId changes nothing it should care about.
        relabeled = dict(project, draftId='reloaded-draft-id')
        with patch.object(module, '_visual_plan_site_call', return_value=(
                {'ready': True, 'reply': 'The requirements are clear.'}, 100)):
            render = client.post('/api/visual-concept/site-plan-assistant',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_site', 'planAssistantAction': 'chat',
                      'message': 'Check the current site inputs.',
                      'projectData': relabeled, 'plansWorkflow': workflow})
        self.assertEqual(render.status_code, 200, render.get_json())
        self.assertTrue(render.get_json()['readyForGeneration'])

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
        with patch.object(module, '_visual_plan_site_call', return_value=(
                {'ready': True, 'reply': 'The requirements are clear.'}, 100)):
            render = client.post('/api/visual-concept/site-plan-assistant',
                headers=self._headers(self.token_a),
                json={'slotId': 'plan_site', 'planAssistantAction': 'chat',
                      'message': 'Check the current site inputs.',
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

    def test_stale_derived_site_context_is_rebased_and_resealed(self):
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
            original, _context, _reference = module._visual_plan_create_scene(data)
            stale_assistant = {
                'inputSignature': original['inputSignature'],
                'summary': 'Old summary that no longer matches the derived site program.',
                'pendingQuestion': 'Old question',
                'answers': [{'question': 'Old question', 'answer': 'Old answer'}],
                'turns': [{'role': 'assistant', 'text': 'Old question'}],
            }
            data['plansWorkflow'] = {**self.workflow(project), 'scene': original,
                                     'siteAssistant': stale_assistant}
            contract, current_context = module._visual_plan_contract(data)
            current_program = module._visual_plan_program(contract, current_context)
            changed_program = {**current_program, 'siteItems': [{
                'id': 'new-landscape', 'name': 'Landscape', 'label': 'Landscape',
                'category': 'landscape', 'kind': 'landscape', 'area': 0,
            }]}

            with patch.object(module, '_visual_plan_program', return_value=changed_program), \
                    patch.object(module, '_visual_plan_site_call', return_value=(
                        {'ready': False, 'question': 'Where should the garden be?',
                         'memory': 'Fresh context'}, 5)) as interview_call:
                response = module._visual_plan_site_interview(data)
                interview_packet = json.loads(interview_call.call_args.args[1])

        refreshed = response['scene']
        self.assertTrue(response['contextChanged'])
        self.assertFalse(interview_packet['continuation'])
        self.assertIsNotNone(interview_packet['validatedProjectData'])
        self.assertEqual(response['assistantState']['answers'], [])
        self.assertEqual(response['assistantState']['summary'], 'Fresh context')
        self.assertEqual(refreshed['siteItems'], changed_program['siteItems'])
        self.assertNotEqual(refreshed['token'], original['token'])
        self.assertEqual(data['plansWorkflow']['scene']['token'], refreshed['token'])
        self.assertEqual(refreshed['inputSignature'], original['inputSignature'])

    def test_stale_signed_scene_rebuilds_when_villa_program_expands_to_units(self):
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
            original, _context, _reference = module._visual_plan_create_scene(data)
            data['plansWorkflow'] = {**self.workflow(project), 'scene': original}
            contract, context = module._visual_plan_contract(data)
            current_program = module._visual_plan_program(contract, context)
            villa_program = {
                'siteItems': current_program['siteItems'],
                'buildings': [{
                    'id': f'unit_1_{index:03d}', 'name': 'Residential Villas',
                    'label': 'Villas', 'footprintArea': 60, 'bands': [],
                    'basementOnly': False, 'levels': 1,
                } for index in (1, 2)],
            }

            with patch.object(module, '_visual_plan_program', return_value=villa_program):
                refreshed, _contract, _context, _program = module._visual_plan_scene_from_request(data)

        self.assertEqual({item['id'] for item in refreshed['buildings']},
                         {'unit_1_001', 'unit_1_002'})
        self.assertNotEqual(refreshed['token'], original['token'])
        self.assertEqual(data['plansWorkflow']['scene']['token'], refreshed['token'])
        module.visual_plan_scene.validate_scene(refreshed, contract, villa_program)

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

        section_ids = ('coordinates', 'colors', 'components', 'access', 'landscape', 'legend')
        model_replies = [{'choices': [{'message': {'content': json.dumps(
            {'ready': True, 'reply': 'Requirements are clear.', 'memory': 'Preserve the approved layout.'})}}],
                          'usage': {'prompt_tokens': 2000, 'completion_tokens': 100}},
                         {'choices': [{'message': {'content': json.dumps({
            'clear': True, 'targetSection': 'components',
            'code': '<g id="ll-section-components"><text>Main Building</text></g>',
            'reply': 'Updated the component label.'})}}],
            'usage': {'prompt_tokens': 2000, 'completion_tokens': 100}}]
        with tempfile.TemporaryDirectory() as upload_dir:
            with patch.dict('os.environ', {'PLAN_SITE_MODEL': 'another/provider-model'}, clear=False), \
                    patch.object(module, 'UPLOADS_DIR', upload_dir), \
                    patch.object(module, 'call_openrouter_chat', side_effect=model_replies) as chat_call, \
                    patch.object(module, 'persist_generated_image',
                                 wraps=module.persist_generated_image) as persist_mock, \
                    patch.object(module, '_prepare_image_reference_for_model', return_value='ref:parcel'):
                render = client.post('/api/visual-concept/site-plan-assistant',
                    headers=self._headers(self.token_a),
                    json={'slotId': 'plan_site', 'planAssistantAction': 'generate',
                          'projectData': project, 'plansWorkflow': workflow})
                self.assertEqual(render.status_code, 200, render.get_json())
                body = render.get_json()
                self.assertTrue(body['image'].startswith('/uploads/creative/' + self.tenant_a + '/'))
                self.assertIn('.svg?', body['image'])
                image_path = body['image'].split('?', 1)[0]
                filename = image_path.rsplit('/', 1)[-1]
                self.assertTrue((Path(upload_dir) / 'creative' / self.tenant_a / filename).is_file())
                endpoint, route_values = module.app.url_map.bind('localhost').match(image_path)
                self.assertEqual(endpoint, 'static_creative_upload', (endpoint, route_values))
                with module.app.test_request_context(body['image']):
                    self.assertTrue(module._media_request_authorized(module.request.path))
                preview = client.get(body['image'])
                try:
                    self.assertEqual(preview.status_code, 200,
                                     f"{preview.get_data(as_text=True)} URL={body['image']}")
                    self.assertEqual(preview.mimetype, 'image/svg+xml')
                    svg_root = ElementTree.fromstring(preview.data)
                    svg_namespace = '{http://www.w3.org/2000/svg}'
                    self.assertEqual(svg_root.tag, svg_namespace + 'svg')
                    component_label = svg_root.find(
                        './/' + svg_namespace + 'g[@id="ll-section-components"]/' + svg_namespace + 'text')
                    self.assertEqual(component_label.text, 'Main Building')
                    for section in ('coordinates', 'access', 'landscape'):
                        group = next(item for item in svg_root.iter()
                                     if item.get('id') == 'll-section-' + section)
                        labels = [item.text for item in group.iter()
                                  if item.tag == svg_namespace + 'text' and item.text]
                        if section == 'access':
                            self.assertTrue(any('Street' in label for label in labels))
                        else:
                            self.assertFalse(labels)
                    found_ids = {element.attrib.get('id') for element in svg_root.iter()}
                    for section in section_ids:
                        self.assertIn('ll-section-' + section, found_ids)
                finally:
                    preview.close()
                before_root = ElementTree.fromstring(body['svgCode'])
                before_sections = {
                    section: ''.join(next(element for element in before_root.iter()
                                          if element.attrib.get('id') == 'll-section-' + section).itertext())
                    for section in section_ids
                }
                edit_workflow = copy.deepcopy(workflow)
                edit_workflow['siteAssistant'] = body['assistantState']
                edited = client.post('/api/visual-concept/site-plan-assistant',
                    headers=self._headers(self.token_a), json={
                        'slotId': 'plan_site', 'planAssistantAction': 'edit',
                        'message': 'Rename the component label.', 'siteSvgCode': body['svgCode'],
                        'projectData': project, 'plansWorkflow': edit_workflow,
                    })
                self.assertEqual(edited.status_code, 200, edited.get_json())
                edited_body = edited.get_json()
                self.assertEqual(edited_body['targetSection'], 'components')
                after_root = ElementTree.fromstring(edited_body['svgCode'])
                after_sections = {
                    section: ''.join(next(element for element in after_root.iter()
                                          if element.attrib.get('id') == 'll-section-' + section).itertext())
                    for section in section_ids
                }
                self.assertEqual(after_sections['components'], 'Main Building')
                for section in set(section_ids) - {'components'}:
                    self.assertEqual(after_sections[section], before_sections[section])
        self.assertEqual(render.status_code, 200, render.get_json())
        body = render.get_json()
        self.assertEqual(body['model'], 'google/gemini-4-argon')
        self.assertEqual(chat_call.call_count, 2)
        self.assertTrue(all(call.kwargs.get('model') == 'google/gemini-4-argon'
                            for call in chat_call.call_args_list))
        self.assertEqual(chat_call.call_args_list[0].kwargs.get('reasoning_effort'), 'high')
        self.assertEqual(chat_call.call_args_list[1].kwargs.get('reasoning_effort'), 'high')
        self.assertEqual(chat_call.call_args_list[0].kwargs.get('max_tokens'), 12000)
        self.assertEqual(chat_call.call_args_list[1].kwargs.get('max_tokens'), 24000)
        persisted_uri = persist_mock.call_args.args[0]
        self.assertTrue(persisted_uri.startswith('data:image/svg+xml;base64,'))
        persisted_svg = base64.b64decode(persisted_uri.split(',', 1)[1])
        ElementTree.fromstring(persisted_svg)

    def test_fixed_geometry_plans_do_not_chain_image_approvals(self):
        module = self.application_module
        project = self.project()
        data = {'projectData': project, 'plansWorkflow': self.workflow(project)}
        for kind in ('uses', 'massing'):
            with self.subTest(kind=kind):
                error = module._visual_concept_plan_workflow_error(
                    copy.deepcopy(data), 'plan_' + kind, require_distribution=True)
                self.assertIsNone(error)

    def test_visual_plan_jobs_fail_after_the_bounded_deadline(self):
        module = self.application_module
        self.assertEqual(module._VISUAL_PLAN_JOB_TIMEOUT_SECONDS, 600)
        client = self.app.test_client()
        now = module.time.time()
        running = {'status': 'running', 'success': True,
                   'createdAt': now - 599, 'deadlineAt': now + 1,
                   'updatedAt': now, 'progress': 45,
                   'todos': module._visual_plan_job_todos('render')}
        with patch.object(module, '_read_job', return_value=running):
            response = client.get('/api/visual-concept/plans-jobs/active-job',
                                  headers=self._headers(self.token_a))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['status'], 'running')
        self.assertEqual(response.get_json()['todos'][1]['status'], 'active')

        expired = {**running, 'deadlineAt': now - 1,
                   'payload': {'kind': 'site_chat'},
                   'todos': module._visual_plan_job_todos('site_chat', active_index=2),
                   'timings': {'scene_validation_ms': 1200}}
        with patch.object(module, '_read_job', return_value=expired), \
                patch.object(module, '_write_job') as write_job:
            response = client.get('/api/visual-concept/plans-jobs/expired-job',
                                  headers=self._headers(self.token_a))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['status'], 'failed')
        self.assertEqual(response.get_json()['result']['error_code'], 'PLANS_JOB_EXPIRED')
        self.assertEqual([item['status'] for item in response.get_json()['todos']],
                         ['done', 'done', 'failed', 'pending'])
        self.assertEqual(response.get_json()['timings']['scene_validation_ms'], 1200)
        persisted = write_job.call_args.args[3]
        self.assertEqual(persisted['createdAt'], expired['createdAt'])
        self.assertEqual(persisted['timings']['scene_validation_ms'], 1200)
        write_job.assert_called_once()

        section_todos = module._visual_plan_site_section_todos(
            {'coordinates': '<g/>', 'colors': '<defs/>'}, active_section='components')
        expired_sections = {**expired, 'todos': section_todos}
        with patch.object(module, '_read_job', return_value=expired_sections), \
                patch.object(module, '_write_job'):
            response = client.get('/api/visual-concept/plans-jobs/expired-svg-job',
                                  headers=self._headers(self.token_a))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual([item['label'] for item in response.get_json()['todos']],
                         [item['label'] for item in section_todos])
        self.assertEqual([item['status'] for item in response.get_json()['todos']],
                         ['done', 'done', 'failed', 'pending', 'pending', 'pending', 'pending'])

    def test_visual_plan_provider_calls_obey_the_job_deadline(self):
        module = self.application_module
        with self.app.test_request_context('/'):
            module.g.visual_plan_job_deadline = 105
            with patch.object(module.time, 'time', return_value=100):
                self.assertEqual(module._visual_plan_job_call_timeout(1200), 5)
            with patch.object(module.time, 'time', return_value=105):
                with self.assertRaises(module.visual_plan_geometry.PlanGeometryError) as raised:
                    module._visual_plan_job_call_timeout(1200)
        self.assertEqual(raised.exception.code, 'PLANS_JOB_EXPIRED')

    def test_site_chat_progress_names_the_work_actually_in_progress(self):
        module = self.application_module
        todos = module._visual_plan_job_todos('site_chat', active_index=3)
        self.assertEqual([item['label'] for item in todos], [
            'فحص بيانات الأرض والتوزيع', 'تجهيز المشهد الهندسي',
            'مراجعة الإجابات السابقة', 'تحليل المتطلبات وتحديد السؤال',
        ])
        self.assertEqual([item['status'] for item in todos], ['done', 'done', 'done', 'active'])
        self.assertNotIn('تحميل بيانات', ' '.join(item['label'] for item in todos))
        failed = module._visual_plan_job_todos('site_chat', state='failed', active_index=3)
        self.assertEqual(failed[3]['status'], 'failed')
        self.assertEqual(failed[0]['status'], 'done')
        reported = []
        with self.app.test_request_context('/'):
            module.g.visual_plan_job_kind = 'site_chat'
            module.g.visual_plan_job_progress = lambda **kwargs: reported.append(kwargs)
            module._visual_plan_report_site_chat_progress(3, 82)
            module._visual_plan_report_site_chat_timing('interview_model_ms', module.time.perf_counter() - 0.01)
        self.assertEqual(reported[0]['progress'], 82)
        self.assertEqual(reported[0]['todos'][3]['status'], 'active')
        self.assertGreaterEqual(reported[1]['timing']['interview_model_ms'], 0)

    def test_site_svg_section_progress_marks_the_active_section_and_preserves_it_on_failure(self):
        module = self.application_module
        checkpoints = {'coordinates': '<g/>', 'colors': '<defs/>'}
        todos = module._visual_plan_site_section_todos(
            checkpoints, active_section='components')
        self.assertEqual([item['status'] for item in todos],
                         ['done', 'done', 'active', 'pending', 'pending', 'pending', 'pending'])
        failed = module._visual_plan_job_terminal_todos(
            'site_chat', 'failed', current_todos=todos)
        self.assertEqual(failed[2]['label'],
                         'Current approved footprints, distinct unit labels and building names.')
        self.assertEqual([item['status'] for item in failed],
                         ['done', 'done', 'failed', 'pending', 'pending', 'pending', 'pending'])
        self.assertEqual(failed[-1]['stage'], 'site_svg_assembly')
        reported = []
        with self.app.test_request_context('/'):
            module.g.visual_plan_job_kind = 'site_generate'
            module.g.visual_plan_job_progress = lambda **kwargs: reported.append(kwargs)
            module._visual_plan_site_report_progress(42, todos, checkpoints, 'current-input')
        self.assertEqual(reported[0]['checkpoint']['svgRenderRevision'],
                         module._VISUAL_PLAN_SITE_RENDER_REVISION)
        self.assertEqual(reported[0]['checkpoint']['svgInputSignature'], 'current-input')
        self.assertEqual(reported[0]['checkpoint']['svgSections'], checkpoints)

    def test_arabic_svg_labels_are_removed_without_rejecting_the_section(self):
        module = self.application_module
        sanitized_sections = []
        fragment = (
            '<g id="ll-section-components">'
            '<rect x="10" y="20" width="30" height="40"/>'
            '<text>المبنى الرئيسي</text><text>Parking area</text>'
            '<g aria-label="المكونات"><circle cx="5" cy="5" r="2"/></g>'
            '</g>'
        )

        cleaned = module._visual_plan_site_section_fragment(
            fragment, 'components', sanitized_sections)

        self.assertIn('<rect', cleaned)
        self.assertIn('Parking area', cleaned)
        self.assertNotRegex(cleaned, r'[\u0600-\u06FF]')
        self.assertEqual(sanitized_sections, ['components'])

    def test_site_svg_checkpoints_require_current_inputs_and_render_rules(self):
        module = self.application_module
        current = {'inputSignature': 'current',
                   'renderRevision': module._VISUAL_PLAN_SITE_RENDER_REVISION, 'checkpoints': {
            'components': '<g id="ll-section-components"/>', 'unknown': '<g/>'}}
        self.assertEqual(module._visual_plan_site_reusable_checkpoints(current, 'current'), {
            'components': '<g id="ll-section-components"/>'})
        self.assertEqual(module._visual_plan_site_reusable_checkpoints(current, 'changed'), {})
        old_renderer = {**current, 'renderRevision': module._VISUAL_PLAN_SITE_RENDER_REVISION - 1}
        self.assertEqual(module._visual_plan_site_reusable_checkpoints(old_renderer, 'current'), {})

    def test_individual_villa_program_expands_every_approved_unit_with_exact_area(self):
        module = self.application_module
        contract = {'distribution': {'rows': [{
            'id': 'villa_row', 'building': 'الفلل', 'component': 'فلل سكنية',
            'floor_range': 'G+1+50% Annex', 'units_per_floor': 100,
            'floor_area_sqm': 13000, 'circulation': '',
        }]}}
        context = {'components': [{
            'id': 'villa_component', 'name': 'فلل سكنية', 'useType': 'residential',
            'units': 100, 'builtArea': 26000, 'floorRange': 'G+1+50% Annex',
        }]}

        program = module._visual_plan_program(contract, context)
        villas = program['buildings']

        self.assertEqual(len(villas), 100)
        self.assertEqual(len({villa['id'] for villa in villas}), 100)
        self.assertTrue(all(villa['label'] == 'Villas' for villa in villas))
        self.assertTrue(all(villa['levels'] == 2.5 for villa in villas))
        self.assertTrue(all(villa['footprintArea'] == 104 for villa in villas))
        self.assertTrue(all(villa['bands'][0]['units'] == 1 for villa in villas))

    def test_scene_program_ignores_distribution_rows_absent_from_current_components(self):
        module = self.application_module
        contract = {'distribution': {'rows': [
            {'id': 'current_villas', 'building': 'Main Building', 'component': 'فلل سكنية',
             'floor_range': 'G+1', 'units_per_floor': 100, 'floor_area_sqm': 26000,
             'circulation': ''},
            {'id': 'deleted_health_club', 'building': 'U Cluster', 'component': 'Health Club',
             'floor_range': 'G', 'units_per_floor': 1, 'floor_area_sqm': 600,
             'circulation': ''},
        ]}}
        context = {'components': [{
            'id': 'current_villas', 'name': 'فلل سكنية', 'useType': 'residential',
            'units': 100, 'builtArea': 26000, 'floorRange': 'G+1',
        }]}

        program = module._visual_plan_program(contract, context)

        self.assertEqual(len(program['buildings']), 100)
        self.assertNotIn('Health Club', json.dumps(program))
        self.assertNotIn('U Cluster', json.dumps(program))

    def test_short_plan_labels_translate_only_the_component_or_building_name(self):
        module = self.application_module
        self.assertEqual(module._visual_concept_plan_building_en('برج أ'), 'Tower A')
        self.assertEqual(module._visual_concept_plan_building_en('مخطط ب'), 'Plan B')
        self.assertEqual(module._visual_concept_plan_component_en('ملعب كرة'), 'Football Field')
        self.assertEqual(module._visual_concept_plan_component_en('ملعب بادل'), 'Padel Court')
        self.assertEqual(module._visual_concept_plan_component_en('فلل سكنية'), 'Villas')

    def test_site_components_are_rendered_as_individual_approved_footprints(self):
        module = self.application_module
        layout = {
            'architecturalColorLegend': [{'category': 'residential', 'color': '#B9D1EB'}],
            'buildings': [{
                'id': f'villa_{index:03d}', 'label': 'Villas', 'category': 'residential',
                'footprint': [[index * 4, 0], [index * 4 + 3, 0],
                              [index * 4 + 3, 3], [index * 4, 3]],
            } for index in range(100)],
        }

        fragment = module._visual_plan_site_component_fragment(layout)
        root = ElementTree.fromstring(fragment)

        polygons = [item for item in root if item.tag.endswith('polygon')]
        labels = [item.text for item in root if item.tag.endswith('text')]
        self.assertEqual(len(polygons), 100)
        self.assertEqual(len({item.get('data-building-id') for item in polygons}), 100)
        self.assertEqual(len(labels), 100)
        self.assertEqual(labels[:3], ['Villas', 'Villas', 'Villas'])

    def test_parcel_oriented_rectangle_shorthand_preserves_angle_and_area(self):
        module = self.application_module
        polygon = module._visual_plan_rect_polygon({'orientedRect': [20, 30, 12, 5, 27]})
        from visual_plan_geometry import signed_area
        self.assertAlmostEqual(abs(signed_area(polygon)), 60, places=8)
        edge = (polygon[0], polygon[1])
        self.assertAlmostEqual(math.degrees(math.atan2(
            edge[1][1] - edge[0][1], edge[1][0] - edge[0][0])), 27, places=8)

    def test_site_svg_layout_contains_current_short_labels_and_uses_the_full_canvas(self):
        module = self.application_module
        polygon = [[0, 0], [40, 0], [40, 30], [0, 30]]
        contract = {'geometry': {'parcels': [{'id': 'p1', 'polygon': polygon}]}}
        scene = {
            'geometry': contract['geometry'],
            'buildings': [{'id': 'b1', 'footprint': [[5, 5], [15, 5], [15, 15], [5, 15]]}],
            'openAreas': [{'id': 'a1', 'componentId': 'row2', 'kind': 'landscape',
                           'polygon': [[20, 5], [25, 5], [25, 10], [20, 10]]}],
            'entries': [],
        }
        program = {
            'buildings': [{'id': 'b1', 'label': 'Tower A (1,040 m²)',
                           'bands': [{'kind': 'ground', 'category': 'residential'}]}],
            'siteItems': [{'id': 'row2', 'label': 'Padel Court (20 x 10m)', 'category': 'amenity'}],
        }
        with patch.object(module.visual_plan_scene, 'buildable_envelopes', return_value=[]):
            layout = module._visual_plan_site_projected_layout(scene, contract, program)

        self.assertEqual(layout['viewBox'], '0 0 1600 900')
        self.assertEqual(layout['siteDrawingBounds'], [90, 150, 1000, 690])
        self.assertEqual(layout['approvedLabels'], ['Tower A', 'Padel Court'])
        self.assertEqual([item['label'] for item in layout['buildings']], ['Tower A'])
        self.assertNotIn('U Cluster', json.dumps(layout))
        self.assertNotIn('distribution', layout)
        self.assertNotIn('approvedSiteAreaSqm', layout)

    def test_site_svg_removes_unapproved_names_and_all_nonlegend_text(self):
        module = self.application_module
        raw = ('<g id="ll-section-components"><rect x="1" y="2" width="3" height="4"/>'
               '<text>Tower A</text><text>U Cluster</text><text>1,040 m2</text></g>')
        cleaned = module._visual_plan_site_section_fragment(
            raw, 'components', allowed_text=['Tower A'])
        self.assertIn('Tower A', cleaned)
        self.assertNotIn('U Cluster', cleaned)
        self.assertNotIn('1,040 m2', cleaned)

        legend = ('<g id="ll-section-legend"><text>Architectural Color</text>'
                  '<text>Health Club</text><text>Residential</text></g>')
        cleaned_legend = module._visual_plan_site_section_fragment(
            legend, 'legend', allowed_text=['Architectural Color', 'Residential'])
        self.assertIn('Architectural Color', cleaned_legend)
        self.assertIn('Residential', cleaned_legend)
        self.assertNotIn('Health Club', cleaned_legend)

_PARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_visual_plan_contract_parts')
_part_files = []
for _dirpath, _dirnames, _filenames in os.walk(_PARTS_DIR):
    _filenames.sort()
    for _filename in _filenames:
        if _filename.endswith('.py'):
            _part_files.append(os.path.join(_dirpath, _filename))
for _part_path in sorted(_part_files, key=lambda path: (os.path.basename(path), path)):
    with open(_part_path, encoding='utf-8') as _part_file:
        exec(compile(_part_file.read(), _part_path, 'exec'), globals())
try:
    del _part_path, _part_file, _part_files, _dirpath, _dirnames, _filenames, _filename
except NameError:
    pass
del _PARTS_DIR


if __name__ == '__main__':
    unittest.main()
